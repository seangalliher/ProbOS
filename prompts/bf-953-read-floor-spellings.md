# BF-953 (#1752): the read floor decides every spelling of one file the same way

**Drafted by:** the Copilot `Architect` (the Claude Code bridge's fallback), 2026-11-04
**Revised by:** the orchestrator (Claude Sonnet 5.5), 2026-11-04, before the build: §1 item 1 names the spelling probe as a session artifact that is not committed (it cited a file outside the repository); no block, count, hash or mutation row changed. The bridge's draft of this prompt (the Claude Code `claude-architect`, Opus 5.5) was stopped partway by a safety classifier, which is why the documented fallback drafted it.
**Status:** ready to build. **Base:** drafted on the BF-948 worktree head `728e1fc2d2f49fd04584adf2a41d1dfa68befcb5` (branch `fix/bf948-list-files-read-policy-20261104-ca0ca20b`, base `origin/main` `ca0ca20b9bfa80b4d2367bc61ab1f5d995969a38`). The orchestrator's brief named `9649df65`; `728e1fc2` adds only the amended BF-948 contract (`git diff --stat 9649df65 728e1fc2` is one file under `prompts/`), and every file this contract changes has the same blob at both (§13), so each pair applies to either. **Dependencies:** none; built first in the BF-948 PR (#1752 says so), before BF-948's M4. **Tier:** M1 STANDARD, M2 HIGH, M3 STANDARD. **Estimated tests:** 1 new file, `tests/test_bf953_read_floor_spellings.py` (10 test functions; counts in §4).
**BF number:** BF-953, held by the title of #1752 (`gh issue view 1752`: OPEN, "BF-953: resolve_read_path does not return one decision for every spelling of one file"). Current highest: **BF-953** (GitHub issue titles, all states, 1,507 fetched; the next BF-95x is BF-954). `git log --all` subjects stop at BF-951; `prompts/bf-95*` is empty; the roadmap's Bug Tracker has no BF-95x row (§Absence Verified).
**Shared-contract change.** `resolve_read_path` is a public function every read path asks. This changes its decisions, so every consumer (§1, found by search) inherits it. **The Diff Reviewer therefore covers the whole candidate**, not the new lines: §16 lists the properties, and §3 D6 gives the compatibility story and §6 how it is tested.
**Which text describes the head.** Line numbers are those of `728e1fc2`. Where prose differs from a REPLACE or new-file block, the block wins. "Head text" means every docstring, comment, error string and test docstring in those blocks, plus the tracker entries (§8) and the commit messages (§5).

## 1. Problem

`security/file_access.py::resolve_read_path` (`:105-162`) resolves a path with `Path.resolve()` and decides it by comparing the result's text with three root lists through `_longest_match` (`:92-102`): the floor (the runtime data directory and the config files, `protected_read_roots` `:197-206`), the exempt roots (`workspace_exempt_roots` `:388-398`) and the permitted roots (`permitted_read_roots` `:165-194`).

1. **The function's decision depends on the spelling.** Measured on the committed head, Windows, Python 3.12.13, by the orchestrator's probe of 20 spellings of one fixture file (a session probe whose output is not committed, run on the tree, with `os.path.samestat` and the bytes as the premise that each row is the same file; T1 is its committed form). 11 spellings are decided like the ordinary one for a file on disk, because `Path.resolve()` normalises them: forward slashes, a doubled separator, a dot segment, `..` through a sibling and through a missing directory, swapped case, the 8.3 name, a trailing dot, a trailing space, a stream suffix, and the device prefix. **9 are decided differently**, for the floor and the permitted roots alike: the extended-length prefix (plain, swapped case, 8.3 name) and the share spellings of the local drive (`localhost`, `127.0.0.1`, the computer name, the extended forms of `localhost` and of the computer name, and `localhost` with `..`). One of the 11, the trailing space, is also decided differently for a file that is not on disk (found while building T1, on this host): `Path.resolve()` of a missing child of a directory spelled with a trailing space returns the extended-length spelling of it (`\\?\C:\…\dir\child`), so it takes the same road through the function. `Path.resolve()` keeps the extended-length prefix it was given and reports a share spelling of a local drive as the share path, so the text of the result matches none of the roots the ordinary spelling matches.
2. **The exemption case.** With a floor root over an exempt root, the 9 spellings are admitted only because no floor root matched them, so the exemption was never asked. After the fix a floor root matches them, and the exemption must still lift it where it applies (T1).
3. **The write side of the same module already treats this.** `_write_key` (`:266-281`) drops the `//?/` and `//./` prefixes (`_DEVICE_PREFIXES` `:252`) and `//?/UNC/` becomes `//`. It cannot make `//localhost/C$/x` the key of `C:/x`: BF-911 adds an `os.stat` identity layer for the config files (`:360-368`). The read side has neither.
4. **Consumers, by search** (`rg -n "resolve_read_path|resolve_for_runtime|protected_read_roots|permitted_read_roots|protected_config_files|workspace_exempt_roots|_longest_match|_ReadFloor" src tests scripts`; 85 hits in 10 `src` files, 7 test files, none in `scripts`):

   | Consumer | Where | How it asks |
   |---|---|---|
   | `resolve_for_runtime` | `security/file_access.py:401-411` | composes the three lists, calls `resolve_read_path` |
   | `read_verified_file`, `read_bounded_utf8` | `file_access.py:863-876`, `:902-` (calls at `:869`, `:933`) | pass the lists they were given; compare the returned path with their lexical candidate (`resolved != candidate`) |
   | `ReadFileTool`, `CodebaseReadSourceTool` | `cognitive/swe_harness/tools.py:449`, `:790` (`resolve_for_runtime`); `:339-341`, `:948-950` (the three lists) | |
   | `ListFilesTool` (BF-948) | `tools.py:563-580` | the base, then every match, with one composition of the lists |
   | `_ReadFloor` (BF-908) and its sites | `agents/code_search.py:143-146`, `:323-359` | one composition per search, one `resolve_read_path` per result path |
   | `FileReaderAgent`, `FileSearchAgent`, `DirectoryListAgent` | `agents/file_reader.py:106-108`, `agents/file_search.py:128-131`, `agents/directory_list.py:107-110` | `resolve_for_runtime` |
   | the copilot adapter | `cognitive/copilot_adapter.py:31-36`, `:110-112` | the three lists |
   | repository instructions | `repository_instructions.py:12-19`, `:62-64` | the three lists |
   | the agent work runner | `agent_work_runner.py:606-617`, `:699-714` | `permitted_read_roots`, `workspace_exempt_roots` |

   `protected_config_files` is also called by the write side (`file_access.py:350`). Nothing outside `file_access.py` calls `_longest_match` (§Absence Verified A1).

## 2. Solution

- **M1:** `tests/test_bf953_read_floor_spellings.py`, written first. Every spelling case the base decides differently, and every test that calls a helper M2 adds, is `xfail(strict=True)`: red on the base, for the reason its mark names.
- **M2:** `_longest_match` decides containment on the namespace-free text of both sides and, for a path or root that still names a share or device, on the identity the operating system gives the file. Windows only. `resolve_read_path` returns the resolved path exactly as before. The marks come off.
- **M3:** trackers and the ledger. The tracker pairs only insert.

## 3. Decisions

Criteria order: correctness (every spelling), safety (nothing admitted that was refused), compatibility, architectural fit, cost, reversibility.

- **D1, how the decision is made. Chosen: D1-d**, ranked against the other three on the evidence of §1.

  | Rank | Option | Sets the property? | Legitimate network path | Long local path | Path that does not exist | POSIX | Cost |
  |---|---|---|---|---|---|---|---|
  | 1 | **D1-d** the namespace-free text, then file identity for a path or root that still names a share or device (Windows only) | yes, for all 20 probed spellings, and for any spelling the system resolves to the same file (host names, addresses, shares): the `ident` column of the probe matched every row in all three scenarios | stays admitted unless a root is the file or an ancestor of it by identity | the extended-prefix local path is decided on its text; the returned path keeps its prefix, so it still opens | the nearest ancestor on disk decides; a root not on disk is matched by text only | unchanged: the new branch is behind `os.name == "nt"` | none for a drive-letter path; for a share path one `os.stat` per ancestor, once per call |
  | 2 | **D1-a** a textual key as the write side's (`_write_key`) | the prefix forms only. It cannot name a machine's own names and addresses, and the write side leaves `//localhost/C$` apart from `C:` too (BF-911 adds identity for that) | unchanged | decided on its text | by text | the write side's rules (case folding, trailing dots and spaces dropped) would make distinct POSIX names equal, so a permitted root would admit more. They must not be applied there | none |
  | 3 | **D1-c** refuse a spelling that cannot be matched to a local drive | complete for local aliases, by refusing every share path | refused: a compatibility break. It needs an operator escape (a config list of admitted shares) with a default, and a default that admits leaves the property unset | the prefix form is matched to a drive by text and admitted | by text | unchanged | none |
  | 4 | **D1-b** the operating system's final path name | no: this is what `Path.resolve()` already asks. For a handle opened by a share spelling of the local drive, the final path name is the share path (DOS and NONE flags), the redirector's device path (NT flag) or a failure (GUID flag), and the extended prefix is kept when it was given | | | cannot be asked: the file must exist | | |

  D1-d is D1-a's pure text step first (the prefix forms need no I/O and cover a root that is not on disk) and the system's own answer to "is this the same file" second. D1-a alone is rank 2 because it leaves exactly the host-name spellings undecided. D1-c is rank 3 because it breaks legitimate network reads for a property D1-d reaches without that.
- **D2, what the function returns. Chosen: the resolved path, as before, in the spelling `Path.resolve()` gave it.** The decision is made on the namespace-free text and the identity; the return value is not rewritten. A rewritten path (the extended prefix dropped) can name a different file than the one decided on, and it can lose the prefix a long local path needs to open. So for every admitted call the path returned is a resolved path (`Path(returned).resolve() == Path(returned)`) in the spelling `Path(raw).resolve()` gave (relative paths resolved against `relative_base` as before), and it names the file the decision was about (T1; T9 pins the exact string for the ordinary and the extended spelling). `read_verified_file` and `read_bounded_utf8` compare the returned path with their own lexical candidate: they see exactly what they saw.
- **D3, operator escape. None.** No config field is added, and nothing that was admitted for a reason other than its spelling is refused: a path on another machine's share stays admitted when no root is, or contains, that file by identity (T10). D1-c is the only option that needs an escape, and it is not chosen.
- **D4, where the new branch runs.** `_longest_match` first tests containment as before. Only if that fails, on Windows, and only if the path or the root starts with two backslashes, does it compare the namespace-free keys (`PureWindowsPath`, case-insensitive), and only if a key still has a drive that starts with two backslashes (a share, a volume or a device) does it compare identities. A drive-letter path against drive-letter roots costs nothing more than before (T9).
- **D5, identity.** `_file_identity(path)` is `(st_dev, st_ino)` from `os.stat`, or `None` when the file is not on disk, cannot be read, or its filesystem gives no file index (zero). `_OnDisk` holds the identities of the path and every ancestor of it that is on disk, read once per `resolve_read_path` call and only when first asked; the three root lists share it. A root contained by identity is one whose identity is among them. This covers a file root (a config file) and a directory root alike.
- **D6, compatibility, and how it is tested.**
  - On another platform the new branch never runs: decisions and return values are those of the base (T8 pins the POSIX names that must stay distinct: case, trailing dot and space, backslashes in a name).
  - On Windows a drive-letter path decided against drive-letter roots gets the same decision, the same return value and no extra I/O (T9, T1's ordinary rows).
  - Every admitted call returns what it returned (T1, T9). The only decisions that change are those of the spellings in §1: the 9, and the trailing space for a file that is not on disk (T1 to T4, red on the base in M1).
  - A path no root covers stays admitted, and a root that is not on disk is matched by text only (T10).
- **D7, fences.** BF-953 changes neither `src/probos/cognitive/swe_harness/tools.py` nor `tests/test_bf948_list_files_read_policy.py`: BF-948's M4 edits `tools.py` around `:460-467` and the tail of that test file by SEARCH. This contract's tests import five names from the BF-948 test file's head (`_OUTSIDE`, `_PROTECTED`, `_list`, `_runtime`, `_scene`; lines `:28-29`, `:44`, `:61`, `:72`) and do not edit it. If BF-948's M4 renames any of them, that is BF-948's amendment to carry. No blocking question: the design needs neither file changed.

## 4. Milestones and gates

| M | Tier | Why | Pairs | Gate |
|---|---|---|---|---|
| M1 | STANDARD | test only, no `src`; its strength is the strict xfails failing on the base for the reason they name, and the premise asserts | B1-1 | G1 |
| M2 | HIGH | a public function's decisions for every consumer (the read floor) | B2-1 to B2-11 | G2 |
| M3 | STANDARD | trackers | B3-1, B3-2, the ledger | G3 |

Run each gate command as one file at a time with `-n 0`.

- **G1 (red).** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf953_read_floor_spellings.py -q -n 0`. Expected on a Windows host that serves every spelling (measured on this one, scratch copy of `728e1fc2`, home-guarded): **42 passed, 61 xfailed, 2 skipped, 0 failed** (105 tests: T1 to T4 are 20 cases each; the two skips are T3's stream-suffix case, a file-only spelling, and T8, POSIX only). On the `ubuntu-latest` runner, derived from the file (not run: this host is Windows): **1 passed (T8), 22 xfailed (T5, T6, T7), 82 skipped (every Windows-only case)**. Any other count, or an XPASS, is a hard stop back to the Architect. `--runxfail` shows each red for its marked reason: `AttributeError` for the missing helpers (T5, T6, T7, T9, T10) and an `AssertionError` naming the spelling and the decision for the 37 family cases.
- **G2 (green).** After M2: the same file, **103 passed, 2 skipped, 0 failed, 0 xfailed** (this host, scratch copy of `728e1fc2` with M1 and M2 applied from this contract's blocks; on the Linux runner, derived: 23 passed, 82 skipped). Then, one file at a time with `-n 0`, each unchanged by BF-953: `tests/test_bf758_file_read_confinement.py` (24 passed, 1 skipped), `tests/test_bf908_floor_and_children.py` (39 passed, 1 skipped), `tests/test_bf911_protected_config_write_refusal.py` (119 passed), `tests/test_bf948_list_files_read_policy.py` (17 passed), `tests/test_ad1200_instruction_file_access.py` (40 passed), `tests/test_ad1200_repository_instructions.py` (98 passed), `tests/test_ad1316_real_effect_routes.py` (67 passed, 2 skipped). Expected: those counts, 0 failed. Then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`.
- **G3.** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`; `... scripts/gen_ad_ledger.py --check`; `... -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. Expected: the generator rewrites `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (stage what it writes), `--check` says the ledger is current, and the test file gives **33 passed**. Run the test only after the regeneration: before it the file fails with "open-ads-report.md is stale".

The broad gate runs once for the batch (BF-948, BF-953), after the Diff Reviewer's repairs: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf948-bf953 --receipt logs/gates/bf948-bf953.receipt.json`. Not run here.

## 5. Commit messages

- M1: `BF-953 M1: reproductions of one file decided differently by spelling`
- M2: `BF-953 M2: the read floor decides every spelling of one file the same way`
- M3: `BF-953 M3: trackers and ledger`

## 6. Tests (`tests/test_bf953_read_floor_spellings.py`)

BF-953 owns every spelling test. A Windows-only case is skipped off Windows, and on Windows a spelling the host does not serve is skipped after its premise (`os.path.samestat` of the spelling and the ordinary path) fails, so a skip is never a pass. The families are one list (`_FAMILIES`); the spellings are built from the fixture path by `_spellings`.

| Id | Test | Covers | xfail until |
|---|---|---|---|
| T1 | `test_every_spelling_gets_the_decision_of_the_ordinary_spelling` (20 families) | floor (directory root, file root), exempt over floor, permitted, a file that is not on disk, the path returned | M2, for the 9 families of §1 and, for a file not on disk, the trailing space (10) |
| T2 | `test_read_file_decides_every_spelling_alike` (20) | consumer: `ReadFileTool` | M2, the same 9 |
| T3 | `test_list_files_decides_every_spelling_of_a_directory_alike` (20) | consumer: `ListFilesTool` on BF-948's rig; premise: the ordinary spelling is refused first | M2, the same 9 |
| T4 | `test_the_read_floor_refuses_every_spelling_of_a_config_file_the_write_side_refuses` (20) | write-side parity | M2, the same 9 |
| T5 | `test_the_namespace_free_form` (15 cases, any platform) | the pure canonicaliser | M2 (helper) |
| T6 | `test_the_namespace_free_form_agrees_with_the_write_sides_key` (any platform) | write-side parity, pure | M2 (helper) |
| T7 | `test_file_identity_is_the_file_the_system_names` (any platform) | the identity helper, including the zero-index rule | M2 (helper) |
| T8 | `test_a_posix_name_keeps_what_a_permitted_root_admits` (POSIX only) | nothing widens on POSIX | none: passes on the base |
| T9 | `test_a_drive_letter_path_costs_no_identity_lookup` (Windows) | compatibility; no extra I/O | M2 (helper) |
| T10 | `test_a_share_path_no_root_covers_stays_admitted` (Windows) | a legitimate network path stays admitted; identity decides containment | M2 (helper) |

## 7. The contract

**Pair grammar.** A pair belongs to the line `**B2-1** \`path\`` above it (the path is the first backticked token). The section runs to the next line that starts with `**B`, `## ` or `### `. Inside it, each `SEARCH:` line outside a fence, with the fenced block that follows, and the next `REPLACE:` line with its fenced block, is one pair. A fence is four backticks, optionally with a language tag, closed by four backticks; fenced text is verbatim, with LF line ends (the files are CRLF in the working tree; the applier keeps each file's own ends). Every SEARCH occurs exactly once in its file and pairs apply in order. A section marked `(new)` holds one fenced block: the whole new file. **No line inside an M1 or M2 fence starts with `**B`, `## ` or `### `.** Each of M3's two pairs holds such a line inside its fences (the PROGRESS paragraph starts with `**B`; the DECISIONS entry holds heading lines), so M3's pairs are applied with the `edit` tool, as BF-948's M3 was, or by an applier that ends a section only outside a fence. All 14 blocks (one new file and 13 pairs) were dry-run on a scratch copy of `728e1fc2` with a fence-aware applier (§13); M1 and M2 also parse under the plain "next `**B`, `## ` or `### ` line" rule.

### 7.1 M1

**B1-1** `tests/test_bf953_read_floor_spellings.py` (new)

````python
"""BF-953 (#1752): ``resolve_read_path`` returns one decision for every spelling of one file.

A path is decided the same way however it is spelled: for the floor (a directory root and a file root), for
the exempt roots that lift the floor, and for the permitted roots; and the path returned is the resolved
path, which names the file the decision was made on. The Windows spellings are built from fixture files this
test creates. A spelling the host does not serve is skipped once its premise (it names the same file as the
ordinary spelling) fails, so a skip is never a pass. The textual canonicaliser, the identity helper and the
POSIX rule run on every platform.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tools import ReadFileTool
from probos.security import file_access
from probos.security.file_access import FileAccessDenied, protected_write_refusal, resolve_read_path
from tests.test_bf948_list_files_read_policy import _OUTSIDE, _PROTECTED, _list, _runtime, _scene

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="BF-953: these are Windows path spellings")
_CONTENT = b"bf953 fixture"
_READ_PROTECTED = "read_file refused: path is protected: the runtime's data directory or a config file"
_READ_OUTSIDE = "read_file refused: path is outside every readable root"

_FAMILIES = [
    "forward slashes", "doubled separator", "dot segment", "dotdot via sibling dir", "dotdot via missing dir",
    "swapped case", "8.3 short name", "trailing dot", "trailing space", "default stream suffix", "device prefix",
    "extended prefix", "extended prefix, swapped case", "extended prefix, 8.3",
    "UNC localhost admin share", "UNC 127.0.0.1 admin share", "UNC computer-name admin share",
    "UNC extended localhost", "UNC extended computer-name", "UNC localhost, dotdot",
]
# The spellings the base decides differently from the ordinary one (measured on the committed head): the extended-length
# and share spellings and, for a file that is not on disk only (T1), a trailing space (the resolved path of a missing
# child of such a directory carries the extended-length prefix). M2 removes the marks.
_DECIDED_DIFFERENTLY = frozenset(_FAMILIES[11:])
_XFAIL = pytest.mark.xfail(strict=True, reason="BF-953: the base decides this spelling differently from the ordinary one")
_PARAMS = [pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY else name for name in _FAMILIES]
_PARAMS_T1 = [
    pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY | {"trailing space"} else name for name in _FAMILIES
]
_BASE_LACKS_IT = pytest.mark.xfail(strict=True, raises=AttributeError, reason="BF-953: M2 adds the helper this test calls")


def _short(text: str) -> str | None:
    """The 8.3 form of the existing path *text* the system gives, or None when the volume gives it none."""
    buffer = ctypes.create_unicode_buffer(1024)
    size = ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer))  # type: ignore[attr-defined]
    return buffer.value if 0 < size < len(buffer) and buffer.value.lower() != text.lower() else None


def _spellings(target: Path) -> dict[str, str]:
    """Spellings of the existing path *target* (a drive-letter path), built from the path itself."""
    text = str(target)
    drive, rest = os.path.splitdrive(text)
    letter, parent, name = drive[0], str(target.parent), target.name
    parent_rest = rest.rsplit("\\", 1)[0]
    computer = os.environ.get("COMPUTERNAME", "")
    short = _short(text)

    def share(host: str, tail: str = rest) -> str:
        return f"\\\\{host}\\{letter}${tail}"

    spelled = {
        "forward slashes": text.replace("\\", "/"),
        "doubled separator": text.replace("\\", "\\\\", 1),
        "dot segment": f"{parent}\\.\\{name}",
        "dotdot via sibling dir": f"{parent}\\..\\{target.parent.name}\\{name}",
        "dotdot via missing dir": f"{parent}\\no-such-dir-bf953\\..\\{name}",
        "swapped case": text.swapcase(),
        "trailing dot": text + ".",
        "trailing space": text + " ",
        "device prefix": "\\\\.\\" + text,
        "extended prefix": "\\\\?\\" + text,
        "extended prefix, swapped case": "\\\\?\\" + text.swapcase(),
        "UNC localhost admin share": share("localhost"),
        "UNC 127.0.0.1 admin share": share("127.0.0.1"),
        "UNC extended localhost": "\\\\?\\UNC\\localhost\\" + letter + "$" + rest,
        "UNC localhost, dotdot": share("localhost", f"{parent_rest}\\..\\{target.parent.name}\\{name}"),
    }
    if target.is_file():
        spelled["default stream suffix"] = text + "::$DATA"
    if short:
        spelled["8.3 short name"] = short
        spelled["extended prefix, 8.3"] = "\\\\?\\" + short
    if computer:
        spelled["UNC computer-name admin share"] = share(computer)
        spelled["UNC extended computer-name"] = "\\\\?\\UNC\\" + computer + "\\" + letter + "$" + rest
    return spelled


def _spelling_or_none(family: str, target: Path) -> str | None:
    """The *family* spelling of the existing *target*, or None when this host has none or does not serve it."""
    spelling = _spellings(target).get(family)
    if spelling is None:
        return None
    try:
        same = os.path.samestat(os.stat(spelling), os.stat(target))
    except OSError:
        same = False
    return spelling if same else None


def _spelling(family: str, target: Path) -> str:
    spelling = _spelling_or_none(family, target)
    if spelling is None:
        pytest.skip(f"BF-953 premise: this host has no {family} spelling that names {target.name}")
    return spelling


def _fixture(tmp_path: Path) -> SimpleNamespace:
    """A floor directory holding an exempt directory, a config file with a neighbour, a permitted directory and one outside.

    Every name is long, so that the volume gives each an 8.3 name when it makes them."""
    root = tmp_path.resolve()
    lay = SimpleNamespace(
        data=root / "floor data directory",
        work=root / "floor data directory" / "work area directory",
        allowed=root / "allowed directory long name",
        outside=root / "outside directory long name",
        config=root / "config directory long name" / "loaded config long name.yaml",
    )
    for directory in (lay.work, lay.allowed, lay.outside, lay.config.parent):
        directory.mkdir(parents=True)
    lay.floor_note = lay.data / "floor note long name.txt"
    lay.work_note = lay.work / "work note long name.txt"
    lay.allowed_note = lay.allowed / "allowed note long name.txt"
    lay.outside_note = lay.outside / "outside note long name.txt"
    lay.neighbour = lay.config.parent / "neighbour file long name.yaml"
    for note in (lay.floor_note, lay.work_note, lay.allowed_note, lay.outside_note, lay.config, lay.neighbour):
        note.write_bytes(_CONTENT)
    return lay


def _decide(raw: str, *, protected: Any = (), exempt: Any = (), permitted: Any = None) -> tuple[str, str]:
    """The whole decision of one call: ``("admitted", <path returned>)`` or ``("refused", <reason>)``."""
    try:
        resolved = resolve_read_path(
            raw, protected_roots=list(protected), exempt_roots=list(exempt), permitted_roots=permitted,
        )
    except FileAccessDenied as exc:
        return "refused", exc.reason
    return "admitted", str(resolved)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS_T1)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(tmp_path: Path, family: str) -> None:
    """T1: each spelling of a file is decided as its ordinary spelling is, against a directory root and a file root of
    the floor, an exempt root under the floor, and a permitted root; so is a file that is not on disk; and the path an
    admitted call returns is the resolved path and names the file."""
    lay = _fixture(tmp_path)
    floor = [lay.data.resolve(), lay.config.resolve()]
    exempt, permitted = [lay.work.resolve()], [lay.allowed.resolve()]
    cases = [
        (lay.floor_note, {"protected": floor, "exempt": exempt}, "refused"),
        (lay.config, {"protected": floor}, "refused"),
        (lay.neighbour, {"protected": floor}, "admitted"),
        (lay.work_note, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed_note, {"permitted": permitted}, "admitted"),
        (lay.outside_note, {"permitted": permitted}, "refused"),
    ]
    for target, roots, expected in cases:
        ordinary = _decide(str(target), **roots)
        assert ordinary[0] == expected, f"premise: the ordinary spelling of {target.name}: {ordinary}"
        spelled = _decide(_spelling(family, target), **roots)
        assert spelled[0] == expected, f"{family} of {target.name}: {spelled}"
        if expected == "refused":
            assert spelled[1] == ordinary[1], f"{family} of {target.name}: another reason"
        else:
            assert Path(spelled[1]) == Path(spelled[1]).resolve(), "the path returned is a resolved path"
            assert os.path.samestat(os.stat(spelled[1]), os.stat(target)), "the path returned names the file"
    missing = [
        (lay.data, {"protected": floor}, "refused"),
        (lay.work, {"protected": floor, "exempt": exempt}, "admitted"),
        (lay.allowed, {"permitted": permitted}, "admitted"),
        (lay.outside, {"permitted": permitted}, "refused"),
    ]
    for directory, roots, expected in missing:
        absent = "missing note long name.txt"
        assert _decide(str(directory / absent), **roots)[0] == expected, "premise: the ordinary spelling"
        spelling = _spelling_or_none(family, directory)
        if spelling is not None:
            assert _decide(spelling + "\\" + absent, **roots)[0] == expected, f"{family}, not on disk"


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_read_file_decides_every_spelling_alike(tmp_path: Path, family: str) -> None:
    """T2: ``ReadFileTool`` answers every spelling of a file as it answers the ordinary one."""
    scene = _scene(tmp_path)
    floor_note = scene.data / "floor note long name.txt"
    allowed_note = scene.allowed / "allowed note long name.txt"
    outside_note = scene.outside / "outside note long name.txt"
    for note in (floor_note, allowed_note, outside_note):
        note.write_bytes(_CONTENT)
    cases = [
        (floor_note, [], _READ_PROTECTED),
        (outside_note, [scene.allowed], _READ_OUTSIDE),
        (allowed_note, [scene.allowed], None),
    ]
    for note, read_roots, refusal in cases:
        tool = ReadFileTool(_runtime(scene, read_roots=read_roots))
        ordinary = await tool.invoke({"path": str(note)})
        assert ordinary.error == refusal, f"premise: the ordinary spelling of {note.name}: {ordinary.error}"
        spelled = await tool.invoke({"path": _spelling(family, note)})
        assert spelled.error == refusal, f"{family} of {note.name}: {spelled.error}"
        if refusal is None:
            assert "bf953 fixture" in repr(spelled.output)


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
async def test_list_files_decides_every_spelling_of_a_directory_alike(tmp_path: Path, family: str) -> None:
    """T3: ``list_files`` asks the same function for its base and for each match, on BF-948's rig. The ordinary
    spellings are decided first (the premise); then a spelling of the floor directory is refused, a spelling of a
    directory outside the permitted root is refused, and a spelling of the permitted root and of the agent
    workspace under the floor is listed."""
    scene = _scene(tmp_path)
    (scene.allowed / "allowed note long name.txt").write_bytes(_CONTENT)
    assert (await _list(scene, [], "*", str(scene.data))).error == _PROTECTED  # premise
    assert (await _list(scene, [scene.allowed], "*", str(scene.outside))).error == _OUTSIDE  # premise
    listed = await _list(scene, [scene.allowed], "*", str(scene.allowed))
    assert listed.error is None and {Path(n).name for n in listed.output["files"]} == {
        "allowed note long name.txt", "ok.txt", "sub",
    }  # premise
    assert (await _list(scene, [], "*", str(scene.workspace))).error is None  # premise: the exemption lifts the floor
    refused_floor = await _list(scene, [], "*", _spelling(family, scene.data))
    assert refused_floor.error == _PROTECTED and refused_floor.output is None, family
    refused_outside = await _list(scene, [scene.allowed], "*", _spelling(family, scene.outside))
    assert refused_outside.error == _OUTSIDE and refused_outside.output is None, family
    spelled = await _list(scene, [scene.allowed], "*", _spelling(family, scene.allowed))
    assert spelled.error is None, f"{family}: {spelled.error}"
    assert {Path(n).name for n in spelled.output["files"]} == {"allowed note long name.txt", "ok.txt", "sub"}, family
    workspace = await _list(scene, [], "*", _spelling(family, scene.workspace))
    assert workspace.error is None and [Path(n).name for n in workspace.output["files"]] == ["scratch.txt"], family


@WINDOWS
@pytest.mark.parametrize("family", _PARAMS)
def test_the_read_floor_refuses_every_spelling_of_a_config_file_the_write_side_refuses(
    tmp_path: Path, family: str,
) -> None:
    """T4: the write side refuses every spelling of the loaded config file (BF-911); so does the read floor."""
    lay = _fixture(tmp_path)
    runtime = SimpleNamespace(config_path=lay.config)
    configs = file_access.protected_config_files(runtime)
    assert lay.config.resolve() in configs, "premise: the runtime names the file"
    assert protected_write_refusal(str(lay.config), runtime=runtime) is not None, "premise: the write side refuses it"
    assert _decide(str(lay.config), protected=configs)[0] == "refused", "premise: the read floor refuses it"
    spelled = _spelling(family, lay.config)
    assert protected_write_refusal(spelled, runtime=runtime) is not None, f"{family}: the write side"
    assert _decide(spelled, protected=configs)[0] == "refused", f"{family}: the read floor"


_NAMESPACE_CASES = [
    ("\\\\?\\C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\?\\c:\\Data", "c:\\Data"),
    ("\\\\?\\C:", "C:"),
    ("\\\\.\\C:\\data", "C:\\data"),
    ("\\\\?\\UNC\\host\\share\\dir\\f.txt", "\\\\host\\share\\dir\\f.txt"),
    ("\\\\?\\unc\\host\\share", "\\\\host\\share"),
    ("C:\\data\\note.txt", "C:\\data\\note.txt"),
    ("\\\\host\\share\\dir", "\\\\host\\share\\dir"),
    ("\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data", "\\\\?\\Volume{4d83c44e-bb8a-4ae4-b23a-fe55aac6532d}\\data"),
    ("\\\\?\\1:\\data", "\\\\?\\1:\\data"),
    ("\\\\?\\CC:\\data", "\\\\?\\CC:\\data"),
    ("\\\\?\\C:data", "\\\\?\\C:data"),
    ("/srv/data/note.txt", "/srv/data/note.txt"),
    ("", ""),
    ("\\\\?\\", "\\\\?\\"),
]


@_BASE_LACKS_IT
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
def test_the_namespace_free_form(text: str, expected: str) -> None:
    """T5: pure text, the same on every platform: the extended and device prefixes of a drive path and the extended
    UNC prefix go; a volume or device name, a drive-relative form and a path of another platform stay."""
    assert file_access._namespace_free(text) == expected


@_BASE_LACKS_IT
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
def test_the_namespace_free_form_agrees_with_the_write_sides_key(text: str) -> None:
    """T6: for every spelling the canonicaliser rewrites, the write side's key (BF-911) of the text and of the rewrite
    are the same."""
    assert file_access._write_key(text) == file_access._write_key(file_access._namespace_free(text))


@_BASE_LACKS_IT
def test_file_identity_is_the_file_the_system_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T7: one identity for every name of a file, none for a path that names nothing, and none when the filesystem
    reports no file index."""
    note = tmp_path / "note.txt"
    note.write_bytes(_CONTENT)
    (tmp_path / "sub").mkdir()
    link = tmp_path / "note-link.txt"
    os.link(note, link)
    identity = file_access._file_identity(note)
    assert identity is not None
    assert file_access._file_identity(tmp_path / "sub" / ".." / "note.txt") == identity == file_access._file_identity(link)
    assert file_access._file_identity(tmp_path / "sub") != identity
    assert file_access._file_identity(tmp_path / "missing.txt") is None
    assert file_access._file_identity(Path("bad\x00name")) is None
    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", lambda _path: SimpleNamespace(st_dev=7, st_ino=0))
        assert file_access._file_identity(note) is None


@pytest.mark.skipif(os.name == "nt", reason="BF-953: on Windows these names are one directory")
def test_a_posix_name_keeps_what_a_permitted_root_admits(tmp_path: Path) -> None:
    """T8: on POSIX the names that differ by case, a trailing dot or space, a backslash or a Windows-looking prefix are
    other directories, and none of them is inside the permitted root."""
    root = tmp_path.resolve()
    names = ["allowed", "Allowed", "allowed.", "allowed ", "allowed\\x", "\\\\?\\allowed", "\\\\localhost\\allowed"]
    for name in names:
        (root / name).mkdir()
        (root / name / "note.txt").write_bytes(_CONTENT)
    assert len(list(root.iterdir())) == len(names), "premise: every name is its own directory"
    permitted = [root / "allowed"]
    assert _decide(str(root / "allowed" / "note.txt"), permitted=permitted)[0] == "admitted"
    for name in names[1:]:
        assert _decide(str(root / name / "note.txt"), permitted=permitted) == (
            "refused", "path is outside every readable root",
        ), name
    assert _decide(f"{root / 'allowed'}\\note.txt", permitted=permitted)[0] == "refused"


@WINDOWS
@_BASE_LACKS_IT
def test_a_drive_letter_path_costs_no_identity_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T9: a drive-letter path against drive-letter roots, and an extended-prefix local path (decided on its text),
    ask the system for no identity; the path returned is unchanged."""
    lay = _fixture(tmp_path)
    asked: list[Path] = []
    monkeypatch.setattr(file_access, "_file_identity", lambda path: asked.append(path))
    roots = {"protected": [lay.data.resolve()], "exempt": [lay.work.resolve()], "permitted": [lay.allowed.resolve()]}
    plain = _decide(str(lay.allowed_note), **roots)
    extended = _decide("\\\\?\\" + str(lay.allowed_note), **roots)
    assert plain == ("admitted", str(lay.allowed_note)) and extended == ("admitted", "\\\\?\\" + str(lay.allowed_note))
    assert asked == []


@WINDOWS
@_BASE_LACKS_IT
def test_a_share_path_no_root_covers_stays_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T10: containment of a share path is decided by identity. With the system's answers replaced (no host is
    contacted), a share path that is not the root and has no ancestor that is the root is not inside it, and one
    that has is."""
    root = _fixture(tmp_path).data.resolve()
    absent_root = root.parent / "no-such-root"
    same_as_root = Path("\\\\bf953-alias\\share\\floor")
    known = {root: (1, 1), same_as_root: (1, 1), absent_root: None}
    monkeypatch.setattr(file_access, "_file_identity", lambda path: known[path] if path in known else (2, hash(path)))
    elsewhere = Path("\\\\bf953-remote\\share\\dir\\note.txt")
    inside = same_as_root / "sub" / "note.txt"
    assert file_access._longest_match(elsewhere, [root]) is None
    assert file_access._longest_match(inside, [root]) == root
    assert file_access._longest_match(same_as_root, [root]) == root
    assert file_access._longest_match(inside, [absent_root]) is None
````

### 7.2 M2

**B2-1** `src/probos/security/file_access.py`

SEARCH:
````python
def _depth(root: Path) -> int:
    return len(root.parts)


def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``."""
    best: Path | None = None
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                if best is None or _depth(root) > _depth(best):
                    best = root
        except (OSError, ValueError):
            continue
    return best
````
REPLACE:
````python
def _depth(root: Path) -> int:
    return len(root.parts)


# BF-953: one decision for every spelling of one file. ``Path.resolve()`` keeps the Windows extended-length
# prefix it is given and reports a share spelling of a local drive as the share path, so the textual test
# below saw each as another place. On Windows the text is first reduced to its namespace-free form
# (``_namespace_free``), and a path or root that still names a share or a device is also compared by the
# identity the system gives the file (``_file_identity``). Elsewhere containment is the textual test.
_NAMESPACE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_EXTENDED_UNC = "\\\\?\\UNC\\"


def _namespace_free(text: str) -> str:
    r"""BF-953: *text*, a path as ``str(WindowsPath)`` spells it, without its Windows namespace prefix.

    ``\\?\UNC\host\share\x`` is ``\\host\share\x``; ``\\?\C:\x`` and ``\\.\C:\x`` are ``C:\x``. Any other
    text (a volume or device name, a drive-relative form, a path of another platform) is returned as it is.
    Pure: it reads nothing and does not depend on the platform it runs on.
    """
    if text[:8].upper() == _EXTENDED_UNC.upper():
        return "\\\\" + text[8:]
    if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and text[4:5].isalpha() and text[5:6] == ":":
        if text[6:7] in ("", "\\"):
            return text[4:]
    return text


def _file_identity(path: Path) -> tuple[int, int] | None:
    """BF-953: the identity the system gives the file *path* names, ``(volume, file index)``.

    ``None`` when it is not on disk, cannot be read, or its filesystem reports no file index (zero).
    """
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino) if info.st_ino else None


class _OnDisk:
    """BF-953: the identities of a path and of each ancestor of it that is on disk, read once and only when asked."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._found: frozenset[tuple[int, int]] | None = None

    def holds(self, identity: tuple[int, int]) -> bool:
        if self._found is None:
            found = (_file_identity(part) for part in (self._path, *self._path.parents))
            self._found = frozenset(ident for ident in found if ident is not None)
        return identity in self._found


def _longest_match(resolved: Path, roots: Iterable[Path], on_disk: _OnDisk | None = None) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``.

    A root contains a path that is under it as spelled. On Windows (BF-953) it also contains a path that is
    under it once both are without a namespace prefix, and a path or root that still names a share or a
    device is contained when the path, or an ancestor of it, is the same file as the root
    (:func:`_file_identity`). A root with no identity, because it is not on disk, is matched by spelling
    only. *on_disk* lets the root lists of one decision read the path's identities once.
    """
    best: Path | None = None
    if on_disk is None:
        on_disk = _OnDisk(resolved)
    for root in roots:
        try:
            inside = resolved == root or resolved.is_relative_to(root)
            if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):
                key = PureWindowsPath(_namespace_free(str(resolved)))
                root_key = PureWindowsPath(_namespace_free(str(root)))
                inside = key == root_key or key.is_relative_to(root_key)
                if not inside and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):
                    root_id = _file_identity(root)
                    inside = root_id is not None and on_disk.holds(root_id)
            if inside and (best is None or _depth(root) > _depth(best)):
                best = root
        except (OSError, ValueError):
            continue
    return best
````

**B2-2** `src/probos/security/file_access.py`

SEARCH:
````python
    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.
    """
````
REPLACE:
````python
    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.

    BF-953: the decision is the same for every spelling of one file, for the floor, the
    exempt roots and the permitted roots (:func:`_longest_match`). What is returned is the
    resolved path itself, in the spelling it was resolved to, never a rewritten one: it
    names the file the decision was made on.
    """
````

**B2-3** `src/probos/security/file_access.py`

SEARCH:
````python
    protect = _longest_match(resolved, protected_roots)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots)
````
REPLACE:
````python
    on_disk = _OnDisk(resolved)  # BF-953: read at most once, and only if a root is compared by identity
    protect = _longest_match(resolved, protected_roots, on_disk)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots, on_disk)
````

**B2-4** `src/probos/security/file_access.py`

SEARCH:
````python
    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
````
REPLACE:
````python
    if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is None:
````

**B2-5** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
# The spellings the base decides differently from the ordinary one (measured on the committed head): the extended-length
# and share spellings and, for a file that is not on disk only (T1), a trailing space (the resolved path of a missing
# child of such a directory carries the extended-length prefix). M2 removes the marks.
_DECIDED_DIFFERENTLY = frozenset(_FAMILIES[11:])
_XFAIL = pytest.mark.xfail(strict=True, reason="BF-953: the base decides this spelling differently from the ordinary one")
_PARAMS = [pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY else name for name in _FAMILIES]
_PARAMS_T1 = [
    pytest.param(name, marks=_XFAIL) if name in _DECIDED_DIFFERENTLY | {"trailing space"} else name for name in _FAMILIES
]
_BASE_LACKS_IT = pytest.mark.xfail(strict=True, raises=AttributeError, reason="BF-953: M2 adds the helper this test calls")
````
REPLACE:
````python
_PARAMS = list(_FAMILIES)
````

**B2-11** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@pytest.mark.parametrize("family", _PARAMS_T1)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(
````
REPLACE:
````python
@pytest.mark.parametrize("family", _PARAMS)
def test_every_spelling_gets_the_decision_of_the_ordinary_spelling(
````

**B2-6** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
````
REPLACE:
````python
@pytest.mark.parametrize(("text", "expected"), _NAMESPACE_CASES)
````

**B2-7** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
````
REPLACE:
````python
@pytest.mark.parametrize("text", [case[0] for case in _NAMESPACE_CASES if case[0] and case[0] != case[1]])
````

**B2-8** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@_BASE_LACKS_IT
def test_file_identity_is_the_file_the_system_names(
````
REPLACE:
````python
def test_file_identity_is_the_file_the_system_names(
````

**B2-9** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@WINDOWS
@_BASE_LACKS_IT
def test_a_drive_letter_path_costs_no_identity_lookup(
````
REPLACE:
````python
@WINDOWS
def test_a_drive_letter_path_costs_no_identity_lookup(
````

**B2-10** `tests/test_bf953_read_floor_spellings.py`

SEARCH:
````python
@WINDOWS
@_BASE_LACKS_IT
def test_a_share_path_no_root_covers_stays_admitted(
````
REPLACE:
````python
@WINDOWS
def test_a_share_path_no_root_covers_stays_admitted(
````

### 7.3 M3

M3 changes no `src` or `tests` file. Its pairs are B3-1 and B3-2 (§8), plus the ledger.

## 8. Tracking (M3's commit)

**Head constraint:** neither head may carry a lifecycle keyword from `gen_ad_ledger.py` `_STATUS_PATTERNS` (`:126-132`: retired, abandoned, withdrawn, superseded, deferred, postponed, closed, shipped, staged, landed, open) in its first 120 characters.
**Date rule:** both heads carry 2026-11-04. If M3 is committed on another local date (`git log -1 --format=%cs`), use that date in both heads.
**Issue number:** the heads carry `#1752` (the BF-953 issue, `gh issue view 1752`).
**Only insert.** Both pairs add text and change no line of BF-948's entries: BF-948's M4 amends those lines by SEARCH later (its P4-6 and P4-7), and each of those SEARCH strings must still occur exactly once after M3 (§13 checks it).
**Staging:** explicit paths only; `PROGRESS.md` and `DECISIONS.md` may hold unrelated work.

**B3-1** `PROGRESS.md`

SEARCH:
````
# ProbOS Progress

````
REPLACE:
````
# ProbOS Progress

**BF-953 (2026-11-04), #1752 -- the read floor decides every spelling of one file the same way.** `resolve_read_path` decided a path by comparing the text of its resolved form with the roots, so on Windows a path spelled with the extended-length prefix or as a share path of a local drive was decided differently from its ordinary spelling, for the floor, the exempt roots and the permitted roots. Now `_longest_match` compares each path and root without its namespace prefix, and a path or root that still names a share or device is also compared by the identity the system gives the file (volume and file index, read once per call and only for those spellings, on Windows only). The function returns the resolved path as before; no config field; other platforms are unchanged. The contract is `prompts/bf-953-read-floor-spellings.md`, with its own tests over `ReadFileTool`, `ListFilesTool` and the write side.

````

**B3-2** `DECISIONS.md`

SEARCH:
````
### BF-948 -- list_files lists only what the read policy admits (2026-11-04, #1736)
````
REPLACE:
````
### BF-953 -- The read floor decides every spelling of one file the same way (2026-11-04, #1752)

- *Scope.* `security/file_access.py` (`_longest_match`, `_namespace_free`, `_file_identity`, `_OnDisk`; `resolve_read_path`'s docstring and its three calls), tests. Contract `prompts/bf-953-read-floor-spellings.md`.
- *SP1 (the decision).* Containment is decided on the namespace-free text of the path and the root; a path or root that still names a share or device is also decided by file identity, read once per call and only for those spellings, on Windows only. Rejected: the textual key alone (it cannot name a machine's own names); the system's final path name (it reports what it was given); refusing every share path (it refuses a legitimate network path and needs an operator escape); identity for every path (a stat per ancestor on every read).
- *SP2 (the return).* The resolved path, as before. It names the file the decision was made on. Rejected: returning the rewritten text (it can name another file).
- *SP3 (no escape).* No config field and no operator escape: nothing admitted for a reason other than its spelling is refused.
- *SP4 (other platforms).* The textual test is the whole decision wherever `os.name` is not `nt`.
- *Residual.* Recorded limits L1 to L8 of the contract.
- *Reversal.* Revert the BF-953 commits.

### BF-948 -- list_files lists only what the read policy admits (2026-11-04, #1736)
````

Then regenerate the ledger (`python -P scripts/gen_ad_ledger.py`) and stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` as the tool writes them. **Not updated:** `docs/development/roadmap.md` (its Bug Tracker lists BFs filed and not fixed; BF-953 is fixed in this PR).

## 9. What this does NOT change

- `src/probos/cognitive/swe_harness/tools.py` and `tests/test_bf948_list_files_read_policy.py` (BF-948's M4 edits both by SEARCH); `ReadFileTool`, `ListFilesTool` and every other consumer.
- The write side: `protected_write_refusal`, `_write_key`, `_same_key`, `_canonical_name`, `_DEVICE_PREFIXES`, and BF-911's T19 parity (`_canonical_name`, `_SHORT_NAME`, `_HFS_IGNORABLE`).
- `permitted_read_roots`, `protected_read_roots`, `protected_config_files`, `workspace_exempt_roots` and `resolve_for_runtime`: the roots they build and how; `resolve_read_path`'s signature, its reasons and its return value.
- `read_verified_file` and `read_bounded_utf8`, `validate_read_location` and the pinned-directory code.
- Config, `EventType`, the tier table, goldens, and any other platform's decisions.

## 10. Mutation rows (campaign of record, run by the Architect on M2's head)

Prefix `SPM` (absent from `prompts/`, `DECISIONS.md` and `PROGRESS.md`: §Absence Verified A4). Line cells hold the source line without its leading indentation. **Campaign of record (2026-11-04).** Base tree: a scratch copy of `728e1fc2` with M1 and M2 applied from this contract's blocks (`git worktree add --detach`, removed afterwards). Files as the working tree held them: `src/probos/security/file_access.py` sha256 `381606bef4795b98adc3ab329666aaf616c91da4f72a8dd51d746fe65979287c` (CRLF working copy; `28ee43378c8bbce975d8f7d0b5eb09c939c468642d548246bba59729beeda675` with LF line ends) and `tests/test_bf953_read_floor_spellings.py` sha256 `cfd2deaa26a96df4f6a68934eeaebab3812412308b9a98a8090a92e009d343da`. Unmutated baseline: 103 passed, 2 skipped. Each row was run alone against the new file, one file at a time, `-n 0`, home-guarded: **all 16 killed, none survived**; the file was restored to the hash above afterwards. **A Builder whose two files match those hashes does not repeat the campaign.** If `file_access.py` differs, rerun every row; if only the test file differs, rerun the rows whose killer changed. The rows were run on Windows (where their branch is reached); on the Linux runner only SPM-1 to SPM-4 and SPM-12 are reachable.

| Id | File (relative to src/probos/) | Line (the exact source line, backticked) | Mutate to (backticked) | Killed by (T-number) |
|---|---|---|---|---|
| SPM-1 | `security/file_access.py` | `if text[:8].upper() == _EXTENDED_UNC.upper():` | `if False:` | T5 |
| SPM-2 | `security/file_access.py` | `return "\\\\" + text[8:]` | `return text[8:]` | T5, T6, T1 |
| SPM-3 | `security/file_access.py` | `if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and text[4:5].isalpha() and text[5:6] == ":":` | `if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and True and text[5:6] == ":":` | T5 |
| SPM-4 | `security/file_access.py` | `if text[6:7] in ("", "\\"):` | `if True:` | T5 |
| SPM-5 | `security/file_access.py` | `if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):` | `if False:` | T1, T2, T3, T4, T9, T10 |
| SPM-6 | `security/file_access.py` | the same line | `if not inside and os.name == "nt" and (str(resolved).startswith("\\\\") and str(root).startswith("\\\\")):` | T1, T2, T3, T4, T9, T10 |
| SPM-7 | `security/file_access.py` | `inside = key == root_key or key.is_relative_to(root_key)` | `inside = key == root_key` | T1, T2, T3, T9 |
| SPM-8 | `security/file_access.py` | `if not inside and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):` | `if False:` | T1, T2, T3, T4, T10 |
| SPM-9 | `security/file_access.py` | the same line | `if not inside:` | T9 |
| SPM-10 | `security/file_access.py` | `inside = root_id is not None and on_disk.holds(root_id)` | `inside = root_id is not None` | T1, T2, T3, T10 |
| SPM-11 | `security/file_access.py` | `found = (_file_identity(part) for part in (self._path, *self._path.parents))` | `found = (_file_identity(part) for part in (self._path,))` | T1, T2, T3, T10 |
| SPM-12 | `security/file_access.py` | `return (info.st_dev, info.st_ino) if info.st_ino else None` | `return (info.st_dev, info.st_ino)` | T7 |
| SPM-13 | `security/file_access.py` | `protect = _longest_match(resolved, protected_roots, on_disk)` | `protect = _longest_match(resolved, (), on_disk)` | T1, T2, T3, T4 |
| SPM-14 | `security/file_access.py` | `if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is None:` | `if permitted_roots and _longest_match(resolved, permitted_roots, on_disk) is not None:` | T1, T2, T3, T9 |
| SPM-15 | `security/file_access.py` | `return identity in self._found` | `return True` | T1, T2, T3, T10 |
| SPM-16 | `security/file_access.py` | `if text[:8].upper() == _EXTENDED_UNC.upper():` | `if text[:8] == _EXTENDED_UNC:` | T5 |

SPM-1 and SPM-16 are killed by T5 alone: an extended-UNC spelling that is not rewritten is still a share path, which the identity branch decides. SPM-9 is the cost row: it changes no decision, and T9 kills it by counting identity lookups.

## 11. Recorded limits

- **L1.** Identity is `(volume, file index)` as `os.stat` reports it. Two files that report the same pair, such as a file and the same file on a bit-identical copy of its volume, are one identity to this function. Only share and device spellings are decided by identity, on Windows.
- **L2.** A root that is not on disk has no identity and is matched by text only. The prefix forms are covered by the namespace-free comparison; a share spelling of the local drive naming a root that does not exist yet is not.
- **L3.** For a share or device spelling, a hard link of a file root (a config file) is the same file by identity and is decided like it. A drive-letter spelling of a hard link is decided by text, as before (the limit `protected_config_files` already records).
- **L4.** A share path costs one `os.stat` per ancestor, once per call, plus one per root compared; over a network share each is a round trip. A drive-letter path costs none (T9).
- **L5.** Each decision is by path and identity at the moment of the check (BF-758's limit). A link retargeted afterwards changes only what a name points to.
- **L6.** Other platforms: no identity layer. A hard link or a bind mount there is decided by path, as before; no spelling family exists there that `Path.resolve()` leaves apart.
- **L7.** A spelling whose drive does not start with two backslashes and that `Path.resolve()` leaves apart from the roots is not known; this contract names none, and T1 enumerates 20.
- **L8.** The write side's own coverage (BF-911) is not changed here; T4 pins that the two sides agree for the loaded config file in these 20 spellings.

## 12. For the Captain

You decide nothing for this build. It adds no config field, no escape and no tier change. Whether to check past use of these spellings on the live vessel is your call; this contract gives no steps for it. It lands in the BF-948 PR as its own commits, before BF-948's M4 (the Architect's order for that PR, §4 of BF-948's amended contract).

## 13. Verified Against Codebase (2026-11-04, on `728e1fc2`)

```
git rev-parse HEAD  (D:\ProbOS-worktrees\bf948-ca0ca20b)
  728e1fc2d2f49fd04584adf2a41d1dfa68befcb5
git diff --stat 9649df656fd3fbe846435b6b67f79e0ae96e3642 728e1fc2
  prompts/bf-948-list-files-read-policy.md | 430 +++...   (one file; 422 insertions, 8 deletions)
blobs equal at both heads: src/probos/security/file_access.py 004ea3991b, tests/test_bf948_list_files_read_policy.py d2282b897c,
  PROGRESS.md 2e7d32cc02, DECISIONS.md 09e596951a, src/probos/cognitive/swe_harness/tools.py fadc8fb71c

grep -n "^def _depth\|^def _longest_match\|^def resolve_read_path\|candidate.resolve()" src/probos/security/file_access.py
  88:def _depth(root: Path) -> int:
  92:def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
  105:def resolve_read_path(
  129:        resolved = candidate.resolve()
grep -n "_longest_match(" src/probos/security/file_access.py
  151:    protect = _longest_match(resolved, protected_roots)
  153:        exempt = _longest_match(resolved, exempt_roots)
  160:    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
grep -n "^from pathlib\|^import os\|^import ntpath\|PureWindowsPath" src/probos/security/file_access.py
  45:import os
  54:from pathlib import Path, PureWindowsPath
grep -n "_DEVICE_PREFIXES\|def _write_key\|def _same_key\|samestat" src/probos/security/file_access.py
  252:_DEVICE_PREFIXES = ("//?/", "//./")
  266:def _write_key(path_text: str) -> tuple[str, ...]:
  284:def _same_key(candidate: tuple[str, ...], protected: tuple[str, ...]) -> bool:
  367:        if os.path.samestat(current, config_stat):
grep -n "resolved != candidate\|resolve_read_path(" src/probos/security/file_access.py
  869:    resolved = resolve_read_path(
  871:    if resolved != candidate:
  933:        resolved = resolve_read_path(
  937:        if resolved != candidate or not resolved.is_relative_to(authorized_root):
grep -n "^_OUTSIDE\|^_PROTECTED\|^def _scene\|^def _runtime\|^async def _list" tests/test_bf948_list_files_read_policy.py
  28:_OUTSIDE = "list_files refused: path is outside every readable root"
  29:_PROTECTED = "list_files refused: path is protected: the runtime's data directory or a config file"
  44:def _scene(tmp_path: Path) -> _Scene:
  61:def _runtime(scene: _Scene, *, read_roots: list[Path]) -> SimpleNamespace:
  72:async def _list(
grep -n "read_file refused\|list_files refused" src/probos/cognitive/swe_harness/tools.py
  (ReadFileTool answers  f"read_file refused: {exc}"; ListFilesTool answers  f"list_files refused: {exc}")
grep -n "requires-python" pyproject.toml
  requires-python = ">=3.12"
```

Consumer search (§1 item 4), run on the committed head: `rg -n "resolve_read_path|resolve_for_runtime|protected_read_roots|permitted_read_roots|protected_config_files|workspace_exempt_roots|_longest_match|_ReadFloor" src` gave 85 hits in `agents/code_search.py` (19), `agents/directory_list.py` (2), `agents/file_reader.py` (2), `agents/file_search.py` (2), `agent_work_runner.py` (5), `cognitive/copilot_adapter.py` (6), `repository_instructions.py` (6), `security/file_access.py` (22), `tools/effect_tiers.py` (1, a comment), `cognitive/swe_harness/tools.py` (20). The same names in `tests` hit 7 files: `test_ad1200_instruction_file_access.py` (2), `test_ad1200_repository_instructions.py` (3), `test_ad1316_real_effect_routes.py` (1), `test_bf758_file_read_confinement.py` (20), `test_bf908_floor_and_children.py` (31), `test_bf911_protected_config_write_refusal.py` (3), `test_bf948_list_files_read_policy.py` (1); `scripts` none.

Measured on this host (Windows, Python 3.12.13), as premises of the design, with a throw-away fixture: for a file opened by each of the ordinary, extended-prefix and `localhost` share spellings, `os.stat` gives one `(st_dev, st_ino)`, equal to the ordinary spelling's, for the forward-slash, extended, `localhost`, `127.0.0.1`, computer-name, extended-UNC and device spellings; `Path.resolve()` keeps `\\?\C:\…`, `\\localhost\C$\…` and `\\?\UNC\localhost\C$\…` and returns `C:\…` for the device and forward-slash spellings; for the share-spelled handle `GetFinalPathNameByHandleW` returns the share path (DOS, NONE), the redirector's device path (NT) and fails (GUID).

Built and run on a scratch copy of `728e1fc2` (`git worktree add --detach`, removed afterwards), by the Architect, to settle the gate counts. Nothing was written in `D:\ProbOS` or in the BF-948 worktree; every test file ran alone, `-n 0`, through the home-guard runner.

```
fence-aware applier, labels B1-1 (new file, 352 lines), B2-1 .. B2-11, B3-1, B3-2:   DRY RUN OK: 14 blocks (1 new file, 13 pairs) in 4 files
plain "next **B / ## / ### line" rule: B1-1 and B2-1 .. B2-11 parse; B3-1 and B3-2 do not (their fences hold such lines), as §7 says
G1  M1 applied:           tests/test_bf953_read_floor_spellings.py   42 passed, 2 skipped, 61 xfailed        (exit 0)
    --runxfail:           every xfail fails for its marked reason (AttributeError for the missing helpers; AssertionError naming the spelling)
G2  M2 applied:           tests/test_bf953_read_floor_spellings.py   103 passed, 2 skipped                   (exit 0)
    consumers on M2:      test_bf758_file_read_confinement 24 passed, 1 skipped | test_bf908_floor_and_children 39 passed, 1 skipped
                          test_bf911_protected_config_write_refusal 119 passed | test_bf948_list_files_read_policy 17 passed
                          test_ad1200_instruction_file_access 40 passed | test_ad1200_repository_instructions 98 passed
                          test_ad1316_real_effect_routes 67 passed, 2 skipped
    check_architecture_principles.py --check:  architecture fitness check passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=13)
G3  M3 applied:           gen_ad_ledger.py wrote docs/development/open-ads-report.md and ad-ledger-snapshot.json (14 + 6 changed lines);
                          --check: AD/BF ledger is current; tests/test_ad1184_ad_ledger.py 33 passed
                          (the test fails until the ledger is regenerated: it passed on the base, failed on M1 to M3 before the regeneration, passed after it)
BF-948 M4 on the BF-953 head (M1 to M3 applied): apply_labelled.py prompts/bf-948-list-files-read-policy.md, labels P4-1 .. P4-7:   DRY RUN OK: 8 pairs in 5 files
```

## Absence Verified (2026-11-04, on `728e1fc2`)

```
A1 CLAIM: nothing outside file_access.py calls _longest_match
   RUN:   rg -n "_longest_match" src tests scripts
   FOUND: security/file_access.py:92 (def), :151, :153, :160 (the three calls)
   HOLDS: yes; the new third parameter is optional

A2 CLAIM: none of the new names exists anywhere on the head
   RUN:   git grep -n -E "_namespace_free|class _OnDisk|_file_identity|_NAMESPACE_PREFIXES|_EXTENDED_UNC" 728e1fc2 -- src tests scripts
   FOUND: (no hits; exit 1)
   HOLDS: yes. Near misses, by name only: `def _identity` in execution/workspace.py:127 (another module) and `_same_identity` in file_access.py:516 (compares two stat results for the pinned reader; no hashable key, no zero-index rule), so the new helper is named _file_identity and is separate (§15)

A3 CLAIM: no read-side code already reduces the namespace prefix of a path for containment
   RUN:   rg -n -F '\\?\' src/probos --glob '*.py'   (and the same pattern with two backslashes)
   FOUND: cognitive/swe_harness/tools.py:229-230 (a final path from a handle, for one verified source read), agents/code_search.py:414 (a docstring), security/file_access.py (the write side's _DEVICE_PREFIXES, :252)
   HOLDS: yes; none is a containment test

A4 CLAIM: the mutation prefix SPM is unused
   RUN:   rg -n -w "SPM-[0-9]+" prompts DECISIONS.md PROGRESS.md
   FOUND: (no hits; exit 1)
   HOLDS: yes

A5 CLAIM: BF-953 is held only by #1752, and BF-954 is free
   RUN:   gh issue list --state all --limit 4000 --json number,title,state (1,507 issues, filtered on BF-9[4-9][0-9]); git log --all --format=%s filtered the same way; Get-ChildItem prompts -Filter bf-95*; Select-String docs/development/roadmap.md,PROGRESS.md,DECISIONS.md -Pattern 'BF-95[3-9]'
   FOUND: issue titles carrying a BF-94x or BF-95x number: BF-940, 942, 943, 944, 945, 946, 947, 948, 949, 950, 952 (#1751, OPEN) and BF-953 (#1752, OPEN); commit subjects: BF-941, 946, 947, 948, 949, 951; prompts/bf-95*: none; trackers: none
   HOLDS: yes

A6 CLAIM: no existing test pins the read floor's decision for an extended-prefix or share spelling (so no test pins the defect)
   RUN:   rg -n "\\\\\\\\\?|UNC|localhost|127\.0\.0\.1" tests/test_bf758_file_read_confinement.py tests/test_bf908_floor_and_children.py tests/test_ad1200_instruction_file_access.py tests/test_ad1200_repository_instructions.py
   FOUND: (no hits). The only prefix and UNC pins are BF-911's pure write-key tables (tests/test_bf911_protected_config_write_refusal.py:190-193)
   HOLDS: yes
```

## 14. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** one private class (`_OnDisk`, one method) and three private helpers in `file_access.py`; no new module, no import (`os`, `PureWindowsPath` are already imported at `:45`, `:54`); only public names cross a module. The new test imports private names from the BF-948 test module and from `file_access`, as BF-911's tests do from `file_access` (`tests/test_bf911_protected_config_write_refusal.py:259`). G2 runs the check.
- **`check_dormant_classes.py`:** `_OnDisk` is constructed in `_longest_match` and `resolve_read_path`.
- **Config:** none. **EventType:** none. **Goldens:** none touched.
- **`gen_ad_ledger.py --check`:** passes once M3 regenerates; the heads carry no status keyword in their first 120 characters.
- **Collection:** one new test file; M1's strict xfails keep G1 green on the base.
- **Exceptions (three-tier):** `_file_identity` degrades (`OSError`/`ValueError` to `None`, the textual decision stands, which is what the base decided); `_longest_match` keeps its `OSError`/`ValueError` skip. Nothing is swallowed that the base propagated.

## 15. Prior Art and Blind Spots

- **Internal:** BF-758 (floor, policy, resolve before containment); BF-908 (the config files in the floor; `_ReadFloor`); BF-911 (the write side's key and its `os.stat` identity layer, whose idea this reuses for the read side); BF-948 review round 1 (finding 1, where this was found). Considered and not reused: `_same_identity` (`file_access.py:516`) compares two `os.stat_result`s, including the file type, for the pinned reader's chain checks; the read floor needs a hashable key and the zero-index rule, and merging the two would touch the pinned reader, so `_file_identity` stays separate.
- **External:** skipped. A Windows-only path-identity matter with no outside design question.
- **Blind spots found:**
  1. The orchestrator's first probe rows for `ListFilesTool` were void (it imported the floor function by name, so a monkeypatch of the module name never reached it): T3 uses BF-948's rig, which passes the floor through the runtime, and asserts first that the ordinary spelling of the same directory is refused.
  2. The exempt scenario passed on the base only because no floor root matched the spelling: T1 asks the exemption on a spelling the floor now matches.
  3. A drive-letter-only text rewrite would have left the host-name spellings undecided (`_write_key` leaves them apart too).
  4. A rewrite of the returned path would lose the prefix a long local path needs (D2).

## 16. Diff Reviewer: properties to verify

This is a shared-contract change: review the whole candidate, every consumer in §1, not only the new lines.

1. For every spelling in `_FAMILIES`, `resolve_read_path` returns the decision the ordinary spelling gets, for the floor (directory root and file root), the exempt roots over the floor, and the permitted roots, whether or not the file exists, with the same refusal reason.
2. An admitted call returns `Path(raw).resolve()` exactly as the base did, and that path names the file the decision was about.
3. Every decision on a drive-letter path against drive-letter roots, on every platform, is the base's, and no `os.stat` is added for it. On a platform other than Windows nothing in `_longest_match` differs from the base in its result.
4. Nothing that the base refused and the new code admits: the new branch only adds matches (more refusals at the floor, more admissions at the permitted roots only where the same file is named). A path no root is, or sits under, by text or by identity stays as it was.
5. The exemption lifts the floor for each spelling that a floor root now matches, and only where the exempt root contains the path; a file under the floor but outside the exempt root is refused.
6. A root that is not on disk, a path that is not on disk, an `os.stat` failure and a zero file index each leave the textual decision standing.
7. `_namespace_free` is pure and is the same on every platform; `_write_key` and its parity with `builder_paths` (BF-911 T19) are unchanged.
8. `tools.py`, the BF-948 test file, every consumer, config and `EventType` are unchanged; the two tracker edits only insert; BF-948's P4-6 and P4-7 SEARCH strings still occur once each.
9. Every new or rewritten docstring, comment, error string and test docstring is true of the head in the code's branch order; no head text describes what can be read, from where or by whom.
10. Each test whose xfail mark M2 removes failed on the base for the reason its mark names; T8 passes on the base.

## 17. Acceptance criteria

1. Every spelling in `_FAMILIES` gets the ordinary spelling's decision from `resolve_read_path`, for the floor, the exempt roots and the permitted roots (T1), through `ReadFileTool` (T2), through `ListFilesTool` (T3), and for the loaded config file the write side agrees (T4).
2. The path returned is the resolved path and names the file (T1, T9). A drive-letter path costs no identity lookup (T9). A share path no root covers stays admitted (T10).
3. The canonicaliser is pure and the same everywhere (T5, T6); the identity helper follows the zero-index rule (T7); POSIX names stay distinct (T8).
4. Every §10 mutant is killed. G1 to G3 and the §14 checks pass, and the broad gate's receipt is green for the batch.
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
