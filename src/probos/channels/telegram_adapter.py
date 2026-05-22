"""AD-803a: Telegram channel adapter (polling mode).

Substrate-only v1 — text-message DMs in/out, AD-802a pairing-gate
enforced for unknown senders. Defers to AD-803b: webhook mode, media
attachments (photo / voice / document), Whisper STT for voice memos,
outbound artifact replies.

Long-polling loop:
    Calls ``TelegramClient.get_updates(offset=…, timeout=N)`` in a tight
    async loop; each returned update advances ``offset`` past
    ``update_id`` so the Bot API drops the message from its server-side
    queue.

Outbound:
    ``send_response(channel_id, text)`` -> ``TelegramClient.send_message``.
    ``channel_id`` is the Telegram ``chat.id`` rendered as a string.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.channels.telegram_client import TelegramAPIError, TelegramClient
from probos.channels.telegram_config import TelegramAdapterConfig

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """Polling-mode Telegram adapter.

    Lifecycle:
        await adapter.start()  -> connects, validates token via getMe,
                                  spawns polling task.
        await adapter.stop()   -> cancels polling, awaits the task,
                                  closes the http client.
    """

    channel_name = "telegram"

    def __init__(
        self,
        runtime: Any,
        config: TelegramAdapterConfig,
        *,
        client: TelegramClient | None = None,
    ) -> None:
        super().__init__(runtime, config)
        self._tg_config = config
        # Caller-injected client takes precedence (lets tests use a MockTransport).
        self._client = client or TelegramClient(
            token=config.token,
            base=config.api_base,
        )
        self._offset: int | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._stop_requested = asyncio.Event()
        self._bot_username: str | None = None

    async def start(self) -> None:
        if self._started:
            return
        me = await self._client.get_me()
        self._bot_username = me.get("username") if isinstance(me, dict) else None
        logger.info(
            "AD-803a: Telegram adapter started as @%s",
            self._bot_username or "<unknown>",
        )
        self._stop_requested.clear()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="ad803a-telegram-poll")
        self._started = True

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
                logger.warning("AD-803a: poll task raised during shutdown", exc_info=True)
        try:
            await self._client.close()
        except Exception:
            logger.warning("AD-803a: TelegramClient.close raised", exc_info=True)
        self._started = False
        logger.info("AD-803a: Telegram adapter stopped")

    async def send_response(self, channel_id: str, response: str, **kwargs: Any) -> None:
        """Send a text reply to the Telegram chat.

        ``channel_id`` is the str representation of ``chat.id``; we cast
        back to int when numeric so the Bot API doesn't reject it.
        """
        if not response:
            return
        target: int | str
        try:
            target = int(channel_id)
        except (TypeError, ValueError):
            target = channel_id
        reply_id = kwargs.get("reply_to_message_id")
        try:
            await self._client.send_message(
                chat_id=target,
                text=response,
                reply_to_message_id=int(reply_id) if reply_id else None,
            )
        except TelegramAPIError as exc:
            logger.warning(
                "AD-803a: send_message to chat=%s failed: %s",
                channel_id, exc,
            )

    # ---------- internals ----------

    def _convert_update(self, update: dict) -> ChannelMessage | None:
        """Filter to text DMs; return None for everything else (v1 scope).

        AD-803b widens this to photo / voice / document. For v1 we log
        and drop non-text messages with a hint so operators know they
        landed.
        """
        if not isinstance(update, dict):
            return None
        msg = update.get("message")
        if not isinstance(msg, dict):
            return None
        text = msg.get("text")
        if not isinstance(text, str) or not text:
            # AD-803b will handle photo / voice / document here.
            logger.debug(
                "AD-803a: skipping non-text update %s (keys=%s); AD-803b will handle media",
                msg.get("message_id"), sorted(msg.keys()),
            )
            return None

        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        chat_id = chat.get("id")
        from_id = sender.get("id")
        if chat_id is None or from_id is None:
            return None

        display = (
            sender.get("username")
            or " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
            or str(from_id)
        )
        return ChannelMessage(
            text=text,
            channel_id=str(chat_id),
            user_id=str(from_id),
            user_display_name=display,
            reply_to_message_id=str(msg["message_id"]) if "message_id" in msg else None,
        )

    async def _process_update(self, update: dict) -> None:
        """Convert + dispatch a single update. Errors here MUST NOT kill
        the polling loop — log and move on.
        """
        message = self._convert_update(update)
        if message is None:
            return
        try:
            response = await self.handle_message(message)
        except Exception:
            logger.warning(
                "AD-803a: handle_message raised for update=%s",
                update.get("update_id"), exc_info=True,
            )
            return
        if response:
            await self.send_response(message.channel_id, response)

    async def _poll_loop(self) -> None:
        """Long-polling main loop. Runs until ``stop()`` cancels it.

        Failure handling: transport errors back off briefly so a flaky
        network doesn't spin the loop. Authoritative failures (invalid
        token, etc.) raise once and exit the loop — the operator sees
        the WARN in the journal.
        """
        backoff_s = 1.0
        max_backoff_s = 30.0
        try:
            while not self._stop_requested.is_set():
                try:
                    updates = await self._client.get_updates(
                        offset=self._offset,
                        timeout=self._tg_config.polling_timeout_s,
                        allowed_updates=self._tg_config.allowed_updates,
                    )
                except TelegramAPIError as exc:
                    logger.warning(
                        "AD-803a: getUpdates failed (will retry in %.1fs): %s",
                        backoff_s, exc,
                    )
                    await asyncio.sleep(backoff_s)
                    backoff_s = min(backoff_s * 2, max_backoff_s)
                    continue

                backoff_s = 1.0  # reset on any successful round-trip
                for update in updates:
                    update_id = update.get("update_id") if isinstance(update, dict) else None
                    if isinstance(update_id, int):
                        # Advance offset PAST this update so the Bot API
                        # drops it from the server-side queue.
                        self._offset = update_id + 1
                    await self._process_update(update)
                # Yield to the event loop between iterations. Production
                # `get_updates` makes a real HTTPS request and yields
                # naturally, but mocked transports (httpx.MockTransport
                # in tests) complete synchronously — without an explicit
                # yield, `task.cancel()` can't deliver `CancelledError`
                # and `stop()` hangs forever.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.debug("AD-803a: polling loop cancelled")
            raise
