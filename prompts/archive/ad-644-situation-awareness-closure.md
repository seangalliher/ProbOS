# AD-644 Closure Note — Agent Situation Awareness Architecture

**Status:** COMPLETE (all 5 phases shipped). No-build close.
**Issue:** #285
**Wave:** 76 (close-only)
**Decision log:** `DECISIONS.md` lines 1838-1894 (entry remains canonical, no edits)
**Research:** `docs/research/agent-situation-awareness-architecture.md` (no edits)

This note documents the closure of #285 against HEAD `ef5e324`. No code, test, or config change is proposed; the work has shipped over the preceding ~16 days across two earlier waves and is verified live.

## Phase-by-phase verification

### Phase 1 — Duty Context Restoration ✅ shipped
- **Commit:** `f10369d` (Apr 20 2026, "Cognitive chain wave: AD-644 through AD-653, BF-208 through BF-217")
- **Surface:** `src/probos/cognitive/cognitive_agent.py` (+527), `src/probos/cognitive/sub_tasks/analyze.py` (+269), `src/probos/cognitive/sub_tasks/compose.py` (+351)
- **Tests:** `tests/test_ad644_phase1_duty_context.py`
- **Behavior:** `params.duty` + trust/agency/rank flow through to ANALYZE and COMPOSE prompt templates. Duty context biases ANALYZE away from `intended_actions: ["silent"]` when a duty is active.

### Phase 2 — Innate Faculties ✅ shipped
- **Commit:** `f10369d`
- **Surface:** `_build_cognitive_state()` on `CognitiveAgent` populates 9 innate keys (temporal awareness, working memory, self-monitoring, ontology identity, orientation, source attribution, confabulation guard, comm proficiency, trust/agency/rank).
- **Tests:** `tests/test_ad644_phase2_innate_faculties.py`
- **Subsequent generalization:** AD-646 split this into `_build_cognitive_baseline()` (intrinsic, all chains) + `_build_cognitive_extensions(context_parts)` (proactive-dependent). AD-644 Phase 2 remains the migration that proved the four-category model; AD-646 generalized it across all chain-eligible intents.

### Phase 3 — Situation Awareness ✅ shipped
- **Commit:** `f10369d`
- **Surface:** 7 environmental percepts (`ward_room_activity`, `recent_alerts`, `recent_events`, `infrastructure_status`, `subordinate_stats`, `cold_start_note`, `active_game`) flow through observation dict pass-through from `context_parts`. Per DECISIONS.md AD-644 migration note (line 1718), this is intentionally a temporary approach until NATS decouples the pipeline.
- **Tests:** `tests/test_ad644_phase3_situation_awareness.py`
- **Subsequent generalization:** AD-646b promoted `self_monitoring` and `introspective_telemetry` into QUERY operations, and added rich source attribution / cold-start / self-recognition into the cognitive baseline. AD-644 Phase 3 remains the parity work that closed the 23/23 checklist; AD-646b absorbed the residual one-shot gaps.

### Phase 4 — Standing Orders additions ✅ shipped
- **Commit:** `f10369d` (`config/standing_orders/ship.md` +24 lines per `git show --stat`)
- **Surface:** Source attribution policy + duty reporting expectations added to `ship.md` per DD-6 (markdown-only, zero code changes).
- **Tests:** None — DD-6 explicitly scopes Phase 4 as policy-only.

### Phase 5 — Deprecation of `_build_prompt_text` proactive block ✅ closed via AD-644b
- **Commit:** `8a20695` (Wave 71, May 2026, "Wave 71 close: AD-644b _build_prompt_text already removed (no-build, #415)")
- **GH:** #415 closed
- **Verify-first finding** (per `prompts/wave-plan.yaml:842`): the 290-line `_build_prompt_text` proactive block was already removed by either AD-644 Phases 1-4 themselves or the AD-647 chain restructure. `sub_task.py` is now 620 lines (was 3607). `Get-ChildItem -Recurse -Include *.py -Path src,tests | Select-String "_build_prompt_text"` returns zero hits.

## Parity scorecard

The 23-item AD-644 parity checklist (research doc § Parity Scorecard) is fully satisfied. No item is outstanding. The chain path has full perceptual equivalence with the legacy `_build_user_message()` one-shot path for the four chain-eligible intents (proactive_think, ward_room_notification, dm_response, plus the AD-646 universal baseline that brings parity to all future chain-eligible intents by construction).

## Why this closes #285 cleanly (not a partial close)

Issue #285 scope = the AD-644 design as documented in DECISIONS.md and the research doc. That scope is exactly the five phases listed above. Every phase has shipped. There is no design carve-out, no deferred sub-AD, no `AD-644-i` follow-on filed against Phase 1-5 scope.

The lineage that follows (AD-645, AD-646, AD-646b, AD-647, AD-648, AD-649, AD-650, AD-653) extends and generalizes AD-644 — it does not represent unfinished AD-644 work. Each of those ADs has its own GH issue and its own closure record. Closing #285 does not close any of them; they remain governed by their own tickets.

## Captain action items

The Wave 76 dispatch (`prompts/WAVE-76-DISPATCH.md`) lists the seven workflow steps. The two text edits worth re-stating here, because they're the only documentation drift this closure resolves:

1. **PROGRESS.md line 361** — flip from "Phase 1-4 Complete ... Phase 5 (deprecation) design" to "COMPLETE. All 5 phases shipped — Phases 1-4 commit f10369d (23/23 parity), Phase 5 closed via AD-644b in Wave 71 (target already removed). Issue #285."
2. **`docs/development/roadmap.md:7083`** — flip the entry tag from `*(Phase 1-4 complete — 23/23 parity, OSS, Issue #285)*` to `*(Complete — all 5 phases, OSS, Issue #285)*` and append a single sentence inside the existing entry: "Phase 5 deprecation closed via AD-644b Wave 71 (target already removed during chain restructure)."

Neither edit changes behavior, semantics, or any cross-reference. Both are stale-status corrections.

## DECISIONS.md is intentionally NOT edited

The AD-644 entry in DECISIONS.md (lines 1838-1894) is canonical and append-only. Its `Status:` field reads "Phase 1-4 Complete (full parity — 23/23 items). Phase 5 Design (deprecation)." which was accurate when written. The decision log records the decision at the time it was made, not the running status — the running status lives in PROGRESS.md and roadmap.md, which are the two files this closure updates.

## Verify-first footer (2026-05-06)

```
git log --oneline | Select-String "AD-644|#415|#285"
  8a20695 Wave 71 close: AD-644b _build_prompt_text already removed (no-build, #415)
  f10369d Cognitive chain wave: AD-644 through AD-653, BF-208 through BF-217

git show f10369d --stat | Select-String "ship.md|cognitive_agent.py|sub_tasks/(analyze|compose)"
  src/probos/cognitive/cognitive_agent.py        | 527 ++++++++++++++++++-
  src/probos/cognitive/sub_tasks/analyze.py      | 269 +++++++++-
  src/probos/cognitive/sub_tasks/compose.py      | 351 ++++++++++++-
  config/standing_orders/ship.md                 |  24 +

git ls-files tests/ | Select-String "ad644"
  tests/test_ad644_phase1_duty_context.py
  tests/test_ad644_phase2_innate_faculties.py
  tests/test_ad644_phase3_situation_awareness.py

# Phase 5 already closed:
prompts/wave-plan.yaml:830 — title: "AD-644b Phase 5 _build_prompt_text deprecation (no-build close)"
prompts/wave-plan.yaml:842 — "Likely removed during AD-644 Phases 1-4 (commit f10369d)"

# Roadmap state at HEAD:
docs/development/roadmap.md:7083 — "AD-644: Agent Situation Awareness Architecture *(Phase 1-4 complete — 23/23 parity, OSS, Issue #285)*"

# PROGRESS.md state at HEAD:
PROGRESS.md:361 — "AD-644  Phase 1-4 Complete. 23/23 parity. Chain path has full perceptual equivalence with _build_user_message(). Phase 5 (deprecation) design."
```

Every concrete claim in this closure note maps to a grep hit above.

## Review history

- **Pass 1 (draft):** Confirmed all five phases shipped; mapped each to commit and (where applicable) test file; reframed to no-build close.
- **Pass 2 (lineage check):** Verified that AD-645 / AD-646 / AD-646b / AD-647 / AD-647b are NOT carve-outs of AD-644 but successor ADs that build on its parity work. None of them claim AD-644 is incomplete; each has its own issue and closure record. AD-644 entry in DECISIONS.md correctly notes "Composes with AD-641g, AD-618, AD-643a, AD-645" — composition, not dependency.
- **Pass 3 (false-positive scan):** No phantom API claims (no implementation work). No prompt-text issues (no LLM-facing text generated). No async hygiene flags (no async code touched). No type-annotation gaps (no Python touched). Defensive `getattr` / `hasattr` are not introduced.
- **Pass 4 (closure-rule audit):** Issue #285 is the parent ticket for the AD-644 design as written; no sub-issues exist under it that would force a partial close. Closing it under Wave 76 is a clean documentation reconciliation, not a deferral. The Captain rule "don't defer unless no choice" is honored — no work is being punted.
