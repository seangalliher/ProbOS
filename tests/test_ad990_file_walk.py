"""AD-990: gitignore-aware file traversal tests (BF-287 — real tmp_path tree)."""
from __future__ import annotations

from pathlib import Path

from probos.agents.file_search import FileSearchAgent
from probos.substrate.file_walk import (
    DEFAULT_IGNORE_DIRS,
    IgnoreSpec,
    is_binary,
    iter_files,
    load_ignore_spec,
)


def _tree(tmp_path: Path) -> Path:
    """A realistic project tree with junk + real source + a .gitignore."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "src" / "util.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "junk.py").write_text("noise\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("x\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython.pyc").write_text("c\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.txt").write_text("built\n", encoding="utf-8")
    (tmp_path / "app.log").write_text("log line\n", encoding="utf-8")
    (tmp_path / "keep.log").write_text("keep me\n", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / ".gitignore").write_text(
        "# comment\n\n*.log\n!keep.log\nbuild/\n", encoding="utf-8"
    )
    return tmp_path


def _names(root: Path) -> set[str]:
    return {f.relative_to(root).as_posix() for f in iter_files(root)}


# ---------------------------------------------------------------------------
# default-ignore dirs
# ---------------------------------------------------------------------------


def test_prunes_default_ignore_dirs(tmp_path: Path):
    root = _tree(tmp_path)
    got = _names(root)
    assert "src/main.py" in got
    assert "src/util.py" in got
    # .venv / node_modules / __pycache__ never descended.
    assert not any(p.startswith(".venv/") for p in got)
    assert not any(p.startswith("node_modules/") for p in got)
    assert not any(p.startswith("__pycache__/") for p in got)


def test_default_ignore_set_has_the_usual_suspects():
    for d in (".git", ".venv", "node_modules", "__pycache__", "data"):
        assert d in DEFAULT_IGNORE_DIRS


# ---------------------------------------------------------------------------
# .gitignore patterns + negation
# ---------------------------------------------------------------------------


def test_gitignore_glob_and_dir_excluded(tmp_path: Path):
    root = _tree(tmp_path)
    got = _names(root)
    assert "app.log" not in got        # *.log
    assert "build/out.txt" not in got  # build/
    assert "src/main.py" in got


def test_gitignore_negation_reincludes(tmp_path: Path):
    root = _tree(tmp_path)
    got = _names(root)
    assert "keep.log" in got           # !keep.log overrides *.log


def test_ignorespec_matches_semantics():
    spec = IgnoreSpec.from_lines(["*.log", "!keep.log", "build/", "/root.txt"])
    assert spec.matches("a/b/c.log", is_dir=False) is True
    assert spec.matches("keep.log", is_dir=False) is False
    # A dir-only rule ("build/") matches the DIRECTORY; iter_files then prunes it
    # so files beneath it are never even checked (see test_gitignore_glob_and_dir
    # _excluded for the end-to-end effect). A dir-only rule does NOT match a file.
    assert spec.matches("build", is_dir=True) is True
    assert spec.matches("build", is_dir=False) is False
    assert spec.matches("root.txt", is_dir=False) is True  # anchored
    assert spec.matches("sub/root.txt", is_dir=False) is False  # anchored != deep


def test_load_ignore_spec_missing_is_empty(tmp_path: Path):
    spec = load_ignore_spec(tmp_path)  # no .gitignore
    assert spec.matches("anything.py", is_dir=False) is False


# ---------------------------------------------------------------------------
# hidden + binary
# ---------------------------------------------------------------------------


def test_hidden_skipped_unless_requested(tmp_path: Path):
    root = _tree(tmp_path)
    assert ".hidden" not in _names(root)
    incl = {f.relative_to(root).as_posix() for f in iter_files(root, include_hidden=True)}
    assert ".hidden" in incl


def test_binary_skipped_unless_requested(tmp_path: Path):
    root = _tree(tmp_path)
    assert "blob.bin" not in _names(root)
    incl = {f.relative_to(root).as_posix() for f in iter_files(root, skip_binary=False)}
    assert "blob.bin" in incl


def test_is_binary_detects_nul(tmp_path: Path):
    b = tmp_path / "x.bin"
    b.write_bytes(b"\x00\xff")
    assert is_binary(b) is True
    t = tmp_path / "x.txt"
    t.write_text("hello\n", encoding="utf-8")
    assert is_binary(t) is False


# ---------------------------------------------------------------------------
# max_files bound
# ---------------------------------------------------------------------------


def test_max_files_bound(tmp_path: Path):
    d = tmp_path / "many"
    d.mkdir()
    for i in range(10):
        (d / f"f{i}.txt").write_text("x\n", encoding="utf-8")
    got = list(iter_files(tmp_path, max_files=4))
    assert len(got) == 4


def test_non_directory_root_yields_nothing(tmp_path: Path):
    f = tmp_path / "solo.txt"
    f.write_text("x\n", encoding="utf-8")
    assert list(iter_files(f)) == []


# ---------------------------------------------------------------------------
# FileSearchAgent integration (AD-990 behavior change)
# ---------------------------------------------------------------------------


async def test_file_search_excludes_ignored_by_default(tmp_path: Path):
    root = _tree(tmp_path)
    agent = FileSearchAgent(agent_id="fs-1")
    res = await agent._search_files(str(root), "*.py")
    assert res["success"]
    rels = {Path(m).relative_to(root).as_posix() for m in res["data"]}
    assert "src/main.py" in rels
    assert not any(".venv" in m for m in res["data"])  # the headline fix


async def test_file_search_include_ignored_escape_hatch(tmp_path: Path):
    root = _tree(tmp_path)
    agent = FileSearchAgent(agent_id="fs-2")
    res = await agent._search_files(str(root), "*.py", include_ignored=True)
    assert res["success"]
    # The raw rglob escape hatch DOES descend .venv.
    assert any(".venv" in m for m in res["data"])
