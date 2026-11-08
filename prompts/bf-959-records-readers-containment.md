# BF-959 (#1762): Ship's Records convergence scan, similarity check, statistics and bill listing follow no directory link out of the repository and use no file that resolves outside it

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was not logged in), 2026-11-08
**Status:** ready to build on `origin/main` `98d0d99b` (BF-958 is in it: PR #1768), in `D:\ProbOS-worktrees\bf959-build`.
**Oracle (2026-11-08, the orchestrator):** every pair (7 + 4 + 2, and the new test file) was applied by tool on `98d0d99b`, each SEARCH matching exactly once. G1 at M1: 2 passed, 12 xfailed. G2 on the M3 head: 396 passed, 6 skipped (the nine existing files on the base: 382 passed, 6 skipped; the six skips are BF-958's file-symlink cases). `check_architecture_principles.py --check` passes and no `.rglob(` is left. A mutation census of section 9's ten rows (`tests/test_bf959_records_readers_containment.py` alone) killed all ten. Blobs at the M2 head: `records_store.py` `8c9e0f7d2d36d04afff38e2aa8fb8fea64bf0bc1`, the test file `e69e14a5993c42eb4dd691049daf0483e23f9d73` (at M1: `681746abfca3ac0c8cc34d73f736bd34f3923ed3`).
**Base:** every SEARCH was taken on `98d0d99b`. `records_store.py` is blob `1df5fe3d6b332b2196041e36ec1a4ec055eda14a`; `tests/test_bf958_records_link_containment.py` is blob `6cc912e95a067fa8c9f9c00256eceaba5f2f3a0e`.
**Dependencies:** BF-958 (`_markdown_files`, `_resolves_inside`, the link helpers of its test module).
**Tier:** M1 STANDARD (tests only). M2 HIGH (a containment control in a security path). M3 STANDARD.
**Estimated tests:** one new file, `tests/test_bf959_records_readers_containment.py`: 4 functions, 14 cases. No existing test file is edited. Counted by reading, not by running.
**BF number:** BF-959, held by #1762. Nothing new is allocated.

**Which text describes the head.** Before building: (1) `git rev-parse HEAD:src/probos/knowledge/records_store.py` must print the blob above; (2) `git diff --stat 98d0d99b HEAD -- src/probos/knowledge/records_store.py tests/test_bf958_records_link_containment.py PROGRESS.md DECISIONS.md` must be empty; (3) `tests/test_bf959_records_readers_containment.py` must not exist. If (1) or (2) fails, every SEARCH below must still occur exactly once; otherwise it is a hard stop and goes back to the Architect. Working copies are CRLF and SEARCH text here is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **The scan reads what a link leads to.** `check_cross_agent_convergence` (`records_store.py:1149`) takes `notebooks_dir.iterdir()` (`:1197`), `agent_dir.is_dir()` and `agent_dir.glob("*.md")` (`:1206`) and reads each file with no containment rule; its caller is `proactive.py:3396`. Measured by the orchestrator on `98d0d99b` (a probe on a synthetic repository in a temporary directory; Windows, CPython 3.12.13; premises asserted): with a junction `notebooks/alice` to a directory holding a fresh `secret.md`, the convergence leg reports agents `['alice','bob','carol']` and the path `notebooks/alice/secret.md`, and the divergence leg returns the file's parsed frontmatter in `divergence_matches[*].frontmatter` (`:1349` strips only `content`).
2. **Statistics count it** (`get_stats`, `:1576`; `rglob` at `:1578`, `:1593`): 3 documents where 2 are real (measured). **Bills** (`list_bills`, `:976`; `rglob` at `:992`) lists `bills/linked/outside.bill.yaml` (measured); nothing in `src` calls it.
3. **Layer 3** (`check_notebook_similarity`, `:1000`) globs `notebooks/<callsign>/*.md` (`:1108`) and reads each file: a `*.md` link out would be read (by the code; not measured: this host has no file-symlink privilege). A junction callsign never reaches it: layer 2 resolves the exact-topic path with `_safe_path` (`:1040`, outside any `try`) and raises `ValueError: Path traversal denied` (measured).
4. **Consumers** (read end to end). The scan's result goes to `_write_convergence_report` (`proactive.py:3931`), which reads each match by path through `read_entry`, so a junction path is refused and its snippet is empty, but the persisted report still names the callsign and department; then `ConvergenceDetectedEvent`, a Bridge Alert and AD-583's escalation (`:3409`-`:3473`). Layer 3's callers (`proactive.py:3245`, `:4403`; `publish_finding_tool.py:765`) catch a raise and write anyway; a `suppress` result drops the agent's note. `get_stats` is served by `routers/records.py:35`.

Reach, as #1762 states it: a directory junction (Windows), a directory symlink or a `*.md` link inside the records tree; the store creates none (#1762). Severity P3.

## 2. Solution

- **`_contained(path, repo, rel_path, reader)`** (new, module level): BF-958's `_resolves_inside` plus the WARNING; it never raises.
- **Scan:** a junction or symlink at `notebooks/<callsign>` is not scanned (WARNING); each file passes `_contained` before its first read. **Layer 3:** the same per-file check. **`get_stats`:** one walk of the repository (`_markdown_files(strict=False)`), each file through `_contained`; the per-directory counts come from that list. **`list_bills`:** the same walk with `pattern="*.bill.yaml"`, each file through `_contained`.
- **`_markdown_files`** gains `pattern: str = "*.md"`; `list_entries` and `_search_records` pass nothing.

## 3. Decisions

D1 to D9 are in the tables above this contract. The dispositions (D6): no reader has a strict mode, so each follows BF-958's default column.

| Row | Operation | Where | Disposition |
|---|---|---|---|
| L1 | `Path.is_junction()` of `notebooks/<callsign>` | scan | Never raises (`ntpath.py:284-290`: an `OSError` gives False). True: WARNING, the directory is not scanned |
| L2 | `Path.is_symlink()` of the same | scan | An `lstat`; a missing path, a non-directory or a loop gives False (`pathlib.py:45`, `:909`); any other `OSError` raises inside the scan's `try`: DEBUG, the scan returns its empty result (its disposition for a failed directory step). True: as L1 |
| R | `Path.resolve()` of each file (`_contained`) | scan, layer 3, statistics, bills | Outside, or `RuntimeError` (a loop): WARNING, skipped. `OSError`: DEBUG, skipped (fail closed). Never raised to the caller |
| Rr | `self._repo_path.resolve()`, once per call | scan, layer 3, statistics | Inside the scan's and layer 3's `try`: an `OSError` ends that scan or layer 3 at its DEBUG line (empty result, no match). In `get_stats` it raises, as `list_entries`' own call does |
| W | `_markdown_files(strict=False)` | statistics, bills | BF-958's O1-O4 and OJ, default column: a missing root lists nothing; a directory that cannot be opened is passed over; an `OSError` while listing raises, as `rglob`'s descent did (BF-958 L10), and neither reader catches it, as before; a junction: BF-958's WARNING |

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-7, then N2-1 to N2-4 (removing the markers) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

- **M0.** On the head, record the collected count (`--collect-only -q`) of every existing file named in G2.
- **G1.** `PY -m pytest tests/test_bf959_records_readers_containment.py -q -n 0 -p no:randomly`.
  - **Expected on the Windows gate host:** **2 passed** (T4 x2), **12 xfailed** (T1, T2 x8, T3 x3). **On POSIX:** 4 passed, 10 xfailed (T3's callsign and bills cases already pass: `rglob` descends no directory symlink).
  - The markers carry `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL. Any other count is a hard stop.
- **G2.**
  1. `PY -m pytest tests/test_bf959_records_readers_containment.py tests/test_records_store.py tests/test_ad550_notebook_dedup.py tests/test_ad554_realtime_convergence.py tests/test_ad583_wrong_convergence.py tests/test_bf949_notebook_reader_identity.py tests/test_bf952_records_keyword_search.py tests/test_bf958_records_link_containment.py tests/test_ad1341_s4_lessons.py tests/test_ad1346_admission_file_write_census.py -q -n 0 -p no:randomly`
  2. `PY -P scripts/check_architecture_principles.py --check`
  3. `rg -n "\.rglob\(" src/probos/knowledge/records_store.py` finds nothing.
  - **Expected:** the new file 14 passed; every other file 0 failed, collected counts equal M0; the check is clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, and no loosened assertion. Any of these goes back to the Architect.
- The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-959 M1: tests for the convergence scan, similarity check, statistics and bill listing following no link out of the repository, xfail until built (#1762)`
- **M2:** `BF-959 M2: the convergence scan skips a directory link, and four readers skip a file that resolves outside the repository (#1762)`
- **M3:** `BF-959 M3: trackers and ledger (#1762)`; its body ends with the line `Closes #1762.`

## 6. Tests (`tests/test_bf959_records_readers_containment.py`)

| Id | Test | Cases | Covers | xfail until |
|---|---|---|---|---|
| T1 | `test_the_convergence_scan_reports_nothing_behind_a_directory_link` | 1 | **Seam:** a real link through the public API agrees with `read_entry`: neither leg names, returns (divergence frontmatter included) or reads the file; layer 2 still refuses | M2 |
| T2 | `test_a_file_that_resolves_away_is_skipped_by_each_reader` | 8 | The per-file rule in four readers: outside, and fail closed | M2 |
| T3 | `test_the_statistics_and_the_bill_listing_descend_no_directory_link` | 3 | A real link at a callsign, at a `_SUBDIRS` root, and in `bills` | M2 (Windows; the root case everywhere) |
| T4 | `test_ordinary_directories_are_still_scanned_counted_and_listed` | 2 | Guard: ordinary, and a root that is itself a link | none |

**How each xfail case fails on the base.** Each fails at an `AssertionError`: T1 at `converged["convergence_agents"] == ...` (the two `ValueError` checks before it pass on the base); T2 at its reader's assertion; T3 at the `(total_documents, directories)` assertion.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf959_records_readers_containment.py`:

```python
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
```

### 7.2 M2

**P2-1.** `src/probos/knowledge/records_store.py`
SEARCH:
```
def _markdown_files(search_path: Path, *, strict: bool) -> list[Path]:
    """AD-1341 S4 (A4, A5), BF-958: every file named ``*.md`` under ``search_path`` by a walk that descends no
    directory link; with ``strict``, or the ``OSError`` that hid one.
```
REPLACE:
```
def _contained(path: Path, repo: Path, rel_path: str, reader: str) -> bool:
    """BF-959: whether a reader that lists or reads ``path`` itself may use it: it resolves inside ``repo`` (the
    resolved repository), :func:`_resolves_inside`'s rule. Never raises. A path outside, or in a link loop, is logged
    at WARNING by ``rel_path`` and not used; one whose resolution raises ``OSError`` is logged at DEBUG and not used
    either, as ``list_entries`` skips an unreadable file in its default mode."""
    try:
        inside = _resolves_inside(path, repo)
    except OSError:  # BF-959: a path whose resolution fails is not used, and is no error of the reader
        logger.debug(
            "BF-959: Ship's Records %s skipped %s: its path could not be resolved", reader, rel_path, exc_info=True,
        )
        return False  # BF-959: fail closed
    if not inside:
        logger.warning(
            "BF-959: Ship's Records %s skipped %s: it resolves outside the records repository (a link); "
            "read_entry refuses it too",
            reader, rel_path,
        )
    return inside


def _markdown_files(search_path: Path, *, strict: bool, pattern: str = "*.md") -> list[Path]:
    """AD-1341 S4 (A4, A5), BF-958, BF-959: every file named ``pattern`` (default ``*.md``) under ``search_path`` by a
    walk that descends no directory link; with ``strict``, or the ``OSError`` that hid one.
```

**P2-2.** `src/probos/knowledge/records_store.py`
SEARCH:
```
                elif fnmatch.fnmatch(entry.name, "*.md"):
```
REPLACE:
```
                elif fnmatch.fnmatch(entry.name, pattern):  # BF-959
```

**P2-3.** `src/probos/knowledge/records_store.py`
SEARCH:
```
        for yaml_file in sorted(bills_dir.rglob("*.bill.yaml")):
            rel_path = str(yaml_file.relative_to(root)).replace("\\", "/")
```
REPLACE:
```
        for yaml_file in sorted(_markdown_files(bills_dir, strict=False, pattern="*.bill.yaml")):  # BF-959
            rel_path = str(yaml_file.relative_to(root)).replace("\\", "/")
            if not _contained(yaml_file, root, rel_path, "bill listing"):  # BF-959
                continue
```

**P2-4.** `src/probos/knowledge/records_store.py`
SEARCH:
```
                for md_file in notebook_dir.glob("*.md"):
                    if md_file.name == f"{topic_slug}.md":
                        continue  # Already checked above
                    try:
                        raw = md_file.read_text(encoding="utf-8")
```
REPLACE:
```
                repo = self._repo_path.resolve()  # BF-959: layer 3 compares resolved paths
                for md_file in notebook_dir.glob("*.md"):
                    if md_file.name == f"{topic_slug}.md":
                        continue  # Already checked above
                    try:
                        rel_path = f"notebooks/{callsign}/{md_file.name}"
                        if not _contained(md_file, repo, rel_path, "notebook similarity check"):  # BF-959
                            continue
                        raw = md_file.read_text(encoding="utf-8")
```

**P2-5.** `src/probos/knowledge/records_store.py`
SEARCH:
```
        # Scan other agents' notebook directories
        try:
            for agent_dir in sorted(notebooks_dir.iterdir()):
                if not agent_dir.is_dir():
                    continue
                other_callsign = agent_dir.name
                if other_callsign == anchor_callsign:
                    continue  # Skip self

                # Collect recent entries for this agent
                entries: list[tuple[float, Path, str, str]] = []  # (ts, path, topic, dept)
                for md_file in agent_dir.glob("*.md"):
                    try:
                        raw = md_file.read_text(encoding="utf-8")
```
REPLACE:
```
        # Scan other agents' notebook directories
        try:
            repo = self._repo_path.resolve()  # BF-959: the scan compares resolved paths
            for agent_dir in sorted(notebooks_dir.iterdir()):
                if not agent_dir.is_dir():
                    continue
                other_callsign = agent_dir.name
                if other_callsign == anchor_callsign:
                    continue  # Skip self
                if agent_dir.is_junction() or agent_dir.is_symlink():  # BF-959: a directory link is never scanned
                    logger.warning(
                        "BF-959: Ship's Records convergence scan did not scan notebooks/%s: it is a directory link "
                        "(a junction or a symbolic link), which may lead out of the records repository; the "
                        "notebooks behind it are not read",
                        other_callsign,
                    )
                    continue

                # Collect recent entries for this agent
                entries: list[tuple[float, Path, str, str]] = []  # (ts, path, topic, dept)
                for md_file in agent_dir.glob("*.md"):
                    try:
                        rel_path = f"notebooks/{other_callsign}/{md_file.name}"
                        if not _contained(md_file, repo, rel_path, "convergence scan"):  # BF-959
                            continue
                        raw = md_file.read_text(encoding="utf-8")
```

**P2-6.** `src/probos/knowledge/records_store.py`
SEARCH:
```
        """Get repository statistics."""
        doc_count = sum(1 for _ in self._repo_path.rglob("*.md"))
```
REPLACE:
```
        """Get repository statistics.

        BF-959: one walk of the repository (:func:`_markdown_files`, which descends no directory junction) counts the
        ``*.md`` files that resolve inside it, ``_archived`` included; a file that resolves outside (a link) is logged
        at WARNING and not counted. Each directory's count is taken from that list by the file's first path component.
        """
        repo = self._repo_path.resolve()  # BF-959: the statistics compare resolved paths
        counted: list[Path] = []  # BF-959: the repository-relative path of each file counted
        for md_file in _markdown_files(self._repo_path, strict=False):
            rel = md_file.relative_to(self._repo_path)
            if _contained(md_file, repo, rel.as_posix(), "statistics"):  # BF-959
                counted.append(rel)
        doc_count = len(counted)
```

**P2-7.** `src/probos/knowledge/records_store.py`
SEARCH:
```
            subdir_path = self._repo_path / subdir
            if subdir_path.exists():
                dir_counts[subdir] = sum(1 for _ in subdir_path.rglob("*.md"))
```
REPLACE:
```
            if (self._repo_path / subdir).exists():
                dir_counts[subdir] = sum(1 for p in counted if p.parts[0] == subdir)  # BF-959
```

**N2-1.** `tests/test_bf959_records_readers_containment.py`
SEARCH:
```
_OTHER = "galley menu rotation next week pasta"
_BUILT = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-959 M2 builds it")
_BUILT_ON_WINDOWS = pytest.mark.xfail(
    os.name == "nt", raises=AssertionError, strict=True,
    reason="BF-959 M2 builds it; elsewhere the base's rglob already passes over a directory symbolic link",
)
```
REPLACE:
```
_OTHER = "galley menu rotation next week pasta"
```

**N2-2.** `tests/test_bf959_records_readers_containment.py`
SEARCH:
```
@_BUILT
async def test_the_convergence_scan_reports_nothing_behind_a_directory_link(
```
REPLACE:
```
async def test_the_convergence_scan_reports_nothing_behind_a_directory_link(
```

**N2-3.** `tests/test_bf959_records_readers_containment.py`
SEARCH:
```
@_BUILT
async def test_a_file_that_resolves_away_is_skipped_by_each_reader(
```
REPLACE:
```
async def test_a_file_that_resolves_away_is_skipped_by_each_reader(
```

**N2-4.** `tests/test_bf959_records_readers_containment.py`
SEARCH:
```
    pytest.param("notebooks/alice", {"notebooks": 1, "bills": 0}, marks=_BUILT_ON_WINDOWS, id="callsign"),
    pytest.param("reports", {"notebooks": 1, "bills": 0, "reports": 0}, marks=_BUILT, id="subdirectory-root"),
    pytest.param("bills/linked", {"notebooks": 1, "bills": 0}, marks=_BUILT_ON_WINDOWS, id="bills"),
```
REPLACE:
```
    pytest.param("notebooks/alice", {"notebooks": 1, "bills": 0}, id="callsign"),
    pytest.param("reports", {"notebooks": 1, "bills": 0, "reports": 0}, id="subdirectory-root"),
    pytest.param("bills/linked", {"notebooks": 1, "bills": 0}, id="bills"),
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

**BF-959 (DATE), #1762 -- Ship's Records convergence scan, similarity check, statistics and bill listing follow no directory link out of the repository.**
- **Base.** A directory junction at `notebooks/<callsign>` was scanned by `check_cross_agent_convergence` (its result named the callsign; its divergence leg returned the file's frontmatter), counted by `get_stats` and, in `bills`, listed by `list_bills`; a `*.md` link to an outside file was read by the scan and by the similarity check's cross-topic layer. `read_entry` refuses every such path.
- **Fix.** The scan skips a junction or symbolic link at `notebooks/<callsign>`; it, layer 3, `get_stats` and `list_bills` use a file only if it resolves inside the resolved repository (new `_contained`). `get_stats` and `list_bills` use BF-958's walk (`_markdown_files`, new `pattern` keyword). A file that resolves outside the repository and, in the scan, a junction or symbolic link at `notebooks/<callsign>` are each a WARNING naming the path, once per call; a path whose resolution raises `OSError` is skipped at DEBUG; the shared walk warns for a junction (BF-958) and passes over a directory symbolic link not named `*.md` without a log line (BF-958's L3). Layer 2 of the similarity check is unchanged. Contract `prompts/bf-959-records-readers-containment.md`. Closes #1762.

```

**P3-2.** `DECISIONS.md`. Append after BF-958's entry. Its last bullet occurs once.
SEARCH:
```
- *Reversal.* Revert the BF-958 commits.
```
REPLACE:
```
- *Reversal.* Revert the BF-958 commits.

### BF-959 -- Ship's Records convergence scan, similarity check, statistics and bill listing follow no directory link out of the repository (DATE, #1762)

- *Scope.* `knowledge/records_store.py` (`_contained`, `_markdown_files`' `pattern`, the scan, layer 3, `get_stats`, `list_bills`), tests. Contract `prompts/bf-959-records-readers-containment.md`.
- *G1 (scan).* A junction or symbolic link at `notebooks/<callsign>` is not scanned, wherever it points: one rule with BF-958's walk, and an inside alias would be a second agent; each file passes `_contained` before its first read. Rejected: the per-file rule alone (a WARNING per file), `_resolves_inside` per directory (BF-958 G1), the recursive walk (AD-1140 DD-7).
- *G2 (statistics, bills).* `get_stats` counts in one walk of the repository and takes each directory's count from it, so a `_SUBDIRS` root link is an entry the walk's junction rule catches; `list_bills` uses the same walk with `pattern`. Rejected: two walks, `rglob` filtered afterwards.
- *G3 (signal).* A file that resolves outside the repository and, in the scan, a junction or symbolic link at `notebooks/<callsign>` are WARNINGs by path, once per call; an `OSError` while resolving skips the file at DEBUG (fail closed); `_contained` raises nothing, but `get_stats` raises when the repository's own resolution fails, as `list_entries` does. The shared walk warns for a junction, as BF-958's did, and passes over a directory symbolic link not named `*.md` without a log line (its L3). No deduplication (BF-958 L4).
- *Not changed.* Layer 2 of the similarity check, `read_entry`, `list_entries`, `search`, the result shapes, classification (the scan and layer 3 read every notebook inside the repository by design). *Residual.* L1 to L6 of the contract. *Reversal.* Revert the BF-959 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited (Grep `BF-959` in `docs/development/roadmap.md` finds 0; its section lists only open bugs deliberately not fixed). `docs/architecture/knowledge.md` is not edited: it names `records_store.py` in one table row and describes none of these readers.

## 8. What this does NOT change

- `list_entries`, `_search_records`, `read_entry`, `_safe_path`, any write path; `_resolves_inside`; BF-958's WARNING texts; `_markdown_files` for its two callers.
- Layer 2 of `check_notebook_similarity` (`exact_file`); the result shapes of the four readers.
- Classification: the scan and layer 3 read private notebooks by design (the `write_notebook` docstring, BF-679); this rule is containment only.
- The one-level globs of the scan and layer 3 (AD-1140 DD-7); `seed_manuals`' glob of the packaged source; `_count_record_names` (AD-1358); `records_snapshot.py`. OSS only; no dependency; no configuration field.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/knowledge/records_store.py | `if agent_dir.is_junction() or agent_dir.is_symlink():  # BF-959: a directory link is never scanned` | `if False:` | T1 |
| 2 | M2 | src/probos/knowledge/records_store.py | `if not _contained(md_file, repo, rel_path, "convergence scan"):  # BF-959` | `if False:` | T2[convergence] |
| 3 | M2 | src/probos/knowledge/records_store.py | `if not _contained(md_file, repo, rel_path, "notebook similarity check"):  # BF-959` | `if False:` | T2[similarity] |
| 4 | M2 | src/probos/knowledge/records_store.py | `if _contained(md_file, repo, rel.as_posix(), "statistics"):  # BF-959` | `if True:` | T2[statistics] |
| 5 | M2 | src/probos/knowledge/records_store.py | `if not _contained(yaml_file, root, rel_path, "bill listing"):  # BF-959` | `if False:` | T2[bills] |
| 6 | M2 | src/probos/knowledge/records_store.py | `inside = _resolves_inside(path, repo)` | `inside = True` | T2[outside], all four readers |
| 7 | M2 | src/probos/knowledge/records_store.py | `return False  # BF-959: fail closed` | `return True` | T2[unreadable], all four readers |
| 8 | M2 | src/probos/knowledge/records_store.py | `elif fnmatch.fnmatch(entry.name, pattern):  # BF-959` | `elif fnmatch.fnmatch(entry.name, "*.md"):` | T2[bills], T3[bills], T4 |
| 9 | M2 | src/probos/knowledge/records_store.py | `repo = self._repo_path.resolve()  # BF-959: the scan compares resolved paths` | `repo = self._repo_path` | T4[root-is-a-link] |
| 10 | M2 | src/probos/knowledge/records_store.py | `dir_counts[subdir] = sum(1 for p in counted if p.parts[0] == subdir)  # BF-959` | `dir_counts[subdir] = 0` | T3, T4 |

No campaign of record: this was a read-only consult, so none was run. The Builder runs the 10 mutants once, on M2's head (Windows host). Not tabulated, for the cap of 10: row 1's halves (`is_symlink()` dropped is killed by T1 on Windows, `is_junction()` dropped on POSIX only), and the `repo =` lines of layer 3 and the statistics, the same mutation as row 9 (T4[root-is-a-link] reaches them).

## 10. Recorded limits

- **L1.** A file replaced by a link between the check and a read is read, as in BF-958 L1; the scan's second read of an admitted file is not checked again.
- **L2.** An inside link is not scanned at the scan's callsign directory (a second agent otherwise); an inside `*.md` link is used, as `read_entry` reads it. Layer 3 scans a link at its own callsign directory that resolves inside (layer 2 admits it). No BF-959 test makes a real file link (BF-958's T3a pins `_resolves_inside` against one, on hosts with the privilege) or a real `notebooks` root link.
- **L3.** The WARNINGs repeat per path per call and nothing deduplicates (BF-958 L4); behind a `notebooks` root link, one per file. Volume is not measured.
- **L4.** A transient `OSError` from `resolve()` leaves a legitimate file out of that call's result (DEBUG).
- **L5.** `directories` takes a file's first path component as it is on disk: on a case-insensitive host, a `_SUBDIRS` directory of another case counts in `total_documents` and not in `directories`. The store creates these names in lower case (`initialize`, `:608`).
- **L6.** The walk and one `resolve()` per file run on the event loop (BF-958 L7). Measured on a read-only checkout of this repository (Windows, CPython 3.12.13, `docs/`: 127 files, median of 5), the count took 1.2 ms with `rglob` twice and 25 ms with the walk and `resolve()`. Measured on the live vessel's records (read-only, 2026-11-08, by the orchestrator: 2,776 `*.md` files, 2,770 of them notebooks, no link among them), the walk took 32 ms and the `resolve()` calls 0.64 s (0.23 ms a file), against 0.1 s for `rglob` twice: `get_stats` takes about 0.7 s where it took about 0.1 s. In the scan, `resolve()` and the comparison cost 0.39 to 0.60 s a pass over the 2,769 notebooks it reads (the scan's own read and parse cost 1.7 to 2.2 s a pass, warm cache; `Path.is_symlink()` would cost 0.07 to 0.10 s). The cost is accepted as BF-958 accepted it for `list_entries`: one rule for every reader, no second path to keep equal. A directory named `*.md` or `*.bill.yaml` is no longer counted or listed (`rglob` returned one).

## 11. Verified Against Codebase (2026-11-08, reading tree `D:\ProbOS-worktrees\bf959-base` at `98d0d99b`)

```
Read: records_store.py :394-440, :496-575, :896-1352, :1354-1440, :1576-1603, :1675-1686; proactive.py :3220-3510, :3931-3990, :4395-4440; publish_finding_tool.py :118-135, :640-700, :745-775; routers/records.py :1-40; the BF-958, BF-949, BF-952, AD-554 and records-store tests; CPython 3.12.13 pathlib.py :45-54, :160-250, :905-935 and ntpath.py :284-290; pyproject.toml (requires-python ">=3.12", asyncio_mode "auto")
Grep "_contained|\bpattern\b" records_store.py -> 0 (no collision: test_records_store.py:425 fails on a duplicate `def` name). Grep "_markdown_files|_resolves_inside" src -> the walk's callers are records_store.py:413 and :1418 only
Grep architecture-baseline.yaml -> :751 RecordsStore is a frozen srp-size row (triggers, not counts); no method, import, subprocess, egress or write call is added
Anchors: a script counted each SEARCH on the LF-normalised text of its file at 98d0d99b (once each), applied the pairs in label order in memory and parsed the results with ast
```

**Run by the Architect, read-only and in memory (no pytest, nothing written; the installed `probos` is another commit, so the patched source ran with its two top-level imports stubbed):**

```
get_stats against the old rglob counts on five read-only trees of this checkout (config, docs, prompts, src/probos/agents, tests/fixtures; 0 to 1,877 files; config gives directories {'manuals': 3}): totals and directories equal in all five. _markdown_files(..., pattern=...) equals rglob over files for four (root, pattern) pairs
A Path patch over a virtual file system (a fake root that does not exist) ran the scan and layer 3: T1's junction at a callsign and a notebooks root that is a link, T2 (outside, unreadable) and T4 pass on the patched source (an inside link at a callsign is not scanned; an unreadable file is skipped without a WARNING); on the unpatched base the same scenarios give agents ['alice','bob','dave'], the outsider's frontmatter, the outside file read, and a layer 3 suppress
```

**Absence Verified (2026-11-08)**

```
CLAIM: the scan's only caller in src is proactive.py:3396; layer 3's callers are proactive.py:3245, :4403 and publish_finding_tool.py:765
RUN:   Grep "check_cross_agent_convergence|check_notebook_similarity" over src
FOUND: those four call sites, the two definitions in records_store.py, and comment or docstring mentions (publish_finding_tool.py:127, :128, :257, :282)
HOLDS: yes

CLAIM: nothing in src calls list_bills, and get_stats has one consumer (routers/records.py:35) with no client in ui/src
RUN:   Grep "list_bills" over src, tests, scripts, ui/src, config, docs; Grep "records/stats|get_records_stats|records_store\.get_stats" over those and desktop; Grep "\.get_stats\(\)" over src
FOUND: list_bills: the definition (records_store.py:976) and tests only; get_stats: routers/records.py:31 and :35 (the other .get_stats() receivers are episodic_memory, ward_room, task_scheduler, cognitive_journal)
HOLDS: yes

CLAIM: no test that patches os.scandir, Path.glob/rglob/iterdir/resolve/read_text names a BF-959 reader
RUN:   PowerShell: Select-String over tests\*.py for those patches (13 files) and for check_cross_agent_convergence|check_notebook_similarity|.list_bills(|.get_stats( (22 files), Compare-Object -IncludeEqual -ExcludeDifferent; Select-String RecordsStore|records_store in test_bf953_read_floor_spellings.py and test_ad1270f_codebase_index_memo.py
FOUND: the intersection is empty; 0 matches in the two files (:1432 patches Path.glob for ListFilesTool; ad1270f:133 patches Path.rglob for the codebase index). BF-952's test wraps _markdown_files with *args, **kwargs (:337); AD-1341 S4's and BF-958's tests call it with strict= only
HOLDS: yes

CLAIM: no AD-1346 census row or ledger line can change from the source edits
RUN:   Grep records_store.py for the scan's write names (".(write_text|write_bytes|unlink|rmtree|copy2|copyfile|copytree|replace|rename|fdopen|write_new|publish_file|remove_file)(", "open(", os.replace|rename|remove|link|write, shutil.copy|move); Grep "records_store.py" in tests/; git log -- tests/fixtures/ad1346_file_write_census.py; git show --stat 8eeb542c; the same pattern over this contract's REPLACE blocks (a script)
FOUND: write points at :743 :852 :863 :965 :1503 :1631 :1702 and open("a") at :1655, none in a BF-959 region; the three .replace("\\", "/") (:414, :993, :1421) take two arguments, which the scan does not count (WF2). Rows naming the file: ad1346_file_write_census.py:146, :159 (file; scope RecordsStore.write_entry), ad1346_effect_census.py:143 and test_bf892_spawn_env_guard.py:101 (scope RecordsStore._git_sync), test_layer_boundaries.py:88, :92 (allowed imports); WF1 counts points by name over src, not by line. BF-958's M2 (8eeb542c) changed 5 files, none a census file. The REPLACE blocks add none of those names. The ledger reads PROGRESS.md and DECISIONS.md live (gen_ad_ledger.py): only M3 changes it (G3)
HOLDS: yes

CLAIM: no BF-959 row, document or tracker entry exists to edit besides M3's
RUN:   git log --all subjects; ls prompts/bf-959*; Select-String BF-959 in PROGRESS.md, DECISIONS.md, roadmap.md; Grep docs/**/*.md "check_cross_agent_convergence|check_notebook_similarity|list_bills|RecordsStore\.get_stats|_markdown_files|records/stats"; Grep knowledge.md "records_store|get_stats|list_bills|convergence"; Grep roadmap.md "BF-9[0-9][0-9]"
FOUND: BF-959: 0 everywhere. docs: roadmap-era-5-completed.md:2563 and :4448 (history of AD-554, AD-583); knowledge.md:61 (a table row naming the file). roadmap.md: one hit, AD-753's row naming BF-927; its Bug Tracker (:1131) holds BF-682 and BF-683 only
HOLDS: yes
```

**Not measured by the Architect:** the orchestrator's probe facts (cited from `probe-main-98d0d99b.txt`); a directory symlink at a callsign on POSIX; a real file link; the G1 and G2 counts and the 10 mutants (by reading, not run); the WARNING volume; that the store creates no links (cited from #1762).

## 12. Prior Art and Blind Spots

- **Internal: adopted.** BF-958's walk (`_markdown_files`, its junction row) and `_resolves_inside`; `list_entries`' default-mode disposition of an `OSError` in a per-file step (skipped at DEBUG).
- **Internal: rejected.** BF-958 G1's per-directory resolution (duplicates); AD-1341 S6's refusal of every file link (BF-958 section 12 rejected it too); the recursive walk for the scan (AD-1140 DD-7).
- **External:** none consulted (BF-958 section 12 holds the sources; no new question arose). `reference-projects.md`: not examined.
- **Blind spots handled.** A relocated root and ordinary directories (T4); an unresolvable path (T2); the divergence frontmatter and a junction callsign at layer 2 (T1); a `_SUBDIRS` root link (T3).
- **What discards a correct result.** `_contained` returning False for an inside file: a `repo` that is not resolved (T4, row 9), an `OSError` (L4); an inside link directory (L2); the bucketing (L5). **Recorded:** L1 to L6.

## 13. Diff Reviewer: properties to verify

1. In the scan and in layer 3, `read_text` runs only after `_contained(md_file, repo, ...)` is true for that path; `entries` holds only admitted paths, and the second loop reads only those.
2. The scan evaluates `agent_dir.is_junction() or agent_dir.is_symlink()` after the self-skip and before any `glob` of that directory, inside the existing `try`.
3. `match_info` (`content`, `frontmatter`) exists only for admitted files. Trace `convergence_matches` to `_write_convergence_report` (`proactive.py:3948-3957`) and to `check_realtime_convergence`: the shapes are unchanged; the consumers receive fewer matches.
4. Layer 2 of `check_notebook_similarity`, layer 3's `matched_path` and the result shapes are byte-unchanged; `list_bills` still returns `{"path", "bill_id"}` items, and `_safe_path("bills")` keeps its `ValueError`.
5. `get_stats` returns the same four keys; the `directories` loop and the git block are as they were but for the count expression; `_archived` counts in the total.
6. `_markdown_files` called without `pattern` returns what it returned and raises where it raised; `list_entries` and `_search_records` are byte-unchanged. No `.rglob(` remains in `records_store.py`.
7. `_contained` never raises; each message names `rel_path` and logs no file content; every BF-959 message begins `BF-959:`.
8. Every test link is removed in a `finally` by `rmdir` (junction) or `unlink` (symlink), never its target; the file has no skip; at M1 on Windows each xfail case fails at an `AssertionError`.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **A junction (Windows) or symlink (POSIX) at `notebooks/<callsign>` leading outside:** the convergence scan names, returns (frontmatter included) and reads nothing from it; `get_stats` counts nothing from it; a WARNING names the skipped path (T1, T3).
- **A `*.md` file that resolves outside, in a notebook directory:** skipped by the scan, by layer 3 and by `get_stats`, and a `*.bill.yaml` by `list_bills` (T2, on every platform). Layer 2 still raises `ValueError` for a junction callsign (T1).
- **No regressions:** ordinary directories, a root that is itself a link, AD-550, AD-554, AD-583, BF-949, BF-952, BF-958 and AD-1341 S4 behave as before (T4, G2).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
