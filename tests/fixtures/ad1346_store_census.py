"""AD-1346 M3e4a (#1604): the census of #1604 property 1's store-write class: its SQL write statements.

``sql_write_scan`` parses one module and reports each SQL write statement in it: a ``str`` constant that is not a
docstring, or an f-string read with each placeholder as ``_``, whose text ``SQL_WRITE`` matches at its start after
leading whitespace. A point is (enclosing scope, line), scoped as the egress scan scopes one. ``sql_write_files`` runs
the scan over every ``src`` module. ``STORE_WRITE_SCOPES`` (AD-1346 M3e4b, D229) gives each (file, enclosing scope)
that holds a point in the Ward Room's ``messages.py`` and ``threads.py`` and in ``cognitive/episodic.py`` a
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
    "src/probos/assignment.py": ("AssignmentService.create_assignment", "created_by"),
    "src/probos/capability_request.py": ("CapabilityRequestStore.file_request", "agent_id"),
    "src/probos/cognitive/clinical_notes_store.py": ("ClinicalNotesStore.write_note", "author_agent_id"),
    "src/probos/persistent_tasks.py": ("PersistentTaskStore.create_task", "created_by"),
    "src/probos/skill_request.py": ("SkillRequestStore.file_request", "agent_id"),
    "src/probos/threads/__init__.py": ("ChatThreadStore.append_message_once", "author_id"),
    "src/probos/ward_room/channels.py": ("ChannelManager.create_channel", "created_by"),
    "src/probos/workforce.py": ("WorkItemStore._insert_work_item", "item.created_by"),
}

#: AD-1346 M3e4a (D220, D221): each other ``src`` file that holds a SQL write statement -> its coverage (AD-1346 M3e4b,
#: D229: the files of ``STORE_WRITE_SCOPES`` are not rows here).
STORE_WRITE_FILES: Final[dict[str, Pending | System | OutsideRuntime]] = {
    # Agent-attributed (AD-1346 M3e4c, D239, D240): M3e4d's (register R113).
    "src/probos/artifacts/__init__.py": _AGENT_ATTRIBUTED,
    "src/probos/assignment.py": _AGENT_ATTRIBUTED,
    "src/probos/capability_request.py": _AGENT_ATTRIBUTED,
    "src/probos/cognitive/clinical_notes_store.py": _AGENT_ATTRIBUTED,
    "src/probos/persistent_tasks.py": _AGENT_ATTRIBUTED,
    "src/probos/skill_request.py": _AGENT_ATTRIBUTED,
    "src/probos/threads/__init__.py": _AGENT_ATTRIBUTED,
    "src/probos/ward_room/channels.py": _AGENT_ATTRIBUTED,
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

#: AD-1346 M3e4b (D229): each (file, enclosing scope) of these three files that holds a SQL write statement -> its coverage.
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
}


def store_write_check_functions() -> set[tuple[str, str]]:
    """AD-1346 M3e4b: (file, function) of each store-write check."""
    return {cover.check for cover in STORE_WRITE_SCOPES.values() if isinstance(cover, StoreCheck)}
