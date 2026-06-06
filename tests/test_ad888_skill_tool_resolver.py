"""AD-888 — Skill → Tool resolver (Skills & Tools Unification epic part 4).

Verifies `resolve_tools_for_skill` against a real `ToolRegistry` and real
`SkillDefinition`/`ToolPreference` objects (BF-287 discipline — no MagicMock at the
substrate boundary). A minimal `_FakeTool` satisfies the `Tool` protocol; the
registry, skill, and preferences are all genuine.
"""

from __future__ import annotations

from typing import Any

from probos.skill_framework import SkillCategory, SkillDefinition
from probos.tools.protocol import ToolPreference, ToolType
from probos.tools.registry import ToolRegistry
from probos.tools.skill_tool_resolver import resolve_tools_for_skill


class _FakeTool:
    """Minimal Tool-protocol implementation for registry registration."""

    def __init__(self, tool_id: str, name: str = "") -> None:
        self._tool_id = tool_id
        self._name = name or tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"fake tool {self._tool_id}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None):  # pragma: no cover - never invoked by resolver
        raise NotImplementedError


def _skill(
    *,
    skill_id: str = "tactical_debug",
    domain: str = "*",
    preferred: list[ToolPreference] | None = None,
) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        name=skill_id.replace("_", " ").title(),
        category=SkillCategory.ACQUIRED,
        description="test skill",
        domain=domain,
        preferred_tools=preferred or [],
    )


def test_preferred_tool_returned_first_by_priority() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("hi_priority"))
    registry.register(_FakeTool("lo_priority"))
    skill = _skill(
        preferred=[
            ToolPreference(tool_id="lo_priority", priority=5),
            ToolPreference(tool_id="hi_priority", priority=1),
        ],
    )

    result = resolve_tools_for_skill(skill, agent_id="ensign-1", tool_registry=registry)

    assert [r.tool_id for r in result] == ["hi_priority", "lo_priority"]


def test_permission_denied_preferred_tool_skipped() -> None:
    registry = ToolRegistry()
    # Restricted to a different agent → resolve_permission returns NONE for us.
    registry.register(_FakeTool("locked_tool"), restricted_to=["other-agent"])
    registry.register(_FakeTool("open_tool"))
    skill = _skill(
        preferred=[
            ToolPreference(tool_id="locked_tool", priority=1),
            ToolPreference(tool_id="open_tool", priority=2),
        ],
    )

    result = resolve_tools_for_skill(skill, agent_id="ensign-1", tool_registry=registry)

    assert [r.tool_id for r in result] == ["open_tool"]


def test_tag_fallback_when_no_preferred_tool() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("diag_tool"), tags=["engineering"])
    registry.register(_FakeTool("unrelated_tool"), tags=["medical"])
    # No preferred tools; the skill's domain is the discovery tag.
    skill = _skill(domain="engineering", preferred=[])

    result = resolve_tools_for_skill(skill, agent_id="ensign-1", tool_registry=registry)

    assert [r.tool_id for r in result] == ["diag_tool"]


def test_tag_fallback_respects_permission() -> None:
    registry = ToolRegistry()
    registry.register(
        _FakeTool("restricted_diag"), tags=["engineering"], restricted_to=["other-agent"]
    )
    skill = _skill(domain="engineering", preferred=[])

    result = resolve_tools_for_skill(skill, agent_id="ensign-1", tool_registry=registry)

    assert result == []


def test_hebbian_param_is_documented_noop() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("a_tool"))
    registry.register(_FakeTool("b_tool"))
    skill = _skill(
        preferred=[
            ToolPreference(tool_id="b_tool", priority=2),
            ToolPreference(tool_id="a_tool", priority=1),
        ],
    )

    sentinel = object()  # any non-None hebbian must not alter ordering
    with_hebbian = resolve_tools_for_skill(
        skill, agent_id="ensign-1", tool_registry=registry, hebbian=sentinel  # type: ignore[arg-type]
    )
    without_hebbian = resolve_tools_for_skill(
        skill, agent_id="ensign-1", tool_registry=registry, hebbian=None
    )

    assert [r.tool_id for r in with_hebbian] == [r.tool_id for r in without_hebbian]
    assert [r.tool_id for r in with_hebbian] == ["a_tool", "b_tool"]


def test_empty_result_is_clean_list_never_raises() -> None:
    registry = ToolRegistry()
    # Preferred tool that does not exist + universal domain → no fallback tag.
    skill = _skill(
        domain="*",
        preferred=[ToolPreference(tool_id="ghost_tool", priority=1)],
    )

    result = resolve_tools_for_skill(skill, agent_id="ensign-1", tool_registry=registry)

    assert result == []
