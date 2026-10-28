# AD-1270 (#1324) slice 4c: the boot-camp tail -- the AD-509 phase tracker and AD-638's uncalled phases 2 and 3 deleted, AD-683's snapshot keyed on enrolment through the coordinator, BF-261's late-bind through a public setter, and the birth chamber's module ids

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28 (Amendment A1: re-anchored on the final slice-4b head `8f0454b5`)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28 (Amendment A2: P-T17 pins the e1 surface counts the oracle measured; section 10 restated in the census grammar)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28 (Amendment A3: head-text hygiene; which text describes the head)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28 (Amendment A4, on `8cb4bad5`: round 1's three false statements deleted: §6's AD-1195 case cell, P-C27's `_own_nodes` docstring, P-T11's roadmap citation)

**Status:** build-ready. Drafted on `77f8fd67` (`origin/main` `7c85ebaf` + the 4b contract `d147c536` + 4b's candidate applied by tool). **Amendment A1** re-anchors every pair on `8f0454b5` (slice 4b's M3 commit, after its R1 and R2), turns the draft's prose edits into pairs, and folds in 4b-R12, 4b-R13, 4b-R6's A2 note and 4b-R14. It builds after 4b merges. **A3:** 4b's commits after `8f0454b5` change only its own contract and `tests/test_ad1324_srp_layout.py` (R3), and no pair here touches either (`git diff --stat 8f0454b5 d8e6eb7f`; `git diff --stat d8e6eb7f 804345c3`). A2's dry run applied all 70 pairs, with no failure, to `d8e6eb7f`, whose source and tests equal 4b's final head `804345c3` (tree `3f9bf0e2`). 4b's merge tree equals `3f9bf0e2` only if `origin/main` has not moved; the orchestrator confirms it after the merge. No new AD or BF number: this is slice 4c of #1324. **Captain:** nothing parked. Overrulable: D2 (event types), D3 (phases 2 and 3), D4 (the snapshot in enrolled agents' DMs and its label), D5 (setter precedence).

**Anchors (A1):** every pair anchors on `8f0454b5`; P-C28 to P-C30 apply to the text P-T12 to P-T14 produce in M1. Slice 4b's register rows are cited as 4b-R4 to 4b-R14 and this slice's own as 4c-R1 to 4c-R4 (numbering restarts per contract). 70 pairs (A2 adds P-T17's four), three new files (§7.1.N, §7.5.N, §7.7.N) and one `git rm` (P-T3). Regenerate by tool: `config-facade-baseline.yaml`, `config-reference.md`, the AD-1152 golden's two hashes (by measurement, §7.6), and the ledger files (M4).

**Which text describes the head (A3).** These are records of the tree they were written on: line numbers, counts, site lists and absences in the Status and Anchors paragraphs, §1, §3, §5 (its line numbers and site lists), §7 (pairs, new files and §7.6), §8's head constraint, §10, §11, every Verified and Absence block, the Not verified list and §13; and the tests-first predictions and build orders in §4 and §6. Unlabelled text was written on `77f8fd67` (the draft), (A1) on `8f0454b5`, (A2) on the oracle `43f54b7f` and (A3) on the oracle `4f24469f`. They are not restated for the head: for example §1's `chamber.py:289` reads `:290` on `4f24469f`. Where an earlier statement and a later amendment differ, the later amendment wins. The front matter's Milestones and Tests lists, §2, §4's focused-gate table, §5's other sentences, §6's file and case columns, §8's U1 and U2, §9, §12, §14 and §15 describe the candidate's head. They name no commit, and each count in them is one that a named command, a focused gate or the broad gate measures.

**Milestones:**
- **M1 (HIGH):** 4b-R4, the AD-509 tracker and `BOOT_CAMP_PHASE_ADVANCED`.
- **M2 (HIGH):** 4b-R5 + 4b-R6, the coordinator: phases 2 and 3, `nudge_cooldown_seconds`, `ward_room`, `BOOT_CAMP_PHASE_ADVANCE`, the snapshot keyed on enrolment (which ends 4b-R6's A2 read of a stale marker), the BF-261 setter behind a finalization helper with a behavioural test (4b-R13), `BootCampConfig` field descriptions (4b-R12) and the chain census keyed by qualified name (4b-R14).
- **M3 (STANDARD):** 4b-R7, the birth chamber's module ids: `holodeck/chamber.py` reads `m.module_id`.
- **M4 (docs):** trackers.

Each milestone is one Builder delegation and one local commit, staged by explicit path (never `git add -A`). Stage `config/system.yaml` by partial hunk only. One cross-family review (`gpt-6.1-sol`) of M1 to M3 against §14. One mutation campaign of record on the M3 tree (§10). Broad gate once, after M4: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-boot-camp-tail --receipt logs/gates/ad1270-boot-camp-tail.receipt.json`.

**Tests:**
- New: `tests/test_ad1270_boot_camp_tracker_retired.py` (M1, 11 cases), `tests/test_ad1270_boot_camp_orientation.py` (M2, 21 cases), `tests/test_ad1270_chamber_module_ids.py` (M3, 2 cases): 34 in all, as `pytest <file> -n 0` reports for each (11, 21 and 2 passed).
- Deleted: `tests/test_ad509_boot_camp.py` (15 cases) and 6 `test_ad638_boot_camp.py` cases (phases 2 and 3, nudge cooldown, observation thread). Neither file is parametrized; `test_ad638_boot_camp.py`'s `def test_` count goes from 35 to 29.
- Updated: `test_ad1195_event_persistence_contract.py`, `test_ad1195_durable_event_seam.py`, `test_ad1270e1_config_facade.py`, `test_ad1270e2i_agentic_models.py`, `test_ad1270e2g_crew_models.py`, `test_ad638_boot_camp.py`, `test_ad640_tiered_trust.py`, `test_ad683_ship_state_snapshot.py`, `test_ad1270_boot_camp_trust.py`, `test_ad1270_boot_camp_lifecycle.py`, `test_ad1270_boot_camp_repair_a1.py`, `test_ad486_birth_chamber.py`; fixture `tests/fixtures/ad1152_agentic_off_golden.json` (two hashes, measured). Each updated test file except `test_ad640_tiered_trust.py` and `test_ad683_ship_state_snapshot.py` adds at least one `AD-1270` comment or docstring line; those two only drop the coordinator's `ward_room` argument and the Ward Room doubles built for it.
- A Grep of the three new files for `LOCALAPPDATA|AppData|environ|getenv|subprocess|ProbOSRuntime|Runtime\(|\.start\(` finds nothing.

## 1. Problem

- **The AD-509 tracker** (`crew_development/boot_camp.py`) is built at finalization (`finalize.py:911-926`, `:4179`) and never fed. Nothing calls `advance_phase` or `get_or_create` on it, and nothing reads `runtime.boot_camp_tracker`. Its five phases are not AD-638's 1 to 4. Its config section (`boot_camp_phase:`) and event type (`BOOT_CAMP_PHASE_ADVANCED`) describe a lifecycle that never runs.
- **AD-638 phases 2 and 3** (`boot_camp.py:250-422`) have no caller. They would post, under the Counselor's id, text the Counselor never composed. Their state (`_nudge_cooldowns`, `_observation_thread_id`, four flags), their config (`nudge_cooldown_seconds`), their dependency (`ward_room`) and their event (`BOOT_CAMP_PHASE_ADVANCE`) are inert.
- **AD-683's snapshot reaches no prompt with the relaxation off, and a stale one with it on.** The reader (`cognitive_agent.py:10477-10497`) is on the `direct_message` branch and keys on `_boot_camp_active`. Since 4b's A2 that marker is written only by `_refresh_boot_camp_relaxation` (`:6009-6045`, set at `:6023`), which the three chain phases call while `relax_quality_gates` is on, and `direct_message` is not chain-eligible (`:348-351`). So with the flag off the block never renders; with it on, it renders only after a chain falls through to the single call (`_decide_via_llm` → `_build_user_message`, `:3985`), on the last phase's answer, even when that relaxation has since ended (4b-R6's A2 note).
- **BF-261** writes the coordinator's private `_ship_state_builder` from `finalize.py:4221-4224`, and no test detects the late-bind's removal (4b-R13).
- **`BootCampConfig`'s fields carry no description** (`config_models/crew.py:15-28`), so every `boot_camp` row of `config-reference.md` (`:2671-2679`) is blank, `relax_quality_gates` included (4b-R12).
- **4b's chain census** (`tests/test_ad1270_boot_camp_trust.py:272-283`) keys methods by bare name and credits a nested function's calls to the method around it (4b-R14).
- **`holodeck/chamber.py:289`** reads `m.id` from AD-507's `CurriculumModule`, whose key is `module_id`, so `HOLODECK_PHASE_ENTERED.modules` is a list of empty strings.

## 2. Solution

Delete the tracker and phases 2 and 3 with the surfaces §7's pairs and P-T3's `git rm` remove (config, event types, state, exports, the wirer, the coordinator's `ward_room` parameter and their tests). A config still carrying the removed keys keeps loading, because unknown keys are ignored (the BF-926 precedent), and the tracked yaml stops carrying them.

The coordinator gains two public methods:
- `bind_ship_state_builder`, replacing BF-261's private write.
- `orientation_snapshot_text(agent_id)`: the rendered snapshot for an enrolled agent, else `""`. It asks `is_enrolled` first, so the read enforces the timeout.

Finalization gains `_late_bind_boot_camp_snapshot`, the setter's one caller in `src`, so the late-bind is tested by behaviour as well as by position. Each `BootCampConfig` field gains a `Field(description=...)`, and 4b's chain census is keyed by qualified name.

The DM branch reads `orientation_snapshot_text`, keyed on enrolment, under a header that says when the snapshot was captured. The chamber reads `m.module_id`.

## 3. Decisions

D1 to D6 are in the Architect's answer that accompanies this contract. In short: one slice; both event types deleted; R5 as decided; R6 in the envelope (its switch is `ship_state_snapshot.enabled`); the setter never replaces an injected builder; R5 and R6 share M2 so that `BootCampCoordinator` keeps the `[methods]` trigger (19 → 17) and stays well under 500 lines.

**Amendment A1 (D7 to D11).**
- **D7.** 4b-R10 (BF-034's detector) stays a #1324 register row, built as slice 4d after this slice merges, under its own BF number allocated when its prompt is drafted. No new issue: the wave's discovery budget is spent, the finding is neither security nor data-integrity, and it is fixable inside #1324.
- **D8.** 4b-R12 lands in M2, in the same facade and reference regeneration as the field removal.
- **D9.** 4b-R13: the late-bind moves into `_late_bind_boot_camp_snapshot` (a module function: `BootCampCoordinator` stays at 17 methods). The AST case pins its position; a behavioural case pins its effect from the helper, through activation, to an enrolled agent's DM.
- **D10.** `orientation_snapshot_text` asks `is_enrolled` before it checks the snapshot, so the DM read expires the boot camp with or without a snapshot, as the coordinator's other reads do (4b D4). It can emit the one `BOOT_CAMP_TIMEOUT` from prompt construction; `_emit` is guarded (`boot_camp.py:540-546`).
- **D11.** 4b-R14 is folded in (P-C27): qualified names, and a nested definition classified as its own entry. It is behaviour-preserving on this tree. A second guard, in §7.5.N, pins the one enrolment read in the prompt builder.

## 4. Milestones

Write each milestone's new test file first and run it on that milestone's base:
- **M1:** all 11 cases fail by assertion, with no collection error.
- **M2:** 20 of 21 fail, by `TypeError` (`ward_room` is still required), `AttributeError` (`bind_ship_state_builder`, `orientation_snapshot_text`) or assertion (the prompt-builder census; the field descriptions). `test_a_non_text_answer_from_the_runtime_adds_nothing` passes on the base, by design: the base never reads `boot_camp` on this path. Any other case passing is a stop. P-C27's census change to `tests/test_ad1270_boot_camp_trust.py` is behaviour-preserving: that file passes on the base and after M2.
- **M3:** both cases fail.

Never delete or loosen a test beyond the listed removals. Run focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| M | Tier | Sections | Focused gate |
|---|---|---|---|
| **M1** | HIGH | 7.1 | `tests/test_ad1270_boot_camp_tracker_retired.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_durable_event_seam.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2i_agentic_models.py tests/test_ad1152_agentic_correlation.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_bf926_config_readers.py tests/test_ad507_curriculum.py tests/test_ad512_discovery_learning.py tests/test_ad486_birth_chamber.py tests/test_finalize.py tests/test_bf927_boot_claims.py tests/test_events.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py`; then `-P scripts/check_config_facade.py --check`, `-P scripts/check_config_profiles.py --check`, `scripts/gen_config_reference.py --check`, `-P scripts/check_architecture_principles.py --check`, `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M2** | HIGH | 7.2 to 7.5 | `tests/test_ad1270_boot_camp_orientation.py tests/test_ad638_boot_camp.py tests/test_ad640_tiered_trust.py tests/test_ad683_ship_state_snapshot.py tests/test_ad1270_boot_camp_trust.py tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270e2g_crew_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1195_event_persistence_contract.py tests/test_ad1195_durable_event_seam.py tests/test_ad1028_context_assembler.py tests/test_ad1029_attention_faculty.py tests/test_ad1030_salience.py tests/test_ad1031_camera_bid.py tests/test_ad1227_recent_outputs.py tests/test_bf907_trust_identity.py tests/test_ad723a_1_consumer_migration.py tests/test_ad639_chain_tuning.py tests/test_ad632g_cognitive_jit_integration.py tests/test_cognitive_agent.py tests/test_finalize.py tests/test_bf927_boot_claims.py tests/test_ad1185_config_profiles.py tests/test_config_reference_current.py tests/test_bf926_config_readers.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py`; then the five script checks as in M1 |
| **M3** | STANDARD | 7.7 | `tests/test_ad1270_chamber_module_ids.py tests/test_ad486_birth_chamber.py tests/test_ad507_curriculum.py` |
| **M4** | docs | §8; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` | `tests/test_ad1184_ad_ledger.py`; `-P scripts/gen_ad_ledger.py --check`. AD-1270 must still resolve `shipped` (the `AD-1270` line of `open-ads-report.md` that reads "Resolved as `shipped`" is unchanged) |

**A1:** M2's focused gate also runs `tests/test_ad1270_boot_camp_repair_a1.py`.

**M1 build order:**
1. Write 7.1.N and run it (11 named failures).
2. Apply the test pairs P-T12 to P-T17.
3. `git rm src/probos/crew_development/boot_camp.py tests/test_ad509_boot_camp.py`; apply P-T1, P-T2 and P-T4 to P-T11, then P-T18.
4. Measure the census with the instrument. Predicted: 450, 227, 223, 85, 142. Any other value is a stop.
5. Regenerate: `-P scripts/check_config_facade.py --update-baseline` and `scripts/gen_config_reference.py`.
6. Check the facade diff. Allowed:
   - `BootCampPhaseConfig` gone from `names` and `models`;
   - `SystemConfig`'s field list (−1) and `schema_sha256`;
   - `field_definitions` 1881 → 1879 and `canonical_dump_leaves` 1891 → 1890;
   - in `surface_counts`, `public_names` 310 → 309, `owned` 297 → 296 and `own_models` 229 → 228 (the check then prints `names=309`; P-T17 pins all four, A2);
   - the top-level `canonical_dump_sha256`.

   Nothing else. The reference diff must show only the `## boot_camp_phase` section (and its summary line, if the generator lists one) going.
7. AD-1152 golden (§7.6).
8. Run the focused gate. Commit.

**M2 build order:**
1. Write 7.5.N and run it (as above).
2. Apply the test pairs P-C16 to P-C22 and P-C24 to P-C31 (P-C28 to P-C30 apply to the text P-T12 to P-T14 produced in M1).
3. Apply P-C1 to P-C15, P-C32 and P-C33.
4. Regenerate the facade and the reference. Allowed facade diff:
   - `BootCampConfig`'s fields (−1) and `schema_sha256` (the removal moves it; the JSON schema also carries the new descriptions);
   - `SystemConfig`'s `schema_sha256`;
   - `field_definitions` 1879 → 1878 and `canonical_dump_leaves` 1890 → 1889;
   - `canonical_dump_sha256`.

   Nothing else: a description is not a field entry, a default or a dump leaf. Reference: the `nudge_cooldown_seconds` row goes and each of the eight remaining `boot_camp` rows gains its description; nothing else. Census: unchanged (no boolean moves).
5. AD-1152 golden (§7.6).
6. Run the focused gate. `check_architecture_principles.py --check` must pass with `BootCampCoordinator` at 17 methods and triggers `[methods]`, and no row change. A `lines` trigger or a stale row is a stop.
7. Commit.

**M3 build order:** write 7.7.N and run it (2 failures); apply P-H1 and P-H2; run the gate; commit.

## 5. Consumers of every value this removes or changes

- `SystemConfig.boot_camp_phase`: read only by `_wire_boot_camp_tracker`, which is deleted. Operator files: ignored.
- `BootCampConfig.nudge_cooldown_seconds`: read only by `_can_nudge`, deleted. Tests set it in 4b helpers: removed (P-C21, P-C22, P-C31). `BootCampConfig` declares no `model_config`, so a leftover key is ignored, not rejected.
- `EventType.BOOT_CAMP_PHASE_ADVANCED` and `BOOT_CAMP_PHASE_ADVANCE`: no subscriber in `src` or `ui/src` before the slice (the first Absence block); after it, a Grep of both for `BOOT_CAMP_PHASE|boot_camp_phase_advance` finds nothing.
- `BootCampCoordinator(ward_room=...)`: `runtime.py:3332` and eight test sites (ad638:92, ad640:212 and :242, ad683:243 and :265, trust:50, lifecycle:65, repair_a1:56), all keyword, all changed.
- The `direct_message` prompt: consumed by the LLM. Default byte-identical for every agent that is not enrolled, and for any runtime whose `boot_camp` is `None`, missing, or answers with a non-`str`. A Grep of `src` and `tests` for `\.boot_camp\s*=[^=]|boot_camp=` finds one `src` site, `runtime.py`'s `BootCampCoordinator` assignment, and in tests only coordinators, `None` and the orientation file's `_agent(boot_camp)` rig; a `MagicMock` runtime answers with a non-`str`, which the `isinstance` guard covers.
- The DM read is an expiring reader: `orientation_snapshot_text` → `is_enrolled` → `_expire_if_timed_out`. The first DM build past the deadline can emit the one `BOOT_CAMP_TIMEOUT`; it has no other effect on the prompt.
- `BootCampConfig` field descriptions: read by `gen_config_reference.py` and by the facade's schema digest (`scripts/check_config_facade.py`); a Grep of `src` for `model_json_schema|json_schema|field_info` finds nothing.
- `HOLODECK_PHASE_ENTERED.modules`: a Grep of `src` and `ui/src` for `HOLODECK_PHASE_ENTERED|holodeck_phase_entered` finds its declaration, its `GRANDFATHERED` entry and `chamber.py`'s three emits, and no subscriber.

## 6. Tests

New files are in §7.1.N, §7.5.N and §7.7.N (34 cases: 11, 21 and 2, as running each file reports). Updated tests are paired in §7.

| File | Cases | On its milestone's base | Change |
|---|---|---|---|
| `tests/test_ad1270_boot_camp_tracker_retired.py` (M1) | 11 | 11 fail by assertion | unchanged by A1 |
| `tests/test_ad1270_boot_camp_orientation.py` (M2) | 21 | 20 fail; the non-text case passes | A1 adds `test_a_stale_relaxation_marker_adds_no_snapshot` (4b-R6 A2), `test_the_dm_read_ends_an_expired_boot_camp[with-snapshot]` and `[without-snapshot]`, `test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder` (guard), `test_finalization_late_bind_reaches_an_enrolled_agents_dm` (4b-R13) and `test_every_boot_camp_field_is_described` (4b-R12); rewrites `test_finalization_late_binds_through_the_public_setter` for the helper |
| `tests/test_ad1270_chamber_module_ids.py` (M3) | 2 | 2 fail | unchanged |
| `tests/test_ad1270_boot_camp_trust.py` | unchanged count | passes before and after | P-C21 (helper), P-C27 (census by qualified name, 4b-R14) |
| `tests/test_ad1270_boot_camp_repair_a1.py` | unchanged count | its coordinator cases fail by `TypeError` without P-C31 | P-C31 (helper) |
| `tests/test_ad1195_event_persistence_contract.py`, `tests/test_ad1195_durable_event_seam.py` | | | P-T12 to P-T14 (M1: 396), P-C28 to P-C30 (M2: 395) |
| `tests/test_ad638_boot_camp.py` | −6 | | P-C16 to P-C20 |

## 7. The contract

### 7.1 M1: the AD-509 tracker

**P-T1 (`src/probos/crew_development/__init__.py`).** SEARCH:
```
from probos.crew_development.boot_camp import (
    AgentBootCampRecord,
    BootCampPhase,
    BootCampPhaseTracker,
)
from probos.crew_development.discovery import (
```
REPLACE:
```
from probos.crew_development.discovery import (
```

**P-T2 (same file).** SEARCH:
```
    "CurriculumModule",
    "AgentBootCampRecord",
    "BootCampPhase",
    "BootCampPhaseTracker",
    "CapabilityConfidence",
```
REPLACE:
```
    "CurriculumModule",
    "CapabilityConfidence",
```

**P-T3.** `git rm src/probos/crew_development/boot_camp.py tests/test_ad509_boot_camp.py`.

**P-T4 (`src/probos/startup/finalize.py`).** SEARCH:
```
def _wire_boot_camp_tracker(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-509 v1: Wire BootCampPhaseTracker (in-memory observational)."""
    cfg = getattr(config, "boot_camp_phase", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.crew_development.boot_camp import BootCampPhaseTracker

    emit_fn = getattr(runtime, "emit_event", None)
    tracker = BootCampPhaseTracker()
    tracker.emit_event = emit_fn
    runtime.boot_camp_tracker = tracker  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-509: Boot Camp Phase Tracker v1 initialized (5 phases + COMPLETED; observational)"
    )
    return True


def _wire_emergence_collector(*, runtime: Any, config: "SystemConfig") -> bool:
```
REPLACE:
```
def _wire_emergence_collector(*, runtime: Any, config: "SystemConfig") -> bool:
```

**P-T5 (same file).** SEARCH:
```
    if _wire_curriculum_registry(runtime=runtime, config=config):
        logger.info("AD-507: Crew Development Framework v1 wired during finalization")

    if _wire_boot_camp_tracker(runtime=runtime, config=config):
        logger.info("AD-509: Boot Camp Phase Tracker v1 wired during finalization")

    if _wire_birth_chamber(runtime=runtime, config=config):
```
REPLACE:
```
    if _wire_curriculum_registry(runtime=runtime, config=config):
        logger.info("AD-507: Crew Development Framework v1 wired during finalization")

    if _wire_birth_chamber(runtime=runtime, config=config):
```

**P-T6 (`src/probos/config.py`).** SEARCH:
```
class BootCampPhaseConfig(BaseModel):
    """AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

    Disambiguated from AD-638 ``BootCampConfig`` (cold-start boot camp); the
    AD-509 v1 tracker records 5-phase progression per agent.
    """

    enabled: bool = True
    # v1: tracker only. A-School curriculum, graduated stimuli,
    # completion-criteria gating, and trait-adaptive pacing are deferred
    # to AD-509b/c/d/e.


class SelfContradictionRecallConfig(BaseModel):  # AD-1293 (#1200)
```
REPLACE:
```
class SelfContradictionRecallConfig(BaseModel):  # AD-1293 (#1200)
```

**P-T7 (same file).** SEARCH:
```
    crew_development: CrewDevelopmentConfig = Field(default_factory=CrewDevelopmentConfig)  # AD-507
    boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)  # AD-509
    discovery_learning: DiscoveryLearningConfig = Field(default_factory=DiscoveryLearningConfig)  # AD-512
```
REPLACE:
```
    crew_development: CrewDevelopmentConfig = Field(default_factory=CrewDevelopmentConfig)  # AD-507
    # AD-1270 (#1324): boot_camp_phase (AD-509) was removed; a config that still sets it loads.
    discovery_learning: DiscoveryLearningConfig = Field(default_factory=DiscoveryLearningConfig)  # AD-512
```

**P-T8 (`src/probos/events.py`).** SEARCH:
```
    CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507

    # ── Boot Camp Phase Tracker (AD-509) ───────────────────────────
    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"  # AD-509

    # AD-486: Holodeck Birth Chamber phase events
```
REPLACE:
```
    CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507

    # AD-486: Holodeck Birth Chamber phase events
```

**P-T9 (`src/probos/event_persistence.py`).** SEARCH:
```
    "BOOT_CAMP_PHASE_ADVANCE",
    "BOOT_CAMP_PHASE_ADVANCED",
    "BOOT_CAMP_TIMEOUT",
```
REPLACE:
```
    "BOOT_CAMP_PHASE_ADVANCE",
    "BOOT_CAMP_TIMEOUT",
```

**P-T10 (`config/system.yaml`; stage this hunk only).** SEARCH:
```
crew_development:
  enabled: true
boot_camp_phase:
  enabled: true
discovery_learning:
```
REPLACE:
```
crew_development:
  enabled: true
discovery_learning:
```

**P-T11 (`src/probos/holodeck/phases.py`).** SEARCH:
```
    Distinct from AD-509 ``BootCampPhase`` (orientation/core_knowledge/
    a_school/calibration/integration). AD-486 phases mirror the spec at
    docs/development/roadmap.md:4130: orientation -> calibration ->
```
REPLACE:
```
    AD-509's separate five-phase ``BootCampPhase`` (orientation/core_knowledge/
    a_school/calibration/integration) was deleted by AD-1270 (#1324). AD-486 phases: orientation -> calibration ->
```

**P-T12 (`tests/test_ad1195_event_persistence_contract.py`).** SEARCH:
```
    """DECL-1: 397 members = 41 declared + 356 grandfathered, disjoint."""
```
REPLACE:
```
    """DECL-1: 396 members = 41 declared + 355 grandfathered, disjoint.

    AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED with its one producer (AD-509's
    tracker): 397 -> 396, 356 -> 355. The DECL-3 golden snapshot keeps its 356 names.
    """
```
and SEARCH:
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (397, 41, 356)
```
REPLACE:
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 41, 355)
```

**P-T13 (same file).** SEARCH:
```
    assert broken == []
    assert len(EventType) == 397
```
REPLACE:
```
    assert broken == []
    assert len(EventType) == 396  # AD-1270 (#1324) slice 4c: BOOT_CAMP_PHASE_ADVANCED deleted
```

**P-T14 (`tests/test_ad1195_durable_event_seam.py`).** SEARCH:
```
    assert len(EventType) == 397
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 368)
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED, an unrouted member: 397 -> 396.
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 367)
```

**P-T15 (`tests/test_ad1270e2i_agentic_models.py`).** SEARCH:
```
    "ArchivePromotionConfig",
    "BootCampPhaseConfig",
    "ConsultationDeliveryConfig",
```
REPLACE:
```
    "ArchivePromotionConfig",
    # AD-1270 (#1324) slice 4c deleted BootCampPhaseConfig (AD-509): it left config.py, not moved.
    "ConsultationDeliveryConfig",
```

**P-T16 (`tests/test_ad1270e1_config_facade.py`; re-anchor after 4b).** SEARCH:
```
    assert counts["field_definitions"] == 1881  # AD-1206 intentionally adds github_repository.
    assert counts["aliased_fields"] == 1
    assert len(baseline["names"]) == 310  # AD-1341 S5 (#1569): ArchivePromotionConfig
    assert len(baseline["models"]) == 230  # AD-1341 S5 (#1569): ArchivePromotionConfig
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c removes BootCampPhaseConfig.enabled and SystemConfig.boot_camp_phase (1881 -> 1879).
    assert counts["field_definitions"] == 1879  # AD-1206 intentionally adds github_repository.
    assert counts["aliased_fields"] == 1
    # AD-1270 (#1324) slice 4c removes the BootCampPhaseConfig model (names 310 -> 309, models 230 -> 229).
    assert len(baseline["names"]) == 309  # AD-1341 S5 (#1569): ArchivePromotionConfig
    assert len(baseline["models"]) == 229  # AD-1341 S5 (#1569): ArchivePromotionConfig
```

**P-T17 (`tests/test_ad1270e1_config_facade.py`; Amendment A2: the surface counts and the check's `names=` that removing `BootCampPhaseConfig` moves).** SEARCH:
```
    assert counts["public_names"] == 310  # AD-1341 S5 (#1569) adds ArchivePromotionConfig (309 -> 310)
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c removes the owned model BootCampPhaseConfig: public_names 310 -> 309,
    # owned 297 -> 296, own_models 229 -> 228, and the check prints names=309.
    assert counts["public_names"] == 309  # AD-1341 S5 (#1569) adds ArchivePromotionConfig (309 -> 310)
```
and SEARCH:
```
    assert counts["owned"] == 297  # AD-1341 S5 (#1569): ArchivePromotionConfig is owned (296 -> 297)
```
REPLACE:
```
    assert counts["owned"] == 296  # AD-1341 S5 (#1569): ArchivePromotionConfig is owned (296 -> 297)
```
and SEARCH:
```
    assert counts["own_models"] == 229  # AD-1341 S5 (#1569): ArchivePromotionConfig (228 -> 229)
```
REPLACE:
```
    assert counts["own_models"] == 228  # AD-1341 S5 (#1569): ArchivePromotionConfig (228 -> 229)
```
and SEARCH:
```
    assert "names=310" in proc.stdout  # AD-1341 S5 (#1569): ArchivePromotionConfig
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c removes BootCampPhaseConfig (names=310 -> names=309).
    assert "names=309" in proc.stdout  # AD-1341 S5 (#1569): ArchivePromotionConfig
```

**P-T18 (`docs/development/config-profiles.yaml`; re-anchor after 4b).** SEARCH:
```
  measured_at_commit: AD-1270 (issue 1324) slice 4b M1 on the slice-4 merge, every count re-measured with
    this instrument (slice 4b adds boot_camp.relax_quality_gates, a default-False boolean no tracked
    config arms; slice 3 measured 450, 226, 224, 85 and 141)
```
REPLACE:
```
  measured_at_commit: AD-1270 (issue 1324) slice 4c M1 on the slice-4b merge, every count re-measured with
    this instrument (slice 4c removes boot_camp_phase.enabled, a default-True boolean; slice 4b
    measured 451, 227, 224, 85 and 142)
```
and SEARCH:
```
  boolean_fields_reachable: 451
  default_false: 227
  default_true: 224
```
REPLACE (with the measured values; predicted):
```
  boolean_fields_reachable: 450
  default_false: 227
  default_true: 223
```

#### 7.1.N New file: `tests/test_ad1270_boot_camp_tracker_retired.py` (11 cases)

```python
"""AD-1270 (#1324) slice 4c, M1: the AD-509 boot-camp phase tracker is deleted, not wired.

Finalization built it and nothing fed it: no caller of ``advance_phase`` or ``get_or_create``
and no reader of ``runtime.boot_camp_tracker``. Its five phases are not AD-638's 1 to 4, and
AD-486's birth chamber carries the orientation phases. A config that still carries
``boot_camp_phase:`` keeps loading, because SystemConfig ignores unknown keys (the BF-926
precedent); the Captain's own file is one.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

import probos.config as config_module
import probos.crew_development as crew_development
from probos import event_persistence as ep
from probos.config import SystemConfig, load_config
from probos.events import EventType
from probos.startup import finalize

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_READERS = _REPO / "scripts" / "check_config_readers.py"
_TRACKER_NAMES = ("AgentBootCampRecord", "BootCampPhase", "BootCampPhaseTracker")


def _load_readers():
    spec = importlib.util.spec_from_file_location("_ad1270_4c_config_readers", _READERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_tracker_module_is_gone() -> None:
    assert importlib.util.find_spec("probos.crew_development.boot_camp") is None
    assert not (_SRC / "crew_development" / "boot_camp.py").exists()


@pytest.mark.parametrize("name", _TRACKER_NAMES)
def test_the_package_no_longer_exports_the_tracker(name: str) -> None:
    assert name not in crew_development.__all__
    assert not hasattr(crew_development, name)


def test_the_package_keeps_its_other_exports() -> None:
    """Premise for the case above: the deletion took the tracker's three names and nothing else."""
    assert len(crew_development.__all__) == 14
    for name in crew_development.__all__:
        assert hasattr(crew_development, name), name


def test_finalization_no_longer_wires_a_tracker() -> None:
    assert not hasattr(finalize, "_wire_boot_camp_tracker")
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "_wire_birth_chamber" in called  # premise: the scan sees the neighbouring wirer
    assert "_wire_boot_camp_tracker" not in called
    assert "ship_state_snapshot" in attributes  # premise: the scan sees runtime attributes
    assert "boot_camp_tracker" not in attributes


def test_the_config_field_and_model_are_gone() -> None:
    assert "crew_development" in SystemConfig.model_fields  # premise: its neighbour stays
    assert "boot_camp_phase" not in SystemConfig.model_fields
    assert not hasattr(config_module, "BootCampPhaseConfig")
    assert "boot_camp_phase" not in SystemConfig().model_dump()


@pytest.mark.parametrize("enabled", [True, False])
def test_a_config_that_still_sets_boot_camp_phase_loads(enabled: bool, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(
        yaml.safe_dump({"boot_camp_phase": {"enabled": enabled}, "crew_development": {"enabled": False}}),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.crew_development.enabled is False  # the file was read
    assert "boot_camp_phase" not in cfg.model_dump()


def test_the_tracked_yaml_carries_no_boot_camp_phase_key(tmp_path: Path) -> None:
    readers = _load_readers()
    document = yaml.safe_load(readers.DEFAULT_YAML.read_text(encoding="utf-8"))
    assert "crew_development" in document  # premise: this is the tracked config
    assert "boot_camp_phase" not in document

    # Control: the reader check reports the section as a key no field declares when it is present.
    (tmp_path / "src").mkdir()
    report = readers.build_report(
        SystemConfig, tmp_path / "src", {**document, "boot_camp_phase": {"enabled": True}},
    )
    assert "boot_camp_phase" in report.orphan_yaml_keys
    assert "crew_development" not in report.orphan_yaml_keys


def test_the_event_type_and_its_grandfathered_entry_are_gone() -> None:
    assert "BOOT_CAMP_ACTIVATED" in ep.GRANDFATHERED  # premise: its AD-638 neighbours stay
    assert "BOOT_CAMP_PHASE_ADVANCED" not in EventType.__members__
    assert "boot_camp_phase_advanced" not in {member.value for member in EventType}
    assert "BOOT_CAMP_PHASE_ADVANCED" not in ep.GRANDFATHERED
    assert ep.assert_complete(EventType.__members__) is None
```

### 7.2 M2: `src/probos/boot_camp.py`

**P-C1.** SEARCH:
```
class WardRoomProtocol(Protocol):
    """Narrow interface for Ward Room operations."""

    async def get_or_create_dm_channel(
        self, agent_a_id: str, agent_b_id: str,
        callsign_a: str, callsign_b: str,
    ) -> Any: ...

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str, thread_mode: str, max_responders: int,
    ) -> Any: ...

    async def create_post(
        self, thread_id: str, author_id: str, body: str,
        parent_id: str | None, author_callsign: str,
    ) -> Any: ...

    async def list_channels(self) -> list: ...


class EpisodicMemoryProtocol(Protocol):
```
REPLACE:
```
class EpisodicMemoryProtocol(Protocol):
```

**P-C2.** SEARCH:
```
    enrolled_at: float = field(default_factory=time.time)
    phase: int = 1  # 1=orientation, 2=introductions, 3=observation, 4=graduated
    introduced_to_chief: bool = False
    cross_dept_contact: bool = False
    shared_observation: bool = False
    notebook_started: bool = False
    ward_room_posts: int = 0
```
REPLACE:
```
    enrolled_at: float = field(default_factory=time.time)
    # 1=enrolled, 4=graduated. AD-1270 (#1324) deleted phases 2 and 3, which had no caller.
    phase: int = 1
    ward_room_posts: int = 0
```

**P-C3.** SEARCH:
```
# Department chief mapping — same callsigns used in standing_orders.py
_DEPARTMENT_CHIEFS: dict[str, str] = {
    "medical": "Bones",
    "engineering": "LaForge",
    "science": "Number One",
    "security": "Worf",
    "operations": "O'Brien",
    "communications": "Uhura",
}


class BootCampCoordinator:
    """Manages cold-start boot camp lifecycle.

    Responsibilities:
    - Detect cold-start and enroll crew agents
    - Drive structured introduction exercises via Counselor
    - Relax quality gates during boot camp (context flag)
    - Track graduation criteria per agent
    - Transition agents to active duty

    Does NOT own: trust scoring, onboarding wiring, quality gate logic,
    Ward Room infrastructure, or Counselor agent behavior.
    """

    def __init__(
        self,
        config: BootCampConfig,
        ward_room: WardRoomProtocol,
        trust_service: TrustServiceProtocol,
```
REPLACE:
```
class BootCampCoordinator:
    """Manages cold-start boot camp lifecycle.

    Responsibilities:
    - Enroll cold-start crew agents
    - Relax quality gates while enrolled, only when ``relax_quality_gates`` is on
    - Offer enrolled agents the AD-683 cold-start snapshot
    - Track graduation criteria per agent
    - Transition agents to active duty

    Does NOT own: trust scoring, onboarding wiring, quality gate logic,
    Ward Room infrastructure, or Counselor agent behavior. AD-1270 (#1324)
    deleted the uncalled Counselor-voiced introduction and observation phases.
    """

    def __init__(
        self,
        config: BootCampConfig,
        trust_service: TrustServiceProtocol,
```

**P-C4.** SEARCH:
```
        self._ward_room = ward_room
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        self._nudge_cooldowns: dict[str, float] = {}
        self._observation_thread_id: str | None = None
        # AD-683: Cold-start ship state snapshot — populated at activate() end.
```
REPLACE:
```
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        # AD-683: Cold-start ship state snapshot — populated at activate() end.
```

**P-C5.** SEARCH:
```
    def get_state(self, agent_id: str) -> AgentBootCampState | None:
        """Get boot camp state for an agent."""
        return self._agents.get(agent_id)

    # --- Public API ---
```
REPLACE:
```
    def get_state(self, agent_id: str) -> AgentBootCampState | None:
        """Get boot camp state for an agent."""
        return self._agents.get(agent_id)

    def bind_ship_state_builder(self, builder: Any) -> bool:
        """BF-261 / AD-1270 (#1324): late-bind the AD-683 builder unless one was injected.

        Finalization builds the builder after this coordinator (Phase 7) and binds it before
        ``activate``, which captures the snapshot once; a bind after activation captures
        nothing. True when bound.
        """
        if builder is None or self._ship_state_builder is not None:
            return False
        self._ship_state_builder = builder
        return True

    def orientation_snapshot_text(self, agent_id: str) -> str:
        """AD-683 / AD-1270 (#1324): the cold-start snapshot for an enrolled agent, else "".

        Keyed on enrolment, not on ``relax_quality_gates``: it is context, not a gate. It asks
        ``is_enrolled`` first, so it enforces the timeout like the other reads, with or without
        a snapshot. The text is the snapshot captured at ``activate``.
        """
        if not self.is_enrolled(agent_id) or self.ship_state_snapshot is None:
            return ""
        try:
            return self.ship_state_snapshot.render_text()
        except Exception:
            logger.debug("AD-683: ship_state_snapshot.render_text failed; no snapshot this turn", exc_info=True)
            return ""

    # --- Public API ---
```

**P-C6.** SEARCH (on this tree, the lines from `check_graduation`'s last two lines through the line above `force_graduate_all`; pre-4b text):
```
        await self._graduate_agent(state, episode_count, trust)
        return True

    async def run_phase_2_introductions(
        self, counselor_id: str, counselor_callsign: str,
    ) -> None:
        """Counselor-driven introduction exercises."""
        # Group agents by department for cross-department pairing
        by_dept: dict[str, list[AgentBootCampState]] = {}
        for state in self._agents.values():
            if state.graduated:
                continue
            by_dept.setdefault(state.department, []).append(state)

        dept_names = list(by_dept.keys())

        for state in self._agents.values():
            if state.graduated or state.phase >= 2:
                continue

            # Cooldown check
            if not self._can_nudge(state.agent_id):
                continue

            # Exercise 1: Introduce to department chief
            chief_callsign = _DEPARTMENT_CHIEFS.get(state.department, "")
            if chief_callsign and not state.introduced_to_chief:
                try:
                    dm_channel = await self._ward_room.get_or_create_dm_channel(
                        counselor_id, state.agent_id,
                        counselor_callsign, state.callsign,
                    )
                    thread = await self._ward_room.create_thread(
                        channel_id=dm_channel.id,
                        author_id=counselor_id,
                        title=f"Welcome aboard, {state.callsign}",
                        body=(
                            f"You should introduce yourself to {chief_callsign}, "
                            f"your department chief. Send them a DM about your role "
                            f"and what you bring to the department."
                        ),
                        author_callsign=counselor_callsign,
                        thread_mode="discuss",
                        max_responders=0,
                    )
                    self._record_nudge(state.agent_id)
                    logger.debug(
                        "AD-638: Phase 2 chief intro nudge sent to %s",
                        state.callsign,
                    )
                except Exception:
                    logger.debug(
                        "AD-638: Failed to send chief intro nudge to %s",
                        state.callsign, exc_info=True,
                    )

            # Exercise 2: Cross-department contact
            if not state.cross_dept_contact and len(dept_names) > 1:
                # Pick a peer from a different department
                other_depts = [d for d in dept_names if d != state.department]
                if other_depts:
                    target_dept = other_depts[0]
                    peers = by_dept.get(target_dept, [])
                    if peers:
                        peer = peers[0]
                        if self._can_nudge(state.agent_id):
                            try:
                                dm_channel = await self._ward_room.get_or_create_dm_channel(
                                    counselor_id, state.agent_id,
                                    counselor_callsign, state.callsign,
                                )
                                await self._ward_room.create_thread(
                                    channel_id=dm_channel.id,
                                    author_id=counselor_id,
                                    title="Cross-department introduction",
                                    body=(
                                        f"Reach out to {peer.callsign} in {target_dept}. "
                                        f"Building cross-department relationships "
                                        f"strengthens the whole crew."
                                    ),
                                    author_callsign=counselor_callsign,
                                    thread_mode="discuss",
                                    max_responders=0,
                                )
                                self._record_nudge(state.agent_id)
                            except Exception:
                                logger.debug(
                                    "AD-638: Failed to send cross-dept nudge to %s",
                                    state.callsign, exc_info=True,
                                )

            # Advance to phase 2
            if state.phase < 2:
                old_phase = state.phase
                state.phase = 2
                self._emit(EventType.BOOT_CAMP_PHASE_ADVANCE, {
                    "agent_id": state.agent_id,
                    "callsign": state.callsign,
                    "from_phase": old_phase,
                    "to_phase": 2,
                })

    async def run_phase_3_observation(
        self, counselor_id: str, counselor_callsign: str,
    ) -> None:
        """Shared observation thread + notebook prompts."""
        # Create observation thread on All Hands if not already created
        if not self._observation_thread_id:
            try:
                channels = await self._ward_room.list_channels()
                all_hands = next(
                    (c for c in channels if getattr(c, 'channel_type', '') == "ship"),
                    None,
                )
                if all_hands:
                    thread = await self._ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id=counselor_id,
                        title="Boot Camp — Initial Observations",
                        body=(
                            "What have you noticed about the ship's current state? "
                            "Share your professional observations."
                        ),
                        author_callsign=counselor_callsign,
                        thread_mode="discuss",
                        max_responders=0,
                    )
                    self._observation_thread_id = thread.id
            except Exception:
                logger.debug(
                    "AD-638: Failed to create observation thread",
                    exc_info=True,
                )

        # Send notebook prompts to each agent
        for state in self._agents.values():
            if state.graduated or state.phase >= 3:
                continue

            if not self._can_nudge(state.agent_id):
                continue

            try:
                dm_channel = await self._ward_room.get_or_create_dm_channel(
                    counselor_id, state.agent_id,
                    counselor_callsign, state.callsign,
                )
                await self._ward_room.create_thread(
                    channel_id=dm_channel.id,
                    author_id=counselor_id,
                    title="Initial assessment",
                    body=(
                        "Start a notebook entry about your initial assessment "
                        "of your department's baseline."
                    ),
                    author_callsign=counselor_callsign,
                    thread_mode="discuss",
                    max_responders=0,
                )
                self._record_nudge(state.agent_id)
            except Exception:
                logger.debug(
                    "AD-638: Failed to send notebook nudge to %s",
                    state.callsign, exc_info=True,
                )

            # Advance to phase 3
            if state.phase < 3:
                old_phase = state.phase
                state.phase = 3
                self._emit(EventType.BOOT_CAMP_PHASE_ADVANCE, {
                    "agent_id": state.agent_id,
                    "callsign": state.callsign,
                    "from_phase": old_phase,
                    "to_phase": 3,
                })

    async def force_graduate_all(self) -> None:
```
REPLACE:
```
        await self._graduate_agent(state, episode_count, trust)
        return True

    async def force_graduate_all(self) -> None:
```

**P-C7.** SEARCH:
```
        state.ward_room_posts += 1

        if channel_type == "ship" and self._observation_thread_id:
            state.shared_observation = True

        # Check graduation after each tracked activity
```
REPLACE:
```
        state.ward_room_posts += 1

        # Check graduation after each tracked activity
```

**P-C8 (re-anchor after 4b).** SEARCH:
```
    def _can_nudge(self, agent_id: str) -> bool:
        """Check nudge cooldown for an agent."""
        last = self._nudge_cooldowns.get(agent_id, 0.0)
        return (self._clock() - last) >= self._config.nudge_cooldown_seconds

    def _record_nudge(self, agent_id: str) -> None:
        """Record nudge timestamp."""
        self._nudge_cooldowns[agent_id] = self._clock()

    def _emit(self, event_type: EventType, data: dict) -> None:
```
REPLACE:
```
    def _emit(self, event_type: EventType, data: dict) -> None:
```

**P-C32 (`src/probos/boot_camp.py`; the 4b docstring that names the expiring readers).** SEARCH:
```
        ``is_active``, ``is_enrolled``, ``check_graduation``, ``on_agent_post``,
        ``on_agent_dm`` and ``check_timeout`` call this first; ``relaxes_quality_gates``
        reaches it through ``is_enrolled`` when ``relax_quality_gates`` is on. ``get_state``
        returns the raw state and does not call it.
```
REPLACE:
```
        ``is_active``, ``is_enrolled``, ``check_graduation``, ``on_agent_post``,
        ``on_agent_dm`` and ``check_timeout`` call this first; ``relaxes_quality_gates``
        reaches it through ``is_enrolled`` when ``relax_quality_gates`` is on, and
        ``orientation_snapshot_text`` (the AD-683 DM read) always does. ``get_state``
        returns the raw state and does not call it.
```

### 7.3 M2: config, events, runtime, finalize

**P-C9 (`src/probos/config_models/crew.py`; also 4b-R12, the field descriptions).** SEARCH:
```
    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600
    # AD-1270 (#1324): AD-638's Evaluate/Reflect auto-approval for enrolled crew. Off,
    # enrolment relaxes nothing. On weakens the anti-confabulation gate: the Captain's switch.
    relax_quality_gates: bool = False
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c (4b register R12): each description is the field's generated reference row.
    enabled: bool = Field(
        default=True,
        description=(
            "AD-638: build the boot-camp coordinator (it also needs the Ward Room, trust and episodic "
            "memory) and enrol a new crew at finalization. False: no coordinator and no enrolment."
        ),
    )
    min_episodes: int = Field(default=5, description="Graduation: the agent's episode count must reach this.")
    min_ward_room_posts: int = Field(
        default=3, description="Graduation: Ward Room posts counted while the agent is enrolled.",
    )
    min_dm_conversations: int = Field(
        default=1,
        description=(
            "Graduation: DMs sent to crew while enrolled. A DM to the Captain or an unsent DM "
            "does not count."
        ),
    )
    min_trust_score: float = Field(
        default=0.55,
        description="Activation skips an agent whose trust is at or above this; graduation needs at least this.",
    )
    min_time_minutes: int = Field(
        default=60, description="Graduation: minutes enrolled, on the coordinator's clock.",
    )
    timeout_minutes: int = Field(
        default=120,
        description=(
            "Minutes after activation at which enrolment ends: every agent still enrolled is marked "
            "graduated and one BOOT_CAMP_TIMEOUT is emitted. Nothing is deleted. Enforced by the "
            "coordinator's reads, with no task."
        ),
    )
    # AD-1270 (#1324): nudge_cooldown_seconds was removed with phases 2 and 3; a config that sets it loads.
    relax_quality_gates: bool = Field(
        default=False,
        description=(
            "AD-1270 (#1324): while on, AD-638 auto-approves Evaluate and Reflect for enrolled crew "
            "until they graduate or time out. On weakens the anti-confabulation gate: the Captain's "
            "switch. Off (the default), enrolment relaxes nothing."
        ),
    )
```

**P-C10 (`config/system.yaml`; stage this hunk only).** SEARCH:
```
  min_time_minutes: 60
  timeout_minutes: 120
  nudge_cooldown_seconds: 600
ship_state_snapshot:
```
REPLACE:
```
  min_time_minutes: 60
  timeout_minutes: 120
ship_state_snapshot:
```

**P-C11 (`src/probos/events.py`).** SEARCH:
```
    SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"  # AD-683
    BOOT_CAMP_PHASE_ADVANCE = "boot_camp_phase_advance"
    BOOT_CAMP_GRADUATION = "boot_camp_graduation"
```
REPLACE:
```
    SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"  # AD-683
    BOOT_CAMP_GRADUATION = "boot_camp_graduation"
```

**P-C12 (`src/probos/event_persistence.py`; applies after P-T9).** SEARCH:
```
    "BOOT_CAMP_GRADUATION",
    "BOOT_CAMP_PHASE_ADVANCE",
    "BOOT_CAMP_TIMEOUT",
```
REPLACE:
```
    "BOOT_CAMP_GRADUATION",
    "BOOT_CAMP_TIMEOUT",
```

**P-C13 (`src/probos/cognitive/cognitive_agent.py`).** SEARCH:
```
            # AD-683: Cold-start ship state snapshot (boot-camp DM path only).
            if observation.get("_boot_camp_active") and self._runtime is not None:
                _bc = getattr(self._runtime, "boot_camp", None)
                _snap = getattr(_bc, "ship_state_snapshot", None) if _bc else None
                if _snap is not None:
                    try:
                        _snapshot_text = _snap.render_text()
                    except Exception:
                        logger.debug(
                            "AD-683: ship_state_snapshot.render_text failed; "
                            "skipping injection",
                            exc_info=True,
                        )
                        _snapshot_text = ""
                    if _snapshot_text:
                        _emit("boot_snapshot", [
                            "--- Ship State Snapshot ---",
                            _snapshot_text,
                            "---",
                            "",
                        ])
```
REPLACE:
```
            # AD-683: Cold-start ship state snapshot (DM path). AD-1270 (#1324): keyed on AD-638
            # enrolment, read through the coordinator, not on the observation's _boot_camp_active:
            # only a chain phase sets that (_refresh_boot_camp_relaxation, while relax_quality_gates
            # is on), and a chain's fall-through to this call carried its last answer here.
            _bc = getattr(self._runtime, "boot_camp", None) if self._runtime is not None else None
            _snapshot_text = _bc.orientation_snapshot_text(self.id) if _bc is not None else ""
            # A non-str answer (a test double's runtime) would break the join below: add nothing.
            if isinstance(_snapshot_text, str) and _snapshot_text:
                _emit("boot_snapshot", [
                    "--- Ship State Snapshot (captured when boot camp began) ---",
                    _snapshot_text,
                    "---",
                    "",
                ])
```

**P-C14 (`src/probos/startup/finalize.py`).** SEARCH:
```
        logger.info("AD-683: Ship State Snapshot v1 wired during finalization")
        # BF-261: Late-bind into BootCampCoordinator (created at Phase 7, before finalize)
        _bc = getattr(runtime, "boot_camp", None)
        if _bc is not None and getattr(_bc, "_ship_state_builder", None) is None:
            _bc._ship_state_builder = runtime.ship_state_snapshot
```
REPLACE:
```
        logger.info("AD-683: Ship State Snapshot v1 wired during finalization")
        # BF-261 / AD-1270 (#1324): late-bind into BootCampCoordinator (created at Phase 7, before
        # finalize) through its public setter, before the activation below captures the snapshot.
        _late_bind_boot_camp_snapshot(runtime=runtime)
```

**P-C33 (`src/probos/startup/finalize.py`; 4b-R13, the late-bind helper above `_is_new_crew_start`).** SEARCH:
```
    return True


async def _is_new_crew_start(runtime: Any) -> bool:
```
REPLACE:
```
    return True


def _late_bind_boot_camp_snapshot(*, runtime: Any) -> bool:
    """BF-261 / AD-1270 (#1324): hand the AD-683 builder to the boot-camp coordinator.

    Phase 7 builds the coordinator before ``runtime.ship_state_snapshot`` exists, so
    finalization binds the builder here, before ``_activate_boot_camp_on_cold_start``
    captures the snapshot. Through the public setter: a builder injected at construction
    is kept. True when the builder was bound.
    """
    coordinator = getattr(runtime, "boot_camp", None)
    if coordinator is None:
        return False
    return coordinator.bind_ship_state_builder(getattr(runtime, "ship_state_snapshot", None))


async def _is_new_crew_start(runtime: Any) -> bool:
```

**P-C15 (`src/probos/runtime.py`).** SEARCH:
```
        # AD-638: Boot camp coordinator (late-bound, needs ward_room + trust + episodic)
        if (
            self.config.boot_camp.enabled
            and self.ward_room
            and self.trust_network
            and getattr(self, 'episodic_memory', None)
        ):
            try:
                self.boot_camp = BootCampCoordinator(
                    config=self.config.boot_camp,
                    ward_room=self.ward_room,
                    trust_service=self.trust_network,
```
REPLACE:
```
        # AD-638: Boot camp coordinator (late-bound; needs trust, episodic memory and the Ward Room,
        # whose posts and DMs it counts toward graduation. AD-1270: it no longer takes the Ward Room.)
        if (
            self.config.boot_camp.enabled
            and self.ward_room
            and self.trust_network
            and getattr(self, 'episodic_memory', None)
        ):
            try:
                self.boot_camp = BootCampCoordinator(
                    config=self.config.boot_camp,
                    trust_service=self.trust_network,
```

### 7.4 M2: updated tests

**P-C16 (`tests/test_ad638_boot_camp.py`).** SEARCH:
```
import time
from dataclasses import dataclass
from typing import Any
```
REPLACE:
```
import time
from typing import Any
```
and SEARCH:
```
    AgentBootCampState,
    BootCampCoordinator,
    _DEPARTMENT_CHIEFS,
)
```
REPLACE:
```
    AgentBootCampState,
    BootCampCoordinator,
)
```

**P-C17 (same file).** SEARCH (from the `@dataclass` above `class FakeChannel:` through the `_make_trust` definition line):
```
@dataclass
class FakeChannel:
    id: str = "ch-001"
    channel_type: str = "ship"
    department: str = ""


@dataclass
class FakeThread:
    id: str = "thread-001"


@dataclass
class FakeDMChannel:
    id: str = "dm-001"


@dataclass
class FakePost:
    id: str = "post-001"


def _make_ward_room() -> MagicMock:
    wr = AsyncMock()
    wr.get_or_create_dm_channel = AsyncMock(return_value=FakeDMChannel())
    wr.create_thread = AsyncMock(return_value=FakeThread())
    wr.create_post = AsyncMock(return_value=FakePost())
    wr.list_channels = AsyncMock(return_value=[FakeChannel()])
    return wr


def _make_trust() -> MagicMock:
```
REPLACE:
```
def _make_trust() -> MagicMock:
```

**P-C18 (same file).** SEARCH:
```
        "timeout_minutes": 120,
        "nudge_cooldown_seconds": 0,  # 0 for tests — no cooldown
    }
```
REPLACE:
```
        "timeout_minutes": 120,
    }
```
and SEARCH:
```
        config=overrides.pop("config", _make_config()),
        ward_room=overrides.pop("ward_room", _make_ward_room()),
        trust_service=overrides.pop("trust_service", _make_trust()),
```
REPLACE:
```
        config=overrides.pop("config", _make_config()),
        trust_service=overrides.pop("trust_service", _make_trust()),
```

**P-C19 (same file).** Delete the TestPhase2 and TestPhase3 sections. SEARCH:
```
# ---------------------------------------------------------------------------
# Test 3: Phase 2 introduction DMs
# ---------------------------------------------------------------------------

class TestPhase2:
    @pytest.mark.asyncio
    async def test_introduction_dms_sent(self):
        wr = _make_ward_room()
        coord = _make_coordinator(ward_room=wr)
        await coord.activate(_CREW)
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Should have created DM channels and threads
        assert wr.get_or_create_dm_channel.call_count >= len(_CREW)
        assert wr.create_thread.call_count >= len(_CREW)

    @pytest.mark.asyncio
    async def test_phase_advance_event(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Activation + phase advances
        phase_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_PHASE_ADVANCE
        ]
        assert len(phase_events) == 3  # One per agent


# ---------------------------------------------------------------------------
# Test 4: Phase 3 observation thread
# ---------------------------------------------------------------------------

class TestPhase3:
    @pytest.mark.asyncio
    async def test_observation_thread_created(self):
        wr = _make_ward_room()
        coord = _make_coordinator(ward_room=wr)
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        # Should have created the observation thread on All Hands
        # Plus notebook prompt DMs for each agent
        assert wr.create_thread.call_count >= 1 + len(_CREW)

    @pytest.mark.asyncio
    async def test_phase_3_advance_events(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        phase_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_PHASE_ADVANCE
        ]
        assert len(phase_events) == 3


# ---------------------------------------------------------------------------
# Test 5-6: Graduation criteria
# ---------------------------------------------------------------------------
```
REPLACE:
```
# ---------------------------------------------------------------------------
# Test 5-6: Graduation criteria
# ---------------------------------------------------------------------------
```
and SEARCH:
```
# ---------------------------------------------------------------------------
# Test 11: Nudge cooldown
# ---------------------------------------------------------------------------

class TestNudgeCooldown:
    @pytest.mark.asyncio
    async def test_nudge_cooldown_blocks_second_nudge(self):
        """Test 11: Second nudge within cooldown → skipped."""
        config = _make_config(nudge_cooldown_seconds=3600)  # 1 hour cooldown
        wr = _make_ward_room()
        coord = _make_coordinator(config=config, ward_room=wr)
        await coord.activate(_CREW)

        # First run sends nudges
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        first_count = wr.create_thread.call_count

        # Second run — should be blocked by cooldown
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        assert wr.create_thread.call_count == first_count  # No new calls


# ---------------------------------------------------------------------------
# Test 12-13: Post and DM tracking
# ---------------------------------------------------------------------------
```
REPLACE:
```
# ---------------------------------------------------------------------------
# Test 12-13: Post and DM tracking
# ---------------------------------------------------------------------------
```

**P-C20 (same file).** SEARCH:
```
        """Test 14: All 4 event types emitted at correct lifecycle points."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Activation
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        # Phase advance
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Graduation
```
REPLACE:
```
        """Test 14: the three lifecycle event types are emitted at their points.

        AD-1270 (#1324) slice 4c deleted phases 2 and 3 and BOOT_CAMP_PHASE_ADVANCE with them.
        """
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Activation
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        # Graduation
```
and SEARCH:
```
        assert EventType.BOOT_CAMP_ACTIVATED in event_types
        assert EventType.BOOT_CAMP_PHASE_ADVANCE in event_types
```
REPLACE:
```
        assert EventType.BOOT_CAMP_ACTIVATED in event_types
```
and SEARCH:
```
        """Test 19: cold start → enrollment → phase 2 → phase 3 → graduation → active duty."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Cold start → activation
        await coord.activate(_CREW)
        assert coord.is_active

        # Phase 2
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).phase >= 2

        # Phase 3
        await coord.run_phase_3_observation("counselor-id", "Echo")
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).phase >= 3

        # Simulate activity for all agents
```
REPLACE:
```
        """Test 19: cold start → enrollment → graduation → active duty (AD-1270 slice 4c: no phases 2 and 3)."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Cold start → activation
        await coord.activate(_CREW)
        assert coord.is_active
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).phase == 1

        # Simulate activity for all agents
```
and SEARCH:
```
    @pytest.mark.asyncio
    async def test_observation_thread_shared(self):
        """Observation thread is reused across calls."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        thread_id_1 = coord._observation_thread_id
        # Reset phases so they can advance again
        for state in coord._agents.values():
            state.phase = 2
        await coord.run_phase_3_observation("counselor-id", "Echo")
        # Thread ID should be reused
        assert coord._observation_thread_id == thread_id_1

    @pytest.mark.asyncio
    async def test_emit_event_failure_safe(self):
```
REPLACE:
```
    @pytest.mark.asyncio
    async def test_emit_event_failure_safe(self):
```

**P-C21 (`tests/test_ad1270_boot_camp_trust.py`; re-anchor after 4b).** SEARCH:
```
    settings = {"min_time_minutes": 0, "nudge_cooldown_seconds": 0, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        ward_room=SimpleNamespace(),
        trust_service=trust,
```
REPLACE:
```
    settings = {"min_time_minutes": 0, **config}  # AD-1270 slice 4c: no nudge cooldown, no ward room
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        trust_service=trust,
```

**P-C22 (`tests/test_ad1270_boot_camp_lifecycle.py`; re-anchor after 4b).** SEARCH:
```
    events: list | None = None,
    ward_room: object | None = None,
    **config: object,
) -> BootCampCoordinator:
    settings = {"min_time_minutes": 0, "nudge_cooldown_seconds": 0, "timeout_minutes": 120, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        ward_room=ward_room if ward_room is not None else SimpleNamespace(),
        trust_service=trust,
```
REPLACE:
```
    events: list | None = None,
    **config: object,
) -> BootCampCoordinator:
    # AD-1270 (#1324) slice 4c: the coordinator has no nudge cooldown and no ward-room dependency.
    settings = {"min_time_minutes": 0, "timeout_minutes": 120, **config}
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(**settings),
        trust_service=trust,
```
and SEARCH:
```
    coord = _coordinator(trust, clock, events=events, ward_room=ws, min_time_minutes=60)
```
REPLACE:
```
    coord = _coordinator(trust, clock, events=events, min_time_minutes=60)
```

**P-C23.** None (kept for numbering).

**P-C24 (`tests/test_ad640_tiered_trust.py`).** SEARCH:
```
            config=BootCampConfig(),
            ward_room=MagicMock(),
            trust_service=mock_trust,
```
REPLACE:
```
            config=BootCampConfig(),
            trust_service=mock_trust,
```
and SEARCH:
```
        mock_ward_room = AsyncMock()
        mock_ward_room.get_or_create_dm_channel = AsyncMock(return_value=MagicMock(id="dm-1"))
        mock_ward_room.create_thread = AsyncMock(return_value=MagicMock(id="t-1"))
        mock_ward_room.create_post = AsyncMock(return_value=MagicMock(id="p-1"))

        coordinator = BootCampCoordinator(
            config=BootCampConfig(),
            ward_room=mock_ward_room,
            trust_service=mock_trust,
```
REPLACE:
```
        coordinator = BootCampCoordinator(
            config=BootCampConfig(),
            trust_service=mock_trust,
```

**P-C25 (`tests/test_ad683_ship_state_snapshot.py`).** SEARCH:
```
    ward_room = AsyncMock()
    trust_service = MagicMock()
```
REPLACE:
```
    trust_service = MagicMock()
```
and SEARCH:
```
        config=BootCampConfig(),
        ward_room=ward_room,
        trust_service=trust_service,
```
REPLACE:
```
        config=BootCampConfig(),
        trust_service=trust_service,
```
and SEARCH:
```
        config=BootCampConfig(),
        ward_room=AsyncMock(),
        trust_service=MagicMock(),
```
REPLACE:
```
        config=BootCampConfig(),
        trust_service=MagicMock(),
```

**P-C26 (`tests/test_ad1270e2g_crew_models.py`).** SEARCH:
```
                          'min_time_minutes': 60,
                          'timeout_minutes': 120,
                          'nudge_cooldown_seconds': 600,
```
REPLACE:
```
                          'min_time_minutes': 60,
                          'timeout_minutes': 120,
                          # AD-1270 (#1324) slice 4c removed nudge_cooldown_seconds (600) with AD-638's phases 2 and 3.
```
and in `tests/test_ad1270e1_config_facade.py` (after P-T16), SEARCH:
```
    assert counts["field_definitions"] == 1879  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c removes boot_camp.nudge_cooldown_seconds with AD-638's phases 2 and 3 (1879 -> 1878).
    assert counts["field_definitions"] == 1878  # AD-1206 intentionally adds github_repository.
```
**P-C27 (`tests/test_ad1270_boot_camp_trust.py`; 4b-R14, after P-C21).** SEARCH:
```
def _executes_a_chain(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "_sub_task_executor"
        for call in ast.walk(node)
    )


def _step_kinds(node: ast.AST) -> set[str]:
    return {
        keyword.value.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "SubTaskSpec"
        for keyword in call.keywords
        if keyword.arg == "sub_task_type" and isinstance(keyword.value, ast.Attribute)
    }


def test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment() -> None:
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods = {node.name: node for node in functions}

    assert {node.name for node in functions if _executes_a_chain(node)} == _GATING_PHASES | _LOOKUP_PHASES
    for name in _GATING_PHASES:
        assert "_refresh_boot_camp_relaxation" in _attribute_calls(methods[name]), name
    for name in _LOOKUP_PHASES:
        assert _step_kinds(methods[name]) == {"QUERY"}, name
    assert "relaxes_quality_gates" in _attribute_calls(methods["_refresh_boot_camp_relaxation"])
    assert "is_enrolled" not in _attribute_calls(tree)
```
REPLACE:
```
def _own_nodes(node: ast.AST) -> list[ast.AST]:
    """4b-R14 (AD-1270 slice 4c): A nested function or class is not walked into."""
    found: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        found.append(child)
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(child))
    return found


def _definitions(node: ast.AST, prefix: str = "") -> list[tuple[str, ast.AST]]:
    """4b-R14: every function in the file under its qualified name (``CognitiveAgent.method``,
    ``outer.inner``), in source order; a repeated name stays repeated."""
    found: list[tuple[str, ast.AST]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{child.name}"
            if not isinstance(child, ast.ClassDef):
                found.append((name, child))
            found.extend(_definitions(child, f"{name}."))
        else:
            found.extend(_definitions(child, prefix))
    return found


def _one(definitions: list[tuple[str, ast.AST]], qualname: str) -> ast.AST:
    matches = [node for name, node in definitions if name == qualname]
    assert len(matches) == 1, (qualname, len(matches))
    return matches[0]


def _own_attribute_calls(node: ast.AST) -> list[str]:
    return [
        call.func.attr
        for call in _own_nodes(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]


def _executes_a_chain(node: ast.AST) -> bool:
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and isinstance(call.func.value, ast.Attribute)
        and call.func.value.attr == "_sub_task_executor"
        for call in _own_nodes(node)
    )


def _step_kinds(node: ast.AST) -> set[str]:
    return {
        keyword.value.attr
        for call in _own_nodes(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "SubTaskSpec"
        for keyword in call.keywords
        if keyword.arg == "sub_task_type" and isinstance(keyword.value, ast.Attribute)
    }


def test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment() -> None:
    """A2's census, hardened by slice 4c (4b-R14): methods are keyed by qualified name, so a
    same-named method in another class is classified on its own, and a nested definition's calls
    are not credited to the method around it."""
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    definitions = _definitions(tree)
    gating = sorted(f"CognitiveAgent.{name}" for name in _GATING_PHASES)
    lookups = sorted(f"CognitiveAgent.{name}" for name in _LOOKUP_PHASES)

    assert sorted(name for name, node in definitions if _executes_a_chain(node)) == sorted(gating + lookups)
    for name in gating:
        assert "_refresh_boot_camp_relaxation" in _own_attribute_calls(_one(definitions, name)), name
    for name in lookups:
        assert _step_kinds(_one(definitions, name)) == {"QUERY"}, name
    producer = _one(definitions, "CognitiveAgent._refresh_boot_camp_relaxation")
    assert "relaxes_quality_gates" in _own_attribute_calls(producer)
    assert "is_enrolled" not in _attribute_calls(tree)
```

**P-C28 (`tests/test_ad1195_event_persistence_contract.py`; applies after P-T12).** SEARCH:
```
    """DECL-1: 396 members = 41 declared + 355 grandfathered, disjoint.

    AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED with its one producer (AD-509's
    tracker): 397 -> 396, 356 -> 355. The DECL-3 golden snapshot keeps its 356 names.
    """
```
REPLACE:
```
    """DECL-1: 395 members = 41 declared + 354 grandfathered, disjoint.

    AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED with its one producer (AD-509's
    tracker): 397 -> 396, 356 -> 355; and BOOT_CAMP_PHASE_ADVANCE with AD-638's phases 2 and 3:
    396 -> 395, 355 -> 354. The DECL-3 golden snapshot keeps its 356 names.
    """
```
and SEARCH:
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (396, 41, 355)
```
REPLACE:
```
    assert (len(names), len(declared), len(ep.GRANDFATHERED)) == (395, 41, 354)
```

**P-C29 (same file; applies after P-T13).** SEARCH:
```
    assert broken == []
    assert len(EventType) == 396  # AD-1270 (#1324) slice 4c: BOOT_CAMP_PHASE_ADVANCED deleted
```
REPLACE:
```
    assert broken == []
    assert len(EventType) == 395  # AD-1270 (#1324) slice 4c: BOOT_CAMP_PHASE_ADVANCED and BOOT_CAMP_PHASE_ADVANCE deleted
```

**P-C30 (`tests/test_ad1195_durable_event_seam.py`; applies after P-T14).** SEARCH:
```
    # AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED, an unrouted member: 397 -> 396.
    assert len(EventType) == 396
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 367)
```
REPLACE:
```
    # AD-1270 (#1324) slice 4c deleted BOOT_CAMP_PHASE_ADVANCED, an unrouted member: 397 -> 396;
    # and BOOT_CAMP_PHASE_ADVANCE (AD-638 phases 2 and 3), another: 396 -> 395.
    assert len(EventType) == 395
    assert len(ROUTED_VALUES) == 29
    assert (len(_ROUTED), len(_NOT_ROUTED)) == (29, 366)
```

**P-C31 (`tests/test_ad1270_boot_camp_repair_a1.py`).** SEARCH:
```
        config=BootCampConfig(
            relax_quality_gates=True, min_time_minutes=0, nudge_cooldown_seconds=0, timeout_minutes=120,
        ),
        ward_room=SimpleNamespace(),
        trust_service=trust if trust is not None else TrustNetwork(),
```
REPLACE:
```
        # AD-1270 (#1324) slice 4c: the coordinator has no nudge cooldown and no ward-room dependency.
        config=BootCampConfig(relax_quality_gates=True, min_time_minutes=0, timeout_minutes=120),
        trust_service=trust if trust is not None else TrustNetwork(),
```

### 7.5.N New file: `tests/test_ad1270_boot_camp_orientation.py` (21 cases)

```python
"""AD-1270 (#1324) slice 4c, M2: AD-638's uncalled phases 2 and 3 are deleted, and an enrolled
agent's Captain DM carries the AD-683 cold-start snapshot.

The snapshot was keyed on ``_boot_camp_active``, which only a chain phase sets (through
``_refresh_boot_camp_relaxation``, while ``relax_quality_gates`` is on), and ``direct_message``
is not a chain intent: with the flag off it reached no prompt, and with it on only after a chain
fell through to the single call, on that chain's last answer. It is keyed on enrolment now and
read through the coordinator, whose ``is_enrolled`` enforces the timeout. BF-261's late-bind goes
through a finalization helper and a public setter. Time comes from an injected clock, trust from
a real TrustNetwork.
"""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from probos.boot_camp import AgentBootCampState, BootCampCoordinator
from probos.config import BootCampConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.onboarding import ShipStateSnapshot
from probos.startup import finalize
from tests.fixtures.ad1028_golden._capture_golden import dm_observation, make_dm_agent

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "probos"
_START = 1_000_000.0
_HEADER = "--- Ship State Snapshot (captured when boot camp began) ---"
_SNAPSHOT = ShipStateSnapshot(captured_at=_START, vessel_name="Enterprise", active_crew_count=3)
_FAILED = "render_text failed"


class _Clock:
    def __init__(self, now: float = _START) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Episodes:
    async def count_for_agent(self, agent_id: str) -> int:
        return 10


class _Builder:
    """A ShipStateSnapshotBuilder stand-in: ``build`` is the one method the coordinator calls."""

    def __init__(self, snapshot: ShipStateSnapshot) -> None:
        self.snapshot = snapshot
        self.builds = 0

    async def build(self) -> ShipStateSnapshot:
        self.builds += 1
        return self.snapshot


class _Unrenderable:
    def render_text(self) -> str:
        raise RuntimeError("render broke")


class _NewCrewStats:
    """The one episodic-memory read ``finalize._is_new_crew_start`` makes: an empty store."""

    async def get_stats(self) -> dict:
        return {"total": 0}


def _coordinator(
    clock: _Clock, *, events: list | None = None, relax: bool = False, **injected: object,
) -> BootCampCoordinator:
    sink = events if events is not None else []
    return BootCampCoordinator(
        config=BootCampConfig(min_time_minutes=0, timeout_minutes=120, relax_quality_gates=relax),
        trust_service=TrustNetwork(),
        episodic_memory=_Episodes(),
        emit_event_fn=lambda event_type, data: sink.append((event_type, data)),
        clock=clock,
        **injected,
    )


def _agent(boot_camp: object):
    """The AD-1028 DM rig with test_ad1227's runtime shape, plus ``boot_camp``."""
    agent = make_dm_agent()
    agent._runtime = SimpleNamespace(
        config=SystemConfig(), attachment_store=None, artifact_store=None, episodic_memory=None,
        work_item_store=None, chat_thread_store=None, ontology=None, registry=None,
        boot_camp=boot_camp,
    )
    return agent


def _crew(agent_id: str) -> list[dict[str, str]]:
    return [{"agent_id": agent_id, "callsign": "Tester", "department": "science"}]


# --- R6: the snapshot reaches an enrolled agent's DM ---------------------------------------


async def test_an_enrolled_agents_captain_dm_carries_the_snapshot() -> None:
    agent = _agent(None)
    coord = _coordinator(_Clock())
    assert coord.bind_ship_state_builder(_Builder(_SNAPSHOT)) is True
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord
    assert coord.is_enrolled(agent.id) and not coord.relaxes_quality_gates(agent.id)  # premise: flag off

    msg = await agent._build_user_message(dm_observation())

    assert _HEADER in msg
    assert _SNAPSHOT.render_text() in msg


async def test_the_snapshot_block_is_the_only_difference() -> None:
    baseline = await _agent(None)._build_user_message(dm_observation())
    agent = _agent(None)
    coord = _coordinator(_Clock())
    coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord

    msg = await agent._build_user_message(dm_observation())

    assert msg == f"{_HEADER}\n{_SNAPSHOT.render_text()}\n---\n\n" + baseline


@pytest.mark.parametrize("case", ["not-enrolled", "graduated", "timed-out", "no-snapshot", "render-fails"])
async def test_no_block_unless_enrolled_with_a_snapshot(
    case: str, caplog: pytest.LogCaptureFixture,
) -> None:
    clock, agent = _Clock(), _agent(None)
    baseline = await agent._build_user_message(dm_observation())
    coord = _coordinator(clock)
    if case != "no-snapshot":
        coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew("someone-else" if case == "not-enrolled" else agent.id))
    if case == "graduated":
        await coord.force_graduate_all()
    if case == "timed-out":
        clock.now += 120 * 60
    if case == "render-fails":
        coord.ship_state_snapshot = _Unrenderable()
    if case in ("no-snapshot", "render-fails"):
        assert coord.is_enrolled(agent.id)  # premise: only the snapshot is missing or broken
    agent._runtime.boot_camp = coord

    with caplog.at_level(logging.DEBUG, logger="probos.boot_camp"):
        msg = await agent._build_user_message(dm_observation())

    assert msg == baseline
    failures = [r for r in caplog.records if _FAILED in r.getMessage()]
    assert len(failures) == (1 if case == "render-fails" else 0)


async def test_a_non_text_answer_from_the_runtime_adds_nothing() -> None:
    """A rig that gives an agent a MagicMock runtime gets a MagicMock back from any boot_camp
    call; the prompt builder must add nothing rather than fail the join. Passes on the base too."""
    baseline = await _agent(None)._build_user_message(dm_observation())
    agent = _agent(SimpleNamespace(orientation_snapshot_text=lambda agent_id: object()))

    assert await agent._build_user_message(dm_observation()) == baseline


def _stale_dm() -> dict:
    """A DM observation still carrying an earlier chain phase's relaxation answer."""
    return {**dm_observation(), "_boot_camp_active": True}


async def test_a_stale_relaxation_marker_adds_no_snapshot() -> None:
    """4b-R6, A2: the DM branch read the observation's ``_boot_camp_active``, so a chain that fell
    through to the single call carried its last phase's answer into the prompt. It reads the
    coordinator now: a marker left by a relaxation that has since ended adds nothing."""
    clock, agent = _Clock(), _agent(None)
    baseline = await agent._build_user_message(_stale_dm())
    coord = _coordinator(clock, relax=True)
    coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    assert coord.relaxes_quality_gates(agent.id)  # premise: the flag is on and the agent was relaxed
    clock.now += 120 * 60
    agent._runtime.boot_camp = coord

    msg = await agent._build_user_message(_stale_dm())

    assert msg == baseline
    assert "Ship State Snapshot" not in msg


@pytest.mark.parametrize("snapshot", [True, False], ids=["with-snapshot", "without-snapshot"])
async def test_the_dm_read_ends_an_expired_boot_camp(snapshot: bool) -> None:
    """``orientation_snapshot_text`` asks ``is_enrolled`` first, so past the timeout the DM build is
    an expiring reader like the others (4b's D4): it emits the one BOOT_CAMP_TIMEOUT and adds no
    block, with or without a captured snapshot."""
    clock, events, agent = _Clock(), [], _agent(None)
    baseline = await agent._build_user_message(dm_observation())
    coord = _coordinator(clock, events=events)
    if snapshot:
        coord.bind_ship_state_builder(_Builder(_SNAPSHOT))
    await coord.activate(_crew(agent.id))
    agent._runtime.boot_camp = coord
    clock.now += 120 * 60
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED]  # premise: no read yet

    msg = await agent._build_user_message(dm_observation())

    assert msg == baseline
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED, EventType.BOOT_CAMP_TIMEOUT]
    assert coord.get_state(agent.id).graduated


def test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder() -> None:
    """A guard in the manner of 4b's chain census: cognitive_agent.py reads enrolment once, through
    ``orientation_snapshot_text`` in ``_build_user_message``, and the prompt builder no longer reads
    the per-phase ``_boot_camp_active`` marker or the coordinator's snapshot attribute."""
    tree = ast.parse((_SRC / "cognitive" / "cognitive_agent.py").read_bytes())
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    builders = [n for n in functions if n.name == "_build_user_message"]
    assert len(builders) == 1  # premise
    constants = {n.value for n in ast.walk(builders[0]) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}

    assert sorted(n.name for n in functions if _call_lines(n, "orientation_snapshot_text")) == ["_build_user_message"]
    assert "boot_snapshot" in constants  # premise: the scan sees the bid's label
    assert "_boot_camp_active" not in constants
    assert "ship_state_snapshot" not in constants | attributes


# --- BF-261: the late-bind goes through the public setter -----------------------------------


async def test_bind_ship_state_builder_never_replaces_an_injected_builder() -> None:
    injected, late = _Builder(_SNAPSHOT), _Builder(_SNAPSHOT)
    owned = _coordinator(_Clock(), ship_state_builder=injected)
    assert owned.bind_ship_state_builder(late) is False
    await owned.activate(_crew("crew-1"))
    assert (injected.builds, late.builds) == (1, 0)

    unbound = _coordinator(_Clock())
    assert unbound.bind_ship_state_builder(None) is False
    assert unbound.bind_ship_state_builder(late) is True
    assert unbound.bind_ship_state_builder(injected) is False
    await unbound.activate(_crew("crew-1"))
    assert (injected.builds, late.builds) == (1, 1)
    assert unbound.ship_state_snapshot is _SNAPSHOT


def _call_lines(body: ast.AST, name: str) -> list[int]:
    return sorted(
        node.lineno for node in ast.walk(body)
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_finalization_late_binds_through_the_public_setter() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    body = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_late_bind_boot_camp_snapshot")
    private = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_ship_state_builder"]
    snapshots = _call_lines(body, "_wire_ship_state_snapshot")
    binds = _call_lines(body, "_late_bind_boot_camp_snapshot")
    activations = _call_lines(body, "_activate_boot_camp_on_cold_start")

    assert private == []
    assert (len(snapshots), len(binds), len(activations)) == (1, 1, 1)
    assert snapshots[0] < binds[0] < activations[0]
    assert len(_call_lines(helper, "bind_ship_state_builder")) == 1


async def test_finalization_late_bind_reaches_an_enrolled_agents_dm() -> None:
    """4b-R13: the AST case above pins where the late-bind sits; this one pins what it does.
    Finalization's helper binds the builder, the activation that follows captures through it, and
    the capture is what an enrolled agent's DM shows. Without the bind, nothing."""
    shown: dict[bool, bool] = {}
    for bound in (True, False):
        late, agent = _Builder(_SNAPSHOT), _agent(None)
        coord = _coordinator(_Clock())  # Phase 7 injected no builder: runtime.ship_state_snapshot did not exist
        member = SimpleNamespace(id=agent.id, agent_type="security_officer", callsign="Tester", department="security")
        runtime = SimpleNamespace(
            boot_camp=coord, ship_state_snapshot=late, ontology=None, is_cold_start=False,
            _lifecycle_state="first_boot", episodic_memory=_NewCrewStats(),
            registry=SimpleNamespace(all=lambda member=member: [member]),
        )
        if bound:
            assert finalize._late_bind_boot_camp_snapshot(runtime=runtime) is True
        assert await finalize._activate_boot_camp_on_cold_start(runtime=runtime) is True
        assert late.builds == (1 if bound else 0)
        agent._runtime.boot_camp = coord
        shown[bound] = _HEADER in await agent._build_user_message(dm_observation())

    assert shown == {True: True, False: False}
    no_coordinator = SimpleNamespace(boot_camp=None, ship_state_snapshot=_Builder(_SNAPSHOT))
    assert finalize._late_bind_boot_camp_snapshot(runtime=no_coordinator) is False


# --- R5: phases 2 and 3 are gone ------------------------------------------------------------


def test_the_counselor_voiced_phases_are_gone() -> None:
    for name in ("run_phase_2_introductions", "run_phase_3_observation", "_can_nudge", "_record_nudge"):
        assert not hasattr(BootCampCoordinator, name), name
    assert "trust_service" in inspect.signature(BootCampCoordinator).parameters  # premise
    assert "ward_room" not in inspect.signature(BootCampCoordinator).parameters
    assert "timeout_minutes" in BootCampConfig.model_fields  # premise
    assert "nudge_cooldown_seconds" not in BootCampConfig.model_fields
    fields = set(AgentBootCampState.__dataclass_fields__)
    assert {"ward_room_posts", "dm_conversations", "phase"} <= fields  # premise
    assert fields.isdisjoint({"introduced_to_chief", "cross_dept_contact", "shared_observation", "notebook_started"})


def test_the_phase_advance_event_type_is_gone() -> None:
    assert {"BOOT_CAMP_ACTIVATED", "BOOT_CAMP_GRADUATION", "BOOT_CAMP_TIMEOUT"} <= set(EventType.__members__)
    assert "BOOT_CAMP_PHASE_ADVANCE" not in EventType.__members__
    assert "boot_camp_phase_advance" not in {member.value for member in EventType}


async def test_a_lifecycle_goes_from_enrolled_to_graduated_with_no_phase_between() -> None:
    clock, events = _Clock(), []
    coord = _coordinator(clock, events=events)
    await coord.activate(_crew("crew-1"))
    assert coord.get_state("crew-1").phase == 1

    clock.now += 120 * 60

    assert not coord.is_enrolled("crew-1")
    assert coord.get_state("crew-1").phase == 4
    assert [event_type for event_type, _ in events] == [EventType.BOOT_CAMP_ACTIVATED, EventType.BOOT_CAMP_TIMEOUT]


def test_a_config_that_still_sets_nudge_cooldown_seconds_loads() -> None:
    cfg = SystemConfig.model_validate({"boot_camp": {"nudge_cooldown_seconds": 600, "timeout_minutes": 90}})

    assert cfg.boot_camp.timeout_minutes == 90  # the section was read
    assert "nudge_cooldown_seconds" not in cfg.boot_camp.model_dump()


def test_the_tracked_yaml_carries_no_nudge_key() -> None:
    boot_camp = yaml.safe_load((_REPO / "config" / "system.yaml").read_text(encoding="utf-8"))["boot_camp"]

    assert boot_camp["timeout_minutes"] == 120  # premise: this is the boot_camp section
    assert "nudge_cooldown_seconds" not in boot_camp


def test_every_boot_camp_field_is_described() -> None:
    """4b-R12: each BootCampConfig field carries a description, so its generated reference row is
    not blank, and the relaxation's says whose switch it is."""
    fields = BootCampConfig.model_fields
    assert list(fields) == [
        "enabled", "min_episodes", "min_ward_room_posts", "min_dm_conversations",
        "min_trust_score", "min_time_minutes", "timeout_minutes", "relax_quality_gates",
    ]  # premise: the field set after this slice
    assert [name for name, field in fields.items() if not (field.description or "").strip()] == []
    assert "Captain" in fields["relax_quality_gates"].description

    reference = (_REPO / "docs" / "development" / "config-reference.md").read_text(encoding="utf-8")
    section = reference.split("## `boot_camp`\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) == len(fields)
    assert [line for line in rows if line.rstrip().endswith("|  |")] == []
```

### 7.6 Generated and measured files (M1 and M2; no pairs)

- `config-facade-baseline.yaml`: `-P scripts/check_config_facade.py --update-baseline`. `config-reference.md`: `scripts/gen_config_reference.py`. The allowed diffs are in §4.
- `tests/fixtures/ad1152_agentic_off_golden.json` lines 15 (`observation_sha256`) and 17 (`default_config_sha256`): refresh by measurement, BF-926 Amendment A1's procedure.
  1. Run `test_default_off_matches_pinned_base -n 0`; copy the actual `default_config_sha256` from its assertion into line 17.
  2. Rerun; copy the actual observation sha from `:525` into line 15.
  3. Binding control:
     - the refreshed fixture passes the file's 3 golden cases;
     - `main`'s fixture fails those 3 only at `default_config_sha256`.
  4. Record both values in the commit message.
  - Do this in M1 and again in M2.

### 7.7 M3: `src/probos/holodeck/chamber.py`

**P-H1.** SEARCH:
```
                modules = self._curriculum_registry.list_by_phase("orientation")
                module_ids = [getattr(m, "id", "") for m in modules]
```
REPLACE:
```
                modules = self._curriculum_registry.list_by_phase("orientation")
                # AD-1270 (#1324): AD-507's CurriculumModule keys on module_id; ``id`` was always "".
                module_ids = [m.module_id for m in modules]
```

**P-H2 (`tests/test_ad486_birth_chamber.py`).** SEARCH:
```
        curriculum.list_by_phase.return_value = (
            SimpleNamespace(id="m1"), SimpleNamespace(id="m2"),
        )
```
REPLACE:
```
        # AD-1270 (#1324): fakes of AD-507's CurriculumModule, which keys on module_id.
        curriculum.list_by_phase.return_value = (
            SimpleNamespace(module_id="m1"), SimpleNamespace(module_id="m2"),
        )
```

#### 7.7.N New file: `tests/test_ad1270_chamber_module_ids.py` (2 cases)

```python
"""AD-1270 (#1324) slice 4c, M3: the birth chamber reports the orientation modules it delivers.

``holodeck/chamber.py`` read ``m.id`` from AD-507's ``CurriculumModule``, whose key is
``module_id``, so ``HOLODECK_PHASE_ENTERED.modules`` was a list of empty strings.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from probos.config import HolodeckBirthChamberConfig
from probos.crew_development import CoreKnowledgeCurriculumRegistry
from probos.events import EventType
from probos.holodeck import BirthChamber


class _Agent:
    id = "a1"
    agent_type = "engineer"


def _chamber(registry: Any) -> tuple[BirthChamber, list[tuple[Any, dict[str, Any]]]]:
    events: list[tuple[Any, dict[str, Any]]] = []
    chamber = BirthChamber(
        config=HolodeckBirthChamberConfig(enabled=True, auto_advance_enabled=False),
        emit_event_fn=lambda event_type, payload: events.append((event_type, dict(payload))),
    )
    chamber.set_curriculum_registry(registry)
    return chamber, events


def _module_events(events: list[tuple[Any, dict[str, Any]]]) -> list[list[str]]:
    return [p["modules"] for t, p in events if t == EventType.HOLODECK_PHASE_ENTERED and "modules" in p]


async def test_the_orientation_event_names_the_delivered_modules() -> None:
    registry = CoreKnowledgeCurriculumRegistry()
    expected = [m.module_id for m in registry.list_by_phase("orientation")]
    assert expected == ["identity_grounding", "chain_of_command", "ethics_boundaries"]  # premise
    chamber, events = _chamber(registry)

    await chamber.admit(_Agent())

    assert _module_events(events) == [expected]


async def test_a_malformed_module_still_marks_orientation_delivered() -> None:
    chamber, events = _chamber(SimpleNamespace(list_by_phase=lambda phase: (object(),)))

    record = await chamber.admit(_Agent())

    assert _module_events(events) == []
    assert record.gates_passed["curriculum_orientation_delivered"] is True
```

## 8. Tracking (M4's commit)

**Head constraint:** neither head has a lifecycle keyword in its first 120 characters. Verified by reading `gen_ad_ledger.py:126-139,176-184`.

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 4c -- the boot-camp tail: AD-509's phase tracker and AD-638's phases 2 and 3 are deleted, and enrolled crew see the AD-683 snapshot.** The AD-509 `BootCampPhaseTracker` was built at finalization and never fed, and its five phases were not AD-638's. It is deleted with its module, exports, wirer, `BootCampPhaseConfig`, `SystemConfig.boot_camp_phase`, the tracked `boot_camp_phase:` section, its tests and `EventType.BOOT_CAMP_PHASE_ADVANCED`. AD-638's phases 2 and 3 had no caller and posted, in the Counselor's name, text the Counselor never composed. They are deleted with `_DEPARTMENT_CHIEFS`, the nudge cooldown and `boot_camp.nudge_cooldown_seconds`, the observation-thread state, four unread state flags, the coordinator's `ward_room` parameter and `EventType.BOOT_CAMP_PHASE_ADVANCE`. A config that still carries either key loads; unknown keys are ignored. AD-683's cold-start snapshot reached no prompt with the relaxation off: it was keyed on `_boot_camp_active`, which only a chain phase sets, and its reader is on the `direct_message` path (with the relaxation on, it appeared only after a chain fell through to the single call, on that chain's last answer). It is now keyed on enrolment and read through the coordinator, so an enrolled agent's Captain DM opens with the snapshot, labelled as captured when boot camp began, and the read enforces the timeout like the coordinator's other reads. Slice 4b's "off, enrolment changes no agent's prompt" therefore no longer holds; `ship_state_snapshot.enabled` is the snapshot's switch. BF-261's late-bind is a finalization helper that calls `BootCampCoordinator.bind_ship_state_builder` instead of writing a private attribute, and a test shows activation capturing through it. Every `BootCampConfig` field now has a description, so its generated reference row is no longer blank, and slice 4b's chain-phase census classifies methods by qualified name. `HOLODECK_PHASE_ENTERED.modules` names the AD-507 modules the birth chamber delivers; it was a list of empty strings. BF-034's dead cold-start detector (#1324 register 4b-R10) is the next slice, 4d. The contract is `prompts/ad-1270-boot-camp-tail.md`.

```

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- the boot-camp tail: AD-509's tracker and AD-638's phases 2 and 3 deleted; AD-683's snapshot keyed on enrolment (2026-10-2X)

**Decision.** Delete the AD-509 phase tracker and AD-638's phases 2 and 3 with every surface they own: config, events, state, the coordinator's ward-room dependency and tests. Do not wire them. Delete both phase-advance event types rather than keep them reserved. They had no subscriber and no persisted row, and the durable reader resolves an unknown name to none. Key AD-683's snapshot on AD-638 enrolment, read through `BootCampCoordinator.orientation_snapshot_text`, under a header that says it was captured when boot camp began; that read asks `is_enrolled` first, so it enforces the timeout. Replace BF-261's private write with `bind_ship_state_builder`, called from one finalization helper, `_late_bind_boot_camp_snapshot`; a builder injected at construction is not replaced. Read `module_id` in the birth chamber. Describe every `BootCampConfig` field. Key slice 4b's chain-phase census by qualified name. Keep BF-034's detector repair on #1324 as slice 4d, with its own BF number and no new issue. **Why.** The tracker was built and never fed. Its phases were a second model for the same agents, and AD-486's chamber carries orientation. Phases 2 and 3 had no caller and would have spoken for the Counselor. The snapshot was dead because its key is set only by a chain phase, and the reader sits on the `direct_message` path; with the relaxation on, a chain's fall-through carried a stale answer into it. A frozen snapshot shown without its capture time invites a stale reading. A blank reference row hid what the relaxation weakens, and a bare-name census lets a same-named method elsewhere stand in for the one under test. **Effect.** Enrolment now changes an enrolled agent's Captain-DM prompt, by one labelled read-only block, until graduation or the timeout. Its switch is the existing `ship_state_snapshot.enabled`. This revises slice 4b's "with the relaxation off, enrolment is bookkeeping". **Captain.** Nothing is parked. He may restore phases 2 and 3, keep the event names, or keep the snapshot out of prompts. **Rejected.** Wiring the tracker (a second phase model). Keeping the event types as reserved values (members with no producer). A new flag for the snapshot (it has one). Keying the snapshot on the relaxation (the snapshot is context, not a gate). A new issue for BF-034 (the discovery budget is spent and #1324 owns it).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): tick the slice-4c item with the commits and the receipt.

## 9. What this does NOT change

- `sub_tasks/evaluate.py`, `sub_tasks/reflect.py`, `sub_task.py`, `journal.py`; the producer `_refresh_boot_camp_relaxation` and its three callers (a Grep of `src` for `_refresh_boot_camp_relaxation\(` finds its definition and three calls); AD-639.
- `relax_quality_gates`'s behaviour (it gains only a description), `relaxes_quality_gates`, the timeout, DM counting, `_activate_boot_camp_on_cold_start` and `_is_new_crew_start` (4b).
- The runtime guard `and self.ward_room` in `runtime.py`: the coordinator no longer takes the Ward Room but counts the posts and DMs made through it, so the guard stays and only its comment changes. `on_agent_post`'s `channel_type` parameter (4c-R3).
- The Ward Room or proactive (chain) prompts: no snapshot there (4c-R2).
- `priority4_cleanup.py` (AD-509e `PacingPolicy`; 4c-R1); `dormant-class-baseline.yaml` (checked, not regenerated); `architecture-baseline.yaml` (no row change).
- BF-034's detector and its readers (4b-R10, slice 4d); `ConnManager` enforcement (4b-R8); who may run `/conn` (4b-R11); slice 5.

## 10. Mutation rows (one campaign of record on the M3 tree, after an unmutated baseline of M1's to M3's focused lists passes; run on the Captain's Windows host)

**Amendment A2.** Every row is in `s6_census.py`'s grammar and runs as written. A1's table had 13 rows the tool could not apply. Each row keeps A1's intent:
- **T-1 and C-13 are single-site.** Re-inserting the member alone, or its GRANDFATHERED name alone, fails the import of `probos.events` (`events.py:532` calls `assert_complete`). So each half dies as a collection ERROR on a file, which no row can claim. Each row instead re-inserts the member in the `EventType` body and writes the name into `event_persistence.GRANDFATHERED` from there, through `_assert_persistence_complete.__globals__`. That is the runtime state of the two-file revert.
- **New anchors.** T-3, T-4 and C-12 insert by repeating a real anchor line. C-6 mutates the log line in `orientation_snapshot_text`'s `except`, because `return ""` occurs twice. C-15 turns the opener into `if False:`. C-19 turns the opener into a call that passes `Field` the default only.
- **Renames.** R14-1 is now Q-1 and R14-2 is now Q-2. Q-1's nested definition has its body line; Q-2 appends after the file's last line.
- **Killed-by cells** are re-derived from the new tests.

Q-1 and Q-2 discriminate the hardened census: before P-C27, both survive `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` (by reading). No row is equivalent. C-5 is killed only through the failure-log count of its case (the mutant's `None.render_text` is caught and logged). Run with `--tests` set to the union of M1's to M3's focused lists; M2's list includes `tests/test_ad1270_boot_camp_repair_a1.py`, which Q-1 needs.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| T-1 | M1 | `events.py` | `CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507` | `CURRICULUM_MODULE_QUERIED = "curriculum_module_queried"  # AD-507\n    BOOT_CAMP_PHASE_ADVANCED = "boot_camp_phase_advanced"\n    _assert_persistence_complete.__globals__["GRANDFATHERED"] = _assert_persistence_complete.__globals__["GRANDFATHERED"].union({"BOOT_CAMP_PHASE_ADVANCED"})` | `test_the_event_type_and_its_grandfathered_entry_are_gone`, `test_every_member_is_declared_or_grandfathered_never_both`, `test_every_member_keeps_str_equality_and_pickle_identity`, `test_route_premises_are_the_contract_counts` |
| T-2 | M1 | `config.py` | `# AD-1270 (#1324): boot_camp_phase (AD-509) was removed; a config that still sets it loads.` | `boot_camp_phase: dict = Field(default_factory=lambda: {"enabled": True})` | `test_the_config_field_and_model_are_gone`, `test_a_config_that_still_sets_boot_camp_phase_loads[True]`, `test_a_config_that_still_sets_boot_camp_phase_loads[False]` |
| T-3 | M1 | `config/system.yaml` | `discovery_learning:` (the top-level key after `crew_development:`) | `boot_camp_phase:\n  enabled: true\ndiscovery_learning:` | `test_the_tracked_yaml_carries_no_boot_camp_phase_key` |
| T-4 | M1 | `startup/finalize.py` | `logger.info("AD-507: Crew Development Framework v1 wired during finalization")` | `logger.info("AD-507: Crew Development Framework v1 wired during finalization")\n    _wire_boot_camp_tracker(runtime=runtime, config=config)` | `test_finalization_no_longer_wires_a_tracker` |
| T-5 | M1 | `crew_development/__init__.py` | `"CurriculumModule",` | `"CurriculumModule", "BootCampPhase",` | `test_the_package_no_longer_exports_the_tracker[BootCampPhase]`, `test_the_package_keeps_its_other_exports` |
| C-1 | M2 | `cognitive_agent.py` | `_snapshot_text = _bc.orientation_snapshot_text(self.id) if _bc is not None else ""` | `_snapshot_text = ""` | `test_an_enrolled_agents_captain_dm_carries_the_snapshot`, `test_the_snapshot_block_is_the_only_difference`, `test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder`, `test_finalization_late_bind_reaches_an_enrolled_agents_dm`, `test_the_dm_read_ends_an_expired_boot_camp[*-snapshot]` |
| C-2 | M2 | `cognitive_agent.py` | `if isinstance(_snapshot_text, str) and _snapshot_text:` | `if _snapshot_text:` | `test_a_non_text_answer_from_the_runtime_adds_nothing` |
| C-3 | M2 | `cognitive_agent.py` | `"--- Ship State Snapshot (captured when boot camp began) ---",` | `"--- Ship State Snapshot ---",` | `test_an_enrolled_agents_captain_dm_carries_the_snapshot`, `test_the_snapshot_block_is_the_only_difference`, `test_finalization_late_bind_reaches_an_enrolled_agents_dm` |
| C-4 | M2 | `boot_camp.py` | `if not self.is_enrolled(agent_id) or self.ship_state_snapshot is None:` | `if self.ship_state_snapshot is None:` | `test_no_block_unless_enrolled_with_a_snapshot[not-enrolled]`, `test_no_block_unless_enrolled_with_a_snapshot[graduated]`, `test_no_block_unless_enrolled_with_a_snapshot[timed-out]`, `test_the_dm_read_ends_an_expired_boot_camp[with-snapshot]`, `test_the_dm_read_ends_an_expired_boot_camp[without-snapshot]`, `test_a_stale_relaxation_marker_adds_no_snapshot` |
| C-5 | M2 | `boot_camp.py` | same | `if not self.is_enrolled(agent_id):` | `test_no_block_unless_enrolled_with_a_snapshot[no-snapshot]` |
| C-6 | M2 | `boot_camp.py` | `logger.debug("AD-683: ship_state_snapshot.render_text failed; no snapshot this turn", exc_info=True)` | `raise` | `test_no_block_unless_enrolled_with_a_snapshot[render-fails]` |
| C-7 | M2 | `boot_camp.py` | `if builder is None or self._ship_state_builder is not None:` | `if builder is None:` | `test_bind_ship_state_builder_never_replaces_an_injected_builder` |
| C-8 | M2 | `boot_camp.py` | same | `if self._ship_state_builder is not None:` | `test_bind_ship_state_builder_never_replaces_an_injected_builder` |
| C-9 | M2 | `boot_camp.py` | `self._ship_state_builder = builder` | `pass` | `test_bind_ship_state_builder_never_replaces_an_injected_builder`, `test_an_enrolled_agents_captain_dm_carries_the_snapshot`, `test_finalization_late_bind_reaches_an_enrolled_agents_dm` |
| C-10 | M2 | `startup/finalize.py` | `_late_bind_boot_camp_snapshot(runtime=runtime)` (in `finalize_startup`) | `pass` | `test_finalization_late_binds_through_the_public_setter` |
| C-11 | M2 | `config_models/crew.py` | `# AD-1270 (#1324): nudge_cooldown_seconds was removed with phases 2 and 3; a config that sets it loads.` | `nudge_cooldown_seconds: int = 600` | `test_the_counselor_voiced_phases_are_gone`, `test_a_config_that_still_sets_nudge_cooldown_seconds_loads`, `test_every_boot_camp_field_is_described` |
| C-12 | M2 | `config/system.yaml` | `timeout_minutes: 120` (the `boot_camp` section's last key) | `timeout_minutes: 120\n  nudge_cooldown_seconds: 600` | `test_the_tracked_yaml_carries_no_nudge_key` |
| C-13 | M2 | `events.py` | `SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"  # AD-683` | `SHIP_STATE_SNAPSHOT_CAPTURED = "ship_state_snapshot_captured"  # AD-683\n    BOOT_CAMP_PHASE_ADVANCE = "boot_camp_phase_advance"\n    _assert_persistence_complete.__globals__["GRANDFATHERED"] = _assert_persistence_complete.__globals__["GRANDFATHERED"].union({"BOOT_CAMP_PHASE_ADVANCE"})` | `test_the_phase_advance_event_type_is_gone`, `test_every_member_is_declared_or_grandfathered_never_both`, `test_every_member_keeps_str_equality_and_pickle_identity`, `test_route_premises_are_the_contract_counts` |
| C-14 | M2 | `startup/finalize.py` | `return coordinator.bind_ship_state_builder(getattr(runtime, "ship_state_snapshot", None))` | `return True` | `test_finalization_late_bind_reaches_an_enrolled_agents_dm`, `test_finalization_late_binds_through_the_public_setter` |
| C-15 | M2 | `startup/finalize.py` | `if coordinator is None:` (in `_late_bind_boot_camp_snapshot`) | `if False:` | `test_finalization_late_bind_reaches_an_enrolled_agents_dm` |
| C-16 | M2 | `boot_camp.py` | `if not self.is_enrolled(agent_id) or self.ship_state_snapshot is None:` | `if self.ship_state_snapshot is None or not self.is_enrolled(agent_id):` | `test_the_dm_read_ends_an_expired_boot_camp[without-snapshot]` |
| C-17 | M2 | `cognitive_agent.py` | `_snapshot_text = _bc.orientation_snapshot_text(self.id) if _bc is not None else ""` | `_snapshot_text = (_bc.orientation_snapshot_text(self.id) or (_bc.ship_state_snapshot.render_text() if observation.get("_boot_camp_active") and _bc.ship_state_snapshot is not None else "")) if _bc is not None else ""` | `test_a_stale_relaxation_marker_adds_no_snapshot`, `test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder` |
| C-18 | M2 | `cognitive_agent.py` | `if isinstance(_snapshot_text, str) and _snapshot_text:` | `if isinstance(_snapshot_text, str) and _snapshot_text and observation.get("_boot_camp_active"):` | `test_an_enrolled_agents_captain_dm_carries_the_snapshot`, `test_the_snapshot_block_is_the_only_difference`, `test_the_dm_snapshot_is_the_one_enrolment_read_in_the_prompt_builder`, `test_finalization_late_bind_reaches_an_enrolled_agents_dm` |
| C-19 | M2 | `config_models/crew.py` | `relax_quality_gates: bool = Field(` | `relax_quality_gates: bool = (lambda **kw: Field(default=kw["default"]))(` | `test_every_boot_camp_field_is_described` |
| Q-1 | M2 | `cognitive_agent.py` | `self._refresh_boot_camp_relaxation(observation)  # AD-1270: phase 2a's answer may have expired` (in `_re_reflect_with_feedback`) | `def _never() -> None:\n                self._refresh_boot_camp_relaxation(observation)` | `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment`, `test_the_feedback_reflection_asks_again_after_phase_two[expired-before-feedback]` |
| Q-2 | M2 | `cognitive_agent.py` | `return stats` (the file's last line, in `cache_stats`) | `return stats\n\n\nclass _CensusProbe:\n    async def _re_reflect_with_feedback(self, observation):\n        self._refresh_boot_camp_relaxation(observation)\n        return await self._sub_task_executor.execute(None, observation)` | `test_every_gating_chain_phase_asks_for_the_relaxation_not_enrolment` |
| H-1 | M3 | `holodeck/chamber.py` | `module_ids = [m.module_id for m in modules]` | `module_ids = [getattr(m, "id", "") for m in modules]` | `test_the_orientation_event_names_the_delivered_modules`, `test_a_malformed_module_still_marks_orientation_delivered` |

## 11. Verified Against Codebase (2026-10-28, on `77f8fd67`)

```
Grep BootCampPhaseTracker|boot_camp_tracker|BootCampPhaseConfig|boot_camp_phase|BOOT_CAMP_PHASE (src tests scripts ui/src config docs)   P1-P3 sites
Read crew_development/__init__.py (whole); crew_development/boot_camp.py:1-30; config.py:3690-3729, 4118-4135, 4150-4164
Read finalize.py:883-932, 4165-4214; runtime.py:3324-3341; boot_camp.py (whole, 545 lines; 19 methods)
Read cognitive_agent.py:3780-3849, 5674-5705, 6040-6069, 10425-10519; Grep _CHAIN_ELIGIBLE_INTENTS (:348-351)
Read onboarding/ship_state_snapshot.py:56-125; holodeck/chamber.py:77-110,148-167,270-304,358-364; curriculum.py:155-209
Read events.py:400-411, 486-497; event_persistence.py:112-154; durable_events.py:555-572; cluster_monitor.py:100-120
Read tests: test_ad638 (whole); test_ad640:200-256; test_ad683:225-290; test_ad1195 contract:35-73,440-509,575-588; seam:316-329
Read test_ad1270e1:1540-1565; e2g:130-149; e2i:140-199,458-532; test_ad1152:200-223,320-325,500-525; bf926:1-170
Read test_ad1227:164-188,630-671; ad1028 _capture_golden.py:1-80; test_ad486:45-83,300-369; 4b test helpers (trust:40-57, lifecycle:1-75,262-291)
Read check_architecture_principles.py:168,188,545-584,620-641,900-939; architecture-baseline.yaml:323-329
Read config-profiles.yaml:14-29; gen_ad_ledger.py:113-184; open-ads-report.md:268
git diff -U2 7c85ebaf 77f8fd67 -- boot_camp.py finalize.py cognitive_agent.py crew.py system.yaml   (4b's lines, for re-anchoring)
git show 6f94608b (BF-926 Amendment A1: AD-1152 golden lines 15 and 17 refreshed by measurement)
```

## Absence Verified (2026-10-28)

```
CLAIM: nothing reads runtime.boot_camp_tracker or calls the tracker
RUN:   Grep boot_camp_tracker (src); Grep '\.advance_phase\(|\.get_or_create\(|\.all_records\(|\.is_completed\(' src
FOUND: finalize.py:922 (the write); crew_development/boot_camp.py:86 (the tracker's self-call); every other get_or_create is on another class
HOLDS: yes

CLAIM: _boot_camp_active is set only on the chain path; the snapshot reader is only on the direct_message path
RUN:   Grep '_boot_camp_active["\']\]\s*=|_boot_camp_active=' src; Grep '_build_user_message\(' cognitive_agent.py
FOUND: cognitive_agent.py:6056 (_execute_sub_task_chain), :6245 (_execute_chain_with_intent_routing); one caller :3985 (_decide_via_llm)
HOLDS: yes -- reachable only through an external chain's fallback on a direct_message (:3786-3810)

CLAIM: run_phase_2/3, the nudge helpers and the observation state have no production caller or reader
RUN:   Grep 'run_phase_2_introductions|run_phase_3_observation|_DEPARTMENT_CHIEFS|nudge_cooldown|_observation_thread_id|shared_observation|_can_nudge|_record_nudge|introduced_to_chief|cross_dept_contact|notebook_started'
FOUND: boot_camp.py definitions; crew.py:25; system.yaml:2117; tests; cognitive_agent.py:2708 (AD-536's own _DEPARTMENT_CHIEFS)
HOLDS: yes

CLAIM: nothing subscribes to either phase-advance event; nothing rebuilds an event type from a stored string without a guard
RUN:   Grep BOOT_CAMP_PHASE|boot_camp_phase_advance (src, ui/src); Grep 'EventType\(' src
FOUND: emitters, declarations, GRANDFATHERED only; EventType( at cluster_monitor.py:113 (local, try) and durable_events.py:569 (ValueError -> None)
HOLDS: yes

CLAIM: no test pins BF-261's private write, the AD-509 log line, the snapshot header or the boot_snapshot label
RUN:   Grep 'BF-261|_ship_state_builder|bf261' tests; Grep 'AD-509|Boot Camp Phase' tests scripts; Grep 'Ship State Snapshot ---|boot_snapshot' src tests
FOUND: none (tests); test_ad509 only; cognitive_agent.py:10497-10498 only
HOLDS: yes

CLAIM: SystemConfig and BootCampConfig ignore unknown keys
RUN:   Grep 'model_config|extra=' config.py; Read crew.py:1-45
FOUND: none; none (config_models/operations.py's forbid models are other classes)
HOLDS: yes

CLAIM: nothing outside boot_camp.py reads coordinator state or BootCampCoordinator is built elsewhere
RUN:   Grep 'boot_camp\.(get_state|_agents|is_active|ship_state_snapshot)|boot_camp_state' src ui/src; Grep 'BootCampCoordinator\(' src tests
FOUND: none; runtime.py:3330 + six test sites (all keyword)
HOLDS: yes
```

## Verified Against Codebase (Amendment A1, 2026-10-28, on `8f0454b5`)

```
git diff 31066065 8f0454b5 -- boot_camp.py finalize.py crew.py dreaming.py cognitive_agent.py   (R1, R2 under 4c's pairs)
Read boot_camp.py:1-252, 420-547; Grep '^    (async )?def ' boot_camp.py (19 methods with is_active)
Read cognitive_agent.py:10440-10514 (P-C13's block, unchanged); Grep _boot_camp_active src
Grep -B4 '_sub_task_executor\.execute\(' cognitive_agent.py: 5752, 5815, 6113, 6358, 6552, each in its method's own try
Grep '^        +(async )?def ' cognitive_agent.py: nested defs 4906-5613, 6674, 10454, 10801; none holds a chain call
Read finalize.py:876-955 (_is_new_crew_start :883, activation :904, tracker wirer :933); tracker call :4201; late-bind :4219-4224
Read runtime.py:3320-3341; crew.py:1-50; crew_utils.py:60-77 (is_crew_agent keys on agent_type)
Read tests: test_ad638:1-220, 425-456; lifecycle:1-85, 255-424; trust:1-60, 200-283; repair_a1:1-75; e2g:125-154, 345-437
Grep 'BootCampCoordinator\(' tests (8 sites); Grep '\.boot_camp\s*=|boot_camp=' tests
Read config-reference.md:2660-2691; check_config_facade.py:925-1012; gen_config_reference.py:164-167
Grep model_json_schema (tests, scripts, src); Grep 'model_fields|ast\.' check_config_profiles.py (:161-167 reads model_fields)
Read .github/copilot-instructions.md:92; .github/agents/orchestrator.agent.md:73-85
```

## Absence Verified (Amendment A1, 2026-10-28)

```
CLAIM: after P-C13 nothing in the DM branch reads _boot_camp_active; every other reader runs inside a chain phase after the producer
RUN:   Grep '_boot_camp_active|boot_camp_active' src
FOUND: cognitive_agent.py:6012-6026 (the producer and AD-639), :10478 (removed by P-C13); sub_task.py:722; evaluate.py:532; reflect.py:449; journal.py and chain_trace.py (the journal column)
HOLDS: yes (supersedes the second claim of the first Absence block: since R2 the only writer is :6023)

CLAIM: nothing outside boot_camp.py reads the deleted state, the phase values 2 and 3, or builds AgentBootCampState
RUN:   Grep 'run_phase_2_introductions|run_phase_3_observation|_DEPARTMENT_CHIEFS|nudge_cooldown|_nudge_cooldowns|_observation_thread_id|shared_observation|_can_nudge|_record_nudge|introduced_to_chief|cross_dept_contact|notebook_started|WardRoomProtocol|BOOT_CAMP_PHASE_ADVANCE' (all but prompts/); Grep 'AgentBootCampState\(' src tests scripts; Grep boot_camp ui/src
FOUND: boot_camp.py; crew.py:25; system.yaml:2117; events.py:406; event_persistence.py:144; the generated reference and facade rows; tests; protocols.py:209 and cognitive_agent.py:2708 (different objects with the same names); AgentBootCampState( at boot_camp.py:181 only; ui/src none
HOLDS: yes

CLAIM: runtime.ship_state_snapshot does not exist when Phase 7 builds the coordinator
RUN:   Grep 'ship_state_snapshot|_ship_state_builder|orientation_snapshot_text|bind_ship_state_builder' src
FOUND: the one assignment is finalize.py:1281 (_wire_ship_state_snapshot); runtime.py:3336 reads it with getattr(..., None)
HOLDS: yes

CLAIM: no test pins the docstrings or comments A1 rewrites
RUN:   Grep 'reaches it through|late-bound, needs ward_room|needs ward_room|Captain's switch|enrolment relaxes nothing' tests
FOUND: none
HOLDS: yes

CLAIM: nothing but the facade hashes SystemConfig's JSON schema, so descriptions move no other pin
RUN:   Grep -l model_json_schema tests scripts src
FOUND: check_config_facade.py; test_ad1270e1 (path models), test_config.py and test_ad666 (SensoriumConfig), test_ad1192
HOLDS: yes
```

## Verified Against Codebase (Amendment A2, 2026-10-28, on the oracle `43f54b7f`: the M3 tree plus trackers)

```
git diff -U1 f1e3432c c09a3617 -- docs/development/config-facade-baseline.yaml   M1: surface_counts public_names 310->309, owned 297->296, own_models 229->228 (absent from A1's §4 list)
git diff -U1 701d9d32 e5d539e4 -- docs/development/config-facade-baseline.yaml   M2: exactly §4's M2 list
Read tests/test_ad1270e1_config_facade.py:1515-1568, 1792-1803 (the four pins; P-T16's text at 1562-1568)
Read the orchestrator's s6_census.py (parse, main) and census_rows_audit2.py; census-rows-audit2-a1.txt (13 of 27 rows)
Grep each §10 anchor as a whole stripped line (^\s*<anchor>\s*$), one hit each: events.py:405, :488; config.py:4115;
  system.yaml:2116, :2347; finalize.py:892, :4195, :4216; crew_development/__init__.py:34; boot_camp.py:118, :120, :130, :135;
  crew.py:52, :53; cognitive_agent.py:6551, :10482, :10484, :12895 (C-3, C-14, C-17, H-1: OK in the audit)
Read events.py:15, :531-532 (assert_complete at import); event_persistence.py:488-520 (reads GRANDFATHERED when called)
Read tests: orientation (whole); tracker_retired (whole); trust:243-330; repair_a1:222-252; contract:440-509, 576-593; seam:324-329
```

## Absence Verified (Amendment A2, 2026-10-28)

```
CLAIM: R14-1 and R14-2 are named nowhere outside section 10
RUN:   Grep 'R14-1|R14-2' (this contract)
FOUND: 2290, 2318, 2319 (all in section 10, replaced by A2's section 10)
HOLDS: yes

CLAIM: a two-file EventType mutant split into halves is killed only at import, never by a named test
RUN:   Grep assert_complete src; Read events.py:531-532; tracker_retired:24 and orientation:27 import EventType at module level
FOUND: events.py:15, :532 (the import-time call); event_persistence.py:5, :488
HOLDS: yes -- each half is a collection ERROR on a file node; T-1 and C-13 are therefore single-site rows
```

## Verified Against Codebase (Amendment A3, 2026-10-28, on the oracle `4f24469f`: 4b's candidate `d8e6eb7f` plus A2 applied by tool)

```
git diff --stat 8f0454b5 d8e6eb7f        4b's contract and tests/test_ad1324_srp_layout.py (R3) only
git diff --stat d8e6eb7f 804345c3        4b's contract only; 804345c3 has tree 3f9bf0e2
git diff --name-status --diff-filter=AD d8e6eb7f 4f24469f   A: the three new test files; D: crew_development/boot_camp.py, tests/test_ad509_boot_camp.py
git show d8e6eb7f:tests/test_ad509_boot_camp.py | grep -nE "def test_|parametrize"   15 cases, no parametrize
git show d8e6eb7f:tests/test_ad638_boot_camp.py | grep -c "def test_"   35; 29 on 4f24469f; no parametrize
git diff -U0 d8e6eb7f 4f24469f -- tests   an added AD-1270 line in each updated file but test_ad640 and test_ad683 (deletions only)
Grep (the three new files) LOCALAPPDATA|AppData|environ|getenv|subprocess|ProbOSRuntime|Runtime\(|\.start\(   none
Grep (src, tests) bind_ship_state_builder\(   src: finalize.py:894 only; tests: test_ad1270_boot_camp_orientation.py
Grep (src, tests) \.boot_camp\s*=[^=]|boot_camp=   src: runtime.py:3331; tests: coordinators, None, the orientation rig
Grep (src) model_json_schema|json_schema|field_info   none
Grep (src, ui/src) HOLODECK_PHASE_ENTERED|holodeck_phase_entered   events.py, GRANDFATHERED, chamber.py x3
Grep (src, ui/src) BOOT_CAMP_PHASE|boot_camp_phase_advance   none
Grep (src) section 14 item 5's pattern   config.py:4115, crew.py:52, phases.py:11 (removal notes); cognitive_agent.py:2708,2755; protocols.py:209; consumer.py:190,652; thread_fanout.py:468-469
Grep (all but logs/) the four test file names   see section 12
Read boot_camp.py:93-136, 243-351; finalize.py:883-895, 4212-4222; cognitive_agent.py:10477-10490; test_ad1270_boot_camp_trust.py:246-329; test_ad1270e1_config_facade.py:1519-1527
logs/ad1270/measure-ad1270c-dry3.log   new files 11, 21 and 2 passed; focused lists 1,341 and 1,629 passed (2 skipped); the five checks green
```

## Not verified (the orchestrator verifies by running)

- Every predicted count: test cases, the census, facade and leaf counts, `EventType` counts, the e1 `names`/`models` counts.
- The exact equality in `test_the_snapshot_block_is_the_only_difference`, which depends on the ContextAssembler join. If it fails while both `startswith(f"{_HEADER}\n{text}\n---\n")` and `endswith(baseline)` hold, assert those two plus the length sum, and record why inline.
- That test_ad1227's runtime shape with a default `SystemConfig()` renders the DM path (test_ad1227 uses `memory.recall_outcome_refs_enabled` toggles on the same shape).
- `BootCampCoordinator` at 17 methods and about 305 lines after M2.
- The AD-1152 hashes (measured).
- That the reference generator removes only the listed rows.

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** no row change (19 → 17 methods, `[methods]`). `finalize.py`'s private access disappears; that category is report-only. A1 adds a module function to `finalize.py` (no class row; `finalize.py` has no row) and no method to `BootCampCoordinator`.
- **`check_dormant_classes.py --check`:** unchanged at 160. The deleted classes were live or are excluded kinds (Protocol, Enum, pydantic).
- **`check_config_facade.py`, `gen_config_reference.py`, `check_config_profiles.py`:** regenerated or paired per milestone.
- **`gen_ad_ledger.py --check`:** AD-1270 stays `shipped` (predicted; M4's `--check` measures it).
- **Test collection:** three new test files and one deleted test file (`git diff --name-status --diff-filter=AD` over the slice, `-- tests`). A Grep for the four file names outside `logs/` finds this contract, `prompts/ad-1270-onboarding.md`, two files under `prompts/archive/`, `decisions-era-5-unification.md`, `progress-era-5-unification.md` and a stale `tests/test_ad509_boot_camp.py` key in `tests/fixtures/file_durations.json`, which `scripts/gen_file_durations.py` rewrites from a green canonical gate.

## 13. Prior Art and Blind Spots

- **Internal:**
  - `docs/research/crew-development-research.md:77,241` maps "Boot Camp" onto AD-486's Construct, the birth chamber. Adopted: AD-486 stays the orientation host and R7 repairs its payload; AD-509's parallel model is deleted.
  - `prompts/archive/ad-486-holodeck-birth-chamber-v1.md:27,1395` ("two trackers coexist") and `prompts/archive/ad-683-ship-state-snapshot-v1.md:820` ("v1 does not couple them"): the coexistence was always deliberate deferral, not design.
  - The Tucker onboarding case study (2026-05-07): crew onboard newcomers unprompted. This informs D3.
  - BF-926 (`6f94608b`): removed keys load; refresh the golden by measurement. Followed.
- **External:** skipped. This is ProbOS-specific retirement and wiring plumbing with no outside design to borrow. `docs/research/reference-projects.md` was not examined.
- **Blind spots found:**
  - (1) The snapshot was dead by path, not only by flag (P7).
  - (2) The snapshot is frozen at activation; labelled (D4).
  - (3) Deleting methods crosses the SRP method threshold, which forced the milestone order.
  - (4) `PacingPolicy` (AD-509e) is left without a host (4c-R1).
  - (5) Chain prompts carry no snapshot (4c-R2).
  - (A1-1) The DM read now expires the boot camp, so prompt construction can emit `BOOT_CAMP_TIMEOUT` (D10; pinned).
  - (A1-2) A bind after activation captures nothing (docstring; finalization binds before activating, AST-pinned).
  - (A1-3) A prompt composed just before graduation carries the snapshot for that one turn. It is context, not a gate: no action.
  - (6) The Captain's file keeps two ignored keys (no action).
  - (7) The JetStream streams were unreadable by the probe; a replayed removed name resolves to `None` (`durable_events.py:566-571`).
  - (8) Slice 4b's "enrolment changes no prompt" claim is revised in U1 and U2.

## 14. Diff Reviewer: properties to verify

1. With `relax_quality_gates` off, the only prompt change is one `boot_snapshot` bid, on the `direct_message` branch, for an agent `is_enrolled` reports true. Any runtime whose `boot_camp` is `None`, missing or answers non-`str` renders byte-identically.
2. `_boot_camp_active`'s one writer (`_refresh_boot_camp_relaxation`) and its readers in `evaluate.py`, `reflect.py`, `sub_task.py` and AD-639 are unchanged, and `_build_user_message` no longer reads it.
3. `orientation_snapshot_text` asks `is_enrolled` before it checks the snapshot, so it enforces the timeout with or without a snapshot and can be the read that emits the one `BOOT_CAMP_TIMEOUT`. A `render_text` failure is logged and yields `""`; the `render_text` call is the only one inside a `try`.
4. `bind_ship_state_builder` never replaces a non-`None` builder and ignores `None`. `finalize.py` has no `_ship_state_builder` attribute access; `_late_bind_boot_camp_snapshot` is the setter's one caller in `src`, and its call sits inside the snapshot-wired branch, between `_wire_ship_state_snapshot` and `_activate_boot_camp_on_cold_start`.
9. Every `BootCampConfig` field has a description and the generated reference shows it; the facade diff is limited to §4's list.
10. The chain census classifies by qualified name and credits no nested definition's calls to its parent; the test asserts that the chain-executing definitions it finds are exactly `_GATING_PHASES` and `_LOOKUP_PHASES` under `CognitiveAgent.` (five methods).
11. Each comment and docstring the slice adds or rewrites is true of the tree after it, among them `_expire_if_timed_out`'s, the runtime guard's, the two coordinator methods', P-C13's and the trackers'. P-T17 keeps the `AD-1341 S5 (#1569)` trailing comments on the lines whose values it changes; they record AD-1341's own change (for example `309 -> 310`), and the slice's `AD-1270` comment above each such line or group records this slice's.
5. A Grep of `src` for `BootCampPhase|boot_camp_phase|boot_camp_tracker|BOOT_CAMP_PHASE_ADVANCE|run_phase_2_introductions|run_phase_3_observation|_DEPARTMENT_CHIEFS|nudge_cooldown|_observation_thread_id|_can_nudge|_record_nudge|introduced_to_chief|cross_dept_contact|notebook_started|shared_observation|WardRoomProtocol` finds only comments and a docstring that record a removal, AD-536's own `_DEPARTMENT_CHIEFS` in `cognitive_agent.py`, `protocols.py`'s own `WardRoomProtocol` and `latest_shared_observation` (`perception/consumer.py`, `routers/thread_fanout.py`). Both event types are gone from `EventType` and GRANDFATHERED. The tracked yaml carries neither removed key.
6. A config carrying `boot_camp_phase:` or `boot_camp.nudge_cooldown_seconds` loads.
7. Each generated file was produced by its tool, and the golden hashes by measurement. `git diff` of `config/system.yaml` over the slice shows two hunks, `boot_camp_phase:` (M1) and `nudge_cooldown_seconds` (M2).
8. The tracker heads carry no lifecycle keyword in their first 120 characters, and each claim in them is true of the head.

## 15. Acceptance criteria

- The three new files pass; every §10 mutant is killed.
- `check_architecture_principles.py --check`, `check_dormant_classes.py --check` (paste its whole output), and the facade, profiles, reference and ledger checks pass.
- The focused gates pass and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **4b-R4 to 4b-R7: built by this slice.** 4b-R6's A2 note (the DM read of a stale marker) is ended by P-C13, with `test_a_stale_relaxation_marker_adds_no_snapshot`.
- **4b-R12, 4b-R13, 4b-R14: built by this slice** (P-C9; P-C14, P-C33 and `test_finalization_late_bind_reaches_an_enrolled_agents_dm`; P-C27).
- **4b-R8, 4b-R9, 4b-R11: unchanged.**
- **4b-R10 (owner #1324): slice 4d, after this slice merges**, under its own BF number allocated when its prompt is drafted (`.github/copilot-instructions.md:92`). No new issue. It is agent-facing at the next reset, so the Captain is told when it lands.
- **4c-R1 (owner #1324, dormant sweep):** `cognitive/priority4_cleanup.py::PacingPolicy` (AD-509e) is `wire` on the dormant baseline, but its five phase names are AD-509's deleted model. Re-dispose it (recommend retire) in the next dormant-class sweep.
- **4c-R2 (owner #1324, unscheduled):** chain prompts (Ward Room, proactive) do not carry the snapshot, and the snapshot is never refreshed during boot camp. If cold-start crew should see current state in Ward Room work, that is a design item, not a repair.
- **4c-R3 (trivial):** `BootCampCoordinator.on_agent_post` keeps a now-unused `channel_type` parameter for its caller (`proactive.py`). Drop it when that caller is next touched.
- **4c-R4 (trivial):** `test_ad638_boot_camp.py` has unused imports from before this slice (`asyncio`, `Any`, `patch`, `AgentBootCampState`).
