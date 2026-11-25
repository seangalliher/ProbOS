# AD-1355 (#1700) S1: the AD-486 Birth Chamber and the department activation scheduler deleted, with their config, wirer, seams, events and tests

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-24

**Revised by:** the orchestrator (`claude-sonnet-5.5`), 2026-11-25, after proving every pair on an oracle tree at the B14 head `ba2b3a4b`: the `{U+XXXX}` placeholders of the draft are the characters they name (the contract tools run with `--utf8 U+03B1,U+2014,U+2192`); the census numbers of P-46 and P-46a are measured; four pairs are added, P-47a (the `EventType` row of the architecture baseline goes stale, section 7 step 4), P-53 and P-54 (the two measured AD-1152 golden values, section 7 step 5) and P-55 (the pin of the `srp-size` count 92 in `tests/test_ad1270b_architecture_fitness.py`, which the draft's M3 focused list fails on: 90 after P-47 and P-47a); the Builder runs no test and no script, so sections 4, 5 and 7 say what the orchestrator runs; and one claim of the draft that the oracle disproved is corrected (section 15, the SRP row); and P-26 and P-28 delete their whole line (the draft's empty REPLACE left a blank line inside a dict literal of `tests/test_ad1270e2g_crew_models.py`: each SEARCH now carries the row that follows and its REPLACE keeps it).

**Status:** build-ready. Drafted on `8704d194`; it builds after B14 (AD-1358 S2) merges, and every pair is re-proved on that base (here the B14 head `ba2b3a4b`, whose tree is the base after the merge). No new AD or BF number: this is slice S1 of #1700. Ceiling AD-1361, next AD-1362 (`scripts/ad_ceiling.py`); BF-993 (`docs/development/open-ads-report.md:32`). **Captain:** nothing parked. The Captain may overrule D1 (old key ignored without a warning) and D2 (six event types deleted, not reserved). **Dependencies:** none. **Tests:** one new file (18 cases); 2 files deleted; 9 existing test files updated by pairs; one golden fixture (two values) refreshed by measurement.

**Prose rule (phantom pre-check):** outside fenced blocks, deleted names never appear in `runtime.<name>` or `Class.member(` form, because the pre-check reads prose. All fences are untagged.

## 1. Problem

The AD-486 Birth Chamber (`holodeck/chamber.py`, `gates.py`, `phases.py`, `affect.py`) and the `DepartmentActivationScheduler` (`holodeck/scheduler.py`) are built only when `holodeck_birth_chamber.enabled` is True. Its default is False (`config_models/crew.py:208`), and the tracked yaml sets false (`config/system.yaml:855`).

With the switch on, the chamber admitted almost no one and graduated no one (#1700, Problem items 1 to 10). The scheduler is built at `startup/finalize.py:1136-1140` (the issue's `:1070-1074` on `5706fe3b`), and nothing in `src/` calls any of its methods.

Dead surfaces:
- the config model and its field (`crew.py:198-230`, `config.py:3947`);
- the wirer (`finalize.py:1102-1182`, called at `:4285`);
- the onboarding seam (`agent_onboarding.py:84-85`, `:101-103`, `:354-379`);
- the assignment seam (`assignment.py:92-93`, `:114-116`, `:204-215`, `:344-355`);
- the proactive skip (`proactive.py:1133-1138`);
- six `HOLODECK_*` event types (`events.py:491-497`, `event_persistence.py:269-274`) that only the chamber emits;
- two test files.

## 2. Solution

Delete the five modules and every surface listed above. The holodeck package keeps AD-539b's scenarios and AD-510's team simulations, with their 14 exports unchanged. A config that still carries `holodeck_birth_chamber:` keeps loading, because unknown keys are ignored (D1), and the tracked yaml stops carrying it.

Generated artifacts move by tool or measurement (section 7 of this contract, below the pairs). One census file proves the deletion.

Rejected heavier designs:
- A warned legacy key: new loader machinery for a key whose only effect was off by default.
- Keeping the six event types as reserved values: members with no producer.
- A differential boot test: it would exercise deleted code.

## 3. Decisions

- **D1.** An old key is ignored, with no warning, and the tracked yaml drops the section. `SystemConfig` has no `model_config` (`config.py:3909`), and `load_config` is a plain `model_validate` (`:4157-4167`); 4c and BF-926 set the precedent.
  - An operator who set `enabled: true` now gets the default path. Admitted agents are no longer held at `ship_records`, and their assignment subscriptions are no longer queued.
  - The Captain's checkout sets false (`D:\ProbOS\config\system.yaml:856-857`).
- **D2.** Delete the six AD-486 members:
  - `HOLODECK_AGENT_ADMITTED`
  - `HOLODECK_PHASE_ENTERED`
  - `HOLODECK_PHASE_GATE_PASSED`
  - `HOLODECK_PHASE_GATE_BLOCKED`
  - `HOLODECK_GRADUATION`
  - `HOLODECK_AFFECTIVE_BASELINE_OBSERVED`

  Delete their `GRANDFATHERED` rows too, and keep the four `HOLODECK_SCENARIO_*` members. Pins move: `len(EventType)` 396 -> 390, `GRANDFATHERED` 354 -> 348, `_NOT_ROUTED` 366 -> 360; the golden stays at 356. Replay is safe:
  - grandfathered members are never routed (`event_persistence.py:477-479`);
  - `_resolve_member` returns none for an unknown name (`durable_events.py:566-571`);
  - `ui/src` has no consumer.
- **D3.** The census file `tests/test_ad1355_birth_chamber_removed.py` scans `src/`:
  - every file except `__pycache__` and files that hold a NUL byte;
  - for `BirthChamber`, `DepartmentActivationScheduler`, `birth_chamber` and `holodeck_birth_chamber`.

  Controls prove that it reads the real tree and reports a planted reference. Prose "AD-486" is not a term.
- **D4.** The proof is:
  - the census rows R1-R10 (section 10), run once as the campaign of record;
  - the named default-path suites, green on the candidate;
  - probes P1-P3 on the base (section 10).
- **D5.** No new number.
  - PROGRESS head `**AD-1355 S1 (...)` gives ledger state `allocated-open` ("mentioned").
  - The DECISIONS heading starts `Acclimation S1`, because a heading that starts with `AD-1355` resolves the number `shipped` (`gen_ad_ledger.py:217-220`, `:483-484`).
  - #1700 stays open.
- **D6.** The Builder deletes files with `Remove-Item -LiteralPath`, and the orchestrator stages them by explicit path. M1, M2 and M3 are three local commits under one review round.
- **D7.** Section 12 lists the review properties. `tests/test_ad486_birth_chamber.py` covers only deleted code, and surviving pieces keep their own tests (section 12, item 11).

## 4. Milestones

Commit subjects carry no AD or BF token:
- **M1:** `Acclimation S1 M1: the Birth Chamber, the department scheduler, their config, wirer, seams and event types are deleted (#1700)`
- **M2:** `Acclimation S1 M2: tests that named the deleted chamber, scheduler, config model or event types follow the deletion (#1700)`
- **M3:** `Acclimation S1 M3: config reference, facade, profile and architecture baselines, the default-config golden, docs and trackers follow the deletion (#1700)`

**M1 build order (Builder):**
1. Apply P-1 to P-21 and create the census file of section 6.13, each followed by its blob check.
2. Run the section 6.1 `Remove-Item` commands.

The Builder runs no test and no script. Before the build the orchestrator ran the census file on the base: 16 failed and 2 passed; the two that pass are `test_the_census_reads_the_real_tree` and `test_the_census_reports_a_planted_reference`, the controls of the census instrument itself. It then runs the M1 focused gate (section 11) on the committed candidate.

**M2 build order (Builder):** apply P-22 to P-40. The orchestrator then runs the M2 focused gate.

**M3 build order:** the orchestrator runs section 7's steps 1 to 6 on the oracle and proves each diff; the Builder applies the pairs P-41 to P-55 (the brief's table carries their blob ids), and the generated files (the facade baseline, the config reference and the ledger pair) are committed from the oracle's blobs. The orchestrator then runs the M3 focused gate and the script checks, regenerates the ledger and runs `--preflight-only`.

## 5. Builder may and may not

**May:**
- edit the files paired here, by the pairs only;
- run section 6.1's `Remove-Item` commands.

**May not:**
- run any test, any script or any git command;
- edit an unpaired file;
- delete or loosen a test beyond the listed removals;
- touch `tests/fixtures/file_durations.json` (stale keys are tolerated; it is regenerated only from a canonical gate), `prompts/`, or the history files (`PROGRESS.md` and `DECISIONS.md` bodies beyond P-51/P-52, era files, roadmaps, `docs/research/`);
- run `gen_ad_ledger.py` (the orchestrator does);
- add a configuration field.

## 11. Gates

Interpreter: `d:/ProbOS/.venv/Scripts/python.exe`. Pytest: `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

**M1 focused gate:**
```
tests/test_ad1355_birth_chamber_removed.py tests/test_onboarding.py tests/test_ad423c_onboarding.py tests/test_new_crew_auto_welcome.py tests/test_assignment.py tests/test_api_assignment.py tests/test_proactive.py tests/test_ad1343_stop_crossing.py tests/test_ad1346_admission_shadow_routing.py tests/test_bf909_proactive_young_clock.py tests/test_ad507_curriculum.py tests/test_ad487_self_distillation.py tests/test_ad539b_holodeck_scenarios.py tests/test_ad510_team_simulations.py tests/test_finalize.py tests/test_ad1270a_startup_receipts.py tests/test_events.py tests/test_layer_boundaries.py tests/test_runtime_m365_wiring.py tests/test_bf926_config_readers.py
```

**M2 focused gate:** M1's list plus:
```
tests/test_ad1270_boot_camp_tracker_retired.py tests/test_ad1270e2g_crew_models.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_durable_event_seam.py tests/test_bf903_ward_room_scope.py
```

**M3 focused gate:** M2's list plus:
```
tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1270_dormant_classes.py tests/test_ad1184_ad_ledger.py
```
Then each with `-P`:
- `scripts/check_config_facade.py --check`
- `scripts/gen_config_reference.py --check`
- `scripts/check_config_profiles.py --check`
- `scripts/check_architecture_principles.py --check` (`srp-size=90`)
- `scripts/check_dormant_classes.py --check` (paste its whole output)
- `scripts/check_seam_contracts.py --check`
- `scripts/check_store_registry.py --check`

**Preflight** (`scripts/run_test_gate.py --preflight-only`): which phases fail if a pair or step is missing.

| Phase | Fails when |
|---|---|
| `config-reference` | section 7 step 2 not run |
| `config-profiles` | P-45 missing (stale `unclassified_flags` row) |
| `config-facade` | step 1 not run |
| `ad-ledger` | P-51/P-52 applied but step 8 not run |
| `architecture-fitness` | P-47 or P-47a missing (stale `BirthChamber` or `EventType` srp-size row) |
| `seam-contracts`, `store-registry` | no change expected |
| `compile` | does not catch a dangling import |

Outside the preflight, tests catch these: the AD-1152 golden (P-44, P-53 and P-54), the architecture fitness count pin (P-55), the facade pins (P-41 to P-43), the e2g tables (P-24 to P-31), the event pins (P-32 to P-34), and the tracked yaml (P-21).

**Broad gate, once:**
```
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1355-s1 --receipt logs/gates/ad1355-s1.receipt.json
```

## 14. Verified Against Codebase (2026-11-24, on `8704d194`)

| Claim | Evidence |
|---|---|
| Wirer and call | `startup/finalize.py:1102` def `_wire_birth_chamber`; `:1109-1111` returns False unless enabled; `:1136-1140` scheduler built; `:1164` task only when enabled; `:4285` call |
| Default off | `config_models/crew.py:208` `enabled: bool = False`; `config/system.yaml:855` `enabled: false`; `D:\ProbOS\config\system.yaml:857` `enabled: false` |
| Field and re-exports | `config.py:137`, `:3947`; `config_models/__init__.py:131`, `:284` |
| Onboarding seam | `agent_onboarding.py:84-85`, `:101-103`, `:356-359` (`_birth_chamber is not None` is tested before the config is read) |
| Assignment seam | `assignment.py:92-93`, `:114-116`, `:205-215`, `:345-355` |
| Proactive skip | `proactive.py:1136-1138` `getattr(rt, "birth_chamber", None)` |
| Package exports | `holodeck/__init__.py:13-62`; scenarios and team_simulations import nothing from the deleted modules (their imports: `scenarios.py:31-47`, `team_simulations.py:29-41`) |
| Events | `events.py:491-497`; `event_persistence.py:269-274`; producers only in `chamber.py:156-332` |
| Persistence routing | `event_persistence.py:477-479` `is_routed`; `durable_events.py:566-571` |
| Event pins | `tests/test_ad1195_event_persistence_contract.py:458`, `:501`, `:593`; `tests/test_ad1195_durable_event_seam.py:329-331` |
| Facade pins | `tests/test_ad1270e1_config_facade.py:1525-1528`, `:1573`, `:1576-1577`, `:1813`; baseline `config-facade-baseline.yaml:50-56`, `:272`, `:2093-2107`, `:3465` |
| e2g tables | `tests/test_ad1270e2g_crew_models.py:71`, `:114`, `:160-171`, `:280`, `:365`, `:373`, `:597-598` |
| Generated rows | `config-reference.md:769-783`; `config-profiles.yaml:826`; `architecture-baseline.yaml:716-723`; `tests/fixtures/ad1152_agentic_off_golden.json:15`, `:17`; AD-1152 deleted-field rule at `tests/test_ad1152_agentic_correlation.py:54-62`, precedent lines `:351-361` |
| Ledger head rules | `scripts/gen_ad_ledger.py:126-139`, `:209-223`, `:483-495` |
| Preflight phases | `scripts/run_test_gate.py:1097-1130` |
| Readers check API | `scripts/check_config_readers.py:42`, `:54`, `:132` |
| Default kept for the load test | `config_models/experience.py:665` `naming_ceremony: bool = True` |
| Non-ASCII characters in touched lines | `finalize.py:1168` U+2014; `agent_onboarding.py:355` U+2014; `crew.py:199` U+2014, `:204` U+03B1; `holodeck/__init__.py:1` U+2014; `proactive.py:1135` U+2192 |
| pprint columns | `grep -n "^ \{62\}'operations',$\|^ \{38\}'bypass_for_existing_agents': True,$" tests/test_ad1270e2g_crew_models.py` matched `:161`, `:163` |

## 15. Absence Verified (2026-11-24)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No src caller of the scheduler's or chamber's methods outside the deleted files and the three seams | Grep `register_admission\|next_admit_candidate\|mark_admitted\|mark_graduated\|is_graduated\|queue_pending_subscription\|get_current_phase` in `src` | `assignment.py:207,209,347,349`; `proactive.py:1137`; `finalize.py:1138`; `holodeck/chamber.py`, `scheduler.py` | yes |
| The runtime attributes are set only by the wirer | Grep `birth_chamber_advance_task\|department_activation_scheduler` (repo, minus prompts) | `finalize.py:1140,1164,1174,1176` only | yes |
| No consumer of the deleted modules outside them | Grep `holodeck\.(chamber\|gates\|phases\|affect\|scheduler)` and `HolodeckPhase\|PHASE_ORDER\|AffectiveBaselineCheck\|NoOpAffectiveBaselineCheck` | `holodeck/__init__.py`, the deleted modules, `tests/test_ad486_birth_chamber.py`, `architecture-baseline.yaml:717` | yes |
| The six events have no other producer or consumer | Grep `HOLODECK_` in the repo, minus prompts and md | `chamber.py`, `events.py`, `event_persistence.py`, `scenarios.py` (SCENARIO_* only), three test files | yes |
| No UI consumer | Grep `-i holodeck\|birth\|chamber` in `ui/src` | 0 | yes |
| No scripts reference | Grep `-i holodeck\|chamber` in `scripts` | 0 | yes |
| SystemConfig does not forbid extras | Grep `model_config\|extra=` in `config.py` | none; Grep `extra="forbid"` in `src`: `config_models/operations.py:166,215` only (not SystemConfig or its parents) | yes |
| Tests touching the names | Grep `is_graduated\|queue_pending_subscription\|set_birth_chamber\|_birth_chamber` in `tests` | `test_ad486`, `test_bf903`, `test_runtime_m365_wiring`, `test_ad1270e2g`, `test_ad1270_boot_camp_tracker_retired`, `file_durations.json` | yes |
| No seam-contract or dormant row for the chamber | Grep `_run_cycle\|wire_agent\|create_assignment\|add_member\|_wire_birth` in `docs/development/*.yaml\|json`; grep `-i chamber\|scheduler\|holodeck` in `dormant-class-baseline.yaml` | none; `holodeck/scenarios.py::ScenarioOutcome`, `proactive.py::DailyBriefingScheduler` (unrelated) | yes |
| Other SRP rows keep their triggers | `wc -l`: `agent_onboarding.py` 769 (class from `:40`, trigger `lines` stays above 500 after about 32 lines go); `AssignmentService` has no row; `ProactiveCognitiveLoop` keeps `lines`+`methods`. The draft said that `EventType` keeps `lines`; the check on the oracle found that it does not: its class span falls from 508 to 500 lines (trigger: more than 500) | `EventType`'s baseline row is stale and `check_architecture_principles.py --check` fails until P-47a removes it | the others yes; `EventType` no |
| `file_durations.json` tolerates a stale key | Grep `test_ad509_boot_camp` (4c deleted it) | still listed, 1 hit | yes |
| AD-1355 has no git token | Grep `AD-1355` in `ad-ledger-snapshot.json` | 0; `open-ads-report.md:155` lists it as unaccounted | yes |

**Not verified (the orchestrator measures):**
- the 18-case count;
- `canonical_dump_leaves`' delta;
- the two AD-1152 digests;
- the profile census;
- the mutation results;
- events.db contents on the Captain's machine.

## 6. The contract

### 6.1 Deleted files (M1)

Run from the worktree root (PowerShell):
```
Remove-Item -LiteralPath src/probos/holodeck/chamber.py
Remove-Item -LiteralPath src/probos/holodeck/gates.py
Remove-Item -LiteralPath src/probos/holodeck/phases.py
Remove-Item -LiteralPath src/probos/holodeck/affect.py
Remove-Item -LiteralPath src/probos/holodeck/scheduler.py
Remove-Item -LiteralPath tests/test_ad486_birth_chamber.py
Remove-Item -LiteralPath tests/test_ad1270_chamber_module_ids.py
```
The orchestrator stages these seven deletions in M1 by explicit path.

### 6.2 `src/probos/holodeck/__init__.py` (M1)

**P-1**
U+ note: `—` is one character, U+2014 EM DASH.
SEARCH:
```
"""AD-486 v1 — Holodeck Birth Chamber.

Graduated cognitive onboarding for crew agents. Agents are admitted
post-naming-ceremony, walk through five phases under completion-criteria
gates (NOT timers), and only then earn Ward Room subscription + proactive
loop dispatch.

v1 ships one concrete construct (BirthChamber). Generalization into a
reusable Holodeck construct API is forcing-function deferred to AD-486e
(consumer: AD-510 Team Simulations).
"""

from probos.holodeck.affect import (
    AffectiveBaselineCheck,
    AffectiveObservation,
    NoOpAffectiveBaselineCheck,
)
from probos.holodeck.chamber import BirthChamber, BirthChamberRecord
from probos.holodeck.phases import HolodeckPhase
from probos.holodeck.scenarios import (
```
REPLACE:
```
"""Holodeck: gap-driven scenarios (AD-539b) and team simulations (AD-510).

AD-1355 S1 (#1700) deleted the AD-486 onboarding construct and the
department scheduler this package also held. Newcomer acclimation is
AD-1355's, from S2 on.
"""

from probos.holodeck.scenarios import (
```

**P-2**
SEARCH:
```
    ScenarioOutcome,
)
from probos.holodeck.scheduler import DepartmentActivationScheduler
from probos.holodeck.team_simulations import (
```
REPLACE:
```
    ScenarioOutcome,
)
from probos.holodeck.team_simulations import (
```

**P-3**
SEARCH:
```
__all__ = [
    "AffectiveBaselineCheck",
    "AffectiveObservation",
    "BirthChamber",
    "BirthChamberRecord",
    "DebriefRecord",
    "DepartmentActivationScheduler",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckPhase",
    "HolodeckScenarioStore",
    "NoOpAffectiveBaselineCheck",
    "ScenarioGapLink",
```
REPLACE:
```
__all__ = [
    "DebriefRecord",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckScenarioStore",
    "ScenarioGapLink",
```

### 6.3 `src/probos/startup/finalize.py` (M1)

**P-4**
U+ note: `—` is one character, U+2014 EM DASH.
SEARCH:
```
def _wire_birth_chamber(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-486 v1: Wire Holodeck Birth Chamber + Department scheduler.

    Default-False per AD-695 transitional-flag precedent. When disabled,
    no chamber is constructed; production graduation gates short-circuit
    to ``True`` via the ``runtime.birth_chamber is None`` check.
    """
    cfg = getattr(config, "holodeck_birth_chamber", None)
    if not cfg or not cfg.enabled:
        return False

    import asyncio as _asyncio

    from probos.holodeck import BirthChamber, DepartmentActivationScheduler

    emit_fn = getattr(runtime, "emit_event", None)
    chamber = BirthChamber(config=cfg, emit_event_fn=emit_fn)
    chamber.set_personal_ontology_prober(
        getattr(runtime, "personal_ontology_prober", None)
    )
    chamber.set_curriculum_registry(
        getattr(runtime, "curriculum_registry", None)
    )
    # AD-488 circuit_breaker is a leading-underscore attr on
    # ProactiveCognitiveLoop (predates Wave 5 convention #1). Demeter
    # exception documented; promote to public in a later wave.
    proactive = getattr(runtime, "proactive_loop", None)
    if proactive is not None:
        chamber.set_circuit_breaker(getattr(proactive, "_circuit_breaker", None))
    chamber.set_callsign_registry(getattr(runtime, "callsign_registry", None))
    chamber.set_episodic_memory(getattr(runtime, "episodic_memory", None))

    runtime.birth_chamber = chamber  # public attribute (Wave 5 convention #1)

    scheduler = DepartmentActivationScheduler(
        department_order=list(cfg.department_order),
        get_phase_fn=chamber.get_current_phase,
    )
    runtime.department_activation_scheduler = scheduler  # public attribute

    # Late-bind onto onboarding service so wire_agent can admit agents
    if getattr(runtime, "onboarding", None) is not None:
        try:
            runtime.onboarding.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: onboarding.set_birth_chamber not available; chamber will not auto-admit"
            )

    # AD-486: Late-bind onto AssignmentService for Ward Room subscription gating
    _assn = getattr(runtime, "assignment_service", None)
    if _assn is not None:
        try:
            _assn.set_birth_chamber(chamber)
        except AttributeError:
            logger.warning(
                "AD-486: assignment_service.set_birth_chamber not available; "
                "Ward Room subscription will not be deferred"
            )

    if cfg.auto_advance_enabled:
        try:
            runtime.birth_chamber_advance_task = _asyncio.create_task(
                chamber.run_advance_loop()
            )
        except RuntimeError:
            # No running loop yet (cold-start before serve()) — finalize
            # is invoked from an async context in normal boot, so this
            # branch is defensive only.
            logger.warning(
                "AD-486: no running event loop; advance task not started"
            )
            runtime.birth_chamber_advance_task = None
    else:
        runtime.birth_chamber_advance_task = None

    logger.info(
        "AD-486: Birth Chamber initialized (auto_advance=%s, departments=%s)",
        cfg.auto_advance_enabled, list(cfg.department_order),
    )
    return True


def _wire_holodeck_team_simulations(*, runtime: Any, config: "SystemConfig") -> bool:
```
REPLACE:
```
def _wire_holodeck_team_simulations(*, runtime: Any, config: "SystemConfig") -> bool:
```

**P-5**
SEARCH:
```
        logger.info("AD-507: Crew Development Framework v1 wired during finalization")

    if _wire_birth_chamber(runtime=runtime, config=config):
        logger.info("AD-486: Holodeck Birth Chamber v1 wired during finalization")

    if _wire_emergence_collector(runtime=runtime, config=config):
```
REPLACE:
```
        logger.info("AD-507: Crew Development Framework v1 wired during finalization")

    if _wire_emergence_collector(runtime=runtime, config=config):
```

### 6.4 `src/probos/agent_onboarding.py` (M1)

**P-6**
SEARCH:
```
        self._mentor_announcer: Callable[[str, str], Any] | None = None
        # AD-486: Birth Chamber (late-bound by finalize._wire_birth_chamber)
        self._birth_chamber: Any = None
        # AD-1273: post-construction state, keyed by (agent_type, name).
```
REPLACE:
```
        self._mentor_announcer: Callable[[str, str], Any] | None = None
        # AD-1273: post-construction state, keyed by (agent_type, name).
```

**P-7**
SEARCH:
```
        self._crew_enroller = enroller

    def set_birth_chamber(self, chamber: Any) -> None:
        """AD-486: Set the Birth Chamber (public setter for LoD)."""
        self._birth_chamber = chamber

    def register_rehydrator(
```
REPLACE:
```
        self._crew_enroller = enroller

    def register_rehydrator(
```

**P-8**
U+ note: `—` is one character, U+2014 EM DASH.
SEARCH:
```
        # AD-486: Birth Chamber admission (post-naming, pre-orientation-context).
        # Tier-2 log-and-degrade — chamber failures must not block onboarding.
        if (
            is_crew
            and self._birth_chamber is not None
            and self._config.holodeck_birth_chamber.enabled
            and not (
                self._config.holodeck_birth_chamber.bypass_for_existing_agents
                and _existing_identity_callsign
            )
        ):
            try:
                department = ""
                if self._ontology is not None:
                    try:
                        department = (
                            self._ontology.get_agent_department(agent.agent_type) or ""
                        )
                    except Exception:
                        department = ""
                await self._birth_chamber.admit(agent, department=department)
            except Exception:
                logger.warning(
                    "AD-486: birth_chamber.admit failed for %s; continuing without chamber",
                    agent.agent_type, exc_info=True,
                )

        # AD-567g: Cognitive re-localization
```
REPLACE:
```
        # AD-567g: Cognitive re-localization
```

### 6.5 `src/probos/assignment.py` (M1)

**P-9**
SEARCH:
```
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation
        # AD-486: Late-bound by finalize._wire_birth_chamber (Wave 5 convention #5)
        self._birth_chamber: Any = None
        self._snapshot_cache: list[dict[str, Any]] = []  # Sync cache for build_state_snapshot
```
REPLACE:
```
        self._ward_room = ward_room  # WardRoomService reference for auto-channel creation
        self._snapshot_cache: list[dict[str, Any]] = []  # Sync cache for build_state_snapshot
```

**P-10**
SEARCH:
```
            self._db = None

    def set_birth_chamber(self, chamber: Any) -> None:
        """AD-486: Set the Birth Chamber for Ward Room subscription gating."""
        self._birth_chamber = chamber

    _admission: object = None
```
REPLACE:
```
            self._db = None

    _admission: object = None
```

**P-11**
SEARCH:
```
                # Subscribe all members
                for agent_id in members:
                    # AD-486: Defer subscription if agent is still in Birth Chamber.
                    if (
                        self._birth_chamber is not None
                        and not self._birth_chamber.is_graduated(agent_id)
                    ):
                        self._birth_chamber.queue_pending_subscription(
                            agent_id, ch.id,
                            (lambda aid=agent_id, cid=ch.id:
                                self._ward_room.subscribe(aid, cid)),
                        )
                    else:
                        await self._ward_room.subscribe(agent_id, ch.id)
```
REPLACE:
```
                # Subscribe all members
                for agent_id in members:
                    await self._ward_room.subscribe(agent_id, ch.id)
```

**P-12**
SEARCH:
```
            try:
                # AD-486: Defer subscription if agent is still in Birth Chamber.
                if (
                    self._birth_chamber is not None
                    and not self._birth_chamber.is_graduated(agent_id)
                ):
                    self._birth_chamber.queue_pending_subscription(
                        agent_id, assignment.ward_room_channel_id,
                        (lambda aid=agent_id, cid=assignment.ward_room_channel_id:
                            self._ward_room.subscribe(aid, cid)),
                    )
                else:
                    await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)
            except Exception as e:
```
REPLACE:
```
            try:
                await self._ward_room.subscribe(agent_id, assignment.ward_room_channel_id)
            except Exception as e:
```

### 6.6 `src/probos/proactive.py` (M1)

**P-13**
U+ note: `→` is one character, U+2192 RIGHTWARDS ARROW.
SEARCH:
```
            # AD-486: Skip agents still in Birth Chamber (pre-graduation).
            # Default-disabled chamber (no runtime.birth_chamber) treats
            # all agents as graduated → zero behavior change.
            chamber = getattr(rt, "birth_chamber", None)
            if chamber is not None and not chamber.is_graduated(agent.id):
                continue
            eligible_agents.append(agent)
```
REPLACE:
```
            eligible_agents.append(agent)
```

### 6.7 `src/probos/config_models/crew.py` (M1)

**P-14**
U+ note: `—` is one character, U+2014 EM DASH; `α` is one character, U+03B1 GREEK SMALL LETTER ALPHA.
SEARCH:
```
class HolodeckBirthChamberConfig(BaseModel):
    """AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

    Default-False per AD-695 transitional-flag precedent: enabling the
    chamber gates Ward Room subscription and proactive-loop dispatch
    behind 5-phase graduation, which is a meaningful behavior change.
    Operators flip ``enabled=True`` after Phase α validation (manual
    cohort under observation).
    """

    enabled: bool = False
    bypass_for_existing_agents: bool = True
    department_order: list[str] = Field(
        default_factory=lambda: [
            "security",
            "operations",
            "engineering",
            "science",
            "medical",
        ]
    )
    calibration_min_episodes: int = Field(default=5, ge=1)
    affective_baseline_check_enabled: bool = True
    auto_advance_enabled: bool = True
    auto_advance_poll_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=30.0
    )
    max_self_discovery_probe_attempts: int = Field(default=3, ge=1)

    @field_validator("department_order")
    @classmethod
    def _department_order_lowercase(cls, v: list[str]) -> list[str]:
        return [d.lower() for d in v]


class HolodeckScenarioConfig(BaseModel):
```
REPLACE:
```
class HolodeckScenarioConfig(BaseModel):
```

### 6.8 `src/probos/config_models/__init__.py` (M1)

**P-15**
SEARCH:
```
    FirewallConfig,
    HolodeckBirthChamberConfig,
    HolodeckScenarioConfig,
```
REPLACE:
```
    FirewallConfig,
    HolodeckScenarioConfig,
```

**P-16**
SEARCH:
```
    "GroupChatConfig",
    "HolodeckBirthChamberConfig",
    "HolodeckScenarioConfig",
```
REPLACE:
```
    "GroupChatConfig",
    "HolodeckScenarioConfig",
```

### 6.9 `src/probos/config.py` (M1)

**P-17**
SEARCH:
```
    FirewallConfig,
    HolodeckBirthChamberConfig,
    HolodeckScenarioConfig,
```
REPLACE:
```
    FirewallConfig,
    HolodeckScenarioConfig,
```

**P-18**
SEARCH:
```
    onboarding: OnboardingConfig = OnboardingConfig()
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
```
REPLACE:
```
    onboarding: OnboardingConfig = OnboardingConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
```

### 6.10 `src/probos/events.py` (M1)

**P-19**
SEARCH:
```
    CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507

    # AD-486: Holodeck Birth Chamber phase events
    HOLODECK_AGENT_ADMITTED = "holodeck_agent_admitted"
    HOLODECK_PHASE_ENTERED = "holodeck_phase_entered"
    HOLODECK_PHASE_GATE_PASSED = "holodeck_phase_gate_passed"
    HOLODECK_PHASE_GATE_BLOCKED = "holodeck_phase_gate_blocked"
    HOLODECK_GRADUATION = "holodeck_graduation"
    HOLODECK_AFFECTIVE_BASELINE_OBSERVED = "holodeck_affective_baseline_observed"

    # AD-539b: Holodeck scenario generation from skill gaps
```
REPLACE:
```
    CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507

    # AD-539b: Holodeck scenario generation from skill gaps
```

### 6.11 `src/probos/event_persistence.py` (M1)

**P-20**
SEARCH:
```
    "HEBBIAN_UPDATE",
    "HOLODECK_AFFECTIVE_BASELINE_OBSERVED",
    "HOLODECK_AGENT_ADMITTED",
    "HOLODECK_GRADUATION",
    "HOLODECK_PHASE_ENTERED",
    "HOLODECK_PHASE_GATE_BLOCKED",
    "HOLODECK_PHASE_GATE_PASSED",
    "HOLODECK_SCENARIO_GAP_LINKED",
```
REPLACE:
```
    "HEBBIAN_UPDATE",
    "HOLODECK_SCENARIO_GAP_LINKED",
```

### 6.12 `config/system.yaml` (M1)

**P-21**
SEARCH:
```
holodeck_birth_chamber:
  enabled: false
  bypass_for_existing_agents: true
  department_order:
  - security
  - operations
  - engineering
  - science
  - medical
  calibration_min_episodes: 5
  affective_baseline_check_enabled: true
  auto_advance_enabled: true
  auto_advance_poll_interval_seconds: 2.0
  max_self_discovery_probe_attempts: 3
holodeck_scenarios:
```
REPLACE:
```
holodeck_scenarios:
```

### 6.13 New file `tests/test_ad1355_birth_chamber_removed.py` (M1, 18 cases)

```
"""AD-1355 S1 (#1700): the AD-486 Birth Chamber and the department activation scheduler are deleted.

Neither ran with its switch at the default: ``holodeck_birth_chamber.enabled`` was False in the
model and in the tracked ``config/system.yaml``. With the switch on, the chamber admitted almost
no one and graduated no one (#1700, Problem items 1 to 10). Both are deleted with their config,
wirer, the onboarding, assignment and proactive seams, the six event types only the chamber
emitted, and their tests. A config that still carries ``holodeck_birth_chamber:`` keeps loading,
because SystemConfig ignores unknown keys (the BF-926 precedent).

The census reads every file under ``src/`` except ``__pycache__`` and files holding a NUL byte,
for the four names #1700's acceptance line lists. Two controls show that it reads the real tree
and that it reports a planted reference.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import probos.config as config_module
import probos.config_models as config_models
import probos.config_models.crew as config_crew
import probos.holodeck as holodeck
from probos import event_persistence as ep
from probos.agent_onboarding import AgentOnboardingService
from probos.assignment import AssignmentService
from probos.config import SystemConfig, load_config
from probos.events import EventType
from probos.startup import finalize

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_READERS = _REPO / "scripts" / "check_config_readers.py"
_TERMS = ("BirthChamber", "DepartmentActivationScheduler", "birth_chamber", "holodeck_birth_chamber")
_MODULES = ("chamber", "gates", "phases", "affect", "scheduler")
_EVENTS = (
    "HOLODECK_AFFECTIVE_BASELINE_OBSERVED",
    "HOLODECK_AGENT_ADMITTED",
    "HOLODECK_GRADUATION",
    "HOLODECK_PHASE_ENTERED",
    "HOLODECK_PHASE_GATE_BLOCKED",
    "HOLODECK_PHASE_GATE_PASSED",
)
_HOLODECK_EXPORTS = (
    "DebriefRecord",
    "GapScenarioGenerator",
    "HolodeckGapBridge",
    "HolodeckGapDrill",
    "HolodeckScenarioStore",
    "ScenarioGapLink",
    "ScenarioOutcome",
    "TeamScenario",
    "TeamScenarioRegistry",
    "TeamSimulationDrill",
    "TeamSimulationOrchestrator",
    "TeamSimulationParticipant",
    "TeamSimulationRecord",
    "TeamSimulationStore",
)


def _readable(root: Path) -> list[Path]:
    """Every file under ``root`` the census reads: not bytecode, not binary."""
    paths: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if b"\x00" in path.read_bytes():
            continue
        paths.append(path)
    return paths


def _census(root: Path, term: str) -> list[str]:
    """``relative/path:line`` for every line under ``root`` that holds ``term``."""
    hits: list[str] = []
    for path in _readable(root):
        text = path.read_bytes().decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if term in line:
                hits.append(f"{path.relative_to(root).as_posix()}:{number}")
    return hits


def _load_readers():
    spec = importlib.util.spec_from_file_location("_ad1355_s1_config_readers", _READERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("term", _TERMS)
def test_no_src_file_names_a_removed_term(term: str) -> None:
    assert _census(_SRC, term) == []


def test_the_census_reads_the_real_tree() -> None:
    """Premise for the case above: the walk reaches every seam S1 edited and a data file, and sees a neighbour."""
    read = {path.relative_to(_SRC).as_posix() for path in _readable(_SRC)}
    for path in (
        "probos/agent_onboarding.py",
        "probos/assignment.py",
        "probos/proactive.py",
        "probos/config.py",
        "probos/config_models/crew.py",
        "probos/startup/finalize.py",
        "probos/holodeck/__init__.py",
        "probos/sop/builtin/general_quarters.yaml",
    ):
        assert path in read, path
    assert _census(_SRC, "HolodeckScenarioConfig")
    assert _census(_SRC, "_wire_holodeck_team_simulations")


def test_the_census_reports_a_planted_reference(tmp_path: Path) -> None:
    """Control: a reference put back is found in Python and in a data file; bytecode and binaries are not read."""
    package = tmp_path / "probos"
    (package / "__pycache__").mkdir(parents=True)
    (package / "seam.py").write_text("x = 1\nfrom probos.holodeck import BirthChamber\n", encoding="utf-8")
    (package / "orders.yaml").write_text("holodeck_birth_chamber:\n  enabled: true\n", encoding="utf-8")
    (package / "__pycache__" / "seam.cpython-312.pyc").write_bytes(b"BirthChamber")
    (package / "blob.bin").write_bytes(b"\x00BirthChamber")

    assert _census(tmp_path, "BirthChamber") == ["probos/seam.py:2"]
    assert _census(tmp_path, "birth_chamber") == ["probos/orders.yaml:1"]
    assert _census(tmp_path, "DepartmentActivationScheduler") == []


@pytest.mark.parametrize("name", _MODULES)
def test_the_deleted_modules_are_gone(name: str) -> None:
    assert importlib.util.find_spec(f"probos.holodeck.{name}") is None
    assert not (_SRC / "probos" / "holodeck" / f"{name}.py").exists()


def test_the_holodeck_package_keeps_scenarios_and_team_simulations() -> None:
    assert tuple(holodeck.__all__) == _HOLODECK_EXPORTS
    for name in _HOLODECK_EXPORTS:
        assert hasattr(holodeck, name), name


def test_the_config_field_and_model_are_gone() -> None:
    assert "holodeck_scenarios" in SystemConfig.model_fields  # premise: its neighbour stays
    assert "holodeck_birth_chamber" not in SystemConfig.model_fields
    assert "holodeck_birth_chamber" not in SystemConfig().model_dump()
    for module in (config_module, config_models, config_crew):
        assert not hasattr(module, "HolodeckBirthChamberConfig"), module.__name__
    assert "HolodeckBirthChamberConfig" not in config_models.__all__


@pytest.mark.parametrize("enabled", [True, False])
def test_a_config_that_still_sets_holodeck_birth_chamber_loads(enabled: bool, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(
        yaml.safe_dump({
            "holodeck_birth_chamber": {
                "enabled": enabled,
                "bypass_for_existing_agents": True,
                "department_order": ["security", "operations", "engineering", "science", "medical"],
                "calibration_min_episodes": 5,
                "auto_advance_enabled": True,
            },
            "onboarding": {"naming_ceremony": False},
        }),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.onboarding.naming_ceremony is False  # the file was read
    assert "holodeck_birth_chamber" not in cfg.model_dump()


def test_the_tracked_yaml_carries_no_holodeck_birth_chamber_key(tmp_path: Path) -> None:
    readers = _load_readers()
    document = yaml.safe_load(readers.DEFAULT_YAML.read_text(encoding="utf-8"))
    assert "holodeck_scenarios" in document  # premise: this is the tracked config
    assert "holodeck_birth_chamber" not in document

    # Control: the reader check reports the section as a key no field declares when it is present.
    (tmp_path / "src").mkdir()
    report = readers.build_report(
        SystemConfig, tmp_path / "src", {**document, "holodeck_birth_chamber": {"enabled": False}},
    )
    assert "holodeck_birth_chamber" in report.orphan_yaml_keys
    assert "holodeck_scenarios" not in report.orphan_yaml_keys


def test_the_six_event_types_and_their_grandfathered_entries_are_gone() -> None:
    assert "HOLODECK_SCENARIO_GENERATED" in EventType.__members__  # premise: AD-539b's events stay
    assert "HOLODECK_SCENARIO_GENERATED" in ep.GRANDFATHERED
    values = {member.value for member in EventType}
    for name in _EVENTS:
        assert name not in EventType.__members__, name
        assert name.lower() not in values, name
        assert name not in ep.GRANDFATHERED, name
        assert name not in ep.DECLARATIONS, name
    assert ep.assert_complete(EventType.__members__) is None


def test_the_wirer_and_both_setters_are_gone() -> None:
    assert hasattr(finalize, "_wire_holodeck_scenarios")  # premise: the neighbouring wirer stays
    assert hasattr(AgentOnboardingService, "set_crew_enroller")  # premise: the neighbouring setters stay
    assert hasattr(AssignmentService, "set_admission")
    assert not hasattr(finalize, "_wire_birth_chamber")
    assert not hasattr(AgentOnboardingService, "set_birth_chamber")
    assert not hasattr(AssignmentService, "set_birth_chamber")
```

### 6.14 `tests/test_ad1270_boot_camp_tracker_retired.py` (M2)

**P-22**
SEARCH:
```
and no reader of ``runtime.boot_camp_tracker``. Its five phases are not AD-638's 1 to 4, and
AD-486's birth chamber carries the orientation phases. A config that still carries
```
REPLACE:
```
and no reader of ``runtime.boot_camp_tracker``. Its five phases are not AD-638's 1 to 4, and
AD-486's birth chamber carried the orientation phases (AD-1355 S1, #1700, deleted it). A config that still carries
```

**P-23**
SEARCH:
```
    assert "_wire_birth_chamber" in called  # premise: the scan sees the neighbouring wirer
```
REPLACE:
```
    assert "_wire_curriculum_registry" in called  # premise: the scan sees a neighbouring wirer (AD-1355 S1 deleted the chamber's)
```

### 6.15 `tests/test_ad1270e2g_crew_models.py` (M2)

**P-24**
SEARCH:
```
in ``probos.config_models.crew`` and are re-exported from ``probos.config``.

What is preserved
```
REPLACE:
```
in ``probos.config_models.crew`` and are re-exported from ``probos.config``.
AD-1355 S1 (#1700) later deleted ``HolodeckBirthChamberConfig`` with the AD-486
Birth Chamber, so the tables below hold the twenty-four that remain.

What is preserved
```

**P-25**
SEARCH:
```
    "FirewallConfig",
    "HolodeckBirthChamberConfig",
    "HolodeckScenarioConfig",
```
REPLACE:
```
    "FirewallConfig",
    "HolodeckScenarioConfig",
```

**P-26**
SEARCH:
```
    "HolodeckBirthChamberConfig": "holodeck_birth_chamber",
    "HolodeckScenarioConfig": "holodeck_scenarios",
```
REPLACE:
```
    "HolodeckScenarioConfig": "holodeck_scenarios",
```

**P-27**
SEARCH:
```
    'HolodeckBirthChamberConfig': {   'enabled': False,
                                      'bypass_for_existing_agents': True,
                                      'department_order': [   'security',
                                                              'operations',
                                                              'engineering',
                                                              'science',
                                                              'medical'],
                                      'calibration_min_episodes': 5,
                                      'affective_baseline_check_enabled': True,
                                      'auto_advance_enabled': True,
                                      'auto_advance_poll_interval_seconds': 2.0,
                                      'max_self_discovery_probe_attempts': 3},
```
REPLACE:
```
    # AD-1355 S1 (#1700) deleted HolodeckBirthChamberConfig with the AD-486 Birth Chamber.
```
(Whitespace is pprint layout: 38 spaces before each continuation key and 62 before each list item, measured.)

**P-28**
SEARCH:
```
    "HolodeckBirthChamberConfig": 4,
    "HolodeckScenarioConfig": 4,
```
REPLACE:
```
    "HolodeckScenarioConfig": 4,
```

**P-29**
SEARCH:
```
#: what keeps the case below non-vacuous: sixteen of the twenty-five carry no
```
REPLACE:
```
#: what keeps the case below non-vacuous: seventeen of the twenty-four carry no
```

**P-30**
SEARCH:
```
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 25
```
REPLACE:
```
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 24  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig deleted
```
Also, on the same turn, a second pair in this file:

**P-31**
SEARCH:
```
    assert len(PLAIN_SUBMODELS) == 22
```
REPLACE:
```
    assert len(PLAIN_SUBMODELS) == 21  # AD-1355 S1 (#1700)
```

**P-31a**
SEARCH:
```
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 31  # AD-1360 (#1828): MemorySecurityConfig 3 -> 4
    assert sum(1 for c in EXPECTED_BOUND_COUNTS.values() if c) == 8
```
REPLACE:
```
    # AD-1355 S1 (#1700) deleted HolodeckBirthChamberConfig and its four bounds: 31 -> 27, 8 -> 7.
    assert sum(EXPECTED_BOUND_COUNTS.values()) == 27  # AD-1360 (#1828): MemorySecurityConfig 3 -> 4
    assert sum(1 for c in EXPECTED_BOUND_COUNTS.values() if c) == 7
```

### 6.16 `tests/test_ad1195_event_persistence_contract.py` (M2)

**P-32**
SEARCH:
```
    """DECL-1: 396 members = 42 declared + 354 grandfathered, disjoint (AD-1337 S2 declared SECRET_MASKED).

    AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED with its one producer (AD-509's
    tracker): 397 -> 396, 356 -> 355; and BOOT_CAMP_PHASE_ADVANCE with AD-638's phases 2 and 3:
    396 -> 395, 355 -> 354. The DECL-3 golden snapshot keeps its 356 names.
    """
    names = set(EventType.__members__)
    declared = set(ep.DECLARATIONS)
    assert not declared & ep.GRANDFATHERED
    assert declared | ep.GRANDFATHERED == names
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 42, 354)
```
REPLACE:
```
    """DECL-1: 390 members = 42 declared + 348 grandfathered, disjoint (AD-1337 S2 declared SECRET_MASKED).

    AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED with its one producer (AD-509's
    tracker): 397 -> 396, 356 -> 355; and BOOT_CAMP_PHASE_ADVANCE with AD-638's phases 2 and 3:
    396 -> 395, 355 -> 354. AD-1355 S1 (#1700) deleted the six grandfathered HOLODECK_* members
    whose one producer was AD-486's Birth Chamber: 396 -> 390, 354 -> 348. The DECL-3 golden
    snapshot keeps its 356 names.
    """
    names = set(EventType.__members__)
    declared = set(ep.DECLARATIONS)
    assert not declared & ep.GRANDFATHERED
    assert declared | ep.GRANDFATHERED == names
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (390, 42, 348)
```

**P-33**
SEARCH:
```
    assert len(EventType) == 396  # AD-1270 (#1324) slice 4c deleted two members; AD-1337 S2 (#1560) added SECRET_MASKED
```
REPLACE:
```
    assert len(EventType) == 390  # AD-1270 (#1324) slice 4c deleted two members; AD-1337 S2 (#1560) added SECRET_MASKED; AD-1355 S1 (#1700) deleted six
```

### 6.17 `tests/test_ad1195_durable_event_seam.py` (M2)

**P-34**
SEARCH:
```
    # AD-1337 S2 (#1560) added SECRET_MASKED, a routed DURABLE member: 395 -> 396, 29 -> 30, 37 -> 38.
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 30
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (30, 366)
```
REPLACE:
```
    # AD-1337 S2 (#1560) added SECRET_MASKED, a routed DURABLE member: 395 -> 396, 29 -> 30, 37 -> 38.
    # AD-1355 S1 (#1700) deleted six unrouted HOLODECK_* members (AD-486's Birth Chamber): 396 -> 390, 366 -> 360.
    assert len(EventType) == 390
    assert len(ROUTED_VALUES) == 30
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (30, 360)
```

### 6.18 `tests/test_bf903_ward_room_scope.py` (M2)

**P-35**
SEARCH:
```
class _Chamber:
    """A Birth Chamber that has graduated no one, so ``AssignmentService`` defers every subscription to it (AD-486)."""

    def __init__(self) -> None:
        self.queued: list[tuple[str, str]] = []

    def is_graduated(self, agent_id: str) -> bool:
        return False

    def queue_pending_subscription(self, agent_id: str, channel_id: str, subscribe: Any) -> None:
        self.queued.append((agent_id, channel_id))


class _Procedure:
```
REPLACE:
```
class _Procedure:
```

**P-36**
SEARCH:
```
    request naming a visitor without ward_room.read answers 403 with the reason and leaves no assignment, channel,
    subscription or deferred subscription; a visitor holding ward_room.read joins with every member subscribed.
```
REPLACE:
```
    request naming a visitor without ward_room.read answers 403 with the reason and leaves no assignment, channel
    or subscription; a visitor holding ward_room.read joins with every member subscribed.
```

**P-37**
SEARCH:
```
        channels = [c.id for c in await rig.ward_room.list_channels()]
        chamber = _Chamber()
        async with _client(runtime) as client:
```
REPLACE:
```
        channels = [c.id for c in await rig.ward_room.list_channels()]
        async with _client(runtime) as client:
```

**P-38**
SEARCH:
```
            assert refused.json() == _SUBSCRIBE_REFUSED
            service.set_birth_chamber(chamber)
            deferred = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor]},
            )
            assert deferred.status_code == 403, deferred.text
            assert chamber.queued == []
            assert await service.list_assignments() == []
            assert [c.id for c in await rig.ward_room.list_channels()] == channels
            assert [p["surface"] for p in _refusals(rig.events)] == ["ward_room.subscribe", "ward_room.subscribe"]
            service.set_birth_chamber(None)
            served = await client.post(
```
REPLACE:
```
            assert refused.json() == _SUBSCRIBE_REFUSED
            again = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor]},
            )
            assert again.status_code == 403, again.text
            assert await service.list_assignments() == []
            assert [c.id for c in await rig.ward_room.list_channels()] == channels
            assert [p["surface"] for p in _refusals(rig.events)] == ["ward_room.subscribe", "ward_room.subscribe"]
            served = await client.post(
```

### 6.19 `tests/test_runtime_m365_wiring.py` (M2)

**P-39**
SEARCH:
```
    config.team_simulations.enabled = False
    config.holodeck_birth_chamber = MagicMock()
    config.holodeck_birth_chamber.enabled = False
    return config


@pytest.fixture
```
REPLACE:
```
    config.team_simulations.enabled = False
    return config


@pytest.fixture
```

**P-40**
SEARCH:
```
    config.team_simulations.enabled = False
    config.holodeck_birth_chamber = MagicMock()
    config.holodeck_birth_chamber.enabled = False
    return config


def test_config_m365_disabled(config_m365_disabled):
```
REPLACE:
```
    config.team_simulations.enabled = False
    return config


def test_config_m365_disabled(config_m365_disabled):
```

### 6.20 `tests/test_ad1270e1_config_facade.py` (M3)

**P-41**
SEARCH:
```
    # own_models 228 -> 229, and the check prints names=310.
    assert counts["public_names"] == 310  # AD-1346 M3c (#1604): AdmissionConfig
    assert counts["owned"] == 297  # AD-1346 M3c (#1604): AdmissionConfig is owned
    assert counts["incidental"] == 13
    assert counts["own_models"] == 229  # AD-1346 M3c (#1604): AdmissionConfig
```
REPLACE:
```
    # own_models 228 -> 229, and the check prints names=310.
    # AD-1355 S1 (#1700) removes the owned model HolodeckBirthChamberConfig: public_names 310 -> 309,
    # owned 297 -> 296, own_models 229 -> 228, and the check prints names=309.
    assert counts["public_names"] == 309  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig
    assert counts["owned"] == 296  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig was owned
    assert counts["incidental"] == 13
    assert counts["own_models"] == 228  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig
```

**P-42**
SEARCH:
```
    # AD-1360 (#1828) adds security.memory.correlation_cutoff (1885 -> 1886).
    assert counts["field_definitions"] == 1886  # AD-1206 intentionally adds github_repository.
    assert counts["aliased_fields"] == 1
    # AD-1270 (#1324) slice 4c removes the BootCampPhaseConfig model (names 310 -> 309, models 230 -> 229).
    assert len(baseline["names"]) == 310  # AD-1346 M3c (#1604): AdmissionConfig (309 -> 310)
    assert len(baseline["models"]) == 230  # AD-1346 M3c (#1604): AdmissionConfig (229 -> 230)
```
REPLACE:
```
    # AD-1360 (#1828) adds security.memory.correlation_cutoff (1885 -> 1886).
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
    assert counts["aliased_fields"] == 1
    # AD-1270 (#1324) slice 4c removes the BootCampPhaseConfig model (names 310 -> 309, models 230 -> 229).
    # AD-1346 M3c (#1604) adds AdmissionConfig (309 -> 310, 229 -> 230).
    assert len(baseline["names"]) == 309  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (310 -> 309)
    assert len(baseline["models"]) == 229  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (230 -> 229)
```

**P-43**
SEARCH:
```
    assert "names=310" in proc.stdout  # AD-1346 M3c (#1604): AdmissionConfig (names=309 -> names=310)
```
REPLACE:
```
    # AD-1346 M3c (#1604) adds AdmissionConfig (names=309 -> names=310).
    assert "names=309" in proc.stdout  # AD-1355 S1 (#1700): HolodeckBirthChamberConfig (names=310 -> names=309)
```

### 6.21 `tests/test_ad1152_agentic_correlation.py` (M3)

**P-44**
SEARCH:
```
    # BF-962/963 (#1792) deleted the unread orientation flag.
    assert "populate_ward_room_department" not in config["orientation"]
```
REPLACE:
```
    # BF-962/963 (#1792) deleted the unread orientation flag.
    assert "populate_ward_room_department" not in config["orientation"]
    # AD-1355 S1 (#1700) deleted AD-486's Birth Chamber section.
    assert "holodeck_birth_chamber" not in config
```

### 6.22 `docs/development/config-profiles.yaml` (M3)

**P-45**
SEARCH:
```
- group_chat.turn_mode_policy_enabled
- holodeck_birth_chamber.enabled
- holodeck_scenarios.enabled
```
REPLACE:
```
- group_chat.turn_mode_policy_enabled
- holodeck_scenarios.enabled
```

**P-46** (fill the placeholders by measurement in section 7, step 3, before applying)
SEARCH:
```
  measured_at_commit: AD-1270 (issue 1324) slice 4c M1 on the slice-4b merge, every count re-measured with
    this instrument (slice 4c removes boot_camp_phase.enabled, a default-True boolean; slice 4b
    measured 451, 227, 224, 85 and 142)
```
REPLACE:
```
  measured_at_commit: AD-1355 S1 (issue 1700) M3 on the AD-1358 S2 merge, every count re-measured with
    this instrument (S1 removes the four holodeck_birth_chamber booleans, enabled (default-False,
    never armed) and three default-True; the base measured 450, 227, 223, 85 and 142)
```

**P-46a**
SEARCH:
```
  boolean_fields_reachable: 450
  default_false: 227
  default_true: 223
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 142
```
REPLACE:
```
  boolean_fields_reachable: 446
  default_false: 226
  default_true: 220
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 141
```
(The base values above may already be stale. The base-to-candidate delta must be exactly -4, -1, -3, 0, -1. Anything else is a stop. The filled text must contain no `: ` and no ` #` inside the folded scalar.)

### 6.23 `docs/development/architecture-baseline.yaml` (M3)

**P-47**
SEARCH:
```
- category: srp-size
  key: probos.holodeck.chamber::BirthChamber
  triggers:
  - methods
  disposition: debt
  owner: AD-1270h
  rationale: Crosses the repository's stated SRP review trigger. No decomposition AD owns this class yet; frozen so a new oversized class cannot land unreviewed.
  review_by: AD-1270h closeout
- category: srp-size
  key: probos.identity::AgentIdentityRegistry
```
REPLACE:
```
- category: srp-size
  key: probos.identity::AgentIdentityRegistry
```

**P-47a** (found by the check on the oracle; section 7 step 4)
SEARCH:
```
- category: srp-size
  key: probos.events::EventType
  triggers:
  - lines
  disposition: debt
  owner: AD-1270h
  rationale: Crosses the repository's stated SRP review trigger. No decomposition AD owns this class yet; frozen so a new oversized class cannot land unreviewed.
  review_by: AD-1270h closeout
- category: srp-size
  key: probos.experience.renderer::ExecutionRenderer
```
REPLACE:
```
- category: srp-size
  key: probos.experience.renderer::ExecutionRenderer
```

### 6.24 `docs/development/structure.md` (M3)

**P-48**
SEARCH:
```
| `holodeck/` | Holodeck birth chamber and scenarios |
```
REPLACE:
```
| `holodeck/` | Holodeck scenarios and team simulations |
```

### 6.25 `docs/development/deterministic-ship.md` (M3)

**P-49**
SEARCH:
```
(AD-1346 epic, #1601). The AD-486 Birth Chamber's calibration gate still counts episodes under the slot id while episodes carry the sovereign id (`holodeck/gates.py:79`; #1700 S1 deletes it). Trust inputs
```
REPLACE:
```
(AD-1346 epic, #1601). Trust inputs
```

**P-50**
SEARCH:
```
| The AD-486 Birth Chamber admits almost no one and graduates no one, silently (AD-1355, #1700, Problem items 1-10). The Birth Chamber calibration gate's slot-id count above. A recall gate never bound
```
REPLACE:
```
| A recall gate never bound
```

Trackers:

### 6.26 `PROGRESS.md` (M3)

**P-51**
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1355 S1 (2026-11-25), #1700 -- the AD-486 Birth Chamber and the department activation scheduler are deleted, with their config, wirer, seams, event types and tests.** Neither ran with its switch at the default: `holodeck_birth_chamber.enabled` was False in the model and in the tracked `config/system.yaml`, and with it on the chamber admitted almost no one and graduated no one (#1700, Problem items 1 to 10). Deleted: `holodeck/chamber.py`, `gates.py`, `phases.py`, `affect.py` and `scheduler.py` with their package exports; `HolodeckBirthChamberConfig` and its `SystemConfig` field; the finalization wirer; `set_birth_chamber` on `AgentOnboardingService` and `AssignmentService`, with the admission branch and both deferred-subscription branches; the proactive loop's pre-graduation skip; and the six `HOLODECK_*` event types only the chamber emitted, with their grandfathered rows. `tests/test_ad1195_event_persistence_contract.py` and `tests/test_ad1195_durable_event_seam.py` measure 390 members, 348 grandfathered and 360 unrouted. `tests/test_ad1355_birth_chamber_removed.py` (18 cases) finds no `src/` file naming `BirthChamber`, `DepartmentActivationScheduler`, `birth_chamber` or `holodeck_birth_chamber`; it reports a planted reference in a scratch tree, loads a config that still sets `holodeck_birth_chamber:` (the section is ignored), finds the tracked yaml without the key, and finds the holodeck package exporting its 14 scenario and team-simulation names. A crew agent is wired, subscribed to an assignment channel and offered a proactive cycle as before: `tests/test_onboarding.py`, `tests/test_assignment.py`, `tests/test_proactive.py` and `tests/test_bf903_ward_room_scope.py` pass, the last without the stub chamber it installed. `tests/test_ad486_birth_chamber.py` and `tests/test_ad1270_chamber_module_ids.py` are deleted with the code they covered; the curriculum's `list_by_phase` stays covered by `tests/test_ad507_curriculum.py`. Mutation census: 10 of 10 killed (rows R1 to R10, run once on the candidate overlay of `40f9305f`), each by its named case. Regenerated: the config reference, the facade baseline, the profile manifest's row and census, the architecture baseline's chamber and `EventType` rows, the AD-1152 default-config digests (by measurement) and the ledger pair. Acclimation itself is S2 onward. Contract `prompts/ad-1355-s1-birth-chamber-removal.md`.

```

### 6.27 `DECISIONS.md` (M3)

**P-52**
SEARCH:
```
Civilization (Phases 31-36)

```
REPLACE:
```
Civilization (Phases 31-36)

### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)

- *Scope.* `holodeck/__init__.py` and the deleted `chamber.py`, `gates.py`, `phases.py`, `affect.py`, `scheduler.py`; `startup/finalize.py`, `agent_onboarding.py`, `assignment.py`, `proactive.py`, `config.py`, `config_models/crew.py`, `config_models/__init__.py`, `events.py`, `event_persistence.py`, `config/system.yaml`; test `tests/test_ad1355_birth_chamber_removed.py`. Contract `prompts/ad-1355-s1-birth-chamber-removal.md`. Slice S1 of #1700.
- *D1.* A config that still carries `holodeck_birth_chamber:` loads with the key ignored, as `SystemConfig` ignores unknown keys (the BF-926 and AD-1270 slice 4c precedent); the tracked yaml drops it. Rejected: a warned legacy key (new loader machinery for a section whose only effect was off by default).
- *D2.* The six `HOLODECK_*` event types whose one producer was the chamber are deleted with their grandfathered rows; AD-539b's four `HOLODECK_SCENARIO_*` stay. A grandfathered member is never routed to events.db, and the durable reader resolves an unknown name to none, so no stored row is orphaned. Rejected: keeping them as reserved values (members with no producer).
- *D3.* The deletion is proved by a census of `src/` for the four names #1700's acceptance line lists, with controls that it reads the real tree and reports a planted reference, and by the default-path suites; no differential boot test, because every deleted branch was unreachable at the default.
- *D4.* This entry's heading does not lead with the AD number, so the ledger keeps AD-1355 allocated and open while S2 to S9 remain.
- *Effect.* None at the default. An operator who had set `enabled: true` now gets the default path: admitted agents are no longer held at `ship_records` or skipped by the proactive loop, and assignment subscriptions are no longer queued.
- *Reversal.* Revert the three S1 commits.

```

### 6.28 `tests/fixtures/ad1152_agentic_off_golden.json` (M3)

**P-53**
SEARCH:
```
  "observation_sha256": "e7d2eae1a3a5d6ba35f21fbe2e0033156caf5b1bc4e08d8522a7b26ff5c42cd8",
```
REPLACE:
```
  "observation_sha256": "537dfac850f0541e3158b0c0986da4415df7141fef8e438b60826c426b34eb93",
```

**P-54**
SEARCH:
```
    "default_config_sha256": "63daa23879986cb3e5be075c772c294b3c5c071d6c9331e6905836f716ccae76",
```
REPLACE:
```
    "default_config_sha256": "ddaf1ddceb7ed07652a41c1bec0921a095d64b8ce122ec5279715f7cdf7a5cb6",
```

### 6.29 `tests/test_ad1270b_architecture_fitness.py` (M3)

**P-55** (found by running the M3 focused list on the oracle: `test_json_report_carries_the_categories_block` fails with 90 against its pin of 92)
SEARCH:
```
    assert categories["srp-size"] == {
        "mode": "gating",
        "current": 92,
        "baseline": 92,
    }
```
REPLACE:
```
    # AD-1355 S1 (#1700) took it from 92 to 90: the BirthChamber row went with
    # its class, and the EventType row with the six deleted members (the class
    # fell from 508 to 500 lines; the trigger is more than 500).
    assert categories["srp-size"] == {
        "mode": "gating",
        "current": 90,
        "baseline": 90,
    }
```

## 7. Generated artifacts (M3, in order)

The orchestrator runs steps 1 to 6 on the oracle and proves each diff against the lists below. The pairs of this section (P-45 to P-55) are applied by the Builder; the generated files are committed from the oracle's blobs.

1. `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline`. The diff may contain only these changes:
   - `HolodeckBirthChamberConfig` gone from `names` and `models`;
   - `SystemConfig`'s field list loses `holodeck_birth_chamber`, and its `schema_sha256` moves;
   - `surface_counts` moves `field_definitions` -9, `public_names`, `owned` and `own_models` -1 each, and `canonical_dump_leaves` by the measured amount;
   - the top-level `canonical_dump_sha256` moves.

   Nothing else changes: `incidental` stays 13 and `aliased_fields` stays 1.
2. `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py`. The only change allowed is that the `## holodeck_birth_chamber` section goes (15 lines).
3. Apply P-45. Measure the five census counts with the instrument `config-profiles.yaml` names, on the base and on the candidate. Fill and apply P-46 and P-46a. Run `-P scripts/check_config_profiles.py --check`.
4. Apply P-47 and P-47a, then run `-P scripts/check_architecture_principles.py --check`. It passes with `srp-size=90` (92 on the base): the `BirthChamber` row (P-47) and the `EventType` row (P-47a) leave, and no other row changes. `EventType`'s class span falls from 508 to 500 lines against the trigger of more than 500 (`SRP_MAX_BODY_LINES`), so its row is stale once the six members are deleted. The count pin of `tests/test_ad1270b_architecture_fitness.py` (`test_json_report_carries_the_categories_block`) moves from 92 to 90 with it (P-55).
5. Apply P-53 and P-54 (the AD-1152 golden). The orchestrator measured both values by following `tests/test_ad1152_agentic_correlation.py:54-62` after P-44: `test_default_off_matches_pinned_base` first fails on `default_config_sha256` alone (golden line 17), then on `observation_sha256` alone (line 15), and with both replaced the whole file passes (41 passed). Lines 15 and 17 are the only changes. Record both values in the M3 commit message.
6. Run `-P scripts/check_dormant_classes.py --check`, `-P scripts/check_seam_contracts.py --check` and `-P scripts/check_store_registry.py --check`. No change is expected; any change is a stop.
7. Apply P-48 to P-52.
8. **Orchestrator:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then `--check`, and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`. Allowed changes:
   - AD-1355 leaves Unaccounted (`1351-1355` becomes `1351-1354`);
   - AD-1355 enters Allocated and open as "mentioned by an authority, no code and no closure";
   - the lifecycle and section counts move by one;
   - the git layer's capture line refreshes.

   AD-1355 must not resolve `shipped`.
9. **Orchestrator:** run `scripts/run_test_gate.py --preflight-only`.

`tests/fixtures/file_durations.json` is not edited: a stale key is tolerated, and the file is rewritten only from a canonical gate.

## 9. What this does NOT change

- `holodeck/scenarios.py`, `team_simulations.py` and their wirers.
- `CoreKnowledgeCurriculumRegistry` and `_wire_curriculum_registry`. The registry's runtime attribute loses its only reader (the deleted wirer); S3 renders it.
- `PersonalOntologyProber` and its wiring, AD-638 boot camp, AD-567g orientation, AD-628e mentor, AD-701 visitors.
- Prose naming AD-486 as a future consumer in `crew_development/curriculum.py:4` and `crew_development/discovery/*.py`. That prose holds none of the four names; S3 owns the consumer story.
- History in `PROGRESS.md:3` (BF-992), `DECISIONS.md:19`, era files, roadmaps, `docs/research/`, `prompts/`.
- `file_durations.json`; `dormant-class-baseline.yaml`; seam-contract and store baselines.

## 10. Census rows and probes

**Rows** (one campaign of record on the M3 tree, after an unmutated baseline of the M3 focused list passes; rerun a row only if its file differs from the recorded sha256):

| Row | Mutant | Killed by |
|---|---|---|
| R1 | `proactive.py` `_run_cycle`: add back `chamber = getattr(rt, "birth_chamber", None)` and its skip | `test_no_src_file_names_a_removed_term[birth_chamber]` |
| R2 | `assignment.py`: add back the `set_birth_chamber` method | `[birth_chamber]`, `test_the_wirer_and_both_setters_are_gone` |
| R3 | `config.py`: add `holodeck_birth_chamber: dict = {}` to `SystemConfig` | `[holodeck_birth_chamber]`, `test_the_config_field_and_model_are_gone`, `test_a_config_that_still_sets_holodeck_birth_chamber_loads[True]` and `[False]` |
| R4 | `config/system.yaml`: restore the section | `test_the_tracked_yaml_carries_no_holodeck_birth_chamber_key` |
| R5 | `events.py` + `event_persistence.py`: restore `HOLODECK_GRADUATION` and its grandfathered row | `test_the_six_event_types_and_their_grandfathered_entries_are_gone`, the ad1195 count pins |
| R6 | Recreate `src/probos/holodeck/phases.py` with the enum only (no census term) | `test_the_deleted_modules_are_gone[phases]` |
| R7 | `holodeck/__init__.py`: add `"HolodeckPhase"` to `__all__` | `test_the_holodeck_package_keeps_scenarios_and_team_simulations` |
| R8 | `src/probos/sop/builtin/general_quarters.yaml`: add a comment line naming `DepartmentActivationScheduler` | `[DepartmentActivationScheduler]` |
| R9 | `agent_onboarding.py`: add back `self._birth_chamber: Any = None` | `[birth_chamber]` |
| R10 | Census file: `_readable` keeps only `.py` files | `test_the_census_reports_a_planted_reference` |

**Probes** (run once on the base, not committed; paste the output):

- **P1:**
  ```
  d:/ProbOS/.venv/Scripts/python.exe -c "from probos.config import SystemConfig, load_config; print(SystemConfig().holodeck_birth_chamber.enabled, load_config('config/system.yaml').holodeck_birth_chamber.enabled, load_config('D:/ProbOS/config/system.yaml').holodeck_birth_chamber.enabled)"
  ```
  Expected: `False False False`.
- **P2:**
  ```
  d:/ProbOS/.venv/Scripts/python.exe -c "import types; from probos.config import SystemConfig; from probos.startup import finalize; rt = types.SimpleNamespace(); print(finalize._wire_birth_chamber(runtime=rt, config=SystemConfig()), vars(rt))"
  ```
  Expected: `False {}`. At the default, the wirer binds no chamber, no scheduler and no task.
- **P3:** the absence rows in section 15 show that the only setter calls are in the wirer and the proactive attribute is assigned only there. At the default, the three seams' guards are therefore False on every path, so deleting them leaves that path.

## 12. Diff Reviewer: properties to verify (round 1, M1 to M3 together)

1. No file under `src/` contains `BirthChamber`, `DepartmentActivationScheduler`, `birth_chamber` or `holodeck_birth_chamber`. No import of `probos.holodeck.chamber`, `gates`, `phases`, `affect` or `scheduler` remains in `src/` or `tests/`.
2. At the default config, `finalize_startup` calls the same wirers in the same order as the base, minus the chamber's.
3. `wire_agent` runs the same steps for a crew agent: naming, then orientation.
4. `AssignmentService` subscribes every member directly in create and add-member. BF-903's `check_subscribe` still runs before any channel, row or subscription.
5. The proactive cycle's eligibility is the base's minus a branch that was False at the default; the stop and shadow-admission lines are unchanged.
6. A yaml that still carries `holodeck_birth_chamber:` loads through `load_config`, the key is absent from the dump, and the tracked yaml no longer carries it.
7. The holodeck package exports exactly its 14 scenario and team-simulation names, and `scenarios.py` and `team_simulations.py` are untouched.
8. `EventType` loses exactly the six AD-486 members and `GRANDFATHERED` exactly their six rows. The four `HOLODECK_SCENARIO_*` stay, and the import-time completeness check passes.
9. Each generated artifact matches its tool or measurement, and its diff is exactly section 7's allowed diff. This covers the facade baseline, the config reference, the profile manifest row and census, the architecture baseline's `BirthChamber` and `EventType` rows, the two AD-1152 digests and the ledger pair.
10. Every changed count pin states its delta in a comment, and no assertion is loosened. This covers the ad1195 counts, the e2g tables, the e1 facade counts and the architecture fitness count.
11. Deleted tests covered only deleted code. `list_by_phase` stays covered by `tests/test_ad507_curriculum.py:151`, the curriculum wirer by `:194-207`, the prober's wiring by `tests/test_ad487_self_distillation.py:396-397`, and direct subscription by `tests/test_bf903_ward_room_scope.py` (the served POST) and `tests/test_assignment.py`.
12. The DECISIONS heading does not start with an AD or BF token, and the PROGRESS head's first 120 characters hold no ledger status word. AD-1355 resolves `allocated-open`.

## 13. #1700 landing comment

```
**S1 (AD-1355) is merged: the AD-486 Birth Chamber and the department activation scheduler are deleted.** PR <PR link>, merge `<sha>`, broad gate `logs/gates/ad1355-s1.receipt.json` (<N> passed, <M> skipped).

- Deleted: `holodeck/chamber.py`, `gates.py`, `phases.py`, `affect.py`, `scheduler.py` and their exports; `HolodeckBirthChamberConfig` and its `SystemConfig` field; the finalization wirer; `set_birth_chamber` on onboarding and assignment with their branches; the proactive skip; the six AD-486 `HOLODECK_*` event types (390 members, 348 grandfathered); `tests/test_ad486_birth_chamber.py` and `tests/test_ad1270_chamber_module_ids.py`.
- Acceptance (S1): `tests/test_ad1355_birth_chamber_removed.py` (<n> cases) finds no `src/` reference to `BirthChamber`, `DepartmentActivationScheduler`, `birth_chamber` or `holodeck_birth_chamber`, and loads a config that still sets `holodeck_birth_chamber:`. The tracked yaml no longer carries the key.
- No behaviour change at the default: the switch was off in the model, the tracked yaml and the Captain's checkout (probes P1 and P2 on `<base>`); the onboarding, assignment and proactive suites pass.
- Mutation census: <k> of 10 killed, each by its named case, run once on `<overlay>`.
- Regenerated: config reference, facade baseline, profile manifest, architecture baseline, the AD-1152 default-config digests (by measurement), ledger pair.
- Next: S2 (`AcclimationService` in observe mode). This issue stays open for S2 to S9.
```

## 16. Prior Art and Blind Spots

- **Prior art in this repository.** This follows `prompts/ad-1270-boot-camp-tail.md` slice 4c and its census file `tests/test_ad1270_boot_camp_tracker_retired.py`. S1 differs in four ways:
  - its census is a text scan of `src/` against the acceptance line, not per-symbol `hasattr` checks;
  - files are deleted by `Remove-Item` because the Builder runs no git;
  - the DECISIONS heading avoids an AD lead (4c's AD-1270 was already shipped; AD-1355 is not);
  - the profile census is refreshed by measurement because the base's census predates AD-1346 M3c's boolean.
- **External prior art.** Skipped: this is the deletion of dormant internal plumbing with no outside analogue. `docs/research/reference-projects.md` was not consulted, because this is not a design AD.
- **Blind spots.** Each was examined; the outcome:
  - **An operator who set the switch to true** sees agents un-held after S1. That is strictly the default path; recorded in D1 and in DECISIONS' *Effect*.
  - **Stale `.pyc` files** for the deleted modules remain under `holodeck/__pycache__`. Python does not import bytecode from there without the source, and the census skips `__pycache__`.
  - **The curriculum registry loses its only reader.** It is constructed, so `check_dormant_classes` is unaffected; S3 is its consumer.
  - **The Captain's checkout `config/system.yaml`** has local edits (the section sits at `:856`, two lines below the tracked file's `:854`). It keeps loading, because the key is ignored. Stage only the worktree's tracked file.

## 17. Acceptance criteria

- Each item in the Diff Reviewer section holds.
- The broad gate is green, with a receipt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
