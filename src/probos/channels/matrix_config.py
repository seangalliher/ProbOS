"""AD-806: Matrix channel adapter configuration."""

from __future__ import annotations

from pydantic import Field

from probos.channels.base import ChannelConfig


class MatrixAdapterConfig(ChannelConfig):
    """Matrix bot adapter config (AD-806).

    Persisted at ``~/.probos/channels/matrix.yaml``. Either ``access_token``
    (preferred — long-lived, set via `probos channel matrix setup`) OR
    ``user_id`` + ``password`` must be provided. The setup verb exchanges
    the password for a token and writes the token back to the config.

    v1 supports plaintext rooms only. AD-806b will add E2EE via libolm.
    """

    homeserver: str = Field(
        default="https://matrix.org",
        description="Homeserver base URL, e.g. https://matrix.org or https://your.homeserver",
    )
    user_id: str = Field(
        default="",
        description="Full Matrix ID, e.g. @yeo:matrix.org (used only for login_password setup)",
    )
    password: str = Field(
        default="",
        description="Used only by setup verb to exchange for an access_token; setup clears this after.",
    )
    access_token: str = Field(
        default="",
        description="Long-lived access token; populated by setup verb after successful login.",
    )
    auto_join_invites: bool = Field(
        default=True,
        description="Auto-accept room invites from anyone the pairing-gate approves.",
    )
    sync_timeout_ms: int = Field(
        default=25000,
        ge=1000,
        le=60000,
        description="Long-poll timeout for /sync. 25s matches the AD-803a Telegram pattern.",
    )
