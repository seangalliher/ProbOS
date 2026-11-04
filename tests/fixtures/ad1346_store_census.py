"""AD-1346 M3e4a (#1604): the census of #1604 property 1's store-write class: its SQL write statements.

``sql_write_scan`` parses one module and reports each SQL write statement in it: a ``str`` constant that is not a
docstring, or an f-string read with each placeholder as ``_``, whose text ``SQL_WRITE`` matches at its start after
leading whitespace. A point is (enclosing scope, line), scoped as the egress scan scopes one. ``sql_write_files`` runs
the scan over every ``src`` module. ``STORE_WRITE_SCOPES`` (AD-1346 M3e4b, D229) gives each (file, enclosing scope)
that holds a point in the Ward Room's ``messages.py`` and ``threads.py``, in ``cognitive/episodic.py`` and, from
AD-1346 M3e4d1 (D284), in ``cognitive/clinical_notes_store.py`` and ``skill_request.py`` and, from AD-1346 M3e4d2
(D291), in ``persistent_tasks.py`` and, from AD-1346 M3e4d3 (D298), in ``threads/__init__.py`` and, from AD-1346
M3e4d4 (D306), in ``assignment.py`` and, from AD-1346 M3e4d5 (D313), in ``ward_room/channels.py`` a
``StoreCheck`` or a ``System``, and ``STORE_WRITE_FILES`` gives each other file that holds a point one coverage, a
``Pending``, ``System`` or ``OutsideRuntime`` of ``tests/fixtures/ad1346_effect_census.py``. A row of
``STORE_WRITE_FILES`` is a file and carries no count (D220). ``AGENT_ATTRIBUTED_SCOPES`` (AD-1346 M3e4c, D240)
gives, for each file whose row is ``Pending("M3e4d")``, a scope whose SQL write statement records a row D239 makes
agent-attributed, and the name in that scope of the id the row records as its author, creator or requester.

Among what the scan cannot see: a statement whose text starts in a part that is not a constant (a name, a call, a
placeholder), SQL not in upper case, a string inside an f-string's placeholder, and the other store-write primitives,
among them a ChromaDB write, a file write and a JetStream publish (register R111).
``tests/test_ad1346_admission_store_census.py`` checks the rows against the code.
"""

from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass
from typing import Final

from tests.fixtures.ad1346_effect_census import SHIP, OutsideRuntime, Pending, System, src_sources

#: AD-1346 M3e4a (D219): the starts of a SQL write statement, in upper case.
SQL_WRITE_STARTS: Final = (
    r"INSERT\s+(?:OR\s+[A-Z]+\s+)?INTO",
    r"REPLACE\s+INTO",
    r"UPDATE\s+\w+\s+SET",
    r"DELETE\s+FROM",
)
#: Matched at the start of a string's text, after leading whitespace.
SQL_WRITE: Final = re.compile(r"\s*(?:" + "|".join(SQL_WRITE_STARTS) + r")(?:\s|$)")

_AGENT_ATTRIBUTED: Final = Pending("M3e4d", "agent-attributed (D239): AGENT_ATTRIBUTED_SCOPES names a scope and its author (register R113)")


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of the docstring constants of the module and of each class and function in it."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


class _SqlWriteScan(ast.NodeVisitor):
    def __init__(self, docstrings: set[int]) -> None:
        self.docstrings = docstrings
        self.scope: list[str] = []
        self.points: list[tuple[str, int]] = []

    def _enter(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def _point(self, node: ast.expr, text: str) -> None:
        if SQL_WRITE.match(text):
            self.points.append((".".join(self.scope) or "<module>", node.lineno))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docstrings:
            self._point(node, node.value)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        # The placeholders are not visited: a string inside one is not a point.
        self._point(node, "".join(part.value if isinstance(part, ast.Constant) else "_" for part in node.values))


def sql_write_scan(source: str, filename: str = "<sql>") -> list[tuple[str, int]]:
    """(scope, line) of each SQL write statement in one module's source (AD-1346 M3e4a, D219)."""
    tree = ast.parse(source, filename=filename)
    scan = _SqlWriteScan(_docstrings(tree))
    scan.visit(tree)
    return scan.points


@functools.lru_cache(maxsize=1)
def sql_write_points() -> tuple[tuple[str, str, int], ...]:
    """(file, scope, line) of each SQL write statement in ``src``."""
    return tuple((rel, *point) for rel, source in src_sources().items() for point in sql_write_scan(source, rel))


def sql_write_files() -> frozenset[str]:
    """The ``src`` files that hold a SQL write statement."""
    return frozenset(path for path, _scope, _line in sql_write_points())


#: AD-1346 M3e4c (D239, D240): each file whose row is ``Pending("M3e4d")`` -> (a scope whose SQL write statement
#: records a row D239 makes agent-attributed, the name in that scope of the id the row records as its author, creator
#: or requester).
AGENT_ATTRIBUTED_SCOPES: Final[dict[str, tuple[str, str]]] = {
    "src/probos/artifacts/__init__.py": ("ArtifactStore.add_version", "created_by"),
    "src/probos/capability_request.py": ("CapabilityRequestStore.file_request", "agent_id"),
    "src/probos/workforce.py": ("WorkItemStore._insert_work_item", "item.created_by"),
}

#: AD-1346 M3e4a (D220, D221): each other ``src`` file that holds a SQL write statement -> its coverage (AD-1346 M3e4b,
#: D229: the files of ``STORE_WRITE_SCOPES`` are not rows here).
STORE_WRITE_FILES: Final[dict[str, Pending | System | OutsideRuntime]] = {
    # Agent-attributed (AD-1346 M3e4c, D239, D240): M3e4d's (register R113).
    "src/probos/artifacts/__init__.py": _AGENT_ATTRIBUTED,
    "src/probos/capability_request.py": _AGENT_ATTRIBUTED,
    "src/probos/workforce.py": _AGENT_ATTRIBUTED,
    # System (AD-1346 M3e4c, D239): each reason names what the file records.
    "src/probos/cognitive/clinical_audit_store.py": System(SHIP, "the clinical audit log"),
    "src/probos/cognitive/counselor.py": System(SHIP, "cognitive profiles and assessments, keyed by the agent assessed (D239)"),
    "src/probos/cognitive/elastic_team_store.py": System(SHIP, "elastic team specs, worker slots, attempts and their outcomes"),
    "src/probos/cognitive/journal.py": System(SHIP, "the cognitive journal: model-call metrics, chain traces, causal templates, optimisation records"),
    "src/probos/cognitive/participant_index.py": System(SHIP, "the episode participant index"),
    "src/probos/cognitive/procedure_challenges.py": System(SHIP, "procedure challenges, comparisons and cycles"),
    "src/probos/cognitive/procedure_store.py": System(SHIP, "procedures, the agents they came from, their lineage, promotion decisions and counters (D239)"),
    "src/probos/cognitive/self_distillation/prober.py": System(SHIP, "ontology probe results, keyed by the agent probed (D239)"),
    "src/probos/cognitive/standing_interest_store.py": System(SHIP, "standing interests: a holder's kind, subject and expiry (D239)"),
    "src/probos/cognitive/workflow_cron.py": System(SHIP, "workflow cron triggers and their firing times"),
    "src/probos/cognitive/working_memory_store.py": System(SHIP, "working-memory snapshots, keyed by agent: copies (D218)"),
    "src/probos/crew_profile.py": System(SHIP, "crew profiles"),
    "src/probos/directive_store.py": System(SHIP, "directives, whose issuer is recorded as a type, not an agent id (D239)"),
    "src/probos/fault_issue_filings.py": System(SHIP, "the issue filings of fault reports"),
    "src/probos/fault_report.py": System(SHIP, "tool fault reports: a tool's error, the run it was seen in and its resolution"),
    "src/probos/holodeck/scenarios.py": System(SHIP, "scenario gap links"),
    "src/probos/holodeck/team_simulations.py": System(SHIP, "team simulation records and debriefs"),
    "src/probos/routers/scheduled_tasks.py": System(SHIP, "a scheduled task's agent hint"),
    "src/probos/task_sessions/__init__.py": System(SHIP, "task sessions and their runs"),
    # System (D221).
    "src/probos/acm.py": System(SHIP, "lifecycle and commissioning records"),
    "src/probos/admission/store.py": System(SHIP, "admission_shadow.db; the admission service's own record is not checked (D218)"),
    "src/probos/agent_stop.py": System(SHIP, "the Captain's stop orders; the stop service's own record is not checked (D218)"),
    "src/probos/approval_authority.py": System(SHIP, "approval authority records"),
    "src/probos/clearance_grants.py": System(SHIP, "clearance grants"),
    "src/probos/cognitive/activation_tracker.py": System(SHIP, "memory activation records"),
    "src/probos/cognitive/circuit_breaker_history_store.py": System(SHIP, "circuit breaker history"),
    "src/probos/cognitive/episode_archive.py": System(SHIP, "copies of episodes leaving live memory (D218)"),
    "src/probos/cognitive/eviction_audit.py": System(SHIP, "the episode eviction audit"),
    "src/probos/cognitive/intent_grants.py": System(SHIP, "intent grants"),
    "src/probos/cognitive/profile_qualification_store.py": System(SHIP, "profile qualification records"),
    "src/probos/cognitive/qualification.py": System(SHIP, "qualification records"),
    "src/probos/cognitive/repair_evidence_store.py": System(SHIP, "repair evidence"),
    "src/probos/cognitive/retrieval_practice.py": System(SHIP, "retrieval practice schedules"),
    "src/probos/cognitive/schema_versions.py": System(SHIP, "schema versions"),
    "src/probos/cognitive/skill_catalog.py": System(SHIP, "the skill catalog"),
    "src/probos/cognitive/skill_grants.py": System(SHIP, "skill grants"),
    "src/probos/consensus/trust.py": System(SHIP, "trust records"),
    "src/probos/continue_extension_permits.py": System(SHIP, "continue-extension permits"),
    "src/probos/decision_pre_clearance.py": System(SHIP, "decision pre-clearances"),
    "src/probos/economic_calibration.py": System(SHIP, "economic calibration records"),
    "src/probos/execution/authority.py": System(SHIP, "the execution authority's records"),
    "src/probos/execution/command_approvals.py": System(SHIP, "command approvals"),
    "src/probos/federation/hebbian_map.py": System(SHIP, "federation Hebbian weights"),
    "src/probos/federation_envelope_store.py": System(SHIP, "federation envelopes"),
    "src/probos/identity.py": System(SHIP, "identity records"),
    "src/probos/identity_key_binding.py": System(SHIP, "identity key bindings"),
    "src/probos/identity_transfer_marks.py": System(SHIP, "identity transfer marks"),
    "src/probos/integrations/mcp_bridge/department_grants.py": System(SHIP, "MCP department grants"),
    "src/probos/integrations/mcp_bridge/risk.py": System(SHIP, "MCP risk records"),
    "src/probos/integrations/mcp_bridge/store.py": System(SHIP, "the MCP bridge store"),
    "src/probos/knowledge/archive_ledger.py": System(SHIP, "the archive ledger"),
    "src/probos/knowledge/archive_store.py": System(SHIP, "promoted copies, with their author's provenance (D218)"),
    "src/probos/knowledge/edges.py": System(SHIP, "knowledge edges"),
    "src/probos/knowledge/rejection_cache.py": System(SHIP, "dream rejections"),
    "src/probos/knowledge/semantic_store.py": System(SHIP, "the Captain's work layer, with copied episode text (D218)"),
    "src/probos/mesh/routing.py": System(SHIP, "routing records"),
    "src/probos/perception/wm_store.py": System(SHIP, "the perception store"),
    "src/probos/security/audit.py": System(SHIP, "the audit log"),
    "src/probos/security/audit_log.py": System(SHIP, "the assistant audit log"),
    "src/probos/security/pairing/store.py": System(SHIP, "pairings"),
    "src/probos/service_profile.py": System(SHIP, "service profiles"),
    "src/probos/skill_framework.py": System(SHIP, "skill records"),
    "src/probos/substrate/event_log.py": System(SHIP, "the event log"),
    "src/probos/tools/action_approvals.py": System(SHIP, "action approvals"),
    "src/probos/tools/permissions.py": System(SHIP, "tool permissions"),
    "src/probos/tools/work_permits.py": System(SHIP, "work permits"),
    # The operator's command line (D167).
    "src/probos/__main__.py": OutsideRuntime("probos reset's eviction audit row"),
}


@dataclass(frozen=True)
class StoreCheck:
    """AD-1346 M3e4b (D229, D230): a scope whose SQL write statements the function ``check``, a (file, qualified
    name) pair, checks with ``check_at``, presenting ``presented``. ``via`` is empty when ``check`` is the scope, else
    the attribute of ``check``'s class through which ``check`` calls the scope."""

    check: tuple[str, str]
    presented: str
    via: str = ""


_WARD_ROOM: Final = "src/probos/ward_room/service.py"
_MESSAGES: Final = "src/probos/ward_room/messages.py"
_THREADS: Final = "src/probos/ward_room/threads.py"
_EPISODIC: Final = "src/probos/cognitive/episodic.py"
_NOTES: Final = "src/probos/cognitive/clinical_notes_store.py"
_SKILLS: Final = "src/probos/skill_request.py"
_TASKS: Final = "src/probos/persistent_tasks.py"
_CHATS: Final = "src/probos/threads/__init__.py"
_ASSIGNMENTS: Final = "src/probos/assignment.py"
_CHANNELS: Final = "src/probos/ward_room/channels.py"

#: AD-1346 M3e4b (D229), M3e4d1 (D284), M3e4d2 (D291), M3e4d3 (D298), M3e4d4 (D306) and M3e4d5 (D313): each (file,
#: enclosing scope) of these nine files that holds a SQL write statement -> its coverage.
STORE_WRITE_SCOPES: Final[dict[tuple[str, str], StoreCheck | System]] = {
    # Agent-attributed (D218): the Ward Room's four content-write entries and the episodic store check them (D231, D232).
    (_MESSAGES, "MessageStore.create_post"): StoreCheck((_WARD_ROOM, "WardRoomService.create_post"), "author_id", "_messages"),
    (_MESSAGES, "MessageStore.edit_post"): StoreCheck((_WARD_ROOM, "WardRoomService.edit_post"), "author_id", "_messages"),
    (_MESSAGES, "MessageStore.endorse"): StoreCheck((_WARD_ROOM, "WardRoomService.endorse"), "voter_id", "_messages"),
    (_THREADS, "ThreadManager.create_thread"): StoreCheck((_WARD_ROOM, "WardRoomService.create_thread"), "author_id", "_threads"),
    (_EPISODIC, "EpisodicMemory.store"): StoreCheck((_EPISODIC, "EpisodicMemory.store"), "_sole_agent_id(episode)"),
    # System (D218): the Ward Room's and the memory's own records about agents, and copies.
    (_MESSAGES, "MessageStore.set_restriction"): System(SHIP, "posting restrictions"),
    (_MESSAGES, "MessageStore.remove_restriction"): System(SHIP, "posting restrictions"),
    (_MESSAGES, "MessageStore._update_credibility"): System(SHIP, "the credibility an endorsement moves"),
    (_MESSAGES, "MessageStore.subscribe"): System(SHIP, "channel memberships"),
    (_MESSAGES, "MessageStore.unsubscribe"): System(SHIP, "channel memberships"),
    (_MESSAGES, "MessageStore.update_last_seen"): System(SHIP, "a member's last-seen time"),
    (_THREADS, "ThreadManager.update_thread"): System(SHIP, "thread settings: locked, pinned, mode, responder cap"),
    (_THREADS, "ThreadManager.archive_dm_messages"): System(SHIP, "DM thread archival"),
    (_THREADS, "ThreadManager.prune_old_threads"): System(SHIP, "the retention prune"),
    (_EPISODIC, "_delete_fts_rows"): System(SHIP, "keyword-index rows deleted by _erase_fts_file and _cleanup_sidecars"),
    (_EPISODIC, "EpisodicMemory._reconcile_fts_index"): System(SHIP, "the keyword index's start-up reconciliation"),
    (_EPISODIC, "EpisodicMemory.seed"): System(SHIP, "the bulk seed of warm boot and the memory probes"),
    (_EPISODIC, "EpisodicMemory._write_restore_sidecars"): System(SHIP, "an episode restore_from_archive copies back (D218)"),
    # AD-1346 M3e4d1 (D284). Agent-attributed (D239): a note's body with author_agent_id, a filing's justification with
    # agent_id and a decision's reason with decided_by; each check is its scope (D285).
    (_NOTES, "ClinicalNotesStore.write_note"): StoreCheck((_NOTES, "ClinicalNotesStore.write_note"), "author_agent_id"),
    (_SKILLS, "SkillRequestStore.file_request"): StoreCheck((_SKILLS, "SkillRequestStore.file_request"), "agent_id"),
    (_SKILLS, "SkillRequestStore.decide"): StoreCheck((_SKILLS, "SkillRequestStore.decide"), "decided_by"),
    # System (D239): a skill request's state, with no text.
    (_SKILLS, "SkillRequestStore.begin_training"): System(SHIP, "a skill request's status and linked_simulation_id"),
    (_SKILLS, "SkillRequestStore.complete_for_simulation"): System(SHIP, "a skill request's status and post_metric"),
    # AD-1346 M3e4d2 (D291). Agent-attributed (D239): a task's intent_text with created_by; the check is its scope (D292).
    (_TASKS, "PersistentTaskStore.create_task"): StoreCheck((_TASKS, "PersistentTaskStore.create_task"), "created_by"),
    # System (D239): a scheduled task's state; these statements do not write created_by.
    (_TASKS, "PersistentTaskStore.cancel_task"): System(SHIP, "a scheduled task's status and enabled"),
    (_TASKS, "PersistentTaskStore.trigger_webhook"): System(SHIP, "a scheduled task's next_run_at"),
    (_TASKS, "PersistentTaskStore._fire_task"): System(SHIP, "a scheduled task's status, last_result, last_run_at, run_count, next_run_at and enabled"),
    # AD-1346 M3e4d3 (D298). Agent-attributed (D239): a thread's title with the created_by_agent of its metadata, which
    # AgentGroupChatService.create_group_chat sets to the creating agent, and a message's body with author_id; each
    # check is its scope (D299).
    (_CHATS, "ChatThreadStore.create_thread"): StoreCheck((_CHATS, "ChatThreadStore.create_thread"), "meta.get('created_by_agent')"),
    (_CHATS, "ChatThreadStore.append_message_once"): StoreCheck((_CHATS, "ChatThreadStore.append_message_once"), "author_id"),
    # System (D239, D218): each reason names what its scope's statements write.
    (_CHATS, "ChatThreadStore.update_thread"): System(SHIP, "a thread's title, pinned, archived, personality_override, workspace_root, project_id or task_id"),
    (_CHATS, "ChatThreadStore.set_personality_override"): System(SHIP, "a thread's personality_override"),
    (_CHATS, "ChatThreadStore.set_title"): System(SHIP, "a thread's title, and with lock its metadata's title_locked"),
    (_CHATS, "ChatThreadStore.set_meeting_active"): System(SHIP, "a thread's metadata's meeting_active"),
    (_CHATS, "ChatThreadStore.set_agent_mode"): System(SHIP, "a thread's agent-mode record: mode, revision, changed_at, changed_by, previous and agent_id, no text (D239)"),
    (_CHATS, "ChatThreadStore.add_participant"): System(SHIP, "a thread's participants and last_active_at"),
    (_CHATS, "ChatThreadStore.add_crew_session_participants"): System(SHIP, "a thread's participants and last_active_at"),
    (_CHATS, "ChatThreadStore.compare_and_set_task_link"): System(SHIP, "a thread's task_id"),
    (_CHATS, "ChatThreadStore.create_crew_session_thread"): System(SHIP, "a CrewSession room built from the provisioning marker its parent work item records (D218)"),
    (_CHATS, "ChatThreadStore.delete_untouched_crew_session_thread"): System(SHIP, "the deletion of an untouched CrewSession room"),
    (_CHATS, "ChatThreadStore.remove_participant"): System(SHIP, "a thread's participants and last_active_at"),
    (_CHATS, "ChatThreadStore.delete_thread"): System(SHIP, "the deletion of a thread and its messages"),
    (_CHATS, "ChatThreadStore.purge_thread"): System(SHIP, "a tombstone of a thread's title, participants and last_active_at, and the deletion of the thread and its messages"),
    (_CHATS, "ChatThreadStore.create_default_for_agent"): System(SHIP, "an agent's default thread, whose participants are the agent"),
    (_CHATS, "ChatThreadStore.get_or_create_default_for_agent"): System(SHIP, "an agent's default thread, whose participants are the agent"),
    (_CHATS, "ChatThreadStore.get_or_create_system_thread"): System(SHIP, "a fixed-id system thread"),
    (_CHATS, "ProjectStore.create_project"): System(SHIP, "a project's name, description and pinned_attachment_ids; projects have no author column (D239)"),
    (_CHATS, "ProjectStore.update_project"): System(SHIP, "a project's name, description or archived"),
    (_CHATS, "ProjectStore.delete_project"): System(SHIP, "the deletion of a project, with its threads and their messages or with its threads' project_id"),
    (_CHATS, "ProjectStore.pin_attachment"): System(SHIP, "a project's pinned_attachment_ids"),
    (_CHATS, "ProjectStore.unpin_attachment"): System(SHIP, "a project's pinned_attachment_ids"),
    (_CHATS, "ProjectStore.touch"): System(SHIP, "a project's last_active_at"),
    # AD-1346 M3e4d4 (D306). Agent-attributed (D239): an assignment's name and mission with created_by, which the
    # assignments route passes from its request, and its member rows; the check is its scope (D307).
    (_ASSIGNMENTS, "AssignmentService.create_assignment"): StoreCheck((_ASSIGNMENTS, "AssignmentService.create_assignment"), "created_by"),
    # System (D239): a member row names the agent it is about; the other two write an assignment's status.
    (_ASSIGNMENTS, "AssignmentService.add_member"): System(SHIP, "an assignment's member row, which names the agent it is about (D239)"),
    (_ASSIGNMENTS, "AssignmentService.remove_member"): System(SHIP, "the deletion of an assignment's member row"),
    (_ASSIGNMENTS, "AssignmentService.complete_assignment"): System(SHIP, "an assignment's status and completed_at"),
    (_ASSIGNMENTS, "AssignmentService.dissolve_assignment"): System(SHIP, "an assignment's status and completed_at, when it is dissolved"),
    # AD-1346 M3e4d5 (D313). Agent-attributed (D239): a channel's name and description with created_by, and a DM
    # channel's name and description with agent_a_id as its created_by; each check is its scope (D314).
    (_CHANNELS, "ChannelManager.create_channel"): StoreCheck((_CHANNELS, "ChannelManager.create_channel"), "created_by"),
    (_CHANNELS, "ChannelManager.get_or_create_dm_channel"): StoreCheck((_CHANNELS, "ChannelManager.get_or_create_dm_channel"), "agent_a_id"),
    # System (D239): the default channels, with created_by 'system', and a channel's archived flag.
    (_CHANNELS, "ChannelManager._ensure_default_channels"): System(SHIP, "the default channels, with created_by 'system'"),
    (_CHANNELS, "ChannelManager.archive_channel"): System(SHIP, "a channel's archived flag"),
}


def store_write_check_functions() -> set[tuple[str, str]]:
    """AD-1346 M3e4b: (file, function) of each store-write check."""
    return {cover.check for cover in STORE_WRITE_SCOPES.values() if isinstance(cover, StoreCheck)}
