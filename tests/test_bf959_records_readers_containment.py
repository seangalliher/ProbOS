"""BF-959 (#1762): Ship's Records convergence scan, notebook similarity check, statistics and bill listing follow no
directory link out of the records repository and use no file that resolves outside it.

Real ``RecordsStore`` objects on real directories in ``tmp_path``; no git. The directory-link, read-spy and resolve
helpers are BF-958's (a junction on Windows, a symbolic link elsewhere; a file that resolves away needs no privilege).
Each link is removed in a ``finally``: the link alone, never its target.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.config import RecordsConfig
from probos.knowledge.records_store import RecordsStore
from tests.test_bf958_records_link_containment import (
    _LOGGER,
    _bf958_warnings,
    _directory_link,
    _record_reads,
    _remove_directory_link,
    _resolve_away,
)

_BODY = "a quasar seen from the bridge, logged for the convergence scan"
_OTHER = "galley menu rotation next week pasta"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-959 M2 builds it")
_BUILT_ON_WINDOWS = pytest.mark.xfail(
    os.name == "nt", raises=AssertionError, strict=True,
    reason="BF-959 M2 builds it; elsewhere the base's rglob already passes over a directory symbolic link",
)


def _note(path: Path, author: str, department: str, topic: str, body: str) -> None:
    """A notebook file with the frontmatter the scan reads; ``updated`` is now, an ISO string that ``yaml`` quotes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "author": author, "classification": "ship", "department": department, "topic": topic,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


def _layout(repo: Path) -> None:
    """The controls: an ordinary notebook directory of another department (``dave``) and one bill."""
    _note(repo / "notebooks" / "dave" / "d.md", "Dave", "operations", "secret", _BODY)
    (repo / "bills").mkdir(parents=True, exist_ok=True)
    (repo / "bills" / "inside.bill.yaml").write_text("id: inside\n", encoding="utf-8")


def _store(tmp_path: Path) -> tuple[RecordsStore, Path]:
    repo = tmp_path / "ship-records"
    _layout(repo)
    return RecordsStore(RecordsConfig(repo_path=str(repo))), repo


def _bf959_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records
        if r.name == _LOGGER and r.levelno == logging.WARNING and "BF-959" in r.getMessage()
    ]


def _resolve_fails(monkeypatch: pytest.MonkeyPatch, victim: Path) -> None:
    """``Path.resolve`` of ``victim`` raises ``PermissionError``; every other path resolves as it does."""
    real_resolve = Path.resolve
    target = real_resolve(victim)

    def resolve(self: Path, *args: Any, **kwargs: Any) -> Path:
        resolved = real_resolve(self, *args, **kwargs)
        if resolved == target:
            raise PermissionError(13, "the path cannot be resolved", str(self))
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve)


@_BUILT
async def test_the_convergence_scan_reports_nothing_behind_a_directory_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The issue's probe on the real scan: a link at ``notebooks/alice`` leads to ``secret.md``, a fresh note that
    matches the anchor; ``dave``, an ordinary directory, is the control. ``read_entry`` and layer 2 refuse the path;
    neither leg of the scan names, returns (the divergence leg returns frontmatter) or reads the file."""
    store, repo = _store(tmp_path)
    outside = tmp_path / "outside"
    _note(outside / "secret.md", "outsider", "engineering", "secret", _BODY)
    link = repo / "notebooks" / "alice"
    reads = _record_reads(monkeypatch)
    _directory_link(link, outside)
    try:
        with pytest.raises(ValueError, match="Path traversal denied"):  # premise: read_entry's rule refuses it
            await store.read_entry("notebooks/alice/secret.md", reader_id="captain")
        with pytest.raises(ValueError, match="Path traversal denied"):  # layer 2 of the similarity check, unchanged
            await store.check_notebook_similarity("alice", "anything", _BODY)
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        converged = await store.check_cross_agent_convergence("bob", "science", "own", _BODY)
        diverged = await store.check_cross_agent_convergence("bob", "science", "secret", _OTHER)
    finally:
        _remove_directory_link(link)
    assert (outside / "secret.md").is_file()  # the link alone was removed
    assert converged["convergence_agents"] == diverged["divergence_agents"] == ["bob", "dave"]
    assert [m["frontmatter"]["author"] for m in diverged["divergence_matches"]] == ["Dave"]
    assert "d.md" in reads  # premise: the spy sees the scan's reads of the ordinary directory
    assert "secret.md" not in reads and "outsider" not in repr((converged, diverged))
    assert any("did not scan" in m and "notebooks/alice" in m for m in _bf959_warnings(caplog)), caplog.text


@pytest.mark.parametrize("kind", ["outside", "unreadable"])
@pytest.mark.parametrize("reader", ["convergence", "similarity", "statistics", "bills"])
@_BUILT
async def test_a_file_that_resolves_away_is_skipped_by_each_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, reader: str, kind: str,
) -> None:
    """The per-file rule on every platform, with no privilege: a file in a real directory resolves outside the
    repository (``outside``, what a ``*.md`` link out does) or its resolution fails (``unreadable``). Each reader skips
    it and serves the rest; the two that read a note never read it. Only ``outside`` is a WARNING."""
    store, repo = _store(tmp_path)
    _note(repo / "notebooks" / "alice" / "note.md", "Alice", "engineering", "note", _OTHER)
    if reader == "bills":
        victim = repo / "bills" / "escape.bill.yaml"
        victim.write_text("id: escape\n", encoding="utf-8")
    else:
        victim = repo / "notebooks" / "alice" / "escape.md"
        _note(victim, "outsider", "engineering", "secret", _BODY)
    if kind == "outside":
        _resolve_away(monkeypatch, victim, tmp_path / "outside" / victim.name)
    else:
        _resolve_fails(monkeypatch, victim)
    reads = _record_reads(monkeypatch)
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    if reader == "convergence":
        found = await store.check_cross_agent_convergence("bob", "science", "own", _BODY)
        assert found["convergence_agents"] == ["bob", "dave"]
    elif reader == "similarity":
        assert (await store.check_notebook_similarity("alice", "other", _BODY))["action"] == "write"
    elif reader == "statistics":
        assert (await store.get_stats())["total_documents"] == 2  # d.md and note.md
    else:
        assert await store.list_bills() == [{"path": "bills/inside.bill.yaml", "bill_id": "inside"}]
    if reader in ("convergence", "similarity"):
        assert "note.md" in reads  # premise: the spy sees the reader's reads
        assert victim.name not in reads  # skipped before its read
    skipped = [m for m in _bf959_warnings(caplog) if victim.relative_to(repo).as_posix() in m]
    assert bool(skipped) == (kind == "outside"), caplog.text


@pytest.mark.parametrize(("link_at", "directories"), [
    pytest.param("notebooks/alice", {"notebooks": 1, "bills": 0}, marks=_BUILT_ON_WINDOWS, id="callsign"),
    pytest.param("reports", {"notebooks": 1, "bills": 0, "reports": 0}, marks=_BUILT, id="subdirectory-root"),
    pytest.param("bills/linked", {"notebooks": 1, "bills": 0}, marks=_BUILT_ON_WINDOWS, id="bills"),
])
async def test_the_statistics_and_the_bill_listing_descend_no_directory_link(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, link_at: str, directories: dict[str, int],
) -> None:
    """A directory link below a listed directory, at a ``_SUBDIRS`` root (a walk's own root is read, so ``rglob``
    followed a link there on every platform) or in ``bills`` leads to ``secret.md`` and ``outside.bill.yaml``. Neither
    reader counts or lists them; on Windows a WARNING names the junction."""
    store, repo = _store(tmp_path)
    outside = tmp_path / "outside"
    _note(outside / "secret.md", "outsider", "engineering", "secret", _BODY)
    (outside / "outside.bill.yaml").write_text("id: outside\n", encoding="utf-8")
    link = repo / link_at
    _directory_link(link, outside)
    try:
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        stats = await store.get_stats()
        bills = await store.list_bills()
    finally:
        _remove_directory_link(link)
    assert (outside / "secret.md").is_file()  # the link alone was removed
    assert (stats["total_documents"], stats["directories"]) == (1, directories)
    assert bills == [{"path": "bills/inside.bill.yaml", "bill_id": "inside"}]
    if os.name == "nt":
        assert any("did not descend" in m and link.name in m for m in _bf958_warnings(caplog)), caplog.text


@pytest.mark.parametrize("relocated", [False, True], ids=["ordinary", "root-is-a-link"])
async def test_ordinary_directories_are_still_scanned_counted_and_listed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, relocated: bool,
) -> None:
    """The guard: with no link below the root, and with a root that is itself a link (a relocated data directory; the
    rule compares resolved paths), every reader returns what it returned before BF-959, and nothing is logged."""
    root = tmp_path / "ship-records"
    real = tmp_path / "relocated" if relocated else root
    _layout(real)
    _note(real / "notebooks" / "alice" / "note.md", "Alice", "engineering", "note", _OTHER)
    _note(real / "notebooks" / "alice" / "twin.md", "Alice", "engineering", "twin", _BODY)
    (real / "_archived").mkdir()
    (real / "_archived" / "old.md").write_text("archived\n", encoding="utf-8")
    (real / "bills" / "drills").mkdir()
    (real / "bills" / "drills" / "deep.bill.yaml").write_text("id: deep\n", encoding="utf-8")
    if relocated:
        _directory_link(root, real)
    try:
        store = RecordsStore(RecordsConfig(repo_path=str(root)))
        if relocated:
            assert store.repo_path != store.repo_path.resolve()  # premise: the configured path is the link
        caplog.set_level(logging.WARNING, logger=_LOGGER)
        converged = await store.check_cross_agent_convergence("bob", "science", "own", _BODY)
        similar = await store.check_notebook_similarity("alice", "other", _BODY)
        stats = await store.get_stats()
        bills = await store.list_bills()
    finally:
        if relocated:
            _remove_directory_link(root)
    assert converged["convergence_agents"] == ["alice", "bob", "dave"]
    assert (similar["action"], similar["existing_path"]) == ("suppress", "notebooks/alice/twin.md")
    assert (stats["total_documents"], stats["directories"]) == (4, {"notebooks": 3, "bills": 0})
    assert sorted(b["path"] for b in bills) == ["bills/drills/deep.bill.yaml", "bills/inside.bill.yaml"]
    assert not _bf959_warnings(caplog) and not _bf958_warnings(caplog)
