# Wave 131 — Review Pass 1 Sweep Summary

**Date:** 2026-05-08
**Reviewer:** Architect
**Tolerance regime:** Convention #15 (relaxed) — 1 ⚠️ allowed on the highest-risk prompt.

## Verdicts

| # | Prompt | Verdict | Required | Recommended | Nits |
|---|--------|---------|----------|-------------|------|
| 1 | `ad-454-emergence-taxonomy-v1.md` | ✅ Approved | 0 | 2 | 3 |
| 2 | `ad-454-evidence-collector-v1.md` | ⚠️ Conditional | **1** | 3 | 3 |

Within tolerance. The single ⚠️ lands on prompt 2, which is the wave's highest-risk artifact (code AD with async + file I/O + LLM dependency + listener wiring) — exactly where convention #15 budgets one Required finding.

## Highest-risk prompt and recommended revision

**`prompts/ad-454-evidence-collector-v1.md`** — one Required defect:

> **Tier-3 propagation inside an `add_event_listener` handler is silently swallowed.**

The runtime dispatches async handlers via `asyncio.create_task(fn(event))` (`runtime.py:917`) without storing the task reference, so any `raise` out of `on_ward_room_post` (or anything it calls, including `_persist`) becomes a silent fire-and-forget task exception. D1's current "tier-3 propagate ONLY for filesystem-broken bugs" wording will produce silently-failing observations under any real bug.

**Revision instruction for the prompt author:**

Replace the exception-tier paragraph in D1 with:

> **All exception paths inside `on_ward_room_post`, `classify_post`, `_parse_llm_response`, and `_persist` are tier-2 (log-and-degrade).** Use `logger.exception(...)` with full context (post_id, trial_id, error class) for unexpected errors; use `logger.warning(...)` with context for expected failures (LLM timeout, malformed JSON, OSError). Never `raise` out of these methods — `add_event_listener` dispatches via `asyncio.create_task` without storing the task ref, so any propagated exception is silently lost. The listener boundary owns the swallow.

The 3 Recommended items can be folded into the same revision or deferred to a v2 collector AD — they are not blockers.

## Wave is on track for pass-2 after one revision cycle.

The two prompts are tightly coupled (taxonomy → collector) but cross-prompt API contracts are clean:

- Collector imports exactly `BehaviorCode`, `TAXONOMY`, `as_classifier_prompt` — taxonomy prompt declares all three as public API.
- Module path `probos.cognitive.emergence_taxonomy` matches in both prompts.
- Frozen-dataclass `TaxonomyEntry` shape and the collector's classifier-prompt consumer are compatible.
- Test taxes are reasonable: prompt 1 = 8 (+1 optional), prompt 2 = 7 (+2 recommended). Combined ~17 new tests.

No structural rework required. Apply the Required fix to prompt 2, address the 5 Recommended items if convenient, and the wave is dispatch-ready on pass-2.

## Cross-prompt concerns

*None blocking.* Two minor items worth tracking but not gating:

1. **Era-file routing for DECISIONS.md is soft in both prompts** ("likely `decisions-era-5-unification.md`; follow current convention"). Builder must grep at commit time. This is consistent with the AD-numbering hard rule and is the correct policy — but a one-line confirmation in `prompts/wave-orchestrator-state.json` would tighten it. Out of scope for this review.

2. **`runtime.evidence_collector` attribute is set by assignment in finalize without a class-level annotation on `ProbOSRuntime`.** Consistent with several existing peer subsystems but worth a future cleanup AD ("expose runtime peer-subsystem slots as class-level `Any | None = None` annotations"). Not a blocker.

## Verify-first audit (cross-cut)

Both prompts pass the verify-first standing order. Symbols, signatures, line numbers, file paths, and dependency presence (`pyyaml>=6.0`) all match HEAD. No phantom APIs.

| Asserted symbol | Live location | Status |
|---|---|---|
| `EventType.WARD_ROOM_POST_CREATED` | `events.py:68` | ✅ |
| `runtime.ward_room.get_post` (async) | `ward_room/messages.py:441` | ✅ |
| `runtime.ward_room.get_thread(*, post_limit=)` (async) | `ward_room/threads.py:688` | ✅ |
| `runtime.add_event_listener` | `runtime.py:791` | ✅ |
| `runtime.emit_event` | `runtime.py:924` | ✅ |
| `LLMRequest.tier` (str field) | `types.py:232` | ✅ |
| `pyyaml>=6.0` | `pyproject.toml:26` | ✅ |
| `tier="utility"` precedent | `agents/introspect.py:27`, `agents/system_qa.py:77` | ✅ |
| `tier="infrastructure"` (claimed phantom) | absent across `src/probos/agents/` + `src/probos/cognitive/` | ✅ correctly flagged |
| AD-454 collisions | none in `PROGRESS.md`, `DECISIONS.md`, era files, `roadmap.md` | ✅ reuse safe |
| Highest live AD | AD-717 | ✅ matches prompt's claim |

## Decision

Wave 131 advances to pass-2 after one revision cycle on prompt 2.
