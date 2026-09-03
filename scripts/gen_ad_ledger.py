"""Generate the reconciled AD/BF lifecycle ledger from the live authorities.

The ledger is generated rather than hand-written because the thing it has to
get right cannot be seen by reading the working tree. AD and BF numbers are
minted by audits and reviews that **file a GitHub issue before any code
exists**, so a recursive tree scan reports a ceiling that is already too low
and reports intentionally-allocated numbers as if they were free. The scan that
preceded this generator said AD-1180 / BF-706; four more numbers had been filed
as issues by then, and AD-1152 -- open, titled, unretired -- was being read as
the "next free" number by three local trackers at once.

**This generator observes the ledger. It does not correct it.** Nothing here
renumbers, retires or rewrites an entry. Disagreements between the authorities
are reported in the artifact so a human can decide, because a generator that
silently "fixes" an append-only history is a worse defect than the drift.

Four authorities, two of them pinned::

    git log commit subjects        pinned snapshot   (see below)
    DECISIONS.md + decisions-era-* live, every run
    PROGRESS.md  + progress-era-*  live, every run
    gh issue list --state all      pinned snapshot   (network)

Usage::

    python scripts/gen_ad_ledger.py            # write, refreshing the git layer
    python scripts/gen_ad_ledger.py --online   # ...and refresh the issue layer
    python scripts/gen_ad_ledger.py --check    # fail if stale (test/CI)

``--check`` is what ``tests/test_ad1184_ad_ledger.py`` runs, so editing
DECISIONS.md or PROGRESS.md without regenerating turns the suite red instead of
silently publishing a stale ledger.

Why the git layer is pinned rather than recomputed in ``--check``
----------------------------------------------------------------

Two measured reasons, both of which would make the gate red for a reason
unrelated to the code -- the exact failure this repo already ate three times
over a ``pathlib`` repr in the config reference:

1. **Self-invalidation.** 1843 of 2215 commit subjects begin with ``AD-NNNN:``
   or ``BF-NNN:``. The commit that lands this artifact necessarily names its own
   AD, which flips that row from ``allocated-open`` to ``shipped`` -- so the
   artifact is stale the instant it is committed, and stays permanently red.
2. **Shallow clones.** ``actions/checkout@v4`` defaults to ``fetch-depth: 1``
   and ci.yml does not override it, so ``git log`` yields a single subject in
   CI and thousands locally. A byte-exact check over that is red by
   construction on one of the two.

So ``git`` and ``gh`` are both captured into
``docs/development/ad-ledger-snapshot.json`` with the timestamp and the commit
they were taken at. ``--check`` re-renders from that pinned snapshot plus a
fresh parse of the two file authorities and compares bytes. It runs **no
subprocess and opens no socket** -- which is asserted, not assumed, in the
tests. The drift that matters is still caught, because this repo's convention
requires DECISIONS.md and PROGRESS.md to record every AD.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _REPO_ROOT / "docs" / "development" / "open-ads-report.md"
_SNAPSHOT = _REPO_ROOT / "docs" / "development" / "ad-ledger-snapshot.json"

_GH_REPO = "seangalliher/ProbOS"

# Written into the file so a reader who lands on it from search knows it is
# generated and where to change it.
_HEADER = """# ProbOS — Reconciled AD/BF Ledger

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_ad_ledger.py` (add `--online` to refresh the
GitHub issue layer). The generator is `scripts/gen_ad_ledger.py`; the pinned
snapshot is `docs/development/ad-ledger-snapshot.json`.

This replaces a hand-made 2026-03-31 snapshot that had been stale for months.

**Read the ceiling here, not from a tree scan.** AD and BF numbers are minted by
audits and reviews that file a GitHub issue *before* any code exists. A
recursive scan of the working tree therefore reports a ceiling that is already
too low, and reports intentionally-allocated numbers as free. That is how
collisions happen.

**No number below the ceiling is free merely because this file does not account
for it.** Gaps are listed as *unaccounted*, which means the four authorities are
silent — not that the number may be reused. Refresh the issue layer and check
`gh issue list --search "AD-NNNN in:title" --state all` before minting.

This file **observes** the ledger. It does not correct it: nothing is renumbered
or retired here, and disagreements between the authorities are reported below
rather than resolved.
"""

# A number token. Sub-slices (AD-574b, BF-688a, AD-1270e2) are children of the
# base number -- the base is what a future build must not reuse, so
# classification keys on the integer and keeps the full token as evidence.
# The suffix admits a trailing digit because the roadmap already names slices
# that way (e1, e2, c3, d3); without it the whole token failed to match at all
# and such a slice was invisible rather than mis-parsed.
# A non-empty suffix MUST start with a letter. A digit-only suffix would read
# AD-123456 as AD-12345 slice "6", conflating two distinct numbers -- and
# ad_ceiling rejects that token outright, so the two tools would disagree.
_TOKEN_RE = re.compile(r"\b(AD|BF)-(\d{1,5})((?:[a-z]{1,3}\d{0,2})?)\b")

# Text permitted *between* two head tokens for both to count as the head of the
# same entry: "AD-661b + AD-661c v1", "BF-688 / BF-688a", "**AD-1154 ".
_CONNECTOR_RE = re.compile(
    r"^(?:[\s*#>_.,:;+/&()\[\]|-]|and\b|plus\b|v\d+\b)*$", re.IGNORECASE
)

# Markup that can precede the first head token on a line.
_LEADING_MARKUP_RE = re.compile(r"^[\s*#>_`\[\]|-]*")

# First status keyword by position in the head window wins. Ordered longest and
# most specific first only for readability; selection is by match position.
_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("retired", re.compile(r"\b(?:RETIRED|ABANDONED|WITHDRAWN)\b", re.IGNORECASE)),
    ("superseded", re.compile(r"\bSUPERSEDED\b", re.IGNORECASE)),
    ("deferred", re.compile(r"\b(?:DEFERRED|POSTPONED)\b", re.IGNORECASE)),
    ("shipped", re.compile(r"\b(?:CLOSED|SHIPPED|STAGED|LANDED)\b", re.IGNORECASE)),
    ("allocated-open", re.compile(r"\bOPEN\b", re.IGNORECASE)),
)

# How much of an entry-head line is treated as its head. Bodies in this repo run
# to 10,000 characters and mention every AD they defer to; a status keyword
# found there belongs to a different number. Every real head in these files puts
# its verdict inside 40 characters (`**AD-1154 shipped (2026-07-26) - `), so 120
# is generous without reaching prose like "the deferred third of #892".
_HEAD_WINDOW = 120

_LIFECYCLE_ORDER = ("allocated-open", "deferred", "superseded", "retired", "shipped")


class Skip(Exception):
    """A single unparseable line. Counted and reported, never fatal."""


def _key(series: str, number: int) -> str:
    """Stable dict/JSON key for a ledger number, e.g. ``AD-1152``."""
    return f"{series}-{number}"


def _leading_tokens(text: str) -> list[tuple[str, int, str]]:
    """Return the AD/BF tokens that form the *head* of ``text``.

    Only tokens reachable from the start of the line across connector text are
    head tokens. Everything after the first non-connector gap is body: an era
    entry headed ``AD-688 v1 CLOSED`` goes on to name six deferred siblings, and
    treating those as CLOSED would mark unbuilt work shipped.
    """
    stripped = _LEADING_MARKUP_RE.sub("", text)
    if not stripped[:1].isalpha():
        return []

    tokens: list[tuple[str, int, str]] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(stripped):
        if not _CONNECTOR_RE.match(stripped[cursor : match.start()]):
            break
        series, digits, suffix = match.group(1), match.group(2), match.group(3)
        tokens.append((series, int(digits), f"{series}-{digits}{suffix}"))
        cursor = match.end()
    return tokens


def _head_status(text: str) -> str | None:
    """The lifecycle keyword governing an entry head, or ``None``."""
    window = text[:_HEAD_WINDOW]
    best: tuple[int, str] | None = None
    for state, pattern in _STATUS_PATTERNS:
        found = pattern.search(window)
        if found is not None and (best is None or found.start() < best[0]):
            best = (found.start(), state)
    return None if best is None else best[1]


def parse_entry_lines(
    lines: Iterable[str], source: str, headings_only: bool
) -> tuple[dict[str, list[str]], list[str]]:
    """Parse one authority file into ``{key: [evidence, ...]}`` plus skips.

    ``headings_only`` selects the DECISIONS.md shape, where an entry is a
    markdown heading and the presence of the heading *is* the claim. PROGRESS
    files put the status on a bold or bare line instead.

    A line that looks like an entry head but yields no usable token is counted
    as a skip and the run continues. Historical formats in this repo span five
    eras and four heading conventions; aborting on the first oddity would mean
    the generator never runs at all.
    """
    evidence: dict[str, list[str]] = defaultdict(list)
    skipped: list[str] = []

    for lineno, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        try:
            if headings_only and not line.startswith("#"):
                continue
            probe = _LEADING_MARKUP_RE.sub("", line)
            if not probe.startswith(("AD-", "BF-", "AD ", "BF ")):
                continue

            tokens = _leading_tokens(line)
            if not tokens:
                raise Skip("head-shaped line yielded no AD/BF token")

            status = _head_status(line)
            if headings_only and status is None:
                # A DECISIONS.md heading is the record of a made decision.
                status = "shipped"
            for series, number, token in tokens:
                label = status or "mentioned"
                evidence[_key(series, number)].append(
                    f"{source}:{lineno} {token} {label}"
                )
        except Skip as exc:
            skipped.append(f"{source}:{lineno} {exc}")
        except Exception as exc:  # pragma: no cover - defensive, never fatal
            skipped.append(f"{source}:{lineno} unexpected {type(exc).__name__}: {exc}")

    return dict(evidence), skipped


def _read_lines(path: Path) -> list[str]:
    """Read an authority file, tolerating undecodable historical bytes."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _authority_files(stem: str, root: str) -> list[Path]:
    """The root tracker plus its era archives, in a stable order."""
    files = [_REPO_ROOT / root]
    files += sorted(_REPO_ROOT.glob(f"{stem}-era-*.md"))
    return [p for p in files if p.is_file()]


def parse_local_authorities() -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Parse DECISIONS + PROGRESS (and their era archives) from disk.

    These are the two authorities that are deterministic from tracked file
    content, identical in a shallow clone, and unchanged by the act of
    committing. They are what ``--check`` compares against.
    """
    evidence: dict[str, list[str]] = defaultdict(list)
    skipped: list[str] = []
    sources: list[str] = []

    for path in _authority_files("decisions", "DECISIONS.md"):
        found, skips = parse_entry_lines(
            _read_lines(path), path.name, headings_only=True
        )
        for key, items in found.items():
            evidence[key].extend(items)
        skipped.extend(skips)
        sources.append(path.name)

    for path in _authority_files("progress", "PROGRESS.md"):
        found, skips = parse_entry_lines(
            _read_lines(path), path.name, headings_only=False
        )
        for key, items in found.items():
            evidence[key].extend(items)
        skipped.extend(skips)
        sources.append(path.name)

    return dict(evidence), skipped, sources


def collect_git_layer() -> dict[str, object]:
    """Capture AD/BF tokens from commit subjects. Write-path only.

    Never called by ``--check`` -- see the module docstring for why a live git
    layer cannot be part of a stable gate.
    """
    captured = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        # Commit subjects in this repo contain em dashes and typographic
        # quotes. ``text=True`` alone decodes with the locale codec, which is
        # cp1252 on Windows and raises on the first such byte.
        subjects = subprocess.run(
            ["git", "log", "--pretty=%s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_REPO_ROOT),
            timeout=120,
            check=False,
        )
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_REPO_ROOT),
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"WARNING: git unavailable ({exc}); keeping the previous git layer. "
            "The ledger is still generated; its git evidence is as of the "
            "timestamp already recorded.",
            file=sys.stderr,
        )
        return {}

    if subjects.returncode != 0:
        print(
            "WARNING: `git log` failed; keeping the previous git layer. "
            f"stderr: {(subjects.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
        return {}

    lines = (subjects.stdout or "").splitlines()
    tokens: dict[str, list[str]] = defaultdict(list)
    for subject in lines:
        for series, number, token in _leading_tokens(subject):
            entry = f"git {token}"
            if entry not in tokens[_key(series, number)]:
                tokens[_key(series, number)].append(entry)

    return {
        "captured_at": captured,
        "head": (head.stdout or "").strip() or "unknown",
        "subject_count": len(lines),
        "tokens": {key: sorted(value) for key, value in sorted(tokens.items())},
    }


def collect_issue_layer() -> dict[str, object]:
    """Capture the GitHub issue layer via ``gh``. ``--online`` only.

    This is the authority the tree cannot see and the only one that needs the
    network. A missing or unauthenticated ``gh`` degrades to a warning and the
    previously captured layer -- never a traceback, and never a failure of the
    local-only checks.
    """
    captured = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "-R", _GH_REPO,
                "--state", "all",
                "--limit", "2000",
                "--json", "number,title,state,stateReason",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(_REPO_ROOT),
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"WARNING: `gh` unavailable ({exc}); keeping the previously captured "
            "issue layer. Install/authenticate the GitHub CLI to refresh it. "
            "Local-only checks are unaffected.",
            file=sys.stderr,
        )
        return {}

    if result.returncode != 0:
        print(
            "WARNING: `gh issue list` failed (offline, unauthenticated, or rate "
            "limited); keeping the previously captured issue layer. Local-only "
            f"checks are unaffected. stderr: {(result.stderr or '').strip()[:200]}",
            file=sys.stderr,
        )
        return {}

    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(
            f"WARNING: `gh` returned unparseable JSON ({exc}); keeping the "
            "previously captured issue layer.",
            file=sys.stderr,
        )
        return {}

    issues: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in raw:
        title = str(item.get("title", ""))
        head_by_key: dict[str, list[str]] = defaultdict(list)
        for series, number, token in _leading_tokens(title):
            head_by_key[_key(series, number)].append(token)
        seen: set[str] = set()
        for match in _TOKEN_RE.finditer(title):
            key = _key(match.group(1), int(match.group(2)))
            if key in seen:
                continue
            seen.add(key)
            issues[key].append(
                {
                    "number": int(item.get("number", 0)),
                    "state": str(item.get("state", "")).upper(),
                    "reason": str(item.get("stateReason") or ""),
                    # The exact token this title *leads* with. An epic naming
                    # its children ("Epic: ... (AD-1196, AD-1197)") claims
                    # none of them, and AD-423a/b/c are three distinct
                    # allocations that share base 423 -- so a collision is two
                    # issues leading with the *identical* token, not two
                    # issues mentioning the same number.
                    "claims": head_by_key.get(key, []),
                    "title": title,
                }
            )

    return {
        "captured_at": captured,
        "issue_count": len(raw),
        "issues": {
            key: sorted(value, key=lambda i: int(i["number"]))
            for key, value in sorted(issues.items())
        },
    }


def classify(
    local: Sequence[str],
    git_tokens: Sequence[str],
    issues: Sequence[dict[str, object]],
) -> tuple[str, str]:
    """Resolve one number to exactly one lifecycle state, with the reason.

    Precedence, highest first. Reality outranks intent; an explicit permanent
    verdict outranks reality; and the residual default is ``allocated-open``,
    never free -- assuming a number is free because nothing mentions it is the
    defect this whole generator exists to prevent.

    1. ``retired``       explicit in a tracker head, or an issue closed
                         ``not planned`` with no shipped evidence
    2. ``superseded``    explicit in a tracker head
    3. ``shipped``       a commit subject, a DECISIONS entry, a tracker head
                         marked closed/shipped, or an issue closed ``completed``
    4. ``allocated-open``an open issue, or a tracker head marked open
    5. ``deferred``      explicit in a tracker head, with no open issue
    6. ``allocated-open``anything else that any authority mentions at all

    Step 4 deliberately outranks step 5, which is why **AD-1152 (#1079)**
    resolves ``allocated-open``: DECISIONS.md line 244 says the OTel half was
    "deferred to AD-1152", but that sentence schedules the work, it does not
    close the number, and issue #1079 is open and unretired. Either label
    forbids reuse, so the safety property does not depend on this ordering --
    only the label does.
    """
    states = {item.rsplit(" ", 1)[-1] for item in local}
    open_issues = [i for i in issues if str(i.get("state")) == "OPEN"]
    closed_issues = [i for i in issues if str(i.get("state")) == "CLOSED"]
    not_planned = [i for i in closed_issues if str(i.get("reason")) == "NOT_PLANNED"]
    completed = [i for i in closed_issues if str(i.get("reason")) != "NOT_PLANNED"]

    shipped_locally = "shipped" in states or bool(git_tokens)

    if "retired" in states:
        return "retired", "a tracker head marks it retired"
    if not_planned and not shipped_locally:
        numbers = ", ".join(f"#{i['number']}" for i in not_planned)
        return "retired", f"issue {numbers} closed as not planned, no code"
    if "superseded" in states:
        return "superseded", "a tracker head marks it superseded"
    if git_tokens:
        return "shipped", f"{len(git_tokens)} commit subject(s)"
    if "shipped" in states:
        return "shipped", "a tracker head marks it closed/shipped"
    if completed:
        numbers = ", ".join(f"#{i['number']}" for i in completed)
        return "shipped", f"issue {numbers} closed as completed"
    if open_issues:
        numbers = ", ".join(f"#{i['number']}" for i in open_issues)
        return "allocated-open", f"issue {numbers} open, no code"
    if "allocated-open" in states:
        return "allocated-open", "a tracker head marks it open"
    if "deferred" in states:
        return "deferred", "a tracker head marks it deferred, no open issue"
    return "allocated-open", "mentioned by an authority, no code and no closure"


def _ranges(numbers: Iterable[int]) -> str:
    """Render integers as compact ranges: ``1-37, 39, 41-44``."""
    ordered = sorted(set(numbers))
    if not ordered:
        return "_(none)_"
    parts: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(parts)


def _issue_links(issues: Sequence[dict[str, object]]) -> str:
    if not issues:
        return "—"
    return ", ".join(
        f"[#{i['number']}](https://github.com/{_GH_REPO}/issues/{i['number']})"
        for i in issues
    )


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render(
    local: dict[str, list[str]],
    skipped: Sequence[str],
    sources: Sequence[str],
    snapshot: dict[str, object],
) -> str:
    """Build the ledger. Pure: no clock, no network, no subprocess.

    Every timestamp shown comes from the pinned snapshot, never from ``now()``.
    A generation timestamp would make the artifact differ from itself on every
    run and turn ``--check`` into a permanent failure.
    """
    git_layer = dict(snapshot.get("git") or {})
    issue_layer = dict(snapshot.get("issues") or {})
    git_tokens: dict[str, list[str]] = dict(git_layer.get("tokens") or {})
    issues: dict[str, list[dict[str, object]]] = dict(issue_layer.get("issues") or {})

    keys = set(local) | set(git_tokens) | set(issues)
    records: dict[str, dict[str, object]] = {}
    for key in keys:
        state, reason = classify(
            local.get(key, []), git_tokens.get(key, []), issues.get(key, [])
        )
        series, _, digits = key.partition("-")
        records[key] = {
            "series": series,
            "number": int(digits),
            "state": state,
            "reason": reason,
            "issues": issues.get(key, []),
            "local": local.get(key, []),
        }

    lines: list[str] = [_HEADER]

    # --- ceilings -------------------------------------------------------
    lines += ["## Ceilings", ""]
    lines += [
        "Derived from all four authorities. A tree scan sees only the numbers "
        "that reached code, so it reports a lower ceiling than this.",
        "",
        "| Series | Highest allocated | Next free | Highest with code | "
        "Allocated above the code ceiling |",
        "|---|---|---|---|---|",
    ]
    ceilings: dict[str, int] = {}
    for series in ("AD", "BF"):
        members = [r for r in records.values() if r["series"] == series]
        if not members:
            lines.append(f"| {series} | _(none)_ | _(none)_ | _(none)_ | _(none)_ |")
            continue
        highest = max(int(r["number"]) for r in members)
        ceilings[series] = highest
        coded = [int(r["number"]) for r in members if r["state"] == "shipped"]
        highest_coded = max(coded) if coded else 0
        above = sorted(
            int(r["number"]) for r in members if int(r["number"]) > highest_coded
        )
        lines.append(
            f"| {series} | **{series}-{highest}** | **{series}-{highest + 1}** "
            f"| {series}-{highest_coded} | {_ranges(above)} |"
        )
    lines.append("")

    # --- provenance -----------------------------------------------------
    lines += ["## Where each layer came from", ""]
    lines += [
        "| Authority | Availability | Captured | Extent |",
        "|---|---|---|---|",
    ]
    lines.append(
        "| `git log` commit subjects | pinned snapshot | "
        f"{git_layer.get('captured_at', '_never_')} at "
        f"`{git_layer.get('head', 'unknown')}` | "
        f"{git_layer.get('subject_count', 0)} subjects, "
        f"{len(git_tokens)} numbers |"
    )
    decision_sources = ", ".join(s for s in sources if s.startswith("DECISIONS") or s.startswith("decisions-"))
    progress_sources = ", ".join(s for s in sources if s.startswith("PROGRESS") or s.startswith("progress-"))
    lines.append(
        f"| `{decision_sources}` | live, every run | at check time | "
        "AD/BF entry headings |"
    )
    lines.append(
        f"| `{progress_sources}` | live, every run | at check time | "
        "AD/BF status head lines |"
    )
    lines.append(
        "| `gh issue list --state all` | pinned snapshot (network) | "
        f"{issue_layer.get('captured_at', '_never_')} | "
        f"{issue_layer.get('issue_count', 0)} issues, {len(issues)} numbers |"
    )
    lines += [
        "",
        "The two pinned layers are refreshed by running the generator "
        "(`--online` for issues). `--check` re-renders from the pinned snapshot "
        "and a fresh parse of the two live authorities, so it opens no socket "
        "and spawns no subprocess.",
        "",
    ]

    # --- lifecycle summary ----------------------------------------------
    lines += ["## Lifecycle", ""]
    lines += ["| State | AD | BF | Meaning |", "|---|---|---|---|"]
    meanings = {
        "allocated-open": "assigned, issue open, no shipped code",
        "deferred": "assigned, explicitly postponed",
        "shipped": "code in history",
        "superseded": "replaced by a later number",
        "retired": "abandoned, number **not** reusable",
    }
    for state in _LIFECYCLE_ORDER:
        ad = sum(1 for r in records.values() if r["state"] == state and r["series"] == "AD")
        bf = sum(1 for r in records.values() if r["state"] == state and r["series"] == "BF")
        lines.append(f"| `{state}` | {ad} | {bf} | {meanings[state]} |")
    lines.append("")

    # --- the numbers a tree scan cannot see -----------------------------
    for state in ("allocated-open", "deferred", "superseded", "retired"):
        members = sorted(
            (r for r in records.values() if r["state"] == state),
            key=lambda r: (r["series"], -int(r["number"])),
        )
        heading = {
            "allocated-open": "Allocated and open — **do not reuse these numbers**",
            "deferred": "Deferred",
            "superseded": "Superseded",
            "retired": "Retired — **never reusable**",
        }[state]
        lines += [f"## {heading}", ""]
        if not members:
            lines += ["_(none)_", ""]
            continue
        if state == "allocated-open":
            lines += [
                f"{len(members)} numbers. Every one is assigned. A recursive "
                "tree scan reports the ones without code as free.",
                "",
            ]
        lines += ["| Number | Issue | Why | Title |", "|---|---|---|---|"]
        for record in members:
            title = ""
            if record["issues"]:
                title = str(record["issues"][0].get("title", ""))
            lines.append(
                f"| `{record['series']}-{record['number']}` "
                f"| {_issue_links(record['issues'])} "
                f"| {_escape(str(record['reason']))} | {_escape(title)} |"
            )
        lines.append("")

    # --- shipped, compactly ---------------------------------------------
    lines += ["## Shipped", ""]
    for series in ("AD", "BF"):
        shipped = [
            int(r["number"])
            for r in records.values()
            if r["state"] == "shipped" and r["series"] == series
        ]
        lines += [f"**{series}** ({len(shipped)}): {_ranges(shipped)}", ""]

    # --- unaccounted ------------------------------------------------------
    lines += ["## Unaccounted — silent, **not** free", ""]
    lines += [
        "Numbers below the ceiling that no authority mentions. The issue layer "
        "is a snapshot and audits allocate before writing code, so silence here "
        "is absence of evidence. Confirm against live issues before minting.",
        "",
    ]
    for series in ("AD", "BF"):
        ceiling = ceilings.get(series)
        if ceiling is None:
            continue
        known = {int(r["number"]) for r in records.values() if r["series"] == series}
        gaps = [n for n in range(1, ceiling + 1) if n not in known]
        lines += [f"**{series}** ({len(gaps)}): {_ranges(gaps)}", ""]

    # --- inconsistencies --------------------------------------------------
    lines += ["## Inconsistencies — reported, deliberately not fixed", ""]
    lines += [
        "This generator observes the ledger; correcting an append-only history "
        "is a separate decision for a human.",
        "",
        "A *collision* below means two issues each **lead** with the identical "
        "number. Sub-allocations that share a base (`AD-423a`, `AD-423b`, "
        "`AD-423c`) and epics that name their children in the title are normal "
        "and are not counted.",
        "",
    ]
    problems: list[str] = []
    for key in sorted(records, key=lambda k: (records[k]["series"], int(records[k]["number"]))):
        record = records[key]
        states = {item.rsplit(" ", 1)[-1] for item in record["local"]}
        verdicts = states - {"mentioned"}
        if len(verdicts) > 1:
            problems.append(
                f"- `{key}` — the trackers disagree: {', '.join(sorted(verdicts))}. "
                f"Resolved as `{record['state']}`."
            )
        if record["state"] == "shipped" and any(
            str(i.get("state")) == "OPEN" for i in record["issues"]
        ):
            problems.append(
                f"- `{key}` — code is in history but "
                f"{_issue_links([i for i in record['issues'] if str(i.get('state')) == 'OPEN'])} "
                "is still open."
            )
        claimants: dict[str, list[dict[str, object]]] = defaultdict(list)
        for issue in record["issues"]:
            for token in issue.get("claims") or []:
                claimants[str(token)].append(issue)
        for token, holders in sorted(claimants.items()):
            if len(holders) > 1:
                problems.append(
                    f"- `{token}` — collision: {len(holders)} issues each lead "
                    f"with this number: {_issue_links(holders)}."
                )
    lines += (problems or ["_(none)_"]) + [""]

    # --- skips ------------------------------------------------------------
    lines += ["## Unparseable lines", ""]
    lines += [
        f"{len(skipped)} head-shaped lines could not be parsed. A malformed or "
        "historical entry is skipped and counted, never fatal — five eras of "
        "formatting conventions are represented in these files.",
        "",
    ]
    if skipped:
        lines += ["```"] + list(skipped[:50]) + ["```", ""]
        if len(skipped) > 50:
            lines += [f"_({len(skipped) - 50} more not shown.)_", ""]

    return "\n".join(lines).rstrip() + "\n"


def _load_snapshot() -> dict[str, object]:
    if not _SNAPSHOT.is_file():
        return {}
    try:
        loaded = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"WARNING: {_SNAPSHOT.name} is unreadable ({exc}); treating both "
            "pinned layers as empty. Regenerate with "
            "`python scripts/gen_ad_ledger.py --online`.",
            file=sys.stderr,
        )
        return {}
    return loaded if isinstance(loaded, dict) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed ledger is stale (no network, no subprocess)",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="refresh the GitHub issue layer via `gh` before writing",
    )
    args = parser.parse_args(argv)

    if args.check and args.online:
        print("--check and --online are mutually exclusive: --check is offline "
              "by design.", file=sys.stderr)
        return 2

    local, skipped, sources = parse_local_authorities()
    snapshot = _load_snapshot()

    if args.check:
        generated = render(local, skipped, sources, snapshot)
        if not _OUTPUT.exists():
            print(f"MISSING: {_OUTPUT}", file=sys.stderr)
            return 1
        if _OUTPUT.read_text(encoding="utf-8") != generated:
            print(
                "STALE: docs/development/open-ads-report.md no longer matches "
                "DECISIONS.md / PROGRESS.md.\nRegenerate with: "
                "python scripts/gen_ad_ledger.py",
                file=sys.stderr,
            )
            return 1
        print("AD/BF ledger is current")
        return 0

    git_layer = collect_git_layer()
    if git_layer:
        snapshot["git"] = git_layer
    if args.online:
        issue_layer = collect_issue_layer()
        if issue_layer:
            snapshot["issues"] = issue_layer

    generated = render(local, skipped, sources, snapshot)

    _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _OUTPUT.write_text(generated, encoding="utf-8")
    print(
        f"wrote {_OUTPUT.relative_to(_REPO_ROOT).as_posix()} "
        f"({len(generated.splitlines())} lines) and "
        f"{_SNAPSHOT.relative_to(_REPO_ROOT).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
