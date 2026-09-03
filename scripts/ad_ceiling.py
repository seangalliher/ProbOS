"""Print the true next AD number, enumerated from all three authoritative sources.

Why this exists (2026-08-29): an AD was allocated from `git log` subjects and
`prompts/ad-*.md` alone, which both capped at AD-1285. Epic #1332's children
held AD-1286..1290 in *unbuilt GitHub issue titles* -- invisible to git log,
because an allocated-but-unbuilt AD has no commit. Two ADs were double-allocated
and the epic had to be renumbered.

The design property that matters: **a source that fails to run must never be
mistaken for a source that found nothing.** A failed `gh` call and a repository
with no AD issues both produce an empty list, and those two must not be
indistinguishable -- that is the same confusion the repo's evidence standard
calls out for absence claims. So every source reports OK/FAILED separately, and
the script exits non-zero when any source could not be consulted.

Also encoded: `gh issue list --limit 400` silently returns exactly 400 rather
than erroring, so the fetch uses a large limit and asserts the returned count is
below it.

Usage:
    python scripts/ad_ceiling.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# A trailing `\b` loses every suffixed token: there is no word boundary between
# the digits and the suffix, so `AD-722b` and `AD-1270e2` matched nothing at all
# and their base number went unseen. A slice never allocates a new number, so
# capture the base and ignore the suffix; the negative lookahead keeps a long
# number from matching a truncated prefix.
_AD_RE = re.compile(r"\bAD-(\d{1,5})(?!\d)", re.IGNORECASE)
_PROMPT_RE = re.compile(r"^ad-(\d{1,5})(?!\d)", re.IGNORECASE)
_GH_LIMIT = 4000

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=_REPO_ROOT, capture_output=True, timeout=180,
            # Not text=True: on Windows that decodes as cp1252 and commit
            # subjects in this repo contain em-dashes, which raises mid-read.
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:400]
    return True, proc.stdout or ""


def from_git_log() -> tuple[bool, int, str]:
    ok, out = _run(["git", "log", "--all", "--format=%s"])
    if not ok:
        return False, 0, out
    nums = [int(m) for line in out.splitlines() for m in _AD_RE.findall(line)]
    return True, max(nums, default=0), f"{len(nums)} AD refs in commit subjects"


def from_prompts() -> tuple[bool, int, str]:
    d = _REPO_ROOT / "prompts"
    if not d.is_dir():
        return False, 0, f"{d} is not a directory"
    nums = [
        int(m.group(1))
        for p in d.glob("ad-*.md")
        if (m := _PROMPT_RE.match(p.name))
    ]
    return True, max(nums, default=0), f"{len(nums)} ad-*.md prompt files"


def from_github_issues() -> tuple[bool, int, str]:
    """Issue titles in ALL states -- the only place an unbuilt AD lives."""
    ok, out = _run([
        "gh", "issue", "list",
        "--state", "all", "--limit", str(_GH_LIMIT),
        "--json", "number,title",
    ])
    if not ok:
        return False, 0, f"gh failed: {out}"
    try:
        issues = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        return False, 0, f"unparseable gh output: {exc}"
    if len(issues) >= _GH_LIMIT:
        return False, 0, (
            f"returned exactly {len(issues)} == --limit; result is TRUNCATED "
            f"and the ceiling would be understated. Raise _GH_LIMIT."
        )
    nums = [int(m) for i in issues for m in _AD_RE.findall(i.get("title") or "")]
    return True, max(nums, default=0), (
        f"{len(issues)} issues (limit {_GH_LIMIT}, not truncated), "
        f"{len(nums)} AD-titled"
    )


def main() -> int:
    sources = {
        "git log --all subjects": from_git_log(),
        "GitHub issue titles (all states)": from_github_issues(),
        "prompts/ad-*.md filenames": from_prompts(),
    }

    width = max(len(n) for n in sources)
    print("AD ceiling, enumerated from three sources\n")
    for name, (ok, ceiling, detail) in sources.items():
        status = f"AD-{ceiling}" if ok else "FAILED"
        print(f"  {name:<{width}}  {status:>9}   {detail}")

    failed = [n for n, (ok, _, _) in sources.items() if not ok]
    consulted = {n: c for n, (ok, c, _) in sources.items() if ok}

    if failed:
        print(
            "\nCOULD NOT CONSULT: " + "; ".join(failed) +
            "\nRefusing to report a ceiling. A source that did not run is not a "
            "source that found nothing -- allocating from the remainder is "
            "exactly how AD-1284/1285 were double-allocated."
        )
        return 1

    ceiling = max(consulted.values())
    winners = [n for n, c in consulted.items() if c == ceiling]
    print(f"\nCEILING: AD-{ceiling}   (from: {', '.join(winners)})")
    print(f"NEXT:    AD-{ceiling + 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
