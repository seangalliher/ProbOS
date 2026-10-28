# AD-1270 (#1324) slice 2: the dormant-class check -- a report-only scan for production classes nothing live uses, against a disposition-only baseline

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-27

**Status:** build-ready on `65f5e02b` (the merge of AD-1270 slice 1, PR #1691), re-anchored by the orchestrator (next paragraph); drafted on `894526c6` (slice 1's first candidate). Slice 1 changed none of the files this contract creates, and §8 anchors only on `# ProbOS Progress` and the `### Explicit delegation models...` line in `DECISIONS.md`. No new AD or BF number: this is slice 2 of #1324 (the queue in the slice-1 consult). **Captain:** no condition met (D8). Overrulable: D6 (the 43 typed events are `retire`), D4 (no test asserts real-tree findings).

**Re-anchored by the orchestrator (2026-10-27).** (1) **Base:** `origin/main` `65f5e02bd98805d6c8fce867e4d0b401bf5e2281`, the merge of AD-1270 slice 1 (PR #1691); its tree is `fae63e3b27b727d3aa5894cc021b5d896f815741`. (2) **What slice 1 changed:** `src/probos/runtime.py`, `bridge_alerts.py`, `watch_rotation.py`, `experience/commands/commands_autonomous.py`, its tests and the trackers. (3) **Line numbers re-read on the new tree:** the three citations into `runtime.py` (§0 twice, §11 once) are renumbered (`3057-3110` is now `3059-3118`, `3115` is now `3125`, `3040-3114` is now `3046-3126`); `watch_rotation.py:216` and `ontology/service.py:105` still hold. Every other cited line is in a file slice 1 did not change. (4) **Trackers:** slice 1's DECISIONS entries sit immediately before the `### Explicit delegation models...` heading, so pair U2 places this entry between them and that heading, "after slice 1's entries", as §8 says; pair U1 places this paragraph first after the title, before slice 1's. (5) **File name:** the contract is committed as `prompts/ad-1270-dormant-class-check.md`, which the §8 PROGRESS text already names.

**Milestones and tiers:**
- **M1, the check** (`scripts/check_dormant_classes.py`, its tests, the generated baseline seeded from §7.3). **STANDARD**: tooling, report-only.
- **Review step** (orchestrator ↔ Architect, no commit): dispositions for every row M1 leaves `unreviewed`.
- **M2, dispositions and trackers** (the baseline rows from the review step, `PROGRESS.md`, `DECISIONS.md`, the regenerated AD ledger). **docs**.

Each milestone is one Builder delegation and one local commit, staged by explicit path, never `git add -A`. The broad gate is the orchestrator's single run after M2: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-dormant-classes --receipt logs/gates/ad1270-dormant-classes.receipt.json`. One mutation campaign runs on the M1 tree (§10).

**Tests:** new `tests/test_ad1270_dormant_classes.py` (M1), predicted 18 cases. No test touches a live system, the real data directory or the real baseline file (the one real-tree case only reads it).

**Line endings:** new files are written LF; the script writes the baseline with `newline="\n"` and its output as UTF-8 bytes with LF.

**Amendment A1 (2026-10-27, after round 1 of the M1 review; `claude-architect`).** A1 repairs M1 (`935acb6a`) in one commit before M2, by the pairs in §7.4. §7.1 to §7.3 keep M1's text; where §7.4 differs, §7.4 wins.
1. **F1:** an import alias counts as its original name where the importing module uses it as a value or a base (D1, D2). The review step's 14 alias rows leave the scan, so the baseline at A1 holds 171 rows: the 52 seeds and 119 for the review step's table (predicted).
2. **F3:** `main` answers `--help` itself, prefix first, through `_emit`.
3. **F4 to F6:** three false statements are narrowed: `HEADER` and the module docstring ("reviewed"), `render_baseline`'s docstring (absolute paths) and `_emit`'s (LF on a text-only stdout).
4. **Recorded, not repaired:** round 1's F2 (R7) and the `NullPolicyEngine` recall limit (R8).
5. **Tests:** T9 and T10 are added, so the file is predicted at 20 cases.
6. **Mutation campaign:** the §10 campaign of record moves to the A1 commit, and every row D-1 to D-64 reruns on it. M1's campaign (51 of 51 killed) is superseded because both pinned files change.
7. **Baseline:** `--update-baseline` regenerates it at A1; it is not edited by a pair (§7.4).

**Measured by the orchestrator (2026-10-27; on the oracle and the Builder's tree for repair 1 `d0bd90a2`, and for M2).** Every prediction above held. **Repair 1:** with M1's script and only the repaired test file, 18 cases pass and 2 fail (T9 at its first assertion, a list of ten keys instead of three; T10 at its second, stdout begins `usage:` with CRLF); on the A1 commit 20 cases pass, 69 with BF-926's file; `--update-baseline` prints `171 dormant class(es): 0 new, 119 without a reviewed disposition, 0 baseline row(s) no longer dormant` (`--check`: 120 lines), and the baseline differs from M1's by 1 insertion and 29 deletions (the first line and the 14 alias rows); `--help` starts `DORMANT CLASSES (report-only): help; nothing checked` with no CR; the real-tree scan takes 4.8 s on a loaded host; `check_architecture_principles.py --check` passes. Two independent routes (the oracle applying the seven pairs by tool, a Builder on `claude-sonnet-5.5` editing M1's files) agree blob for blob on the three files. The campaign of record (§10, rows D-1 to D-64, on `d0bd90a2`): baseline 20 passed, **all 64 rows killed**, none claimed-not-failing (D-27, D-43 and D-48 are killed on this Windows host). **M2:** the review step's 119 applicable rows are applied (wire 80, staged 21, retire 11, false-positive 7; with the 52 seeds: wire 86, staged 23, retire 54, false-positive 8, 171 rows) and `--check` prints `171 dormant class(es): 0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant`; a second, independent verifier that reads the Architect's table and the baseline YAML (field for field, the 52 seeds unchanged, the 14 alias rows absent, no extra field) passes, and every owner (#1324, #1335 = AD-1288, #1352 = AD-1299, #1565 = AD-1338, #1659 = AD-1353, #1557 = AD-1335) is an OPEN issue whose title carries that AD id. The `PROGRESS.md` and `DECISIONS.md` pairs carry the date 2026-10-27 in place of the placeholder; the AD ledger is regenerated in the real tree and current.

**Corrected by the orchestrator after round 2 (2026-10-28; round 2 was one `gpt-6.1-sol` reviewer over `935acb6a..e84f807d`, NOT READY on one finding).** F1 (P2, ordinary reach, a regression M2 introduced): `tools/work_permits.py::WorkPermit` and `::WorkPermitStore` were `wire` with owner `#1324`, on the premise that no open issue owns them; #1630 (AD-1348, PAUSED until the Captain lifts the new-capability pause) names the AD-1159 work permit in `src/probos/tools/work_permits.py` as the authority that lets a crew member drive its robot (its "Who drives" line, and acceptance requires operation under a live permit). Both rows are now `staged` with owner `AD-1348 (#1630)`, the Architect's own criterion for a staged row (an open issue names the work); the 119 applied rows become wire 78, staged 23, retire 11, false-positive 7 and, with the 52 seeds, wire 84, staged 25, retire 54, false-positive 8 (171 rows). The orchestrator then ran the check the round-2 sample could not: **all 79 open issues (title, body and every comment) against all 171 rows, by class name, source path and dotted module path** (`census_issue_owners.py`; evidence `evidence-ad1270dc-issue-owner-census*.txt`). #1630 is the only open issue that makes a baseline class the consumer of its own planned work; every other match is a path coincidence (a file name with a line number), the typed events' shared `events.py`, slice 3's own rows (#1566 cites AD-670), or one of the relations recorded in R15. The census covers open GitHub issues; it cannot show that no unfiled roadmap item owns a `wire` row, which is why R12 to R15 stay the Captain's list.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| The 2026-10-16 audit lists 120 classes with no production reference and 39 imported but never built | present | `logs/ad1270/dormant-audit-2026-10-16.md:14-15,39-210` |
| Its method missed loop and value construction | present | `runtime.py:3059-3118` (`test_cls()` over 25 probes); `startup/communication.py:226`; `recreation/service.py:64`; `cognitive_agent.py:5380` |
| Its method ignored live users in the class's own module | present | `duty_schedule.py:78` ← `startup/finalize.py:4230`; `provenance.py:115` ← `oracle_query_tool.py:319`; `crew_profile.py:566`; `file_walk.py:126,158` ← `agents/code_search.py:266`; `result_offload.py:293` ← `agentic_loop.py:1216`; `communication_benchmarks.py:665` ← `runtime.py:3125` |
| 22 listed classes are pydantic models behind a private base; one is a TypedDict | present | `elastic_team.py:160`, `elastic_commission.py:127`, `execution_profile.py:109`, `work_item_steps.py:122`, `crew_verdict.py:24`; `routers/readiness.py:27` |
| Still dormant: working memory, onboarding, 43 typed events, channel adapters and 44 plain classes | present | Absence AV1 to AV4 |
| `SystemHealthProvider` is gone | present | removed by `dac29856` (BF-920, 2026-10-24) |
| BF-926's sibling check: report-only, exit 0 on every input, `PREFIX`, `parse_known_args`, tests that load it by path | present | `scripts/check_config_readers.py:1-24,172-198`; `tests/test_bf926_config_readers.py:28-37,79-108` |
| Sibling baselines live in `docs/development/` as YAML with `--update-baseline` | present | `git ls-files docs/development/*baseline*`; `docs/development/config-facade-baseline.yaml:1-6` |
| `run_test_gate.py` runs an explicit list of check scripts | present | `scripts/run_test_gate.py:1105-1124` |
| The program forbids a second capability registry | present | `docs/development/platform-maturity-program.md:255,290` |

**Group E, the 43 typed event classes** (`src/probos/events.py`, `@dataclass` subclasses of `BaseEvent`): `AgentCapacityApproachingEvent`, `BuildFailureEvent`, `BuildGeneratedEvent`, `BuildProgressEvent`, `BuildResolvedEvent`, `BuildStartedEvent`, `BuildSuccessEvent`, `CascadeConfabulationEvent`, `CircuitBreakerTripEvent`, `ConsensusEvent`, `ConsultationCompletedEvent`, `ConsultationFailedEvent`, `ConsultationRequestedEvent`, `ConsultationTimeoutEvent`, `CorroborationProvenanceValidatedEvent`, `CorroborationVerifiedEvent`, `CounselorAssessmentEvent`, `DesignFailureEvent`, `DesignGeneratedEvent`, `DesignProgressEvent`, `DesignStartedEvent`, `DreamCompleteEvent`, `EmergenceMetricsEvent`, `HebbianUpdateEvent`, `ObservableStateMismatchEvent`, `PeerRepetitionDetectedEvent`, `ProcedureFallbackLearningEvent`, `SelfModFailureEvent`, `SelfModImportApprovedEvent`, `SelfModProgressEvent`, `SelfModRetryCompleteEvent`, `SelfModStartedEvent`, `SelfModSuccessEvent`, `SelfMonitoringConcernEvent`, `TaskExecutionCompleteEvent`, `TrustCascadeEvent`, `TrustUpdateEvent`, `WardRoomEchoDetectedEvent`, `WardRoomEndorsementEvent`, `WardRoomPostCreatedEvent`, `WardRoomThreadCreatedEvent`, `WardRoomThreadUpdatedEvent`, `ZoneRecoveryEvent`.

## 1. Problem

The 2026-10-16 built-but-dormant audit is the only list of #1324's integration debt, and it is stale and partly wrong.
- It is stale: one class is gone, and classes have been added since.
- It is partly wrong: at least 41 of its 159 classes are live, built in loops, passed as values or built by a live definition in their own module. 23 more are schema types.
- The script that produced it was never committed.

So slices 3 and 4 (working memory, onboarding) have no reproducible acceptance check, and nothing tells anyone when a new class lands unused.

## 2. Solution overview

- **M1:** `scripts/check_dormant_classes.py` scans `src/probos` with `ast` and lists dormant classes. A class is dormant when nothing live uses it as a value (§3, D1). It compares the list with `docs/development/dormant-class-baseline.yaml`, which records each class's reviewed disposition, and reports three kinds of finding: new classes, classes that are no longer dormant, and incomplete dispositions. It exits 0 on every input. `--update-baseline` keeps reviewed rows, adds new classes as `unreviewed` and drops classes that left. The Builder generates the baseline and applies the §7.3 dispositions.
- **Review step:** the Architect assigns a disposition to every remaining `unreviewed` row.
- **M2:** apply those dispositions, so `--check` reports no findings, then update the trackers.

## 3. Decisions

- **D1. A use is a value reference; reachability runs inside the module.**
  - Counted as uses: a call, `Name.x`, `module.Name`, a base, a decorator, the class passed as a value, and a string whose last `.` or `:` segment is the name.
  - **Aliases (A1).** After `from m import X as Y` anywhere in a module (a function body included), a value use of `Y` in that module counts as a use of `X`, and a base written `Y` reaches D3 as `X`. An alias that is only imported, or only used in an annotation, is not a use. Aliases are per module: two modules that alias different classes to one name each resolve only their own.
  - Not counted: imports, annotations, assignment targets, `__all__`, `isinstance`/`issubclass`, `is`/`is not` operands, and `if TYPE_CHECKING:` bodies.
  - A use from another module always counts. A use in the class's own module counts only from module-level code, from a top-level definition with a non-inert decorator, or from a top-level definition that is itself live (a fixed point).
  - Rejected: whole-program reachability from entry points (brittle: one missed root marks a subsystem dormant), and other-module uses only (the audit's false positives).
- **D2. Names are matched, not resolved, except an import alias (A1)** (vulture's model and BF-926's).
  - **What the check does.** It matches a use to every class of that name. It resolves `from m import X as Y` within the importing module (D1). `import m as n` needs no rule, because `n.X` reads `X`.
  - **So it under-reports.** Two classes with one name are live together, a use from a dormant module still counts, and a use of an alias counts every name its module imports under it.
  - **What it does not do.** It does not follow `getattr` or an import with a computed name, `config/`, an entry point, or an alias imported again under that alias from the module that made it. A class reached only that way is reported although it is live (R2, R3; AV7 finds no such class alias today).
  - **Measured on `935acb6a`** with the alias rule patched in (`logs/ad1270/evidence-ad1270dc-alias-probe.txt`): 185 dormant classes became 171, removing exactly the review step's 14 alias rows and adding none. A1's code also resolves bases and keeps every original an alias names. Both can only remove rows, and none is predicted on this tree.
  - Documented in the module docstring.
- **D3. Schema kinds and private classes are not reported:** Protocol, Enum family, exceptions, TypedDict, NamedTuple, and pydantic `BaseModel`/`RootModel`/`BaseSettings`, matched by base name transitively across the tree. Validation builds them, which AST cannot see. They are vocabulary, not capability.
- **D4. Report-only; no test asserts real-tree findings.** One real-tree case asserts exit 0 and the prefix only. The check is not a `run_test_gate.py` phase. Making it a phase, or adding a test that `--check` is clean, would make it a gate: HIGH and the Captain's call (as with BF-926).
- **D5. The baseline holds dispositions only.** One row per class: `disposition`, plus `owner` (an issue or AD) for `wire`, `retire` and `staged`, or `note` for `false-positive`. No description, status, AD tag, line count or test data. That keeps it a fitness baseline rather than a second capability registry (`platform-maturity-program.md:255`). Line numbers appear in the output only. Keys are `<POSIX path relative to src/probos>::<Class>`.
- **D6. Seeded dispositions (§7.3); everything else is `unreviewed` until the review step.**
  - The 43 typed events are `retire`: no producer builds them, and the wire format is the `EventType` plus a dict (`TrustUpdateEvent` lacks the emitted `old_score`). The deletion is a later slice with a DECISIONS entry.
  - Overrulable.
- **D7. Methods are out of scope.** `OntologyService.set_alert_condition` (no caller) stays on the register (R1). Name-matching methods would flood the report.
- **D8. Captain conditions: none.** No production code changes and nothing is deleted. No control is weakened, no gate is added, nothing is spent and nothing crosses the OSS boundary.

## 4. Milestones

Write the new test file first and run it on M1's base. It must fail at collection: `_load_checker()` raises `FileNotFoundError` because the script does not exist yet (predicted). If a test outside §7 fails, stop and report it. Run focused gates with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`.

| Milestone | Tier | Files | Focused gate |
|---|---|---|---|
| **M1** the check | STANDARD | 7.1 new `scripts/check_dormant_classes.py`; 7.2 new `tests/test_ad1270_dormant_classes.py`; 7.3 generated `docs/development/dormant-class-baseline.yaml` | `tests/test_ad1270_dormant_classes.py tests/test_bf926_config_readers.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --check` (paste the whole output into the report) |
| **Review step** | — | none | The orchestrator sends the `unreviewed:` lines and any seed with no row to the Architect |
| **M2** dispositions and trackers | docs | the baseline rows from the review step; §8 pairs; `python scripts/gen_ad_ledger.py`, then stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` | `--check` reports `0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant`; `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

**M1 build order:**
1. Write 7.2, then run it: it fails at collection.
2. Write 7.1, then run the focused gate.
3. Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --update-baseline`. It must print `baseline rewritten: docs/development/dormant-class-baseline.yaml`. If it prints `baseline not rewritten`, stop and report the warnings.
4. Edit the generated rows per §7.3. Never add a row the scan did not produce; list each seed with no row in the report.
5. Run `--update-baseline` again (it normalizes the file), then `--check`.
6. Commit the three files.

## 5. Consumers of every value this adds

| Value | Consumers | Effect |
|---|---|---|
| `scripts/check_dormant_classes.py` output | the orchestrator; the contracts for slices 3 and 4 ("these rows leave the list") | new; no production reader |
| `docs/development/dormant-class-baseline.yaml` | the script only | new data file; not read by `src/` or `ui/` |
| `run_test_gate.py` phases | unchanged | the check is not a phase (D4) |

## 6. Tests

On M1's base the new file fails at collection, so every case errors: `FileNotFoundError` from `spec.loader.exec_module` (predicted). There is no negative case that passes on the base.

(A1) With §7.4's test pair applied over `935acb6a`'s script, T1 to T8 pass and the two A1 cases fail (predicted):
- **T9** fails at its first assertion. The dormant list holds ten keys, not three: the seven classes reached through an alias or based on one are reported too.
- **T10** fails at its second assertion. stdout starts with `usage:`, not `PREFIX`.

| ID | Case | Proves |
|---|---|---|
| T1 | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` | every use and non-use rule in D1, the in-module fixed point, D3 exclusions, sorted keys |
| T2 | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` | the three finding kinds and their exact lines |
| T3 | `test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest` | merge semantics, LF bytes, ASCII header, idempotence |
| T4 | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline` ×3 | no rewrite that would lose reviewed rows |
| T5 | `test_the_check_exits_zero_on_every_input` ×9 | report-only on every input, including the real tree (exit and prefix only) |
| T6 | `test_the_command_line_exits_zero_with_lf_utf8_output` | the command line: exit 0, LF bytes, a finding line |
| T7 | `test_the_output_names_no_absolute_path` | host-independent output |
| T8 | `test_modules_are_read_in_posix_path_order_on_every_host` | Windows and Linux read modules in the same order |
| T9 | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` | (A1) an alias used as a value in a function, imported and used inside a function body, used at module level (two on one import line), naming a helper that builds a dataclass, and naming a schema base, counts as its original. An annotation-only alias, the same alias name in another module and a plain unused import do not. |
| T10 | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` | (A1) `--help` from the command line: prefix first, LF bytes, nothing scanned |

Predicted: 18 cases at M1 and 20 after A1; the focused list is predicted at those plus BF-926's file. The orchestrator measures both.

## 7. The contract

### 7.1 New file: `scripts/check_dormant_classes.py` (M1)

```python
"""AD-1270 (#1324): report production classes that nothing in production uses, against a reviewed baseline.

REPORT-ONLY: this check warns and never fails. Its exit status is 0 on every input -- a missing or
malformed baseline, a source file that does not parse, an unknown or incomplete argument --
because nothing may gate on it until the Captain decides to enforce it. It is a separate command:
``scripts/run_test_gate.py`` does not run it, and no test asserts what it finds in the real tree.

A class is dormant when it is defined at the top level of a module under ``src/probos`` and
nothing live uses it. A use is a value reference: a call, an attribute read (``Name.x`` or
``module.Name``), a base class, a decorator, the name passed as a value (a loop tuple, a factory
default, a registry argument) or a string constant whose last ``.`` or ``:`` segment is the name
(a lookup or import by name). These are not uses: an import, an annotation, an assignment target,
an ``__all__`` entry, the second argument of ``isinstance`` or ``issubclass``, an operand of
``is`` or ``is not``, and anything under ``if TYPE_CHECKING:``. A use from another module always
counts. A use inside the class's own module counts only from module-level code, from a top-level
definition with a registering decorator, or from a top-level definition that is itself live.

Names are matched, not resolved (the shape of vulture's dead-code scan and of BF-926's
``check_config_readers.py``), so it under-reports: two classes with one name are live together,
and a use from a dormant module still counts. It cannot see a class built from ``config/``, an
entry point or a name assembled at run time. Protocols, enums, exceptions, TypedDicts,
NamedTuples and pydantic models are schema rather than capability and are not reported; nor are
private classes.

The baseline holds one row per dormant class and its reviewed disposition (wire, retire or
staged, each with an owner issue or AD; or false-positive, with a note) and nothing else, so it
does not become a second capability registry (``platform-maturity-program.md``, AD-1270a).

Usage::

    python -P scripts/check_dormant_classes.py [--check | --update-baseline] [--src PATH] [--baseline PATH]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

PREFIX = "DORMANT CLASSES (report-only): "
DEFAULT_SOURCE = _REPO_ROOT / "src" / "probos"
DEFAULT_BASELINE = _REPO_ROOT / "docs" / "development" / "dormant-class-baseline.yaml"
DISPOSITIONS = ("wire", "retire", "staged", "false-positive")
UNREVIEWED = "unreviewed"
OWNER = re.compile(r"#\d+|\b(?:AD|BF)-\d+")
SCHEMA_BASES = frozenset({
    "BaseModel", "RootModel", "BaseSettings", "Protocol", "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
    "TypedDict", "NamedTuple", "BaseException", "Exception",
})
INERT_DECORATORS = frozenset({
    "dataclass", "runtime_checkable", "total_ordering", "final", "unique", "lru_cache", "cache",
    "contextmanager", "asynccontextmanager", "overload",
})
TYPE_TESTS = frozenset({"isinstance", "issubclass"})
HEADER = (
    "# AD-1270 (#1324): production classes that nothing in production uses, each with its reviewed disposition.\n"
    "# Regenerate with: python -P scripts/check_dormant_classes.py --update-baseline\n"
    "# It keeps reviewed rows, adds new classes as 'unreviewed' and drops rows that are no longer dormant.\n"
    "# disposition: wire, retire or staged (owner: an issue or AD), or false-positive (note: why).\n"
    "# One row per class and nothing more: no description, status or test data. It is not a capability registry.\n"
)


@dataclass(frozen=True)
class Candidate:
    """A dormant class: ``key`` is ``<path relative to the source root>::<name>``."""

    key: str
    line: int


@dataclass
class Report:
    """What one scan found, sorted by key."""

    dormant: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Module:
    """One parsed module: its top-level definitions and what its module-level code uses."""

    path: str
    symbols: dict[str, set[str]] = field(default_factory=dict)
    classes: dict[str, tuple[int, list[str]]] = field(default_factory=dict)
    root_uses: set[str] = field(default_factory=set)
    registered: set[str] = field(default_factory=set)

    def uses(self) -> set[str]:
        return self.root_uses.union(*self.symbols.values())


def _display(path: Path) -> str:
    """A path for the output: relative to the repository, or its name alone (never absolute)."""
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _last_name(node: ast.AST) -> str:
    """``b`` for ``a.b``, ``a.b(...)`` or ``a.b[...]``; an empty string for anything else."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _uses(root: ast.AST) -> set[str]:
    """The names ``root`` uses as values; the module docstring lists what is not a use."""
    found: set[str] = set()
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.arg):
            continue  # an argument's only child node is its annotation
        if isinstance(node, ast.If) and _last_name(node.test) == "TYPE_CHECKING":
            stack.extend(node.orelse)
            continue
        if isinstance(node, ast.Assign) and any(_last_name(target) == "__all__" for target in node.targets):
            continue
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                stack.append(node.value)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(child for child in ast.iter_child_nodes(node) if child is not node.returns)
            continue
        if isinstance(node, ast.Call) and _last_name(node.func) in TYPE_TESTS:
            stack.extend([node.func, *node.args[:1], *(keyword.value for keyword in node.keywords)])
            continue
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            operands = [node.left, *node.comparators]
            stack.extend(operand for operand in operands if not isinstance(operand, (ast.Name, ast.Attribute)))
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            found.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(re.split(r"[.:]", node.value)[-1])
        stack.extend(ast.iter_child_nodes(node))
    return found


def _parse_module(path: str, tree: ast.Module) -> _Module:
    module = _Module(path)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module.root_uses |= _uses(node)
            continue
        module.symbols.setdefault(node.name, set()).update(_uses(node))
        if any(_last_name(decorator) not in INERT_DECORATORS for decorator in node.decorator_list):
            module.registered.add(node.name)
        if isinstance(node, ast.ClassDef):
            module.classes[node.name] = (node.lineno, [_last_name(base) for base in node.bases])
    return module


def _live(module: _Module, users: dict[str, set[str]]) -> set[str]:
    """Top-level names of ``module`` that another module, module-level code or a live definition uses."""
    live = {
        name for name in module.symbols
        if users.get(name, set()) - {module.path} or name in module.root_uses or name in module.registered
    }
    frontier = list(live)
    while frontier:
        for name in module.symbols[frontier.pop()].intersection(module.symbols):
            if name not in live:
                live.add(name)
                frontier.append(name)
    return live


def _is_schema_base(name: str) -> bool:
    return name in SCHEMA_BASES or name.endswith(("Error", "Exception", "Warning"))


def _schema_classes(modules: list[_Module]) -> set[str]:
    """Class names whose bases reach a schema kind, matched by name across the tree."""
    bases: dict[str, set[str]] = {}
    for module in modules:
        for name, (_, names) in module.classes.items():
            bases.setdefault(name, set()).update(names)
    schema: set[str] = set()
    grew = True
    while grew:
        grew = False
        for name, names in bases.items():
            if name not in schema and any(_is_schema_base(base) or base in schema for base in names):
                schema.add(name)
                grew = True
    return schema


def build_report(source_root: Path) -> Report:
    """Scan every module under ``source_root`` and list its dormant classes, sorted by key."""
    report = Report()
    root = Path(source_root)
    if not root.is_dir():
        report.warnings.append(f"source root {_display(root)} is not a directory")
        return report
    modules: list[_Module] = []
    for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
            report.warnings.append(f"skipped {relative}: {type(exc).__name__}")
            continue
        modules.append(_parse_module(relative, tree))
    users: dict[str, set[str]] = {}
    for module in modules:
        for name in module.uses():
            users.setdefault(name, set()).add(module.path)
    schema = _schema_classes(modules)
    for module in modules:
        live = _live(module, users)
        for name, (line, _) in module.classes.items():
            if not (name.startswith("_") or name in schema or name in live):
                report.dormant.append(Candidate(f"{module.path}::{name}", line))
    report.dormant.sort(key=lambda candidate: candidate.key)
    return report


def load_baseline(path: Path, warnings: list[str]) -> dict[str, dict[str, Any]] | None:
    """The baseline's rows: ``{}`` when the file is absent, ``None`` when it cannot be read."""
    import yaml

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(f"no baseline at {_display(path)}; every dormant class is new")
        return {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"baseline not read ({_display(path)}): {type(exc).__name__}")
        return None  # unreadable
    rows = document.get("classes") if isinstance(document, dict) else None
    if not isinstance(rows, dict):
        warnings.append(f"baseline {_display(path)} has no 'classes' mapping")
        return None  # not a baseline document
    return {str(key): row if isinstance(row, dict) else {} for key, row in rows.items()}


def gap(row: dict[str, Any]) -> str | None:
    """Why a row has no reviewed disposition, or None when it has one."""
    disposition = row.get("disposition")
    if disposition == UNREVIEWED:
        return "unreviewed"
    if disposition not in DISPOSITIONS:
        return f"unknown disposition {disposition!r}"
    if disposition == "false-positive":
        return None if str(row.get("note") or "").strip() else "false-positive without a note"
    return None if OWNER.search(str(row.get("owner") or "")) else f"{disposition} without an owner issue or AD"


def merge(report: Report, rows: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Rows for the current dormant classes: reviewed fields kept, new classes ``unreviewed``."""
    merged: dict[str, dict[str, str]] = {}
    for candidate in report.dormant:
        kept = rows.get(candidate.key, {})
        row = {"disposition": str(kept.get("disposition") or UNREVIEWED)}
        row.update({name: str(kept[name]) for name in ("owner", "note") if kept.get(name)})
        merged[candidate.key] = row
    return merged


def render_baseline(merged: dict[str, dict[str, str]]) -> str:
    """The baseline text: sorted, ASCII, no timestamps and no absolute paths."""
    import yaml

    body = yaml.safe_dump(
        {"schema_version": 1, "classes": merged},
        sort_keys=True, allow_unicode=False, default_flow_style=False, width=4096,
    )
    return HEADER + body


def _where(candidate: Candidate) -> str:
    path, name = candidate.key.split("::")
    return f"{path}:{candidate.line} {name}"


def render(report: Report, rows: dict[str, dict[str, Any]]) -> str:
    """The summary line, then one line per finding."""
    dormant = {candidate.key: candidate for candidate in report.dormant}
    new = [key for key in dormant if key not in rows]
    left = sorted(key for key in rows if key not in dormant)
    gaps = [(key, reason) for key in dormant if key in rows and (reason := gap(rows[key]))]
    lines = [
        f"{PREFIX}{len(dormant)} dormant class(es): {len(new)} new, {len(gaps)} without a reviewed disposition, "
        f"{len(left)} baseline row(s) no longer dormant; this check warns and never fails"
    ]
    lines.extend(f"  new: {_where(dormant[key])}" for key in new)
    lines.extend(f"  {reason}: {_where(dormant[key])}" for key, reason in gaps)
    lines.extend(f"  no longer dormant (remove the row): {key}" for key in left)
    lines.extend(f"  warning: {item}" for item in report.warnings)
    return "\n".join(lines)


def _emit(text: str) -> None:
    """Write ``text`` and a newline as UTF-8 with LF line ends, whatever the host's console does."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        print(text)
        return
    sys.stdout.flush()
    stream.write(text.encode("utf-8") + b"\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    """Print the findings, rewriting the baseline first when asked. Returns 0 on every path."""
    try:
        parser = argparse.ArgumentParser(description="Report production classes nothing in production uses (report-only).")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--check", action="store_true", help="compare the tree with the baseline (the default)")
        mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline, keeping reviewed rows")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree scanned")
        parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="reviewed baseline file")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            _emit(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        report = build_report(Path(args.src))
        scan_complete = not report.warnings
        baseline = Path(args.baseline)
        rows = load_baseline(baseline, report.warnings)
        if args.update_baseline and scan_complete and rows is not None:
            rows = merge(report, rows)
            baseline.write_text(render_baseline(rows), encoding="utf-8", newline="\n")
            report.warnings.append(f"baseline rewritten: {_display(baseline)}")
        elif args.update_baseline:
            report.warnings.append("baseline not rewritten: the scan was incomplete or the baseline could not be read")
        report.warnings.extend(f"ignored argument {item!r}" for item in unknown)
        _emit(render(report, rows or {}))
    except Exception as exc:  # report-only: a failure to report is itself only reported
        _emit(f"{PREFIX}could not run: {type(exc).__name__}")
    return 0  # report-only: the status never reflects the findings


if __name__ == "__main__":
    raise SystemExit(main())
```

### 7.2 New file: `tests/test_ad1270_dormant_classes.py` (M1)

```python
"""AD-1270 (#1324) slice 2: the dormant-class check is report-only, finds a class nothing live uses
by the rules its docstring states, and keeps a disposition-only baseline current.

The check is loaded by path, as it is run. Every finding case scans a fixture tree under
``tmp_path``. The one real-tree case asserts only that the check runs and exits 0, so nothing in
the suite depends on what the real tree contains: the check stays report-only (decision D4).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_dormant_classes.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_ad1270_dormant_classes", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return root


# --- T1: what is and is not a use ---------------------------------------------------

_DEFS = '''\
"""Fixture module: the classes under test."""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SelfRef:
    def clone(self):
        return SelfRef()


class Called: ...
class AttrRead: ...
class ByName: ...
class Subclassed: ...
class LoopValue: ...
class ByString: ...
class ByDottedString: ...
class OnlyImported: ...
class OnlyAnnotated: ...
class OnlyAssigned: ...
class OnlyAll: ...
class OnlyIsinstance: ...
class OnlyIdentity: ...
class OnlyTypeChecking: ...
class OnlyDocstring: ...
class UsedByLiveHelper: ...
class UsedByDeadHelper: ...
class UsedAtModuleLevel: ...
class SchemaModel(BaseModel): ...
class SchemaChild(SchemaModel): ...
class Kind(Enum): ...
class Port(Protocol): ...
class TypedPort(Protocol[T]): ...
class Failure(ValueError): ...
class _Private: ...


@register
class Registered: ...


@dataclass(frozen=True)
class DataOnly: ...


__all__ = ["OnlyAll"]
DEFAULT = UsedAtModuleLevel


def live_helper():
    return _middle()


def _middle():
    return UsedByLiveHelper()


def dead_helper():
    return UsedByDeadHelper()
'''

_USER = '''\
import typing

from pkg import defs
from pkg.defs import ByName, OnlyAnnotated, OnlyIdentity, OnlyImported, OnlyIsinstance

if typing.TYPE_CHECKING:
    from pkg.defs import OnlyTypeChecking

    Alias = OnlyTypeChecking

CURRENT: OnlyAnnotated | None = None
OnlyAssigned = None


def run(x: OnlyAnnotated) -> OnlyAnnotated:
    """Mentions OnlyDocstring in prose."""
    defs.Called()
    defs.AttrRead.make()
    ByName()
    for cls in (defs.LoopValue,):
        cls()
    getattr(defs, "ByString")
    target = "pkg.defs.ByDottedString"
    defs.live_helper()
    if isinstance(x, OnlyIsinstance) or type(x) is OnlyIdentity:
        return x
    return target


class Child(defs.Subclassed): ...
'''

_EXPECTED_DORMANT = [
    "pkg/defs.py::DataOnly",
    "pkg/defs.py::OnlyAll",
    "pkg/defs.py::OnlyAnnotated",
    "pkg/defs.py::OnlyAssigned",
    "pkg/defs.py::OnlyDocstring",
    "pkg/defs.py::OnlyIdentity",
    "pkg/defs.py::OnlyImported",
    "pkg/defs.py::OnlyIsinstance",
    "pkg/defs.py::OnlyTypeChecking",
    "pkg/defs.py::SelfRef",
    "pkg/defs.py::UsedByDeadHelper",
    "pkg/user.py::Child",
]


def test_a_class_is_dormant_unless_something_live_uses_it_as_a_value(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/defs.py": _DEFS, "pkg/user.py": _USER})

    report = checker.build_report(source)

    assert [candidate.key for candidate in report.dormant] == _EXPECTED_DORMANT
    assert report.warnings == []


# --- T2: the findings ---------------------------------------------------------------

_SEVEN = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta")


def test_the_check_lists_new_incomplete_and_no_longer_dormant_rows(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "".join(f"class {name}: ...\n" for name in _SEVEN)})
    rows = {
        "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324"},
        "pkg/a.py::Beta": {"disposition": "unreviewed"},
        "pkg/a.py::Gamma": {"disposition": "staged"},
        "pkg/a.py::Delta": {"disposition": "false-positive"},
        "pkg/a.py::Epsilon": {"disposition": "maybe"},
        "pkg/a.py::Zeta": {"disposition": "staged", "owner": "AD-1288"},
        "pkg/gone.py::Ghost": {"disposition": "wire", "owner": "#1"},
    }

    output = checker.render(checker.build_report(source), rows)

    assert output.splitlines() == [
        f"{checker.PREFIX}7 dormant class(es): 1 new, 4 without a reviewed disposition, "
        "1 baseline row(s) no longer dormant; this check warns and never fails",
        "  new: pkg/a.py:7 Eta",
        "  unreviewed: pkg/a.py:2 Beta",
        "  false-positive without a note: pkg/a.py:4 Delta",
        "  unknown disposition 'maybe': pkg/a.py:5 Epsilon",
        "  staged without an owner issue or AD: pkg/a.py:3 Gamma",
        "  no longer dormant (remove the row): pkg/gone.py::Ghost",
    ]


# --- T3, T4: the baseline -------------------------------------------------------------


def test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "class Alpha: ...\nclass Beta: ...\n"})
    baseline = tmp_path / "baseline.yaml"
    baseline.write_text(yaml.safe_dump({"schema_version": 1, "classes": {
        "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324", "note": "slice 3"},
        "pkg/gone.py::Ghost": {"disposition": "retire", "owner": "#1"},
    }}), encoding="utf-8")
    argv = ["--update-baseline", "--src", str(source), "--baseline", str(baseline)]

    assert checker.main(argv) == 0
    first = baseline.read_bytes()
    assert checker.main(argv) == 0

    assert baseline.read_bytes() == first  # a second run changes nothing
    assert first.startswith(checker.HEADER.encode("ascii"))
    assert b"\r" not in first
    assert yaml.safe_load(first.decode("utf-8")) == {
        "schema_version": 1,
        "classes": {
            "pkg/a.py::Alpha": {"disposition": "wire", "owner": "#1324", "note": "slice 3"},
            "pkg/a.py::Beta": {"disposition": "unreviewed"},
        },
    }
    output = capsys.readouterr().out
    assert "  warning: baseline rewritten: " in output
    assert "  unreviewed: pkg/a.py:2 Beta" in output


_KEPT = "schema_version: 1\nclasses:\n  pkg/gone.py::Ghost:\n    disposition: retire\n    owner: '#1'\n"


@pytest.mark.parametrize("case", ["an incomplete scan", "an unreadable baseline", "a baseline with no classes mapping"])
def test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {"pkg/a.py": "class Alpha: ...\n"}
    if case == "an incomplete scan":
        files["pkg/broken.py"] = "def (:\n"
    source = _tree(tmp_path / "src", files)
    text = {"an unreadable baseline": "classes: [unclosed\n", "a baseline with no classes mapping": "schema_version: 1\n"}.get(
        case, _KEPT
    )
    baseline = tmp_path / "baseline.yaml"
    baseline.write_bytes(text.encode("utf-8"))

    assert checker.main(["--update-baseline", "--src", str(source), "--baseline", str(baseline)]) == 0

    assert baseline.read_bytes() == text.encode("utf-8")
    assert "baseline not rewritten" in capsys.readouterr().out


# --- T5 to T8: report-only, host-independent ---------------------------------------------

_EXIT_CASES = {
    "the real tree": ([], ""),
    "a missing baseline": (["--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "no baseline at"),
    "a malformed baseline": (["--src", "{tmp}/src", "--baseline", "{tmp}/broken.yaml"], "baseline not read ("),
    "a source file that does not parse": (
        ["--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "skipped broken.py: SyntaxError"
    ),
    "a missing source root": (["--src", "{tmp}/nowhere", "--baseline", "{tmp}/absent.yaml"], "is not a directory"),
    "an unknown argument": (
        ["--strict", "--src", "{tmp}/src", "--baseline", "{tmp}/absent.yaml"], "ignored argument '--strict'"
    ),
    "an argument without its value": (["--baseline"], "could not parse the arguments"),
    "both modes at once": (["--check", "--update-baseline"], "could not parse the arguments"),
    "a baseline in a missing directory": (
        ["--update-baseline", "--src", "{tmp}/clean", "--baseline", "{tmp}/missing/dir/b.yaml"],
        "could not run: FileNotFoundError",
    ),
}


@pytest.mark.parametrize("case", sorted(_EXIT_CASES))
def test_the_check_exits_zero_on_every_input(case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("classes: [unclosed\n", encoding="utf-8")
    _tree(tmp_path / "src", {"broken.py": "def (:\n", "pkg/a.py": "class Alpha: ...\n"})
    _tree(tmp_path / "clean", {"pkg/a.py": "class Alpha: ...\n"})
    template, expected = _EXIT_CASES[case]
    argv = [part.format(tmp=tmp_path.as_posix()) for part in template]

    assert checker.main(argv) == 0

    output = capsys.readouterr().out
    assert output.startswith(checker.PREFIX)
    assert expected in output


def test_the_command_line_exits_zero_with_lf_utf8_output(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "class Alpha: ...\n"})
    completed = subprocess.run(
        [sys.executable, "-P", str(_SCRIPT), "--src", str(source), "--baseline", str(tmp_path / "absent.yaml")],
        capture_output=True, timeout=300, cwd=_REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(checker.PREFIX.encode("ascii"))
    assert completed.stdout.endswith(b"\n")
    assert b"\r" not in completed.stdout
    assert b"  new: pkg/a.py:1 Alpha\n" in completed.stdout


def test_the_output_names_no_absolute_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("classes: [unclosed\n", encoding="utf-8")

    checker.main(["--src", str(tmp_path / "nowhere"), "--baseline", str(tmp_path / "broken.yaml")])

    output = capsys.readouterr().out
    assert "nowhere" in output and "broken.yaml" in output
    assert str(tmp_path) not in output
    assert tmp_path.as_posix() not in output


def test_modules_are_read_in_posix_path_order_on_every_host(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "def (:\n", "pkg/B.py": "def (:\n"})

    report = checker.build_report(source)

    assert report.warnings == ["skipped pkg/B.py: SyntaxError", "skipped pkg/a.py: SyntaxError"]
```

### 7.3 Generated file: `docs/development/dormant-class-baseline.yaml` (M1)

`--update-baseline` generates this file (§4, M1 build order). Then set these rows by editing the YAML, and leave every other row `unreviewed`. A seed whose key the scan did not produce is **not** added; list it in the report. Afterwards run `--update-baseline` again.

| Key (relative to `src/probos`) | disposition | owner | note |
|---|---|---|---|
| `cognitive/memory_metabolism.py::MemoryMetabolism` | wire | `#1324` | AD-670; slice 3 wires it behind a new default-off flag; AD-1339 (#1566) depends on it |
| `cognitive/salience_filter.py::SalienceFilter` | wire | `#1324` | AD-668; slice 3 |
| `crew_development/boot_camp_extensions.py::CurriculumProgressionTracker` | wire | `#1324` | AD-507b; slice 4 (onboarding) |
| `crew_development/boot_camp_extensions.py::ASchoolCurriculum` | wire | `#1324` | AD-509b; slice 4 |
| `crew_development/boot_camp_extensions.py::GraduatedStimuliMonitor` | wire | `#1324` | AD-509c; slice 4 |
| `crew_development/boot_camp_extensions.py::CompletionCriteriaGate` | wire | `#1324` | AD-509d; slice 4 |
| `cognitive/elastic_commission.py::ElasticCommissionService` | staged | `AD-1288 (#1335)` | wiring is AD-1288 S2 |
| `cognitive/repair_candidate.py::RepairCandidate` | staged | `AD-1299 (#1352)` | type-checked by repair_approval and repair_evidence_store; nothing builds one yet |
| `mesh/nats_bus.py::MockNATSBus` | false-positive | — | test double kept in src for the tests; production names it only under TYPE_CHECKING |
| `events.py::TrustUpdateEvent` | retire | `#1324` | AD-527 typed form never built; the producer emits trust_update as a dict that carries old_score, which this class lacks |
| `events.py::<each other Group E name, §0>` (42 rows) | retire | `#1324` | AD-527 typed form never built; producers emit the EventType with a dict |

### 7.4 Repair 1 (A1)

These pairs are written against M1's files as committed at `935acb6a`. Each SEARCH occurs once in its file, matched on the LF blob (the Windows working copy may be CRLF).

**Order:**
1. Apply pair T-1 first and run the test file over `935acb6a`'s script. Predicted: 18 passed, 2 failed (§6).
2. Apply S-1 to S-6, then run M1's focused gate.
3. Regenerate the baseline (the last paragraph of this section).
4. Commit the three files.

**Pair S-1 (`scripts/check_dormant_classes.py`).** SEARCH:
```
Names are matched, not resolved (the shape of vulture's dead-code scan and of BF-926's
``check_config_readers.py``), so it under-reports: two classes with one name are live together,
and a use from a dormant module still counts. It cannot see a class built from ``config/``, an
entry point or a name assembled at run time. Protocols, enums, exceptions, TypedDicts,
NamedTuples and pydantic models are schema rather than capability and are not reported; nor are
private classes.

The baseline holds one row per dormant class and its reviewed disposition (wire, retire or
staged, each with an owner issue or AD; or false-positive, with a note) and nothing else, so it
does not become a second capability registry (``platform-maturity-program.md``, AD-1270a).
```
REPLACE:
```
Names are matched, not resolved (the shape of vulture's dead-code scan and of BF-926's
``check_config_readers.py``), with one exception: an import alias. After ``from m import X as Y``
anywhere in a module, a function body included, a value use of ``Y`` in that module, or a base
written as ``Y``, also counts as ``X``. An alias that is only imported or only annotates is not a
use, and an alias belongs to the module that imports it. ``import m as n`` needs no rule: ``n.X``
reads ``X``. So it under-reports: two classes with one name are live together, a use from a
dormant module still counts, and a use of an alias counts for every name the module imports under
it. It over-reports a class that only a path it cannot see reaches: ``config/``, an entry point,
``getattr`` or an import with a computed name, or an alias imported under that alias from the
module that made it. Protocols, enums, exceptions, TypedDicts, NamedTuples and pydantic models are
schema rather than capability and are not reported; nor are private classes.

The baseline holds one row per dormant class and its disposition and nothing else: ``unreviewed``
until a reviewer sets wire, retire or staged (each with an owner issue or AD) or false-positive
(with a note). Holding nothing else keeps it from becoming a second capability registry
(``platform-maturity-program.md``, AD-1270a).
```

**Pair S-2 (`scripts/check_dormant_classes.py`).** SEARCH:
```
    "# AD-1270 (#1324): production classes that nothing in production uses, each with its reviewed disposition.\n"
```
REPLACE:
```
    "# AD-1270 (#1324): production classes that nothing in production uses, each with its disposition.\n"
```

**Pair S-3 (`scripts/check_dormant_classes.py`).** SEARCH:
```
def _parse_module(path: str, tree: ast.Module) -> _Module:
    module = _Module(path)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module.root_uses |= _uses(node)
            continue
        module.symbols.setdefault(node.name, set()).update(_uses(node))
        if any(_last_name(decorator) not in INERT_DECORATORS for decorator in node.decorator_list):
            module.registered.add(node.name)
        if isinstance(node, ast.ClassDef):
            module.classes[node.name] = (node.lineno, [_last_name(base) for base in node.bases])
    return module
```
REPLACE:
```
def _aliases(tree: ast.Module) -> dict[str, set[str]]:
    """``{Y: {X, ...}}`` for each ``from m import X as Y`` anywhere in the module, a function body included."""
    aliases: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.asname != alias.name:
                    aliases.setdefault(alias.asname, set()).add(alias.name)
    return aliases


def _resolve(names: set[str], aliases: dict[str, set[str]]) -> set[str]:
    """``names`` and the original name behind each alias among them."""
    return names.union(*(aliases.get(name, set()) for name in names))


def _parse_module(path: str, tree: ast.Module) -> _Module:
    module = _Module(path)
    aliases = _aliases(tree)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module.root_uses |= _resolve(_uses(node), aliases)
            continue
        module.symbols.setdefault(node.name, set()).update(_resolve(_uses(node), aliases))
        if any(_last_name(decorator) not in INERT_DECORATORS for decorator in node.decorator_list):
            module.registered.add(node.name)
        if isinstance(node, ast.ClassDef):
            bases = _resolve({_last_name(base) for base in node.bases}, aliases)
            module.classes[node.name] = (node.lineno, sorted(bases))
    return module
```

**Pair S-4 (`scripts/check_dormant_classes.py`).** SEARCH:
```
    """The baseline text: sorted, ASCII, no timestamps and no absolute paths."""
```
REPLACE:
```
    """The baseline text: sorted, ASCII and without a timestamp. Keys are relative paths; a retained owner or note is kept as written."""
```

**Pair S-5 (`scripts/check_dormant_classes.py`).** SEARCH:
```
    """Write ``text`` and a newline as UTF-8 with LF line ends, whatever the host's console does."""
```
REPLACE:
```
    """Write ``text`` and a newline as UTF-8 with LF line ends to stdout's byte buffer.

    A stdout without a ``buffer`` (a text-only stream) gets ``print``, so that stream's own newline
    translation applies.
    """
```

**Pair S-6 (`scripts/check_dormant_classes.py`).** SEARCH:
```
def main(argv: list[str] | None = None) -> int:
    """Print the findings, rewriting the baseline first when asked. Returns 0 on every path."""
    try:
        parser = argparse.ArgumentParser(description="Report production classes nothing in production uses (report-only).")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--check", action="store_true", help="compare the tree with the baseline (the default)")
        mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline, keeping reviewed rows")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree scanned")
        parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="reviewed baseline file")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            _emit(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        report = build_report(Path(args.src))
```
REPLACE:
```
def main(argv: list[str] | None = None) -> int:
    """Print the findings, rewriting the baseline first when asked. Returns 0 on every path.

    ``--help`` is answered here, not by argparse, so its first line also starts with ``PREFIX`` and it
    is written through ``_emit``.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Report production classes nothing in production uses (report-only).", add_help=False
        )
        parser.add_argument("-h", "--help", action="store_true", help="show this help and check nothing")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--check", action="store_true", help="compare the tree with the baseline (the default)")
        mode.add_argument("--update-baseline", action="store_true", help="rewrite the baseline, keeping reviewed rows")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree scanned")
        parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="baseline file of dispositions")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            _emit(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        if args.help:
            _emit(f"{PREFIX}help; nothing checked\n{parser.format_help().rstrip()}")
            return 0  # help is the whole output
        report = build_report(Path(args.src))
```

**Pair T-1 (`tests/test_ad1270_dormant_classes.py`).** SEARCH:
```
def test_modules_are_read_in_posix_path_order_on_every_host(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "def (:\n", "pkg/B.py": "def (:\n"})

    report = checker.build_report(source)

    assert report.warnings == ["skipped pkg/B.py: SyntaxError", "skipped pkg/a.py: SyntaxError"]
```
REPLACE:
```
def test_modules_are_read_in_posix_path_order_on_every_host(tmp_path: Path) -> None:
    source = _tree(tmp_path / "src", {"pkg/a.py": "def (:\n", "pkg/B.py": "def (:\n"})

    report = checker.build_report(source)

    assert report.warnings == ["skipped pkg/B.py: SyntaxError", "skipped pkg/a.py: SyntaxError"]


# --- T9, T10 (A1): import aliases and --help ----------------------------------------------

_ALIAS_DEFS = '''\
from dataclasses import dataclass
from typing import Protocol as P

from pydantic import BaseModel as BM


class AliasedBuilt: ...
class AliasedInFunction: ...
class FirstOnLine: ...
class SecondOnLine: ...
class AliasedAnnotationOnly: ...
class SameAliasElsewhere: ...
class NotAliasedUnused: ...
class AliasedPort(P): ...
class AliasedModel(BM): ...


@dataclass(frozen=True)
class BuiltByHelper:
    value: int = 0


def make_built():
    return BuiltByHelper()
'''

_ALIAS_USER = '''\
from pkg.defs import AliasedAnnotationOnly as _Ann
from pkg.defs import AliasedBuilt as _Built
from pkg.defs import FirstOnLine as _First, SecondOnLine as _Second
from pkg.defs import NotAliasedUnused
from pkg.defs import make_built as _make

PAIR = (_First, _Second)
CURRENT: _Ann | None = None


def run(x: _Ann) -> _Ann:
    _Built()
    _make()
    return x


def lazy():
    from pkg.defs import AliasedInFunction as _Lazy

    return _Lazy()
'''

_ALIAS_OTHER = '''\
from pkg.defs import SameAliasElsewhere as _Built


def typed(x: _Built) -> None:
    return None
'''


def test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value(tmp_path: Path) -> None:
    source = _tree(
        tmp_path / "src", {"pkg/defs.py": _ALIAS_DEFS, "pkg/user.py": _ALIAS_USER, "pkg/other.py": _ALIAS_OTHER}
    )

    report = checker.build_report(source)

    assert [candidate.key for candidate in report.dormant] == [
        "pkg/defs.py::AliasedAnnotationOnly",
        "pkg/defs.py::NotAliasedUnused",
        "pkg/defs.py::SameAliasElsewhere",
    ]
    assert report.warnings == []


def test_help_starts_with_the_prefix_and_is_written_lf_utf8(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable, "-P", str(_SCRIPT), "--help",
            "--src", str(tmp_path / "src"), "--baseline", str(tmp_path / "absent.yaml"),
        ],
        capture_output=True, timeout=300, cwd=_REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(checker.PREFIX.encode("ascii") + b"help; nothing checked\n")
    assert b"\r" not in completed.stdout
    assert completed.stdout.endswith(b"\n")
    assert b"--update-baseline" in completed.stdout
    assert b"dormant class(es)" not in completed.stdout  # help is the whole output: nothing is scanned
    assert completed.stderr == b""
```

**Baseline at the A1 commit (a command, not a pair).** Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_dormant_classes.py --update-baseline`. It must print `baseline rewritten: docs/development/dormant-class-baseline.yaml`.
- `git diff --stat` on the baseline is predicted at 1 insertion and 29 deletions: line 1 loses "reviewed ", and the 14 alias rows (two lines each) are dropped. Nothing else changes.
- Then `--check` is predicted to print `171 dormant class(es): 0 new, 119 without a reviewed disposition, 0 baseline row(s) no longer dormant`.
- A pair is not used because the script writes `HEADER` itself, so a hand-written header would be a second copy that could drift. The drop of the 14 rows is the rule under test.

**What T9 covers:**
- An aliased class built by a function: `_Built`.
- An alias imported inside a function body: `_Lazy`.
- Two aliases on one line, used at module level: `PAIR`.
- An aliased helper that builds a dataclass: `_make` → `BuiltByHelper`.
- Aliased schema bases: `P`, `BM`.
- An alias used only in annotations, which stays dormant: `_Ann`.
- The same alias name in another module, which does not leak: `other.py`.
- A non-aliased unused import, still reported: `NotAliasedUnused`.

## 8. Tracking (M2's commit)

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 slice 2 -- the dormant-class check.** `scripts/check_dormant_classes.py` lists the production classes that nothing live uses, against a reviewed baseline, `docs/development/dormant-class-baseline.yaml`: one row per class, with its disposition (wire, retire or staged with an owner issue or AD, or false-positive with a note) and nothing else, so it is not a capability registry. A use is a value reference (a call, an attribute read, a base, a decorator, the class passed as a value, a string naming it); imports, annotations, `__all__`, `isinstance` and `is` tests and `TYPE_CHECKING` blocks are not uses, and a use inside the class's own module counts only from live code; a name imported under an alias (`from m import X as Y`) counts as `X` where that module uses `Y` as a value or a base. It replaces the 2026-10-16 built-but-dormant audit, whose method missed loop and factory construction (25 qualification probes, the work-item pull tools, `RecreationTurnSupport`) and counted same-module use as none (`PolicyWindow`, `ProvenanceEnvelope`, `PerformanceReview`, `IgnoreSpec`, `ReaderIdentity`, `CommunicationQualityProbe`). Report-only: exit 0 on every input, not a `run_test_gate.py` phase, and no test asserts what it finds in the real tree. `--update-baseline` keeps reviewed rows, adds new classes as `unreviewed` and drops classes that became live, so the working-memory and onboarding slices can take "these rows leave the list" as acceptance. `OntologyService.set_alert_condition` (no caller) is a method, outside a class check, and stays on #1324's register. New: `tests/test_ad1270_dormant_classes.py`. The contract is `prompts/ad-1270-dormant-class-check.md`.

```

New entries go before the heading named in the SEARCH, after slice 1's entries.

**Pair U2 (`DECISIONS.md`).** SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1270 (#1324) -- the dormant-class check: value uses with in-module reachability, a disposition-only baseline, report-only (2026-10-2X)

**Decision.** `scripts/check_dormant_classes.py` reports a top-level class under `src/probos` as dormant when nothing live uses it as a value. Imports, annotations, `__all__`, `isinstance`/`issubclass`, `is` operands and `TYPE_CHECKING` blocks are not uses; a use from another module always counts; a use in the class's own module counts only from module-level code, a registering decorator or a live definition; a name imported under an alias counts as its original where the importing module uses the alias as a value or a base (without this, 14 live classes were reported). Schema kinds (Protocol, Enum, exceptions, TypedDict, NamedTuple, pydantic models) and private classes are not reported. `docs/development/dormant-class-baseline.yaml` records only a disposition per class. The check exits 0 on every input; it is not a gate phase and no test asserts its real-tree findings. The 43 AD-527 typed events no producer builds are marked `retire` (their deletion is a later slice). **Why.** The 2026-10-16 audit's list could not be acceptance for the working-memory and onboarding slices: a quarter of it was live code its method could not see. A disposition-only baseline keeps the check a fitness report and not a second capability registry (`platform-maturity-program.md`). **Rejected.** Whole-program reachability from entry points (one missed root, a route decorator or a server string, marks a subsystem dormant). Other-module uses only (the audit's method). Counting annotations and imports as uses (it answers "is it named?", not "is it used?"). Counting an aliased import as a use of its original whether or not the alias is used (vulture's rule; an unused import is still an import). A suite test that `--check` is clean (a gate in effect: HIGH and the Captain's call). Unused methods, such as `OntologyService.set_alert_condition` (name matching on methods would flood; it stays on #1324's register).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

Parent checklist (the orchestrator, on #1324): add and tick a slice-2 item with the commits and the receipt.

## 9. What this does NOT change

- No file under `src/`, `ui/` or `config/`; no production behaviour.
- `scripts/run_test_gate.py` and CI: the check is not a phase or step.
- No class is wired or deleted. `retire` and `wire` are dispositions; acting on them is a later slice with its own contract.
- `scripts/check_config_readers.py` and its tests.
- `OntologyService.set_alert_condition` and any other method (R1).

## 10. Mutation rows (one campaign on the M1 tree, after an unmutated baseline of `tests/test_ad1270_dormant_classes.py` passes; run on the Captain's Windows host)

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| D-1 | M1 | `scripts/check_dormant_classes.py` | `OWNER = re.compile(r"#\d+\|\b(?:AD\|BF)-\d+")` | `OWNER = re.compile(r"#\d+")` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-2 | M1 | `scripts/check_dormant_classes.py` | `"dataclass", "runtime_checkable", "total_ordering", "final", "unique", "lru_cache", "cache",` | `"runtime_checkable", "total_ordering", "final", "unique", "lru_cache", "cache",` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-3 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Call):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-4 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Subscript):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-5 | M1 | `scripts/check_dormant_classes.py` | `return node.attr` | `return ""` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-6 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.arg):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-7 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.If) and _last_name(node.test) == "TYPE_CHECKING":` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-8 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Assign) and any(_last_name(target) == "__all__" for target in node.targets):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-9 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.AnnAssign):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-10 | M1 | `scripts/check_dormant_classes.py` | `stack.extend(child for child in ast.iter_child_nodes(node) if child is not node.returns)` | `stack.extend(ast.iter_child_nodes(node))` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-11 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Call) and _last_name(node.func) in TYPE_TESTS:` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-12 | M1 | `scripts/check_dormant_classes.py` | `stack.extend([node.func, *node.args[:1], *(keyword.value for keyword in node.keywords)])` | `stack.extend([node.func, *node.args, *(keyword.value for keyword in node.keywords)])` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-13 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-14 | M1 | `scripts/check_dormant_classes.py` | `stack.extend(operand for operand in operands if not isinstance(operand, (ast.Name, ast.Attribute)))` | `stack.extend(operands)` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-15 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):` | `if isinstance(node, ast.Name):` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-16 | M1 | `scripts/check_dormant_classes.py` | `found.add(node.id)` | `pass` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-17 | M1 | `scripts/check_dormant_classes.py` | `found.add(node.attr)` | `pass` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-18 | M1 | `scripts/check_dormant_classes.py` | `elif isinstance(node, ast.Constant) and isinstance(node.value, str):` | `elif False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-19 | M1 | `scripts/check_dormant_classes.py` | `found.add(re.split(r"[.:]", node.value)[-1])` | `found.add(node.value)` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-20 | M1 | `scripts/check_dormant_classes.py` | `module.root_uses \|= _resolve(_uses(node), aliases)` | `pass` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value`, `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-21 | M1 | `scripts/check_dormant_classes.py` | `if any(_last_name(decorator) not in INERT_DECORATORS for decorator in node.decorator_list):` | `if False:` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-22 | M1 | `scripts/check_dormant_classes.py` | `if users.get(name, set()) - {module.path} or name in module.root_uses or name in module.registered` | `if users.get(name, set()) or name in module.root_uses or name in module.registered` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-23 | M1 | `scripts/check_dormant_classes.py` | `frontier.append(name)` | `pass` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-24 | M1 | `scripts/check_dormant_classes.py` | `return name in SCHEMA_BASES or name.endswith(("Error", "Exception", "Warning"))` | `return name in SCHEMA_BASES` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-25 | M1 | `scripts/check_dormant_classes.py` | `if name not in schema and any(_is_schema_base(base) or base in schema for base in names):` | `if name not in schema and any(_is_schema_base(base) for base in names):` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-26 | M1 | `scripts/check_dormant_classes.py` | `if not root.is_dir():` | `if False:` | `test_the_check_exits_zero_on_every_input[a missing source root]`, `test_the_output_names_no_absolute_path` |
| D-27 | M1 | `scripts/check_dormant_classes.py` | `for path in sorted(root.rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):` | `for path in sorted(root.rglob("*.py")):` | `test_modules_are_read_in_posix_path_order_on_every_host` (host-dependent: Windows `Path` ordering is case-insensitive; on Linux this is an equivalent mutant) |
| D-28 | M1 | `scripts/check_dormant_classes.py` | `except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:` | `except (ValueError, UnicodeDecodeError, OSError) as exc:` | `test_the_check_exits_zero_on_every_input[a source file that does not parse]`, `test_modules_are_read_in_posix_path_order_on_every_host` |
| D-29 | M1 | `scripts/check_dormant_classes.py` | `if not (name.startswith("_") or name in schema or name in live):` | `if not (name in schema or name in live):` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value` |
| D-30 | M1 | `scripts/check_dormant_classes.py` | `report.dormant.sort(key=lambda candidate: candidate.key)` | `pass` | `test_a_class_is_dormant_unless_something_live_uses_it_as_a_value`, `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-31 | M1 | `scripts/check_dormant_classes.py` | `return path.name` | `return str(path)` | `test_the_output_names_no_absolute_path` |
| D-32 | M1 | `scripts/check_dormant_classes.py` | `return None  # unreadable` | `return {}` | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[an unreadable baseline]` |
| D-33 | M1 | `scripts/check_dormant_classes.py` | `return None  # not a baseline document` | `return {}` | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[a baseline with no classes mapping]` |
| D-34 | M1 | `scripts/check_dormant_classes.py` | `if disposition == UNREVIEWED:` | `if False:` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-35 | M1 | `scripts/check_dormant_classes.py` | `if disposition not in DISPOSITIONS:` | `if False:` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-36 | M1 | `scripts/check_dormant_classes.py` | `return None if str(row.get("note") or "").strip() else "false-positive without a note"` | `return None` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-37 | M1 | `scripts/check_dormant_classes.py` | `return None if OWNER.search(str(row.get("owner") or "")) else f"{disposition} without an owner issue or AD"` | `return None` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-38 | M1 | `scripts/check_dormant_classes.py` | `kept = rows.get(candidate.key, {})` | `kept = {}` | `test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest` |
| D-39 | M1 | `scripts/check_dormant_classes.py` | `row.update({name: str(kept[name]) for name in ("owner", "note") if kept.get(name)})` | `pass` | `test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest` |
| D-40 | M1 | `scripts/check_dormant_classes.py` | `new = [key for key in dormant if key not in rows]` | `new = []` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows`, `test_the_command_line_exits_zero_with_lf_utf8_output` |
| D-41 | M1 | `scripts/check_dormant_classes.py` | `left = sorted(key for key in rows if key not in dormant)` | `left = []` | `test_the_check_lists_new_incomplete_and_no_longer_dormant_rows` |
| D-42 | M1 | `scripts/check_dormant_classes.py` | `stream.write(text.encode("utf-8") + b"\n")` | `stream.write(text.encode("utf-8"))` | `test_the_command_line_exits_zero_with_lf_utf8_output` |
| D-43 | M1 | `scripts/check_dormant_classes.py` | `if stream is None:` | `if True:` | `test_the_command_line_exits_zero_with_lf_utf8_output` (host-dependent: `print` to a Windows pipe writes CRLF; on Linux this is an equivalent mutant) |
| D-44 | M1 | `scripts/check_dormant_classes.py` | `if exc.code not in (0, None):` | `if False:` | `test_the_check_exits_zero_on_every_input[an argument without its value]`, `test_the_check_exits_zero_on_every_input[both modes at once]` |
| D-45 | M1 | `scripts/check_dormant_classes.py` | `scan_complete = not report.warnings` | `scan_complete = True` | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[an incomplete scan]` |
| D-46 | M1 | `scripts/check_dormant_classes.py` | `if args.update_baseline and scan_complete and rows is not None:` | `if args.update_baseline and rows is not None:` | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[an incomplete scan]` |
| D-47 | M1 | `scripts/check_dormant_classes.py` | `rows = merge(report, rows)` | `pass` | `test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest` |
| D-48 | M1 | `scripts/check_dormant_classes.py` | `baseline.write_text(render_baseline(rows), encoding="utf-8", newline="\n")` | `baseline.write_text(render_baseline(rows), encoding="utf-8")` | `test_updating_the_baseline_keeps_reviewed_rows_adds_new_ones_and_drops_the_rest` (host-dependent: Windows writes CRLF; on Linux this is an equivalent mutant) |
| D-49 | M1 | `scripts/check_dormant_classes.py` | `report.warnings.append("baseline not rewritten: the scan was incomplete or the baseline could not be read")` | `pass` | `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[an incomplete scan]`, `test_the_baseline_is_not_rewritten_from_an_incomplete_scan_or_an_unreadable_baseline[an unreadable baseline]` |
| D-50 | M1 | `scripts/check_dormant_classes.py` | `report.warnings.extend(f"ignored argument {item!r}" for item in unknown)` | `pass` | `test_the_check_exits_zero_on_every_input[an unknown argument]` |
| D-51 | M1 | `scripts/check_dormant_classes.py` | `except Exception as exc:  # report-only: a failure to report is itself only reported` | `except ZeroDivisionError as exc:  # report-only: a failure to report is itself only reported` | `test_the_check_exits_zero_on_every_input[a baseline in a missing directory]` |
| D-52 | M1 | `scripts/check_dormant_classes.py` | `for node in ast.walk(tree):` | `for node in tree.body:` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-53 | M1 | `scripts/check_dormant_classes.py` | `if isinstance(node, ast.ImportFrom):` | `if False:` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-54 | M1 | `scripts/check_dormant_classes.py` | `if alias.asname and alias.asname != alias.name:` | `if False:` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-55 | M1 | `scripts/check_dormant_classes.py` | `aliases.setdefault(alias.asname, set()).add(alias.name)` | `pass` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-56 | M1 | `scripts/check_dormant_classes.py` | `return names.union(*(aliases.get(name, set()) for name in names))` | `return names` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-57 | M1 | `scripts/check_dormant_classes.py` | `module.root_uses \|= _resolve(_uses(node), aliases)` | `module.root_uses \|= _uses(node)` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-58 | M1 | `scripts/check_dormant_classes.py` | `module.symbols.setdefault(node.name, set()).update(_resolve(_uses(node), aliases))` | `module.symbols.setdefault(node.name, set()).update(_uses(node))` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-59 | M1 | `scripts/check_dormant_classes.py` | `bases = _resolve({_last_name(base) for base in node.bases}, aliases)` | `bases = {_last_name(base) for base in node.bases}` | `test_an_import_alias_counts_as_its_original_name_where_it_is_used_as_a_value` |
| D-60 | M1 | `scripts/check_dormant_classes.py` | `if args.help:` | `if False:` | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` |
| D-61 | M1 | `scripts/check_dormant_classes.py` | `_emit(f"{PREFIX}help; nothing checked\n{parser.format_help().rstrip()}")` | `pass` | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` |
| D-62 | M1 | `scripts/check_dormant_classes.py` | `return 0  # help is the whole output` | `pass` | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` |
| D-63 | M1 | `scripts/check_dormant_classes.py` | `parser.add_argument("-h", "--help", action="store_true", help="show this help and check nothing")` | `pass` | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` |
| D-64 | M1 | `scripts/check_dormant_classes.py` | `description="Report production classes nothing in production uses (report-only).", add_help=False` | `description="Report production classes nothing in production uses (report-only).",` | `test_help_starts_with_the_prefix_and_is_written_lf_utf8` |

The `|` characters in the D-1, D-20 and D-57 cells are escaped as `\|` for the table; the line in the file has a plain `|`. Each line occurs once in the script; D-20 and D-57 are two mutants of one line. Rows D-52 to D-64 and D-20's new line are A1's. Lines with no row, and why:
- the docstrings and `HEADER`: text only;
- `TYPE_TESTS`: D-11 covers it;
- `_where`, `render_baseline`, `_Module.uses` and `merged[candidate.key] = row`: every T2/T3 assertion depends on them, so a mutant fails the unmutated path broadly;
- `live.add(name)`: a mutant would loop forever on reachability cycles in the real tree, so there is no row.
- (A1) `aliases: dict[str, set[str]] = {}`, `return aliases`, `aliases = _aliases(tree)` and `module.classes[node.name] = (node.lineno, sorted(bases))`: a mutant breaks every scan (T1 and T9 fail broadly); `for alias in node.names:` is covered by D-54 and D-55.

The census pins `scripts/check_dormant_classes.py` and `tests/test_ad1270_dormant_classes.py` from the A1 commit (M1's campaign of 51 rows is superseded: both files changed). If either file differs at census time, rerun every row. Predicted unmutated baseline: 20 passed.

## 11. Verified Against Codebase (2026-10-27, on `894526c6`; the citations into `runtime.py` re-read on `65f5e02b`)

```
Read logs/ad1270/dormant-audit-2026-10-16.md (all); logs/ad1270/answer-ad1270-first-slice.txt:1-60, :1145-1172
Read scripts/check_config_readers.py (all); tests/test_bf926_config_readers.py (all)
Grep 43 event names in src/probos (glob !events.py) -> cognitive/causal_reasoning.py:15 only (docstring)
Grep ^class (<43>) in events.py -> 43; Read events.py:540-571 (BaseEvent), :698-707 (TrustUpdateEvent)
Grep 36-name and 41-name batches (the strong list) in src/probos -> own modules + prose (see §0)
Grep 39-name check list in src/probos -> 32 files; Read runtime.py:3046-3126 (probe loops)
Grep ^class (_Frozen|_OwnedFormat|_Criterion|...|ChannelConfig|BaseEvent) -> elastic_team.py:160, elastic_commission.py:127, execution_profile.py:109, work_item_steps.py:122, crew_verdict.py:24, channels/base.py:20, events.py:544
Read routers/readiness.py:20-89 (IntegrationAvailability is a TypedDict)
Grep DutySchedule|load_ignore_spec|CrewProfile.from_dict|query_with_provenance|... -> finalize.py:4230, oracle_query_tool.py:317-319, crew_profile.py:598, file_walk.py:158
Grep \bDeliveryRun\b|\biter_files\( -> agentic_loop.py:1216, agents/code_search.py:266
Read cognitive/chain_nats_bridge.py:34-40 (MockNATSBus under TYPE_CHECKING)
Grep ^@[A-Za-z_.]*(register|...) -> knowledge/embeddings.py:119 @register_embedding_function (a registering class decorator exists)
Grep scripts/run_test_gate.py check_*.py -> :1105-1124, an explicit list
git log -S"class SystemHealthProvider" -> dac29856 (2026-10-24); git log -S"owned_steps.OwnedArtifactReference" -> 693096ac (2026-09-22)
gh issue list --search "AD-1288 OR AD-1287 in:title" -> #1335 OPEN, #1334 CLOSED; #1352 (AD-1299) OPEN
git ls-files docs/development/*baseline* -> architecture-baseline.yaml, config-facade-baseline.yaml, store-baseline.yaml
Grep pyproject.toml [project.scripts] -> probos = "probos.__main__:main" (a function)
```

## Absence Verified (2026-10-27)

| ID | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No production use of the 43 typed events | Grep `\b(<43>)\b` in `src/probos`, glob `!events.py` | `causal_reasoning.py:15` (prose) | yes |
| AV2 | `set_alert_condition` has no caller | Grep `set_alert_condition` in `src` | def `ontology/service.py:105`; comment `watch_rotation.py:216` | yes |
| AV3 | Nothing constructs `PermissionConfig`, `RepairCandidate`, `MockNATSBus`, `ContainerExec`, `BrowserTask`, `TrustViolation`, `CurriculumRequirement`, `UncertaintyContext`, `TelemetrySample`, `ConnectionWeight`, `DutyShift` | Grep `\b(<names>)\(` in `src` | none | yes |
| AV4 | `MemoryMetabolism`/`SalienceFilter`: imports and annotations only | Grep the names in `src/probos` | `agent_working_memory.py:26,29,291,328,568`; `config_models/cognition.py:334` (prose) | yes |
| AV5 | No test enumerates `scripts/` | Grep `SCRIPTS.*glob\|scripts.*\.glob\(\|scripts.*iterdir` in `tests` | none | yes |
| AV6 | No class path in `config/` | Grep `probos\.[a-z_.]+\.[A-Z][A-Za-z]+` in `config` | none | yes |
| AV7 | (A1, 2026-10-27) No class is aliased at module level and so re-exportable under its alias | Grep `^\s*from \S+ import .*\b[A-Z]\w* as [A-Za-z]\w*` and `^\s+[A-Z]\w* as [A-Za-z]\w*,?\s*(#.*)?$` in `src/probos`; Grep the same in `**/__init__.py` | `admission/taxonomy.py:15` and `cognitive/standing_interests.py:57` (constants); `ward_room/threads.py:549`, `ward_room/messages.py:298,426`, `runtime.py:1661-1663` (inside functions); `cognitive/repair_issue.py:19` (`TraceReader as TraceReader`, same name); `__init__.py`: `doctor/__init__.py:24` (a module) | yes for capitalised names; aliased functions not enumerated |
| AV8 | (A1, 2026-10-27) Nothing sets `runtime.action_dispatcher`, `teams_adapter`, `federation_hebbian_map` or `federation_cluster_monitor` (R11) | Grep `\b(action_dispatcher\|teams_adapter\|federation_hebbian_map\|federation_cluster_monitor)\b` in `src/probos`; Grep `setattr\((self\.)?(runtime\|self\|rt)\b` in `src/probos` | 12 lines: reads at `reply_pipeline.py:1070`, `routers/agent_actions.py:34`, `routers/teams_webhook.py:29`, `commands_status.py:165-166`; `= None` at `runtime.py:1309-1310`; the rest are docstrings, a log string and imports. `setattr`: `startup/shutdown.py:371,470,472`, each setting `None` | yes |

## Not verified (the orchestrator verifies by running)

1. The real-tree scan's output: which classes it flags, how many, and how long it takes. Every count here is predicted.
2. That `print` to a pipe on Windows writes CRLF (the D-43 host claim), and that `Path` sorting there is case-insensitive (D-27).
3. That `yaml.safe_dump(..., sort_keys=True)` output parses back to the same mapping (T3 asserts it).
4. That `check_architecture_principles.py --check` does not scan `scripts/`. Run it after M1.
5. That no `src/probos` module uses `__all__ +=`. An augmented `__all__` would count its strings as uses.

## 12. Deterministic gate checks, resolved up front

- `run_test_gate.py`: unchanged; the check is not a phase (D4).
- `check_config_readers.py`, `check_config_facade.py`, `check_store_registry.py`: no config, model or store change.
- `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py`: regenerate in M2.
- The new real-tree exit case (T5) runs the full scan in the suite. It cannot fail on findings: `main` exits 0 and prints the prefix on every path.

## 13. Prior Art and Blind Spots

- **External: vulture** (https://github.com/jendrikseipp/vulture), the closest analogue. It matches names over `ast`, reports unused classes at 60% confidence, and keeps a generated whitelist (`--make-whitelist`).
  - **Absorbed:** name matching, report-only, a generated record of accepted findings.
  - **Adapted:** our baseline carries a reviewed disposition instead of fake uses. Our rule counts value uses only, because the question is "is it used at run time?", not "is it named?".
  - **Adapted (A1), aliases:** vulture's `_add_aliases` adds `name_and_alias.name` to `used_names` whenever an `asname` is imported (https://github.com/jendrikseipp/vulture/blob/main/vulture/core.py). We count the original only where the alias is used as a value or a base, because an unused import is not a use (D1).
  - **Rejected:** confidence percentages (the dispositions do that job) and `--ignore-names` (it hides findings without review).
- **Reference projects:** `docs/research/reference-projects.md` has no dead-code tooling row. Its overdue rows were not examined (date used: 2026-10-27).
- **Internal:**
  - BF-926 `check_config_readers.py`: conventions copied, with stated departures (baseline, byte-level stdout, no `probos` import, no real-tree pins).
  - `check_config_facade.py`: the YAML baseline and `--update-baseline` pattern.
  - The 2026-10-16 audit: replaced.
  - `platform-maturity-program.md:255,290`: no second registry.
  - AD-1270a activation receipts: the runtime truth, which this static check does not replace.
- **Blind spots handled:**
  - loop, factory and constant-namespace use;
  - same-module live users;
  - schema construction by validation;
  - `TYPE_CHECKING` aliases;
  - registering class decorators (`knowledge/embeddings.py:119`);
  - a rewrite from a broken scan or an unreadable baseline;
  - CRLF and path-order drift across hosts;
  - absolute paths in output.
- **Blind spots recorded, not fixed:** R1 to R6.

## 14. Diff Reviewer: properties to verify

**M1 (as amended by A1):**
1. `main` returns 0 for every argv and every file state, and its first output line starts with `PREFIX`. This includes `--help`, which `main` answers through `_emit` (A1).
2. A class is reported if and only if the D1 rules find no live value use and D3 does not exclude it. Imports, annotations, `__all__`, `isinstance`/`issubclass` second arguments, `is` operands and `TYPE_CHECKING` bodies never make a class live.
   - (A1) After `from m import X as Y` anywhere in a module, a value use of `Y` in that module, or a base written `Y`, counts as `X`. An alias that is only imported or only annotates does not. An alias in one module never resolves a name in another.
   - (A1) The repair is monotone: it only adds names to use sets and bases, so it removes report rows and never adds one.
3. `--update-baseline` never writes after a scan warning or from an unreadable or non-baseline document. When it writes, reviewed `disposition`/`owner`/`note` survive, new classes are `unreviewed`, and rows no longer dormant are dropped.
4. The baseline and stdout are UTF-8 and sorted, with no timestamp.
   - The header, the keys and every diagnostic line name no absolute path; a retained `owner` or `note` is kept as written (A1, F5).
   - The baseline is LF. stdout is LF when it has a byte buffer; a text-only stdout gets `print`'s line ends (A1, F6).
5. The script imports nothing from `probos` and writes no file other than `--baseline`.
6. No test asserts which classes the real tree reports.
7. (A1) Every claim in the module docstring, in `HEADER` and in the docstrings of `render_baseline`, `_emit` and `main` is true of the code at the commit.

**M2:**
8. `--check` reports `171 dormant class(es): 0 new, 0 without a reviewed disposition, 0 baseline row(s) no longer dormant` (171 predicted). No row carries fields other than `disposition`, `owner` and `note`.
9. (A1) None of the review step's 14 alias rows is in the baseline. The 119 applied rows equal its table less those 14, field for field, and no seed row changed.
10. (A1) Each `owner` names an issue, or the AD of an issue, that exists and is OPEN. Each `false-positive` `note` is true of the tree at the commit: the `file:line` it cites says what the note claims. The U1 and U2 sentences are true of the code.

## 15. Acceptance criteria

- [ ] M1 and M2 built in order with the review step between, one delegation and one local commit each, staged by explicit path.
- [ ] The new test file failed at collection on M1's base before the script was written.
- [ ] M1's focused gate passes with `-n 0`. The Builder's report contains the full `--check` output and any seed with no row.
- [ ] (A1) Over `935acb6a`'s script, T9 fails at its first assertion and T10 at its second, and the other 18 cases pass. On the A1 commit all 20 pass.
- [ ] (A1) At the A1 commit, `--update-baseline` drops exactly the 14 alias rows and changes only the header's first line; `--check` then prints `0 new, 119 without a reviewed disposition, 0 baseline row(s) no longer dormant` (predicted).
- [ ] The §10 campaign runs once on the A1 commit (it supersedes M1's). Every row D-1 to D-64 is killed, or recorded as host-equivalent (D-27, D-43, D-48 on Linux only), or returned to the Architect.
- [ ] After M2, `--check` shows no findings. `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass.
- [ ] The orchestrator's single broad gate passes with its receipt.
- [ ] #1324 gets a ticked slice-2 checklist item with commits and receipt, and the register rows below.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R1.** `OntologyService.set_alert_condition` has no caller (`ontology/service.py:105`), so `red_alert` never fires. It is a method, outside a class check. Owner: whichever slice gives the alert condition a writer.
- **R2.** Names are matched, not resolved, apart from A1's import-alias rule (D2).
  - **Under-reports:**
    - Two classes with one name are live together.
    - A use from a dormant module counts.
    - A use of an alias counts every name its module imports under it.
    - An inert decorator imported under an alias (`from dataclasses import dataclass as dc`) counts as registering.
    - `Y = X` counts `X` as used even when `Y` never is.
  - **Over-reports** (a live class listed): a class reached only through an alias imported again under that alias from the module that made it (none for class names today, AV7), only through `getattr` or an import with a computed name, or as R3 says.
- **R3.** Construction from `config/`, an entry point or a run-time-built name is invisible. None exists today (AV6; the entry point is a function).
- **R4.** An owner issue that has closed is not detected offline. Example: the audit called `RegistryComponentSource` staged under AD-1287, but #1334 is CLOSED. The review step decides its row.
- **R5.** Mutants D-27, D-43 and D-48 are killed only on Windows; on Linux they are equivalent.
- **R6.** Retiring the 43 typed events (D6) is a later slice with a DECISIONS entry. Until then they stay listed as `retire`.
- **R7.** (Round 1 F2: P2, reached only by injected faults, recorded.) `load_baseline` (`scripts/check_dormant_classes.py:236-252` at `935acb6a`) accepts any YAML document with a `classes` mapping.
  - A duplicate class key keeps the last row with no warning, so a reviewed row can become `unreviewed`.
  - An unsupported `schema_version` is accepted, and `--update-baseline` rewrites it as 1.
  - An unrelated document with a `classes` mapping is treated as a baseline.
  - **Reach:** a hand-edited or future-format baseline only. The loss shows in `git diff` and in `--check`'s output.
  - **Smallest fix:** a `SafeLoader` subclass whose mapping constructor raises on a repeated key, and rejection of any `schema_version` other than 1 and of a non-mapping row. Each returns `None` with a warning, so `--update-baseline` does not write.
  - Owner: #1324, the next slice that edits the script.
- **R8.** (Round 1: P3, ordinary reach, by design.) A string constant's last `.`/`:` segment counts as a use (D1). So `NullPolicyEngine` (`governance/policy_engine.py:20`) is live only through the default `Field(default="NullPolicyEngine", ...)` at `config.py:2977`, whose own description says no production code acts on it. The check cannot tell an inert string from a lookup by name. Owner: #1659 (AD-1353), which that description names.
- **R9.** (Review step F2: P3.) D3 matches schema kinds by base name, so a call protocol written without a `Protocol` base is reported: `cognitive/orders.py:36` `StandingOrderPredicate`, used only as an annotation (the default predicate is a function at `orders.py:51`). Its row is `false-positive`; no rule change.
- **R10.** (Review step F3: P3.) The scan root is `src/probos`, so a class used only from `scripts/` is reported: `maturity/registry.py:34` `MaturityRegistry`, built by `load_default_registry` for `scripts/gen_capability_truth.py:44-48`. Its row is `false-positive`; widening the root would count tooling as production.
- **R11.** (A product defect the check revealed; not a class finding.) Four `runtime` attributes are read by live code and never set to a value in `src/probos`, so each reader always takes its fallback (AV8):
  - `runtime.action_dispatcher`: `cognitive/dm/reply_pipeline.py:1070` reads it with `getattr(..., None)` and, finding nothing, strips DM action markers with the warning at `:1073` ("AD-745: runtime.action_dispatcher missing; stripping markers"). `routers/agent_actions.py:34` returns `getattr(runtime, "action_dispatcher", None)`.
  - `runtime.teams_adapter`: `routers/teams_webhook.py:29` reads `getattr(runtime, "teams_adapter", None)`.
  - `runtime.federation_hebbian_map` and `runtime.federation_cluster_monitor`: set to `None` at `runtime.py:1309-1310` and read at `experience/commands/commands_status.py:165-166`. Nothing assigns another value.
  - **Reproduce:** `rg -n "\b(action_dispatcher|teams_adapter|federation_hebbian_map|federation_cluster_monitor)\b" src/probos` lists 12 lines, and the only assignments among them are the two `= None` initialisers. `rg -n "setattr\((self\.)?(runtime|self|rt)\b" src/probos` lists only `startup/shutdown.py:371,470,472`, which set `None`.
  - **Related class rows** (all `wire`, #1324): `cognitive/dm/action_dispatcher.py::ActionDispatcher`, `channels/teams_adapter.py::TeamsAdapter`, `federation/hebbian_map.py::FederationHebbianMap`, `federation/cluster_monitor.py::FederationClusterMonitor`.
  - Owner: #1324. It is registered here; the discovery budget files no new issue.
- **R12.** (Dispositions the Captain may overrule.)
  - **Voice AD-474 substrate, `retire` ×4** (`voice/_substrate.py::BrowserSpeechRecognizer`, `SilentTextToSpeech`, `StaticWakeWordDetector`, `TranscriptionResult`). They are public re-exports of `probos.voice`, and the live speech output is `audio/tts/backends.py:22` `TTSBackend`. `_substrate.py:8` defers runtime wiring to AD-474c, which was never filed (`gh issue list --state all --search "AD-474c in:title"`: none). Alternative: `wire`.
  - **Ward room, `retire` ×2** (`ward_room/models.py::WardRoomEndorsement`, `ChannelMembership`). They are public exports, and `test_public_apis.py` pins `WardRoomEndorsement`. The live paths return a dict (`ward_room/service.py:480`) or store SQL rows (`:489`).
  - **Insights, `retire` ×2** (`cognitive/insights.py::TopicCount`, `CrewInteraction`). BF-925 left these two report sections with no source (`insights.py:23-28,82-83`). Retiring them removes two always-empty fields from the report's JSON. Alternative: build the counting store.
  - **Channel adapters, `wire` ×4** (Gmail, Matrix, Teams, Telegram). All four have tests. Their configs are not in the main config, and `__main__.py:832-874` starts only Discord, Slack and Webhook. Alternative: `retire`.
- **R13.** (Staged rows and pauses, checked 2026-10-27.)
  - Seven rows are `staged` under AD-1353 (#1659), whose body begins "PAUSED: not actionable until the Captain lifts the new-capability pause". They stay dormant while the pause holds:
    - `consensus/quorum.py::QuorumResult`
    - `security/autonomy_boundaries.py::BoundaryProbingDetector`, `DisengagementResponse`, `ProbingPattern`, `ProtectiveDisengagement`
    - `security/permission_model.py::PermissionConfig`
    - `security/trust_integrity.py::TrustViolation`
  - The four `security/container_sandbox.py` rows are `staged` under AD-1335 (#1557). That issue is OPEN with the label `enhancement`, and neither its body nor any comment mentions a pause (`gh issue view 1557 --json body,comments` filtered for `paus`: none). It is not marked paused.
  - **Two more rows are `staged` under a paused issue** (corrected after round 2, F1): `tools/work_permits.py::WorkPermit` and `::WorkPermitStore`, owner AD-1348 (#1630), whose body begins "PAUSED: not actionable until the Captain lifts the new-capability pause". The AD-1159 work permit is the authority the robot's driver holds; the store has no production construction today. Nine rows in all stay dormant while a pause holds (seven under AD-1353, two under AD-1348).
- **R14.** (The lowest-confidence `wire` rows; a later slice may turn them into `retire`.)
  - `integrations/mcp_bridge/adapter.py::MCPToolAdapter`: the live MCP path is `cognitive/agentic_dispatch.py:1619` `_McpTool`.
  - `tools/adapters.py::DeterministicFunctionAdapter`: `runtime.py:6701` says that path uses `InfraServiceAdapter`.
  - `ward_room_pipeline.py::AgentResponse`: `merge_agent_responses` has no caller.
  - `avatars/asset_manifest.py::AssetManifest`.
- **R15.** (Open issues that touch a row without owning it, found by the 79-issue census in the header note; none changes a disposition.)
  - **BF-938 (#1680, parked for the Captain's decision)** is about binding AD-607's recall anomaly gate in production. `cognitive/memory_security.py::MemorySecurityGate` stays `wire` (`#1324`) unless that fix lands, and then its row leaves the baseline in the commit that makes it live; its own text says `MemorySecurityRegistry` stays on #1324.
  - **BF-937 (#1678)** guards the `LocalDiskPersistence` write path in `cognitive/self_improvement/versioning.py`, the module of the `wire` rows `AgentVersion` and `ShadowComparisonResult`. If it retires that module instead, those two rows become `retire` owned by #1678.
  - **AD-1346 M3 (#1604)** names its own types `WorkRequest` and `AdmissionVerdict` and notes that `AdmissionRequest` and `AdmissionDecision` already exist in `execution/authority.py`; AD-1299 (#1352) lists that module and `effect_broker.py` as reusable infrastructure without naming these classes. The AD-1315 rows `AdmissionRequest`, `EnforcementSourceSnapshot`, `ManifestPublicationRequest` and `execution/effect_broker.py::EffectCoverageReport` stay `wire` (`#1324`); AD-1346 or AD-1299 may take one over.
  - **#1566 (AD-1339)** cites AD-670's `AuditFlag` and `MemoryMetabolism` as an existing owner; slice 3 (working-memory cognition) owns those rows and removes them.
