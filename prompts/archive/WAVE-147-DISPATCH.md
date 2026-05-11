# Wave 147 — AD-722a-5 divergence history surface

**Issue:** [#614](https://github.com/seangalliher/ProbOS/issues/614)
**Spec:** [prompts/ad-722a-5-divergence-history.md](./ad-722a-5-divergence-history.md)
**Dependencies:** AD-722a (Wave 143, shipped), AD-722a-7 (Wave 146, shipped — c697516)
**Estimated tests:** ≥ 9 backend + ≥ 3 Vitest = ≥ 12 new
**Status:** Ready for Builder

## Overview

Surface accumulated divergence events as a Counselor clinical-quality panel inside `<SelfImageTab>`. Two views:
1. **Recent divergence list** — last N events per agent (timestamp + intent + applied_fired_rules + signed magnitude), most-recent-first, scrollable.
2. **Aggregate metric** — "Of the last N replies, M had non-zero intent-vs-output divergence (M/N = X%)".

In-memory ring buffer per agent (volatile across restarts; acceptable tradeoff). Read-only with respect to trust + Hebbian. Per-agent in v1 (cross-crew is AD-722a-6 / #615).

## Out of scope (forward markers preserved)

- Cross-agent / wardroom rollup ([#615 AD-722a-6](https://github.com/seangalliher/ProbOS/issues/615))
- Trend chart visualization beyond count + percentage
- Calibration loop using the history (v2 calibration AD; will be filed at retrospective)
- On-disk persistence of the ring buffer
- WS push channel for divergence history (HTTP-poll only in v1)

## Pre-flight gate

1. `git status` clean; `git log -1 --oneline` reads `c697516` (Wave 146) or later main HEAD.
2. Full parallel gate green: `pytest tests/ -q -n 4 --dist=loadfile`. Capture baseline.
3. UI tests green: `cd ui && npx vitest run`.

## Per-prompt workflow

Single prompt. Execute `prompts/ad-722a-5-divergence-history.md` end-to-end. Test gate after each section.

## Hard-stop conditions

- AD-727 OUTPUT-subject regex (`_FORBIDDEN_PHRASING_RE` at `tests/test_ad722a_divergence_detector.py:497`) finds a hit in any new history-rendering text.
- Existing AD-722a or AD-722 tests regress.
- Manifest validator rejects the new config fields.

## Commit message format

```
AD-722a-5 (Wave 147): divergence history surface in SelfImageTab

Closes #614. New in-memory ring buffer on runtime.divergence_history (per-agent,
capped at AvatarTelemetryConfig.divergence_history_size, default 100). New
GET /api/agent/{id}/avatar-telemetry/divergence-history endpoint returns history
most-recent-first + aggregate metric. New PanelDivergenceHistory in SelfImageTab
auto-hides when divergence_detection is off.
```

## Tracking

- `PROGRESS.md` — close #614, update test count.
- `docs/development/roadmap.md` — mark AD-722a-5 row shipped.
- `DECISIONS.md` — append AD-722a-5 closure block.
- GH issue #614 — close with commit reference.
- Forward markers preserved: #615 stays open.
