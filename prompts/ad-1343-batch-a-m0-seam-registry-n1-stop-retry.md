# AD-1343 batch A: M0, the seam registry and its guard test; N1, a stopped crew session the Captain can retry

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Status:** build-ready contract, two slices of AD-1343 (#1595) in one batch. **Tier: HIGH** (governance control and a shared contract: the exception `CrewSessionFinalizer.resume` raises for a stop, and the type `SubtaskVerifier.converge_for_session` raises after an admitted correction). Confirmed, not lowered.
**Base:** `origin/main` `9388bfda79cd372a40a89c53caa5da21036ad6e6` (AD-1343 S1 merged, PR #1603).
**Dependencies:** none outside this contract. N1's registry rows (Section N1.6) edit files that M0 creates, so build M0 first.
**Numbering:** no new AD or BF. Current highest: AD-1346 (`scripts/ad_ceiling.py`: git log subjects and GitHub issue titles); BF-907 (orchestrator's brief, BF-908 reserved for C1).
**Milestones:** M0 (Sections M0.1 to M0.4, about 70 tool calls), then N1 (Sections N1.1 to N1.7, about 140 tool calls). Each has its own Builder run, consolidated focused check, Diff Reviewer pass (`gpt-6.1-sol`) and local commit; one broad gate and one PR for the batch.
**Estimated tests:** M0 adds 1 file (6 tests); N1 adds 1 file (3 tests, 4 collected), 2 tests to M0's file and 2 to `tests/test_ad1343_stop_crossing_resume.py`, and edits 3 S1 tests (none deleted).

---

## Problem

### M0: the census is a test, not a list

S1's inventory (`tests/test_ad1343_stop_seam_inventory.py`) pins the stop checks it knows (`_STOP_CHECK_SITES`, lines 48-64) and a few primitives (`.invoke(` on `*tool` receivers, `WorkItemAgenticExecutor(`, crew `.complete(`). It does not list each place agent work can start, and it does not scan for one: a new call such as `agent.check_own_render()` or `agent.handle_intent(...)` from a new module passes every S1 test. The Captain asked (comment 6282055471 on #1595; epic #1601 M0) for a living, machine-readable registry of every dispatch seam, each naming its guard, and a guard test that fails when a new seam appears or a listed seam loses its guard, found structurally. The S1 visitor and census (`_Visitor`, `_census`, lines 163-213) and the tables (lines 48-150) are reused, not copied.

### N1: a stopped crew session ends where the Captain cannot retry it

A3 made a stopped facilitator or producer read as one that is not live:

- facilitator, owner door: `crew_finalizer.py:2011-2015` (`active_stop` -> `raise ValueError("synthesis_producer_unavailable")`) and `:2036-2037` (`except AgentStopped` -> the same `ValueError`);
- producer, owner door: `crew_finalizer.py:1692-1693` (`except AgentStopped` -> `ValueError("child_producer_unavailable")`);
- the owner contains any `ValueError` as `blocked_needs_captain` / `recovery_integrity_conflict`, "no implicit retry" (`crew_orchestrator.py:1418-1425`);
- the authorizer `_authorize_blocked_retry` (`crew_session.py:5252-5315`) accepts only `crew_worker_unavailable`, `child_execution_interrupted` and `recovery_retry_exhausted`, so the Captain's retry gives `crew_session_retry_not_authorized` (`:5314-5315`).

Round 4's reviewer reproduced it through the real owner, finalizer and stores (N1, P2). D44 moved it to S2; the Captain's D3 then put S2 on #1601's work tickets, and D44 records that "where it is fixed meanwhile is for the Architect to decide after S1 merges". The Architect's decision (consult of 2026-10-20 05:07Z) is to fix it now.

---

## Solution

### M0

1. Lift S1's visitor, census and AST helpers, unchanged, into `tests/fixtures/ad1343_seam_census.py`; move S1's tables, unchanged apart from dropping the leading underscore, into `tests/fixtures/ad1343_seam_registry.py`, a data module that imports nothing. S1's inventory imports both under its old names, so its 19 test bodies stay byte-identical.
2. Add the structural scan. The agent-work entry primitives are CognitiveAgent's classified public coroutines (S1's `COGNITIVE_AGENT_COROUTINES`, all but `lifecycle`) plus its synchronous work starters (`SYNC_WORK_STARTERS`). A seam is a call to one of them **as an attribute on a receiver other than `self` or `super()`**; for the names other classes also use (`perceive`, `decide`, `act`, `report`, `consult`) the receiver must name an agent (`agent`, `*_agent`). A coroutine added to CognitiveAgent fails S1's `test_cognitive_agent_entry_points_are_classified` until it is classified, and is then scanned automatically.
3. Register every such call today (15 keys, Section M0.2) in `AGENT_WORK_CALLS`, each with its guard, and index the Captain's list of seams in `SEAM_INDEX`, each with its guard. The guard test checks each guard against the census: the stop check is still found, a same-function check still comes first, a named S1 exception is still in `S1_SCOPE`, and a module named as starting no work still starts none.
4. Model calls (`.complete(`) outside the crew modules: a **report**, never gated (`model_call_report()` and `python -m tests.fixtures.ad1343_seam_census`), classified structurally ("agent class X" when the enclosing class subclasses CognitiveAgent, else "outside an agent class") with a hand override table, `MODEL_CALLS_OUTSIDE_CREW`, empty today. #1601 M3's coverage guard owns gating them.

### N1

1. At the **stop** sites of the owner door only, raise `CrewRecoveryTransientError` (`crew_session.py:423`) with the codes `synthesis_producer_stopped` and `child_producer_stopped`. A facilitator or producer that is **not live** keeps its `ValueError`.
2. The owner's recovery loop already retries a transient error with backoff (`crew_orchestrator.py:1154-1163`, `_checkpoint_transient_failure` `:1328-1391`). If the order is lifted in time the session continues by itself; otherwise it ends `recovery_retry_exhausted` (`:1344-1350`), which `_authorize_blocked_retry` already accepts for a `verifying` session whose phase is in `_VERIFYING_RECOVERY_PHASES` (`crew_session.py:5292-5311`; `children_verified` and `verifying_children` are in it, `:172-179`).
3. F-177: a correction admitted just before the order (its permit kept) is told apart by a new `AgentStopped` subclass, `CorrectionAdmittedNotExecuted`, raised by the verifier; the owner door keeps `ValueError` for it, so that session stays blocked and is not retryable (a retry would replay the permit as `correction_execution_defect`).
4. `S1_SCOPE["refuses"]` and `LIFT_NOTE` (both served to the Captain) say what is now true.

No persisted schema, EventType, route, config field or UI change. The two codes are new values of the existing free-text `last_error_code` (`_RECOVERY_ERROR_RE`, `crew_session.py:169`), written only while the loop backs off and overwritten on exhaustion.

---

## Settled premises (the orchestrator's open questions)

**P1. The first-run door has no recovery loop, and production never reaches it.** `CrewSessionFinalizer.finalize` reaches `_finalize_claimed` (the first-run door, `crew_finalizer.py:2617`, with `_fail(blocked=True)` at `:2737-2744` and `:2909-2916`) only when the session has no recovery record (`:1118-1125` hands any session with one to `resume`). Its only caller is `CrewOrchestrator.run_crew_task` (`crew_orchestrator.py:3578`), whose only caller is `_run_owned_parent` when `self._crew_session_service is None` (`:641-646`); with a service, `_run_owned_parent` runs the recovery loop (`:647`), and `_run_recovery_attempt` establishes a recovery record before it calls the finalizer (`:788-789`). Production refuses to build the orchestrator without a session service (`startup/finalize.py:2150-2174`, `crew_session_service` is mandatory; pinned by `test_enabled_startup_missing_mandatory_dependency_fails_before_admission`, `tests/test_ad1127_crew_session_lifecycle_recovery.py:3285`). **Decision:** the first-run door is unchanged and out of scope; N1 pins the reachability premise structurally (Section N1.6, `FIRST_RUN_DOOR`). Its S1 tests (`tests/test_ad1343_stop_crossing_finalizer.py`, X7 to X9, all through `finalize` with no recovery record) keep passing unchanged.

**P2. "Nothing is replayed on a lift" stays true for refused work.** What retries is the crew session's **own durable step** (its blocked synthesis, or the correction of its refuted child), by the session's existing owner, on the recovery schedule it already uses for transient faults. A stop pauses that step; it does not refuse a message to the agent. Nothing refused during the stop is queued or replayed: DMs, Ward Room notices, intents, proactive cycles, delegations, browser actions and tool calls refused while stopped are gone, as S1 says. `AgentStopService` itself still replays nothing (`agent_stop.py:437` stays true). `LIFT_NOTE` and `S1_SCOPE["refuses"]` now name the crew-session continuation explicitly (Section N1.3), so the Captain is told before the lift what will continue.

**P3. The producer's correction path and the orphan permit (F-177).** A stop found **before** admission (`crew_verifier.py:2019-2023`) admits nothing, so a retry after the lift runs the correction normally: transient. A stop that lands **after** admission and is refused at the run entry (`crew_verifier.py:2164-2174`) keeps the permit (D34); a retry would re-admit with the same deterministic `review_attempt_id` (`:2072-2083`), read no stored correction (`:2107-2131`) and fail closed as `correction_execution_defect`. N1 tells the two apart with `CorrectionAdmittedNotExecuted` (an `AgentStopped`, so every S1 mapping is kept; the first-run door's `except AgentStopped` at `:2737` still catches it); the owner door maps it to `ValueError("child_producer_unavailable")`, so the session is contained as `recovery_integrity_conflict` in that same attempt and is not retryable (X14). That residual is the honest state of a narrow race (a stop issued during the admission transaction); it stays recorded on #1523 with D34.

**P4. Tests and wording that pin the current mapping.**

| Pin | Where | Change |
|---|---|---|
| X10 asserts `ValueError("synthesis_producer_unavailable")` from the owner door | `tests/test_ad1343_stop_crossing_resume.py:113-116` | expects `CrewRecoveryTransientError("synthesis_producer_stopped")` |
| X11 asserts `ValueError` and `stopped == not_live` | same file, `:199-206`, `:244`, `:248-249` | the stopped case is transient (`child_producer_stopped`); every other field still equals the not-live case |
| X10b (claimed synthesis runs), the two goldens, I18 | same file `:153-191`, `:137-149`, `:254-271`; inventory `test_only_the_owned_resume_passes_admitted_synthesis` | unchanged |
| T35 (`admitted but not executed`) | `tests/test_ad1343_agent_stop_verify.py:518-522` | gains one assertion on the raised type |
| first-run crossings X7 to X9 | `tests/test_ad1343_stop_crossing_finalizer.py` | unchanged (P1) |
| T33 session and race variants | `tests/test_ad1343_agent_stop_crew.py:391-413`, `:444-466` | unchanged; `:461` (`raised.value is entry.raised`) already proves a run-entry refusal with no permit is re-raised unchanged |
| `S1_SCOPE["refuses"]` "cannot yet be retried after the lift (AD-1343 S2)" | `src/probos/agent_stop.py:81-85` | reworded (N1.3); the only occurrence outside `prompts/` (Absence A3) |
| DECISIONS D44, residual (6), behaviour change (6); PROGRESS AD-1343 S1 line ("a retry after the lift is S2", twice) | `DECISIONS.md:324`, `:327`, `:328`; `PROGRESS.md:3` | **not rewritten**: they record S1 as merged. The new DECISIONS section and PROGRESS entry state that N1 supersedes them (D15) |

---

## M0 implementation

### Section M0.1: new file `tests/fixtures/ad1343_seam_registry.py`

Data only. It imports nothing (R5 checks). Every S1 table is copied verbatim from `tests/test_ad1343_stop_seam_inventory.py` lines 47-150 with the leading underscore dropped; do not reformat or reorder their rows.

```python
"""AD-1343 M0 (#1595): the registry of every place agent work can start, each with the guard that refuses a stopped agent.

Data only, and it imports nothing (``tests/test_ad1343_seam_registry.py`` checks), so a later column cannot create an
import cycle: #1601 M3 adds the shadow ``decide()`` each seam calls by widening the guard tuples of ``AGENT_WORK_CALLS``
and ``SEAM_INDEX``. The census these rows are checked against is ``tests/fixtures/ad1343_seam_census.py``.

Keys never carry a line number: (repo-relative file, enclosing qualified name, callee), as in the S1 census.

Guard kinds:
- ``("sink", site)``: the callee is a sink that refuses a stopped agent itself; ``site`` is its stop check.
- ``("check", site)``: a stop check in the same function, before the call.
- ``("upstream", site, ...)``: reached only after the stop check at each ``site``.
- ``("exception", (scope_key, phrase))``: a named S1 exception; ``phrase`` must stay in ``agent_stop.S1_SCOPE[scope_key]``.
- ``("at", site)``: the stop check of an indexed seam (``SEAM_INDEX``).
- ``("none", file)``: the module starts no agent work; the census must find none there.
"""

# ---- S1's inventory (tests/test_ad1343_stop_seam_inventory.py), moved here unchanged ----

# (file, enclosing function, callee) -> the seam constant it names.
STOP_CHECK_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", "refusal"): "SEAM_INTENT",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", "refusal"): "SEAM_CONSULTATION",
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool_refusal"): "SEAM_TOOL",
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", "active_stop"): "SEAM_PROACTIVE",
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", "active_stop"): "SEAM_WARD_ROOM",
    ("src/probos/routers/agents.py", "_agent_chat_impl", "active_stop"): "SEAM_DM_ROUTE",
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", "active_stop"): "SEAM_GROUP_FANOUT",
    ("src/probos/routers/agent_actions.py", "ack_action", "active_stop"): "SEAM_BROWSER_ACTION",
    ("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run", "refuse_new_run"): "SEAM_AGENTIC_RUN",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", "active_stop"): "SEAM_DELEGATION",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop"): "SEAM_TOOL",
}

# Every public coroutine on CognitiveAgent. sink: consults the stop itself; within_turn: runs
# only inside a turn a sink admitted; dm_route: reached only after the DM route's check;
# captain_persona / s2_in_flight / lifecycle: named S1 exceptions, reported in S1_SCOPE.
COGNITIVE_AGENT_COROUTINES: dict[str, str] = {
    "handle_intent": "sink",
    "handle_consultation_request": "sink",
    "perceive": "within_turn",
    "decide": "within_turn",
    "act": "within_turn",
    "report": "within_turn",
    "consult": "within_turn",
    "interpret_recall": "within_turn",
    "interpret_own_dream": "within_turn",
    "observe_self_avatar": "dm_route",
    "check_own_render": "dm_route",
    "propose_appearance": "captain_persona",
    "propose_voice_profile": "captain_persona",
    "recover_promoted_turn": "s2_in_flight",
    "stop": "lifecycle",
}
SYNC_WORK_STARTERS: dict[str, str] = {
    "resume_promoted_turn": "s2_in_flight: AD-855 resume of a turn begun before the stop; tool calls refused",
}

# Direct tool invocations: each skips ToolRegistry.check_and_invoke unless it is that method.
DIRECT_TOOL_INVOKES: dict[tuple[str, str, str], str] = {
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool"): "the tool sink, after its check",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "browser_tool"):
        "after its own stop check at SEAM_TOOL (A2, F2): a turn admitted before the order proposes and runs no action",
    ("src/probos/routers/agent_actions.py", "ack_action", "browser_tool"): "after SEAM_BROWSER_ACTION",
}

SOURCE_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", ("_check_unread_dms", "_think_for_agent")),
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", ("count_posts_by_author", "dispatch_async")),
    ("src/probos/routers/agents.py", "_agent_chat_impl", ("get_or_create_default_for_agent", "send")),
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", ("_capture_owned_steps_turn",)),
    ("src/probos/routers/agent_actions.py", "ack_action", ("invoke", "mark_executed", "mark_failed")),
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", ("admit", "bind_delegated_run", "WorkItemAgenticExecutor")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", ("complete",)),
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", ("_claim_owned_synthesis", "synthesize_for_session")),
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", ("register", "invoke")),
)

# A2: every place a WorkItemAgenticExecutor is built, and how a stopped agent is refused there.
AGENTIC_RUN_OWNERS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch"): "admitted turn (handle_intent)",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic"): "admitted turn",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn"): "S2 promoted resume",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke"): "SEAM_DELEGATION, then the run entry",
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
}
ADMITTED_TURN_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic._run_pass", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
# A4 (F1): the one place a synthesis is admitted past the facilitator's stop: the owned resume, from its own claim.
ADMITTED_SYNTHESIS_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "admitted_synthesis=admission is not None"),
})

# A3 (R1): every model call in the crew modules, by enclosing function, and whose name it runs under.
CREW_MODEL_CALLS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session"):
        "facilitator: SEAM_AGENTIC_RUN at the entry, unless the owned resume claimed it after its own check (I18)",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer._synthesize_output"): "ship: the generic _SYSTEM_PROMPT, no crew identity or instructions",
}
# A3 (R1): the verifier's stop question, and every place that asks it.
VERIFIER_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_independent_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_department_peer"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_authority_chief"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_live_session_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"),
})
STANDING_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._stopped"),
})

# ---- M0: every call that starts another agent's work, and its guard ----

_INTENT_SINK = ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", "refusal")
_DM_ROUTE_CHECK = ("src/probos/routers/agents.py", "_agent_chat_impl", "active_stop")
_CAPTAIN_PERSONA = ("not_covered", "Voice and appearance proposals the Captain requests, directly or through the Counselor")
_PROMOTED_RESUME = ("does_not_end", "a promoted turn the Captain approves while the agent is stopped resumes")

# (file, enclosing function, callee) -> guard. Found by ``ad1343_seam_census.agent_work_calls()``.
AGENT_WORK_CALLS: dict[tuple[str, str, str], tuple[object, ...]] = {
    # Through the intent sink, which refuses a stopped crew agent itself (a designed agent in the sandbox is not crew, D9).
    ("src/probos/activation/dispatcher.py", "Dispatcher.dispatch", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/agents/system_qa.py", "SystemQAAgent.run_smoke_tests", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/cognitive/communication_benchmarks.py", "_send_chain_probe", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/cognitive/qualification_tests.py", "_send_probe", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/cognitive/sandbox.py", "SandboxRunner.test_agent", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/experience/commands/commands_diagnostic.py", "cmd_diagnostic", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/experience/commands/commands_knowledge.py", "cmd_scout", "handle_intent"): ("sink", _INTENT_SINK),
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._think_for_agent", "handle_intent"): ("sink", _INTENT_SINK),
    # Inside the Captain's DM route, after its stop check (the full reply chain runs only there).
    ("src/probos/routers/agents.py", "_agent_chat_impl", "observe_self_avatar"): ("check", _DM_ROUTE_CHECK),
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4_self_check_parse", "check_own_render"):
        ("upstream", _DM_ROUTE_CHECK),
    # Named S1 exceptions, reported in S1_SCOPE.
    ("src/probos/cognitive/counselor.py", "CounselorAgent._mediate_appearance_revision", "propose_appearance"):
        ("exception", _CAPTAIN_PERSONA),
    ("src/probos/routers/agents.py", "propose_agent_appearance", "propose_appearance"): ("exception", _CAPTAIN_PERSONA),
    ("src/probos/routers/agents.py", "propose_agent_voice_profile", "propose_voice_profile"): ("exception", _CAPTAIN_PERSONA),
    ("src/probos/cognitive/turn_promotion.py", "resume_promoted_turn", "recover_promoted_turn"): ("exception", _PROMOTED_RESUME),
    ("src/probos/cognitive/turn_promotion.py", "resume_promoted_turn", "resume_promoted_turn"): ("exception", _PROMOTED_RESUME),
}

# The Captain's list of seams (comment 6282055471 on #1595), each with its guard. Every ``agent_stop.SEAM_*`` value is a key.
SEAM_INDEX: dict[str, tuple[str, tuple[object, ...]]] = {
    "intent": (
        "every intent to a crew agent: DMs through the mesh, Ward Room notices, proactive and duty cycles, the mesh",
        ("at", _INTENT_SINK),
    ),
    "work_items": ("work items dispatched to an agent as intents", ("at", _INTENT_SINK)),
    "sandbox": ("the self-mod sandbox's test of a designed agent, through the intent sink", ("at", _INTENT_SINK)),
    "consultation": (
        "a consultation request to an agent",
        ("at", ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", "refusal")),
    ),
    "tool": (
        "every tool call through the registry, protected effects included",
        ("at", ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool_refusal")),
    ),
    "proactive": (
        "the proactive cycle: duties and the DM sweep",
        ("at", ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", "active_stop")),
    ),
    "ward_room": (
        "Ward Room routing to an agent",
        ("at", ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", "active_stop")),
    ),
    "dm_route": ("the Captain's DM route", ("at", _DM_ROUTE_CHECK)),
    "group_fanout": (
        "a group chat turn",
        ("at", ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", "active_stop")),
    ),
    "browser_action_ack": (
        "the Captain's ACK of a proposed browser action",
        ("at", ("src/probos/routers/agent_actions.py", "ack_action", "active_stop")),
    ),
    "inline_browser_action": (
        "a browser action proposed inside a DM reply",
        ("at", ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop")),
    ),
    "agentic_run": (
        "every new agentic run (the agentic loop), whoever builds it",
        ("at", ("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run", "refuse_new_run")),
    ),
    "delegation": (
        "a task delegated to an agent",
        ("at", ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", "active_stop")),
    ),
    "crew_executor": (
        "a crew subtask: a stopped agent is not eligible",
        ("at", ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility", "standing_stop")),
    ),
    "crew_verifier": (
        "verifying a colleague's crew work, at each pick and judgment",
        ("at", ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session", "_stopped")),
    ),
    "crew_correction": (
        "a correction re-run of a refuted crew subtask",
        ("at", ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop")),
    ),
    "crew_synthesis": (
        "the facilitator's synthesis of a crew session",
        ("at", ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop")),
    ),
    "captain_persona": ("voice and appearance proposals the Captain requests", ("exception", _CAPTAIN_PERSONA)),
    "promoted_turn_resume": ("the resume of a promoted turn the Captain approved", ("exception", _PROMOTED_RESUME)),
    "long_runs": ("LongRunService records runs and starts no agent work", ("none", "src/probos/execution/long_runs.py")),
}

# Report only (never gated until #1601 M3): a hand classification of a model call outside the crew modules, keyed by
# (file, enclosing function). Empty today; ``model_call_report()`` classifies the rest structurally.
MODEL_CALLS_OUTSIDE_CREW: dict[tuple[str, str], str] = {}
```

### Section M0.2: new file `tests/fixtures/ad1343_seam_census.py`

`Visitor`, `census`, `function`, `calls` and `first_line` are S1's `_Visitor`, `_census`, `_function`, `_calls` and `_first_line` (inventory lines 153-249) with the leading underscore dropped; `census` delegates per file to `scan`. Keep every other line of their bodies as S1 wrote it.

```python
"""AD-1343 M0 (#1595): the AST census of ``src/probos`` that the stop's seam registry is checked against.

Lifted from ``tests/test_ad1343_stop_seam_inventory.py`` (S1) so the S1 inventory and the registry guard
(``tests/test_ad1343_seam_registry.py``) read one census; the data is ``tests/fixtures/ad1343_seam_registry.py``.

Report (never gated): ``python -m tests.fixtures.ad1343_seam_census`` prints every model call (``.complete(``) outside
the crew modules, by file, enclosing function and receiver, classified by ``MODEL_CALLS_OUTSIDE_CREW`` or structurally:
``agent class X`` when the enclosing class subclasses CognitiveAgent (by simple base name), else ``outside an agent class``.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import probos
from tests.fixtures import ad1343_seam_registry as registry

PACKAGE = Path(probos.__file__).resolve().parent
ROOT = PACKAGE.parents[1]
IMPLEMENTATION = "src/probos/agent_stop.py"
STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal", "refuse_new_run"})
# M0: the calls a guard can be: the S1 stop questions, crew eligibility's and the verifier's.
GUARD_CALLEES = STOP_CALLEES | {"standing_stop", "_stopped"}
# M0: the agent-work entry primitives: CognitiveAgent's classified public coroutines (all but its lifecycle) and its
# synchronous work starters, so a coroutine added there is scanned as soon as S1's census classifies it.
AGENT_WORK_METHODS = frozenset(
    name for name, kind in registry.COGNITIVE_AGENT_COROUTINES.items() if kind != "lifecycle"
) | frozenset(registry.SYNC_WORK_STARTERS)
# Names other classes also use (a store's decide, an organ's act): such a call counts only when its receiver names an agent.
GENERIC_AGENT_METHODS = frozenset({"perceive", "decide", "act", "report", "consult"})
RECORDED = STOP_CALLEES | AGENT_WORK_METHODS | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
}
PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops", "admitted_synthesis"})  # recorded as "name=value" on any call passing one
CREW_PREFIX = "src/probos/cognitive/crew_"


@dataclass(frozen=True)
class Call:
    file: str
    function: str
    callee: str
    receiver: str
    seam: str
    keywords: tuple[str, ...] = ()


class Visitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self._rel = rel
        self._scope: list[str] = []
        self.calls: list[Call] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            callee, receiver = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            callee, receiver = func.id, ""
        else:
            callee, receiver = "", ""
        keywords = tuple(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg in PINNED_KEYWORDS)
        if callee in RECORDED or keywords:
            seam = ""
            if callee == "refusal" and len(node.args) >= 2:
                seam = ast.unparse(node.args[1])
            elif callee == "active_stop" and len(node.args) >= 3:
                seam = ast.unparse(node.args[2])
            elif callee == "tool_refusal":
                seam = "SEAM_TOOL"
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
            self.calls.append(Call(self._rel, ".".join(self._scope) or "<module>", callee, receiver, seam, keywords))
        self.generic_visit(node)


def scan(source: bytes | str, rel: str) -> tuple[Call, ...]:
    """The census of one module's source, read as the repo-relative path ``rel``."""
    visitor = Visitor(rel)
    visitor.visit(ast.parse(source, filename=rel))
    return tuple(visitor.calls)


@functools.lru_cache(maxsize=1)
def census() -> tuple[Call, ...]:
    found: list[Call] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        found += scan(path.read_bytes(), path.relative_to(ROOT).as_posix())
    return tuple(found)


def function(rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse((ROOT / rel).read_bytes(), filename=rel)

    def walk(body: list[ast.stmt], prefix: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                if name == qualname and not isinstance(node, ast.ClassDef):
                    return node
                hit = walk(node.body, name)
                if hit is not None:
                    return hit
        return None

    found = walk(tree.body, "")
    assert found is not None, (rel, qualname)
    return found


def calls(name: str) -> Callable[[ast.AST], bool]:
    def match(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        )
    return match


def first_line(node: ast.AST, predicate: Callable[[ast.AST], bool]) -> int:
    lines = [n.lineno for n in ast.walk(node) if predicate(n)]
    assert lines, f"nothing matched in {getattr(node, 'name', node)}"
    return min(lines)


def is_agent_work_call(call: Call) -> bool:
    """M0: a call that starts another agent's work: a primitive called as an attribute on a receiver other than the caller."""
    if call.callee not in AGENT_WORK_METHODS or call.receiver in ("", "self") or call.receiver.startswith("super("):
        return False
    if call.callee in GENERIC_AGENT_METHODS:
        last = call.receiver.split(".")[-1]
        return last == "agent" or last.endswith("_agent")
    return True


def agent_work_calls() -> frozenset[tuple[str, str, str]]:
    """Every (file, enclosing function, callee) in ``src/probos`` that starts another agent's work."""
    return frozenset((c.file, c.function, c.callee) for c in census() if is_agent_work_call(c))


@functools.lru_cache(maxsize=1)
def agent_classes() -> frozenset[str]:
    """Class names in ``src/probos`` that subclass ``CognitiveAgent``, resolved by simple base name (report only)."""
    bases: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, set()).update(ast.unparse(base).split(".")[-1] for base in node.bases)
    found = {"CognitiveAgent"}
    while True:
        more = {name for name, parents in bases.items() if parents & found} - found
        if not more:
            return frozenset(found)
        found |= more


def model_call_report() -> tuple[tuple[str, str, str, str], ...]:
    """Report only: (file, function, receiver, classification) for each model call outside the crew modules."""
    rows = {
        (c.file, c.function, c.receiver)
        for c in census()
        if c.callee == "complete" and c.receiver and not c.file.startswith(CREW_PREFIX)
    }
    report = []
    for file, function_name, receiver in sorted(rows):
        how = registry.MODEL_CALLS_OUTSIDE_CREW.get((file, function_name))
        if how is None:
            owner = function_name.split(".")[0]
            how = f"agent class {owner}" if owner in agent_classes() else "outside an agent class"
        report.append((file, function_name, receiver, how))
    return tuple(report)


if __name__ == "__main__":
    rows = model_call_report()
    for file, function_name, receiver, how in rows:
        print(f"{file}::{function_name}  {receiver}.complete(...)  {how}")
    print(f"{len(rows)} model call sites outside the crew modules (report only; #1601 M3 gates them)")
```

### Section M0.3: edit `tests/test_ad1343_stop_seam_inventory.py` (header only)

Replace **lines 25-250** (sentinels: line 25 is `from __future__ import annotations`; line 249 is `    return min(lines)`; line 252 is `def test_census_premise_reads_this_checkout() -> None:`) with the block below, keeping one blank line pair before line 252. Lines 1-24 (the docstring) and everything from `def test_census_premise_reads_this_checkout` to the end of the file stay byte-identical: `git diff -U0 -- tests/test_ad1343_stop_seam_inventory.py` must show one hunk, ending before that `def`.

```python
from __future__ import annotations

import ast
from pathlib import Path

from probos import agent_stop
from probos.security.url_guard import validate_public_url
# AD-1343 M0: the census and its tables are shared with the seam registry guard (tests/test_ad1343_seam_registry.py);
# imported under their S1 names so the tests below are unchanged.
from tests.fixtures.ad1343_seam_census import (
    IMPLEMENTATION as _IMPLEMENTATION,
    ROOT as _ROOT,
    STOP_CALLEES as _STOP_CALLEES,
    calls as _calls,
    census as _census,
    first_line as _first_line,
    function as _function,
)
from tests.fixtures.ad1343_seam_registry import (
    ADMITTED_SYNTHESIS_SITES as _ADMITTED_SYNTHESIS_SITES,
    ADMITTED_TURN_SITES as _ADMITTED_TURN_SITES,
    AGENTIC_RUN_OWNERS as _AGENTIC_RUN_OWNERS,
    COGNITIVE_AGENT_COROUTINES as _COGNITIVE_AGENT_COROUTINES,
    CREW_MODEL_CALLS as _CREW_MODEL_CALLS,
    DIRECT_TOOL_INVOKES as _DIRECT_TOOL_INVOKES,
    SOURCE_ORDER as _SOURCE_ORDER,
    STANDING_STOP_SITES as _STANDING_STOP_SITES,
    STOP_CHECK_SITES as _STOP_CHECK_SITES,
    SYNC_WORK_STARTERS as _SYNC_WORK_STARTERS,
    VERIFIER_STOP_SITES as _VERIFIER_STOP_SITES,
)
```

Check before committing: `grep -n "_PACKAGE\|_RECORDED\|_PINNED_KEYWORDS\|_Call\b\|_Visitor\|functools\|Callable\|dataclass" tests/test_ad1343_stop_seam_inventory.py` finds nothing (none of them is used below line 252).

### Section M0.4: new file `tests/test_ad1343_seam_registry.py`

```python
"""AD-1343 M0 (#1595): the seam registry is the living list of every place agent work can start, each with its guard.

Each test reads the AST census of ``src/probos`` (``tests/fixtures/ad1343_seam_census.py``) against the registry
(``tests/fixtures/ad1343_seam_registry.py``):

- R1  every call that starts another agent's work is registered, and every registered call still exists;
- R2  every registered call and every indexed seam names a guard that still holds: its stop check is still found where
      the registry says, a same-function check still comes first, a named S1 exception is still in ``S1_SCOPE``, and a
      module named as starting no work still starts none; every ``agent_stop.SEAM_*`` value is indexed;
- R3  the scanner's rule on a fixed source: the caller's own calls, ``super()`` calls, bare calls and non-agent
      receivers of the generic names are not seams;
- R4  the model-call report covers the model calls outside the crew modules and gates none of them;
- R5  the registry imports nothing, so #1601 M3 can add a column without a cycle.

Not seen (stated bounds, as in S1): a call through an alias, ``getattr`` or a stored reference
(``handler=agent.handle_intent``; the sink still refuses it), and a model call outside the crew modules (reported, not
gated, until #1601 M3).
"""

from __future__ import annotations

import ast
from pathlib import Path

from probos import agent_stop
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures import ad1343_seam_registry as seam_registry
from tests.fixtures.ad1343_seam_census import (
    GUARD_CALLEES,
    ROOT,
    agent_work_calls,
    calls,
    census,
    first_line,
    function,
    model_call_report,
    scan,
)
from tests.fixtures.ad1343_seam_registry import AGENT_WORK_CALLS, MODEL_CALLS_OUTSIDE_CREW, SEAM_INDEX

_WORK_STARTERS = seam_census.AGENT_WORK_METHODS | {"WorkItemAgenticExecutor", "invoke", "complete"}


def _guard_sites() -> frozenset[tuple[str, str, str]]:
    return frozenset((c.file, c.function, c.callee) for c in census() if c.callee in GUARD_CALLEES)


def _assert_guard(where: object, guard: tuple[object, ...], primitive: tuple[str, str, str] | None) -> None:
    kind, *refs = guard
    assert refs, (where, guard)
    if kind in {"sink", "check", "upstream", "at"}:
        found = _guard_sites()
        for ref in refs:
            assert ref in found, (where, "the guard is no longer found", ref)
        if kind == "check":
            assert primitive is not None and len(refs) == 1, (where, guard)
            rel, qualname, callee = refs[0]
            assert (rel, qualname) == primitive[:2], (where, "a check guards only calls in its own function")
            fn = function(rel, qualname)
            assert first_line(fn, calls(callee)) < first_line(fn, calls(primitive[2])), (where, "the check is no longer first")
    elif kind == "exception":
        scope_key, phrase = refs[0]
        assert phrase in agent_stop.S1_SCOPE[scope_key], (where, scope_key, phrase)
    elif kind == "none":
        rel = refs[0]
        assert (ROOT / rel).is_file(), (where, rel)
        starters = {(c.function, c.callee) for c in census() if c.file == rel and c.callee in _WORK_STARTERS}
        assert starters == set(), (where, sorted(starters))
    else:
        raise AssertionError((where, "unknown guard kind", kind))


# R1
def test_every_agent_work_call_is_registered() -> None:
    found = agent_work_calls()
    assert ("src/probos/activation/dispatcher.py", "Dispatcher.dispatch", "handle_intent") in found  # premise: the scan sees a sink caller
    assert found == set(AGENT_WORK_CALLS), sorted(found ^ set(AGENT_WORK_CALLS))


# R2
def test_every_registered_call_names_a_guard_that_still_holds() -> None:
    for key, guard in AGENT_WORK_CALLS.items():
        assert guard[0] in {"sink", "check", "upstream", "exception"}, (key, guard)
        _assert_guard(key, guard, key)


# R2
def test_every_indexed_seam_names_a_guard_that_still_holds() -> None:
    seams = {
        getattr(agent_stop, name) for name in dir(agent_stop)
        if name.startswith("SEAM_") and isinstance(getattr(agent_stop, name), str)
    }
    assert seams <= set(SEAM_INDEX), sorted(seams - set(SEAM_INDEX))
    for name, (what, guard) in SEAM_INDEX.items():
        assert what, name
        assert guard[0] in {"at", "exception", "none"}, (name, guard)
        _assert_guard(name, guard, None)


# R3
def test_the_scan_counts_only_calls_that_start_another_agents_work() -> None:
    source = (
        "class Loop:\n"
        "    async def run(self, agent, store, organ, bus):\n"
        "        await self.decide(1)\n"
        "        await super().handle_intent(2)\n"
        "        await resume_promoted_turn(3)\n"
        "        await store.decide(4)\n"
        "        organ.act(5)\n"
        "        await agent.decide(6)\n"
        "        await self.ctx.agent.check_own_render()\n"
        "        await bus.handle_intent(7)\n"
    )
    found = {
        (c.function, c.callee, c.receiver)
        for c in scan(source, "src/probos/example.py")
        if seam_census.is_agent_work_call(c)
    }
    assert found == {
        ("Loop.run", "decide", "agent"),
        ("Loop.run", "check_own_render", "self.ctx.agent"),
        ("Loop.run", "handle_intent", "bus"),
    }, sorted(found)


# R4
def test_the_model_call_report_covers_the_sites_outside_the_crew_modules_and_gates_nothing() -> None:
    report = model_call_report()
    rows = {(file, fn) for file, fn, _receiver, _how in report}
    assert rows  # premise: there are model calls outside the crew modules
    assert not any(file.startswith(seam_census.CREW_PREFIX) for file, _fn in rows)
    assert all(how for *_rest, how in report)
    assert any(how == "agent class CognitiveAgent" for *_rest, how in report)  # premise: CognitiveAgent's own calls are recognised
    assert set(MODEL_CALLS_OUTSIDE_CREW) <= rows, sorted(set(MODEL_CALLS_OUTSIDE_CREW) - rows)  # no stale hand row


# R5
def test_the_registry_imports_nothing() -> None:
    tree = ast.parse(Path(seam_registry.__file__).read_bytes())
    assert [type(n).__name__ for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))] == []
```

### M0 focused check

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py -n 0 -q
d:/ProbOS/.venv/Scripts/python.exe -m tests.fixtures.ad1343_seam_census
```
Expect 19 + 6 passed, and a report whose last line counts the sites. Stage the four files by explicit path, then run `scripts/check_architecture_principles.py --check`, `scripts/check_seam_contracts.py --check` and `scripts/check_store_registry.py --check` (none should change: M0 touches nothing under `src/`). If R1 reports a key this contract did not list, **stop**: it is either a qualname this contract got wrong (fix the row; record it) or a real unguarded seam (hard stop to the Architect, do not register it).

---

## N1 implementation

### Section N1.1: `src/probos/cognitive/crew_finalizer.py`

**Block 1.1** (imports):

SEARCH:
```python
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, AgentStopService, active_stop
from probos.cognitive.crew_session import CrewSynthesisMetadata
```
REPLACE:
```python
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, AgentStopService, active_stop
from probos.cognitive.crew_session import CrewRecoveryTransientError, CrewSynthesisMetadata
```

**Block 1.2:**

SEARCH:
```python
from probos.cognitive.crew_verifier import (
    SessionConvergenceOutcome,
```
REPLACE:
```python
from probos.cognitive.crew_verifier import (
    CorrectionAdmittedNotExecuted,
    SessionConvergenceOutcome,
```

**Block 1.3** (the producer's correction, owner door):

SEARCH:
```python
        except AgentStopped as exc:  # A3 (R2): the producer was stopped before its correction; nothing is recorded
            raise ValueError("child_producer_unavailable") from exc
        return await self._defer_checkpoint(self._checkpoint_child_convergence(
```
REPLACE:
```python
        except CorrectionAdmittedNotExecuted as exc:  # N1 (F-177): its permit is kept; a retry would replay it as a defect
            raise ValueError("child_producer_unavailable") from exc
        except AgentStopped as exc:  # A3 (R2), N1: stopped before its correction; nothing is recorded, so a retry is safe
            raise CrewRecoveryTransientError("child_producer_stopped") from exc
        return await self._defer_checkpoint(self._checkpoint_child_convergence(
```

**Block 1.4** (the facilitator, owner door; not live keeps `ValueError`):

SEARCH:
```python
        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None or active_stop(self._agent_stops, session.facilitator_id, SEAM_AGENTIC_RUN) is not None:
            # AD-1343 A3 (R1): a facilitator stopped by the Captain's order is not available, as one not live; checked
            # before the synthesis is claimed, so no claim is left behind. Through the orchestrator this ends the session
            # blocked (recovery_integrity_conflict), which the Captain cannot yet retry (D44; AD-1343 S2).
            raise ValueError("synthesis_producer_unavailable")
```
REPLACE:
```python
        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None:
            raise ValueError("synthesis_producer_unavailable")
        if active_stop(self._agent_stops, session.facilitator_id, SEAM_AGENTIC_RUN) is not None:
            # AD-1343 A3 (R1): checked before the synthesis is claimed, so no claim is left behind. N1: the order is
            # transient, not an integrity conflict. The owner's recovery loop retries with backoff; the session continues
            # if the order is lifted in time and otherwise ends recovery_retry_exhausted, which the Captain may retry.
            raise CrewRecoveryTransientError("synthesis_producer_stopped")
```

**Block 1.5** (a session with no owned steps, D43):

SEARCH:
```python
        except AgentStopped as exc:  # A3 (R1), A4: a session with no owned steps, so nothing was claimed or synthesized
            raise ValueError("synthesis_producer_unavailable") from exc
```
REPLACE:
```python
        except AgentStopped as exc:  # A3 (R1), A4, N1: no owned steps, so nothing was claimed or synthesized; transient
            raise CrewRecoveryTransientError("synthesis_producer_stopped") from exc
```

The first-run door (`_finalize_claimed`, its `except AgentStopped:` blocks at `:2737` and `:2909`) is **not** edited (P1).

### Section N1.2: `src/probos/cognitive/crew_verifier.py`

**Block 2.1** (the new type; `AgentStopped` is already imported at line 58):

SEARCH:
```python
    return tuple(validated)


_MISSING_VERDICT_FIELD = object()
```
REPLACE:
```python
    return tuple(validated)


class CorrectionAdmittedNotExecuted(AgentStopped):
    """AD-1343 N1 (F-177): a session correction admitted (its permit recorded) and then refused at the run entry.

    Still an ``AgentStopped``, so every caller that maps a stop keeps its mapping. The owner's resume tells it apart:
    a retry would replay the kept permit through the interrupted-correction path and fail closed as
    ``correction_execution_defect``, so that session stays blocked for the Captain instead (D34).
    """


_MISSING_VERDICT_FIELD = object()
```

**Block 2.2** (`converge_for_session` docstring):

SEARCH:
```python
        AD-1343 A3: raises ``AgentStopped`` when the producer of a refuted child is stopped by the
        Captain's order before its correction runs. No correction executes and no outcome is
        returned, so nothing can read the stop as exhaustion; the finalizer blocks the session as
        for a producer that is not available.
        """
```
REPLACE:
```python
        AD-1343 A3: raises ``AgentStopped`` when the producer of a refuted child is stopped by the
        Captain's order before its correction runs. No correction executes and no outcome is
        returned, so nothing can read the stop as exhaustion. N1: the owner's resume retries it as
        transient; a correction admitted before the order landed raises the subclass
        ``CorrectionAdmittedNotExecuted`` instead, and that session stays blocked (F-177).
        """
```

**Block 2.3** (the run-entry refusal):

SEARCH:
```python
            except AgentStopped:
                # AD-1343 A3 (R2, R5): stopped after the check above, at the run entry. No correction executed and no
                # outcome is recorded. A correction admitted first (an owned session) keeps its permit as the evidence
                # of that admission, and is said so here.
                if correction_permit is not None:
                    logger.warning(
                        "AD-1343: correction %d of child %s was admitted but not executed: its producer %s is "
                        "stopped by the Captain's order",
                        attempt_index, current.work_item_id, current.agent_id,
                    )
                raise  # A3 (R2): the finalizer blocks the session as for a producer that is not available
```
REPLACE:
```python
            except AgentStopped as stop_refusal:
                # AD-1343 A3 (R2, R5): stopped after the check above, at the run entry. No correction executed and no
                # outcome is recorded. A correction admitted first (an owned session) keeps its permit as the evidence
                # of that admission, and is said so here.
                if correction_permit is not None:
                    logger.warning(
                        "AD-1343: correction %d of child %s was admitted but not executed: its producer %s is "
                        "stopped by the Captain's order",
                        attempt_index, current.work_item_id, current.agent_id,
                    )
                    # N1 (F-177): told apart, so the owner's resume keeps this session blocked; a retry would replay the
                    # kept permit and fail closed as correction_execution_defect.
                    raise CorrectionAdmittedNotExecuted(stop_refusal.record) from stop_refusal
                raise  # A3 (R2), N1: before admission; the owner's resume treats it as transient
```
Before applying, confirm `stop_refusal` is not otherwise bound in `converge_for_session` (`grep -n "stop_refusal" src/probos/cognitive/crew_verifier.py` finds nothing).

### Section N1.3: `src/probos/agent_stop.py` (Captain-facing text only)

**Block 3.1:**

SEARCH:
```python
        "it is not picked to verify a colleague's work; a crew session it facilitates is not synthesized "
        "and ends blocked for the Captain, as with a facilitator that is not live), correction re-runs of "
        "its refuted subtasks (a crew session ends blocked for the Captain instead, as with a producer that "
        "is not live, and cannot yet be retried after the lift (AD-1343 S2); elsewhere the result is "
        "escalated unverified), browser actions and every "
```
REPLACE:
```python
        "it is not picked to verify a colleague's work; a crew session it facilitates is not synthesized "
        "while the order stands: the session retries on its recovery schedule, continues if the order is "
        "lifted in time and otherwise ends blocked for the Captain, who can retry it after the lift), "
        "correction re-runs of its refuted subtasks (a crew session waits and ends in the same way; one whose "
        "correction was admitted just before the order ends blocked and cannot be retried; elsewhere the "
        "result is escalated unverified), browser actions and every "
```

**Block 3.2:**

SEARCH:
```python
LIFT_NOTE: Final = (
    "Dispatch is restored. Work refused while the agent was stopped is not replayed; "
    "refused_while_stopped counts it by seam since the last start."
)
```
REPLACE:
```python
LIFT_NOTE: Final = (
    "Dispatch is restored. Work refused while the agent was stopped is not replayed; "
    "refused_while_stopped counts it by seam since the last start. A crew session that was waiting "
    "on the agent continues on its own recovery schedule, or is blocked for the Captain to retry."
)
```
`S1_SCOPE["does_not_end"]` and `["not_covered"]` are unchanged (M0's registry quotes them).

### Section N1.4: edits to existing S1 tests

**`tests/test_ad1343_stop_crossing_resume.py`**

Block 4.1 (imports):

SEARCH:
```python
from probos import work_item_steps as owned_steps
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
```
REPLACE:
```python
from probos import work_item_steps as owned_steps
from probos.agent_stop import AgentStopped
from probos.cognitive.crew_finalizer import CrewSessionFinalizer
from probos.cognitive.crew_session import CrewRecoveryTransientError
```

Block 4.2 (docstring, X10):

SEARCH:
```
- X10  a stopped facilitator: ``ValueError("synthesis_producer_unavailable")`` BEFORE the owned
       synthesis is claimed, so the synthesizer is not called and a resume after the lift is not read
```
REPLACE:
```
- X10  a stopped facilitator: ``CrewRecoveryTransientError("synthesis_producer_stopped")`` (N1) BEFORE the
       owned synthesis is claimed, so the synthesizer is not called and a resume after the lift is not read
```

Block 4.3 (docstring, X11):

SEARCH:
```
- X11  a stopped producer of a refuted child: ``ValueError("child_producer_unavailable")`` as for a
       producer with ``is_alive=False``, and no trust-outbox row.
```
REPLACE:
```
- X11  a stopped producer of a refuted child: ``CrewRecoveryTransientError("child_producer_stopped")``
       (N1), otherwise as for a producer with ``is_alive=False``, and no trust-outbox row;
- X10c (N1) a stop landing after the facilitator check of a synthesis that is not claimed (a session with
       no owned steps) is transient too; X10d (N1) a facilitator that is not live keeps ``ValueError``.
```

Block 4.4 (X10):

SEARCH:
```python
        with pytest.raises(ValueError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert str(refused.value) == "synthesis_producer_unavailable"
```
REPLACE:
```python
        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert refused.value.code == "synthesis_producer_stopped"  # N1: transient, so the owner's recovery loop retries it
```

Block 4.5 (X11 `observe`):

SEARCH:
```python
    async def observe(rig: _Rig) -> dict[str, Any]:
        with pytest.raises(ValueError) as refused:
            await rig.finalizer.resume(rig.parent_id)
```
REPLACE:
```python
    async def observe(rig: _Rig) -> dict[str, Any]:
        with pytest.raises((ValueError, CrewRecoveryTransientError)) as refused:
            await rig.finalizer.resume(rig.parent_id)
```

Block 4.6:

SEARCH:
```python
        return {
            "error": str(refused.value),
            "state": session.state,
```
REPLACE:
```python
        return {
            "error": str(refused.value),
            "kind": type(refused.value).__name__,
            "state": session.state,
```

Block 4.7:

SEARCH:
```python
        assert not_live["error"] == "child_producer_unavailable"  # premise: the established vocabulary for a producer not live
```
REPLACE:
```python
        assert not_live["error"] == "child_producer_unavailable"  # premise: the established vocabulary for a producer not live
        assert not_live["kind"] == "ValueError"  # N1: a producer that is not live is still an integrity conflict
```

Block 4.8:

SEARCH:
```python
            assert stopped["error"] == "child_producer_unavailable"
```
REPLACE:
```python
            assert (stopped["kind"], stopped["error"]) == ("CrewRecoveryTransientError", "child_producer_stopped")  # N1
```

Block 4.9:

SEARCH:
```python
            # ends exactly as the same resume with the producer not live (the judge was asked once here, never there)
            assert stopped == not_live
```
REPLACE:
```python
            # N1: ends as the same resume with the producer not live in every other respect (the judge was asked once
            # here, never there), except that the stop is transient
            assert {**stopped, "kind": None, "error": None} == {**not_live, "kind": None, "error": None}
```

Block 4.10 (append X10c and X10d after the file's last test):

SEARCH:
```python
        assert await _outbox_rows(case.stores.work) != []  # the trust the session earned is recorded
        assert _loud(caplog) == []  # the stop module writes nothing when no order is in force
```
REPLACE:
```python
        assert await _outbox_rows(case.stores.work) != []  # the trust the session earned is recorded
        assert _loud(caplog) == []  # the stop module writes nothing when no order is in force


# X10c (N1, D43)
async def test_resume_of_an_unclaimed_synthesis_stopped_after_the_facilitator_check_is_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True)], synth=[])

        async def claim_nothing_then_stop(session: Any) -> None:
            # A session with no owned steps claims nothing; the order lands before the synthesizer's own entry check.
            await stops.issue_stop(FACILITATOR, reason=REASON)
            return None

        monkeypatch.setattr(rig.finalizer, "_claim_owned_synthesis", claim_nothing_then_stop)
        assert stops.stop_for(FACILITATOR) is None  # premise: the finalizer's own check passes

        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert refused.value.code == "synthesis_producer_stopped"
        assert isinstance(refused.value.__cause__, AgentStopped)  # refused at the synthesizer's entry, not by the finalizer
        assert rig.synth.requests == [] and await rig.synthesis_claim() is None


# X10d (N1)
async def test_resume_with_a_facilitator_that_is_not_live_is_still_an_integrity_conflict(
    tmp_path: Path, trust_network: TrustNetwork,
) -> None:
    async with _executed_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, trust_network, judge=[_verdict(True)], synth=[])
        rig.registry.get(FACILITATOR).is_alive = False
        assert stops.stop_for(FACILITATOR) is None  # premise: no order; the facilitator is simply not live

        with pytest.raises(ValueError) as refused:
            await rig.finalizer.resume(rig.parent_id)

        assert str(refused.value) == "synthesis_producer_unavailable"
        assert rig.synth.requests == []
```

**`tests/test_ad1343_agent_stop_verify.py`** (T35)

Block 4.11:

SEARCH:
```python
from probos.cognitive.crew_verifier import SessionVerificationPass, SubtaskVerifier, VerificationVerdict
```
REPLACE:
```python
from probos.cognitive.crew_verifier import (
    CorrectionAdmittedNotExecuted,
    SessionVerificationPass,
    SubtaskVerifier,
    VerificationVerdict,
)
```

Block 4.12:

SEARCH:
```python
        record = service.stop_for(AGENT)
        assert record is not None and raised.value.record == record  # the order landed during the admission
```
REPLACE:
```python
        record = service.stop_for(AGENT)
        assert record is not None and raised.value.record == record  # the order landed during the admission
        assert type(raised.value) is CorrectionAdmittedNotExecuted  # N1 (F-177): told apart from a refusal before admission
```

### Section N1.5: new file `tests/test_ad1343_stop_crossing_retry.py`

```python
"""AD-1343 N1 (#1595): a crew session stopped by the Captain's order can be finished after the lift.

S1 ended such a session ``blocked_needs_captain`` / ``recovery_integrity_conflict``, which the Captain could not retry.
N1 raises a transient error at the stop checks of the owner's resume, so the owner's recovery loop retries it with
backoff. These tests cross the whole chain on real parts: a real ``AgentStopService`` over ``agent_stops.db`` -> the
real ``CrewOrchestrator._run_owned_parent`` and its recovery loop -> the real verifier, synthesizer and finalizer over
real stores -> the real authorizer, through ``CrewSessionService.open_or_resume(retry_blocked=True)``:

- X12  a stopped facilitator or producer: blocked ``recovery_retry_exhausted`` after the bounded retries -> lift -> the
       Captain's retry is authorized -> the owner finishes the session;
- X13  the order is lifted during the backoff: the session finishes by itself, with no Captain action;
- X14  F-177: a correction admitted just before the order keeps its permit, and the session still ends blocked
       ``recovery_integrity_conflict``, which the Captain cannot retry (a retry would replay the permit as a defect).

One ``CrewSessionService`` owns the session, the finalizer's checkpoints and the authorizer: the store binds a single
owned-steps owner (``CrewSessionService.register_owned_steps_component``). Nothing sleeps: the owner's clock and sleep
are injected, and every owner run is bounded with ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import CrewRecoveryTransientError, CrewSessionService, _build_adopted_recovery_plan
from probos.config import AgenticDispatchConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.workforce import CrewSessionParentCreate
from tests.test_ad1125_room_bound_execution import (
    _Agent as _ExecutionAgent,
    _Clock,
    _Registry as _ExecutionRegistry,
    _StaticOutcomeExecutor,
    _child,
    _crew_executor,
    _runtime as _execution_runtime,
    stores as _execution_stores,
)
from tests.test_ad1126_verified_finalization import _registry_for, _text, _verdict
from tests.test_ad1244_verdict_criteria import _ExecutedSession
from tests.test_ad1343_agent_stop import LIFT_REASON, REASON, _service
from tests.test_ad1343_agent_stop_crew import _BOUND, _CountingLLM
from tests.test_ad1343_stop_crossing_resume import FACILITATOR, FINAL_TEXT, _Rig

MAX_RETRIES = 1
INITIAL_BACKOFF = 2.0


class _CrewTypes:
    """The ontology's crew types: every agent the rig registers is crew, so the Captain's retry can validate the room."""

    def get_crew_agent_types(self) -> set[str]:
        return {"facilitator", "builder", "reviewer"}


@asynccontextmanager
async def _retryable_session(tmp_path: Path) -> AsyncIterator[_ExecutedSession]:
    """``_executed_session`` (``tests/test_ad1244_verdict_criteria.py``), with its session owned by a service wired for
    the Captain's retry: the config (the retry bound), the registry, the ontology and the admission port."""
    generator = _execution_stores.__wrapped__(tmp_path)
    stores = await generator.__anext__()
    try:
        async with stores.admission_port.reserve() as reservation:
            parent = await reservation.create_parent(CrewSessionParentCreate(
                id="crew-session-n1-retry",
                title="Room-bound session",
                description="Room-bound session",
                assigned_to="facilitator-1",
                created_by="captain",
                metadata={},
                created_at=100.0,
                steps=[],
            ))
        thread = stores.chat.create_thread(
            title="Room-bound session", participants=["facilitator-1", "agent-1"], task_id=parent.id,
        )
        service = CrewSessionService(
            work_item_store=stores.work,
            chat_thread_store=stores.chat,
            registry=_registry_for([SimpleNamespace(id="checkpoint-child", assigned_to="agent-1")]),
            ontology=_CrewTypes(),
            config=AgenticDispatchConfig(orchestrator_enabled=True, crew_recovery_max_retries=MAX_RETRIES),
            admission_port=stores.admission_port,
            clock=_Clock(200.0),
        )
        await service.initialize_session(
            parent.id,
            thread.id,
            goal="Produce a room-bound result",
            origin="captain",
            originator_id="captain",
            facilitator_id="facilitator-1",
            owner_ids=["facilitator-1", "agent-1"],
            success_criteria=["Artifact is persisted", "Evidence is durable"],
            expected_deliverable="A persisted report",
        )
        child = await _child(stores, parent_id=parent.id, child_id="checkpoint-child")
        session = await service.get_session(parent.id)
        assert session is not None
        executing = await service.transition_session(parent.id, "executing", expected_revision=session.revision)
        await service.adopt_recovery_plan(
            parent.id, expected_session=executing, expected_recovery=None,
            plan=_build_adopted_recovery_plan(parent.id, (child,)), expected_children=(child,),
        )
        runtime = _execution_runtime(stores, tmp_path)
        runtime.crew_session_service = service
        executor = _crew_executor(
            stores=stores, registry=_ExecutionRegistry({"agent-1": _ExecutionAgent("agent-1")}),
            executor=_StaticOutcomeExecutor(output="Durable child evidence", total_tokens=7),
            runtime=runtime, service=service,
        )
        results = await executor.resume(parent.id)
        assert len(results) == 1 and results[0].status == "done"
        child = await stores.work.get_work_item(child.id)
        assert child is not None
        yield _ExecutedSession(stores, parent, thread, service, child, results)
    finally:
        await generator.aclose()


def _owner(
    rig: _Rig, sleeps: list[float], on_sleep: Callable[[], Awaitable[None]] | None = None,
) -> CrewOrchestrator:
    """The real owner over the rig's one service and its finalizer, with an injected clock and sleep."""
    now = {"value": 1_000.0}
    config = SystemConfig()
    config.agentic_dispatch.orchestrator_enabled = True
    config.agentic_dispatch.crew_recovery_max_retries = MAX_RETRIES
    config.agentic_dispatch.crew_recovery_initial_backoff_seconds = INITIAL_BACKOFF
    config.agentic_dispatch.crew_recovery_max_backoff_seconds = 3.0

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        now["value"] += delay
        if on_sleep is not None:
            await on_sleep()

    return CrewOrchestrator(
        assignment_resolver=object(),
        delegator=object(),
        crew_executor=object(),
        verifier=object(),
        synthesizer=object(),
        work_item_store=rig.case.stores.work,
        runtime=SimpleNamespace(),
        config=config,
        crew_session_finalizer=rig.finalizer,
        crew_session_service=rig.case.service,
        clock=lambda: now["value"],
        sleep=sleep,
    )


async def _captain_retry(case: _ExecutedSession) -> Any:
    session = await case.service.get_session(case.parent.id)
    assert session is not None
    return await case.service.open_or_resume(
        principal=case.service.captain_principal(),
        goal=session.goal,
        success_criteria=list(session.success_criteria),
        expected_deliverable=session.expected_deliverable,
        requested_thread_id=case.thread.id,
        retry_blocked=True,
    )


# X12
@pytest.mark.parametrize("role", ["facilitator", "producer"])
async def test_a_stopped_session_is_retried_by_the_captain_after_the_lift_and_finishes(tmp_path: Path, role: str) -> None:
    if role == "facilitator":
        judge = [_verdict(True), _verdict(True)]
        code = "synthesis_producer_stopped"
    else:
        judge = [*(_verdict(False, critique="incomplete") for _ in range(4)), _verdict(True), _verdict(True)]
        code = "child_producer_stopped"
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, TrustNetwork(), judge=judge, synth=[_text(FINAL_TEXT)])
        agent_id = FACILITATOR if role == "facilitator" else rig.producer_id
        record = (await stops.issue_stop(agent_id, reason=REASON)).record

        # Premise: the first resume, made directly, refuses with the transient code and leaves the session verifying.
        with pytest.raises(CrewRecoveryTransientError) as refused:
            await rig.finalizer.resume(rig.parent_id)
        assert refused.value.code == code
        verifying = await case.service.get_session(rig.parent_id)
        assert verifying is not None and verifying.state == "verifying"

        sleeps: list[float] = []
        owner = _owner(rig, sleeps)
        owned = await asyncio.wait_for(owner._run_owned_parent(rig.parent_id), timeout=_BOUND)

        blocked = await case.service.get_session(rig.parent_id)
        recovery = await case.service.get_recovery(rig.parent_id)
        assert owned.completed is False and blocked is not None and recovery is not None
        assert (blocked.state, blocked.blocked_reason) == ("blocked_needs_captain", "recovery_retry_exhausted")
        assert (recovery.last_error_code, recovery.retry_count) == ("recovery_retry_exhausted", MAX_RETRIES)
        assert sleeps == [INITIAL_BACKOFF]  # one bounded backoff, then exhaustion
        assert rig.synth.requests == [] and await rig.synthesis_claim() is None  # nothing synthesized or claimed
        assert len(rig.correction.calls) == 0  # the stopped producer ran nothing
        assert stops.refused_counts(record.stop_id) == {"agentic_run": 3}  # the direct resume and both owner attempts

        lifted = await stops.lift_stop(agent_id, reason=LIFT_REASON)
        assert lifted.refused == {"agentic_run": 3}
        scheduled: list[asyncio.Task[Any]] = []

        def schedule(parent_id: str) -> asyncio.Task[Any]:
            task = asyncio.create_task(owner._run_owned_parent(parent_id))
            scheduled.append(task)
            return task

        case.service.bind_scheduler(schedule)
        retried = await _captain_retry(case)
        assert (retried.state, retried.scheduled) == ("verifying", True)  # the Captain's retry is authorized
        assert len(scheduled) == 1
        finished = await asyncio.wait_for(scheduled[0], timeout=_BOUND)

        done = await case.service.get_session(rig.parent_id)
        assert finished.completed is True and done is not None and done.state == "done"
        assert len(rig.synth.requests) == 1  # the one synthesis, after the lift
        if role == "facilitator":
            assert len(rig.judge.requests) == 2  # the child once (checkpointed before the stop), the final verification once
        else:
            # D12 (F-178, measured): round 0 is judged again at each attempt (three while stopped, one after the retry),
            # then the correction and the final verification once each.
            assert len(rig.judge.requests) == 6 and len(rig.correction.calls) == 1


# X13
async def test_a_stop_lifted_during_the_backoff_lets_the_session_finish_by_itself(tmp_path: Path) -> None:
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(case, tmp_path, stops, TrustNetwork(), judge=[_verdict(True), _verdict(True)], synth=[_text(FINAL_TEXT)])
        await stops.issue_stop(FACILITATOR, reason=REASON)
        with pytest.raises(CrewRecoveryTransientError):
            await rig.finalizer.resume(rig.parent_id)  # premise: the session is verifying and its synthesis was refused
        lifts: list[Any] = []

        async def lift_during_backoff() -> None:
            lifts.append(await stops.lift_stop(FACILITATOR, reason=LIFT_REASON))

        sleeps: list[float] = []
        owner = _owner(rig, sleeps, on_sleep=lift_during_backoff)
        finished = await asyncio.wait_for(owner._run_owned_parent(rig.parent_id), timeout=_BOUND)

        done = await case.service.get_session(rig.parent_id)
        assert finished.completed is True and done is not None and done.state == "done"  # no Captain action
        assert sleeps == [INITIAL_BACKOFF] and len(lifts) == 1
        assert lifts[0].refused == {"agentic_run": 2}  # the direct resume and the first owner attempt
        assert (len(rig.judge.requests), len(rig.synth.requests)) == (2, 1)
        assert stops.stop_for(FACILITATOR) is None


# X14 (F-177)
async def test_a_correction_admitted_just_before_the_stop_still_blocks_and_is_not_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    llm = _CountingLLM()
    refute = [_verdict(False, critique="incomplete") for _ in range(2)]
    async with _retryable_session(tmp_path) as case, _service(tmp_path / "stops") as stops:
        rig = _Rig(
            case, tmp_path, stops, TrustNetwork(), judge=refute, synth=[],
            correction=WorkItemAgenticExecutor(llm_client=llm),
        )
        await stops.issue_stop(rig.producer_id, reason=REASON)
        with pytest.raises(CrewRecoveryTransientError):
            await rig.finalizer.resume(rig.parent_id)  # premise: refused before admission; the session is verifying
        await stops.lift_stop(rig.producer_id, reason=LIFT_REASON)

        admit = case.service.admit_correction
        admitted: list[str] = []

        async def admit_then_stop(*args: Any, **kwargs: Any) -> Any:
            # The F-177 window: the real admission records the permit, then the Captain's order lands before the run entry.
            admission = await admit(*args, **kwargs)
            admitted.append(admission.disposition)
            await stops.issue_stop(rig.producer_id, reason=REASON)
            return admission

        monkeypatch.setattr(case.service, "admit_correction", admit_then_stop)
        with caplog.at_level(logging.WARNING):
            owned = await asyncio.wait_for(_owner(rig, [])._run_owned_parent(rig.parent_id), timeout=_BOUND)

        blocked = await case.service.get_session(rig.parent_id)
        assert owned.completed is False and admitted == ["new"]
        assert blocked is not None
        assert (blocked.state, blocked.blocked_reason) == ("blocked_needs_captain", "recovery_integrity_conflict")
        assert llm.calls == []  # the correction never ran
        assert sum("admitted but not executed" in r.getMessage() for r in caplog.records) == 1
        assert len(rig.judge.requests) == 2

        await stops.lift_stop(rig.producer_id, reason=LIFT_REASON)
        with pytest.raises(ValueError, match="crew_session_retry_not_authorized"):
            await _captain_retry(case)
```

### Section N1.6: N1 rows in the M0 registry and census

**Block 6.1** (`tests/fixtures/ad1343_seam_census.py`, record the new callees):

SEARCH:
```python
RECORDED = STOP_CALLEES | AGENT_WORK_METHODS | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
}
```
REPLACE:
```python
RECORDED = STOP_CALLEES | AGENT_WORK_METHODS | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
    "CrewRecoveryTransientError", "finalize", "run_crew_task",  # N1
}
```

**Block 6.2** (same file, inside `Visitor.visit_Call`, the seam extraction S1 wrote):

SEARCH:
```python
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
```
REPLACE:
```python
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
            elif callee == "CrewRecoveryTransientError" and node.args:  # N1: the transient code it is built with
                seam = ast.unparse(node.args[0])
```

**Block 6.3** (`tests/fixtures/ad1343_seam_registry.py`, append after `MODEL_CALLS_OUTSIDE_CREW`):

SEARCH:
```python
MODEL_CALLS_OUTSIDE_CREW: dict[tuple[str, str], str] = {}
```
REPLACE:
```python
MODEL_CALLS_OUTSIDE_CREW: dict[tuple[str, str], str] = {}

# N1: every construction of the recovery loop's transient error, by (file, function, the code it is built with).
RECOVERY_TRANSIENT_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator._translate_recovery_boundary_error", "code"):
        "AD-1127: a timeout, connection, busy or OS error at a recovery boundary",
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_child_convergence", "'child_producer_stopped'"):
        "N1: the producer of a refuted child is stopped before its correction is admitted",
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "'synthesis_producer_stopped'"):
        "N1: the facilitator is stopped before its synthesis is claimed, or before an unclaimed synthesis starts",
}

# N1 (P1): the first-run door is reached only through run_crew_task, and run_crew_task only from the owner when no
# session service is wired, which production refuses (startup/finalize.py, the mandatory dependency check).
FIRST_RUN_DOOR: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator.run_crew_task", "finalize"),
    ("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator._run_owned_parent", "run_crew_task"),
})
```

**Block 6.4** (`tests/test_ad1343_seam_registry.py`): add `FIRST_RUN_DOOR` and `RECOVERY_TRANSIENT_SITES` to the `from tests.fixtures.ad1343_seam_registry import ...` line (alphabetical), and append:

```python


# N1
def test_every_recovery_transient_is_classified() -> None:
    found = {(c.file, c.function, c.seam) for c in census() if c.callee == "CrewRecoveryTransientError"}
    assert found == set(RECOVERY_TRANSIENT_SITES), sorted(found ^ set(RECOVERY_TRANSIENT_SITES))


# N1 (P1)
def test_the_first_run_finalize_door_is_reached_only_without_a_session_service() -> None:
    found = {(c.file, c.function, c.callee) for c in census() if c.callee in {"finalize", "run_crew_task"}}
    assert found == FIRST_RUN_DOOR, sorted(found ^ FIRST_RUN_DOOR)
    owner = function("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator._run_owned_parent")
    assert "self._crew_session_service is None" in ast.unparse(owner)  # the run_crew_task branch needs no service
```

### Section N1.7: trackers (in N1's milestone, covering both slices)

**`PROGRESS.md`:** insert a new entry between line 1 (`# ProbOS Progress`) and the AD-1343 S1 entry (line 3), separated by one blank line on each side:

> **AD-1343 batch A (2026-10-20), #1595 -- M0: the stop's seam census is now a living registry of every place agent work can start, each naming the guard that refuses a stopped agent there, and a test fails when a new one appears or a listed one loses its guard. N1: a crew session stopped by the Captain's order can be finished after the lift.** M0 moves the S1 census into `tests/fixtures/ad1343_seam_census.py` and its tables into one import-free registry, `tests/fixtures/ad1343_seam_registry.py`, and adds `tests/test_ad1343_seam_registry.py`: it scans `src/probos` for calls that start another agent's work (CognitiveAgent's classified public coroutines and work starters, called on another receiver), and fails on one the registry does not list, or on a listed guard that is no longer found, no longer first or no longer named in `S1_SCOPE`. The Captain's list of seams (cognition, Ward Room, DM, the agentic loop, work items, delegation, the crew executor and verifier, consultation, browser actions, the sandbox and long runs) is indexed with its guard. Model calls outside the crew modules are reported (`python -m tests.fixtures.ad1343_seam_census`), not gated, until #1601 M3. N1: a stopped facilitator or producer no longer ends its crew session as an integrity conflict the Captain cannot retry. The owner's resume treats the stop as transient: the recovery loop retries with its backoff, the session continues if the order is lifted in time, and otherwise ends `recovery_retry_exhausted`, which the Captain can retry after the lift. What continues is the session's own blocked step, never work refused during the stop; `S1_SCOPE` and the lift's note say so. A correction admitted just before the order (F-177) still ends the session blocked and not retryable, because a retry would replay its permit as a defect; a facilitator or producer that is not live is unchanged. This supersedes the S1 entry's "a retry after the lift is S2". No persisted schema, event, route or config change. Decisions in DECISIONS.md (AD-1343 batch A); contract `prompts/ad-1343-batch-a-m0-seam-registry-n1-stop-retry.md`.

**`DECISIONS.md`:** insert a new section after the AD-1343 S1 section, immediately before the line `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)`, with one blank line before it. Title: `### AD-1343 batch A -- M0 the seam registry and its guard test; N1 a stopped crew session the Captain can retry (2026-10-20, #1595)`. Content: a *Scope* bullet (the two slices, one batch, HIGH tier, the Captain's authorization of M0 in comment 6282055471 and the Architect's placement of N1 under D44's last sentence); a *Decision* bullet summarizing Solution (M0 1-4, N1 1-4); a *Rejected alternatives* bullet; D1 to D18 of this contract, each one line with its rejected alternative; *Supersedes* (D44's move of N1 to S2, residual (6) and behaviour change (6) of the S1 section, which stay as the record of S1); *Behaviour changes (intended)* (with no stop issued nothing changes; with a stop: the crew-session continuation and its exhaustion; the Captain's retry now authorized; `S1_SCOPE` and `LIFT_NOTE` text); *Reversal* (revert the batch's two commits; nothing persisted needs cleaning: the two codes appear in `last_error_code` only while a session backs off); *Tests* (files and collected counts read by `pytest --collect-only`, not run results); the contract path. Do not edit the S1 section.

**`docs/research/reference-projects.md`** (Prior Art below):

SEARCH:
```
| Google Agent Development Kit | 2026-04-08 | passing | `universal-agent-activation-research.md` (the agent layer of Solace Agent Mesh) |
| OpenAI Agents SDK | never | never | none |
```
REPLACE:
```
| Google Agent Development Kit | 2026-10-20 | checked | AD-1343 batch A (#1595) Prior Art, `prompts/ad-1343-batch-a-m0-seam-registry-n1-stop-retry.md` (`before_agent_callback` skips an agent at one entry: the single-gate shape #1601 targets; nothing to absorb for M0); `universal-agent-activation-research.md` (the agent layer of Solace Agent Mesh) |
| OpenAI Agents SDK | 2026-10-20 | checked | AD-1343 batch A (#1595) Prior Art, `prompts/ad-1343-batch-a-m0-seam-registry-n1-stop-retry.md` (a guardrail tripwire raises an exception the application maps, as `AgentStopped` does; nothing new) |
```

No `roadmap.md` row (no BF). No EventType (no Section 0).

### N1 focused check

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_stop_crossing_resume.py tests/test_ad1343_stop_crossing_retry.py tests/test_ad1343_agent_stop_verify.py tests/test_ad1343_agent_stop_crew.py tests/test_ad1343_stop_crossing_finalizer.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_agent_stop.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1128_crew_session_ingress_dedup.py tests/test_ad1244_verdict_criteria.py tests/test_ad1130_outcome_only_room_trust.py -q
```
The second line is the consumer set (finalizer, owner, authorizer); it runs at the default parallelism, and any failure is rerun at `-n 0` before triage. Then stage by explicit path and run the three scripts as in M0.

---

## Tests

| ID | File | Test | Proves |
|---|---|---|---|
| R1 | `tests/test_ad1343_seam_registry.py` | `test_every_agent_work_call_is_registered` | a new seam fails; a removed one fails |
| R2 | same | `test_every_registered_call_names_a_guard_that_still_holds` | a registered seam that loses its guard fails |
| R2i | same | `test_every_indexed_seam_names_a_guard_that_still_holds` | the Captain's list holds, and every `SEAM_*` value is indexed |
| R3 | same | `test_the_scan_counts_only_calls_that_start_another_agents_work` | the scanner's rule, boundary cases |
| R4 | same | `test_the_model_call_report_covers_the_sites_outside_the_crew_modules_and_gates_nothing` | the report exists, classifies, has no stale hand row |
| R5 | same | `test_the_registry_imports_nothing` | M3 can add a column |
| R6 | same | `test_every_recovery_transient_is_classified` | N1's transient raises are pinned |
| R7 | same | `test_the_first_run_finalize_door_is_reached_only_without_a_session_service` | P1 |
| X10 (edited) | `tests/test_ad1343_stop_crossing_resume.py` | `test_resume_with_a_stopped_facilitator_is_refused_before_the_claim_and_resumes_after_the_lift` | stop is transient, still before the claim |
| X11 (edited) | same | `test_resume_with_a_stopped_producer_ends_as_with_a_producer_not_live` | transient; otherwise identical to not live |
| X10c | same | `test_resume_of_an_unclaimed_synthesis_stopped_after_the_facilitator_check_is_transient` | the D43 branch (S1's surviving mutant F2) |
| X10d | same | `test_resume_with_a_facilitator_that_is_not_live_is_still_an_integrity_conflict` | not live keeps `ValueError` |
| T35 (edited) | `tests/test_ad1343_agent_stop_verify.py` | `test_a_correction_admitted_then_refused_at_the_run_entry_logs_one_warning_and_keeps_its_permit` | F-177's distinct type |
| X12 | `tests/test_ad1343_stop_crossing_retry.py` | `test_a_stopped_session_is_retried_by_the_captain_after_the_lift_and_finishes[facilitator|producer]` | **the crossing**: stop -> blocked -> lift -> Captain retry -> done, through the real owner, finalizer, stores and authorizer |
| X13 | same | `test_a_stop_lifted_during_the_backoff_lets_the_session_finish_by_itself` | automatic continuation inside the window |
| X14 | same | `test_a_correction_admitted_just_before_the_stop_still_blocks_and_is_not_retryable` | F-177 stays blocked, honestly |

Goldens: X10 golden, X11 golden and X10b are unchanged and must pass; with no order issued every changed path behaves as before.

---

## Mutation table (HIGH tier)

Rows are whole stripped lines, each unique in its file after the build. Runner set: the 14 `tests/test_ad1343_*.py` modules, `tests/test_ad1127_crew_session_lifecycle_recovery.py` and `tests/test_ad1126_verified_finalization.py`.

| ID | File | Original line (stripped) | Mutant | Expected killer |
|---|---|---|---|---|
| M0-1 | `src/probos/routers/agents.py` | `_stopped = active_stop(getattr(runtime, "agent_stops", None), agent_id, SEAM_DM_ROUTE)` | `_stopped = None` | R2, R2i (and S1 `test_stop_checks_are_exactly_the_inventory`) |
| M0-2 | `src/probos/routers/agents.py` | `await agent.observe_self_avatar()` | `await agent.check_own_render()` | R1 |
| M0-3 | `src/probos/cognitive/sandbox.py` | `agent.handle_intent(test_intent),` | `agent.handle_consultation_request(test_intent),` | R1 (a new seam) |
| M0-4 | `src/probos/cognitive/turn_promotion.py` | `outcome = await agent.recover_promoted_turn(item, request_id)` | `outcome = await agent.resume_promoted_turn(item, request_id)` | R1 |
| M0-5 | `src/probos/agent_stop.py` | `"a promoted turn the Captain approves while the agent is stopped resumes, with its tool "` | `"a promoted turn resumes, with its tool "` | R2, R2i |
| M0-6 | `tests/fixtures/ad1343_seam_census.py` | `if call.callee not in AGENT_WORK_METHODS or call.receiver in ("", "self") or call.receiver.startswith("super("):` | `if call.callee not in AGENT_WORK_METHODS:` | R3, R1 |
| M0-7 | `tests/fixtures/ad1343_seam_census.py` | `return last == "agent" or last.endswith("_agent")` | `return True` | R3, R1 |
| M0-8 | `tests/fixtures/ad1343_seam_census.py` | `) \| frozenset(registry.SYNC_WORK_STARTERS)` | `)` | R1 |
| M0-9 | `tests/fixtures/ad1343_seam_registry.py` | `("src/probos/cognitive/sandbox.py", "SandboxRunner.test_agent", "handle_intent"): ("sink", _INTENT_SINK),` | (empty line) | R1 |
| N1-1 | `src/probos/cognitive/crew_finalizer.py` | `raise CrewRecoveryTransientError("synthesis_producer_stopped")` | `raise ValueError("synthesis_producer_unavailable")` | X10, X12[facilitator], X13 |
| N1-2 | `src/probos/cognitive/crew_finalizer.py` | `raise CrewRecoveryTransientError("synthesis_producer_stopped") from exc` | `raise ValueError("synthesis_producer_unavailable") from exc` | X10c |
| N1-3 | `src/probos/cognitive/crew_finalizer.py` | `raise CrewRecoveryTransientError("child_producer_stopped") from exc` | `raise ValueError("child_producer_unavailable") from exc` | X11, X12[producer] |
| N1-4 | `src/probos/cognitive/crew_finalizer.py` | `raise ValueError("child_producer_unavailable") from exc` | `raise CrewRecoveryTransientError("child_producer_stopped") from exc` | X14 |
| N1-5 | `src/probos/cognitive/crew_finalizer.py` | `raise ValueError("synthesis_producer_unavailable")` | `raise CrewRecoveryTransientError("synthesis_producer_stopped")` | X10d |
| N1-6 | `src/probos/cognitive/crew_finalizer.py` | `except CorrectionAdmittedNotExecuted as exc:  # N1 (F-177): its permit is kept; a retry would replay it as a defect` | `except ZeroDivisionError as exc:` | X14 |
| N1-7 | `src/probos/cognitive/crew_verifier.py` | `raise CorrectionAdmittedNotExecuted(stop_refusal.record) from stop_refusal` | `raise` | T35, X14 |
| N1-8 | `src/probos/cognitive/crew_verifier.py` | `raise  # A3 (R2), N1: before admission; the owner's resume treats it as transient` | `raise CorrectionAdmittedNotExecuted(stop_refusal.record) from stop_refusal` | T33 race (`tests/test_ad1343_agent_stop_crew.py:461`, `raised.value is entry.raised`) |
| N1-9 | `src/probos/cognitive/crew_orchestrator.py` | `transient = self._as_recovery_transient(exc)` | `transient = None` | X12, X13 |
| N1-10 | `src/probos/cognitive/crew_session.py` | `and recovery.last_error_code == "recovery_retry_exhausted"` | `and False` | X12 |
| N1-11 | `tests/fixtures/ad1343_seam_census.py` | `elif callee == "CrewRecoveryTransientError" and node.args:  # N1: the transient code it is built with` | `elif False:` | R6 |
| N1-12 | `tests/fixtures/ad1343_seam_registry.py` | `("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator.run_crew_task", "finalize"),` | (empty line) | R7 |

M0-8's original line starts with `)` followed by ` | frozenset(...)`; the table escapes the pipe. N1-10 is existing code: it proves X12 really reaches the authorizer's exhausted branch. If a row survives, record it as a gap with its reason; do not weaken a test to kill it.

---

## What This Does NOT Change

- The first-run finalizer door (`_finalize_claimed`) and its S1 tests (P1).
- A facilitator or producer that is not live: still `ValueError`, still `recovery_integrity_conflict`, still not retryable.
- The authorizer, the recovery loop, its backoff policy and config (`crew_recovery_max_retries`, the backoff seconds), and the persisted contracts (`CrewRecoveryContract`, `CrewSessionContract`, `agent_stops.db`).
- `AgentStopService`, the seams and their counting (`SEAMS` does not grow), the routes, the EventLog pair, the census of the AD-1195 freeze.
- In-flight work (S2) and the vessel-wide stop (S3): both remain #1601 M4.
- The admission gate itself (#1601 M3): M0 makes bypasses visible; it does not route anything through one gate.
- `docs/development/seams/*.yaml` (the AD-1270 inter-component catalog, a different denominator).
- Historical S1 entries in `DECISIONS.md` and `PROGRESS.md`.

---

## Decisions (batch A)

| ID | Decision | Rejected |
|---|---|---|
| D1 | The registry and census live in `tests/fixtures/` (tooling side; nothing in `src/probos` reads them). | A module under `src/probos` (runtime carrying test data; the architecture caps); a YAML catalog beside `docs/development/seams` (a different denominator, and a parser to maintain). |
| D2 | One import-free data module; the census imports it. | One combined module (an M3 column could create a cycle); a JSON file (no comments, no tuple keys). |
| D3 | Primitives are derived from S1's classified CognitiveAgent coroutines and work starters; a seam is an attribute call on a receiver other than `self`/`super()`; generic names need an agent-named receiver. | A name-only scan (measured: `store.decide` at `delegated_approvals.py:677` and four other stores, `organ.act` at `economic_judgment_organ.py:920`, `optimizer.decide` at `routers/chain_optimizer.py:71`); type inference (not static); listing `handle_intent` references (bus and handler references are unbounded, and the sink refuses them anyway). |
| D4 | Guards are typed (sink, check, upstream, exception, at, none) and each is re-proved from the census on every run. | A hand-kept "guarded: yes" flag (it cannot lose its guard). |
| D5 | S1's inventory imports the lifted code under its old names; its 19 test bodies are byte-identical. | Renaming inside S1's tests (churn, and S1's campaign of record maps by test name). |
| D6 | `.complete(` outside the crew modules: a report (function and `python -m`), classified structurally with an empty hand table; only stale hand rows fail. | Gating it now (#1601 M3's coverage guard owns that); hand-classifying every site in M0 (scope). |
| D7 | `SEAM_INDEX` holds the Captain's named list; every `agent_stop.SEAM_*` value must be a key; long runs are pinned by absence. | An index that only documents (it could drift). |
| D8 | N1: `CrewRecoveryTransientError` at the owner door's stop sites only. | (c) a new retry transition or blocked reason in the authorizer (a persisted retry policy: the Captain's call, D44); a new persisted "stopped" reason (schema and downgrade); a park-until-lift wake-up from the stop service to the crew owner (Temporal's activity pause; new coupling, and it is S2's ticket revocation in #1601 M4). |
| D9 | The first-run door is unchanged and its reachability is pinned (P1). | Editing `_finalize_claimed` (unreachable in production; it would need its own retry semantics). |
| D10 | What retries is the session's own durable step, by its owner; nothing refused is replayed; `S1_SCOPE` and `LIFT_NOTE` say so (P2). | Leaving the Captain-facing text as S1 wrote it (it would be false). |
| D11 | F-177: `CorrectionAdmittedNotExecuted(AgentStopped)` in `crew_verifier.py`; the owner door keeps `ValueError` for it (P3). | Letting it replay (a false `correction_execution_defect`); a release-permit transition (D34, a shared owned-steps contract); an attribute set on the `AgentStopped` instance (a hidden contract). |
| D12 | F-178 measured: one verifier judgment of round 0 per attempt while a producer is stopped, bounded by `crew_recovery_max_retries + 1` per owner run (4 by default); accepted. | Refusing at round 0 for a stopped producer (it would block a stopped producer's accepted work). |
| D13 | Each attempt refused while stopped is counted at `agentic_run` (X12 pins 3). | Not counting retries (the lift's counts would understate what the ship refused). |
| D14 | The owner holds its parent-concurrency slot through the backoff (at most the sum of the backoffs, 35 s with defaults); recorded. | A slot release during backoff (a scheduler change outside this slice). |
| D15 | The S1 tracker entries stay as written; the new DECISIONS section and PROGRESS entry supersede them. `S1_SCOPE` and `LIFT_NOTE`, served to the Captain, are corrected. | Rewriting the S1 history lines (the audit trail). |
| D16 | The crossing rig uses one `CrewSessionService`, wired for the Captain's retry. | A second service over the same stores (`register_owned_steps_component` binds the store's single owner, `crew_session.py:2367-2370`; a second registration raises `owned_steps_owner_already_bound`). |
| D17 | HIGH tier; the review is whole-candidate (a public raise type changes: `CrewSessionFinalizer.resume` and `converge_for_session`). | A delta review. |
| D18 | The two codes are values of the existing free-text `last_error_code`; an older build reading one during backoff only retries. | A new field or enum (schema). |

## Needs the Captain

Nothing. Every decision is inside the Delegated AD Execution envelope: no persisted schema, authority, gate or audit control changes, and N1's placement is the Architect's under D44's last sentence. The Captain-facing `S1_SCOPE` and `LIFT_NOTE` change to stay true; the Captain can overrule D8 (automatic continuation inside the backoff window) afterwards.

---

## Acceptance Criteria

1. M0: R1 to R5 pass; S1's 19 inventory tests pass with their bodies byte-identical; the report prints; the three scripts pass on the staged tree.
2. N1: X10, X10c, X10d, X11, X12 to X14 (4 collected in the new file), T35 and the goldens pass; the consumer set passes; R6 and R7 pass.
3. With no order issued, every changed path behaves as before (X10 golden, X11 golden, X10b, X7 to X9).
4. The mutation table is executed as the campaign of record (base tree and each file's sha256 recorded); a survivor is recorded with its reason.
5. Trackers updated as Section N1.7 says; the S1 entries untouched.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Process notes.** Commit this contract alone before staging any build file (the gate preflight runs the phantom-API precheck on staged `prompts/*.md`; reword anything it flags). Stage new and edited files by explicit path before running the architecture, seam and store-registry scripts. Hard stops: an R1 difference this contract did not predict (see M0 focused check); X12's counts differing from the table (judge, synth, refused, sleeps): report the measured values, do not edit the expectations to match; any S1 golden failing.

---

## Prior Art and Blind Spots

Date used: 2026-10-20 (the orchestrator's date; the environment clock reads 2026-10-19). Internal research: no study in `docs/research/` covers stop, pause or admission (search for kill switch, admission gate, emergency stop, pause and resume: none). The decisions it builds on are S1's D19, D29 to D44 and #1601's M0 and M3 text.

- **Temporal activity pause** ([Activity operations](https://docs.temporal.io/activity-operations), [Retry policies](https://docs.temporal.io/encyclopedia/retry-policies), [Non-retryable errors](https://docs.temporal.io/design-patterns/non-retryable-errors)): pausing an activity stops new retries and unpausing reschedules them with the attempt count preserved; non-retryable errors are reserved for failures where a retry is futile. **Adapted:** a stop is a retryable condition, not an integrity failure (D8), which is Temporal's line between the two. **Rejected for now:** pause semantics (no retry budget spent while stopped, wake on lift), because it couples the stop service to the crew owner; it is the natural shape of S2's ticket revocation in #1601 M4. Its warning that a mass unpause floods downstream services does not apply: N1 wakes nothing on a lift.
- **ArchUnit frozen rules** ([Flink architecture tests](https://apache.googlesource.com/flink/+/master/flink-architecture-tests)): a store of known violations, keyed by a fixed description, fails only on new ones. **Absorbed:** stable keys that carry no line number (as AD-1270b's baseline). **Adapted:** the registry fails in both directions (a stale row fails too), as `scripts/check_architecture_principles.py` does. **Rejected:** a "refreeze" switch that rewrites the store; a registry change is a reviewed diff.
- **Google ADK `before_agent_callback`** ([Types of callbacks](https://adk.dev/callbacks/types-of-callbacks/)): one callback at the agent's entry can skip the run. It is the single-gate shape #1601 targets; M0 is the interim census until then. Nothing to absorb now. Overdue row (never reviewed in 194 days, 180-day interval), updated in N1.7.
- **OpenAI Agents SDK guardrails** ([guardrail reference](https://openai.github.io/openai-agents-python/ref/guardrail/)): a tripwire raises an exception the application must map, as `AgentStopped` is raised and mapped by each caller (D19). Nothing new. Overdue row (never reviewed), updated in N1.7.
- Considered, deferred (overdue in `reference-projects.md`, not relevant to a stop or a seam census): SWE-agent, Cursor, OpenCode, AG-UI.

Blind spots, each decided:
1. A stop longer than the backoff window (35 s by default) still ends blocked; the Captain's retry is the path (X12). Accepted (D8).
2. The Captain can retry while the order still stands; the session backs off and exhausts again. Harmless; not guarded.
3. A restart during backoff: the cancellation checkpoint keeps `retry_count`; the next start's attempt meets the stop and backs off again. No new state.
4. A stop issued between a synthesis claim and the model call: unchanged (X10b, admitted work).
5. Producer-stop retries spend one round-0 judgment each (D12) and count a refusal each (D13).
6. M0 cannot see a call through an alias, `getattr` or a stored reference; the sinks still refuse those, and #1601 M3's gate is the structural answer.
7. Sub-agents or harness sessions outside `src/probos` (AD-1342) are outside the census by construction.

---

## Verified Against Codebase (2026-10-20)

Tree: detached worktree at `9388bfda79cd372a40a89c53caa5da21036ad6e6`. Read with the Read and Grep tools unless a command is shown.

```
grep -n "synthesis_producer_unavailable|child_producer_unavailable|active_stop|_fail(" src/probos/cognitive/crew_finalizer.py
  26:  from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, AgentStopService, active_stop
  1659: raise ValueError("child_producer_unavailable")                       (producer not live: unchanged)
  1692: except AgentStopped as exc:  # A3 (R2): the producer was stopped before its correction; nothing is recorded
  1693: raise ValueError("child_producer_unavailable") from exc
  2011: if facilitator is None or active_stop(self._agent_stops, session.facilitator_id, SEAM_AGENTIC_RUN) is not None:
  2015: raise ValueError("synthesis_producer_unavailable")
  2036: except AgentStopped as exc:  # A3 (R1), A4: a session with no owned steps, ...
  2037: raise ValueError("synthesis_producer_unavailable") from exc
  2737-2744, 2909-2916: first-run door, except AgentStopped -> self._fail(... blocked=True)
crew_finalizer.py:27   from probos.cognitive.crew_session import CrewSynthesisMetadata
crew_finalizer.py:47-55 from probos.cognitive.crew_verifier import ( SessionConvergenceOutcome, ... )
crew_finalizer.py:1102-1125 finalize(): a recovery record hands off to self.resume(parent_key)
crew_finalizer.py:1208  return await self._finalize_claimed(parent_key, claimed, results)
crew_finalizer.py:1210-1258 resume(): executing -> verifying (phase verifying_children), then _resume_checkpoints
crew_finalizer.py:1315-1320 phase children_verified is checkpointed before _resume_synthesis
crew_finalizer.py:2024  admission = await self._claim_owned_synthesis(session)
crew_finalizer.py:2034  admitted_synthesis=admission is not None
crew_finalizer.py:725-740 register_owned(self, ...); bind_corrections(self._sessions)   (the verifier's port is the service)
crew_finalizer.py:2617  async def _finalize_claimed(
crew_finalizer.py:4016-4058 _fail(): blocked -> transition_session(... "blocked_needs_captain", blocked_reason=reason)

crew_orchestrator.py:589-590  task = asyncio.create_task(self._run_owned_parent(parent_id), ...)
crew_orchestrator.py:638-647  _run_owned_parent: ... or self._crew_session_service is None -> return await self.run_crew_task(parent_id); else _run_recovery_loop
crew_orchestrator.py:788-789  if recovery is None or recovery.plan is None: recovery = await self._establish_recovery_plan(...)
crew_orchestrator.py:886-908  executing -> finalizer.resume; verifying -> finalizer.resume (except ValueError only for legacy_verification_nonreconstructable)
crew_orchestrator.py:1107-1166 _run_recovery_loop: transient = self._as_recovery_transient(exc) ... continue; else _contain_recovery_failure
crew_orchestrator.py:1264-1267 _as_recovery_transient: isinstance(exc, CrewRecoveryTransientError)
crew_orchestrator.py:1305     wrapped = CrewRecoveryTransientError(code)          (in CrewOrchestrator._translate_recovery_boundary_error)
crew_orchestrator.py:1328-1391 _checkpoint_transient_failure: retry_count >= max -> "recovery_retry_exhausted"; else backoff min(initial*2**(n-1), max), sleep
crew_orchestrator.py:1416-1437 _contain_recovery_failure: ValueError -> blocked_needs_captain / recovery_integrity_conflict, "no implicit retry"
crew_orchestrator.py:1445-1472 _transition_recovery_terminal keeps retry_count, sets last_error_code=code
crew_orchestrator.py:294-313  CrewOrchestrator.__init__(..., crew_session_finalizer=None, crew_session_service=None, ..., clock=time.time, sleep=asyncio.sleep)
crew_orchestrator.py:3523     async def run_crew_task(self, parent_id: str) -> SynthesisResult:
crew_orchestrator.py:3578     finalized = await self._crew_session_finalizer.finalize(

crew_session.py:169    _RECOVERY_ERROR_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")
crew_session.py:172-179 _VERIFYING_RECOVERY_PHASES = {verifying_children, children_verified, synthesized, final_verified, artifact_bound, provenance_bound}
crew_session.py:423-430 class CrewRecoveryTransientError(RuntimeError): __init__(self, code) ... self.code = code
crew_session.py:2322-2337 CrewSessionService.__init__(*, work_item_store, chat_thread_store, registry, ontology, trust_network, config, compute_similarity, decomposer, admission_port, worker_resolver, require_worker_eligibility, clock)
crew_session.py:2367-2370 register_owned_steps_component binds the store's owner when it does not match
crew_session.py:3251    def captain_principal(self) -> CrewSessionPrincipal:
crew_session.py:3268    def bind_scheduler(
crew_session.py:3529-3542 open_or_resume(*, principal, goal, success_criteria, expected_deliverable, facilitator_id, owner_ids, requested_thread_id, retry_blocked, value_band, stakes)
crew_session.py:4830-4839 _validate_live_crew_id: registry.get + is_crew_agent(agent, ontology)
crew_session.py:4920-4921 equal goal fingerprint -> equivalent, no similarity scorer
crew_session.py:5252-5315 _authorize_blocked_retry: recovery_retry_exhausted valid when previous == verifying and phase in _VERIFYING_RECOVERY_PHASES and retry_count == self._config.crew_recovery_max_retries
config_models/agentic.py:1312 crew_recovery_max_retries: int = Field(default=3, ge=0, le=10)
startup/finalize.py:2002, 2048  cfg = getattr(config, "agentic_dispatch", None); CrewSessionService(config=cfg)   (the same config as the owner's)
startup/finalize.py:2150-2174   crew_session_service in the mandatory list -> RuntimeError("crew_orchestrator_dependency_missing:...")

crew_verifier.py:58     from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, active_stop, standing_stop
crew_verifier.py:155-158 return tuple(validated) / blank / blank / _MISSING_VERDICT_FIELD = object()
crew_verifier.py:1959-1963 converge_for_session docstring (A3 text)
crew_verifier.py:2021-2023 stopped = active_stop(... current.agent_id, SEAM_AGENTIC_RUN); raise AgentStopped(stopped)   (before admission)
crew_verifier.py:2072-2096 deterministic review_attempt_id; admitted = await self._owned_steps_port.admit_correction(...)
crew_verifier.py:2107-2131 replayed admission with no stored correction -> correction_execution_defect
crew_verifier.py:2164-2174 except AgentStopped: WARNING "admitted but not executed" when correction_permit is not None; raise

agent_stop.py:75-101   S1_SCOPE (refuses lines 81-86; does_not_end line 93 "a promoted turn the Captain approves while the agent is stopped resumes, with its tool "; not_covered line 97)
agent_stop.py:103-106  LIFT_NOTE
agent_stop.py:310-320  class AgentStopped(RuntimeError): __init__(self, record) ... self.record = record

tests/test_ad1343_stop_seam_inventory.py:25 from __future__ import annotations; :48-150 tables; :153-249 _Call, _Visitor, _census, _function, _calls, _first_line; :252 def test_census_premise_reads_this_checkout
tests/test_ad1343_stop_crossing_resume.py:28-29, :113-116, :198-206, :228, :244, :248-249, :267-271 (the SEARCH anchors above)
tests/test_ad1343_agent_stop_verify.py:44 import line; :518-522 T35
tests/test_ad1343_agent_stop_crew.py:93 class _CountingLLM; :454-461 race test, raised.value is entry.raised
tests/test_ad1343_stop_crossing_finalizer.py:146-147 _finalize -> rig.finalizer.finalize(...)   (first-run door)
tests/test_ad1244_verdict_criteria.py:530-567 _ExecutedSession and _executed_session (copied in _retryable_session)
tests/test_ad1125_room_bound_execution.py:69 class _Clock; :376-430 _session_parent; :433 _child; :458 _crew_executor
tests/test_ad1126_verified_finalization.py:201-209 _Agent(agent_type="builder"); :940-951 _registry_for (facilitator, reviewer)
tests/test_ad1127_crew_session_lifecycle_recovery.py:4531-4566 SystemConfig agentic_dispatch overrides and CrewOrchestrator(..., clock=, sleep=)
tests/test_ad1128_crew_session_ingress_dedup.py:3323-3333 open_or_resume(principal=service.captain_principal(), ..., retry_blocked=True) -> state previous, scheduled True

Structural seam sites (grep -n "\.handle_intent\(" and the agent-work names, src/probos):
  activation/dispatcher.py:203 (Dispatcher.dispatch, 70-233)      agents/system_qa.py:328 (SystemQAAgent.run_smoke_tests, 236-)
  cognitive/communication_benchmarks.py:218 (_send_chain_probe, 183-235)   cognitive/qualification_tests.py:58 (_send_probe, 43-72)
  cognitive/sandbox.py:122 (SandboxRunner.test_agent, 57-161)     experience/commands/commands_diagnostic.py:65 (cmd_diagnostic, 39-)
  experience/commands/commands_knowledge.py:148 (cmd_scout, 132-)  proactive.py:1312, 1324 (ProactiveCognitiveLoop._think_for_agent, 1241-1712)
  routers/agents.py:560 (propose_agent_voice_profile, 534-580), :656 (propose_agent_appearance, 593-698), :3640 (_agent_chat_impl, 2941-3860; DM check at :2964)
  cognitive/dm/reply_pipeline.py:853 (DmReplyPipeline.step_4_self_check_parse, 827-873; full chain only at routers/agents.py:3773)
  cognitive/counselor.py:880 (CounselorAgent._mediate_appearance_revision, 806-926)
  cognitive/turn_promotion.py:2922, 2933 (module function resume_promoted_turn, 2881-2975)
  excluded by the rule: self./super() calls (utility agents, cognitive_agent.py:2230), bare resume_promoted_turn(...) at capability_gap_driver.py:327 and promoted_turn_recovery.py:178, store/organ/optimizer receivers
```

## Absence Verified (2026-10-20)

```
A1 CLAIM: the first-run door has no production caller
   RUN:   Grep "\.finalize\(|_finalize_claimed\(" src/probos ; Grep "run_crew_task\(" src/probos
   FOUND: crew_orchestrator.py:3578 (.finalize, in run_crew_task); crew_finalizer.py:1147, 1208 (inside finalize); run_crew_task called only at crew_orchestrator.py:646
   HOLDS: yes, with startup/finalize.py:2150-2174 (service mandatory)
A2 CLAIM: CrewRecoveryTransientError is built in one place today
   RUN:   Grep "CrewRecoveryTransientError\(" src/probos
   FOUND: crew_orchestrator.py:1305 (and the class at crew_session.py:423)
   HOLDS: yes
A3 CLAIM: "cannot yet be retried" appears outside prompts/ only in S1_SCOPE; no test pins S1_SCOPE or LIFT_NOTE text
   RUN:   Grep "cannot yet be retried|not yet retryable|cannot be retried after the lift" (glob !prompts/**); Grep "S1_SCOPE|LIFT_NOTE" tests
   FOUND: agent_stop.py:84 only; tests compare to the constants (test_ad1343_agent_stop.py:672, 677, 691, 770, 800, 801)
   HOLDS: yes
A4 CLAIM: LongRunService starts no agent work
   RUN:   Grep "handle_intent|WorkItemAgenticExecutor|\.run\(|\.invoke\(|\.complete\(|\.decide\(|\.act\(" src/probos/execution/long_runs.py
   FOUND: nothing (only "class LongRunService" at :183 for the first pattern set)
   HOLDS: yes
A5 CLAIM: handle_consultation_request, interpret_recall and interpret_own_dream have no direct call site outside cognitive_agent.py
   RUN:   Grep "interpret_recall|interpret_own_dream|handle_consultation_request" src/probos (glob !**/cognitive_agent.py)
   FOUND: routers/agent_stop.py:73 (a getattr identity check, not a call)
   HOLDS: yes
A6 CLAIM: no agent-receiver calls of report/consult/perceive/decide/act exist today
   RUN:   Grep "agent\.(report|consult|perceive|decide|act|interpret_recall|interpret_own_dream)\(" src/probos
   FOUND: nothing
   HOLDS: yes
A7 CLAIM: no repository doc outside generated reports describes the S1 retry limit
   RUN:   Grep "blocked for the Captain|api/stops|AD-1343" docs
   FOUND: docs/development/open-ads-report.md, docs/development/ad-ledger-snapshot.json (generated)
   HOLDS: yes
A8 CLAIM: the Captain-facing tests do not pin the agent-stop seam catalog in docs/development/seams
   RUN:   Grep "agent_stop|stop_seam|AD-1343" docs/development/seams
   FOUND: nothing
   HOLDS: yes
```
