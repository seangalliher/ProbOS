# WAVE 100 DISPATCH — AD-539b v1 Holodeck Scenario Generation from Skill Gaps (closes #12)

## Wave summary

**Umbrella:** AD-539b — Holodeck Scenario Generation from Skill Gaps. Documented at `docs/development/roadmap.md:1260` ("Deferred: AD-539b (Holodeck scenario generation from gaps)") and `decisions-era-4-evolution.md:2094` (parked alongside AD-539c/d when AD-539 v1 shipped). Bridges the AD-539 gap-detection pipeline (`src/probos/cognitive/gap_predictor.py:186` `GapReport`, `:474` `trigger_qualification_if_needed`) to the AD-486 Holodeck substrate (just shipped at HEAD `6d34fcb` — `src/probos/holodeck/`) via the AD-477 `QualificationHarness` runnable surface (`src/probos/cognitive/qualification.py:350`). v1 produces a runnable `HolodeckGapDrill` per `GapReport` and registers it with the existing `QualificationHarness` so AD-628d `DrillCalendar` can schedule and execute it — which is exactly what the **AD-628d-1 forcing function** (W93 dispatch, `prompts/archive/WAVE-93-DISPATCH.md:55-66`) is gated on: *"AD-486 + AD-539b ship the Holodeck primitive."* W99 shipped AD-486; W100 ships AD-539b; AD-628d-1 becomes unblockable in a later wave.

**Wave kind:** Source-modifying single-AD v1 — additive new module `src/probos/holodeck/scenarios.py` (~480 LOC), four new `EventType` values under the existing AD-486 Holodeck cluster in `events.py:387-393`, one new Pydantic config `HolodeckScenarioConfig` adjacent to `HolodeckBirthChamberConfig` at `config.py:1756`, one new finalize wirer `_wire_holodeck_scenarios` in `startup/finalize.py` adjacent to `_wire_birth_chamber` (`:159`) and `_wire_discovery_learning` (`:241`), and one optional `holodeck_bridge=None` keyword parameter on `gap_predictor.trigger_qualification_if_needed` at `gap_predictor.py:474`. The chain is fully observational under default-False per AD-695 transitional-flag precedent. Operators flip `holodeck_scenarios.enabled=True` once the AD-486 Birth Chamber Phase α cohort produces `GapReport` instances with non-empty `mapped_skill_id` to bridge against.

**Reframe decision — ship full v1, NO scope split (Captain rule "don't defer unless no choice" applied):**

The original draft considered five forcing-function deferrals (no `QualificationHarness` registration; no `HolodeckScenarioStore` SQLite path; no `gap_predictor` hook; no AD-512 `DiscoveryScenarioRegistry` reuse; no auto-link back to `gap.qualification_path_id`). On second-pass evaluation against HEAD `6d34fcb`, four of those failed the Captain rule and were absorbed into v1:

1. **`QualificationHarness.register_test()` integration:** `register_test` is shipped at `qualification.py:371`; the `QualificationTest` Protocol is shipped at `:39`. Adapting the generated `HolodeckGapDrill` to the Protocol is ~30 LOC (it already needs `name`/`tier`/`description`/`threshold`/`run` — those map 1:1 to gap fields). Without harness registration, the generated drill is unrunnable — the v1 surface would be design-only. **Absorbed into v1.** This is also the precise mechanism that lets AD-628d `DrillCalendar.schedule_drill` schedule a generated drill in a later wave (the AD-628d-1 unblock path).
2. **`DiscoveryScenarioRegistry` reuse:** AD-512 v1 shipped `DiscoveryScenario` (frozen dataclass at `crew_development/discovery/scenarios.py:23`), `DiscoveryScenarioRegistry` (`:144`) with `list_by_category` (`:174`) and `list_by_difficulty_band` (`:181`), 8 default scenarios across 5 capability_categories (analysis/communication/coordination/construction/diagnosis), and is wired at `startup/finalize.py:241` (`_wire_discovery_learning`). The original "AD-539b-c — LLM-driven scenario synthesis" deferral assumed v1 would invent scenarios from scratch. With AD-512's catalog already at HEAD, `GapScenarioGenerator` can FIRST attempt to match a `DiscoveryScenario` from the registry by `capability_category` derived from `gap.mapped_skill_id` / `gap.affected_intent_types`, and ONLY fall back to a templated scenario when no match exists. Reusing 8 shipped scenarios is ~50 LOC of adapter code. **Absorbed into v1.**
3. **`gap_predictor.trigger_qualification_if_needed` optional hook:** the existing AD-539 function at `gap_predictor.py:474` is the canonical post-mapping hook for skill-side gap remediation. Adding an optional `holodeck_bridge=None` keyword parameter that, when supplied, also invokes `holodeck_bridge.bridge_gap_to_holodeck(gap)` AFTER the existing skill-service path is ~5 LOC. Default `None` preserves byte-for-byte behavior at every existing call site (Dream Step 8 in `dreaming.py`). Without this hook, the v1 bridge is callable only from external code paths — which means no production wiring without a follow-up AD. **Absorbed into v1.**
4. **`HolodeckScenarioStore` SQLite path:** the AD-477 `QualificationStore` at `qualification.py:136` already provides a `ConnectionFactory`-backed SQLite path for test results. The bridge's job is NOT to duplicate test-result persistence — it's to persist the `gap_id ↔ scenario_id ↔ drill_test_name` linkage so that gap closure can be cross-referenced. v1 ships `HolodeckScenarioStore` as a tiny SQLite table (`scenario_gap_links`) via the same `ConnectionFactory` precedent (~70 LOC), with an in-memory ring fallback when `data_dir` is None. Without the store, generated drills cannot be deduplicated against their source `GapReport` and re-generation on every Dream cycle would create duplicate `QualificationHarness` registrations. **Absorbed into v1.**

One genuine forcing-function deferral remains after the reframe:

- **AD-539b-d — ZPDCalibrator-driven difficulty calibration.** AD-512 v1 shipped `ZPDCalibrator` at `crew_development/discovery/zpd.py` (verified imported at `startup/finalize.py:254` + `runtime.zpd_calibrator` public attribute at `:274`), but its calibration depends on `CapabilityConfidenceScorer` (also shipped at AD-512 v1) accumulating ≥10 outcome observations per agent before the Beta(α,β) posterior diverges meaningfully from the prior. v1 takes the chosen `DiscoveryScenario.difficulty` field unmodified and lets the resulting `HolodeckGapDrill.threshold` default to `config.default_threshold` (0.6). **Forcing function:** AD-539b v1 ships under `enabled=True` for one full cohort (≥10 generated drills executed via `QualificationHarness.run_test`) AND `runtime.zpd_calibrator` accumulates ≥10 outcome posts per agent. Until then, ZPD calibration would test scaffolding rather than substance.

The reframe ships gap-driven scenario generation, runnable-drill registration with AD-477 `QualificationHarness`, AD-512 `DiscoveryScenarioRegistry` reuse, in-memory + SQLite-backed `gap_id ↔ scenario_id` linkage persistence, and the optional `gap_predictor` hook in one Builder cycle. AD-539b's "Holodeck scenario generation from gaps" surface — the precise blocker for AD-628d-1 — is fully delivered.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-539b v1 — Holodeck Scenario Generation from Skill Gaps** (~38-test plan, `prompts/ad-539b-holodeck-scenario-generation-v1.md`). One new module `src/probos/holodeck/scenarios.py` with: `ScenarioGapLink` frozen dataclass (gap_id / scenario_id / drill_test_name / generated_at / status / last_run_score), `ScenarioOutcome` frozen dataclass (link + last `TestResult` snapshot), `GapScenarioGenerator` (matches `gap.mapped_skill_id` + `gap.affected_intent_types` against `DiscoveryScenarioRegistry.list_by_category` / `get_scenario` lookups; falls back to a templated `DiscoveryScenario` when no match), `HolodeckGapDrill` (implements `QualificationTest` Protocol from `qualification.py:39` — `name = f"holodeck_gap:{gap.id}"`, `tier = 2`, `threshold = config.default_threshold`, `run(agent_id, runtime) -> TestResult` calls a configured `drill_runner` callable with the scenario + gap + agent_id and produces a TestResult), `HolodeckScenarioStore` (SQLite via `ConnectionFactory` mirroring `QualificationStore`; `start()`/`stop()`/`save_link()`/`get_link_for_gap()`/`update_outcome()` async API; in-memory fallback when `data_dir is None`), `HolodeckGapBridge` orchestrator (public `bridge_gap_to_holodeck(gap)` async method: idempotent against existing `gap_id` link, calls `generator.generate_from_gap` → constructs `HolodeckGapDrill` → registers with `QualificationHarness` → persists `ScenarioGapLink` via store → emits 3 events → back-fills `gap.qualification_path_id` so existing closure tracking sees the link). Four new `EventType` values appended to the existing AD-486 Holodeck cluster (`events.py:387-393`): `HOLODECK_SCENARIO_GENERATED`, `HOLODECK_SCENARIO_REGISTERED`, `HOLODECK_SCENARIO_GAP_LINKED`, `HOLODECK_SCENARIO_OUTCOME_RECORDED`. New `HolodeckScenarioConfig` Pydantic model adjacent to `HolodeckBirthChamberConfig` at `config.py:1756` with `enabled=False` default per AD-695 transitional-flag precedent + `auto_register_with_harness=True` + `default_threshold=0.6` + `default_tier=2` + `data_dir: Path | None = None` + `category_fallback="construction"`. New `_wire_holodeck_scenarios` finalize wirer mirroring `_wire_birth_chamber` (`finalize.py:159`) + `_wire_discovery_learning` (`:241`) shapes — late-binds onto `runtime.qualification_harness` (already at HEAD per AD-477) + `runtime.discovery_scenario_registry` (already at HEAD per AD-512 v1); installs `runtime.holodeck_gap_bridge` public attribute. Optional `holodeck_bridge: Any = None` keyword parameter added to `trigger_qualification_if_needed` at `gap_predictor.py:474` — default None preserves all existing call sites byte-for-byte; when supplied, invoked AFTER the existing skill-service path. ~38 focused tests at `tests/test_ad539b_holodeck_scenarios.py` across 6 classes (4 EventTypes + 5 Config + 4 ScenarioGapLink + 8 GapScenarioGenerator + 6 HolodeckGapDrill + 8 HolodeckGapBridge + 3 StartupWiring).

**v1 OUT scope (deferred with explicit forcing functions, NOT minted as new GH issues):**

- **AD-539b-d — ZPDCalibrator-driven difficulty calibration.** Forcing function: AD-539b v1 ships under `enabled=True` for one full cohort AND `runtime.zpd_calibrator` accumulates ≥10 outcome posts per agent. Until then, ZPD calibration would test scaffolding. v1 ships descriptor-only with the upgrade path documented in `scenarios.py` module docstring referencing `runtime.zpd_calibrator`.
- **AD-539b-e — Auto-schedule generated drills via AD-628d `DrillCalendar`.** v1 registers drills with `QualificationHarness` but does NOT schedule them. Forcing function: AD-628d-1 is drafted (which this wave unblocks) AND first 5 generated drills are manually scheduled — pattern justifies an auto-schedule policy. Currently the operator drives drill execution via the existing `/readiness` slash command path or a future TRAINO standing-order proactive cycle.

The five roadmap forward-references that AD-539b transitively unblocks (AD-628d-1 TRAINO Holodeck-driven drill scheduling, Lab Tech crew role at `roadmap.md:2921`, AD-510 Team Simulations scenario-library extension at `roadmap.md:6405`, AD-511c boundary training scenarios at `roadmap.md:6407`, AD-486e Holodeck Construct abstraction at the W99 dispatch deferral line) all remain as already-tracked downstream consumers — Wave 100 mints zero new GH issues.

**The fleet-level overlay surface (out-of-repo):**
The OSS `GapScenarioGenerator` + `HolodeckGapBridge` + `HolodeckScenarioStore` + 4 new EventTypes form the architectural surface. Cross-instance scenario-library distribution (a fleet-wide cohort sharing generated scenarios across vessels for federated drill calibration), customer-defined scenario template content, and outcome-style consulting on scenario-library curation are all class-extension territory under the private commercial-repo path token surface. v1 ships zero closed-source content — descriptor-only references throughout this dispatch and the per-AD prompt. Two additional fleet-level surfaces are also out-of-repo: cross-instance gap-pattern aggregation (privacy-preserving fleet-wide gap pattern indexing) and per-fleet drill-success-rate leaderboards.

## AD numbering

Highest AD stem at HEAD `6d34fcb` is **AD-696** (verified by `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern '\bAD-(\d{3})\b' -AllMatches | Sort-Object -Descending | Select-Object -First 5` returning AD-696 across all four files). W100 mints **zero new AD numbers** (AD-539b is pre-allocated at `decisions-era-4-evolution.md:2094` + `docs/development/roadmap.md:1260`; AD-539b-d / AD-539b-e are letter-suffixed forcing-function descriptors, not GH tracking issues). Highest BF stem at HEAD: **BF-265** (verified by `Select-String -Path PROGRESS.md, docs/development/roadmap.md, decisions-era-*.md, DECISIONS.md -Pattern '\bBF-(\d+)\b' -AllMatches | Sort-Object -Descending -Property {[int]($_-replace 'BF-','')} | Select-Object -First 3`; `BF-265` / `BF-264` / `BF-263` are the top three; the W99 dispatch claim of `BF-596` was a stale value carried forward from W93 and does not reflect HEAD). W100 mints **zero new BF numbers**. **Current highest: AD-696, BF-265.**

## Verify-first against HEAD `6d34fcb`

```
git rev-parse HEAD
  6d34fcb (HEAD -> main, origin/main, origin/HEAD) Wave 99 archive: AD-486 holodeck birth chamber (#24)

Select-String -Path src\probos\holodeck\__init__.py -Pattern "BirthChamber|HolodeckPhase|DepartmentActivationScheduler"
  src/probos/holodeck/__init__.py:13: from probos.holodeck.affect import (...)
  src/probos/holodeck/__init__.py:18: from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
  src/probos/holodeck/__init__.py:19: from probos.holodeck.phases import HolodeckPhase
  src/probos/holodeck/__init__.py:20: from probos.holodeck.scheduler import DepartmentActivationScheduler

git ls-files src/probos/holodeck/scenarios.py
  (no output — file does not exist; greenfield in v1)

Select-String -Path src\probos\cognitive\gap_predictor.py -Pattern "class GapReport|^def classify_gap|^def detect_gaps|^async def map_gap_to_skill|^async def trigger_qualification_if_needed"
  src/probos/cognitive/gap_predictor.py:186: class GapReport:
  src/probos/cognitive/gap_predictor.py:229: def classify_gap(
  src/probos/cognitive/gap_predictor.py:258: def detect_gaps(
  src/probos/cognitive/gap_predictor.py:420: async def map_gap_to_skill(
  src/probos/cognitive/gap_predictor.py:474: async def trigger_qualification_if_needed(

Select-String -Path src\probos\cognitive\qualification.py -Pattern "class QualificationTest|class TestResult|class QualificationHarness|class QualificationStore|def register_test|def registered_tests|async def run_test"
  src/probos/cognitive/qualification.py:39:  class QualificationTest(Protocol):
  src/probos/cognitive/qualification.py:74:  class TestResult:
  src/probos/cognitive/qualification.py:136: class QualificationStore:
  src/probos/cognitive/qualification.py:350: class QualificationHarness:
  src/probos/cognitive/qualification.py:371: def register_test(self, test: QualificationTest) -> None:
  src/probos/cognitive/qualification.py:375: @property def registered_tests(self) -> dict[str, QualificationTest]:
  src/probos/cognitive/qualification.py:380: async def run_test(self, agent_id, test_name, runtime) -> TestResult:

Select-String -Path src\probos\crew_development\discovery\scenarios.py -Pattern "class DiscoveryScenario|class DiscoveryScenarioRegistry|def list_by_category|def list_by_difficulty_band|def get_scenario|_DEFAULT_SCENARIOS"
  src/probos/crew_development/discovery/scenarios.py:23:  class DiscoveryScenario:
  src/probos/crew_development/discovery/scenarios.py:43:  _DEFAULT_SCENARIOS: tuple[DiscoveryScenario, ...] = (
  src/probos/crew_development/discovery/scenarios.py:144: class DiscoveryScenarioRegistry:
  src/probos/crew_development/discovery/scenarios.py:168: def get_scenario(self, scenario_id: str) -> DiscoveryScenario | None:
  src/probos/crew_development/discovery/scenarios.py:174: def list_by_category(self, category: str) -> tuple[DiscoveryScenario, ...]:
  src/probos/crew_development/discovery/scenarios.py:181: def list_by_difficulty_band(self, low: float, high: float) -> tuple[...]:

Select-String -Path src\probos\events.py -Pattern "HOLODECK_AGENT_ADMITTED|HOLODECK_PHASE_ENTERED|HOLODECK_GRADUATION|HOLODECK_AFFECTIVE_BASELINE_OBSERVED"
  src/probos/events.py:388: HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
  src/probos/events.py:389: HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
  src/probos/events.py:392: HOLODECK_GRADUATION = "holodeck_graduation"
  src/probos/events.py:393: HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"

Select-String -Path src\probos\events.py -Pattern "HOLODECK_SCENARIO_"
  (no output — collision-free for the four new EventTypes)

Select-String -Path src\probos\config.py -Pattern "class HolodeckBirthChamberConfig|holodeck_birth_chamber:"
  src/probos/config.py:1756: class HolodeckBirthChamberConfig(BaseModel):
  src/probos/config.py:2796: holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()

Select-String -Path src\probos\config.py -Pattern "class HolodeckScenarioConfig|holodeck_scenarios:"
  (no output — collision-free)

Select-String -Path src\probos\startup\finalize.py -Pattern "_wire_birth_chamber|_wire_discovery_learning|_wire_holodeck_scenarios"
  src/probos/startup/finalize.py:159:  def _wire_birth_chamber(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:241:  def _wire_discovery_learning(*, runtime: Any, config: "SystemConfig") -> bool:
  src/probos/startup/finalize.py:1543: if _wire_birth_chamber(runtime=runtime, config=config):
  (no _wire_holodeck_scenarios — collision-free)

Select-String -Path src\probos\startup\finalize.py -Pattern "runtime\.qualification_harness|runtime\.discovery_scenario_registry|runtime\.zpd_calibrator"
  src/probos/startup/finalize.py:261:  runtime.discovery_scenario_registry = scenario_registry
  src/probos/startup/finalize.py:274:  runtime.zpd_calibrator = zpd_calibrator
  (qualification_harness is wired by AD-477 v1 — verified via cross-reference at AD-628d drill_calendar.py:35 import line)

Select-String -Path src\probos\storage\sqlite_factory.py -Pattern "default_factory|class.*ConnectionFactory|async def connect"
  (verified via cross-reference at qualification.py:175 — `from probos.storage.sqlite_factory import default_factory`)

Select-String -Path tests -Pattern "test_ad539b_holodeck"
  (no output — test file does not exist; greenfield)
```

All concrete claims in `prompts/ad-539b-holodeck-scenario-generation-v1.md` map to one of:
1. A grep hit shown above (existing anchor preserved by SEARCH/REPLACE).
2. A new symbol introduced by this prompt's own SEARCH/REPLACE blocks (Section 0 EventTypes, Section 1 config model + field, Section 2 scenarios.py module, Section 3 _wire_holodeck_scenarios + invocation, Section 4 trigger_qualification_if_needed optional kwarg, Section 5 holodeck/__init__.py public surface extension).

Phantom-API pre-check on the prompt body via `scripts/phantom-api-precheck.ps1`:
- Expected FP class: intra-prompt-introduction phantoms (`HolodeckGapBridge.X`, `HolodeckGapDrill.X`, `GapScenarioGenerator.X`, `HolodeckScenarioStore.X`, `ScenarioGapLink.X`, `ScenarioOutcome.X` — all defined in Section 2 of this prompt). Same FP class as Waves 27-49 + 96-99.
- 0 NEW genuine phantoms expected.
- Builder runs the pre-check; documented FP count goes into the build report.

## Pre-flight checklist

```powershell
# 1. Confirm clean working tree
git status --short
# expected: empty (no tracked or untracked source under src/, tests/, prompts/ except the wave 100 prompts)

# 2. Confirm baseline pytest count
.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile
# expected: 12271 passed (per Captain's W100 dispatch baseline)

# 3. Confirm no scenarios.py exists
git ls-files src/probos/holodeck/scenarios.py
# expected: empty

# 4. Confirm no AD-539b test file exists
git ls-files tests/test_ad539b_holodeck_scenarios.py
# expected: empty

# 5. Confirm AD-486 v1 substrate is at HEAD
git ls-files src/probos/holodeck/
# expected: __init__.py affect.py chamber.py gates.py phases.py scheduler.py

# 6. Confirm AD-477 substrate is at HEAD
.venv\Scripts\python.exe -c "from probos.cognitive.qualification import QualificationHarness, QualificationTest, TestResult; print('AD-477 OK')"
# expected: AD-477 OK

# 7. Confirm AD-512 substrate is at HEAD
.venv\Scripts\python.exe -c "from probos.crew_development.discovery import DiscoveryScenario, DiscoveryScenarioRegistry, ZPDCalibrator; print('AD-512 OK')"
# expected: AD-512 OK

# 8. Confirm AD-539 pipeline is at HEAD
.venv\Scripts\python.exe -c "from probos.cognitive.gap_predictor import GapReport, classify_gap, detect_gaps, map_gap_to_skill, trigger_qualification_if_needed; print('AD-539 OK')"
# expected: AD-539 OK
```

If any pre-flight step fails, STOP. Builder reports to architect. Do not proceed.

## Per-prompt workflow

1. Read `prompts/ad-539b-holodeck-scenario-generation-v1.md` end-to-end before editing any source.
2. Apply Section 0 (EventTypes) first — the four new values must exist before Sections 2/3 reference them.
3. Apply Section 1 (Pydantic config) before Section 3 (wirer reads config).
4. Apply Section 2 (scenarios.py module) — single new file, ~480 LOC. ast.parse validates after write.
5. Apply Section 3 (_wire_holodeck_scenarios + invocation in startup main).
6. Apply Section 4 (gap_predictor optional kwarg) — single SEARCH/REPLACE pair.
7. Apply Section 5 (holodeck/__init__.py public surface extension) — additive imports + __all__ entries.
8. Run the focused test file: `.venv\Scripts\pytest.exe tests/test_ad539b_holodeck_scenarios.py -v -n 0`. Target: ~38 passed.
9. Run the full gate: `.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile`. Target: ≥12305 passed (+34 floor; aim +38 over baseline 12271).
10. Run the phantom-API pre-check: `.\scripts\phantom-api-precheck.ps1 prompts/ad-539b-holodeck-scenario-generation-v1.md`. Document FP count in the build report.
11. Apply Section 6 tracker updates (PROGRESS.md, roadmap.md, decisions-era-4-evolution.md, wave-plan.yaml).
12. Commit with the canonical message in Section 7 of the per-AD prompt.
13. Archive both prompts. `gh issue close 12` with the canonical paragraph.

## Per-commit quality gates

- Single Builder commit for the AD: `AD-539b: Holodeck scenario generation from skill gaps (generator+drill+bridge+store+wirer+gap-predictor-hook) (+~38 tests)`.
- Single archive commit: `Wave 100 archive: AD-539b holodeck scenario generation from skill gaps (#12)`.
- Pre-commit hook deletion sanity: max additive deltas only (one new module + one new test file + four EventTypes + one Pydantic class + one wirer + one optional kwarg). Well below 200-line surprise-deletion threshold.
- Pre-commit-hook simulation `Select-String -Path prompts/WAVE-100-DISPATCH.md, prompts/ad-539b-holodeck-scenario-generation-v1.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern across all 11 banned-pattern descriptors (Builder runs and reports in build-report).

## Hard-stop conditions

The Builder STOPS and reports to architect immediately if:

1. **Phantom API in implementation:** any imported symbol in scenarios.py / wirer / gap_predictor hook does not resolve at HEAD `6d34fcb`.
2. **Architectural change required:** the prompt's adapter pattern (HolodeckGapDrill implementing QualificationTest Protocol) requires a Protocol mutation in qualification.py. (It should NOT — the Protocol at `:39` matches HolodeckGapDrill's shape verbatim per the design.)
3. **Pre-flight failure:** any of the 8 pre-flight checks above fails before any source edit.
4. **Test count regression beyond -1:** if the full gate count drops below 12270 (1 below baseline), STOP; this would indicate accidental damage to existing AD-486 / AD-512 / AD-477 / AD-539 tests.
5. **Banned-pattern hit on pre-commit-hook simulation:** any literal banned pattern appears in either prompt file. Re-write to descriptor-only language.

## Wave-specific reminders for known false positives

- **Constructor-test pattern:** `HolodeckGapBridge.__init__` accepts `qualification_harness=None` for unit-test isolation BUT v1 production wiring always passes a real `QualificationHarness` from `runtime.qualification_harness`. The "log-and-degrade when harness is None" branch is genuine fallback (e.g., AD-477 disabled by config), NOT a unit-test-only hatch. Do NOT add `else: # Only for unit tests`.
- **Frozen dataclass field ordering:** `ScenarioGapLink` defaulted fields (`status="generated"`, `last_run_score=None`) must come AFTER non-defaulted fields. Builder verified order in Section 2.
- **`asyncio.iscoroutinefunction` guard:** `HolodeckGapDrill.run` is `async def` — the harness invokes it via `await test.run(agent_id, runtime)`. Do NOT add `hasattr(test, 'run')` defensive guards; AD-477 already validates via the `QualificationTest` Protocol.
- **`emit_event` public attribute:** `runtime.emit_event` is a stable public method (per W99 finalize wirer at `:170` — `emit_fn = getattr(runtime, "emit_event", None)`). Do NOT add `hasattr(runtime, 'emit_event')` guards.
- **AD-512 reuse — `runtime.discovery_scenario_registry`:** the wirer late-binds onto this attribute; if AD-512 is disabled by config, the bridge falls back to template-only generation (covered by Section 2 `category_fallback` config field). Do NOT make the wirer fail when discovery_scenario_registry is missing.
- **AD-695 transitional flag:** v1 ships `enabled=False`. The wirer returns `False` early when disabled — do NOT register `runtime.holodeck_gap_bridge` in that branch (no public attr until enabled). Do NOT default `enabled=True` "for development".

## Build groups

Wave 100 ships a single AD with no inter-section dependencies that would benefit from grouping. Sections 0→6 ship in one Builder commit; tracker updates in a follow-up commit alongside the archive move.

## Captain rule alignment

- **Don't defer unless no choice:** v1 absorbs four originally-considered deferrals (harness registration, DiscoveryScenarioRegistry reuse, gap_predictor hook, SQLite-backed store) into a single ship. The lone deferral (AD-539b-d ZPDCalibrator-driven difficulty calibration) has a crisp upstream-data forcing function — until the calibrator accumulates real outcomes, calibration tests scaffolding rather than substance. AD-539b-e (auto-schedule via AD-628d DrillCalendar) is parked because AD-628d-1 is the natural consumer wave (which this AD unblocks). Reframe satisfied.
- **Verify-first:** every concrete claim has explicit grep evidence in the per-AD prompt's `## Verified Against Codebase` footer. 16 grep-anchored claims confirm extension-point existence at HEAD `6d34fcb`.
- **`.github/copilot-instructions.md` compliance:** `HolodeckGapBridge.bridge_gap_to_holodeck` is observation-and-registration only — no destructive intent (`requires_consensus` not applicable). Layer-discipline rule respected — `scenarios.py` lives in `src/probos/holodeck/` and imports from cognitive (qualification, gap_predictor) + crew_development (discovery) + storage + events + types — all peer or lower layers. New EventTypes follow the AD-527 typed-events pattern + use the AD-486 cluster comment block. New Pydantic config fields follow the AD-432 default-factory rule (no mutable defaults). Trust storage rule N/A (no trust mutations in v1). Episodic completeness rule N/A (events flow through standard `emit_event` → episode pipeline). Async hygiene: no `create_task()` in v1 (the wirer is synchronous; the async `run` method is awaited by `QualificationHarness.run_test`).
- **Close #12 cleanly:** issue closed at end of W100 with the canonical paragraph in Section 7 of the per-AD prompt; no children minted; the two future sub-AD letters (AD-539b-d / AD-539b-e) tracked as part of the umbrella close note (forcing-function language only — NOT a "remaining work" backlog).
- **No commercial leak:** descriptor-only audit, banned-pattern scan returns zero literal hits across both files.

## Banned-pattern audit on this dispatch + the per-AD prompt + this audit prose itself

Eleven patterns checked, descriptor-only language used throughout: "the e-word + tier-phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The audit text itself does NOT contain literal forms of any banned pattern — descriptor-only references throughout. The pre-commit hook trips on literal "the e-word + tier-phrase" and "the private commercial-repo path token" forms; this dispatch (and the per-AD prompt + the wave-plan entry) avoids both literal forms via descriptor-only references. Pre-commit-hook simulation returns zero hits per pattern (Builder runs and reports in build-report).

## Files

- `prompts/WAVE-100-DISPATCH.md` (this file)
- `prompts/ad-539b-holodeck-scenario-generation-v1.md` (the per-AD prompt — six implementation sections + tests + tracker updates)
- `prompts/wave-plan.yaml` (W100 entry appended)

## Wave-100 baseline + targets

- **HEAD:** `6d34fcb` (Wave 99 archive: AD-486 holodeck birth chamber — closed #24). Captain reference HEAD `6d34fcb` matches origin/main exactly; no upstream BF commits between Captain HEAD and this draft HEAD.
- **Baseline pytest:** 12271.
- **Target pytest:** ≥ 12305 (+34 floor; ~38 tests planned across six classes — TestEventTypes ~4, TestConfig ~5, TestScenarioGapLink ~4, TestGapScenarioGenerator ~8, TestHolodeckGapDrill ~6, TestHolodeckGapBridge ~8, TestStartupWiring ~3).
- **Issue closed:** `#12 — AD-539b: Holodeck scenario generation from skill gaps` (single issue; no children minted by W100 — two forcing-function letters tracked as part of the umbrella close note).

## Architect review-pass record

Four review passes completed before this dispatch shipped:

- **Pass 1 (gap-and-substrate audit):** confirmed AD-486 v1 substrate (`src/probos/holodeck/`) at HEAD; confirmed AD-477 `QualificationHarness.register_test` + Protocol at `qualification.py:39/350/371`; confirmed AD-512 `DiscoveryScenarioRegistry` shipped (changed v1 design to REUSE rather than reinvent — saves ~120 LOC + drops the LLM-synthesis deferral); confirmed AD-539 `GapReport` + `trigger_qualification_if_needed` pipeline at `gap_predictor.py:186/474`; confirmed AD-628d-1 forcing function at `prompts/archive/WAVE-93-DISPATCH.md:55-66`. Reframe absorbed 4 of 5 originally-considered deferrals.
- **Pass 2 (verify-first sweep):** every concrete file path + line number + class name + method signature verified against HEAD `6d34fcb` via Select-String. 16 grep anchors documented. Phantom risk concentrated in Section 2 intra-prompt symbols (same FP class as W93/W99). One sweep correction: BF stem at HEAD is **BF-265** not the W99-claimed BF-596 (W99 carried a stale W93 inheritance — corrected here).
- **Pass 3 (Captain-rule + commercial-leak audit):** Captain rule "don't defer unless no choice" satisfied — only AD-539b-d remains deferred with a crisp data-corpus forcing function; AD-539b-e parked because AD-628d-1 is its natural consumer (this AD unblocks AD-628d-1 — symmetric reasoning is sound). Banned-pattern scan: descriptor-only language used in this dispatch, the per-AD prompt, the wave-plan entry, AND this audit prose itself. Zero literal banned-pattern hits.
- **Pass 4 (anti-pattern + drift sweep):** verified frozen-dataclass field-order rule (defaulted fields after non-defaulted in `ScenarioGapLink` + `ScenarioOutcome`); verified no `else: # Only for unit tests` constructor branches; verified no `hasattr` guards for stable `runtime.emit_event` / `QualificationTest.run` APIs; verified no `create_task` fire-and-forget patterns; verified async `run` method matches `QualificationTest` Protocol via `iscoroutinefunction`-compatible signature; verified test class names match `tests/test_ad486_birth_chamber.py` precedent; verified `_wire_holodeck_scenarios` invocation point in `startup/finalize.py` main flow; verified `runtime.holodeck_gap_bridge` public-attribute shape (Wave 5 conv #1 — direct attribute, no leading-underscore Demeter exception). Single drift correction: ConnectionFactory import path corrected from `probos.storage.connection_factory` (incorrect guess) to `probos.storage.sqlite_factory.default_factory` (verified at `qualification.py:175`).
