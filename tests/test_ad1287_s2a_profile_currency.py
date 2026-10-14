"""AD-1287 S2a (M2): the live component source, ``profile_drift`` and the currency gate.

Contract: ``prompts/ad-1287-s2a-skill-tool-currency-gate.md``, M2 (17 tests) with D1 and D5-D9.
``RegistryComponentSource`` is exercised over a REAL ``CognitiveSkillCatalog`` (a skills directory under ``tmp_path``)
and a REAL ``ToolRegistry``
holding a ``_SchemaTool``; the gate runs on the real ``ProfileQualificationStore`` and ``ElasticTeamStore`` through
``_World``. ``_FakeSource`` is a hand-written ``ProfileComponentSource`` that answers from two dicts and notes every
question; nothing here uses a mock library. ``_World``, ``_variant`` and ``_FakeTeams`` come from the S1 slot-boundary
tests, ``_evaluation`` from the S1 store tests, ``_profile`` and the authority/import walkers from the M1 tests, and
``_spec`` and ``_attempt`` from AD-1286's contract tests. Source is read with ``read_bytes()`` only.
"""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import logging
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

import probos.cognitive.profile_components as components_module
import probos.cognitive.profile_currency as currency_module
from probos.cognitive.elastic_team import AuthorityCeiling, WorkerAttempt
from probos.cognitive.elastic_team_store import ElasticTeamConflict
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_components import ComponentDigestError, skill_resource_digest, tool_schema_digest
from probos.cognitive.profile_currency import (
    ComponentDrift,
    ComponentUnreadable,
    LiveSkill,
    RegistryComponentSource,
    admit_current_qualified_attempt,
    profile_drift,
)
from probos.cognitive.profile_qualification_store import (
    ProfileQualificationStoreUnavailable,
    SlotAdmissionRefused,
    admit_qualified_attempt,
)
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.tools.protocol import Tool, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from tests.test_ad1286_elastic_team_contract import _attempt, _spec
from tests.test_ad1287_execution_profile import _all_field_names, _authority_named, _probos_imports, _profile
from tests.test_ad1287_profile_qualification_store import _evaluation
from tests.test_ad1287_slot_qualification import _FakeTeams, _World, _variant

_LOGGER = "probos.cognitive.profile_currency"
_CHANGED = "9" * 64  # a digest no fixture declares
_DECLARED_SKILL = "a" * 64  # the fixture profile's digest for code-review
_DECLARED_OTHER_SKILL = "b" * 64  # ... for audit-trail
_DECLARED_TOOL = "c" * 64  # ... and the schema digest of codebase_query
_SKILLS: list[dict[str, Any]] = [
    # declared out of name order on purpose: the profile sorts them, and profile_drift reports in the profile's order
    {"skill_name": "code-review", "resource_digest": _DECLARED_SKILL},
    {"skill_name": "audit-trail", "resource_digest": _DECLARED_OTHER_SKILL},
]
_TOOLS: list[dict[str, Any]] = [
    {"tool_id": "codebase_query", "schema_digest": _DECLARED_TOOL, "implementation_digest": "d" * 64},
]
_CURRENT = object()  # a parametrized answer meaning "leave this component as the profile declares it"

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}
_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {"type": "string"}}},
}
_CHANGED_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "integer"}},
    "required": ["query"],
}

_SKILL_MD = (
    "---\n"
    "name: {name}\n"
    "description: Reviews a change for correctness\n"
    "---\n"
    "\n"
    "## Instructions\n"
    "Review the change against the checklist.\n"
)
_CHECKLIST = b"- every changed line has a reason: A\n"
_CHECKLIST_CHANGED = _CHECKLIST.replace(b"A", b"B")  # exactly one byte differs


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


def _answered(value: Any) -> Any:
    """What a double answers: an exception instance is raised, as a failing source would; anything else is returned."""
    if isinstance(value, BaseException):
        raise value
    return value


class _FakeSource:
    """A ``ProfileComponentSource`` answering from two dicts, noting each question in the order it was asked.

    A name with no entry answers ``None`` (missing); an entry that is an exception instance is raised instead.
    """

    def __init__(self, skills: dict[str, Any], tools: dict[str, Any]) -> None:
        self.skills = skills
        self.tools = tools
        self.skill_questions: list[str] = []
        self.tool_questions: list[str] = []

    async def skill_state(self, skill_name: str) -> Any:
        self.skill_questions.append(skill_name)
        return _answered(self.skills.get(skill_name))

    async def tool_schema_digest(self, tool_id: str) -> Any:
        self.tool_questions.append(tool_id)
        return _answered(self.tools.get(tool_id))


class _SchemaTool:
    """A minimal registrable ``Tool``: a fixed id, the schemas the test chooses and a trivial ``invoke``.

    A schema given as an exception instance is raised when it is read, as a tool whose schema property fails would.
    """

    tool_type = ToolType.DETERMINISTIC_FUNCTION

    def __init__(self, tool_id: str, input_schema: Any, output_schema: Any) -> None:
        self.tool_id = tool_id
        self.name = f"{tool_id} double"
        self.description = f"A test double for {tool_id} with fixed schemas"
        self._input_schema = input_schema
        self._output_schema = output_schema

    @property
    def input_schema(self) -> Any:
        return _answered(self._input_schema)

    @property
    def output_schema(self) -> Any:
        return _answered(self._output_schema)

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output=None)


def _codebase_query_tool(input_schema: Any = None) -> _SchemaTool:
    """A fresh ``codebase_query`` double; ``input_schema`` replaces the default input schema."""
    return _SchemaTool("codebase_query", _INPUT_SCHEMA if input_schema is None else input_schema, _OUTPUT_SCHEMA)


def _registry_source(*tools: _SchemaTool) -> RegistryComponentSource:
    """A source over a registry holding ``tools`` and a catalog that holds no skills (the tool tests never ask it)."""
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return RegistryComponentSource(CognitiveSkillCatalog(), registry)


def _write_skill(skills_dir: Path, directory: str = "code-review", name: str = "code-review") -> Path:
    """``skills_dir/<directory>`` holding ``SKILL.md`` (frontmatter ``name``) and ``references/checklist.md``."""
    skill_dir = skills_dir / directory
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(_SKILL_MD.format(name=name).encode("utf-8"))
    (skill_dir / "references" / "checklist.md").write_bytes(_CHECKLIST)
    return skill_dir


@contextlib.asynccontextmanager
async def _started_catalog(skills_dir: Path) -> AsyncIterator[CognitiveSkillCatalog]:
    """A real catalog that has scanned ``skills_dir``, stopped on exit."""
    catalog = CognitiveSkillCatalog(skills_dir=skills_dir)
    await catalog.start()
    try:
        yield catalog
    finally:
        await catalog.stop()


def _fixture(version: str = "v1") -> ExecutionProfile:
    """A review-slot profile declaring two skills (out of name order) and one tool; ``version`` makes it distinct."""
    return _variant(version, skills=_SKILLS, tools=_TOOLS)


def _fixture_dict(version: str = "v1") -> dict[str, Any]:
    """The same profile as ``_fixture`` in dict form (not yet validated)."""
    return _profile(**{"model.version": version, "skills": _SKILLS, "tools": _TOOLS})


def _current_source(profile: ExecutionProfile) -> _FakeSource:
    """A source reporting every component ``profile`` declares as current: the declared digests, structurally valid."""
    return _FakeSource(
        skills={skill.skill_name: LiveSkill(skill.resource_digest, True) for skill in profile.skills},
        tools={tool.tool_id: tool.schema_digest for tool in profile.tools},
    )


def _skill_drift(code: str, live: str | None) -> ComponentDrift:
    return ComponentDrift("skill", "code-review", code, _DECLARED_SKILL, live)


def _tool_drift(code: str, live: str | None) -> ComponentDrift:
    return ComponentDrift("tool", "codebase_query", code, _DECLARED_TOOL, live)


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    """The records ``probos.cognitive.profile_currency`` emitted at exactly ``level``."""
    return [record for record in caplog.records if record.name == _LOGGER and record.levelno == level]


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    opened = _World(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()  # whichever instances are current: a test that restarted replaced the first pair


async def _qualified(world: _World, profile: ExecutionProfile) -> str:
    """Register ``profile``, record a passing evaluation and return its reference; the reported status is asserted."""
    ref = await world.qualifications.register_profile(profile)
    await world.qualifications.record_evaluation(_evaluation(ref))
    qualification = await world.qualifications.get_qualification(ref)
    assert qualification is not None
    assert qualification.status == "qualified"
    return ref


# --------------------------------------------------------------------------------------
# 1-5. RegistryComponentSource over a real catalog and a real registry
# --------------------------------------------------------------------------------------


async def test_registry_source_reports_live_skill_state(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skills")
    async with _started_catalog(tmp_path / "skills") as catalog:
        entry = catalog.get_entry("code-review")
        assert entry is not None  # premise: the scan filed the directory under its declared name
        assert Path(entry.skill_dir) == skill_dir
        assert (await catalog.validate_skill("code-review")).valid is True  # premise: it passes the catalog's check
        source = RegistryComponentSource(catalog, ToolRegistry())

        state = await source.skill_state("code-review")

        assert state == LiveSkill(skill_resource_digest(skill_dir), True)
        assert state is not None
        assert state.structurally_valid is True
        assert await source.skill_state("no-such-skill") is None
        # the directory is read afresh on every call: one byte changed is a different digest
        (skill_dir / "references" / "checklist.md").write_bytes(_CHECKLIST_CHANGED)
        changed = await source.skill_state("code-review")
        assert changed == LiveSkill(skill_resource_digest(skill_dir), True)
        assert changed != state


async def test_registry_source_reports_structurally_invalid_skill(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path / "skills", directory="code-review-x", name="code-review")
    async with _started_catalog(tmp_path / "skills") as catalog:
        entry = catalog.get_entry("code-review")
        assert entry is not None  # premise: the catalog filed the skill under the name its frontmatter declares
        assert Path(entry.skill_dir) == skill_dir
        validation = await catalog.validate_skill("code-review")
        assert validation.valid is False  # premise: the catalog's own check refuses it ...
        assert any("code-review-x" in error for error in validation.errors)  # ... because of the directory name
        source = RegistryComponentSource(catalog, ToolRegistry())

        state = await source.skill_state("code-review")

        assert state == LiveSkill(skill_resource_digest(skill_dir), False)
        assert state is not None
        assert state.structurally_valid is False


@pytest.mark.parametrize(
    ("fault", "cause_type"),
    [
        pytest.param("byte_limit", ComponentDigestError, id="over_the_byte_limit"),
        pytest.param("directory_deleted", ComponentDigestError, id="directory_deleted_after_the_scan"),
        pytest.param("permission_denied", PermissionError, id="permission_denied"),
    ],
)
async def test_registry_source_unreadable_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fault: str,
    cause_type: type[Exception],
) -> None:
    skill_dir = _write_skill(tmp_path / "skills")
    async with _started_catalog(tmp_path / "skills") as catalog:
        source = RegistryComponentSource(catalog, ToolRegistry())
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            readable = await source.skill_state("code-review")
            assert readable == LiveSkill(skill_resource_digest(skill_dir), True)  # premise: readable before the fault
            assert _records(caplog, logging.WARNING) == []
            if fault == "byte_limit":
                monkeypatch.setattr(components_module, "MAX_SKILL_BYTES", 1)  # SKILL.md alone is longer than this
            elif fault == "directory_deleted":
                shutil.rmtree(skill_dir)  # the catalog still holds the entry it scanned
            else:

                def _denied(directory: Path) -> str:
                    raise PermissionError(13, "access denied")

                monkeypatch.setattr(currency_module, "skill_resource_digest", _denied)

            with pytest.raises(ComponentUnreadable) as raised:
                await source.skill_state("code-review")

    assert type(raised.value) is ComponentUnreadable
    assert raised.value.args == ("code-review",)
    assert type(raised.value.__cause__) is cause_type
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1  # one WARNING, naming the skill and the cause
    assert "code-review" in warnings[0].getMessage()
    assert str(raised.value.__cause__) in warnings[0].getMessage()


async def test_registry_source_reports_tool_schema_digest() -> None:
    source = _registry_source(_codebase_query_tool())
    expected = tool_schema_digest(_INPUT_SCHEMA, _OUTPUT_SCHEMA)
    swapped = tool_schema_digest(_OUTPUT_SCHEMA, _INPUT_SCHEMA)
    assert expected != swapped  # premise: the two schemas differ, so a read that swapped them would show

    digest = await source.tool_schema_digest("codebase_query")

    assert digest == expected
    assert digest != swapped
    assert await source.tool_schema_digest("no_such_tool") is None


@pytest.mark.parametrize(
    ("input_schema", "cause_type"),
    [
        pytest.param(RuntimeError("schema property failed"), RuntimeError, id="input_schema_property_raises"),
        pytest.param([{"type": "string"}], ComponentDigestError, id="input_schema_is_a_list"),
    ],
)
async def test_registry_source_unreadable_tool(
    caplog: pytest.LogCaptureFixture, input_schema: Any, cause_type: type[Exception],
) -> None:
    source = _registry_source(
        _SchemaTool("healthy_tool", _INPUT_SCHEMA, _OUTPUT_SCHEMA),
        _SchemaTool("faulty_tool", input_schema, _OUTPUT_SCHEMA),
    )
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        healthy = await source.tool_schema_digest("healthy_tool")
        assert healthy == tool_schema_digest(_INPUT_SCHEMA, _OUTPUT_SCHEMA)  # premise: the same registry digests fine
        assert _records(caplog, logging.WARNING) == []

        with pytest.raises(ComponentUnreadable) as raised:
            await source.tool_schema_digest("faulty_tool")

    assert type(raised.value) is ComponentUnreadable
    assert raised.value.args == ("faulty_tool",)
    assert type(raised.value.__cause__) is cause_type
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "faulty_tool" in warnings[0].getMessage()
    assert str(raised.value.__cause__) in warnings[0].getMessage()


# --------------------------------------------------------------------------------------
# 6-9. profile_drift
# --------------------------------------------------------------------------------------

_DRIFT_CASES: list[Any] = [
    # (the answer for code-review, the answer for codebase_query, every drift reported); the other two stay current
    pytest.param(_CURRENT, _CURRENT, (), id="current"),
    pytest.param(
        ComponentUnreadable("code-review"), _CURRENT, (_skill_drift("component_unreadable_skill", None),),
        id="skill_unreadable",
    ),
    pytest.param(None, _CURRENT, (_skill_drift("component_missing_skill", None),), id="skill_missing"),
    pytest.param(
        LiveSkill(_DECLARED_SKILL, False), _CURRENT,
        (_skill_drift("component_structurally_invalid_skill", _DECLARED_SKILL),),
        id="skill_structurally_invalid_with_a_matching_digest",
    ),
    pytest.param(
        LiveSkill(_CHANGED, False), _CURRENT, (_skill_drift("component_structurally_invalid_skill", _CHANGED),),
        id="skill_structurally_invalid_and_drifted",
    ),
    pytest.param(
        LiveSkill(_CHANGED, True), _CURRENT, (_skill_drift("component_drift_skill", _CHANGED),), id="skill_drifted",
    ),
    pytest.param(
        _CURRENT, ComponentUnreadable("codebase_query"), (_tool_drift("component_unreadable_tool", None),),
        id="tool_unreadable",
    ),
    pytest.param(_CURRENT, None, (_tool_drift("component_missing_tool", None),), id="tool_missing"),
    pytest.param(
        _CURRENT, _CHANGED, (_tool_drift("component_drift_tool_schema", _CHANGED),), id="tool_drifted",
    ),
]


@pytest.mark.parametrize(("skill_answer", "tool_answer", "expected"), _DRIFT_CASES)
async def test_profile_drift_codes(
    skill_answer: Any, tool_answer: Any, expected: tuple[ComponentDrift, ...],
) -> None:
    profile = _fixture()
    assert await profile_drift(profile, _current_source(profile)) == ()  # premise: nothing has drifted yet
    source = _current_source(profile)
    if skill_answer is not _CURRENT:
        source.skills["code-review"] = skill_answer
    if tool_answer is not _CURRENT:
        source.tools["codebase_query"] = tool_answer

    drifts = await profile_drift(profile, source)

    assert type(drifts) is tuple
    assert drifts == expected


async def test_profile_drift_reports_all_in_profile_order() -> None:
    profile = _fixture()
    # premise: the fixture declares code-review first, and the profile holds the skills by name
    assert [skill["skill_name"] for skill in _SKILLS] == ["code-review", "audit-trail"]
    assert [skill.skill_name for skill in profile.skills] == ["audit-trail", "code-review"]
    assert [tool.tool_id for tool in profile.tools] == ["codebase_query"]
    assert await profile_drift(profile, _current_source(profile)) == ()
    # the answers are listed in the opposite order to the profile's
    source = _FakeSource(
        skills={"code-review": LiveSkill(_CHANGED, True), "audit-trail": LiveSkill("8" * 64, True)},
        tools={"codebase_query": _CHANGED},
    )

    drifts = await profile_drift(profile, source)

    assert [(drift.kind, drift.key) for drift in drifts] == [
        ("skill", "audit-trail"), ("skill", "code-review"), ("tool", "codebase_query"),
    ]
    assert [drift.code for drift in drifts] == [
        "component_drift_skill", "component_drift_skill", "component_drift_tool_schema",
    ]
    assert source.skill_questions == ["audit-trail", "code-review"]  # asked once per component, in the profile's order
    assert source.tool_questions == ["codebase_query"]


_MALFORMED: list[Any] = [
    # (where the malformed value goes, its key, the value, the code)
    pytest.param("skills", "audit-trail", "x", "profile_component_source_invalid", id="skill_answer_is_a_str"),
    pytest.param(
        "skills", "audit-trail", LiveSkill("not-a-digest", True), "profile_component_source_invalid",
        id="skill_digest_is_not_a_sha256",
    ),
    pytest.param(
        "skills", "audit-trail", LiveSkill(_DECLARED_OTHER_SKILL, 1), "profile_component_source_invalid",
        id="skill_validity_is_not_a_bool",
    ),
    pytest.param(
        "tools", "codebase_query", "z" * 64, "profile_component_source_invalid", id="tool_answer_is_not_hex",
    ),
    pytest.param("profile", "", None, "profile_currency_type_invalid", id="profile_is_a_dict"),
]


@pytest.mark.parametrize(("where", "key", "answer", "code"), _MALFORMED)
async def test_profile_drift_refuses_malformed_input(where: str, key: str, answer: Any, code: str) -> None:
    profile = _fixture()
    assert await profile_drift(profile, _current_source(profile)) == ()  # premise: well-formed answers are current
    source = _current_source(profile)
    argument: Any = profile
    if where == "skills":
        source.skills[key] = answer
    elif where == "tools":
        source.tools[key] = answer
    else:
        argument = _fixture_dict()
        assert ExecutionProfile.model_validate(argument) == profile  # premise: a valid profile, only its type is wrong

    with pytest.raises(TypeError) as refused:
        await profile_drift(argument, source)

    assert type(refused.value) is TypeError
    assert refused.value.args == (code,)
    if where == "profile":
        assert (source.skill_questions, source.tool_questions) == ([], [])  # refused before anything was asked


async def test_profile_drift_propagates_other_source_errors() -> None:
    profile = _fixture()
    assert await profile_drift(profile, _current_source(profile)) == ()  # premise: nothing fails, nothing drifts
    skill_failure = RuntimeError("catalog unavailable")
    source = _current_source(profile)
    source.skills["code-review"] = skill_failure

    with pytest.raises(RuntimeError) as skill_raised:
        await profile_drift(profile, source)

    assert skill_raised.value is skill_failure  # the very exception: not a wrapper, not a drift entry
    tool_failure = RuntimeError("registry unavailable")
    source = _current_source(profile)
    source.tools["codebase_query"] = tool_failure

    with pytest.raises(RuntimeError) as tool_raised:
        await profile_drift(profile, source)

    assert tool_raised.value is tool_failure


# --------------------------------------------------------------------------------------
# 10. The chain: real catalog, real registry, real stores, across a restart
# --------------------------------------------------------------------------------------


async def test_chain_real_catalog_and_tool_drift_is_refused_and_restored_profile_admitted_across_restart(
    world: _World, tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = _write_skill(skills_dir)
    checklist = skill_dir / "references" / "checklist.md"
    assert sum(old != new for old, new in zip(_CHECKLIST, _CHECKLIST_CHANGED)) == 1  # premise: one byte differs
    assert len(_CHECKLIST) == len(_CHECKLIST_CHANGED)
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)

    # the digests come from the live objects, through the two ports the source reads
    async with _started_catalog(skills_dir) as first_catalog:
        first_registry = ToolRegistry()
        first_registry.register(_codebase_query_tool())
        entry = first_catalog.get_entry("code-review")
        live_tool = first_registry.get_tool("codebase_query")
        assert entry is not None
        assert live_tool is not None
        assert isinstance(live_tool, Tool)  # premise: a genuine Tool, as the registry holds it
        skill_digest = skill_resource_digest(Path(entry.skill_dir))
        tool_digest = tool_schema_digest(live_tool.input_schema, live_tool.output_schema)
    profile = _variant(
        "v1",
        skills=[{"skill_name": "code-review", "resource_digest": skill_digest}],
        tools=[{"tool_id": "codebase_query", "schema_digest": tool_digest, "implementation_digest": "d" * 64}],
    )
    ref = await world.qualifications.register_profile(profile)
    await world.qualifications.record_evaluation(_evaluation(ref))
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    before = (world.qualifications, world.teams)
    await world.stop()
    await world.start()  # NEW store instances on the same two files; a new catalog and registry follow
    assert world.qualifications is not before[0]
    assert world.teams is not before[1]
    with pytest.raises(ProfileQualificationStoreUnavailable):
        await before[0].get_qualification(ref)  # premise: the first instance is stopped, so it cannot be what answers

    async with _started_catalog(skills_dir) as catalog:
        assert catalog is not first_catalog
        registry = ToolRegistry()
        registry.register(_codebase_query_tool())
        source = RegistryComponentSource(catalog, registry)
        qualification = await world.qualifications.get_qualification(ref)
        assert qualification is not None
        assert qualification.status == "qualified"  # premise: decided from the evaluation the file carried across
        assert qualification.profile == profile
        assert await world.teams.get_team_spec(spec_ref) == spec  # premise: the spec crossed in its file too
        assert (await catalog.validate_skill("code-review")).valid is True  # premise: structurally fine, so only drift
        assert await profile_drift(qualification.profile, source) == ()  # premise: every declared component is current
        assert await world.teams.get_attempt(attempt.worker_attempt_id) is None

        # a tool's schema changes: the new instance's digest is not the one the profile declares
        registry.register(_codebase_query_tool(input_schema=_CHANGED_INPUT_SCHEMA))
        with pytest.raises(SlotAdmissionRefused) as tool_refused:
            await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)
        assert type(tool_refused.value) is SlotAdmissionRefused
        assert tool_refused.value.args == ("component_drift_tool_schema",)
        assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
        registry.register(_codebase_query_tool())
        assert await profile_drift(qualification.profile, source) == ()  # premise: the tool is as declared again

        # one byte of references/checklist.md changes
        checklist.write_bytes(_CHECKLIST_CHANGED)
        live_digest = skill_resource_digest(skill_dir)
        assert live_digest != skill_digest  # premise: the byte changed the directory's digest
        assert await profile_drift(qualification.profile, source) == (
            ComponentDrift("skill", "code-review", "component_drift_skill", skill_digest, live_digest),
        )
        with pytest.raises(SlotAdmissionRefused) as refused:
            await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

        assert type(refused.value) is SlotAdmissionRefused
        assert refused.value.args == ("component_drift_skill",)
        assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
        still = await world.qualifications.get_qualification(ref)
        assert still is not None
        assert still.status == "qualified"  # S1 still says qualified: only the currency gate refused
        assert still.invalidation_reasons == ()  # and nothing was recorded against the profile (D6)

        checklist.write_bytes(_CHECKLIST)  # the file is restored byte for byte
        admitted = await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

        assert admitted == attempt
        stored = await world.teams.get_attempt(attempt.worker_attempt_id)
        assert stored is not None
        assert stored.execution_profile_ref == ref


# --------------------------------------------------------------------------------------
# 11-15, 17. The gate
# --------------------------------------------------------------------------------------

_GATE_REFUSALS: list[Any] = [
    # (the code, spec stored, profile evaluated, the answer for code-review, the answer for codebase_query)
    pytest.param("slot_spec_unknown", False, True, _CURRENT, _CURRENT, id="slot_spec_unknown"),
    pytest.param("profile_status_unevaluated", True, False, _CURRENT, _CURRENT, id="profile_status_unevaluated"),
    pytest.param(
        "component_unreadable_skill", True, True, ComponentUnreadable("code-review"), _CURRENT, id="skill_unreadable",
    ),
    pytest.param("component_missing_skill", True, True, None, _CURRENT, id="skill_missing"),
    pytest.param(
        "component_structurally_invalid_skill", True, True, LiveSkill(_DECLARED_SKILL, False), _CURRENT,
        id="skill_structurally_invalid",
    ),
    pytest.param("component_drift_skill", True, True, LiveSkill(_CHANGED, True), _CURRENT, id="skill_drifted"),
    pytest.param(
        "component_unreadable_tool", True, True, _CURRENT, ComponentUnreadable("codebase_query"),
        id="tool_unreadable",
    ),
    pytest.param("component_missing_tool", True, True, _CURRENT, None, id="tool_missing"),
    pytest.param("component_drift_tool_schema", True, True, _CURRENT, _CHANGED, id="tool_drifted"),
]


@pytest.mark.parametrize(("code", "spec_stored", "evaluated", "skill_answer", "tool_answer"), _GATE_REFUSALS)
async def test_gate_refusal_codes(
    world: _World,
    caplog: pytest.LogCaptureFixture,
    code: str,
    spec_stored: bool,
    evaluated: bool,
    skill_answer: Any,
    tool_answer: Any,
) -> None:
    spec = _spec()
    profile = _fixture()
    ref = await world.qualifications.register_profile(profile)
    if evaluated:
        await world.qualifications.record_evaluation(_evaluation(ref))
    if spec_stored:
        await world.teams.put_team_spec(spec)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)
    assert await profile_drift(profile, _current_source(profile)) == ()  # premise: nothing has drifted yet
    source = _current_source(profile)
    if skill_answer is not _CURRENT:
        source.skills["code-review"] = skill_answer
    if tool_answer is not _CURRENT:
        source.tools["codebase_query"] = tool_answer

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        with pytest.raises(SlotAdmissionRefused) as refused:
            await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == (code,)
    refusals = [record.getMessage() for record in _records(caplog, logging.INFO)]
    assert len(refusals) == 1  # one INFO record, naming the profile and the code
    assert ref in refusals[0]
    assert code in refusals[0]
    assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
    # control: repair only what was wrong and the same attempt is admitted, so nothing else was refusing it
    if not spec_stored:
        await world.teams.put_team_spec(spec)
    if not evaluated:
        await world.qualifications.record_evaluation(_evaluation(ref))
    admitted = await admit_current_qualified_attempt(
        world.qualifications, world.teams, _current_source(profile), attempt,
    )
    assert admitted == attempt
    assert await world.teams.get_attempt(attempt.worker_attempt_id) == attempt


async def test_gate_reads_components_only_for_a_qualified_profile(world: _World) -> None:
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)
    profile = _fixture()
    ref = await world.qualifications.register_profile(profile)  # registered and never evaluated
    unevaluated = await world.qualifications.get_qualification(ref)
    assert unevaluated is not None
    assert unevaluated.status == "unevaluated"  # premise: S1 does not qualify it
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    # premise: a source that answers nothing reports every component missing, so the profile is drifted
    missing = await profile_drift(profile, _FakeSource({}, {}))
    assert {drift.code for drift in missing} == {"component_missing_skill", "component_missing_tool"}
    source = _FakeSource({}, {})

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

    assert refused.value.args == ("profile_status_unevaluated",)  # S1's code, not a component code
    assert (source.skill_questions, source.tool_questions) == ([], [])  # the source was never asked
    # control: once qualified, the same source is asked about every component and the drift is what refuses
    await world.qualifications.record_evaluation(_evaluation(ref))
    with pytest.raises(SlotAdmissionRefused) as drifted:
        await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)
    assert drifted.value.args == ("component_missing_skill",)
    assert source.skill_questions == ["audit-trail", "code-review"]
    assert source.tool_questions == ["codebase_query"]
    assert await world.teams.get_attempt(attempt.worker_attempt_id) is None


async def test_gate_refuses_a_non_attempt(world: _World) -> None:
    spec = _spec()
    profile = _fixture()
    ref = await _qualified(world, profile)
    teams = _FakeTeams(spec)
    source = _current_source(profile)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)
    as_dict = attempt.model_dump()
    # premise: the dict is a valid attempt, so only its type is wrong
    assert WorkerAttempt.model_validate(as_dict) == attempt

    for wrong in (as_dict, None):
        with pytest.raises(TypeError) as refused:
            await admit_current_qualified_attempt(world.qualifications, teams, source, wrong)

        assert type(refused.value) is TypeError
        assert refused.value.args == ("elastic_attempt_type_invalid",)
    assert teams.spec_lookups == []  # refused before anything was looked up, read or recorded
    assert teams.recorded == []
    assert (source.skill_questions, source.tool_questions) == ([], [])
    # control: the real attempt passes the same gate and is recorded
    assert await admit_current_qualified_attempt(world.qualifications, teams, source, attempt) == attempt
    assert teams.recorded == [attempt]


async def test_record_attempt_errors_propagate(world: _World) -> None:
    spec = _spec()
    profile = _fixture()
    ref = await _qualified(world, profile)
    failure = ElasticTeamConflict("elastic_attempt_budget_exhausted")
    teams = _FakeTeams(spec, record_error=failure)
    attempt = _attempt(team_spec_ref=spec.content_ref(), slot_id="review", execution_profile_ref=ref)

    with pytest.raises(ElasticTeamConflict) as raised:
        await admit_current_qualified_attempt(world.qualifications, teams, _current_source(profile), attempt)

    assert teams.recorded == [attempt]  # premise: the gate admitted the attempt and handed it on, once
    assert raised.value is failure  # the very exception, not a wrapper or a copy
    assert raised.value.args == ("elastic_attempt_budget_exhausted",)


async def test_s1_gate_alone_still_admits_a_drifted_profile(world: _World, tmp_path: Path) -> None:
    second_directory = tmp_path / "second-world"
    second_directory.mkdir()
    second = _World(second_directory)  # R-4: the two gates run on separate stores holding the same state
    await second.start()
    try:
        spec = _spec()
        spec_ref = await world.teams.put_team_spec(spec)
        assert await second.teams.put_team_spec(spec) == spec_ref
        profile = _fixture()
        ref = await _qualified(world, profile)
        assert await _qualified(second, profile) == ref  # premise: the same qualified profile on both
        attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
        source = _current_source(profile)
        assert await profile_drift(profile, source) == ()  # premise: current ...
        source.skills["code-review"] = LiveSkill(_CHANGED, True)  # ... until the skill changes
        assert [drift.code for drift in await profile_drift(profile, source)] == ["component_drift_skill"]

        admitted = await admit_qualified_attempt(world.qualifications, world.teams, attempt)  # S1: no currency check
        with pytest.raises(SlotAdmissionRefused) as refused:
            await admit_current_qualified_attempt(second.qualifications, second.teams, source, attempt)

        assert admitted == attempt
        stored = await world.teams.get_attempt(attempt.worker_attempt_id)
        assert stored is not None
        assert stored.execution_profile_ref == ref  # S1 recorded the attempt for the drifted profile
        assert type(refused.value) is SlotAdmissionRefused
        assert refused.value.args == ("component_drift_skill",)  # S2a refused the same state
        assert await second.teams.get_attempt(attempt.worker_attempt_id) is None
    finally:
        await second.stop()


async def test_replay_after_drift_is_refused(world: _World) -> None:
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)
    profile = _fixture()
    ref = await _qualified(world, profile)
    source = _current_source(profile)
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    first = await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)
    assert first == attempt  # premise: admitted while every component was current
    # premise: while they still are, an identical replay is acknowledged
    assert await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt) == first
    source.skills["code-review"] = LiveSkill(_CHANGED, True)  # the skill changes after the attempt was recorded

    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("component_drift_skill",)
    assert await world.teams.get_attempt(attempt.worker_attempt_id) == first  # the first record is still there


# --------------------------------------------------------------------------------------
# 16. Authority and import boundaries
# --------------------------------------------------------------------------------------

_ALLOWED_PROBOS_IMPORTS = {
    "probos.cognitive.elastic_team",
    "probos.cognitive.execution_profile",
    "probos.cognitive.profile_components",
    "probos.cognitive.profile_qualification_store",
}


def test_no_authority_fields_and_imports_allowlisted() -> None:
    names = {field.name for live_type in (LiveSkill, ComponentDrift) for field in dataclasses.fields(live_type)}

    # the walk reaches both types (a walk that found nothing would pass vacuously)
    assert {"resource_digest", "structurally_valid", "kind", "key", "code", "declared", "live"} <= names
    assert _authority_named(names) == set()
    # negative control: the same words flag AD-1286's AuthorityCeiling
    assert "tool_scopes" in _authority_named(_all_field_names(AuthorityCeiling))
    imported = _probos_imports(ast.parse(Path(currency_module.__file__).read_bytes()))
    assert imported == _ALLOWED_PROBOS_IMPORTS  # never probos.tools or skill_catalog: it depends on the ports
    # negative controls: the helper sees each module D8 forbids, whatever the form or depth of the import
    assert _probos_imports(ast.parse("import probos.tools.registry")) == {"probos.tools.registry"}
    assert _probos_imports(ast.parse("from probos.cognitive.skill_catalog import CognitiveSkillCatalog")) == {
        "probos.cognitive.skill_catalog"
    }
    assert _probos_imports(ast.parse("def late():\n    from probos.tools import registry\n")) == {"probos.tools"}
