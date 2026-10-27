"""AD-1270 (#1324): Night Orders triggers name only events something emits (M1).

The trigger rule (``watch_rotation.night_order_trigger``), the inert-trigger
disclosure in Night Orders status, and the console's report of it.
"""
from __future__ import annotations

import ast
import logging
import math
import tokenize
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

import probos
from probos.config import TRUST_FLOOR_CONN
from probos.events import EventType
from probos.experience.commands import commands_autonomous
from probos.runtime import ProbOSRuntime
from probos.watch_rotation import (
    NIGHT_ORDER_TEMPLATES,
    NIGHT_ORDER_TRIGGER_EVENTS,
    WIRED_NIGHT_ORDER_TRIGGERS,
    NightOrdersManager,
    night_order_trigger,
)

_SRC = Path(probos.__file__).resolve().parent
_F = TRUST_FLOOR_CONN
_INERT = {"red_alert", "security_alert"}
_LOGGER = "probos.watch_rotation"


def _trigger(event_type: str, details: dict[str, Any] | None) -> str | None:
    return night_order_trigger(event_type, details, trust_floor=_F)


def _source(*parts: str) -> str:
    return _SRC.joinpath(*parts).read_text(encoding="utf-8")


# AD-1270 A3 (review B round 2, F1 and F2): T2 finds producers by parsing, not by matching text.
_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})


def _old_producer_calls(source: str) -> list[tuple[int, str]]:
    """Return ``(line, name)`` for each call in ``source`` that would produce an inert trigger today.

    Flagged: a call whose callee (a name or an attribute) is ``set_alert_condition``; and a call whose
    callee, with leading underscores stripped, starts with ``emit_event`` and whose first positional
    argument is a string literal equal to an old event name. Keywords are never read (AD-1270 A4,
    review B r3 G1): every ``emit_event*`` method in ``src/probos`` but ``_emit_event_local`` takes the
    event as its first parameter, and the forwarders' keywords are payload. Comments, docstrings and
    longer names never count.

    Only a source whose text contains ``set_alert_condition``, or ``emit_event`` and an old name whole,
    is parsed. In a parsed source the parser joins adjacent literals and decodes escapes, so those are
    found; a name split or escaped that way, or a callee Python normalises (NFKC) to ``emit_event`` or
    ``set_alert_condition``, is found only when the text also passes that filter. Not resolved
    (register R11 on #1324): an event passed by keyword, an emitter under another name, a call through
    ``getattr``, and a name held in a variable or written as an f-string. A source the filter admits
    that does not parse raises ``SyntaxError``: the guard fails on a file it cannot read instead of
    passing it.
    """
    emits_old = "emit_event" in source and any(name in source for name in _OLD_EVENT_NAMES)
    if not emits_old and "set_alert_condition" not in source:
        return []  # neither form can be present, so the source is not parsed
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if callee == "set_alert_condition":
            hits.append((node.lineno, callee))
        if not callee.lstrip("_").startswith("emit_event"):
            continue
        # AD-1270 A4 (review B r3 G1): the event is the first positional argument; a keyword is payload or R11 (g).
        for arg in node.args[:1]:
            if isinstance(arg, ast.Constant) and arg.value in _OLD_EVENT_NAMES:
                hits.append((node.lineno, arg.value))
    return sorted(hits)


def _scan_tree(root: Path) -> dict[str, list[tuple[int, str]]]:
    """T2's scan: ``{path relative to root: hits}`` for each ``*.py`` file under ``root`` with a hit.

    AD-1270 A4 (review B r3 G2): a file is decoded as the importer decodes it (``tokenize.open`` honours
    a UTF-8 BOM and a PEP 263 coding line), so a valid module never fails the scan by its encoding.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    for path in root.rglob("*.py"):
        with tokenize.open(path) as handle:
            hits = _old_producer_calls(handle.read())
        if hits:
            found[path.relative_to(root).as_posix()] = hits
    return found


# --- T1, T2: the map names producers, and only producers ---------------------


def test_every_mapped_event_has_a_production_producer() -> None:
    assert set(NIGHT_ORDER_TRIGGER_EVENTS) == {"build_failure", "trust_update"}
    assert EventType("build_failure") is EventType.BUILD_FAILURE
    assert EventType("trust_update") is EventType.TRUST_UPDATE
    assert "emit_event(EventType.BUILD_FAILURE, {" in _source("routers", "build.py")
    trust = _source("consensus", "trust.py")
    assert 'emissions.append(("trust_update", {' in trust
    assert '"new_score": new_score,' in trust


def test_the_inert_triggers_still_have_no_producer() -> None:
    """If this fails, a producer exists now: map it in NIGHT_ORDER_TRIGGER_EVENTS."""
    values = {m.value for m in EventType}
    assert values.isdisjoint(_OLD_EVENT_NAMES)
    # AD-1270 A3, A4: calls found by parsing (_old_producer_calls over _scan_tree); blind spots are R11 on #1324.
    assert _scan_tree(_SRC) == {}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('rt.emit_event("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event ("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(\n    "red_alert",\n    {},\n)\n', [(1, "red_alert")]),
        ('emit_event("trust_change", {})\n', [(1, "trust_change")]),
        ('self._emit_event_fn("alert_condition_change", {})\n', [(1, "alert_condition_change")]),
        ('log(rt.emit_event("security_alert", {}))\n', [(1, "security_alert")]),
        ('log(rt.emit_event("security_alert", {}))\nrt.emit_event("red_alert", {})\n',
         [(1, "security_alert"), (2, "red_alert")]),
        ('x = "security_alert"\nrt.emit_event("red_" "alert", {})\n', [(2, "red_alert")]),
        ('svc.set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        ('svc.set_alert_condition ("RED")\n', [(1, "set_alert_condition")]),
        ('set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
    ],
    ids=["positional", "space-before-paren", "split-lines", "bare-name", "suffixed-callee", "nested", "two-calls",
         "split-literal-admitted", "set-alert", "set-alert-space", "set-alert-bare"],
)
def test_old_producer_calls_flags_a_literal_producer(source: str, expected: list[tuple[int, str]]) -> None:
    """AD-1270 A3, A4: a direct call naming an old event as its first positional argument is found."""
    assert _old_producer_calls(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        '# e.g. rt.emit_event("red_alert", {})\nx = 1\n',
        '"""Page with rt.emit_event("red_alert", {}) or svc.set_alert_condition("RED")."""\n',
        'rt.emit_event("red_alert_resolved", {})\n',
        'rt.emit_event("trust_change_summary", {})\n',
        'rt.emit_event("build_failure", {})\nrt.publish("red_alert", {})\n',
        'rt.emit_event("build_failure", "red_alert")\n',
        'rt.emit_event("build_failure", data="red_alert")\n',
        'self._emit_event("build_failure", event_type="red_alert")\n',
        'self._emit_event(name="build_failure", event_type="red_alert")\n',
        'def set_alert_condition(self, condition):\n    pass\n',
        'rt.emit_event("build_failure", {}\n',
        'def (:\n',
    ],
    ids=["comment", "docstring", "longer-name", "longer-name-trust", "other-callee", "second-positional",
         "other-keyword", "payload-event-type", "payload-keyword-bound", "definition-only",
         "unparsable-without-old-name", "unparsable-unrelated"],
)
def test_old_producer_calls_ignores_what_is_not_a_producer(source: str) -> None:
    """AD-1270 A3 (review B r2 F2): text that only mentions a producer, or names a longer event, is not one."""
    assert _old_producer_calls(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'fire = rt.emit_event\nfire("red_alert", {})\n',
        'getattr(rt, "emit_event")("red_alert", {})\n',
        'name = "red_alert"\nrt.emit_event(name, {})\n',
        'rt.emit_event(f"red_alert", {})\n',
        'rt.emit_event("red_" "alert", {})\n',
        'rt._emit_event(event_type="trust_change", data={})\n',
        'rt.emit_event(event="security_alert")\n',
        'self._emit_event(name="alert_condition_change", payload={})\n',
        'rt.\uff45mit_event("red_alert", {})\n',
    ],
    ids=["alias", "getattr", "variable", "f-string", "split-literal", "event-type-kw", "event-kw", "name-kw",
         "normalised-callee"],
)
def test_old_producer_calls_does_not_resolve_these_forms(source: str) -> None:
    """Register R11 on #1324: forms the guard does not resolve; split-literal and normalised-callee only because
    the filter skips the file. If one starts to match, update R11 and DECISIONS."""
    assert _old_producer_calls(source) == []


def test_a_source_the_guard_cannot_parse_fails_it() -> None:
    """AD-1270 A3: a file that may hold a producer and does not parse fails T2 instead of being skipped."""
    with pytest.raises(SyntaxError):
        _old_producer_calls('rt.emit_event("red_alert", {}\n')


def test_the_tree_scan_decodes_each_file_as_the_importer_does(tmp_path: Path) -> None:
    """AD-1270 A4 (review B r3 G2, G5): T2's own scan reads a BOM file and a PEP 263 file as Python does."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "bom_markers.py").write_bytes(b'\xef\xbb\xbfMARKERS = ("emit_event", "red_alert")\n')
    (tmp_path / "latin1.py").write_bytes(b"# -*- coding: latin-1 -*-\nLABEL = '\xe9'\n")
    (tmp_path / "pkg" / "bom_producer.py").write_bytes(b'\xef\xbb\xbfrt.emit_event("red_alert", {})\n')
    assert _scan_tree(tmp_path) == {"pkg/bom_producer.py": [(1, "red_alert")]}


def test_every_template_trigger_is_wired_or_known_inert() -> None:
    names = {t for tpl in NIGHT_ORDER_TEMPLATES.values() for t in tpl["escalation_triggers"]}
    assert WIRED_NIGHT_ORDER_TRIGGERS == {"build_failure", "trust_drop"}
    assert names - WIRED_NIGHT_ORDER_TRIGGERS == _INERT


# --- T3: the rule --------------------------------------------------------------


@pytest.mark.parametrize(
    ("details", "expected"),
    [
        (None, "build_failure"),
        ({}, "build_failure"),
        ({"not_executed": True}, None),
        ({"not_executed": False}, "build_failure"),
        ({"not_executed": "true"}, "build_failure"),
        ({"not_executed": 1}, "build_failure"),
    ],
    ids=["none", "absent", "refused", "false", "string-true", "int-one"],
)
def test_build_failure_raises_unless_the_request_ran_nothing(details: Any, expected: str | None) -> None:
    assert _trigger("build_failure", details) == expected


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (_F + 0.1, _F - 0.1, "trust_drop"),
        (_F, _F - 0.01, "trust_drop"),
        (_F - 0.01, _F - 0.1, None),
        (_F + 0.1, _F, None),
        (_F - 0.1, _F + 0.1, None),
        (_F - 0.1, _F - 0.1, None),
        (math.inf, _F - 0.1, None),
        (_F + 0.1, math.nan, None),
        (True, False, None),
        ("0.7", "0.5", None),
        (None, _F - 0.1, None),
        # AD-1270 A2 (B5): a valid old score beside an invalid new one that the comparison alone would accept
        (_F + 0.1, False, None),
        (_F + 0.1, -math.inf, None),
        # AD-1270 A2 (B4): a finite integer too large for a float is still a score
        (10**400, _F - 0.1, "trust_drop"),
    ],
    ids=["crosses", "from-floor", "already-below", "lands-on-floor", "rises", "floor-hit",
         "inf", "nan", "bool", "str", "missing", "new-bool", "new-neg-inf", "huge-int"],
)
def test_trust_update_raises_trust_drop_once_as_it_crosses_the_floor(old: Any, new: Any, expected: str | None) -> None:
    assert _trigger("trust_update", {"agent_id": "a1", "old_score": old, "new_score": new}) == expected


@pytest.mark.parametrize("event_type", ["trust_change", "alert_condition_change", "security_alert", "bridge_alert"])
def test_events_the_old_map_keyed_raise_nothing(event_type: str) -> None:
    assert _trigger(event_type, {"new_trust": 0.0, "new_level": "red", "old_score": 0.9, "new_score": 0.1}) is None


# --- T4: status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "inert"),
    [("maintenance", ["security_alert"]), ("build", ["security_alert"]), ("quiet", ["red_alert", "security_alert"])],
)
def test_status_names_the_triggers_that_can_never_fire(template: str, inert: list[str]) -> None:
    mgr = NightOrdersManager()
    mgr.set_night_orders(instructions=[], template=template)
    assert mgr.get_status()["inert_triggers"] == inert


def test_a_custom_trigger_with_no_producer_is_reported_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop", "typo"])
    status = mgr.get_status()
    assert status["escalation_triggers"] == ["build_failure", "trust_drop", "typo"]
    assert status["inert_triggers"] == ["typo"]
    assert any("never page the Captain" in r.getMessage() and "typo" in r.getMessage() for r in caplog.records)


def test_wired_triggers_report_nothing_inert_and_log_nothing(caplog: pytest.LogCaptureFixture) -> None:
    mgr = NightOrdersManager()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        mgr.set_night_orders(instructions=[], escalation_triggers=["build_failure", "trust_drop"])
    assert mgr.get_status()["inert_triggers"] == []
    assert not [r for r in caplog.records if "never page the Captain" in r.getMessage()]


def test_inactive_status_is_unchanged() -> None:
    assert NightOrdersManager().get_status() == {"active": False}


# --- T5: the console ---------------------------------------------------------------


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=False, width=200)


def _out(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


def _runtime() -> Any:
    rt = MagicMock(spec=ProbOSRuntime)
    rt.conn_manager = None
    rt._night_orders_mgr = NightOrdersManager()
    return rt


@pytest.mark.asyncio
async def test_the_console_says_which_triggers_never_fire() -> None:
    rt = _runtime()
    set_console = _console()
    await commands_autonomous.cmd_night_orders(rt, set_console, "quiet")
    assert "Never fires on this build: red_alert, security_alert" in _out(set_console)
    status_console = _console()
    await commands_autonomous.cmd_night_orders(rt, status_console, "status")
    text = _out(status_console)
    assert "Escalates on: red_alert, security_alert" in text
    assert "Never fires on this build: red_alert, security_alert" in text


@pytest.mark.asyncio
async def test_a_fully_wired_order_prints_no_inert_line() -> None:
    rt = _runtime()
    rt._night_orders_mgr.set_night_orders([], escalation_triggers=["build_failure"])
    console = _console()
    await commands_autonomous.cmd_night_orders(rt, console, "status")
    text = _out(console)
    assert "Escalates on: build_failure" in text
    assert "Never fires" not in text


@pytest.mark.parametrize("template", ["maintenance", "build", "quiet"])
@pytest.mark.asyncio
async def test_a_template_order_that_is_already_expired_does_not_break_the_console(template: str) -> None:
    """AD-1270 A2 (B1): the console accepts a TTL that has already run out, so the status is exactly
    ``{"active": False}``; the console must not index ``inert_triggers`` on it. A negative TTL, not 0:
    a TTL of 0 may still be active at the clock's resolution."""
    rt = _runtime()
    console = _console()
    await commands_autonomous.cmd_night_orders(rt, console, f"{template} -1")
    assert rt._night_orders_mgr.orders is not None
    assert rt._night_orders_mgr.get_status() == {"active": False}
    assert "Never fires" not in _out(console)
