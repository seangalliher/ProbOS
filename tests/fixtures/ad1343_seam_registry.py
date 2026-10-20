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
