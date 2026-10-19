"""BF-906 (#1594) - ACM and skill-service API behind crew enrollment, the enrollment service and the route wording (milestones M1 to M3).

Unit tests for the additive API the BF-906 enrollment entry point builds on:

- ``AgentCapitalService.record_commissioning`` / ``get_commissioning_record`` /
  ``has_lifecycle_record`` (U1, U2)
- ``AgentCapitalService.onboard(reason=...)`` (U3)
- ``AgentCapitalService.commission(preserve_existing=..., grant_issued_by=...)``
  (U4, U5, U6)
- ``AgentSkillService.commission_agent(skip_skill_ids=...)`` (U7)
- the SRP size of ``AgentCapitalService`` and the ``acm.db`` store declaration
  (U14, U15: Amendment A1)

and for what sits on top of it (milestones M2 and M3):

- ``CrewEnrollmentService.enroll`` and ``enroll_wired_crew``, ``check_crew_invariant``
  and ``_boot_source`` (U8 to U12), ``log_crew_invariant_failure`` (U16 to U18: Amendment
  A2), the startup pass and the startup invariant report (extras)
- the suspend and reinstate route bodies and wording (U13)

Real subsystems on ``tmp_path`` (BF-287 discipline, as in
``test_ad889_commission_chain.py``): a real ``AgentCapitalService``,
``SkillRegistry`` + ``AgentSkillService`` and ``ToolPermissionStore``. The only
stubs are the runtime attribute-holder and the ontology (and, for the enrollment
service, the agents, the event log and the identity registry); ``_FakeTool`` only
fills the ``ToolRegistry``. Nothing here sleeps, waits or orders anything by
wall-clock time (history rows are picked by predicate, never by position).

U5 pins today's default ``commission`` semantics and uses no BF-906 API, so it is
the one test here that also passes on the pre-BF-906 source.

``test_unstarted_acm_*``, ``test_commission_preserve_existing_skips_*`` and the tests
named ``test_enroll_*`` and ``test_report_crew_invariant_*`` beyond U8 to U12 are extra
boundary tests for new branches that the contract's U-list does not reach; they are not
part of that list.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService, LifecycleState
from probos.ontology.models import RoleTemplate, SkillRequirement
from probos.skill_framework import (
    AgentSkillRecord,
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillRegistry,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPreference, ToolType
from probos.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Minimal stubs (the runtime attribute-holder and the ontology only)
# ---------------------------------------------------------------------------


class _FakeTool:
    """Minimal Tool-protocol implementation for registry registration."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._tool_id

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

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None):  # pragma: no cover - never invoked
        raise NotImplementedError


class _FakeOntology:
    """Read-only ontology stub exposing only ``get_role_template_for_agent``."""

    def __init__(self, templates: dict[str, RoleTemplate]) -> None:
        self._templates = templates

    def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
        return self._templates.get(agent_type)


class _FakeRuntime:
    """Plain attribute holder: ``commission`` reads its collaborators via getattr."""

    def __init__(
        self,
        *,
        skill_service: Any,
        tool_permission_store: Any,
        tool_registry: Any,
        skill_registry: Any,
        ontology: Any,
    ) -> None:
        self.skill_service = skill_service
        self.tool_permission_store = tool_permission_store
        self.tool_registry = tool_registry
        self.skill_registry = skill_registry
        self.ontology = ontology


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _scanner_skill() -> SkillDefinition:
    return SkillDefinition(
        skill_id="tactical_debug",
        name="Tactical Debug",
        category=SkillCategory.ROLE,
        description="role skill",
        domain="*",
        preferred_tools=[ToolPreference(tool_id="scanner", priority=1)],
    )


def _science_templates() -> dict[str, RoleTemplate]:
    """One post whose template wants ``tactical_debug`` at APPLY and ``diplomacy`` at ASSIST."""
    return {
        "science_officer": RoleTemplate(
            post_id="science_officer",
            required_skills=[
                SkillRequirement(skill_id="tactical_debug", min_proficiency=3),
                SkillRequirement(skill_id="diplomacy", min_proficiency=2),
            ],
        ),
    }


@dataclass
class _World:
    acm: AgentCapitalService
    service: AgentSkillService
    store: ToolPermissionStore
    runtime: _FakeRuntime


@contextlib.asynccontextmanager
async def _world(
    tmp_path: Path, *, templates: dict[str, RoleTemplate] | None = None,
) -> AsyncIterator[_World]:
    """Real ACM + skill service + permission store on ``tmp_path``, all stopped on exit."""
    async with contextlib.AsyncExitStack() as stack:
        registry = SkillRegistry(db_path=str(tmp_path / "registry.db"))
        await registry.start()
        stack.push_async_callback(registry.stop)
        await registry.register_skill(_scanner_skill())

        service = AgentSkillService(db_path=str(tmp_path / "skills.db"), registry=registry)
        await service.start()
        stack.push_async_callback(service.stop)

        store = ToolPermissionStore(db_path=str(tmp_path / "grants.db"))
        await store.start()
        stack.push_async_callback(store.stop)

        tool_registry = ToolRegistry()
        tool_registry.register(_FakeTool("scanner"))  # unrestricted -> ship-wide READ

        acm = AgentCapitalService(data_dir=tmp_path)
        await acm.start()
        stack.push_async_callback(acm.stop)

        runtime = _FakeRuntime(
            skill_service=service,
            tool_permission_store=store,
            tool_registry=tool_registry,
            skill_registry=registry,
            ontology=_FakeOntology(templates or {}),
        )
        yield _World(acm=acm, service=service, store=store, runtime=runtime)


@pytest.fixture
async def acm(tmp_path: Path) -> AsyncIterator[AgentCapitalService]:
    """A started ACM on ``tmp_path`` for the tests that need no skill service."""
    svc = AgentCapitalService(data_dir=tmp_path)
    await svc.start()
    try:
        yield svc
    finally:
        await svc.stop()


async def _held(service: AgentSkillService, agent_id: str) -> dict[str, AgentSkillRecord]:
    return {r.skill_id: r for r in (await service.get_profile(agent_id)).all_skills}


async def _hold_exercised(
    service: AgentSkillService, agent_id: str, skill_id: str,
    *, level: ProficiencyLevel, source: str, exercises: int,
) -> None:
    """Give the agent a skill above FOLLOW, exercised ``exercises`` times (a prior life)."""
    await service.acquire_skill(agent_id, skill_id, source=source, proficiency=level)
    for _ in range(exercises):
        await service.record_exercise(agent_id, skill_id)


# ---------------------------------------------------------------------------
# U1 / U2 / U3 - ACM recording, lifecycle-row query, onboarding reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_commissioning_first_call_true_second_false_one_same_state_row(
    acm: AgentCapitalService,
) -> None:
    """U1: recorded once; one from == to history row; the ACM state does not move."""
    agent = "agent-1"
    await acm.onboard(agent, "scout", "scout_pool", "science")
    # Premise: probationary, nothing recorded, and the only history is the onboarding row.
    assert await acm.get_lifecycle_state(agent) is LifecycleState.PROBATIONARY
    assert await acm.get_commissioning_record(agent) is None
    assert [(t.from_state, t.to_state) for t in await acm.get_transition_history(agent)] == [
        ("registered", "probationary"),
    ]

    first = await acm.record_commissioning(
        agent_id=agent, agent_type="scout", source="birth", role_template="scout_post",
        skills=("communication", "codebase_exploration"), tools=("scanner",),
        initiated_by="system", reason="BF-906 enrollment source=birth",
    )

    assert first is True
    record = await acm.get_commissioning_record(agent)
    assert record is not None
    assert (record.agent_id, record.agent_type, record.source) == (agent, "scout", "birth")
    assert record.role_template == "scout_post"
    assert record.skills == ("communication", "codebase_exploration")
    assert record.tools == ("scanner",)
    assert (record.initiated_by, record.reason) == ("system", "BF-906 enrollment source=birth")
    assert record.timestamp > 0

    history = await acm.get_transition_history(agent)
    same_state = [t for t in history if t.from_state == t.to_state]
    assert len(same_state) == 1
    assert (same_state[0].from_state, same_state[0].to_state) == ("probationary", "probationary")
    assert same_state[0].initiated_by == "system"
    assert "BF-906 enrollment source=birth" in same_state[0].reason
    assert "role_template=scout_post" in same_state[0].reason
    assert "skills=communication,codebase_exploration" in same_state[0].reason
    assert "tools=scanner" in same_state[0].reason
    # The onboarding transition is untouched and no state change was added.
    assert [(t.from_state, t.to_state) for t in history if t.from_state != t.to_state] == [
        ("registered", "probationary"),
    ]
    assert await acm.get_lifecycle_state(agent) is LifecycleState.PROBATIONARY

    second = await acm.record_commissioning(
        agent_id=agent, agent_type="scout", source="join", role_template=None,
        skills=("other",), tools=(), initiated_by="captain", reason="a later attempt",
    )

    assert second is False
    assert await acm.get_commissioning_record(agent) == record  # the first record stands
    history_after = await acm.get_transition_history(agent)
    assert len([t for t in history_after if t.from_state == t.to_state]) == 1
    assert len(history_after) == len(history)
    assert await acm.get_lifecycle_state(agent) is LifecycleState.PROBATIONARY


@pytest.mark.asyncio
async def test_has_lifecycle_record_false_for_unknown_agent_true_after_onboard(
    acm: AgentCapitalService,
) -> None:
    """U2: a missing lifecycle row is told apart from a REGISTERED one."""
    # Premise: an agent with no row reads as REGISTERED, which is what has_lifecycle_record disambiguates.
    assert await acm.get_lifecycle_state("agent-2") is LifecycleState.REGISTERED
    assert await acm.has_lifecycle_record("ghost") is False
    assert await acm.has_lifecycle_record("agent-2") is False

    await acm.onboard("agent-2", "scout", "scout_pool", "science")

    assert await acm.has_lifecycle_record("agent-2") is True
    assert await acm.has_lifecycle_record("ghost") is False  # keyed by agent, not "any row exists"


@pytest.mark.asyncio
async def test_onboard_reason_is_used_and_default_text_kept_without_it(
    acm: AgentCapitalService,
) -> None:
    """U3: ``onboard(reason=...)`` names the path; with no reason the old text stays."""
    for agent in ("agent-3a", "agent-3b", "agent-3c"):
        assert await acm.get_transition_history(agent) == []  # premise: nothing recorded yet

    named = await acm.onboard(
        "agent-3a", "scout", "scout_pool", "science", reason="BF-906 enrollment source=backfill",
    )
    assert named.reason == "BF-906 enrollment source=backfill"
    assert named.initiated_by == "system"
    assert [t.reason for t in await acm.get_transition_history("agent-3a")] == [
        "BF-906 enrollment source=backfill",
    ]

    default = await acm.onboard("agent-3b", "scout", "scout_pool", "science")
    assert default.reason == "Onboarded as scout in science"
    assert [t.reason for t in await acm.get_transition_history("agent-3b")] == [
        "Onboarded as scout in science",
    ]

    # A pre-BF-906 positional call (initiated_by, sovereign_id): ``reason`` is appended, so the order holds.
    legacy = await acm.onboard("agent-3c", "scout", "scout_pool", "science", "captain", "sovereign-3c")
    assert legacy.initiated_by == "captain"
    assert legacy.reason == "Onboarded as scout in science"


# ---------------------------------------------------------------------------
# U4 / U5 / U6 - commission(preserve_existing=..., grant_issued_by=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commission_preserve_existing_keeps_held_skills_and_acquires_missing_template_skill(
    tmp_path: Path,
) -> None:
    """U4: held records survive (template skill and PCC); a missing template skill is acquired."""
    async with _world(tmp_path, templates=_science_templates()) as w:
        agent = "agent-4"
        await _hold_exercised(
            w.service, agent, "tactical_debug",
            level=ProficiencyLevel.LEAD, source="experience", exercises=2,
        )
        await _hold_exercised(
            w.service, agent, "communication",
            level=ProficiencyLevel.ADVISE, source="experience", exercises=1,
        )
        before = await _held(w.service, agent)
        # Premise: the agent holds both above what commissioning would give, and nothing else.
        assert set(before) == {"tactical_debug", "communication"}
        assert before["tactical_debug"].proficiency == ProficiencyLevel.LEAD
        assert before["tactical_debug"].exercise_count == 2
        assert before["communication"].proficiency == ProficiencyLevel.ADVISE
        assert before["communication"].exercise_count == 1

        summary = await w.acm.commission(
            agent, "science_officer", w.runtime, preserve_existing=True,
        )

        after = await _held(w.service, agent)
        # The template skill the agent already held keeps its level and exercise count.
        assert after["tactical_debug"].proficiency == ProficiencyLevel.LEAD
        assert after["tactical_debug"].exercise_count == 2
        assert after["tactical_debug"] == before["tactical_debug"]
        # So does the PCC (the commission -> commission_agent skip_skill_ids seam).
        assert after["communication"] == before["communication"]
        # The missing template skill is still acquired, at the template's declared level.
        assert after["diplomacy"].proficiency == ProficiencyLevel.ASSIST
        assert after["diplomacy"].acquisition_source == "commission"
        # The rest of the complement is still commissioned.
        assert after["chain_of_command"].proficiency == ProficiencyLevel.FOLLOW
        assert {"tactical_debug", "communication", "diplomacy"} <= set(summary["skills_acquired"])


@pytest.mark.asyncio
async def test_commission_default_reapplies_template_level_over_lower_record(
    tmp_path: Path,
) -> None:
    """U5: the default call is unchanged - the template level is re-applied (apply-role semantics)."""
    async with _world(tmp_path, templates=_science_templates()) as w:
        agent = "agent-5"
        await w.service.acquire_skill(
            agent, "tactical_debug", source="experience", proficiency=ProficiencyLevel.FOLLOW,
        )
        before = await _held(w.service, agent)
        # Premise: the held record is below the template's APPLY.
        assert before["tactical_debug"].proficiency == ProficiencyLevel.FOLLOW

        await w.acm.commission(agent, "science_officer", w.runtime)  # defaults only

        after = await _held(w.service, agent)
        assert after["tactical_debug"].proficiency == ProficiencyLevel.APPLY
        assert after["diplomacy"].proficiency == ProficiencyLevel.ASSIST


@pytest.mark.asyncio
async def test_commission_grant_issued_by_reaches_grant_and_defaults_to_captain(
    tmp_path: Path,
) -> None:
    """U6: ``grant_issued_by`` is stamped on the tool grant; the default stays ``captain``."""
    async with _world(tmp_path, templates=_science_templates()) as w:
        # Premise: neither agent holds a scanner grant before commissioning.
        assert w.store.get_active_grants_sync("agent-6-system", "scanner") == []
        assert w.store.get_active_grants_sync("agent-6-default", "scanner") == []

        enrolled = await w.acm.commission(
            "agent-6-system", "science_officer", w.runtime, grant_issued_by="system",
        )
        default = await w.acm.commission("agent-6-default", "science_officer", w.runtime)

        assert enrolled["tools_granted"] == ["scanner"]
        assert default["tools_granted"] == ["scanner"]
        system_grants = [
            g for g in w.store.get_active_grants_sync("agent-6-system", "scanner")
            if not g.is_restriction
        ]
        default_grants = [
            g for g in w.store.get_active_grants_sync("agent-6-default", "scanner")
            if not g.is_restriction
        ]
        assert [g.issued_by for g in system_grants] == ["system"]
        assert [g.issued_by for g in default_grants] == ["captain"]


# ---------------------------------------------------------------------------
# U7 - AgentSkillService.commission_agent(skip_skill_ids=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commission_agent_skip_skill_ids_keeps_pcc_and_role_skill_records(
    tmp_path: Path,
) -> None:
    """U7: a skipped PCC and a skipped role skill keep their records; the rest is acquired."""
    async with _world(tmp_path) as w:
        agent = "agent-7"
        await _hold_exercised(
            w.service, agent, "communication",
            level=ProficiencyLevel.LEAD, source="experience", exercises=2,
        )
        await _hold_exercised(
            w.service, agent, "threat_analysis",
            level=ProficiencyLevel.ADVISE, source="mentoring", exercises=1,
        )
        before = await _held(w.service, agent)
        # Premise: a PCC and a security_officer role skill held above FOLLOW; the rest of the complement is missing.
        assert set(before) == {"communication", "threat_analysis"}
        assert before["communication"].proficiency == ProficiencyLevel.LEAD
        assert before["communication"].exercise_count == 2
        assert before["threat_analysis"].proficiency == ProficiencyLevel.ADVISE
        assert before["threat_analysis"].exercise_count == 1

        profile = await w.service.commission_agent(
            agent, "security_officer",
            skip_skill_ids=frozenset({"communication", "threat_analysis"}),
        )

        after = await _held(w.service, agent)
        assert after["communication"] == before["communication"]  # the skipped PCC
        assert after["threat_analysis"] == before["threat_analysis"]  # the skipped role skill
        # Skipping is selective: a PCC and role skills that were not named are acquired at FOLLOW.
        for skill_id in ("chain_of_command", "audit_procedures", "vulnerability_assessment"):
            assert after[skill_id].proficiency == ProficiencyLevel.FOLLOW, skill_id
            assert after[skill_id].acquisition_source == "commissioning", skill_id
        # The returned profile is the same complement.
        assert {r.skill_id: r for r in profile.all_skills} == after


# ---------------------------------------------------------------------------
# Extra boundary tests for new M1 branches (not in the contract's U1-U7 list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unstarted_acm_reads_empty_and_refuses_to_record(tmp_path: Path) -> None:
    """A never-started ACM reads as 'nothing recorded' and refuses to record."""
    acm = AgentCapitalService(data_dir=tmp_path)
    assert not (tmp_path / "acm.db").exists()  # premise: no database was opened

    assert await acm.has_lifecycle_record("ghost") is False
    assert await acm.get_commissioning_record("ghost") is None
    with pytest.raises(RuntimeError, match="ACM not started"):
        await acm.record_commissioning(
            agent_id="ghost", agent_type="scout", source="birth", role_template=None,
            skills=(), tools=(),
        )


@pytest.mark.asyncio
async def test_commission_preserve_existing_skips_when_profile_read_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """If the pre-commission profile cannot be read, nothing is written: no record can be overwritten."""
    async with _world(tmp_path, templates=_science_templates()) as w:
        agent = "agent-9"
        skills_db = tmp_path / "skills.db"
        # A stored record the service cannot read: proficiency 99 is not a ProficiencyLevel.
        with contextlib.closing(sqlite3.connect(skills_db)) as conn:
            conn.execute(
                "INSERT INTO agent_skills (agent_id, skill_id, proficiency) VALUES (?, ?, ?)",
                (agent, "communication", 99),
            )
            conn.commit()
        # Premise: the profile read really fails for this agent.
        with pytest.raises(ValueError):
            await w.service.get_profile(agent)

        with caplog.at_level(logging.WARNING, logger="probos.commissioning"):
            summary = await w.acm.commission(
                agent, "science_officer", w.runtime, preserve_existing=True,
            )

        assert summary["skills_acquired"] == []
        assert summary["tools_granted"] == []
        with contextlib.closing(sqlite3.connect(skills_db)) as conn:
            rows = conn.execute(
                "SELECT skill_id, proficiency FROM agent_skills WHERE agent_id = ?", (agent,),
            ).fetchall()
        assert rows == [("communication", 99)]  # nothing acquired, nothing overwritten
        assert w.store.get_active_grants_sync(agent, "scanner") == []
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "BF-906" in r.getMessage() and agent in r.getMessage()
        ]
        assert len(warnings) == 1


def test_agent_capital_service_is_within_the_srp_limits() -> None:
    """A1.2 (D14): the gate's srp-size rule (span > 500 lines or > 15 direct methods) must not fire on the ACM service."""
    import ast
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    checker_path = root / "scripts" / "check_architecture_principles.py"
    spec = importlib.util.spec_from_file_location("_bf906_arch_checker", checker_path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    # The checker defines dataclasses, which look their own module up in sys.modules.
    sys.modules[spec.name] = checker
    try:
        spec.loader.exec_module(checker)
    finally:
        sys.modules.pop(spec.name, None)
    max_lines = checker.SRP_MAX_BODY_LINES
    max_methods = checker.SRP_MAX_DIRECT_METHODS
    # Premise: the limits are real numbers, so the comparisons below can fail.
    assert isinstance(max_lines, int) and max_lines > 0
    assert isinstance(max_methods, int) and max_methods > 0

    tree = ast.parse((root / "src" / "probos" / "acm.py").read_text(encoding="utf-8"))
    classes = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "AgentCapitalService"
    ]
    assert len(classes) == 1  # premise: exactly one class to measure
    node = classes[0]
    # The checker's own rule (check_architecture_principles.py, srp-size).
    span = (node.end_lineno or node.lineno) - node.lineno + 1
    methods = sum(
        1 for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )

    assert span <= max_lines and methods <= max_methods, (
        f"AgentCapitalService span={span} (limit {max_lines}), "
        f"direct methods={methods} (limit {max_methods})"
    )


def test_acm_store_is_declared_and_leaves_the_baseline() -> None:
    """A1.5/A1.6 (D16): acm.db is a declared store, and its row is gone from the undeclared-store baseline."""
    import importlib

    import yaml

    from probos.storage_declarations import STORE_DECLARATIONS

    matches = [d for d in STORE_DECLARATIONS if d.id == "acm.agent-capital"]
    assert len(matches) == 1, f"declarations with id acm.agent-capital: {len(matches)}"
    decl = matches[0]
    owner = getattr(importlib.import_module(decl.owner_module), decl.owner_symbol)
    assert owner is AgentCapitalService
    assert decl.canonical_path == "acm.db"
    for table in ("lifecycle", "lifecycle_transitions", "identity_mapping", "commissioning_records"):
        assert table in decl.notes, f"notes do not name table {table}"

    baseline_path = Path(__file__).resolve().parents[1] / "docs" / "development" / "store-baseline.yaml"
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    rows = baseline["undeclared_stores"]
    assert isinstance(rows, list) and rows  # premise: the section exists and is not empty
    assert [r for r in rows if r["module"] == "probos.acm"] == []


# ---------------------------------------------------------------------------
# Milestone M2: crew enrollment (U8-U12) and the invariant-failure write (U16-U18)
# ---------------------------------------------------------------------------
# ``probos.crew_enrollment`` and ``probos.startup.crew_enrollment`` are imported inside the
# helpers and tests of this section, so the module still collects, and everything above still
# runs, on a tree that does not have them. Real ACM, skill service and permission store as
# above; the stubs below stand in for the ontology, the wired agent, the event log and the
# identity registry only. Nothing here sleeps or orders anything by wall-clock time (history
# rows are picked by predicate, never by position).
#
# The tests below that carry no U-number (``test_enroll_crew_agent_*``,
# ``test_enroll_wired_crew_*``, ``test_enroll_without_*``, ``test_enroll_onboarding_*``,
# ``test_enroll_event_log_*``, ``test_enroll_boot_crew_*`` and ``test_report_crew_invariant_*``)
# are extra boundary tests for branches the contract's U8-U12 / U16-U18 list does not reach.


@dataclass(frozen=True)
class _FakeAgent:
    """The attributes crew enrollment reads from a wired agent."""

    id: str
    agent_type: str
    pool: str = "enrollment_pool"
    sovereign_id: str = ""


class _CrewOntology(_FakeOntology):
    """The ontology surface enrollment reads: crew types, department and role template."""

    def __init__(
        self,
        templates: dict[str, RoleTemplate],
        *,
        crew_types: set[str],
        departments: dict[str, str] | None = None,
    ) -> None:
        super().__init__(templates)
        self._crew_types = set(crew_types)
        self._departments = dict(departments or {})

    def get_crew_agent_types(self) -> set[str]:
        return set(self._crew_types)

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._departments.get(agent_type)


class _FakeEventLog:
    """Keeps the keyword arguments of every ``log`` call, as ``EventLog.log`` receives them."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def log(self, **row: Any) -> int:
        self.rows.append(row)
        return len(self.rows)


@dataclass(frozen=True)
class _FakeCertificate:
    birth_timestamp: float


class _FakeIdentityRegistry:
    """Maps a slot id to a certificate that carries only a birth timestamp."""

    def __init__(self, births: dict[str, float]) -> None:
        self._certificates = {slot: _FakeCertificate(born) for slot, born in births.items()}

    def get_by_slot(self, slot_id: str) -> _FakeCertificate | None:
        return self._certificates.get(slot_id)


def _enrollment_service(
    w: _World,
    ontology: _CrewOntology,
    *,
    identity_registry: Any = None,
    event_log: Any = None,
    boot_started_at: float = 1_000.0,
) -> Any:
    """A ``CrewEnrollmentService`` over the world's real ACM and skill service."""
    from probos.crew_enrollment import CrewEnrollmentService

    # The commissioning chain reads role templates from ``runtime.ontology``: one ontology for both.
    w.runtime.ontology = ontology
    return CrewEnrollmentService(
        acm=w.acm,
        ontology=ontology,
        skill_service=w.service,
        identity_registry=identity_registry,
        event_log=event_log,
        commission_context=w.runtime,
        boot_started_at=boot_started_at,
    )


def _same_state(history: list[Any]) -> list[Any]:
    """The commissioning rows of a lifecycle history (from_state == to_state), picked by predicate."""
    return [t for t in history if t.from_state == t.to_state]


@pytest.mark.asyncio
async def test_enroll_non_crew_agent_returns_none_and_writes_nothing(tmp_path: Path) -> None:
    """U8: only crew are enrolled; any other agent gets None and no ACM, skill or event-log row."""
    from types import SimpleNamespace

    from probos.crew_utils import is_crew_agent

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        event_log = _FakeEventLog()
        service = _enrollment_service(w, ontology, event_log=event_log)
        visitor = _FakeAgent("visitor-8", "visitor")
        bare = SimpleNamespace(id="bare-8")  # no agent_type at all
        scout = _FakeAgent("scout-8", "scout")
        # Premise: the first two are not crew and the scout is, by the test enrollment applies.
        assert is_crew_agent(visitor, ontology) is False
        assert is_crew_agent(bare, ontology) is False
        assert is_crew_agent(scout, ontology) is True

        for agent in (visitor, bare):
            assert await service.enroll(agent, source="join") is None
            assert await w.acm.has_lifecycle_record(agent.id) is False
            assert await w.acm.get_commissioning_record(agent.id) is None
            assert await w.acm.get_transition_history(agent.id) == []
            assert (await w.service.get_profile(agent.id)).all_skills == []
        assert event_log.rows == []

        # Control: the same service does enroll a crew agent, so the None above is not an idle service.
        enrolled = await service.enroll(scout, source="join")
        assert enrolled is not None and enrolled.commissioned is True
        assert [row["agent_id"] for row in event_log.rows] == [scout.id]


@pytest.mark.asyncio
async def test_enroll_unknown_source_raises_value_error_and_writes_nothing(tmp_path: Path) -> None:
    """U9: a source outside birth / backfill / join is refused before anything is written."""
    from probos.crew_enrollment import ENROLLMENT_SOURCES

    assert ENROLLMENT_SOURCES == {"birth", "backfill", "join"}  # premise: the whole vocabulary
    async with _world(tmp_path) as w:
        event_log = _FakeEventLog()
        service = _enrollment_service(w, _CrewOntology({}, crew_types={"scout"}), event_log=event_log)
        agent = _FakeAgent("scout-9", "scout")

        for source in ("other", "", "Birth"):
            with pytest.raises(ValueError, match="unknown enrollment source"):
                await service.enroll(agent, source=source)

        assert await w.acm.has_lifecycle_record(agent.id) is False
        assert await w.acm.get_commissioning_record(agent.id) is None
        assert event_log.rows == []


@pytest.mark.asyncio
async def test_enroll_commissioning_that_leaves_no_skills_records_nothing_and_logs_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """U10: an empty profile after commissioning is not recorded, is an ERROR, and the invariant lists it."""
    from probos.crew_enrollment import check_crew_invariant

    async with _world(tmp_path) as w:
        async def _no_commissioning(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(w.service, "commission_agent", _no_commissioning)
        ontology = _CrewOntology({}, crew_types={"scout"})
        event_log = _FakeEventLog()
        service = _enrollment_service(w, ontology, event_log=event_log)
        agent = _FakeAgent("scout-10", "scout")
        # Premise: no role template for the type, and the agent holds no skill.
        assert ontology.get_role_template_for_agent("scout") is None
        assert (await w.service.get_profile(agent.id)).all_skills == []

        with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
            result = await service.enroll(agent, source="join")

        assert result is not None
        assert (result.onboarded, result.commissioned) == (True, False)
        assert (result.skills_granted, result.tools_granted) == ((), ())
        assert await w.acm.get_commissioning_record(agent.id) is None
        assert _same_state(await w.acm.get_transition_history(agent.id)) == []
        assert event_log.rows == []
        assert (await w.service.get_profile(agent.id)).all_skills == []
        errors = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert "BF-906" in errors[0].getMessage()
        assert agent.id in errors[0].getMessage()
        assert "no skills" in errors[0].getMessage()
        report = await check_crew_invariant(
            acm=w.acm, skill_service=w.service, ontology=ontology, agents=[agent],
        )
        assert report.checked == 1
        assert report.never_commissioned == (agent.id,)
        assert report.missing_lifecycle == ()  # it was onboarded; only the commissioning is missing
        assert report.ok is False


@pytest.mark.asyncio
async def test_check_crew_invariant_commissioned_means_a_record_or_skills_and_decommissioned_is_exempt(
    tmp_path: Path,
) -> None:
    """U11: a skilled agent and a decommissioned one with no record pass; acm=None lists every crew member."""
    from probos.crew_enrollment import check_crew_invariant

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        skilled = _FakeAgent("skilled-11", "scout")
        decommissioned = _FakeAgent("decom-11", "scout")
        bare = _FakeAgent("bare-11", "scout")
        ghost = _FakeAgent("ghost-11", "scout")
        recorded = _FakeAgent("recorded-11", "scout")
        visitor = _FakeAgent("visitor-11", "visitor")
        for agent in (skilled, decommissioned, bare, recorded):
            await w.acm.onboard(agent.id, "scout", "scout_pool", "science")
        await w.service.acquire_skill(
            skilled.id, "communication", source="experience", proficiency=ProficiencyLevel.ASSIST,
        )
        await w.acm.decommission(decommissioned.id)
        await w.acm.record_commissioning(
            agent_id=recorded.id, agent_type="scout", source="birth", role_template=None,
            skills=(), tools=(),
        )
        # Premise: the five situations are what the names say. ``ghost`` has no row at all.
        assert await w.acm.get_lifecycle_state(decommissioned.id) is LifecycleState.DECOMMISSIONED
        assert await w.acm.has_lifecycle_record(ghost.id) is False
        for agent in (skilled, decommissioned, bare, ghost):
            assert await w.acm.get_commissioning_record(agent.id) is None
        assert (await w.service.get_profile(skilled.id)).all_skills != []
        for agent in (decommissioned, bare, ghost, recorded):
            assert (await w.service.get_profile(agent.id)).all_skills == []

        async def check(acm: Any, agents: list[Any]) -> Any:
            return await check_crew_invariant(
                acm=acm, skill_service=w.service, ontology=ontology, agents=agents,
            )

        healthy = await check(w.acm, [skilled, decommissioned, recorded])
        assert healthy.ok is True
        assert (healthy.checked, healthy.missing_lifecycle, healthy.never_commissioned) == (3, (), ())

        everyone = await check(w.acm, [skilled, decommissioned, bare, ghost, recorded, visitor])
        assert everyone.checked == 5  # the visitor is not crew
        assert everyone.missing_lifecycle == (ghost.id,)
        assert everyone.never_commissioned == (bare.id, ghost.id)
        assert everyone.ok is False
        assert everyone.to_dict() == {
            "checked": 5, "missing_lifecycle": [ghost.id], "never_commissioned": [bare.id, ghost.id],
        }

        no_acm = await check(None, [skilled, bare, visitor])
        assert no_acm.checked == 2
        assert no_acm.missing_lifecycle == (bare.id, skilled.id)
        assert no_acm.never_commissioned == (bare.id, skilled.id)
        assert no_acm.ok is False

        no_skills = await check_crew_invariant(
            acm=w.acm, skill_service=None, ontology=ontology, agents=[skilled, recorded],
        )
        assert no_skills.checked == 2
        assert no_skills.never_commissioned == (skilled.id,)  # no skill service: only a record counts


@pytest.mark.asyncio
async def test_boot_source_certificate_older_than_the_boot_is_backfill_else_birth(tmp_path: Path) -> None:
    """U12: a certificate older than the boot gives backfill; a newer one, none, or no registry gives birth."""
    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        registry = _FakeIdentityRegistry({"older": 999.0, "newer": 1_001.0, "same": 1_000.0})
        service = _enrollment_service(
            w, ontology, identity_registry=registry, boot_started_at=1_000.0,
        )
        no_registry = _enrollment_service(
            w, ontology, identity_registry=None, boot_started_at=1_000.0,
        )
        # Premise: the registry knows three slots and not the fourth.
        assert registry.get_by_slot("none") is None
        assert registry.get_by_slot("older") is not None

        assert service._boot_source(_FakeAgent("older", "scout")) == "backfill"
        assert service._boot_source(_FakeAgent("newer", "scout")) == "birth"
        assert service._boot_source(_FakeAgent("same", "scout")) == "birth"  # not older than the boot
        assert service._boot_source(_FakeAgent("none", "scout")) == "birth"
        assert no_registry._boot_source(_FakeAgent("older", "scout")) == "birth"


@pytest.mark.asyncio
async def test_invariant_failure_row_is_written_with_the_report() -> None:
    """U16: the failure row carries the lifecycle category, the failure event and the report as data."""
    from unittest.mock import AsyncMock

    from probos.crew_enrollment import CrewInvariantReport, log_crew_invariant_failure

    report = CrewInvariantReport(
        checked=3, missing_lifecycle=("agent-a",), never_commissioned=("agent-a", "agent-b"),
    )
    assert report.ok is False  # premise: a failing report
    assert report.to_dict() == {
        "checked": 3, "missing_lifecycle": ["agent-a"], "never_commissioned": ["agent-a", "agent-b"],
    }
    event_log = AsyncMock()

    written = await log_crew_invariant_failure(event_log, report)

    assert written is True
    event_log.log.assert_awaited_once_with(
        category="lifecycle", event="crew_invariant_failed", data=report.to_dict(),
    )


@pytest.mark.asyncio
async def test_invariant_failure_without_an_event_log_warns_and_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """U17: no event log is not an error: False, no raise, and one WARNING that says so."""
    from probos.crew_enrollment import CrewInvariantReport, log_crew_invariant_failure

    report = CrewInvariantReport(checked=1, missing_lifecycle=("agent-a",), never_commissioned=("agent-a",))

    with caplog.at_level(logging.WARNING, logger="probos.crew_enrollment"):
        written = await log_crew_invariant_failure(None, report)

    assert written is False
    warnings = [
        r for r in caplog.records
        if r.name == "probos.crew_enrollment" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "no event log" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_invariant_failure_write_error_warns_and_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """U18: a failing write never raises: False, and one WARNING that carries the exception."""
    from unittest.mock import AsyncMock

    from probos.crew_enrollment import CrewInvariantReport, log_crew_invariant_failure

    report = CrewInvariantReport(checked=1, missing_lifecycle=("agent-a",), never_commissioned=("agent-a",))
    event_log = AsyncMock()
    event_log.log.side_effect = RuntimeError("events.db is locked")

    with caplog.at_level(logging.WARNING, logger="probos.crew_enrollment"):
        written = await log_crew_invariant_failure(event_log, report)

    assert written is False
    event_log.log.assert_awaited_once()  # the write was attempted
    warnings = [
        r for r in caplog.records
        if r.name == "probos.crew_enrollment" and r.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "could not be written" in warnings[0].getMessage()
    assert warnings[0].exc_info is not None and warnings[0].exc_info[0] is RuntimeError


@pytest.mark.asyncio
async def test_enroll_crew_agent_onboards_commissions_records_and_logs_once(tmp_path: Path) -> None:
    """Extra: the happy path on the real chain, and a second call that changes nothing."""
    from probos.crew_enrollment import CrewEnrollment

    templates = _science_templates()
    async with _world(tmp_path, templates=templates) as w:
        ontology = _CrewOntology(
            templates, crew_types={"science_officer"}, departments={"science_officer": "science"},
        )
        event_log = _FakeEventLog()
        service = _enrollment_service(w, ontology, event_log=event_log)
        agent = _FakeAgent("agent-e1", "science_officer", pool="science_pool", sovereign_id="sovereign-e1")
        # Premise: a new crew agent - no lifecycle row, no skill, no grant.
        assert await w.acm.has_lifecycle_record(agent.id) is False
        assert (await w.service.get_profile(agent.id)).all_skills == []
        assert w.store.get_active_grants_sync(agent.id) == []

        first = await service.enroll(agent, source="join")

        assert first is not None
        assert (first.agent_id, first.agent_type, first.source) == (agent.id, "science_officer", "join")
        assert (first.onboarded, first.commissioned) == (True, True)
        assert first.role_template == "science_officer"
        assert {"communication", "tactical_debug", "diplomacy"} <= set(first.skills_granted)
        assert first.tools_granted == ("scanner",)
        assert await w.acm.get_lifecycle_state(agent.id) is LifecycleState.PROBATIONARY
        record = await w.acm.get_commissioning_record(agent.id)
        assert record is not None
        assert (record.source, record.role_template, record.initiated_by) == (
            "join", "science_officer", "system",
        )
        assert (record.skills, record.tools) == (first.skills_granted, ("scanner",))
        assert "BF-906" in record.reason
        history = await w.acm.get_transition_history(agent.id)
        onboarding = [t for t in history if (t.from_state, t.to_state) == ("registered", "probationary")]
        assert len(onboarding) == 1
        assert onboarding[0].initiated_by == "system"
        assert "BF-906" in onboarding[0].reason and "source=join" in onboarding[0].reason
        assert "in science" in onboarding[0].reason  # the ontology's department
        assert len(_same_state(history)) == 1
        assert "source=join" in _same_state(history)[0].reason
        assert [g.issued_by for g in w.store.get_active_grants_sync(agent.id, "scanner")] == ["system"]
        assert len(event_log.rows) == 1
        row = event_log.rows[0]
        assert (row["category"], row["event"], row["agent_id"], row["agent_type"], row["pool"]) == (
            "lifecycle", "crew_commissioned", agent.id, "science_officer", "science_pool",
        )
        assert row["data"] == {
            "source": "join", "role_template": "science_officer",
            "skills": list(first.skills_granted), "tools": ["scanner"],
            "initiated_by": "system", "reason": record.reason,
        }
        held = await _held(w.service, agent.id)

        second = await service.enroll(agent, source="join")

        assert second == CrewEnrollment(
            agent_id=agent.id, agent_type="science_officer", source="join",
            onboarded=False, commissioned=False,
        )
        assert await w.acm.get_commissioning_record(agent.id) == record
        assert await w.acm.get_transition_history(agent.id) == history
        assert len(event_log.rows) == 1
        assert await _held(w.service, agent.id) == held
        assert len(w.store.get_active_grants_sync(agent.id, "scanner")) == 1


@pytest.mark.asyncio
async def test_enroll_wired_crew_records_the_source_each_certificate_dates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: the Phase 7 pass crosses ``_boot_source`` -> ``enroll`` -> the record; a second pass does nothing."""
    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        registry = _FakeIdentityRegistry({"old-e2": 900.0, "new-e2": 1_100.0})
        event_log = _FakeEventLog()
        service = _enrollment_service(
            w, ontology, identity_registry=registry, event_log=event_log, boot_started_at=1_000.0,
        )
        agents = [
            _FakeAgent("old-e2", "scout"), _FakeAgent("new-e2", "scout"),
            _FakeAgent("bare-e2", "scout"), _FakeAgent("visitor-e2", "visitor"),
        ]
        expected = {"old-e2": "backfill", "new-e2": "birth", "bare-e2": "birth"}

        with caplog.at_level(logging.INFO, logger="probos.crew_enrollment"):
            results = await service.enroll_wired_crew(agents)

        assert {r.agent_id: r.source for r in results} == expected  # the visitor is not enrolled
        assert all(r.onboarded and r.commissioned for r in results)
        for agent_id, source in expected.items():
            record = await w.acm.get_commissioning_record(agent_id)
            assert record is not None and record.source == source
        assert await w.acm.has_lifecycle_record("visitor-e2") is False
        summaries = [
            r.getMessage() for r in caplog.records
            if r.name == "probos.crew_enrollment" and "crew enrollment pass" in r.getMessage()
        ]
        assert summaries == [
            "BF-906: crew enrollment pass: 3 crew, 3 onboarded, 3 commissioned (2 birth, 1 backfill)",
        ]
        assert len(event_log.rows) == 3

        again = await service.enroll_wired_crew(agents)

        assert [(r.agent_id, r.onboarded, r.commissioned) for r in again] == [
            ("old-e2", False, False), ("new-e2", False, False), ("bare-e2", False, False),
        ]
        assert len(event_log.rows) == 3


@pytest.mark.asyncio
async def test_enroll_wired_crew_continues_after_one_agent_fails_and_logs_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: one agent's failure is an ERROR naming it, and the rest of the pass still enrolls."""

    class _BrokenRegistry(_FakeIdentityRegistry):
        def get_by_slot(self, slot_id: str) -> _FakeCertificate | None:
            if slot_id == "broken-e3":
                raise RuntimeError("identity.db is offline")
            return super().get_by_slot(slot_id)

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        service = _enrollment_service(
            w, ontology, identity_registry=_BrokenRegistry({}), event_log=_FakeEventLog(),
        )

        with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
            results = await service.enroll_wired_crew(
                [_FakeAgent("broken-e3", "scout"), _FakeAgent("fine-e3", "scout")],
            )

        assert [r.agent_id for r in results] == ["fine-e3"]
        assert await w.acm.get_commissioning_record("fine-e3") is not None
        assert await w.acm.get_commissioning_record("broken-e3") is None
        assert await w.acm.has_lifecycle_record("broken-e3") is False
        errors = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert "broken-e3" in errors[0].getMessage() and "enrollment failed" in errors[0].getMessage()
        assert errors[0].exc_info is not None


@pytest.mark.asyncio
async def test_enroll_without_a_usable_skill_service_records_nothing_and_logs_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: no skill service, or a profile read that fails: onboarded, never recorded, one ERROR each."""
    from probos.crew_enrollment import CrewEnrollmentService

    class _FailingSkills:
        async def get_profile(self, agent_id: str) -> Any:
            raise RuntimeError("skills.db is offline")

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        w.runtime.ontology = ontology
        for agent_id, skills in (("no-skills-e4", None), ("failing-skills-e4", _FailingSkills())):
            service = CrewEnrollmentService(
                acm=w.acm, ontology=ontology, skill_service=skills, identity_registry=None,
                event_log=_FakeEventLog(), commission_context=w.runtime, boot_started_at=1_000.0,
            )

            with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
                result = await service.enroll(_FakeAgent(agent_id, "scout"), source="join")

            assert result is not None
            assert (result.onboarded, result.commissioned) == (True, False), agent_id
            assert await w.acm.get_commissioning_record(agent_id) is None, agent_id
            assert (await w.service.get_profile(agent_id)).all_skills == [], agent_id
            errors = [
                r for r in caplog.records
                if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR
                and agent_id in r.getMessage()
            ]
            assert len(errors) == 1, agent_id


@pytest.mark.asyncio
async def test_enroll_onboarding_failure_is_logged_and_the_invariant_reports_the_missing_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: an ACM onboarding failure is an ERROR naming the agent, and the invariant reports its missing row."""
    from probos.crew_enrollment import check_crew_invariant

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        service = _enrollment_service(w, ontology, event_log=_FakeEventLog())
        agent = _FakeAgent("agent-e5", "scout")

        async def _refuse(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("acm.db is locked")

        monkeypatch.setattr(w.acm, "onboard", _refuse)

        with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
            result = await service.enroll(agent, source="join")

        assert result is not None and result.onboarded is False
        assert await w.acm.has_lifecycle_record(agent.id) is False
        errors = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert agent.id in errors[0].getMessage() and "onboarding failed" in errors[0].getMessage()
        assert errors[0].exc_info is not None
        report = await check_crew_invariant(
            acm=w.acm, skill_service=w.service, ontology=ontology, agents=[agent],
        )
        assert report.missing_lifecycle == (agent.id,)
        assert report.ok is False


@pytest.mark.asyncio
async def test_enroll_event_log_failure_or_absence_keeps_the_recorded_commissioning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: the event-log row is best effort; the ACM record is authoritative."""

    class _FailingEventLog:
        async def log(self, **row: Any) -> int:
            raise RuntimeError("events.db is locked")

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        failing = _enrollment_service(w, ontology, event_log=_FailingEventLog())
        absent = _enrollment_service(w, ontology, event_log=None)

        with caplog.at_level(logging.WARNING, logger="probos.crew_enrollment"):
            broken = await failing.enroll(_FakeAgent("failing-log-e6", "scout"), source="join")
            quiet = await absent.enroll(_FakeAgent("no-log-e6", "scout"), source="join")

        for result in (broken, quiet):
            assert result is not None and result.commissioned is True
        for agent_id in ("failing-log-e6", "no-log-e6"):
            assert await w.acm.get_commissioning_record(agent_id) is not None
        unlogged = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and "not in the event log" in r.getMessage()
        ]
        assert [("failing-log-e6" in r.getMessage(), r.exc_info is not None) for r in unlogged] == [
            (True, True),
        ]


@pytest.mark.asyncio
async def test_report_crew_invariant_logs_error_and_writes_the_event_row_only_on_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: a healthy crew writes no row; a failing one is an ERROR naming the agent plus the event row."""
    from types import SimpleNamespace

    from probos.startup.crew_enrollment import report_crew_invariant

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        enrolled = _FakeAgent("enrolled-e7", "scout")
        stranger = _FakeAgent("stranger-e7", "scout")  # never enrolled
        enrolled_result = await _enrollment_service(w, ontology, event_log=_FakeEventLog()).enroll(
            enrolled, source="birth",
        )
        assert enrolled_result is not None and enrolled_result.commissioned is True  # premise
        event_log = _FakeEventLog()
        runtime = SimpleNamespace(
            acm=w.acm, skill_service=w.service, ontology=ontology,
            registry=SimpleNamespace(all=lambda: [enrolled]), event_log=event_log,
        )

        with caplog.at_level(logging.INFO, logger="probos.startup.crew_enrollment"):
            holds = await report_crew_invariant(runtime=runtime)

        assert holds is not None and holds.ok is True and holds.checked == 1
        assert event_log.rows == []
        assert any(
            "invariant holds" in r.getMessage() for r in caplog.records
            if r.name == "probos.startup.crew_enrollment"
        )

        runtime.registry = SimpleNamespace(all=lambda: [enrolled, stranger])
        with caplog.at_level(logging.ERROR, logger="probos.startup.crew_enrollment"):
            failed = await report_crew_invariant(runtime=runtime)

        assert failed is not None and failed.ok is False
        assert failed.missing_lifecycle == (stranger.id,)
        assert failed.never_commissioned == (stranger.id,)
        errors = [
            r for r in caplog.records
            if r.name == "probos.startup.crew_enrollment" and r.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert "crew invariant FAILED" in errors[0].getMessage()
        assert stranger.id in errors[0].getMessage()
        assert [(r["category"], r["event"]) for r in event_log.rows] == [
            ("lifecycle", "crew_invariant_failed"),
        ]
        assert event_log.rows[0]["data"] == failed.to_dict()


@pytest.mark.asyncio
async def test_enroll_boot_crew_without_acm_returns_none_and_sets_no_enroller(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Extra: with no ACM the pass is an ERROR, returns None, and hands onboarding nothing."""
    from types import SimpleNamespace

    from probos.startup.crew_enrollment import enroll_boot_crew

    handed: list[Any] = []
    runtime = SimpleNamespace(acm=None, onboarding=SimpleNamespace(set_crew_enroller=handed.append))

    with caplog.at_level(logging.ERROR, logger="probos.startup.crew_enrollment"):
        service = await enroll_boot_crew(runtime=runtime, boot_started_at=1_000.0)

    assert service is None
    assert handed == []
    errors = [
        r for r in caplog.records
        if r.name == "probos.startup.crew_enrollment" and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1 and "ACM is unavailable" in errors[0].getMessage()


@pytest.mark.asyncio
async def test_enroll_boot_crew_enrolls_the_wired_crew_then_hands_onboarding_the_joining_path(
    tmp_path: Path,
) -> None:
    """Extra: Phase 7 crosses the pass -> ``set_crew_enroller`` -> a later agent enrolled with source ``join``."""
    from types import SimpleNamespace

    from probos.startup.crew_enrollment import enroll_boot_crew

    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        old = _FakeAgent("old-e8", "scout")
        visitor = _FakeAgent("visitor-e8", "visitor")
        late = _FakeAgent("late-e8", "scout")
        handed: list[Any] = []
        runtime = w.runtime  # the commissioning context is the runtime itself
        runtime.ontology = ontology
        runtime.acm = w.acm
        runtime.identity_registry = _FakeIdentityRegistry({"old-e8": 900.0})
        runtime.event_log = _FakeEventLog()
        runtime.registry = SimpleNamespace(all=lambda: [old, visitor])
        runtime.onboarding = SimpleNamespace(set_crew_enroller=handed.append)
        assert await w.acm.get_commissioning_record(late.id) is None  # premise: not wired yet

        service = await enroll_boot_crew(runtime=runtime, boot_started_at=1_000.0)

        assert service is not None
        old_record = await w.acm.get_commissioning_record(old.id)
        assert old_record is not None and old_record.source == "backfill"
        assert await w.acm.has_lifecycle_record(visitor.id) is False
        assert len(handed) == 1  # onboarding was handed exactly one enroller

        joined = await handed[0](late)

        assert joined is not None and (joined.source, joined.commissioned) == ("join", True)
        late_record = await w.acm.get_commissioning_record(late.id)
        assert late_record is not None and late_record.source == "join"


# ---------------------------------------------------------------------------
# U13 - the HR-status routes say they record a status and stop nothing (milestone M3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hr_status_routes_answer_that_they_record_a_status_only(
    acm: AgentCapitalService,
) -> None:
    """U13: suspend and reinstate answer ``hr_status_only`` and the note, and keep ``status`` and the transition."""
    from types import SimpleNamespace

    from probos.api_models import AgentLifecycleRequest
    from probos.routers.acm import HR_STATUS_NOTE, reinstate_agent, suspend_agent

    runtime = SimpleNamespace(acm=acm)  # the two routes read ``runtime.acm`` and nothing else
    await acm.onboard("hr-u13", "scout", "science", "science")
    assert await acm.check_activation("hr-u13", 0.65, 0.65) is True  # premise: only an active agent can be suspended
    assert await acm.get_lifecycle_state("hr-u13") is LifecycleState.ACTIVE

    suspended = await suspend_agent("hr-u13", AgentLifecycleRequest(reason="inspection"), runtime)

    assert set(suspended) == {"status", "hr_status_only", "note", "transition"}
    assert suspended["status"] == "suspended"  # the pre-existing key is kept
    assert suspended["hr_status_only"] is True
    assert suspended["note"] == HR_STATUS_NOTE
    assert set(suspended["transition"]) == {"from_state", "to_state", "reason", "timestamp"}
    assert (suspended["transition"]["from_state"], suspended["transition"]["to_state"]) == ("active", "suspended")
    assert suspended["transition"]["reason"] == "inspection"
    assert await acm.get_lifecycle_state("hr-u13") is LifecycleState.SUSPENDED

    reinstated = await reinstate_agent("hr-u13", AgentLifecycleRequest(), runtime)

    assert set(reinstated) == {"status", "hr_status_only", "note", "transition"}
    assert reinstated["status"] == "active"
    assert reinstated["hr_status_only"] is True
    assert reinstated["note"] == HR_STATUS_NOTE
    assert set(reinstated["transition"]) == {"from_state", "to_state", "reason", "timestamp"}
    assert (reinstated["transition"]["from_state"], reinstated["transition"]["to_state"]) == ("suspended", "active")
    assert reinstated["transition"]["reason"] == "Reinstated by Captain"  # the default reason is kept
    assert await acm.get_lifecycle_state("hr-u13") is LifecycleState.ACTIVE


def test_hr_status_note_says_it_records_a_status_only_and_names_the_operational_stop() -> None:
    """U13: the note's wording (pinned by the contract) says HR record only, and where the operational stop lives."""
    from probos.routers.acm import HR_STATUS_NOTE

    assert HR_STATUS_NOTE == (
        "Records an HR status only. It does not stop or resume the agent's work "
        "(the operational stop is AD-1343)."
    )


def test_hr_status_route_docstrings_say_suspend_does_not_stop_and_reinstate_resumes_nothing() -> None:
    """U13: the route docstrings (shown in the OpenAPI schema) carry the same message as the body's note."""
    from probos.routers.acm import reinstate_agent, suspend_agent

    suspend_doc = " ".join((suspend_agent.__doc__ or "").split())
    reinstate_doc = " ".join((reinstate_agent.__doc__ or "").split())

    assert "does not stop" in suspend_doc
    assert "AD-1343" in suspend_doc
    assert "resumes nothing" in reinstate_doc
    assert "AD-1343" in reinstate_doc


# ---------------------------------------------------------------------------
# Gap tests (repair round 1): enrollment details the contract's rows left unpinned
# ---------------------------------------------------------------------------


def _read_committed(tmp_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Committed state, through a separate read-only stdlib connection (opened and closed per query)."""
    connection = sqlite3.connect(f"{(tmp_path / 'acm.db').resolve().as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_enroll_an_agent_that_already_holds_a_skill_records_only_what_the_chain_acquired(
    tmp_path: Path,
) -> None:
    """HA3: a skill held before enrollment is neither recorded nor granted, and keeps its level and exercises."""
    templates = _science_templates()
    async with _world(tmp_path, templates=templates) as w:
        ontology = _CrewOntology(
            templates, crew_types={"science_officer"}, departments={"science_officer": "science"},
        )
        service = _enrollment_service(w, ontology)
        agent = _FakeAgent("agent-ha3", "science_officer", pool="science_pool")
        await _hold_exercised(
            w.service, agent.id, "diplomacy", level=ProficiencyLevel.APPLY, source="prior", exercises=3,
        )
        before = await _held(w.service, agent.id)
        assert set(before) == {"diplomacy"}  # premise: it holds diplomacy, above the template's ASSIST
        assert before["diplomacy"].proficiency == ProficiencyLevel.APPLY
        assert before["diplomacy"].exercise_count == 3

        result = await service.enroll(agent, source="join")

        assert result is not None and result.commissioned is True
        record = await w.acm.get_commissioning_record(agent.id)
        assert record is not None
        for skills in (record.skills, result.skills_granted):
            assert "diplomacy" not in skills
            assert "tactical_debug" in skills  # newly acquired from the template
            assert {"communication", "duty_execution"} <= set(skills)  # newly acquired PCCs
        assert record.skills == result.skills_granted
        after = await _held(w.service, agent.id)
        assert after["diplomacy"].proficiency == ProficiencyLevel.APPLY
        assert after["diplomacy"].exercise_count == 3


@pytest.mark.asyncio
async def test_enroll_warns_about_a_missing_role_template_only_for_a_type_without_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """HA8: the 'no role template' WARNING names the type and the agent, and only a type without a template gets it."""
    templates = _science_templates()
    async with _world(tmp_path, templates=templates) as w:
        ontology = _CrewOntology(
            templates, crew_types={"science_officer", "scout"}, departments={"science_officer": "science"},
        )
        service = _enrollment_service(w, ontology)
        with_template = _FakeAgent("agent-ha8-t", "science_officer", pool="science_pool")
        without_template = _FakeAgent("agent-ha8-n", "scout")

        with caplog.at_level(logging.WARNING, logger="probos.crew_enrollment"):
            await service.enroll(with_template, source="join")
            await service.enroll(without_template, source="join")

        first = await w.acm.get_commissioning_record(with_template.id)
        second = await w.acm.get_commissioning_record(without_template.id)
        assert first is not None and first.role_template is not None  # premise
        assert second is not None and second.role_template is None  # premise
        warnings = [
            r.getMessage() for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.WARNING
            and "no role template" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "scout" in warnings[0] and without_template.id in warnings[0]
        assert "science_officer" not in warnings[0] and with_template.id not in warnings[0]


@pytest.mark.asyncio
async def test_enroll_maps_the_agents_sovereign_id_to_its_slot_in_acm(tmp_path: Path) -> None:
    """HA9: the agent's sovereign id reaches ``identity_mapping``; an agent without one has no mapping row."""
    async with _world(tmp_path) as w:
        ontology = _CrewOntology({}, crew_types={"scout"})
        service = _enrollment_service(w, ontology)
        sovereign = _FakeAgent("agent-ha9-s", "scout", sovereign_id="sov-agent-ha9-s")
        plain = _FakeAgent("agent-ha9-p", "scout")
        assert sovereign.sovereign_id == "sov-agent-ha9-s" and plain.sovereign_id == ""  # premise

        await service.enroll(sovereign, source="join")
        await service.enroll(plain, source="join")

        query = "SELECT sovereign_id FROM identity_mapping WHERE slot_id = ?"
        assert _read_committed(tmp_path, query, (sovereign.id,)) == [("sov-agent-ha9-s",)]
        assert _read_committed(tmp_path, query, (plain.id,)) == []


# ---------------------------------------------------------------------------
# BF-906 A3 (F1, F2): ACM write sections are atomic; a failed base step is not recorded
#
# F1 cannot be reproduced by racing on every host (asyncio timers shorter than the clock
# tick collapse on Windows), so these tests GATE a writer with ``_GatedConnection``: the
# writer is held inside its section, at a chosen statement, while another writer (and
# ``stop``) is started. Nothing here races, and the one bounded wait (U19) always expires
# under correct code.
# ---------------------------------------------------------------------------


class _GatedConnection:
    """Test-only proxy over ACM's real connection: holds or fails ONE keyed statement.

    ``execute`` is a sync method, like aiosqlite's: a statement the key does not match
    returns ``real.execute(...)`` unchanged (ACM's readers use ``async with``), the keyed
    one returns a coroutine that waits on ``release`` (``mode="hold"``) or raises
    (``mode="fail"``).
    """

    def __init__(self, real: Any, key: Any, *, mode: str = "hold") -> None:
        self.real = real
        self.key = key
        self.mode = mode
        self.armed = True
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)

    def execute(self, sql: str, parameters: Any = None) -> Any:
        if self.armed and self.key(sql, parameters):
            return self._gated(sql, parameters)
        return self.real.execute(sql, parameters)

    async def _gated(self, sql: str, parameters: Any) -> Any:
        if self.mode == "fail":
            raise sqlite3.OperationalError("BF-906 A3: injected write failure")
        self.arrived.set()
        await self.release.wait()
        return await self.real.execute(sql, parameters)


def _a3_key(writer: str, target: str) -> Any:
    """The statement that identifies ``writer``'s section for ``target``: its LAST statement but one."""
    if writer == "record":
        return lambda sql, p: sql.startswith("INSERT INTO lifecycle_transitions") and p[0] == target
    if writer == "transition":
        return lambda sql, p: (
            sql.startswith("INSERT INTO lifecycle_transitions") and p[0] == target and p[2] == "active"
        )
    return lambda sql, p: sql.startswith("INSERT OR IGNORE INTO identity_mapping") and p[0] == target


async def _a3_call(acm: AgentCapitalService, writer: str, name: str) -> Any:
    if writer == "record":
        return await acm.record_commissioning(
            agent_id=name, agent_type="scout", source="join", role_template=None,
            skills=("communication",), tools=(), reason="BF-906 A3 test",
        )
    if writer == "transition":
        return await acm.transition(name, LifecycleState.ACTIVE, reason="BF-906 A3 test")
    return await acm.onboard(name, "scout", "pool", "science", sovereign_id=f"sov-{name}")


_A3_ORPHANS = {
    "record": (
        "SELECT COUNT(*) FROM commissioning_records r WHERE NOT EXISTS (SELECT 1 FROM "
        "lifecycle_transitions t WHERE t.agent_id = r.agent_id AND t.from_state = t.to_state)"
    ),
    "transition": (
        "SELECT COUNT(*) FROM lifecycle l WHERE l.state = 'active' AND NOT EXISTS (SELECT 1 FROM "
        "lifecycle_transitions t WHERE t.agent_id = l.agent_id AND t.to_state = 'active')"
    ),
    "onboard": (
        "SELECT COUNT(*) FROM lifecycle l WHERE NOT EXISTS (SELECT 1 FROM identity_mapping m "
        "WHERE m.slot_id = l.agent_id)"
    ),
}


async def _a3_settle(gate: _GatedConnection | None, tasks: list[asyncio.Task[Any]]) -> None:
    """Release the gate and end every task still running, so a failing assertion leaves nothing hanging."""
    if gate is not None:
        gate.release.set()
    if tasks:
        await asyncio.wait(tasks, timeout=5)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["record", "transition", "onboard"])
async def test_a_write_section_is_never_committed_in_part_by_another_writer(
    tmp_path: Path, writer: str,
) -> None:
    """U19: while writer B is held inside its section, writer A (and ``stop``) wait; nothing half-written is durable."""
    acm = AgentCapitalService(data_dir=tmp_path)
    await acm.start()
    gate: _GatedConnection | None = None
    tasks: list[asyncio.Task[Any]] = []
    try:
        if writer == "transition":
            await acm.onboard("a", "scout", "pool", "science")
            await acm.onboard("b", "scout", "pool", "science")
        gate = _GatedConnection(acm._db, _a3_key(writer, "b"))
        acm._db = gate

        task_b = asyncio.create_task(_a3_call(acm, writer, "b"))
        tasks.append(task_b)
        await asyncio.wait_for(gate.arrived.wait(), 5)
        task_a = asyncio.create_task(_a3_call(acm, writer, "a"))
        tasks.append(task_a)
        waiting = {task_a}
        stop_task: asyncio.Task[Any] | None = None
        if writer == "record":
            stop_task = asyncio.create_task(acm.stop())
            tasks.append(stop_task)
            waiting.add(stop_task)

        done, _ = await asyncio.wait(waiting, timeout=0.5)

        assert done == set()  # A (and stop) are queued behind B's section
        assert _read_committed(tmp_path, _A3_ORPHANS[writer]) == [(0,)]

        gate.release.set()
        results = await asyncio.gather(*tasks)

        assert _read_committed(tmp_path, _A3_ORPHANS[writer]) == [(0,)]
        if writer == "record":
            assert results[:2] == [True, True]
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM commissioning_records") == [(2,)]
            assert _read_committed(
                tmp_path, "SELECT COUNT(*) FROM lifecycle_transitions WHERE from_state = to_state",
            ) == [(2,)]
        elif writer == "transition":
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM lifecycle WHERE state = 'active'") == [(2,)]
            assert _read_committed(
                tmp_path, "SELECT COUNT(*) FROM lifecycle_transitions WHERE to_state = 'active'",
            ) == [(2,)]
        else:
            assert _read_committed(
                tmp_path, "SELECT COUNT(*) FROM lifecycle WHERE state = 'probationary'",
            ) == [(2,)]
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM identity_mapping") == [(2,)]
    finally:
        await _a3_settle(gate, tasks)
        await acm.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["record", "transition", "onboard"])
async def test_a_failed_write_section_leaves_nothing_pending_and_the_next_call_succeeds(
    tmp_path: Path, writer: str,
) -> None:
    """U20: a write that fails mid-section rolls the section back, so a foreign commit cannot land it."""
    acm = AgentCapitalService(data_dir=tmp_path)
    await acm.start()
    try:
        if writer == "transition":
            await acm.onboard("x", "scout", "pool", "science")
        real = acm._db
        gate = _GatedConnection(real, _a3_key(writer, "x"), mode="fail")
        acm._db = gate

        with pytest.raises(sqlite3.OperationalError, match="injected"):
            await _a3_call(acm, writer, "x")

        assert real.in_transaction is False
        if writer == "record":
            assert await acm.get_commissioning_record("x") is None
        elif writer == "transition":
            assert await acm.get_lifecycle_state("x") is LifecycleState.PROBATIONARY
        else:
            assert await acm.has_lifecycle_record("x") is False

        await acm.onboard("bystander", "scout", "pool", "science")  # a foreign commit

        if writer == "record":
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM commissioning_records WHERE agent_id = 'x'") == [(0,)]
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'x'") == [(0,)]
        elif writer == "transition":
            assert _read_committed(tmp_path, "SELECT state FROM lifecycle WHERE agent_id = 'x'") == [("probationary",)]
            assert _read_committed(
                tmp_path,
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'x' AND to_state = 'active'",
            ) == [(0,)]
        else:
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM lifecycle WHERE agent_id = 'x'") == [(0,)]
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM identity_mapping WHERE slot_id = 'x'") == [(0,)]

        gate.armed = False
        retried = await _a3_call(acm, writer, "x")

        if writer == "record":
            assert retried is True
            assert _read_committed(tmp_path, "SELECT COUNT(*) FROM commissioning_records WHERE agent_id = 'x'") == [(1,)]
            assert _read_committed(
                tmp_path,
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'x' AND from_state = to_state",
            ) == [(1,)]
        elif writer == "transition":
            assert await acm.get_lifecycle_state("x") is LifecycleState.ACTIVE
            assert _read_committed(
                tmp_path,
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'x' AND to_state = 'active'",
            ) == [(1,)]
        else:
            assert await acm.get_lifecycle_state("x") is LifecycleState.PROBATIONARY
            assert _read_committed(
                tmp_path, "SELECT sovereign_id FROM identity_mapping WHERE slot_id = 'x'",
            ) == [("sov-x",)]
            assert _read_committed(
                tmp_path,
                "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'x' "
                "AND from_state = 'registered' AND to_state = 'probationary'",
            ) == [(1,)]
    finally:
        await acm.stop()


@pytest.mark.asyncio
async def test_enroll_a_failed_base_commissioning_step_is_not_recorded_and_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """U21: the chain swallows a failed base step at DEBUG; the enroller records only when every PCC is held.

    The template step still grants its own skills (tactical_debug, diplomacy); the PCCs come only
    from the failed base step, so they are all missing and nothing is recorded until a retry holds them.
    """
    from probos.skill_framework import BUILTIN_PCCS

    templates = _science_templates()
    async with _world(tmp_path, templates=templates) as w:
        async def _refused(*args: Any, **kwargs: Any) -> None:
            raise sqlite3.OperationalError("refused PCC write")

        monkeypatch.setattr(w.service, "commission_agent", _refused)
        ontology = _CrewOntology(
            templates, crew_types={"science_officer"}, departments={"science_officer": "science"},
        )
        event_log = _FakeEventLog()
        service = _enrollment_service(w, ontology, event_log=event_log)
        agent = _FakeAgent("agent-u21", "science_officer", pool="science_pool")

        with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
            first = await service.enroll(agent, source="join")

        assert first is not None
        assert (first.onboarded, first.commissioned) == (True, False)
        assert await w.acm.get_commissioning_record(agent.id) is None
        assert _same_state(await w.acm.get_transition_history(agent.id)) == []
        assert event_log.rows == []
        held = await _held(w.service, agent.id)
        assert held["tactical_debug"].proficiency == ProficiencyLevel.APPLY  # premise: the template step ran
        assert held["diplomacy"].proficiency == ProficiencyLevel.ASSIST
        assert "duty_execution" not in held  # premise: the failed base step left every PCC out
        assert "communication" not in held
        errors = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR
        ]
        assert len(errors) == 1
        assert "BF-906" in errors[0].getMessage()
        assert agent.id in errors[0].getMessage()
        assert "duty_execution" in errors[0].getMessage()

        await w.service.record_exercise(agent.id, "diplomacy")
        await w.service.record_exercise(agent.id, "diplomacy")
        held = await _held(w.service, agent.id)
        assert held["diplomacy"].exercise_count == 2  # premise: a re-acquisition would visibly reset it

        monkeypatch.undo()
        second = await service.enroll(agent, source="join")

        assert second is not None
        assert (second.onboarded, second.commissioned) == (False, True)
        record = await w.acm.get_commissioning_record(agent.id)
        assert record is not None
        assert record.source == "join"
        after = await _held(w.service, agent.id)
        assert {p.skill_id for p in BUILTIN_PCCS} <= set(after)
        assert after["diplomacy"] == held["diplomacy"]  # preserve_existing
        assert after["tactical_debug"] == held["tactical_debug"]
        assert len(event_log.rows) == 1


@pytest.mark.asyncio
async def test_a_cancelled_record_section_leaves_nothing_pending(tmp_path: Path) -> None:
    """U22: cancelling a caller held inside ``record_commissioning`` rolls its record back too."""
    acm = AgentCapitalService(data_dir=tmp_path)
    await acm.start()
    gate: _GatedConnection | None = None
    tasks: list[asyncio.Task[Any]] = []
    try:
        real = acm._db
        gate = _GatedConnection(real, _a3_key("record", "b"))
        acm._db = gate
        task_b = asyncio.create_task(_a3_call(acm, "record", "b"))
        tasks.append(task_b)
        await asyncio.wait_for(gate.arrived.wait(), 5)

        task_b.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task_b

        assert real.in_transaction is False
        assert await acm.get_commissioning_record("b") is None

        gate.armed = False
        assert await _a3_call(acm, "record", "b") is True
        assert _read_committed(tmp_path, "SELECT COUNT(*) FROM commissioning_records WHERE agent_id = 'b'") == [(1,)]
        assert _read_committed(
            tmp_path, "SELECT COUNT(*) FROM lifecycle_transitions WHERE agent_id = 'b' AND from_state = to_state",
        ) == [(1,)]
    finally:
        await _a3_settle(gate, tasks)
        await acm.stop()
