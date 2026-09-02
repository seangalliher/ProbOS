"""AD-1270e2 batch 2 -- the ``cognition`` batch left ``config.py`` unchanged.

Fifteen leaf models -- attention, dreaming, self-modification and the working /
episodic memory cluster -- now live in ``probos.config_models.cognition`` and are
re-exported from ``probos.config``. The property under test is that no consumer
can tell: same class object, same qualname, same MRO, same ordered fields, same
dumped defaults. A name-only check would pass a wrapper or a re-declared copy,
so the identity assertions compare ``is``.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` at
authoring time -- the class text *before* the move, evaluated on its own. Had it
been derived from the moved module the assertion would compare the code against
itself and pass for any value.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.cognition as config_cognition
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_COGNITION_SOURCE = _REPO_ROOT / "src" / "probos" / "config_models" / "cognition.py"

#: The batch, named once. Every parametrised case walks exactly these fifteen.
MOVED_MODELS: tuple[str, ...] = (
    "AttentionConfig",
    "DistillationConfig",
    "DreamWMConfig",
    "DreamingConfig",
    "MemoryBudgetConfig",
    "MetabolismConfig",
    "PinnedKnowledgeConfig",
    "ReconsolidationConfig",
    "RetroactiveConfig",
    "SelfModConfig",
    "SpreadingActivationConfig",
    "StorageGateConfig",
    "TemporalValidityConfig",
    "ThoughtStoreConfig",
    "WorkingMemoryConfig",
)

#: ``SystemConfig`` field -> moved model, so a dump assertion names both ends.
#: ``AttentionConfig`` is absent on purpose: it hangs off ``memory.attention``,
#: one level down, and is asserted separately.
FIELD_TO_MODEL: dict[str, str] = {
    "dreaming": "DreamingConfig",
    "dream_wm": "DreamWMConfig",
    "self_mod": "SelfModConfig",
    "working_memory": "WorkingMemoryConfig",
    "memory_budget": "MemoryBudgetConfig",
    "spreading_activation": "SpreadingActivationConfig",
    "thought_store": "ThoughtStoreConfig",
    "distillation": "DistillationConfig",
    "metabolism": "MetabolismConfig",
    "reconsolidation": "ReconsolidationConfig",
    "storage_gate": "StorageGateConfig",
    "retroactive": "RetroactiveConfig",
    "pinned_knowledge": "PinnedKnowledgeConfig",
    "temporal_validity": "TemporalValidityConfig",
}

#: Pre-move ``model_dump(mode="json")`` for each moved model, measured against
#: ``HEAD``'s ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {   'AttentionConfig': {   'enabled': False,
                               'token_budget': 120000,
                               'salience_scoring': False,
                               'w_rel': 1.0,
                               'w_rec': 0.5,
                               'w_imp': 0.5,
                               'recency_half_life_seconds': 86400.0,
                               'camera_scene_bid_enabled': True,
                               'camera_novelty_minimum': 0.3,
                               'camera_novelty_ema_alpha': 0.3,
                               'camera_recessive_suppress_threshold': 0.15,
                               'arousal_enabled': False,
                               'arousal_red_budget_multiplier': 0.5,
                               'arousal_full_decay_seconds': 300.0,
                               'arousal_repeat_window_seconds': 60.0},
        'DreamingConfig': {   'organ_enabled': False,
                              'idle_threshold_seconds': 120.0,
                              'dream_interval_seconds': 600.0,
                              'replay_episode_count': 50,
                              'pathway_strengthening_factor': 0.03,
                              'pathway_weakening_factor': 0.02,
                              'prune_threshold': 0.01,
                              'trust_boost': 0.1,
                              'trust_penalty': 0.1,
                              'pre_warm_top_k': 5,
                              'notebook_consolidation_enabled': True,
                              'notebook_consolidation_threshold': 0.6,
                              'notebook_consolidation_min_entries': 2,
                              'notebook_convergence_threshold': 0.5,
                              'notebook_convergence_min_agents': 3,
                              'notebook_convergence_min_departments': 2,
                              'active_retrieval_enabled': False,
                              'retrieval_episodes_per_cycle': 3,
                              'retrieval_success_threshold': 0.6,
                              'retrieval_partial_threshold': 0.3,
                              'retrieval_initial_interval_hours': 24.0,
                              'retrieval_max_interval_hours': 168.0,
                              'retrieval_counselor_failure_streak': 3,
                              'reminiscence_enabled': True,
                              'reminiscence_episodes_per_session': 3,
                              'reminiscence_concern_threshold': 3,
                              'reminiscence_confabulation_alert': 0.3,
                              'reminiscence_cooldown_hours': 2.0,
                              'activation_enabled': True,
                              'activation_decay_d': 0.5,
                              'activation_prune_threshold': -2.0,
                              'activation_access_max_age_days': 180,
                              'prune_min_age_hours': 24,
                              'prune_max_fraction': 0.1,
                              'reflection_enabled': True,
                              'reflection_max_per_cycle': 3,
                              'reflection_min_importance': 8,
                              'per_agent_dream_attribution_enabled': False,
                              'aggressive_prune_enabled': True,
                              'aggressive_prune_min_age_hours': 168,
                              'aggressive_prune_threshold': 0.0,
                              'aggressive_prune_max_fraction': 0.25,
                              'episode_pressure_threshold': 5000,
                              'episode_pressure_multiplier': 1.5,
                              'trace_exemplars_per_procedure': 3,
                              'relationship_inference_enabled': True,
                              'relationship_inference_max_pairs_per_run': 50,
                              'relationship_inference_max_per_entity': 5,
                              'relationship_inference_min_confidence': 0.6},
        'DreamWMConfig': {   'enabled': True,
                             'max_priming_entries': 3,
                             'flush_min_entries': 5,
                             'priming_category': 'observation'},
        'SelfModConfig': {   'enabled': False,
                             'require_user_approval': True,
                             'probationary_alpha': 1.0,
                             'probationary_beta': 3.0,
                             'max_designed_agents': 5,
                             'sandbox_timeout_seconds': 60.0,
                             'allowed_imports': [   'asyncio',
                                                    'pathlib',
                                                    'json',
                                                    'os',
                                                    're',
                                                    'datetime',
                                                    'typing',
                                                    'dataclasses',
                                                    'collections',
                                                    'math',
                                                    'hashlib',
                                                    'urllib.parse',
                                                    'base64',
                                                    'csv',
                                                    'io',
                                                    'tempfile'],
                             'forbidden_patterns': [   'subprocess',
                                                       'shutil\\.rmtree',
                                                       'os\\.remove',
                                                       'os\\.unlink',
                                                       'eval\\s*\\(',
                                                       'exec\\s*\\(',
                                                       '__import__',
                                                       'open\\s*\\(.*[\'\\"][waxWAX]',
                                                       'socket\\b',
                                                       'ctypes\\b',
                                                       'os\\.system',
                                                       'os\\.popen',
                                                       'os\\.exec',
                                                       'os\\.kill',
                                                       '\\.write_text\\s*\\(',
                                                       '\\.write_bytes\\s*\\(',
                                                       '\\.unlink\\s*\\(',
                                                       '__builtins__',
                                                       'compile\\s*\\('],
                             'research_enabled': False,
                             'research_domain_whitelist': [   'docs.python.org',
                                                              'pypi.org',
                                                              'developer.mozilla.org',
                                                              'learn.microsoft.com'],
                             'research_max_pages': 3,
                             'research_max_content_per_page': 2000},
        'WorkingMemoryConfig': {   'token_budget': 3000,
                                   'max_recent_actions': 10,
                                   'max_recent_observations': 5,
                                   'max_recent_conversations': 5,
                                   'max_events': 10,
                                   'proactive_budget': 1500,
                                   'stale_threshold_hours': 24.0,
                                   'conclusion_ttl_seconds': 1800.0,
                                   'max_conclusions': 20,
                                   'duty_budget': 600,
                                   'social_budget': 800,
                                   'ship_budget': 800,
                                   'engagement_budget': 800},
        'MemoryBudgetConfig': {   'enabled': True,
                                  'total_budget_tokens': 4650,
                                  'l0_budget': 150,
                                  'l1_budget': 3000,
                                  'l2_budget': 1000,
                                  'l3_budget': 500},
        'SpreadingActivationConfig': {   'enabled': True,
                                         'max_hops': 2,
                                         'k_per_hop': 5,
                                         'hop_decay_factor': 0.6,
                                         'min_anchor_fields': 2},
        'ThoughtStoreConfig': {   'enabled': True,
                                  'min_importance': 5,
                                  'max_thoughts_per_cycle': 3},
        'DistillationConfig': {   'enabled': True,
                                  'min_failure_cluster_size': 3,
                                  'comparative_enabled': True},
        'MetabolismConfig': {   'enabled': True,
                                'decay_half_life_seconds': 3600.0,
                                'forget_threshold': 0.05,
                                'min_entries_per_buffer': 2,
                                'audit_enabled': True,
                                'cycle_interval_seconds': 300.0,
                                'triage_fullness_threshold': 0.8,
                                'triage_base_score': 0.3},
        'ReconsolidationConfig': {   'enabled': True,
                                     'base_intervals_hours': [   1.0,
                                                                 6.0,
                                                                 24.0,
                                                                 72.0,
                                                                 168.0,
                                                                 720.0],
                                     'importance_scale_factor': 0.1,
                                     'max_scheduled': 500},
        'StorageGateConfig': {   'enabled': True,
                                 'duplicate_threshold': 0.95,
                                 'utility_floor': 0.2,
                                 'recent_window': 50,
                                 'contradiction_check_enabled': True},
        'RetroactiveConfig': {   'enabled': True,
                                 'neighbor_k': 5,
                                 'similarity_threshold': 0.7,
                                 'max_relations_per_episode': 10,
                                 'propagate_watch_section': True,
                                 'propagate_department': True},
        'PinnedKnowledgeConfig': {   'enabled': True,
                                     'max_tokens': 150,
                                     'max_pins': 10,
                                     'default_ttl_seconds': 86400.0},
        'TemporalValidityConfig': {'enabled': True, 'default_validity_hours': 0.0}}


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


facade = _load("_ad1270e2b_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    document = yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))
    return document["models"]


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_cognition, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    """``config_models/__init__`` must not shadow the module with a copy."""
    assert getattr(config_pkg, name) is getattr(config_cognition, name)
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
        AttentionConfig,
        DistillationConfig,
        DreamWMConfig,
        DreamingConfig,
        MemoryBudgetConfig,
        MetabolismConfig,
        PinnedKnowledgeConfig,
        ReconsolidationConfig,
        RetroactiveConfig,
        SelfModConfig,
        SpreadingActivationConfig,
        StorageGateConfig,
        TemporalValidityConfig,
        ThoughtStoreConfig,
        WorkingMemoryConfig,
    )

    assert AttentionConfig is config_cognition.AttentionConfig
    assert TemporalValidityConfig is config_cognition.TemporalValidityConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``.

    That is the one predicate this move breaks. If it did, all fifteen would
    reclassify as import leakage and the baseline would demand a regeneration
    that proves nothing.
    """
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.cognition"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field_name", sorted(FIELD_TO_MODEL))
def test_system_config_dump_is_unchanged_for_the_moved_field(field_name: str) -> None:
    dumped = SystemConfig().model_dump(mode="json")

    assert dumped[field_name] == EXPECTED_DUMPS[FIELD_TO_MODEL[field_name]]


def test_nested_attention_dump_is_unchanged() -> None:
    """``AttentionConfig`` is reached through ``memory``, not off the root."""
    dumped = SystemConfig().model_dump(mode="json")

    assert dumped["memory"]["attention"] == EXPECTED_DUMPS["AttentionConfig"]


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
    model = getattr(config_facade, name)

    assert model().model_dump(mode="json") == EXPECTED_DUMPS[name]


def test_attention_lower_bounds_survived_the_move() -> None:
    """``AttentionConfig`` carries the batch's only ``Field`` constraints."""
    assert config_facade.AttentionConfig(w_rel=0.0).w_rel == 0.0
    with pytest.raises(ValueError):
        config_facade.AttentionConfig(w_rel=-0.1)
    with pytest.raises(ValueError):
        config_facade.AttentionConfig(recency_half_life_seconds=0.0)


def test_attention_upper_bounds_survived_the_move() -> None:
    """``le=1.0`` is the other half of the bound; a move must not drop it."""
    assert (
        config_facade.AttentionConfig(camera_novelty_minimum=1.0).camera_novelty_minimum
        == 1.0
    )
    with pytest.raises(ValueError):
        config_facade.AttentionConfig(camera_novelty_minimum=1.1)


def test_attention_token_budget_floor_survived_the_move() -> None:
    assert config_facade.AttentionConfig(token_budget=1000).token_budget == 1000
    with pytest.raises(ValueError):
        config_facade.AttentionConfig(token_budget=999)


@pytest.mark.parametrize("value", ["not-a-number", None, [1]])
def test_moved_models_still_reject_wrong_types(value: object) -> None:
    """Error path: the move must not have loosened coercion."""
    with pytest.raises(ValueError):
        config_facade.MemoryBudgetConfig(l1_budget=value)


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.dreaming is not second.dreaming
    assert first.memory.attention is not second.memory.attention

    first.dreaming.organ_enabled = not first.dreaming.organ_enabled

    assert (
        second.dreaming.organ_enabled
        == EXPECTED_DUMPS["DreamingConfig"]["organ_enabled"]
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_cognition_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_COGNITION_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "probos.config" not in imported
    assert not any(name.startswith("probos.config.") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    """A re-export beside a surviving definition would shadow silently."""
    tree = ast.parse(
        (_REPO_ROOT / "src" / "probos" / "config.py").read_text(encoding="utf-8")
    )
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_a_cognition_model_change() -> None:
    """A model change must still select the full suite."""
    selector = _load("_ad1270e2b_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/cognition.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    """The widened scan must reach every file in the package, not just core."""
    profiles = _load(
        "_ad1270e2b_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )
    package = _REPO_ROOT / "src" / "probos"

    scanned = [path.name for path in profiles._env_scan_paths(package)]

    assert "config.py" in scanned
    assert "cognition.py" in scanned
    assert profiles.env_reads_reaching_defaults(package)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
