"""AD-1197 (#1134) M5: envelope-signing configuration, fleet wiring, the runtime hand-off and the store declaration.

Off is byte-identical: with ``federation.envelope_signing_enabled`` unset the fleet
gets the raw transport and no envelope store file exists, even when a binding that
could sign is offered. Armed, the transport is wrapped before it starts; ``require``
keeps federation closed when its store cannot open, ``sign`` degrades to unsigned
federation with a warning, and a missing key binding builds no federation at all.

No test opens a socket or reaches the real OS keyring: AD-1196's autouse guard is
imported (H4), transports run over the mock NATS bus, and ZeroMQ is made
unavailable wherever its fallback would run (H9).
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import logging
import sqlite3
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import keyring
import pytest
from pydantic import ValidationError

import probos.federation.transport as federation_transport_module
import probos.startup.fleet_organization as fleet_organization_module
from probos.config import (
    FederationConfig,
    MedicalConfig,
    PeerConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
    load_config,
)
from probos.federation.envelope import EnvelopeGuard
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.signed_transport import SignedFederationTransport, build_signed_transport
from probos.federation.transport import FederationTransport
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.identity_keys import STATUS_ACTIVE
from probos.mesh.nats_bus import MockNATSBus
from probos.startup.fleet_organization import organize_fleet
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H4)
    _armed,
    _DuckKeyring,
    _KeyringProbe,
    _no_real_os_keyring,
)

_ROOT = Path(__file__).resolve().parents[1]
_ENVELOPE_LOGGER = "probos.federation.envelope"
_FLEET_LOGGER = "probos.startup.fleet_organization"
_FEDERATION_SUBJECTS = ["federation.gossip", "federation.intent.node-a"]
_GOSSIP = FederationMessage(type="gossip_self_model", source_node="node-a", payload={"node_id": "node-a"}, timestamp=1.0)


class _RecordingNATSBus(MockNATSBus):
    """The mock NATS bus, recording every raw subscription (the federation transport subscribes raw)."""

    def __init__(self) -> None:
        super().__init__()
        self.raw_subscriptions: list[str] = []

    async def subscribe_raw(self, subject: str, callback: Any, queue: str = "") -> str:
        self.raw_subscriptions.append(subject)
        return await super().subscribe_raw(subject, callback, queue)


class _RecordingIntentBus:
    """The intent-bus members organize_fleet and FederationBridge use; records each local broadcast."""

    def __init__(self) -> None:
        self.broadcasts: list[IntentMessage] = []
        self.federation_handler: Any = None

    def set_federation_handler(self, handler: Any) -> None:
        self.federation_handler = handler

    def candidate_agent_ids(self, intent_name: str) -> set[str]:
        return {"node-a-agent"}

    async def broadcast(
        self, intent: IntentMessage, *, timeout: Any = None, federated: bool = True, raise_on_denial: bool = False,
    ) -> list[IntentResult]:
        self.broadcasts.append(intent)
        return [IntentResult(
            intent_id=intent.id, agent_id="node-a-agent", success=True, result="done", confidence=0.9,
        )]


def _system_config(*, armed: bool, policy: str = "require") -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            enabled=True, node_id="node-a", gossip_interval_seconds=1_000.0,
            peers=[PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530")],
            identity_keys_enabled=armed, envelope_signing_enabled=armed, envelope_policy=policy,
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


@contextlib.asynccontextmanager
async def _nats_bus() -> AsyncIterator[_RecordingNATSBus]:
    bus = _RecordingNATSBus()
    await bus.start()
    try:
        yield bus
    finally:
        await bus.stop()


@contextlib.asynccontextmanager
async def _fleet(
    config: SystemConfig,
    *,
    bus: MockNATSBus,
    identity_key_binding: Any,
    data_dir: Path | None,
    intent_bus: Any = None,
) -> AsyncIterator[Any]:
    """``organize_fleet`` over the mock NATS bus; the bridge and the transport are always stopped."""
    result = None
    try:
        result = await organize_fleet(
            config=config,
            pools={},
            pool_groups=PoolGroupRegistry(),
            escalation_manager=SimpleNamespace(),
            intent_bus=_RecordingIntentBus() if intent_bus is None else intent_bus,
            trust_network=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            build_pool_intent_map_fn=dict,
            find_consensus_pools_fn=set,
            build_self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
            validate_remote_result_fn=None,
            attachment_resolver_fn=None,
            nats_bus=bus,
            identity_key_binding=identity_key_binding,
            data_dir=data_dir,
        )
        yield result
    finally:
        if result is not None and result.federation_bridge is not None:
            await result.federation_bridge.stop()
        if result is not None and result.federation_transport is not None:
            await result.federation_transport.stop()


def _epochs(data_dir: Path) -> list[tuple[int, ...]]:
    with contextlib.closing(sqlite3.connect(data_dir / ENVELOPE_DB_NAME)) as db:
        return db.execute("SELECT epoch FROM envelope_send_epoch").fetchall()


def _messages(caplog: pytest.LogCaptureFixture, logger_name: str, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == logger_name and record.levelno == level]


async def _unusable_store_dir(tmp_path: Path) -> Path:
    """A data directory whose envelope database path is a directory, so the store cannot open."""
    data_dir = tmp_path / "data"
    (data_dir / ENVELOPE_DB_NAME).mkdir(parents=True)
    store = EnvelopeStore(data_dir / ENVELOPE_DB_NAME)
    try:
        with pytest.raises(sqlite3.OperationalError):
            await store.start()  # premise: the store really cannot open there
    finally:
        await store.stop()
    return data_dir


def test_envelope_config_defaults_off() -> None:
    federation = FederationConfig()
    assert (federation.envelope_signing_enabled, federation.envelope_policy) == (False, "sign")
    assert SystemConfig().federation.envelope_signing_enabled is False
    shipped = load_config(_ROOT / "config" / "system.yaml").federation
    assert (shipped.envelope_signing_enabled, shipped.envelope_policy) == (False, "sign")


def test_envelope_signing_requires_identity_keys() -> None:
    with pytest.raises(ValidationError, match="requires federation.identity_keys_enabled"):
        FederationConfig(envelope_signing_enabled=True)
    armed = FederationConfig(envelope_signing_enabled=True, identity_keys_enabled=True, envelope_policy="require")
    assert (armed.envelope_signing_enabled, armed.envelope_policy) == (True, "require")
    assert FederationConfig(identity_keys_enabled=True).envelope_signing_enabled is False  # keys alone arm nothing


def test_envelope_policy_rejects_an_unknown_value() -> None:
    with pytest.raises(ValidationError, match="envelope_policy"):
        FederationConfig(envelope_policy="strict")  # type: ignore[arg-type]
    assert FederationConfig(envelope_policy="require").envelope_policy == "require"  # premise: known values parse


async def test_off_fleet_organization_creates_no_envelope_store(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        assert binding.key_status == STATUS_ACTIVE  # premise: a binding that could sign is offered, and ignored
        async with _fleet(
            _system_config(armed=False), bus=bus, identity_key_binding=binding, data_dir=data_dir,
        ) as result:
            assert type(result.federation_transport) is NATSFederationTransport
            assert result.federation_bridge is not None
            assert bus.raw_subscriptions == _FEDERATION_SUBJECTS
            assert await result.federation_transport.send_to_all_peers(_GOSSIP) == ["node-b"]
            assert bus.published[-1] == ("federation.gossip", {
                "type": "gossip_self_model", "source_node": "node-a", "message_id": _GOSSIP.message_id,
                "payload": {"node_id": "node-a"}, "timestamp": 1.0,
            })
    assert list(data_dir.iterdir()) == []


async def test_armed_fleet_organization_wraps_the_transport_before_start(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(
            _system_config(armed=True), bus=bus, identity_key_binding=binding, data_dir=data_dir,
        ) as result:
            transport = result.federation_transport
            assert type(transport) is SignedFederationTransport and result.federation_bridge is not None
            assert bus.raw_subscriptions == _FEDERATION_SUBJECTS  # the inner transport started once, by the wrapper
            assert _epochs(data_dir) == [(1,)]  # its guard started and committed the first send epoch
            assert await transport.send_to_all_peers(_GOSSIP) == ["node-b"]
            subject, published = bus.published[-1]
            assert subject == "federation.gossip" and published["auth"]["target"] == "*"


async def test_armed_require_with_an_unusable_store_sends_and_accepts_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    data_dir = await _unusable_store_dir(tmp_path)
    intent_bus = _RecordingIntentBus()
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(
            _system_config(armed=True, policy="require"), bus=bus, identity_key_binding=binding, data_dir=data_dir,
            intent_bus=intent_bus,
        ) as result:
            transport = result.federation_transport
            assert type(transport) is SignedFederationTransport and result.federation_bridge is not None
            assert transport.connected_peers == []
            assert bus.raw_subscriptions == []  # the inner transport never started
            await transport.send_to_peer("node-b", FederationMessage(
                type="intent_request", source_node="node-a", payload={"id": "i-0"}, timestamp=1.0,
            ))
            assert await transport.send_to_all_peers(_GOSSIP) == []
            assert bus.published == []
            await bus.publish_raw("federation.intent.node-a", {
                "type": "intent_request", "source_node": "node-b", "message_id": "m-1",
                "payload": {"intent": "read_file", "params": {"path": "/a"}, "id": "i-1"}, "timestamp": 1.0,
            })
            assert intent_bus.broadcasts == []
    assert _messages(caplog, _ENVELOPE_LOGGER, logging.ERROR) == [
        "AD-1197: the federation envelope store could not be opened (OperationalError); policy 'require' keeps "
        "federation closed -- nothing is sent or accepted -- until it opens on a restart",
    ]


async def test_armed_sign_with_an_unusable_store_degrades_to_unsigned_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    data_dir = await _unusable_store_dir(tmp_path)
    intent_bus = _RecordingIntentBus()
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(
            _system_config(armed=True, policy="sign"), bus=bus, identity_key_binding=binding, data_dir=data_dir,
            intent_bus=intent_bus,
        ) as result:
            transport = result.federation_transport
            assert type(transport) is SignedFederationTransport
            assert bus.raw_subscriptions == _FEDERATION_SUBJECTS
            assert await transport.send_to_all_peers(_GOSSIP) == ["node-b"]
            subject, published = bus.published[-1]
            assert subject == "federation.gossip" and "auth" not in published
            await bus.publish_raw("federation.intent.node-a", {
                "type": "intent_request", "source_node": "node-b", "message_id": "m-1",
                "payload": {"intent": "read_file", "params": {"path": "/a"}, "id": "i-1"}, "timestamp": 1.0,
            })
            assert [intent.id for intent in intent_bus.broadcasts] == ["i-1"]  # the unsigned message was dispatched
    assert _messages(caplog, _ENVELOPE_LOGGER, logging.WARNING) == [
        "AD-1197: the federation envelope store could not be opened (OperationalError); policy 'sign' runs "
        "federation unsigned and unverified until it opens on a restart",
    ]


async def test_armed_without_a_key_binding_starts_no_federation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(federation_transport_module, "_HAS_ZMQ", False)
    with pytest.raises(ImportError):  # premise: ZeroMQ is unavailable, so its fallback opens nothing (H9)
        FederationTransport(node_id="node-a", bind_address="tcp://127.0.0.1:65530", peers=[])
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    async with _nats_bus() as bus:
        async with _fleet(_system_config(armed=True), bus=bus, identity_key_binding=None, data_dir=data_dir) as result:
            assert result.federation_bridge is None and result.federation_transport is None
        assert bus.raw_subscriptions == [] and bus.published == []
    assert list(data_dir.iterdir()) == []
    assert _messages(caplog, _FLEET_LOGGER, logging.WARNING) == [
        "AD-637e: NATS federation transport failed, falling back to ZeroMQ: federation envelope signing needs the "
        "ship key binding (federation.identity_keys_enabled)",
        "pyzmq not available; federation transport disabled",
    ]


async def test_armed_without_a_data_directory_starts_no_federation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(federation_transport_module, "_HAS_ZMQ", False)
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(_system_config(armed=True), bus=bus, identity_key_binding=binding, data_dir=None) as result:
            assert result.federation_bridge is None and result.federation_transport is None
        assert bus.raw_subscriptions == [] and bus.published == []
    assert _messages(caplog, _FLEET_LOGGER, logging.WARNING)[0] == (
        "AD-637e: NATS federation transport failed, falling back to ZeroMQ: federation envelope signing needs a "
        "data directory for its replay store"
    )


def test_build_signed_transport_refuses_a_missing_key_binding(tmp_path: Path) -> None:
    inner = NATSFederationTransport(node_id="node-a", nats_bus=MockNATSBus(), peer_node_ids=[])
    with pytest.raises(ValueError, match="ship key binding"):
        build_signed_transport(inner, policy="require", key_binding=None, data_dir=tmp_path)
    built = build_signed_transport(inner, policy="require", key_binding=SimpleNamespace(), data_dir=tmp_path)
    assert type(built) is SignedFederationTransport  # premise: with any binding it builds (and opens nothing yet)
    assert list(tmp_path.iterdir()) == []


async def test_runtime_hands_the_key_binding_and_data_dir_to_fleet_organization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive.llm_client import MockLLMClient
    from probos.runtime import ProbOSRuntime

    monkeypatch.setattr(keyring, "get_keyring", _KeyringProbe(_DuckKeyring()))
    received: list[dict[str, Any]] = []
    delegate = fleet_organization_module.organize_fleet

    async def _recording_organize_fleet(**kwargs: Any) -> Any:
        received.append(kwargs)
        return await delegate(**kwargs)

    monkeypatch.setattr(fleet_organization_module, "organize_fleet", _recording_organize_fleet)
    config = SystemConfig(federation=FederationConfig(identity_keys_enabled=True))
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        binding, data_dir = runtime.identity_key_binding, runtime._data_dir
    finally:
        await runtime.stop()
    assert binding is not None  # premise: identity keys are armed, so there is a binding to hand over
    assert len(received) == 1
    assert received[0]["identity_key_binding"] is binding
    assert received[0]["data_dir"] is data_dir and data_dir == tmp_path / "data"


def test_envelope_store_declaration_matches_its_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    from probos.storage.declarations import declaration_errors
    from probos.storage.registry import load_default_store_registry

    registry = load_default_store_registry()
    declaration = registry.get("federation.envelope-replay")
    assert declaration is not None
    assert declaration.to_dict() == {
        "id": "federation.envelope-replay",
        "title": "Federation envelope key holds and replay windows (AD-1197)",
        "owner_module": "probos.federation_envelope_store",
        "owner_symbol": "EnvelopeStore",
        "canonical_path": "federation_envelopes.db",
        "criticality": "feature-gated",
        "lifecycle_owner": "probos.federation.envelope.EnvelopeGuard",
        "retention": "unbounded",
        "retention_note": (  # AD-1198 slice 2c: "No DELETE FROM" stopped being true when a re-anchor (2b) and a reset (2c) delete rows
            "One row per sender held (at most 256), with at most 4,096 key ids each, at most two replay windows per "
            "sender and one send-epoch row, updated in place and only ever forward, with two deletions (AD-1198): a "
            "re-anchor deletes one sender's replay windows (slice 2b), and an operator's reset deletes one sender's row "
            "and replay windows (slice 2c), each in one transaction."
        ),
        "backup": "included",
        "restore": "unknown",
        "reconstruction": "",
        "notes": (
            "Constructed only when federation.envelope_signing_enabled. Public key-event histories, key ids, counters "
            "and 64-bit window masks only: no private key, envelope signature or message body. Restoring an older copy "
            "rolls replay windows back (envelopes recorded after the backup are accepted once more); deleting "
            "it forgets every hold and every recorded key id (the next envelope from each sender is a first contact), "
            "and a sender that lost its own copy restarts at epoch 1 until it rotates its key."
        ),
    }
    assert declaration_errors(declaration) == ()
    assert registry.by_canonical_path(ENVELOPE_DB_NAME) is declaration
    assert getattr(importlib.import_module(declaration.owner_module), declaration.owner_symbol) is EnvelopeStore
    lifecycle_module, _, lifecycle_symbol = declaration.lifecycle_owner.rpartition(".")
    assert getattr(importlib.import_module(lifecycle_module), lifecycle_symbol) is EnvelopeGuard
    spec = importlib.util.spec_from_file_location(
        "check_store_registry_ad1197", _ROOT / "scripts" / "check_store_registry.py",
    )
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, checker)  # dataclasses re-read annotations from sys.modules
    spec.loader.exec_module(checker)
    source = (_ROOT / "src" / "probos" / "federation_envelope_store.py").read_text(encoding="utf-8")
    assert sorted(checker.detect_tables(source)) == ["envelope_send_epoch", "envelope_senders", "envelope_windows"]
