"""Layout guard for the standing-orders split (the ProbOS Orchestrator profile).

``.github/copilot-instructions.md`` (C, the constitution) used to carry the
orchestration procedure, the full Engineering Principles, the architect standards
and the architecture reference in one large file that Copilot injects into every
call. It was split into:

- C, now short: the shared rules, an index of the rest and "Where Each Rule Lives".
- O, ``.github/agents/orchestrator.agent.md``: the orchestration procedure.
- EP, AS and AR, under ``docs/development/``: ``engineering-principles.md``,
  ``architect-standards.md`` and ``architecture-reference.md``, read by section.

These tests pin that layout over the governed set: C, O, EP, AS, AR and
``CLAUDE.md``. They check one owner per rule, no sentence in two files, a
constitution that stays small, a profile Copilot can load, pointers that resolve
and the retired Supervised Worker profiles gone.

Each test asserts its own premise first (the file exists, the scan saw enough
files, the detector finds a planted duplicate), so a vacuous pass reads as a
failure. Fix a failing layout test by moving text to its owner or by replacing a
copy with a pointer, never by loosening the test.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

from probos.repository_instructions import (
    discover_repository_instructions,
    render_repository_instructions,
)
from probos.security.file_access import INSTRUCTION_FILE_BYTES

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[1]
_AGENTS_DIR = _REPO_ROOT / ".github" / "agents"

CONSTITUTION = _REPO_ROOT / ".github" / "copilot-instructions.md"
ORCHESTRATOR = _AGENTS_DIR / "orchestrator.agent.md"
ENGINEERING = _REPO_ROOT / "docs" / "development" / "engineering-principles.md"
STANDARDS = _REPO_ROOT / "docs" / "development" / "architect-standards.md"
ARCHITECTURE = _REPO_ROOT / "docs" / "development" / "architecture-reference.md"
CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"
GOVERNED = (CONSTITUTION, ORCHESTRATOR, ENGINEERING, STANDARDS, ARCHITECTURE, CLAUDE_MD)

# The Captain's routing line and the compaction safeguard that follows it, verbatim.
R0A = (
    "Orchestrating the queue? You must be the ProbOS Orchestrator agent; "
    "if you are not, read .github/agents/orchestrator.agent.md before doing anything else."
)
R0B = (
    "If that profile's sections are no longer in your context "
    "(for example after a context compaction), read it again before your next step."
)

CONSTITUTION_CAP_BYTES = 18_000

# Heading text (without the leading #s) -> the one file that owns that section.
OWNERS: dict[str, Path] = {
    "Evidence Standard (Standing Order, both modes)": CONSTITUTION,
    "Adversarial Review Before Every Commit (Standing Order, both modes)": CONSTITUTION,
    "AD and BF Numbering — Hard Rule": CONSTITUTION,
    "Repository Boundary — OSS vs Commercial": CONSTITUTION,
    "Building: Engineering Principles (Standing Order)": CONSTITUTION,
    "Delegation and Waiting (Standing Order)": ORCHESTRATOR,
    "Backlog Burn-Down Mode (Standing Order)": ORCHESTRATOR,
    "Delegated AD Execution Mode (Standing Order)": ORCHESTRATOR,
    "Gate, Batch and Push (Standing Order)": ORCHESTRATOR,
    "Review Rounds and Progress (Standing Order)": ORCHESTRATOR,
    "SOLID Principles": ENGINEERING,
    "Testing Standards": ENGINEERING,
    "Architect: Review Checklist": STANDARDS,
    "Common Review Flags": STANDARDS,
    "Architect: Claude Code Prompt Drafting": STANDARDS,
    "Architect: Strategy": STANDARDS,
    "Design Principles": ARCHITECTURE,
    "HXI Design Principles": ARCHITECTURE,
}

# A sentence is compared once it has at least this many characters after normalisation.
_MIN_SENTENCE_CHARS = 60

# Front-matter keys the Copilot CLI accepts in an agent profile.
_PROFILE_KEYS = frozenset({
    "name", "description", "model", "tools", "user-invocable", "disable-model-invocation",
    "argument-hint", "target", "agents", "handoffs", "mcp-servers", "hooks",
})

# Profiles whose `model` is still an array (the CLI refuses an array; follow-up F1).
KNOWN_ARRAY = frozenset({"diff-reviewer.agent.md"})

# Procedure text the orchestrator profile owns, and the constitution must not repeat.
PROCEDURE = (
    "scripts/claude_architect.py --task-file",
    "Start-Sleep -Seconds 270",
    "scripts/run_test_gate.py --label <issue-or-wave> --receipt",
    "**Still requires the Captain.**",
    "Discovery budget",
    "Freeze the batch, then run ONE full repository gate",
    "**Route decisions through the Architect, not the Captain (Captain, 2026-10-14).**",
    "**decided by the Architect**",
    "Before parking, ask whether the blocking requirement itself can be narrowed or reframed",
    "**Convergence (codified 2026-10-15).**",
    "**Round-three brake (Captain, 2026-10-15).**",
    "Do not start a fourth round on your own, whatever leads to it",
    "the exact command that shows the delta (`git diff <base> <head>` for a committed candidate",
    "`git diff --cached <base>` in the worktree for a staged one",
    "or staged in full (`git add <paths>`, new files included; never `git add -N`",
    "that exists only in the working tree has neither form, so stage it before the call and never hand it off unstaged",
    "kept out of the index and named by `git diff` in the worktree for a staged candidate or by `git diff <head>` for a committed one",
    "**Progress comments (Captain, 2026-10-15).**",
    "Phase: draft | build | review round N | gate | CI",
)

# Shared rules the constitution keeps.
SHARED_RULES = (
    "Claims that something does NOT exist require an enumeration you actually ran",
    "run the `Diff Reviewer` subagent on the staged diff",
    "scripts/ad_ceiling.py",
    "`ad_ceiling.py` does not cover BF numbers",
    "How the product makes money",
)

# The review-rounds section: its owner is O; C, CLAUDE.md and the Architect's profile point to it by name,
# and both sides of the round-three brake name the same three options.
ARCHITECT_PROFILE = _REPO_ROOT / ".claude" / "agents" / "claude-architect.md"
REVIEW_ROUNDS = "Review Rounds and Progress"
BRAKE_OPTIONS = ("**continue**", "**rescope**", "**split**")

_POINTER = re.compile(r"`((?:\.github|\.claude|docs|scripts)/[^`\s]*\.(?:md|py))`")
# Local role profiles that exist only in a developer's checkout (.claude/ is gitignored).
UNTRACKED_LOCAL = frozenset({".claude/agents/builder.md", ".claude/agents/architect.md"})

RETIRED = re.compile(r"probos-(?:architect|builder|diff-reviewer)(?![-\w])|ProbOS Supervised|supervised-worker\.json")
RETIRED_FILES = (
    ".github/agents/probos-architect.agent.md",
    ".github/agents/probos-builder.agent.md",
    ".github/agents/probos-diff-reviewer.agent.md",
    ".github/supervised-worker.json",
)
_SCANNED_TREES = (".github", "scripts", "src", "tests")

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Two synthetic texts that share exactly one long sentence, written with different
# markup and case, plus a short sentence they also share that must not be reported.
_PLANTED_PAIR = {
    "first": (
        "# First\n\n"
        "- **Every changed contract** has to be traced through all of its   production consumers before commit.\n"
        "A sentence that exists only in the first of these two texts and is long enough to count.\n"
    ),
    "second": (
        "# Second\n\n"
        "every Changed contract has to be traced through all of its production consumers before commit. Short shared line.\n"
        "A sentence that exists only in the second of these two texts and is long enough to count.\n"
        "Short shared line.\n"
    ),
}
_PLANTED_NORMALISED = (
    "every changed contract has to be traced through all of its production consumers before commit."
)


def _text(path: Path) -> str:
    """The file as UTF-8 text with LF line endings (universal newlines), whatever the checkout's EOL."""
    return path.read_text(encoding="utf-8")


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _front_matter(path: Path) -> dict[str, object] | None:
    """The parsed YAML front matter of a profile, or None when it has none."""
    match = _FRONT_MATTER.match(_text(path))
    if match is None:
        return None
    meta = yaml.safe_load(match.group(1))
    assert isinstance(meta, dict), f"{_rel(path)}: front matter is not a mapping"
    return meta


def _headings(path: Path) -> list[str]:
    """Markdown heading texts (leading #s removed) outside fenced code blocks."""
    found: list[str] = []
    in_fence = False
    for line in _text(path).split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            match = _HEADING.match(line)
            if match is not None:
                found.append(match.group(1))
    return found


def _normalise(sentence: str) -> str:
    """Strip emphasis markers and a list marker, collapse whitespace, lowercase."""
    plain = _LIST_MARKER.sub("", sentence.replace("**", "").strip())
    return re.sub(r"\s+", " ", plain).strip().lower()


def _sentence_units(text: str) -> list[str]:
    """Normalised sentences of at least ``_MIN_SENTENCE_CHARS`` characters, YAML front matter excluded."""
    match = _FRONT_MATTER.match(text)
    body = text[match.end():] if match is not None else text
    units: list[str] = []
    for line in body.split("\n"):
        for raw in _SENTENCE_END.split(line.replace("**", "")):
            unit = _normalise(raw)
            if len(unit) >= _MIN_SENTENCE_CHARS:
                units.append(unit)
    return units


def _duplicated_sentences(texts: dict[str, str]) -> dict[str, list[str]]:
    """Each normalised sentence found more than once across ``texts``, with the names holding it."""
    seen: dict[str, list[str]] = {}
    for name, text in texts.items():
        for unit in _sentence_units(text):
            seen.setdefault(unit, []).append(name)
    return {unit: names for unit, names in seen.items() if len(names) > 1}


def _scan_for_retired_references() -> tuple[list[str], list[str]]:
    """Walk the scanned paths and return (files visited, ``path:line: text`` hits).

    The walk uses ``pathlib``, never a gitignore-aware search: ``.gitignore`` excludes
    ``.claude/``, so ripgrep from the repository root skips the tracked
    ``.claude/agents/claude-*.md`` files, one of which names a memory file that this
    pattern must not match. Bytecode caches are build output, and this file's own cache
    holds the pattern text, so ``__pycache__`` is skipped along with this file.
    """
    candidates: list[Path] = []
    for tree in _SCANNED_TREES:
        candidates.extend(path for path in (_REPO_ROOT / tree).rglob("*") if path.is_file())
    candidates.extend(sorted((_REPO_ROOT / ".claude" / "agents").glob("claude-*.md")))
    candidates.append(CLAUDE_MD)
    visited: list[str] = []
    hits: list[str] = []
    for path in candidates:
        if path == _THIS_FILE or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # a temp file another test removed mid-walk is not tracked content
        rel = _rel(path)
        visited.append(rel)
        for match in RETIRED.finditer(text):
            hits.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}: {match.group(0)}")
    return visited, hits


# ── the constitution ───────────────────────────────────────────────


def test_constitution_opens_with_orchestrator_routing_line() -> None:
    assert CONSTITUTION.is_file(), f"{_rel(CONSTITUTION)} is missing"
    lines = [line for line in _text(CONSTITUTION).split("\n") if line.strip()]
    assert len(lines) >= 3, "the constitution is nearly empty"
    assert lines[0].startswith("# "), f"the first line is not the title: {lines[0]!r}"
    assert lines[1] == R0A
    assert lines[2] == R0B


def test_constitution_stays_slim() -> None:
    """The constitution is injected into every Copilot call, so every byte is paid on every call.

    18,000 bytes (LF-normalised UTF-8) is a deliberate cap. Raising it is a deliberate
    decision, taken with the Captain's knowledge and recorded in DECISIONS.md. It is never
    the way to make this test pass: move reference material to ``docs/development/`` and
    point to it from "Where Each Rule Lives".
    """
    text = _text(CONSTITUTION)
    assert text.strip(), f"{_rel(CONSTITUTION)} is empty"
    size = len(text.encode("utf-8"))
    assert size <= CONSTITUTION_CAP_BYTES, (
        f"{_rel(CONSTITUTION)} is {size} bytes, over the {CONSTITUTION_CAP_BYTES}-byte cap"
    )


def test_constitution_prefix_delivered_to_the_native_builder(tmp_path: Path) -> None:
    """AD-1200 reads at most INSTRUCTION_FILE_BYTES of each instruction file, so ProbOS's own
    builder receives a typed prefix of the constitution, not the whole file. The prefix must
    still carry the title, the routing lines and the whole Evidence Standard (it ends where
    the Adversarial Review heading begins).

    If the premise fails (the cap changed, or C now fits), restate this test deliberately:
    a C that fits must be asserted ``delivery == "complete"``.
    """
    # Premise: the per-file cap and C's size are what this test was written against.
    assert INSTRUCTION_FILE_BYTES == 8192, (
        f"AD-1200's per-file cap changed to {INSTRUCTION_FILE_BYTES}; restate T3"
    )
    file_text = CONSTITUTION.read_bytes().decode("utf-8-sig")
    size = len(file_text.encode("utf-8"))
    assert size > INSTRUCTION_FILE_BYTES, (
        f"{_rel(CONSTITUTION)} is {size} bytes and now fits the {INSTRUCTION_FILE_BYTES}-byte "
        "per-file cap; restate T3 to assert delivery == 'complete'"
    )

    repo = tmp_path / "project"
    (repo / ".git").mkdir(parents=True)
    copied = repo / ".github" / "copilot-instructions.md"
    copied.parent.mkdir()
    shutil.copyfile(CONSTITUTION, copied)

    rendered = render_repository_instructions(discover_repository_instructions(repo))

    frames = [json.loads(line) for line in rendered.splitlines() if line.startswith('{"source":')]
    ours = [frame for frame in frames if str(frame["source"]).endswith("copilot-instructions.md")]
    assert len(ours) == 1, f"expected one copilot-instructions.md frame, got {[f['source'] for f in frames]}"
    frame = ours[0]
    assert frame["status"] == "truncated", f"status {frame['status']!r}"
    assert frame["delivery"] == "prefix", f"delivery {frame['delivery']!r}"

    content = frame["content"]
    assert content, "the delivered prefix is empty"
    assert len(content.encode("utf-8")) <= INSTRUCTION_FILE_BYTES
    assert file_text.startswith(content), "the delivered text is not a prefix of the constitution"

    for required in (
        R0A,
        R0B,
        "## Evidence Standard (Standing Order, both modes)",
        "## Adversarial Review Before Every Commit (Standing Order, both modes)",
    ):
        assert required in content, (
            f"{required!r} is no longer inside the first {INSTRUCTION_FILE_BYTES} bytes "
            "that AD-1200 delivers to ProbOS's own builder"
        )


def test_engineering_principles_acceptance_line_still_resolves() -> None:
    """About 800 prompts say "comply with the Engineering Principles in `.github/copilot-instructions.md`"."""
    constitution = _text(CONSTITUTION)
    engineering = _text(ENGINEERING).split("\n")
    assert "## Building: Engineering Principles (Standing Order)" in constitution.split("\n")
    assert "docs/development/engineering-principles.md" in constitution
    assert "### SOLID Principles" in engineering
    assert "### Testing Standards" in engineering


# ── one owner per rule ─────────────────────────────────────────────


def test_each_section_has_exactly_one_owner() -> None:
    absent = [_rel(path) for path in GOVERNED if not path.is_file()]
    assert not absent, f"governed files are missing: {absent}"
    headings = {path: _headings(path) for path in GOVERNED}
    problems: list[str] = []
    for heading, owner in OWNERS.items():
        where = {_rel(path): found.count(heading) for path, found in headings.items() if heading in found}
        if where != {_rel(owner): 1}:
            problems.append(f"{heading!r}: expected once in {_rel(owner)}, found {where or 'nowhere'}")
    assert not problems, "\n".join(problems)


def test_no_sentence_is_duplicated_across_instruction_files() -> None:
    """A rule lives in one file. A duplicate, in ``CLAUDE.md`` too, is replaced by a pointer."""
    texts = {_rel(path): _text(path) for path in GOVERNED}
    compared = sum(len(_sentence_units(text)) for text in texts.values())
    assert compared >= 200, f"only {compared} sentences were compared; the detector is not seeing the files"
    planted = _duplicated_sentences(_PLANTED_PAIR)
    assert list(planted) == [_PLANTED_NORMALISED], "the detector missed its own planted duplicate"

    duplicates = _duplicated_sentences(texts)

    assert not duplicates, "sentences in more than one place:\n" + "\n".join(
        f"  {names}: {unit[:100]}" for unit, names in duplicates.items()
    )


def test_duplicate_detector_finds_a_planted_duplicate() -> None:
    found = _duplicated_sentences(_PLANTED_PAIR)

    assert list(found) == [_PLANTED_NORMALISED]
    assert found[_PLANTED_NORMALISED] == ["first", "second"]


# ── the profiles ───────────────────────────────────────────────────


def test_orchestrator_profile_frontmatter_has_cli_shape() -> None:
    meta = _front_matter(ORCHESTRATOR)
    assert meta is not None, f"{_rel(ORCHESTRATOR)} has no YAML front matter"
    assert meta.get("name") == "ProbOS Orchestrator"
    model = meta.get("model")
    assert isinstance(model, str) and model.strip(), f"model must be a non-empty string, got {model!r}"
    assert isinstance(meta.get("description"), str)
    assert meta.get("user-invocable") is True
    assert meta.get("disable-model-invocation") is True
    assert "tools" not in meta, "a tools list shrinks the system message; the profile must omit it"
    assert set(meta) <= _PROFILE_KEYS, f"unknown front-matter keys: {sorted(set(meta) - _PROFILE_KEYS)}"


def test_agent_profile_models_are_strings() -> None:
    profiles = sorted(_AGENTS_DIR.glob("*.agent.md"))
    assert len(profiles) >= 2, f"only {len(profiles)} agent profiles were found"
    offenders: list[str] = []
    for profile in profiles:
        meta = _front_matter(profile) or {}
        if profile.name not in KNOWN_ARRAY and "model" in meta and not isinstance(meta["model"], str):
            offenders.append(f"{profile.name}: {meta['model']!r}")
    assert not offenders, f"the Copilot CLI refuses an array model: {offenders}"


def test_known_array_model_exceptions_are_still_arrays() -> None:
    for name in KNOWN_ARRAY:
        meta = _front_matter(_AGENTS_DIR / name) or {}
        assert isinstance(meta.get("model"), list), (
            f"{name} no longer has an array model: remove it from KNOWN_ARRAY"
        )


def test_orchestrator_profile_carries_the_procedure() -> None:
    orchestrator = _text(ORCHESTRATOR)
    constitution = _text(CONSTITUTION)
    missing = [needle for needle in PROCEDURE if needle not in orchestrator]
    repeated = [needle for needle in PROCEDURE if needle in constitution]
    assert not missing, f"missing from the orchestrator profile: {missing}"
    assert not repeated, f"also in the constitution, which must only point to them: {repeated}"


def test_constitution_keeps_the_shared_rules() -> None:
    constitution = _text(CONSTITUTION)
    missing = [needle for needle in SHARED_RULES if needle not in constitution]
    assert not missing, f"missing from the constitution: {missing}"


def test_review_rounds_pointers_and_brake_options_agree() -> None:
    """C, CLAUDE.md and claude-architect.md point to the review-rounds section by name
    instead of restating it, and both sides of the round-three brake name the same options."""
    pointers = (CONSTITUTION, CLAUDE_MD, ARCHITECT_PROFILE)
    absent = [_rel(path) for path in (ORCHESTRATOR, *pointers) if not path.is_file()]
    assert not absent, f"files are missing: {absent}"
    assert f"{REVIEW_ROUNDS} (Standing Order)" in _headings(ORCHESTRATOR), "the section heading moved"

    unpointed = [_rel(path) for path in pointers if f"**{REVIEW_ROUNDS}**" not in _text(path)]
    assert not unpointed, f"no pointer to **{REVIEW_ROUNDS}** in: {unpointed}"

    orchestrator, architect = _text(ORCHESTRATOR), _text(ARCHITECT_PROFILE)
    missing = {
        _rel(ORCHESTRATOR): [option for option in BRAKE_OPTIONS if option not in orchestrator],
        _rel(ARCHITECT_PROFILE): [option for option in BRAKE_OPTIONS if option not in architect],
    }
    assert not any(missing.values()), f"brake options the two sides do not share: {missing}"


def test_brake_handoff_does_not_redefine_frozen() -> None:
    """'Frozen' keeps its plain meaning (a candidate held fixed during a pass) in the round definition and the
    focused check, so the brake's handoff forms are described without it and a working-tree pass still counts."""
    orchestrator = _text(ORCHESTRATOR)
    marker = "**Round-three brake (Captain, 2026-10-15).**"
    assert orchestrator.count(marker) == 1, "the brake paragraph moved or was duplicated"
    brake = orchestrator.split(marker, 1)[1].split("\n\n", 1)[0]
    assert "in one of two forms and no other" in brake, "the paragraph under test is not the handoff clause"
    assert not re.search(r"\bfrozen\b", brake, re.IGNORECASE), "the brake paragraph uses 'frozen' again"


# ── pointers and the retired profiles ──────────────────────────────


def test_pointer_paths_exist() -> None:
    found = {
        (_rel(source), path)
        for source in (CONSTITUTION, ORCHESTRATOR)
        for path in _POINTER.findall(_text(source))
        if "*" not in path  # `.claude/agents/claude-*.md` in the constitution's table is a glob, not a path
    }
    assert len(found) >= 5, f"only {len(found)} pointer paths were found; the extraction is not seeing the files"
    missing = sorted(
        (source, path) for source, path in found
        if path not in UNTRACKED_LOCAL and not (_REPO_ROOT / path).is_file()
    )
    assert not missing, f"pointers to files that do not exist: {missing}"


def test_retired_supervised_worker_profiles_are_gone() -> None:
    visited, hits = _scan_for_retired_references()
    assert len(visited) >= 50, f"the scan visited only {len(visited)} files"
    assert ".claude/agents/claude-architect.md" in visited, "the scan never reached .claude/agents/claude-architect.md"

    present = [rel for rel in RETIRED_FILES if (_REPO_ROOT / rel).exists()]
    assert not present, f"retired files are still present: {present}"
    assert not hits, "references to the retired profiles:\n" + "\n".join(f"  {hit}" for hit in hits)


def test_retired_profile_pattern_is_bounded() -> None:
    assert RETIRED.search("probos-builder.agent.md")
    assert RETIRED.search('"probos-diff-reviewer"')
    assert RETIRED.search("ProbOS Supervised Architect")
    assert not RETIRED.search("/memories/probos-architect-learnings.md")
