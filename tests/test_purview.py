import json
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from purview_lab.agents.common import SAFE_PROMPT
from purview_lab.errors import IntegrationError, PolicyBlocked, PolicyVerificationError
from purview_lab.offline import BLOCK_MARKER, DEMO_CONFIG, OfflinePurviewService, offline_token
from purview_lab.purview import ConnectedAgent
from purview_lab.registry import AGENTS


def connection(service, agent=AGENTS[0], runner=None, config=DEMO_CONFIG):
    return ConnectedAgent(
        agent, config, offline_token, transport=httpx.MockTransport(service), runner=runner
    )


def assert_no_internal_sdk_fields(value):
    if isinstance(value, dict):
        assert (
            not {"type", "tenant_id", "user_id", "process_inline", "scope_identifier"}
            & value.keys()
        )
        for item in value.values():
            assert_no_internal_sdk_fields(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_internal_sdk_fields(item)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_real_sdk_requests_for_each_real_framework(agent):
    service = OfflinePurviewService()
    result = await connection(service, agent).run(SAFE_PROMPT)
    assert result.agent.answer == "42"
    assert result.mode == "offline"
    assert not result.live_api_verified
    assert result.prompt.mode == result.response.mode == "evaluateInline"
    assert len(service.requests) == len(result.receipts) == 3
    assert [receipt.status for receipt in result.receipts] == [200, 200, 200]
    assert len({receipt.client_request_id for receipt in result.receipts}) == 3
    for receipt in result.receipts:
        UUID(receipt.client_request_id)
        UUID(receipt.service_request_id)
    compute, incoming, outgoing = service.requests
    assert compute.method == incoming.method == outgoing.method == "POST"
    assert compute.url.host == incoming.url.host == outgoing.url.host == "graph.microsoft.com"
    expected_path = f"/v1.0/users/{DEMO_CONFIG.user_id}/dataSecurityAndGovernance/"
    assert str(compute.url.path) == expected_path + "protectionScopes/compute"
    assert incoming.url.path == outgoing.url.path == expected_path + "processContent"
    compute_body = json.loads(compute.content)
    assert set(compute_body) == {"activities", "locations", "integratedAppMetadata"}
    assert compute_body["activities"] == "uploadText,downloadText"
    assert compute_body["locations"] == [
        {
            "@odata.type": "microsoft.graph.policyLocationApplication",
            "value": DEMO_CONFIG.client_id,
        }
    ]
    entries = []
    for index, request in enumerate((incoming, outgoing)):
        body = json.loads(request.content)
        assert set(body) == {"contentToProcess"}
        assert_no_internal_sdk_fields(body)
        assert request.headers["Authorization"] == "Bearer offline-not-a-real-token"
        assert request.headers["If-None-Match"] == 'W/"demo-scope-1"'
        assert request.headers["Prefer"] == "evaluateInline"
        content = body["contentToProcess"]
        assert (
            content["protectedAppMetadata"]["applicationLocation"]["value"] == DEMO_CONFIG.client_id
        )
        assert content["protectedAppMetadata"]["name"] == agent.app_name
        entry = content["contentEntries"][0]
        assert entry["@odata.type"] == "microsoft.graph.processConversationMetadata"
        assert entry["content"]["@odata.type"] == "microsoft.graph.textContent"
        assert entry["content"]["data"] == (SAFE_PROMPT if index == 0 else "42")
        assert entry["agents"][0]["identifier"] == agent.agent_id
        assert entry["sequenceNumber"] == index
        assert not entry["isTruncated"]
        assert entry["createdDateTime"].endswith(("+00:00", "Z"))
        entries.append(entry)
    assert entries[0]["correlationId"] == entries[1]["correlationId"] == result.conversation_id
    assert entries[0]["identifier"] != entries[1]["identifier"]


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_blocked_input_never_reaches_any_framework(agent):
    calls = []

    async def runner(prompt):
        calls.append(prompt)
        return await agent.run(prompt)

    connected = connection(OfflinePurviewService(), agent, runner)
    with pytest.raises(PolicyBlocked) as error:
        await connected.run(f"{SAFE_PROMPT} # {BLOCK_MARKER}")
    assert error.value.stage == "prompt"
    assert calls == []
    assert connected.last_result is None
    assert len(connected.receipts) == 2


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_blocked_output_never_leaves_any_framework_wrapper(agent):
    service = OfflinePurviewService()
    service.block_response = True
    connected = connection(service, agent)
    with pytest.raises(PolicyBlocked) as error:
        await connected.run(SAFE_PROMPT)
    assert error.value.stage == "response"
    assert connected.last_result is None
    assert len(connected.receipts) == 3
    assert str(error.value) == (
        "Purview blocked the response. No blocked content was released. "
        f"Correlation ID: {error.value.correlation_id}"
    )


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500, 503, 302])
async def test_http_errors_fail_closed_without_echoing_service_content(status):
    called = []

    def handler(request):
        return httpx.Response(status, json={"error": {"message": "SENSITIVE_SERVER_ECHO"}})

    async def runner(prompt):
        called.append(prompt)
        return await AGENTS[0].run(prompt)

    with pytest.raises(IntegrationError) as error:
        await connection(handler, runner=runner).run(SAFE_PROMPT)
    assert str(status) in str(error.value)
    assert "SENSITIVE_SERVER_ECHO" not in str(error.value)
    assert not called


async def test_network_timeout_does_not_look_like_a_connection():
    def handler(request):
        raise httpx.ReadTimeout("private-detail", request=request)

    connected = connection(handler)
    with pytest.raises(IntegrationError, match="could not be reached"):
        await connected.run(SAFE_PROMPT)
    assert not connected.receipts
    assert connected.last_result is None


@pytest.mark.parametrize("status", [202, 204])
async def test_inline_requires_a_decision_even_after_http_acceptance(status):
    service = OfflinePurviewService()
    service.process_status = status
    with pytest.raises(PolicyVerificationError, match="without an inline decision"):
        await connection(service).run(SAFE_PROMPT)
    assert service.process_count == 1


@pytest.mark.parametrize("status", [202, 204])
async def test_offline_policy_acceptance_is_not_claimed_as_an_inline_verdict(status):
    service = OfflinePurviewService("evaluateOffline")
    service.process_status = status
    result = await connection(service).run(SAFE_PROMPT)
    assert result.prompt.outcome == result.response.outcome == "acceptedWithoutVerdict"
    assert result.agent.answer == "42"
    assert service.process_count == 2
    assert all("Prefer" not in request.headers for request in service.requests[1:])


async def test_policy_changes_refresh_etag_for_the_next_message():
    service = OfflinePurviewService()
    service.modified_responses = 1
    result = await connection(service).run(SAFE_PROMPT)
    assert result.agent.answer == "42"
    assert service.compute_count == 2
    process_requests = [
        request for request in service.requests if request.url.path.endswith("/processContent")
    ]
    assert [request.headers["If-None-Match"] for request in process_requests] == [
        'W/"demo-scope-1"',
        'W/"demo-scope-2"',
    ]


@pytest.mark.parametrize("mode", ["evaluateInline", "evaluateOffline"])
async def test_modified_state_refreshes_cache_without_replaying_current_content(mode):
    service = OfflinePurviewService(mode)
    service.modified_responses = 100
    result = await connection(service).run(SAFE_PROMPT)
    assert result.agent.answer == "42"
    assert service.process_count == 2
    assert service.compute_count == 3


async def test_refreshed_inline_upgrade_is_evaluated_before_running_the_agent():
    service = OfflinePurviewService("evaluateOffline")
    service.modified_responses = 100
    calls = []

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute") and service.compute_count > 1:
            body = response.json()
            body["value"][0]["executionMode"] = "evaluateInline"
            return httpx.Response(200, headers=response.headers, json=body)
        return response

    async def runner(prompt):
        calls.append(service.process_count)
        return await AGENTS[0].run(prompt)

    result = await connection(handler, runner=runner).run(SAFE_PROMPT)
    assert calls == [2]
    assert result.prompt.mode == result.response.mode == "evaluateInline"
    assert service.process_count == 3
    process_requests = [
        request for request in service.requests if request.url.path.endswith("/processContent")
    ]
    assert "Prefer" not in process_requests[0].headers
    assert all(request.headers["Prefer"] == "evaluateInline" for request in process_requests[1:])


async def test_refreshed_inline_upgrade_cannot_proceed_without_an_inline_verdict():
    service = OfflinePurviewService("evaluateOffline")
    service.modified_responses = 1

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute") and service.compute_count > 1:
            body = response.json()
            body["value"][0]["executionMode"] = "evaluateInline"
            return httpx.Response(200, headers=response.headers, json=body)
        if request.headers.get("Prefer") == "evaluateInline":
            return httpx.Response(202)
        return response

    with pytest.raises(PolicyVerificationError, match="without an inline decision"):
        await connection(handler).run(SAFE_PROMPT)
    assert service.process_count == 2


async def test_refreshed_scope_block_overrides_a_modified_allow_response():
    service = OfflinePurviewService()
    service.modified_responses = 1

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute") and service.compute_count > 1:
            body = response.json()
            body["value"][0]["policyActions"] = [
                {"action": "restrictAccess", "restrictionAction": "block"}
            ]
            return httpx.Response(200, headers=response.headers, json=body)
        return response

    with pytest.raises(PolicyBlocked):
        await connection(handler).run(SAFE_PROMPT)
    assert service.process_count == 1


async def test_a_block_in_a_modified_response_is_still_enforced():
    service = OfflinePurviewService()
    service.modified_responses = 1
    with pytest.raises(PolicyBlocked):
        await connection(service).run(f"{SAFE_PROMPT} # {BLOCK_MARKER}")
    assert service.compute_count == 2
    assert service.process_count == 1


async def test_scope_refresh_failure_does_not_release_content():
    service = OfflinePurviewService()
    service.modified_responses = 1

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute") and service.compute_count > 1:
            return httpx.Response(503)
        return response

    with pytest.raises(IntegrationError, match="503"):
        await connection(handler).run(SAFE_PROMPT)
    assert service.process_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"value": None},
        {"value": [None]},
        {"value": [{"executionMode": "unknownFutureValue"}]},
        {"value": [{"executionMode": "evaluateInline", "activities": "unknownFutureValue"}]},
        {
            "value": [
                {"executionMode": "evaluateInline", "activities": "uploadText", "locations": []}
            ]
        },
    ],
)
async def test_malformed_protection_scopes_fail_closed(body):
    def handler(request):
        return httpx.Response(200, headers={"etag": '"etag"'}, json=body)

    with pytest.raises(IntegrationError):
        await connection(handler).run(SAFE_PROMPT)


async def test_missing_etag_is_not_silently_ignored():
    def handler(request):
        return httpx.Response(200, json={"value": []})

    with pytest.raises(PolicyVerificationError, match="ETag"):
        await connection(handler).run(SAFE_PROMPT)


@pytest.mark.parametrize(
    "change",
    [
        {"processingErrors": [{"message": "CLASSIFICATION_FAILED"}]},
        {"processingErrors": None},
        {"policyActions": None},
        {"policyActions": [{"action": "unknownFutureValue"}]},
        {"protectionScopeState": "unknownFutureValue"},
    ],
)
async def test_processing_errors_and_unknown_actions_fail_closed(change):
    service = OfflinePurviewService()

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/processContent"):
            return httpx.Response(200, json={**response.json(), **change})
        return response

    with pytest.raises(IntegrationError):
        await connection(handler).run(SAFE_PROMPT)


@pytest.mark.parametrize("body", [b"", b"<html>sign in</html>", b"[]", b"null"])
async def test_empty_or_non_json_success_is_not_connectivity_proof(body):
    def handler(request):
        return httpx.Response(200, headers={"etag": '"etag"'}, content=body)

    with pytest.raises(IntegrationError):
        await connection(handler).run(SAFE_PROMPT)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_no_policy_is_reported_as_metadata_only_not_dlp_protection(agent):
    service = OfflinePurviewService(None)
    result = await connection(service, agent).run(SAFE_PROMPT)
    assert result.prompt.mode == result.response.mode == "noApplicablePolicy"
    assert result.prompt.outcome == result.response.outcome == "metadataLoggedOnly"
    assert service.process_count == 0
    assert [receipt.status for receipt in result.receipts] == [200, 201, 201]
    for request in service.requests[1:]:
        body = json.loads(request.content)
        assert_no_internal_sdk_fields(body)
        assert set(body) == {"id", "userId", "scopeIdentifier", "contentMetadata"}
        assert "content" not in body["contentMetadata"]["contentEntries"][0]


async def test_strictest_of_multiple_matching_scopes_wins():
    service = OfflinePurviewService("evaluateOffline")

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute"):
            body = response.json()
            inline = {
                **body["value"][0],
                "executionMode": "evaluateInline",
                "activities": "uploadText",
            }
            body["value"].append(inline)
            return httpx.Response(200, headers=response.headers, json=body)
        return response

    result = await connection(handler).run(SAFE_PROMPT)
    assert result.prompt.mode == "evaluateInline"
    assert result.response.mode == "evaluateOffline"


async def test_scope_level_block_is_enforced_before_model_or_content_processing():
    service = OfflinePurviewService()

    def handler(request):
        response = service(request)
        if request.url.path.endswith("/compute"):
            body = response.json()
            body["value"][0]["policyActions"] = [
                {"action": "restrictAccess", "restrictionAction": "block"}
            ]
            return httpx.Response(200, headers=response.headers, json=body)
        return response

    with pytest.raises(PolicyBlocked):
        await connection(handler).run(SAFE_PROMPT)
    assert service.process_count == 0


async def test_app_location_uses_actual_selected_client_id_not_a_name():
    config = replace(DEMO_CONFIG, client_id="44444444-4444-4444-8444-444444444444")
    service = OfflinePurviewService()
    await connection(service, config=config).run(SAFE_PROMPT)
    assert json.loads(service.requests[0].content)["locations"][0]["value"] == config.client_id


async def test_rerunning_does_not_reuse_stale_success_or_conversation_ids():
    service = OfflinePurviewService()
    connected = connection(service)
    first = await connected.run(SAFE_PROMPT)
    second = await connected.run(SAFE_PROMPT)
    assert first.conversation_id != second.conversation_id
    assert len(second.receipts) == 3
    service.process_status = 500
    with pytest.raises(IntegrationError):
        await connected.run(SAFE_PROMPT)
    assert connected.last_result is None
    assert connected.receipts[-1].status == 500
