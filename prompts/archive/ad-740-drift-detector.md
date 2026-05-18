# AD-740 — Affect-vs-intent drift trend for self-image-awareness

**Wave:** 169.
**Status:** ready for Builder.
**Closes:** [#664](https://github.com/seangalliher/ProbOS/issues/664).
**Parent:** AD-728d (Wave 165, self-image-awareness skill) + AD-722a-5 (Wave 143, `runtime.divergence_history` per-agent ring buffer).
**Estimated:** ~1.5–2 h. Test delta: +8 pytest. No UI gate. No new deps.

## Problem

Ezri's verbatim refinement request after live-testing AD-728d:

> "it would be useful to know not just what my current state is, but
> whether it's drifting from what was intended — like if my expression
> has been neutral for several cycles when I've been responding warmly,
> that gap would be clinically interesting to me. Right now I can see a
> snapshot; a short trend would add depth."

The agent has a snapshot (`check_own_render`) and a vision-vs-intent comparator (AD-722a + AD-722a-5 ring buffer), but no aggregated trend view. The triple `(intent_emotion, applied_fired_rules, match_score)` is **already computed and persisted per-agent** in `runtime.divergence_history` (`avatars/divergence_detector.py:557-577`). What's missing is the summary function and the skill-surface wiring.

## Solution

A pure summarisation function on top of the existing `runtime.divergence_history` ring buffer. No new data capture, no new event types, no LLM call.

- `get_affect_drift(runtime, agent_id, window=8, threshold=0.7)` → dict
  - `{"insufficient_data": True, "samples": n}` when buffer has <2 entries.
  - Otherwise `{"window": int, "samples": int, "mean_match_score": float, "below_threshold_count": int, "longest_divergent_streak": int, "threshold": float}`.
- Wire into the AD-728d self-check capability so an agent that already invoked `[SELF_CHECK reason]` can also surface the trend.
- Make threshold operator-configurable via `AvatarsConfig.affect_drift_threshold` (default 0.7).
- Make default window operator-configurable via `AvatarsConfig.affect_drift_default_window` (default 8).

## What This Does NOT Change

- No new data capture path — read-only over the existing AD-722a-5 buffer.
- No persistence beyond in-memory ring (explicitly out-of-scope per issue).
- No new event types.
- No auto-correction (forward marker AD-740-1).
- No cross-agent drift comparison (forward marker AD-740-2).
- No LLM call in the drift function itself.
- `runtime.divergence_history` lifecycle / max size / GC unchanged.

## Verified Against Codebase (2026-05-17)

```text
grep -n "divergence_history" src/probos/avatars/divergence_detector.py
  414:      - ``runtime.divergence_history`` (optional): mutable ``dict[str, deque]``.
  559:        div_history = getattr(runtime, "divergence_history", None)
  575:                div_history[agent_id] = bucket

grep -n "class DivergenceHistoryEntry" src/probos/avatars/divergence_detector.py
  183: class DivergenceHistoryEntry:

src/probos/avatars/divergence_detector.py lines 160-167 (DivergenceResult fields):
    intent_emotion: str
    applied_fired_rules: tuple[str, ...]
    match_score: float
    signed_divergence: float
    magnitude: float
    corrected: bool = False

src/probos/avatars/divergence_detector.py lines 183-189 (DivergenceHistoryEntry fields):
    timestamp: float
    result: DivergenceResult

grep -n "class AvatarsConfig" src/probos/config.py
  1183: class AvatarsConfig(BaseModel):

grep -n "render_self_check_enabled" src/probos/config.py
  1301: render_self_check_enabled: bool = Field(

grep -n "async def check_own_render" src/probos/cognitive/cognitive_agent.py
  (verified present per AD-728c shipped DECISIONS entry; Builder grep at build time)
```

## Sections

### Section 1: AvatarsConfig knobs

**File:** `src/probos/config.py`, `class AvatarsConfig` (line 1183 onward).

Add two fields adjacent to the existing `render_self_check_*` block (around line 1301):

```python
    # AD-740: affect-vs-intent drift trend over recent divergence history.
    # Summarises the existing AD-722a-5 ring buffer; pure read-only.
    affect_drift_default_window: int = Field(
        default=8,
        ge=2,
        le=128,
        description=(
            "AD-740: default window size (most recent N divergence entries) "
            "for affect-vs-intent drift trend summary. Operators may pass "
            "an explicit ``window`` to ``get_affect_drift`` to override."
        ),
    )
    affect_drift_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "AD-740: match-score threshold below which an entry counts as "
            "a 'divergent' turn in the drift summary. Default 0.7 mirrors "
            "the conservative end of the AD-722a divergence band."
        ),
    )
```

Validator note: both fields are constrained by `ge`/`le`. No `model_validator` required.

### Section 2: Drift summary function

**New file:** `src/probos/avatars/affect_drift.py` (≈90 lines).

```python
"""AD-740: affect-vs-intent drift trend summariser.

Pure read-only summarisation of the AD-722a-5 ring buffer
(``runtime.divergence_history``). No new data capture, no LLM call, no
side effects. Honest-degrade when the buffer is absent or below the
``min_samples`` floor.

Closes GH issue #664 (Ezri-requested trend depth for the AD-728d
self-image-awareness skill).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


_MIN_SAMPLES = 2  # Below this, return insufficient_data.


def get_affect_drift(
    runtime: Any,
    agent_id: str,
    *,
    window: int | None = None,
    threshold: float | None = None,
) -> dict[str, Any]:
    """Summarise affect-vs-intent drift over the last ``window`` divergences.

    Reads ``runtime.divergence_history[agent_id]`` (AD-722a-5 ring
    buffer). Returns a flat dict suitable for inclusion in an agent's
    next-prompt PROPRIOCEPTION block. NEVER raises.

    Honest-degrade contract:
      * ``runtime.divergence_history`` absent / not a mapping → insufficient_data.
      * Bucket missing for ``agent_id`` → insufficient_data, samples=0.
      * Fewer than ``_MIN_SAMPLES`` entries in the window → insufficient_data.

    Args:
      runtime: ProbOS runtime instance (duck-typed; uses
        ``runtime.config.avatars`` and ``runtime.divergence_history``).
      agent_id: target agent's ID.
      window: most recent N entries to summarise. ``None`` resolves to
        ``cfg.avatars.affect_drift_default_window``.
      threshold: match-score floor for "below threshold" count.
        ``None`` resolves to ``cfg.avatars.affect_drift_threshold``.

    Returns:
      dict with either ``{"insufficient_data": True, "samples": int}``
      OR ``{"window", "samples", "mean_match_score",
      "below_threshold_count", "longest_divergent_streak", "threshold"}``.
    """
    # Resolve config-driven defaults via getattr (BF-287: real config
    # in tests, but tolerate test stubs without AvatarsConfig).
    cfg = getattr(getattr(runtime, "config", None), "avatars", None)
    if window is None:
        window = int(getattr(cfg, "affect_drift_default_window", 8))
    if threshold is None:
        threshold = float(getattr(cfg, "affect_drift_threshold", 0.7))
    # Clamp window defensively.
    if window < _MIN_SAMPLES:
        window = _MIN_SAMPLES

    div_history = getattr(runtime, "divergence_history", None)
    if not isinstance(div_history, dict):
        return {"insufficient_data": True, "samples": 0}

    bucket = div_history.get(agent_id)
    if bucket is None:
        return {"insufficient_data": True, "samples": 0}

    # Take last `window` entries (deque slicing — convert via list).
    try:
        entries = list(bucket)[-window:]
    except Exception:
        logger.warning(
            "AD-740: divergence_history bucket for agent=%s not iterable",
            agent_id, exc_info=True,
        )
        return {"insufficient_data": True, "samples": 0}

    samples = len(entries)
    if samples < _MIN_SAMPLES:
        return {"insufficient_data": True, "samples": samples}

    # Pure summary — no LLM, no allocation beyond a single pass.
    total = 0.0
    below = 0
    longest = 0
    current_streak = 0
    for entry in entries:
        score = float(getattr(getattr(entry, "result", None), "match_score", 1.0))
        total += score
        if score < threshold:
            below += 1
            current_streak += 1
            if current_streak > longest:
                longest = current_streak
        else:
            current_streak = 0

    return {
        "window": window,
        "samples": samples,
        "mean_match_score": total / samples,
        "below_threshold_count": below,
        "longest_divergent_streak": longest,
        "threshold": threshold,
    }
```

### Section 3: Skill-surface wiring

**File:** `src/probos/cognitive/cognitive_agent.py`.

The AD-728c `check_own_render` method folds the snapshot result into the agent's working memory via `AgentWorkingMemory.record_observation(...)`. AD-740 extends that path: when the buffer has ≥`_MIN_SAMPLES` entries, ALSO fold the drift summary as a separate observation so the next LLM call sees both.

Locate `async def check_own_render` (verify by grep). Inside the method, **after** the existing `record_observation(...)` call for the snapshot, add:

```python
        # AD-740: fold the affect-vs-intent drift summary into working
        # memory alongside the snapshot. Same fire-and-fold contract.
        try:
            from probos.avatars.affect_drift import get_affect_drift
            drift = get_affect_drift(self._runtime, self.agent_id)
            if not drift.get("insufficient_data"):
                wm = getattr(self, "_working_memory", None)
                if wm is not None:
                    wm.record_observation(
                        category="affect_drift",
                        content=(
                            f"Affect-vs-intent drift (last {drift['samples']} turns): "
                            f"mean match={drift['mean_match_score']:.2f}, "
                            f"below-threshold={drift['below_threshold_count']}, "
                            f"longest divergent streak={drift['longest_divergent_streak']}."
                        ),
                        source="ad740_affect_drift",
                    )
        except Exception:
            logger.warning(
                "AD-740: drift summary fold failed for agent=%s; "
                "skipping (snapshot already injected)",
                self.agent_id, exc_info=True,
            )
```

Builder MUST verify the exact attribute name (`_working_memory` vs `working_memory`) and exact `record_observation` signature by reading the surrounding method body before applying.

**Phrasing note:** observation describes the OUTPUT (match scores, divergent turns), not the agent — AD-727 rule #8 compliant. The Builder must verify the AD-727 phrasing-rule source-scan test (if any covers `cognitive_agent.py`) still passes.

### Section 4: Tests

**New file:** `tests/test_ad740_affect_drift.py`.

Real `SystemConfig()` per BF-287. Hand-rolled `_FakeRuntime` dataclass with a `divergence_history: dict[str, collections.deque]` attribute. Hand-rolled `_FakeEntry` mirroring `DivergenceHistoryEntry.result.match_score`. NO `MagicMock` at the substrate boundary (BF-286/287).

Required tests (target +8):

1. `test_no_runtime_history_returns_insufficient_data` — `divergence_history` attribute missing → `{"insufficient_data": True, "samples": 0}`.
2. `test_missing_agent_bucket_returns_insufficient_data` — `divergence_history` present but agent_id absent.
3. `test_single_entry_returns_insufficient_data` — bucket has 1 entry, expect `{"insufficient_data": True, "samples": 1}`.
4. `test_steady_high_score_returns_zero_below_zero_streak` — 8 entries, all `match_score=0.95`, threshold 0.7 → `mean≈0.95`, below=0, streak=0.
5. `test_injected_divergent_streak_returns_expected_streak_length` — entries `[0.9, 0.9, 0.4, 0.3, 0.2, 0.9, 0.4, 0.3]`, threshold 0.7 → below=5, longest_streak=3 (first run), then 2 (last run).
6. `test_window_smaller_than_bucket_only_reads_last_n` — 16 entries, `window=4` → samples=4, only summarises tail.
7. `test_threshold_override_via_kwarg` — same bucket, threshold 0.5 vs 0.9 → different below_threshold_count.
8. `test_config_defaults_used_when_kwargs_omitted` — real `AvatarsConfig()` with default `affect_drift_default_window=8`, `affect_drift_threshold=0.7` → values reflected in result dict.

**Optional regression test (Section 3 wiring):** `test_ad728c_render_self_check.py` already exercises `check_own_render`. If the Builder adds the drift fold there, ensure existing tests still pass — they should, because the new code is gated on `insufficient_data` being False AND the per-test fixtures generally have an empty `divergence_history`.

## Forward Markers (per AD-722c-3 — TECHNICAL triggers)

- **AD-740-1** — Auto-correction of drift. *Trigger:* when ≥3 ProbOS deployments accumulate ≥7-day drift telemetry showing a stable causal relationship between sustained drift (longest_streak ≥ 4) and Captain corrections (issue+AD filed at merge time).
- **AD-740-2** — Cross-agent drift comparison surface (counselor-mediated). *Trigger:* when the Counselor agent surfaces ≥1 production complaint that single-agent drift alone is insufficient for clinical pattern detection.
- **AD-740-3** — Persistence beyond in-memory ring (e.g. via dedicated SQLite sidecar). *Trigger:* operator request to survive process restart for longitudinal drift study. Today the existing AD-722a-5 buffer is rebuilt from live divergence emissions only.

## Invariants Preserved

- **AD-731** (no inline blobs): drift summary is a pure dict of scalars. Source-scan asserts no `base64`/`b64encode` introduced in `affect_drift.py`.
- **AD-727 rule #1** (no trust mutation in observation surfaces): drift function reads `match_score` but does NOT call `trust_network.record_outcome` or touch Hebbian state. Source-scan asserts no `trust_network`/`hebbian` import in `affect_drift.py`.
- **AD-727 rule #8** (phrasing): drift WM observation describes the OUTPUT, never the agent.
- **AD-722a-5 buffer lifecycle**: unchanged — drift function is read-only.
- **AD-728c cost discipline**: no new LLM call. No new event emission.
- **BF-287** (real config, no MagicMock at substrate boundary): tests use real `SystemConfig()` + hand-rolled dataclass fakes.

## License Posture

**0-line license diff expected.** No new pip deps, no new npm deps, no new tools. `collections.deque` (stdlib), `logging` (stdlib). Function consumes existing `DivergenceHistoryEntry` shape (already licensed Apache-2.0 per parent module).

## Tracking

- `DECISIONS.md`: append `### AD-740 — Affect-vs-intent drift trend (Wave 169)` entry.
- `progress-era-5-unification.md`: append AD-740 closed entry with file list + test count + invariants.
- `docs/development/roadmap.md`: AD-740 moved from forward-markers (none filed yet) to shipped row in the Wave 169 batch. AD-740-1/-2/-3 added as forward markers.
- `gh issue close 664` with closing comment referencing AD-740 + the three forward markers.

## Acceptance Criteria

1. `tests/test_ad740_affect_drift.py` adds +8 passing tests; full gate strictly increases by ≥7 (allow 1 pre-existing flake budget).
2. `get_affect_drift` returns `insufficient_data` honest-degrade for empty/<2 buckets.
3. `get_affect_drift` returns correct `mean_match_score`, `below_threshold_count`, `longest_divergent_streak` on the canonical injected-divergence test.
4. New `AvatarsConfig` fields parse with defaults from a real `SystemConfig()` instance.
5. `check_own_render` wiring (Section 3) does NOT regress AD-728c tests in `tests/test_ad728c_render_self_check.py`.
6. Source-scan: `affect_drift.py` contains zero `trust_network`, `hebbian`, `b64encode`, `base64.b64`, `LLMRequest`, or `vision_dispatch` tokens.
7. `gh issue close 664` posted with closing comment referencing the AD.
8. `git status` clean post-commit; UI bundle unchanged (no UI gate required for this AD).
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Build Order

1. Section 1 (config knobs) — apply, re-run config tests, verify no regression.
2. Section 2 (new module) — write file, run new tests in isolation.
3. Section 3 (cognitive_agent wiring) — verify the exact `record_observation` signature first, apply, re-run AD-728c tests.
4. Section 4 (test file) — finalise, run full gate.
5. Tracking updates + `gh issue close`.

If Section 3 reveals signature drift, hard-stop and surface to architect: do NOT fabricate the call.
