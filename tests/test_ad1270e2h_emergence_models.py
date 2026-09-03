"""AD-1270e2 batch 8 -- the ``emergence`` batch preserved every public value.

Twenty-seven leaf models -- the emergence collector/detector/metrics trio and
emergent leadership, the novelty gate and earned agency, behavioural metrics and
the cognitive journal, medical/counselor/clinical telemetry, trait adaptation
and trust dampening, ground truth and infodynamics, learned shortcuts, thread
priority, the procedural bridge and bridge alerts, agent tiers, the query
planner, runtime overrides, persistent tasks, the process-chain registry, the
workflow cron trigger and the two proactive-scan surfaces -- now live in
``probos.config_models.emergence`` and are re-exported from ``probos.config``.

What is preserved is the PUBLIC FACADE and every value behind it: same class
object, same qualname, same MRO, same ordered fields, same dumped defaults.
What deliberately CHANGES is the declaration site -- ``config.py`` loses 406
lines and each model's ``__module__`` becomes
``probos.config_models.emergence``. That relocation is observable and is
asserted on purpose.

``EXPECTED_DUMPS`` was CAPTURED AT AUTHORING TIME from
``git show HEAD:src/probos/config.py`` -- the class text *before* the move,
compiled in a throwaway module and evaluated on its own. It is a static literal
from here on: nothing in this file regenerates it at run time, and that is
deliberate, because after this commit lands ``HEAD`` no longer contains the
pre-move text. Had it been derived from the moved module it would compare the
code against itself and pass for any value.

Two consumer classes learned the hard way earlier in this wave are asserted
here rather than assumed: ``CodebaseIndex`` reads config models as SOURCE TEXT
(batch 4), and several ``?raw`` guards resolved ``config.py`` by literal path
(batches 5 and 7).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, get_origin

import pytest
import yaml

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.emergence as config_emergence
from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_SOURCE_ROOT = _REPO_ROOT / "src" / "probos"
_EMERGENCE_SOURCE = _SOURCE_ROOT / "config_models" / "emergence.py"

MOVED_MODELS: tuple[str, ...] = (
    "AgentTierConfig",
    "BehavioralMetricsConfig",
    "BridgeAlertConfig",
    "BridgeConfig",
    "ClinicalTelemetryConfig",
    "CognitiveJournalConfig",
    "CounselorConfig",
    "EarnedAgencyConfig",
    "EmergenceCollectorConfig",
    "EmergenceMetricsConfig",
    "EmergentDetectorConfig",
    "EmergentLeadershipConfig",
    "GroundTruthConfig",
    "InfodynamicConfig",
    "LearnedShortcutsConfig",
    "MedicalConfig",
    "NoveltyGateConfig",
    "PersistentTasksConfig",
    "ProactiveScanCalendarConfig",
    "ProactiveScanInboxConfig",
    "ProcessChainRegistryConfig",
    "QueryPlannerConfig",
    "RuntimeOverridesConfig",
    "ThreadPriorityConfig",
    "TraitAdaptiveConfig",
    "TrustDampeningConfig",
    "WorkflowCronTriggerConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``. Every one of the
#: twenty-seven is a plain submodel this batch, so all are dump-checked.
MODEL_TO_PATH: dict[str, str] = {
    "AgentTierConfig": "agent_tiers",
    "BehavioralMetricsConfig": "behavioral_metrics",
    "BridgeAlertConfig": "bridge_alerts",
    "BridgeConfig": "procedural_bridge",
    "ClinicalTelemetryConfig": "clinical_telemetry",
    "CognitiveJournalConfig": "cognitive_journal",
    "CounselorConfig": "counselor",
    "EarnedAgencyConfig": "earned_agency",
    "EmergenceCollectorConfig": "emergence_collector",
    "EmergenceMetricsConfig": "emergence_metrics",
    "EmergentDetectorConfig": "emergent_detector",
    "EmergentLeadershipConfig": "emergent_leadership",
    "GroundTruthConfig": "ground_truth",
    "InfodynamicConfig": "infodynamic",
    "LearnedShortcutsConfig": "learned_shortcuts",
    "MedicalConfig": "medical",
    "NoveltyGateConfig": "novelty_gate",
    "PersistentTasksConfig": "persistent_tasks",
    "ProactiveScanCalendarConfig": "proactive_scan.calendar",
    "ProactiveScanInboxConfig": "proactive_scan.inbox",
    "ProcessChainRegistryConfig": "process_chain_registry",
    "QueryPlannerConfig": "query_planner",
    "RuntimeOverridesConfig": "runtime_overrides",
    "ThreadPriorityConfig": "thread_priority",
    "TraitAdaptiveConfig": "trait_adaptive",
    "TrustDampeningConfig": "trust_dampening",
    "WorkflowCronTriggerConfig": "workflow_cron",
}

#: Numeric bounds (Ge/Gt/Le/Lt) declared per model. Pinning the exact count is
#: what keeps the case below non-vacuous: twenty-one of the twenty-seven carry
#: no bound at all, so "at least zero were checked" would pass even if a model
#: that DOES carry bounds silently lost every one.
EXPECTED_BOUND_COUNTS: dict[str, int] = {
    "AgentTierConfig": 0,
    "BehavioralMetricsConfig": 0,
    "BridgeAlertConfig": 0,
    "BridgeConfig": 0,
    "ClinicalTelemetryConfig": 0,
    "CognitiveJournalConfig": 0,
    "CounselorConfig": 0,
    "EarnedAgencyConfig": 0,
    "EmergenceCollectorConfig": 7,
    "EmergenceMetricsConfig": 0,
    "EmergentDetectorConfig": 0,
    "EmergentLeadershipConfig": 0,
    "GroundTruthConfig": 5,
    "InfodynamicConfig": 3,
    "LearnedShortcutsConfig": 0,
    "MedicalConfig": 0,
    "NoveltyGateConfig": 0,
    "PersistentTasksConfig": 0,
    "ProactiveScanCalendarConfig": 2,
    "ProactiveScanInboxConfig": 2,
    "ProcessChainRegistryConfig": 0,
    "QueryPlannerConfig": 0,
    "RuntimeOverridesConfig": 0,
    "ThreadPriorityConfig": 0,
    "TraitAdaptiveConfig": 0,
    "TrustDampeningConfig": 0,
    "WorkflowCronTriggerConfig": 1,
}

#: Pre-move ``model_dump(mode="json")``, measured against ``HEAD``'s
#: ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {   'AgentTierConfig': {   'crew_types': [   'architect',
                                             'builder',
                                             'code_reviewer',
                                             'counselor',
                                             'diagnostician',
                                             'surgeon',
                                             'pharmacist',
                                             'pathologist',
                                             'red_team',
                                             'system_qa',
                                             'scout',
                                             'data_analyst',
                                             'systems_analyst',
                                             'research_specialist'],
                           'core_types': [   'event_log',
                                             'vitals_monitor',
                                             'introspect']},
    'BehavioralMetricsConfig': {   'thread_lookback_hours': 72.0,
                                   'min_thread_contributors': 2,
                                   'min_thread_posts': 3,
                                   'frame_diversity_min_departments': 2,
                                   'synthesis_novelty_threshold': 0.35,
                                   'synthesis_min_thread_posts': 4,
                                   'trigger_correlation_window_hours': 24.0,
                                   'trigger_topic_similarity_threshold': 0.6,
                                   'convergence_similarity_threshold': 0.75,
                                   'convergence_min_agreeing': 2,
                                   'anchor_independence_min_episodes': 3,
                                   'max_snapshots': 100},
    'BridgeAlertConfig': {   'enabled': False,
                             'cooldown_seconds': 300.0,
                             'trust_drop_threshold': 0.15,
                             'trust_drop_alert_threshold': 0.25,
                             'resolve_clean_period': 3600.0,
                             'default_dismiss_duration': 14400.0},
    'BridgeConfig': {   'enabled': True,
                        'min_cross_cycle_episodes': 5,
                        'novelty_threshold': 0.3},
    'ClinicalTelemetryConfig': {   'enabled': False,
                                   'audit_max_entries': 1000,
                                   'audit_persistence_enabled': False,
                                   'audit_db_path': 'data/clinical_audit.db',
                                   'circuit_breaker_history_persistence_enabled': False,
                                   'circuit_breaker_history_db_path': 'data/circuit_breaker_history.db'},
    'CognitiveJournalConfig': {   'enabled': True,
                                  'retention_days': 14,
                                  'max_rows': 500000,
                                  'prune_interval_seconds': 3600.0},
    'CounselorConfig': {   'enabled': True,
                           'profile_retention_days': 90,
                           'trust_delta_threshold': 0.15,
                           'sweep_max_agents': 50,
                           'alert_on_red': True,
                           'alert_on_yellow': False},
    'EarnedAgencyConfig': {   'enabled': False,
                              'initiative_trust_thresholds': {   'responsive': 0.3,
                                                                 'contributory': 0.5,
                                                                 'proactive': 0.7}},
    'EmergenceCollectorConfig': {   'enabled': False,
                                    'confidence_threshold': 0.7,
                                    'dedup_window_seconds': 600.0,
                                    'output_dir': 'data/research/emergence-evidence',
                                    'llm_tier': 'fast',
                                    'trial_id': 'default',
                                    'thread_context_limit': 5,
                                    'max_reasoning_chars': 2000},
    'EmergenceMetricsConfig': {   'pid_bins': 2,
                                  'pid_permutation_shuffles': 50,
                                  'pid_significance_threshold': 0.05,
                                  'min_thread_contributors': 2,
                                  'min_thread_posts': 3,
                                  'thread_lookback_hours': 24.0,
                                  'groupthink_redundancy_threshold': 0.8,
                                  'fragmentation_synergy_threshold': 0.1,
                                  'tom_baseline_window': 20,
                                  'tom_trend_min_samples': 10,
                                  'hebbian_synergy_min_interactions': 5},
    'EmergentDetectorConfig': {   'cluster_edge_threshold': 0.3,
                                  'cluster_min_size': 3,
                                  'cluster_min_avg_weight': 0.25,
                                  'cluster_cooldown_seconds': 1800.0,
                                  'cluster_activity_window': 900.0,
                                  'dream_min_history': 5,
                                  'dream_anomaly_min_strengthened': 10,
                                  'dream_anomaly_min_pruned': 5,
                                  'dream_anomaly_min_trust_adj': 10,
                                  'adaptive_window_size': 30,
                                  'adaptive_z_threshold': 2.5,
                                  'adaptive_debounce_count': 2,
                                  'adaptive_min_history': 8},
    'EmergentLeadershipConfig': {   'enabled': True,
                                    'min_weight': 0.1,
                                    'min_ratio': 1.5},
    'GroundTruthConfig': {   'enabled': True,
                             'threshold': 0.75,
                             'event_window_seconds': 600.0,
                             'write_episode': True,
                             'active_rejection_enabled': False,
                             'quarantine_metadata_key': 'ground_truth_quarantine',
                             'trust_feedback_enabled': False,
                             'trust_feedback_success_weight': 1.0,
                             'trust_feedback_failure_weight': 0.5},
    'InfodynamicConfig': {   'enabled': True,
                             'event_window_seconds': 3600.0,
                             'trust_buckets': 10},
    'LearnedShortcutsConfig': {'enabled': True, 'register_workflow_cache': True},
    'MedicalConfig': {   'enabled': True,
                         'vitals_interval_seconds': 5.0,
                         'vitals_window_size': 12,
                         'pool_health_min': 0.5,
                         'trust_floor': 0.3,
                         'health_floor': 0.6,
                         'max_trust_outliers': 3,
                         'scheduled_diagnosis_interval': 300.0},
    'NoveltyGateConfig': {   'enabled': True,
                             'similarity_threshold': 0.82,
                             'max_fingerprints_per_agent': 50,
                             'decay_hours': 24.0,
                             'min_text_length': 80},
    'PersistentTasksConfig': {   'enabled': False,
                                 'tick_interval_seconds': 5.0,
                                 'max_concurrent_executions': 1,
                                 'dag_auto_resume': False},
    'ProactiveScanCalendarConfig': {   'calendar_ids': ['primary'],
                                       'lookahead_hours': 24,
                                       'include_declined': False},
    'ProactiveScanInboxConfig': {   'folders': ['Inbox'],
                                    'lookback_hours': 24,
                                    'importance_filter': 'any',
                                    'unread_only': False,
                                    'sender_allowlist': [],
                                    'sender_denylist': []},
    'ProcessChainRegistryConfig': {'enabled': True},
    'QueryPlannerConfig': {'enabled': False, 'fall_through_on_empty': True},
    'RuntimeOverridesConfig': {   'enabled': True,
                                  'store_filename': 'runtime_overrides.json'},
    'ThreadPriorityConfig': {   'enabled': True,
                                'weight_captain': 0.3,
                                'weight_unresolved': 0.2,
                                'weight_cross_department': 0.15,
                                'weight_recency': 0.2,
                                'weight_endorsement': 0.15,
                                'captain_callsign': 'Captain'},
    'TraitAdaptiveConfig': {'enabled': True},
    'TrustDampeningConfig': {   'dampening_window_seconds': 300.0,
                                'dampening_geometric_factors': [   1.0,
                                                                   0.75,
                                                                   0.5,
                                                                   0.25],
                                'dampening_floor': 0.25,
                                'hard_trust_floor': 0.05,
                                'cascade_agent_threshold': 3,
                                'cascade_department_threshold': 2,
                                'cascade_delta_threshold': 0.15,
                                'cascade_window_seconds': 300.0,
                                'cascade_global_dampening': 0.5,
                                'cascade_cooldown_seconds': 600.0,
                                'cold_start_observation_threshold': 20.0,
                                'cold_start_dampening_floor': 0.5},
    'WorkflowCronTriggerConfig': {   'enabled': False,
                                     'db_path': '',
                                     'tick_interval_seconds': 1.0,
                                     'initial_triggers': []}}


#: Every field in this batch whose default value is a list/dict/set. Pinned
#: exactly rather than counted with ``>=``, so losing coverage of one is a
#: failure instead of a quietly smaller loop.
EXPECTED_MUTABLE_FIELDS: tuple[str, ...] = (
    "AgentTierConfig.core_types",
    "AgentTierConfig.crew_types",
    "EarnedAgencyConfig.initiative_trust_thresholds",
    "ProactiveScanCalendarConfig.calendar_ids",
    "ProactiveScanInboxConfig.folders",
    "ProactiveScanInboxConfig.sender_allowlist",
    "ProactiveScanInboxConfig.sender_denylist",
    "WorkflowCronTriggerConfig.initial_triggers",
)


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


def _first_mutable_free_field(name: str, section: dict[str, Any]) -> tuple[str, Any]:
    """Pick a field with no declared bound, so perturbing it stays valid.

    Bounded fields are excluded because a perturbation could land outside the
    constraint and make the round-trip fail for a reason that has nothing to do
    with YAML. ``Literal`` fields are excluded for the same reason -- any string
    perturbation leaves the allowed set. Bools and strings are preferred;
    numbers and string lists are the fallback for models that declare neither.
    """
    model = getattr(config_facade, name)
    fallback: tuple[str, Any] | None = None
    for field_name, info in model.model_fields.items():
        if field_name not in section:
            continue
        if any(
            type(meta).__name__ in {"Ge", "Gt", "Le", "Lt"} for meta in info.metadata
        ):
            continue
        if get_origin(info.annotation) is Literal:
            continue
        value = section[field_name]
        if isinstance(value, bool) or isinstance(value, str):
            return field_name, value
        if fallback is None and isinstance(value, (int, float)):
            fallback = (field_name, value)
        if fallback is None and isinstance(value, list):
            if all(isinstance(item, str) for item in value):
                fallback = (field_name, value)
    if fallback is not None:
        return fallback
    raise AssertionError(f"no perturbable unbounded field on {name}")


def _perturb(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, str):
        return f"{value}-probe"
    if isinstance(value, list):
        return [*value, "probe"]
    return value + 1


facade = _load("_ad1270e2h_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


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
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 27
    assert set(EXPECTED_DUMPS) == set(MOVED_MODELS)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)


def test_every_moved_model_constructs_without_arguments() -> None:
    """Premise for the dump cases: none of this batch requires a filler.

    Batch 7 had two models that did, and forgetting them silently removed a
    literal mutable default from the shared-default check. Asserting the
    property here means a future batch cannot inherit that assumption.
    """
    for name in MOVED_MODELS:
        assert getattr(config_facade, name)() is not None


# ---------------------------------------------------------------------------
# Identity and re-export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_emergence, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    assert getattr(config_pkg, name) is getattr(config_emergence, name)
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
        AgentTierConfig,
        CounselorConfig,
        EmergentDetectorConfig,
        MedicalConfig,
        WorkflowCronTriggerConfig,
    )

    assert AgentTierConfig is config_emergence.AgentTierConfig
    assert WorkflowCronTriggerConfig is config_emergence.WorkflowCronTriggerConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``."""
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.emergence"
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

    assert list(config_schema[name]) == list(
        getattr(config_emergence, name).model_fields
    )


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_system_config_dump_is_unchanged_for_the_moved_model(name: str) -> None:
    """Reached through the real composition path."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    assert getattr(config_facade, name)().model_dump(mode="json") == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_every_declared_bound_is_still_enforced(name: str) -> None:
    """Walk the ACTUAL metadata, and pin the per-model count.

    Reading ``FieldInfo.metadata`` came from batch 4 (a hand-written case
    asserted a bound on a field that had none). Pinning the COUNT came from
    batch 6, where the same loop ended in ``assert checked >= 0`` and so proved
    nothing for any model that declares no bound.
    """
    model = getattr(config_facade, name)
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
                assert getattr(model(**{field_name: bound}), field_name) == bound
                bad = bound - step
            elif kind == "Le":
                assert getattr(model(**{field_name: bound}), field_name) == bound
                bad = bound + step
            else:
                bad = bound
            with pytest.raises(ValueError):
                model(**{field_name: bad})
            checked += 1

    assert checked == EXPECTED_BOUND_COUNTS[name]


def test_the_bound_table_is_exhaustive_and_not_all_zero() -> None:
    """Premise on both halves: exhaustive, and not trivially satisfiable."""
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 20
    assert sorted(n for n, c in EXPECTED_BOUND_COUNTS.items() if c) == [
        "EmergenceCollectorConfig",
        "GroundTruthConfig",
        "InfodynamicConfig",
        "ProactiveScanCalendarConfig",
        "ProactiveScanInboxConfig",
        "WorkflowCronTriggerConfig",
    ]


def test_moved_models_still_reject_wrong_types() -> None:
    """The field is asserted to EXIST first.

    Pydantic ignores an unknown keyword on a model without ``extra="forbid"``,
    so a typo'd field name makes ``pytest.raises`` fail for the right reason and
    the wrong cause. That happened in batch 6.
    """
    assert "min_thread_contributors" in config_facade.EmergenceMetricsConfig.model_fields

    for value in ("not-a-number", None, [1]):
        with pytest.raises(ValueError):
            config_facade.EmergenceMetricsConfig(min_thread_contributors=value)


def test_mutable_defaults_are_not_shared_between_instances() -> None:
    """Every mutable-valued field on EVERY moved model.

    Batch 6 gated this on ``default_factory`` and so skipped literal mutable
    defaults; batch 7 then excluded the argument-taking models and put one back
    outside the check. Neither exclusion applies here, and the examined field
    set is pinned EXACTLY -- a ``>= n`` threshold would let coverage shrink
    silently, which is the same shape of weakness as the earlier two.
    """
    shared: list[str] = []
    examined: list[str] = []
    for name in MOVED_MODELS:
        model = getattr(config_facade, name)
        first, second = model(), model()
        for field_name in model.model_fields:
            a, b = getattr(first, field_name), getattr(second, field_name)
            if not isinstance(a, (list, dict, set)):
                continue
            examined.append(f"{name}.{field_name}")
            if a is b:
                shared.append(f"{name}.{field_name}")

    assert sorted(examined) == sorted(EXPECTED_MUTABLE_FIELDS)
    assert shared == []


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_a_non_default_value_survives_a_yaml_round_trip(name: str) -> None:
    """The config FILE path, not just in-process construction.

    Every other case here builds models directly. A move that broke YAML
    loading -- the way an operator actually supplies these values -- would pass
    all of them. This dumps a non-default value to YAML, reloads it through
    ``SystemConfig.model_validate``, and checks the section survived.
    """
    dotted = MODEL_TO_PATH[name]
    section = dict(_walk(SystemConfig().model_dump(mode="json"), dotted))

    field, original = _first_mutable_free_field(name, section)
    section[field] = _perturb(original)

    document: dict[str, Any] = {}
    node = document
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = section

    reloaded = SystemConfig.model_validate(yaml.safe_load(yaml.safe_dump(document)))

    assert _walk(reloaded.model_dump(mode="json"), dotted) == section
    # Premise: the perturbation must actually differ, or this proves nothing.
    assert section[field] != original


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first, second = SystemConfig(), SystemConfig()

    assert first.medical is not second.medical
    assert first.emergent_detector is not second.emergent_detector

    first.medical.enabled = not first.medical.enabled

    assert second.medical.enabled == EXPECTED_DUMPS["MedicalConfig"]["enabled"]


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_emergence_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_EMERGENCE_SOURCE.read_text(encoding="utf-8"))
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
    """``__all__`` drift is how a re-export silently stops being public."""
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


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_an_emergence_model_change() -> None:
    selector = _load("_ad1270e2h_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/emergence.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    profiles = _load(
        "_ad1270e2h_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )

    scanned = [path.name for path in profiles._env_scan_paths(_SOURCE_ROOT)]

    assert "config.py" in scanned
    assert "emergence.py" in scanned
    assert profiles.env_reads_reaching_defaults(_SOURCE_ROOT)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
