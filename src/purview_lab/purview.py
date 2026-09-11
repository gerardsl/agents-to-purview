from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import httpx

from .agents.common import AgentResult, parse_prompt
from .config import TenantConfig
from .errors import IntegrationError, PolicyBlocked, PolicyVerificationError
from .registry import AgentRunner, AgentSpec
from .sdk import HttpReceipt, SdkSession, Stage, TokenProvider, WireReply

PolicyMode = Literal["evaluateInline", "evaluateOffline", "noApplicablePolicy"]


def _has_block(actions: object) -> bool:
    if not isinstance(actions, list):
        raise PolicyVerificationError("Purview policyActions must be a list.")
    blocked = False
    for action in actions:
        if not isinstance(action, dict):
            raise PolicyVerificationError("Purview returned a malformed policy action.")
        if action.get("action") == "blockAccess" or (
            action.get("action") == "restrictAccess" and action.get("restrictionAction") == "block"
        ):
            blocked = True
        else:
            raise PolicyVerificationError(
                "Purview returned an unsupported policy action. Content has not been released."
            )
    return blocked


@dataclass(frozen=True)
class ScopeSet:
    etag: str
    scopes: tuple[dict[str, Any], ...]

    @classmethod
    def from_reply(cls, reply: WireReply) -> ScopeSet:
        if reply.receipt.status != 200 or reply.body is None:
            raise PolicyVerificationError("Protection scopes did not return HTTP 200 with JSON.")
        scopes = reply.body.get("value")
        if not isinstance(scopes, list) or not all(isinstance(scope, dict) for scope in scopes):
            raise PolicyVerificationError(
                "Protection scopes did not contain the required value list."
            )
        if not reply.etag:
            raise PolicyVerificationError("Protection scopes did not include the required ETag.")
        for scope in scopes:
            if scope.get("executionMode") not in ("evaluateInline", "evaluateOffline"):
                raise PolicyVerificationError("Purview returned an unsupported execution mode.")
            activities = scope.get("activities")
            if not isinstance(activities, str) or not activities:
                raise PolicyVerificationError("A protection scope did not specify activities.")
            if not set(part.strip() for part in activities.split(",")).issubset(
                {"none", "uploadText", "downloadText", "uploadFile", "downloadFile"}
            ):
                raise PolicyVerificationError("Purview returned an unsupported activity type.")
            locations = scope.get("locations")
            if not isinstance(locations, list) or not locations:
                raise PolicyVerificationError("A protection scope did not specify locations.")
            if not all(
                isinstance(loc, dict) and isinstance(loc.get("value"), str) for loc in locations
            ):
                raise PolicyVerificationError("Purview returned a malformed scope location.")
            _has_block(scope.get("policyActions"))
        return cls(reply.etag, tuple(scopes))

    def for_stage(self, stage: Stage, client_id: str) -> tuple[PolicyMode, bool]:
        activity = "uploadText" if stage == "prompt" else "downloadText"
        mode: PolicyMode = "noApplicablePolicy"
        blocked = False
        for scope in self.scopes:
            activity_match = activity in [part.strip() for part in scope["activities"].split(",")]
            location_match = any(
                location["value"].lower() == client_id
                and location.get("@odata.type", "microsoft.graph.policyLocationApplication").lstrip(
                    "#"
                )
                == "microsoft.graph.policyLocationApplication"
                for location in scope["locations"]
            )
            if not (activity_match and location_match):
                continue
            blocked = blocked or _has_block(scope["policyActions"])
            if scope["executionMode"] == "evaluateInline":
                mode = "evaluateInline"
            elif mode != "evaluateInline":
                mode = "evaluateOffline"
        return mode, blocked


@dataclass(frozen=True)
class ContentDecision:
    mode: PolicyMode
    outcome: Literal["allowed", "acceptedWithoutVerdict", "metadataLoggedOnly"]


@dataclass(frozen=True)
class ProtectedResult:
    agent: AgentResult
    mode: Literal["offline", "live"]
    conversation_id: str
    prompt: ContentDecision
    response: ContentDecision
    receipts: tuple[HttpReceipt, ...]

    @property
    def live_api_verified(self) -> bool:
        return self.mode == "live"


class ConnectedAgent:
    def __init__(
        self,
        agent: AgentSpec,
        config: TenantConfig,
        token_provider: TokenProvider,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        runner: AgentRunner | None = None,
    ) -> None:
        self.agent = agent
        self.config = config
        self._token_provider = token_provider
        self._transport = transport
        self.mode: Literal["offline", "live"] = "offline" if transport is not None else "live"
        self._runner = runner or agent.run
        self._lock = asyncio.Lock()
        self.receipts: list[HttpReceipt] = []
        self.last_result: ProtectedResult | None = None

    async def run(self, prompt: str) -> ProtectedResult:
        parse_prompt(prompt)
        async with self._lock:
            self.receipts = []
            self.last_result = None
            conversation_id = str(uuid4())
            async with SdkSession(
                self.config,
                self.agent,
                self._token_provider,
                self.receipts,
                transport=self._transport,
            ) as sdk:
                scopes = ScopeSet.from_reply(await sdk.compute_scopes())
                incoming, scopes = await self._check(sdk, scopes, prompt, "prompt", conversation_id)
                result = await asyncio.wait_for(self._runner(prompt), timeout=30)
                outgoing, _ = await self._check(
                    sdk, scopes, result.answer, "response", conversation_id
                )
            protected = ProtectedResult(
                result, self.mode, conversation_id, incoming, outgoing, tuple(self.receipts)
            )
            self.last_result = protected
            return protected

    async def _check(
        self, sdk: SdkSession, scopes: ScopeSet, text: str, stage: Stage, conversation_id: str
    ) -> tuple[ContentDecision, ScopeSet]:
        for _ in range(2):
            mode, scope_block = scopes.for_stage(stage, self.config.client_id)
            if scope_block:
                raise PolicyBlocked(stage, conversation_id)
            if mode == "noApplicablePolicy":
                reply = await sdk.log_activity(stage, conversation_id, scopes.etag)
                if reply.receipt.status != 201 or not reply.body or not reply.body.get("id"):
                    raise PolicyVerificationError(
                        "Content activity was not confirmed with HTTP 201 and an ID."
                    )
                return ContentDecision(mode, "metadataLoggedOnly"), scopes
            reply = await sdk.process(
                text, stage, conversation_id, scopes.etag, inline=mode == "evaluateInline"
            )
            if reply.receipt.status in (202, 204):
                if mode == "evaluateInline":
                    raise PolicyVerificationError(
                        "Purview accepted the content without an inline decision. "
                        "Content has not been released."
                    )
                if reply.body:
                    raise PolicyVerificationError(
                        "An asynchronous acceptance contained an unexpected body."
                    )
                return ContentDecision(mode, "acceptedWithoutVerdict"), scopes
            if reply.receipt.status != 200 or reply.body is None:
                raise PolicyVerificationError(
                    "Content evaluation did not return a usable decision."
                )
            body = reply.body
            errors = body.get("processingErrors")
            if not isinstance(errors, list) or errors:
                raise PolicyVerificationError(
                    "Purview content processing errors prevent verification."
                )
            blocked = _has_block(body.get("policyActions"))
            state = body.get("protectionScopeState")
            if state not in ("notModified", "modified"):
                raise PolicyVerificationError(
                    "Purview did not return a recognized protection scope state."
                )
            if state == "modified":
                scopes = ScopeSet.from_reply(await sdk.compute_scopes())
                refreshed_mode, refreshed_block = scopes.for_stage(stage, self.config.client_id)
                blocked = blocked or refreshed_block
                if not blocked and mode == "evaluateOffline" and refreshed_mode == "evaluateInline":
                    continue
            if blocked:
                raise PolicyBlocked(stage, conversation_id)
            # "modified" invalidates the scope cache, not the returned content decision.
            return ContentDecision(mode, "allowed"), scopes
        raise IntegrationError("No content decision was produced after an inline policy upgrade.")
