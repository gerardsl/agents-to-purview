from __future__ import annotations

from collections.abc import Mapping
from contextlib import AsyncExitStack

from .config import TenantConfig, TenantCredential
from .purview import ConnectedAgent
from .registry import AGENTS


class LiveLab:
    def __init__(self, connections: dict[str, ConnectedAgent], resources: AsyncExitStack) -> None:
        self.connections = connections
        self._resources = resources

    @classmethod
    async def connect(
        cls, configs: Mapping[str, TenantConfig], *, secrets: Mapping[str, str] | None = None
    ) -> LiveLab:
        expected = {agent.agent_id for agent in AGENTS}
        if set(configs) != expected:
            raise ValueError(
                "Provide exactly one configuration for each of the six registered agents."
            )
        credentials: dict[tuple[str, str, str], TenantCredential] = {}
        connections: dict[str, ConnectedAgent] = {}
        async with AsyncExitStack() as resources:
            for agent in AGENTS:
                config = configs[agent.agent_id]
                key = (config.tenant_id, config.client_id, config.auth_mode)
                if key not in credentials:
                    credential = TenantCredential(
                        config, client_secret=(secrets or {}).get(config.client_id)
                    )
                    resources.push_async_callback(credential.close)
                    await credential.token()
                    credentials[key] = credential
                connections[agent.agent_id] = ConnectedAgent(agent, config, credentials[key].token)
            return cls(connections, resources.pop_all())

    async def close(self) -> None:
        await self._resources.aclose()
