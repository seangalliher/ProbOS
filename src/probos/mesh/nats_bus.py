"""NATS event bus — unified messaging for ProbOS (AD-637).

Provides:
- NATSMessage: wrapper around raw NATS messages with ack/nak/respond
- NATSBus: real NATS client with auto-reconnect, JetStream, graceful degradation
- MockNATSBus: in-memory mock for testing without a NATS server
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for subscriber callbacks
MessageCallback = Callable[["NATSMessage"], Awaitable[None]]

# BF-229: NATS subject tokens allow [A-Za-z0-9_\-] on all server versions.
# Dots are token separators. Colons, spaces, and other chars are unsafe.
_NATS_UNSAFE_CHAR = re.compile(r'[^A-Za-z0-9_\-.]')


# ---------------------------------------------------------------------------
# NATSMessage
# ---------------------------------------------------------------------------


class NATSMessage:
    """Wrapper around a NATS message for consumer-side processing."""

    __slots__ = ("subject", "data", "reply", "headers", "_msg")

    def __init__(
        self,
        subject: str,
        data: dict[str, Any],
        reply: str = "",
        headers: dict[str, str] | None = None,
        _msg: Any = None,
    ) -> None:
        self.subject = subject
        self.data = data
        self.reply = reply
        self.headers = headers or {}
        self._msg = _msg  # Raw nats.aio.msg.Msg for ack/nak

    async def ack(self) -> None:
        """Acknowledge JetStream message."""
        if self._msg and hasattr(self._msg, "ack"):
            await self._msg.ack()

    async def nak(self, delay: float | None = None) -> None:
        """Negative-acknowledge JetStream message (redelivery)."""
        if self._msg and hasattr(self._msg, "nak"):
            await self._msg.nak(delay=delay)

    async def term(self) -> None:
        """Terminate JetStream message — permanently reject, no redelivery."""
        if self._msg and hasattr(self._msg, "term"):
            await self._msg.term()

    async def respond(self, data: dict[str, Any]) -> None:
        """Reply to a request-reply message."""
        if self._msg and hasattr(self._msg, "respond"):
            payload = json.dumps(data).encode()
            await self._msg.respond(payload)


# ---------------------------------------------------------------------------
# NATSBus — real NATS client
# ---------------------------------------------------------------------------


class NATSBus:
    """NATS event bus — unified messaging for ProbOS (AD-637).

    Wraps nats-py client with:
    - Automatic reconnection with backoff
    - JetStream stream management
    - Graceful drain on shutdown
    - Fallback-safe: callers check .connected before assuming delivery
    """

    def __init__(
        self,
        url: str = "nats://localhost:4222",
        connect_timeout: float = 5.0,
        max_reconnect_attempts: int = 60,
        reconnect_time_wait: float = 2.0,
        drain_timeout: float = 5.0,
        subject_prefix: str = "probos.local",
        jetstream_enabled: bool = True,
        js_publish_timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_wait = reconnect_time_wait
        self._drain_timeout = drain_timeout
        self._subject_prefix = subject_prefix
        self._jetstream_enabled = jetstream_enabled
        self._js_publish_timeout = js_publish_timeout
        self._nc: Any = None  # nats.NATS client
        self._js: Any = None  # JetStream context
        self._subscriptions: list[Any] = []
        self._connected = False
        self._started = False
        self._active_subs: list[dict[str, Any]] = []  # Tracked subs for prefix re-subscription
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
        self._stream_configs: list[dict[str, Any]] = []  # Track streams for prefix re-creation

    @property
    def connected(self) -> bool:
        """True when NATS client is connected and not draining."""
        return self._connected and self._nc is not None and self._nc.is_connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    async def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix and re-subscribe all tracked subscriptions.

        AD-637z: Subscriptions created via subscribe()/js_subscribe() are
        tracked in _active_subs with un-prefixed subjects. On prefix change,
        each is unsubscribed and re-created with the new prefix.

        BF-229: Sanitizes the prefix — replaces NATS-unsafe characters
        (colons, spaces, etc.) with underscores. Ship DIDs contain colons
        (did:probos:<uuid>) which some NATS server versions reject in
        subject tokens. NATSBus owns this constraint.

        Note: publish_raw/subscribe_raw are intentionally NOT tracked.
        Federation uses raw subjects to bypass per-ship prefix isolation.
        """
        sanitized = _NATS_UNSAFE_CHAR.sub('_', prefix)
        if sanitized != prefix:
            logger.info("BF-229: Prefix sanitized %s → %s", prefix, sanitized)
        if sanitized == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = sanitized
        logger.info("NATS subject prefix changed: %s → %s", old_prefix, sanitized)

        # BF-232: Use recreate_stream which handles delete-then-create internally.
        # Replaces BF-231's explicit _delete_stream + ensure_stream loop.
        #
        # BF-223 interaction: stream deletion cascades to consumer deletion on
        # the NATS server, so BF-223's per-consumer delete_consumer() calls
        # (lines 199-211) become no-ops. BF-223 is preserved as defense-in-
        # depth for consumers on streams not tracked in _stream_configs.
        if self.connected and self._stream_configs:
            logger.info(
                "set_subject_prefix: recreating %d streams for new prefix",
                len(self._stream_configs),
            )
            for sc in self._stream_configs:
                stream_name = sc["name"]
                try:
                    await self.recreate_stream(
                        stream_name,
                        sc["subjects"],
                        max_msgs=sc.get("max_msgs", -1),
                        max_age=sc.get("max_age", 0),
                    )
                except Exception as e:
                    logger.error(
                        "BF-231: Stream recreate on prefix change failed for %s: %s — "
                        "JetStream publishes will fail until ProbOS is restarted.",
                        stream_name, e,
                    )
        else:
            logger.warning(
                "set_subject_prefix: skipping stream recreate (connected=%s, configs=%d)",
                self.connected, len(self._stream_configs),
            )

        # Re-subscribe all tracked subscriptions with new prefix
        if self.connected and self._active_subs:
            self._resubscribing = True
            try:
                for entry in self._active_subs:
                    old_sub = entry["sub"]
                    if old_sub is not None:
                        try:
                            await old_sub.unsubscribe()
                        except Exception as e:
                            logger.debug("Unsubscribe during prefix change: %s", e)

                    # Re-create with new prefix (subscribe/js_subscribe use _full_subject)
                    if entry["kind"] == "core":
                        new_sub = await self.subscribe(
                            entry["subject"], entry["callback"], **entry["kwargs"]
                        )
                    else:
                        # BF-223: JetStream durable consumers have their filter_subject
                        # baked into server-side config. Re-subscribing with a new prefix
                        # fails because NATS rejects the filter mismatch. Must delete the
                        # old consumer first so js_subscribe() creates a fresh one.
                        durable_name = entry["kwargs"].get("durable")
                        stream_name = entry["kwargs"].get("stream")
                        if durable_name and stream_name:
                            try:
                                await self.delete_consumer(stream_name, durable_name)
                                logger.debug(
                                    "BF-223: Deleted stale consumer %s/%s before re-subscribe",
                                    stream_name, durable_name,
                                )
                            except Exception as e:
                                logger.debug(
                                    "BF-223: Consumer delete before re-subscribe: %s", e
                                )
                        new_sub = await self.js_subscribe(
                            entry["subject"], entry["callback"], **entry["kwargs"]
                        )
                    entry["sub"] = new_sub
            finally:
                self._resubscribing = False

        # Notify registered callbacks (notification only — NATSBus already re-subscribed)
        for cb in self._prefix_change_callbacks:
            try:
                await cb(old_prefix, prefix)
            except Exception as e:
                logger.warning("Prefix change callback failed: %s", e)

    def register_on_prefix_change(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Register a callback for subject prefix changes (notification only).

        Callbacks fire AFTER NATSBus has re-subscribed everything. They are
        for logging and bookkeeping — NOT for managing subscriptions.
        """
        self._prefix_change_callbacks.append(callback)

    async def remove_tracked_subscription(self, subject: str) -> bool:
        """Remove and unsubscribe a tracked subscription by un-prefixed subject.

        Used by IntentBus.unsubscribe() to clean up agent subscriptions
        without maintaining a parallel tracking dict.
        Returns True if found and removed, False otherwise.
        """
        for i, entry in enumerate(self._active_subs):
            if entry["subject"] == subject:
                sub = entry["sub"]
                if sub is not None:
                    try:
                        await sub.unsubscribe()
                    except Exception as e:
                        logger.debug("Tracked unsubscribe error: %s", e)
                self._active_subs.pop(i)
                return True
        return False

    def _strip_prefix(self, subject: str) -> str:
        """Remove current prefix from subject for storage in _active_subs."""
        prefix_dot = self._subject_prefix + "."
        if subject.startswith(prefix_dot):
            return subject[len(prefix_dot):]
        return subject

    def _full_subject(self, subject: str) -> str:
        """Prepend subject prefix if not already present."""
        if subject.startswith(self._subject_prefix + "."):
            return subject
        return f"{self._subject_prefix}.{subject}"

    async def start(self) -> None:
        """Connect to NATS server."""
        if self._started:
            return

        import nats  # Lazy import — only needed when enabled

        async def _disconnected_cb() -> None:
            self._connected = False
            logger.warning("NATS disconnected")

        async def _reconnected_cb() -> None:
            self._connected = True
            logger.info("NATS reconnected to %s", self._nc.connected_url)

        async def _error_cb(e: Exception) -> None:
            logger.error("NATS error: %s", e)

        async def _closed_cb() -> None:
            self._connected = False
            logger.info("NATS connection closed")

        try:
            self._nc = await nats.connect(
                servers=[self._url],
                connect_timeout=self._connect_timeout,
                max_reconnect_attempts=self._max_reconnect,
                reconnect_time_wait=self._reconnect_wait,
                disconnected_cb=_disconnected_cb,
                reconnected_cb=_reconnected_cb,
                error_cb=_error_cb,
                closed_cb=_closed_cb,
            )
            self._connected = True
            self._started = True

            if self._jetstream_enabled:
                self._js = self._nc.jetstream()

            logger.info(
                "NATS connected to %s (JetStream=%s)",
                self._nc.connected_url,
                "enabled" if self._js else "disabled",
            )
        except Exception as e:
            logger.error("NATS connection failed: %s", e)
            self._nc = None
            self._connected = False
            # Don't raise — NATS is optional, system degrades gracefully

    async def stop(self) -> None:
        """Drain subscriptions and close connection."""
        if not self._nc:
            return

        try:
            # Drain flushes pending messages before closing
            await asyncio.wait_for(
                self._nc.drain(),
                timeout=self._drain_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("NATS drain timed out after %.1fs", self._drain_timeout)
        except Exception as e:
            logger.warning("NATS drain error: %s", e)

        # Force close if drain didn't complete
        if self._nc and not self._nc.is_closed:
            await self._nc.close()

        self._nc = None
        self._js = None
        self._connected = False
        self._started = False
        self._subscriptions.clear()
        self._active_subs.clear()
        self._prefix_change_callbacks.clear()
        self._stream_configs.clear()
        logger.info("NATS connection closed")

    async def publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish a message on a core NATS subject (fire-and-forget)."""
        if not self.connected:
            return

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()
        await self._nc.publish(full_subject, payload, headers=headers)

    async def subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> Any:
        """Subscribe to a core NATS subject."""
        if not self.connected:
            return None

        full_subject = self._full_subject(subject)

        async def _handler(msg: Any) -> None:
            try:
                raw_data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("NATS: invalid JSON on %s", msg.subject)
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=raw_data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
            except Exception:
                logger.error(
                    "NATS subscriber error on %s", msg.subject, exc_info=True
                )

        sub = await self._nc.subscribe(full_subject, queue=queue, cb=_handler)
        self._subscriptions.append(sub)
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "core",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {"queue": queue} if queue else {},
                "sub": sub,
            })
        return sub

    async def request(
        self,
        subject: str,
        data: dict[str, Any],
        timeout: float = 5.0,
    ) -> NATSMessage | None:
        """Send a request and wait for a reply (request/reply pattern)."""
        if not self.connected:
            return None

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        try:
            response = await self._nc.request(
                full_subject, payload, timeout=timeout
            )
            resp_data = json.loads(response.data) if response.data else {}
            return NATSMessage(
                subject=response.subject,
                data=resp_data,
                reply=response.reply or "",
                _msg=response,
            )
        except Exception as e:
            logger.warning("NATS request to %s failed: %s", full_subject, e)
            return None

    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish to a JetStream subject (durable, at-least-once).

        BF-230: Retry once on transient failure, then fall back to core NATS.
        Three-tier resilience:
          1. JetStream publish with configurable timeout
          2. One retry after 0.5s backoff (transient load spikes)
          3. Fallback to core NATS publish (at-most-once, but not lost)
        """
        if not self._js:
            await self.publish(subject, data, headers=headers)
            return

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        for attempt in range(2):  # attempt 0 = first try, attempt 1 = retry
            try:
                await self._js.publish(
                    full_subject, payload, headers=headers,
                    timeout=self._js_publish_timeout,
                )
                return  # Success
            except Exception as e:
                if attempt == 0:
                    logger.warning(
                        "JetStream publish to %s failed (attempt 1/2, retrying): %s",
                        full_subject, e,
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(
                        "JetStream publish to %s failed after retry, "
                        "falling back to core NATS: %s",
                        full_subject, e,
                    )

        # Fallback: core NATS (at-most-once delivery, but event not lost)
        try:
            await self.publish(subject, data, headers=headers)
        except Exception as fallback_err:
            logger.error(
                "BF-230: JetStream AND core NATS publish failed for %s — "
                "event dropped. Check NATS server health: %s",
                full_subject, fallback_err,
            )

    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
        max_ack_pending: int | None = None,
        ack_wait: int | None = None,
        manual_ack: bool = False,
        max_deliver: int | None = None,  # AD-654b
    ) -> Any:
        """Subscribe to a JetStream subject (durable consumer)."""
        if not self._js:
            # Fallback to core NATS subscription
            return await self.subscribe(subject, callback)

        full_subject = self._full_subject(subject)

        async def _handler(msg: Any) -> None:
            try:
                raw_data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("JetStream: invalid JSON on %s", msg.subject)
                if not manual_ack:
                    await msg.nak()
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=raw_data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
                if not manual_ack:
                    await msg.ack()
            except Exception:
                logger.error(
                    "JetStream subscriber error on %s",
                    msg.subject,
                    exc_info=True,
                )
                if not manual_ack:
                    await msg.nak()

        try:
            subscribe_kwargs: dict[str, Any] = {
                "durable": durable,
                "stream": stream,
                "cb": _handler,
            }
            if max_ack_pending is not None or ack_wait is not None or max_deliver is not None:
                from nats.js.api import ConsumerConfig
                config_kwargs: dict[str, Any] = {}
                if max_ack_pending is not None:
                    config_kwargs["max_ack_pending"] = max_ack_pending
                if ack_wait is not None:
                    config_kwargs["ack_wait"] = ack_wait
                if max_deliver is not None:
                    config_kwargs["max_deliver"] = max_deliver
                subscribe_kwargs["config"] = ConsumerConfig(**config_kwargs)
            sub = await self._js.subscribe(full_subject, **subscribe_kwargs)
            self._subscriptions.append(sub)
            if not self._resubscribing:
                self._active_subs.append({
                    "kind": "js",
                    "subject": self._strip_prefix(subject),
                    "callback": callback,
                    "kwargs": {
                        k: v for k, v in {
                            "durable": durable,
                            "stream": stream,
                            "max_ack_pending": max_ack_pending,
                            "ack_wait": ack_wait,
                            "manual_ack": manual_ack if manual_ack else None,
                            "max_deliver": max_deliver,
                        }.items() if v is not None
                    },
                    "sub": sub,
                })
            return sub
        except Exception as e:
            logger.error("JetStream subscribe to %s failed: %s", full_subject, e)
            return None

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        """Create or update a JetStream stream."""
        if not self._js:
            return

        from nats.js.api import StreamConfig

        # Track un-prefixed subjects for re-creation on prefix change
        stripped = [self._strip_prefix(s) for s in subjects]
        existing = next((sc for sc in self._stream_configs if sc["name"] == name), None)
        if existing:
            existing["subjects"] = stripped
            existing["max_msgs"] = max_msgs
            existing["max_age"] = max_age
        else:
            self._stream_configs.append({
                "name": name, "subjects": stripped,
                "max_msgs": max_msgs, "max_age": max_age,
            })

        full_subjects = [self._full_subject(s) for s in stripped]

        try:
            config = StreamConfig(
                name=name,
                subjects=full_subjects,
                max_msgs=max_msgs,
                max_age=max_age,
            )
            try:
                await self._js.add_stream(config)
            except Exception as add_err:
                # Stream exists with different config — update it
                if "10058" in str(add_err) or "already in use" in str(add_err):
                    await self._js.update_stream(config)
                else:
                    raise add_err
            logger.info("JetStream stream '%s' ensured: %s", name, full_subjects)
        except Exception as e:
            logger.error("Failed to ensure stream '%s': %s", name, e)
            raise

    async def recreate_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        """BF-232: Delete-then-create a JetStream stream.

        Unlike ensure_stream() (idempotent, non-destructive), this method
        always deletes any existing stream before creating. Use when subject
        filters may have changed (prefix change, new boot with stale server
        state). Retained messages are lost — acceptable for transient event
        buses with short max_age retention.

        On add_stream failure after delete, the stream is left absent and the
        config tracking entry is stale. Next set_subject_prefix() or
        recreate_stream() call self-heals.
        """
        if not self._js:
            return

        from nats.js.api import StreamConfig

        # Track un-prefixed subjects for re-creation on prefix change
        stripped = [self._strip_prefix(s) for s in subjects]
        existing = next((sc for sc in self._stream_configs if sc["name"] == name), None)
        if existing:
            existing["subjects"] = stripped
            existing["max_msgs"] = max_msgs
            existing["max_age"] = max_age
        else:
            self._stream_configs.append({
                "name": name, "subjects": stripped,
                "max_msgs": max_msgs, "max_age": max_age,
            })

        full_subjects = [self._full_subject(s) for s in stripped]

        try:
            await self._delete_stream(name)
            config = StreamConfig(
                name=name,
                subjects=full_subjects,
                max_msgs=max_msgs,
                max_age=max_age,
            )
            await self._js.add_stream(config)
            logger.info("JetStream stream '%s' recreated: %s", name, full_subjects)
        except Exception as e:
            logger.error("Failed to recreate stream '%s': %s", name, e)
            raise

    async def delete_consumer(self, stream: str, durable_name: str) -> None:
        """Delete a durable JetStream consumer (AD-654a cleanup)."""
        if not self._js:
            return
        try:
            await self._js.delete_consumer(stream, durable_name)
            logger.debug("NATSBus: Deleted consumer %s from stream %s", durable_name, stream)
        except Exception as e:
            logger.debug("NATSBus: Consumer delete failed (%s/%s): %s", stream, durable_name, e)

    async def _delete_stream(self, name: str) -> bool:
        """BF-231: Delete a JetStream stream by name. Returns True if deleted."""
        if not self._js:
            return False
        try:
            await self._js.delete_stream(name)
            logger.info("NATSBus: Deleted stream %s", name)
            return True
        except Exception as e:
            msg = str(e).lower()
            if "not found" in msg or "10059" in msg:
                logger.debug("NATSBus: Stream %s not found (already absent)", name)
            else:
                logger.warning("BF-232: Stream delete failed (%s): %s", name, e)
            return False

    def health(self) -> dict[str, Any]:
        """Return NATS health status for VitalsMonitor integration."""
        if not self._nc:
            return {
                "connected": False,
                "status": "not_started",
                "url": self._url,
            }
        return {
            "connected": self.connected,
            "status": "connected" if self.connected else "disconnected",
            "url": self._nc.connected_url or self._url,
            "reconnects": getattr(self._nc, "reconnected_count", 0),
            "jetstream": self._js is not None,
            "subscriptions": len(self._subscriptions),
        }

    async def publish_raw(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish without subject prefix — for cross-ship federation subjects."""
        if not self.connected:
            return
        payload = json.dumps(data).encode()
        await self._nc.publish(subject, payload, headers=headers)

    async def subscribe_raw(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> Any:
        """Subscribe without subject prefix — for cross-ship federation subjects."""
        if not self.connected:
            return None

        async def _handler(msg: Any) -> None:
            try:
                raw_data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("NATS: invalid JSON on %s", msg.subject)
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=raw_data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
            except Exception:
                logger.error(
                    "NATS subscriber error on %s", msg.subject, exc_info=True
                )

        sub = await self._nc.subscribe(subject, queue=queue, cb=_handler)
        self._subscriptions.append(sub)
        return sub


# ---------------------------------------------------------------------------
# MockNATSBus — in-memory mock for testing
# ---------------------------------------------------------------------------


class MockNATSBus:
    """In-memory mock for testing without a NATS server.

    Implements NATSBusProtocol with local dispatch.
    Messages published are immediately delivered to matching subscribers.
    """

    def __init__(self, subject_prefix: str = "probos.test") -> None:
        self._subject_prefix = subject_prefix
        self._connected = False
        self._started = False
        self._subs: dict[str, list[MessageCallback]] = {}
        self._queue_subs: dict[str, dict[str, list[MessageCallback]]] = {}
        self._streams: dict[str, dict[str, Any]] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []  # Test inspection
        self._active_subs: list[dict[str, Any]] = []
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
        self._stream_configs: list[dict[str, Any]] = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    async def set_subject_prefix(self, prefix: str) -> None:
        """Update prefix and rebuild subscriptions from _active_subs."""
        sanitized = _NATS_UNSAFE_CHAR.sub('_', prefix)
        if sanitized == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = sanitized

        # Rebuild _subs from _active_subs (un-prefixed source of truth)
        new_subs: dict[str, list[MessageCallback]] = {}
        for entry in self._active_subs:
            full = self._full_subject(entry["subject"])
            new_subs.setdefault(full, []).append(entry["callback"])
            entry["sub"] = full  # update tracked sub to new full subject

        # Preserve raw subscriptions (federation, not in _active_subs)
        for key, cbs in self._subs.items():
            if key not in new_subs:
                # Check if this key was from the old prefix
                old_dot = old_prefix + "."
                if not key.startswith(old_dot):
                    # Raw subscription — preserve as-is
                    new_subs[key] = cbs
        self._subs = new_subs

        # Notify callbacks
        for cb in self._prefix_change_callbacks:
            try:
                await cb(old_prefix, prefix)
            except Exception:
                pass

    def register_on_prefix_change(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        self._prefix_change_callbacks.append(callback)

    async def remove_tracked_subscription(self, subject: str) -> bool:
        """Remove a tracked subscription by un-prefixed subject."""
        for i, entry in enumerate(self._active_subs):
            if entry["subject"] == subject:
                # Remove from _subs dict
                full = self._full_subject(subject)
                if full in self._subs:
                    # Remove the specific callback, not all subs on this subject
                    try:
                        self._subs[full].remove(entry["callback"])
                    except ValueError:
                        pass
                    if not self._subs[full]:
                        del self._subs[full]
                self._active_subs.pop(i)
                return True
        return False

    def _strip_prefix(self, subject: str) -> str:
        prefix_dot = self._subject_prefix + "."
        if subject.startswith(prefix_dot):
            return subject[len(prefix_dot):]
        return subject

    def _full_subject(self, subject: str) -> str:
        if subject.startswith(self._subject_prefix + "."):
            return subject
        return f"{self._subject_prefix}.{subject}"

    async def start(self) -> None:
        self._connected = True
        self._started = True

    async def stop(self) -> None:
        self._connected = False
        self._started = False
        self._subs.clear()
        self._queue_subs.clear()
        self._active_subs.clear()
        self._prefix_change_callbacks.clear()
        self._stream_configs.clear()

    def _match_subject(self, pattern: str, subject: str) -> bool:
        """NATS subject matching: * = one token, > = one or more tokens."""
        pat_parts = pattern.split(".")
        sub_parts = subject.split(".")
        for i, pat in enumerate(pat_parts):
            if pat == ">":
                return True  # > matches remainder
            if i >= len(sub_parts):
                return False
            if pat != "*" and pat != sub_parts[i]:
                return False
        return len(pat_parts) == len(sub_parts)

    async def publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        if not self._connected:
            return

        full = self._full_subject(subject)
        self.published.append((full, data))

        msg = NATSMessage(subject=full, data=data, headers=headers or {})
        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, full):
                for cb in cbs:
                    await cb(msg)

    async def subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> str:
        full = self._full_subject(subject)
        if full not in self._subs:
            self._subs[full] = []
        self._subs[full].append(callback)
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "core",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {"queue": queue} if queue else {},
                "sub": full,
            })
        return full  # subscription handle

    async def request(
        self,
        subject: str,
        data: dict[str, Any],
        timeout: float = 5.0,
    ) -> NATSMessage | None:
        if not self._connected:
            return None

        full = self._full_subject(subject)
        self.published.append((full, data))

        # Find subscriber and invoke, capture respond() call
        reply_data: dict[str, Any] = {}

        class _MockReplyMsg:
            async def respond(self, payload: bytes) -> None:
                reply_data.update(json.loads(payload))

        msg = NATSMessage(
            subject=full,
            data=data,
            reply=f"_INBOX.mock.{id(data)}",
            _msg=_MockReplyMsg(),
        )

        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, full) and cbs:
                await cbs[0](msg)
                if reply_data:
                    return NATSMessage(
                        subject=msg.reply, data=reply_data
                    )
        return None

    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        await self.publish(subject, data, headers=headers)

    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
        max_ack_pending: int | None = None,
        ack_wait: int | None = None,
        manual_ack: bool = False,
        max_deliver: int | None = None,  # AD-654b
    ) -> str:
        full = self._full_subject(subject)
        if full not in self._subs:
            self._subs[full] = []
        self._subs[full].append(callback)
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "js",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {
                    k: v for k, v in {
                        "durable": durable,
                        "stream": stream,
                        "max_ack_pending": max_ack_pending,
                        "ack_wait": ack_wait,
                        "manual_ack": manual_ack if manual_ack else None,
                        "max_deliver": max_deliver,
                    }.items() if v is not None
                },
                "sub": full,
            })
        return full

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        stripped = [self._strip_prefix(s) for s in subjects]
        existing = next((sc for sc in self._stream_configs if sc["name"] == name), None)
        if existing:
            existing["subjects"] = stripped
        else:
            self._stream_configs.append({
                "name": name, "subjects": stripped,
                "max_msgs": max_msgs, "max_age": max_age,
            })
        self._streams[name] = {
            "subjects": [self._full_subject(s) for s in stripped],
            "max_msgs": max_msgs,
            "max_age": max_age,
        }

    async def recreate_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        """BF-232: In-memory — same as ensure_stream (no server state to clear)."""
        await self.ensure_stream(name, subjects, max_msgs=max_msgs, max_age=max_age)

    async def delete_consumer(self, stream: str, durable_name: str) -> None:
        """Delete a durable JetStream consumer (AD-654a cleanup) — mock no-op."""
        pass

    def health(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "status": "mock",
            "url": "mock://localhost",
            "reconnects": 0,
            "jetstream": True,
            "subscriptions": sum(len(cbs) for cbs in self._subs.values()),
        }

    async def publish_raw(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish without subject prefix — for cross-ship federation subjects."""
        if not self._connected:
            return
        self.published.append((subject, data))
        msg = NATSMessage(subject=subject, data=data, headers=headers or {})
        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, subject):
                for cb in cbs:
                    await cb(msg)

    async def subscribe_raw(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> str:
        """Subscribe without subject prefix — for cross-ship federation subjects."""
        if subject not in self._subs:
            self._subs[subject] = []
        self._subs[subject].append(callback)
        return subject
