# BF-901 S2: the journal records what each call cost, where the count came from, and the model that answered

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21 (Amendment A1, after review round 1 of candidate r1; section 16)

**Status:** build-ready. **Part of #1575** (slice S2 of S1 to S3; S3, the doctor view, closes #1575 and is drafted later on the merged tree, because it reads this slice's schema). **Tier HIGH** (a schema change on `journal` and `chain_traces`, and the record sites of every one-shot and chain-step model call). **Base:** `origin/main` `8c8bc4415e6279a22ffe2151cbd6cbc81b993691` **plus BF-900 and BF-901 S1 applied**, in that order (`prompts/bf-900-dispatch-claim-keeps-the-park.md`, `prompts/bf-901-s1-shared-estimator-and-usage-presence.md`). **Batch:** item 3 of 3, one broad gate for the batch. **Source:** the Architect's consult of 2026-10-21 (13:58Z), re-verified (section 11).

**Tests:** the count is stated once, in section 6 (one new file; no existing test changes).

**Line endings:** every edited file's working copy is CRLF (`git ls-files --eol`: `i/lf w/crlf`). The SEARCH blocks are written with LF; match and write with the file's own line endings.

---

## 0. What this slice anchors on in S1 (and BF-900)

S2's source SEARCH blocks touch no file S1 or BF-900 edits except `cognitive_agent.py`, where BF-900 changed only `_handle_work_item_dispatch` (about line 2268-2310); S2's blocks there are at about 3660-3720 and 4484-4511 on the base and match the same text after BF-900. S2 **calls** these S1 symbols and **anchors its tracker blocks** on S1's entries:

| S1 symbol or text | Where S1 puts it | Where S2 uses it |
|---|---|---|
| `charge_completion(outbound, response) -> TokenCharge` | `src/probos/cognitive/token_accounting.py` (S1 section 7.1) | `cognitive_agent.py` one-shot record (section 7.6); the four handlers (7.7 to 7.10); tests |
| `TokenCharge.prompt_tokens`, `.completion_tokens`, `.total_tokens`, `.source` | same | same |
| `request_messages(request)` | same | same |
| `answered_model_name(response)` | same | same |
| `LLMResponse.usage_reported` | `src/probos/types.py` (S1 section 7.3) | S2's tests build responses with it |
| The PROGRESS head `**BF-901 S1 (2026-10-21), part of #1575 -- one owner for the token estimator, and usage presence at the transport.**` | `PROGRESS.md` line 3 after S1 | S2's PROGRESS SEARCH |
| The DECISIONS line `- *Reversal.* Revert the BF-901 S1 commit (and S2 first, which depends on it). Nothing persisted changes.` | S1's DECISIONS entry | S2's DECISIONS SEARCH |

S2 imports `token_accounting` **at the call sites** (inside the functions), not at module scope: the module imports `swe_harness.tool_call` (S1 section 7.1, "Import cycle"), and neither `cognitive_agent.py` nor the sub-task handlers import a `swe_harness` module at module scope today (`Grep "^from probos\.cognitive\.(swe_harness|agentic_dispatch)" src/probos/cognitive/` lists neither), so a module-scope import would add an edge whose closure this contract has not enumerated. `cognitive_agent.py` already imports at call sites (for example `:2179`, `:2235`, `:2302`).

## 1. Problem

On the vessel (#1575, read-only 2026-10-16) every real model call's journal row has `total_tokens = 0`, 1,272 rows have an empty `model`, and no row says whether a count was measured. The code shows why:

- **One-shot calls** (`cognitive_agent.py:4471` -> `:4487`) record `model=response.model` (the id **sent**, not the one that answered, `types.py:355-361`), the transport's raw counts (the proxy's zeros, which S1 now charges as estimates), and `cached=False` always (`:4500`), although a client cache replay returns `cached=True` carrying the original call's `tokens_used` (`llm_client.py:1526-1530`, `:2001-2010`). Once counts are real, a replay recorded as `cached=False` would be charged as spend: every reader filters `cached = 0` (`journal.py:831`, `:841`, `:872`, `:895`).
- **Chain steps** (`sub_task.py:657-669`) record `total_tokens` only, no `model=` (so the column's default `''`, `journal.py:28`, `:368`) and no prompt/completion split; `SubTaskResult` has no model field (`sub_task.py:85-97`). The timed-out attempt row (`:586-598`) has no model either. The trace (`:680-715`) has the split but no source.
- **Cache hits and procedural replays** (`cognitive_agent.py:3668`, `:3705`) make no model call and record no model.
- Neither table has a column for the source.

The 1,272 empty-model rows fit the chain-step sites: 2,076 chain steps against 1,272 rows, because QUERY steps get a trace but no journal row (`sub_task.py:654`). Confirming the count needs one query on a copy of the vessel's journal (section 13).

## 2. Solution overview

- **Schema.** `token_source TEXT NOT NULL DEFAULT ''` on `journal` and `chain_traces`: in the `CREATE TABLE` for a new database, and an idempotent `ALTER TABLE` for an existing one (the AD-432 list for `journal`, `journal.py:201-211`; a BF-901 tuple and loop for `chain_traces`, beside AD-658a's, `:122-125`, `:227-232`). `''` means nothing was accounted for (an attempt, a cache hit, a replay, an error) or the row predates BF-901; no code labels it measured.
- **Records.** `record()` and `record_chain_trace()` write the column. `SubTaskResult` gains `model`, `token_source` and `cached` (A1); `ChainExecutionTrace` gains `token_source`.
- **Sites.** The four sub-task handlers charge each completed call with S1's `charge_completion` and set `model` from `answered_model_name`. `sub_task.py:657` passes the handler's charge, split and source, with `model` or `"unknown"`, and the result's `cached` (A1, section 7.10a); `:586` records `"unknown"`; the trace passes the source. `cognitive_agent.py:4487` records the charge, the answering model and `cached=response.cached is True`; `:3668` and `:3705` record `"unknown"`.

Where this contract departs from the consult, and why:

1. **`ChainExecutionTrace` gains `token_source` only, not `model`.** `chain_traces` has no model column (S2 adds `token_source` only, consult decision 6), and the journal is the trace's only reader (`Grep "ChainExecutionTrace" src/probos/` -> `journal.py:417`, `sub_task.py:679-680`, a docstring at `chain_optimizer.py:3`), so a `model` field on the trace would be written nowhere. The step's journal row (same `dag_node_id` prefix `st:{chain_id}:{step_index}:`) names the model.
2. **`cached=response.cached is True`**, not `bool(response.cached)`: `LLMResponse.cached` is a `bool`, so the two agree on it; a `MagicMock` response double (for example `test_ad632a_sub_task_foundation.py:625-634`) makes `bool(...)` true and would mark the double's row cached.
3. **The chain-step journal row also gains the prompt/completion split** (`prompt_tokens`, `completion_tokens` from the handler's charge). #1575's acceptance asks every real call to record all three counts; the trace already carried the split, the row did not.
4. **The analyze handler's parse-failure result is charged too** (`analyze.py:651-662`): the model answered and the call was spent; only the reply's shape failed.
5. **(A1) A chain step that replays the client cache is recorded `cached`.** Review round 1 (F1) found the one-shot rule (D4) applied to one path only: the chain-step result carried no flag, so the step row took `record()`'s default `False`, and a replay of a zero-count proxy answer, which S1 charges as an estimate, entered every reader's sum and the AD-617b cap. A1 carries the flag (D9, section 7.10a).

## 3. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | Additive `token_source TEXT NOT NULL DEFAULT ''` on both tables, idempotent `ALTER` (consult decision 6; not a Captain condition, `orchestrator.agent.md:118`: no schema breaks) | A new table: two joins for every reader, and S3 would read both. `NULL` default: S3 and every reader would need a third state beside `''` |
| D2 | `''` means "nothing accounted for, or before BF-901"; only `charge_completion`'s measured branch writes `"measured"` | Back-filling old rows as measured: they were recorded from the proxy's zeros |
| D3 | The one-shot site records `answered_model_name(response)`: answered, else sent, else `"unknown"` | `response.model` (the sent id; the defect) |
| D4 | `cached=response.cached is True` | `cached=False` (replays would be charged); `bool(response.cached)` (D2 of section 2) |
| D5 | Cache-hit, procedural-replay and timed-out-attempt rows record `model="unknown"` and `token_source=''` | Leaving `''`: #1575 forbids an empty model |
| D6 | Handlers charge at every result built from a completed call, so the chain-step row carries measured or estimated counts and the answering model | Charging at `sub_task.py:657`: the executor has no request and no response, only the handler's result |
| D7 | Call-site imports of `token_accounting` | A module-scope import (section 0) |
| D8 | The chain-step row and the trace read the new `SubTaskResult` fields with `getattr`, as the trace already reads the split (`sub_task.py:694-698`, AD-658a) | Direct attributes: a handler registered by a test that returns a result object without the fields would lose its row (the `except` at `:670-674` logs at debug) |
| D9 (A1) | Each of the six results built from a completed call (the analyze parse-failure and evaluate default-verdict results included) carries `cached=getattr(response, "cached", False) is True`; the step row records `getattr(result, "cached", False) is True` (D8); the charge and its source stay on the row, as on the one-shot row (D4), and the readers' `cached = 0` filter keeps it out of spend | Zeroing a replay's charge: the row would no longer say what the replayed answer cost, and the one-shot row keeps it. `bool(...)`: D4. A `cached` column on `chain_traces`: a schema change, and no reader sums trace tokens as spend (section 5) |

## 4. Milestones (about 50 Builder tool calls in all)

| M | Work | Focused check (`-n 0`, the orchestrator's worktree environment: `PYTHONPATH=<tree>/src`) |
|---|---|---|
| M1 (about 10 calls) | Sections 7.1 (`journal.py`) and 7.2 (`chain_trace.py`) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_journal.py tests/test_ad658a_chain_trace_token_split.py tests/test_ad658_chain_harness_metrics.py tests/test_ad700b_journal_level_tag.py tests/test_ad492_cognitive_correlation_ids.py tests/test_replay_dispatch.py tests/test_ad617b_per_agent_token_budget.py tests/test_ad469_eps.py -n 0 -q` |
| M2 (about 8 calls) | Sections 7.3 to 7.5 (`sub_task.py`) and 7.6 (`cognitive_agent.py`) | M1's command, then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad632a_sub_task_foundation.py tests/test_bf864_decision_cache_key.py tests/test_cognitive_agent.py tests/test_ad643a_intent_routing.py tests/test_ad1248_slice_a_crossing.py -n 0 -q` |
| M3 (about 13 calls) | Sections 7.7 to 7.10 (the four handlers), then 7.10a (A1: the replay flag in `sub_task.py` and the handlers) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf183_subtask_retry.py tests/test_ad632h_parallel_dispatch.py tests/test_ad632a_sub_task_foundation.py tests/test_ad632c_analyze_handler.py tests/test_ad632d_compose_handler.py tests/test_ad632e_evaluate_reflect.py tests/test_ad639_chain_tuning.py tests/test_bf184_evaluate_social_bypass.py tests/test_bf185_reflect_social_bypass.py tests/test_bf186_compose_standing_orders.py tests/test_bf187_bf188_dm_captain_delivery.py tests/test_bf190_bf191_route_evaluate.py tests/test_bf204_grounding.py tests/test_bf233_grounding_false_positives.py tests/test_ad645b_evaluate_brief_alignment.py tests/test_bf288_log_hygiene.py tests/test_ad632b_query_handler.py -n 0 -q` |
| M4 (about 12 calls) | Section 7.11 (the new test file) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf901_s2_journal_token_provenance.py tests/test_bf901_s1_token_accounting.py -n 0 -q`, then M1 to M3 again, then `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_seam_registry.py tests/test_layer_boundaries.py tests/test_ad661_diagnostic_context.py -n 0 -q` |
| M5 (about 6 calls) | Section 8: `PROGRESS.md`, `DECISIONS.md`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` | `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -n 0 -q` |
| M6 (about 4 calls) | Section audit; stage by explicit path: `src/probos/cognitive/journal.py`, `src/probos/cognitive/chain_trace.py`, `src/probos/cognitive/sub_task.py`, `src/probos/cognitive/cognitive_agent.py`, `src/probos/cognitive/sub_tasks/analyze.py`, `src/probos/cognitive/sub_tasks/compose.py`, `src/probos/cognitive/sub_tasks/evaluate.py`, `src/probos/cognitive/sub_tasks/reflect.py`, `tests/test_bf901_s2_journal_token_provenance.py`, `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` (never `git add -A`) | `git diff --cached --stat` |

Then the orchestrator: the scratch-tree dry run (on the tree with BF-900 and S1 applied), the mutation rows (section 10), review, the local commit, then the batch's one receipted broad gate.

## 5. Consumers of every value this changes

Greps: `Grep "journal\.record\(|\.record_chain_trace\(" src/probos/`; `Grep "INTO journal|INTO chain_traces|FROM journal|FROM chain_traces" src/probos/`; `Grep "\.(get_reasoning_chain|recent_for_agent|get_decision_points|get_recent_chain_traces|get_token_usage_by|get_token_usage_since|get_token_usage)\(" src/probos/`; `Grep "\.tokens_used\b" src/probos/cognitive/`; `Grep "ChainExecutionTrace" src/probos/`; `Grep "SUB_TASK_CHAIN_COMPLETED|sub_task_chain_completed" src/probos/ ui/src/`; `Grep "api/journal|chain-traces|/reasoning" ui/src/`.

**Scope (A1, review round 1 F4).** This section lists the writers, the direct readers of the two tables and of the changed values, and each reader's first caller; it is not a census of every transitive consumer. Round 1 found further ones, all compatible (they forward rows or read named keys; none reads a token field or the key set): `query_agent_chain_traces` (`clinical_telemetry.py:149`) forwards `get_recent_chain_traces` rows to `routers/clinical.py:97`, to the CLI panel `render_clinical_traces_panel` (`experience/panels.py:1360`, which reads `ts`, `chain_id`, `outcome` and steps) and to the proactive self-monitoring summary (`proactive.py:2425-2436`: count, `ts`, `outcome`); `routers/diagnostic_context.py:47` serialises the diagnostic bundle (`bundle.to_dict()`), whose chain rows carry the new key.

**Writers.** The five `journal.record` sites and one `record_chain_trace` site above are the only writers (`cognitive_agent.py:3668`, `:3705`, `:4487`; `sub_task.py:586`, `:657`, `:715`); every SQL statement on the two tables is in `journal.py`.

| Value | Consumer | What it does with the new value | Base or added |
|---|---|---|---|
| `journal.total_tokens` / `prompt_tokens` / `completion_tokens` now the charge (measured or estimated) on one-shot and chain-step rows | `get_token_usage` (`journal.py:817-855`), `get_token_usage_by` (`:881-926`), `routers/journal.py:25-44` | Sums become non-zero where the proxy reported zeros; the shape is unchanged | Added |
| | AD-617b hourly cap, `proactive.py:809`, `:824` (`get_token_usage_since`) | Reads the new sums; inert while `per_agent_hourly_token_cap` is 0 (`config_models/knowledge.py:253`; `config/system.yaml:2067` sets 0). Its policy is unchanged | Added input; policy unchanged |
| | EPS capacity report, `eps/capacity.py:75-77` | A report; per-model groups now show the answering model or `unknown` instead of `''` | Added |
| `journal.cached = 1` for a client cache replay | The four readers' `cached = 0` filter (`journal.py:831`, `:841`, `:872`, `:895`) | A replay is excluded from spend (U4) | Added |
| `journal.model` never `''` from the five sites | `get_token_usage_by(group_by="model")` and the EPS report | Groups by real names and `unknown` | Added (rows written before BF-901 keep `''`) |
| New column `token_source` in `SELECT *` rows | `get_reasoning_chain` (`journal.py:790`) -> `routers/agents.py:3895-3898`; `get_decision_points` (`:956`) -> `routers/journal.py:58-64` | One more key in each JSON entry; no UI caller (`Grep "api/journal|chain-traces|/reasoning" ui/src/` finds nothing) | Added |
| | `get_recent_chain_traces` (`:486`) -> `chain_optimizer.py:264`, `clinical_telemetry.py:196`, `optimization_counselor.py:194`, `routers/chain_traces.py:33-38`, `diagnostic_context.py:257` | The first three read no token field (`Grep "tokens" ` in each finds none relevant); the route passes rows through; `diagnostic_context._row_tokens` (`:431-433`) estimates a row's size from its serialised values, so each chain row costs a few more characters (`"estimated"` is 9) against its 8,000-token default budget (`:108`) | Added |
| `SubTaskResult.tokens_used` now the charge | `sub_task.py:385` (sum into the `SUB_TASK_CHAIN_COMPLETED` event): no listener subscribes (`Grep` finds the emitter, `events.py:436`, `:1117` and the persistence list `event_persistence.py:411` only); `chain_nats_bridge.py:192` (the NATS step payload, observability) | Non-zero where the proxy reported zeros | Added |
| `SubTaskResult.model`, `.token_source` (new, defaulted) | `sub_task.py:657` row and the trace | Section 7.4, 7.5 | Added |
| `SubTaskResult.cached` (new, defaulted `False`; A1) | The step row (`sub_task.py:657`), then the four readers' `cached = 0` filter and the AD-617b cap (`proactive.py:824`) | A replayed step is excluded from spend, as a one-shot replay is (U11) | Added |
| | AD-633's speculative budget: `_sum_tokens` (`predictive_branching/executor.py:195-199`) -> `record_consumption` (`:102-105`) | Sums every result's `tokens_used`, a replay's included; reads no `cached`. Off by default (`config_models/knowledge.py:422`; `config/system.yaml:1986`). Recorded, not repaired (a reader change; section 16) | Base behaviour; S1's estimate widens it |
| | `chain_nats_bridge.py:183-194` (the NATS step payload) | Reads named fields, `cached` not among them | Unchanged |
| A replayed step's `chain_traces` row (no `cached` column) | The trace readers above | They read no token field; S3 takes spend from `journal` (section 13) | Unchanged |
| `ChainExecutionTrace.token_source` (new) | `record_chain_trace` | Section 7.1 | Added |
| `record(token_source=...)` (new keyword, defaulted `""`) | The five sites | Two pass it (`:4487`, `:657`), three keep `''` | Added |
| Schema pins in tests | `test_ad492_cognitive_correlation_ids.py:166-168`, `test_ad658a_chain_trace_token_split.py:139-142`, `:173-176`, `test_ad700b_journal_level_tag.py:113-116`, `:124-128`, `test_replay_dispatch.py:159-161` | Each asserts a named column is present (or present once); none asserts the full column set | Unchanged |

Pre-existing on the base and recorded, not repaired here: a warm-boot `ALTER` that fails for a reason other than "column exists" is swallowed (the AD-432 and AD-658a loops' precedent), after which every insert into that table fails at debug level (`journal.py:411-412`, `:455-456`); `MockLLMClient` rows are charged as measured (S1 section 8, considered, deferred); the model calls that write no journal row (about 48 files) stay unrecorded (consult decision 4).

## 6. Tests

All in `tests/test_bf901_s2_journal_token_provenance.py`: **26 test cases in 12 test functions**. Every test but U9 and U12 goes through a real `CognitiveJournal` on `tmp_path`; U9 and U12 test the handlers' returned results, and U11 carries a replayed step from the handler through the journal to the usage readers and the AD-617b gate.

| ID | Test | What it proves |
|---|---|---|
| U1 | `test_a_one_shot_call_records_an_estimate_where_the_provider_reported_zeros` | `CognitiveAgent.decide` -> `_decide_via_llm` -> `journal.record`: the proxy's shape (usage reported, zeros, content) records `token_source="estimated"`, `completion_tokens` = the reply's `len // 4`, `prompt_tokens` = the request's `len // 4` per message, their sum as the total, the answering model, `cached=0` |
| U2 | `test_a_one_shot_call_records_measured_counts` | Reported counts are recorded as reported, `token_source="measured"` |
| U3 | `test_a_one_shot_row_names_the_model_that_answered[answered|sent|error]` | `answered_model` wins; the sent id when none answered; `"unknown"` (and `''` source, `success=0`) for an error response |
| U4 | `test_a_replay_row_is_cached_and_adds_nothing_to_token_usage` | A client cache replay is recorded `cached=1` and `get_token_usage` stays 0; a following real call is counted |
| U5 | `test_a_decision_cache_hit_row_names_unknown` | `:3668` |
| U6 | `test_a_procedural_replay_row_names_unknown` | `:3705` |
| U7 | `test_a_chain_step_records_the_handler_charge_and_model` | `SubTaskExecutor` + the real `ComposeHandler` + the real journal: the step row has the split, the estimate, the source and the answering model; the trace row has the same source and total |
| U8 | `test_a_timed_out_attempt_and_its_retry_name_unknown` | `:586` (the attempt row) and `:657` with a result that names no model: both rows say `"unknown"` |
| U9 | `test_each_handler_charges_its_call[analyze|compose|evaluate|reflect]-[estimated|measured]` (8) | Each handler's success result carries the charge, the source and the answering model, and a fresh call's result is not marked `cached` (A1) |
| U10 | `test_a_warm_boot_adds_the_columns_once_and_old_rows_read_empty` | On a database with the pre-BF-901 schema: `start()` adds `token_source` to both tables once, old rows read `''`, new rows write the source, and a second start changes nothing |
| U11 | `test_a_replayed_chain_step_is_journaled_cached_and_adds_nothing_to_spend` | (A1, F1) A client cache replay of a zero-count answer, built as `llm_client.py`'s replay paths build it, through the real `ComposeHandler`, `SubTaskExecutor` and journal: the row is estimated, non-zero and `cached=1`; `get_token_usage`, `get_token_usage_by(group_by="model")`, `get_token_usage_since` and the real AD-617b gate (`_is_over_token_budget`, a 1-token cap) leave it out; a fresh step that follows is counted by all four. On r1 it fails at `assert replay_row["cached"] == 1` |
| U12 | `test_each_completed_result_carries_the_replay_flag[analyze-parsed|analyze-parse-failure|compose|evaluate-verdict|evaluate-default|reflect]` (6) | (A1) Every result built from a completed call, the parse-failure and default-verdict results included, carries a replay's `cached` beside its estimated charge and the answering model; a premise pins the branch each case names |

Consumer tests run unchanged (M1 to M4): the journal suites (`test_cognitive_journal.py`, including test 9's `cached is False` and test 10's cache-hit row), `test_ad658a_chain_trace_token_split.py`, `test_ad658_chain_harness_metrics.py`, `test_ad700b_journal_level_tag.py`, `test_ad492_cognitive_correlation_ids.py`, `test_replay_dispatch.py`, `test_ad617b_per_agent_token_budget.py`, `test_ad469_eps.py`, `test_ad661_diagnostic_context.py`; the handler suites (M3; their LLM doubles report counts, which a not-stated presence keeps as measured, S1 D3; their `tokens_used == 0` assertions are on bypass paths that make no call); `test_ad632a_sub_task_foundation.py`, `test_bf864_decision_cache_key.py`, `test_cognitive_agent.py`, `test_ad643a_intent_routing.py`, `test_ad1248_slice_a_crossing.py` (source scans of `decide`/`_decide_via_llm` whose strings this contract keeps), `test_bf288_log_hygiene.py` (pins three strings in `AnalyzeHandler.__call__`, kept), `test_ad1343_seam_registry.py`, `test_layer_boundaries.py`.

**Platform.** Every test runs on SQLite files in `tmp_path` and in-memory doubles; U8 replaces `asyncio.sleep` for its duration so BF-183's fixed 2 s back-off does not run (the step timeout is 50 ms and the handler's first call waits on an event that is never set, so the timeout fires on any host). Nothing depends on the platform: the outcome cannot differ on POSIX.

## 7. The contract

### 7.1 `src/probos/cognitive/journal.py`

SEARCH:
```python
    level            TEXT NOT NULL DEFAULT '',
    level_rank       INTEGER NOT NULL DEFAULT 0
);
```
REPLACE:
```python
    level            TEXT NOT NULL DEFAULT '',
    level_rank       INTEGER NOT NULL DEFAULT 0,
    token_source     TEXT NOT NULL DEFAULT ''
);
```

SEARCH:
```python
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    success             INTEGER NOT NULL DEFAULT 1,
```
REPLACE:
```python
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    token_source        TEXT NOT NULL DEFAULT '',
    success             INTEGER NOT NULL DEFAULT 1,
```

SEARCH:
```python
_MIGRATIONS_CHAIN_TRACES_AD658A = (
    "ALTER TABLE chain_traces ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chain_traces ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
)
```
REPLACE:
```python
_MIGRATIONS_CHAIN_TRACES_AD658A = (
    "ALTER TABLE chain_traces ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chain_traces ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0",
)

# BF-901: idempotent migration for warm-boot DBs created before BF-901. ``''`` means nothing was accounted
# for (an attempt, a cache hit, a replay, an error) or the row predates BF-901; it is never read as measured.
_MIGRATIONS_CHAIN_TRACES_BF901 = (
    "ALTER TABLE chain_traces ADD COLUMN token_source TEXT NOT NULL DEFAULT ''",
)
```

SEARCH:
```python
            ("correlation_id", "TEXT NOT NULL DEFAULT ''"),  # AD-492: cognitive correlation ID
        ]:
```
REPLACE:
```python
            ("correlation_id", "TEXT NOT NULL DEFAULT ''"),  # AD-492: cognitive correlation ID
            ("token_source", "TEXT NOT NULL DEFAULT ''"),  # BF-901: measured, estimated or '' (none)
        ]:
```

SEARCH:
```python
        # AD-658a: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-658a.
        for stmt in _MIGRATIONS_CHAIN_TRACES_AD658A:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
```
REPLACE:
```python
        # AD-658a: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-658a.
        for stmt in _MIGRATIONS_CHAIN_TRACES_AD658A:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        # BF-901: the token source column, for warm-boot DBs that pre-date BF-901.
        for stmt in _MIGRATIONS_CHAIN_TRACES_BF901:
            try:
                await self._db.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
```

SEARCH:
```python
        level_rank: int = 0,  # AD-700b: ordinal 1..5; 0 for non-diagnostic intents
    ) -> None:
        """Append a journal entry. Fire-and-forget — never raises."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO journal
                   (id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, success, cached, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id, level, level_rank)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id, level, level_rank,
                ),
            )
```
REPLACE:
```python
        level_rank: int = 0,  # AD-700b: ordinal 1..5; 0 for non-diagnostic intents
        token_source: str = "",  # BF-901: "measured", "estimated" or "" (nothing accounted for)
    ) -> None:
        """Append a journal entry. Fire-and-forget — never raises."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT OR IGNORE INTO journal
                   (id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, success, cached, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id, level, level_rank, token_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id, timestamp, agent_id, agent_type, tier, model,
                    prompt_tokens, completion_tokens, total_tokens,
                    latency_ms, intent, 1 if success else 0,
                    1 if cached else 0, request_id,
                    prompt_hash, response_length,
                    intent_id, dag_node_id, response_hash, procedure_id,
                    correlation_id, level, level_rank, token_source,
                ),
            )
```

SEARCH:
```python
                    started_at, duration_ms, tokens_used,
                    prompt_tokens, completion_tokens,
                    success, error_truncated,
                    context_keys_declared, context_keys_passed, context_filter_applied,
                    communication_context, chain_trust_band, trust_score,
                    boot_camp_active, from_captain, is_dm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.chain_id, trace.step_index, trace.step_name,
                    trace.sub_task_type, trace.tier, trace.chain_source,
                    trace.agent_id, trace.agent_type, trace.intent, trace.intent_id,
                    trace.started_at, trace.duration_ms, trace.tokens_used,
                    # AD-658a: defensive getattr — tolerates pre-AD-658a trace objects
                    # produced by external test fixtures or stub journals.
                    getattr(trace, "prompt_tokens", 0),
                    getattr(trace, "completion_tokens", 0),
```
REPLACE:
```python
                    started_at, duration_ms, tokens_used,
                    prompt_tokens, completion_tokens, token_source,
                    success, error_truncated,
                    context_keys_declared, context_keys_passed, context_filter_applied,
                    communication_context, chain_trust_band, trust_score,
                    boot_camp_active, from_captain, is_dm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace.chain_id, trace.step_index, trace.step_name,
                    trace.sub_task_type, trace.tier, trace.chain_source,
                    trace.agent_id, trace.agent_type, trace.intent, trace.intent_id,
                    trace.started_at, trace.duration_ms, trace.tokens_used,
                    # AD-658a: defensive getattr — tolerates pre-AD-658a trace objects
                    # produced by external test fixtures or stub journals.
                    getattr(trace, "prompt_tokens", 0),
                    getattr(trace, "completion_tokens", 0),
                    # BF-901: the same tolerance for objects that pre-date the source field.
                    getattr(trace, "token_source", ""),
```

**Warm boot, with and without the columns.** Without them (any database created before BF-901): `CREATE TABLE IF NOT EXISTS` leaves the tables as they are, the `ALTER`s add `token_source` with its default, so every existing row reads `''`, and the indexes are unaffected (none names the column). With them (a database created after BF-901, or a second start): the `ALTER`s raise `sqlite3.OperationalError` (duplicate column) and are skipped. The `journal` `ALTER` runs in the AD-432 loop, before AD-700b's `level` columns, so on a warm database the new column's ordinal position differs from a fresh one; every statement names its columns (the `INSERT`s) or reads by name (`dict(row)`), so the position is not read anywhere.

### 7.2 `src/probos/cognitive/chain_trace.py`

SEARCH:
```python
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
    success: bool = True
```
REPLACE:
```python
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
    token_source: str = ""              # BF-901: "measured", "estimated" or "" (nothing accounted for)
    success: bool = True
```

### 7.3 `src/probos/cognitive/sub_task.py`: `SubTaskResult`

SEARCH:
```python
    tier_used: str = ""                 # Actual LLM tier used
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
```
REPLACE:
```python
    tier_used: str = ""                 # Actual LLM tier used
    prompt_tokens: int = 0              # AD-658a: prompt-side token count
    completion_tokens: int = 0          # AD-658a: completion-side token count
    model: str = ""                     # BF-901: the model that answered ("" = none named; the row says "unknown")
    token_source: str = ""              # BF-901: "measured", "estimated" or "" (nothing accounted for)
```

### 7.4 `src/probos/cognitive/sub_task.py`: the timed-out attempt row

SEARCH:
```python
                            tier=spec.tier,
                            total_tokens=0,
                            latency_ms=spec.timeout_ms,
```
REPLACE:
```python
                            tier=spec.tier,
                            model="unknown",  # BF-901: an abandoned attempt names no answering model
                            total_tokens=0,
                            latency_ms=spec.timeout_ms,
```

### 7.5 `src/probos/cognitive/sub_task.py`: the step row and the trace

SEARCH:
```python
                    tier=result.tier_used or spec.tier,
                    total_tokens=result.tokens_used,
                    latency_ms=result.duration_ms,
                    intent=intent,
                    intent_id=intent_id,
                    success=result.success,
                    dag_node_id=dag_node_id,
                )
```
REPLACE:
```python
                    tier=result.tier_used or spec.tier,
                    # BF-901: the handler's charge and the model that answered, read with getattr as the
                    # trace below reads the split (AD-658a).
                    model=getattr(result, "model", "") or "unknown",
                    prompt_tokens=getattr(result, "prompt_tokens", 0),
                    completion_tokens=getattr(result, "completion_tokens", 0),
                    total_tokens=result.tokens_used,
                    latency_ms=result.duration_ms,
                    intent=intent,
                    intent_id=intent_id,
                    success=result.success,
                    dag_node_id=dag_node_id,
                    token_source=getattr(result, "token_source", ""),  # BF-901: as the handler charged it
                )
```

SEARCH:
```python
                    prompt_tokens=getattr(result, "prompt_tokens", 0),
                    completion_tokens=getattr(result, "completion_tokens", 0),
                    success=result.success,
                    error_truncated=(result.error or "")[:200],
```
REPLACE:
```python
                    prompt_tokens=getattr(result, "prompt_tokens", 0),
                    completion_tokens=getattr(result, "completion_tokens", 0),
                    token_source=getattr(result, "token_source", ""),  # BF-901: the step row's source
                    success=result.success,
                    error_truncated=(result.error or "")[:200],
```

(The second SEARCH is unique after the first is applied: the step row's split is followed by `total_tokens=`, the trace's by `success=result.success,` and `error_truncated=`.)

### 7.6 `src/probos/cognitive/cognitive_agent.py`

SEARCH:
```python
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            cached=True,
                            correlation_id=observation.get("correlation_id", ""),
```
REPLACE:
```python
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            model="unknown",  # BF-901: a decision-cache hit makes no model call
                            cached=True,
                            correlation_id=observation.get("correlation_id", ""),
```

SEARCH:
```python
                        cached=True,
                        total_tokens=0,
                        procedure_id=procedural_result.get("procedure_id", ""),
```
REPLACE:
```python
                        model="unknown",  # BF-901: a procedural replay makes no model call
                        cached=True,
                        total_tokens=0,
                        procedure_id=procedural_result.get("procedure_id", ""),
```

SEARCH:
```python
                _prompt_hash = hashlib.md5(user_message[:500].encode()).hexdigest()[:12]
                await self._cognitive_journal.record(
                    entry_id=request.id,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    tier=response.tier,
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.tokens_used,
                    latency_ms=_latency_ms,
                    intent=observation.get("intent", ""),
                    success=response.error is None,
                    cached=False,
                    request_id=request.id,
```
REPLACE:
```python
                _prompt_hash = hashlib.md5(user_message[:500].encode()).hexdigest()[:12]
                # BF-901 (#1575): the call's charge (measured, or estimated where the provider reported
                # no usable count), the model that answered, and a client cache replay recorded as one,
                # so the readers' ``cached = 0`` filter keeps it out of spend.
                from probos.cognitive.token_accounting import (
                    answered_model_name,
                    charge_completion,
                    request_messages,
                )

                _charge = charge_completion(request_messages(request), response)
                await self._cognitive_journal.record(
                    entry_id=request.id,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    tier=response.tier,
                    model=answered_model_name(response),
                    prompt_tokens=_charge.prompt_tokens,
                    completion_tokens=_charge.completion_tokens,
                    total_tokens=_charge.total_tokens,
                    latency_ms=_latency_ms,
                    intent=observation.get("intent", ""),
                    success=response.error is None,
                    cached=response.cached is True,
                    request_id=request.id,
                    token_source=_charge.source,
```

**What the `try` covers** (`cognitive_agent.py:4485-4511`). On the base: the prompt hash and the `record` call (with its argument reads). Here: the same, plus the call-site import, `request_messages`, `charge_completion` and `answered_model_name`. Its arm (`except Exception: logger.debug(...)`) is unchanged and catches any of them: a fault in the charge loses that row, as a fault in `record` does today; `decision` (built before the `try`, `:4477-4481`) is unaffected.

### 7.7 `src/probos/cognitive/sub_tasks/analyze.py`

SEARCH:
```python
        # Parse structured JSON from response
        try:
            analysis = extract_json(response.content)
```
REPLACE:
```python
        # BF-901 (#1575): what this call is charged (measured, or estimated where the provider reported no
        # usable count) and the model that answered; both results below carry them.
        from probos.cognitive.token_accounting import (
            answered_model_name,
            charge_completion,
            request_messages,
        )

        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse structured JSON from response
        try:
            analysis = extract_json(response.content)
```

SEARCH:
```python
                result={},
                tokens_used=response.tokens_used,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                duration_ms=duration,
                success=False,
                error=error_msg,
                tier_used=response.tier,
            )
```
REPLACE:
```python
                result={},
                tokens_used=charge.total_tokens,
                prompt_tokens=charge.prompt_tokens,
                completion_tokens=charge.completion_tokens,
                duration_ms=duration,
                success=False,
                error=error_msg,
                tier_used=response.tier,
                model=answered,
                token_source=charge.source,
            )
```

SEARCH:
```python
            result=analysis,
            tokens_used=response.tokens_used,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```
REPLACE:
```python
            result=analysis,
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
        )
```

The error-response result (`analyze.py:610-623`, `response.error` set) is unchanged: it carries the transport's zeros and no model, and `sub_task.py` records it as `"unknown"`. `test_bf288_log_hygiene.py:104-124` pins `"LLM returned empty content"`, `"if not content.strip():"` and `"JSON parse failure, content: %s"` in `AnalyzeHandler.__call__`; all three stay.

### 7.8 `src/probos/cognitive/sub_tasks/compose.py`

SEARCH:
```python
        # Return composed output
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name=spec.name,
            result={"output": response.content or ""},
            tokens_used=response.tokens_used,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
        )
```
REPLACE:
```python
        # BF-901 (#1575): what this call is charged and the model that answered.
        from probos.cognitive.token_accounting import (
            answered_model_name,
            charge_completion,
            request_messages,
        )

        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Return composed output
        duration = (time.monotonic() - start) * 1000
        return SubTaskResult(
            sub_task_type=SubTaskType.COMPOSE,
            name=spec.name,
            result={"output": response.content or ""},
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
        )
```

### 7.9 `src/probos/cognitive/sub_tasks/evaluate.py`

SEARCH:
```python
        duration = int((time.monotonic() - start) * 1000)

        # Parse structured verdict
```
REPLACE:
```python
        duration = int((time.monotonic() - start) * 1000)

        # BF-901 (#1575): what this call is charged and the model that answered; both results below carry them.
        from probos.cognitive.token_accounting import (
            answered_model_name,
            charge_completion,
            request_messages,
        )

        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse structured verdict
```

SEARCH:
```python
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=getattr(response, "tokens_used", 0),
                prompt_tokens=getattr(response, "prompt_tokens", 0),
                completion_tokens=getattr(response, "completion_tokens", 0),
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
            )
```
REPLACE:
```python
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=charge.total_tokens,
                prompt_tokens=charge.prompt_tokens,
                completion_tokens=charge.completion_tokens,
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
                model=answered,
                token_source=charge.source,
            )
```

SEARCH:
```python
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            prompt_tokens=getattr(response, "prompt_tokens", 0),
            completion_tokens=getattr(response, "completion_tokens", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```
REPLACE:
```python
            result=result,
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
        )
```

`request` is bound: it is assigned inside the `try` before `complete` (`evaluate.py:636-645`), and the `except` returns (`:646-661`).

### 7.10 `src/probos/cognitive/sub_tasks/reflect.py`

SEARCH:
```python
        duration = int((time.monotonic() - start) * 1000)

        # Parse response
        content = getattr(response, "content", "") or ""
```
REPLACE:
```python
        duration = int((time.monotonic() - start) * 1000)

        # BF-901 (#1575): what this call is charged and the model that answered.
        from probos.cognitive.token_accounting import (
            answered_model_name,
            charge_completion,
            request_messages,
        )

        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse response
        content = getattr(response, "content", "") or ""
```

SEARCH:
```python
            result=result,
            tokens_used=getattr(response, "tokens_used", 0),
            prompt_tokens=getattr(response, "prompt_tokens", 0),
            completion_tokens=getattr(response, "completion_tokens", 0),
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
        )
```
REPLACE:
```python
            result=result,
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
        )
```

(`request` is bound as in evaluate: `reflect.py:514-523`, the `except` returns at `:524-540`.)

**Handler doubles.** The handlers' tests hand them `LLMResponse` objects with counts, `MagicMock` responses (`test_ad632d_compose_handler.py:58-62`) and `AsyncMock` clients. S1's `charge_completion` reads all of them without raising and keeps a reported count (an `int` `tokens_used` with presence not stated) as measured (S1 D3, D6, its C1 `mock_double` and `unstated_counts` rows), so `result.tokens_used` assertions such as `test_ad632d...:342` (`== 123`) and `test_ad632e...:288` (`== 42`) hold.

### 7.10a The replay flag (Amendment A1): `sub_task.py` and the four handlers

Apply after 7.1 to 7.10: each SEARCH below is the text those sections leave and occurs once in its file. Review round 1 (F1): a chain step's result carried no flag, so the step row took `record()`'s default `cached=False`, and a client cache replay (`llm_client.py:1526-1530`, `:2001-2010`) of a zero-count proxy answer, which S1 charges as an estimate, entered the readers' sums and the AD-617b cap. Each of the six results built from a completed call now carries `cached` (D9) and the step row records it. The kwargs are added in blocks that begin mid-call, after 7.7 to 7.10, so the evaluate and reflect blocks stay unique.

`src/probos/cognitive/sub_task.py`, `SubTaskResult` (appended last; every field is defaulted):

SEARCH:
```python
    model: str = ""                     # BF-901: the model that answered ("" = none named; the row says "unknown")
    token_source: str = ""              # BF-901: "measured", "estimated" or "" (nothing accounted for)
```
REPLACE:
```python
    model: str = ""                     # BF-901: the model that answered ("" = none named; the row says "unknown")
    token_source: str = ""              # BF-901: "measured", "estimated" or "" (nothing accounted for)
    cached: bool = False                # BF-901: a client cache replay (the step row records it; spend excludes it)
```

`src/probos/cognitive/sub_task.py`, the step row:

SEARCH:
```python
                    dag_node_id=dag_node_id,
                    token_source=getattr(result, "token_source", ""),  # BF-901: as the handler charged it
```
REPLACE:
```python
                    dag_node_id=dag_node_id,
                    cached=getattr(result, "cached", False) is True,  # BF-901: a replay stays out of spend
                    token_source=getattr(result, "token_source", ""),  # BF-901: as the handler charged it
```

`src/probos/cognitive/sub_tasks/analyze.py`:

SEARCH:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse structured JSON from response
```
REPLACE:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)
        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay

        # Parse structured JSON from response
```

SEARCH:
```python
                error=error_msg,
                tier_used=response.tier,
                model=answered,
                token_source=charge.source,
            )
```
REPLACE:
```python
                error=error_msg,
                tier_used=response.tier,
                model=answered,
                token_source=charge.source,
                cached=replayed,  # BF-901: a replay whose reply did not parse is still a replay
            )
```

SEARCH:
```python
            success=True,
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
        )
```
REPLACE:
```python
            success=True,
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
            cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend
        )
```

`src/probos/cognitive/sub_tasks/compose.py`:

SEARCH:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Return composed output
```
REPLACE:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)
        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay

        # Return composed output
```

SEARCH:
```python
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
        )
```
REPLACE:
```python
            tier_used=response.tier,
            model=answered,
            token_source=charge.source,
            cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend
        )
```

`src/probos/cognitive/sub_tasks/evaluate.py`:

SEARCH:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse structured verdict
```
REPLACE:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)
        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay

        # Parse structured verdict
```

SEARCH:
```python
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=charge.total_tokens,
                prompt_tokens=charge.prompt_tokens,
                completion_tokens=charge.completion_tokens,
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
                model=answered,
                token_source=charge.source,
            )
```
REPLACE:
```python
                result=dict(_PASS_BY_DEFAULT),
                tokens_used=charge.total_tokens,
                prompt_tokens=charge.prompt_tokens,
                completion_tokens=charge.completion_tokens,
                duration_ms=duration,
                success=True,
                tier_used=getattr(response, "tier", ""),
                model=answered,
                token_source=charge.source,
                cached=replayed,  # BF-901: a replay whose verdict did not parse is still a replay
            )
```

SEARCH:
```python
            result=result,
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
        )
```
REPLACE:
```python
            result=result,
            tokens_used=charge.total_tokens,
            prompt_tokens=charge.prompt_tokens,
            completion_tokens=charge.completion_tokens,
            duration_ms=duration,
            success=True,
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
            cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend
        )
```

`src/probos/cognitive/sub_tasks/reflect.py`:

SEARCH:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)

        # Parse response
```
REPLACE:
```python
        charge = charge_completion(request_messages(request), response)
        answered = answered_model_name(response)
        replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay

        # Parse response
```

SEARCH:
```python
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
        )
```
REPLACE:
```python
            tier_used=getattr(response, "tier", ""),
            model=answered,
            token_source=charge.source,
            cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend
        )
```

**Not changed, and why.** `analyze.py`'s error-response result (`response.error` set: a replay carries no error, and S1 charges an error nothing); the `except` arms (no response); the timed-out attempt row and the optional-step failure result (no response); the decision-cache-hit and procedural-replay rows (already `cached=True`, section 7.6); `ChainExecutionTrace` and `chain_traces` (no column, D9).

### 7.11 New file

#### `tests/test_bf901_s2_journal_token_provenance.py`

```python
"""BF-901 S2 (#1575): the journal records what each call cost, where the count came from, and the model that answered.

The contract is ``prompts/bf-901-s2-journal-token-provenance.md``. Every test but U9 and U12 writes through a real
``CognitiveJournal`` on ``tmp_path`` and reads the rows back through its own readers (``get_reasoning_chain``,
``get_recent_chain_traces``, ``get_token_usage``; U11 also ``get_token_usage_by``, ``get_token_usage_since`` and the
AD-617b hourly gate). U9 and U12 test the handlers' returned results, with no journal; U11 carries a replayed step
from a handler's result into the journal (review round 1, F1). The one-shot rows come from the real
``CognitiveAgent.decide`` -> ``_decide_via_llm`` (the agent
built as tests/test_cognitive_journal.py builds it, over a spec'd runtime mock); the chain rows from the real
``SubTaskExecutor`` and the real sub-task handlers. Stand-ins, named: the model client (``_OneShotClient``, a
``MockLLMClient`` that answers one scripted ``LLMResponse``), the procedural-memory lookup in U6, and in U8 a handler
whose first call never returns plus a no-wait ``asyncio.sleep`` (BF-183's 2 s back-off).

Mutants (the contract's section 10): J1, J2 U10; J3, C3, C4 U1; J4, S3 U7; C1 U3; C2 U4; C5 U5; C6 U6; S1, S2 U8;
H1-H8 U9; S4 U11; R1-R10 U12 (R4 and R5 also fail U11).
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.cognitive.chain_trace import ChainExecutionTrace
from probos.cognitive.cognitive_agent import CognitiveAgent, _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES
from probos.cognitive.journal import CognitiveJournal
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.sub_task import SubTaskChain, SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import AnalyzeHandler
from probos.cognitive.sub_tasks.compose import ComposeHandler
from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_tasks.reflect import ReflectHandler
from probos.config import CognitiveConfig, LLMRateConfig
from probos.crew_execution_usage import TOKEN_SOURCE_ESTIMATED, TOKEN_SOURCE_MEASURED
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.types import IntentDescriptor, LLMRequest, LLMResponse

SENT = "sent-model"
ANSWERED = "answered-model"
OBSERVATION = {"intent": "test", "params": {"q": "hello"}, "context": ""}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _TestAgent(CognitiveAgent):
    """tests/test_cognitive_journal.py's agent (copied: tests do not import each other)."""

    agent_type = "test_journal_agent"
    _handled_intents = {"test"}
    instructions = "You are a test agent."
    intent_descriptors = [IntentDescriptor(name="test", params={}, description="Test", tier="domain")]


class _OneShotClient(MockLLMClient):
    """Answers every request with one scripted response (its ``request_id`` set to the request's)."""

    def __init__(self, response: LLMResponse) -> None:
        super().__init__()
        self._response = response
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return dataclasses.replace(self._response, request_id=request.id)


class _OneReply:
    """A handler's ``llm_client``: answers every request with one response and records the requests."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return self._response


@pytest.fixture(autouse=True)
def _clear_decision_caches() -> None:
    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


@pytest.fixture
async def journal(tmp_path: Path) -> AsyncIterator[CognitiveJournal]:
    j = CognitiveJournal(db_path=str(tmp_path / "cognitive_journal.db"))
    await j.start()
    try:
        yield j
    finally:
        await j.stop()


def _runtime(journal: CognitiveJournal, *, decision_cache: bool = False) -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt.cognitive_journal = journal
    if decision_cache:
        # BF-864: the decision cache is off unless configured on (tests/test_cognitive_journal.py, test 10).
        rt.config = SimpleNamespace(cognitive=CognitiveConfig(decision_cache_enabled=True))
    return rt


async def _rows(journal: CognitiveJournal, agent_id: str) -> list[dict[str, Any]]:
    return await journal.get_reasoning_chain(agent_id, limit=50)


def _len4(text: str) -> int:
    """AD-1142's estimate of one message: ``max(1, len(text) // 4)``, worked here, not imported."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# 1. The one-shot call (cognitive_agent.py, _decide_via_llm)
# ---------------------------------------------------------------------------


async def test_a_one_shot_call_records_an_estimate_where_the_provider_reported_zeros(journal: CognitiveJournal) -> None:
    """U1: the proxy's shape. The row's counts are the estimate, labelled, and it names the answering model."""
    reply = "z" * 400
    llm = _OneShotClient(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, usage_reported=True))
    agent = _TestAgent(llm_client=llm, runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (request,) = llm.requests
    assert request.messages is None  # premise: the prompt shape, so the estimate is system + user
    expected_prompt = (_len4(request.system_prompt) if request.system_prompt else 0) + _len4(request.prompt)
    (row,) = await _rows(journal, agent.id)
    assert row["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert row["completion_tokens"] == _len4(reply)
    assert row["prompt_tokens"] == expected_prompt
    assert row["total_tokens"] == expected_prompt + _len4(reply)
    assert row["model"] == ANSWERED
    assert row["cached"] == 0
    assert row["success"] == 1


async def test_a_one_shot_call_records_measured_counts(journal: CognitiveJournal) -> None:
    """U2: reported counts are recorded as reported."""
    llm = _OneShotClient(
        LLMResponse(content="ok", model=SENT, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
    )
    agent = _TestAgent(llm_client=llm, runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (100, 50, 150)
    assert row["token_source"] == TOKEN_SOURCE_MEASURED


@pytest.mark.parametrize(
    ("response", "model", "source", "success"),
    [
        pytest.param(
            LLMResponse(content="ok", model=SENT, answered_model=ANSWERED, tokens_used=9, usage_reported=True),
            ANSWERED, TOKEN_SOURCE_MEASURED, 1, id="answered",
        ),
        pytest.param(LLMResponse(content="ok", model=SENT, tokens_used=9, usage_reported=True), SENT, TOKEN_SOURCE_MEASURED, 1, id="sent"),
        pytest.param(LLMResponse(content="", model="", error="All LLM tiers unavailable"), "unknown", "", 0, id="error"),
    ],
)
async def test_a_one_shot_row_names_the_model_that_answered(
    journal: CognitiveJournal, response: LLMResponse, model: str, source: str, success: int,
) -> None:
    """U3: answered first, then the id sent, then ``unknown``; never empty."""
    agent = _TestAgent(llm_client=_OneShotClient(response), runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert (row["model"], row["token_source"], row["success"]) == (model, source, success)


async def test_a_replay_row_is_cached_and_adds_nothing_to_token_usage(journal: CognitiveJournal) -> None:
    """U4: a client cache replay carries the original call's count and ``cached=True``; recorded as cached, the
    readers' ``cached = 0`` filter keeps it out of spend. The control call that follows is counted."""
    replay = LLMResponse(content="cached text", model=SENT, tokens_used=500, cached=True)
    agent = _TestAgent(llm_client=_OneShotClient(replay), runtime=_runtime(journal))

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert row["cached"] == 1
    assert row["total_tokens"] == 500  # premise: the replay's count is on the row
    usage = await journal.get_token_usage()
    assert (usage["total_tokens"], usage["total_calls"]) == (0, 0)

    agent._llm_client = _OneShotClient(
        LLMResponse(content="ok", model=SENT, tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True),
    )
    await agent.decide(dict(OBSERVATION))

    usage = await journal.get_token_usage()
    assert (usage["total_tokens"], usage["total_calls"]) == (150, 1)


# ---------------------------------------------------------------------------
# 2. The rows that make no model call (cognitive_agent.py:3668, :3705)
# ---------------------------------------------------------------------------


async def test_a_decision_cache_hit_row_names_unknown(journal: CognitiveJournal) -> None:
    """U5: the second identical observation is a decision-cache hit; its row is cached and names ``unknown``."""
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=_runtime(journal, decision_cache=True), pool="test")

    await agent.decide(dict(OBSERVATION))
    await agent.decide(dict(OBSERVATION))

    rows = {row["cached"]: row for row in await _rows(journal, agent.id)}
    assert set(rows) == {0, 1}  # premise: one model call, one cache hit
    assert rows[1]["model"] == "unknown"
    assert rows[1]["token_source"] == ""
    assert rows[0]["model"] == "mock"  # the call's own row names the mock client's model


async def test_a_procedural_replay_row_names_unknown(journal: CognitiveJournal) -> None:
    """U6: a procedural replay makes no model call; its row names ``unknown``."""
    agent = _TestAgent(llm_client=MockLLMClient(), runtime=_runtime(journal))
    agent._check_procedural_memory = AsyncMock(
        return_value={"action": "execute", "llm_output": "replayed", "procedure_id": "proc-1"},
    )

    await agent.decide(dict(OBSERVATION))

    (row,) = await _rows(journal, agent.id)
    assert row["procedure_id"] == "proc-1"  # premise: the replay branch wrote it
    assert row["model"] == "unknown"
    assert row["cached"] == 1


# ---------------------------------------------------------------------------
# 3. Chain steps (sub_task.py)
# ---------------------------------------------------------------------------

_CONTEXT = {
    "_agent_type": "science_officer",
    "_callsign": "Lynx",
    "_department": "Science",
    "context": "Thread content here.",
}


async def test_a_chain_step_records_the_handler_charge_and_model(journal: CognitiveJournal) -> None:
    """U7: the real executor, the real compose handler and the real journal. The step row carries the handler's
    charge (the proxy's zeros, so an estimate), its split, its source and the answering model; the trace carries the
    same source and total."""
    reply = "A reply to the thread."
    llm = _OneReply(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, usage_reported=True))
    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=llm, runtime=None))
    chain = SubTaskChain(steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard")], source="test")

    await executor.execute(
        chain, dict(_CONTEXT), agent_id="agent-1", agent_type="science_officer",
        intent="ward_room_notification", intent_id="int-1", journal=journal,
    )

    assert len(llm.requests) == 1  # premise: the handler made its call
    (row,) = await _rows(journal, "agent-1")
    assert row["dag_node_id"].endswith(":compose")
    assert row["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert row["model"] == ANSWERED
    assert row["completion_tokens"] == _len4(reply)
    assert row["prompt_tokens"] > 0
    assert row["total_tokens"] == row["prompt_tokens"] + row["completion_tokens"]
    (trace,) = await journal.get_recent_chain_traces(limit=10)
    assert trace["token_source"] == TOKEN_SOURCE_ESTIMATED
    assert trace["tokens_used"] == row["total_tokens"]


class _SlowOnce:
    """A handler whose first call never returns (BF-183 times it out and retries) and whose retry names no model."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, spec: SubTaskSpec, context: dict, prior: list[SubTaskResult]) -> SubTaskResult:
        self.calls += 1
        if self.calls == 1:
            await asyncio.Event().wait()
        return SubTaskResult(
            sub_task_type=spec.sub_task_type, name=spec.name, result={"output": "ok"}, success=True, tier_used="standard",
        )


async def test_a_timed_out_attempt_and_its_retry_name_unknown(
    journal: CognitiveJournal, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """U8: the timed-out attempt's row (``sub_task.py:586``) and the step's row for a result that names no model
    (``:657``) both say ``unknown``; neither accounts for tokens."""
    real_sleep = asyncio.sleep

    async def _no_backoff(delay: float, result: Any = None) -> Any:
        await real_sleep(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", _no_backoff)
    handler = _SlowOnce()
    executor = SubTaskExecutor()
    executor.register_handler(SubTaskType.COMPOSE, handler)
    chain = SubTaskChain(
        steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard", timeout_ms=50)],
        chain_timeout_ms=60_000, source="test",
    )

    await executor.execute(chain, dict(_CONTEXT), agent_id="agent-2", agent_type="science_officer", journal=journal)

    assert handler.calls == 2  # premise: timed out once, retried once
    rows = await _rows(journal, "agent-2")
    attempts = [r for r in rows if r["dag_node_id"].endswith(":timeout")]
    steps = [r for r in rows if not r["dag_node_id"].endswith(":timeout")]
    assert len(attempts) == 1 and len(steps) == 1
    assert attempts[0]["model"] == "unknown"
    assert attempts[0]["success"] == 0
    assert steps[0]["model"] == "unknown"
    assert (attempts[0]["token_source"], steps[0]["token_source"]) == ("", "")


async def test_a_replayed_chain_step_is_journaled_cached_and_adds_nothing_to_spend(journal: CognitiveJournal) -> None:
    """U11 (A1, review round 1 F1): the chain path of U4, from the handler to the spend readers. A client cache replay
    of a zero-count answer, built as llm_client.py's two replay paths build it (the original's content, models and
    ``tokens_used``, ``cached=True``, usage presence not stated), goes through the real compose handler, the real
    executor and the real journal. S1 charges it as an estimate, as it charges a one-shot replay; the step row is
    ``cached=1``, so ``get_token_usage``, ``get_token_usage_by``, ``get_token_usage_since`` and the real AD-617b gate
    (called as tests/test_ad617b_per_agent_token_budget.py calls it, with a 1-token cap) leave it out. A fresh step
    that follows is counted by all four: the filter is not vacuous."""
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(
        SimpleNamespace(
            config=SimpleNamespace(llm_rate=LLMRateConfig(per_agent_hourly_token_cap=1)), cognitive_journal=journal,
        ),
    )
    since = time.time() - 3600.0

    async def _step(response: LLMResponse) -> None:
        executor = SubTaskExecutor()
        executor.register_handler(SubTaskType.COMPOSE, ComposeHandler(llm_client=_OneReply(response), runtime=None))
        chain = SubTaskChain(
            steps=[SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", tier="standard")], source="test",
        )
        await executor.execute(
            chain, dict(_CONTEXT), agent_id="agent-3", agent_type="science_officer",
            intent="ward_room_notification", intent_id="int-3", journal=journal,
        )

    replay = LLMResponse(
        content="A reply to the thread.", model=SENT, answered_model=ANSWERED, tokens_used=0, cached=True,
    )
    await _step(replay)

    (replay_row,) = await _rows(journal, "agent-3")
    assert replay_row["token_source"] == TOKEN_SOURCE_ESTIMATED  # premise: S1 charges the zero-count replay
    assert replay_row["total_tokens"] > 0  # premise: so only ``cached`` keeps it out of spend
    assert replay_row["cached"] == 1
    usage = await journal.get_token_usage("agent-3")
    assert (usage["total_tokens"], usage["total_calls"]) == (0, 0)
    assert await journal.get_token_usage_by(group_by="model", agent_id="agent-3") == []
    assert await journal.get_token_usage_since("agent-3", since) == 0
    assert await loop._is_over_token_budget("agent-3") is False

    await _step(LLMResponse(content="A fresh reply.", model=SENT, answered_model=ANSWERED, usage_reported=True))

    (fresh,) = [row for row in await _rows(journal, "agent-3") if row["cached"] == 0]
    spent = fresh["total_tokens"]
    assert spent > 0  # premise: the control is charged
    usage = await journal.get_token_usage("agent-3")
    assert (usage["total_tokens"], usage["total_calls"]) == (spent, 1)
    by_model = await journal.get_token_usage_by(group_by="model", agent_id="agent-3")
    assert [(g["model"], g["total_calls"], g["total_tokens"]) for g in by_model] == [(ANSWERED, 1, spent)]
    assert await journal.get_token_usage_since("agent-3", since) == spent
    assert await loop._is_over_token_budget("agent-3") is True


# ---------------------------------------------------------------------------
# 4. The four handlers' success results
# ---------------------------------------------------------------------------

_HANDLERS = {
    "analyze": (AnalyzeHandler, SubTaskType.ANALYZE, '{"contribution_assessment": "RESPOND"}'),
    "compose": (ComposeHandler, SubTaskType.COMPOSE, "A reply to the thread."),
    "evaluate": (
        EvaluateHandler, SubTaskType.EVALUATE,
        '{"pass": true, "score": 0.9, "criteria": {}, "recommendation": "approve"}',
    ),
    "reflect": (ReflectHandler, SubTaskType.REFLECT, '{"output": "A reply to the thread.", "revised": false}'),
}


@pytest.mark.parametrize("mode", ["estimated", "measured"])
@pytest.mark.parametrize("kind", sorted(_HANDLERS))
async def test_each_handler_charges_its_call(kind: str, mode: str) -> None:
    """U9: each handler's success result carries the charge, its source and the answering model."""
    handler_cls, step_type, content = _HANDLERS[kind]
    if mode == "estimated":
        response = LLMResponse(content=content, model=SENT, answered_model=ANSWERED, usage_reported=True)
    else:
        response = LLMResponse(
            content=content, model=SENT, answered_model=ANSWERED,
            tokens_used=150, prompt_tokens=100, completion_tokens=50, usage_reported=True,
        )
    llm = _OneReply(response)
    handler = handler_cls(llm_client=llm, runtime=None)

    result = await handler(SubTaskSpec(sub_task_type=step_type, name=kind, tier="standard"), dict(_CONTEXT), [])

    assert len(llm.requests) == 1  # premise: the handler reached its model call
    assert result.success is True
    assert result.model == ANSWERED
    assert result.cached is False  # BF-901 (A1): a fresh call is not a replay
    if mode == "estimated":
        assert result.token_source == TOKEN_SOURCE_ESTIMATED
        assert result.prompt_tokens > 0
        assert result.completion_tokens == _len4(content)
        assert result.tokens_used == result.prompt_tokens + result.completion_tokens
    else:
        assert result.token_source == TOKEN_SOURCE_MEASURED
        assert (result.prompt_tokens, result.completion_tokens, result.tokens_used) == (100, 50, 150)


_NOT_JSON = "No JSON in this reply."
_REPLAY_CASES = {
    # case id: (handler, reply, the result's success, a result key, its value); the last three pin the branch
    "analyze-parsed": ("analyze", _HANDLERS["analyze"][2], True, "contribution_assessment", "RESPOND"),
    "analyze-parse-failure": ("analyze", _NOT_JSON, False, "contribution_assessment", None),
    "compose": ("compose", _HANDLERS["compose"][2], True, "output", "A reply to the thread."),
    "evaluate-verdict": ("evaluate", _HANDLERS["evaluate"][2], True, "score", 0.9),
    "evaluate-default": ("evaluate", _NOT_JSON, True, "score", 1.0),
    "reflect": ("reflect", _HANDLERS["reflect"][2], True, "output", "A reply to the thread."),
}


@pytest.mark.parametrize("case", list(_REPLAY_CASES))
async def test_each_completed_result_carries_the_replay_flag(case: str) -> None:
    """U12 (A1, review round 1 F1): every result built from a completed call, the analyze parse-failure and the
    evaluate default-verdict results included, carries a client cache replay's ``cached`` beside the charge S1 makes
    for it (a zero-count replay: an estimate) and the answering model. U11 carries one such result into the journal."""
    kind, reply, success, key, value = _REPLAY_CASES[case]
    handler_cls, step_type, _ = _HANDLERS[kind]
    llm = _OneReply(LLMResponse(content=reply, model=SENT, answered_model=ANSWERED, cached=True))
    handler = handler_cls(llm_client=llm, runtime=None)

    result = await handler(SubTaskSpec(sub_task_type=step_type, name=kind, tier="standard"), dict(_CONTEXT), [])

    assert len(llm.requests) == 1  # premise: the handler reached its model call
    assert (result.success, result.result.get(key)) == (success, value)  # premise: the branch the case names
    assert result.cached is True
    assert result.token_source == TOKEN_SOURCE_ESTIMATED
    assert result.model == ANSWERED


# ---------------------------------------------------------------------------
# 5. The migration
# ---------------------------------------------------------------------------

_PRE_BF901_JOURNAL = """
CREATE TABLE journal (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    agent_id    TEXT NOT NULL,
    agent_type  TEXT NOT NULL DEFAULT '',
    tier        TEXT NOT NULL DEFAULT 'standard',
    model       TEXT NOT NULL DEFAULT '',
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    latency_ms       REAL NOT NULL DEFAULT 0.0,
    intent           TEXT NOT NULL DEFAULT '',
    success          INTEGER NOT NULL DEFAULT 1,
    cached           INTEGER NOT NULL DEFAULT 0,
    request_id       TEXT NOT NULL DEFAULT '',
    prompt_hash      TEXT NOT NULL DEFAULT '',
    response_length  INTEGER NOT NULL DEFAULT 0,
    intent_id        TEXT NOT NULL DEFAULT '',
    dag_node_id      TEXT NOT NULL DEFAULT '',
    response_hash    TEXT NOT NULL DEFAULT '',
    procedure_id     TEXT NOT NULL DEFAULT '',
    correlation_id   TEXT NOT NULL DEFAULT '',
    level            TEXT NOT NULL DEFAULT '',
    level_rank       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE chain_traces (
    chain_id            TEXT NOT NULL,
    step_index          INTEGER NOT NULL,
    step_name           TEXT NOT NULL,
    sub_task_type       TEXT NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'standard',
    chain_source        TEXT NOT NULL DEFAULT '',
    agent_id            TEXT NOT NULL DEFAULT '',
    agent_type          TEXT NOT NULL DEFAULT '',
    intent              TEXT NOT NULL DEFAULT '',
    intent_id           TEXT NOT NULL DEFAULT '',
    started_at          REAL NOT NULL DEFAULT 0.0,
    duration_ms         REAL NOT NULL DEFAULT 0.0,
    tokens_used         INTEGER NOT NULL DEFAULT 0,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    success             INTEGER NOT NULL DEFAULT 1,
    error_truncated     TEXT NOT NULL DEFAULT '',
    context_keys_declared INTEGER NOT NULL DEFAULT 0,
    context_keys_passed   INTEGER NOT NULL DEFAULT 0,
    context_filter_applied INTEGER NOT NULL DEFAULT 0,
    communication_context TEXT,
    chain_trust_band      TEXT,
    trust_score           REAL,
    boot_camp_active      INTEGER NOT NULL DEFAULT 0,
    from_captain          INTEGER NOT NULL DEFAULT 0,
    is_dm                 INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chain_id, step_index)
);
INSERT INTO journal (id, timestamp, agent_id, model, total_tokens) VALUES ('old-row', 1.0, 'agent-old', '', 0);
INSERT INTO chain_traces (chain_id, step_index, step_name, sub_task_type, agent_id, started_at)
    VALUES ('old-chain', 0, 'compose', 'compose', 'agent-old', 1.0);
"""


async def _columns(db_path: str, table: str) -> list[str]:
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in await cursor.fetchall()]


async def test_a_warm_boot_adds_the_columns_once_and_old_rows_read_empty(tmp_path: Path) -> None:
    """U10: a database with the pre-BF-901 schema and one row in each table."""
    db_path = str(tmp_path / "warm.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(_PRE_BF901_JOURNAL)
        await conn.commit()
    assert "token_source" not in await _columns(db_path, "journal")  # premise: the old shape

    journal = CognitiveJournal(db_path=db_path)
    await journal.start()
    try:
        assert (await _columns(db_path, "journal")).count("token_source") == 1
        assert (await _columns(db_path, "chain_traces")).count("token_source") == 1
        (old,) = await journal.get_reasoning_chain("agent-old")
        assert old["token_source"] == ""
        (old_trace,) = await journal.get_recent_chain_traces(agent_id="agent-old")
        assert old_trace["token_source"] == ""
        await journal.record(
            entry_id=uuid.uuid4().hex, timestamp=time.time(), agent_id="agent-new", model="m",
            total_tokens=7, token_source=TOKEN_SOURCE_MEASURED,
        )
        await journal.record_chain_trace(
            ChainExecutionTrace(
                chain_id="new-chain", step_index=0, step_name="compose", sub_task_type="compose", tier="standard",
                agent_id="agent-new", started_at=time.time(), tokens_used=7, token_source=TOKEN_SOURCE_ESTIMATED,
            ),
        )
        (new,) = await journal.get_reasoning_chain("agent-new")
        assert new["token_source"] == TOKEN_SOURCE_MEASURED
        (new_trace,) = await journal.get_recent_chain_traces(agent_id="agent-new")
        assert new_trace["token_source"] == TOKEN_SOURCE_ESTIMATED
    finally:
        await journal.stop()

    again = CognitiveJournal(db_path=db_path)
    await again.start()  # the second start: the ALTERs find the columns and are skipped
    try:
        assert (await _columns(db_path, "journal")).count("token_source") == 1
        assert (await _columns(db_path, "chain_traces")).count("token_source") == 1
    finally:
        await again.stop()
```

## 8. Tracking (tracker pairs)

**`PROGRESS.md`** (anchored on the first line, the blank line after it and the head of S1's entry):

SEARCH:
```markdown
# ProbOS Progress

**BF-901 S1 (2026-10-21), part of #1575 -- one owner for the token estimator, and usage presence at the transport.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-901 S2 (2026-10-21), part of #1575 -- the journal records what each call cost, where the count came from, and the model that answered.** `journal` and `chain_traces` gain `token_source TEXT NOT NULL DEFAULT ''` (in the schema for a new database, an idempotent `ALTER` for an existing one; `''` means nothing accounted for or recorded before BF-901, never measured). The four sub-task handlers charge each completed call with S1's `charge_completion` and carry the answering model on `SubTaskResult` (new `model`, `token_source`, `cached`); the chain-step journal row records the charge with its prompt/completion split, the source, the model (or `unknown`) and whether the step replayed the client cache, and the trace records the source. The one-shot record in `CognitiveAgent._decide_via_llm` records the charge, the model that answered (it recorded the id sent) and `cached` from the response. On both paths a client cache replay keeps its charge, labelled, and is recorded `cached`, so the readers' `cached = 0` filter keeps it out of spend and out of the AD-617b cap. The timed-out attempt, decision-cache-hit and procedural-replay rows, which make no model call, record `unknown`. The aggregate readers' shapes are unchanged (`get_token_usage`, `get_token_usage_since`, `get_token_usage_by`); the full-row readers (`SELECT *`: `get_reasoning_chain`, `get_decision_points`, `get_recent_chain_traces`) and the routes and diagnostic context that serialize them gain a `token_source` key. The token sums become non-zero where the proxy reported zeros, the AD-617b cap that reads them stays off by default, and rows written before BF-901 keep `''`. New: `tests/test_bf901_s2_journal_token_provenance.py` (the real `decide`, `SubTaskExecutor` and handlers; the journal tests through a real `CognitiveJournal`, the handler tests on the handlers' results; a replayed chain step through the journal, its usage readers and the hourly cap; a warm boot on the old schema). S3 (the doctor view, closes #1575) reads these columns. The decisions are in DECISIONS.md (BF-901 S2); the contract is `prompts/bf-901-s2-journal-token-provenance.md`.

**BF-901 S1 (2026-10-21), part of #1575 -- one owner for the token estimator, and usage presence at the transport.**
```

**`DECISIONS.md`** (after S1's entry, before the heading that follows it):

SEARCH:
```markdown
- *Reversal.* Revert the BF-901 S1 commit (and S2 first, which depends on it). Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the BF-901 S1 commit (and S2 first, which depends on it). Nothing persisted changes.

### BF-901 S2 -- The journal records what each call cost, where the count came from, and the model that answered (2026-10-21, part of #1575)

- *Scope.* `cognitive/journal.py` (the column, the migrations, the two writers), `cognitive/chain_trace.py`, `cognitive/sub_task.py` (`SubTaskResult`, the attempt row, the step row, the trace), `cognitive/cognitive_agent.py` (the three journal sites), the four sub-task handlers and tests. Contract: `prompts/bf-901-s2-journal-token-provenance.md`.
- *Cause.* The one-shot site recorded the id sent as the model, the proxy's zero counts and `cached=False` for a client cache replay; the chain-step row recorded no model, no split and no source; the cache-hit, replay and timed-out-attempt rows no model. Neither table had a column for the source. The chain-step sites fit #1575's 1,272 empty-model rows (QUERY steps write no row); one query on a copy of the vessel's journal would confirm it (the contract's section 13).
- *D1-D2.* `token_source TEXT NOT NULL DEFAULT ''` on both tables, added in the schema and by an idempotent `ALTER` (additive, no schema breaks, so not a Captain condition). `''` means nothing accounted for or recorded before BF-901; only `charge_completion`'s measured branch writes `measured`.
- *D3-D5.* The one-shot row names `answered_model_name(response)`; `cached` is the response's (`is True`, so a mock double is not read as a replay), which the readers' `cached = 0` filter then keeps out of spend; rows that make no model call record `unknown`.
- *D6-D8.* The handlers charge at each result built from a completed call (the executor has no request or response); the chain-step row also gains the prompt/completion split; the executor reads the new result fields with `getattr`, as it already reads the split; `token_accounting` is imported at the call sites.
- *D9 (Amendment A1, review round 1 F1).* A chain step's result carries `cached` (`getattr(response, "cached", False) is True` at each of the six results built from a completed call, the parse-failure and default-verdict results included), and the step row records it, as the one-shot row does (D4). The charge and its source stay on the row, labelled; the readers' `cached = 0` filter keeps it out of spend. Without it, a replay of a zero-count proxy answer, which S1 charges as an estimate, entered the sums and the AD-617b cap. `chain_traces` has no `cached` column and gets none: nothing sums trace tokens as spend, and S3 takes spend from `journal`.
- *Departures from the consult.* `ChainExecutionTrace` gains `token_source` only: `chain_traces` has no model column and the journal is the trace's only reader, so a `model` field would be written nowhere; the step's journal row names the model.
- *Recorded, not repaired.* A warm-boot `ALTER` that fails for a reason other than a duplicate column is swallowed, as the earlier migrations' are; the readers' sums now include estimates, labelled per row, and S3 shows measured, estimated and `''` apart. AD-633's speculative budget (`predictive_branching/executor.py:102-105`, `:195-199`) sums its chain results' `tokens_used`, a replay's included; it is off by default (`predictive_branching.enabled: false`), and skipping results marked `cached` there is a one-line follow-up.
- *Reversal.* Revert the BF-901 S2 commit. The added columns stay in any database that started under it (SQLite keeps them) and are harmless, though not invisible: the reverted code's named `INSERT`s leave them at their default `''`, and its `SELECT *` readers still return them, so the routes and the diagnostic context still serialize `token_source` on rows written while S2 ran. The aggregate readers do not read it.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both belong to the commit. Then `--check` and `tests/test_ad1184_ad_ledger.py` (M5).

**Records the orchestrator adds before the commit:** a *Validation of record* bullet in this entry (the mutation campaign, base tree and sha256 of each file in section 10), then the ledger regeneration again.

**`docs/development/roadmap.md`:** no row (BF-900's contract, section 8, gives the grep).

## 9. What this does NOT change

- The readers' queries, and the aggregate readers' shapes (`get_token_usage`, `get_token_usage_since`, `get_token_usage_by` and its allowlist, `journal.py:891`; the full-row `SELECT *` readers' rows gain the `token_source` key, section 5), the routes, the AD-617b cap and its default, the EPS report's logic, the chain optimizer, the clinical telemetry, the optimization counselor; S3 adds the source split and the doctor view.
- The agentic loop and dispatch (they write no journal row; BF-680 labels their outcomes), `TurnCostBudget`, AD-1208 and AD-1323 to AD-1325.
- The model calls that write no journal row (about 48 files, consult decision 4), `MockLLMClient`, the transport (S1), the Copilot proxy, price tables, configuration (no field; `config/system.yaml` untouched).
- Rows already in a vessel's journal: they keep their values and read `''` for the source (no back-fill).
- `chain_traces`: A1 adds no `cached` column (D9); spend is the journal's sum.
- The error-response results of the handlers (`analyze.py:610-623` and the `except` arms): they record the transport's zeros and `unknown`.

## 10. Mutation rows (32 rows; whole stripped lines; each occurs once in its file after section 7, 7.10a included)

Run against `tests/test_bf901_s2_journal_token_provenance.py` on the contract-applied tree (BF-900 and S1 applied), after an unmutated baseline run of that file that passes. The runner mutates each file in place and restores it before the next row.

| # | File | Line (stripped) | Mutate to | Killed by (the failing assertion) |
|---|---|---|---|---|
| J1 | `src/probos/cognitive/journal.py` | `("token_source", "TEXT NOT NULL DEFAULT ''"),  # BF-901: measured, estimated or '' (none)` | `# removed` | U10: `assert (await _columns(db_path, "journal")).count("token_source") == 1` |
| J2 | same | `"ALTER TABLE chain_traces ADD COLUMN token_source TEXT NOT NULL DEFAULT ''",` | `# removed` | U10: `assert (await _columns(db_path, "chain_traces")).count("token_source") == 1` |
| J3 | same | `correlation_id, level, level_rank, token_source,` | `correlation_id, level, level_rank, "",` | U1: `assert row["token_source"] == TOKEN_SOURCE_ESTIMATED` |
| J4 | same | `getattr(trace, "token_source", ""),` | `"",` | U7: `assert trace["token_source"] == TOKEN_SOURCE_ESTIMATED` |
| C1 | `src/probos/cognitive/cognitive_agent.py` | `model=answered_model_name(response),` | `model=response.model,` | U3[answered]: the row names `sent-model` |
| C2 | same | `cached=response.cached is True,` | `cached=False,` | U4: `assert row["cached"] == 1` |
| C3 | same | `token_source=_charge.source,` | `token_source="",` | U1: `assert row["token_source"] == TOKEN_SOURCE_ESTIMATED` |
| C4 | same | `total_tokens=_charge.total_tokens,` | `total_tokens=response.tokens_used,` | U1: `assert row["total_tokens"] == expected_prompt + _len4(reply)` (the row says 0) |
| C5 | same | `model="unknown",  # BF-901: a decision-cache hit makes no model call` | `model="",` | U5: `assert rows[1]["model"] == "unknown"` |
| C6 | same | `model="unknown",  # BF-901: a procedural replay makes no model call` | `model="",` | U6: `assert row["model"] == "unknown"` |
| S1 | `src/probos/cognitive/sub_task.py` | `model="unknown",  # BF-901: an abandoned attempt names no answering model` | `model="",` | U8: `assert attempts[0]["model"] == "unknown"` |
| S2 | same | `model=getattr(result, "model", "") or "unknown",` | `model=getattr(result, "model", ""),` | U8: `assert steps[0]["model"] == "unknown"` |
| S3 | same | `token_source=getattr(result, "token_source", ""),  # BF-901: as the handler charged it` | `token_source="",` | U7: `assert row["token_source"] == TOKEN_SOURCE_ESTIMATED` |
| H1 | `src/probos/cognitive/sub_tasks/analyze.py` | `charge = charge_completion(request_messages(request), response)` | `charge = charge_completion([], response)` | U9[analyze-estimated]: `assert result.prompt_tokens > 0` |
| H2 | same | `answered = answered_model_name(response)` | `answered = response.model` | U9[analyze-*]: `assert result.model == ANSWERED` |
| H3 | `src/probos/cognitive/sub_tasks/compose.py` | `charge = charge_completion(request_messages(request), response)` | `charge = charge_completion([], response)` | U9[compose-estimated] (and U7) |
| H4 | same | `answered = answered_model_name(response)` | `answered = response.model` | U9[compose-*] (and U7) |
| H5 | `src/probos/cognitive/sub_tasks/evaluate.py` | `charge = charge_completion(request_messages(request), response)` | `charge = charge_completion([], response)` | U9[evaluate-estimated] |
| H6 | same | `answered = answered_model_name(response)` | `answered = response.model` | U9[evaluate-*] |
| H7 | `src/probos/cognitive/sub_tasks/reflect.py` | `charge = charge_completion(request_messages(request), response)` | `charge = charge_completion([], response)` | U9[reflect-estimated] |
| H8 | same | `answered = answered_model_name(response)` | `answered = response.model` | U9[reflect-*] |
| S4 | `src/probos/cognitive/sub_task.py` | `cached=getattr(result, "cached", False) is True,  # BF-901: a replay stays out of spend` | `cached=False,` | U11: `assert replay_row["cached"] == 1` |
| R1 | `src/probos/cognitive/sub_tasks/analyze.py` | `replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay` | `replayed = False` | U12[analyze-parsed], U12[analyze-parse-failure]: `assert result.cached is True` |
| R2 | same | `cached=replayed,  # BF-901: a replay whose reply did not parse is still a replay` | `cached=False,` | U12[analyze-parse-failure]: `assert result.cached is True` |
| R3 | same | `cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend` | `cached=False,` | U12[analyze-parsed]: `assert result.cached is True` |
| R4 | `src/probos/cognitive/sub_tasks/compose.py` | `replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay` | `replayed = False` | Pinned by U12[compose]: `assert result.cached is True` (U11 also fails: `assert replay_row["cached"] == 1`) |
| R5 | same | `cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend` | `cached=False,` | Pinned by U12[compose] (U11 also fails) |
| R6 | `src/probos/cognitive/sub_tasks/evaluate.py` | `replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay` | `replayed = False` | U12[evaluate-verdict], U12[evaluate-default]: `assert result.cached is True` |
| R7 | same | `cached=replayed,  # BF-901: a replay whose verdict did not parse is still a replay` | `cached=False,` | U12[evaluate-default]: `assert result.cached is True` |
| R8 | same | `cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend` | `cached=False,` | U12[evaluate-verdict]: `assert result.cached is True` |
| R9 | `src/probos/cognitive/sub_tasks/reflect.py` | `replayed = getattr(response, "cached", False) is True  # BF-901: a client cache replay` | `replayed = False` | U12[reflect]: `assert result.cached is True` |
| R10 | same | `cached=replayed,  # BF-901: the step row records it, so the readers leave it out of spend` | `cached=False,` | U12[reflect]: `assert result.cached is True` |

The `SubTaskResult.cached` declaration has no row: it is a field, not a propagation line, and removing it makes every handler raise `TypeError`. A `replayed = True` mutant is killed by U9's `assert result.cached is False`.

Campaign of record: name the base tree and the sha256 of each mutated file and the new test file; a later run whose hashes match does not repeat it.

## 11. Verified Against Codebase (2026-10-21, tree `8c8bc441`)

`git diff --stat 3dfb6f81 HEAD -- src/probos/cognitive/journal.py src/probos/cognitive/sub_task.py src/probos/cognitive/sub_tasks src/probos/cognitive/chain_trace.py src/probos/cognitive/cognitive_agent.py` printed nothing: no anchor moved since the consult. BF-900 edits `cognitive_agent.py:2279-2298` only; S1 edits none of these files.

| Consult anchor | On this tree | Evidence |
|---|---|---|
| Journal schema | TRUE | `journal.py:22-46` (`model TEXT NOT NULL DEFAULT ''` at `:28`; `level_rank` last, `:45`); `chain_traces` `:59-88` (`completion_tokens` `:75`, `success` `:76`) |
| Idempotent ALTER precedents | TRUE | `journal.py:201-211` (AD-432 list ending with `correlation_id`, `except sqlite3.OperationalError: pass`), `:122-125` and `:227-232` (AD-658a); `import sqlite3` at `:12` |
| `record()` | TRUE (`:360-412`) | 23 columns and 23 placeholders (`:392-399`); `level_rank` the last keyword (`:385`) |
| `record_chain_trace()` | TRUE (`:414-456`) | 26 columns, 26 placeholders (`:425-434`); AD-658a's getattr (`:440-443`) |
| Readers' `cached = 0` | TRUE | `journal.py:831`, `:841`, `:872`, `:895`; `SELECT *` at `:486`, `:790`, `:956` |
| `get_token_usage_by` allowlist | TRUE | `journal.py:891` (S3's) |
| `SubTaskResult` | TRUE (`sub_task.py:85-97`) | frozen; every field after `name` defaulted; `completion_tokens` last (`:97`) |
| Timeout row | TRUE (`sub_task.py:586-598`) | `tier=spec.tier,` / `total_tokens=0,` / `latency_ms=spec.timeout_ms,` (`:591-593`) |
| Step row | TRUE (`:657-669`) | `tier=result.tier_used or spec.tier,` / `total_tokens=result.tokens_used,` (`:662-663`); QUERY skipped (`:654`) |
| Trace | TRUE (`:680-715`) | `prompt_tokens=getattr(result, "prompt_tokens", 0),` (`:697`) ... `error_truncated=(result.error or "")[:200],` (`:700`) |
| `ChainExecutionTrace` | TRUE | `chain_trace.py:14-56`, `to_dict` is `asdict` (`:54-56`) |
| One-shot site | MOVED +1 (`:4487`) | `cognitive_agent.py:4471` `response = await self._llm_client.complete(request, priority=_priority)`; `:4493` `model=response.model,`; `:4500` `cached=False,`; the `try` `:4485-4511` |
| Cache hit, replay | MOVED +1 (`:3668`, `:3705`) | `:3675` `cached=True,` (28 spaces) then `correlation_id`; `:3712-3714` `cached=True,` / `total_tokens=0,` / `procedure_id=...` |
| Handlers | TRUE | `analyze.py:584-590` (request), `:625-627`, `:651-662`, `:665-675`; `compose.py:653-664`, `:678-690`; `evaluate.py:636-645`, `:663-665`, `:677-687`, `:729-739`; `reflect.py:514-523`, `:542-545`, `:582-592` |
| The journal property | TRUE | `cognitive_agent.py:1695-1700` (`runtime.cognitive_journal`) |
| The agent rig | TRUE | `tests/test_cognitive_journal.py:199-245` (`_TestAgent`, `MagicMock(spec=ProbOSRuntime)`, `decide`), `:260-262` (decision cache on) |
| Executor API | TRUE | `sub_task.py:285-295` (`execute(chain, context, *, agent_id, agent_type, intent, intent_id, journal)`), `:232` `register_handler`, `:101-106` `SubTaskChain` (`chain_timeout_ms` default 240000), `:575-614` (BF-183 retry: needs `remaining_ms >= timeout + 2000`, sleeps `backoff_ms / 1000`) |
| Handler constructors | TRUE | `AnalyzeHandler.__init__(self, *, llm_client, runtime)` `analyze.py:538`; `ComposeHandler` `compose.py:594`; `EvaluateHandler(*, llm_client=None, runtime=None)` `evaluate.py:369`; `ReflectHandler` `reflect.py:371` |
| Tracker anchors (after S1) | per S1 section 8 | `PROGRESS.md` line 1, blank, S1's entry; `DECISIONS.md` S1's *Reversal* line, blank, `### Explicit delegation models, ...` |

### 11.1 A1 re-verification (2026-10-21, candidate r1, tree `8112781c`)

The claims above stand (tree `8c8bc441`). A1's anchors on the candidate:

| A1 anchor | Evidence |
|---|---|
| `SubTaskResult` has no `cached` | `sub_task.py:85-99` (`token_source` last, `:99`); `Grep "\bcached\b" src/probos/cognitive/sub_task.py` finds nothing |
| The step row passes no `cached`; `record` defaults it `False` | `sub_task.py:660-678`; `journal.py:390` (`cached: bool = False`), `:420` |
| The six completed-call results | `analyze.py:662-675` (parse failure), `:678-690`; `compose.py:690-702`; `evaluate.py:687-699` (default verdict), `:741-753`; `reflect.py:592-604` |
| Results that need no flag | `analyze.py:613-623` (error response); the `except` arms `analyze.py:599`, `compose.py:668`, `evaluate.py:653`, `reflect.py:532`; the attempt row `sub_task.py:588-601`; the optional-step result `:647-654`; the cache-hit and procedural-replay rows, `cached=True` at `cognitive_agent.py:3705`, `:3743` |
| The replay paths | `llm_client.py:1526-1530`, `:2001-2010`: `tokens_used=cached.tokens_used`, `cached=True`, no `usage_reported` (default `None`, `types.py:366`) |
| S1 charges a zero-count replay as an estimate | `token_accounting.py:188-204` |
| `LLMResponse.cached` is a `bool` | `types.py:344` |
| The readers' filter (moved by section 7.1) | `journal.py:849`, `:859`, `:890`, `:913` |
| The AD-617b gate | `proactive.py:794` (`_is_over_token_budget`), `:809-811`, `:824-826`; `set_runtime` `:775-777`; the constructor's keyword-only defaults `:620-626` |
| The usage readers' shapes | `get_token_usage` `journal.py:835-873` (`total_calls`, `total_tokens`); `get_token_usage_since` `:875-897`; `get_token_usage_by` `:899-941` (the group key, `total_calls`, `total_tokens`) |
| `LLMRateConfig(per_agent_hourly_token_cap=...)` | `tests/test_ad617b_per_agent_token_budget.py:14`, `:114` |
| `_PASS_BY_DEFAULT` (the default-verdict premise) | `evaluate.py:354-359` (`score` 1.0, `criteria` `{}`) |
| `extract_json` raises on a reply with no object | `utils/json_extract.py:79` |

## Absence Verified (2026-10-21)

```
CLAIM: the five journal.record sites and one trace site are the only writers
RUN:   Grep "journal\.record\(|\.record_chain_trace\(" src/probos/
FOUND: cognitive_agent.py:3668, :3705, :4487; sub_task.py:586, :657, :715
RUN:   Grep "INTO journal|INTO chain_traces|FROM journal|FROM chain_traces" src/probos/
FOUND: cognitive/journal.py only
HOLDS: yes

CLAIM: nothing reconstructs a ChainExecutionTrace from a row, and only the journal reads the trace
RUN:   Grep "ChainExecutionTrace" src/probos/
FOUND: chain_optimizer.py:3 (docstring), chain_trace.py:1, :15, journal.py:417, sub_task.py:679, :680
HOLDS: yes

CLAIM: no reader of chain_traces rows reads a token field (other than the route, which passes rows through)
RUN:   Grep "tokens_used" src/probos/cognitive/chain_optimizer.py; Grep "tokens" src/probos/cognitive/clinical_telemetry.py; Grep "tokens" src/probos/cognitive/optimization_counselor.py
FOUND: nothing; nothing; nothing
RUN:   Grep "tokens" src/probos/cognitive/diagnostic_context.py
FOUND: its own size estimate (_estimate_tokens, _row_tokens :431-433, the 8000 default :108)
HOLDS: yes

CLAIM: no reader depends on the exact key set of a row
RUN:   Grep "set\(row\)|row\.keys\(\)|set\(trace\)|set\(t\)\b" src/probos/
FOUND: persistent_tasks.py:688, skill_framework.py:1070-1074, threads/__init__.py:1971-1972 (none reads the journal)
HOLDS: yes

CLAIM: no test pins the full column set of journal or chain_traces, or the field set of SubTaskResult / ChainExecutionTrace
RUN:   Grep "PRAGMA table_info\((journal|chain_traces)\)" tests/
FOUND: test_ad492...:166, test_ad658a...:139, :173, test_ad700b...:113, :124, test_replay_dispatch.py:159 (each asserts named columns present, or present once)
RUN:   Grep "fields\(SubTaskResult|fields\(ChainExecutionTrace|asdict\(trace|SubTaskResult\.__dataclass_fields__" tests/
FOUND: nothing
HOLDS: yes

CLAIM: no listener reads the chain-completed event's total
RUN:   Grep "SUB_TASK_CHAIN_COMPLETED|sub_task_chain_completed" src/probos/ ; Grep "sub_task_chain_completed" ui/src/
FOUND: events.py:436, :1117; event_persistence.py:411; sub_task.py:300, :743, :759; nothing in ui/src
HOLDS: yes

CLAIM: no UI caller of the journal or chain-trace routes
RUN:   Grep "api/journal|chain-traces|/reasoning" ui/src/
FOUND: nothing
HOLDS: yes

CLAIM: the new local names are free in the edited functions
RUN:   Grep "\bcharge\b|\banswered\b" src/probos/cognitive/sub_tasks/; Grep "\b_charge\b|token_accounting|answered_model_name|charge_completion|request_messages" src/probos/
FOUND: nothing; nothing (before S1; after S1 only token_accounting.py)
HOLDS: yes

CLAIM: the handler tests' zero-token assertions are on paths that make no model call
RUN:   Grep "assert .*tokens_used == 0" tests/ --glob "test_{bf233,bf204,bf190,bf186,bf187,bf184,bf185,ad645b,ad639,ad632}*.py"
FOUND: ad632b :133, :458 (QUERY), ad632e :413 (suppress), ad632d :204, :216 (SILENT), ad639 :169, :296, :431-432 (low trust), bf184 :80, :99, bf185 :93, :110, bf186 :307, bf187 :135, :165 (social bypass), bf190 :158 (JSON rejection), bf204 :139 (grounding)
HOLDS: yes -- none follows a model call

CLAIM: the AD-617b cap is off by default
RUN:   Grep "per_agent_hourly_token_cap" src/probos/config_models/knowledge.py config/system.yaml src/probos/proactive.py
FOUND: knowledge.py:253 (= 0), system.yaml:2067 (0), proactive.py:809
HOLDS: yes

CLAIM (A1): the six results in 11.1 are every result built from a completed chain call
RUN:   Grep "\.complete\(" src/probos/cognitive/sub_tasks/
FOUND: analyze.py:593, compose.py:662, evaluate.py:643, reflect.py:521 (one call per handler; query.py makes none)
RUN:   Grep "token_source=charge\.source" src/probos/cognitive/sub_tasks/
FOUND: analyze.py:674, :689; compose.py:701; evaluate.py:698, :752; reflect.py:603
HOLDS: yes -- the other results after a call are analyze.py:613 (error response) and the except arms

CLAIM (A1): no code reads a SubTaskResult by its field set
RUN:   Grep "SubTaskResult" src/probos/
FOUND: sub_task.py, sub_tasks/{analyze,compose,evaluate,reflect,query}.py, predictive_branching/executor.py, chain_nats_bridge.py
RUN:   Grep "asdict\(.*result|fields\(SubTaskResult|SubTaskResult\.__dataclass_fields__|vars\(result\)" src/probos/
FOUND: crew_executor.py:2287, :2375; routers/ard.py:522, :536; routers/work.py:89; ward_room/_helpers.py:95; social_verification.py:427, :615 -- none in a file that names SubTaskResult
HOLDS: yes

CLAIM (A1): outside the journal, AD-633 is the only budget that sums chain results' tokens
RUN:   Grep "\.tokens_used\b" src/probos/ (sub_tasks/ excluded)
FOUND: sub_task.py:387 (the event, no listener), :671, :702; chain_nats_bridge.py:192 (observability); the rest in files that do not name SubTaskResult
RUN:   Grep "SubTaskResult|\.cached|tokens_used" src/probos/cognitive/predictive_branching/executor.py
FOUND: :114, :195, :199 (getattr(r, "tokens_used", 0)); no cached
HOLDS: yes -- AD-633 recorded in section 5, off by default

CLAIM (A1): no test pins the step row's keyword set
RUN:   Grep "record\.(call_args|assert_called)" tests/
FOUND: named-key reads only (test_bf183_subtask_retry.py:363-366, :396-398; test_ad632h_parallel_dispatch.py:651, :674; test_ad632c_analyze_handler.py:532-535; test_ad632a_sub_task_foundation.py:435-438, :452-453; the journal and replay suites' one-shot reads)
HOLDS: yes

CLAIM (A1): the handlers' new local name is free
RUN:   Grep "\breplayed\b|\bcached\b" src/probos/cognitive/sub_tasks/
FOUND: nothing
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| srp-size | `CognitiveJournal` (baseline `lines`, `methods`, `architecture-baseline.yaml:562-567`) gains about 15 lines, no method. `SubTaskExecutor` (baseline `lines`, `:641-646`) gains about 8 lines, no method. `CognitiveAgent` (baseline `lines`, `methods`) gains about 12 lines, no method. The handler classes start at `analyze.py:531`, `compose.py:586`, `evaluate.py:366`, `reflect.py:368` and end with their files (676, 691, 740, 593 lines on the base), so each stays well under 500 lines after about 15 added; none gains a method |
| layer-import | No module-scope import added (call-site imports only) |
| A1 (srp-size, layer-import, precheck) | `SubTaskExecutor` (baselined by trigger, `architecture-baseline.yaml:641-648`) gains 1 line, `SubTaskResult` 1 field, no method; the handler classes gain 2 or 3 lines each (about 164, 119, 391 and 239 lines), none near 500 and none gaining a method. No import in `src/`; the test file imports `probos.proactive` and `LLMRateConfig`, as `tests/test_ad617b_per_agent_token_budget.py:14-15` does. The new kwargs sit in mid-call blocks (7.10a), so the precheck's field check (`phantom_api_ast_helper.py:873-875`, `:925-950`), which reads the tree it runs on, sees no `SubTaskResult(...)` call naming `cached` before the build |
| db-connect | No `connect` in `src/` (the test uses `aiosqlite.connect` on `tmp_path`, as `test_ad658a_chain_trace_token_split.py:129` does) |
| unowned-task | None |
| config reference and facade | No config field; `config/system.yaml` untouched |
| seam contracts | `Grep "journal|SubTaskResult|ChainExecutionTrace" docs/development/seams/` finds nothing |
| store registry | No table added; `cognitive.journal`'s declaration (`cognitive/storage_declarations.py:68-90`) lists no columns |
| AD-1343 seam census | No `.complete(` call added; run `tests/test_ad1343_seam_registry.py` (M4) |
| Hidden pins | `test_bf288_log_hygiene.py:104-124` (strings kept); `test_cognitive_journal.py:243` (`cached is False` holds for an `LLMResponse`); the schema pins in section 5 |
| Ledger | M5 |

## 13. What I could not verify here, and Prior Art

- **The 1,272 count** needs, on a **copy** of the vessel's `cognitive_journal.db`: `SELECT dag_node_id LIKE 'st:%', cached, procedure_id<>'', COUNT(*) FROM journal WHERE model='' GROUP BY 1,2,3`. Reading the live data directory is access to the live system: the Captain's, at the next restart (with the consult's other two: one real plain and one real tool-call call through the proxy, capturing the raw `usage` block; and after S2 is deployed, the S3 doctor check).
- **Prior art:** OpenTelemetry's GenAI conventions record the served model (`gen_ai.response.model`) beside the requested one (S1 section 13); adopted as the answered-model row value. No outside analogue for the source column; it is ProbOS's BF-680 provenance.
- **Blind spots named:** a chain step's estimate does not include the per-tier system suffix the transport appends (S1, `request_messages`); a warm boot whose `ALTER` fails for another reason loses that table's inserts silently (pre-existing, section 5); the column's position differs between a fresh and a migrated `journal` (read by name everywhere, section 7.1). A1: a replayed chain step's trace row carries its charge and no `cached` (the table has no such column); spend is the journal's `cached = 0` sum, so S3 must take spend from `journal`, not by summing `chain_traces`.

## 14. Diff Reviewer: properties to verify

1. On a database without the columns, `start()` adds `token_source` to both tables exactly once, and on a second start adds nothing and raises nothing.
2. Each `INSERT` names exactly as many columns as it binds values, in the same order.
3. No write site records an empty `model`: the five `journal.record` calls pass a model that is the answering model, the sent id or `"unknown"`.
4. The one-shot row's `cached` equals the response's `cached`, and its counts and source are the values `charge_completion` returned for that request and response.
5. Each handler's results built from a completed call carry the charge's three counts, its source and the answering model; the handlers' early-return and error results are unchanged.
6. The chain-step row and the trace carry the same `token_source` as the handler's result.
7. `''` is written only where nothing was accounted for; `"measured"` reaches a row only from `charge_completion`'s measured branch.
8. No module-scope import was added to `cognitive_agent.py` or the handlers.
9. `decision` returned by `_decide_via_llm` is unchanged by the journal block.
10. (F1) At each of the six results built from a completed call (analyze parse failure and success, compose, evaluate default verdict and verdict, reflect), `cached` is `getattr(response, "cached", False) is True` for the response that call returned, and the step row's `cached` is `getattr(result, "cached", False) is True`. The row keeps the charge's counts and source. A replayed step adds nothing to `get_token_usage`, `get_token_usage_by`, `get_token_usage_since` or the AD-617b gate, and a fresh step that follows is counted (U11).
11. (F2) No tracker text says that no reader's shape changes: the aggregate readers' shapes are unchanged, the `SELECT *` readers and what serializes them gain `token_source`, and after a revert the retained columns stay visible through `SELECT *` and serialization.
12. (F3) The new test file's docstring claims a real journal only for the tests that use one (not U9 or U12).
13. (F4) Section 5 states its scope and names the transitive consumers found in round 1.
14. (F5, unchanged) The swallowed non-duplicate migration failure is recorded (sections 5, 13, 16), not repaired; A1 does not touch `journal.py`.

## 15. Acceptance criteria

1. A real `CognitiveJournal` records the charge, its source and the answering model for a one-shot call (U1 to U3) and for a chain step (U7, U9).
2. A warm boot on a database without the columns adds them, old rows read `''`, and a second boot is a no-op (U10, J1, J2).
3. No empty `model` at any of the five record sites (U3, U5, U6, U8; C1, C5, C6, S1, S2).
4. A replay row is `cached=1` and adds nothing to `get_token_usage` (U4, C2).
5. Every reader of `journal` and `chain_traces` rows is listed with what it does with the new key and values (section 5), and the schema pins hold (M1).
6. Every mutation row in section 10 is killed by the named assertion.
7. A chain step that replays the client cache is recorded `cached=1` with its charge, and adds nothing to the usage readers or the AD-617b cap (U11, U12; S4, R1 to R10).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-10-21, review round 1 of candidate r1)

Candidate r1 (commit `d10776bc`, tree `8112781c`) was byte-identical to this contract before A1. The Diff Reviewer (`gpt-6.1-sol`) verified section 14's nine properties and returned five findings. S2 is rebuilt from the amended contract on S1's commit: sections 7.1 to 7.10, then 7.10a, then 7.11 as amended.

| F | Severity | Finding | Disposition | Sections |
|---|---|---|---|---|
| F1 | P2 | A chain step that replayed the client cache was journaled `cached=0`, so a zero-count replay, charged as an estimate, entered spend and the AD-617b cap | Fixed: `SubTaskResult.cached`, carried at the six completed-call results and recorded by the step row (D9); U11, U12 and U9's new assertion; rows S4, R1 to R10 | 2, 3, 4, 5, 6, 7.10a, 7.11, 8, 10, 14, 15 |
| F2 | P3 | The trackers said no reader's shape changes, and that nothing reads the columns after a revert | Fixed | 8, 9 |
| F3 | P3 | The test docstring claimed a real journal for U9 | Fixed | 6, 7.11 |
| F4 | doc | Section 5 read as a full census | Scope stated; the transitive consumers named; AD-633 added | 5 |
| F5 | recorded | A non-duplicate migration failure is swallowed (`journal.py:217-220`, `:243-247` on the candidate) | Pre-existing (AD-432, AD-658a), injection-only; recorded, not repaired | 5, 13 |

**What A1 does not change.** No schema change (`journal.cached` exists, `journal.py:35`), no reader change, no new column, file or module-scope import. Sections 7.1, 7.2, 7.4 and 7.6 are unchanged, as are the section 0 anchors and the tracker SEARCH anchors (S1's PROGRESS head and S1's DECISIONS *Reversal* line). S3 reads the same schema.

**Section 11 and Absence Verified.** Their claims on `8c8bc441` stand; A1 adds no writer, so the five `journal.record` sites and one trace site are still the only writers. A1 adds 11.1, re-verified on the candidate, and five Absence claims.

**Considered, deferred.** AD-633's speculative budget counts a replayed result's tokens (section 5). It is off by default. A follow-up can skip results marked `cached`, which needs this field.
