"""AD-1270e2 batch 9 -- the ``agentic`` batch, and the last of the true leaves.

Twenty-two leaf models -- agentic dispatch and the agentic tool surface, the
four DM pipeline stages (sanity gate, targeted lookup, deliberate, agentic),
the write-claim guard, repair, capability triage, autonomy boundaries, crew
development and discovery learning, scoped cognition, workspace ontology, the
gap-pipeline extensions and the extension loader, creative expression, the
classification gate, grounding, OS activity, temporal and mDNS discovery -- now
live in ``probos.config_models.agentic`` and are re-exported from
``probos.config``.

This is the largest single batch by source volume (949 class lines), because it
carries ``DmAgenticConfig`` and ``AgenticToolsConfig``, whose field descriptions
are essay-length. It does NOT empty the true-leaf set: fourteen leaves remain in
``config.py`` and are pinned below, so the mechanical line-span recipe still
applies to batch 10.

What is preserved is the PUBLIC FACADE and every value behind it. What
deliberately CHANGES is the declaration site -- ``config.py`` loses 993 lines
and each model's ``__module__`` becomes ``probos.config_models.agentic``.

``EXPECTED_DUMPS`` was CAPTURED AT AUTHORING TIME from
``git show HEAD:src/probos/config.py`` -- the class text *before* the move,
compiled in a throwaway module and evaluated on its own. It is a static literal
from here on: nothing in this file regenerates it at run time, and that is
deliberate, because after this commit ``HEAD`` no longer contains the pre-move
text. Had it been derived from the moved module it would compare the code
against itself and pass for any value.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import sys
import tokenize
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, get_origin

import pytest
import yaml
from pydantic import ValidationError

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.agentic as config_agentic
from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_SOURCE_ROOT = _REPO_ROOT / "src" / "probos"
_AGENTIC_SOURCE = _SOURCE_ROOT / "config_models" / "agentic.py"

MOVED_MODELS: tuple[str, ...] = (
    "AgenticDispatchConfig",
    "AgenticToolsConfig",
    "AutonomyBoundariesConfig",
    "CapabilityTriageConfig",
    "ClassificationGateConfig",
    "CreativeExpressionConfig",
    "CrewDevelopmentConfig",
    "DiscoveryConfig",
    "DiscoveryLearningConfig",
    "DmAgenticConfig",
    "DmDeliberateConfig",
    "DmSanityGateConfig",
    "DmTargetedLookupConfig",
    "ExtensionsConfig",
    "GapPipelineExtensionsConfig",
    "GroundingConfig",
    "OSActivityConfig",
    "RepairConfig",
    "ScopedCognitionConfig",
    "TemporalConfig",
    "WorkspaceOntologyConfig",
    "WriteClaimGuardConfig",
)

MODEL_TO_PATH: dict[str, str] = {
    "AgenticDispatchConfig": "agentic_dispatch",
    "AgenticToolsConfig": "agentic_tools",
    "AutonomyBoundariesConfig": "autonomy_boundaries",
    "CapabilityTriageConfig": "capability_triage",
    "ClassificationGateConfig": "classification_gate",
    "CreativeExpressionConfig": "creative_expression",
    "CrewDevelopmentConfig": "crew_development",
    "DiscoveryConfig": "discovery",
    "DiscoveryLearningConfig": "discovery_learning",
    "DmAgenticConfig": "dm_agentic",
    "DmDeliberateConfig": "dm_deliberate",
    "DmSanityGateConfig": "dm_sanity_gate",
    "DmTargetedLookupConfig": "dm_targeted_lookup",
    "ExtensionsConfig": "extensions",
    "GapPipelineExtensionsConfig": "gap_pipeline_extensions",
    "GroundingConfig": "grounding",
    "OSActivityConfig": "os_activity",
    "RepairConfig": "repair",
    "ScopedCognitionConfig": "scoped_cognition",
    "TemporalConfig": "temporal",
    "WorkspaceOntologyConfig": "workspace_ontology",
    "WriteClaimGuardConfig": "write_claim_guard",
}

#: Bound ENDPOINTS that cannot be probed with the field alone, because a
#: cross-field ``model_validator`` relates them to a sibling holding its default.
#: Setting the field to THIS endpoint raises a MODEL-level error (``loc == ()``)
#: about the relationship, not a field error about the bound -- so a naive probe
#: would be satisfied by the wrong exception entirely.
#:
#: Keyed by ``(model, field, kind)``, NOT by field. An earlier version excluded
#: whole fields, which suppressed twelve probes where only six endpoints
#: conflict and let three real constraints escape every guard. An exclusion
#: table is exactly where an unenforced bound hides, so it is kept minimal, and
#: both halves are proven below rather than trusted.
CROSS_FIELD_BLOCKED: tuple[tuple[str, str, str], ...] = (
    ("AgenticDispatchConfig", "crew_ingress_scan_limit", "Ge"),
    ("AgenticDispatchConfig", "crew_ingress_semantic_call_limit", "Le"),
    ("AgenticDispatchConfig", "crew_recovery_initial_backoff_seconds", "Le"),
    ("AgenticDispatchConfig", "crew_recovery_max_backoff_seconds", "Ge"),
    ("DiscoveryLearningConfig", "zpd_lower_bound", "Le"),
    ("DiscoveryLearningConfig", "zpd_upper_bound", "Ge"),
)

#: Numeric bounds declared per model, EXCLUDING the six endpoints above.
#: Pinning the exact count is what keeps the case below non-vacuous: sixteen of
#: the twenty-two carry no bound at all.
#:
#: The six endpoints in ``CROSS_FIELD_BLOCKED`` are unreachable by the GENERIC
#: probe above, which perturbs one field and leaves its siblings at their
#: defaults: a sibling ``model_validator`` then rejects the endpoint before the
#: field bound is consulted. They are pinned BY VALUE here instead.
#:
#: Two of the six ARE reachable behaviourally once a sibling is chosen to satisfy
#: the relationship, and those two are additionally probed in
#: ``test_the_cross_field_bounds_are_still_enforced_with_a_valid_sibling``.
#: Measured 2026-09-03: without this table all four testable widenings survived
#: (scan-limit ge 1->0, semantic-call le 128->1000, zpd-lower le 1.0->2.0,
#: zpd-upper ge 0.0->-1.0) while the whole file stayed green.
CROSS_FIELD_BOUND_VALUES: dict[tuple[str, str, str], float] = {
    ("AgenticDispatchConfig", "crew_ingress_scan_limit", "Ge"): 1,
    ("AgenticDispatchConfig", "crew_ingress_semantic_call_limit", "Le"): 128,
    ("AgenticDispatchConfig", "crew_recovery_initial_backoff_seconds", "Le"): 3_600.0,
    ("AgenticDispatchConfig", "crew_recovery_max_backoff_seconds", "Ge"): 0.0,
    ("DiscoveryLearningConfig", "zpd_lower_bound", "Le"): 1.0,
    ("DiscoveryLearningConfig", "zpd_upper_bound", "Ge"): 0.0,
}

#: True leaves still in ``config.py`` after this batch -- the batch 10 work
#: queue. Measured with comments and docstrings stripped; see
#: ``test_the_remaining_true_leaf_set_is_pinned`` for why that matters.
#:
#: Batch 10 caveat, measured 2026-09-03: a class's trailing comments sit OUTSIDE
#: its AST span (``BootCampPhaseConfig`` ends at line 3373, its three comments
#: run 3374-3376), so a line-span move relocates the class and strands them.
#: Earlier batches did the same; six such comments now trail
#: ``SelfDistillationConfig``.
REMAINING_TRUE_LEAVES: tuple[str, ...] = (
    "BootCampPhaseConfig",
    "ConsultationDeliveryConfig",
    "ConsultationDispatchConfig",
    "ConsultationWorkspaceConfig",
    "DeviceConfig",
    "DmMeshSynthesisConfig",
    "EdgeBackfillConfig",
    "HybridDispatchConfig",
    "KnowledgeEdgeClassificationConfig",
    "KnowledgeEdgesConfig",
    "NLGraphQueryConfig",
    "SecurityInfraConfig",
    "SelfContradictionRecallConfig",
    "WorkBoardReconcilerConfig",
)

EXPECTED_BOUND_COUNTS: dict[str, int] = {
    "AgenticDispatchConfig": 21,
    "AgenticToolsConfig": 16,
    "AutonomyBoundariesConfig": 0,
    "CapabilityTriageConfig": 0,
    "ClassificationGateConfig": 0,
    "CreativeExpressionConfig": 0,
    "CrewDevelopmentConfig": 0,
    "DiscoveryConfig": 0,
    "DiscoveryLearningConfig": 4,
    "DmAgenticConfig": 15,
    "DmDeliberateConfig": 0,
    "DmSanityGateConfig": 0,
    "DmTargetedLookupConfig": 0,
    "ExtensionsConfig": 0,
    "GapPipelineExtensionsConfig": 0,
    "GroundingConfig": 0,
    "OSActivityConfig": 2,
    "RepairConfig": 1,
    "ScopedCognitionConfig": 0,
    "TemporalConfig": 0,
    "WorkspaceOntologyConfig": 0,
    "WriteClaimGuardConfig": 0,
}

#: Pre-move ``model_dump(mode="json")``, measured against ``HEAD``'s
#: ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {   'AgenticDispatchConfig': {   'enabled': False,
                                 'max_parallel_subtasks': 3,
                                 'max_convergence_rounds': 2,
                                 'orchestrator_enabled': False,
                                 'max_active_crew_sessions': 2,
                                 'crew_resume_scan_limit': 100,
                                 'crew_ingress_scan_limit': 100,
                                 'crew_ingress_semantic_call_limit': 32,
                                 'crew_ingress_semantic_threshold': 0.9,
                                 'crew_provisioning_repair_limit': 100,
                                 'crew_recovery_max_retries': 3,
                                 'crew_recovery_initial_backoff_seconds': 5.0,
                                 'crew_recovery_max_backoff_seconds': 300.0,
                                 'crew_compaction_enabled': False,
                                 'crew_compaction_threshold_tokens': 60000,
                                 'crew_token_budget': None,
                                 'crew_loop_until_done_enabled': False,
                                 'crew_loop_until_done_max_iterations': 2,
                                 'crew_loop_until_done_predicate': 'stopped_reason',
                                 'crew_loop_until_done_completion_marker': 'TASK '
                                                                           'COMPLETE'},
    'AgenticToolsConfig': {   'tool_search_enabled': False,
                              'delegation_enabled': False,
                              'delegation_max_depth': 1,
                              'delegation_max_iterations': 5,
                              'delegation_tier': 'standard',
                              'oracle_query_enabled': False,
                              'publish_finding_enabled': False,
                              'publish_finding_max_per_hour': 12,
                              'publish_finding_max_content_chars': 4000,
                              'publish_finding_max_per_hour_ship': 40,
                              'browser_enabled': False,
                              'disposition_enabled': False,
                              'crew_sigma_context_enabled': False,
                              'crew_sigma_max_chars': 2000,
                              'crew_sigma_max_entries': 4,
                              'crew_sigma_min_score': 0.35},
    'AutonomyBoundariesConfig': {'enabled': True},
    'CapabilityTriageConfig': {   'grant_fast_path_enabled': False,
                                  'grant_trust_floor': 0.8},
    'ClassificationGateConfig': {'enabled': True},
    'CreativeExpressionConfig': {'enabled': True, 'default_classification': 'ship'},
    'CrewDevelopmentConfig': {'enabled': True},
    'DiscoveryConfig': {   'enabled': False,
                           'service_type': '_probos._tcp.local.',
                           'hostname': 'probos',
                           'instance_name': 'ProbOS',
                           'txt_path': '/'},
    'DiscoveryLearningConfig': {   'enabled': True,
                                   'confidence_prior_alpha': 1.0,
                                   'confidence_prior_beta': 1.0,
                                   'zpd_lower_bound': 0.4,
                                   'zpd_upper_bound': 0.75},
    'DmAgenticConfig': {   'enabled': False,
                           'max_iterations': 5,
                           'tier': 'standard',
                           'continue_or_ask_enabled': False,
                           'continue_or_ask_max_passes': 2,
                           'promote_to_task_after_seconds': 0.0,
                           'promoted_run_deadline_seconds': 1800.0,
                           'promoted_run_unconfirmed_grace_seconds': 1800.0,
                           'hold_degraded_turns': False,
                           'hold_degraded_turn_ttl_seconds': 900.0,
                           'hold_degraded_turn_max_threads': 16,
                           'compaction_enabled': False,
                           'compaction_threshold_tokens': 60000},
    'DmDeliberateConfig': {'enabled': False, 'tier': 'deep', 'max_tokens': 800},
    'DmSanityGateConfig': {   'enabled': True,
                              'length_floor': 5,
                              'repetition_prefix_chars': 100,
                              'repetition_similarity_threshold': 0.85,
                              'retry_on_rejection': True,
                              'retry_warnings': ['length_floor', 'orphaned_tag']},
    'DmTargetedLookupConfig': {   'enabled': False,
                                  'classifier_tier': 'regex',
                                  'timeout_ms': 500,
                                  'enable_oracle': True,
                                  'enable_episodic': True,
                                  'enable_codebase': False,
                                  'enable_knowledge': True,
                                  'identity_enabled': True,
                                  'max_lookup_chars': 1500},
    'ExtensionsConfig': {   'enabled': False,
                            'enforce_sealed_core': False,
                            'default_profile': 'minimal',
                            'extensions_dir': 'src/probos/extensions'},
    'GapPipelineExtensionsConfig': {   'remediation_tracker_enabled': True,
                                       'fleet_aggregator_enabled': True,
                                       'remediation_max_history': 100,
                                       'active_remediation_enabled': False},
    'GroundingConfig': {   'referent_gate_enabled': False,
                           'ground_before_collaborate_enabled': False,
                           'confab_probe_enabled': False},
    'OSActivityConfig': {'enabled': False, 'poll_interval_seconds': 5},
    'RepairConfig': {   'enabled': False,
                        'targets': ['architect'],
                        'propose_after_occurrences': 2},
    'ScopedCognitionConfig': {'enabled': True},
    'TemporalConfig': {   'enabled': True,
                          'include_birth_time': True,
                          'include_system_uptime': True,
                          'include_last_action': True,
                          'include_post_count': True,
                          'captain_timezone': '',
                          'include_episode_timestamps': True},
    'WorkspaceOntologyConfig': {'enabled': True, 'max_terms': 1000},
    'WriteClaimGuardConfig': {'enabled': True}}

#: Every field in this batch whose default is a list/dict/set. Pinned exactly
#: rather than counted with ``>=`` -- batches 6, 7 and 8 each shipped a weaker
#: version of this guard, and a threshold lets coverage shrink silently.
EXPECTED_MUTABLE_FIELDS: tuple[str, ...] = (
    "DmSanityGateConfig.retry_warnings",
    "RepairConfig.targets",
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


def _perturbable_field(name: str, section: dict[str, Any]) -> tuple[str, Any]:
    """Pick a field with no declared bound and no ``Literal``, so a
    perturbation stays valid and any round-trip failure is about YAML."""
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


facade = _load("_ad1270e2i_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


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
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 22
    assert set(EXPECTED_DUMPS) == set(MOVED_MODELS)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)


def test_every_moved_model_constructs_without_arguments() -> None:
    """Premise for the dump cases: none of this batch requires a filler."""
    for name in MOVED_MODELS:
        assert getattr(config_facade, name)() is not None


def test_the_remaining_true_leaf_set_is_pinned() -> None:
    """What is left for batch 10, measured rather than asserted from prose.

    A "true leaf" is a class in ``config.py`` whose executable body references no
    other module-level name -- the only shape a byte-for-byte move can take.

    Comments and docstrings are stripped BEFORE the identifier scan. Without
    that, a class is disqualified by a neighbouring name that appears only in
    prose, and the scan reports an empty leaf set for a file that still holds
    fourteen of them. Measured 2026-09-03: the raw-text scan this replaced saw
    0, this scan sees 14, and a pure AST-load walk (which cannot see a quoted
    forward reference) sees 19. The strict middle figure is the one pinned.
    """
    source = (_SOURCE_ROOT / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    tracked: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            tracked.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.Import):
            tracked.update(a.asname or a.name.split(".")[0] for a in node.names)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tracked.add(node.name)
        elif isinstance(node, ast.Assign):
            tracked.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            tracked.add(node.target.id)

    tracked -= {
        "BaseModel", "Field", "Literal", "field_validator", "model_validator",
        "ValidationInfo", "ConfigDict", "Any", "Optional", "annotations",
        "TYPE_CHECKING",
    }

    import re as _re

    ident = _re.compile(r"[A-Za-z_][A-Za-z_0-9]*")

    def _strip(node: ast.ClassDef, segment: str) -> str:
        try:
            pieces = [
                tok.string
                for tok in tokenize.generate_tokens(io.StringIO(segment).readline)
                if tok.type != tokenize.COMMENT
            ]
            segment = " ".join(pieces)
        except (tokenize.TokenError, IndentationError):
            pass
        for child in ast.walk(node):
            if isinstance(
                child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                doc = ast.get_docstring(child, clean=False)
                if doc:
                    segment = segment.replace(doc, " ")
        return segment

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    leaves = []
    for node in classes:
        body = _strip(node, ast.get_source_segment(source, node) or "")
        if not ((set(ident.findall(body)) & tracked) - {node.name}):
            leaves.append(node.name)

    # Premise: the scan must see the remaining classes, and must still be able
    # to disqualify one. A scan that classified everything as a leaf, or nothing
    # as a leaf, would satisfy a bare equality below without measuring anything.
    assert len(classes) >= 25
    assert 0 < len(leaves) < len(classes)

    assert sorted(leaves) == sorted(REMAINING_TRUE_LEAVES)

    # The move itself: nothing this batch claims to have extracted is still here.
    assert set(leaves).isdisjoint(MOVED_MODELS)


# ---------------------------------------------------------------------------
# Identity and re-export
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_agentic, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    assert getattr(config_pkg, name) is getattr(config_agentic, name)
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
        AgenticDispatchConfig,
        AgenticToolsConfig,
        DmAgenticConfig,
        GroundingConfig,
        WriteClaimGuardConfig,
    )

    assert AgenticDispatchConfig is config_agentic.AgenticDispatchConfig
    assert WriteClaimGuardConfig is config_agentic.WriteClaimGuardConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``."""
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.agentic"
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

    assert list(config_schema[name]) == list(getattr(config_agentic, name).model_fields)


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

    Sixty-five bounds in this batch, the densest of the wave -- and three of the
    four models carrying them are the agentic dispatch/tools/DM surface, where a
    silently widened ceiling is a real safety-budget change rather than a
    cosmetic one.
    """
    model = getattr(config_facade, name)
    checked = 0

    for field_name, info in model.model_fields.items():
        for meta in info.metadata:
            kind = type(meta).__name__
            if kind not in {"Ge", "Gt", "Le", "Lt"}:
                continue
            if (name, field_name, kind) in CROSS_FIELD_BLOCKED:
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
            with pytest.raises(ValidationError) as caught:
                model(**{field_name: bad})
            # The rejection must be ABOUT this field. A model-level error means
            # a sibling relationship fired and the bound was never reached.
            assert any(
                tuple(e.get("loc", ())) == (field_name,) for e in caught.value.errors()
            )
            checked += 1

    assert checked == EXPECTED_BOUND_COUNTS[name]


def test_the_bound_table_is_exhaustive_and_not_all_zero() -> None:
    """Premise on both halves: exhaustive, and not trivially satisfiable."""
    assert set(EXPECTED_BOUND_COUNTS) == set(MOVED_MODELS)
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 59
    assert sorted(n for n, c in EXPECTED_BOUND_COUNTS.items() if c) == [
        "AgenticDispatchConfig",
        "AgenticToolsConfig",
        "DiscoveryLearningConfig",
        "DmAgenticConfig",
        "OSActivityConfig",
        "RepairConfig",
    ]


def test_the_cross_field_exclusions_are_real() -> None:
    """Prove every exclusion rather than trusting the list.

    An exclusion table is a place to hide a bound that quietly stopped being
    enforced. Each ``(model, field, kind)`` entry must (a) still declare that
    exact bound, and (b) still raise a MODEL-level error -- ``loc == ()`` --
    when the field is set to that bound's own endpoint. An entry that no longer
    does either is a stale exemption and fails here.
    """
    assert CROSS_FIELD_BLOCKED, "an empty table would make the skip vacuous"

    for model_name, field_name, kind in CROSS_FIELD_BLOCKED:
        model = getattr(config_facade, model_name)
        info = model.model_fields[field_name]
        declared = [
            getattr(meta, kind.lower())
            for meta in info.metadata
            if type(meta).__name__ == kind
        ]

        assert declared, f"{model_name}.{field_name} no longer declares a {kind} bound"

        with pytest.raises(ValidationError) as caught:
            model(**{field_name: declared[0]})

        assert any(tuple(e.get("loc", ())) == () for e in caught.value.errors()), (
            f"{model_name}.{field_name} {kind} no longer raises a cross-field "
            "error; remove it from CROSS_FIELD_BLOCKED and let the bound be probed"
        )


def test_the_cross_field_bounds_are_pinned_by_value() -> None:
    """The six endpoints the GENERIC probe cannot reach.

    The generic probe perturbs one field and leaves its siblings at their
    defaults; a sibling ``model_validator`` then rejects each of these endpoints
    before the field bound is consulted. This pins the declared metadata, which
    is a weaker property than a behavioural check -- it says the number has not
    moved, not that the runtime enforces it. Two of the six are also reachable
    behaviourally and are probed in the valid-sibling case below.

    Mutation-checked 2026-09-03: with this case absent, widening scan-limit
    ``ge`` 1->0, semantic-call ``le`` 128->1000, zpd-lower ``le`` 1.0->2.0 and
    zpd-upper ``ge`` 0.0->-1.0 each left the entire file green.
    """
    assert set(CROSS_FIELD_BOUND_VALUES) == set(CROSS_FIELD_BLOCKED)

    for (model_name, field_name, kind), expected in CROSS_FIELD_BOUND_VALUES.items():
        model = getattr(config_facade, model_name)
        declared = [
            getattr(meta, kind.lower())
            for meta in model.model_fields[field_name].metadata
            if type(meta).__name__ == kind
        ]

        assert declared == [expected], (
            f"{model_name}.{field_name} declares {kind}={declared}, pinned {expected}; "
            "a cross-field endpoint changed and no behavioural probe can see it"
        )


def test_the_cross_field_bounds_are_still_enforced_with_a_valid_sibling() -> None:
    """The excluded bounds are skipped by the loop, not left untested.

    Each is exercised with a sibling value that satisfies the relationship, so
    the bound itself is still shown to accept its endpoint and reject beyond it.
    """
    assert (
        config_facade.AgenticDispatchConfig(
            crew_ingress_scan_limit=1, crew_ingress_semantic_call_limit=1
        ).crew_ingress_scan_limit
        == 1
    )
    with pytest.raises(ValueError):
        config_facade.AgenticDispatchConfig(
            crew_ingress_scan_limit=0, crew_ingress_semantic_call_limit=0
        )

    assert (
        config_facade.AgenticDispatchConfig(
            crew_recovery_initial_backoff_seconds=0.0,
            crew_recovery_max_backoff_seconds=0.0,
        ).crew_recovery_max_backoff_seconds
        == 0.0
    )
    with pytest.raises(ValueError):
        config_facade.AgenticDispatchConfig(
            crew_recovery_initial_backoff_seconds=-0.001,
            crew_recovery_max_backoff_seconds=0.0,
        )

    # The two CEILINGS. The cases above drive each field's floor; a sibling
    # large enough to satisfy the relationship reaches the ceiling as well, and
    # the rejection must name the field rather than the model.
    assert (
        config_facade.AgenticDispatchConfig(
            crew_ingress_scan_limit=1_000, crew_ingress_semantic_call_limit=128
        ).crew_ingress_semantic_call_limit
        == 128
    )
    with pytest.raises(ValidationError) as caught:
        config_facade.AgenticDispatchConfig(
            crew_ingress_scan_limit=1_000, crew_ingress_semantic_call_limit=129
        )
    assert any(
        tuple(e.get("loc", ())) == ("crew_ingress_semantic_call_limit",)
        for e in caught.value.errors()
    )

    assert (
        config_facade.AgenticDispatchConfig(
            crew_recovery_initial_backoff_seconds=3_600.0,
            crew_recovery_max_backoff_seconds=86_400.0,
        ).crew_recovery_initial_backoff_seconds
        == 3_600.0
    )
    with pytest.raises(ValidationError) as caught:
        config_facade.AgenticDispatchConfig(
            crew_recovery_initial_backoff_seconds=3_600.001,
            crew_recovery_max_backoff_seconds=86_400.0,
        )
    assert any(
        tuple(e.get("loc", ())) == ("crew_recovery_initial_backoff_seconds",)
        for e in caught.value.errors()
    )

    assert (
        config_facade.DiscoveryLearningConfig(
            zpd_lower_bound=0.0, zpd_upper_bound=1.0
        ).zpd_upper_bound
        == 1.0
    )
    with pytest.raises(ValueError):
        config_facade.DiscoveryLearningConfig(zpd_lower_bound=-0.001, zpd_upper_bound=1.0)
    with pytest.raises(ValueError):
        config_facade.DiscoveryLearningConfig(zpd_lower_bound=0.0, zpd_upper_bound=1.001)


def test_moved_models_still_reject_wrong_types() -> None:
    """The field is asserted to EXIST first (batch 6's lesson)."""
    assert "max_iterations" in config_facade.DmAgenticConfig.model_fields

    for value in ("not-a-number", None, [1]):
        with pytest.raises(ValueError):
            config_facade.DmAgenticConfig(max_iterations=value)


def test_mutable_defaults_are_not_shared_between_instances() -> None:
    """Every mutable-valued field, with the examined set pinned exactly."""
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

    Every other case builds models directly, so a move that broke YAML loading
    -- the way an operator actually supplies these values -- would pass them all.
    """
    dotted = MODEL_TO_PATH[name]
    section = dict(_walk(SystemConfig().model_dump(mode="json"), dotted))

    field, original = _perturbable_field(name, section)
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

    assert first.dm_agentic is not second.dm_agentic
    assert first.agentic_tools is not second.agentic_tools

    first.dm_agentic.max_iterations += 1

    assert (
        second.dm_agentic.max_iterations
        == EXPECTED_DUMPS["DmAgenticConfig"]["max_iterations"]
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_agentic_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_AGENTIC_SOURCE.read_text(encoding="utf-8"))
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


def test_the_selector_selects_broadly_for_an_agentic_model_change() -> None:
    selector = _load("_ad1270e2i_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/agentic.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    profiles = _load(
        "_ad1270e2i_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )

    scanned = [path.name for path in profiles._env_scan_paths(_SOURCE_ROOT)]

    assert "config.py" in scanned
    assert "agentic.py" in scanned
    assert profiles.env_reads_reaching_defaults(_SOURCE_ROOT)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
