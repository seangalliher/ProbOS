"""AD-885: ACM consolidated profile — unified capability lens.

Extends ``ACM.get_consolidated_profile`` with two additive blocks:
  7. cognitive_skills / cognitive_skill_count  (AD-596 catalogue)
  8. tools / tool_count                         (AD-423 tool grants)

BF-287 discipline: real ``ToolRegistry`` and real ``CognitiveSkillCatalog``
fixtures at the substrate boundary — no MagicMock for the subsystems whose
attribute shape we depend on. The runtime container is a plain stub object
(``_LensRuntime``) holding real subsystems, so attribute lookups hit reality.
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers — real subsystems, plain stub runtime container
# ---------------------------------------------------------------------------


class _StubTool:
    """Minimal Tool protocol implementation for registry fixtures."""

    def __init__(
        self,
        tool_id: str,
        *,
        name: str = "Stub",
        tool_type: ToolType = ToolType.INFRA_SERVICE,
        description: str = "stub",
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        return ToolResult(output="ok")


class _CrewProfile:
    """Minimal crew profile shape consumed by block 2 of the lens."""

    class _Rank:
        def __init__(self, value: str) -> None:
            self.value = value

    class _Personality:
        openness = 0.5
        conscientiousness = 0.5
        extraversion = 0.5
        agreeableness = 0.5
        neuroticism = 0.5

    def __init__(self, *, department: str, rank: str) -> None:
        self.callsign = "Stub"
        self.display_name = "Stub Agent"
        self.department = department
        self.rank = self._Rank(rank)
        self.personality = self._Personality()


class _ProfileStore:
    def __init__(self, profile: _CrewProfile | None) -> None:
        self._profile = profile

    def get(self, agent_id: str) -> _CrewProfile | None:
        return self._profile


class _LensRuntime:
    """Plain runtime container — only the attributes the lens reads."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        cognitive_skill_catalog: Any = None,
        profile_store: _ProfileStore | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.cognitive_skill_catalog = cognitive_skill_catalog
        self.profile_store = profile_store
        # Subsystems exercised by earlier blocks are intentionally NOT defined as
        # attributes — their blocks guard with hasattr(), so omitting them keeps
        # those blocks dormant and isolates blocks 7 & 8 under test.


@pytest.fixture
async def acm(tmp_path):
    svc = AgentCapitalService(data_dir=str(tmp_path))
    await svc.start()
    yield svc
    await svc.stop()


async def _make_catalog(tmp_path, *, skill_id: str = "debug-tactics"):
    """Build and start a real CognitiveSkillCatalog with one SKILL.md entry."""
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog

    skills_dir = tmp_path / "skills" / skill_id
    skills_dir.mkdir(parents=True, exist_ok=True)
    # No metadata block → ungoverned defaults (department='*', min_rank='ensign').
    (skills_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_id}\n"
        "description: How to debug tactically\n"
        "---\n\n"
        "## Instructions\nDebug carefully.\n",
        encoding="utf-8",
    )
    catalog = CognitiveSkillCatalog(skills_dir=tmp_path / "skills", db_path=None)
    await catalog.start()
    return catalog


# ---------------------------------------------------------------------------
# Block 7: cognitive skills
# ---------------------------------------------------------------------------


class TestCognitiveSkillsBlock:
    @pytest.mark.asyncio
    async def test_cognitive_skills_present(self, acm, tmp_path):
        """Lens includes cognitive_skills + count from a real catalogue."""
        await acm.onboard("a1", "scout", "pool", "science")
        catalog = await _make_catalog(tmp_path)
        rt = _LensRuntime(cognitive_skill_catalog=catalog)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["cognitive_skill_count"] == 1
        names = {s["name"] for s in profile["cognitive_skills"]}
        assert "debug-tactics" in names
        assert all({"name", "description", "skill_id"} <= set(s) for s in profile["cognitive_skills"])

    @pytest.mark.asyncio
    async def test_cognitive_skills_absent_when_no_catalog(self, acm):
        """No catalogue → block omitted (graceful)."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = _LensRuntime(cognitive_skill_catalog=None)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert "cognitive_skills" not in profile
        assert "cognitive_skill_count" not in profile

    @pytest.mark.asyncio
    async def test_cognitive_skills_empty_catalog(self, acm, tmp_path):
        """Catalogue with no entries → empty list, count 0."""
        from probos.cognitive.skill_catalog import CognitiveSkillCatalog

        await acm.onboard("a1", "scout", "pool", "science")
        empty_dir = tmp_path / "empty_skills"
        empty_dir.mkdir()
        catalog = CognitiveSkillCatalog(skills_dir=empty_dir, db_path=None)
        await catalog.start()
        rt = _LensRuntime(cognitive_skill_catalog=catalog)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["cognitive_skill_count"] == 0
        assert profile["cognitive_skills"] == []


# ---------------------------------------------------------------------------
# Block 8: tool grants
# ---------------------------------------------------------------------------


class TestToolGrantsBlock:
    @pytest.mark.asyncio
    async def test_tools_present_ship_wide(self, acm):
        """Ship-wide tool (no permission matrix → READ default) is granted."""
        await acm.onboard("a1", "scout", "pool", "science")
        registry = ToolRegistry()
        registry.register(_StubTool("codebase_query"))
        rt = _LensRuntime(tool_registry=registry)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["tool_count"] == 1
        assert "codebase_query" in profile["tools"]

    @pytest.mark.asyncio
    async def test_tools_use_real_rank_not_ensign(self, acm):
        """A rank-gated tool is granted to a commander but not an ensign.

        Proves block 8 passes the agent's REAL rank, not the ensign default.
        """
        await acm.onboard("a1", "engineering_officer", "pool", "engineering")
        registry = ToolRegistry()
        # Ensign gets none; commander gets read.
        registry.register(
            _StubTool("reactor_control"),
            default_permissions={"ensign": "none", "commander": "read"},
        )

        # Ensign-identity runtime → tool NOT granted.
        ens_rt = _LensRuntime(
            tool_registry=registry,
            profile_store=_ProfileStore(_CrewProfile(department="engineering", rank="ensign")),
        )
        ens_profile = await acm.get_consolidated_profile("a1", ens_rt)
        assert "reactor_control" not in ens_profile["tools"]

        # Commander-identity runtime → tool granted.
        cmd_rt = _LensRuntime(
            tool_registry=registry,
            profile_store=_ProfileStore(_CrewProfile(department="engineering", rank="commander")),
        )
        cmd_profile = await acm.get_consolidated_profile("a1", cmd_rt)
        assert "reactor_control" in cmd_profile["tools"]

    @pytest.mark.asyncio
    async def test_tools_absent_when_no_registry(self, acm):
        """No registry → block omitted (graceful)."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = _LensRuntime(tool_registry=None)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert "tools" not in profile
        assert "tool_count" not in profile

    @pytest.mark.asyncio
    async def test_tools_empty_registry(self, acm):
        """Empty registry → empty list, count 0."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = _LensRuntime(tool_registry=ToolRegistry())

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["tool_count"] == 0
        assert profile["tools"] == []


# ---------------------------------------------------------------------------
# Additive guarantee — existing blocks untouched
# ---------------------------------------------------------------------------


class TestAdditiveLens:
    @pytest.mark.asyncio
    async def test_existing_blocks_still_present(self, acm, tmp_path):
        """Lifecycle/agent_id still returned; new blocks are purely additive."""
        await acm.onboard("a1", "scout", "pool", "science")
        catalog = await _make_catalog(tmp_path)
        registry = ToolRegistry()
        registry.register(_StubTool("codebase_query"))
        rt = _LensRuntime(tool_registry=registry, cognitive_skill_catalog=catalog)

        profile = await acm.get_consolidated_profile("a1", rt)

        assert profile["agent_id"] == "a1"
        assert profile["lifecycle_state"] == "probationary"
        assert "cognitive_skill_count" in profile
        assert "tool_count" in profile
