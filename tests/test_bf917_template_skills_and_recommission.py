"""BF-917 (#1625): the role templates' skills are registered, and a changed role template re-commissions a crew member once without loss.

Real objects throughout: the real ``OntologyLoader``/``VesselOntologyService`` over the shipped
``config/ontology`` or a copy a test edits; the real ``SkillRegistry``, ``AgentSkillService``,
``AgentCapitalService``, ``ToolPermissionStore`` and ``ToolRegistry`` on SQLite files under
``tmp_path``; and the real AD-889 chain reached through ``CrewEnrollmentService.enroll``. The only
stand-ins are the wired agent, E4's failing ``commission``, E5's failing base step and E6's gate
around the real ``acquire_skill``. History rows are picked by predicate. Only E6 waits on a clock:
a bounded wait for a second caller that, under the enroller's lock, never arrives.

- G1-G5 the registration (guard 1: no tool; guard 2: no faster decay, no changed acquisition)
- A1-A2 ACM: the fingerprint column and the re-commission write
- E1-E6 the trigger, end to end (E5: a missing PCC; E6: overlapping enrollments)
- D1-D3 the doctor's ``role_templates`` check
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.crew_enrollment import template_fingerprint
from probos.doctor.checks.role_template_check import _RoleTemplateCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.ontology.loader import OntologyLoader
from probos.role_template_audit import unregistered_template_skills
from probos.skill_framework import (
    BUILTIN_PCCS,
    ONTOLOGY_TEMPLATE_SKILLS,
    ROLE_SKILL_TEMPLATES,
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillRegistry,
    builtin_skill_definitions,
)
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.registry import ToolRegistry
from probos.tools.skill_tool_resolver import resolve_tools_for_skill
from tests.fixtures.crew_template_world import (
    ONTOLOGY_DIR,
    PROBE_TOOL,
    CrewAgent,
    boot_enroller,
    crew_world,
    edit_skills_yaml,
    recommission_rows,
    skill_records,
)

# The 22 ids #1625 found unregistered (skills.yaml:44-261 on 80456da2).
_BF917_IDS = frozenset({
    "architecture_review", "pattern_recognition", "wellness_assessment", "personality_analysis",
    "crew_counseling", "systems_analysis", "architecture_implementation", "trend_analysis",
    "data_processing", "quantitative_analysis", "cross_department_synthesis", "emergence_analysis",
    "technical_writing", "evidence_analysis", "diagnostic_analysis", "health_monitoring",
    "treatment_planning", "threat_assessment", "access_control", "vulnerability_analysis",
    "workflow_optimization", "system_monitoring",
})
_VULNERABILITY = "      - skill_id: vulnerability_analysis\n        min_proficiency: 4\n"
_ADD_CODE_REVIEW = _VULNERABILITY + "      - skill_id: code_review\n        min_proficiency: 3\n"
_DAY = 86400.0
# E6: how long the first caller waits for a second. Without the enroller's lock the second arrives within
# milliseconds; with it, it never does, so the passing run pays this wait once.
_SECOND_CALLER_WAIT = 2.0


async def _noop(**kwargs: Any) -> None:
    return None


def _legacy_role_skills() -> list[Any]:
    return [defn for skills in ROLE_SKILL_TEMPLATES.values() for defn in skills]


async def _shipped_loader() -> OntologyLoader:
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    return loader


# --- G1 to G5: the registration ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_role_template_skill_is_a_registered_definition(tmp_path: Path) -> None:
    """G1: every id a shipped template requires or offers is registered at boot; BF-917's ids are 39 references to 22."""
    loader = await _shipped_loader()
    assert len(loader.role_templates) >= 14  # premise: the shipped templates loaded
    skill_registry = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await skill_registry.start()
    try:
        await skill_registry.register_builtins()
        named = [
            (post_id, req.skill_id)
            for post_id, template in loader.role_templates.items()
            for req in [*template.required_skills, *template.optional_skills]
        ]
        assert [pair for pair in named if skill_registry.get_skill(pair[1]) is None] == []
        registered = frozenset(d.skill_id for d in builtin_skill_definitions())
        assert unregistered_template_skills(loader.role_templates, registered) == ()
        bf917_refs = [
            req.skill_id for template in loader.role_templates.values()
            for req in template.required_skills if req.skill_id in _BF917_IDS
        ]
        assert (len(bf917_refs), len(set(bf917_refs))) == (39, 22)
        assert {d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS} <= {skill for _, skill in named}
    finally:
        await skill_registry.stop()


def test_the_template_skills_change_no_acquisition_decay_or_tool_route() -> None:
    """G2 (guards 1 and 2): role skills with no prerequisite, preferred tool or composite; 14 days; a legacy domain."""
    ids = [d.skill_id for d in builtin_skill_definitions()]
    assert len(ids) == len(set(ids))
    assert _BF917_IDS <= {d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS}
    legacy_domains = {d.domain for d in _legacy_role_skills()}
    assert legacy_domains == {"security", "engineering", "operations", "medical", "science"}  # premise
    for defn in ONTOLOGY_TEMPLATE_SKILLS:
        assert (defn.category, defn.origin) == (SkillCategory.ROLE, "role"), defn.skill_id
        assert defn.prerequisites == [] and defn.preferred_tools == [], defn.skill_id
        assert defn.composite_skill_ids == [] and defn.synergy_partners == [], defn.skill_id
        assert defn.decay_rate_days == 14, defn.skill_id  # check_decay's value for a record with no definition
        assert defn.domain in legacy_domains, defn.skill_id
        assert defn.name and defn.description, defn.skill_id


@pytest.mark.asyncio
async def test_the_resolver_gives_a_template_skill_no_tool_its_domain_does_not_already_get() -> None:
    """G3 (guard 1): startup's ontology-seeded tools give no template skill a tool, and against any registry a
    template skill resolves exactly what a legacy role skill of its domain resolves."""
    loader = await _shipped_loader()
    seeded = ToolRegistry()
    for capability in loader.tool_capabilities:  # startup/communication.py's seeding, tags and all
        seeded.register(
            DirectServiceAdapter(tool_id=capability.id, name=capability.name, description=capability.description, handler=_noop),
            provider=capability.provider, tags=[capability.id, capability.provider],
        )
    assert seeded.list_tools()  # premise: there are readable tools to find
    legacy_by_domain = {d.domain: d for d in _legacy_role_skills()}
    probe = ToolRegistry()
    for domain in sorted(legacy_by_domain):
        probe.register(
            DirectServiceAdapter(tool_id=f"probe_{domain}", name=domain, description="BF-917 probe", handler=_noop),
            provider="bf917", tags=[domain],
        )
    for defn in ONTOLOGY_TEMPLATE_SKILLS:
        assert resolve_tools_for_skill(defn, agent_id="crew-g3", tool_registry=seeded) == [], defn.skill_id
        resolved = [r.tool_id for r in resolve_tools_for_skill(defn, agent_id="crew-g3", tool_registry=probe)]
        legacy = legacy_by_domain[defn.domain]
        assert resolved == [r.tool_id for r in resolve_tools_for_skill(legacy, agent_id="crew-g3", tool_registry=probe)]
        assert resolved == [f"probe_{defn.domain}"], defn.skill_id  # the probe is live: the domain is the question


@pytest.mark.asyncio
async def test_a_formerly_undefined_record_decays_exactly_as_before(tmp_path: Path) -> None:
    """G4 (guard 2): the same records decay identically with and without the template definitions."""
    bare_registry = SkillRegistry(db_path=str(tmp_path / "bare.db"))
    full_registry = SkillRegistry(db_path=str(tmp_path / "full.db"))
    await bare_registry.start()
    await full_registry.start()
    for defn in [*BUILTIN_PCCS, *_legacy_role_skills()]:
        await bare_registry.register_skill(defn)
    await full_registry.register_builtins()
    bare_service = AgentSkillService(db_path=str(tmp_path / "bare.db"), registry=bare_registry)
    full_service = AgentSkillService(db_path=str(tmp_path / "full.db"), registry=full_registry)
    await bare_service.start()
    await full_service.start()
    try:
        ids = [d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS]
        for skill_id in ids:
            await bare_service.acquire_skill("crew-g4", skill_id, source="commission", proficiency=ProficiencyLevel.ADVISE)
            await full_service.acquire_skill("crew-g4", skill_id, source="commission", proficiency=ProficiencyLevel.ADVISE)
        records = await full_service.get_all_records("crew-g4")
        base = max(r.last_exercised for r in records)
        assert await bare_service.check_decay(now=base + 13 * _DAY) == []
        assert await full_service.check_decay(now=base + 13 * _DAY) == []
        await bare_service.check_decay(now=base + 20 * _DAY)
        await full_service.check_decay(now=base + 20 * _DAY)
        bare = {r.skill_id: r.proficiency for r in await bare_service.get_all_records("crew-g4")}
        full = {r.skill_id: r.proficiency for r in await full_service.get_all_records("crew-g4")}
        assert full == bare == {skill_id: ProficiencyLevel.ENABLE for skill_id in ids}
    finally:
        await bare_service.stop()
        await full_service.stop()
        await bare_registry.stop()
        await full_registry.stop()


@pytest.mark.asyncio
async def test_a_record_under_a_newly_registered_id_becomes_a_role_skill_unchanged(tmp_path: Path) -> None:
    """G5: an orphan record (above its floor, exercised) is a role skill after registration, every field unchanged."""
    db = str(tmp_path / "skills.db")
    before_registry = SkillRegistry(db_path=db)
    await before_registry.start()
    for defn in [*BUILTIN_PCCS, *_legacy_role_skills()]:
        await before_registry.register_skill(defn)
    before_service = AgentSkillService(db_path=db, registry=before_registry)
    await before_service.start()
    await before_service.acquire_skill("crew-g5", "threat_assessment", source="commission", proficiency=ProficiencyLevel.ADVISE)
    await before_service.update_proficiency("crew-g5", "threat_assessment", ProficiencyLevel.LEAD, source="bf917-test")
    await before_service.record_exercise("crew-g5", "threat_assessment")
    orphan = await before_service.get_profile("crew-g5")
    assert ([r.skill_id for r in orphan.acquired_skills], orphan.role_skills) == (["threat_assessment"], [])  # premise
    held = await skill_records(before_service, "crew-g5")
    await before_service.stop()
    await before_registry.stop()

    after_registry = SkillRegistry(db_path=db)
    await after_registry.start()
    await after_registry.register_builtins()
    after_service = AgentSkillService(db_path=db, registry=after_registry)
    await after_service.start()
    try:
        profile = await after_service.get_profile("crew-g5")
        assert ([r.skill_id for r in profile.role_skills], profile.acquired_skills) == (["threat_assessment"], [])
        assert await skill_records(after_service, "crew-g5") == held
    finally:
        await after_service.stop()
        await after_registry.stop()


# --- A1, A2: ACM ---------------------------------------------------------------------------------

# BF-906's commissioning_records exactly as it shipped: the live vessel's shape.
_BF906_TABLE = """
CREATE TABLE commissioning_records (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    source TEXT NOT NULL,
    role_template TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    initiated_by TEXT NOT NULL DEFAULT 'system',
    reason TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
INSERT INTO commissioning_records (agent_id, agent_type, source, role_template, skills_json, tools_json,
    initiated_by, reason, timestamp)
VALUES ('crew-a1', 'scout', 'backfill', 'scout_officer', '["communication"]', '[]', 'system', 'BF-906', 5.0);
"""


@pytest.mark.asyncio
async def test_a_bf906_acm_db_gains_the_fingerprint_column_and_keeps_its_rows(tmp_path: Path) -> None:
    """A1: the migration adds the column once, keeps the row, and reads its fingerprint as None."""
    with contextlib.closing(sqlite3.connect(tmp_path / "acm.db")) as conn:
        conn.executescript(_BF906_TABLE)
        conn.commit()
    for _ in range(2):  # the second start is a later boot: idempotent
        acm = AgentCapitalService(data_dir=tmp_path)
        await acm.start()
        try:
            record = await acm.get_commissioning_record("crew-a1")
            assert record is not None
            assert (record.agent_type, record.source, record.role_template, record.skills, record.timestamp) == (
                "scout", "backfill", "scout_officer", ("communication",), 5.0,
            )
            assert record.template_fingerprint is None
        finally:
            await acm.stop()
    with contextlib.closing(sqlite3.connect(tmp_path / "acm.db")) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(commissioning_records)")]
    assert columns.count("template_fingerprint") == 1


@pytest.mark.asyncio
async def test_a_recommission_replaces_only_the_template_and_writes_one_history_row(tmp_path: Path) -> None:
    """A2: recommission=True is False without a record or with the same fingerprint, and otherwise replaces only
    the role template and fingerprint, with one re-commission history row."""
    acm = AgentCapitalService(data_dir=tmp_path)
    await acm.start()
    try:
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="join", role_template=None, skills=(), tools=(),
            reason="BF-917 test", template_fingerprint="fp-1", recommission=True,
        ) is False
        assert await acm.get_transition_history("crew-a2") == []
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="join", role_template=None,
            skills=("communication",), tools=(), reason="BF-917 test", template_fingerprint="fp-1",
        ) is True
        first = await acm.get_commissioning_record("crew-a2")
        history = await acm.get_transition_history("crew-a2")
        assert first is not None and first.template_fingerprint == "fp-1"
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="backfill", role_template="scout_officer", skills=(),
            tools=(), reason="BF-917 test", template_fingerprint="fp-1", recommission=True,
        ) is False
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="backfill", role_template="scout_officer",
            skills=("pattern_recognition",), tools=(), reason="BF-917 test", template_fingerprint="fp-2",
            recommission=True,
        ) is True
        second = await acm.get_commissioning_record("crew-a2")
        assert second is not None
        assert (second.role_template, second.template_fingerprint) == ("scout_officer", "fp-2")
        assert (second.source, second.skills, second.tools, second.timestamp) == (
            first.source, first.skills, first.tools, first.timestamp,
        )
        rows = recommission_rows(history, await acm.get_transition_history("crew-a2"))
        assert len(rows) == 1
        assert "role_template=scout_officer" in rows[0].reason and "pattern_recognition" in rows[0].reason
    finally:
        await acm.stop()


# --- E1 to E4: the trigger -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_changed_role_template_is_applied_once_keeping_every_record_and_granting_no_tool(tmp_path: Path) -> None:
    """E1 (the seam): template v1 -> commissioned; v2 adds a skill -> the next boot re-commissions once, keeps every
    record (one above its floor), grants no tool; the same template again -> nothing."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e1", "security_officer")
        enroller, ontology = await boot_enroller(world)
        first = await enroller.enroll(agent, source="birth")
        assert first is not None and first.commissioned is True
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None
        assert record.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        steady = await enroller.enroll(agent, source="backfill")
        assert steady is not None and (steady.commissioned, steady.recommissioned) == (False, False)

        await world.skill_service.update_proficiency(agent.id, "threat_assessment", ProficiencyLevel.LEAD, source="bf917-test")
        await world.skill_service.record_exercise(agent.id, "communication")
        held = await skill_records(world.skill_service, agent.id)
        assert held["threat_assessment"][0] == ProficiencyLevel.LEAD  # premise: above the template's floor of 5
        assert "code_review" not in held
        history = await world.acm.get_transition_history(agent.id)
        assert await world.permission_store.list_grants(active_only=True) == []

        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, ontology = await boot_enroller(world)  # the next boot reads the changed template
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and (again.commissioned, again.recommissioned) == (False, True)
        assert (again.role_template, again.skills_granted, again.tools_granted) == ("chief_security", ("code_review",), ())
        after = await skill_records(world.skill_service, agent.id)
        assert {skill: after[skill] for skill in held} == held
        assert set(after) - set(held) == {"code_review"}
        assert after["code_review"][0] == ProficiencyLevel.APPLY  # the new skill at the template's floor
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None and changed.role_template == "chief_security"
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        assert changed.template_fingerprint != record.template_fingerprint
        assert (changed.agent_type, changed.source, changed.skills, changed.tools, changed.timestamp) == (
            record.agent_type, record.source, record.skills, record.tools, record.timestamp,
        )
        rows = recommission_rows(history, await world.acm.get_transition_history(agent.id))
        assert len(rows) == 1
        assert "BF-917" in rows[0].reason and "code_review" in rows[0].reason
        # A full AD-889 chain would grant the probe tool for code_review; the re-commission grants nothing.
        code_review = world.skill_registry.get_skill("code_review")
        assert code_review is not None
        resolvable = resolve_tools_for_skill(code_review, agent_id=agent.id, tool_registry=world.tool_registry)
        assert [r.tool_id for r in resolvable] == [PROBE_TOOL]
        assert await world.permission_store.list_grants(active_only=True) == []

        settled = (after, changed, await world.acm.get_transition_history(agent.id))
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False
        assert (
            await skill_records(world.skill_service, agent.id),
            await world.acm.get_commissioning_record(agent.id),
            await world.acm.get_transition_history(agent.id),
        ) == settled


@pytest.mark.asyncio
async def test_a_record_written_before_bf917_is_recommissioned_once_and_acquires_nothing(tmp_path: Path) -> None:
    """E2: the live vessel's first boot: a NULL fingerprint is re-commissioned once, changes no record, then is stable."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e2", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        held = await skill_records(world.skill_service, agent.id)
        await world.acm.stop()
        with contextlib.closing(sqlite3.connect(tmp_path / "acm" / "acm.db")) as conn:
            conn.execute("UPDATE commissioning_records SET template_fingerprint = NULL")
            conn.commit()
        await world.acm.start()  # the next boot reopens the file
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None and record.template_fingerprint is None  # premise: as BF-906 wrote it
        history = await world.acm.get_transition_history(agent.id)

        enroller, ontology = await boot_enroller(world)
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and (again.recommissioned, again.skills_granted) == (True, ())
        assert await skill_records(world.skill_service, agent.id) == held
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        rows = recommission_rows(history, await world.acm.get_transition_history(agent.id))
        assert len(rows) == 1 and "skills=none" in rows[0].reason
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False


@pytest.mark.asyncio
async def test_a_decommissioned_crew_member_is_not_recommissioned(tmp_path: Path) -> None:
    """E3: a changed template leaves a decommissioned agent's records and commissioning untouched."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e3", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        await world.acm.decommission(agent.id, reason="BF-917 test", initiated_by="captain")
        record = await world.acm.get_commissioning_record(agent.id)
        held = await skill_records(world.skill_service, agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        result = await enroller.enroll(agent, source="backfill")

        assert result is not None and result.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await skill_records(world.skill_service, agent.id) == held


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "no-profile"])
async def test_a_failed_recommission_records_nothing_and_the_next_boot_applies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    """E4: a chain that raises, or reads no profile, records nothing and logs one ERROR; the next pass applies it."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e4", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        record = await world.acm.get_commissioning_record(agent.id)
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        async def _failing(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if failure == "raises":
                raise OSError("BF-917 test: the commissioning chain failed")
            return {"agent_id": agent.id, "agent_type": agent.agent_type, "skills_acquired": [], "tools_granted": []}

        with monkeypatch.context() as patched:
            patched.setattr(world.acm, "commission", _failing)
            with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
                failed = await enroller.enroll(agent, source="backfill")

        assert failed is not None and failed.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await world.acm.get_transition_history(agent.id) == history
        assert "code_review" not in await skill_records(world.skill_service, agent.id)
        errors = [r for r in caplog.records if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "BF-917" in errors[0].getMessage() and agent.id in errors[0].getMessage()
        # A1: each guard names its own cause, so the profile guard is not masked by the PCC check after it.
        assert ("read no skill profile" if failure == "no-profile" else "re-commissioning failed") in errors[0].getMessage()

        retried = await enroller.enroll(agent, source="backfill")
        assert retried is not None and (retried.recommissioned, retried.skills_granted) == (True, ("code_review",))


@pytest.mark.asyncio
async def test_a_recommission_that_leaves_a_pcc_missing_records_nothing_and_the_next_boot_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """E5 (A1): a PCC added after the agent's commissioning, and a base step that fails. AD-889 logs the failure at
    DEBUG and returns the profile it read; the re-commission records nothing and logs one ERROR naming the PCC, the
    rule a first commissioning keeps (BF-906 A3). The next pass acquires the PCC and records the template."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e5", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        await world.skill_service.stop()
        with contextlib.closing(sqlite3.connect(tmp_path / "skills.db")) as conn:
            conn.execute("DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?", (agent.id, "duty_execution"))
            conn.commit()
        await world.skill_service.start()  # the next boot reopens the file
        assert "duty_execution" not in await skill_records(world.skill_service, agent.id)  # premise: a PCC is missing
        record = await world.acm.get_commissioning_record(agent.id)
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        async def _failing_base_step(*args: Any, **kwargs: Any) -> None:
            raise OSError("BF-917 test: the base commissioning step failed")

        with monkeypatch.context() as patched:
            patched.setattr(world.skill_service, "commission_agent", _failing_base_step)
            with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
                degraded = await enroller.enroll(agent, source="backfill")

        assert degraded is not None and degraded.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await world.acm.get_transition_history(agent.id) == history
        held = await skill_records(world.skill_service, agent.id)
        assert "code_review" in held and "duty_execution" not in held  # premise: the chain ran past its failed base step
        errors = [r for r in caplog.records if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "BF-917" in errors[0].getMessage() and "without the PCCs duty_execution" in errors[0].getMessage()

        retried = await enroller.enroll(agent, source="backfill")
        assert retried is not None and (retried.recommissioned, retried.skills_granted) == (True, ("duty_execution",))
        assert (await skill_records(world.skill_service, agent.id))["code_review"] == held["code_review"]


@pytest.mark.asyncio
async def test_overlapping_enrollments_of_one_agent_acquire_a_missing_skill_once_and_keep_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E6 (A1): two enrollments of one agent overlap after a template change. The first to reach ``acquire_skill``
    for the new skill waits, bounded, for a second; the record it writes is then advanced. Without the enroller's
    lock the second has passed its snapshot too and its write resets that record. With it, the second waits, reads
    the new fingerprint and acquires nothing."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e6", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, ontology = await boot_enroller(world)

        real_acquire = world.skill_service.acquire_skill
        callers: list[str] = []
        second_arrived = asyncio.Event()
        release_second = asyncio.Event()

        async def _gated_acquire(agent_id: str, skill_id: str, *args: Any, **kwargs: Any) -> Any:
            if skill_id == "code_review":
                callers.append(agent_id)
                if len(callers) == 1:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(second_arrived.wait(), _SECOND_CALLER_WAIT)
                else:
                    second_arrived.set()
                    await release_second.wait()
            return await real_acquire(agent_id, skill_id, *args, **kwargs)

        monkeypatch.setattr(world.skill_service, "acquire_skill", _gated_acquire)
        tasks = [asyncio.create_task(enroller.enroll(agent, source="backfill")) for _ in range(2)]
        try:
            done, _pending = await asyncio.wait(tasks, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            assert done, "premise: one enrollment finished"
            assert "code_review" in await skill_records(world.skill_service, agent.id)  # premise: the first write ran
            await world.skill_service.update_proficiency(agent.id, "code_review", ProficiencyLevel.ADVISE, source="bf917-test")
            await world.skill_service.record_exercise(agent.id, "code_review")
            advanced = (await skill_records(world.skill_service, agent.id))["code_review"]
            assert (advanced[0], advanced[1]) == (ProficiencyLevel.ADVISE, 1)  # premise: the record moved on
        finally:
            release_second.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 60)

        assert callers == [agent.id]  # the missing skill was acquired once
        assert (await skill_records(world.skill_service, agent.id))["code_review"] == advanced
        assert sorted((r.commissioned, r.recommissioned) for r in results if r is not None) == [(False, False), (False, True)]
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        assert len(recommission_rows(history, await world.acm.get_transition_history(agent.id))) == 1


# --- D1 to D3: probos doctor ------------------------------------------------------------------------


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path / "data", config_path=None)


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(root.rglob("*"))}


@pytest.mark.asyncio
async def test_the_doctor_reports_ok_for_the_shipped_templates(tmp_path: Path) -> None:
    """D1: the shipped ontology passes, and the check creates no data directory."""
    result = await _RoleTemplateCheck().run(_context(tmp_path))
    assert result.outcome is CheckOutcome.OK, result.detail
    assert "templates" in result.message
    assert not (tmp_path / "data").exists()


@pytest.mark.asyncio
async def test_the_doctor_warns_for_an_unregistered_template_skill_and_writes_nothing(tmp_path: Path) -> None:
    """D2: one unregistered id is one WARN line naming the post and the skill; nothing on disk changes."""
    copy = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, copy)
    path = copy / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("      - skill_id: access_control\n") == 1  # premise
    path.write_text(text.replace("      - skill_id: access_control\n", "      - skill_id: access_kontrol\n"), encoding="utf-8")
    before = _tree(tmp_path)

    result = await _RoleTemplateCheck(ontology_dir=copy).run(_context(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.detail.splitlines() == [
        "chief_security: template skill access_kontrol is not a registered skill definition",
    ]
    assert "skills.yaml" in result.remediation
    assert _tree(tmp_path) == before


def test_the_role_template_check_is_registered_once_after_token_accounting() -> None:
    """D3: a fresh interpreter on this tree registers the check once, after token_accounting, next to crew_enrollment."""
    import probos

    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    probe = (
        "import json, probos; from probos.doctor import checks; from probos.doctor.registry import iter_checks; "
        "print(json.dumps({'src': probos.__file__, 'names': [c.name for c in iter_checks()]}))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
    )
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert Path(seen["src"]).resolve().is_relative_to(src_dir)  # the child imported this tree
    names = seen["names"]
    assert names.count("role_templates") == 1
    assert names[names.index("crew_enrollment") + 1] == "token_accounting"
    assert names[names.index("token_accounting") + 1] == "role_templates"
