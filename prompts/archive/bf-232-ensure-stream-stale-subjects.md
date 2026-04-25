# BF-232: ensure_stream() inherits stale subject filters from previous boot

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Related:** BF-231 (set_subject_prefix delete-then-create), BF-229 (DID sanitization), BF-230 (js_publish fallback)
**Files:** `src/probos/mesh/nats_bus.py` (EDIT), `src/probos/startup/nats.py` (EDIT), `tests/test_bf232_ensure_stream_stale_subjects.py` (NEW)

## Problem

JetStream publishes to `system.events.sub_task_chain_completed` and `system.events.task_execution_complete` persistently fail with "no response from stream", falling back to core NATS. This happens on every boot, not just after reset.

**Root cause:** `ensure_stream()` uses an add-or-update pattern (lines 617–624) that silently inherits stale subject filters:

1. Previous boot leaves `SYSTEM_EVENTS` stream on NATS server with subjects `probos.did_probos_OLD.system.events.>`
2. New boot Phase 2 calls `ensure_stream("SYSTEM_EVENTS", ["system.events.>"])` → `add_stream()` fails (stream exists)
3. Falls to `update_stream()` — which **silently fails to change subject filters** on some NATS server versions (BF-231 finding)
4. Stream keeps old DID subjects. New publishes don't match → "no response from stream"
5. Phase 7 `set_subject_prefix()` does delete-then-create (BF-231 fix), but if `_delete_stream()` fails it logs at DEBUG and returns False — the failure is invisible
6. `ensure_stream()` called by `set_subject_prefix()` hits the same add-or-update path → same silent failure

BF-231 fixed `set_subject_prefix()` but left `ensure_stream()` itself using the broken pattern.

**Impact:** Non-critical — BF-230's fallback delivers events via core NATS. But JetStream's at-least-once delivery guarantee is bypassed, and the warnings pollute logs on every agent task completion.

**Completion note:** After BF-232 + BF-229/230/231, the entire class of NATS subject-filter and stream-state issues is closed. "no response from stream" should be a real signal again, not background noise.

## Design — Split ensure_stream / recreate_stream

The current `ensure_stream()` name promises "make this stream exist with these subjects (idempotent, non-destructive)." Changing it to always delete would break that API contract — future callers (health checks, recovery routines, federation handshakes) would unknowingly nuke retained messages.

**Solution:** Two methods, two names, two semantics:

- **`ensure_stream()`** — keeps the current add-or-update-on-conflict semantics. Non-destructive. Used by future callers that want idempotent existence checks.
- **`recreate_stream()`** (NEW) — delete-then-create. Explicitly destructive. Used by Phase 2 startup and `set_subject_prefix()` where stale subjects must be replaced.

**Callers:**
- `startup/nats.py` Phase 2: change from `ensure_stream()` → `recreate_stream()`
- `set_subject_prefix()`: change the explicit `_delete_stream` + `ensure_stream` loop to just `recreate_stream()` (which handles both internally)

---

## Section 1: Add `recreate_stream()` method

**File:** `src/probos/mesh/nats_bus.py`, `NATSBus` class

Add after `ensure_stream()` (after line ~628):

```python
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

        On add_stream failure after successful delete, the stream is left
        absent and the config tracking entry is stale. Next
        set_subject_prefix() or recreate_stream() call self-heals.
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
```

Also add `recreate_stream` to `InMemoryNATSBus` — delegate to `ensure_stream` (no NATS server, same behavior):

After `InMemoryNATSBus.ensure_stream()` (line ~977):

```python
    async def recreate_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        """BF-232: In-memory — same as ensure_stream (no server state to clear)."""
        await self.ensure_stream(name, subjects, max_msgs=max_msgs, max_age=max_age)
```

---

## Section 2: Update `set_subject_prefix()` to use `recreate_stream()`

**File:** `src/probos/mesh/nats_bus.py`, `NATSBus.set_subject_prefix()` method

Replace the explicit delete-then-ensure loop (lines 160–180):

```python
        if self.connected and self._stream_configs:
            logger.info(
                "set_subject_prefix: recreating %d streams for new prefix",
                len(self._stream_configs),
            )
            for sc in self._stream_configs:
                stream_name = sc["name"]
                try:
                    await self._delete_stream(stream_name)
                    await self.ensure_stream(
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
```

With:

```python
        # BF-232: Use recreate_stream which handles delete-then-create internally.
        # Replaces BF-231's explicit _delete_stream + ensure_stream loop.
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
```

Key: the explicit `_delete_stream(stream_name)` call is **removed**. `recreate_stream()` handles deletion internally. This prevents double-delete which would cause spurious WARNING logs (see Section 3).

---

## Section 3: Promote `_delete_stream()` log level with "not found" filter

**File:** `src/probos/mesh/nats_bus.py`, `NATSBus._delete_stream()` method (line ~640)

Replace:

```python
        except Exception as e:
            logger.debug("NATSBus: Stream delete failed (%s): %s", name, e)
            return False
```

With:

```python
        except Exception as e:
            msg = str(e).lower()
            if "not found" in msg or "10059" in msg:
                logger.debug("NATSBus: Stream %s not found (already absent)", name)
            else:
                logger.warning("BF-232: Stream delete failed (%s): %s", name, e)
            return False
```

"Not found" is benign (first boot, clean NATS server). Real failures (permissions, server errors) are promoted to WARNING for visibility.

---

## Section 4: Update Phase 2 startup to use `recreate_stream()`

**File:** `src/probos/startup/nats.py`

Replace the three `ensure_stream` calls (lines 55–73):

```python
            await bus.ensure_stream(
                "SYSTEM_EVENTS",
                ["system.events.>"],
                max_msgs=50000,
                max_age=3600,
            )
            await bus.ensure_stream(
                "WARDROOM",
                ["wardroom.events.>"],
                max_msgs=10000,
                max_age=3600,
            )
            await bus.ensure_stream(
                "INTENT_DISPATCH",
                ["intent.dispatch.>"],
                max_msgs=10000,
                max_age=300,       # 5 min retention — stale notifications are worthless
            )
            logger.info("Startup [nats]: JetStream streams ensured (SYSTEM_EVENTS, WARDROOM, INTENT_DISPATCH)")
```

With:

```python
            # BF-232: Use recreate_stream to clear stale subject filters from
            # previous boots. ensure_stream's update_stream fallback silently
            # fails to change subjects on some NATS versions.
            await bus.recreate_stream(
                "SYSTEM_EVENTS",
                ["system.events.>"],
                max_msgs=50000,
                max_age=3600,
            )
            await bus.recreate_stream(
                "WARDROOM",
                ["wardroom.events.>"],
                max_msgs=10000,
                max_age=3600,
            )
            await bus.recreate_stream(
                "INTENT_DISPATCH",
                ["intent.dispatch.>"],
                max_msgs=10000,
                max_age=300,       # 5 min retention — stale notifications are worthless
            )
            logger.info("Startup [nats]: JetStream streams recreated (SYSTEM_EVENTS, WARDROOM, INTENT_DISPATCH)")
```

---

## Section 5: No changes to `ensure_stream()` or `InMemoryNATSBus`

- **`ensure_stream()`** — unchanged. Keeps its add-or-update semantics for future non-destructive callers.
- **`InMemoryNATSBus.ensure_stream()`** — unchanged. No NATS server interaction.

---

## Section 6: Tests

**File:** `tests/test_bf232_ensure_stream_stale_subjects.py` (NEW)

```python
"""Tests for BF-232: recreate_stream deletes stale streams before creating."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.mesh.nats_bus import NATSBus


@pytest.fixture
def bus():
    """NATSBus with mocked NATS connection."""
    b = NATSBus(url="nats://localhost:4222")
    b._connected = True
    b._nc = MagicMock()
    b._nc.is_connected = True
    b._js = AsyncMock()
    b._subject_prefix = "probos.local"
    return b


class TestBF232RecreateStream:

    @pytest.mark.asyncio
    async def test_recreate_stream_deletes_before_create(self, bus):
        """BF-232: recreate_stream deletes existing stream before creating."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        bus._js.delete_stream.assert_called_once_with("SYSTEM_EVENTS")
        bus._js.add_stream.assert_called_once()
        config = bus._js.add_stream.call_args[0][0]
        assert "probos.local.system.events.>" in config.subjects

    @pytest.mark.asyncio
    async def test_recreate_stream_delete_failure_nonfatal(self, bus):
        """BF-232: Stream delete failure (not found) doesn't prevent create."""
        bus._js.delete_stream = AsyncMock(side_effect=Exception("stream not found"))
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # Delete failed (benign), but create still attempted
        bus._js.add_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_stream_from_previous_boot_replaced(self, bus):
        """BF-232: Boot finds stale stream, replaces it cleanly."""
        bus._js.delete_stream = AsyncMock()  # Succeeds (stream exists from prev boot)
        bus._js.add_stream = AsyncMock()  # Succeeds (clean creation)

        # Simulate: Phase 2 recreate_stream call after previous boot left stale state
        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # Old stream deleted, new stream created
        bus._js.delete_stream.assert_called_once_with("SYSTEM_EVENTS")
        bus._js.add_stream.assert_called_once()
        # Critically: update_stream should NEVER be called — the broken code path is gone
        bus._js.update_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_prefix_change_uses_recreate(self, bus):
        """BF-232: set_subject_prefix uses recreate_stream (single delete, no double)."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()
        bus._active_subs = []

        # Seed stream configs as Phase 2 would
        bus._stream_configs = [
            {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
            {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
        ]

        await bus.set_subject_prefix("probos.did_probos_abc123")

        # Each stream deleted exactly once (by recreate_stream, no double-delete)
        deleted_names = [call.args[0] for call in bus._js.delete_stream.call_args_list]
        assert deleted_names.count("SYSTEM_EVENTS") == 1
        assert deleted_names.count("WARDROOM") == 1

        # Recreated with new prefix
        last_configs = [call.args[0] for call in bus._js.add_stream.call_args_list]
        all_subjects = []
        for cfg in last_configs:
            all_subjects.extend(cfg.subjects)
        assert any("probos.did_probos_abc123.system.events.>" in s for s in all_subjects)
        assert any("probos.did_probos_abc123.wardroom.events.>" in s for s in all_subjects)

    @pytest.mark.asyncio
    async def test_recreate_stream_tracks_config(self, bus):
        """BF-232: Stream configs tracked for set_subject_prefix re-creation."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.recreate_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        assert len(bus._stream_configs) == 1
        assert bus._stream_configs[0]["name"] == "SYSTEM_EVENTS"
        assert bus._stream_configs[0]["subjects"] == ["system.events.>"]

    @pytest.mark.asyncio
    async def test_recreate_stream_create_failure_raises(self, bus):
        """BF-232: If create fails after delete, error propagates."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock(side_effect=Exception("server error"))

        with pytest.raises(Exception, match="server error"):
            await bus.recreate_stream("SYSTEM_EVENTS", ["system.events.>"])

    @pytest.mark.asyncio
    async def test_no_js_skips_everything(self, bus):
        """recreate_stream is no-op without JetStream."""
        bus._js = None
        # Should not raise
        await bus.recreate_stream("SYSTEM_EVENTS", ["system.events.>"])

    @pytest.mark.asyncio
    async def test_ensure_stream_unchanged(self, bus):
        """BF-232: ensure_stream still uses add-or-update (non-destructive)."""
        bus._js.add_stream = AsyncMock()
        bus._js.delete_stream = AsyncMock()

        await bus.ensure_stream(
            "SYSTEM_EVENTS", ["system.events.>"],
            max_msgs=50000, max_age=3600,
        )

        # ensure_stream does NOT call delete_stream
        bus._js.delete_stream.assert_not_called()
        bus._js.add_stream.assert_called_once()
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf232_ensure_stream_stale_subjects.py -v

# BF-231 tests still pass (set_subject_prefix call counts unchanged — single delete per stream)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf231_stale_stream_cleanup.py -v

# All NATS tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "nats" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

**BF-231 test compatibility:** `set_subject_prefix` now calls `recreate_stream()` instead of explicit `_delete_stream()` + `ensure_stream()`. The `_delete_stream` call moves inside `recreate_stream`, so `delete_stream` is still called exactly once per stream. BF-231's `test_prefix_change_deletes_streams` checks `deleted_names` (which streams, not count), so it remains compatible. `test_delete_failure_does_not_block_recreate` checks `add_stream.call_count >= 2`, also compatible. If any BF-231 tests break due to call-count differences, update them to match the new single-delete-per-stream behavior.

---

## Tracking

### PROGRESS.md
Add line:
```
BF-232 CLOSED. ensure_stream() inherits stale subject filters from previous boot — update_stream() silently fails to change subjects (BF-231 finding), causing persistent "no response from stream" warnings on every JetStream publish. Fix: new recreate_stream() method uses delete-then-create; ensure_stream() unchanged (non-destructive). Phase 2 startup and set_subject_prefix() now use recreate_stream(). _delete_stream() failure logging promoted from DEBUG to WARNING for real failures (not-found stays DEBUG). Completes BF-229/230/231 NATS resilience trilogy. 8 new tests.
```

### DECISIONS.md
Add entry:
```markdown
### BF-232 — ensure_stream uses recreate_stream for stale subject cleanup

**Date:** 2026-04-24
**Status:** Complete

**BF-232: Split ensure_stream / recreate_stream.** Completes the BF-229/230/231 NATS resilience trilogy. The add-or-update pattern in `ensure_stream()` silently failed to change subject filters when prefixes changed across boots — `update_stream()` on some NATS server versions is a no-op for subject changes (BF-231 finding). New `recreate_stream()` method uses delete-then-create for explicit recreation. `ensure_stream()` retains non-destructive add-or-update semantics for future idempotent callers. Phase 2 startup and `set_subject_prefix()` use `recreate_stream()`. `_delete_stream()` warning logging now distinguishes benign "not found" (DEBUG) from real failures (WARNING). Stream retention sacrifice is acceptable — all current streams are transient event buses (max_age 5–60 min).
```

### docs/development/roadmap.md
Add to Bug Tracker section:
```
- **BF-232** *(closed)*: `ensure_stream()` stale subject filters — new `recreate_stream()` method uses delete-then-create; `ensure_stream()` unchanged. Completes NATS resilience trilogy (BF-229/230/231/232).
```
