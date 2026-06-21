"""AD-1021c: agent co-edit suggestions — list / propose / dismiss endpoints + store.

Mirrors ``tests/test_ad1021b_workspace_write.py`` (BF-287): a REAL
``ExecutionConfig`` at the config boundary (a MagicMock would make the gating
bools truthy) + a REAL ``WorkspaceManager`` resolving under ``tmp_path``, AND a
REAL ``WorkspaceSuggestionStore`` attached explicitly on the runtime — NOT a
MagicMock-derived attribute (a MagicMock runtime auto-fakes
``runtime.workspace_suggestions.add`` and a broken endpoint would pass). The
"did not enter the store" guarantee is proven with ``patch.object(store, "add",
wraps=...)`` spies that keep the real behavior while asserting call count.

The WHOLE co-edit surface is gated on the EXISTING
``execution.workspace_write_enabled`` flag (Accept routes through the AD-1021b
governed write): list honest-degrades to ``[]`` when off, post/dismiss ``503``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from probos.config import AuthConfig, ExecutionConfig
from probos.execution.workspace_suggestions import WorkspaceSuggestionStore

# The sanitized owner key for the test agent (callsign empty -> agent_type).
OWNER = "code_runner"


def _client(
    tmp_path: Path,
    *,
    enabled: bool = True,
    persistent: bool = True,
    write_enabled: bool = True,
    agent=None,
    store: WorkspaceSuggestionStore | None = None,
):
    from probos.api import create_app

    exec_cfg = ExecutionConfig(
        enabled=enabled,
        persistent_workspaces=persistent,
        workspace_root=str(tmp_path / "ws"),
        workspace_write_enabled=write_enabled,
    )
    agent = agent or SimpleNamespace(id="cr-1", callsign="", agent_type="code_runner")
    runtime = MagicMock()
    runtime.registry.get = MagicMock(return_value=agent)
    cfg = MagicMock()
    cfg.execution = exec_cfg          # REAL config — gating depends on it (BF-287)
    cfg.auth = AuthConfig()
    runtime.config = cfg
    real_store = store or WorkspaceSuggestionStore()
    # REAL store, explicitly attached (NOT a MagicMock auto-attribute).
    runtime.workspace_suggestions = real_store
    return TestClient(create_app(runtime)), runtime, real_store


# ── LIST ────────────────────────────────────────────────────────────────────

def test_list_honest_degrades_empty_when_co_edit_off(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=False)
    # Even with a suggestion in the store, the off switch hides it (honest-degrade).
    store.add(OWNER, "main.py", "x=1", "forge-1", "Forge")
    resp = client.get("/api/agent/cr-1/workspace/suggestions", params={"path": "main.py"})
    assert resp.status_code == 200
    assert resp.json()["suggestions"] == []


def test_list_returns_suggestions_when_enabled(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=True)
    store.add(OWNER, "main.py", "x=1", "forge-1", "Forge", "tweak")
    resp = client.get("/api/agent/cr-1/workspace/suggestions", params={"path": "main.py"})
    assert resp.status_code == 200, resp.text
    items = resp.json()["suggestions"]
    assert len(items) == 1
    assert items[0]["content"] == "x=1"
    assert items[0]["author_id"] == "forge-1"
    assert items[0]["author_callsign"] == "Forge"
    assert items[0]["note"] == "tweak"
    assert items[0]["id"]


def test_list_traversal_rejected_400(tmp_path: Path):
    client, _, _ = _client(tmp_path, write_enabled=True)
    resp = client.get(
        "/api/agent/cr-1/workspace/suggestions", params={"path": "../../../etc/passwd"}
    )
    assert resp.status_code == 400


# ── POST (propose) ──────────────────────────────────────────────────────────

def test_post_default_off_returns_503_store_untouched(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=False)
    with patch.object(store, "add", wraps=store.add) as add_spy:
        resp = client.post(
            "/api/agent/cr-1/workspace/suggestions",
            json={"path": "out.py", "content": "x=1", "author_id": "forge-1"},
        )
    assert resp.status_code == 503
    add_spy.assert_not_called()


def test_post_traversal_rejected_400_before_store(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=True)
    with patch.object(store, "add", wraps=store.add) as add_spy:
        resp = client.post(
            "/api/agent/cr-1/workspace/suggestions",
            json={"path": "../../evil.py", "content": "x=1", "author_id": "forge-1"},
        )
    assert resp.status_code == 400
    # The path guard MUST precede the store — a traversal never gets queued.
    add_spy.assert_not_called()
    assert store.list(OWNER, "evil.py") == []


def test_post_over_cap_returns_413_store_untouched(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=True)
    big = "x" * (1_048_576 + 1)
    with patch.object(store, "add", wraps=store.add) as add_spy:
        resp = client.post(
            "/api/agent/cr-1/workspace/suggestions",
            json={"path": "big.py", "content": big, "author_id": "forge-1"},
        )
    assert resp.status_code == 413
    add_spy.assert_not_called()


def test_post_adds_suggestion_when_enabled(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=True)
    resp = client.post(
        "/api/agent/cr-1/workspace/suggestions",
        json={
            "path": "sub/out.py",
            "content": "y=2",
            "author_id": "forge-1",
            "author_callsign": "Forge",
            "note": "rewrite",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["suggestion"]
    assert body["path"] == "sub/out.py"
    assert body["content"] == "y=2"
    assert body["author_callsign"] == "Forge"
    # The REAL store actually holds it (proves the endpoint hit the real attr).
    stored = store.list(OWNER, "sub/out.py")
    assert len(stored) == 1
    assert stored[0].content == "y=2"


# ── DISMISS ─────────────────────────────────────────────────────────────────

def test_dismiss_default_off_returns_503(tmp_path: Path):
    client, _, _ = _client(tmp_path, write_enabled=False)
    resp = client.post("/api/agent/cr-1/workspace/suggestions/abc/dismiss")
    assert resp.status_code == 503


def test_dismiss_removes_existing_returns_true(tmp_path: Path):
    client, _, store = _client(tmp_path, write_enabled=True)
    s = store.add(OWNER, "main.py", "x=1", "forge-1")
    resp = client.post(f"/api/agent/cr-1/workspace/suggestions/{s.id}/dismiss")
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is True
    assert store.list(OWNER, "main.py") == []


def test_dismiss_missing_returns_false_no_404(tmp_path: Path):
    client, _, _ = _client(tmp_path, write_enabled=True)
    resp = client.post("/api/agent/cr-1/workspace/suggestions/ghost/dismiss")
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is False


# ── store unit (bound + add/list/dismiss/clear) ─────────────────────────────

def test_store_bound_evicts_oldest():
    store = WorkspaceSuggestionStore(max_per_path=3)
    ids = [store.add("o", "p", f"c{i}", "a").id for i in range(4)]
    listed = store.list("o", "p")
    assert len(listed) == 3
    # The oldest (first inserted) is evicted; the newest is retained.
    assert [s.id for s in listed] == ids[1:]


def test_store_add_list_dismiss_clear_unit():
    store = WorkspaceSuggestionStore()
    s1 = store.add("o", "p1", "c1", "a1", "A1", "n1")
    store.add("o", "p2", "c2", "a2")
    assert store.list("o", "p1") == [s1]
    assert store.list("o", "unknown") == []
    # dismiss is owner-scoped, by id (no path) — finds across buckets.
    assert store.dismiss("o", s1.id) is True
    assert store.list("o", "p1") == []
    assert store.dismiss("o", "ghost") is False
    # clear(owner) drops everything for the owner.
    store.clear("o")
    assert store.list("o", "p2") == []
