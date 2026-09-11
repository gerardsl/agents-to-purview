"""Clearly labeled, HTTP-boundary simulation; never authenticates to a tenant."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx

from .config import TenantConfig
from .purview import ConnectedAgent
from .registry import AGENTS

DEMO_CONFIG = TenantConfig(
    tenant_id="11111111-1111-4111-8111-111111111111",
    client_id="22222222-2222-4222-8222-222222222222",
    user_id="33333333-3333-4333-8333-333333333333",
)
BLOCK_MARKER = "PURVIEW_LAB_BLOCK"


async def offline_token() -> str:
    return "offline-not-a-real-token"


class OfflinePurviewService:
    def __init__(self, execution_mode: str | None = "evaluateInline") -> None:
        self.execution_mode = execution_mode
        self.requests: list[httpx.Request] = []
        self.compute_count = 0
        self.process_count = 0
        self.block_response = False
        self.modified_responses = 0
        self.process_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = json.loads(request.content)
        headers = {
            "request-id": str(uuid4()),
            "client-request-id": request.headers["client-request-id"],
        }
        if request.url.path.endswith("/protectionScopes/compute"):
            self.compute_count += 1
            headers["etag"] = f'W/"demo-scope-{self.compute_count}"'
            scopes = []
            if self.execution_mode:
                scopes = [
                    {
                        "activities": "uploadText,downloadText",
                        "executionMode": self.execution_mode,
                        "locations": payload["locations"],
                        "policyActions": [],
                    }
                ]
            return httpx.Response(200, headers=headers, json={"value": scopes})
        if request.url.path.endswith("/processContent"):
            self.process_count += 1
            if self.process_status in (202, 204):
                return httpx.Response(self.process_status, headers=headers)
            content = payload["contentToProcess"]
            activity = content["activityMetadata"]["activity"]
            text = content["contentEntries"][0]["content"]["data"]
            block = BLOCK_MARKER in text or (self.block_response and activity == "downloadText")
            actions = (
                [
                    {
                        "@odata.type": "#microsoft.graph.restrictAccessAction",
                        "action": "restrictAccess",
                        "restrictionAction": "block",
                    }
                ]
                if block
                else []
            )
            state = "modified" if self.process_count <= self.modified_responses else "notModified"
            return httpx.Response(
                self.process_status,
                headers=headers,
                json={
                    "protectionScopeState": state,
                    "policyActions": actions,
                    "processingErrors": [],
                },
            )
        if request.url.path.endswith("/activities/contentActivities"):
            return httpx.Response(201, headers=headers, json={"id": str(uuid4())})
        return httpx.Response(404, headers=headers, json={"error": {"code": "UnknownDemoEndpoint"}})


def offline_connections() -> dict[str, ConnectedAgent]:
    return {
        agent.agent_id: ConnectedAgent(
            agent,
            DEMO_CONFIG,
            offline_token,
            transport=httpx.MockTransport(OfflinePurviewService()),
        )
        for agent in AGENTS
    }
