# BF-159/160: Qualification Probe Fix Wave

**Status:** Ready for builder
**Issues:** #190 (BF-159), #191 (BF-160)
**Relates to:** AD-592, BF-148, BF-150, AD-582d, BF-143, BF-155

## Context

Qualification test run (2026-04-12) showed 5 failures out of 221 tests:

| Agent | Probe | Score | Threshold |
|-------|-------|-------|-----------|
| security_officer | knowledge_update_probe | 0.500 | 0.6 |
| surgeon | knowledge_update_probe | 0.000 | 0.6 |
| pharmacist | knowledge_update_probe | 0.500 | 0.6 |
| surgeon | seeded_recall_probe | 0.439 | 0.6 |
| CREW | cross_agent_synthesis_probe | 0.000 | 0.5 |

Two distinct bugs. This prompt fixes both.

---

## BF-159: AUTHORITATIVE source framing suppresses temporal preference

### Root Cause

`_confabulation_guard()` in `cognitive_agent.py` (line 2028) returns only the `base` anti-fabrication guard for `SourceAuthority.AUTHORITATIVE` — no `temporal_preference` instruction. Agents with dense, well-anchored episodic histories (3,500+ real episodes) trigger AUTHORITATIVE framing during probes because their real episodes' high anchor confidence pushes `quality_score > 0.55` (in `source_governance.py:256-258`). Without "prefer the most recent observation," the LLM treats contradictory old/new seeded episodes as equally valid.

AD-592's original design rationale was "AUTHORITATIVE memories are well-anchored and unlikely to conflict with orientation." But temporal contradictions (same measurement, different values at different times) are valid even for high-quality memories. The temporal preference instruction is NOT an orientation/quality concern — it's a logical principle (AGM Belief Revision).

### Change 1: Add temporal preference to AUTHORITATIVE tier

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** `_confabulation_guard()` static method, line 2053

**Before (line 2053-2055):**
```python
        if authority == SourceAuthority.AUTHORITATIVE:
            # High-quality memories — still guard against number fabrication
            return base
```

**After:**
```python
        if authority == SourceAuthority.AUTHORITATIVE:
            # High-quality memories — still guard against number fabrication.
            # BF-159: Include temporal preference even for AUTHORITATIVE.
            # Temporal contradictions (same metric, different timestamps) are
            # valid regardless of anchor quality. AGM Belief Revision applies
            # universally — newer observations supersede older ones.
            return base + temporal_preference
```

**Design note:** AUTHORITATIVE still does NOT get `orientation_priority`. That instruction ("orientation data is authoritative") is about system data vs memories — a quality concern. Temporal preference is about time ordering — a logical principle. These are orthogonal.

### Change 2: Update BF-148 test to match new behavior

**File:** `tests/test_bf148_knowledge_update.py`
**Location:** `test_authoritative_tier_no_temporal_preference` at line 56

**Before (lines 56-59):**
```python
    def test_authoritative_tier_no_temporal_preference(self):
        """BF-148: AUTHORITATIVE tier stays minimal — no temporal preference."""
        text = CognitiveAgent._confabulation_guard(SourceAuthority.AUTHORITATIVE)
        assert "prefer" not in text.lower() and "most recent" not in text.lower()
```

**After:**
```python
    def test_authoritative_tier_has_temporal_preference(self):
        """BF-159: AUTHORITATIVE tier includes temporal preference.

        Temporal contradictions are valid even for high-quality memories.
        AGM Belief Revision: newer observations supersede older ones,
        regardless of source authority level.
        """
        text = CognitiveAgent._confabulation_guard(SourceAuthority.AUTHORITATIVE)
        assert "most recent" in text.lower() or "prefer" in text.lower()
```

### Change 3: Verify AUTHORITATIVE still excludes orientation_priority

Add a new test to confirm the design intent is preserved — AUTHORITATIVE gets temporal preference but NOT orientation priority.

**File:** `tests/test_bf148_knowledge_update.py`
**Location:** After the updated test above.

**Add:**
```python
    def test_authoritative_tier_no_orientation_priority(self):
        """BF-159: AUTHORITATIVE tier still omits orientation priority.

        Orientation priority ("orientation data is authoritative") is about
        system data quality — not appropriate for high-quality memories.
        This is distinct from temporal preference (time ordering).
        """
        text = CognitiveAgent._confabulation_guard(SourceAuthority.AUTHORITATIVE)
        assert "orientation" not in text.lower()
```

---

## BF-160: CrossAgentSynthesisProbe false failure at CREW level

### Root Cause

BF-150 redesigned `CrossAgentSynthesisProbe` from cross-shard recall to sovereign-shard synthesis — a per-agent test. But the tier remained at 3. The drift scheduler's `run_collective(3)` runs ALL tier-3 tests with `agent_id='__crew__'`. The probe calls `runtime.registry.get('__crew__')` → None → `_make_error_result` (score=0.0, passed=False).

The collective tests in `collective_tests.py` handle `__crew__` by ignoring the agent_id entirely. This probe needs a real agent.

### Change 4: Add `__crew__` guard to CrossAgentSynthesisProbe

**File:** `src/probos/cognitive/memory_probes.py`
**Location:** `CrossAgentSynthesisProbe._run_inner()`, line 775

**Before (lines 775-784):**
```python
    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")
        if getattr(runtime, "registry", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_registry")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")
```

**After:**
```python
    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        # BF-160: Skip when run in collective mode — this is a per-agent probe.
        # BF-150 redesigned from cross-shard to sovereign-shard synthesis,
        # but tier remained at 3, so run_collective() invokes it with __crew__.
        from probos.cognitive.qualification import CREW_AGENT_ID
        if agent_id == CREW_AGENT_ID:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "per_agent_only")

        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")
        if getattr(runtime, "registry", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_registry")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")
```

**Why skip, not error:** `_make_skip_result` returns `score=1.0, passed=True` — the test gracefully indicates "I can't run in this mode." `_make_error_result` would be `score=0.0, passed=False`, which is the current false failure.

### Change 5: Add test for CREW skip behavior

**File:** `tests/test_bf150_synthesis_probe.py`
**Location:** End of file.

**Add test class:**
```python
class TestCrewSkipGuard:
    """BF-160: CrossAgentSynthesisProbe skips when run as __crew__."""

    def test_crew_agent_id_returns_skip(self):
        """Probe returns skip result when agent_id is __crew__."""
        from probos.cognitive.memory_probes import CrossAgentSynthesisProbe
        from probos.cognitive.qualification import CREW_AGENT_ID

        probe = CrossAgentSynthesisProbe()

        class MockRuntime:
            episodic_memory = True
            registry = type("R", (), {"get": lambda self, x: None})()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            probe.run(CREW_AGENT_ID, MockRuntime())
        )
        assert result.passed is True
        assert result.score == 1.0
        assert result.details.get("skipped") is True
        assert result.details.get("reason") == "per_agent_only"
```

---

## Summary of Changes

| # | File | Change | Lines |
|---|------|--------|-------|
| 1 | `src/probos/cognitive/cognitive_agent.py` | Add `temporal_preference` to AUTHORITATIVE return | 2053-2055 |
| 2 | `tests/test_bf148_knowledge_update.py` | Invert AUTHORITATIVE temporal test; verify it now HAS temporal preference | 56-59 |
| 3 | `tests/test_bf148_knowledge_update.py` | Add test: AUTHORITATIVE still excludes orientation_priority | After change 2 |
| 4 | `src/probos/cognitive/memory_probes.py` | Add `__crew__` skip guard to CrossAgentSynthesisProbe | 775-784 |
| 5 | `tests/test_bf150_synthesis_probe.py` | Add test: CREW agent_id returns skip result | End of file |

**Source files modified:** 2
**Test files modified:** 2
**New tests:** 3
**Existing tests modified:** 1

## Engineering Principles Compliance

- **Fail Fast:** The `__crew__` guard fails early with a clear skip reason, not a cryptic error.
- **SOLID (O):** Extending behavior by adding temporal_preference to AUTHORITATIVE, not patching private members.
- **DRY:** Reuses existing `temporal_preference` string and `_make_skip_result` helper.
- **Defense in Depth:** BF-160 guard validates at the probe boundary, not relying on the harness to filter.

## Verification

After building, run:
```bash
uv run python -m pytest tests/test_bf148_knowledge_update.py tests/test_bf150_synthesis_probe.py -v
```

Then run a qualification test to verify the 5 failures are resolved:
```
/qualify
```

Expected: security_officer, surgeon, pharmacist `knowledge_update_probe` should pass. Surgeon `seeded_recall_probe` should improve (may still be affected by episode competition — but temporal preference helps). CREW `cross_agent_synthesis_probe` should show score=1.000, Pass=Y (skip).
