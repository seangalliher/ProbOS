"""AD-521: SWE/Build Pipeline Separation — Model A.

12 boundary tests covering:
- BuildPipeline Ship's Computer service shape (4 tests)
- SoftwareEngineerAgent crew class identity (3 tests)
- BuilderAgent back-compat alias (1 test)
- Module-level execute_approved_build shim preserved (1 test)
- Runtime wiring (2 tests)
- Crew identity continuity through the rename (1 test)
"""
from __future__ import annotations

import inspect


# --- BuildPipeline service shape -------------------------------------------

def test_build_pipeline_class_exists_at_top_level():
    """BuildPipeline lives at src/probos/build_pipeline.py — Ship's Computer
    tier, NOT under cognitive/. Per AD-521 the pipeline is infrastructure,
    not cognition.
    """
    from probos.build_pipeline import BuildPipeline

    assert BuildPipeline.__module__ == "probos.build_pipeline"


def test_build_pipeline_constructor_accepts_runtime():
    """BuildPipeline() accepts an optional runtime= kwarg for ergonomic unit
    tests; production wiring passes runtime=self from runtime.start().
    """
    from probos.build_pipeline import BuildPipeline

    pipeline_no_runtime = BuildPipeline()
    assert pipeline_no_runtime is not None

    class _FakeRuntime:
        pass

    pipeline_with_runtime = BuildPipeline(runtime=_FakeRuntime())
    assert pipeline_with_runtime is not None


def test_build_pipeline_execute_approved_build_signature():
    """BuildPipeline.execute_approved_build is an async method whose
    parameter list mirrors the existing module-level coroutine.
    """
    from probos.build_pipeline import BuildPipeline

    method = BuildPipeline.execute_approved_build
    assert inspect.iscoroutinefunction(method)

    sig = inspect.signature(method)
    expected_params = {
        "self", "file_changes", "spec", "work_dir", "run_tests",
        "max_fix_attempts", "llm_client", "escalation_hook",
        "builder_source",
    }
    assert expected_params <= set(sig.parameters)


def test_build_pipeline_parse_file_blocks_signature():
    """BuildPipeline.parse_file_blocks is callable and returns a list."""
    from probos.build_pipeline import BuildPipeline

    # Empty input should return an empty list, not raise.
    result = BuildPipeline.parse_file_blocks("")
    assert isinstance(result, list)


# --- SoftwareEngineerAgent crew class identity -----------------------------

def test_software_engineer_agent_class_exists():
    """SoftwareEngineerAgent is the canonical class name post-AD-521."""
    from probos.cognitive.builder import SoftwareEngineerAgent
    from probos.cognitive.cognitive_agent import CognitiveAgent

    assert issubclass(SoftwareEngineerAgent, CognitiveAgent)
    assert SoftwareEngineerAgent.agent_type == "builder"
    assert SoftwareEngineerAgent.tier == "domain"


def test_software_engineer_agent_handles_build_code_intent():
    """build_code intent ownership preserved through the rename;
    requires_consensus=True preserved.
    """
    from probos.cognitive.builder import SoftwareEngineerAgent

    assert SoftwareEngineerAgent._handled_intents == {"build_code"}

    descriptors = list(SoftwareEngineerAgent.intent_descriptors)
    build_code_descriptor = next(
        (d for d in descriptors if d.name == "build_code"), None,
    )
    assert build_code_descriptor is not None
    assert build_code_descriptor.requires_consensus is True
    assert build_code_descriptor.tier == "domain"


def test_software_engineer_agent_resolves_deep_tier():
    """Crew judgment for code generation runs on the deep-tier LLM."""
    from probos.cognitive.builder import SoftwareEngineerAgent

    # _resolve_tier is the existing override; preserved through rename.
    assert SoftwareEngineerAgent._resolve_tier(SoftwareEngineerAgent) == "deep"


# --- BuilderAgent alias preservation ---------------------------------------

def test_builder_agent_alias_is_software_engineer_agent():
    """`from probos.cognitive.builder import BuilderAgent` continues to
    resolve; the alias is the same class object as SoftwareEngineerAgent.
    16 existing test files depend on this.
    """
    from probos.cognitive.builder import BuilderAgent, SoftwareEngineerAgent

    assert BuilderAgent is SoftwareEngineerAgent


# --- Module-level shim preserved -------------------------------------------

def test_module_level_execute_approved_build_shim_preserved():
    """The module-level coroutine continues to be importable from its
    historical path. Existing callers in build_dispatcher.py:18 and
    routers/build.py:382 keep working unchanged.
    """
    from probos.cognitive.builder import execute_approved_build

    assert inspect.iscoroutinefunction(execute_approved_build)


# --- Runtime wiring --------------------------------------------------------

def test_runtime_declares_build_pipeline_attribute():
    """ProbOSRuntime.__init__ declares self.build_pipeline as a class
    attribute alongside the other Ship's Computer services.
    """
    from probos.runtime import ProbOSRuntime

    # Inspect __init__ source for the declaration. We do not instantiate
    # the runtime here (heavy fixture); we verify via source presence.
    src = inspect.getsource(ProbOSRuntime.__init__)
    assert "self.build_pipeline" in src
    assert "BuildPipeline" in src


def test_runtime_build_pipeline_instantiated_in_start():
    """runtime.start() wires self.build_pipeline = BuildPipeline(runtime=self).

    We verify by inspecting the start() source rather than running a full
    runtime boot (heavy fixture). A separate integration test lives in
    test_runtime_lifecycle.py if/when the harness wave needs it.
    """
    from probos.runtime import ProbOSRuntime

    src = inspect.getsource(ProbOSRuntime.start)
    assert "self.build_pipeline" in src
    assert "BuildPipeline(" in src


# --- Crew identity continuity through the rename ---------------------------

def test_class_rename_preserves_role_keys():
    """The rename is class-only. Pool name `builder`, agent_type `builder`,
    standing-orders mapping `builder → engineering`, skill-framework
    `builder` key, fleet pool group `builder`, _WARD_ROOM_CREW `builder`
    are all preserved.
    """
    from probos.cognitive.builder import SoftwareEngineerAgent
    from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
    from probos.crew_utils import _WARD_ROOM_CREW

    # agent_type unchanged
    assert SoftwareEngineerAgent.agent_type == "builder"
    # standing-orders mapping unchanged
    assert _AGENT_DEPARTMENTS.get("builder") == "engineering"
    # ward room crew membership unchanged
    assert "builder" in _WARD_ROOM_CREW
