"""AD-1209 (#1160): an agent must be able to READ a task's state.

Without a way to look, the only route toward answering "is it done?" is to do
the work and see -- so a status question becomes a second execution of the job.
Measured 2026-07-31: 106 seconds and fifteen repeat HTTP fetches to answer a
question a database row already knew. Measured again 2026-08-08: one request
became four work items in 26 minutes.

The load-bearing test is `test_the_tool_is_actually_offered_to_the_loop`. A tool
that is registered but never offered is inert, and this repository's dominant
defect shape is exactly that -- AD-1157, BF-688, BF-690, BF-692, BF-695 were all
"built, tested, and unreachable in production".
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.tools.work_item_status_tool import WorkItemStatusTool

AGENT = "counselor_counselor_0_abc"
OTHER = "yeoman_yeoman_0_xyz"


class _Runtime:
    def __init__(self, store: Any) -> None:
        self.work_item_store = store


async def _store(tmp_path: Any):
    from probos.workforce import WorkItemStore

    store = WorkItemStore(db_path=str(tmp_path / "workforce.db"))
    await store.start()
    return store


def _tool(store: Any) -> WorkItemStatusTool:
    return WorkItemStatusTool(runtime=_Runtime(store))


# ── the happy path, against a real store ──────────────────────────────────
@pytest.mark.asyncio
async def test_reports_state_for_an_owned_task(tmp_path: Any) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="For each of the top 15 Python packages",
            work_type="task",
            assigned_to=AGENT,
        )
        res = await _tool(store).invoke(
            {"work_item_id": item.id}, {"agent_id": AGENT},
        )
    finally:
        await store.stop()

    out = res.output
    assert out["found"] is True
    assert out["work_item_id"] == item.id
    assert out["title"].startswith("For each of the top 15")
    assert out["status"]
    assert "is_final" in out and isinstance(out["is_final"], bool)
    assert out["summary"]
    assert res.error is None


@pytest.mark.asyncio
async def test_a_prefix_from_the_transcript_resolves(tmp_path: Any) -> None:
    """Acknowledgements print a shortened id, so that is what an agent quotes."""
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="t", work_type="task", assigned_to=AGENT,
        )
        res = await _tool(store).invoke(
            {"work_item_id": item.id[:12]}, {"agent_id": AGENT},
        )
    finally:
        await store.stop()

    assert res.output["found"] is True
    assert res.output["work_item_id"] == item.id


@pytest.mark.asyncio
async def test_a_terminal_task_says_no_further_work_will_happen(
    tmp_path: Any,
) -> None:
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="t", work_type="task", assigned_to=AGENT,
        )
        await store.transition_work_item(item.id, "cancelled", source="captain")
        res = await _tool(store).invoke(
            {"work_item_id": item.id}, {"agent_id": AGENT},
        )
    finally:
        await store.stop()

    assert res.output["is_final"] is True
    assert res.output["status"] == "cancelled"
    assert "no further work" in res.output["summary"]


# ── honest degradation ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_another_agents_task_is_not_readable(tmp_path: Any) -> None:
    """Reporting someone else's task would be a guess dressed as an answer,
    and would leak one crew member's work into another's context."""
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="secret", work_type="task", assigned_to=OTHER,
        )
        res = await _tool(store).invoke(
            {"work_item_id": item.id}, {"agent_id": AGENT},
        )
    finally:
        await store.stop()

    assert res.output["found"] is False
    assert "secret" not in str(res.output)
    assert res.error is None


@pytest.mark.asyncio
async def test_an_unknown_id_degrades_rather_than_erroring(tmp_path: Any) -> None:
    store = await _store(tmp_path)
    try:
        res = await _tool(store).invoke(
            {"work_item_id": "0" * 32}, {"agent_id": AGENT},
        )
    finally:
        await store.stop()

    assert res.output["found"] is False
    assert res.error is None


@pytest.mark.asyncio
async def test_a_too_short_id_is_refused_not_guessed() -> None:
    res = await WorkItemStatusTool(runtime=_Runtime(None)).invoke(
        {"work_item_id": "abc"}, {"agent_id": AGENT},
    )
    assert res.output["found"] is False
    assert "8 characters" in res.output["reason"]


@pytest.mark.asyncio
async def test_no_store_degrades_honestly() -> None:
    res = await WorkItemStatusTool(runtime=_Runtime(None)).invoke(
        {"work_item_id": "a" * 16}, {"agent_id": AGENT},
    )
    assert res.output["found"] is False
    assert res.error is None


@pytest.mark.asyncio
async def test_a_raising_store_never_breaks_the_turn() -> None:
    class _Boom:
        async def get_work_item(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db on fire")

        async def list_work_items(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("db on fire")

    res = await WorkItemStatusTool(runtime=_Runtime(_Boom())).invoke(
        {"work_item_id": "a" * 16}, {"agent_id": AGENT},
    )
    assert res.output["found"] is False
    assert res.error is None


@pytest.mark.asyncio
async def test_an_anonymous_caller_is_not_a_wildcard(tmp_path: Any) -> None:
    """An empty agent_id must not read everything."""
    store = await _store(tmp_path)
    try:
        item = await store.create_work_item(
            title="t", work_type="task", assigned_to=AGENT,
        )
        res = await _tool(store).invoke({"work_item_id": item.id}, {"agent_id": ""})
    finally:
        await store.stop()

    assert res.output["found"] is False


# ── it must stay read-only ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_tool_never_mutates_the_board(tmp_path: Any) -> None:
    """AD-1204 owns resumption. This must not grow into it."""
    store = await _store(tmp_path)
    calls: list[str] = []
    for name in ("transition_work_item", "update_work_item", "create_work_item"):
        original = getattr(store, name)

        def _spy(*a: Any, _n: str = name, _o: Any = original, **k: Any) -> Any:
            calls.append(_n)
            return _o(*a, **k)

        setattr(store, name, _spy)

    try:
        item = await store.create_work_item(
            title="t", work_type="task", assigned_to=AGENT,
        )
        calls.clear()
        await _tool(store).invoke({"work_item_id": item.id}, {"agent_id": AGENT})
    finally:
        await store.stop()

    assert calls == [], f"the lookup mutated the board: {calls}"


def test_the_schema_declares_only_a_lookup() -> None:
    tool = WorkItemStatusTool(runtime=_Runtime(None))
    assert tool.tool_id == "work_item_status"
    assert list(tool.input_schema["properties"]) == ["work_item_id"]
    assert tool.input_schema["required"] == ["work_item_id"]


def test_the_description_steers_away_from_redoing_the_work() -> None:
    """BF-719's lesson: a constraint has to name the alternative or it does not
    change the choice. The whole defect is an agent re-running a job to find
    out how the job is going, so the description must say so."""
    text = WorkItemStatusTool(runtime=_Runtime(None)).description.lower()
    assert "read-only" in text
    assert "second copy" in text or "again" in text


def test_the_description_does_not_trip_the_capability_gap_regex() -> None:
    """Agent-facing text matching _CAPABILITY_GAP_RE triggers self-modification."""
    from probos.cognitive.decomposer import is_capability_gap

    assert not is_capability_gap(
        WorkItemStatusTool(runtime=_Runtime(None)).description
    )


# ── the crossing test ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_tool_is_actually_offered_to_the_loop(tmp_path: Any) -> None:
    """Registered is not offered. A tool the loop never sees cannot answer
    anything, which is precisely how AD-1157 / BF-688 / BF-690 / BF-692 /
    BF-695 all shipped inert.

    Drives the real ``WorkItemAgenticExecutor`` tool assembly with a real store
    and asserts ``work_item_status`` reaches the tool list handed to the loop.
    """
    import probos.cognitive.swe_harness.agentic_loop as loop_mod
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.tools.registry import ToolRegistry

    store = await _store(tmp_path)
    seen: dict = {}

    class _CaptureLoop:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, **kwargs: Any) -> Any:
            seen["tools"] = kwargs.get("tools") or []
            return loop_mod.AgenticResult(final_text="ok")

    class _Rt:
        def __init__(self) -> None:
            self.work_item_store = store
            self.tool_registry = ToolRegistry()

    class _LLM:
        async def complete(self, request: Any, **_k: Any) -> Any:
            from probos.cognitive.llm_client import LLMResponse

            return LLMResponse(content="ok", model="m", tier="standard")

    original = loop_mod.AgenticLoop
    loop_mod.AgenticLoop = _CaptureLoop  # type: ignore[misc]
    try:
        await WorkItemAgenticExecutor(llm_client=_LLM()).run(
            agent_id=AGENT, instructions="i", task_text="t", runtime=_Rt(),
        )
    finally:
        loop_mod.AgenticLoop = original  # type: ignore[misc]
        await store.stop()

    offered = {
        (t.get("function") or {}).get("name") or t.get("name")
        for t in seen.get("tools", [])
    }
    assert "work_item_status" in offered, (
        f"the status tool was not offered to the loop; offered={sorted(offered)}"
    )
