"""AD-843c-2: submit_device_actuate_with_consensus — sensitive device tier + era-4 guard.

Real fixtures only (BF-287: no MagicMock at the runtime boundary). Proposer-unit
tests mirror ``test_ad1019c_proposer.py`` (propose-only, never actuates).
Consensus-path tests mirror ``test_ad1019c_consensus.py`` (a real ``ProbOSRuntime``
+ ``start()`` + a real ``DeviceConsensusProposer`` pool) plus the AD-843c-1
``_pair`` / ``_CountingAdapter`` helpers. The headline assertion is the **era-4 /
AD-362 guard**: a rejected or insufficient vote performs ZERO ``actuate`` calls —
the actuation is the *commit*, gated on APPROVED.

Trust policy (architect override of the BuildSpec): a trust outcome is recorded
**ONLY when an actuation was actually attempted** (the APPROVED + no-failed-
verification branch), keyed ``success=committed``. A rejected / insufficient /
unauthorized path performs no actuation and writes **no** trust outcome (avoids
the consensus-weighting lock-out spiral + the INSUFFICIENT-penalizes-device bug).
A genuine APPROVED-but-actuate-fails still records ``success=False`` (test 13).
Episodes are stored on ALL paths (audit / learning completeness).
"""

from __future__ import annotations

import pytest

from probos.agents.device_consensus_proposer import DeviceConsensusProposer
from probos.cognitive.episodic import EpisodicMemory
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.startup.finalize import _wire_device_consensus
from probos.substrate.device_node import DeviceNode, NoOpDeviceNodeAdapter
from probos.substrate.device_pairing import generate_keypair, sign_challenge
from probos.substrate.device_service import DEVICE_NODE_SERVICE_ID
from probos.types import (
    ConsensusOutcome,
    HandlerLatencyClass,
    IntentMessage,
    IntentResult,
    QuorumPolicy,
)

_CHALLENGE = "device-consensus-challenge"


# ------------------------------------------------------------------
# Real delegating spies + adapters (BF-287: never a Mock)
# ------------------------------------------------------------------
class _CountingAdapter:
    """Real adapter wrapper counting ``actuate`` calls (delegates to NoOp)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._inner = NoOpDeviceNodeAdapter()

    async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult:
        self.calls.append((device.device_id, intent.intent))
        return await self._inner.actuate(device, intent)


class _FailingAdapter:
    """Real adapter that reports a failed actuation (an attempt that fails).

    Used by test 13: the actuation IS attempted (counted) but returns
    ``success=False`` — the runtime must commit=False yet still record a trust
    failure (an actuation was attempted, so the genuine-failure signal is kept).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def actuate(self, device: DeviceNode, intent: IntentMessage) -> IntentResult:
        self.calls.append((device.device_id, intent.intent))
        return IntentResult(
            intent_id=intent.id,
            agent_id=f"device:{device.device_id}",
            success=False,
            error="backend failure",
            confidence=0.0,
        )


class _TrustSpy:
    """Real delegating TrustNetwork wrapper recording every ``record_outcome``.

    Delegates all other attribute access to the wrapped real network (so quorum /
    voter trust weighting is unaffected). The recorded outcomes are filtered by
    the device handle in the assertions, so any unrelated voter-trust writes do
    not pollute the device-tier assertions.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.outcomes: list[tuple[str, bool]] = []

    def record_outcome(self, agent_id: str, success: bool, **kwargs: object) -> float:
        self.outcomes.append((agent_id, success))
        return self._inner.record_outcome(agent_id, success, **kwargs)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


class _StoreSpy:
    """Real delegating wrapper recording every episode store (not a Mock)."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.stored: list = []

    async def store(self, episode: object) -> None:
        self.stored.append(episode)
        return await self._inner.store(episode)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def _pair(registry: object, device_id: str, capabilities: frozenset[str]) -> None:
    """Crypto-pair ``device_id`` into ``registry`` granting ``capabilities``."""
    private_key, public_key_b64 = generate_keypair()
    signature_b64 = sign_challenge(private_key, _CHALLENGE)
    paired = registry.pair_device(  # type: ignore[attr-defined]
        device_id,
        public_key_b64,
        capabilities,
        challenge=_CHALLENGE,
        signature=signature_b64,
    )
    assert paired is not None


def _device_episodes(ep_spy: _StoreSpy) -> list:
    """The stored device-actuation episodes (filter out any unrelated episodes)."""
    return [
        e
        for e in ep_spy.stored
        if getattr(e, "outcomes", None)
        and e.outcomes
        and e.outcomes[0].get("kind") == "device_actuate"
    ]


# ------------------------------------------------------------------
# Proposer-unit tests (no runtime) — mirror test_ad1019c_proposer.py
# ------------------------------------------------------------------
def _proposer() -> DeviceConsensusProposer:
    return DeviceConsensusProposer(pool="device_consensus")


@pytest.mark.asyncio
async def test_proposer_proposes_valid_actuate_with_consensus_flag() -> None:
    agent = _proposer()
    msg = IntentMessage(
        intent="device_actuate",
        params={"device_id": "phone-1", "intent_name": "device.location", "params": {}},
    )

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is True
    assert result.result["requires_consensus"] is True
    assert result.result["device_id"] == "phone-1"
    assert result.result["intent_name"] == "device.location"


@pytest.mark.asyncio
async def test_proposer_rejects_missing_device_id() -> None:
    agent = _proposer()
    msg = IntentMessage(intent="device_actuate", params={"intent_name": "device.location"})

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is False
    assert "device_id" in (result.error or "")


@pytest.mark.asyncio
async def test_proposer_rejects_missing_intent_name() -> None:
    agent = _proposer()
    msg = IntentMessage(intent="device_actuate", params={"device_id": "phone-1"})

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is False
    assert "intent_name" in (result.error or "")


@pytest.mark.asyncio
async def test_proposer_ignores_unhandled_intent() -> None:
    agent = _proposer()
    msg = IntentMessage(intent="device.notify", params={"device_id": "phone-1"})

    result = await agent.handle_intent(msg)

    assert result is None


def test_proposer_descriptor_consensus_and_utility_tier() -> None:
    descs = {d.name: d for d in DeviceConsensusProposer.intent_descriptors}
    assert "device_actuate" in descs
    assert descs["device_actuate"].requires_consensus is True
    assert DeviceConsensusProposer.tier == "utility"


# ------------------------------------------------------------------
# Consensus-path tests (real runtime + start()) — mirror test_ad1019c_consensus.py
# ------------------------------------------------------------------
@pytest.fixture
async def runtime(tmp_path):
    # Explicit default SystemConfig() keeps device.enabled=False, so finalize's
    # _wire_device_consensus is a no-op; each test creates the pool explicitly and
    # calls submit_device_actuate_with_consensus directly. The device registry is
    # constructed eagerly in __init__ regardless of the flag, so devices pair.
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=SystemConfig())
    rt.spawner.register_template("device_consensus_proposer", DeviceConsensusProposer)
    await rt.start()
    yield rt
    await rt.stop()


def _install_spies(runtime, tmp_path, *, adapter):
    """Swap in real delegating spies for trust + episodic + the actuation adapter."""
    trust_spy = _TrustSpy(runtime.trust_network)
    runtime.trust_network = trust_spy
    inner_ep = runtime.episodic_memory or EpisodicMemory(db_path=str(tmp_path / "ep"))
    ep_spy = _StoreSpy(inner_ep)
    runtime.episodic_memory = ep_spy
    runtime.device_node_adapter = adapter
    return trust_spy, ep_spy


@pytest.mark.asyncio
async def test_approved_commits_single_actuate(runtime, tmp_path):
    """APPROVED + no failed verifications → exactly one actuate; trust + episode recorded."""
    await runtime.create_pool(
        "device_consensus", "device_consensus_proposer", target_size=3
    )
    adapter = _CountingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)
    _pair(runtime.device_node_registry, "phone-1", frozenset({"device.location"}))
    score_before = trust_spy.get_score("device:phone-1")

    result = await runtime.submit_device_actuate_with_consensus(
        "phone-1", "device.location", {}, timeout=5.0
    )

    assert result["consensus"].outcome == ConsensusOutcome.APPROVED
    assert result["committed"] is True
    assert len(adapter.calls) == 1
    # Episode stored, device-anchored, success.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["success"] is True
    assert device_eps[0].anchors.channel == "device"
    # Trust recorded once for the device, success=True, score rose vs Beta(1, 3).
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:phone-1"]
    assert device_outcomes == [("device:phone-1", True)]
    assert trust_spy.get_score("device:phone-1") > score_before


@pytest.mark.asyncio
async def test_rejected_vote_performs_zero_actuate(runtime, tmp_path):
    """era-4 guard: a REJECTED vote must NOT actuate — and (override) records NO trust."""
    await runtime.create_pool(
        "device_consensus", "device_consensus_proposer", target_size=3
    )
    adapter = _CountingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)
    _pair(runtime.device_node_registry, "phone-1", frozenset({"device.location"}))
    rec_before = trust_spy.get_record("device:phone-1")
    alpha_before, beta_before = rec_before.alpha, rec_before.beta

    # An impossible approval threshold forces REJECTED even with all-success proposals.
    result = await runtime.submit_device_actuate_with_consensus(
        "phone-1", "device.location", {}, timeout=5.0,
        policy=QuorumPolicy(min_votes=3, approval_threshold=1.1),
    )

    assert result["consensus"].outcome == ConsensusOutcome.REJECTED
    assert result["committed"] is False
    assert len(adapter.calls) == 0  # <-- the era-4 regression guard
    # Episode still stored (audit completeness), marked not-committed.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["success"] is False
    assert device_eps[0].outcomes[0]["reason"] == "not_committed"
    # Override death-spiral guard: NO trust outcome on a governance rejection.
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:phone-1"]
    assert device_outcomes == []
    rec_after = trust_spy.get_record("device:phone-1")
    assert (rec_after.alpha, rec_after.beta) == (alpha_before, beta_before)


@pytest.mark.asyncio
async def test_insufficient_votes_performs_zero_actuate(runtime, tmp_path):
    """era-4 guard: no proposer pool → INSUFFICIENT → zero actuate, (override) NO trust."""
    # Deliberately do NOT create the proposer pool: no agent answers device_actuate.
    adapter = _CountingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)
    _pair(runtime.device_node_registry, "phone-1", frozenset({"device.location"}))
    rec_before = trust_spy.get_record("device:phone-1")
    alpha_before, beta_before = rec_before.alpha, rec_before.beta

    result = await runtime.submit_device_actuate_with_consensus(
        "phone-1", "device.location", {}, timeout=5.0
    )

    assert result["consensus"].outcome == ConsensusOutcome.INSUFFICIENT
    assert result["committed"] is False
    assert len(adapter.calls) == 0  # <-- the era-4 regression guard
    # Episode still stored.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["success"] is False
    # Override: an INSUFFICIENT vote (operator did not run the pool) records NO trust.
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:phone-1"]
    assert device_outcomes == []
    rec_after = trust_spy.get_record("device:phone-1")
    assert (rec_after.alpha, rec_after.beta) == (alpha_before, beta_before)


@pytest.mark.asyncio
async def test_unauthorized_device_refused_before_consensus(runtime, tmp_path):
    """Unpaired device → refused before consensus: no trust, no votes, no actuate."""
    adapter = _CountingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)

    result = await runtime.submit_device_actuate_with_consensus(
        "ghost-1", "device.location", {}
    )

    assert result["authorized"] is False
    assert result["committed"] is False
    assert result["consensus"] is None
    assert len(adapter.calls) == 0
    # Episode stored, marked unauthorized.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["authorized"] is False
    assert device_eps[0].outcomes[0]["success"] is False
    # c-1 parity: a grant-gate refusal is NOT a scored outcome — no trust + no record.
    assert trust_spy.get_record("device:ghost-1") is None
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:ghost-1"]
    assert device_outcomes == []


@pytest.mark.asyncio
async def test_store_device_consensus_episode_honest_degrade_when_no_memory(runtime):
    """No episodic memory → the episode helper is a no-op, never raises."""
    runtime.episodic_memory = None
    await runtime._store_device_consensus_episode(
        device_id="phone-1",
        intent_name="device.location",
        authorized=True,
        committed=True,
        reason="",
    )  # must not raise


@pytest.mark.asyncio
async def test_approved_but_actuate_fails_records_trust_failure(runtime, tmp_path):
    """APPROVED but the actuation fails → committed=False, but a trust FAILURE IS recorded.

    The override penalizes a real actuation failure (an actuation WAS attempted),
    while NOT penalizing governance rejections / insufficient votes (tests 7/8).
    """
    await runtime.create_pool(
        "device_consensus", "device_consensus_proposer", target_size=3
    )
    adapter = _FailingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)
    _pair(runtime.device_node_registry, "phone-1", frozenset({"device.location"}))

    result = await runtime.submit_device_actuate_with_consensus(
        "phone-1", "device.location", {}, timeout=5.0
    )

    assert result["consensus"].outcome == ConsensusOutcome.APPROVED
    assert result["committed"] is False
    assert len(adapter.calls) == 1  # an actuation WAS attempted
    # An actuation was attempted → a trust failure IS recorded (success=False).
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:phone-1"]
    assert device_outcomes == [("device:phone-1", False)]
    # Episode stored, marked not-committed.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["success"] is False


@pytest.mark.asyncio
async def test_authorized_but_missing_device_fails_closed(runtime, tmp_path):
    """Defensive guard: authorize() True but get_device() None (removal race) → fail CLOSED.

    Replaces the prior ``assert device is not None`` (which a ``-O`` build strips).
    No consensus broadcast, zero actuate, an episode is still stored (audit
    completeness) marked authorized-but-not-committed, and NO trust outcome is
    written (no actuation was attempted).
    """
    adapter = _CountingAdapter()
    trust_spy, ep_spy = _install_spies(runtime, tmp_path, adapter=adapter)
    _pair(runtime.device_node_registry, "phone-1", frozenset({"device.location"}))
    # authorize() reads ``_devices`` directly (still True); simulate the node
    # vanishing between authorize() and get_device().
    runtime.device_node_registry.get_device = lambda _id: None

    result = await runtime.submit_device_actuate_with_consensus(
        "phone-1", "device.location", {}
    )

    assert result["authorized"] is True
    assert result["committed"] is False
    assert result["consensus"] is None          # never reached the broadcast
    assert result["reason"] == "device_missing"
    assert len(adapter.calls) == 0              # fail-closed: zero actuate
    # Episode stored, authorized=True but not committed.
    device_eps = _device_episodes(ep_spy)
    assert len(device_eps) == 1
    assert device_eps[0].outcomes[0]["authorized"] is True
    assert device_eps[0].outcomes[0]["success"] is False
    assert device_eps[0].outcomes[0]["reason"] == "device_missing"
    # No actuation attempted → no trust outcome.
    device_outcomes = [o for o in trust_spy.outcomes if o[0] == "device:phone-1"]
    assert device_outcomes == []


# ------------------------------------------------------------------
# Wiring + c-1 regression tests (own runtime, no start() needed)
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wire_device_consensus_off_is_noop(tmp_path):
    """Default-OFF: no pool, no dispatch subscription → byte-identical to AD-843c-1."""
    cfg = SystemConfig()  # device.enabled is False by default
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=cfg)

    wired = await _wire_device_consensus(runtime=rt, config=cfg)

    assert wired is False
    assert "device_consensus" not in rt.pools
    assert "device_consensus_dispatch" not in rt.intent_bus._subscribers
    for name in ("device.location", "device.camera", "device.screen"):
        assert "device_consensus_dispatch" not in rt.intent_bus._intent_index.get(name, set())


@pytest.mark.asyncio
async def test_wire_device_consensus_subscribes_as_deterministic(tmp_path):
    cfg = SystemConfig()
    cfg.device.enabled = True
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=cfg)

    wired = await _wire_device_consensus(runtime=rt, config=cfg)

    assert wired is True
    assert (
        rt.intent_bus._subscriber_latency_classes["device_consensus_dispatch"]
        == HandlerLatencyClass.DETERMINISTIC
    )


@pytest.mark.asyncio
async def test_device_notify_path_unchanged(tmp_path):
    """c-1 regression: device.notify still routes through the NON-consensus service."""
    cfg = SystemConfig()
    cfg.device.enabled = True
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=cfg)

    # The c-1 device.notify subscription is on the SERVICE id, not the c-2 dispatch.
    assert DEVICE_NODE_SERVICE_ID in rt.intent_bus._intent_index["device.notify"]
    assert "device_consensus_dispatch" not in rt.intent_bus._intent_index.get(
        "device.notify", set()
    )

    # The c-1 service path still actuates device.notify (non-consensus, NoOp echo).
    _pair(rt.device_node_registry, "phone-1", frozenset({"device.notify"}))
    result = await rt.device_node_service.handle_intent(
        IntentMessage(intent="device.notify", params={"device_id": "phone-1"})
    )

    assert result is not None
    assert result.success is True
    assert result.result["backend"] == "noop"
