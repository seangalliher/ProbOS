"""BF #423: tests for ``KnowledgeStore`` git-recovery branches.

Covers the four-tier recovery path added by this week's BFs (a96a774,
23ae043, e272533):

    1. Corrupt ``.git/index`` -> rebuilt via ``git read-tree HEAD``.
    2. Broken HEAD ref ("cannot lock ref") -> recovered via reflog +
       ``git update-ref``.
    3. Truncated branch ref where ``logs/refs/heads/<branch>`` parse
       provides the last-good sha.
    4. Branch ref + branch reflog gone, but ``logs/HEAD`` retains a
       parseable last-good sha.
    5. All reflogs missing -> ``git fsck --lost-found`` fallback.

These hit ``KnowledgeStore._git_commit`` and
``KnowledgeStore._recover_last_commit_sha`` directly with a real
on-disk git repo (no monkeypatching of subprocess).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from probos.config import KnowledgeConfig
from probos.knowledge.store import KnowledgeStore

requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )


@pytest.fixture
def store_with_history(tmp_path: Path) -> KnowledgeStore:
    """A KnowledgeStore with a git repo holding two real commits.

    Auto-commit is on but debounce is large so we drive ``_git_commit``
    directly from the tests rather than racing with the timer.
    """
    repo = tmp_path / "knowledge"
    cfg = KnowledgeConfig(
        enabled=True,
        repo_path=str(repo),
        auto_commit=True,
        commit_debounce_seconds=10.0,
    )
    store = KnowledgeStore(cfg)

    async def _seed() -> None:
        await store.initialize()
        # Force one real commit so HEAD + reflog have content.
        await store._ensure_repo()
        (repo / "qa" / "seed.json").write_text('{"k": 1}', encoding="utf-8")
        await store._git_commit("seed-1")
        (repo / "qa" / "seed.json").write_text('{"k": 2}', encoding="utf-8")
        await store._git_commit("seed-2")

    asyncio.run(_seed())
    return store


def _branch_ref(repo: Path) -> Path:
    """Return whichever of master/main exists for this repo."""
    for name in ("master", "main"):
        p = repo / ".git" / "refs" / "heads" / name
        if p.is_file():
            return p
    raise RuntimeError("no branch ref present")


# ---------------------------------------------------------------------------
# Tier 1 — corrupt index
# ---------------------------------------------------------------------------


@requires_git
def test_recovers_from_corrupt_index(store_with_history: KnowledgeStore) -> None:
    """A garbage ``.git/index`` (wrong magic) triggers rebuild from HEAD.

    The recovery branch keys on stderr containing ``"index file corrupt"``.
    Git emits that exact message when the index has the right size but a
    bad magic header / checksum, so we write 4KB of random-ish bytes
    (NOT zero-length, which produces "smaller than expected" instead).
    """
    repo = store_with_history.repo_path
    idx = repo / ".git" / "index"
    idx.write_bytes(b"\xab\xcd\xef\x99" * 1024)  # garbage with valid size
    (repo / "qa" / "after.json").write_text('{"x": 1}', encoding="utf-8")

    asyncio.run(store_with_history._git_commit("after-corrupt-index"))

    log = _git(repo, "log", "--oneline")
    assert log.returncode == 0
    # Commit landed
    assert "after-corrupt-index" in log.stdout


# ---------------------------------------------------------------------------
# Tier 2 — broken HEAD ref recovered via standard reflog
# ---------------------------------------------------------------------------


@requires_git
def test_recovers_from_broken_branch_ref_via_reflog(store_with_history: KnowledgeStore) -> None:
    """Truncate the branch ref but leave the standard reflog intact.

    Recovery rewrites the ref via ``git update-ref`` and the next commit
    succeeds.
    """
    repo = store_with_history.repo_path
    ref = _branch_ref(repo)
    # Capture good sha before we trash the ref
    expected_sha = ref.read_text(encoding="utf-8").strip()
    assert len(expected_sha) == 40
    ref.write_bytes(b"")  # zero-length -> "cannot lock ref"

    (repo / "qa" / "post.json").write_text('{"x": 2}', encoding="utf-8")
    asyncio.run(store_with_history._git_commit("after-broken-ref"))

    # Ref healed
    new_sha = ref.read_text(encoding="utf-8").strip()
    assert len(new_sha) == 40
    log = _git(repo, "log", "--oneline")
    assert log.returncode == 0
    assert "after-broken-ref" in log.stdout


# ---------------------------------------------------------------------------
# Tier 3 — branch reflog file parse only
# ---------------------------------------------------------------------------


@requires_git
def test_recover_sha_falls_back_to_branch_reflog_file(store_with_history: KnowledgeStore) -> None:
    """When ``git reflog`` cannot resolve HEAD, branch reflog file is parsed.

    We simulate the ``git reflog`` failure by zeroing HEAD and the branch
    ref simultaneously; the parser must still find a valid sha in
    ``logs/refs/heads/<branch>``.
    """
    repo = store_with_history.repo_path
    git_dir = repo / ".git"
    head = git_dir / "HEAD"
    branch = _branch_ref(repo)
    branch.write_bytes(b"")
    head.write_text("ref: refs/heads/zzz_does_not_exist\n", encoding="utf-8")
    # Sanity: standard reflog command should now fail.
    rl = _git(repo, "reflog", "--format=%H", "-n", "1")
    assert rl.returncode != 0 or not rl.stdout.strip()

    sha = asyncio.run(store_with_history._recover_last_commit_sha())
    assert sha is not None and len(sha) == 40


# ---------------------------------------------------------------------------
# Tier 4 — only ``logs/HEAD`` survives
# ---------------------------------------------------------------------------


@requires_git
def test_recover_sha_falls_back_to_logs_head(store_with_history: KnowledgeStore) -> None:
    """Branch reflog deleted; ``logs/HEAD`` still resolves a sha."""
    repo = store_with_history.repo_path
    git_dir = repo / ".git"
    branch = _branch_ref(repo)
    branch.write_bytes(b"")
    # Wipe per-branch reflogs but keep logs/HEAD
    for rel in ("logs/refs/heads/master", "logs/refs/heads/main"):
        p = git_dir / rel
        if p.is_file():
            p.unlink()
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/zzz_does_not_exist\n", encoding="utf-8")

    sha = asyncio.run(store_with_history._recover_last_commit_sha())
    assert sha is not None and len(sha) == 40


# ---------------------------------------------------------------------------
# Tier 5 — fsck fallback when all reflogs gone
# ---------------------------------------------------------------------------


@requires_git
def test_recover_sha_falls_back_to_fsck_when_reflogs_missing(
    store_with_history: KnowledgeStore,
) -> None:
    """All reflog sources gone -> ``git fsck --lost-found`` returns a dangling commit."""
    repo = store_with_history.repo_path
    git_dir = repo / ".git"
    branch = _branch_ref(repo)
    branch.write_bytes(b"")
    for rel in ("logs/refs/heads/master", "logs/refs/heads/main", "logs/HEAD"):
        p = git_dir / rel
        if p.is_file():
            p.unlink()
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/zzz_does_not_exist\n", encoding="utf-8")

    sha = asyncio.run(store_with_history._recover_last_commit_sha())
    # fsck should still find dangling commits from the original two commits
    assert sha is not None and len(sha) == 40


# ---------------------------------------------------------------------------
# Defensive: git_commit must never raise even on unrecoverable damage
# ---------------------------------------------------------------------------


@requires_git
def test_git_commit_unrecoverable_logs_and_returns(
    store_with_history: KnowledgeStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Wipe HEAD, branch refs, all reflogs, and the object DB. Commit must
    not raise — it logs the failure and returns cleanly so callers degrade.
    """
    import logging
    repo = store_with_history.repo_path
    git_dir = repo / ".git"
    # Nuke everything that could yield a sha
    for rel in (
        "HEAD", "refs/heads/master", "refs/heads/main",
        "logs/refs/heads/master", "logs/refs/heads/main", "logs/HEAD",
    ):
        p = git_dir / rel
        if p.is_file():
            p.unlink()
    objs = git_dir / "objects"
    if objs.is_dir():
        # Windows: pack/loose objects may be locked by an ongoing git op;
        # ignore_errors keeps the corruption simulation best-effort. The
        # assertion below only requires that ``_git_commit`` does not raise.
        shutil.rmtree(objs, ignore_errors=True)
        objs.mkdir(exist_ok=True)

    (repo / "qa" / "ghost.json").write_text('{"x": 3}', encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        # Must not raise.
        asyncio.run(store_with_history._git_commit("after-total-corruption"))
