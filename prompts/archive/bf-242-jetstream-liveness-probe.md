# BF-242: JetStream Liveness Probe

**Status:** Ready for builder  
**Scope:** OSS (`src/probos/mesh/nats_bus.py`, `tests/test_bf242_jetstream_liveness.py`)

## Context

JetStream can become unresponsive while the NATS TCP connection stays healthy. When this happens, every `js_publish()` call burns ~11s (5s timeout × 2 attempts + 0.5s backoff) before falling back to core NATS via BF-230. During dream cycles (20+ events in burst), this creates minutes of stalled publishes.

**Why existing fixes don't cover this:**
- BF-241 (`_on_reconnected`) only fires on TCP reconnection — no TCP drop means no recovery trigger
- BF-230 (fallback) handles individual publishes but doesn't trigger stream recreation or reduce timeout overhead
- `health()` reports TCP connected + JetStream enabled, never probes whether JetStream actually works

**Observed failure pattern:** ProbOS runs normally for hours, then all JetStream publishes start failing with "nats: no response from stream" while core NATS stays connected. BF-230 fallback works, but the 11s penalty per event degrades system responsiveness.

**Fix:** Track consecutive JetStream publish failures. After a threshold, trigger `_recover_jetstream()`. If recovery fails, disable JetStream temporarily so publishes go straight to core NATS (no timeout penalty) until the next successful recovery or reconnect.

## Implementation

### 1. Add failure tracking state to `NATSBus.__init__()` in `src/probos/mesh/nats_bus.py`

After the existing `_stream_configs` field (line 115), add:

```python
        # BF-242: JetStream liveness probe — consecutive failure tracking
        self._js_consecutive_failures: int = 0
        self._js_failure_threshold: int = 3  # Trigger recovery after N consecutive failures
        self._js_suspended: bool = False  # True = JetStream disabled, publishes go straight to core NATS
        self._js_recovery_task: asyncio.Task | None = None  # Single-flight guard for recovery
```

### 2. Add `_suspend_jetstream()` method

Add after `_recover_jetstream()` (after line 317):

```python
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
```

### 3. Add `_resume_jetstream()` method

Add immediately after `_suspend_jetstream()`:

```python
    def _resume_jetstream(self) -> None:
        """BF-242: Re-enable JetStream after successful recovery."""
        if self._js_suspended:
            self._js_suspended = False
            self._js_consecutive_failures = 0
            logger.info("BF-242: JetStream resumed — publishes restored to at-least-once delivery.")
```

### 4. Modify `js_publish()` — add failure counting and suspension bypass

Replace the `js_publish()` method body (lines 504–554) with the version below. Changes are:
- Early exit when `_js_suspended` (bypass straight to core NATS, no timeout)
- Increment `_js_consecutive_failures` on failure
- Reset counter on success
- Trigger `_try_jetstream_recovery()` when threshold exceeded

```python
    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish to a JetStream subject (durable, at-least-once).

        BF-230: Retry once on transient failure, then fall back to core NATS.
        BF-242: Track consecutive failures. After threshold, suspend JetStream
        and trigger recovery. While suspended, publishes bypass directly to
        core NATS (no timeout penalty).
        """
        if not self._js:
            await self.publish(subject, data, headers=headers)
            return

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
            return

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
                return  # Success
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
```

### 5. Add `_on_recovery_task_done()` callback

Add after `_resume_jetstream()`:

```python
    def _on_recovery_task_done(self, task: asyncio.Task) -> None:
        """BF-242: Surface exceptions from background recovery task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("BF-242: Recovery task failed with unhandled exception: %s", exc)
```

### 6. Add `_try_jetstream_recovery()` method

Add after `_resume_jetstream()`:

```python
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
```

### 7. Modify `_on_reconnected()` — resume JetStream on reconnect

In `_on_reconnected()` (line 319), after the existing `_recover_jetstream()` call, add a resume call. Replace the method body:

```python
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
```

### 8. Update `health()` — report suspension state

In `health()` (line 769), add `js_suspended` to the returned dict. In the connected branch, add after `"jetstream"`:

```python
            "js_suspended": self._js_suspended,
```

Full connected return block becomes:

```python
        return {
            "connected": self.connected,
            "status": "connected" if self.connected else "disconnected",
            "url": self._nc.connected_url or self._url,
            "reconnects": getattr(self._nc, "reconnected_count", 0),
            "jetstream": self._js is not None,
            "js_suspended": self._js_suspended,
            "subscriptions": len(self._subscriptions),
        }
```

### 9. Add MockNATSBus parity — `src/probos/mesh/nats_bus.py`

In `MockNATSBus.__init__()` (line 845), add after `_stream_configs`:

```python
        self._js_suspended: bool = False  # BF-242 parity
```

In `MockNATSBus.health()` (line 1113), add `js_suspended` to the returned dict:

```python
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
```

**Rationale:** MockNATSBus must mirror NATSBus fields used by production code (e.g. `health()` callers, test helpers that inspect `_js_suspended`). Without this, tests using MockNATSBus silently diverge from prod behavior.

### 10. Tests — `tests/test_bf242_jetstream_liveness.py`

Create this test file:

```python
"""BF-242: JetStream liveness probe — consecutive failure tracking + recovery.

Tests cover:
- Consecutive failure counter increments on js_publish failure
- Counter resets on success
- Recovery triggered after threshold consecutive failures
- JetStream suspended during recovery
- JetStream resumed after successful recovery + probe
- JetStream stays suspended when probe fails
- Recovery failure keeps bus suspended
- Suspended publishes bypass to core NATS (no timeout)
- Reconnect resumes suspended JetStream
- health() reports js_suspended state
- Single-flight guard prevents concurrent recovery tasks
- Suspended + core NATS failure doesn't propagate
- MockNATSBus parity
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_bus():
    """Build a NATSBus with mocked internals for unit testing."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._url = "nats://localhost:4222"
    bus._subject_prefix = "probos.test"
    bus._js = MagicMock()  # Truthy — JetStream enabled
    bus._nc = MagicMock()
    bus._nc.is_connected = True
    bus._nc.connected_url = "nats://localhost:4222"
    bus._connected = True
    bus._started = True
    bus._resubscribing = False
    bus._active_subs = []
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
    ]
    bus._subscriptions = []
    bus._prefix_change_callbacks = []
    bus._js_publish_timeout = 5.0
    bus._jetstream_enabled = True
    # BF-242
    bus._js_consecutive_failures = 0
    bus._js_failure_threshold = 3
    bus._js_suspended = False
    bus._js_recovery_task = None
    return bus


@pytest.mark.asyncio
async def test_failure_counter_increments():
    """Consecutive failure counter increments after both attempts fail."""
    bus = _make_bus()
    bus._js.publish = AsyncMock(side_effect=Exception("no response from stream"))
    bus.publish = AsyncMock()  # core NATS fallback

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures == 1
    assert bus.publish.call_count == 1  # fell back to core NATS


@pytest.mark.asyncio
async def test_failure_counter_resets_on_success():
    """Counter resets to 0 on a successful JetStream publish."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2
    bus._js.publish = AsyncMock()  # success

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_recovery_triggered_at_threshold():
    """Consecutive failures reaching threshold sets condition for recovery."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2  # One more will hit threshold of 3
    bus._js.publish = AsyncMock(side_effect=Exception("no response"))
    bus.publish = AsyncMock()

    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus._js_consecutive_failures >= bus._js_failure_threshold


@pytest.mark.asyncio
async def test_suspend_sets_flag():
    """_suspend_jetstream sets _js_suspended to True."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3
    bus._suspend_jetstream()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_resume_clears_state():
    """_resume_jetstream clears suspended flag and resets counter."""
    bus = _make_bus()
    bus._js_suspended = True
    bus._js_consecutive_failures = 5
    bus._resume_jetstream()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_suspended_bypasses_to_core_nats():
    """When suspended, js_publish goes straight to core NATS — no JS attempt."""
    bus = _make_bus()
    bus._js_suspended = True
    bus.publish = AsyncMock()

    await bus.js_publish("system.events.test", {"type": "test"})

    # JS publish should NOT have been called
    bus._js.publish.assert_not_called()
    # Core NATS publish SHOULD have been called
    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_try_recovery_resumes_on_probe_success():
    """Successful recovery + probe resumes JetStream."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(return_value=MagicMock())

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_try_recovery_stays_suspended_on_probe_failure():
    """Failed probe keeps JetStream suspended."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(side_effect=Exception("timeout"))

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_reconnect_resumes_suspended_jetstream():
    """_on_reconnected resumes JetStream even if it was suspended."""
    bus = _make_bus()
    bus._js_suspended = True
    bus._js_consecutive_failures = 5

    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()

    await bus._on_reconnected()

    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


def test_health_reports_suspension():
    """health() includes js_suspended field."""
    bus = _make_bus()
    bus._js_suspended = True

    h = bus.health()
    assert h["js_suspended"] is True

    bus._js_suspended = False
    h = bus.health()
    assert h["js_suspended"] is False


@pytest.mark.asyncio
async def test_suspend_is_idempotent():
    """Calling _suspend_jetstream multiple times doesn't change state."""
    bus = _make_bus()
    bus._suspend_jetstream()
    bus._suspend_jetstream()
    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_resume_is_idempotent():
    """Calling _resume_jetstream when not suspended is a no-op."""
    bus = _make_bus()
    assert bus._js_suspended is False
    bus._resume_jetstream()
    assert bus._js_suspended is False
    assert bus._js_consecutive_failures == 0


@pytest.mark.asyncio
async def test_recovery_failure_stays_suspended():
    """If _recover_jetstream raises, bus stays suspended."""
    bus = _make_bus()
    bus._js_consecutive_failures = 3

    bus.recreate_stream = AsyncMock(side_effect=Exception("NATS server gone"))
    bus.delete_consumer = AsyncMock()

    await bus._try_jetstream_recovery()

    assert bus._js_suspended is True


@pytest.mark.asyncio
async def test_single_flight_recovery():
    """Only one recovery task runs at a time."""
    bus = _make_bus()
    bus._js_consecutive_failures = 2  # Next failure hits threshold
    bus._js.publish = AsyncMock(side_effect=Exception("no response"))
    bus.publish = AsyncMock()  # core NATS fallback
    bus.recreate_stream = AsyncMock()
    bus.delete_consumer = AsyncMock()
    bus._js.stream_info = AsyncMock(return_value=MagicMock())

    # Trigger threshold — first recovery task spawns
    await bus.js_publish("system.events.test", {"type": "test1"})
    assert bus._js_recovery_task is not None
    first_task = bus._js_recovery_task

    # Let recovery complete
    await first_task

    # Trigger again — counter was reset by resume, need 3 more failures
    bus._js_suspended = False  # Simulate resume completed
    bus._js_consecutive_failures = 2
    await bus.js_publish("system.events.test", {"type": "test2"})

    # New task spawned (old one is .done())
    assert bus._js_recovery_task is not first_task or first_task.done()


@pytest.mark.asyncio
async def test_suspended_core_nats_failure_no_propagation():
    """When suspended, core NATS failure is caught — no exception propagates."""
    bus = _make_bus()
    bus._js_suspended = True
    bus.publish = AsyncMock(side_effect=Exception("NATS down"))

    # Should NOT raise — error is logged and swallowed
    await bus.js_publish("system.events.test", {"type": "test"})

    assert bus.publish.call_count == 1


@pytest.mark.asyncio
async def test_mock_bus_parity():
    """MockNATSBus has js_suspended field and reports it in health()."""
    from probos.mesh.nats_bus import MockNATSBus

    mock = MockNATSBus()
    assert mock._js_suspended is False

    h = mock.health()
    assert "js_suspended" in h
    assert h["js_suspended"] is False
```

## Tracker Updates

### PROGRESS.md

Add after the BF-241 line:

```
BF-242 CLOSED. JetStream liveness probe — consecutive failure counter triggers recovery + suspension. Suspended JetStream bypasses to core NATS (no timeout penalty). Single-flight guard on recovery task. Probe verifies recovery success via stream_info(). MockNATSBus parity. Reconnect auto-resumes. 16 new tests.
```

### docs/development/roadmap.md

Add to Bug Tracker table:

```
| BF-242 | JetStream liveness probe: detect silent failures, suspend + recover | Closed |
```

### DECISIONS.md

Add entry:

```
### BF-242: JetStream Liveness Probe — Circuit Breaker Pattern

**Decision:** When JetStream becomes unresponsive without TCP disconnection, track consecutive publish failures. After 3 consecutive failures (all attempts exhausted per-publish), suspend JetStream and trigger asynchronous recovery. While suspended, publishes bypass directly to core NATS with no timeout penalty. Recovery recreates streams/consumers, then probes with `stream_info()`. On success, JetStream resumes. On failure, stays suspended until next TCP reconnect.

**Rationale:**
- **Why 3?** BF-230 already handles transient single failures (2-attempt retry + fallback). Three consecutive all-attempts-exhausted failures indicate a systemic JetStream problem, not transient jitter. Lower threshold risks false positives from burst packet loss; higher threshold accumulates 33s+ of timeout penalty (11s × N) before recovery.
- **Why single-flight guard?** Without it, concurrent publishes crossing the threshold simultaneously would spawn N recovery tasks — each recreating streams, probing, and potentially racing on `_js_suspended` state. Storing the `asyncio.Task` reference and checking `.done()` ensures exactly one recovery runs at a time.
- **Why `stream_info(name)` for probing?** Direct stream metadata query — lightweight, authoritative, doesn't depend on subject routing. `find_stream_name_by_subject()` requires subject → stream resolution which can fail for reasons unrelated to JetStream health.
- **Why probe only the first stream?** Pragmatic — if the JetStream subsystem is down, any stream query will fail. If one stream responds, the subsystem is functional. Probing all streams adds latency for no diagnostic value.
- **Why suspend (not just recover)?** During recovery, concurrent publishes would still attempt JetStream → timeout → fallback. Suspension eliminates the timeout penalty immediately. "Recovery is async; current publish falls through to core NATS immediately."
- **Precedent:** Extends BF-229/230/231/232/241 NATS resilience stack. Circuit breaker pattern (Nygard, "Release It!").

**Alternatives considered:**
- Periodic health probe (timer-based): rejected — adds unnecessary background traffic when JetStream is healthy. Reactive (failure-triggered) is cheaper.
- Exponential backoff on threshold: rejected — over-complicated for a binary state (JS works or doesn't). Simple counter + hard threshold is more predictable.
```
