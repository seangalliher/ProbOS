"""Tests for AD-476 v1 — Specialized Builders (Cognitive Division of Labor for SWE)."""

from __future__ import annotations

import pytest

from probos.cognitive.builder import SoftwareEngineerAgent
from probos.cognitive.builder_specialist import (
    SoftwareEngineerSpecialty,
    SpecialistRouter,
    SpecialtyMatchResult,
    score_path,
)
from probos.cognitive.builder_specialists import (
    SPECIALIST_CLASSES,
    BackendSWEAgent,
    DataSWEAgent,
    FrontendSWEAgent,
    InfrastructureSWEAgent,
    TestSWEAgent,
)
from probos.config import SoftwareEngineerSpecialistsConfig


# ----- Test 1: enum shape -----
def test_specialty_enum_has_six_values_with_string_form():
    """SoftwareEngineerSpecialty exposes 6 values; each value's ``.value`` is the
    lowercase string form used in config keys + log lines."""
    expected = {"general", "backend", "frontend", "test", "infrastructure", "data"}
    assert {s.value for s in SoftwareEngineerSpecialty} == expected
    assert SoftwareEngineerSpecialty.BACKEND.value == "backend"


# ----- Test 2: SpecialtyMatchResult is frozen + has to_dict -----
def test_specialty_match_result_frozen_and_to_dict_round_trips():
    r = SpecialtyMatchResult(
        specialty=SoftwareEngineerSpecialty.BACKEND, score=4, rationale="t",
    )
    assert r.to_dict() == {"specialty": "backend", "score": 4, "rationale": "t"}
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        r.score = 99  # type: ignore[misc]


# ----- Test 3: score_path resolves frontend (.tsx) -----
def test_score_path_frontend_tsx_scores_above_other_specialties():
    s = score_path("ui/src/components/AgentList.tsx")
    assert s[SoftwareEngineerSpecialty.FRONTEND] > s[SoftwareEngineerSpecialty.BACKEND]
    assert s[SoftwareEngineerSpecialty.FRONTEND] >= 5  # .tsx (3) + ui/src/ (3) ≥ 5 with overlap


# ----- Test 4: score_path resolves test (tests/ + test_*) -----
def test_score_path_test_directory_with_test_prefix_scores_test_specialty():
    s = score_path("tests/test_ad476_specialized_builders.py")
    assert s[SoftwareEngineerSpecialty.TEST] > 0
    # TEST should outscore BACKEND despite the .py suffix
    assert s[SoftwareEngineerSpecialty.TEST] > s[SoftwareEngineerSpecialty.BACKEND]


# ----- Test 5: score_path resolves infrastructure (Dockerfile) -----
def test_score_path_dockerfile_routes_to_infrastructure():
    s = score_path("Dockerfile")
    assert s[SoftwareEngineerSpecialty.INFRASTRUCTURE] >= 4


# ----- Test 6: score_path resolves data (.sql + migrations/) -----
def test_score_path_sql_migration_routes_to_data():
    s = score_path("migrations/001_initial.sql")
    assert s[SoftwareEngineerSpecialty.DATA] > s[SoftwareEngineerSpecialty.BACKEND]


# ----- Test 7: route_chunk picks frontend for a .tsx target -----
def test_route_chunk_frontend_tsx():
    from probos.cognitive.builder import ChunkSpec
    chunk = ChunkSpec(
        chunk_id="c1", description="add badge", target_file="ui/src/components/Badge.tsx",
        what_to_generate="React component",
    )
    result = SpecialistRouter().route_chunk(chunk)
    assert result.specialty is SoftwareEngineerSpecialty.FRONTEND
    assert result.score > 0
    assert "frontend" in result.rationale


# ----- Test 8: route_build_spec picks backend for a router target -----
def test_route_build_spec_backend_router():
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title="Add /api/specialty router",
        description="Wire new router",
        target_files=["src/probos/routers/specialty.py", "src/probos/api.py"],
        reference_files=[],
        test_files=[],
    )
    result = SpecialistRouter().route_build_spec(spec)
    assert result.specialty is SoftwareEngineerSpecialty.BACKEND
    assert result.score > 0


# ----- Test 9: route_build_spec falls back to GENERAL when no signal -----
def test_route_build_spec_general_fallback_when_no_signal():
    from probos.cognitive.builder import BuildSpec
    spec = BuildSpec(
        title="Edit a manual",
        description="Touch a doc",
        target_files=["docs/manual.md"],  # .md is not in any specialty's rule set
        reference_files=[],
        test_files=[],
    )
    result = SpecialistRouter().route_build_spec(spec)
    assert result.specialty is SoftwareEngineerSpecialty.GENERAL
    assert result.score == 0
    assert "general" in result.rationale


# ----- Test 10: each specialist subclass has the right specialty + agent_type -----
@pytest.mark.parametrize(
    "cls, expected_specialty, expected_agent_type",
    [
        (BackendSWEAgent, SoftwareEngineerSpecialty.BACKEND, "backend_swe"),
        (FrontendSWEAgent, SoftwareEngineerSpecialty.FRONTEND, "frontend_swe"),
        (TestSWEAgent, SoftwareEngineerSpecialty.TEST, "test_swe"),
        (InfrastructureSWEAgent, SoftwareEngineerSpecialty.INFRASTRUCTURE, "infrastructure_swe"),
        (DataSWEAgent, SoftwareEngineerSpecialty.DATA, "data_swe"),
    ],
)
def test_each_specialist_has_correct_specialty_and_agent_type(
    cls, expected_specialty, expected_agent_type,
):
    assert cls.specialty is expected_specialty
    assert cls.agent_type == expected_agent_type
    assert issubclass(cls, SoftwareEngineerAgent)


# ----- Test 11: each specialist's instructions extends the base output format -----
def test_specialist_instructions_distinct_from_base_and_include_output_format():
    base_instructions = SoftwareEngineerAgent.instructions
    seen = set()
    for cls in SPECIALIST_CLASSES:
        # Each must have its own non-trivial instructions string.
        assert cls.instructions, f"{cls.__name__} missing instructions"
        assert cls.instructions != base_instructions, f"{cls.__name__} not specialized"
        # The OUTPUT FORMAT block is shared.
        assert "OUTPUT FORMAT:" in cls.instructions
        seen.add(cls.instructions)
    # All five must be distinct from each other.
    assert len(seen) == len(SPECIALIST_CLASSES)


# ----- Test 12: SoftwareEngineerSpecialistsConfig defaults + validators -----
def test_specialists_config_defaults_and_validators():
    cfg = SoftwareEngineerSpecialistsConfig()
    assert cfg.enabled is False  # opt-in
    assert cfg.pool_size_per_specialty == 1
    assert cfg.model_tier_overrides == {
        "backend": "deep",
        "frontend": "standard",
        "test": "fast",
        "infrastructure": "standard",
        "data": "deep",
    }
    # Bad pool size rejected.
    with pytest.raises(Exception):
        SoftwareEngineerSpecialistsConfig(pool_size_per_specialty=0)
    # Bad tier rejected.
    with pytest.raises(Exception):
        SoftwareEngineerSpecialistsConfig(model_tier_overrides={"backend": "ultra"})


# ----- Test 13: BuildPipeline.execute_approved_build signature accepts specialty kwarg -----
def test_build_pipeline_execute_approved_build_signature_has_specialty_kwarg():
    import inspect
    from probos.build_pipeline import BuildPipeline
    sig = inspect.signature(BuildPipeline.execute_approved_build)
    assert "specialty" in sig.parameters
    p = sig.parameters["specialty"]
    assert p.default == "general"


# ----- Test 14: legacy execute_approved_build coroutine accepts specialty kwarg -----
def test_legacy_execute_approved_build_signature_has_specialty_kwarg():
    import inspect
    from probos.cognitive.builder import execute_approved_build
    sig = inspect.signature(execute_approved_build)
    assert "specialty" in sig.parameters
    assert sig.parameters["specialty"].default == "general"
