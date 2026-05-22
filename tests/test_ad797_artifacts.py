"""AD-797: artifacts substrate tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.artifacts import ArtifactStore


# ---------------- Store ----------------


def _add(store, *, thread_id="t1", name="report.md", content_hash="aa", mime="text/markdown", size=10, by="agent-1"):
    return store.add_version(
        thread_id=thread_id,
        name=name,
        content_hash=content_hash,
        mime=mime,
        size_bytes=size,
        created_by=by,
    )


def test_add_first_version_starts_at_1(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    a = _add(store)
    assert a.version == 1 and a.supersedes is None


def test_add_subsequent_versions_increment_and_link(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    v1 = _add(store, content_hash="aa")
    v2 = _add(store, content_hash="bb")
    v3 = _add(store, content_hash="cc")
    assert (v1.version, v2.version, v3.version) == (1, 2, 3)
    assert v2.supersedes == v1.id and v3.supersedes == v2.id


def test_versions_are_per_name(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    a1 = _add(store, name="report.md")
    b1 = _add(store, name="diagram.svg")
    assert a1.version == 1 and b1.version == 1


def test_versions_are_per_thread(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    t1v1 = _add(store, thread_id="t1")
    t2v1 = _add(store, thread_id="t2")
    assert t1v1.version == 1 and t2v1.version == 1


def test_latest_returns_highest_version(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    _add(store, content_hash="a")
    _add(store, content_hash="b")
    v3 = _add(store, content_hash="c")
    latest = store.latest(thread_id="t1", name="report.md")
    assert latest is not None and latest.id == v3.id


def test_latest_missing_returns_none(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    assert store.latest(thread_id="t1", name="nope") is None


def test_list_versions_chronological_ascending(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    ids = [_add(store, content_hash=str(i)).id for i in range(3)]
    versions = store.list_versions(thread_id="t1", name="report.md")
    assert [v.id for v in versions] == ids


def test_list_thread_latest_dedups_by_name(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    _add(store, name="a", content_hash="1")
    _add(store, name="a", content_hash="2")
    _add(store, name="b", content_hash="3")
    items = store.list_thread_latest("t1")
    by_name = {x.name: x for x in items}
    assert set(by_name) == {"a", "b"}
    assert by_name["a"].content_hash == "2"


def test_get_returns_none_for_missing(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    assert store.get("nope") is None


def test_delete_works(tmp_path):
    store = ArtifactStore(tmp_path / "a.db")
    a = _add(store)
    assert store.delete(a.id) is True
    assert store.get(a.id) is None
    assert store.delete(a.id) is False


# ---------------- REST ----------------


@pytest.fixture
def client(tmp_path):
    from probos.routers import artifacts as artifacts_router
    from probos.routers.deps import get_runtime

    store = ArtifactStore(tmp_path / "a.db")
    runtime = SimpleNamespace(artifact_store=store)
    app = FastAPI()
    app.include_router(artifacts_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app), store


def _payload(**over):
    base = {
        "thread_id": "t1",
        "name": "report.md",
        "content_hash": "abc123def456",
        "mime": "text/markdown",
        "size_bytes": 42,
        "created_by": "agent-1",
    }
    base.update(over)
    return base


def test_rest_add_and_list(client):
    c, _ = client
    r = c.post("/api/artifacts", json=_payload())
    assert r.status_code == 200 and r.json()["version"] == 1
    r = c.post("/api/artifacts", json=_payload(content_hash="xxxxxxxxxx"))
    assert r.json()["version"] == 2
    lst = c.get("/api/artifacts/thread/t1").json()["artifacts"]
    assert len(lst) == 1 and lst[0]["version"] == 2


def test_rest_versions_listing(client):
    c, _ = client
    for h in ("aaaaaaaa", "bbbbbbbb", "cccccccc"):
        c.post("/api/artifacts", json=_payload(content_hash=h))
    r = c.get("/api/artifacts/thread/t1/name/report.md/versions").json()
    assert [v["version"] for v in r["versions"]] == [1, 2, 3]


def test_rest_get_by_id(client):
    c, _ = client
    a = c.post("/api/artifacts", json=_payload()).json()
    r = c.get(f"/api/artifacts/{a['id']}")
    assert r.status_code == 200 and r.json()["id"] == a["id"]


def test_rest_get_404(client):
    c, _ = client
    assert c.get("/api/artifacts/missing").status_code == 404


def test_rest_delete(client):
    c, _ = client
    a = c.post("/api/artifacts", json=_payload()).json()
    r = c.delete(f"/api/artifacts/{a['id']}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert c.get(f"/api/artifacts/{a['id']}").status_code == 404


def test_rest_503_when_store_missing(tmp_path):
    from probos.routers import artifacts as artifacts_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(artifacts_router.router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace()
    c = TestClient(app)
    assert c.get("/api/artifacts/thread/anything").status_code == 503
