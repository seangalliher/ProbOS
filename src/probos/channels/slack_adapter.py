"""AD-472: SlackAdapter -- ChannelAdapter implementation for Slack.

OPT-IN: requires `pip install probos[slack]` (slack-sdk dependency).

v1 supports:
  - Inbound: events_api callback handler via Slack's Events API
  - Outbound: chat.postMessage via slack-sdk WebClient
  - Threaded replies (thread_ts)
  - User identity mapping (slack user_id -> ProbOS callsign via slack_user_map config)
"""

from __future__ import annotations

import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.config import SlackConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack adapter using slack-sdk's AsyncWebClient.

    Requires `slack-sdk` (opt-in: `uv sync --extra slack`).
    """

    def __init__(self, runtime: Any, config: SlackConfig) -> None:
        super().__init__(runtime, config)
        self._slack_config = config
        self._web_client: Any = None  # slack_sdk.web.async_client.AsyncWebClient

    async def start(self) -> None:
        try:
            from slack_sdk.web.async_client import AsyncWebClient
        except ImportError:
            logger.error(
                "AD-472: slack-sdk not installed; run `uv sync --extra slack`. "
                "SlackAdapter disabled."
            )
            return

        token = self._slack_config.bot_token
        if not token:
            logger.warning(
                "AD-472: SlackAdapter has no bot_token; refusing to start"
            )
            return

        self._web_client = AsyncWebClient(token=token)
        # Verify auth (real-work check, not theater)
        try:
            response = await self._web_client.auth_test()
            if not response.get("ok"):
                logger.error("AD-472: Slack auth_test failed: %s", response)
                self._web_client = None
                return
        except Exception:
            logger.error("AD-472: Slack auth_test error", exc_info=True)
            self._web_client = None
            return

        self._started = True
        logger.info("AD-472: SlackAdapter started (auth_test ok)")

    async def stop(self) -> None:
        self._web_client = None
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        if self._web_client is None:
            self._emit_delivery_failed(channel_id, reason="not_started")
            return
        thread_ts = kwargs.get("thread_ts")
        try:
            await self._web_client.chat_postMessage(
                channel=channel_id,
                text=response,
                thread_ts=thread_ts if self._slack_config.default_thread_ts else None,
            )
        except Exception as exc:
            logger.warning(
                "AD-472: Slack chat_postMessage failed (channel=%s)", channel_id,
                exc_info=True,
            )
            self._emit_delivery_failed(channel_id, reason="api_error", detail=str(exc))

    async def receive(self, *, text: str, channel_id: str, user_id: str,
                      user_display_name: str = "", thread_ts: str | None = None) -> str:
        """Inbound entry point (called by Slack events_api callback handler).

        Verifies allowed_channel_ids / allowed_user_ids, emits
        CHANNEL_MESSAGE_RECEIVED, then routes through handle_message.
        """
        cfg = self._slack_config
        if cfg.allowed_channel_ids and channel_id not in cfg.allowed_channel_ids:
            return ""
        if cfg.allowed_user_ids and user_id not in cfg.allowed_user_ids:
            return ""

        self._emit_received(channel_id=channel_id, user_id=user_id, platform="slack")
        message = ChannelMessage(
            text=text,
            channel_id=channel_id,
            user_id=user_id,
            user_display_name=user_display_name,
            reply_to_message_id=thread_ts,
        )
        return await self.handle_message(message)

    def _emit_received(self, *, channel_id: str, user_id: str, platform: str) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_MESSAGE_RECEIVED,
                {"platform": platform, "channel_id": channel_id, "user_id": user_id},
            )
        except Exception:
            logger.debug("AD-472: CHANNEL_MESSAGE_RECEIVED emit failed", exc_info=True)

    def _emit_delivery_failed(
        self, channel_id: str, *, reason: str, detail: str = "",
    ) -> None:
        rt = self.runtime
        if rt is None or not hasattr(rt, "emit_event"):
            return
        try:
            rt.emit_event(
                EventType.CHANNEL_DELIVERY_FAILED,
                {
                    "platform": "slack",
                    "channel_id": channel_id,
                    "reason": reason,
                    "detail": detail[:200] if detail else "",
                },
            )
        except Exception:
            logger.debug("AD-472: CHANNEL_DELIVERY_FAILED emit failed", exc_info=True)
