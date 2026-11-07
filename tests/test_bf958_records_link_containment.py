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
