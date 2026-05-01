"""AD-499: Ship & Crew Naming Conventions tests."""

from __future__ import annotations

import pytest

from probos.config import NamingConfig
from probos.events import EventType
from probos.naming import (
    AgentNamingPolicy,
    CallsignValidation,
    FederationDisplayFormat,
    ShipNameDecision,
    ShipNamingPolicy,
)


def test_event_type_ship_named_exists() -> None:
    assert EventType.SHIP_NAMED.value == "ship_named"


def test_event_type_agent_self_named_exists() -> None:
    assert EventType.AGENT_SELF_NAMED.value == "agent_self_named"


def test_ship_naming_captain_override() -> None:
    policy = ShipNamingPolicy()
    decision = policy.select(instance_id="abc", override_name="Yamato")
    assert decision.name == "Yamato"
    assert decision.source == "captain_override"
    assert decision.seed == "abc"


def test_ship_naming_deterministic_seed_stable() -> None:
    policy = ShipNamingPolicy()
    d1 = policy.select(instance_id="instance-uuid-fixed-1234")
    d2 = policy.select(instance_id="instance-uuid-fixed-1234")
    assert d1.name == d2.name
    assert d1.source == "deterministic_seed"
    assert d1.name in policy.pool


def test_ship_naming_distinct_instance_ids_likely_distinct_names() -> None:
    policy = ShipNamingPolicy()
    name_a = policy.select(instance_id="instance-A").name
    name_b = policy.select(instance_id="instance-B").name
    assert name_a in policy.pool
    assert name_b in policy.pool


def test_ship_naming_empty_pool_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ShipNamingPolicy(pool=())


def test_ship_naming_empty_instance_id_raises() -> None:
    policy = ShipNamingPolicy()
    with pytest.raises(ValueError, match="instance_id required"):
        policy.select(instance_id="")


def test_callsign_validation_happy_path() -> None:
    policy = AgentNamingPolicy()
    result = policy.validate("Picard")
    assert result.accepted is True
    assert result.normalized == "Picard"
    assert result.reason == ""


def test_callsign_validation_lowercase_first_rejected() -> None:
    policy = AgentNamingPolicy()
    result = policy.validate("picard")
    assert result.accepted is False
    assert result.reason == "format_invalid"


def test_callsign_validation_banned_word_rejected() -> None:
    policy = AgentNamingPolicy()
    result = policy.validate("admin")
    assert result.accepted is False
    assert result.reason == "banned_word"


def test_callsign_validation_empty_input_rejected() -> None:
    policy = AgentNamingPolicy()
    assert policy.validate(None).reason == "empty_input"
    assert policy.validate("").reason == "empty_input"
    assert policy.validate("   ").reason == "empty_input"


def test_callsign_validation_extra_banned_words_merged() -> None:
    policy = AgentNamingPolicy(banned=frozenset({"Picard"}))
    result = policy.validate("Picard")
    assert result.accepted is False
    assert result.reason == "banned_word"


def test_federation_display_format_full() -> None:
    assert FederationDisplayFormat.format("Picard", "Enterprise") == "Picard [Enterprise]"


def test_federation_display_format_empty_inputs_no_raise() -> None:
    assert FederationDisplayFormat.format("", "") == ""
    assert FederationDisplayFormat.format("Picard", "") == "Picard"
    assert FederationDisplayFormat.format("", "Enterprise") == "[Enterprise]"


def test_naming_config_defaults() -> None:
    cfg = NamingConfig()
    assert cfg.enabled is True
    assert cfg.captain_ship_override == ""
    assert cfg.extra_banned_words == []


def test_callsign_validation_returns_dataclass() -> None:
    policy = AgentNamingPolicy()
    result = policy.validate("Riker")
    assert isinstance(result, CallsignValidation)


def test_ship_name_decision_returns_dataclass() -> None:
    policy = ShipNamingPolicy()
    decision = policy.select(instance_id="x", override_name="Constellation")
    assert isinstance(decision, ShipNameDecision)
    assert decision.pool_size == len(policy.pool)
