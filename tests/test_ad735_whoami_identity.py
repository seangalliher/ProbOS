"""AD-735: verified self-identity grounding on the DM path (whoami).

Covers:
  1. whoami() happy path — cert fields win over public attrs.
  2. whoami() honest-degrade — no cert/registry yields public subset, no fabrication.
  3. whoami_block() spells the callsign (E-z-r-i style).
  4. Classifier detects identity (first in ladder) + negative cases + AD-725 no-regression.
  5. Dispatcher injects the identity block (gated by identity_enabled).
  6. Firewall preserved — no intent_bus broadcast, respects timeout.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.dm_targeted_lookup import (
    LookupDispatcher,
    RegexSubintentClassifier,
    TargetedLookupResult,
)
from probos.config import DmTargetedLookupConfig
from probos.identity import AgentBirthCertificate


def _make_cert(
    *,
    callsign: str = "Ezri",
    department: str = "Medical",
    birth_timestamp: float = 1_739_525_267.0,
    certificate_hash: str = "4f1a9c2b8d031234deadbeef",
    vessel_name: str = "USS Enterprise",
    did: str = "did:probos:inst-1:uuid-1",
) -> AgentBirthCertificate:
    return AgentBirthCertificate(
        agent_uuid="uuid-1",
        did=did,
        agent_type="counselor",
        callsign=callsign,
        instance_id="inst-1",
        vessel_name=vessel_name,
        birth_timestamp=birth_timestamp,
        department=department,
        post_id="post-1",
        baseline_version="v1.0.0",
        certificate_hash=certificate_hash,
    )


def _make_agent(**overrides: Any) -> CognitiveAgent:
    """Bare CognitiveAgent for unit testing (mirrors test_bf101 pattern)."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.callsign = ""
    agent.agent_type = "counselor"
    agent.id = "med_counselor_0_abc12345"
    agent._runtime = None
    for k, v in overrides.items():
        setattr(agent, k, v)
    return agent


# ---------------------------------------------------------------------------
# 1. whoami() happy path — cert wins
# ---------------------------------------------------------------------------
def test_whoami_happy_path_prefers_cert_fields() -> None:
    cert = _make_cert(callsign="Ezri", department="Medical")
    registry = MagicMock()
    registry.get_by_slot.return_value = cert
    rt = SimpleNamespace(_identity_registry=registry)
    agent = _make_agent(callsign="StalePublic", _runtime=rt)

    facts = agent.whoami()

    assert facts["callsign"] == "Ezri"  # cert wins over public attr
    assert facts["department"] == "Medical"
    assert facts["did"] == "did:probos:inst-1:uuid-1"
    assert facts["certificate_hash"] == "4f1a9c2b8d03"  # 12-char prefix
    assert facts["birth_iso"].startswith("2025-")  # ISO from float epoch
    assert facts["vessel_name"] == "USS Enterprise"


# ---------------------------------------------------------------------------
# 2. whoami() honest-degrade — no cert / no registry
# ---------------------------------------------------------------------------
def test_whoami_honest_degrade_no_cert_omits_fabricated_keys() -> None:
    agent = _make_agent(callsign="Ezri", _runtime=None)

    facts = agent.whoami()

    assert facts["callsign"] == "Ezri"
    assert facts["agent_type"] == "counselor"
    # Department derived from static mapping (may or may not resolve), but
    # cert-only fields must be absent — never fabricated.
    assert "did" not in facts
    assert "birth_iso" not in facts
    assert "certificate_hash" not in facts
    assert "vessel_name" not in facts


def test_whoami_malformed_birth_timestamp_omits_birth() -> None:
    cert = _make_cert()
    cert = SimpleNamespace(
        callsign="Ezri",
        department="Medical",
        did="did:probos:inst-1:uuid-1",
        birth_timestamp="not-a-float",  # malformed
        certificate_hash="4f1a9c2b8d031234",
        vessel_name="USS Enterprise",
    )
    registry = MagicMock()
    registry.get_by_slot.return_value = cert
    rt = SimpleNamespace(_identity_registry=registry)
    agent = _make_agent(callsign="Ezri", _runtime=rt)

    facts = agent.whoami()

    assert "birth_iso" not in facts  # guard prevents raise on bad float
    assert facts["certificate_hash"] == "4f1a9c2b8d03"


# ---------------------------------------------------------------------------
# 3. whoami_block() spells the callsign
# ---------------------------------------------------------------------------
def test_whoami_block_spells_callsign() -> None:
    cert = _make_cert(callsign="Ezri", department="Medical")
    registry = MagicMock()
    registry.get_by_slot.return_value = cert
    rt = SimpleNamespace(_identity_registry=registry)
    agent = _make_agent(callsign="Ezri", _runtime=rt)

    block = agent.whoami_block()

    assert "Callsign: Ezri (spelled E-z-r-i)" in block
    assert "Role / agent_type: counselor" in block
    assert "Department: Medical" in block
    assert "Identity hash: 4f1a9c2b8d03" in block


# ---------------------------------------------------------------------------
# 4. Classifier — identity detection + negatives + AD-725 no-regression
# ---------------------------------------------------------------------------
def test_classifier_detects_identity() -> None:
    clf = RegexSubintentClassifier()
    lt, _ = clf.classify("how is your name spelled?", agent_id="a1")
    assert lt == "identity"


def test_classifier_identity_who_are_you() -> None:
    clf = RegexSubintentClassifier()
    lt, _ = clf.classify("who are you?", agent_id="a1")
    assert lt == "identity"


def test_classifier_negative_function_name_not_identity() -> None:
    clf = RegexSubintentClassifier()
    lt, _ = clf.classify("how do you spell the name of that function", agent_id="a1")
    assert lt != "identity"


def test_classifier_negative_role_play_not_identity() -> None:
    clf = RegexSubintentClassifier()
    lt, _ = clf.classify("what role do you want me to play", agent_id="a1")
    assert lt != "identity"


def test_classifier_ad725_ladder_no_regression() -> None:
    clf = RegexSubintentClassifier()
    assert clf.classify("what time is it?", agent_id="a1")[0] == "oracle"
    assert clf.classify("what did we discuss last time?", agent_id="a1")[0] == "episodic"
    assert clf.classify("which file is FooBar defined in?", agent_id="a1")[0] == "codebase"
    assert clf.classify("according to the manual, what is the policy?", agent_id="a1")[0] == "knowledge"
    assert clf.classify("hi", agent_id="a1")[0] == "none"


# ---------------------------------------------------------------------------
# 5. Dispatcher — identity injection gated by identity_enabled
# ---------------------------------------------------------------------------
def _identity_runtime(agent: Any) -> SimpleNamespace:
    registry = SimpleNamespace(get=lambda aid: agent)
    rt = SimpleNamespace()
    rt.registry = registry
    # Firewall sentinels — must remain untouched.
    rt.intent_bus = MagicMock()
    rt.trust_network = MagicMock()
    rt.hebbian_router = MagicMock()
    return rt


@pytest.mark.asyncio
async def test_dispatcher_injects_identity_block_when_enabled() -> None:
    cert = _make_cert(callsign="Ezri")
    reg = MagicMock()
    reg.get_by_slot.return_value = cert
    inner_rt = SimpleNamespace(_identity_registry=reg)
    target = _make_agent(callsign="Ezri", _runtime=inner_rt)

    cfg = DmTargetedLookupConfig(enabled=True, identity_enabled=True)
    rt = _identity_runtime(target)
    d = LookupDispatcher(runtime=rt, config=cfg)

    out = await d.maybe_lookup("who are you?", agent_id="ezri")

    assert isinstance(out, TargetedLookupResult)
    assert out.lookup_type == "identity"
    assert "spelled E-z-r-i" in out.content


@pytest.mark.asyncio
async def test_dispatcher_identity_disabled_returns_none() -> None:
    target = _make_agent(callsign="Ezri")
    cfg = DmTargetedLookupConfig(enabled=True, identity_enabled=False)
    rt = _identity_runtime(target)
    d = LookupDispatcher(runtime=rt, config=cfg)

    out = await d.maybe_lookup("who are you?", agent_id="ezri")

    assert out is None


# ---------------------------------------------------------------------------
# 6. Firewall preserved
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatcher_identity_no_intent_bus_broadcast() -> None:
    cert = _make_cert(callsign="Ezri")
    reg = MagicMock()
    reg.get_by_slot.return_value = cert
    inner_rt = SimpleNamespace(_identity_registry=reg)
    target = _make_agent(callsign="Ezri", _runtime=inner_rt)

    cfg = DmTargetedLookupConfig(enabled=True, identity_enabled=True)
    rt = _identity_runtime(target)
    d = LookupDispatcher(runtime=rt, config=cfg)

    await d.maybe_lookup("who are you?", agent_id="ezri")

    rt.intent_bus.broadcast.assert_not_called()
    rt.trust_network.record_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_identity_respects_timeout() -> None:
    # Prove the "identity" lookup_type flows through the same AD-725
    # wait_for(timeout) firewall wrapper as every other type: an async-slow
    # dispatch is cancelled and degrades to None.
    class _SlowDispatcher(LookupDispatcher):
        async def _dispatch(self, lookup_type, query, agent_id):  # type: ignore[override]
            import asyncio
            await asyncio.sleep(0.5)
            return "Callsign: Slow (spelled S-l-o-w)"

    cfg = DmTargetedLookupConfig(enabled=True, identity_enabled=True, timeout_ms=10)
    rt = _identity_runtime(_make_agent(callsign="Ezri"))
    d = _SlowDispatcher(runtime=rt, config=cfg)

    out = await d.maybe_lookup("who are you?", agent_id="ezri")

    assert out is None  # timed out -> degrade
