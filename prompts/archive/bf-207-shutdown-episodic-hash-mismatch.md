# BF-207: Shutdown Race — Episodic Memory Hash Mismatch (Complete Fix)

**Status:** Ready for builder
**Priority:** High
**Type:** Bugfix
**Issue:** #282
**Files:** `src/probos/startup/shutdown.py`, `src/probos/__main__.py`, `src/probos/cognitive/episodic.py`, `src/probos/startup/cognitive_services.py`, `tests/test_bf207_shutdown_episodic_integrity.py`

## Problem Statement

The 5-second shutdown timeout in `__main__.py` (lines 401 and 527) wraps the entire `runtime.stop()` call. The shutdown sequence in `startup/shutdown.py` executes ~25 service stops, a 1-second grace period, and a 2-second dream consolidation timeout BEFORE reaching `episodic_memory.stop()` at line 321. When any service stop is slow (Ward Room thread creation, NATS disconnect, knowledge store flush), the 5s budget expires before ChromaDB's `client.close()` runs. This leaves ChromaDB in an inconsistent state where metadata no longer matches the content hash computed at store time, causing BF-207 warnings on every subsequent recall.

A partial fix was applied previously:
- Dream consolidation timeout reduced from 5s to 2s (shutdown.py line 282)
- Episodic memory stop moved before knowledge store persist (shutdown.py line 321)
- Auto-heal for hash mismatches added to `_verify_episode_hash` (episodic.py line 499)

But the root cause remains: `episodic_memory.stop()` is still positioned AFTER the 1s grace period + ~25 service stops + 2s dream consolidation, consuming 3s+ of the 5s budget before the critical ChromaDB close even begins.

## Root Cause Analysis

The shutdown sequence in `startup/shutdown.py` currently executes in this order:

1. Session record write (sync, fast) — line 34
2. Ward Room stasis announcement — line 59 (can be slow: DB write + thread creation)
3. **1s grace period** — line 85 (`asyncio.sleep(1)`)
4. Cancel flush task — line 88
5. **~25 service stops** — lines 95–262 (ACM, Identity, SIF, Initiative, cognitive queues, proactive loop, watch manager, persistent tasks, workforce, build dispatcher, Ward Room, cognitive journal, clearance store, tool permissions, counselor profiles, procedure store, drift scheduler, qualification store, retrieval practice, activation tracker, cognitive skills, skill framework, assignment, red team, pool scaler, federation)
6. **Dream consolidation** — line 278 (2s timeout)
7. Working memory freeze — line 294
8. Pool stops — line 312
9. **Episodic memory stop** — line 321 (the critical ChromaDB close)
10. Eviction audit stop — line 324
11. Knowledge store persist — line 330
12. Mesh/NATS/event log stops — lines 354–379
13. LLM client close — line 382

Steps 2–8 routinely consume 3–5 seconds. If step 6 (dream consolidation) hits its 2s timeout, we're already at 4s+ before episodic memory stop even begins. The `__main__.py` timeout fires at 5s, cancelling the task.

**Fix:** Restructure shutdown into two phases — critical persistence first (dream consolidation + episodic memory close), then service cleanup. Increase the `__main__.py` timeout from 5s to 10s as a safety margin.

## What This Does NOT Change

- `_verify_episode_hash()` auto-heal logic — unchanged. The existing auto-heal in `episodic.py` lines 493–528 remains as a defense-in-depth fallback.
- `compute_episode_hash()` — unchanged.
- `_episode_to_metadata()` — unchanged.
- Session record write — stays first (sync, BF-135/BF-137).
- Ward Room stasis announcement — stays early (AD-435/AD-502).
- The existing test class `TestAutoHealCurrentVersion` — unchanged.

---

## Section 1: Restructure Shutdown Sequence

**File:** `src/probos/startup/shutdown.py`

Move dream consolidation and episodic memory close to immediately after the grace period and flush task cancellation (Phase 1: Critical Persistence), before the long list of service stops (Phase 2: Service Cleanup).

### 1a: Delete the old dream consolidation + episodic memory blocks

**Do this FIRST** to avoid a broken-file-with-duplicates window. Remove these two blocks from their current positions:

**Block A** — Dream consolidation (currently at lines 272–291). Delete:

```python
    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    # Must run BEFORE pools stop (dream_cycle may trigger Ward Room notifications)
    # and BEFORE LLM client is closed (dream_cycle makes LLM calls).
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info("Consolidating session memories...")
        try:
            report = await asyncio.wait_for(
                runtime.dream_scheduler.engine.dream_cycle(),
                timeout=2.0,  # BF-207: Reduced from 5s — must leave budget for cleanup within __main__'s 5s limit
            )
            logger.info(
                "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
                report.episodes_replayed,
                report.weights_strengthened,
                report.weights_pruned,
            )
        except asyncio.TimeoutError:
            logger.warning("Shutdown consolidation timed out (2s limit) — partial consolidation completed")
        except (asyncio.CancelledError, Exception) as e:
            logger.warning("Shutdown consolidation failed: %s", e or type(e).__name__)
```

**Block B** — Episodic memory + eviction audit (currently at lines 320–326). Delete:

```python
    # BF-207: Close episodic memory (ChromaDB) early — nothing below writes episodes,
    # and the 5s __main__.py shutdown timeout often expires before reaching the
    # original position. Without client.close(), ChromaDB's internal state may not
    # finalize, causing hash mismatches on restart.
    if runtime.episodic_memory:
        await runtime.episodic_memory.stop()

    # AD-541f: Stop eviction audit log (companion to episodic memory)
    _eviction_audit = getattr(runtime, "_eviction_audit", None)
    if _eviction_audit is not None:
        await _eviction_audit.stop()
        runtime._eviction_audit = None
```

After both deletions, the file is missing these features (intentionally — Section 1b adds them back in the correct position).

### 1b: Insert Phase 1 block at the correct position

After the flush task cancellation block (line 93 area), insert the new Phase 1 block. Find the current code:

```python
    # Cancel periodic flush — BF-099: await cancellation before trust writes
    if hasattr(runtime, '_flush_task'):
        runtime._flush_task.cancel()
        try:
            await runtime._flush_task
        except (asyncio.CancelledError, Exception):
            pass

    # Stop ACM (AD-427)
```

Replace with:

```python
    # Cancel periodic flush — BF-099: await cancellation before trust writes
    if hasattr(runtime, '_flush_task'):
        runtime._flush_task.cancel()
        try:
            await runtime._flush_task
        except (asyncio.CancelledError, Exception):
            pass

    # ── Phase 1: Critical Persistence ──────────────────────────────────
    # Dream consolidation + episodic memory close MUST complete before the
    # __main__.py timeout expires. Moved ahead of service stops (BF-207).
    # Budget: 2s dream timeout + ~500ms episodic close = ≤3s typical,
    # with 7s remaining of the 10s timeout for Phase 2.
    import time as _time
    _phase1_start = _time.monotonic()

    # Tier 3: Shutdown consolidation — flush remaining episodes (AD-288)
    # Must run BEFORE pools stop (dream_cycle may trigger Ward Room notifications)
    # and BEFORE LLM client is closed (dream_cycle makes LLM calls).
    if runtime.dream_scheduler and runtime.episodic_memory:
        logger.info("Consolidating session memories...")
        try:
            report = await asyncio.wait_for(
                runtime.dream_scheduler.engine.dream_cycle(),
                timeout=2.0,
            )
            logger.info(
                "Session consolidation complete: replayed=%d strengthened=%d pruned=%d",
                report.episodes_replayed,
                report.weights_strengthened,
                report.weights_pruned,
            )
        except asyncio.TimeoutError:
            logger.warning("Shutdown consolidation timed out (2s limit) — partial consolidation completed")
        except (asyncio.CancelledError, Exception) as e:
            logger.warning("Shutdown consolidation failed: %s", e or type(e).__name__)

    # BF-207: Close episodic memory (ChromaDB) immediately after dream
    # consolidation — this is the critical operation that caused hash mismatches
    # when it was positioned after ~25 service stops.
    if runtime.episodic_memory:
        await runtime.episodic_memory.stop()

    # AD-541f: Stop eviction audit log (companion to episodic memory)
    _eviction_audit = getattr(runtime, "_eviction_audit", None)
    if _eviction_audit is not None:
        await _eviction_audit.stop()
        runtime._eviction_audit = None

    _phase1_elapsed = _time.monotonic() - _phase1_start
    logger.info("BF-207: Phase 1 (Critical Persistence) completed in %.1fs", _phase1_elapsed)

    # ── Phase 2: Service Cleanup ───────────────────────────────────────

    # Stop ACM (AD-427)
```

### 1c: Verify no remaining references

After the deletions and insertion, verify the dream consolidation timeout comment no longer references "5s limit" (the old `# BF-207: Reduced from 5s` comment was removed with Block A). The new Phase 1 block uses a clean comment without the stale reference. Also verify that `episodic_memory.stop()` and `_eviction_audit.stop()` each appear exactly once in the file.

---

## Section 2: Increase Shutdown Timeout

**File:** `src/probos/__main__.py`

The 5s timeout is too tight. Phase 1 (dream consolidation 2s + episodic memory close) plus Phase 2 (service cleanup) routinely exceeds 5s. Increase to 10s.

### 2a: Update `_boot_and_run` shutdown timeout

Find (line 401):
```python
            await asyncio.wait_for(runtime.stop(reason=getattr(shell, '_quit_reason', '')), timeout=5)
```

Replace with:
```python
            await asyncio.wait_for(runtime.stop(reason=getattr(shell, '_quit_reason', '')), timeout=10)
```

### 2b: Update `_boot_and_run` timeout message

Find (line 404):
```python
            console.print(" [yellow]timed out (5s)[/yellow]")
```

Replace with:
```python
            console.print(" [yellow]timed out (10s)[/yellow]")
```

### 2c: Update `_serve` shutdown timeout

Find (line 527):
```python
            await asyncio.wait_for(runtime.stop(), timeout=5)
```

Replace with:
```python
            await asyncio.wait_for(runtime.stop(), timeout=10)
```

### 2d: Update `_serve` timeout message

Find (line 530):
```python
            console.print(" [yellow]timed out (5s)[/yellow]")
```

Replace with:
```python
            console.print(" [yellow]timed out (10s)[/yellow]")
```

---

## Section 3: Startup Hash Integrity Sweep

**File:** `src/probos/cognitive/episodic.py`

Add a startup function that proactively scans recent episodes for hash mismatches and auto-heals them, so stale hashes from a previous unclean shutdown don't produce BF-207 warnings during normal recall.

### 3a: Add `sweep_hash_integrity` function

Add this function after the existing `migrate_enriched_embedding()` function (around line 436) and before the `compute_episode_hash()` function:

```python
async def sweep_hash_integrity(
    episodic_memory: "EpisodicMemory",
    max_episodes: int = 200,
) -> int:
    """BF-207: Proactive hash integrity sweep on startup.

    Scans the most recent episodes and auto-heals any content hash
    mismatches left by an unclean shutdown. Runs AFTER all other
    migrations (BF-103, AD-570, AD-584, AD-605) which may change
    metadata that affects the hash.

    max_episodes=200 covers approximately 10 minutes of busy session
    activity. Crashed shutdowns typically only leave the last few
    episodes stale, but the generous budget costs little (sub-second
    for 200 episodes).

    Note: ChromaDB's .get() and .update() are synchronous. This function
    is async to fit the startup migration interface but blocks the event
    loop briefly. For 200 episodes this is sub-second. If collection sizes
    grow or the sweep expands, consider wrapping ChromaDB calls in
    asyncio.to_thread().

    Returns the number of episodes healed.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0

    t0 = time.time()
    healed = 0

    try:
        result = episodic_memory._collection.get(
            include=["metadatas", "documents"],
        )
        if not result or not result.get("ids"):
            return 0

        ids_list = result["ids"]
        metadatas = result.get("metadatas", [])
        documents = result.get("documents", [])

        # Sort by timestamp descending, check most recent first
        paired = list(zip(ids_list, metadatas, documents))
        paired.sort(
            key=lambda x: float(x[1].get("timestamp", 0)) if x[1] else 0,
            reverse=True,
        )

        batch_ids: list[str] = []
        batch_metas: list[dict] = []

        for ep_id, meta, doc in paired[:max_episodes]:
            if not meta:
                continue
            stored_hash = meta.get("content_hash", "")
            if not stored_hash:
                continue  # Legacy episode — no hash to verify

            ep = EpisodicMemory._metadata_to_episode(ep_id, doc or "", meta)
            recomputed = compute_episode_hash(ep)

            if recomputed != stored_hash:
                updated_meta = dict(meta)
                updated_meta["content_hash"] = recomputed
                updated_meta["_hash_v"] = _HASH_VERSION
                batch_ids.append(ep_id)
                batch_metas.append(updated_meta)

        # Batch update — ChromaDB's .update() accepts arrays natively
        if batch_ids:
            episodic_memory._collection.update(
                ids=batch_ids,
                metadatas=batch_metas,
            )
            healed = len(batch_ids)

        elapsed = time.time() - t0
        if healed > 0:
            logger.info(
                "BF-207: Healed %d hash mismatches in startup sweep (%.1fs)",
                healed, elapsed,
            )
        else:
            logger.debug("BF-207: Hash integrity sweep clean — 0 mismatches (%.1fs)", elapsed)
    except Exception:
        logger.warning("BF-207: Hash integrity sweep failed (non-fatal)", exc_info=True)

    return healed
```

---

## Section 4: Wire Startup Sweep

**File:** `src/probos/startup/cognitive_services.py`

### 4a: Add hash integrity sweep after all other migrations

After the existing AD-605 enriched embedding migration block (around line 230, after the `except` block), add:

```python
    # BF-207: Proactive hash integrity sweep — heal stale hashes from unclean shutdown.
    # Must run AFTER all other migrations (BF-103, AD-570, AD-584, AD-605) which
    # may legitimately change metadata that affects the content hash.
    # ⚠️ MUST be the last migration. New migrations go ABOVE this block.
    if episodic_memory and config.memory.verify_content_hash:
        try:
            from probos.cognitive.episodic import sweep_hash_integrity
            healed = await sweep_hash_integrity(episodic_memory)
            if healed > 0:
                logger.info("BF-207: Healed %d hash mismatches from previous shutdown", healed)
        except Exception:
            logger.warning("BF-207: Hash integrity sweep failed (non-fatal)", exc_info=True)
```

This runs only when `verify_content_hash` is enabled (default: `True` per `config.py` line 354), gated on the same flag that controls recall-time verification.

---

## Section 5: Tests

**File:** `tests/test_bf207_shutdown_episodic_integrity.py`

Extend the existing test file with new test classes for the restructured shutdown ordering and the startup hash integrity sweep.

### Test 1: `test_episodic_stop_before_service_stops`

In the existing `TestShutdownOrdering` class, add a new test that verifies `episodic_memory.stop()` appears BEFORE the first service stop block (ACM stop). This is the key ordering invariant from Section 1.

```python
    def test_episodic_stop_before_service_stops(self):
        """BF-207 complete fix: episodic_memory.stop() before service cleanup."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")
        acm_stop_pos = source.find("# Stop ACM")

        assert episodic_stop_pos != -1, "episodic_memory.stop() must exist"
        assert acm_stop_pos != -1, "ACM stop block must exist"
        assert episodic_stop_pos < acm_stop_pos, \
            "episodic_memory.stop() must come before service stops (ACM)"
        # Pin uniqueness — catch stale duplicates from incomplete cut-paste
        assert source.count("await runtime.episodic_memory.stop()") == 1, \
            "episodic_memory.stop() must appear exactly once (no duplicates)"
```

### Test 2: `test_dream_consolidation_before_episodic_stop`

In `TestShutdownOrdering`, verify dream consolidation still runs before episodic memory close (dream_cycle writes episodes).

```python
    def test_dream_consolidation_before_episodic_stop(self):
        """Dream consolidation must complete before episodic memory closes."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        dream_pos = source.find("runtime.dream_scheduler.engine.dream_cycle()")
        episodic_stop_pos = source.find("await runtime.episodic_memory.stop()")

        assert dream_pos != -1, "dream_cycle() must exist in shutdown"
        assert episodic_stop_pos != -1, "episodic_memory.stop() must exist"
        assert dream_pos < episodic_stop_pos, \
            "dream_cycle() must run before episodic_memory.stop()"
        # Pin uniqueness — catch stale duplicates from incomplete cut-paste
        assert source.count("runtime.dream_scheduler.engine.dream_cycle()") == 1, \
            "dream_cycle() must appear exactly once (no duplicates)"
        assert source.count("await _eviction_audit.stop()") == 1, \
            "_eviction_audit.stop() must appear exactly once (no duplicates)"
```

### Test 3: `test_phase_comments_present`

Verify the Phase 1/Phase 2 structural comments are present in shutdown.py.

```python
    def test_phase_comments_present(self):
        """Shutdown has Phase 1 (critical persistence) and Phase 2 (service cleanup) markers."""
        from probos.startup import shutdown as shutdown_mod
        source = inspect.getsource(shutdown_mod.shutdown)

        assert "Phase 1: Critical Persistence" in source
        assert "Phase 2: Service Cleanup" in source
```

### Test 4: `test_main_shutdown_timeout_10s`

New test class `TestMainShutdownTimeout`. Verify the `__main__.py` shutdown timeout is 10s.

```python
class TestMainShutdownTimeout:
    """Verify __main__.py shutdown timeout is 10s (BF-207)."""

    def test_boot_and_run_timeout_10s(self):
        """_boot_and_run shutdown uses 10s timeout."""
        import probos.__main__ as main_mod
        source = inspect.getsource(main_mod._boot_and_run)
        assert "runtime.stop(reason=" in source and "timeout=10" in source, \
            "runtime.stop() shutdown timeout should be 10s"
        assert "timeout=5)" not in source, "old 5s timeout should be removed"

    def test_serve_timeout_10s(self):
        """_serve shutdown uses 10s timeout for runtime, 5s for adapter."""
        import probos.__main__ as main_mod
        source = inspect.getsource(main_mod._serve)
        # Pin both: runtime stop at 10s AND adapter stop at 5s (asymmetric by design)
        assert "runtime.stop(), timeout=10" in source, \
            "runtime.stop() should use 10s timeout"
        assert "adapter.stop(), timeout=5" in source, \
            "adapter.stop() should remain at 5s (separate concern)"
```

### Test 5: `test_sweep_hash_integrity_heals_mismatches`

New test class `TestStartupHashSweep`.

```python
class TestStartupHashSweep:
    """BF-207: Startup hash integrity sweep."""

    @pytest.mark.asyncio
    async def test_sweep_heals_mismatches(self):
        """Sweep detects and heals stale content hashes."""
        from probos.cognitive.episodic import sweep_hash_integrity, compute_episode_hash

        ep = Episode(
            id="sweep-test-1",
            timestamp=1000.0,
            user_input="Sweep test input",
            dag_summary={},
            outcomes=[],
            agent_ids=["agent-1"],
            duration_ms=50.0,
        )
        correct_hash = compute_episode_hash(ep)

        # Mock episodic memory with one episode that has a stale hash
        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["sweep-test-1"],
            "metadatas": [{
                "timestamp": 1000.0,
                "user_input": "Sweep test input",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": '["agent-1"]',
                "duration_ms": 50.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": "stale_hash_from_crash",
                "_hash_v": 2,
                "importance": 5,
            }],
            "documents": ["Sweep test input"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 1
        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args
        updated_meta = call_kwargs[1]["metadatas"][0]
        assert updated_meta["content_hash"] == correct_hash
```

### Test 5b: `test_sweep_batches_multiple_mismatches`

```python
    @pytest.mark.asyncio
    async def test_sweep_batches_multiple_mismatches(self):
        """Sweep issues a single batch .update() call for multiple mismatches."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        # Three episodes, all with stale hashes
        ids = ["ep-a", "ep-b", "ep-c"]
        base_meta = {
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 10.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": "",
            "content_hash": "stale",
            "_hash_v": 2,
            "importance": 5,
        }
        metas = []
        docs = []
        for i, ep_id in enumerate(ids):
            m = dict(base_meta)
            m["timestamp"] = float(1000 + i)
            m["user_input"] = f"input-{ep_id}"
            metas.append(m)
            docs.append(f"input-{ep_id}")

        mock_collection.get.return_value = {
            "ids": ids,
            "metadatas": metas,
            "documents": docs,
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 3
        # Must be a single batched call, not 3 individual calls
        mock_collection.update.assert_called_once()
        call_kwargs = mock_collection.update.call_args[1]
        assert call_kwargs["ids"] == ["ep-c", "ep-b", "ep-a"]  # sorted by timestamp desc
```

### Test 6: `test_sweep_skips_matching_hashes`

```python
    @pytest.mark.asyncio
    async def test_sweep_skips_matching_hashes(self):
        """Sweep does not touch episodes with correct hashes."""
        from probos.cognitive.episodic import sweep_hash_integrity, compute_episode_hash

        ep = Episode(
            id="clean-1",
            timestamp=2000.0,
            user_input="Clean episode",
            dag_summary={},
            outcomes=[],
            agent_ids=["agent-2"],
            duration_ms=75.0,
        )
        correct_hash = compute_episode_hash(ep)

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["clean-1"],
            "metadatas": [{
                "timestamp": 2000.0,
                "user_input": "Clean episode",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": '["agent-2"]',
                "duration_ms": 75.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": correct_hash,
                "_hash_v": 2,
                "importance": 5,
            }],
            "documents": ["Clean episode"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 0
        mock_collection.update.assert_not_called()
```

### Test 7: `test_sweep_skips_legacy_episodes`

```python
    @pytest.mark.asyncio
    async def test_sweep_skips_legacy_episodes(self):
        """Sweep ignores episodes with no stored hash (legacy)."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection

        mock_collection.get.return_value = {
            "ids": ["legacy-1"],
            "metadatas": [{
                "timestamp": 500.0,
                "user_input": "Old episode",
                "dag_summary_json": "{}",
                "outcomes_json": "[]",
                "reflection": "",
                "agent_ids_json": "[]",
                "duration_ms": 0.0,
                "shapley_values_json": "{}",
                "trust_deltas_json": "[]",
                "source": "direct",
                "anchors_json": "",
                "content_hash": "",
                "_hash_v": 0,
                "importance": 5,
            }],
            "documents": ["Old episode"],
        }

        healed = await sweep_hash_integrity(mock_em)

        assert healed == 0
        mock_collection.update.assert_not_called()
```

### Test 8: `test_sweep_handles_empty_collection`

```python
    @pytest.mark.asyncio
    async def test_sweep_handles_empty_collection(self):
        """Sweep returns 0 for empty collection."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection
        mock_collection.get.return_value = {"ids": [], "metadatas": [], "documents": []}

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0
```

### Test 9: `test_sweep_handles_no_collection`

```python
    @pytest.mark.asyncio
    async def test_sweep_handles_no_collection(self):
        """Sweep returns 0 when episodic memory has no collection."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_em._collection = None

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0
```

### Test 10: `test_sweep_graceful_on_exception`

```python
    @pytest.mark.asyncio
    async def test_sweep_graceful_on_exception(self):
        """Sweep catches exceptions and returns 0."""
        from probos.cognitive.episodic import sweep_hash_integrity

        mock_em = MagicMock()
        mock_collection = MagicMock()
        mock_em._collection = mock_collection
        mock_collection.get.side_effect = RuntimeError("ChromaDB unavailable")

        healed = await sweep_hash_integrity(mock_em)
        assert healed == 0
```

### Existing test updates

Update the existing `TestShutdownOrdering.test_episodic_stop_before_knowledge_store` — this test still passes because episodic memory stop is still before knowledge store persist (it just moved even earlier). No changes needed to this test.

Update `TestShutdownOrdering.test_dream_cycle_timeout_is_2s` — this test checks for `"timeout=2.0"` in the shutdown source. The new block still uses `timeout=2.0`. No changes needed.

Update `TestShutdownOrdering.test_timeout_warning_says_2s` — the warning message is unchanged. No changes needed.

---

## Verification

Run targeted tests:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf207_shutdown_episodic_integrity.py -v
```

Run full suite to verify no regressions:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Report test count at each step.

---

## Engineering Principles

- **Fail Fast:** Episodic memory close is the critical operation — position it where it cannot be starved by non-critical service cleanup. The 10s timeout is a safety margin, not the fix; the restructured ordering is the fix.
- **Defense in Depth:** Three layers protect against hash corruption, in order of operation: (1) shutdown ordering ensures ChromaDB closes cleanly (preventive), (2) startup sweep proactively heals any residual mismatches (detective + corrective), (3) recall-time auto-heal catches anything missed (last-resort fallback). Each layer is independent.
- **Single Responsibility:** The shutdown phases (Critical Persistence vs Service Cleanup) have clear, distinct purposes. No service stop should block the ChromaDB close.
- **DRY:** The startup sweep reuses `_metadata_to_episode()` and `compute_episode_hash()` — no new hash logic.

---

## Tracker Updates

### PROGRESS.md
Update BF-207 status from `Open` to `**Closed**`.

### docs/development/roadmap.md
Update BF-207 row with fix description:
```
| BF-207 | **Shutdown race — episodic memory hash mismatch (complete fix).** 5s `__main__.py` timeout expired before `episodic_memory.stop()` reached, leaving ChromaDB improperly closed. Metadata no longer matched stored content hash on restart. **Root cause:** `episodic_memory.stop()` was positioned after ~25 service stops + 1s grace + 2s dream consolidation, consuming 3–5s of the 5s budget. **Fix:** (1) Restructured shutdown into Phase 1 (Critical Persistence: dream consolidation + episodic memory close + eviction audit) and Phase 2 (Service Cleanup), ensuring ChromaDB closes within ≤3s typical. (2) Increased `__main__.py` timeout from 5s to 10s as safety margin. (3) Added startup hash integrity sweep (`sweep_hash_integrity`) that proactively heals stale hashes from previous unclean shutdowns, running after all migrations. Three-layer defense: clean shutdown ordering → startup sweep → recall-time auto-heal. 11 new/updated tests. | High | **Closed** |
```

### DECISIONS.md
Add entry:
```
### BF-207 — Shutdown Race: Episodic Memory Hash Mismatch (Complete Fix)
**Context:** The 5s shutdown timeout in `__main__.py` routinely expired before `episodic_memory.stop()` ran because ~25 service stops, a 1s grace period, and a 2s dream consolidation timeout consumed the budget first. ChromaDB left in inconsistent state → metadata no longer matched content hash on restart → BF-207 warnings on every recall.
**Decision:** Restructured shutdown into Phase 1 (Critical Persistence: dream consolidation → episodic memory close → eviction audit stop) and Phase 2 (Service Cleanup: all other service stops). Phase 1 budget: 2s dream timeout + ~500ms episodic close = ≤3s typical. Timeout increased from 5s to 10s as safety margin — the ordering fix is the real solution, not the timeout increase. Added `sweep_hash_integrity()` startup defense: scans 200 most recent episodes, recomputes hashes, auto-heals mismatches from prior unclean shutdowns. ChromaDB .update() uses native batch API. Three-layer defense-in-depth: (1) clean shutdown ordering (preventive), (2) startup sweep (detective + corrective), (3) existing recall-time auto-heal in `_verify_episode_hash` (last-resort fallback). Adapter stop timeout remains 5s (separate concern).
**Consequences:** Episodic memory close now happens within 3s of shutdown start instead of after 4s+ of service cleanup. Hash mismatches from prior crashes are healed before any agent recalls. Phase 1 elapsed time is logged for regression visibility. Future: if collection sizes grow, sweep's sync ChromaDB calls may need `asyncio.to_thread()` wrapping.
```
