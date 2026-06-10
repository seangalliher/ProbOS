"""AD-958a: exploration / anti-rich-get-richer term in the chat facilitator.

A trust-weighted facilitator risks rich-get-richer: a high-trust agent keeps
being surfaced and a low-trust but domain-relevant agent never gets a chance to
EARN trust. AD-958a adds a deterministic "optimism under uncertainty" (UCB-style)
exploration bonus — ``weight_exploration * department_relevance * (1 - trust)``
— so a domain-relevant newcomer is surfaced to earn trust while a high-trust
agent (already carried by the trust term) gets ~0 extra. Bounded below the
mention weight so a direct address always wins; NO randomness (the facilitator
stays pure + deterministic). Default 0.0 (off) — transitional flag #14.

The ``ChatFacilitator`` is a pure value-class (no I/O), so these test it
directly with ``SpeakerSignals`` — no fixtures needed.
"""
from __future__ import annotations

from probos.cognitive.chat_facilitator import ChatFacilitator, SpeakerSignals
from probos.config import GroupChatConfig


def test_exploration_off_by_default_is_byte_identical():
    # Pydantic default weight_exploration=0.0 -> no exploration factor at all,
    # ranking identical to pre-AD-958a.
    f = ChatFacilitator()  # all defaults, exploration off
    sigs = [
        SpeakerSignals(agent_id="proven", department_relevance=0.8, trust=0.9, order_index=0),
        SpeakerSignals(agent_id="newcomer", department_relevance=0.8, trust=0.1, order_index=1),
    ]
    ranked = f.rank(sigs)
    # No exploration factor present on any score.
    assert all("exploration" not in s.factors for s in ranked)
    # With exploration OFF, the higher-trust agent wins the tie on relevance.
    assert ranked[0].agent_id == "proven"


def test_exploration_surfaces_unproven_domain_relevant_agent():
    # Two equally domain-relevant agents; one proven (high trust), one a
    # newcomer (low trust). With exploration ON, the newcomer is surfaced to
    # EARN trust — it outranks the proven agent.
    f = ChatFacilitator(weight_exploration=0.15)
    sigs = [
        SpeakerSignals(agent_id="proven", department_relevance=0.8, trust=0.9, order_index=0),
        SpeakerSignals(agent_id="newcomer", department_relevance=0.8, trust=0.1, order_index=1),
    ]
    ranked = f.rank(sigs)
    assert ranked[0].agent_id == "newcomer"
    # The exploration factor is recorded for the newcomer (diagnostics).
    newcomer = next(s for s in ranked if s.agent_id == "newcomer")
    assert newcomer.factors.get("exploration", 0.0) > 0.0


def test_exploration_is_near_zero_for_a_high_trust_agent():
    # A fully-trusted agent gets ~0 exploration bonus (it is already carried by
    # the trust term) — (1 - trust) -> 0.
    f = ChatFacilitator(weight_exploration=0.15)
    sigs = [SpeakerSignals(agent_id="proven", department_relevance=1.0, trust=1.0, order_index=0)]
    ranked = f.rank(sigs)
    assert ranked[0].factors.get("exploration", 0.0) == 0.0


def test_exploration_is_zero_for_an_irrelevant_agent():
    # An off-topic agent (department_relevance == 0) is NEVER boosted, however
    # low its trust — exploration is gated on relevance.
    f = ChatFacilitator(weight_exploration=0.15)
    sigs = [SpeakerSignals(agent_id="offtopic", department_relevance=0.0, trust=0.0, order_index=0)]
    ranked = f.rank(sigs)
    assert ranked[0].factors.get("exploration", 0.0) == 0.0


def test_exploration_never_beats_a_direct_mention():
    # A directly-addressed agent (mention 0.40) must still win over a maximally-
    # boosted unproven agent (exploration max = 0.15 at dep=1, trust=0). The
    # bound (weight_exploration < weight_mention) preserves AD-951 rule 1a.
    f = ChatFacilitator(weight_exploration=0.15)
    sigs = [
        SpeakerSignals(agent_id="mentioned", mentioned=True, department_relevance=0.0,
                       trust=1.0, turns_since_last_spoke=0, order_index=0),
        SpeakerSignals(agent_id="newcomer", department_relevance=1.0, trust=0.0,
                       turns_since_last_spoke=99, order_index=1),
    ]
    result = f.facilitate(sigs, [])
    assert result.speaking_order[0] == "mentioned"


def test_exploration_bonus_formula_is_deterministic():
    # The bonus is exactly weight_exploration * dep * (1 - trust) — pure, no RNG.
    f = ChatFacilitator(weight_exploration=0.2)
    sigs = [SpeakerSignals(agent_id="x", department_relevance=0.5, trust=0.25, order_index=0)]
    ranked = f.rank(sigs)
    # 0.2 * 0.5 * (1 - 0.25) = 0.075
    assert abs(ranked[0].factors["exploration"] - 0.075) < 1e-9
    # Re-running yields the identical value (determinism).
    again = f.rank(sigs)
    assert again[0].factors["exploration"] == ranked[0].factors["exploration"]


def test_from_config_reads_weight_exploration():
    gc = GroupChatConfig(weight_exploration=0.15)
    f = ChatFacilitator.from_config(type("C", (), {"group_chat": gc})())
    sigs = [SpeakerSignals(agent_id="newcomer", department_relevance=0.8, trust=0.1, order_index=0)]
    ranked = f.rank(sigs)
    assert ranked[0].factors.get("exploration", 0.0) > 0.0


def test_config_default_exploration_is_off():
    # Transitional flag #14: ships OFF (0.0); system.yaml sets the live value.
    assert GroupChatConfig().weight_exploration == 0.0
