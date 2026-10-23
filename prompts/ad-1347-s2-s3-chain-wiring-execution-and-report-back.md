# AD-1347 S2 and S3: the chain's agent-work tags, and the Ship's Computer runs, parks, resumes and reports agent-created work (closes #1627)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23

**Status:** build-ready after wave 2 (BF-917 #1625, BF-915 #1623) merges. Slices 2 and 3 of 4 of #1627, built as one batch (the Architect's queue ruling, comment `IC_kwDORgp-xs8AAAABer-scw`). **S3 closes AD-1347.** **Tier HIGH:** crew create governed work through the chain; colleagues run it with tools; there is a Captain approval path. **AD number:** AD-1347; this batch allocates nothing (the orchestrator runs `scripts/ad_ceiling.py`). **Base:** `origin/main` `6b950acf` (S1 and S4 merged).

**Wave 2:** this contract needs nothing from wave 2 and edits none of its files: `skill_framework.py`, `acm.py`, `crew_enrollment.py`, `config/ontology/skills.yaml`, the doctor checks, `role_template_audit.py`, `storage_declarations.py` and its four test files. Every code SEARCH anchors on text. Each tracker SEARCH anchors on a line that wave 2's entries do not change (§8).

**Tests:**
- M1: `tests/test_ad1347_s2_chain_tags.py`, 13 functions.
- M2: `tests/test_ad1347_s3_execution.py`, 12 functions; `tests/test_ad1347_s3_wiring.py`, 1 function (a real boot).
- Updated pins:
  - `tests/fixtures/ad1343_seam_registry.py`: one `AGENTIC_RUN_OWNERS` row and the `agent_work` `SEAM_INDEX` text;
  - `tests/test_ad1156_plan_execute_mode.py`: the `_NEVER_RAN_REFUSALS` set;
  - `tests/test_issue1419_failed_start_rollback.py`: one stopped component;
  - `tests/test_ad1347_s1_agent_work.py`: two docstring sentences;
  - `tests/test_bf237_pipeline_post_budget.py` and `tests/test_bf238_post_budget_telemetry.py`: the extractor stub in each takes the two new keywords (§7.3a, §7.3b; M1).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks here are LF; match and write with each file's own endings. New files are written LF.

**Mechanical repairs by the orchestrator (2026-10-23; six, found by applying the contract by tool on `6b950acf` and `ba20e949`, running its tests and its mutation table, and building M1; no decision changed, and the production code needed none).** (1) `tests/test_ad1347_s3_execution.py` imported `AgentWorkConfig` from `probos.agent_work`, which does not export it (S1 defines it in `probos.config`, and S1's own tests import it there): the import moves. (2) C9's first case used the thread id `"bad thread"`, which S1's `AgentWorkOrigin` accepts (it refuses only a non-str, an id over 128 characters, an id with surrounding whitespace and an id that does not encode as UTF-8), so the tag was filed: the case is `" t1"`, an id with surrounding whitespace. (3) X3's `restricted_before_run` case issued its restriction at `ToolPermission.READ`, which restricts nothing at read level (S1's tests restrict with `ToolPermission.NONE`): it is `NONE`. (4) W3's boot config left the Ward Room off, and finalize wires AD-855's driver only inside `if runtime.ward_room:`, so the premise assertion failed: the test now builds its config through a local `_config` that sets `ward_room.enabled = True`, the change §7.21's note had told the Builder to make. After the four, all 41 test cases pass on the contract applied by tool. (5) Found by the campaign: row R11 (`if outcome == OUTCOME_EXPIRED:` to `if False:`) survived, because X5 asserted only that the notice contains "expired", and the fallback text ("ended as expired without a result") contains it too: X5 now asserts the expired wording itself. (Row SD1's killer is `tests/test_issue1419_failed_start_rollback.py`: its campaign command names that file as well.) The mutation table has 53 rows; the heading said 44. (6) Found by the M1 Builder: two existing test stubs of the extractor, `_fake_extract` in `tests/test_bf237_pipeline_post_budget.py` and in `tests/test_bf238_post_budget_telemetry.py`, have the fixed signature `(agent, text, *, post_budget=None)`, so the pipeline's new `thread_id` and `post_id` keywords raised `TypeError` in four bf237 tests (bf238's stub fails the same way): §7.3a and §7.3b give each stub the two keywords. §5's row and AV5's claim that no test fakes the extractor's kwargs were wrong (AV5 searched only for `def extract_and_execute_actions`) and are corrected; M1's focused command now names the bf238 test. **Re-verified on `origin/main` `ba20e949` (wave 2 merged):** all 37 code pairs and both tracker pairs apply, each SEARCH exactly once; the 41 test cases pass on the contract applied by tool; the table's rows are run on that tree and recorded in §17. The phantom precheck lists 21 candidates on the base tree `6b950acf` and 8 on the tree with this contract applied, each explained: the 13 `kwarg_mismatch` (base tree only) are the `thread_id` and `post_id` parameters this contract adds to the extractor; 5 `method_phantom` (`restrict_to_plan_mode` and `confine_calls` exist on `DispatchToolExecutor`, where the precheck typed `executor` as `WorkItemAgenticExecutor`; `mark_fulfilled` exists on the capability-request store, where it typed `store` as `WorkItemStore`); 1 `field_phantom` (`origin.id` is a Ward Room thread's id, where the precheck typed `origin` as `AgentWorkOrigin`); and two stdlib classes (`AssertionError`, `SimpleNamespace`).

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| Ward Room replies (threads and Ward Room DM channels) reach the proactive action extractor | present | `ward_room_pipeline.py:288-296` calls `extract_and_execute_actions`; `cognitive_agent.py:7284-7314` posts every Ward Room response through `process_and_post` with `thread_id`, `post_id` |
| The extractor knows no thread | present | `proactive.py:3010-3014` (signature), `:2859-2865` (public wrapper), `:1474` (proactive caller) |
| Existing tags are rank-gated, Lieutenant and above for work-starting actions | present | `proactive.py:3021-3024`; `[ASSIGN]` `:3675-3715`; `[CREW]` `:3717-3769` |
| BF-203's catch-all strips any remaining `[UPPERCASE ...]` opener but not a closer | present | `proactive.py:3807-3813` |
| The chain teaches tags through the compose step's system prompt | present | `cognitive/sub_tasks/compose.py:657-660` (one builder call for every mode), `:585-589` |
| The Captain's one-to-one chat runs its own 24-step pipeline and does not call the extractor | present | `cognitive/dm/reply_pipeline.py:484-509`, `:397-437` (plan-mode tables), `:1240-1316` (DMs and notebooks only) |
| A claimed request is not executed by anything | present | `workforce.py:11403` (`_publish_assignment` skips the dispatcher when `agent_pull`); `tools/work_item_pull_tool.py:314-324` ("owned=True confirms ... ownership ... not execution"); Absence AV1 |
| A claimed `task` is `scheduled`, which the task type cannot leave by `transition_work_item`; the booking moves it | present | `workforce.py:11316-11318` (status `scheduled`), `:181-200` (task transitions), `:11568-11594` (`start_booking` sets `in_progress`) |
| The AD-839 dispatch path frames a work item as from the Captain and runs the full offer | present | `cognitive_agent.py:2148-2194`, `:2405-2416` |
| A read-only allowlist enforced at the call, before any parking | present | `agentic_dispatch.py:750-761`, `:3451-3453`; `cognitive/agent_mode.py:68-83` |
| AD-1154 files `action` requests for the browser only; an ordinary approved action has no fulfiller and emits no FULFILLED | present | `agentic_dispatch.py:225`, `:1074-1249`; `routers/capability_requests.py:248-257`, `:486-499` |
| AD-855 parks and resumes, and denial cancels; the denial reason is written after the cancel | present | `cognitive/capability_gap_driver.py:135-188`, `:291-340` (resume through the router or a promoted turn), `:383-413` |
| Every new agentic run is refused for a stopped agent at the run entry | present | `agentic_dispatch.py:2622-2623`; `agent_stop.py:602-611` |
| AD-1343 S2 (ending a running turn) is not built | absent | `agent_stop.py:91-98` (`does_not_end`); Absence AV2 |

## 1. Problem

S1 can create agent work, but nothing in the chain calls it, and nothing runs, parks, resumes or reports an item once it exists. The crew still ask the Captain for reads (#1627's live evidence, 2026-10-22).

## 2. Solution overview

- **M1 (S2):**
  - One parser module reads four tags from any chain reply that reaches the action extractor, and acts on them for Lieutenant rank and above.
  - The Ward Room pipeline passes the thread and post the reply answers.
  - The compose step teaches the tags only while the service exists.
  - Each tag is acknowledged in the agent's own reply.
- **M2 (S3):**
  - A Ship's Computer runner announces each request to its eligible members, and claims through the tool sink.
  - It runs each item in its assignee's agentic loop under a per-call confinement: read-only tools run, and every other call is filed for the Captain's approval.
  - It parks the item on that request (AD-855), resumes it on approval and consumes each approval once. A denial ends the item with the Captain's reason.
  - It returns an item whose claimant may not run it to the board, unclaimed.
  - It reports the result, a decline, an expiry or a denial once per requester and watcher, in the origin thread.

## 3. Decisions

**D1 (parser home and callers).** New core module `probos/agent_work_tags.py`, called from `ProactiveCognitiveLoop._extract_and_execute_actions` only, just before BF-203's catch-all.
- Each tag has a closed form, so it is fully stripped before that catch-all runs.
- Both chain paths reach the extractor: a proactive thought directly, and every Ward Room reply through the pipeline.
- The extractor and its public wrapper gain two keyword arguments, `thread_id` and `post_id`, defaulting to "", which the pipeline passes.
- The origin channel is `ward_room` when a thread is known and `proactive` otherwise. The value `dm` in `ORIGIN_CHANNELS` stays reserved for the Captain's one-to-one chat, which is not wired (register R5).
- Ranked:
  - **A** (chosen): as above.
  - **B** a step in each caller.
  - **C** in `ward_room_router`.
  - **D** also the `DmReplyPipeline` (rejected; see the decisions summary).

**D2 (grammar, rank and acknowledgement).** The grammar is in the module docstring (§7.1).
- Rank: Lieutenant and above, as AD-654d's `[ASSIGN]` and AD-868's `[CREW]`. An ensign's tags are stripped and nothing is done.
- At most 3 tags are acted on per reply.
- `Assignee: @callsign` resolves through `CallsignRegistry.resolve`. An unresolved callsign is passed as written, and the service refuses it (`assignee_unknown`).
- A `ValueError` from `AgentWorkOrigin` is a refused tag, as S1 asked (S1 status, F2/F3).
- The acknowledgement is a parenthesised line, `(Ship's Computer: ...)`, appended to the agent's own reply text. It has no brackets, so BF-203 leaves it alone, and it starts no routing of its own.
- Disclosed: if BF-237 suppresses the main post because a `[REPLY]` was posted, the acknowledgement is not posted. The item exists either way and its report names it.

**D3 (how an item runs).** `AgentWorkRunner` in `probos/agent_work_runner.py`, built in finalize only while `runtime.agent_work` is the real service. One listener on the work store's events:
- a created self-task or chief assignment starts a run;
- a created request is announced;
- a claimed request starts a run;
- an item reaching done, failed or cancelled has its live bookings closed and its notices delivered.

A claim through the chain also starts the run directly, and the runner holds each item to one run at a time. `recover` restarts every assigned, unfinished, unparked item at start.

Each run calls `WorkItemAgenticExecutor.run` without `admitted_turn`, so the run entry refuses a stopped agent at `agentic_run`. The task text frames the work as a colleague's request, not the Captain's.

Before a request runs, `AgentWorkService.execution_allowed` asks the claim gate's question again (S1's hand-on, A3).
- If the claimant may not run it, the request is unassigned: its booking is cancelled and its status is open again.
- After the run the question is asked once more. A claimant stopped mid-run, or one that lost the tool, also releases the request, because AD-1343 S2 is not built (blind spot 7).
- A self-task or assignment whose assignee may not run it is left for its TTL.

Ranked:
- **A** (chosen): push through the store's events, plus a direct start and recovery.
- **B** the AD-839 `_handle_work_item_dispatch`.
- **C** pull only.

**D4 (read-only, enforced at the call).** `ToolCallConfinement(tool_ids, gate)` is a new frozen dataclass in `agentic_dispatch.py`, armed per run with `DispatchToolExecutor.confine_calls`.
- It is checked first in `_DispatchGuardMixin._invoke_reserved_body`, before plan mode and before AD-1154's browser inbox.
- A call to a tool in `AGENT_WORK_READ_TOOL_IDS` runs as usual. That set is the plan-mode read set without the three tools that leave the ship (web_search, read_page, http_fetch) and without discover_work_items.
- Any other call goes to the gate, which answers `admit`, `filed` or `refused`.
- A gate fault refuses. The two refusal texts are never-ran outcomes, classified `permission_denied` and kept out of defect evidence.
- The offer is unchanged: the agent can name any tool it holds, and only read-only calls run unasked.
- Confinement and plan mode are mutually exclusive (`tool_call_confinement_invalid`).

Ranked:
- **A** (chosen): as above.
- **B** narrow the offer (the approval path would be dead).
- **C** widen the AD-1154 browser inbox.

**D5 (approval, park and resume; no new request kind).** The gate files a call through `CapabilityRequestStore.file_action_request` with:
- `tool_id` = the called tool;
- action `agent_work_call`;
- `params` = the call's parameters;
- `scope_key` = `agent_work:<item id>`;
- `work_item_id` = the item.

It checks the AD-1154 pending cap first (`approval_inbox.max_pending_per_agent`), and dedup is AD-1154's own. After the run, the item parks on the first request it filed (`block_on_request`).

**Approval** is its own fulfilment: a new branch in `_maybe_fulfil_on_approval` marks the request fulfilled.
- FULFILLED makes AD-855 resume the item. `_resume` hands an agent-work item to `resume_agent_work`, never to the router.
- The resumed run admits exactly the approved call (same agent, item, tool and parameters) once, consuming the approval on a claim-once `agent_work_notices` row (kind `approval_use:<request id>`), so a restart cannot replay it.
- A repeat of the call is filed again.

**Denial:** AD-855 cancels the item. The report reads the Captain's reason from the denied request, because AD-855 writes `denial_reason` only after the cancel.

**D6 (reports and notices).** Every post is authored `system`, callsign "Ship's Computer"; its text names who did what.
- **Activation notice:** a thread in the request's department channel. It @mentions each eligible member not yet told (claim-once kind `activation`), excludes the requester, and sets `max_responders` to the number mentioned, so routing reaches only those members (`ward_room_router.py:497-502`; mentions are targeted first at `:1007-1012`). It gives the claim and decline syntax and the TTL.
- **Report, decline relay, expiry and denial:** one post in the origin thread. If there is no thread, or the post fails, a new thread in the department channel of the work.
- The post @mentions the requester and every watcher newly told: each terminal notice is claimed before it is sent (S1's `claim_notice`), under one delivery lock.
- **Report content:** the executor's answer (up to 1,500 characters), the tools that answered, the work item id under which AD-1224's tool records are filed, and the trace reference. It ends with the echo-chamber rule: "This is a colleague's report: check it against the record before you rely on it."
- The answer is stored on the item (`metadata["agent_work_result"]`) when it is marked done. If the TTL ended the item mid-run, the answer is written to the ended item (register R3).

**D7 (stop and census).** No new seam:
- creation is `agent_work` (S1);
- a claim is `tool` (through `ToolRegistry.check_and_invoke`);
- a run is `agentic_run` (the run entry);
- candidate questions use `standing_stop` inside the service's existing `_stopped_now`.

Pinned rows:
- `AGENTIC_RUN_OWNERS` gains `("src/probos/startup/finalize.py", "_wire_agent_work_runner")`;
- the `agent_work` `SEAM_INDEX` text names the run;
- `agent_stop.S1_SCOPE["refuses"]` names agent-created work, now that it is reachable (S1 D6 deferred this to S2).

AD-1346: a run of agent work becomes an admission subject when M3 wires `decide` at the run entry; nothing is built here.

**D8 (milestones).** Two (§6). M1 alone files items that nothing yet runs, which is why the batch is one candidate.

## 4. Wave 2 and the rest of the queue

| Item | Its files (from its issue) | Overlap with this contract |
|---|---|---|
| Wave 2 (BF-917, BF-915) | `skill_framework.py`, `acm.py`, `crew_enrollment.py`, `config/ontology/skills.yaml`, doctor checks, `role_template_audit.py`, `storage_declarations.py`, four test files | none |
| BF-914 (#1621) | `channels/*`, `api.py`, `config_models/experience.py`, `doctor/checks/channel_discord_check.py` | none |
| BF-918 (#1626) | `audio/tts/*`, `routers/avatars.py`, `avatars/rhubarb_backend.py`, `attachments/*` | none |
| AD-1341 S2 to S6 (#1569) | `knowledge/archive_store.py`, `knowledge/records_store.py`, `cognitive/oracle_service.py`, `startup/cognitive_services.py`, `__main__.py` | none |

Trackers: the `PROGRESS.md` pair anchors on the title and blank line. The `DECISIONS.md` pair anchors on the heading `### Explicit delegation models, ...`, which none of these items changes.

## 5. Consumers of every value this changes

| Value | Consumer | Accepts it because |
|---|---|---|
| `_extract_and_execute_actions(..., thread_id="", post_id="")` | `extract_and_execute_actions` (wrapper); `ProactiveCognitiveLoop` at `proactive.py:1474`; `WardRoomPostPipeline.process_and_post` | keyword-only, defaulted; two test stubs had the fixed signature `(agent, text, *, post_budget=None)` (`tests/test_bf237_pipeline_post_budget.py:25`, `tests/test_bf238_post_budget_telemetry.py:174`) and now take the two keywords (§7.3a, §7.3b); every other double is an `AsyncMock` |
| `ComposeHandler` system prompt + agent-work block | the compose LLM call | appended only when the runtime holds the real service and the mode is `ward_room_response` or `proactive_observation` |
| `S1_SCOPE["refuses"]` text | stop routes' answers; `tests/test_ad1343_seam_registry.py:63` (phrases of the named exceptions) | only the `refuses` value changes; no phrase checked there is in it |
| `AgentWorkService.crew_member`, `execution_allowed` | `AgentWorkRunner` | new public methods; the service reaches 15 methods (trigger is above 15) |
| `run(..., confinement=None)` | every existing caller | appended after `admitted_turn` (the 21-name prefix pinned by `tests/test_ad1155_loop_until_done.py:508` is unchanged); forwarded only when set (the arguments dict pinned by AD-1239 is unchanged) |
| `_NEVER_RAN_REFUSALS` (+2), `classify_tool_fault_error` tuple (+2) | AD-1189/1257 defect evidence; AD-1205 fault classification | both new texts are emitted only under a confinement |
| `metadata["capability_request_id"]` on an agent-work item | AD-855 resume and cancel (compare and set); `_approved_admission`; `_denial_reason` | written only by `block_on_request` |
| `agent_work_call` `action` requests | `_maybe_fulfil_on_approval` (new branch); HXI card (generic `action`) | AD-1154's exact six-key payload |
| `metadata["agent_work_result"]` | report text; the board (`to_dict`) | not a reserved key; written with the done status in one write |
| `agent_work_notices` kinds `activation`, `decline`, `approval_use:<id>` | `list_due_work_notices` filters by kind `terminal` | other kinds never appear in the terminal query |
| Ward Room posts by `system` | the router (routes like an agent post: mentions first, `max_responders` on the notice thread) | the same author as BF-200 and AD-1343 notices |
| `runtime.agent_work_runner` | `resume_agent_work`, `apply_agent_work_tags`, shutdown | `None` unless finalize built it |

## 6. Milestones and tests

| Milestone | Opens at | Content | Commit |
|---|---|---|---|
| **M1 (S2)** | §7.1 | parser module; extractor and pipeline wiring; compose teaching; `S1_SCOPE`; M1 tests | one |
| **M2 (S3)** | §7.7 | service methods; confinement in the executor; the runner; claim and decline tags; AD-855 resume; approval fulfilment; runtime, finalize, shutdown wiring; census and pinned tests; M2 tests | one |
| Trackers | §8 | — | M2's commit or a docs commit |

**M1, `tests/test_ad1347_s2_chain_tags.py`.** Every test fails on today's tree, at import.

| # | Test | Covers |
|---|---|---|
| C1 | `test_the_parser_reads_each_tag_and_strips_every_marker` (6 cases) | grammar |
| C2 | `test_a_text_without_agent_work_tags_is_returned_unchanged` | off-path equality |
| C3 | `test_a_self_task_tag_in_a_ward_room_reply_files_under_the_agents_slot_with_the_thread_as_origin` | acceptance 6; D1 |
| C4 | `test_a_request_tag_publishes_to_a_department_and_the_chain_request_is_discoverable` | acceptance 6 (placement regression through the chain) |
| C5 | `test_while_off_the_extractor_never_enters_the_agent_work_path` | acceptance 7 |
| C6 | `test_an_ensigns_tags_are_stripped_and_nothing_is_filed` | rank |
| C7 | `test_an_unresolved_or_stopped_requester_is_refused_and_nothing_is_written` (2 cases) | identity fail-closed; acceptance 5 |
| C8 | `test_at_most_three_actions_are_taken_from_one_reply` | cap |
| C9 | `test_an_origin_the_service_cannot_record_is_a_refused_tag` (2 cases) | S1 F2 hand-on |
| C10 | `test_a_second_requester_of_the_same_request_becomes_its_watcher_through_the_chain` | dedup |
| C11 | `test_the_compose_prompt_teaches_the_tags_only_while_agent_work_is_on` (3 modes) | byte-identical golden of the prompt |
| C12 | `test_the_ward_room_pipeline_passes_its_thread_and_post_to_the_extractor` | crosses pipeline, extractor and service |
| C13 | `test_a_chief_assigns_a_member_of_its_department_by_callsign` | assignment by callsign |

**M2, `tests/test_ad1347_s3_execution.py`.**

| # | Test | Covers |
|---|---|---|
| X1 | `test_a_chain_request_is_announced_claimed_run_and_reported_in_its_origin_thread` | **acceptance 2** (the whole seam); acceptance 1's evidence shapes |
| X2 | `test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once` | acceptance 4 (approve, run once, deny with reason) |
| X3 | `test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed` (3 cases) | acceptance 5; blind spot 7 |
| X4 | `test_every_watcher_of_a_deduplicated_request_gets_the_report` | blind spot 6 |
| X5 | `test_an_expired_request_tells_each_recipient_once_across_two_overlapping_deliveries` | TTL notice; concurrency |
| X6 | `test_two_overlapping_starts_run_an_item_once` | concurrency |
| X7 | `test_a_decline_is_recorded_once_and_its_reason_reaches_the_requester` | decline |
| X8 | `test_an_ensign_or_another_department_cannot_claim_through_the_chain` | acceptance 3 (claim half) |
| X9 | `test_the_confinement_gate_decides_every_call_outside_its_set` (4 cases) and `test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome` | D4 |
| X10 | `test_a_full_approval_inbox_refuses_the_call_without_filing_it` | AD-1154 cap |
| X11 | `test_recover_runs_work_a_previous_start_left_unfinished` | restart |
| X12 | `test_an_ordinary_item_still_resumes_through_the_work_item_router` | regression |

**M2, `tests/test_ad1347_s3_wiring.py`:** W3 `test_the_runner_is_wired_only_with_the_service_and_released_at_stop`.

**Concurrency claims, each proved on real stores:**
- two overlapping deliveries tell each recipient once (X5);
- two overlapping starts run once (X6);
- a decline repeats nothing (X7);
- an approval admits one call (X2).

**Stale pins and readers hunted:**
- `tests/test_ad1343_stop_seam_inventory.py`: `AGENTIC_RUN_OWNERS` (updated); `ADMITTED_TURN_SITES`, `STOP_CHECK_SITES`, `STANDING_STOP_SITES` and `DIRECT_TOOL_INVOKES` gain nothing.
- `tests/test_ad1156_plan_execute_mode.py:538-539` (updated).
- `tests/test_issue1419_failed_start_rollback.py:1127-1176`, `:1392-1423` (updated: the new step passes its component).
- `tests/test_ad1155_loop_until_done.py:503-508` and `tests/test_ad1142_crew_child_compaction.py:505-511` (unaffected).
- `tests/test_bf874_dm_callsign_and_fail_closed.py:564-578` (unaffected: no new strip call).
- `tests/test_bf213_proactive_action_vocabulary.py:116-126` (unaffected: the builders are not edited).
- `tests/test_bf688_chain_priority_inheritance.py:51` (no new model call in compose).
- The proactive `read_text` pins (`test_bf156`, `bf163`, `bf164`, `bf257`, `ad590`, `ad591`) assert DM strings this contract does not touch.
- `tests/test_ad1211_approval_fulfils_every_kind.py` and `tests/test_ad1154_approval_inbox.py`: ordinary actions still return `fulfilled: False` (the new branch recognises only `agent_work_call` scoped to its own item).
- `cognitive/dm/reply_pipeline.py` is untouched, so its 24-step guard is too.

**Focused commands:**
- M1: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s2_chain_tags.py tests/test_ad1347_s1_agent_work.py tests/test_ad868_self_originated_crew.py tests/test_ad437_action_space.py tests/test_bf237_pipeline_post_budget.py tests/test_bf238_post_budget_telemetry.py tests/test_ad654a_async_dispatch.py tests/test_bf874_dm_callsign_and_fail_closed.py tests/test_bf213_proactive_action_vocabulary.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_proactive.py -q -n 0 -p no:randomly`
- M2: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s3_execution.py tests/test_ad1347_s3_wiring.py tests/test_ad1347_s1_wiring.py tests/test_ad1347_s2_chain_tags.py tests/test_ad1156_plan_execute_mode.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py tests/test_ad1154_approval_inbox.py tests/test_ad1211_approval_fulfils_every_kind.py tests/test_ad1328_s2c_park_and_scope.py tests/test_ad1187_agent_work_pull.py tests/test_ad1155_loop_until_done.py tests/test_ad1142_crew_child_compaction.py tests/test_ad1239*.py -q -n 0 -p no:randomly`
- Glob `test_ad1239*`, and drop any file that does not exist.

## 7. The contract

### 7.1 New file: `src/probos/agent_work_tags.py` (M1)

```python
"""AD-1347 S2 (#1627): the chain's agent-work action tags, read by one parser for every chain path.

An agent turns a need into durable work from the cognitive chain. The proactive loop's action extractor
(``ProactiveCognitiveLoop._extract_and_execute_actions``) is the one place the tags are acted on: a proactive thought
reaches it directly, and every Ward Room reply (a department or ship thread, or a Ward Room DM channel) reaches it
through ``WardRoomPostPipeline.process_and_post``, which passes the thread and the post the reply answers. The
Captain's one-to-one chat (``cognitive/dm/reply_pipeline.py``) does not read them: work found in a conversation with
the Captain is the Captain's (AD-845, AD-1165), so that path is unchanged.

Grammar (taught only while the service exists, ``agent_work_instructions``)::

    [SELF_TASK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id, optional>
    [/SELF_TASK]

    [REQUEST_WORK]
    Title: <one line>
    Reason: <why it is needed>
    Tool: <tool id>
    Department: <department, optional>
    Assignee: @<callsign, optional>
    [/REQUEST_WORK]

    [CLAIM_WORK <work item id>]
    [DECLINE_WORK <work item id>] <reason> [/DECLINE_WORK]

A line without a key continues the field before it; free text before any key is the item's details. Rank: Lieutenant
and above, as AD-654d's ASSIGN and AD-868's CREW; an ensign's tags are stripped and nothing is done. At most
``MAX_TAGS_PER_REPLY`` tags are acted on in one reply. The requester is the agent's own id, which the service resolves
to its slot and refuses when it cannot (fail closed; never the Captain).

The acknowledgement is a line the Ship's Computer appends to the agent's own reply, in parentheses and without
brackets (BF-203's catch-all would strip a bracketed one). It is posted where the reply is posted, so it starts no
routing of its own and cannot loop.

Off: ``agent_work_service`` answers None, the extractor never calls this module, and nothing is taught.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from probos.agent_work import (
    KIND_ASSIGNMENT,
    KIND_REQUEST,
    MAX_DESCRIPTION_CHARS,
    AgentWorkCreated,
    AgentWorkOrigin,
    AgentWorkRefusal,
    AgentWorkService,
    read_agent_work,
)
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)

ACTION_SELF_TASK: Final = "self_task"
ACTION_REQUEST: Final = "request"
ACTION_CLAIM: Final = "claim"
ACTION_DECLINE: Final = "decline"
MAX_TAGS_PER_REPLY: Final = 3
#: The compose modes whose replies reach the action extractor (D1); a DM with the Captain does not.
AGENT_WORK_COMPOSE_MODES: Final[frozenset[str]] = frozenset({"ward_room_response", "proactive_observation"})

AGENT_WORK_INSTRUCTIONS: Final = (
    "**Agent work (AD-1347)** -- when your reasoning needs a fact only a ship's tool can read, file it as work "
    "instead of asking the Captain. Place the block after your reply text; Lieutenant rank and above.\n"
    "Work for yourself, run shortly with your own read-only tools:\n"
    "[SELF_TASK]\nTitle: <one line>\nReason: <why it is needed>\nTool: <tool id, optional>\n[/SELF_TASK]\n"
    "A request to the department that holds a tool you do not hold; a chief may name a member of its own "
    "department with Assignee:\n"
    "[REQUEST_WORK]\nTitle: <one line>\nReason: <why you need it>\nTool: <tool id>\n"
    "Department: <department, optional>\nAssignee: @<callsign, optional>\n[/REQUEST_WORK]\n"
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict."
)

_BLOCK_RE: Final = re.compile(
    r"\[(SELF_TASK|REQUEST_WORK)\](.*?)\[/\1\]"
    r"|\[CLAIM_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\]"
    r"|\[DECLINE_WORK[ \t]+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})[ \t]*\](.*?)\[/DECLINE_WORK\]",
    re.DOTALL,
)
_STRAY_RE: Final = re.compile(
    r"\[/?(?:SELF_TASK|REQUEST_WORK|DECLINE_WORK)\]|\[(?:CLAIM_WORK|DECLINE_WORK)\b[^\]\n]{0,160}\]"
)
_FIELD_RE: Final = re.compile(r"^\s*(title|reason|tool|department|assignee|details)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class AgentWorkTag:
    """One tag read from a reply: what it asks, and its fields (empty when not given)."""

    action: str
    title: str = ""
    reason: str = ""
    details: str = ""
    tool_id: str = ""
    department: str = ""
    assignee: str = ""
    work_item_id: str = ""


def _fields(body: str) -> dict[str, str]:
    """``Key: value`` lines; a line without a key continues the field before it (free text first is ``details``)."""
    found: dict[str, list[str]] = {}
    current = "details"
    for line in body.splitlines():
        match = _FIELD_RE.match(line)
        if match is not None:
            current = match.group(1).lower()
            found.setdefault(current, []).append(match.group(2).strip())
        elif line.strip():
            found.setdefault(current, []).append(line.strip())
    return {key: " ".join(part for part in parts if part).strip() for key, parts in found.items()}


def split_agent_work_tags(text: str) -> tuple[str, tuple[AgentWorkTag, ...]]:
    """Every agent-work tag in ``text``, in order, and the text without any of them (stray markers included).

    A text with no tag and no stray marker is returned as it was, whitespace included.
    """
    tags: list[AgentWorkTag] = []
    for match in _BLOCK_RE.finditer(text):
        if match.group(1) is not None:
            fields = _fields(match.group(2))
            tags.append(AgentWorkTag(
                ACTION_SELF_TASK if match.group(1) == "SELF_TASK" else ACTION_REQUEST,
                title=fields.get("title", ""), reason=fields.get("reason", ""), details=fields.get("details", ""),
                tool_id=fields.get("tool", ""), department=fields.get("department", "").lower(),
                assignee=fields.get("assignee", "").lstrip("@").strip(),
            ))
        elif match.group(3) is not None:
            tags.append(AgentWorkTag(ACTION_CLAIM, work_item_id=match.group(3)))
        else:
            tags.append(AgentWorkTag(ACTION_DECLINE, work_item_id=match.group(4), reason=" ".join(match.group(5).split())))
    without = _STRAY_RE.sub("", _BLOCK_RE.sub("", text))
    if not tags and without == text:
        return text, ()
    return without.strip(), tuple(tags)


def agent_work_service(runtime: Any) -> AgentWorkService | None:
    """The runtime's agent-work service when it is the real one, else None (agent_work off, or a test double)."""
    service = getattr(runtime, "agent_work", None)
    return service if type(service) is AgentWorkService else None


def agent_work_instructions(runtime: Any) -> str:
    """The prompt block that teaches the tags, or "" while the service does not exist (the prompt is unchanged)."""
    return AGENT_WORK_INSTRUCTIONS if agent_work_service(runtime) is not None else ""


def _ack(text: str) -> str:
    return f"(Ship's Computer: {text}.)"


def _slot_of(runtime: Any, callsign: str) -> str | None:
    """The slot a callsign names through the callsign registry, else the text itself (the service refuses it)."""
    if not callsign:
        return None
    try:
        resolved = runtime.callsign_registry.resolve(callsign)
    except Exception:
        logger.debug("AD-1347: callsign %s did not resolve; the service judges it as written", callsign, exc_info=True)
        resolved = None
    agent_id = resolved.get("agent_id") if isinstance(resolved, dict) else None
    return agent_id if type(agent_id) is str and agent_id else callsign


def _created_ack(created: AgentWorkCreated, *, actor: str, in_thread: bool) -> str:
    item = created.work_item
    short = item.id[:8]
    record = read_agent_work(item)
    department = record.department if record is not None else "its department"
    where = "in this thread" if in_thread else f"in the {department} channel"
    if created.deduplicated:
        if record is not None and record.requester == actor:
            return _ack(f"you already have open request {short} (\"{item.title}\")")
        return _ack(f"open request {short} (\"{item.title}\") already asks this; you were added as a watcher and get its result too")
    if created.kind == KIND_REQUEST:
        tool = record.tool_id if record is not None else "the tool"
        note = "; a colleague outside your command was named, so it went to the department" if created.converted else ""
        return _ack(f"request {short} (\"{item.title}\") was sent to {department} for {tool}{note}; the result will be posted {where}")
    if created.kind == KIND_ASSIGNMENT:
        return _ack(f"work item {short} (\"{item.title}\") was assigned to {item.assigned_to}; the result will be posted {where}")
    return _ack(f"self-task {short} (\"{item.title}\") is on the board and runs shortly; the result will be posted {where}")


async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
    return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action


async def _apply_one(
    tag: AgentWorkTag, *, service: AgentWorkService, runtime: Any, actor: str,
    origin: AgentWorkOrigin | None, in_thread: bool,
) -> tuple[str, dict[str, Any]]:
    if tag.action in (ACTION_CLAIM, ACTION_DECLINE):
        return await _claim_or_decline(tag, runtime=runtime, actor=actor)
    action: dict[str, Any] = {"type": "agent_work", "action": tag.action}
    if origin is None:
        return (
            _ack("agent work was not filed: this reply's thread could not be recorded as its origin"),
            {**action, "outcome": "refused:invalid_origin"},
        )
    if tag.action == ACTION_SELF_TASK:
        result = await service.create_self_task(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id or None,
        )
    else:
        result = await service.request_work(
            actor, title=tag.title, description=tag.details[:MAX_DESCRIPTION_CHARS], reason=tag.reason,
            origin=origin, tool_id=tag.tool_id,
            assignee=_slot_of(runtime, tag.assignee),
            department=tag.department or None,
        )
    if isinstance(result, AgentWorkRefusal):
        return _ack(f"agent work was not filed: {result.detail or result.code}"), {**action, "outcome": f"refused:{result.code}"}
    outcome = "deduplicated" if result.deduplicated else "created"
    return _created_ack(result, actor=actor, in_thread=in_thread), {**action, "outcome": outcome, "work_item_id": result.work_item.id}


async def apply_agent_work_tags(
    text: str, *, runtime: Any, actor: str, rank: Rank, thread_id: str = "", post_id: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Strip every agent-work tag from a reply, act on each one the agent's rank allows, append the acknowledgements.

    Never raises for a tag: a refusal, an origin that cannot be recorded or an unavailable action is an
    acknowledgement line. The text is returned unchanged when the service does not exist.
    """
    service = agent_work_service(runtime)
    if service is None:
        return text, []
    cleaned, tags = split_agent_work_tags(text)
    if not tags or rank is Rank.ENSIGN:
        return cleaned, []
    try:
        origin: AgentWorkOrigin | None = AgentWorkOrigin("ward_room" if thread_id else "proactive", thread_id=thread_id, post_id=post_id)
    except ValueError:
        origin = None
    acks: list[str] = []
    actions: list[dict[str, Any]] = []
    for index, tag in enumerate(tags):
        if index >= MAX_TAGS_PER_REPLY:
            acks.append(_ack(f"only {MAX_TAGS_PER_REPLY} agent-work actions are taken from one reply; the rest were not"))
            break
        ack, action = await _apply_one(
            tag, service=service, runtime=runtime, actor=actor, origin=origin, in_thread=bool(thread_id),
        )
        acks.append(ack)
        actions.append(action)
    return "\n\n".join(part for part in (cleaned, *acks) if part), actions
```

### 7.2 `src/probos/proactive.py` (M1)

Pair 1 of 3 (the extractor's signature):

SEARCH:
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract structured actions from proactive response and execute them.
```
REPLACE:
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
        thread_id: str = "",
        post_id: str = "",
    ) -> tuple[str, list[dict]]:
        """AD-437: Extract structured actions from proactive response and execute them.

        AD-1347 S2: ``thread_id`` and ``post_id`` name the Ward Room thread and post a reply answers (the Ward Room
        pipeline passes them); a proactive thought has none. Only the agent-work tags read them.
```

Pair 2 of 3 (the public wrapper):

SEARCH:
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a)."""
        return await self._extract_and_execute_actions(agent, text, post_budget=post_budget)
```
REPLACE:
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
        thread_id: str = "",
        post_id: str = "",
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a; AD-1347 S2 adds the thread and post)."""
        return await self._extract_and_execute_actions(agent, text, post_budget=post_budget, thread_id=thread_id, post_id=post_id)
```

Pair 3 of 3 (the tags, before BF-203's catch-all):

SEARCH:
```python
        text = re.sub(handoff_pattern, '', text, flags=re.DOTALL).strip()

        # BF-203: Strip unrecognized bracket command tags that the LLM hallucinated.
```
REPLACE:
```python
        text = re.sub(handoff_pattern, '', text, flags=re.DOTALL).strip()

        # --- Agent-created work (AD-1347 S2) — Lieutenant+; only while the service exists, so off is untouched ---
        # Before BF-203: each tag has a closed form and is stripped whole here.
        from probos.agent_work_tags import agent_work_service, apply_agent_work_tags

        if agent_work_service(rt) is not None:
            text, work_actions = await apply_agent_work_tags(
                text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,
            )
            actions_executed.extend(work_actions)

        # BF-203: Strip unrecognized bracket command tags that the LLM hallucinated.
```

### 7.3 `src/probos/ward_room_pipeline.py` (M1)

SEARCH:
```python
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget,
            )
```
REPLACE:
```python
        if agent and self._proactive_loop:
            # AD-1347 S2: the thread and post this reply answers are the origin of any work it files.
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget, thread_id=thread_id, post_id=post_id or "",
            )
```

### 7.3a `tests/test_bf237_pipeline_post_budget.py` (M1: the extractor stub takes the two new keywords)

SEARCH:
```python
    async def _fake_extract(agent, text, *, post_budget=None):
        if spend_budget and post_budget is not None:
```
REPLACE:
```python
    async def _fake_extract(agent, text, *, post_budget=None, thread_id="", post_id=""):
        if spend_budget and post_budget is not None:
```

### 7.3b `tests/test_bf238_post_budget_telemetry.py` (M1: the extractor stub takes the two new keywords)

SEARCH:
```python
    async def _fake_extract(agent, text, *, post_budget=None):
        if post_budget is not None:
```
REPLACE:
```python
    async def _fake_extract(agent, text, *, post_budget=None, thread_id="", post_id=""):
        if post_budget is not None:
```

### 7.4 `src/probos/cognitive/sub_tasks/compose.py` (M1)

SEARCH:
```python
        # Build prompts
        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )
```
REPLACE:
```python
        # Build prompts
        system_prompt, user_prompt = builder(
            context, prior_results, callsign, department,
        )
        # AD-1347 S2: the agent-work tags, taught only while the Ship's Computer's service exists, so the prompt is
        # byte-identical while agent_work is off. Only the modes whose replies reach the action extractor (D1).
        from probos.agent_work_tags import AGENT_WORK_COMPOSE_MODES, agent_work_instructions

        if mode_key in AGENT_WORK_COMPOSE_MODES:
            agent_work_block = agent_work_instructions(self._runtime)
            if agent_work_block:
                system_prompt += f"\n\n{agent_work_block}"
```

### 7.5 `src/probos/agent_stop.py` (M1: the scope names agent-created work, now reachable)

SEARCH:
```python
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), browser actions and every "
        "tool call, protected effects included."
```
REPLACE:
```python
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), work it would create for itself or ask of a colleague and the run of "
        "agent-created work it holds (AD-1347: a request it claimed goes back to the board), browser actions and every "
        "tool call, protected effects included."
```

### 7.6 New file: `tests/test_ad1347_s2_chain_tags.py` (M1)

```python
"""AD-1347 S2 (#1627): the chain's agent-work tags, against the real service and the real chain paths.

The real ``AgentWorkService`` over a real ``WorkItemStore`` (``_ship`` from ``tests/test_ad1347_s1_agent_work.py``),
the real ``ProactiveCognitiveLoop._extract_and_execute_actions``, the real ``WardRoomPostPipeline`` over a real
``WardRoomService`` (C12) and the real ``ComposeHandler`` (C11). The runtime the loop reads is a ``MagicMock`` with the
``ProbOSRuntime`` spec carrying the real service and a real ``TrustNetwork``, as ``tests/test_ad868_self_originated_crew.py``
builds it. On today's tree every test fails at import: ``probos.agent_work_tags`` is absent.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import probos.agent_work_tags as tags_module
from probos.agent_work import read_agent_work
from probos.agent_work_tags import AGENT_WORK_INSTRUCTIONS, MAX_TAGS_PER_REPLY, AgentWorkTag, split_agent_work_tags
from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.compose import (
    ComposeHandler,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)
from probos.consensus.trust import TrustNetwork
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.types import LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from tests.test_ad1347_s1_agent_work import STOP_REASON, _discovered, _section, _ship

REQUEST = (
    "[REQUEST_WORK]\nTitle: Read the EventLog window\nReason: the thread cannot show what the log holds\n"
    "Tool: event_log_query\n[/REQUEST_WORK]"
)
SELF_TASK = "[SELF_TASK]\nTitle: Check my build log\nReason: the relay drifted twice\n[/SELF_TASK]"


def _loop_runtime(service: Any, trust: TrustNetwork) -> Any:
    """The runtime the extractor reads, as tests/test_ad868_self_originated_crew.py builds it, with ``agent_work``."""
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock()
    runtime.trust_network = trust
    runtime.ward_room_router = MagicMock(spec=WardRoomRouter)
    runtime.ward_room_router.extract_endorsements.return_value = (None, [])
    runtime.config = MagicMock()
    runtime.config.communications = MagicMock()
    runtime.config.communications.dm_min_rank = "ensign"
    runtime.crew_session_service = None
    runtime.dispatcher = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "callsign"
    runtime.callsign_registry.resolve.return_value = None
    runtime.agent_work = service
    return runtime


def _loop(runtime: Any) -> ProactiveCognitiveLoop:
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(runtime)
    return loop


def _posts(path: Path, thread_id: str) -> list[tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute(
            "SELECT author_id, body FROM posts WHERE thread_id = ? ORDER BY created_at", (thread_id,),
        ).fetchall()


# C1
@pytest.mark.parametrize(("text", "expected", "cleaned"), [
    (f"Note.\n{SELF_TASK}", [AgentWorkTag("self_task", title="Check my build log", reason="the relay drifted twice")], "Note."),
    (
        "[REQUEST_WORK]\nTitle: Read it\nReason: first\nsecond line\nTool: event_log_query\nDepartment: Engineering\n"
        "Assignee: @Forge\n[/REQUEST_WORK] after",
        [AgentWorkTag("request", title="Read it", reason="first second line", tool_id="event_log_query",
                      department="engineering", assignee="Forge")],
        "after",
    ),
    ("Taking it. [CLAIM_WORK wi-123]", [AgentWorkTag("claim", work_item_id="wi-123")], "Taking it."),
    ("[DECLINE_WORK wi-9]\nOn the warp core\nall shift.\n[/DECLINE_WORK]",
     [AgentWorkTag("decline", work_item_id="wi-9", reason="On the warp core all shift.")], ""),
    ("Open [SELF_TASK]\nTitle: never closed", [], "Open \nTitle: never closed"),
    ("Stray [/REQUEST_WORK] and [CLAIM_WORK] and [DECLINE_WORK bad id!]", [], "Stray  and  and"),
])
def test_the_parser_reads_each_tag_and_strips_every_marker(text: str, expected: list[AgentWorkTag], cleaned: str) -> None:
    got, tags = split_agent_work_tags(text)
    assert list(tags) == expected
    assert got == cleaned


# C2
def test_a_text_without_agent_work_tags_is_returned_unchanged() -> None:
    text = "  Relay 4 is at 93 percent. [ENDORSE p1 UP]\n"
    assert split_agent_work_tags(text) == (text, ())


# C3
async def test_a_self_task_tag_in_a_ward_room_reply_files_under_the_agents_slot_with_the_thread_as_origin(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(
            ship.agents["forge-1"], f"Checking.\n{SELF_TASK}", thread_id="thread-9", post_id="post-9",
        )
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert (item.created_by, item.assigned_to) == ("forge-1", "forge-1")
        assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": "thread-9", "post_id": "post-9"}
        assert "[SELF_TASK]" not in cleaned and "[/SELF_TASK]" not in cleaned
        assert cleaned.startswith("Checking.") and item.id[:8] in cleaned and "Ship's Computer" in cleaned
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": "created", "work_item_id": item.id}


# C4
async def test_a_request_tag_publishes_to_a_department_and_the_chain_request_is_discoverable(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, _ = await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None
        assert (record.kind, record.department, record.tool_id) == ("request", "engineering", "event_log_query")
        assert (item.created_by, item.assigned_to) == ("pulaski-1", None)
        assert await _discovered(ship, "forge-1") == [item.id]  # the placement trap (premise 6), through the chain
        assert "engineering" in cleaned and item.id[:8] in cleaned
        named = REQUEST.replace("Title: Read the EventLog window", "Title: Read the access log").replace(
            "Tool: event_log_query", "Tool: event_log_query\nDepartment: Security",
        )
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], named, thread_id="t1")
        security = [read_agent_work(i) for i in await ship.store.list_agent_work(False, None, 10) if i.id != item.id]
        assert [r.department for r in security if r is not None] == ["security"]


# C5
async def test_while_off_the_extractor_never_enters_the_agent_work_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[dict[str, Any]] = []

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        entered.append(kwargs)
        raise AssertionError("the agent-work path was entered while agent_work is off")

    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    async with _ship(tmp_path) as ship:
        for service in (None, MagicMock()):  # off, and a double that is not the real service
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C6
async def test_an_ensigns_tags_are_stripped_and_nothing_is_filed(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        trust = TrustNetwork()
        trust.create_with_prior("forge-2", 1.0, 3.0)  # 0.25: an ensign
        loop = _loop(_loop_runtime(ship.service, trust))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-2"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert cleaned == "Obs." and [a for a in actions if a.get("type") == "agent_work"] == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C7
@pytest.mark.parametrize("who", ["unresolved", "stopped"])
async def test_an_unresolved_or_stopped_requester_is_refused_and_nothing_is_written(tmp_path: Path, who: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        if who == "unresolved":
            agent: Any = SimpleNamespace(id="ghost-1", agent_type="builder", callsign="Ghost")
        else:
            issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
            agent = ship.agents["forge-1"]
        cleaned, actions = await loop._extract_and_execute_actions(agent, SELF_TASK, thread_id="t1")
        assert "not filed" in cleaned and "CANARY" not in cleaned
        code = "requester_unresolved" if who == "unresolved" else "agent_stopped"
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": f"refused:{code}"}
        assert await ship.store.list_agent_work(False, None, 10) == []
        if who == "stopped":
            assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 1}


# C8
async def test_at_most_three_actions_are_taken_from_one_reply(tmp_path: Path) -> None:
    async with _ship(tmp_path, section=_section(max_open_per_agent=10, max_created_per_agent_per_hour=10)) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        blocks = "\n".join(
            f"[SELF_TASK]\nTitle: Task {n}\nReason: the relay drifted\n[/SELF_TASK]" for n in ("one", "two", "three", "four")
        )
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], blocks, thread_id="t1")
        assert len(await ship.store.list_agent_work(False, None, 10)) == MAX_TAGS_PER_REPLY
        assert len([a for a in actions if a.get("type") == "agent_work"]) == MAX_TAGS_PER_REPLY
        assert f"only {MAX_TAGS_PER_REPLY} agent-work actions" in cleaned


# C9
@pytest.mark.parametrize("thread_id", [" t1", "x" * 129])
async def test_an_origin_the_service_cannot_record_is_a_refused_tag(tmp_path: Path, thread_id: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], SELF_TASK, thread_id=thread_id)
        assert "could not be recorded as its origin" in cleaned
        assert actions[-1]["outcome"] == "refused:invalid_origin"
        assert await ship.store.list_agent_work(False, None, 10) == []


# C10
async def test_a_second_requester_of_the_same_request_becomes_its_watcher_through_the_chain(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["ogawa-1"], REQUEST, thread_id="t2")
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert await ship.store.list_work_watchers(item.id) == ("ogawa-1",)
        assert "watcher" in cleaned and actions[-1]["outcome"] == "deduplicated"


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="ok", tokens_used=1)


_BUILDERS = {
    "ward_room_response": _build_ward_room_compose_prompt,
    "proactive_observation": _build_proactive_compose_prompt,
    "dm_response": _build_dm_compose_prompt,
}


# C11
@pytest.mark.parametrize("mode", sorted(_BUILDERS))
async def test_the_compose_prompt_teaches_the_tags_only_while_agent_work_is_on(tmp_path: Path, mode: str) -> None:
    """The byte-identical golden of the prompt: off, the compose system prompt is exactly the mode's builder output."""
    context = {"_agent_type": "builder", "_callsign": "Forge", "_department": "engineering"}
    expected, _ = _BUILDERS[mode](dict(context), [], "Forge", "engineering")
    prompts: dict[str, str] = {}
    async with _ship(tmp_path) as ship:
        for label, service in (("off", None), ("on", ship.service)):
            llm = _Capture()
            handler = ComposeHandler(llm_client=llm, runtime=SimpleNamespace(agent_work=service))
            spec = SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", prompt_template=mode)
            result = await handler(spec, dict(context), [])
            assert result.success, result.error
            prompts[label] = llm.requests[0].system_prompt
    assert prompts["off"] == expected
    if mode == "dm_response":
        assert prompts["on"] == expected
    else:
        assert prompts["on"] == expected + "\n\n" + AGENT_WORK_INSTRUCTIONS
        assert "[SELF_TASK]" in prompts["on"] and "[REQUEST_WORK]" in prompts["on"]


# C12
async def test_the_ward_room_pipeline_passes_its_thread_and_post_to_the_extractor(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await wr.start()
        try:
            medical = await wr.get_channel_by_department("medical")
            thread = await wr.create_thread(medical.id, "bones-1", "Relay", "The relay drifted.", author_callsign="Bones")
            post = await wr.create_post(thread.id, "bones-1", "Twice now.", author_callsign="Bones")
            runtime = _loop_runtime(ship.service, TrustNetwork())
            runtime.ward_room = wr
            router = MagicMock(spec=WardRoomRouter)
            router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
            pipeline = WardRoomPostPipeline(
                ward_room=wr, ward_room_router=router, proactive_loop=_loop(runtime), trust_network=None,
                callsign_registry=None, config=MagicMock(),
            )
            posted = await pipeline.process_and_post(
                agent=ship.agents["pulaski-1"], response_text=f"I need the log.\n{REQUEST}",
                thread_id=thread.id, event_type="ward_room_post_created", post_id=post.id,
            )
            assert posted is True
            [item] = await ship.store.list_agent_work(False, None, 10)
            assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": thread.id, "post_id": post.id}
            replies = [body for author, body in _posts(tmp_path / "wr.db", thread.id) if author == "pulaski-1"]
            assert len(replies) == 1 and item.id[:8] in replies[0] and "[REQUEST_WORK]" not in replies[0]
        finally:
            await wr.stop()


# C13
async def test_a_chief_assigns_a_member_of_its_department_by_callsign(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        runtime = _loop_runtime(ship.service, TrustNetwork())
        runtime.callsign_registry.resolve.return_value = {"agent_id": "forge-1"}
        assigned = REQUEST.replace("Tool: event_log_query", "Tool: event_log_query\nAssignee: @Forge")
        cleaned, actions = await _loop(runtime)._extract_and_execute_actions(ship.agents["laforge-1"], assigned, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None and (record.kind, item.assigned_to, item.created_by) == ("assignment", "forge-1", "laforge-1")
        assert "assigned to forge-1" in cleaned and actions[-1]["outcome"] == "created"
```

### 7.7 `src/probos/agent_work.py` (M2: two public questions for the runner)

SEARCH:
```python
    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?
```
REPLACE:
```python
    def crew_member(self, key: str) -> CrewMember | None:
        """S3: the live crew member ``key`` names (any identity form the facade resolves), or None (fail closed)."""
        ref = self._identities.resolve(key) if _identifier(key) else None
        return self._directory.member(ref.slot_id) if ref is not None else None

    def execution_allowed(self, item: WorkItem, slot_id: str) -> bool:
        """S3, asked before every run and again after it (A3's hand-on): may ``slot_id`` run this item now?

        Its assignee only, live and not stopped. A request: a member of its department who may use its tool, the claim
        gate's question asked again, so a claimant that lost eligibility after its claim is not run. A self-task or an
        assignment: holding the named tool when one is named. Never cached; never raises.
        """
        try:
            record = read_agent_work(item)
            if record is None or item.assigned_to != slot_id:
                return False
            member = self._directory.member(slot_id)
            if member is None or self._stopped_now(member.slot_id):
                return False
            if record.kind == KIND_REQUEST:
                return member.department == record.department and record.tool_id is not None and self._holds_tool(member, record.tool_id)
            return record.tool_id is None or self._holds_tool(member, record.tool_id)
        except Exception:
            logger.warning(
                "AD-1347: the run check for work item %s failed; it is not run by %s now",
                getattr(item, "id", "?"), slot_id, exc_info=True,
            )
            return False

    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?
```

### 7.8 `src/probos/cognitive/agentic_dispatch.py` (M2: per-call confinement)

Pair 1 of 9 (the refusals and the confinement):

SEARCH:
```python
# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset(
    {_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL}
)
```
REPLACE:
```python
# AD-1347 S3 (#1627): agent-created work runs confined. Its calls to the tools in the run's set run as usual; a call to
# any other tool is put to the run's gate, which files it for the Captain's approval (an AD-1154 ``action``) or admits
# the one call an approval on record covers. Error-shaped and final, in the AD-1154 voice; never defect evidence.
CONFINED_CALL_FILED: str = (
    "That call needs the Captain's approval before it runs. It was filed for review and did not run. Do not "
    "repeat it: a repeat is folded into the same request. Finish what the read-only tools allow and report "
    "what remains open."
)
CONFINED_CALL_NOT_FILED: str = (
    "That call needs the Captain's approval before it runs, and it could not be filed for review, so it did "
    "not run. Finish what the read-only tools allow and report what remains open."
)
CONFINEMENT_ADMIT = "admit"
CONFINEMENT_FILED = "filed"
CONFINEMENT_REFUSED = "refused"

# AD-1189 / AD-1156: refusals of calls that never ran. They say nothing about
# the tool, so they are never defect evidence.
_NEVER_RAN_REFUSALS: frozenset[str] = frozenset(
    {_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED}
)


@dataclass(frozen=True)
class ToolCallConfinement:
    """AD-1347 S3: the calls a run makes directly (``tool_ids``) and the gate every other call is put to.

    ``gate(agent_id, tool_id, params)`` answers ``CONFINEMENT_ADMIT`` (run it), ``CONFINEMENT_FILED`` (filed for the
    Captain's approval) or anything else (not filed). Enforced first in the executor's invoke, before plan mode and the
    AD-1154 browser inbox, so the decision is made at the tool call, never by reading the plan.
    """

    tool_ids: frozenset[str]
    gate: Callable[[str, Any, Any], Awaitable[str]]

    def __post_init__(self) -> None:
        if (
            type(self.tool_ids) is not frozenset or not self.tool_ids
            or any(type(tool_id) is not str or not tool_id for tool_id in self.tool_ids)
            or not callable(self.gate)
        ):
            raise ValueError("tool_call_confinement_invalid")

    async def refuse_or_admit(self, agent_id: str, tool_id: Any, params: Any) -> ToolResult | None:
        """None admits the call; otherwise the refusal it gets. Fails closed: a gate that raises refuses."""
        try:
            verdict = await self.gate(agent_id, tool_id, params)
        except Exception:
            logger.warning(
                "AD-1347: the confinement gate raised for a call from agent %s; the call is refused and did not run",
                agent_id[:12], exc_info=True,
            )
            verdict = CONFINEMENT_REFUSED
        if verdict == CONFINEMENT_ADMIT:
            return None
        return ToolResult(error=CONFINED_CALL_FILED if verdict == CONFINEMENT_FILED else CONFINED_CALL_NOT_FILED)
```

Pair 2 of 9 (checked first at the call):

SEARCH:
```python
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
            if strict_dispatch is not None:
                strict_log("plan_mode", "plan_mode_refused")
```
REPLACE:
```python
        confinement = self._confinement
        if confinement is not None and tool_id not in confinement.tool_ids:
            refusal = await confinement.refuse_or_admit(agent_id, tool_id, params)
            if refusal is not None:
                strict_log("confinement", "confinement_refused")
                return refuse(refusal, "confinement_refused")
        if self._plan_mode_tool_ids is not None and tool_id not in self._plan_mode_tool_ids:
            if strict_dispatch is not None:
                strict_log("plan_mode", "plan_mode_refused")
```

Pair 3 of 9 (unarmed by default):

SEARCH:
```python
        self._plan_mode_tool_ids: frozenset[str] | None = None  # AD-1156: None = unarmed

    def arm_approval_inbox(
```
REPLACE:
```python
        self._plan_mode_tool_ids: frozenset[str] | None = None  # AD-1156: None = unarmed
        self._confinement: ToolCallConfinement | None = None  # AD-1347 S3: None = unarmed

    def arm_approval_inbox(
```

Pair 4 of 9 (arming):

SEARCH:
```python
    def restrict_to_plan_mode(self, tool_ids: frozenset[str]) -> None:
        """AD-1156: refuse, first in :meth:`invoke`, every call to a tool not in ``tool_ids``."""
        self._plan_mode_tool_ids = tool_ids
```
REPLACE:
```python
    def restrict_to_plan_mode(self, tool_ids: frozenset[str]) -> None:
        """AD-1156: refuse, first in :meth:`invoke`, every call to a tool not in ``tool_ids``."""
        self._plan_mode_tool_ids = tool_ids

    def confine_calls(self, confinement: ToolCallConfinement) -> None:
        """AD-1347 S3: put every call to a tool outside ``confinement.tool_ids`` to its gate, first in :meth:`invoke`."""
        self._confinement = confinement
```

Pair 5 of 9 (a policy outcome for fault observation):

SEARCH:
```python
            _BROWSER_READ_ONLY_REFUSAL, _APPROVAL_PARKED_REFUSAL_NO_ID,
            _APPROVAL_INBOX_FULL_REFUSAL, _APPROVAL_CREDENTIAL_REFUSAL,
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            "consensus_blocked", "requires_confirmation",
```
REPLACE:
```python
            _BROWSER_READ_ONLY_REFUSAL, _APPROVAL_PARKED_REFUSAL_NO_ID,
            _APPROVAL_INBOX_FULL_REFUSAL, _APPROVAL_CREDENTIAL_REFUSAL,
            _DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL,
            CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED,  # AD-1347 S3
            "consensus_blocked", "requires_confirmation",
```

Pair 6 of 9 (`run` gains the keyword, appended last):

SEARCH:
```python
        inner_loop_hook: Any = None,
        admitted_turn: bool = False,
    ) -> WorkItemAgenticOutcome:
```
REPLACE:
```python
        inner_loop_hook: Any = None,
        admitted_turn: bool = False,
        confinement: ToolCallConfinement | None = None,
    ) -> WorkItemAgenticOutcome:
```

Pair 7 of 9 (forwarded only when set):

SEARCH:
```python
        # AD-1322: transported unchanged; absent => the arguments are unchanged.
        if inner_loop_hook is not None:
            arguments["inner_loop_hook"] = inner_loop_hook
```
REPLACE:
```python
        # AD-1322: transported unchanged; absent => the arguments are unchanged.
        if inner_loop_hook is not None:
            arguments["inner_loop_hook"] = inner_loop_hook
        # AD-1347 S3: forwarded only when set, for the same reason.
        if confinement is not None:
            arguments["confinement"] = confinement
```

Pair 8 of 9 (`_run_reserved` gains the keyword and validates it):

SEARCH:
```python
        budget_awareness_state: AgenticBudgetAwarenessState | None = None,
        inner_loop_hook: Any = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.
```
REPLACE:
```python
        budget_awareness_state: AgenticBudgetAwarenessState | None = None,
        inner_loop_hook: Any = None,
        # AD-1347 S3: agent-created work's per-call confinement. None -- every other caller -- changes nothing.
        confinement: ToolCallConfinement | None = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.
```

and

SEARCH:
```python
            raise ValueError("plan_mode_tool_ids_invalid")

        department, rank = _resolve_agentic_identity(
```
REPLACE:
```python
            raise ValueError("plan_mode_tool_ids_invalid")

        # AD-1347 S3: a confinement is exact and never runs with plan mode, or the run does not start.
        if confinement is not None and (
            type(confinement) is not ToolCallConfinement or plan_mode_tool_ids is not None
        ):
            raise ValueError("tool_call_confinement_invalid")

        department, rank = _resolve_agentic_identity(
```

Pair 9 of 9 (armed after the offer is built; the offer itself is unchanged):

SEARCH:
```python
        if plan_mode_tool_ids is not None:
            tool_ids = [tool_id for tool_id in tool_ids if tool_id in plan_mode_tool_ids]
            executor.restrict_to_plan_mode(plan_mode_tool_ids)
```
REPLACE:
```python
        if plan_mode_tool_ids is not None:
            tool_ids = [tool_id for tool_id in tool_ids if tool_id in plan_mode_tool_ids]
            executor.restrict_to_plan_mode(plan_mode_tool_ids)
        # AD-1347 S3: the offer stays whole -- the agent may name any tool it holds -- and the call decides (D4).
        if confinement is not None:
            executor.confine_calls(confinement)
```

### 7.9 New file: `src/probos/agent_work_runner.py` (M2)

```python
"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work and reports it where it was asked.

One runner per vessel, built in finalize only while ``runtime.agent_work`` exists. It reacts to the work store's own
events (one listener):

- a created self-task or chief assignment runs at once, in its assignee's agentic loop;
- a created department request is announced once to each eligible member, in that department's channel, with the
  claim and decline tags (a pull reaches nobody by itself; the TTL is the backstop);
- a claimed request runs in its claimant's agentic loop (AD-1187's claim; the chain's CLAIM_WORK claims through the
  same tool sink and also starts the run itself);
- an item that ends has its live bookings closed and is reported, once per recipient, to its requester and watchers.

Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is filed as an AD-1154 ``action`` request instead of running. After such a run the item parks
``blocked`` on that request through AD-855's ``block_on_request``; the Captain's approval fulfils it, AD-855 resumes the
item through ``resume_agent_work``, and the next run makes that one call (its approval is consumed on a claim-once row).
A denial cancels the item (AD-855) and the report names the Captain's reason.

The stop: every run enters at ``WorkItemAgenticExecutor.run``, which refuses a stopped agent at ``agentic_run``. A
request whose claimant may no longer run it (stopped, moved, lost the tool) goes back to the board unclaimed, never
failed. Expiry stays the store's TTL sweep; this runner only reports it. The cognitive layer is imported inside the
functions that run work, so the approval route's import of ``agent_work_approval`` loads no agentic stack.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Final

from probos.agent_stop import AgentStopped
from probos.agent_work import (
    KIND_REQUEST,
    MAX_REASON_CHARS,
    OUTCOME_EXPIRED,
    SCAN_LIMIT,
    AgentWorkNotice,
    AgentWorkRecord,
    AgentWorkService,
    read_agent_work,
)
from probos.capability_request import action_dedup_key, validate_action_payload
from probos.events import EventType
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.workforce import AGENT_WORK_METADATA_KEY, WorkItem

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

logger = logging.getLogger(__name__)

#: The tools an agent-created work run calls directly: the plan-mode read set (``agent_mode.PLAN_MODE_TOOL_IDS``, each
#: asserted read-only there) without the three that reach off the ship (web_search, read_page, http_fetch) and without
#: discover_work_items. Every other call is filed for the Captain's approval: a new or renamed tool is filed until
#: someone decides it only reads.
AGENT_WORK_READ_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
})
APPROVAL_ACTION: Final = "agent_work_call"
APPROVAL_SCOPE_PREFIX: Final = "agent_work:"
APPROVAL_USE_PREFIX: Final = "approval_use:"
NOTICE_ACTIVATION: Final = "activation"
NOTICE_DECLINE: Final = "decline"
RESULT_METADATA_KEY: Final = "agent_work_result"
SHIP_COMPUTER_ID: Final = "system"
SHIP_COMPUTER_CALLSIGN: Final = "Ship's Computer"
RUN_SOURCE: Final = "agent_work_runner"
REPORT_MAX_CHARS: Final = 1_500
BLOCKED_REASON: Final = "waiting for the Captain's decision on a tool call outside the read-only set"
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
_HANDLED_EVENTS: Final[frozenset[str]] = frozenset({
    EventType.WORK_ITEM_CREATED.value, EventType.WORK_ITEM_CLAIMED.value, EventType.WORK_ITEM_STATUS_CHANGED.value,
})
#: The claim tool renders its receipt through the invocation's presentation; the runner reads the board, not the text.
_PRESENTATION: Final = ToolResultPresentation(render_complete=repr)


def agent_work_approval(request: Any) -> dict[str, Any] | None:
    """The validated payload when ``request`` asks to make one tool call in one agent-created work item, else None."""
    if getattr(request, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(request, "payload", None))
    work_item_id = getattr(request, "work_item_id", None)
    if (
        payload is None or payload["action"] != APPROVAL_ACTION
        or type(work_item_id) is not str or not work_item_id
        or payload["scope_key"] != APPROVAL_SCOPE_PREFIX + work_item_id
    ):
        return None
    return payload


def approval_payload(tool_id: Any, params: Any, work_item_id: str) -> dict[str, Any] | None:
    """The AD-1154 ``action`` payload that asks for one call, or None when the call cannot be recorded."""
    if type(tool_id) is not str or type(params) is not dict:
        return None
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": dict(params),
        "scope_key": APPROVAL_SCOPE_PREFIX + work_item_id, "session_id": None, "thread_id": "",
    })


def _provenance(item: WorkItem) -> dict[str, Any]:
    metadata = item.metadata if type(item.metadata) is dict else {}
    raw = metadata.get(AGENT_WORK_METADATA_KEY)
    return raw if type(raw) is dict else {}


def _origin_thread(item: WorkItem) -> str:
    """The Ward Room thread the work was asked in, or "" (a proactive thought, or no thread)."""
    origin = _provenance(item).get("origin")
    if type(origin) is not dict or origin.get("channel") != "ward_room":
        return ""
    thread_id = origin.get("thread_id")
    return thread_id if type(thread_id) is str else ""


def task_text(item: WorkItem, *, requester: str) -> str:
    """What the run is asked: the colleague's request, its reason and its tool, and the confinement in plain words."""
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
    details = f"{item.description}\n\n" if item.description and item.description != item.title else ""
    return (
        f"Agent work {item.id}: {item.title}\n\n{details}"
        f"Asked by {requester}. Reason: {reason}. Tool named: {tool}.\n\n"
        "Read-only tools run directly. A call to any other tool is filed for the Captain's approval and does not run "
        "now; this work resumes after the Captain decides. Do the reading, then answer with what you found and the "
        "tool results you relied on. Your answer is posted where the work was asked for."
    )


def outcome_text(item: WorkItem, outcome: str, *, mentions: str, denial: str = "") -> str:
    """The post that tells the requester and watchers how the work came out (the echo-chamber rule included)."""
    head = f"{mentions} Agent work {item.id[:8]} (\"{item.title}\")"
    metadata = item.metadata if type(item.metadata) is dict else {}
    result = metadata.get(RESULT_METADATA_KEY)
    if type(result) is dict and type(result.get("answer")) is str:
        tools = ", ".join(name for name in result.get("tools", ()) if type(name) is str) or "none"
        trace = result.get("trace") if type(result.get("trace")) is str else ""
        evidence = f"Evidence: tools that answered: {tools}; their records are filed under work item {item.id}"
        evidence += f", trace {trace}" if trace else ""
        status = "is done" if outcome == "done" else f"ended as {outcome}, after this answer"
        return (
            f"{head} {status}. {result.get('executor', 'A colleague')} reported:\n\n{result['answer']}\n\n"
            f"{evidence}. This is a colleague's report: check it against the record before you rely on it."
        )
    if outcome == OUTCOME_EXPIRED:
        return f"{head} expired before anyone produced a result. Ask again if it is still needed."
    if denial:
        return f"{head} was stopped: the Captain declined a step it needed. Reason: {denial}"
    if outcome == "failed":
        return f"{head} failed before it produced a result."
    return f"{head} ended as {outcome} without a result."


async def _approved_admission(requests: Any, item: WorkItem, slot_id: str) -> tuple[str, str] | None:
    """(request id, call key) of the approval this item was parked on and resumed by, or None."""
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return None
    request = await requests.get(request_id)
    payload = agent_work_approval(request) if request is not None else None
    if payload is None or request.status != "fulfilled" or request.agent_id != slot_id or request.work_item_id != item.id:
        return None
    return request_id, action_dedup_key(agent_id=slot_id, payload=payload, work_item_id=item.id)


async def _denial_reason(requests: Any, item: WorkItem) -> str:
    """The Captain's reason when the request this item was parked on was denied, else "".

    Read from the request, not the item: AD-855 writes ``denial_reason`` only after the cancel this notice follows.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    if type(request_id) is not str or not request_id:
        return ""
    request = await requests.get(request_id)
    if request is None or request.status != "denied" or agent_work_approval(request) is None:
        return ""
    return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]


async def _close_bookings(store: Any, work_item_id: str, *, completed: bool) -> None:
    """A finished item's live booking is completed (done) or cancelled, so its claimant's capacity is freed."""
    for booking in await store.list_bookings(work_item_id=work_item_id):
        if booking.status in ("completed", "cancelled"):
            continue
        if completed and booking.status in ("active", "scheduled"):
            await store.complete_booking(booking.id)
        else:
            await store.cancel_booking(booking.id)


class AgentWorkRunner:
    """Ship's Computer: runs agent-created work in its assignee's agentic loop and reports it (AD-1347 S3)."""

    def __init__(
        self,
        *,
        service: AgentWorkService,
        store: Any,
        ward_room: Any,
        tools: Any,
        requests: Any,
        parking: Any,
        executor: WorkItemAgenticExecutor,
        runtime: Any,
        agents: Any,
        callsign_of: Callable[[str], str],
        max_pending: int = 20,
        ttl_seconds: int = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if any(value is None for value in (service, store, ward_room, tools, requests, parking, executor, agents)):
            raise ValueError("agent_work_runner_dependencies_required")
        self._service = service
        self._store = store
        self._ward_room = ward_room
        self._tools = tools
        self._requests = requests
        self._parking = parking
        self._executor = executor
        self._runtime = runtime  # passed through to each run only (the executor reads its stores from it)
        self._agents = agents
        self._callsign_of = callsign_of
        self._max_pending = max_pending
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._tasks: set[asyncio.Task[None]] = set()
        self._active: set[str] = set()
        self._deliver_lock = asyncio.Lock()
        self._stopping = False

    @property
    def running(self) -> tuple[asyncio.Task[None], ...]:
        """The runs in flight (``stop`` cancels them; a test awaits them)."""
        return tuple(self._tasks)

    async def on_store_event(self, event: Any) -> None:
        """The work store's events: created and claimed agent work starts, ended work is reported. Never raises."""
        try:
            raw_type = event.get("type") if type(event) is dict else None
            kind = getattr(raw_type, "value", raw_type)
            data = event.get("data") if type(event) is dict else None
            raw = data.get("work_item") if type(data) is dict else None
            work_item_id = raw.get("id") if type(raw) is dict else None
            if kind not in _HANDLED_EVENTS or type(work_item_id) is not str or not work_item_id:
                return
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None:
                return
            if kind == EventType.WORK_ITEM_STATUS_CHANGED.value:
                if item.status in TERMINAL_STATUSES:
                    await _close_bookings(self._store, item.id, completed=item.status == "done")
                    await self.deliver_due_notices()
            elif kind == EventType.WORK_ITEM_CREATED.value and record.kind == KIND_REQUEST:
                await self._announce(item, record)
            elif kind == EventType.WORK_ITEM_CREATED.value or record.kind == KIND_REQUEST:
                self._start(item.id)
        except Exception:
            logger.warning(
                "AD-1347: an agent-work event could not be handled; the board is unchanged and the next start's "
                "recovery retries it", exc_info=True,
            )

    async def claim(self, actor: str, work_item_id: str) -> tuple[str, str]:
        """CLAIM_WORK: claim through the tool sink (the stop at ``tool``, the claim tool's rank, AD-1187's compare and
        set, S1's eligibility gate), then run. Returns (outcome, what the claimant is told)."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        if member is None:
            return "refused", f"work item {short} was not claimed: you are not a live crew member"
        try:
            result = await self._tools.check_and_invoke(
                member.slot_id, "claim_work_item", {"work_item_id": work_item_id}, required=ToolPermission.WRITE,
                agent_department=member.department, agent_rank=member.rank, agent_types=[member.agent_type],
                context={"agent_id": member.slot_id, "_tool_result_presentation": _PRESENTATION},
            )
            claimed = result.error is None
        except Exception:
            logger.info("AD-1347: %s could not claim work item %s through the tool", member.slot_id, short, exc_info=True)
            claimed = False
        claimed_item = await self._store.get_work_item(work_item_id) if claimed else None
        if claimed_item is None or claimed_item.assigned_to != member.slot_id:
            return "not_claimed", f"work item {short} was not claimed by you: it is taken, closed, or not yours to serve"
        self._start(claimed_item.id)
        return "claimed", f"you claimed work item {short} (\"{claimed_item.title}\"); it runs now and its result is posted where it was asked"

    async def decline(self, actor: str, work_item_id: str, reason: str) -> tuple[str, str]:
        """DECLINE_WORK: a member of the request's department says why it is not theirs, once; the requester is told in
        the thread the work was asked in. The request stays open for the rest of the department."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        item = await self._store.get_work_item(work_item_id)
        record = read_agent_work(item) if item is not None else None
        if (
            member is None or item is None or record is None or record.kind != KIND_REQUEST
            or item.status != "open" or member.department != record.department
        ):
            return "refused", f"work item {short} is not an open request to your department"
        if not await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_DECLINE, self._clock()):
            return "repeated", f"you already declined work item {short}"
        why = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        requester = self._callsign_of(record.requester)
        await self._post(item, record, f"@{requester} {self._callsign_of(member.slot_id)} declined work item {short} (\"{item.title}\"): {why}")
        return "declined", f"you declined work item {short}; {requester} was told"

    async def resume(self, work_item_id: str) -> None:
        """AD-855 resumed a parked item (its request settled): run it again."""
        self._start(work_item_id)

    async def recover(self) -> int:
        """At start: run again every agent-created item a previous run left assigned and unfinished (a parked item
        waits for its request), then send the notices it owed. Idempotent; returns how many runs it started."""
        started = 0
        for open_item in await self._store.list_agent_work(True, None, SCAN_LIMIT):
            if open_item.assigned_to is None or open_item.status == "blocked":
                continue
            self._start(open_item.id)
            started += 1
        await self.deliver_due_notices()
        return started

    async def deliver_due_notices(self) -> int:
        """Tell each requester and watcher how ended agent work came out: one post per item, naming everyone newly
        told. A notice is claimed before it is sent (S1), so overlapping deliveries and a restart send it at most once.
        Returns how many recipients were told."""
        async with self._deliver_lock:
            grouped: dict[str, list[AgentWorkNotice]] = {}
            for notice in await self._service.terminal_notices_due():
                grouped.setdefault(notice.work_item_id, []).append(notice)
            told = 0
            for work_item_id, notices in grouped.items():
                item = await self._store.get_work_item(work_item_id)
                record = read_agent_work(item) if item is not None else None
                if item is None or record is None:
                    continue
                claimed = [notice.recipient for notice in notices if await self._service.claim_notice(work_item_id, notice.recipient)]
                if not claimed:
                    continue
                mentions = " ".join(f"@{self._callsign_of(recipient)}" for recipient in claimed)
                body = outcome_text(item, notices[0].outcome, mentions=mentions, denial=await _denial_reason(self._requests, item))
                if await self._post(item, record, body):
                    told += len(claimed)
            return told

    async def stop(self) -> None:
        """Shutdown: start nothing more, cancel the runs in flight and wait for them (``recover`` restarts them)."""
        self._stopping = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start(self, work_item_id: str) -> None:
        """Run one item in the background, at most once at a time in this process."""
        if self._stopping or work_item_id in self._active:
            return
        self._active.add(work_item_id)
        task = asyncio.create_task(self._run(work_item_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, work_item_id: str) -> None:
        """One confined run of one item, then park it, return it to the board, or record its answer. Never raises
        (a cancellation from ``stop`` excepted); a failure marks the item failed, which its requester is told."""
        try:
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None or item.assigned_to is None or item.status in TERMINAL_STATUSES:
                return
            if item.status == "blocked":
                return
            slot = item.assigned_to
            if not self._service.execution_allowed(item, slot):
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant may not run it now")
                return
            if not await self._begin(item):
                return
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS,
                self._gate_for(item.id, await _approved_admission(self._requests, item, slot), filed),
            )
            try:
                outcome = await self._executor.run(
                    agent_id=slot, instructions=str(getattr(agent, "instructions", "") or ""),
                    task_text=task_text(item, requester=self._callsign_of(record.requester)),
                    runtime=self._runtime, failure_scope=item.id,
                    work_item_id_provider=lambda: item.id, confinement=confinement,
                )
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            if filed:
                await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)
                return
            if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):
                await self._store.unassign_work_item(item.id, reason="the claimant was stopped or lost the tool during the run")
                return
            invocations = getattr(outcome, "tool_invocations", None)
            result = {
                "executor": self._callsign_of(slot),
                "answer": (outcome.final_text or "").strip()[:REPORT_MAX_CHARS] or "(no answer text)",
                "tools": sorted(getattr(invocations, "succeeded", ()) or ()),
                "trace": outcome.tool_trace_ref or "",
            }
            done = await self._store.transition_work_item(
                item.id, "done", source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},
            )
            if done is None:
                current = await self._store.get_work_item(item.id)
                if current is not None and current.status in TERMINAL_STATUSES:
                    await self._store.transition_work_item(
                        item.id, current.status, source=RUN_SOURCE, expected_status=current.status,
                        metadata_patch={RESULT_METADATA_KEY: result},
                    )
            await _close_bookings(self._store, item.id, completed=done is not None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1347: the run of agent work item %s failed; it is marked failed and its requester is told",
                work_item_id, exc_info=True,
            )
            try:
                if await self._store.transition_work_item(
                    work_item_id, "failed", source=RUN_SOURCE, expected_status="in_progress",
                ) is not None:
                    await _close_bookings(self._store, work_item_id, completed=False)
            except Exception:
                logger.warning("AD-1347: work item %s could not be marked failed; it stays in_progress", work_item_id, exc_info=True)
        finally:
            self._active.discard(work_item_id)

    async def _begin(self, item: WorkItem) -> bool:
        """Move the item to in_progress once: a claimed request starts its booking; a self-task or an assignment
        moves from open; a resumed item is in_progress already."""
        if item.status == "in_progress":
            return True
        if item.status == "scheduled":
            bookings = [
                booking for booking in await self._store.list_bookings(work_item_id=item.id, status="scheduled")
                if booking.resource_id == item.assigned_to
            ]
            return len(bookings) == 1 and await self._store.start_booking(bookings[0].id) is not None
        if item.status == "open":
            moved = await self._store.transition_work_item(item.id, "in_progress", source=RUN_SOURCE, expected_status="open")
            return moved is not None
        return False

    def _gate_for(
        self, work_item_id: str, admission: tuple[str, str] | None, filed: list[str],
    ) -> Callable[[str, Any, Any], Awaitable[str]]:
        """The run's confinement gate: admit the one call an approval on record covers, else file the call for the
        Captain's approval. Fails toward refusal: a call that cannot be recorded is not run."""
        from probos.cognitive.agentic_dispatch import CONFINEMENT_ADMIT, CONFINEMENT_FILED, CONFINEMENT_REFUSED

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
            key = action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id)
            if admission is not None and key == admission[1] and await self._store.claim_work_notice(
                work_item_id, agent_id, APPROVAL_USE_PREFIX + admission[0], self._clock(),
            ):
                return CONFINEMENT_ADMIT
            if self._requests.count_pending_sync(agent_id) >= self._max_pending:
                return CONFINEMENT_REFUSED
            request = await self._requests.file_action_request(
                agent_id, payload, rationale=f"agent work {work_item_id[:8]} called {tool_id}, outside the read-only set",
                work_item_id=work_item_id,
            )
            if request is None or not getattr(request, "id", ""):
                return CONFINEMENT_REFUSED
            if request.id not in filed:
                filed.append(request.id)
            return CONFINEMENT_FILED

        return gate

    async def _announce(self, item: WorkItem, record: AgentWorkRecord) -> int:
        """The activation notice: once per eligible member of the request's department, in that department's channel,
        with routing held to the members named (``max_responders``). Returns how many were told."""
        if record.tool_id is None or item.status != "open":
            return 0
        fresh: list[str] = []
        for member in self._service.eligible_members(record.tool_id):
            if member.department != record.department or member.slot_id == record.requester:
                continue
            if await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_ACTIVATION, self._clock()):
                fresh.append(member.slot_id)
        if not fresh:
            return 0
        reason = _provenance(item).get("reason", "")
        body = (
            " ".join(f"@{self._callsign_of(slot)}" for slot in fresh)
            + f" {self._callsign_of(record.requester)} asks {record.department} for work with {record.tool_id}: "
            f"\"{item.title}\". Reason: {reason}. Work item {item.id}. To take it, reply in this thread with "
            f"[CLAIM_WORK {item.id}]. If it is not yours to do, reply with [DECLINE_WORK {item.id}] and your reason, "
            f"then [/DECLINE_WORK]. The first claim wins; it expires {max(1, self._ttl_seconds // 3600)} h after it was asked."
        )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the notice of work item %s; its TTL is the backstop", record.department, item.id[:8])
                return 0
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Work request] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=len(fresh),
            )
        except Exception:
            logger.warning("AD-1347: the notice of work item %s was not posted; its TTL is the backstop", item.id[:8], exc_info=True)
            return 0
        return len(fresh)

    async def _post(self, item: WorkItem, record: AgentWorkRecord, body: str) -> bool:
        """Post in the thread the work was asked in; with none (a proactive thought, a pruned or locked thread), in the
        department channel of the work. Authored by the Ship's Computer; the text names who did what. Never raises."""
        thread_id = _origin_thread(item)
        if thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=thread_id, author_id=SHIP_COMPUTER_ID, body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
                )
                return True
            except Exception:
                logger.info(
                    "AD-1347: thread %s could not take the post for work item %s; it goes to the %s channel",
                    thread_id[:8], item.id[:8], record.department, exc_info=True,
                )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the post of work item %s; it was not posted", record.department, item.id[:8])
                return False
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Agent work] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
            )
            return True
        except Exception:
            logger.warning("AD-1347: the post for work item %s was not made", item.id[:8], exc_info=True)
            return False


async def resume_agent_work(runtime: Any, item: Any) -> bool:
    """AD-855's resume of agent-created work: through its runner, never the WorkItemRouter (which drops it). False for
    any other item, which AD-855 resumes as before. Never raises."""
    if read_agent_work(item) is None:
        return False
    runner = getattr(runtime, "agent_work_runner", None)
    if type(runner) is not AgentWorkRunner:
        logger.warning(
            "AD-1347: agent work item %s was resumed but no agent-work runner is wired; it stays in_progress until the "
            "next start's recovery runs it", getattr(item, "id", "?"),
        )
        return True
    await runner.resume(item.id)
    return True
```

### 7.10 `src/probos/agent_work_tags.py` (M2: claims and declines reach the runner; the tags are taught)

Pair 1 of 3 (import):

SEARCH:
```python
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.agent_work_runner import AgentWorkRunner
from probos.crew_profile import Rank

logger = logging.getLogger(__name__)
```

Pair 2 of 3 (teaching):

SEARCH:
```python
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict."
)
```
REPLACE:
```python
    "The result is posted where you asked. A colleague's report is evidence to check, not a verdict.\n"
    "When the Ship's Computer asks your department to take a request, reply [CLAIM_WORK <work item id>] to take it, "
    "or [DECLINE_WORK <work item id>] <your reason> [/DECLINE_WORK] when it is not yours to do. The first claim wins."
)
```

Pair 3 of 3 (the runner):

SEARCH:
```python
async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
    return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action
```
REPLACE:
```python
async def _claim_or_decline(tag: AgentWorkTag, *, runtime: Any, actor: str) -> tuple[str, dict[str, Any]]:
    """Claims and declines are run by the Ship's Computer's runner (S3); without one nothing changes."""
    runner = getattr(runtime, "agent_work_runner", None)
    verb = "claimed" if tag.action == ACTION_CLAIM else "declined"
    if type(runner) is not AgentWorkRunner:
        action = {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": "unavailable"}
        return _ack(f"work item {tag.work_item_id[:8]} was not {verb}: claims are not taken on this vessel yet"), action
    if tag.action == ACTION_CLAIM:
        outcome, said = await runner.claim(actor, tag.work_item_id)
    else:
        outcome, said = await runner.decline(actor, tag.work_item_id, tag.reason)
    return _ack(said), {"type": "agent_work", "action": tag.action, "work_item_id": tag.work_item_id, "outcome": outcome}
```

### 7.11 `src/probos/cognitive/capability_gap_driver.py` (M2: an agent-work item resumes through its runner)

SEARCH:
```python
        from probos.cognitive.turn_promotion import (
            is_promoted_turn,
            resume_promoted_turn,
        )

        if is_promoted_turn(updated):
```
REPLACE:
```python
        from probos.agent_work_runner import resume_agent_work
        from probos.cognitive.turn_promotion import (
            is_promoted_turn,
            resume_promoted_turn,
        )

        # AD-1347 S3: agent-created work is not dispatchable; its runner runs it again (the router would drop it).
        if await resume_agent_work(self._runtime, updated):
            return
        if is_promoted_turn(updated):
```

### 7.12 `src/probos/routers/capability_requests.py` (M2: an agent-work approval is its own fulfilment)

Pair 1 of 2 (import):

SEARCH:
```python
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
```
REPLACE:
```python
from probos.agent_work_runner import agent_work_approval  # AD-1347 S3 (no cognitive import at module scope)
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import (
```

Pair 2 of 2 (the branch):

SEARCH:
```python
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
```
REPLACE:
```python
    if agent_work_approval(decided) is not None:
        # AD-1347 S3 (#1627): one tool call in one agent-created work item. The approval is its own fulfilment:
        # FULFILLED resumes the parked item (AD-855), whose next run makes that call once (the runner consumes the
        # approval). A denial does nothing here: AD-855 cancels the item on the DECIDED event.
        if not approve:
            return False
        return await store.mark_fulfilled(decided.id) is not None
    if not approve:
        return False
    fulfiller = _APPROVAL_FULFILLERS.get(decided.kind)
```

### 7.13 `src/probos/runtime.py` (M2)

Pair 1 of 3:

SEARCH:
```python
    from probos.agent_work import AgentWorkService  # AD-1347 S1
```
REPLACE:
```python
    from probos.agent_work import AgentWorkService  # AD-1347 S1
    from probos.agent_work_runner import AgentWorkRunner  # AD-1347 S3
```

Pair 2 of 3:

SEARCH:
```python
    agent_work: "AgentWorkService | None"  # AD-1347 S1: built in start() only when agent_work.enabled; released with the store
```
REPLACE:
```python
    agent_work: "AgentWorkService | None"  # AD-1347 S1: built in start() only when agent_work.enabled; released with the store
    agent_work_runner: "AgentWorkRunner | None"  # AD-1347 S3: built in finalize only with agent_work; stopped before the store
```

Pair 3 of 3:

SEARCH:
```python
        # AD-1347 S1: the service that owns agent-created work; built in start() only when agent_work.enabled
        self.agent_work: "AgentWorkService | None" = None
```
REPLACE:
```python
        # AD-1347 S1: the service that owns agent-created work; built in start() only when agent_work.enabled
        self.agent_work: "AgentWorkService | None" = None
        # AD-1347 S3: the Ship's Computer runner of agent-created work; built in finalize only with the service
        self.agent_work_runner: "AgentWorkRunner | None" = None
```

### 7.14 `src/probos/startup/finalize.py` (M2)

Pair 1 of 2 (the wiring function):

SEARCH:
```python
    logger.info("AD-846: task-completion Captain-DM notifier wired")
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
```
REPLACE:
```python
    logger.info("AD-846: task-completion Captain-DM notifier wired")
    return True


def _wire_agent_work_runner(*, runtime: Any) -> bool:
    """AD-1347 S3 (#1627): build the Ship's Computer runner of agent-created work and subscribe it to the work store.

    Only while ``runtime.agent_work`` is the real service (agent_work.enabled built it). The runner needs the Ward Room
    to report, the tool registry to claim through, the capability-request store and AD-855's driver to park on the
    Captain's decision, and an LLM client to run; with any missing it is not built and the reason is logged
    (log-and-degrade: agent-created work is still filed, and a later start's recovery runs it).
    """
    from probos.agent_work import AgentWorkService

    if type(getattr(runtime, "agent_work", None)) is not AgentWorkService:
        return False
    needed = (
        "work_item_store", "ward_room", "tool_registry", "capability_request_store", "capability_gap_driver",
        "llm_client", "callsign_registry", "registry",
    )
    missing = [name for name in needed if getattr(runtime, name, None) is None]
    add_listener = getattr(runtime, "add_event_listener", None)
    if missing or add_listener is None:
        logger.warning(
            "AD-1347: agent_work is on but its runner is not built (missing: %s); agent-created work is filed and "
            "not run", ", ".join(missing) or "add_event_listener",
        )
        return False
    from probos.agent_work_runner import AgentWorkRunner
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    registry = runtime.registry
    callsigns = runtime.callsign_registry

    def callsign_of(slot_id: str) -> str:
        agent = registry.get(slot_id)
        callsign = callsigns.get_callsign(agent.agent_type) if agent is not None else ""
        return callsign or slot_id

    approval_inbox = getattr(runtime.config, "approval_inbox", None)
    runner = AgentWorkRunner(
        service=runtime.agent_work, store=runtime.work_item_store, ward_room=runtime.ward_room,
        tools=runtime.tool_registry, requests=runtime.capability_request_store, parking=runtime.capability_gap_driver,
        executor=WorkItemAgenticExecutor(llm_client=runtime.llm_client), runtime=runtime, agents=registry,
        callsign_of=callsign_of, max_pending=int(getattr(approval_inbox, "max_pending_per_agent", 20)),
        ttl_seconds=runtime.config.agent_work.ttl_seconds,
    )
    add_listener(
        runner.on_store_event, event_types=["work_item_created", "work_item_claimed", "work_item_status_changed"],
    )
    runtime.agent_work_runner = runner
    return True


def _wire_workspace_ontology(*, runtime: Any, config: "SystemConfig") -> bool:
```

Pair 2 of 2 (the call, after the gap driver and the notifiers):

SEARCH:
```python
            if _wire_task_completion_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-846: task-completion Captain-DM notifier wired "
                    "during finalization"
                )
```
REPLACE:
```python
            if _wire_task_completion_notifier(runtime=runtime, config=config):
                logger.info(
                    "AD-846: task-completion Captain-DM notifier wired "
                    "during finalization"
                )

            # AD-1347 S3 (#1627): the runner of agent-created work, after AD-855's driver (it parks on it). Only with
            # the agent_work service; recover() runs what a previous start left unfinished and sends owed notices.
            if _wire_agent_work_runner(runtime=runtime):
                await runtime.agent_work_runner.recover()
                logger.info("AD-1347: agent-work runner wired during finalization")
```

### 7.15 `src/probos/startup/shutdown.py` (M2)

SEARCH:
```python
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
        runtime.agent_work = None  # AD-1347 S1: the service holds the store; released with it
```
REPLACE:
```python
        work_runner = getattr(runtime, "agent_work_runner", None)
        if work_runner is not None:
            with steps("agent work runner stop", work_runner):
                await work_runner.stop()
            runtime.agent_work_runner = None  # AD-1347 S3: its runs end before the store they write closes
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
        runtime.agent_work = None  # AD-1347 S1: the service holds the store; released with it
```

### 7.16 `tests/fixtures/ad1343_seam_registry.py` (M2)

Pair 1 of 2:

SEARCH:
```python
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
}
```
REPLACE:
```python
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
    # AD-1347 S3: agent-created work; execution_allowed (the stop, no count) before each run, then the run entry.
    ("src/probos/startup/finalize.py", "_wire_agent_work_runner"): "agent-work eligibility, then the run entry",
}
```

Pair 2 of 2:

SEARCH:
```python
        "work an agent creates for itself or requests from a colleague (AD-1347); its claim is a tool call (SEAM_TOOL)",
```
REPLACE:
```python
        "work an agent creates for itself or requests from a colleague (AD-1347); its claim is a tool call (SEAM_TOOL) "
        "and its run a new agentic run (SEAM_AGENTIC_RUN)",
```

### 7.17 `tests/test_ad1156_plan_execute_mode.py` (M2: the never-ran set)

SEARCH:
```python
    never_ran = getattr(agentic_dispatch, "_NEVER_RAN_REFUSALS", frozenset())
    assert never_ran == {_REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL}
```
REPLACE:
```python
    never_ran = getattr(agentic_dispatch, "_NEVER_RAN_REFUSALS", frozenset())
    # AD-1347 S3: a confined call that was filed or refused never ran either.
    assert never_ran == {
        _REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL,
        agentic_dispatch.CONFINED_CALL_FILED, agentic_dispatch.CONFINED_CALL_NOT_FILED,
    }
```

### 7.18 `tests/test_issue1419_failed_start_rollback.py` (M2: one more stopped component)

SEARCH:
```python
    ("persistent_task_store", "persistent task store stop"),
    ("work_item_store", "workforce store stop"),
    ("build_dispatcher", "build dispatcher stop"),
```
REPLACE:
```python
    ("persistent_task_store", "persistent task store stop"),
    ("agent_work_runner", "agent work runner stop"),  # AD-1347 S3: before the store its runs write
    ("work_item_store", "workforce store stop"),
    ("build_dispatcher", "build dispatcher stop"),
```

### 7.19 `tests/test_ad1347_s1_agent_work.py` (M2: two docstring sentences; no behaviour)

Pair 1 of 2:

SEARCH:
```python
S2 and S3 extend ``test_request_is_created_published_and_claimed_by_an_eligible_member`` into acceptance 2's chain.
"""
```
REPLACE:
```python
Acceptance 2's whole chain (tag, item, notice, claim, run, report) is ``tests/test_ad1347_s3_execution.py`` X1.
"""
```

Pair 2 of 2:

SEARCH:
```python
    S2 and S3 extend this test into acceptance 2's chain: the chain tag before creation; the activation notice, the
    execution with event_log_query and the post in the origin thread after the claim.
```
REPLACE:
```python
    The whole chain, from the tag before creation to the post in the origin thread after the run, is
    tests/test_ad1347_s3_execution.py X1.
```

### 7.20 New file: `tests/test_ad1347_s3_execution.py` (M2)

```python
"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work, parks it on the Captain's decision and reports it.

Real objects: ``WorkItemStore``, ``CapabilityRequestStore``, ``WardRoomService``, ``EventLog``, ``ToolRegistry`` with
``event_log_query`` and the work pull tools registered by their production functions, ``ToolPermissionStore``,
``AgentStopService``, ``VesselOntologyService``, ``AgentRegistry``, ``TrustNetwork``, AD-855's ``CapabilityGapDriver``,
the approval route's ``decide_capability_request``, the real ``WardRoomPostPipeline`` and extractor, and the real
``WorkItemAgenticExecutor`` driven by a scripted model. The stores' events are captured and delivered by ``_pump`` as
the runtime's listeners deliver them. On today's tree every test fails at import (``probos.agent_work_runner``).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agent_stop import AgentStopService
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkService, open_agent_work_service
from probos.agent_work_runner import AGENT_WORK_READ_TOOL_IDS, AgentWorkRunner
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import agentic_dispatch
from probos.cognitive.agent_mode import PLAN_MODE_TOOL_IDS
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_FILED,
    CONFINED_CALL_NOT_FILED,
    ToolCallConfinement,
    WorkItemAgenticExecutor,
    classify_tool_fault_error,
)
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.crew_directory import RuntimeCrewDirectory
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.config import AgentWorkConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.ontology import VesselOntologyService
from probos.proactive import ProactiveCognitiveLoop
from probos.routers.capability_requests import decide_capability_request
from probos.runtime import ProbOSRuntime
from probos.startup.communication import _register_event_log_query_tool, _register_work_item_pull_tools
from probos.substrate.event_log import EventLog
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from probos.workforce import BookableResource, WorkItemStore
from tests.test_ad1347_s1_agent_work import CREW, ENSIGNS, LIFT_REASON, RANKS, REASON, STOP_REASON, WIRED, _SlotIdentities
from tests.test_ad1347_s2_chain_tags import REQUEST, _loop_runtime, _posts
from tests.test_ad864_crew_assignment import _make_registry

_REPO = Path(__file__).resolve().parents[1]
CALLSIGNS = {
    "laforge-1": "LaForge", "forge-1": "Forge", "forge-2": "Rookie", "worf-1": "Worf", "rahda-1": "Rahda",
    "bones-1": "Bones", "pulaski-1": "Pulaski", "ogawa-1": "Ogawa", "numberone-1": "Riker",
}
WINDOW = {"start_time": "2026-10-23T00:00:00Z", "end_time": "2026-10-23T01:00:00Z", "category": "agent_stop"}
ANSWER = "Two stop orders in the window, both lifted."
PRESENTATION = ToolResultPresentation(render_complete=repr)


class _ScriptedClient:
    """The model, scripted: a response, or an async callable that returns one (as tests/test_ad1187_agent_work_pull.py)."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        return await response(request) if callable(response) else response


def _call(tool_id: str, params: dict[str, Any], call_id: str = "c1") -> LLMResponse:
    return LLMResponse(content="", tokens_used=1, content_blocks=[ToolUseBlock(ToolCallRequest(name=tool_id, arguments=params, id=call_id))])


def _final(text: str = ANSWER) -> LLMResponse:
    return LLMResponse(content=text, tokens_used=1, content_blocks=[TextBlock(text)])


class _Survey:
    """A tool outside the read set that counts its runs (hull_survey, engineering)."""

    tool_id = "hull_survey"
    name = "Hull survey"
    tool_type = ToolType.INFRA_SERVICE
    description = "Reads the hull sensors and writes a survey record."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self) -> None:
        self.calls = 0

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(output="Hull integrity 98 percent; survey record written.")


@dataclass
class _Rig:
    service: AgentWorkService
    store: WorkItemStore
    tools: ToolRegistry
    permissions: ToolPermissionStore
    stops: AgentStopService
    agents: dict[str, Any]
    wr: Any
    requests: Any
    driver: Any
    runner: AgentWorkRunner
    llm: _ScriptedClient
    survey: _Survey
    runtime: Any
    pipeline: Any
    work_events: list[tuple[Any, dict[str, Any]]]
    request_events: list[tuple[Any, dict[str, Any]]]
    data: Path


@contextlib.asynccontextmanager
async def _rig(
    tmp_path: Path, script: list[Any], *, section: AgentWorkConfig | None = None,
    clock: Callable[[], float] | None = None, max_pending: int = 20,
) -> AsyncIterator[_Rig]:
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(_REPO / "config" / "ontology", ontology_dir)
    (tmp_path / "ontology-data").mkdir()
    ontology = VesselOntologyService(ontology_dir, data_dir=tmp_path / "ontology-data")
    await ontology.initialize()
    for agent_type, slot in WIRED:
        ontology.wire_agent(agent_type, slot)
    registry = await _make_registry(list(CREW))
    agents = {agent.id: agent for agent in registry.all()}
    trust = TrustNetwork()
    for slot in ENSIGNS:
        trust.create_with_prior(slot, 1.0, 3.0)
    work_events: list[tuple[Any, dict[str, Any]]] = []
    request_events: list[tuple[Any, dict[str, Any]]] = []
    permissions = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    stops = AgentStopService(data_dir=tmp_path / "stops")
    event_log = EventLog(tmp_path / "events.db")
    requests = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"), emit_event=lambda kind, data: request_events.append((kind, data)))
    wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
    runtime = object.__new__(ProbOSRuntime)  # the attributes the pull authority and the run read, as S1's _ship does
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"), tick_interval=1000.0,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        emit_event=lambda kind, data: work_events.append((kind, data)),
    )
    tools = ToolRegistry()
    survey = _Survey()
    started: list[Any] = []
    runner: AgentWorkRunner | None = None
    try:
        for agent in agents.values():
            await agent.start()
        for component in (permissions, stops, event_log, requests, wr):
            await component.start()
            started.append(component)
        tools.set_permission_store(permissions)
        tools.set_stop_gate(stops)
        _register_event_log_query_tool(tool_registry=tools, enabled=True, event_log_reader=event_log, event_log_audit_sink=event_log)
        tools.register(survey, allowed_departments=("engineering",), default_permissions=dict.fromkeys(RANKS, "read"))
        await permissions.issue_grant("forge-1", "hull_survey", ToolPermission.READ)
        runtime.config = SystemConfig()
        runtime.registry = registry
        runtime.ontology = ontology
        runtime.trust_network = trust
        runtime.tool_registry = tools
        runtime.tool_permission_store = permissions
        runtime.work_item_store = store
        runtime.event_log = event_log
        runtime.capability_request_store = requests
        runtime.intent_bus = None
        for slot, agent in agents.items():
            store.register_resource(BookableResource(resource_id=slot, agent_type=agent.agent_type, department="", capacity=5, characteristics=[]))
        await store.start()
        started.append(store)
        _register_work_item_pull_tools(tool_registry=tools, work_item_store=store, pull_resource_resolver=runtime.resolve_workforce_pull_resource)
        directory = RuntimeCrewDirectory(agent_registry=registry, ontology=ontology, trust_network=trust)
        service = await open_agent_work_service(
            config=section or AgentWorkConfig(enabled=True), store=store, tools=tools,
            identities=_SlotIdentities(agents), directory=directory, stop_gate=stops, clock=clock or time.time,
        )
        assert isinstance(service, AgentWorkService)
        runtime.agent_work = service
        driver = CapabilityGapDriver(runtime=runtime, work_item_store=store, capability_request_store=requests)
        runtime.capability_gap_driver = driver
        llm = _ScriptedClient(script)
        runner = AgentWorkRunner(
            service=service, store=store, ward_room=wr, tools=tools, requests=requests, parking=driver,
            executor=WorkItemAgenticExecutor(llm_client=llm), runtime=runtime, agents=registry,
            callsign_of=lambda slot: CALLSIGNS.get(slot, slot), max_pending=max_pending,
        )
        runtime.agent_work_runner = runner
        loop_runtime = _loop_runtime(service, trust)
        loop_runtime.ward_room = wr
        loop_runtime.agent_work_runner = runner
        loop = ProactiveCognitiveLoop(cooldown=0)
        loop.set_runtime(loop_runtime)
        router = MagicMock(spec=WardRoomRouter)
        router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
        pipeline = WardRoomPostPipeline(
            ward_room=wr, ward_room_router=router, proactive_loop=loop, trust_network=None,
            callsign_registry=None, config=MagicMock(),
        )
        yield _Rig(
            service, store, tools, permissions, stops, agents, wr, requests, driver, runner, llm, survey, runtime,
            pipeline, work_events, request_events, tmp_path,
        )
    finally:
        if runner is not None:
            await runner.stop()
        for component in reversed(started):
            await component.stop()
        for agent in agents.values():
            if agent.is_alive:
                await agent.stop()


async def _pump(rig: _Rig) -> None:
    """Deliver the stores' events as the runtime's listeners do, and wait for every run, until nothing is left."""
    for _ in range(20):
        work = list(rig.work_events)
        rig.work_events.clear()
        asked = list(rig.request_events)
        rig.request_events.clear()
        for kind, data in work:
            await rig.runner.on_store_event({"type": getattr(kind, "value", kind), "data": data})
        for kind, data in asked:
            await rig.driver.on_capability_event({"type": getattr(kind, "value", kind), "data": data})
        await asyncio.gather(*rig.runner.running)
        if not work and not asked and not rig.work_events and not rig.request_events:
            return
    raise AssertionError("the stores kept emitting")


async def _thread_in(rig: _Rig, department: str, author: str) -> Any:
    channel = await rig.wr.get_channel_by_department(department)
    return await rig.wr.create_thread(channel.id, author, "Relay drift", "The relay drifted twice.", author_callsign=CALLSIGNS[author])


def _system_posts(rig: _Rig, thread_id: str) -> list[str]:
    return [body for author, body in _posts(rig.data / "wr.db", thread_id) if author == "system"]


def _events(rig: _Rig, category: str, event: str) -> list[tuple[str, dict[str, Any]]]:
    with contextlib.closing(sqlite3.connect(rig.data / "events.db")) as raw:
        rows = raw.execute("SELECT agent_id, data FROM events WHERE category = ? AND event = ?", (category, event)).fetchall()
    return [(agent_id, json.loads(data) if data else {}) for agent_id, data in rows]


def _seen(rig: _Rig, text: str) -> bool:
    """Whether the model was shown ``text`` (in the plain or the structured transcript)."""
    for request in rig.llm.requests:
        if text in (request.prompt or "") or any(text in str(message.get("content", "")) for message in (request.messages or [])):
            return True
    return False


async def _with_tool(rig: _Rig, slot: str, tool_id: str, params: dict[str, Any]) -> Any:
    member = rig.service.crew_member(slot)
    assert member is not None, slot
    required = ToolPermission.READ if tool_id == "discover_work_items" else ToolPermission.WRITE
    return await rig.tools.check_and_invoke(
        slot, tool_id, params, required=required, agent_department=member.department, agent_rank=member.rank,
        agent_types=[member.agent_type], context={"agent_id": slot, "_tool_result_presentation": PRESENTATION},
    )


async def _request(rig: _Rig, requester: str, thread_id: str) -> str:
    created = await rig.service.request_work(
        requester, title="Read the EventLog window", description="", reason=REASON,
        origin=AgentWorkOrigin("ward_room", thread_id=thread_id), tool_id="event_log_query",
    )
    assert isinstance(created, AgentWorkCreated), created
    return created.work_item.id


# X1
async def test_a_chain_request_is_announced_claimed_run_and_reported_in_its_origin_thread(tmp_path: Path) -> None:
    """Acceptance 2: the chain tag, the item, the notice, the claim, the run with event_log_query, the post in the thread."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["pulaski-1"], response_text=f"I need the event log for that window.\n{REQUEST}",
            thread_id=origin.id, event_type="ward_room_thread_created",
        )
        [item] = await rig.store.list_agent_work(False, None, 10)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert notice.author_id == "system" and item.id in notice.body and notice.max_responders == 2
        assert "@Forge" in notice.body and "@LaForge" in notice.body
        assert "@Rookie" not in notice.body and "@Worf" not in notice.body and "@Rahda" not in notice.body
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"Taking it.\n[CLAIM_WORK {item.id}]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        await asyncio.gather(*rig.runner.running)  # the chain's claim starts the run itself
        done = await rig.store.get_work_item(item.id)
        assert done is not None and (done.status, done.assigned_to, done.created_by) == ("done", "forge-1", "pulaski-1")
        await _pump(rig)
        [booking] = await rig.store.list_bookings(work_item_id=item.id)
        assert (booking.resource_id, booking.status) == ("forge-1", "completed")
        assert any(agent == "forge-1" and data.get("outcome") == "success" for agent, data in _events(rig, "audit", "event_log_query"))
        assert any(data.get("work_item_id") == item.id and data.get("is_error") is False for _, data in _events(rig, "tool", "tool_invoked"))
        [report] = _system_posts(rig, origin.id)
        assert ANSWER in report and item.id in report and "@Pulaski" in report and "check it against the record" in report
        acks = [body for author, body in _posts(rig.data / "wr.db", notice.id) if author == "forge-1"]
        assert len(acks) == 1 and "you claimed work item" in acks[0]
        assert len(rig.llm.requests) == 2


# X2
async def test_a_call_outside_the_read_set_parks_the_item_and_an_approval_runs_it_exactly_once(tmp_path: Path) -> None:
    """Acceptance 4: filed, nothing run; approved, the item resumes and the call runs once; a repeat is filed; denied,
    the item ends and the Captain's reason reaches the origin thread."""
    script = [
        _call("hull_survey", {}), _final("Waiting for the Captain."),
        _call("hull_survey", {}, "c1"), _call("hull_survey", {}, "c2"), _final("Surveyed once."),
    ]
    async with _rig(tmp_path, script) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey the hull", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        item_id = created.work_item.id
        await _pump(rig)
        parked = await rig.store.get_work_item(item_id)
        assert parked is not None and parked.status == "blocked" and rig.survey.calls == 0
        first_id = parked.metadata["capability_request_id"]
        first = await rig.requests.get(first_id)
        assert (first.kind, first.status, first.agent_id, first.work_item_id) == ("action", "pending", "forge-1", item_id)
        assert (first.payload["tool_id"], first.payload["action"], first.payload["scope_key"]) == (
            "hull_survey", "agent_work_call", f"agent_work:{item_id}",
        )
        assert _seen(rig, CONFINED_CALL_FILED)
        captain = SimpleNamespace(capability_request_store=rig.requests)
        approved = await decide_capability_request(first_id, CapabilityRequestDecideRequest(approve=True), runtime=captain)
        assert approved["fulfilled"] is True
        await _pump(rig)
        again = await rig.store.get_work_item(item_id)
        assert rig.survey.calls == 1, "the approval admits the call it was asked for, once"
        assert again is not None and again.status == "blocked"
        second_id = again.metadata["capability_request_id"]
        assert second_id != first_id and (await rig.requests.get(second_id)).status == "pending"
        denied = await decide_capability_request(
            second_id, CapabilityRequestDecideRequest(approve=False, reason="once is enough"), runtime=captain,
        )
        assert denied["fulfilled"] is False
        await _pump(rig)
        ended = await rig.store.get_work_item(item_id)
        assert ended is not None and ended.status == "cancelled" and rig.survey.calls == 1
        [report] = _system_posts(rig, origin.id)
        assert "once is enough" in report and "@Forge" in report


# X3
@pytest.mark.parametrize("cause", ["stop_before_run", "restricted_before_run", "stop_during_run"])
async def test_a_claimant_that_may_not_run_returns_the_request_to_the_board_unclaimed(tmp_path: Path, cause: str) -> None:
    """Acceptance 5 and blind spot 7: never failed; the booking is cancelled; the member may claim it again once allowed."""
    holder: dict[str, Any] = {}

    async def _stop_then_read(request: LLMRequest) -> LLMResponse:
        await holder["rig"].stops.issue_stop("forge-1", reason=STOP_REASON)
        return _call("event_log_query", WINDOW)

    script = [_stop_then_read, _final("partial")] if cause == "stop_during_run" else []
    async with _rig(tmp_path, script) as rig:
        holder["rig"] = rig
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        claim = await _with_tool(rig, "forge-1", "claim_work_item", {"work_item_id": item_id})
        assert ast.literal_eval(claim.output)["owned"] is True
        restriction = None
        if cause == "stop_before_run":
            await rig.stops.issue_stop("forge-1", reason=STOP_REASON)
        elif cause == "restricted_before_run":
            restriction = await rig.permissions.issue_grant("forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True)
        await _pump(rig)  # WORK_ITEM_CLAIMED starts the run
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert [booking.status for booking in await rig.store.list_bookings(work_item_id=item_id)] == ["cancelled"]
        assert _system_posts(rig, origin.id) == []
        if cause == "stop_during_run":
            [stop] = rig.stops.active()
            assert rig.stops.refused_counts(stop.stop_id) == {"tool": 1}
        else:
            assert rig.llm.requests == []
        if restriction is not None:
            await rig.permissions.revoke_grant(restriction.id)
        else:
            await rig.stops.lift_stop("forge-1", reason=LIFT_REASON)
        discovered = await _with_tool(rig, "forge-1", "discover_work_items", {})
        assert item_id in [entry["id"] for entry in ast.literal_eval(discovered.output)["items"]]


# X4
async def test_every_watcher_of_a_deduplicated_request_gets_the_report(tmp_path: Path) -> None:
    """Blind spot 6: dedup must not drop a watcher's answer."""
    async with _rig(tmp_path, [_call("event_log_query", WINDOW), _final()]) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        other = await _thread_in(rig, "medical", "ogawa-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", other.id) == item_id
        await _pump(rig)
        assert (await rig.runner.claim("forge-1", item_id))[0] == "claimed"
        await _pump(rig)
        [report] = _system_posts(rig, origin.id)
        assert "@Pulaski" in report and "@Ogawa" in report and ANSWER in report
        assert await rig.service.terminal_notices_due() == ()


# X5
async def test_an_expired_request_tells_each_recipient_once_across_two_overlapping_deliveries(tmp_path: Path) -> None:
    section = AgentWorkConfig(enabled=True, ttl_seconds=60)
    async with _rig(tmp_path, [], section=section, clock=lambda: time.time() - 120) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        assert await _request(rig, "ogawa-1", origin.id) == item_id
        assert await rig.store.transition_work_item(item_id, "cancelled", source="ttl_expiry") is not None  # as the sweep does
        told = await asyncio.gather(rig.runner.deliver_due_notices(), rig.runner.deliver_due_notices())
        assert sorted(told) == [0, 2]
        await _pump(rig)
        [notice] = _system_posts(rig, origin.id)
        assert "expired before anyone produced a result" in notice and "@Pulaski" in notice and "@Ogawa" in notice
        engineering = await rig.wr.get_channel_by_department("engineering")
        assert await rig.wr.list_threads(engineering.id) == []  # an ended request is not announced


# X6
async def test_two_overlapping_starts_run_an_item_once(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await asyncio.gather(rig.runner.resume(created.work_item.id), rig.runner.resume(created.work_item.id))
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"
        assert len(rig.llm.requests) == 1 and len(_system_posts(rig, origin.id)) == 1


# X7
async def test_a_decline_is_recorded_once_and_its_reason_reaches_the_requester(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        assert await rig.pipeline.process_and_post(
            agent=rig.agents["forge-1"], response_text=f"[DECLINE_WORK {item_id}]\nOn the warp core all shift.\n[/DECLINE_WORK]",
            thread_id=notice.id, event_type="ward_room_thread_created",
        )
        assert (await rig.runner.decline("forge-1", item_id, "again"))[0] == "repeated"
        assert (await rig.runner.decline("worf-1", item_id, "not mine"))[0] == "refused"
        [relay] = _system_posts(rig, origin.id)
        assert "declined" in relay and "warp core" in relay and "@Pulaski" in relay
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)


# X8
async def test_an_ensign_or_another_department_cannot_claim_through_the_chain(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        origin = await _thread_in(rig, "medical", "bones-1")
        item_id = await _request(rig, "pulaski-1", origin.id)
        await _pump(rig)
        engineering = await rig.wr.get_channel_by_department("engineering")
        [notice] = await rig.wr.list_threads(engineering.id)
        for slot in ("forge-2", "worf-1"):
            await rig.pipeline.process_and_post(
                agent=rig.agents[slot], response_text=f"Mine.\n[CLAIM_WORK {item_id}]",
                thread_id=notice.id, event_type="ward_room_thread_created",
            )
        posts = dict(_posts(rig.data / "wr.db", notice.id))
        assert "was not claimed by you" in posts["worf-1"]
        assert "Ship's Computer" not in posts.get("forge-2", "")  # an ensign's tag is stripped and nothing is done
        item = await rig.store.get_work_item(item_id)
        assert item is not None and (item.status, item.assigned_to) == ("open", None)
        assert rig.runner.running == ()


# X9
@pytest.mark.parametrize(("verdict", "expected"), [
    ("admit", None), ("filed", CONFINED_CALL_FILED), ("refused", CONFINED_CALL_NOT_FILED), ("anything", CONFINED_CALL_NOT_FILED),
])
async def test_the_confinement_gate_decides_every_call_outside_its_set(verdict: str, expected: str | None) -> None:
    async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
        return verdict

    result = await ToolCallConfinement(frozenset({"event_log_query"}), gate).refuse_or_admit("forge-1", "hull_survey", {})
    assert (result.error if result is not None else None) == expected


async def test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome() -> None:
    async def broken(agent_id: str, tool_id: Any, params: Any) -> str:
        raise RuntimeError("store down")

    result = await ToolCallConfinement(frozenset({"event_log_query"}), broken).refuse_or_admit("forge-1", "hull_survey", {})
    assert result is not None and result.error == CONFINED_CALL_NOT_FILED
    for text in (CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED):
        assert text in agentic_dispatch._NEVER_RAN_REFUSALS
        assert not is_capability_gap(text)
        assert classify_tool_fault_error(text) == "permission_denied"
    for tool_ids, gate in ((frozenset(), broken), ({"x"}, broken), (frozenset({"x"}), "not callable")):
        with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
            ToolCallConfinement(tool_ids, gate)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
        await WorkItemAgenticExecutor(llm_client=_ScriptedClient([])).run(
            agent_id="forge-1", instructions="", task_text="x", runtime=SimpleNamespace(),
            plan_mode_tool_ids=frozenset({"event_log_query"}), confinement=ToolCallConfinement(frozenset({"x"}), broken),
        )
    assert AGENT_WORK_READ_TOOL_IDS <= PLAN_MODE_TOOL_IDS
    assert not AGENT_WORK_READ_TOOL_IDS & {"web_search", "read_page", "http_fetch", "discover_work_items"}


# X10
async def test_a_full_approval_inbox_refuses_the_call_without_filing_it(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_call("hull_survey", {}), _final()], max_pending=0) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Survey", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        await _pump(rig)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done" and rig.survey.calls == 0
        assert rig.requests.count_pending_sync("forge-1") == 0
        assert _seen(rig, CONFINED_CALL_NOT_FILED)


# X11
async def test_recover_runs_work_a_previous_start_left_unfinished(tmp_path: Path) -> None:
    async with _rig(tmp_path, [_final()]) as rig:
        origin = await _thread_in(rig, "engineering", "laforge-1")
        created = await rig.service.create_self_task(
            "forge-1", title="Read the log", description="", reason=REASON, origin=AgentWorkOrigin("ward_room", thread_id=origin.id),
        )
        assert isinstance(created, AgentWorkCreated)
        rig.work_events.clear()  # the created event was lost with the previous start
        assert await rig.runner.recover() == 1
        await asyncio.gather(*rig.runner.running)
        done = await rig.store.get_work_item(created.work_item.id)
        assert done is not None and done.status == "done"


# X12
async def test_an_ordinary_item_still_resumes_through_the_work_item_router(tmp_path: Path) -> None:
    async with _rig(tmp_path, []) as rig:
        dispatched: list[str] = []

        class _Router:
            async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
                dispatched.append(wi["id"])
                return True

            def is_dispatchable(self, wi: dict[str, Any]) -> bool:
                return True

        rig.runtime.work_item_router = _Router()
        plain = await rig.store.create_work_item(title="Plain task", assigned_to="forge-1")
        asked = await rig.requests.file_request(agent_id="forge-1", kind="continue", target="continue", work_item_id=plain.id)
        assert await rig.driver.block_on_request(work_item_id=plain.id, request_id=asked.id, reason="waiting")
        await rig.requests.decide(asked.id, True)
        await rig.requests.mark_fulfilled(asked.id)
        await _pump(rig)
        assert dispatched == [plain.id]
        assert rig.llm.requests == [] and rig.runner.running == ()
```

### 7.21 New file: `tests/test_ad1347_s3_wiring.py` (M2)

```python
"""AD-1347 S3 (#1627): finalize builds the agent-work runner only with the service, and shutdown releases it.

Real boots, as ``tests/test_ad1347_s1_wiring.py`` (its config and its two fixtures: the Ship's Archive off, the local
embedding backend).
"""

from __future__ import annotations

from pathlib import Path

from probos.agent_work import AgentWorkService
from probos.agent_work_runner import AgentWorkRunner
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from tests.test_ad1347_s1_wiring import (  # noqa: F401  (fixtures are found by name)
    _assert_no_embedding_model_loaded,
    _boot_config,
    archive_resolutions,
    local_embeddings,
)


def _config(*, enabled: bool) -> SystemConfig:
    """S1's boot shape with the Ward Room on: the runner posts its notices and reports there, and finalize wires AD-855's driver only with it."""
    config = _boot_config(enabled=enabled)
    config.ward_room.enabled = True
    return config


# W3
async def test_the_runner_is_wired_only_with_the_service_and_released_at_stop(
    tmp_path: Path, archive_resolutions: list[object], local_embeddings: Path,
) -> None:
    off = ProbOSRuntime(config=_config(enabled=False), data_dir=tmp_path / "off", llm_client=MockLLMClient())
    await off.start()
    try:
        assert off.agent_work is None and off.agent_work_runner is None
    finally:
        await off.stop()
    on = ProbOSRuntime(config=_config(enabled=True), data_dir=tmp_path / "on", llm_client=MockLLMClient())
    await on.start()
    try:
        assert isinstance(on.agent_work, AgentWorkService)
        assert on.capability_gap_driver is not None and on.capability_request_store is not None and on.ward_room is not None, (
            "premise: the runner's collaborators exist on this boot"
        )
        assert isinstance(on.agent_work_runner, AgentWorkRunner)
    finally:
        await on.stop()
    assert on.agent_work_runner is None, "a clean stop releases the runner"
    assert archive_resolutions == []
    _assert_no_embedding_model_loaded(local_embeddings)
```

W3 boots through `_config`, S1's boot shape with the Ward Room on. On S1's own boot config the Ward Room is off, so finalize wires neither AD-855's driver nor anything else inside its `if runtime.ward_room:` block, and the premise assertion fails (shown by execution, 2026-10-23); with it on, the runner and its collaborators exist. The test's assertions are unchanged.

## 8. Tracking (in M2's commit, or a docs-only commit after it)

Set the date to the commit date. Both anchors survive wave 2's entries.

**`PROGRESS.md`** (title plus blank line; occurs once):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**AD-1347 S2 and S3 (2026-10-23), #1627 slices 2 and 3 of 4, closing AD-1347 -- crew file, claim and run governed work from the cognitive chain, read-only by default, with the Captain's approval for anything else, and the result is posted where it was asked.** New `probos/agent_work_tags.py`: one parser for `[SELF_TASK]`, `[REQUEST_WORK]`, `[CLAIM_WORK]` and `[DECLINE_WORK]`, acted on in `ProactiveCognitiveLoop._extract_and_execute_actions` (proactive thoughts and every Ward Room reply, whose pipeline now passes its thread and post), Lieutenant and above, at most 3 per reply, each acknowledged in the agent's own reply; the compose step teaches the tags only while `agent_work` is on (byte-identical off). New `probos/agent_work_runner.py` (`AgentWorkRunner`, wired in finalize only with the service): announces each request once to each eligible member in its department's channel; claims through the tool sink; runs each item in its assignee's agentic loop under the new `ToolCallConfinement` (read-only tools run; any other call is filed as an AD-1154 `action` request and the item parks on it through AD-855; the Captain's approval resumes it and admits that call once; a denial ends it with the reason); returns a request whose claimant may not run it to the board; reports each outcome once per requester and watcher in the origin thread. `AgentWorkService` gains `crew_member` and `execution_allowed`; the approval route fulfils agent-work approvals; AD-855 resumes agent work through its runner. The Captain's one-to-one chat is not wired (its work is the Captain's: AD-845, AD-1165). New: `tests/test_ad1347_s2_chain_tags.py`, `tests/test_ad1347_s3_execution.py` (acceptance 2 end to end), `tests/test_ad1347_s3_wiring.py`. Updated: the AD-1343 seam registry, `test_ad1156_plan_execute_mode.py`, `test_issue1419_failed_start_rollback.py`, two docstrings in `test_ad1347_s1_agent_work.py`. The contract is `prompts/ad-1347-s2-s3-chain-wiring-execution-and-report-back.md`.

```

**`DECISIONS.md`** (anchored on the next heading; occurs once):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1347 S2 and S3 -- The chain's agent-work tags, and the Ship's Computer runs, parks, resumes and reports agent-created work (2026-10-23, #1627 slices 2 and 3 of 4; closes AD-1347)

- *Scope.* One batch, two milestone commits. New `agent_work_tags.py` and `agent_work_runner.py`; `proactive.py`, `ward_room_pipeline.py`, `cognitive/sub_tasks/compose.py`, `agent_stop.py` (`S1_SCOPE` text), `agent_work.py` (two methods), `cognitive/agentic_dispatch.py` (`ToolCallConfinement`), `cognitive/capability_gap_driver.py`, `routers/capability_requests.py`, `runtime.py`, `startup/finalize.py`, `startup/shutdown.py`, tests. Contract `prompts/ad-1347-s2-s3-chain-wiring-execution-and-report-back.md`.
- *D1 (one parser).* Acted on only in the proactive action extractor, which proactive thoughts and every Ward Room reply already reach; the pipeline passes the thread and post. The Captain's one-to-one chat is not wired: work found there is the Captain's (AD-845, AD-1165).
- *D2 (grammar).* Block tags with `Key: value` lines; Lieutenant and above; 3 per reply; the acknowledgement is a Ship's Computer line in the agent's own reply, so it starts no routing.
- *D3 (runs).* A runner reacts to the work store's events (created self-task or assignment, claimed request, ended item), a chain claim starts its run, and a start recovers unfinished work. Runs go through `WorkItemAgenticExecutor.run` without `admitted_turn` (the stop at `agentic_run`). A request whose claimant may not run it, before or after the run, goes back to the board unclaimed (AD-1343 S2 is not built).
- *D4 (read-only at the call).* `ToolCallConfinement`: the plan-mode read set without its off-ship reads runs; any other call is put to a gate before plan mode and the browser inbox; a gate fault refuses; the refusals never ran. The offer is not narrowed, so a write call is reachable and governed.
- *D5 (approval).* An AD-1154 `action` (`agent_work_call`, scoped to the item); AD-855 parks the item; approval is its own fulfilment; the resumed run admits that call once on a claim-once row; a denial cancels and the report reads the reason from the request. No new request kind.
- *D6 (reports).* Ship's Computer posts: the notice in the department channel (mentions, `max_responders`), the report, decline, expiry and denial in the origin thread (fallback the department channel), each notice claimed before it is sent. The store's TTL sweep stays the only expiry owner.
- *Disclosed effects.* `S1_SCOPE` names agent-created work; two refusal texts join the never-ran set; `runtime.agent_work_runner` exists (None while off); a standing rule granted on an agent-work approval is inert.
- *Reversal.* Revert both commits; open agent work stays on the board until its TTL; the AD-1154 requests filed stay in the inbox as ordinary actions with no fulfiller.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, verify with `--check` and `tests/test_ad1184_ad_ledger.py`, and commit the regenerated files with the trackers. **`docs/development/roadmap.md`:** no row (AD-1347 is not there).

## 9. What this does NOT change

- `cognitive/dm/reply_pipeline.py`: the Captain's one-to-one chat, its 24 steps, its plan-mode tables; AD-845's `[CREATE_TASK]`; AD-1165 promotion.
- `_handle_work_item_dispatch` and `_run_agentic_dispatch` (the AD-839 path).
- AD-1154's browser inbox: `_APPROVAL_INBOX_TOOL_IDS`, `_park_or_admit`, the standing-rule machinery. A standing rule can still be granted on an agent-work approval, and the gate never reads it (register R2).
- Tools:
  - no `allowed_departments` or rank change;
  - no tool registered;
  - the agent's offer is not narrowed.
- Persistence and configuration:
  - no config field (`AgentWorkConfig` is S1's);
  - no table;
  - no EventLog category or event pair;
  - no request kind.
- AD-1343: no new seam constant and no new stop-check site. AD-1346: no `decide`.
- `WorkItemStore`: no new method. The TTL sweep and the claim gate are unchanged.
- `ward_room_router.py` and the Ward Room service.
- `config/system.yaml`.

## 10. Mutation rows (53 rows; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row against the named test on the contract-applied tree, after an unmutated baseline that passes, and restore the file before the next row. None of these rows has been executed; the build's campaign is the one of record.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| T1 | `src/probos/agent_work_tags.py` | `if not tags or rank is Rank.ENSIGN:` | `if not tags:` | C6 (the ensign's self-task is filed) |
| T2 | `src/probos/agent_work_tags.py` | `if index >= MAX_TAGS_PER_REPLY:` | `if False:` | C8 (four items) |
| T3 | `src/probos/agent_work_tags.py` | `origin: AgentWorkOrigin \| None = AgentWorkOrigin("ward_room" if thread_id else "proactive", thread_id=thread_id, post_id=post_id)` | `origin: AgentWorkOrigin \| None = AgentWorkOrigin("proactive")` | C3, C12 (origin) |
| T4 | `src/probos/agent_work_tags.py` | `return service if type(service) is AgentWorkService else None` | `return service` | C5 (the double enters the path) |
| T5 | `src/probos/agent_work_tags.py` | `return AGENT_WORK_INSTRUCTIONS if agent_work_service(runtime) is not None else ""` | `return AGENT_WORK_INSTRUCTIONS` | C11 (off prompt differs) |
| T6 | `src/probos/agent_work_tags.py` | `assignee=_slot_of(runtime, tag.assignee),` | `assignee=None,` | C13 (`requester_holds_tool`) |
| T7 | `src/probos/agent_work_tags.py` | `department=tag.department or None,` | `department=None,` | C4 (security) |
| T8 | `src/probos/agent_work_tags.py` | `if created.deduplicated:` | `if False:` | C10 (no "watcher") |
| T9 | `src/probos/agent_work_tags.py` | `if type(runner) is not AgentWorkRunner:` | `if True:` | X1 (no claim) |
| P1 | `src/probos/proactive.py` | `if agent_work_service(rt) is not None:` | `if False:` | C3 |
| P2 | `src/probos/proactive.py` | `text, runtime=rt, actor=agent.id, rank=rank, thread_id=thread_id, post_id=post_id,` | `text, runtime=rt, actor=agent.id, rank=rank,` | C3 (origin proactive) |
| P3 | `src/probos/proactive.py` | `return await self._extract_and_execute_actions(agent, text, post_budget=post_budget, thread_id=thread_id, post_id=post_id)` | `return await self._extract_and_execute_actions(agent, text, post_budget=post_budget)` | C12 |
| WP1 | `src/probos/ward_room_pipeline.py` | `post_budget=budget, thread_id=thread_id, post_id=post_id or "",` | `post_budget=budget,` | C12 |
| CP1 | `src/probos/cognitive/sub_tasks/compose.py` | `if mode_key in AGENT_WORK_COMPOSE_MODES:` | `if True:` | C11 (dm_response taught) |
| S1 | `src/probos/agent_work.py` | `return self._directory.member(ref.slot_id) if ref is not None else None` | `return None` | X1 (claim refused) |
| S2 | `src/probos/agent_work.py` | `if member is None or self._stopped_now(member.slot_id):` | `if member is None:` | X3 stop_before_run (the run starts) |
| S3 | `src/probos/agent_work.py` | `return member.department == record.department and record.tool_id is not None and self._holds_tool(member, record.tool_id)` | `return True` | X3 restricted_before_run |
| A1 | `src/probos/cognitive/agentic_dispatch.py` | `if confinement is not None and tool_id not in confinement.tool_ids:` | `if False:` | X2 (the survey runs at once) |
| A2 | `src/probos/cognitive/agentic_dispatch.py` | `executor.confine_calls(confinement)` | `pass` | X2 |
| A3 | `src/probos/cognitive/agentic_dispatch.py` | `arguments["confinement"] = confinement` | `pass` | X2 |
| A4 | `src/probos/cognitive/agentic_dispatch.py` | `{_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL, CONFINED_CALL_FILED, CONFINED_CALL_NOT_FILED}` | `{_DEFERRED_SCHEMA_REFUSAL, _PLAN_MODE_TOOL_REFUSAL}` | X9b; `tests/test_ad1156_plan_execute_mode.py` |
| A5 | `src/probos/cognitive/agentic_dispatch.py` | `verdict = CONFINEMENT_REFUSED` | `verdict = CONFINEMENT_ADMIT` | X9b (the broken gate admits) |
| A6 | `src/probos/cognitive/agentic_dispatch.py` | `if verdict == CONFINEMENT_ADMIT:` | `if True:` | X9 |
| A7 | `src/probos/cognitive/agentic_dispatch.py` | `type(confinement) is not ToolCallConfinement or plan_mode_tool_ids is not None` | `type(confinement) is not ToolCallConfinement` | X9b |
| R1 | `src/probos/agent_work_runner.py` | `if item.status in TERMINAL_STATUSES:` | `if False:` | X1 (no report) |
| R2 | `src/probos/agent_work_runner.py` | `await self._announce(item, record)` | `pass` | X1 (no notice) |
| R3 | `src/probos/agent_work_runner.py` | `elif kind == EventType.WORK_ITEM_CREATED.value or record.kind == KIND_REQUEST:` | `elif kind == EventType.WORK_ITEM_CREATED.value:` | X3 (the claimed request is not released) |
| R4 | `src/probos/agent_work_runner.py` | `if member.department != record.department or member.slot_id == record.requester:` | `if member.slot_id == record.requester:` | X1 (`@Worf`) |
| R5 | `src/probos/agent_work_runner.py` | `body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=len(fresh),` | `body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=0,` | X1 |
| R6 | `src/probos/agent_work_runner.py` | `if claimed_item is None or claimed_item.assigned_to != member.slot_id:` | `if claimed_item is None:` | X8 (Worf is told he claimed it) |
| R7 | `src/probos/agent_work_runner.py` | `self._start(claimed_item.id)` | `pass` | X1 (not done before the pump) |
| R8 | `src/probos/agent_work_runner.py` | `if not await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_DECLINE, self._clock()):` | `if False:` | X7 (a second relay) |
| R9 | `src/probos/agent_work_runner.py` | `or item.status != "open" or member.department != record.department` | `or item.status != "open"` | X7 (Worf's decline is accepted) |
| R10 | `src/probos/agent_work_runner.py` | `claimed = [notice.recipient for notice in notices if await self._service.claim_notice(work_item_id, notice.recipient)]` | `claimed = [notice.recipient for notice in notices]` | X5 (two posts) |
| R11 | `src/probos/agent_work_runner.py` | `if outcome == OUTCOME_EXPIRED:` | `if False:` | X5 ("expired") |
| R12 | `src/probos/agent_work_runner.py` | `if denial:` | `if False:` | X2 (the reason) |
| R13 | `src/probos/agent_work_runner.py` | `return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]` | `return "no reason recorded"` | X2 |
| R14 | `src/probos/agent_work_runner.py` | `await self._store.unassign_work_item(item.id, reason="the claimant may not run it now")` | `pass` | X3 before_run cases (status scheduled) |
| R15 | `src/probos/agent_work_runner.py` | `if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):` | `if False:` | X3 stop_during_run (done, not open) |
| R16 | `src/probos/agent_work_runner.py` | `await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)` | `pass` | X2 (not blocked) |
| R17 | `src/probos/agent_work_runner.py` | `item.id, "done", source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},` | `item.id, "done", source=RUN_SOURCE, expected_status="in_progress",` | X1 (no answer in the report) |
| R18 | `src/probos/agent_work_runner.py` | `if completed and booking.status in ("active", "scheduled"):` | `if False:` | X1 (booking cancelled) |
| R19 | `src/probos/agent_work_runner.py` | `return CONFINEMENT_ADMIT` | `return CONFINEMENT_FILED` | X2 (the survey never runs) |
| R20 | `src/probos/agent_work_runner.py` | `if self._requests.count_pending_sync(agent_id) >= self._max_pending:` | `if False:` | X10 (a request is filed) |
| R21 | `src/probos/agent_work_runner.py` | `filed.append(request.id)` | `pass` | X2 (not parked) |
| R22 | `src/probos/agent_work_runner.py` | `if type(origin) is not dict or origin.get("channel") != "ward_room":` | `if True:` | X1 (the report goes to the department channel) |
| R23 | `src/probos/agent_work_runner.py` | `await runner.resume(item.id)` | `pass` | X2 (no resume) |
| R24 | `src/probos/agent_work_runner.py` | `if read_agent_work(item) is None:` | `if False:` | X12 (the router is not called) |
| G1 | `src/probos/cognitive/capability_gap_driver.py` | `if await resume_agent_work(self._runtime, updated):` | `if False:` | X2 |
| F1 | `src/probos/routers/capability_requests.py` | `if agent_work_approval(decided) is not None:` | `if False:` | X2 (`fulfilled` False) |
| F2 | `src/probos/routers/capability_requests.py` | `return await store.mark_fulfilled(decided.id) is not None` | `return False` | X2 |
| W1 | `src/probos/startup/finalize.py` | `if type(getattr(runtime, "agent_work", None)) is not AgentWorkService:` | `if False:` | W3 (the off boot builds a runner with no service and fails) |
| SD1 | `src/probos/startup/shutdown.py` | `await work_runner.stop()` | `pass` | `tests/test_issue1419_failed_start_rollback.py::test_a_rollback_with_no_failed_step_asks_each_component_once_and_closes_nothing` |

Row T3's Line cell escapes the union bar (`\|`) for the Markdown table; the source line has a plain `|`. X9b is `test_a_failing_gate_refuses_and_every_refusal_is_a_never_ran_policy_outcome`.

## 11. Verified Against Codebase (2026-10-23, worktree `s23-consult` at `6b950acf`)

```
grep -n "async def _extract_and_execute_actions\|async def extract_and_execute_actions" src/probos/proactive.py
  3010, 2859   (signature :3010-3014; wrapper body :2865)
grep -n "rank = Rank.from_trust\|Rank.ENSIGN.value\|assign_min_rank = Rank.LIEUTENANT\|crew_min_rank = Rank.LIEUTENANT" src/probos/proactive.py
  3034, 3046, 3064, 3676, 3718
grep -n "BF-203: Strip unrecognized\|text = re.sub(handoff_pattern" src/probos/proactive.py
  3807, 3805 (each once)
grep -n "extract_and_execute_actions(\|post_budget=budget" src/probos/ward_room_pipeline.py
  292, 294   (process_and_post params thread_id :252, post_id :254)
grep -n "pipeline.process_and_post(" src/probos/cognitive/cognitive_agent.py
  7308   (thread_id, event_type, post_id from intent params :7309-7314)
grep -n "# Build prompts\|_COMPOSITION_MODES = \|def __init__(self, \*, llm_client: Any, runtime: Any)" src/probos/cognitive/sub_tasks/compose.py
  657, 585, 604
grep -n "PLAN_MODE_TOOL_IDS: frozenset" src/probos/cognitive/agent_mode.py
  68   (members :69-82)
grep -n "_APPROVAL_INBOX_TOOL_IDS: frozenset\|_NEVER_RAN_REFUSALS: frozenset\|def classify_tool_fault_error\|def restrict_to_plan_mode\|async def _park_or_admit" src/probos/cognitive/agentic_dispatch.py
  225, 298, 2023, 886, 1074
grep -n "admitted_turn: bool = False\|refuse_new_run(runtime, agent_id)\|arguments\[\"inner_loop_hook\"\]\|raise ValueError(\"plan_mode_tool_ids_invalid\")\|executor.restrict_to_plan_mode(plan_mode_tool_ids)" src/probos/cognitive/agentic_dispatch.py
  2613, 2623, 2663, 2823, 3453 (each once)
grep -n "class WorkItemAgenticExecutor\|async def run(\|async def _run_reserved(" src/probos/cognitive/agentic_dispatch.py
  2344, 2592, 2674
grep -n "async def block_on_request\|async def _resume\|async def _cancel\|base\[\"denial_reason\"\]" src/probos/cognitive/capability_gap_driver.py
  135, 291, 383, 408
grep -n "def awaited_command_request\|async def park_on_command_escalation" src/probos/cognitive/command_escalation_park.py
  55, 91
grep -n "def _maybe_fulfil_on_approval\|_APPROVAL_FULFILLERS: dict\|command_approval_request(decided) is not None" src/probos/routers/capability_requests.py
  432, 424, 464 and 609
grep -n "_ACTION_PAYLOAD_KEYS: frozenset\|def validate_action_payload\|def action_dedup_key\|async def file_action_request\|def count_pending_sync\|async def mark_fulfilled\|async def get(" src/probos/capability_request.py
  74, 165, 456, 779, 931, 1037, 1126
grep -n "\"task\": WorkTypeDefinition\|WorkTypeTransition(\"open\", \"in_progress\", requires_assignment=True)" src/probos/workforce.py
  181, 188   (no "scheduled" transition for task :187-197)
grep -n "async def transition_work_item\|async def claim_work_item\|async def unassign_work_item\|async def start_booking\|async def complete_booking\|async def cancel_booking\|async def list_bookings\|async def _expire_ttl_items" src/probos/workforce.py
  10753, 11437, 11534, 11568, 11633, 11689, 11726, 11931
grep -n "if self._dispatcher and not agent_pull:\|events.append(EventType.WORK_ITEM_CLAIMED)" src/probos/workforce.py
  11403, 11389
grep -n "def is_dispatchable\|async def dispatch_work_item" src/probos/mesh/work_item_router.py
  59, 68
grep -n "is_agent_post = \|target_agent_ids = target_agent_ids\[:thread_max_responders\]\|def find_targets_for_agent" src/probos/ward_room_router.py
  421, 502, 993
grep -n "\"mentions\": extract_mentions(body)\|AD-654d: Emit mention TaskEvent" src/probos/ward_room/messages.py src/probos/ward_room/threads.py
  messages.py:244, 247; threads.py:498, 501
grep -n "async def create_thread\|async def create_post\|async def get_channel_by_department\|async def list_threads" src/probos/ward_room/service.py
  413, 466, 328, 344
grep -n "def dm_channel_name" src/probos/ward_room/channels.py
  19   (eight-character prefixes collide, :20-25)
grep -n "SEAM_AGENTIC_RUN: Final\|SEAM_AGENT_WORK: Final\|S1_SCOPE: Final\|def standing_stop\|def refuse_new_run\|def active(self)" src/probos/agent_stop.py
  68, 70, 77, 590, 602, 397
grep -n "def crew_member\|def execution_allowed\|def claim_allowed\|def eligible_members\|def notice_recipients\|def terminal_notices_due\|def claim_notice\|def _stopped_now\|def _holds_tool" src/probos/agent_work.py
  (none for the first two: added by §7.7); 416, 407, 437, 446, 461, 501, 505
grep -n "AGENTIC_RUN_OWNERS: dict\|\"agent_work\": (" tests/fixtures/ad1343_seam_registry.py
  88, 224
grep -n "never_ran == " tests/test_ad1156_plan_execute_mode.py
  539
grep -n "(\"work_item_store\", \"workforce store stop\")\|def test_every_step_that_stops_a_component_hands_that_component_to_the_guard" tests/test_issue1419_failed_start_rollback.py
  1141, 1399
grep -n "assert list(params)\[:21\]" tests/test_ad1155_loop_until_done.py
  508
grep -n "def _wire_task_completion_notifier\|if _wire_task_completion_notifier(runtime=runtime, config=config):\|agentic_executor = WorkItemAgenticExecutor(llm_client=llm_client)" src/probos/startup/finalize.py
  3368, 5531, 2196
grep -n "runtime.agent_work = None" src/probos/startup/shutdown.py
  1674
grep -n "from probos.agent_work import AgentWorkService\|self.agent_work: \"AgentWorkService | None\" = None\|self.event_log = EventLog" src/probos/runtime.py
  167, 1135, 707
grep -n "async def audit_governed_query\|category=\"audit\",\|event=\"event_log_query\"," src/probos/substrate/event_log.py
  1065, 1106, 1107
grep -n "_TOOL_EVENT_CATEGORY = \|def tool_record_identity" src/probos/tools/executor.py
  44, 311   (without a catalog the retained tool id is opaque :317-325)
grep -n "def _register_event_log_query_tool\|allowed_departments=(\"engineering\", \"science\", \"security\")" src/probos/startup/communication.py
  46, 74
grep -n "max_pending_per_agent: \|class ApprovalInboxConfig" src/probos/config_models/experience.py
  158, 15
grep -n "def apply_dm_sanity" src/probos/cognitive/dm_sanity_gate.py
  578   (a non-DmSanityGate runtime is a no-op :589-591)
grep -n "SRP_MAX_BODY_LINES = \|SRP_MAX_DIRECT_METHODS = " scripts/check_architecture_principles.py
  187, 188   (the trigger is "> 15"; AgentWorkService and AgentWorkRunner each have 15)
```

**SEARCH uniqueness.** Each SEARCH's distinctive line was grepped and occurs once in its file:
- `agentic_dispatch.py`: 299, 750, 856, 2029, 2613, 2663, 2823, 3453. The 2735-2738 block is unique because `_run_reserved` alone has `inner_loop_hook` directly before the return annotation.
- `proactive.py`: 3805, and the two `def` lines.
- `compose.py`: 657.
- `finalize.py`: 3401, 5531.
- `routers/capability_requests.py`: 17, 488.
- `shutdown.py`: 1671.
- `capability_gap_driver.py`: the turn-promotion import and `if is_promoted_turn(updated):` each occur once.
- `agent_stop.py`: 88.
- `ward_room_pipeline.py`: `if agent and self._proactive_loop:` occurs twice (291, 307), so that SEARCH carries the next line, which occurs once.

## 12. Absence Verified (2026-10-23)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | nothing subscribes to WORK_ITEM_CLAIMED, so nothing runs a pull-claimed item | `rg "work_item_claimed\|WORK_ITEM_CLAIMED" src/probos` | `event_persistence.py:462` (persisted list), `events.py:108`, `workforce.py:11389` (emit) | yes |
| AV2 | AD-1343 S2 (ending a running turn) is not built | `rg "AD-1343 S2" src/probos` | `agent_stop.py:92` only (`does_not_end`) | yes |
| AV3 | none of the new names exist yet | `rg "agent_work_runner\|agent_work_tags\|AgentWorkRunner\|ToolCallConfinement\|CLAIM_WORK\|SELF_TASK\|REQUEST_WORK"` (repo, excluding prompts) | no files | yes |
| AV4 | the Captain's one-to-one chat does not call the extractor | `rg "extract_and_execute" src/probos/cognitive/dm/reply_pipeline.py` | `:1240-1316` (`extract_and_execute_dms`, `extract_and_execute_notebooks`) only | yes |
| AV5 | two test stubs fake `extract_and_execute_actions` with a fixed signature; no other double constrains its kwargs | `rg "def _fake_extract\|post_budget=None\):" tests`; `rg "extract_and_execute_actions *=" tests` | `tests/test_bf237_pipeline_post_budget.py:25` and `tests/test_bf238_post_budget_telemetry.py:174` (both updated: §7.3a, §7.3b); the other doubles are `AsyncMock`s | yes (corrected after the M1 build: the first claim searched only for `def extract_and_execute_actions`) |
| AV6 | no test pins `S1_SCOPE["refuses"]` text | `rg "browser actions and every\|result is escalated unverified"` (excluding prompts) | `agent_stop.py:88` only | yes |
| AV7 | an ordinary approved `action` has no fulfiller today | `routers/capability_requests.py:248-257`, `:424-429` | `continue`, `grant`, `install`, `build` only | yes |

## 13. Prior Art and Blind Spots

- **Internal prior art.**
  - AD-1156 plan mode: an allowlist enforced at the call; **adopted** as the confinement's shape.
  - AD-1154 inbox, AD-1328 S2b/S2c and AD-855: park, approve and resume; **reused unchanged**, with one new fulfilment branch.
  - The crew executor runs a colleague's loop from the Ship's Computer (`finalize.py:2196`); **adopted**.
  - BF-200 and AD-1343 post as `system`; **adopted** as the author of every Ship's Computer post.
- **External prior art.** The issue's review covered it: Contract Net (an announcement, then the first claim wins) is **adapted** through the notice and AD-1187's compare and set; CrewAI's in-run delegation was **rejected**. This slice is ProbOS plumbing, so I ran no new external search. `docs/research/reference-projects.md` was not re-checked (considered, deferred).
- **Blind spots the issue does not name, each handled or registered:**
  - Ward Room DM channel names collide on 8-character prefixes. Handled: notices go to the department channel.
  - A claimed `task` sits in `scheduled`, which its TTL cannot cancel. Handled: the runner starts the booking at once (register R1).
  - AD-855 writes the denial reason after the cancel event. Handled: the reason is read from the request.
  - An agent-run DM thread origin is a Ward Room thread. Handled: origin channel `ward_room`.
  - A pull-claim from an agent's own loop also triggers the runner. Accepted: the runner is the executor of record.
  - The pull tools are offered inside an agent-work run, so a claim made there is filed for approval (register R7).

## 14. Diff Reviewer: properties to verify

1. With `agent_work` off:
   - no new path is entered: the extractor never calls the tag module;
   - the compose system prompt equals the builder's output;
   - finalize builds no runner and `runtime.agent_work_runner` is None;
   - the executor's run arguments and its unarmed state are unchanged;
   - the router's and AD-855's behaviour for every non-agent-work request and item is unchanged.
2. Every agent-created item is created through `AgentWorkService` only. `created_by` is the resolved requester slot, and no path stamps the Captain.
3. Tags are acted on only for Lieutenant and above, at most three per reply. While on, every tag and stray marker is removed from the posted text.
4. The acknowledgement is part of the agent's own reply text; the tag module creates no Ward Room post.
5. A chain claim goes through `ToolRegistry.check_and_invoke` for `claim_work_item`, with the claimant's department, rank and agent type, at WRITE.
6. Every agent-work run passes a `ToolCallConfinement` and never passes `admitted_turn`. No run starts for an item that `execution_allowed` refuses.
7. A call outside `AGENT_WORK_READ_TOOL_IDS` reaches its tool only when an approval on record for the same agent, item, tool and parameters is consumed in that call. Each approval admits at most one call, across restarts.
8. A gate fault, a store fault or a payload that cannot be recorded refuses the call; none admits it.
9. A request whose claimant may not run it ends open and unassigned with its booking cancelled, never failed or cancelled.
10. Each terminal, activation and decline notice is claimed before it is sent. Delivery makes one post per item, and every watcher of a deduplicated request is a recipient.
11. No new EventLog category or event pair, request kind, config field, table, stop-seam constant or stop-check site.
12. Every background run is held in a set and cancelled at stop. Shutdown stops the runner before the work store.
13. `probos.agent_work_runner` imports the cognitive layer only inside functions, so the approval route's import chain gains no cognitive module.

## 15. Acceptance criteria

1. **Live (closes the AD).** A crew agent in a Ward Room thread that needs an EventLog read files a request; a Lieutenant-or-above member of Engineering, Science or Security claims it and runs `event_log_query`; the result is posted in the originating thread, and the Captain sends no DM. Evidence comes from the live vessel (§16).
2. **One test crosses the whole seam:** X1.
3. **Guards:** S1's tests cover the claim side, plus X8 through the chain.
4. **The approval path:** X2.
5. **The stop:** C7 (create), X3 (claim and run); the census rows are updated (§7.16).
6. **Provenance through the chain:** C3, C4.
7. **Off is unchanged:** C5, C11, W3. AD-845 and AD-1165 are untouched (§9).
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance (acceptance 1): what the Captain does and what is read

**Captain's actions** (all operator-owned):
1. Set `agent_work.enabled: true` in his own `config/system.yaml`.
2. Confirm `agentic_dispatch.orchestrator_enabled` is on, so `event_log_query` is registered (`startup/communication.py:46-81`).
3. Restart the vessel.
4. Check the boot log has `AD-1347: agent-work runner wired`. If it says `runner is not built (missing: ...)`, enable what it names.
5. Let a Ward Room conversation produce a request, or prompt one by asking a medical officer about a log window in a thread.

**Read-only queries** against `%LOCALAPPDATA%\ProbOS\data`. Open each database with `sqlite3.connect("file:<path>?mode=ro", uri=True)` under `python -I`.

1. The work item, from `workforce.db`:

   ```sql
   SELECT id, title, status, created_by, assigned_to,
          json_extract(metadata,'$.agent_work.kind'),
          json_extract(metadata,'$.agent_work.origin.thread_id'),
          json_extract(metadata,'$.agent_work.tool_id'),
          json_extract(metadata,'$.agent_work_result.executor')
   FROM work_items
   WHERE json_type(metadata,'$.agent_work') = 'object'
   ORDER BY created_at DESC LIMIT 5;
   ```

2. The claim booking, from `workforce.db`:

   ```sql
   SELECT id, resource_id, status, start_time, actual_start, actual_end
   FROM bookings WHERE work_item_id = :id;
   ```

3. The tool audit records, from `events.db`:

   ```sql
   SELECT id, timestamp, agent_id, json_extract(data,'$.outcome')
   FROM events WHERE category = 'audit' AND event = 'event_log_query'
     AND agent_id = :claimant AND timestamp BETWEEN :claimed AND :done;

   SELECT id, timestamp, agent_id, json_extract(data,'$.is_error')
   FROM events WHERE category = 'tool' AND event = 'tool_invoked'
     AND json_extract(data,'$.work_item_id') = :id;
   ```

4. The thread post, from `ward_room.db`:

   ```sql
   SELECT id, author_id, author_callsign, created_at, substr(body, 1, 400)
   FROM posts WHERE thread_id = :origin_thread AND author_id = 'system'
   ORDER BY created_at;
   ```

5. No Captain DM in the window, from `ward_room.db`:

   ```sql
   SELECT count(*) FROM posts p
     JOIN threads t ON p.thread_id = t.id
     JOIN channels c ON t.channel_id = c.id
   WHERE c.channel_type = 'dm' AND p.author_id = 'captain'
     AND p.created_at BETWEEN :created AND :done;
   ```

   Also count `threads` with `author_id = 'captain'` in DM channels in the same window.

6. The notices, from `workforce.db`:

   ```sql
   SELECT work_item_id, recipient, kind, claimed_at
   FROM agent_work_notices WHERE work_item_id = :id;
   ```
