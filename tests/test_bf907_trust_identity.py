"""BF-907 (#1597): trust is keyed by slot id; sovereign identities resolve to their slot at the trust boundary.

Milestone M1 (Sections 1 and 2 of ``prompts/bf-907-trust-slot-keying.md``): the identity resolver
(``AgentIdentityRegistry.resolve_slot_id``, ``is_sovereign_identity_key``) and the ``TrustNetwork`` changes
(``set_identity_resolver``, the canonical key on ``record_outcome``/``get_score``/``get_record``/
``get_events_for_agent``, and ``merge_identity_records``).

Milestone M2 (Sections 3 to 5): the startup reconcile ``reconcile_trust_identities`` and the crew check
``verify_crew_trust_identity`` of ``probos.startup.trust_identity``, driven with a real ``EventLog``, and the seams
they close (dream consolidation, the header, the telemetry, warm boot).

Milestone M3 (Sections 6 and 7): the telemetry marks a trust miss instead of showing the prior, the three injected
telemetry blocks and the query sub-task ask for the slot id, the AD-589 cache holds the score the agent was shown,
correction feedback records trust on the one active agent of the type, and the memory domain still counts episodes by
the sovereign id.

Every fixture uses the live shapes (2026-10-18/19): slot ids ``surgeon_medical_surgeon_0_b2321292`` and
``counselor_counselor_0_67c601cb``, certificate UUIDs and DIDs issued by a real ``AgentIdentityRegistry``, strays near
``(2.48, 2.0)``, slot records near ``(95.0, 3.0)``. All state lives in ``tmp_path``; the live data directory is never
read. Nothing here sleeps or orders anything by wall-clock time.
"""

from __future__ import annotations

import contextlib
import importlib
import logging
import re
import sqlite3
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos.identity as identity
from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.feedback import FeedbackEngine
from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.query import QueryHandler
from probos.config import SystemConfig, format_trust
from probos.consensus.trust import TrustNetwork
from probos.identity import AgentBirthCertificate, AgentIdentityRegistry
from probos.mesh.routing import HebbianRouter
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.storage.sqlite_factory import default_factory
from probos.substrate.event_log import EventLog
from probos.substrate.registry import AgentRegistry
from probos.types import Episode
from probos.warm_boot import WarmBootService

INSTANCE_ID = "bf907-ship"
SURGEON_SLOT = "surgeon_medical_surgeon_0_b2321292"
SURGEON_SECOND_SLOT = "surgeon_medical_surgeon_1_9d41e0aa"
COUNSELOR_SLOT = "counselor_counselor_0_67c601cb"
OPERATIONS_SLOT = "operations_officer_operations_officer_0_adb55c01"  # Nova's live slot id
TOOL_SLOT = "calculator_calculator_0_5f3a9c1e"
RUNTIME_ID = "24ca56be31064c24a102afbceaff6636"  # a dashless 32-hex runtime agent id (the BaseAgent default)
PEER_KEY = "federation_peer:ship-b"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path: Path):
    """A real identity registry in ``tmp_path``, started and commissioned as tests/test_ad1196_did_key_binding.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name="Bf907", version="1")
        yield reg
    finally:
        await reg.stop()


@pytest_asyncio.fixture
async def trust(tmp_path: Path):
    """A real ``TrustNetwork`` over ``tmp_path/trust.db``."""
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"))
    await network.start()
    try:
        yield network
    finally:
        await network.stop()


@pytest_asyncio.fixture
async def event_log(tmp_path: Path):
    """A real ``EventLog`` over ``tmp_path/events.db``."""
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _issue(
    reg: AgentIdentityRegistry,
    slot_id: str = SURGEON_SLOT,
    agent_type: str = "surgeon",
    callsign: str = "Meridian",
    department: str = "medical",
    post_id: str = "surgeon",
) -> AgentBirthCertificate:
    """Issue (or resolve) the birth certificate of a slot through the real registry."""
    return await reg.resolve_or_issue(
        slot_id=slot_id, agent_type=agent_type, callsign=callsign, instance_id=INSTANCE_ID,
        vessel_name="Bf907", department=department, post_id=post_id, baseline_version="v1",
    )


async def _seed(network: TrustNetwork, rows: dict[str, tuple[float, float]]) -> None:
    """Hold ``rows`` as live ones are held: in memory and, after a save, in trust.db."""
    for key, (alpha, beta) in rows.items():
        network.create_with_prior(key, alpha, beta)
    await network.save()


def _db(network: TrustNetwork) -> Path:
    return Path(str(network.db_path))


def _raw(network: TrustNetwork) -> dict[str, tuple[float, float]]:
    return {key: (row["alpha"], row["beta"]) for key, row in network.raw_scores().items()}


def _file_rows(db_path: Path) -> dict[str, tuple[float, float]]:
    """``trust_scores`` as the file holds it, read through an independent connection."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as con:
        return {row[0]: (row[1], row[2]) for row in con.execute("SELECT agent_id, alpha, beta FROM trust_scores")}


def _count(db_path: Path, table: str) -> int:
    with contextlib.closing(sqlite3.connect(str(db_path))) as con:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # fixed table names only


def _startup() -> Any:
    """``probos.startup.trust_identity``, imported when a test needs it (a missing module fails that test, not the collection)."""
    return importlib.import_module("probos.startup.trust_identity")


async def _reconcile(
    network: TrustNetwork, reg: AgentIdentityRegistry, log: EventLog, active_ids: set[str],
) -> Any:
    """The startup reconcile, called as ``init_structural_services`` calls it."""
    return await _startup().reconcile_trust_identities(
        trust_network=network, identity_registry=reg, active_ids=set(active_ids), event_log=log,
    )


async def _merge_events(log: EventLog) -> list[dict[str, Any]]:
    """The ``trust_identity_merge`` rows the event log holds (``query`` hands them back newest first)."""
    return [row for row in await log.query(category="trust", limit=1000) if row["event"] == "trust_identity_merge"]


def _merge_rows(db_path: Path) -> dict[str, dict[str, Any]]:
    """``trust_key_merges`` as the file holds it, keyed by source key."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as con:
        con.row_factory = sqlite3.Row
        return {row["source_key"]: dict(row) for row in con.execute("SELECT * FROM trust_key_merges")}


def _module_log(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    """What ``probos.startup.trust_identity`` logged, as ``(level, message)``."""
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "probos.startup.trust_identity"]


def _header_agent(slot_id: str, sovereign_id: str, network: TrustNetwork) -> CognitiveAgent:
    """A cognitive agent whose slot id differs from its sovereign id, built as ``_sensorium_agent_metrics`` needs it.

    As ``tests/test_ad588_telemetry_introspection.py::_make_cognitive_agent`` builds one, but with ``id != sovereign_id``
    (that helper sets ``sovereign_id = id``, which is why the split was invisible).
    """
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = slot_id
    agent.sovereign_id = sovereign_id
    agent._runtime = SimpleNamespace(trust_network=network, config=SystemConfig())
    return agent


def _telemetry(network: TrustNetwork) -> IntrospectiveTelemetryService:
    """The real telemetry service over ``network`` (only its trust domain is under test here)."""
    return IntrospectiveTelemetryService(runtime=SimpleNamespace(trust_network=network, registry=None))


async def _register_agents(*agents: tuple[str, str | None]) -> AgentRegistry:
    """A real ``AgentRegistry`` holding one stand-in agent per ``(slot id, sovereign id)``."""
    agent_registry = AgentRegistry()
    for slot_id, sovereign_id in agents:
        await agent_registry.register(
            SimpleNamespace(id=slot_id, sovereign_id=sovereign_id, agent_type="stand-in", pool="bf907", capabilities=[]),
        )
    return agent_registry


class _ObservedConnection:
    """Test-local connection wrapper: forwards every call.

    ``observe`` sees each ``execute`` statement before it runs; ``fail_on`` raises on a statement with that prefix.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.fail_on: str | None = None
        self.observe: Callable[[str], None] | None = None

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        if self.observe is not None:
            self.observe(sql)
        if self.fail_on is not None and sql.lstrip().startswith(self.fail_on):
            raise sqlite3.OperationalError("disk I/O error (simulated by the test)")
        return self._inner.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _ObservedFactory:
    """Test-local connection factory handing ``TrustNetwork`` an ``_ObservedConnection``."""

    def __init__(self) -> None:
        self.connection: _ObservedConnection | None = None

    async def connect(self, db_path: str) -> _ObservedConnection:
        self.connection = _ObservedConnection(await default_factory.connect(db_path))
        return self.connection


class _FakeTelemetry:
    """Test-local telemetry: answers ``get_trust_state`` from a table and remembers whom it was asked about."""

    def __init__(self, states: dict[str, dict[str, Any]]) -> None:
        self.states = states
        self.subjects: list[str] = []

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]:
        self.subjects.append(agent_id)
        return self.states.get(agent_id, {})


class _StubKnowledgeStore:
    """Test-local knowledge store for warm boot: it holds a trust snapshot and nothing else (the real one is git-backed)."""

    def __init__(self, trust_snapshot: dict[str, dict[str, float]]) -> None:
        self._trust_snapshot = trust_snapshot

    async def load_trust_snapshot(self) -> dict[str, dict[str, float]]:
        return self._trust_snapshot

    async def load_routing_weights(self) -> None:
        return None

    async def load_agents(self) -> None:
        return None

    async def load_skills(self) -> None:
        return None

    async def load_workflows(self) -> None:
        return None

    async def load_qa_reports(self) -> None:
        return None


async def _unused(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("warm boot reached a step this test leaves empty")


def _warm_boot(network: TrustNetwork, trust_snapshot: dict[str, dict[str, float]]) -> WarmBootService:
    """The real ``WarmBootService`` over a stub knowledge store that holds only ``trust_snapshot``."""
    return WarmBootService(
        knowledge_store=_StubKnowledgeStore(trust_snapshot),
        trust_network=network,
        hebbian_router=SimpleNamespace(),
        episodic_memory=None,
        workflow_cache=None,
        config=SystemConfig(),
        register_designed_agent_fn=_unused,
        create_designed_pool_fn=_unused,
        add_skill_to_agents_fn=_unused,
        qa_reports={},
        pools={},
    )


# ---------------------------------------------------------------------------
# Section 1: the identity resolver
# ---------------------------------------------------------------------------


async def test_resolve_slot_id_maps_certificate_did_and_asset_uuid(registry: AgentIdentityRegistry) -> None:
    """A certificate UUID, its agent DID and an asset-tag UUID each resolve to their slot (kills R15)."""
    cert = await _issue(registry)
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    # premise: real, distinct sovereign identities, none of them a slot id
    assert registry.get_by_slot(SURGEON_SLOT) is cert
    assert uuid.UUID(cert.agent_uuid).version == 4
    assert uuid.UUID(tag.asset_uuid).version == 4
    assert cert.did == f"did:probos:{INSTANCE_ID}:{cert.agent_uuid}"
    assert tag.slot_id == TOOL_SLOT
    assert len({SURGEON_SLOT, TOOL_SLOT, cert.agent_uuid, cert.did, tag.asset_uuid}) == 5

    for key in (cert.agent_uuid, cert.did, tag.asset_uuid):
        assert identity.is_sovereign_identity_key(key) is True, key
    assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
    assert registry.resolve_slot_id(cert.did) == SURGEON_SLOT
    assert registry.resolve_slot_id(tag.asset_uuid) == TOOL_SLOT


async def test_resolve_slot_id_returns_none_for_slot_peer_unknown_and_ambiguous(
    registry: AgentIdentityRegistry, caplog: pytest.LogCaptureFixture,
) -> None:
    """Anything that is not one identity bound to one slot resolves to None (kills R13)."""
    cert = await _issue(registry)
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    # premise: the certificate resolves while it is bound to one slot, and that call logs no BF-907 diagnostic
    with caplog.at_level(logging.DEBUG, logger="probos.identity"):
        assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
    assert [
        record.getMessage() for record in caplog.records
        if record.name == "probos.identity" and record.getMessage().startswith("BF-907: identity")
    ] == []
    caplog.clear()

    # the live non-candidate shapes and every other key that is not a sovereign identity
    for key in (SURGEON_SLOT, TOOL_SLOT, RUNTIME_ID, "system", "captain", PEER_KEY, "mcp-peer:tool-x", "device:usb-1", ""):
        assert identity.is_sovereign_identity_key(key) is False, key
        assert registry.resolve_slot_id(key) is None, key
    for key in (None, 7, b"24ca56be31064c24a102afbceaff6636"):
        assert identity.is_sovereign_identity_key(key) is False, key  # type: ignore[arg-type]
        assert registry.resolve_slot_id(key) is None, key  # type: ignore[arg-type]

    # shaped like an identity, bound to nothing: unknown certificate UUID, unknown DID, the ship DID, a malformed DID
    unknown_uuid = str(uuid.uuid4())
    assert identity.is_sovereign_identity_key(unknown_uuid) is True
    for key in (
        unknown_uuid,
        f"did:probos:{INSTANCE_ID}:{unknown_uuid}",
        f"did:probos:{INSTANCE_ID}",
        f"did:probos:{INSTANCE_ID}:{unknown_uuid}:extra",
    ):
        assert registry.resolve_slot_id(key) is None, key

    # ambiguous: the same certificate bound to a second slot resolves to neither
    ok, _message = await registry.reassign_slot(cert.agent_uuid, SURGEON_SECOND_SLOT)
    assert ok is True
    assert registry.get_by_slot(SURGEON_SLOT) is cert
    assert registry.get_by_slot(SURGEON_SECOND_SLOT) is cert
    with caplog.at_level(logging.DEBUG, logger="probos.identity"):
        assert registry.resolve_slot_id(cert.agent_uuid) is None
    ambiguity_logs = [
        record.getMessage() for record in caplog.records if record.name == "probos.identity"
    ]
    assert ambiguity_logs == [f"BF-907: identity {cert.agent_uuid} is bound to 2 slots; not resolved"]
    assert registry.resolve_slot_id(cert.did) is None
    # an unrelated asset tag still resolves
    assert registry.resolve_slot_id(tag.asset_uuid) == TOOL_SLOT


async def test_resolve_slot_id_survives_registry_restart(tmp_path: Path) -> None:
    """The asset index is rebuilt by ``start`` from identity.db, not only filled by issuance (kills R14)."""
    data_dir = tmp_path / "identity"
    first = AgentIdentityRegistry(data_dir=data_dir)
    try:
        await first.start()
        await first.start(instance_id=INSTANCE_ID, vessel_name="Bf907", version="1")
        cert = await _issue(first)
        tag = await first.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    finally:
        await first.stop()

    second = AgentIdentityRegistry(data_dir=data_dir)
    try:
        await second.start()
        await second.start(instance_id=INSTANCE_ID, vessel_name="Bf907", version="1")
        # premise: a new registry object that loaded both identities from the file
        assert second is not first
        loaded_cert = second.get_by_slot(SURGEON_SLOT)
        assert loaded_cert is not None and loaded_cert.agent_uuid == cert.agent_uuid
        loaded_tag = second.get_asset_by_slot(TOOL_SLOT)
        assert loaded_tag is not None and loaded_tag.asset_uuid == tag.asset_uuid

        assert second.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
        assert second.resolve_slot_id(cert.did) == SURGEON_SLOT
        assert second.resolve_slot_id(tag.asset_uuid) == TOOL_SLOT
    finally:
        await second.stop()


# ---------------------------------------------------------------------------
# Section 2: the TrustNetwork boundary
# ---------------------------------------------------------------------------


async def test_trust_reads_by_sovereign_identity_return_the_slot_record(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """Reads by certificate UUID and by DID equal the slot's, observation count and events included (kills R2-R5)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0)})
    trust.record_outcome(SURGEON_SLOT, True, intent_type="proactive_think", episode_id="ep-1")
    trust.record_outcome(SURGEON_SLOT, True, intent_type="proactive_think", episode_id="ep-2")
    trust.set_identity_resolver(registry.resolve_slot_id)

    # premise: trust is keyed by slot only, the slot reads far from the prior, and it carries two events
    assert set(_raw(trust)) == {SURGEON_SLOT, COUNSELOR_SLOT}
    slot_record = trust.get_record(SURGEON_SLOT)
    assert slot_record is not None
    assert slot_record.score > 0.9
    assert slot_record.observations > 90.0
    slot_events = trust.get_events_for_agent(SURGEON_SLOT)
    assert len(slot_events) == 2

    for identity_key in (cert.agent_uuid, cert.did):
        assert trust.get_score(identity_key) == trust.get_score(SURGEON_SLOT)
        assert trust.get_score(identity_key) != 0.5
        assert trust.get_record(identity_key) is slot_record
        assert trust.get_record(identity_key).observations == slot_record.observations  # type: ignore[union-attr]
        assert trust.get_events_for_agent(identity_key) == slot_events
        assert trust.get_events_for_agent(identity_key, n=1) == slot_events[-1:]
    # a read creates nothing
    assert set(_raw(trust)) == {SURGEON_SLOT, COUNSELOR_SLOT}

    # an identity bound to nothing, and a key that is no identity, read as before: the prior and no record
    unknown = str(uuid.uuid4())
    for other_key in (unknown, PEER_KEY):
        assert trust.get_score(other_key) == 0.5
        assert trust.get_record(other_key) is None
        assert trust.get_events_for_agent(other_key) == []


async def test_record_outcome_by_sovereign_identity_moves_the_slot_record_and_creates_no_stray(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """A write by certificate UUID or DID lands on the slot record, its event and dampening included (kills R1, R5)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0)})
    trust.set_identity_resolver(registry.resolve_slot_id)
    # premise: one record, keyed by the slot, at the seeded value; nothing under either identity
    assert _raw(trust) == {SURGEON_SLOT: (95.0, 3.0)}

    score = trust.record_outcome(cert.agent_uuid, True, intent_type="dream_consolidation", episode_id="ep-1")
    after_uuid = _raw(trust)
    assert set(after_uuid) == {SURGEON_SLOT}  # no stray
    assert after_uuid[SURGEON_SLOT][0] > 95.0  # the slot's alpha rose
    assert after_uuid[SURGEON_SLOT][1] == 3.0
    assert score == pytest.approx(trust.get_score(SURGEON_SLOT))
    # the event follows the slot
    events = trust.get_events_for_agent(SURGEON_SLOT)
    assert [event.agent_id for event in events] == [SURGEON_SLOT]
    assert trust.get_events_for_agent(cert.agent_uuid) == events

    # a write by DID lands on the same slot record
    trust.record_outcome(cert.did, True, intent_type="dream_consolidation", episode_id="ep-2")
    after_did = _raw(trust)
    assert set(after_did) == {SURGEON_SLOT}
    assert after_did[SURGEON_SLOT][0] > after_uuid[SURGEON_SLOT][0]
    assert [event.agent_id for event in trust.get_events_for_agent(SURGEON_SLOT)] == [SURGEON_SLOT, SURGEON_SLOT]


async def test_trust_without_resolver_is_unchanged(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """Backward compatibility: with no resolver a key is exactly the key given. Pins today's behaviour; no new API."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0)})
    # premise: no resolver is bound, and nothing is held under the certificate UUID
    assert _raw(trust) == {SURGEON_SLOT: (95.0, 3.0)}

    # reads: a certificate UUID is an unknown key
    assert trust.get_score(cert.agent_uuid) == 0.5
    assert trust.get_record(cert.agent_uuid) is None
    assert trust.get_events_for_agent(cert.agent_uuid) == []

    # a write keys the record by exactly the id it was given, and the slot is untouched
    trust.record_outcome(cert.agent_uuid, True, intent_type="dream_consolidation", episode_id="ep-1")
    raw = _raw(trust)
    assert set(raw) == {SURGEON_SLOT, cert.agent_uuid}
    assert raw[SURGEON_SLOT] == (95.0, 3.0)
    assert raw[cert.agent_uuid][0] > 2.0
    assert raw[cert.agent_uuid][1] == 2.0
    record = trust.get_record(cert.agent_uuid)
    assert record is not None and record.agent_id == cert.agent_uuid
    assert trust.get_score(cert.agent_uuid) > 0.5
    assert [event.agent_id for event in trust.get_events_for_agent(cert.agent_uuid)] == [cert.agent_uuid]
    assert trust.get_events_for_agent(SURGEON_SLOT) == []

    # a slot-keyed write behaves as it always did
    trust.record_outcome(SURGEON_SLOT, True, intent_type="proactive_think", episode_id="ep-2")
    assert trust.get_record(SURGEON_SLOT).alpha > 95.0  # type: ignore[union-attr]
    assert [event.agent_id for event in trust.get_events_for_agent(SURGEON_SLOT)] == [SURGEON_SLOT]


# ---------------------------------------------------------------------------
# Section 2: merge_identity_records
# ---------------------------------------------------------------------------


async def test_merge_counts_the_prior_once(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """Slot (5.0, 2.0) plus stray (2.48, 2.0) over the prior (2, 2) is (5.48, 2.0), not the prior twice (kills R6, R7)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (5.0, 2.0), cert.agent_uuid: (2.48, 2.0)})
    # premise: the network prior is (2, 2); the stray holds 0.48 of evidence above it
    assert (trust.prior_alpha, trust.prior_beta) == (2.0, 2.0)
    assert _raw(trust) == {SURGEON_SLOT: (5.0, 2.0), cert.agent_uuid: (2.48, 2.0)}

    merges, refused = await trust.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

    assert refused == {}
    record = trust.get_record(SURGEON_SLOT)
    assert record is not None
    assert (record.alpha, record.beta) == pytest.approx((5.48, 2.0), abs=1e-9)
    assert record.score == pytest.approx(0.7326, abs=5e-5)
    # not the prior counted twice: (7.48, 4.0), score 0.6516
    assert (record.alpha, record.beta) != pytest.approx((7.48, 4.0), abs=1e-6)
    assert record.score != pytest.approx(0.6516, abs=5e-5)
    [merge] = merges
    assert (merge.source_key, merge.target_key) == (cert.agent_uuid, SURGEON_SLOT)
    assert (merge.source_alpha, merge.source_beta) == (2.48, 2.0)
    assert (merge.target_alpha_before, merge.target_beta_before) == (5.0, 2.0)
    assert (merge.prior_alpha, merge.prior_beta) == (2.0, 2.0)
    assert (merge.alpha_after, merge.beta_after) == pytest.approx((5.48, 2.0), abs=1e-9)


async def test_merge_keeps_a_probationary_slot_prior(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """A slot created with prior (1.0, 3.0) keeps it: stray (2.2, 2.0) gives (1.2, 3.0), not (2.2, 2.0)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (1.0, 3.0), cert.agent_uuid: (2.2, 2.0)})
    # premise: the slot's prior is not the network prior
    assert _raw(trust)[SURGEON_SLOT] == (1.0, 3.0)
    assert (trust.prior_alpha, trust.prior_beta) == (2.0, 2.0)

    merges, refused = await trust.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

    assert refused == {} and len(merges) == 1
    record = trust.get_record(SURGEON_SLOT)
    assert record is not None
    assert (record.alpha, record.beta) == pytest.approx((1.2, 3.0), abs=1e-9)
    # subtracting the slot's own prior instead of the network prior would give (2.2, 2.0)
    assert (record.alpha, record.beta) != pytest.approx((2.2, 2.0), abs=1e-6)


async def test_merge_two_sources_one_target(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """A UUID stray and a DID stray of one agent both add to its slot, the second on top of the first (kills R9)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0), cert.did: (2.1, 2.0)})
    pairs = {cert.agent_uuid: SURGEON_SLOT, cert.did: SURGEON_SLOT}
    # premise: two strays held by key, one slot, and both identities resolve to it
    assert set(_raw(trust)) == {SURGEON_SLOT, cert.agent_uuid, cert.did}
    for key, slot in pairs.items():
        assert registry.resolve_slot_id(key) == slot, key

    merges, refused = await trust.merge_identity_records(pairs)

    assert refused == {}
    assert len(merges) == 2
    assert {merge.source_key for merge in merges} == set(pairs)
    first, second = merges  # the order is the sorted source key; the chain below does not depend on it
    evidence = {cert.agent_uuid: 0.48, cert.did: 0.10}
    assert (first.target_alpha_before, first.target_beta_before) == (95.0, 3.0)
    assert first.alpha_after == pytest.approx(95.0 + evidence[first.source_key], abs=1e-9)
    # the second merge starts from the first's result, not from the slot's stored value again
    assert (second.target_alpha_before, second.target_beta_before) == (first.alpha_after, first.beta_after)
    assert second.alpha_after == pytest.approx(95.0 + 0.48 + 0.10, abs=1e-9)
    assert second.beta_after == pytest.approx(3.0, abs=1e-9)
    # memory and file hold the sum, and neither stray
    assert _raw(trust)[SURGEON_SLOT] == pytest.approx((95.58, 3.0), abs=1e-9)
    assert set(_raw(trust)) == {SURGEON_SLOT}
    assert _file_rows(_db(trust)) == _raw(trust)


async def test_merge_refuses_a_source_below_the_prior(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """A source under the network prior is refused with ``below_prior`` and left untouched (kills R8)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (1.9, 2.0)})
    before_memory = _raw(trust)
    before_file = _file_rows(_db(trust))
    # premise: the stray holds less alpha than the prior
    assert before_memory[cert.agent_uuid] == (1.9, 2.0)
    assert before_file == before_memory

    merges, refused = await trust.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

    assert merges == ()
    assert refused == {cert.agent_uuid: "below_prior"}
    # kept: memory and file untouched, and nothing recorded
    assert _raw(trust) == before_memory
    assert _file_rows(_db(trust)) == before_file
    assert _count(_db(trust), "trust_snapshots") == 0
    assert _count(_db(trust), "trust_key_merges") == 0


async def test_merge_snapshot_holds_every_record_and_the_restore_sql_reverses_it(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """The snapshot holds every record as it stood, and the contract's restore SQL puts the file back (kills R10)."""
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    pre = {
        SURGEON_SLOT: (95.0, 3.0),
        COUNSELOR_SLOT: (123.5, 3.0),
        TOOL_SLOT: (2.0, 2.0),
        RUNTIME_ID: (2.0, 2.0),
        PEER_KEY: (2.0, 2.0),
        surgeon.agent_uuid: (2.48, 2.0),
        counselor.agent_uuid: (2.1, 2.0),
    }
    await _seed(trust, pre)
    db = _db(trust)
    # premise: trust.db holds exactly the rows the merge is about to change
    assert _file_rows(db) == pre

    merges, refused = await trust.merge_identity_records(
        {surgeon.agent_uuid: SURGEON_SLOT, counselor.agent_uuid: COUNSELOR_SLOT},
    )

    assert refused == {} and len(merges) == 2
    snapshot_ids = {merge.snapshot_id for merge in merges}
    assert len(snapshot_ids) == 1
    snapshot_id = snapshot_ids.pop()
    # the merge changed the file, so the restore below reverses something
    merged_file = _file_rows(db)
    assert merged_file != pre
    assert surgeon.agent_uuid not in merged_file and counselor.agent_uuid not in merged_file
    # the snapshot holds every in-memory record as it stood, including those the merge did not touch
    with contextlib.closing(sqlite3.connect(str(db))) as con:
        snapshot = {
            row[0]: (row[1], row[2])
            for row in con.execute(
                "SELECT agent_id, alpha, beta FROM trust_snapshots WHERE snapshot_id = ?", (snapshot_id,),
            )
        }
    assert snapshot == pre

    # the restore SQL of the contract's reversal procedure, on the closed file
    await trust.stop()
    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM trust_scores")
        con.execute(
            "INSERT INTO trust_scores (agent_id, alpha, beta, updated) "
            "SELECT agent_id, alpha, beta, taken_at FROM trust_snapshots WHERE snapshot_id = :id",
            {"id": snapshot_id},
        )
        con.execute("COMMIT")
    finally:
        con.close()
    assert _file_rows(db) == pre


async def test_merge_persists_and_a_rerun_is_a_noop(registry: AgentIdentityRegistry, trust: TrustNetwork) -> None:
    """The merge is on disk and in memory at once; running it again writes nothing, in this process or after a restart.

    M1 half of contract item 13: the pairs are explicit and the merge is called on the network itself;
    ``test_reconcile_rerun_writes_nothing_in_process_and_after_a_restart`` is the M2 half, through
    ``reconcile_trust_identities`` and the event log. This half kills R11 (source row not deleted) and R12 (source not
    removed from memory): ``reconcile_trust_identities`` runs AD-280 after the merge, which would hide a source that
    was not removed from memory.
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.58, 2.0)})
    db = _db(trust)
    pairs = {cert.agent_uuid: SURGEON_SLOT}
    # premise: one stray held by key that resolves to its slot, and the file agrees with memory
    assert set(_raw(trust)) == {SURGEON_SLOT, cert.agent_uuid}
    for key, slot in pairs.items():
        assert registry.resolve_slot_id(key) == slot, key
    assert _file_rows(db) == _raw(trust)

    merges, refused = await trust.merge_identity_records(pairs)

    assert refused == {} and len(merges) == 1
    merged = _raw(trust)
    assert set(merged) == {SURGEON_SLOT}
    assert merged[SURGEON_SLOT] == pytest.approx((95.58, 3.0), abs=1e-9)
    # on disk at the commit, before any save: no stray row, the merged slot row
    assert _file_rows(db) == merged
    assert _count(db, "trust_key_merges") == 1
    snapshot_rows = _count(db, "trust_snapshots")
    assert snapshot_rows == 2  # the slot and the stray, as they stood

    # same process: no identity key is left in memory, nothing written
    assert set(_raw(trust)) == {SURGEON_SLOT}
    assert await trust.merge_identity_records({}) == ((), {})
    assert _count(db, "trust_snapshots") == snapshot_rows
    assert _count(db, "trust_key_merges") == 1
    assert _raw(trust) == merged

    # after a restart: the stray does not come back, no identity key is in memory, nothing written
    await trust.stop()
    reopened = TrustNetwork(db_path=str(db))
    await reopened.start()
    try:
        assert _raw(reopened) == merged
        assert set(_raw(reopened)) == {SURGEON_SLOT}
        assert await reopened.merge_identity_records({}) == ((), {})
        assert _count(db, "trust_snapshots") == snapshot_rows
        assert _count(db, "trust_key_merges") == 1
        assert _raw(reopened) == merged
    finally:
        await reopened.stop()


async def test_merge_failure_rolls_back_and_keeps_records(registry: AgentIdentityRegistry, tmp_path: Path) -> None:
    """A write that fails inside the merge transaction leaves the file and memory exactly as they were.

    M1 half of contract item 17: the merge raises (the reason ``merge_failed`` and the ERROR log belong to
    ``reconcile_trust_identities``, Section 3, M2). The connection wrapper is test-local.
    """
    cert = await _issue(registry)
    factory = _ObservedFactory()
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"), connection_factory=factory)
    await network.start()
    try:
        await _seed(network, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), cert.agent_uuid: (2.48, 2.0)})
        db = _db(network)
        before_memory = _raw(network)
        before_file = _file_rows(db)
        # premise: file and memory agree, the stray is there, and the wrapper is the live connection
        assert before_file == before_memory
        assert cert.agent_uuid in before_memory
        assert factory.connection is not None
        factory.connection.fail_on = "INSERT INTO trust_key_merges"

        with pytest.raises(sqlite3.OperationalError, match="simulated by the test"):
            await network.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

        # memory unchanged
        assert _raw(network) == before_memory
        # file unchanged: the rows, and neither new table holds anything (the statements before the failure rolled back)
        assert _file_rows(db) == before_file
        assert _count(db, "trust_snapshots") == 0
        assert _count(db, "trust_key_merges") == 0
        # the failure left no lock behind: a synchronous trust write is accepted at once
        network.record_outcome(COUNSELOR_SLOT, True)
        # and a retry on a healthy connection merges
        factory.connection.fail_on = None
        merges, refused = await network.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})
        assert refused == {} and len(merges) == 1
        assert cert.agent_uuid not in _raw(network)
        assert _count(db, "trust_key_merges") == 1
    finally:
        await network.stop()


# ---------------------------------------------------------------------------
# Coverage additions beyond the numbered list: branches of the new code the numbered tests do not reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("answer", [None, "", 7], ids=["none", "empty", "not-a-string"])
async def test_canonical_key_keeps_the_given_key_when_the_resolver_has_no_usable_answer(
    trust: TrustNetwork, answer: Any,
) -> None:
    """D3: an identity the resolver cannot map is recorded and read under the key it was given."""
    unknown = str(uuid.uuid4())
    trust.set_identity_resolver(lambda key: answer)
    # premise: nothing is held
    assert _raw(trust) == {}

    trust.record_outcome(unknown, True, intent_type="dream_consolidation", episode_id="ep-1")

    assert set(_raw(trust)) == {unknown}
    assert trust.get_record(unknown) is not None
    assert [event.agent_id for event in trust.get_events_for_agent(unknown)] == [unknown]


async def test_merge_refuses_a_missing_source_and_a_source_that_is_its_own_target(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """``source_missing`` and ``target_is_source`` are refused; nothing is written and nothing changes."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)})
    absent = str(uuid.uuid4())
    before_memory = _raw(trust)
    before_file = _file_rows(_db(trust))
    # premise: the absent key holds no record
    assert absent not in before_memory

    merges, refused = await trust.merge_identity_records({absent: SURGEON_SLOT, cert.agent_uuid: cert.agent_uuid})

    assert merges == ()
    assert refused == {absent: "source_missing", cert.agent_uuid: "target_is_source"}
    assert _raw(trust) == before_memory
    assert _file_rows(_db(trust)) == before_file
    assert _count(_db(trust), "trust_snapshots") == 0
    assert _count(_db(trust), "trust_key_merges") == 0


async def test_merge_into_a_slot_without_a_record_creates_it_at_the_prior_plus_the_evidence(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """A slot with no record starts from the network prior; the stray's evidence above it is all that moves."""
    cert = await _issue(registry)
    await _seed(trust, {cert.agent_uuid: (2.48, 2.0)})
    # premise: the slot has no record
    assert trust.get_record(SURGEON_SLOT) is None

    merges, refused = await trust.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

    assert refused == {}
    [merge] = merges
    assert (merge.target_alpha_before, merge.target_beta_before) == (2.0, 2.0)
    assert set(_raw(trust)) == {SURGEON_SLOT}
    assert _raw(trust)[SURGEON_SLOT] == pytest.approx((2.48, 2.0), abs=1e-9)
    assert _file_rows(_db(trust)) == _raw(trust)


async def test_merge_on_a_network_without_a_store_raises(registry: AgentIdentityRegistry) -> None:
    """A network that was never started has no trust.db to merge in: the merge raises and changes nothing."""
    cert = await _issue(registry)
    network = TrustNetwork()
    network.create_with_prior(SURGEON_SLOT, 95.0, 3.0)
    network.create_with_prior(cert.agent_uuid, 2.48, 2.0)
    before = _raw(network)

    with pytest.raises(RuntimeError, match="trust_store_not_started"):
        await network.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

    assert _raw(network) == before


async def test_merge_blocks_synchronous_trust_writers_until_it_commits(
    registry: AgentIdentityRegistry, tmp_path: Path,
) -> None:
    """While the merge transaction is open a synchronous trust write is refused; after the commit it is accepted."""
    cert = await _issue(registry)
    factory = _ObservedFactory()
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"), connection_factory=factory)
    await network.start()
    try:
        await _seed(network, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), cert.agent_uuid: (2.48, 2.0)})
        seen: list[str] = []

        def observe(sql: str) -> None:
            if sql.startswith("INSERT INTO trust_key_merges"):
                try:
                    network.record_outcome(COUNSELOR_SLOT, True)
                except RuntimeError as exc:
                    seen.append(str(exc))
                else:
                    seen.append("accepted")

        assert factory.connection is not None
        factory.connection.observe = observe

        merges, refused = await network.merge_identity_records({cert.agent_uuid: SURGEON_SLOT})

        assert refused == {} and len(merges) == 1
        assert seen == ["trust_write_in_progress"]
        network.record_outcome(COUNSELOR_SLOT, True)  # the flag is cleared at the end of the merge
    finally:
        await network.stop()


# ---------------------------------------------------------------------------
# Sections 3 to 5 (M2): the startup reconcile, the seams it closes, and the crew check
# ---------------------------------------------------------------------------


async def test_dream_consolidation_with_sovereign_episode_ids_moves_slot_score_and_header_and_telemetry_agree(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """The seam (contract item 7): dream consolidation writes by the sovereign id its episodes carry.

    After the startup reconcile that write lands on the slot record and creates no stray, and the header and the
    telemetry show one score for the agent. Kills R16 (the resolver is not bound) together with
    ``test_telemetry_differs_from_header_until_bound``.
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)})
    # premise: the agent's slot id and sovereign id differ, the stray is held by key, and the identity resolves
    assert cert.agent_uuid != SURGEON_SLOT
    assert set(_raw(trust)) == {SURGEON_SLOT, cert.agent_uuid}
    assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT

    result = await _reconcile(trust, registry, event_log, {SURGEON_SLOT})

    assert [merge.source_key for merge in result.merged] == [cert.agent_uuid]
    merged = _raw(trust)
    assert set(merged) == {SURGEON_SLOT}
    # the dream engine as tests/test_trust_concurrency.py builds it (config trust_boost 0.1), over the real network
    engine = object.__new__(DreamingEngine)
    engine._agent_id = "dream-agent"
    engine._agent_type = "dream"
    engine.config = SimpleNamespace(trust_boost=0.1, trust_penalty=0.1)
    engine.trust_network = trust
    episodes = [
        Episode(
            user_input=f"bf907 task {n}", timestamp=float(n), agent_ids=[cert.agent_uuid],
            outcomes=[{"success": True}], dag_summary={},
        )
        for n in (1, 2)
    ]

    assert engine._consolidate_trust(episodes) == 1

    after = _raw(trust)
    assert set(after) == {SURGEON_SLOT}  # the write by the sovereign id created no stray
    assert after[SURGEON_SLOT][0] > merged[SURGEON_SLOT][0]  # the slot alpha rose
    assert after[SURGEON_SLOT][1] == merged[SURGEON_SLOT][1]
    slot_score = format_trust(trust.get_score(SURGEON_SLOT))
    # the header: what the agent reads about itself
    header = _header_agent(SURGEON_SLOT, cert.agent_uuid, trust)._sensorium_agent_metrics({})
    assert header.startswith(f"Your trust: {slot_score} | Initiative:")
    # the telemetry for the slot: the same score, with its observations
    snapshot = await _telemetry(trust).get_full_snapshot(SURGEON_SLOT)
    record = trust.get_record(SURGEON_SLOT)
    assert record is not None
    assert snapshot["trust"]["score"] == slot_score
    assert snapshot["trust"]["observations"] == int(record.observations)
    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)
    assert f"Trust: {slot_score} (" in rendered
    assert f"{int(record.observations)} observations" in rendered


async def test_telemetry_differs_from_header_until_bound(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """The red-without-fix contrast (contract item 19).

    Before the startup reconcile binds trust to the identity registry, a telemetry read by the sovereign id (what the
    DM, Ward Room and proactive blocks held) lands on the stray and differs from the header; after it, the two agree.
    Kills R16 together with the seam test.
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)})
    agent = _header_agent(SURGEON_SLOT, cert.agent_uuid, trust)
    telemetry = _telemetry(trust)
    header_before = format_trust(trust.get_score(SURGEON_SLOT))
    # premise: no resolver is bound (the sovereign id reads its own stray record, not the slot's), and the
    # header shows the slot's score
    assert trust.get_record(cert.agent_uuid) is not trust.get_record(SURGEON_SLOT)
    assert format_trust(trust.get_score(cert.agent_uuid)) != header_before
    assert agent._sensorium_agent_metrics({}).startswith(f"Your trust: {header_before} | Initiative:")

    before = await telemetry.get_trust_state(cert.agent_uuid)

    assert before["score"] == format_trust(trust.get_score(cert.agent_uuid))
    assert before["score"] != header_before

    result = await _reconcile(trust, registry, event_log, {SURGEON_SLOT})

    assert [merge.source_key for merge in result.merged] == [cert.agent_uuid]
    header_after = format_trust(trust.get_score(SURGEON_SLOT))
    after = await telemetry.get_trust_state(cert.agent_uuid)
    assert agent._sensorium_agent_metrics({}).startswith(f"Your trust: {header_after} | Initiative:")
    assert after["score"] == header_after
    record = trust.get_record(SURGEON_SLOT)
    assert record is not None
    assert after["observations"] == int(record.observations)


async def test_merge_event_recorded_in_event_log(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """One ``trust_identity_merge`` event per merge, carrying the merge's evidence (contract item 14).

    Kills R29 (the constant's value) together with the AD-1195 resolved-pair freeze.
    """
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    await _seed(trust, {
        SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0),
        surgeon.agent_uuid: (2.48, 2.0), counselor.agent_uuid: (2.1, 2.0),
    })
    # premise: the constant is the name the census freezes, and the log holds nothing yet
    assert _startup().MERGE_EVENT == "trust_identity_merge"
    assert await event_log.count_all() == 0

    result = await _reconcile(trust, registry, event_log, {SURGEON_SLOT, COUNSELOR_SLOT})

    assert {merge.source_key for merge in result.merged} == {surgeon.agent_uuid, counselor.agent_uuid}
    events = await _merge_events(event_log)
    assert len(events) == 2
    assert await event_log.count_all() == 2  # nothing else was logged
    rows = _merge_rows(_db(trust))
    expected = {
        surgeon.agent_uuid: (SURGEON_SLOT, 95.0, 3.0, 0.48),
        counselor.agent_uuid: (COUNSELOR_SLOT, 123.5, 3.0, 0.10),
    }
    assert {event["data"]["source_key"] for event in events} == set(expected)
    for event in events:
        data = event["data"]
        slot, alpha_before, beta_before, evidence = expected[data["source_key"]]
        row = rows[data["source_key"]]
        assert event["category"] == "trust"
        assert event["event"] == "trust_identity_merge"
        assert event["agent_id"] == slot
        assert event["detail"] == f"BF-907: {data['source_key']} merged into {slot}"
        assert data["target_key"] == slot
        assert data["alpha_before"] == alpha_before
        assert data["beta_before"] == beta_before
        assert data["delta_alpha"] == pytest.approx(evidence, abs=1e-9)
        assert data["delta_beta"] == pytest.approx(0.0, abs=1e-9)
        assert data["alpha_after"] == pytest.approx(alpha_before + evidence, abs=1e-9)
        assert data["beta_after"] == pytest.approx(beta_before, abs=1e-9)
        # the event and the trust_key_merges row describe the same merge
        assert data["merged_at"] == row["merged_at"]
        assert data["snapshot_id"] == row["snapshot_id"]
        assert data["alpha_after"] == row["alpha_after"]
        assert data["beta_after"] == row["beta_after"]


async def test_unmapped_identity_record_is_kept_and_reported(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog, caplog: pytest.LogCaptureFixture,
) -> None:
    """An identity key that cannot be merged is kept with its reason and survives AD-280 (contract item 15).

    An unknown certificate UUID is ``unresolved``; the certificate of a slot with no active agent is
    ``slot_inactive``. Kills R18 (an inactive slot is merged into) and R19 (AD-280 deletes the kept keys).
    """
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    unknown = str(uuid.uuid4())
    active = {SURGEON_SLOT}
    await _seed(trust, {
        SURGEON_SLOT: (95.0, 3.0), unknown: (2.1, 2.0), counselor.agent_uuid: (2.58, 2.0), "system": (2.0, 2.0),
    })
    before = _file_rows(_db(trust))
    # premise: both identity keys are shaped like a sovereign identity; the unknown one resolves to nothing, the
    # counselor's to a slot that has no active agent; `system` is the stale key AD-280 exists to remove
    assert identity.is_sovereign_identity_key(unknown) and identity.is_sovereign_identity_key(counselor.agent_uuid)
    assert registry.resolve_slot_id(unknown) is None
    assert registry.resolve_slot_id(counselor.agent_uuid) == COUNSELOR_SLOT
    assert COUNSELOR_SLOT not in active
    assert before == _raw(trust)

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        result = await _reconcile(trust, registry, event_log, active)

    assert result.merged == ()
    assert result.kept == {unknown: "unresolved", counselor.agent_uuid: "slot_inactive"}
    assert result.removed == 1  # AD-280 ran: the stale key went, the identity keys did not
    assert _raw(trust) == {key: value for key, value in before.items() if key != "system"}
    # nothing was merged, so nothing was written
    assert _file_rows(_db(trust)) == before
    assert (_count(_db(trust), "trust_snapshots"), _count(_db(trust), "trust_key_merges")) == (0, 0)
    assert await event_log.count_all() == 0
    log = _module_log(caplog)
    assert sorted(message for level, message in log if level == logging.WARNING) == sorted([
        f"BF-907: trust record {unknown} kept unmerged (unresolved)",
        f"BF-907: trust record {counselor.agent_uuid} kept unmerged (slot_inactive)",
    ])
    assert (logging.INFO, "BF-907 trust identity merge: merged=0 kept=2") in log


async def test_non_identity_stale_keys_are_still_removed_by_ad280(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog, caplog: pytest.LogCaptureFixture,
) -> None:
    """A dashless runtime id, ``system`` and ``captain`` are no sovereign identity: AD-280 still removes them (item 16).

    Kills R17 (every stale key is treated as an identity candidate and kept).
    """
    stale = (RUNTIME_ID, "system", "captain")
    await _seed(trust, {TOOL_SLOT: (2.0, 2.0), **{key: (2.0, 2.0) for key in stale}})
    # premise: three stale keys that are no sovereign identity and resolve to nothing, beside one active slot
    for key in stale:
        assert identity.is_sovereign_identity_key(key) is False, key
        assert registry.resolve_slot_id(key) is None, key
    assert set(_raw(trust)) == {TOOL_SLOT, *stale}

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        result = await _reconcile(trust, registry, event_log, {TOOL_SLOT})

    assert result.removed == 3
    assert result.kept == {}
    assert result.merged == ()
    assert set(_raw(trust)) == {TOOL_SLOT}
    assert _raw(trust)[TOOL_SLOT] == (2.0, 2.0)
    assert _module_log(caplog) == [(logging.INFO, "BF-907 trust identity merge: merged=0 kept=0")]


async def test_unaffected_vessel_writes_nothing(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """A vessel with no identity-keyed record is not touched: nothing snapshotted, merged or logged (contract item 18)."""
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0)})
    before = _file_rows(_db(trust))
    # premise: slot keys only, the file agrees with memory, and no table or log row exists yet
    assert set(before) == {SURGEON_SLOT, COUNSELOR_SLOT}
    assert before == _raw(trust)
    assert (_count(_db(trust), "trust_snapshots"), _count(_db(trust), "trust_key_merges")) == (0, 0)
    assert await event_log.count_all() == 0

    result = await _reconcile(trust, registry, event_log, {SURGEON_SLOT, COUNSELOR_SLOT})

    assert (result.merged, result.kept, result.removed) == ((), {}, 0)
    assert _raw(trust) == before
    assert _file_rows(_db(trust)) == before
    assert (_count(_db(trust), "trust_snapshots"), _count(_db(trust), "trust_key_merges")) == (0, 0)
    assert await event_log.count_all() == 0
    # trust is bound all the same: an identity read lands on the slot record
    assert trust.get_record(cert.agent_uuid) is trust.get_record(SURGEON_SLOT)


async def test_reconcile_rerun_writes_nothing_in_process_and_after_a_restart(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """M2 half of contract item 13: the reconcile merges once; a rerun finds nothing and writes nothing.

    The event log holds one ``trust_identity_merge`` row per first-run merge and none after, in this process or
    after ``stop()`` and a new network ``start()``. (The M1 half kills R12; here a source row that was not deleted from
    trust.db, R11, would come back after the restart and merge a second time.)
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.58, 2.0)})
    db = _db(trust)
    active = {SURGEON_SLOT}
    # premise: one stray that resolves to its slot, the file agrees with memory, and nothing is recorded yet
    assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
    assert _file_rows(db) == _raw(trust)
    assert (_count(db, "trust_snapshots"), _count(db, "trust_key_merges"), await event_log.count_all()) == (0, 0, 0)

    first = await _reconcile(trust, registry, event_log, active)

    assert [merge.source_key for merge in first.merged] == [cert.agent_uuid]
    merged = _raw(trust)
    assert set(merged) == {SURGEON_SLOT}
    assert merged[SURGEON_SLOT] == pytest.approx((95.58, 3.0), abs=1e-9)
    assert _file_rows(db) == merged
    written = (_count(db, "trust_snapshots"), _count(db, "trust_key_merges"), await event_log.count_all())
    assert written == (2, 1, 1)  # the slot and the stray as they stood, one merge, one event
    assert len(await _merge_events(event_log)) == 1

    # the same process: nothing to merge, nothing written
    again = await _reconcile(trust, registry, event_log, active)
    assert (again.merged, again.kept, again.removed) == ((), {}, 0)
    assert (_count(db, "trust_snapshots"), _count(db, "trust_key_merges"), await event_log.count_all()) == written
    assert _raw(trust) == merged

    # after a restart: the stray did not come back, nothing to merge, nothing written
    await trust.stop()
    reopened = TrustNetwork(db_path=str(db))
    await reopened.start()
    try:
        assert _raw(reopened) == merged
        restarted = await _reconcile(reopened, registry, event_log, active)
        assert (restarted.merged, restarted.kept, restarted.removed) == ((), {}, 0)
        assert (_count(db, "trust_snapshots"), _count(db, "trust_key_merges"), await event_log.count_all()) == written
        assert len(await _merge_events(event_log)) == 1
        assert _raw(reopened) == merged
    finally:
        await reopened.stop()


async def test_reconcile_merge_failure_is_logged_keeps_the_record_and_ad280_still_runs(
    registry: AgentIdentityRegistry, tmp_path: Path, event_log: EventLog, caplog: pytest.LogCaptureFixture,
) -> None:
    """M2 half of contract item 17: a merge that fails does not stop the reconcile.

    The failure is reported as ``merge_failed`` with an ERROR log, trust.db and memory are as they were, AD-280 still
    runs with the identity key kept (``removed`` counts only the real stale key), and the next start merges the
    same stray.
    """
    cert = await _issue(registry)
    factory = _ObservedFactory()
    network = TrustNetwork(db_path=str(tmp_path / "trust.db"), connection_factory=factory)
    await network.start()
    try:
        await _seed(network, {
            SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), cert.agent_uuid: (2.48, 2.0), RUNTIME_ID: (2.0, 2.0),
        })
        db = _db(network)
        active = {SURGEON_SLOT, COUNSELOR_SLOT}
        before_file = _file_rows(db)
        # premise: the file agrees with memory, the stray resolves to an active slot, the stale key is no identity,
        # and the wrapper is the live connection
        assert before_file == _raw(network)
        assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
        assert identity.is_sovereign_identity_key(RUNTIME_ID) is False
        assert factory.connection is not None
        factory.connection.fail_on = "INSERT INTO trust_key_merges"

        with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
            result = await _reconcile(network, registry, event_log, active)

        assert result.merged == ()
        assert result.kept == {cert.agent_uuid: "merge_failed"}
        assert result.removed == 1  # AD-280 ran: the stale runtime id went, the kept identity key did not
        # memory: the merge changed nothing; only the stale key is gone (AD-280 acts on memory)
        assert _raw(network) == {key: value for key, value in before_file.items() if key != RUNTIME_ID}
        # file: exactly as it was, and neither new table holds a row
        assert _file_rows(db) == before_file
        assert (_count(db, "trust_snapshots"), _count(db, "trust_key_merges")) == (0, 0)
        assert await event_log.count_all() == 0
        errors = [record for record in caplog.records if record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "trust identity merge failed and was rolled back" in errors[0].getMessage()
        assert errors[0].exc_info is not None
        assert (logging.WARNING, f"BF-907: trust record {cert.agent_uuid} kept unmerged (merge_failed)") in _module_log(caplog)

        # the next start, on a healthy store: the same stray merges
        factory.connection.fail_on = None
        retried = await _reconcile(network, registry, event_log, active)
        assert [merge.source_key for merge in retried.merged] == [cert.agent_uuid]
        assert retried.kept == {}
        assert set(_raw(network)) == active
        assert _count(db, "trust_key_merges") == 1
    finally:
        await network.stop()


async def test_warm_boot_restore_of_a_pre_merge_snapshot_re_merges_to_the_same_values(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """D11: a death before the knowledge-store flush restores the pre-merge records, and the merge reruns to the same values.

    Warm boot force-sets every key of ``snapshot.json`` over ``trust.db`` before structural services run, and the
    merge writes ``trust.db`` only. The rerun comes with a second snapshot, merge rows and events. A stray the
    snapshot holds but ``trust.db`` never had (no ``trust_scores`` row) merges too, and its DELETE is a no-op.
    """
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    active = {SURGEON_SLOT, COUNSELOR_SLOT}
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), surgeon.agent_uuid: (2.48, 2.0)})
    db = _db(trust)
    # the knowledge-store snapshot as its last flush wrote it: the pre-merge records, and a stray trust.db never had
    snapshot = trust.raw_scores()
    snapshot[counselor.agent_uuid] = {"alpha": 2.58, "beta": 2.0}
    # premise: the snapshot holds a stray that trust.db does not, and both identities resolve to active slots
    assert surgeon.agent_uuid in snapshot and counselor.agent_uuid in snapshot
    assert counselor.agent_uuid not in _file_rows(db)
    assert registry.resolve_slot_id(surgeon.agent_uuid) == SURGEON_SLOT
    assert registry.resolve_slot_id(counselor.agent_uuid) == COUNSELOR_SLOT

    first = await _reconcile(trust, registry, event_log, active)

    assert [merge.source_key for merge in first.merged] == [surgeon.agent_uuid]
    first_values = _raw(trust)
    assert set(first_values) == active
    assert first_values[SURGEON_SLOT] == pytest.approx((95.48, 3.0), abs=1e-9)
    assert _count(db, "trust_key_merges") == 1

    # the process dies before the next flush: a new network starts on the same file, then warm boot restores the snapshot
    await trust.stop()
    reopened = TrustNetwork(db_path=str(db))
    await reopened.start()
    try:
        assert _raw(reopened) == first_values  # trust.db holds the merged state
        await _warm_boot(reopened, snapshot).restore()
        restored = _raw(reopened)
        # premise: the pre-merge state is back, both strays included
        assert set(restored) == active | {surgeon.agent_uuid, counselor.agent_uuid}
        assert restored[SURGEON_SLOT] == (95.0, 3.0)
        assert restored[surgeon.agent_uuid] == (2.48, 2.0)
        assert restored[counselor.agent_uuid] == (2.58, 2.0)

        second = await _reconcile(reopened, registry, event_log, active)

        assert {merge.source_key for merge in second.merged} == {surgeon.agent_uuid, counselor.agent_uuid}
        assert second.kept == {}
        assert second.removed == 0
        final = _raw(reopened)
        assert set(final) == active  # no sovereign key remains
        assert final[SURGEON_SLOT] == first_values[SURGEON_SLOT]  # the same values as the first merge
        assert final[COUNSELOR_SLOT] == pytest.approx((124.08, 3.0), abs=1e-9)  # 123.5 plus the stray's 0.58 above the prior
        assert _file_rows(db) == final
        # a second set of rows: the second run's two merges on top of the first run's one, under two snapshots
        assert _count(db, "trust_key_merges") == 3
        with contextlib.closing(sqlite3.connect(str(db))) as con:
            assert con.execute("SELECT COUNT(DISTINCT snapshot_id) FROM trust_key_merges").fetchone()[0] == 2
        assert len(await _merge_events(event_log)) == 3
    finally:
        await reopened.stop()


async def test_a_certificate_imported_from_a_peer_ship_resolves_to_its_slot_and_its_stray_merges(
    tmp_path: Path, trust: TrustNetwork, event_log: EventLog,
) -> None:
    """``resolve_slot_id`` resolves a birth-certificate UUID "native or foreign"; the reconcile merges a stray keyed by it.

    The foreign certificate sits in a slot the registry holds, loaded by ``AgentIdentityRegistry.start`` (AD-443b), as
    ``tests/test_bf906_doctor_check.py::_seed_transferred_in_slot`` places one: the signed import needs a second
    ship's chain, so the row ``import_transfer_certificate`` writes is inserted into the store the real registry made.
    """
    data_dir = tmp_path / "identity"
    seeder = AgentIdentityRegistry(data_dir=data_dir)
    try:
        await seeder.start()
        await seeder.start(instance_id=INSTANCE_ID, vessel_name="Bf907", version="1")
    finally:
        await seeder.stop()
    foreign_uuid = str(uuid.uuid4())
    foreign_did = f"did:probos:other-inst:{foreign_uuid}"
    with contextlib.closing(sqlite3.connect(data_dir / "identity.db")) as conn:
        conn.execute(
            "INSERT INTO foreign_birth_certificates (agent_uuid, did, agent_type, callsign, instance_id, "
            "vessel_name, birth_timestamp, department, post_id, baseline_version, certificate_hash, "
            "certificate_vc_json, origin_ship_did, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                foreign_uuid, foreign_did, "surgeon", "Visitor", "other-inst", "Other Ship",
                1.0, "medical", "surgeon", "v0", f"hash-{foreign_uuid}", "{}", "did:probos:other-ship", 2.0,
            ),
        )
        conn.execute("INSERT OR REPLACE INTO slot_mappings (slot_id, agent_uuid) VALUES (?, ?)", (SURGEON_SLOT, foreign_uuid))
        conn.commit()
    reg = AgentIdentityRegistry(data_dir=data_dir)
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name="Bf907", version="1")
        await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), foreign_uuid: (2.48, 2.0), foreign_did: (2.1, 2.0)})
        # premise: the slot holds the foreign certificate (not a native one), and both keys have a sovereign shape
        held = reg.get_by_slot(SURGEON_SLOT)
        assert held is not None
        assert (held.agent_uuid, held.instance_id) == (foreign_uuid, "other-inst")
        assert reg.get_by_uuid(foreign_uuid) is held
        assert uuid.UUID(foreign_uuid).version == 4
        assert identity.is_sovereign_identity_key(foreign_uuid) and identity.is_sovereign_identity_key(foreign_did)

        assert reg.resolve_slot_id(foreign_uuid) == SURGEON_SLOT
        assert reg.resolve_slot_id(foreign_did) == SURGEON_SLOT

        result = await _reconcile(trust, reg, event_log, {SURGEON_SLOT})

        assert {merge.source_key for merge in result.merged} == {foreign_uuid, foreign_did}
        assert result.kept == {}
        assert set(_raw(trust)) == {SURGEON_SLOT}
        assert _raw(trust)[SURGEON_SLOT] == pytest.approx((95.0 + 0.48 + 0.10, 3.0), abs=1e-9)
        assert _file_rows(_db(trust)) == _raw(trust)
    finally:
        await reg.stop()


async def test_crew_check_reports_a_consistent_crew(
    registry: AgentIdentityRegistry, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """Every crew member's telemetry trust equals its header trust: one INFO line and no problem (contract item 20)."""
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    operations = await _issue(registry, OPERATIONS_SLOT, "operations_officer", "Nova", "operations", "chief_operations")
    await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    await _seed(trust, {
        SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), OPERATIONS_SLOT: (93.2, 3.0), TOOL_SLOT: (2.0, 2.0),
    })
    agents = await _register_agents(
        (SURGEON_SLOT, surgeon.agent_uuid), (COUNSELOR_SLOT, counselor.agent_uuid),
        (OPERATIONS_SLOT, operations.agent_uuid), (TOOL_SLOT, None),
    )
    # premise: four registered agents, three of them with a birth certificate (the tool holds an asset tag), each
    # certified one holds its certificate as sovereign_id, and trust is keyed by slot ids only
    assert agents.count == 4
    assert registry.get_by_slot(TOOL_SLOT) is None
    for agent in agents.all():
        cert = registry.get_by_slot(agent.id)
        assert (cert is None) == (agent.id == TOOL_SLOT), agent.id
        if cert is not None:
            assert agent.sovereign_id == cert.agent_uuid
    assert set(_raw(trust)) == {SURGEON_SLOT, COUNSELOR_SLOT, OPERATIONS_SLOT, TOOL_SLOT}

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        crew, problems = await _startup().verify_crew_trust_identity(
            trust_network=trust, identity_registry=registry, registry=agents, telemetry=_telemetry(trust),
        )

    assert (crew, problems) == (3, ())
    assert _module_log(caplog) == [(logging.INFO, "BF-907 trust identity check: crew=3 consistent=3")]


async def test_crew_check_reports_mismatch_and_missing_sovereign_id(
    registry: AgentIdentityRegistry, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """A crew member without its certificate as sovereign_id, and one whose telemetry differs from its header (item 21).

    Kills R27 (the telemetry comparison is dropped) and R28 (the sovereign_id comparison is dropped).
    """
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    operations = await _issue(registry, OPERATIONS_SLOT, "operations_officer", "Nova", "operations", "chief_operations")
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), OPERATIONS_SLOT: (93.2, 3.0)})
    # the surgeon's sovereign_id is empty (the BaseAgent default); the telemetry reads the prior for the counselor
    agents = await _register_agents(
        (SURGEON_SLOT, ""), (COUNSELOR_SLOT, counselor.agent_uuid), (OPERATIONS_SLOT, operations.agent_uuid),
    )
    headers = {slot: format_trust(trust.get_score(slot)) for slot in (SURGEON_SLOT, COUNSELOR_SLOT, OPERATIONS_SLOT)}
    states: dict[str, dict[str, Any]] = {}
    for slot in headers:
        record = trust.get_record(slot)
        assert record is not None
        states[slot] = {"score": headers[slot], "observations": int(record.observations)}
    states[COUNSELOR_SLOT] = {"score": 0.5, "observations": 7}
    telemetry = _FakeTelemetry(states)
    # premise: the counselor's header is far from the prior its telemetry reports, the surgeon's sovereign_id is
    # not its certificate, and the other two agree with their certificates and headers
    assert headers[COUNSELOR_SLOT] != 0.5
    assert agents.get(SURGEON_SLOT).sovereign_id != surgeon.agent_uuid  # type: ignore[union-attr]
    assert agents.get(COUNSELOR_SLOT).sovereign_id == counselor.agent_uuid  # type: ignore[union-attr]
    assert agents.get(OPERATIONS_SLOT).sovereign_id == operations.agent_uuid  # type: ignore[union-attr]

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        crew, problems = await _startup().verify_crew_trust_identity(
            trust_network=trust, identity_registry=registry, registry=agents, telemetry=telemetry,
        )

    missing = f"Meridian: sovereign_id '' is not its certificate {surgeon.agent_uuid}"
    differs = f"Ezri: telemetry trust 0.5 is not header {headers[COUNSELOR_SLOT]}"
    assert crew == 3
    assert problems == (missing, differs)
    assert telemetry.subjects == [SURGEON_SLOT, COUNSELOR_SLOT, OPERATIONS_SLOT]  # asked by slot id, in registry order
    assert _module_log(caplog) == [
        (logging.WARNING, f"BF-907 trust identity check: crew=3 consistent=1; {missing}; {differs}"),
    ]


async def test_crew_check_reports_a_record_still_keyed_by_its_identity_and_telemetry_without_a_record(
    registry: AgentIdentityRegistry, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """The remaining branches of the crew check: an identity-keyed record left behind, a telemetry state with no
    observations, and no telemetry service at all."""
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0), surgeon.did: (2.48, 2.0)})
    agents = await _register_agents((SURGEON_SLOT, surgeon.agent_uuid), (COUNSELOR_SLOT, counselor.agent_uuid))
    headers = {slot: format_trust(trust.get_score(slot)) for slot in (SURGEON_SLOT, COUNSELOR_SLOT)}
    # the counselor's telemetry carries the right score but counts no observations: it found no record
    states: dict[str, dict[str, Any]] = {
        SURGEON_SLOT: {"score": headers[SURGEON_SLOT], "observations": 96},
        COUNSELOR_SLOT: {"score": headers[COUNSELOR_SLOT]},
    }
    # premise: the surgeon's DID is still a trust key, and every sovereign_id is its certificate
    assert surgeon.did in _raw(trust)
    assert agents.get(SURGEON_SLOT).sovereign_id == surgeon.agent_uuid  # type: ignore[union-attr]
    assert agents.get(COUNSELOR_SLOT).sovereign_id == counselor.agent_uuid  # type: ignore[union-attr]

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        crew, problems = await _startup().verify_crew_trust_identity(
            trust_network=trust, identity_registry=registry, registry=agents, telemetry=_FakeTelemetry(states),
        )

    assert crew == 2
    assert problems == (
        "Meridian: a trust record is still keyed by its sovereign identity",
        f"Ezri: telemetry trust {headers[COUNSELOR_SLOT]} is not header {headers[COUNSELOR_SLOT]}",
    )
    assert [level for level, _message in _module_log(caplog)] == [logging.WARNING]

    # no telemetry service: the telemetry check fails for every crew member
    crew, problems = await _startup().verify_crew_trust_identity(
        trust_network=trust, identity_registry=registry, registry=agents, telemetry=None,
    )

    assert crew == 2
    assert problems == (
        "Meridian: a trust record is still keyed by its sovereign identity",
        f"Meridian: telemetry trust no record is not header {headers[SURGEON_SLOT]}",
        f"Ezri: telemetry trust no record is not header {headers[COUNSELOR_SLOT]}",
    )


# ---------------------------------------------------------------------------
# Coverage additions beyond the numbered list: the wiring of Sections 4 and 5, through two real boots
# ---------------------------------------------------------------------------


def _boot_config() -> SystemConfig:
    """As ``tests/test_bf906_crew_enrollment_boot.py::_config``: no naming ceremony, no proactive loop, no QA."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path) -> ProbOSRuntime:
    """A real ``ProbOSRuntime`` through every startup phase with the mock LLM (no network, no model), as bf906 boots one."""
    runtime = ProbOSRuntime(config=_boot_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


async def test_a_real_boot_merges_a_stray_and_checks_the_crew(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Sections 4 and 5 through two real boots: the reconcile gets the identity registry and the event log, and the
    crew check runs at the end of finalize.

    Nothing else in this module calls ``init_structural_services`` or ``finalize_startup``, so a removed call or a wrong
    argument at either site would pass every other test. Boot 1 leaves a stray, keyed by a crew member's certificate
    UUID, in trust.db. Boot 2, on the same data directory, must bind trust to the identity registry, merge the stray
    into its slot (one ``trust_key_merges`` row, one event) and report a consistent crew. The slot's absolute value is
    not asserted: boot activity may move it.
    """
    data_dir = tmp_path / "data"
    first = await _boot(data_dir)
    try:
        crew = sorted(
            agent.id for agent in first.registry.all()
            if first.identity_registry.get_by_slot(agent.id) is not None
            and first.trust_network.get_record(agent.id) is not None
        )
        assert crew, "premise: the boot wired crew that hold a birth certificate and a trust record"
        slot = crew[0]
        cert = first.identity_registry.get_by_slot(slot)
        assert cert is not None
        assert cert.agent_uuid != slot
        slot_record = first.trust_network.get_record(slot)
        assert slot_record is not None
        # as T-B2 does: a slot score far from the 0.5 prior, so a read that misses the slot cannot equal it by accident
        slot_record.alpha, slot_record.beta = 20.0, 2.0
        first.trust_network.create_with_prior(cert.agent_uuid, 2.5, 2.0)
        await first.trust_network.save()
        db = Path(str(first.trust_network.db_path))
    finally:
        await first.stop()
    # premise: boot 1 left the stray in the file boot 2 loads, and nothing has been merged yet
    assert db.is_relative_to(data_dir)
    assert _file_rows(db)[cert.agent_uuid] == (2.5, 2.0)
    assert slot in _file_rows(db)
    assert _count(db, "trust_key_merges") == 0

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        second = await _boot(data_dir)
    try:
        trust = second.trust_network
        # premise: the same slot came back, holding the same certificate
        assert second.registry.get(slot) is not None
        assert second.identity_registry.get_by_slot(slot) == cert
        # (a) no identity key is left as a trust key
        assert cert.agent_uuid not in trust.raw_scores()
        assert cert.did not in trust.raw_scores()
        # (b) the real boot bound the resolver: a read by the certificate UUID is the slot's, and the slot is off the prior
        assert trust.get_score(slot) != 0.5
        assert trust.get_score(cert.agent_uuid) == trust.get_score(slot)
        # (d) one merge event
        merge_events = [
            row for row in await second.event_log.query(category="trust", limit=1000)
            if row["event"] == "trust_identity_merge"
        ]
        assert len(merge_events) == 1
        assert merge_events[0]["data"]["source_key"] == cert.agent_uuid
    finally:
        await second.stop()

    # (c) trust.db holds the one merge, of the stray into the slot, with the stray's 0.5 of evidence above the prior
    assert _count(db, "trust_key_merges") == 1
    row = _merge_rows(db)[cert.agent_uuid]
    assert (row["source_key"], row["target_key"]) == (cert.agent_uuid, slot)
    assert row["alpha_after"] - row["target_alpha_before"] == pytest.approx(0.5)
    # (e) the reconcile and the crew check logged their results, and the whole crew is consistent
    info = [message for level, message in _module_log(caplog) if level == logging.INFO]
    assert "BF-907 trust identity merge: merged=1 kept=0" in info, _module_log(caplog)
    checks = [re.fullmatch(r"BF-907 trust identity check: crew=(\d+) consistent=(\d+)", message) for message in info]
    checked = [match for match in checks if match is not None]
    assert len(checked) == 1, _module_log(caplog)
    crew_count, consistent = (int(number) for number in checked[0].groups())
    assert crew_count == consistent >= 1, _module_log(caplog)


# ---------------------------------------------------------------------------
# Milestone M3. Section 6: telemetry. Section 7: correction feedback by agent type
# ---------------------------------------------------------------------------

TELEMETRY_LOGGER = "probos.cognitive.introspective_telemetry"
FEEDBACK_LOGGER = "probos.cognitive.feedback"
INTROSPECTIVE_TEXT = "How is your trust score?"  # a question CognitiveAgent._is_introspective_query accepts


class _RecordingTelemetry:
    """Test-local telemetry service: remembers the subject of every ``get_full_snapshot`` and renders as the real one."""

    def __init__(self) -> None:
        self.subjects: list[str] = []

    async def get_full_snapshot(self, agent_id: str, *, extra_domains: tuple[str, ...] = ()) -> dict[str, Any]:
        self.subjects.append(agent_id)
        return {"trust": {"score": 0.9694, "observations": 96}}

    def render_telemetry_context(self, snapshot: dict[str, Any]) -> str:
        return IntrospectiveTelemetryService.render_telemetry_context(snapshot)


class _EmptyHebbianRouter:
    """Test-local Hebbian router with no connections (the social domain reads only ``all_weights_typed``)."""

    def all_weights_typed(self) -> dict[tuple[str, str, str], float]:
        return {}


class _RecordingMemory:
    """Test-local episodic memory: counts episodes per subject id and remembers whom it was asked about (as AD-1259's)."""

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.subjects: list[str] = []

    @property
    def is_available(self) -> bool:
        return True

    async def count_for_agent(self, agent_id: str) -> int:
        self.subjects.append(agent_id)
        return self.counts[agent_id]


class _StubEpisodicMemory:
    """Test-local episodic memory for the feedback engine: it keeps the episodes it is asked to store."""

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


def _injection_runtime(network: TrustNetwork, service: Any = None) -> SimpleNamespace:
    """The runtime the injected-telemetry call sites read, as ``test_ad1258_self_knowledge._consumer_telemetry_runtime``
    builds one. ``service`` is the telemetry service; with none, it is the real one over this same runtime."""
    runtime = SimpleNamespace(
        config=SystemConfig(), registry=None, episodic_memory=None, trust_network=network,
        hebbian_router=_EmptyHebbianRouter(), is_cold_start=False,
    )
    runtime._introspective_telemetry = IntrospectiveTelemetryService(runtime=runtime) if service is None else service
    return runtime


def _telemetry_miss_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The BF-907 trust-miss warnings the telemetry service logged."""
    return [
        record.getMessage() for record in caplog.records
        if record.name == TELEMETRY_LOGGER and record.levelno == logging.WARNING and "BF-907" in record.getMessage()
    ]


async def _inject_proactive(runtime: SimpleNamespace, agent: CognitiveAgent) -> str:
    """The proactive block: ``ProactiveCognitiveLoop._gather_context`` puts the rendered telemetry in the context."""
    loop = ProactiveCognitiveLoop()
    loop.set_runtime(runtime)
    context = await loop._gather_context(agent, 0.5124)
    return str(context.get("introspective_telemetry", ""))


async def _inject_dm(runtime: SimpleNamespace, agent: CognitiveAgent) -> str:
    """The DM block: the user message of a direct message that asks the agent about itself."""
    return await agent._build_user_message({"intent": "direct_message", "params": {"text": INTROSPECTIVE_TEXT}})


async def _inject_wr(runtime: SimpleNamespace, agent: CognitiveAgent) -> str:
    """The Ward Room block: the user message of a notification that asks the agent about itself."""
    return await agent._build_user_message({
        "intent": "ward_room_notification",
        "params": {
            "text": INTROSPECTIVE_TEXT, "title": "Self report", "channel_name": "bridge", "author_callsign": "Captain",
        },
        "context": "",
    })


async def _inject_query(runtime: SimpleNamespace, agent: CognitiveAgent) -> str:
    """The query sub-task, with a ``sovereign_id`` context key (nothing sets one live, but a caller may) that differs
    from ``_agent_id``, as ``test_ad1258_self_knowledge`` builds its query context."""
    spec = SubTaskSpec(
        sub_task_type=SubTaskType.QUERY, name="query-introspective-telemetry", context_keys=("introspective_telemetry",),
    )
    context = {
        "params": {"title": INTROSPECTIVE_TEXT, "text": ""},
        "_agent_id": agent.id,
        "sovereign_id": agent.sovereign_id,
        "context": "Thread content",
        "_agent_type": "agent",
        "_agent_rank": None,
        "_skill_profile": None,
        "_formatted_memories": "",
    }
    result = await QueryHandler(runtime)(spec, context, [])
    assert result.success
    return str(result.result["introspective_telemetry"])


_INJECTION_SITES: dict[str, Callable[[SimpleNamespace, CognitiveAgent], Awaitable[str]]] = {
    "proactive": _inject_proactive,
    "dm": _inject_dm,
    "wr": _inject_wr,
    "query": _inject_query,
}


async def _register_typed_agents(*agents: tuple[str, str]) -> AgentRegistry:
    """A real ``AgentRegistry`` holding one stand-in agent per ``(slot id, agent type)``."""
    agent_registry = AgentRegistry()
    for slot_id, agent_type in agents:
        await agent_registry.register(
            SimpleNamespace(id=slot_id, sovereign_id=None, agent_type=agent_type, pool="bf907", capabilities=[]),
        )
    return agent_registry


def _correction(agent_type: str) -> SimpleNamespace:
    """A correction signal for ``agent_type``, with the fields ``apply_correction_feedback`` reads."""
    return SimpleNamespace(
        target_agent_type=agent_type, correction_type="parameter_fix", corrected_values={"path": "fixed"},
        target_intent="read_file",
    )


async def test_telemetry_trust_miss_is_marked_not_prior(
    registry: AgentIdentityRegistry, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """A trust miss is reported as a miss, never as the prior (contract item 22). Kills R20 and R21.

    For an id that holds no record ``get_score`` answers the 0.5 prior, which the agent read as its own trust (the
    injected blocks used to ask by the sovereign id). The state now carries no ``score`` and says ``record: missing``,
    it renders ``Trust: no record for this id``, and the miss is logged once per subject, not on every call.
    """
    surgeon = await _issue(registry)
    counselor = await _issue(registry, COUNSELOR_SLOT, "counselor", "Ezri", "medical", "counselor")
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0)})
    telemetry = _telemetry(trust)
    # premise: neither certificate holds a record and the network would answer the 0.5 prior for it; the slot holds one
    assert trust.get_record(surgeon.agent_uuid) is None
    assert trust.get_record(counselor.agent_uuid) is None
    assert trust.get_score(surgeon.agent_uuid) == 0.5
    assert trust.get_record(SURGEON_SLOT) is not None
    assert _telemetry_miss_warnings(caplog) == []

    with caplog.at_level(logging.WARNING, logger=TELEMETRY_LOGGER):
        first = await telemetry.get_trust_state(surgeon.agent_uuid)
        second = await telemetry.get_trust_state(surgeon.agent_uuid)

    assert "score" not in first
    assert first.get("record") == "missing"
    assert second == first
    warnings = _telemetry_miss_warnings(caplog)
    assert len(warnings) == 1  # one WARNING across the two calls
    assert surgeon.agent_uuid in warnings[0]

    # once per subject: a second missing subject is logged once more, and a subject with a record is not marked
    with caplog.at_level(logging.WARNING, logger=TELEMETRY_LOGGER):
        other = await telemetry.get_trust_state(counselor.agent_uuid)
        known = await telemetry.get_trust_state(SURGEON_SLOT)

    assert other.get("record") == "missing"
    assert "record" not in known
    assert known["score"] == format_trust(trust.get_score(SURGEON_SLOT))
    warnings = _telemetry_miss_warnings(caplog)
    assert len(warnings) == 2
    assert counselor.agent_uuid in warnings[1]

    # what the agent reads: the miss is rendered as a miss, and the first subject is not logged again by the snapshot
    snapshot = await telemetry.get_full_snapshot(surgeon.agent_uuid)
    rendered = IntrospectiveTelemetryService.render_telemetry_context(snapshot)
    assert "score" not in snapshot["trust"]
    assert "Trust: no record for this id" in rendered.splitlines()
    assert "Trust: 0.5" not in rendered
    assert len(_telemetry_miss_warnings(caplog)) == 2


@pytest.mark.parametrize("path", ["proactive", "dm", "wr", "query"])
async def test_injected_telemetry_uses_the_slot_id(
    path: str, registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """Each injected telemetry block asks for the agent's slot id, not its sovereign id (contract item 23).

    Trust is keyed by slot id and the cognitive, temporal and social domains look the agent up by it; the memory
    domain resolves the sovereign id itself. The three blocks (proactive, DM, Ward Room) and the query sub-task used
    to hand the sovereign id to every domain. Kills R22 (proactive), R23 (dm), R24 (wr) and R25 (query).
    """
    from tests.test_ad588_telemetry_introspection import _make_cognitive_agent

    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0)})
    service = _RecordingTelemetry()
    runtime = _injection_runtime(trust, service)
    agent = _make_cognitive_agent(agent_id=SURGEON_SLOT, runtime=runtime)
    agent.sovereign_id = cert.agent_uuid  # that helper sets sovereign_id = id, which is why the split was invisible
    # premise: the slot id and the sovereign id differ, and the service has not been asked yet
    assert agent.id == SURGEON_SLOT
    assert agent.sovereign_id == cert.agent_uuid
    assert agent.sovereign_id != agent.id
    assert service.subjects == []

    block = await _INJECTION_SITES[path](runtime, agent)

    assert service.subjects == [SURGEON_SLOT]
    assert "Your Telemetry" in block  # the block reached its consumer


async def test_ad589_cached_snapshot_trust_equals_get_score(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """The AD-589 cache holds the trust the agent was shown, and it is the agent's score (contract item 24).

    The DM path caches the telemetry snapshot in the agent's working memory; the cached trust equals
    ``get_score(agent.id)`` and the observation count, and the same score was shown to the agent. AD-589's check does
    not compare numeric trust claims with this cache (a gap recorded separately); this test does not claim it does.
    Real service and real network; no resolver is bound, so the id the DM path passes is the key the network reads.
    Kills R23 together with the dm case of item 23.
    """
    from tests.test_ad588_telemetry_introspection import _make_cognitive_agent

    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)})
    runtime = _injection_runtime(trust)
    working_memory = AgentWorkingMemory()
    agent = _make_cognitive_agent(agent_id=SURGEON_SLOT, runtime=runtime, working_memory=working_memory)
    agent.sovereign_id = cert.agent_uuid
    expected = format_trust(trust.get_score(agent.id))
    record = trust.get_record(agent.id)
    # premise: the ids differ, the sovereign id reads a stray with another score, and nothing is cached yet
    assert agent.sovereign_id != agent.id
    assert record is not None
    assert format_trust(trust.get_score(cert.agent_uuid)) != expected
    assert working_memory._last_telemetry_snapshot is None

    prompt = await agent._build_user_message({"intent": "direct_message", "params": {"text": INTROSPECTIVE_TEXT}})

    cached = working_memory._last_telemetry_snapshot
    assert cached is not None
    assert cached["trust"]["score"] == expected
    assert cached["trust"]["observations"] == int(record.observations)
    assert f"Trust: {expected} (" in prompt  # the agent was shown the same score


async def test_correction_trust_lands_on_the_single_slot_of_the_type(
    trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """Correction feedback records trust on the one active agent of the target type (contract item 25).

    Trust is keyed by slot id; the write keyed by the agent type created a record named for the type. Hebbian and
    episodic processing keep the type, as before.
    """
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0)})
    agents = await _register_typed_agents(
        (SURGEON_SLOT, "surgeon"), (COUNSELOR_SLOT, "counselor"), (TOOL_SLOT, "calculator"),
    )
    hebbian = HebbianRouter()
    episodic = _StubEpisodicMemory()
    engine = FeedbackEngine(
        trust_network=trust, hebbian_router=hebbian, episodic_memory=episodic, agent_registry=agents,
    )
    before = _raw(trust)
    # premise: one active agent has the type, and no trust record is keyed by the type
    assert [agent.id for agent in agents.all() if agent.agent_type == "surgeon"] == [SURGEON_SLOT]
    assert "surgeon" not in before

    with caplog.at_level(logging.DEBUG, logger=FEEDBACK_LOGGER):
        result = await engine.apply_correction_feedback(
            "get the surgeon's report", _correction("surgeon"), SimpleNamespace(changes_description="fixed path"),
            retry_success=True,
        )

    assert [
        record.getMessage() for record in caplog.records
        if record.name == FEEDBACK_LOGGER and record.getMessage().startswith("BF-907: correction trust observation")
    ] == []  # the success case logs no not-recorded warning
    after = _raw(trust)
    assert set(after) == set(before)  # no record keyed by the agent type
    assert after[SURGEON_SLOT][0] > before[SURGEON_SLOT][0]  # the slot's alpha rose
    assert after[SURGEON_SLOT][1] == before[SURGEON_SLOT][1]
    assert after[COUNSELOR_SLOT] == before[COUNSELOR_SLOT]  # no other agent was touched
    assert result.agents_updated == ["surgeon"]  # Hebbian and the episode keep the type
    assert any(key[:2] == ("read_file", "surgeon") for key in hebbian.all_weights_typed())
    assert len(episodic.stored) == 1


@pytest.mark.parametrize("scenario", ["zero", "several", "no-registry"])
async def test_correction_trust_with_zero_or_several_agents_of_the_type_records_nothing(
    scenario: str, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """With no active agent of the type, several, or no agent registry at all, no trust is recorded (contract item 26).

    Spreading one observation over several agents would multiply the evidence, and a record keyed by the type is the
    defect. Hebbian and episodic processing go on. Kills R26 (``not target_ids`` records on the first of several).
    """
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), SURGEON_SECOND_SLOT: (80.0, 3.0), COUNSELOR_SLOT: (123.5, 3.0)})
    agents: AgentRegistry | None
    if scenario == "several":
        agents = await _register_typed_agents(
            (SURGEON_SLOT, "surgeon"), (SURGEON_SECOND_SLOT, "surgeon"), (COUNSELOR_SLOT, "counselor"),
        )
        holders = 2
    elif scenario == "zero":
        agents = await _register_typed_agents((COUNSELOR_SLOT, "counselor"))
        holders = 0
    else:
        agents = None
        holders = 0
    episodic = _StubEpisodicMemory()
    engine = FeedbackEngine(
        trust_network=trust, hebbian_router=HebbianRouter(), episodic_memory=episodic, agent_registry=agents,
    )
    before = _raw(trust)
    # premise: the registry holds as many agents of the type as the scenario says, and no record is keyed by the type
    assert len([agent for agent in (agents.all() if agents else []) if agent.agent_type == "surgeon"]) == holders
    assert "surgeon" not in before

    with caplog.at_level(logging.WARNING, logger=FEEDBACK_LOGGER):
        result = await engine.apply_correction_feedback(
            "get the surgeon's report", _correction("surgeon"), SimpleNamespace(changes_description="fixed path"),
            retry_success=True,
        )

    assert _raw(trust) == before  # nothing recorded, and no record keyed by the type
    warnings = [
        record.getMessage() for record in caplog.records
        if record.name == FEEDBACK_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith(
        f"BF-907: correction trust observation for agent_type=surgeon not recorded: {holders} active agents of that type"
    )
    assert "needs exactly one" in warnings[0]
    assert result.agents_updated == ["surgeon"]  # Hebbian and the episode go on
    assert len(episodic.stored) == 1


async def test_memory_domain_still_counts_by_sovereign_id_given_the_slot(
    registry: AgentIdentityRegistry, trust: TrustNetwork,
) -> None:
    """The memory domain counts episodes by the sovereign id it resolves from the slot id (contract item 27).

    Section 6 hands the slot id to every domain. Episodes are keyed by the sovereign id (AD-1259:
    ``tests/test_ad1259_one_source_of_truth.py::test_profile_and_self_query_reconcile_sovereign_memory``), so the
    memory domain must keep resolving it itself while the trust domain of the same snapshot reads the slot record.
    A guard: it holds before Section 6 as well as after it.
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0)})
    agents = await _register_agents((SURGEON_SLOT, cert.agent_uuid))
    memory = _RecordingMemory({SURGEON_SLOT: 17, cert.agent_uuid: 196})
    runtime = SimpleNamespace(
        registry=agents, episodic_memory=memory, trust_network=trust, hebbian_router=_EmptyHebbianRouter(),
    )
    service = IntrospectiveTelemetryService(runtime=runtime)
    # premise: the slot id and the sovereign id differ and are counted differently, and nothing has been asked yet
    assert cert.agent_uuid != SURGEON_SLOT
    assert memory.counts[SURGEON_SLOT] != memory.counts[cert.agent_uuid]
    assert memory.subjects == []

    snapshot = await service.get_full_snapshot(SURGEON_SLOT)

    assert memory.subjects == [cert.agent_uuid]
    assert snapshot["memory"]["episode_count"] == 196
    assert snapshot["memory"]["measurement"]["subject_id"] == cert.agent_uuid
    assert snapshot["trust"]["score"] == format_trust(trust.get_score(SURGEON_SLOT))  # the slot record, in one snapshot


async def test_the_boot_wires_the_agent_registry_into_the_correction_feedback_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Section 7e through a real boot (a wiring check beyond the numbered list).

    Items 25 and 26 build the engine with a registry by hand, so a dropped ``agent_registry=registry`` in
    ``init_cognitive_services`` would pass them while every correction on the live vessel recorded no trust. The
    engine the boot builds must name the one active agent of a type by its slot id.
    """
    runtime = await _boot(tmp_path / "data")
    try:
        slots_by_type: dict[str, list[str]] = {}
        for agent in runtime.registry.all():
            slots_by_type.setdefault(agent.agent_type, []).append(agent.id)
        singles = sorted(
            (agent_type, slots[0]) for agent_type, slots in slots_by_type.items()
            if len(slots) == 1 and runtime.trust_network.get_record(slots[0]) is not None
        )
        # premise: the boot built the engine and wired an agent type held by exactly one agent with a trust record
        assert runtime.feedback_engine is not None
        assert singles, sorted(slots_by_type)
        agent_type, slot = singles[0]
        assert agent_type != slot
        assert runtime.trust_network.get_record(agent_type) is None
        recorded: list[str] = []
        real_record_outcome = runtime.trust_network.record_outcome

        def _spy(agent_id: str, *args: Any, **kwargs: Any) -> float:
            recorded.append(agent_id)
            return real_record_outcome(agent_id, *args, **kwargs)

        monkeypatch.setattr(runtime.trust_network, "record_outcome", _spy)

        await runtime.feedback_engine.apply_correction_feedback(
            "get the report", _correction(agent_type), SimpleNamespace(changes_description="fixed path"),
            retry_success=True,
        )

        assert slot in recorded  # the observation landed on the agent's slot id
        assert agent_type not in recorded
        assert runtime.trust_network.get_record(agent_type) is None
    finally:
        await runtime.stop()


# ---------------------------------------------------------------------------
# Coverage additions beyond the numbered list: gaps found by the mutation campaign (hand rows H1, H2, H19)
# ---------------------------------------------------------------------------


class _FailingEventLog:
    """Test-local event log whose ``log`` always fails, as an unavailable event store would."""

    async def log(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("event store unavailable (simulated by the test)")


async def test_reconcile_keeps_a_stray_below_the_prior_and_ad280_does_not_remove_it(
    registry: AgentIdentityRegistry, trust: TrustNetwork, event_log: EventLog, caplog: pytest.LogCaptureFixture,
) -> None:
    """A stray whose evidence is below the network prior is refused by the merge (``below_prior``); the reconcile
    must keep it, log the reason, and hand it to AD-280 as active so it is not deleted (kills hand mutant H1).
    """
    cert = await _issue(registry)
    active = {SURGEON_SLOT}
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (1.9, 2.0)})
    before = _file_rows(_db(trust))
    # premise: the stray is in memory and in the file, resolves to the slot, and the slot is active
    assert _raw(trust)[cert.agent_uuid] == (1.9, 2.0)
    assert before[cert.agent_uuid] == (1.9, 2.0)
    assert identity.is_sovereign_identity_key(cert.agent_uuid)
    assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
    assert SURGEON_SLOT in active
    assert before == _raw(trust)

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        result = await _reconcile(trust, registry, event_log, active)

    assert result.merged == ()
    assert result.kept == {cert.agent_uuid: "below_prior"}
    assert result.removed == 0  # AD-280 did not delete the kept stray
    assert _raw(trust) == {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (1.9, 2.0)}
    assert _file_rows(_db(trust)) == {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (1.9, 2.0)}
    assert (_count(_db(trust), "trust_snapshots"), _count(_db(trust), "trust_key_merges")) == (0, 0)
    assert await _merge_events(event_log) == []
    log = _module_log(caplog)
    assert (
        logging.WARNING, f"BF-907: trust record {cert.agent_uuid} kept unmerged (below_prior)",
    ) in log, log


async def test_reconcile_survives_an_event_log_write_failure_and_keeps_the_merge(
    registry: AgentIdentityRegistry, trust: TrustNetwork, caplog: pytest.LogCaptureFixture,
) -> None:
    """A failure of ``event_log.log`` after a committed merge is logged as a WARNING and does not abort the
    reconcile; the merge stands in trust.db (kills hand mutant H2).
    """
    cert = await _issue(registry)
    await _seed(trust, {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)})
    # premise: the stray and the slot are in memory and in the file, nothing has been merged, the slot is active
    assert _raw(trust) == {SURGEON_SLOT: (95.0, 3.0), cert.agent_uuid: (2.48, 2.0)}
    assert _file_rows(_db(trust)) == _raw(trust)
    assert registry.resolve_slot_id(cert.agent_uuid) == SURGEON_SLOT
    assert _count(_db(trust), "trust_key_merges") == 0

    with caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        result = await _startup().reconcile_trust_identities(
            trust_network=trust, identity_registry=registry, active_ids={SURGEON_SLOT},
            event_log=_FailingEventLog(),
        )

    assert [merge.source_key for merge in result.merged] == [cert.agent_uuid]
    assert result.kept == {}
    merged_values = {SURGEON_SLOT: (pytest.approx(95.48), 3.0)}
    assert _raw(trust) == merged_values
    assert _file_rows(_db(trust)) == merged_values
    rows = _merge_rows(_db(trust))
    assert list(rows) == [cert.agent_uuid]
    assert rows[cert.agent_uuid]["target_key"] == SURGEON_SLOT
    warnings = [
        record for record in caplog.records
        if record.name == "probos.startup.trust_identity" and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, [record.getMessage() for record in warnings]
    message = warnings[0].getMessage()
    assert message.startswith(f"BF-907: merge event for {cert.agent_uuid} was not written"), message
    assert result.merged[0].snapshot_id is not None
    assert f"(snapshot {result.merged[0].snapshot_id})" in message
    assert warnings[0].exc_info is not None
    assert isinstance(warnings[0].exc_info[1], RuntimeError)


async def test_a_failing_crew_check_does_not_abort_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The crew check at the end of ``finalize_startup`` is wrapped: if it raises, startup completes and the failure
    is logged at WARNING with its traceback (kills hand mutant H19).
    """

    async def _failing_check(**kwargs: Any) -> None:
        raise RuntimeError("crew check defect (simulated by the test)")

    # finalize imports the name at call time, so the module attribute is what it reads
    monkeypatch.setattr("probos.startup.trust_identity.verify_crew_trust_identity", _failing_check)
    with caplog.at_level(logging.INFO, logger="probos.startup.finalize"), \
            caplog.at_level(logging.INFO, logger="probos.startup.trust_identity"):
        runtime = await _boot(tmp_path / "data")
    try:
        # premise: the boot completed its start(): crew are registered and the trust network and registry exist
        assert runtime.trust_network is not None
        assert runtime.identity_registry is not None
        assert [
            agent for agent in runtime.registry.all()
            if runtime.identity_registry.get_by_slot(agent.id) is not None
        ]
        warnings = [
            record for record in caplog.records
            if record.name == "probos.startup.finalize" and record.levelno == logging.WARNING
            and record.getMessage() == "BF-907: the crew trust identity check failed to run; startup continues"
        ]
        assert len(warnings) == 1, [(r.name, r.levelno, r.getMessage()) for r in caplog.records]
        assert warnings[0].exc_info is not None
        assert isinstance(warnings[0].exc_info[1], RuntimeError)
        assert str(warnings[0].exc_info[1]) == "crew check defect (simulated by the test)"
        # the stub replaced the real check, so the success line was never logged
        assert not [
            message for _, message in _module_log(caplog) if message.startswith("BF-907 trust identity check: crew=")
        ]
    finally:
        await runtime.stop()
