"""AD-1195 (#1132) M3: the EventLog write sites are frozen, so a new pair is a reviewed change.

An AST census of every ``.log(...)`` call, and every call of a forwarding
wrapper, under ``src/probos``. A ``.log(...)`` call is an EventLog write unless
its receiver is a known non-EventLog receiver (``math`` or a Python logger), or
it is the ``*args, **kwargs`` call inside a wrapper, whose callers count
instead. Nothing else excludes it: the router writes positionally through
``self._sink``, which a ``category=`` or ``event_log`` filter would miss.
``category`` and ``event`` are the keyword, else the first two positionals
(after the event log, for a wrapper call).

Each resolves from a string literal, ``EventType.X[.value]``, a module-level
name bound exactly once in its module to a string literal, or both arms of a
conditional expression. Frozen:
the 37 literal pairs, the resolved pairs, and the dynamic sites keyed by (file,
enclosing function, unparsed category, unparsed event). A call the census
cannot classify fails. Not seen: a write through an alias of the method or
through ``getattr``.
"""

from __future__ import annotations

import ast
import functools
import itertools
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.event_persistence import OWNER_RECORDS
from probos.events import EventType
from probos.substrate.durable_events import ROUTED_VALUES

_PACKAGE = Path(probos.__file__).resolve().parent
_ROOT = _PACKAGE.parents[1]
_NOT_EVENT_LOG_RECEIVERS = frozenset({
    "math", "logging", "logger", "_logger", "LOGGER", "self.logger", "self._logger",
})
_WRAPPERS = frozenset({"_safe_log_event"})
"""Functions that forward ``*args, **kwargs`` to ``EventLog.log``; callers pass the log first."""

# DRIFT-1: the contract's 37 literal pairs (section 1.4).
_LITERAL_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ('audit', 'event_log_query'),
    ('cognitive', 'feedback_hebbian_update'),
    ('cognitive', 'feedback_plan_rejected'),
    ('cognitive', 'feedback_trust_update'),
    ('cognitive', 'proposal_approved'),
    ('cognitive', 'proposal_created'),
    ('cognitive', 'proposal_node_removed'),
    ('cognitive', 'proposal_rejected'),
    ('consensus', 'device_actuate_blocked'),
    ('consensus', 'mcp_invoke_blocked'),
    ('consensus', 'quorum_evaluated'),
    ('consensus', 'verification_complete'),
    ('consensus', 'write_blocked'),
    ('dependency', 'dependency_check'),
    ('dependency', 'dependency_install_approved'),
    ('dependency', 'dependency_install_declined'),
    ('dependency', 'dependency_install_failed'),
    ('dependency', 'dependency_install_success'),
    ('self_mod', 'dependency_check'),
    ('self_mod', 'dependency_install_approved'),
    ('self_mod', 'dependency_install_declined'),
    ('self_mod', 'dependency_install_failed'),
    ('self_mod', 'dependency_install_success'),
    ('lifecycle', 'agent_wired'),
    ('medical', 'remediation'),
    ('mesh', 'intent_broadcast'),
    ('mesh', 'intent_resolved'),
    ('naming', 'agent_self_named'),
    ('pipeline', 'pipeline_duplicate_post_suppressed'),
    ('qa', 'agent_flagged'),
    ('qa', 'agent_removed'),
    ('qa', 'qa_error'),
    ('qa', 'smoke_test_started'),
    ('system', 'pool_created'),
    ('system', 'started'),
    ('system', 'stopped'),
    ('system', 'stopping'),
})

# DRIFT-2: the pairs that resolve through a constant, EventType member or conditional arm.
_RESOLVED_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ('backup', 'backup_complete'),
    ('backup', 'backup_failed'),
    ('consensus', 'device_actuate_committed'),
    ('consensus', 'device_actuate_failed'),
    ('consensus', 'mcp_invoke_committed'),
    ('consensus', 'mcp_invoke_failed'),
    ('consensus', 'write_committed'),
    ('consensus', 'write_failed'),
    ('tool', 'tool_invoked'),
    ('tool', 'tool_record_budget_exhausted'),
    ('tool', 'tool_started'),
})

# DRIFT-3: sites whose category or event is not statically a string.
_DYNAMIC_SITES: frozenset[tuple[str, str, str, str]] = frozenset({
    ('src/probos/agents/system_qa.py', 'SystemQAAgent.run_smoke_tests', "'qa'", 'event'),
    ('src/probos/cognitive/feedback.py', 'FeedbackEngine.apply_correction_feedback', "'cognitive'", 'event_name'),
    ('src/probos/cognitive/feedback.py', 'FeedbackEngine.apply_execution_feedback', "'cognitive'", 'event_name'),
    ('src/probos/credential_store.py', 'CredentialStore._log_access', "'credential'", "f'access:{name}'"),
    ('src/probos/dream_adapter.py', 'DreamAdapter._event_log_emergent', "'emergent'", 'pattern.pattern_type'),
    ('src/probos/substrate/durable_events.py', 'DurableEventRouter._write', 'ROUTED_CATEGORY', 'record.event'),
    ('src/probos/substrate/durable_events.py', 'DurableEventRouter._write_marker', 'ROUTED_CATEGORY', 'DROP_MARKER_EVENT'),
    ('src/probos/ward_room_router.py', 'WardRoomRouter.deliver_bridge_alert', "'bridge_alert'", 'alert.alert_type'),
})


# ── the census ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Site:
    where: str
    file: str
    function: str
    category: str
    event: str
    pairs: frozenset[tuple[str, str]]
    literal: bool


@dataclass(frozen=True)
class _Census:
    sites: tuple[_Site, ...]
    forwarding: tuple[str, ...]
    unclassifiable: tuple[str, ...]
    skipped: tuple[str, ...]

    def literal_pairs(self) -> dict[tuple[str, str], str]:
        return self._pairs(literal=True)

    def resolved_pairs(self) -> dict[tuple[str, str], str]:
        return self._pairs(literal=False)

    def dynamic_sites(self) -> dict[tuple[str, str, str, str], str]:
        found: dict[tuple[str, str, str, str], str] = {}
        for site in self.sites:
            if not site.pairs:
                found.setdefault((site.file, site.function, site.category, site.event), site.where)
        return found

    def _pairs(self, *, literal: bool) -> dict[tuple[str, str], str]:
        found: dict[tuple[str, str], str] = {}
        for site in self.sites:
            if site.pairs and site.literal is literal:
                for pair in sorted(site.pairs):
                    found.setdefault(pair, site.where)
        return found


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _unpacks(call: ast.Call) -> bool:
    return any(isinstance(arg, ast.Starred) for arg in call.args) or any(
        keyword.arg is None for keyword in call.keywords
    )


def _event_type_member(node: ast.AST) -> EventType | None:
    if isinstance(node, ast.Attribute) and node.attr == "value":
        node = node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "EventType":
        return EventType.__members__.get(node.attr)
    return None


def _bound_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.append(node.id)
        elif isinstance(node, ast.arg):
            names.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.alias):
            names.append((node.asname or node.name).split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.extend(node.names)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.append(node.rest)
    return names


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound exactly once in the module, to a string literal."""
    bindings = _bound_names(tree)
    constants: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and _is_str(value) and bindings.count(target.id) == 1:
            constants[target.id] = value.value  # type: ignore[attr-defined]
    return constants


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str, constants: Mapping[str, str]) -> None:
        self._rel = rel
        self._constants = constants
        self._scope: list[str] = []
        self._functions: list[str] = []
        self.sites: list[_Site] = []
        self.forwarding: list[str] = []
        self.unclassifiable: list[str] = []
        self.skipped: list[str] = []

    def _enter(self, node: ast.AST, name: str, *, function: bool) -> None:
        self._scope.append(name)
        if function:
            self._functions.append(name)
        self.generic_visit(node)
        if function:
            self._functions.pop()
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name, function=False)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name, function=True)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._enter(node, "<lambda>", function=True)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if isinstance(func, ast.Attribute) and name == "log":
            self._log_call(node, func)
        elif name in _WRAPPERS:
            self._record(node, node.args[1:])
        self.generic_visit(node)

    def _qualname(self) -> str:
        return ".".join(self._scope) or "<module>"

    def _log_call(self, node: ast.Call, func: ast.Attribute) -> None:
        receiver = ast.unparse(func.value)
        if receiver in _NOT_EVENT_LOG_RECEIVERS:
            self.skipped.append(receiver)
        elif self._functions and self._functions[-1] in _WRAPPERS and _unpacks(node):
            self.forwarding.append(f"{self._rel}:{self._qualname()}")
        else:
            self._record(node, node.args)

    def _record(self, node: ast.Call, args: Sequence[ast.expr]) -> None:
        where = f"{self._rel}:{node.lineno}"
        if _unpacks(node):
            self.unclassifiable.append(f"{where} in {self._qualname()}: unpacked arguments")
            return
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        category = keywords.get("category", args[0] if args else None)
        event = keywords.get("event", args[1] if len(args) > 1 else None)
        if category is None or event is None:
            self.unclassifiable.append(f"{where} in {self._qualname()}: no category or event argument")
            return
        categories, events = self._resolve(category), self._resolve(event)
        pairs = frozenset(itertools.product(categories, events)) if categories and events else frozenset()
        self.sites.append(_Site(
            where, self._rel, self._qualname(), ast.unparse(category), ast.unparse(event),
            pairs, _is_str(category) and _is_str(event),
        ))

    def _resolve(self, node: ast.AST) -> frozenset[str]:
        if _is_str(node):
            return frozenset({node.value})  # type: ignore[attr-defined]
        if isinstance(node, ast.IfExp):
            body, orelse = self._resolve(node.body), self._resolve(node.orelse)
            return body | orelse if body and orelse else frozenset()
        if isinstance(node, ast.Name) and node.id in self._constants:
            return frozenset({self._constants[node.id]})
        member = _event_type_member(node)
        return frozenset({member.value}) if member is not None else frozenset()


def _census_of(sources: Mapping[str, str | bytes]) -> _Census:
    sites: list[_Site] = []
    forwarding: list[str] = []
    unclassifiable: list[str] = []
    skipped: list[str] = []
    for rel in sorted(sources):
        tree = ast.parse(sources[rel], filename=rel)
        visitor = _Visitor(rel, _module_constants(tree))
        visitor.visit(tree)
        sites += visitor.sites
        forwarding += visitor.forwarding
        unclassifiable += visitor.unclassifiable
        skipped += visitor.skipped
    return _Census(tuple(sites), tuple(forwarding), tuple(unclassifiable), tuple(skipped))


@functools.lru_cache(maxsize=1)
def _tree_census() -> _Census:
    return _census_of({
        path.relative_to(_ROOT).as_posix(): path.read_bytes() for path in sorted(_PACKAGE.rglob("*.py"))
    })


def _drift(table: str, found: Mapping[Any, str], frozen: Set[Any]) -> list[str]:
    """Both directions of the difference between the census and a frozen table, with a remedy each."""
    added = [
        f"{table}: {item!r} is written at {found[item]} but not frozen; decide its persistence "
        f"(AD-1195, probos/event_persistence.py), then add it to {table}"
        for item in sorted(set(found) - set(frozen))
    ]
    removed = [
        f"{table}: {item!r} is frozen but no longer written; remove it from {table}"
        for item in sorted(set(frozen) - set(found))
    ]
    return added + removed


def _fail_on(problems: list[str]) -> None:
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)


def _contract_problems(
    census: _Census, owner_records: Mapping[str, tuple[str, str]], routed_values: Set[str],
) -> list[str]:
    written = {**census.resolved_pairs(), **census.literal_pairs()}
    problems = [
        f"OWNER_RECORDS[{name!r}] = {pair!r} is written by no census site"
        for name, pair in sorted(owner_records.items())
        if pair not in written
    ]
    problems += [
        f"routed value {pair[1]!r} is also the event of {pair!r} at {where}; "
        "an owner already writes it, so declare it in OWNER_RECORDS"
        for pair, where in sorted(written.items())
        if pair[1] in routed_values
    ]
    return problems


# ── the tree ─────────────────────────────────────────────────────────────────

_ROUTER = "src/probos/substrate/durable_events.py"
_ROUTER_SITES = {
    (_ROUTER, "DurableEventRouter._write", "ROUTED_CATEGORY", "record.event"),
    (_ROUTER, "DurableEventRouter._write_marker", "ROUTED_CATEGORY", "DROP_MARKER_EVENT"),
}


def test_census_premise_reads_this_checkout_and_sees_known_calls() -> None:
    """Premise for DRIFT-1..3: the census scans this checkout and sees writes and non-writes."""
    assert (_ROOT / "src" / "probos" / "events.py").resolve() == (_PACKAGE / "events.py").resolve()
    census = _tree_census()
    stopped = [
        site for site in census.sites
        if site.file == "src/probos/startup/shutdown.py" and ("system", "stopped") in site.pairs
    ]
    assert stopped, "the shutdown ('system', 'stopped') write was not seen"
    assert "src/probos/cognitive/feedback.py:FeedbackEngine._safe_log_event" in census.forwarding
    assert {"math", "logger"} <= set(census.skipped)
    router = {(s.file, s.function, s.category, s.event) for s in census.sites if s.file == _ROUTER}
    assert router == _ROUTER_SITES


def test_literal_pairs_are_exactly_the_contract_37() -> None:
    """DRIFT-1: the literal (category, event) pairs are the contract's 37."""
    _fail_on(_drift("_LITERAL_PAIRS", _tree_census().literal_pairs(), _LITERAL_PAIRS))
    assert len(_LITERAL_PAIRS) == 37


def test_resolved_pairs_are_frozen() -> None:
    """DRIFT-2: every pair reached through a constant, member or conditional arm is frozen."""
    _fail_on(_drift("_RESOLVED_PAIRS", _tree_census().resolved_pairs(), _RESOLVED_PAIRS))


def test_every_dynamic_site_is_allowlisted_and_nothing_is_unclassifiable() -> None:
    """DRIFT-3: dynamic sites are allowlisted (the router's two included); no call is unclassifiable."""
    census = _tree_census()
    problems = _drift("_DYNAMIC_SITES", census.dynamic_sites(), _DYNAMIC_SITES)
    problems += [
        f"unclassifiable: {item}; pass category and event as arguments, or add the receiver "
        "to _NOT_EVENT_LOG_RECEIVERS if it is not an EventLog"
        for item in census.unclassifiable
    ]
    _fail_on(problems)
    assert _ROUTER_SITES <= _DYNAMIC_SITES


# ── the census discriminates ─────────────────────────────────────────────────

_SYNTHETIC = "src/probos/_synthetic_drift.py"


def _one_function(body: str) -> _Census:
    return _census_of({_SYNTHETIC: "async def write(event_log, sink):\n" + body})


def test_census_reports_an_added_removed_or_renamed_pair_and_a_positional_call() -> None:
    """DRIFT-4: each change to a literal pair is reported, in both directions."""
    base = _one_function('    await event_log.log(category="system", event="started")\n')
    frozen = frozenset(base.literal_pairs())
    assert frozen == {("system", "started")}
    assert _drift("T", base.literal_pairs(), frozen) == []

    added = _one_function(
        '    await event_log.log(category="system", event="started")\n'
        '    await event_log.log(category="system", event="added")\n'
    )
    problems = _drift("T", added.literal_pairs(), frozen)
    assert len(problems) == 1 and "('system', 'added')" in problems[0] and "not frozen" in problems[0]

    removed = _one_function("    pass\n")
    problems = _drift("T", removed.literal_pairs(), frozen)
    assert len(problems) == 1 and "('system', 'started')" in problems[0] and "no longer written" in problems[0]

    renamed = _one_function('    await event_log.log(category="system", event="restarted")\n')
    problems = _drift("T", renamed.literal_pairs(), frozen)
    assert len(problems) == 2
    assert "('system', 'restarted')" in problems[0] and "('system', 'started')" in problems[1]

    positional = _one_function(
        '    await event_log.log(category="system", event="started")\n'
        '    await sink.log("system", "positional")\n'
    )
    problems = _drift("T", positional.literal_pairs(), frozen)
    assert len(problems) == 1 and "('system', 'positional')" in problems[0]
    assert f"{_SYNTHETIC}:3" in problems[0]


def test_census_resolves_only_static_strings_and_flags_what_it_cannot_classify() -> None:
    """DRIFT-4: resolution, dynamic keys, unpacked calls, forwarding and skipped receivers."""
    census = _census_of({_SYNTHETIC: (
        "import math\n"
        "from probos.events import EventType\n"
        "from elsewhere import IMPORTED\n"
        'CATEGORY = "tool"\n'
        'TWICE = "a"\n'
        'TWICE = "b"\n'
        "\n"
        "class Engine:\n"
        "    def _safe_log_event(self, event_log, *args, **kwargs):\n"
        "        event_log.log(*args, **kwargs)\n"
        "\n"
        "    async def write(self, event_log, ok, e, args):\n"
        '        self._safe_log_event(event_log, category="cognitive", event="wrapped")\n'
        '        await event_log.log(category=CATEGORY, event="started" if ok else "failed")\n'
        '        await event_log.log(category="security", event=EventType.THREAT_DETECTED.value)\n'
        '        await event_log.log(category="security", event=EventType.EGRESS_BLOCKED)\n'
        '        await event_log.log(category=TWICE, event="x")\n'
        "        await event_log.log(category=IMPORTED, event=e)\n"
        "        await event_log.log(*args)\n"
        '        await event_log.log(category="system")\n'
        "        math.log(2)\n"
    )})
    assert set(census.literal_pairs()) == {("cognitive", "wrapped")}
    assert set(census.resolved_pairs()) == {
        ("tool", "started"), ("tool", "failed"),
        ("security", "threat_detected"), ("security", "egress_blocked"),
    }
    assert set(census.dynamic_sites()) == {
        (_SYNTHETIC, "Engine.write", "TWICE", "'x'"),
        (_SYNTHETIC, "Engine.write", "IMPORTED", "e"),
    }
    assert census.forwarding == (f"{_SYNTHETIC}:Engine._safe_log_event",)
    assert [item.split(": ", 1)[1] for item in census.unclassifiable] == [
        "unpacked arguments", "no category or event argument",
    ]
    assert census.skipped == ("math",)


# ── DRIFT-5 ──────────────────────────────────────────────────────────────────


def test_owner_pairs_are_written_and_no_routed_value_is_a_written_event() -> None:
    """DRIFT-5: every owner pair has a writer, and the router never duplicates an owner's row."""
    assert _contract_problems(_tree_census(), OWNER_RECORDS, ROUTED_VALUES) == []
    assert len(OWNER_RECORDS) == 8 and len(ROUTED_VALUES) == 28


def test_contract_problems_report_an_unwritten_owner_and_a_routed_collision() -> None:
    """DRIFT-5 discriminates: an owner pair nobody writes, and a routed value an owner writes."""
    census = _one_function('    await event_log.log(category="security", event="threat_detected")\n')
    problems = _contract_problems(
        census, {"CONSENSUS": ("consensus", "quorum_evaluated")}, frozenset({"threat_detected"}),
    )
    assert len(problems) == 2
    assert "CONSENSUS" in problems[0] and "written by no census site" in problems[0]
    assert "'threat_detected'" in problems[1] and f"{_SYNTHETIC}:2" in problems[1]
