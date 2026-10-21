"""AD-1346 M1a (epic #1601, checklist M1, first slice) - real-boot tests: the ``IdentityService`` facade is wired (M2).

``tests/test_ad1346_identity_service.py`` drives the facade over registries it builds itself. These tests boot a real
``ProbOSRuntime`` through every startup phase, in production order, with the mock LLM (no network and no model), as
``tests/test_bf906_crew_enrollment_boot.py`` does, and check the wiring:

- T14  after a real boot every identified agent resolves through ``runtime.identity_service`` to its own slot,
       sovereign id, DID and live callsign. On a fresh data directory no slot has a stored certificate, so the crew
       certificates are issued in Phase 7, after the facade is built at Phase 2 entry, and a crew agent that
       resolves proves the facade holds a reference, not a copy.
- T15  the facade exists when ``create_agent_fleet`` is reached (it is built before any agent is wired), and a start
       that fails there is rolled back with the facade released.
- T16  a clean ``stop()`` releases the facade together with the identity registry.
- T17  across Phase 7 on a fresh data directory, a crew slot asset-tagged at wiring keeps its slot and gains its
       certificate ref (a new sovereign id and a DID), every crew agent resolves with a DID after Phase 7, and no
       asset changes.
- T18  on the next boot over the same data directory and configuration, each crew slot with a stored certificate
       resolves to it at Phase 7 entry and after it.
- T19  on the next boot, with the utility agent pools the first boot ran without turned on, the crew slots this
       adds (none has a stored certificate) go through T17's window while the stored ones resolve as in T18: the
       window is per slot, not per boot.

Every data directory is under ``tmp_path`` and every runtime is stopped or rolled back. No test sleeps of its own, but a
clean ``stop()`` runs the production shutdown grace waits (``startup/shutdown.py``, about 3 s; T15's zero-grace config
skips them). Nothing reads the live data directory, the OS keyring (``tests/conftest.py`` forces the failing backend)
or the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig, UtilityAgentsConfig
from probos.crew_utils import is_crew_agent
from probos.identity_service import IdentityRef, IdentityService
from probos.runtime import ProbOSRuntime
from probos.startup import communication as startup_communication
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import InjectedStartFailure, inject_start_failure, lifecycle_config


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _read_the_facade_at_phase_7_entry(
    monkeypatch: pytest.MonkeyPatch, runtime: ProbOSRuntime,
) -> list[dict[str, IdentityRef | None] | None]:
    """Wrap Phase 7 (``init_communication``) so that, on entry, the facade resolves every registered agent's slot.

    A direct wrapper, not ``inject_start_failure(..., "communication")``: that helper always raises once it fires
    (``tests/fixtures/runtime_lifecycle.py:310-320``), and these boots must finish. ``runtime.py`` imports
    ``init_communication`` inside ``start()``, so the patched module attribute is the one it calls; ``monkeypatch``
    restores it. Each list entry is one Phase 7 call; None means the facade did not exist then.
    """
    original = startup_communication.init_communication
    reads: list[dict[str, IdentityRef | None] | None] = []

    async def at_phase_7_entry(*args: Any, **kwargs: Any) -> Any:
        service = runtime.identity_service
        if service is None:
            reads.append(None)
        else:
            reads.append({agent.id: service.resolve(agent.id) for agent in runtime.registry.all()})
        return await original(*args, **kwargs)

    monkeypatch.setattr(startup_communication, "init_communication", at_phase_7_entry)
    return reads


async def test_after_a_real_boot_every_identified_agent_resolves_to_its_own_slot(tmp_path: Path) -> None:
    """T14: the facade built at Phase 2 entry resolves every agent identified by the end of the boot."""
    rt = await _boot(tmp_path / "data")
    try:
        service = rt.identity_service
        assert isinstance(service, IdentityService), "premise: the boot built the facade"
        agents = list(rt.registry.all())
        crew = [a for a in agents if is_crew_agent(a, rt.ontology)]
        crew_ids = {a.id for a in crew}

        # Premises. On this fresh data directory a crew certificate is issued in Phase 7, after the facade exists, so
        # a crew agent with a DID that resolves proves a reference rather than a copy. An asset (a non-crew agent
        # holding a tag and no DID) is the other identity the facade resolves.
        assert any(a.did for a in crew), "premise: Phase 7 issued at least one crew birth certificate"
        assert any(a.sovereign_id and not a.did for a in agents if a.id not in crew_ids), (
            "premise: at least one non-crew agent holds an asset tag"
        )

        held = 0  # crew agents whose certificate UUID and DID were resolved back to the same ref
        named = 0  # crew agents whose callsign was resolved to their slot
        for agent in agents:
            if not agent.sovereign_id:
                continue  # not proved here: BF-907's finalize check covers crew without an identity
            who = f"{agent.agent_type} {agent.id}"
            ref = service.resolve(agent.id)
            assert ref is not None, f"{who} holds sovereign id {agent.sovereign_id} but resolves to None"
            assert ref.slot_id == agent.id, who
            assert ref.sovereign_id == agent.sovereign_id, who
            assert ref.did == agent.did, who
            assert ref.callsign == rt.callsign_registry.get_callsign(agent.agent_type), who
            if agent.id not in crew_ids:
                continue
            if rt.identity_registry.resolve_slot_id(agent.sovereign_id) == agent.id:
                assert service.resolve(agent.sovereign_id) == ref, f"{who}: the certificate UUID form"
                assert service.resolve(agent.did) == ref, f"{who}: the DID form"
                held += 1
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)
            live_in_pool = [a.id for a in rt.registry.get_by_pool(agent.agent_type) if a.is_alive]
            if callsign and live_in_pool == [agent.id]:  # CallsignRegistry.resolve searches the pool named by the type
                named_ref = service.resolve_callsign(callsign)
                assert named_ref is not None, f"{who}: callsign {callsign!r} resolves to None"
                assert named_ref.slot_id == agent.id, f"{who}: callsign {callsign!r}"
                named += 1
        assert held > 0, "premise: the certificate UUID and DID forms were checked for at least one crew agent"
        assert named > 0, "premise: the callsign form was checked for at least one crew agent"
    finally:
        await rt.stop()


async def test_the_facade_exists_before_the_fleet_and_a_failed_start_releases_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T15: the facade is built before ``create_agent_fleet`` runs, and the rollback of a failed start releases it."""
    monkeypatch.chdir(tmp_path)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    seen: list[IdentityService | None] = []
    failure = inject_start_failure(
        monkeypatch, runtime, "fleet_entry", on_fire=lambda rt: seen.append(rt.identity_service),
    )

    with pytest.raises(InjectedStartFailure) as raised:
        await runtime.start()

    assert raised.value is failure.error
    assert len(seen) == 1, "premise: the start reached create_agent_fleet, where the facade was read"
    assert isinstance(seen[0], IdentityService), "the facade must exist when the fleet is created"
    assert runtime.identity_service is None, "a rolled-back start must release the facade"


async def test_a_clean_stop_releases_the_facade(tmp_path: Path) -> None:
    """T16: stop() sets the facade to None, in the block that releases the identity registry."""
    rt = await _boot(tmp_path / "data")
    try:
        assert rt.identity_service is not None, "premise: the boot built the facade"
    finally:
        await rt.stop()

    assert rt.identity_service is None, "a clean stop must release the facade"


async def test_across_phase_7_a_crew_agent_keeps_its_slot_and_only_an_asset_ref_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T17: one boot on a fresh data directory, read through the facade before and after Phase 7 (AD-1346 M1a, D13).

    No slot has a stored certificate. The onboarding service is built without the ontology and receives it in
    Phase 8, so the crew test at wiring falls back to a legacy set, and a crew type outside it is asset-tagged at
    Phase 2 and certified in Phase 7 on the same slot. The crew are therefore read after the boot, from the
    ontology; no crew type is named here.
    """
    rt = ProbOSRuntime(config=_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, rt)
    await rt.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = rt.identity_service
        assert isinstance(service, IdentityService), "premise: the boot built the facade"
        assert rt.ontology is not None, "premise: Phase 7 loaded the ontology that names the crew"
        agents = list(rt.registry.all())
        crew_ids = {a.id for a in agents if is_crew_agent(a, rt.ontology)}
        assert crew_ids, "premise: the ontology names at least one crew agent"

        tagged = 0  # crew agents that resolved at Phase 7 entry
        for agent in agents:
            who = f"{agent.agent_type} {agent.id}"
            before = entry.get(agent.id)
            after = service.resolve(agent.id)
            if agent.id not in crew_ids:
                if before is not None:
                    assert after is not None and after == before, (
                        f"{who}: an asset's ref must not change across Phase 7 ({before} -> {after})"
                    )
                    assert after.did == "", f"{who}: an asset gained a DID in Phase 7"
                continue
            assert after is not None and after.did, f"{who}: a crew agent must resolve with a DID after Phase 7"
            assert after.slot_id == agent.id, who
            if before is None:
                continue  # unresolved at Phase 7 entry: deferred at wiring, or wired in Phase 7
            tagged += 1
            assert before.did == "", (
                f"{who}: before Phase 7 a crew slot with no stored certificate can hold only an asset tag: {before}"
            )
            assert before.slot_id == after.slot_id, f"{who}: Phase 7 must keep the slot"
            if before.sovereign_id != after.sovereign_id:
                assert after.did, f"{who}: a new sovereign id must come with a DID"
                assert before != after, f"{who}: a new sovereign id is a new ref (D3)"
            assert service.resolve(before.sovereign_id) == after, (
                f"{who}: the asset-tag UUID read before Phase 7 must resolve to the slot's ref after it"
            )
        assert tagged > 0, (
            "premise: no crew agent resolved at Phase 7 entry, so none was asset-tagged at wiring. Either every crew "
            "type of the ontology is now in crew_utils._WARD_ROOM_CREW, or the onboarding service gets the ontology "
            "before Phase 2. A crew slot's ref then no longer changes at Phase 7: remove this test and T19's asset "
            "premise, and in DECISIONS.md (AD-1346 M1a) drop D13's asset-then-certificate case and the matching "
            "clauses of D14 and the binding on M3."
        )
    finally:
        await rt.stop()


async def test_a_crew_slot_with_a_stored_certificate_resolves_to_it_before_and_after_phase_7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: a crew slot with a stored certificate has no Phase 7 window (AD-1346 M1a, D14).

    The identity registry loads the stored slot mappings in Phase 1 of every boot, before any agent is wired. A
    second boot over the same data directory and the same configuration therefore resolves each crew slot of the
    first boot to its certificate ref at Phase 7 entry, and Phase 7 returns the same certificate. T19 covers the
    crew slots added after a first boot that ran without their pools, which have no stored certificate.
    """
    data_dir = tmp_path / "data"
    first = await _boot(data_dir)
    try:
        first_service = first.identity_service
        assert isinstance(first_service, IdentityService), "premise: the first boot built the facade"
        first_refs = {
            a.id: first_service.resolve(a.id) for a in first.registry.all() if is_crew_agent(a, first.ontology)
        }
    finally:
        await first.stop()
    assert first_refs, "premise: the first boot has crew"
    assert all(ref is not None and ref.did for ref in first_refs.values()), (
        "premise: the first boot certified every crew agent"
    )

    second = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, second)
    await second.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = second.identity_service
        assert isinstance(service, IdentityService), "premise: the second boot built the facade"
        checked = 0
        for slot, ref in first_refs.items():
            assert ref is not None, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            early = entry[slot]
            assert early is not None, f"{slot}: a slot with a stored certificate must resolve to it before Phase 7"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 must not change a stored certificate's ref"
            checked += 1
        assert checked > 0, "premise: at least one crew slot was registered before Phase 7 of the second boot"
    finally:
        await second.stop()


async def test_after_a_config_change_the_added_crew_slots_wait_for_phase_7_and_the_stored_ones_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T19: a crew slot wired in Phase 2 with no stored certificate waits for Phase 7 (AD-1346 M1a, D14).

    The first boot runs with the utility agent pools off; the next boot over the same data directory turns them on,
    which adds crew slots that have no stored certificate. Each added slot is unresolved, or an asset ref, at Phase 7
    entry and a certificate ref with a DID on the same slot after it, as in T17; each crew slot of the first boot
    resolves to its stored certificate at Phase 7 entry and after it, as in T18. The crew are read from the ontology
    after each boot; no crew type is named here.
    """
    data_dir = tmp_path / "data"
    first_config = _config()
    first_config.utility_agents = UtilityAgentsConfig(enabled=False)
    first = ProbOSRuntime(config=first_config, data_dir=data_dir, llm_client=MockLLMClient())
    await first.start()
    try:
        first_service = first.identity_service
        assert isinstance(first_service, IdentityService), "premise: the first boot built the facade"
        stored = {
            a.id: first_service.resolve(a.id) for a in first.registry.all() if is_crew_agent(a, first.ontology)
        }
    finally:
        await first.stop()
    assert stored, "premise: the first boot has crew"
    assert all(ref is not None and ref.did for ref in stored.values()), (
        "premise: the first boot certified every crew agent"
    )

    second_config = _config()
    assert second_config.utility_agents.enabled, "premise: the utility agent pools are on by default"
    second = ProbOSRuntime(config=second_config, data_dir=data_dir, llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, second)
    await second.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = second.identity_service
        assert isinstance(service, IdentityService), "premise: the second boot built the facade"
        crew = {a.id for a in second.registry.all() if is_crew_agent(a, second.ontology)}
        assert set(stored) <= crew, "premise: the second boot keeps every crew slot of the first"
        added = crew - set(stored)
        assert added, (
            "premise: turning the utility agent pools on added no crew slot; use another configuration change that "
            "adds a crew pool (startup/agent_fleet.py)"
        )

        kept = 0  # stored crew slots read at Phase 7 entry
        for slot, ref in stored.items():
            assert ref is not None, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            early = entry[slot]
            assert early is not None, f"{slot}: a slot with a stored certificate must resolve to it before Phase 7"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 must not change a stored certificate's ref"
            kept += 1
        assert kept > 0, "premise: at least one stored crew slot was registered before Phase 7"

        deferred = 0  # added crew slots unresolved at Phase 7 entry
        tagged = 0  # added crew slots that resolved to an asset ref at Phase 7 entry
        for slot in sorted(added):
            after = service.resolve(slot)
            assert after is not None and after.did, f"{slot}: an added crew slot must resolve with a DID after Phase 7"
            assert after.slot_id == slot, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            before = entry[slot]
            if before is None:
                deferred += 1
                continue
            tagged += 1
            assert before.did == "", (
                f"{slot}: before Phase 7 a crew slot with no stored certificate can hold only an asset tag: {before}"
            )
            assert before.slot_id == after.slot_id, f"{slot}: Phase 7 must keep the slot"
            assert service.resolve(before.sovereign_id) == after, (
                f"{slot}: the asset-tag UUID read before Phase 7 must resolve to the slot's ref after it"
            )
        assert deferred > 0, "premise: at least one added crew slot was unresolved at Phase 7 entry"
        assert tagged > 0, (
            "premise: no added crew slot resolved to an asset ref at Phase 7 entry. T17's premise fails for the same "
            "cause; follow its message, and also drop this premise and the asset clause of T19's docstring."
        )
    finally:
        await second.stop()
