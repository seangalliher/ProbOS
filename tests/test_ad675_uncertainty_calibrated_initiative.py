from probos.earned_agency import InitiativeLevel, UncertaintyContext, calibrate_initiative


def test_high_confidence_no_change() -> None:
    result = calibrate_initiative(InitiativeLevel.PROACTIVE, 0.8)

    assert result == InitiativeLevel.PROACTIVE


def test_low_confidence_clamps_down_one() -> None:
    result = calibrate_initiative(InitiativeLevel.PROACTIVE, 0.3)

    assert result == InitiativeLevel.CONTRIBUTORY


def test_critical_confidence_clamps_down_two() -> None:
    result = calibrate_initiative(InitiativeLevel.STRATEGIC, 0.1)

    assert result == InitiativeLevel.CONTRIBUTORY


def test_directed_stays_directed() -> None:
    result = calibrate_initiative(InitiativeLevel.DIRECTED, 0.1)

    assert result == InitiativeLevel.DIRECTED


def test_uncertainty_context_aggregate() -> None:
    context = UncertaintyContext(0.9, 0.3, 0.8)

    assert context.aggregate_confidence == 0.3


def test_custom_thresholds() -> None:
    result = calibrate_initiative(
        InitiativeLevel.PROACTIVE,
        0.5,
        low_confidence_threshold=0.6,
    )

    assert result == InitiativeLevel.CONTRIBUTORY
