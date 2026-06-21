"""AD-1021b: governed Monaco workstation write-through — read + write endpoints.

Mirrors ``tests/test_ad998_workspace_api.py`` (BF-287): a REAL ``ExecutionConfig``
at the config boundary (a MagicMock would make the gating bools truthy) + a REAL
``WorkspaceManager`` resolving under ``tmp_path``. The governed-write primitive is
the seam that is mocked — ``runtime.submit_write_with_consensus`` is an
``AsyncMock`` (NOT a config-boundary MagicMock), so the path-confinement + gating
logic runs for real while the consensus pipeline is stubbed.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from probos.config import AuthConfig, ExecutionConfig


def _client(
    tmp_path: Path,
    *,
    enabled: bool = True,
    persistent: bool = True,
    write_enabled: bool = False,
    agent=None,
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
    return TestClient(create_app(runtime)), runtime


def _seed(tmp_path: Path, owner: str, name: str, body: str) -> None:
    ws = tmp_path / "ws" / owner
    ws.mkdir(parents=True, exist_ok=True)
    (ws / name).write_text(body, encoding="utf-8")


# ── READ ──────────────────────────────────────────────────────────────────

def test_read_returns_file_content_when_found(tmp_path: Path):
    _seed(tmp_path, "code_runner", "main.py", "print('hi')")
    client, _ = _client(tmp_path)
    resp = client.get("/api/agent/cr-1/workspace/file", params={"path": "main.py"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is True
    assert body["content"] == "print('hi')"
    assert body["size_bytes"] >= 11
    assert body["too_large"] is False


def test_read_missing_file_honest_degrades_found_false(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/agent/cr-1/workspace/file", params={"path": "nope.py"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["content"] is None


def test_read_disabled_execution_honest_degrades(tmp_path: Path):
    _seed(tmp_path, "code_runner", "main.py", "x")
    client, _ = _client(tmp_path, enabled=False)
    resp = client.get("/api/agent/cr-1/workspace/file", params={"path": "main.py"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["content"] is None


def test_read_traversal_rejected_400(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get(
        "/api/agent/cr-1/workspace/file", params={"path": "../../../etc/passwd"}
    )
    assert resp.status_code == 400


def test_read_absolute_path_rejected_400(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/agent/cr-1/workspace/file", params={"path": "/etc/passwd"})
    assert resp.status_code == 400


# ── WRITE ─────────────────────────────────────────────────────────────────

def test_write_default_off_returns_503_no_governance(tmp_path: Path):
    client, runtime = _client(tmp_path, write_enabled=False)
    runtime.submit_write_with_consensus = AsyncMock()
    resp = client.post(
        "/api/agent/cr-1/workspace/file", json={"path": "out.py", "content": "x=1"}
    )
    assert resp.status_code == 503
    runtime.submit_write_with_consensus.assert_not_called()


def test_write_traversal_rejected_400_before_governance(tmp_path: Path):
    client, runtime = _client(tmp_path, write_enabled=True)
    runtime.submit_write_with_consensus = AsyncMock()
    resp = client.post(
        "/api/agent/cr-1/workspace/file",
        json={"path": "../../evil.py", "content": "x=1"},
    )
    assert resp.status_code == 400
    # The path guard MUST precede the governed write — nothing reaches consensus.
    runtime.submit_write_with_consensus.assert_not_called()


def test_write_committed_routes_through_consensus_with_confined_path(tmp_path: Path):
    from probos.types import ConsensusOutcome, ConsensusResult

    client, runtime = _client(tmp_path, write_enabled=True)
    runtime.submit_write_with_consensus = AsyncMock(
        return_value={
            "committed": True,
            "consensus": ConsensusResult(
                proposal_id="p",
                outcome=ConsensusOutcome.APPROVED,
                weighted_approval=4.0,
                total_weight=4.0,
            ),
        }
    )
    resp = client.post(
        "/api/agent/cr-1/workspace/file",
        json={"path": "sub/out.py", "content": "x=1"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"] == "committed"
    runtime.submit_write_with_consensus.assert_awaited_once()
    kwargs = runtime.submit_write_with_consensus.await_args.kwargs
    assert kwargs["content"] == "x=1"
    # The CONFINED absolute path is what reaches the write primitive.
    passed = Path(kwargs["path"])
    assert passed.name == "out.py"
    assert passed.parent.name == "sub"
    assert passed.parent.parent.name == "code_runner"


def test_write_refused_maps_consensus_outcome(tmp_path: Path):
    from probos.types import ConsensusOutcome, ConsensusResult

    client, runtime = _client(tmp_path, write_enabled=True)
    runtime.submit_write_with_consensus = AsyncMock(
        return_value={
            "committed": False,
            "consensus": ConsensusResult(
                proposal_id="p",
                outcome=ConsensusOutcome.REJECTED,
                weighted_approval=1.0,
                total_weight=4.0,
            ),
        }
    )
    resp = client.post(
        "/api/agent/cr-1/workspace/file", json={"path": "out.py", "content": "x=1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "refused"
    assert body["consensus_outcome"] == "rejected"
    assert body["approval_ratio"] == 0.25


def test_write_governance_exception_degrades_to_refused_never_500(tmp_path: Path):
    client, runtime = _client(tmp_path, write_enabled=True)
    runtime.submit_write_with_consensus = AsyncMock(side_effect=RuntimeError("boom"))
    resp = client.post(
        "/api/agent/cr-1/workspace/file", json={"path": "out.py", "content": "x=1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "refused"
    assert body["consensus_outcome"] == "error"


def test_write_over_cap_returns_413_no_governance(tmp_path: Path):
    client, runtime = _client(tmp_path, write_enabled=True)
    runtime.submit_write_with_consensus = AsyncMock()
    big = "x" * (1_048_576 + 1)
    resp = client.post(
        "/api/agent/cr-1/workspace/file", json={"path": "big.py", "content": big}
    )
    assert resp.status_code == 413
    runtime.submit_write_with_consensus.assert_not_called()


# ── resolve_file unit (DD-3 confinement, real tmp_path) ─────────────────────

def test_resolve_file_confines_to_owner_folder(tmp_path: Path):
    from probos.execution.workspace import WorkspaceManager

    mgr = WorkspaceManager(str(tmp_path / "ws"))

    ok = mgr.resolve_file("code_runner", "a/b.py")
    assert ok is not None
    assert ok.name == "b.py"
    assert ok.parent.parent.name == "code_runner"

    # traversal escape -> None
    assert mgr.resolve_file("code_runner", "../../etc/passwd") is None
    # absolute -> None
    assert mgr.resolve_file("code_runner", str(tmp_path / "outside.py")) is None
    # empty / NUL -> None
    assert mgr.resolve_file("code_runner", "") is None
    assert mgr.resolve_file("code_runner", "a\x00b") is None
    # the folder itself (not a file) -> None
    assert mgr.resolve_file("code_runner", ".") is None

    # create_parents materializes the confined parent dir
    target = mgr.resolve_file("code_runner", "deep/dir/file.py", create_parents=True)
    assert target is not None
    assert target.parent.is_dir()
