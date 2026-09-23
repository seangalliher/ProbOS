"""Distribution + runtime integration tests for Phase 22 (AD-253).

Tests cover:
- Runtime integration: utility agent pools, descriptors, config gating
- Distribution: `probos init`, FastAPI endpoints, WebSocket
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from probos import work_item_steps as owned_steps
from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime

from tests.test_ad1131_crew_session_delivery_metrics import (
    _Harness as _NotificationHarness,
    _make_outcome,
    harness as notification_delivery_harness,
)
from tests.test_ad1192_owned_steps_execution import (
    _owned_http_apply,
    _owned_http_proposal,
    _owned_http_view,
    owned_closeout_case,
)
from tests.test_ad1207_fault_visibility import fault_visibility_api


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

async def test_fault_list_canonical_happy_path(fault_visibility_api: Any) -> None:
    rig = fault_visibility_api
    fault = await rig.store.file_fault(tool_id="browser", error_text="Page opening failed")
    response = await rig.client.get("/api/faults")
    assert response.status_code == 200
    assert response.json()["faults"][0]["id"] == fault.id
    assert response.json()["total"] == 1
    assert response.headers["cache-control"] == "no-store"


async def test_fault_list_canonical_empty_and_unavailable_are_distinct(fault_visibility_api: Any) -> None:
    rig = fault_visibility_api
    assert (await rig.client.get("/api/faults")).json() == {
        "faults": [], "total": 0, "limit": 50, "offset": 0,
    }
    rig.runtime.fault_report_store = None
    response = await rig.client.get("/api/faults")
    assert response.status_code == 503 and response.json() == {"detail": "fault_store_unavailable"}


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=bad", "offset=-1", "offset=1.5"])
async def test_fault_list_canonical_query_validation(fault_visibility_api: Any, query: str) -> None:
    assert (await fault_visibility_api.client.get(f"/api/faults?{query}")).status_code == 422


async def test_fault_detail_canonical_happy_path(fault_visibility_api: Any) -> None:
    rig = fault_visibility_api
    fault = await rig.store.file_fault(
        tool_id="browser", error_text="Page opening failed", agent_id="reporter",
    )
    response = await rig.client.get(f"/api/faults/{fault.id}")
    assert response.status_code == 200
    assert response.json()["fault"]["recorded_agent_id"] == "reporter"
    assert response.json()["fault"]["occurrences"] == "1"
    assert response.headers["cache-control"] == "no-store"


async def test_fault_detail_canonical_unknown_and_unavailable(fault_visibility_api: Any) -> None:
    rig = fault_visibility_api
    response = await rig.client.get("/api/faults/abcdefabcdef")
    assert response.status_code == 404 and response.json() == {"detail": "fault_not_found"}
    rig.runtime.fault_report_store = None
    assert (await rig.client.get("/api/faults/abcdefabcdef")).status_code == 503


@pytest.mark.parametrize("fault_id", ["BAD", "ABCDEFABCDEF", "a" * 11, "a" * 13, "g" * 12])
async def test_fault_detail_canonical_id_validation(fault_visibility_api: Any, fault_id: str) -> None:
    assert (await fault_visibility_api.client.get(f"/api/faults/{fault_id}")).status_code == 422


@pytest.fixture
async def actionable_capability_api(tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI

    from probos.capability_request import CapabilityRequestStore
    from probos.routers.capability_requests import router
    from probos.routers.deps import get_runtime

    store = CapabilityRequestStore(db_path=str(tmp_path / "actionable.db"))
    await store.start()
    app = FastAPI()
    app.include_router(router)
    runtime = SimpleNamespace(capability_request_store=store)
    app.dependency_overrides[get_runtime] = lambda: runtime
    try:
        yield app, runtime, store
    finally:
        await store.stop()


async def test_actionable_api_happy_path(actionable_capability_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = actionable_capability_api
    req = await store.file_request("agent", "install", "numpy")
    await store.decide(req.id, True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 200
    assert response.json()["view"] == "actionable"
    assert [row["id"] for row in response.json()["requests"]] == [req.id]
    assert response.json()["requests"][0]["can_retry_fulfilment"] is True


async def test_actionable_api_empty_is_authoritative(actionable_capability_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, _store = actionable_capability_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 200
    assert response.json() == {"view": "actionable", "requests": []}


async def test_actionable_api_without_store_returns_503(actionable_capability_api):
    from httpx import ASGITransport, AsyncClient

    app, runtime, _store = actionable_capability_api
    runtime.capability_request_store = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 503
    assert response.json() == {"detail": "capability request store not available"}


async def test_actionable_api_store_error_is_not_empty(actionable_capability_api, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = actionable_capability_api

    async def failed_read():
        raise RuntimeError("controlled actionable read failure")

    monkeypatch.setattr(store, "list_actionable", failed_read)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/capability-requests/actionable")
    assert response.status_code == 500


async def test_actionable_api_input_cannot_mutate_or_widen_view(actionable_capability_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = actionable_capability_api
    req = await store.file_request("agent", "action", "browser.navigate")
    await store.decide(req.id, True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        mutation = await client.post(
            "/api/capability-requests/actionable", json={"approve": True},
        )
        observation = await client.get(
            "/api/capability-requests/actionable?status=approved&view=pending",
        )
    assert mutation.status_code == 405
    assert observation.status_code == 200
    assert observation.json() == {"view": "actionable", "requests": []}
    assert (await store.get(req.id)).status == "approved"


@pytest.fixture
async def runtime(tmp_path):
    """Runtime with MockLLMClient and utility agents enabled."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.fixture
async def runtime_no_utility(tmp_path):
    """Runtime with utility agents disabled."""
    config = SystemConfig()
    config.utility_agents.enabled = False
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.fixture
async def owned_steps_create_app(runtime):
    from httpx import ASGITransport, AsyncClient

    store = runtime.work_item_store
    assert runtime.crew_session_service is not None
    assert runtime.crew_orchestrator is not None
    parent = await store.create_work_item(
        id="owned-http-parent",
        title="Owned HTTP parent",
        steps=[
            {
                "label": "Manual HTTP row",
                "status": "pending",
                "assigned_to": None,
                "submitted_by": None,
                "confirmed_by": None,
                "note": None,
            }
        ],
    )
    child = await store.create_work_item(
        id="owned-http-child",
        title="Owned HTTP child",
        parent_id=parent.id,
        assigned_to="agent-a",
        metadata={"spec_id": "owned-http-spec"},
    )
    await store.get_owned_steps_execution_port().admit(
        parent.id,
        children=(child,),
        thread_id="",
    )
    app = create_app(runtime)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield runtime, client, parent.id, child.id


async def test_owned_steps_create_app_happy_read_preview_adopt_and_commands(
    owned_steps_create_app,
) -> None:
    runtime, client, parent_id, child_id = owned_steps_create_app
    legacy = await client.get(f"/api/work-items/{parent_id}/steps")
    assert legacy.content == (
        b'{"steps":[{"label":"Manual HTTP row","status":"pending",'
        b'"assigned_to":null,"submitted_by":null,"confirmed_by":null,'
        b'"note":null}],"gate_completion":false}'
    )
    observed = await client.get(f"/api/work-items/{child_id}/owned-steps")
    assert observed.status_code == 200
    view = observed.json()
    assert view["parent_id"] == parent_id
    assert view["requested_item_id"] == child_id
    assert view["mode"] == "awaiting_adoption"
    reference = view["reference"]
    previewed = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/preview",
        json={
            "version": 1,
            "kind": "adopt_existing",
            "preparation_id": "http-adopt-preparation",
            "reference": reference,
        },
    )
    assert previewed.status_code == 200, previewed.text
    proposal = previewed.json()["proposal"]
    assert proposal["kind"] == "adopt_existing"
    assert proposal["state"] == "ready"
    adopted = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/adopt",
        json={
            "version": 1,
            "operation_id": "http-adopt",
            "reference": proposal["reference"],
        },
    )
    assert adopted.status_code == 200, adopted.text
    replayed = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/adopt",
        json={
            "version": 1,
            "operation_id": "http-adopt",
            "reference": proposal["reference"],
        },
    )
    assert replayed.status_code == 200
    assert replayed.json() == {"disposition": "duplicate"}
    active = (
        await client.get(f"/api/work-items/{parent_id}/owned-steps")
    ).json()
    assert "replan_unstarted" in active["recovery"]
    assert "replace_manual_prefix" in active["recovery"]
    commanded = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/commands",
        json={
            "version": 1,
            "reference": active["reference"],
            "commands": [
                {
                    "operation_id": "http-submit",
                    "step_id": active["rows"][0]["step_id"],
                    "kind": "manual_submit",
                }
            ],
        },
    )
    assert commanded.status_code == 200
    assert commanded.json() == {
        "results": [
            {"operation_id": "http-submit", "disposition": "applied"}
        ]
    }
    assert (
        await runtime.work_item_store.get_work_item(parent_id)
    ).steps[0]["status"] == "submitted"


@pytest.mark.parametrize("active", [False, True], ids=["adopt", "replan"])
async def test_owned_steps_current_edited_prefix_survives_proposal_application(
    owned_closeout_case: Any, active: bool,
) -> None:
    case = owned_closeout_case
    state = case.state
    setup = await state.create_legacy()
    parent_id = setup["parent_id"]
    if active:
        await _owned_http_apply(
            case, parent_id,
            await _owned_http_proposal(case, parent_id, "adopt_existing", "prefix-adopt"),
            "prefix-adopt",
        )
    before = await state.store.get_owned_steps(parent_id)
    view = await _owned_http_view(case, parent_id)
    response = await case.client.post(
        f"/api/work-items/{parent_id}/owned-steps/commands",
        json={
            "version": 1, "reference": view["reference"],
            "commands": [{
                "operation_id": "edit-current-prefix", "step_id": view["rows"][0]["step_id"],
                "kind": "edit_note", "note": "Current authorized manual bytes",
            }],
        },
    )
    assert response.status_code == 200, response.text
    edited = await state.store.get_owned_steps(parent_id)
    assert edited.control.original_steps_json == before.control.original_steps_json
    kind = "replan_unstarted" if active else "adopt_existing"
    proposal = await _owned_http_proposal(case, parent_id, kind, "edited-prefix-preview")
    await _owned_http_apply(case, parent_id, proposal, "edited-prefix-apply")
    after = await state.store.get_owned_steps(parent_id)
    assert after.control.original_steps_json == before.control.original_steps_json
    assert after.control.rows[0] == edited.control.rows[0]
    assert (await state.store.get_work_item(parent_id)).steps[0]["note"] == "Current authorized manual bytes"


async def test_owned_steps_child_owner_urls_cover_adoption_replan_and_repair(owned_closeout_case: Any) -> None:
    case = owned_closeout_case
    setup = await case.state.create_legacy()
    child_id = setup["child_id"]
    parent_id = setup["parent_id"]
    for index, (kind, fields) in enumerate((
        ("adopt_existing", {}),
        ("replan_unstarted", {}),
        ("replace_manual_prefix", {"prefix_json": '[ { "label" : "Repaired current prefix", "status" : "pending" } ]'}),
    )):
        view = await _owned_http_view(case, child_id)
        assert view["parent_id"] == parent_id
        assert view["requested_item_id"] == child_id
        proposal = await _owned_http_proposal(case, child_id, kind, f"child-preview-{index}", **fields)
        await _owned_http_apply(case, child_id, proposal, f"child-apply-{index}")
    repaired = await case.client.get(f"/api/work-items/{child_id}/owned-steps/repair")
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["parent_id"] == repaired.json()["reference"]["parent_id"] == parent_id
    assert (await case.state.store.get_work_item(parent_id)).steps[0]["label"] == "Repaired current prefix"
    other = await case.state.create_legacy()
    foreign = await _owned_http_proposal(case, other["child_id"], "adopt_existing", "foreign-preview")
    refused = await case.client.post(
        f"/api/work-items/{child_id}/owned-steps/adopt",
        json={"version": 1, "operation_id": "foreign-apply", "reference": foreign["reference"]},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"]["parent_id"] == parent_id
    assert (await case.state.store.get_owned_steps(other["parent_id"])).control.mode == "awaiting_adoption"

    ordinary = await case.state.store.create_work_item(id="ordinary-parent", title="Ordinary parent")
    ordinary_child = await case.state.store.create_work_item(
        id="ordinary-child", title="Ordinary child", parent_id=ordinary.id,
        steps=[{"label": "Child's own steps", "status": "pending"}],
    )
    unmanaged = await _owned_http_view(case, ordinary_child.id)
    assert unmanaged["mode"] == "unmanaged"
    assert unmanaged["parent_id"] == unmanaged["requested_item_id"] == ordinary_child.id
    assert unmanaged["rows"][0]["todo"]["label"] == "Child's own steps"
    refused = await case.client.get(f"/api/work-items/{ordinary_child.id}/owned-steps/repair")
    assert refused.status_code == 404
    assert refused.json()["detail"]["parent_id"] == ordinary_child.id


@pytest.mark.parametrize("kind,fields", [
    ("reassign_unstarted", {"assignee_id": None}),
    ("pause_accounting", {"booking_id": None, "resource_id": "worker-a"}),
    ("pause_accounting", {"booking_id": "booking", "resource_id": None}),
    ("pause_accounting", {"booking_id": None, "resource_id": None}),
    ("resume_accounting", {"booking_id": None, "resource_id": "worker-a"}),
    ("resume_accounting", {"booking_id": "booking", "resource_id": None}),
    ("resume_accounting", {"booking_id": None, "resource_id": None}),
])
async def test_owned_steps_null_required_binding_rejected_before_effects(
    owned_closeout_case: Any, kind: str, fields: dict[str, str | None],
) -> None:
    import sqlite3

    case = owned_closeout_case
    setup = await case.state.create_replan()
    parent_id = setup["parent_id"]
    view = await _owned_http_view(case, parent_id)
    with sqlite3.connect(case.state.storage_root / "workforce.db") as db:
        before = list(db.iterdump())
    events = list(case.state.events)
    response = await case.client.post(
        f"/api/work-items/{parent_id}/owned-steps/commands",
        json={
            "version": 1, "reference": view["reference"],
            "commands": [{"operation_id": "null-binding", "step_id": view["rows"][0]["step_id"], "kind": kind, **fields}],
        },
    )
    assert response.status_code == 422, response.text
    with sqlite3.connect(case.state.storage_root / "workforce.db") as db:
        assert list(db.iterdump()) == before
    assert case.state.events == events


async def test_owned_steps_nullable_note_still_clears_manual_note(owned_closeout_case: Any) -> None:
    case = owned_closeout_case
    setup = await case.state.create_legacy()
    parent_id = setup["parent_id"]
    for index, note in enumerate(("Before clear", None)):
        view = await _owned_http_view(case, parent_id)
        response = await case.client.post(
            f"/api/work-items/{parent_id}/owned-steps/commands",
            json={
                "version": 1, "reference": view["reference"],
                "commands": [{"operation_id": f"note-{index}", "step_id": view["rows"][0]["step_id"], "kind": "edit_note", "note": note}],
            },
        )
        assert response.status_code == 200, response.text
    assert (await case.state.store.get_work_item(parent_id)).steps[0]["note"] is None


async def test_owned_steps_repair_replaces_malformed_then_requires_explicit_adopt(
    runtime,
) -> None:
    from httpx import ASGITransport, AsyncClient

    store = runtime.work_item_store
    parent = await store.create_work_item(
        id="owned-repair-parent",
        title="Owned repair parent",
        steps=[{"label": "Historical", "status": "completed"}],
    )
    child = await store.create_work_item(
        id="owned-repair-child",
        title="Owned repair child",
        parent_id=parent.id,
        assigned_to="agent-a",
        metadata={"spec_id": "owned-repair-spec"},
    )
    with pytest.raises(owned_steps.OwnedStepsError, match="repair_required"):
        await store.get_owned_steps_execution_port().admit(
            parent.id,
            children=(child,),
            thread_id="",
        )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(runtime)),
        base_url="http://test",
    ) as client:
        malformed = await client.get(
            f"/api/work-items/{parent.id}/owned-steps"
        )
        assert malformed.status_code == 409
        assert malformed.json()["detail"]["code"] == "owned_steps_repair_required"
        repair = await client.get(
            f"/api/work-items/{parent.id}/owned-steps/repair"
        )
        assert repair.status_code == 200, repair.text
        evidence = repair.json()
        assert evidence["raw_steps"] == (
            '[{"label": "Historical", "status": "completed"}]'
        )
        preview = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/preview",
            json={
                "version": 1,
                "kind": "replace_manual_prefix",
                "preparation_id": "repair-prefix-preparation",
                "reference": evidence["reference"],
                "prefix_json": '[{"label":"Replacement","status":"pending"}]',
            },
        )
        assert preview.status_code == 200, preview.text
        proposal = preview.json()["proposal"]
        # The former assertion routed replacement through /adopt. The ratified
        # proposal protocol reserves /adopt for adopt_existing only.
        refused_route = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/adopt",
            json={
                "version": 1,
                "operation_id": "repair-prefix-apply",
                "reference": proposal["reference"],
            },
        )
        assert refused_route.status_code == 409, refused_route.text
        assert refused_route.json()["detail"]["code"] == "owned_steps_proposal_route_conflict"
        replaced = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/commands",
            json={
                "version": 1,
                "operation_id": "repair-prefix-apply",
                "reference": proposal["reference"],
            },
        )
        assert replaced.status_code == 200, replaced.text
        awaiting = (
            await client.get(f"/api/work-items/{parent.id}/owned-steps")
        ).json()
        assert awaiting["mode"] == "awaiting_adoption"
        assert len(awaiting["rows"]) == 1
        adoption = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/preview",
            json={
                "version": 1,
                "kind": "adopt_existing",
                "preparation_id": "repair-adopt-preparation",
                "reference": awaiting["reference"],
            },
        )
        adopted = await client.post(
            f"/api/work-items/{parent.id}/owned-steps/adopt",
            json={
                "version": 1,
                "operation_id": "repair-adopt-apply",
                "reference": adoption.json()["proposal"]["reference"],
            },
        )
        assert adopted.status_code == 200, adopted.text
        active = (
            await client.get(f"/api/work-items/{parent.id}/owned-steps")
        ).json()
        assert active["mode"] == "active"
        assert [row["todo"]["status"] for row in active["rows"]] == [
            "pending",
            "pending",
        ]


async def test_owned_steps_repair_auth_error_and_validation(
    owned_steps_create_app,
) -> None:
    runtime, client, parent_id, _ = owned_steps_create_app
    missing = await client.get(
        "/api/work-items/missing-owned-parent/owned-steps/repair"
    )
    assert missing.status_code == 404
    runtime.config.auth.crew_scope_token = "owned-repair-secret"
    denied = await client.get(
        f"/api/work-items/{parent_id}/owned-steps/repair"
    )
    assert denied.status_code == 401
    invalid = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/preview",
        json={
            "version": 1,
            "kind": "replace_manual_prefix",
            "preparation_id": "bad-prefix",
            "reference": {
                "version": 1,
                "parent_id": parent_id,
                "actor_id": "captain",
                "thread_id": "",
                "turn_id": "http-owner",
                "view_id": "spoof",
                "content_hash": "0" * 64,
                "observation_id": "spoof",
            },
            "prefix_json": '[{"label":"bad","status":"completed"}]',
        },
        headers={"Authorization": "Bearer owned-repair-secret"},
    )
    assert invalid.status_code == 422


async def test_owned_steps_unmanaged_read_does_not_require_owner_service(
    runtime,
) -> None:
    from httpx import ASGITransport, AsyncClient

    item = await runtime.work_item_store.create_work_item(
        id="owned-unmanaged-default",
        title="Unmanaged default",
        steps=[{"label": "Manual", "status": "pending"}],
    )
    owner = runtime.crew_orchestrator
    service = runtime.crew_session_service
    runtime.crew_orchestrator = None
    runtime.crew_session_service = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=create_app(runtime)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                f"/api/work-items/{item.id}/owned-steps"
            )
    finally:
        runtime.crew_orchestrator = owner
        runtime.crew_session_service = service
    assert response.status_code == 200
    assert response.json()["mode"] == "unmanaged"


@pytest.mark.parametrize(
    "suffix",
    ["preview", "adopt", "commands", "finalize"],
)
async def test_owned_steps_create_app_auth_precedes_malformed_body(
    owned_steps_create_app,
    suffix: str,
) -> None:
    runtime, client, parent_id, _ = owned_steps_create_app
    runtime.config.auth.crew_scope_token = "owned-http-secret"
    response = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/{suffix}",
        content=b"{malformed",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401
    assert b"owned-http-secret" not in response.content


@pytest.mark.parametrize(
    "suffix",
    ["preview", "adopt", "commands", "finalize"],
)
async def test_owned_steps_create_app_strict_input_rejects_spoof_fields(
    owned_steps_create_app,
    suffix: str,
) -> None:
    runtime, client, parent_id, _ = owned_steps_create_app
    runtime.config.auth.crew_scope_token = "owned-http-secret"
    response = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/{suffix}",
        json={"actor": "captain", "accepted": True, "control": {}},
        headers={
            "Authorization": f"Bearer {runtime.config.auth.crew_scope_token}"
        },
    )
    assert response.status_code == 422


async def test_owned_steps_create_app_finalize_has_typed_recovery_error(
    owned_steps_create_app,
) -> None:
    _runtime, client, parent_id, _ = owned_steps_create_app
    observed = (
        await client.get(f"/api/work-items/{parent_id}/owned-steps")
    ).json()
    response = await client.post(
        f"/api/work-items/{parent_id}/owned-steps/finalize",
        json={"version": 1, "reference": observed["reference"]},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "owned_steps_finalization_unavailable"
    assert detail["actions"] == ["inspect_source"]
    assert "token" not in json.dumps(detail)


@pytest.fixture
def notification_context_api():
    from types import SimpleNamespace

    from fastapi import FastAPI

    from probos.routers import system
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(system.router)
    runtime = SimpleNamespace(config=SystemConfig())
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app, runtime


@pytest.mark.parametrize("notification_id", ["short", "A" * 64, "a" * 65])
async def test_notification_context_input_validation(notification_context_api, notification_id):
    from httpx import ASGITransport, AsyncClient

    app, _runtime = notification_context_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/notifications/{notification_id}/context")
    assert response.status_code == 422
    assert response.json() == {"detail": "notification_context_id_invalid"}
    assert response.headers["cache-control"] == "no-store"


async def test_notification_context_unavailable_default_auth_off(notification_context_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime = notification_context_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/notifications/{'a' * 64}/context")
    assert response.status_code == 503
    assert response.json() == {"detail": "notification_context_unavailable"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Bearer correct"])
async def test_notification_context_auth_before_lookup(notification_context_api, authorization):
    from httpx import ASGITransport, AsyncClient

    app, runtime = notification_context_api
    runtime.config.auth.crew_scope_token = "correct"
    headers = {} if authorization is None else {"Authorization": authorization}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/notifications/{'a' * 64}/context", headers=headers)
    assert response.status_code == (503 if authorization == "Bearer correct" else 401)
    assert set(response.json()) == {"detail"}
    assert response.headers["cache-control"] == "no-store"


@pytest.fixture
async def persisted_notification_context(
    notification_context_api: Any,
    notification_delivery_harness: _NotificationHarness,
) -> Any:
    app, runtime = notification_context_api
    harness = notification_delivery_harness
    case = await _make_outcome(harness, "failed")
    assert await harness.delivery.on_status_changed(case.event) == 1
    assert len(harness.queue.snapshot()) == 1
    runtime.work_item_store = harness.work
    runtime.crew_session_service = harness.service
    runtime.chat_thread_store = harness.threads
    runtime.notification_queue = harness.queue
    return app, runtime, harness, case


@pytest.mark.parametrize(
    ("configured", "authorization", "expected_status"),
    [(False, None, 200), (True, None, 401), (True, "Bearer wrong", 401),
     (True, "Bearer correct", 200)],
)
async def test_notification_context_valid_persisted_context_and_auth(
    persisted_notification_context: Any,
    configured: bool,
    authorization: str | None,
    expected_status: int,
) -> None:
    import copy

    from httpx import ASGITransport, AsyncClient

    from probos.crew_session_live import load_crew_session_projection

    app, runtime, harness, case = persisted_notification_context
    assert not runtime.config.agentic_dispatch.orchestrator_enabled
    if configured:
        runtime.config.auth.crew_scope_token = "correct"
    notification = harness.queue.snapshot()[0]
    parent = await harness.work.get_work_item(case.contract.task_id)
    loaded = await load_crew_session_projection(
        case.contract.task_id, crew_session_service=harness.service,
        work_item_store=harness.work,
    )
    assert loaded is not None
    entry = await harness.work.get_crew_session_delivery(notification["id"])
    messages = harness.threads.list_messages(case.thread.id)
    events = copy.deepcopy(harness.notification_events)
    harness.connection.queries.clear()
    headers = {} if authorization is None else {"Authorization": authorization}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/notifications/{notification['id']}/context", headers=headers,
        )
    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "no-store"
    if expected_status == 401:
        assert set(response.json()) == {"detail"}
        assert harness.connection.queries == []
    else:
        assert response.json() == {
            "kind": "crew_session", "notification_id": notification["id"],
            "delivery_revision": case.contract.revision,
            "thread": harness.threads.get_thread(case.thread.id).to_dict(),
            "session": loaded.detail.to_wire(),
        }
        assert harness.connection.queries
        assert all(sql.lstrip().upper().startswith("SELECT")
                   for sql, _parameters in harness.connection.queries)
    assert await harness.work.get_work_item(case.contract.task_id) == parent
    assert await harness.work.get_crew_session_delivery(notification["id"]) == entry
    assert harness.threads.list_messages(case.thread.id) == messages
    assert harness.notification_events == events
    assert harness.queue.snapshot() == [notification]


@pytest.mark.parametrize(
    ("failure", "expected_status", "detail"),
    [
        ("unknown", 404, "not_found"), ("deleted", 404, "not_found"),
        ("archived", 410, "archived"), ("mismatch", 409, "conflict"),
        ("corrupt", 409, "conflict"), ("unavailable", 503, "unavailable"),
        ("missing_service", 503, "unavailable"),
    ],
)
async def test_notification_context_persisted_error_boundaries(
    persisted_notification_context: Any,
    failure: str,
    expected_status: int,
    detail: str,
) -> None:
    import copy

    from httpx import ASGITransport, AsyncClient

    app, runtime, harness, case = persisted_notification_context
    notification_id = harness.queue.snapshot()[0]["id"]
    if failure == "unknown":
        assert notification_id != "a" * 64
        notification_id = "a" * 64
    elif failure == "deleted":
        harness.threads.delete_thread(case.thread.id)
    elif failure == "archived":
        harness.threads.update_thread(case.thread.id, archived=True)
    elif failure == "mismatch":
        harness.threads.update_thread(case.thread.id, task_id="other-parent")
    elif failure == "corrupt":
        await harness.connection.execute(
            "UPDATE crew_delivery_outbox SET payload_json = ? WHERE delivery_id = ?",
            ("{}", notification_id),
        )
        await harness.connection.commit()
    elif failure == "unavailable":
        await harness.work.stop()
    elif failure == "missing_service":
        runtime.crew_session_service = None
    events = copy.deepcopy(harness.notification_events)
    snapshot = harness.queue.snapshot()
    harness.connection.queries.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/notifications/{notification_id}/context")
    assert response.status_code == expected_status
    assert response.json() == {"detail": f"notification_context_{detail}"}
    assert response.headers["cache-control"] == "no-store"
    assert all(sql.lstrip().upper().startswith("SELECT")
               for sql, _parameters in harness.connection.queries)
    assert harness.notification_events == events
    assert harness.queue.snapshot() == snapshot


# ------------------------------------------------------------------
# Runtime integration tests
# ------------------------------------------------------------------

class TestUtilityRuntimeIntegration:
    """Runtime-level tests for utility agent registration and lifecycle."""

    UTILITY_POOLS = {
        "web_search", "page_reader", "weather", "news",
        "translator", "summarizer", "calculator",
        "todo_manager", "note_taker", "scheduler",
    }

    UTILITY_INTENTS = {
        "web_search", "read_page", "get_weather", "get_news",
        "translate_text", "summarize_text", "calculate",
        "manage_todo", "manage_notes", "manage_schedule",
    }

    @pytest.mark.asyncio
    async def test_all_utility_pools_created(self, runtime):
        """All 10 utility pool types are created at boot."""
        pool_names = set(runtime.pools.keys())
        assert self.UTILITY_POOLS.issubset(pool_names), (
            f"Missing utility pools: {self.UTILITY_POOLS - pool_names}"
        )

    @pytest.mark.asyncio
    async def test_utility_agents_have_llm_client(self, runtime):
        """Utility agents have llm_client reference set."""
        for pool_name in self.UTILITY_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._llm_client is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no llm_client"
                )

    @pytest.mark.asyncio
    async def test_utility_agents_have_runtime(self, runtime):
        """Utility agents have runtime reference set."""
        for pool_name in self.UTILITY_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._runtime is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no runtime"
                )

    @pytest.mark.asyncio
    async def test_intent_descriptors_include_utility(self, runtime):
        """_collect_intent_descriptors() includes all utility agent intents."""
        descriptors = runtime.decomposer._intent_descriptors
        descriptor_names = {d.name for d in descriptors}
        assert self.UTILITY_INTENTS.issubset(descriptor_names), (
            f"Missing utility intents: {self.UTILITY_INTENTS - descriptor_names}"
        )

    @pytest.mark.asyncio
    async def test_disabled_skips_utility_pools(self, runtime_no_utility):
        """utility_agents.enabled: false skips utility pool creation."""
        pool_names = set(runtime_no_utility.pools.keys())
        overlap = self.UTILITY_POOLS & pool_names
        assert len(overlap) == 0, (
            f"Utility pools should not exist when disabled: {overlap}"
        )

    @pytest.mark.asyncio
    async def test_status_includes_utility_pools(self, runtime):
        """Runtime status() includes utility agent pools."""
        status = runtime.status()
        for pool_name in self.UTILITY_POOLS:
            assert pool_name in status["pools"], (
                f"Pool {pool_name} missing from status"
            )

    @pytest.mark.asyncio
    async def test_total_agent_count(self, runtime):
        """Total agent count includes utility agents (~47 total)."""
        status = runtime.status()
        total = status["total_agents"]
        # 20 utility (10 pools × 2) + core agents
        assert total >= 40, f"Expected >= 40 agents, got {total}"

    @pytest.mark.asyncio
    async def test_utility_nl_query(self, runtime):
        """Utility agents respond to NL queries via MockLLMClient."""
        result = await runtime.process_natural_language("what's the weather in Paris")
        assert result["node_count"] >= 1
        assert result["complete"]


# ------------------------------------------------------------------
# Distribution tests: probos init
# ------------------------------------------------------------------

class TestProbOSInit:
    """Tests for `probos init` config wizard."""

    def test_init_creates_directory_structure(self, tmp_path):
        """probos init creates ~/.probos/ with subdirectories."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        args = argparse.Namespace(probos_home=str(home), force=False)

        # Simulate user input (enter defaults)
        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        assert home.exists()
        assert (home / "config.yaml").exists()
        assert (home / "data").is_dir()
        assert (home / "notes").is_dir()

    def test_init_creates_valid_yaml(self, tmp_path):
        """probos init creates a parseable YAML config."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        args = argparse.Namespace(probos_home=str(home), force=False)

        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        content = (home / "config.yaml").read_text()
        config = yaml.safe_load(content)
        assert isinstance(config, dict)
        assert config["system"]["name"] == "ProbOS"
        assert "cognitive" in config
        assert config.get("utility_agents", {}).get("enabled") is True

    def test_init_force_overwrites(self, tmp_path):
        """probos init --force overwrites existing config."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        home.mkdir()
        (home / "config.yaml").write_text("old: true")

        args = argparse.Namespace(probos_home=str(home), force=True)
        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        content = (home / "config.yaml").read_text()
        assert "old: true" not in content
        assert "ProbOS" in content

    def test_init_skips_without_force(self, tmp_path, capsys):
        """probos init without --force skips if config exists."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        home.mkdir()
        (home / "config.yaml").write_text("existing: true")

        args = argparse.Namespace(probos_home=str(home), force=False)
        _cmd_init(args)

        content = (home / "config.yaml").read_text()
        assert content == "existing: true"


class TestProbOSReset:
    """Tests for ``probos reset`` CLI subcommand (BF-070: Tiered Reset)."""

    def _make_repo(self, tmp_path):
        """Create a fake KnowledgeStore directory with sample files."""
        from probos.__main__ import _RESET_SUBDIRS
        repo = tmp_path / "knowledge"
        for sub in _RESET_SUBDIRS:
            d = repo / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / "sample.json").write_text("{}")
            (d / "sample.py").write_text("# code")
            (d / ".gitkeep").write_text("")
        return repo

    def _make_data_dir(self, tmp_path):
        """Create a data dir with files across all tiers."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Tier 1 (transients)
        (data_dir / "events.db").write_text("events")
        (data_dir / "scheduled_tasks.db").write_text("tasks")
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")
        # Tier 2 (cognition + identity) — session_last.json lives here now
        (data_dir / "session_last.json").write_text("{}")
        (data_dir / "chroma.sqlite3").write_text("chroma")
        (data_dir / "cognitive_journal.db").write_text("journal")
        (data_dir / "hebbian_weights.db").write_text("hebbian")
        (data_dir / "trust.db").write_text("trust")
        (data_dir / "service_profiles.db").write_text("profiles")
        sem_dir = data_dir / "semantic"
        sem_dir.mkdir()
        (sem_dir / "index.bin").write_text("idx")
        (data_dir / "identity.db").write_text("identity")
        (data_dir / "acm.db").write_text("acm")
        (data_dir / "skills.db").write_text("skills")
        (data_dir / "directives.db").write_text("directives")
        ont_dir = data_dir / "ontology"
        ont_dir.mkdir()
        (ont_dir / "instance_id").write_text("did:probos:old")
        # Tier 3 (institutional knowledge)
        (data_dir / "ward_room.db").write_text("ward room data")
        (data_dir / "workforce.db").write_text("workforce")
        sr_dir = data_dir / "ship-records"
        sr_dir.mkdir()
        (sr_dir / "log.md").write_text("captain's log")
        scout_dir = data_dir / "scout_reports"
        scout_dir.mkdir()
        (scout_dir / "report.json").write_text("{}")
        return data_dir

    def _reset_args(self, data_dir, **overrides):
        """Create argparse Namespace for reset with tier flags."""
        defaults = dict(
            yes=True, soft=False, full=False,
            dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_tier1_soft_only_clears_transients(self, tmp_path):
        """--soft (Tier 1) clears only runtime transients, preserves timeline."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, soft=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Tier 1 files cleared
        assert not (data_dir / "events.db").exists()
        assert not (data_dir / "scheduled_tasks.db").exists()
        assert len(list((data_dir / "checkpoints").glob("*.json"))) == 0

        # session_last.json SURVIVES soft reset (timeline intact for stasis recovery)
        assert (data_dir / "session_last.json").exists()

        # Tier 2+ files preserved
        assert (data_dir / "chroma.sqlite3").exists()
        assert (data_dir / "trust.db").exists()
        assert (data_dir / "hebbian_weights.db").exists()
        assert (data_dir / "identity.db").exists()
        assert (data_dir / "ward_room.db").exists()

    def test_tier2_default_clears_cognition_and_identity(self, tmp_path):
        """Default reset (Tier 2) clears cognition + identity, preserves institutional."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir)  # no tier flag = default Tier 2

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Tier 1+2 files cleared
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()
        assert not (data_dir / "trust.db").exists()
        assert not (data_dir / "hebbian_weights.db").exists()
        assert not (data_dir / "cognitive_journal.db").exists()
        assert not (data_dir / "service_profiles.db").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "acm.db").exists()
        assert not (data_dir / "skills.db").exists()
        assert not (data_dir / "directives.db").exists()
        assert not (data_dir / "ontology" / "instance_id").exists()
        assert not (data_dir / "events.db").exists()

        # Tier 3 files preserved
        assert (data_dir / "ward_room.db").exists()
        assert (data_dir / "workforce.db").exists()
        assert (data_dir / "ship-records").is_dir()
        assert (data_dir / "scout_reports").is_dir()

        # Knowledge subdirs cleared (Tier 2 special)
        for sub in ("episodes", "agents", "routing"):
            assert not list((repo / sub).glob("*.json"))
            assert not list((repo / sub).glob("*.py"))

    def test_tier3_full_clears_everything(self, tmp_path):
        """--full (Tier 3) clears everything including records."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, full=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # All tiers cleared
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()

        # Ward Room archived
        archives = list((data_dir / "archives").glob("ward_room_*.db"))
        assert len(archives) == 1
        assert archives[0].read_text() == "ward room data"

    def test_wipe_records_is_alias_for_full(self, tmp_path):
        """--wipe-records backward compat alias triggers Tier 3."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, wipe_records=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Same as Tier 4 — everything cleared
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()
        assert not (data_dir / "identity.db").exists()

    def test_dry_run_changes_nothing(self, tmp_path):
        """--dry-run shows what would happen but doesn't delete anything."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, dry_run=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Everything should still exist
        assert (data_dir / "session_last.json").exists()
        assert (data_dir / "chroma.sqlite3").exists()
        assert (data_dir / "identity.db").exists()
        assert (data_dir / "ward_room.db").exists()

    def test_chromadb_uuid_dirs_cleaned(self, tmp_path):
        """Default reset (Tier 2) cleans UUID-named ChromaDB HNSW index directories."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        # Create a UUID-named dir (ChromaDB HNSW index)
        uuid_dir = data_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        uuid_dir.mkdir()
        (uuid_dir / "index.bin").write_text("hnsw data")

        args = self._reset_args(data_dir)  # Default = Tier 2 (includes ChromaDB cleanup)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        assert not uuid_dir.exists()

    def test_reset_no_crash_empty_repo(self, tmp_path):
        """Reset on a nonexistent knowledge dir doesn't crash."""
        from probos.__main__ import _cmd_reset

        repo = tmp_path / "nonexistent_knowledge"
        data_dir = tmp_path / "data"

        args = self._reset_args(data_dir)
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)  # Should not raise


# ------------------------------------------------------------------
# Distribution tests: FastAPI endpoints
# ------------------------------------------------------------------

class TestFastAPIEndpoints:
    """Tests for the REST API and WebSocket server."""

    @pytest.fixture
    async def app_and_runtime(self, tmp_path):
        """Create a FastAPI app with a running runtime."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        app = create_app(rt)
        yield app, rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_health_endpoint(self, app_and_runtime):
        """GET /api/health returns correct JSON structure."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["agents"], int)
        assert data["agents"] > 0
        assert isinstance(data["health"], float)

    @pytest.mark.asyncio
    async def test_status_endpoint(self, app_and_runtime):
        """GET /api/status returns runtime status."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_agents" in data
        assert "pools" in data

    @pytest.mark.asyncio
    async def test_system_extensions_returns_empty_list(self, app_and_runtime):
        """BF-321 (#790): /api/system/extensions returns the empty-stub shape."""
        from httpx import ASGITransport, AsyncClient

        app, _rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/system/extensions")

        assert resp.status_code == 200
        assert resp.json() == {"extensions": []}

    @pytest.mark.asyncio
    async def test_chat_endpoint(self, app_and_runtime):
        """POST /api/chat processes message and returns response."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "hello"},
                timeout=30.0,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "dag" in data
        assert "results" in data

    @pytest.mark.asyncio
    async def test_create_app_returns_fastapi(self):
        """create_app() returns a FastAPI instance."""
        from fastapi import FastAPI

        class FakeRuntime:
            def status(self):
                return {"total_agents": 0}

        app = create_app(FakeRuntime())
        assert isinstance(app, FastAPI)
        assert app.title == "ProbOS"

    @pytest.mark.asyncio
    async def test_enrich_endpoint_returns_enriched(self, app_and_runtime):
        """POST /api/selfmod/enrich returns enriched spec from LLM."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/selfmod/enrich",
                json={
                    "intent_name": "lookup_person",
                    "intent_description": "Look up a person online",
                    "parameters": {"name": "<person_name>"},
                    "user_guidance": "Search DuckDuckGo, find LinkedIn profiles",
                },
                timeout=30.0,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "enriched" in data
        assert len(data["enriched"]) > 0
        assert data["status"] == "ok"
        assert data["intent_name"] == "lookup_person"

    @pytest.mark.asyncio
    async def test_enrich_endpoint_fallback_without_llm(self):
        """Enrich returns user_guidance when no LLM is available."""
        from httpx import ASGITransport, AsyncClient

        class NoLLMRuntime:
            def status(self):
                return {"total_agents": 0}

        app = create_app(NoLLMRuntime())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/selfmod/enrich",
                json={
                    "intent_name": "test_intent",
                    "intent_description": "A test",
                    "parameters": {},
                    "user_guidance": "My raw guidance text",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["enriched"] == "My raw guidance text"
        assert data["status"] == "no_llm"


# ------------------------------------------------------------------
# AD-1243: GET /api/traces/{ref}/consulted -- bounded, redacted evidence
# ------------------------------------------------------------------

@pytest.fixture
async def consulted_api(tmp_path):
    """The traces router over a real ``FilesystemAttachmentStore``.

    Mirrors ``notification_context_api``'s shape (``SimpleNamespace`` runtime
    + dependency override) rather than ``app_and_runtime``'s full
    ``ProbOSRuntime`` -- this route only reads ``attachment_store`` and
    ``config.auth``, and a real store lets the happy-path round-trip an
    actual persisted trace instead of a hand-built fake.
    """
    from types import SimpleNamespace

    from fastapi import FastAPI

    from probos.attachments.filesystem_store import FilesystemAttachmentStore
    from probos.routers import traces
    from probos.routers.deps import get_runtime

    store = FilesystemAttachmentStore(tmp_path / "attachments")
    app = FastAPI()
    app.include_router(traces.router)
    runtime = SimpleNamespace(config=SystemConfig(), attachment_store=store)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app, runtime, store


async def _persist_trace(store: Any, entries: list) -> str:
    import hashlib

    blob = json.dumps(entries).encode("utf-8")
    trace_ref = hashlib.sha256(blob).hexdigest()
    await store.write(trace_ref, blob, "application/json", origin="crew_trace")
    return trace_ref


@pytest.mark.parametrize("authorized", [False, True])
async def test_consulted_happy_path_returns_bounded_redacted_shape(consulted_api, authorized):
    from httpx import ASGITransport, AsyncClient

    app, runtime, store = consulted_api
    runtime.config.auth.crew_scope_token = "synthetic-consulted-auth" if authorized else ""
    ref = await _persist_trace(store, [
        {"name": "clone_repo", "arguments": {"repoName": "langchain-ai/langchain"}},
        {"name": "http_fetch", "arguments": {"password": "hunter2"}},
        "not-a-dict",
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/traces/{ref}/consulted",
            headers={"Authorization": "Bearer synthetic-consulted-auth"} if authorized else {},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "ref", "requests", "requests_total", "requests_omitted",
        "invalid_entries", "redacted", "truncated", "notice",
    }
    assert body["ref"] == ref
    assert body["invalid_entries"] == 1
    assert body["requests_total"] == 2
    assert body["requests_omitted"] == 0
    assert body["truncated"] is False
    assert body["redacted"] is True
    assert len(body["requests"]) == 2
    assert "langchain-ai/langchain" in body["requests"][0]
    raw_bytes = response.content
    assert b"hunter2" not in raw_bytes
    assert b"REDACTED" in raw_bytes
    # BF-775-style guarantee: no raw tool output ever appears in this route.
    assert b'"output"' not in raw_bytes


async def test_consulted_response_never_exceeds_16kib_on_the_wire(consulted_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = consulted_api
    entries = [
        {
            "name": "clone_repo",
            "arguments": {f"argument_{j}": ("x" * 80) + f"-{i}-{j}" for j in range(6)},
        }
        for i in range(40)
    ]
    ref = await _persist_trace(store, entries)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) <= 16 * 1024
    body = response.json()
    assert body["truncated"] is True
    assert body["requests_omitted"] > 0
    assert body["requests_total"] == len(body["requests"]) + body["requests_omitted"]


async def test_consulted_missing_or_unreadable_trace_is_404(consulted_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, _store = consulted_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{'a' * 64}/consulted")

    assert response.status_code == 404
    assert response.json() == {"detail": "Trace not found or unreadable"}
    assert response.headers["cache-control"] == "no-store"


async def test_consulted_missing_store_is_503(consulted_api):
    from httpx import ASGITransport, AsyncClient

    app, runtime, _store = consulted_api
    runtime.attachment_store = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{'a' * 64}/consulted")

    assert response.status_code == 503
    assert response.json() == {"detail": "Attachment store not available"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("ref", ["short", "z" * 64, "g" * 12, "a" * 65])
async def test_consulted_invalid_ref_is_400(consulted_api, ref):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, _store = consulted_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid trace reference"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Bearer correct"])
async def test_consulted_auth_checked_before_storage_access(consulted_api, authorization):
    """Auth is enforced before the ref is even looked at: a bad token with a
    ref that does not exist still comes back 401, never 404, and every
    branch -- success included -- carries ``Cache-Control: no-store``."""
    from httpx import ASGITransport, AsyncClient

    app, runtime, _store = consulted_api
    runtime.config.auth.crew_scope_token = "correct"
    headers = {} if authorization is None else {"Authorization": authorization}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{'a' * 64}/consulted", headers=headers)

    assert response.status_code == (404 if authorization == "Bearer correct" else 401)
    assert set(response.json()) == {"detail"}
    assert response.headers["cache-control"] == "no-store"


async def test_consulted_default_off_auth_allows_unauthenticated_success(consulted_api):
    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = consulted_api
    ref = await _persist_trace(store, [{"name": "recall_artifact", "arguments": {}}])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


async def test_consulted_unexpected_failure_is_sanitised_500(consulted_api, monkeypatch, caplog):
    from httpx import ASGITransport, AsyncClient

    from probos.routers import traces

    app, _runtime, store = consulted_api
    ref = await _persist_trace(store, [{"name": "recall_artifact", "arguments": {}}])

    def _boom(entries, ref):
        raise RuntimeError("controlled consulted-projection failure")

    monkeypatch.setattr(traces, "build_consulted_receipt", _boom)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")

    assert response.status_code == 500
    assert response.json() == {"detail": "Could not build consulted evidence"}
    assert response.headers["cache-control"] == "no-store"
    assert b"controlled consulted-projection failure" not in response.content
    assert "controlled consulted-projection failure" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_consulted_read_failure_is_404_without_exception_text_in_logs(
    consulted_api, monkeypatch, caplog,
):
    import logging

    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = consulted_api

    async def _fail_read(content_hash: str) -> bytes:
        raise RuntimeError("synthetic-sensitive-read-detail")

    monkeypatch.setattr(store, "read", _fail_read)
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.trace_analysis")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{'a' * 64}/consulted")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert b"synthetic-sensitive-read-detail" not in response.content
    assert "synthetic-sensitive-read-detail" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("blob", [b"{unreadable", b"\xffsynthetic-sensitive-read-detail", b'{"not": "a list"}'])
async def test_consulted_unreadable_storage_is_safe_404(consulted_api, blob, caplog):
    import hashlib
    import logging

    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = consulted_api
    ref = hashlib.sha256(blob).hexdigest()
    await store.write(ref, blob, "application/json", origin="crew_trace")
    caplog.set_level(logging.DEBUG, logger="probos.cognitive.trace_analysis")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert b"synthetic-sensitive-read-detail" not in response.content
    assert "synthetic-sensitive-read-detail" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_consulted_serialization_failure_is_safe_no_store_500(consulted_api, monkeypatch, caplog):
    from httpx import ASGITransport, AsyncClient

    from probos.routers import traces

    app, _runtime, store = consulted_api
    ref = await _persist_trace(store, [{"name": "lookup", "arguments": {}}])
    monkeypatch.setattr(traces, "build_consulted_receipt", lambda entries, ref: {"requests": [object()]})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/traces/{ref}/consulted")
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Could not build consulted evidence"}
    assert all(record.exc_info is None for record in caplog.records)


async def test_consulted_cancelled_read_propagates_and_cleans_up(consulted_api, monkeypatch):
    import asyncio

    from httpx import ASGITransport, AsyncClient

    app, _runtime, store = consulted_api
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def _blocked(content_hash: str) -> bytes:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
        raise AssertionError("unreachable")

    monkeypatch.setattr(store, "read", _blocked)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.get(f"/api/traces/{'a' * 64}/consulted"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cleaned.is_set()
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
