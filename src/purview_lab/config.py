from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from azure.core.credentials import AccessToken
from azure.identity import (
    ClientSecretCredential,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
)

GRAPH_BASE_URI = "https://graph.microsoft.com/v1.0/"
GRAPH_SCOPES = ("https://graph.microsoft.com/.default",)
AuthMode = Literal["interactive", "device_code", "client_secret"]


def require_guid(value: str, field: str) -> str:
    try:
        parsed = UUID(value.strip())
    except (ValueError, AttributeError) as exc:
        raise ValueError(
            f"{field} must be an actual GUID from your Microsoft Entra tenant."
        ) from exc
    if parsed.int == 0:
        raise ValueError(f"{field} cannot be the all-zero placeholder GUID.")
    return str(parsed)


@dataclass(frozen=True)
class TenantConfig:
    tenant_id: str
    client_id: str
    user_id: str
    auth_mode: AuthMode = "interactive"

    def __post_init__(self) -> None:
        for field in ("tenant_id", "client_id", "user_id"):
            object.__setattr__(self, field, require_guid(getattr(self, field), field))
        if self.auth_mode not in ("interactive", "device_code", "client_secret"):
            raise ValueError("auth_mode must be interactive, device_code, or client_secret.")

    @classmethod
    def from_environment(cls) -> TenantConfig:
        names = ("PURVIEW_TENANT_ID", "PURVIEW_CLIENT_ID", "PURVIEW_USER_ID")
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise ValueError(f"Missing configuration: {', '.join(missing)}.")
        return cls(
            tenant_id=os.environ["PURVIEW_TENANT_ID"],
            client_id=os.environ["PURVIEW_CLIENT_ID"],
            user_id=os.environ["PURVIEW_USER_ID"],
        )


class TenantCredential:
    """One explicitly selected tenant/app; no ambient Azure credential fallback."""

    def __init__(self, config: TenantConfig, *, client_secret: str | None = None) -> None:
        self.config = config
        self._closed = False
        self._credential: (
            InteractiveBrowserCredential | DeviceCodeCredential | ClientSecretCredential
        )
        if config.auth_mode == "interactive":
            # Let the SDK select an available localhost callback port.
            self._credential = InteractiveBrowserCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                timeout=300,
            )
        elif config.auth_mode == "device_code":
            self._credential = DeviceCodeCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                timeout=300,
            )
        else:
            if not client_secret:
                raise ValueError("Client-secret authentication requires a secret entered securely.")
            self._credential = ClientSecretCredential(
                tenant_id=config.tenant_id,
                client_id=config.client_id,
                client_secret=client_secret,
            )

    async def token(self) -> str:
        if self._closed:
            raise RuntimeError("The credential is closed. Rerun the authentication cell.")
        token: AccessToken = await asyncio.to_thread(
            self._credential.get_token, *GRAPH_SCOPES, tenant_id=self.config.tenant_id
        )
        if not token.token:
            raise RuntimeError("Microsoft identity returned an empty access token.")
        return token.token

    async def close(self) -> None:
        if not self._closed:
            await asyncio.to_thread(self._credential.close)
            self._closed = True
