# AD-722e — Deterministic structured self-projection v1 (Wave 154)

**GH:** [#571](https://github.com/seangalliher/ProbOS/issues/571). **Status:** Buildable.

**Hard prerequisite: AD-727 (#585) must land first.** This prompt MUST make the AD-727 safety_constraints tests pass.

## Architectural reframe (Captain ruling 2026-05-10)

AD-722e v1 ships as **deterministic structured projection** from the same source-of-truth that drives the renderer (DSL + AvatarTelemetrySnapshot). **Zero vision-LLM calls.** No browser-side capture. No new HTTP endpoint. The function reads existing in-process state and returns a dataclass.

This eliminates Category B (security harm) at the architectural level — no pixels enter the loop.

## Scope

### 1. New module `src/probos/cognitive/self_perception.py`

```python
"""AD-722e: deterministic structured self-perception.

Reads the same source-of-truth that drives the avatar renderer
(AppearanceProfile.dsl + AvatarTelemetrySnapshot) and emits a
structured ``SelfPerceptionProjection`` for use in INTEROCEPTION
sensorium blocks and (via AD-722a-1 future work) divergence detection.

v1 invariants (enforced by tests/test_ad727_safety_constraints.py):
- No vision-LLM calls.
- No browser-side capture.
- Function takes self.id as the only agent parameter — comparative
  perception is a separate AD.
- No trust/Hebbian mutations from this path — perception is
  read-only w.r.t. governance state (AD-727 hard rule #1).
- Emits pipeline_version so changes to renderer config surface
  to the agent as observations, not silent self-mutations
  (AD-727 hard rule #2).
"""
```

Exports:

- `@dataclass(frozen=True) SelfPerceptionProjection` with fields:
  - `agent_id: str`
  - `timestamp: float`
  - `pipeline_version: str` (read from a new module-level constant `PIPELINE_VERSION = "1.0.0"`)
  - `dsl_body_type: str`, `dsl_hair_style: str`, `dsl_outfit_style: str`, `dsl_primary_color: str` (from `DslSummarySnapshot` at [avatars/telemetry.py:322](src/probos/avatars/telemetry.py#L322))
  - `working_state: str` (from `AgentSignalsSnapshot.working_state` at [avatars/telemetry.py:280](src/probos/avatars/telemetry.py#L280) — **verified class name, do NOT use `AvatarSignals`**; accessed via `snap.current_signals.working_state` per the canonical pattern in [cognitive_agent.py:3107](src/probos/cognitive/cognitive_agent.py#L3107))
  - `expression_resting: str | None` (source is `AvatarTelemetrySnapshot.expression_resting: str | None` at [avatars/telemetry.py:365](src/probos/avatars/telemetry.py#L365) — preserve the Optional)
  - `mouth_active: bool`
  - `modulation_rate_factor: float | None`
  - `modulation_pitch_factor: float | None`

- `async def project_self_perception(self_id: str, runtime: Any) -> SelfPerceptionProjection | None`
  - Read existing `AvatarTelemetrySnapshot` via `probos.avatars.telemetry.build_telemetry_snapshot(self_id, runtime)`. If telemetry is unavailable or disabled, return `None`. Tier-2 log-and-degrade.
  - Construct `SelfPerceptionProjection` from the snapshot.
  - **Must NOT** import or call anything from `llm_client`, `vision_dispatch`, or any rendering/capture module.

- Also add to `src/probos/types.py` next to other Sensorium types: declare `SelfPerceptionProjection` there OR re-export from self_perception.py — Builder picks the consistent location with existing patterns. **Verify** by grepping how `AvatarTelemetrySnapshot` is exported.

### 2. Wire into `CognitiveAgent._build_avatar_self_observation`

In [src/probos/cognitive/cognitive_agent.py](src/probos/cognitive/cognitive_agent.py) `_build_avatar_self_observation` (line ~3075):

Currently builds INTEROCEPTION text from `self._last_self_avatar_snap` (AvatarTelemetrySnapshot). Extend to call `project_self_perception` and append a `pipeline_version: <version>` line to the rendered block. The existing text format stays; only one new line is added.

Feature-flagged behind `runtime.config.avatar_telemetry.inject_into_agent_context` (existing flag). No new config flag.

### 3. Out of scope (FORWARD MARKERS — file new AD + GH issue at wave close)

- **AD-722e-2: Vision-LLM divergence verification.** Per AD-727 hard rule #4, future visual extension MUST run against backend-server-side render, never browser canvas. File new AD + GH issue at wave close.
- **AD-722e-3: Cross-crew visual perception.** Per AD-727 hard rule #7. Existing AD-729 (#587) family covers this; cite at close.
- **AD-722e-4: Aesthetic-preference proposals.** Per AD-727 hard rule #6. Existing AD-721d covers DSL approval; this would extend to "I prefer" semantics. File new AD + GH issue at wave close.

## Files

- `src/probos/cognitive/self_perception.py` (new, ~120 lines)
- `src/probos/cognitive/cognitive_agent.py` (one-line additive change in `_build_avatar_self_observation`)
- `src/probos/types.py` (if SelfPerceptionProjection lives there)
- `tests/test_ad722e_self_perception.py` (new, 6 tests)

## Tests (≥6)

1. `test_projection_returns_dataclass_with_pipeline_version` — invoke `project_self_perception` against a stub runtime with a populated telemetry snapshot; assert returned `SelfPerceptionProjection.pipeline_version == "1.0.0"`.
2. `test_projection_returns_none_when_telemetry_disabled` — stub runtime with telemetry disabled; assert `None` returned; no exception.
3. `test_projection_returns_none_when_no_snapshot` — `build_telemetry_snapshot` returns `None` or empty; assert `None`.
4. `test_projection_fields_match_snapshot` — populate snapshot with known DSL + signals; assert each field on the projection matches the source.
5. `test_projection_function_does_not_import_llm_client` — module-level assertion: `import probos.cognitive.self_perception; assert 'llm_client' not in sys.modules.get('probos.cognitive.self_perception').__dict__`.
6. `test_cognitive_agent_self_observation_includes_pipeline_version_line` — patch a CognitiveAgent with `_last_self_avatar_snap` populated and `avatar_telemetry.inject_into_agent_context=True`; call `_build_avatar_self_observation`; assert the returned string contains `pipeline_version`.

**Plus: must turn the AD-727 safety_constraints tests green** (5 tests from AD-727 prompt).

## Acceptance

- Full test gate green. Focused gates green for both `test_ad722e_*` and `test_ad727_*`.
- AD-734 pre-commit hook passes (no vision-shape changes — vision_dispatch.py untouched in this prompt).
- README.md links to `docs/architecture/self-perception-framing.md` (added in AD-727; verify present).
- **DECISIONS.md gets a NEW `### AD-722e` entry under era-5** (verified: no AD-722e section exists at HEAD — only forward-marker mentions at DECISIONS.md:1693, 1786, 1811). Do not search-and-replace an existing entry; append a new section.

## Commit

`AD-722e: deterministic structured self-projection v1 (Wave 154). Closes #571.`
