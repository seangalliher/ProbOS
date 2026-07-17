"""Bounded federation avatar telemetry relay (AD-722b-5a)."""
from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import re
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.avatars.telemetry_frames import (
    DEGRADED_REASON_VALUES,
    FIRED_RULE_VALUES,
    MAX_AVATAR_SEQUENCE,
    is_safe_avatar_agent_id,
    project_avatar_telemetry_data_for_federation,
    select_avatar_telemetry_frame,
    validate_avatar_telemetry_data,
)
from probos.federation.relay import is_safe_relay_node_id

if TYPE_CHECKING:
    from probos.avatars.events import AvatarEventBus
    from probos.avatars.sampling_state import AvatarSamplingStateMachine
    from probos.avatars.telemetry import AvatarTelemetrySnapshot

logger = logging.getLogger(__name__)

AVATAR_TELEMETRY_TOPIC = "avatar.telemetry.v1"
MAX_TELEMETRY_AGENTS = 64
MAX_REMOTE_AVATAR_TELEMETRY_ENTRIES = 256
MAX_DISPATCH_LOG_ENTRIES = 256

_TOPIC_PAYLOAD_KEYS = frozenset({
    "agent_id",
    "frame_type",
    "stream_id",
    "sequence",
    "data",
})
_STREAM_ID_RE = re.compile(r"^[0-9a-f]{32}$")

TelemetryEmitCallback = Callable[
    [str, dict[str, Any]],
    Awaitable[bool],
]
TelemetrySnapshotBuilder = Callable[
    [str],
    Awaitable["AvatarTelemetrySnapshot"],
]


@dataclass(frozen=True)
class PeerTelemetrySubscription:
    peer_id: str
    agent_ids: frozenset[str]


@dataclass(frozen=True)
class _RemoteAvatarTelemetryEntry:
    source_node: str
    agent_id: str
    stream_id: str
    sequence: int
    last_frame_type: str
    received_at: float
    snapshot: dict[str, Any]


def _has_exact_payload_keys(value: Any) -> bool:
    if type(value) is not dict or dict.__len__(value) != len(
        _TOPIC_PAYLOAD_KEYS
    ):
        return False
    seen: set[str] = set()
    for key in dict.keys(value):
        if type(key) is not str or key not in _TOPIC_PAYLOAD_KEYS:
            return False
        seen.add(key)
    return seen == _TOPIC_PAYLOAD_KEYS


def parse_avatar_telemetry_payload(
    payload: Any,
) -> dict[str, Any] | None:
    """Validate and detach one exact avatar telemetry topic payload."""
    if not _has_exact_payload_keys(payload):
        return None
    agent_id = dict.__getitem__(payload, "agent_id")
    frame_type = dict.__getitem__(payload, "frame_type")
    stream_id = dict.__getitem__(payload, "stream_id")
    sequence = dict.__getitem__(payload, "sequence")
    data = dict.__getitem__(payload, "data")
    if (
        not is_safe_avatar_agent_id(agent_id)
        or type(frame_type) is not str
        or frame_type not in {"snapshot", "diff"}
        or type(stream_id) is not str
        or _STREAM_ID_RE.fullmatch(stream_id) is None
        or type(sequence) is not int
        or sequence < 0
        or sequence > MAX_AVATAR_SEQUENCE
    ):
        return None
    detached_data = validate_avatar_telemetry_data(data, frame_type)
    if detached_data is None:
        return None
    return {
        "agent_id": agent_id,
        "frame_type": frame_type,
        "stream_id": stream_id,
        "sequence": sequence,
        "data": detached_data,
    }


def validate_avatar_telemetry_payload(payload: dict[str, Any]) -> bool:
    """Return literal True only for the complete closed topic contract."""
    return parse_avatar_telemetry_payload(payload) is not None


class FederationTelemetryRelay:
    """Dispatch explicit local avatar streams to configured peer filters."""

    def __init__(
        self,
        *,
        max_per_sec_per_peer: int = 10,
        snapshot_builder: TelemetrySnapshotBuilder | None = None,
        event_bus: "AvatarEventBus | None" = None,
        sampling_state: "AvatarSamplingStateMachine | None" = None,
        diff_enabled: bool = True,
        diff_threshold: float = 0.05,
        full_every_n: int = 10,
    ) -> None:
        if (
            type(max_per_sec_per_peer) is not int
            or not 1 <= max_per_sec_per_peer <= 10
        ):
            raise ValueError("telemetry_rate_limit_invalid")
        self._subs: dict[str, PeerTelemetrySubscription] = {}
        self._rate: dict[str, deque[float]] = {}
        self._max_per_sec = max_per_sec_per_peer
        self._dispatch_log: list[tuple[str, dict[str, Any]]] = []
        self._emit_callback: TelemetryEmitCallback = self._default_emit
        self._snapshot_builder = snapshot_builder
        self._event_bus = event_bus
        self._sampling_state = sampling_state
        self._diff_enabled = diff_enabled
        self._diff_threshold = diff_threshold
        self._full_every_n = full_every_n
        self._producer_tasks: dict[str, asyncio.Task[None]] = {}
        self._frame_cursors: dict[str, dict[str, Any] | None] = {}
        self._tick_counts: dict[str, int] = {}
        self._stream_id: str | None = None
        self._sequences: dict[str, int] = {}
        self._running = False
        self._lifecycle_lock = asyncio.Lock()

    def register_peer(self, peer_id: str, agent_ids: list[str]) -> None:
        """Register one immutable-while-running peer export filter."""
        self._require_stopped()
        if (
            not is_safe_relay_node_id(peer_id)
            or type(agent_ids) is not list
            or list.__len__(agent_ids) > MAX_TELEMETRY_AGENTS
        ):
            raise ValueError("telemetry_subscription_invalid")
        admitted: set[str] = set()
        for index in range(list.__len__(agent_ids)):
            agent_id = list.__getitem__(agent_ids, index)
            if not is_safe_avatar_agent_id(agent_id) or agent_id in admitted:
                raise ValueError("telemetry_subscription_invalid")
            admitted.add(agent_id)
        self._subs[peer_id] = PeerTelemetrySubscription(
            peer_id=peer_id,
            agent_ids=frozenset(admitted),
        )
        self._rate.pop(peer_id, None)
        logger.info(
            "Federation avatar telemetry peer=%s configured with %d explicit exports",
            peer_id,
            len(admitted),
        )

    def unregister_peer(self, peer_id: str) -> None:
        """Remove one stopped relay subscription and its rate state."""
        self._require_stopped()
        self._subs.pop(peer_id, None)
        self._rate.pop(peer_id, None)

    def set_emit_callback(self, callback: TelemetryEmitCallback) -> None:
        """Install an exact two-argument async bool transport adapter."""
        self._require_stopped()
        try:
            if not callable(callback):
                raise ValueError("telemetry_emit_callback_invalid")
            if inspect.iscoroutinefunction(callback) is not True:
                raise ValueError("telemetry_emit_callback_invalid")
            parameters = tuple(inspect.signature(callback).parameters.values())
            if len(parameters) != 2 or any(
                parameter.kind not in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
                for parameter in parameters
            ):
                raise ValueError("telemetry_emit_callback_invalid")
        except Exception:
            raise ValueError("telemetry_emit_callback_invalid") from None
        self._emit_callback = callback

    async def start(self) -> None:
        """Start one referenced producer per unique explicitly exported agent."""
        async with self._lifecycle_lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        if self._running:
            return
        dependencies = (
            self._snapshot_builder,
            self._event_bus,
            self._sampling_state,
        )
        if any(item is not None for item in dependencies) and any(
            item is None for item in dependencies
        ):
            raise ValueError("telemetry_producer_dependencies_invalid")
        agent_ids = sorted({
            agent_id
            for subscription in self._subs.values()
            for agent_id in subscription.agent_ids
        })
        if len(agent_ids) > MAX_TELEMETRY_AGENTS:
            raise ValueError("telemetry_agent_cap_exceeded")
        self._rate.clear()
        self._frame_cursors.clear()
        self._tick_counts.clear()
        self._producer_tasks.clear()
        self._sequences.clear()
        self._stream_id = secrets.token_hex(16)
        self._running = True
        if not agent_ids or self._snapshot_builder is None:
            return
        try:
            for agent_id in agent_ids:
                ready = asyncio.Event()
                task = asyncio.create_task(
                    self._producer_loop(agent_id, ready),
                    name=f"federation-avatar-telemetry-{agent_id}",
                )
                self._producer_tasks[agent_id] = task
                await ready.wait()
                if task.done():
                    task.result()
                task.add_done_callback(
                    lambda completed, agent_id=agent_id: (
                        self._observe_producer_done(agent_id, completed)
                    ),
                )
        except BaseException:
            await self._cleanup_producers()
            self._reset_volatile_state()
            raise

    async def stop(self) -> None:
        """Stop/reap producers and clear every volatile stream/rate cursor."""
        async with self._lifecycle_lock:
            self._running = False
            await self._cleanup_producers()
            self._reset_volatile_state()

    async def on_local_telemetry_frame(
        self,
        *,
        agent_id: str,
        frame_type: str,
        payload: dict[str, Any],
    ) -> int:
        """Validate, sequence, rate-claim, and dispatch one semantic frame."""
        if not self._running or self._stream_id is None:
            return 0
        projected = project_avatar_telemetry_data_for_federation(payload)
        sequence = self._sequences.get(agent_id, 0)
        candidate = {
            "agent_id": agent_id,
            "frame_type": frame_type,
            "stream_id": self._stream_id,
            "sequence": sequence,
            "data": projected,
        }
        exact_payload = parse_avatar_telemetry_payload(candidate)
        if exact_payload is None:
            return 0
        self._sequences[agent_id] = sequence + 1
        dispatched = 0
        for peer_id, subscription in self._subs.items():
            if agent_id not in subscription.agent_ids:
                continue
            if not self._claim_attempt(peer_id):
                continue
            try:
                accepted = await self._emit_callback(peer_id, exact_payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Federation avatar telemetry emit failed peer=%s "
                    "exception_type=%s; frame dropped and next cadence continues",
                    peer_id,
                    type(exc).__name__,
                )
                continue
            if accepted is True:
                dispatched += 1
        return dispatched

    def dispatch_log(self) -> list[tuple[str, dict[str, Any]]]:
        """Return detached entries recorded by the default test callback."""
        return copy.deepcopy(self._dispatch_log)

    def reset_dispatch_log(self) -> None:
        """Clear the bounded default callback observation log."""
        self._dispatch_log.clear()

    async def _producer_loop(
        self,
        agent_id: str,
        ready: asyncio.Event,
    ) -> None:
        event: asyncio.Event | None = None
        try:
            if self._event_bus is None:
                return
            event = self._event_bus.subscribe(agent_id)
            self._frame_cursors[agent_id] = None
            self._tick_counts[agent_id] = 0
            ready.set()
            last_build_at = await self._produce_agent_frame(
                agent_id,
                force_full=True,
            )
            while self._running:
                event.clear()
                rate_ms = self._sampling_state.current_rate_ms(agent_id)
                interval_s = max(0.1, float(rate_ms) / 1000.0)
                wait_event: asyncio.Task[bool] | None = None
                wait_timer: asyncio.Task[None] | None = None
                try:
                    wait_event = asyncio.create_task(event.wait())
                    wait_timer = asyncio.create_task(asyncio.sleep(interval_s))
                    await asyncio.wait(
                        {wait_event, wait_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    waiters = tuple(
                        waiter
                        for waiter in (wait_event, wait_timer)
                        if waiter is not None
                    )
                    for waiter in waiters:
                        if not waiter.done():
                            waiter.cancel()
                    if waiters:
                        await asyncio.gather(*waiters, return_exceptions=True)
                elapsed = time.monotonic() - last_build_at
                if elapsed < 0.1:
                    await asyncio.sleep(0.1 - elapsed)
                if not self._running:
                    break
                self._tick_counts[agent_id] += 1
                last_build_at = await self._produce_agent_frame(agent_id)
        except asyncio.CancelledError:
            raise
        finally:
            ready.set()
            if event is not None and self._event_bus is not None:
                self._event_bus.unsubscribe(agent_id, event)

    async def _produce_agent_frame(
        self,
        agent_id: str,
        *,
        force_full: bool = False,
    ) -> float:
        built_at = time.monotonic()
        try:
            snapshot = await self._snapshot_builder(agent_id)
            frame, cursor = select_avatar_telemetry_frame(
                snapshot,
                previous_snapshot=self._frame_cursors.get(agent_id),
                tick_count=self._tick_counts.get(agent_id, 0),
                diff_enabled=self._diff_enabled,
                diff_threshold=self._diff_threshold,
                full_every_n=self._full_every_n,
                force_full=force_full,
            )
            if frame is not None:
                self._frame_cursors[agent_id] = cursor
                await self.on_local_telemetry_frame(
                    agent_id=frame.agent_id,
                    frame_type=frame.frame_type,
                    payload=frame.data,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Federation avatar telemetry snapshot build failed agent=%s "
                "exception_type=%s; frame dropped and producer will retry",
                agent_id,
                type(exc).__name__,
            )
        return built_at

    async def _cleanup_producers(self) -> None:
        tasks = tuple(self._producer_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._producer_tasks.clear()

    def _observe_producer_done(
        self,
        agent_id: str,
        task: asyncio.Task[None],
    ) -> None:
        exception_type = "none"
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            exception_type = type(exc).__name__
        if self._running:
            logger.warning(
                "Federation avatar telemetry producer stopped agent=%s "
                "exception_type=%s; that agent's federation telemetry "
                "producer stopped and relay restart required",
                agent_id,
                exception_type,
            )

    def _reset_volatile_state(self) -> None:
        self._running = False
        self._rate.clear()
        self._frame_cursors.clear()
        self._tick_counts.clear()
        self._sequences.clear()
        self._stream_id = None

    def _claim_attempt(self, peer_id: str) -> bool:
        now = time.monotonic()
        window = self._rate.setdefault(peer_id, deque())
        cutoff = now - 1.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max_per_sec:
            return False
        window.append(now)
        return True

    def _require_stopped(self) -> None:
        if self._running or self._lifecycle_lock.locked():
            raise RuntimeError("telemetry_relay_running")

    async def _default_emit(
        self,
        peer_id: str,
        payload: dict[str, Any],
    ) -> bool:
        self._dispatch_log.append((peer_id, copy.deepcopy(payload)))
        if len(self._dispatch_log) > MAX_DISPATCH_LOG_ENTRIES:
            del self._dispatch_log[:-MAX_DISPATCH_LOG_ENTRIES]
        return True


class RemoteAvatarTelemetryCache:
    """Volatile ordered cache of validated remote avatar stream state."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if (
            type(max_entries) is not int
            or not 1 <= max_entries <= MAX_REMOTE_AVATAR_TELEMETRY_ENTRIES
        ):
            raise ValueError("remote_avatar_cache_size_invalid")
        self._max_entries = max_entries
        self._entries: OrderedDict[
            tuple[str, str],
            _RemoteAvatarTelemetryEntry,
        ] = OrderedDict()

    async def ingest(
        self,
        source_node: str,
        payload: dict[str, Any],
    ) -> None:
        """Accept one semantically valid contiguous frame without side effects."""
        if not is_safe_relay_node_id(source_node):
            return
        parsed = parse_avatar_telemetry_payload(payload)
        if parsed is None:
            return
        agent_id = parsed["agent_id"]
        frame_type = parsed["frame_type"]
        stream_id = parsed["stream_id"]
        sequence = parsed["sequence"]
        data = parsed["data"]
        key = (source_node, agent_id)
        current = self._entries.get(key)
        if current is None:
            if frame_type != "snapshot":
                return
            snapshot = data
        elif stream_id != current.stream_id:
            if frame_type != "snapshot":
                return
            snapshot = data
        else:
            if sequence <= current.sequence:
                return
            if frame_type == "snapshot":
                snapshot = data
            else:
                if sequence != current.sequence + 1:
                    return
                snapshot = {**current.snapshot, **data}
        entry = _RemoteAvatarTelemetryEntry(
            source_node=source_node,
            agent_id=agent_id,
            stream_id=stream_id,
            sequence=sequence,
            last_frame_type=frame_type,
            received_at=time.time(),
            snapshot=snapshot,
        )
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def get(
        self,
        source_node: str,
        agent_id: str,
    ) -> dict[str, Any] | None:
        """Return a detached cache record without changing LRU authority."""
        entry = self._entries.get((source_node, agent_id))
        return None if entry is None else self._to_public(entry)

    def list(self) -> list[dict[str, Any]]:
        """Return detached records in deterministic composite-key order."""
        return [
            self._to_public(self._entries[key])
            for key in sorted(self._entries)
        ]

    def clear(self) -> None:
        """Clear all volatile remote stream state."""
        self._entries.clear()

    @staticmethod
    def _to_public(entry: _RemoteAvatarTelemetryEntry) -> dict[str, Any]:
        snapshot = copy.deepcopy(entry.snapshot)
        return {
            "source_node": entry.source_node,
            "agent_id": entry.agent_id,
            "stream_id": entry.stream_id,
            "sequence": entry.sequence,
            "last_frame_type": entry.last_frame_type,
            "received_at": entry.received_at,
            "snapshot": {"agent_id": entry.agent_id, **snapshot},
        }
