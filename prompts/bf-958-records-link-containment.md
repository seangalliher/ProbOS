# BF-958 (#1761): Ship's Records listing and search descend no directory junction and read no file that resolves outside the repository

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-06
**Status:** ready to build on top of BF-957 in the same branch (one broad gate, one PR).
**Base:** the BF-957 head. Anchors were taken on the oracle `D:\ProbOS-worktrees\bf957-o3`: a detached checkout of `11325587` (the AD-1358 candidate) with every BF-957 pair applied. Its `records_store.py` is blob `e3de25db001c75d60ecafcf348f9938180b08f6f` per the orchestrator; the bridge did not let me hash it.
**Dependencies:** BF-957 M2 (same file).
**Orchestrator note (2026-11-07, before building):** BF-957 was amended through A7 after this contract was drafted, so check 1 below (the blob) and check 2 (the commit) describe BF-957's M2-era head. The pairs were applied by tool on BF-957's final head `d1e151db` instead (`records_store.py` is blob `132d8964ee7149faa7cdcda0834d7bb243718f21` there): all 21 pairs (13 + 6 + 2, and the new file) applied with every SEARCH matching exactly once, so the hard stop named below did not occur.
**Tier:**
- M1 STANDARD (tests only).
- M2 HIGH (a containment control in a security path).
- M3 STANDARD.

**Estimated tests:** one new file, `tests/test_bf958_records_link_containment.py`, with 9 functions and 26 cases. Two existing test files are edited, with no change to their case counts. Counted by reading, not by running.
**BF number:** BF-958, held by #1761. Nothing new is allocated.

**Which text describes the head.** Before building, `<BF-957 M2 commit>` means BF-957's last commit that touches `records_store.py`: M2, or a later review repair. Run these checks:
1. `git rev-parse <BF-957 M2 commit>:src/probos/knowledge/records_store.py` should print `e3de25db001c75d60ecafcf348f9938180b08f6f`.
2. `git diff --stat <BF-957 M2 commit> HEAD -- src/probos/knowledge/records_store.py src/probos/recreation/history.py tests/test_ad1341_s4_lessons.py tests/test_bf952_records_keyword_search.py` must be empty.
3. `git diff --stat 11325587 <BF-957 M2 commit> -- src/probos/recreation/history.py tests/test_ad1341_s4_lessons.py tests/test_bf952_records_keyword_search.py` must be empty. If `11325587` is not in the history (AD-1358 was squash-merged), skip this check.
4. `tests/test_bf958_records_link_containment.py` must not exist.

If the blob differs, every SEARCH below must still occur exactly once; otherwise this is a hard stop and goes back to the Architect. Working copies are CRLF and SEARCH text here is LF. Where prose and a block differ, the block wins.

**Where the edits fall (oracle line numbers).**

| Pair | Region | BF-957 regions (untouched) |
|---|---|---|
| P2-1 | `records_store.py:403-418` (`_search_records`) | `:10` (import), `:23-38` (constants, `_git_error_line`), `:540-544` (`__init__`), `:1642` to the end of `_commit` (git methods, logging) |
| P2-2 | `:490-525` (strict walk) | as above |
| P2-3 | `:1355-1374` (`list_entries`) | as above |
| P2-4 | `:931` (`list_bills` docstring) | as above |

None of these overlaps a BF-957 region. The nearest gap is 15 lines (`:525` to `:540`).

## 1. Problem

1. **The strict walk descends a junction.** `_markdown_files_or_raise` (`records_store.py:490-525`) descends every entry for which `entry.is_dir(follow_symlinks=False)` is true (`:521`). On Windows that is true for a directory junction, for which `is_symlink()` is false. The orchestrator's probe `probe_store_junction.py` measured this; I did not rerun it.
   - Its docstring (`:502-503`) says "a symbolic link is not descended". That does not cover a junction.
2. **The default walk and the search use `rglob("*.md")`** (`:1365`, `:410`). In CPython 3.12.13, `rglob` walks with `Path.walk(follow_symlinks=False)` (`pathlib.py:228-232`, `:1112-1155`), which also descends a junction. It ignores an `OSError` raised when opening a directory (`:1128-1133`).
3. **Only the top path and `read_entry`'s argument are contained.** `_safe_path` (`:1610-1621`) resolves the path and requires `is_relative_to` the resolved repository; otherwise it raises `ValueError("Path traversal denied")`. Nothing checks a file the walk reaches. A `*.md` file link is read by `read_text` in both readers (`:1373`, `:415`).
4. **Effect.** A listing returns an outside file's frontmatter, and a search returns its frontmatter plus a 200-character snippet (`:473`). Whether a reader sees it depends on that file's own frontmatter (`record_is_readable` `:106`, `_base_reading_admits` `:341`).
5. **A cycle.** A junction cycle ends the strict walk with `OSError` [WinError 1921] after about 60 levels (`probe_cycle.py`). The default walk and the search return the record once per level.
6. **Readers that list and then read fail on such a layout today** (found by reading, not measured):
   - `exit_note_citations` (`archive_promotion.py:315`) and `plan_promotion` (`:372`) pass each listed path to `read_entry`, which raises `ValueError` for the outside one. The first means `/forget`; the second, `probos reset`'s plan.

## 2. Solution

- **One walk.** `_markdown_files(search_path, *, strict)` serves the strict listing, the default listing and the search.
  - It never descends `entry.is_junction()` (new row OJ) and logs a WARNING naming the path.
  - In strict mode it keeps the AD-1341 S4 rows O1–O4 exactly.
  - In default mode it ignores what `rglob`'s walk ignored: a directory it cannot open is passed over, and an entry whose type cannot be read is taken for no directory. An `OSError` during a listing step still raises, as it did in `rglob`.
- **A containment check per file.** `_resolves_inside(path, repo)` applies `_safe_path`'s rule to each file the walk returns. `list_entries` and `_search_records` call it before `read_text`. A file outside, or a link loop, is skipped with a WARNING in both modes and raises in neither.

## 3. Decisions

Decisions D1–D7 are in the tables above this contract.

**Amendment to #1761's acceptance, line 3.** It said "A junction cycle still ends the strict walk with OSError". It becomes: "a junction cycle ends the walk without descending it: each record once, a WARNING naming the junction, no `OSError`". I wrote the original line; this amendment is within the delegated scope.

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-5, then N2-1 to N2-8, then N2-9 to N2-14 (removing the markers) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0.** On the head, record the collected count (`--collect-only -q`) of every existing file named in G2. The bridge does not allow pytest, so I could not.
- **G1.** `PY -m pytest tests/test_bf958_records_link_containment.py -q -n 0 -p no:randomly`.
  - **Expected on the Windows gate host, which cannot create a file symlink:** **3 passed** (T5, T6, T7), **17 xfailed** (T1 ×4, T2 ×6, T4 ×3, T8 ×4), **6 skipped** (T3a ×3, T3b ×3, a host precondition).
  - **On POSIX:** 13 passed, 13 xfailed.
  - The markers carry `raises=AssertionError, strict=True`, so any other exception, or an XPASS, is a FAIL.
  - Any other count is a hard stop.
- **G2.**
  1. `PY -m pytest tests/test_bf958_records_link_containment.py tests/test_records_store.py tests/test_bf949_notebook_reader_identity.py tests/test_bf952_records_keyword_search.py tests/test_ad1341_s4_lessons.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s1_promotion.py tests/test_ad1341_s6_records_snapshot.py tests/test_ad1358_s1_head_to_head.py tests/test_bf084_truncation_and_manuals.py tests/test_bf957_records_git_signal.py -q -n 0 -p no:randomly`
  2. `PY -P scripts/check_architecture_principles.py --check`
  - **Expected:** the new file gives **20 passed, 6 skipped** (Windows host, no file-symlink privilege) or 26 passed (POSIX). Every other file: 0 failed, and collected counts equal M0.
- **G3.**
  1. `PY -P scripts/gen_ad_ledger.py`
  2. `PY -P scripts/gen_ad_ledger.py --check`
  3. `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`
- **Harness rule.** No source change made to pass a test, no skip other than T3's precondition, and no loosened assertion. Any of these goes back to the Architect.
- The broad gate runs once for the BF-957 + BF-958 batch, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-958 M1: tests for Ship's Records listing and search following no link out of the repository, xfail until built`
- **M2:** `BF-958 M2: Ship's Records listing and search descend no directory junction and skip a file that resolves outside the repository`
- **M3:** `BF-958 M3: trackers and ledger`

## 6. Tests (`tests/test_bf958_records_link_containment.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_a_directory_link_out_of_the_repository_is_not_listed_or_searched` | 4 | **Seam:** a real link, reached through the public API, gives the result and the WARNING, and agrees with `read_entry` | M2 (Windows) |
| T2 | `test_a_listed_file_that_resolves_outside_is_skipped_with_a_warning` | 6 | The per-file check on every platform (outside, loop) | M2 |
| T3a | `test_a_markdown_link_to_a_file_outside_is_skipped_with_a_warning` | 3 | A real `*.md` link out | M2 |
| T3b | `test_a_markdown_link_to_a_file_inside_is_listed_as_read_entry_reads_it` | 3 | Guard: an inside link is admitted, as `read_entry` admits it | none |
| T4 | `test_a_directory_link_cycle_is_not_descended_and_the_walk_ends` | 3 | A cycle: no `OSError`, the record once, the walk ends | M2 (Windows) |
| T5 | `test_an_ordinary_nested_directory_is_still_listed_and_searched` | 1 | Guard | none |
| T6 | `test_a_records_root_that_is_itself_a_link_is_still_listed_and_searched` | 1 | Guard: the check compares resolved paths | none |
| T7 | `test_the_default_listing_and_search_pass_over_a_directory_they_cannot_list` | 1 | Guard: default mode ignores what `rglob` ignored; strict raises | none |
| T8 | `test_the_default_walk_raises_only_a_failed_listing_step` | 4 | The fault matrix for default mode | M2 |

**How each xfail case fails on the base.** Each fails at an `AssertionError`:
- T1, T3a and T4 fail at `found == [_NOTE]`; T4 turns the base's strict `OSError` into an `AssertionError`.
- T2 fails at `found == [_NOTE]`.
- T8 fails at `_walk()`'s `assert`.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf958_records_link_containment.py`:

```python
"""BF-958 (#1761): Ship's Records listing and search descend no directory junction, and read no listed file that
resolves outside the records repository.

Real ``RecordsStore`` objects on real directories in ``tmp_path``; no git. A directory link is a junction on Windows
(``_winapi.CreateJunction``, no privilege) and a symbolic link elsewhere, as AD-1200's ``_junction`` makes one. Each
link is removed in a ``finally``: the link alone, never its target.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

import probos.knowledge.records_store as records_store_module
from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore
from tests.test_ad1341_s4_lessons import _WALK_FAULTS, _Trace, _TracedListing, _walk_tree

_LOGGER = "probos.knowledge.records_store"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-958 M2 builds it")
_BUILT_ON_WINDOWS = pytest.mark.xfail(
    os.name == "nt", raises=AssertionError, strict=True,
    reason="BF-958 M2 builds it; elsewhere the base already passes over a directory symbolic link",
)
_MODES = ["list-strict", "list-default", "search"]
_NOTE = "notebooks/alice/note.md"


def _write(path: Path, author: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nauthor: {author}\nclassification: ship\n---\n\n{body}\n", encoding="utf-8")


def _store(tmp_path: Path) -> tuple[RecordsStore, Path]:
    repo = tmp_path / "ship-records"
    _write(repo / _NOTE, "Alice", "A quasar seen from the bridge.")
    return RecordsStore(RecordsConfig(repo_path=str(repo))), repo


async def _paths(store: RecordsStore, mode: str, directory: str = "") -> list[str]:
    if mode == "search":
        return sorted(r["path"] for r in await store.search("quasar", reader_id="captain", directory=directory))
    return sorted(e["path"] for e in await store.list_entries(directory, strict=mode == "list-strict"))


def _directory_link(link: Path, target: Path) -> None:
    """A directory link, as AD-1200's ``_junction``: a junction on Windows (no privilege), else a symbolic link."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)
        assert link.is_symlink()


def _remove_directory_link(link: Path) -> None:
    """Remove the link alone, never its target: ``rmdir`` of a junction on Windows, ``unlink`` of a symlink."""
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


def _file_link(link: Path, target: Path) -> None:
    """A ``*.md`` symbolic link to a file. Windows grants one only with a privilege or Developer Mode; a host without
    it cannot make the layout, which is this test's platform precondition, not a failure."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"this host cannot create a file symbolic link: {exc}")


def _bf958_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.name == _LOGGER and r.levelno == logging.WARNING and "BF-958" in r.getMessage()
    ]


def _resolve_away(monkeypatch: pytest.MonkeyPatch, victim: Path, outside: Path | None) -> None:
    """``Path.resolve`` of ``victim`` answers ``outside``, as for a link that leads there, or raises ``RuntimeError``
    as ``Path.resolve`` does for a link loop when ``outside`` is None. Every other path resolves as it does. This
    reaches the per-file check on every platform, with no host privilege."""
    real_resolve = Path.resolve
    target = real_resolve(victim)

    def resolve(self: Path, *args: Any, **kwargs: Any) -> Path:
        resolved = real_resolve(self, *args, **kwargs)
        if resolved != target:
            return resolved
        if outside is None:
            raise RuntimeError(f"Symlink loop from {str(self)!r}")
        return outside

    monkeypatch.setattr(Path, "resolve", resolve)


def _count_listings(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count every ``os.scandir``; the 2,000th raises, so a walk that does not end fails instead of hanging."""
    real_scandir = os.scandir
    calls = {"n": 0}

    def scandir(path: Any = ".") -> Any:
        calls["n"] += 1
        if calls["n"] >= 2000:
            raise AssertionError("the walk does not end")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    return calls


def _walk() -> Any:
    walk = getattr(records_store_module, "_markdown_files", None)
    assert walk is not None, "BF-958: the shared walk _markdown_files is not built"
    return walk


def _traced_default_walk(root: Path, trace: Any) -> list[Path]:
    """The default walk with every ``os.scandir`` traced (AD-1341 S4's tracer) and a tripwire on every other call."""
    walk = _walk()
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> Any:
        where = os.fspath(path)
        trace.tick("open-root" if Path(where) == root else "open-subdirectory", where)
        return _TracedListing(real_scandir(path), trace, where)

    def tripwire(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the default walk made a filesystem call its table has no row for")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "scandir", scandir)
        for name in ("stat", "lstat", "listdir", "walk"):
            patch.setattr(os, name, tripwire)
        return walk(root, strict=False)


@pytest.mark.parametrize(("mode", "directory"), [
    pytest.param("list-strict", "", id="strict"),
    pytest.param("list-default", "", id="default"),
    pytest.param("list-strict", "notebooks", id="strict-directory"),
    pytest.param("search", "", id="search"),
])
@_BUILT_ON_WINDOWS
async def test_a_directory_link_out_of_the_repository_is_not_listed_or_searched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: str, directory: str,
) -> None:
    """The issue's probe: a directory link below a listed directory leads to ``outside/secret.md``, a ship-classified
    record holding the searched word. ``read_entry`` refuses that path; the listings and the search return only the
    record inside, and on Windows a WARNING names the junction they did not descend."""
    store, repo = _store(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / "secret.md", "outsider", "A quasar seen from outside.")
    link = repo / "notebooks" / "alice" / "escape"
    _directory_link(link, outside)
    try:
        with pytest.raises(ValueError, match="Path traversal denied"):  # premise: read_entry's rule refuses it
            await store.read_entry("notebooks/alice/escape/secret.md", reader_id="captain")
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        found = await _paths(store, mode, directory)
    finally:
        _remove_directory_link(link)
    assert (outside / "secret.md").is_file()  # the link alone was removed
    assert found == [_NOTE]
    if os.name == "nt":
        assert any("did not descend" in m and "escape" in m for m in _bf958_warnings(caplog)), caplog.text


@pytest.mark.parametrize("kind", ["outside", "loop"])
@pytest.mark.parametrize("mode", _MODES)
@_BUILT
async def test_a_listed_file_that_resolves_outside_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str, kind: str,
) -> None:
    """A listed ``*.md`` that resolves outside the repository, or into a link loop, is not read: the listing (strict
    or not) and the search skip it with a WARNING naming it, and still return the record inside."""
    store, repo = _store(tmp_path)
    victim = repo / "notebooks" / "alice" / "escape.md"
    _write(victim, "outsider", "A quasar seen from outside.")
    _resolve_away(monkeypatch, victim, tmp_path / "outside" / "secret.md" if kind == "outside" else None)
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    found = await _paths(store, mode)
    assert found == [_NOTE]
    assert any("skipped" in m and "notebooks/alice/escape.md" in m for m in _bf958_warnings(caplog)), caplog.text


@pytest.mark.parametrize("mode", _MODES)
@_BUILT
async def test_a_markdown_link_to_a_file_outside_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: str,
) -> None:
    store, repo = _store(tmp_path)
    outside = tmp_path / "outside" / "secret.md"
    _write(outside, "outsider", "A quasar seen from outside.")
    link = repo / "notebooks" / "alice" / "escape.md"
    _file_link(link, outside)
    try:
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        found = await _paths(store, mode)
    finally:
        link.unlink()
    assert outside.is_file()  # the link alone was removed
    assert found == [_NOTE]
    assert any("skipped" in m and "notebooks/alice/escape.md" in m for m in _bf958_warnings(caplog)), caplog.text


@pytest.mark.parametrize("mode", _MODES)
async def test_a_markdown_link_to_a_file_inside_is_listed_as_read_entry_reads_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, mode: str,
) -> None:
    store, repo = _store(tmp_path)
    target = repo / "notebooks" / "bob" / "real.md"
    _write(target, "Bob", "A quasar seen by Bob.")
    link = repo / "notebooks" / "alice" / "alias.md"
    _file_link(link, target)
    try:
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        found = await _paths(store, mode)
        read = await store.read_entry("notebooks/alice/alias.md", reader_id="captain")
    finally:
        link.unlink()
    assert found == sorted([_NOTE, "notebooks/alice/alias.md", "notebooks/bob/real.md"])
    assert read is not None and "Bob" in read["content"]
    assert not _bf958_warnings(caplog)


@pytest.mark.parametrize("mode", _MODES)
@_BUILT_ON_WINDOWS
async def test_a_directory_link_cycle_is_not_descended_and_the_walk_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str,
) -> None:
    """A directory link to its own parent. On the base, Windows descended the junction until the OS refused the path
    (the strict walk raised ``OSError``, WinError 1921, after about 60 levels; the default walk and the search
    returned the record once per level). Now the walk passes over it: the record once, a WARNING on Windows, no
    ``OSError``. Elsewhere the base already passed over the symbolic link."""
    store, repo = _store(tmp_path)
    loop = repo / "notebooks" / "alice" / "loop"
    _directory_link(loop, loop.parent)
    try:
        calls = _count_listings(monkeypatch)
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        try:
            found = await _paths(store, mode)
        except OSError as exc:
            raise AssertionError(f"the walk raised {exc!r} instead of passing over the link") from exc
    finally:
        _remove_directory_link(loop)
    assert calls["n"] < 2000
    assert found == [_NOTE]
    if os.name == "nt":
        assert any("did not descend" in m and "loop" in m for m in _bf958_warnings(caplog)), caplog.text


async def test_an_ordinary_nested_directory_is_still_listed_and_searched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    store, repo = _store(tmp_path)
    _write(repo / "reports" / "a" / "b" / "c" / "deep.md", "Alice", "A quasar three levels down.")
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    for mode in _MODES:
        assert await _paths(store, mode) == [_NOTE, "reports/a/b/c/deep.md"], mode
    assert await _paths(store, "list-strict", "reports") == ["reports/a/b/c/deep.md"]
    assert await _paths(store, "search", "reports") == ["reports/a/b/c/deep.md"]
    assert not _bf958_warnings(caplog)


async def test_a_records_root_that_is_itself_a_link_is_still_listed_and_searched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """The repository's own path may be a link (a relocated data directory). The rule compares resolved paths, so
    every record under it is inside: nothing is skipped and nothing is logged."""
    real_root = tmp_path / "relocated"
    _write(real_root / _NOTE, "Alice", "A quasar seen from the bridge.")
    link = tmp_path / "ship-records"
    _directory_link(link, real_root)
    try:
        store = RecordsStore(RecordsConfig(repo_path=str(link)))
        assert store.repo_path != store.repo_path.resolve()  # premise: the configured path is the link
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        found = {mode: await _paths(store, mode) for mode in _MODES}
        found["strict-directory"] = await _paths(store, "list-strict", "notebooks")
    finally:
        _remove_directory_link(link)
    assert (real_root / _NOTE).is_file()
    assert found == dict.fromkeys(found, [_NOTE])
    assert not _bf958_warnings(caplog)


async def test_the_default_listing_and_search_pass_over_a_directory_they_cannot_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``rglob`` passed over a directory it could not open; the default walk still does. The strict listing raises."""
    store, repo = _store(tmp_path)
    _write(repo / "notebooks" / "bob" / "hidden.md", "Bob", "A quasar behind a locked door.")
    denied = (repo / "notebooks" / "bob").resolve()
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> Any:
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == denied:
            raise PermissionError(13, "the directory is being used by another process", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    assert await _paths(store, "list-default") == [_NOTE]
    assert await _paths(store, "search") == [_NOTE]
    with pytest.raises(PermissionError):
        await store.list_entries(strict=True)


@pytest.mark.parametrize("kind", sorted(_WALK_FAULTS))
@_BUILT
def test_the_default_walk_raises_only_a_failed_listing_step(tmp_path: Path, kind: str) -> None:
    """AD-1341 S4's trace-and-fault matrix, for the default walk: each operation of a clean walk fails once with
    ``kind``. Only a failed listing step (``next``) raises, as in ``rglob``'s walk; a directory that cannot be opened is
    passed over, and an entry whose type cannot be read is taken for no directory."""
    root = tmp_path / "records"
    _walk_tree(root)
    clean = _Trace()
    found = sorted(_traced_default_walk(root, clean))
    assert found == sorted(path for path in root.rglob("*.md") if path.is_file())
    assert set(clean.operations) == {"open-root", "open-subdirectory", "next", "is_junction", "is_dir"}
    for fail_at, operation in enumerate(clean.operations, start=1):
        trace = _Trace(fail_at, _WALK_FAULTS[kind])
        try:
            outcome: Any = sorted(_traced_default_walk(root, trace))
        except OSError as exc:
            outcome = type(exc)
        assert trace.fired == operation, (fail_at, operation)  # premise: the fault fired where it was aimed
        if operation == "next":
            assert outcome is type(_WALK_FAULTS[kind]("cell")), (fail_at, operation)
        else:
            assert isinstance(outcome, list), (fail_at, operation)
```

### 7.2 M2

**P2-1.** `src/probos/knowledge/records_store.py`
SEARCH:
```
    """BF-952: the walk, parse and ranking of :meth:`RecordsStore.search`, run in a worker thread.

    It reads files under ``search_path`` and touches no store state, so it is safe off the
    event loop. Every record is parsed, not only those that match, because a term's rarity
    is counted over what this reader may read and over nothing else (A4).
    """
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None]] = []
    for md_file in sorted(search_path.rglob("*.md")):
        rel_path = str(md_file.relative_to(root)).replace("\\", "/")
        if rel_path.startswith("_archived/"):
            continue
        try:
            raw = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
```
REPLACE:
```
    """BF-952: the walk, parse and ranking of :meth:`RecordsStore.search`, run in a worker thread.

    It reads files under ``search_path`` and touches no store state, so it is safe off the
    event loop. Every record is parsed, not only those that match, because a term's rarity
    is counted over what this reader may read and over nothing else (A4). BF-958: the walk is
    the default listing's (:func:`_markdown_files`), and a file that resolves outside the
    repository is skipped before it is read, as :meth:`RecordsStore.list_entries` skips it.
    """
    repo = root.resolve()  # BF-958: root is the repository, resolved or as configured
    readable: list[tuple[str, dict[str, Any], str, dict[str, float], int, str | None]] = []
    for md_file in sorted(_markdown_files(search_path, strict=False)):
        rel_path = str(md_file.relative_to(root)).replace("\\", "/")
        if rel_path.startswith("_archived/"):
            continue
        try:
            if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the search reads
                logger.warning(
                    "BF-958: Ship's Records search skipped %s: it resolves outside the records repository (a link), "
                    "so it is not read; read_entry refuses it too",
                    rel_path,
                )
                continue
            raw = md_file.read_text(encoding="utf-8")
        except Exception:
            logger.debug("Skipping unreadable file", exc_info=True)
            continue
```

**P2-2.** `src/probos/knowledge/records_store.py`
SEARCH:
```
def _markdown_files_or_raise(search_path: Path) -> list[Path]:
    """AD-1341 S4 (A4, A5): every file named ``*.md`` under ``search_path``, or the ``OSError`` that hid one.

    A5 (round 3 R3-M1-1): ``os.walk`` filed an entry whose type it could not read as a file and never descended into
    it, as ``Path.rglob`` passed over a directory it could not list (A4): each standard walker absorbs some error. So
    this walk is explicit, and each filesystem operation it makes has one disposition (the contract's 7.3a table):

    - O1 ``os.scandir(search_path)``: ``FileNotFoundError`` or ``NotADirectoryError`` lists nothing, since nothing
      was written under a directory that is not there; any other ``OSError`` raises.
    - O2 ``os.scandir`` of a directory a listing reported: any ``OSError`` raises, ``FileNotFoundError`` included
      (gone since, or unaddressable, it is not proved empty; a strict caller refuses and is retried).
    - O3 each step of a listing: any ``OSError`` raises.
    - O4 ``entry.is_dir(follow_symlinks=False)``: any ``OSError`` raises; the entry is never taken for a file. The
      type comes from the listing record, so a symbolic link is not descended, as ``rglob`` descends none.

    Only a successful listing proves a document absent. A directory named ``*.md`` is no document and is not
    returned; the suffix matches with the platform's case rule (``fnmatch``), as ``rglob``'s does.
    """
    found: list[Path] = []
    pending: list[Path] = [search_path]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)  # O1 for search_path, O2 below it
        except (FileNotFoundError, NotADirectoryError):
            if directory is not search_path:
                raise  # O2 (A5): a directory a listing reported is never "no documents"
            return found  # O1: search_path does not exist, so nothing was written under it
        with listing:
            for entry in listing:  # O3: an OSError while listing propagates
                path = Path(directory, entry.name)
                if entry.is_dir(follow_symlinks=False):  # O4: an OSError propagates; it is never read as "a file"
                    pending.append(path)
                elif fnmatch.fnmatch(entry.name, "*.md"):
                    found.append(path)
    return found
```
REPLACE:
```
def _resolves_inside(path: Path, repo: Path) -> bool:
    """BF-958: whether ``path`` resolves inside ``repo`` (the resolved repository), :meth:`RecordsStore._safe_path`'s
    rule, which the listing and the search apply to each file their walk returns before reading it. A link loop
    resolves nowhere (``Path.resolve`` raises ``RuntimeError``), so it is not inside; an ``OSError`` propagates."""
    try:
        return path.resolve().is_relative_to(repo)
    except RuntimeError:
        return False  # Path.resolve raised RuntimeError: a link loop resolves nowhere, so it is outside


def _markdown_files(search_path: Path, *, strict: bool) -> list[Path]:
    """AD-1341 S4 (A4, A5), BF-958: every file named ``*.md`` under ``search_path`` by a walk that descends no
    directory link; with ``strict``, or the ``OSError`` that hid one.

    A5 (round 3 R3-M1-1): ``os.walk`` filed an entry whose type it could not read as a file and never descended into
    it, as ``Path.rglob`` passed over a directory it could not list (A4): each standard walker absorbs some error. So
    this walk is explicit, and each filesystem operation it makes has one disposition (the AD-1341 S4 contract's 7.3a
    table, with BF-958's OJ row and default column):

    - O1 ``os.scandir(search_path)``: ``FileNotFoundError`` or ``NotADirectoryError`` lists nothing, since nothing
      was written under a directory that is not there. Any other ``OSError``: ``strict`` raises; the default lists
      nothing.
    - O2 ``os.scandir`` of a directory a listing reported: ``strict`` raises any ``OSError``, ``FileNotFoundError``
      included (gone since, or unaddressable, it is not proved empty; a strict caller refuses and is retried). The
      default passes over that directory, as ``rglob`` did.
    - O3 each step of a listing: any ``OSError`` raises, in both modes (``rglob``'s walk raised it too).
    - OJ ``entry.is_junction()`` (BF-958): a directory junction is not descended, and a WARNING names it, in both
      modes. ``is_dir(follow_symlinks=False)`` is true for a junction, so before BF-958 this walk descended one.
    - O4 ``entry.is_dir(follow_symlinks=False)``: the type comes from the listing record, so a symbolic link is not
      descended, as ``rglob`` descends none.

    An ``OSError`` from OJ or O4 raises with ``strict``, and the entry is never taken for a file; the default takes
    the entry for no directory, as ``rglob``'s walk did. Only a successful listing proves a document absent. A
    directory named ``*.md`` is no document and is not returned; the suffix matches with the platform's case rule
    (``fnmatch``), as ``rglob``'s does. Whether a returned file resolves inside the repository is the caller's
    check (:func:`_resolves_inside`).
    """
    found: list[Path] = []
    pending: list[Path] = [search_path]
    while pending:
        directory = pending.pop()
        try:
            listing = os.scandir(directory)  # O1 for search_path, O2 below it
        except (FileNotFoundError, NotADirectoryError):
            if strict and directory is not search_path:
                raise  # O2 (A5): a directory a listing reported is never "no documents"
            continue  # O1: search_path does not exist, so nothing was written under it; O2 in the default mode
        except OSError:
            if strict:  # O1, O2: the strict walk raises what it cannot list
                raise
            logger.debug("Skipping a records directory that cannot be listed: %s", directory, exc_info=True)
            continue  # O1, O2 in the default mode, as rglob passed over it
        with listing:
            for entry in listing:  # O3: an OSError while listing propagates, in both modes
                path = Path(directory, entry.name)
                try:
                    if entry.is_junction():  # OJ (BF-958): never descended; it may lead out of the repository
                        logger.warning(
                            "BF-958: Ship's Records did not descend %s: it is a directory junction, which may lead "
                            "out of the records repository; the records behind it are not listed or searched there",
                            path,
                        )
                        continue
                    is_dir = entry.is_dir(follow_symlinks=False)  # O4
                except OSError:
                    if strict:  # OJ, O4: the strict walk never reads an unknown entry as a file
                        raise
                    is_dir = False  # BF-958: the default walk reads it as rglob's walk did, as no directory
                if is_dir:
                    pending.append(path)
                elif fnmatch.fnmatch(entry.name, "*.md"):
                    found.append(path)
    return found
```

**P2-3.** `src/probos/knowledge/records_store.py`
SEARCH:
```
        A4, A5: ``strict=True`` walks with ``_markdown_files_or_raise``, which raises every ``OSError`` that could leave
        a document unseen (a directory it cannot open, a listing step that fails, an entry whose type it cannot read)
        and reads only a missing ``directory`` as empty. A listed file whose read fails raises for any ``OSError``,
        with no second look at whether it is still a file (A5).
        """
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        results = []
        # AD-1341 S4 (A4): rglob passes over a directory it cannot list; the strict walk raises its OSError instead
        found = _markdown_files_or_raise(search_path) if strict else search_path.rglob("*.md")

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
            # Skip archived
            if rel_path.startswith("_archived/"):
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
```
REPLACE:
```
        A4, A5: ``strict=True`` walks with ``_markdown_files(strict=True)``, which raises every ``OSError`` that could
        leave a document unseen (a directory it cannot open, a listing step that fails, an entry whose type it cannot
        read) and reads only a missing ``directory`` as empty. A listed file whose read fails raises for any
        ``OSError``, with no second look at whether it is still a file (A5).

        BF-958: in both modes the walk does not descend a directory junction, and a listed file that resolves outside
        the repository (a link; :meth:`read_entry` refuses it) is skipped. Each is logged at WARNING; neither raises.
        """
        search_path = self._safe_path(directory) if directory else self._repo_path
        # BF-949 R1: _safe_path resolves, so a directory's paths are taken against the resolved root
        root = self._repo_path.resolve() if directory else self._repo_path
        repo = self._repo_path.resolve()  # BF-958: the containment rule compares resolved paths
        results = []
        # AD-1341 S4 (A4), BF-958: one walk for both modes; only the strict mode raises what hid a document
        found = _markdown_files(search_path, strict=strict)

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
            # Skip archived
            if rel_path.startswith("_archived/"):
                continue
            try:
                if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the listing reads
                    logger.warning(
                        "BF-958: Ship's Records listing skipped %s: it resolves outside the records repository "
                        "(a link), so it is not listed; read_entry refuses it too",
                        rel_path,
                    )
                    continue
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
```

**P2-4.** `src/probos/knowledge/records_store.py`
SEARCH:
```
        list_entries() uses rglob("*.md") which would never find them.
```
REPLACE:
```
        list_entries() lists only *.md files, so it would never find them.
```

**P2-5.** `src/probos/recreation/history.py` (docstring only; `_count_record_names`'s behaviour is unchanged)
SEARCH:
```
    No file is opened. The walk is ``_markdown_files_or_raise``'s: the resolved ``directory`` is
    listed; an entry that ``is_dir(follow_symlinks=False)`` is descended by its unresolved path,
```
REPLACE:
```
    No file is opened. The walk is the store's strict walk (``_markdown_files``) but for one rule: it
    descends a directory junction, which the store's walk passes over (BF-958). The resolved ``directory`` is
    listed; an entry that ``is_dir(follow_symlinks=False)`` is descended by its unresolved path,
```

**N2-1.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
from probos.knowledge.records_store import RecordsStore, _markdown_files_or_raise
```
REPLACE:
```
from probos.knowledge.records_store import RecordsStore, _markdown_files
```

**N2-2.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
class _TracedEntry:
    """A5: a directory entry offering only ``name`` and ``is_dir``: 7.3a's table has no row for anything else."""

    def __init__(self, entry: Any, trace: _Trace) -> None:
        self.name: str = entry.name
        self._entry, self._trace = entry, trace

```
REPLACE:
```
class _TracedEntry:
    """A5: a directory entry offering only ``name``, ``is_junction`` (BF-958's OJ row) and ``is_dir``: 7.3a's table
    has no row for anything else."""

    def __init__(self, entry: Any, trace: _Trace) -> None:
        self.name: str = entry.name
        self._entry, self._trace = entry, trace

    def is_junction(self) -> bool:
        self._trace.tick("is_junction", self._entry.path)
        return bool(self._entry.is_junction())

```

**N2-3.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
    """A5: the real ``_markdown_files_or_raise`` with every ``os.scandir`` traced, and a tripwire on every other
```
REPLACE:
```
    """A5: the real ``_markdown_files(strict=True)`` with every ``os.scandir`` traced, and a tripwire on every other
```

**N2-4.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
        return _markdown_files_or_raise(root)
```
REPLACE:
```
        return _markdown_files(root, strict=True)
```

**N2-5.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
    included, each ``is_dir``); the trace allows nothing else, so an operation added without a row fails here. Then
```
REPLACE:
```
    included, each ``is_junction`` and each ``is_dir``); the trace allows nothing else, so an operation added without
    a row fails here. Then
```

**N2-6.** `tests/test_ad1341_s4_lessons.py`
SEARCH:
```
    assert set(clean.operations) == {"open-root", "open-subdirectory", "next", "is_dir"}  # one row each, no other
```
REPLACE:
```
    assert set(clean.operations) == {"open-root", "open-subdirectory", "next", "is_junction", "is_dir"}  # one row each
```

**N2-7.** `tests/test_bf952_records_keyword_search.py`
SEARCH:
```
    """RK7: the walk, the reads, the parse and the ranking all run in a worker thread, so a search never blocks
    the event loop. The test records the thread of each step: ``rglob`` and ``read_text`` on the store's own path
    class, and the module functions the walk calls. On the base the whole walk ran on the loop's thread (and
    ``_search_read_document`` does not exist there, so the test fails at setup)."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    seen: dict[str, list[int]] = {"rglob": [], "read_text": [], "parse": [], "count": [], "rank": [], "admit": []}
```
REPLACE:
```
    """RK7: the walk, the reads, the parse and the ranking all run in a worker thread, so a search never blocks
    the event loop. The test records the thread of each step: the walk (``_markdown_files``; ``rglob`` before
    BF-958), ``read_text`` on the store's own path class, and the module functions the search calls. On the base
    the whole walk ran on the loop's thread (and ``_search_read_document`` does not exist there, so the test fails
    at setup)."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    seen: dict[str, list[int]] = {"walk": [], "read_text": [], "parse": [], "count": [], "rank": [], "admit": []}
```

**N2-8.** `tests/test_bf952_records_keyword_search.py`
SEARCH:
```
    monkeypatch.setattr(path_type, "rglob", _recording("rglob", path_type.rglob))
```
REPLACE:
```
    monkeypatch.setattr(records_store_module, "_markdown_files", _recording("walk", records_store_module._markdown_files))
```

**N2-9.** `tests/test_bf958_records_link_containment.py` (the markers come off)
SEARCH:
```
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-958 M2 builds it")
_BUILT_ON_WINDOWS = pytest.mark.xfail(
    os.name == "nt", raises=AssertionError, strict=True,
    reason="BF-958 M2 builds it; elsewhere the base already passes over a directory symbolic link",
)
_MODES = ["list-strict", "list-default", "search"]
```
REPLACE:
```
_MODES = ["list-strict", "list-default", "search"]
```

**N2-10.** `tests/test_bf958_records_link_containment.py`
SEARCH:
```
@_BUILT_ON_WINDOWS
async def test_a_directory_link_out_of_the_repository_is_not_listed_or_searched(
```
REPLACE:
```
async def test_a_directory_link_out_of_the_repository_is_not_listed_or_searched(
```

**N2-11.** `tests/test_bf958_records_link_containment.py`
SEARCH:
```
@_BUILT
async def test_a_listed_file_that_resolves_outside_is_skipped_with_a_warning(
```
REPLACE:
```
async def test_a_listed_file_that_resolves_outside_is_skipped_with_a_warning(
```

**N2-12.** `tests/test_bf958_records_link_containment.py`
SEARCH:
```
@_BUILT
async def test_a_markdown_link_to_a_file_outside_is_skipped_with_a_warning(
```
REPLACE:
```
async def test_a_markdown_link_to_a_file_outside_is_skipped_with_a_warning(
```

**N2-13.** `tests/test_bf958_records_link_containment.py`
SEARCH:
```
@_BUILT_ON_WINDOWS
async def test_a_directory_link_cycle_is_not_descended_and_the_walk_ends(
```
REPLACE:
```
async def test_a_directory_link_cycle_is_not_descended_and_the_walk_ends(
```

**N2-14.** `tests/test_bf958_records_link_containment.py`
SEARCH:
```
@_BUILT
def test_the_default_walk_raises_only_a_failed_listing_step(tmp_path: Path, kind: str) -> None:
```
REPLACE:
```
def test_the_default_walk_raises_only_a_failed_listing_step(tmp_path: Path, kind: str) -> None:
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-958 (DATE), #1761 -- Ship's Records listing and search follow no directory junction out of the repository.**
- **Base.** `RecordsStore.list_entries` (strict or not) and `search` descended a directory junction below a listed directory (`is_dir(follow_symlinks=False)` is true for one on Windows) and read a `*.md` link without checking where it resolves, so they could return a file from outside the repository that `read_entry` refused, with its frontmatter and, in a search, a 200-character snippet.
- **Fix.** One walk, `_markdown_files(strict=...)`, serves both listings and the search and does not descend a directory junction; each listed file is read only if it resolves inside the resolved repository (`_safe_path`'s rule). Both skips are logged at WARNING in both modes and raise in neither. The default walk passes over what `rglob` passed over.
- **Changed for a link layout.** A junction cycle is not descended, so the strict walk no longer ends with `OSError` after about 60 levels. A junction that stays inside is not descended either; its records are listed at their own paths.
- **Not changed.** The store's other walks (`get_stats`, `list_bills`, the notebook similarity and convergence checks; follow-up `#1762`) and `_count_record_names` (AD-1358). Contract `prompts/bf-958-records-link-containment.md`.

```

**P3-2.** `DECISIONS.md`. Append after BF-957's entry. Its last bullet occurs once.
SEARCH:
```
- *Reversal.* Revert the BF-957 commits.
```
REPLACE:
```
- *Reversal.* Revert the BF-957 commits.

### BF-958 -- Ship's Records listing and search follow no directory junction out of the repository (DATE, #1761)

- *Scope.* `knowledge/records_store.py` (`_markdown_files` replacing `_markdown_files_or_raise`, `_resolves_inside`, `list_entries`, `_search_records`, a docstring of `list_bills`), the docstring of `recreation/history.py::_count_record_names`, tests. Contract `prompts/bf-958-records-link-containment.md`.
- *G1 (walk).* One walk for both listing modes and the search; it does not descend `DirEntry.is_junction()` (as AD-1341 S6's snapshot walk refuses one). Rejected: checking each directory against the repository before listing it (an inside cycle still descends until `OSError`; duplicates).
- *G2 (file).* Each listed file is read only if it resolves inside the resolved repository, `read_entry`'s rule, so an inside `*.md` link stays listed as `read_entry` reads it.
- *G3 (signal).* A skipped junction or file is logged at WARNING in both modes and raises in neither: it is no document of this store, so the strict callers' rule (an unreadable document is never an absent one) holds.
- *Not changed.* `read_entry`, `_safe_path`, the store's other walks, `_count_record_names`'s behaviour.
- *Residual.* Recorded limits L1 to L9 of the contract.
- *Reversal.* Revert the BF-958 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited: Grep `BF-95[0-9]` in `docs/development/roadmap.md` finds 0.

## 8. What this does NOT change

- `read_entry`, `_safe_path`, any write path.
- `get_stats`, `list_bills`, `check_notebook_similarity`, `check_cross_agent_convergence` (follow-up #1762).
- `_count_record_names` behaviour (AD-1358); only its docstring changes.
- `records_snapshot.py`, the semantic index, BF-957's git handling.
- Every `list_entries` and `search` result for a layout without a link. T5 and the existing suites guard this.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/knowledge/records_store.py | `if entry.is_junction():  # OJ (BF-958): never descended; it may lead out of the repository` | `if False:` | T4, T1 WARNING (Windows; inert on POSIX) |
| 2 | M2 | src/probos/knowledge/records_store.py | `return path.resolve().is_relative_to(repo)` | `return True` | T2[outside] |
| 3 | M2 | src/probos/knowledge/records_store.py | `return False  # Path.resolve raised RuntimeError: a link loop resolves nowhere, so it is outside` | `return True` | T2[loop] |
| 4 | M2 | src/probos/knowledge/records_store.py | `if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the listing reads` | `if False:` | T2 list cases |
| 5 | M2 | src/probos/knowledge/records_store.py | `if not _resolves_inside(md_file, repo):  # BF-958: read_entry's rule, before the search reads` | `if False:` | T2 search cases |
| 6 | M2 | src/probos/knowledge/records_store.py | `repo = self._repo_path.resolve()  # BF-958: the containment rule compares resolved paths` | `repo = self._repo_path` | T6 |
| 7 | M2 | src/probos/knowledge/records_store.py | `repo = root.resolve()  # BF-958: root is the repository, resolved or as configured` | `repo = root` | T6 |
| 8 | M2 | src/probos/knowledge/records_store.py | `found = _markdown_files(search_path, strict=strict)` | `found = _markdown_files(search_path, strict=True)` | T7 |
| 9 | M2 | src/probos/knowledge/records_store.py | `for md_file in sorted(_markdown_files(search_path, strict=False)):` | `for md_file in sorted(_markdown_files(search_path, strict=True)):` | T7 |
| 10 | M2 | src/probos/knowledge/records_store.py | `if strict and directory is not search_path:` | `if directory is not search_path:` | T8[absent] |
| 11 | M2 | src/probos/knowledge/records_store.py | `if strict:  # O1, O2: the strict walk raises what it cannot list` | `if False:` | T7, AD-1341 S4 matrix |
| 12 | M2 | src/probos/knowledge/records_store.py | `if strict:  # OJ, O4: the strict walk never reads an unknown entry as a file` | `if False:` | AD-1341 S4 `test_every_operation_of_the_strict_walk_raises_unless_the_root_is_missing` |
| 13 | M2 | src/probos/knowledge/records_store.py | `if strict:  # OJ, O4: the strict walk never reads an unknown entry as a file` | `if True:` | T8 |
| 14 | M2 | src/probos/knowledge/records_store.py | `is_dir = False  # BF-958: the default walk reads it as rglob's walk did, as no directory` | `raise` | T8 |

There is no campaign of record yet; the Builder runs these mutants on M2's head (Windows host).

## 10. Recorded limits

- **L1.** A file replaced by a link between the check and the read is read, the same window `read_entry` has. A descriptor-based check (`O_NOFOLLOW`, handle identity) was considered and deferred.
- **L2.** A hard link to an outside file cannot be told apart, and is read, as `read_entry` reads it.
- **L3.** A directory symbolic link (POSIX, or Windows `mklink /D`) is not descended, as before, and not logged. Only a junction is logged.
- **L4.** The WARNING repeats once per link per call; nothing deduplicates across calls.
- **L5.** A directory reparse point that is not a junction (for example a cloud-file placeholder) is descended as before; its files are still contained.
- **L6.** Records behind an inside junction are not listed under the junction's path, although `read_entry` reads that path.
- **L7.** `list_entries`' walk and reads still run on the event loop (register R22). BF-958 adds one `Path.resolve` per listed file; the cost is not measured.
- **L8.** `_count_record_names` descends an inside junction, so its count can exceed the listing's. This errs on the safe side for the cap.
- **L9.** In default mode, an entry named `*.md` whose type cannot be read is returned, then skipped at its read, as `rglob` did.

## 11. Verified Against Codebase (2026-11-06, oracle `D:\ProbOS-worktrees\bf957-o3`)

```
Grep "def |rglob|is_dir\(|_safe_path|read_text|..." records_store.py
  394 _search_records; 410 for md_file in sorted(search_path.rglob("*.md")); 415 read_text
  490 def _markdown_files_or_raise; 513 os.scandir; 521 entry.is_dir(follow_symlinks=False)
  1336 list_entries; 1365 found = _markdown_files_or_raise(...) if strict else search_path.rglob("*.md"); 1373 read_text
  1493 search; 1501 asyncio.to_thread(_search_records, ...); 1610-1621 _safe_path; 1305-1334 read_entry
Read records_store.py:340-534, :535-554, :927-950, :1040-1099, :1130-1189, :1305-1544, :1606-1621
Grep BF-957 records_store.py -> 23, 25, 27, 32, 540, 542, 1650, 1694, 1707, 1714 (BF-957 regions)
Grep "glob\(|iterdir\(|os\.walk|scandir\(" records_store.py -> 410, 513, 769, 943, 1059, 1148, 1157, 1365, 1513, 1528
Grep anchors (count): history.py 2 lines once each; records_store.py 4 lines once each
Read pathlib.py (CPython 3.12.13, uv home from .venv/pyvenv.cfg):176-255 (_WildcardSelector catches OSError;
  _RecursiveWildcardSelector walks with Path.walk), :1112-1155 (Path.walk: follow_symlinks=False; scandir OSError
  ignored; is_dir OSError -> file), :1228-1240 (resolve raises RuntimeError "Symlink loop"), :924 is_junction
Grep requires-python pyproject.toml -> ">=3.12"; asyncio_mode = "auto"
Read records_snapshot.py:205-244 (:227 entry.is_symlink() or entry.is_junction() refused)
Read recreation/history.py:123-202 (_count_record_names directory check :141-142; listing :183; read_entry :197)
Read archive_promotion.py:296-375 (:310 strict listing; :315, :372 read_entry); stand_down.py:268-297 (:281)
Read semantic.py:700-729; Grep read_entry semantic.py -> :738; Read __main__.py:3566-3576, :3138-3172
Read routers/work.py:78-90 (work-item store)
Grep "list_entries\(|(records|_store|store|_records)\.search\(" src -> consumers listed in D3
Grep "strict=True" src -> archive_promotion.py:310, stand_down.py:281, recreation/history.py:184 (+ unrelated pydantic/zip)
Read tests/test_ad1341_s4_lessons.py:1-62, :112-340, :920-970 (tracer, _TracedEntry, matrix :931-953)
Read tests/test_bf952_records_keyword_search.py:316-354 (patches rglob)
Read tests/test_ad1358_s1_head_to_head.py:690-810 (link helpers; outside and cycle tests stay valid: count refuses first)
Read tests/test_ad1200_instruction_file_access.py:30-52 (_junction, _unlink_junction)
Grep config_models/knowledge.py -> :321 repo_path, :322 auto_commit
Grep architecture-baseline.yaml records_store -> srp-size triggers only (no frozen count)
Grep PROGRESS.md -> :1 title, :3 BF-957 entry; DECISIONS.md -> :1490 AD-1358 S1 Reversal, :1501 BF-957 Reversal
Read docs/development/engineering-principles.md:36-79 (Testing, Logging)
```

**Absence Verified (2026-11-06)**

```
CLAIM: _markdown_files and _resolves_inside are new; BF-958 is not yet in the code
RUN:   Grep "_markdown_files\b|_resolves_inside|BF-958" src/**/*.py, tests/**/*.py (oracle)
FOUND: 0
HOLDS: yes

CLAIM: the old walk name is referenced only where this contract edits it
RUN:   Grep "_markdown_files_or_raise" src; Grep the same in tests
FOUND: src: records_store.py:490, :1355, :1365; history.py:126. tests: test_ad1341_s4_lessons.py:57, :311, :327
HOLDS: yes (P2-2, P2-3, P2-5, N2-1, N2-3, N2-4)

CLAIM: only the BF-952 test patches rglob for a records reader
RUN:   Grep "_markdown_files|\"rglob\"|'rglob'|records_store\.py" tests
FOUND: test_bf952_records_keyword_search.py:327, :336 (others: unrelated census rows; ad1270f patches Path.rglob for the codebase index)
HOLDS: yes

CLAIM: list_bills has no production caller
RUN:   Grep "list_bills\(" src/probos
FOUND: records_store.py:927 (definition only)
HOLDS: yes

CLAIM: the roadmap holds no BF-95x row
RUN:   Grep "BF-95[0-9]" docs/development/roadmap.md
FOUND: 0
HOLDS: yes
```

**Not measured by the Architect:**
- The `--collect-only` counts (M0 records them).
- The oracle blob hash (`git -C` was refused).
- The orchestrator's probes; their facts are cited from the issue and the request.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** AD-1341 S6's snapshot walk (`records_snapshot.py:227`) treats `entry.is_junction()` as a link that is never followed. The same predicate is used here for directories.
  - **Not adopted:** S6 refuses every file link. The store's `read_entry` and `write_entry` admit an inside link, and stand-down relies on the listing agreeing with `write_entry`: it must not ask an agent to write over a note that exists behind a link.
- **Internal: rejected.** AD-1358's per-directory check (`history.py:141`) is D1 option (b).
- **Internal: reused.** `_safe_path`'s rule (`:1615-1618`) is restated in `_resolves_inside` for an absolute path. `_safe_path` takes a user path and raises, so it cannot be called on a walked file directly.
- **External** (from search summaries only):
  - [bpo-23407](https://bugs.python.org/issue23407): `os.walk` followed Windows junctions with `followlinks=False`. A [UrBackup report](https://blog.urbackup.org/163/python-on-windows-issues) describes an infinite loop through `C:\Users` compatibility junctions, ended by the path-length limit.
  - Recent CPython treats a junction as a link in `os.walk` and `rmtree` ([gh-156707 commit](https://chromium.googlesource.com/external/github.com/python/cpython/+/d87ee279a1f6dfdb478ede5f0ba0360123d85916)). Not verified for 3.12.13; this design does not rely on it.
  - CWE-59 guidance ([corgea](https://hub.corgea.com/vulnerabilities/CWE-59), [CIRCL](https://cvepremium.circl.lu/cwe/CWE-59?page=73)): canonicalize, then compare with the allowed root. That is adopted here. A check separated from the open leaves a race (L1). Descriptor-identity checks were considered and deferred.
- **`reference-projects.md`** (judged on 2026-11-06): no row concerns filesystem link handling. None was examined and none is updated; overdue rows such as AG-UI are unrelated.
- **Blind spots handled.**
  - A root that is itself a link (T6).
  - An inside `*.md` link (T3b).
  - Duplicates through an inside junction or a cycle (T4).
  - A loop link making `Path.resolve` raise `RuntimeError` (T2[loop]).
  - Readers that list and then call `read_entry` were raising `ValueError` on this layout (§1.6).
  - The default walk keeps `rglob`'s tolerance (T7, T8).
- **Blind spots recorded.** L1 (race), L3 (directory symlink not logged), L7 (event loop).

## 13. Diff Reviewer: properties to verify (whole-candidate review: shared contract)

1. On a tree with no junction, `_markdown_files(p, strict=True)` returns what `_markdown_files_or_raise(p)` returned, and raises exactly where it raised (O1–O4). It also raises for an `OSError` from `is_junction()`.
2. `_markdown_files(p, strict=False)` never raises when opening a directory or reading an entry's type. A failed listing step raises in both modes.
3. No entry whose `is_junction()` is true is ever appended to `pending` or `found`.
4. In `list_entries` and `_search_records`, `read_text` runs only after `_resolves_inside(md_file, repo)` is true. `repo` is the resolved repository: `self._repo_path.resolve()`, or `root.resolve()` where `root` is the repository.
5. Neither skip raises in strict mode. Strict mode's other raises (a read `OSError`, A5/O5) are unchanged.
6. No `rglob` remains in `list_entries` or `_search_records`. The store's other walks are byte-unchanged.
7. Each WARNING names a path and logs no file content.
8. Every test link is removed in a `finally` by `rmdir` (junction) or `unlink` (symlink), never its target. The only skip is T3's host precondition.
9. At M1 on Windows, each xfail case fails at an `AssertionError`.
10. `history.py` changes only in its docstring.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **Below a listed directory, a junction that leads outside:** `list_entries` (strict and not) and `search` neither return nor read the outside file, and a WARNING names the junction (T1).
- **A `*.md` link to an outside file:** skipped with a WARNING (T2, T3a).
- **A junction cycle (amended):** it is not descended; the walk ends with each record once, a WARNING, and no `OSError` (T4).
- **No regressions:** an ordinary nested directory, a root that is a link, an inside `*.md` link and every existing records test behave as before (T5, T6, T3b, G2).
- T1 crosses the seam: a real link, reached through the public API, gives the result and the WARNING, and agrees with `read_entry`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

**Follow-up F1** is filed as #1762 (BF-959): the store's other walks (`check_notebook_similarity`, `check_cross_agent_convergence`, `get_stats`, `list_bills`) and what each does with a link. The shape it names is to reuse `_markdown_files` and `_resolves_inside` from BF-958. The issue, not this contract, holds the per-walk findings.

Sources:
- [bpo-23407: os.walk always follows Windows junctions](https://bugs.python.org/issue23407)
- [UrBackup: Python on Windows issues](https://blog.urbackup.org/163/python-on-windows-issues)
- [gh-156707 commit: do not follow junctions in os_helper.rmtree()](https://chromium.googlesource.com/external/github.com/python/cpython/+/d87ee279a1f6dfdb478ede5f0ba0360123d85916)
- [CWE-59 (corgea)](https://hub.corgea.com/vulnerabilities/CWE-59)
- [CWE-59 records (CIRCL)](https://cvepremium.circl.lu/cwe/CWE-59?page=73)
