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
from collections.abc import Iterable
from functools import lru_cache
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Type alias for subscriber callbacks
MessageCallback = Callable[["NATSMessage"], Awaitable[None]]

# BF-229: NATS subject tokens allow [A-Za-z0-9_\-] on all server versions.
# Dots are token separators. Colons, spaces, and other chars are unsafe.
_NATS_UNSAFE_CHAR = re.compile(r'[^A-Za-z0-9_\-.]')


def _subscription_tombstones(bus: Any) -> set[str]:
    """Return the per-bus removal tombstones, tolerating pre-init fixtures."""
    tombstones = getattr(bus, "_removed_subscription_subjects", None)
    if tombstones is None:
        tombstones = set()
        bus._removed_subscription_subjects = tombstones
    return tombstones


@lru_cache(maxsize=1)
def _already_removed_exc_types() -> tuple[type[BaseException], ...]:
    """BF-685: unsubscribe failures that already satisfy the removal contract.

    ``nats-py``'s ``Subscription.unsubscribe`` raises ``BadSubscriptionError``
    when the handle is already closed and ``ConnectionClosedError`` when the
    whole transport is gone. Both mean the invariant removal exists to
    establish — that this subscription delivers no further messages — already
    holds, so treating either as a failure asks teardown to undo something
    that is already undone.

    ``_recover_jetstream`` has always taken this view (it swallows a stale
    handle's unsubscribe at debug level and re-subscribes), and its docstring
    names the condition as expected. Teardown took the opposite view on the
    identical condition, and a single stale handle left behind by a partial
    recovery would surface at shutdown as *every* pool failing to stop,
    burying any genuine teardown fault in the noise.

    Resolved lazily, and to an empty tuple when ``nats`` is absent, because
    this module imports without the package so ``MockNATSBus`` stays usable.
    ``except ()`` is valid and never matches, which is the correct degrade: no
    real subscription objects exist on that path.
    """
    try:
        from nats import errors as nats_errors
    except Exception:  # pragma: no cover - exercised only without nats
        return ()
    candidates = (
        getattr(nats_errors, "BadSubscriptionError", None),
        getattr(nats_errors, "ConnectionClosedError", None),
    )
    return tuple(
        candidate
        for candidate in candidates
        if isinstance(candidate, type) and issubclass(candidate, BaseException)
    )


def _subscription_mutation_lock(bus: Any) -> asyncio.Lock:
    """Return the per-bus lock serializing recipe creation and removal."""
    lock = getattr(bus, "_subscription_mutation_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        bus._subscription_mutation_lock = lock
    return lock


# ---------------------------------------------------------------------------
# NATSMessage
# ---------------------------------------------------------------------------

# BF-805: the NATS server default. A connected client reports the real figure
# (``NATSBus.max_payload``); this is only the floor for a caller with no live
# connection to ask.
DEFAULT_MAX_PAYLOAD_BYTES: int = 1024 * 1024


@lru_cache(maxsize=1)
def _header_framing() -> tuple[bytes, bytes]:
    """The header line and line terminator nats-py frames headers with.

    Read from the library when it is installed, so a change to its framing
    surfaces here rather than being silently approximated. The protocol
    literals are the fallback for a build without the optional NATS extra,
    where nothing is going to be published anyway.
    """
    try:
        from nats.aio.client import NATS_HDR_LINE, _CRLF_  # type: ignore

        return bytes(NATS_HDR_LINE), bytes(_CRLF_)
    except Exception:  # pragma: no cover - only without nats-py installed
        return b"NATS/1.0", b"\r\n"


_NO_HEADERS: Any = object()
"""Distinguishes "this message has no headers attribute" from ``None`` or ``{}``."""


def encoded_header_size(headers: Any) -> int:
    """Bytes NATS frames for ``headers``, mirroring nats-py's own encoder.

    BF-805: ``Msg.respond`` republishes the REQUEST's headers onto the reply,
    and the server counts those bytes against ``max_payload`` alongside the
    body — while nats-py's own guard checks ``len(payload)`` alone. Measured
    against a live server: a 1,048,568-byte body plus 279 bytes of echoed
    headers was refused at a 1,048,576 limit, and the requester timed out
    holding nothing.

    Mirrors the loop in ``Client._send_publish``: header line, then
    ``key: value`` per entry, then a blank line, with empty keys skipped and
    values stripped exactly as it does.

    ``None`` and ``{}`` are NOT the same thing: the library sends a plain PUB
    for ``None`` and costs nothing, but an empty dict still takes the HPUB
    branch and frames a 12-byte header block.
    """
    if headers is None:
        return 0
    try:
        items = list(headers.items())
    except Exception:
        return 0
    hdr_line, crlf = _header_framing()
    size = len(hdr_line) + len(crlf)
    for key, value in items:
        # ``k.strip()`` exactly as the library does, not ``str(k).strip()``:
        # nats-py's own ``Header`` is a ``str`` subtype whose ``str()`` renders
        # as ``Header.DESCRIPTION`` while ``.strip()`` yields the wire name, and
        # the difference showed up as 39 predicted bytes against 32 real ones.
        try:
            name = key.strip()
        except AttributeError:
            name = str(key).strip()
        if not name:
            continue
        try:
            rendered = value.strip()
        except AttributeError:
            rendered = str(value).strip()
        size += (
            len(name.encode())
            + 2  # b": "
            + len(rendered.encode())
            + len(crlf)
        )
    return size + len(crlf)


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

    async def respond_encoded(self, payload: bytes) -> None:
        """Reply with bytes a caller has already encoded and checked.

        BF-805: the caller that decides whether a reply fits must send the
        BYTES it measured. Encoding twice means the check and the send can see
        different artifacts — measured with a mapping whose ``items()`` succeeds
        once and then raises, which passed the check and destroyed the answer on
        the second encode, reproducing the very defect being fixed.
        """
        if self._msg and hasattr(self._msg, "respond"):
            await self._msg.respond(payload)

    def reply_body_budget(self, max_payload: int) -> int:
        """BF-805: bytes left for a reply BODY after the echoed headers.

        ``Msg.respond`` carries the request's headers onto the reply, so the
        body's real ceiling is lower than the server's advertised limit by
        exactly their framed size. Never negative: a header block that alone
        exceeds the limit leaves nothing, and the caller's own checks then fail
        the reply honestly rather than sending something the server refuses.

        The headers charged are the ones ``respond`` will actually echo, which
        live on the raw message. ``or`` would collapse a raw ``{}`` -- a real
        12-byte HPUB block -- into this wrapper's own copy, so absent is
        distinguished from empty explicitly.
        """
        headers = getattr(self._msg, "headers", _NO_HEADERS)
        if headers is _NO_HEADERS:
            # This wrapper coerces absent headers to ``{}`` at construction, so
            # its own copy cannot tell "none" from "an empty HPUB block". Only
            # the raw message carries that distinction -- and only the raw
            # message's headers are what ``respond`` actually echoes.
            headers = self.headers or None
        return max(0, max_payload - encoded_header_size(headers))


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
        self._raw_subscription_release_tasks: list[
            tuple[object, asyncio.Task[bool]]
        ] = []
        self._connected = False
        self._started = False
        self._active_subs: list[dict[str, Any]] = []  # Tracked subs for prefix re-subscription
        self._removed_subscription_subjects: set[str] = set()
        self._subscription_mutation_lock = asyncio.Lock()
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
        self._stream_configs: list[dict[str, Any]] = []  # Track streams for prefix re-creation
        # BF-242: JetStream liveness probe — consecutive failure tracking
        self._js_consecutive_failures: int = 0
        self._js_failure_threshold: int = 3  # Trigger recovery after N consecutive failures
        self._js_suspended: bool = False  # True = JetStream disabled, publishes go straight to core NATS
        self._js_recovery_task: asyncio.Task | None = None  # Single-flight guard for recovery

    @property
    def connected(self) -> bool:
        """True when NATS client is connected and not draining."""
        return self._connected and self._nc is not None and self._nc.is_connected

    @property
    def max_payload(self) -> int:
        """Bytes the connected server will accept in one message.

        BF-805: a producer sizing a reply has to ask the transport, not guess.
        The server advertises this at connect (1 MiB by default) and enforces
        it with ``nats: maximum payload exceeded`` — which, on the reply path,
        replaces a perfectly good answer with a synthetic failure.

        Falls back to the NATS default when there is no live client, so an
        offline caller is bounded by the number the server almost certainly
        advertises rather than by nothing at all.
        """
        value = getattr(self._nc, "max_payload", None)
        if isinstance(value, int) and value > 0:
            return value
        return DEFAULT_MAX_PAYLOAD_BYTES

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

        if self.connected:
            # BF-241: Reuse shared recovery for streams + JS consumers
            await self._recover_jetstream(reason="prefix_change")

            # Core NATS re-subscription (not handled by _recover_jetstream —
            # nats-py auto-resubscribes core subs on reconnect but not on
            # prefix change, so this is prefix-change-only logic)
            core_entries = [e for e in self._active_subs if e["kind"] == "core"]
            if core_entries:
                for entry in core_entries:
                    if entry["subject"] in _subscription_tombstones(self):
                        continue
                    old_sub = entry["sub"]
                    if old_sub is not None:
                        try:
                            await old_sub.unsubscribe()
                        except Exception as e:
                            logger.debug("Unsubscribe during prefix change: %s", e)
                    new_sub = await self.subscribe(
                        entry["subject"],
                        entry["callback"],
                        _allow_removed=False,
                        **entry["kwargs"],
                    )
                    entry["sub"] = new_sub
        else:
            logger.warning(
                "set_subject_prefix: skipping recovery (not connected)"
            )

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
        return bool(await self.remove_tracked_subscriptions((subject,)))

    async def remove_tracked_subscriptions(
        self,
        subjects: Iterable[str],
    ) -> int:
        """Serialize removal against subscription creation and recovery."""
        async with _subscription_mutation_lock(self):
            return await self._remove_tracked_subscriptions_locked(subjects)

    async def _remove_tracked_subscriptions_locked(
        self,
        subjects: Iterable[str],
    ) -> int:
        """Tombstone and remove all tracked recipes for the given subjects.

        Every tombstone and recipe removal happens before the first await so
        concurrent prefix/JetStream recovery cannot recreate one subject while
        teardown is still unsubscribing another.
        """
        stripped_subjects = {
            self._strip_prefix(subject)
            for subject in subjects
        }
        if not stripped_subjects:
            return 0
        _subscription_tombstones(self).update(stripped_subjects)
        entries = [
            entry for entry in self._active_subs
            if entry["subject"] in stripped_subjects
        ]
        self._active_subs = [
            entry for entry in self._active_subs
            if entry["subject"] not in stripped_subjects
        ]
        failed_entries: list[dict[str, Any]] = []
        failures: list[BaseException] = []
        for entry in entries:
            sub = entry["sub"]
            if sub is not None:
                try:
                    await sub.unsubscribe()
                except _already_removed_exc_types() as exc:
                    # BF-685: already torn down. Fall through to drop the
                    # handle from tracking rather than restoring it — a
                    # retained dead handle would raise again on every
                    # subsequent attempt, which is how one stale subscription
                    # became a shutdown-wide failure.
                    logger.debug(
                        "BF-685: subscription for %s was already removed "
                        "(%s); treating teardown as complete",
                        entry["subject"], type(exc).__name__,
                    )
                except BaseException as exc:
                    failed_entries.append(entry)
                    failures.append(exc)
                    continue
                self._subscriptions = [
                    candidate
                    for candidate in self._subscriptions
                    if candidate is not sub
                ]
        if failed_entries:
            self._active_subs.extend(failed_entries)
        if failures:
            raise failures[0]
        return len(entries)

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

    async def _recover_jetstream(self, *, reason: str = "reconnect") -> None:
        """Recreate JetStream streams and re-subscribe consumers.

        Called on NATS reconnection (BF-241) and subject prefix change (BF-232).
        Streams are recreated via delete-then-create to handle stale server state.
        Consumer subscriptions are re-established from _active_subs tracking.

        Processing order: all JS streams first, then all JS consumers. Subscription
        processing order changes from the prior interleaved order in
        set_subject_prefix() to js-first, core-second. No test depends on the
        prior order.

        Tolerates mid-flight disconnects — each stream/consumer operation has its
        own try/except, so partial recovery is acceptable. Concurrent js_publish()
        calls during recovery will fail and use BF-230 fallback; no lock is added
        to avoid serializing and starving publishers.

        Stale entry["sub"] references from prior failed recoveries are handled
        gracefully — the unsubscribe will fail (already-invalid handle) and
        continue to the re-subscribe attempt.

        Failures are logged at ERROR but do not propagate — partial JetStream
        is better than none, and BF-230 fallback provides degraded delivery.
        """
        if not self._js:
            logger.debug("BF-241: _recover_jetstream skipped (JetStream disabled)")
            return

        # --- Phase 1: Recreate streams ---
        if self._stream_configs:
            logger.info(
                "BF-241: Recovering %d JetStream streams (reason=%s)",
                len(self._stream_configs), reason,
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
                        "BF-241: Stream recreate failed for %s (reason=%s): %s — "
                        "JetStream publishes to this stream will use BF-230 fallback.",
                        stream_name, reason, e,
                    )

        # --- Phase 2: Re-subscribe JetStream consumers ---
        js_entries = [e for e in self._active_subs if e["kind"] == "js"]
        if js_entries:
            logger.info(
                "BF-241: Re-subscribing %d JetStream consumers (reason=%s)",
                len(js_entries), reason,
            )
            self._resubscribing = True
            try:
                for entry in js_entries:
                    if entry["subject"] in _subscription_tombstones(self):
                        continue
                    old_sub = entry["sub"]
                    if old_sub is not None:
                        try:
                            await old_sub.unsubscribe()
                        except Exception as e:
                            logger.debug("BF-241: Unsubscribe stale consumer: %s", e)

                    # BF-223: Delete stale durable consumer before re-subscribe
                    durable_name = entry["kwargs"].get("durable")
                    stream_name = entry["kwargs"].get("stream")
                    if durable_name and stream_name:
                        try:
                            await self.delete_consumer(stream_name, durable_name)
                            logger.debug(
                                "BF-241: Deleted stale consumer %s/%s before re-subscribe",
                                stream_name, durable_name,
                            )
                        except Exception as e:
                            logger.debug(
                                "BF-241: Consumer delete before re-subscribe: %s", e
                            )

                    try:
                        new_sub = await self.js_subscribe(
                            entry["subject"],
                            entry["callback"],
                            _allow_removed=False,
                            **entry["kwargs"],
                        )
                        entry["sub"] = new_sub
                    except Exception as e:
                        logger.error(
                            "BF-241: Consumer re-subscribe failed for %s (reason=%s): %s",
                            entry["subject"], reason, e,
                        )
            finally:
                self._resubscribing = False

    def _suspend_jetstream(self) -> None:
        """BF-242: Temporarily disable JetStream — publishes bypass to core NATS.

        Called when consecutive JetStream failures exceed threshold and
        recovery fails. Eliminates the ~11s timeout penalty per publish.
        JetStream is restored by _resume_jetstream() after successful recovery.
        """
        if not self._js_suspended:
            self._js_suspended = True
            logger.warning(
                "BF-242: JetStream suspended after %d consecutive failures — "
                "all publishes will use core NATS until recovery succeeds.",
                self._js_consecutive_failures,
            )

    def _resume_jetstream(self) -> None:
        """BF-242: Re-enable JetStream after successful recovery."""
        if self._js_suspended:
            self._js_suspended = False
            self._js_consecutive_failures = 0
            logger.info("BF-242: JetStream resumed — publishes restored to at-least-once delivery.")

    def _on_recovery_task_done(self, task: asyncio.Task) -> None:
        """BF-242: Surface exceptions from background recovery task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("BF-242: Recovery task failed with unhandled exception: %s", exc)

    async def _try_jetstream_recovery(self) -> None:
        """BF-242: Attempt JetStream recovery after consecutive failures.

        Sequence:
        1. Suspend JetStream (no more timeout penalties for concurrent publishes)
        2. Attempt _recover_jetstream (recreate streams + consumers)
        3. Probe JetStream with a stream_info() call to verify it's responsive
        4. If probe succeeds → resume JetStream
        5. If probe fails → stay suspended until next reconnect

        Note: This runs asynchronously. The publish that triggered recovery
        has already fallen through to core NATS — suspension eliminates
        timeout penalty for all concurrent and subsequent publishes
        immediately, before recovery completes.

        Probe uses stream_info(name) on the first configured stream.
        If one stream responds, the JetStream subsystem is functional —
        probing all streams adds latency for no diagnostic value.
        """
        self._suspend_jetstream()

        try:
            await self._recover_jetstream(reason="liveness")
        except Exception as e:
            logger.error(
                "BF-242: JetStream recovery failed — staying suspended: %s", e
            )
            return

        # Probe: verify JetStream is actually responsive after recovery
        if self._stream_configs:
            probe_stream = self._stream_configs[0]["name"]
            try:
                await self._js.stream_info(probe_stream)
                logger.info("BF-242: JetStream probe succeeded (stream: %s)", probe_stream)
                self._resume_jetstream()
            except Exception as e:
                logger.warning(
                    "BF-242: JetStream probe failed after recovery — "
                    "staying suspended until next reconnect: %s", e
                )
        else:
            # No streams tracked — resume optimistically
            self._resume_jetstream()

    async def _on_reconnected(self) -> None:
        """BF-241: Reconnect callback — restore JetStream state.

        Extracted from the nested closure in start() so it can be tested
        directly. nats-py auto-resubscribes core NATS subscriptions on
        reconnect, but JetStream streams and consumers must be explicitly
        recreated.

        BF-242: Also resumes JetStream if it was suspended due to liveness
        failure, since a reconnect means the server may have restarted.
        """
        self._connected = True
        logger.info("NATS reconnected to %s", self._nc.connected_url)
        if self._js:
            try:
                await self._recover_jetstream(reason="reconnect")
                # BF-242: Reconnect implies server may have restarted — resume
                self._resume_jetstream()
            except asyncio.CancelledError:
                raise  # propagate — shutdown in progress
            except Exception as e:
                logger.error(
                    "BF-241: JetStream recovery on reconnect failed: %s — "
                    "JetStream publishes will use BF-230 fallback until next "
                    "reconnect or restart.",
                    e,
                )

    async def start(self) -> None:
        """Connect to NATS server."""
        if self._started:
            return

        import nats  # Lazy import — only needed when enabled

        async def _disconnected_cb() -> None:
            self._connected = False
            logger.warning("NATS disconnected")

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
                reconnected_cb=self._on_reconnected,
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
        *,
        _allow_removed: bool = True,
    ) -> Any:
        """Serialize core subscription creation against tracked removal."""
        async with _subscription_mutation_lock(self):
            return await self._subscribe_locked(
                subject,
                callback,
                queue,
                _allow_removed=_allow_removed,
            )

    async def _subscribe_locked(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
        *,
        _allow_removed: bool = True,
    ) -> Any:
        """Subscribe to a core NATS subject."""
        if not self.connected:
            return None

        stripped_subject = self._strip_prefix(subject)
        tombstones = _subscription_tombstones(self)
        if not _allow_removed and stripped_subject in tombstones:
            return None
        if _allow_removed:
            tombstones.discard(stripped_subject)
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
        if not _allow_removed and stripped_subject in tombstones:
            await sub.unsubscribe()
            return None
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
    ) -> str:
        """Publish to a JetStream subject (durable, at-least-once).

        BF-230: Retry once on transient failure, then fall back to core NATS.
        BF-242: Track consecutive failures. After threshold, suspend JetStream
        and trigger recovery. While suspended, publishes bypass directly to
        core NATS (no timeout penalty).

        BF-815: returns which transport took it -- ``"jetstream"`` (durable
        ACK), ``"core_nats"`` (at-most-once fallback), or ``"dropped"`` (both
        failed; the event is gone). This returned ``None`` for all three, so a
        caller could not tell a durable ACK from a logged "event dropped", and
        ``dispatch_async`` reported a dropped message as successfully
        dispatched. Adding a return value is backward-compatible -- existing
        callers ignore it.
        """
        if not self._js:
            await self.publish(subject, data, headers=headers)
            return "core_nats"

        # BF-242: When JetStream is suspended, go straight to core NATS
        if self._js_suspended:
            try:
                await self.publish(subject, data, headers=headers)
            except Exception as fallback_err:
                logger.error(
                    "BF-242: Suspended JetStream AND core NATS publish failed for %s — "
                    "event dropped: %s",
                    self._full_subject(subject), fallback_err,
                )
                return "dropped"
            return "core_nats"

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        for attempt in range(2):  # attempt 0 = first try, attempt 1 = retry
            try:
                await self._js.publish(
                    full_subject, payload, headers=headers,
                    timeout=self._js_publish_timeout,
                )
                # BF-242: Success — reset failure counter
                if self._js_consecutive_failures > 0:
                    self._js_consecutive_failures = 0
                return "jetstream"
            except Exception as e:
                if attempt == 0:
                    logger.warning(
                        "JetStream publish to %s failed (attempt 1/2, retrying): %s",
                        full_subject, e,
                    )
                    await asyncio.sleep(0.5)
                else:
                    self._js_consecutive_failures += 1
                    logger.warning(
                        "JetStream publish to %s failed after retry, "
                        "falling back to core NATS (consecutive failures: %d): %s",
                        full_subject, self._js_consecutive_failures, e,
                    )
                    # BF-242: Threshold exceeded — trigger recovery (single-flight)
                    if self._js_consecutive_failures >= self._js_failure_threshold:
                        if self._js_recovery_task is None or self._js_recovery_task.done():
                            self._js_recovery_task = asyncio.create_task(
                                self._try_jetstream_recovery()
                            )
                            self._js_recovery_task.add_done_callback(
                                self._on_recovery_task_done
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
            return "dropped"
        return "core_nats"

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
        *,
        _allow_removed: bool = True,
    ) -> Any:
        """Serialize JetStream consumer creation against tracked removal."""
        async with _subscription_mutation_lock(self):
            return await self._js_subscribe_locked(
                subject,
                callback,
                durable=durable,
                stream=stream,
                max_ack_pending=max_ack_pending,
                ack_wait=ack_wait,
                manual_ack=manual_ack,
                max_deliver=max_deliver,
                _allow_removed=_allow_removed,
            )

    async def _js_subscribe_locked(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
        max_ack_pending: int | None = None,
        ack_wait: int | None = None,
        manual_ack: bool = False,
        max_deliver: int | None = None,
        *,
        _allow_removed: bool = True,
    ) -> Any:
        """Subscribe to a JetStream subject (durable consumer)."""
        if not self._js:
            # Fallback to core NATS subscription
            return await self._subscribe_locked(
                subject,
                callback,
                _allow_removed=_allow_removed,
            )

        stripped_subject = self._strip_prefix(subject)
        tombstones = _subscription_tombstones(self)
        if not _allow_removed and stripped_subject in tombstones:
            return None
        if _allow_removed:
            tombstones.discard(stripped_subject)
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
            if not _allow_removed and stripped_subject in tombstones:
                await sub.unsubscribe()
                if stream and durable:
                    await self.delete_consumer(stream, durable)
                return None
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
            message = str(e).lower()
            if "not found" in message or "10014" in message:
                logger.debug(
                    "NATSBus: Consumer already absent (%s/%s): %s",
                    stream,
                    durable_name,
                    e,
                )
                return
            raise

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
            "js_suspended": self._js_suspended,
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

    async def release_raw_subscription(self, subscription: object) -> bool:
        """Drain and identity-remove one exact tracked raw subscription."""
        if not any(candidate is subscription for candidate in self._subscriptions):
            return False

        release_task = next(
            (
                task
                for candidate, task in self._raw_subscription_release_tasks
                if candidate is subscription
            ),
            None,
        )
        if release_task is None:
            release_task = asyncio.create_task(
                self._release_raw_subscription(subscription),
                name="nats-raw-subscription-release",
            )
            self._raw_subscription_release_tasks.append(
                (subscription, release_task),
            )
            release_task.add_done_callback(
                lambda completed, owned=subscription: self._forget_raw_release_task(
                    owned,
                    completed,
                )
            )

        try:
            return await asyncio.shield(release_task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(release_task)
            except Exception:
                pass
            raise

    async def _release_raw_subscription(self, subscription: object) -> bool:
        try:
            drain = getattr(subscription, "drain")
            await drain()
        except asyncio.CancelledError:
            raise
        except Exception as drain_error:
            try:
                unsubscribe = getattr(subscription, "unsubscribe")
                await unsubscribe()
            except asyncio.CancelledError:
                raise
            except Exception as unsubscribe_error:
                raise RuntimeError(
                    "nats_raw_subscription_release_failed"
                ) from unsubscribe_error

        self._subscriptions = [
            candidate
            for candidate in self._subscriptions
            if candidate is not subscription
        ]
        return True

    def _forget_raw_release_task(
        self,
        subscription: object,
        release_task: asyncio.Task[bool],
    ) -> None:
        self._raw_subscription_release_tasks = [
            (candidate, task)
            for candidate, task in self._raw_subscription_release_tasks
            if candidate is not subscription or task is not release_task
        ]


# ---------------------------------------------------------------------------
# MockNATSBus — in-memory mock for testing
# ---------------------------------------------------------------------------


class _MockDeliveredMsg:
    """Records which JetStream disposition a consumer chose (AD-1276).

    ``MockNATSBus.publish`` used to build ``NATSMessage`` with no ``_msg``, and
    every disposition method on that wrapper no-ops when ``_msg`` is None. So a
    consumer that ``term()``ed a message and one that ``ack()``ed it produced
    identical observable state, and no test could tell them apart.
    """

    __slots__ = ("subject", "_acks", "_naks", "_terms")

    def __init__(
        self,
        subject: str,
        acks: list[str],
        naks: list[tuple[str, float | None]],
        terms: list[str],
    ) -> None:
        self.subject = subject
        self._acks = acks
        self._naks = naks
        self._terms = terms

    async def ack(self) -> None:
        self._acks.append(self.subject)

    async def nak(self, delay: float | None = None) -> None:
        self._naks.append((self.subject, delay))

    async def term(self) -> None:
        self._terms.append(self.subject)


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
        # AD-1276: delivered-message dispositions, for tests that must tell a
        # refusal from an acceptance. Not cleared by ``stop()``, matching
        # ``published`` -- these are the record of what happened, and a test
        # that stops the bus before asserting still needs them.
        self.acks: list[str] = []
        self.naks: list[tuple[str, float | None]] = []
        self.terms: list[str] = []
        self._active_subs: list[dict[str, Any]] = []
        self._removed_subscription_subjects: set[str] = set()
        self._subscription_mutation_lock = asyncio.Lock()
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
        self._stream_configs: list[dict[str, Any]] = []
        self._js_suspended: bool = False  # BF-242 parity

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
            if entry["subject"] in _subscription_tombstones(self):
                continue
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

    async def _recover_jetstream(self, *, reason: str = "reconnect") -> None:
        """No-op for mock bus — no server-side state to recover."""
        pass

    async def remove_tracked_subscription(self, subject: str) -> bool:
        """Remove a tracked subscription by un-prefixed subject."""
        return bool(await self.remove_tracked_subscriptions((subject,)))

    async def remove_tracked_subscriptions(
        self,
        subjects: Iterable[str],
    ) -> int:
        """Serialize removal against mock subscription creation."""
        async with _subscription_mutation_lock(self):
            return await self._remove_tracked_subscriptions_locked(subjects)

    async def _remove_tracked_subscriptions_locked(
        self,
        subjects: Iterable[str],
    ) -> int:
        """Tombstone and remove all tracked recipes for the given subjects."""
        stripped_subjects = {
            self._strip_prefix(subject)
            for subject in subjects
        }
        if not stripped_subjects:
            return 0
        _subscription_tombstones(self).update(stripped_subjects)
        entries = [
            entry for entry in self._active_subs
            if entry["subject"] in stripped_subjects
        ]
        self._active_subs = [
            entry for entry in self._active_subs
            if entry["subject"] not in stripped_subjects
        ]
        for entry in entries:
            full = self._full_subject(entry["subject"])
            if full in self._subs:
                try:
                    self._subs[full].remove(entry["callback"])
                except ValueError:
                    pass
                if not self._subs[full]:
                    del self._subs[full]
        return len(entries)

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

        # AD-1276: a raw message stands behind the wrapper so ack/nak/term are
        # observable. Without it every disposition silently no-ops.
        msg = NATSMessage(
            subject=full,
            data=data,
            headers=headers or {},
            _msg=_MockDeliveredMsg(full, self.acks, self.naks, self.terms),
        )
        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, full):
                for cb in cbs:
                    await cb(msg)

    async def subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
        *,
        _allow_removed: bool = True,
    ) -> str:
        async with _subscription_mutation_lock(self):
            return await self._subscribe_locked(
                subject,
                callback,
                queue,
                _allow_removed=_allow_removed,
            )

    async def _subscribe_locked(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
        *,
        _allow_removed: bool = True,
    ) -> str:
        stripped = self._strip_prefix(subject)
        tombstones = _subscription_tombstones(self)
        if not _allow_removed and stripped in tombstones:
            return ""
        if _allow_removed:
            tombstones.discard(stripped)
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
        *,
        headers: dict[str, str] | None = None,
    ) -> NATSMessage | None:
        """Deliver a request to one subscriber and capture its reply.

        AD-1276: ``headers`` models a PEER's header block, not a ProbOS caller
        -- neither ``NATSBus.request`` nor any caller in this repo sends
        headers. It exists because ``Msg.respond`` echoes the request's headers
        onto the reply and the server charges them against the reply's size
        limit, which is the whole subject of BF-805/BF-827. Keyword-only and
        defaulted, so every existing call site is unaffected.
        """
        if not self._connected:
            return None

        full = self._full_subject(subject)
        self.published.append((full, data))

        # Find subscriber and invoke, capture respond() call
        reply_data: dict[str, Any] = {}
        # The RAW value, deliberately not coerced to ``{}``: nats-py leaves
        # ``Msg.headers`` as ``None`` when a request carried none, and
        # ``encoded_header_size`` charges 0 for ``None`` against 12 for an
        # empty HPUB block. Coercing taxed every existing reply site 12 bytes.
        _raw_headers = headers

        class _MockReplyMsg:
            # AD-1276: ``Msg.respond`` echoes the REQUEST's headers and the
            # server charges them against the reply's limit, so
            # ``reply_body_budget`` reads them off the RAW message. Without
            # this attribute it fell back to the wrapper's own copy and no
            # test could exercise a real echo cost.
            headers = _raw_headers

            async def respond(self, payload: bytes) -> None:
                reply_data.update(json.loads(payload))

        msg = NATSMessage(
            subject=full,
            data=data,
            reply=f"_INBOX.mock.{id(data)}",
            headers=headers,
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
    ) -> str:
        """Deliver like the real bus and report the route it took (AD-1276).

        This returned ``None``, which no real transport ever reports.
        ``dispatch_async`` branches on ``outcome != "dropped"``, so the mock
        yielded ``DispatchAdmission(True, route=None)`` -- an admission shape
        production cannot produce.
        """
        await self.publish(subject, data, headers=headers)
        return "jetstream"

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
        *,
        _allow_removed: bool = True,
    ) -> str:
        async with _subscription_mutation_lock(self):
            return await self._js_subscribe_locked(
                subject,
                callback,
                durable=durable,
                stream=stream,
                max_ack_pending=max_ack_pending,
                ack_wait=ack_wait,
                manual_ack=manual_ack,
                max_deliver=max_deliver,
                _allow_removed=_allow_removed,
            )

    async def _js_subscribe_locked(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
        max_ack_pending: int | None = None,
        ack_wait: int | None = None,
        manual_ack: bool = False,
        max_deliver: int | None = None,
        *,
        _allow_removed: bool = True,
    ) -> str:
        stripped = self._strip_prefix(subject)
        tombstones = _subscription_tombstones(self)
        if not _allow_removed and stripped in tombstones:
            return ""
        if _allow_removed:
            tombstones.discard(stripped)
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
            "js_suspended": self._js_suspended,
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
