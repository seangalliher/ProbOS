# BF-231: JetStream Streams Retain Stale DID Subject Filters After Reset

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** BF-229 (DID subject sanitization — complete), BF-230 (JetStream publish resilience — complete)
**Files:** `src/probos/mesh/nats_bus.py`, `tests/test_bf231_stale_stream_cleanup.py` (NEW)

## Problem

`probos reset` generates a new ship DID but doesn't flush JetStream streams. The lifecycle:

1. **Phase 2** (`startup/nats.py:54-73`): Three streams created with un-prefixed subjects (`system.events.>`, `wardroom.events.>`, `intent.dispatch.>`). `ensure_stream()` stores them in `_stream_configs` and creates them with the current prefix (initially `probos.local`).

2. **Phase 7** (`runtime.py:1544`): Ship DID assigned → `set_subject_prefix(f"probos.{cert.ship_did}")` → `set_subject_prefix()` iterates `_stream_configs` and calls `ensure_stream()` to update subject filters to the new DID-prefixed subjects.

3. **`probos reset -y`**: Deletes data files (SQLite DBs, checkpoints) but does NOT touch NATS JetStream streams. Streams persist on the NATS server with the old DID's subject filters.

4. **Next startup**: New ship DID generated → Phase 2 calls `ensure_stream()` → NATS server returns error 10058 ("stream name already in use") → `ensure_stream()` falls back to `update_stream()` → **subject filter update may silently fail or be rejected** depending on NATS server version.

5. **Result**: Streams have subject filters for the OLD DID (`probos.did_probos_6698b0c8...>`), new instance publishes to NEW DID (`probos.did_probos_d9832d8c...>`). Every `js_publish()` gets "no response from stream". BF-230's core NATS fallback prevents total data loss but event persistence is broken.

**Root cause:** `ensure_stream()` tries `add_stream()` then falls back to `update_stream()`, but updating a stream's subject filter to a completely different prefix can fail silently on some NATS server versions. The fix is to delete-and-recreate instead of update when the stream's current subjects don't match the desired subjects.

## Design

**Fix `set_subject_prefix()` to delete-and-recreate streams** instead of calling `ensure_stream()` (which tries update).

The logic:
1. For each tracked stream config, check if the existing stream's subjects match the new prefix
2. If not, delete the stream and recreate it with the correct subjects
3. This is safe because JetStream streams in ProbOS are transient event buses (max_age 5-60 min) — losing persisted messages on prefix change is acceptable

This is better than fixing `probos reset` because:
- `set_subject_prefix()` is the right place — it already knows the prefix changed
- It handles the case where NATS server wasn't running during reset
- It handles manual prefix changes (not just reset)
- The streams are recreated correctly regardless of how the stale state got there

## What This Does NOT Change

- `probos reset` (`__main__.py`) — no change (doesn't need to know about NATS)
- `ensure_stream()` — unchanged (still used for initial creation in Phase 2)
- `_stream_configs` tracking — unchanged
- `js_publish()`, `js_subscribe()` — unchanged
- Subscription re-wiring in `set_subject_prefix()` — unchanged (lines 177+)
- BF-223 per-consumer cleanup (lines 195-211) — unchanged, kept as defense-in-depth

**BF-223 interaction:** Stream deletion cascades to consumer deletion on the NATS server, so BF-223's explicit `delete_consumer()` calls (lines 199-211) become no-ops after BF-231 deletes the stream. BF-223 is preserved as defense-in-depth — if a future stream is added without being tracked in `_stream_configs`, BF-223 still cleans up its consumers. A comment is added in the Section 2 replacement block to document this relationship.

**Startup cost:** Adds 1-2 NATS round-trips per stream on every Phase 7 prefix transition (~150ms for 3 streams). Acceptable trade-off for correctness.

**Publish window:** During stream recreate, the publish path may briefly fail (no stream to publish to). BF-230's retry+fallback covers this sub-second window.

---

## Section 1: Add `_delete_stream()` helper

**File:** `src/probos/mesh/nats_bus.py`

Add a new method after `delete_consumer()` (line 628):

```python
    async def _delete_stream(self, name: str) -> bool:
        """BF-231: Delete a JetStream stream by name. Returns True if deleted."""
        if not self._js:
            return False
        try:
            await self._js.delete_stream(name)
            logger.info("NATSBus: Deleted stream %s", name)
            return True
        except Exception as e:
            logger.debug("NATSBus: Stream delete failed (%s): %s", name, e)
            return False
```

---

## Section 2: Replace stream update with delete-and-recreate in `set_subject_prefix()`

**File:** `src/probos/mesh/nats_bus.py`

Replace the stream update block in `set_subject_prefix()` (lines 150-175):

Current:
```python
        # Update stream subject filters to match new prefix
        if self.connected and self._stream_configs:
            logger.info("set_subject_prefix: updating %d stream configs", len(self._stream_configs))
            for sc in self._stream_configs:
                try:
                    logger.info(
                        "set_subject_prefix: updating stream %s subjects=%s",
                        sc["name"], sc["subjects"],
                    )
                    await self.ensure_stream(
                        sc["name"], sc["subjects"],
                        max_msgs=sc.get("max_msgs", -1),
                        max_age=sc.get("max_age", 0),
                    )
                except Exception as e:
                    logger.error(
                        "BF-229: Stream update on prefix change failed for %s: %s — "
                        "JetStream publishes to this stream will fail. "
                        "Delete the stream (nats stream rm %s) and restart to recover.",
                        sc["name"], e, sc["name"],
                    )
        else:
            logger.warning(
                "set_subject_prefix: skipping stream update (connected=%s, configs=%d)",
                self.connected, len(self._stream_configs),
            )
```

Replace with:
```python
        # BF-231: Delete and recreate streams with new prefix.
        # update_stream() can silently fail to change subject filters on some
        # NATS server versions (especially when the old prefix is a completely
        # different DID). Delete-and-recreate is reliable and safe — these are
        # transient event buses with short max_age retention.
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
        else:
            logger.warning(
                "set_subject_prefix: skipping stream recreate (connected=%s, configs=%d)",
                self.connected, len(self._stream_configs),
            )
```

---

## Section 3: Tests

**File:** `tests/test_bf231_stale_stream_cleanup.py` (NEW)

```python
"""Tests for BF-231: JetStream streams deleted and recreated on prefix change."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.mesh.nats_bus import NATSBus


@pytest.fixture
def bus():
    """Create a NATSBus instance with mocked NATS connection."""
    b = NATSBus(url="nats://localhost:4222")
    b._connected = True
    b._nc = MagicMock()
    b._nc.is_connected = True
    b._js = AsyncMock()
    b._subject_prefix = "probos.local"
    # Simulate streams created during Phase 2
    b._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
        {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
    ]
    # Prevent subscription re-wiring from interfering
    b._active_subs = []
    return b


class TestBF231StaleStreamCleanup:

    @pytest.mark.asyncio
    async def test_prefix_change_deletes_streams(self, bus):
        """BF-231: set_subject_prefix deletes existing streams before recreating."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # Both streams should be deleted
        deleted_names = [call.args[0] for call in bus._js.delete_stream.call_args_list]
        assert "SYSTEM_EVENTS" in deleted_names
        assert "WARDROOM" in deleted_names

    @pytest.mark.asyncio
    async def test_prefix_change_recreates_streams_with_new_prefix(self, bus):
        """BF-231: Recreated streams use the new prefix and preserve retention limits."""
        bus._js.delete_stream = AsyncMock()
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # Streams should be recreated with new prefix
        add_calls = bus._js.add_stream.call_args_list
        subjects_created = []
        for call in add_calls:
            config = call.args[0] if call.args else call.kwargs.get("config")
            subjects_created.extend(config.subjects)

        assert any("probos.did_probos_new123.system.events.>" in s for s in subjects_created)
        assert any("probos.did_probos_new123.wardroom.events.>" in s for s in subjects_created)

        # Retention limits must be preserved (not reset to defaults)
        first_config = bus._js.add_stream.call_args_list[0].args[0]
        assert first_config.max_msgs == 50000  # SYSTEM_EVENTS
        assert first_config.max_age == 3600

    @pytest.mark.asyncio
    async def test_delete_failure_does_not_block_recreate(self, bus):
        """BF-231: If delete fails (stream doesn't exist), recreate still attempted."""
        bus._js.delete_stream = AsyncMock(side_effect=Exception("stream not found"))
        bus._js.add_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        # add_stream should still be called despite delete failure
        assert bus._js.add_stream.call_count >= 2

    @pytest.mark.asyncio
    async def test_same_prefix_skips_recreate(self, bus):
        """No-op when prefix hasn't changed."""
        bus._js.delete_stream = AsyncMock()

        await bus.set_subject_prefix("probos.local")

        # Same prefix — should return early, no delete calls
        bus._js.delete_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_streams_no_action(self, bus):
        """BF-231: When no streams tracked, prefix change is subscription-only."""
        bus._stream_configs = []
        bus._js.delete_stream = AsyncMock()

        await bus.set_subject_prefix("probos.did_probos_new123")

        bus._js.delete_stream.assert_not_called()
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf231_stale_stream_cleanup.py -v

# NATS-related tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "nats" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

### PROGRESS.md
Add line:
```
BF-231 CLOSED. JetStream stale DID stream fix — set_subject_prefix() now deletes and recreates streams instead of updating subject filters. Prevents "no response from stream" after probos reset generates a new ship DID. 5 new tests.
```

### DECISIONS.md
Add entry:
```
**BF-231: Delete-and-recreate JetStream streams on prefix change.** `set_subject_prefix()` previously called `ensure_stream()` which tried `add_stream()` → fallback `update_stream()`. Subject filter updates could silently fail on some NATS server versions, leaving streams with stale DID prefixes after `probos reset`. Fix: delete the stream first, then recreate with correct subjects. Safe because ProbOS JetStream streams are transient event buses with short retention (5-60 min max_age). BF-223's per-consumer cleanup is preserved as defense-in-depth — stream deletion cascades to consumer deletion, making BF-223's explicit `delete_consumer()` calls largely redundant, but they guard consumers on streams not tracked in `_stream_configs`. Alternative considered: flushing streams in `probos reset` — rejected because `set_subject_prefix()` is the right fix location (handles any prefix change, not just reset, and works even if NATS wasn't running during reset). Completes BF-229/230/231 trio — closes the entire class of "JetStream silently dropped events after DID change" incidents.
```

### docs/development/roadmap.md
Update BF-231 status from `Open` to `Closed`.
