# WAVE 99 DISPATCH — AD-486 v1 Holodeck Birth Chamber: Graduated Cognitive Onboarding (closes #24)

## Wave summary

**Umbrella:** Holodeck Birth Chamber — Graduated Cognitive Onboarding (`docs/development/roadmap.md:4128-4136` *Cognitive Birth & Agent Maturation (AD-486–489)*). Replaces the current "all-stimuli-at-once" cold-start pattern with a five-phase chamber that gates Ward Room subscription and proactive-loop dispatch behind completion-criteria predicates (NOT timers), with sequential department activation per the AD spec (Security/Operations → Engineering/Science → Medical) and trait-adaptive calibration pacing per AD-494. Single AD wave; AD-486 is its own substrate (no other AD-486-letter ships in W99).

**Wave kind:** Source-modifying single-AD v1 — additive new package `src/probos/holodeck/` (~720 LOC across 6 modules) plus two narrow production graduation gates in `proactive.py` and `assignment.py`. Existing AD-499 naming-ceremony, AD-628e mentor-announcer, AD-509 boot-camp-tracker, and AD-638 boot-camp-coordinator paths are preserved byte-for-byte; the chamber is a parallel layer gated by a default-False flag (per AD-695 transitional-flag precedent). v1 ships dormant — operators flip `holodeck_birth_chamber.enabled=True` after Phase α validation.

**Reframe decision — ship full v1, NO scope split (Captain rule "don't defer unless no choice" applied):**

The original draft considered four forcing-function deferrals (NoOp affect / circuit-breaker integration / trait-adaptive pacing / Holodeck construct generalization). On second-pass evaluation against HEAD `4bdf23a`, three of those deferrals failed the Captain rule and were absorbed into v1:

1. **AD-488 circuit-breaker Phase 4 integration:** `CognitiveCircuitBreaker.should_allow_think(agent_id)` is shipped (AD-488 `docs/development/roadmap.md:4133` "done, OSS"). Wiring it as a sub-predicate inside `gate_ship_records` is ~10 LOC + 1 test. The original "AD-486c — Cognitive load monitoring during Phase 4" deferral was speculative scaffolding — we have the consumer at HEAD. **Absorbed into v1.**
2. **AD-494 trait-adaptive calibration pacing:** `PersonalityTraits.conscientiousness` is shipped at `crew_profile.py:66`; `CallsignRegistry.get_profile(agent_type)` is the existing access pattern at `:406` (and `acm.py:312` already reads `crew_profile.personality.neuroticism` via the same pattern). Mapping conscientiousness → calibration multiplier (≥0.7 → 2.0x, ≤0.3 → 0.5x, else 1.0x) is ~15 LOC + 3 tests in `gates.py`. The original "AD-486d — Trait-adaptive pacing" deferral was speculative — sea-trial evidence at `docs/development/roadmap.md:4130` (Sentinel vs Medical) is precisely what motivates this multiplier. **Absorbed into v1.**
3. **`DepartmentActivationScheduler` sequential activation:** the AD spec at `:4130` makes this an invariant ("Departments are activated sequentially with observation windows"). Shipping the chamber without sequential activation would violate the AD spec on day one. The observation criterion is "previous group reaches SELF_DISCOVERY or higher" — pure phase-state observation, no timers, no LLM calls. **In v1 from the start.**

Two genuine forcing-function deferrals remain after the reframe:

- **AD-486b — LLM-based affective baseline check.** `NoOpAffectiveBaselineCheck` v1 always returns `("stable", 1.0)`. A real implementation needs a corpus of `record.affective_observations` from a Phase α cohort to calibrate against — that corpus does not exist at HEAD. Building the analyzer speculatively against the NoOp would test scaffolding rather than substance. **Forcing function:** chamber runs under `enabled=True` for one full cohort (~10 admissions, all reaching GRADUATED) AND first cross-phase `affective_observations` show non-NoOp signal divergence patterns.
- **AD-486e — Holodeck "construct" abstraction.** Generalizes `BirthChamber` into a reusable `Construct` Protocol so AD-510 Team Simulations (issue #92) and AD-539b TRAINO Holodeck scenarios (issue #12) can register additional constructs against a shared lifecycle. **Forcing function:** AD-510 prompt drafted AND a second concrete construct designed. Without a second consumer the abstraction is speculative; the package layout `src/probos/holodeck/` is greenfield-named to support future generalization without churn.

The reframe ships all five AD-486 invariants (5 phases, completion-criteria gating, sequential activation, trait-adaptive pacing, Westworld Principle adherence via Code-of-Conduct event tagging) in one Builder cycle.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-486 v1 — Holodeck Birth Chamber** (50-test plan, `prompts/ad-486-holodeck-birth-chamber-v1.md`). Six new modules under `src/probos/holodeck/`: `__init__.py` (public surface), `phases.py` (HolodeckPhase + PHASE_ORDER + next_phase helper), `affect.py` (AffectiveBaselineCheck Protocol + NoOpAffectiveBaselineCheck + AffectiveObservation dataclass), `gates.py` (5 phase predicates + conscientiousness_multiplier helper), `scheduler.py` (DepartmentActivationScheduler with phase-state observation criterion), `chamber.py` (BirthChamber orchestrator with admit/try_advance/is_graduated public API + late-bound services + run_advance_loop background task). Six new EventTypes under the existing AD-509 cluster in `events.py:385`. New Pydantic `HolodeckBirthChamberConfig` adjacent to `OnboardingConfig` at `config.py:1748` with `enabled=False` default. New finalize wirer `_wire_birth_chamber` in `startup/finalize.py:141` adjacent to `_wire_boot_camp_tracker`. New `AgentOnboardingService.set_birth_chamber` setter + admission hook in `wire_agent` post-naming-ceremony. Two production gates: `proactive.py:498-518` (`_run_cycle` skips pre-graduation agents) and `assignment.py:184/310` (Ward Room subscription deferred via `chamber.queue_pending_subscription`, drained at graduation). 50 focused tests at `tests/test_ad486_birth_chamber.py` across 8 classes (5 enum + 4 config + 3 record + 10 gates + 12 chamber + 4 graduation + 7 scheduler + 5 wirer/onboarding).

**v1 OUT scope (deferred with explicit forcing functions, NOT minted as new GH issues):**

- **AD-486b — LLM-based affective baseline check.** Forcing function: chamber runs under `enabled=True` for one full cohort AND first cross-phase `affective_observations` show non-NoOp signal divergence. v1 ships descriptor-only with the upgrade path documented in `affect.py` module docstring.
- **AD-486e — Holodeck "construct" abstraction.** Forcing function: AD-510 prompt drafted (issue #92) AND a second concrete construct designed. Until then the abstraction is speculative — generalizing with one consumer would test scaffolding rather than substance.

The four roadmap forward-references that AD-486 transitively unblocks (AD-509e trait-adaptive pacing, AD-510 team simulations, AD-511c boundary training scenarios, AD-628d Holodeck integration) all remain as already-tracked downstream consumers — Wave 99 mints zero new GH issues.

**The fleet-level overlay surface (out-of-repo):**
The OSS BirthChamber + DepartmentActivationScheduler + 5 phase gates form the architectural surface. Advanced templated onboarding tracks (curriculum-driven mentor assignment beyond AD-628e's announcer, milestone-progression workflows, cohort-comparison analytics across instances) are class-extension territory under the private commercial repository path token surface. v1 ships zero closed-source content — descriptor-only references throughout this dispatch and the per-AD prompt. Two additional fleet-level surfaces are also out-of-repo: cross-instance cohort phase-progression telemetry and per-fleet Phase-α validation dashboards.

## AD numbering

Highest AD stem at HEAD `4bdf23a` is **AD-696** (verified via numeric sweep across PROGRESS.md + roadmap.md + wave-plan.yaml; W98 archive confirms "Highest AD stem at HEAD `632398f` is AD-696" and W98 minted zero new ADs). Highest BF: **BF-596** (W98 inheritance). W99 mints **zero new AD numbers** (AD-486 already exists as planned at `docs/development/roadmap.md:4130`; AD-486b and AD-486e are letter-suffixed forcing-function deferrals, not GH tracking issues). W99 mints **zero new BF numbers**. **Current highest: AD-696, BF-596.**

## Verify-first against HEAD `4bdf23a`

```
git rev-parse HEAD
  4bdf23a (HEAD -> main, origin/main, origin/HEAD) Wave 98 archive: AD-543-549 native SWE harness (#13)

git ls-files src/probos/holodeck/
  (no output — package does not exist; greenfield)

grep -rn "AD-486\|HolodeckBirthChamber\|BirthChamber" src/probos/
  src/probos/agent_onboarding.py:614:  prose mention only
  src/probos/config.py:2670:           prose mention only
  src/probos/crew_development/discovery/*:  prose mentions only (forward-references)
  (zero live classes, zero imports — true greenfield)

grep -n "def wire_agent\|_mentor_announcer\|_orientation_service and self._config.orientation.enabled" src/probos/agent_onboarding.py
  83:  self._mentor_announcer: Callable[[str, str], Any] | None = None
  118: async def wire_agent(self, agent: Any) -> None:
  277: if is_crew and self._orientation_service and self._config.orientation.enabled:

grep -n "class OnboardingConfig\|onboarding: OnboardingConfig" src/probos/config.py
  1748: class OnboardingConfig(BaseModel):
  2760:     onboarding: OnboardingConfig = OnboardingConfig()

grep -n "BOOT_CAMP_PHASE_ADVANCED\|^class EventType" src/probos/events.py
  385: BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

grep -n "_wire_boot_camp_tracker" src/probos/startup/finalize.py
  141: def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
  1457:     if _wire_boot_camp_tracker(runtime=runtime, config=config):

grep -n "eligible_agents.append" src/probos/proactive.py
  504:             eligible_agents.append(agent)

grep -n "await self._ward_room.subscribe" src/probos/assignment.py
  184:                  await self._ward_room.subscribe(agent_id, ch.id)
  310:                  await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)

grep -n "class CoreKnowledgeCurriculumRegistry\|def list_by_phase" src/probos/crew_development/curriculum.py
  154: class CoreKnowledgeCurriculumRegistry:
  186:     def list_by_phase(self, phase: str) -> tuple[CurriculumModule, ...]:

grep -n "class PersonalOntologyProber\|async def probe_domain" src/probos/cognitive/self_distillation/prober.py
  66:  class PersonalOntologyProber:
  121: async def probe_domain(self, agent_id: str, domain: str) -> ProbeResult:

grep -n "should_allow_think\|def should_allow_think" src/probos/cognitive/circuit_breaker.py
  (method exists per AD-488; verified via cross-reference at proactive.py:545)

grep -n "    conscientiousness:" src/probos/crew_profile.py
  66:  conscientiousness: float = 0.5

grep -n "def get_profile" src/probos/crew_profile.py
  406:  def get_profile(self, agent_type: str) -> dict | None:
```

All concrete claims in `prompts/ad-486-holodeck-birth-chamber-v1.md` map to one of:
1. A grep hit shown above (existing anchor preserved by SEARCH/REPLACE).
2. A new symbol introduced by this prompt's own SEARCH/REPLACE blocks (Section 0 EventTypes, Section 1 config model + field, Section 2 holodeck/ package files, Section 3 _wire_birth_chamber + invocation, Section 4 set_birth_chamber + admission hook, Section 5 gate insertions).

Phantom-API pre-check on the prompt body via `scripts/phantom-api-precheck.ps1`:
- Expected FP class: intra-prompt-introduction phantoms (BirthChamber.X, HolodeckPhase.X, BirthChamberRecord.X, NoOpAffectiveBaselineCheck.X, DepartmentActivationScheduler.X, AffectiveBaselineCheck.X — all defined in Section 2 of this prompt). Same FP class as Waves 27-49 + 96-98.
- 0 NEW genuine phantoms expected.
- Builder runs the pre-check; documented FP count goes into the build report.

## Pre-flight checklist

```powershell
# 1. Confirm clean working tree
git status --short
# expected: empty (no tracked or untracked source under src/, tests/, prompts/ except the wave 99 prompts)

# 2. Confirm baseline pytest count
.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile
# expected: 12210 passed (per Captain's W99 dispatch baseline)

# 3. Confirm no holodeck package exists
git ls-files src/probos/holodeck/
# expected: empty

# 4. Confirm AD-486 not yet shipped in tracker
Select-String -Path docs/development/roadmap.md -Pattern '^**AD-486:.*\*\(planned' | Select-Object -First 1
# expected: line 4130 still says *(planned, OSS)*
```

## Builder per-prompt workflow

Standard Wave-99 workflow applies (per `prompts/BUILDER-EXECUTION-PLAN.md`):

1. Read `prompts/ad-486-holodeck-birth-chamber-v1.md` end-to-end.
2. Apply Section 0 (events.py — 1 SEARCH/REPLACE pair).
3. Apply Section 1 (config.py — 2 SEARCH/REPLACE pairs).
4. Create `src/probos/holodeck/__init__.py` (Section 2 file 1/6) + `phases.py` + `affect.py` + `scheduler.py` + `gates.py` + `chamber.py`.
5. Apply Section 3 (finalize.py — 2 SEARCH/REPLACE pairs).
6. Apply Section 4 (agent_onboarding.py — 2 SEARCH/REPLACE pairs).
7. Apply Section 5 (proactive.py — 1 SEARCH/REPLACE pair; assignment.py — 2 SEARCH/REPLACE pairs).
8. Create `tests/test_ad486_birth_chamber.py` with 50 tests across 8 classes per the test plan in Section 4 of the per-AD prompt.
9. Run focused gate: `.venv\Scripts\pytest.exe tests/test_ad486_birth_chamber.py -v -n 0` → 50 passed expected.
10. Run full gate: `.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile` → ≥12260 passed expected (Δ +50).
11. Apply Section 6 tracker updates (DECISIONS.md decisions-era-4-evolution.md status flip, roadmap.md status flip, PROGRESS.md close paragraph append at file head, wave-plan.yaml entry append).
12. Phantom-API pre-check: `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-486-holodeck-birth-chamber-v1.md` — verify FP-only output (intra-prompt-introduction class).
13. `git add -A; git commit -m "AD-486 v1: Holodeck Birth Chamber — graduated cognitive onboarding (5 phases, gates, sequential dept activation, trait-adaptive pacing) (+50 tests)"`.
14. `git push`.
15. Archive: `git mv prompts/WAVE-99-DISPATCH.md prompts/archive/ ; git mv prompts/ad-486-holodeck-birth-chamber-v1.md prompts/archive/ ; git add -A ; git commit -m "Wave 99 archive: AD-486 v1 Holodeck Birth Chamber (#24)"`.
16. `gh issue close 24 -c "<canonical Wave 99 close paragraph from PROGRESS.md head>"`.

## Hard-stop conditions

Surface to user (do NOT continue) ONLY if:

- **Phantom API in implementation source.** Section 2's chamber.py invokes `prober.probe_domain` (verified at HEAD `prober.py:122`); `curriculum_registry.list_by_phase` (verified at `curriculum.py:186`); `circuit_breaker.should_allow_think` (verified live per AD-488 status at roadmap.md:4133); `callsign_registry.get_profile` (verified at `crew_profile.py:406`); `episodic_memory.count_for_agent` (used by AD-638 BootCampCoordinator at `boot_camp.py:50`). Any source-code phantom not introduced by this prompt is a hard stop.
- **Architectural change required.** Modifying `BaseAgent`, `IntentMessage` Protocol, `AgentOnboardingService` constructor signature beyond the additive setter, or `ProactiveCognitiveLoop`/`AssignmentService` constructor signatures — surface and revise the prompt.
- **Test-gate-baseline drift > 5 tests.** If full gate at Step 10 shows |delta - 50| > 5, surface for triage. Allowable: +50 ± 5. Anything else (e.g., quarantine count rising or pre-existing flake re-tripping) needs a BF entry decision before proceeding.
- **Pre-commit hook trips on banned literal.** All audit prose in this dispatch and the per-AD prompt uses placeholder forms ("the private commercial repository", "the paid offering tier", "class-extension territory under the private commercial repository path token surface"). Zero literal banned-pattern hits expected; if the hook trips, the violation is in Builder-introduced text and must be revised in-place — no `--no-verify` shortcut.

## Wave-specific reminders for known false positives

- **`runtime.birth_chamber` is greenfield** — verified zero hits at HEAD before edit. Pre-check should NOT flag the new attribute as `runtime_X_phantom`.
- **`runtime.department_activation_scheduler` is greenfield** — same.
- **`AffectiveBaselineCheck` Protocol member access (`prober.probe_domain` etc.)** — Pattern B receivers like `services.get("episodic_memory")` resolve to `Any` in the prompt body; pre-check helper safe-skips. Same FP class as Waves 27-49.
- **`HolodeckBirthChamberConfig.X` attribute access** — config field references introduced in Section 1 of THIS prompt; pre-check intra-prompt-introduction FPs are expected and documented.
- **`runtime.boot_camp_tracker` and `runtime.curriculum_registry`** — both verified live at HEAD per `startup/finalize.py:152` and `:133` respectively. Not phantoms.

## Commercial-leak audit

The pre-commit hook at `.git/hooks/pre-commit` checks 11 banned literals. This dispatch and `prompts/ad-486-holodeck-birth-chamber-v1.md` use placeholder forms only, never the literal patterns. Audit table (descriptor only — does NOT reproduce any banned literal text):

| Hook pattern class | Placeholder used in prompt | Count of literal matches expected |
|---|---|---|
| Pricing-cadence dollar-amount strings | "the paid offering tier" | 0 |
| Multi-year revenue forecasting language | (not referenced) | 0 |
| Investor-deck contraction acronyms | (not referenced) | 0 |
| Outcome-aligned pricing model | (not referenced) | 0 |
| Methodology slogan (top-cog absorption) | (not referenced) | 0 |
| Methodology slogan (pattern absorption) | (not referenced) | 0 |
| Private-repo path token | "the private commercial repository" | 0 |
| Private-overlay synonym | (not referenced) | 0 |
| Tier-naming overlay synonym | (not referenced) | 0 |
| Premium-tier marketing label | "the paid offering tier" | 0 |
| Self-host-overlay synonym | (not referenced) | 0 |

The audit prose **itself** uses placeholders only — no literal patterns appear in this dispatch or in the per-AD prompt at any nesting level (descriptor table above intentionally describes the pattern classes without quoting them). Pre-commit hook should exit 0 against the staged prompts.

The OSS BirthChamber + DepartmentActivationScheduler + 5 phase gates form the architectural surface. The advanced templated-onboarding-track depth overlay (curriculum-driven mentor assignment beyond AD-628e's announcer, milestone-progression workflows, cross-instance cohort-comparison analytics) is class-extension territory under AD-452's class-extension framework and lives in the private commercial repository path token surface. v1 ships zero closed-source content — descriptor-only references throughout.

## Pre-commit deletion sanity

This wave is overwhelmingly additive:
- 1 new package (6 new files under `src/probos/holodeck/`).
- 1 new test file (`tests/test_ad486_birth_chamber.py`).
- 6 new EventType lines in `events.py` (additive).
- 1 new Pydantic model + 1 new field in `config.py` (additive).
- 1 new wirer function + 1 new invocation in `finalize.py` (additive).
- 1 new attribute slot + 1 new setter + 1 new admission block in `agent_onboarding.py` (additive).
- 3 SEARCH/REPLACE in production gates (`proactive.py` + `assignment.py`) — each replaces one existing line with a 5-8 line gated branch (net +12 lines per site, no deletions).
- 4 tracker updates (DECISIONS era-4, roadmap.md, PROGRESS.md head, wave-plan.yaml).

Maximum expected single-file deletion count: ~3 lines (line-replacement granularity in the production gate SEARCH/REPLACE blocks). Well below the 200-line surprise-deletion threshold. No file is rewritten or moved.

## Build groups with dependency DAG

```
Group 1 (substrate, parallel-safe):
  - events.py EventTypes (Section 0)
  - config.py HolodeckBirthChamberConfig (Section 1)

Group 2 (package, depends on Group 1):
  - holodeck/phases.py
  - holodeck/affect.py            (depends on phases.py)
  - holodeck/scheduler.py         (depends on phases.py)
  - holodeck/gates.py             (depends on phases.py + chamber.py forward-ref via TYPE_CHECKING)
  - holodeck/chamber.py           (depends on phases.py, affect.py, gates.py, events.py)
  - holodeck/__init__.py          (depends on all)

Group 3 (wiring, depends on Groups 1+2):
  - startup/finalize.py _wire_birth_chamber (Section 3)
  - agent_onboarding.py set_birth_chamber + admission hook (Section 4)

Group 4 (production gates, depends on Group 3):
  - proactive.py _run_cycle gate (Section 5a)
  - assignment.py subscription deferral (Section 5b/c)

Group 5 (tests, depends on Groups 1-4):
  - tests/test_ad486_birth_chamber.py (50 tests)

Group 6 (trackers, depends on green test gate):
  - DECISIONS.md / roadmap.md / PROGRESS.md / wave-plan.yaml
```

Builder applies in order; each group is a single commit-worthy unit but the wave is committed once at Step 13 after all groups are green.

## Build report and post-sweep procedures

Builder produces `prompts/build-reports/ad-486-build.md` capturing:
1. Final test count delta (target +50).
2. Phantom-API pre-check FP/genuine breakdown.
3. Any drift-fix decisions (line-number drift, anchor adjustments).
4. Commercial-leak audit confirmation (hook exit 0).
5. Hard-stops triggered (none expected).
6. Closing the GH issue: paste of `gh issue close 24 -c "<paragraph>"` confirmation.

After commit + push + archive + close, Wave 99 is done.

---

**Reviewer's note for Captain (Architect-internal):** four review passes were applied before this dispatch was finalized. Pass summaries below for audit:

1. **Pass 1 — verify-first sweep.** Caught initial draft references to `_wire_personal_ontology_prober` (verified — exists at `finalize.py:1257`) and `runtime.curriculum_registry` (verified at `:133`). Caught initial assumption that `BootCampPhaseTracker` had AD-486 phase shape — corrected: AD-509 ships its OWN enum (`ORIENTATION/CORE_KNOWLEDGE/A_SCHOOL/CALIBRATION/INTEGRATION`); AD-486 ships its OWN distinct enum (`ORIENTATION/CALIBRATION/SELF_DISCOVERY/SHIP_RECORDS/WARD_ROOM_INTEGRATION`). Two trackers coexist orthogonally.

2. **Pass 2 — reframe sweep.** Re-evaluated four planned forcing-function deferrals against Captain rule "don't defer unless no choice." Three absorbed into v1 (AD-488 circuit-breaker integration, AD-494 trait-adaptive pacing, sequential department activation). Two retained as forcing-function children (AD-486b LLM affect, AD-486e construct abstraction) — both have concrete forcing functions and lack consumers at HEAD.

3. **Pass 3 — anti-pattern sweep.** Verified: no `else: # Only for unit tests` fallback branches; no defensive `getattr(obj, "method", None)` for APIs defined in this prompt (only for cross-prompt APIs documented in finalize.py wirer); no `hasattr` for cross-module wiring (used only in production gate path where chamber may be None — defensive runtime check, not test-fixture defensive); no bare mutable defaults in Pydantic (`department_order` uses `Field(default_factory=lambda: [...])`); BirthChamberRecord has `agent_id` and `agent_type` non-defaulted before defaulted `current_phase` etc. (frozen-not-required dataclass; field ordering still respected); `_birth_chamber` is a private slot but `set_birth_chamber` is the public setter so cross-module wiring uses the public path.

4. **Pass 4 — commercial-leak + tracker audit.** Audit table descriptor-only — no literal banned-pattern text appears anywhere in this dispatch or the per-AD prompt at any nesting level. Tracker updates: DECISIONS era-4 status flip (verified anchor at `:1168`), roadmap.md status flip (verified anchor at `:4130`), PROGRESS.md head append (file format verified), wave-plan.yaml append (format matches W98 entry). Closes #24 cleanly via `gh issue close 24 -c <paragraph>` invocation in Step 16. Zero new GH issues minted (AD-486b/AD-486e are roadmap forward-references with explicit forcing functions, not tracking issues).
