"""AD-472 + AD-804: SlackAdapter — ChannelAdapter implementation for Slack.

History:
    * AD-472 v1 shipped webhook-only inbound via the ``slack-sdk``
      opt-in extra (``pip install probos[slack]``).
    * AD-804 (Wave 191) refactored the client onto a thin httpx-based
      ``SlackClient`` so the adapter works out-of-the-box with no
      additional install, added polling-mode inbound (no public URL
      required), and wired the AD-802a ``_check_pairing`` hook by
      setting ``channel_name = "slack"``. The webhook ``receive()``
      entry point is preserved for operators who want Events API.

Inbound paths:
    * Polling mode (default): ``conversations.history`` is polled per
      channel every ``config.poll_interval_s``. Each new message
      passes through the AD-802a pairing-gate then ``handle_message``.
    * Webhook mode (AD-472): the operator wires an Events API receiver
      that calls ``adapter.receive(text=..., channel_id=..., user_id=...)``.
      Both inbound paths share the same ``handle_message`` body.

Outbound:
    * ``send_response(channel_id, text)`` -> ``SlackClient.chat_post_message``.
    * ``reply_to_message_id`` (set by inbound conversion to the parent
      ``ts``) is threaded via the Slack ``thread_ts`` parameter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from probos.channels.base import (
    ChannelAdapter,
    ChannelMessage,
    PairingNotificationError,
)
from probos.channels.slack_client import SlackAPIError, SlackClient
from probos.config import SlackConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Slack adapter — polling-mode default, optional webhook receive()."""

    #: AD-802a: routes unknown senders through `runtime.pairing_service`
    channel_name = "slack"

    def __init__(
        self,
        runtime: Any,
        config: SlackConfig,
        *,
        client: SlackClient | None = None,
    ) -> None:
        super().__init__(runtime, config)
        self._slack_config = config
        # Pre-built client allowed for tests (httpx.MockTransport injection).
        self._client: SlackClient | None = client
        self._bot_user_id: str | None = None
        self._team_name: str | None = None
        # AD-804: polling-mode state.
        self._channels: list[str] = list(getattr(config, "channels", []) or [])
        self._last_seen_ts: dict[str, str] = {}
        self._poll_task: asyncio.Task[None] | None = None
        self._stop_requested = asyncio.Event()

    # Back-compat with AD-472 tests that asserted on `_web_client`.
    @property
    def _web_client(self) -> SlackClient | None:
        return self._client

    async def start(self) -> None:
        if self._started:
            return
        token = self._slack_config.bot_token
        if not token:
            logger.warning("AD-472: SlackAdapter has no bot_token; refusing to start")
            return

        if self._client is None:
            self._client = SlackClient(
                bot_token=token,
                base=getattr(self._slack_config, "api_base", "https://slack.com/api"),
            )

        try:
            identity = await self._client.auth_test()
        except SlackAPIError as exc:
            logger.error("AD-472: Slack auth_test failed: %s", exc)
            try:
                await self._client.close()
            finally:
                self._client = None
            return

        self._bot_user_id = identity.get("user_id")
        self._team_name = identity.get("team")

        # If polling is requested and no explicit channel list was given,
        # auto-discover via conversations.list. Empty discovery -> empty
        # list -> nothing polled (operator can populate later via setup).
        if getattr(self._slack_config, "poll_inbound", True) and not self._channels:
            try:
                discovered = await self._client.conversations_list()
                self._channels = [
                    c["id"] for c in discovered
                    if isinstance(c, dict) and c.get("is_member") and c.get("id")
                ]
            except SlackAPIError as exc:
                logger.warning(
                    "AD-804: conversations.list failed during start; "
                    "no channels will be polled until config supplies them: %s",
                    exc,
                )
                self._channels = []

        # Anchor offsets at "now" so polling doesn't replay history.
        now_ts = f"{time.time():.6f}"
        for ch_id in self._channels:
            self._last_seen_ts.setdefault(ch_id, now_ts)

        if getattr(self._slack_config, "poll_inbound", True) and self._channels:
            self._stop_requested.clear()
            self._poll_task = asyncio.create_task(self._poll_loop(), name="ad804-slack-poll")

        self._started = True
        logger.info(
            "AD-472/AD-804: SlackAdapter started as user=%s team=%s polling=%s channels=%d",
            self._bot_user_id, self._team_name,
            bool(self._poll_task), len(self._channels),
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self._stop_requested.set()
        task = self._poll_task
        self._poll_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("AD-804: poll task raised during shutdown", exc_info=True)
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                logger.warning("AD-804: SlackClient.close raised", exc_info=True)
            self._client = None
        self._started = False
        logger.info("AD-472/AD-804: SlackAdapter stopped")

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        if self._client is None:
            self._emit_delivery_failed(channel_id, reason="not_started")
            return
        thread_ts = kwargs.get("thread_ts")
        try:
            await self._client.chat_post_message(
                channel=channel_id,
                text=response,
                thread_ts=thread_ts if self._slack_config.default_thread_ts else None,
            )
        except SlackAPIError as exc:
            logger.warning(
                "AD-472: Slack chat_postMessage failed (channel=%s): %s",
                channel_id, exc,
            )
            self._emit_delivery_failed(channel_id, reason="api_error", detail=str(exc))

    async def receive(self, *, text: str, channel_id: str, user_id: str,
                      user_display_name: str = "", thread_ts: str | None = None) -> str:
        """AD-472 webhook entry point (called by Events API callback handler).

        Pre-AD-804 deployments wired this via an HTTP server hosting the
        Events API; new deployments default to polling-mode and never
        call this. Both paths go through ``handle_message`` so the
        AD-802a pairing-gate fires either way.
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
        try:
            return await self.handle_message(message)
        except PairingNotificationError:
            # BF-804: this is an operator-wired HTTP entry point, so a raise
            # here would surface as a 500 and invite an Events API retry.
            # Slack has no deferred acknowledgement to withhold, so keep the
            # pre-BF-804 contract and drop the message after logging it.
            logger.error(
                "BF-804: pairing instructions could not be delivered for a "
                "Slack sender in channel=%s; the message is dropped rather "
                "than answered. This path is also reached when no pairing "
                "code could be minted at all, so the sender must retry once "
                "the pairing service is reachable again -- the Captain "
                "cannot approve a code that was never created.",
                channel_id, exc_info=True,
            )
            return ""

    # ---------- AD-804 polling internals ----------

    def _convert_message(self, channel_id: str, msg: dict) -> ChannelMessage | None:
        """Filter Slack history messages to crew-eligible inbound.

        Drops: bot-posted (including our own), subtype noise
        (join/leave/etc.), messages without ``user`` or ``text``, and
        our own bot's messages. AD-804b widens to file uploads.
        """
        if not isinstance(msg, dict):
            return None
        if msg.get("subtype") in {"bot_message", "channel_join", "channel_leave"}:
            return None
        if msg.get("bot_id"):
            return None
        user = msg.get("user")
        if not isinstance(user, str) or not user:
            return None
        if self._bot_user_id and user == self._bot_user_id:
            return None
        text = msg.get("text")
        if not isinstance(text, str) or not text:
            return None
        ts = msg.get("ts")
        if not isinstance(ts, str):
            return None

        # Per-channel allow-lists (AD-472 hardening).
        cfg = self._slack_config
        if cfg.allowed_channel_ids and channel_id not in cfg.allowed_channel_ids:
            return None
        if cfg.allowed_user_ids and user not in cfg.allowed_user_ids:
            return None

        return ChannelMessage(
            text=text,
            channel_id=channel_id,
            user_id=user,
            user_display_name=user,
            reply_to_message_id=ts,
        )

    async def _process_channel(self, channel_id: str) -> None:
        """Poll one channel; dispatch new messages. Per-channel errors
        must not kill the loop (e.g., bot kicked from a channel).
        """
        assert self._client is not None
        oldest = self._last_seen_ts.get(channel_id)
        try:
            messages = await self._client.conversations_history(
                channel=channel_id, oldest=oldest, limit=20,
            )
        except SlackAPIError as exc:
            logger.warning(
                "AD-804: conversations.history(channel=%s) failed: %s",
                channel_id, exc,
            )
            return

        # Slack returns newest-first; process oldest-first.
        for msg in reversed(messages):
            ts = msg.get("ts") if isinstance(msg, dict) else None
            if isinstance(ts, str):
                if float(ts) > float(self._last_seen_ts.get(channel_id, "0")):
                    self._last_seen_ts[channel_id] = ts
            cm = self._convert_message(channel_id, msg)
            if cm is None:
                continue
            self._emit_received(channel_id=channel_id, user_id=cm.user_id, platform="slack")
            try:
                response = await self.handle_message(cm)
            except Exception:
                logger.warning(
                    "AD-804: handle_message raised for channel=%s ts=%s",
                    channel_id, ts, exc_info=True,
                )
                continue
            if response:
                await self.send_response(cm.channel_id, response, thread_ts=cm.reply_to_message_id)

    async def _poll_loop(self) -> None:
        """Round-robin poll every channel; honor stop_requested promptly."""
        try:
            while not self._stop_requested.is_set():
                for ch_id in list(self._channels):
                    if self._stop_requested.is_set():
                        break
                    await self._process_channel(ch_id)
                # Yield to event loop + sleep — same MockTransport-friendly
                # pattern as AD-803a Telegram.
                await asyncio.sleep(0)
                try:
                    await asyncio.wait_for(
                        self._stop_requested.wait(),
                        timeout=self._slack_config.poll_interval_s,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            logger.debug("AD-804: Slack polling loop cancelled")
            raise

    # ---------- event emission (preserved from AD-472) ----------

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
