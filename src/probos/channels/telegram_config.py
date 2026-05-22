"""AD-803a: Telegram adapter configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from probos.channels.base import ChannelConfig


class TelegramAdapterConfig(ChannelConfig):
    """Telegram bot adapter config (AD-803a).

    Persisted at ``~/.probos/channels/telegram.yaml``. The token is the
    operator-issued Bot Father token; treat as a secret (file mode 0600
    on POSIX).
    """

    token: str = Field(default="", description="Bot Father token (HTTP API)")
    polling_timeout_s: int = Field(
        default=25,
        ge=1,
        le=50,
        description="Long-polling timeout for getUpdates (max 50s per Bot API)",
    )
    allowed_updates: list[str] = Field(
        default_factory=lambda: ["message"],
        description="Update types to receive. v1 ships text-message-only; "
                    "AD-803b adds 'callback_query', 'edited_message', etc.",
    )
    api_base: str = Field(
        default="https://api.telegram.org",
        description="Override only for testing — defaults to the canonical Bot API host.",
    )
