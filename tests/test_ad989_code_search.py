"""AD-989: CodeSearchAgent (search_content) tests.

BF-287: real agent + real tmp_path tree, no mocks at the substrate boundary. The
``rg`` engine is non-deterministic across machines (may or may not be installed),
so we force the pure-Python engine by monkeypatching ``shutil.which`` -> None;
the rg path has its own thin parse test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.agents.code_search import CodeSearchAgent, _parse_rg_line
from probos.types import IntentMessage


@pytest.fixture(autouse=True)
def _force_python_engine(monkeypatch):
    # Deterministic: no rg on PATH, no tools/rg -> Python engine every time.
    monkeypatch.setattr("probos.agents.code_search.shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "probos.agents.code_search._resolve_rg_binary", lambda: None,
    )


def _project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def recall_for_agent(self):\n    return TODO\n", encoding="utf-8"
    )
    (tmp_path / "src" / "util.py").write_text(
        "X = 1\nclass Helper:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text("# recall_for_agent docs\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("def recall_for_agent(): pass\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00recall_for_agent\x00")
    return tmp_path


async def _search(root: Path, pattern: str, **params) -> dict:
    agent = CodeSearchAgent(agent_id="cs-test")
    msg = IntentMessage(
        intent="search_content",
        params={"path": str(root), "pattern": pattern, **params},
    )
    res = await agent.handle_intent(msg)
    return {"success": res.success, "data": res.result, "error": res.error}


# ---------------------------------------------------------------------------
# core matching
# ---------------------------------------------------------------------------


async def test_literal_match_returns_path_line_text(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "recall_for_agent")
    assert res["success"]
    hits = res["data"]
    main = next(h for h in hits if h["path"].endswith("main.py"))
    assert main["line"] == 1
    assert "recall_for_agent" in main["text"]


async def test_regex_match(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, r"def \w+")
    assert res["success"]
    assert any("recall_for_agent" in h["text"] for h in res["data"])


async def test_case_insensitive(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "RECALL_FOR_AGENT", case_insensitive=True)
    assert res["success"]
    assert len(res["data"]) >= 1


async def test_glob_filter_limits_to_py(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "recall_for_agent", glob="*.py")
    assert res["success"]
    assert all(h["path"].endswith(".py") for h in res["data"])
    assert not any(h["path"].endswith(".md") for h in res["data"])


# ---------------------------------------------------------------------------
# automatic filtering (AD-990 integration)
# ---------------------------------------------------------------------------


async def test_respects_ignores_by_default(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "recall_for_agent")
    assert res["success"]
    assert not any(".venv" in h["path"] for h in res["data"])  # headline


async def test_include_ignored_searches_venv(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "recall_for_agent", include_ignored=True)
    assert res["success"]
    assert any(".venv" in h["path"] for h in res["data"])


async def test_binary_file_skipped(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, "recall_for_agent")
    assert res["success"]
    assert not any(h["path"].endswith(".bin") for h in res["data"])


# ---------------------------------------------------------------------------
# bounds + safety
# ---------------------------------------------------------------------------


async def test_max_results_truncates(tmp_path: Path):
    d = tmp_path / "many"
    d.mkdir()
    for i in range(10):
        (d / f"f{i}.py").write_text("hit\nhit\n", encoding="utf-8")
    agent = CodeSearchAgent(agent_id="cs-trunc")
    msg = IntentMessage(
        intent="search_content",
        params={"path": str(tmp_path), "pattern": "hit", "max_results": 3},
    )
    res = await agent.handle_intent(msg)
    assert res.success
    assert len(res.result) == 3


async def test_catastrophic_pattern_rejected_no_hang(tmp_path: Path):
    root = _project(tmp_path)
    res = await _search(root, r"(a+)+$")
    assert res["success"] is False
    assert "Unsafe pattern" in res["error"]


async def test_missing_path_errors(tmp_path: Path):
    res = await _search(tmp_path / "nope", "x")
    assert res["success"] is False
    assert "not found" in res["error"].lower()


async def test_missing_pattern_errors(tmp_path: Path):
    agent = CodeSearchAgent(agent_id="cs-nop")
    msg = IntentMessage(intent="search_content", params={"path": str(tmp_path)})
    res = await agent.handle_intent(msg)
    assert res.success is False


# ---------------------------------------------------------------------------
# descriptor + rg-line parser
# ---------------------------------------------------------------------------


def test_intent_descriptor_exposes_search_content():
    descs = CodeSearchAgent.intent_descriptors
    d = next(x for x in descs if x.name == "search_content")
    assert "[MESH search_content" in d.usage_hint


def test_parse_rg_line():
    assert _parse_rg_line("src/main.py:12:def foo():") == {
        "path": "src/main.py", "line": 12, "text": "def foo():"
    }
    # text may contain colons
    assert _parse_rg_line("a.py:3:x = {1: 2}")["text"] == "x = {1: 2}"
    assert _parse_rg_line("garbage") is None
    assert _parse_rg_line("a.py:notnum:text") is None
