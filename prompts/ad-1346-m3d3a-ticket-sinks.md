# AD-1346 M3d3a (#1604): the work ticket's sink checks at the tool sink and the model gateway, in shadow

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-30
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). M3d3 is split into M3d3a (this contract: the sink checks) and M3d3b (the persisted sink record; register R46). No new AD or BF number: M3 takes AD-1346 (`scripts/ad_ceiling.py` on 2026-10-30: ceiling AD-1355 from GitHub issue titles, next AD-1356; none allocated here). **Tier:** HIGH (M1, M2, M3), docs (M4). Nothing parked.
**Dependencies:** AD-1346 M3d2 (`prompts/ad-1346-m3d2-ticket-issue-points.md`, with its amendments) merged to `origin/main`. Its head after three cross-family review rounds is `302e6bf9` (tree `75aecaf1d45f5c4a9489d0d65d73486cff8337be`); its PR merges before this build, and the build base is `origin/main` at that merge, whose tree is that tree.
**Anchors:** every SEARCH text in §7 and §8 was read on the detached checkout `93af6ae4` (tree `21172897`): `origin/main` `1ffbdc61` (the M3d1 merge, PR #1711) plus the six M3d2 candidate commits `550a53d2`..`93af6ae4`. 33 pairs (M1 17, M2 14, M4 2), 1 new file besides this contract (`tests/test_ad1346_admission_ticket_sinks.py`), 2 regenerated files in M4 (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`). The orchestrator dry-applied the 33 pairs and the new file on `302e6bf9` (2026-10-30) with no failure, and A1 changes no SEARCH text in §7 or §8.
**Contract file:** `prompts/ad-1346-m3d3a-ticket-sinks.md`.

**Identifiers.**
- Register rows: M3c1's R10 to R18, M3c2's R19 to R23, M3c3's R24 to R28, M3d1's R29 to R36, M3d2's R37 to R45 and this contract's R46 to R51 are written "register R<n>".
- Tests: service tests T<n> (`tests/test_ad1346_admission_service.py`), census tests 9a to 9c (`tests/test_ad1343_stop_seam_inventory.py`), M3d1's K1 to K15, M3d2's I1 to I11 (`tests/test_ad1346_admission_ticket_issue.py`) and this slice's SK1 to SK10 (`tests/test_ad1346_admission_ticket_sinks.py`).
- Mutation rows here are SKX-<n>.
- Decisions D123 to D136 are numbered after M3d2's D107 to D122 (M3d1's are D90 to D106). #1604's properties are numbered 1 to 13.

**Which text describes the head.**
- **Records of the read tree `21172897` (commit `93af6ae4`):** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), the internal citations in §13, and every SEARCH text in §7 and §8. Each SEARCH text occurs once in its file on that tree, and no earlier pair of this contract edits those lines.
- **M3d2's head is `302e6bf9`** (tree `75aecaf1d45f5c4a9489d0d65d73486cff8337be`), after three cross-family review rounds; its repair after `93af6ae4` changed text and one log message. The build base is `origin/main` at the M3d2 merge, whose tree is that tree. On it, before the build, re-run each SEARCH text's uniqueness check in these M3d2 files, which this contract **edits**:
  - `src/probos/admission/service.py` (M1-01 to M1-08);
  - `src/probos/admission/seam.py` (M1-09, M1-10);
  - `src/probos/runtime.py` (M2-07 edits the line M3d2 wrote; M2-08 edits an M3c line);
  - `tests/test_ad1346_admission_service.py` (M1-11 to M1-15, M2-12 to M2-14: T13 and T14 as M3d2 left them);
  - `tests/test_ad1346_admission_ticket_issue.py` (M1-16, M1-17: I11);
  - `tests/fixtures/ad1343_seam_census.py` (M2-09 anchors on M3d2's `hold_at` line);
  - `PROGRESS.md` and `DECISIONS.md` (M4 anchors next to M3d2's entries).
  
  It **cites** these, unedited: `src/probos/admission/carrier.py` (`CURRENT_TICKET`, `TicketHold.end`), `AdmissionService.hold`, `seam.hold_at` and the run entry's hold in `src/probos/cognitive/agentic_dispatch.py`. SK5 and SK6 drive that hold.
  
  If the merged text of any of these differs from `302e6bf9`'s, re-verify the pair or the citation against the merged text.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15. Each count in them is measured by a named command, a focused gate or the broad gate, or is marked as a prediction.
- **Text inside the new-file block** (docstrings, comments) is head text and is reviewed as such.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (HIGH):** the package side.
  - `AdmissionService` takes an optional `loop` and gains `check_ticket`, `_check_ticket` and `off_loop_checks`, plus the module helper `_running_loop`.
  - `probos.admission.seam` gains `check_at`.
  - T13, T14 and I11 are updated, with their module docstrings.
- **M2 (HIGH):** the sinks and the wiring.
  - `ToolRegistry.check_and_invoke` calls `check_at` after its shadow statement, with zero net lines in the class.
  - `OpenAICompatibleClient` gains `_admission` and `set_admission`, and `complete` calls `check_at` first.
  - `runtime.py` passes its loop to the service and the service to the gateway.
  - The census records `check_at`.
  - The `.complete(` report's texts are reclassified.
  - T16 is updated.
- **M3 (HIGH):** new `tests/test_ad1346_admission_ticket_sinks.py`, SK1 to SK10.
- **M4 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`. `git add` the new file before M3's focused gate.
- Commit subjects take the form `AD-1346 M3d3a, M<n>: ... (#1604)`.
- One cross-family review (`gpt-6.1-sol`) of M1 to M3 against §14.
- One mutation campaign of record on the M3 tree (§10).
- The cost measurement of D132 runs on the M1 stage, before the review.
- The broad gate runs once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3d3a --receipt logs/gates/ad1346-m3d3a.receipt.json`.

**Tests:**
- New: `tests/test_ad1346_admission_ticket_sinks.py` (M3), SK1 to SK10. The block in §7.12.N defines 10 `def test_` functions and no parametrised case. It collected 10 in the orchestrator's pre-build run (2026-10-30); record the number collected at M3's gate.
- Updated:
  - `tests/test_ad1346_admission_service.py`: M1 updates T13 (renamed, its signature and attribute sets), T14's allowlist, logging rule and docstring, and the module docstring's T13 and T14 bullets; M2 updates T16 (renamed, its importer set and docstring) and the module docstring's T16 bullet.
  - `tests/test_ad1346_admission_ticket_issue.py` (M1): I11's set and its module bullet.
  
  No file's `def test_` count changes.
- The acceptance greps for the new test file are in §15.

## 1. Problem

- Register R30 asks M3d3 for these, and none exists on this tree:
  - the sink checks;
  - the persisted sink record;
  - the census of sinks;
  - the crossing tests of property 5;
  - the cost measurement of property 7.

  The carrier (`probos.admission.carrier.CURRENT_TICKET`) is set at three entries (M3d2), and nothing reads it at an effect point. Absence: no Python file names `check_at` or `check_ticket`.
- The tool sink is `ToolRegistry.check_and_invoke` (`src/probos/tools/registry.py:362`):
  - its stop check is at `:396`, its shadow statement at `:397-398` and today's refusal at `:399-404`;
  - the class runs from `:85` to the end of the 582-line file (`wc -l`), so its span is 498 lines against the SRP trigger `span > 500` (`scripts/check_architecture_principles.py:566`);
  - its baseline row records `methods` only (`docs/development/architecture-baseline.yaml:994-997`).
- The model gateway is `OpenAICompatibleClient.complete` (`src/probos/cognitive/llm_client.py:1458`):
  - its docstring ends at `:1468`, and its first statement (`:1469-1470`) chooses the lane before a semaphore wait of up to 30 seconds (`:1475`);
  - the class's baseline row records both triggers (`architecture-baseline.yaml:581-584`);
  - the class has no admission attribute;
  - the client is late-bound elsewhere through `set_attachment_store` (`:2179-2187`, called from `__main__.py:655-656`).
- Threads (register R31; M3d1's D99 confines the registry to its loop's thread):
  - `consultation/llm_decomposer.py:148-149` runs `self._client.complete(req)` under `asyncio.run` in a `ThreadPoolExecutor` worker.
  - `tools/browser/loop_host.py`'s docstring (`:15-23`) says it marshals at the page boundary and leaves `llm_client.complete()` on the main loop.
  - `channels/discord_adapter.py:190`, `:208` create loops in its thread-isolated teardown (`:178`).
  - These are read from the source, not traced at run time; D128 does not depend on which sites run off the loop.
- Internal precedent for the thread rule: `substrate/durable_events.py:239-245` and `:553-557` (AD-1195):
  - on its loop it accepts in place;
  - elsewhere it calls `loop.call_soon_threadsafe(...)` and drops on `RuntimeError` (`loop_closed`);
  - its `_running_loop()` wraps `asyncio.get_running_loop()` in `except RuntimeError: return None`.
- The model clients in `src`:
  - `BaseLLMClient` has two subclasses, `OpenAICompatibleClient` (`llm_client.py:265`) and `MockLLMClient` (`:2684`);
  - `_complete_inner` is called only at `:1485`, inside `complete`;
  - `_call_openai` and `_call_ollama_native` are called only at `:2167`, `:2172`;
  - `__main__.py:335` builds the production client and `:376` falls back to `MockLLMClient` when no endpoint answers;
  - see Absence.
- A boot with an `OpenAICompatibleClient` starts its health probe (`startup/finalize.py:4313-4321`, awaited when it is a coroutine function).
- Hidden pins this slice meets:
  - 9b pins every `shadow_at` call's keywords, count and place (`tests/test_ad1343_stop_seam_inventory.py:244-270`); 9c pins its callers (`:273-276`). This slice changes no `shadow_at` call.
  - `test_each_sink_consults_the_stop_first` requires the tool sink's `tool_refusal` before `resolve_permission`, `self._tools.get` and `start_permitted_effect` (`:119-123`).
  - T13 pins `AdmissionService.__init__`'s parameters and attributes (`tests/test_ad1346_admission_service.py:469-491`).
  - T14 pins:
    - the package's import allowlists (`:73-94`, `service.py` at `:80-84`);
    - the forbidden calls (`:111-114`; `call_soon_threadsafe` and `get_running_loop` are not among them);
    - logging only in `shadow` and `hold` (`:536-542`).
  - T16 pins the files that import the package (`:602-608`).
  - I11 pins the carrier's callers (`tests/test_ad1346_admission_ticket_issue.py:580-596`).
  - R4 (`tests/test_ad1343_seam_registry.py:127-134`) pins that the `.complete(` report covers the sites outside the crew modules and gates nothing.

## 2. Solution

- **The check.**
  - `AdmissionService.check_ticket(effect=, presented_id=)` reads `CURRENT_TICKET` in the caller's context and asks the registry about that ticket at the effect point, comparing the principal key `decide` gives the presented id when there is one.
  - The registry counts the finding in its tally (`(effect, code)`), so a call with nothing carried counts `ticket_missing` for its effect.
  - It returns None.
  - `probos.admission.seam.check_at` calls it for an exact `AdmissionService`; for anything else it does nothing.
- **The sinks.**
  - `ToolRegistry.check_and_invoke` calls `check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)` right after its shadow statement and before today's stop answer.
  - `OpenAICompatibleClient.complete` calls `check_at(self._admission, effect=SEAM_MODEL_CALL, presented_id=getattr(request, "agent_id", None))` as its first statement.
- **Wiring.**
  - The runtime builds the service with `loop=asyncio.get_running_loop()`.
  - Beside the tool registry's `set_admission`, it calls `set_admission(self.admission_service)` on its LLM client when that is an `OpenAICompatibleClient`. With the switch off that argument is None, and the sinks check nothing.
- **Threads.** A service built with a loop checks on that loop. A sink on another thread, or on another thread's loop, reads the carrier where it runs and hands the check, with the ticket it read, to that loop with `call_soon_threadsafe`.
- **No blocking, nothing persisted.** Every finding is in the registry's in-memory tally. The persisted sink record is M3d3b (register R46).

## 3. Decisions (numbered after M3d2's D107 to D122)

- **D123 The split.**
  - M3d3a holds the sink checks, the thread rule, the census, the crossing tests and the cost method.
  - M3d3b (register R46) holds the persisted record, the issue findings' persistence (register R39), the report queries, the executed older-build check and the measurement with the recorder.
  - Reason: one slice would be about 50 pairs. A slice that edits three live entry points took two HIGH review rounds. With the checks first, the record has a producer, and its chain test can go from a sink to a report query in one test.
  - Rejected: one slice; the record first (a writer with no producer); three slices (the census and crossing tests would separate from the code they pin).
- **D124 The check is the service's.**
  - `AdmissionService.check_ticket(*, effect, presented_id) -> None` reads `CURRENT_TICKET.get()` and either checks at once or hands the check over (D128).
  - `_check_ticket` checks nothing when the service has no registry or is closed (the closed case includes a check handed over before `close`).
  - Otherwise it computes `key`: `resolve_principal(presented_id, identities).key` when `presented_id` is a non-empty `str`, else `""` (no principal compared).
  - It then calls `TicketRegistry.check(ticket, effect=effect, presented_key=key)` inside its own `except Exception`, which counts in `failures` and logs through its own guard (F-212), as `hold` does.
  - The new logging block copies `hold`'s rather than sharing a helper. A helper would move `shadow`'s and `hold`'s logging lines, which M3c's and M3d2's mutation rows name.
  - Rejected:
    - a sink that calls the registry itself (it bypasses the service's `except`, `close` and thread rule);
    - returning the finding (a sink would then have something to act on; M3a's D7);
    - a log line per finding.
- **D125 The seam function.**
  - `check_at(service, *, effect, presented_id) -> None` calls `check_ticket` only for `type(service) is AdmissionService`, as `shadow_at` and `hold_at` do.
  - It awaits nothing, raises no `Exception` and returns None.
- **D126 The tool sink** (refines M3d1's D103).
  - The statement is `check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)`, directly after the `shadow_at` statement and directly before `if stopped is not None:`, so a call today's stop refuses is checked too.
  - The M3c comment line above the shadow statement becomes a trailing comment on the new line, so the two lines replace two lines and the class's span does not change (§1: 498).
  - D103 said "one statement doing the shadow decision and the sink check". Two statements keep every `shadow_at` pin (9b, 9c, `SHADOW_SITES`, G2) unchanged and give both sinks the same statement, which SK7 pins.
  - Rejected:
    - a combined `shadow_and_check_at` replacing `shadow_at` (it changes 9b's count and 9c's callers);
    - `shadow_at` checking the ticket when the seam is an effect seam (hidden behaviour);
    - a check after today's refusal returns (a stopped agent's call would never be checked, and property 5's tool half could not be seen for the run's own agent).
- **D127 The model gateway.**
  - The first statement of `OpenAICompatibleClient.complete` is `check_at(self._admission, effect=SEAM_MODEL_CALL, presented_id=getattr(request, "agent_id", None))`.
    - The argument is evaluated before `check_at` is entered. With `getattr` and a None default, an object passed as the request with no `agent_id` raises, if at all, where the base raises, in `_complete_inner`, after the lane wait. An `LLMRequest`'s `agent_id` is a dataclass field that defaults to None, so the value passed is the field's.
    - An `agent_id` whose read raises an `Exception` other than `AttributeError` now raises before the lane wait (injected only; §14 item 1).
  - The class gets `_admission: AdmissionService | None = None` and `set_admission(service)`, beside `set_attachment_store`.
  - `ProbOSRuntime.start`, after the tool registry's `set_admission`, calls `self.llm_client.set_admission(self.admission_service)` when `isinstance(self.llm_client, OpenAICompatibleClient)`.
  - `llm_client.py` imports `check_at`, `SEAM_MODEL_CALL` and `AdmissionService` from `probos.admission`, so T16's importer set gains it.
  - `MockLLMClient` gets no sink: it is the test double and the fallback when no endpoint answers (register R48).
  - Rejected:
    - the service carried in a context variable (a service locator; work with no hold would then record nothing, losing register R38's evidence);
    - a setter on `BaseLLMClient` and a sink in the mock;
    - a sink after the lane wait (register R47).
- **D128 Threads** (settles register R31).
  - `AdmissionService.__init__` takes `loop: asyncio.AbstractEventLoop | None = None` (keyword-only; anything else raises `TypeError`). The runtime passes `asyncio.get_running_loop()`.
  - `check_ticket` checks at once when `loop` is None or `_running_loop() is loop`. Otherwise it calls `loop.call_soon_threadsafe(self._check_ticket, ticket, effect, presented_id, True)`.
    - The ticket is read in the caller's context, before the hand-off.
    - The callback counts the check in `off_loop_checks()` by effect.
    - An `Exception` from the hand-off is passed over uncounted, because off the loop nothing may be counted. Python 3.12 says `call_soon_threadsafe` "Raises RuntimeError if called on a loop that's been closed."
  - For a service built with a loop, as the runtime builds it, a sink check uses the registry, the identity facade and the service's counts only on that loop's thread. `shadow` and `hold` hand nothing over and run on the thread that calls them (M3d1's D99 confines the registry to its loop's thread).
  - A service built with no loop checks in place on any thread. In `src` only the runtime builds the service, and it passes its loop (SK9; register R51).
  - The design is AD-1195's (`durable_events.py`, §1).
  - Rejected:
    - a thread-safe deque drained at the next on-loop check (arbitrary delay, and its drops would go uncounted);
    - skipping off-loop sinks (no evidence for R31);
    - checking in place (D99: no lock; `_revoke_tree` iterates sets the loop thread grows).
- **D129 What is recorded, and where (this slice).**
  - Each check the registry answers is counted in its tally under `(effect, code)`.
  - Checks handed over and answered are also counted in `off_loop_checks()`.
  - A check that raises is counted in `failures` and logged.
  - A hand-off that raises is not counted.
  - No carried ticket gives `ticket_missing` for its effect (registers R37, R38: in memory now, persisted by M3d3b).
  - A revoked, expired, unknown or mismatched ticket gives its own code.
  - A `TestTicket`: in `src` the carrier holds none (I11 pins who sets the carrier; K5 pins who names `TestTicket`), and a production registry answers `ticket_test_refused`.
  - Nothing else is recorded. M3e decides on further issue points (register R38).
- **D130 The census.**
  - `RECORDED` gains `check_at`. SK7 pins the two call sites, their keywords and their places. SK8 pins the gateway's no-bypass facts.
  - The M0 `.complete(` report stays report-only. Its printed line and the hand-classification comment now say the ticket is checked at the gateway, not per call site (R4 unchanged).
  - T16's importer set gains `probos/cognitive/llm_client.py`.
  - I11's set gains `("probos/admission/service.py", "AdmissionService.check_ticket", "get")`.
  - 9a to 9c, `SHADOW_SITES`, T15 and G2 are unchanged.
- **D131 The crossing tests of property 5** (in memory; the persisted half is M3d3b's). SK5 and SK6 drive:
  - the real run entry (`WorkItemAgenticExecutor.run`: its stop check, shadow statement and hold), with a test subclass's scripted `_run_reserved` in place of the agentic loop;
  - a `SimpleNamespace` runtime holding a real `ToolRegistry` (real stop gate and service) and the service;
  - the real gateway, whose `_complete_inner` returns a canned answer (the `tests/test_bf731_captain_llm_lane.py` precedent).

  The runtime is not booted and no request is sent.
  - Premises: before the stop, each sink counts `ticket_live` and today's tool check admits the call (the tool is absent, so the answer is "not found").
  - SK5: after a Captain's stop on the run's agent, the next model and tool call count `ticket_revoked`, with the stop's id on the entry.
  - SK6: a run the first run delegates holds a child ticket. After a stop on the delegating agent, the child's next model and tool call count `ticket_revoked` while today's tool check still admits them. A root run of a third agent afterwards counts `ticket_live`: the control that must not differ.
- **D132 The cost (#1604 property 7): the method.** Run by you on the M1 stage, on the Captain's Windows host, CPython 3.12.13, idle.
  - **Setup** (D120's):
    - an `IdentityService` over a started identity registry, an `AgentStopService`, and a fresh `TicketRegistry` per round;
    - an `AdmissionService(..., tickets=..., loop=asyncio.get_running_loop())` driven inside a coroutine on that loop;
    - one hold taken (a slot-id key), so the carrier holds a live root.
  - **Timing:** 5 rounds of 20,000 iterations after 2,000 warm-up iterations. Each iteration is timed alone with `time.perf_counter_ns()`. Report the median and the 99th percentile of the 100,000 deltas, and of an empty timed iteration.
  - **Variants:**
    - (a) the tool sink's hot path: one `shadow_at(...)` plus one `check_at(..., effect=SEAM_TOOL, presented_id=<slot>)`;
    - (b) as (a) under a depth-1 child hold;
    - (c) the gateway: `check_at(..., effect=SEAM_MODEL_CALL, presented_id=<slot>)`;
    - (d) as (c) with nothing carried;
    - (e) `check_at(None, ...)`.
  - **Prediction:** (c) costs less than one `shadow_at` call (4.08 µs measured beside D120). It does one `IdentityService.resolve`, about 10 dict reads (M3d1's D100), one `get_running_loop` and one `ContextVar.get`, and builds no verdict. Neither p99 is predicted.
  - **Record:** the figures go in the DECISIONS campaign-of-record bullet and on #1604. M3d3b repeats (a) to (d) with the recorder, and #1604's property 7 report cites M3d3b's figures.
- **D133 Property 12 and property 6 at the sinks** (SK10). The tool sink's and the gateway's answers are byte-identical with the service and without it:
  - with nothing carried;
  - with a live ticket;
  - while the registry's clock raises (each check counted in `failures`);
  - after a Captain's stop.

  The switch-off boot keeps `_admission` None (SK9). M3d2's I9 and M3c1's G2 boots use `MockLLMClient` and are unaffected.
- **D134 The clock-reset rule** (extends D106, D121).
  - This slice changes neither `decide()` nor its checks, so nothing restarts. All of M3d precedes the M3e deploy that starts the shadow period.
  - During the period, a fix to any of these restarts the 7 days for the sink records (M3d3b), not for the verdict and parity records: `check_ticket`, `_check_ticket`, `_running_loop`, `check_at`, the two sink statements, `set_admission`, the gateway's wiring, the runtime's `loop=` argument, or `TicketRegistry.check`.
  - A fix to the recorder or the report does not.
- **D135 Compatibility: nothing is persisted.** No store, table, schema version, configuration field, event type or route changes. `service.py` and `seam.py` stay decision files under T14 (no await, lock, file or connection call).
- **D136 Left out.**
  - The persisted record, the issue findings' persistence, the report queries, the executed older-build check and the measurement with the recorder are M3d3b (register R46).
  - The remaining effect points and the system-principal census are M3e.
  - Enforcement, revocation generations and explicit threading are M4.

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `src/probos/admission/service.py`, `src/probos/admission/seam.py`, `tests/test_ad1346_admission_service.py`, `tests/test_ad1346_admission_ticket_issue.py` | `pytest tests/test_ad1346_admission_service.py tests/test_ad1346_admission_tickets.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1346_admission_shadow_parity.py tests/test_ad1343_stop_seam_inventory.py tests/test_layer_boundaries.py -n 0`; `python -P scripts/check_architecture_principles.py --check` |
| M2 | `src/probos/tools/registry.py`, `src/probos/cognitive/llm_client.py`, `src/probos/runtime.py`, `tests/fixtures/ad1343_seam_census.py`, `tests/fixtures/ad1343_seam_registry.py`, `tests/test_ad1346_admission_service.py` | `pytest tests/test_ad1346_admission_service.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py tests/test_ad1343_agent_stop.py tests/test_ad1343_stop_crossing.py tests/test_ad1346_admission_shadow_seams.py tests/test_ad1346_admission_shadow_crew.py tests/test_ad1346_admission_service_boot.py tests/test_ad423b_tool_permissions.py tests/test_llm_client.py tests/test_ad636_llm_priority_scheduling.py tests/test_bf731_captain_llm_lane.py tests/test_ad1324_terminal_context.py tests/test_layer_boundaries.py -n 0`; `python -P scripts/check_architecture_principles.py --check`; `python -P scripts/check_seam_contracts.py --check` |
| M3 | new `tests/test_ad1346_admission_ticket_sinks.py` | `git add` the new file, then `pytest tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1343_stop_seam_inventory.py -n 0`; `pytest tests/test_ad1346_admission_ticket_sinks.py --collect-only -q -p no:cacheprovider -n 0` (record the count) |
| M4 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`AdmissionService.__init__`'s new keyword `loop` (default None).**
  - Read by `check_ticket`.
  - The T19 double takes `*args, **kwargs` (`tests/test_ad1346_admission_service_boot.py:130-134`).
  - `runtime.py` passes it, and so do SK1 (an object that is not a loop, for the `TypeError`), SK4 (its running loop, and a closed loop), SK5, SK6 and SK10 (the running loop).
- **`check_ticket`, `_check_ticket`, `off_loop_checks`.**
  - `check_at` calls `check_ticket`; SK1 and SK3 call it directly.
  - `check_ticket` calls `_check_ticket`, or schedules it on the loop.
  - `off_loop_checks` is read by SK1 and SK4.
- **`seam.check_at`.** Called in `src` at the two sinks only (SK7), and by SK2 and SK4.
- **`OpenAICompatibleClient._admission` and `set_admission`.** Read by `complete`; set by `runtime.py` (SK9) and by tests. No other `src` file calls it (Absence: the `set_admission` callers are the tool registry's).
- **`RECORDED`.** Read only by the census `Visitor` (M3d2's Absence). Of the census's consumers, only SK7 selects a `check_at` row: the others select by callee (T15 first by file), or by a pinned keyword, which the `check_at` rows do not carry.
- **The `.complete(` report text** (`model_call_report`'s printed line). Read by no test (Absence).

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_ticket_sinks.py` | M3 | 10 (the block's `def test_` count; record the collected number at M3's gate) | SK1 to SK10: real `IdentityService`, `AgentStopService` and `ToolRegistry` under `tmp_path`, a `TicketRegistry` on a test clock, the real gateway with a canned `_complete_inner`, the real run entry with a scripted body, and two boots under `tmp_path` |
| `tests/test_ad1346_admission_service.py` | M1, M2 | unchanged count | T13 (renamed; signature and attributes), T14 (allowlist, logging rule, docstring), T16 (renamed; importer set, docstring), the module docstring's T13, T14 and T16 bullets |
| `tests/test_ad1346_admission_ticket_issue.py` | M1 | unchanged count | I11's set and its module bullet |

## 7. The contract

### 7.1 M1: `src/probos/admission/service.py`

**M1-01** (module docstring)

SEARCH:
```
``except Exception`` of its own, which counts in ``failures`` and logs as ``shadow``'s does.
The service reads no configuration.
```
REPLACE:
```
``except Exception`` of its own, which counts in ``failures`` and logs as ``shadow``'s does.
AD-1346 M3d3a added ``check_ticket``: ``probos.admission.seam.check_at`` calls it at the tool sink and the model
gateway, and nothing is refused or persisted. A service built with an event loop checks on that loop: a sink on
another thread, or on another thread's loop, hands its check there with ``call_soon_threadsafe`` (D128). A sink check
that raises an ``Exception`` in ``_check_ticket`` is counted in ``failures`` and logged, as ``hold``'s is.
The service reads no configuration.
```

**M1-02** (imports)

SEARCH:
```
from __future__ import annotations

import logging
import time
```
REPLACE:
```
from __future__ import annotations

import asyncio
import logging
import time
```

**M1-03** (the loop helper)

SEARCH:
```
_WORK_SCOPE: Final = TicketScope(frozenset(TICKET_EFFECTS))
_NO_CEILINGS: Final = TicketBudget()
```
REPLACE:
```
_WORK_SCOPE: Final = TicketScope(frozenset(TICKET_EFFECTS))
_NO_CEILINGS: Final = TicketBudget()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The loop running on this thread, or None (``asyncio.get_running_loop`` raises ``RuntimeError`` when none runs)."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None
```

**M1-04** (the signature)

SEARCH:
```
        tickets: TicketRegistry | None = None,
    ) -> None:
```
REPLACE:
```
        tickets: TicketRegistry | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
```

**M1-05** (the check and the attributes)

SEARCH:
```
        if tickets is not None and not isinstance(tickets, TicketRegistry):
            raise TypeError("AdmissionService takes a TicketRegistry or None")
        self._identities = identity_service
        self._stops = stop_service
        self._clock = clock
        self._recorder = recorder
        self._tickets = tickets  # AD-1346 M3d2: compared with None, never by truth (an empty registry is falsy)
        self._closed = False
```
REPLACE:
```
        if tickets is not None and not isinstance(tickets, TicketRegistry):
            raise TypeError("AdmissionService takes a TicketRegistry or None")
        if loop is not None and not isinstance(loop, asyncio.AbstractEventLoop):
            raise TypeError("AdmissionService takes an event loop or None")
        self._identities = identity_service
        self._stops = stop_service
        self._clock = clock
        self._recorder = recorder
        self._tickets = tickets  # AD-1346 M3d2: compared with None, never by truth (an empty registry is falsy)
        self._loop = loop  # AD-1346 M3d3a (D128): the loop its sink checks run on; None checks in place (tests)
        self._off_loop: dict[str, int] = {}  # AD-1346 M3d3a: checks handed to that loop from elsewhere, by effect
        self._closed = False
```

**M1-06** (`close`'s docstring)

SEARCH:
```
        """Decide and issue nothing from now on: a later ``shadow`` returns None at once and a later ``hold`` returns ``NO_HOLD``; ``decide`` is unaffected (AD-1346 M3c, D61; M3d2)."""
```
REPLACE:
```
        """Decide, issue and check nothing from now on: a later ``shadow`` returns None at once, a later ``hold`` returns ``NO_HOLD`` and a later sink check, or one handed to the loop before this call, checks nothing; ``decide`` is unaffected (AD-1346 M3c, D61; M3d2; M3d3a)."""
```

**M1-07** (the sink check)

SEARCH:
```
            return NO_HOLD

    def _count(self, verdict: AdmissionVerdict, elapsed_ns: int) -> None:
```
REPLACE:
```
            return NO_HOLD

    def check_ticket(self, *, effect: str, presented_id: object) -> None:
        """The sink check of one effect point, in shadow: the registry's finding for the ticket the carrier holds (AD-1346 M3d3a).

        ``probos.admission.seam.check_at`` calls it at the tool sink and the model gateway. It reads the carrier in the
        caller's context. On the loop the service was built with, or on any thread when it was built with none, it checks
        at once (``_check_ticket``). Anywhere else (another thread, or another thread's loop) it hands the check, with the
        ticket it read, to that loop with ``call_soon_threadsafe``, so a service built with a loop makes its sink
        checks on that loop's thread (D128). A hand-off that raises an ``Exception`` (a
        closed loop raises ``RuntimeError``) checks and counts nothing. It returns None, so a sink has nothing to act
        on; no ``Exception`` leaves it, and a ``BaseException`` that is not an ``Exception`` propagates.
        """
        ticket = CURRENT_TICKET.get()
        if self._loop is None or _running_loop() is self._loop:
            self._check_ticket(ticket, effect, presented_id, False)
            return None
        try:
            self._loop.call_soon_threadsafe(self._check_ticket, ticket, effect, presented_id, True)
        except Exception:  # noqa: BLE001 -- D128: a hand-off that raises (a closed loop) checks and counts nothing
            pass  # off the loop nothing may be counted: the counts are the loop's (D99)
        return None

    def _check_ticket(self, ticket: object, effect: str, presented_id: object, off_loop: bool) -> None:
        """One sink check on the service's loop, or in place: the registry counts its finding for ``ticket`` at ``effect``.

        With no registry, or after ``close`` (a check handed over before it included), it checks nothing. The principal
        compared is the key ``decide`` gives ``presented_id`` when that is a non-empty ``str``, else none. A check handed
        over from elsewhere is counted in ``off_loop_checks`` once answered. An ``Exception`` is counted in ``failures``
        and logged, as ``hold``'s is; a ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed or self._tickets is None:  # no registry, or closed (a check handed over before close included): nothing is checked
            return None
        try:
            key = resolve_principal(presented_id, self._identities).key if type(presented_id) is str and presented_id else ""
            self._tickets.check(ticket, effect=effect, presented_key=key)
            if off_loop:
                self._off_loop[effect] = self._off_loop.get(effect, 0) + 1
        except Exception:  # D129: counted and logged; the sink gets None
            self._failures += 1
            try:
                logger.log(
                    logging.WARNING if self._failures == 1 else logging.DEBUG,
                    "AD-1346 M3d3a: a work ticket's sink check raised (%d failures so far); check_ticket() returned None to the sink",
                    self._failures,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 -- F-212 (D59): a logging handler that raised must not reach the sink
                pass  # the failure is already counted in ``failures``
        return None

    def off_loop_checks(self) -> dict[str, int]:
        """Sink checks handed to the service's loop from another thread or loop and answered there by the registry, by effect, since this service was built; a copy."""
        return dict(self._off_loop)

    def _count(self, verdict: AdmissionVerdict, elapsed_ns: int) -> None:
```

**M1-08** (`failures`' docstring)

SEARCH:
```
        """Exceptions that the ``except Exception`` of ``shadow`` or of ``hold`` counted since this service was built."""
```
REPLACE:
```
        """Exceptions that the ``except Exception`` of ``shadow``, of ``hold`` or of a sink check (``_check_ticket``) counted since this service was built."""
```

### 7.2 M1: `src/probos/admission/seam.py`

**M1-09** (the module docstring)

SEARCH:
```
"""AD-1346 M3c and M3d2 (#1604): the statements a site adds beside its own stop check.

``shadow_at`` hands the site's work to ``AdmissionService.shadow`` with what the site's own check
did (``refused``) and returns None, so the site has no result to act on. It calls only an exact
``AdmissionService``: None, a test double or any other object is passed over. It awaits nothing.
It raises no ``Exception``: its own work is one type check and
one call with the keywords ``shadow`` takes, and ``shadow`` lets no ``Exception`` out (D59); a
``BaseException`` that is not an ``Exception`` propagates.

``hold_at`` (AD-1346 M3d2) hands one entry's admitted unit to ``AdmissionService.hold`` for an exact
``AdmissionService`` and returns its ``TicketHold``; for anything else it returns ``NO_HOLD``. The entry's only use of
the hold is its ``end()`` in a ``finally`` (``tests/test_ad1346_admission_ticket_issue.py``, I10). It awaits nothing
and raises no ``Exception``: ``hold`` lets none out.
"""
```
REPLACE:
```
"""AD-1346 M3c, M3d2 and M3d3a (#1604): the statements a site adds beside its own stop check, and at an effect point.

``shadow_at`` hands the site's work to ``AdmissionService.shadow`` with what the site's own check
did (``refused``) and returns None, so the site has no result to act on. It calls only an exact
``AdmissionService``: None, a test double or any other object is passed over. It awaits nothing.
It raises no ``Exception``: its own work is one type check and
one call with the keywords ``shadow`` takes, and ``shadow`` lets no ``Exception`` out (D59); a
``BaseException`` that is not an ``Exception`` propagates.

``hold_at`` (AD-1346 M3d2) hands one entry's admitted unit to ``AdmissionService.hold`` for an exact
``AdmissionService`` and returns its ``TicketHold``; for anything else it returns ``NO_HOLD``. The entry's only use of
the hold is its ``end()`` in a ``finally`` (``tests/test_ad1346_admission_ticket_issue.py``, I10). It awaits nothing
and raises no ``Exception``: ``hold`` lets none out.

``check_at`` (AD-1346 M3d3a) hands one effect point's call to ``AdmissionService.check_ticket`` for an exact
``AdmissionService``; for anything else it does nothing. The tool sink and the model gateway call it
(``tests/test_ad1346_admission_ticket_sinks.py``, SK7). It returns None, awaits nothing and raises no ``Exception``:
``check_ticket`` lets none out.
"""
```

**M1-10** (`check_at`)

SEARCH:
```
    if type(service) is AdmissionService:
        return service.hold(presented_id=presented_id, work_kind=work_kind, seam=seam, child=child)
    return NO_HOLD
```
REPLACE:
```
    if type(service) is AdmissionService:
        return service.hold(presented_id=presented_id, work_kind=work_kind, seam=seam, child=child)
    return NO_HOLD


def check_at(service: object, *, effect: str, presented_id: object) -> None:
    """The sink check of one effect point, in shadow: ``AdmissionService.check_ticket`` for an exact service, else nothing."""
    if type(service) is AdmissionService:  # an exact service; None, a double or any other object is passed over
        service.check_ticket(effect=effect, presented_id=presented_id)
    return None
```

### 7.3 M1: `tests/test_ad1346_admission_service.py`

**M1-11** (module docstring, T13 and T14)

SEARCH:
```
- T13 the service's inputs: no configuration field and no dependency beyond the facade, the stop record, an
      optional recorder (AD-1346 M3b) and an optional ticket registry (AD-1346 M3d2).
- T14 the decision files await nothing and, among them, only ``shadow`` and ``hold`` log; every file of the package
      imports only its allowlist (AD-1346 M3b's persistence files have allowlists of their own and may await).
```
REPLACE:
```
- T13 the service's inputs: no configuration field and no dependency beyond the facade, the stop record, an
      optional recorder (AD-1346 M3b), an optional ticket registry (AD-1346 M3d2) and an optional event loop (AD-1346
      M3d3a).
- T14 the decision files await nothing and, among them, only ``shadow``, ``hold`` and ``_check_ticket`` log; every file
      of the package imports only its allowlist (AD-1346 M3b's persistence files have allowlists of their own and may
      await).
```

**M1-12** (T14's allowlist)

SEARCH:
```
        "__future__", "collections.abc", "logging", "time", "typing", "probos.admission.carrier", "probos.admission.checks",
```
REPLACE:
```
        "__future__", "asyncio", "collections.abc", "logging", "time", "typing", "probos.admission.carrier", "probos.admission.checks",
```

**M1-13** (T13)

SEARCH:
```
async def test_the_service_reads_no_configuration_and_holds_only_its_two_dependencies_and_two_optional_parts(
    gate: AdmissionService,
) -> None:
    """T13: no configuration field; the facade, the stop record, a clock, an optional recorder, an optional ticket
    registry and its counters are all it holds. AD-1346 M3b renamed this test when it added the keyword-only
    ``recorder`` (None in this fixture). AD-1346 M3c added ``today_outcome`` (default None) and the ``_closed`` flag.
    AD-1346 M3d2 added the keyword-only ``tickets`` (None in this fixture) and renamed this test again. The service's
    source still names no configuration (``SystemConfig``, ``shadow_enabled``)."""
    source = (_PACKAGE / "service.py").read_text(encoding="utf-8")
    assert "SystemConfig" not in source and "shadow_enabled" not in source
    init = inspect.signature(AdmissionService.__init__).parameters
    assert list(init) == ["self", "identity_service", "stop_service", "clock", "recorder", "tickets"]
    assert init["clock"].kind is inspect.Parameter.KEYWORD_ONLY
    assert init["recorder"].kind is inspect.Parameter.KEYWORD_ONLY and init["recorder"].default is None
    assert init["tickets"].kind is inspect.Parameter.KEYWORD_ONLY and init["tickets"].default is None
    shadow = inspect.signature(AdmissionService.shadow).parameters
    assert list(shadow) == ["self", "presented_id", "work_kind", "seam", "origin", "origin_id", "today_outcome"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in shadow.items() if name != "self")
    assert shadow["today_outcome"].default is None
    assert set(vars(gate)) == {
        "_identities", "_stops", "_clock", "_recorder", "_tickets", "_closed", "_tally", "_latency", "_failures",
    }
    assert vars(gate)["_recorder"] is None and vars(gate)["_tickets"] is None and vars(gate)["_closed"] is False
```
REPLACE:
```
async def test_the_service_reads_no_configuration_and_holds_only_its_two_dependencies_and_three_optional_parts(
    gate: AdmissionService,
) -> None:
    """T13: no configuration field; the facade, the stop record, a clock, an optional recorder, an optional ticket
    registry, an optional event loop and its counters are all it holds. AD-1346 M3b renamed this test when it added the
    keyword-only ``recorder`` (None in this fixture). AD-1346 M3c added ``today_outcome`` (default None) and the
    ``_closed`` flag. AD-1346 M3d2 added the keyword-only ``tickets`` (None in this fixture) and renamed this test again.
    AD-1346 M3d3a added the keyword-only ``loop`` (None in this fixture) and the ``_off_loop`` counts, and renamed it a
    third time. The service's source still names no configuration (``SystemConfig``, ``shadow_enabled``)."""
    source = (_PACKAGE / "service.py").read_text(encoding="utf-8")
    assert "SystemConfig" not in source and "shadow_enabled" not in source
    init = inspect.signature(AdmissionService.__init__).parameters
    assert list(init) == ["self", "identity_service", "stop_service", "clock", "recorder", "tickets", "loop"]
    assert init["clock"].kind is inspect.Parameter.KEYWORD_ONLY
    assert init["recorder"].kind is inspect.Parameter.KEYWORD_ONLY and init["recorder"].default is None
    assert init["tickets"].kind is inspect.Parameter.KEYWORD_ONLY and init["tickets"].default is None
    assert init["loop"].kind is inspect.Parameter.KEYWORD_ONLY and init["loop"].default is None
    shadow = inspect.signature(AdmissionService.shadow).parameters
    assert list(shadow) == ["self", "presented_id", "work_kind", "seam", "origin", "origin_id", "today_outcome"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in shadow.items() if name != "self")
    assert shadow["today_outcome"].default is None
    assert set(vars(gate)) == {
        "_identities", "_stops", "_clock", "_recorder", "_tickets", "_loop", "_off_loop", "_closed", "_tally", "_latency",
        "_failures",
    }
    assert vars(gate)["_recorder"] is None and vars(gate)["_tickets"] is None and vars(gate)["_closed"] is False
    assert vars(gate)["_loop"] is None and vars(gate)["_off_loop"] == {}
```

**M1-14** (T14's docstring)

SEARCH:
```
    """T14: in the decision files no await, lock, file or connection call; logging only in ``shadow`` and, from AD-1346
    M3d2, ``hold``, and in ``service.py`` the clock only in ``shadow`` (``tickets.py``, added by AD-1346 M3d1, reads its
    registry's injected clock); the import allowlist per file of the package. AD-1346 M3b renamed this test and added the
    persistence files' allowlists when the package gained files that await and open a store."""
```
REPLACE:
```
    """T14: in the decision files no await, lock, file or connection call; logging only in ``shadow``, from AD-1346
    M3d2 ``hold`` and from AD-1346 M3d3a ``_check_ticket``, and in ``service.py`` the clock only in ``shadow``
    (``tickets.py``, added by AD-1346 M3d1, reads its registry's injected clock); the import allowlist per file of the
    package. AD-1346 M3b renamed this test and added the persistence files' allowlists when the package gained files that
    await and open a store. AD-1346 M3d3a added ``asyncio`` to ``service.py``'s allowlist, for ``get_running_loop`` and
    ``call_soon_threadsafe``, neither of which awaits."""
```

**M1-15** (T14's logging rule)

SEARCH:
```
    hold = function("src/probos/admission/service.py", "AdmissionService.hold")
    loggers = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "logger" and isinstance(n.ctx, ast.Load)]
    assert loggers and all(_within(n, shadow) or _within(n, hold) for n in loggers), "only shadow() and hold() log"
    assert any(_within(n, hold) for n in loggers), "premise: hold() logs its failure"
```
REPLACE:
```
    hold = function("src/probos/admission/service.py", "AdmissionService.hold")
    sink = function("src/probos/admission/service.py", "AdmissionService._check_ticket")
    loggers = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "logger" and isinstance(n.ctx, ast.Load)]
    assert loggers and all(_within(n, shadow) or _within(n, hold) or _within(n, sink) for n in loggers), (
        "only shadow(), hold() and _check_ticket() log"
    )
    assert any(_within(n, hold) for n in loggers), "premise: hold() logs its failure"
    assert any(_within(n, sink) for n in loggers), "premise: _check_ticket() logs its failure"
```

### 7.4 M1: `tests/test_ad1346_admission_ticket_issue.py` (an M3d2 file)

**M1-16** (module docstring, I11)

SEARCH:
```
- I11 in ``src`` only ``AdmissionService.hold`` reads and sets the carrier and only ``TicketHold.end`` resets it, and
      only ``carrier.py`` and ``service.py`` name it.
```
REPLACE:
```
- I11 in ``src`` only ``AdmissionService.hold`` sets the carrier, only it and, from AD-1346 M3d3a, the sink check
      ``AdmissionService.check_ticket`` read it, only ``TicketHold.end`` resets it, and only ``carrier.py`` and
      ``service.py`` name it.
```

**M1-17** (I11's set)

SEARCH:
```
        ("probos/admission/service.py", "AdmissionService.hold", "set"),
        ("probos/admission/carrier.py", "TicketHold.end", "reset"),
```
REPLACE:
```
        ("probos/admission/service.py", "AdmissionService.hold", "set"),
        ("probos/admission/service.py", "AdmissionService.check_ticket", "get"),  # AD-1346 M3d3a: the sink check
        ("probos/admission/carrier.py", "TicketHold.end", "reset"),
```

### 7.5 M2: `src/probos/tools/registry.py`

**M2-01** (import)

SEARCH:
```
from probos.admission.seam import shadow_at
```
REPLACE:
```
from probos.admission.seam import check_at, shadow_at
```

**M2-02** (the tool sink; two lines replace two, so the class's span does not change)

SEARCH:
```
        stopped = tool_refusal(self._stop_gate, agent_id, tool_id)
        # AD-1346 M3c: the shadow decision beside the check, with what the check did; it blocks nothing.
        shadow_at(self._admission, presented_id=agent_id, work_kind="tool_call", seam=SEAM_TOOL, origin="agent", origin_id=agent_id, refused=stopped is not None)
        if stopped is not None:
```
REPLACE:
```
        stopped = tool_refusal(self._stop_gate, agent_id, tool_id)
        shadow_at(self._admission, presented_id=agent_id, work_kind="tool_call", seam=SEAM_TOOL, origin="agent", origin_id=agent_id, refused=stopped is not None)
        check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)  # AD-1346 M3c, M3d3a: the shadow decision beside the check, then the carried work ticket's sink check; neither blocks.
        if stopped is not None:
```

### 7.6 M2: `src/probos/cognitive/llm_client.py`

**M2-03** (imports)

SEARCH:
```
from probos.types import LLMRequest, LLMResponse, Priority
from probos.attachments.store import AttachmentStore
```
REPLACE:
```
from probos.types import LLMRequest, LLMResponse, Priority
from probos.attachments.store import AttachmentStore
from probos.admission import AdmissionService
from probos.admission.seam import check_at
from probos.admission.taxonomy import SEAM_MODEL_CALL
```

**M2-04** (the class attribute)

SEARCH:
```
    _UNREACHABLE_THRESHOLD = 3  # BF-069: consecutive failures before tier is unreachable
```
REPLACE:
```
    _UNREACHABLE_THRESHOLD = 3  # BF-069: consecutive failures before tier is unreachable
    _admission: AdmissionService | None = None  # AD-1346 M3d3a (set_admission): None checks nothing
```

**M2-05** (the gateway's sink check)

SEARCH:
```
        LOW is an observability label — same semaphore as NORMAL.
        """
        # AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
```
REPLACE:
```
        LOW is an observability label — same semaphore as NORMAL.
        """
        check_at(self._admission, effect=SEAM_MODEL_CALL, presented_id=getattr(request, "agent_id", None))  # AD-1346 M3d3a: the model gateway's sink check of the carried work ticket, in shadow; it blocks nothing (getattr: D127).
        # AD-637f: CRITICAL uses reserved interactive slots; NORMAL and LOW share background
```

**M2-06** (the setter)

SEARCH:
```
    def set_attachment_store(self, store: AttachmentStore | None) -> None:
        """AD-731: deferred setter for the AttachmentStore.
```
REPLACE:
```
    def set_admission(self, service: AdmissionService | None) -> None:
        """AD-1346 M3d3a: late-bind the shadow admission service whose sink check ``complete`` makes first; None checks nothing.

        The runtime passes the service it built, or None when ``admission.shadow_enabled`` is false or the service was
        not built. The check blocks nothing and changes no request or response.
        """
        self._admission = service

    def set_attachment_store(self, store: AttachmentStore | None) -> None:
        """AD-731: deferred setter for the AttachmentStore.
```

### 7.7 M2: `src/probos/runtime.py`

**M2-07** (the service's loop; edits the line M3d2 wrote)

SEARCH:
```
            # unbuilt, as above. It is in memory, and nothing persists it.
            try:
                from probos.admission import AdmissionService
                from probos.admission.tickets import TicketRegistry

                tickets = TicketRegistry(self.agent_stops, max_depth=self.config.agentic_tools.delegation_max_depth)
                self.admission_service = AdmissionService(self.identity_service, self.agent_stops, recorder=shadow_recorder, tickets=tickets)
```
REPLACE:
```
            # unbuilt, as above. It is in memory, and nothing persists it.
            # AD-1346 M3d3a (D128): the service is given the loop running here; a sink check elsewhere hands its check to it.
            try:
                from probos.admission import AdmissionService
                from probos.admission.tickets import TicketRegistry

                tickets = TicketRegistry(self.agent_stops, max_depth=self.config.agentic_tools.delegation_max_depth)
                self.admission_service = AdmissionService(self.identity_service, self.agent_stops, recorder=shadow_recorder, tickets=tickets, loop=asyncio.get_running_loop())
```

**M2-08** (the gateway's wiring)

SEARCH:
```
            self.tool_registry.set_admission(self.admission_service)  # AD-1346 M3c: its shadow statement; None shadows nothing
        self.tool_permission_store = comm.tool_permission_store
```
REPLACE:
```
            self.tool_registry.set_admission(self.admission_service)  # AD-1346 M3c: its shadow statement; None shadows nothing
        if isinstance(self.llm_client, OpenAICompatibleClient):  # AD-1346 M3d3a (D127): the model gateway's sink check; None checks nothing
            self.llm_client.set_admission(self.admission_service)
        self.tool_permission_store = comm.tool_permission_store
```

### 7.8 M2: `tests/fixtures/ad1343_seam_census.py`

**M2-09** (`RECORDED`; anchors on M3d2's line)

SEARCH:
```
    "hold_at",  # AD-1346 M3d2: the work-ticket hold an admitted entry takes (tests/test_ad1346_admission_ticket_issue.py, I10)
}
```
REPLACE:
```
    "hold_at",  # AD-1346 M3d2: the work-ticket hold an admitted entry takes (tests/test_ad1346_admission_ticket_issue.py, I10)
    "check_at",  # AD-1346 M3d3a: the sink check at the tool sink and the model gateway (tests/test_ad1346_admission_ticket_sinks.py, SK7)
}
```

**M2-10** (the report's printed line)

SEARCH:
```
    print(f"{len(rows)} model call sites outside the crew modules (report only; #1601 M3 gates them)")
```
REPLACE:
```
    print(f"{len(rows)} model call sites outside the crew modules (report only; AD-1346 M3d3a checks the work ticket at the gateway, OpenAICompatibleClient.complete, not per call site)")
```

### 7.9 M2: `tests/fixtures/ad1343_seam_registry.py`

**M2-11**

SEARCH:
```
# Report only (never gated until #1601 M3): a hand classification of a model call outside the crew modules, keyed by
# (file, enclosing function). Empty today; ``model_call_report()`` classifies the rest structurally.
```
REPLACE:
```
# Report only: a hand classification of a model call outside the crew modules, keyed by (file, enclosing function).
# Empty today; ``model_call_report()`` classifies the rest structurally. AD-1346 M3d3a checks the work ticket at the
# gateway, ``OpenAICompatibleClient.complete``, not at each call site (tests/test_ad1346_admission_ticket_sinks.py,
# SK7 and SK8).
```

### 7.10 M2: `tests/test_ad1346_admission_service.py`

**M2-12** (T16's name and docstring)

SEARCH:
```
def test_only_the_wiring_and_the_shadowed_seams_name_the_service_or_import_the_package() -> None:
    """T16: the consumer census (#1604, property 11). Outside the package the runtime builds the service and shutdown
    closes and releases it. Each site AD-1346 M3c1 to M3c3 shadow reaches it the way it reaches its stop gate: ten files
    read ``admission_service`` from a runtime (``cognitive_agent.py``, ``agentic_dispatch.py``, ``proactive.py``,
    ``cognitive/dm/reply_pipeline.py``, ``tools/delegate_task_tool.py``, ``crew_synth.py``, ``crew_verifier.py``, which
    also hands it to a correction's projected registry, and three routers); ``tools/registry.py`` is handed it by
    ``set_admission``; ``ward_room_router.py`` and ``crew_finalizer.py`` take it in their constructors from
    ``startup/finalize.py``; and ``agent_work.py`` takes it in its constructor from ``runtime.py``. Each of those fourteen
    imports ``probos.admission``. The only routers that name the service or import the package are the three whose routes
    M3c2 shadows, and none of them is a module of #1604 property 11's routes, which are never admission-gated."""
```
REPLACE:
```
def test_only_the_wiring_the_shadowed_seams_and_the_model_gateway_name_the_service_or_import_the_package() -> None:
    """T16: the consumer census (#1604, property 11). Outside the package the runtime builds the service and shutdown
    closes and releases it. Each site AD-1346 M3c1 to M3c3 shadow reaches it the way it reaches its stop gate: ten files
    read ``admission_service`` from a runtime (``cognitive_agent.py``, ``agentic_dispatch.py``, ``proactive.py``,
    ``cognitive/dm/reply_pipeline.py``, ``tools/delegate_task_tool.py``, ``crew_synth.py``, ``crew_verifier.py``, which
    also hands it to a correction's projected registry, and three routers); ``tools/registry.py`` is handed it by
    ``set_admission``; ``ward_room_router.py`` and ``crew_finalizer.py`` take it in their constructors from
    ``startup/finalize.py``; and ``agent_work.py`` takes it in its constructor from ``runtime.py``. Each of those fourteen
    imports ``probos.admission``. From AD-1346 M3d3a the model gateway's module, ``cognitive/llm_client.py``, imports it
    too, and ``runtime.py`` hands ``OpenAICompatibleClient`` the service through its own ``set_admission``. AD-1346 M3d3a
    renamed this test. The only routers that name the service or import the package are the three whose routes M3c2
    shadows, and none of them is a module of #1604 property 11's routes, which are never admission-gated."""
```

**M2-13** (T16's importer set)

SEARCH:
```
        "probos/tools/registry.py", "probos/ward_room_router.py",
    }, sorted(importers)
```
REPLACE:
```
        "probos/tools/registry.py", "probos/ward_room_router.py", "probos/cognitive/llm_client.py",
    }, sorted(importers)
```

**M2-14** (module docstring, T16)

SEARCH:
```
- T16 outside the package the service is named only by ``runtime.py``, ``startup/shutdown.py``, ``startup/finalize.py``
      (which hands it to the Ward Room router and the crew session finalizer) and twelve shadowed-site files, which read
      it from a runtime or take it in a constructor; the package is imported only by ``runtime.py`` and the fourteen
      shadowed-site files; the only routers that do either are the three whose routes AD-1346 M3c2 shadows, and none of
      them serves a route #1604 property 11 keeps ungated.
```
REPLACE:
```
- T16 outside the package the service is named only by ``runtime.py``, ``startup/shutdown.py``, ``startup/finalize.py``
      (which hands it to the Ward Room router and the crew session finalizer) and twelve shadowed-site files, which read
      it from a runtime or take it in a constructor; the package is imported only by ``runtime.py``, the fourteen
      shadowed-site files and, from AD-1346 M3d3a, the model gateway's module ``cognitive/llm_client.py``; the only
      routers that do either are the three whose routes AD-1346 M3c2 shadows, and none of them serves a route #1604
      property 11 keeps ungated.
```

### 7.11 (no further pairs in M2)

### 7.12.N New file: `tests/test_ad1346_admission_ticket_sinks.py` (M3)

```python
"""AD-1346 M3d3a (#1604): the work ticket's sink checks at the tool sink and the model gateway, in shadow.

``probos.admission.seam.check_at`` hands one effect point's call to ``AdmissionService.check_ticket``, which asks the
``TicketRegistry`` about the ticket ``probos.admission.carrier.CURRENT_TICKET`` holds for that effect (``tool`` or
``model_call``); the registry counts the finding in its tally and the sink gets None. ``ToolRegistry.check_and_invoke``
calls it after its shadow statement and before today's stop answer, and ``OpenAICompatibleClient.complete`` as its
first statement. These tests drive it over a real ``IdentityService`` and a real ``AgentStopService`` under ``tmp_path``,
a ``TicketRegistry`` on a clock the test moves, a real ``ToolRegistry``, the real gateway with the request it would send
replaced by a canned answer, and the real run entry with a scripted body in place of the agentic loop; SK9 boots twice.

- SK1  the service refuses a ``loop`` that is not an event loop; with no registry, or once closed, a sink check
       counts nothing; with one it counts the registry's finding for what the carrier holds: ``ticket_missing``
       with nothing carried, ``ticket_live`` for a live ticket (with no principal compared when the presented id is
       None), ``ticket_principal_mismatch`` for another agent's id and ``ticket_expired`` once the hold ended; it
       returns None.
- SK2  ``check_at`` passes over None, a plain object and a look-alike, and forwards the effect and the presented id to
       an exact ``AdmissionService``.
- SK3  a sink check whose registry raises is counted in ``failures`` and logged at WARNING and then DEBUG, a logging
       call that raises is passed over, no finding is counted and the sink gets None (#1604 property 6 at the service).
- SK4  the thread rule (D128): a sink on another thread, or in a worker running a loop of its own as
       ``consultation/llm_decomposer.py`` does, reads the carrier there and hands the check to the service's loop, which
       counts it in ``off_loop_checks``; the registry's checks run on that loop's thread; a check handed over and then
       closed is not run; a hand-off to a closed loop raises nothing, runs no check and counts no failure.
- SK5  #1604 property 5, the run, in memory: inside the real run entry's hold, the next model call and tool call after
       a Captain's stop on the run's agent count ``ticket_revoked``, with the stop's id on the entry; before the stop
       both count ``ticket_live`` and today's tool check admits the call.
- SK6  #1604 property 5, the delegated child, in memory: a run the first run delegates holds a child of its ticket;
       after a Captain's stop on the delegating agent, the child's next model call and tool call count
       ``ticket_revoked`` while today's tool check still admits the child's call; a root run of a third agent afterwards
       counts ``ticket_live``.
- SK7  the sink census: in ``src``, ``check_at`` is called in exactly the two sinks, once each, with the sink's own
       service attribute, effect constant and presented id; at the tool sink it is the statement right after the
       shadow statement and right before ``if stopped is not None:``, at the gateway the first statement after the
       docstring.
- SK8  in ``src``, the classes whose base is named ``BaseLLMClient`` are ``OpenAICompatibleClient`` and
       ``MockLLMClient``, no class's base is named ``OpenAICompatibleClient``, ``_complete_inner`` is called only in
       ``OpenAICompatibleClient.complete``, and ``_call_openai`` and ``_call_ollama_native`` only inside
       ``OpenAICompatibleClient``.
- SK9  the wiring: on a boot whose LLM client is an ``OpenAICompatibleClient``, the runtime builds the service with its
       running loop and hands the service to the gateway, and a model call it makes then counts a ``model_call``
       finding; with ``admission.shadow_enabled`` false the runtime hands the gateway None.
- SK10 #1604 property 12 at the sinks, and property 6: the tool sink and the gateway answer byte for byte the same with
       the service and without it, with nothing carried, with a live ticket, while the registry's clock raises, and
       after a Captain's stop.

Each boot uses ``SystemConfig()`` with the naming ceremony, the proactive loop and QA turned off, as
``tests/test_ad1346_admission_ticket_issue.py`` does, and an ``OpenAICompatibleClient`` subclass that starts no health
probe and answers each request with a canned response in place of sending it. Besides each test's own loop, SK4
creates two event loops (one through ``asyncio.run`` in a worker thread, and one it closes at once) and starts worker
threads.
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import dataclasses
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
from probos.admission import AdmissionService
from probos.admission import service as service_module
from probos.admission.carrier import CURRENT_TICKET
from probos.admission.checks import resolve_principal
from probos.admission.seam import check_at
from probos.admission.taxonomy import SEAM_MODEL_CALL
from probos.admission.tickets import TicketFinding, TicketRegistry
from probos.agent_stop import SEAM_TOOL, AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests.fixtures.ad1343_seam_census import calls, census, function

INSTANCE_ID = "ad1346-m3d3a-ship"
VESSEL_NAME = "Ad1346m3d3a"
AGENT_A = "ad1346-m3d3a-agent-a"
AGENT_B = "ad1346-m3d3a-agent-b"
AGENT_C = "ad1346-m3d3a-agent-c"
_ABSENT = "ad1346_m3d3a_absent"  # a tool id no registry holds: the tool sink answers "not found" and runs nothing
_NOT_FOUND = f"Tool '{_ABSENT}' not found"
_SRC = Path(probos.__file__).resolve().parent
_LLM = "src/probos/cognitive/llm_client.py"
#: (file, sink) -> (the effect constant its check names, the expression it presents as the principal).
_SINK_SITES: dict[tuple[str, str], tuple[str, str]] = {
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke"): ("SEAM_TOOL", "agent_id"),
    (_LLM, "OpenAICompatibleClient.complete"): ("SEAM_MODEL_CALL", "getattr(request, 'agent_id', None)"),
}


class _Clock:
    """A monotonic clock that only the test moves, and that raises while ``boom`` is set."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.boom = False

    def __call__(self) -> float:
        if self.boom:
            raise RuntimeError("INJECTED clock failure")
        return self.now


class _ThreadRecordingRegistry(TicketRegistry):
    """A ticket registry that records the thread each ``check`` runs on."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.threads: list[int] = []

    def check(self, ticket: object, *, effect: str, presented_key: str = "") -> TicketFinding:
        self.threads.append(threading.get_ident())
        return super().check(ticket, effect=effect, presented_key=presented_key)


class _OfflineGateway(OpenAICompatibleClient):
    """The model gateway with no endpoint: it starts no health probe and answers with a canned response where it would
    send the request."""

    async def start_health_probe(self, interval_seconds: float = 30.0, emit_fn: Any = None) -> None:
        return None

    async def _complete_inner(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="ad1346-m3d3a", model="m", tier="standard")


class _ScriptedRun(WorkItemAgenticExecutor):
    """The real run entry (its stop check, shadow statement and hold) over a scripted body in place of the agentic loop."""

    def __init__(self, bodies: dict[str, Callable[[dict[str, Any]], Awaitable[str]]]) -> None:
        super().__init__(llm_client=None)
        self.bodies = bodies

    async def _run_reserved(self, **arguments: Any) -> Any:
        return await self.bodies[arguments["agent_id"]](arguments)


@pytest_asyncio.fixture
async def identity_registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry, started and commissioned as tests/test_ad1346_admission_service.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, identity_registry: AgentIdentityRegistry) -> IdentityService:
    """The real facade over the registry and a ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(identity_registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def tickets(stops: AgentStopService, clock: _Clock) -> TicketRegistry:
    """A production-shaped registry at the default delegation depth of 1, on the test's clock."""
    return TicketRegistry(stops, max_depth=1, clock=clock)


@pytest.fixture
def gate(identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry) -> AdmissionService:
    """A service built with no loop, so it checks in place."""
    return AdmissionService(identities, stops, tickets=tickets)


async def _settle() -> None:
    """Let the loop run the checks a sink elsewhere handed to it."""
    for _ in range(3):
        await asyncio.sleep(0)


def _tools(stops: AgentStopService, service: AdmissionService | None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def _gateway(service: AdmissionService | None) -> _OfflineGateway:
    client = _OfflineGateway()
    client.set_admission(service)
    return client


def _runtime(tools: ToolRegistry, service: AdmissionService) -> SimpleNamespace:
    """A runtime holding the tool registry (its stop gate) and the admission service; the run entry's other reads of a
    runtime (``getattr`` with a default) find nothing."""
    return SimpleNamespace(tool_registry=tools, admission_service=service)


async def _run(runner: _ScriptedRun, runtime: SimpleNamespace, agent_id: str, extra: dict[str, Any] | None = None) -> Any:
    """The real run entry: its stop check, shadow statement and hold, then the scripted body under the hold."""
    return await runner.run(agent_id=agent_id, instructions="i", task_text="t", runtime=runtime, extra_context=extra)


def _config(*, shadow_enabled: bool) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = shadow_enabled
    return config


async def _boot(tmp_path: Path, name: str, *, shadow_enabled: bool) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(shadow_enabled=shadow_enabled), data_dir=tmp_path / name, llm_client=_OfflineGateway())
    await runtime.start()
    return runtime


def _src_classes_and_calls(callees: frozenset[str]) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """In ``src/probos``: (file, class, base) for each class whose base, by simple name, is ``BaseLLMClient`` or
    ``OpenAICompatibleClient``; and (file, enclosing qualified name, callee) for each call of a name in ``callees``."""
    bases: set[tuple[str, str, str]] = set()
    found: set[tuple[str, str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parents[1]).as_posix()
        text = path.read_text(encoding="utf-8")
        if "LLMClient" not in text and "OpenAICompatibleClient" not in text and not any(c in text for c in callees):
            continue

        def visit(node: ast.AST, scope: tuple[str, ...], rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    for base in child.bases:
                        name = ast.unparse(base).split(".")[-1]
                        if name in ("BaseLLMClient", "OpenAICompatibleClient"):
                            bases.add((rel, child.name, name))
                if isinstance(child, ast.Call):
                    func = child.func
                    callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                    if callee in callees:
                        found.add((rel, ".".join(scope), callee))
                named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                visit(child, (*scope, child.name) if named else scope)

        visit(ast.parse(text, filename=rel), ())
    return bases, found


async def test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, gate: AdmissionService,
) -> None:
    """SK1 (kills SKX-1, SKX-5, SKX-6, SKX-7, SKX-10): no registry, or a closed service, counts nothing; each of the
    registry's findings for nothing carried, a live ticket, another agent's id and an ended ticket is counted once."""
    with pytest.raises(TypeError, match="event loop"):
        AdmissionService(identities, stops, loop=object())  # type: ignore[arg-type]
    assert resolve_principal(AGENT_A, identities).key == AGENT_A, "premise: the test's ids do not resolve; each is its own key"
    bare = AdmissionService(identities, stops)
    assert bare.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert bare.failures == 0 and tickets.tally() == {}
    assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=None) is None
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=None)
        gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_B)
    finally:
        held.end()
    token = CURRENT_TICKET.set(held.ticket)
    try:
        gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=AGENT_A)
    finally:
        CURRENT_TICKET.reset(token)
    expected = {
        ("tool", "ticket_missing"): 1, ("model_call", "ticket_missing"): 1, ("issue", "ticket_issued"): 1,
        ("tool", "ticket_live"): 1, ("model_call", "ticket_live"): 1, ("tool", "ticket_principal_mismatch"): 1,
        ("model_call", "ticket_expired"): 1,
    }
    assert tickets.tally() == expected
    gate.close()
    assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert tickets.tally() == expected, "a closed service checks nothing"
    assert gate.failures == 0 and gate.off_loop_checks() == {}


async def test_check_at_calls_only_an_exact_service_and_forwards_the_effect_and_the_presented_id(
    gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """SK2 (kills SKX-11, SKX-17)."""

    class _LookAlike:
        calls = 0

        def check_ticket(self, **kwargs: Any) -> None:
            _LookAlike.calls += 1

    for other in (None, object(), _LookAlike()):
        assert check_at(other, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert _LookAlike.calls == 0 and tickets.tally() == {}
    assert check_at(gate, effect=SEAM_MODEL_CALL, presented_id=AGENT_A) is None
    assert tickets.tally() == {("model_call", "ticket_missing"): 1}
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        assert check_at(gate, effect=SEAM_TOOL, presented_id=AGENT_B) is None
    finally:
        held.end()
    assert tickets.tally() == {
        ("model_call", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("tool", "ticket_principal_mismatch"): 1,
    }, "check_at forwards the presented id: another agent's id is compared with the ticket's principal"


async def test_a_sink_check_that_raises_is_counted_and_logged_and_the_sink_gets_none(
    gate: AdmissionService, tickets: TicketRegistry, clock: _Clock, caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SK3 (kills SKX-9): #1604 property 6 at the service."""
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        clock.boom = True
        with caplog.at_level(logging.DEBUG, logger="probos.admission.service"):
            assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
            assert gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=AGENT_A) is None
        levels = [r.levelno for r in caplog.records if "AD-1346 M3d3a" in r.getMessage()]
        assert levels == [logging.WARNING, logging.DEBUG] and gate.failures == 2

        def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("INJECTED logging failure")

        monkeypatch.setattr(service_module.logger, "log", _raise)
        assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
        assert gate.failures == 3
    finally:
        clock.boom = False
        monkeypatch.undo()
        held.end()
    assert tickets.tally() == {("issue", "ticket_issued"): 1}, "a check that raised counted no finding"


async def test_a_sink_off_the_services_loop_hands_its_check_to_that_loop(
    identities: IdentityService, stops: AgentStopService, clock: _Clock,
) -> None:
    """SK4 (kills SKX-2, SKX-3, SKX-4, SKX-5, SKX-8): the thread rule (D128)."""
    loop_thread = threading.get_ident()
    registry = _ThreadRecordingRegistry(stops, max_depth=1, clock=clock)
    service = AdmissionService(identities, stops, tickets=registry, loop=asyncio.get_running_loop())
    held = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"

    async def _model_call_in_a_worker_loop() -> None:
        check_at(service, effect=SEAM_MODEL_CALL, presented_id=AGENT_A)

    try:
        await asyncio.to_thread(check_at, service, effect=SEAM_TOOL, presented_id=AGENT_A)
        await _settle()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            await asyncio.wrap_future(pool.submit(lambda: asyncio.run(_model_call_in_a_worker_loop())))
        await _settle()
        assert check_at(service, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    finally:
        held.end()
    assert registry.threads == [loop_thread] * 3, "each check ran on the service's loop's thread"
    assert registry.tally() == {
        ("issue", "ticket_issued"): 1, ("tool", "ticket_live"): 2, ("model_call", "ticket_missing"): 1,
    }, "asyncio.to_thread copies the caller's context; the submitted worker's check carried no ticket"
    assert service.off_loop_checks() == {"tool": 1, "model_call": 1}, "the check made on the loop is not counted as handed over"
    worker = threading.Thread(target=check_at, args=(service,), kwargs={"effect": SEAM_TOOL, "presented_id": AGENT_A})
    worker.start()
    worker.join()
    service.close()
    await _settle()
    assert registry.threads == [loop_thread] * 3 and service.off_loop_checks() == {"tool": 1, "model_call": 1}, (
        "a check handed over before close is not run after it"
    )
    closed = asyncio.new_event_loop()
    closed.close()
    orphan = AdmissionService(identities, stops, tickets=registry, loop=closed)
    assert check_at(orphan, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert orphan.failures == 0 and service.failures == 0 and registry.threads == [loop_thread] * 3


async def test_a_captains_stop_reaches_the_next_model_and_tool_call_of_an_in_flight_run(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """SK5 (kills SKX-12, SKX-13): #1604 property 5 for the run's own calls, counted in memory."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    seen: dict[str, Any] = {}

    async def body(arguments: dict[str, Any]) -> str:
        seen["ticket"] = CURRENT_TICKET.get()
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))
        seen["tool_before"] = await tools.check_and_invoke(AGENT_A, _ABSENT, {})
        seen["tally_before"] = tickets.tally()
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the Captain stops a run in flight")
        seen["stop_id"] = issued.record.stop_id
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))
        seen["tool_after"] = await tools.check_and_invoke(AGENT_A, _ABSENT, {})
        return "ran"

    assert await _run(_ScriptedRun({AGENT_A: body}), _runtime(tools, service), AGENT_A) == "ran"
    assert seen["ticket"] is not None, "premise: the run entry's hold carried the run's ticket into its body"
    assert seen["tally_before"] == {
        ("issue", "ticket_issued"): 1, ("model_call", "ticket_live"): 1, ("tool", "ticket_live"): 1,
    }
    assert seen["tool_before"].error == _NOT_FOUND, "premise: before the stop today's check admits the call"
    assert tickets.tally() == {**seen["tally_before"], ("model_call", "ticket_revoked"): 1, ("tool", "ticket_revoked"): 1}
    assert seen["tool_after"].error.startswith(f"Tool '{_ABSENT}' was not run."), "today's check refuses the stopped agent"
    entry = tickets.entry(seen["ticket"])
    assert entry is not None and entry.stop_id == seen["stop_id"] and entry.revoked_at is not None
    assert service.failures == 0


async def test_a_captains_stop_reaches_a_delegated_childs_next_calls_and_not_a_root_of_another_agent(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """SK6 (kills SKX-12, SKX-13 too): #1604 property 5 for a delegated child, counted in memory, with a root run of
    another agent as the control that does not differ."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    runtime = _runtime(tools, service)
    seen: dict[str, Any] = {}

    async def parent(arguments: dict[str, Any]) -> str:
        seen["parent"] = CURRENT_TICKET.get()
        return await _run(runner, runtime, AGENT_B, {"_delegation_depth": 1})

    async def child(arguments: dict[str, Any]) -> str:
        seen["child"] = CURRENT_TICKET.get()
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_B))
        seen["tool_before"] = await tools.check_and_invoke(AGENT_B, _ABSENT, {})
        seen["tally_before"] = tickets.tally()
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the Captain stops the delegating agent")
        seen["stop_id"] = issued.record.stop_id
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_B))
        seen["tool_after"] = await tools.check_and_invoke(AGENT_B, _ABSENT, {})
        return "child ran"

    async def other(arguments: dict[str, Any]) -> str:
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_C))
        seen["other_tool"] = await tools.check_and_invoke(AGENT_C, _ABSENT, {})
        return "other ran"

    runner = _ScriptedRun({AGENT_A: parent, AGENT_B: child, AGENT_C: other})
    assert await _run(runner, runtime, AGENT_A) == "child ran"
    after_child = tickets.tally()
    assert await _run(runner, runtime, AGENT_C) == "other ran"
    parent_entry, child_entry = tickets.entry(seen["parent"]), tickets.entry(seen["child"])
    assert parent_entry is not None and child_entry is not None
    assert child_entry.parent_id == parent_entry.ticket_id and child_entry.depth == 1, (
        "premise: the delegated run holds a child of the delegating run's ticket"
    )
    assert seen["tally_before"] == {
        ("issue", "ticket_issued"): 2, ("model_call", "ticket_live"): 1, ("tool", "ticket_live"): 1,
    }
    assert seen["tool_before"].error == _NOT_FOUND, "premise: before the stop today's check admits the child's call"
    assert after_child == {**seen["tally_before"], ("model_call", "ticket_revoked"): 1, ("tool", "ticket_revoked"): 1}
    assert seen["tool_after"].error == _NOT_FOUND and stops.stop_for(AGENT_B) is None, (
        "today's check admits the child's call: its own agent is not stopped"
    )
    assert child_entry.stop_id == seen["stop_id"] and parent_entry.revoked_at is not None
    assert tickets.tally() == {
        **after_child, ("issue", "ticket_issued"): 3, ("model_call", "ticket_live"): 2, ("tool", "ticket_live"): 2,
    }, "a root run of another agent is not reached by the stop"
    assert seen["other_tool"].error == _NOT_FOUND and service.failures == 0


def test_the_sink_check_is_called_once_in_each_of_the_two_sinks_in_its_place() -> None:
    """SK7: the sink census, in the manner of 9b, 9c and I10."""
    found = {(c.file, c.function) for c in census() if c.callee == "check_at"}
    assert found == set(_SINK_SITES), sorted(found)
    for (rel, qualname), (effect, presented) in _SINK_SITES.items():
        fn = function(rel, qualname)
        sinks = [n for n in ast.walk(fn) if calls("check_at")(n)]
        assert len(sinks) == 1, (qualname, len(sinks))
        call = sinks[0]
        assert [ast.unparse(a) for a in call.args] == ["self._admission"], qualname
        assert {k.arg: ast.unparse(k.value) for k in call.keywords} == {"effect": effect, "presented_id": presented}, qualname
        index = next((i for i, stmt in enumerate(fn.body) if isinstance(stmt, ast.Expr) and stmt.value is call), None)
        assert index is not None, (qualname, "the sink check is a statement of the function's own body")
        if qualname == "ToolRegistry.check_and_invoke":
            before, after = fn.body[index - 1], fn.body[index + 1]
            assert isinstance(before, ast.Expr) and calls("shadow_at")(before.value), qualname
            assert isinstance(after, ast.If) and ast.unparse(after.test) == "stopped is not None", qualname
        else:
            docstring = fn.body[0]
            assert index == 1 and isinstance(docstring, ast.Expr) and isinstance(docstring.value, ast.Constant), qualname


def test_in_src_the_gateway_alone_calls_the_completion_internals_and_the_model_clients_are_the_two_known() -> None:
    """SK8: the facts that make the gateway's first statement a check of every completion an ``OpenAICompatibleClient``
    sends through ``complete``."""
    bases, found = _src_classes_and_calls(frozenset({"_complete_inner", "_call_openai", "_call_ollama_native"}))
    assert bases == {(_LLM, "OpenAICompatibleClient", "BaseLLMClient"), (_LLM, "MockLLMClient", "BaseLLMClient")}, sorted(bases)
    inner = {(rel, fn, callee) for rel, fn, callee in found if callee == "_complete_inner"}
    assert inner == {(_LLM, "OpenAICompatibleClient.complete", "_complete_inner")}, sorted(inner)
    transports = {(rel, fn.split(".")[0], callee) for rel, fn, callee in found if callee != "_complete_inner"}
    assert transports == {
        (_LLM, "OpenAICompatibleClient", "_call_openai"), (_LLM, "OpenAICompatibleClient", "_call_ollama_native"),
    }, sorted(found)


async def test_the_runtime_gives_the_service_its_loop_and_hands_it_to_the_model_gateway(tmp_path: Path) -> None:
    """SK9 (kills SKX-14, SKX-15, SKX-16): the wiring, on two boots."""
    on = await _boot(tmp_path, "on", shadow_enabled=True)
    try:
        service = on.admission_service
        assert service is not None and isinstance(on.llm_client, _OfflineGateway), "premise: the boot built the service"
        assert vars(service)["_loop"] is asyncio.get_running_loop()
        assert vars(on.llm_client)["_admission"] is service
        registry = vars(service)["_tickets"]
        before = registry.tally().get(("model_call", "ticket_missing"), 0)
        await on.llm_client.complete(LLMRequest(prompt="ad1346-m3d3a"))
        assert registry.tally().get(("model_call", "ticket_missing"), 0) > before
    finally:
        await on.stop()
    off = await _boot(tmp_path, "off", shadow_enabled=False)
    try:
        assert off.admission_service is None and vars(off.llm_client)["_admission"] is None
    finally:
        await off.stop()


async def test_with_and_without_the_service_the_sinks_answer_byte_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, clock: _Clock,
) -> None:
    """SK10: #1604 property 12 at the two sinks, and property 6: a check that raises changes no answer."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())

    async def drive(with_service: bool) -> str:
        tools = _tools(stops, service if with_service else None)
        gateway = _gateway(service if with_service else None)
        answers: list[dict[str, Any]] = []

        async def both() -> None:
            answers.append(dataclasses.asdict(await tools.check_and_invoke(AGENT_A, _ABSENT, {})))
            answers.append(dataclasses.asdict(await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))))

        await both()
        held = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            await both()
            clock.boom = True
            try:
                await both()
            finally:
                clock.boom = False
        finally:
            held.end()
        return json.dumps(answers, sort_keys=True, default=repr)

    first = (await drive(True), await drive(False))
    await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the golden test's stop")
    second = (await drive(True), await drive(False))
    assert first[0] == first[1] and second[0] == second[1]
    assert first[0] != second[0], "premise: the stop changes today's answer, so the comparison can see a difference"
    assert ("tool", "ticket_revoked") in tickets.tally() and service.failures == 4, (
        "premise: with the service the sinks checked, saw the stop and counted each raising check"
    )
```

## 8. Tracking (M4's commit)

**Date rule.** If M4 is committed on a date other than 2026-10-30, the Builder substitutes the commit date for `2026-10-30` in exactly two strings, both new:
- the new paragraph's head `**AD-1346 (2026-10-30), #1604 M3d3a -- ` in M4-01's REPLACE;
- the new heading `### AD-1346 M3d3a -- the work ticket's sink checks at the tool sink and the model gateway, in shadow (2026-10-30, #1604)` in M4-02's REPLACE.

M4-01's SEARCH text and the M3d2 head its REPLACE keeps (`**AD-1346 (2026-10-30), #1604 M3d2 -- `) keep 2026-10-30. The commit date is the committing machine's local date when M4 is committed, not the UTC date. No other deviation is permitted.

Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode), and commit `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. Two bullets for `DECISIONS.md` are added in a later docs commit, after the reviewed commit: the campaign of record and D132's measurement.

**Where the entries land.**
- M4-01 puts the new paragraph between the title line `# ProbOS Progress` and M3d2's paragraph (`PROGRESS.md:3` on `93af6ae4`). `PROGRESS.md` runs newest first.
- M4-02 puts M3d3a's entry (its heading, paragraph and bullets, the last of them its `*Reversal.*` bullet, then a blank line) directly above the heading that follows M3d2's entry, `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)` (`DECISIONS.md:1022` on `93af6ae4`, `:1023` on `302e6bf9`). M3d3a's entry therefore follows M3d2's (`:1008`); the AD-1346 entries run oldest first.
- Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M4-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d2 -- 
```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-10-30), #1604 M3d3a -- the work ticket's sink checks at the tool sink and the model gateway, in shadow.** `ToolRegistry.check_and_invoke`, right after its shadow statement and before today's stop answer, and `OpenAICompatibleClient.complete`, as its first statement, call `probos.admission.seam.check_at`; `AdmissionService.check_ticket` then asks the `TicketRegistry` about the ticket `probos.admission.carrier.CURRENT_TICKET` holds for that effect point (`tool`, `model_call`), and the registry counts the finding in its in-memory tally, so a call with nothing carried counts `ticket_missing` for its effect. The runtime gives the service its event loop and hands the service to an `OpenAICompatibleClient` with `set_admission`; a sink on another thread, or on another thread's loop, reads the carrier there and hands the check to that loop with `call_soon_threadsafe`, so the sink checks run on that loop's thread. Crossing tests drive the real run entry with no vessel and no network: after a Captain's stop, the next model and tool call of a run in flight, and of a run it delegated, count `ticket_revoked`, while a root run of another agent still counts `ticket_live`. Nothing blocks, charges or is persisted, and with `admission.shadow_enabled` false no service is built and the sinks check nothing. The persisted sink record is M3d3b. The contract is `prompts/ad-1346-m3d3a-ticket-sinks.md`.

**AD-1346 (2026-10-30), #1604 M3d2 -- 
```

**M4-02** (`DECISIONS.md`)

SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1346 M3d3a -- the work ticket's sink checks at the tool sink and the model gateway, in shadow (2026-10-30, #1604)

AD-1346 M3d3a checks the work ticket of epic #1601's design note at the two effect points its scope names, the first of two M3d3 slices; the persisted sink record is M3d3b. It advances #1604 property 5 (counted in memory), property 1 (the sink census) and property 12 at the sinks, and fixes the method of property 7's measurement. The contract is `prompts/ad-1346-m3d3a-ticket-sinks.md`.

- *D123 (the split).* M3d3a holds the sink checks, the thread rule, the census and the crossing tests; M3d3b adds the persisted record in `admission_shadow.db` (version 1), the issue findings and an executed older-build check. Rejected: one slice (about fifty pairs), and the record first (a writer with no producer).
- *D124, D125 (the check).* `AdmissionService.check_ticket`, reached through `probos.admission.seam.check_at` for an exact service, reads `CURRENT_TICKET` in the caller's context and asks the registry about it at the effect point, comparing the principal key `decide` gives the presented id when there is one; the registry counts the finding, and the sink gets None. Rejected: a sink that calls the registry itself, bypassing the service's `except Exception`, `close` and thread rule.
- *D126 (the tool sink).* `check_at` is the statement right after `ToolRegistry.check_and_invoke`'s shadow statement and before today's stop answer, so a call today's stop refuses is checked too; the shadow statement's comment moves onto it, so the class's span does not change. Rejected: a combined shadow and check call, which would change the shadow census of sixteen sites.
- *D127 (the model gateway).* `check_at` is the first statement of `OpenAICompatibleClient.complete`; the runtime hands the gateway its service with `set_admission`, as the tool registry is handed it, and None with the switch off. Rejected: carrying the service in the context, under which work with no hold would record nothing.
- *D128 (threads).* The runtime builds the service with its running loop. A sink on any other thread or loop reads the carrier there and hands the check to that loop with `call_soon_threadsafe`, so the sink checks run on that loop's thread; checks handed over and answered are counted by effect, and a hand-off to a closed loop counts nothing. Rejected: checking in place (the registry holds no lock) and skipping such sinks (no evidence for register R31).
- *Tests.* One new file (`tests/test_ad1346_admission_ticket_sinks.py`, SK1 to SK10): the crossing tests of property 5 drive the real run entry with no vessel and no network; T13, T14, T16 and I11 are updated; the seam census records `check_at`.
- *Residual, accepted.* Register R46 to R51 of the contract.
- *Reversal.* Revert the M3d3a commits; nothing is persisted.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

## 9. What this does NOT change

- `decide`, the checks, `shadow`, `shadow_at`, `hold`, `hold_at`, `TicketHold`, the recorder, the store, the report, every vocabulary in `taxonomy.py`, `TICKET_FINDING_KEYS` and `SCHEMA_VERSION`.
- Any line of `src/probos/admission/carrier.py` or `src/probos/admission/tickets.py`.
- Every `shadow_at` and `hold_at` call, `SHADOW_SITES`, `SHADOW_PENDING`, 9a to 9c, T15, G2, I1 to I10.
- `MockLLMClient`, `BaseLLMClient`, `consultation/llm_decomposer.py`, `DelegateTaskTool`, the crew modules, `AgentStopService` and the Captain's stop and lift routes.
- `config.py`, `config/system.yaml`, the profiles, the config facade baseline and reference.
- `docs/development/store-baseline.yaml`, `docs/development/architecture-baseline.yaml`, the seam manifest and `startup/*`.

## 10. Mutation rows (one campaign of record on the M3 tree, after an unmutated baseline passes; run on the Captain's Windows host)

Group and its `--tests`: every SKX row runs against `tests/test_ad1346_admission_ticket_sinks.py`. No two rows mutate the same line. Each Line is a stripped line that occurs once in its file at its milestone's tree and at M3's tree. No row is expected to be equivalent.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| SKX-1 | M1 | `src/probos/admission/service.py` | `ticket = CURRENT_TICKET.get()` | `ticket = None` | `test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none` |
| SKX-2 | M1 | `src/probos/admission/service.py` | `if self._loop is None or _running_loop() is self._loop:` | `if True:` | `test_a_sink_off_the_services_loop_hands_its_check_to_that_loop` |
| SKX-3 | M1 | `src/probos/admission/service.py` | `self._loop.call_soon_threadsafe(self._check_ticket, ticket, effect, presented_id, True)` | `pass` | `test_a_sink_off_the_services_loop_hands_its_check_to_that_loop` |
| SKX-4 | M1 | `src/probos/admission/service.py` | `except Exception:  # noqa: BLE001 -- D128: a hand-off that raises (a closed loop) checks and counts nothing` | `except ZeroDivisionError:` | `test_a_sink_off_the_services_loop_hands_its_check_to_that_loop` |
| SKX-5 | M1 | `src/probos/admission/service.py` | `if self._closed or self._tickets is None:  # no registry, or closed (a check handed over before close included): nothing is checked` | `if False:` | `test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none`, `test_a_sink_off_the_services_loop_hands_its_check_to_that_loop` |
| SKX-6 | M1 | `src/probos/admission/service.py` | `key = resolve_principal(presented_id, self._identities).key if type(presented_id) is str and presented_id else ""` | `key = ""` | `test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none` |
| SKX-7 | M1 | `src/probos/admission/service.py` | `self._tickets.check(ticket, effect=effect, presented_key=key)` | `self._tickets.check(ticket, effect=effect)` | `test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none` |
| SKX-8 | M1 | `src/probos/admission/service.py` | `self._off_loop[effect] = self._off_loop.get(effect, 0) + 1` | `pass` | `test_a_sink_off_the_services_loop_hands_its_check_to_that_loop` |
| SKX-9 | M1 | `src/probos/admission/service.py` | `except Exception:  # D129: counted and logged; the sink gets None` | `except ZeroDivisionError:` | `test_a_sink_check_that_raises_is_counted_and_logged_and_the_sink_gets_none` |
| SKX-10 | M1 | `src/probos/admission/service.py` | `if loop is not None and not isinstance(loop, asyncio.AbstractEventLoop):` | `if False:` | `test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none` |
| SKX-11 | M1 | `src/probos/admission/seam.py` | `if type(service) is AdmissionService:  # an exact service; None, a double or any other object is passed over` | `if False:` | `test_check_at_calls_only_an_exact_service_and_forwards_the_effect_and_the_presented_id` |
| SKX-12 | M2 | `src/probos/tools/registry.py` | `check_at(self._admission, effect=SEAM_TOOL, presented_id=agent_id)  # AD-1346 M3c, M3d3a: the shadow decision beside the check, then the carried work ticket's sink check; neither blocks.` | `pass` | `test_a_captains_stop_reaches_the_next_model_and_tool_call_of_an_in_flight_run` |
| SKX-13 | M2 | `src/probos/cognitive/llm_client.py` | `check_at(self._admission, effect=SEAM_MODEL_CALL, presented_id=getattr(request, "agent_id", None))  # AD-1346 M3d3a: the model gateway's sink check of the carried work ticket, in shadow; it blocks nothing (getattr: D127).` | `pass` | `test_a_captains_stop_reaches_the_next_model_and_tool_call_of_an_in_flight_run` |
| SKX-14 | M2 | `src/probos/cognitive/llm_client.py` | `self._admission = service` | `pass` | `test_the_runtime_gives_the_service_its_loop_and_hands_it_to_the_model_gateway` |
| SKX-15 | M2 | `src/probos/runtime.py` | `self.llm_client.set_admission(self.admission_service)` | `pass` | `test_the_runtime_gives_the_service_its_loop_and_hands_it_to_the_model_gateway` |
| SKX-16 | M2 | `src/probos/runtime.py` | `self.admission_service = AdmissionService(self.identity_service, self.agent_stops, recorder=shadow_recorder, tickets=tickets, loop=asyncio.get_running_loop())` | `self.admission_service = AdmissionService(self.identity_service, self.agent_stops, recorder=shadow_recorder, tickets=tickets)` | `test_the_runtime_gives_the_service_its_loop_and_hands_it_to_the_model_gateway` |
| SKX-17 | M1 | `src/probos/admission/seam.py` | `service.check_ticket(effect=effect, presented_id=presented_id)` | `service.check_ticket(effect=effect, presented_id=None)` | `test_check_at_calls_only_an_exact_service_and_forwards_the_effect_and_the_presented_id` |

How the rows are killed (each SK<n> here is the case whose test function the row's Killed-by cell names):
- **SKX-1:** the live-ticket checks count `ticket_missing`.
- **SKX-2:** the `asyncio.to_thread` check runs on the worker thread, so `threads[0]` is not the loop's.
- **SKX-3:** nothing is counted for the two checks handed over.
- **SKX-4:** the closed loop's `RuntimeError` escapes `check_at`.
- **SKX-5:** in SK1 the service with no registry calls `check` on None and counts a failure; in SK4 the check handed over before `close` runs after it.
- **SKX-6, SKX-7:** the other agent's id counts `ticket_live`, not `ticket_principal_mismatch`.
- **SKX-8:** `off_loop_checks()` stays empty.
- **SKX-9:** the clock's `RuntimeError` escapes `check_ticket`.
- **SKX-10:** `loop=object()` is accepted.
- **SKX-11:** `check_at(gate, ...)` counts nothing.
- **SKX-12, SKX-13:** the tally before the stop lacks that sink's `ticket_live`.
- **SKX-14:** `vars(on.llm_client)` has no `_admission`.
- **SKX-15:** `vars(on.llm_client)` has no `_admission`.
- **SKX-16:** `_loop` is None.
- **SKX-17:** the other agent's id that SK2 presents through `check_at` counts `ticket_live`, not `ticket_principal_mismatch`.

M3d2's IX-13 names the runtime line SKX-16 replaces. M3d2's campaign runs on M3d2's own M3 tree, so it is unaffected.

## 11. Verified Against Codebase (2026-10-30, read on `93af6ae4`, tree `21172897`)

```
git rev-parse HEAD HEAD^{tree} origin/main  -> 93af6ae452e1..., 21172897775478aa..., 1ffbdc612b06...
git log --oneline -8                        -> 93af6ae4 (M3d2 M4), 1900f15f (M3), 16436b0b (M2), deda7ec3 (M1), 550a53d2 (M3d2 contract), 1ffbdc61 (merge #1711), 146974c2, 2e461ee3
git status --short                          -> (nothing)
git ls-files --eol <the edited src and test files, PROGRESS.md, DECISIONS.md> -> i/lf w/crlf (anchor greps use \r?$)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING: AD-1355 (GitHub issue titles, all states); NEXT: AD-1356

src/probos/admission/service.py
  :15-20   docstring tail (M1-01); :22-26 imports (M1-02); :42-44 _WORK_SCOPE, _NO_CEILINGS (M1-03)
  :50-58   __init__ signature, tickets at :57 (M1-04); :65-72 tickets check and attributes (M1-05); :73-75 counters
  :107-142 shadow (`if self._closed:` at :119); :144-146 close (M1-06); :148-185 hold (`return NO_HOLD` at :160, :185)
  :187     _count (M1-07's SEARCH ends here); :200-203 failures (M1-08)
src/probos/admission/seam.py:1-14 docstring (M1-09); :36-40 hold_at (M1-10)
src/probos/admission/carrier.py:25 CURRENT_TICKET; :37-53 TicketHold.end
src/probos/admission/checks.py:61-69 resolve_principal (slot key when it resolves, else the presented id)
src/probos/admission/tickets.py:144-164 TicketFinding (work_kind "" by default); :254-286 check (ticket None -> ticket_missing; clock read at :276); :298-310 release; :312-318 entry; :320-322 tally; :359-392 _liveness (stop_for walk, :386-390); :394-406 _revoke_tree
src/probos/tools/registry.py:16 import (M2-01); :85 class ToolRegistry (last top-level class; 582 lines by wc -l); :109 _admission; :134-145 set_stop_gate, stop_gate, set_admission; :362 check_and_invoke; :395-399 stop check, M3c comment, shadow_at, `if stopped` (M2-02); :415-416 not-found answer
src/probos/cognitive/llm_client.py:3 `from __future__ import annotations`; :19 typing imports (no TYPE_CHECKING); :23-24 imports (M2-03); :243 BaseLLMClient; :265 OpenAICompatibleClient; :286 (M2-04); :1236-1246 start_health_probe; :1293-1300 stop_health_probe; :1458 complete; :1467-1469 (M2-05); :1475 the 30 s lane wait; :1485 _complete_inner call; :2167, :2172 transports; :2179-2187 set_attachment_store (M2-06); :2684 MockLLMClient
src/probos/runtime.py:5 import asyncio; :108 imports OpenAICompatibleClient; :1004 llm_client; :2779 start; :2950-2958 the service's try (M2-07); :3422-3426 tool registry wiring (M2-08)
src/probos/cognitive/agentic_dispatch.py:2438 __init__(*, llm_client); :2703-2716 run's stop check, shadow, hold; :2761 fault_observer_for; :2763-2769 browser lookup then `return await self._run_reserved(**arguments)`; :2770-2771 finally end
src/probos/agent_stop.py:298-301 StopIssued.record; :376-380 stop_for; :406-436 issue_stop (any non-empty id); :580-588 tool_refusal text "Tool {tool_id!r} was not run. ..."; :603-612 refuse_new_run reads runtime.tool_registry.stop_gate
src/probos/fault_detection.py:440-452 fault_observer_for (None for an object with neither attribute)
src/probos/substrate/durable_events.py:239-247, :553-557 the on-loop / call_soon_threadsafe / RuntimeError precedent
src/probos/consultation/llm_decomposer.py:146-149 complete under asyncio.run in a ThreadPoolExecutor worker
src/probos/tools/browser/loop_host.py:15-23 (marshals at the page boundary), :217 run_coroutine_threadsafe
src/probos/channels/discord_adapter.py:178, :190, :208 teardown loops
src/probos/startup/finalize.py:4313-4321 awaits llm_client.start_health_probe when it is a coroutine function
src/probos/__main__.py:335 production OpenAICompatibleClient; :376 MockLLMClient fallback; :655-656 set_attachment_store
src/probos/config.py:3581 `shadow_enabled: bool = True`
src/probos/types.py:307-331 LLMRequest (agent_id: str | None); :335-374 LLMResponse (no time-varying default)
src/probos/tools/protocol.py:80-91 ToolResult (frozen dataclass)
tests/fixtures/ad1343_seam_census.py:35-41 RECORDED (M2-09); :182-203 model_call_report and its print (M2-10)
tests/fixtures/ad1343_seam_registry.py:259-261 MODEL_CALLS_OUTSIDE_CREW comment (M2-11)
tests/test_ad1343_seam_registry.py:127-134 R4
tests/test_ad1343_stop_seam_inventory.py:110-123 stop-first; :244-276 9b, 9c
tests/test_ad1346_admission_service.py:23-32 module bullets (M1-11, M2-14); :80-84 allowlist (M1-12); :111-114 _FORBIDDEN_CALLS; :469-491 T13 (M1-13); :500-503 T14 docstring (M1-14); :536-542 T14 logging (M1-15); :562-571 T16 (M2-12); :602-608 importers (M2-13)
tests/test_ad1346_admission_ticket_issue.py:33-34 I11 bullet (M1-16); :116-164 fixtures (pattern for the new file); :580-596 I11 (M1-17)
tests/test_bf731_captain_llm_lane.py:63-68 `client._complete_inner = _probe`, LLMResponse(content="ok", model="m", tier="standard")
docs/development/architecture-baseline.yaml:581-585 OpenAICompatibleClient [lines, methods]; :871-875 ProbOSRuntime [lines, methods]; :994-998 ToolRegistry [methods]
scripts/check_architecture_principles.py:566-568 span > 500, methods > 15; :198-199 TASK_CREATE_CALLEES
scripts/gen_ad_ledger.py:126-132 status keywords; :139 the 120-character head window
PROGRESS.md:1 title; :3 M3d2's paragraph head. DECISIONS.md:1008 M3d2's heading; :1022 the heading after it (M4-02)
Python 3.12 asyncio-eventloop docs (fetched 2026-10-30): get_running_loop "Raise a RuntimeError if there is no running event loop."; call_soon_threadsafe "A thread-safe variant of call_soon(). When scheduling callbacks from another thread, this function must be used, since call_soon() is not thread-safe." and "Raises RuntimeError if called on a loop that's been closed. This can happen on a secondary thread when the main application is shutting down."
```

## Absence Verified (2026-10-30, run on `93af6ae4`, tree `21172897`)

```
CLAIM: no Python file names check_at, check_ticket, off_loop_checks or ticket_sinks (this contract introduces each)
RUN:   Grep "\bcheck_at\b|check_ticket|off_loop_checks|[^_a-z]_running_loop\(|ticket_sinks", glob *.py, the whole worktree
FOUND: src/probos/substrate/durable_events.py:239, :553 (that module's own _running_loop)
HOLDS: yes for the four names; the second _running_loop is private to another module, which this slice does not import

CLAIM: in src the classes declared with base BaseLLMClient or OpenAICompatibleClient are two, both on BaseLLMClient
RUN:   Grep "class \w+\((BaseLLMClient|OpenAICompatibleClient)" src/probos
FOUND: llm_client.py:265, :2684
HOLDS: yes for single-line class statements; SK8 checks every base by AST

CLAIM: in src, _complete_inner, _call_openai and _call_ollama_native are called only in llm_client.py, and nothing calls self.complete(
RUN:   Grep "self\.complete\(|\._complete_inner\(|_call_openai\(|_call_ollama_native\(" src/probos
FOUND: llm_client.py:1485, :2167, :2172, :2278 (def), :2446 (def)
HOLDS: yes

CLAIM: no test reads OpenAICompatibleClient.complete's source or pins its first statement
RUN:   Grep "getsource\([^)]*complete|OpenAICompatibleClient\.complete|is_critical = priority|vars\(client\)|client\._admission" tests, glob *.py
FOUND: test_ad1324_terminal_context.py:222 (wraps the method); test_ad636_llm_priority_scheduling.py:92 (its signature); test_ad742a_vision_fast_tier.py:127, :137 and test_bf686_breaker_log_attribution.py:245 (_complete_inner's source); test_ad934_deliberate.py:47 (a docstring)
HOLDS: yes: complete's signature and _complete_inner are unchanged

CLAIM: no test pins the tool sink's M3c comment line
RUN:   Grep "a stopped agent invokes nothing|the shadow decision beside the check|registry\.py" tests
FOUND: fixture rows naming the file (ad1343_seam_registry.py:24, :47, :93, :202); test_ad1343_stop_seam_inventory.py:119 (by AST); T16's file names; unrelated store and template registry lines
HOLDS: yes

CLAIM: llm_client.py's text does not contain "admission_service" (T16's named set stays)
RUN:   grep -c "admission_service" src/probos/cognitive/llm_client.py
FOUND: 0
HOLDS: yes, and the new text of M2-03 to M2-06 does not contain it

CLAIM: set_admission is defined once in src and called at two src sites
RUN:   Grep "\.set_admission\(|def set_admission", glob *.py
FOUND: crew_verifier.py:1249, tools/registry.py:143 (def), runtime.py:3425
HOLDS: yes

CLAIM: no test patches shadow_at in tools/registry.py or anything in llm_client.py's admission imports
RUN:   Grep "registry\.shadow_at|llm_client\.check_at|\"shadow_at\"\)|monkeypatch\.setattr\([^)]*shadow_at" tests
FOUND: test_ad1343_stop_seam_inventory.py:252; test_ad1346_admission_shadow_crew.py:116 (a crew module); test_ad1346_admission_ticket_issue.py:565
HOLDS: yes

CLAIM: the texts M2-10 and M2-11 change occur in src or tests only there
RUN:   Grep "gates them|never gated until|Report only \(never gated", glob *.{py,md}
FOUND: tests/fixtures/ad1343_seam_registry.py:259; tests/fixtures/ad1343_seam_census.py:203; prompts/ad-1343-batch-a-m0-seam-registry-n1-stop-retry.md:304, :511 (a record); unrelated lines in three tests and two docs
HOLDS: yes

CLAIM: the seam manifest names none of the touched symbols
RUN:   Grep "llm_client|check_and_invoke|tools/registry|OpenAICompatibleClient|admission" docs/development/seams (count)
FOUND: 0
HOLDS: yes

CLAIM: SEAM_MODEL_CALL is named outside the package nowhere in src
RUN:   grep -rn "SEAM_MODEL_CALL" src/probos --include=*.py
FOUND: admission/taxonomy.py:22, :23; admission/tickets.py:37, :60
HOLDS: yes (llm_client.py becomes its first importer outside the package)

CLAIM: pyproject.toml sets no line-length rule
RUN:   Grep "line-length|E501|select =|ignore =" pyproject.toml
FOUND: no matches
HOLDS: for pyproject.toml; other lint configuration files were not searched
```

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** no baseline row changes. M1's and M2's gates run it.
  - `AdmissionService` gains `check_ticket`, `_check_ticket` and `off_loop_checks`: 9 to 12 direct methods, and its span is 215 lines by `ast` against the trigger `span > 500` (the orchestrator's pre-build run, 2026-10-30; A1 changes no line count in the class).
  - `ToolRegistry`'s span does not change (M2-02 replaces two lines with two; 498 by `ast` before and after, the same run) and it gains no method (25).
  - `OpenAICompatibleClient` gains `set_admission` (44 to 45 methods, the same run); its row carries both triggers.
  - `ProbOSRuntime` gains no method (115, the same run).
  - No `create_task` and no `connect`; `call_soon_threadsafe` is not a tracked callee (`:198-199`).
- **`check_seam_contracts.py --check`:** unchanged; the manifest names none of the touched symbols (Absence).
- **`check_store_registry.py --check`:** unchanged; no store and no storage declaration.
- **Config:** no field.
- **T14:**
  - `service.py`'s allowlist gains `asyncio`;
  - `seam.py`'s is unchanged;
  - the logging rule admits `_check_ticket`;
  - `__all__` is unchanged.
- **T13, T16, I11:** updated (M1-13, M2-12, M2-13, M1-17). T15 sees no guard callee or agent-work call in the new code.
- **9a to 9c, `SHADOW_SITES`, G2:** unchanged; no `shadow_at` call changes.
- **Every sentence and test that quotes a set this slice changes:**
  - T13, T14, T16 and the service tests' module docstring (M1-11, M2-14);
  - I11 and its bullet (M1-16, M1-17);
  - `service.py`'s and `seam.py`'s module docstrings (M1-01, M1-09);
  - `close` and `failures` (M1-06, M1-08);
  - the census fixture's print and the registry fixture's comment (M2-10, M2-11).
  
  M3d2's carrier docstring, which names `AdmissionService.hold` the one call that sets the carrier and `TicketHold.end` the one that resets it, stays true: the sink check only reads the carrier. M3d2's dated `PROGRESS.md` and `DECISIONS.md` entries, which say that nothing checks a ticket yet, are records of their date and stay as written.
- **`gen_ad_ledger.py --check`:** passes after M4 regenerates both files (prediction).
- **Test collection:** `git diff --name-status --diff-filter=AD <slice base>..HEAD -- 'tests/test_*.py'` lists exactly one `A` file, `tests/test_ad1346_admission_ticket_sinks.py`.

## 13. Prior Art and Blind Spots

**Internal (adopted):**
- AD-1195's durable-events router (`substrate/durable_events.py:239-247`, `:553-557` on `93af6ae4`): on its loop in place, elsewhere `call_soon_threadsafe`, `RuntimeError` dropped. D128 copies the shape.
- `ToolRegistry.set_admission` (AD-1346 M3c) and `OpenAICompatibleClient.set_attachment_store` (AD-731): late binding for D127.
- `tests/test_bf731_captain_llm_lane.py:63-68`: the gateway with `_complete_inner` replaced (D131).
- M3d1's D99, D101 and D103 (D126 refines D103's "one statement"); M3d2's D120 setup (D132).
- `docs/architecture/architecture-review-2026-10-20.md` §3.3, as M3d1 cites it; not re-read in this session.

**External:**
- **Python 3.12 asyncio documentation** (quoted in §11). Adopted for D128.
- **Google ADK callbacks.** `before_model_callback` and `before_tool_callback` intercept at the model call and the tool call, the same two effect points ([adk-docs callbacks](https://raw.githubusercontent.com/google/adk-docs/refs/heads/main/docs/callbacks/index.md), [adk.dev guardrails](https://adk.dev/live/guardrails/)). A before-callback that returns a value replaces the call, which is an enforcement shape. Adopted: the two sinks as the interception points. Rejected for shadow; noted for M4.
- **Context loss across thread pools.** OpenTelemetry Python keeps trace context in `contextvars`, and a `ThreadPoolExecutor` worker starts without the submitter's context; third-party write-ups: [oneuptime](https://oneuptime.com/blog/post/2026-02-06-troubleshoot-threadpool-context-loss/view), [Arize Phoenix](https://phoenix.arize.com/docs/ax/concepts/otel-openinference/context-propagation). Absorbed as SK4's premise and register R31's evidence: the check reads the carrier in the caller's context and counts `ticket_missing` when a worker carries none. Rejected: wrapping executors to copy context (a change to `llm_decomposer.py`; explicit threading is M4).
- `docs/research/reference-projects.md`, judged on 2026-10-30:
  - Google ADK (2026-10-20, interval 180 days) was examined although not overdue. Row update for the caller: Last reviewed 2026-10-30, checked, "AD-1346 M3d3a (#1604) Prior Art, `prompts/ad-1346-m3d3a-ticket-sinks.md` (before-model and before-tool callbacks intercept at the two sinks; a before-callback's return replaces the call, an enforcement shape left to M4)".
  - Overdue and unrelated, considered and deferred: SWE-agent (2026-03-20), Cursor (2026-06-13), OpenCode (2026-05-08), MCP Apps (2026-04-08), AG-UI (never).

**Blind spots** (register items in brackets):
1. The gateway checks before the lane wait (up to 30 seconds); a stop during the wait is not seen by that call [R47].
2. Health probes and `check_connectivity` send requests without passing `complete`, and a vessel on the mock fallback records no `model_call` finding [R48].
3. A check made off the loop runs later on the loop, so a stop issued in between is seen [R49].
4. The tool sink resolves the principal twice: once in `shadow`'s `decide`, once in the check [R50].
5. A service built with no loop checks in place on any thread [R51].
6. Only the runtime's service is wired to the gateway; a projected correction runtime uses the ship's client and therefore the ship's service (by reading `crew_verifier.py:1249`, which hands the projected tool registry the ship's service).

## 14. Diff Reviewer: properties to verify

1. **Behaviour at either sink.**
   - `check_and_invoke` and `complete` return, raise and await what they did before, except where a `BaseException` that is not an `Exception` leaves the check (item 5) or where reading a request's `agent_id` raises an `Exception` other than `AttributeError`, which `complete` now does before the lane wait (D127). Both need an injected fault.
   - `check_at`, `check_ticket` and `_check_ticket` raise no `Exception`.
   - `shadow_at`'s line in `check_and_invoke` is byte-identical.
   - `ToolRegistry`'s line count does not change.
2. **Placement.**
   - At the tool sink, `check_at` is the statement directly after `shadow_at` and directly before `if stopped is not None:`.
   - At the gateway, it is the first statement after the docstring.
   - Neither is under a condition; neither is awaited.
3. **The carrier.**
   - `check_ticket` reads `CURRENT_TICKET` once, on the calling thread, before any hand-off.
   - Nothing in `src` sets or resets it but M3d2's two sites (I11).
4. **The thread rule.**
   - On the sink path the registry, the identity facade, `_off_loop` and `failures` are touched only in `_check_ticket`: `check_ticket` reads the carrier, `self._loop` and `_running_loop()` before it calls `_check_ticket` or hands it over. `shadow` and `hold` touch them too, on the thread that calls them, with no hand-off.
   - `_check_ticket` runs on the service's loop when the service has one.
   - The hand-off path writes no attribute of the service.
   - A hand-off that raises is passed over without a count.
5. **Fail-open.** `_check_ticket`'s `except Exception` counts in `failures` and logs through its own guard; a `BaseException` propagates.
6. **Wiring.**
   - The service gets `loop=asyncio.get_running_loop()` inside `start`.
   - The gateway gets `set_admission(self.admission_service)` only when it is an `OpenAICompatibleClient`, and None with the switch off.
   - `MockLLMClient` is untouched.
7. **Nothing persisted, nothing charged.** No `src` change adds a file, connection, event, trust, budget or stop write; `tickets.py` and `carrier.py` are untouched.
8. **Head text.** Each docstring and comment in `service.py`, `seam.py`, `llm_client.py`, `registry.py`, `runtime.py`, the fixtures and the new test file is true at its own milestone. No `src` comment outside the package contains `CURRENT_TICKET`, `TicketRegistry` or `WorkTicket` (I11, K15).
9. **Test file hygiene.**
   - The new file's text reads no environment variable, imports or calls no `subprocess` or `socket`, constructs `ProbOSRuntime` only in `_boot`, and puts every data directory under `tmp_path` (§15).
   - It starts worker threads and creates two event loops besides each test's own (its docstring says so).
   - These are properties of the file's text.

## 15. Acceptance criteria

- The updated files and the new file pass, and each §10 mutant is killed.
- `grep -nE "LOCALAPPDATA|AppData|environ|getenv|(import|from) (subprocess|socket)|(subprocess|socket)\.|create_subprocess|Popen" tests/test_ad1346_admission_ticket_sinks.py` finds nothing.
- `grep -n "data_dir=" tests/test_ad1346_admission_ticket_sinks.py` prints three lines, each containing `tmp_path /`: the identity registry fixture's, the stops fixture's and `_boot`'s.
- `grep -n "ProbOSRuntime(" tests/test_ad1346_admission_ticket_sinks.py` prints one line, in `_boot`.
- `grep -rn "check_at(" src/probos` prints three lines: the definition in `admission/seam.py`, and the calls in `tools/registry.py` and `cognitive/llm_client.py`.
- `grep -rn "CURRENT_TICKET" src/probos` prints lines of `src/probos/admission/carrier.py` and `src/probos/admission/service.py` only.
- `grep -rn "call_soon_threadsafe" src/probos/admission` prints lines of `src/probos/admission/service.py` only.
- `grep -rnE "TestTicket|allow_test_tickets" src/probos` prints lines of `src/probos/admission/tickets.py` only.
- The `--check` scripts of §12 pass. The broad gate's receipt is green. D132's figures are recorded.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Corrections to this contract

A1 (2026-10-30, after the orchestrator's pre-build run on `93af6ae4` and its dry application on `302e6bf9`, the M3d2 head after three review rounds) repairs:
- Defect 1: §10's Killed-by cells named cases (SK1 to SK10), and the census tool needs test functions. Each cell now names its case's function, and the list under the table says how to read its SK labels (A1-1a, A1-1b). The relaxed census had killed every row by the functions the cases name.
- Defect 2: predictions since measured. The collected count (A1-2a), `AdmissionService`'s span and the classes' method counts in §12 (A1-2b), and §17, which now lists only what is not yet confirmed (A1-2c).
- Defect 3: M3d2 took registers R44 and R45, so this contract's R44 to R49 are now R46 to R51 (A1-3a to A1-3k, A1-4a, A1-6b), and "Inherited and still open" gains R44 and R45 (A1-3k).
- Defect 4: the base statements now give M3d2's head `302e6bf9`, its tree and the build base (A1-4a to A1-4c), and §8 records M4-02's anchor on `302e6bf9` (A1-4d). The records of `93af6ae4` stay dated to it.
- Defect 5: §14 item 4 and D128 said the registry, the facade and the counts are touched only in the sink check, but `shadow` and `hold` touch them too. Both are now scoped to the sink path (A1-5a, A1-3d). §5's "every existing construction" now leaves out the runtime's (A1-5b). §12's quotation marks around M3d2's text are removed (A1-5c).
- Defect 6, the ruling (Architect, 2026-10-30): option G. The gateway passes `getattr(request, "agent_id", None)`, so an object with no `agent_id` raises, if at all, where the base raises. An `LLMRequest`'s value is unchanged. D127 and §14 item 1 state what remains: an `agent_id` whose read raises another `Exception` raises before the lane wait, and only an injected fault can cause that (A1-6a to A1-6e; SKX-13's Line in A1-1a). Before the build this costs text only; M3d2's analogue was recorded (its R44) because the repair came after its build.
- Defect 7, the sweep: D129's "every check is counted" (A1-7a); the module, `check_ticket`, `_check_ticket`, `off_loop_checks`, `failures` and seam docstrings, which counted a finding or a hand-off the code does not count (A1-7b to A1-7g); the new file's SK7 bullet, now scoped to `src` (A1-7h); the PROGRESS and DECISIONS D128 text (A1-7i, A1-7j); §12's list of T15's callees, given as the set (A1-7k); and §14 item 7, which the new test file's stop and file writes falsified (A1-7l).

Landing text changes in §7.1 (M1-01: A1-7b; M1-07: A1-7c to A1-7e; M1-08: A1-7f), §7.2 (M1-09: A1-7g), §7.6 (M2-05: A1-6c, A1's one executable change), §7.12.N (A1-6d, A1-7h) and §8 (M4-01: A1-7i; M4-02: A1-3f, A1-7j). No SEARCH text of §7 or §8, `def`, case count or mutation row number changes. SKX-13's Line follows M2-05, the class line counts in §12 are unchanged, and the slice still has 33 pairs. No decision or register row is added; D127 gains two sub-bullets.

A2 (2026-10-30, after cross-family review round 1 on the candidate `41324376`) repairs:
- F1: §5 said every construction other than the runtime's passes no `loop`, but the new file passes one at six places. The sentence, which A1-5b wrote, is deleted, and the list now names the tests that pass `loop` (A2-1).
- F2: §5 said each census consumer filters by callee, but two tests in `tests/test_ad1343_stop_seam_inventory.py` filter by keyword. The sentence now says how the consumers select rows, and why only SK7's filter selects a `check_at` row (A2-2).
- F3: the front matter called each SEARCH text's uniqueness a whole-line match, but M4-01's last SEARCH line is a prefix of its line. The parenthetical is deleted (A2-3).
- F4, the ruling (Architect, 2026-10-30): option S. SK2's name and its module bullet said it pins the forwarding of the presented id. A `check_at` that passed `presented_id=None` passed SK2, the new file, and the service and ticket-issue tests (the orchestrator's mutation run). SK2 now holds a ticket for one agent and presents another agent's id through `check_at`, which must count `ticket_principal_mismatch` (A2-4a). §10 gains SKX-17 for the forwarding line, killed by SK2's function (A2-4b, A2-4c). SK2's name and bullet are unchanged.
- The sweep: §5's call and read lists, which left out the new file's direct calls of `check_ticket` and `check_at` and SK1's read of `off_loop_checks` (A2-5); the SK1 bullet, whose "takes an event loop" SK1 does not exercise (A2-6a); the SK4 bullet, whose "counts nothing" covered `off_loop_checks`, which SK4 does not read for the closed loop's service (A2-6b); the `_runtime` helper's docstring, which named two attributes as all the run entry reads from a runtime, although the entry also reads others with `getattr` defaults (A2-6c); and §17, whose items 1 and 3 the build confirmed and which now lists A2's text (A2-7).

Landing text changes only in §7.12.N: A2-4a (SK2's body and docstring, A2's one executable change), A2-6a and A2-6b (the module docstring) and A2-6c (a helper's docstring). §7.1 to §7.11 and §8 are unchanged. No SEARCH text of §7 or §8, no `def`, the case count and no existing mutation row's number changes. The slice still has 33 pairs and 10 cases. §10 now has 17 rows. A2 changes no other test function's statements, so the campaign of record reruns the unmutated baseline, SKX-11 and SKX-17. No decision or register row is added; D137 and R52 stay free.

## 17. Claims not yet confirmed

1. `gen_ad_ledger.py --check` after M4's regeneration (§12).
2. The A2 text, which no gate has run: SK2's new assertions and SKX-17's kill (A2-4a to A2-4c). The rest of A2 is docstring and contract text and changes no statement.

The build (2026-10-30, M1 `eda4ac1b` to M4 `41324376`) confirmed what items 1 and 3 listed before A2. D132's figures were measured on the M1 stage ((c) 5.0 to 5.1 us median, (a) 9.0 to 9.2 us, as the orchestrator reported them). The A1 text was built, and the campaign of record killed 16 of 16 rows by their named functions.

The orchestrator's pre-build run (2026-10-30, scratch trees of `93af6ae4`) confirmed the rest of what this section listed before A1. It ran the focused gates of M1 (84 passed), M2 (222 passed) and M3 (32 passed; the new file collects 10), and SK1 to SK10 passed. That confirms the `_OfflineGateway` boot, no import cycle from `llm_client.py`, no `CURRENT_TICKET` in a worker's `asyncio.run`, the unclosed client and `issue_stop` with no event log. It also measured the spans in §12. The build's gates run each again on the build base.

## For the register (#1604)

- **Advanced by this slice:**
  - #1604 property 5, counted in memory (SK5, SK6);
  - property 1's sink census (SK7, SK8);
  - property 12 at the sinks (SK10);
  - property 6 at the sinks (SK3, SK10);
  - property 7's method (D132).
- **R30:** delivered by M3d3a except the persisted record, the report queries, the older-build check and the measurement with the recorder, which are now R46.
- **R31:** settled by D128.
- **R37, R38:** `ticket_missing` is counted by effect in the registry's tally; M3d3b persists it, and M3e decides on further issue points.
- **R39:** M3d3b persists the issue findings (R46).
- **R41:** unchanged; M3e.
- **R46 (M3d3b: the persisted sink record; binding direction, which its contract re-verifies and may refine; depends on M3d3a merged):**
  - **Findings table:** an additive table `ticket_findings (day, operation, code, work_kind, off_loop, findings)` keyed by the first five.
    - Per-day bound: 3 operations × 12 codes × 13 work kinds (the 12 of `WORK_KINDS` plus `""` for a finding with no entry) × 2 = 936 rows; over 35 days, 32,760, below `AGGREGATE_ROW_LIMIT` (100,000).
    - Pruned by day, as `shadow_parity` is.
    - Depth stays out of the key: with depth (×4), 35 days would hold 131,040 rows.
  - **Sample ring:** `ticket_samples`, the newest 5,000 findings whose code is neither `ticket_issued` nor `ticket_live`, as `TicketFinding.to_dict()` JSON with boot, hour, time and `off_loop`.
  - **Markers:** a separate `ticket_markers` table (offered, written, dropped, samples dropped, per boot and hour), for property 8. A new table rather than new columns: columns on `shadow_markers` would need `ALTER TABLE`, a migration.
  - **Writer:** the existing recorder, in the same flush transaction. Offered by `hold` (the issue finding) and `_check_ticket` (`check`'s return value).
  - **Reports:** report queries appended.
  - **Schema:** `SCHEMA_VERSION` stays 1.
  - **Executed older-build check:** before that build, open a file the M3d3b build wrote with the merged M3d3a build's `AdmissionShadowStore.start`, all `REPORT_QUERIES` and `prune`, run from a checkout of that commit (`git worktree add <dir> <commit>`, then `python -P` with `<dir>/src` first on `sys.path`). Record the results as M3c3's D83 did.
  - **Cost:** repeat D132 (a) to (d) with the recorder.
- **R47:** the gateway checks before the lane wait (up to 30 seconds); a Captain's stop during the wait is not seen by that call. M4 decides whether enforcement checks after the lane, nearer the request.
- **R48:** a vessel on the `MockLLMClient` fallback records no `model_call` finding, and health probes and `check_connectivity` send requests without passing `complete`. M3e classifies them in the system-principal census.
- **R49:** a check handed over from another thread runs later on the loop, so a stop issued in between is seen. Such checks, once the registry answers them, are counted in `off_loop_checks` (persisted with `off_loop` by M3d3b) so the M4 ruling can separate them. A hand-off to a closed loop is not counted.
- **R50:** the tool sink resolves the principal twice (the shadow decision and the check). M4 may share one resolution when it replaces the seams' statements.
- **R51:** a service built with no loop checks in place on any thread. In `src` only the runtime builds the service, and SK9 pins that it passes its loop.
- **Inherited and still open:** registers R10, R13 to R18, R19 to R23, R24 to R28, R32 to R34, R36, R39 to R45.
