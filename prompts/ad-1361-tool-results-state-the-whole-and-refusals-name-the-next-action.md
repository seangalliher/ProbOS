# AD-1361 (#1743 items 1, 2 and 6): a sliced `read_file` states the whole it is a slice of, the native tools' refusals name the next action, and the review criteria ask the parity question

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-18
**Corrected by:** the orchestrator, 2026-11-18, after its oracle run of the section 10 campaign: row RF-10 named `test_each_next_action_reads_as_no_gap_and_names_only_tools_the_refused_agent_has` (U4) as its killer. U4 reads the test file's own copies of the four sentences, so mutating the production sentence does not reach it; the row is killed by `test_read_and_list_refusals_name_the_next_action[read_file]` and `test_the_standing_orders_denial_and_the_sentences_are_pinned`, which tie the production sentences to those copies. The row now says so. Nothing else changed.
**Save as:** `prompts/ad-1361-tool-results-state-the-whole-and-refusals-name-the-next-action.md`
**Status:** Ready to build as batch B4 (M1 to M4). The Captain admitted items 1, 2 and 6 on #1743 on 2026-11-18. Items 3, 4, 5 and 7 are not admitted and are not touched. **Base:** drafted on `9f43697f` (origin/main, 2026-11-18). Built after #1680 (BF-938) and #1811 (BF-980) merge. Neither issue touches the files this contract edits (their titles concern the recall anomaly gate and the event chain; this is not a diff check, see §4.1 V1). **Dependencies:** none. **Tier:** M1 HIGH (it edits AD-1240's delivery in `result_offload.py`), M2 STANDARD, M3 STANDARD (one docs line), M4 STANDARD. **Estimated tests:** two new files. `tests/test_ad1361_slice_notes.py` holds 11 cases (M1) and `tests/test_ad1361_refusal_next_actions.py` holds 11 (M2). Existing pins are updated in `test_ad1240_tool_result_delivery.py`, `test_ad1200_repository_instruction_wire.py`, `test_bf948_list_files_read_policy.py`, `test_bf953_read_floor_spellings.py` and `test_bf911_protected_config_write_refusal.py`.
**AD number:** AD-1361. `d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py` on `9f43697f` gave `CEILING: AD-1360 (from: GitHub issue titles (all states))` and `NEXT: AD-1361`. Re-run it at build time. Item 6 takes no number.

**Which text describes the head.** Sections 1 to 3 describe `9f43697f`, with that commit's line numbers. A SEARCH that no longer matches goes back to the Architect and is not rebased by hand. Where prose and a REPLACE or new-file block differ, the block wins.

## 0. Event Types

None. No `EventType`, no config field and no persisted key is added.

## 1. Problem

1. **A sliced `read_file` drops the total.** There are two fresh paths.
   - **The plain path** (no read context: strict profile, no workspace owner, or `invocation_context` returned `None`). It returns `"\n".join(lines[start:end])` (`tools.py:488-494`), and `len(lines)` is discarded.
   - **The verified path** (`_verified_source_result`, `tools.py:334-380`). This is every `read_file` the loop arms under an AD-1240 delivery run (`result_offload.py:296-353`). It computes the total into `SourceRef.total_lines` (`tools.py:372`, `workspace_results.py:183`), but no `src` code renders or reads that field (Absence A3).
   - **Effect on the model.** It sees the slice with no bound. When the slice is offloaded, the source frame says `observed lines A:B` and nothing more (`result_offload.py:545-546`).
2. **The issue's anchors** (`f31afa56`) are `tools.py:483-488`, which is the plain path (now `:488-494`), and `:379-393`, which is `_workspace_slice_result` (now `:383-397`). The issue does not name the verified path, which is the live one. Its premise about the workspace-slice path is only half true. That path reads an offloaded artifact by characters, and the pointer frame that promised the artifact already gives its whole in characters. Its `Outline` is `CanonicalCapture.outline`, whose `chars` must equal `source_chars` (`workspace_results.py:147`, `result_offload.py:521-528`).
3. **A note inside the verified text would break AD-1240.**
   - A recovery read's text is held to the per-read bound: `len(text) > settings.max_chars` raises `recovery_slice_too_large` (`result_offload.py:621-624`).
   - The source frame sizes its worked call by counting the capture's lines into the allowance (`result_offload.py:531-551`).
   - So a note in the text of a fresh offloaded slice would be counted as source lines. A note in a recovery's text would make the frame's own suggested read go over the bound.
   - In both cases the producer's `output` would change too (`test_ad1240:2794` pins it as the slice).
4. **Refusals in `cognitive/swe_harness/tools.py` that name no next action.** The census is in §3. Nine of its 49 error returns are refusals that do not say what to do instead:
   - `read_file refused:` (`:472`) and `list_files refused:` (`:621`)
   - the standing-orders denial (`:900-902`, returned at `:1000`)
   - the three write rules of `write_file` (`:1100`, `:1104`, `:1108`) and `edit_file` (`:1197`, `:1201`, `:1205`)

   The convention to copy is the browser refusal (`agentic_dispatch.py:199-203`) and the AD-1154 and AD-1328 voice: "Do not repeat it; ... report ..." (`agentic_dispatch.py:261-280`, `execution/command_gate.py:81-92`).
5. **Item 6.** `prompts/review-criteria.md` §8 "Design Choices" (`:69-73`) has no question about a store the crew relies on. The full text is in `docs/research/clark-extended-mind-absorption.md:54-65`.

## 2. Solution

- **M1 (item 1).**
  - **Plain path.** `read_file` returns the slice, a blank line and one bracketed note: the lines shown (counted from 0) of the total, the `offset` and `limit` that give them, and either the `offset` that reads on or a statement that the slice reaches the end. A range with no lines gives the note alone.
  - **Verified path.** The same note is computed, but it is carried beside the text as `slice_note`. AD-1240's legacy branch in `_prepare_result` appends it to what the model is shown. The offload threshold, the per-read bound, the frame's line count and the producer's `output` are therefore all measured on the slice alone.
  - **Offloaded source frame.** It now says `observed lines A:B of N`.
  - **Not covered.** A recovery re-read and a workspace-artifact read get no note, because their frame named the whole. `codebase_read_source` is unchanged.
- **M2 (item 2, first family).** Each of the nine refusals ends with one sentence naming the nearest action this agent has. BF-948's `" refused: "` mark is kept, so the fault detectors are unaffected. Fixed text, free of `_CAPABILITY_GAP_RE`. The other 40 returns are unchanged.
- **M3 (item 6).** One bullet is added to `prompts/review-criteria.md` §8, in its own commit.
- **M4.** Trackers and the ledger.
- **Rejected:**
  - A note inside the verified text: it breaks the AD-1240 bounds (§1.3).
  - A typed note rendered by the loop's `format_tool_result_content`: it needs `agentic_loop.py` and a new result field on `ToolCallResult` for the same effect.
  - A note on recovery reads with frames reserving room for it: that moves the AD-1240 accounting and BF-946's bound.
  - Covering `codebase_read_source` now: its 1-based inclusive spelling needs its own sentence, and the issue names `read_file`.
  - Editing the rule texts in `builder_paths.py` and `file_access.py`: other writers (FileWriterAgent, the builder) return them too, and that is another family.

## 3. Decisions

- **The note.**
  - **Unit:** lines, counted the way `str.splitlines` counts them. That is how `offset` and `limit` select lines and how `SourceRef.total_lines` counts them.
  - **Range:** the range actually returned, from `slice(start, end).indices(len(lines))`, with `last` never below `first`. So a request past the end, a short file, a negative offset and `limit=0` are each stated truthfully.
  - **Texts**, with the line counts filled in:
    - more follows: `[read_file slice: lines {first} to {last} of {total}, counted from 0 (offset={first}, limit={count}). More follows: call read_file again with the same path and offset={last} to read on.]`
    - reaches the end: `[read_file slice: lines {first} to {last} of {total}, counted from 0 (offset={first}, limit={count}). This slice reaches the end of the file.]`
    - empty: `[read_file slice: no lines in this range. The file has {total} lines, counted from 0.]`
  - **Placement:** after the slice, separated by a blank line. A reader of the text meets the slice first, and AD-1148 keeps a tail, so the note survives its bound unless the cap is too small for it. This copies BF-889's `read_page` header, with the integers kept bare so the model can copy them back.
  - **Total unknown:** this does not happen on either covered path, since both have `len(lines)`.
- **Which paths.**

  | Path | Note | Where it is rendered |
  |---|---|---|
  | `read_file` plain (`:488-494`) | yes | in the result's text |
  | `read_file` verified fresh (`expected is None`, not whole) | yes | `slice_note`, appended by `_prepare_result`'s legacy branch |
  | `read_file` verified fresh, offloaded | frame says `of N` | `_source_frame` |
  | `read_file` recovery re-read; workspace artifact slice | no (L1) | the promising frame named the whole |
  | `codebase_read_source` (both paths) | no (L3) | none |

- **What must not move.**
  - On the verified path: `ResultDelivery.presentation` of a recovery, `_OversizedFrame`'s bound check, the threshold measured on `encoded_size`, `canonical_capture`, `_source_frame`'s allowance and count, and the producer `output`.
  - Everywhere: AD-1148's algorithm, the tool schemas and descriptions (the AD-1179 golden), and `source_chars` (still `None` for a `str` result).
  - Only the plain path's own text grows, by about 200 characters at most (L5).
- **Consumers of the text, enumerated:**
  - **The model**, through `format_tool_result_content`: `truncate_tool_output` for a legacy result, `presentation` for a delivery (`agentic_loop.py:867-907`).
  - **`AgenticResult.tool_results[*].output`**, which goes to:
    - the AD-1151 durable trace (`build_tool_trace_payload`, attachment store, `agentic_dispatch.py:4590-4599`);
    - the invocation record, which reads names and `is_error` only (`agentic_dispatch.py:2345-2377`);
    - the DM reply value, which reads `is_error`.
  - **BF-947 `CarriedResults`**, which reads the raw `ToolResult.output`, so only the plain path's note (`agent_work_runner.py:137-153`).
  - **AD-1240 `_prepare_result`** (`result_offload.py:589-671`).

  No code parses a `read_file` result's text (Absence A1, A3). The AD-1346 register is unchanged: no new store, egress or subprocess site; the existing trace write stores the longer text.
- **The refusal convention (item 2).**
  - **Rule.** A refusal says what was refused and why (unchanged), then one sentence naming the nearest action this agent has.
  - **Where no tool fits**, the sentence names the reply: "say in your reply ...". That is available to every agent in every run. It matches the AD-1328 frames ("report that this step is blocked"). The capability-request route is not a tool an agent calls: requests are filed by the system from gap replies, tier floors and continue-or-ask (`capability_triage.py:573`, `continue_or_ask.py:544`, `tier_floor_ask.py:259`).
  - **Named tools.** The only tool named is `list_files`, in the `read_file` refusal. It is registered beside `read_file` with the same permission matrix (`tools.py:1487-1488`, `read_perms`). It lists only what the read policy admits (BF-948), and `llm_function_name("list_files") == "list_files"`. Plan mode withholds both (`agent_mode.py:68-83`).
  - **Sentences.**
    - read: `Do not repeat this call with the same path: read another file, and use list_files to see which files you can read.`
    - list: `Do not repeat this call with the same path: list another directory.`
    - write: `Do not repeat this call: leave this file as it is, go on with the rest of your task, and say in your reply what change you wanted.`
    - standing orders: `Do not repeat this call for it: say in your reply which file you needed.`
  - **Composition.** Each is appended as `"{refusal}. {sentence}"`. The marked prefix and the rule's own text are unchanged, so `is_caller_input_error` and the fault detectors decide as before, and two identical refusals stay identical.
- **The census of `tools.py` error returns** on `9f43697f`. Method: `Grep "error="` over the file, read site by site. Every hit is a `ToolResult(...)` or `RecoveryFailureToolResult(...)` call with an `error` keyword inside a tool class, except `:134` (`ctypes.WinDLL(..., use_last_error=True)`, not counted). There are 49 returns.

  | Lines | Tool | Return | Class | AD-1361 |
  |---|---|---|---|---|
  | 462 | read_file | `"path is required"` | input | unchanged |
  | 472 | read_file | `f"read_file refused: {exc}"` | refusal, no next action | **+ read sentence** |
  | 496 | read_file | `RecoveryFailureToolResult(error=exc.code)` | AD-1240 delivery code (`_ERROR_CODE`) | unchanged |
  | 498, 511 | read_file | `File not found:` / `read_file failed:` | failure | unchanged |
  | 605 | list_files | `"pattern is required"` | input | unchanged |
  | 607 | list_files | `_LIST_FILES_PATTERN_REFUSAL` | refusal, names next ("name the directory in path") | unchanged |
  | 621 | list_files | `f"list_files refused: {exc}"` | refusal, no next action | **+ list sentence** |
  | 639, 645 | list_files | `list_files_failed` / `list_files failed:` | failure | unchanged |
  | 676, 718, 760, 798, 844 | codebase_* | `"<arg> is required"` | input | unchanged |
  | 679, 721, 763, 801 | codebase_query, find_callers, find_tests, get_imports | `"codebase_index unavailable on runtime"` | the tool's own state, not a rule's refusal | unchanged (L12) |
  | 684, 729, 767, 805, 880 | codebase_* | `"<tool> failed: {exc}"` | failure (`:880` also carries read-policy refusals, L8) | unchanged |
  | 876, 878 | codebase_read_source | delivery code / `File not found:` | code / failure | unchanged |
  | 965 | standing_orders_lookup | `scope must be one of ...` | input, names the values | unchanged |
  | 980 | standing_orders_lookup | `_STANDING_ORDERS_NAME_REFUSAL` | refusal, names an example | unchanged |
  | 985 | standing_orders_lookup | `... not found for that name; available: ...` | refusal, names what is available | unchanged |
  | 1000 | standing_orders_lookup | `_STANDING_ORDERS_DENIED` | refusal, no next action | **+ sentence, in the constant** |
  | 1004 | standing_orders_lookup | `failed:` | failure | unchanged |
  | 1045 | system_self_model | `failed:` | failure | unchanged |
  | 1092, 1094 | write_file | `is required` | input | unchanged |
  | 1100, 1104, 1108 | write_file | AD-1344, BF-943 (marked), BF-911 | refusal; names who decides, no agent action | **+ write sentence** |
  | 1142 | write_file | `failed:` | failure | unchanged |
  | 1187, 1189 | edit_file | `is required` | input | unchanged |
  | 1197, 1201, 1205 | edit_file | AD-1344, BF-943 (marked), BF-911 | refusal | **+ write sentence** |
  | 1267, 1271 | edit_file | `File not found:` / `failed:` | failure | unchanged |
  | 1382 | run_command | `command is required` | input | unchanged |
  | 1402 | run_command | AD-1328 policy and escalation frames | refusal, names next ("Do not repeat it; use the alternative named, or report ...") | unchanged |
  | 1425, 1447 | run_command | `timed out` / `failed:` | failure | unchanged |

  Per class: ReadFileTool 5, ListFilesTool 5, CodebaseQueryTool 3, CodebaseFindCallersTool 3, CodebaseFindTestsTool 3, CodebaseGetImportsTool 3, CodebaseReadSourceTool 4, StandingOrdersLookupTool 5, SystemSelfModelTool 1, WriteFileTool 6, EditFileTool 7, RunCommandTool 4.

  U5 pins this table by AST. Its premise fails if it finds nothing, and adding or removing a return fails it until the return is classified.
- **#1722 S3 versus this item.** S3's refusals are `CONFINED_CALL_FILED`, `CONFINED_CALL_NOT_FILED`, `CONFINED_CALL_ANSWERED` and `UNREGISTERED_TOOL_REFUSAL` (`agentic_dispatch.py:307-325`). None of them is in `tools.py`. The refusals outside S3, family by family:
  - `tools.py`: this AD.
  - `agentic_dispatch.py` approval, plan-mode, deferred-schema and browser texts (`:199-203`, `:261-301`): already name a next action.
  - `agentic_loop.py` `UNOFFERED_TOOL_REFUSAL` (`:178-183`): already names one.
  - `execution/command_gate.py` and `execution/command_escalation.py` frames: already name one.
  - `tools/protocol.py` `refuse_undeclared_params`: names the accepted parameters.
  - `cognitive/copilot_adapter.py:76`: its own `_STANDING_ORDERS_DENIED` copy (L11).
  - The rule texts in `builder_paths.py` and `file_access.py` as other writers return them.
  - The modules under `src/probos/tools/`, which this contract does not enumerate.
- **Tests pin the convention.** U1 to U3 run each changed refusal and compare the exact text. U4 checks that each sentence is gap-free and names only a co-registered tool spelled as the model sees it. U5 is the census.
- **Item 6.** The bullet is placed under §8 after "Rollback path". No other copy of the criteria exists:
  - no `src` or `tests` file names it (Absence A5);
  - `scripts/wave-orchestrator.ps1:495` and `.claude/agents/claude-architect.md:99` tell a reviewer agent to read the file;
  - `prompts/archive/**` and `prompts/Reviews/archive/**` mention it historically;
  - no generated file, template or test hashes it.

  The bytes change what reviewer agents read when they open the file, not a runtime prompt.
- **No config, no `EventType`, no new class.** The only new public name is the module function `with_slice_note`.

## 4. Milestones and gates

| M | Tier | Pairs | Gate |
|---|---|---|---|
| M1 | HIGH | P1-1 to P1-14, N1 | G1 |
| M2 | STANDARD | P2-1 to P2-14, N2 | G2 |
| M3 | STANDARD | P3-1 | G3 |
| M4 | STANDARD | P4-1, P4-2, the ledger | G4 |

**G1:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1361_slice_notes.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1240_workspace_results.py tests/test_ad1240_workspace_result_lifecycle.py tests/test_ad1200_repository_instruction_wire.py tests/test_bf946_read_only_delivery_failures.py tests/test_ad1356_s1_recovery_reads.py tests/test_ad1191_delegation_wire.py tests/test_ad544_native_tools.py tests/test_ad1179_tool_schema_golden.py -q -n 0`, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`. New file: 11 cases. The other counts are not measured here; the oracle records them on M1's stage.

**G2:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1361_refusal_next_actions.py tests/test_bf948_list_files_read_policy.py tests/test_bf953_read_floor_spellings.py tests/test_bf911_protected_config_write_refusal.py tests/test_bf943_captain_document_write_refusal.py tests/test_ad1344_constitution_write_refusal.py tests/test_bf910_standing_orders_lookup.py tests/test_search_threads_and_running_code.py tests/test_ad1356_s1_input_errors.py tests/test_ad1179_vocabulary_constants.py tests/test_bf965_unoffered_tool_refusal.py tests/test_ad1316_real_effect_routes.py tests/test_ad544_native_tools.py -q -n 0`. New file: 11 cases. Other counts are measured by the oracle.

**G3:** no test (Absence A5). `git diff --cached --stat` shows only `prompts/review-criteria.md`, 1 file, 1 insertion. Delta review only.

**G4:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then `... gen_ad_ledger.py --check`, then `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

**Focused-list derivation (AV9).** I grepped `tests/` for every changed symbol and text:
- `ReadFileTool(` → ad1179 schema golden, ad1240, ad544, bf948, bf908, bf953;
- `swe_harness.result_offload` → ad1240, bf946;
- `SourceToolResult|InstructionSourceToolResult|WriteFileTool|EditFileTool|StandingOrdersLookupTool|ListFilesTool|_STANDING_ORDERS_DENIED` → 14 files;
- `"offset":|"limit":` → ad1240, ad1200, bf946;
- the refusal texts → bf948, bf953, bf910.

`test_bf908_floor_and_children.py` asserts no read_file refusal text. It runs in the broad gate, not G1.

### 4.1 Premises the orchestrator verifies first-hand

| Id | Premise | Probe (premise asserted) |
|---|---|---|
| V1 | No file this contract edits moved between `9f43697f` and the build base | `git diff --stat 9f43697f HEAD -- src/probos/cognitive/swe_harness/tools.py src/probos/cognitive/swe_harness/result_offload.py tests/test_ad1240_tool_result_delivery.py tests/test_ad1200_repository_instruction_wire.py tests/test_bf948_list_files_read_policy.py tests/test_bf953_read_floor_spellings.py tests/test_bf911_protected_config_write_refusal.py prompts/review-criteria.md` is empty. Otherwise the contract goes back to the Architect |
| V2 | AD-1361 is still free | `scripts/ad_ceiling.py` prints `NEXT: AD-1361` |
| V3 | The loop's `read_file` takes the verified path | T3 asserts that `Path.read_text` was never called for the file. G1 green on M1's stage |
| V4 | My census is complete | U5 green on M2's stage. A mismatch is a hard stop back to the Architect (do not edit the table to match) |
| V5 | No pin of the source frame's header or length breaks | G1 green (Absence A1 covers the text; frame lengths in tests were not read one by one) |
| V6 | The new sentences are gap-free and name a co-registered tool | U4 green |
| V7 | Every §10 mutant is killed | the oracle's campaign of record on M2's head |

## 5. Commit messages

- M1: `AD-1361 M1: a sliced read_file states the whole it is a slice of (#1743 item 1)`
- M2: `AD-1361 M2: the native tools' refusals name the next action (#1743 item 2)`
- M3: `#1743 item 6: the review criteria ask the parity question for a store the crew relies on`
- M4: `AD-1361 M4: trackers and ledger`

## 6. Tests

| Id | File | Test | Covers |
|---|---|---|---|
| T1 (6) | slice_notes | `test_a_plain_sliced_read_states_the_whole` (more-follows, reaches-the-end, offset-only, past-the-end, limit-zero, whole-file) | the note's three texts; the empty case; a whole read unchanged |
| T2 | slice_notes | `test_codebase_read_source_slices_carry_no_note` | L3 on both paths |
| T3 (2) | slice_notes | `test_a_fresh_sliced_read_through_the_loop_states_the_whole_and_the_next_read_follows_it` (both transcripts) | the seam from tool to `_prepare_result` to model message, and a second read at the named offset |
| T4 | slice_notes | `test_an_offloaded_fresh_slice_names_the_whole_in_its_frame_and_keeps_its_line_count` | `of N`; the worked call's `limit` (64) is unchanged; producer output is the slice |
| T5 | slice_notes | `test_a_recovery_read_carries_no_note_and_is_delivered_as_the_slice_alone` | L1; the BF-946 bound is untouched |
| U1 (2) | refusal_next_actions | `test_read_and_list_refusals_name_the_next_action` | exact text; BF-948 mark kept |
| U2 (6) | refusal_next_actions | `test_write_refusals_name_the_next_action` (2 tools × 3 rules) | exact text; target unchanged |
| U3 | refusal_next_actions | `test_the_standing_orders_denial_and_the_sentences_are_pinned` | the constant and the three sentence constants |
| U4 | refusal_next_actions | `test_each_next_action_reads_as_no_gap_and_names_only_tools_the_refused_agent_has` | `_CAPABILITY_GAP_RE`, registration, permission matrix, model spelling |
| U5 | refusal_next_actions | `test_every_error_return_in_the_native_tools_is_counted` | the census |

Updated pins, each with an inline reason (§7):
- `test_ad1240`: `:1318` parity, `:1605`, `:2149-2150`, `:3411-3412`
- `test_ad1200`: `:504`, `:508`
- `test_bf948`: `:41-42`, `:120`, `:177`, `:332`
- `test_bf953`: `:68-69`, `:566`, `:798`
- `test_bf911`: `:685`

Left as they are, with the reason:
- `test_bf948:258`, `:261`, `:265-267`: inputs to the classifier, not outputs of the tool; still correctly marked.
- `test_bf948:304-305`: `_seen` matches substrings (`test_ad1347_s3_execution.py:284-289`).
- `test_bf910` `:299`, `:736`, `:772`, `:785`, `:850`: compare to `tools._STANDING_ORDERS_DENIED` itself.
- `test_search_threads_and_running_code.py:478`: `startswith`.
- The `ad1344`, `bf911` and `bf943` containment checks (`_AD in`, `_BF in`).
- `ad1179` and `ad1152` goldens: schemas only.
- `ad1200` golden traces: whole reads only (`_read`, `test_ad1200:91-101`).

## 7. The contract

### 7.1 M1

**P1-1** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
@dataclass(frozen=True)
class SourceToolResult(ToolResult):
    """A verified original-file read, carrying the reference a recovery re-reads."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)


@dataclass(frozen=True)
class InstructionSourceToolResult(InstructionToolResult):
    """``SourceToolResult`` for a read that also carries repository instructions."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)
```
REPLACE:
```python
@dataclass(frozen=True)
class SourceToolResult(ToolResult):
    """A verified original-file read, carrying the reference a recovery re-reads."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)
    # AD-1361 (#1743 item 1): for a fresh sliced read_file, the note naming the whole it is a slice of. It is kept
    # beside ``output``, so the slice text and every AD-1240 bound measured on it are unchanged; the delivery adds
    # it to what the model is shown. Empty for a whole read, a recovery re-read and codebase_read_source.
    slice_note: str = field(default="", kw_only=True, repr=False)


@dataclass(frozen=True)
class InstructionSourceToolResult(InstructionToolResult):
    """``SourceToolResult`` for a read that also carries repository instructions."""

    source_reference: SourceRef = field(kw_only=True, repr=False)
    recovery: bool = field(default=False, kw_only=True)
    slice_note: str = field(default="", kw_only=True, repr=False)  # AD-1361: as on SourceToolResult
```

**P1-2** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
    delivery_error: str = field(kw_only=True)


def _read_context(context: dict[str, Any] | None) -> WorkspaceReadContext | None:
```
REPLACE:
```python
    delivery_error: str = field(kw_only=True)


# AD-1361 (#1743 item 1): what a sliced read_file says about the whole it is a slice of, after BF-889's read_page
# sections. Plain integers, so the model can copy ``offset=`` back; lines are counted as ``str.splitlines`` counts
# them, which is how ``offset`` and ``limit`` select them.
_READ_FILE_SLICE_MORE = (
    "[read_file slice: lines {first} to {last} of {total}, counted from 0 (offset={first}, limit={count}). "
    "More follows: call read_file again with the same path and offset={last} to read on.]"
)
_READ_FILE_SLICE_END = (
    "[read_file slice: lines {first} to {last} of {total}, counted from 0 (offset={first}, limit={count}). "
    "This slice reaches the end of the file.]"
)
_READ_FILE_SLICE_EMPTY = "[read_file slice: no lines in this range. The file has {total} lines, counted from 0.]"


def _read_file_slice_note(first: int, last: int, total: int) -> str:
    """AD-1361: the note for the zero-based, end-exclusive range ``first:last`` actually returned of ``total`` lines.

    ``first`` and ``last`` are ``slice.indices`` of the request, with ``last`` never below ``first``.
    """
    if first >= last:
        return _READ_FILE_SLICE_EMPTY.format(total=total)
    template = _READ_FILE_SLICE_MORE if last < total else _READ_FILE_SLICE_END
    return template.format(first=first, last=last, total=total, count=last - first)


def with_slice_note(text: str, note: str) -> str:
    """AD-1361: ``text``, a blank line and ``note``; ``note`` alone when ``text`` is empty; ``text`` when there is no note.

    The note follows the slice, so a reader of the text from its start meets the slice first, and AD-1148's bound,
    which keeps a head and a tail, keeps the note unless the cap is too small for it.
    """
    if not note:
        return text
    return f"{text}\n\n{note}" if text else note


def _read_context(context: dict[str, Any] | None) -> WorkspaceReadContext | None:
```

**P1-3** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
def _verified_source_result(
    target: Path, runtime: object, read: WorkspaceReadContext,
    start: int | None, end: int | None,
) -> ToolResult:
```
REPLACE:
```python
def _verified_source_result(
    target: Path, runtime: object, read: WorkspaceReadContext,
    start: int | None, end: int | None, *, note_slice: bool = False,
) -> ToolResult:
```

**P1-4** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
    result = _file_read_result(text, target, runtime)
    if isinstance(result, InstructionToolResult):
        return InstructionSourceToolResult(
            output=text, repository_instructions=result.repository_instructions,
            source_reference=reference, recovery=expected is not None,
        )
    return SourceToolResult(output=text, source_reference=reference, recovery=expected is not None)
```
REPLACE:
```python
    # AD-1361 (#1743 item 1): a fresh sliced read_file carries the note naming the whole it is a slice of; a
    # recovery re-read does not, because its text is held to the per-read bound (BF-946) and the frame that made
    # its promise already named the whole.
    note = (
        _read_file_slice_note(first, max(first, last), len(lines))
        if note_slice and expected is None and not whole else ""
    )
    result = _file_read_result(text, target, runtime)
    if isinstance(result, InstructionToolResult):
        return InstructionSourceToolResult(
            output=text, repository_instructions=result.repository_instructions,
            source_reference=reference, recovery=expected is not None, slice_note=note,
        )
    return SourceToolResult(
        output=text, source_reference=reference, recovery=expected is not None, slice_note=note,
    )
```

**P1-5** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
                return await drained_result_io(
                    lambda: _verified_source_result(target, self._runtime, read, start, end),
                )
            text = target.read_text(encoding="utf-8")
            if offset is not None or limit is not None:
                lines = text.splitlines()
                start = int(offset or 0)
                end = start + int(limit) if limit is not None else len(lines)
                text = "\n".join(lines[start:end])
            return _file_read_result(text, target, self._runtime)
```
REPLACE:
```python
                return await drained_result_io(
                    lambda: _verified_source_result(target, self._runtime, read, start, end, note_slice=True),
                )
            text = target.read_text(encoding="utf-8")
            if offset is not None or limit is not None:
                lines = text.splitlines()
                start = int(offset or 0)
                end = start + int(limit) if limit is not None else len(lines)
                first, last, _ = slice(start, end).indices(len(lines))
                # AD-1361 (#1743 item 1): the slice, then the note naming the whole it is a slice of.
                note = _read_file_slice_note(first, max(first, last), len(lines))
                text = with_slice_note("\n".join(lines[start:end]), note)
            return _file_read_result(text, target, self._runtime)
```

**P1-6** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
from probos.cognitive.swe_harness.tools import (
    CodebaseReadSourceTool, InstructionSourceToolResult, ReadFileTool,
    RecoveryFailureToolResult, SourceToolResult, WorkspaceSliceToolResult,
)
```
REPLACE:
```python
from probos.cognitive.swe_harness.tools import (
    CodebaseReadSourceTool, InstructionSourceToolResult, ReadFileTool,
    RecoveryFailureToolResult, SourceToolResult, WorkspaceSliceToolResult,
    with_slice_note,
)
```

**P1-7** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
    if not count:
        raise WorkspaceResultError("source_window_unavailable")
    return (
        f"[original source v1; raw_sha256={reference.raw_sha256}; "
        f"observed lines {reference.line_start}:{reference.line_end}]\n"
```
REPLACE:
```python
    if not count:
        raise WorkspaceResultError("source_window_unavailable")
    # AD-1361 (#1743 item 1): the frame names the whole file the observed lines are a part of.
    return (
        f"[original source v1; raw_sha256={reference.raw_sha256}; "
        f"observed lines {reference.line_start}:{reference.line_end} of {reference.total_lines}]\n"
```

**P1-8** `src/probos/cognitive/swe_harness/result_offload.py`

SEARCH:
```python
        return with_result_delivery(producer, ResultDelivery("recovered", text, reference))
    if encoded_size <= TOOL_RESULT_THRESHOLD_BYTES:
        return captured.legacy_result()
    capture = canonical_capture(captured)
```
REPLACE:
```python
        return with_result_delivery(producer, ResultDelivery("recovered", text, reference))
    if encoded_size <= TOOL_RESULT_THRESHOLD_BYTES:
        if isinstance(raw, (SourceToolResult, InstructionSourceToolResult)) and raw.slice_note:
            # AD-1361 (#1743 item 1): a fresh sliced read_file states the whole it is a slice of. The note follows
            # the slice in what the model is shown; the threshold above was measured on the slice alone.
            return captured.result(with_slice_note(text, raw.slice_note))
        return captured.legacy_result()
    capture = canonical_capture(captured)
```

**P1-9** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
from probos.cognitive.swe_harness.tools import (
    InstructionSourceToolResult,
    ReadFileTool,
    RecoveryFailureToolResult,
    SourceToolResult,
    WorkspaceSliceToolResult,
    register_native_swe_tools,
)
```
REPLACE:
```python
from probos.cognitive.swe_harness.tools import (
    InstructionSourceToolResult,
    ReadFileTool,
    RecoveryFailureToolResult,
    SourceToolResult,
    WorkspaceSliceToolResult,
    register_native_swe_tools,
    with_slice_note,
)
```

**P1-10** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
    assert isinstance(native, ToolResult) and not isinstance(native, _SOURCE_RESULTS)
    assert isinstance(armed, _SOURCE_RESULTS)
    assert armed.output == native.output  # universal newlines, slicing and the trailing newline
```
REPLACE:
```python
    assert isinstance(native, ToolResult) and not isinstance(native, _SOURCE_RESULTS)
    assert isinstance(armed, _SOURCE_RESULTS)
    # AD-1361 (#1743 item 1): a sliced read_file states the whole. The plain path puts the note in its text; the
    # verified path carries it beside its text, and AD-1240's delivery shows it, so the text stays the slice.
    assert bool(armed.slice_note) == (reader == "read_file" and bool(arguments))
    assert native.output == with_slice_note(armed.output, armed.slice_note)  # universal newlines, slicing, trailing newline
```

**P1-11** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
    raw = await _invoke(executor, "read_file", {"path": str(path), "offset": 1, "limit": 1}, context)
    assert isinstance(raw, ToolResult) and not isinstance(raw, _SOURCE_RESULTS)
    assert raw.error is None and raw.output == "second"
```
REPLACE:
```python
    raw = await _invoke(executor, "read_file", {"path": str(path), "offset": 1, "limit": 1}, context)
    assert isinstance(raw, ToolResult) and not isinstance(raw, _SOURCE_RESULTS)
    # AD-1361 (#1743 item 1): the plain path's slice is followed by the note naming the whole.
    assert raw.error is None and raw.output == (
        "second\n\n[read_file slice: lines 1 to 2 of 3, counted from 0 (offset=1, limit=1). "
        "More follows: call read_file again with the same path and offset=2 to read on.]"
    )
```

**P1-12** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
    ("read_file", {"offset": -2, "limit": 1}, "c"),
    ("read_file", {"offset": 1, "limit": 0}, ""),
    ("read_file", {}, "a\nb\nc\nd\n"),
```
REPLACE:
```python
    # AD-1361 (#1743 item 1): the model is shown a sliced read_file's note after the slice (the range actually
    # returned, of the 4 lines); an empty range is the note alone; a whole read is unchanged.
    ("read_file", {"offset": -2, "limit": 1}, (
        "c\n\n[read_file slice: lines 2 to 3 of 4, counted from 0 (offset=2, limit=1). "
        "More follows: call read_file again with the same path and offset=3 to read on.]"
    )),
    ("read_file", {"offset": 1, "limit": 0}, "[read_file slice: no lines in this range. The file has 4 lines, counted from 0.]"),
    ("read_file", {}, "a\nb\nc\nd\n"),
```

**P1-13** `tests/test_ad1240_tool_result_delivery.py`

SEARCH:
```python
            expected = "REPLACEMENT_PAYLOAD" if change == "physical" else canonical.splitlines()[0]
            assert _last_result(fresh_llm.requests[-1]) == expected
            assert isinstance(observed[-1], _SOURCE_RESULTS)
            assert observed[-1].recovery is False
```
REPLACE:
```python
            expected = "REPLACEMENT_PAYLOAD" if change == "physical" else canonical.splitlines()[0]
            assert isinstance(observed[-1], _SOURCE_RESULTS)
            assert observed[-1].recovery is False
            # AD-1361 (#1743 item 1): the fresh sliced read keeps its text and is shown with the note naming the whole.
            assert observed[-1].output == expected and observed[-1].slice_note.startswith("[read_file slice: lines 0 to 1 of ")
            assert _last_result(fresh_llm.requests[-1]) == with_slice_note(expected, observed[-1].slice_note)
```

**P1-14** `tests/test_ad1200_repository_instruction_wire.py`

SEARCH:
```python
    result = await reader.invoke(params)
    assert isinstance(result, InstructionToolResult)
    assert result.output == "beta" and result.metadata == {} and result.error is None
    assert "NOT-SOURCE-OUTPUT" not in repr(result)
    adapted = ToolCallResult.from_tool_result("call", result, 12.5)
    assert isinstance(adapted, InstructionToolCallResult)
    assert adapted.output == "beta" and adapted.duration_ms == 12.5
```
REPLACE:
```python
    result = await reader.invoke(params)
    assert isinstance(result, InstructionToolResult)
    # AD-1361 (#1743 item 1): a sliced read_file states the whole after the slice; codebase_read_source does not.
    expected = "beta" if tool == "codebase_read_source" else (
        "beta\n\n[read_file slice: lines 1 to 2 of 2, counted from 0 (offset=1, limit=1). "
        "This slice reaches the end of the file.]"
    )
    assert result.output == expected and result.metadata == {} and result.error is None
    assert "NOT-SOURCE-OUTPUT" not in repr(result)
    adapted = ToolCallResult.from_tool_result("call", result, 12.5)
    assert isinstance(adapted, InstructionToolCallResult)
    assert adapted.output == expected and adapted.duration_ms == 12.5
```

### 7.2 New file: `tests/test_ad1361_slice_notes.py` (M1)

```python
"""AD-1361 (#1743 item 1): a sliced ``read_file`` states the whole it is a slice of.

The plain path (no read context) puts the note in the result's text. The verified path (every ``read_file`` the
loop arms under an AD-1240 delivery run) carries it beside the text as ``slice_note``; the delivery adds it to what
the model is shown, so the slice text, the offload threshold, the per-read bound and a source frame's line count
are measured on the slice alone. A recovery re-read carries no note, and ``codebase_read_source`` is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.result_offload import DeliveryContext, prepare_result
from probos.cognitive.swe_harness.tool_call import capture_tool_result, result_delivery
from probos.execution.workspace_results import FreshRead, RecoverRead, WorkspaceReadContext
from tests.offered_tools import offer
from tests.test_ad1240_tool_result_delivery import (
    _SETTINGS,
    _SOURCE_RESULTS,
    _FakeLLM,
    _done,
    _environment,
    _invoke,
    _last_result,
    _new_run,
    _promise_source,
    _turn,
    _verbatim_call,
    _write_source,
)

_FIVE = b"l0\nl1\nl2\nl3\nl4\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,expected", [
    pytest.param({"offset": 1, "limit": 2}, (
        "l1\nl2\n\n[read_file slice: lines 1 to 3 of 5, counted from 0 (offset=1, limit=2). "
        "More follows: call read_file again with the same path and offset=3 to read on.]"
    ), id="more-follows"),
    pytest.param({"offset": 3, "limit": 10}, (
        "l3\nl4\n\n[read_file slice: lines 3 to 5 of 5, counted from 0 (offset=3, limit=2). "
        "This slice reaches the end of the file.]"
    ), id="reaches-the-end"),
    pytest.param({"offset": 2}, (
        "l2\nl3\nl4\n\n[read_file slice: lines 2 to 5 of 5, counted from 0 (offset=2, limit=3). "
        "This slice reaches the end of the file.]"
    ), id="offset-only"),
    pytest.param(
        {"offset": 9, "limit": 2},
        "[read_file slice: no lines in this range. The file has 5 lines, counted from 0.]",
        id="past-the-end",
    ),
    pytest.param(
        {"limit": 0},
        "[read_file slice: no lines in this range. The file has 5 lines, counted from 0.]",
        id="limit-zero",
    ),
    pytest.param({}, "l0\nl1\nl2\nl3\nl4\n", id="whole-file"),
])
async def test_a_plain_sliced_read_states_the_whole(
    tmp_path: Path, arguments: dict[str, int], expected: str,
) -> None:
    """The plain path: the slice, a blank line and the note; the note alone for a range with no lines; a whole read
    unchanged."""
    _runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    result = await _invoke(executor, "read_file", {"path": str(path), **arguments}, context)
    assert result.error is None and not isinstance(result, _SOURCE_RESULTS)  # premise: the plain path
    assert result.output == expected


@pytest.mark.asyncio
async def test_codebase_read_source_slices_carry_no_note(tmp_path: Path) -> None:
    """L3: ``codebase_read_source`` keeps its slice text alone, on the plain and the verified path."""
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    params = {"file_path": str(path), "start_line": 2, "end_line": 3}
    plain = await _invoke(executor, "codebase_read_source", params, context)
    read = await _new_run(runtime, context).invocation_context("codebase_read_source", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead  # premise: the verified path
    armed = await _invoke(executor, "codebase_read_source", params, context, read=read)
    assert not isinstance(plain, _SOURCE_RESULTS) and plain.output == "l1\nl2"
    assert isinstance(armed, _SOURCE_RESULTS) and armed.output == "l1\nl2" and armed.slice_note == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_a_fresh_sliced_read_through_the_loop_states_the_whole_and_the_next_read_follows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    """The seam: the verified read's note reaches the model's next request, and a read at the offset it names is
    served and states the end of the file."""
    runtime, executor, context = _environment(tmp_path)
    path = tmp_path / "five.txt"
    path.write_bytes(_FIVE)
    real_read_text = Path.read_text
    plain_reads: list[Path] = []

    def watched_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == path:
            plain_reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", watched_read_text)
    llm = _FakeLLM([
        _turn("read_file", _call_id="first", path=str(path), offset=0, limit=3),
        _turn("read_file", _call_id="second", path=str(path), offset=3, limit=3),
        _done(),
    ])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=executor, max_iterations=4, tool_result_max_chars=6000,
        structured_tool_messages=structured, workspace_results=runtime.workspace_results,
    )
    result = await loop.run(system_prompt="", user_message="", tools=[*offer("read_file")], context=context)
    first = (
        "l0\nl1\nl2\n\n[read_file slice: lines 0 to 3 of 5, counted from 0 (offset=0, limit=3). "
        "More follows: call read_file again with the same path and offset=3 to read on.]"
    )
    second = (
        "l3\nl4\n\n[read_file slice: lines 3 to 5 of 5, counted from 0 (offset=3, limit=2). "
        "This slice reaches the end of the file.]"
    )
    assert plain_reads == []  # premise: both reads took the verified path, not the plain one
    assert result.stopped_reason == "complete" and len(llm.requests) == 3
    assert _last_result(llm.requests[1]) == first and _last_result(llm.requests[2]) == second
    assert [item.output for item in result.tool_results] == [first, second]
    assert not runtime.workspace_results.root.exists()


@pytest.mark.asyncio
async def test_an_offloaded_fresh_slice_names_the_whole_in_its_frame_and_keeps_its_line_count(
    tmp_path: Path,
) -> None:
    """A fresh slice over the threshold is shown as a source frame naming the whole; the note is not in the frame,
    and the frame's worked call counts source lines only."""
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path, lines=400)
    params = {"path": str(source), "offset": 10, "limit": 160}
    run = _new_run(runtime, context)
    read = await run.invocation_context("read_file", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is FreshRead
    raw = await _invoke(executor, "read_file", params, context, read=read)
    assert isinstance(raw, _SOURCE_RESULTS) and raw.recovery is False
    assert len(raw.output.encode("utf-8")) > 12288  # premise: offloaded, not delivered inline
    assert raw.slice_note == (
        "[read_file slice: lines 10 to 170 of 400, counted from 0 (offset=10, limit=160). "
        "More follows: call read_file again with the same path and offset=170 to read on.]"
    )
    captured = capture_tool_result("call", raw, 1.0, max_chars=_SETTINGS.max_chars)
    delivered = await prepare_result(captured, DeliveryContext(run, 4))
    delivery = result_delivery(delivered)
    assert delivery is not None and delivery.status == "source"
    assert delivery.presentation.splitlines()[0].endswith("; observed lines 10:170 of 400]")
    assert "[read_file slice:" not in delivery.presentation
    name, arguments = _verbatim_call(delivery.presentation)
    # 92-character source lines: 64 of them fit the 6,000-character allowance; the note is counted in none.
    assert (name, arguments["offset"], arguments["limit"]) == ("read_file", 10, 64)
    assert delivered.output == raw.output  # the producer's text is the slice alone


@pytest.mark.asyncio
async def test_a_recovery_read_carries_no_note_and_is_delivered_as_the_slice_alone(tmp_path: Path) -> None:
    """L1: a promised source re-read is held to BF-946's per-read bound, so it carries no note."""
    runtime, executor, context = _environment(tmp_path)
    source = _write_source(tmp_path)
    run, original = await _promise_source(runtime, executor, context, source)
    params = {"path": str(source), "offset": 20, "limit": 3}
    read = await run.invocation_context("read_file", params)
    assert type(read) is WorkspaceReadContext and type(read.directive) is RecoverRead  # premise: a promise
    recovered = await _invoke(executor, "read_file", params, context, read=read)
    assert isinstance(recovered, _SOURCE_RESULTS) and recovered.recovery is True
    assert recovered.slice_note == ""
    slice_text = "\n".join(original.output.splitlines()[20:23])
    assert recovered.output == slice_text
    captured = capture_tool_result("call", recovered, 1.0, max_chars=_SETTINGS.max_chars)
    delivery = result_delivery(await prepare_result(captured, DeliveryContext(run, 4)))
    assert delivery is not None and delivery.status == "recovered" and delivery.presentation == slice_text
```

### 7.3 M2

**P2-1** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
# --------------------------------------------------------------------------
# Read-only tools (Trust 0.0+ Ensign / READ permission)
# --------------------------------------------------------------------------
```
REPLACE:
```python
# AD-1361 (#1743 item 2): a refusal names the nearest action this agent has. list_files is registered beside
# read_file with the same permissions (register_native_swe_tools) and lists only what the read policy admits
# (BF-948). Where no tool fits, the agent's reply is the action. Each sentence is kept clear of
# decomposer._CAPABILITY_GAP_RE (tests/test_ad1361_refusal_next_actions.py).
_READ_REFUSAL_NEXT = (
    "Do not repeat this call with the same path: read another file, and use list_files to see which files you can read."
)
_LIST_REFUSAL_NEXT = "Do not repeat this call with the same path: list another directory."
_WRITE_REFUSAL_NEXT = (
    "Do not repeat this call: leave this file as it is, go on with the rest of your task, "
    "and say in your reply what change you wanted."
)


# --------------------------------------------------------------------------
# Read-only tools (Trust 0.0+ Ensign / READ permission)
# --------------------------------------------------------------------------
```

**P2-2** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
                if not isinstance(exc, FileAccessDenied):
                    raise  # BF-948: only the policy's refusal carries the refusal mark; any other error is a failure
                return ToolResult(error=f"read_file refused: {exc}")
```
REPLACE:
```python
                if not isinstance(exc, FileAccessDenied):
                    raise  # BF-948: only the policy's refusal carries the refusal mark; any other error is a failure
                return ToolResult(error=f"read_file refused: {exc}. {_READ_REFUSAL_NEXT}")  # AD-1361: and the next action
```

**P2-3** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
                    permitted_roots=permitted, relative_base=_PROJECT_ROOT,
                )
            except FileAccessDenied as exc:
                return ToolResult(error=f"list_files refused: {exc}")
```
REPLACE:
```python
                    permitted_roots=permitted, relative_base=_PROJECT_ROOT,
                )
            except FileAccessDenied as exc:
                return ToolResult(error=f"list_files refused: {exc}. {_LIST_REFUSAL_NEXT}")  # AD-1361: and the next action
```

**P2-4** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)
```
REPLACE:
```python
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel. "
    "Do not repeat this call for it: say in your reply which file you needed."  # AD-1361: the next action
)
```

**P2-5** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: write_file
            if refused is not None:
                logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: write_file
            if refused is not None:
                logger.warning("BF-943 WriteFileTool refused operation=write_file reason_code=captain_document_refused")
                return ToolResult(error=f"write_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file
            if refused is not None:
                logger.warning("BF-911 WriteFileTool refused operation=write_file reason_code=protected_write_refused")
                return ToolResult(error=refused)
```
REPLACE:
```python
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: write_file
            if refused is not None:
                logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")
                return ToolResult(error=f"{refused}. {_WRITE_REFUSAL_NEXT}")  # AD-1361 (AD-1344 rule): write_file names the next action
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: write_file
            if refused is not None:
                logger.warning("BF-943 WriteFileTool refused operation=write_file reason_code=captain_document_refused")
                return ToolResult(error=f"write_file refused: {refused}. {_WRITE_REFUSAL_NEXT}")  # BF-975 (#1806): marked, so the two fault detectors skip it; AD-1361: the next action
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file
            if refused is not None:
                logger.warning("BF-911 WriteFileTool refused operation=write_file reason_code=protected_write_refused")
                return ToolResult(error=f"{refused}. {_WRITE_REFUSAL_NEXT}")  # AD-1361 (BF-911 rule): write_file names the next action
```

**P2-6** `src/probos/cognitive/swe_harness/tools.py`

SEARCH:
```python
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: edit_file
            if refused is not None:
                logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: edit_file
            if refused is not None:
                logger.warning("BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused")
                return ToolResult(error=f"edit_file refused: {refused}")  # BF-975 (#1806): marked, so the two fault detectors skip it
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file
            if refused is not None:
                logger.warning("BF-911 EditFileTool refused operation=edit_file reason_code=protected_write_refused")
                return ToolResult(error=refused)
```
REPLACE:
```python
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: edit_file
            if refused is not None:
                logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")
                return ToolResult(error=f"{refused}. {_WRITE_REFUSAL_NEXT}")  # AD-1361 (AD-1344 rule): edit_file names the next action
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: edit_file
            if refused is not None:
                logger.warning("BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused")
                return ToolResult(error=f"edit_file refused: {refused}. {_WRITE_REFUSAL_NEXT}")  # BF-975 (#1806): marked, so the two fault detectors skip it; AD-1361: the next action
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file
            if refused is not None:
                logger.warning("BF-911 EditFileTool refused operation=edit_file reason_code=protected_write_refused")
                return ToolResult(error=f"{refused}. {_WRITE_REFUSAL_NEXT}")  # AD-1361 (BF-911 rule): edit_file names the next action
```

**P2-7** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
SECRET_NAME = "secret-name-948.txt"
_OUTSIDE = "list_files refused: path is outside every readable root"
_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file"
```
REPLACE:
```python
SECRET_NAME = "secret-name-948.txt"
# AD-1361 (#1743 item 2): a policy refusal now ends with the next action; the mark and the reason are unchanged.
_LIST_NEXT = ". Do not repeat this call with the same path: list another directory."
_READ_OUTSIDE = (
    "read_file refused: path is outside every readable root. Do not repeat this call with the same path: "
    "read another file, and use list_files to see which files you can read."
)
_OUTSIDE = "list_files refused: path is outside every readable root" + _LIST_NEXT
_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file" + _LIST_NEXT
```

**P2-8** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
    runtime = _runtime(scene, read_roots=[scene.allowed])
    refused = await ReadFileTool(runtime).invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise
```
REPLACE:
```python
    runtime = _runtime(scene, read_roots=[scene.allowed])
    refused = await ReadFileTool(runtime).invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == _READ_OUTSIDE  # premise (AD-1361: with the next action)
```

**P2-9** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
        runtime = _runtime(scene, read_roots=[scene.allowed])
        refused = await ReadFileTool(runtime).invoke({"path": str(door / SECRET_NAME)})
        assert refused.error == "read_file refused: path is outside every readable root"  # premise
```
REPLACE:
```python
        runtime = _runtime(scene, read_roots=[scene.allowed])
        refused = await ReadFileTool(runtime).invoke({"path": str(door / SECRET_NAME)})
        assert refused.error == _READ_OUTSIDE  # premise (AD-1361: with the next action)
```

**P2-10** `tests/test_bf948_list_files_read_policy.py`

SEARCH:
```python
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.allowed]))
    refused = await reader.invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == "read_file refused: path is outside every readable root"  # premise
```
REPLACE:
```python
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.allowed]))
    refused = await reader.invoke({"path": str(scene.outside / SECRET_NAME)})
    assert refused.error == _READ_OUTSIDE  # premise (AD-1361: with the next action)
```

**P2-11** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
```python
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"
```
REPLACE:
```python
_CONTENT = b"bf953 fixture"
# AD-1361 (#1743 item 2): read_file's policy refusal now ends with the next action.
_READ_NEXT = (
    ". Do not repeat this call with the same path: read another file, and use list_files to see which files you can read."
)
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file" + _READ_NEXT
_READ_OUTSIDE = "read_file refused: path is outside every readable root" + _READ_NEXT
```

**P2-12** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
```python
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.root]))
    answered = await reader.invoke({"path": shared})
    assert answered.error == f"read_file refused: {_UNVERIFIED_REASON}" and answered.output is None
```
REPLACE:
```python
    reader = ReadFileTool(_runtime(scene, read_roots=[scene.root]))
    answered = await reader.invoke({"path": shared})
    assert answered.error == f"read_file refused: {_UNVERIFIED_REASON}{_READ_NEXT}" and answered.output is None
```

**P2-13** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
```python
    assert config_stream.error == _READ_PROTECTED and config_stream.output is None
    vault_stream = await reader.invoke({"path": str(vault) + ":zz"})
    assert vault_stream.error == f"read_file refused: {_LEAF_REASON}" and vault_stream.output is None
```
REPLACE:
```python
    assert config_stream.error == _READ_PROTECTED and config_stream.output is None
    vault_stream = await reader.invoke({"path": str(vault) + ":zz"})
    assert vault_stream.error == f"read_file refused: {_LEAF_REASON}{_READ_NEXT}" and vault_stream.output is None
```

**P2-14** `tests/test_bf911_protected_config_write_refusal.py`

SEARCH:
```python
        except Exception as exc:  # r1's route under the dispatch context: NoEffectFailure("file_not_found")
            outcomes.append(f"raised {type(exc).__name__}")
    assert outcomes == [refusal, refusal], outcomes
```
REPLACE:
```python
        except Exception as exc:  # r1's route under the dispatch context: NoEffectFailure("file_not_found")
            outcomes.append(f"raised {type(exc).__name__}")
    # AD-1361 (#1743 item 2): edit_file returns the rule's refusal followed by the next action.
    answered = (
        f"{refusal}. Do not repeat this call: leave this file as it is, go on with the rest of your task, "
        "and say in your reply what change you wanted."
    )
    assert outcomes == [answered, answered], outcomes
```

### 7.4 New file: `tests/test_ad1361_refusal_next_actions.py` (M2)

```python
"""AD-1361 (#1743 item 2): every refusal in ``cognitive/swe_harness/tools.py`` names the nearest action the agent has.

The contract's census (section 3) classifies the file's 49 error returns on 9f43697f. The nine refusals that named no
next action now end with one sentence; refusals that already named one, input errors, failures and AD-1240 delivery
codes are unchanged. A ToolResult error added to or removed from a tool class fails the census until it is classified
under this convention.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import llm_function_name
from probos.cognitive.swe_harness.tools import EditFileTool, ReadFileTool, WriteFileTool, register_native_swe_tools
from probos.tools.protocol import is_caller_input_error
from probos.tools.registry import ToolRegistry
from tests.test_bf948_list_files_read_policy import SECRET_NAME, _list, _runtime, _scene

_READ_NEXT = (
    "Do not repeat this call with the same path: read another file, and use list_files to see which files you can read."
)
_LIST_NEXT = "Do not repeat this call with the same path: list another directory."
_WRITE_NEXT = (
    "Do not repeat this call: leave this file as it is, go on with the rest of your task, "
    "and say in your reply what change you wanted."
)
_STANDING_ORDERS_NEXT = "Do not repeat this call for it: say in your reply which file you needed."
_RULE = "RULE-TEXT-1361"
_RULES = ("constitution_write_refusal", "captain_document_write_refusal", "protected_write_refusal")

# Each sentence and the tools whose refusal ends with it.
_REFUSED_BY = {
    _READ_NEXT: ("read_file",),
    _LIST_NEXT: ("list_files",),
    _WRITE_NEXT: ("write_file", "edit_file"),
    _STANDING_ORDERS_NEXT: ("standing_orders_lookup",),
}

# The census (contract section 3): ToolResult and RecoveryFailureToolResult calls with an ``error`` keyword, per tool
# class, on 9f43697f. AD-1361 changes texts, never the number of returns.
_ERROR_RETURNS = {
    "ReadFileTool": 5, "ListFilesTool": 5, "CodebaseQueryTool": 3, "CodebaseFindCallersTool": 3,
    "CodebaseFindTestsTool": 3, "CodebaseGetImportsTool": 3, "CodebaseReadSourceTool": 4,
    "StandingOrdersLookupTool": 5, "SystemSelfModelTool": 1, "WriteFileTool": 6, "EditFileTool": 7,
    "RunCommandTool": 4,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", ["read_file", "list_files"])
async def test_read_and_list_refusals_name_the_next_action(tmp_path: Path, tool_id: str) -> None:
    """The policy's refusal keeps BF-948's mark and its reason, then names the next action."""
    scene = _scene(tmp_path)
    if tool_id == "read_file":
        result = await ReadFileTool(_runtime(scene, read_roots=[scene.allowed])).invoke(
            {"path": str(scene.outside / SECRET_NAME)},
        )
        base, sentence = "read_file refused: path is outside every readable root", _READ_NEXT
    else:
        result = await _list(scene, [scene.allowed], "*", str(scene.outside))
        base, sentence = "list_files refused: path is outside every readable root", _LIST_NEXT
    assert result.output is None and (result.error or "").startswith(base)  # premise: the policy refused
    assert result.error == f"{base}. {sentence}"
    assert is_caller_input_error(tool_id, result.error)  # the mark is kept, so both fault detectors still skip it


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", _RULES)
@pytest.mark.parametrize("tool_id", ["write_file", "edit_file"])
async def test_write_refusals_name_the_next_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_id: str, rule: str,
) -> None:
    """Each write rule as the tool returns it: the rule's text (marked for the Captain-document rule, as BF-975 left
    it), then the next action. The target is a temporary file, so nothing outside ``tmp_path`` could be written even
    if a refusal were lost."""
    for name in _RULES:
        monkeypatch.setattr(swe_tools, name, (lambda *_a, **_k: _RULE) if name == rule else (lambda *_a, **_k: None))
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    tool = WriteFileTool(SimpleNamespace()) if tool_id == "write_file" else EditFileTool(SimpleNamespace())
    params = (
        {"path": str(target), "content": "new"} if tool_id == "write_file"
        else {"path": str(target), "old_text": "old", "new_text": "new"}
    )
    result = await tool.invoke(params)
    base = f"{tool_id} refused: {_RULE}" if rule == "captain_document_write_refusal" else _RULE
    assert (result.error or "").startswith(base)  # premise: that rule refused
    assert result.error == f"{base}. {_WRITE_NEXT}"
    assert target.read_text(encoding="utf-8") == "old"


def test_the_standing_orders_denial_and_the_sentences_are_pinned() -> None:
    """BF-910's tests prove the tool returns ``_STANDING_ORDERS_DENIED`` for a refused read; this pins its text and the
    three sentences the other refusals append."""
    assert swe_tools._STANDING_ORDERS_DENIED == (
        "standing_orders_lookup: that standing-orders file is not readable on this vessel. " + _STANDING_ORDERS_NEXT
    )
    assert (swe_tools._READ_REFUSAL_NEXT, swe_tools._LIST_REFUSAL_NEXT, swe_tools._WRITE_REFUSAL_NEXT) == (
        _READ_NEXT, _LIST_NEXT, _WRITE_NEXT,
    )


def test_each_next_action_reads_as_no_gap_and_names_only_tools_the_refused_agent_has() -> None:
    """No sentence reads as a capability gap; a tool a sentence names is registered with the refused tool's own
    permission matrix and spelled as the model sees it."""
    registry = ToolRegistry()
    assert register_native_swe_tools(registry, SimpleNamespace()) == 12
    named_any = False
    for sentence, refused_by in _REFUSED_BY.items():
        assert _CAPABILITY_GAP_RE.search(sentence) is None, sentence
        for name in sorted(set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", sentence))):
            named_any = True
            registration = registry.get(name)
            assert registration is not None, f"{name} is not a registered tool"
            assert llm_function_name(name) == name
            for tool_id in refused_by:
                assert registration.default_permissions == registry.get(tool_id).default_permissions, (name, tool_id)
    assert named_any, "premise: at least one sentence names a tool"


def test_every_error_return_in_the_native_tools_is_counted() -> None:
    """The census: an error return added to or removed from a native tool class is classified under AD-1361's
    convention (a refusal names the nearest action this agent has) before this table changes."""
    tree = ast.parse(Path(swe_tools.__file__).read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        found = sum(
            1 for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id in ("ToolResult", "RecoveryFailureToolResult")
            and any(keyword.arg == "error" for keyword in call.keywords)
        )
        if found:
            counts[node.name] = found
    assert sum(counts.values()) > 0, "premise: the census found the native tools' error returns"
    assert counts == _ERROR_RETURNS, "classify the added or removed error return under AD-1361, then update the table"
```

### 7.5 M3 (its own commit)

**P3-1** `prompts/review-criteria.md`

SEARCH:
```
- **Consistency with prior art:** Does the fix pattern match how similar issues were resolved before? Check DECISIONS.md for precedent.
- **Rollback path:** If the fix causes problems, can it be reverted cleanly? Any migration or state change that complicates rollback?

## 9. Prompt Structure
```
REPLACE:
```
- **Consistency with prior art:** Does the fix pattern match how similar issues were resolved before? Check DECISIONS.md for precedent.
- **Rollback path:** If the fix causes problems, can it be reverted cleanly? Any migration or state change that complicates rollback?
- **Parity for a store the crew relies on:** If the prompt adds or changes a store an agent is meant to rely on as it relies on memory (for example AD-1240's workspace results, or the results BF-947 carries across resumes), ask three questions. Is it there when the agent needs it, without a special request? Can the agent tell who wrote each item and when? Is it governed like memory: kept, not deleted (AD-1340); private by default where it is personal (AD-1157); checked for currency (AD-1302)? A store that fails the first two is shown to the agent as a source to check, not as something it knows. (`docs/research/clark-extended-mind-absorption.md` item 3; #1743 item 6.)

## 9. Prompt Structure
```

### 7.6 M4

See §8.

## 8. Tracking (M4's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`) in its first 120 characters. Do not write "open" or "closed" there.
**Date rule:** both heads carry 2026-11-18. If M4 is committed on a later date (`git log -1 --format=%cs`), use that date in both.

**P4-1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1361 (2026-11-18), #1743 items 1, 2 and 6 -- a sliced read_file states the whole it is a slice of, and the native tools' refusals name the next action.** A `read_file` call with `offset` or `limit` returns its slice, a blank line and one bracketed note. The note gives the lines shown (counted from 0) of the file's total and the `offset` and `limit` that give them. It then gives the `offset` that reads on, or says that the slice reaches the end, or says that the range holds no lines. On the plain path the note is in the result's text. On the verified path (every `read_file` under an AD-1240 delivery run) it is carried beside the text as `slice_note`, and the delivery adds it to what the model is shown. The slice text, the offload threshold, the per-read bound and a source frame's line count are therefore measured on the slice alone. An offloaded source frame now says `observed lines A:B of N`. A recovery re-read and a read of an offloaded artifact carry no note, because their frame named the whole. `codebase_read_source` is unchanged. The nine refusals in `cognitive/swe_harness/tools.py` that named no next action now end with one sentence: `read_file` and `list_files` policy refusals (BF-948's mark kept), the standing-orders denial, and the three write rules of `write_file` and `edit_file`. A census test counts the file's 49 error returns. Item 6 adds the parity question to `prompts/review-criteria.md` section 8. Items 3, 4, 5 and 7 of #1743 are untouched. No config field, no event type. The contract is `prompts/ad-1361-tool-results-state-the-whole-and-refusals-name-the-next-action.md`.

```

**P4-2** `DECISIONS.md`

SEARCH:
```
### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```
REPLACE:
```
### AD-1361 -- A sliced read_file states the whole it is a slice of, and the native tools' refusals name the next action (2026-11-18, #1743)

- *Scope.* `cognitive/swe_harness/tools.py` (`with_slice_note`, `_read_file_slice_note`, `SourceToolResult.slice_note`, the refusal sentences), `cognitive/swe_harness/result_offload.py` (the legacy branch of `_prepare_result`, `_source_frame`), tests. #1743 items 1 and 2. Item 6 is one bullet in `prompts/review-criteria.md` section 8 and takes no number. Contract `prompts/ad-1361-tool-results-state-the-whole-and-refusals-name-the-next-action.md`.
- *The note.* Lines as `str.splitlines` counts them, the range actually returned, three fixed texts (more follows, reaches the end, no lines), placed after the slice. It follows BF-889's `read_page` sections.
- *Placement by path.* The plain path puts it in the text. The verified path carries it beside the text, and the AD-1240 legacy delivery appends it. A note inside the verified text was rejected: it would count against the per-read bound (BF-946) and the source frame's line count. A recovery re-read and an artifact slice carry none, because their frame named the whole (`of N` on the source frame; `chars` in the artifact outline).
- *Refusals.* A refusal says what was refused and why, then one sentence naming the nearest action this agent has. Where no tool fits, that action is the agent's reply. Only `list_files` is named, because it is registered beside `read_file` with the same permissions. Appending keeps BF-948's mark and the identity of repeated texts, so the fault detectors decide as before. The first family is `tools.py`. #1722 S3 keeps the agent-work refusals, and the other families follow on #1743.
- *Rejected.* A typed note rendered by the loop (more code for the same effect). Reserving room in the frames for a note on recovery reads (it moves the AD-1240 accounting). Covering `codebase_read_source` now (it needs its own 1-based sentence). Editing the rule texts in `builder_paths.py` and `file_access.py` (other writers return them).
- *Residual.* Recorded limits L1 to L12 of the contract.
- *Reversal.* Revert the AD-1361 commits. Item 6's bullet is reverted on its own.

### BF-946 -- A read-only call's failed delivery comes back to the agent as an error, and the run goes on (2026-11-02, #1723)
```

Then regenerate the ledger (`d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (no BF).

**#1743 checklist update** (the orchestrator posts it; the body keeps the Captain's admission lines):
- under item 1: `**Done (AD-1361 M1, PR #<n>, <date>):** a sliced read_file ends with a note naming the lines shown, the file's total and the next offset. The verified path carries it beside the text, so the AD-1240 bounds are unchanged. Recovery re-reads and offloaded-artifact reads carry none (their frame names the whole); codebase_read_source is not covered.`
- under item 2: `**First family done (AD-1361 M2, PR #<n>, <date>):** every refusal in cognitive/swe_harness/tools.py names the next action (census of 49 error returns in the contract, section 3). Remaining families: the tool modules under src/probos/tools/, the Copilot adapter's standing-orders copy, and the rule texts other writers return. #1722 S3 keeps the agent-work refusals.`
- under item 6: `**Done (PR #<n>, <date>):** prompts/review-criteria.md section 8 asks the parity question.`
- closing line: `Items 3, 4, 5 and 7 are untouched. This issue stays open for them and for item 2's remaining families.`

## 9. What this does NOT change

- AD-1240's promised-recovery semantics, BF-946's per-read bound and retry text, `ResultDelivery`, the threshold, `canonical_capture`, the workspace frame, and `_source_frame`'s allowance and count.
- `codebase_read_source`, `_workspace_slice_result`, tool schemas and descriptions (the AD-1179 golden), and AD-1148's truncation.
- `is_caller_input_error`, `POLICY_REFUSAL_MARK`, the two fault detectors, `_NEVER_RAN_REFUSALS`, and the rule texts in `builder_paths.py` and `security/file_access.py`.
- The `run_command` and AD-1328 frames, `refuse_undeclared_params`, and the `codebase_index unavailable on runtime` texts.
- `cognitive/copilot_adapter.py`'s `_STANDING_ORDERS_DENIED`.
- `agentic_loop.py`, `tool_call.py`, `workspace_results.py`. No method is added to any class. No config field, no `EventType`.
- #1743 items 3, 4, 5 and 7, and #1722 S3.

## 10. Mutation rows (campaign of record on M2's head)

The Line cells hold the source line without its leading indentation. Each occurs once in its file. Prefixes `SL` and `RF` are absent from `DECISIONS.md` and `prompts/ad-13*.md` and `prompts/bf-9*.md`.

| Id | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| SL-1 | `tools.py` | `text = with_slice_note("\n".join(lines[start:end]), note)` | `text = "\n".join(lines[start:end])` | `test_a_plain_sliced_read_states_the_whole` |
| SL-2 | `tools.py` | `template = _READ_FILE_SLICE_MORE if last < total else _READ_FILE_SLICE_END` | `... if last <= total else ...` | `test_a_plain_sliced_read_states_the_whole[reaches-the-end]` |
| SL-3 | `tools.py` | `if first >= last:` | `if first > last:` | `test_a_plain_sliced_read_states_the_whole[past-the-end]` |
| SL-4 | `tools.py` | `return f"{text}\n\n{note}" if text else note` | `return f"{text}\n\n{note}"` | `test_a_plain_sliced_read_states_the_whole[past-the-end]` |
| SL-5 | `tools.py` | `if note_slice and expected is None and not whole else ""` | `if note_slice and not whole else ""` | `test_a_recovery_read_carries_no_note_and_is_delivered_as_the_slice_alone` |
| SL-6 | `tools.py` | `lambda: _verified_source_result(target, self._runtime, read, start, end, note_slice=True),` | `..., note_slice=False),` | `test_a_fresh_sliced_read_through_the_loop_states_the_whole_and_the_next_read_follows_it` |
| SL-7 | `result_offload.py` | `return captured.result(with_slice_note(text, raw.slice_note))` | `return captured.legacy_result()` | `test_a_fresh_sliced_read_through_the_loop_states_the_whole_and_the_next_read_follows_it` |
| SL-8 | `result_offload.py` | `f"observed lines {reference.line_start}:{reference.line_end} of {reference.total_lines}]\n"` | `f"observed lines {reference.line_start}:{reference.line_end}]\n"` | `test_an_offloaded_fresh_slice_names_the_whole_in_its_frame_and_keeps_its_line_count` |
| SL-9 | `tools.py` | `if not note:` | `if False:` | `test_armed_fresh_read_returns_the_native_content_with_a_verified_reference[read_file-arguments0]` (`test_ad1240`) |
| RF-1 | `tools.py` | `return ToolResult(error=f"read_file refused: {exc}. {_READ_REFUSAL_NEXT}")  # AD-1361: and the next action` | `return ToolResult(error=f"read_file refused: {exc}")` | `test_read_and_list_refusals_name_the_next_action[read_file]` |
| RF-2 | `tools.py` | `return ToolResult(error=f"list_files refused: {exc}. {_LIST_REFUSAL_NEXT}")  # AD-1361: and the next action` | `return ToolResult(error=f"list_files refused: {exc}")` | `test_read_and_list_refusals_name_the_next_action[list_files]` |
| RF-3 | `tools.py` | `"Do not repeat this call for it: say in your reply which file you needed."  # AD-1361: the next action` | delete the line | `test_the_standing_orders_denial_and_the_sentences_are_pinned` |
| RF-4 | `tools.py` | the `# AD-1361 (AD-1344 rule): write_file names the next action` line | `return ToolResult(error=refused)` | `test_write_refusals_name_the_next_action[write_file-constitution_write_refusal]` |
| RF-5 | `tools.py` | the `write_file refused: {refused}. {_WRITE_REFUSAL_NEXT}` line | `return ToolResult(error=f"write_file refused: {refused}")` | `...[write_file-captain_document_write_refusal]` |
| RF-6 | `tools.py` | the `# AD-1361 (BF-911 rule): write_file names the next action` line | `return ToolResult(error=refused)` | `...[write_file-protected_write_refusal]` |
| RF-7 | `tools.py` | the `# AD-1361 (AD-1344 rule): edit_file names the next action` line | `return ToolResult(error=refused)` | `...[edit_file-constitution_write_refusal]` |
| RF-8 | `tools.py` | the `edit_file refused: {refused}. {_WRITE_REFUSAL_NEXT}` line | `return ToolResult(error=f"edit_file refused: {refused}")` | `...[edit_file-captain_document_write_refusal]` |
| RF-9 | `tools.py` | the `# AD-1361 (BF-911 rule): edit_file names the next action` line | `return ToolResult(error=refused)` | `...[edit_file-protected_write_refusal]` |
| RF-10 | `tools.py` | `"Do not repeat this call with the same path: read another file, and use list_files to see which files you can read."` | `list_files` → `list_dir` | `test_read_and_list_refusals_name_the_next_action[read_file]`, `test_the_standing_orders_denial_and_the_sentences_are_pinned` |

**Campaign of record.** Run an unmutated baseline of both new files first. Then run each row against the file that holds its killer. Record the base tree and the sha256 of `tools.py` and `result_offload.py`. A Builder whose files match does not repeat it.

## 11. Recorded limits

- **L1.** A recovery re-read and a workspace-artifact slice carry no note. Their text is held to the per-read bound, and the frame that promised them named the whole.
- **L2.** An offloaded fresh slice shows its frame, which says `of N`, not the "More follows" sentence. The frame's worked call names the next read.
- **L3.** `codebase_read_source` carries no note on either path. It needs its own 1-based sentence.
- **L4.** Lines are counted by `str.splitlines`, so `\x0c`, `\x1c`-`\x1e`, `\x85`, `\u2028` and `\u2029` count as breaks. This matches what `offset` selects.
- **L5.** On the plain path the note is part of the text, so it counts against AD-1148's cap and, under a delivery run, against the threshold (at most about 200 characters).
- **L6.** The run's `tool_results[*].output` holds the note for a plain read and a verified legacy read, but not for an offloaded one. It reaches the AD-1151 trace, and BF-947 carried results for the plain path only.
- **L7.** The `read_file` refusal names `list_files` without checking the agent's offer. A per-agent override that removes `list_files` alone would make it name a tool the agent lacks. Plan mode withholds both.
- **L8.** `codebase_read_source` answers a read-policy refusal as `codebase_read_source failed:` (`tools.py:852`, `:880`). This predates AD-1361; BF-948 marked `read_file` and `list_files` only.
- **L9.** The AD-1344 and BF-911 refusals stay unmarked, so the detectors count them. This predates AD-1361 and is not changed here.
- **L10.** At a tiny AD-1148 cap the trailing note can be cut.
- **L11.** The Copilot adapter's own `_STANDING_ORDERS_DENIED` (`copilot_adapter.py:76`) is not updated (another family).
- **L12.** `codebase_index unavailable on runtime` (four tools) names no next action. It reports the tool's own state, not a rule's refusal, and is a candidate for a later family.

## 12. Verified Against Codebase (2026-11-18, on `9f43697f`)

```
git rev-parse HEAD -> 9f43697fd8433071dd0f0afc394fba06de905a0c
scripts/ad_ceiling.py -> CEILING AD-1360 (issue titles), NEXT AD-1361
Read src/probos/cognitive/swe_harness/tools.py :1-80, :255-519, :556-653, :806-1009, :1050-1110, :1192-1206,
  :1280-1521; grep "error=|_REFUSAL|_DENIED|refused" (census, section 3); grep "^class |^def " (class bounds)
  264-278 SourceToolResult/InstructionSourceToolResult; 288-291 RecoveryFailureToolResult; 334-380
  _verified_source_result (364 lines, 365 whole, 366-367 indices, 372 len(lines) into SourceRef); 383-397
  _workspace_slice_result; 411-413 section header; 470-472 read refusal; 482-494 verified dispatch and plain path;
  515-518 _LIST_FILES_PATTERN_REFUSAL; 618-621 list refusal; 896-902 standing-orders constants; 1097-1108 and
  1194-1205 write rules; 1399-1404 run_command refusal; 1468-1510 read_perms shared by read_file and list_files
Read src/probos/cognitive/swe_harness/result_offload.py :35-79, :296-353, :500-552, :560-700
  40-43 tools import; 521-528 _workspace_frame; 531-552 _source_frame (532-541 count, 546 header); 615-626 recovery
  (621 bound); 627-628 legacy branch; 640-647 source branch (646 reserve); 674-700 delivery_trace
Read src/probos/execution/workspace_results.py :1-250, :290-330 (147 outline chars == source_chars; 173-201 SourceRef;
  294-299 WorkspaceSlice)
Read src/probos/execution/workspace_result_store.py :858-897 (893-897 char slice and indices)
Read src/probos/cognitive/swe_harness/tool_call.py :64-71 llm_function_name; :805-911 CapturedConversion, result,
  legacy_result, capture, with_result_delivery
Read src/probos/cognitive/swe_harness/agentic_loop.py :125-126 head/tail, :178-183, :210-249 truncate_tool_output,
  :867-907 format_tool_result_content, :1209-1240 _open_delivery_run
Read src/probos/agents/utility/web_agents.py :110-169 (BF-889 section headers)
Read src/probos/cognitive/agentic_dispatch.py :180-212, :250-337, :2340-2380, :3012-3036, :4505-4599
Read src/probos/tools/protocol.py :60-115 (marks, is_caller_input_error), :196-221 refuse_undeclared_params
Read src/probos/security/file_access.py :340-391, :417-441, :552-581; src/probos/cognitive/builder_paths.py
  :137-166, :243-269; src/probos/execution/command_gate.py :81-92, :372-387; execution/command_escalation.py :58-85
Read src/probos/cognitive/decomposer.py :51-69 (_CAPABILITY_GAP_RE); cognitive/agent_mode.py :60-83
Read src/probos/agent_work_runner.py :115-160 (CarriedResults)
Read scripts/gen_ad_ledger.py :113-139; scripts/check_architecture_principles.py :187-188 (SRP 500 lines, 15 methods)
Read tests/test_ad1240_tool_result_delivery.py :69-76, :150-191, :676-766, :1290-1322, :1407-1424, :1518-1606,
  :1690-1719, :1866-1872, :2128-2170, :2622-2643, :2756-2800, :3395-3416, :3780-3819, :5255-5283
Read tests/test_ad1200_repository_instruction_wire.py :91-101, :128-134, :488-517
Read tests/test_bf948_list_files_read_policy.py :1-140, :168-179, :322-335; tests/test_bf953_read_floor_spellings.py
  :64-71, :272-297, :562-566, :793-798; tests/test_bf911_protected_config_write_refusal.py :664-687;
  tests/test_bf910_standing_orders_lookup.py :285-302; tests/test_ad544_native_tools.py :29-40, :125-161;
  tests/test_ad1347_s3_execution.py :284-289; prompts/bf-972-975-search-threads-and-running-code.md :650-678
Read prompts/review-criteria.md :1-80; docs/research/clark-extended-mind-absorption.md :54-75;
  gibson-affordances-absorption.md :18-80 (grep); primacy-of-perception-absorption.md :23-33 (grep)
Read PROGRESS.md :1-6; DECISIONS.md :1-12, grep "^### " (BF-946 heading at :1947)
git show f31afa56:src/probos/cognitive/swe_harness/tools.py lines 375-395, 476-495, 856-876 (the issue's anchors)
```

## Absence Verified (2026-11-18, on `9f43697f`)

```
A1 CLAIM: nothing parses a source frame's header or a read_file result's text.
   RUN:   Grep "original source v1|observed lines|workspace result v1" over src and tests; Grep "_source_frame|
          No copy was written|Ordinary zero-based" over tests
   FOUND: result_offload.py:523, :545, :546 only; tests: none (test_bf869 "single source frame" is a camera frame)
   HOLDS: yes
A2 CLAIM: a source or artifact promise is reserved only by the offload branch, after its frame was built.
   RUN:   Grep "\.reserve\(|\.reserve_workspace\(" over src
   FOUND: result_offload.py:646, :668; crew_session.py:3718 and fault_detection.py:568 (other objects)
   HOLDS: yes
A3 CLAIM: no src code reads SourceRef.total_lines beyond its validation.
   RUN:   Grep "total_lines|\.source_reference|workspace_slice\b" over src
   FOUND: workspace_results.py:183, :194, :196; architect.py:353-372 (a local variable); result_offload.py:625, :641
          (the reference object, not the field)
   HOLDS: yes
A4 CLAIM: no name this contract adds exists yet.
   RUN:   Grep "slice_note|_READ_REFUSAL_NEXT|_LIST_REFUSAL_NEXT|_WRITE_REFUSAL_NEXT|_READ_FILE_SLICE|test_ad1361|AD-1361"
          over the repository (excluding .adq/)
   FOUND: none
   HOLDS: yes
A5 CLAIM: no runtime code or test loads prompts/review-criteria.md.
   RUN:   Grep "review-criteria|review_criteria|Build Prompt Review Criteria" over the repository; Grep "review-criteria"
          in .claude/agents/claude-architect.md; git ls-files .claude .github/agents src/probos/crew* config | grep review
   FOUND: scripts/wave-orchestrator.ps1:495 (instruction text), .claude/agents/claude-architect.md:99, prompts archives
          and reviews; no src, no tests
   HOLDS: yes
A6 CLAIM: exact pins of read_file/list_files refusal texts are only in bf948 and bf953 (and bf910 via the constant).
   RUN:   Grep "read_file refused|list_files refused|_STANDING_ORDERS_DENIED|not readable on this vessel|write_file refused|
          edit_file refused" over tests
   FOUND: bf948 :41, :42, :44, :120, :177, :261, :265-267, :305, :332; bf953 :68, :69, :566, :798; bf910 :299, :736, :772,
          :785, :850 (constant), :1179-1244 (copilot_adapter's constant)
   HOLDS: yes
A7 CLAIM: the only exact pin of a write refusal returned by WriteFileTool/EditFileTool is bf911:685.
   RUN:   Grep "== (protected|constitution|captain_document)_write_refusal\(" and "\[refusal, refusal\]|error == refus"
          over tests; Grep "\.error" in bf911, bf943, ad1344
   FOUND: bf911:685; the rest are containment (_AD in, _BF in) or startswith (test_search_threads_and_running_code:478)
   HOLDS: yes
A8 CLAIM: the fresh sliced read_file results pinned in tests are test_ad1240 :1318, :1605, :2149-2150, :3412 and
          test_ad1200 :504, :508.
   RUN:   Grep "\"offset\":|\"limit\":|\"start_line\":|\"end_line\":" over tests (count, then content in the delivery files);
          Grep "read_file.*\b(offset|limit)=" over tests
   FOUND: test_ad1240 :1298-1301 (parity), :1395, :1414, :1528, :1568, :1709, :1916-1917, :2142, :2767-2769, :3799,
          :4648, :5207 (recovery or workspace reads, unchanged), :1603, :2149-2150, :2633 (a codebase_read_source promise,
          then recovery), :3405, :5271 (workspace fresh route, unchanged); test_ad1200 :498; bf946 :129 (worked = recovery)
   HOLDS: yes for these; test files that pass offsets through variables elsewhere were not read one by one (broad gate)
A9 CLAIM: none of #1722 S3's refusals is in tools.py.
   RUN:   Grep "error=|_REFUSAL\b|_DENIED\b|refused" over tools.py (the census)
   FOUND: no CONFINED_CALL_* or UNREGISTERED_TOOL_REFUSAL; they are at agentic_dispatch.py:307-325
   HOLDS: yes
```

**Not verified (the orchestrator measures):** the focused counts of the existing files; U5's AST count (my census is by grep, read site by site); T4's 64-line arithmetic (92-character lines, 6,000 allowance) against the live `_source_frame`; that no test in `test_ad1240` asserts a source frame's exact length at a tight bound; the 66 test files that check strings against `_CAPABILITY_GAP_RE` were not read one by one; `asyncio_mode` (the new files mark every async test explicitly).

## 13. Prior Art and Blind Spots

- **Internal.**
  - BF-889's `read_page` section headers (`web_agents.py:128-152`): copied, with the unit changed to lines.
  - BF-946's per-read bound and retry text: kept, which is why recovery reads get no note.
  - The AD-1240 frames: the workspace outline already states `chars`.
  - BF-948's refusal mark: kept.
  - The AD-1154 and AD-1328 refusal voice ("Do not repeat ...; ... report ..."): adopted.
  - BF-719 (`tests/test_bf719_sandbox_names_the_alternative.py`): the same idea for the sandbox.
  - `UNREGISTERED_TOOL_REFUSAL`: Gibson note `:74`. It names `search_capabilities` unconditionally; that is the cautionary case behind U4.
  - The source notes: Merleau-Ponty item 1, Gibson item 3, Clark item 3.
- **External.** Date used: 2026-11-18.
  - Anthropic, "Writing effective tools for agents": "prompt-engineer your error responses to clearly communicate specific and actionable improvements" and "If you choose to truncate responses, be sure to steer agents with helpful instructions." Adopted: the note says how to read on, and each refusal names an action. ([anthropic.com/engineering/writing-tools-for-agents](https://www.anthropic.com/engineering/writing-tools-for-agents))
  - SWE-agent (not overdue; checked). Its ACI page says the viewer "works best when displaying just 100 lines in each turn". It does not say whether the viewer states a total; third-party summaries say it does, but that is not verified. Nothing adopted beyond BF-946. ([swe-agent.com ACI](https://swe-agent.com/latest/background/aci/))
  - Claude Code's file-read error names the limit and asks for `offset`/`limit` (cited in BF-946, anthropics/claude-code#19085): the same shape as the read refusal.
  - Considered, deferred (overdue on this date, not relevant): MCP Apps, AG-UI, RAGFlow, LoCoMo.
- **Blind spots found.**
  1. The live path is the verified one, which the issue does not name. A note in its text would break AD-1240 (§1.3).
  2. The issue's workspace-slice premise is half wrong: the frame already states the whole.
  3. Refusal texts are machine-read by prefix (`is_caller_input_error`) and by identity (the detectors). Appending keeps both.
  4. A refusal sentence the model echoes could trip capability-gap triage; U4 guards this.
  5. `codebase_read_source` labels a policy refusal "failed" (L8).
  6. A second copy of the standing-orders denial exists (L11).
- **Row update for `docs/research/reference-projects.md`** (the orchestrator applies it): SWE-agent: ``2026-11-18 | checked | AD-1361 (#1743) Prior Art, `prompts/ad-1361-tool-results-state-the-whole-and-refusals-name-the-next-action.md` (the ACI page states the 100-line window, not whether the viewer gives a total); BF-946 (#1723) Prior Art; AD-360 builder guardrails``

## 14. Diff Reviewer: properties to verify

1. On the verified path, `SourceToolResult.output` and `InstructionSourceToolResult.output` are byte-identical to the base for every read. `slice_note` is non-empty only when `note_slice` is true, the read is not a recovery, and the read is not whole. **Consumer:** `_prepare_result`.
2. `_prepare_result` appends the note only in the legacy branch, after the threshold was measured on the slice. The recovery branch, the bound check, `canonical_capture`, `_source_frame`'s count and `ResultDelivery` are unchanged apart from the frame header's ` of N`. **Consumer:** the loop's `format_tool_result_content` and BF-946's continuation.
3. On the plain path, the note describes the range `lines[start:end]` actually returned, by `slice.indices`. A whole read (no `offset`, no `limit`) is byte-identical. **Consumer:** the model, through AD-1148.
4. Each changed refusal keeps its prefix byte-for-byte and appends `". " + one fixed sentence`. `is_caller_input_error` answers as before for each, and two identical refusals stay identical. **Consumers:** `fault_report.detect_tool_defect` and `fault_detection.collect_tool_fault_batch`.
5. No sentence or note matches `_CAPABILITY_GAP_RE`. The only tool named is `list_files`.
6. No method is added to any class, and no config field, `EventType`, persisted key or schema change is made.
7. Every new or rewritten comment, docstring, test docstring and tracker line is true of the head.
8. T3 starts at the model's call and ends at the next request's message, and T4 starts at the tool and ends at the frame.
9. M3's diff is one bullet in `prompts/review-criteria.md` §8 and nothing else. **Consumer:** the reviewer agents that read the file.

## 15. Acceptance criteria

1. T1 to T5 pass: a sliced `read_file` states the whole on both paths. An offloaded slice's frame says `of N` and keeps its line count. A recovery read carries no note.
2. U1 to U5 pass: the nine refusals name the next action, their marks hold, the sentences are gap-free and name only a co-registered tool, and the census holds.
3. The updated pins pass with their inline reasons, and the left pins pass unchanged.
4. G1 to G4 pass, every §10 mutant is killed, and the broad gate's receipt is green.
5. `prompts/review-criteria.md` §8 holds the parity bullet in its own commit.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Register note

- **AD-1346 register.** No new store-write, egress or subprocess site, so no row. The longer texts reach the existing AD-1151 trace write (attachment store) and the in-process BF-947 carried results.
- **AD ledger.** One new entry, AD-1361. Item 6 adds none.
- **#1743** stays OPEN with items 3, 4, 5 and 7 and item 2's remaining families. Its title and the ledger heads carry no lifecycle keyword.
