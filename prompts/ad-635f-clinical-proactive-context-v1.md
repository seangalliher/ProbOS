# AD-635f v1 — Clinical Telemetry: Proactive Context Injection

**Status:** Draft (Wave 66, last AD-635 child)
**Closes:** GH issue #395
**Depends on:** AD-635 v1 (COMPLETE), AD-635b (audit persistence, COMPLETE), AD-635c (circuit-breaker history, COMPLETE), AD-635e (shell command + `captain_override` kwarg, COMPLETE)
**Related:** AD-630 (subordinate-stats injection — structural mirror), AD-644 (Situation-Awareness architecture)
**HEAD at draft:** `1edc781`
**Baseline test count:** 11386 → expected **11401** (+15 net), window **[+13, +18]**
**Builder:** required

## Problem

AD-635 / AD-635b / AD-635c shipped the **service** (cross-agent dream/chain-trace/circuit-breaker query facade with audit). AD-635d shipped **REST**. AD-635e shipped the **Captain shell** (`/clinical`). Clinical agents themselves — Chapel (`agent_type="diagnostician"`, FULL clearance) and Echo (`agent_type="counselor"`, ORACLE clearance) — still have no automatic visibility into clinical telemetry during their proactive cognitive cycles. They must explicitly query the service.

That contradicts the AD-630 Chiefs pattern: Chiefs see subordinate stats automatically because the proactive loop pre-assembles them into `context["subordinate_stats"]`. Clinical agents should see fitness-for-duty signals the same way.

GH issue #395 verbatim: *"Clinical agents (Chapel, Echo) see diagnostic data summary during `_gather_context()` when health assessment is active. Parallels AD-630 subordinate stats injection pattern. Enables proactive fitness-for-duty assessments without explicit queries."*

The roadmap entry at `docs/development/roadmap.md:5966` says the same: AD-635f is the proactive-injection sibling of the AD-630 subordinate-stats pattern, scoped specifically to clinical agents.

## Verified Against Codebase (HEAD `1edc781`)

```
src/probos/cognitive/clinical_telemetry.py:57    CLINICAL_ROLES = frozenset({"diagnostician", "counselor"})
src/probos/cognitive/clinical_telemetry.py:65    class ClinicalTelemetryService
src/probos/cognitive/clinical_telemetry.py:93    async def query_dream_history(*, requester_agent_id, limit=20, captain_override: bool = False) -> list[dict]
src/probos/cognitive/clinical_telemetry.py:149   async def query_agent_chain_traces(*, requester_agent_id, target_agent_id, limit=20, captain_override: bool = False)
src/probos/cognitive/clinical_telemetry.py:226   @property def audit_log -> list[dict]
src/probos/cognitive/clinical_telemetry.py:230   async def query_circuit_breaker_history(*, requester_agent_id, target_agent_id=None, limit=50, captain_override: bool = False)
src/probos/cognitive/clinical_telemetry.py:367   def _record_audit(...*, granted, result_count, target_agent_id=None, by_captain=False)
src/probos/proactive.py:1156                     async def _gather_context(self, agent: Any, trust_score: float) -> dict
src/probos/proactive.py:1793                     # AD-630: Subordinate communication stats for Chiefs (reference pattern)
src/probos/proactive.py:1815                     logger.debug("AD-630: Subordinate stats fetch failed for %s", agent.id, exc_info=True)
src/probos/cognitive/cognitive_agent.py:4072     # 5. Subordinate stats (AD-630) — Chiefs only (reference renderer)
src/probos/cognitive/cognitive_agent.py:4084     state["_subordinate_stats"] = "\n".join(sub_lines)
src/probos/cognitive/sub_tasks/compose.py:543    _sub_stats = context.get("_subordinate_stats", "")
src/probos/cognitive/sub_tasks/analyze.py:270    _sub_stats = context.get("_subordinate_stats", "")
docs/development/roadmap.md:5966                 AD-635f *(Scoped, OSS, Issue #395)*
DECISIONS.md highest                             AD-695 — AD-635f is unique
PROGRESS.md baseline                             11386 (post-Wave-65)
```

The two cognitive_agent renderers exist at lines 4060–4090 and again near 4622 (AD-644 SA-arch path); only the first ("compose"-side observation builder) needs AD-635f wiring — the second is the analyze-arc that pulls the same `_clinical_telemetry` key out of the same dict per the AD-630 pattern.

## Solution

Mirror AD-630 byte-for-byte structurally:

1. **Producer side** — new branch in `proactive.py::_gather_context()` immediately after the AD-630 subordinate-stats block. Gates on `agent.agent_type in CLINICAL_ROLES` AND `runtime.clinical_telemetry is not None`. Calls the three service methods with `captain_override=False, requester_agent_id=agent.id` (Chapel and Echo legitimately hold FULL/ORACLE — the audit row records a real authorized read, not a Captain bypass). Aggregates a compact summary dict into `context["clinical_telemetry"]`.
2. **State-builder side** — new section in `cognitive_agent.py` observation-builder immediately after the AD-630 `_subordinate_stats` block at line 4072. Reads `context_parts.get("clinical_telemetry")` and renders an XML-tagged `<clinical_telemetry>...</clinical_telemetry>` block into `state["_clinical_telemetry"]`.
3. **Prompt-render side** — two new sections (one in `compose.py` adjacent to `_subordinate_stats`, one in `analyze.py` adjacent to the same) that pick up `context["_clinical_telemetry"]` and append a `## Clinical Telemetry` section to the rendered prompt.

No service-side change. No new EventType. No new Pydantic config. No new module. No new dependency. The `CLINICAL_ROLES` frozenset is imported from `clinical_telemetry.py` directly — already public.

## Architect calls (Decision Log)

- **DLog #1 — Gate is `agent_type in CLINICAL_ROLES`, NOT a clearance check.** The service's own clearance gate fires inside `_authorize_clinical_query` and decides what to return. The proactive injection only filters the *attempt* to call the service; the service decides what data the clinical agent is allowed to see. Defense in depth — proactive layer narrows by role to avoid noisy audit-ring entries from non-clinical agents whose calls would be denied anyway, and the service layer enforces actual authorization.

- **DLog #2 — `captain_override=False`, ALWAYS.** AD-635e introduced `captain_override` as a Captain-only fast-path; it bypasses the clearance gate AND stamps `by_captain=True` on the audit row. Chapel and Echo are clinical agents legitimately holding FULL/ORACLE — they pass the real gate. Setting `captain_override=True` here would (a) be a security regression (any clinical agent's proactive cycle would mark itself as Captain-equivalent), and (b) corrupt the audit ring's `by_captain` field. The kwarg is omitted (defaults to False); the existing `_authorize_clinical_query` path runs.

- **DLog #3 — Compact summary, NOT raw rows, in the context dict.** Raw rows from the three queries can be hundreds of dicts; injecting them verbatim would blow the LLM token budget and overwhelm signal-to-noise. v1 reduces each domain to a small dict: dreams → `{count, latest_ts}`, chain_traces (self-targeted) → `{count, latest_ts, latest_outcome}`, breakers (fleet-wide) → `{count, recent_transitions: [{agent, from, to, ts}, ...] up to 5}`. This matches the AD-630 reduction pattern (subordinate posts → small per-callsign dict, not raw post payloads).

- **DLog #4 — Self-targeted chain traces ONLY for v1.** The service's `query_agent_chain_traces` requires `target_agent_id`. Clinical agents looking at *their own* chain traces is the safe, useful default — it surfaces the same self-monitoring data they'd see via AD-588. Cross-agent chain traces in proactive context need a target-selection policy (which agent to inspect this cycle?) and would couple AD-635f to the Counselor's profile rotation logic. Deferred to AD-635f-1.

- **DLog #5 — Fleet-wide breakers (no agent_id filter).** The service's `query_circuit_breaker_history(target_agent_id=None)` returns all-agent transitions; the resulting summary is the highest-signal piece for fitness-for-duty assessment because it shows who's flapping at the moment. Limit clamped at module-level constant `_BREAKER_RECENT_LIMIT = 5`.

- **DLog #6 — Per-domain limits hardcoded as module-level constants in proactive.py, NOT config.** v1 uses `_DREAM_RECENT_LIMIT = 5`, `_CHAIN_TRACE_RECENT_LIMIT = 5`, `_BREAKER_RECENT_LIMIT = 5`. These are signal-density constants tuned to LLM context economy; making them config knobs is premature. AD-635f-2 if operator demand emerges.

- **DLog #7 — Tier-2 log-and-degrade on every service call.** Each of the three queries is wrapped in `try/except` → `logger.debug("AD-635f: <domain> fetch failed for %s", agent.id, exc_info=True)` and contributes nothing to the summary on failure. Mirrors AD-630's identical guard at `proactive.py:1815`. The clinical_telemetry block NEVER raises into the proactive cycle.

- **DLog #8 — `context_parts["clinical_telemetry"]` lives at the same level as `subordinate_stats`, NOT nested under `self_monitoring`.** The AD-504 `self_monitoring` key carries the agent's *own* introspective signals; clinical telemetry is *cross-agent* (other agents' fitness data). Same conceptual layer as `subordinate_stats` (a Chief seeing peers' activity), so it lives next to it.

- **DLog #9 — Render section title: `## Clinical Telemetry`.** Mirrors `## Subordinate Activity` (AD-630), `## Recent Ward Room Activity` (AD-413), `## Recent Events`, `## Infrastructure Status` (AD-576). Consistent with the existing prompt-section nomenclature in compose.py / analyze.py.

- **DLog #10 — Chapel and Echo BOTH receive injection.** The `CLINICAL_ROLES` frozenset is `{"diagnostician", "counselor"}`. The `_gather_context` branch gates on `agent.agent_type in CLINICAL_ROLES` — both roles pass. There is no per-role differentiation in v1 (Chapel and Echo see the same three summaries). AD-635f-3 if role-specific framing is needed.

- **DLog #11 — XML tag wrapping in `_clinical_telemetry` mirrors `_subordinate_stats`.** Reference pattern at `cognitive_agent.py:4076-4084`: `<subordinate_activity>` open tag, indented per-callsign lines, `</subordinate_activity>` close tag. AD-635f uses `<clinical_telemetry>` / `</clinical_telemetry>` with the same shape. The agent-side LLM has been trained on AD-630 XML conventions.

- **DLog #12 — Empty-summary suppression: when all three domains return zero, do NOT inject the key.** Mirrors AD-630 at `proactive.py:1813` — `if sub_stats:` guards the assignment. Empty `clinical_telemetry` dict means no signal; suppressing avoids prompt clutter. Test #11 locks this behavior.

- **DLog #13 — Wave-10 reframe NOT triggered.** The producer side is one new branch in `_gather_context`; the state-builder side is one new section; each prompt-render module gets one new section. Zero call-site refactors. Single Builder cycle is comfortably tractable. The change is purely additive — every existing callsite, every existing test, every existing prompt remains bit-for-bit unchanged when the agent is not Chapel or Echo.

- **DLog #14 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-65 — `scripts/phantom-api-precheck.ps1` PowerShell parser error documented in user-memory. Manual verify-first pass performed at draft (16 verifying greps; all confirmed against HEAD `1edc781`). Net-new symbols are intra-prompt-introduction (`context["clinical_telemetry"]` key, `state["_clinical_telemetry"]` key, `_DREAM_RECENT_LIMIT`/`_CHAIN_TRACE_RECENT_LIMIT`/`_BREAKER_RECENT_LIMIT` module constants). Same FP class as Waves 27-65.

- **DLog #15 — Test count target +15 (within window [+13, +18]).** Producer side (4 tests: clinical role injection happy path, non-clinical no injection, service-disabled no injection, three-domain failure all log-and-degrade) + state-builder side (3 tests: rendering with summary, empty-summary skip, XML tag shape) + prompt-render side (4 tests: compose includes section, compose skips when empty, analyze includes section, analyze skips when empty) + integration (4 tests: end-to-end Chapel proactive cycle producing `## Clinical Telemetry` in prompt; end-to-end Echo same; service `captain_override=False` audit-ring entry asserted; non-clinical agent's `_gather_context` does not call the service) = 15 tests. Floor +13 absorbs one boundary test miss; ceiling +18 absorbs two extra integration shapes if the Builder discovers an edge.

- **DLog #16 — Commercial-leak audit: clean.** AD-635f is OSS plumbing — one new branch in proactive.py, one new section in cognitive_agent.py, two new sections (compose.py + analyze.py), fifteen tests. No deferral mentions tenant scoping or revenue model. The architecture pattern (proactive context injection) is OSS-native; commercial overlays would attach via the existing AD-630 / AD-635 extension seams. No pricing, no GTM language, no competitive analysis. **Clean.**

## What this AD does NOT change

- No service-side change to `clinical_telemetry.py`. Three query methods, the audit ring, and the persistence side are untouched. Existing AD-635 / AD-635b / AD-635c / AD-635d / AD-635e tests must pass without modification.
- No new EventType. No new Pydantic config. No new module. No new public attribute on runtime.
- No HXI surface. No shell command (the Captain still uses `/clinical` from AD-635e).
- No multi-user / non-clinical-role path. AD-635f-3 covers per-role differentiation if needed.
- No cross-agent chain-trace target selection (AD-635f-1).
- No config knob for the per-domain limits (AD-635f-2).
- No on-demand refresh. The proactive cycle's tick rate is the refresh rate.
- No federation / cross-mesh (records are local).

## Implementation

### Section 0: Module-level constants in proactive.py

Insert immediately AFTER the existing imports block in `src/probos/proactive.py` (locate the area around line 80–120 just below the `from __future__ import annotations` + stdlib imports — pick the canonical location next to other proactive-only module constants if any exist; otherwise insert just below the `logger = logging.getLogger(__name__)` line).

```
===SEARCH===
logger = logging.getLogger(__name__)
===REPLACE===
logger = logging.getLogger(__name__)


# AD-635f: Per-domain recency caps for clinical telemetry context injection.
# Module-level constants (NOT config) — signal-density tuning for LLM context.
_DREAM_RECENT_LIMIT = 5
_CHAIN_TRACE_RECENT_LIMIT = 5
_BREAKER_RECENT_LIMIT = 5
===END REPLACE===
```

If `logger = logging.getLogger(__name__)` does not appear at the canonical location (verify before applying), the Builder must locate the actual single instance and SEARCH against that exact line plus its surrounding 3-line context.

### Section 1: New `_gather_context` branch in proactive.py

Insert immediately AFTER the AD-630 `# AD-630: Subordinate stats fetch failed` debug-log line at `proactive.py:1815`, BEFORE the `# AD-504: Self-monitoring context` block at `:1818`.

```
===SEARCH===
                logger.debug("AD-630: Subordinate stats fetch failed for %s", agent.id, exc_info=True)

        # AD-504: Self-monitoring context
===REPLACE===
                logger.debug("AD-630: Subordinate stats fetch failed for %s", agent.id, exc_info=True)

        # AD-635f: Clinical telemetry summary for clinical agents (Chapel, Echo)
        try:
            from probos.cognitive.clinical_telemetry import CLINICAL_ROLES
            _clinical_service = getattr(rt, "clinical_telemetry", None)
            if (
                _clinical_service is not None
                and getattr(agent, "agent_type", "") in CLINICAL_ROLES
            ):
                _clin: dict[str, Any] = {}

                # Dreams (most recent N)
                try:
                    _dreams = await _clinical_service.query_dream_history(
                        requester_agent_id=agent.id,
                        limit=_DREAM_RECENT_LIMIT,
                    )
                    if _dreams:
                        _latest = _dreams[0] if isinstance(_dreams, list) else None
                        _clin["dreams"] = {
                            "count": len(_dreams),
                            "latest_ts": (_latest or {}).get("ts"),
                        }
                except Exception:
                    logger.debug(
                        "AD-635f: dream summary fetch failed for %s", agent.id,
                        exc_info=True,
                    )

                # Chain traces (self-targeted)
                try:
                    _traces = await _clinical_service.query_agent_chain_traces(
                        requester_agent_id=agent.id,
                        target_agent_id=agent.id,
                        limit=_CHAIN_TRACE_RECENT_LIMIT,
                    )
                    if _traces:
                        _latest = _traces[0] if isinstance(_traces, list) else None
                        _clin["chain_traces"] = {
                            "count": len(_traces),
                            "latest_ts": (_latest or {}).get("ts"),
                            "latest_outcome": (_latest or {}).get("outcome"),
                        }
                except Exception:
                    logger.debug(
                        "AD-635f: chain trace summary fetch failed for %s", agent.id,
                        exc_info=True,
                    )

                # Circuit breakers (fleet-wide)
                try:
                    _breakers = await _clinical_service.query_circuit_breaker_history(
                        requester_agent_id=agent.id,
                        target_agent_id=None,
                        limit=_BREAKER_RECENT_LIMIT,
                    )
                    if _breakers:
                        _recent: list[dict[str, Any]] = []
                        for row in _breakers[:_BREAKER_RECENT_LIMIT]:
                            if not isinstance(row, dict):
                                continue
                            _recent.append({
                                "agent": row.get("agent_id") or row.get("target_agent_id"),
                                "from": row.get("from_zone") or row.get("from"),
                                "to": row.get("to_zone") or row.get("to"),
                                "ts": row.get("ts"),
                            })
                        _clin["breakers"] = {
                            "count": len(_breakers),
                            "recent_transitions": _recent,
                        }
                except Exception:
                    logger.debug(
                        "AD-635f: breaker summary fetch failed for %s", agent.id,
                        exc_info=True,
                    )

                if _clin:
                    context["clinical_telemetry"] = _clin
        except Exception:
            logger.debug(
                "AD-635f: clinical telemetry injection failed for %s", agent.id,
                exc_info=True,
            )

        # AD-504: Self-monitoring context
===END REPLACE===
```

### Section 2: New section in `cognitive_agent.py` observation builder

Insert immediately AFTER the AD-630 `_subordinate_stats` block at `cognitive_agent.py:4072-4084`, BEFORE the BF-034 cold-start block.

```
===SEARCH===
        # 5. Subordinate stats (AD-630) — Chiefs only
        sub_stats = context_parts.get("subordinate_stats")
        if sub_stats:
            sub_lines = ["<subordinate_activity>"]
            for callsign, stats in sub_stats.items():
                sub_lines.append(
                    f"  {callsign}: {stats['posts_total']} posts, "
                    f"{stats['endorsements_given']} endorsements given, "
                    f"{stats['endorsements_received']} endorsements received, "
                    f"credibility {stats['credibility_score']:.2f}"
                )
            sub_lines.append("</subordinate_activity>")
            state["_subordinate_stats"] = "\n".join(sub_lines)

        # 6. Cold-start system note (BF-034)
===REPLACE===
        # 5. Subordinate stats (AD-630) — Chiefs only
        sub_stats = context_parts.get("subordinate_stats")
        if sub_stats:
            sub_lines = ["<subordinate_activity>"]
            for callsign, stats in sub_stats.items():
                sub_lines.append(
                    f"  {callsign}: {stats['posts_total']} posts, "
                    f"{stats['endorsements_given']} endorsements given, "
                    f"{stats['endorsements_received']} endorsements received, "
                    f"credibility {stats['credibility_score']:.2f}"
                )
            sub_lines.append("</subordinate_activity>")
            state["_subordinate_stats"] = "\n".join(sub_lines)

        # 5b. Clinical telemetry (AD-635f) — Chapel, Echo only
        clin = context_parts.get("clinical_telemetry")
        if clin:
            clin_lines = ["<clinical_telemetry>"]
            _dreams = clin.get("dreams")
            if isinstance(_dreams, dict):
                clin_lines.append(
                    f"  dreams: {_dreams.get('count', 0)} recent"
                )
            _traces = clin.get("chain_traces")
            if isinstance(_traces, dict):
                clin_lines.append(
                    f"  chain_traces: {_traces.get('count', 0)} self "
                    f"(latest_outcome={_traces.get('latest_outcome', 'unknown')})"
                )
            _breakers = clin.get("breakers")
            if isinstance(_breakers, dict):
                _recent = _breakers.get("recent_transitions") or []
                clin_lines.append(
                    f"  breakers: {_breakers.get('count', 0)} transitions "
                    f"(recent={len(_recent)})"
                )
                for tr in _recent:
                    if not isinstance(tr, dict):
                        continue
                    clin_lines.append(
                        f"    - {tr.get('agent', '?')}: "
                        f"{tr.get('from', '?')}->{tr.get('to', '?')}"
                    )
            clin_lines.append("</clinical_telemetry>")
            state["_clinical_telemetry"] = "\n".join(clin_lines)

        # 6. Cold-start system note (BF-034)
===END REPLACE===
```

### Section 3: Render section in `compose.py`

Insert immediately AFTER the AD-630 `_subordinate_stats` block in `src/probos/cognitive/sub_tasks/compose.py` (around line 543).

```
===SEARCH===
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        parts.append(f"## Subordinate Activity\n\n{_sub_stats}")

    _cold_start = context.get("_cold_start_note", "")
===REPLACE===
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        parts.append(f"## Subordinate Activity\n\n{_sub_stats}")

    # AD-635f: Clinical telemetry section for Chapel / Echo
    _clinical = context.get("_clinical_telemetry", "")
    if _clinical:
        parts.append(f"## Clinical Telemetry\n\n{_clinical}")

    _cold_start = context.get("_cold_start_note", "")
===END REPLACE===
```

### Section 4: Render section in `analyze.py`

Insert immediately AFTER the AD-630 `_sub_stats` block in `src/probos/cognitive/sub_tasks/analyze.py` (around line 270).

```
===SEARCH===
    # Subordinate stats (AD-630) — Chiefs
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        situation_parts.append(_sub_stats)

    # Active game (BF-110)
===REPLACE===
    # Subordinate stats (AD-630) — Chiefs
    _sub_stats = context.get("_subordinate_stats", "")
    if _sub_stats:
        situation_parts.append(_sub_stats)

    # Clinical telemetry (AD-635f) — Chapel, Echo
    _clinical = context.get("_clinical_telemetry", "")
    if _clinical:
        situation_parts.append(_clinical)

    # Active game (BF-110)
===END REPLACE===
```

### Section 5: Tests — `tests/test_ad635f_clinical_proactive_context.py` (NEW)

Mirror `test_ad630_leadership_feedback.py` for fixture shape (loop + MagicMock runtime, `set_runtime` + `_build_self_monitoring_context = AsyncMock(return_value=None)` to silence the AD-504 path, MagicMock-based `clinical_telemetry` service stub).

Required test classes and tests (15 total):

**`TestClinicalRoleGate` (4 tests)**
1. `test_diagnostician_gets_clinical_telemetry` — `agent.agent_type="diagnostician"`, service returns 3 dreams + 2 traces + 1 breaker → `context["clinical_telemetry"]` populated with `dreams`, `chain_traces`, `breakers` keys.
2. `test_counselor_gets_clinical_telemetry` — same as #1 with `agent.agent_type="counselor"`.
3. `test_non_clinical_agent_no_injection` — `agent.agent_type="engineering_officer"` → service methods NOT called → `"clinical_telemetry" not in context`.
4. `test_service_unavailable_no_injection` — `runtime.clinical_telemetry = None` → branch short-circuits → no exception, no key.

**`TestPerDomainErrorIsolation` (3 tests)**
5. `test_dream_query_failure_logs_and_skips_dreams` — `query_dream_history` raises; `chain_traces` + `breakers` still collected. No exception escapes. `"dreams" not in context["clinical_telemetry"]`.
6. `test_all_three_queries_fail_no_key_injected` — all three raise; `"clinical_telemetry" not in context`.
7. `test_captain_override_never_set_to_true` — assert all three service calls were invoked WITHOUT `captain_override=True` (kwarg either absent or explicitly False). Pin DLog #2 audit-row contract.

**`TestStateBuilder` (3 tests)**
8. `test_clinical_telemetry_xml_tags` — provide `context_parts={"clinical_telemetry": {...full summary...}}`, build state, assert `state["_clinical_telemetry"].startswith("<clinical_telemetry>")` and `.endswith("</clinical_telemetry>")` and contains the per-domain summary lines.
9. `test_clinical_telemetry_empty_no_state` — `context_parts={"clinical_telemetry": {}}` (empty dict — should be suppressed at producer side, but defense-in-depth at builder side too): `"_clinical_telemetry" not in state`.
10. `test_clinical_telemetry_partial_summary` — only `dreams` present in summary → state has dream line but no chain_traces/breakers lines.

**`TestPromptRender` (4 tests)**
11. `test_compose_includes_clinical_section` — pass `context={"_clinical_telemetry": "<clinical_telemetry>...stuff...</clinical_telemetry>"}`, call the compose builder, assert the rendered string contains `"## Clinical Telemetry"` followed by the XML body.
12. `test_compose_skips_when_clinical_empty` — `context={}` → rendered string does NOT contain `"## Clinical Telemetry"`.
13. `test_analyze_includes_clinical_section` — analogous to #11 against `analyze.py` builder.
14. `test_analyze_skips_when_clinical_empty` — analogous to #12.

**`TestIntegration` (1 test)**
15. `test_chapel_end_to_end_proactive_cycle_renders_section` — full happy-path integration: MagicMock runtime, MagicMock `clinical_telemetry` service returning realistic dream/chain/breaker rows, MagicMock Chapel agent (`agent_type="diagnostician"`), invoke `_gather_context` → observation builder → compose render. Assert the final rendered prompt string contains `## Clinical Telemetry` AND the `<clinical_telemetry>` XML opening tag AND a `dreams: ` summary line.

## Builder workflow

1. **Pre-flight gate**: `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11386 collected at HEAD `1edc781`.
2. Apply Section 0 (proactive.py module-level constants).
3. Apply Section 1 (proactive.py `_gather_context` branch). Run `pytest tests/test_ad630_leadership_feedback.py tests/test_ad635*.py -n 0` → confirm zero regression in AD-630 / AD-635 / AD-635b / AD-635c / AD-635d / AD-635e tests.
4. Apply Section 2 (cognitive_agent.py state builder). Re-run AD-630 / AD-635* tests.
5. Apply Section 3 (compose.py render). Run `pytest tests/test_ad645_composition_briefs.py tests/test_ad644_phase3_situation_awareness.py -n 0` → confirm zero regression.
6. Apply Section 4 (analyze.py render). Re-run AD-644 / AD-645 tests.
7. Apply Section 5 (NEW test file). Add the 15 tests one at a time; confirm each passes before adding the next.
8. **Final gate**: `pytest tests/ -q -n 4 --dist=loadfile` → expect 11401 (+15 net target; window [+13, +18] = [11399, 11404]).
9. **Update tracking**:
   - `PROGRESS.md` — append CLOSED paragraph entry.
   - `docs/development/roadmap.md:5966` — flip `*(Scoped, OSS, Issue #395)*` → `*(complete)*`.
   - `prompts/wave-plan.yaml` (id 66) — `status: done`.
   - `DECISIONS.md` — NOT modified (textbook proactive-context-injection sibling pattern).

## Hard-stop conditions

1. Test count delta lands outside [+13, +18]. → Triage which test class over/under-shot.
2. Existing AD-630 / AD-635* / AD-644 / AD-645 tests fail. → Producer- or render-side change is leaking past the role gate or empty-summary guard. Hard-stop and re-read DLog #1 / DLog #12.
3. Real working-tree changes appear in source files NOT named in this prompt (`src/probos/proactive.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/sub_tasks/compose.py`, `src/probos/cognitive/sub_tasks/analyze.py`, `tests/test_ad635f_clinical_proactive_context.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any test or any source file passes `captain_override=True` from the proactive path. → That's the security regression in DLog #2. Hard-stop.
5. Any test inserts a runtime fixture that boots a real `ProbOSRuntime`. → Use `MagicMock` per `test_ad630_leadership_feedback.py:_make_loop_and_rt` precedent. Full-runtime fixtures explode wave-gate runtime budget. Hard-stop.
6. The `from probos.cognitive.clinical_telemetry import CLINICAL_ROLES` import creates a circular import. → Verified no cycle at HEAD (`clinical_telemetry.py` does not import from `proactive.py`). If a cycle appears post-edit, move the import to module top of `proactive.py` and surface.

## Tracking

| Tracker | Update |
|---|---|
| `PROGRESS.md` | Append `AD-635f v1 CLOSED.` paragraph (one-paragraph CLOSED entry mirroring AD-635e). |
| `docs/development/roadmap.md:5966` | Flip `*(Scoped, OSS, Issue #395)*` to `*(complete)*`. |
| `DECISIONS.md` | NOT modified (textbook proactive-context-injection sibling pattern; mirrors AD-630 byte-for-byte structurally). |
| `prompts/wave-plan.yaml` (id: 66) | Set `status: done` post-archive. |
| GH issue #395 | Closed by Captain post-merge with commit hash. |

## Acceptance Criteria

- [ ] All 15 new tests in `tests/test_ad635f_clinical_proactive_context.py` pass.
- [ ] `pytest tests/ -q -n 4 --dist=loadfile` collects 11401 (window [11399, 11404]).
- [ ] Zero regressions in AD-630, AD-635, AD-635b, AD-635c, AD-635d, AD-635e, AD-644, AD-645 test files.
- [ ] No `captain_override=True` passed from `proactive.py` (grep verifies absent).
- [ ] Engineering Principles compliance per `.github/copilot-instructions.md`: SOLID-S (one branch per concern in `_gather_context`), tier-2 log-and-degrade on every service call, no fire-and-forget tasks, no bare log messages.
- [ ] Phantom-API pre-check: 0 net-new phantoms (intra-prompt-introduction symbols only).
- [ ] Pre-commit deletion sanity: zero deletions in any modified file (purely additive).
- [ ] `roadmap.md:5966` flipped to `*(complete)*`.
- [ ] `PROGRESS.md` CLOSED paragraph appended.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
