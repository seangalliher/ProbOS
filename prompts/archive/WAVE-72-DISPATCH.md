# WAVE 72 DISPATCH — AD-696 v1 Agentic Oracle Retrieval (single AD)

**Wave id:** 72
**Single AD:** AD-696 v1 (full scope per GH issue #416)
**Closes:** GH issue #416
**Baseline test count:** 11433 (HEAD `66ee2eb`, post-Wave-71) → expected **11446** (+13 net), window **[+10, +14]** = [11443, 11447]
**HEAD at draft:** `66ee2eb`, working tree clean
**Builder:** required

## Summary

`OracleService` runs in exactly one mode at HEAD: pre-instantiation RAG injection. Crew agents that discover a need for specific records mid-chain have no mechanism — the architectural asymmetry was self-reported by an agent during a 2026-05-04 reflection cycle:

> *"The Oracle shapes what I know before I start thinking, but I can't direct it once I'm already thinking."*

AD-696 v1 closes the seam by registering Oracle as an agent-invocable tool and wiring an on-demand retrieval step between the chain's triage (QUERY + ANALYZE) and execute (COMPOSE + EVALUATE + REFLECT) phases. The full scope is named in GH issue #416 and `roadmap.md:7191-7202`:

- **QUERY operation** (`oracle_lookup` in `_QUERY_OPERATIONS` dispatch table at `query.py:266-280`)
- **ToolRegistry registration** (`runtime.oracle.query_formatted` wrapped via `DirectServiceAdapter`, `ToolPermission.READ`, gated by `RecallTier.ORACLE`)
- **ANALYZE intent signal** (`oracle_query` added to `intended_actions` vocab at `analyze.py:174,379` plus a new `oracle_query_text` JSON field)
- **Chain dispatch seam** (one-shot, between triage and execute, in `_execute_chain_with_intent_routing` at `cognitive_agent.py:1979-2284`)
- **Result rendering** reuses the existing `observation["_oracle_context"]` key — COMPOSE picks it up at `compose.py:495` with zero template change

**Discipline:** v1 is once per chain (DLog #4 in the per-AD prompt). The `_oracle_lookup_fired` flag prevents reflexive querying. AD-696b (temporal decay), AD-696c (query intent classification), AD-696d (multi-turn retrieval chains) are explicitly deferred per GH #416 scope.

**Recall-tier gate:** `RecallTier.ORACLE` only — same gate as the existing AD-620 RAG-style path at `cognitive_agent.py:5208-5214`. Resolver call mirrors that path line-for-line.

**No commercial leak.** AD-696 is OSS plumbing — one EventType, one QUERY op, one tool registration, one chain helper, three short ANALYZE prompt insertions, fourteen tests. Deferred children remain OSS.

## Architect calls (Decision Log)

The full 15-item decision log lives in `prompts/ad-696-agentic-oracle-retrieval-v1.md` Sections "Architect calls (Decision Log)". Highest-risk items repeated here for Builder pre-flight:

- **DLog #1 — Reuse `_oracle_context` injection key.** Free downstream rendering. Trade-off: agentic result overwrites pre-RAG result (acceptable in v1; AD-696b adds timestamp tags).
- **DLog #2 — `oracle_lookup` as a QUERY op, NOT a new SubTaskType.** Preserves the "5 sub-task types" invariant in `sub_task.py:29`.
- **DLog #4 — Once per chain, hard.** `_oracle_lookup_fired` flag. The agent self-report named the failure mode: *"An agent that fires Oracle queries on every uncertainty isn't thinking; it's just searching."*
- **DLog #5 — Recall-tier gate inside the QUERY op, NOT inside the chain helper.** Future callers (utility agent, slash command, MCP bridge) get the same gate for free.
- **DLog #7 — `runtime.oracle` (public) NOT `runtime._oracle_service` (private).** Public alias added at `runtime.py:1349` for AD-686. Wave-5 convention #1 from day one.
- **DLog #8 — `ToolPermission.READ` not `OBSERVE`.** Oracle returns content the agent will quote, paraphrase, or reason from.
- **DLog #9 — Tool registration in `startup/communication.py`, NOT `startup/finalize.py`.** Mirrors existing precedent at `communication.py:391-396`.
- **DLog #10 — No new Pydantic config.** Hard-coded budget mirrors AD-620 path (`k_per_tier=3`, `max_chars=2000`). v1 is zero-config.
- **DLog #14 — Commercial-leak audit: clean.**

## Builder workflow (standard)

1. **Pre-flight gate:** `pytest tests/ -q -n 4 --dist=loadfile` → confirm 11433 collected at HEAD `66ee2eb`.
2. Apply Section 0 (`events.py` 1 new EventType line). No tests should regress yet — additive only.
3. Apply Section 1 (`query.py` new function + dispatch-table entry). Run `pytest tests/test_*query* tests/test_*sub_task* -n 0 -q` to confirm zero regression on the QUERY surface.
4. Apply Section 2 (3 SEARCH/REPLACE blocks in `analyze.py`). Run `pytest tests/test_*analyze* tests/test_ad643* tests/test_ad646* -n 0 -q` to confirm prompt changes do not break the existing ANALYZE-output extraction.
5. Apply Section 3 (3 SEARCH/REPLACE blocks in `cognitive_agent.py`). Run `pytest tests/test_cognitive_agent*.py tests/test_ad643*.py -n 0 -q` to confirm chain wiring is intact.
6. Apply Section 4 (`startup/communication.py` registration block). Run `pytest tests/test_*communication* tests/test_*tool* tests/test_ad423* -n 0 -q` to confirm tool-registry surface is intact.
7. Apply Section 5 (NEW test file `tests/test_ad696_agentic_oracle_retrieval.py`). Add the 13 tests one at a time; confirm each passes before adding the next.
8. **Final gate:** `pytest tests/ -q -n 4 --dist=loadfile` → expect 11446 (+13 net target; window [+10, +14] = [11443, 11447]).
9. **Update tracking:**
   - `PROGRESS.md` — append CLOSED paragraph for AD-696 v1.
   - `docs/development/roadmap.md` — flip the AD-696 entry status from `*(Scoped, OSS, Issue #416)*` to `*(complete via AD-696 v1, Wave 72 — QUERY operation + ToolRegistry registration + ANALYZE intent signal; temporal decay deferred to AD-696b, query intent classification deferred to AD-696c, multi-turn retrieval deferred to AD-696d)*`.
   - `prompts/wave-plan.yaml` (id 72) — `status: done`.
   - GH issue #416 — close with comment listing the four shipping pieces (QUERY op, tool registration, ANALYZE intent signal, chain dispatch seam) + the three deferred children + this commit hash.

## Hard-stop conditions

1. Test count delta lands outside [+10, +14]. → Triage which class over/under-shot.
2. Existing ANALYZE / chain / tool-registry tests fail. → SEARCH/REPLACE blocks may have drifted from the live anchors at HEAD `66ee2eb`. Re-grep before retrying.
3. Real working-tree changes appear in source files NOT named in this dispatch (`src/probos/events.py`, `src/probos/cognitive/sub_tasks/query.py`, `src/probos/cognitive/sub_tasks/analyze.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/startup/communication.py`, `tests/test_ad696_agentic_oracle_retrieval.py`, plus tracking files). → Hard stop, surface to Captain.
4. Any source change to `src/probos/cognitive/oracle_service.py` (Oracle internals are unchanged in v1 — we only call `query_formatted`), `src/probos/cognitive/sub_tasks/compose.py`, `src/probos/cognitive/sub_tasks/evaluate.py`, `src/probos/cognitive/sub_tasks/reflect.py`, `src/probos/runtime.py`, `src/probos/startup/finalize.py`, or `src/probos/cognitive/sub_task.py`. → Hard-stop. (DLog #2: no new SubTaskType. DLog #9: no register-call in finalize.py. DLog #1: no new compose template.)
5. Any new Pydantic config field, any change to `src/probos/config.py`, any change to `config/system.yaml`, or any new `*Config` class. → DLog #10 violation. Hard-stop.
6. Any test boots a real `ProbOSRuntime` to validate Section 3 or Section 4 wiring. → Use `MagicMock` per Wave 13/66/67/68/69/70 fixture precedent. Test #14 instantiates a real `ToolRegistry()` but uses a `MagicMock` runtime. Hard-stop on any `ProbOSRuntime(...)` boot in this test file.
7. The `oracle_query_text` field is dropped from Section 2.3a OR 2.3b, OR the once-per-chain `_oracle_lookup_fired` flag is omitted in Section 3.3, OR the `RecallTier.ORACLE` gate is omitted in Section 1.1. → DLog #3, #4, #5 violations. Hard-stop and re-read.
8. The third ANALYZE surface at `analyze.py:467` (DM comprehension prompt) is modified. → Section 2 explicitly excludes it; this is the AD-696b extension surface. Hard-stop.
9. Tool registration is placed inside the `for tc in ontology.get_tool_capabilities():` loop OR uses `InfraServiceAdapter` (intent-bus dispatch) instead of `DirectServiceAdapter` (direct method call). → DLog #9 placement violation OR DLog #7 wrong-adapter violation. Oracle is a runtime service with a direct async method, NOT an intent-bus-routed agent. Hard-stop.
10. The Builder elects to ship AD-696b, AD-696c, OR AD-696d "while we're here" — even partially, even as a stub. → Out of scope. Hard-stop.

## Acceptance criteria

1. Full gate passes at 11446 ± 2 (target +13; window [11443, 11447]).
2. All Section 0–5 SEARCH/REPLACE / CREATE blocks applied byte-for-byte as specified.
3. 13 new tests in `tests/test_ad696_agentic_oracle_retrieval.py` all pass.
4. No file outside the dispatch's named set is modified (other than tracking files: `PROGRESS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml`).
5. The Builder build report cites the test count delta + the ten "what this AD does NOT change" verifications.
6. The Builder build report explicitly cites which deferred children remain (AD-696b temporal decay, AD-696c query intent classification, AD-696d multi-turn retrieval) and what their forcing functions are.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `66ee2eb`)

The full 16-item verify-first table lives in the per-AD prompt at `prompts/ad-696-agentic-oracle-retrieval-v1.md` "Verified Against Codebase" footer. Highest-risk anchors repeated here:

```
grep -n "self.oracle = cog.oracle_service" src/probos/runtime.py
  1349:    self.oracle = cog.oracle_service  # AD-686 (public alias; same instance)
  (DLog #7: public seam exists at HEAD)

grep -n "_QUERY_OPERATIONS\|_query_introspective_telemetry" src/probos/cognitive/sub_tasks/query.py
  239:    async def _query_introspective_telemetry(
  266:    _QUERY_OPERATIONS: dict[str, QueryOperation] = {
  279:    "introspective_telemetry": _query_introspective_telemetry,
  (Section 1.1 + 1.2 SEARCH anchors confirmed; "oracle_lookup" key collision-free)

grep -n "_extract_intended_actions" src/probos/cognitive/cognitive_agent.py
  1725:    def _extract_intended_actions(chain_results: list) -> list[str]:
  2191:        intended_actions = self._extract_intended_actions(triage_results)
  (Section 3.2 SEARCH anchor + Section 3.3 helper insertion anchor confirmed)

grep -n "Return a JSON object with these" src/probos/cognitive/sub_tasks/analyze.py
  208:    f"Return a JSON object with these 7 keys. No other text."
  411:    "Return a JSON object with these 6 keys. No other text."
  (Section 2.3a + 2.3b SEARCH anchors confirmed)

grep -n "tool_registry.register" src/probos/startup/communication.py
  391:    tool_registry.register(
  (Section 4 SEARCH anchor confirmed)

grep -rn "test_ad696" tests/
  (no matches — net-new test file confirmed)

grep -n "AD-696" docs/development/roadmap.md
  7187: ### Agentic Oracle Retrieval (AD-696)
  7191: AD-696: ... *(Scoped, OSS, Issue #416)* — Register OracleService as ...
  7202: v1 = QUERY operation + ToolRegistry registration + ANALYZE intent signal. Deferred: ...
  (roadmap source-of-truth confirms scope alignment with this prompt)

grep -n "ORACLE_LOOKUP_DISPATCHED\|oracle_lookup" src/probos/events.py
  (no matches — collision-free for net-new ORACLE_LOOKUP_DISPATCHED)
```

---

## Per-AD prompt path

`prompts/ad-696-agentic-oracle-retrieval-v1.md`
