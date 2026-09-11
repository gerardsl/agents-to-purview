"""Opt-in only: these tests send synthetic data to the configured Microsoft tenant."""

import os
from dataclasses import replace

import pytest

from purview_lab.config import TenantConfig, TenantCredential
from purview_lab.purview import ConnectedAgent
from purview_lab.registry import AGENTS

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PURVIEW_LIVE_TESTS") != "1",
        reason="Live tests are opt-in; set PURVIEW_LIVE_TESTS=1 only after reading README.",
    ),
]


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.agent_id)
async def test_live_sdk_round_trip_for_each_framework(agent):
    config = replace(TenantConfig.from_environment(), auth_mode="client_secret")
    secret = os.environ.get("PURVIEW_CLIENT_SECRET")
    assert secret, "Opt-in live tests require PURVIEW_CLIENT_SECRET; do not hard-code it."
    credential = TenantCredential(config, client_secret=secret)
    try:
        connected = ConnectedAgent(agent, config, credential.token)
        result = await connected.run("add 17 25")
        assert result.live_api_verified
        assert result.agent.answer == "42"
        assert len(result.receipts) >= 3
        assert all(receipt.status in (200, 201, 202, 204) for receipt in result.receipts)
    finally:
        await credential.close()
