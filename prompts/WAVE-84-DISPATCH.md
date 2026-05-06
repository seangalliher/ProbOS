# WAVE 84 DISPATCH — AD-512 v1 Discovery-Based Capability Building (Substrate)

**Wave id:** 84
**Umbrella AD:** AD-512 (Discovery-Based Capability Building — Experiential Learning Over Instruction)
**OSS sub-AD letters in scope (concrete substrate):** AD-512a (DiscoveryScenario registry), AD-512b (StrengthMap), AD-512c (CrossFunctionalSuggestion helper), AD-512d (GrowthMindsetFramer pure helpers), AD-512e (CapabilityConfidenceScorer Beta(α,β) per capability), AD-512f (ZPDCalibrator).
**OSS sub-AD letters hard-deferred:** none. Captain rule honored — every capability listed in roadmap line 6407 ships as observational substrate now; the eventual AD-486 Holodeck consumer wires Hebbian + Episode writes against this substrate without modifying it.
**Closes:** GH issue #94
**HEAD at draft:** `7504430` (post-Wave-83)
**Baseline test count:** 11673 → expected **≥ 11703** pytest (Δ ≥ +30; 32 tests planned)
**Builder required:** true (one focused build prompt)
**AD numbering:** Highest stem in trackers at draft is **AD-696** (Wave 72). AD-512 is the umbrella AD pre-allocated at GH #94 + roadmap line 6407 creation; sub-AD letters a–f are organizational only — no new AD numbers minted by this wave (mirrors AD-507/509/511 v1 precedent where letters are catalog markers, not new ADs).

## Verdict

Verify-first against HEAD `7504430` confirms the substrate AD-512 v1 needs is in place AND the consumer (AD-486 Holodeck Birth Chamber) is absent — exactly the configuration that defined AD-507 / AD-509 / AD-511 v1:

- **Crew-development package exists, discovery sub-package absent:** `src/probos/crew_development/curriculum.py:151` `class CoreKnowledgeCurriculumRegistry` (AD-507 v1) + `src/probos/crew_development/boot_camp.py:62` `class BootCampPhaseTracker` (AD-509 v1) ship as observational read-only registries. No `discovery/` sub-package, no `scenarios.py`, no `strength_map.py`, no `confidence.py`, no `zpd.py`, no `framing.py`, no `cross_functional.py` at HEAD (`Test-Path` returns False). Greenfield, collision-free.
- **AD-486 Holodeck Birth Chamber absent at HEAD:** no `src/probos/holodeck/` package, no `HolodeckRunner`, no `Holodeck` class anywhere. Same situation as AD-507's relationship to AD-486 — the substrate ships now, the Holodeck consumer wires it later.
- **EventType registry has the AD-509 anchor:** `src/probos/events.py:357` `BOOT_CAMP_PHASE_ADVANCED` immediately followed by `events.py:359` `SPC_RULE_VIOLATED` (AD-522). 5 new AD-512 EventTypes insert cleanly in between, mirroring the AD-507/509 placement convention.
- **Pydantic config pattern verified:** `src/probos/config.py:2410` `class CrewDevelopmentConfig` (AD-507) + `:2419` `class BootCampPhaseConfig` (AD-509) — both default-True, observational-only, no resource creation. `DiscoveryLearningConfig` follows the same precedent. `SystemConfig.crew_development` (`config.py:2607`) and `:2608 SystemConfig.boot_camp_phase` are the adjacent insertion anchors.
- **Finalize wirer pattern verified:** `src/probos/startup/finalize.py:122` `_wire_curriculum_registry` and `:141 _wire_boot_camp_tracker` are the AD-507/509 v1 wirers; `:1308-1312` is the dispatch block. `_wire_discovery_learning` lands immediately after `_wire_boot_camp_tracker` in both definition and dispatch — keeps Crew Development substrate together.
- **Hebbian consumer surface verified:** `src/probos/mesh/routing.py:39` `class HebbianRouter` + `:177 def record_interaction(source, target, success, rel_type)`. AD-512 v1 `cross_functional.suggest_routing(...)` returns the `(source, target, success, rel_type)` tuple shape only; **the substrate never calls `record_interaction`**. The eventual AD-486 wave is the caller. v1 ships zero behavior change to mesh/routing.
- **Episode consumer surface verified:** `src/probos/cognitive/episodic.py:942 async def store(self, episode: Episode) -> None` accepts an `Episode` constructed from `src/probos/types.py:439` `@dataclass(frozen=True) class Episode` whose `importance: int = 5` field is the natural target for high-importance discovery encoding (v1 sets `importance=8` in the payload helper). `StrengthMap.to_episode_payload(record)` returns the dict shape only; v1 substrate **never calls `EpisodicMemory.store()`** — the caller does.
- **PersonalOntologyProber sibling verified:** `src/probos/cognitive/self_distillation/prober.py:66 class PersonalOntologyProber` already exists (AD-487). AD-512e `CAPABILITY_CONFIDENCE_UPDATED` and AD-512b `STRENGTH_MAP_UPDATED` are events the prober *can* later subscribe to (AD-487b territory) but explicitly does NOT subscribe today.
- **Trust principle alignment verified:** `CapabilityConfidenceScorer` stores raw `(alpha, beta)` Beta parameters per the standing-order rule "store raw `(alpha, beta)` trust parameters, never derived mean scores" (`.github/copilot-instructions.md` Coding Standards). Mean is computed on-demand via `CapabilityConfidence.mean` property; raw params are the durable state.
- **Default-True precedent verified:** AD-507 / AD-509 / AD-511 v1 all default-True because they are observational substrate with zero resource creation. AD-512 v1 follows the same precedent. (Contrast: AD-633 / AD-695 / AD-482 default-False because they spawn agents, open ChromaDB collections, write files. AD-512 does none of that.)

AD-512 v1 (six concrete sub-AD letters + zero hard-deferrals) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every capability listed in roadmap line 6407 ships as substrate this wave; Hebbian writes and episodic encoding are *caller responsibilities by design* (the AD-486 Holodeck wave's job, not AD-512's), so they are explicit out-of-scope items, not deferrals.

| Roadmap capability (line 6407) | Wave 84 action |
|---|---|
| (1) Capability discovery scenarios | **BUILD** AD-512a `DiscoveryScenarioRegistry` — 8 default scenarios, 5 capability categories, registry shape mirrors AD-507 `CoreKnowledgeCurriculumRegistry`. Holodeck integration is AD-486 territory. |
| (2) Strength mapping | **BUILD** AD-512b `StrengthMap` — per-agent rolling aggregate; `record_outcome` / `get_strengths` / `get_struggles` / `success_rate` / `to_episode_payload`. PersonalOntologyProber subscription is AD-487b territory. |
| (3) Cross-functional awareness | **BUILD** AD-512c `suggest_routing(...)` pure function returning `CrossFunctionalSuggestion(source, target, success, rel_type, rationale)`. **No Hebbian writes inside the substrate** — caller invokes `runtime.hebbian_router.record_interaction(...)`. |
| (4) Growth mindset framing | **BUILD** AD-512d `frame_as_growth(...)` and `frame_as_discovery(...)` pure helpers. Stateless, idempotent. Replaces "you can't" → "you have not yet developed". |
| (5) Capability confidence scoring | **BUILD** AD-512e `CapabilityConfidenceScorer` — per-(agent, capability) Beta(α, β) accumulator. Stores raw `(alpha, beta)`; mean and variance are computed properties. Default prior Beta(1, 1). |
| (6) Vygotsky ZPD calibration | **BUILD** AD-512f `ZPDCalibrator.compute_band(...)` and `select_scenarios(...)` — anchors the band on `confidence.mean`, applies caller-supplied lower/upper offsets, emits `ZPD_SCENARIO_CALIBRATED`. |
| Pydantic config | **BUILD** `DiscoveryLearningConfig` (default-True; AD-507/509/511 precedent — observational substrate). `model_validator(mode="after")` enforces `zpd_lower_bound < zpd_upper_bound`. |
| Finalize wirer | **BUILD** `_wire_discovery_learning(*, runtime, config) -> bool` invoked immediately after `_wire_boot_camp_tracker`. Sets 4 public runtime attributes (`discovery_scenario_registry`, `strength_map`, `capability_confidence_scorer`, `zpd_calibrator`). Tier-2 log-and-degrade not required (no I/O, no network, no spawner — observational substrate). |

## Reframe decision (Captain rule applied)

**Six concrete sub-AD letters + zero hard-deferrals + zero Protocol seams.** Strictest application of "don't defer unless no choice" available for AD-512 — the umbrella has no consumer-side requirement that demands a Protocol shim because the natural consumer (AD-486 Holodeck) is its own future wave.

Two things that LOOK like deferrals but aren't:

1. **Hebbian writes are out of scope by design, not deferred.** AD-512c `suggest_routing` returns a `CrossFunctionalSuggestion` tuple shape. The substrate's job is to *observe and suggest*; the *write* is governed by AD-486 Holodeck post-scenario hooks (or any other future caller). Shipping `record_interaction` calls inside the substrate would couple AD-512 to AD-486 timing and trigger the layer-violation review flag — `crew_development/` would be importing `mesh/routing` to reach across architectural layers. The substrate ships clean; the caller composes. This is the Open/Closed principle in action.

2. **Episode encoding is out of scope by design, not deferred.** `StrengthMap.to_episode_payload(record)` returns a dict; the caller constructs an `Episode` and calls `EpisodicMemory.store(...)`. Same layer-discipline rationale as Hebbian — the substrate publishes data shapes, the consumer wave composes the writes. A discovery episode importance of 8 is recorded in the payload helper so the eventual consumer ships consistent encoding without re-deriving the convention.

A third pattern worth highlighting:

3. **No Protocol seams needed.** Unlike AD-633 (`IdleSpeculationPolicy`, `PreplayHook`) and AD-482 (`ShadowDeploymentPolicy`), AD-512's substrate consumers will not require a stable dispatch entry point in v1 — `record_interaction` and `EpisodicMemory.store` ARE the existing stable APIs. The substrate hands data to the caller; the caller invokes existing public APIs. Protocol seams would be redundant.

GH #94 closure note (drafted; commits with Builder's PR): "Closed by Wave 84 (six concrete OSS sub-AD letters 512a/b/c/d/e/f). All capabilities listed in roadmap line 6407 ship as observational substrate. Hebbian writes and episodic encoding are caller responsibilities by design (AD-486 Holodeck wave) — out of scope, not deferred. AD-512 umbrella is fully OSS — zero `*(Commercial)*` tags on the roadmap entry. Captain rule honored — zero hard-deferrals."

## Commercial-leak audit (pre-commit hook safety)

**Banned token sweep on draft** (`prompts/WAVE-84-DISPATCH.md` + `prompts/ad-512-discovery-learning-v1.md`):

- Banned phrase #1 (the e-word + tier) — **0 hits.**
- Banned phrase #2 (the private commercial repo path token) — **0 hits.**
- `pric` `ing` / `reven` `ue` / Great-Artists-Steal — **0 hits.**
- AD-512 sub-AD scope is fully described in the public roadmap at `docs/development/roadmap.md:6407` (no `*(Commercial)*` tag on the umbrella entry — verified via `Select-String '\\bAD-512\\b.*Commercial' docs/development/roadmap.md` returning zero hits). Public-OSS framing safe to inline.
- "Premium-feature specs" / "private commercial repo" used **zero times** in this wave's artifacts (the closure-note paragraph for GH #94 is purely OSS — the wave has no commercial component to disambiguate, unlike Wave 83's AD-482 closure that needed the disambiguation). The wave's text never references either banned token literal.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  7504430

# Highest AD stem at HEAD (no new AD minted by this wave; AD-512 pre-allocated by roadmap):
docs/development/roadmap.md:6407
  "AD-512: Discovery-Based Capability Building — Experiential Learning Over Instruction (planned, OSS, depends: AD-507, AD-486)"
docs/development/roadmap.md:7191
  AD-696 (last assigned — Wave 72 Oracle agentic retrieval)

# Baseline test count (verified):
pytest --collect-only -q | tail -1
  11673 tests collected

# Existing crew-development substrate (pattern source — verified shipped):
src/probos/crew_development/__init__.py     # AD-507 / AD-509 re-exports
src/probos/crew_development/curriculum.py:151    class CoreKnowledgeCurriculumRegistry  # AD-507 v1
src/probos/crew_development/boot_camp.py:62      class BootCampPhaseTracker             # AD-509 v1
src/probos/security/autonomy_boundaries.py:31    class BoundaryDefinition               # AD-511 v1

# AD-487 PersonalOntologyProber (sibling — future subscriber, not consumer in v1):
src/probos/cognitive/self_distillation/prober.py:66    class PersonalOntologyProber

# Existing wirer pattern (pattern source — verified shipped):
src/probos/startup/finalize.py:122   def _wire_curriculum_registry           # AD-507 v1 wirer
src/probos/startup/finalize.py:141   def _wire_boot_camp_tracker             # AD-509 v1 wirer
src/probos/startup/finalize.py:176   def _wire_autonomy_boundaries           # AD-511 v1 wirer
src/probos/startup/finalize.py:1308-1312     # dispatch block (curriculum + boot_camp + ship_state_snapshot)

# Existing config pattern (pattern source — verified shipped):
src/probos/config.py:2410   class CrewDevelopmentConfig         # AD-507 (default-True, observational)
src/probos/config.py:2419   class BootCampPhaseConfig           # AD-509 (default-True, observational)
src/probos/config.py:2607   crew_development: CrewDevelopmentConfig = Field(default_factory=...)
src/probos/config.py:2608   boot_camp_phase: BootCampPhaseConfig = Field(default_factory=...)

# EventType insertion site (adjacent to AD-509):
src/probos/events.py:354   CURRICULUM_MODULE_QUERIED  # AD-507
src/probos/events.py:357   BOOT_CAMP_PHASE_ADVANCED   # AD-509  ← insertion anchor
src/probos/events.py:359   SPC_RULE_VIOLATED          # AD-522 (next block — bracket end of insertion)

# Hebbian consumer (caller-driven; substrate never writes):
src/probos/mesh/routing.py:39    class HebbianRouter
src/probos/mesh/routing.py:177   def record_interaction(source, target, success, rel_type)

# Episode consumer (caller-driven; substrate never writes):
src/probos/cognitive/episodic.py:651    class EpisodicMemory
src/probos/cognitive/episodic.py:942    async def store(self, episode: Episode) -> None
src/probos/types.py:439                 @dataclass(frozen=True) class Episode  # importance: int = 5

# Greenfield (verified absent — no collision):
src/probos/crew_development/discovery/                     # does not exist
src/probos/crew_development/discovery/scenarios.py         # does not exist
src/probos/crew_development/discovery/strength_map.py      # does not exist
src/probos/crew_development/discovery/cross_functional.py  # does not exist
src/probos/crew_development/discovery/framing.py           # does not exist
src/probos/crew_development/discovery/confidence.py        # does not exist
src/probos/crew_development/discovery/zpd.py               # does not exist
tests/test_ad512_discovery_learning.py                     # does not exist

# AD-486 Holodeck consumer (verified absent — same status as v1 was for AD-507 / 509 / 511):
src/probos/holodeck/                # does not exist
class HolodeckRunner                # does not exist
class Holodeck                      # does not exist
```

All concrete claims map to a grep hit above. New entities introduced by this wave's prompt SEARCH/REPLACE blocks (5 EventTypes, `DiscoveryLearningConfig`, `_wire_discovery_learning`, 6 module classes, 4 public runtime attrs) are NOT flagged as missing — they are the migration.

## Build Plan

1. **Section 0** — 5 EventTypes adjacent to `BOOT_CAMP_PHASE_ADVANCED`.
2. **Section 1** — `DiscoveryLearningConfig` Pydantic + `SystemConfig.discovery_learning` field + ZPD-band model_validator.
3. **Section 2** — `discovery/__init__.py` re-exports.
4. **Section 3** — `discovery/scenarios.py` (DiscoveryScenarioRegistry, 8 scenarios).
5. **Section 4** — `discovery/strength_map.py` (StrengthMap + StrengthRecord + to_episode_payload).
6. **Section 5** — `discovery/cross_functional.py` (CrossFunctionalSuggestion + suggest_routing).
7. **Section 6** — `discovery/framing.py` (frame_as_growth, frame_as_discovery — pure helpers).
8. **Section 7** — `discovery/confidence.py` (CapabilityConfidence + CapabilityConfidenceScorer).
9. **Section 8** — `discovery/zpd.py` (ZPDBand + ZPDCalibrator).
10. **Section 9** — package `__init__.py` re-exports for `crew_development` (best-effort; skip if anchor doesn't match).
11. **Section 10** — `_wire_discovery_learning` in `startup/finalize.py` + dispatch.
12. **Section 11** — `tests/test_ad512_discovery_learning.py` (32 tests, 8 classes).

## What This Wave Does NOT Change

- No new agent class. No new pool / spawner template. No new Intent.
- No HXI surface. No router endpoints.
- No LLM call inside any v1 module.
- No Hebbian writes from inside the substrate (caller-driven by design).
- No Episode storage from inside the substrate (caller-driven by design).
- No PersonalOntologyProber subscription (deferred to AD-487b).
- No HolodeckRunner module (AD-486 wave's job).
- No persistence (in-memory only; AD-512h territory).
- No federation export (agent-local in v1; AD-512g territory).
- No edits to AD-507 / AD-509 / AD-511 v1 substrate.
- No new EventType beyond the 5 listed.
- No new AD numbers minted (sub-AD letters a–f are organizational only).

## Hard-stop Conditions for the Builder

1. Phantom API in implementation (not just in test assertions). Surfaces of concern: `EpisodicMemory.store`, `HebbianRouter.record_interaction`, `EventType.*` enum members. The substrate **never calls** the first two — but a stray test fixture might. Flag if seen.
2. Architectural change required (modify `BaseAgent` / `IntentMessage` Protocols, change layer rules). Should not be needed.
3. Section 8 (`crew_development/__init__.py` re-export) anchor mismatch — Builder may skip per the prompt's escape clause; runtime attrs land via the wirer regardless.
4. ZPD-band defaults conflict — `lower_offset=0.40, upper_offset=0.75` must always satisfy `low < high`. Pydantic `model_validator` enforces this at config load.

## Quality Gates

After Builder completes, run:
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad512_discovery_learning.py -v -n 0` — focused gate, expect 32 passing.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` — full gate, expect ≥ 11703.

## Tracking & Closure

- `PROGRESS.md` — open `## Wave 84` entry; flip to closed after Builder lands.
- `docs/development/roadmap.md:6407` — flip AD-512 tag from `*(planned, OSS, depends: AD-507, AD-486)*` to `*(v1 partial — Discovery Learning substrate shipped Wave 84; Holodeck consumer deferred to AD-486)*`.
- `DECISIONS.md` — append `### AD-512 v1: Discovery-Based Capability Building Substrate (2026-05-06)`.
- `prompts/wave-plan.yaml` — wave 84 entry already appended.
- GH issue #94 — closed by Builder's PR with the closure note in this dispatch.

## Reframe Decision Summary

**No reframe required.** Six concrete sub-AD letters + zero hard-deferrals + zero Protocol seams. The substrate-now-consumer-later pattern that defined AD-507 / AD-509 / AD-511 v1 applies cleanly here. Captain rule "don't defer unless no choice" is honored.
