"""BF-957: is Ship's Records' git history still growing?

Three readings of the records repository: an ``index.lock`` at least ``records.git_lock_stale_minutes`` old
(FAIL: every git add and commit fails while it remains), more uncommitted paths than
``records.git_uncommitted_warn_paths`` (WARN), and a last commit at least ``records.git_last_commit_warn_hours``
old while uncommitted paths exist (WARN).

The check writes nothing and takes no lock. The lock is read with ``stat``, and both git commands run with
``GIT_OPTIONAL_LOCKS=0``, so ``git status`` does not refresh the index, and with ``HARDENED_GIT_CONFIG_ARGS``
(BF-904a), so no repository hook or fsmonitor runs: optional locks do not stop a configured fsmonitor, which may
write. It removes nothing either: removing a lock stays the operator's decision once no git process uses the
repository.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from probos.config import resolve_records_repo_path
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS, trusted_command_env

#: Seconds each read-only git command may take. Stopping one holds no lock: optional locks are off.
_GIT_READ_TIMEOUT_S = 15.0
_RANK = {CheckOutcome.OK: 0, CheckOutcome.WARN: 1, CheckOutcome.FAIL: 2}
_HEADLINE = {
    CheckOutcome.OK: "Ship's Records git: history is being kept",
    CheckOutcome.WARN: "Ship's Records git: needs attention",
    CheckOutcome.FAIL: "Ship's Records git: history has stopped",
}

_Part = tuple[CheckOutcome, str, str]  # (outcome, detail line, remediation)


def _git_read_sync(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One read-only git command in ``repo``: optional locks off, and no repository hook or fsmonitor runs."""
    return subprocess.run(
        ["git", *HARDENED_GIT_CONFIG_ARGS, "-C", str(repo), *args],  # BF-957 A3: optional locks do not stop an fsmonitor
        env={**trusted_command_env(), "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=_GIT_READ_TIMEOUT_S,
    )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return "(no output)"


def _lock_part(repo: Path, git_dir: Path, records: Any) -> _Part:
    lock = git_dir / "index.lock"
    try:
        modified = lock.stat().st_mtime
    except FileNotFoundError:
        return CheckOutcome.OK, "index.lock: none", ""
    except OSError as exc:
        return CheckOutcome.WARN, f"index.lock: could not be read ({type(exc).__name__})", ""
    age_min = max(0.0, (time.time() - modified) / 60.0)
    if age_min >= records.git_lock_stale_minutes:
        return (
            CheckOutcome.FAIL,
            f"index.lock: present for {age_min:.0f} min (threshold {records.git_lock_stale_minutes:g} min); "
            "every git add and commit of Ship's Records fails while it remains",
            f"A git process that ended without cleaning up leaves {lock}. With the vessel stopped and no git "
            f"process using {repo}, back up {git_dir}; removing the lock file and committing the pending records "
            "are then the operator's decision. ProbOS does not remove it.",
        )
    return (
        CheckOutcome.OK,
        f"index.lock: present for {age_min:.0f} min, under the {records.git_lock_stale_minutes:g} min threshold "
        "(a git command may be running)",
        "",
    )


def _git_parts(repo: Path, records: Any) -> list[_Part]:
    if shutil.which("git") is None:
        return [(CheckOutcome.WARN, "git: not found on PATH; uncommitted paths and the last commit were not read", "")]
    try:
        status = _git_read_sync(repo, "status", "--porcelain", "--untracked-files=all", "--no-renames", "-z")
        last = _git_read_sync(repo, "log", "-1", "--format=%ct")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [(CheckOutcome.WARN, f"git: could not read the repository ({type(exc).__name__})", "")]
    if status.returncode != 0:
        return [(CheckOutcome.WARN, f"git status failed (exit {status.returncode}): {_first_line(status.stderr)}", "")]
    parts: list[_Part] = []
    pending = sum(1 for entry in status.stdout.split("\0") if entry)
    if pending > records.git_uncommitted_warn_paths:
        parts.append((
            CheckOutcome.WARN,
            f"uncommitted: {pending} path(s), over the bound of {records.git_uncommitted_warn_paths}",
            "Uncommitted records are not in the records history. The vessel's log names each git failure "
            "('Ship's Records: git ...').",
        ))
    else:
        parts.append((CheckOutcome.OK, f"uncommitted: {pending} path(s)", ""))
    try:
        committed = int(last.stdout.strip()) if last.returncode == 0 else None
    except ValueError:
        committed = None
    if committed is None:
        parts.append((CheckOutcome.WARN, f"last commit: not read (exit {last.returncode}: {_first_line(last.stderr)})", ""))
        return parts
    age_h = max(0.0, (time.time() - committed) / 3600.0)
    if pending and age_h >= records.git_last_commit_warn_hours:
        parts.append((
            CheckOutcome.WARN,
            f"last commit: {age_h:.1f} h ago with {pending} uncommitted path(s) "
            f"(threshold {records.git_last_commit_warn_hours:g} h)",
            "",
        ))
    else:
        parts.append((CheckOutcome.OK, f"last commit: {age_h:.1f} h ago", ""))
    return parts


def _inspect(repo: Path, git_dir: Path, records: Any) -> CheckResult:
    parts = [_lock_part(repo, git_dir, records), *_git_parts(repo, records)]
    worst = max((outcome for outcome, _, _ in parts), key=_RANK.__getitem__)
    return CheckResult(
        outcome=worst,
        message=f"{_HEADLINE[worst]} ({repo})",
        remediation=" ".join(text for _, _, text in parts if text),
        detail="\n".join(line for _, line, _ in parts),
    )


@dataclass(frozen=True)
class _RecordsGitCheck:
    name: str = "records_git"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        records = getattr(ctx.config, "records", None) if ctx.config is not None else None
        if records is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Ship's Records git: not checked, because the configuration did not load",
            )
        if not records.enabled:
            return CheckResult(outcome=CheckOutcome.OK, message="Ship's Records git: records are disabled in config")
        if not records.auto_commit:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Ship's Records git: auto_commit is off, so ProbOS keeps no records history to check",
            )
        repo = resolve_records_repo_path(records, ctx.data_dir)
        if not repo.exists() and not repo.is_symlink():
            return CheckResult(
                outcome=CheckOutcome.OK,
                message=f"Ship's Records git: {repo} does not exist yet; it is created when the vessel starts",
            )
        if not repo.is_dir():
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Ship's Records git: {repo} exists and is not a directory, so Ship's Records cannot start",
                remediation="records.repo_path must name a directory, or a path that does not exist yet, which "
                "ProbOS creates when the vessel starts.",
            )
        git_dir = repo / ".git"
        if not git_dir.is_dir():
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message=f"Ship's Records git: {repo} is not a git repository, so records have no history",
                remediation="Ship's Records initialises the repository when the vessel starts.",
            )
        return await asyncio.to_thread(_inspect, repo, git_dir, records)


register_check(_RecordsGitCheck())
