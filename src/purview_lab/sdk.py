"""Version-pinned compatibility boundary for the preview Purview SDK.

The package does not publicly export its standalone client. All private SDK access
is isolated here. Tests verify its actual HTTP requests, not a replacement client.
"""

from __future__ import annotations

import platform
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from types import TracebackType
from typing import Any, Literal
from uuid import uuid4

import httpx
from agent_framework_purview import PurviewRequestError, PurviewServiceError, PurviewSettings
from agent_framework_purview._client import PurviewClient
from agent_framework_purview._models import (
    Activity,
    ActivityMetadata,
    AiAgentInfo,
    ContentActivitiesRequest,
    ContentToProcess,
    DeviceMetadata,
    IntegratedAppMetadata,
    OperatingSystemSpecifications,
    PolicyLocation,
    ProcessContentRequest,
    ProcessConversationMetadata,
    ProtectedAppMetadata,
    ProtectionScopeActivities,
    ProtectionScopesRequest,
    PurviewTextContent,
)

from .config import GRAPH_BASE_URI, TenantConfig
from .errors import IntegrationError, PolicyVerificationError
from .registry import AgentSpec, disable_external_telemetry

SDK_VERSION = "1.0.0b260730"
TokenProvider = Callable[[], Awaitable[str]]
Stage = Literal["prompt", "response"]


def _remove_internal_types(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _remove_internal_types(item) for key, item in value.items() if key != "type"}
    if isinstance(value, list):
        return [_remove_internal_types(item) for item in value]
    return value


def _serialize_content(content: ContentToProcess) -> dict[str, Any]:
    raw: dict[str, Any] = _remove_internal_types(
        content.model_dump(by_alias=True, exclude_none=True, mode="json")
    )
    # This preview serializer drops datetime values rather than converting them.
    for entry, serialized in zip(content.content_entries, raw["contentEntries"], strict=True):
        for field, alias in (
            ("created_date_time", "createdDateTime"),
            ("modified_date_time", "modifiedDateTime"),
        ):
            value = getattr(entry, field)
            if value is not None:
                serialized[alias] = value.isoformat()
    return raw


class _GraphScopesRequest(ProtectionScopesRequest):
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        raw = super().model_dump(**kwargs)
        allowed = {"activities", "locations", "deviceMetadata", "integratedAppMetadata", "pivotOn"}
        return _remove_internal_types({key: value for key, value in raw.items() if key in allowed})


class _GraphProcessRequest(ProcessContentRequest):
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {"contentToProcess": _serialize_content(self.content_to_process)}


class _GraphActivityRequest(ContentActivitiesRequest):
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        raw = super().model_dump(**kwargs)
        allowed = {"id", "userId", "scopeIdentifier", "contentMetadata"}
        result = _remove_internal_types(
            {key: value for key, value in raw.items() if key in allowed}
        )
        result["contentMetadata"] = _serialize_content(self.content_to_process)
        return result


@dataclass(frozen=True)
class HttpReceipt:
    endpoint: str
    status: int
    client_request_id: str
    service_request_id: str | None
    checked_at_utc: str


@dataclass(frozen=True)
class WireReply:
    receipt: HttpReceipt
    body: dict[str, Any] | None
    etag: str | None


def _http_failure(status: int, request_id: str, retry_after: str | None) -> IntegrationError:
    advice = {
        400: "Check the user object ID, app registration, and request contract.",
        401: "Sign in again to the explicitly configured tenant.",
        402: "Have an administrator check Purview licensing and pay-as-you-go billing.",
        403: "Check Graph permissions, administrator consent, user scope, and tenant policies.",
        404: "Check that the user exists in this tenant and this API is enabled.",
        429: (
            "Microsoft throttled the request. Retry later; "
            f"Retry-After={retry_after or 'not supplied'}."
        ),
    }.get(status, "Check service availability and network/proxy configuration, then retry.")
    return IntegrationError(f"Purview HTTP {status}. {advice} Request ID: {request_id}")


class SdkSession:
    def __init__(
        self,
        config: TenantConfig,
        agent: AgentSpec,
        token_provider: TokenProvider,
        receipts: list[HttpReceipt],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if version("agent-framework-purview") != SDK_VERSION:
            raise IntegrationError(
                f"This compatibility adapter requires agent-framework-purview=={SDK_VERSION}. "
                "Restore requirements-lock.txt before using the notebook."
            )
        disable_external_telemetry()
        self.config = config
        self.agent = agent
        self.receipts = receipts
        self._transport = transport
        self._last: WireReply | None = None
        settings = PurviewSettings(
            app_name=agent.app_name,
            app_version="0.1.0",
            tenant_id=config.tenant_id,
            graph_base_uri=GRAPH_BASE_URI,
            ignore_exceptions=False,
            ignore_payment_required=False,
        )
        self._sdk = PurviewClient(token_provider, settings, timeout=30.0)

    async def __aenter__(self) -> SdkSession:
        await self._sdk.close()
        self._sdk._client = httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            event_hooks={"response": [self._capture_response]},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._sdk.close()

    async def _capture_response(self, response: httpx.Response) -> None:
        await response.aread()
        endpoint = response.request.url.path.split("/dataSecurityAndGovernance/", 1)[-1]
        request_id = response.request.headers["client-request-id"]
        receipt = HttpReceipt(
            endpoint=endpoint,
            status=response.status_code,
            client_request_id=request_id,
            service_request_id=response.headers.get("request-id"),
            checked_at_utc=datetime.now(UTC).isoformat(),
        )
        self.receipts.append(receipt)
        if response.status_code not in (200, 201, 202, 204):
            raise _http_failure(
                response.status_code, request_id, response.headers.get("retry-after")
            )
        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                raise PolicyVerificationError(
                    f"Purview returned invalid JSON. Request ID: {request_id}"
                ) from None
            if not isinstance(body, dict):
                raise PolicyVerificationError(
                    f"Purview returned an unexpected JSON shape. Request ID: {request_id}"
                )
            if body.get("error"):
                raise PolicyVerificationError(
                    f"Purview returned an error in its response body. Request ID: {request_id}"
                )
        self._last = WireReply(receipt, body, response.headers.get("etag"))

    async def _invoke(self, operation: Awaitable[object], *, allow_204: bool = False) -> WireReply:
        self._last = None
        try:
            await operation
        except PurviewRequestError:
            # The documented processContent API supports 204; this SDK release rejects it.
            if not (allow_204 and self._last and self._last.receipt.status == 204):
                raise IntegrationError(
                    "The pinned Purview SDK rejected the service response."
                ) from None
        except PurviewServiceError:
            raise IntegrationError(
                "The pinned Purview SDK could not parse the service response."
            ) from None
        except httpx.HTTPError:
            raise IntegrationError(
                "Purview could not be reached. "
                "Check connectivity, proxy/TLS configuration, and retry."
            ) from None
        if self._last is None:
            raise IntegrationError("No HTTP response was observed; connectivity is not verified.")
        return self._last

    def _location(self) -> PolicyLocation:
        return PolicyLocation(
            data_type="microsoft.graph.policyLocationApplication", value=self.config.client_id
        )

    async def compute_scopes(self) -> WireReply:
        request = _GraphScopesRequest(
            user_id=self.config.user_id,
            tenant_id=self.config.tenant_id,
            activities=ProtectionScopeActivities.UPLOAD_TEXT
            | ProtectionScopeActivities.DOWNLOAD_TEXT,
            locations=[self._location()],
            integrated_app_metadata=IntegratedAppMetadata(
                name=self.agent.app_name, version="0.1.0"
            ),
            correlation_id=str(uuid4()),
        )
        return await self._invoke(self._sdk.get_protection_scopes(request))

    def _content(
        self, text: str, stage: Stage, conversation_id: str, *, metadata_only: bool = False
    ) -> ContentToProcess:
        now = datetime.now(UTC)
        return ContentToProcess(
            content_entries=[
                ProcessConversationMetadata(
                    identifier=str(uuid4()),
                    content=None if metadata_only else PurviewTextContent(data=text),
                    name=f"{self.agent.app_name} - {stage}",
                    correlation_id=conversation_id,
                    sequence_number=0 if stage == "prompt" else 1,
                    is_truncated=False,
                    created_date_time=now,
                    modified_date_time=now,
                    agents=[AiAgentInfo(identifier=self.agent.agent_id, name=self.agent.framework)],
                )
            ],
            activity_metadata=ActivityMetadata(
                activity=Activity.UPLOAD_TEXT if stage == "prompt" else Activity.DOWNLOAD_TEXT
            ),
            device_metadata=DeviceMetadata(
                operating_system_specifications=OperatingSystemSpecifications(
                    operating_system_platform=platform.system(),
                    operating_system_version=platform.version(),
                )
            ),
            integrated_app_metadata=IntegratedAppMetadata(
                name="Six-agent Purview lab", version="0.1.0"
            ),
            protected_app_metadata=ProtectedAppMetadata(
                name=self.agent.app_name, version="0.1.0", application_location=self._location()
            ),
        )

    async def process(
        self, text: str, stage: Stage, conversation_id: str, etag: str, *, inline: bool
    ) -> WireReply:
        request = _GraphProcessRequest(
            content_to_process=self._content(text, stage, conversation_id),
            user_id=self.config.user_id,
            tenant_id=self.config.tenant_id,
            correlation_id=str(uuid4()),
            scope_identifier=etag,
            process_inline=inline,
        )
        return await self._invoke(self._sdk.process_content(request), allow_204=True)

    async def log_activity(self, stage: Stage, conversation_id: str, etag: str) -> WireReply:
        request = _GraphActivityRequest(
            user_id=self.config.user_id,
            tenant_id=self.config.tenant_id,
            content_to_process=self._content("", stage, conversation_id, metadata_only=True),
            scope_identifier=etag,
            correlation_id=str(uuid4()),
        )
        return await self._invoke(self._sdk.send_content_activities(request))
