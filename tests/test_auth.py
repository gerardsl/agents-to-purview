from dataclasses import replace

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError

from purview_lab.config import GRAPH_SCOPES, TenantCredential
from purview_lab.live import LiveLab
from purview_lab.offline import DEMO_CONFIG
from purview_lab.registry import AGENTS


async def test_browser_credential_is_bound_to_explicit_tenant_and_app(monkeypatch):
    calls = {}

    class FakeBrowserCredential:
        def __init__(self, **kwargs):
            calls["constructor"] = kwargs

        def get_token(self, *scopes, **kwargs):
            calls["scopes"] = scopes
            calls["token_kwargs"] = kwargs
            return AccessToken("fake-secret-token", 9999999999)

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr("purview_lab.config.InteractiveBrowserCredential", FakeBrowserCredential)
    credential = TenantCredential(DEMO_CONFIG)
    assert await credential.token() == "fake-secret-token"
    assert calls["constructor"]["tenant_id"] == DEMO_CONFIG.tenant_id
    assert calls["constructor"]["client_id"] == DEMO_CONFIG.client_id
    assert "redirect_uri" not in calls["constructor"]
    assert calls["scopes"] == GRAPH_SCOPES
    assert calls["token_kwargs"]["tenant_id"] == DEMO_CONFIG.tenant_id
    await credential.close()
    assert calls["closed"]
    with pytest.raises(RuntimeError, match="closed"):
        await credential.token()


@pytest.mark.parametrize("mode", ["interactive", "device_code", "client_secret"])
async def test_real_identity_sdk_constructor_and_cleanup_without_sign_in(mode):
    credential = TenantCredential(
        replace(DEMO_CONFIG, auth_mode=mode),
        client_secret="synthetic-secret-used-only-for-offline-construction",
    )
    await credential.close()


def test_client_secret_mode_cannot_fall_back_to_ambient_credentials():
    with pytest.raises(ValueError, match="requires a secret"):
        TenantCredential(replace(DEMO_CONFIG, auth_mode="client_secret"))


async def test_one_shared_app_authenticates_once_but_creates_six_connections(monkeypatch):
    calls = {"created": 0, "tokens": 0, "closed": 0}

    class FakeCredential:
        def __init__(self, config, **kwargs):
            calls["created"] += 1

        async def token(self):
            calls["tokens"] += 1
            return "fake-token"

        async def close(self):
            calls["closed"] += 1

    monkeypatch.setattr("purview_lab.live.TenantCredential", FakeCredential)
    lab = await LiveLab.connect({agent.agent_id: DEMO_CONFIG for agent in AGENTS})
    assert len(lab.connections) == 6
    assert calls["created"] == calls["tokens"] == 1
    assert all(connection.last_result is None for connection in lab.connections.values())
    await lab.close()
    assert calls["closed"] == 1


async def test_credentials_are_closed_when_authentication_fails(monkeypatch):
    closed = []

    class FailingCredential:
        def __init__(self, config, **kwargs):
            self.config = config

        async def token(self):
            raise ClientAuthenticationError("synthetic auth failure")

        async def close(self):
            closed.append(self.config.client_id)

    monkeypatch.setattr("purview_lab.live.TenantCredential", FailingCredential)
    with pytest.raises(ClientAuthenticationError):
        await LiveLab.connect({agent.agent_id: DEMO_CONFIG for agent in AGENTS})
    assert closed == [DEMO_CONFIG.client_id]


async def test_partial_six_agent_configuration_is_not_accepted():
    with pytest.raises(ValueError, match="exactly"):
        await LiveLab.connect({"microsoft": DEMO_CONFIG})


async def test_six_separate_registrations_get_six_explicit_credentials(monkeypatch):
    created, closed = [], []

    class FakeCredential:
        def __init__(self, config, **kwargs):
            self.config = config
            created.append(config.client_id)

        async def token(self):
            return "fake-token"

        async def close(self):
            closed.append(self.config.client_id)

    monkeypatch.setattr("purview_lab.live.TenantCredential", FakeCredential)
    configs = {
        agent.agent_id: replace(DEMO_CONFIG, client_id=f"44444444-4444-4444-8444-{index:012d}")
        for index, agent in enumerate(AGENTS, 1)
    }
    lab = await LiveLab.connect(configs)
    assert len(set(created)) == 6
    assert {item.config.client_id for item in lab.connections.values()} == set(created)
    await lab.close()
    assert set(closed) == set(created)
