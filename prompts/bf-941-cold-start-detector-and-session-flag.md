# BF-941 (#1324 slice 4d, register 4b-R10): BF-034's cold-start detector asks the boot camp's new-crew predicate, its Fresh Start thread moves to finalization, and the fresh-start window closes at the first dream cycle or the orientation window

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

**Status:** build-ready. Drafted on `ed253049`: slice 4c's candidate with slice 5's contract applied by tool. Slice 4d builds after slice 5 and slice 1b merge. **BF-941** was allocated by enumeration (`logs/ad1270/live-and-bf-evidence-4d.md` §2; the highest in use is BF-940). No issue is filed (4b's D7): the prompt filename and the commit subjects carry the number, and the contract is tracked as #1324 register row 4b-R10. **Tier:** HIGH. **Captain:** told, nothing parked. Overrulable: D2 (the window follows the orientation window), D3 (the Fresh Start thread replaces the auto-welcome, as BF-102 designed).

**Anchors.** Every pair anchors on `ed253049` text that slice 5 does not add or change. Slice 5's five `finalize.py` receipt sites, its import block and its `PROGRESS.md`/`DECISIONS.md` entries are not anchors. P-U2 anchors on 4c's heading, which slice 5 leaves alone. Six paired test files assume slice 1b leaves them alone (§12): `test_ad1326_startup_wiring.py`, `test_new_crew_auto_welcome.py`, `test_ad1270_boot_camp_lifecycle.py`, `test_ad1270_boot_camp_repair_a1.py`, `test_ad1324_srp_layout.py` and `docs/development/architecture-baseline.yaml`. If 1b changes any paired line, re-anchor that pair; do not rewrite it. 31 pairs, three new files (§7.1.N, §7.2.N, §7.3.N) and one measured value (§7.4).

**Which text describes the head.** These are records of `ed253049`: the Status and Anchors paragraphs, §7 (pairs, new files, §7.4), §10, §11, every Verified and Absence block, the Not verified list and §13. The tests-first predictions and build orders in §4 and §6 are records too. The Milestones and Tests lists, §1, §2, §3, §4's focused-gate table, §5, §8's entries, §9, §12, §14 and §15 describe the candidate's head. They name no commit and no line number, and every count in them is one that a named command or gate measures.

**Milestones:**
- **M1 (HIGH):** the fresh-start window. `runtime.is_cold_start` opens once at Phase 5 and closes at the first full dream cycle or after `orientation.orientation_window_seconds`. The dream adapter ends the runtime's flag. The proactive note and the cold-start orientation state no trust number. On its own M1 opens no fresh-start window on a boot with an episodic memory, because the detector cannot fire there until M2; the cold-start orientation's trust line changes at once.
- **M2 (HIGH):** the detector. `probos.startup.crew_start.is_new_crew_start` is shared with the boot camp's `_is_new_crew_start`. The Fresh Start thread moves to finalization. `init_dreaming` takes `lifecycle_state` and no longer takes `ward_room`. AD-435 titles a `reset` boot as a first activation. The architecture-baseline row is removed.
- **M3 (docs):** trackers and the ledger.

Each milestone is one Builder delegation and one local commit, staged by explicit path (never `git add -A`). One cross-family review (`gpt-6.1-sol`) of M1 and M2 against §14. One mutation campaign of record on the M2 tree (§10). Broad gate once, after M3, alone: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf941-cold-start-detector --receipt logs/gates/bf941-cold-start-detector.receipt.json`.

**Tests:**
- New: `tests/test_bf941_fresh_start_window.py` (M1, 7 cases) and `tests/test_bf941_cold_start_detector.py` (M2, 20 cases), as `pytest <file> -n 0` reports for each.
- Updated: `tests/test_ad1324_srp_layout.py` (the pin, measured), `tests/test_ad1326_startup_wiring.py`, `tests/test_new_crew_auto_welcome.py`, `tests/test_ad1270_boot_camp_lifecycle.py` (a comment) and `tests/test_ad1270_boot_camp_repair_a1.py` (a message).
- A Grep of the two new test files for `LOCALAPPDATA|AppData|environ|getenv|subprocess|Runtime\(` finds nothing.

## 1. Problem

- **BF-034's detector cannot fire on a boot with an episodic memory** (`startup/dreaming.py`, the `BF-034` block in `init_dreaming`). It requires two things, and each is false on a boot with an episodic memory and an AD-640 bridge or chief prior:
  - `episodes_empty = not episodic_memory` tests the memory object's truthiness, which holds whenever a memory exists.
  - `all_at_prior` requires every trust record at the generic prior. AD-640 gives bridge and chief roles their own priors at Phase 2 (`agent_onboarding.py`, `tiered_trust.initialize_trust`).
  - Live evidence (read only): over the six rotated logs, `BF-034: Cold start detected` appears 0 times. The same block's `BF-178: Stasis recovery` line appears in every file, which proves the block runs and logs.
- **Its announcement is dead by phase as well.** The Fresh Start thread runs only `if cold_start and ward_room`. At Phase 5, `runtime.ward_room` is still the `None` from `__init__`; Phase 7 assigns it. The announcement also used a bare `loop.create_task`, which is the `unowned-task` row for `probos.startup.dreaming::init_dreaming` in `architecture-baseline.yaml`.
- **The session flag is never cleared.** `runtime._cold_start` is set at Phase 5 and nothing in `src` clears it. The AD-517 extraction left BF-034's post-dream clear on `DreamAdapter._cold_start`, a copy finalization takes. A repaired detector would therefore keep "You have no prior episodic memories" in agents' prompts for the whole session.
- **Text that would switch on is wrong.**
  - The proactive note and the Fresh Start body say "All trust scores are at baseline (0.5)", which AD-640 contradicts.
  - The Fresh Start body says "This instance has been reset" and "Episodic memory has been cleared", which is false on a first install.
  - The cold-start orientation (already live for every newborn crew agent) says "Your trust starts at baseline (0.5)".
- **AD-435's startup announcement has no `reset` branch.** The detector's `reset` label would replace "System Online — First Activation" with the generic "System Online".

## 2. Solution

**The predicate.**
- `startup/crew_start.py` holds `is_new_crew_start(lifecycle_state, episodic_memory)`: no previous session record (`first_boot` or `reset`) and `get_stats()` answering `total == 0`. It fails warm.
- `init_dreaming` asks it with the new `lifecycle_state` argument; the runtime passes `self._lifecycle_state`. BF-178's stasis branch reads the same argument.
- Finalize's `_is_new_crew_start(runtime)` delegates to the same function.

**The window.**
- `ProbOSRuntime.adopt_new_crew_start(cold_start)` replaces the inline adoption in `start()`. For a new crew it opens the window for `orientation.orientation_window_seconds` and sets `reset`.
- `is_cold_start` is true while the flag is set and the window is open.
- `end_cold_start(reason)` clears the flag. `DreamAdapter` takes `end_cold_start_fn` and calls it when it clears its own copy after a dream cycle; finalization passes `runtime.end_cold_start`.

**The announcement.**
- `crew_start.announce_fresh_start(ward_room)` posts "Fresh Start — New Crew" to All Hands, log-and-degrade.
- Finalization awaits it after the AD-435 announcement, under the same `runtime._cold_start` that skips the BF-102 auto-welcome.
- AD-435 treats `reset` as a first activation.
- Phase 5 no longer touches the Ward Room, so `init_dreaming` loses its `ward_room` parameter and its unowned task.

**Text.** The proactive note, the Fresh Start body and the cold-start orientation state no trust number and no reset.

## 3. Decisions

- **D1.** One predicate, in `startup/crew_start.py`, asked at Phase 5 and again at Phase 8. The trust half goes: the default `probos reset` tier deletes `trust.db` with `session_last.json`, and AD-640 role priors are not evidence of prior service.
  - The two answers can differ, for example when an episode is stored between Phase 5 and Phase 8; the boot camp is then skipped (warm).
  - Rejected: the boot camp reading Phase 5's flag (the window closes, and it couples enrolment to a prompt note); Phase 5 importing from `finalize.py`; keeping the trust half against role priors.
- **D2.** The window closes at the first full dream cycle or after `orientation.orientation_window_seconds`, whichever comes first.
  - The runtime owns the flag. The adapter keeps its copy and its log line, and calls the runtime.
  - Rejected: a dream-only bound (a dream needs 120 s with no Captain request, a dream before finalization rewires the adapter is lost, and the next waits 600 s); a boot-camp bound (up to 120 minutes); a new config field.
- **D3.** The Fresh Start thread's gate is the auto-welcome's with `runtime._cold_start` negated. Both read `runtime._cold_start` during finalization, at two points with awaits between them (4d-R4). It uses `get_channel_by_name("All Hands")` as its two neighbours do, and is awaited inline.
- **D4.** A `reset` boot keeps AD-435's first-activation title, so the only new thread a new crew sees is the Fresh Start thread.
- **D5.** The text rewrites are part of this BF. Switching the readers on with false text is not a repair.

## 4. Milestones

Write each milestone's new test file first and run it on that milestone's base:
- **M1:** all 7 cases fail, by `AttributeError` (`adopt_new_crew_start`) or by assertion. No collection error.
- **M2:** all 20 cases fail, by `ModuleNotFoundError` (`probos.startup.crew_start`, imported per case), by `TypeError` (`init_dreaming`'s keywords) or by assertion (the census, the signature). No collection error. Any case passing is a stop.

Never delete or loosen a test beyond the listed pairs. Run focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| M | Tier | Sections | Focused gate |
|---|---|---|---|
| **M1** | HIGH | 7.1 | `tests/test_bf941_fresh_start_window.py tests/test_bf034_cold_start.py tests/test_ad1077_group_chat_coaching.py tests/test_bf102_new_crew_awareness.py tests/test_ad646b_chain_parity.py tests/test_proactive.py tests/test_orientation.py tests/test_temporal_context.py tests/test_bf103_episode_id_mismatch.py tests/test_ad573d_dream_to_working_memory.py tests/test_ad791g_main_chat_thread.py tests/test_ad933a_group_episode.py tests/test_bf879_designed_agents_start_probationary.py tests/test_dreaming.py tests/test_new_crew_auto_welcome.py tests/test_bf235_stale_identity_cache.py tests/test_ad680_public_runtime_api.py`; then `-P scripts/check_architecture_principles.py --check` |
| **M2** | HIGH | 7.2, 7.3, 7.4 | `tests/test_bf941_cold_start_detector.py tests/test_bf941_fresh_start_window.py tests/test_ad1326_startup_wiring.py tests/test_new_crew_auto_welcome.py tests/test_ad1270_boot_camp_lifecycle.py tests/test_ad1270_boot_camp_repair_a1.py tests/test_ad1270_boot_camp_orientation.py tests/test_ad1270a_startup_receipts.py tests/test_ad1270a_activation_receipts.py tests/test_bf034_cold_start.py tests/test_bf178_stasis_anomaly.py tests/test_bf166_consolidation_cold_start.py tests/test_emergent_detector.py tests/test_temporal_context.py tests/test_ad1324_srp_layout.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1270f_impact_selector.py tests/test_layer_boundaries.py tests/test_finalize.py tests/test_bf927_boot_claims.py`; then `-P scripts/check_architecture_principles.py --check` and `-P scripts/check_dormant_classes.py --check` (paste its whole output) |
| **M3** | docs | §8; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` | `tests/test_ad1184_ad_ledger.py`; `-P scripts/gen_ad_ledger.py --check` |

**M1 build order:** write 7.1.N and run it (7 failures). Apply P-R1 to P-R4, P-A1 to P-A3, P-F1, P-P1 and P-O1. Run the gate. Commit.

**M2 build order:**
1. Write 7.3.N and run it (20 failures).
2. Write 7.2.N (`crew_start.py`).
3. Apply P-S1 to P-S4, P-R5, P-R6 and P-F2 to P-F5, then the test pairs P-T2 to P-T8. P-T5 and P-T6 fail `test_auto_welcome_skipped_on_cold_start` until P-F4 and P-F5 are in; apply them together.
4. Apply P-B1.
5. §7.4: measure the baseline's LF-normalised sha256 and write it into P-T1's token.
6. Run the gate. `check_architecture_principles.py --check` must report no new and no stale row.
7. Commit.

**M3 build order:** apply P-U1 and P-U2, regenerate the ledger, run the gate, commit.

## 5. Consumers of every value this changes

- **`init_dreaming(...)`:** callers are `runtime.py`'s Phase 5 call and `tests/test_ad1326_startup_wiring.py` (P-R5, P-R6, P-T3). `ward_room` is removed, and `lifecycle_state` defaults to `""`, which is not a new crew.
- **`runtime.is_cold_start`:** readers are `CognitiveAgent._sensorium_cold_start_note` (its `_cold_start_note` feeds `sub_tasks/analyze.py` and `sub_tasks/compose.py`), the BF-102 Ward Room note in `cognitive_agent.py`, and `ProactiveCognitiveLoop._gather_context`'s `system_note` (which feeds the proactive-think prompt and `_sensorium_situation_system_note`; AD-1077 coaching waits while it is present). After the window closes, each renders as for a warm boot.
- **`runtime._cold_start` (raw):** read only during finalization: the adapter copy, the new Fresh Start gate and the auto-welcome guard.
- **`_lifecycle_state == "reset"`:** readers are `runtime.py`'s HXI `fresh_boot`; `cognitive_agent.py`'s sparse-memory note (`lifecycle != "reset"`, two sites); the proactive loop's `memory_state.lifecycle` and `context["lifecycle_state"]`; `emergent_detector`'s phase tag; `introspective_telemetry`; finalize's `_is_new_crew_start` (accepts it); and AD-435 (first-activation title, P-F4).
- **`DreamAdapter(end_cold_start_fn=...)`:** a keyword-only default `None`. Finalize passes `runtime.end_cold_start`. The six test constructions are unaffected.
- **Text:** consumed by the LLM (the proactive note, the orientation) and by the crew and Captain (the Fresh Start thread). No test pins the old wording (§11 Absence block).
- **The `unowned-task` row for `init_dreaming`:** removed (P-B1), and the pin is moved by measurement (P-T1).

## 6. Tests

| File | Cases | On its milestone's base | Change |
|---|---|---|---|
| `tests/test_bf941_fresh_start_window.py` (M1) | 7 | 7 fail | new |
| `tests/test_bf941_cold_start_detector.py` (M2) | 20 | 20 fail | new |
| `tests/test_new_crew_auto_welcome.py` | unchanged count | `test_auto_welcome_skipped_on_cold_start` fails until P-F4/P-F5 | P-T4 to P-T6 |
| `tests/test_ad1326_startup_wiring.py` | unchanged | fails without P-T3 after P-S2 | P-T2, P-T3 |
| `tests/test_ad1324_srp_layout.py` | unchanged | the pin fails until §7.4 | P-T1 |
| `tests/test_ad1270_boot_camp_lifecycle.py`, `tests/test_ad1270_boot_camp_repair_a1.py` | unchanged | pass before and after | P-T7, P-T8 (a comment and a message) |

The cross-seam test is `test_a_new_crew_reaches_the_agent_note_until_the_first_dream` (three cases). It runs Phase 5's `init_dreaming` with AD-640 role priors and a truthy memory, carries the answer through `adopt_new_crew_start` into the agent's note, and has a dream adapter, wired as finalization wires it, close the window. Its stasis-recovery and episodes-kept cases are the controls.

## 7. The contract

### 7.1 M1: the fresh-start window

**P-R1** `src/probos/runtime.py`

SEARCH:
```
    _cold_start: bool
    _start_time: float
```
REPLACE:
```
    _cold_start: bool
    _cold_start_until: float
    _start_time: float
```

**P-R2** `src/probos/runtime.py`

SEARCH:
```
        # BF-034: Cold-start flag — True when booting with empty state (post-reset)
        self._cold_start: bool = False
```
REPLACE:
```
        # BF-034: Cold-start flag — True when this boot starts a new crew (BF-941: set once at Phase 5)
        self._cold_start: bool = False
        # BF-941: when the fresh-start window closes (time.monotonic()); see is_cold_start
        self._cold_start_until: float = 0.0
```

**P-R3** `src/probos/runtime.py`

SEARCH:
```
    @property
    def is_cold_start(self) -> bool:
        """True during first cycle after a clean reset (no prior state)."""
        return self._cold_start
```
REPLACE:
```
    @property
    def is_cold_start(self) -> bool:
        """BF-034 / BF-941: True while a new crew's fresh-start notes apply.

        Opened once at Phase 5 by ``adopt_new_crew_start`` from the new-crew predicate
        (``probos.startup.crew_start.is_new_crew_start``). Closed by the first full dream cycle
        (``end_cold_start``, called by the dream adapter) or once
        ``orientation.orientation_window_seconds`` have passed, whichever comes first.
        """
        return self._cold_start and time.monotonic() < self._cold_start_until

    def adopt_new_crew_start(self, cold_start: bool) -> None:
        """BF-941: adopt Phase 5's new-crew answer; ``start()`` calls this once.

        A new crew opens the fresh-start window for ``orientation.orientation_window_seconds``
        and takes AD-502's lifecycle state ``reset``; any other boot changes nothing.
        """
        self._cold_start = cold_start
        if cold_start:
            self._cold_start_until = time.monotonic() + self.config.orientation.orientation_window_seconds
            self._lifecycle_state = "reset"

    def end_cold_start(self, reason: str) -> bool:
        """BF-941: clear the fresh-start flag (the first dream cycle calls this); True when it was set."""
        if not self._cold_start:
            return False
        self._cold_start = False
        logger.info("BF-941: fresh-start window ended (%s)", reason)
        return True
```

**P-R4** `src/probos/runtime.py`

SEARCH:
```
        self._cold_start = cold_start
        if self._cold_start:
            self._lifecycle_state = "reset"
```
REPLACE:
```
        self.adopt_new_crew_start(cold_start)  # BF-941: opens the fresh-start window for a new crew
```

**P-A1** `src/probos/dream_adapter.py`

SEARCH:
```
        working_memory: Any = None,  # AD-573d: dream-to-WM pipeline
    ) -> None:
```
REPLACE:
```
        working_memory: Any = None,  # AD-573d: dream-to-WM pipeline
        end_cold_start_fn: Callable[[str], Any] | None = None,  # BF-941: runtime.end_cold_start
    ) -> None:
```

**P-A2** `src/probos/dream_adapter.py`

SEARCH:
```
        self._working_memory = working_memory  # AD-573d

        # Runtime state references (set by runtime after creation)
        self._cold_start: bool = False
```
REPLACE:
```
        self._working_memory = working_memory  # AD-573d
        self._end_cold_start_fn = end_cold_start_fn  # BF-941

        # Runtime state references (set by runtime after creation)
        self._cold_start: bool = False
```

**P-A3** `src/probos/dream_adapter.py`

SEARCH:
```
        # BF-034: Clear cold-start flag after first dream cycle
        if self._cold_start:
            self._cold_start = False
            logger.info("BF-034: Cold start period ended — normal detection resumed")
```
REPLACE:
```
        # BF-034: Clear cold-start flag after first dream cycle
        if self._cold_start:
            self._cold_start = False
            logger.info("BF-034: Cold start period ended — normal detection resumed")
            # BF-941: end the runtime's flag too, so the fresh-start notes stop with this cycle
            if self._end_cold_start_fn is not None:
                self._end_cold_start_fn("first dream cycle")
```

**P-F1** `src/probos/startup/finalize.py`

SEARCH:
```
        working_memory=getattr(runtime, "working_memory", None),  # AD-573d
    )
    dream_adapter._cold_start = runtime._cold_start
```
REPLACE:
```
        working_memory=getattr(runtime, "working_memory", None),  # AD-573d
        end_cold_start_fn=runtime.end_cold_start,  # BF-941: the first dream cycle ends the fresh-start window
    )
    dream_adapter._cold_start = runtime._cold_start
```

**P-P1** `src/probos/proactive.py`

SEARCH:
```
        # BF-034: Cold-start context note for agents
        # AD-567g: Orientation subsumes this note when available
        _has_orientation = bool(getattr(agent, '_orientation_rendered', None))
        if not _has_orientation and hasattr(rt, 'is_cold_start') and rt.is_cold_start:
            context["system_note"] = (
                "SYSTEM NOTE: This is a fresh start after a system reset. "
                "All trust scores are at baseline (0.5). This is normal initialization, "
                "not a demotion. Build trust through demonstrated competence. "
                "You have no prior episodic memories — do not reference or invent past experiences."
            )
```
REPLACE:
```
        # BF-034: Cold-start context note for agents
        # AD-567g: Orientation subsumes this note when available
        # BF-941: no trust number (AD-640 starts bridge and chief roles above the generic
        # prior) and no "reset" (a first install is a new crew too)
        _has_orientation = bool(getattr(agent, '_orientation_rendered', None))
        if not _has_orientation and hasattr(rt, 'is_cold_start') and rt.is_cold_start:
            context["system_note"] = (
                "SYSTEM NOTE: This is a fresh start: this crew has no previous session record "
                "and no stored episodes. Trust starts at each role's initial level; this is "
                "normal initialization, not a demotion. Build trust through demonstrated competence. "
                "You have no prior episodic memories — do not reference or invent past experiences."
            )
```

**P-O1** `src/probos/cognitive/orientation.py`

SEARCH:
```
            "- Build relationships through the Ward Room. Your trust starts at baseline (0.5) "
            "— earn it through demonstrated competence.",
```
REPLACE:
```
            # BF-941: AD-640 sets the initial trust by role, so the text names no number
            "- Build relationships through the Ward Room. Your trust starts at your role's initial "
            "level — earn more through demonstrated competence.",
```

#### 7.1.N New file: tests/test_bf941_fresh_start_window.py

```
"""BF-941 (#1324 slice 4d) M1: BF-034's fresh-start window is bounded before its detector is wired.

``runtime.is_cold_start`` drives the fresh-start notes in agents' prompts. BF-034 meant it to end
after the first dream cycle, but the AD-517 extraction left that clear on the dream adapter's own
copy, so nothing ended the runtime's flag. It now opens once at Phase 5 (``adopt_new_crew_start``)
and closes at the first full dream cycle, through the adapter, or after
``orientation.orientation_window_seconds``, whichever comes first. The proactive note and the
cold-start orientation no longer state a trust number that AD-640's role priors contradict.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.orientation import OrientationContext, OrientationService
from probos.config import OrientationConfig, SystemConfig
from probos.dream_adapter import DreamAdapter
from probos.runtime import ProbOSRuntime

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"


def _runtime(lifecycle: str, *, window: float = 600.0) -> ProbOSRuntime:
    """A runtime holding only what the fresh-start window reads; nothing is booted."""
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime.config = SystemConfig(orientation=OrientationConfig(orientation_window_seconds=window))
    runtime._cold_start = False
    runtime._cold_start_until = 0.0
    runtime._lifecycle_state = lifecycle
    return runtime


def _adapter(runtime: ProbOSRuntime) -> DreamAdapter:
    """A dream adapter wired as finalization wires it: the runtime's end, and the flag copied."""
    adapter = DreamAdapter(
        dream_scheduler=None,
        emergent_detector=None,
        episodic_memory=None,
        knowledge_store=None,
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        event_emitter=lambda *_args, **_kwargs: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=MagicMock(),
        event_log=None,
        config=SystemConfig(),
        pools={},
        end_cold_start_fn=runtime.end_cold_start,
    )
    adapter._cold_start = runtime._cold_start  # finalize.py copies the runtime's flag the same way
    return adapter


def _note(runtime: ProbOSRuntime) -> str:
    """The chain-baseline cold-start note an agent on this runtime renders (BF-102)."""
    return CognitiveAgent._sensorium_cold_start_note(SimpleNamespace(_runtime=runtime), {})


@pytest.mark.parametrize(
    ("lifecycle", "new_crew", "after"),
    [("first_boot", True, "reset"), ("stasis_recovery", False, "stasis_recovery")],
    ids=["new-crew", "warm"],
)
def test_phase_fives_answer_opens_the_window_and_marks_a_new_crew_reset(lifecycle: str, new_crew: bool, after: str) -> None:
    runtime = _runtime(lifecycle)

    runtime.adopt_new_crew_start(new_crew)

    assert runtime.is_cold_start is new_crew
    assert runtime._lifecycle_state == after
    assert ("fresh start" in _note(runtime).lower()) is new_crew


def test_the_window_closes_by_time_without_a_dream() -> None:
    runtime = _runtime("first_boot", window=0.0)

    runtime.adopt_new_crew_start(True)

    assert runtime.is_cold_start is False
    assert _note(runtime) == ""
    assert runtime._lifecycle_state == "reset"  # the label outlives the window


def test_the_first_dream_cycle_ends_the_window_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="probos.runtime")
    runtime = _runtime("first_boot")
    runtime.adopt_new_crew_start(True)
    adapter = _adapter(runtime)
    assert "fresh start" in _note(runtime).lower(), "premise: the window is open before the dream"

    adapter.on_post_dream(None)
    adapter.on_post_dream(None)

    assert runtime.is_cold_start is False
    assert _note(runtime) == ""
    assert runtime.end_cold_start("again") is False
    ended = [r.getMessage() for r in caplog.records if r.getMessage().startswith("BF-941: fresh-start window ended")]
    assert ended == ["BF-941: fresh-start window ended (first dream cycle)"]


def test_finalization_hands_the_adapter_the_runtimes_end() -> None:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_text(encoding="utf-8"))
    finalize = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "finalize_startup"
    )
    adapters = [
        node for node in ast.walk(finalize)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DreamAdapter"
    ]

    assert len(adapters) == 1
    value = {keyword.arg: keyword.value for keyword in adapters[0].keywords}.get("end_cold_start_fn")
    assert isinstance(value, ast.Attribute) and value.attr == "end_cold_start"
    assert isinstance(value.value, ast.Name) and value.value.id == "runtime"


@pytest.mark.asyncio
async def test_the_proactive_note_states_no_trust_number_and_no_reset() -> None:
    from probos.proactive import ProactiveCognitiveLoop

    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.is_cold_start = True
    runtime.ward_room = None
    runtime.episodic_memory = None
    runtime.bridge_alerts = None
    runtime.event_log = None
    agent = MagicMock()
    agent._orientation_rendered = None  # AD-567g: no orientation, so the BF-034 note is the one shown
    loop = ProactiveCognitiveLoop(interval=60)
    loop.set_runtime(runtime)

    note = (await loop._gather_context(agent, 0.5))["system_note"]

    assert "fresh start" in note.lower()
    assert "0.5" not in note
    assert "system reset" not in note.lower()


def test_the_cold_start_orientation_states_no_trust_number() -> None:
    context = OrientationContext(
        callsign="Vega",
        post="Security Agent",
        department="Security",
        department_chief="Worf",
        reports_to="Worf",
        rank="Ensign",
        ship_name="ProbOS",
        crew_count=12,
        departments=["Security", "Engineering", "Medical", "Science"],
        lifecycle_state="cold_start",
        agent_age_seconds=0.0,
        stasis_duration_seconds=0.0,
        stasis_shutdown_utc="",
        stasis_resume_utc="",
        episodic_memory_count=0,
        has_baseline_trust=True,
        social_verification_available=False,
        manifest=None,
    )

    text = OrientationService(config=SystemConfig()).render_cold_start_orientation(context)

    assert "FIRST DUTY GUIDANCE" in text  # premise: the section that carried the number
    assert "baseline (0.5)" not in text
    assert "role's initial level" in text
```

### 7.2 M2: the predicate, the detector, the announcement

#### 7.2.N New file: src/probos/startup/crew_start.py

```
"""BF-941 (#1324 slice 4d): whether this boot starts a new crew, and the crew's Fresh Start thread.

``is_new_crew_start`` is the one predicate for a new crew: no previous session record (AD-502's
lifecycle state is ``first_boot``, or ``reset``) and an empty episode store. BF-034's cold-start
detector (``startup/dreaming.py``, Phase 5) and the AD-638 boot-camp enrolment
(``startup/finalize.py``, Phase 8) both ask it. It fails warm, because the two errors are not
alike: a false new crew tells agents their memory is empty, while a false warm start omits the
fresh-start notes and, at finalization, the boot camp's activation.

``announce_fresh_start`` posts BF-034's "Fresh Start" thread to All Hands. Finalization calls it
after the AD-435 startup announcement: at Phase 5 the Ward Room does not exist yet.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# AD-502 lifecycle states with no previous session record. Phase 4 writes ``first_boot`` or
# ``stasis_recovery``; Phase 5 writes ``reset`` for a new crew (BF-034).
NEW_CREW_LIFECYCLE_STATES: frozenset[str] = frozenset({"first_boot", "reset"})

FRESH_START_TITLE = "Fresh Start — New Crew"
FRESH_START_BODY = (
    "This crew is starting fresh: there is no previous session record and the episode "
    "store is empty. All crew are being created through the Construct. "
    "Each role's trust starts at its initial level; this is normal initialization, "
    "not a demotion, and trust is built through demonstrated competence. "
    "No previous experiences are available."
)


async def is_new_crew_start(lifecycle_state: str, episodic_memory: Any) -> bool:
    """True when this boot starts a new crew: no previous session record and no episodes.

    Fails warm: a session record, a missing memory, an unreadable count, or an answer whose
    ``get("total")`` is not ``== 0`` (``None``, a list, an int, a mapping without ``total``) is
    not a new crew. Trust is not read: AD-640 gives bridge and chief roles their own priors, and
    the default ``probos reset`` tier deletes the trust store with the session record.
    """
    if lifecycle_state not in NEW_CREW_LIFECYCLE_STATES:
        return False  # BF-941: a session record means this crew has served before
    try:
        stats = await episodic_memory.get_stats()
        return stats.get("total") == 0
    except Exception:  # BF-941: no memory, or an unreadable or malformed answer, is not a new crew
        logger.debug("BF-941: episode count unavailable or malformed; not treated as a new crew", exc_info=True)
        return False


async def announce_fresh_start(ward_room: Any) -> bool:
    """BF-034 / BF-941: post the Fresh Start thread to All Hands; True when it was posted.

    Log-and-degrade: a Ward Room failure is logged and startup continues.
    """
    try:
        all_hands = await ward_room.get_channel_by_name("All Hands")
        if not all_hands:
            return False
        await ward_room.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title=FRESH_START_TITLE,
            body=FRESH_START_BODY,
            author_callsign="Ship's Computer",
            thread_mode="announce",
            max_responders=0,
        )
        return True
    except Exception:  # BF-941: a failed announcement must not fail the boot
        logger.warning("BF-941: the Fresh Start announcement failed; startup continues", exc_info=True)
        return False
```

**P-S1** `src/probos/startup/dreaming.py`

SEARCH:
```
from probos.startup.results import DreamingResult
```
REPLACE:
```
from probos.startup.crew_start import is_new_crew_start
from probos.startup.results import DreamingResult
```

**P-S2** `src/probos/startup/dreaming.py`

SEARCH:
```
    knowledge_store: Any,
    ward_room: Any,
    registry: Any,
```
REPLACE:
```
    knowledge_store: Any,
    registry: Any,
```

**P-S3** `src/probos/startup/dreaming.py`

SEARCH:
```
    expertise_directory: Any = None,  # AD-600: transactive memory
) -> tuple[DreamingResult, bool]:
```
REPLACE:
```
    expertise_directory: Any = None,  # AD-600: transactive memory
    lifecycle_state: str = "",  # BF-941: AD-502's state, the new-crew predicate's first half
) -> tuple[DreamingResult, bool]:
```

**P-S4** `src/probos/startup/dreaming.py`

SEARCH:
```
    # BF-034: Detect cold start (post-reset boot with empty state)
    # BF-069: Don't gate on _knowledge_store — cold start detection must work
    # even if knowledge store is disabled or fails to initialize.
    cold_start = False
    if emergent_detector:
        trust_records = trust_network.raw_scores()
        all_at_prior = all(
            abs(r["alpha"] - config.consensus.trust_prior_alpha) < 0.01
            and abs(r["beta"] - config.consensus.trust_prior_beta) < 0.01
            for r in trust_records.values()
        ) if trust_records else True
        episodes_empty = not episodic_memory
        if all_at_prior and episodes_empty:
            cold_start = True
            emergent_detector.set_cold_start_suppression(300)  # 5 minutes
            logger.info("BF-034: Cold start detected — suppressing trust anomalies for 5 minutes")
        elif runtime and getattr(runtime, '_lifecycle_state', None) == 'stasis_recovery':
            # BF-178: Stasis recovery is not a cold start (trust/memory preserved),
            # but dream history is stale. Clear it so dream_min_history gate re-applies
            # and apply a short suppression window for the first dream cycle.
            emergent_detector.clear_dream_history()
            emergent_detector.set_cold_start_suppression(60)  # 1 minute
            logger.info("BF-178: Stasis recovery — cleared stale dream history, suppressing anomalies for 60s")

    # BF-034: Announce fresh start to crew
    if cold_start and ward_room:
        async def _announce_cold_start():
            try:
                channels = await ward_room.list_channels()
                all_hands = next((c for c in channels if c.channel_type == "ship"), None)
                if all_hands:
                    await ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id="system",
                        title="Fresh Start — System Reset",
                        body=(
                            "This instance has been reset. All crew are being created fresh "
                            "through the Construct. All trust scores are at baseline (0.5) — "
                            "this is normal initialization, not a demotion. Trust will be rebuilt "
                            "through demonstrated competence. Episodic memory has been cleared. "
                            "Previous experiences are not available."
                        ),
                        author_callsign="Ship's Computer",
                        thread_mode="announce",
                        max_responders=0,
                    )
            except Exception:
                logger.debug("Cold-start announcement failed", exc_info=True)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_announce_cold_start())
        except RuntimeError:
            pass
```
REPLACE:
```
    # BF-034: Detect cold start (post-reset boot with empty state)
    # BF-069: Don't gate on _knowledge_store — cold start detection must work
    # even if knowledge store is disabled or fails to initialize.
    # BF-941: a new crew is the one predicate the AD-638 boot camp also asks: no previous
    # session record and an empty episode store. It replaces the memory object's truthiness
    # (true whenever a memory exists) and the every-record-at-the-generic-prior test (false
    # whenever AD-640 gives a bridge or chief role its own prior), either of which kept this branch dead.
    cold_start = False
    if emergent_detector:
        if await is_new_crew_start(lifecycle_state, episodic_memory):
            cold_start = True
            emergent_detector.set_cold_start_suppression(300)  # 5 minutes
            logger.info("BF-034: Cold start detected — suppressing trust anomalies for 5 minutes")
        elif lifecycle_state == "stasis_recovery":
            # BF-178: Stasis recovery is not a cold start (trust/memory preserved),
            # but dream history is stale. Clear it so dream_min_history gate re-applies
            # and apply a short suppression window for the first dream cycle.
            emergent_detector.clear_dream_history()
            emergent_detector.set_cold_start_suppression(60)  # 1 minute
            logger.info("BF-178: Stasis recovery — cleared stale dream history, suppressing anomalies for 60s")

    # BF-034's "Fresh Start" thread is posted at finalization (BF-941,
    # probos.startup.crew_start.announce_fresh_start): the Ward Room is built at Phase 7.
```

**P-R5** `src/probos/runtime.py`

SEARCH:
```
            knowledge_store=self._knowledge_store,
            ward_room=self.ward_room,
            registry=self.registry,
            on_gap_predictions_fn=lambda p: self.dream_adapter.on_gap_predictions(p) if self.dream_adapter else None,
```
REPLACE:
```
            knowledge_store=self._knowledge_store,
            registry=self.registry,
            on_gap_predictions_fn=lambda p: self.dream_adapter.on_gap_predictions(p) if self.dream_adapter else None,
```

**P-R6** `src/probos/runtime.py`

SEARCH:
```
            expertise_directory=self._expertise_directory,  # AD-600
        )
        self.dream_scheduler = dream_result.dream_scheduler
```
REPLACE:
```
            expertise_directory=self._expertise_directory,  # AD-600
            lifecycle_state=self._lifecycle_state,  # BF-941: set at Phase 4 from the session record
        )
        self.dream_scheduler = dream_result.dream_scheduler
```

**P-F2** `src/probos/startup/finalize.py`

SEARCH:
```
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent
```
REPLACE:
```
from probos.utils import format_duration
from probos.crew_utils import is_crew_agent
from probos.startup.crew_start import announce_fresh_start, is_new_crew_start
```

**P-F3** `src/probos/startup/finalize.py`

SEARCH:
```
async def _is_new_crew_start(runtime: Any) -> bool:
    """AD-1270 (#1324): True when this boot starts a new crew, for the AD-638 boot camp.

    A new crew has no previous session record (AD-502's ``_lifecycle_state`` is
    ``first_boot``, or ``reset``) and an empty episode store; a stasis recovery is not one.
    This is not BF-034's ``runtime.is_cold_start``: that flag reads the memory object's
    truthiness, so it is false whenever an ``EpisodicMemory`` exists, and Phase 7 builds
    the coordinator only when a memory object is present (#1324 register R10). Fails warm:
    an unreadable count, or an answer whose ``get("total")`` is not ``== 0`` (``None``, a
    list, an int, a mapping without ``total``), is not a new crew.
    """
    if runtime._lifecycle_state not in ("first_boot", "reset"):
        return False  # AD-1270: a session record means this crew has served before
    try:
        stats = await runtime.episodic_memory.get_stats()
        return stats.get("total") == 0
    except Exception:  # AD-1270: an unreadable or malformed answer is not a new crew
        logger.debug("AD-1270: episode count unavailable or malformed; not treated as a new crew", exc_info=True)
        return False  # AD-1270: an unreadable count is not a new crew
```
REPLACE:
```
async def _is_new_crew_start(runtime: Any) -> bool:
    """AD-1270 (#1324): True when this boot starts a new crew, for the AD-638 boot camp.

    BF-941: asks ``probos.startup.crew_start.is_new_crew_start``, the predicate BF-034's
    Phase 5 detector also asks: no previous session record (AD-502's ``_lifecycle_state`` is
    ``first_boot``, or ``reset``) and an empty episode store; a stasis recovery is not one.
    It asks again rather than reading ``runtime.is_cold_start``, a prompt-note window that
    closes at the first dream cycle. The two answers can differ: an episode stored between
    Phase 5 and here skips the boot camp. Fails warm.
    """
    return await is_new_crew_start(runtime._lifecycle_state, getattr(runtime, "episodic_memory", None))
```

**P-F4** `src/probos/startup/finalize.py`

SEARCH:
```
                    elif runtime._lifecycle_state == "first_boot":
                        title = "System Online — First Activation"
```
REPLACE:
```
                    elif runtime._lifecycle_state in ("first_boot", "reset"):  # BF-941: Phase 5 marks a new crew "reset"
                        title = "System Online — First Activation"
```

**P-F5** `src/probos/startup/finalize.py`

SEARCH:
```
        except Exception:
            logger.debug("Startup announcement failed", exc_info=True)

    # AD-573: Restore working memory from stasis
```
REPLACE:
```
        except Exception:
            logger.debug("Startup announcement failed", exc_info=True)

    # BF-034 / BF-941: the "Fresh Start" thread for a new crew, after the AD-435 announcement.
    # Moved from Phase 5 (startup/dreaming.py), where the Ward Room did not exist yet. Its gate
    # is the BF-102 auto-welcome's below with runtime._cold_start negated.
    if runtime.ward_room and runtime._cold_start:
        await announce_fresh_start(runtime.ward_room)

    # AD-573: Restore working memory from stasis
```

**P-B1** `docs/development/architecture-baseline.yaml`

SEARCH:
```
  review_by: AD-1270h closeout
- category: unowned-task
  key: probos.startup.dreaming::init_dreaming
  callee: loop.create_task
  count: 1
  disposition: debt
  owner: AD-1270h
  rationale: 'Bare-statement task creation: the reference is discarded at the statement, so nothing awaits, cancels, or drains it.'
  review_by: AD-1270h closeout
```
REPLACE:
```
  review_by: AD-1270h closeout
```

### 7.3 M2: tests

**P-T1** `tests/test_ad1324_srp_layout.py` (the token is replaced by measurement, §7.4)

SEARCH:
```
# The LF-normalised sha256 of the reviewed baseline. AD-1270 (#1324) slice 4b lowered one row
# (unowned-task, probos.startup.dreaming::init_dreaming, count 2 -> 1): the dead activation
# block's loop.create_task left dreaming.py, and the architecture checker requires the row to
# follow in the same commit. The pin before slice 4b (set by AD-1324, b513580b) was
# 62ceb51a9ebe031ad272a4396924d265fa48e9d20c6934371427322d750c87d1.
ARCHITECTURE_BASELINE_SHA256 = "c2ee53af26ff8a4ca97a971a2e3f6b2aba7450213fc48bbd83036078d2aff70f"
```
REPLACE:
```
# The LF-normalised sha256 of the reviewed baseline. AD-1270 (#1324) slice 4b lowered one row
# (unowned-task, probos.startup.dreaming::init_dreaming, count 2 -> 1): the dead activation
# block's loop.create_task left dreaming.py, and the architecture checker requires the row to
# follow in the same commit. The pin before slice 4b (set by AD-1324, b513580b) was
# 62ceb51a9ebe031ad272a4396924d265fa48e9d20c6934371427322d750c87d1.
# BF-941 (#1324 slice 4d) deleted that row (count 1 -> 0): the Fresh Start announcement's
# loop.create_task left dreaming.py for an awaited call at finalization. The pin before BF-941
# was c2ee53af26ff8a4ca97a971a2e3f6b2aba7450213fc48bbd83036078d2aff70f.
ARCHITECTURE_BASELINE_SHA256 = "__BF941_MEASURED_SHA256__"
```

**P-T2** `tests/test_ad1326_startup_wiring.py`

SEARCH:
```
    """The one ``TrustNetwork`` method ``init_dreaming`` reads: a boot with no trust records."""
```
REPLACE:
```
    """A boot with no trust records. Since BF-941, ``init_dreaming``'s cold-start detector reads none."""
```

**P-T3** `tests/test_ad1326_startup_wiring.py`

SEARCH:
```
            knowledge_store=None,
            ward_room=None,
            registry=None,
```
REPLACE:
```
            knowledge_store=None,
            registry=None,
```

**P-T4** `tests/test_new_crew_auto_welcome.py`

SEARCH:
```
        assert len(welcome_calls) == 1
        call_kwargs = welcome_calls[0].kwargs
        assert "Kira" in call_kwargs["body"]
```
REPLACE:
```
        assert len(welcome_calls) == 1
        call_kwargs = welcome_calls[0].kwargs
        assert "Kira" in call_kwargs["body"]
        # BF-941: not a new crew, so no Fresh Start thread
        assert not any(c.kwargs.get("title") == "Fresh Start — New Crew" for c in calls)
```

**P-T5** `tests/test_new_crew_auto_welcome.py`

SEARCH:
```
        runtime._cold_start = True  # Cold start!
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "first_boot"
```
REPLACE:
```
        runtime._cold_start = True  # Cold start!
        runtime.registry = registry
        runtime._started = False
        runtime._lifecycle_state = "reset"  # BF-941: Phase 5 marks a new crew "reset"
```

**P-T6** `tests/test_new_crew_auto_welcome.py`

SEARCH:
```
        # The only create_thread call should be the startup announcement, not auto-welcome
        for call in ward_room.create_thread.call_args_list:
            if hasattr(call, 'kwargs'):
                assert call.kwargs.get("title") != "New Crew Aboard"
```
REPLACE:
```
        # BF-941: a new crew gets the AD-435 first-activation title and the Fresh Start thread,
        # not the auto-welcome
        titles = [call.kwargs.get("title") for call in ward_room.create_thread.call_args_list]
        assert "New Crew Aboard" not in titles
        assert titles.count("System Online — First Activation") == 1
        assert titles.count("Fresh Start — New Crew") == 1
```

**P-T7** `tests/test_ad1270_boot_camp_lifecycle.py`

SEARCH:
```
    # AD-1270 A1: is_cold_start is False, as production reports it whenever a coordinator exists
    # (register R10); a new crew is no session record (first_boot) and an empty episode store.
```
REPLACE:
```
    # AD-1270 A1 / BF-941: the boot camp asks the shared new-crew predicate itself and never reads
    # is_cold_start; a new crew is no session record (first_boot) and an empty episode store.
```

**P-T8** `tests/test_ad1270_boot_camp_repair_a1.py`

SEARCH:
```
        assert memory, "premise: a live memory object is truthy, so BF-034's `not episodic_memory` reads it as warm"
```
REPLACE:
```
        assert memory, "premise: a live memory object is truthy, which BF-034's old `not episodic_memory` read as warm (BF-941)"
```

#### 7.3.N New file: tests/test_bf941_cold_start_detector.py

```
"""BF-941 (#1324 slice 4d) M2: BF-034's cold-start detector asks the boot camp's new-crew predicate.

The detector tested the memory object's truthiness (true whenever a memory exists) and every
trust record against the generic prior (false whenever AD-640 gives a bridge or chief role its
own), either of which kept its branch from running (#1324 register 4b-R10). It now asks
``probos.startup.crew_start.is_new_crew_start``, which the AD-638 boot camp also asks. Its
Fresh Start thread, posted at Phase 5 where the Ward Room does not exist yet, moved to
finalization. Phase 5 runs here as ``runtime.start()`` runs it (the AD-1326 harness), with
AD-640 role priors in a real ``TrustNetwork``.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.procedure_store import ProcedureStore
from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.dream_adapter import DreamAdapter
from probos.runtime import ProbOSRuntime
from probos.startup import dreaming
from probos.startup.dreaming import init_dreaming

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_TITLE = "Fresh Start — New Crew"


def _crew_start() -> ModuleType:
    """Imported per case, so that each case fails by name before the module exists."""
    return importlib.import_module("probos.startup.crew_start")


class _Stats:
    """The one read the predicate makes of an episodic memory."""

    def __init__(self, total: int = 0, error: Exception | None = None) -> None:
        self.total = total
        self.error = error

    async def get_stats(self) -> dict[str, int]:
        if self.error is not None:
            raise self.error
        return {"total": self.total}


def _memory(total: int) -> MagicMock:
    """A memory object as Phase 5 sees one: truthy, and answering ``get_stats``."""
    memory = MagicMock()
    memory.get_stats = AsyncMock(return_value={"total": total})
    return memory


def _trust_with_role_priors() -> TrustNetwork:
    """AD-640's tiers at their defaults: a bridge and a chief record above the generic prior."""
    trust = TrustNetwork()
    trust.create_with_prior("bridge-0", 4.5, 1.0)
    trust.create_with_prior("chief-0", 3.0, 1.0)
    trust.create_with_prior("crew-0", 2.0, 2.0)
    return trust


async def _idle() -> None:
    await asyncio.sleep(3600)


async def _process(_text: str, **_kwargs: Any) -> None:
    return None


@asynccontextmanager
async def _phase_five(tmp_path: Path, *, lifecycle: str, memory: Any) -> AsyncIterator[bool]:
    """``init_dreaming`` as ``runtime.start()`` calls it; its background tasks are stopped afterwards."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    result = None
    try:
        result, cold_start = await init_dreaming(
            config=SystemConfig(),
            trust_network=_trust_with_role_priors(),
            hebbian_router=MagicMock(),
            episodic_memory=memory,
            pool_scaler=None,
            knowledge_store=None,
            registry=None,
            on_gap_predictions_fn=lambda _predictions: None,
            on_contradictions_fn=lambda _contradictions: None,
            on_post_dream_fn=lambda _report: None,
            on_pre_dream_fn=lambda: None,
            on_post_micro_dream_fn=lambda _report: None,
            process_natural_language_fn=_process,
            periodic_flush_loop_fn=_idle,
            refresh_emergent_detector_roster_fn=lambda: None,
            emit_event_fn=lambda _event_type, _payload: None,
            llm_client=MagicMock(),
            procedure_store=store,
            lifecycle_state=lifecycle,
        )
        yield cold_start
    finally:
        if result is not None:
            await result.dream_scheduler.stop()
            await result.task_scheduler.stop()
            result.flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await result.flush_task
        await store.stop()


def _runtime(lifecycle: str) -> ProbOSRuntime:
    """A runtime holding only what the fresh-start window reads; nothing is booted."""
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime.config = SystemConfig()
    runtime._cold_start = False
    runtime._cold_start_until = 0.0
    runtime._lifecycle_state = lifecycle
    return runtime


def _adapter(runtime: ProbOSRuntime) -> DreamAdapter:
    """A dream adapter wired as finalization wires it."""
    adapter = DreamAdapter(
        dream_scheduler=None,
        emergent_detector=None,
        episodic_memory=None,
        knowledge_store=None,
        hebbian_router=MagicMock(),
        trust_network=MagicMock(),
        event_emitter=lambda *_args, **_kwargs: None,
        self_mod_pipeline=None,
        bridge_alerts=None,
        ward_room=None,
        registry=MagicMock(),
        event_log=None,
        config=SystemConfig(),
        pools={},
        end_cold_start_fn=runtime.end_cold_start,
    )
    adapter._cold_start = runtime._cold_start  # finalize.py copies the runtime's flag the same way
    return adapter


def _calls_by_enclosing_function(name: str) -> set[str]:
    """``<path>::<innermost enclosing function>`` for every call of ``name`` under ``src/probos``."""
    found: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if name not in text:
            continue
        tree = ast.parse(text)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) != name:
                continue
            owner = parents.get(node)
            while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(owner)
            found.add(f"{path.relative_to(_SRC).as_posix()}::{owner.name if owner else '<module>'}")
    return found


# --- the predicate -------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "memory", "expected"),
    [
        ("first_boot", _Stats(0), True),
        ("reset", _Stats(0), True),
        ("stasis_recovery", _Stats(0), False),
        ("restart", _Stats(0), False),
        ("", _Stats(0), False),
        ("first_boot", _Stats(4), False),
        ("first_boot", None, False),
        ("first_boot", _Stats(error=OSError("collection unavailable")), False),
    ],
    ids=["first-boot", "reset", "stasis-recovery", "restart", "no-lifecycle", "episodes-kept", "no-memory", "count-raises"],
)
async def test_a_new_crew_is_no_session_record_and_no_episodes(lifecycle: str, memory: Any, expected: bool) -> None:
    assert await _crew_start().is_new_crew_start(lifecycle, memory) is expected


def test_the_detector_and_the_boot_camp_ask_the_one_predicate() -> None:
    assert _calls_by_enclosing_function("is_new_crew_start") == {
        "startup/dreaming.py::init_dreaming",
        "startup/finalize.py::_is_new_crew_start",
    }


# --- the detector, through Phase 5 -----------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "total", "cold"),
    [("first_boot", 0, True), ("stasis_recovery", 0, False), ("first_boot", 3, False), ("restart", 0, False)],
    ids=["new-crew", "stasis-recovery", "episodes-kept", "restart"],
)
async def test_the_detector_asks_the_new_crew_predicate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, lifecycle: str, total: int, cold: bool
) -> None:
    caplog.set_level(logging.INFO, logger="probos.startup.dreaming")
    memory = _memory(total)
    assert memory, "premise: a memory object is truthy, which BF-034's `not episodic_memory` read as warm"
    priors = _trust_with_role_priors().raw_scores().values()
    generic = SystemConfig().consensus.trust_prior_alpha
    assert any(abs(r["alpha"] - generic) >= 0.01 for r in priors), "premise: AD-640 role priors differ from the generic prior"

    async with _phase_five(tmp_path, lifecycle=lifecycle, memory=memory) as cold_start:
        pass

    assert cold_start is cold
    messages = [r.getMessage() for r in caplog.records if r.name == "probos.startup.dreaming"]
    assert sum(m.startswith("BF-034: Cold start detected") for m in messages) == (1 if cold else 0)
    assert sum(m.startswith("BF-178: Stasis recovery") for m in messages) == (1 if lifecycle == "stasis_recovery" else 0)
    assert memory.get_stats.await_count == (1 if lifecycle in ("first_boot", "reset") else 0)


def test_the_fresh_start_thread_left_phase_five() -> None:
    parameters = inspect.signature(init_dreaming).parameters

    assert "ward_room" not in parameters
    assert parameters["lifecycle_state"].default == ""
    assert "create_thread" not in inspect.getsource(dreaming)


# --- the announcement ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_fresh_start_thread_goes_to_all_hands() -> None:
    ward_room = AsyncMock()
    ward_room.get_channel_by_name = AsyncMock(return_value=SimpleNamespace(id="ch-1", name="All Hands"))
    ward_room.create_thread = AsyncMock()

    assert await _crew_start().announce_fresh_start(ward_room) is True

    ward_room.get_channel_by_name.assert_awaited_once_with("All Hands")
    kwargs = ward_room.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "ch-1"
    assert kwargs["title"] == _TITLE
    assert kwargs["author_id"] == "system"
    assert kwargs["thread_mode"] == "announce"
    assert kwargs["max_responders"] == 0
    body = kwargs["body"]
    assert "starting fresh" in body
    assert "0.5" not in body
    assert "has been reset" not in body
    assert "has been cleared" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "no-all-hands"])
async def test_a_ward_room_failure_does_not_stop_startup(failure: str) -> None:
    ward_room = AsyncMock()
    if failure == "raises":
        ward_room.get_channel_by_name = AsyncMock(side_effect=RuntimeError("ward room down"))
    else:
        ward_room.get_channel_by_name = AsyncMock(return_value=None)
    ward_room.create_thread = AsyncMock()

    assert await _crew_start().announce_fresh_start(ward_room) is False
    ward_room.create_thread.assert_not_awaited()


# --- the seam: detector -> runtime -> agent note -> first dream ------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "total", "fresh"),
    [("first_boot", 0, True), ("stasis_recovery", 0, False), ("first_boot", 2, False)],
    ids=["new-crew", "stasis-recovery", "episodes-kept"],
)
async def test_a_new_crew_reaches_the_agent_note_until_the_first_dream(
    tmp_path: Path, lifecycle: str, total: int, fresh: bool
) -> None:
    async with _phase_five(tmp_path, lifecycle=lifecycle, memory=_memory(total)) as cold_start:
        pass
    runtime = _runtime(lifecycle)
    runtime.adopt_new_crew_start(cold_start)  # what runtime.start() does with Phase 5's answer
    agent = SimpleNamespace(_runtime=runtime)

    assert ("fresh start" in CognitiveAgent._sensorium_cold_start_note(agent, {}).lower()) is fresh

    _adapter(runtime).on_post_dream(None)

    assert runtime.is_cold_start is False
    assert CognitiveAgent._sensorium_cold_start_note(agent, {}) == ""
```

### 7.4 Measured value (M2; no pair)

After P-B1, compute the baseline's LF-normalised sha256 exactly as `test_architecture_baseline_is_byte_identical_to_the_reviewed_base` does (read the bytes, replace `b"\r\n"` with `b"\n"`, `hashlib.sha256(...).hexdigest()`). Replace `__BF941_MEASURED_SHA256__` in P-T1 with it and record the value in the M2 commit message.

## 8. Tracking (M3's commit)

**Head constraint:** neither head has a lifecycle keyword (`gen_ad_ledger.py` `_STATUS_PATTERNS`) in its first 120 characters.

**P-U1** `PROGRESS.md`

SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-941 (2026-10-28), #1324 slice 4d -- BF-034's cold-start detector asks the boot camp's new-crew predicate, and its notes end at the first dream.** BF-034's detector could not fire on a boot with an episodic memory. It tested the episodic-memory object's truthiness, which holds whenever a memory exists, and required every trust record at the generic prior, which AD-640's bridge and chief priors break (#1324 register 4b-R10). It now asks `probos.startup.crew_start.is_new_crew_start`, the predicate the AD-638 boot camp asks at finalization: no previous session record and an empty episode store, failing warm. At the next new-crew start the detector's readers therefore switch on. Trust-anomaly, cooperation-cluster and dream-anomaly detection are suppressed for five minutes. AD-502's lifecycle state becomes `reset`. Agents' prompts carry the fresh-start note. All Hands gets a "Fresh Start — New Crew" thread instead of the "New Crew Aboard" welcome, beside the unchanged "System Online — First Activation" announcement. The Fresh Start thread had been posted at Phase 5, before the Ward Room exists; it is now awaited at finalization, so the unowned task and its architecture-baseline row are gone. `runtime.is_cold_start` was never cleared, because the dream adapter cleared only its own copy. It now closes at the first full dream cycle, through `runtime.end_cold_start`, or after `orientation.orientation_window_seconds`, whichever is first. The proactive note, the Fresh Start body and the cold-start orientation no longer state a 0.5 trust baseline, or a reset that a first install did not have. `init_dreaming` takes `lifecycle_state` and no longer takes `ward_room`. The contract is `prompts/bf-941-cold-start-detector-and-session-flag.md`.

```

**P-U2** `DECISIONS.md`

SEARCH:
```
### AD-1270 (#1324) -- the boot-camp tail: AD-509's tracker and AD-638's phases 2 and 3 deleted; AD-683's snapshot keyed on enrolment (2026-10-28)
```
REPLACE:
```
### BF-941 (#1324 slice 4d) -- BF-034's cold-start detector asks the new-crew predicate; the fresh-start window ends at the first dream or the orientation window (2026-10-28)

**Decision.** One predicate for a new crew, `probos.startup.crew_start.is_new_crew_start(lifecycle_state, episodic_memory)`: no previous session record (AD-502 `first_boot` or `reset`) and an empty episode store, failing warm. BF-034's Phase 5 detector and the AD-638 boot camp's `_is_new_crew_start` both ask it, and the detector drops its trust half. `runtime.is_cold_start` opens once at Phase 5 (`adopt_new_crew_start`). It closes at the first full dream cycle (`end_cold_start`, called by the dream adapter) or after `orientation.orientation_window_seconds`, whichever is first. BF-034's Fresh Start thread moves from Phase 5 to finalization, awaited after the AD-435 announcement, which titles a `reset` boot as a first activation. Agent-facing and crew-facing text states no trust number and no reset. **Why.** Each of the detector's two halves was false on a boot with an episodic memory and an AD-640 bridge or chief prior (the memory object's truthiness; AD-640 role priors), and the Ward Room it announced through is built at Phase 7. The AD-517 extraction left the session flag's clear on the adapter's copy, so a repaired detector would have kept "no prior memories" in agents' prompts for the session. The trust half adds no safety: the default `probos reset` tier deletes the trust store with the session record, and a crash-orphaned trust store beside an empty episode store is still a crew with no memories. A dream needs 120 s with no Captain request and may run before finalization wires the adapter, so a dream-only bound could last the session. **Effect.** At the next new-crew start the readers switch on: five minutes of anomaly suppression, the `reset` label, the fresh-start note, and the Fresh Start thread replacing the auto-welcome. A stasis recovery and a boot with episodes are unchanged. **Captain.** Told; nothing parked. He may change the window (it follows the orientation window), restore the auto-welcome beside the Fresh Start thread, or remove the agent notes, which overlap the no-memories flag. **Rejected.** The boot camp reading Phase 5's flag (the window closes, and it couples enrolment to a prompt note). Importing the predicate from `finalize.py` into Phase 5. Keeping the trust half against role priors. A dream-only bound, a boot-camp bound (up to two hours), and a new config field for the window.

### AD-1270 (#1324) -- the boot-camp tail: AD-509's tracker and AD-638's phases 2 and 3 deleted; AD-683's snapshot keyed on enrolment (2026-10-28)
```

`docs/development/roadmap.md` is not updated: its Bug Tracker table is for BFs filed but deliberately not fixed. Parent checklist (the orchestrator, on #1324): mark row 4b-R10 built by BF-941, with the commits and the receipt.

## 9. What this does NOT change

- The BF-178 stasis branch's behaviour: clear the dream history and suppress for 60 s. Only its source of the lifecycle state changes, from `runtime` to the explicit argument.
- `EmergentDetector` (including `set_cold_start_suppression`'s docstring mention of 0.5), `EpisodicMemory.get_stats`, the AD-638 coordinator, `_activate_boot_camp_on_cold_start`, slice 5's receipts, and the boot-camp enrolment rule (4b's `_is_new_crew_start` cases pass unchanged).
- The sensorium and Ward Room note text (`cognitive_agent.py`), the no-memories flag, and `analyze.py` and `compose.py`.
- `--fresh` (it relabels `reset` after finalization; 4d-R2), AD-435's unreachable `restart` branch (4d-R1), and `agent_onboarding.py` passing `trust_score=0.5` into the orientation context (4d-R3).
- No config field, no `EventType`, no persisted schema.

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline of M1's and M2's focused lists passes; run on the Captain's Windows host)

Paths are relative to `src/probos/`, as in 4c's rows. `runtime.py` is `src/probos/runtime.py`, not `sop/runtime.py`. Run with `--tests` set to the union of M1's and M2's focused lists. No row is claimed equivalent.

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| W-1 | M1 | `runtime.py` | `return self._cold_start and time.monotonic() < self._cold_start_until` | `return self._cold_start` | `test_the_window_closes_by_time_without_a_dream` |
| W-2 | M1 | `runtime.py` | `self._cold_start_until = time.monotonic() + self.config.orientation.orientation_window_seconds` | `self._cold_start_until = float("inf")` | `test_the_window_closes_by_time_without_a_dream` |
| W-3 | M1 | `runtime.py` | `self._lifecycle_state = "reset"` | `pass` | `test_phase_fives_answer_opens_the_window_and_marks_a_new_crew_reset[new-crew]`, `test_the_window_closes_by_time_without_a_dream` |
| W-4 | M1 | `runtime.py` | `self._cold_start = False` | `pass` | `test_the_first_dream_cycle_ends_the_window_once`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[new-crew]` |
| W-5 | M1 | `dream_adapter.py` | `self._end_cold_start_fn("first dream cycle")` | `pass` | `test_the_first_dream_cycle_ends_the_window_once`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[new-crew]` |
| W-6 | M1 | `startup/finalize.py` | `end_cold_start_fn=runtime.end_cold_start,  # BF-941: the first dream cycle ends the fresh-start window` | `end_cold_start_fn=None,` | `test_finalization_hands_the_adapter_the_runtimes_end` |
| W-7 | M1 | `proactive.py` | `"normal initialization, not a demotion. Build trust through demonstrated competence. "` | `"normal initialization, not a demotion. All trust scores are at baseline (0.5). "` | `test_the_proactive_note_states_no_trust_number_and_no_reset` |
| W-8 | M1 | `cognitive/orientation.py` | `"- Build relationships through the Ward Room. Your trust starts at your role's initial "` | `"- Build relationships through the Ward Room. Your trust starts at baseline (0.5) "` | `test_the_cold_start_orientation_states_no_trust_number` |
| N-1 | M2 | `startup/crew_start.py` | `if lifecycle_state not in NEW_CREW_LIFECYCLE_STATES:` | `if False:` | `test_a_new_crew_is_no_session_record_and_no_episodes[stasis-recovery]`, `[restart]`, `[no-lifecycle]`, `test_the_detector_asks_the_new_crew_predicate[stasis-recovery]`, `[restart]`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[stasis-recovery]` |
| N-2 | M2 | `startup/crew_start.py` | `return stats.get("total") == 0` | `return True` | `test_a_new_crew_is_no_session_record_and_no_episodes[episodes-kept]`, `test_the_detector_asks_the_new_crew_predicate[episodes-kept]`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[episodes-kept]`, `test_a_new_crew_needs_no_session_record_and_no_episodes[episodes]` |
| N-3 | M2 | `startup/crew_start.py` | `NEW_CREW_LIFECYCLE_STATES: frozenset[str] = frozenset({"first_boot", "reset"})` | `NEW_CREW_LIFECYCLE_STATES: frozenset[str] = frozenset({"first_boot"})` | `test_a_new_crew_is_no_session_record_and_no_episodes[reset]` (both files) |
| N-4 | M2 | `startup/dreaming.py` | `if await is_new_crew_start(lifecycle_state, episodic_memory):` | `if not episodic_memory:` | `test_the_detector_asks_the_new_crew_predicate[new-crew]`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[new-crew]` |
| N-5 | M2 | `startup/dreaming.py` | same | `if await is_new_crew_start(lifecycle_state, episodic_memory) and all(abs(r["alpha"] - config.consensus.trust_prior_alpha) < 0.01 for r in trust_network.raw_scores().values()):` | `test_the_detector_asks_the_new_crew_predicate[new-crew]`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[new-crew]` |
| N-6 | M2 | `startup/dreaming.py` | `elif lifecycle_state == "stasis_recovery":` | `elif False:` | `test_the_detector_asks_the_new_crew_predicate[stasis-recovery]` |
| N-7 | M2 | `startup/finalize.py` | `return await is_new_crew_start(runtime._lifecycle_state, getattr(runtime, "episodic_memory", None))` | `return runtime._lifecycle_state in ("first_boot", "reset")` | `test_the_detector_and_the_boot_camp_ask_the_one_predicate`, `test_a_new_crew_needs_no_session_record_and_no_episodes[episodes]`, `[count-raises]`, `test_a_malformed_stats_answer_is_not_a_new_crew[none]` |
| N-8 | M2 | `startup/finalize.py` | `await announce_fresh_start(runtime.ward_room)` | `pass` | `TestAutoWelcome::test_auto_welcome_skipped_on_cold_start` |
| N-9 | M2 | `startup/finalize.py` | `if runtime.ward_room and runtime._cold_start:` | `if runtime.ward_room:` | `TestAutoWelcome::test_auto_welcome_posts_for_new_crew` |
| N-10 | M2 | `startup/finalize.py` | `elif runtime._lifecycle_state in ("first_boot", "reset"):  # BF-941: Phase 5 marks a new crew "reset"` | `elif runtime._lifecycle_state == "first_boot":` | `TestAutoWelcome::test_auto_welcome_skipped_on_cold_start` |
| N-11 | M2 | `startup/crew_start.py` | `"Each role's trust starts at its initial level; this is normal initialization, "` | `"All trust scores are at baseline (0.5); this is normal initialization, "` | `test_the_fresh_start_thread_goes_to_all_hands` |
| N-12 | M2 | `startup/crew_start.py` | `logger.warning("BF-941: the Fresh Start announcement failed; startup continues", exc_info=True)` | `raise` | `test_a_ward_room_failure_does_not_stop_startup[raises]` |
| N-13 | M2 | `startup/dreaming.py` | `if await is_new_crew_start(lifecycle_state, episodic_memory):` | `if False:` | `test_the_detector_asks_the_new_crew_predicate[new-crew]`, `test_a_new_crew_reaches_the_agent_note_until_the_first_dream[new-crew]` |

## 11. Verified Against Codebase (2026-10-28, on `ed253049`)

```
Read startup/dreaming.py:1-38 (imports; :25 results import; :33 logger), :36-66 (signature; :44 ward_room; :61 expertise_directory),
  :165-211 (if episodic_memory: engine + DreamScheduler), :224-249 (EmergentDetector unconditional; :246 phase tag reads runtime),
  :251-303 (BF-034 block: :256-261 all_at_prior, :262 `episodes_empty = not episodic_memory`, :267 BF-178 elif,
  :276 `if cold_start and ward_room`, :301 loop.create_task), :357 flush_task, :372 return
Read runtime.py:586-593 (:591 _cold_start), :1236-1243 (:1241), :2238-2241 (is_cold_start), :2340-2365 (:2357 fresh_boot),
  :2975-2989 (:2987 lifecycle from Phase 4), :3140-3219 (Phase 5 call :3162-3186, :3171-3175 lambdas `if self.dream_adapter`,
  :3207-3209 adoption), :3580-3605 (:3593 enroll_boot_crew, :3598 finalize, :3605 dream_adapter); :229 logger
Grep runtime.py `self\.ward_room\b.*=|ward_room: `   :507 annotation, :1091 `= None  # Initialized in start()`, :3281 Phase 7
Grep runtime.py `# Phase \d`   Phase 5 :3159, Phase 6 :3211, Phase 7 :3255, Phase 8 :3595
Read startup/cognitive_services.py:282-301 (:291-292 episodic_memory.start, not in a try), :577-596 (lifecycle first_boot/stasis_recovery)
Read __main__.py:586-599 (--fresh = restore_on_boot False), :695-717 (BF-141 session record), :805-822 (--fresh sets reset after boot),
  :2640-2679 (RESET_TIERS: tier 2 deletes session_last.json, chroma.sqlite3, trust.db ...)
Read startup/finalize.py:860-952 (:904-922 _is_new_crew_start), :6220-6245 (DreamAdapter + :6233 copy), :6355-6517
  (AD-435 :6369-6407, no reset branch; BF-102 auto-welcome :6486-6517 guarded `not runtime._cold_start`)
git diff 8cb4bad5 HEAD -- src/probos/startup/finalize.py   slice 5: imports after :21, receipts at :4180, :4223-4249, :6450-6460, :6852-6858
git diff -U1 8cb4bad5 HEAD -- DECISIONS.md   slice 5 inserts before 4c's heading
Read dream_adapter.py:6-14 (future annotations, Callable), :60-160 (ctor keyword-only :72-94; :113-116; on_post_dream :140-145), :169-205
Read cognitive/cognitive_agent.py:1155-1166, :1272-1282, :9245-9278 (no-memories flag; cold-start note), :9365-9375 (lifecycle != "reset"),
  :10903-10910 (BF-102 WR note), :11065-11076 (system_note in proactive think); :1333 self._runtime
Read proactive.py:1735-1761 (BF-034 note with "baseline (0.5)"; AD-1077), :1790-1814; Grep `"lifecycle":` :2719-2723
Grep cognitive/sub_tasks analyze.py:267-270, compose.py:567-569 (_cold_start_note)
Read cognitive/emergent_detector.py:254-306 (set_cold_start_suppression covers trust, clusters, dreams), :708-722
Read tiered_trust.py:40-86; Grep agent_onboarding.py:255-267 (AD-640 at wire_agent); config_models/crew.py:66-80 (enabled True; bridge 4.5/1.0; chief 3.0/1.0)
Read config_models/knowledge.py:365-375 (orientation_window_seconds 600.0); config.py:4040 SystemConfig.orientation
Read cognitive/dreaming.py:3136-3171 (_last_activity_time = monotonic at construction), :3318-3365 (full dream: idle >= 120 and interval >= 600)
Grep config_models/cognition.py:100-101 (idle 120, interval 600); runtime.py:5703-5704, :6092-6093 (only record_activity callers)
Read cognitive/episodic.py:4282-4289 (get_stats: {"total": 0} when no collection)
Read cognitive/orientation.py:400-412 ("Your trust starts at baseline (0.5)")
Read tests: test_bf034_cold_start.py (whole); test_ad1326_startup_wiring.py:1-88; test_new_crew_auto_welcome.py:180-240, 240-305, 360-369, 425-434;
  test_ad1270_boot_camp_repair_a1.py:1-8, 250-332; test_ad1270_boot_camp_lifecycle.py:348-372; test_ad1077_group_chat_coaching.py:80-106;
  test_orientation.py:20-78, 148-161; test_ad1324_srp_layout.py:1-64; test_ad641d_deliberation.py:250-322 (skipped); test_bf235:86-99; conftest.py:376-489 (mock)
Read docs/development/architecture-baseline.yaml:1-22, 1155-1172 (the init_dreaming row is the last); scripts/check_architecture_principles.py:15-54 (stale row fails)
Read scripts/gen_ad_ledger.py:110-139 (head window 120; status keywords)
Grep activation_receipts.py cold|_lifecycle_state|is_new_crew   :105, :119 docstring/label only (does not read the detector)
```

## Absence Verified (2026-10-28)

```
CLAIM: nothing clears runtime._cold_start after it is set
RUN:   Grep `_cold_start\b|is_cold_start|cold_start` src/probos
FOUND: runtime.py:591, :1241, :2239-2241, :3207-3208 (boot writes); dream_adapter.py:116, :143-144 (its own copy);
       finalize.py:6233 (copy), :6488 (read); readers cognitive_agent.py:9271, :10905; proactive.py:1751
HOLDS: yes

CLAIM: the Ward Room does not exist at Phase 5
RUN:   Grep `self\.ward_room\b.*=|ward_room: ` src/probos/runtime.py; Grep `# Phase \d` runtime.py
FOUND: :1091 None, :3281 assigned after Phase 7 (:3255); Phase 5 call at :3162
HOLDS: yes

CLAIM: no src code produces lifecycle "restart"
RUN:   Grep `_lifecycle_state\s*=|lifecycle_state\s*=\s*"restart"|"reset"` src/probos; Read cognitive_services.py:583-596
FOUND: runtime.py:1555 (first_boot), :2987 (Phase 4 value), :3209 (reset); __main__.py:822 (reset); cognitive_services first_boot/stasis_recovery only
HOLDS: yes (AD-435's restart branch is unreachable; 4d-R1)

CLAIM: init_dreaming has two callers and uses ward_room only in the announcer
RUN:   Grep `init_dreaming\(` (*.py); Grep `ward_room|asyncio\.` src/probos/startup/dreaming.py
FOUND: runtime.py:3162; tests/test_ad1326_startup_wiring.py:46; ward_room at :44, :276, :279, :282 only
HOLDS: yes

CLAIM: no test or UI pins the rewritten texts or the moved title
RUN:   Grep `baseline \(0\.5\)|after a system reset|Episodic memory has been cleared|has been reset|Cold start period ended` (tests, src, ui/src);
       Grep `Fresh Start|System Reset|New Crew Aboard` (ui/src, src, docs, config); Grep `Build relationships through the Ward Room|FIRST DUTY GUIDANCE`
FOUND: src sites being rewritten; tests/test_temporal_context.py:406 (a local literal, not the source); test_orientation.py:159 (section header only)
HOLDS: yes

CLAIM: nothing else reads _newly_commissioned (the auto-welcome is its only reader)
RUN:   Grep `_newly_commissioned` src/probos
FOUND: agent_onboarding.py:350 (set); finalize.py:6492, :6515
HOLDS: yes

CLAIM: every finalize_startup test runtime is a MagicMock (so runtime.end_cold_start resolves)
RUN:   Grep `await finalize_startup\(` tests; Read each runtime construction
FOUND: test_ad641d_deliberation (MagicMock, skipped), test_bf235 (MagicMock), test_new_crew_auto_welcome x4 (MagicMock)
HOLDS: yes

CLAIM: BF-941 is unused
RUN:   git log --all --oneline -i --grep=BF-941 --grep=BF-940; gh issue list --state all --search "BF-941 in:title"; Glob prompts/bf-94*.md
FOUND: none; []; none
HOLDS: yes (the orchestrator's full enumeration in live-and-bf-evidence-4d.md section 2 gives BF-940 as the highest)
```

## Not verified (the orchestrator verifies by running)

- Every predicted count and failure mode in §4 and §6, and every kill in §10.
- That `s6_census.py` resolves `runtime.py` to `src/probos/runtime.py` (`sop/runtime.py` also exists).
- That a real `TrustNetwork()` with three `create_with_prior` records passes through `init_dreaming` as the AD-1326 stub did.
- That `ProbOSRuntime.__new__` plus `config`, `_cold_start`, `_cold_start_until` and `_lifecycle_state` is all the property and the two methods read (by reading, yes).
- That `EpisodicMemory.start()` cannot leave `_collection` `None` without raising. If it can, `get_stats` answers `{"total": 0}` and a first boot with an unreadable store reads as a new crew.
- That `tests/test_ad1270f_impact_selector.py` needs no manifest entry for a new `startup/` module.
- That slice 1b's two test files are none of the six paired files listed in the Anchors paragraph.
- The measured sha (§7.4), and BF-941's state in the regenerated ledger.
- On a live boot, whether the first full dream reaches the adapter. One that runs before finalization is a no-op (the Phase 5 lambda checks `self.dream_adapter`); the time bound covers it.

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** P-B1 removes the stale `unowned-task` row for `init_dreaming`, and no row is added. `announce_fresh_start` is awaited inline, and `crew_start.py` creates no task. `ProbOSRuntime`'s triggers stay `[lines, methods]`; magnitudes are not stored.
- **`check_dormant_classes.py --check`:** unchanged; no class is added under `src/probos`.
- **Config facade, profiles and reference:** unchanged; no field is added.
- **`gen_ad_ledger.py --check`:** regenerated in M3.
- **Test collection:** two new test files (`git diff --name-status --diff-filter=A` over the slice, `-- tests`).

## 13. Prior Art and Blind Spots

- **Internal:**
  - `docs/research/agent-situation-awareness-architecture.md` (the BF-034 note as a situation-awareness input) and `docs/research/ambient-awareness-optimal-working-memory.md` (the confabulation guard and the cold-start note) treat the note as a short-lived situation input. Adopted: the window bounds it.
  - `docs/research/self-regulation-research.md` (trust-anomaly cold-start suppression). Kept as is.
  - The AD-640 tiered-trust research is why the trust half and the 0.5 texts go.
  - 4b's decision (`DECISIONS.md`: "repairing BF-034's detector ... a fresh-start prompt note that nothing clears") is acted on here.
- **External:** skipped. This is ProbOS-specific startup wiring with no outside design to borrow. `docs/research/reference-projects.md` was not examined.
- **Blind spots found:**
  1. The announcement was dead by phase as well as by the predicate.
  2. Its unowned task was baseline debt.
  3. Three texts claim 0.5, and two claim a reset.
  4. AD-435 would have degraded to the generic title.
  5. AD-1077 coaching waits while the proactive note is shown.
  6. The Phase 5 and Phase 8 evaluations can diverge.
  7. A dream before finalization is lost, and Captain activity postpones dreams.
  8. `get_stats` scans all metadata on a first boot with a large store (once, as 4b's Phase 8 read already does).
  9. The raw flag stays set after a time-only close; only finalization reads it.
  10. Register items 4d-R1 to 4d-R3 below.

## 14. Diff Reviewer: properties to verify (by execution: run both new files, then the greps)

1. With `runtime._cold_start` false, every prompt but the cold-start orientation renders byte-identically to the base. The proactive text changes only inside its cold branch, and the orientation change is one line of First Duty Guidance.
2. A Grep of `src` for `await is_new_crew_start\(` finds exactly `startup/dreaming.py` (`init_dreaming`) and `startup/finalize.py` (`_is_new_crew_start`). `crew_start.is_new_crew_start` fails warm on a session record, `None`, a raise, and a non-zero or malformed answer. The detector reads no trust record.
3. `is_cold_start` is false after the first `DreamAdapter.on_post_dream`, or once the window has elapsed. `end_cold_start` is idempotent. `adopt_new_crew_start(False)` changes nothing, and `adopt_new_crew_start(True)` sets `reset`.
4. The Fresh Start thread is awaited in `finalize_startup` after the AD-435 block, under `runtime.ward_room and runtime._cold_start`, the auto-welcome's gate with the flag negated. `dreaming.py` contains no `create_thread` and no `loop.create_task`. No `create_task` is added anywhere.
5. BF-178's stasis branch (`clear_dream_history`, 60 s suppression, its log line) is unchanged in behaviour.
6. `architecture-baseline.yaml` loses exactly the one row, and the P-T1 pin equals the measured value.
7. No config field, `EventType` or persisted schema is added. `init_dreaming` takes `lifecycle_state` and no longer takes `ward_room`.
8. Every comment and docstring the slice adds or rewrites is true of the head: `_is_new_crew_start`'s, the detector block's, `is_cold_start`'s, P-T7's and P-T8's, and the trackers'.
9. No agent-facing or crew-facing text added by the slice contains "0.5", "has been reset" or "has been cleared".

## 15. Acceptance criteria

- Both new files pass, and every §10 mutant is killed.
- `check_architecture_principles.py --check` and `check_dormant_classes.py --check` (paste its whole output) pass, as does the ledger check.
- The focused gates pass and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-10-28, before the build, on slice 1b's candidate `4b228a27`)

Written before the build (nothing of M1 to M3 committed), from the orchestrator's pre-build sweep (B1 to B4) and the Architect's sweep of the text that describes the head.

- **B1 (P-F5's comment, D3, §14 item 4).** "Posted exactly when the auto-welcome is skipped" was false twice: with no Ward Room both are skipped, and the two gates read `runtime._cold_start` at two points with awaits between them, so a dream cycle that completes in between can clear the flag and post both (new row 4d-R4). The text now describes the gate: the auto-welcome's with the flag negated.
- **B2 (P-F3's docstring, §3, §13 item 6).** "Differ only if an episode is stored" ignored a count that is readable at one ask and not at the other, which can make either answer the new-crew one. Now "can differ", with the episode case as the example; "(warm)" leaves §13.
- **B3 (7.3.N's docstring, P-S4's comment).** A log sample was stated as "never ran" in shipped text. The log evidence leaves the docstring (it stays in #1324 register 4b-R10 and §1), and each half is stated as conditionally keeping the branch dead.
- **B4 (7.2.N's docstring).** The shared predicate's false warm start also skips the boot camp's activation at finalization; "only" and "every" go.
- **Sweep repairs.** M1's "changes no boot" (the cold-start orientation changes at once for every agent it is rendered for); §1's, PROGRESS's and DECISIONS' universals over live boots, now scoped to a boot with an episodic memory (and, for DECISIONS, an AD-640 bridge or chief prior); DECISIONS' "every prompt" (three readers); §14 item 1 (the orientation does not read the flag); §14 item 2's Grep, which also matched the predicate's `def` and `_is_new_crew_start(` and is now anchored on `await`; §12's dormant-class line, scoped to `src/probos` (the new test file adds `_Stats`); §8's roadmap sentence (the table holds a CLOSED row); 4d-R1, scoped to AD-502's `_lifecycle_state` (the orientation context has its own `restart`).
- **Scope.** Wording only. No code, test, case count, mutation row, decision or milestone changes; every repair inside a pair body or a new-file body changes comment or docstring text. The tracker heads keep their first 120 characters. The "instead of" and "replacing" sentences in the trackers and row 4b-R10 stand as the gates' design; 4d-R4 records their one exception.

## For the register (#1324)

- **4b-R10: built by BF-941** (this slice), with `test_a_new_crew_reaches_the_agent_note_until_the_first_dream` as the detector-to-reader seam. The Captain is told when it lands: at the next new-crew start the crew sees "Fresh Start — New Crew" instead of "New Crew Aboard", and agents carry the fresh-start note until the first dream or ten minutes.
- **4d-R1 (owner #1324, unscheduled):** AD-435's `restart` branch is unreachable. No `src` code writes `restart` to AD-502's `_lifecycle_state`.
- **4d-R2 (owner #1324, unscheduled):** `--fresh` writes `reset` after finalization, so a warm boot with episodes reads `reset` to the HXI and to agent telemetry for the session.
- **4d-R3 (owner #1324, verify):** `agent_onboarding.py` passes `trust_score=0.5` into every cold-start `OrientationContext` whatever the AD-640 tier. Check whether any rendered orientation shows it.
- **4d-R4 (owner #1324, unscheduled):** the Fresh Start gate and the BF-102 auto-welcome read `runtime._cold_start` at two points of finalization, with awaits between them. A full dream cycle that completes between the two reads clears the flag through the adapter, and both threads are posted. It needs that stretch of finalization to run 120 s or more after Phase 5 starts the dream scheduler, with no Captain activity; not measured.
