import json
from dataclasses import replace

import httpx
import pytest

from purview_lab.errors import IntegrationError
from purview_lab.offline import DEMO_CONFIG, offline_connections, offline_token
from purview_lab.purview import ConnectedAgent
from purview_lab.registry import AGENTS
from purview_lab.reporting import check_agent, require_all_verified, write_report


async def reports_for_all_six():
    return {name: await check_agent(agent) for name, agent in offline_connections().items()}


async def test_report_is_persistent_and_cannot_confuse_offline_with_live(tmp_path):
    reports = await reports_for_all_six()
    assert "LIVE TENANT NOT VERIFIED" in require_all_verified(reports, live=False)
    with pytest.raises(IntegrationError):
        require_all_verified(reports, live=True)
    path = write_report(reports, tmp_path / "results.json")
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["offline_simulation_passed"]
    assert payload["reported_agents"] == 6
    assert not payload["live_tenant_verified"]
    assert not payload["portal_ingestion_verified"]
    assert not payload["live_dlp_blocking_verified"]
    assert all(row["answer"] == "42" for row in payload["agents"])
    assert all(row["tenant_id"] == DEMO_CONFIG.tenant_id for row in payload["agents"])
    assert all(row["client_id"] == DEMO_CONFIG.client_id for row in payload["agents"])
    assert all(row["user_id"] == DEMO_CONFIG.user_id for row in payload["agents"])
    assert "offline-not-a-real-token" not in text
    assert "Authorization" not in text
    assert "add 17 25" not in text


async def test_all_six_reports_are_required():
    reports = await reports_for_all_six()
    del reports["agno"]
    with pytest.raises(IntegrationError, match="exactly the six"):
        require_all_verified(reports, live=False)


async def test_a_failed_agent_does_not_stop_other_checks_or_produce_green_report(tmp_path):
    connections = offline_connections()
    connections["autogen"] = ConnectedAgent(
        AGENTS[2],
        DEMO_CONFIG,
        offline_token,
        transport=httpx.MockTransport(lambda request: httpx.Response(403)),
    )
    reports = {name: await check_agent(agent) for name, agent in connections.items()}
    assert len(reports) == 6
    assert reports["autogen"].status == "FAILED"
    assert reports["agno"].status == "OFFLINE_SIMULATED"
    with pytest.raises(IntegrationError, match="autogen"):
        require_all_verified(reports, live=False)
    payload = json.loads(write_report(reports, tmp_path / "failed.json").read_text())
    assert not payload["live_tenant_verified"]
    assert not payload["offline_simulation_passed"]


async def test_duplicate_or_mismatched_agent_identity_is_rejected():
    reports = await reports_for_all_six()
    reports["agno"] = replace(reports["agno"], agent_id="microsoft")
    with pytest.raises(IntegrationError):
        require_all_verified(reports, live=False)
