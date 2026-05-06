# WAVE 66 DISPATCH — AD-635f v1 Clinical Telemetry: Proactive Context Injection

**Wave id:** 66
**Single AD:** AD-635f (LAST AD-635 child — closes the AD-635 series end-to-end)
**Closes:** GH issue #395
**Baseline test count:** 11386 (HEAD `1edc781`, post-Wave-65) → expected **11401** (+15 net), window **[+13, +18]**
**HEAD at draft:** `1edc781`, working tree clean
**Builder:** required

## Summary

AD-635 (Wave 60) shipped `ClinicalTelemetryService` as an in-process query facade. AD-635b/c (Waves 62/63) added audit persistence and circuit-breaker history. AD-635d (Wave 64) added the four `/api/clinical/*` REST endpoints. AD-635e (Wave 65) added the Captain's `/clinical` shell command with the `captain_override` kwarg.

What's still missing closes the AD-635 series: **clinical agents themselves — Chapel (`agent_type="diagnostician"`, FULL clearance) and Echo (`agent_type="counselor"`, ORACLE clearance) — have no automatic visibility into the data they exist to monitor.** Their proactive cognitive cycles don't see fitness-for-duty signals unless they explicitly query the service. This contradicts the AD-630 Chiefs pattern (subordinate stats are pre-assembled into proactive context).

The roadmap entry at `docs/development/roadmap.md:5966` defines AD-635f scope literally:

> *"Clinical agents see diagnostic data summary during `_gather_context()` when health assessment is active. Captain bypasses clearance gate (Fleet Admiral authority). Parallels AD-630 subordinate stats injection pattern. Depends on: AD-635 v1 (COMPLETE), AD-635c. Related: AD-630, AD-644 (SA Architecture)."*

Verified at HEAD `1edc781`:

```
src/probos/cognitive/clinical_telemetry.py:57    CLINICAL_ROLES = frozenset({"diagnostician", "counselor"})
src/probos/cognitive/clinical_telemetry.py:65    class ClinicalTelemetryService
src/probos/cognitive/clinical_telemetry.py:93    async def query_dream_history(*, requester_agent_id, limit=20, captain_override=False)
src/probos/cognitive/clinical_telemetry.py:149   async def query_agent_chain_traces(*, requester_agent_id, target_agent_id, limit=20, captain_override=False)
src/probos/cognitive/clinical_telemetry.py:230   async def query_circuit_breaker_history(*, requester_agent_id, target_agent_id=None, limit=50, captain_override=False)
src/probos/cognitive/clinical_telemetry.py:367   def _record_audit(...*, granted, result_count, target_agent_id=None, by_captain=False)
src/probos/proactive.py:1156                     async def _gather_context(self, agent: Any, trust_score: float) -> dict
src/probos/proactive.py:1793                     # AD-630: Subordinate communication stats for Chiefs (REFERENCE PATTERN)
src/probos/proactive.py:1815                     logger.debug("AD-630: Subordinate stats fetch failed for %s", agent.id, exc_info=True)
src/probos/cognitive/cognitive_agent.py:4072     # 5. Subordinate stats (AD-630) — Chiefs only (REFERENCE STATE BUILDER)
src/probos/cognitive/cognitive_agent.py:4084     state["_subordinate_stats"] = "\n".join(sub_lines)
src/probos/cognitive/sub_tasks/compose.py:543    _sub_stats = context.get("_subordinate_stats", "")
src/probos/cognitive/sub_tasks/analyze.py:270    _sub_stats = context.get("_subordinate_stats", "")
runtime.clinical_telemetry slot                  startup/finalize.py:598 (None when cfg.enabled=False)
DECISIONS.md highest                             AD-695 — AD-635f is unique
PROGRESS.md baseline                             11386 collected (post-Wave-65, HEAD 1edc781)
docs/development/roadmap.md:5966                 AD-635f *(Scoped, OSS, Issue #395)*
GH issue #395 body                               "Clinical agents (Chapel, Echo) see diagnostic data summary during _gather_context()"
```

**The gap closed by AD-635f:** clinical agents see a compact summary of dream history, self-targeted chain traces, and fleet-wide circuit-breaker transitions injected into their proactive observation prompt — without explicit queries — using their own (legitimate) FULL/ORACLE clearance. The `captain_override` kwarg from AD-635e is **NOT used here** because Chapel and Echo legitimately pass the real clearance gate.

AD-635f v1 ships:

1. **Producer side** (`proactive.py`): one new branch in `_gather_context()` immediately after the AD-630 subordinate-stats block. Gates on `agent.agent_type in CLINICAL_ROLES` AND `runtime.clinical_telemetry is not None`. Calls all three service methods with `captain_override=False` (the default — kwarg omitted entirely). Aggregates a compact summary dict into `context["clinical_telemetry"]`. Three module-level constants control per-domain recency caps.
2. **State-builder side** (`cognitive_agent.py`): one new section immediately after the AD-630 `_subordinate_stats` block at line 4072. Renders an XML-tagged `<clinical_telemetry>...</clinical_telemetry>` block into `state["_clinical_telemetry"]`.
3. **Prompt-render side** (`compose.py` + `analyze.py`): two new `## Clinical Telemetry` sections, each adjacent to the existing `## Subordinate Activity` (AD-630) section.
4. **Tests** (`test_ad635f_clinical_proactive_context.py`, NEW): 15 tests across five test classes (role gate, error isolation, state builder, prompt render, integration).

**No service-side change.** No new EventType. No new Pydantic config. No new module. No new public attribute on runtime. The `clinical_telemetry.py` query methods, audit ring, and persistence side are bit-for-bit untouched. All AD-635 / AD-635b / AD-635c / AD-635d / AD-635e tests must pass without modification because the service-side code is not edited.

**Deferred at the prompt level:**
- AD-635f-1 — cross-agent chain traces in proactive context (target-selection policy needed; couples to Counselor profile rotation).
- AD-635f-2 — Pydantic config knobs for the per-domain limits (currently module-level constants).
- AD-635f-3 — per-role framing (Chapel and Echo currently see identical summaries).
- AD-635f-4 — non-clinical clearance-bearing agents (e.g., Captain proactive cycle) — would re-enable the captain_override path; v1 keeps the proactive surface clinical-only.
- AD-635f-5 — *(Commercial)* tenant-scoped proactive injection (per-mesh runtime resolver behind a tenant prefix). The OSS injection remains tenant-agnostic; the seam is the runtime injection point.
- AD-635f-6 — HXI surface visualizing the `<clinical_telemetry>` summaries (Captain visibility into what Chapel/Echo see).

## Architect calls (Decision Log)

- **DLog #1 — Role gate at producer side, NOT clearance gate.** The proactive layer narrows by `agent.agent_type in CLINICAL_ROLES` to avoid noisy audit-ring entries from non-clinical agents whose calls would be denied at the service layer anyway. Defense in depth — the service's `_authorize_clinical_query` still enforces actual authorization. Producer-side gate is a performance/noise filter, not a security filter.

- **DLog #2 — `captain_override=False` ALWAYS.** AD-635e's `captain_override` is a Captain-only fast-path; setting it from Chapel/Echo's proactive cycle would (a) be a security regression — any clinical agent's proactive cycle would mark itself as Captain-equivalent, and (b) corrupt the audit ring's `by_captain` field (DLog #4 of AD-635e). The kwarg is omitted entirely; the existing `_authorize_clinical_query` path runs and grants because Chapel holds FULL and Echo holds ORACLE — both pass `QUALIFYING_TIERS`. Test #7 locks this contract via service-call kwargs assertion.

- **DLog #3 — Compact summary, NOT raw rows, in the context dict.** Raw rows from the three queries can be hundreds of dicts; injecting them verbatim would blow LLM context budget. v1 reduces each domain to a small dict: dreams → `{count, latest_ts}`, chain_traces (self-targeted) → `{count, latest_ts, latest_outcome}`, breakers (fleet-wide) → `{count, recent_transitions: [{agent, from, to, ts}, ...] up to 5}`. Mirrors AD-630's reduction (subordinate posts → small per-callsign dict, not raw post payloads).

- **DLog #4 — Self-targeted chain traces ONLY for v1.** The service's `query_agent_chain_traces` requires `target_agent_id`. Self-targeted is the safe useful default — surfaces the same self-monitoring data the agent would see via AD-588. Cross-agent chain traces in proactive context need a target-selection policy (which agent to inspect this cycle?) and would couple AD-635f to Counselor's profile rotation logic. Deferred AD-635f-1.

- **DLog #5 — Fleet-wide breakers (no agent_id filter).** `query_circuit_breaker_history(target_agent_id=None)` returns all-agent transitions; the resulting summary is the highest-signal fitness-for-duty piece because it shows who's flapping right now. Cap at module-level constant `_BREAKER_RECENT_LIMIT = 5`.

- **DLog #6 — Per-domain limits hardcoded as module-level constants in proactive.py, NOT config.** `_DREAM_RECENT_LIMIT = 5`, `_CHAIN_TRACE_RECENT_LIMIT = 5`, `_BREAKER_RECENT_LIMIT = 5`. These are signal-density constants tuned to LLM context economy; making them config knobs is premature. AD-635f-2 if operator demand emerges. Same precedent as AD-635e's `_RECORDS_CONTENT_EXCERPT_CHARS` and the AD-688 `_GRAPH_*` constants.

- **DLog #7 — Tier-2 log-and-degrade on every service call.** Each of the three queries is wrapped in `try/except` → `logger.debug("AD-635f: <domain> fetch failed for %s", agent.id, exc_info=True)` and contributes nothing to the summary on failure. Mirrors AD-630's identical guard at `proactive.py:1815`. Outer `try/except` catches the import + role-check + service-handle failure modes. The clinical_telemetry block NEVER raises into the proactive cycle.

- **DLog #8 — `context_parts["clinical_telemetry"]` lives at the same level as `subordinate_stats`, NOT nested under `self_monitoring`.** AD-504's `self_monitoring` carries the agent's *own* introspective signals; clinical telemetry is *cross-agent* (other agents' fitness data). Same conceptual layer as `subordinate_stats` (a Chief seeing peers' activity), so it lives next to it. Test #15 locks the integration shape.

- **DLog #9 — Render section title `## Clinical Telemetry` (markdown H2).** Mirrors `## Subordinate Activity` (AD-630), `## Recent Ward Room Activity` (AD-413), `## Recent Events`, `## Infrastructure Status` (AD-576). Consistent with the existing prompt-section nomenclature in compose.py / analyze.py.

- **DLog #10 — Both Chapel AND Echo receive injection (no per-role differentiation).** `CLINICAL_ROLES = frozenset({"diagnostician", "counselor"})`. The `_gather_context` branch gates on `agent.agent_type in CLINICAL_ROLES` — both pass. There is no role-specific framing in v1. AD-635f-3 if surfaced.

- **DLog #11 — XML tag wrapping in `_clinical_telemetry` mirrors `_subordinate_stats`.** Reference at `cognitive_agent.py:4076-4084`: `<subordinate_activity>` open, indented per-callsign lines, `</subordinate_activity>` close. AD-635f uses `<clinical_telemetry>` / `</clinical_telemetry>` with the same shape. Agent-side LLMs are already trained on AD-630 XML conventions.

- **DLog #12 — Empty-summary suppression: when all three domains return zero, do NOT inject the key.** Mirrors AD-630 at `proactive.py:1813`: `if sub_stats:` guards the assignment. Empty dict means no signal; suppressing avoids prompt clutter. Test #6 (state-builder side) and the producer-side `if _clin:` guard both lock this — defense in depth.

- **DLog #13 — Wave-10 reframe NOT triggered.** Producer side: one new branch. State builder: one new section. Prompt render: two new sections. Zero call-site refactors. Single Builder cycle is comfortably tractable. Purely additive — every existing callsite, every existing test, every existing prompt remains bit-for-bit unchanged when the agent is not Chapel or Echo.

- **DLog #14 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-65 — `scripts/phantom-api-precheck.ps1` PowerShell parser error documented in user-memory. Manual verify-first pass at draft (16 verifying greps; all confirmed against HEAD `1edc781`). Net-new symbols are intra-prompt-introduction (`context["clinical_telemetry"]` key, `state["_clinical_telemetry"]` key, three `_*_RECENT_LIMIT` module constants). Same FP class as Waves 27-65.

- **DLog #15 — Test count target +15 (window [+13, +18]).** Role gate (4) + per-domain error isolation (3) + state builder (3) + prompt render (4) + integration (1) = 15. Floor +13 absorbs one missed boundary case; ceiling +18 absorbs two extra integration shapes if the Builder discovers an edge.

- **DLog #16 — Commercial-leak audit: clean.** AD-635f is OSS plumbing — one new branch in proactive.py, one new section in cognitive_agent.py, two new sections (compose.py + analyze.py), fifteen tests. The AD-635f-5 *(Commercial)* deferral names tenant-scoped variants; the OSS injection remains tenant-agnostic. The dispatch contains zero pricing, revenue model, customer counts, professional-services positioning, competitive analysis, or GTM language. **Clean.**

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11386 collected at HEAD `1edc781`.
2. Apply Section 0 (`proactive.py` module-level constants).
3. Apply Section 1 (`proactive.py` `_gather_context` branch). Run `pytest tests/test_ad630_leadership_feedback.py tests/test_ad635*.py -n 0` → confirm zero regression.
4. Apply Section 2 (`cognitive_agent.py` state builder). Re-run AD-630 / AD-635* tests.
5. Apply Section 3 (`compose.py` render). Run `pytest tests/test_ad645_composition_briefs.py tests/test_ad644_phase3_situation_awareness.py -n 0` → confirm zero regression.
6. Apply Section 4 (`analyze.py` render). Re-run AD-644 / AD-645 tests.
7. Run `python -c "from probos.cognitive.clinical_telemetry import CLINICAL_ROLES; print(CLINICAL_ROLES)"` to confirm import path.
8. Apply Section 5 (NEW test file). Add the 15 tests one at a time; confirm each passes before adding the next.
9. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11401 (+15 net target; window [+13, +18] = [11399, 11404]).
10. **Update tracking:**
    - `PROGRESS.md` — append CLOSED paragraph.
    - `docs/development/roadmap.md:5966` — flip `*(Scoped, OSS, Issue #395)*` → `*(complete)*`.
    - `prompts/wave-plan.yaml` (id 66) — `status: done`.

## Hard-stop conditions

1. Test count delta lands outside [+13, +18]. → Triage which class over/under-shot.
2. Existing AD-630 / AD-635 / AD-635b / AD-635c / AD-635d / AD-635e / AD-644 / AD-645 tests fail. → Producer- or render-side change is leaking past the role gate or empty-summary guard. Hard-stop and re-read DLog #1 / DLog #12.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/proactive.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/sub_tasks/compose.py`, `src/probos/cognitive/sub_tasks/analyze.py`, `tests/test_ad635f_clinical_proactive_context.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any test or any source file passes `captain_override=True` from the proactive path. → Security regression per DLog #2. Hard-stop.
5. Any source change to `src/probos/cognitive/clinical_telemetry.py`, `src/probos/cognitive/clinical_audit_store.py`, `src/probos/cognitive/circuit_breaker_history_store.py`, `src/probos/routers/clinical.py`, `src/probos/experience/commands/commands_clinical.py`, or `src/probos/experience/panels.py`. → AD-635f does NOT modify these files (DLog #2/#7). Hard-stop.
6. Any test inserts a runtime fixture that boots a real `ProbOSRuntime`. → Use MagicMock per `test_ad630_leadership_feedback.py::_make_loop_and_rt` precedent. Full-runtime fixtures explode wave-gate runtime budget. Hard-stop.
7. The `from probos.cognitive.clinical_telemetry import CLINICAL_ROLES` import inside `_gather_context` creates a circular import. → Verified no cycle at HEAD (`clinical_telemetry.py` does NOT import `probos.proactive`). If cycle appears post-edit, move the import to `proactive.py` module top.

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635f v1 CLOSED.` paragraph (mirrors AD-635e). |
| `docs/development/roadmap.md:5966` | Flip `*(Scoped, OSS, Issue #395)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook proactive-context-injection sibling pattern; mirrors AD-630 byte-for-byte structurally). |
| `prompts/wave-plan.yaml` (id: 66) | Set `status: done` post-archive. |
| GH issue #395 | Closed by Captain post-merge with commit hash. |

## Series Closure

AD-635f is the **last** AD-635 child. Post-build, the AD-635 series is end-to-end complete:
- AD-635 v1 — service facade + audit ring (Wave 60)
- AD-635b — audit persistence (Wave 62)
- AD-635c — circuit-breaker history (Wave 63)
- AD-635d — REST endpoints (Wave 64)
- AD-635e — Captain shell + `captain_override` (Wave 65)
- AD-635f — proactive context injection for clinical agents (Wave 66, this AD)

Roadmap section at `docs/development/roadmap.md:5944` should now show all six entries flipped to `*(complete)*` — the Captain may consider promoting the AD-635 group to a top-level "Clinical Telemetry Surface (COMPLETE)" header in a future cleanup pass (out of v1 scope).
