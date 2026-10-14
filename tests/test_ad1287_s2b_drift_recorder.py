"""AD-1287 S2b M1: the drift recorder (``profile_drift_recorder``), tested against the installed source.

Numbered as the build contract's M1 list numbers them:

 1. the invalidation id's known answer        2. the id binds every field
 3. the id refuses bad input                  4. skill and tool drift are recorded
 5. a structurally invalid skill is recorded  6. missing / unreadable are not recorded
 7. a mixed answer records the read ones      8. a current profile records nothing
 9. a non-qualified profile is untouched      10. unknown and malformed references
11. the store's answer is checked             12. a stale replay writes nothing new
13. the same drift after a requalification    14. errors propagate
15. the chain on real stores                  16. imports allowlisted, module unwired
17. a duplicate replay spares a later E2      18. a partial failure, then a rerun

Doubles are hand-written ``_Fake*`` classes (no mock library). The real stores come from ``_World`` (S1's slot-boundary
tests), the real catalog and registry from S2a's helpers. Every test asserts its own premise first, so a setup that
never reached the boundary under test fails loudly instead of passing.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

import probos.cognitive.profile_drift_recorder as recorder_module
from probos.cognitive.elastic_team import ElasticId
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_components import skill_resource_digest, tool_schema_digest
from probos.cognitive.profile_currency import (
    ComponentDrift,
    ComponentUnreadable,
    LiveSkill,
    RegistryComponentSource,
    admit_current_qualified_attempt,
    profile_drift,
)
from probos.cognitive.profile_drift_recorder import drift_invalidation_id, record_component_drift
from probos.cognitive.profile_qualification_store import (
    ProfileQualification,
    ProfileQualificationConflict,
    ProfileQualificationStore,
    ProfileQualificationStoreUnavailable,
    RecordedInvalidation,
    SlotAdmissionRefused,
)
from probos.federation.ard import jcs
from probos.tools.protocol import Tool
from probos.tools.registry import ToolRegistry
from tests.test_ad1286_elastic_team_contract import _attempt, _spec
from tests.test_ad1287_execution_profile import _probos_imports
from tests.test_ad1287_profile_qualification_store import _evaluation, _rows
from tests.test_ad1287_s2a_profile_currency import (
    _CHANGED,
    _CHECKLIST,
    _CHECKLIST_CHANGED,
    _DECLARED_SKILL,
    _DECLARED_TOOL,
    _SKILLS,
    _TOOLS,
    _FakeSource,
    _codebase_query_tool,
    _current_source,
    _fixture,
    _qualified,
    _started_catalog,
    _write_skill,
)
from tests.test_ad1287_slot_qualification import (
    _GATE_NAMES,
    _NON_QUALIFIED,
    _S1_MODULES,
    _World,
    _in_state,
    _variant,
)

_LOGGER = "probos.cognitive.profile_drift_recorder"
_DOMAIN = b"probos.execution_profile/drift_invalidation/v1\x00"  # written out here, never read from the module
_PROFILE_REF = "1" * 64
_EVIDENCE_REF = "2" * 64
# the two drifts S2a's ``_fixture`` profile shows once code-review's resources and codebase_query's schemas have
# changed to ``_CHANGED`` (the skill is structurally valid)
_SKILL_DRIFT = ComponentDrift("skill", "code-review", "component_drift_skill", _DECLARED_SKILL, _CHANGED)
_TOOL_DRIFT = ComponentDrift("tool", "codebase_query", "component_drift_tool_schema", _DECLARED_TOOL, _CHANGED)
_COMPONENT_KEYS = {"skill": "code-review", "tool": "codebase_query"}
_ALLOWED_PROBOS_IMPORTS = {
    "probos.cognitive.elastic_team",
    "probos.cognitive.profile_currency",
    "probos.cognitive.profile_qualification_store",
}


# --------------------------------------------------------------------------------------
# Test doubles and helpers
# --------------------------------------------------------------------------------------


class _FakeStore:
    """A ``DriftInvalidationStore`` answering from what a test gives it, and noting each call in the order made.

    ``get_qualification`` answers ``answer`` whatever it is asked. ``invalidate_profile`` answers the
    ``RecordedInvalidation`` its arguments describe (sequence 1, 2, ... in call order), or raises ``failures[n]`` on
    its n-th call (counted from 1).
    """

    def __init__(
        self, answer: ProfileQualification | None, failures: dict[int, BaseException] | None = None,
    ) -> None:
        self.answer = answer
        self.failures = {} if failures is None else failures
        self.calls: list[tuple[str, ...]] = []

    @property
    def writes(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == "invalidate_profile"]

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        self.calls.append(("get_qualification", profile_ref))
        return self.answer

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation:
        self.calls.append(("invalidate_profile", profile_ref, invalidation_id, reason_code))
        attempt = len(self.writes)
        if attempt in self.failures:
            raise self.failures[attempt]
        return RecordedInvalidation(profile_ref, invalidation_id, reason_code, attempt, 1_000_000)


class _StaleStore:
    """A ``DriftInvalidationStore`` whose read is out of date: ``get_qualification`` answers a qualification a test
    captured earlier, while ``invalidate_profile`` is the real store's. It is what a second recorder holds when it
    read before the first one wrote (a concurrent recorder holding the same evaluation).
    """

    def __init__(self, real: ProfileQualificationStore, stale: ProfileQualification) -> None:
        self._real = real
        self._stale = stale
        self.reads = 0

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        self.reads += 1
        return self._stale

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation:
        return await self._real.invalidate_profile(profile_ref, invalidation_id, reason_code)


class _FailSecondWrite:
    """A ``DriftInvalidationStore`` over the real store: reads and the first write pass through to it, and the second
    ``invalidate_profile`` raises ``error`` before it reaches the store, so nothing of that write is stored. Each write
    is noted as ``(profile_ref, invalidation_id, reason_code)``.
    """

    def __init__(self, real: ProfileQualificationStore, error: BaseException) -> None:
        self._real = real
        self._error = error
        self.writes: list[tuple[str, str, str]] = []

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None:
        return await self._real.get_qualification(profile_ref)

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation:
        self.writes.append((profile_ref, invalidation_id, reason_code))
        if len(self.writes) == 2:
            raise self._error
        return await self._real.invalidate_profile(profile_ref, invalidation_id, reason_code)


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    opened = _World(tmp_path)
    await opened.start()
    try:
        yield opened
    finally:
        await opened.stop()  # whichever instances are current: a test that restarted replaced the first pair


async def _read(store: ProfileQualificationStore, profile_ref: str) -> ProfileQualification:
    """The store's answer for a registered profile (asserted to exist)."""
    qualification = await store.get_qualification(profile_ref)
    assert qualification is not None
    return qualification


def _invalidation_rows(directory: Path, profile_ref: str) -> list[dict[str, Any]]:
    """``profile_ref``'s invalidation rows, oldest first, read straight from the qualification file ``_World`` keeps in
    ``directory`` (the store has no call that lists them)."""
    rows = _rows(directory / "profile_qualifications.db", "profile_invalidations")
    return sorted((row for row in rows if row["profile_ref"] == profile_ref), key=lambda row: row["seq"])


def _drifted_source(profile: ExecutionProfile) -> _FakeSource:
    """A source reporting code-review changed (a recordable drift) and every other component current."""
    source = _current_source(profile)
    source.skills["code-review"] = LiveSkill(_CHANGED, True)
    return source


def _both_drifted(profile: ExecutionProfile) -> _FakeSource:
    """A fresh source reporting code-review and codebase_query both changed: two recordable drifts, skill then tool."""
    source = _drifted_source(profile)
    source.tools["codebase_query"] = _CHANGED
    return source


def _not_read(profile: ExecutionProfile, kind: str, mode: str) -> _FakeSource:
    """A current source except one component: ``missing`` (answers None) or ``unreadable`` (raises)."""
    source = _current_source(profile)
    key = _COMPONENT_KEYS[kind]
    answer = None if mode == "missing" else ComponentUnreadable(key)
    (source.skills if kind == "skill" else source.tools)[key] = answer
    return source


def _asked(source: _FakeSource) -> tuple[list[str], list[str]]:
    """The skills, then the tools, the source was asked about."""
    return source.skill_questions, source.tool_questions


def _recorder_records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    """The records ``probos.cognitive.profile_drift_recorder`` emitted at exactly ``level``."""
    return [record for record in caplog.records if record.name == _LOGGER and record.levelno == level]


def _known_answer(profile_ref: str, evidence_ref: str, drift: ComponentDrift) -> str:
    """The id D4 defines, built from the literal domain bytes and the RFC 8785 canonicaliser, not from the module."""
    material = {
        "code": drift.code,
        "evidence_ref": evidence_ref,
        "key": drift.key,
        "kind": drift.kind,
        "live": drift.live,
        "profile_ref": profile_ref,
    }
    return "drift-" + hashlib.sha256(_DOMAIN + jcs.canonicalize(material)).hexdigest()


# --------------------------------------------------------------------------------------
# 1-3. The invalidation id
# --------------------------------------------------------------------------------------


def test_drift_invalidation_id_known_answer() -> None:
    # premise: the six fields, as RFC 8785 writes them (members sorted by name, no whitespace), are what gets hashed
    canonical = jcs.canonicalize(
        {
            "profile_ref": _PROFILE_REF,
            "evidence_ref": _EVIDENCE_REF,
            "kind": "skill",
            "key": "code-review",
            "code": "component_drift_skill",
            "live": _CHANGED,
        }
    )
    assert canonical == (
        b'{"code":"component_drift_skill","evidence_ref":"' + _EVIDENCE_REF.encode() + b'","key":"code-review",'
        b'"kind":"skill","live":"' + _CHANGED.encode() + b'","profile_ref":"' + _PROFILE_REF.encode() + b'"}'
    )
    expected = "drift-" + hashlib.sha256(b"probos.execution_profile/drift_invalidation/v1\x00" + canonical).hexdigest()

    produced = drift_invalidation_id(_PROFILE_REF, _EVIDENCE_REF, _SKILL_DRIFT)

    assert produced == expected
    assert len(produced) == 70
    assert TypeAdapter(ElasticId).validate_python(produced) == produced
    # negative control: the adapter does refuse a string that is not an id, so accepting this one means something
    with pytest.raises(ValidationError):
        TypeAdapter(ElasticId).validate_python("drift/" + "0" * 64)
    # a second vector, a tool drift: the kind, key and code are part of what is hashed
    tool_expected = _known_answer(_PROFILE_REF, _EVIDENCE_REF, _TOOL_DRIFT)
    assert drift_invalidation_id(_PROFILE_REF, _EVIDENCE_REF, _TOOL_DRIFT) == tool_expected
    assert tool_expected != expected


# one input changed per case, the rest as the base: (profile_ref, evidence_ref, drift)
_ONE_CHANGED: dict[str, tuple[str, str, ComponentDrift]] = {
    "profile_ref": ("3" * 64, _EVIDENCE_REF, _SKILL_DRIFT),
    "evidence_ref": (_PROFILE_REF, "4" * 64, _SKILL_DRIFT),
    "kind": (_PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT, kind="tool")),
    "key": (_PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT, key="audit-trail")),
    "code": (
        _PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT, code="component_structurally_invalid_skill"),
    ),
    "live": (_PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT, live="8" * 64)),
}


@pytest.mark.parametrize("field", list(_ONE_CHANGED))
def test_drift_invalidation_id_binds_every_field(field: str) -> None:
    profile_ref, evidence_ref, drift = _ONE_CHANGED[field]
    differs = {
        "profile_ref": profile_ref != _PROFILE_REF,
        "evidence_ref": evidence_ref != _EVIDENCE_REF,
        "kind": drift.kind != _SKILL_DRIFT.kind,
        "key": drift.key != _SKILL_DRIFT.key,
        "code": drift.code != _SKILL_DRIFT.code,
        "live": drift.live != _SKILL_DRIFT.live,
    }
    assert differs == {name: name == field for name in differs}  # premise: this case changes that input, no other
    assert drift.declared == _SKILL_DRIFT.declared  # ... and leaves `declared` alone (it is not an input, D4)
    base = drift_invalidation_id(_PROFILE_REF, _EVIDENCE_REF, _SKILL_DRIFT)

    # the same inputs twice give one id, even through a second, equal ComponentDrift object
    assert drift_invalidation_id(_PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT)) == base
    assert drift_invalidation_id(profile_ref, evidence_ref, drift) != base


_BAD_ID_INPUTS: list[Any] = [
    pytest.param("not-a-sha256", _EVIDENCE_REF, _SKILL_DRIFT, id="bad_profile_ref"),
    pytest.param(_PROFILE_REF, "not-a-sha256", _SKILL_DRIFT, id="bad_evidence_ref"),
    pytest.param(_PROFILE_REF, _EVIDENCE_REF, dataclasses.replace(_SKILL_DRIFT, live=None), id="live_is_none"),
    pytest.param(_PROFILE_REF, _EVIDENCE_REF, dataclasses.asdict(_SKILL_DRIFT), id="dict_in_place_of_drift"),
]


@pytest.mark.parametrize(("profile_ref", "evidence_ref", "drift"), _BAD_ID_INPUTS)
def test_drift_invalidation_id_refuses_bad_input(profile_ref: Any, evidence_ref: Any, drift: Any) -> None:
    good = drift_invalidation_id(_PROFILE_REF, _EVIDENCE_REF, _SKILL_DRIFT)
    assert good.startswith("drift-")  # premise: unspoiled inputs are accepted, so only this case's input refuses

    with pytest.raises(TypeError) as refused:
        drift_invalidation_id(profile_ref, evidence_ref, drift)

    assert type(refused.value) is TypeError
    assert refused.value.args == ("drift_invalidation_input_invalid",)


# --------------------------------------------------------------------------------------
# 4-8. What is recorded, and what is not
# --------------------------------------------------------------------------------------


async def test_records_skill_and_tool_drift_as_invalidations(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    before = await _read(world.qualifications, ref)
    assert before.status == "qualified"  # premise
    assert before.deciding is not None
    source = _drifted_source(profile)
    source.tools["codebase_query"] = _CHANGED
    expected = (_SKILL_DRIFT, _TOOL_DRIFT)
    assert await profile_drift(profile, source) == expected  # premise: these two drifts, skill then tool, nothing else

    recorded = await record_component_drift(world.qualifications, source, ref)

    assert type(recorded) is tuple
    assert [type(item) for item in recorded] == [RecordedInvalidation, RecordedInvalidation]
    assert [item.invalidation_id for item in recorded] == [
        drift_invalidation_id(ref, before.deciding.evidence_ref, drift) for drift in expected
    ]
    assert [item.reason_code for item in recorded] == ["component_drift_skill", "component_drift_tool_schema"]
    assert [item.profile_ref for item in recorded] == [ref, ref]
    assert recorded[0].seq < recorded[1].seq
    after = await _read(world.qualifications, ref)
    assert after.status == "invalidated"
    assert after.invalidation_reasons == ("component_drift_skill", "component_drift_tool_schema")


async def test_records_structurally_invalid_skill(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    before = await _read(world.qualifications, ref)
    assert before.status == "qualified"  # premise
    assert before.deciding is not None
    source = _current_source(profile)
    source.skills["code-review"] = LiveSkill(_DECLARED_SKILL, False)  # the bytes are as declared; validate_skill fails
    invalid = ComponentDrift(
        "skill", "code-review", "component_structurally_invalid_skill", _DECLARED_SKILL, _DECLARED_SKILL,
    )
    assert await profile_drift(profile, source) == (invalid,)  # premise: one drift, and it is the structural one

    recorded = await record_component_drift(world.qualifications, source, ref)

    assert len(recorded) == 1
    assert recorded[0].reason_code == "component_structurally_invalid_skill"
    assert recorded[0].invalidation_id == drift_invalidation_id(ref, before.deciding.evidence_ref, invalid)
    after = await _read(world.qualifications, ref)
    assert after.status == "invalidated"
    assert after.invalidation_reasons == ("component_structurally_invalid_skill",)


_NOT_RECORDED: list[Any] = [
    pytest.param("component_missing_skill", "skill", "missing", id="skill_missing"),
    pytest.param("component_unreadable_skill", "skill", "unreadable", id="skill_unreadable"),
    pytest.param("component_missing_tool", "tool", "missing", id="tool_missing"),
    pytest.param("component_unreadable_tool", "tool", "unreadable", id="tool_unreadable"),
]


@pytest.mark.parametrize(("code", "kind", "mode"), _NOT_RECORDED)
async def test_missing_and_unreadable_are_not_recorded(
    world: _World, caplog: pytest.LogCaptureFixture, code: str, kind: str, mode: str,
) -> None:
    spec_ref = await world.teams.put_team_spec(_spec())
    profile = _fixture()
    ref = await _qualified(world, profile)
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    # premise: this component is the only drift, and it is the unrecorded kind
    assert [drift.code for drift in await profile_drift(profile, _not_read(profile, kind, mode))] == [code]
    source = _not_read(profile, kind, mode)

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        recorded = await record_component_drift(world.qualifications, source, ref)

    assert recorded == ()
    after = await _read(world.qualifications, ref)
    assert after.status == "qualified"
    assert after.invalidation_reasons == ()
    infos = _recorder_records(caplog, logging.INFO)
    assert len(infos) == 1  # one INFO record from the recorder's own logger, naming the profile and the code
    assert code in infos[0].getMessage()
    assert ref in infos[0].getMessage()
    # cross-check (D5): nothing was recorded, so it is the slot boundary that still refuses this profile, by that code
    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)
    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == (code,)
    assert await world.teams.get_attempt(attempt.worker_attempt_id) is None


async def test_mixed_drift_records_only_the_read_ones(world: _World, caplog: pytest.LogCaptureFixture) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    before = await _read(world.qualifications, ref)
    assert before.status == "qualified"  # premise
    assert before.deciding is not None
    source = _not_read(profile, "skill", "missing")
    source.tools["codebase_query"] = _CHANGED
    assert [drift.code for drift in await profile_drift(profile, source)] == [  # premise: one of each kind of answer
        "component_missing_skill",
        "component_drift_tool_schema",
    ]

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        recorded = await record_component_drift(world.qualifications, source, ref)

    assert [item.reason_code for item in recorded] == ["component_drift_tool_schema"]
    assert recorded[0].invalidation_id == drift_invalidation_id(ref, before.deciding.evidence_ref, _TOOL_DRIFT)
    infos = _recorder_records(caplog, logging.INFO)
    assert len(infos) == 1  # the missing skill, logged and not recorded
    assert "component_missing_skill" in infos[0].getMessage()
    after = await _read(world.qualifications, ref)
    assert after.status == "invalidated"
    assert after.invalidation_reasons == ("component_drift_tool_schema",)


async def test_current_profile_records_nothing(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    assert await profile_drift(profile, _current_source(profile)) == ()  # premise: every component is current
    source = _current_source(profile)  # a fresh one: its questions are what this test counts

    recorded = await record_component_drift(world.qualifications, source, ref)

    assert recorded == ()
    after = await _read(world.qualifications, ref)
    assert after.status == "qualified"
    assert after.invalidation_reasons == ()
    assert _asked(source) == (["audit-trail", "code-review"], ["codebase_query"])  # once per component


# --------------------------------------------------------------------------------------
# 9-11. Which profiles, and which store answers, it acts on
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", _NON_QUALIFIED)
async def test_non_qualified_profile_is_not_read_or_written(world: _World, state: str) -> None:
    ref = await _in_state(world, state, "v1", skills=_SKILLS, tools=_TOOLS)  # asserts the reported status is `state`
    before = await _read(world.qualifications, ref)
    assert before.status == state
    assert before.status != "qualified"  # premise
    profile = before.profile
    # premise: a source reporting a recordable drift, so a recorder that read it would also write it
    assert await profile_drift(profile, _drifted_source(profile)) == (_SKILL_DRIFT,)
    source = _drifted_source(profile)

    recorded = await record_component_drift(world.qualifications, source, ref)

    assert recorded == ()
    assert _asked(source) == ([], [])  # the components were never read
    after = await _read(world.qualifications, ref)
    assert after.status == before.status
    assert after.invalidation_reasons == before.invalidation_reasons


async def test_unknown_and_malformed_references(world: _World) -> None:
    profile = _fixture()
    await _qualified(world, profile)  # the store holds a profile, so only the reference below is unknown
    unregistered = "5" * 64
    assert await world.qualifications.get_qualification(unregistered) is None  # premise: a well-formed, unknown ref
    source = _drifted_source(profile)

    with pytest.raises(ProfileQualificationConflict) as unknown:
        await record_component_drift(world.qualifications, source, unregistered)

    assert type(unknown.value) is ProfileQualificationConflict
    assert unknown.value.args == ("profile_unknown",)
    assert _asked(source) == ([], [])
    # premise: the fake notes the question a well-formed reference puts to it, so "never asked" below is a real finding
    asked_store = _FakeStore(None)
    with pytest.raises(ProfileQualificationConflict):
        await record_component_drift(asked_store, _drifted_source(profile), unregistered)
    assert asked_store.calls == [("get_qualification", unregistered)]

    store = _FakeStore(None)
    malformed_source = _drifted_source(profile)
    with pytest.raises(ValueError) as malformed:
        await record_component_drift(store, malformed_source, "x")

    assert type(malformed.value) is ValueError  # exactly ValueError: not the store's conflict, which subclasses it
    assert malformed.value.args == ("execution_profile_ref_invalid",)
    assert store.calls == []
    assert _asked(malformed_source) == ([], [])


async def test_store_answer_checks(world: _World) -> None:
    profile = _fixture("v1")
    other_profile = _fixture("v2")
    ref = await _qualified(world, profile)
    other_ref = await _qualified(world, other_profile)
    assert ref != other_ref  # premise: two profiles
    qualification = await _read(world.qualifications, ref)
    other_qualification = await _read(world.qualifications, other_ref)
    assert qualification.status == "qualified"  # premise: the real answer would be acted on, drift and all
    assert qualification.deciding is not None
    assert await profile_drift(profile, _drifted_source(profile)) == (_SKILL_DRIFT,)

    # the store answers for another profile: once with another profile's label, once with another profile's body
    wrong_label = dataclasses.replace(qualification, profile_ref=other_ref)
    wrong_body = dataclasses.replace(qualification, profile=other_qualification.profile)
    assert (wrong_label.profile_ref, wrong_label.profile.content_ref()) == (other_ref, ref)  # premise: only the label
    assert (wrong_body.profile_ref, wrong_body.profile.content_ref()) == (ref, other_ref)  # premise: only the body
    for shape, answer in (("wrong label", wrong_label), ("wrong body", wrong_body)):
        store = _FakeStore(answer)
        source = _drifted_source(profile)

        with pytest.raises(ValueError) as mismatch:
            await record_component_drift(store, source, ref)

        assert type(mismatch.value) is ValueError, shape
        assert mismatch.value.args == ("profile_evidence_mismatch",), shape
        assert store.calls == [("get_qualification", ref)], shape  # the one read, and no invalidate_profile call
        assert _asked(source) == ([], []), shape  # the source was not asked

    # qualified with no deciding evaluation is treated as not qualified: nothing to read, nothing to write
    no_evidence = dataclasses.replace(qualification, deciding=None)
    assert no_evidence.status == "qualified"  # premise: the status alone would have sent it on to read the source
    store = _FakeStore(no_evidence)
    source = _drifted_source(profile)

    assert await record_component_drift(store, source, ref) == ()

    assert store.calls == [("get_qualification", ref)]
    assert _asked(source) == ([], [])


# --------------------------------------------------------------------------------------
# 12-14. Replay, requalification and failure
# --------------------------------------------------------------------------------------


async def test_stale_replay_writes_nothing_new(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    captured = await _read(world.qualifications, ref)  # read before anything was recorded: what a slower recorder holds
    assert captured.status == "qualified"  # premise
    assert captured.deciding is not None
    assert await profile_drift(profile, _drifted_source(profile)) == (_SKILL_DRIFT,)  # premise: one recordable drift

    first = await record_component_drift(world.qualifications, _drifted_source(profile), ref)

    assert len(first) == 1  # the first call records, at sequence `seq`
    seq = first[0].seq
    recorded = await _read(world.qualifications, ref)
    assert recorded.status == "invalidated"  # premise: the row exists
    assert recorded.invalidation_reasons == ("component_drift_skill",)
    assert await record_component_drift(world.qualifications, _drifted_source(profile), ref) == ()  # a plain replay

    world.clock.now += 5.0  # a row written from here on would carry a later time than the first one
    assert first[0].invalidated_at_ms < int(world.clock.now * 1_000)  # premise: the clock moved on
    stale = _StaleStore(world.qualifications, captured)
    replayed = await record_component_drift(stale, _drifted_source(profile), ref)

    assert stale.reads == 1  # premise: the recorder decided from the out-of-date `qualified` answer
    assert replayed == first  # the row the store already held: the same id, sequence and time
    assert (replayed[0].seq, replayed[0].invalidated_at_ms) == (seq, first[0].invalidated_at_ms)
    final = await _read(world.qualifications, ref)
    assert final.status == "invalidated"
    assert len(final.invalidation_reasons) == 1  # nothing new was written


async def test_same_drift_after_requalification_is_recorded_again(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)  # E1
    first_qualification = await _read(world.qualifications, ref)
    assert first_qualification.status == "qualified"  # premise
    assert first_qualification.deciding is not None
    e1 = first_qualification.deciding

    first = await record_component_drift(world.qualifications, _drifted_source(profile), ref)  # drift L, against E1

    assert len(first) == 1
    id_a = first[0].invalidation_id
    assert (await _read(world.qualifications, ref)).status == "invalidated"  # premise: L now disqualifies E1
    e2 = await world.qualifications.record_evaluation(_evaluation(ref, "eval-2"))
    requalified = await _read(world.qualifications, ref)
    assert requalified.status == "qualified"  # premise: the new evaluation qualifies the profile again
    assert requalified.invalidation_reasons == ()
    assert requalified.deciding is not None
    assert requalified.deciding.evidence_ref == e2.evidence_ref
    assert e2.evidence_ref != e1.evidence_ref
    assert e2.seq > first[0].seq

    second = await record_component_drift(world.qualifications, _drifted_source(profile), ref)  # the same drift L

    assert len(second) == 1
    id_b = second[0].invalidation_id
    assert id_b != id_a
    assert second[0].seq > e2.seq  # a new row, recorded after E2, so it applies to E2
    after = await _read(world.qualifications, ref)
    assert after.status == "invalidated"
    assert after.invalidation_reasons == ("component_drift_skill",)
    # negative control: it is the evaluation that tells the two ids apart (A is E1's id, B is E2's)
    assert drift_invalidation_id(ref, e1.evidence_ref, _SKILL_DRIFT) == id_a
    assert drift_invalidation_id(ref, e2.evidence_ref, _SKILL_DRIFT) == id_b


async def test_errors_propagate(world: _World) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)
    qualification = await _read(world.qualifications, ref)
    assert qualification.status == "qualified"  # premise
    assert qualification.deciding is not None

    # a source that fails: the skill drift was seen before the tool read raised, and still nothing was written
    boom = RuntimeError("tool registry is down")
    source = _drifted_source(profile)
    source.tools["codebase_query"] = boom
    with pytest.raises(RuntimeError) as source_failed:
        await record_component_drift(world.qualifications, source, ref)
    assert source_failed.value is boom  # the same object, not wrapped or replaced
    assert _asked(source) == (["audit-trail", "code-review"], ["codebase_query"])  # premise: the tool read was reached
    after = await _read(world.qualifications, ref)
    assert after.status == "qualified"
    assert after.invalidation_reasons == ()

    # a store that fails on its second write: the first write was made, and the error is the store's own object
    write_failed = RuntimeError("disk full")
    store = _FakeStore(qualification, failures={2: write_failed})
    both = _drifted_source(profile)
    both.tools["codebase_query"] = _CHANGED
    with pytest.raises(RuntimeError) as store_failed:
        await record_component_drift(store, both, ref)
    assert store_failed.value is write_failed
    evidence_ref = qualification.deciding.evidence_ref
    assert store.calls == [
        ("get_qualification", ref),
        ("invalidate_profile", ref, drift_invalidation_id(ref, evidence_ref, _SKILL_DRIFT), "component_drift_skill"),
        (
            "invalidate_profile",
            ref,
            drift_invalidation_id(ref, evidence_ref, _TOOL_DRIFT),
            "component_drift_tool_schema",
        ),
    ]


# --------------------------------------------------------------------------------------
# 15. The chain: real catalog, real registry, real stores, across a restart
# --------------------------------------------------------------------------------------


async def test_chain_real_drift_recorded_survives_restart_and_gate_refuses_until_requalified(
    world: _World, tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = _write_skill(skills_dir)
    checklist = skill_dir / "references" / "checklist.md"
    assert sum(old != new for old, new in zip(_CHECKLIST, _CHECKLIST_CHANGED)) == 1  # premise: one byte differs
    assert len(_CHECKLIST) == len(_CHECKLIST_CHANGED)
    assert checklist.read_bytes() == _CHECKLIST  # premise: the file holds the original bytes
    spec = _spec()
    spec_ref = await world.teams.put_team_spec(spec)

    async with _started_catalog(skills_dir) as first_catalog:
        first_registry = ToolRegistry()
        first_registry.register(_codebase_query_tool())
        entry = first_catalog.get_entry("code-review")
        live_tool = first_registry.get_tool("codebase_query")
        assert entry is not None
        assert live_tool is not None
        assert isinstance(live_tool, Tool)  # premise: a genuine Tool, as the registry holds it
        # the digests come from the live objects, through the two ports the source reads
        skill_digest = skill_resource_digest(Path(entry.skill_dir))
        tool_digest = tool_schema_digest(live_tool.input_schema, live_tool.output_schema)
        profile = _variant(
            "v1",
            skills=[{"skill_name": "code-review", "resource_digest": skill_digest}],
            tools=[{"tool_id": "codebase_query", "schema_digest": tool_digest, "implementation_digest": "d" * 64}],
        )
        ref = await world.qualifications.register_profile(profile)
        await world.qualifications.record_evaluation(_evaluation(ref))  # E1
        attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
        source = RegistryComponentSource(first_catalog, first_registry)
        evaluated = await _read(world.qualifications, ref)
        assert evaluated.status == "qualified"  # premise
        assert evaluated.deciding is not None
        assert await profile_drift(profile, source) == ()  # premise: every declared component is current

        checklist.write_bytes(_CHECKLIST_CHANGED)  # one byte of references/checklist.md changes
        live_digest = skill_resource_digest(skill_dir)
        assert live_digest != skill_digest  # premise: the byte changed the directory's digest
        drift = ComponentDrift("skill", "code-review", "component_drift_skill", skill_digest, live_digest)
        assert await profile_drift(profile, source) == (drift,)  # premise: exactly that one drift

        recorded = await record_component_drift(world.qualifications, source, ref)

        assert [item.reason_code for item in recorded] == ["component_drift_skill"]
        assert recorded[0].invalidation_id == drift_invalidation_id(ref, evaluated.deciding.evidence_ref, drift)
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
        invalidated = await _read(world.qualifications, ref)
        assert invalidated.status == "invalidated"  # decided from the invalidation the file carried across
        assert invalidated.invalidation_reasons == ("component_drift_skill",)
        assert invalidated.profile == profile
        assert await world.teams.get_team_spec(spec_ref) == spec  # premise: the spec crossed in its file too
        assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
        # a replay while the changed byte is still there finds the profile invalidated: nothing is recorded again
        assert await profile_drift(invalidated.profile, source) == (drift,)  # premise: the drift is still live
        assert await record_component_drift(world.qualifications, source, ref) == ()
        assert (await _read(world.qualifications, ref)).invalidation_reasons == ("component_drift_skill",)

        checklist.write_bytes(_CHECKLIST)  # the file is restored byte for byte
        assert await profile_drift(invalidated.profile, source) == ()  # premise: every component is current again
        with pytest.raises(SlotAdmissionRefused) as refused:
            await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

        assert type(refused.value) is SlotAdmissionRefused
        assert refused.value.args == ("profile_status_invalidated",)  # the record is what refuses it now
        assert await world.teams.get_attempt(attempt.worker_attempt_id) is None
        assert await record_component_drift(world.qualifications, source, ref) == ()  # a replay of the recorder

        await world.qualifications.record_evaluation(_evaluation(ref, "eval-2"))  # E2
        requalified = await _read(world.qualifications, ref)
        assert requalified.status == "qualified"  # premise: a new evaluation lifts the invalidation
        admitted = await admit_current_qualified_attempt(world.qualifications, world.teams, source, attempt)

        assert admitted == attempt
        stored = await world.teams.get_attempt(attempt.worker_attempt_id)
        assert stored is not None
        assert stored.execution_profile_ref == ref


# --------------------------------------------------------------------------------------
# 16. Import boundary and wiring
# --------------------------------------------------------------------------------------


def test_imports_allowlisted_and_unwired() -> None:
    imported = _probos_imports(ast.parse(Path(recorder_module.__file__).read_bytes()))

    assert imported == _ALLOWED_PROBOS_IMPORTS  # never probos.tools or the catalog: it depends on S2a's ports
    # negative controls: the walker flags a module outside the allowlist, whatever the form or depth of the import
    assert _probos_imports(ast.parse("import probos.tools.registry\n")) - _ALLOWED_PROBOS_IMPORTS == {
        "probos.tools.registry"
    }
    assert _probos_imports(ast.parse("from probos.tools import registry\n")) - _ALLOWED_PROBOS_IMPORTS == {
        "probos.tools"
    }
    assert _probos_imports(ast.parse("def late():\n    from probos.tools import registry\n")) - (
        _ALLOWED_PROBOS_IMPORTS
    ) == {"probos.tools"}
    # premise: S1's scan owns this module and watches this call by name, so nothing in src/probos may wire it
    assert "profile_drift_recorder" in _S1_MODULES
    assert "record_component_drift" in _GATE_NAMES


# --------------------------------------------------------------------------------------
# 17-18. Review round 1: a duplicate replay and a partial failure, on real stores
# --------------------------------------------------------------------------------------


async def test_duplicate_replay_does_not_invalidate_a_later_evaluation(world: _World, tmp_path: Path) -> None:
    profile = _fixture()
    ref = await _qualified(world, profile)  # E1
    captured = await _read(world.qualifications, ref)  # the E1 qualification: what a slower recorder still holds
    assert captured.status == "qualified"  # premise: qualified ...
    assert captured.deciding is not None
    e1 = captured.deciding
    assert await profile_drift(profile, _current_source(profile)) == ()  # ... and current before the drift
    assert await record_component_drift(world.qualifications, _current_source(profile), ref) == ()
    assert _invalidation_rows(tmp_path, ref) == []  # premise: nothing is recorded yet

    first = await record_component_drift(world.qualifications, _drifted_source(profile), ref)  # drift L, against E1

    assert [item.reason_code for item in first] == ["component_drift_skill"]  # I1
    assert (await _read(world.qualifications, ref)).status == "invalidated"  # premise: I1 disqualifies E1
    e2 = await world.qualifications.record_evaluation(_evaluation(ref, "eval-2"))
    requalified = await _read(world.qualifications, ref)
    assert requalified.status == "qualified"  # premise: E2 is qualified before the stale replay
    assert requalified.invalidation_reasons == ()
    assert requalified.deciding is not None
    assert requalified.deciding.evidence_ref == e2.evidence_ref
    assert e2.seq > first[0].seq  # premise: I1 is numbered before E2, so it does not apply to E2

    stale = _StaleStore(world.qualifications, captured)
    replay = await record_component_drift(stale, _drifted_source(profile), ref)  # the same drift L, from the E1 read

    assert stale.reads == 1  # premise: the recorder decided from the out-of-date E1 `qualified` answer
    assert replay == first  # the existing row, not a new one: the same id, sequence and time
    assert (replay[0].invalidation_id, replay[0].seq) == (first[0].invalidation_id, first[0].seq)
    after = await _read(world.qualifications, ref)
    assert after.status == "qualified"  # that row applies only to evaluations recorded before it, so E2 stands
    assert after.invalidation_reasons == ()
    rows = _invalidation_rows(tmp_path, ref)
    assert [(row["invalidation_id"], row["seq"], row["reason_code"]) for row in rows] == [
        (first[0].invalidation_id, first[0].seq, "component_drift_skill")
    ]  # one invalidation row

    # control: a stale recorder whose live digest differs holds another id, so the store inserts a NEW row. That row is
    # numbered after E2 and applies to it: a newly inserted row does invalidate an evaluation recorded between the
    # recorder's read and its write.
    other_live = "8" * 64
    assert other_live != _CHANGED  # premise: a digest the first recorder did not see
    other_source = _current_source(profile)
    other_source.skills["code-review"] = LiveSkill(other_live, True)
    other_drift = ComponentDrift("skill", "code-review", "component_drift_skill", _DECLARED_SKILL, other_live)
    assert await profile_drift(profile, other_source) == (other_drift,)  # premise: that one drift

    control = await record_component_drift(_StaleStore(world.qualifications, captured), other_source, ref)

    assert [item.reason_code for item in control] == ["component_drift_skill"]
    assert control[0].invalidation_id == drift_invalidation_id(ref, e1.evidence_ref, other_drift)  # bound to E1
    assert control[0].invalidation_id != first[0].invalidation_id
    assert control[0].seq > e2.seq  # a new row, numbered after E2
    final = await _read(world.qualifications, ref)
    assert final.status == "invalidated"
    assert final.invalidation_reasons == ("component_drift_skill",)
    assert len(_invalidation_rows(tmp_path, ref)) == 2  # I1 and the new row


async def test_partial_failure_then_rerun_records_nothing_more(world: _World, tmp_path: Path) -> None:
    spec_ref = await world.teams.put_team_spec(_spec())
    profile = _fixture()
    ref = await _qualified(world, profile)  # E1
    attempt = _attempt(team_spec_ref=spec_ref, slot_id="review", execution_profile_ref=ref)
    qualified = await _read(world.qualifications, ref)
    assert qualified.status == "qualified"  # premise: qualified ...
    assert qualified.deciding is not None
    e1 = qualified.deciding
    assert await profile_drift(profile, _current_source(profile)) == ()  # ... and current before the drift
    assert await record_component_drift(world.qualifications, _current_source(profile), ref) == ()
    assert await profile_drift(profile, _both_drifted(profile)) == (_SKILL_DRIFT, _TOOL_DRIFT)  # premise: two drifts

    boom = RuntimeError("write 2 failed")
    failing = _FailSecondWrite(world.qualifications, boom)
    with pytest.raises(RuntimeError) as failed:
        await record_component_drift(failing, _both_drifted(profile), ref)

    assert failed.value is boom  # the same exception object, unwrapped
    skill_id = drift_invalidation_id(ref, e1.evidence_ref, _SKILL_DRIFT)
    assert failing.writes == [  # premise: the skill write went through, and the tool write was made and raised
        (ref, skill_id, "component_drift_skill"),
        (ref, drift_invalidation_id(ref, e1.evidence_ref, _TOOL_DRIFT), "component_drift_tool_schema"),
    ]
    before = (world.qualifications, world.teams)
    await world.stop()
    await world.start()  # NEW store instances on the same two files
    assert world.qualifications is not before[0]
    assert world.teams is not before[1]
    with pytest.raises(ProfileQualificationStoreUnavailable):
        await before[0].get_qualification(ref)  # premise: the first instance is stopped, so it cannot be what answers
    durable = await _read(world.qualifications, ref)
    assert durable.status == "invalidated"  # premise: the first write is durable
    assert durable.invalidation_reasons == ("component_drift_skill",)
    rows = _invalidation_rows(tmp_path, ref)
    assert [(row["invalidation_id"], row["reason_code"]) for row in rows] == [(skill_id, "component_drift_skill")]

    rerun_source = _both_drifted(profile)
    rerun = await record_component_drift(world.qualifications, rerun_source, ref)

    assert rerun == ()  # the profile is invalidated, so nothing more is recorded ...
    assert _asked(rerun_source) == ([], [])  # ... and the components are never read
    assert len(_invalidation_rows(tmp_path, ref)) == 1  # the tool's drift was not recorded
    with pytest.raises(SlotAdmissionRefused) as refused:
        await admit_current_qualified_attempt(world.qualifications, world.teams, _both_drifted(profile), attempt)
    assert type(refused.value) is SlotAdmissionRefused
    assert refused.value.args == ("profile_status_invalidated",)  # the record is what refuses it, not the drift
    assert await world.teams.get_attempt(attempt.worker_attempt_id) is None

    e2 = await world.qualifications.record_evaluation(_evaluation(ref, "eval-2"))
    requalified = await _read(world.qualifications, ref)
    assert requalified.status == "qualified"  # premise: E2 qualifies the profile again
    assert requalified.invalidation_reasons == ()
    assert requalified.deciding is not None
    assert requalified.deciding.evidence_ref == e2.evidence_ref

    final = await record_component_drift(world.qualifications, _both_drifted(profile), ref)

    assert [item.reason_code for item in final] == ["component_drift_skill", "component_drift_tool_schema"]
    assert [item.invalidation_id for item in final] == [  # both live drifts, recorded against E2
        drift_invalidation_id(ref, e2.evidence_ref, _SKILL_DRIFT),
        drift_invalidation_id(ref, e2.evidence_ref, _TOOL_DRIFT),
    ]
    assert final[0].invalidation_id != skill_id  # the skill is a new row, not the one E1 left
    assert all(item.seq > e2.seq for item in final)
    after = await _read(world.qualifications, ref)
    assert after.status == "invalidated"
    assert after.invalidation_reasons == ("component_drift_skill", "component_drift_tool_schema")
    assert len(_invalidation_rows(tmp_path, ref)) == 3  # E1's skill row, then E2's skill and tool rows
