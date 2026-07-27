"""AD-1155: loop-until-done — an outer completion evaluator over a crew child.

Organised by the acceptance sections of the AD. Two tests carry more weight
than the rest:

* **The headline** — the same test body, one flag flipped. A child that stops at
  ``max_iterations`` with work left is re-invoked and completes with the gate
  on, and is recorded ``failed`` with the gate off. If it passes with the flag
  off, the outer loop is not the thing under test.
* **``test_open_todos_with_an_empty_step_list_stops``** — the C-2 #2 regression.
  Issue #1082 proposed ``not _all_steps_done(child.steps)`` as the default
  predicate. ``_all_steps_done`` is ``bool(steps) and all(...)``, so it returns
  ``False`` for an empty checklist and the negation is ``True`` — and the crew
  fan-out NEVER writes ``WorkItem.steps``. Shipping that literal would
  re-invoke every crew child, always, to the cap. This file asserts against the
  REAL ``workforce._all_steps_done`` that the naive predicate would continue and
  that this implementation stops.

Default-OFF byte-identity is asserted key-for-key and value-for-value against a
literal recomputation of the AD-1142 kwarg set, not against ``called_once``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.agentic_dispatch import (
    WorkItemAgenticExecutor,
    WorkItemAgenticOutcome,
)
from probos.cognitive.crew_executor import (
    _ACTIONABLE_STEP_STATUSES,
    _CONTINUATION_HEADER,
    _CONTINUATION_MARKER_INSTRUCTION,
    _CONTINUATION_OUTPUT_ELISION,
    _CONTINUATION_OUTPUT_HEADER,
    _CONTINUATION_STOP_REASON_NOTE,
    _CONTINUATION_TODO_HEADER,
    _DEFAULT_COMPLETION_MARKER,
    _LOOP_PREDICATE_COMPLETION_MARKER,
    _LOOP_PREDICATE_OPEN_TODOS,
    _LOOP_PREDICATE_STOP_REASON,
    _LOOP_PREDICATES,
    _LOOP_UNTIL_DONE_MAX_ITERATIONS,
    _MAX_CONTINUATION_CHARS,
    _MAX_CONTINUATION_OUTPUT_CHARS,
    _MAX_CONTINUATION_TODOS,
    _MIN_CREW_TOKEN_BUDGET,
    _REINVOKABLE_STOPPED_REASONS,
    _STOPPED_REASONS,
    CrewTaskExecutor,
    SubtaskResult,
    _actionable_step_labels,
    _iteration_made_progress,
    _normalize_completion_marker,
    _normalize_loop_until_done_enabled,
    _normalize_loop_until_done_max_iterations,
    _normalize_loop_until_done_predicate,
    _render_continuation,
    _should_continue,
)
from probos.cognitive.crew_session import (
    _PROVISIONING_SPEC_KEYS,
    _canonical_plan_json_bytes,
    _final_plan_hash,
)
from probos.cognitive.crew_verifier import SubtaskVerifier
# The REAL regex, imported rather than re-typed (AD-1140's lesson — ``lack`` is
# a bare substring in it, so reasoning about a match is not evidence).
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness import session_compactor as session_compactor_module
from probos.config import AgenticDispatchConfig, SystemConfig
from probos.workforce import STEP_STATUSES, WorkItemStore, _all_steps_done

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Doubles (the AD-1142 shapes, reused)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _FakeAgent:
    id: str
    instructions: str = "do the thing"
    department: str = "engineering"
    rank: str = "ensign"
    agent_type: str = "builder"
    callsign: str = "WRENCH"
    sovereign_id: str = ""


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._agents = agents

    def get(self, agent_id: str | None) -> _FakeAgent | None:
        return None if agent_id is None else self._agents.get(agent_id)

    def all(self) -> list[_FakeAgent]:
        return list(self._agents.values())


class _ScriptedExecutor:
    """Records every ``run`` kwarg dict and returns a scripted outcome list.

    The last scripted outcome repeats, so a test that scripts two outcomes but
    permits three iterations still terminates.
    """

    def __init__(self, outcomes: list[WorkItemAgenticOutcome]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._outcomes = outcomes

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        index = min(len(self.calls), len(self._outcomes) - 1)
        self.calls.append(dict(kwargs))
        return self._outcomes[index]


def _outcome(
    *,
    stopped_reason: str = "complete",
    final_text: str = "done",
    total_tokens: int = 0,
    artifact_refs: list[dict[str, Any]] | None = None,
    tool_trace_ref: str | None = None,
) -> WorkItemAgenticOutcome:
    return WorkItemAgenticOutcome(
        final_text=final_text,
        stopped_reason=stopped_reason,
        total_tokens=total_tokens,
        artifact_refs=artifact_refs or [],
        tool_trace_ref=tool_trace_ref,
    )


class _CountingCompactorFactory:
    """Stands in for ``SessionCompactor`` so instantiations can be counted."""

    instances: list[Any] = []

    def __init__(self) -> None:
        _CountingCompactorFactory.instances.append(self)

    async def compact(self, messages: list[dict], **_kwargs: Any) -> list[dict]:
        return messages


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(
        db_path=str(tmp_path / "crew.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _runtime() -> Any:
    return SimpleNamespace(
        tool_registry=None,
        tool_permission_store=None,
        intent_bus=None,
        attachment_store=None,
        episodic_memory=None,
        emit_event=None,
        config=SimpleNamespace(agentic_loop=None),
    )


def _executor(
    store: WorkItemStore,
    registry: _FakeRegistry,
    agentic: Any,
    *,
    runtime: Any = None,
    **kwargs: Any,
) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store,
        agent_registry=registry,
        agentic_executor=agentic,  # type: ignore[arg-type]
        runtime=_runtime() if runtime is None else runtime,
        max_parallel_subtasks=3,
        **kwargs,
    )


async def _child(
    store: WorkItemStore,
    *,
    parent_id: str,
    title: str = "Rebalance the coolant manifold",
    description: str = "Rebalance the port coolant manifold and record it.",
    assigned_to: str = "a1",
    spec_id: str = "s1",
):
    return await store.create_work_item(
        title=title,
        description=description,
        work_type="task",
        parent_id=parent_id,
        assigned_to=assigned_to,
        depends_on=[],
        metadata={"spec_id": spec_id},
    )


async def _run_one(
    store: WorkItemStore,
    agentic: Any,
    *,
    steps: list[dict[str, Any]] | None = None,
    **executor_kwargs: Any,
) -> Any:
    """Fan out one parent with one child and return the child's persisted row."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    if steps is not None:
        await store.set_steps(parent.id, steps)
    child = await _child(store, parent_id=parent.id)
    ex = _executor(
        store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic, **executor_kwargs
    )
    await ex.run(parent.id)
    return await store.get_work_item(child.id)


def _plan_identity(child: Any) -> tuple[str, str]:
    """``(plan_seed_hash, final_plan_hash)`` over the child's plan projection.

    ``description`` is a member of ``_PROVISIONING_SPEC_KEYS``, so any AD that
    persisted enriched task text into it would move both hashes and orphan the
    recovery plan.
    """
    projection = {
        "spec_id": str(child.metadata.get("spec_id", child.id)),
        "title": child.title,
        "description": child.description,
        "work_type": child.work_type,
        "priority": child.priority,
        "depends_on": list(child.depends_on),
        "resources": [],
        "spec_metadata": {},
        "expected_output": "",
        "capability": "",
        "department": "",
    }
    assert set(projection) == set(_PROVISIONING_SPEC_KEYS)
    seed = hashlib.sha256(
        _canonical_plan_json_bytes([projection], maximum_bytes=1_048_576)
    ).hexdigest()
    final = _final_plan_hash(
        "parent-1",
        seed,
        [{"spec_id": projection["spec_id"], "work_item_id": child.id}],
        policy="derived_v1",
    )
    return seed, final


# ===========================================================================
# 1. Headline — the same body, one flag flipped
# ===========================================================================

_HEADLINE_SCRIPT = [
    _outcome(
        stopped_reason="max_iterations",
        final_text="I surveyed the manifold and got halfway.",
        tool_trace_ref="a" * 64,
    ),
    _outcome(
        stopped_reason="complete",
        final_text="Manifold rebalanced and logged.",
        tool_trace_ref="b" * 64,
    ),
]


async def test_headline_gate_on_reinvokes_the_cut_off_child_and_it_completes(
    store,
) -> None:
    agentic = _ScriptedExecutor(list(_HEADLINE_SCRIPT))

    row = await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert len(agentic.calls) == 2
    execution = row.metadata["crew_execution"]
    assert execution["status"] == "done"
    assert execution["stopped_reason"] == "complete"
    assert execution["output_summary"] == "Manifold rebalanced and logged."
    assert execution["tool_trace_ref"] == "b" * 64


async def test_headline_gate_off_leaves_the_child_failed_at_max_iterations(
    store,
) -> None:
    """The headline body with ONE flag flipped. This is what must fail without
    the outer loop, and what proves the loop is the mechanism under test."""
    agentic = _ScriptedExecutor(list(_HEADLINE_SCRIPT))

    row = await _run_one(store, agentic, crew_loop_until_done_enabled=False)

    assert len(agentic.calls) == 1
    execution = row.metadata["crew_execution"]
    assert execution["status"] == "failed"
    assert execution["stopped_reason"] == "max_iterations"
    assert execution["output_summary"] == "I surveyed the manifold and got halfway."
    assert execution["tool_trace_ref"] == "a" * 64


# ===========================================================================
# 2. Seam (DD-1) — byte-identity when off
# ===========================================================================

async def test_gate_off_child_run_kwargs_match_the_ad1142_set_key_for_key(
    store,
) -> None:
    """Key-for-key AND value-for-value against a literal recomputation — an
    ``assert called_once`` would not catch a changed value."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agent = _FakeAgent("a1")
    agentic = _ScriptedExecutor([_outcome()])
    runtime = _runtime()
    ex = CrewTaskExecutor(
        work_item_store=store,
        agent_registry=_FakeRegistry({"a1": agent}),
        agentic_executor=agentic,  # type: ignore[arg-type]
        runtime=runtime,
        max_parallel_subtasks=3,
    )

    await ex.run(parent.id)

    assert len(agentic.calls) == 1
    call = agentic.calls[0]
    expected = {
        "agent_id": "a1",
        "instructions": "do the thing",
        "task_text": child.description,
        "runtime": runtime,
        "thread_id": "",
        "extra_context": {
            "_crew_session_id": parent.id,
            "_crew_work_item_id": child.id,
        },
    }
    assert call == expected
    assert list(call) == list(expected)


async def test_gate_off_instantiates_zero_session_compactors(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _CountingCompactorFactory.instances.clear()
    monkeypatch.setattr(
        session_compactor_module, "SessionCompactor", _CountingCompactorFactory
    )

    await _run_one(store, _ScriptedExecutor([_outcome()]))

    assert _CountingCompactorFactory.instances == []


async def test_work_item_agentic_executor_run_signature_is_unchanged() -> None:
    """The five other callers of ``run`` must be untouched BY CONSTRUCTION."""
    params = inspect.signature(WorkItemAgenticExecutor.run).parameters
    assert list(params) == [
        "self",
        "agent_id",
        "instructions",
        "task_text",
        "runtime",
        "department",
        "rank",
        "thread_id",
        "max_iterations",
        "tier",
        "extra_context",
        "compactor",
        "compaction_threshold",
        "token_budget",
    ]
    assert not any(
        "loop_until_done" in name or "continuation" in name for name in params
    )


async def test_converge_for_session_still_passes_no_token_budget() -> None:
    """DD-9 / BF-683: pinned as a KNOWN gap rather than an accident. The
    correction rounds run outside the AD-1142 ceilings, and this AD's budget
    arithmetic deliberately does not depend on them being budgeted."""
    source = inspect.getsource(SubtaskVerifier.converge_for_session)
    assert "token_budget" not in source
    assert "compactor" not in source


async def test_crew_verifier_and_finalizer_carry_no_ad1155_changes() -> None:
    """The convergence loop and the finalizer are explicitly out of scope."""
    root = Path(__file__).resolve().parents[1] / "src" / "probos" / "cognitive"
    for name in ("crew_verifier.py", "crew_finalizer.py"):
        assert "AD-1155" not in (root / name).read_text(encoding="utf-8"), name


# ===========================================================================
# 3. Predicates (DD-2) and re-invokability (DD-6)
# ===========================================================================

async def test_stopped_reason_predicate_continues_on_max_iterations(store) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert len(agentic.calls) == 2


@pytest.mark.parametrize("reason", ["complete", "token_budget", "error"])
async def test_stopped_reason_predicate_stops_on_every_other_value(
    store, reason: str
) -> None:
    agentic = _ScriptedExecutor([_outcome(stopped_reason=reason)])

    await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert len(agentic.calls) == 1


async def test_completion_marker_stops_when_the_marker_is_in_the_tail(
    store,
) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text="all set\nTASK COMPLETE")]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_COMPLETION_MARKER,
    )

    assert len(agentic.calls) == 1


async def test_completion_marker_continues_when_the_marker_is_absent(
    store,
) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text="half done"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_COMPLETION_MARKER,
    )

    assert len(agentic.calls) == 2


async def test_completion_marker_ignores_a_marker_outside_the_trailing_window(
    store,
) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(
                stopped_reason="max_iterations",
                final_text="TASK COMPLETE" + "z" * 500,
            ),
            _outcome(),
        ]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_COMPLETION_MARKER,
    )

    assert len(agentic.calls) == 2


async def test_completion_marker_predicate_still_stops_on_a_complete_stop(
    store,
) -> None:
    """DD-6's precondition binds BEFORE the predicate: the model choosing to
    stop is not the failure this AD addresses."""
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="complete", final_text="no marker here"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_COMPLETION_MARKER,
    )

    assert len(agentic.calls) == 1


async def test_open_todos_with_an_empty_step_list_stops(store) -> None:
    """**The C-2 #2 regression, and the most important test in this file.**

    Issue #1082's literal ``not _all_steps_done(child.steps)`` is asserted here
    against the REAL ``workforce._all_steps_done`` to show it would CONTINUE,
    and the shipped predicate is asserted to STOP. The crew fan-out never writes
    ``WorkItem.steps``, so every crew child hits this path — a naive
    implementation re-invokes all of them to the cap, always.
    """
    assert _all_steps_done([]) is False
    assert (not _all_steps_done([])) is True  # what #1082 would have shipped
    assert _actionable_step_labels([]) is None  # what this AD ships

    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        steps=[],
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=5,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_OPEN_TODOS,
    )

    assert len(agentic.calls) == 1


async def test_open_todos_stops_when_only_done_and_submitted_remain(store) -> None:
    """``submitted -> done`` needs rank >= ``room_todos_min_rank`` (commander,
    trust >= 0.7) and built-ins seed at Beta(2,2) = 0.50 => lieutenant. The
    modal crew agent cannot close its own submitted step, so re-invoking it is
    guaranteed-futile work."""
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        steps=[
            {"label": "survey", "status": "done"},
            {"label": "rebalance", "status": "submitted"},
        ],
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_OPEN_TODOS,
    )

    assert len(agentic.calls) == 1


@pytest.mark.parametrize("open_status", ["pending", "in_progress", "rejected"])
async def test_open_todos_continues_when_an_actionable_step_remains(
    store, open_status: str
) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        steps=[
            {"label": "survey", "status": "done"},
            {"label": "rebalance", "status": open_status},
        ],
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_predicate=_LOOP_PREDICATE_OPEN_TODOS,
    )

    assert len(agentic.calls) == 2


@pytest.mark.parametrize(
    "steps",
    [
        None,
        {"label": "a", "status": "pending"},
        ["pending"],
        [{"label": "a", "status": "not-a-real-status"}],
        [{"label": "a", "status": 7}],
    ],
    ids=["none", "dict", "non-dict-member", "unknown-status", "non-str-status"],
)
async def test_malformed_steps_stop_without_raising(
    steps: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.crew_executor"):
        labels = _actionable_step_labels(steps, child_id="c1")

    assert labels is None
    continued, reason = _should_continue(
        _outcome(stopped_reason="max_iterations"),
        iteration=1,
        max_iterations=3,
        predicate=_LOOP_PREDICATE_OPEN_TODOS,
        completion_marker=_DEFAULT_COMPLETION_MARKER,
        no_progress_streak=0,
        actionable_labels=labels,
    )
    assert continued is False
    assert reason == "todos_inapplicable"
    if steps is not None:
        assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_actionable_statuses_are_a_subset_of_the_step_vocabulary() -> None:
    assert _ACTIONABLE_STEP_STATUSES <= STEP_STATUSES
    assert _ACTIONABLE_STEP_STATUSES == {"pending", "in_progress", "rejected"}
    assert "submitted" not in _ACTIONABLE_STEP_STATUSES
    assert "done" not in _ACTIONABLE_STEP_STATUSES


async def test_reinvokable_stopped_reasons_is_a_guarded_subset() -> None:
    """The drift guard: a future ``stopped_reason`` cannot be silently
    admitted, because the set ADMITS rather than EXCLUDES."""
    assert _REINVOKABLE_STOPPED_REASONS <= _STOPPED_REASONS
    assert _REINVOKABLE_STOPPED_REASONS == {"max_iterations"}


@pytest.mark.parametrize("reason", sorted(_STOPPED_REASONS - {"max_iterations"}))
async def test_every_non_max_iterations_reason_stops_under_every_predicate(
    reason: str,
) -> None:
    for predicate in sorted(_LOOP_PREDICATES):
        continued, why = _should_continue(
            _outcome(stopped_reason=reason, final_text="no marker"),
            iteration=1,
            max_iterations=5,
            predicate=predicate,
            completion_marker=_DEFAULT_COMPLETION_MARKER,
            no_progress_streak=0,
            actionable_labels=["still open"],
        )
        assert continued is False, (predicate, reason)
        assert why == f"stopped_reason_terminal:{reason}"


@pytest.mark.parametrize(
    "value", ["nonsense", "", None, 7, True, _LOOP_PREDICATE_OPEN_TODOS.upper()]
)
async def test_an_unknown_predicate_normalises_to_the_default(value: Any) -> None:
    assert _normalize_loop_until_done_predicate(value) == _LOOP_PREDICATE_STOP_REASON


async def test_known_predicates_survive_normalisation() -> None:
    for predicate in _LOOP_PREDICATES:
        assert _normalize_loop_until_done_predicate(predicate) == predicate


async def test_only_open_todos_pays_a_parent_round_trip(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store read per outer iteration is a real cost; the other two
    predicates must not pay it."""
    original = store.get_work_item
    reads: list[str] = []

    async def _counting(work_item_id: str):
        reads.append(work_item_id)
        return await original(work_item_id)

    monkeypatch.setattr(store, "get_work_item", _counting)

    parent_reads: dict[str, int] = {}
    for predicate in (
        _LOOP_PREDICATE_STOP_REASON,
        _LOOP_PREDICATE_COMPLETION_MARKER,
        _LOOP_PREDICATE_OPEN_TODOS,
    ):
        parent = await store.create_work_item(
            title="parent", work_type="work_order"
        )
        await store.set_steps(
            parent.id, [{"label": "open one", "status": "pending"}]
        )
        await _child(store, parent_id=parent.id)
        reads.clear()
        agentic = _ScriptedExecutor(
            [_outcome(stopped_reason="max_iterations", final_text="x"), _outcome()]
        )
        ex = _executor(
            store,
            _FakeRegistry({"a1": _FakeAgent("a1")}),
            agentic,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_predicate=predicate,
        )
        await ex.run(parent.id)
        assert len(agentic.calls) == 2, predicate
        parent_reads[predicate] = reads.count(parent.id)

    assert (
        parent_reads[_LOOP_PREDICATE_STOP_REASON]
        == parent_reads[_LOOP_PREDICATE_COMPLETION_MARKER]
    )
    assert (
        parent_reads[_LOOP_PREDICATE_OPEN_TODOS]
        == parent_reads[_LOOP_PREDICATE_STOP_REASON] + 1
    )


# ===========================================================================
# 4. Caps and budget (DD-3)
# ===========================================================================

async def test_the_outer_cap_binds_and_the_last_outcome_is_persisted(
    store,
) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", final_text="pass one"),
            _outcome(stopped_reason="max_iterations", final_text="pass two"),
            _outcome(stopped_reason="max_iterations", final_text="pass three"),
        ]
    )

    row = await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=3,
    )

    assert len(agentic.calls) == 3
    execution = row.metadata["crew_execution"]
    assert execution["stopped_reason"] == "max_iterations"
    assert execution["output_summary"] == "pass three"


async def test_a_cap_of_one_runs_exactly_once_even_with_the_gate_on(
    store,
) -> None:
    """The cap is a bound, never an enable."""
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=1,
    )

    assert len(agentic.calls) == 1


async def test_the_budget_is_carried_forward_as_a_remainder(store) -> None:
    """A ceiling, not an allowance: resetting per iteration would multiply the
    operator's spend ceiling by the outer cap."""
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", total_tokens=7_000),
            _outcome(total_tokens=1_000),
        ]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_token_budget=10_000,
    )

    assert len(agentic.calls) == 2
    assert agentic.calls[0]["token_budget"] == 10_000
    assert agentic.calls[1]["token_budget"] == 3_000


async def test_a_sub_floor_remainder_stops_before_the_next_iteration(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", total_tokens=9_500), _outcome()]
    )

    with caplog.at_level(logging.INFO, logger="probos.cognitive.crew_executor"):
        await _run_one(
            store,
            agentic,
            crew_loop_until_done_enabled=True,
            crew_token_budget=10_000,
        )

    assert len(agentic.calls) == 1
    assert 10_000 - 9_500 < _MIN_CREW_TOKEN_BUDGET
    assert any("budget_exhausted" in r.getMessage() for r in caplog.records)


async def test_no_token_budget_key_appears_when_none_is_configured(store) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", total_tokens=500),
            _outcome(stopped_reason="max_iterations", total_tokens=500),
            _outcome(total_tokens=500),
        ]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=3,
    )

    assert len(agentic.calls) == 3
    for call in agentic.calls:
        assert "token_budget" not in call


async def test_a_fresh_compactor_is_built_for_every_iteration(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _CountingCompactorFactory.instances.clear()
    monkeypatch.setattr(
        session_compactor_module, "SessionCompactor", _CountingCompactorFactory
    )
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations"),
            _outcome(stopped_reason="max_iterations"),
            _outcome(),
        ]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=3,
        crew_compaction_enabled=True,
    )

    assert len(agentic.calls) == 3
    assert len(_CountingCompactorFactory.instances) == 3
    seen = [call["compactor"] for call in agentic.calls]
    for i, left in enumerate(seen):
        for right in seen[i + 1:]:
            assert left is not right


@pytest.mark.parametrize(
    "value", [0, 6, 99, -1, "3", True, None, 3.0],
)
async def test_out_of_range_caps_clamp_to_the_default_and_never_raise(
    value: Any,
) -> None:
    assert (
        _normalize_loop_until_done_max_iterations(value)
        == _LOOP_UNTIL_DONE_MAX_ITERATIONS
    )


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5])
async def test_in_range_caps_are_preserved(value: int) -> None:
    assert _normalize_loop_until_done_max_iterations(value) == value


@pytest.mark.parametrize("value", [None, 0, 1, "true", "True", "", [], object()])
async def test_only_a_literal_true_arms_the_gate(value: Any) -> None:
    assert _normalize_loop_until_done_enabled(value) is False


async def test_a_literal_true_arms_the_gate() -> None:
    assert _normalize_loop_until_done_enabled(True) is True


@pytest.mark.parametrize("value", [None, "", "   ", 7, b"x", []])
async def test_a_malformed_marker_degrades_to_the_default(value: Any) -> None:
    """An empty marker is contained in every string, so degrading to ``""``
    would silently disable the predicate the operator just armed."""
    assert _normalize_completion_marker(value) == _DEFAULT_COMPLETION_MARKER


async def test_a_long_marker_is_bounded() -> None:
    assert len(_normalize_completion_marker("M" * 5_000)) == 120


# ===========================================================================
# 5. Continuation text (DD-4)
# ===========================================================================

async def test_iteration_one_receives_the_task_text_by_identity(store) -> None:
    """Identity, not equality — the exact object AD-1141 produced."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        crew_loop_until_done_enabled=True,
    )
    captured: list[str] = []
    original = ex._augment_task_text

    async def _capturing(base: str, **kwargs: Any) -> str:
        result = await original(base, **kwargs)
        captured.append(result)
        return result

    ex._augment_task_text = _capturing  # type: ignore[assignment]

    await ex.run(parent.id)

    assert len(agentic.calls) == 2
    assert agentic.calls[0]["task_text"] is captured[0]
    assert captured[0] == child.description


async def test_iteration_two_extends_iteration_one(store) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", final_text="halfway there"),
            _outcome(),
        ]
    )

    await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    first = agentic.calls[0]["task_text"]
    second = agentic.calls[1]["task_text"]
    assert second.startswith(first)
    assert len(second) > len(first)
    assert _CONTINUATION_STOP_REASON_NOTE in second
    assert "halfway there" in second


async def test_the_continuation_never_stacks_across_iterations(store) -> None:
    """Each iteration rebuilds from the BASE text, so five passes do not carry
    four stacked blocks."""
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text=f"pass {i}")
         for i in range(1, 6)]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=5,
    )

    assert len(agentic.calls) == 5
    for call in agentic.calls[1:]:
        assert call["task_text"].count(_CONTINUATION_HEADER) == 1
        assert len(call["task_text"]) <= (
            len(agentic.calls[0]["task_text"]) + _MAX_CONTINUATION_CHARS
        )


async def test_the_persisted_description_is_byte_identical_after_three_passes(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    before = child.description
    before_hashes = _plan_identity(child)
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text="partial")]
    )
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=3,
    )

    await ex.run(parent.id)

    assert len(agentic.calls) == 3
    row = await store.get_work_item(child.id)
    assert row.description == before
    assert _plan_identity(row) == before_hashes


_CREW_EXECUTION_KEYS = frozenset({
    "version",
    "parent_id",
    "work_item_id",
    "thread_id",
    "assigned_to",
    "status",
    "stopped_reason",
    "output_summary",
    "tool_trace_ref",
    "artifact_refs",
    "tokens_used",
    "started_at",
    "finished_at",
    "blocked_dependency_ids",
})


async def test_the_evidence_record_is_still_the_exact_fourteen_key_set(
    store,
) -> None:
    """The set is frozen and cannot carry a list of intermediate trace refs;
    inventing a companion key is the 'one extra breaks recovery' hazard."""
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    row = await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert frozenset(row.metadata["crew_execution"]) == _CREW_EXECUTION_KEYS
    assert len(_CREW_EXECUTION_KEYS) == 14
    assert not any(
        "loop" in key or "iteration" in key or "continuation" in key
        for key in row.metadata["crew_execution"]
    )


async def test_subtask_result_field_set_is_unchanged() -> None:
    assert len({f.name for f in dataclasses.fields(SubtaskResult)}) == 12


async def test_a_fifty_thousand_char_prior_output_is_truncated_with_a_marker(
) -> None:
    block = _render_continuation(
        previous_output="q" * 50_000, todo_labels=None, completion_marker=None
    )

    assert len(block) <= _MAX_CONTINUATION_CHARS
    assert "characters elided from your previous output" in block
    assert "48" in block or "47" in block  # the elided count is reported
    assert block.count("q") <= _MAX_CONTINUATION_OUTPUT_CHARS


async def test_the_worst_case_block_stays_inside_its_budget() -> None:
    block = _render_continuation(
        previous_output="q" * 50_000,
        todo_labels=[f"{'L' * 400} {i}" for i in range(60)],
        completion_marker="TASK COMPLETE",
    )

    assert len(block) <= _MAX_CONTINUATION_CHARS
    assert block.count("\n- ") <= _MAX_CONTINUATION_TODOS


async def test_todo_labels_appear_only_under_the_open_todos_predicate(
    store,
) -> None:
    steps = [
        {"label": "survey", "status": "done"},
        {"label": "rebalance the manifold", "status": "pending"},
    ]
    for predicate, expect_labels in (
        (_LOOP_PREDICATE_OPEN_TODOS, True),
        (_LOOP_PREDICATE_STOP_REASON, False),
    ):
        agentic = _ScriptedExecutor(
            [_outcome(stopped_reason="max_iterations", final_text="x"), _outcome()]
        )
        await _run_one(
            store,
            agentic,
            steps=steps,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_predicate=predicate,
        )
        second = agentic.calls[1]["task_text"]
        assert (_CONTINUATION_TODO_HEADER in second) is expect_labels, predicate
        assert ("rebalance the manifold" in second) is expect_labels, predicate


async def test_the_marker_instruction_appears_only_under_that_predicate(
    store,
) -> None:
    for predicate, expect in (
        (_LOOP_PREDICATE_COMPLETION_MARKER, True),
        (_LOOP_PREDICATE_STOP_REASON, False),
    ):
        agentic = _ScriptedExecutor(
            [_outcome(stopped_reason="max_iterations", final_text="x"), _outcome()]
        )
        await _run_one(
            store,
            agentic,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_predicate=predicate,
        )
        second = agentic.calls[1]["task_text"]
        assert ("end your final message with the exact line" in second) is expect


async def test_a_raising_continuation_stops_cleanly_without_an_exception_status(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A composition failure must degrade to 'stop the loop', never to
    ``stopped_reason="execution_exception"``."""
    from probos.cognitive import crew_executor as module

    def _boom(**_kwargs: Any) -> str:
        raise RuntimeError("the renderer is down")

    monkeypatch.setattr(module, "_render_continuation", _boom)
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text="partial work"),
         _outcome()]
    )

    row = await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert len(agentic.calls) == 1
    execution = row.metadata["crew_execution"]
    assert execution["stopped_reason"] == "max_iterations"
    assert execution["stopped_reason"] != "execution_exception"
    assert execution["output_summary"] == "partial work"


async def test_an_empty_continuation_block_stops_the_loop(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probos.cognitive import crew_executor as module

    monkeypatch.setattr(module, "_render_continuation", lambda **_kw: "")
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations"), _outcome()]
    )

    row = await _run_one(store, agentic, crew_loop_until_done_enabled=True)

    assert len(agentic.calls) == 1
    assert row.metadata["crew_execution"]["stopped_reason"] == "max_iterations"


async def test_every_authored_string_is_clean_under_the_real_gap_regex() -> None:
    """Re-run against the IMPORTED regex, not a re-typed copy. ``lack`` is a
    bare substring in it and "you were unable to complete" trips it twice."""
    authored = [
        _CONTINUATION_HEADER,
        _CONTINUATION_STOP_REASON_NOTE,
        _CONTINUATION_OUTPUT_HEADER,
        _CONTINUATION_OUTPUT_ELISION.format(omitted=1234),
        _CONTINUATION_TODO_HEADER,
        _CONTINUATION_MARKER_INSTRUCTION.format(marker=_DEFAULT_COMPLETION_MARKER),
        _DEFAULT_COMPLETION_MARKER,
    ]
    for text in authored:
        assert _CAPABILITY_GAP_RE.search(text) is None, text


async def test_every_rendered_block_is_clean_under_the_real_gap_regex() -> None:
    for todo_labels in (None, ["rebalance the manifold", "log the reading"]):
        for marker in (None, _DEFAULT_COMPLETION_MARKER):
            for output in ("", "partial work so far", "z" * 50_000):
                block = _render_continuation(
                    previous_output=output,
                    todo_labels=todo_labels,
                    completion_marker=marker,
                )
                assert _CAPABILITY_GAP_RE.search(block) is None, block[:200]


# ===========================================================================
# 6. No-progress detection (DD-5)
# ===========================================================================

async def test_two_consecutive_no_progress_iterations_stop_before_the_cap(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    agentic = _ScriptedExecutor(
        [_outcome(stopped_reason="max_iterations", final_text="the same text")]
    )

    with caplog.at_level(logging.INFO, logger="probos.cognitive.crew_executor"):
        await _run_one(
            store,
            agentic,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_max_iterations=5,
        )

    assert len(agentic.calls) == 3
    assert any("no_progress" in r.getMessage() for r in caplog.records)


async def test_an_artifact_resets_the_no_progress_streak(store) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", final_text="same"),
            _outcome(
                stopped_reason="max_iterations",
                final_text="same",
                artifact_refs=[{"artifact_id": "a", "content_hash": "h"}],
            ),
            _outcome(stopped_reason="max_iterations", final_text="same"),
            _outcome(stopped_reason="max_iterations", final_text="same"),
        ]
    )

    await _run_one(
        store,
        agentic,
        crew_loop_until_done_enabled=True,
        crew_loop_until_done_max_iterations=5,
    )

    assert len(agentic.calls) == 4


async def test_changed_final_text_counts_as_progress() -> None:
    assert _iteration_made_progress(
        _outcome(final_text="second pass"),
        previous_text_hash=hashlib.sha256(b"first pass").hexdigest(),
        previous_actionable_count=None,
        actionable_count=None,
    ) is True


async def test_identical_text_with_no_artifacts_is_no_progress() -> None:
    assert _iteration_made_progress(
        _outcome(final_text="same"),
        previous_text_hash=hashlib.sha256(b"same").hexdigest(),
        previous_actionable_count=None,
        actionable_count=None,
    ) is False


async def test_closing_a_todo_counts_as_progress() -> None:
    assert _iteration_made_progress(
        _outcome(final_text="same"),
        previous_text_hash=hashlib.sha256(b"same").hexdigest(),
        previous_actionable_count=3,
        actionable_count=2,
    ) is True


async def test_the_first_iteration_always_counts_as_progress() -> None:
    assert _iteration_made_progress(
        _outcome(final_text=""),
        previous_text_hash=None,
        previous_actionable_count=None,
        actionable_count=None,
    ) is True


# ===========================================================================
# 7. Governance per iteration (DD-8)
# ===========================================================================

async def test_each_iteration_persists_a_distinct_tool_trace_and_keeps_the_last(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    agentic = _ScriptedExecutor(
        [
            _outcome(stopped_reason="max_iterations", final_text="one",
                     tool_trace_ref="1" * 64),
            _outcome(stopped_reason="max_iterations", final_text="two",
                     tool_trace_ref="2" * 64),
            _outcome(final_text="three", tool_trace_ref="3" * 64),
        ]
    )

    with caplog.at_level(logging.INFO, logger="probos.cognitive.crew_executor"):
        row = await _run_one(
            store,
            agentic,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_max_iterations=3,
        )

    assert row.metadata["crew_execution"]["tool_trace_ref"] == "3" * 64
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "1" * 64 in logged
    assert "2" * 64 in logged


async def test_trust_demotion_between_iterations_removes_the_browser_tool(
    store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cheapest available proof that iterations are genuinely independent
    runs rather than a resumed session. REAL ``ToolRegistry`` + REAL
    ``ToolPermissionStore`` (BF-287) and the REAL ``_resolve_agentic_identity``
    / ``check_permission`` offer gate — a mock at that boundary would paper over
    exactly the thing being proved. Only the ``AgenticLoop`` itself is stubbed,
    and only so the run terminates at ``max_iterations`` without 25 live turns;
    the tool set it receives was resolved by the real gate."""
    from probos.cognitive.swe_harness import agentic_loop as agentic_loop_module
    from probos.config import BrowserToolConfig
    from probos.security.audit import AuditLog
    from probos.tools.browser.tool import BrowserTool
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.registry import ToolRegistry

    offered: list[list[str]] = []
    scripted = ["max_iterations", "complete"]

    class _RecordingLoop:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, *, tools: list[dict], **_kwargs: Any) -> Any:
            index = min(len(offered), len(scripted) - 1)
            offered.append(
                [(t.get("function") or {}).get("name") for t in tools]
            )
            return SimpleNamespace(
                final_text="stopped early",
                stopped_reason=scripted[index],
                total_tokens=1,
                iterations=1,
                error="",
                tool_calls=[],
                tool_results=[],
                token_source="measured",
            )

    monkeypatch.setattr(agentic_loop_module, "AgenticLoop", _RecordingLoop)

    class _DemotingTrustNetwork:
        """0.55 => lieutenant (browser: read) then 0.30 => ensign (none)."""

        def __init__(self) -> None:
            self.scores = [0.55, 0.30]
            self.calls = 0

        def get_score(self, _agent_id: str) -> float:
            score = self.scores[min(self.calls, len(self.scores) - 1)]
            self.calls += 1
            return score

    perm_store = ToolPermissionStore(db_path=":memory:")
    await perm_store.start()
    browser = BrowserTool(
        config=BrowserToolConfig(enabled=True), audit_log=AuditLog(), emit_event=None
    )
    trust = _DemotingTrustNetwork()
    try:
        tool_registry = ToolRegistry()
        tool_registry.register(
            browser,
            domain="*",
            tags=["browser", "computer_use"],
            provider="ship_computer",
            enabled=True,
            default_permissions={
                "ensign": "none",
                "lieutenant": "read",
                "commander": "write",
                "senior_officer": "full",
            },
            concurrency="concurrent",
        )
        tool_registry.set_permission_store(perm_store)

        agent_registry = _FakeRegistry({"a1": _FakeAgent("a1")})
        runtime = SimpleNamespace(
            tool_registry=tool_registry,
            tool_permission_store=perm_store,
            intent_bus=None,
            intent_grant_store=None,
            mcp_workbench=None,
            cognitive_skill_catalog=None,
            attachment_store=None,
            episodic_memory=None,
            emit_event=None,
            registry=agent_registry,
            ontology=SimpleNamespace(
                get_agent_department=lambda _t: "engineering"
            ),
            trust_network=trust,
            config=SimpleNamespace(
                execution=SimpleNamespace(enabled=False),
                mcp=SimpleNamespace(agent_tools_enabled=False),
                browser_tool=BrowserToolConfig(enabled=True),
                agentic_tools=SimpleNamespace(
                    tool_search_enabled=False,
                    delegation_enabled=False,
                    browser_enabled=True,
                ),
                agentic_loop=None,
            ),
        )

        parent = await store.create_work_item(
            title="parent", work_type="work_order"
        )
        await _child(store, parent_id=parent.id)
        ex = _executor(
            store,
            agent_registry,
            WorkItemAgenticExecutor(llm_client=object()),
            runtime=runtime,
            crew_loop_until_done_enabled=True,
            crew_loop_until_done_max_iterations=2,
        )

        await ex.run(parent.id)
    finally:
        await browser.stop()
        await perm_store.stop()

    assert len(offered) == 2, offered
    assert trust.calls == 2  # live re-resolution, not a cached identity
    assert "browser" in offered[0]
    assert "browser" not in offered[1]


# ===========================================================================
# 8. Config (DD-3, DD-7)
# ===========================================================================

async def test_the_shipped_defaults_are_off_and_documented() -> None:
    cfg = AgenticDispatchConfig()
    assert cfg.crew_loop_until_done_enabled is False
    assert cfg.crew_loop_until_done_max_iterations == _LOOP_UNTIL_DONE_MAX_ITERATIONS
    assert cfg.crew_loop_until_done_predicate == _LOOP_PREDICATE_STOP_REASON
    assert cfg.crew_loop_until_done_completion_marker == _DEFAULT_COMPLETION_MARKER


async def test_the_cap_bounds_match_the_module_clamp() -> None:
    field = AgenticDispatchConfig.model_fields["crew_loop_until_done_max_iterations"]
    bounds = {type(m).__name__: getattr(m, "ge", getattr(m, "le", None))
              for m in field.metadata}
    assert bounds.get("Ge") == 1
    assert bounds.get("Le") == 5
    assert _normalize_loop_until_done_max_iterations(5) == 5
    assert _normalize_loop_until_done_max_iterations(6) == (
        _LOOP_UNTIL_DONE_MAX_ITERATIONS
    )


async def test_system_config_still_constructs_with_zero_configuration() -> None:
    cfg = SystemConfig()
    assert cfg.agentic_dispatch.crew_loop_until_done_enabled is False


async def test_the_config_reference_documents_the_four_way_worst_case() -> None:
    """A doc-grep, following the AD-1142 Section 11 precedent. The worst case
    is the operator's only warning that this knob multiplies four ways."""
    doc = (
        Path(__file__).resolve().parents[1]
        / "docs" / "development" / "config-reference.md"
    ).read_text(encoding="utf-8")

    assert "crew_loop_until_done_enabled" in doc
    assert "5 x 25 x 16 = 2000 tool invocations" in doc
    assert "convergence x outer x inner x parallel" in doc
    assert "SHARED" in doc and "carried forward as a remainder" in doc
    assert "crew fan-out never writes WorkItem.steps" in doc


async def test_the_budget_field_cross_references_the_loop_feature() -> None:
    description = AgenticDispatchConfig.model_fields[
        "crew_token_budget"
    ].description or ""
    assert "AD-1155" in description
    assert "crew_loop_until_done_enabled" in description
