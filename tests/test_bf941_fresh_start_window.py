"""BF-941 (#1324 slice 4d) M1: BF-034's fresh-start window is bounded before its detector is wired.

``runtime.is_cold_start`` drives the fresh-start notes in agents' prompts. BF-034 meant it to end
after the first dream cycle, but the AD-515 extraction left that clear on the dream adapter's own
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
