"""AD-805: Microsoft Teams channel adapter configuration.

Persisted at ``~/.probos/channels/teams.yaml``. The ``app_id`` and
``app_password`` come from the Azure Bot Service registration; treat
``app_password`` as a secret (file mode 0600 on POSIX).

v1 substrate accepts the app password directly. Full Azure AD OAuth
flow (federated identity, managed identity, certificate auth) is
AD-805a — pairs with the AD-749 M365 OAuth infrastructure once we have
real Teams traffic to validate against.
"""

from __future__ import annotations

from pydantic import Field

from probos.channels.base import ChannelConfig


class TeamsAdapterConfig(ChannelConfig):
    """Microsoft Teams Bot Framework adapter config (AD-805)."""

    app_id: str = Field(default="", description="Azure Bot Service app/client ID")
    app_password: str = Field(
        default="",
        description="Bot Service client secret (env var PROBOS_TEAMS_APP_PASSWORD)",
    )
    allowed_team_ids: list[str] = Field(
        default_factory=list,
        description="Empty = respond in all teams; populate to restrict.",
    )
    allowed_user_aads: list[str] = Field(
        default_factory=list,
        description="Empty = respond to all senders; populate with AAD object IDs to restrict.",
    )
    tenant_id: str = Field(
        default="",
        description="Optional AAD tenant restriction. Empty = multi-tenant.",
    )
    webhook_path: str = Field(
        default="/api/channels/teams/webhook",
        description="FastAPI route Bot Framework POSTs activities to. "
                    "Operator configures Bot Service to call "
                    "https://<public-host>{webhook_path}.",
    )
