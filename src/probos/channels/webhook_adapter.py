"""AD-472: WebhookAdapter -- catch-all POST /api/webhook/{channel}.

Lets unsupported platforms forward messages by POSTing JSON. Stdlib-only
(uses existing FastAPI). Verifies a shared secret header on every inbound.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.config import WebhookConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class WebhookAdapter(ChannelAdapter):
    """Generic webhook adapter -- inbound POST /api/webhook/{channel}.

    v1 outbound is a no-op: webhook is inbound-only; downstream consumers
    (Slack, Discord) own their own outbound paths. send_response is
    implemented as a logged no-op so the ABC contract is honored without
    pretending to deliver.
    """

    def __init__(self, runtime: Any, config: WebhookConfig) -> None:
        super().__init__(runtime, config)
        self._webhook_config = config

    async def start(self) -> None:
        # No persistent connection -- the API surface is the FastAPI route.
        if not self._webhook_config.shared_secret:
            logger.warning(
                "AD-472: WebhookAdapter starting WITHOUT shared_secret; "
                "any caller can post messages. Set PROBOS_WEBHOOK_SECRET."
            )
        self._started = True
        logger.info("AD-472: WebhookAdapter started")

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        # v1: webhook is inbound-only. The originating platform is responsible
        # for delivering its own response (synchronous return value from
        # the FastAPI route). No-op here, with an audit log line for honesty.
        logger.info(
            "AD-472: WebhookAdapter.send_response is a no-op in v1 "
            "(channel=%s, len=%d)", channel_id, len(response or ""),
        )

    async def receive(
        self, *, text: str, channel: str, user_id: str = "webhook",
        secret: str = "",
    ) -> str:
        """Inbound entry point (called by FastAPI route).

        Returns the runtime's response synchronously so the FastAPI route
        can echo it back to the caller.
        """
        cfg = self._webhook_config
        # Shared-secret check (real today; convention #7 no-theater)
        if cfg.shared_secret and secret != cfg.shared_secret:
            self._emit_delivery_failed(channel, reason="bad_secret")
            return ""
        if cfg.allowed_channels and channel not in cfg.allowed_channels:
            self._emit_delivery_failed(channel, reason="channel_not_allowed")
            return ""

        self._emit_received(channel=channel, user_id=user_id)
        message = ChannelMessage(
            text=text,
            channel_id=channel,
            user_id=user_id,
        )
        return await self.handle_message(message)

    def _emit_received(self, *, channel: str, user_id: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {"platform": "webhook", "channel_id": channel, "user_id": user_id},
            )
        except Exception:
            logger.debug("AD-472: emit failed", exc_info=True)

    def _emit_delivery_failed(self, channel: str, *, reason: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_DELIVERY_FAILED,
                {"platform": "webhook", "channel_id": channel, "reason": reason},
            )
        except Exception:
            logger.debug("AD-472: emit failed", exc_info=True)
