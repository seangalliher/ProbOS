# AD-521 v1: SWE/Build Pipeline Separation — Model A

**Status / Dependencies / Estimated tests**

- **Status:** AD-521 DECIDED (2026-03-29) at `decisions-era-4-evolution.md:1427-1467`. Wave 96 ships v1 implementation.
- **Dependencies:** AD-398 (Three-Tier Agent Architecture, COMPLETE), AD-452 (Agent Tier Licensing, COMPLETE), AD-302 (BuilderAgent creation, COMPLETE), AD-515 (runtime.py extraction, COMPLETE — establishes the service-injection pattern this AD reuses).
- **Estimated new tests:** **12** (all in `tests/test_ad521_swe_pipeline_separation.py`). Existing 16 test files importing from `probos.cognitive.builder` continue to pass unchanged via aliases and module-level re-exports.

## Problem

`src/probos/cognitive/builder.py` is a 117 KB / ~2900-line module that is BOTH:

1. **A sovereign crew agent** — `class BuilderAgent(CognitiveAgent)` at line 1690 with `agent_type = "builder"`, callsign "Scotty", standing-orders mapping `builder → engineering` (`cognitive/standing_orders.py:42`), `_handled_intents = {"build_code"}`, IntentDescriptor with `requires_consensus=True`.
2. **A pile of build pipeline functions** — `BuildSpec` / `BuildResult` / `BuildFailureReport` / `BuildBlueprint` / `ChunkSpec` dataclasses (lines 146-441), `classify_build_failure` (line 232), blueprint/chunk decomposition (lines 446-1185), transporter helpers (lines 1192-1295), the visiting-vs-native router (line 1251), `execute_approved_build(...)` (line 2512) plus its git/test/fix loop helpers, `_check_sealed_path`, `_run_targeted_tests`, `_run_tests`, `_build_fix_prompt`, `_validate_python`, `_parse_file_blocks`, `_PROJECT_ROOT`, `_SOURCE_ROOT`.

This conflates crew identity with tool capability. Per AD-521 (`decisions-era-4-evolution.md:1427-1467`):

> Architecture decision to cleanly separate the **crew SWE role** from the **build pipeline infrastructure**. Currently `BuilderAgent` (cognitive/builder.py) is a single class that is both a sovereign crew member (Scotty, with callsign, personality, standing orders) and the code generation pipeline (BuildSpec parsing, SEARCH/REPLACE application, test-gate). This conflates crew identity with tool capability.

AD-521 specifies **Model A**: SWE always in the chain. Architect → SWE (Scotty) → { Native Build Pipeline | Copilot | Claude Code }. Three-layer separation: SWE Crew (sovereign), Build Pipeline (infrastructure / Ship's Computer service), External Tools (visiting officers).

Implementation has been deferred since 2026-03-29 ("requires build prompt and builder execution"). v1 ships the structural separation now.

## Solution

Five sections, applied top-to-bottom:

1. New module `src/probos/build_pipeline.py` — `BuildPipeline` class (Ship's Computer service). Wraps the existing `execute_approved_build` coroutine as an instance method. Holds no agent identity. Constructor injection of `runtime`. Module lives at `src/probos/` top-level alongside `warm_boot.py`, `dream_adapter.py`, `agent_onboarding.py`, `self_mod_manager.py`, `ward_room_router.py` — the same tier as the AD-515 extracted services. **Does NOT live under `cognitive/`** because per AD-521, the pipeline is infrastructure, not cognition.
2. `src/probos/cognitive/builder.py` rename + shim — class `BuilderAgent` renamed to `SoftwareEngineerAgent` with `BuilderAgent = SoftwareEngineerAgent` module-level alias. Class docstring updated to reflect the SWE crew role (engineering judgment, quality gates, tool selection, output ownership). The module-level `execute_approved_build(...)` coroutine becomes a thin shim that constructs/uses a `BuildPipeline` and forwards.
3. `src/probos/runtime.py` wiring — `self.build_pipeline: BuildPipeline | None = None` declared in `__init__` alongside other Ship's Computer services, instantiated in `start()`.
4. `tests/test_ad521_swe_pipeline_separation.py` — 12 boundary tests covering BuildPipeline service shape, SoftwareEngineerAgent class identity, BuilderAgent alias preservation, runtime wiring, and crew-identity continuity.
5. Tracker updates — DECISIONS / era-4 / roadmap / PROGRESS / wave-plan reconciled.

**Crew identity continuity preserved:** `agent_type = "builder"`, callsign "Scotty", pool name `"builder"` (`runtime.py:697`), standing-orders mapping (`cognitive/standing_orders.py:42`), skill-framework `"builder"` key (`skill_framework.py:328`), config allow-list (`config.py:2511`), spawner registration, fleet organisation pool group (`startup/fleet_organization.py:94`), `_WARD_ROOM_CREW` (`crew_utils.py:15`), `agent_onboarding.py:611` allow-list — ALL UNCHANGED. The rename is class-only by explicit design.

## Section 1 — `src/probos/build_pipeline.py` (NEW FILE)

Create `src/probos/build_pipeline.py` with the following content:

```python
"""BuildPipeline — Ship's Computer service for build execution (AD-521).

Extracted from cognitive/builder.py as part of AD-521 SWE/Build Pipeline
Separation Model A. The pipeline is infrastructure (no agent identity);
the SoftwareEngineerAgent crew agent (formerly BuilderAgent) delegates
to this service for build execution.

Architecture (AD-521):

    Architect → SoftwareEngineerAgent (Scotty, crew tier)
                    ↓
                BuildPipeline (this module — infrastructure)
                    ↓
                { native execute_approved_build | visiting builder }

The pipeline is composable, runtime-injected, and shareable across
multiple SWE crew members for parallel workstreams.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.cognitive.builder import BuildResult, BuildSpec
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime


logger = logging.getLogger(__name__)


class BuildPipeline:
    """Ship's Computer service for executing approved build specifications.

    The pipeline owns no agent identity. It accepts file changes from a
    SWE crew agent (or any caller), writes them to disk under a git
    branch, runs targeted + full pytest gates with a fix-loop, and
    returns a structured BuildResult.

    Constructor injection (per AD-521 / copilot-instructions Engineering
    Principles): the runtime handle is passed at construction time.
    Optional pre-flight, llm_client, escalation_hook, and emit_event
    are accessed through the runtime via `getattr` defensive lookups
    (the runtime attributes are populated by `startup/finalize.py` and
    other startup modules; ordering between `BuildPipeline.__init__`
    and those startup hooks is therefore irrelevant).
    """

    def __init__(self, runtime: ProbOSRuntime | None = None) -> None:
        self._runtime = runtime

    async def execute_approved_build(
        self,
        file_changes: list[dict[str, Any]],
        spec: BuildSpec,
        work_dir: str,
        run_tests: bool = True,
        max_fix_attempts: int = 2,
        llm_client: BaseLLMClient | None = None,
        escalation_hook: Callable | None = None,
        builder_source: str = "native",
    ) -> BuildResult:
        """Execute an approved build (write files, run tests, create git branch).

        Delegates to the existing module-level coroutine in
        `cognitive/builder.py` for now; v1 of AD-521 is structural
        separation only. The behaviour, prompts, parsing, fix loop, and
        pre-flight gates are unchanged. Future ADs (AD-543–549, the SWE
        Tool Harness wave) will migrate the implementation into this
        class as instance methods.
        """
        # Local import avoids circular dependency at module load time:
        # cognitive/builder.py imports nothing from this module, but the
        # shim direction means we want to defer the import.
        from probos.cognitive.builder import (
            execute_approved_build as _legacy_execute_approved_build,
        )

        return await _legacy_execute_approved_build(
            file_changes=file_changes,
            spec=spec,
            work_dir=work_dir,
            run_tests=run_tests,
            max_fix_attempts=max_fix_attempts,
            llm_client=llm_client,
            escalation_hook=escalation_hook,
            builder_source=builder_source,
            runtime=self._runtime,
        )

    @staticmethod
    def parse_file_blocks(text: str) -> list[dict[str, Any]]:
        """Parse LLM-emitted ===FILE:===/===MODIFY:=== blocks into change dicts.

        Re-exposes the existing parser as a stable public method on the
        pipeline service. Existing callers using the
        `BuilderAgent._parse_file_blocks(...)` static method continue to
        work; new callers should prefer this method.
        """
        from probos.cognitive.builder import BuilderAgent

        return BuilderAgent._parse_file_blocks(text)
```

## Section 2 — `src/probos/cognitive/builder.py` rename + shim

### Section 2a — Class rename

Find the class declaration and update it.

```
===MODIFY: src/probos/cognitive/builder.py===
===SEARCH===
class BuilderAgent(CognitiveAgent):
    """Engineering agent that generates code from build specifications."""

    agent_type = "builder"
    tier = "domain"
    _handled_intents = {"build_code"}
===REPLACE===
class SoftwareEngineerAgent(CognitiveAgent):
    """SWE crew agent (Scotty) — engineering judgment, quality gates, tool delegation (AD-521).

    Per AD-521 SWE/Build Pipeline Separation Model A, this agent is
    the sovereign crew member that owns build output quality. It
    receives build specs from the Architect, applies engineering
    judgment, selects a tool (native BuildPipeline service, visiting
    Copilot builder, or future agentic-loop harness from AD-543–549),
    validates output against standing-orders quality gates, and
    reports up.

    Identity continuity: agent_type, callsign, pool name, and
    standing-orders mapping are preserved — the rename is class-only.
    `BuilderAgent` is kept as a module-level alias for back-compat
    (16 test files import the name; all keep working unchanged).
    """

    agent_type = "builder"
    tier = "domain"
    _handled_intents = {"build_code"}
===END REPLACE===
===END MODIFY===
```

### Section 2b — Add `BuilderAgent` back-compat alias

The alias must be at module level so `from probos.cognitive.builder import BuilderAgent` continues to resolve. Add it immediately after the class definition closes — Builder finds the end of the class by searching for the last static method or the `execute_approved_build` module-level coroutine that follows. The simplest stable anchor is the comment block before `execute_approved_build`.

```
===MODIFY: src/probos/cognitive/builder.py===
===SEARCH===
async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
===REPLACE===
# AD-521: Back-compat alias. Existing imports
# (`from probos.cognitive.builder import BuilderAgent`) continue to resolve.
# 16 test files use the BuilderAgent name; all keep working unchanged.
BuilderAgent = SoftwareEngineerAgent


async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
===END REPLACE===
===END MODIFY===
```

### Section 2c — Internal references to `BuilderAgent.<staticmethod>` (verification only)

The class body contains internal references like `BuilderAgent._build_file_outline(...)`, `BuilderAgent._parse_file_blocks(...)` (lines 522, 573, 777, 1095, 2260, 2282, 2710 per the verification footer). These resolve correctly via the alias because `BuilderAgent is SoftwareEngineerAgent` at module load time. **No changes needed** — the alias makes these references continue to work. Builder verifies after Section 2a + 2b that `python -c "from probos.cognitive.builder import BuilderAgent, SoftwareEngineerAgent; assert BuilderAgent is SoftwareEngineerAgent"` succeeds.

## Section 3 — `src/probos/runtime.py` wiring

### Section 3a — Declare attribute in `__init__`

Find the existing service-attribute block at runtime.py:567-569 and add the `build_pipeline` declaration.

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
        self.warm_boot: WarmBootService | None = None
===REPLACE===
        self.warm_boot: WarmBootService | None = None
        # AD-521: BuildPipeline Ship's Computer service. Owns no agent
        # identity; SoftwareEngineerAgent (Scotty) delegates to this
        # service for build execution. Constructor-injected with the
        # runtime handle so it can read pre_flight_runner / emit_event
        # / llm_client via defensive `getattr` lookups at invocation
        # time (the runtime attributes are populated by
        # startup/finalize.py and other startup modules).
        self.build_pipeline: BuildPipeline | None = None
===END REPLACE===
===END MODIFY===
```

### Section 3b — Add the `BuildPipeline` import at the top of `runtime.py`

The existing service classes are imported at the top of `runtime.py`. Add `BuildPipeline` to the same import area. Builder finds an existing service import line (e.g. `from probos.warm_boot import WarmBootService`) and adds the new import after it.

```
===MODIFY: src/probos/runtime.py===
===SEARCH===
from probos.warm_boot import WarmBootService
===REPLACE===
from probos.build_pipeline import BuildPipeline
from probos.warm_boot import WarmBootService
===END REPLACE===
===END MODIFY===
```

(If the `from probos.warm_boot import WarmBootService` line is part of a multi-line block or has different surrounding context at HEAD, Builder adapts the SEARCH context to be unique. The intent is: add the `BuildPipeline` import alongside the other Ship's Computer service imports.)

### Section 3c — Instantiate in `start()`

Find the existing service-instantiation block in `runtime.start()` (the AD-515 extracted services are instantiated there). The `BuildPipeline` instantiation has no ordering constraint vs `pre_flight_runner` because `BuildPipeline.execute_approved_build` reads the runtime attribute via `getattr` at invocation time (same pattern as the current `cognitive/builder.py:2548` lookup).

Builder locates the AD-515 service-instantiation site (search for `WarmBootService(` or `DreamAdapter(` in `runtime.py`) and adds the line:

```python
self.build_pipeline = BuildPipeline(runtime=self)
```

immediately after one of the existing `self.<service> = <Service>(...)` lines. The exact SEARCH anchor depends on HEAD's surrounding context; if the AD-515 services are instantiated as a block, Builder adds the new line at the end of the block. If the SEARCH block does not match cleanly at HEAD, Builder hard-stops per W96-1 and surfaces back to Architect.

## Section 4 — `tests/test_ad521_swe_pipeline_separation.py` (NEW FILE)

Create `tests/test_ad521_swe_pipeline_separation.py` with the 12 tests below. All tests use `_FakeRuntime` / `_FakeAgent` stub patterns from `tests/conftest.py` where needed. No real LLM calls, no real git, no real disk writes outside `tmp_path`.

```python
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

import asyncio
import inspect

import pytest


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
    from probos.cognitive.standing_orders import _DEPARTMENT_BY_AGENT_TYPE
    from probos.crew_utils import _WARD_ROOM_CREW

    # agent_type unchanged
    assert SoftwareEngineerAgent.agent_type == "builder"
    # standing-orders mapping unchanged
    assert _DEPARTMENT_BY_AGENT_TYPE.get("builder") == "engineering"
    # ward room crew membership unchanged
    assert "builder" in _WARD_ROOM_CREW
```

**Note for test 12 (`test_class_rename_preserves_role_keys`):** Builder verifies the actual symbol names exported by `cognitive/standing_orders.py` and `crew_utils.py` at HEAD — `_DEPARTMENT_BY_AGENT_TYPE` is the canonical name in `standing_orders.py:42-44` per the verify-first footer; if HEAD uses a different symbol name, Builder adapts the import. The intent of the test is unchanged: confirm role keys survive.

## Section 5 — Tracker updates

### Section 5a — `decisions-era-4-evolution.md` AD-521 status flip

```
===MODIFY: decisions-era-4-evolution.md===
===SEARCH===
**Status:** **DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.
===REPLACE===
**Status:** **v1 COMPLETE** (2026-05-07, Wave 96). Structural separation shipped: `BuildPipeline` extracted as Ship's Computer service at `src/probos/build_pipeline.py`; `BuilderAgent` class renamed to `SoftwareEngineerAgent` with module-level alias for back-compat (16 test files unchanged); `runtime.build_pipeline` wired via constructor injection. Crew identity continuity preserved (agent_type `builder`, callsign Scotty, pool name `builder`, standing-orders mapping, skill-framework key — all unchanged). The agentic-loop tooling (AD-543–549, GH #13) is the next wave and depends on this v1 as its prerequisite. The closed-source SWE-tier overlay slots in via the AD-452 class-extension plug-in point (out-of-repo, governed by the placeholder-tier licensing AD that lives in the private commercial-repo path token surface). Issue #96 closed.
===END REPLACE===
===END MODIFY===
```

### Section 5b — `docs/development/roadmap.md` AD-521 bullet flip

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
**AD-521: SWE/Build Pipeline Separation — Model A** *(decided, OSS + Commercial, depends: AD-398, AD-452)* — Clean separation of the crew SWE role from the build pipeline infrastructure. Currently `BuilderAgent` (cognitive/builder.py) conflates sovereign crew identity with mechanical code generation. Model A puts the SWE always in the chain: Architect → SWE → coding tools.
===REPLACE===
**AD-521: SWE/Build Pipeline Separation — Model A** *(v1 complete 2026-05-07 Wave 96, OSS + Commercial, depends: AD-398, AD-452)* — Clean separation of the crew SWE role from the build pipeline infrastructure. Previously `BuilderAgent` (cognitive/builder.py) conflated sovereign crew identity with mechanical code generation. v1 ships the structural separation: `BuildPipeline` extracted as Ship's Computer service at `src/probos/build_pipeline.py`; `BuilderAgent` class renamed to `SoftwareEngineerAgent` with module-level back-compat alias; `runtime.build_pipeline` wired via constructor injection; crew identity continuity preserved (agent_type, callsign, pool name, standing-orders mapping, skill-framework key all unchanged). The agentic-loop tooling (AD-543–549, GH #13) is the next wave and depends on AD-521 v1 as its prerequisite. Model A puts the SWE always in the chain: Architect → SWE → { native BuildPipeline | visiting Copilot | future agentic-loop harness }.
===END REPLACE===
===END MODIFY===
```

### Section 5c — `PROGRESS.md` ADD new status note

`PROGRESS.md` has zero AD-521 matches at HEAD (verified). W96 INSERTS a new status note after the `AD-652 REALISED` line at PROGRESS.md:331.

```
===MODIFY: PROGRESS.md===
===SEARCH===
AD-652 REALISED (Wave 95 close, 2026-05-07). Cognitive Code-Switching — unified pipeline with contextual modulation. All six principles delivered across shipped children: AD-632 (unified pipeline substrate), AD-649 (channel→register inference, 5 registers), AD-639 (chain trust band tenor weighting), AD-650 (analytical_reasoning depth field), AD-651 (StepInstructionRouter billet overlays), AD-651a (proposal + duty report compose billets), AD-647/AD-647c (process chains — variable depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting, trust-gated). Downstream consumers AD-655/AD-656/AD-657/AD-658/AD-659/AD-660 all complete. Tracker reconciliation only — no code, no tests. Research: cognitive-code-switching-research.md. Issue #302 closed.
===REPLACE===
AD-652 REALISED (Wave 95 close, 2026-05-07). Cognitive Code-Switching — unified pipeline with contextual modulation. All six principles delivered across shipped children: AD-632 (unified pipeline substrate), AD-649 (channel→register inference, 5 registers), AD-639 (chain trust band tenor weighting), AD-650 (analytical_reasoning depth field), AD-651 (StepInstructionRouter billet overlays), AD-651a (proposal + duty report compose billets), AD-647/AD-647c (process chains — variable depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting, trust-gated). Downstream consumers AD-655/AD-656/AD-657/AD-658/AD-659/AD-660 all complete. Tracker reconciliation only — no code, no tests. Research: cognitive-code-switching-research.md. Issue #302 closed.
AD-521 v1 COMPLETE (Wave 96, 2026-05-07). SWE/Build Pipeline Separation — Model A. `BuildPipeline` Ship's Computer service extracted to `src/probos/build_pipeline.py`; `BuilderAgent` class renamed to `SoftwareEngineerAgent` with module-level back-compat alias (16 test files unchanged); `runtime.build_pipeline` wired via constructor injection. Crew identity continuity preserved (agent_type `builder`, callsign Scotty, pool name `builder`, standing-orders mapping, skill-framework key — all unchanged). +12 boundary tests in test_ad521_swe_pipeline_separation.py. The agentic-loop tooling (AD-543–549, GH #13) is the next wave. Issue #96 closed.
===END REPLACE===
===END MODIFY===
```

### Section 5d — `prompts/wave-plan.yaml` W96 entry

Append after the W95 tail. Builder finds the closing `gh issue close 302` line of the W95 notes block and adds the W96 entry below it.

```
===MODIFY: prompts/wave-plan.yaml===
===SEARCH===
      Pre-commit hook runs naturally on commit. Full pytest gate
      belt-and-braces (expected 12130 passed). Commit with "AD-652:
      Cognitive Code-Switching umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 302
      with the canonical paragraph in Section 5 of the per-AD prompt.
===REPLACE===
      Pre-commit hook runs naturally on commit. Full pytest gate
      belt-and-braces (expected 12130 passed). Commit with "AD-652:
      Cognitive Code-Switching umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 302
      with the canonical paragraph in Section 5 of the per-AD prompt.
  - id: "96"
    title: "AD-521 v1 SWE/Build Pipeline Separation — Model A"
    kind: single
    depends_on: ["95"]
    dispatch_prompt: "prompts/WAVE-96-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-521-swe-build-pipeline-separation-v1.md"
    builder_required: true
    issues_to_close: [96]
    status: pending
    notes: |
      Source-modifying v1 of AD-521 (DECIDED 2026-03-29 at
      decisions-era-4-evolution.md:1427-1467). Five sections applied
      top-to-bottom: (1) new module src/probos/build_pipeline.py
      (~180 lines, BuildPipeline Ship's Computer service with
      execute_approved_build + parse_file_blocks instance methods,
      constructor injection of runtime, defensive getattr lookups for
      pre_flight_runner / emit_event / llm_client at invocation time);
      (2) cognitive/builder.py rename — class BuilderAgent renamed to
      SoftwareEngineerAgent, module-level BuilderAgent =
      SoftwareEngineerAgent alias preserves the 16 test files importing
      the old name, class docstring updated to reflect SWE crew role;
      (3) runtime.py wiring — self.build_pipeline declared in __init__
      alongside warm_boot / dream_adapter (runtime.py:567-569), the
      BuildPipeline import added alongside other Ship's Computer service
      imports, instantiation in start() with no ordering constraint vs
      pre_flight_runner because BuildPipeline reads the runtime
      attribute via getattr at invocation time (same pattern as the
      current cognitive/builder.py:2548 lookup); (4) new test file
      tests/test_ad521_swe_pipeline_separation.py with 12 boundary
      tests across BuildPipeline service shape (4), SoftwareEngineerAgent
      class identity (3), BuilderAgent alias (1), module-level shim (1),
      runtime wiring (2), crew identity continuity (1); (5) tracker
      reconciliation — decisions-era-4-evolution.md:1467 status flip
      from DECIDED to v1 COMPLETE, docs/development/roadmap.md:6628
      bullet flip from decided to v1 complete with realisation summary,
      PROGRESS.md INSERT new status note after AD-652 line at :331
      (zero existing AD-521 matches at HEAD), wave-plan.yaml W96 entry
      appended.

      Crew identity continuity preserved: agent_type "builder" unchanged
      (16+ allow-list / spawner / standing-orders / skill-framework
      sites untouched), callsign Scotty unchanged, pool name "builder"
      unchanged at runtime.py:697, standing-orders mapping
      builder→engineering unchanged at cognitive/standing_orders.py:42,
      _WARD_ROOM_CREW "builder" entry unchanged at crew_utils.py:15,
      fleet pool group "builder" unchanged at startup/fleet_organization
      .py:94, skill_framework "builder" key unchanged at
      skill_framework.py:328, config allow-list unchanged at
      config.py:2511, agent_onboarding allow-list unchanged at
      agent_onboarding.py:611. The rename is class-only by explicit
      design — agent_type / pool name / standing-orders mapping are
      role keys, not class names, and churning them is a separate AD.

      The CodeReviewAgent (Inspector role per AD-521) already exists at
      cognitive/code_reviewer.py and is invoked from cognitive/builder
      .py:2654-2674. v1 preserves the existing wiring through the
      refactor — no Inspector changes.

      The agentic-loop tooling (AD-543 ToolCall protocol + ToolExecutor,
      AD-544 native tool suite, AD-545 agentic loop, AD-546
      BuildPipeline integration, AD-547 session compaction, AD-548
      trust-tier permissions, AD-549 visiting-builder migration) is the
      next wave (GH #13). AD-521 v1 unblocks AD-546 which depends on
      it explicitly per docs/development/roadmap.md:6768.

      The closed-source SWE-tier overlay (AD-452 class-extension
      plug-in point) is out-of-repo. v1 ships zero closed-source
      content — the OSS class structure is the architectural surface
      and the overlay slots in via the placeholder-tier licensing AD
      that lives in the private commercial-repo path token surface.
      Banned-pattern audit on this dispatch + per-AD prompt + this
      notes block: zero hits across all 11 patterns (the e-word + tier
      phrase, the private commercial-repo path token, the e-word
      overlay phrase, the e-word-prefixed repo token, monthly-price
      regex, per-month abbreviation regex, rev-proj phrase, the
      recurring-revenue acronym, outcome-style pricing phrase, the
      GTM-pattern phrase, the patterns-to-absorb phrase). Pre-commit
      hook simulation Select-String -SimpleMatch returns zero per
      pattern across all artefacts.

      4 review passes recorded: P1 (initial draft against HEAD 08bfc7f
      — five-section structure, 12-test plan, AD-521 spec mapping
      verified against decisions-era-4-evolution.md:1427-1467); P2
      (verify-first sweep — caught two phantom claims: PROGRESS.md
      had zero AD-521 matches so Section 5c is INSERT not flip,
      pre_flight_runner is set in startup/finalize.py:1644 not
      runtime.__init__ so getattr defensive pattern is canonical and
      no ordering constraint matters; both fixed); P3 (reframe table
      — build v1 not defer, AD-543-549 deps tracked under GH #13,
      Captain rule satisfied non-vacuously by AD-546 forcing
      function); P4 (banned-pattern audit + SEARCH/REPLACE block
      uniqueness check across 6 MODIFY blocks; AD numbering verified
      AD-696 highest no collision; the 16-test-file import path
      coverage cross-checked).

      Builder execution: read prompt top-to-bottom, apply 6
      SEARCH/REPLACE pairs across 6 MODIFY blocks plus the 2 new file
      creates (build_pipeline.py + test_ad521_swe_pipeline_separation
      .py). Verify git diff --stat shows 4 modified trackers (DECISIONS
      era-4, roadmap.md, PROGRESS.md, wave-plan.yaml) plus 1 modified
      runtime.py plus 1 modified cognitive/builder.py plus 2 new
      files plus this prompt + dispatch (which Builder will archive
      after commit). Pre-commit hook runs naturally on commit. Full
      pytest gate (expected ≥12142 passed; minimum gate is +12).
      Commit with "AD-521 v1: SWE/Build Pipeline Separation — Model A
      (extract BuildPipeline service, rename BuilderAgent →
      SoftwareEngineerAgent + alias, runtime wiring, +12 tests)".
      Archive both prompts. gh issue close 96 with the canonical
      paragraph in Section 6 of this per-AD prompt.
===END REPLACE===
===END MODIFY===
```

## Section 6 — Issue close paragraph (canonical)

`gh issue close 96 -c "..."` body:

> Closed by Wave 96. AD-521 v1 ships the structural SWE/Build Pipeline separation specified in the 2026-03-29 decision (decisions-era-4-evolution.md:1427-1467): `BuildPipeline` extracted as a Ship's Computer service at src/probos/build_pipeline.py with constructor injection of the runtime; `BuilderAgent` class renamed to `SoftwareEngineerAgent` with a module-level back-compat alias preserving all 16 test-file import paths; `runtime.build_pipeline` wired alongside the AD-515 extracted services; crew identity continuity preserved (agent_type `builder`, callsign Scotty, pool name `builder`, standing-orders mapping, skill-framework key — all role keys unchanged by explicit design). +12 boundary tests in tests/test_ad521_swe_pipeline_separation.py covering service shape, class identity, alias, shim, runtime wiring, and role-key continuity. The agentic-loop tooling (AD-543–549, GH #13) is the next wave and depends on this v1 as its prerequisite per docs/development/roadmap.md:6768.

## What This Does NOT Change

- **Behaviour:** zero. Same LLM prompts, same SEARCH/REPLACE parser, same fix loop, same pre-flight gates, same git/test orchestration. Pure structural refactor.
- **`agent_type`, callsign, pool name, standing-orders mapping, skill-framework key, fleet pool group, `_WARD_ROOM_CREW`, config allow-list, agent_onboarding allow-list:** all unchanged.
- **Module-level imports** from `probos.cognitive.builder` (`BuilderAgent`, `BuildSpec`, `BuildResult`, `BuildFailureReport`, `_should_use_visiting_builder`, `_check_sealed_path`, `_PROJECT_ROOT`, `_SOURCE_ROOT`, `execute_approved_build`): all preserved as module-level re-exports or actual definitions in `cognitive/builder.py`.
- **`build_dispatcher.py:18`** (`from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build`) and **`routers/build.py:382`** (`from probos.cognitive.builder import execute_approved_build`): unchanged.
- **`CopilotBuilderAdapter`** (`cognitive/copilot_adapter.py`): unchanged. The visiting-builder coexistence model is preserved.
- **`CodeReviewAgent`** (Inspector role): unchanged. Existing invocation site at `cognitive/builder.py:2654-2674` is preserved through the refactor.
- **Standing orders, quality gates, ward-room behaviour, ChromaDB schemas, episodic memory, Hebbian routing, trust network, federation:** all untouched.

## Tracking

- `decisions-era-4-evolution.md:1467` — status footer flipped (Section 5a)
- `docs/development/roadmap.md:6628` — bullet status flipped + realisation summary (Section 5b)
- `PROGRESS.md` — new status note INSERTED after the AD-652 line at :331 (Section 5c)
- `prompts/wave-plan.yaml` — W96 entry appended after W95 tail (Section 5d)

## Acceptance Criteria

- All 6 MODIFY blocks apply cleanly. SEARCH anchors match exactly at HEAD `08bfc7f`. If any anchor drifts, Builder hard-stops per W96-1 and surfaces back.
- Both new files (`src/probos/build_pipeline.py`, `tests/test_ad521_swe_pipeline_separation.py`) parse cleanly via `ast.parse`.
- `python -c "from probos.cognitive.builder import BuilderAgent, SoftwareEngineerAgent; assert BuilderAgent is SoftwareEngineerAgent"` succeeds.
- `python -c "from probos.build_pipeline import BuildPipeline; print(BuildPipeline)"` succeeds.
- All 12 new tests in `tests/test_ad521_swe_pipeline_separation.py` pass.
- Targeted pytest gate on the 16 existing import-path test files (`test_builder_agent.py`, `test_builder_api.py`, `test_builder_guardrails.py`, `test_build_dispatcher.py`, `test_build_queue.py`, `test_architect_agent.py`, `test_dispatch_wiring.py`, `test_copilot_adapter.py`, `test_codebase_skill.py`, `test_ad398_crew_identity.py`, `test_ad481_extensions.py`) passes with zero regressions.
- Full pytest gate `.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile` returns **≥12142 passed** (baseline 12130 + 12 new). Any other count means regression — Builder hard-stops per W96-2.
- Pre-commit hook runs cleanly on commit. Banned-pattern scan returns zero hits.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-07, HEAD `08bfc7f`)

- `git rev-parse HEAD` → `08bfc7f`
- `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern 'AD-(\d{3})' -AllMatches | … Measure-Object -Maximum` → max 696 (no AD-521 collision)
- `grep -n "## AD-521" decisions-era-4-evolution.md` → `1427: ## AD-521: SWE/Build Pipeline Separation — Model A (2026-03-29)`
- `grep -n "Status:.*DECIDED" decisions-era-4-evolution.md | grep AD-521` → `1467: **Status:** **DECIDED** (2026-03-29). Architecture approved. Implementation deferred — requires build prompt and builder execution.`
- `grep -n "AD-521:" docs/development/roadmap.md` → `6628: **AD-521: SWE/Build Pipeline Separation — Model A** *(decided, OSS + Commercial, depends: AD-398, AD-452)* — Clean separation of the crew SWE role from the build pipeline infrastructure.`
- `grep -n "AD-521" PROGRESS.md` → zero hits (W96 INSERT, not flip)
- `grep -n "class BuilderAgent" src/probos/cognitive/builder.py` → `1690: class BuilderAgent(CognitiveAgent):`
- `grep -n "async def execute_approved_build" src/probos/cognitive/builder.py` → `2512: async def execute_approved_build(`
- `grep -n "self.warm_boot" src/probos/runtime.py` → `567: self.warm_boot: WarmBootService | None = None`
- `grep -n "self.spawner.register_template..builder" src/probos/runtime.py` → `697: self.spawner.register_template("builder", BuilderAgent)` (unchanged through alias)
- `grep -n "pre_flight_runner" src/probos/cognitive/builder.py` → `2548: pre_flight = getattr(runtime, "pre_flight_runner", None) if runtime is not None else None` (canonical defensive pattern preserved)
- `grep -n "runtime.pre_flight_runner =" src/probos/startup/finalize.py` → `1644: runtime.pre_flight_runner = PreFlightRunner(...)` (set in startup/finalize.py, NOT in runtime.__init__ — confirms ordering between BuildPipeline init and pre_flight_runner init is irrelevant because BuildPipeline reads the attribute via getattr at execute time)
- `grep -n "_DEPARTMENT_BY_AGENT_TYPE\|\"builder\":" src/probos/cognitive/standing_orders.py` → `42: "builder": "engineering",` (canonical mapping preserved by class-only rename)
- `grep -n "\"builder\"" src/probos/crew_utils.py` → `15: "builder",  # Scotty — SWE officer, uses build pipeline as tool` (`_WARD_ROOM_CREW` membership preserved)
- `findstr /S /I /M "BuilderAgent\|execute_approved_build" tests\*.py` → 16 test files import these names; all preserved through alias + module-level shim
- `findstr /S /I /M "AD-521" tests\*.py` → zero existing test files (test_ad521_swe_pipeline_separation.py is the new file W96 introduces)
- `git status` → clean working tree at HEAD `08bfc7f`
- `.venv\Scripts\pytest.exe --collect-only -q tests/` → 12130 tests collected (per Captain reference)
