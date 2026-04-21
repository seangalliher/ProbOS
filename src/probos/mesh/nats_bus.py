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
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for subscriber callbacks
MessageCallback = Callable[["NATSMessage"], Awaitable[None]]


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
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_wait = reconnect_time_wait
        self._drain_timeout = drain_timeout
        self._subject_prefix = subject_prefix
        self._jetstream_enabled = jetstream_enabled
        self._nc: Any = None  # nats.NATS client
        self._js: Any = None  # JetStream context
        self._subscriptions: list[Any] = []
        self._connected = False
        self._started = False

    @property
    def connected(self) -> bool:
        """True when NATS client is connected and not draining."""
        return self._connected and self._nc is not None and self._nc.is_connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix (e.g., after ship DID is known)."""
        self._subject_prefix = prefix

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
            logger.debug("NATS request to %s failed: %s", full_subject, e)
            return None

    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish to a JetStream subject (durable, at-least-once)."""
        if not self._js:
            # Fallback to core NATS if JetStream not available
            await self.publish(subject, data, headers=headers)
            return

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        try:
            await self._js.publish(full_subject, payload, headers=headers)
        except Exception as e:
            logger.error("JetStream publish to %s failed: %s", full_subject, e)

    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
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
                await msg.ack()
            except Exception:
                logger.error(
                    "JetStream subscriber error on %s",
                    msg.subject,
                    exc_info=True,
                )
                await msg.nak()

        try:
            sub = await self._js.subscribe(
                full_subject,
                durable=durable,
                stream=stream,
                cb=_handler,
            )
            self._subscriptions.append(sub)
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

        full_subjects = [self._full_subject(s) for s in subjects]

        try:
            config = StreamConfig(
                name=name,
                subjects=full_subjects,
                max_msgs=max_msgs,
                max_age=max_age,
            )
            await self._js.add_stream(config)
            logger.info("JetStream stream '%s' ensured: %s", name, full_subjects)
        except Exception as e:
            logger.error("Failed to ensure stream '%s': %s", name, e)

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

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    def set_subject_prefix(self, prefix: str) -> None:
        self._subject_prefix = prefix

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
    ) -> str:
        return await self.subscribe(subject, callback)

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        self._streams[name] = {
            "subjects": subjects,
            "max_msgs": max_msgs,
            "max_age": max_age,
        }

    def health(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "status": "mock",
            "url": "mock://localhost",
            "reconnects": 0,
            "jetstream": True,
            "subscriptions": sum(len(cbs) for cbs in self._subs.values()),
        }
