"""AD-1270 (#1324) slice 3: AD-668 salience and AD-670 metabolism, wired to crew working memory.

Default off: with ``working_memory.cognition_enabled`` false nothing is constructed and working
memory behaves as before (``test_flag_off_*``). On, AD-573's restore, the real startup helper,
the real driver and the real engines meet across the startup seam (``test_flag_on_*``), and what
the agent is shown (``render_context``) and what shutdown freezes (``to_dict``) change as AD-670
and AD-668 say. Two cases scan production source with ``ast`` (a shared contract: the cycle's
order against the AD-573 restore and freeze); they parse bytes, so they read the same on every
host.

No test touches a live system or the real data directory. The BF-926 sibling reads the tracked
``config/system.yaml`` and changes nothing.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import importlib.util
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from probos.cognitive import working_memory_cognition as wmc
from probos.cognitive.agent_working_memory import AgentWorkingMemory, NamedBuffer, WorkingMemoryEntry
from probos.cognitive.memory_metabolism import MemoryMetabolism, MetabolismReport
from probos.cognitive.salience_filter import SalienceFilter
from probos.cognitive.working_memory_cognition import (
    CognitionTickReport,
    WorkingMemoryCognition,
    build_working_memory_cognition,
)
from probos.cognitive.working_memory_store import WorkingMemoryStore
from probos.config import MetabolismConfig, SalienceConfig, SystemConfig, WorkingMemoryConfig
from probos.startup import finalize as finalize_module
from probos.startup import shutdown as shutdown_module
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from tests.fixtures.runtime_lifecycle import BareRuntime

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "probos"
_HOUR = 3600.0
_TASK_NAME = "ad1270-working-memory-cognition"
_STALE = {
    "checked the warp core telemetry": 12 * _HOUR,
    "filed the morning duty report": 11 * _HOUR,
    "reviewed the sensor sweep logs": 10 * _HOUR,
}
_FRESH = "answered the Captain about the plan"
_KEPT = ["reviewed the sensor sweep logs", _FRESH]


# --- helpers ------------------------------------------------------------------------------


def _on(**sections: dict[str, Any]) -> SystemConfig:
    """A config with the flag on and these sections overridden."""
    return SystemConfig.model_validate({"working_memory": {"cognition_enabled": True}, **sections})


def _build(
    config: SystemConfig, members: list[tuple[str, AgentWorkingMemory]]
) -> WorkingMemoryCognition | None:
    return build_working_memory_cognition(
        working_memory=config.working_memory,
        salience=config.salience,
        metabolism=config.metabolism,
        working_memories=lambda: list(members),
    )


def _backdate(memory: AgentWorkingMemory, buffer: str, ages: dict[str, float]) -> None:
    """Age ring entries by content; a live-recorded named-buffer entry is the same object."""
    now = time.time()
    for entry in memory.get_buffers()[buffer]:
        if entry.content in ages:
            entry.timestamp = now - ages[entry.content]


def _frozen_state(now: float) -> dict[str, Any]:
    """A working memory as AD-573 freezes it: three stale actions and a fresh one, in both views."""
    ages = {**_STALE, _FRESH: 60.0}
    actions = [
        {
            "content": content, "category": "action", "source_pathway": "proactive",
            "timestamp": now - age, "metadata": {}, "knowledge_source": "unknown",
        }
        for content, age in ages.items()
    ]
    return {
        "recent_actions": actions,
        "named_buffers": {
            "duty": {"name": "duty", "token_budget": 600, "entries": [dict(action) for action in actions]},
        },
    }


def _agent(agent_id: str, agent_type: str, memory: AgentWorkingMemory | None) -> SimpleNamespace:
    return SimpleNamespace(id=agent_id, agent_type=agent_type, working_memory=memory)


def _runtime(*agents: SimpleNamespace) -> SimpleNamespace:
    """What the startup helper reads: the registry, and the ontology (None selects the legacy crew set)."""
    return SimpleNamespace(registry=SimpleNamespace(all=lambda: list(agents)), ontology=None)


def _snapshot(memory: AgentWorkingMemory) -> str:
    return json.dumps(memory.to_dict(), sort_keys=True)


class _Refuse:
    """Stands in for a class that must not be built with the flag off."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("constructed with working_memory.cognition_enabled off")

    @classmethod
    def from_config(cls, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("constructed with working_memory.cognition_enabled off")


def _calls_in(path: Path, function: str) -> list[tuple[int, str]]:
    """``(line, callee name)`` for every call inside the top-level function ``function``."""
    tree = ast.parse(path.read_bytes(), filename=path.as_posix())
    target = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
    )
    calls: list[tuple[int, str]] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.append((node.lineno, node.func.attr))
            elif isinstance(node.func, ast.Name):
                calls.append((node.lineno, node.func.id))
    return sorted(calls)


def _load_reader_check() -> Any:
    path = _REPO_ROOT / "scripts" / "check_config_readers.py"
    spec = importlib.util.spec_from_file_location("_ad1270_wmc_config_readers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@functools.lru_cache(maxsize=1)
def _reader_report() -> Any:
    """Built once per process from the real model, source and tracked yaml; tests only read it."""
    checker = _load_reader_check()
    document = yaml.safe_load(checker.DEFAULT_YAML.read_text(encoding="utf-8"))
    return checker.build_report(SystemConfig, checker.DEFAULT_SOURCE, document)


_NO_GRACE = {"shutdown_write_grace_s": 0.0, "shutdown_dispatch_grace_s": 0.0}
_FROZEN_ACTION = "logged the shield harmonics before the shutdown"


async def _cancelled_once() -> None:
    """Cancel the running task once and handle it, as BF-303's Ctrl+C leaves shutdown's caller.

    Call it first in a task of its own: the count it leaves must not reach the test's task.
    """
    current = asyncio.current_task()
    assert current is not None and current.cancelling() == 0
    current.cancel()
    try:
        await asyncio.sleep(0)
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("the earlier cancellation was not delivered")
    assert current.cancelling() == 1


# --- T1 to T5: the flag, the sections and the refusals ------------------------------------


def test_the_flag_is_off_by_default() -> None:
    assert WorkingMemoryConfig().cognition_enabled is False
    assert SystemConfig().working_memory.cognition_enabled is False
    assert WorkingMemoryConfig.model_validate({"cognition_enabled": True}).cognition_enabled is True


def test_flag_off_the_builder_constructs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SalienceFilter", "MemoryMetabolism", "WorkingMemoryCognition"):
        monkeypatch.setattr(wmc, name, _Refuse)

    def never() -> list[tuple[str, AgentWorkingMemory]]:
        raise AssertionError("crew listed with the flag off")

    assert build_working_memory_cognition(
        working_memory=WorkingMemoryConfig(), salience=SalienceConfig(),
        metabolism=MetabolismConfig(), working_memories=never,
    ) is None


@pytest.mark.parametrize("part", ["salience-off", "metabolism-off"])
def test_each_section_turns_its_own_part_off(part: str) -> None:
    memory = AgentWorkingMemory()
    section = {"salience": {"enabled": False}} if part == "salience-off" else {"metabolism": {"enabled": False}}
    cognition = _build(_on(**section), [("crew-1", memory)])

    assert cognition is not None and cognition.attach_all() == 1
    if part == "salience-off":
        assert memory.get_background_stream() is None
        assert isinstance(memory.run_metabolism_cycle(), MetabolismReport)
    else:
        assert memory.get_background_stream() is not None
        assert memory.run_metabolism_cycle() is None


def test_both_sections_off_attaches_nothing() -> None:
    config = _on(salience={"enabled": False}, metabolism={"enabled": False})

    assert _build(config, []) is None


def test_the_salience_section_sets_the_threshold_and_the_stream_size() -> None:
    memory = AgentWorkingMemory()
    config = _on(salience={"threshold": 0.99, "background_max_entries": 2}, metabolism={"enabled": False})
    cognition = _build(config, [("crew-1", memory)])
    assert cognition is not None and cognition.attach_all() == 1

    for number in range(3):
        memory.record_observation(f"routine reading number {number}", source="proactive")

    assert len(memory.get_buffers()["observations"]) == 0
    assert len(memory.get_background_stream()) == 2


def test_the_metabolism_section_sets_decay_forget_and_floor() -> None:
    """Half-life 60 s, forget below 0.5, keep none: a 90 s entry scores 2**-1.5 = 0.354 and goes."""
    memory = AgentWorkingMemory()
    config = _on(
        salience={"enabled": False},
        metabolism={"decay_half_life_seconds": 60.0, "forget_threshold": 0.5, "min_entries_per_buffer": 0},
    )
    cognition = _build(config, [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    memory.record_action("ran the ninety second diagnostic", source="proactive")
    _backdate(memory, "actions", {"ran the ninety second diagnostic": 90.0})

    report = memory.run_metabolism_cycle()

    assert report is not None and report.forgotten_count == 1
    assert len(memory.get_buffers()["actions"]) == 0


@pytest.mark.parametrize(("audit", "flags"), [(True, 1), (False, 0)], ids=["on", "off"])
def test_the_metabolism_section_sets_audit(audit: bool, flags: int) -> None:
    memory = AgentWorkingMemory()
    cognition = _build(_on(salience={"enabled": False}, metabolism={"audit_enabled": audit}), [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    memory.record_observation("the reactor coolant pump is running", source="proactive")
    memory.record_observation("the reactor coolant pump is not running", source="proactive")

    assert cognition.tick_once().audit_flags == flags


@pytest.mark.parametrize(
    ("section", "prior"),
    [({"triage_base_score": 0.6}, 0), ({"triage_fullness_threshold": 0.0}, 5)],
    ids=["base", "fullness"],
)
def test_the_metabolism_section_sets_triage(section: dict[str, float], prior: int) -> None:
    """A short entry scores 0.5. Base 0.6 refuses it in an empty ring; fullness 0.0 refuses it at 5 of 10."""
    memory = AgentWorkingMemory()
    cognition = _build(_on(salience={"enabled": False}, metabolism=section), [("crew-1", memory)])
    assert cognition is not None
    cognition.attach_all()
    for number in range(prior):
        memory.record_action(f"a long enough action number {number}", source="proactive")

    memory.record_action("short note", source="proactive")

    assert "short note" not in [entry.content for entry in memory.get_buffers()["actions"]]


_INVALID: dict[str, dict[str, dict[str, float]]] = {
    "interval-zero": {"metabolism": {"cycle_interval_seconds": 0.0}},
    "interval-nan": {"metabolism": {"cycle_interval_seconds": float("nan")}},
    "interval-inf": {"metabolism": {"cycle_interval_seconds": float("inf")}},
    "half-life-nan": {"metabolism": {"decay_half_life_seconds": float("nan")}},
    "half-life-inf": {"metabolism": {"decay_half_life_seconds": float("inf")}},
    "fullness-one": {"metabolism": {"triage_fullness_threshold": 1.0}},
    "fullness-negative": {"metabolism": {"triage_fullness_threshold": -0.1}},
    "base-nan": {"metabolism": {"triage_base_score": float("nan")}},
    "base-above-one": {"metabolism": {"triage_base_score": 1.5}},
    "threshold-nan": {"salience": {"threshold": float("nan")}},
    "threshold-above-one": {"salience": {"threshold": 1.5}},
    "background-negative": {"salience": {"background_max_entries": -1}},
}


@pytest.mark.parametrize("case", sorted(_INVALID))
def test_invalid_values_are_refused(case: str) -> None:
    config = _on(**_INVALID[case])  # parsed outside the raises block: pydantic's error is a ValueError too

    with pytest.raises(ValueError):
        _build(config, [])


_DRIVER_INVALID: dict[str, dict[str, Any]] = {
    "nothing": {"salience_filter": None, "metabolism": None},
    "zero": {"interval_seconds": 0.0},
    "inf": {"interval_seconds": float("inf")},
    "negative-stream": {"background_max_entries": -1},
}


@pytest.mark.parametrize("case", sorted(_DRIVER_INVALID))
def test_the_driver_needs_a_part_and_a_finite_period(case: str) -> None:
    arguments: dict[str, Any] = {
        "working_memories": lambda: [], "salience_filter": SalienceFilter(), "metabolism": MemoryMetabolism(),
        "background_max_entries": 50, "interval_seconds": 300.0, **_DRIVER_INVALID[case],
    }

    with pytest.raises(ValueError):
        WorkingMemoryCognition(**arguments)


# --- T6 to T9: AgentWorkingMemory ---------------------------------------------------------


def test_attach_cognition_is_idempotent_and_keeps_the_stream() -> None:
    memory = AgentWorkingMemory()
    gate = SalienceFilter(threshold=0.99)
    memory.attach_cognition(salience_filter=gate, metabolism=None)
    memory.record_observation("routine reading kept in the stream", source="proactive")
    stream = memory.get_background_stream()

    memory.attach_cognition(salience_filter=gate, metabolism=None)

    assert memory.get_background_stream() is stream
    assert len(stream) == 1


def test_attach_cognition_with_none_leaves_that_part_as_it_is() -> None:
    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=None, metabolism=MemoryMetabolism())
    assert memory.get_background_stream() is None

    memory.attach_cognition(salience_filter=SalienceFilter(), metabolism=None)

    assert memory.get_background_stream() is not None
    assert isinstance(memory.run_metabolism_cycle(), MetabolismReport)


def test_forget_leaves_the_named_buffers_too() -> None:
    memory = AgentWorkingMemory()
    memory.set_metabolism(MemoryMetabolism())
    for content in (*_STALE, _FRESH):
        memory.record_action(content, source="proactive")
    _backdate(memory, "actions", _STALE)

    report = memory.run_metabolism_cycle()

    assert report is not None and report.forgotten_count == 2
    assert [entry.content for entry in memory.get_buffers()["actions"]] == _KEPT
    assert [entry.content for entry in memory.get_buffer("duty").entries] == _KEPT
    assert "checked the warp core telemetry" not in memory.render_buffers(["duty"])


def test_discard_matches_by_value_and_keeps_the_rest() -> None:
    first, second, third = (
        WorkingMemoryEntry(content=text, category="action", source_pathway="proactive", timestamp=1000.0 + number)
        for number, text in enumerate(("one", "two", "three"))
    )
    named = NamedBuffer(name="duty", token_budget=600)
    for entry in (first, second, third):
        named.append(entry)

    assert named.discard([replace(second, metadata={"_decay_score": 0.0})]) == 1
    assert named.entries == [first, third]
    assert named.discard([]) == 0
    for number in range(25):
        named.append(WorkingMemoryEntry(content=f"filler {number}", category="action", source_pathway="proactive"))
    assert len(named) == 20


def test_run_metabolism_cycle_returns_its_report_or_none() -> None:
    memory = AgentWorkingMemory()
    assert memory.run_metabolism_cycle() is None

    memory.set_metabolism(MemoryMetabolism())
    memory.record_action("did something worth keeping", source="proactive")
    report = memory.run_metabolism_cycle()

    assert isinstance(report, MetabolismReport)
    assert report.decayed_count == 1 and report.forgotten_count == 0


def test_a_salience_scorer_that_raises_admits_the_entry(caplog: pytest.LogCaptureFixture) -> None:
    class _Raising(SalienceFilter):
        def score(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> Any:
            raise RuntimeError("scorer fault")

    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=_Raising(), metabolism=None)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_working_memory"):
        memory.record_action("kept despite the scorer fault", source="proactive")

    assert [entry.content for entry in memory.get_buffers()["actions"]] == ["kept despite the scorer fault"]
    assert "salience scoring failed" in caplog.text


def test_at_the_default_threshold_the_gate_demotes_nothing() -> None:
    """D7's evidence: with no agent context and no novelty gate a fresh entry scores at least 0.575
    against 0.3, so enabling the flag at the defaults changes nothing through the salience gate.
    If this fails, AD-668's defaults changed: that is a Captain-visible change to agent memory."""
    memory = AgentWorkingMemory()
    memory.attach_cognition(salience_filter=SalienceFilter.from_config(SalienceConfig()), metabolism=None)

    memory.record_action("ok", source="proactive", metadata={"severity": "low"})
    memory.record_observation("ok", source="proactive")
    memory.record_conversation("ok", partner="someone-unknown", source="dm")
    memory.record_event("ok")
    memory.record_reasoning("ok", source="chain")

    assert len(memory.get_background_stream()) == 0


# --- T10, T11: the driver -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_attaches_now_and_stop_ends_the_cycle() -> None:
    first, second = AgentWorkingMemory(), AgentWorkingMemory()
    cognition = _build(_on(), [("crew-1", first), ("crew-2", second)])
    assert cognition is not None
    await cognition.stop()  # before start: nothing to stop

    await cognition.start()
    try:
        assert cognition.running
        assert first.get_background_stream() is not None
        assert second.get_background_stream() is not None
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert not cognition.running
    await asyncio.wait_for(cognition.stop(), timeout=2)  # idempotent


@pytest.mark.asyncio
async def test_start_twice_keeps_one_task() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    await cognition.start()
    try:
        live = [task for task in asyncio.all_tasks() if task.get_name() == _TASK_NAME and not task.done()]
        assert len(live) == 1
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)


@pytest.mark.asyncio
async def test_stop_passes_on_a_cancellation_aimed_at_its_caller() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    stopper = asyncio.create_task(cognition.stop())
    await asyncio.sleep(0)  # the stopper has cancelled the cycle and is waiting for it

    stopper.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert not cognition.running


@pytest.mark.asyncio
async def test_stop_from_a_task_cancelled_earlier_absorbs_only_its_own_cancellation() -> None:
    """A1: shutdown's caller keeps a cancel count above zero for the whole teardown (BF-303)."""
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()

    async def stop_twice_after_an_earlier_cancellation() -> list[bool]:
        await _cancelled_once()
        raised: list[bool] = []
        for _ in range(2):  # the second call: idempotent for the same caller
            try:
                await cognition.stop()
            except asyncio.CancelledError:
                raised.append(True)
            else:
                raised.append(False)
        return raised

    try:
        raised = await asyncio.create_task(stop_twice_after_an_earlier_cancellation())
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert raised == [False, False]
    assert not cognition.running


@pytest.mark.asyncio
async def test_the_loop_runs_a_cycle_each_interval_and_survives_a_raising_cycle(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    cognition = WorkingMemoryCognition(
        working_memories=lambda: [], salience_filter=None, metabolism=MemoryMetabolism(),
        background_max_entries=50, interval_seconds=0.01,
    )
    calls: list[int] = []

    def tick() -> CognitionTickReport:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first cycle fails")
        return CognitionTickReport(agents=0, forgotten=0, audit_flags=0, demoted=0, failed=0)

    monkeypatch.setattr(cognition, "tick_once", tick)
    caplog.set_level(logging.WARNING, logger=wmc.__name__)
    await cognition.start()
    try:
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert len(calls) >= 2
    assert "the next one runs on time" in caplog.text


def test_a_tick_attaches_a_memory_that_joined_or_was_replaced() -> None:
    members: list[tuple[str, AgentWorkingMemory]] = []
    cognition = _build(_on(), members)
    assert cognition is not None and cognition.attach_all() == 0
    joined = AgentWorkingMemory()
    members.append(("crew-1", joined))

    tick = cognition.tick_once()

    assert tick.agents == 1
    assert joined.get_background_stream() is not None


def test_one_failing_agent_does_not_stop_the_others(caplog: pytest.LogCaptureFixture) -> None:
    class _Broken(AgentWorkingMemory):
        def run_metabolism_cycle(self) -> MetabolismReport | None:
            raise RuntimeError("cycle fault")

    good = AgentWorkingMemory()
    cognition = _build(_on(salience={"threshold": 0.99}), [("crew-broken", _Broken()), ("crew-good", good)])
    assert cognition is not None
    cognition.attach_all()
    good.record_observation("routine reading for the good agent", source="proactive")

    with caplog.at_level(logging.WARNING, logger=wmc.__name__):
        tick = cognition.tick_once()

    assert tick == CognitionTickReport(agents=2, forgotten=0, audit_flags=0, demoted=1, failed=1)
    assert "crew-broken" in caplog.text


def test_a_provider_that_raises_makes_an_empty_cycle(caplog: pytest.LogCaptureFixture) -> None:
    def broken() -> list[tuple[str, AgentWorkingMemory]]:
        raise RuntimeError("registry fault")

    cognition = WorkingMemoryCognition(
        working_memories=broken, salience_filter=SalienceFilter(), metabolism=None,
        background_max_entries=50, interval_seconds=1.0,
    )
    with caplog.at_level(logging.WARNING, logger=wmc.__name__):
        assert cognition.attach_all() == 0
        assert cognition.tick_once() == CognitionTickReport(agents=0, forgotten=0, audit_flags=0, demoted=0, failed=0)

    assert "could not list crew working memory" in caplog.text


def test_the_tick_logs_what_it_did_per_agent(caplog: pytest.LogCaptureFixture) -> None:
    quiet, busy = AgentWorkingMemory(), AgentWorkingMemory()
    cognition = _build(_on(salience={"threshold": 0.99}), [("crew-quiet", quiet), ("crew-busy", busy)])
    assert cognition is not None
    cognition.attach_all()
    busy.record_observation("routine reading for the busy agent", source="proactive")

    with caplog.at_level(logging.INFO, logger=wmc.__name__):
        cognition.tick_once()

    lines = [record.getMessage() for record in caplog.records if record.name == wmc.__name__]
    assert lines == ["AD-1270: working memory of crew-busy: forgotten=0 audit_flags=0 demoted=1"]


# --- X1 to X7: across the startup and shutdown seams ------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_a_restored_memory_forgets_its_stale_entries_everywhere() -> None:
    """The crossing: AD-573's restore -> the real startup helper -> the real driver -> AD-670 ->
    what the agent is shown and what shutdown freezes, including the restored named-buffer copies."""
    restored = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    bystander = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    bystander_before = _snapshot(bystander)
    runtime = _runtime(
        _agent("crew-1", "counselor", restored),
        _agent("crew-2", "scout", None),
        _agent("tool-1", "not_a_crew_type", bystander),
    )

    await finalize_module._start_working_memory_cognition(runtime=runtime, config=_on())
    cognition = runtime.working_memory_cognition
    try:
        assert isinstance(cognition, WorkingMemoryCognition) and cognition.running
        tick = cognition.tick_once()
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert tick == CognitionTickReport(agents=1, forgotten=2, audit_flags=0, demoted=0, failed=0)
    shown = restored.render_context()
    assert "reviewed the sensor sweep logs" in shown and _FRESH in shown
    assert "checked the warp core telemetry" not in shown and "filed the morning duty report" not in shown
    frozen = restored.to_dict()
    assert [entry["content"] for entry in frozen["recent_actions"]] == _KEPT
    assert [entry["content"] for entry in frozen["named_buffers"]["duty"]["entries"]] == _KEPT
    assert all("_decay_score" in entry["metadata"] for entry in frozen["recent_actions"])
    assert bystander.get_background_stream() is None
    assert _snapshot(bystander) == bystander_before


@pytest.mark.asyncio
async def test_flag_on_a_demoted_entry_never_reaches_the_prompt_and_the_cycle_drains_it() -> None:
    memory = AgentWorkingMemory()
    runtime = _runtime(_agent("crew-1", "counselor", memory))
    await finalize_module._start_working_memory_cognition(runtime=runtime, config=_on(salience={"threshold": 0.99}))
    cognition = runtime.working_memory_cognition
    try:
        memory.record_observation("routine hull temperature reading", source="proactive")
        assert "routine hull temperature reading" not in memory.render_context()
        assert len(memory.get_background_stream()) == 1

        tick = cognition.tick_once()
    finally:
        await asyncio.wait_for(cognition.stop(), timeout=2)

    assert tick.demoted == 1
    assert len(memory.get_background_stream()) == 0


@pytest.mark.asyncio
async def test_flag_off_startup_builds_nothing_and_working_memory_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("SalienceFilter", "MemoryMetabolism", "WorkingMemoryCognition"):
        monkeypatch.setattr(wmc, name, _Refuse)
    memory = AgentWorkingMemory.from_dict(_frozen_state(time.time()))
    before = _snapshot(memory)
    runtime = _runtime(_agent("crew-1", "counselor", memory))

    await finalize_module._start_working_memory_cognition(runtime=runtime, config=SystemConfig())

    assert runtime.working_memory_cognition is None
    assert _snapshot(memory) == before
    assert memory.get_background_stream() is None
    assert memory.run_metabolism_cycle() is None
    memory.record_action("   ", source="proactive")  # no TRIAGE: a blank entry is still admitted
    assert [entry.content for entry in memory.get_buffers()["actions"]][-1] == "   "


@pytest.mark.asyncio
async def test_an_invalid_value_leaves_cognition_off_at_startup(caplog: pytest.LogCaptureFixture) -> None:
    memory = AgentWorkingMemory()
    runtime = _runtime(_agent("crew-1", "counselor", memory))

    with caplog.at_level(logging.WARNING, logger=finalize_module.__name__):
        await finalize_module._start_working_memory_cognition(
            runtime=runtime, config=_on(metabolism={"cycle_interval_seconds": 0.0}),
        )

    assert runtime.working_memory_cognition is None
    assert memory.get_background_stream() is None
    assert "working-memory cognition config is invalid" in caplog.text


@pytest.mark.asyncio
async def test_the_shutdown_helper_stops_the_cycle_and_ignores_anything_else() -> None:
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    runtime = SimpleNamespace(working_memory_cognition=cognition)

    await asyncio.wait_for(shutdown_module._stop_working_memory_cognition(runtime), timeout=2)

    assert not cognition.running
    assert runtime.working_memory_cognition is None
    foreign = object()
    other = SimpleNamespace(working_memory_cognition=foreign)
    await shutdown_module._stop_working_memory_cognition(other)
    assert other.working_memory_cognition is foreign
    await shutdown_module._stop_working_memory_cognition(SimpleNamespace())


@pytest.mark.asyncio
async def test_the_shutdown_helper_passes_on_a_cancellation_that_arrives_during_the_stop() -> None:
    """A1: cancelled once already (BF-303), then again while the stop waits; the second propagates."""
    cognition = _build(_on(), [])
    assert cognition is not None
    await cognition.start()
    runtime = SimpleNamespace(working_memory_cognition=cognition)
    entered = asyncio.Event()

    async def stop_after_an_earlier_cancellation() -> None:
        await _cancelled_once()
        entered.set()
        await shutdown_module._stop_working_memory_cognition(runtime)

    stopper = asyncio.create_task(stop_after_an_earlier_cancellation())
    await entered.wait()  # the stopper has cancelled the cycle and is waiting for it
    stopper.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert not cognition.running
    assert runtime.working_memory_cognition is None


@pytest.mark.asyncio
async def test_the_shutdown_helper_leaves_a_foreign_service_alone() -> None:
    """Only the driver this slice builds is stopped; another object with an async stop() is not."""
    stops: list[str] = []

    class _Foreign:
        async def stop(self) -> None:
            stops.append("stop")

    foreign = _Foreign()
    runtime = SimpleNamespace(working_memory_cognition=foreign)

    await shutdown_module._stop_working_memory_cognition(runtime)

    assert stops == []
    assert runtime.working_memory_cognition is foreign


@pytest.mark.asyncio
async def test_the_shutdown_helper_logs_a_failed_stop_and_still_clears_the_attribute(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingStop(WorkingMemoryCognition):
        async def stop(self) -> None:
            raise RuntimeError("stop fault")

    cognition = _FailingStop(
        working_memories=lambda: [], salience_filter=SalienceFilter(), metabolism=None,
        background_max_entries=50, interval_seconds=1.0,
    )
    runtime = SimpleNamespace(working_memory_cognition=cognition)

    with caplog.at_level(logging.WARNING, logger=shutdown_module.__name__):
        await shutdown_module._stop_working_memory_cognition(runtime)

    assert "AD-1270 WorkingMemoryCognition.stop() failed during shutdown" in caplog.text
    assert runtime.working_memory_cognition is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enabled", "cancelled_earlier"),
    [(True, False), (False, True), (True, True)],
    ids=["on-never-cancelled", "off-cancelled-earlier", "on-cancelled-earlier"],
)
async def test_the_real_shutdown_freezes_working_memory_after_an_earlier_cancellation(
    tmp_path: Path, enabled: bool, cancelled_earlier: bool,
) -> None:
    """The A1 crossing: the real ``shutdown()`` on a bare runtime, the real startup helper and
    driver, and a real SQLite working-memory store. BF-303: shutdown is awaited from a task the
    operator's Ctrl+C already cancelled. The controls come first; the last case is the regression."""
    config = SystemConfig.model_validate(
        {"working_memory": {"cognition_enabled": enabled}, "memory": _NO_GRACE}
    )
    runtime = BareRuntime(tmp_path / "runtime", config=config, started=True)
    db_path = str(tmp_path / "working_memory.db")
    store = WorkingMemoryStore(connection_factory=SQLiteConnectionFactory(), db_path=db_path)
    await store.start()
    runtime.working_memory_store = store
    memory = AgentWorkingMemory()
    memory.record_action(_FROZEN_ACTION, source="proactive")
    await runtime.registry.register(
        SimpleNamespace(id="crew-1", agent_type="counselor", pool="crew", working_memory=memory)
    )
    await finalize_module._start_working_memory_cognition(runtime=runtime, config=config)
    cognition = runtime.working_memory_cognition
    assert isinstance(cognition, WorkingMemoryCognition) is enabled

    async def shut_down() -> bool:
        """Its own task, so the earlier cancellation never reaches this test's task."""
        if cancelled_earlier:
            await _cancelled_once()
        try:
            await shutdown_module.shutdown(runtime, reason="ad1270-a1")
        except asyncio.CancelledError:
            return True
        return False

    try:
        raised = await asyncio.create_task(shut_down())
    finally:
        await store.stop()  # shutdown stops it; one cut short does not
        if isinstance(cognition, WorkingMemoryCognition):
            await asyncio.wait_for(cognition.stop(), timeout=2)

    reader = WorkingMemoryStore(connection_factory=SQLiteConnectionFactory(), db_path=db_path)
    await reader.start()
    try:
        frozen = await reader.load_all()
    finally:
        await reader.stop()
    outcome = {
        "raised": raised,
        "frozen": {
            agent_id: [entry["content"] for entry in state["recent_actions"]]
            for agent_id, state in frozen.items()
        },
        "llm_closed": "llm_client.close" in runtime.calls,
        "started": runtime._started,
        "driver_on_runtime": runtime.working_memory_cognition,
    }
    assert outcome == {
        "raised": False,
        "frozen": {"crew-1": [_FROZEN_ACTION]},
        "llm_closed": True,
        "started": False,
        "driver_on_runtime": None,
    }
    assert not [task for task in asyncio.all_tasks() if task.get_name() == _TASK_NAME and not task.done()]


def test_shutdown_stops_the_cycle_before_working_memory_is_frozen() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    calls = _calls_in(_SRC / "startup" / "shutdown.py", "shutdown")
    stops = [line for line, name in calls if name == "_stop_working_memory_cognition"]
    freezes = [line for line, name in calls if name == "save_all"]

    assert len(stops) == 1 and len(freezes) == 1
    assert stops[0] < freezes[0]


def test_startup_starts_the_cycle_after_the_stasis_restore() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    calls = _calls_in(_SRC / "startup" / "finalize.py", "finalize_startup")
    starts = [line for line, name in calls if name == "_start_working_memory_cognition"]
    restores = [line for line, name in calls if name == "from_dict"]

    assert len(starts) == 1 and restores
    assert starts[0] > max(restores)


_WIRED_FIELDS = (
    *(f"metabolism.{name}" for name in MetabolismConfig.model_fields),
    "working_memory.cognition_enabled",
    "salience.threshold",
    "salience.background_max_entries",
)


@pytest.mark.parametrize("path", _WIRED_FIELDS)
def test_the_reader_check_reports_the_wired_fields_as_read(path: str) -> None:
    """BF-926's sibling: these fields are read now, so they carry no inert marker and are not unread."""
    report = _reader_report()

    assert path not in report.inert
    assert path not in report.unread
