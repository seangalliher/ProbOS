"""BF-895 (#1548): the rg engine parses every path shape and never reports a false zero."""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

import pytest

from probos.agents import code_search
from probos.agents.code_search import CodeSearchAgent, _parse_rg_line

_RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(_RG is None, reason="ripgrep (rg) is not on PATH")
NUL = "\x00"  # never "\0": "\0" followed by a digit is an octal escape


@pytest.mark.parametrize("path, rest, lineno, text", [
    (r"C:\tmp\f.txt", "3:hello", 3, "hello"),
    (r"c:\Users\a b\x.py", "12:def f(): pass", 12, "def f(): pass"),
    (r"\\?\C:\long\f.txt", "7:x", 7, "x"),
    (r"C:\tmp\f.txt", "3:12:34 text", 3, "12:34 text"),
    (r"C:\tmp\f.txt", "3:", 3, ""),
    (r"C:\tmp\f.txt:7", "1:needle", 1, "needle"),          # NTFS stream named 7 (F1)
    (r"\\server\share\f.txt", "2:y", 2, "y"),
])
def test_windows_lines_parse(path, rest, lineno, text):
    assert _parse_rg_line(path + NUL + rest) == {"path": path, "line": lineno, "text": text}


@pytest.mark.parametrize("path, rest, lineno, text", [
    ("src/main.py", "12:def foo():", 12, "def foo():"),
    ("/tmp/f.txt", "3:hello", 3, "hello"),
    ("a.py", "3:x = {1: 2}", 3, "x = {1: 2}"),
    ("/tmp/f.txt", "3:12:x", 3, "12:x"),
    ("/tmp/a:b.txt", "4:z", 4, "z"),
    ("/tmp/a:12:b.txt", "4:z", 4, "z"),                     # segment holding :<digits>:
    ("a.txt", "3:x" + NUL + "y", 3, "x" + NUL + "y"),      # the FIRST NUL ends the path
])
def test_posix_and_colon_lines_parse(path, rest, lineno, text):
    assert _parse_rg_line(path + NUL + rest) == {"path": path, "line": lineno, "text": text}


@pytest.mark.parametrize("line", [
    "", "garbage", "a.py:3:x",                     # no NUL: the old shape is unparsed
    NUL + "3:x",                                   # empty path
    "a.py" + NUL + "notnum:text",
    "a.py" + NUL + "3",                            # no ':' after the line number
    "a.py" + NUL + ":x",                           # empty line number
    "a.py" + NUL + "+3:x",                         # int() would accept the sign
    "a.py" + NUL + "\u0663:x",                     # non-ASCII digit int() would accept
])
def test_malformed_lines_are_dropped(line):
    assert _parse_rg_line(line) is None


def test_oversized_line_number_is_unparsed_not_an_exception():
    field = "1" + "9" * 5000 + "12"
    with pytest.raises(ValueError):  # premise: int() refuses it here, or this test proves nothing
        int(field)
    assert _parse_rg_line("a.py" + NUL + field + ":x") is None


def test_text_is_truncated_to_preview():
    parsed = _parse_rg_line("p.txt" + NUL + "1:" + "x" * 400)
    assert parsed is not None and len(parsed["text"]) == 300


class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


def _fake_rg(monkeypatch, returncode: int, stdout: bytes) -> list:
    seen: list = []

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return _FakeProc(returncode, stdout)

    monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg")
    return seen


async def _run(root: Path, pattern: str) -> dict:
    agent = CodeSearchAgent(agent_id="bf895")
    plan = await agent.decide({"params": {"path": str(root), "pattern": pattern}})
    return await agent.act(plan)


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\nhello world\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("returncode, stdout", [
    (0, b"this is not an rg match line\n"),
    (0, b""),
    (0, b"C:\\x\\a.txt:2:hello world\n"),          # the pre---null shape is unparsed
    (1, b"stray output\n"),
    (1, b"\n"),                                    # whitespace-only output (F3)
])
async def test_unparsed_rg_output_falls_back_to_python(tmp_path, monkeypatch, returncode, stdout):
    seen = _fake_rg(monkeypatch, returncode, stdout)
    result = await _run(_tree(tmp_path), "hello")
    assert seen, "the fake rg was not launched"
    assert "--with-filename" in seen[0]
    assert "--null" in seen[0]
    assert result["engine"] == "python"
    assert result["success"] and result["count"] == 1


async def test_empty_rg_result_stays_a_zero_success(tmp_path, monkeypatch):
    _fake_rg(monkeypatch, 1, b"")
    result = await _run(_tree(tmp_path), "absent")
    assert result == {"success": True, "data": [], "count": 0, "engine": "rg", "truncated": False}


async def test_fallback_warning_names_exit_bytes_and_root_but_not_match_text(tmp_path, monkeypatch, caplog):
    unparsed = b"api_key = hunter2 is not an rg line\n"
    _fake_rg(monkeypatch, 0, unparsed)
    with caplog.at_level(logging.WARNING, logger=code_search.logger.name):
        await _run(_tree(tmp_path), "hello")
    messages = [r.getMessage() for r in caplog.records if "BF-895" in r.getMessage()]
    assert len(messages) == 1
    assert "exited 0" in messages[0]
    assert f"{len(unparsed)} output bytes" in messages[0]
    assert tmp_path.name in messages[0]
    assert "hunter2" not in messages[0]


async def test_parsed_drive_letter_output_is_reported_by_rg(tmp_path, monkeypatch):
    _fake_rg(monkeypatch, 0, b"C:\\x\\a.txt\x002:hello world\r\n")
    result = await _run(_tree(tmp_path), "hello")
    assert result["engine"] == "rg"
    assert result["data"] == [{"path": r"C:\x\a.txt", "line": 2, "text": "hello world"}]


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


@needs_rg
@pytest.mark.parametrize("file_root", [False, True])
async def test_real_rg_matches_python_engine(tmp_path, file_root):
    root = _tree(tmp_path)
    (root / "b.txt").write_text("hello again\n12:hello in text\nnope\n", encoding="utf-8")
    target = root / "a.txt" if file_root else root
    agent = CodeSearchAgent(agent_id="bf895")
    plan = await agent.decide({"params": {"path": str(target), "pattern": "hello"}})
    via_rg = await agent._search_rg(_RG, plan, target)
    via_py = agent._search_python(plan, target)
    assert via_rg is not None and via_rg["engine"] == "rg"
    assert via_rg["count"] == via_py["count"] > 0
    assert sorted((_norm(m["path"]), m["line"]) for m in via_rg["data"]) == \
        sorted((_norm(m["path"]), m["line"]) for m in via_py["data"])


@needs_rg
@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
async def test_real_rg_reads_a_numeric_stream_file_root(tmp_path):
    (tmp_path / "f.txt").write_text("base\n", encoding="utf-8")
    stream = Path(str(tmp_path / "f.txt") + ":7")
    try:
        stream.write_text("needle\n", encoding="utf-8")
    except OSError:
        pytest.skip("the temp filesystem does not support alternate data streams")
    agent = CodeSearchAgent(agent_id="bf895")
    plan = await agent.decide({"params": {"path": str(stream), "pattern": "needle"}})
    via_rg = await agent._search_rg(_RG, plan, stream)
    via_py = agent._search_python(plan, stream)
    assert via_rg is not None and via_rg["engine"] == "rg"
    assert [(_norm(m["path"]), m["line"], m["text"]) for m in via_rg["data"]] == \
        [(_norm(m["path"]), m["line"], m["text"]) for m in via_py["data"]] == \
        [(_norm(str(stream)), 1, "needle")]


@needs_rg
async def test_oversized_line_number_field_from_rg_config_falls_back(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.txt").write_text("12:hello\n", encoding="utf-8")
    config = tmp_path / "ripgreprc"
    config.write_text("--field-match-separator=" + "9" * 5000 + "\n", encoding="utf-8")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(config))
    result = await _run(root, "hello")
    assert result["success"] and result["engine"] == "python" and result["count"] == 1
