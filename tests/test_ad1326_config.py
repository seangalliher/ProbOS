"""AD-1326 (#1510), milestone 2: the ``dreaming.procedure_challenger_*`` configuration.

``DreamingConfig`` carries the legacy flag (``procedure_challenger_enabled``, default True) and
seven bounded siblings, with a parse-time rule that refuses ``min_decisions`` above the situations a
full recall of ``PROCEDURE_EVOLUTION_EPISODE_LIMIT`` (10) episodes can give one challenge:
``min(held_out_episodes, 5)`` held-out ones plus at most ``10 - held_out`` used ones. Review round 1
(F6) bounded ``used_contexts`` 0..10, ``held_out_episodes`` 0..5 and ``min_decisions`` 1..10, because a
configuration the dream cycle could never satisfy (``used_contexts=10, held_out_episodes=10,
min_decisions=20``) was accepted. Each test parses the section
the way its callers do: the constructor, ``model_validate`` of a plain dict, ``SystemConfig`` and the
operator's YAML through ``load_config``.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import probos.config as config_facade
from probos.cognitive import dreaming
from probos.config import SystemConfig, load_config
from probos.config_models import cognition as cognition_models
from probos.config_models.cognition import DreamingConfig

_USED = "procedure_challenger_used_contexts"
_HELD = "procedure_challenger_held_out_episodes"
_MIN = "procedure_challenger_min_decisions"
_MARGIN = "procedure_challenger_promotion_margin"
_CALLS = "procedure_challenger_max_judge_calls_per_cycle"
_CYCLES = "procedure_challenger_max_pending_cycles"
_PER_CHAMPION = "procedure_challenger_max_pending_per_champion"

_DEFAULTS: dict[str, Any] = {
    "procedure_challenger_enabled": True,
    _USED: 2,
    _HELD: 2,
    _MIN: 3,
    _MARGIN: 0.1,
    _CALLS: 16,
    _CYCLES: 5,
    _PER_CHAMPION: 2,
}
_ROUTES = ["kwargs", "dict", "system_config", "yaml_file"]


def _parse(route: str, values: dict[str, Any], tmp_path: Path) -> DreamingConfig:
    """Parse ``values`` as the ``dreaming`` section the way one of its callers does."""
    if route == "kwargs":
        return DreamingConfig(**values)
    if route == "dict":
        return DreamingConfig.model_validate(values)
    if route == "system_config":
        return SystemConfig.model_validate({"dreaming": values}).dreaming
    path = tmp_path / "system.yaml"
    path.write_text(yaml.safe_dump({"dreaming": values}), encoding="utf-8")
    return load_config(path).dreaming


def _short(field: str) -> str:
    return field.removeprefix("procedure_challenger_")


def test_challenger_defaults() -> None:
    config = DreamingConfig()

    assert {name: getattr(config, name) for name in _DEFAULTS} == _DEFAULTS
    # The flag and seven bounded siblings are all there is: no unlisted procedure_challenger_* field.
    assert {name for name in DreamingConfig.model_fields if name.startswith("procedure_challenger_")} == set(_DEFAULTS)
    # The defaults satisfy the cross-field rule and reach a SystemConfig unchanged.
    system = SystemConfig().dreaming
    assert {name: getattr(system, name) for name in _DEFAULTS} == _DEFAULTS


# Each field: the value just below its lower bound, and the first value above its upper bound.
# Review round 1 (F6): held_out_episodes is bounded 0..5 (it was 0..10) and min_decisions 1..10 (it was 1..20),
# so the first values above them are 6 and 11 (they were 11 and 21: still refused, but no longer the first
# value above the bound, so they could not tell the new bound from the old one). used_contexts keeps 0..10.
_OUT_OF_RANGE = [
    (_USED, -1, 11),
    (_HELD, -1, 6),
    (_MIN, 0, 11),
    (_MARGIN, -0.0001, 0.5),  # the margin's upper bound is exclusive: 0.5 itself is refused
    (_CALLS, -1, 201),
    (_CYCLES, 0, 101),
    (_PER_CHAMPION, 0, 6),
]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param(field, value, id=f"{_short(field)}={value}")
        for field, below, above in _OUT_OF_RANGE
        for value in (below, above)
    ],
)
def test_challenger_bounds_reject_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValidationError) as refused:
        DreamingConfig(**{field: value})

    # Refused by the field's own bound (loc is the field), not by the cross-field rule (loc is empty).
    assert {error["loc"] for error in refused.value.errors()} == {(field,)}


# Each bound value that is allowed, with the companion values the cross-field rule needs at that bound.
_ACCEPTED_BOUNDS = [
    (_USED, 0, {_MIN: 2}),
    (_USED, 10, {}),
    (_HELD, 0, {_MIN: 2}),
    (_HELD, 5, {}),  # review round 1 (F6): 10 until then; at most half of the 10 episodes one recall holds
    (_MIN, 1, {}),
    (_MIN, 10, {_USED: 10, _HELD: 5}),  # review round 1 (F6): 20, with 10 used and 10 held out, until then
    (_MARGIN, 0.0, {}),
    (_MARGIN, math.nextafter(0.5, 0.0), {}),  # the largest float below the exclusive 0.5
    (_CALLS, 0, {}),
    (_CALLS, 200, {}),
    (_CYCLES, 1, {}),
    (_CYCLES, 100, {}),
    (_PER_CHAMPION, 1, {}),
    (_PER_CHAMPION, 5, {}),
]


@pytest.mark.parametrize(
    ("field", "value", "companions"),
    [
        pytest.param(field, value, companions, id=f"{_short(field)}={value}")
        for field, value, companions in _ACCEPTED_BOUNDS
    ],
)
def test_challenger_bounds_accept_the_bound_values(field: str, value: float, companions: dict[str, Any]) -> None:
    config = DreamingConfig(**{**companions, field: value})

    assert getattr(config, field) == value


# Settings whose min_decisions exceeds the situations a full recall of 10 episodes can give one challenge:
# min(held_out_episodes, 5) held-out ones plus min(used_contexts, 10 - held_out) used ones. Each is paired with
# that number, which the rejection message names. No challenger could ever be promoted under any of them.
_UNDECIDABLE = [
    pytest.param({_USED: 1, _HELD: 1, _MIN: 3}, 2, id="min_3_above_1_plus_1"),
    pytest.param({_USED: 2, _HELD: 2, _MIN: 5}, 4, id="min_5_above_2_plus_2"),
    pytest.param({_USED: 0, _HELD: 0, _MIN: 1}, 0, id="no_situation_at_all"),
    pytest.param({_USED: 0}, 2, id="used_contexts_0_with_the_default_min_decisions"),
    pytest.param({_HELD: 0}, 2, id="held_out_episodes_0_with_the_default_min_decisions"),
    pytest.param({_USED: 4, _HELD: 5, _MIN: 10}, 9, id="min_10_above_4_plus_5_one_short_of_a_full_recall"),
    pytest.param({_USED: 8, _HELD: 0, _MIN: 9}, 8, id="min_9_above_8_plus_0"),
]


@pytest.mark.parametrize("route", _ROUTES)
@pytest.mark.parametrize(("values", "achievable"), _UNDECIDABLE)
def test_min_decisions_above_available_situations_is_rejected_at_parse_time(
    route: str, values: dict[str, Any], achievable: int, tmp_path: Path,
) -> None:
    # The cross-field rule's own message. A field bound's error also names the field, so with the bounds this
    # tight the field name alone (all this test used to match) would pass for a case the bounds refuse.
    message = (
        "procedure_challenger_min_decisions exceeds the comparison situations one challenge can have "
        f"({achievable} from at most 10 recalled episodes)"
    )
    with pytest.raises(ValidationError, match=re.escape(message)):
        _parse(route, values, tmp_path)


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({_USED: 1, _HELD: 2, _MIN: 3}, id="min_3_equals_1_plus_2"),
        pytest.param({_USED: 2, _HELD: 1, _MIN: 3}, id="min_3_equals_2_plus_1"),
        pytest.param({_USED: 1, _HELD: 1, _MIN: 2}, id="min_2_equals_1_plus_1"),
    ],
)
def test_min_decisions_equal_to_available_situations_is_accepted(values: dict[str, Any]) -> None:
    config = DreamingConfig(**values)

    assert {name: getattr(config, name) for name in values} == values


@pytest.mark.parametrize("route", _ROUTES)
def test_flag_off_validates_from_a_plain_dict(route: str, tmp_path: Path) -> None:
    config = _parse(route, {"procedure_challenger_enabled": False}, tmp_path)

    assert config.procedure_challenger_enabled is False
    siblings = {name: value for name, value in _DEFAULTS.items() if name != "procedure_challenger_enabled"}
    assert {name: getattr(config, name) for name in siblings} == siblings  # the seven bounded siblings keep their defaults


@pytest.mark.parametrize("route", _ROUTES)
def test_reviewers_unreachable_configuration_is_rejected(route: str, tmp_path: Path) -> None:
    # Review round 1 (F6): this was accepted, yet one dream cycle recalls at most 10 episodes, so no challenge
    # could ever hold 20 situations and no challenger could ever be promoted.
    with pytest.raises(ValidationError) as refused:
        _parse(route, {_USED: 10, _HELD: 10, _MIN: 20}, tmp_path)

    # Refused by the two bounds that moved (held_out_episodes 0..5, min_decisions 1..10); used_contexts=10 is allowed.
    assert {error["loc"][-1] for error in refused.value.errors()} == {_HELD, _MIN}

    # The most one full recall can give is accepted: 5 held out and 5 used, so 10 situations.
    config = _parse(route, {_USED: 10, _HELD: 5, _MIN: 10}, tmp_path)

    assert (config.procedure_challenger_used_contexts, config.procedure_challenger_held_out_episodes) == (10, 5)
    assert config.procedure_challenger_min_decisions == 10


def test_validator_reads_the_shared_recall_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review round 1 (F6): the validator and the dream cycle's three recall caps share one constant.
    name = "PROCEDURE_EVOLUTION_EPISODE_LIMIT"
    assert cognition_models.PROCEDURE_EVOLUTION_EPISODE_LIMIT == 10
    assert dreaming.PROCEDURE_EVOLUTION_EPISODE_LIMIT is cognition_models.PROCEDURE_EVOLUTION_EPISODE_LIMIT
    # ``is`` cannot tell an import from a second literal 10 (CPython shares small ints), so also read dreaming.py:
    # it imports the name from config_models.cognition and binds it nowhere else.
    tree = ast.parse(Path(dreaming.__file__).read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "probos.config_models.cognition"
        for alias in node.names
    ]
    stored = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store)
    ]
    assert name in imported
    assert stored == []
    # The facade's public surface is pinned (tests/test_ad1270e1_config_facade.py): the name is not re-exported.
    assert not hasattr(config_facade, name)

    # The validator reads the constant when it runs. With 10 episodes recalled, 4 used and 2 held out give 6 situations
    values = {_USED: 4, _HELD: 2, _MIN: 6}
    assert DreamingConfig(**values).procedure_challenger_min_decisions == 6
    # and with 4 recalled they give 4: 2 held out (at most half) and 2 used.
    monkeypatch.setattr(cognition_models, name, 4)
    with pytest.raises(ValidationError, match=re.escape("(4 from at most 4 recalled episodes)")):
        DreamingConfig(**values)
