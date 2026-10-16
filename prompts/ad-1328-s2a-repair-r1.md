# AD-1328 S2a repair r1 -- review round 1: executable-resolution fidelity, the verdict on every exit, one exact string, a typed record from the run_command tool only, the whole envelope budget

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s2a-command-policy-wiring.md` (see "Amendments"). Every SEARCH below was read from the staged file and occurs once in it. No new AD or BF number (#1530).
**Dependencies:** the staged S2a candidate (base `e5dc1000`, S1 round-2 candidate). S1's public API by name only: `CommandPolicy.evaluate` / `.canonical` raise `TypeError("command_policy_command_type_invalid")` for anything but an exact `str` (`parse_command`, `canonical_command`); `ProgramResolver` answers an absolute path or None.
**Estimated tests:** about +95 cases (gate 52, tool and executor 22, agents 6, real shells 15 on Windows); 11 existing tests edited (Part A).

Verified against (staged blobs, `git ls-files -s`; `git diff` empty, so the worktree equals the index):

| File | Blob |
|---|---|
| `src/probos/execution/command_gate.py` | `2dbfccd67f53bc2bc4824251b27de38e5ca33ca9` |
| `src/probos/cognitive/swe_harness/tools.py` | `becdcf953f0bdff8d84fea9b46a699ae6e2fafee` |
| `src/probos/agents/red_team.py` | `c36d01e1559698915d93aaed8dd805e689a1a767` |
| `src/probos/tools/executor.py` | `1fb336cf4f7424f87d1d8023bae7abd9e087dced` |
| `DECISIONS.md` | `def9824226f95b609569972c3ce5e6ba486b4808` |
| `tests/test_ad1328_s2a_gate.py` | `eb69c3e47939b8fabcbe5a3a1b239f0473c1a126` |
| `tests/test_ad1328_s2a_run_command_tool.py` | `d4d4f143541fbd7d4f45f95e6afea59caf514169` |
| `tests/test_ad1328_s2a_shell_agent.py` | `047672599475f270bc835e78df5043965fcef900` |
| `tests/test_ad1328_s2a_startup_and_doctor.py` | `bcf0608daee02449a2c7dab77017d0b01e044dfb` |

If a blob differs, re-grep each SEARCH before installing.

## Problem

GPT-6.1 Sol, round 1 on staged tree `17e56476` (`logs/architect/ad1328-s2a-review-r1-report.md`; the orchestrator reproduced F1-F4, `logs/architect/s2a-review1-evidence/`). REQUEST CHANGES, five findings, all fixed here.

| F | Reach | What is wrong | Where |
|---|---|---|---|
| F1 (P1) | ordinary | Every dialect resolves a bare name with `shutil.which`. PowerShell (5.1 and 7, measured) searches no working directory, picks `<name>.ps1` before every `PATHEXT` file within a PATH directory, and runs an alias, function or cmdlet before any file (`where` -> `Where-Object`; 5.1's `curl`). With `tool.cmd` + `tool.ps1`, a pinned `allow` for the `.cmd` was proved while PowerShell ran the `.ps1` (`IntentResult.success=True`, `VerificationResult.verified=True`) | `command_gate.py:122-150` |
| F2 (P2) | ordinary | A spawn failure after an evaluated `allow` returns `ToolResult(error=...)` without the decision (`WinError 267`, `metadata={}`) | `tools.py:1242-1244` |
| F3 (P2) | injected, regression | `str(command)` three times (`:1190`, `:1199`, `:1207`; two on the base): a stateful non-string is judged as one text and spawned as another, even without a policy; a JSON number is admitted. The red team judges `str(command)` and re-runs the raw value | `tools.py:1199`, `red_team.py:424` |
| F4 (P2) | injected, regression | `command_policy_record_of` checks the outer keys, the schema, the decision and the call site only; the AD-1224 hook reads it from **any** tool. A `write_file` result carrying `canonical_key="echo REVIEW_RAW_COMMAND --token=abc"`, a bad dialect and free text in `causes` reached the emitted payload | `command_gate.py:276-301`, `executor.py:1209-1214` |
| F5 (P3) | injected, regression | `_bounded_record` shrinks only `params`; a 1,803-character genuine record with quote-heavy provenance persisted a 4,195-byte envelope (2,238 without it) | `executor.py:1120-1131`, `:1214` |

## Decisions

**D-s2a-1 Resolver (F1).** Ranked on correctness, safety, usability, testability:

| Option | Correct | Safe | Usable here | Testable |
|---|---|---|---|---|
| (c) PowerShell never answers | yes, by construction | yes | a pinned program under PowerShell is written as its path; the refusal names it | trivial |
| (a) model `.ps1` first per directory | files only: an alias, function or cmdlet still runs instead (Microsoft, `about_Command_Precedence`: alias, function, cmdlet, then external files; `where.exe` is hidden by the alias `where`) | no | keeps bare pins | needs `is_file` |
| (b) refuse when a `.ps1` exists | same alias gap, plus `which`'s own gaps (below) | no | keeps most bare pins | needs `is_file` |

**Decided: (c) for `powershell`,** because only it closes the class: a file lookup cannot name what PowerShell runs, and the loaded alias table and auto-loaded modules (the child receives `PSMODULEPATH`, `command_env.py:36-41`) are not visible from here. Cost: a pinned `allow` reached by `ShellCommandAgent` or the red team on Windows needs the absolute path written. S1 already tells the agent "run the pinned executable: <path>", and PowerShell runs a written path exactly (same Microsoft page). The canonical key of a bare name under PowerShell becomes the name as written. The starter policy has no pins.

**`cmd` gets an explicit model instead of `which`.** `shutil.which` on Windows (Python 3.12 and later) prepends `.`, this process's directory, ahead of the given path. It also returns an extensionless file last in a directory, and it reads a quoted or `%VAR%` PATH entry literally. The model: the working directory (`cwd`, or this process's, which a child given none inherits), then each `;`-separated PATH entry; within a directory each extension of the **child's** `PATHEXT` in order; the first file wins. That is measured against `cmd.exe` in 12 layouts, and an R1-M3 seam test re-measures it. The answer is None (no proof, so a pinned `allow` refuses) for: a name holding `. \ / : " % * ? < > |`; a missing or malformed `PATHEXT`; and a relative, quoted or `%` entry (or relative `cwd`) reached before the answer. An empty entry is skipped. **`posix`** keeps `which` on the child's PATH, but only an absolute answer counts (an empty or relative PATH entry is relative to a directory this lookup does not see). The probes are injected: `which` (posix) and the new `is_file` (cmd, default `os.path.isfile`); `judge` gains `pathext=`, which the tool passes from the child's environment.

**D-s2a-2 The verdict on every exit after judgement (F2).** The generic `except` returns `metadata=policy_result_metadata(verdict)`. `verdict` is None before judgement completes (validation, a judgement that raises) and with no policy, so those exits are byte-identical with the base.

**D-s2a-3 One object, judged and spawned (F3).** One rule: **the policy judges the very object the call site runs, never a conversion; `judge` accepts only an exact `str` (S1 raises otherwise).** The tool passes `command` itself to `_policy_verdict`. When the policy is active, the tool spawns that same object. With no policy it spawns `str(command)` as the base did: two conversions, and a number is spawned as its text. With a policy, a non-string (number, `str` subclass, any object) raises `TypeError` in `judge`; the handler returns `run_command failed: command_policy_command_type_invalid`, nothing is spawned, and no decision is recorded. The red team passes `command` raw, so it is unverified and not re-run. The shell agent already passes its rewritten object: a subclass is refused with `COMMAND_POLICY_UNAVAILABLE_MESSAGE` (pinned by a new test, no source change). Preflight already refuses to judge a non-string (`type(command) is not str` -> `""`, `tools.py:1166-1168`); the broker then denies it as `shell_isolation_unproven`. That holds.

**D-s2a-4 Record ingestion (F4).** Both measures, at the one ingestion point:
- **Provenance:** `command_policy_record_of(result, *, tool_id)` reads a record only when `tool_id` is exactly `"run_command"` (`RUN_COMMAND_TOOL_ID`). The hook passes `ctx["tool_id"]`, the executor's resolved registry id (`executor.py:646`, `:668`; BF-757 refuses an ambiguous one).
- **Closed, typed projection:** every field holds one of these:
  - a constant from a fixed set: schema; call site `run_command_tool` only; decision; dialect `cmd`/`posix` (the tool's); kind `argv`/`script`; cause kind;
  - a 64-character lower-case hex digest (`policy_digest`, `canonical_key`);
  - a rule name in the config grammar (`[a-z0-9][a-z0-9_.-]{0,63}`, the literal twin of `operations._COMMAND_RULE_NAME_PATTERN`, pinned by a test);
  - an `int` count from 0 to 2^31-1.

  At most 8 rules and 8 causes. Each cause is exactly `{kind, segment, rule}`: `rule` is a name exactly when `kind == "rule"`, and `segment` is a count, or None only for `unparseable`. The record is **rebuilt** from those values, and anything else drops the whole record.

**No command text, provable by enumeration:** a field can hold only those value forms, none of which is free text, and only the run_command tool's own `policy_result_metadata(verdict)` is read. The 2,048-character check is kept; the largest admitted S2a record is about 1,900 characters (test B10).

**D-s2a-5 Envelope budget (F5).** `_bounded_policy_record` runs after `_bounded_record`. Compaction order, deterministic:
1. parameter detail (the existing step, now measured with the record present);
2. the record's two lists, emptied and counted as omitted (`compact_command_policy_record`), so the decision, dialect, digest and key survive;
3. the `command_policy` field.

Without the field the payload is exactly what the base emitted. The compact record costs about 460 envelope bytes.

**D-s2a-6 Delivery.** Sections 1-13 are fenced pairs (`install_fenced_pairs.py`): `command_gate.py`, `tools.py`, `red_team.py`, `executor.py`, `DECISIONS.md`. Builders write tests only: R1-M1 (gate), R1-M2 (tool and executor), R1-M3 (agents and the new Windows-only real-shell file). Part A lists every existing test that changes. **S1 amendments: none.** **Captain: none.** Every decision makes the policy refuse more or record less; no authority, gate or control is widened.

## Section 1 -- `src/probos/execution/command_gate.py` (imports)

SEARCH:
```python
import json
import logging
import os
import shutil
import sys
from collections.abc import Callable
```
REPLACE:
```python
import json
import logging
import ntpath
import os
import posixpath
import re
import shutil
import sys
from collections.abc import Callable
```

## Section 2 -- `src/probos/execution/command_gate.py` (module docstring)

SEARCH:
```python
command, computes its canonical approval key with the same memoised resolver (a PATH
lookup on the child's environment; for ``cmd.exe`` its working directory first), and
```
REPLACE:
```python
command, computes its canonical approval key with the same memoised resolver (where the
child's shell finds a bare program name: ``cmd.exe`` its working directory, then PATH, in
PATHEXT order; ``/bin/sh`` PATH; PowerShell never, because it runs an alias, function or
cmdlet before any file -- see ``make_program_resolver``), and
```

## Section 3 -- `src/probos/execution/command_gate.py` (`make_program_resolver`, F1)

SEARCH:
```python
def make_program_resolver(
    *,
    dialect: Dialect,
    search_path: str | None,
    cwd: str | None,
    which: Callable[..., Any] = shutil.which,
) -> ProgramResolver:
    """A PATH lookup as the child's shell makes it, memoised for one judgement.

    ``search_path`` is the child's ``PATH`` (from ``build_command_env``). ``cmd.exe``
    looks in its working directory first, so for the ``cmd`` dialect ``cwd`` -- or this
    process's directory, which a child given no ``cwd`` inherits -- leads the search.
    Symlinks are not followed: a pinned ``allow`` rule names the path PATH yields. A
    miss, or an answer that is not a string, is ``None``, which a pinned rule refuses.
    """
    entries: list[str] = []
    if dialect == "cmd":
        entries.append(cwd if cwd else os.getcwd())
    if search_path:
        entries.append(search_path)
    path = os.pathsep.join(entries)
    found: dict[str, str | None] = {}

    def resolve(name: str) -> str | None:
        if name not in found:
            answer = which(name, path=path) if path else None
            found[name] = answer if type(answer) is str else None
        return found[name]

    return resolve
```
REPLACE:
```python
#: S2a repair r1 (review F1): a Windows path that names one directory whatever the current
#: drive and directory: 'C:\x', or a UNC or device path.
_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]")
#: A name holding one of these is not a bare name for the cmd lookup: an extension, a path,
#: a drive, a quote, a variable or a wildcard.
_NOT_A_BARE_NAME: Final = frozenset('.\\/:"%*?<>|')


def _pathext(value: str | None) -> tuple[str, ...] | None:
    """The child's ``PATHEXT`` as ordered upper-case extensions; None when it is missing or
    holds an entry that is not '.' followed by letters or digits."""
    if type(value) is not str:
        return None
    entries = tuple(entry.strip().upper() for entry in value.split(";") if entry.strip())
    if not entries or any(len(entry) < 2 or entry[0] != "." or not entry[1:].isalnum() for entry in entries):
        return None
    return entries


def _cmd_lookup(
    name: str, directories: tuple[str, ...], extensions: tuple[str, ...], is_file: Callable[[str], bool],
) -> str | None:
    """Where ``cmd.exe`` finds the bare name ``name`` (measured, review r1: 12 layouts): each
    directory in order and, within one, each ``PATHEXT`` extension in order; the first file
    wins. None when that cannot be established."""
    if not name or any(char in _NOT_A_BARE_NAME for char in name):
        return None
    for directory in directories:
        if not directory:
            continue  # an empty PATH entry
        if any(char in directory for char in '"%') or _WINDOWS_ABSOLUTE.match(directory) is None:
            return None  # cmd may read this entry otherwise: nothing after it is proven
        for extension in extensions:
            candidate = ntpath.join(directory, name + extension)
            if is_file(candidate):
                return candidate
    return None


def make_program_resolver(
    *,
    dialect: Dialect,
    search_path: str | None,
    cwd: str | None,
    pathext: str | None = None,
    which: Callable[..., Any] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> ProgramResolver:
    """Where the child's shell finds a bare program name, memoised for one judgement.

    ``search_path`` and ``pathext`` are the child's ``PATH`` and ``PATHEXT`` (from
    ``build_command_env``). None means the answer cannot be established; a pinned
    ``allow`` then refuses, naming the pinned path to run instead (S2a repair r1, F1).

    - ``posix``: ``which`` on ``search_path``; only an absolute answer counts (an empty or
      relative PATH entry is relative to a directory this lookup does not see).
    - ``cmd``: ``cwd`` -- or this process's directory, which a child given none inherits
      -- then each PATH entry; within a directory each ``PATHEXT`` extension in order; the
      first file wins. A name with an extension or a path, a missing or malformed
      ``PATHEXT``, and a relative, quoted or ``%`` entry reached before the answer prove
      nothing.
    - ``powershell``: never answers. PowerShell runs an alias, function or cmdlet (module
      auto-loading reads the child's ``PSModulePath``) before any file, and within a PATH
      directory ``<name>.ps1`` before every ``PATHEXT`` file (measured on 5.1 and 7), so no
      file lookup names what it runs. A pinned program is written as its absolute path.

    Symlinks are not followed: a pinned rule names the path the lookup yields.
    """
    extensions = _pathext(pathext)
    directories = (cwd if cwd else os.getcwd(), *(search_path or "").split(";")) if dialect == "cmd" else ()
    found: dict[str, str | None] = {}

    def lookup(name: str) -> str | None:
        if dialect == "powershell":
            return None
        if dialect == "cmd":
            return None if extensions is None else _cmd_lookup(name, directories, extensions, is_file)
        answer = which(name, path=search_path) if search_path else None
        return answer if type(answer) is str and posixpath.isabs(answer) else None

    def resolve(name: str) -> str | None:
        if name not in found:
            found[name] = lookup(name)
        return found[name]

    return resolve
```

## Section 4 -- `src/probos/execution/command_gate.py` (record projection and compact form, F4, F5)

SEARCH:
```python
def command_policy_record_of(result: object) -> dict[str, Any] | None:
    """The decision record a tool result carries, re-validated for the AD-1224 sink.

    Exact keys, the schema tag, a known decision and call site, JSON-serialisable and
    at most ``MAX_RECORD_CHARS``; returns a JSON copy, else None. A tool result is
    untrusted input to the record: anything else is dropped, never repaired.
    """
    metadata = getattr(result, "metadata", None)
    if type(metadata) is not dict:
        return None
    record = metadata.get("command_policy")
    if type(record) is not dict or set(record) != _RECORD_KEYS or record.get("schema") != RECORD_SCHEMA:
        return None
    decision, call_site = record["decision"], record["call_site"]
    if type(decision) is not str or type(call_site) is not str:
        return None  # a list or dict value would raise in the membership tests below
    if decision not in COMMAND_DECISION_RANK or call_site not in CALL_SITES:
        return None
    try:
        encoded = json.dumps(record, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(encoded) > MAX_RECORD_CHARS:
        return None
    copied: dict[str, Any] = json.loads(encoded)
    return copied
```
REPLACE:
```python
#: S2a repair r1 (review F4): the one tool whose result carries a decision record, and the
#: closed values each field of that record can hold. The rule-name grammar is the literal
#: twin of ``config_models.operations._COMMAND_RULE_NAME_PATTERN`` (a test pins that).
RUN_COMMAND_TOOL_ID: Final = "run_command"
_RECORD_SCHEMAS: Final = frozenset({RECORD_SCHEMA})
_RECORD_SITES: Final = frozenset({"run_command_tool"})
_RECORD_DIALECTS: Final = frozenset({run_command_tool_dialect("win32"), run_command_tool_dialect("linux")})
_RECORD_DECISIONS: Final = frozenset(COMMAND_DECISION_RANK)
_RECORD_KINDS: Final = frozenset({"argv", "script"})
_CAUSE_KEYS: Final = frozenset({"kind", "segment", "rule"})
_CAUSE_KINDS: Final = frozenset({"rule", "unmatched", "unparseable"})
_RECORD_RULE_NAME: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_RECORD_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_MAX_COUNT: Final = 2**31 - 1


def _one_of(value: object, allowed: frozenset[str]) -> bool:
    return type(value) is str and value in allowed


def _is_digest(value: object) -> bool:
    return type(value) is str and _RECORD_DIGEST.fullmatch(value) is not None


def _is_rule_name(value: object) -> bool:
    return type(value) is str and _RECORD_RULE_NAME.fullmatch(value) is not None


def _is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= _MAX_COUNT


def _cause_of(value: object) -> dict[str, Any] | None:
    """One recorded cause rebuilt from its three typed fields; None if any is not typed."""
    if type(value) is not dict or set(value) != _CAUSE_KEYS:
        return None
    kind, segment, rule = value["kind"], value["segment"], value["rule"]
    if not _one_of(kind, _CAUSE_KINDS):
        return None
    if not (_is_count(segment) or (segment is None and kind == "unparseable")):
        return None
    if not (_is_rule_name(rule) if kind == "rule" else rule is None):
        return None
    return {"kind": kind, "segment": segment, "rule": rule}


def command_policy_record_of(result: object, *, tool_id: object) -> dict[str, Any] | None:
    """The decision record a tool result carries, projected for the AD-1224 sink; else None.

    Only the resolved ``run_command`` tool's own result is read (``tool_id`` is the
    executor's resolved id). Every field must hold its closed type: a fixed constant, a
    64-character lower-case hex digest, a rule name in the rule-name grammar, or a bounded
    count. The record is rebuilt from those fields, so no field can hold command text.
    Anything else drops the whole record, never repairs it (S2a repair r1, F4).
    """
    if type(tool_id) is not str or tool_id != RUN_COMMAND_TOOL_ID:
        return None
    metadata = getattr(result, "metadata", None)
    if type(metadata) is not dict:
        return None
    record = metadata.get("command_policy")
    if type(record) is not dict or set(record) != _RECORD_KEYS:
        return None
    rules, causes = record["matched_rules"], record["causes"]
    checks = (
        _one_of(record["schema"], _RECORD_SCHEMAS),
        _one_of(record["call_site"], _RECORD_SITES),
        _one_of(record["decision"], _RECORD_DECISIONS),
        _one_of(record["dialect"], _RECORD_DIALECTS),
        _one_of(record["canonical_kind"], _RECORD_KINDS),
        _is_digest(record["policy_digest"]),
        _is_digest(record["canonical_key"]),
        _is_count(record["matched_rules_omitted"]),
        _is_count(record["causes_omitted"]),
        type(rules) is list and len(rules) <= _MAX_RECORDED and all(_is_rule_name(name) for name in rules),
        type(causes) is list and len(causes) <= _MAX_RECORDED,
    )
    if not all(checks):
        return None
    projected = [_cause_of(cause) for cause in causes]
    if any(cause is None for cause in projected):
        return None
    copied: dict[str, Any] = {
        "schema": record["schema"],
        "call_site": record["call_site"],
        "decision": record["decision"],
        "dialect": record["dialect"],
        "policy_digest": record["policy_digest"],
        "canonical_key": record["canonical_key"],
        "canonical_kind": record["canonical_kind"],
        "matched_rules": list(rules),
        "matched_rules_omitted": record["matched_rules_omitted"],
        "causes": projected,
        "causes_omitted": record["causes_omitted"],
    }
    if len(json.dumps(copied, sort_keys=True)) > MAX_RECORD_CHARS:
        return None  # not reachable for an S2a record (at most about 1,900 characters)
    return copied


def compact_command_policy_record(record: dict[str, Any]) -> dict[str, Any]:
    """``record`` without its two lists, their entries counted as omitted: the form the
    AD-1224 sink keeps when the whole record does not fit the envelope (S2a repair r1, F5)."""
    return {
        **record,
        "matched_rules": [],
        "matched_rules_omitted": min(len(record["matched_rules"]) + record["matched_rules_omitted"], _MAX_COUNT),
        "causes": [],
        "causes_omitted": min(len(record["causes"]) + record["causes_omitted"], _MAX_COUNT),
    }
```

## Section 5 -- `src/probos/execution/command_gate.py` (`CommandPolicyGate.__init__`)

SEARCH:
```python
    ``which`` is the program lookup (``shutil.which``); tests inject one.
    """

    def __init__(
        self,
        config: CommandPolicyConfig,
        *,
        platform: str | None = None,
        which: Callable[..., Any] = shutil.which,
    ) -> None:
        if type(config) is not CommandPolicyConfig:
            raise TypeError("command_policy_config_type_invalid")
        self._config = config
        self._platform = sys.platform if platform is None else platform
        self._which = which
```
REPLACE:
```python
    ``which`` (``shutil.which``, the posix lookup) and ``is_file`` (``os.path.isfile``, the
    cmd lookup) are the program lookup's probes; tests inject them.
    """

    def __init__(
        self,
        config: CommandPolicyConfig,
        *,
        platform: str | None = None,
        which: Callable[..., Any] = shutil.which,
        is_file: Callable[[str], bool] = os.path.isfile,
    ) -> None:
        if type(config) is not CommandPolicyConfig:
            raise TypeError("command_policy_config_type_invalid")
        self._config = config
        self._platform = sys.platform if platform is None else platform
        self._which = which
        self._is_file = is_file
```

## Section 6 -- `src/probos/execution/command_gate.py` (`judge`, F1, F3)

SEARCH:
```python
    def judge(
        self, command: str, *, site: CallSite, search_path: str | None, cwd: str | None = None,
    ) -> CommandGateVerdict:
        """Judge ``command`` as ``site`` will run it: in its dialect, resolving programs on
        ``search_path`` (the child's PATH) and, for ``cmd``, ``cwd`` first."""
        if not self._config.rules:  # no policy: nothing is parsed, resolved or recorded
            return NO_POLICY
        dialect = self.dialect_for(site)
        policy = self._policies[dialect]
        resolve = make_program_resolver(dialect=dialect, search_path=search_path, cwd=cwd, which=self._which)
```
REPLACE:
```python
    def judge(
        self,
        command: str,
        *,
        site: CallSite,
        search_path: str | None,
        cwd: str | None = None,
        pathext: str | None = None,
    ) -> CommandGateVerdict:
        """Judge ``command`` as ``site`` will run it: in its dialect, resolving programs as
        ``make_program_resolver`` does on the child's ``search_path`` (PATH), ``pathext``
        (PATHEXT) and, for ``cmd``, ``cwd``. ``command`` must be exactly a ``str``; anything
        else raises ``TypeError`` (S1), so a caller runs the very object judged and never
        a conversion of it (S2a repair r1, F3)."""
        if not self._config.rules:  # no policy: nothing is parsed, resolved or recorded
            return NO_POLICY
        dialect = self.dialect_for(site)
        policy = self._policies[dialect]
        resolve = make_program_resolver(
            dialect=dialect, search_path=search_path, cwd=cwd, pathext=pathext,
            which=self._which, is_file=self._is_file,
        )
```

## Section 7 -- `src/probos/cognitive/swe_harness/tools.py` (`_policy_verdict`, F1, F3)

SEARCH:
```python
    def _policy_verdict(self, command: str, cwd: object) -> CommandGateVerdict | None:
        """AD-1328 S2a: the policy's verdict on ``command`` as this tool spawns it, or None
        with no policy (no gate, or no rules), in which case nothing else is done."""
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        # The child's PATH, from the owner that builds the child's environment below.
        child_env = build_command_env(self._command_env_passthrough)
        return gate.judge(
            command,
            site="run_command_tool",
            search_path=child_env.get("PATH"),
            cwd=cwd if type(cwd) is str else None,
        )
```
REPLACE:
```python
    def _policy_verdict(self, command: Any, cwd: object) -> CommandGateVerdict | None:
        """AD-1328 S2a: the policy's verdict on ``command`` as this tool spawns it, or None
        with no policy (no gate, or no rules), in which case nothing else is done and
        ``command`` is not read. ``judge`` raises for anything but an exact ``str``, so the
        object judged is the object spawned (repair r1, F3)."""
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        # The child's PATH and PATHEXT, from the owner that builds the child's environment below.
        child_env = build_command_env(self._command_env_passthrough)
        return gate.judge(
            command,
            site="run_command_tool",
            search_path=child_env.get("PATH"),
            cwd=cwd if type(cwd) is str else None,
            pathext=child_env.get("PATHEXT"),
        )
```

## Section 8 -- `src/probos/cognitive/swe_harness/tools.py` (`invoke`: judge and spawn one object, F3)

SEARCH:
```python
            # AD-1328 S2a (#1530): the command policy judges the command before it runs. With
            # no policy the verdict is None and nothing else here changes. A judgement that
            # raises lands in the handler below: the command is not run.
            verdict = self._policy_verdict(str(command), cwd)
            if verdict is not None and not verdict.runs:
                return ToolResult(
                    error=verdict.refusal_message,
                    metadata=policy_result_metadata(verdict),
                )
            # Cross-platform: use shell=True via create_subprocess_shell
            proc = await _asyncio.create_subprocess_shell(
                str(command),
```
REPLACE:
```python
            # AD-1328 S2a (#1530): the command policy judges the command before it runs. With
            # no policy the verdict is None and nothing else here changes. A judgement that
            # raises lands in the handler below: the command is not run. Repair r1 (review F3):
            # the policy judges the object itself and the same object is spawned; a command that
            # is not exactly a str raises in judge. With no policy it is converted as before.
            verdict = self._policy_verdict(command, cwd)
            if verdict is not None and not verdict.runs:
                return ToolResult(
                    error=verdict.refusal_message,
                    metadata=policy_result_metadata(verdict),
                )
            # Cross-platform: use shell=True via create_subprocess_shell
            proc = await _asyncio.create_subprocess_shell(
                str(command) if verdict is None else command,
```

## Section 9 -- `src/probos/cognitive/swe_harness/tools.py` (generic failure keeps the verdict, F2)

SEARCH:
```python
        except Exception as exc:
            logger.warning("AD-544 RunCommandTool failed for command=%s: %s", command, exc)
            return ToolResult(error=f"run_command failed: {exc}")
```
REPLACE:
```python
        except Exception as exc:
            logger.warning("AD-544 RunCommandTool failed for command=%s: %s", command, exc)
            # AD-1328 S2a repair r1 (review F2): a failure after the policy judged the command keeps
            # its decision; before that, and with no policy, the metadata stays empty as before.
            return ToolResult(error=f"run_command failed: {exc}", metadata=policy_result_metadata(verdict))
```

## Section 10 -- `src/probos/agents/red_team.py` (judge the object re-run, F3)

SEARCH:
```python
            verdict = gate.judge(str(command), site="shell_command_agent", search_path=child_env.get("PATH"))
```
REPLACE:
```python
            # Repair r1 (review F3): the object re-run below, not a conversion; a non-str raises here.
            verdict = gate.judge(command, site="shell_command_agent", search_path=child_env.get("PATH"))
```

## Section 11 -- `src/probos/tools/executor.py` (provenance and whole-envelope budget, F4, F5)

SEARCH:
```python
            policy_record = command_policy_record_of(result)
            if policy_record is not None:
                fields["command_policy"] = policy_record
            payload = _bounded_record(fields)
```
REPLACE:
```python
            # S2a repair r1 (review F4): only the resolved run_command tool's own result is read.
            policy_record = command_policy_record_of(result, tool_id=ctx.get("tool_id"))
            if policy_record is not None:
                fields["command_policy"] = policy_record
            # S2a repair r1 (review F5): the whole envelope stays within budget with the record.
            payload = _bounded_policy_record(_bounded_record(fields))
```

## Section 12 -- `src/probos/tools/executor.py` (`_bounded_policy_record`, F5)

SEARCH:
```python
        params["detail_omitted"] = True
        payload = {**payload, "params": params}
    return payload
```
REPLACE:
```python
        params["detail_omitted"] = True
        payload = {**payload, "params": params}
    return payload


def _bounded_policy_record(payload: dict[str, Any]) -> dict[str, Any]:
    """AD-1328 S2a repair r1 (review F5): the whole envelope stays within ``_RECORD_MAX_BYTES``
    with the command policy record in it. ``_bounded_record`` has already dropped the parameter
    detail; then the record loses its two lists (counted as omitted), and last the field
    itself, which leaves the payload the base emitted."""
    if "command_policy" not in payload or _record_size(payload) <= _RECORD_MAX_BYTES:
        return payload
    from probos.execution.command_gate import compact_command_policy_record

    compact = {**payload, "command_policy": compact_command_policy_record(payload["command_policy"])}
    if _record_size(compact) <= _RECORD_MAX_BYTES:
        return compact
    return {key: value for key, value in payload.items() if key != "command_policy"}
```

## Section 13 -- `DECISIONS.md` (the S2a entry)

SEARCH:
```
- *Three call sites.* The red team's run_command verification re-ran the claimed command before reading the claim, so it would have executed a command the shell agent refused; it now answers from the verdict without re-running. Each site judges the command as it will run (after the shell agent's rewrites) in its own dialect, resolving programs on the child's PATH (`cmd`: working directory first).
```
REPLACE:
```
- *Three call sites.* The red team's run_command verification re-ran the claimed command before reading the claim, so it would have executed a command the shell agent refused; it now answers from the verdict without re-running. Each site judges the very object it runs (after the shell agent's rewrites; never a `str()` conversion, so a non-string is refused under a policy) in its own dialect. A bare program is resolved where the child's shell finds it: `cmd` in its working directory, then PATH, in the child's PATHEXT order (an explicit model, not `shutil.which`); `/bin/sh` on PATH, absolute answers only; PowerShell never, because it runs an alias, function or cmdlet before any file and a `.ps1` before PATHEXT files, so a pinned program is written as its path there (repair r1).
```

SEARCH:
```
- *Refusals and records.* A refusal names each cause (rule, justification and alternative, or the unmatched or unparseable reason when no rule decided). The AD-1224 completion record gains a validated `command_policy` record (decision, dialect, digest, canonical key, rule names, cause kinds; never the command text). An `escalate` is refused truthfully in S2a; S2b files it.
```
REPLACE:
```
- *Refusals and records.* A refusal names each cause (rule, justification and alternative, or the unmatched or unparseable reason when no rule decided). The AD-1224 completion record gains a `command_policy` record (decision, dialect, digest, canonical key, rule names, cause kinds; never the command text), read only from the `run_command` tool's own result and rebuilt from closed, typed fields; it is kept on every exit after judgement, and when the whole envelope would exceed 4,096 bytes it loses its lists, then itself (repair r1). An `escalate` is refused truthfully in S2a; S2b files it.
```

## Tests

Rules as S2a: never edit `src/`; spawns recorded by monkeypatching, except in the new real-shell file; gates built with explicit `platform=`, an injected `which` **and an injected `is_file`** (hermetic: a `cmd` lookup must not probe this host's files). In every table cell, `\|` is a literal `|`.

### Part A -- existing tests that change

| File:line (blob above) | Change | Why |
|---|---|---|
| `test_ad1328_s2a_gate.py:90-91` (`_gate`) | add `is_file: Callable[[str], bool] \| None = None`, default a recorder that answers False; pass it to `CommandPolicyGate` | hermetic cmd lookup |
| `test_ad1328_s2a_gate.py:302-334` (`test_resolver_search_order`) | rows `cmd_with_cwd`, `cmd_without_cwd`, `powershell` rewritten. Pass `pathext=".COM;.EXE"`, `search_path="C:\\P"` and the recording `is_file` (answers False). `cmd_with_cwd`: probes are exactly `C:\work\git.COM, C:\work\git.EXE, C:\P\git.COM, C:\P\git.EXE`, answer None, `which` never called. `cmd_without_cwd` is host-named: on win32 the first probe is `ntpath.join(os.getcwd(), "git.COM")`; elsewhere the answer is None with no probe (`os.getcwd()` is not a Windows path). `powershell`: no probe and no `which` call, answer None. Rows `posix` and `no_path` unchanged | D-s2a-1: cmd no longer calls `which`; PowerShell never answers |
| `test_ad1328_s2a_gate.py:337-346` (`..._cmd_searches_its_directory_even_without_a_path`) | `is_file` answers True for `C:\work\git.EXE`, `pathext=".EXE"`: answer `C:\work\git.EXE` for `search_path` None and `""`; control: `posix` and `powershell` with `""` give None, PowerShell with no probe | same |
| `test_ad1328_s2a_gate.py:409-422` (win32 half of `test_judge_resolves_programs_on_the_childs_path_and_directory`) | gate built with a recording `is_file`; judge with `pathext=".EXE"`, `search_path="C:\\P"`: cmd with `cwd="C:\\work"` probes `C:\work\git.EXE`, then `C:\P\git.EXE`; without `cwd` the first probe is host-named as above; the `shell_command_agent` call adds no probe; `cmd_where.calls == []`. Posix half `:424-429` unchanged | same |
| `test_ad1328_s2a_gate.py:744, :789, :801-805, :839` | every `command_policy_record_of(x)` -> `command_policy_record_of(x, tool_id=RUN_COMMAND_TOOL_ID)`; expectations unchanged (`not_finite`, `too_long` and the rest stay rejected, now by type) | F4 signature |
| `test_ad1328_s2a_gate.py:808-821` (`test_record_validator_accepts_exactly_the_bound_and_no_more`) | Replaced by B10. Its padding builds a 2,000-character rule name, which the typed projection refuses, so the length bound is now proved by the types | F4 |
| `test_ad1328_s2a_gate.py` imports | add `RUN_COMMAND_TOOL_ID`, `compact_command_policy_record` | |
| `test_ad1328_s2a_run_command_tool.py:103-106` (`_gate`) | add `is_file` as in the gate file | hermetic |
| `test_ad1328_s2a_run_command_tool.py:478-520` (#7) | Remove row `cmd_without_working_directory` (host-dependent; B3 covers it). Rewrite `cmd_with_working_directory`: `setenv("PATH", "C:\\tools")`, `setenv("PATHEXT", ".COM;.EXE")`, and the tool is `RunCommandTool(SimpleNamespace(), command_env_passthrough=("PATHEXT",), command_policy_gate=gate)`, so the child carries PATHEXT on every host. The pin is `C:\tools\git.EXE`; `is_file` answers True for it. Probes: `C:\work\git.COM, C:\work\git.EXE, C:\tools\git.COM, C:\tools\git.EXE`. The spawn's `env` is `build_command_env(("PATHEXT",))`, and `which` is never called. Control: `is_file` also answers True for `C:\work\git.EXE`, which gives forbid naming `C:\work\git.EXE` and no spawn. The posix row is unchanged | D-s2a-1 |
| `test_ad1328_s2a_run_command_tool.py:1001-1022` (`..._drops_a_record_the_tool_result_forged`) | row `valid_control` now asserts `"command_policy" not in payload`: a well-formed record from a tool that is not `run_command` is not read. The positive control moves to B14 | F4: the row pinned the defect |
| `test_ad1328_s2a_startup_and_doctor.py:121-122` (`_gate`) | pass `is_file=lambda path: False` | hermetic |

`tests/test_ad1328_s2a_shell_agent.py`: no change. Its `judge_spy` (`:177-181`) has no `pathext`; the agents never pass it (H7).

### Part B -- new tests

**R1-M1, appended to `tests/test_ad1328_s2a_gate.py`:**

- **B1** `test_r1_judge_takes_exactly_a_str[int, bytes, str_subclass, stateful]`. A configured gate raises `TypeError` matching `command_policy_command_type_invalid` for each, and the stateful object's `__str__` is never called. An unconfigured gate returns `NO_POLICY` for each with no `__str__` call. Control: `"echo hi"` is judged.
- **B2** `test_r1_cmd_lookup[...]` calls `make_program_resolver(dialect="cmd", ...)` with an `is_file` that answers from a set and records each probe. Each row asserts the answer and the probes in order up to it. Default PATHEXT is `.COM;.EXE;.BAT;.CMD`.
  - `cwd_first`: cwd `C:\work`, PATH `C:\d1`, files `C:\work\tool.BAT` and `C:\d1\tool.EXE`. Answer: `C:\work\tool.BAT`.
  - `path_order`: PATH `C:\d1;C:\d2`, files `C:\d1\tool.CMD` and `C:\d2\tool.EXE`. Answer: `C:\d1\tool.CMD`.
  - `pathext_order`: files `C:\d1\tool.BAT` and `C:\d1\tool.CMD` give `.BAT`; with PATHEXT `.CMD;.BAT` they give `.CMD`.
  - `never_ps1`: only `C:\d1\tool.ps1`. Answer: None; no probe ends in `.ps1`.
  - `empty_entry_skipped`: PATH `C:\d1;;C:\d2`, file `C:\d2\tool.EXE`. Answer: that file.
  - `relative_entry_before_hit`: PATH `bin;C:\d2`, files `bin\tool.EXE` and `C:\d2\tool.EXE`. Answer: None.
  - `relative_entry_after_hit`: PATH `C:\d1;bin`. Answer: `C:\d1\tool.EXE`.
  - `quoted_entry_before_hit`: PATH `"C:\d1";C:\d2`. Answer: None.
  - `percent_entry_before_hit`: PATH `%T%;C:\d2`. Answer: None.
  - `unc_entry`: PATH `\\srv\share`. Answer: `\\srv\share\tool.EXE`.
  - `name_with_extension` (`tool.exe`), `name_with_path` (`bin\tool`), `missing_pathext` (None), `malformed_pathext` (`COM;.EXE`), `relative_cwd` (`work`): None, with **no probe**.
- **B3** `test_r1_cmd_without_cwd_starts_in_this_process_directory` (host-named): on win32 the first probe's directory is `os.getcwd()`; elsewhere the answer is None with no probe.
- **B4** `test_r1_powershell_never_answers`: `dialect="powershell"` with a `which` and an `is_file` that would both answer gives None, and neither is called. Through a win32 gate, with a pinned `allow` for `git` (pin `C:\tools\git.EXE`, `is_file` True for it, `pathext=".EXE"`, `search_path="C:\\tools"`):
  - `shell_command_agent` with `git status` gives `forbid`, `runs is False`, and the message contains `C:\tools\git.EXE`.
  - `C:\tools\git.EXE status` written at the same site gives `allow` (premise: S1 reads it as that path).
  - `git status` at `run_command_tool` gives `allow` (cmd proves it).
  - The canonical key of the bare form under PowerShell has `parts[0] == "git"`.
- **B5** `test_r1_posix_lookup_needs_an_absolute_answer[git, ./git, bin/git, /usr/bin/git]`: only the last is returned.
- **B6** `test_r1_record_projection_admits_only_typed_fields[...]`. Each row forges one field of the genuine record (from `_recorded()`) and expects None. The control returns an equal copy whose lists are new objects. Rows:
  - schema `v2`;
  - call_site `shell_command_agent`;
  - decision `Allow`;
  - dialect `powershell`, and dialect `bash`;
  - kind `argv x`;
  - policy_digest of 63 hex characters, of upper-case hex, and as `SENTINEL text`;
  - canonical_key `echo REVIEW_RAW_COMMAND --token=abc` (the review's);
  - `matched_rules_omitted` as `True`, `-1`, `2**31`, `1.0` and `"1"` (and the same for `causes_omitted`);
  - rule names: 65 characters, `Has-Upper`, `two words`, `7` (an int), nine names, a tuple;
  - causes: a string, nine causes, an extra key `"text"`, kind `evil`, kind `rule` with rule None, kind `unmatched` with a rule name, kind `rule` with segment None, segment `-1`, segment `True`, rule `curl evil --token=abc`.
- **B7** `test_r1_record_projection_reads_only_the_run_command_tool[write_file, none, str_subclass_of_run_command, empty]`: the genuine record gives None for each; `tool_id="run_command"` accepts it; `RUN_COMMAND_TOOL_ID == RunCommandTool.tool_id`.
- **B8** `test_r1_record_rule_name_grammar_is_the_config_grammar`: `command_gate._RECORD_RULE_NAME.pattern == operations._COMMAND_RULE_NAME_PATTERN`.
- **B9** `test_r1_compact_record`: for M1 #13's 20-rule record, the compact form has empty lists and `matched_rules_omitted == causes_omitted == 20`, its other nine fields are equal, and it passes `command_policy_record_of(..., tool_id="run_command")` unchanged.
- **B10** `test_r1_the_largest_admitted_record_is_within_the_bound`. Build the record with 8 names of 64 characters, 8 `rule` causes with 64-character names and segment `2**31-1`, both counts `2**31-1`, decision `escalate`, dialect `posix`, kind `script` and hex digests. It is accepted, and `len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS`. The same record with one 65-character name gives None.

**R1-M2, appended to `tests/test_ad1328_s2a_run_command_tool.py`** (gate: `forbid curl`, `unmatched="allow"`):

- **B11** `test_r1_policy_spawns_the_object_it_judged`: `{"command": c}` with a plain `c = "echo hi"` gives one spawn with `args[0] is c`.
- **B11b** `test_r1_policy_refuses_a_command_that_is_not_text[number, str_subclass, stateful]`. Every row: error `run_command failed: command_policy_command_type_invalid`, no spawn, `metadata == {}`.
  - `number`: `5`.
  - `str_subclass`: a value of `"curl x"` whose `__str__` returns `"echo hi"`.
  - `stateful`: `__str__` returns `"echo ok"`, then `"curl x"`; it is called exactly once (the validation line).
- **B12** `test_r1_no_policy_converts_as_before[no_gate, unconfigured]`: the stateful object (`"echo a"`, then `"echo b"`) gives exactly 2 `__str__` calls and a spawn of `("echo b",)`; `5` is spawned as `("5",)`. In both, `metadata == {}`. This is the base's behaviour at `e5dc1000`.
- **B13** `test_r1_spawn_failure_keeps_the_decision`.
  - (a) The recorder raises `OSError("spawn refused")`: the error is `run_command failed: spawn refused` and `metadata["command_policy"]["decision"] == "allow"`. Through `_recorded`, the emitted `command_policy` equals it.
  - (b) A real spawn (no recorder) with `working_directory=str(tmp_path / "missing")`: the error starts `run_command failed:` and the decision is `allow`.
  - Controls: with no policy the same failure equals `ToolResult(error="run_command failed: spawn refused")`; a `judge` that raises gives `metadata == {}`.
- **B14** `test_r1_ad1224_reads_only_the_run_command_tool`.
  - A `_StandInTool` subclass with `tool_id = "run_command"` that returns the genuine record: the record is retained.
  - The same stand-in returning the review's forgery (`canonical_key="echo REVIEW_RAW_COMMAND --token=abc"`, `dialect="bash"`, a cause `{"kind": "rule", "segment": 0, "rule": "curl evil --token=abc"}`): no `command_policy`, and neither `REVIEW_RAW_COMMAND` nor `--token=abc` appears in the payload JSON.
  - `tool_id = "write_file"` returning the genuine record: no key.
- **B15** `test_r1_bounded_policy_record_steps`, unit-testing `probos.tools.executor._bounded_policy_record` on synthetic payloads (`tool_id`, `agent_id`, `invocation_id`, a `pad` string, the record):
  - (i) a payload that fits is returned as the same object;
  - (ii) a `pad` sized so the full payload is over 4,096 but the compact one fits gives the compact record, every other key equal;
  - (iii) a `pad` so large that the compact one is over too gives a payload with no `command_policy` and every other key unchanged;
  - (iv) an oversized payload with no record is returned as the same object.
- **B16** `test_r1_the_envelope_stays_within_budget_at_maximal_fields` (amended after install, D-fix-1). Setup: a real executor and registry, and a posix gate with M1 #13's 20 forbid rules (64-character names) over 20 segments. Pass `context={"thread_id": q, "_crew_work_item_id": q, "_agentic_run_id": q}` and `agent_id=q`, with `q = '"' * 200`. The real record cannot overflow the real 4,096-byte bound (B16b), so this test lowers it: `monkeypatch.setattr(executor_module, "_RECORD_MAX_BYTES", 3000)`, and every assertion reads `bound = executor_module._RECORD_MAX_BYTES` after the patch. 3,000 sits between the compact envelope (about 2,390 bytes: the full 3,889 less about 1,500 for the two lists, each list entry's quotes escaped twice) and the full one (3,889 less the parameter detail, which is under 200 bytes for one `command` field).
  - Compact step (bound 3,000). Premises: the emitted payload without `error`, with the full record put back, has `_record_size > bound`; with `compact_command_policy_record(full)` put back, `<= bound`. The emitted payload without `error` has `_record_size <= bound`, its `command_policy` equals `compact_command_policy_record(full)` (decision `forbid`, `matched_rules == []`, `matched_rules_omitted == 20`), and when it carries `params`, `params["detail_omitted"] is True` (the first step ran).
  - Durable (bound 3,000, the same patch): copy `_paired` and `_rows` from `tests/test_ad1224_durable_tool_start.py:110-125` and use a real `EventLog` in `tmp_path`. The persisted completion row's data has `_record_size <= bound` and the same compact record.
  - Drop step: `monkeypatch.setattr(executor_module, "_RECORD_MAX_BYTES", 1500)`, a fresh recorded executor, the same call. Premise: the emitted payload without `error`, with the compact record put back, has `_record_size > 1500`. The emitted payload has no `command_policy`, and its key set equals the compact step's key set less `command_policy` (values such as the invocation id and duration differ per call, so compare keys only).
  - If any premise fails, stop and report the observed sizes; do not move the bounds.
- **B16b** `test_r1_the_typed_record_fits_the_real_envelope_at_maximal_provenance` (new, D-fix-1). No patch; the B16 setup with `q = '"' * 200` (quotes are the worst escaping case under `_bounded_text`'s 128-JSON-byte cap). The emitted payload without `error` keeps `command_policy == full` (not compacted), has `_record_size <= 4096`, and carries no `params["detail_omitted"]`. The durable row keeps the same full record. A comment records the measurement: 3,888 to 3,889 bytes on 2026-10-16 (about 207 bytes of headroom). A record that grows (S2b's `approval` field, H8) fails this test, and S2b must re-measure and re-anchor B16 and B16b.
  - Control: the same call with plain `"t"` provenance keeps the full record.

**R1-M3, appended to `tests/test_ad1328_s2a_shell_agent.py`:**

- **B17** `test_r1_red_team_judges_the_object_it_reruns`: a `str` subclass with value `"curl x"` and `__str__` returning `"echo ok"`. `_verify_run_command` does not re-run it, gives `verified is False`, and the discrepancy names the policy. Control: a plain `"echo ok"` is re-run once with `reruns.calls[0][0] is command`.
- **B18** `test_r1_shell_agent_refuses_a_command_that_is_not_text`: `_run_command(subclass)` returns `{"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}`, and `_run_sync` is not called. Control: a plain `"echo ok"` runs with the identical object.
- **B19** `test_r1_agents_refuse_a_pinned_bare_name_under_powershell`. Gate: `platform="win32"`, a pinned `tool` (pin `C:\d1\tool.CMD`) and a `which` and `is_file` that answer the pin. The agent's `_run_command("tool")` is refused, the message names `C:\d1\tool.CMD`, and `_run_sync` is not called. The red team does not re-run it.

**R1-M3, new file `tests/test_ad1328_s2a_r1_real_shells.py`** (`pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe and Windows PowerShell")`; real shells, real `os.path.isfile`).

Fixture files in `tmp_path` directories: `.bat` echoes `BAT` and writes `ran_bat` beside itself; `.cmd` echoes `CMD`; `.ps1` writes `ran_ps1` and outputs `PS1`; `.exe` is a copy of `%SystemRoot%\System32\hostname.exe`. Environment: `{SYSTEMROOT, PATH, PATHEXT: ".COM;.EXE;.BAT;.CMD"}`.

- **B20** `test_r1_cmd_lookup_names_the_file_cmd_runs[cmd_only, bat_and_cmd, exe_and_cmd, cmd_and_ps1, d1_ps1_d2_cmd, cwd_bat_d1_cmd, d1_empty_d2_cmd]`. `subprocess.run("tool", shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)` is the `cmd.exe /c` that `create_subprocess_shell` starts. The marker it prints is the one of the file that `make_program_resolver(dialect="cmd", search_path=PATH, cwd=cwd, pathext=PATHEXT)("tool")` names. Premise: each single-file control prints its own marker.
- **B21** `test_r1_powershell_runs_a_file_no_lookup_names`. With `cmd_and_ps1` in `d1`, `powershell -NoProfile -ExecutionPolicy Bypass -Command tool` prints `PS1`, while the cmd lookup names `tool.CMD` and the PowerShell resolver gives None. `(Get-Command where).CommandType` is `Alias`. pwsh 7 repeats both when it is installed (skip otherwise).
- **B22** `test_r1_tool_and_agent_end_to_end`. Gate: a real `CommandPolicyGate(policy, platform="win32")` (real probes), PATH set to `<d1>;%SystemRoot%\System32`, a pinned `allow` for `tool` with pin `<d1>\tool.CMD`, and `unmatched="escalate"`.
  - (a) With `d1` holding `tool.cmd`, `RunCommandTool.invoke({"command": "tool", "working_directory": <empty>})` (real spawn) gives stdout `CMD` and decision `allow`.
  - (b) Add `<empty>\tool.bat` and repeat: `forbid` naming it, and `ran_bat` is absent.
  - (c) With `d1` holding `tool.cmd` and `tool.ps1`, a real `ShellCommandAgent._run_command("tool")` (real `_run_sync`) is refused naming `<d1>\tool.CMD`, and `ran_ps1` is absent. `_run_command(f"{d1}\\tool.cmd")` succeeds with stdout `CMD`.

## Mutation campaign (rows added; anchors are single lines, unique after r1)

Rerun the whole S2a campaign on the committed r1 tree for every file that changed (`command_gate.py`, `tools.py`, `red_team.py`, `executor.py`). G3 and G10 are re-anchored below; G1, G2, G4-G9, G11, T1-T3, R1, X1 and A1 keep their anchors.

| Id | File | Anchor | Mutant | Killer |
|---|---|---|---|---|
| G3 (re-anchored) | command_gate.py | `directories = (cwd if cwd else os.getcwd(), *(search_path or "").split(";")) if dialect == "cmd" else ()` | `directories = tuple((search_path or "").split(";")) if dialect == "cmd" else ()` | B2 `cwd_first`; Part A `cmd_with_cwd`; M2 #7 cmd row |
| G10 (re-anchored) | command_gate.py | `if type(record) is not dict or set(record) != _RECORD_KEYS:` | `if type(record) is not dict:` | M1 #14 `extra_key`, `missing_key` |
| G12 | command_gate.py | `if dialect == "powershell":` | `if False:` | B4; B19 |
| G13 | command_gate.py | `for extension in extensions:` | `for extension in reversed(extensions):` | B2 `pathext_order` |
| G14 | command_gate.py | `if any(char in directory for char in '"%') or _WINDOWS_ABSOLUTE.match(directory) is None:` | `if False:` | B2 `relative_entry_before_hit`, `quoted_entry_before_hit`, `percent_entry_before_hit`, `relative_cwd` |
| G15 | command_gate.py | `if not name or any(char in _NOT_A_BARE_NAME for char in name):` | `if not name:` | B2 `name_with_extension`, `name_with_path` (no probe) |
| G16 | command_gate.py | `continue  # an empty PATH entry` | `return None` | B2 `empty_entry_skipped` |
| G17 | command_gate.py | `return answer if type(answer) is str and posixpath.isabs(answer) else None` | `return answer if type(answer) is str else None` | B5 |
| G18 | command_gate.py | `if not entries or any(len(entry) < 2 or entry[0] != "." or not entry[1:].isalnum() for entry in entries):` | `if not entries:` | B2 `malformed_pathext` |
| G19 | command_gate.py | `return None if extensions is None else _cmd_lookup(name, directories, extensions, is_file)` | `return _cmd_lookup(name, directories, extensions or (".EXE",), is_file)` | B2 `missing_pathext` |
| G20 | command_gate.py | `if type(tool_id) is not str or tool_id != RUN_COMMAND_TOOL_ID:` | `if False:` | B7; B14 `write_file` |
| G21 | command_gate.py | `_one_of(record["schema"], _RECORD_SCHEMAS),` | `True,` | M1 #14 `wrong_schema` |
| G22 | command_gate.py | `_one_of(record["call_site"], _RECORD_SITES),` | `True,` | B6 call_site |
| G23 | command_gate.py | `_one_of(record["decision"], _RECORD_DECISIONS),` | `True,` | M1 #14 `bad_decision`; B6 |
| G24 | command_gate.py | `_one_of(record["dialect"], _RECORD_DIALECTS),` | `True,` | B6 dialect rows |
| G25 | command_gate.py | `_one_of(record["canonical_kind"], _RECORD_KINDS),` | `True,` | B6 kind |
| G26 | command_gate.py | `_is_digest(record["policy_digest"]),` | `True,` | B6 digest rows |
| G27 | command_gate.py | `_is_digest(record["canonical_key"]),` | `True,` | B6 canonical_key; B14 forgery |
| G28 | command_gate.py | `_is_count(record["matched_rules_omitted"]),` | `True,` | B6 rows for `matched_rules_omitted` |
| G29 | command_gate.py | `_is_count(record["causes_omitted"]),` | `True,` | B6 rows for `causes_omitted` |
| G30 | command_gate.py | `type(rules) is list and len(rules) <= _MAX_RECORDED and all(_is_rule_name(name) for name in rules),` | `True,` | B6 rule-name rows; M1 #14 `too_long` |
| G31 | command_gate.py | `type(causes) is list and len(causes) <= _MAX_RECORDED,` | `True,` | B6 nine causes |
| G32 | command_gate.py | `if not _one_of(kind, _CAUSE_KINDS):` | `if False:` | B6 kind `evil` |
| G33 | command_gate.py | `if not (_is_count(segment) or (segment is None and kind == "unparseable")):` | `if False:` | B6 segment rows |
| G34 | command_gate.py | `if not (_is_rule_name(rule) if kind == "rule" else rule is None):` | `if False:` | B6 rule rows; B14 forgery |
| G35 | command_gate.py | `if type(value) is not dict or set(value) != _CAUSE_KEYS:` | `if type(value) is not dict:` | B6 cause extra key (dropped, not repaired) |
| G36 | command_gate.py | `"matched_rules": list(rules),` | `"matched_rules": rules,` | M1 #14 accepted branch (the appended `tampered`) |
| G37 | command_gate.py | `"matched_rules_omitted": min(len(record["matched_rules"]) + record["matched_rules_omitted"], _MAX_COUNT),` | `"matched_rules_omitted": record["matched_rules_omitted"],` | B9 |
| G38 | command_gate.py | `"causes_omitted": min(len(record["causes"]) + record["causes_omitted"], _MAX_COUNT),` | `"causes_omitted": record["causes_omitted"],` | B9 |
| T4 | tools.py | `verdict = self._policy_verdict(command, cwd)` | `verdict = self._policy_verdict(str(command), cwd)` | B11b `str_subclass`, `stateful`, `number` (spawned); B12 (3 conversions) |
| T5 | tools.py | `str(command) if verdict is None else command,` | `command,` | B12 (`5` and the object spawned unconverted) |
| T6 | tools.py | `return ToolResult(error=f"run_command failed: {exc}", metadata=policy_result_metadata(verdict))` | `return ToolResult(error=f"run_command failed: {exc}")` | B13 |
| T7 | tools.py | `pathext=child_env.get("PATHEXT"),` | `pathext=None,` | M2 #7 cmd row (allow needs PATHEXT) |
| R2 | red_team.py | `verdict = gate.judge(command, site="shell_command_agent", search_path=child_env.get("PATH"))` | `verdict = gate.judge(str(command), site="shell_command_agent", search_path=child_env.get("PATH"))` | B17 |
| X2 | executor.py | `policy_record = command_policy_record_of(result, tool_id=ctx.get("tool_id"))` | `policy_record = command_policy_record_of(result, tool_id="run_command")` | B14 `write_file`; Part A `valid_control` |
| X3 | executor.py | `payload = _bounded_policy_record(_bounded_record(fields))` | `payload = _bounded_record(fields)` | B16 compact and durable steps (bound patched to 3,000); not B16b, which runs at the real bound where the call is inert by construction |
| X4 | executor.py | `if "command_policy" not in payload or _record_size(payload) <= _RECORD_MAX_BYTES:` | `if "command_policy" not in payload:` | B15 (i) |
| X5 | executor.py | `if _record_size(compact) <= _RECORD_MAX_BYTES:` | `if True:` | B15 (iii) |

**Equivalent mutants, not listed:**
- `str(command),` for T5's anchor: with a verdict the command is an exact `str`, and `str()` of one is the same object.
- `if False:` for `if len(json.dumps(copied, sort_keys=True)) > MAX_RECORD_CHARS:`: B10 shows the typed maximum is below the bound. It stays as the S2b guard (H8).
- Dropping the `min(..., _MAX_COUNT)` clamps beyond G37/G38: counts near 2^31 need about 2^31 rules.

No mutant can loop: every loop above iterates a finite tuple or list.

## Closure enumeration

| F | Producer, exit or consumer | Closed by |
|---|---|---|
| F1 | `make_program_resolver`, the one producer (only `CommandPolicyGate.judge` calls it: Absence A1) | Section 3 |
| F1 | Consumers: `RunCommandTool.invoke` and `command_policy_preflight` (both through `_policy_verdict`, `cmd` or posix), `ShellCommandAgent._command_policy_refusal` and `RedTeamAgent._command_policy_verification` (PowerShell or posix) | Sections 6-7. The agents pass no `pathext`, and their dialects never read it |
| F1 | PowerShell: aliases, functions, cmdlets, module auto-load, `.ps1` first, no cwd, execution policy | Never answers (pin needs the written path) |
| F1 | cmd: `which` prepending this process's `.`, extensionless file, quoted / `%` / relative entry, relative `cwd`, empty entry, name with extension or path, PATHEXT from this process rather than the child | Model (Section 3) with fail-closed guards; the child's PATHEXT (Section 7) |
| F1 | posix: empty or relative PATH entry, relative answer | Absolute answers only |
| F1 | cmd `NoDefaultCurrentDirectoryInExePath` in the child | Holds: not in the child's allowlist (`command_env.py:28-41`), so cmd searches its directory |
| F1 | Boundary: a program **written** as an extensionless absolute path against an extensionless pin (the shell appends an extension) | S1's written-path identity (D-r2-4) and pin validator (`operations.py:121-128`); it needs an operator-authored extensionless pin. Recorded, not changed |
| F1 | Boundary: cmd `AutoRun` (registry, same user; `cmd /c` without `/d`) changing PATH or the directory | Host configuration outside the environment BF-890 controls. Recorded |
| F2 | Exits after judgement: refusal, success, timeout (already kept), generic exception (Section 9) | Kept |
| F2 | Exits before judgement: undeclared params, `command is required`, `float(timeout)` raising (propagates, unchanged), `judge` raising | No verdict: metadata empty, as before |
| F2 | `CancelledError` | Raises, no `ToolResult` (unchanged) |
| F3 | Tool: validation `str(command).strip()` (unchanged), judgement (raw, Section 8), spawn (same object, or `str()` with no policy) | Sections 7-8 |
| F3 | Red team judgement versus raw re-run | Section 10 |
| F3 | Shell agent: `decide()` uses `.strip()`/`.split()` on the object; `_strip_ps_wrapper` and `_rewrite_python_interpreter` return a new `str` or the object; `judge` and `_run_sync` get one object | Holds; B18 pins the refusal of a subclass |
| F3 | Preflight: `type(command) is not str` -> `""` before judging | Holds (no conversion); the broker denies `shell_isolation_unproven` |
| F4 | Ingestion: `make_audit_hook` non-strict branch, the one caller (Absence A1) | Provenance plus typed projection (Sections 4, 11) |
| F4 | Producers: `policy_result_metadata(verdict)` on `RunCommandTool` results (refusal, success, timeout, generic failure) | The projection accepts the genuine shape (B9, B10, M2 #12) |
| F4 | Strict AD-1224 projection (`_strict_tool_record`) | Carries no `command_policy` (unchanged; under the broker the tool is denied preflight) |
| F4 | Sinks: bus payload (`emit`, adds the closed `error` category only) and durable row (`event_log.log(data=payload)`) | Both get the projected payload |
| F5 | Completion payload (non-strict) | By construction: D-s2a-4's typed projection holds no free text, so at maximal provenance the full envelope is 3,889 bytes, within 4,096 (B16b). Section 12 is defence in depth, its steps exercised under a lowered bound (B16) and on synthetic payloads (B15). The review's 4,195 bytes were measured on the pre-repair record |
| F5 | Start records (`executor.py:1325`, `:1395`) | Carry no policy record (unchanged) |
| F5 | Bus-only `error` key added after budgeting | Bus payloads are not persisted; the durable row is the budgeted payload |

## Amendments (what r1 overrides in `prompts/ad-1328-s2a-command-policy-wiring.md`)

| Earlier text | r1 |
|---|---|
| D3 `CommandPolicyGate(config, *, platform=None, which=shutil.which)` | adds `is_file=os.path.isfile` |
| D5 *As it will run*: "`RunCommandTool` judges `str(command)`"; the red team judges `params["command"]` (Section 9 code used `str(command)`) | Each site judges the object it runs; a non-string is refused under a policy |
| D5 *Resolver*: `which(name, path=...)` for every dialect, cwd first for cmd | Posix `which` (absolute answers only); the cmd model; PowerShell never answers. `judge(..., pathext=)` |
| D5 *Judgement errors fail closed* | Plus: a failure after judgement keeps the verdict |
| D8 "re-validation (`command_policy_record_of`)", "a record without a policy is unchanged" | Provenance (`tool_id`) plus a closed, typed, rebuilt projection; whole-envelope budget with compaction |
| Blind spot (4) "`shutil.which` on Windows ... every misresolution fails closed" | Refuted by review F1 (it was not fail-closed under PowerShell) |
| M1 #4, #14, M2 #7, #12 (`valid_control`) | Part A |
| Mutation rows G3, G10 | Re-anchored |
| Hidden pin "AD-1224 record budget ... record at most 2,048 characters" | Plus `_bounded_policy_record` on the whole envelope |

## Amendments after install (2026-10-16, `claude-architect`)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16, after the R1-M2 Builder's hard stop on B16.

| Id | Decision or deviation | Contract change |
|---|---|---|
| D-fix-1 | B16's premise (full envelope over 4,096) is false with the typed record: measured 3,888-3,889 bytes at maximal provenance, because `_bounded_text` (`executor.py:81-89`) caps each provenance string at 128 JSON bytes and D-s2a-4 removed the record's free text. F5 is closed by construction; `_bounded_policy_record` (`executor.py:1134-1146`) is kept as defence in depth, because S2b's `approval` field (H8) can make it reachable. Deleting it would leave S2b to rediscover the bound | B16 lowers `executor_module._RECORD_MAX_BYTES` to 3,000 (compact step and durable half) and 1,500 (drop step), with premises asserted; new B16b pins the real headroom at 4,096; X3's killer is B16 under the patch; closure row F5 restated. Section 13 (installed DECISIONS text) stands: it states the rule ("when the whole envelope would exceed 4,096 bytes"), not a measured overflow. The Problem table's 4,195 bytes stays, as the pre-repair measurement |
| D-fix-2 | Accepted, no source change. `tools.py:1248` (`logger.warning("... command=%s", command)`, AD-544, pre-existing) stringifies a refused non-text command when log handlers format it; the policy and the spawn never read it. Only an injected object reaches it (tool parameters arrive as JSON values). Recorded as an S2a blind spot: a non-text command's `__str__` may run in log formatting | B11b `stateful` disables that logger in the test and asserts `calls == 1` for the validation line, with a comment naming this decision |
| Dev-1 | B13 split into `(a)` and `(b)` test functions | None (same assertions) |
| Dev-2 | M2 #7's cmd row moved to `test_resolver_cmd_searches_the_working_directory_then_the_child_path_with_its_pathext`; the escaped-path control asserts `repr("C:\\work\\git.EXE") in error` | T7 and G3 killers name the new test |
| Dev-3 | B19 pins two paths, `C:\d1\tool.CMD` and `/d1/tool.CMD`, with a `which` answering the posix one: the single Windows pin left G12 alive (the mutant fell to the posix branch, where `posixpath.isabs("C:\\d1\\tool.CMD")` is false) | G12 killed by B4 and the two-pin B19 |
| Dev-4 | B20's lone `.ps1` control asserts that nothing runs under cmd; B20 controls use a clean working directory (a `.bat` there shadowed the `.cmd` control); B22's PATH is `<d1>;System32;System32\WindowsPowerShell\v1.0` (the agent starts `powershell` by name) | None (B20 found all 7 layouts equal to the model; no architectural stop) |

## Hidden pins (enumerated)

| Id | Pin | Effect |
|---|---|---|
| H1 | S2a tests that inject `which` for cmd/PowerShell, call `command_policy_record_of`, or pin acceptance from any tool | Part A, every row named (Absence A2) |
| H2 | Architecture fitness (`scripts/check_architecture_principles.py:187-188`) | New module functions only; `CommandPolicyGate` keeps 8 methods, `RunCommandTool` 4 |
| H3 | S1 wiring scan `test_only_the_gate_constructs_the_policy` (spares `command_gate.py`'s imports from `command_policy`) | No new import from `command_policy` |
| H4 | BF-892 launch guard / BF-890 env scan | The launch statement's arguments change; its `env=` and kwargs do not |
| H5 | Tool schema golden; `RunCommandTool.input_schema` | Unchanged |
| H6 | Layer boundaries | New imports are `ntpath`, `posixpath`, `re` only |
| H7 | M3 `judge_spy` signature (`test_ad1328_s2a_shell_agent.py:177-181`) has no `pathext` | Holds: the agents do not pass it |
| H8 | **S2b re-anchor list** (`prompts/ad-1328-s2b-command-policy-escalation.md`) | `command_policy_record_of(result, *, tool_id)`, rebuilt typed projection. S2b's anchor `if record["decision"] not in COMMAND_DECISION_RANK or record["call_site"] not in CALL_SITES:` (`:985`) is gone: add `approval` as a typed check and include it in the rebuilt dict; `compact_command_policy_record` carries it via `**record`. S2b's `approval` adds about 200 characters, so its maximal record is over 2,048: raise `MAX_RECORD_CHARS` or bound it, and extend B10. `_RECORD_SCHEMAS` holds `RECORD_SCHEMA` (v1 -> v2 follows). `_policy_verdict(self, command: Any, cwd)`. The anchor `verdict = self._policy_verdict(str(command), cwd)` (`:1072`) is now `self._policy_verdict(command, cwd)`. S2b's `_escalate(verdict, str(command), context)` must pass `command`. The spawn line is `str(command) if verdict is None else command,`. The generic `except` returns metadata. `judge(..., pathext=)`; `CommandPolicyGate(..., is_file=)`; `make_program_resolver(..., pathext, is_file)`. S2b's gates are `platform="linux"` with a fake `which`: unaffected |

## What This Does NOT Change

S1 (`command_policy.py`, `operations.py`); the record keys and schema; the refusal frames; the no-policy paths (B12, M2 #1, M3 #1, #9); preflight; the shell agent's source; the broker and its adapters; the strict AD-1224 projection; the starter policy.

## Tracking

DECISIONS.md (Section 13). No PROGRESS or roadmap change (same AD, same PR).

## Acceptance Criteria

1. Sections 1-13 install mechanically; each SEARCH occurs exactly once.
2. Part A and Part B as written; the four S2a test files plus `tests/test_ad1328_s2a_r1_real_shells.py` pass at `-n 0` on Windows (and on Linux with B20-B22 skipped).
3. The orchestrator re-runs the review's probes (`probe_s2a_f1_wide.py`, `probe_s2a_f1_resolution.py`, `probe_s2a_findings_2to5.py`). Each finding no longer reproduces: F1, the PowerShell pinned allow is refused; F2, the decision is kept; F3, no conversion and the non-string refused; F4, the `write_file` record dropped. For F5, run B16's maximal case through real persistence.
4. S2a's focused gate (contract acceptance 8) and the seven `--check` scripts (acceptance 9) pass.
5. Every row above is killed; the re-anchored and unchanged S2a rows are rerun for the four changed files.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, blobs above)

```
command_gate.py:30-35    import json/logging/os/shutil/sys, Callable           (Section 1 anchor)
command_gate.py:16-17    module docstring resolver sentence                     (Section 2)
command_gate.py:122-151  make_program_resolver (which over os.pathsep-joined entries)   (Section 3)
command_gate.py:86-89    _RECORD_KEYS; :83 _MAX_RECORDED = 8; :65 MAX_RECORD_CHARS = 2048
command_gate.py:276-301  command_policy_record_of(result) outer-key validation   (Section 4)
command_gate.py:336-352  docstring "which is the program lookup"; __init__ which=  (Section 5)
command_gate.py:394-403  judge(command, *, site, search_path, cwd=None)          (Section 6)
command_gate.py:92-94    run_command_tool_dialect -> default_dialect ("cmd" on win32, else "posix")
command_policy.py:1345-1346, :1767-1768  parse_command / canonical_command raise TypeError("command_policy_command_type_invalid")
command_policy.py:1587   _evaluate calls parse_command first
command_policy.py:411, :416-420  CanonicalCommand.kind Literal["argv","script"]; key = sha256 hexdigest (64)
command_policy.py:1728   policy_digest = sha256 hexdigest
command_policy.py:313    RuleMatch.segment: int; :1512-1552 RuleMatch(rule.name, ...) only
operations.py:37         _COMMAND_RULE_NAME_PATTERN = r"[a-z0-9][a-z0-9_.-]{0,63}"; :217 max_segments le=256
tools.py:1147-1160       _policy_verdict(command: str, ...)                      (Section 7)
tools.py:1166-1168       preflight: type(command) is not str -> ""
tools.py:1190, :1199, :1207  three str(command)                                 (Section 8)
tools.py:1242-1244       except Exception -> ToolResult(error=...) without metadata   (Section 9)
tools.py: create_subprocess_shell( occurs once
red_team.py:424          gate.judge(str(command), ...)                           (Section 10); :323 re-runs raw command
shell_command.py:175-181, :221  rewrites then judge(command) with the same object
executor.py:1209-1214    command_policy_record_of(result); _bounded_record(fields)   (Section 11)
executor.py:1120-1131    _bounded_record tail                                     (Section 12)
executor.py:1108-1117    _record_size; :52 _RECORD_MAX_BYTES = 4096; :50 _DIGEST_MAX_TEXT_CHARS = 128
executor.py:633-646, :666-668  hook_context["tool_id"] = resolved canonical id
executor.py:1216-1222    bus emit adds "error"; :1238-1243 durable data=payload
protocol.py:84-87        ToolResult(output, error, duration_ms, metadata=default_factory(dict))
command_env.py:36-41, :110-111  PATHEXT, PSMODULEPATH in the Windows allowlist, copied from os.environ
effect_adapters.py:195-202, :226  preflight -> denial or shell_isolation_unproven
DECISIONS.md:29, :32     the two S2a bullets                                       (Section 13)
tests/test_ad1328_s2a_gate.py:90-91, :302-346, :409-429, :744, :764-821, :839   Part A
tests/test_ad1328_s2a_run_command_tool.py:103-106, :478-520, :1000-1025          Part A
tests/test_ad1328_s2a_startup_and_doctor.py:116-122                              Part A
tests/test_ad1224_durable_tool_start.py:110-125  _rows, _paired (B16 copies)
learn.microsoft.com about_Command_Precedence (fetched 2026-10-16): alias, function, cmdlet, then external files; "where -> Where-Object" hides where.exe; a path runs that file
```

## Absence Verified (2026-10-16)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | `make_program_resolver`, `command_policy_record_of` and `judge` have no other src callers | Grep `make_program_resolver\|command_policy_record_of\|\.judge\(\|_policy_verdict\(` in `src/` | gate `:403`; executor `:1211`; tools `:1155`, `:1170`, `:1199`; shell `:221`; red team `:424` | yes |
| A2 | Every test that injects `which` for a Windows dialect or calls `command_policy_record_of` is in Part A | Grep `which=\|command_policy_record_of\|make_program_resolver\(\|platform="win32"` in `tests/test_ad1328_s2a_*.py` | the gate, tool and doctor rows above; the shell agent's win32 gates hold unpinned rules only (`:399`, `:568`) | yes |
| A3 | No test outside S2a constructs a gate or reads the record | Grep `CommandPolicyGate\(\|command_policy_record_of` in `tests/` | S2a files only | yes |
| A4 | No test pins `str(command)` or `_bounded_record` | Grep `str\(command\)\|_bounded_record\|_record_size` in `tests/` | none | yes |
| A5 | `_bounded_record`'s other callers carry no policy record | Grep `_bounded_record\(` in `src/` | executor `:1214` (the hook), `:1325`, `:1395` (start records) | yes |

## Not verified

- I ran no shell here: the bridge allows no PowerShell or Python. F1's shell behaviour rests on the orchestrator's measured outputs (`probe_s2a_f1_wide.out.txt`, `probe_s2a_f1_resolution.out.txt`) and on Microsoft's precedence page. B20-B22 re-measure it.
- Not measured, and each fails closed or is pinned by B20: `.COM` before `.EXE` (the wide probe's two copies print the same marker); cmd's handling of an empty PATH entry (modelled as skipped; B20 `d1_empty_d2_cmd`); cmd's reading of quoted and `%` entries (refused, so it is not modelled); cmd with a name that carries an extension (refused).
- Python's `shutil.which` prepending `.` on Windows is taken from the 3.12 documentation, not run. The decision does not depend on it, because cmd no longer uses `which`.
- The staged tree id `17e56476...` was not recomputed (`git write-tree` is denied); the blobs come from `git ls-files -s`, and `git diff` is empty.
- B4's premise that S1 reads `C:\tools\git.EXE status` under PowerShell as that path; the Builder stops if it does not.

## Prior Art and Blind Spots

A repair of a reviewed slice; one external source, used and cited: Microsoft's `about_Command_Precedence` (aliases, functions and cmdlets outrank files; a path runs that file), which decides D-s2a-1 for (c). `docs/research/reference-projects.md` was not consulted; no reference project models shell resolution, so this was considered and deferred. Blind spots recorded: the cmd `AutoRun` key; the extensionless written path (S1); and a PATH changed by this process between judgement and launch (S2a blind spot 5, unchanged). Added after install (D-fix-2): an injected non-text command's `__str__` may run in the AD-544 failure log line (`tools.py:1248`); it is never judged or spawned. And (D-fix-1): the whole-envelope budget is unreachable with S2a's record (3,889 of 4,096 bytes); S2b's `approval` field must re-measure B16b.

=== BUILDER BRIEFS ===

### Brief R1-M1 -- `tests/test_ad1328_s2a_gate.py` (effort: high, at most 90 calls)

Contract `prompts/ad-1328-s2a-repair-r1.md`; source installed and frozen, so write tests only. Apply Part A's gate-file rows, then B1-B10. Every cmd lookup uses an injected recording `is_file`; never probe the host except B3's named win32 branch. Kill G3, G10, G12-G38 (gate rows). Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2a_gate.py -q -n 0`. If a premise fails (B4's written path, a count), stop and report the observed value; do not weaken an assertion.

### Brief R1-M2 -- `tests/test_ad1328_s2a_run_command_tool.py` (effort: high, at most 100 calls)

Apply Part A's tool-file rows, then B11-B16 and B16b. B13 (b) and B16's durable half are real (a real failing spawn; a real `EventLog` in `tmp_path`); everything else keeps the spawn recorder. Kill T4-T7, X2-X5. Run the file with `-n 0`, then `tests/test_ad1224_durable_tool_start.py -q -n 0`. Stop and report rather than weaken.

### Brief R1-M3 -- agents and real shells (effort: high, at most 90 calls)

Append B17-B19 to `tests/test_ad1328_s2a_shell_agent.py` (recorders as M3) and the startup file's Part A row. Create `tests/test_ad1328_s2a_r1_real_shells.py` (B20-B22, Windows only, real shells, files only under `tmp_path`, every subprocess with `timeout=60`). Kill R2, G12 (B19). Run the four S2a files and the new file with `-n 0`, then S2a's focused gate (contract acceptance 8). Report each count and every skip with its reason. If B20 finds cmd running a file the lookup does not name, stop and report the layout and both answers. That is an architectural stop, not a test to adjust.

### Mutation campaign (orchestrator, effort: high)

On the committed R1-M3 tree: baseline green; count each anchor (exactly once); one mutant at a time with a `.mutbak` restore in `finally`; run the four S2a files serially, plus the real-shell file on Windows. Record the base commit, each changed file's sha256, and KILLED / INERT / INVALID with the killer. Rerun the S2a rows of the four changed files.
