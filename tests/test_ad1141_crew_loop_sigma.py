"""AD-1141: crew loop wired to Σ — consult before, publish after.

The suite is organised by the acceptance sections of the AD, and section 1 is
load-bearing above all the others: **with the flags off, crew behaviour must be
byte-identical to pre-AD-1141.** Today's isolated-children behaviour is the
Nooplex §8.3 ablation control arm and the live Σ-off baseline has not been
captured yet, so an OFF path that is merely "equivalent" destroys the only
empirical claim the Σ epic makes. Those tests assert identity, exact key sets
and zero Oracle calls rather than approximate sameness.
"""

from __future__ import annotations

import dataclasses
import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.crew_executor import (
    _BUDGET_NOTE,
    _COMMONS_DISPOSITION,
    _COMMONS_HEADER,
    _EMPTY_CONSULT_NOTE,
    _EXPECTED_OUTPUT_DISPOSITION,
    _EXPECTED_OUTPUT_HEADER,
    _MAX_CONSULT_QUERY_CHARS,
    _MAX_ENTRY_CHARS,
    _MAX_EXPECTED_OUTPUT_CHARS,
    _MIN_CONSULT_QUERY_CHARS,
    _PUBLISH_NUDGE,
    CrewTaskExecutor,
    SubtaskResult,
    _compose_child_task_text,
    _render_commons_block,
    _render_expected_output_block,
)
# The REAL regex, imported rather than re-typed. ``lack`` is a bare substring in
# it, so "black hole" / "slack" / "blackhole" all trip it — AD-1140 hit this for
# real, which is why a re-typed copy is not acceptable here.
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.oracle_service import OracleResult, OracleService
from probos.config import AgenticToolsConfig, RecordsConfig, SystemConfig
from probos.knowledge.records_store import RecordsStore
from probos.tools.oracle_query_tool import SIGMA_TIERS, SOVEREIGN_TIER
from probos.tools.publish_finding_tool import PublishFindingTool
from probos.workforce import WorkItemStore

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Doubles
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
        if agent_id is None:
            return None
        return self._agents.get(agent_id)

    def all(self) -> list[_FakeAgent]:
        return list(self._agents.values())


class _RecordingExecutor:
    """Records the **exact** kwargs of every ``run`` call.

    Criterion #1 needs the ``task_text`` and ``extra_context`` as passed, plus
    the full kwarg key set — the latter is how "nothing new was threaded
    through to the dispatch" is proven, since ``tool_ids`` is assembled inside
    ``WorkItemAgenticExecutor.run`` from surfaces this AD does not touch.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> WorkItemAgenticOutcome:
        self.calls.append(dict(kwargs))
        return WorkItemAgenticOutcome(
            final_text="done",
            stopped_reason="complete",
            tool_trace_ref="d" * 64,
        )

    @property
    def task_texts(self) -> list[str]:
        return [call["task_text"] for call in self.calls]


class _RecordingOracle:
    """Counts ``query`` calls and returns a fixed result list."""

    def __init__(self, results: list[OracleResult] | None = None) -> None:
        self.results = results or []
        self.calls: list[dict[str, Any]] = []

    async def query(self, query_text: str, **kwargs: Any) -> list[OracleResult]:
        self.calls.append({"query_text": query_text, **kwargs})
        return list(self.results)


class _RaisingOracle:
    def __init__(self) -> None:
        self.calls = 0

    async def query(self, *_a: Any, **_kw: Any) -> list[OracleResult]:
        self.calls += 1
        raise RuntimeError("the commons is unreachable")


class _RecordingEpisodic:
    """Sovereignty: any touch of the per-agent shard from the consult path is a
    test failure."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def store(self, *_a: Any, **_kw: Any) -> None:
        self.calls.append("store")

    async def recall(self, *_a: Any, **_kw: Any) -> list[Any]:
        self.calls.append("recall")
        return []

    async def recall_for_agent_scored(self, *_a: Any, **_kw: Any) -> list[Any]:
        self.calls.append("recall_for_agent_scored")
        return []


class _FakeToolRegistry:
    def __init__(self, registered: set[str] | None = None) -> None:
        self._registered = registered or set()

    def get(self, tool_id: str) -> object | None:
        return object() if tool_id in self._registered else None


class _RaisingToolRegistry:
    def get(self, tool_id: str) -> object | None:
        raise RuntimeError("registry is down")


class _StaticResolver:
    def __init__(self, mapping: dict[str, tuple[str, str]]) -> None:
        self._mapping = mapping

    def __call__(self, agent_id: str) -> tuple[str, str]:
        return self._mapping.get(agent_id, ("", ""))


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


def _runtime(*, tools: set[str] | None = None, episodic: Any = None) -> Any:
    return SimpleNamespace(
        tool_registry=_FakeToolRegistry(tools),
        episodic_memory=episodic,
        attachment_store=None,
    )


def _executor(
    store: WorkItemStore,
    registry: _FakeRegistry,
    agentic: Any,
    *,
    runtime: Any = None,
    oracle: Any = None,
    enabled: bool = False,
    max_chars: int = 2000,
    max_entries: int = 4,
    min_score: float = 0.35,
) -> CrewTaskExecutor:
    return CrewTaskExecutor(
        work_item_store=store,
        agent_registry=registry,
        agentic_executor=agentic,  # type: ignore[arg-type]
        runtime=runtime if runtime is not None else _runtime(),
        max_parallel_subtasks=3,
        oracle=oracle,
        crew_sigma_context_enabled=enabled,
        crew_sigma_max_chars=max_chars,
        crew_sigma_max_entries=max_entries,
        crew_sigma_min_score=min_score,
    )


async def _child(
    store: WorkItemStore,
    *,
    parent_id: str,
    title: str = "Rebalance the coolant manifold",
    description: str = "Rebalance the port coolant manifold and record the result.",
    assigned_to: str = "a1",
    spec_id: str = "s1",
    metadata: dict[str, Any] | None = None,
):
    meta: dict[str, Any] = {"spec_id": spec_id}
    if metadata:
        meta.update(metadata)
    return await store.create_work_item(
        title=title,
        description=description,
        work_type="task",
        parent_id=parent_id,
        assigned_to=assigned_to,
        metadata=meta,
    )


def _result(
    *,
    content: str = "The port coolant loop resonates at 4.2 kHz under load.",
    score: float = 0.9,
    tier: str = "records",
    provenance: str = "[ship's records]",
    timestamp: float | None = None,
) -> OracleResult:
    metadata: dict[str, Any] = {}
    if timestamp is not None:
        metadata["timestamp"] = timestamp
    return OracleResult(
        source_tier=tier,
        content=content,
        score=score,
        metadata=metadata,
        provenance=provenance,
    )


_AUTHORED_STRINGS: dict[str, str] = {
    "_COMMONS_HEADER": _COMMONS_HEADER,
    "_COMMONS_DISPOSITION": _COMMONS_DISPOSITION,
    "_EXPECTED_OUTPUT_HEADER": _EXPECTED_OUTPUT_HEADER,
    "_EXPECTED_OUTPUT_DISPOSITION": _EXPECTED_OUTPUT_DISPOSITION,
    "_PUBLISH_NUDGE": _PUBLISH_NUDGE,
    "_BUDGET_NOTE": _BUDGET_NOTE,
    "_EMPTY_CONSULT_NOTE": _EMPTY_CONSULT_NOTE,
}


# ===========================================================================
# 1. Byte-identity with the flags OFF — CRITERION #1
# ===========================================================================

async def test_compose_returns_base_by_identity_when_every_option_is_empty() -> None:
    """The OFF path is a provable no-op, not a re-render that happens to match."""
    base = "Rebalance the port coolant manifold."
    assert _compose_child_task_text(base) is base
    assert (
        _compose_child_task_text(
            base, commons_block="", expected_output_block="", publish_nudge="",
        )
        is base
    )


async def test_compose_returns_base_by_identity_for_empty_string_base() -> None:
    base = ""
    assert _compose_child_task_text(base) is base


async def test_flag_off_task_text_is_exactly_description_or_title(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic, enabled=False,
    )

    await ex.run(parent.id)

    # Literal recomputation, not a golden file.
    assert agentic.task_texts == [child.description or child.title or ""]


async def test_flag_off_task_text_falls_back_to_title_exactly(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id, description="")
    agentic = _RecordingExecutor()
    ex = _executor(
        store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic, enabled=False,
    )

    await ex.run(parent.id)

    assert agentic.task_texts == [child.title]


async def test_flag_off_extra_context_is_exactly_the_two_crew_keys(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic, enabled=False,
    )

    await ex.run(parent.id)

    assert agentic.calls[0]["extra_context"] == {
        "_crew_session_id": parent.id,
        "_crew_work_item_id": child.id,
    }


async def test_flag_on_extra_context_is_still_exactly_the_two_crew_keys(store) -> None:
    """DD-1: ``extra_context`` is the tool-invocation context and never reaches
    the prompt, so AD-1141 leaves it byte-identical in **both** arms."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert agentic.calls[0]["extra_context"] == {
        "_crew_session_id": parent.id,
        "_crew_work_item_id": child.id,
    }


async def test_flag_off_oracle_query_is_called_zero_times(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    oracle = _RecordingOracle([_result()])
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=oracle,
        enabled=False,
    )

    await ex.run(parent.id)

    assert oracle.calls == []


async def test_flag_off_run_kwarg_key_set_is_the_pre_ad1141_set(store) -> None:
    """Nothing new is threaded into ``WorkItemAgenticExecutor.run``.

    ``tool_ids`` is assembled inside the dispatch from the runtime, the config
    and the agent — surfaces this AD does not touch — so proving the crew
    executor passes exactly the pre-AD-1141 kwargs is what proves ``tool_ids``
    is byte-identical.
    """
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store, _FakeRegistry({"a1": _FakeAgent("a1")}), agentic, enabled=False,
    )

    await ex.run(parent.id)

    assert set(agentic.calls[0]) == {
        "agent_id",
        "instructions",
        "task_text",
        "runtime",
        "thread_id",
        "extra_context",
    }


async def test_flag_on_run_kwarg_key_set_is_unchanged(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert set(agentic.calls[0]) == {
        "agent_id",
        "instructions",
        "task_text",
        "runtime",
        "thread_id",
        "extra_context",
    }


async def test_persisted_evidence_is_key_for_key_identical_on_and_off(store) -> None:
    async def _evidence(enabled: bool) -> dict[str, Any]:
        parent = await store.create_work_item(title="parent", work_type="work_order")
        child = await _child(store, parent_id=parent.id, spec_id=f"s-{enabled}")
        ex = _executor(
            store,
            _FakeRegistry({"a1": _FakeAgent("a1")}),
            _RecordingExecutor(),
            oracle=_RecordingOracle([_result()]),
            enabled=enabled,
        )
        await ex.run(parent.id)
        row = await store.get_work_item(child.id)
        return dict(row.metadata["crew_execution"])

    off = await _evidence(False)
    on = await _evidence(True)

    assert set(off) == set(on)
    # Every value except the ids/timestamps that legitimately differ per run.
    volatile = {"parent_id", "work_item_id", "started_at", "finished_at"}
    assert {k: v for k, v in off.items() if k not in volatile} == {
        k: v for k, v in on.items() if k not in volatile
    }


# ===========================================================================
# 2. Crew contracts untouched
# ===========================================================================

_CREW_EXECUTION_KEYS = {
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
}

_SUBTASK_RESULT_FIELDS = {
    "work_item_id",
    "spec_id",
    "agent_id",
    "output",
    "status",
    "tool_trace_ref",
    "started_at",
    "finished_at",
    "stopped_reason",
    "actual_tokens",
    "artifact_refs",
    "blocked_dependency_ids",
}


async def test_crew_execution_evidence_is_the_exact_fourteen_key_set(store) -> None:
    """One extra key raises ``crew_execution_evidence_invalid`` on every restart."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    row = await store.get_work_item(child.id)
    assert set(row.metadata["crew_execution"]) == _CREW_EXECUTION_KEYS
    assert len(_CREW_EXECUTION_KEYS) == 14


async def test_subtask_result_field_set_is_frozen_at_twelve() -> None:
    names = {f.name for f in dataclasses.fields(SubtaskResult)}
    assert names == _SUBTASK_RESULT_FIELDS
    assert len(names) == 12


async def test_sigma_run_does_not_mutate_the_persisted_description(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    before = child.description
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    row = await store.get_work_item(child.id)
    assert row.description == before


async def test_plan_identity_hash_is_unchanged_by_a_sigma_on_run(store) -> None:
    """``description`` is inside the plan-identity hash, so the enriched string
    must never be persisted. Rebuild the projection from the LIVE post-run rows
    and assert the seed hash is bit-for-bit what the plan committed to."""
    from probos.cognitive.crew_session import (
        _build_derived_recovery_plan,
        _validate_contextual_recovery_plan,
    )
    from probos.consultation.dispatch import WorkItemSpec

    specs = [
        WorkItemSpec(
            spec_id="spec-a",
            title="Rebalance the coolant manifold",
            description="Rebalance the port coolant manifold and record it.",
            work_type="task",
        )
    ]
    plan, inserts = _build_derived_recovery_plan(
        "session-parent", specs, created_by="facilitator-1",
    )
    seed_before = plan.plan_seed_hash
    # AD-1127 recovery is green on the committed plan before the run.
    assert _validate_contextual_recovery_plan("session-parent", plan, inserts)

    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(
        store,
        parent_id=parent.id,
        title=specs[0].title,
        description=specs[0].description,
        spec_id="spec-a",
    )
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )
    await ex.run(parent.id)

    rows = await store.list_work_items(parent_id=parent.id, limit=10)
    rebuilt, _ = _build_derived_recovery_plan(
        "session-parent",
        [
            WorkItemSpec(
                spec_id="spec-a",
                title=rows[0].title,
                description=rows[0].description,
                work_type="task",
            )
        ],
        created_by="facilitator-1",
    )

    assert rebuilt.plan_seed_hash == seed_before
    # And AD-1127 recovery stays green afterwards.
    assert _validate_contextual_recovery_plan("session-parent", plan, inserts)


# ===========================================================================
# 3. Consult
# ===========================================================================

async def test_relevant_record_reaches_task_text_framed_and_provenance_marked(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle(
            [_result(content="Coolant resonance peaks at 4.2 kHz.", score=0.9)]
        ),
        enabled=True,
    )

    await ex.run(parent.id)

    task_text = agentic.task_texts[0]
    assert task_text.startswith(child.description)
    assert _COMMONS_HEADER in task_text
    assert _COMMONS_DISPOSITION in task_text
    assert "Coolant resonance peaks at 4.2 kHz." in task_text
    # Provenance marker: source tier and confidence.
    assert "[ship's records]" in task_text
    assert "confidence 0.90" in task_text
    row = await store.get_work_item(child.id)
    assert row.description == child.description


async def test_nothing_clears_the_floor_injects_zero_characters(store) -> None:
    """DD-3, the load-bearing zero-cost empty path: not an empty-body note, not
    a header, not a whitespace delta — the base string byte-for-byte."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    oracle = _RecordingOracle(
        [_result(score=0.34), _result(score=0.10), _result(score=0.0)]
    )
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=oracle,
        enabled=True,
        min_score=0.35,
    )

    await ex.run(parent.id)

    assert len(oracle.calls) == 1, "the Oracle should still be consulted once"
    assert agentic.task_texts[0] == child.description
    assert len(agentic.task_texts[0]) == len(child.description)


async def test_render_commons_block_returns_empty_string_below_the_floor() -> None:
    assert _render_commons_block(
        [_result(score=0.34)], max_chars=2000, max_entries=4, min_score=0.35,
    ) == ""


async def test_render_commons_block_returns_empty_string_for_no_results() -> None:
    assert _render_commons_block(
        [], max_chars=2000, max_entries=4, min_score=0.35,
    ) == ""


async def test_query_floor_skips_the_oracle_call_entirely(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    # title + "\n" + description must strip to under 24 chars.
    await _child(store, parent_id=parent.id, title="fix", description="it")
    oracle = _RecordingOracle([_result()])
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=oracle,
        enabled=True,
    )

    await ex.run(parent.id)

    assert oracle.calls == []
    assert agentic.task_texts == ["it"]
    assert _MIN_CONSULT_QUERY_CHARS == 24


async def test_consult_query_is_bounded_at_the_tool_query_cap(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id, description="d" * 5000)
    oracle = _RecordingOracle([])
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=oracle,
        enabled=True,
    )

    await ex.run(parent.id)

    assert len(oracle.calls[0]["query_text"]) == _MAX_CONSULT_QUERY_CHARS
    assert _MAX_CONSULT_QUERY_CHARS == 512


async def test_entry_cap_keeps_the_highest_scoring_entries() -> None:
    results = [_result(content=f"entry-{i}", score=0.4 + i / 100) for i in range(9)]
    block = _render_commons_block(
        results, max_chars=8000, max_entries=4, min_score=0.35,
    )
    kept = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(kept) == 4
    # Highest scores first: entry-8 .. entry-5.
    assert "entry-8" in kept[0]
    assert "entry-5" in kept[3]
    assert "entry-4" not in block


async def test_budget_note_appears_only_when_entries_were_dropped() -> None:
    dropped = _render_commons_block(
        [_result(content=f"e{i}", score=0.9) for i in range(9)],
        max_chars=8000,
        max_entries=4,
        min_score=0.35,
    )
    assert _BUDGET_NOTE in dropped

    intact = _render_commons_block(
        [_result(content="only one", score=0.9)],
        max_chars=8000,
        max_entries=4,
        min_score=0.35,
    )
    assert _BUDGET_NOTE not in intact


async def test_char_budget_is_enforced_and_reports_the_elision() -> None:
    results = [_result(content="x" * 900, score=0.9) for _ in range(4)]
    block = _render_commons_block(
        results, max_chars=1200, max_entries=4, min_score=0.35,
    )
    assert len(block) <= 1200
    assert _BUDGET_NOTE in block
    assert sum(1 for line in block.splitlines() if line.startswith("- ")) == 1


async def test_a_budget_too_small_for_one_entry_injects_zero_characters() -> None:
    """DD-3 again at the budget boundary: a header with no entries under it is
    still pure overhead, so the block collapses to nothing rather than to a
    frame around an empty body."""
    block = _render_commons_block(
        [_result(content="x" * 900, score=0.9)],
        max_chars=500,
        max_entries=4,
        min_score=0.35,
    )
    assert block == ""


async def test_entries_are_bounded_per_entry() -> None:
    block = _render_commons_block(
        [_result(content="y" * 5000, score=0.9)],
        max_chars=8000,
        max_entries=4,
        min_score=0.35,
    )
    entry = next(line for line in block.splitlines() if line.startswith("- "))
    assert len(entry) <= _MAX_ENTRY_CHARS
    assert _MAX_ENTRY_CHARS == 400


async def test_entry_marker_carries_an_age_when_a_timestamp_is_present() -> None:
    block = _render_commons_block(
        [_result(score=0.9, timestamp=time.time() - 3 * 86400)],
        max_chars=8000,
        max_entries=4,
        min_score=0.35,
    )
    assert "3d ago" in block


async def test_consult_uses_the_imported_sigma_tiers_and_never_episodic(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    oracle = _RecordingOracle([_result()])
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        _RecordingExecutor(),
        oracle=oracle,
        enabled=True,
    )

    await ex.run(parent.id)

    tiers = oracle.calls[0]["tiers"]
    assert tiers == list(SIGMA_TIERS)
    assert SOVEREIGN_TIER not in tiers
    assert "episodic" not in tiers


async def test_a_raising_consult_degrades_to_the_base_task_text(store, caplog) -> None:
    """DD-8: the consult sits OUTSIDE the executor's try, which persists
    ``execution_exception``. A commons outage must not fail every child."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    oracle = _RaisingOracle()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=oracle,
        enabled=True,
    )

    with caplog.at_level("WARNING"):
        results = await ex.run(parent.id)

    assert oracle.calls == 1
    assert agentic.task_texts == [child.description]
    assert [r.status for r in results] == ["done"]
    row = await store.get_work_item(child.id)
    assert row.metadata["crew_execution"]["stopped_reason"] == "complete"
    assert any("commons consult failed" in r.message for r in caplog.records)


async def test_a_raising_tool_registry_degrades_without_a_nudge(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        runtime=SimpleNamespace(
            tool_registry=_RaisingToolRegistry(), attachment_store=None,
        ),
        oracle=_RecordingOracle([]),
        enabled=True,
    )

    results = await ex.run(parent.id)

    assert _PUBLISH_NUDGE not in agentic.task_texts[0]
    assert agentic.task_texts[0] == child.description
    assert [r.status for r in results] == ["done"]


async def test_absent_oracle_with_the_flag_on_injects_no_commons_block(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=None,
        enabled=True,
    )

    await ex.run(parent.id)

    assert agentic.task_texts[0] == child.description


# ===========================================================================
# 4. Publish — nudge, ship budget, headline round trip
# ===========================================================================

async def test_publish_nudge_present_when_the_tool_is_registered(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        runtime=_runtime(tools={"publish_finding"}),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert _PUBLISH_NUDGE in agentic.task_texts[0]
    assert agentic.task_texts[0].rstrip().endswith(_PUBLISH_NUDGE)


async def test_publish_nudge_absent_when_the_tool_is_not_registered(store) -> None:
    """Do not nudge an agent toward a verb it does not hold."""
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        runtime=_runtime(tools=set()),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert _PUBLISH_NUDGE not in agentic.task_texts[0]


@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    store = RecordsStore(
        RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False)
    )
    await store.initialize()
    return store


def _publish_tool(
    records_store: Any,
    *,
    max_per_hour: int = 12,
    max_per_hour_ship: int = 40,
    mapping: dict[str, tuple[str, str]] | None = None,
) -> PublishFindingTool:
    return PublishFindingTool(
        records_store=records_store,
        callsign_resolver=_StaticResolver(
            mapping or {"agent-a": ("SCOUT", "science")}
        ),
        source_node="node-1",
        max_per_hour=max_per_hour,
        max_per_hour_ship=max_per_hour_ship,
    )


_PUBLISH_TOPICS: list[tuple[str, str, str]] = [
    (
        "Coolant loop harmonics",
        "The port coolant loop resonates at 4.2 kHz under sustained load.",
        "Nine sensor sweeps across three watches on deck twelve.",
    ),
    (
        "Warp plasma injector drift",
        "Injector three drifts 0.8 percent hot after forty minutes at warp six.",
        "Telemetry comparison against the port and starboard injectors.",
    ),
    (
        "Shuttlebay door seal wear",
        "The upper shuttlebay seal loses pressure integrity below 4 degrees.",
        "Three cold-cycle pressure tests during the outer survey.",
    ),
    (
        "Sensor palette calibration",
        "Lateral sensor palette four reports bearings two degrees to starboard.",
        "Cross-checked against stellar cartography fixes on eleven targets.",
    ),
    (
        "Replicator pattern buffer decay",
        "Pattern buffers degrade measurably after nine hundred consecutive uses.",
        "Sampled output mass variance across four decks over one month.",
    ),
    (
        "Deflector grid impedance",
        "Deflector grid impedance rises sharply when the dish exceeds 340 kelvin.",
        "Thermal load testing during the nebula transit.",
    ),
]


def _publish_params(n: int) -> dict[str, Any]:
    """Distinct subject matter per call.

    AD-550 near-duplicate suppression (0.8 similarity) is live on this path, so
    near-identical claims would be refused as duplicates and the test would be
    measuring dedup rather than the AD-1141 budget.
    """
    title, claim, basis = _PUBLISH_TOPICS[n % len(_PUBLISH_TOPICS)]
    suffix = "" if n < len(_PUBLISH_TOPICS) else f" Repeat observation {n}."
    return {
        "title": f"{title} {n}",
        "claim": f"{claim}{suffix}",
        "basis": basis,
    }


async def test_ship_budget_refuses_the_next_publish_across_two_authors(
    records,
) -> None:
    """Proven with **two** authors so the bound is provably the ship's, not an
    author's: each stays well under its own 12/hr limit."""
    tool = _publish_tool(
        records,
        max_per_hour=12,
        max_per_hour_ship=4,
        mapping={"agent-a": ("SCOUT", "science"), "agent-b": ("WRENCH", "engineering")},
    )
    agents = ["agent-a", "agent-b"]
    for n in range(4):
        res = await tool.invoke(
            _publish_params(n), {"agent_id": agents[n % 2]},
        )
        assert res.metadata["published"] is True, res.metadata

    refused = await tool.invoke(_publish_params(99), {"agent_id": "agent-a"})

    assert refused.metadata == {"published": False, "reason": "ship_rate_limited"}
    assert refused.error is None


async def test_ship_budget_is_checked_before_the_per_author_limiter(records) -> None:
    """An author at its own limit **and** the ship at its limit must report the
    ship bound — telling it that it hit its personal limit would be false and
    would send it into the retry loop the limiter exists to absorb."""
    tool = _publish_tool(records, max_per_hour=2, max_per_hour_ship=2)
    for n in range(2):
        res = await tool.invoke(_publish_params(n), {"agent_id": "agent-a"})
        assert res.metadata["published"] is True

    refused = await tool.invoke(_publish_params(9), {"agent_id": "agent-a"})

    assert refused.metadata["reason"] == "ship_rate_limited"
    assert refused.metadata["reason"] != "rate_limited"


async def test_per_author_limit_still_reports_rate_limited_under_the_ship_budget(
    records,
) -> None:
    tool = _publish_tool(records, max_per_hour=2, max_per_hour_ship=40)
    for n in range(2):
        assert (
            await tool.invoke(_publish_params(n), {"agent_id": "agent-a"})
        ).metadata["published"] is True

    refused = await tool.invoke(_publish_params(9), {"agent_id": "agent-a"})

    assert refused.metadata["reason"] == "rate_limited"


async def test_a_ship_refused_call_performs_no_write(records) -> None:
    tool = _publish_tool(records, max_per_hour=12, max_per_hour_ship=1)
    first = await tool.invoke(_publish_params(0), {"agent_id": "agent-a"})
    assert first.metadata["published"] is True

    refused_params = _publish_params(1)
    refused = await tool.invoke(refused_params, {"agent_id": "agent-a"})

    assert refused.metadata["published"] is False
    assert refused.metadata["reason"] == "ship_rate_limited"
    hits = await records.search(refused_params["title"], scope="ship")
    assert all(
        refused_params["claim"] not in (hit.get("snippet") or "")
        and refused_params["claim"] not in (hit.get("content") or "")
        for hit in hits
    )


async def test_a_per_author_refusal_does_not_consume_ship_budget(records) -> None:
    """The ship window is recorded only once both budgets admit the call."""
    tool = _publish_tool(
        records,
        max_per_hour=1,
        max_per_hour_ship=40,
        mapping={"agent-a": ("SCOUT", "science"), "agent-b": ("WRENCH", "engineering")},
    )
    assert (
        await tool.invoke(_publish_params(0), {"agent_id": "agent-a"})
    ).metadata["published"] is True
    # agent-a is now at its personal limit; this call must not consume a ship slot.
    refused = await tool.invoke(_publish_params(1), {"agent_id": "agent-a"})
    assert refused.metadata["reason"] == "rate_limited"

    assert len(tool._ship_publications) == 1


async def test_the_ship_deque_does_not_grow_without_bound_under_a_burst(
    records,
) -> None:
    tool = _publish_tool(records, max_per_hour=200, max_per_hour_ship=3)
    for n in range(25):
        await tool.invoke(_publish_params(n), {"agent_id": "agent-a"})

    assert len(tool._ship_publications) <= 3
    assert tool._ship_publications.maxlen == 3


async def test_ship_budget_default_is_forty() -> None:
    assert AgenticToolsConfig().publish_finding_max_per_hour_ship == 40


async def test_headline_round_trip_a_later_session_reaches_the_finding(
    tmp_path: Path,
) -> None:
    """A crew child in session A (science) publishes; a **new** ``OracleService``
    over the same on-disk paths — standing in for a later session — hands the
    claim to a **different** agent in a **different** department."""
    from probos.cognitive.oracle_service import make_reader_identity_resolver

    repo = tmp_path / "ship-records"
    write_store = RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))
    await write_store.initialize()

    tool = PublishFindingTool(
        records_store=write_store,
        callsign_resolver=_StaticResolver({"agent-a": ("SCOUT", "science")}),
        source_node="node-1",
        max_per_hour_ship=40,
    )
    published = await tool.invoke(
        {
            "title": "Deck twelve coolant harmonics",
            "claim": (
                "The port coolant loop resonates at 4.2 kHz under sustained "
                "load on deck twelve."
            ),
            "basis": "Nine sensor sweeps across three watches.",
        },
        {"agent_id": "agent-a", "department": "science"},
    )
    assert published.metadata["published"] is True

    # ---- later session: fresh objects, same on-disk paths ----
    read_store = RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))
    await read_store.initialize()
    oracle = OracleService(records_store=read_store)
    oracle.attach_reader_identity_resolver(
        make_reader_identity_resolver(
            registry=SimpleNamespace(
                get=lambda aid: SimpleNamespace(
                    agent_type="engineer", callsign="WRENCH", sovereign_id="",
                )
                if aid == "agent-b"
                else None,
                all=lambda: [],
            ),
            ontology=SimpleNamespace(get_agent_department=lambda _t: "engineering"),
        )
    )

    results = await oracle.query(
        query_text="deck twelve coolant harmonics",
        agent_id="agent-b",
        k_per_tier=5,
        tiers=list(SIGMA_TIERS),
    )

    assert results, "the later session received nothing from the commons"
    assert any(
        (r.metadata or {}).get("path") == published.metadata["path"] for r in results
    ), [r.metadata for r in results]
    # And the crew renderer turns it into framed, provenance-marked context.
    block = _render_commons_block(
        results, max_chars=2000, max_entries=4, min_score=0.0,
    )
    assert _COMMONS_HEADER in block
    assert _COMMONS_DISPOSITION in block


# ===========================================================================
# 5. expected_output
# ===========================================================================

async def test_expected_output_reaches_the_producer_under_its_header(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(
        store,
        parent_id=parent.id,
        metadata={"expected_output": "A ranked list of causes with citations."},
    )
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle([]),
        enabled=True,
    )

    await ex.run(parent.id)

    task_text = agentic.task_texts[0]
    assert _EXPECTED_OUTPUT_HEADER in task_text
    assert _EXPECTED_OUTPUT_DISPOSITION in task_text
    assert "A ranked list of causes with citations." in task_text
    assert task_text.startswith(child.description)


async def test_expected_output_absent_emits_no_header(store) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle([]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert _EXPECTED_OUTPUT_HEADER not in agentic.task_texts[0]
    assert agentic.task_texts[0] == child.description


async def test_expected_output_empty_string_emits_no_header() -> None:
    assert _render_expected_output_block("") == ""
    assert _render_expected_output_block("   ") == ""
    assert _render_expected_output_block(None) == ""
    assert _render_expected_output_block(123) == ""


async def test_expected_output_is_bounded_at_one_thousand_chars() -> None:
    block = _render_expected_output_block("z" * 5000)
    assert _MAX_EXPECTED_OUTPUT_CHARS == 1000
    body = block.split("\n\n")[-1]
    assert len(body) <= _MAX_EXPECTED_OUTPUT_CHARS + len("...[truncated]")
    assert body.endswith("...[truncated]")


async def test_expected_output_and_commons_both_appear_in_declared_order(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    child = await _child(
        store, parent_id=parent.id, metadata={"expected_output": "A ranked list."},
    )
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        runtime=_runtime(tools={"publish_finding"}),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    text = agentic.task_texts[0]
    assert (
        text.index(child.description)
        < text.index(_EXPECTED_OUTPUT_HEADER)
        < text.index(_COMMONS_HEADER)
        < text.index(_PUBLISH_NUDGE)
    )


# ===========================================================================
# 6. Framing — every authored string against the REAL regex
# ===========================================================================

async def test_every_module_level_authored_string_is_gap_regex_clean() -> None:
    for name, text in _AUTHORED_STRINGS.items():
        match = _CAPABILITY_GAP_RE.search(text)
        assert match is None, f"{name} trips the gap regex on {match!r}"


async def test_the_gap_regex_under_test_is_the_real_one() -> None:
    """A re-typed copy would not catch what actually bites.

    BF-707: these assertions used to be ``black hole`` and ``cut some slack``,
    which matched only because ``lack`` had no word boundary. Proving the import
    is real by leaning on a defect means the test PASSES a broken regex and
    FAILS the fix -- precisely inverted. Real phrasings prove the same thing,
    and the ordinary-word half is now pinned alongside it.
    """
    assert _CAPABILITY_GAP_RE.search("cannot do this") is not None
    assert _CAPABILITY_GAP_RE.search("no mechanism for that") is not None
    assert _CAPABILITY_GAP_RE.search("it lacks a renderer") is not None
    # The BF-707 half: ordinary prose must no longer register as a gap.
    assert _CAPABILITY_GAP_RE.search("we found a black hole") is None
    assert _CAPABILITY_GAP_RE.search("cut some slack") is None


async def test_composed_task_text_is_clean_across_every_path(store) -> None:
    """Success / empty / truncated / no-tool — all four composed outputs."""
    cases = {
        "success": (
            _runtime(tools={"publish_finding"}),
            _RecordingOracle([_result(content="Resonance peaks at 4.2 kHz.")]),
        ),
        "empty": (_runtime(tools={"publish_finding"}), _RecordingOracle([])),
        "truncated": (
            _runtime(tools={"publish_finding"}),
            _RecordingOracle([_result(content="q" * 3000, score=0.9)] * 9),
        ),
        "no_tool": (_runtime(tools=set()), _RecordingOracle([_result()])),
    }
    for label, (runtime, oracle) in cases.items():
        # A fresh parent/child per case: a completed child is terminal and
        # would be skipped on a second run, recording no call at all.
        parent = await store.create_work_item(
            title=f"parent-{label}", work_type="work_order",
        )
        await _child(
            store,
            parent_id=parent.id,
            spec_id=f"s-{label}",
            metadata={"expected_output": "A ranked list."},
        )
        agentic = _RecordingExecutor()
        ex = _executor(
            store,
            _FakeRegistry({"a1": _FakeAgent("a1")}),
            agentic,
            runtime=runtime,
            oracle=oracle,
            enabled=True,
        )
        await ex.run(parent.id)
        assert agentic.task_texts, f"{label} path recorded no run"
        text = agentic.task_texts[0]
        match = _CAPABILITY_GAP_RE.search(text)
        assert match is None, f"{label} path trips the gap regex on {match!r}"


async def test_the_empty_consult_note_exists_is_clean_and_is_never_emitted(
    store,
) -> None:
    """DD-3: kept defined so a later AD does not re-derive the wording, but a
    child that never asked must not be told the commons was silent."""
    assert _EMPTY_CONSULT_NOTE
    assert _CAPABILITY_GAP_RE.search(_EMPTY_CONSULT_NOTE) is None

    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    agentic = _RecordingExecutor()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1")}),
        agentic,
        oracle=_RecordingOracle([_result(score=0.01)]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert _EMPTY_CONSULT_NOTE not in agentic.task_texts[0]


# ===========================================================================
# 7. Ablation surface
# ===========================================================================

async def test_sigma_flag_dicts_carry_the_one_new_bool_path() -> None:
    from tests.ablation.sigma_flags import SIGMA_OFF, SIGMA_ON

    key = "agentic_tools.crew_sigma_context_enabled"
    assert key in SIGMA_OFF
    assert key in SIGMA_ON
    assert SIGMA_OFF[key] is False
    assert SIGMA_ON[key] is True


async def test_sigma_flag_dicts_stay_structurally_symmetric_and_boolean() -> None:
    from tests.ablation.sigma_flags import SIGMA_OFF, SIGMA_ON, resolve_flag

    assert set(SIGMA_ON) == set(SIGMA_OFF)
    config = SystemConfig()
    for path in SIGMA_ON:
        assert type(resolve_flag(config, path)) is bool, path


async def test_the_int_and_float_knobs_stay_out_of_the_flag_dicts() -> None:
    """``apply_flags`` requires every path to resolve to a ``bool``; the guard
    going red is the guard working, not something to loosen."""
    from tests.ablation.sigma_flags import SIGMA_ON

    for excluded in (
        "agentic_tools.crew_sigma_max_chars",
        "agentic_tools.crew_sigma_max_entries",
        "agentic_tools.crew_sigma_min_score",
        "agentic_tools.publish_finding_max_per_hour_ship",
    ):
        assert excluded not in SIGMA_ON


async def test_the_rig_registers_publish_finding_when_the_flag_is_on(
    tmp_path: Path,
) -> None:
    from tests.ablation import sigma_rig

    assert "_register_publish_finding_tool" in inspect.getsource(
        sigma_rig._wire_sigma
    )
    params = inspect.signature(sigma_rig._wire_sigma).parameters
    assert "registry" in params and "ontology" in params


async def test_reachability_refuses_a_crew_sigma_arm_without_an_oracle() -> None:
    from tests.ablation.sigma_rig import sigma_reachability_problems

    config = SystemConfig()
    config.agentic_tools.crew_sigma_context_enabled = True
    rig = SimpleNamespace(
        config=config,
        runtime=SimpleNamespace(
            oracle=None, tool_registry=_FakeToolRegistry(), records_store=object(),
        ),
    )

    assert "crew_sigma_oracle_unavailable" in sigma_reachability_problems(rig)


async def test_reachability_refuses_an_unregistered_publish_tool() -> None:
    from tests.ablation.sigma_rig import sigma_reachability_problems

    config = SystemConfig()
    config.agentic_tools.publish_finding_enabled = True
    rig = SimpleNamespace(
        config=config,
        runtime=SimpleNamespace(
            oracle=object(),
            tool_registry=_FakeToolRegistry(),
            records_store=object(),
        ),
    )

    assert "publish_finding_tool_not_registered" in sigma_reachability_problems(rig)


async def test_reachability_is_silent_when_the_treatment_arm_is_whole() -> None:
    from tests.ablation.sigma_rig import sigma_reachability_problems

    config = SystemConfig()
    config.agentic_tools.crew_sigma_context_enabled = True
    config.agentic_tools.publish_finding_enabled = True
    rig = SimpleNamespace(
        config=config,
        runtime=SimpleNamespace(
            oracle=object(),
            tool_registry=_FakeToolRegistry({"publish_finding"}),
            records_store=object(),
        ),
    )

    assert sigma_reachability_problems(rig) == ()


async def test_crew_sigma_defaults_are_off_and_bounded() -> None:
    cfg = AgenticToolsConfig()
    assert cfg.crew_sigma_context_enabled is False
    assert cfg.crew_sigma_max_chars == 2000
    assert cfg.crew_sigma_max_entries == 4
    assert cfg.crew_sigma_min_score == 0.35


# ===========================================================================
# 8. Sovereignty
# ===========================================================================

async def test_a_sigma_on_run_makes_zero_episodic_calls_from_the_consult(
    store,
) -> None:
    parent = await store.create_work_item(title="parent", work_type="work_order")
    await _child(store, parent_id=parent.id)
    await _child(store, parent_id=parent.id, spec_id="s2", assigned_to="a2")
    episodic = _RecordingEpisodic()
    ex = _executor(
        store,
        _FakeRegistry({"a1": _FakeAgent("a1"), "a2": _FakeAgent("a2")}),
        _RecordingExecutor(),
        runtime=_runtime(tools={"publish_finding"}, episodic=episodic),
        oracle=_RecordingOracle([_result()]),
        enabled=True,
    )

    await ex.run(parent.id)

    assert episodic.calls == []
