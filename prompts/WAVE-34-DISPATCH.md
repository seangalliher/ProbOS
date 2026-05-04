# Wave 34 Dispatch — AD-647 v1 Process-Oriented Cognitive Chains (Scout Report)

**Status:** Pending
**Issue:** #291 (closes on merge)
**Prompt:** [`prompts/ad-647-process-oriented-chains-v1.md`](ad-647-process-oriented-chains-v1.md)
**Wave plan slot:** id="34" (already populated, status=pending)
**Predecessor:** Wave 33 (AD-661 v1 Diagnostic Context, commit 449c733, gate 10950)
**Expected gate after build:** 10958 (+8)

---

## v1 Scope (one line)

Greenfield `ProcessChainStepKind` / `ProcessChainStep` / `ProcessChainDefinition` / `ProcessChainExecutor` primitive in `src/probos/cognitive/process_chains.py`, plus a Scout-internal migration of `ScoutAgent.act()` to invoke a 4-step `SCOUT_REPORT_CHAIN` (TRANSFORM → TRANSFORM → STORE → NOTIFY) through the executor.

**BF-209 stays.** Removing it requires a registry surface + base-class hook → AD-647b.

## Dependencies — Verify-First Findings (HEAD 449c733)

| Dep | Status | Used in v1? |
|---|---|---|
| AD-618 (Bills) | All sub-ADs (a–e) shipped | NO — deferred to AD-647c |
| AD-595 (Watch Bill) | All sub-ADs (a–e) shipped | NO — deferred to AD-647b/c |
| AD-641g (NATS cognitive pipeline) | **DESIGN ONLY** — no `chain.X.analyze` subjects exist; `NATSBus` is general event bus, not coupled to cognitive chain | NO — sync executor in v1 |
| AD-632 (cognitive chain) | Shipped (`SubTaskExecutor` at `sub_task.py:172`, wired `finalize.py:1579`) | Distinct subsystem; AD-647 is parallel infrastructure |
| BF-209 (Scout opt-out) | Shipped at `scout.py:247` | RETAINED unchanged |

The AD-647 DECISIONS entry (status: Scoped, line 1729) explicitly lists the three deps; v1 deliberately ships without them to unblock the Scout reference implementation. AD-647b (registry + base hook + BF-209 removal) and AD-647c (Bill-driven chains) follow.

## Naming-Collision Notice (read before building)

`SubTaskType(str, Enum)` already exists at `src/probos/cognitive/sub_task.py:31` with values `QUERY/ANALYZE/COMPOSE/EVALUATE/REFLECT`. **Do NOT reuse this enum.** AD-647 introduces a new, distinct enum `ProcessChainStepKind(str, Enum)` with `QUERY/TRANSFORM/STORE/NOTIFY` in the new module. Different concept (process lifecycle vs cognitive sub-task), different module, no collision.

## Phantom-API Pre-Check

Ran `scripts/phantom-api-precheck.ps1` against the prompt:

```
=== prompts/ad-647-process-oriented-chains-v1.md ===
  2 phantom symbol(s):
    - [<Class>.<method>] ScoutAgent.__new__
    - [<Class>(...)] class:TypeError
```

**Both are documented false positives:**
- `ScoutAgent.__new__` — `__new__` is inherited from `object` (stdlib protocol method). Used in the end-to-end test fixture to bypass the spawner constructor while wiring only the attributes the test exercises. Same pattern as Wave 27's test fixture FP class.
- `class:TypeError` — Python builtin exception. Used in `test_executor_rejects_non_dict_handler_return` to assert the wrapped cause type.

**0 NEW phantoms.** Same intro-not-in-index + stdlib FP class as Waves 27/28/29/30/31/32/33.

## Test Plan (8 over 7 floor by 1)

1. `test_definition_step_name_uniqueness_enforced` — duplicate names → `ValueError` at construction.
2. `test_definition_rejects_prompt_template_id_in_v1` — `prompt_template_id` reserved for AD-647b → `ValueError`.
3. `test_executor_runs_steps_sequentially_and_threads_context` — order is canonical; each step sees prior step's output merged.
4. `test_executor_rejects_empty_chain` — empty steps tuple → `ProcessChainExecutionError`.
5. `test_executor_surfaces_handler_exception_with_metadata` — handler raises → wrapped in `ProcessChainExecutionError(chain_name, step_name, cause)`.
6. `test_executor_rejects_non_dict_handler_return` — handler returning non-dict/non-None → `TypeError` wrapped.
7. `test_executor_treats_none_return_as_empty_dict` — `None` is shorthand for "no context update".
8. `test_scout_act_runs_through_process_chain` — end-to-end: synthetic `===SCOUT_REPORT===` LLM output → executor runs all four handlers → report JSON written to tmp_path, digest in result, enrichment took effect.

Test count baseline 10950 (Wave 33) → expected 10958 (+8 exact).

## Build Quality Reminders (Wave 33 lessons applied)

- The four bound-method handlers MUST be defined as `async def _scout_step_*` on `ScoutAgent` — they are referenced by name from the chain construction in `act()`. Fail-fast at runtime if any are misnamed.
- `ProcessChainStep` is frozen; build the tuple inline in `act()` (handlers are bound methods on `self`, so the chain must be constructed per-invocation).
- The migration REMOVES the inline pipeline that previously sat between the early-return guard and the `digest = format_digest(...)` line. Section 2c in the prompt is explicit; the SEARCH/REPLACE in 2b is the early-portion-only swap, and the rest is deleted as part of the handler insertion described in 2c.
- Keep the existing `_deliver_discord` method intact — the new `_scout_step_notify_and_deliver` handler calls it.
- Existing Scout tests (`tests/test_scout.py`, `tests/test_bf208*`, `tests/test_bf209*`, `tests/test_bf214*`, `tests/test_bf225*`) MUST stay green — duty-path behavior is unchanged externally.

## Out of Scope (Hard Limits)

| Out | Where it lives next |
|---|---|
| BF-209 removal + base-class hook | AD-647b |
| Intent/duty → ProcessChainDefinition registry | AD-647b |
| LLM prompt-template handlers (`prompt_template_id`) | AD-647b |
| Bill-driven process chains (AD-618 integration) | AD-647c |
| Watch Bill / billet-based chain assignment (AD-595 integration) | AD-647c |
| NATS coupling (AD-641g subjects) | AD-647d |
| Parallel steps, conditional branching, rollback, retry | future |
| Chain-execution journal table + EventType emission | future |
| HXI process-chain visualization | future |
| New Pydantic config | future |

## Success Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta exactly +8 vs baseline 10950 → 10958.
3. Scout duty-triggered cycle still produces the same digest + report file as pre-AD-647 (regression-equivalence).
4. BF-209 opt-out unchanged at `scout.py:247`.
5. PROGRESS.md flipped from `AD-647 SCOPED` to `AD-647 v1 CLOSED`.
6. DECISIONS.md AD-647 entry appended with v1 line (no rewrite).
7. Issue #291 closed on merge.
