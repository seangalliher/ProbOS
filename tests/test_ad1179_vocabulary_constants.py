"""AD-1179: each schema vocabulary is named once, ordered, and read by its gate.

Nine ``enum`` vocabularies appear in a tool ``input_schema``. Two were already
derived from a named constant (``browser.action`` from ``_AGENT_ACTIONS``,
``oracle.kind`` from ``SIGMA_TIERS``); the other seven were hand-written
literals sitting beside their own executable gates.

These tests assert the two properties that make the pattern load-bearing:

1. **The schema reads the constant** — so a value the agent is offered is a value
   the gate accepts, by construction rather than by review.
2. **The constant is ORDERED** — never a ``set``. Python string hashing is
   randomised per process, so ``list(a_set)`` yields a different order on every
   boot and the wire bytes an LLM receives would vary run to run. This is a real
   trap here: ``search_capabilities._SPECIFIC_KINDS`` *was* a set literal, and
   deriving its enum from it directly would have shipped exactly that.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import (
    _STANDING_ORDERS_SCOPES,
    StandingOrdersLookupTool,
)
from probos.config import BrowserToolConfig
from probos.knowledge.records_store import _CLASSIFICATION_LEVELS
from probos.tools.browser.actions import (
    _MOUSE_BUTTONS,
    _MOUSE_PRESSES,
    _SCROLL_DIRECTIONS,
)
from probos.tools.browser.tool import _AGENT_ACTIONS, BrowserTool
from probos.tools.event_log_query_tool import (
    _AGGREGATIONS,
    _ORDERS,
    EventLogQueryTool,
)
from probos.tools.oracle_query_tool import SIGMA_TIERS, OracleQueryTool
from probos.tools.publish_finding_tool import _CLASSIFICATIONS, PublishFindingTool
from probos.tools.search_capabilities_tool import (
    _KINDS,
    _SPECIFIC_KINDS,
    SearchCapabilitiesTool,
)


def _browser_props() -> dict[str, Any]:
    return BrowserTool(config=BrowserToolConfig(enabled=True)).input_schema["properties"]


def _event_log_props() -> dict[str, Any]:
    tool = EventLogQueryTool(reader=None, audit_sink=None)
    return tool.input_schema["properties"]


# ── the schema reads the constant ─────────────────────────────────


def test_browser_action_still_reads_agent_actions() -> None:
    """BF-701's fix, untouched by this slice."""
    assert _browser_props()["action"]["enum"] == list(_AGENT_ACTIONS)


def test_browser_button_reads_the_mouse_button_constant() -> None:
    assert _browser_props()["button"]["enum"] == list(_MOUSE_BUTTONS)


def test_browser_press_reads_the_mouse_press_constant() -> None:
    assert _browser_props()["press"]["enum"] == list(_MOUSE_PRESSES)


def test_browser_direction_reads_the_scroll_direction_constant() -> None:
    assert _browser_props()["direction"]["enum"] == list(_SCROLL_DIRECTIONS)


def test_standing_orders_scope_reads_the_scope_constant() -> None:
    schema = StandingOrdersLookupTool.input_schema
    assert schema["properties"]["scope"]["enum"] == list(_STANDING_ORDERS_SCOPES)


def test_event_log_order_reads_the_orders_constant() -> None:
    assert _event_log_props()["order"]["enum"] == list(_ORDERS)


def test_event_log_aggregate_reads_the_aggregations_constant() -> None:
    assert _event_log_props()["aggregate"]["enum"] == list(_AGGREGATIONS)


def test_search_capabilities_kind_reads_the_kinds_constant() -> None:
    tool = SearchCapabilitiesTool(runtime=None)
    assert tool.input_schema["properties"]["kind"]["enum"] == list(_KINDS)


def test_publish_finding_classification_reads_the_classifications_constant() -> None:
    tool = PublishFindingTool(records_store=None, callsign_resolver=None)
    schema = tool.input_schema["properties"]["classification"]
    assert schema["enum"] == list(_CLASSIFICATIONS)


def test_oracle_kind_still_reads_sigma_tiers() -> None:
    """Already derived before this slice; the reference pattern, unchanged."""
    tool = OracleQueryTool(oracle=None)
    assert tool.input_schema["properties"]["kind"]["enum"] == [*SIGMA_TIERS, "all"]


# ── the gate reads the same constant ──────────────────────────────


@pytest.mark.asyncio
async def test_standing_orders_gate_and_error_string_come_from_the_constant() -> None:
    """Four restatements collapsed to one: schema, description, gate, refusal."""
    tool = StandingOrdersLookupTool(runtime=None)
    result = await tool.invoke({"scope": "fleet"})
    assert result.error == "scope must be one of " + "|".join(_STANDING_ORDERS_SCOPES)
    assert "/".join(_STANDING_ORDERS_SCOPES) in StandingOrdersLookupTool.description
    for scope in _STANDING_ORDERS_SCOPES:
        assert scope in StandingOrdersLookupTool.description


def test_event_log_both_aggregate_gates_read_one_constant() -> None:
    """``aggregate`` is gated in two places — ``_parse_query`` (the executable
    admission) and ``_raw_audit_details`` (what the audit row records). Both had
    their own tuple literal; a disagreement would audit a value the query
    refused, or the reverse."""
    from probos.tools import event_log_query_tool as mod

    for name in ("_parse_query", "_raw_audit_details"):
        import inspect

        source = inspect.getsource(getattr(mod, name))
        assert "_AGGREGATIONS" in source, f"{name} does not read _AGGREGATIONS"
        assert '"cooperation_signature",' not in source, (
            f"{name} still carries a hand-typed aggregate tuple"
        )


def test_search_capabilities_membership_set_derives_from_the_ordered_kinds() -> None:
    """The ``_AGENT_ACTIONS`` / ``_AGENT_ACTION_SET`` shape: the ordered tuple is
    the schema's source, the frozenset is membership only."""
    assert _SPECIFIC_KINDS == frozenset(_KINDS) - {"all"}
    assert "all" not in _SPECIFIC_KINDS


def test_publish_finding_classifications_are_the_records_store_authority() -> None:
    """The module comment claims the vocabulary is 'imported rather than
    re-typed so the two cannot drift'. That was true of the validator and false
    of the schema; this pins the claim to both."""
    assert _CLASSIFICATIONS == tuple(_CLASSIFICATION_LEVELS)


# ── the ordered-tuple rule ────────────────────────────────────────


_VOCABULARY_CONSTANTS: tuple[tuple[str, Any], ...] = (
    ("_AGENT_ACTIONS", _AGENT_ACTIONS),
    ("_MOUSE_BUTTONS", _MOUSE_BUTTONS),
    ("_MOUSE_PRESSES", _MOUSE_PRESSES),
    ("_SCROLL_DIRECTIONS", _SCROLL_DIRECTIONS),
    ("_STANDING_ORDERS_SCOPES", _STANDING_ORDERS_SCOPES),
    ("_ORDERS", _ORDERS),
    ("_AGGREGATIONS", _AGGREGATIONS),
    ("_KINDS", _KINDS),
    ("_CLASSIFICATIONS", _CLASSIFICATIONS),
    ("SIGMA_TIERS", SIGMA_TIERS),
)


@pytest.mark.parametrize("name,constant", _VOCABULARY_CONSTANTS)
def test_every_vocabulary_constant_is_an_ordered_tuple(name: str, constant: Any) -> None:
    """Not a set. A set-derived enum reorders on every boot, so the definition
    an LLM receives would differ run to run and the golden fixture could never
    be stable."""
    assert isinstance(constant, tuple), f"{name} is {type(constant).__name__}"
    assert not isinstance(constant, (set, frozenset))
    assert all(isinstance(value, str) for value in constant), name
    assert len(set(constant)) == len(constant), f"{name} has duplicates"


def test_the_constant_roster_covers_every_derived_enum() -> None:
    """Premise assertion: the roster above must not silently shrink."""
    assert len(_VOCABULARY_CONSTANTS) == 10
    assert len({name for name, _ in _VOCABULARY_CONSTANTS}) == 10
