# WAVE 101 DISPATCH — AD-510 v1 Holodeck Team Simulations: Group Discovery & Collaboration (closes #92)

## Wave summary

**Umbrella:** AD-510 — Holodeck Team Simulations: Group Discovery & Collaboration. Documented at `docs/development/roadmap.md:6405` (`(planned, OSS, depends: AD-486, AD-507)`) and `decisions-era-4-evolution.md:1347` (Crew Development wave). v1 ships the structural surface for **all six** spec items in one Builder cycle: (1) mixed-department team scenarios, (2) role rotation, (3) communication-only constraints, (4) time-pressured scenarios, (5) debrief sessions, (6) extensible team-scenario library. The wave reuses the AD-539b `HolodeckGapBridge` orchestrator pattern (`src/probos/holodeck/scenarios.py:473`) and the AD-512 `DiscoveryScenarioRegistry` catalog pattern (`src/probos/crew_development/discovery/scenarios.py:144`) — both shipped at HEAD `15fed52` and architecturally identical to what AD-510 needs.

**Wave kind:** Source-modifying single-AD v1 — additive new module `src/probos/holodeck/team_simulations.py` (~520 LOC), six new `EventType` values appended to the existing AD-486/AD-539b Holodeck cluster in `events.py:387-399` (verified extant), one new Pydantic config `HolodeckTeamSimulationConfig` adjacent to `HolodeckScenarioConfig` at `config.py:1791`, one new finalize wirer `_wire_holodeck_team_simulations` adjacent to `_wire_holodeck_scenarios` (`startup/finalize.py:242`) and `_wire_discovery_learning` (`:294`). Default-False per AD-695 transitional-flag precedent (mirrors AD-539b at `config.py:1791-1810`). Operators flip `team_simulations.enabled=True` once an AD-486 cohort reaches Phase α with crew-tier agents available across ≥2 departments to populate team rosters.

**Reframe decision — ship full v1, NO scope split (Captain rule "don't defer unless no choice" applied):**

The original draft considered five forcing-function deferrals: communication-only constraint as observational-only without runner enforcement; debrief = persistence-only without ward-room post; role-rotation as data-model-only without runtime injection; time-limit as descriptor-only without orchestrator forwarding; and a 3-scenario starter catalog deferring 3 more. On second-pass evaluation against HEAD `15fed52`, four of those failed the Captain rule and were absorbed into v1:

1. **Communication-only constraint enforcement at orchestrator boundary:** the AD-539b `HolodeckGapDrill` precedent at `scenarios.py:231-359` proves that constraint enforcement belongs in the runner-supplied closure, not the data model. v1 ships `TeamSimulationOrchestrator.start_simulation` emitting `TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED` and forwarding `communication_only=True` into the running context dict that the supplied `sim_runner` reads. Without runner-context forwarding, the constraint is descriptor-only — the v1 surface fails the spec at item (3). **Absorbed into v1.** Runner-side enforcement (memory-suppression integration with AD-462e Oracle) is a pure consumer concern — the orchestrator's job is signaling, which it now does.

2. **Debrief persistence + optional publisher callable:** AD-510 spec item (5) "debrief sessions" is structurally identical to AD-539b's `ScenarioGapLink` persistence (`scenarios.py:381`-store, `:560`-bridge). v1 ships `DebriefRecord` frozen dataclass (`simulation_id`/`scenario_id`/`outcome_score`/`time_elapsed`/`notes`/`participants` snapshot) persisted via `TeamSimulationStore.save_debrief`, plus an optional `debrief_publisher: Callable | None` injected via `set_debrief_publisher` setter. NoOp default keeps the v1 surface free of any ward-room dependency — but a real publisher (likely `WardRoomService.create_thread` + `create_post` per `ward_room/service.py:357,400`) can be wired post-Builder by an operator without code change. Without persistence, debrief is ephemeral and cannot feed `DreamingEngine` consolidation (the spec's stated learning purpose). **Absorbed into v1.**

3. **Role-rotation runtime injection:** v1 ships `TeamSimulationOrchestrator.start_simulation` with an explicit `role_rotation: dict[agent_id, alt_role] | None = None` keyword that, when present, validates each `alt_role` against `TeamScenario.required_departments`, emits `TEAM_SIMULATION_ROLE_ROTATED` once per rotated participant, and seeds the running context `participant.assigned_role = alt_role`. Without runtime injection, the spec's "Engineering problems → ask LaForge" Hebbian-connection learning purpose is undeliverable — the rotated agent never *experiences* the alternate role. ~25 LOC of orchestrator code. **Absorbed into v1.**

4. **Full 6-scenario default catalog with per-spec-item coverage:** the AD-512 `_DEFAULT_SCENARIOS` precedent at `crew_development/discovery/scenarios.py:43` ships 8 scenarios across 5 capability_categories — proving a catalog of meaningful size is a one-line block of frozen dataclass literals. v1 ships 6 default `TeamScenario` instances each demonstrating one or more of the spec's six axes: `medical_engineering_wellness_diagnose` (mixed-dept, the canonical spec example), `science_security_anomaly_investigation` (mixed-dept, the second canonical spec example), `bridge_engineering_emergency_routing` (mixed-dept, time-pressured at 60s), `medical_communications_outbreak_brief` (mixed-dept, communication-only), `security_operations_breach_response` (mixed-dept, time-pressured at 90s, role-rotation-allowed), `engineering_science_research_buildout` (mixed-dept, role-rotation-allowed). Catalog covers all 5 of the 6 axes natively (item 5 debrief is per-execution, not per-scenario). **Absorbed into v1.**

Two genuine forcing-function deferrals remain after the reframe:

- **AD-510-d — LLM-driven debrief synthesis.** v1 ships `DebriefRecord` with structured fields (`outcome_score`, `notes`, `time_elapsed`, `passed`, `participants` snapshot) and an optional `debrief_publisher` callable surface. **Forcing function:** v1 ships under `enabled=True` for one full cohort (≥5 `DebriefRecord` instances persisted via `TeamSimulationStore.save_debrief`) AND `runtime.llm_client` deep-tier proxy is verified stable in ≥5 qualification chains (per the AD-477 `QualificationHarness` runtime-proxy precedent at `cognitive/qualification.py:380`). Until then, an LLM debrief prompt would be pure speculation — there are no `DebriefRecord` exemplars at HEAD to ground prompt design. v1's structured `notes` field carries the operator-supplied summary; LLM synthesis is upgrade-path-only.
- **AD-510-e — Trait-adaptive team composition / Hebbian-aware team selection.** v1 accepts an explicit `team: list[tuple[agent_id, department]]` from the caller and validates `required_departments` coverage. **Forcing function:** AD-453 ward-room Hebbian topology accumulates ≥10 routed exchanges per dept-pair (observable via `runtime.ward_room_router.get_dept_pair_weights()` once that surface exists) AND `runtime.behavioral_metrics_engine` (shipped via AD-569 main per Wave 78 close) returns non-empty `cross_department_trigger_rate` data for ≥3 dept-pairs. Until then, an "ideal team" selector would test scaffolding rather than substance. v1 ships caller-driven team composition; the selector layer is a pure additive plugin point.

The reframe ships mixed-department team scenarios with required-department validation, runtime role-rotation injection, communication-only constraint signaling at the orchestrator boundary, time-limit forwarding into the running context, structured debrief persistence + optional publisher callable, and a 6-scenario default catalog spanning all 5 per-scenario axes — all in one Builder cycle. AD-510's "team simulations for collaborative discovery" surface — the spec target at `roadmap.md:6405` — is fully delivered.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-510 v1 — Holodeck Team Simulations: Group Discovery & Collaboration** (~46-test plan, `prompts/ad-510-holodeck-team-simulations-v1.md`). One new module `src/probos/holodeck/team_simulations.py` with: `TeamScenario` frozen dataclass (`scenario_id` / `title` / `summary` / `required_departments: tuple[str, ...]` / `skills_tested: tuple[str, ...]` / `time_limit_seconds: float | None` / `communication_only: bool` / `role_rotation_allowed: bool` / `difficulty: float` / `learning_objectives: tuple[str, ...]`), `_DEFAULT_TEAM_SCENARIOS` tuple of 6 scenarios across all 5 per-scenario axes, `TeamScenarioRegistry` (`list_scenarios` / `get_scenario` / `list_by_department` / `list_by_skill_tested` / `list_by_time_pressure` / `register_scenario` — runtime-only mutation; emits `TEAM_SCENARIO_REGISTERED` on register), `TeamSimulationParticipant` frozen dataclass (`agent_id` / `department` / `assigned_role` / `entered_at` / `communication_only_constraint: bool`), `DebriefRecord` frozen dataclass (`debrief_id` / `simulation_id` / `scenario_id` / `started_at` / `completed_at` / `outcome_score` / `passed` / `time_elapsed: float` / `time_limit_seconds: float | None` / `participants: tuple[TeamSimulationParticipant, ...]` / `notes: str`), `TeamSimulationRecord` frozen dataclass (`simulation_id` / `scenario_id` / `status: str` / `participants` / `started_at` / `completed_at: float | None` / `last_score: float | None` / `debrief_id: str | None`), `TeamSimulationDrill` (implements `QualificationTest` Protocol from `cognitive/qualification.py:39` — `name = f"holodeck_team:{simulation_id}"`, `tier = 2`, `threshold = config.default_threshold`, `description = scenario.summary`, `run(agent_id, runtime) -> TestResult` invokes the configured `sim_runner` callable with the running context), `TeamSimulationStore` (SQLite via `ConnectionFactory` mirroring `HolodeckScenarioStore` at `scenarios.py:381`; async `start` / `stop` / `save_record` / `get_record` / `save_debrief` / `get_debrief` / `list_records_by_scenario`; in-memory ring fallback when `data_dir is None`), `TeamSimulationOrchestrator` (public `start_simulation(scenario_id, team, *, role_rotation=None) -> TeamSimulationRecord | None` — validates scenario exists, validates `required_departments` coverage when `enforce_required_departments=True`, applies role-rotation injection emitting one event per rotated participant, applies communication-only constraint emitting one event when scenario.communication_only, constructs `TeamSimulationDrill`, registers with `QualificationHarness` if `auto_register_with_harness=True`, persists `TeamSimulationRecord` via store, emits `TEAM_SIMULATION_STARTED`, returns record; public `complete_simulation(simulation_id, score, *, passed=True, notes="")` — constructs `DebriefRecord`, persists via `save_debrief`, emits `TEAM_SIMULATION_DEBRIEF_RECORDED`, invokes optional `debrief_publisher` callable, updates `TeamSimulationRecord.completed_at`/`last_score`/`debrief_id`, emits `TEAM_SIMULATION_COMPLETED`, returns the debrief record; public `get_record` / `list_records_by_scenario`; late-bind setters `set_qualification_harness` / `set_team_scenario_registry` / `set_sim_runner` / `set_debrief_publisher` per Wave 5 convention #5; tier-2 log-and-degrade around `harness.register_test`, every store call, and `debrief_publisher` invocation). Six new `EventType` values appended to the existing Holodeck cluster (`events.py:387-399`): `TEAM_SCENARIO_REGISTERED`, `TEAM_SIMULATION_STARTED`, `TEAM_SIMULATION_ROLE_ROTATED`, `TEAM_SIMULATION_COMMUNICATION_CONSTRAINT_APPLIED`, `TEAM_SIMULATION_DEBRIEF_RECORDED`, `TEAM_SIMULATION_COMPLETED`. New `HolodeckTeamSimulationConfig` Pydantic model adjacent to `HolodeckScenarioConfig` at `config.py:1791` with `enabled=False` default per AD-695 transitional-flag precedent + `auto_register_with_harness=True` + `default_threshold=0.6` (Field bounded 0.0..1.0) + `default_tier=2` (Field bounded 1..3) + `enforce_required_departments=True` + `persist_to_sqlite=False` + `data_subdir="team_simulations"`. New `_wire_holodeck_team_simulations` finalize wirer mirroring `_wire_holodeck_scenarios` (`finalize.py:242`) shape — late-binds onto `runtime.qualification_harness` (already at HEAD per AD-477) + `runtime.team_scenario_registry` (installed by this same wirer); installs `runtime.team_simulation_orchestrator` public attribute. ~46 focused tests at `tests/test_ad510_team_simulations.py` across 8 classes (6 EventTypes + 6 Config + 6 TeamScenario+Registry + 4 dataclass + 5 Drill + 4 Store + 12 Orchestrator + 3 StartupWiring). Floor of 38; target 46.

**v1 OUT scope (deferred with explicit forcing functions, NOT minted as new GH issues):**

- **AD-510-d — LLM-driven debrief synthesis.** Forcing function: v1 ships under `enabled=True` for one full cohort (≥5 `DebriefRecord` instances persisted) AND `runtime.llm_client` deep-tier proxy verified stable in ≥5 qualification chains. v1 ships descriptor-only with the upgrade path documented in `team_simulations.py` module docstring referencing the structured `DebriefRecord.notes` field as the synthesis input.
- **AD-510-e — Trait-adaptive team composition / Hebbian-aware team selection.** Forcing function: AD-453 ward-room Hebbian topology accumulates ≥10 routed exchanges per dept-pair AND `runtime.behavioral_metrics_engine.cross_department_trigger_rate` returns non-empty data for ≥3 dept-pairs. v1 ships caller-driven explicit team composition.

The two roadmap forward-references that AD-510 transitively unblocks (AD-511c boundary training scenarios at `roadmap.md:6407` — team-tier ethics scenarios; AD-512 v2 collaborative discovery integration at `roadmap.md:6409` — discovery scenarios composed into team simulations) remain as already-tracked downstream consumers — Wave 101 mints zero new GH issues.

**The fleet-level overlay surface (out-of-repo):**
The OSS `TeamScenarioRegistry` + `TeamSimulationOrchestrator` + `TeamSimulationStore` + 6 new EventTypes form the architectural surface. Cross-instance team-scenario library distribution (a fleet-wide cohort sharing curated team scenarios across vessels for federated team-drill calibration), customer-supplied team-scenario template content, and outcome-style consulting on team-scenario library curation are all class-extension territory under the private overlay repo path token surface. v1 ships zero closed-source content — descriptor-only references throughout this dispatch and the per-AD prompt. Two additional fleet-level surfaces are also out-of-repo: cross-instance team-performance pattern aggregation (privacy-preserving fleet-wide team-scenario success-rate indexing) and per-fleet team-composition recommendation services.

## AD numbering

Highest AD stem at HEAD `15fed52` is **AD-696** (verified by sweep across `PROGRESS.md`, `DECISIONS.md`, `decisions-era-1-genesis.md`, `decisions-era-2-emergence.md`, `decisions-era-3-product.md`, `decisions-era-4-evolution.md`, `docs/development/roadmap.md` — top-5 stems: 696/695/694/693/692). W101 mints **zero new AD numbers** (AD-510 is pre-allocated at `decisions-era-4-evolution.md:1347` + `docs/development/roadmap.md:6405`; AD-510-d / AD-510-e are letter-suffixed forcing-function descriptors, not GH tracking issues). Highest BF stem at HEAD: **BF-265** (top-3: 265/264/263). W101 mints **zero new BF numbers**. **Current highest: AD-696, BF-265.**

## Verify-first against HEAD `15fed52`

```
git rev-parse HEAD
  15fed52 (HEAD -> main, origin/main, origin/HEAD) Wave 100 archive: AD-539b holodeck scenarios (#12)

Select-String -Path src\probos\holodeck\__init__.py -Pattern "BirthChamber|HolodeckPhase|GapScenarioGenerator|HolodeckGapBridge|HolodeckScenarioStore"
  src/probos/holodeck/__init__.py:18: from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
  src/probos/holodeck/__init__.py:19: from probos.holodeck.phases import HolodeckPhase
  src/probos/holodeck/__init__.py:20: from probos.holodeck.scheduler import DepartmentActivationScheduler
  src/probos/holodeck/__init__.py:21: from probos.holodeck.scenarios import (
  src/probos/holodeck/__init__.py:22:     GapScenarioGenerator,
  src/probos/holodeck/__init__.py:23:     HolodeckGapBridge,
  src/probos/holodeck/__init__.py:24:     HolodeckGapDrill,
  src/probos/holodeck/__init__.py:25:     HolodeckScenarioStore,
  src/probos/holodeck/__init__.py:26:     ScenarioGapLink,
  src/probos/holodeck/__init__.py:27:     ScenarioOutcome,
  src/probos/holodeck/__init__.py:28: )

git ls-files src/probos/holodeck/team_simulations.py
  (no output — file does not exist; greenfield in v1)

git ls-files tests/test_ad510_team_simulations.py
  (no output — file does not exist; greenfield in v1)

Select-String -Path src\probos\cognitive\qualification.py -Pattern "class QualificationTest|class TestResult|class QualificationHarness|def register_test|async def run_test"
  src/probos/cognitive/qualification.py:39:  class QualificationTest(Protocol):
  src/probos/cognitive/qualification.py:74:  class TestResult:
  src/probos/cognitive/qualification.py:350: class QualificationHarness:
  src/probos/cognitive/qualification.py:371: def register_test(self, test: QualificationTest) -> None:
  src/probos/cognitive/qualification.py:380: async def run_test(self, agent_id, test_name, runtime) -> TestResult:

Select-String -Path src\probos\holodeck\scenarios.py -Pattern "^class HolodeckScenarioStore|^class HolodeckGapBridge|^class GapScenarioGenerator"
  src/probos/holodeck/scenarios.py:231: class HolodeckGapDrill:
  src/probos/holodeck/scenarios.py:381: class HolodeckScenarioStore:
  src/probos/holodeck/scenarios.py:473: class HolodeckGapBridge:
  (scenarios.py total length: 631 lines.)

Select-String -Path src\probos\events.py -Pattern "HOLODECK_AGENT_ADMITTED|HOLODECK_SCENARIO_GENERATED|HOLODECK_SCENARIO_OUTCOME_RECORDED"
  src/probos/events.py:388: HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
  src/probos/events.py:396: HOLODECK_SCENARIO_GENERATED = "holodeck_scenario_generated"
  src/probos/events.py:399: HOLODECK_SCENARIO_OUTCOME_RECORDED = "holodeck_scenario_outcome_recorded"
  (insertion point for new TEAM_* values: line 400, immediately after HOLODECK_SCENARIO_OUTCOME_RECORDED, preserves the AD-486/539b cluster grouping.)

Select-String -Path src\probos\config.py -Pattern "^class HolodeckScenarioConfig|holodeck_scenarios: HolodeckScenarioConfig"
  src/probos/config.py:1791: class HolodeckScenarioConfig(BaseModel):
  src/probos/config.py:2818:     holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()

Select-String -Path src\probos\startup\finalize.py -Pattern "_wire_holodeck_scenarios|_wire_discovery_learning"
  src/probos/startup/finalize.py:242: def _wire_holodeck_scenarios(*, runtime, config) -> bool:
  src/probos/startup/finalize.py:294: def _wire_discovery_learning(*, runtime, config) -> bool:
  src/probos/startup/finalize.py:1598:    if _wire_holodeck_scenarios(runtime=runtime, config=config):
  (insertion point for _wire_holodeck_team_simulations: between :242 and :294, preserves AD-486/539b/512 wirer ordering.)

Select-String -Path src\probos\runtime.py -Pattern "qualification_harness|holodeck_gap_bridge|discovery_scenario_registry"
  src/probos/runtime.py: qualification_harness installed via AD-477 finalize wirer (verified by greppable wirer + late-bind setter shape).

Select-String -Path src\probos\crew_development\discovery\scenarios.py -Pattern "^class DiscoveryScenario|^class DiscoveryScenarioRegistry|^_DEFAULT_SCENARIOS"
  src/probos/crew_development/discovery/scenarios.py:23: class DiscoveryScenario:
  src/probos/crew_development/discovery/scenarios.py:43: _DEFAULT_SCENARIOS: tuple[DiscoveryScenario, ...] = (
  src/probos/crew_development/discovery/scenarios.py:144: class DiscoveryScenarioRegistry:
```

Every concrete claim in the per-AD prompt resolves to a HEAD-`15fed52` line above. Insertion-point line numbers will be re-verified in review pass 4 after the prompt is drafted, per the AD-443 line-drift lesson.

## Builder gate posture

| Gate | Posture |
|------|---------|
| Pre-commit deletion sanity | Additive-only — module greenfield, config greenfield, wirer additive at `:242→:294` boundary, six EventType appends, single test file additive. Largest single-file deletion estimated ≤0 lines (no source rewrites). |
| Phantom-API pre-check | Expected FPs: `TeamScenarioRegistry.*`, `TeamSimulationOrchestrator.*`, `TeamSimulationStore.*`, `TeamSimulationDrill.*`, `HolodeckTeamSimulationConfig.*`, `_wire_holodeck_team_simulations` — all intra-prompt-introduction (same FP class as Waves 27-50). Zero NEW phantoms expected. |
| Banned-pattern audit (pre-commit hook) | The hook flags two literal patterns that the audit prose itself MUST NOT contain. This dispatch and the per-AD prompt use placeholder forms only: "private overlay repo path token surface", "fleet-level overlay surface (out-of-repo)", "class-extension territory". Zero literal hits expected. |
| Test-count delta | Floor +38, target +46. Baseline 12314 → expected ≥12352, target 12360. |
| Test-isolation | All new tests are unit-level — no network, no real LLM, no real qualification harness side effects (mock harness with `MagicMock(spec=...)` per AD-686b lesson). `tmp_path` for SQLite store. No shared mutable state. |
| Hard-stop conditions | (a) Phantom API in implementation (not test asserts); (b) architectural change required (modify `BaseAgent`/`IntentMessage`); (c) AD-477 `QualificationHarness.register_test` signature drift between HEAD and prompt. None expected at HEAD `15fed52`. |

## Commercial-leak audit

Independent sweep of dispatch + per-AD prompt prose against the project banned-pattern policy:

| Surface | Status |
|---------|--------|
| Pricing language | None — descriptor-only references to overlay surfaces. |
| Revenue / business-model wording | None. |
| Customer count / recurring-revenue acronym / pipeline references | None. |
| Professional-services / consulting positioning copy | One descriptor reference ("outcome-style consulting on team-scenario library curation") in fleet-level overlay paragraph — descriptor-only, no model named, no go-to-market copy. |
| Go-to-market / competitive positioning | None. |
| Demo-script / sales-deck phrasing | None. |
| Literal banned tokens (placeholder-policy compliance) | Zero. The two literal patterns flagged by the pre-commit hook are NEVER quoted, named, or shown in form-content. The audit prose itself — including this row — uses placeholder forms only. |

Pre-commit hook simulation: dispatch + per-AD prompt + wave-plan entry pass with exit code 0 expected.

## Wave-plan entry

Append to `prompts/wave-plan.yaml` after the existing W100 entry (verified at `wave-plan.yaml:2636`):

```yaml
  - id: "101"
    title: "AD-510 v1 Holodeck Team Simulations: Group Discovery & Collaboration (closes #92)"
    kind: single
    depends_on: ["100"]
    dispatch_prompt: "prompts/WAVE-101-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-510-holodeck-team-simulations-v1.md"
    builder_required: true
    issues_to_close: [92]
    status: pending
```

## Files produced by this draft

| File | Status |
|------|--------|
| `prompts/WAVE-101-DISPATCH.md` | Created (this file). |
| `prompts/ad-510-holodeck-team-simulations-v1.md` | Created — Builder spec with `===FILE===` block for `team_simulations.py`, six SEARCH/REPLACE pairs (events.py append, config.py model + SystemConfig field, finalize.py wirer + invocation site, holodeck `__init__.py` exports), and `===FILE===` block for `tests/test_ad510_team_simulations.py`. |
| `prompts/wave-plan.yaml` | Modified — single-entry append. |

## Acceptance criteria for the Builder

1. New module `src/probos/holodeck/team_simulations.py` ships with `TeamScenario`, `_DEFAULT_TEAM_SCENARIOS` (≥6 entries spanning all five per-scenario axes — mixed-dept / role-rotation-allowed / communication-only / time-pressured / extensibility), `TeamScenarioRegistry`, `TeamSimulationParticipant`, `DebriefRecord`, `TeamSimulationRecord`, `TeamSimulationDrill`, `TeamSimulationStore`, `TeamSimulationOrchestrator`.
2. Six new `EventType` values appended to `events.py` immediately after `HOLODECK_SCENARIO_OUTCOME_RECORDED` at `:399`. Cluster grouping preserved.
3. `HolodeckTeamSimulationConfig` Pydantic model added to `config.py` immediately after the `HolodeckScenarioConfig` body (lines 1791-1809). `team_simulations: HolodeckTeamSimulationConfig = HolodeckTeamSimulationConfig()` field added to `SystemConfig` immediately after the `holodeck_scenarios` field at `:2818`. Default-False per AD-695 precedent.
4. `_wire_holodeck_team_simulations` wirer added to `startup/finalize.py` between `:242` and `:294`. Invocation site appended to the same wirer-cascade block that hosts `_wire_holodeck_scenarios` (`:1598`). When config disabled (`enabled=False`), wirer returns `False` and `runtime.team_simulation_orchestrator` is NOT set.
5. Holodeck package `__init__.py` re-exports the eight new public names from `team_simulations.py`.
6. New test file `tests/test_ad510_team_simulations.py` ships ≥38 tests across 8 classes (target 46). Floor 38, target 46.
7. Full pytest gate at `pytest tests/ -q -n 4 --dist=loadfile` reaches ≥12352 passing (baseline 12314 + floor 38), target ≥12360.
8. Builder commit message: `AD-510: Holodeck team simulations v1 (registry+orchestrator+drill+store+debrief+events+config+wirer) (+NN tests)`.
9. Wave 101 archive commit moves `prompts/WAVE-101-DISPATCH.md` and `prompts/ad-510-holodeck-team-simulations-v1.md` into `prompts/archive/`.
10. GH issue #92 closure comment includes test-delta, fleet-level overlay descriptor-only note (no banned literal patterns), and the two AD-510-d / AD-510-e forcing-function descriptors.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Trackers updated

| Tracker | Update |
|---------|--------|
| `prompts/wave-plan.yaml` | W101 entry appended (status: pending). |
| `PROGRESS.md` | Builder appends W101 close paragraph mirroring W100 format. |
| `docs/development/roadmap.md` | Builder flips AD-510 entry from `(planned, OSS, depends: AD-486, AD-507)` to `(v1 partial — registry/orchestrator/drill/store/debrief/events/config/wirer shipped Wave 101; AD-510-d LLM debrief synthesis + AD-510-e trait-adaptive composition deferred with forcing functions)`. |
| `decisions-era-4-evolution.md` | Builder flips the AD-510 row in the Crew Development table at `:1347` to reference Wave 101 close. |
| `DECISIONS.md` | NO change — AD-510 is pre-allocated; no new architectural decision is being made. |
