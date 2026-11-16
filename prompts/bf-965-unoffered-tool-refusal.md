# Unoffered tool refusal: the agentic loop refuses any tool call outside the request's offer, on every route -- #1796, one batch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16 (R1: review round 1, findings F1 and F2; section 4, R1). R1 adds eight cases to the new file (24 after R1) and one public function, `without_never_ran_refusals`.
**File in the repository:** `prompts/bf-965-unoffered-tool-refusal.md`. No commit subject or tracker line of this batch carries an `AD-` or `BF-` token, or this file's name (section 5).
**Status:** M0 to M3 build on the head of BF-982 (#1817, section 6, L5), which is built, reviewed and committed first in the same wave, on `origin/main` after batch 1 (#1799, #1802, #1805), #1794 and batch 3 merge. One PR and one broad gate cover both (section 3). Batch 1 and #1794 touch no file this batch edits; the trackers move but their anchors stay. **M0's and M2-F's pairs arrived in parts, and all of Part 3 is in: M0 is N0-1 and P0-2 to P0-259; M2 is P2-1 to P2-47 (P2-1 to P2-23 the guard and the new file, P2-24 onward M2-F).** Part 1 (2026-11-15) holds P0-2 to P0-58 and P2-24 to P2-28. Part 2 holds P0-59 to P0-110 and P2-29. Part 3 holds 3a-1 (P0-111 to P0-208, P2-30 to P2-35), 3a-2 (stage-3 files: P0-209 to P0-242, P2-36 to P2-40), 3b (D-MCP: P0-243 to P0-254, P2-41 to P2-47) and 3c (P0-255 to P0-259: `test_ad1190` and `test_ad1356_s3_chain_of_command`). The Builder starts M0 once BF-982's commits are on the wave branch (head `137a9326`), P0-255 to P0-259 still apply exactly once on that head, and the orchestrator's census rerun on the M2 tree reads only the four failures that predate this change (two in `test_ad1316_real_effect_routes`, two in `ablation/test_sigma_harness_structural`).
**Dependencies:** one in code, BF-982 (#1817, section 6, L5), built first in the same wave on its own commits: under a confinement, the agent-work gate receives the id the executor resolves, not the provider alias the model called. Without it the three CC5 cases of `test_ad1356_s3_chain_of_command.py` fail at G2. **Number:** #1796 is BF-965 (`gh issue view 1796`). Nothing is allocated here.
**Builder:** `claude-sonnet-5.5`; at most about 150 tool calls per milestone; focused tests only; search first, then read the range. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Estimated tests (expected, not measured):** one new file, `tests/test_bf965_unoffered_tool_refusal.py`, with 16 cases: 13 strict xfail at M1 and 3 controls. One new helper, `tests/offered_tools.py`: `offer`, `offer_scripted`, and the D-MCP rig (`OfferedMcpTools`, `offer_mcp`, `McpSearchToolStandIn`). One case is rewritten in place (T4 of `tests/test_bf943_captain_document_write_refusal.py`). The fixture edits are M0's P0-2 onward (offer, or grant, only) and M2-F's P2-24 onward (`offered=` on direct callers; plan-mode, S1.1, AD-1189, department-gate and Captain-restriction cases, and MCP calls that the AD-1241 offer or a correction projection withholds, in Part 3). One passing case, `test_armed_below_threshold_requests_and_results_are_byte_identical`, is offered too: under M2 it passes only because both arms are refused. No test function is removed.

**Base blobs (`5275d008`).**

| File | Blob | Role |
|---|---|---|
| `src/probos/cognitive/swe_harness/agentic_loop.py` | `9e51c15be9439ecd1f6e6c0a534538740c603e0a` | edited (M2) |
| `src/probos/cognitive/agentic_dispatch.py` | `1c1e3ce95b6ba915719ea475c4b3ede165922efd` | edited (M2) |
| `src/probos/cognitive/tool_manifest.py` | `c8948bcbbf9a88f508b0a6b5421ca413d4f1bb27` | edited (M2) |
| `tests/test_bf943_captain_document_write_refusal.py` | `2e4b2c1c7c24b2c0728e610236e6c8330cc4c246` | edited (M2, T4) |
| `PROGRESS.md`, `DECISIONS.md` | `3e87baf3...`, `675bdc29...` | these move when batch 1 and #1794 merge; the M3 anchors stay |

## 1. Problem

See #1796 ("Problem", "Evidence"). Re-derived on `5275d008`:

| Claim | Evidence | Verdict |
|---|---|---|
| The loop hands any model-named tool to the executor | `agentic_loop.py:2684-2710` (`self._executor.invoke(tool_id=use.tool_call.name, ...)`); no name check in `_execute_one_tool` (`:2551-2683`) | Holds |
| The exact offer is the request's `tools` | `agentic_loop.py:1812-1836`; an AD-1324 floor re-issue keeps them (`:1906-1912`, `replace(req, ...)`) | Holds |
| The offer changes inside the run | AD-1240 reader `:1706-1710`; BF-755 refresh `:2265-2288` (after execution, so from the next step) | Holds |
| Only two loops; one call constructor | `AgenticLoop(` only at `agentic_dispatch.py:4121`, `native_builder.py:139`; `ToolCallRequest(` only at `llm_client.py:2428` | Holds |
| *New:* the route's failure list keeps never-ran refusals | `agentic_dispatch.py:4364-4370` builds `tool_failures` from the executed pairs, not from `_defect_outcome`; an unoffered name renders `UNKNOWN_TOOL_LABEL` (`reply_value.py:58-66`, `:106-128`) | A2 as filed cannot hold (D3) |
| *New:* the native builder's fault observer sees raw results | `native_builder.py:181-185` passes `outcome=agentic_result`; `classify_tool_fault_error` (`agentic_dispatch.py:2148-2165`) decides what is noise (`fault_detection.py:32-35`) | A required addition (P2-15). R1: P2-15 reaches only the cross-turn lane, because `collect_tool_fault_batch` counts a same-run defect before its noise filter, so the native observer now reads the run through the DM route's strip (D7) |
| *New:* tests call the private methods directly | `_execute_one_tool(` is called at `test_ad1187_agent_work_pull.py:1032,1047`, `test_ad1224_durable_tool_start.py:870`, `test_ad1261_authority_domain.py:958,1300` | Required edits (M2-F) |

## 2. Solution and decisions

- **D1 (the seam).** Issue design 1 to 6 as filed: the check sits in the loop, not in the executor.
- **D2 (the set).** For each response, `offered` is built from the `function.name` values in `req.tools`, where `req` is the request that produced that response, plus `also_offered()`. It is computed once per step by the module function `_offered_tool_names`, so no method is added to `AgenticLoop` (it has 13 direct methods; the `srp-size` baseline row for it, `architecture-baseline.yaml:649-656`, triggers on `lines` only). If `also_offered` raises, a warning is logged and only the request's own offer is admitted.
- **D3 (A2 amended).** The refusal is never a denial: `denied_tools` is untouched, so AD-855 files nothing. It is never defect or fault evidence: it is added to `_NEVER_RAN_REFUSALS` and to `classify_tool_fault_error`. The DM reply's failure list records the call under `UNKNOWN_TOOL_LABEL`, never under its raw name. This is AD-1248 DD-1a's rule for unoffered names, and the other never-ran refusals already appear there the same way. A2 as filed ("`tool_failures` holds no entry for the call") would need a filter that also changes the reply for the plan-mode, deferred-schema and confinement refusals. Rejected.
- **D4 (AD-1189).** `ToolManifestOffer.loadable_names()` returns `(withheld & last_built) - presented`. That is empty until a build arms the offer, because `_withheld` is set only on arming (`tool_manifest.py:259-263`). `request()` reuses it. `_run_reserved` passes `also_offered` only when a manifest offer exists, so the unarmed constructor keywords that `test_ad1189...:77-89` pins are unchanged.
- **D5 (comments that M2 makes stale).** The plan-mode comment (`agentic_dispatch.py:3600-3602`) and the `withhold_call` docstring (`tool_manifest.py:320-321`) say that the executor resolves unoffered names. Both are updated to say the loop refuses them first and the guards stay as defence in depth.
- **D6 (commit order).** M0 (helper and offer-only fixture edits, no behaviour change) -> M1 (new tests, xfail) -> M2 (guard, T4, M2-F) -> M3 (trackers). The T4 rewrite and the private-caller edits must ride with M2: on the base the loop has no refusal for T4 to assert, and `_execute_one_tool` rejects an `offered=` keyword.
- **D7 (R1, review round 1).** D3's "never defect or fault evidence" needs the strip on every fault observer, not the classification alone: `collect_tool_fault_batch` takes `same_run = detect_tool_defect(outcome)` (`fault_detection.py:266`) before its noise filter (`:315`). The native builder now passes `without_never_ran_refusals(agentic_result)`, the public name R1 gives the strip the DM route applies (`agentic_dispatch.py:4372`, `:4437`). A call whose tool name is not a `str` is refused like any unoffered name, before `in offered` hashes it (the idiom of `agentic_loop.py:730`, `:746`). Rejected: importing the private strip into `native_builder.py` (cross-module private access); moving the strip into `collect_tool_fault_batch` or `observe_completed_tool_run` (a shared public function's behaviour changes for every caller, and the fault layer would need the dispatch layer's refusal texts or a new parameter).
- **Rejected or deferred:**
  - An executor-side allowlist: it would refuse the AD-1240 reader, miss the native builder, and see neither the refresh nor the alias as shown (issue Seam). Rejected.
  - Echoing the requested name, or listing the available tools, in the refusal: the name is attacker-chosen text in the injection case, and the model already has its list. A constant text also keeps the exact-match `_NEVER_RAN_REFUSALS` contract. Rejected.
  - An injection-signal event or counter: considered, deferred (issue Limits).

## 3. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`, run from the repository root.

**The Builder's gates (focused tests only):**
- **G0 (M0):**
  - Before editing, record for each file that M0 edits the result of `PY -m pytest <file> -q -n 0 -p no:randomly`.
  - After M0, run the same command. The counts are identical, because M0 changes no behaviour. Any difference is a stop.
- **G1 (M1):** `PY -m pytest tests/test_bf965_unoffered_tool_refusal.py -q -n 0 -p no:randomly`.
  - **Expected (not measured):** **3 passed, 13 xfailed.**
  - Then set `$env:UNOFFERED_REFUSAL_RUNXFAIL = "1"`, run the file alone, and `Remove-Item Env:UNOFFERED_REFUSAL_RUNXFAIL`. Every xfail case fails at its own `assert`: none at an import, a fixture or a call.
  - An XPASS is a FAIL; report it to the Architect.
- **G2 (M2):**
  - The new file at `-n 0 -p no:randomly`: **16 passed, 0 xfailed** (expected). After R1: **24 passed** (expected).
  - Then, at the repository's default parallelism with `-p no:randomly`: `tests/test_bf943_captain_document_write_refusal.py`, the 70 test files of the consumer census below, and every file that M0 or M2-F edits: 0 failed. A failure under parallel runs is rerun at `-n 0` before it is reported. The wave adds no file to this set: BF-982 adds no test file, `test_ad1356_s1_unknown_tools` is in the census and `test_ad1356_s3_chain_of_command` is an M0 file. G0's base counts are taken on BF-982's final head (after its review repairs R1 and R2), where `test_ad1356_s1_unknown_tools` holds 7 cases, not 2, and `test_ad1356_s3_chain_of_command` holds 10 (its CC5 has five cases).
  - Then `PY -P scripts/check_architecture_principles.py --check`.
  - **Consumer census** (`tests/`): ablation/test_ad1324_tier_choice_ablation, ablation/test_ad1320_budget_awareness_ablation, ablation/test_ad1322_economic_judgment_ablation, test_ad1142_crew_child_compaction, test_ad1146_multiturn_messages, test_ad1147_parallel_tools, test_ad1148_tool_result_bounds, test_ad1151_durable_tool_outputs, test_ad1152_agentic_correlation, test_ad1153_browser_agentic_loop, test_ad1154_approval_inbox, test_ad1156_plan_execute_mode, test_ad1156_plan_mode_containment, test_ad1164_continue_or_ask, test_ad1174_live_tool_progress, test_ad1187_agent_work_pull, test_ad1189_deferred_tool_schemas, test_ad1190_delegation_tree_budget, test_ad1192_owned_steps_dm, test_ad1200_repository_instruction_wire, test_ad1205_fault_paths, test_ad1208_cost_bounded_turns, test_ad1224_durable_tool_start, test_ad1239_mcp_before_the_browser, test_ad1240_tool_result_delivery, test_ad1261_authority_domain, test_ad1279_fault_finds_its_trace, test_ad1316_governed_effect_broker, test_ad1316_real_effect_routes, test_ad1320_agentic_budget_awareness, test_ad1322_economic_judgment_integration, test_ad1324_audit_terminal, test_ad1324_fail_closed, test_ad1324_loop_tier_choice, test_ad1324_redo_iterations, test_ad1324_terminal_context, test_ad1341_s2_inherited_label, test_ad1343_agent_stop_runs, test_ad1346_admission_effect_census, test_ad1346_admission_subprocess_plumbing, test_ad1346_admission_ticket_offers, test_ad1346_admission_ticket_sinks, test_ad1356_s1_unknown_tools, test_ad545_agentic_loop, test_bf680_token_usage_fallback, test_bf697_agentic_final_text_on_max_iterations, test_bf731_captain_llm_lane, test_bf755_mid_turn_tool_discovery, test_bf901_s1_token_accounting, test_bf946_read_only_delivery_failures, test_browser_session_lifecycle, test_issue1421_http_fetch_safe_methods, test_ad546_native_builder_harness, test_ad1126_verified_finalization, test_ad1246_long_run_promotion, test_ad1241_mcp_offer_budget, test_ad1191_delegation_wire, test_ad1257_defect_follows_failure, test_ad1356_s2_tool_effect_table, test_ad856_agentic_dispatch, test_bf948_list_files_read_policy, test_ad1072_agentic_tools, test_ad1258_self_knowledge, test_ad1356_s1_recovery_reads, test_ad859a_agentic_executor, test_bf900_dispatch_claim_keeps_the_park, test_ad1325_completion_chain, test_bf947_multi_call_agent_work, test_ad1323_continue_extension_seam, test_ad1162_captain_session_binding (each `.py`; the last 17 are the stage-3 files of the 2026-11-15 census that fail or hold an inert case; `ablation/test_sigma_harness_structural` stays out: its failure predates this change).
- **G3 (M3):** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. No AD or BF number moves. Any changed number row is a hard stop for the Architect.

**The orchestrator's steps:** the oracle (every SEARCH applies exactly once, in label order), the mutation campaign (section 7, the new file only), then once for the wave, on its final committed head (BF-982's commits, then M0 to M3): `PY scripts/run_test_gate.py --label wave-1817-1796 --receipt logs/gates/wave-1817-1796.receipt.json`. A red test is first rerun focused on BF-982's head to attribute it.

**Harness rule.** No source change to make a test pass, no new skip, no loosened assertion, and nothing that turns the rule off (there is no such keyword). If an expected count differs, stop and report to the Architect.

## 4. The contract

The SEARCH text is LF, ASCII, starts at a line start and matches exactly once in its file, once the earlier blocks for that file have been applied in label order (the four source files are CRLF in a Windows worktree and LF in the index). A label names its file. Every non-ASCII line of the edited files lies outside every SEARCH: `agentic_loop.py:2439`, `:2443` and `:2500` are the nearest; in the test file, `test_bf943...:170` and `:245`.

### M0: fixtures, with no behaviour change (commits first)

This milestone holds N0-1 and P0-2 onward (Part 1: `test_ad1240`, `test_ad1261`, and `test_ad1187` up to its `:1104`). P0-59 onward add Parts 2 and 3.

**N0-1.** New file `tests/offered_tools.py`. It is a plain helper, not a fixture; it is imported as `tests.offered_tools`, as `tests/posix_stat.py` is.

```python
"""The tool offer a scripted model's calls need (#1796).

The agentic loop runs only a call whose name is in the request's offer, so a test whose scripted model calls a tool
must offer that tool. ``offer`` gives the smallest definition the loop reads (``function.name``); a test that holds
the tool's registration offers ``tool_registration_to_llm_definition(registration)`` instead.
"""

from __future__ import annotations

from typing import Any


def offer(*names: str) -> list[dict[str, Any]]:
    """One minimal function definition per name, in order: what the loop matches a called name against."""
    return [
        {"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}
        for name in names
    ]
```

These cover all 252 failures. Two notes on how they work:
- After a promise the AD-1240 reader always arrives as `read_file`, through `delivery_run.offer` (`agentic_loop.py:1752-1756`, `result_offload.py:404-417`). So each pair offers only what the script calls before a promise, plus any non-reader sibling.
- P0-17 is not in the failing list. `test_armed_below_threshold_requests_and_results_are_byte_identical` passes today only because both arms are refused the same way, so it proves nothing. It is offered too, so that it runs its tool again.

**P0-2** (`tests/test_ad1240_tool_result_delivery.py`: import)
SEARCH:
```
from tests.test_ad1147_parallel_tools import _RecordingEmit
```
REPLACE:
```
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1147_parallel_tools import _RecordingEmit
```

**P0-3** (`tests/test_ad1240_tool_result_delivery.py`: `test_original_source_no_copy_full_loop_recovers_through_real_reader`)
SEARCH:
```
        result = await loop.run(
            system_prompt="fixture", user_message="read source", tools=[], context=context,
        )
```
REPLACE:
```
        result = await loop.run(
            system_prompt="fixture", user_message="read source", tools=[*offer(reader)], context=context,  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        )
```

**P0-4** (`tests/test_ad1240_tool_result_delivery.py`: `test_no_unusable_pointer_for_tiny_cap_or_insufficient_iterations`)
SEARCH:
```
        llm_client=llm, tool_executor=executor, max_iterations=iterations,
        tool_result_max_chars=cap, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
        llm_client=llm, tool_executor=executor, max_iterations=iterations,
        tool_result_max_chars=cap, workspace_results=runtime.workspace_results,
    )
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-5** (`tests/test_ad1240_tool_result_delivery.py`: `test_unavailable_owner_is_armed_but_small_outputs_remain_legacy`)
SEARCH:
```
        loop.workspace_results = UnavailableWorkspaceResults()
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
        loop.workspace_results = UnavailableWorkspaceResults()
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-6** (`tests/test_ad1240_tool_result_delivery.py`: `test_source_promise_changed_refuses_then_next_top_level_is_fresh`, first run)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "source_changed"
        assert len(result.tool_calls) == 2 and len(llm.requests) == 2
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "error" and result.error == "source_changed"
        assert len(result.tool_calls) == 2 and len(llm.requests) == 2
```

**P0-7** (`tests/test_ad1240_tool_result_delivery.py`: same test, the fresh run)
SEARCH:
```
        fresh = await next_loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert fresh.stopped_reason == "complete"
```
REPLACE:
```
        fresh = await next_loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert fresh.stopped_reason == "complete"
```

**P0-8** (`tests/test_ad1240_tool_result_delivery.py`: `test_armed_original_reader_preserves_ordinary_line_ranges`)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete"
    assert _last_result(llm.requests[-1]) == expected
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "complete"
    assert _last_result(llm.requests[-1]) == expected
```

**P0-9** (`tests/test_ad1240_tool_result_delivery.py`: `test_original_single_overlarge_line_reports_unrecoverable_window`)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "source_line_too_large"
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "source_line_too_large"
```

**P0-10** (`tests/test_ad1240_tool_result_delivery.py`: `test_reader_offer_refresh_and_compaction_preserve_whole_recovery_groups`; the run holds `registration`, and BF-755's refresh only applies from the next step)
SEARCH:
```
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and compactor.calls == 4
```
REPLACE:
```
    async with _started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=[tool_registration_to_llm_definition(registration)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete" and compactor.calls == 4
```

**P0-11** (`tests/test_ad1240_tool_result_delivery.py`: `test_current_reader_authority_required_without_widening`; `registration` there is `read_file`'s, so `offer` is used)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error"
        assert result.error == ("reader_locked" if denial == "loto" else "reader_unavailable")
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "error"
        assert result.error == ("reader_locked" if denial == "loto" else "reader_unavailable")
```

**P0-12** (`tests/test_ad1240_tool_result_delivery.py`: `test_parallel_delivery_failure_drains_request_order_preserves_producer_error`)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "workspace_unavailable"
    assert [item.id for item in result.tool_results] == ["first", "second"]
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("codebase_query", "codebase_find_tests")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "workspace_unavailable"
    assert [item.id for item in result.tool_results] == ["first", "second"]
```

**P0-13** (`tests/test_ad1240_tool_result_delivery.py`: `test_delegation_body_only_offloaded_evidence_stays_exact`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete"
        original = result.tool_results[0]
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete"
        original = result.tool_results[0]
```

**P0-14** (`tests/test_ad1240_tool_result_delivery.py`: `test_original_source_instructions_reach_next_request_not_workspace_guidance`)
SEARCH:
```
    result = await loop.run(system_prompt="base", user_message="", tools=[], context=context)
```
REPLACE:
```
    result = await loop.run(system_prompt="base", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-15** (`tests/test_ad1240_tool_result_delivery.py`: `test_real_work_pull_receipt_armed_loop_preserves_preadmission_and_inline_exemption`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete"
        stored = await store.get_work_item(item.id)
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("claim_work_item")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete"
        stored = await store.get_work_item(item.id)
```

**P0-16** (`tests/test_ad1240_tool_result_delivery.py`: `test_shared_loop_concurrent_runs_isolate_source_promises`)
SEARCH:
```
        loop.run(system_prompt=label, user_message="", tools=[], context=context)
```
REPLACE:
```
        loop.run(system_prompt=label, user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-17** (`tests/test_ad1240_tool_result_delivery.py`: `test_armed_below_threshold_requests_and_results_are_byte_identical`; passes only because both arms are refused)
SEARCH:
```
            assert (loop.workspace_results is not None) == (owner is not None)  # premise: really armed
            result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
            assert (loop.workspace_results is not None) == (owner is not None)  # premise: really armed
            result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-18** (`tests/test_ad1240_tool_result_delivery.py`: `test_armed_capture_failures_are_truthful_without_retry_or_publication`)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == code
    assert result.tool_results[0].is_error is False and raw.calls == 1
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == code
    assert result.tool_results[0].is_error is False and raw.calls == 1
```

**P0-19** (`tests/test_ad1240_tool_result_delivery.py`: `test_raised_producer_error_retained_recoverable_and_not_logged`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        assert result.tool_results[0].is_error is True and result.tool_results[0].output == canonical
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete" and raw.calls == 1
        assert result.tool_results[0].is_error is True and result.tool_results[0].output == canonical
```

**P0-20** (`tests/test_ad1240_tool_result_delivery.py`: `test_source_recovery_over_canonical_ceiling_refuses_even_with_unbounded_message_cap`; the second call is the promised reader)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "capture_limit"
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("codebase_read_source")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "capture_limit"
```

**P0-21** (`tests/test_ad1240_tool_result_delivery.py`: `test_available_delegation_small_cap_refuses_without_losing_evidence`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        delivered = result.tool_results[0]
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        delivered = result.tool_results[0]
```

**P0-22** (`tests/test_ad1240_tool_result_delivery.py`: `test_owned_recovery_refuses_unconsumable_slice_without_recursive_offload`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        expected = "recovery_slice_too_large" if case == "oversized_slice" else "recovery_iterations_unavailable"
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        expected = "recovery_slice_too_large" if case == "oversized_slice" else "recovery_iterations_unavailable"
```

**P0-23** (`tests/test_ad1240_tool_result_delivery.py`: `test_large_source_subrange_recovers_exact_original_lines_without_copy`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        delivered = result.tool_results[0]
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
        delivered = result.tool_results[0]
```

**P0-24** (`tests/test_ad1240_tool_result_delivery.py`: `test_storage_failure_preserves_producer_without_logging_backend_details`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        code = "workspace_write_failed" if typed else "delivery_unavailable"
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        code = "workspace_write_failed" if typed else "delivery_unavailable"
```

**P0-25** (`tests/test_ad1240_tool_result_delivery.py`: `test_error_outcome_frame_too_small_keeps_error_identity`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        assert result.final_text == "!"
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "error" and result.error == "delivery_frame_too_large"
        assert result.final_text == "!"
```

**P0-26** (`tests/test_ad1240_tool_result_delivery.py`: `test_strict_offload_threshold_uses_canonical_utf8_bytes`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        if size > 12288:
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        if size > 12288:
```

**P0-27** (`tests/test_ad1240_tool_result_delivery.py`: the `_run_promised_alias` helper; one pair for `test_promised_source_alias_refuses`, `..._by_changed_path_resolution_refuses` and both physical-alias tests)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    return result, observed
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    return result, observed
```

**P0-28** (`tests/test_ad1240_tool_result_delivery.py`: `test_fresh_read_error_loop_contract_is_unchanged_by_arming`)
SEARCH:
```
                workspace_results=runtime.workspace_results if armed else None,
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "complete" and result.error == ""
```
REPLACE:
```
                workspace_results=runtime.workspace_results if armed else None,
            ).run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
            assert result.stopped_reason == "complete" and result.error == ""
```

**P0-29** (`tests/test_ad1240_tool_result_delivery.py`: `test_r1_fresh_native_error_preserves_observer_and_consumes_correction_once`)
SEARCH:
```
        workspace_results=runtime.workspace_results if armed else None,
    ).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete" and result.error == "" and not llm.responses
```
REPLACE:
```
        workspace_results=runtime.workspace_results if armed else None,
    ).run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "complete" and result.error == "" and not llm.responses
```

**P0-30** (`tests/test_ad1240_tool_result_delivery.py`: `test_r1_worked_source_call_keeps_lexical_promise_before_target_access`, the promised run)
SEARCH:
```
            result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "error" and result.error == "source_changed"
            assert len(llm.requests) == 2 and len(observed) == 2
```
REPLACE:
```
            result = await loop.run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
            assert result.stopped_reason == "error" and result.error == "source_changed"
            assert len(llm.requests) == 2 and len(observed) == 2
```

**P0-31** (`tests/test_ad1240_tool_result_delivery.py`: same test, the fresh run)
SEARCH:
```
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert fresh.stopped_reason == "complete" and not fresh_llm.responses
```
REPLACE:
```
            ).run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
            assert fresh.stopped_reason == "complete" and not fresh_llm.responses
```

**P0-32** (`tests/test_ad1240_tool_result_delivery.py`: `test_r1_promised_native_read_errors_remain_delivery_refusals_without_fallback`; offering `reader` also offers the `codebase_read_source` recovery call that its `_SameReaderRecovery` makes)
SEARCH:
```
    ).run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "source_changed"
    assert len(llm.requests) == 2 and len(observed) == 2
```
REPLACE:
```
    ).run(system_prompt="", user_message="", tools=[*offer(reader)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "source_changed"
    assert len(llm.requests) == 2 and len(observed) == 2
```

**P0-33** (`tests/test_ad1240_tool_result_delivery.py`: `test_promise_survives_authority_loss_through_the_loop`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert emitted and set(emitted) == {"path", "offset", "limit"}  # premise: the call was emitted before the loss
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file", "event_log_query")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert emitted and set(emitted) == {"path", "offset", "limit"}  # premise: the call was emitted before the loss
```

**P0-34** (`tests/test_ad1240_tool_result_delivery.py`: `test_refused_only_group_makes_no_hook_call_and_still_closes_the_run`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert [call.id for call in result.tool_calls] == ["fixture-call", "recovery"]
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    assert [call.id for call in result.tool_calls] == ["fixture-call", "recovery"]
```

**P0-35** (`tests/test_ad1240_tool_result_delivery.py`: `test_tier_steps_observe_only_the_outcomes_of_a_refused_group`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    # The refused request is never reported to the controller; a sibling's outcome is, and a group
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file", "event_log_query")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "reference_unavailable"
    # The refused request is never reported to the controller; a sibling's outcome is, and a group
```

**P0-36** (`tests/test_ad1240_tool_result_delivery.py`: `test_offer_failure_with_an_untyped_exception_stops_with_reader_unavailable`)
SEARCH:
```
    result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result_delivery(result.tool_results[0]).status == "source"  # premise: a promise was made first
```
REPLACE:
```
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result_delivery(result.tool_results[0]).status == "source"  # premise: a promise was made first
```

**P0-37** (`tests/test_ad1240_tool_result_delivery.py`: `test_terminal_failure_is_selected_by_request_order`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert len(requests) == 2 and opaque.calls == 1  # both requests were issued; the failing one still ran
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file", "codebase_query")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert len(requests) == 2 and opaque.calls == 1  # both requests were issued; the failing one still ran
```

**P0-38** (`tests/test_ad1240_tool_result_delivery.py`: `test_delivered_results_are_never_presented_for_acknowledgement`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "complete" and len(llm.requests) == 4
    # Premise: the loop really offloaded the big result and really recovered a slice of it.
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("codebase_query", "codebase_find_tests")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "complete" and len(llm.requests) == 4
    # Premise: the loop really offloaded the big result and really recovered a slice of it.
```

**P0-39** (`tests/test_ad1240_tool_result_delivery.py`: `test_refusal_before_later_real_error_reaches_correlation`)
- This run goes through `WorkItemAgenticExecutor`, so its offer is the agent's grants (rule A as amended by E4).
- Evidence: `census-26.txt:2834` shows `assert (1 == 1 and 0 == 1)` at `:4018`. That is `failing.calls == 0`: the first `read_file` call was refused.

SEARCH:
```
    await runtime.tool_permission_store.issue_grant(_AGENT_ID, failing.tool_id, ToolPermission.READ)
    received: list[Any] = []
```
REPLACE:
```
    await runtime.tool_permission_store.issue_grant(_AGENT_ID, failing.tool_id, ToolPermission.READ)
    await runtime.tool_permission_store.issue_grant(_AGENT_ID, "read_file", ToolPermission.READ)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered (a dispatch run offers its granted tools).
    received: list[Any] = []
```

**P0-40** (`tests/test_ad1240_tool_result_delivery.py`: `test_armed_self_query_presentation_sites_match_the_unarmed_loop`)
SEARCH:
```
            ).run(system_prompt="", user_message="", tools=[], context=context)
            assert result.stopped_reason == "complete"
            observations.append((asdict(result.tool_results[0]), _last_result(llm.requests[1])))
```
REPLACE:
```
            ).run(system_prompt="", user_message="", tools=[*offer("self_query")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
            assert result.stopped_reason == "complete"
            observations.append((asdict(result.tool_results[0]), _last_result(llm.requests[1])))
```

**P0-41** (`tests/test_ad1240_tool_result_delivery.py`: `test_armed_loop_refuses_a_large_result_without_the_authorized_view`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
    assert result.stopped_reason == "error" and result.error == "workspace_authority_unavailable"
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.stopped_reason == "error" and result.error == "workspace_authority_unavailable"
```

**P0-42** (`tests/test_ad1240_tool_result_delivery.py`: `test_delivery_scope_is_closed_on_every_exit`)
SEARCH:
```
        task = asyncio.create_task(loop.run(system_prompt="", user_message="", tools=[], context=context))
```
REPLACE:
```
        task = asyncio.create_task(loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context))  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-43** (`tests/test_ad1240_tool_result_delivery.py`: `test_ordinary_16k_result_with_the_owned_steps_metadata_key_still_offloads`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        # A metadata key confers no exemption: only the producer's own type does.
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        assert result.stopped_reason == "complete" and raw.calls == 1
        delivery = result_delivery(result.tool_results[0])
        # A metadata key confers no exemption: only the producer's own type does.
```

**P0-44** (`tests/test_ad1240_tool_result_delivery.py`: `test_delivery_remaining_follows_both_ad1208_ceilings`; the names in `_StepLLM.TOOLS`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        names = [call.name for call in result.tool_calls]
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer("http_fetch", "fixture_small", "fixture_large")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        names = [call.name for call in result.tool_calls]
```

**P0-45** (`tests/test_ad1240_tool_result_delivery.py`: `test_delivery_remaining_reaches_every_tool_execution_path`)
SEARCH:
```
        result = await loop.run(system_prompt="", user_message="", tools=[], context=context)
        # The remainder (3, then 2) reached ``prepare_result`` on that path, so the result was
```
REPLACE:
```
        result = await loop.run(system_prompt="", user_message="", tools=[*offer(large_tool)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        # The remainder (3, then 2) reached ``prepare_result`` on that path, so the result was
```

**P0-46** (`tests/test_ad1240_tool_result_delivery.py`: `test_workspace_promise_refuses_replaced_reader_before_invocation`)
SEARCH:
```
            event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[], context=context)
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: the call that was refused printed exactly the published path, which is a real artifact.
```
REPLACE:
```
            event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[*offer(producer.tool_id)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    reference = result_delivery(result.tool_results[0]).reference
    # Premise: the call that was refused printed exactly the published path, which is a real artifact.
```

**P0-47** (`tests/test_ad1240_tool_result_delivery.py`: `test_repeated_slices_of_a_promised_workspace_path_validate_each_time`)
SEARCH:
```
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[], context=context)
    reference = result_delivery(result.tool_results[0]).reference
    first = printed[0][1]
```
REPLACE:
```
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    reference = result_delivery(result.tool_results[0]).reference
    first = printed[0][1]
```

**P0-48** (`tests/test_ad1240_tool_result_delivery.py`: `test_unpromised_artifact_path_keeps_the_typed_fresh_route`, its `run` helper; the second run reads unpromised, so `read_file` is not the reader there)
SEARCH:
```
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[], context=context)

    async with _started(runtime):
```
REPLACE:
```
            structured_tool_messages=structured, workspace_results=store,
        ).run(system_prompt="", user_message="", tools=[*offer("fixture_result", "read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.

    async with _started(runtime):
```

**P0-49** (`tests/test_ad1240_tool_result_delivery.py`: `test_workspace_promise_refuses_the_other_native_reader_before_invocation`; the subject is AD-1240's refusal, so the other reader is offered and the call reaches that refusal again)
SEARCH:
```
            structured_tool_messages=structured, event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
            structured_tool_messages=structured, event_emit_fn=emit, workspace_results=runtime.workspace_results,
        ).run(system_prompt="", user_message="", tools=[*offer("fixture_result", "codebase_read_source")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-50** (`tests/test_ad1261_authority_domain.py`: import)
SEARCH:
```
from tests.test_ad1260_wellness_domain import (
```
REPLACE:
```
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1260_wellness_domain import (
```

**P0-51** (`tests/test_ad1261_authority_domain.py`: `test_loop_r2_retained_text_reaches_next_request_without_third_representation`, `:1046`)
SEARCH:
```
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[],
        context={"agent_id": _SUBJECT, "department": identity.department, "rank": identity.rank},
```
REPLACE:
```
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[*offer("self_query")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        context={"agent_id": _SUBJECT, "department": identity.department, "rank": identity.rank},
```

**P0-52** (`tests/test_ad1261_authority_domain.py`: `test_loop_r2_pre_hook_refusal_without_retention_reaches_next_request_unchanged`, `:1350`)
SEARCH:
```
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[],
        context={"agent_id": _SUBJECT}, fault_capture=capture,
```
REPLACE:
```
        system_prompt="SYS", user_message="Read explicit self domains.", tools=[*offer("self_query")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        context={"agent_id": _SUBJECT}, fault_capture=capture,
```

**P0-53** (`tests/test_ad1187_agent_work_pull.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult, truncate_tool_output
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult, truncate_tool_output
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
```

**P0-54** (`tests/test_ad1187_agent_work_pull.py`: `test_loop_presentation_overwrites_forged_context_and_preserves_next_request`)
SEARCH:
```
    result = await loop.run(system_prompt="SYS", user_message="Task", tools=[], context=context)

    assert len(client.requests) == 2
    assert context["_tool_result_presentation"] is forged
```
REPLACE:
```
    result = await loop.run(system_prompt="SYS", user_message="Task", tools=[*offer(tool_id)], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.

    assert len(client.requests) == 2
    assert context["_tool_result_presentation"] is forged
```

**P0-55** (`tests/test_ad1187_agent_work_pull.py`: `test_loop_concurrent_presentations_are_invocation_local`)
SEARCH:
```
        asyncio.create_task(loop.run(
            system_prompt="SYS", user_message="Task", tools=[], context={"agent_id": "agent-a"},
        ))
```
REPLACE:
```
        asyncio.create_task(loop.run(
            system_prompt="SYS", user_message="Task", tools=[*offer("claim_work_item")], context={"agent_id": "agent-a"},  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        ))
```

**P0-56** (`tests/test_ad1187_agent_work_pull.py`: `test_loop_presentation_exact_render_fit_and_frozen_carrier`)
SEARCH:
```
    await loop.run(system_prompt="SYS", user_message="Task", tools=[], context={"agent_id": "agent-a"})
    carrier = executor.contexts[0]["_tool_result_presentation"]
```
REPLACE:
```
    await loop.run(system_prompt="SYS", user_message="Task", tools=[*offer("discover_work_items")], context={"agent_id": "agent-a"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    carrier = executor.contexts[0]["_tool_result_presentation"]
```

**P0-57** (`tests/test_ad1187_agent_work_pull.py`: `test_loop_other_tools_keep_existing_context`)
SEARCH:
```
    result = await AgenticLoop(llm_client=client, tool_executor=_OtherExecutor()).run(
        system_prompt="SYS", user_message="Task", tools=[], context=context,
    )
```
REPLACE:
```
    result = await AgenticLoop(llm_client=client, tool_executor=_OtherExecutor()).run(
        system_prompt="SYS", user_message="Task", tools=[*offer("other_tool")], context=context,  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    )
```

**P0-58** (`tests/test_ad1187_agent_work_pull.py`: the shared `_invoke_pull` helper; one pair covers the `test_claim_description_*`, `test_claim_tiny_cap_*`, replay, discovery and pull cases whose tracebacks land at `:1128` and `:1184`)
SEARCH:
```
        system_prompt="Choose work; read the ownership receipt.", user_message="Task",
        tools=[], context={
```
REPLACE:
```
        system_prompt="Choose work; read the ownership receipt.", user_message="Task",
        tools=[*offer(tool_id)], context={  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

`_dispatch_runtime` is synchronous, and grants are per agent and async (`permissions.py:110`). So one async helper builds a granting store, and each dispatch site passes it in. The dispatch never copies the runtime's store into the registry; only `startup/communication.py:833` and `crew_verifier.py:1248` call `set_permission_store`. So a READ grant on the runtime store changes the offer and nothing else.

**P0-59** (`tests/test_ad1224_durable_tool_start.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult

_SECRET = "sk-live-511dd0ec-DO-NOT-LOG-THIS-VALUE"
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.

_SECRET = "sk-live-511dd0ec-DO-NOT-LOG-THIS-VALUE"
```

**P0-60** (`tests/test_ad1224_durable_tool_start.py`: `test_agentic_loop_mints_a_run_id_per_run`, `:611-613`)
SEARCH:
```
    await loop.run(system_prompt="s", user_message="u", tools=[], context=caller_context)
    llm.calls = 0
    await loop.run(system_prompt="s", user_message="u", tools=[], context=caller_context)
```
REPLACE:
```
    await loop.run(system_prompt="s", user_message="u", tools=[*offer("read_file")], context=caller_context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    llm.calls = 0
    await loop.run(system_prompt="s", user_message="u", tools=[*offer("read_file")], context=caller_context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-61** (`tests/test_ad1224_durable_tool_start.py`: the new helper)
SEARCH:
```
        emit_event=None, event_log=event_log,
    )


async def _run_dispatch(*, log: Any, hang: bool) -> tuple[asyncio.Task[Any], _DispatchTool]:
```
REPLACE:
```
        emit_event=None, event_log=event_log,
    )


async def _offering_store(agent_id: str, *tool_ids: str) -> Any:
    """#1796: a dispatch run offers the tools its agent is granted, so a test grants the tools its scripted model calls."""
    from probos.tools.permissions import ToolPermissionStore

    store = ToolPermissionStore()
    for tool_id in tool_ids:
        await store.issue_grant(agent_id, tool_id, ToolPermission.READ)
    return store


async def _run_dispatch(*, log: Any, hang: bool) -> tuple[asyncio.Task[Any], _DispatchTool]:
```

**P0-62** (`tests/test_ad1224_durable_tool_start.py`: `_run_dispatch`; covers the cancelled-mid-tool and completes tests, `:977`)
SEARCH:
```
        runtime=_dispatch_runtime(registry=registry, event_log=log),
        department="counseling", rank="ensign", thread_id="thread-bf731",
```
REPLACE:
```
        runtime=_dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("counselor-001", "dispatch_probe")),  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
        department="counseling", rank="ensign", thread_id="thread-bf731",
```

**P0-63** (`tests/test_ad1224_durable_tool_start.py`: `test_dispatch_run_denied_tool_closes_its_own_pairing`; A, with a NONE grant)
SEARCH:
```
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
```
REPLACE:
```
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    await perm_store.issue_grant("counselor-001", "dispatch_probe", ToolPermission.NONE)  # #1796: the loop runs only offered tools; a grant offers it, and a NONE grant leaves the registry's rank-gate denial (this case's subject) unchanged.
```

**P0-64** (`tests/test_ad1224_durable_tool_start.py`: `test_dispatch_executor_preserves_hook_set_and_bus_frequency`)
SEARCH:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.emit_event = lambda event, _payload: emitted.append(event)
```
REPLACE:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("counselor-001", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    runtime.emit_event = lambda event, _payload: emitted.append(event)
```

**P0-65** (`tests/test_ad1224_durable_tool_start.py`: `test_active_exhausted_loop_is_not_readmitted_after_257_other_runs`, the parent run)
SEARCH:
```
        system_prompt="s", user_message="u", tools=[], context={"agent_id": "parent"},
```
REPLACE:
```
        system_prompt="s", user_message="u", tools=[*offer("read_file")], context={"agent_id": "parent"},  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-66** (`tests/test_ad1224_durable_tool_start.py`: same test, the 257 other runs)
SEARCH:
```
                system_prompt="s", user_message="u", tools=[], context={"agent_id": f"other-{index}"},
```
REPLACE:
```
                system_prompt="s", user_message="u", tools=[*offer("read_file")], context={"agent_id": f"other-{index}"},  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-67** (`tests/test_ad1224_durable_tool_start.py`: `test_overlapping_parallel_bodies_keep_durable_chain_and_pairing[False]`)
SEARCH:
```
        ).run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "parallel-agent"}), timeout=15)
```
REPLACE:
```
        ).run(system_prompt="s", user_message="u", tools=[*offer(*names)], context={"agent_id": "parallel-agent"}), timeout=15)  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-68** (`tests/test_ad1224_durable_tool_start.py`: `test_conversational_agent_uses_real_dispatch_registry_and_durable_log`)
SEARCH:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True)
```
REPLACE:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("conversation-agent", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    runtime.config.dm_agentic = DmAgenticConfig(enabled=True)
```

**P0-69** (`tests/test_ad1224_durable_tool_start.py`: `test_crew_outer_loop_passes_real_work_item_provenance_to_dispatch`)
SEARCH:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    crew = CrewTaskExecutor(
```
REPLACE:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("crew-agent", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    crew = CrewTaskExecutor(
```

**P0-70** (`tests/test_ad1224_durable_tool_start.py`: `test_promoted_conversational_continuation_links_late_work_item`)
SEARCH:
```
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_block_inside_tool)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
```
REPLACE:
```
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=False, on_invoke=_block_inside_tool)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("conversation-agent", "dispatch_probe", "post_promotion_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-71** (`tests/test_ad1224_durable_tool_start.py`: `test_promoted_interrupted_tool_reopens_with_unique_run_link`)
SEARCH:
```
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=True, on_invoke=_observe_start)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
```
REPLACE:
```
    first_tool = _DispatchTool("dispatch_probe", entered=asyncio.Event(), hang=True, on_invoke=_observe_start)
    later_tool = _DispatchTool("post_promotion_probe", entered=asyncio.Event(), hang=False)
    registry = ToolRegistry()
    registry.register(first_tool)
    registry.register(later_tool)
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("conversation-agent", "dispatch_probe", "post_promotion_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-72** (`tests/test_ad1224_durable_tool_start.py`: `test_promotion_diagnostic_failures_preserve_registry_chain`, 24 cases). The registry holds no permission store, so the `denied` and `loto` outcomes keep their denials.
SEARCH:
```
        assert registry.acquire_lock("dispatch_probe", "other-agent", reason="test lock")
    runtime = _dispatch_runtime(registry=registry, event_log=log)
```
REPLACE:
```
        assert registry.acquire_lock("dispatch_probe", "other-agent", reason="test lock")
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("diagnostic-agent", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools (the registry holds no store, so denied/loto stay denied).
```

**P0-73** (`tests/test_ad1224_durable_tool_start.py`: `test_diagnostic_cancellation_propagates_without_a_synthetic_completion`)
SEARCH:
```
            runtime=_dispatch_runtime(registry=registry, event_log=log), **kwargs,
```
REPLACE:
```
            runtime=_dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("agent-1", "dispatch_probe")), **kwargs,  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-74** (`tests/test_ad1224_durable_tool_start.py`: `test_promotion_link_diagnostic_boundaries_preserve_execution_and_reporting`, 23 cases)
SEARCH:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log)
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    original_create = store.create_work_item
    original_merge = store.merge_work_item_metadata
```
REPLACE:
```
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("diagnostic-agent", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    runtime.work_item_store = store
    runtime.chat_thread_store = threads
    original_create = store.create_work_item
    original_merge = store.merge_work_item_metadata
```

**P0-75** (`tests/test_ad1224_durable_tool_start.py`: `test_promotion_provenance_is_inert_without_event_log`)
SEARCH:
```
    runtime = _dispatch_runtime(registry=registry, event_log=None)
```
REPLACE:
```
    runtime = _dispatch_runtime(registry=registry, event_log=None, perm_store=await _offering_store("conversation-agent", "dispatch_probe"))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-76** (`tests/test_ad1224_durable_tool_start.py`: `test_promotion_provenance_isolated_between_turns_and_passes`)
SEARCH:
```
    monkeypatch.setattr(store, "create_work_item", _create_after_overlap)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
```
REPLACE:
```
    monkeypatch.setattr(store, "create_work_item", _create_after_overlap)
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("conversation-agent", *(name for label in labels for name in names[label])))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-77** (`tests/test_ad1224_durable_tool_start.py`: `test_promotion_link_samples_run_at_publication`)
SEARCH:
```
    monkeypatch.setattr(store, "create_work_item", _create_during_continuation)
    runtime = _dispatch_runtime(registry=registry, event_log=log)
```
REPLACE:
```
    monkeypatch.setattr(store, "create_work_item", _create_during_continuation)
    runtime = _dispatch_runtime(registry=registry, event_log=log, perm_store=await _offering_store("conversation-agent", *tools))  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-78** (`tests/test_ad1224_durable_tool_start.py`: `test_loop_run_observer_receives_only_actual_valid_identity_before_execution`, 8 cases)
SEARCH:
```
        system_prompt="Test instructions.", user_message="Use the probe", tools=[], context=context,
```
REPLACE:
```
        system_prompt="Test instructions.", user_message="Use the probe", tools=[*offer("dispatch_probe")], context=context,  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```


The fix point is the shared helpers `_run` and `_dm`, plus 8 direct sites. `_observer_runtime` is synchronous and has about 30 callers, so the grant lives in the async helpers instead.

The new helper `_offer_tools` grants only registered, non-MCP tools, and only when the agent has no grant for that tool yet:
- MCP is skipped because grants never offer MCP (`agentic_dispatch.py:3087-3088`).
- In `_run`, only the tools the script calls are granted. That keeps it away from the projected `_SessionPermissionStore` (`crew_verifier.py:305`, `:1040`), whose script calls only the MCP alias.
- It does change the offer order in one place: from the second `_run` onward, `run_python` is granted as well as offered by `exec_ids`. No test in the file asserts request tools; only `:1820` reads `r.tools`, and that is an arm-to-arm equality.

**P0-79** (`tests/test_ad1205_fault_paths.py`: import)
SEARCH:
```
from tests.test_ad1066_code_execution_tool import (
    _ctx, _loop_runtime, _runtime, _tool_use,
)
```
REPLACE:
```
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1066_code_execution_tool import (
    _ctx, _loop_runtime, _runtime, _tool_use,
)
```

**P0-80** (`tests/test_ad1205_fault_paths.py`: `_offer_tools` and `_run`; covers the 33 failing `_run` cases)
SEARCH:
```
async def _run(runtime, responses, **kwargs) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses)).run(
```
REPLACE:
```
async def _offer_tools(runtime, agent_id, called=None) -> None:
    """#1796: a dispatch run offers the tools its agent is granted, so the fixture grants the registered tools its
    scripted model calls (by id or provider alias; every registered tool when ``called`` is None). An MCP tool is
    offered by the AD-1241 workbench, never by a grant, so it is skipped; a tool the agent already holds is left alone."""
    for tool_id in runtime.tool_registry.list_ids():
        if tool_id.startswith("mcp:") or (
            called is not None and tool_id not in called and llm_function_name(tool_id) not in called
        ):
            continue
        if not runtime.tool_permission_store.get_active_grants_sync(agent_id, tool_id):
            await runtime.tool_permission_store.issue_grant(agent_id, tool_id, ToolPermission.READ)


async def _run(runtime, responses, **kwargs) -> WorkItemAgenticOutcome:
    await _offer_tools(runtime, "counselor-ezri", {  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        block.tool_call.name for response in responses for block in getattr(response, "content_blocks", ())
        if isinstance(block, ToolUseBlock)
    })
    return await WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses)).run(
```

**P0-81** (`tests/test_ad1205_fault_paths.py`: `_dm`; covers the 6 `_dm` cases)
SEARCH:
```
async def _dm(agent, raw="Captain raw request") -> str:
    return await CognitiveAgent._maybe_run_conversational_agentic(
```
REPLACE:
```
async def _dm(agent, raw="Captain raw request") -> str:
    await _offer_tools(agent._runtime, agent.id)  # #1796: the loop runs only offered tools, so the fixture's tools are offered.
    return await CognitiveAgent._maybe_run_conversational_agentic(
```

**P0-82** (`tests/test_ad1205_fault_paths.py`: `test_direct_executor_observes_all_returned_stop_reasons`)
SEARCH:
```
        outcome = await WorkItemAgenticExecutor(llm_client=_LLM(responses)).run(
```
REPLACE:
```
        await _offer_tools(runtime, "counselor-ezri", {tool.tool_id})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        outcome = await WorkItemAgenticExecutor(llm_client=_LLM(responses)).run(
```

**P0-83** (`tests/test_ad1205_fault_paths.py`: `test_delegated_real_parent_child_loops_file_child_fault_and_preserve_evidence`; the child `bashir-1` calls the tool, `:1043`)
SEARCH:
```
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    runtime.fault_report_store = store
```
REPLACE:
```
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    runtime.fault_report_store = store
    await runtime.tool_permission_store.issue_grant("bashir-1", tool.tool_id, ToolPermission.READ)  # #1796: the loop runs only offered tools; the delegated child's run offers its granted tools.
```

**P0-84** (`tests/test_ad1205_fault_paths.py`: `test_real_crew_outer_passes_share_child_turn_and_preserve_plan_and_fourteen_keys`; the agent is `_FakeAgent("a1")`)
SEARCH:
```
    runtime.tool_registry.register(progress, provider="test", default_permissions={"ensign": "read"})
```
REPLACE:
```
    runtime.tool_registry.register(progress, provider="test", default_permissions={"ensign": "read"})
    await _offer_tools(runtime, "a1")  # #1796: the loop runs only offered tools, so the fixture's tools are offered.
```

**P0-85** (`tests/test_ad1205_fault_paths.py`: `test_real_dm_fault_attempted_uses_only_exact_raw_key`, 5 cases)
SEARCH:
```
    agent = _agent(runtime)
    params = {
```
REPLACE:
```
    agent = _agent(runtime)
    await _offer_tools(runtime, agent.id)  # #1796: the loop runs only offered tools, so the fixture's tools are offered.
    params = {
```

**P0-86** (`tests/test_ad1205_fault_paths.py`: `test_legacy_dm_raw_selection_and_explicit_exhaustion_override`, 10 cases)
SEARCH:
```
    agent = _agent(runtime)
    agent._llm_client = _ScriptedLLM([
        _use_with_text(tool.tool_id, "Partial evidence"),
```
REPLACE:
```
    agent = _agent(runtime)
    await _offer_tools(runtime, agent.id)  # #1796: the loop runs only offered tools, so the fixture's tools are offered.
    agent._llm_client = _ScriptedLLM([
        _use_with_text(tool.tool_id, "Partial evidence"),
```

**P0-87** (`tests/test_ad1205_fault_paths.py`: `test_raw_capture_preserves_result_transcript_and_event_bytes`; both arms get the same offer, so `values[0] == values[1]` still holds)
SEARCH:
```
            system_prompt="Instructions", user_message="Task", tools=[], context={"agent_id": "agent"},
```
REPLACE:
```
            system_prompt="Instructions", user_message="Task", tools=[*offer("fixture")], context={"agent_id": "agent"},  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-88** (`tests/test_ad1205_fault_paths.py`: `test_parallel_capture_follows_request_identity_not_completion_order`)
SEARCH:
```
        system_prompt="", user_message="", tools=[], context={"agent_id": "agent"},
        fault_capture=capture,
```
REPLACE:
```
        system_prompt="", user_message="", tools=[*offer("web_search", "read_page", "write_file")], context={"agent_id": "agent"},  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        fault_capture=capture,
```

**P0-89** (`tests/test_ad1205_fault_paths.py`: `test_reused_executor_owns_distinct_captures_for_overlapping_runs[shared]`)
SEARCH:
```
    else:
        executor = WorkItemAgenticExecutor(llm_client=llm)
```
REPLACE:
```
    else:
        await _offer_tools(runtime, "agent", {"read_file"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        executor = WorkItemAgenticExecutor(llm_client=llm)
```

**Not covered: `test_mcp_confirmation_is_neutral_through_real_shared_loop` x2, `test_real_governed_fault_chain_neutral_turn_privacy_and_one_approval[*-mcp]` x8, and the inert `test_adapter_query_projection_limits_aliases_and_current_registration`.** I put these in a new group, D-MCP (section 3). An MCP alias reaches the model only through the AD-1241 offer (`agentic_dispatch.py:3105-3138`):
- The preload offers OPEN-risk tools only (`mcp_workbench.py:928-945`).
- So a CONFIRM-risk adapter can be offered only after a `find_mcp_tool` selection.

Part 3b covers them (P0-243 to P0-247) without a real workbench or a new script: `offer_mcp` arms the run's AD-1241 offer with a source that admits the fixture's own adapter, as a `find_mcp_tool` pull does (`mcp_workbench.py:1130`), so the adapter, its risk store and the script stay as they are.


**P0-90** (`tests/test_ad1152_agentic_correlation.py`: import)
SEARCH:
```
from tests import test_ad1125_room_bound_execution as room
from tests.test_ad1258_self_knowledge import _OfferSysProxy
```
REPLACE:
```
from tests import test_ad1125_room_bound_execution as room
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1258_self_knowledge import _OfferSysProxy
```

**P0-91** (`tests/test_ad1152_agentic_correlation.py`: `_off_observation`, Category D; covers `test_default_off_matches_pinned_base` and `..._descriptor_owner_platform[linux|win32]`)
SEARCH:
```
            system_prompt="sys", user_message="task", tools=[], context=context,
            on_run_started=callbacks.append,
        )
```
REPLACE:
```
            system_prompt="sys", user_message="task", tools=[*offer("read_page")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
            on_run_started=callbacks.append,
        )
        # #1796: the offer was added after this capture. Each request carried exactly it; the captured requests carried
        # none, so that value is restored and every other byte stays compared with the golden.
        assert [request["request"]["tools"] for request in client.requests] == [offer("read_page")] * 2
        for request in client.requests:
            request["request"]["tools"] = []
```
(The loop passes `tools=tools` through unchanged, `agentic_loop.py:1863,1878`, and `_ScriptedClient` records `asdict(request)`, `:128`. The two `asserts` that follow, `:361-362`, then run on unchanged data.)

**P0-92** (`tests/test_ad1152_agentic_correlation.py`: `:705`)
SEARCH:
```
            system_prompt=name, user_message="task", tools=[], context=incoming,
```
REPLACE:
```
            system_prompt=name, user_message="task", tools=[*offer("read_page")], context=incoming,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-93** (`tests/test_ad1152_agentic_correlation.py`: `:791`; the script calls `unknown` too, and every call ran at base, `:802`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a"},
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("write_file", "read_page", "unknown")], context={"agent_id": "a"},  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-94** (`tests/test_ad1152_agentic_correlation.py`: `:819`)
SEARCH:
```
                    system_prompt="inner", user_message="nested", tools=[],
```
REPLACE:
```
                    system_prompt="inner", user_message="nested", tools=[*offer("read_page")],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-95** (`tests/test_ad1152_agentic_correlation.py`: `:827`)
SEARCH:
```
        system_prompt="outer", user_message="task", tools=[],
```
REPLACE:
```
        system_prompt="outer", user_message="task", tools=[*offer("read_page")],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-96** (`tests/test_ad1152_agentic_correlation.py`: `:858`)
SEARCH:
```
            system_prompt=name, user_message=name, tools=[], context=incoming,
```
REPLACE:
```
            system_prompt=name, user_message=name, tools=[*offer("read_page")], context=incoming,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-97** (`tests/test_ad1152_agentic_correlation.py`: `:915`)
SEARCH:
```
        ]), _ToolRecorder(),
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        ]), _ToolRecorder(),
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-98** (`tests/test_ad1152_agentic_correlation.py`: `:938`)
SEARCH:
```
        _FailedTools(), parallel_tool_calls_enabled=parallel,
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        _FailedTools(), parallel_tool_calls_enabled=parallel,
    )
    result = await loop.run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-99** (`tests/test_ad1152_agentic_correlation.py`: `:962`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[], context={},
        on_run_started=ids.append,
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={},  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        on_run_started=ids.append,
```

**P0-100** (`tests/test_ad1152_agentic_correlation.py`: `:1002`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[], context={},
    ))
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={},  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
    ))
```

**P0-101** (`tests/test_ad1152_agentic_correlation.py`: `:1040`; also fixes the 2 inert `sink` cases)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[], context={}, on_run_started=ids.append,
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={}, on_run_started=ids.append,  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-102** (`tests/test_ad1152_agentic_correlation.py`: `:1121`)
SEARCH:
```
                system_prompt=name, user_message="task", tools=[],
                context={"agent_id": "same", "_agentic_run_id": "inherited"},
```
REPLACE:
```
                system_prompt=name, user_message="task", tools=[*offer("read_page")],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
                context={"agent_id": "same", "_agentic_run_id": "inherited"},
```


**P0-103** (`tests/test_ad1187_agent_work_pull.py`: `test_pull_invalid_actual_loop_bounds_refuse_before_mutation`, the 2 inert cases). The subject is the tool's own bounds refusal, which the loop's refusal had replaced.
SEARCH:
```
        tool_result_head_chars=-1,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[],
```
REPLACE:
```
        tool_result_head_chars=-1,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[*offer(tool_id)],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-104** (`tests/test_ad1187_agent_work_pull.py`: `test_provider_failure_after_commit_recovers_by_exact_id_replay`)
SEARCH:
```
        structured_tool_messages=True,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[],
```
REPLACE:
```
        structured_tool_messages=True,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[*offer("claim_work_item")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```



**P0-105** (`tests/test_ad1147_parallel_tools.py`: import)
SEARCH:
```
from probos.types import LLMRequest, LLMResponse

_MUTATING_TOOL_IDS = ("run_python", "write_file", "edit_file", "run_command")
```
REPLACE:
```
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.

_MUTATING_TOOL_IDS = ("run_python", "write_file", "edit_file", "run_command")
```

**P0-106** (`tests/test_ad1147_parallel_tools.py`: `test_ad1147`: the `_run` helper; 8 failing and 3 inert cases)
SEARCH:
```
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
```
REPLACE:
```
        user_message="do it",
        tools=[*offer(*names)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "agent-1"},
```

**P0-107** (`tests/test_ad1147_parallel_tools.py`: `test_ad1147`: hanging test 1; `while executor.in_flight < 2` at `:527` never ends while both calls are refused)
SEARCH:
```
    """Acceptance: CancelledError propagates and no tool task is left pending."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[],
```
REPLACE:
```
    """Acceptance: CancelledError propagates and no tool task is left pending."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[*offer("web_search", "read_page")],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-108** (`tests/test_ad1147_parallel_tools.py`: `test_ad1147`: hanging test 2)
SEARCH:
```
    """DD-5: the run must not complete with cancellation-shaped tool output."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[],
```
REPLACE:
```
    """DD-5: the run must not complete with cancellation-shaped tool output."""
    client = _CapturingClient(
        responses=[_tool_response("web_search", "read_page"), _final_response()]
    )
    executor = _TimingExecutor(default_delay=5.0)
    loop = AgenticLoop(
        llm_client=client,  # type: ignore[arg-type]
        tool_executor=executor,  # type: ignore[arg-type]
        parallel_tool_calls_enabled=True,
    )
    task = asyncio.create_task(
        loop.run(
            system_prompt="sys",
            user_message="go",
            tools=[*offer("web_search", "read_page")],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-109** (`tests/test_ad1316_governed_effect_broker.py`: import)
SEARCH:
```
from tests.test_ad1315_protected_execution_authority import (
```
REPLACE:
```
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1315_protected_execution_authority import (
```

**P0-110** (`tests/test_ad1316_governed_effect_broker.py`: `test_agentic_loop_parallel_swapped_completion_crosses_broker`, the third hanging test). `http_fetch` stays offered, because its subject is a denial by a pre-hook after the offer (`:614-617`).
SEARCH:
```
        user_message="run both",
        tools=[],
```
REPLACE:
```
        user_message="run both",
        tools=[*offer("web_search", "read_page", "http_fetch")],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**How to check they no longer hang:** run the three nodeids with `PY -m pytest <nodeids> -q -n 0 -p no:randomly --timeout=60`. Expected: 3 passed. Then put them back into the census run, so nothing is deselected. `test_ad1322`'s two `_cancel_scenario` cases also timed out at 5 s (a TimeoutError, not a hang); P0-167 covers them.

**P0-111** (`tests/offered_tools.py`: `offer_scripted`, the shared helper for scripts passed as data)
SEARCH:
```
from __future__ import annotations

from typing import Any


def offer(*names: str) -> list[dict[str, Any]]:
    """One minimal function definition per name, in order: what the loop matches a called name against."""
    return [
        {"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}
        for name in names
    ]
```
REPLACE:
```
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from probos.cognitive.swe_harness.tool_call import ToolUseBlock


def offer(*names: str) -> list[dict[str, Any]]:
    """One minimal function definition per name, in order: what the loop matches a called name against."""
    return [
        {"type": "function", "function": {"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}}
        for name in names
    ]


def offer_scripted(responses: Iterable[Any]) -> list[dict[str, Any]]:
    """``offer`` for every name a scripted model's responses call, first call first and each once.

    For a helper that receives its script as data. An empty name is skipped: the loop never offers one.
    """
    names = dict.fromkeys(
        block.tool_call.name
        for response in responses
        for block in (getattr(response, "content_blocks", None) or ())
        if isinstance(block, ToolUseBlock) and block.tool_call.name
    )
    return offer(*names)
```

**P0-112** (`tests/test_ad1174_live_tool_progress.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
```
REPLACE:
```
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.
from probos.tools.registry import ToolRegistry
```

**P0-113** (`tests/test_ad1174_live_tool_progress.py`: import `offer`)
SEARCH:
```
from tests import test_ad1224_durable_tool_start as durable
from tests.test_ad1224_durable_tool_start import conversation_stores, open_log  # noqa: F401
```
REPLACE:
```
from tests import test_ad1224_durable_tool_start as durable
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1224_durable_tool_start import conversation_stores, open_log  # noqa: F401
```

**P0-114** (`tests/test_ad1174_live_tool_progress.py`: `test_on_thread_identity_is_exact_strict_bounded`, 16 cases)
SEARCH:
```
    await loop.run(system_prompt="sys", user_message="task", tools=[], context=context)
```
REPLACE:
```
    await loop.run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context=context)  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-115** (`tests/test_ad1174_live_tool_progress.py`: `test_off_valid_thread_does_not_change_payload_or_cardinality`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[],
        context={"agent_id": "agent", "thread_id": "authoritative"},
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        context={"agent_id": "agent", "thread_id": "authoritative"},
```

**P0-116** (`tests/test_ad1174_live_tool_progress.py`: `test_overlapping_runs_capture_thread_before_delayed_emission`)
SEARCH:
```
        system_prompt=context["thread_id"], user_message="task", tools=[], context=context,
```
REPLACE:
```
        system_prompt=context["thread_id"], user_message="task", tools=[*offer("read_page")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-117** (`tests/test_ad1174_live_tool_progress.py`: `test_real_conversation_live_start_precedes_completion_and_matches_durable_run`, 4 cases; the DM route)
SEARCH:
```
    runtime.tool_registry = registry
    runtime.tool_permission_store = ToolPermissionStore()
```
REPLACE:
```
    runtime.tool_registry = registry
    runtime.tool_permission_store = ToolPermissionStore()
    await runtime.tool_permission_store.issue_grant("conversation-agent", "dispatch_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-118** (`tests/test_ad1174_live_tool_progress.py`: `test_cancellation_retains_only_started_observation`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[],
        context={"agent_id": "a", "thread_id": "cancel-room"},
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        context={"agent_id": "a", "thread_id": "cancel-room"},
```

**P0-119** (`tests/test_ad1208_cost_bounded_turns.py`: imports)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.workforce import WorkItem

from tests.test_ad706_browser_tool import _FakePage, _make_session_factory
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.workforce import WorkItem

from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad706_browser_tool import _FakePage, _make_session_factory
```

**P0-120** (`tests/test_ad1208_cost_bounded_turns.py`: `_fifteen_fetch_turn`, the two M1 DM-turn cases)
SEARCH:
```
        text = await CognitiveAgent._maybe_run_conversational_agentic(
            agent,
            {"intent": "direct_message", "params": {}},
            system_prompt="You are Ezri. " + "s" * 8000,
```
REPLACE:
```
        await agent._runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
        text = await CognitiveAgent._maybe_run_conversational_agentic(
            agent,
            {"intent": "direct_message", "params": {}},
            system_prompt="You are Ezri. " + "s" * 8000,
```

**P0-121** (`tests/test_ad1208_cost_bounded_turns.py`: `_run_loop`, 19 cases. The parametrized `""` case stays refused because the loop never offers an empty name; it asserts only the stop.)
SEARCH:
```
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message="Research the packages.",
        tools=[],
```
REPLACE:
```
    result = await loop.run(
        system_prompt="You are Ezri.",
        user_message="Research the packages.",
        tools=[*offer_scripted(responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-122** (`tests/test_ad1208_cost_bounded_turns.py`: `_run_gated_loop`, 5 cases)
SEARCH:
```
        user_message="Finish the payment.",
        tools=[],
```
REPLACE:
```
        user_message="Finish the payment.",
        tools=[*offer_scripted(responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-123** (`tests/test_ad1208_cost_bounded_turns.py`: `_answer_at_the_budget_turn`)
SEARCH:
```
    runtime = _fetch_runtime(registry, store, cfg)
    observation: dict[str, Any] = {"intent": "direct_message", "params": {}}
```
REPLACE:
```
    runtime = _fetch_runtime(registry, store, cfg)
    await runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    observation: dict[str, Any] = {"intent": "direct_message", "params": {}}
```

**P0-124** (`tests/test_ad1208_cost_bounded_turns.py`: `test_f1_armed_empty_answer_at_the_budget_keeps_the_cost_stop`)
SEARCH:
```
    agent = _real_dm_agent(_fetch_runtime(registry, store, cfg), llm)
```
REPLACE:
```
    agent = _real_dm_agent(_fetch_runtime(registry, store, cfg), llm)
    await agent._runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-125** (`tests/test_bf946_read_only_delivery_failures.py`: import)
SEARCH:
```
from probos.types import LLMRequest, LLMResponse
from tests.test_ad1240_tool_result_delivery import (
```
REPLACE:
```
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1240_tool_result_delivery import (
```

**P0-126** (`tests/test_bf946_read_only_delivery_failures.py`: `test_an_oversized_read_only_result_comes_back_as_an_error_and_a_narrower_call_succeeds`, 4 cases)
SEARCH:
```
        result = await _loop(llm, executor, runtime, structured=structured).run(
            system_prompt="", user_message="", tools=[], context=context,
```
REPLACE:
```
        result = await _loop(llm, executor, runtime, structured=structured).run(
            system_prompt="", user_message="", tools=[*offer("event_log_query")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-127** (`tests/test_bf946_read_only_delivery_failures.py`: `test_a_failed_delivery_still_ends_the_run_for_a_producer_that_is_not_read_only`)
SEARCH:
```
    llm = _NarrowingLLM("fixture_result", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
    llm = _NarrowingLLM("fixture_result", 100)
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[*offer("fixture_result")], context=context)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-128** (`tests/test_bf946_read_only_delivery_failures.py`: `test_a_recovery_read_over_the_bound_comes_back_naming_the_bound_and_a_smaller_read_is_served`, 2 cases)
SEARCH:
```
    llm = _ReadBackLLM(list(limits))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
    llm = _ReadBackLLM(list(limits))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[*offer("event_log_query", "read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-129** (`tests/test_bf946_read_only_delivery_failures.py`: `test_a_promised_read_whose_authority_is_lost_still_ends_the_run`)
SEARCH:
```
    llm = _ReadBackLLM([4096], before_read=lambda: _withhold_reader(runtime, monkeypatch))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[], context=context)
```
REPLACE:
```
    llm = _ReadBackLLM([4096], before_read=lambda: _withhold_reader(runtime, monkeypatch))
    async with _started(runtime):
        result = await _loop(llm, executor, runtime).run(system_prompt="", user_message="", tools=[*offer("event_log_query", "read_file")], context=context)  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-130** (`tests/test_bf946_read_only_delivery_failures.py`: `_frame_length`)
SEARCH:
```
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=900).run(
            system_prompt="", user_message="", tools=[], context=context,
```
REPLACE:
```
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=900).run(
            system_prompt="", user_message="", tools=[*offer("event_log_query")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-131** (`tests/test_bf946_read_only_delivery_failures.py`: `test_a_fresh_frame_exactly_at_the_bound_is_delivered`)
SEARCH:
```
        result = await _loop(llm, executor, runtime, bound=length).run(
            system_prompt="", user_message="", tools=[], context=context,
```
REPLACE:
```
        result = await _loop(llm, executor, runtime, bound=length).run(
            system_prompt="", user_message="", tools=[*offer("event_log_query")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-132** (`tests/test_bf946_read_only_delivery_failures.py`: `test_a_fresh_frame_one_over_the_bound_comes_back_as_an_error`)
SEARCH:
```
        result = await _loop(llm, executor, runtime, bound=length - 1).run(
            system_prompt="", user_message="", tools=[], context=context,
```
REPLACE:
```
        result = await _loop(llm, executor, runtime, bound=length - 1).run(
            system_prompt="", user_message="", tools=[*offer("event_log_query")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-133** (`tests/test_bf946_read_only_delivery_failures.py`: `test_each_failed_delivery_logs_one_content_free_warning_naming_its_site`, 2 cases)
SEARCH:
```
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=bound).run(
            system_prompt="", user_message="", tools=[], context=context,
```
REPLACE:
```
        result = await _loop(_NarrowingLLM("event_log_query", 100), executor, runtime, bound=bound).run(
            system_prompt="", user_message="", tools=[*offer("event_log_query")], context=context,  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-134** (`tests/test_ad1324_loop_tier_choice.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult

FLOOR = {"high": "standard", "severe": "deep"}
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.

FLOOR = {"high": "standard", "severe": "deep"}
```

**P0-135** (`tests/test_ad1324_loop_tier_choice.py`: `run`, 18 cases)
SEARCH:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "ezri", **(context or {})},
```
REPLACE:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[*offer_scripted(responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "ezri", **(context or {})},
```

**P0-136** (`tests/ablation/test_ad1324_tier_choice_ablation.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.test_ad1324_loop_tier_choice import Client, Tools, answer, controller, read, write
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad1324_loop_tier_choice import Client, Tools, answer, controller, read, write
```

**P0-137** (`tests/ablation/test_ad1324_tier_choice_ablation.py`: `_arm`, 8 cases)
SEARCH:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
```
REPLACE:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[*offer_scripted(scripted)], context={"agent_id": "ezri"})  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-138** (`tests/test_ad1324_redo_iterations.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.test_ad1324_loop_tier_choice import DIRECTIVE, Client, Tools, answer, controller, read
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad1324_loop_tier_choice import DIRECTIVE, Client, Tools, answer, controller, read
```

**P0-139** (`tests/test_ad1324_redo_iterations.py`: `run`, 4 cases)
SEARCH:
```
        loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"}), 10,
```
REPLACE:
```
        loop.run(system_prompt="s", user_message="u", tools=[*offer_scripted(responses)], context={"agent_id": "ezri"}), 10,  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-140** (`tests/test_ad1324_terminal_context.py`: import)
SEARCH:
```
from probos.substrate.event_log import EventLog
from tests.test_ad1324_audit import _build
```
REPLACE:
```
from probos.substrate.event_log import EventLog
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1324_audit import _build
```

**P0-141** (`tests/test_ad1324_terminal_context.py`: `_armed_run`; the scripts here call only `read`, which is `http_fetch`)
SEARCH:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
    await ctl.drain_audit()
    return result, ctl
```
REPLACE:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[*offer("http_fetch")], context={"agent_id": "ezri"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    await ctl.drain_audit()
    return result, ctl
```

**P0-142** (`tests/test_ad1324_terminal_context.py`: `test_cancelled_error_on_redo_still_propagates_and_writes_no_terminal`)
SEARCH:
```
    with pytest.raises(asyncio.CancelledError):
        await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "ezri"})
```
REPLACE:
```
    with pytest.raises(asyncio.CancelledError):
        await loop.run(system_prompt="s", user_message="u", tools=[*offer("http_fetch")], context={"agent_id": "ezri"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-143** (`tests/test_ad1148_tool_result_bounds.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
```

**P0-144** (`tests/test_ad1148_tool_result_bounds.py`: `_run_loop`, 8 cases)
SEARCH:
```
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
    )
    return client, result
```
REPLACE:
```
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[*offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        context={"agent_id": "agent-1"},
    )
    return client, result
```

**P0-145** (`tests/test_ad1148_tool_result_bounds.py`: `test_bounded_run_retains_full_output_on_the_result_objects`)
SEARCH:
```
    loop._bound_tool_output = _spy  # type: ignore[method-assign]
    await loop.run(
        system_prompt="sys", user_message="go", tools=[], context={"agent_id": "a"}
    )
```
REPLACE:
```
    loop._bound_tool_output = _spy  # type: ignore[method-assign]
    await loop.run(
        system_prompt="sys", user_message="go", tools=[*offer_scripted(client.responses)], context={"agent_id": "a"}  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    )
```

**P0-146** (`tests/test_ad1151_durable_tool_outputs.py`: import)
SEARCH:
```
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItem
```
REPLACE:
```
from probos.types import LLMRequest, LLMResponse
from probos.workforce import WorkItem
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
```

**P0-147** (`tests/test_ad1151_durable_tool_outputs.py`: `_run_loop`, 11 cases)
SEARCH:
```
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[],
        context={"agent_id": "agent-1"},
    )
    return client, result
```
REPLACE:
```
    result = await loop.run(
        system_prompt="sys",
        user_message="do it",
        tools=[*offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
        context={"agent_id": "agent-1"},
    )
    return client, result
```

**P0-148** (`tests/test_ad1151_durable_tool_outputs.py`: `test_tool_results_are_captured_in_request_order_across_iterations`)
SEARCH:
```
    result = await loop.run(
        system_prompt="sys", user_message="go", tools=[], context={"agent_id": "a"}
    )
```
REPLACE:
```
    result = await loop.run(
        system_prompt="sys", user_message="go", tools=[*offer_scripted(client.responses)], context={"agent_id": "a"}  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
    )
```

**P0-149** (`tests/test_ad1146_multiturn_messages.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
```

**P0-150** (`tests/test_ad1146_multiturn_messages.py`: `_run_loop`, 6 cases; the existing nameless definition stays)
SEARCH:
```
        user_message="task",
        tools=[{"type": "function"}],
        context={"agent_id": "a1"},
```
REPLACE:
```
        user_message="task",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "a1"},
```

**P0-151** (`tests/test_ad1190_delegation_tree_budget.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
```

**P0-152** (`tests/test_ad1190_delegation_tree_budget.py`: `_parent`, plus the delegated children under `_RecordingDelegate.invoke`; the offer is assembled in `_offered_tool_names` (`agentic_loop.py:1298`) and deduplicated at `agentic_dispatch.py:3585-3593`)
SEARCH:
```
async def _parent(runtime: SimpleNamespace, llm: Any) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="parent", instructions="parent instructions", task_text="delegate the work",
```
REPLACE:
```
async def _offer_probe(runtime: SimpleNamespace) -> None:
    """#1796: a dispatch run offers its agent's granted tools, so every agent here is granted the probe its script calls."""
    for agent_id in ("parent", "child", "grandchild"):
        await runtime.tool_permission_store.issue_grant(agent_id, "probe", ToolPermission.READ)


async def _parent(runtime: SimpleNamespace, llm: Any) -> WorkItemAgenticOutcome:
    await _offer_probe(runtime)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="parent", instructions="parent instructions", task_text="delegate the work",
```

**P0-153** (`tests/test_ad1190_delegation_tree_budget.py`: `_run_child`)
SEARCH:
```
) -> WorkItemAgenticOutcome:
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="child", instructions="child instructions", task_text="child task",
```
REPLACE:
```
) -> WorkItemAgenticOutcome:
    await _offer_probe(runtime)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id="child", instructions="child instructions", task_text="child task",
```

**P0-154** (`tests/test_ad1316_real_effect_routes.py`: import)
SEARCH:
```
from probos.types import IntentMessage, LLMResponse
from tests.test_ad1147_parallel_tools import _CapturingClient, _RecordingEmit
```
REPLACE:
```
from probos.types import IntentMessage, LLMResponse
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
from tests.test_ad1147_parallel_tools import _CapturingClient, _RecordingEmit
```

**P0-155** (`tests/test_ad1316_real_effect_routes.py`: `test_repeated_model_action_reuses_unknown_operation`)
SEARCH:
```
        user_message="repeat",
        tools=[],
```
REPLACE:
```
        user_message="repeat",
        tools=[*offer("opaque_mutation")],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-156** (`tests/test_ad1316_real_effect_routes.py`: `test_permission_refusal_correlation_reaches_strict_attachment`; a bare loop, so the registry's rank denial still decides)
SEARCH:
```
            user_message="deny",
            tools=[],
```
REPLACE:
```
            user_message="deny",
            tools=[*offer("denied_tool")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered; the registry's denial (this case's subject) is unchanged.
```

**P0-157** (`tests/test_ad1316_real_effect_routes.py`: `test_delegation_binding_ack_loss_reuses_one_parent_operation`)
SEARCH:
```
        user_message="delegate twice",
        tools=[],
```
REPLACE:
```
        user_message="delegate twice",
        tools=[*offer("delegate_task")],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-158** (`tests/test_ad1316_real_effect_routes.py`: `test_reservation_failure_propagates_without_completion_event`)
SEARCH:
```
            user_message="reserve",
            tools=[],
```
REPLACE:
```
            user_message="reserve",
            tools=[*offer("web_search")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-159** (`tests/test_ad1322_economic_judgment_integration.py`: imports)
SEARCH:
```
from probos.config_models.agentic import EconomicJudgmentConfig

from tests.test_ad1320_agentic_budget_awareness import (
```
REPLACE:
```
from probos.config_models.agentic import EconomicJudgmentConfig
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.

from tests.offered_tools import offer, offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad1320_agentic_budget_awareness import (
```

**P0-160** (`tests/test_ad1322_economic_judgment_integration.py`: `_run`, 11 cases)
SEARCH:
```
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    return result, client, tools
```
REPLACE:
```
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[*offer_scripted(script)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "counselor-ezri"},
    )
    return result, client, tools
```

**P0-161** (`tests/test_ad1322_economic_judgment_integration.py`: `test_block_appended_after_ad1320_note_on_structured_path`, inert)
SEARCH:
```
    await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    prompt = client.requests[2].system_prompt
```
REPLACE:
```
    await loop.run(system_prompt="s", user_message="u", tools=[*offer("http_fetch")], context={"agent_id": "a"})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
    prompt = client.requests[2].system_prompt
```

**P0-162** (`tests/test_ad1322_economic_judgment_integration.py`: `test_seam_crew_child_real_work_item_value_stakes_reaches_next_llm_request_system_prompt`)
SEARCH:
```
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=_runtime(store), max_iterations=5, token_budget=1000,
```
REPLACE:
```
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    runtime = _runtime(store)
    await runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=runtime, max_iterations=5, token_budget=1000,
```

**P0-163** (`tests/test_ad1322_economic_judgment_integration.py`: `test_seam_dm_turn_organ_enabled_block_reaches_next_request_and_detach_on_stop`; the agent id is `_Agent.id`, `"agent-1"`)
SEARCH:
```
    agent._compose_economic_judgment_organ()
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert len(requests) >= 2
```
REPLACE:
```
    agent._compose_economic_judgment_organ()
    await runtime.tool_permission_store.issue_grant("agent-1", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert len(requests) >= 2
```

**P0-164** (`tests/test_ad1322_economic_judgment_integration.py`: `test_crew_child_default_tier_priced_as_request_tier`)
SEARCH:
```
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=_priced_runtime(), max_iterations=5, tier=None,
```
REPLACE:
```
    executor = agentic_dispatch.WorkItemAgenticExecutor(llm_client=client)
    runtime = _priced_runtime()
    await runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    outcome = await executor.run(
        agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go.",
        runtime=runtime, max_iterations=5, tier=None,
```

**P0-165** (`tests/test_ad1322_economic_judgment_integration.py`: `test_dm_path_passes_ratio_not_multiplier`)
SEARCH:
```
    agent._compose_economic_judgment_organ()
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert handed and handed[0]["trust_headroom"] == 1.0, "effective/configured, not 0.5"
```
REPLACE:
```
    agent._compose_economic_judgment_organ()
    await runtime.tool_permission_store.issue_grant("agent-1", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    text = await agent._maybe_run_conversational_agentic(
        {"intent": "direct_message", "params": {}},
        system_prompt="You are Ezri.", user_message="Fetch two pages.",
    )
    assert text, "premise: the agentic turn ran"
    assert handed and handed[0]["trust_headroom"] == 1.0, "effective/configured, not 0.5"
```

**P0-166** (`tests/test_ad1322_economic_judgment_integration.py`: `test_loop_notes_charge_before_first_await`, 2 cases)
SEARCH:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    assert result.token_source == {"measured": "measured", "estimated": "mixed"}[source]
```
REPLACE:
```
    result = await loop.run(system_prompt="s", user_message="u", tools=[*offer("fetch")], context={"agent_id": "a"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    assert result.token_source == {"measured": "measured", "estimated": "mixed"}[source]
```

**P0-167** (`tests/test_ad1322_economic_judgment_integration.py`: `_cancel_scenario`, the two hanging cancel cases)
SEARCH:
```
    task = asyncio.create_task(
        loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
    )
```
REPLACE:
```
    task = asyncio.create_task(
        loop.run(system_prompt="s", user_message="u", tools=[*offer("fetch")], context={"agent_id": "a"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    )
```

**P0-168** (`tests/test_ad1322_economic_judgment_integration.py`: `_turn`; `spec["script"]` builds a fresh, equal script on each call)
SEARCH:
```
    result = await loop.run(system_prompt=f"You are {key}.", user_message="Go.", tools=[],
                            context={"agent_id": f"agent-{key}"})
```
REPLACE:
```
    result = await loop.run(system_prompt=f"You are {key}.", user_message="Go.", tools=[*offer_scripted(spec["script"]())],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
                            context={"agent_id": f"agent-{key}"})
```

**P0-169** (`tests/ablation/test_ad1322_economic_judgment_ablation.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.test_ad1320_agentic_budget_awareness import Client, Resp, Tools, answer, fetch, write
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.offered_tools import offer, offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad1320_agentic_budget_awareness import Client, Resp, Tools, answer, fetch, write
```

**P0-170** (`tests/ablation/test_ad1322_economic_judgment_ablation.py`: `_arm`)
SEARCH:
```
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[],
        context={"agent_id": "counselor-ezri"},
    )
    verified = result.stopped_reason == "complete" and VERIFY in tools.calls
```
REPLACE:
```
    result = await loop.run(
        system_prompt="You are Ezri.", user_message="Go.", tools=[*offer_scripted(script)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "counselor-ezri"},
    )
    verified = result.stopped_reason == "complete" and VERIFY in tools.calls
```

**P0-171** (`tests/ablation/test_ad1322_economic_judgment_ablation.py`: the nested `run` in `test_ablation_concurrent_turns_on_one_organ_match_solo_runs`)
SEARCH:
```
        await loop.run(system_prompt="You are Ezri.", user_message="Go.", tools=[],
                       context={"agent_id": "counselor-ezri"})
```
REPLACE:
```
        await loop.run(system_prompt="You are Ezri.", user_message="Go.", tools=[*offer_scripted(script)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
                       context={"agent_id": "counselor-ezri"})
```

**P0-172** (`tests/ablation/test_ad1322_economic_judgment_ablation.py`: `_acceptance_goal`; `_PolicySensitiveClient` calls only `fetch` and `write`, `:178-180`)
SEARCH:
```
        user_message=f"Complete {goal.name}.",
        tools=[],
```
REPLACE:
```
        user_message=f"Complete {goal.name}.",
        tools=[*offer("http_fetch", "write_file")],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-173** (`tests/test_ad1320_agentic_budget_awareness.py`: imports)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry

MARKER = "Budget notice"
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
from tests.offered_tools import offer, offer_scripted  # #1796: the loop runs only offered tools.

MARKER = "Budget notice"
```

**P0-174** (`tests/test_ad1320_agentic_budget_awareness.py`: `run`, 14 inert cases; also used by `test_ad1322` integration as `run_ad1320`)
SEARCH:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "counselor-ezri"},
```
REPLACE:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[*offer_scripted(responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "counselor-ezri"},
```

**P0-175** (`tests/test_ad1320_agentic_budget_awareness.py`: `test_two_pass_seam_shares_state_through_real_executor_and_loop`, pass 1)
SEARCH:
```
    first = await loop.run(system_prompt="s", user_message="u", tools=[], context={"agent_id": "a"})
```
REPLACE:
```
    first = await loop.run(system_prompt="s", user_message="u", tools=[*offer("write_file")], context={"agent_id": "a"})  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-176** (`tests/test_ad1320_agentic_budget_awareness.py`: same test, pass 2 through the executor)
SEARCH:
```
    with mock.patch.object(AgenticLoop, "__init__", _spy):
        outcome = await executor.run(
            agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go on.",
            runtime=_executor_runtime(), max_iterations=5, **budget.loop_kwargs(),
        )
```
REPLACE:
```
    runtime = _executor_runtime()
    await runtime.tool_permission_store.issue_grant("counselor-ezri", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    with mock.patch.object(AgenticLoop, "__init__", _spy):
        outcome = await executor.run(
            agent_id="counselor-ezri", instructions="You are Ezri.", task_text="Go on.",
            runtime=runtime, max_iterations=5, **budget.loop_kwargs(),
        )
```

**P0-177** (`tests/ablation/test_ad1320_budget_awareness_ablation.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.test_ad1320_agentic_budget_awareness import (
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop

from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
from tests.test_ad1320_agentic_budget_awareness import (
```

**P0-178** (`tests/ablation/test_ad1320_budget_awareness_ablation.py`: `_arm`, 2 inert cases)
SEARCH:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[],
        context={"agent_id": "counselor-ezri"},
```
REPLACE:
```
        system_prompt="You are Ezri.", user_message="Research.", tools=[*offer_scripted(script)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
        context={"agent_id": "counselor-ezri"},
```

**P0-179** (`tests/test_ad1142_crew_child_compaction.py`: import)
SEARCH:
```
from probos.work_item_steps import OwnedExecutionLease, OwnedStepExecutionPermit
from probos.workforce import WorkItemStore
```
REPLACE:
```
from probos.work_item_steps import OwnedExecutionLease, OwnedStepExecutionPermit
from probos.workforce import WorkItemStore
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
```

**P0-180** (`tests/test_ad1142_crew_child_compaction.py`: `test_window_exhausting_child_goes_from_error_to_complete_on_the_gate`, off arm; `_ScriptedClient` calls only `read_page`, `:221-227`)
SEARCH:
```
        off_client, _BulkToolExecutor(output_chars=2000), max_iterations=20
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        off_client, _BulkToolExecutor(output_chars=2000), max_iterations=20
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-181** (`tests/test_ad1142_crew_child_compaction.py`: same test, on arm)
SEARCH:
```
        compaction_threshold=2500,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        compaction_threshold=2500,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-182** (`tests/test_ad1142_crew_child_compaction.py`: `test_compaction_does_not_convert_a_max_iterations_stop`, inert)
SEARCH:
```
        compaction_threshold=1500,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        compaction_threshold=1500,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-183** (`tests/test_ad1142_crew_child_compaction.py`: `test_high_cumulative_spend_with_a_short_history_never_compacts`, inert)
SEARCH:
```
        compaction_threshold=5_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        compaction_threshold=5_000,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-184** (`tests/test_ad1142_crew_child_compaction.py`: `test_compaction_fires_only_when_occupancy_re_crosses`)
SEARCH:
```
        compaction_threshold=3_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        compaction_threshold=3_000,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-185** (`tests/test_ad1142_crew_child_compaction.py`: `test_large_history_with_small_spend_does_compact`)
SEARCH:
```
        max_iterations=5,
        compactor=compactor,
        compaction_threshold=2_000,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        max_iterations=5,
        compactor=compactor,
        compaction_threshold=2_000,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-186** (`tests/test_ad1142_crew_child_compaction.py`: `test_a_group_larger_than_the_threshold_warns_and_continues`)
SEARCH:
```
            compaction_threshold=2_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
            compaction_threshold=2_000,
        ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-187** (`tests/test_ad1142_crew_child_compaction.py`: `test_a_misbehaving_compactor_does_not_stop_the_run`)
SEARCH:
```
            compactor=_RecordingCompactor(replacement=[]),
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
            compactor=_RecordingCompactor(replacement=[]),
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-188** (`tests/test_ad1142_crew_child_compaction.py`: `test_a_raising_compactor_keeps_the_previous_messages`)
SEARCH:
```
            compactor=compactor,
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
            compactor=compactor,
            compaction_threshold=1_000,
        ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-189** (`tests/test_ad1142_crew_child_compaction.py`: `test_token_budget_is_threaded_to_the_loop_and_stops_it`)
SEARCH:
```
        token_budget=4096,
    ).run(system_prompt="sys", user_message="task", tools=[], context={})
```
REPLACE:
```
        token_budget=4096,
    ).run(system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={})  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-190** (`tests/test_bf680_token_usage_fallback.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
```

**P0-191** (`tests/test_bf680_token_usage_fallback.py`: `_run`, 8 inert cases; `read_page` is the file's only scripted tool, `:63`)
SEARCH:
```
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"}
```
REPLACE:
```
        system_prompt="sys", user_message="task", tools=[*offer("read_page")], context={"agent_id": "a1"}  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-192** (`tests/test_bf901_s1_token_accounting.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
```

**P0-193** (`tests/test_bf901_s1_token_accounting.py`: `_run`, 2 inert cases)
SEARCH:
```
    return await loop.run(system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"})
```
REPLACE:
```
    return await loop.run(system_prompt="sys", user_message="task", tools=[*offer_scripted(responses)], context={"agent_id": "a1"})  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-194** (`tests/test_ad545_agentic_loop.py`: import)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMResponse
```
REPLACE:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMResponse
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.
```

**P0-195** (`tests/test_ad545_agentic_loop.py`: `test_loop_one_tool_use_then_text_stops_at_iteration_two`)
SEARCH:
```
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="sys",
        user_message="task",
        tools=[{"type": "function"}],
```
REPLACE:
```
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="sys",
        user_message="task",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-196** (`tests/test_ad545_agentic_loop.py`: `test_loop_emits_tool_call_started_and_completed`)
SEARCH:
```
        event_emit_fn=lambda et, p: events.append(et),
    )
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
        event_emit_fn=lambda et, p: events.append(et),
    )
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-197** (`tests/test_ad545_agentic_loop.py`: `test_loop_max_iterations_forces_stop`, inert)
SEARCH:
```
        llm_client=client, tool_executor=_FakeExecutor(), max_iterations=2
    )
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
        llm_client=client, tool_executor=_FakeExecutor(), max_iterations=2
    )
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-198** (`tests/test_ad545_agentic_loop.py`: `test_loop_tool_exception_continues_with_error_result`, inert)
SEARCH:
```
    executor = _FakeExecutor(raise_exc=True)
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
    executor = _FakeExecutor(raise_exc=True)
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-199** (`tests/test_ad545_agentic_loop.py`: `test_loop_never_raises_under_failures`, inert)
SEARCH:
```
    # If any failure path raised, this would propagate.
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
    # If any failure path raised, this would propagate.
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-200** (`tests/test_ad545_agentic_loop.py`: `test_loop_appends_assistant_and_tool_result_messages`, inert)
SEARCH:
```
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
    executor = _FakeExecutor()
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-201** (`tests/test_ad545_agentic_loop.py`: `test_loop_compactor_invoked_when_threshold_reached`, inert)
SEARCH:
```
        user_message=bulky_user_message,
        tools=[],
```
REPLACE:
```
        user_message=bulky_user_message,
        tools=[*offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tool is offered.
```

**P0-202** (`tests/test_ad545_agentic_loop.py`: `test_loop_tool_call_history_populated_across_iterations`, inert)
SEARCH:
```
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
    loop = AgenticLoop(llm_client=client, tool_executor=_FakeExecutor())
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-203** (`tests/test_ad545_agentic_loop.py`: `test_loop_executor_returning_error_result_continues`, inert)
SEARCH:
```
    executor = _FakeExecutor(error="permission denied")
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}],
```
REPLACE:
```
    executor = _FakeExecutor(error="permission denied")
    loop = AgenticLoop(llm_client=client, tool_executor=executor)
    out = await loop.run(
        system_prompt="s",
        user_message="u",
        tools=[{"type": "function"}, *offer_scripted(client.responses)],  # #1796: the loop runs only offered tools, so the scripted calls' tools are offered.
```

**P0-204** (`tests/test_ad1200_repository_instruction_wire.py`: import)
SEARCH:
```
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
```
REPLACE:
```
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
```

**P0-205** (`tests/test_ad1200_repository_instruction_wire.py`: `test_shared_loop_nested_and_concurrent_runs_keep_observations_local`, 2 cases)
SEARCH:
```
            system_prompt="BASE", user_message=label, tools=[],
```
REPLACE:
```
            system_prompt="BASE", user_message=label, tools=[*offer("read_file")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-206** (`tests/test_ad1200_repository_instruction_wire.py`: `test_cancelled_loop_drops_guidance_before_next_run`)
SEARCH:
```
        system_prompt="BASE", user_message="cancel", tools=[],
```
REPLACE:
```
        system_prompt="BASE", user_message="cancel", tools=[*offer("read_file")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-207** (`tests/test_ad1316_governed_effect_broker.py`: `test_real_delegate_executor_forwards_parent_operation_to_child`; the child's dispatch run reads the delegation runtime's store, `test_ad1191_delegation_wire.py:233-239`)
SEARCH:
```
    runtime.tool_registry = registry
    runtime.effect_broker = broker
```
REPLACE:
```
    runtime.tool_registry = registry
    runtime.effect_broker = broker
    await runtime.tool_permission_store.issue_grant("child", "child_effect", ToolPermission.READ)  # #1796: the loop runs only offered tools; the child's dispatch run offers its granted tools.
```

**P0-208** (`tests/test_ad1316_governed_effect_broker.py`: `test_permission_denied_agentic_completion_carries_persisted_ids`; a bare loop, so the registry's rank denial still decides)
SEARCH:
```
        system_prompt="sys",
        user_message="denied",
        tools=[],
```
REPLACE:
```
        system_prompt="sys",
        user_message="denied",
        tools=[*offer("web_search")],  # #1796: the loop runs only offered tools, so the scripted call's tool is offered; the registry's denial (this case's subject) is unchanged.
```

**P0-209** (`tests/test_ad1246_long_run_promotion.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.tools.registry import ToolRegistry
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
```

**P0-210** (`tests/test_ad1246_long_run_promotion.py`: `test_m1_grant_reaches_the_tool_only_from_a_promotable_turn`, 4 cases; the DM route)
SEARCH:
```
    runtime.tool_registry.register(probe)
    agent = _conversational_agent(runtime, _ScriptedLLM("grant_probe", {}))
```
REPLACE:
```
    runtime.tool_registry.register(probe)
    await runtime.tool_permission_store.issue_grant("conversation-agent", "grant_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    agent = _conversational_agent(runtime, _ScriptedLLM("grant_probe", {}))
```

**P0-211** (`tests/test_ad1246_long_run_promotion.py`: `_run_with_extra_context`, the async helper of the 8 M5 cases; `_probe_runtime` is synchronous). A second grant of the same tool from `_assert_dispatch_refuses` adds a row the offer deduplicates (`agentic_dispatch.py:3585-3593`).
SEARCH:
```
    """The real ``WorkItemAgenticExecutor.run`` boundary, called the way a direct turn calls it."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    return await asyncio.wait_for(
```
REPLACE:
```
    """The real ``WorkItemAgenticExecutor.run`` boundary, called the way a direct turn calls it."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    await runtime.tool_permission_store.issue_grant("conversation-agent", "grant_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    return await asyncio.wait_for(
```

**P0-212** (`tests/test_ad1191_delegation_wire.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.publish_finding_tool import FindingToolResult, PublishFindingTool
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.publish_finding_tool import FindingToolResult, PublishFindingTool
```

**P0-213** (`tests/test_ad1191_delegation_wire.py`: `test_raw_post_hook_does_not_promote_dictionary_or_metadata_authority`). `publish_finding` is in `_GATED_TOOL_IDS`, so it is offered by its own block, which asks for WRITE (`agentic_dispatch.py:3477-3486`). The forged registration has no rank table, so it resolves to READ; a WRITE grant to `child` lets that block offer it.
SEARCH:
```
    forged = _ForgedPublication()
    runtime.tool_registry.register(forged, provider="local-test")
```
REPLACE:
```
    forged = _ForgedPublication()
    runtime.tool_registry.register(forged, provider="local-test")
    await runtime.tool_permission_store.issue_grant("child", "publish_finding", ToolPermission.WRITE)  # #1796: the loop runs only offered tools; publish_finding is offered by its own block, which asks for WRITE.
```

**P0-214** (`tests/test_ad1191_delegation_wire.py`: `test_child_cancellation_propagates_without_terminal_evidence_or_leaking_collection`; `[tool]` timed out because the child was refused `blocking_probe`)
SEARCH:
```
    blocking = _BlockingTool()
    runtime.tool_registry.register(blocking, provider="local-test")
```
REPLACE:
```
    blocking = _BlockingTool()
    runtime.tool_registry.register(blocking, provider="local-test")
    await runtime.tool_permission_store.issue_grant("child", "blocking_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-215** (`tests/test_ad1257_defect_follows_failure.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
```
REPLACE:
```
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
```

**P0-216** (`tests/test_ad1257_defect_follows_failure.py`: `_run_executor`; 2 failing and 3 inert browser cases. The MCP alias case is 3b.)
SEARCH:
```
    perm_store = ToolPermissionStore()
    executor = WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses))
```
REPLACE:
```
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-ezri", tool.tool_id, ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    executor = WorkItemAgenticExecutor(llm_client=_ScriptedLLM(responses))
```

**P0-217** (`tests/test_ad1356_s2_tool_effect_table.py`: import `ToolPermission`)
SEARCH:
```
    tool_tier,
)
from tests.test_ad1240_workspace_results import make_store
```
REPLACE:
```
    tool_tier,
)
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.
from tests.test_ad1240_workspace_results import make_store
```

**P0-218** (`tests/test_ad1356_s2_tool_effect_table.py`: `_native`, the shared helper. It covers ET3, ET4 and ET5, and the three `test_bf948_list_files_read_policy.py` failures, which import it. The native tools' rank tables already give READ (`swe_harness/tools.py:1436-1441`), so the grant changes nothing on the base tree. The agent-work gate does not read grants.)
SEARCH:
```
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    await store.start()
    return store
```
REPLACE:
```
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    for tool_id in ("read_file", "list_files", "codebase_query"):  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
        await rig.permissions.issue_grant("forge-1", tool_id, ToolPermission.READ)
    await store.start()
    return store
```

**P0-219** (`tests/test_ad856_agentic_dispatch.py`: `test_run_agentic_dispatch_enabled_runs_multiple_tool_iterations`; `ToolPermission` is already imported, at `:24`)
SEARCH:
```
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "fake_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-220** (`tests/test_ad856_agentic_dispatch.py`: `test_run_agentic_dispatch_tool_denied_surfaces_capability_gap`; the subject is the rank-table denial)
SEARCH:
```
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("restricted_tool"),
```
REPLACE:
```
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    await perm_store.issue_grant("counselor-001", "restricted_tool", ToolPermission.NONE)  # #1796: the loop runs only offered tools; a grant offers it, and a NONE grant leaves the registry's rank-gate denial (this case's subject) unchanged.
    gap_driver = _FakeGapDriver()
    llm = _ScriptedLLM(
        [
            _tool_use_response("restricted_tool"),
```

**P0-221** (`tests/test_ad856_agentic_dispatch.py`: `test_run_agentic_dispatch_respects_max_iterations`)
SEARCH:
```
    tool = _FakeTool("loop_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    tool = _FakeTool("loop_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "loop_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-222** (`tests/test_ad1072_agentic_tools.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
```

**P0-223** (`tests/test_ad1072_agentic_tools.py`: `test_delegate_happy_path_returns_result_and_increments_depth`; the nested run is `bashir-1`'s)
SEARCH:
```
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg, extra_tools=[probe])
    # The nested loop (the tool's own client): probe the context, then answer.
```
REPLACE:
```
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg, extra_tools=[probe])
    await runtime.tool_permission_store.issue_grant("bashir-1", "nested_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    # The nested loop (the tool's own client): probe the context, then answer.
```

**P0-224** (`tests/test_ad1072_agentic_tools.py`: `test_loop_delegate_task_runs_nested_executor_and_returns_into_transcript`)
SEARCH:
```
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    # One scripted LLM drives BOTH the parent loop and (since the delegate tool
```
REPLACE:
```
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    await runtime.tool_permission_store.issue_grant("bashir-1", "nested_probe", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    # One scripted LLM drives BOTH the parent loop and (since the delegate tool
```

**P0-225** (`tests/test_ad859a_agentic_executor.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState
```

**P0-226** (`tests/test_ad859a_agentic_executor.py`: `test_executor_run_returns_final_text_and_stopped_reason`, inert)
SEARCH:
```
    """Outcome maps AgenticResult.final_text and .stopped_reason from the loop."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    """Outcome maps AgenticResult.final_text and .stopped_reason from the loop."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "fake_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-227** (`tests/test_ad859a_agentic_executor.py`: `test_executor_run_captures_denied_tools`; the subject is the rank-table denial)
SEARCH:
```
    """A ToolPermissionDenied mid-loop is recorded in outcome.denied_tools."""
    registry = ToolRegistry()
    restricted = _FakeTool("restricted_tool")
    registry.register(
        restricted, provider="test", default_permissions={"captain": "full"}
    )
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
```
REPLACE:
```
    """A ToolPermissionDenied mid-loop is recorded in outcome.denied_tools."""
    registry = ToolRegistry()
    restricted = _FakeTool("restricted_tool")
    registry.register(
        restricted, provider="test", default_permissions={"captain": "full"}
    )
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    await perm_store.issue_grant("counselor-001", "restricted_tool", ToolPermission.NONE)  # #1796: the loop runs only offered tools; a grant offers it, and a NONE grant leaves the registry's rank-gate denial (this case's subject) unchanged.
```

**P0-228** (`tests/test_ad859a_agentic_executor.py`: `test_executor_run_persists_tool_trace_ref_when_store_wired`, inert)
SEARCH:
```
    """tool_trace_ref is a content-addressable SHA ref (not inline bytes)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    """tool_trace_ref is a content-addressable SHA ref (not inline bytes)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "fake_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-229** (`tests/test_ad859a_agentic_executor.py`: `test_executor_run_tool_trace_ref_none_when_store_unwired`, inert)
SEARCH:
```
    """No AttachmentStore -> tool_trace_ref honest-degrades to None (no raise)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    """No AttachmentStore -> tool_trace_ref honest-degrades to None (no raise)."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "fake_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-230** (`tests/test_ad859a_agentic_executor.py`: `test_run_agentic_dispatch_returns_str_after_refactor`, inert)
SEARCH:
```
    """AD-839 path unchanged: _run_agentic_dispatch still returns the loop's str."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
```
REPLACE:
```
    """AD-839 path unchanged: _run_agentic_dispatch still returns the loop's str."""
    registry = ToolRegistry()
    tool = _FakeTool("fake_tool")
    registry.register(tool, provider="test")
    perm_store = ToolPermissionStore()
    await perm_store.issue_grant("counselor-001", "fake_tool", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-231** (`tests/test_ad859a_agentic_executor.py`: `test_run_agentic_dispatch_surfaces_gaps_after_refactor`; the subject is the rank-table denial)
SEARCH:
```
    """Gap surfacing for denied tools stays the caller's responsibility."""
    registry = ToolRegistry()
    restricted = _FakeTool("restricted_tool")
    registry.register(
        restricted, provider="test", default_permissions={"captain": "full"}
    )
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
```
REPLACE:
```
    """Gap surfacing for denied tools stays the caller's responsibility."""
    registry = ToolRegistry()
    restricted = _FakeTool("restricted_tool")
    registry.register(
        restricted, provider="test", default_permissions={"captain": "full"}
    )
    perm_store = ToolPermissionStore()
    registry.set_permission_store(perm_store)
    await perm_store.issue_grant("counselor-001", "restricted_tool", ToolPermission.NONE)  # #1796: the loop runs only offered tools; a grant offers it, and a NONE grant leaves the registry's rank-gate denial (this case's subject) unchanged.
```

**P0-232** (`tests/test_bf900_dispatch_claim_keeps_the_park.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult
```

**P0-233** (`tests/test_bf900_dispatch_claim_keeps_the_park.py`: the `wired` fixture; covers T1 and T3. Triage ignores a NONE grant (`capability_triage.py:141`), so the gap still triages as `grant`.)
SEARCH:
```
    registry.register(restricted, provider="test", default_permissions={"captain": "full"})
    registry.set_permission_store(perms)
```
REPLACE:
```
    registry.register(restricted, provider="test", default_permissions={"captain": "full"})
    registry.set_permission_store(perms)
    await perms.issue_grant(AGENT, RESTRICTED, ToolPermission.NONE)  # #1796: the loop runs only offered tools; a grant offers it, and a NONE grant leaves the registry's rank-gate denial (this case's subject) unchanged.
```

**P0-234** (`tests/test_ad1325_completion_chain.py`: import `ToolPermission`)
SEARCH:
```
from probos.threads import ChatThreadStore
from probos.workforce import (
```
REPLACE:
```
from probos.threads import ChatThreadStore
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.
from probos.workforce import (
```

**P0-235** (`tests/test_ad1325_completion_chain.py`: `_production_owned_case`, async. It covers the two inert cases, `test_production_observer_real_outer_loop_persists_every_pass` and `test_public_unbudgeted_signed_sequence_observes_safe_spends_without_changing_total`; `_production_runtime` is synchronous.)
SEARCH:
```
    runtime = _production_runtime(
        store,
        registry,
        calibration_enabled=calibration_enabled,
    )
```
REPLACE:
```
    runtime = _production_runtime(
        store,
        registry,
        calibration_enabled=calibration_enabled,
    )
    await runtime.tool_permission_store.issue_grant("agent-1", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
```

**P0-236** (`tests/test_ad1325_completion_chain.py`: `test_production_observer_direct_executor_floor_redo_captures_distinct_price_snapshots`. The BF-680 estimate is computed from the messages, not the offered tools (`agentic_loop.py:1959-1963`), so 1532 holds.)
SEARCH:
```
        runtime = _production_runtime(store, registry)
        organ = EconomicJudgmentOrgan()
```
REPLACE:
```
        runtime = _production_runtime(store, registry)
        await runtime.tool_permission_store.issue_grant("agent-1", "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
        organ = EconomicJudgmentOrgan()
```

**P0-237** (`tests/test_bf947_multi_call_agent_work.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult
from probos.types import LLMRequest
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult
from probos.types import LLMRequest
```

**P0-238** (`tests/test_bf947_multi_call_agent_work.py`: `test_another_claimant_is_not_given_the_first_claimants_results`; the rig grants `hull_survey` to `forge-1` only, at `test_ad1347_s3_execution.py:193`)
SEARCH:
```
        assert released is not None and (released.status, released.assigned_to) == ("open", None)
        assert (await rig.runner.claim("laforge-1", item_id))[0] == "claimed"
```
REPLACE:
```
        assert released is not None and (released.status, released.assigned_to) == ("open", None)
        await rig.permissions.issue_grant("laforge-1", "hull_survey", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
        assert (await rig.runner.claim("laforge-1", item_id))[0] == "claimed"
```

**P0-239** (`tests/test_ad1356_s1_recovery_reads.py`: import `ToolPermission`)
SEARCH:
```
from probos.cognitive.swe_harness.tools import register_native_swe_tools
from tests.test_ad1240_workspace_results import _capture, make_store
```
REPLACE:
```
from probos.cognitive.swe_harness.tools import register_native_swe_tools
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.
from tests.test_ad1240_workspace_results import _capture, make_store
```

**P0-240** (`tests/test_ad1356_s1_recovery_reads.py`: `_workspace`; covers RR1 and RR3. These are direct `read_file` calls, not the AD-1240 reader after a promise.)
SEARCH:
```
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    await store.start()
    return store
```
REPLACE:
```
    assert register_native_swe_tools(rig.tools, rig.runtime) == 12
    await rig.permissions.issue_grant("forge-1", "read_file", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    await store.start()
    return store
```

**P0-241** (`tests/test_ad1323_continue_extension_seam.py`: import `ToolPermission`)
SEARCH:
```
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
```
REPLACE:
```
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
```

**P0-242** (`tests/test_ad1323_continue_extension_seam.py`: `board`, async; covers the 12 inert cases. `_reboot` calls `board` again, so a rebooted ship is granted too.)
SEARCH:
```
    runtime.registry = registry
    assert _wire_capability_gap_driver(runtime=runtime, config=system) is True
```
REPLACE:
```
    runtime.registry = registry
    await runtime.tool_permission_store.issue_grant(AGENT, "http_fetch", ToolPermission.READ)  # #1796: the loop runs only offered tools; a dispatch run offers its granted tools.
    assert _wire_capability_gap_driver(runtime=runtime, config=system) is True
```

**P0-243** (`tests/offered_tools.py`: the D-MCP rig, shared by `test_ad1205` and `test_ad1257`; two pairs)
SEARCH:
```
from collections.abc import Iterable
from typing import Any

from probos.cognitive.swe_harness.tool_call import ToolUseBlock
```
REPLACE:
```
from collections.abc import Iterable, Sequence
from types import SimpleNamespace
from typing import Any

from probos.cognitive.swe_harness.tool_call import ToolUseBlock
from probos.tools.protocol import ToolType
```
SEARCH:
```
        if isinstance(block, ToolUseBlock) and block.tool_call.name
    )
    return offer(*names)
```
REPLACE:
```
        if isinstance(block, ToolUseBlock) and block.tool_call.name
    )
    return offer(*names)


class OfferedMcpTools:
    """An AD-1241 dispatch source (``MCPDispatchSource``) that offers fixed MCP adapter ids.

    A dispatch run offers an MCP adapter only through ``runtime.mcp_workbench`` while ``config.mcp.agent_tools_enabled``
    is set; a grant never offers one. ``create_dispatch_offer`` admits each id into the run's ``MCPDispatchOffer`` with
    ``admit``, the call a successful ``find_mcp_tool`` pull makes, so the offer reads as a discovery the run already
    made, whatever the adapter's risk tier. The adapters stay the fixture's own registrations: this source holds no
    grant, bridge or risk store, offers no search tool, and every call still goes through the registry and the
    adapter's own checks.
    """

    def __init__(self, *tool_ids: str) -> None:
        self.tool_ids = tuple(tool_ids)

    async def create_dispatch_offer(self, agent_id: str, *, preload_limit: int) -> Any:
        from probos.cognitive.mcp_workbench import MCPDispatchOffer

        offer = MCPDispatchOffer(self, agent_id, preload_limit=preload_limit)
        for tool_id in self.tool_ids:
            if not offer.admit(tool_id):
                raise ValueError(f"not an admissible MCP adapter id: {tool_id!r}")
        return offer

    def accepts_dispatch_offer(self, offer: Any, agent_id: str) -> bool:
        from probos.cognitive.mcp_workbench import MCPDispatchOffer

        return type(offer) is MCPDispatchOffer and offer.belongs_to(self, agent_id)

    def dispatch_tool_ids(self, agent_id: str, *, candidate_ids: Sequence[str] | None = None) -> list[str]:
        """The supplied candidates this source holds, in order; every held id when ``candidate_ids`` is None."""
        ids = self.tool_ids if candidate_ids is None else candidate_ids
        return [tool_id for tool_id in dict.fromkeys(ids) if tool_id in self.tool_ids]


def offer_mcp(runtime: Any, *tool_ids: str) -> OfferedMcpTools:
    """Arm ``runtime``'s AD-1241 offer with ``OfferedMcpTools(*tool_ids)``.

    ``runtime.config`` is a namespace with no ``mcp`` section of its own (``_exec_runtime``); the section it gets turns
    the offer on and nothing else.
    """
    source = OfferedMcpTools(*tool_ids)
    runtime.mcp_workbench = source
    runtime.config.mcp = SimpleNamespace(agent_tools_enabled=True)
    return source


class McpSearchToolStandIn:
    """A ``find_mcp_tool`` registration typed as the real one (``ToolType.UTILITY_AGENT``, ``_FindMcpToolTool``).

    A session-correction projection offers MCP adapters only when its source registry holds a valid search tool
    (``crew_verifier`` ``synchronize_mcp_definitions``). Register it with ``tags=["find_mcp_tool", "mcp"]``. Nothing
    offers it a call, so it never runs.
    """

    tool_id = "find_mcp_tool"
    name = "find_mcp_tool"
    tool_type = ToolType.UTILITY_AGENT
    description = "Search for an MCP tool by what you want to do."
    input_schema: dict[str, Any] = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    output_schema: dict[str, Any] = {"type": "object"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
        raise AssertionError("the stand-in search tool never runs")
```

**P0-244** (`tests/test_ad1205_fault_paths.py`: import)
SEARCH:
```
from tests.offered_tools import offer  # #1796: the loop runs only offered tools.
```
REPLACE:
```
from tests.offered_tools import McpSearchToolStandIn, offer, offer_mcp  # #1796: the loop runs only offered tools.
```

**P0-245** (`tests/test_ad1205_fault_paths.py`: `test_mcp_confirmation_is_neutral_through_real_shared_loop`, 2 cases; `_offer_tools` skips MCP ids by design, P0-80)
SEARCH:
```
    await _grant_fixture(runtime, tool)
    alias = llm_function_name(tool.tool_id)
    assert alias != tool.tool_id and tool_fault_adapter_kind(runtime.tool_registry, tool.tool_id) is ToolFaultAdapterKind.MCP
```
REPLACE:
```
    await _grant_fixture(runtime, tool)
    offer_mcp(runtime, tool.tool_id)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
    alias = llm_function_name(tool.tool_id)
    assert alias != tool.tool_id and tool_fault_adapter_kind(runtime.tool_registry, tool.tool_id) is ToolFaultAdapterKind.MCP
```

**P0-246** (`tests/test_ad1205_fault_paths.py`: `test_real_governed_fault_chain_neutral_turn_privacy_and_one_approval[*-mcp]`, 8 cases; the browser arm is already granted)
SEARCH:
```
    if adapter == "mcp":
        tool, bridge, risk = _mcp_fixture()
        failure_params = neutral_params = {}
```
REPLACE:
```
    if adapter == "mcp":
        tool, bridge, risk = _mcp_fixture()
        offer_mcp(runtime, tool.tool_id)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
        failure_params = neutral_params = {}
```

**P0-247** (`tests/test_ad1205_fault_paths.py`: the inert `test_adapter_query_projection_limits_aliases_and_current_registration`. The projection offers an adapter only through its source's AD-1241 offer, and only when the source holds a valid search tool; otherwise it denies every MCP-tagged id (`crew_verifier.py:1143-1202`). The search tool is never offered here.)
SEARCH:
```
    risk.risk = McpToolRisk.CONFIRM
    await _grant_fixture(runtime, tool)
    projected = _session_correction_runtime(
```
REPLACE:
```
    risk.risk = McpToolRisk.CONFIRM
    await _grant_fixture(runtime, tool)
    # #1796: the loop runs only offered tools, so the scripted call's tool is offered. A correction projection offers an
    # MCP adapter only through its source's AD-1241 offer, which needs a valid search tool in the source registry.
    offer_mcp(runtime, tool.tool_id)
    runtime.tool_registry.register(McpSearchToolStandIn(), provider="AD-1019c", tags=["find_mcp_tool", "mcp"])
    projected = _session_correction_runtime(
```

**P0-248** (`tests/test_ad1257_defect_follows_failure.py`: import `offer_mcp`)
SEARCH:
```
from probos.tools.registry import ToolRegistry

ERROR_TEXT = "unknown browser action: 'key_type'"
```
REPLACE:
```
from probos.tools.registry import ToolRegistry
from tests.offered_tools import offer_mcp  # #1796: the loop runs only offered tools.

ERROR_TEXT = "unknown browser action: 'key_type'"
```

**P0-249** (`tests/test_ad1257_defect_follows_failure.py`: `test_an_mcp_fault_is_filed_against_the_canonical_id_and_recovers_args`; the model calls the alias of `mcp:docs:search`)
SEARCH:
```
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.attachment_store = trace
```
REPLACE:
```
    runtime = _exec_runtime(registry, ToolPermissionStore())
    runtime.attachment_store = trace
    offer_mcp(runtime, MCP_TOOL_ID)  # #1796: the loop runs only offered tools, so the scripted call's tool is offered.
```

**P0-250** (`tests/test_ad1126_verified_finalization.py`: import `MCPDispatchOffer`)
SEARCH:
```
    SubtaskVerifier,
)
from probos.config import SystemConfig
```
REPLACE:
```
    SubtaskVerifier,
)
from probos.cognitive.mcp_workbench import MCPDispatchOffer  # #1796: a correction offers MCP tools only through its source's AD-1241 offer.
from probos.config import SystemConfig
```

**P0-251** (`tests/test_ad1126_verified_finalization.py`: `_McpWorkbench` gets the AD-1241 source surface. `calls` still counts only the projection's read of the source's tool list, so `calls == ["producer-1"]` and `calls == []` hold. Its other users, at `:6788`, `:6916`, `:6979` and `:7870`, run no correction loop.)
SEARCH:
```
class _McpWorkbench:
    def __init__(self, tool_ids: list[str]) -> None:
        self.tool_ids = list(tool_ids)
        self.calls: list[str] = []

    def dispatch_tool_ids(self, agent_id: str) -> list[str]:
        self.calls.append(agent_id)
        return list(self.tool_ids)
```
REPLACE:
```
class _McpWorkbench:
    def __init__(self, tool_ids: list[str]) -> None:
        self.tool_ids = list(tool_ids)
        self.calls: list[str] = []

    def dispatch_tool_ids(
        self, agent_id: str, *, candidate_ids: Sequence[str] | None = None,
    ) -> list[str]:
        if candidate_ids is not None:
            # #1796: the AD-1241 selection a run's offer reads, as MCPWorkbench.dispatch_tool_ids gives it: the search
            # tool plus the supplied candidates this source holds. ``calls`` counts only the projection's snapshot read.
            return ["find_mcp_tool", *(
                tool_id for tool_id in dict.fromkeys(candidate_ids)
                if tool_id != "find_mcp_tool" and tool_id in self.tool_ids
            )]
        self.calls.append(agent_id)
        return list(self.tool_ids)

    async def create_dispatch_offer(self, agent_id: str, *, preload_limit: int) -> MCPDispatchOffer:
        # #1796: the loop runs only offered tools, and a correction offers find_mcp_tool only through its source's
        # AD-1241 offer (crew_verifier._SessionMcpToolIds). Nothing is preloaded: no adapter is registered here.
        return MCPDispatchOffer(self, agent_id, preload_limit=preload_limit)

    def accepts_dispatch_offer(self, offer: MCPDispatchOffer, agent_id: str) -> bool:
        return type(offer) is MCPDispatchOffer and offer.belongs_to(self, agent_id)
```

**P0-252** (`tests/test_ad1126_verified_finalization.py`: `_ProjectionMetadataTool` takes a `tool_type`. The default keeps `MCP_SERVER`, so the 18 malformed cases are unchanged.)
SEARCH:
```
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> None:
        super().__init__(tool_id, tool_type=ToolType.MCP_SERVER)
```
REPLACE:
```
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        tool_type: ToolType = ToolType.MCP_SERVER,  # #1796: an offered search tool is UTILITY_AGENT, as the real one is.
    ) -> None:
        super().__init__(tool_id, tool_type=tool_type)
```

**P0-253** (`tests/test_ad1126_verified_finalization.py`: `test_session_correction_find_mcp_tool_source_registration_executes_without_shared_mutation`; a correction offers a search tool only as `UTILITY_AGENT`, `crew_verifier.py:525-532`)
SEARCH:
```
        output={"discovery": "source-backed-mcp-result"},
        tool_type=ToolType.MCP_SERVER,
    )
```
REPLACE:
```
        output={"discovery": "source-backed-mcp-result"},
        tool_type=ToolType.UTILITY_AGENT,  # #1796: the loop runs only offered tools; an offered search tool is UTILITY_AGENT.
    )
```

**P0-254** (`tests/test_ad1126_verified_finalization.py`: `test_session_correction_find_mcp_registration_valid_string_boundaries_execute`)
SEARCH:
```
        output_schema={"type": "object", "result": four_byte_character * 1_024},
    )
```
REPLACE:
```
        output_schema={"type": "object", "result": four_byte_character * 1_024},
        tool_type=ToolType.UTILITY_AGENT,  # #1796: the loop runs only offered tools; an offered search tool is UTILITY_AGENT.
    )
```

**P0-255** (`tests/test_ad1190_delegation_tree_budget.py`: import `offer_scripted`)
SEARCH:
```
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

_DELEGATED_KEYS = {"delegated", "to", "result", "stopped_reason"}
```
REPLACE:
```
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse
from tests.offered_tools import offer_scripted  # #1796: the loop runs only offered tools.

_DELEGATED_KEYS = {"delegated", "to", "result", "stopped_reason"}
```

**P0-256** (`tests/test_ad1190_delegation_tree_budget.py`: `_loop_run`; the inert `test_loop_run_negative_reported_usage_still_stops_at_token_budget`, whose budget stop is charged over a transcript that holds each `probe` result. The other four callers script no call, so `offer_scripted` gives them `[]`, as before.)
SEARCH:
```
    return await loop.run(
        system_prompt="sys", user_message="task", tools=[], context={"agent_id": "a1"},
    )
```
REPLACE:
```
    # #1796: the loop runs only offered tools, so the calls a script makes are offered; a script with none offers nothing.
    return await loop.run(
        system_prompt="sys", user_message="task", tools=offer_scripted(responses), context={"agent_id": "a1"},
    )
```

**P0-257** (`tests/test_ad1356_s3_chain_of_command.py`: import `ToolPermission` and `OfferedMcpTools`)
SEARCH:
```
from probos.tools.effect_tiers import TIER_CRITICAL, filed_call_tier
from tests.test_ad1347_s1_agent_work import RANKS, REASON
```
REPLACE:
```
from probos.tools.effect_tiers import TIER_CRITICAL, filed_call_tier
from probos.tools.protocol import ToolPermission  # #1796: a dispatch run offers its granted tools.
from tests.offered_tools import OfferedMcpTools  # #1796: a dispatch run offers an MCP adapter only through AD-1241.
from tests.test_ad1347_s1_agent_work import RANKS, REASON
```

**P0-258** (`tests/test_ad1356_s3_chain_of_command.py`: CC2, `test_a_chiefs_own_elevated_call_and_another_departments_chief_leave_it_with_the_captain`. The work runs as `laforge-1` (`:167`), and P0-218 grants `forge-1` only. The native tools' rank tables already give READ, and the agent-work gate reads no grant, so this changes nothing on the base tree.)
SEARCH:
```
            async with _chain(rig) as (service, _audit, _told):
                origin = await _thread_in(rig, "engineering", "forge-1")
```
REPLACE:
```
            async with _chain(rig) as (service, _audit, _told):
                # #1796: the loop runs only offered tools; a dispatch run offers its granted tools, and LaForge runs this.
                await rig.permissions.issue_grant("laforge-1", "list_files", ToolPermission.READ)
                origin = await _thread_in(rig, "engineering", "forge-1")
```

**P0-259** (`tests/test_ad1356_s3_chain_of_command.py`: CC5, `test_an_mcp_call_takes_its_tier_from_its_ad1019b_risk`, 5 cases after BF-982's round-1 repair R1 (its `[len65]` and `[slash]` inherit this offer; R1 leaves the four lines below unchanged); D-MCP. This rig's config is a real `SystemConfig`, so the `mcp` section is copied with the flag set rather than replaced with `offer_mcp`'s namespace. `_chain`'s `model_copy` keeps it. The offer is the alias, so CC5 passes at M2 only on BF-982's head, whose script calls the alias (section 6, L5). On the base the offer changes nothing.)
SEARCH:
```
        rig.tools.register(
            tool, provider="AD-1019c", tags=[tool.tool_id, "mcp"], default_permissions=dict.fromkeys(RANKS, "read"),
        )
        async with _chain(rig) as (service, _audit, _told):
```
REPLACE:
```
        rig.tools.register(
            tool, provider="AD-1019c", tags=[tool.tool_id, "mcp"], default_permissions=dict.fromkeys(RANKS, "read"),
        )
        # #1796: the loop runs only offered tools, and a dispatch run offers an MCP adapter only through its AD-1241 offer.
        rig.runtime.mcp_workbench = OfferedMcpTools(tool.tool_id)
        rig.runtime.config = rig.runtime.config.model_copy(
            update={"mcp": rig.runtime.config.mcp.model_copy(update={"agent_tools_enabled": True})},
        )
        async with _chain(rig) as (service, _audit, _told):
```

**The rule for every fixture pair (the Architect applies it; the Builder applies the pairs as written).**
- **A (M0).** A case whose scripted model calls a tool its run does not offer, and whose subject is not the refusal. The only change is to make that tool part of the offer.
  - If the run holds the tool's registration, add `tool_registration_to_llm_definition(<registration>)` to the `tools` it passes. Otherwise add `*offer("<the exact name the script calls>")`.
  - If the run's offer is assembled by the dispatch (`WorkItemAgenticExecutor`, the DM and crew routes, `NativeBuilderHarness`), there is no `tools=` to extend. Grant the tool the way the test grants its others (`issue_grant(<agent>, "<name>", ToolPermission.READ)`), because granted ids are the offer (`agentic_dispatch.py:3081-3089`, `:3588-3596`). A tool in `_GATED_TOOL_IDS` (`:146-151`) is offered through its own block instead; the pair names that block. When the case's subject is the registry's denial, the grant is `ToolPermission.NONE`: it offers the tool and does not change the denial.
  - A helper that receives its script as data offers `*offer_scripted(<the script>)` (P0-111).
  - A runtime built by a synchronous helper gets its grant at the async call site (`await runtime.tool_permission_store.issue_grant(<agent>, "<name>", ToolPermission.READ)`), never inside the helper.
  - An MCP adapter, or `find_mcp_tool`, is never offered by a grant (`agentic_dispatch.py:3075-3086`), only by the AD-1241 offer (`:3088-3135`). A fixture that registers its own adapter calls `offer_mcp(runtime, <the adapter id>)` (P0-243). A fixture with its own AD-1241 source gives it `create_dispatch_offer`, `accepts_dispatch_offer` and `dispatch_tool_ids(candidate_ids=)` (P0-251). A session-correction projection also needs a search tool typed `UTILITY_AGENT` in its source registry (`crew_verifier.py:525-532`; P0-247, P0-253, P0-254).
  - On a bare `AgenticLoop`, a case whose subject is a registry or pre-hook denial is offered like any other; the offer does not change the denial.
  - One inline comment on the changed line: `# #1796: the loop runs only offered tools, so the scripted call's tool is offered.`
  - Nothing else changes: not the script, the assertions, the executor, the registry, or a helper's name.
- **B (M2-F).** A case whose subject is an executor guard reached by an unoffered name: plan mode (AD-1156), AD-1356 S1.1 under confinement, or AD-1189's withheld name that is no longer assembled. It is not made offered. Its pair either drives the executor directly (a code-named call, which the guards still defend) or asserts the loop's refusal. Either way it keeps the case's "the tool did not run" assertion and adds an inline reason.
  - Also B: a registry denial that the dispatch's offer applies as well, so that no grant can offer the tool without lifting the denial. That is a gated id outside its department scope (offered only through its block's `check_permission`), or a tool under a Captain restriction (left out of `granted_ids` and refused by its block's `check_permission`). The offer withholds the tool, so the pair asserts the loop's refusal, and where the case reads `denied_tools`, that it is empty (P2-37, P2-39, P2-40). A rank-table denial of a non-gated tool is A, with a NONE grant.
  - Also B: an MCP alias or `find_mcp_tool` that the AD-1241 offer withdrew or never selected, or that a correction projection denies explicitly (`crew_verifier.py:497-498`). The pair asserts the loop's refusal and an empty `denied_tools`, and keeps the "did not run" assertions. Where a correction's outcome read the denial, it now reads `failed` with `correction_execution_defect` (`crew_verifier.py:2733-2742`) (P2-42 to P2-47).
- **C (M2-F).** A direct caller of `_execute_one_tool` or `_execute_tool_uses`: the call gains `offered=frozenset({<the call's name>})`, with the reason above, comment `# #1796: a direct call passes the offer the loop's step would pass.` Known: `test_ad1187...:1032,1047`, `test_ad1224...:870`, `test_ad1261...:958,1300`.
- **D.** A case that pins request bytes captured on a base tree (for example `tests/fixtures/ad1240_below_threshold_golden.json`, or `_OFF_REQUESTS_SHA256` in `test_ad1189...:76`): the golden is never regenerated. The Architect writes the pair, or records why the case's offer already covers its calls. Where a golden captures the direct loop's own request, the pair asserts the new offer exactly and restores the captured value, as the file already does for fields added after the capture.
- No pair adds a skip, removes an assertion or test function, or weakens a comparison.

### M1

**N1-1.** New file `tests/test_bf965_unoffered_tool_refusal.py`. It imports only names that exist after M0. The refusal is matched by its text; the names M2 adds are read with `getattr` or behind an assert.

```python
"""The agentic loop refuses a call whose tool is not in its request's offer, on every route (#1796).

Each case scripts the model and runs the real loop: with a recording executor; with the DM route's composition
(``AgenticLoop`` + ``DispatchToolExecutor(registry=)``); through ``_run_reserved`` (the AD-1189 rig); through the
native builder; and with the AD-1240 delivery rig. Synthetic fixtures only. A case marked ``until_built("#1796")``
failed on the base at its own assert; M2 adds "#1796" to ``_BUILT``, after which the marker does nothing.
``UNOFFERED_REFUSAL_RUNXFAIL=1`` runs every case plainly. The refusal is matched by its text, and the names M2 adds
are read with ``getattr`` or behind an assert, so on the base a case fails at an assert, not at import.
"""

from __future__ import annotations

import copy
import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.cognitive.swe_harness.agentic_loop as loop_module
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_NOT_FILED,
    CONFINEMENT_REFUSED,
    DispatchToolExecutor,
    ToolCallConfinement,
)
from probos.cognitive.builder import BuildSpec
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
    llm_function_name,
    tool_registration_to_llm_definition,
)
from probos.cognitive.swe_harness.tools import WriteFileTool, register_native_swe_tools
from probos.dm_reply import UNKNOWN_TOOL_LABEL
from probos.events import EventType
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests import test_ad1189_deferred_tool_schemas as ad1189
from tests import test_ad1240_tool_result_delivery as ad1240
from tests.offered_tools import offer
from tests.test_ad546_native_builder_harness import _FakeRegistry

_BUILT: frozenset[str] = frozenset()


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("UNOFFERED_REFUSAL_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_TEXT = (
    "That call names a tool that is not in your current tool list, so it was "
    "refused and did not run. Call only the tools in your list, by the names it "
    "gives. If this step needs another tool, finish what your tools allow and "
    "name the step and the tool it needs."
)
_LOGGER = "probos.cognitive.swe_harness.agentic_loop"
_CONTEXT = {"agent_id": "lt-1", "department": "engineering", "rank": "lieutenant"}


def _call(name: str, call_id: str, **arguments: Any) -> ToolCallRequest:
    return ToolCallRequest(name=name, arguments=arguments, id=call_id)


def _names(tools: list[dict[str, Any]] | None) -> set[str]:
    return {definition["function"]["name"] for definition in tools or []}


class _Model:
    """Answers request N with step N (a list of calls, or text) and keeps a copy of every request."""

    def __init__(self, *steps: list[ToolCallRequest] | str) -> None:
        self.steps = list(steps)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        assert self.steps, "the run asked for more steps than the script holds"
        step = self.steps.pop(0)
        if isinstance(step, str):
            return LLMResponse(content=step, tier="fast", tokens_used=1, content_blocks=[TextBlock(text=step)])
        blocks = [ToolUseBlock(tool_call=call) for call in step]
        return LLMResponse(content="", tier="fast", tokens_used=1, content_blocks=blocks)


class _Executor:
    """The loop's executor seam only: records each tool id it is asked to run and answers ``ran <id>``."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    async def invoke(self, *, tool_id: str, **kwargs: Any) -> ToolResult:
        self.ran.append(tool_id)
        return ToolResult(output=f"ran {tool_id}")


class _StrictExecutor(_Executor):
    """``_Executor`` under the strict effect profile: the loop asks it to match an operation before each call."""

    protected_effects_enabled = True

    def __init__(self) -> None:
        super().__init__()
        self.matched = 0

    async def match_operation_handle(self, **kwargs: Any) -> None:
        self.matched += 1
        return None


class _Probe:
    """A registered tool with the given id that counts its calls."""

    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "A probe that counts its calls."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {}

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.name = tool_id
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output=f"probe {self.tool_id}")


def _loop(**kwargs: Any) -> AgenticLoop:
    """The loop; a keyword M2 adds is checked first, so the base fails here at an assert."""
    if "also_offered" in kwargs:
        assert "also_offered" in inspect.signature(AgenticLoop).parameters, "also_offered is added in M2"
    return AgenticLoop(**kwargs)


async def _run(loop: AgenticLoop, tools: list[dict[str, Any]]) -> Any:
    return await loop.run(system_prompt="", user_message="", tools=tools, context=dict(_CONTEXT))


def _dm_registry() -> ToolRegistry:
    """The native tools in a registry with no permission store, as T4 of the captain-document tests builds it."""
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    return registry


def _defined(registry: ToolRegistry, *tool_ids: str) -> list[dict[str, Any]]:
    return [tool_registration_to_llm_definition(registry.get(tool_id)) for tool_id in tool_ids]


def _write_spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each path ``WriteFileTool.invoke`` is asked to write, recorded before the real tool runs."""
    reached: list[str] = []
    real = WriteFileTool.invoke

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    return reached


def test_the_refusal_text_is_not_a_capability_gap() -> None:
    """A13: the decomposer must not read the refusal as the model reporting a missing capability."""
    assert not is_capability_gap(_TEXT)


@until_built("#1796")
def test_the_refusal_is_public_never_ran_and_never_a_fault() -> None:
    """Design 3, A2, A13: the constant is this text, a never-ran refusal, and a policy refusal to fault detection."""
    assert getattr(loop_module, "UNOFFERED_TOOL_REFUSAL", None) == _TEXT
    assert _TEXT in agentic_dispatch._NEVER_RAN_REFUSALS
    assert agentic_dispatch.classify_tool_fault_error(_TEXT) == "permission_denied"


async def test_an_offered_write_file_call_still_reaches_the_tool_on_the_dm_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: the DM composition runs an offered tool as before."""
    reached = _write_spy(monkeypatch)
    registry = _dm_registry()
    target = str(tmp_path / "c1.md")
    model = _Model([_call("write_file", "c1-write", path=target, content="x")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry))
    result = await _run(loop, _defined(registry, "read_file", "write_file"))
    assert reached == [target] and result.stopped_reason == "complete"


@until_built("#1796")
async def test_a1_an_unoffered_write_file_call_is_refused_on_the_dm_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1: the tool is not reached, the model is shown the refusal, and the run goes on to its next step."""
    reached = _write_spy(monkeypatch)
    registry = _dm_registry()
    executor = DispatchToolExecutor(registry=registry)
    target = str(tmp_path / "a1.md")
    model = _Model([_call("write_file", "a1-write", path=target, content="x")], "done")
    tools = _defined(registry, "read_file")
    assert registry.get("write_file") is not None and "write_file" not in _names(tools)  # premise
    result = await _run(AgenticLoop(llm_client=model, tool_executor=executor), tools)
    assert reached == []
    assert f"[tool_result:a1-write error=True]\n{_TEXT}" in model.requests[1].prompt
    assert result.stopped_reason == "complete" and len(model.requests) == 2
    assert executor.denied_tools == []


@until_built("#1796")
async def test_a2_through_run_reserved_a_refusal_is_not_a_denial_a_defect_or_a_named_failure(tmp_path: Path) -> None:
    """A2 (amended, D3): two refused calls; no denial, no defect, and the failure list shows only the unknown label."""
    spare = _Probe("spare_probe")
    script = [[_call("spare_probe", "a2-first")], [_call("spare_probe", "a2-second")], "a2 complete"]
    async with ad1189._environment(tmp_path, "a2") as env:
        env.registry.register(spare)
        outcome, llm = await ad1189._run(env, ad1189._config("namespace", structured=False), script)
    assert "spare_probe" not in _names(llm.requests[0].tools)  # premise: registered, never offered
    assert spare.calls == 0
    assert outcome.stopped_reason == "complete" and outcome.denied_tools == []
    assert outcome.tool_failures.names() == (UNKNOWN_TOOL_LABEL,)
    assert outcome.tool_defect is None


@until_built("#1796")
async def test_a3_the_native_builder_refuses_a_registered_tool_outside_its_build_offer(tmp_path: Path) -> None:
    """A3: the second loop is guarded by the same check, with no keyword of its own."""
    registry = _FakeRegistry()
    for tool_id in ("read_file", "write_file", "system_self_model"):
        registry.add(tool_id)
    executor = _Executor()
    model = _Model([_call("system_self_model", "a3-unoffered")], "done")
    harness = NativeBuilderHarness(
        runtime=SimpleNamespace(emit_event=lambda *a, **k: None), llm_client=model,
        tool_executor=executor, tool_registry=registry,
    )
    result = await harness.run_build(BuildSpec(title="t", description="d"), work_dir=str(tmp_path))
    assert "system_self_model" not in _names(model.requests[0].tools)  # premise: outside the build offer
    assert executor.ran == []
    assert f"[tool_result:a3-unoffered error=True]\n{_TEXT}" in model.requests[1].prompt
    assert result["metadata"]["stopped_reason"] == "complete"


@until_built("#1796")
async def test_a4_the_parallel_path_refuses_an_unoffered_allowlisted_name_and_runs_its_siblings() -> None:
    """A4: with the AD-1147 fan-out on, the refusal keeps its slot and the offered siblings run, in request order."""
    executor = _Executor()
    model = _Model([_call("web_search", "a4-1"), _call("http_fetch", "a4-2"), _call("read_page", "a4-3")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, parallel_tool_calls_enabled=True)
    assert {"web_search", "http_fetch", "read_page"} <= loop_module.PARALLEL_SAFE_TOOL_IDS  # premise
    result = await _run(loop, offer("web_search", "read_page"))
    assert sorted(executor.ran) == ["read_page", "web_search"]
    assert [r.id for r in result.tool_results] == ["a4-1", "a4-2", "a4-3"]
    assert [(r.output, r.is_error) for r in result.tool_results] == [
        ("ran web_search", False), (_TEXT, True), ("ran read_page", False),
    ]


@until_built("#1796")
async def test_a5_the_offered_alias_runs_and_the_unshown_canonical_id_is_refused() -> None:
    """A5: matching is exact; the executor's BF-754 resolution of the alias is unchanged."""
    registry = ToolRegistry()
    probe = _Probe("mcp:fixture:probe")
    registration = registry.register(probe)
    alias = llm_function_name(probe.tool_id)
    assert alias != probe.tool_id  # premise: the model is shown the provider-safe alias
    model = _Model([_call(alias, "a5-alias"), _call(probe.tool_id, "a5-canonical")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry))
    result = await _run(loop, [tool_registration_to_llm_definition(registration)])
    assert probe.calls == 1
    assert [(r.id, r.is_error) for r in result.tool_results] == [("a5-alias", False), ("a5-canonical", True)]
    assert result.tool_results[1].output == _TEXT


@until_built("#1796")
async def test_a6_the_mid_turn_refresh_moves_the_offer_from_the_next_step() -> None:
    """A6: a tool the BF-755 refresh adds runs from the next step, and one it removes is refused from then on."""
    executor = _Executor()
    model = _Model([_call("alpha", "a6-1")], [_call("gamma", "a6-2"), _call("beta", "a6-3")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, refresh_tools=lambda: offer("alpha", "gamma"))
    result = await _run(loop, offer("alpha", "beta"))
    assert executor.ran == ["alpha", "gamma"]
    assert result.tool_results[2].id == "a6-3" and result.tool_results[2].output == _TEXT


async def test_a7_the_recovery_reader_that_delivery_adds_is_admitted(tmp_path: Path) -> None:
    """A7 (control): the dispatcher's offer has no reader; AD-1240 adds one, and the readbacks through it run."""
    runtime, executor, context = ad1240._environment(tmp_path)
    raw = ad1240._RawTool(ToolResult(output="fixture line\n" * 1200))
    registration = runtime.tool_registry.register(raw)
    tools = [tool_registration_to_llm_definition(registration)]
    assert "read_file" not in _names(tools)  # premise
    llm = ad1240._ReadbackLLM(ad1240._turn(), raw.result.output)
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        workspace_results=runtime.workspace_results,
    )
    async with ad1240._started(runtime):
        result = await loop.run(system_prompt="", user_message="", tools=tools, context=context)
    assert result.stopped_reason == "complete" and len(llm.readbacks) == 2
    assert all(item.output != _TEXT for item in result.tool_results)


@until_built("#1796")
async def test_a8_a_withheld_loadable_tool_gets_the_deferred_refusal_and_any_other_name_the_offer_refusal(
    tmp_path: Path,
) -> None:
    """A8: AD-1189 names a withheld tool only inside load_tools; the loop admits it and the executor's guard answers it."""
    direct = _call("heavy_probe", "a8-direct", **ad1189._HEAVY_ARGS)
    ghost = _call("ghost_probe", "a8-ghost")
    config = ad1189._config("namespace", structured=False, threshold=ad1189._THRESHOLD)
    async with ad1189._environment(tmp_path, "a8") as env:
        outcome, llm = await ad1189._run(env, config, [[direct, ghost], "a8 complete"])
    first, second = llm.requests[0], llm.requests[1]
    assert "heavy_probe" not in _names(first.tools)  # premise: withheld ...
    assert ad1189._manifest_names(first.tools) == ["heavy_probe"]  # ... and loadable
    assert "[tool_result:a8-direct error=True]" in second.prompt
    assert agentic_dispatch._DEFERRED_SCHEMA_REFUSAL in second.prompt
    assert f"[tool_result:a8-ghost error=True]\n{_TEXT}" in second.prompt
    assert env.heavy.calls == [] and outcome.denied_tools == []


@until_built("#1796")
async def test_a9_an_unoffered_tool_never_reaches_the_confinement_gate() -> None:
    """A9: the loop refuses first; an offered tool outside the confinement set still reaches the gate."""
    registry = _dm_registry()
    seen: list[str] = []

    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        seen.append(tool_id)
        return CONFINEMENT_REFUSED

    executor = DispatchToolExecutor(registry=registry)
    executor.confine_calls(ToolCallConfinement(tool_ids=frozenset({"read_file"}), gate=gate))
    model = _Model([_call("write_file", "a9-unoffered", path="a9.md", content="x"), _call("edit_file", "a9-offered")], "done")
    result = await _run(AgenticLoop(llm_client=model, tool_executor=executor), _defined(registry, "read_file", "edit_file"))
    assert seen == ["edit_file"]
    assert result.tool_results[0].output == _TEXT
    assert CONFINED_CALL_NOT_FILED in model.requests[1].prompt


@until_built("#1796")
async def test_a10_under_the_strict_profile_a_refusal_opens_no_operation_and_fires_no_start() -> None:
    """A10: no operation is matched, the executor is not called, and no STARTED event fires."""
    events: list[Any] = []
    executor = _StrictExecutor()
    model = _Model([_call("write_file", "a10-unoffered", path="a10.md", content="x")], "done")
    loop = AgenticLoop(llm_client=model, tool_executor=executor, event_emit_fn=lambda kind, payload: events.append(kind))
    result = await _run(loop, offer("read_file"))
    assert EventType.AGENTIC_LOOP_ITERATION in events  # premise: the emitter is wired
    assert executor.ran == [] and executor.matched == 0
    assert EventType.AGENTIC_TOOL_CALL_STARTED not in events
    assert result.tool_results[0].output == _TEXT and result.stopped_reason == "complete"


@until_built("#1796")
async def test_a11_every_call_gets_one_result_and_the_log_holds_no_raw_name(caplog: pytest.LogCaptureFixture) -> None:
    """A11: structured messages pair each tool-call id once; one INFO line, with an opaque tool identity."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    executor = _Executor()
    raw_name = "zz_unoffered_probe"
    model = _Model([_call("alpha", "a11-offered"), _call(raw_name, "a11-unoffered")], "done")
    await _run(AgenticLoop(llm_client=model, tool_executor=executor, structured_tool_messages=True), offer("alpha"))
    second = model.requests[1]
    assert [m["tool_call_id"] for m in second.messages if m.get("role") == "tool"] == ["a11-offered", "a11-unoffered"]
    messages = [record.getMessage() for record in caplog.records if record.name == _LOGGER]
    assert sum("outside the offer" in message for message in messages) == 1
    assert not any(raw_name in message for message in messages)
    assert executor.ran == ["alpha"]


@until_built("#1796")
async def test_also_offered_names_are_admitted_and_a_failing_source_admits_only_the_offer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design 5: ``also_offered`` widens the set; if it raises, a warning is logged and only the request's offer is admitted."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    admitted = _Executor()
    model = _Model([_call("alpha", "ao-1"), _call("beta", "ao-2")], "done")
    await _run(_loop(llm_client=model, tool_executor=admitted, also_offered=lambda: frozenset({"beta"})), offer("alpha"))
    assert admitted.ran == ["alpha", "beta"]

    def unreadable() -> frozenset[str]:
        raise RuntimeError("fixture: the loadable names cannot be read")

    refused = _Executor()
    model = _Model([_call("alpha", "ao-3"), _call("beta", "ao-4")], "done")
    result = await _run(_loop(llm_client=model, tool_executor=refused, also_offered=unreadable), offer("alpha"))
    assert refused.ran == ["alpha"] and result.tool_results[1].output == _TEXT
    assert any("loadable tool names" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


@until_built("#1796")
def test_loadable_names_follow_the_latest_build_and_what_was_presented_in_full() -> None:
    """Design 5: ``(withheld & last built) - presented``; empty before a build arms the offer."""
    assert getattr(ad1189._offer(), "loadable_names", lambda: None)() == frozenset()
    manifest, definitions = ad1189._armed_offer("heavy_b", "heavy_c")
    loadable = getattr(manifest, "loadable_names", lambda: None)
    assert loadable() == frozenset({"heavy_b", "heavy_c"})
    manifest.present([d for d in definitions if d["function"]["name"] != "heavy_b"], keep_full=frozenset())
    assert loadable() == frozenset({"heavy_c"})  # a build that no longer assembles heavy_b
    manifest.present(definitions, keep_full=frozenset())
    assert manifest.request(names=["heavy_c"], query=None)["requested"] == ["heavy_c"]
    assert loadable() == frozenset({"heavy_b", "heavy_c"})  # requested, not yet shown in full
    manifest.present(definitions, keep_full=frozenset())
    manifest.commit_presentation()
    assert loadable() == frozenset({"heavy_b"})  # shown in full: now in the request's own tools
```

**How the built cases fail on the base (expected).** The constants case fails at the `getattr` assert. In A1 the spy is reached. In A2 the probe runs once per call. In A3, A4 and A10 the executor runs the unoffered name. In A5 the canonical id runs. In A6 `beta` runs. In A8 the ghost has no refusal. In A9 the gate sees `write_file`. In A11 there is no refusal line. The also-offered and loadable-names cases fail at their asserts on the missing names. A7 and the two controls pass on both trees.

### M2

**P2-1** (`src/probos/cognitive/swe_harness/agentic_loop.py`: import)
SEARCH:
```
from probos.tools.delegation_evidence import MESSAGE_OMISSION_MARKER, evidence_frame
from probos.tools.executor import recording_identity, tool_recording_scope
from probos.tools.protocol import ToolResult, ToolResultPresentation
```
REPLACE:
```
from probos.tools.delegation_evidence import MESSAGE_OMISSION_MARKER, evidence_frame
from probos.tools.executor import recording_identity, tool_record_identity, tool_recording_scope
from probos.tools.protocol import ToolResult, ToolResultPresentation
```

**P2-2** (`agentic_loop.py`: the constant)
SEARCH:
```
PARALLEL_TOOL_CALLS_DEFAULT = 3
PARALLEL_TOOL_CALLS_MAX = 16

# AD-1148 / DD-3: truncation is visible to the model. The marker states that
```
REPLACE:
```
PARALLEL_TOOL_CALLS_DEFAULT = 3
PARALLEL_TOOL_CALLS_MAX = 16

# BF-965 (#1796): the model-facing refusal of a call that names a tool outside the
# request's offer. Error-shaped and final, in the AD-1154 voice; it names no tool,
# must not match ``_CAPABILITY_GAP_RE`` (``probos.cognitive.decomposer``) and is
# never defect evidence (``agentic_dispatch._NEVER_RAN_REFUSALS``).
UNOFFERED_TOOL_REFUSAL: str = (
    "That call names a tool that is not in your current tool list, so it was "
    "refused and did not run. Call only the tools in your list, by the names it "
    "gives. If this step needs another tool, finish what your tools allow and "
    "name the step and the tool it needs."
)

# AD-1148 / DD-3: truncation is visible to the model. The marker states that
```

**P2-3** (`agentic_loop.py`: the set)
SEARCH:
```
            return delivery.code, delivery.presentation
    return None


def _observe_completion_spend(
```
REPLACE:
```
            return delivery.code, delivery.presentation
    return None


def _offered_tool_names(
    tools: list[dict[str, Any]] | None,
    also_offered: Callable[[], frozenset[str]] | None,
    agent_id: str,
) -> frozenset[str]:
    """BF-965 (#1796): the names one step may call, matched later by exact string.

    The ``function.name`` of each definition in the request that produced the
    response, plus the AD-1189 loadable names when ``also_offered`` is set. A
    failing ``also_offered`` costs the loadable names, never the offer.
    """
    names: set[str] = set()
    for definition in tools or ():
        function = definition.get("function") if isinstance(definition, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    if also_offered is None:
        return frozenset(names)
    try:
        loadable = frozenset(name for name in also_offered() if type(name) is str)
    except Exception:
        logger.warning(
            "BF-965: the loadable tool names for agent %s could not be read; this "
            "step admits only the tools its request offered", agent_id[:12], exc_info=True,
        )
        loadable = frozenset()
    return frozenset(names) | loadable


def _observe_completion_spend(
```

**P2-4** (`agentic_loop.py`: constructor keyword)
SEARCH:
```
        workspace_results: WorkspaceResults | None = None,
    ) -> None:
        self._llm = llm_client
```
REPLACE:
```
        workspace_results: WorkspaceResults | None = None,
        also_offered: Callable[[], frozenset[str]] | None = None,
    ) -> None:
        self._llm = llm_client
```

**P2-5** (`agentic_loop.py`: constructor body)
SEARCH:
```
        # AD-1240: None (every caller that injects no owner) keeps legacy delivery.
        # The assignment goes through the slot, so an invalid owner is refused here.
        if workspace_results is not None:
            self.workspace_results = workspace_results
```
REPLACE:
```
        # BF-965: the AD-1189 names of withheld tools, shown only inside the load_tools
        # definition and admitted beside each request's offer. None (every caller
        # without an armed manifest) admits the request's offer alone.
        self._also_offered = also_offered
        # AD-1240: None (every caller that injects no owner) keeps legacy delivery.
        # The assignment goes through the slot, so an invalid owner is refused here.
        if workspace_results is not None:
            self.workspace_results = workspace_results
```

**P2-6** (`agentic_loop.py`: `_run_scoped`, the step's set)
SEARCH:
```
                    self._max_iter - counted_iterations - (1 if _counts_toward_max_iterations(tool_uses) else 0),
                )
            tool_results = await self._execute_tool_uses(
                tool_uses,
                agent_id=agent_id,
```
REPLACE:
```
                    self._max_iter - counted_iterations - (1 if _counts_toward_max_iterations(tool_uses) else 0),
                )
            # BF-965 (#1796): the names this step may call are the offer of the request that
            # produced the response (an AD-1324 floor re-issue keeps its tools), with the
            # AD-1189 loadable names; read once per step, matched exactly.
            offered = _offered_tool_names(req.tools, self._also_offered, agent_id)
            tool_results = await self._execute_tool_uses(
                tool_uses,
                offered=offered,
                agent_id=agent_id,
```

**P2-7** (`agentic_loop.py`: `_execute_tool_uses` signature)
SEARCH:
```
    async def _execute_tool_uses(
        self,
        tool_uses: list[ToolUseBlock],
        *,
        agent_id: str,
```
REPLACE:
```
    async def _execute_tool_uses(
        self,
        tool_uses: list[ToolUseBlock],
        *,
        offered: frozenset[str],
        agent_id: str,
```

**P2-8** (`agentic_loop.py`: the sequential path)
SEARCH:
```
        if not self._parallel_tool_calls_enabled:
            return [
                await self._execute_one_tool(
                    use, agent_id=agent_id, iteration=iteration, context=context,
```
REPLACE:
```
        if not self._parallel_tool_calls_enabled:
            return [
                await self._execute_one_tool(
                    use, offered=offered, agent_id=agent_id, iteration=iteration, context=context,
```

**P2-9** (`agentic_loop.py`: the parallel subset)
SEARCH:
```
                async with semaphore:
                    return await self._execute_one_tool(
                        tool_uses[index],
                        agent_id=agent_id,
```
REPLACE:
```
                async with semaphore:
                    return await self._execute_one_tool(
                        tool_uses[index],
                        offered=offered,
                        agent_id=agent_id,
```

**P2-10** (`agentic_loop.py`: the sequential remainder)
SEARCH:
```
        for index in sequential_indices:
            by_index[index] = await self._execute_one_tool(
                tool_uses[index],
                agent_id=agent_id,
```
REPLACE:
```
        for index in sequential_indices:
            by_index[index] = await self._execute_one_tool(
                tool_uses[index],
                offered=offered,
                agent_id=agent_id,
```

**P2-11** (`agentic_loop.py`: `_execute_one_tool` signature)
SEARCH:
```
    async def _execute_one_tool(
        self,
        use: ToolUseBlock,
        *,
        agent_id: str,
```
REPLACE:
```
    async def _execute_one_tool(
        self,
        use: ToolUseBlock,
        *,
        offered: frozenset[str],
        agent_id: str,
```

**P2-12** (`agentic_loop.py`: the check)
SEARCH:
```
        :class:`InvocationRefusal` (a control record, not a producer outcome):
        no executor call, no event, no hook and no observer ever sees it.
        """
        correlation = (
```
REPLACE:
```
        :class:`InvocationRefusal` (a control record, not a producer outcome):
        no executor call, no event, no hook and no observer ever sees it.

        BF-965 (#1796): a call whose name is not in ``offered`` is refused first, as
        an error result the model sees, before the AD-1240 invocation context, the
        STARTED event, fault capture and the executor. Exact match: an offered
        provider alias passes, the canonical id it stands for does not.
        """
        if use.tool_call.name not in offered:
            logger.info(
                "BF-965: refused a call to a tool outside the offer agent=%s tool=%s "
                "iteration=%d; it did not run",
                agent_id[:12], tool_record_identity(use.tool_call.name), iteration,
            )
            return ToolCallResult(id=use.tool_call.id, output=UNOFFERED_TOOL_REFUSAL, is_error=True)
        correlation = (
```

**P2-13** (`src/probos/cognitive/agentic_dispatch.py`: import)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import (
    AGENTIC_DEFAULT_TIER,
    AgenticBudgetAwarenessState,
)
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import (
    AGENTIC_DEFAULT_TIER,
    UNOFFERED_TOOL_REFUSAL,
    AgenticBudgetAwarenessState,
)
```

**P2-14** (`agentic_dispatch.py`: never ran)
SEARCH:
```
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset({
    _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,
    CONFINED_CALL_ANSWERED, UNREGISTERED_TOOL_REFUSAL,
})
```
REPLACE:
```
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset({
    _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,
    CONFINED_CALL_ANSWERED, UNREGISTERED_TOOL_REFUSAL,
    UNOFFERED_TOOL_REFUSAL,  # BF-965 (#1796): the loop refused a tool outside the offer
})
```

**P2-15** (`agentic_dispatch.py`: fault classification; the native builder observes raw results, `native_builder.py:181-185`)
SEARCH:
```
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947
            UNREGISTERED_TOOL_REFUSAL,  # AD-1356 S1.1
            "consensus_blocked", "requires_confirmation",
```
REPLACE:
```
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED, CONFINED_CALL_ANSWERED,  # AD-1347 S3, BF-947
            UNREGISTERED_TOOL_REFUSAL,  # AD-1356 S1.1
            UNOFFERED_TOOL_REFUSAL,  # BF-965 (#1796): a refused unoffered call is not a fault
            "consensus_blocked", "requires_confirmation",
```

**P2-16** (`agentic_dispatch.py`: the plan-mode comment that M2 makes stale)
SEARCH:
```
        # matching invoke-time guard -- one decision, two consequences (BF-690).
        # The guard is what holds for a tool the model names without being
        # offered it, because the registry resolves every REGISTERED tool; it
        # refuses before a call is resolved, parked (AD-1154) or run. Filtered
```
REPLACE:
```
        # matching invoke-time guard -- one decision, two consequences (BF-690).
        # BF-965: the loop refuses a tool the model names without being offered
        # it before any executor sees the call; this guard stays as defence in
        # depth, because the registry resolves every REGISTERED tool and a direct
        # executor call is checked against no offer. It refuses before a call is
        # resolved, parked (AD-1154) or run. Filtered
```

**P2-17** (`agentic_dispatch.py`: wiring, armed only)
SEARCH:
```
        # AD-1189: an armed manifest needs the same seam; both off => no kwarg.
        if (mcp_offer_armed and mcp_offer is not None) or manifest_offer is not None:
            _loop_kwargs["refresh_tools"] = _refresh_tools
```
REPLACE:
```
        # AD-1189: an armed manifest needs the same seam; both off => no kwarg.
        if (mcp_offer_armed and mcp_offer is not None) or manifest_offer is not None:
            _loop_kwargs["refresh_tools"] = _refresh_tools
        # BF-965: a withheld, loadable tool is named only inside load_tools, so the
        # loop's offer check admits it and the AD-1189 guard answers the call. Unarmed
        # => no kwarg, so a loop double pinning the unarmed keywords is unchanged.
        if manifest_offer is not None:
            _loop_kwargs["also_offered"] = manifest_offer.loadable_names
```

**P2-18** (`src/probos/cognitive/tool_manifest.py`: `loadable_names`)
SEARCH:
```
    def has_pending_loads(self) -> bool:
        """True while a requested definition the latest build assembles is not presented."""
        return bool((self._requested - self._presented) & self._last_built)
```
REPLACE:
```
    def has_pending_loads(self) -> bool:
        """True while a requested definition the latest build assembles is not presented."""
        return bool((self._requested - self._presented) & self._last_built)

    def loadable_names(self) -> frozenset[str]:
        """BF-965: withheld names the latest build assembles and has not shown in full.

        The ``load_tools`` definition lists them by name only, so the agentic loop
        admits a call to one beside the request's offer and :meth:`withhold_call`
        answers it. Empty until a build arms the offer (nothing is withheld before).
        """
        return (self._withheld & self._last_built) - self._presented
```

**P2-19** (`tool_manifest.py`: `request` reuses it)
SEARCH:
```
            raise ValueError("load_tools query must be a bounded string")
        loadable = (self._withheld & self._last_built) - self._presented
```
REPLACE:
```
            raise ValueError("load_tools query must be a bounded string")
        loadable = self.loadable_names()
```

**P2-20** (`tool_manifest.py`: the docstring that M2 makes stale)
SEARCH:
```
        A withheld name the latest build no longer assembles is not refused here:
        the executor resolves it as it resolves any name outside the offer.
```
REPLACE:
```
        A withheld name the latest build no longer assembles is not refused here.
        It is not in :meth:`loadable_names`, so the agentic loop refuses it first as
        a name outside the offer (BF-965).
```

**P2-21** (`tests/test_bf943_captain_document_write_refusal.py`: imports)
SEARCH:
```
from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool, register_native_swe_tools
```
REPLACE:
```
from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.agentic_loop import UNOFFERED_TOOL_REFUSAL, AgenticLoop
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock, tool_registration_to_llm_definition
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool, register_native_swe_tools
```
SEARCH:
```
from probos.types import IntentMessage
from tests.posix_stat import _posix_stat
```
REPLACE:
```
from probos.types import IntentMessage, LLMResponse
from tests.posix_stat import _posix_stat
```

**P2-22** (`tests/test_bf943_captain_document_write_refusal.py`: T4 in place, A12)
SEARCH:
```
async def test_a_lieutenants_unoffered_write_file_call_reaches_the_tool_on_the_dm_route(
    checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4, acceptance 1 and the severity: the DM route's executor runs a registered tool the model was never offered.

    The route builds ``DispatchToolExecutor(registry=)`` with no confinement and offers only the Captain's grants; the loop's call passes no
    ``required``, so ``check_and_invoke`` asks for READ, and the rank matrix gives a lieutenant WRITE. A pass on both trees (it is about the
    route, not the rule); if it fails the route is closed and P3-1 says Medium.
    """
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    reached: list[str] = []
    real = WriteFileTool.invoke

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    target = str(checkout / "docs" / "dm.md")
    result = await DispatchToolExecutor(registry=registry).invoke(
        agent_id="lt-1", tool_id="write_file", params={"path": target, "content": "x"},
        agent_department="engineering", agent_rank="lieutenant", context={})
    assert reached == [target] and result.success, result.error
```
REPLACE:
```
async def test_a_lieutenants_unoffered_write_file_call_is_refused_by_the_loop_on_the_dm_route(
    checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4, acceptance 1 and the severity, updated for #1796: the DM route refuses a registered tool the model was never offered.

    The route builds ``DispatchToolExecutor(registry=)`` with no confinement and offers only the Captain's grants. Before #1796 this case
    called the executor directly and showed it writing: the registry resolves any registered tool the rank permits. #1796 put the offer
    check in the loop every model-named call passes through, so the case drives the loop as ``_run_reserved`` composes it, offers
    ``read_file`` only, and asserts the call is refused before ``WriteFileTool.invoke``. It passes only once #1796 is built.
    """
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    reached: list[str] = []
    real = WriteFileTool.invoke
    target = str(checkout / "docs" / "dm.md")

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    class _Model:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def complete(self, request, **kwargs):  # type: ignore[no-untyped-def]
            self.prompts.append(request.prompt)
            if len(self.prompts) == 1:
                call = ToolCallRequest(name="write_file", arguments={"path": target, "content": "x"}, id="t4-write")
                return LLMResponse(content="", tokens_used=1, content_blocks=[ToolUseBlock(tool_call=call)])
            return LLMResponse(content="done", tokens_used=1, content_blocks=[TextBlock(text="done")])

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    model = _Model()
    loop = AgenticLoop(llm_client=model, tool_executor=DispatchToolExecutor(registry=registry))
    result = await loop.run(
        system_prompt="", user_message="", tools=[tool_registration_to_llm_definition(registry.get("read_file"))],
        context={"agent_id": "lt-1", "department": "engineering", "rank": "lieutenant"})
    assert reached == [] and result.stopped_reason == "complete"
    assert result.tool_results[0].is_error and result.tool_results[0].output == UNOFFERED_TOOL_REFUSAL
    assert f"[tool_result:t4-write error=True]\n{UNOFFERED_TOOL_REFUSAL}" in model.prompts[1]
```

**P2-23** (`tests/test_bf965_unoffered_tool_refusal.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset()
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1796"})
```

**M2-F.** P2-24 to P2-28 (Part 1, Category C) and P2-29 (Part 2, Category D) follow. Part 3a-1 adds P2-30 to P2-35 (Category B). Part 3a-2 adds P2-36 to P2-40 (Category B). Part 3b adds P2-41 to P2-47 (Category B). They commit with P2-1 to P2-23.

**P2-24** (`tests/test_ad1187_agent_work_pull.py`: `:1032`, `test_loop_invalid_presentation_bounds_refuse_admission`)
SEARCH:
```
        ToolUseBlock(ToolCallRequest(name="claim_work_item")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
    )
```
REPLACE:
```
        ToolUseBlock(ToolCallRequest(name="claim_work_item")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
        offered=frozenset({"claim_work_item"}),  # #1796: a direct call passes the offer the loop's step would pass.
    )
```

**P2-25** (`tests/test_ad1187_agent_work_pull.py`: `:1047`, `test_loop_rendering_failure_is_error_not_successful_empty`)
SEARCH:
```
        ToolUseBlock(ToolCallRequest(name="discover_work_items")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
    )
```
REPLACE:
```
        ToolUseBlock(ToolCallRequest(name="discover_work_items")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
        offered=frozenset({"discover_work_items"}),  # #1796: a direct call passes the offer the loop's step would pass.
    )
```

**P2-26** (`tests/test_ad1224_durable_tool_start.py`: `:870`)
SEARCH:
```
        ToolUseBlock(tool_call=ToolCallRequest(id="c1", name="read_file", arguments={"path": "a"})),
        agent_id="agent-9", iteration=4, context=caller_context,
    )
```
REPLACE:
```
        ToolUseBlock(tool_call=ToolCallRequest(id="c1", name="read_file", arguments={"path": "a"})),
        agent_id="agent-9", iteration=4, context=caller_context,
        offered=frozenset({"read_file"}),  # #1796: a direct call passes the offer the loop's step would pass.
    )
```

**P2-27** (`tests/test_ad1261_authority_domain.py`: the `_execute_retention` helper at `:958`; this one pair covers the 31 TypeErrors there)
SEARCH:
```
            id="retention-read",
        )),
        agent_id=_SUBJECT, iteration=1, context={"agent_id": _SUBJECT},
    )
```
REPLACE:
```
            id="retention-read",
        )),
        agent_id=_SUBJECT, iteration=1, context={"agent_id": _SUBJECT},
        offered=frozenset({tool_id}),  # #1796: a direct call passes the offer the loop's step would pass.
    )
```

**P2-28** (`tests/test_ad1261_authority_domain.py`: `:1300`, `test_loop_r2_concurrent_calls_have_separate_retained_pairs`)
SEARCH:
```
                name="self_query", arguments={"domains": [domain]}, id=subject,
            )),
            agent_id=subject, iteration=1, context={"agent_id": subject},
        ))
```
REPLACE:
```
                name="self_query", arguments={"domains": [domain]}, id=subject,
            )),
            agent_id=subject, iteration=1, context={"agent_id": subject},
            offered=frozenset({"self_query"}),  # #1796: a direct call passes the offer the loop's step would pass.
        ))
```

**P2-29** (`tests/test_ad1156_plan_execute_mode.py`, `test_the_plan_mode_refusal_is_a_policy_outcome`: Category D, the pinned set). D3 adds the new constant to `_NEVER_RAN_REFUSALS` (P2-14), and the constant exists only after M2.
SEARCH:
```
    # AD-1356 S1.1: nor one refused because its tool id is not registered.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
        agentic_dispatch.CONFINED_CALL_ANSWERED, agentic_dispatch.UNREGISTERED_TOOL_REFUSAL,
    }
```
REPLACE:
```
    # AD-1356 S1.1: nor one refused because its tool id is not registered; BF-965 (#1796): nor one the loop refused
    # because its tool was not offered.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
        agentic_dispatch.CONFINED_CALL_ANSWERED, agentic_dispatch.UNREGISTERED_TOOL_REFUSAL,
        agentic_dispatch.UNOFFERED_TOOL_REFUSAL,
    }
```

**P2-30** (`tests/test_ad1156_plan_execute_mode.py`: `test_plan_mode_offers_the_allowlist_and_refuses_everything_else`)
SEARCH:
```
    assert _offered(llm.requests[0]) == ["http_fetch"]
    assert (writer.calls, hidden.calls, len(fetch.calls)) == ([], [], 1)
    assert _transcript(llm.requests[1]).count(_REFUSAL) == 1
    assert _transcript(llm.requests[2]).count(_REFUSAL) == 2
```
REPLACE:
```
    assert _offered(llm.requests[0]) == ["http_fetch"]
    assert (writer.calls, hidden.calls, len(fetch.calls)) == ([], [], 1)
    # BF-965 (#1796): plan mode withholds both tools from the offer, so the loop refuses them before the executor's
    # plan-mode guard is reached; test_the_executor_guard_refuses_before_resolving_the_tool drives that guard directly.
    assert _transcript(llm.requests[1]).count(agentic_dispatch.UNOFFERED_TOOL_REFUSAL) == 1
    assert _transcript(llm.requests[2]).count(agentic_dispatch.UNOFFERED_TOOL_REFUSAL) == 2
    assert _REFUSAL not in _transcript(llm.requests[2])
```

**P2-31** (`tests/test_ad1156_plan_execute_mode.py`: `test_repeated_plan_mode_refusals_are_not_a_tool_defect`, inert)
SEARCH:
```
    assert writer.calls == [] and refused_outcome.tool_defect is None
```
REPLACE:
```
    assert writer.calls == [] and refused_outcome.tool_defect is None
    # BF-965 (#1796): plan mode withholds file_writer from the offer, so both refusals are the loop's; a never-ran
    # refusal is not defect evidence (agentic_dispatch._NEVER_RAN_REFUSALS).
    assert _transcript(refused.requests[2]).count(agentic_dispatch.UNOFFERED_TOOL_REFUSAL) == 2
```

**P2-32** (`tests/test_ad1156_plan_execute_mode.py`: `test_m1_the_mode_command_governs_the_next_real_dm_turn`)
SEARCH:
```
    assert _REFUSAL in _transcript(plan_llm.requests[1])
```
REPLACE:
```
    # BF-965 (#1796): the plan-mode offer withholds file_writer, so the loop refuses it before the executor's guard.
    assert agentic_dispatch.UNOFFERED_TOOL_REFUSAL in _transcript(plan_llm.requests[1])
```

**P2-33** (`tests/test_ad1189_deferred_tool_schemas.py`: `test_load_tools_ungranted_registered_name_is_reported_unknown_and_never_presented`; `ToolPermissionDenied` is still used at `:1138`)
SEARCH:
```
    load, direct = invocations
    assert load.tool_id == _META and load.result is not None and load.result.error is None
    assert load.result.output["unknown"] == ["secret_probe"]
    assert load.result.output["unknown_count"] == 1
    assert load.result.output["requested"] == []
    for request in llm.requests:
        assert "secret_probe" not in _names(request.tools)
        assert "secret_probe" not in _manifest_names(request.tools)
    assert direct.tool_id == "secret_probe"
    assert isinstance(direct.raised, ToolPermissionDenied)
    assert secret.calls == []
    assert outcome.denied_tools == ["secret_probe"]
```
REPLACE:
```
    # BF-965 (#1796): the direct call names a tool its request did not offer and load_tools did not make loadable,
    # so the loop refuses it and the executor (whose permission denial this case used to reach) is never entered.
    (load,) = invocations
    assert load.tool_id == _META and load.result is not None and load.result.error is None
    assert load.result.output["unknown"] == ["secret_probe"]
    assert load.result.output["unknown_count"] == 1
    assert load.result.output["requested"] == []
    for request in llm.requests:
        assert "secret_probe" not in _names(request.tools)
        assert "secret_probe" not in _manifest_names(request.tools)
    assert agentic_dispatch.UNOFFERED_TOOL_REFUSAL in llm.requests[2].prompt
    assert secret.calls == []
    assert outcome.denied_tools == []
```

**P2-34** (`tests/test_ad1356_s1_unknown_tools.py`: UT1 docstring, which is otherwise left stating something false)
SEARCH:
```
    """Acceptance 3: the model is shown the refusal, which names search_capabilities; nothing is filed on the item; the
```
REPLACE:
```
    """Acceptance 3: the model is shown a refusal (the loop's since BF-965); nothing is filed on the item; the
```

**P2-35** (`tests/test_ad1356_s1_unknown_tools.py`: UT1)
SEARCH:
```
        assert requests_for_work_item(rig.requests, item.id) == []
        assert _seen(rig, UNREGISTERED_TOOL_REFUSAL)
```
REPLACE:
```
        assert requests_for_work_item(rig.requests, item.id) == []
        # BF-965 (#1796): an unregistered id is never offered, so the loop refuses it before the executor's AD-1356
        # S1.1 refusal is reached; UT2 drives that refusal directly. Neither is filed or counted as a fault.
        assert _seen(rig, agentic_dispatch.UNOFFERED_TOOL_REFUSAL)
        assert not _seen(rig, UNREGISTERED_TOOL_REFUSAL)
```

**P2-36** (`tests/test_ad1191_delegation_wire.py`: import the refusal constant)
SEARCH:
```
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult
```
REPLACE:
```
from probos.cognitive.swe_harness.agentic_loop import UNOFFERED_TOOL_REFUSAL, AgenticLoop, AgenticResult
```

**P2-37** (`tests/test_ad1191_delegation_wire.py`: `test_target_department_gate_still_prevents_the_producer_from_running`, Category B. The department gate is applied by the offer (the gated block's `check_permission`, `agentic_dispatch.py:3477-3486`), so no grant can offer the tool without lifting the gate. The "did not run" assertions at `:737-740` stay.)
SEARCH:
```
    ref = next(ref for ref in result.evidence.source_refs if ref.kind == "tool_trace")
    trace = json.loads(runtime.attachment_store.blobs[ref.content_hash])
    assert trace[0]["is_error"] is True and "has none on publish_finding" in trace[0]["output"]
```
REPLACE:
```
    ref = next(ref for ref in result.evidence.source_refs if ref.kind == "tool_trace")
    trace = json.loads(runtime.attachment_store.blobs[ref.content_hash])
    # BF-965 (#1796): the department gate withholds publish_finding from the child's offer, so the loop refuses the
    # call before the registry's own department check is reached.
    offered = [(definition.get("function") or {}).get("name") for definition in (llm.requests[0].tools or [])]
    assert "publish_finding" not in offered
    assert trace[0]["is_error"] is True and trace[0]["output"] == UNOFFERED_TOOL_REFUSAL
```

**P2-38** (`tests/test_ad1258_self_knowledge.py`: import the refusal constant)
SEARCH:
```
from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
from probos.cognitive.swe_harness.tool_call import (
```
REPLACE:
```
from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
from probos.cognitive.swe_harness.agentic_loop import UNOFFERED_TOOL_REFUSAL
from probos.cognitive.swe_harness.tool_call import (
```

**P2-39** (`tests/test_ad1258_self_knowledge.py`: `test_loop_self_query_errors_reach_model_without_telemetry_reads[captain-restriction-*]`, Category B, the error the model is shown. The restriction is left out of the granted ids, and `self_query`'s block asks `check_permission` (`agentic_dispatch.py:3428-3435`).)
SEARCH:
```
        assert runtime.tool_permission_store.get_active_grants_sync(
            "baseline-agent", "self_query",
        ) == [grant]
        error = (
            "Tool self_query failed: Agent baseline-agent has none on self_query, "
            "needs read"
        )
```
REPLACE:
```
        assert runtime.tool_permission_store.get_active_grants_sync(
            "baseline-agent", "self_query",
        ) == [grant]
        # BF-965 (#1796): the restriction withholds self_query from the offer, so the loop refuses the call before the
        # registry's permission denial is reached.
        error = UNOFFERED_TOOL_REFUSAL
```

**P2-40** (`tests/test_ad1258_self_knowledge.py`: the same case, `denied_tools`. The `resolve_permission(...) is NONE` assertion stays.)
SEARCH:
```
    if reason == "captain-restriction":
        assert "self_query" not in offered
        assert outcome.denied_tools == ["self_query"]
```
REPLACE:
```
    if reason == "captain-restriction":
        assert "self_query" not in offered
        assert outcome.denied_tools == []  # BF-965 (#1796): a call the loop refused is not a denial; AD-855 files nothing.
```

**P2-41** (`tests/test_ad1126_verified_finalization.py`: import the refusal constant)
SEARCH:
```
from probos.cognitive.mcp_workbench import MCPDispatchOffer  # #1796: a correction offers MCP tools only through its source's AD-1241 offer.
```
REPLACE:
```
from probos.cognitive.mcp_workbench import MCPDispatchOffer  # #1796: a correction offers MCP tools only through its source's AD-1241 offer.
from probos.cognitive.swe_harness.agentic_loop import UNOFFERED_TOOL_REFUSAL
```

**P2-42** (`tests/test_ad1126_verified_finalization.py`: `test_session_correction_find_mcp_tool_absent_registration_is_explicitly_denied_without_shared_mutation`, Category B. The run denies the missing finder explicitly, so its offer withholds it (`crew_verifier.py:363-364`, `:497-498`). The "did not run" assertions after the outcome stay.)
SEARCH:
```
    assert outcome.status == "blocked"
    assert outcome.failure_code == "correction_capability_denied"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ("find_mcp_tool",)
    assert runtime.tool_registry is before_registry
```
REPLACE:
```
    # BF-965 (#1796): the projection's explicit denial withholds find_mcp_tool from the offer (synchronize_mcp_definitions
    # skips an explicit denial, and no grant offers it), so the loop refuses the call before the denial is reached. A
    # refusal is not a denial, so the one-response script ends the run as an execution defect, not a capability block.
    assert "find_mcp_tool" not in [
        (definition.get("function") or {}).get("name") for definition in correction_llm.requests[0].tools or []
    ]
    assert UNOFFERED_TOOL_REFUSAL in str(correction_llm.requests[1].prompt)
    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ()
    assert runtime.tool_registry is before_registry
```

**P2-43** (`tests/test_ad1126_verified_finalization.py`: `test_session_correction_malformed_find_mcp_registration_is_explicit_denial`, 18 cases, Category B. Malformed finder metadata leaves the run with an explicit denial (`crew_verifier.py:1146-1149`, `:1192-1202`). `calls == []` and `source_tool.calls == []` stay.)
SEARCH:
```
    assert outcome.status == "blocked"
    assert outcome.failure_code == "correction_capability_denied"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ("find_mcp_tool",)
    assert runtime.mcp_workbench.calls == []
    assert source_tool.calls == []
```
REPLACE:
```
    # BF-965 (#1796): malformed finder metadata makes the projection deny find_mcp_tool explicitly, which also withholds
    # it from the offer, so the loop refuses the call. A refusal is not a denial, so the one-response script ends the
    # run as an execution defect, not a capability block.
    assert "find_mcp_tool" not in [
        (definition.get("function") or {}).get("name") for definition in correction_llm.requests[0].tools or []
    ]
    assert UNOFFERED_TOOL_REFUSAL in str(correction_llm.requests[1].prompt)
    assert outcome.status == "failed"
    assert outcome.failure_code == "correction_execution_defect"
    assert outcome.terminal_attempt is not None
    assert outcome.terminal_attempt.denied_tools == ()
    assert runtime.mcp_workbench.calls == []
    assert source_tool.calls == []
```

**P2-44** (`tests/test_ad1241_mcp_offer_budget.py`: `test_real_discovery_withdrawal_releases_pins_only_after_successful_assembly[none-*]`, 2 cases, Category B. With no injected failure the refresh withdraws the alias, and the test asserts `alias not in names` at `:2250`. The 4 failure-injection cases keep the alias offered, so they are unchanged. `bridge.invocations` and the trace count 7 stay; the trace records the refused call.)
SEARCH:
```
        assert "after-denied-call" in _history(request)
        assert environment.bridge.invocations == [
            ("offline", "tool_000", {"value": "authorized-control"}),
        ]
        assert [
            payload["is_error"] for event, payload in environment.events
            if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == alias
        ] == [False, True]
```
REPLACE:
```
        assert "after-denied-call" in _history(request)
        assert environment.bridge.invocations == [
            ("offline", "tool_000", {"value": "authorized-control"}),
        ]
        # BF-965 (#1796): with no failure, the refresh withdrew the alias from the offer, so the loop refuses the call
        # before the adapter's authority recheck is reached: no tool event, and the model sees the refusal. With a
        # failed refresh the alias stays offered and the adapter denies it as before.
        withdrawn = failure == "none"
        assert (loop_module.UNOFFERED_TOOL_REFUSAL in _history(request)) is withdrawn
        assert [
            payload["is_error"] for event, payload in environment.events
            if event == "AGENTIC_TOOL_CALL_COMPLETED" and payload["tool_id"] == alias
        ] == ([False] if withdrawn else [False, True])
```

**P2-45** (`tests/test_ad1241_mcp_offer_budget.py`: `test_correction_missing_search_denial_is_not_recreated_or_upgraded`, 2 cases, Category B. The test asserts `_offered_names(request) == ["ordinary_probe"]` at `:2929`. `factories == []`, the unchanged definitions and `bridge.invocations == []` stay. Two pairs.)
SEARCH:
```
        assert "[tool_result:missing-search-denial error=True]" in request.prompt
```
REPLACE:
```
        assert "[tool_result:missing-search-denial error=True]" in request.prompt
        assert loop_module.UNOFFERED_TOOL_REFUSAL in request.prompt  # BF-965 (#1796): the unoffered search tool is refused by the loop.
```
SEARCH:
```
    assert outcome.denied_tools == ["find_mcp_tool"]
    assert factories == []
```
REPLACE:
```
    assert outcome.denied_tools == []  # BF-965 (#1796): a call the loop refused is not a denial; AD-855 files nothing.
    assert factories == []
```

**P2-46** (`tests/test_ad1241_mcp_offer_budget.py`: `test_correction_discovery_never_upgrades_frozen_adapter_denial`, Category B. The test asserts `alias not in _offered_names(request)` at `:2970`. `bridge.invocations == []` and `events == []` stay. Two pairs.)
SEARCH:
```
        assert "[tool_result:frozen-denial error=True]" in request.prompt
        return None
```
REPLACE:
```
        assert "[tool_result:frozen-denial error=True]" in request.prompt
        assert loop_module.UNOFFERED_TOOL_REFUSAL in request.prompt  # BF-965 (#1796): the frozen alias is never offered, so the loop refuses it.
        return None
```
SEARCH:
```
    assert outcome.stopped_reason == "complete" and outcome.denied_tools
    assert isinstance(environment.bridge, _SearchBridge) and environment.bridge.invocations == []
```
REPLACE:
```
    assert outcome.stopped_reason == "complete" and outcome.denied_tools == []  # BF-965 (#1796): a refusal is not a denial.
    assert isinstance(environment.bridge, _SearchBridge) and environment.bridge.invocations == []
```

**P2-47** (`tests/test_ad1241_mcp_offer_budget.py`: the inert `test_correction_malformed_discovered_metadata_is_not_installed_or_invoked`, Category B. The test asserts `_offered_names(request) == ["ordinary_probe", "find_mcp_tool"]` at `:3020`, so the alias is never offered. With this pair the case shows which layer refused the call.)
SEARCH:
```
        assert "[tool_result:malformed-denial error=True]" in request.prompt
        return None
```
REPLACE:
```
        assert "[tool_result:malformed-denial error=True]" in request.prompt
        assert loop_module.UNOFFERED_TOOL_REFUSAL in request.prompt  # BF-965 (#1796): uninstalled metadata is never offered, so the loop refuses it.
        return None
```

### M3: trackers and ledger

Replace `DATE` with M3's date. No line carries an `AD-` or `BF-` token or this contract's file name.

**P3-1** (`PROGRESS.md`). The anchor is the title line and the blank line after it. This entry is the newest, so it lands above batch 1's and #1794's entries.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**The agentic loop refuses a call to a tool outside its request's offer, on every route (DATE), #1796.**
- **Base.** A run's tool offer is how rank and role limit what an agent may call, but no route enforced it. The loop handed any name the model returned to the executor, and the registry resolves every registered tool the rank permits, offered or not. A name the model was not offered is what prompt injection produces, and the DM agentic route is on in shipped config.
- **Change.** For each response, the loop takes the exact tool names of the request that produced it, plus, with deferred schemas armed, the withheld names the `load_tools` list shows (the new `ToolManifestOffer.loadable_names()`). `_execute_one_tool` refuses any other name first. The refusal is an error result with a fixed text the model sees, issued before the delivery context, the start event, fault capture and the executor, plus one INFO line with an opaque tool identity. The sequential and parallel paths, the DM and work-item routes and the native builder all pass through it. A mid-turn refresh and the recovery reader count from the step whose request carried them. A provider alias passes as shown; the canonical id it stands for is refused. The refusal is never a denial, a capability request or defect evidence, and the DM reply reports it under the unknown-tool label. The executor's own guards are unchanged. Test fixtures whose scripted models called tools they did not offer now offer them, each with its reason inline, and the captain-document case T4 now drives the loop and asserts the refusal. This retires item F8 of #1754 and F-3 of #1419. Refs #1796.

```

**P3-2** (`DECISIONS.md`). The anchor is the heading below, at line 1796 on `5275d008`. Batch 1's and #1794's entries are inserted before it, so this entry lands after theirs.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### The agentic loop refuses a call to a tool outside its request's offer (DATE, #1796)

- *Scope.* `cognitive/swe_harness/agentic_loop.py` (`UNOFFERED_TOOL_REFUSAL`, the `also_offered` keyword, the check in `_execute_one_tool`), `cognitive/agentic_dispatch.py` (never-ran set, fault classification, `also_offered` wired from an armed manifest), `cognitive/tool_manifest.py` (`loadable_names`); one new test file, one shared fixture helper, fixture updates with inline reasons.
- *D1 (the seam).* The loop, not the executor: it is the one step every model-named call passes through, and it sees the mid-turn refresh, the recovery reader and the alias as shown. Rejected: an executor allowlist, which would refuse the recovery reader and miss the native builder.
- *D2 (the set).* The `function.name` values of the request that produced the response, matched exactly; with deferred schemas armed, also the loadable withheld names. A failing source of loadable names admits the request's offer only. No flag disables it.
- *D3 (what the route reports).* Never a denial, a capability request, or defect or fault evidence. The DM reply's failure list shows it under the unknown-tool label, as it shows any unoffered name. The raw name is never logged. Rejected: a fixed refusal that echoes the name or lists the tools.
- *Residual.* The rule bounds which tool runs, not what an offered tool does. Direct executor callers (code naming a tool) and the repair-verification replay are outside it. *Reversal.* Revert the batch's commits in reverse order.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. No AD or BF number moves. The roadmap Bug Tracker is not edited.

### R1: review round 1 (F1, F2), on `73b4d8c9`

The pairs are in commit R1 (R1-1 to R1-23): `without_never_ran_refusals` in `agentic_dispatch.py`; the native builder's import and observer call; the type test in `_execute_one_tool`; two imports and eight cases in the new file; this contract; `PROGRESS.md`; `DECISIONS.md`. R1b records the campaign and regenerates the ledger pair.
- **F1 (P2, a regression of M2, native harness on).** P2-15 made the refusal noise for the cross-turn lane only. `collect_tool_fault_batch` takes `same_run` (`fault_detection.py:266`) before its noise filter (`:315`), and `native_builder.py:181-185` (M3) handed the observer the raw run, so two refusals of one tool filed an open fault and a `FAULT_REPORTED` event for a tool that never ran. R1 hands it `without_never_ran_refusals(agentic_result)` (D7).
- **F2 (P2, a regression of M2, injected input only).** `if use.tool_call.name not in offered:` raised `TypeError` for a list or a dict name (`llm_client.py:2428-2430` passes the provider's value unchecked), outside `_execute_one_tool`'s error handling, so the turn failed; the base answered such a call with an item error and ran its siblings. R1 refuses a non-`str` name with the same text; its consumers already took a non-`str` name with an error result of this shape on the base (section 9, property 10).
- **The base's twin.** On the base a name the registry does not hold, called twice on the native route, filed a fault (the orchestrator's probe). Its text is the registry's not-found error (`tools/registry.py:416`, `:485`), not a never-ran refusal (`UNREGISTERED_TOOL_REFUSAL` is produced only under a confinement, `agentic_dispatch.py:860`), so the DM route's strip did not remove it either. Since M2 the loop refuses that name before the executor; with R1 neither route files it. Intended (D3); pinned by `[unregistered-twice]`. What stays is L6.
- **Embedded text.** P2-12's REPLACE, N1-1's file, P3-1 and P3-2 stay as M2 and M3 wrote them, so every SEARCH stays valid for a rebuild from this contract; R1's pairs are the correction. This header, section 1's row, D7, G2 and sections 6 to 12 are edited in place.
- **Other readers in `run_build`.** `final_text`, `iterations`, the `tool_calls` names (`tools_used`), `stopped_reason`, `total_tokens` and `token_source` keep the raw result: none is defect evidence, and `tools_used` reports what the model called, as on M3 and the base.
- **Expected after R1 (not measured).** The new file: 24 passed. On M3, `[unoffered-twice]`, `[unregistered-twice]`, `[list]` and `[dict]` fail; R1-control, `[unoffered-once]`, `[none]` and `[int]` pass on both. Focused, 0 failed: the new file, `test_ad546_native_builder_harness`, `test_ad1205_fault_paths`, `test_ad1205_fault_observer`, `test_ad1189_deferred_tool_schemas`, `test_ad1147_parallel_tools`, `test_ad1240_tool_result_delivery`; then the architecture check. Campaign: section 7's 19 rows, the new file only (baseline 24 passed).
- **Non-ASCII.** `native_builder.py:204` (M3) holds a non-ASCII character, outside R1's SEARCH texts.
- **Shared contract.** None changes: one public function is added; no existing signature, return shape, persisted or wire format changes. Round 2 is a delta review of `73b4d8c9..R1b`.

## 5. Commit messages

Every body ends with `Refs #1796.`; the committing agent's trailer paragraph comes after it. No subject contains an `AD-` or `BF-` token. No message uses a closing keyword in any form: close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved.
- Contract: `Unoffered tool refusal (#1796): contract for refusing any tool call outside the request's offer, in the agentic loop`
- M0: `Unoffered tool refusal M0: test fixtures offer the tools their scripted models call (#1796)`
- M1: `Unoffered tool refusal M1: tests for the refusal on every route, xfail until built (#1796)`
- M2: `Unoffered tool refusal M2: the agentic loop refuses a tool outside the request's offer (#1796)`
- M3: `Unoffered tool refusal M3: trackers and ledger (#1796)`
- R1: `Unoffered tool refusal R1: the native fault observer skips refused calls, and a non-text tool name is refused (#1796)`
- R1b: `Unoffered tool refusal R1b: mutation campaign of record and ledger (#1796)`

With `BASE` = the `origin/main` commit the batch is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

## 6. Recorded limits

- **L1.** The rule bounds which tool runs, not what an offered tool does (issue Limits; BF-975, #1806).
- **L2.** Direct executor callers and `repair_verification.py:222` name tools in code and are outside the rule. The executor's guards (S1.1, confinement, plan mode, deferred schema) stay as defence in depth.
- **L3.** The AD-1295 invocation record still lists the unoffered name as attempted and not succeeded. That record serves the DM write-claim check and is not shown to the model. It is unchanged here; considered, deferred.
- **L4.** Mutation rows 5 and 6 mutate code next to the check (the BF-755 refresh, the reader in the set) to show that A6 and A7 read the live offer. The mutants named in A9 ("run the gate first") and A10 ("fire the event before the check") are not one-line mutants; row 1 is their killer of record.
- **L5 (prerequisite BF-982, #1817: same wave and PR, its own commits, built first).** The AD-1356 S3 agent-work gate files a call under the name the model called (`agentic_dispatch.py:808`, `:850-851`; `agent_work_runner.py:722`). A model is shown an MCP tool only under its provider alias (`llm_function_name`), so on the base every MCP call from agent work is filed under the alias, and `filed_call_tier` (`effect_tiers.py:114-115`) makes it critical whatever its AD-1019b risk, against DECISIONS.md's AD-1356 S3 entry (OPEN is elevated). `test_ad1356_s3_chain_of_command.py` CC5 passed only because its script called the canonical id, which no model is shown and which this batch's exact match refuses (A5). BF-982 passes the resolved id to the confinement's set check, gate and `record_admitted`, and moves CC5's script to the alias; P0-259 then offers that alias. After it, CC5 `[reaped]` records one inert refusal: the resumed call names an adapter no longer registered, so it is not offered; on the base S1.1 refuses the same call.

- **L6.** Outside a confinement, a name that is still in the offer but that the registry no longer holds (a tool removed after its request was built) is answered by the registry's not-found error, which is fault evidence on both routes, as on the base. Unchanged; considered, deferred.

## 7. Mutation rows (each line occurs once, stripped, in its file after R1; run only the new file; expected, not measured)

Rows 1 to 15 as run on M2 (the campaign of record in DECISIONS.md) read row 1's line as `if use.tool_call.name not in offered:`. R1 puts the type test in front, so rows 1, 3 and 4 are restated on R1's line, and rows 16 to 19 are R1's. "R1-control", "R1-native" and "R1-text" are `test_r1_the_native_route_files_one_fault_for_a_real_repeated_failure`, `test_r1_the_native_route_files_no_fault_for_refusals` and `test_r1_a_name_that_is_not_text_is_refused_and_its_sibling_runs`.

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | agentic_loop | `if type(use.tool_call.name) is not str or use.tool_call.name not in offered:` | `if False:` | A1, A3, A4, A5, A6, A8, A9, A10, A11, also-offered; R1-native (all three), R1-text (all four) |
| 2 | same | `offered = _offered_tool_names(req.tools, self._also_offered, agent_id)` | `offered = _offered_tool_names(req.tools, None, agent_id)` | A8, also-offered |
| 3 | same | row 1's line | `if type(use.tool_call.name) is not str or (use.tool_call.name not in offered and use.tool_call.name not in PARALLEL_SAFE_TOOL_IDS):` | A4 |
| 4 | same | row 1's line | `if type(use.tool_call.name) is not str or __import__("probos.cognitive.swe_harness.tool_call", fromlist=["llm_function_name"]).llm_function_name(use.tool_call.name) not in offered:` | A5 |
| 5 | same | `tools = refreshed` | `pass` | A6 |
| 6 | same | row 2's line | `offered = _offered_tool_names([d for d in req.tools or [] if (d.get("function") or {}).get("name") != "read_file"], self._also_offered, agent_id)` | A7 |
| 7 | same | `agent_id[:12], tool_record_identity(use.tool_call.name), iteration,` | `agent_id[:12], use.tool_call.name, iteration,` | A11 |
| 8 | same | `loadable = frozenset()` | `raise` | also-offered |
| 9 | same | `return ToolCallResult(id=use.tool_call.id, output=UNOFFERED_TOOL_REFUSAL, is_error=True)` | `... is_error=False)` | A1, A2, A4, A5, A8; R1-native (all three), R1-text (all four) |
| 10 | same | row 9's line | `return ToolCallResult(id="", output=UNOFFERED_TOOL_REFUSAL, is_error=True)` | A5, A11; R1-native (all three), R1-text (all four) |
| 11 | agentic_dispatch | `UNOFFERED_TOOL_REFUSAL,  # BF-965 (#1796): the loop refused a tool outside the offer` | `# mutated` | constants case; A2 (`tool_defect`); R1-native `[unoffered-twice]`, `[unregistered-twice]` |
| 12 | same | `UNOFFERED_TOOL_REFUSAL,  # BF-965 (#1796): a refused unoffered call is not a fault` | `# mutated` | constants case |
| 13 | same | `_loop_kwargs["also_offered"] = manifest_offer.loadable_names` | `pass` | A8 |
| 14 | tool_manifest | `return (self._withheld & self._last_built) - self._presented` | `return self._withheld - self._presented` | loadable-names |
| 15 | same | same | `return self._withheld & self._last_built` | loadable-names |
| 16 | native_builder | `fault_observer, outcome=without_never_ran_refusals(agentic_result),` | `fault_observer, outcome=agentic_result,` | R1-native `[unoffered-twice]`, `[unregistered-twice]` |
| 17 | agentic_dispatch | `return _without_deferred_schema_refusals(agentic_result)` | `return agentic_result` | R1-native `[unoffered-twice]`, `[unregistered-twice]` |
| 18 | agentic_loop | row 1's line | `if use.tool_call.name not in offered:` | R1-text `[list]`, `[dict]` |
| 19 | agentic_loop | row 1's line | `if type(use.tool_call.name) is str and use.tool_call.name not in offered:` | R1-text (all four) |

## 8. What this does NOT change

- **Source:**
  - `DispatchToolExecutor` and its guards; `ToolExecutor._resolve_tool_id` (BF-754);
  - `ToolRegistry.check_and_invoke`; `correlate_tool_outcomes` and `_project_tool_invocations`;
  - the BF-755 refresh and the AD-1240 delivery code;
  - `NativeBuilderHarness`, except R1's one change: its fault observer reads the run without never-ran refusals, as the DM route's does (D7);
  - plan mode, confinement and AD-1154 behaviour for offered tools.
- **Config:** no key and no flag.
- **Elsewhere:** `ui/`; the commercial overlay; every tracker except `PROGRESS.md`, `DECISIONS.md` and the ledger pair; the roadmap Bug Tracker.

## 9. Diff Reviewer (`gpt-6.1-sol`): properties to verify

Name the consumer for each property and confirm it accepts the change.
1. **Every model-named call is checked before any side effect.**
   - In `_execute_one_tool`, the check comes before `delivery_run.invocation_context`, the STARTED `_fire_event`, `match_operation_handle` and `self._executor.invoke`.
   - All three call sites in `_execute_tool_uses` pass `offered`.
   - **Consumers:** the parallel path (AD-1147 `_bounded`); the strict profile.
2. **The set is the offer of the request that produced the response.**
   - It is built from `req.tools`, and an AD-1324 floor re-issue keeps them (`replace(req, ...)`).
   - `delivery_run.offer` runs before `req` is built, so the AD-1240 reader is admitted in the same step.
   - The BF-755 refresh assigns `tools` after execution, so it applies from the next step.
   - **Consumers:** the AD-1240 reader; the BF-755 mid-turn refresh.
3. **AD-1189.**
   - `loadable_names()` is the expression `request()` used before, and `withhold_call`'s preconditions hold for each name in it.
   - `also_offered` is passed only when `manifest_offer is not None`.
   - **Consumers:** the deferred-schema guard (`agentic_dispatch.py:874`); `test_ad1189...:77-89` (`_OFF_LOOP_KWARGS`); the `refresh_tools` pins in `test_ad1241...:1553,2597,3277`.
4. **The provider alias.** Matching is exact. An offered alias reaches the executor unchanged and resolves through `_resolve_tool_id` (`executor.py:560`); the canonical id is refused.
5. **Pairing of tool-call ids.**
   - The refusal is a `ToolCallResult` with the call's id, not an `InvocationRefusal`.
   - **Consumers:** `_executed_outcomes`, `build_tool_result_messages`, `_delivery_stop` (no stop), `correlate_tool_outcomes`, `_project_tool_invocations`. They stay aligned.
6. **What the routes report.**
   - `denied_tools` is untouched, so the AD-855 capability-gap path gets nothing.
   - **Consumers:**
     - `_without_deferred_schema_refusals`: drops the refusal, so neither `tool_defect` nor the DM route's fault observer sees it.
     - `classify_tool_fault_error`: returns `permission_denied`, which is noise only for the cross-turn lane of `collect_tool_fault_batch`; its same-run count is taken before that filter, so (R1, D7) the native builder hands its observer `without_never_ran_refusals(agentic_result)`, as the DM route hands its own the strip.
     - The DM route's `_run_reserved` failure list: shows the unknown label.
7. **Privacy and compatibility.**
   - No log line carries the raw name; `tool_record_identity` without a catalog is opaque.
   - `also_offered` defaults to `None`, and `AgenticLoop` gains no method.
8. **Paperwork.** The text is ASCII; tracker lines and subjects carry no `AD-` or `BF-` token.
9. **R1 (F1): one strip for every fault observer.** `observe_completed_tool_run` has two production callers (`agentic_dispatch.py:4436`; `native_builder.py`, `run_build`), and both pass a run without never-ran refusals. `without_never_ran_refusals` returns `_without_deferred_schema_refusals`'s value unchanged, the same object when nothing was refused, so a native run with no refusal is observed exactly as on M3 (the native cases of `test_ad1205_fault_paths.py`). Every other reader in `run_build` keeps the raw result. **Consumers:** `collect_tool_fault_batch` (`_DefectEvidence` carries the two lists it reads); `FaultReportStore`.
10. **R1 (F2): a non-text name is refused, not hashed.** `type(...) is not str` is tested first, as at `agentic_loop.py:730` and `:746`, so only a `str` reaches `in offered`; a `None` or an int is refused as on M3. The refused call keeps its id and the base's error-result shape. **Consumers:** `tool_record_identity` (any type, never raises); `build_tool_result_messages` (reads the result only); `correlate_tool_outcomes`, `_project_tool_invocations`, `detect_tool_defect` and `collect_tool_fault_batch` (each skips a non-`str` name); the strip (matches by output text).

## 10. Acceptance criteria

- **A1 to A11** pass as the named cases in section 4, M1. A2 is amended (D3): the refused call appears in the failure list only under `UNKNOWN_TOOL_LABEL`, with no denial, no defect and no capability request.
- **A12:** T4 is updated in place with its reason inline (P2-22) and is not deleted.
- **A13:** the refusal text does not match `_CAPABILITY_GAP_RE` (control case).
- **A14:** every fixture edit follows the M0 rule. No test turns the rule off, and none is skipped or loosened.
- **A15 (R1, F1):** on the native route, refused calls file no fault and no `FAULT_REPORTED` event, once or twice, for a registered tool outside the offer or a name the registry does not hold; an offered tool that really fails twice with one error still files one (control).
- **A16 (R1, F2):** a call whose tool name is `None`, an int, a list or a dict gets the refusal text as an error result under its own id, and its offered sibling runs.
- Rows 1, 2 and 9 of section 7 fail the new file. Rows 16 to 19 fail it too (R1).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 11. Verified Against Codebase (2026-11-14, read-only tree `D:\ProbOS-worktrees\next-read2` at `origin/main` `5275d00874799d68536fef2a7ff27c7bc44cda65`)

```
agentic_loop.py:76 from probos.tools.executor import recording_identity, tool_recording_scope
agentic_loop.py:156 PARALLEL_SAFE_TOOL_IDS (web_search, read_page, http_fetch, search_capabilities, event_log_query); :171-172 PARALLEL_TOOL_CALLS_*
agentic_loop.py:700-723 partition_tool_uses: by name in PARALLEL_SAFE_TOOL_IDS only; :916-919 role "tool", "tool_call_id"
agentic_loop.py:1198-1220 _open_delivery_run: None without an owner or under strict; :1232-1248 _executed_outcomes; :1263-1287 _delivery_stop, _observe_completion_spend
agentic_loop.py:1327-1358 __init__ keywords end at workspace_results; :1433-1436 workspace_results slot assignment
agentic_loop.py:1706-1710 tools = delivery_run.offer(tools); :1812-1836 LLMRequest(tools=tools); :1906-1912 req = replace(req, ...)
agentic_loop.py:2117-2134 the only _execute_tool_uses call; :2265-2288 BF-755 refresh after execution
agentic_loop.py:2412-2423, :2446-2461, :2469-2485, :2530-2545 _execute_tool_uses and its three _execute_one_tool calls
agentic_loop.py:2551-2576 _execute_one_tool signature and docstring end; :2598-2613 AD-1240 context; :2614 STARTED; :2684-2710 executor.invoke
agentic_loop.py: 13 direct methods on AgenticLoop (1327..2942); architecture-baseline.yaml:649-656 srp-size row, triggers [lines]
agentic_dispatch.py:36-39 import from agentic_loop; :286 _DEFERRED_SCHEMA_REFUSAL; :321 UNREGISTERED_TOOL_REFUSAL; :325-328 CONFINEMENT_*; :332-335 _NEVER_RAN_REFUSALS
agentic_dispatch.py:339-377 ToolCallConfinement; :913 denied_tools.append; :1004 confine_calls; :1518 DispatchToolExecutor
agentic_dispatch.py:2148-2165 classify_tool_fault_error; :2176-2209 _without_deferred_schema_refusals; :2253-2284 _executed_outcome_pairs
agentic_dispatch.py:2815-2816 run -> _run_reserved; :3078-3086 granted_ids from grants; :3598-3604 plan-mode comment
agentic_dispatch.py:3638 manifest_offer; :3759-3760 unarmed -> None; :3844 _loop_kwargs; :3986-3988 refresh_tools wiring; :4121-4132 AgenticLoop(**_loop_kwargs)
agentic_dispatch.py:4351-4378 _defect_outcome, denied_tools, tool_failures (executed pairs, known_tools=offered_names), tool_defect
tool_manifest.py:143-147 __slots__; :259-263 _withheld set only when armed; :269-271 has_pending_loads; :285 loadable expression; :317-333 withhold_call
native_builder.py:139-157 AgenticLoop(...), no also_offered; :181-185 observe_completed_tool_run(outcome=agentic_result); :210-225 _select_build_tools
reply_value.py:58-66 offered_display_name -> UNKNOWN_TOOL_LABEL; :106-128 correlate_tool_outcomes; dm_reply.py:134 UNKNOWN_TOOL_LABEL; :290-294 names()
fault_detection.py:32-35 _NOISE includes permission_denied; executor.py:300-325 tool_record_identity (no catalog -> opaque); :560 _resolve_tool_id
decomposer.py:51-58 _CAPABILITY_GAP_RE; tool_call.py:64-71 llm_function_name; :670-686 ToolCallRequest, ToolCallResult; :942-966 definition shape
types.py:318 LLMRequest.tools; protocol.py:81-87 ToolResult(output, error, metadata); events.py:296, :298 AGENTIC_TOOL_CALL_STARTED, AGENTIC_LOOP_ITERATION
registry.py:318-325 empty default_permissions -> READ for all ranks; pyproject.toml:181 asyncio_mode = "auto"
test_bf943...:22-31 imports; :210-233 T4 (direct executor invoke)
test_ad1189...:76-89 digest and _OFF_LOOP_KWARGS; :182-213 _environment; :220-240 _ScriptedLLM; :243-264 _config; :274-279 _run; :533 _DETAIL; :559 _offer; :959-983 _manifest_names, _armed_offer; :1017-1055 the existing direct-call case
test_ad1240...:149-189 _FakeLLM, _RawTool, _turn, _done; :675-717 _environment, _started; :1873-1925 _ReadbackLLM; :2189-2218 the reader-offer case
test_ad546...:14-29 _FakeRegistry; :97-124 run_build with a SimpleNamespace runtime
PROGRESS.md:1-2 title and blank line; DECISIONS.md:1796 anchor heading
```

**Absence verified (2026-11-14).**
- **Claim:** none of `UNOFFERED_TOOL_REFUSAL`, `loadable_names`, `also_offered`, `_offered_tool_names` or `UNOFFERED_REFUSAL` exists. **Run:** Grep over `*.{py,md,yaml}`. **Found:** none. **Holds.**
- **Claim:** neither file this batch adds, nor this contract, exists yet. **Run:** Glob `{tests/offered_tools.py,tests/test_bf965*,prompts/bf-965*}`. **Found:** none. **Holds.**
- **Claim:** only two loops and one call constructor exist. **Run:** Grep `AgenticLoop\(` and `ToolCallRequest\(` over `src`. **Found:** `agentic_dispatch.py:4121`, `native_builder.py:139`; `llm_client.py:2428`. **Holds.**
- **Claim:** no test pins the comment or docstring that P2-16 and P2-20 change. **Run:** Grep `tests` for `invoke-time guard|the executor resolves it as it resolves|names without being`. **Found:** only `test_ad1156_plan_execute_mode.py:11`, a docstring that describes the guard; it is not a source pin. **Holds.**
- **Claim:** the tests that call the private methods directly are the five in Category C. **Run:** Grep `tests` for `_execute_one_tool|_execute_tool_uses`. **Found:** `ad1187:1032,1047`, `ad1224:870`, `ad1261:958,1300` (direct); `ad1147:468-498` (subclass, `**kwargs` pass-through); `ad1322:959` (replaced attribute). **Holds.**

**Verified for Part 3b (2026-11-15, tree `D:\ProbOS-worktrees\ob2q` at `44cc943a`, production code as at `aee4a43c`).**
- `agentic_dispatch.py:3075-3086` grants never offer `find_mcp_tool` or an `mcp:` id; `:3102-3135` the AD-1241 offer (`create_dispatch_offer`, `type(...) is MCPDispatchOffer`, `accepts_dispatch_offer`, `dispatch_tool_ids(candidate_ids=selected_ids)` within `{"find_mcp_tool", *selected_ids}`); `:3725-3726`, `:3757` published canonical ids are acknowledged; `:3796-3838` refresh after each tool iteration; `:4144-4145` the offer rides only in the invocation context; `:1719-1721` `_McpTool.tool_id` is `mcp:{server}:{tool}`; `tool_call.py:962` the offered name is `llm_function_name(tool_id)`.
- `mcp_workbench.py:188-212` `MCPDispatchOffer(workbench, agent_id, *, preload_limit, preloaded_ids=())`; `:241-247` `belongs_to` is an identity check; `:249-279` `admit`; `:281-310` `acknowledge_published`; `:313-326` `MCPDispatchSource`; `:795-906` the preload offers OPEN-risk tools only; `:1016-1017` the real search tool is `UTILITY_AGENT`; `:1130` a discovery pull calls `offer.admit`.
- `crew_verifier.py:353-411` `_SessionMcpToolIds` (its `create_dispatch_offer` needs `synchronize(("find_mcp_tool",)) == ["find_mcp_tool"]`, then the source's offer); `:492-576` `synchronize_mcp_definitions` skips explicit denials (`:497-498`) and admits a search tool only as `UTILITY_AGENT` (`:525-532`); `:1143-1202` the projection reads the source's ids only when the search tool's registration is valid, and otherwise denies every MCP-tagged id; `:2246-2267`, `:2733-2742` `blocked` only for a denial or a token budget, otherwise `correction_execution_defect`.
- Tests: `test_ad1126...:241-260` `_ScriptedLLM` records the request, then raises when empty; `:6303-6313`, `:6359-6366`, `:7412-7683`. `test_ad1205...:582-616`, `:1336-1358`, `:1386-1388`, `:1392-1416`, `:1578-1674`, `:1677-1740`. `test_ad1257...:319-328` (`_exec_runtime`: namespace config, no `mcp`), `:1171-1211`. `test_ad1241...:20` (`loop_module`), `:1172-1242`, `:2151-2294`, `:2903-3044`.
- **Claim:** outside startup, only the dispatch and the correction projection read `config.mcp.agent_tools_enabled` or `runtime.mcp_workbench`. **Run:** Grep `src/probos` for `agent_tools_enabled` and for `mcp_workbench`. **Found:** `agentic_dispatch.py:3094,3103`; `crew_verifier.py:1056,1144,1145`; `startup/finalize.py:5053,5112` (wiring); otherwise docstrings and type references. **Holds.**
- **Claim:** no other `_McpWorkbench` user in `test_ad1126` runs a correction loop. **Run:** Grep the file for `_McpWorkbench\(` and `WorkItemAgenticExecutor\(`. **Found:** `:6788`, `:6916`, `:6979` in `test_session_correction_projects_static_mesh_mcp_and_runtime_tools` (`:6757`, no executor); `:7870` in the source-defect case (`:7837`), which fails before its model runs. **Holds.**

**R1 verified against `73b4d8c9` (2026-11-16, read-only).**
- `native_builder.py:8-12` the import from `agentic_dispatch`; `:179-185` `observe_completed_tool_run(fault_observer, outcome=agentic_result, ...)`; `:189-206` the other readers; `:204` non-ASCII.
- `agentic_dispatch.py:333-337` `_NEVER_RAN_REFUSALS`; `:860` the only `UNREGISTERED_TOOL_REFUSAL` producer (under a confinement); `:2161-2179` `classify_tool_fault_error`; `:2190-2223` `_without_deferred_schema_refusals` (the same object when nothing was refused, `:2215-2216`); `:2346-2348` `_project_tool_invocations` skips a non-`str` name; `:4372` `_defect_outcome`; `:4397-4399` `detect_tool_defect(_defect_outcome, ...)`; `:4436-4443` `observe_completed_tool_run(..., outcome=_defect_outcome, ...)`.
- `fault_detection.py:266` `same_run = detect_tool_defect(outcome, ...)`; `:273-285` a non-`str` name is skipped as uncorrelatable; `:308-309` `same_run_count`; `:315` the noise filter; `:345` `same_run` kept at count >= 2; `:457-471` `observe_completed_tool_run` calls `collect_tool_fault_batch`.
- `fault_report.py:376` `detect_tool_defect` reads only `str` names; `:584-596` `FaultReportStore(db_path, connection_factory, emit_event)`; `:950` `list_open`; `:980` `_emit_fault` passes the `EventType` member. `tools/registry.py:416`, `:485` `Tool '...' not found`.
- `agentic_loop.py:730`, `:746` `type(name) is str` before a set membership; `:2631-2642` the check and the refusal; `:2938-2947` the base's item error for a raising call; `:927-939` `build_tool_result_messages` reads only the result. `dm/reply_value.py:119-121` `correlate_tool_outcomes` skips a non-`str` name. `llm_client.py:2428-2430` `name=fn.get("name", "")`. `tools/executor.py:300-325` `tool_record_identity` (no catalog: opaque, any type).
- **Absence.** Claim: no `without_never_ran_refusals` exists. Run: Grep `_without_deferred_schema_refusals|without_never_ran_refusals` over the repository, `logs/` excluded. Found: the private name only (`agentic_dispatch.py:2190`, `:4372`; `test_ad1189_deferred_tool_schemas.py:2493`; two prompts). Holds.
- **Absence.** Claim: `observe_completed_tool_run` has two production callers. Run: Grep `observe_completed_tool_run\(` over `src`. Found: `agentic_dispatch.py:4436`, `native_builder.py:181`, and the definition (`fault_detection.py:457`). Holds. In `tests`, only `test_ad1205_fault_observer.py:570`, `:691` call it, directly; none patches the native module's name.
- **Absence.** Claim: no test pins the base's `unhashable` item-error text for a tool name. Run: Grep `tests` for `unhashable`. Found: `test_ad1147_parallel_tools.py:218` (partition only: it asserts sequential, not a loop result) and unrelated stores. Holds.

## 12. Prior Art and Blind Spots

- **Internal.** The refusal follows the voice and consumers of the AD-1156 plan-mode refusal, AD-1356 S1.1's unregistered-tool refusal and AD-1189's deferred-schema refusal (all in `_NEVER_RAN_REFUSALS`). The DM reply's label is AD-1248 DD-1a.
- **External (LangGraph, reviewed 2026-11-14).** `ToolNode` answers an invalid tool name with an error tool message, "Error: {requested_tool} is not a valid tool, try one of [...]".
  - Adopted: the error-result shape. The model sees it and the run goes on.
  - Rejected: echoing the name and listing the tools (D2's last bullet).
  - A reported LangChain.js case where an invalid name crashed before error handling is why this check sits before every side effect and cannot raise. On M3 it could: a list or a dict name raised `TypeError` at the membership test (F2); R1 tests the type first.
- **Blind spots.**
  1. The 54-file census misses runs driven through `WorkItemAgenticExecutor`, `NativeBuilderHarness` or the agents (70 more files match those names), so the oracle must cover the whole suite, and the oracle reports tests that pass while the refusal fired (inert cases), not only failures.
  2. The native builder's raw fault observation (P2-15, completed by R1: P2-15 reached only the cross-turn lane, D7).
  3. Private direct callers (Category C).
  4. Request goldens (Category D).
  5. The AD-1295 attempted record (L3).
