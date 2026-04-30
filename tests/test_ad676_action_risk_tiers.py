from __future__ import annotations

from probos.config import RiskTierConfig
from probos.events import EventType
from probos.governance.risk_tiers import ActionRiskRegistry, RiskTier


def test_risk_tier_enum_values() -> None:
    assert RiskTier.ROUTINE.value == "routine"
    assert RiskTier.ELEVATED.value == "elevated"
    assert RiskTier.CRITICAL.value == "critical"


def test_default_action_classifications() -> None:
    registry = ActionRiskRegistry()

    assert registry.get_tier("dm") is RiskTier.ROUTINE
    assert registry.get_tier("reply") is RiskTier.ELEVATED
    assert registry.get_tier("lock") is RiskTier.CRITICAL
    assert registry.get_tier("patch") is RiskTier.CRITICAL


def test_unregistered_action_defaults_to_routine() -> None:
    registry = ActionRiskRegistry()

    assert registry.get_tier("unregistered_action") is RiskTier.ROUTINE


def test_check_authorization_routine() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization("dm", rank_ordinal=0) is True


def test_check_authorization_elevated_denied() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization("reply", rank_ordinal=0) is False


def test_check_authorization_elevated_with_clearance() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization(
        "reply",
        rank_ordinal=0,
        has_clearance_grant=True,
    ) is True


def test_check_authorization_critical() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization(
        "patch",
        rank_ordinal=2,
        trust_score=0.75,
    ) is True


def test_check_authorization_critical_low_trust() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization(
        "patch",
        rank_ordinal=2,
        trust_score=0.50,
    ) is False


def test_captain_override_bypasses_all() -> None:
    registry = ActionRiskRegistry()

    assert registry.check_authorization(
        "patch",
        rank_ordinal=0,
        trust_score=0.0,
        is_captain_override=True,
    ) is True


def test_register_custom_action() -> None:
    registry = ActionRiskRegistry()

    registry.register("purge_cache", RiskTier.ELEVATED)

    assert registry.get_tier("purge_cache") is RiskTier.ELEVATED
    assert registry.list_actions(RiskTier.ELEVATED)["purge_cache"] is RiskTier.ELEVATED


def test_action_risk_denied_event_exists() -> None:
    assert EventType.ACTION_RISK_DENIED.value == "action_risk_denied"


def test_risk_tier_config_defaults() -> None:
    config = RiskTierConfig()

    assert config.enabled is True
    assert config.elevated_min_trust == 0.0
    assert config.critical_min_trust == 0.70
