"""BF-690: the browser offer must advertise exactly the actions the guard permits.

AD-1153 armed a read-only guard inside ``DispatchToolExecutor.invoke`` but left
the *offer* untouched. The agent was shown all eleven actions — and told, in the
tool's own description, to "click/type by index" — then refused five of them by a
rule it had never been given. That costs a loop iteration and makes the offer a
lie; AD-1158 sharpens it further by letting an agent act on a session the Captain
is watching.

These tests pin the invariant in one direction only: **everything advertised is
permitted**. The reverse is deliberately not asserted — the intersection is
fail-safe, so a permitted action the tool does not declare is silently dropped
rather than advertised.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    _BROWSER_LOOP_ACTIONS,
    _BROWSER_READ_ONLY_REFUSAL,
    _browser_read_only_description,
    _narrow_browser_offer,
    WorkItemAgenticExecutor,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    tool_registration_to_llm_definition,
)
from probos.tools.browser.tool import BrowserTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.types import LLMResponse

from tests.test_ad1153_browser_agentic_loop import (
    _ALL_SIX,
    _EXCLUDED_ACTIONS,
    _agentic_runtime,
    _make_browser_tool,
    _registry_with_browser,
)


# -- Harness --------------------------------------------------------------


class _DefinitionCapturingLLM:
    """Records the full tool DEFINITIONS handed to the loop, not just the names.

    AD-1153's ``_ToolIdCapturingLLM`` keeps only ``function.name``, which is
    exactly why this bug survived that AD's test suite.
    """

    def __init__(self) -> None:
        self.definitions: list[list[dict[str, Any]]] = []

    async def complete(self, request: Any, **_kw: object) -> LLMResponse:
        self.definitions.append(list(getattr(request, "tools", None) or []))
        return LLMResponse(
            content="done", tokens_used=1, content_blocks=[TextBlock(text="done")],
        )


def _enum_of(definition: dict[str, Any]) -> list[str]:
    return definition["function"]["parameters"]["properties"]["action"]["enum"]


async def _declared() -> tuple[list[str], str]:
    """The tool's OWN advertised action enum and description, unnarrowed."""
    tool, _ = _make_browser_tool()
    try:
        return (
            list(tool.input_schema["properties"]["action"]["enum"]),
            tool.description,
        )
    finally:
        await tool.stop()


async def _offered_browser_definition(
    *,
    browser_enabled: bool = True,
    rank: str = "lieutenant",
    grant: ToolPermission | None = None,
) -> dict[str, Any] | None:
    """Run the REAL dispatch; return the ``browser`` definition it offered."""
    store = ToolPermissionStore(db_path=":memory:")
    await store.start()
    tool: BrowserTool | None = None
    try:
        if grant is not None:
            await store.issue_grant(
                "agent-a", "browser", grant,
                issued_by="captain", reason="captain escape hatch",
            )
        tool, _ = _make_browser_tool()
        registry = _registry_with_browser(tool, permission_store=store)
        llm = _DefinitionCapturingLLM()
        await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="agent-a", instructions="", task_text="go",
            runtime=_agentic_runtime(
                registry, store, browser_enabled=browser_enabled,
            ),
            department="engineering", rank=rank,
        )
        for definition in llm.definitions[0]:
            if (definition.get("function") or {}).get("name") == "browser":
                return definition
        return None
    finally:
        if tool is not None:
            await tool.stop()
        await store.stop()


def _synthetic(enum: Any) -> dict[str, Any]:
    """A minimal offer definition with an arbitrary ``action.enum`` payload."""
    return {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "original",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string", "enum": enum}},
            },
        },
    }


# -- The invariant, through the real dispatch -----------------------------


@pytest.mark.asyncio
async def test_the_restricted_offer_advertises_only_permitted_actions() -> None:
    """The BF-690 invariant: offered ⊆ permitted."""
    definition = await _offered_browser_definition()
    assert definition is not None
    assert set(_enum_of(definition)) <= _BROWSER_LOOP_ACTIONS


@pytest.mark.asyncio
async def test_the_restricted_offer_advertises_every_loop_action() -> None:
    definition = await _offered_browser_definition()
    assert definition is not None
    assert set(_enum_of(definition)) == set(_ALL_SIX)


@pytest.mark.asyncio
async def test_no_refused_action_is_advertised_to_a_restricted_agent() -> None:
    """The five the guard refuses must not appear in the offer at all."""
    definition = await _offered_browser_definition()
    assert definition is not None
    assert not set(_enum_of(definition)) & set(_EXCLUDED_ACTIONS)


@pytest.mark.asyncio
async def test_the_narrowed_enum_preserves_the_schema_declaration_order() -> None:
    declared, _ = await _declared()
    definition = await _offered_browser_definition()
    assert definition is not None
    assert _enum_of(definition) == [
        a for a in declared if a in _BROWSER_LOOP_ACTIONS
    ]


@pytest.mark.asyncio
async def test_the_restricted_description_does_not_instruct_click_or_type() -> None:
    """The shipped description ends "then click/type by index" — narrowing the
    enum alone would leave a read-only agent being told to use both."""
    definition = await _offered_browser_definition()
    assert definition is not None
    description = definition["function"]["description"]
    assert "click" not in description
    assert "type" not in description
    assert "read-only" in description


@pytest.mark.asyncio
async def test_the_restricted_description_names_the_permitted_actions() -> None:
    definition = await _offered_browser_definition()
    assert definition is not None
    description = definition["function"]["description"]
    for action in _ALL_SIX:
        assert action in description


# -- The unarmed paths stay byte-identical --------------------------------


@pytest.mark.asyncio
async def test_a_captain_grant_still_offers_the_full_action_surface() -> None:
    """DD-2's grant-UP semantics. An agent holding ``browser`` through a Captain
    grant is not restricted, so its offer must be the tool's own schema."""
    declared, description = await _declared()
    definition = await _offered_browser_definition(grant=ToolPermission.WRITE)
    assert definition is not None
    assert _enum_of(definition) == declared
    assert definition["function"]["description"] == description


@pytest.mark.asyncio
async def test_the_flag_off_path_offers_no_browser_at_all() -> None:
    assert await _offered_browser_definition(browser_enabled=False) is None


@pytest.mark.asyncio
async def test_an_ensign_is_offered_no_browser_and_so_nothing_is_narrowed() -> None:
    assert await _offered_browser_definition(rank="ensign") is None


# -- The helper in isolation ----------------------------------------------


@pytest.mark.asyncio
async def test_narrowing_leaves_the_source_definition_untouched() -> None:
    """The schema must survive intact for the AD-745 DM dispatch path."""
    tool, _ = _make_browser_tool()
    try:
        registry = _registry_with_browser(tool)
        definition = tool_registration_to_llm_definition(registry.get("browser"))
        before = copy.deepcopy(definition)
        narrowed = _narrow_browser_offer(definition, _BROWSER_LOOP_ACTIONS)
        assert definition == before
        assert narrowed is not definition
        assert _enum_of(narrowed) != _enum_of(definition)
        assert tool.input_schema["properties"]["action"]["enum"] == before[
            "function"
        ]["parameters"]["properties"]["action"]["enum"]
    finally:
        await tool.stop()


def test_an_armed_action_the_schema_does_not_declare_is_not_advertised() -> None:
    """Fail-safe intersection, the same direction as ``_BROWSER_LOOP_ACTIONS``."""
    narrowed = _narrow_browser_offer(
        _synthetic(["goto", "state"]), frozenset({"goto", "teleport"}),
    )
    assert _enum_of(narrowed) == ["goto"]


def test_an_empty_intersection_degrades_to_the_verbatim_schema_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The guard still refuses everything, so this is noisy, not unsafe."""
    definition = _synthetic(["goto", "state"])
    with caplog.at_level(logging.WARNING):
        narrowed = _narrow_browser_offer(definition, frozenset({"teleport"}))
    assert narrowed is definition
    assert "BF-690" in caplog.text
    assert "drifted apart" in caplog.text


@pytest.mark.parametrize(
    "definition",
    [
        {},
        {"function": None},
        {"function": {}},
        {"function": {"parameters": None}},
        {"function": {"parameters": {}}},
        {"function": {"parameters": {"properties": None}}},
        {"function": {"parameters": {"properties": {}}}},
        {"function": {"parameters": {"properties": {"action": None}}}},
        {"function": {"parameters": {"properties": {"action": {}}}}},
        _synthetic("not-a-list"),
        _synthetic(None),
        _synthetic({"goto": True}),
    ],
)
def test_an_unexpected_schema_shape_degrades_to_the_definition_unchanged(
    definition: dict[str, Any], caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = _narrow_browser_offer(definition, _BROWSER_LOOP_ACTIONS)
    assert result is definition
    assert "BF-690" in caplog.text


def test_the_generated_description_names_exactly_the_actions_given() -> None:
    text = _browser_read_only_description(["goto", "state"])
    assert "goto, state" in text
    assert "extract_text" not in text


# -- Drift guards ---------------------------------------------------------


def test_the_generated_description_is_clean_under_the_real_gap_regex() -> None:
    """A description that trips ``_CAPABILITY_GAP_RE`` would make the offer
    itself read as a capability gap. Note ``lack`` is a BARE substring there."""
    text = _browser_read_only_description(sorted(_BROWSER_LOOP_ACTIONS))
    match = _CAPABILITY_GAP_RE.search(text)
    assert match is None, f"tripped on {match.group(0)!r} in: {text}"


def test_the_refusal_string_still_lists_exactly_the_permitted_actions() -> None:
    """``_BROWSER_READ_ONLY_REFUSAL`` is the third hand-written copy of this
    action list. If ``_BROWSER_LOOP_ACTIONS`` is widened, this catches the
    refusal text drifting out of sync with it."""
    for action in _BROWSER_LOOP_ACTIONS:
        assert action in _BROWSER_READ_ONLY_REFUSAL
    for action in _EXCLUDED_ACTIONS:
        assert action not in _BROWSER_READ_ONLY_REFUSAL


@pytest.mark.asyncio
async def test_every_permitted_action_is_declared_by_the_tool_schema() -> None:
    """If these diverge the intersection silently shrinks the offer, so pin it."""
    declared, _ = await _declared()
    assert _BROWSER_LOOP_ACTIONS <= set(declared)
