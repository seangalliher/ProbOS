"""AD-572e: Task awareness in Captain DM context."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from probos.cognitive.captain_engagement import CaptainEngagementProvider


def _make_item(*, id: str = "wi-1", title: str = "t", work_type: str = "task"):
    return SimpleNamespace(id=id, title=title, work_type=work_type)


# ----- Section 1: task_awareness() helper -----


def test_task_awareness_returns_empty_when_runtime_none():
    provider = CaptainEngagementProvider(runtime=None)
    result = asyncio.run(provider.task_awareness("agent-1"))
    assert result == {}


def test_task_awareness_returns_empty_when_agent_id_empty():
    rt = SimpleNamespace(work_item_store=SimpleNamespace())
    provider = CaptainEngagementProvider(runtime=rt)
    assert asyncio.run(provider.task_awareness("")) == {}


def test_task_awareness_returns_empty_when_work_item_store_missing():
    rt = SimpleNamespace(work_item_store=None)
    provider = CaptainEngagementProvider(runtime=rt)
    assert asyncio.run(provider.task_awareness("agent-1")) == {}


def test_task_awareness_returns_empty_on_query_exception():
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(side_effect=RuntimeError("boom"))
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)
    assert asyncio.run(provider.task_awareness("agent-1")) == {}


def test_task_awareness_returns_open_count_and_tasks():
    items = [
        _make_item(id="wi-1", title="Fix bug", work_type="task"),
        _make_item(id="wi-2", title="Write doc", work_type="card"),
    ]
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=items)
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.task_awareness("agent-1"))
    assert result == {
        "open_count": 2,
        "tasks": [
            {"id": "wi-1", "title": "Fix bug", "type": "task"},
            {"id": "wi-2", "title": "Write doc", "type": "card"},
        ],
    }


def test_task_awareness_caps_tasks_at_10():
    items = [_make_item(id=f"wi-{i}") for i in range(15)]
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=items)
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.task_awareness("agent-1"))
    # open_count reflects what the store returned (already limit=10 enforced
    # by store; helper additionally caps the slice for defensive consistency).
    assert len(result["tasks"]) == 10
    assert result["tasks"][0]["id"] == "wi-0"
    assert result["tasks"][9]["id"] == "wi-9"


def test_task_awareness_extracts_id_title_type_fields():
    items = [_make_item(id="wi-x", title="hello", work_type="duty")]
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=items)
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.task_awareness("agent-1"))
    assert result["tasks"] == [{"id": "wi-x", "title": "hello", "type": "duty"}]


def test_task_awareness_handles_missing_fields_gracefully():
    # Object missing all expected fields → defaults to empty strings
    bare = object()
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=[bare])
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    result = asyncio.run(provider.task_awareness("agent-1"))
    assert result == {
        "open_count": 1,
        "tasks": [{"id": "", "title": "", "type": ""}],
    }


def test_task_awareness_calls_list_work_items_with_assigned_to():
    """Verify the join key is agent_id (NOT agent_type)."""
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=[])
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    asyncio.run(provider.task_awareness("agent-uuid-123"))
    store.list_work_items.assert_awaited_once()
    kwargs = store.list_work_items.await_args.kwargs
    assert kwargs["assigned_to"] == "agent-uuid-123"


def test_task_awareness_calls_list_work_items_with_status_open():
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=[])
    rt = SimpleNamespace(work_item_store=store)
    provider = CaptainEngagementProvider(runtime=rt)

    asyncio.run(provider.task_awareness("agent-1"))
    kwargs = store.list_work_items.await_args.kwargs
    assert kwargs["status"] == "open"
    assert kwargs["limit"] == 10


# ----- Section 2: proactive context integration -----


def test_proactive_loop_injects_task_awareness_into_captain_engagement_context():
    """Direct unit test of the injection shape -- the proactive pattern is
    `context["captain_engagement"]["task_awareness"] = await provider.task_awareness(agent.id)`."""
    items = [_make_item(id="wi-1", title="t1", work_type="task")]
    store = SimpleNamespace()
    store.list_work_items = AsyncMock(return_value=items)
    rt = SimpleNamespace(work_item_store=store, bridge_alerts=None, ward_room=None)
    provider = CaptainEngagementProvider(runtime=rt)

    # Mirror proactive.py:1181-1199 control flow
    context: dict = {}
    context["captain_engagement"] = provider.snapshot()
    if isinstance(context.get("captain_engagement"), dict):
        context["captain_engagement"]["task_awareness"] = asyncio.run(
            provider.task_awareness("agent-1")
        )

    assert context["captain_engagement"]["task_awareness"] == {
        "open_count": 1,
        "tasks": [{"id": "wi-1", "title": "t1", "type": "task"}],
    }


def test_proactive_loop_handles_provider_missing_gracefully():
    """When task_awareness helper not present (rolling-deploy / downgrade),
    proactive loop's hasattr guard skips injection."""
    # Provider stub without task_awareness method
    provider = SimpleNamespace(snapshot=lambda: {"alerts_pending": 0})

    context: dict = {"captain_engagement": provider.snapshot()}
    if hasattr(provider, "task_awareness"):
        context["captain_engagement"]["task_awareness"] = "would-inject"

    # No task_awareness key was added because the helper was absent
    assert "task_awareness" not in context["captain_engagement"]
