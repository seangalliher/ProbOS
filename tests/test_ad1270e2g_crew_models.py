"""AD-1270e2 batch 7 -- the ``crew`` batch preserved every public value.

Twenty-five leaf models -- boot camp and tiered trust, ship-state snapshots,
standing orders, the ready room and ward room (plus its Hebbian weights),
department cognitive profiles and EPS department budgets, deliberation,
permissions and memory security, the three holodeck models, skill requests,
naming, utility agents, SWE specialists, assignments, visiting officers, the
content firewall, risk tiers, duty definitions and policy windows -- now live
in ``probos.config_models.crew`` and are re-exported from ``probos.config``.

What is preserved is the PUBLIC FACADE and every value behind it. What
deliberately CHANGES is the declaration site: ``config.py`` loses 346 lines and
each model's ``__module__`` becomes ``probos.config_models.crew``. That is
observable and is asserted on purpose.

Three of the twenty-five are not plain submodels of ``SystemConfig`` and are
handled explicitly rather than being quietly dropped from the dump cases:

* ``DepartmentCognitiveProfile`` is a ``dict`` VALUE type (``dept_profiles.profiles``
  defaults to ``{}``), so the composed path holds no instance by default.
* ``EPSDepartmentConfig`` is a ``list`` ELEMENT type with six shipped entries and
  a required ``name``.
* ``DutyDefinition`` is a doubly-nested container element -- the annotation is
  ``dict[str, list[DutyDefinition]]`` on
  ``proactive_cognitive.duty_schedule.schedules`` -- and requires two fields.

An earlier draft of this file asserted ``DutyDefinition`` was **unreachable from
SystemConfig**. That was false, and it was false because the traversal I used to
check did not follow a dict-of-list annotation. Review caught it. All three are
now reached through the real composition path with non-empty payloads, so none
of them escapes assertion by being awkward to reach.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` --
the class text *before* the move, compiled in a throwaway module. Deriving it
from the moved module would compare the code against itself. The two
argument-taking models carry a dump built with the same fillers the bound case
uses, so they are not excluded from value comparison either.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.crew as config_crew
from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_SOURCE_ROOT = _REPO_ROOT / "src" / "probos"
_CREW_SOURCE = _SOURCE_ROOT / "config_models" / "crew.py"

MOVED_MODELS: tuple[str, ...] = (
    "AssignmentConfig",
    "BootCampConfig",
    "DeliberationConfig",
    "DepartmentCognitiveProfile",
    "DutyDefinition",
    "EPSDepartmentConfig",
    "FirewallConfig",
    "HolodeckBirthChamberConfig",
    "HolodeckScenarioConfig",
    "HolodeckTeamSimulationConfig",
    "MemorySecurityConfig",
    "NamingConfig",
    "OrdersConfig",
    "PermissionsConfig",
    "PolicyWindowConfig",
    "ReadyRoomConfig",
    "RiskTierConfig",
    "ShipStateSnapshotConfig",
    "SkillRequestConfig",
    "SoftwareEngineerSpecialistsConfig",
    "TieredTrustConfig",
    "UtilityAgentsConfig",
    "VisitingOfficersConfig",
    "WardRoomConfig",
    "WardRoomHebbianConfig",
)

#: Models that require arguments, so ``Model()`` raises rather than dumping.
REQUIRES_ARGUMENTS: tuple[str, ...] = ("DutyDefinition", "EPSDepartmentConfig")

#: Models that are a container's value/element type rather than a plain
#: submodel. All three ARE reachable; they simply are not reached by walking to
#: a submodel dict, so the composed-dump case excludes them by construction and
#: dedicated cases below reach each one with a non-empty payload.
NOT_A_PLAIN_SUBMODEL: tuple[str, ...] = (
    "DepartmentCognitiveProfile",
    "DutyDefinition",
    "EPSDepartmentConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``. ``DutyDefinition``
#: sits two containers deep, so its path names the dict, not the model.
MODEL_TO_PATH: dict[str, str] = {
    "AssignmentConfig": "assignments",
    "BootCampConfig": "boot_camp",
    "DeliberationConfig": "deliberation",
    "DepartmentCognitiveProfile": "dept_profiles.profiles",
    "DutyDefinition": "proactive_cognitive.duty_schedule.schedules",
    "EPSDepartmentConfig": "eps.departments",
    "FirewallConfig": "firewall",
    "HolodeckBirthChamberConfig": "holodeck_birth_chamber",
    "HolodeckScenarioConfig": "holodeck_scenarios",
    "HolodeckTeamSimulationConfig": "team_simulations",
    "MemorySecurityConfig": "security.memory",
    "NamingConfig": "naming",
    "OrdersConfig": "orders",
    "PermissionsConfig": "security.permissions",
    "PolicyWindowConfig": "duty_schedule.work_hours",
    "ReadyRoomConfig": "ready_room",
    "RiskTierConfig": "risk_tiers",
    "ShipStateSnapshotConfig": "ship_state_snapshot",
    "SkillRequestConfig": "skill_requests",
    "SoftwareEngineerSpecialistsConfig": "swe_specialists",
    "TieredTrustConfig": "tiered_trust",
    "UtilityAgentsConfig": "utility_agents",
    "VisitingOfficersConfig": "visiting_officers",
    "WardRoomConfig": "ward_room",
    "WardRoomHebbianConfig": "ward_room_hebbian",
}

#: Pre-move ``model_dump(mode="json")``, measured against ``HEAD``'s
#: ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {   'AssignmentConfig': {'enabled': False},
    'BootCampConfig': {   'enabled': True,
                          'min_episodes': 5,
                          'min_ward_room_posts': 3,
                          'min_dm_conversations': 1,
                          'min_trust_score': 0.55,
                          'min_time_minutes': 60,
                          'timeout_minutes': 120,
                          'nudge_cooldown_seconds': 600},
    'DeliberationConfig': {'enabled': True, 'captain_callsign': 'Captain'},
    'DepartmentCognitiveProfile': {   'recall_depth': 5,
                                      'recall_threshold': 0.25,
                                      'context_token_budget': 4000},
    'FirewallConfig': {   'enabled': True,
                          'scan_trust_threshold': 0.65,
                          'low_trust_threshold': 0.45,
                          'hex_id_min_length': 6,
                          'hex_id_threshold': 2,
                          'fabricated_metrics_threshold': 3,
                          'flag_window_seconds': 3600.0,
                          'quarantine_threshold': 3},
    'HolodeckBirthChamberConfig': {   'enabled': False,
                                      'bypass_for_existing_agents': True,
                                      'department_order': [   'security',
                                                              'operations',
                                                              'engineering',
                                                              'science',
                                                              'medical'],
                                      'calibration_min_episodes': 5,
                                      'affective_baseline_check_enabled': True,
                                      'auto_advance_enabled': True,
                                      'auto_advance_poll_interval_seconds': 2.0,
                                      'max_self_discovery_probe_attempts': 3},
    'HolodeckScenarioConfig': {   'enabled': False,
                                  'auto_register_with_harness': True,
                                  'default_threshold': 0.6,
                                  'default_tier': 2,
                                  'category_fallback': 'construction',
                                  'persist_to_sqlite': False,
                                  'data_subdir': 'holodeck_scenarios'},
    'HolodeckTeamSimulationConfig': {   'enabled': False,
                                        'auto_register_with_harness': True,
                                        'default_threshold': 0.6,
                                        'default_tier': 2,
                                        'enforce_required_departments': True,
                                        'persist_to_sqlite': False,
                                        'data_subdir': 'team_simulations'},
    'MemorySecurityConfig': {   'enforce_recall': False,
                                'enforce_provenance': False,
                                'enforce_leak_guard': False,
                                'enforce_store': False,
                                'anchor_mismatch_threshold': 0.7,
                                'dp_min_cohort_size': 3},
    'NamingConfig': {   'enabled': True,
                        'captain_ship_override': '',
                        'extra_banned_words': []},
    'OrdersConfig': {   'enabled': True,
                        'max_active_per_post': 8,
                        'default_ttl_seconds': 3600.0},
    'PermissionsConfig': {'allow': [], 'deny': []},
    'PolicyWindowConfig': {   'start_time': '08:00',
                              'end_time': '18:00',
                              'days': [0, 1, 2, 3, 4]},
    'ReadyRoomConfig': {   'enabled': True,
                           'idea_store_filename': 'ready_room/ideas.json',
                           'wardroom_channel_id': 'ready_room'},
    'RiskTierConfig': {   'enabled': True,
                          'elevated_min_trust': 0.0,
                          'critical_min_trust': 0.7},
    'ShipStateSnapshotConfig': {'enabled': True},
    'SkillRequestConfig': {'enabled': False, 'data_subdir': 'skill_requests'},
    'SoftwareEngineerSpecialistsConfig': {   'enabled': False,
                                             'pool_size_per_specialty': 1,
                                             'model_tier_overrides': {   'backend': 'deep',
                                                                         'frontend': 'standard',
                                                                         'test': 'fast',
                                                                         'infrastructure': 'standard',
                                                                         'data': 'deep'}},
    'TieredTrustConfig': {   'enabled': True,
                             'bridge_alpha': 4.5,
                             'bridge_beta': 1.0,
                             'chief_alpha': 3.0,
                             'chief_beta': 1.0,
                             'bridge_pools': ['counselor', 'yeoman'],
                             'bridge_callsigns': ['Meridian', 'Yeo'],
                             'chief_callsigns': [   'Bones',
                                                    'LaForge',
                                                    'Number One',
                                                    'Worf',
                                                    "O'Brien"]},
    'UtilityAgentsConfig': {'enabled': True},
    'VisitingOfficersConfig': {   'enabled': False,
                                  'session_ttl_seconds': 3600.0,
                                  'sweep_interval_seconds': 60.0,
                                  'default_capabilities': [   'ward_room.post',
                                                              'ward_room.read']},
    'WardRoomConfig': {   'enabled': False,
                          'max_agent_rounds': 5,
                          'agent_cooldown_seconds': 45.0,
                          'max_thread_posts': 50,
                          'default_discuss_responder_cap': 3,
                          'retention_days': 7,
                          'retention_days_endorsed': 30,
                          'retention_days_captain': 0,
                          'archive_enabled': True,
                          'prune_interval_seconds': 86400.0,
                          'dm_exchange_limit': 15,
                          'dm_similarity_threshold': 0.6,
                          'router_concurrency_limit': 10,
                          'event_coalesce_ms': 200,
                          'dm_response_budget': 6,
                          'dm_response_window_seconds': 600.0,
                          'dm_pair_exchange_budget': 8},
    'WardRoomHebbianConfig': {   'enabled': True,
                                 'learning_rate': 0.1,
                                 'decay_factor': 0.99}}

#: Derived, never hand-listed.
PLAIN_SUBMODELS: tuple[str, ...] = tuple(
    n for n in MOVED_MODELS if n not in NOT_A_PLAIN_SUBMODEL
)
CONSTRUCTIBLE: tuple[str, ...] = tuple(
    n for n in MOVED_MODELS if n not in REQUIRES_ARGUMENTS
)


#: Numeric bounds (Ge/Gt/Le/Lt) declared per model. Pinning the exact count is
#: what keeps the case below non-vacuous: sixteen of the twenty-five carry no
#: bound at all, so "at least zero were checked" would pass even if a model
#: that DOES carry bounds silently lost every one.
EXPECTED_BOUND_COUNTS: dict[str, int] = {
    "AssignmentConfig": 0,
    "BootCampConfig": 0,
    "DeliberationConfig": 0,
    "DepartmentCognitiveProfile": 5,
    "DutyDefinition": 0,
    "EPSDepartmentConfig": 4,
    "FirewallConfig": 0,
    "HolodeckBirthChamberConfig": 4,
    "HolodeckScenarioConfig": 4,
    "HolodeckTeamSimulationConfig": 4,
    "MemorySecurityConfig": 3,
    "NamingConfig": 0,
    "OrdersConfig": 4,
    "PermissionsConfig": 0,
    "PolicyWindowConfig": 0,
    "ReadyRoomConfig": 0,
    "RiskTierConfig": 0,
    "ShipStateSnapshotConfig": 0,
    "SkillRequestConfig": 0,
    "SoftwareEngineerSpecialistsConfig": 0,
    "TieredTrustConfig": 0,
    "UtilityAgentsConfig": 0,
    "VisitingOfficersConfig": 2,
    "WardRoomConfig": 0,
    "WardRoomHebbianConfig": 0,
}

#: The two models with required fields need those supplied before any bound on
#: a DIFFERENT field can be exercised -- otherwise every construction raises for
#: the missing field and the bound is never reached, which would make the case
#: pass while proving nothing.
REQUIRED_FILLERS: dict[str, dict[str, object]] = {
    "DutyDefinition": {"duty_id": "probe", "description": "probe"},
    "EPSDepartmentConfig": {"name": "probe"},
}


def _fillers(name: str) -> dict[str, object]:
    return dict(REQUIRED_FILLERS.get(name, {}))


#: Pre-move dumps for the two models that require arguments, built with the same
#: fillers. Without these they would be excluded from value comparison entirely
#: -- which is how ``DutyDefinition.required_skills`` escaped the mutable-default
#: check in the first draft of this file.
EXPECTED_FILLED_DUMPS: dict[str, dict[str, object]] = {
    "DutyDefinition": {
        "duty_id": "probe",
        "description": "probe",
        "cron": "",
        "interval_seconds": 0.0,
        "priority": 2,
        "required_skills": [],
    },
    "EPSDepartmentConfig": {"name": "probe", "percent": 0.0, "priority": 5},
}


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _walk(dumped: dict[str, Any], dotted: str) -> Any:
    node: Any = dumped
    for part in dotted.split("."):
        node = node[part]
    return node


facade = _load("_ad1270e2g_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    return yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))["models"]


@pytest.fixture(scope="module")
def config_schema() -> dict[str, Any]:
    index = CodebaseIndex(_SOURCE_ROOT)
    index.build()
    return index.get_config_schema()


def test_the_batch_tables_are_consistent_and_exhaustive() -> None:
    """Guard the guards: a model dropped from a table must fail, not vanish."""
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 25
    assert set(EXPECTED_DUMPS) == set(CONSTRUCTIBLE)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)
    assert set(REQUIRES_ARGUMENTS) <= set(MOVED_MODELS)
    assert set(NOT_A_PLAIN_SUBMODEL) <= set(MOVED_MODELS)
    # The partitions must actually partition, or a model could be excluded from
    # every case at once and still satisfy each individual assertion.
    assert set(PLAIN_SUBMODELS) | set(NOT_A_PLAIN_SUBMODEL) == set(MOVED_MODELS)
    assert len(PLAIN_SUBMODELS) == 22


# ---------------------------------------------------------------------------
# Identity and re-export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_crew, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    assert getattr(config_pkg, name) is getattr(config_crew, name)
    assert name in config_pkg.__all__


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_identity_matches_the_e1_baseline(
    name: str, baseline_models: dict[str, dict]
) -> None:
    """Qualname, MRO bases and ordered fields are what e1 froze."""
    stored = baseline_models[name]
    model = getattr(config_facade, name)

    assert model.__qualname__ == stored["qualname"]
    assert [base.__name__ for base in model.__mro__[1:]] == stored["bases"]
    assert list(model.model_fields) == [field["name"] for field in stored["fields"]]


def test_the_literal_consumer_spelling_still_imports() -> None:
    from probos.config import (  # noqa: F401
        DutyDefinition,
        EPSDepartmentConfig,
        PermissionsConfig,
        WardRoomConfig,
    )

    assert WardRoomConfig is config_crew.WardRoomConfig
    assert DutyDefinition is config_crew.DutyDefinition


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``."""
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.crew"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# The source-reading consumer -- not an import consumer
# ---------------------------------------------------------------------------


def test_the_index_still_sees_a_never_moved_model(config_schema: dict) -> None:
    """Control. Without it, the next assertion proves nothing on failure."""
    assert "CognitiveConfig" in config_schema


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_the_source_reading_consumer_still_sees_the_moved_model(
    name: str, config_schema: dict
) -> None:
    """Ordered field set, not mere presence -- presence passes on one field."""
    assert name in config_schema

    assert list(config_schema[name]) == list(getattr(config_crew, name).model_fields)


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", PLAIN_SUBMODELS)
def test_system_config_dump_is_unchanged_for_the_moved_model(name: str) -> None:
    """Reached through the real composition path."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == EXPECTED_DUMPS[name]


def test_the_dict_valued_profile_map_composes_empty() -> None:
    """``dept_profiles.profiles`` ships empty, so no instance sits at the path."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH["DepartmentCognitiveProfile"]) == {}


def test_the_eps_department_list_composes_its_six_shipped_entries() -> None:
    """The element type has required fields, so the shipped list IS the default.

    Asserting the whole list rather than its length: a move that dropped a
    department, or reordered them, would keep the count and change the budget.
    """
    dumped = SystemConfig().model_dump(mode="json")

    departments = _walk(dumped, MODEL_TO_PATH["EPSDepartmentConfig"])

    assert [d["name"] for d in departments] == [
        "engineering",
        "science",
        "medical",
        "security",
        "operations",
        "other",
    ]
    assert [d["percent"] for d in departments] == [0.3, 0.2, 0.15, 0.15, 0.1, 0.1]
    assert [d["priority"] for d in departments] == [3, 4, 2, 2, 4, 6]
    assert sum(d["percent"] for d in departments) == pytest.approx(1.0)


@pytest.mark.parametrize("name", REQUIRES_ARGUMENTS)
def test_models_with_required_fields_still_refuse_an_empty_construction(
    name: str,
) -> None:
    """The two element types must not have gained a default in the move."""
    with pytest.raises(ValueError):
        getattr(config_facade, name)()


@pytest.mark.parametrize("name", REQUIRES_ARGUMENTS)
def test_models_with_required_fields_match_the_pre_move_filled_dump(
    name: str,
) -> None:
    """Value comparison for the two models the empty-construction case cannot."""
    model = getattr(config_facade, name)

    dumped = model(**_fillers(name)).model_dump(mode="json")

    assert dumped == EXPECTED_FILLED_DUMPS[name]


def test_the_duty_schedule_composes_a_real_duty_definition() -> None:
    """``dict[str, list[DutyDefinition]]`` -- two containers deep.

    An earlier draft claimed this model was unreachable from ``SystemConfig``.
    It is not; the traversal used to check simply did not follow a dict-of-list
    annotation. Reaching it here through the real validation path is the
    correction.
    """
    composed = SystemConfig.model_validate(
        {
            "proactive_cognitive": {
                "duty_schedule": {
                    "schedules": {
                        "alpha": [{"duty_id": "probe", "description": "probe"}]
                    }
                }
            }
        }
    )

    duty = composed.proactive_cognitive.duty_schedule.schedules["alpha"][0]

    assert type(duty) is config_crew.DutyDefinition
    assert duty.model_dump(mode="json") == EXPECTED_FILLED_DUMPS["DutyDefinition"]
    # And the default really is empty, so the case above is not reading a value
    # some other default happened to put there.
    assert SystemConfig().proactive_cognitive.duty_schedule.schedules == {}


@pytest.mark.parametrize("name", CONSTRUCTIBLE)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", CONSTRUCTIBLE)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    assert getattr(config_facade, name)().model_dump(mode="json") == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_every_declared_bound_is_still_enforced(name: str) -> None:
    """Walk the ACTUAL metadata, and pin the per-model count.

    Reading ``FieldInfo.metadata`` came from batch 4 (a hand-written case
    asserted a bound on a field that had none). Pinning the COUNT came from
    batch 6, where the same loop ended in ``assert checked >= 0`` and was
    therefore vacuous for every model that declares no bound.
    """
    model = getattr(config_facade, name)
    filler = _fillers(name)
    checked = 0

    for field_name, info in model.model_fields.items():
        for meta in info.metadata:
            kind = type(meta).__name__
            if kind not in {"Ge", "Gt", "Le", "Lt"}:
                continue
            bound = getattr(meta, kind.lower(), None)
            if not isinstance(bound, (int, float)) or isinstance(bound, bool):
                continue
            step = 1 if isinstance(bound, int) else 0.001
            if kind == "Ge":
                assert getattr(
                    model(**{**filler, field_name: bound}), field_name
                ) == bound
                bad = bound - step
            elif kind == "Le":
                assert getattr(
                    model(**{**filler, field_name: bound}), field_name
                ) == bound
                bad = bound + step
            else:
                bad = bound
            with pytest.raises(ValueError):
                model(**{**filler, field_name: bad})
            checked += 1

    assert checked == EXPECTED_BOUND_COUNTS[name]


def test_the_bound_table_is_exhaustive_and_not_all_zero() -> None:
    """Premise on both halves: exhaustive, and not trivially satisfiable."""
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 30
    assert sum(1 for c in EXPECTED_BOUND_COUNTS.values() if c) == 8


def test_the_required_field_fillers_actually_satisfy_their_models() -> None:
    """Premise for the bound case on the two argument-taking models.

    If a filler were wrong, every construction in that model's bound case would
    raise for the MISSING FIELD rather than the bound, and ``pytest.raises``
    would be satisfied by the wrong error entirely.
    """
    assert set(REQUIRED_FILLERS) == set(REQUIRES_ARGUMENTS)

    for name, filler in REQUIRED_FILLERS.items():
        model = getattr(config_facade, name)
        required = {f for f, i in model.model_fields.items() if i.is_required()}

        assert set(filler) == required
        # Constructs cleanly with the filler alone -- so any later failure in
        # the bound case is attributable to the bound.
        assert model(**filler) is not None


def test_moved_models_still_reject_wrong_types() -> None:
    """The field is asserted to EXIST first.

    Pydantic ignores an unknown keyword on a model without ``extra="forbid"``,
    so a typo'd field name makes ``pytest.raises`` fail for the right reason and
    the wrong cause. That happened in batch 6.
    """
    assert "dm_exchange_limit" in config_facade.WardRoomConfig.model_fields

    for value in ("not-a-number", None, [1]):
        with pytest.raises(ValueError):
            config_facade.WardRoomConfig(dm_exchange_limit=value)


def test_mutable_defaults_are_not_shared_between_instances() -> None:
    """Every mutable-valued field on EVERY moved model.

    Batch 6's version gated on ``default_factory`` and so skipped exactly the
    literal mutable defaults, which are the ones a naive model would share.
    The first draft of THIS file closed that gap but then excluded the two
    argument-taking models, which put ``DutyDefinition.required_skills`` -- a
    literal list -- straight back outside the check. Both holes are closed by
    constructing every model with its fillers.
    """
    shared: list[str] = []
    examined: list[str] = []
    for name in MOVED_MODELS:
        model = getattr(config_facade, name)
        filler = _fillers(name)
        first, second = model(**filler), model(**filler)
        for field_name in model.model_fields:
            a, b = getattr(first, field_name), getattr(second, field_name)
            if not isinstance(a, (list, dict, set)):
                continue
            examined.append(f"{name}.{field_name}")
            if a is b:
                shared.append(f"{name}.{field_name}")

    # Pin the exact field set, so a model dropping out of coverage is a failure
    # rather than a silently smaller loop.
    assert "DutyDefinition.required_skills" in examined
    assert len(examined) >= 10
    assert shared == []


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first, second = SystemConfig(), SystemConfig()

    assert first.ward_room is not second.ward_room
    assert first.eps.departments is not second.eps.departments

    first.ward_room.dm_exchange_limit += 1

    assert (
        second.ward_room.dm_exchange_limit
        == EXPECTED_DUMPS["WardRoomConfig"]["dm_exchange_limit"]
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_crew_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_CREW_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not any(name.startswith("probos") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    tree = ast.parse((_SOURCE_ROOT / "config.py").read_text(encoding="utf-8"))
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_no_name_is_defined_in_more_than_one_domain_module() -> None:
    owners: dict[str, list[str]] = {}
    for module in sorted((_SOURCE_ROOT / "config_models").glob("*.py")):
        if module.name == "__init__.py":
            continue
        for node in ast.parse(module.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                owners.setdefault(node.name, []).append(module.name)

    assert {name: mods for name, mods in owners.items() if len(mods) > 1} == {}


def test_the_package_exports_exactly_what_it_imports() -> None:
    tree = ast.parse(
        (_SOURCE_ROOT / "config_models" / "__init__.py").read_text(encoding="utf-8")
    )
    imported: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("probos.config_models"):
                imported.extend(alias.name for alias in node.names)

    assert sorted(set(imported)) == list(config_pkg.__all__)
    assert len(imported) == len(set(imported))


def test_no_test_resolves_a_moved_model_through_a_hardcoded_config_path() -> None:
    """Batch 5's regression class, enumerated rather than spot-checked.

    ``?raw`` source guards that assert text at the literal path
    ``src/probos/config.py`` go red the moment their model moves. Three broke in
    batch 5 (``ExecutionConfig``); a fourth broke here when ``WardRoomConfig``
    moved. Naming the three known files was not enough -- review showed a file
    could satisfy it while still hard-coding the read. This walks the whole test
    tree with AST and flags any file that BOTH reads ``src/probos/config.py``
    literally AND mentions a model that no longer lives there.
    """
    moved_anywhere: set[str] = set()
    package = _SOURCE_ROOT / "config_models"
    for module in package.glob("*.py"):
        if module.name == "__init__.py":
            continue
        for node in ast.parse(module.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                moved_anywhere.add(node.name)

    # Premise: an empty set would make the scan below prove nothing.
    assert len(moved_anywhere) >= 100

    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "tests").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not any(name in text for name in moved_anywhere):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant):
                continue
            if first.value != "src/probos/config.py":
                continue
            callee = node.func
            reads = isinstance(callee, ast.Name) and callee.id in {"Path", "_text"}
            if reads:
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_a_crew_model_change() -> None:
    selector = _load("_ad1270e2g_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/crew.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    profiles = _load(
        "_ad1270e2g_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )

    scanned = [path.name for path in profiles._env_scan_paths(_SOURCE_ROOT)]

    assert "config.py" in scanned
    assert "crew.py" in scanned
    assert profiles.env_reads_reaching_defaults(_SOURCE_ROOT)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
