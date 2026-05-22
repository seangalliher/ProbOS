"""AD-815a: TaskSession substrate tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.task_sessions import (
    InvalidStatusTransition,
    TaskSessionStore,
)


# ---------------- Store: sessions ----------------


def _store(tmp_path: Path) -> TaskSessionStore:
    return TaskSessionStore(
        db_path=tmp_path / "ts.db",
        workspace_root=tmp_path / "workspaces",
    )


def test_create_session_provisions_folders(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="Generate report")
    root = Path(sess.root_dir)
    assert root.exists()
    assert (root / "inputs").is_dir()
    assert (root / "outputs").is_dir()
    assert (root / "scratch").is_dir()
    assert sess.status == "pending"


def test_create_session_persists_schedule_fields(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1",
        title="Daily summary",
        schedule_kind="recurring",
        schedule_cron="0 9 * * *",
        schedule_timezone="America/Los_Angeles",
        recurrence_policy="new_session_each_run",
        recurrence_max_runs=30,
    )
    fetched = s.get_session(sess.id)
    assert fetched is not None
    assert fetched.schedule_kind == "recurring"
    assert fetched.schedule_cron == "0 9 * * *"
    assert fetched.recurrence_policy == "new_session_each_run"
    assert fetched.recurrence_max_runs == 30


def test_list_sessions_filters_by_thread(tmp_path):
    s = _store(tmp_path)
    a = s.create_session(thread_id="t1", title="a")
    s.create_session(thread_id="t2", title="b")
    listed = s.list_sessions(thread_id="t1")
    assert [x.id for x in listed] == [a.id]


def test_list_sessions_filters_by_status(tmp_path):
    s = _store(tmp_path)
    a = s.create_session(thread_id="t1", title="a")
    s.set_status(a.id, "running")
    s.create_session(thread_id="t1", title="b")
    pending = s.list_sessions(status="pending")
    running = s.list_sessions(status="running")
    assert len(pending) == 1 and len(running) == 1


def test_set_status_validates_transitions(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.set_status(sess.id, "running")
    with pytest.raises(InvalidStatusTransition):
        s.set_status(sess.id, "pending")  # running -> pending illegal


def test_set_status_completed_stamps_completed_at(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.set_status(sess.id, "running")
    final = s.set_status(sess.id, "completed")
    assert final is not None
    assert final.completed_at is not None


def test_set_work_item_links(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.set_work_item(sess.id, "wi-42")
    assert s.get_session(sess.id).work_item_id == "wi-42"


def test_cancel_session_terminal_is_noop(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.set_status(sess.id, "running")
    s.set_status(sess.id, "completed")
    after = s.cancel(sess.id)
    assert after.status == "completed"  # unchanged


# ---------------- Store: runs ----------------


def test_start_run_transitions_to_running(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    run = s.start_run(sess.id)
    assert run is not None
    assert s.get_session(sess.id).status == "running"
    assert s.get_session(sess.id).last_run_at is not None


def test_start_run_rejects_non_pending(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.start_run(sess.id)
    with pytest.raises(InvalidStatusTransition):
        s.start_run(sess.id)


def test_finish_run_zero_exit_marks_completed(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    run = s.start_run(sess.id)
    finished = s.finish_run(
        run.id,
        exit_code=0,
        container_image_used="probos/cowork-base:latest",
        pip_installed_extras=["polars"],
    )
    assert finished.exit_code == 0
    assert finished.pip_installed_extras == ["polars"]
    assert s.get_session(sess.id).status == "completed"


def test_finish_run_nonzero_exit_marks_failed(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=2, container_image_used="img", error="boom")
    assert s.get_session(sess.id).status == "failed"


def test_list_runs_chronological(tmp_path):
    clock = {"t": 0.0}
    s = TaskSessionStore(
        db_path=tmp_path / "ts.db",
        workspace_root=tmp_path / "ws",
        clock=lambda: clock["t"],
    )
    sess = s.create_session(thread_id="t1", title="x")
    clock["t"] = 1.0
    r1 = s.start_run(sess.id)
    clock["t"] = 2.0
    s.finish_run(r1.id, exit_code=0, container_image_used="img")
    clock["t"] = 3.0
    s.rearm(sess.id)
    clock["t"] = 4.0
    s.start_run(sess.id)
    runs = s.list_runs(sess.id)
    assert len(runs) == 2
    assert runs[0].started_at == 1.0
    assert runs[1].started_at == 4.0


def test_rearm_recurring_back_to_pending(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1", title="x", schedule_kind="recurring"
    )
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    rearmed = s.rearm(sess.id)
    assert rearmed.status == "pending"


def test_rearm_cancelled_is_noop(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    s.cancel(sess.id)
    assert s.rearm(sess.id).status == "cancelled"


# ---------------- REST ----------------


@pytest.fixture
def client(tmp_path):
    from probos.routers import task_sessions as router_module
    from probos.routers.deps import get_runtime

    store = _store(tmp_path)
    runtime = SimpleNamespace(task_session_store=store)
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), store


def test_rest_create_and_list(client):
    c, _ = client
    r = c.post(
        "/api/task-sessions",
        json={"thread_id": "t1", "title": "Generate report"},
    )
    assert r.status_code == 200
    sess = r.json()
    assert sess["status"] == "pending"
    listed = c.get("/api/task-sessions").json()["sessions"]
    assert len(listed) == 1


def test_rest_run_lifecycle(client):
    c, _ = client
    sid = c.post(
        "/api/task-sessions", json={"thread_id": "t1", "title": "x"}
    ).json()["id"]
    run = c.post(f"/api/task-sessions/{sid}/run").json()
    assert "id" in run
    finished = c.post(
        f"/api/task-sessions/runs/{run['id']}/finish",
        json={"exit_code": 0, "container_image_used": "img"},
    ).json()
    assert finished["exit_code"] == 0
    sess = c.get(f"/api/task-sessions/{sid}").json()
    assert sess["status"] == "completed"


def test_rest_409_when_starting_running_session(client):
    c, _ = client
    sid = c.post(
        "/api/task-sessions", json={"thread_id": "t1", "title": "x"}
    ).json()["id"]
    c.post(f"/api/task-sessions/{sid}/run")
    r = c.post(f"/api/task-sessions/{sid}/run")
    assert r.status_code == 409


def test_rest_404_for_missing_session(client):
    c, _ = client
    assert c.get("/api/task-sessions/missing").status_code == 404
    assert c.post("/api/task-sessions/missing/run").status_code == 404
    assert c.post("/api/task-sessions/missing/cancel").status_code == 404


def test_rest_cancel(client):
    c, _ = client
    sid = c.post(
        "/api/task-sessions", json={"thread_id": "t1", "title": "x"}
    ).json()["id"]
    r = c.post(f"/api/task-sessions/{sid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_rest_503_when_store_missing(tmp_path):
    from probos.routers import task_sessions as router_module
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace()
    c = TestClient(app)
    assert c.get("/api/task-sessions").status_code == 503


def test_rest_schedule_validation(client):
    c, _ = client
    r = c.post(
        "/api/task-sessions",
        json={
            "thread_id": "t1",
            "title": "x",
            "schedule_kind": "bogus",
        },
    )
    assert r.status_code == 422


def test_rest_egress_validation(client):
    c, _ = client
    r = c.post(
        "/api/task-sessions",
        json={"thread_id": "t1", "title": "x", "egress_policy": "wide-open"},
    )
    assert r.status_code == 422
