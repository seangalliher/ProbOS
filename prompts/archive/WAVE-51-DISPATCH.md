# WAVE 51 DISPATCH — AD-660b v1 Causal Reasoning Auto-Invocation + Emergence

**Wave id:** 51
**Single AD:** AD-660b
**Closes:** #411
**Baseline test count:** 11170 (Wave 50) → expected **11182** (+12)
**HEAD at draft:** `1d6b728`

## Summary

Captain has banked the AD-660b slot since Wave 32. v1 closes the three remaining gaps in the Causal Reasoning framework:

1. **Default-on flip + per-bucket sliding-window rate limiter** (`max_invocations_per_hour=5`, default bucket = `agent_id`).
2. **AD-557 emergence integration** — counselor hooks for `GROUPTHINK_WARNING` + `FRAGMENTATION_WARNING` invoke `CausalReasoner.analyze_groupthink` / `analyze_fragmentation`, both routed through dedicated rate-limit buckets `_emergence:groupthink` / `_emergence:fragmentation`.
3. **Hypothesis ranking + recommended-action surfacing** — two new fields on `CausalReasoningTemplate` (`ranked_hypotheses`, `recommended_actions`), both backed by a journal schema migration (`ALTER TABLE ADD COLUMN`).

Diagnostic-action **execution** is OUT of scope. v1 logs each action with `needs_sandbox=True` for human review or AD-456b sandboxed execution (Wave 55, not yet shipped). This is the legitimate boundary.

## Architect calls (Decision Log)

- **DLog #1 — bucket model.** Rate limiter is keyed on a `bucket: str` parameter on `analyze()`, defaulting to `agent_id`. Emergence convenience methods pass `bucket="_emergence:groupthink"` / `bucket="_emergence:fragmentation"`. This isolates ship-level emergence budget from per-agent self-monitoring budget — under tight defaults (5/hr) one agent's amber-zone bursts cannot starve emergence anomaly diagnosis.

- **DLog #2 — synthetic ship agent id.** Emergence triggers carry no agent identity. `_SHIP_EMERGENCE_AGENT_ID = "_ship_emergence"` is the synthetic id stamped on emergence templates so journal queries by `agent_id` filter them cleanly.

- **DLog #3 — frozen-dc field-order rule preserved.** Both new fields (`ranked_hypotheses`, `recommended_actions`) are appended last with `default_factory=list`. The pre-existing `source_event_ref: str | None = None` already established the trailing-defaulted-fields zone, so no field-order shuffle.

- **DLog #4 — journal schema migration is idempotent.** `ALTER TABLE ADD COLUMN` calls are wrapped in `try/except: pass`. SQLite raises `OperationalError` when the column already exists; that is the success signal on warm boot. Schema literal also extended so cold-boot DBs get the columns directly via `CREATE TABLE`.

- **DLog #5 — backward-compat break: AD-660 test #7.** `test_wirer_skips_when_config_disabled` asserts `sys_cfg.causal_reasoning.enabled is False  # default`. Captain explicitly asked to flip default to `True`, so Section 7 of the prompt UPDATES this test (constructs an explicitly-disabled config). All other AD-660 v1 tests are field-additive-compatible.

- **DLog #6 — novelty calc is best-effort.** `_gather_prior_hypothesis_tokens` reads from `runtime.cognitive_journal.get_recent_causal_templates` and falls back to `[]` on any failure. Empty journal → novelty 1.0 for every hypothesis. Cold-boot first invocation always scores at full novelty — that is correct behavior.

- **DLog #7 — `_check_rate_limit` records on success only.** When the budget is exhausted, the deque is NOT mutated. This guarantees the rejected timestamp does not extend the window past the natural expiry.

- **DLog #8 — `_jaccard` exported for testability.** Tokenizer + ranker are module-level helpers (under `_` prefix) so tests can call them directly without spinning up an LLM.

- **DLog #9 — emergence handlers stay log-then-causal.** The existing `_on_groupthink_warning` / `_on_fragmentation_warning` log lines are preserved verbatim (AD-557 + AD-583 escalation logic untouched). The AD-660b hook block is appended at the end, mirroring the AD-660 hook pattern in `_on_self_monitoring_concern`.

- **DLog #10 — `EMERGENCE_METRICS_UPDATED` snapshot event NOT hooked.** That event fires every dream cycle whether or not anything is wrong. Hooking it would burn the rate-limit budget every cycle and mask real anomalies. Only the *warning* events (`GROUPTHINK_WARNING`, `FRAGMENTATION_WARNING`), which fire conditionally on `dream_report.groupthink_risk` / `fragmentation_risk` flags, are wired.

- **DLog #11 — emergence event payload shapes confirmed at `dream_adapter.py:120-135`.** Groupthink: `{"redundancy_ratio": float}`. Fragmentation: `{"synergy_ratio": float, "pairs_analyzed": int}`. The synthesized triggers consume exactly these fields.

## Highest-risk constraints (re-read before each Section)

1. **Section 3 SEARCH/REPLACE in `causal_reasoning.py` is large** (~85-line method body). Keep the prompt's exact text — every existing line is preserved verbatim except the new bucket parameter, the rate-limit guard at the top, and the new ranking + recommended_actions wiring at the bottom.
2. **Section 6 has TWO replace blocks on the same `for key in (...)` loop.** The first is a no-op (search-and-replace identical text) used as a redundancy guard; the second extends the loop body with the new `for json_col, dest_key in (...)` block. If the Builder finds the no-op replace fails (already applied), skip to the second block.
3. **Test 11 (counselor hook smoke)** uses `Counselor.__new__(Counselor)` to bypass `__init__`. If that pattern fails (e.g., Counselor mandates state in `__init__`), fall back to the AD-660 v1 wirer pattern (real Counselor via `_wire_causal_reasoner`).
4. **Do NOT touch `dream_adapter.py`.** Emission path stays as-is. AD-660b is consumer-side only.
5. **Do NOT touch `EmergenceMetricsEvent` or any event dataclass.** Counselor consumes raw `data: dict` payloads — that is the existing AD-557 contract.
6. **Do NOT add diagnostic-action execution.** `recommended_actions` is a passive surface only.
7. **Field-order rule on frozen dc** — both new fields go at the END of `CausalReasoningTemplate`, after the existing `source_event_ref: str | None = None`. Non-defaulted fields must NOT be added.

## Phantom-API pre-check result

4 candidates flagged on the prompt body. ALL 4 are FPs from the same intra-prompt-introduction class as Waves 27-50:

- 1× `Counselor.__new__` — stdlib object-protocol (Test 11 bypass-init pattern; same FP class as Wave 34 `ScoutAgent.__new__`).
- 1× `class:SimpleNamespace` — stdlib `types.SimpleNamespace` test fixture (every wave).
- 2× `CausalReasoningTemplate.ranked_hypotheses` / `recommended_actions` (field_phantom — introduced by Section 1; same intra-prompt-introduction class as Wave 47/49 field_phantom FPs).

7 standard skips (`reasoner.analyze*` / `journal.record_causal_template` / `journal.get_recent_causal_templates` / `journal.start`/`stop` no_class_resolution — pattern_b_reassignment FPs introduced by `_make_runtime` / `journal = CognitiveJournal(...)` test-fixture variables).

**0 NEW phantoms.** Helper functions (`_check_rate_limit`, `_jaccard`, `_rank_hypotheses`, `_recommended_actions_from`, `_tokenize_for_novelty`, `_gather_prior_hypothesis_tokens`) and intra-prompt symbols (`max_invocations_per_hour` config field, `analyze_groupthink`/`analyze_fragmentation` methods) all resolved cleanly by the script.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11170 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `config.py` default flip + new field
2. Section 1 — template fields
3. Section 2 — module-level helpers + ctor extension
4. Section 3 — `analyze()` rewrite + emergence convenience methods
5. Section 4 — wirer kwarg pass-through
6. Section 5 — counselor groupthink + fragmentation hooks
7. Section 6 — journal schema + INSERT + decode-loop migration
8. Section 7 — existing AD-660 test update
9. Section 8 — new test file
10. Run focused gate first: `pytest tests/test_ad660b_causal_auto_emergence.py tests/test_ad660_causal_reasoning.py -v -n 0`
11. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- Phantom API surfaces during build that is NOT one of the 15 documented FPs.
- `analyze_concern` shape needs to change (it does NOT — it delegates to `analyze`, which now applies rate limit transparently).
- `Counselor` constructor mandates state that breaks the Test 11 `__new__` shortcut → use the wirer fallback documented inline.
- Schema migration `ALTER TABLE` raises an exception OTHER than "duplicate column" on warm boot. The blanket `try/except: pass` already absorbs this — but if the test DB is brand-new, the ALTER may raise on cold boot before the CREATE TABLE finishes. Fix: ensure ALTER runs AFTER `executescript(_SCHEMA_CAUSAL_TEMPLATES)` (already correct in Section 6).

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-660b CLOSED entry.
- `docs/development/roadmap.md` — AD-660 status update + AD-660b sub-entry.
- `DECISIONS.md` — prepend AD-660b entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#411** (expect EMU 403 same as Waves 31-50; Captain closes manually).

## Commit message

`AD-660b: Causal Reasoning auto-invocation + AD-557 emergence integration (+12 tests)`
