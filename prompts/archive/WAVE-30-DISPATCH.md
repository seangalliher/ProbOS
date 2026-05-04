# Wave 30 Dispatch — AD-645b EVALUATE Brief Alignment (AD-645 Phase 4)

**Issue:** [#287](https://github.com/seang/ProbOS/issues/287)
**Prompt:** [`prompts/ad-645b-evaluate-brief-alignment.md`](prompts/ad-645b-evaluate-brief-alignment.md)
**Estimated tests:** 7 (one over the 6-floor — 3 helper + 1 render + 3 handler integration).
**Test count baseline:** 10920 → expected 10927.
**Hard deps:** AD-645 Phases 1–3 — shipped at HEAD `8c19530`. Verified live:
- Phase 1 brief schema in ANALYZE: `analyze.py:184`/`:383`/`:462`
- Phase 2 brief render in COMPOSE: `compose.py:415-449`
- Phase 3 metacognitive storage: `cognitive_agent.py:2644-2663`

## Wave shape

Single-prompt wave. Closes the AD-645 issue (#287) by shipping Phase 4 —
the last in-scope phase. Phase 5 (NATS schema) is deferred to AD-641g
per the research doc Section 6.

## What v1 ships

1. Two helpers in `evaluate.py`: `_get_composition_brief`,
   `_render_brief_for_eval` (plus 2 module-level constants —
   `_BRIEF_FIELDS_RENDERED`, `_BRIEF_ALIGNMENT_CRITERION_TEXT`,
   `_BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT`).
2. Conditional brief_alignment criterion in
   `_build_ward_room_eval_prompt` and `_build_proactive_eval_prompt` —
   adds criterion text, JSON schema fragment, and rendered brief in
   user prompt **only when** the brief is present.
3. Post-LLM backfill in `EvaluateHandler.__call__` so
   `result["criteria"]["brief_alignment"]` is always present after the
   LLM-eval path. Distinguishes `"brief absent"` (legacy traces) from
   `"verdict omitted criterion"` (LLM regression).
4. 7 focused tests at `tests/test_ad645b_evaluate_brief_alignment.py`.

## Deferred (explicitly out-of-scope)

- Phase 5 — NATS schema (AD-641g).
- `notebook_quality` mode brief alignment — defer to AD-645b-i if data
  justifies; v1 covers ward_room + proactive only (response-composition
  modes, where the brief is most directly assessable).
- Trust-band gate changes — low/mid/high/bypass paths preserved verbatim.
- Pass/fail threshold changes — DD-7 says additive, not gating.
- Composition brief schema changes — read-only consumer.
- Aggregator score recomputation — there is no manual aggregator; the
  LLM returns `score` directly. brief_alignment factors in via the
  rubric instruction only.

## Decision: issues_to_close = [287]

Issue #287 is the umbrella for AD-645 Phases 1–5. Phase 5 is **explicitly
deferred to AD-641g** per the research doc Section 5 ("NATS Alignment
(AD-641g)") and Section 6 ("Phase 5 — Brief Format as NATS Schema
(deferred to AD-641g)"). No Phase 5 work belongs to #287's scope after
this wave. AD-641g has its own (or will have its own) GH issue when the
NATS work is scheduled. Therefore, completing Phase 4 closes #287.

## Phantom-API pre-check

```
pwsh scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-645b-evaluate-brief-alignment.md
1 phantom symbol(s):
  - [<Class>(...)] class:SimpleNamespace
=== Summary ===
Prompts scanned: 1
Total phantom candidates: 1
```

**1 documented false positive — `SimpleNamespace`** is `types.SimpleNamespace`
(stdlib), used in test fixtures to mock `LLMClient.complete` return shape.
Same false-positive pattern documented in Wave 28 (FP #1 = APIRouter,
stdlib FastAPI alias). 0 NEW phantoms.

All consumed APIs verified live in the prompt's `## Verified Against
Codebase` footer at HEAD `8c19530`:
- `_get_compose_output`, `_get_analysis_result`, `_EVALUATION_MODES`,
  `_PASS_BY_DEFAULT` — all real symbols in `evaluate.py`.
- `composition_brief` — real key in ANALYZE result dict per
  `analyze.py:184`/`:383`/`:462`.
- `EvaluateHandler` ctor `(*, llm_client=None, runtime=None)` — real
  signature at `evaluate.py:175`.
- `SubTaskResult`/`SubTaskSpec`/`SubTaskType.{COMPOSE,ANALYZE,EVALUATE}`
  — real dataclass shapes.

## Standing rules (re-stated for Wave 30)

- Test gate: `pytest tests/ -q -n 8 --dist=loadfile`. Triage gate: `-n 0`.
- Hard-stop conditions:
  1. Phantom API in implementation (not just test scaffolding).
  2. Architectural change required (modifying SubTaskHandler protocol,
     EvaluateHandler ctor signature, or SubTaskResult dataclass shape).
  3. Tests that pass under serial but fail under parallel — almost
     always not a real bug; classify as environmental and continue.
- Watch for the **search/replace twin block** subtlety in Section 2c
  and Section 3c: ward_room and proactive both use the same 11-line
  user_prompt construction shape. The Builder must apply each SEARCH
  surgically — the surrounding context (preceding `if trust_band ==
  "mid"` JSON-schema append) differs between the two functions and
  disambiguates the match.
- Backward compat: a brief-absent trace (legacy / SILENT contribution
  / pre-AD-645 chain) MUST produce `criteria.brief_alignment =
  {"pass": True, "score": 0.5, "reason": "brief absent",
  "dimensions": {}}`. Test `test_brief_absent_post_fills_neutral_brief_alignment`
  asserts this directly.
- Privacy: brief contents render only into the agent-private LLM
  prompt context. No event payload changes. No new EventType.

## Common false positives to NOT flag

- `SimpleNamespace` — stdlib `types.SimpleNamespace` (pre-check FP, see above).
- `_get_composition_brief` / `_render_brief_for_eval` /
  `_BRIEF_FIELDS_RENDERED` / `_BRIEF_ALIGNMENT_CRITERION_TEXT` /
  `_BRIEF_ALIGNMENT_JSON_SCHEMA_FRAGMENT` — introduced by Section 1
  of this prompt.
- `tests/test_ad645b_evaluate_brief_alignment.py` — introduced by
  Section 5.
- `verdict omitted criterion` reason string — introduced by Section 4
  backfill block.
- "`composition_brief` may be a string" — defensive `isinstance(brief,
  dict)` check in `_get_composition_brief`. Confirmed real ANALYZE
  output is always a dict or None per `analyze.py:184`-area; the
  defensive check guards against malformed-LLM-output corruption only.

## Wave plan state

`prompts/wave-plan.yaml` Wave 30 entry retargeted in the same draft
commit: `id="30"`, `title="AD-645b: EVALUATE Brief Alignment (AD-645
Phase 4)"`, `prompt_paths` updated to
`prompts/ad-645b-evaluate-brief-alignment.md`, `issues_to_close=[287]`,
`status: pending`. Retarget rationale: original Wave 30 entry was a
flat-AD-645-v1 stub drafted before Phases 1–3 shipped under #287.
Phases 1–3 are now closed; Phase 4 is the natural single-prompt wave
that closes the umbrella issue. Phase 5 explicitly out-of-scope here
(deferred to AD-641g).

## Tracking on close

- `progress-era-4-evolution.md` — append AD-645b CLOSED entry at top.
- `docs/development/roadmap.md` AD-645 entry — flip Phase 4 to
  *(Complete, OSS, Issue #287)*; leave Phase 5 row as
  *(Deferred → AD-641g)*.
- `DECISIONS.md` — no new entry. DD-7 (additive, not gating) is
  documented in the AD-645 research doc.
- `PROGRESS.md` line 320 (`AD-645 Phase 1-3 Complete...`) — extend on
  close to `AD-645 Phase 1-4 Complete. ... Phase 5 deferred to AD-641g.`

## Build report

After build commit, append a build report to
`prompts/build-reports/wave-30.md` with: test count delta (target +7),
hard-stop count (expected 0), phantom-API recurrence count (expected
0), any twin-block SEARCH/REPLACE ambiguity caught at apply time, and
any review-time anti-patterns caught.
