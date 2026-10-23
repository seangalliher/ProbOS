"""BF-906 (#1594) - real-boot tests: boot-wired crew are enrolled end to end (milestones M2 and M3).

Crew are wired in Phase 2, before ACM, the ontology and the skill service exist (Phase 7).
Each test boots a real ``ProbOSRuntime`` through every startup phase, in production order,
with the mock LLM (no network and no model), as
``test_bf879_designed_agents_start_probationary.py`` does, then reads what the boot left
behind through the real ACM, skill service, permission store and event log. Nothing is
stubbed except where a test names its stub.

- T-B1  every boot-wired crew member is onboarded and commissioned (source ``birth``)
- T-B2  a vessel whose crew predate commissioning is backfilled (source ``backfill``)
- T-B3  a second boot duplicates nothing and keeps proficiency
- T-B4  re-commissioning after a lost record keeps the skills the agent holds
- T-B5  crew wired after startup go through the same entry point (source ``join``)
- T-B6  the crew invariant fails red when the pass is removed (startup ERROR, event, doctor)
- T-B7  after a normal boot the startup check and the doctor agree the invariant holds
- T-B8  suspend and reinstate cross the route, ACM and the roster (an HR status only)
- T-B9  ``check_activation`` moves a boot-wired crew member at the threshold

Every data directory is under ``tmp_path`` and every runtime is stopped; nothing sleeps or
waits, and nothing is ordered by wall-clock time (history rows are picked by predicate).
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService, LifecycleState
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from probos.skill_framework import ProficiencyLevel


def _config(*, ward_room: bool = False) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    if ward_room:
        # Only T-B1 asks: AD-625's comm-profile cache is built in finalize.py only inside
        # ``if runtime.ward_room:``, and the ward room is off by default (WardRoomConfig.enabled).
        config.ward_room.enabled = True
    return config


async def _boot(data_dir: Path, config: SystemConfig | None = None) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=config or _config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


@pytest.fixture
async def runtime(tmp_path: Path) -> AsyncIterator[ProbOSRuntime]:
    booted = await _boot(tmp_path / "data")
    try:
        yield booted
    finally:
        await booted.stop()


def _crew(rt: ProbOSRuntime) -> list[Any]:
    crew = [a for a in rt.registry.all() if is_crew_agent(a, rt.ontology)]
    assert crew, "premise: the boot wired crew"
    return crew


def _architect(rt: ProbOSRuntime) -> Any:
    architects = [a for a in _crew(rt) if a.agent_type == "architect"]
    assert len(architects) == 1, f"premise: exactly one architect among the crew, got {len(architects)}"
    return architects[0]


def _same_state(history: list[Any]) -> list[Any]:
    """The commissioning rows of a lifecycle history (from_state == to_state), picked by predicate."""
    return [t for t in history if t.from_state == t.to_state]


def _onboarding(history: list[Any]) -> list[Any]:
    return [t for t in history if (t.from_state, t.to_state) == ("registered", "probationary")]


async def _commissioned_events(rt: ProbOSRuntime) -> list[dict[str, Any]]:
    return await rt.event_log.query_structured(
        category="lifecycle", event="crew_commissioned", limit=1_000,
    )


async def _levels(rt: ProbOSRuntime, agent_id: str) -> dict[str, tuple[ProficiencyLevel, int]]:
    """Each skill row's proficiency and exercise count."""
    profile = await rt.skill_service.get_profile(agent_id)
    return {r.skill_id: (r.proficiency, r.exercise_count) for r in profile.all_skills}


async def _snapshot(rt: ProbOSRuntime, crew_ids: list[str]) -> dict[str, Any]:
    """Everything a second boot must leave exactly as it found it."""
    skills: dict[str, dict[str, Any]] = {}
    history: dict[str, list[tuple[str, str, str, str, float]]] = {}
    records: dict[str, Any] = {}
    for agent_id in crew_ids:
        profile = await rt.skill_service.get_profile(agent_id)
        skills[agent_id] = {r.skill_id: r for r in profile.all_skills}
        transitions = await rt.acm.get_transition_history(agent_id)
        history[agent_id] = sorted(
            (t.from_state, t.to_state, t.reason, t.initiated_by, t.timestamp) for t in transitions
        )
        records[agent_id] = await rt.acm.get_commissioning_record(agent_id)
    grants = sorted(await rt.tool_permission_store.list_grants(active_only=True), key=lambda g: g.id)
    return {
        "skills": skills,
        "history": history,
        "records": records,
        "grants": grants,
        "commissioned_events": len(await _commissioned_events(rt)),
    }


def _table_count(data_dir: Path, table: str) -> int:
    """Row count of an ACM table, read from the stopped vessel's acm.db."""
    with contextlib.closing(sqlite3.connect(data_dir / "acm.db")) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # table: a literal below


@pytest.mark.asyncio
async def test_every_boot_wired_crew_member_is_onboarded_and_commissioned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T-B1: after one boot every crew member is probationary, commissioned (birth), skilled, logged and cached."""
    with caplog.at_level(logging.WARNING, logger="probos.crew_enrollment"):
        rt = await _boot(tmp_path / "data", _config(ward_room=True))
    try:
        assert rt.ward_room is not None, (
            "premise: the AD-625 comm-profile cache is built in finalize.py only inside "
            "`if runtime.ward_room:`, so without a ward room the cache assertion below would prove nothing"
        )
        crew = _crew(rt)
        events: dict[str, list[dict[str, Any]]] = {}
        for row in await _commissioned_events(rt):
            events.setdefault(row["agent_id"], []).append(row)
        assert set(events) == {a.id for a in crew}, "one crew_commissioned row per crew member, none for anyone else"

        for agent in crew:
            who = f"{agent.agent_type} ({agent.id})"
            assert await rt.acm.has_lifecycle_record(agent.id), f"{who}: no lifecycle row"
            assert await rt.acm.get_lifecycle_state(agent.id) is LifecycleState.PROBATIONARY, who
            record = await rt.acm.get_commissioning_record(agent.id)
            assert record is not None, f"{who}: no commissioning record"
            assert record.source == "birth", who
            assert (await rt.skill_service.get_profile(agent.id)).all_skills, f"{who}: empty skill profile"
            history = await rt.acm.get_transition_history(agent.id)
            onboarding = _onboarding(history)
            assert len(onboarding) == 1, who
            assert onboarding[0].initiated_by == "system", who
            assert "BF-906" in onboarding[0].reason, who
            commissioning = _same_state(history)
            assert len(commissioning) == 1, who
            assert "source=birth" in commissioning[0].reason, who
            assert len(events[agent.id]) == 1, who
            assert events[agent.id][0]["data"]["source"] == "birth", who
            assert rt._comm_profiles[agent.id].all_skills, f"{who}: empty AD-625 comm-profile cache"

        # AD-441: the sovereign id the boot gave each crew agent is mapped to its slot in the vessel's acm.db.
        sovereign_crew = [a for a in crew if getattr(a, "sovereign_id", "")]
        assert sovereign_crew, "premise: at least one boot-wired crew agent carries a sovereign id"
        with contextlib.closing(sqlite3.connect(tmp_path / "data" / "acm.db")) as conn:
            for agent in sovereign_crew:
                rows = conn.execute(
                    "SELECT slot_id, sovereign_id FROM identity_mapping WHERE slot_id = ?", (agent.id,),
                ).fetchall()
                assert rows == [(agent.id, agent.sovereign_id)], f"{agent.agent_type} ({agent.id}): identity mapping"

        # The template upgrade still happens: the architect's PCC is raised to the post's level.
        architect = _architect(rt)
        held = {r.skill_id: r for r in (await rt.skill_service.get_profile(architect.id)).all_skills}
        assert held["communication"].proficiency == ProficiencyLevel.ADVISE

        # BF-915 (#1623): every crew type now resolves a role template, so the yeoman is commissioned under its own
        # and no 'no role template' WARNING is logged. The WARNING itself stays pinned by
        # test_bf906_acm_commissioning.py's HA8, with a type that has no template.
        yeomen = [a for a in crew if a.agent_type == "yeoman"]
        assert len(yeomen) == 1, f"premise: exactly one yeoman among the crew, got {len(yeomen)}"
        assert rt.ontology.get_role_template_for_agent("yeoman") is not None
        yeoman_record = await rt.acm.get_commissioning_record(yeomen[0].id)
        assert yeoman_record is not None and yeoman_record.role_template == "yeoman"
        assert [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and "no role template" in r.getMessage()
        ] == []
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_a_vessel_whose_crew_predate_commissioning_is_backfilled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-B2: a vessel booted without the pass is backfilled by the next boot; trust and certificates are untouched."""
    data_dir = tmp_path / "data"

    async def _no_enrollment(*, runtime: Any, boot_started_at: float) -> None:
        return None

    with monkeypatch.context() as patched:
        patched.setattr("probos.startup.crew_enrollment.enroll_boot_crew", _no_enrollment)
        first = await _boot(data_dir)
    try:
        crew_ids = sorted(a.id for a in _crew(first))
        subject_id = _architect(first).id
        # Premise: the pass did not run, so no crew member holds a lifecycle row.
        for agent_id in crew_ids:
            assert await first.acm.has_lifecycle_record(agent_id) is False, agent_id
        trust = first.trust_network.get_record(subject_id)
        assert trust is not None
        trust.alpha, trust.beta = 20.0, 2.0
        certificate = first.identity_registry.get_by_slot(subject_id)
        assert certificate is not None
    finally:
        await first.stop()

    second = await _boot(data_dir)
    try:
        assert sorted(a.id for a in _crew(second)) == crew_ids  # premise: the same crew came back
        for agent_id in crew_ids:
            born = second.identity_registry.get_by_slot(agent_id)
            assert born is not None and born.birth_timestamp < second._start_time_wall, agent_id
            record = await second.acm.get_commissioning_record(agent_id)
            assert record is not None, agent_id
            assert record.source == "backfill", agent_id
            onboarding = _onboarding(await second.acm.get_transition_history(agent_id))
            assert len(onboarding) == 1, agent_id
            assert "BF-906" in onboarding[0].reason, agent_id
            assert "source=backfill" in onboarding[0].reason, agent_id
        after = second.trust_network.get_record(subject_id)
        assert after is not None
        assert (after.alpha, after.beta) == (20.0, 2.0)
        assert second.identity_registry.get_by_slot(subject_id) == certificate
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_a_second_boot_duplicates_nothing_and_keeps_proficiency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T-B3: boot 2 commissions nobody, adds no row, grant or event, keeps LEAD, and logs no BF-906 ERROR."""
    data_dir = tmp_path / "data"
    commissioned: list[str] = []
    real_commission = AgentCapitalService.commission

    async def counting_commission(
        self: AgentCapitalService, agent_id: str, *args: Any, **kwargs: Any,
    ) -> dict[str, Any]:
        commissioned.append(agent_id)
        return await real_commission(self, agent_id, *args, **kwargs)

    monkeypatch.setattr(AgentCapitalService, "commission", counting_commission)

    first = await _boot(data_dir)
    try:
        crew_ids = sorted(a.id for a in _crew(first))
        architect_id = _architect(first).id
        # Premise: the wrapper is live, and boot 1 commissioned every crew member once.
        assert sorted(commissioned) == crew_ids
        raised = await first.skill_service.update_proficiency(
            architect_id, "communication", ProficiencyLevel.LEAD,
        )
        assert raised is not None and raised.proficiency == ProficiencyLevel.LEAD
        before = await _snapshot(first, crew_ids)
    finally:
        await first.stop()
    transitions_before = _table_count(data_dir, "lifecycle_transitions")
    records_before = _table_count(data_dir, "commissioning_records")
    # Premise: there is something to duplicate.
    assert records_before == len(crew_ids)
    assert transitions_before >= 2 * len(crew_ids)
    assert before["commissioned_events"] == len(crew_ids)
    assert all(before["records"][agent_id] is not None for agent_id in crew_ids)

    commissioned.clear()
    with caplog.at_level(logging.INFO, logger="probos.crew_enrollment"):
        second = await _boot(data_dir)
    try:
        assert sorted(a.id for a in _crew(second)) == crew_ids  # premise: the same crew came back
        after = await _snapshot(second, crew_ids)
        assert after["skills"][architect_id]["communication"].proficiency == ProficiencyLevel.LEAD
    finally:
        await second.stop()

    assert commissioned == []
    assert _table_count(data_dir, "lifecycle_transitions") == transitions_before
    assert _table_count(data_dir, "commissioning_records") == records_before
    assert after["commissioned_events"] == before["commissioned_events"]
    assert after["grants"] == before["grants"]
    assert after["history"] == before["history"]
    assert after["records"] == before["records"]
    assert after["skills"] == before["skills"]
    passes = [
        r.getMessage() for r in caplog.records
        if r.name == "probos.crew_enrollment" and "crew enrollment pass" in r.getMessage()
    ]
    assert len(passes) == 1, "premise: the capture saw boot 2's pass"
    assert f"{len(crew_ids)} crew, 0 onboarded, 0 commissioned" in passes[0]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR and "BF-906" in r.getMessage()]
    assert errors == []


@pytest.mark.asyncio
async def test_recommissioning_after_a_lost_record_keeps_existing_skills(tmp_path: Path) -> None:
    """T-B4: a lost commissioning row is re-recorded as backfill, and no skill the agent held is reset."""
    data_dir = tmp_path / "data"
    first = await _boot(data_dir)
    try:
        crew_ids = sorted(a.id for a in _crew(first))
        architect_id = _architect(first).id
        raised = await first.skill_service.update_proficiency(
            architect_id, "communication", ProficiencyLevel.LEAD,
        )
        assert raised is not None and raised.proficiency == ProficiencyLevel.LEAD
        held_before = await _levels(first, architect_id)
        assert held_before["communication"][0] == ProficiencyLevel.LEAD
        assert len(held_before) > 1, "premise: the architect holds more than the one skill that was raised"
        for agent_id in crew_ids:
            record = await first.acm.get_commissioning_record(agent_id)
            assert record is not None and record.source == "birth", agent_id
    finally:
        await first.stop()

    with contextlib.closing(sqlite3.connect(data_dir / "acm.db")) as conn:
        removed = conn.execute(
            "DELETE FROM commissioning_records WHERE agent_id = ?", (architect_id,),
        ).rowcount
        conn.commit()
    assert removed == 1, "premise: the architect's commissioning row existed and is gone"

    second = await _boot(data_dir)
    try:
        record = await second.acm.get_commissioning_record(architect_id)
        assert record is not None
        assert record.source == "backfill"
        held_after = await _levels(second, architect_id)
        assert held_after["communication"][0] == ProficiencyLevel.LEAD
        assert held_after == held_before  # every skill row's proficiency and exercise count
        for agent_id in crew_ids:
            if agent_id != architect_id:
                other = await second.acm.get_commissioning_record(agent_id)
                assert other is not None and other.source == "birth", agent_id  # their records stand
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_crew_joining_after_startup_go_through_the_same_entry_point(
    runtime: ProbOSRuntime,
) -> None:
    """T-B5: a crew pool created after startup enrolls its member at wire time, with source ``join``."""
    boot_crew_ids = {a.id for a in _crew(runtime)}

    pool = await runtime.create_pool("bf906_join", "counselor", target_size=1)

    joiners = [runtime.registry.get(agent_id) for agent_id in pool.healthy_agents]
    assert len(joiners) == 1, "premise: the pool made one member"
    joiner = joiners[0]
    assert joiner.id not in boot_crew_ids, "premise: a new agent, not a boot crew member"
    assert is_crew_agent(joiner, runtime.ontology), "premise: a counselor is crew"
    assert await runtime.acm.get_lifecycle_state(joiner.id) is LifecycleState.PROBATIONARY
    record = await runtime.acm.get_commissioning_record(joiner.id)
    assert record is not None
    assert record.source == "join"
    mine = [row for row in await _commissioned_events(runtime) if row["agent_id"] == joiner.id]
    assert len(mine) == 1
    assert mine[0]["data"]["source"] == "join"


@pytest.mark.asyncio
async def test_check_activation_moves_a_boot_wired_crew_member_at_the_threshold(
    runtime: ProbOSRuntime,
) -> None:
    """T-B9: AD-442 owns activation: a boot-wired crew member moves at the threshold and not below it."""
    subject = _architect(runtime)
    # Premise: the boot left it probationary (before BF-906 it had no lifecycle row at all).
    assert await runtime.acm.get_lifecycle_state(subject.id) is LifecycleState.PROBATIONARY

    assert await runtime.acm.check_activation(subject.id, 0.6499, 0.65) is False
    assert await runtime.acm.get_lifecycle_state(subject.id) is LifecycleState.PROBATIONARY

    assert await runtime.acm.check_activation(subject.id, 0.65, 0.65) is True
    assert await runtime.acm.get_lifecycle_state(subject.id) is LifecycleState.ACTIVE


# ---------------------------------------------------------------------------
# T-B6 to T-B8 (milestone M3): the invariant check, the doctor and the HR routes
# ---------------------------------------------------------------------------

_NO_LIFECYCLE = "No ACM lifecycle record: "


def _doctor_context(data_dir: Path) -> Any:
    from probos.doctor.protocol import DoctorContext

    return DoctorContext(config=None, home_dir=data_dir.parent, data_dir=data_dir, config_path=None)


def _fingerprint(data_dir: Path) -> dict[str, tuple[int, int]]:
    """Every file under the data directory as relative path -> (size, mtime in ns)."""
    found: dict[str, tuple[int, int]] = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            stat = path.stat()
            found[path.relative_to(data_dir).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


def _store_digests(data_dir: Path) -> dict[str, str]:
    """The sha256 of each store file the doctor reads (the boot made all three)."""
    import hashlib

    digests: dict[str, str] = {}
    for name in ("identity.db", "acm.db", "skills.db"):
        assert (data_dir / name).is_file(), f"premise: the boot left {name}"
        digests[name] = hashlib.sha256((data_dir / name).read_bytes()).hexdigest()
    return digests


@pytest.mark.asyncio
async def test_the_invariant_fails_red_when_the_pass_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T-B6: with the pass removed, boot logs one ERROR and one event row, and the doctor says FAIL and changes nothing."""
    from probos.doctor.checks.crew_enrollment_check import _CrewEnrollmentCheck
    from probos.doctor.protocol import CheckOutcome

    data_dir = tmp_path / "data"

    async def _no_enrollment(*, runtime: Any, boot_started_at: float) -> None:
        return None

    monkeypatch.setattr("probos.startup.crew_enrollment.enroll_boot_crew", _no_enrollment)
    with caplog.at_level(logging.ERROR, logger="probos.startup.crew_enrollment"):
        rt = await _boot(data_dir)
    try:
        crew_ids = sorted(a.id for a in _crew(rt))
        for agent_id in crew_ids:  # premise: the pass did not run
            assert await rt.acm.has_lifecycle_record(agent_id) is False, agent_id
        rows = await rt.event_log.query_structured(
            category="lifecycle", event="crew_invariant_failed", limit=1_000,
        )
    finally:
        await rt.stop()

    failures = [
        r.getMessage() for r in caplog.records
        if r.levelno == logging.ERROR and "crew invariant FAILED" in r.getMessage()
    ]
    assert len(failures) == 1
    for agent_id in crew_ids:
        assert agent_id in failures[0], agent_id
    assert len(rows) == 1
    assert rows[0]["data"]["checked"] == len(crew_ids)
    assert rows[0]["data"]["missing_lifecycle"] == crew_ids
    assert rows[0]["data"]["never_commissioned"] == crew_ids

    # The doctor reads the same stores, stopped, and must not change a byte or a timestamp of the data directory.
    # The plain (name, size, mtime) fingerprint is used: none of identity.db, acm.db or skills.db is a WAL store
    # today, so no -wal/-shm sidecar can appear (A2.8).
    digests = _store_digests(data_dir)
    fingerprint = _fingerprint(data_dir)
    result = await _CrewEnrollmentCheck().run(_doctor_context(data_dir))

    assert result.outcome is CheckOutcome.FAIL, result
    assert result.message == f"Crew enrollment: {len(crew_ids)} of {len(crew_ids)} crew fail the BF-906 invariant"
    assert result.remediation.splitlines()[0] == _NO_LIFECYCLE + ", ".join(crew_ids)
    assert _store_digests(data_dir) == digests  # the doctor wrote to no store
    assert _fingerprint(data_dir) == fingerprint  # and created, resized or touched no file


@pytest.mark.asyncio
async def test_after_a_real_boot_the_startup_check_and_doctor_agree_it_holds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T-B7: after a normal boot the startup check logs that the invariant holds, and the doctor reads the stores OK."""
    from probos.doctor.checks.crew_enrollment_check import _CrewEnrollmentCheck
    from probos.doctor.protocol import CheckOutcome

    data_dir = tmp_path / "data"
    with caplog.at_level(logging.INFO, logger="probos.startup.crew_enrollment"):
        rt = await _boot(data_dir)
    try:
        crew_count = len(_crew(rt))
    finally:
        await rt.stop()

    holds = [r.getMessage() for r in caplog.records if "crew invariant holds" in r.getMessage()]
    assert holds == [f"BF-906: crew invariant holds for {crew_count} crew agents"]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and "BF-906" in r.getMessage()] == []

    result = await _CrewEnrollmentCheck().run(_doctor_context(data_dir))

    assert result.outcome is CheckOutcome.OK, result
    assert result.message == (
        f"Crew enrollment: all {crew_count} crew have an ACM lifecycle record and a commissioning"
    )


@pytest.mark.asyncio
async def test_suspend_then_reinstate_crosses_route_acm_and_roster(runtime: ProbOSRuntime) -> None:
    """T-B8: the Captain's suspend and reinstate cross the route, ACM and the roster, and say they stop nothing."""
    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app

    subject = _architect(runtime)
    # Premise: the boot enrolled it (before BF-906 it had no lifecycle row, so suspend answered 409 for a worse reason).
    assert await runtime.acm.get_lifecycle_state(subject.id) is LifecycleState.PROBATIONARY

    async def roster_state(client: AsyncClient) -> str | None:
        response = await client.get("/api/crew/roster")
        assert response.status_code == 200, response.text
        mine = [entry for entry in response.json()["crew"] if entry["agent_id"] == subject.id]
        assert len(mine) == 1, f"premise: the roster lists {subject.id} once"
        return mine[0].get("lifecycle_state")

    async with AsyncClient(transport=ASGITransport(app=create_app(runtime)), base_url="http://test") as client:
        assert await roster_state(client) == "probationary"
        refused = await client.post(f"/api/acm/agents/{subject.id}/suspend", json={})
        assert refused.status_code == 409, refused.text

        assert await runtime.acm.check_activation(subject.id, 0.65, 0.65) is True  # AD-442 owns activation
        assert await roster_state(client) == "active"
        suspended = await client.post(f"/api/acm/agents/{subject.id}/suspend", json={"reason": "BF-906 T-B8"})
        assert suspended.status_code == 200, suspended.text
        body = suspended.json()
        assert body["status"] == "suspended"
        assert body["hr_status_only"] is True
        assert "AD-1343" in body["note"]
        assert await roster_state(client) == "suspended"
        agent = runtime.registry.get(subject.id)
        assert agent is not None
        # AD-1343 replaces this: today a suspension is an HR record and the agent keeps running.
        assert agent.is_alive is True

        reinstated = await client.post(f"/api/acm/agents/{subject.id}/reinstate", json={})
        assert reinstated.status_code == 200, reinstated.text
        assert reinstated.json()["hr_status_only"] is True
        assert await roster_state(client) == "active"
