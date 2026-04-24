# BF-230: JetStream Publish Resilience — Retry + Fallback on Timeout

**Issue:** [#335](https://github.com/seangalliher/ProbOS/issues/335)
**Status:** Ready for builder
**Priority:** Medium
**Files:** `src/probos/mesh/nats_bus.py`, `src/probos/config.py`, `tests/test_ad637a_nats_foundation.py`

## Problem

`NATSBus.js_publish()` silently drops events when JetStream publish times out. Under CPU load, NATS server may not ack within the default timeout (~2s), producing `nats: no response from stream`. The error is logged but the event is permanently lost — no retry, no fallback.

**Observed in production:**
```
ERROR  probos.mesh.nats_bus  JetStream publish to probos.did_probos_d9832d8c-...system.events.sub_task_chain_completed failed: nats: no response from stream
ERROR  probos.mesh.nats_bus  JetStream publish to probos.did_probos_d9832d8c-...system.events.task_execution_complete failed: nats: no response from stream
```

Errors appeared during high CPU load on the host machine.

## Root Cause

`NATSBus.js_publish()` at around line 432 of `src/probos/mesh/nats_bus.py`:

```python
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
```

Problems:
1. **No timeout parameter** — uses nats-py default (~2s), too tight under load
2. **No retry** — transient timeout = permanent event loss
3. **No fallback** — the `_js is None` path falls back to core NATS, but the failure path does not
4. **Silent swallow** — exception is logged but swallowed; caller never knows

## What This Does NOT Change

- `_emit_event()` in `runtime.py` — still fire-and-forget via `create_task()`. This fix makes `js_publish` itself more resilient, not the calling pattern.
- `MockNATSBus.js_publish()` — mock delegates to `publish()` already. No change needed.
- `publish_raw()` / `subscribe_raw()` — federation paths, not affected.
- Stream creation/update logic in `ensure_stream()` — separate concern.
- `_emit_event_local()` — in-memory fallback path, unchanged.

---

## Section 1: Add `js_publish_timeout` to NatsConfig

**File:** `src/probos/config.py`

Add one field to `NatsConfig` (around line 1036, after `subject_prefix`):

```python
    subject_prefix: str = "probos.local"

    # BF-230: JetStream publish timeout (seconds) — raised from nats-py default
    # to tolerate CPU load spikes. Applied per-publish, not connection-level.
    js_publish_timeout: float = 5.0
```

---

## Section 2: Pass timeout through NATSBus constructor

**File:** `src/probos/mesh/nats_bus.py`

### 2a: Add parameter to `__init__`

Current `__init__` signature (around line 88):

```python
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
```

Add `js_publish_timeout: float = 5.0` parameter after `jetstream_enabled`. Store as `self._js_publish_timeout = js_publish_timeout`.

### 2b: Wire in startup

**File:** `src/probos/startup/nats.py`

Current constructor call (around line 32):

```python
    bus = NATSBus(
        url=config.nats.url,
        connect_timeout=config.nats.connect_timeout_seconds,
        max_reconnect_attempts=config.nats.max_reconnect_attempts,
        reconnect_time_wait=config.nats.reconnect_time_wait_seconds,
        drain_timeout=config.nats.drain_timeout_seconds,
        subject_prefix=config.nats.subject_prefix,
        jetstream_enabled=config.nats.jetstream_enabled,
    )
```

Add `js_publish_timeout=config.nats.js_publish_timeout,` after the `jetstream_enabled` line.

---

## Section 3: Rewrite `js_publish()` with retry + fallback

**File:** `src/probos/mesh/nats_bus.py`

Replace the current `js_publish()` method (around line 432) with:

```python
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
```

**Note:** `asyncio` is already imported at the top of the file (line 11 of `nats_bus.py`).

**nats-py version:** `JetStreamContext.publish()` accepts `timeout=` as a keyword argument in nats-py >= 2.6.0. The `timeout` is the deadline for receiving the PubAck from the stream (not a connection timeout). ProbOS pins `nats-py>=2.9` in `pyproject.toml` (line 35).

**Design rationale:**
- **1 retry, not infinite** — this is fire-and-forget event emission. Blocking the event loop with retries would be worse than dropping the event.
- **0.5s backoff** — enough for a transient CPU spike to pass, short enough to not block the agent's cognitive loop. Under sustained load, concurrent failing publishes produce concurrent sleeping retry tasks (all sleeping simultaneously, so wall-clock impact bounded at 0.5s). Acceptable for transient spikes; if observed at scale, add a bounded retry semaphore in a follow-up.
- **Fallback to core NATS** — core NATS publish doesn't require stream acknowledgment. For subjects with parallel core subscribers, the event is still delivered (at-most-once). For JetStream-only subjects (e.g., WARDROOM durable consumers, cognitive queue dispatch), the fallback is effectively a no-op — the event reaches the NATS server but no JetStream consumer receives it. The fallback's real value is: doesn't crash, leaves a server-side trail for correlation with the WARNING log, and preserves delivery for any subjects that do have core subscribers. It does NOT guarantee delivery for JetStream-only paths.
- **Scope boundary**: This fix protects *publishers* from timeout-induced event loss. It does not protect *subscribers* from slow message delivery under load — that is a separate concern.
- **Log levels**: WARNING for retryable failure (expected under load), ERROR only if both paths fail (actionable — check NATS server).

---

## Section 4: Tests

**File:** `tests/test_ad637a_nats_foundation.py`

Add a new test class after the existing `TestJSPublishFallback` class (around line 371).

**Important:** Tests that trigger the retry path must mock `asyncio.sleep` to avoid 0.5s real delays in CI. Use `@patch("probos.mesh.nats_bus.asyncio.sleep", new_callable=AsyncMock)` — this works because `asyncio` is module-level imported in `nats_bus.py` (line 11). `patch` and `AsyncMock` are already imported in the test file (line 10). Add `import logging` to test file imports (needed for `caplog.at_level`).

**Test fixture note:** All tests for BF-230 retry/fallback use the real `NATSBus` class with mocked `_js`, NOT `MockNATSBus` (which has no retry/fallback logic). The `NATSBus.publish()` fallback path requires three preconditions: `bus._connected = True`, `bus._nc` set to a mock, and `bus._nc.is_connected = True`. All three must be set on the test bus instance — otherwise `publish()` short-circuits before the side_effect fires, and the test passes vacuously. The `_subject_prefix` is set in `__init__` (defaults to `"probos.local"`) so `_full_subject()` works without `start()`.

```python
# ---------------------------------------------------------------------------
# Tests: BF-230 — JetStream publish resilience
# ---------------------------------------------------------------------------


class TestJSPublishResilience:

    @pytest.mark.asyncio
    @patch("probos.mesh.nats_bus.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_first_failure(self, mock_sleep):
        """BF-230: js_publish retries once on transient failure."""
        bus = NATSBus(jetstream_enabled=True, js_publish_timeout=5.0)
        bus._connected = True

        mock_js = MagicMock()
        # First call fails, second succeeds
        mock_js.publish = AsyncMock(
            side_effect=[Exception("nats: no response from stream"), None]
        )
        bus._js = mock_js

        await bus.js_publish("system.events.test", {"data": "value"})

        assert mock_js.publish.call_count == 2
        mock_sleep.assert_awaited_once_with(0.5)

    @pytest.mark.asyncio
    @patch("probos.mesh.nats_bus.asyncio.sleep", new_callable=AsyncMock)
    async def test_fallback_to_core_after_retry_exhausted(self, mock_sleep):
        """BF-230: Falls back to core NATS when JetStream fails twice."""
        bus = NATSBus(jetstream_enabled=True, js_publish_timeout=5.0)
        bus._connected = True
        bus._nc = MagicMock()
        bus._nc.is_connected = True
        bus._nc.publish = AsyncMock()

        mock_js = MagicMock()
        mock_js.publish = AsyncMock(
            side_effect=Exception("nats: no response from stream")
        )
        bus._js = mock_js

        await bus.js_publish("system.events.test", {"data": "value"})

        # JetStream tried twice
        assert mock_js.publish.call_count == 2
        # Fell back to core NATS
        bus._nc.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_passed_to_js_publish(self):
        """BF-230: Configurable timeout is passed to nats-py."""
        bus = NATSBus(jetstream_enabled=True, js_publish_timeout=10.0)
        bus._connected = True

        mock_js = MagicMock()
        mock_js.publish = AsyncMock()
        bus._js = mock_js

        await bus.js_publish("system.events.test", {"data": "value"})

        call_kwargs = mock_js.publish.call_args
        assert call_kwargs.kwargs.get("timeout") == 10.0

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        """BF-230: Successful publish does not retry."""
        bus = NATSBus(jetstream_enabled=True, js_publish_timeout=5.0)
        bus._connected = True

        mock_js = MagicMock()
        mock_js.publish = AsyncMock()
        bus._js = mock_js

        await bus.js_publish("system.events.test", {"data": "value"})

        assert mock_js.publish.call_count == 1

    @pytest.mark.asyncio
    @patch("probos.mesh.nats_bus.asyncio.sleep", new_callable=AsyncMock)
    async def test_total_failure_logs_error(self, mock_sleep, caplog):
        """BF-230: When both JetStream and core NATS fail, event dropped with ERROR."""
        bus = NATSBus(jetstream_enabled=True, js_publish_timeout=5.0)
        bus._connected = True
        bus._nc = MagicMock()
        bus._nc.is_connected = True
        bus._nc.publish = AsyncMock(side_effect=Exception("NATS down"))

        mock_js = MagicMock()
        mock_js.publish = AsyncMock(
            side_effect=Exception("nats: no response from stream")
        )
        bus._js = mock_js

        # Should not raise — fire-and-forget
        with caplog.at_level(logging.ERROR):
            await bus.js_publish("system.events.test", {"data": "value"})

        # JetStream tried twice, core tried once
        assert mock_js.publish.call_count == 2
        assert bus._nc.publish.call_count == 1
        # Verify ERROR log with BF-230 marker
        assert "BF-230" in caplog.text

    @pytest.mark.asyncio
    async def test_default_timeout_is_5_seconds(self):
        """BF-230: Default js_publish_timeout is 5.0s."""
        bus = NATSBus()
        assert bus._js_publish_timeout == 5.0
```

### Existing test impact

- `TestJSPublishFallback.test_fallback_when_no_jetstream` (around line 374) — **no change needed**. Tests the `_js is None` path which is unchanged.
- `TestMockNATSBus.test_js_publish_delegates_to_publish` (around line 155) — **no change needed**. Tests MockNATSBus which is unchanged.
- All tests in `test_bf229_did_subject_sanitization.py` — **no change needed**. They test subject sanitization, not publish resilience.

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad637a_nats_foundation.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
BF-230 CLOSED. JetStream publish silently drops events under CPU load — no retry, no fallback to core NATS. Fix: js_publish() retries once (0.5s backoff), then falls back to core NATS publish, only ERROR if both fail. Configurable timeout (default 5s) via NatsConfig.js_publish_timeout. 6 new tests. Issue #335.
```

### DECISIONS.md
Add entry:
```
**BF-230: js_publish resilience — bounded retry + degrade-to-core-NATS.** Chose 1 retry with 0.5s backoff + fallback to core NATS publish over alternatives (local buffer-and-replay, unbounded retry). Buffer would require persistence and replay logic — deferred until needed. Fallback to core NATS is best-effort: JetStream-only subscribers (WARDROOM durable, cognitive queue) will NOT receive the event via the fallback path. The fallback's value is crash prevention + server-side trail, not delivery guarantee.
```

### docs/development/roadmap.md
Add to Bug Tracker section:
```
| BF-230 | JetStream publish silent failure under CPU load | Closed | #335 |
```
