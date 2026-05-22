"""AD-806: Matrix channel adapter (sync-loop, no libolm, plaintext rooms).

Substrate-only v1 — long-polls ``/sync`` for inbound events,
dispatches via AD-802a pairing-gate + AD-472 ``ChannelAdapter.handle_message``,
replies via the standard ``send_message`` flow. Defers E2EE rooms to
AD-806b (requires libolm or python-olm; both have install complexity).

Per-room offset bookkeeping is implicit: Matrix's ``/sync`` returns a
``next_batch`` token; we feed it back on the next call. The first
sync uses ``since=None`` which returns the current snapshot — anchored
state, no replay of history.

Plaintext-only: messages with ``content.msgtype != "m.text"`` and
events in encrypted rooms (``m.room.encrypted``) are skipped with a
debug log pointing at AD-806b.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.channels.matrix_client import MatrixAPIError, MatrixClient
from probos.channels.matrix_config import MatrixAdapterConfig

logger = logging.getLogger(__name__)


class MatrixAdapter(ChannelAdapter):
    """Matrix adapter (plaintext rooms, sync-loop inbound)."""

    channel_name = "matrix"

    def __init__(
        self,
        runtime: Any,
        config: MatrixAdapterConfig,
        *,
        client: MatrixClient | None = None,
    ) -> None:
        super().__init__(runtime, config)
        self._matrix_config = config
        self._client = client or MatrixClient(
            homeserver=config.homeserver,
            access_token=config.access_token or None,
        )
        self._sync_token: str | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._stop_requested = asyncio.Event()
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        if self._started:
            return
        if not self._matrix_config.access_token:
            logger.warning(
                "AD-806: MatrixAdapter has no access_token; run "
                "`probos channel matrix setup` first",
            )
            return
        try:
            self._bot_user_id = await self._client.whoami()
        except MatrixAPIError as exc:
            logger.error("AD-806: whoami failed: %s", exc)
            await self._client.close()
            return

        logger.info("AD-806: MatrixAdapter started as %s", self._bot_user_id)
        self._stop_requested.clear()
        self._sync_task = asyncio.create_task(self._sync_loop(), name="ad806-matrix-sync")
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        self._stop_requested.set()
        task = self._sync_task
        self._sync_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("AD-806: sync task raised during shutdown", exc_info=True)
        try:
            await self._client.close()
        except Exception:
            logger.warning("AD-806: MatrixClient.close raised", exc_info=True)
        self._started = False
        logger.info("AD-806: MatrixAdapter stopped")

    async def send_response(self, channel_id: str, response: str, **kwargs: Any) -> None:
        if not response:
            return
        try:
            await self._client.send_message(channel_id, response)
        except MatrixAPIError as exc:
            logger.warning(
                "AD-806: send_message to room=%s failed: %s",
                channel_id, exc,
            )

    # ---------- internals ----------

    def _convert_event(self, room_id: str, event: dict) -> ChannelMessage | None:
        """Filter a /sync timeline event to a crew-eligible ChannelMessage."""
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        if event_type == "m.room.encrypted":
            # AD-806b will handle E2EE.
            logger.debug(
                "AD-806: skipping encrypted event in room=%s (AD-806b will handle E2EE)",
                room_id,
            )
            return None
        if event_type != "m.room.message":
            return None
        sender = event.get("sender")
        if not isinstance(sender, str) or not sender:
            return None
        if self._bot_user_id and sender == self._bot_user_id:
            return None  # our own messages echo back via /sync
        content = event.get("content") or {}
        if not isinstance(content, dict):
            return None
        if content.get("msgtype") != "m.text":
            # AD-806b can widen to m.image / m.audio / m.file.
            return None
        body = content.get("body")
        if not isinstance(body, str) or not body:
            return None
        event_id = event.get("event_id")
        return ChannelMessage(
            text=body,
            channel_id=room_id,
            user_id=sender,
            user_display_name=sender,
            reply_to_message_id=str(event_id) if event_id else None,
        )

    async def _process_sync_payload(self, payload: dict) -> None:
        """Walk the rooms.join.<room>.timeline events; dispatch each."""
        rooms = payload.get("rooms", {}) if isinstance(payload, dict) else {}
        join_rooms = rooms.get("join", {}) if isinstance(rooms, dict) else {}
        invite_rooms = rooms.get("invite", {}) if isinstance(rooms, dict) else {}

        # Auto-accept invites if configured (pairing-gate still applies on
        # the first message from the inviting user).
        if self._matrix_config.auto_join_invites and isinstance(invite_rooms, dict):
            for room_id in list(invite_rooms.keys()):
                try:
                    await self._client.join_room(room_id)
                    logger.info("AD-806: auto-joined invited room %s", room_id)
                except MatrixAPIError as exc:
                    logger.warning(
                        "AD-806: failed to auto-join room=%s: %s",
                        room_id, exc,
                    )

        if not isinstance(join_rooms, dict):
            return

        for room_id, room_data in join_rooms.items():
            timeline = room_data.get("timeline", {}) if isinstance(room_data, dict) else {}
            events = timeline.get("events", []) if isinstance(timeline, dict) else []
            if not isinstance(events, list):
                continue
            for event in events:
                cm = self._convert_event(room_id, event)
                if cm is None:
                    continue
                try:
                    response = await self.handle_message(cm)
                except Exception:
                    logger.warning(
                        "AD-806: handle_message raised for room=%s event=%s",
                        room_id, event.get("event_id"), exc_info=True,
                    )
                    continue
                if response:
                    await self.send_response(room_id, response)

    async def _sync_loop(self) -> None:
        """Long-polling /sync loop. Same MockTransport-friendly yield
        pattern as AD-803a Telegram + AD-804 Slack.
        """
        backoff_s = 1.0
        max_backoff_s = 30.0
        try:
            while not self._stop_requested.is_set():
                try:
                    payload = await self._client.sync(
                        since=self._sync_token,
                        timeout_ms=self._matrix_config.sync_timeout_ms,
                    )
                except MatrixAPIError as exc:
                    logger.warning(
                        "AD-806: /sync failed (will retry in %.1fs): %s",
                        backoff_s, exc,
                    )
                    await asyncio.sleep(backoff_s)
                    backoff_s = min(backoff_s * 2, max_backoff_s)
                    continue

                backoff_s = 1.0
                next_batch = payload.get("next_batch")
                if isinstance(next_batch, str):
                    self._sync_token = next_batch

                await self._process_sync_payload(payload)
                # Yield to event loop — MockTransport-friendly.
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.debug("AD-806: /sync loop cancelled")
            raise
