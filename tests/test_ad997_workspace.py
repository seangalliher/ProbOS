"""AD-997: per-agent working folders (WorkspaceManager + persistent execution).

BF-287: real WorkspaceManager + real ExecutionConfig + real subprocess runs
under tmp_path (no mocks at the substrate boundary). Cross-platform.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.code_runner import CodeRunnerAgent
from probos.config import ExecutionConfig
from probos.execution.workspace import WorkspaceFile, WorkspaceManager
from probos.types import IntentMessage


# ---------------------------------------------------------------------------
# WorkspaceManager — keying + sanitize
# ---------------------------------------------------------------------------


def test_sanitize_keeps_safe_chars(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    assert mgr.sanitize("Ezri") == "ezri"
    assert mgr.sanitize("counselor_0") == "counselor_0"
    assert mgr.sanitize("a/b\\c..d") == "a_b_c_d"
    assert mgr.sanitize("  ") == "shared"
    assert mgr.sanitize("") == "shared"


def test_sanitize_blocks_traversal(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    # A traversal attempt resolves to a child of root, never escapes.
    p = mgr.resolve("../../etc/passwd")
    assert tmp_path in p.parents
    assert p.parent == tmp_path


def test_key_for_agent_prefers_callsign(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    assert mgr.key_for_agent(SimpleNamespace(callsign="Ezri", agent_type="counselor", id="x")) == "ezri"
    assert mgr.key_for_agent(SimpleNamespace(callsign="", agent_type="code_runner", id="x")) == "code_runner"
    assert mgr.key_for_agent(SimpleNamespace(callsign="", agent_type="", id="abc123")) == "abc123"


def test_resolve_create(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path / "ws")
    p = mgr.resolve("ezri", create=True)
    assert p.is_dir()
    assert p == tmp_path / "ws" / "ezri"


def test_venv_dir(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    assert mgr.venv_dir("ezri") == tmp_path / "ezri" / ".venv"


# ---------------------------------------------------------------------------
# WorkspaceManager — inspection
# ---------------------------------------------------------------------------


def test_list_files_absent_is_empty(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    assert mgr.list_files("nobody") == []
    assert mgr.total_bytes("nobody") == 0


def test_list_files_reports_entries(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    ws = mgr.resolve("ezri", create=True)
    (ws / "result.txt").write_text("hello", encoding="utf-8")
    (ws / "sub").mkdir()
    (ws / "sub" / "data.json").write_text("{}", encoding="utf-8")
    files = mgr.list_files("ezri")
    names = {f.name for f in files}
    assert "result.txt" in names
    assert "sub" in names
    assert "sub/data.json" in names
    rt = next(f for f in files if f.name == "result.txt")
    assert isinstance(rt, WorkspaceFile)
    assert rt.is_dir is False
    assert rt.size_bytes == 5
    assert mgr.total_bytes("ezri") >= 5


def test_list_files_does_not_recurse_into_venv(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    ws = mgr.resolve("ezri", create=True)
    venv = ws / ".venv" / "lib" / "site-packages"
    venv.mkdir(parents=True)
    (venv / "numpy.py").write_text("x = 1", encoding="utf-8")
    (ws / "script.py").write_text("print(1)", encoding="utf-8")
    files = mgr.list_files("ezri")
    names = {f.name for f in files}
    assert ".venv" in names                       # shown as one opaque entry
    assert not any("site-packages" in n for n in names)  # not recursed
    venv_entry = next(f for f in files if f.name == ".venv")
    assert venv_entry.is_dir is True


def test_list_files_bounded(tmp_path: Path):
    mgr = WorkspaceManager(tmp_path)
    ws = mgr.resolve("ezri", create=True)
    for i in range(50):
        (ws / f"f{i}.txt").write_text("x", encoding="utf-8")
    files = mgr.list_files("ezri", limit=10)
    assert len(files) == 10


# ---------------------------------------------------------------------------
# CodeRunnerAgent — persistent workspace behavior
# ---------------------------------------------------------------------------


def _agent(tmp_path: Path, **exec_kwargs) -> CodeRunnerAgent:
    exec_kwargs.setdefault("scratch_dir", str(tmp_path / "exec"))
    exec_kwargs.setdefault("workspace_root", str(tmp_path / "ws"))
    cfg = ExecutionConfig(**exec_kwargs)
    runtime = SimpleNamespace(config=SimpleNamespace(execution=cfg))
    return CodeRunnerAgent(agent_id="cr-test", runtime=runtime)


async def _call(agent: CodeRunnerAgent, intent: str, **params) -> dict:
    res = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    return {"success": res.success, "data": res.result, "error": res.error}


async def test_run_python_persists_workspace(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    res = await _call(agent, "run_python", code="open('out.txt','w').write('hi')")
    assert res["success"] is True
    ws = Path(res["data"]["workspace"])
    # Persistent: the folder + the file the script wrote survive the run.
    assert ws.is_dir()
    assert (ws / "out.txt").read_text(encoding="utf-8") == "hi"
    assert res["data"]["persistent"] is True
    # Default owner is the code-runner's own key.
    assert res["data"]["owner"] == "code_runner"
    assert ws == tmp_path / "ws" / "code_runner"


async def test_workspace_owner_param_routes_to_named_folder(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    res = await _call(agent, "run_python", code="print('x')", workspace_owner="Ezri")
    assert res["success"] is True
    assert res["data"]["owner"] == "ezri"
    assert Path(res["data"]["workspace"]) == tmp_path / "ws" / "ezri"


async def test_two_owners_get_separate_folders(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    a = await _call(agent, "run_python", code="open('a.txt','w').write('a')", workspace_owner="yeo")
    b = await _call(agent, "run_python", code="open('b.txt','w').write('b')", workspace_owner="ezri")
    yeo, ezri = Path(a["data"]["workspace"]), Path(b["data"]["workspace"])
    assert yeo != ezri
    assert (yeo / "a.txt").exists() and not (yeo / "b.txt").exists()
    assert (ezri / "b.txt").exists() and not (ezri / "a.txt").exists()


async def test_persistent_workspace_reused_across_runs(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    r1 = await _call(agent, "run_python", code="open('keep.txt','w').write('1')", workspace_owner="ezri")
    # Second run in the same owner folder still sees the first run's file.
    r2 = await _call(agent, "run_python", code="print(open('keep.txt').read())", workspace_owner="ezri")
    assert r1["data"]["workspace"] == r2["data"]["workspace"]
    assert r2["success"] is True
    assert "1" in r2["data"]["stdout"]


async def test_ephemeral_mode_reaps(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True, persistent_workspaces=False)
    res = await _call(agent, "run_python", code="print('ok')")
    assert res["success"] is True
    assert res["data"]["persistent"] is False
    # Ephemeral scratch is reaped after the run.
    assert not Path(res["data"]["workspace"]).exists()


async def test_resolve_owner_sanitizes_explicit(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    assert agent._resolve_owner({"workspace_owner": "Ezri Dax!"}) == "ezri_dax"
    assert agent._resolve_owner({}) == "code_runner"
