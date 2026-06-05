"""AD-884 — Authority-scoping regression guard for the Quartermaster.

The Quartermaster's mutations (unassign / re-dispatch / metadata quarantine
flag) are reversible board housekeeping. Per the Reversibility Preference and
Minimal Authority axioms it requires **no** consensus gate — but that scoping
must stay explicit and guarded. These tests lock the capability surface to
reconcile-only, consensus-free, Utility-tier operations (BF-287: real agent,
no LLM, no mocks).
"""

from __future__ import annotations

from probos.agents.quartermaster import QuartermasterAgent


def _qm() -> QuartermasterAgent:
    return QuartermasterAgent(pool="utility", agent_id="qm-1")


def test_declared_intents_are_reconcile_only() -> None:
    qm = _qm()

    names = {d.name for d in qm.intent_descriptors}

    assert names <= QuartermasterAgent.RECONCILE_ONLY_INTENTS
    assert names == {"reconcile_board"}


def test_no_declared_intent_requires_consensus() -> None:
    qm = _qm()

    assert not any(d.requires_consensus for d in qm.intent_descriptors)


def test_stays_utility_tier_quartermaster() -> None:
    qm = _qm()

    assert qm.tier == "utility"
    assert qm.agent_type == "quartermaster"
