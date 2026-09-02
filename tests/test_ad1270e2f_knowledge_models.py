"""AD-1270e2 batch 6 -- the ``knowledge`` batch preserved every public value.

Twenty-three leaf models -- the knowledge store and its loading policy, records
and archive, the chain tuning/optimizer/counselor trio, causal reasoning and
diagnostic context, consultation and expertise, orientation and social
verification, source tracing, observable state, predictive branching, self
improvement, salience, task context, question adaptation, step instructions,
sub-tasks and the LLM rate limiter -- now live in
``probos.config_models.knowledge`` and are re-exported from ``probos.config``.

What is preserved is the PUBLIC FACADE and every value behind it: same class
object, same qualname, same MRO, same ordered fields, same dumped defaults.
What deliberately CHANGES is the declaration site -- ``config.py`` loses 491
lines and each model's ``__module__`` becomes ``probos.config_models.knowledge``.
That relocation is observable, and one case below asserts it on purpose rather
than pretending otherwise. A name-only check would pass a wrapper or a
re-declared copy, so the identity assertions compare ``is``.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` at
authoring time -- the class text *before* the move, compiled in a throwaway
module and evaluated on its own. Had it been derived from the moved module the
assertion would compare the code against itself and pass for any value.

Two consumer classes here are not about this batch at all, and both were
learned the hard way earlier in this wave:

* ``CodebaseIndex`` reads config models as *source text* rather than importing
  them, so the facade re-export did nothing for it and batches 1-3 shipped with
  their models missing from the system's own config self-knowledge.
* Several ``?raw`` source-contract guards read ``config.py`` as a literal path
  and went red in batch 5 the moment ``ExecutionConfig`` moved.

Both are asserted explicitly from here on.
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
import probos.config_models.knowledge as config_knowledge
from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_SOURCE_ROOT = _REPO_ROOT / "src" / "probos"
_KNOWLEDGE_SOURCE = _SOURCE_ROOT / "config_models" / "knowledge.py"

#: The batch, named once. Every parametrised case walks exactly these.
MOVED_MODELS: tuple[str, ...] = (
    "ArchiveConfig",
    "CausalReasoningConfig",
    "ChainOptimizerConfig",
    "ChainOptimizerCounselorConfig",
    "ChainTuningConfig",
    "ConsultationConfig",
    "DiagnosticContextConfig",
    "ExpertiseConfig",
    "KnowledgeConfig",
    "KnowledgeLoadingConfig",
    "LLMRateConfig",
    "ObservableStateConfig",
    "OrientationConfig",
    "PredictiveBranchingConfig",
    "QuestionAdaptiveConfig",
    "RecordsConfig",
    "SalienceConfig",
    "SelfImprovementConfig",
    "SocialVerificationConfig",
    "SourceTracingConfig",
    "StepInstructionConfig",
    "SubTaskConfig",
    "TaskContextConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``.
MODEL_TO_PATH: dict[str, str] = {
    "ArchiveConfig": "archive",
    "CausalReasoningConfig": "causal_reasoning",
    "ChainOptimizerConfig": "chain_optimizer",
    "ChainOptimizerCounselorConfig": "chain_optimizer_counselor",
    "ChainTuningConfig": "chain_tuning",
    "ConsultationConfig": "consultation",
    "DiagnosticContextConfig": "diagnostic_context",
    "ExpertiseConfig": "expertise",
    "KnowledgeConfig": "knowledge",
    "KnowledgeLoadingConfig": "knowledge_loading",
    "LLMRateConfig": "llm_rate",
    "ObservableStateConfig": "observable_state",
    "OrientationConfig": "orientation",
    "PredictiveBranchingConfig": "predictive_branching",
    "QuestionAdaptiveConfig": "question_adaptive",
    "RecordsConfig": "records",
    "SalienceConfig": "salience",
    "SelfImprovementConfig": "self_improvement",
    "SocialVerificationConfig": "social_verification",
    "SourceTracingConfig": "source_tracing",
    "StepInstructionConfig": "step_instruction",
    "SubTaskConfig": "sub_task",
    "TaskContextConfig": "task_context",
}

#: Pre-move ``model_dump(mode="json")``, measured against ``HEAD``'s
#: ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {   'ArchiveConfig': {'enabled': True, 'db_path': ''},
    'CausalReasoningConfig': {   'enabled': True,
                                 'max_tokens': 700,
                                 'tier': 'standard',
                                 'max_invocations_per_hour': 5},
    'ChainOptimizerConfig': {   'enabled': False,
                                'analysis_window': 100,
                                'latency_p95_ms_floor': 10000.0,
                                'success_rate_floor': 0.7,
                                'error_rate_ceiling': 0.3,
                                'min_samples_per_group': 20,
                                'apply_enabled': False,
                                'analysis_interval_seconds': 0},
    'ChainOptimizerCounselorConfig': {   'enabled': False,
                                         'baseline_window_seconds': 1800.0,
                                         'observation_window_seconds': 1800.0,
                                         'success_rate_drop_floor': 0.1,
                                         'min_samples_per_window': 20,
                                         'auto_revert_enabled': False},
    'ChainTuningConfig': {   'enabled': True,
                             'low_trust_ceiling': 0.6,
                             'high_trust_floor': 0.75},
    'ConsultationConfig': {   'enabled': True,
                              'timeout_seconds': 30.0,
                              'max_consultations_per_agent_per_hour': 20,
                              'max_pending_requests': 10,
                              'expert_selection_max_candidates': 5,
                              'weight_capability_match': 0.5,
                              'weight_trust': 0.3,
                              'weight_billet_relevance': 0.2},
    'DiagnosticContextConfig': {   'enabled': True,
                                   'default_budget_tokens': 8000,
                                   'chain_trace_ratio': 0.3,
                                   'procedure_ratio': 0.25,
                                   'episode_ratio': 0.25,
                                   'records_ratio': 0.2,
                                   'chars_per_token': 4,
                                   'redistribute_remainder': True},
    'ExpertiseConfig': {   'enabled': True,
                           'max_topics_per_agent': 50,
                           'min_confidence': 0.1,
                           'decay_rate': 0.95,
                           'top_k_experts': 3},
    'KnowledgeConfig': {   'enabled': True,
                           'repo_path': '',
                           'auto_commit': True,
                           'commit_debounce_seconds': 5.0,
                           'max_episodes': 1000,
                           'max_workflows': 200,
                           'restore_on_boot': True},
    'KnowledgeLoadingConfig': {   'enabled': True,
                                  'ambient_token_budget': 200,
                                  'contextual_token_budget': 400,
                                  'on_demand_token_budget': 600,
                                  'ambient_max_age_seconds': 300.0,
                                  'contextual_max_age_seconds': 60.0,
                                  'on_demand_max_age_seconds': 0.0,
                                  'intent_knowledge_map': {   'security_alert': [   'trust',
                                                                                    'agents'],
                                                              'proactive_think': [   'episodes',
                                                                                     'proactive'],
                                                              'ward_room_notification': [   'episodes',
                                                                                            'agents'],
                                                              'direct_message': [   'episodes',
                                                                                    'agents']}},
    'LLMRateConfig': {   'rpm_fast': 120,
                         'rpm_standard': 120,
                         'rpm_deep': 30,
                         'max_wait_seconds': 30.0,
                         'cache_max_entries': 500,
                         'per_agent_hourly_token_cap': 0,
                         'max_concurrent_calls': 6,
                         'interactive_reserved_slots': 2,
                         'max_inflight_per_endpoint': 8,
                         'endpoint_failure_cooldown_seconds': 15.0},
    'ObservableStateConfig': {   'verification_enabled': True,
                                 'max_claims_per_thread': 10},
    'OrientationConfig': {   'enabled': True,
                             'orientation_window_seconds': 600.0,
                             'cold_start_full_orientation': True,
                             'warm_boot_orientation': True,
                             'proactive_supplement': True,
                             'populate_watch_section': True,
                             'populate_ward_room_department': True,
                             'populate_event_log_window': True},
    'PredictiveBranchingConfig': {   'enabled': False,
                                     'cache_ttl_seconds': 60.0,
                                     'cache_max_entries': 128,
                                     'speculation_tokens_per_window': 2000,
                                     'speculation_window_seconds': 300.0,
                                     'flush_rate_feedback_threshold': 0.3,
                                     'flush_rate_window_seconds': 3600.0,
                                     'accuracy_ring_size': 100,
                                     'cheap_tier_min_confidence': 0.3,
                                     'standard_tier_min_confidence': 0.7,
                                     'anticipatory_tier_min_confidence': 0.85},
    'QuestionAdaptiveConfig': {'enabled': True, 'strategy_overrides': {}},
    'RecordsConfig': {   'enabled': True,
                         'repo_path': '',
                         'auto_commit': True,
                         'commit_debounce_seconds': 5.0,
                         'max_episodes_per_hour': 20,
                         'notebook_dedup_enabled': True,
                         'notebook_similarity_threshold': 0.8,
                         'notebook_staleness_hours': 72.0,
                         'notebook_max_scan_entries': 20,
                         'notebook_repetition_enabled': True,
                         'notebook_repetition_window_hours': 48.0,
                         'notebook_repetition_threshold_count': 3,
                         'notebook_repetition_novelty_threshold': 0.2,
                         'notebook_repetition_suppression_count': 5,
                         'notebook_metrics_enabled': True,
                         'realtime_convergence_enabled': True,
                         'realtime_convergence_threshold': 0.5,
                         'realtime_divergence_threshold': 0.3,
                         'realtime_convergence_staleness_hours': 72.0,
                         'realtime_max_scan_per_agent': 5,
                         'realtime_min_convergence_agents': 2,
                         'realtime_min_convergence_departments': 2,
                         'convergence_independence_threshold': 0.3,
                         'notebook_quality_enabled': True,
                         'notebook_quality_low_threshold': 0.3,
                         'notebook_quality_warn_threshold': 0.5,
                         'notebook_staleness_alert_rate': 0.7,
                         'semantic_index_enabled': False},
    'SalienceConfig': {   'enabled': True,
                          'weights': {   'relevance': 0.3,
                                         'recency': 0.25,
                                         'novelty': 0.15,
                                         'urgency': 0.2,
                                         'social': 0.1},
                          'threshold': 0.3,
                          'background_max_entries': 50},
    'SelfImprovementConfig': {   'enabled': False,
                                 'qa_pool_size': 3,
                                 'iteration_cap': 5,
                                 'evolution_half_life_seconds': 2592000.0,
                                 'evolution_collection_name': 'self_improvement_lessons',
                                 'persistence_root_dir': 'src/probos/agents/designed'},
    'SocialVerificationConfig': {   'enabled': True,
                                    'corroboration_threshold': 0.4,
                                    'corroboration_max_agents': 5,
                                    'corroboration_min_confidence': 0.3,
                                    'cascade_enabled': True,
                                    'cascade_independence_threshold': 0.3,
                                    'cascade_cooldown_seconds': 300.0,
                                    'anomaly_window_discount': 0.5,
                                    'provenance_version_independence_weight': 0.7,
                                    'provenance_validation_enabled': True,
                                    'expose_episode_content': False},
    'SourceTracingConfig': {   'echo_min_chain_length': 3,
                               'echo_similarity_threshold': 0.4,
                               'echo_analysis_enabled': True},
    'StepInstructionConfig': {   'enabled': False,
                                 'step_categories': {   'query': [],
                                                        'analyze': [   'observation_guidelines',
                                                                       'situation_assessment',
                                                                       'when_to_act_vs_observe',
                                                                       'memory_anchoring',
                                                                       'source_attribution',
                                                                       'self_monitoring'],
                                                        'compose': [   'communication_style',
                                                                       'personality_expression',
                                                                       'audience_awareness',
                                                                       'ward_room_actions',
                                                                       'knowledge_capture',
                                                                       'duty_reporting'],
                                                        'evaluate': [   'self_monitoring',
                                                                        'scope_discipline',
                                                                        'communication_style'],
                                                        'reflect': [   'self_monitoring',
                                                                       'scope_discipline',
                                                                       'knowledge_capture']},
                                 'universal_categories': [   'identity',
                                                             'chain_of_command',
                                                             'core_directives',
                                                             'encoding_safety'],
                                 'log_token_savings': True},
    'SubTaskConfig': {   'enabled': True,
                         'chain_timeout_ms': 30000,
                         'step_timeout_ms': 15000,
                         'max_chain_steps': 6,
                         'fallback_on_timeout': 'single_call',
                         'max_concurrent_chains': 4,
                         'nats_publish_enabled': False,
                         'nats_payload_max_bytes': 16384},
    'TaskContextConfig': {   'enabled': True,
                             'orders_dir': 'config/task_orders',
                             'max_tokens': 500}}


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _walk(dumped: dict[str, Any], dotted: str) -> Any:
    """Follow a ``MODEL_TO_PATH`` entry into a ``model_dump`` result."""
    node: Any = dumped
    for part in dotted.split("."):
        node = node[part]
    return node


facade = _load("_ad1270e2f_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    return yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))["models"]


@pytest.fixture(scope="module")
def config_schema() -> dict[str, Any]:
    index = CodebaseIndex(_SOURCE_ROOT)
    index.build()
    return index.get_config_schema()


def test_the_batch_tables_agree_with_each_other() -> None:
    """Guard the guard: a model dropped from a table must fail, not vanish."""
    assert set(EXPECTED_DUMPS) == set(MOVED_MODELS)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 23


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_knowledge, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    """``config_models/__init__`` must not shadow the module with a copy."""
    assert getattr(config_pkg, name) is getattr(config_knowledge, name)
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
    """The existing call sites spell it exactly this way."""
    from probos.config import (  # noqa: F401
        ArchiveConfig,
        KnowledgeConfig,
        LLMRateConfig,
        RecordsConfig,
        SubTaskConfig,
        TaskContextConfig,
    )

    assert ArchiveConfig is config_knowledge.ArchiveConfig
    assert TaskContextConfig is config_knowledge.TaskContextConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``."""
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.knowledge"
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
        getattr(config_knowledge, name).model_fields
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
    """Empty input: every field falls back to its own default."""
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    """The direct instance, not just the one ``SystemConfig`` composes."""
    assert getattr(config_facade, name)().model_dump(mode="json") == EXPECTED_DUMPS[name]


#: Numeric bounds (Ge/Gt/Le/Lt) declared per model, counted on the PRE-MOVE
#: source. Pinning the exact count per model is what makes the case below
#: non-vacuous: twenty of the twenty-three carry no bound at all, so a bare
#: "at least zero were checked" assertion would pass even if a model that DOES
#: carry bounds silently lost every one of them.
EXPECTED_BOUND_COUNTS: dict[str, int] = {
    "ArchiveConfig": 0,
    "CausalReasoningConfig": 0,
    "ChainOptimizerConfig": 0,
    "ChainOptimizerCounselorConfig": 0,
    "ChainTuningConfig": 0,
    "ConsultationConfig": 0,
    "DiagnosticContextConfig": 0,
    "ExpertiseConfig": 0,
    "KnowledgeConfig": 0,
    "KnowledgeLoadingConfig": 0,
    "LLMRateConfig": 2,
    "ObservableStateConfig": 0,
    "OrientationConfig": 0,
    "PredictiveBranchingConfig": 14,
    "QuestionAdaptiveConfig": 0,
    "RecordsConfig": 0,
    "SalienceConfig": 0,
    "SelfImprovementConfig": 5,
    "SocialVerificationConfig": 0,
    "SourceTracingConfig": 0,
    "StepInstructionConfig": 0,
    "SubTaskConfig": 0,
    "TaskContextConfig": 0,
}


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_every_declared_bound_is_still_enforced(name: str) -> None:
    """Walk the ACTUAL metadata rather than a hand-written bound list.

    Batch 4 taught half of this: a hand-written case asserted a bound on a field
    that had none, so the constraints are now read from ``FieldInfo.metadata``.
    Review of THIS batch taught the other half -- reading the live metadata and
    then asserting ``checked >= 0`` is always true, so a model could lose every
    bound and still pass. The count is pinned per model, from the pre-move
    source, and must match exactly.
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
            elif kind == "Gt":
                bad = bound
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
    """Premise for the case above, on both halves.

    Exhaustive, so a model cannot drop out of the table unnoticed; and not all
    zero, because a table of zeroes would make every per-model assertion
    trivially satisfiable.
    """
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 21
    assert sorted(n for n, c in EXPECTED_BOUND_COUNTS.items() if c) == [
        "LLMRateConfig",
        "PredictiveBranchingConfig",
        "SelfImprovementConfig",
    ]


@pytest.mark.parametrize("value", ["not-a-number", None, [1]])
def test_moved_models_still_reject_wrong_types(value: object) -> None:
    """Error path: the move must not have loosened coercion.

    The field is asserted to EXIST first. Pydantic silently ignores an unknown
    keyword on a model without ``extra="forbid"``, so a typo'd field name makes
    ``pytest.raises`` fail for the right reason but for the wrong cause -- which
    is exactly what happened when this case was first written against a field
    ``LLMRateConfig`` does not have.
    """
    assert "rpm_fast" in config_facade.LLMRateConfig.model_fields

    with pytest.raises(ValueError):
        config_facade.LLMRateConfig(rpm_fast=value)


def test_unknown_keywords_are_ignored_not_rejected() -> None:
    """Pins the trap above as measured behaviour rather than folklore.

    This records what the models DO today, not what they ought to do. The
    permissiveness comes from an empty ``model_config`` -- no ``extra="forbid"``
    anywhere in the chain -- and it is why a typo'd field name in a test passes
    silently instead of failing. If that is ever tightened, UPDATE this case to
    assert rejection; do not delete it, because the trap it documents is what
    made an earlier version of the coercion test above prove nothing.
    """
    assert config_facade.LLMRateConfig.model_config.get("extra") is None

    model = config_facade.LLMRateConfig(definitely_not_a_field=object())

    assert not hasattr(model, "definitely_not_a_field")
    assert model.rpm_fast == EXPECTED_DUMPS["LLMRateConfig"]["rpm_fast"]


def test_mutable_defaults_are_not_shared_between_instances() -> None:
    """Any list/dict/set default that is shared would leak across instances.

    Checks EVERY mutable-valued field, not only those declared with a
    ``default_factory``. Three fields in this batch declare a mutable default as
    a plain literal; gating on ``default_factory`` skipped exactly those, which
    are the ones a naive Pydantic model would actually share.
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

    # Premise: a silent drop to zero examined fields would make this vacuous.
    assert len(examined) >= 5
    assert shared == []


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.knowledge is not second.knowledge
    assert first.archive is not second.archive

    first.knowledge.enabled = not first.knowledge.enabled

    assert second.knowledge.enabled == EXPECTED_DUMPS["KnowledgeConfig"]["enabled"]


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_knowledge_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_KNOWLEDGE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not any(name.startswith("probos") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    """A re-export beside a surviving definition would shadow silently."""
    tree = ast.parse((_SOURCE_ROOT / "config.py").read_text(encoding="utf-8"))
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_no_name_is_defined_in_more_than_one_domain_module() -> None:
    """Six batches now share one namespace; a collision would shadow one."""
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


def test_no_test_resolves_a_moved_model_through_a_hardcoded_config_path() -> None:
    """Batch 5's regression class, pinned so batch 7 cannot repeat it.

    Three ``?raw`` source guards asserted docstring text at the literal path
    ``src/probos/config.py`` and went red the moment ``ExecutionConfig`` moved.
    They were repaired to resolve ``inspect.getfile(Model)``; this asserts the
    repair is still in place rather than trusting that it stayed.
    """
    for relative in (
        "tests/test_bf781_isolation_claims.py",
        "tests/test_bf763_execution_claims.py",
    ):
        source = (_REPO_ROOT / relative).read_text(encoding="utf-8")

        assert "_declaring_source(" in source
        assert 'CONFIG = "src/probos/config.py"' not in source
        assert '_text("src/probos/config.py")' not in source


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_a_knowledge_model_change() -> None:
    """A model change must still select the full suite."""
    selector = _load("_ad1270e2f_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/knowledge.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    """The widened scan must reach every file in the package, not just core."""
    profiles = _load(
        "_ad1270e2f_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )

    scanned = [path.name for path in profiles._env_scan_paths(_SOURCE_ROOT)]

    assert "config.py" in scanned
    assert "knowledge.py" in scanned
    assert profiles.env_reads_reaching_defaults(_SOURCE_ROOT)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
