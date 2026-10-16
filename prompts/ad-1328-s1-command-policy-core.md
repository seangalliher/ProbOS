# AD-1328 S1 -- Command execution policy core: prefix rules, a three-dialect tokenizer, strictest wins, self-testing examples, canonical command and policy digest (pure, unwired)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16

**Status:** Ready for build (slice S1 of AD-1328, #1530). No new AD or BF number: AD-1328 is allocated by the issue title (`scripts/ad_ceiling.py`: ceiling AD-1341, next AD-1342; nothing else claims AD-1328, see Absence Verified A1).
**Base:** `26250c9c` (branch `feat/ad1328-s1-20261016-26250c9c`).
**Dependencies:** none unbuilt. BF-890 (`execution/command_env.py`, `ExecutionConfig.command_env_passthrough`) and BF-892/893 are on the base; S1 reads none of them.
**Estimated tests:** about 60 test functions (about 230 cases with parametrization) in three new files; no existing test changes.

One-line summary: a pure module, `probos.execution.command_policy`, reads one shell command line the way `sh`, `cmd.exe` or PowerShell will, splits it into simple commands, and judges each against ordered token-prefix rules declared as Pydantic models in `config_models/operations.py` (strictest of `allow` < `escalate` < `forbid` wins, every matched rule listed, unreadable input takes a configured decision that can never be `allow`); every rule's `match`/`not_match` examples are judged by the same evaluator, and a `CommandPolicy` cannot be built from a policy whose examples fail; it also gives the canonical command used for approval reuse and a versioned policy digest. Nothing under `src/` constructs it and no config field carries it.

---

## Problem

`run_command` is governed only as a whole tool. `RunCommandTool.invoke` (`src/probos/cognitive/swe_harness/tools.py:1134`) passes any string to `asyncio.create_subprocess_shell` (`:1151`); `ShellCommandAgent._run_command` (`src/probos/agents/shell_command.py:161`) runs it under `powershell -NoProfile -Command` on Windows (`:250`) and `shell=True` elsewhere (`:259-261`). The `run_command` intent is consensus-gated as a unit (`:55`), and AD-1316's broker classifies the call only as a `shell` effect (`src/probos/execution/effect_broker.py:338-339`). Nothing distinguishes `git status` from `git push --force`, or `pytest -q` from `curl ... | sh`.

#1530 decides a per-command policy (Codex `execpolicy` prior art). Its core -- rules, tokenizer, evaluator, self-test, canonical command, digest -- has no dependency on the two call sites, the approval inbox or the records, and is the part most worth reviewing alone: a tokenizer that reads a command differently from the shell is a bypass. S1 is that core, unwired.

## Solution

1. **Models** (`CommandPolicyRule`, `CommandPolicyConfig`, `CommandDecisionName`, `COMMAND_DECISION_RANK`, `windows_program_stem`) in `config_models/operations.py`, beside `ExecutionConfig`, with every structural check at parse time. Not attached to `ExecutionConfig`, not re-exported (D2).
2. **Engine** `src/probos/execution/command_policy.py`: `parse_command` (three single-pass lexers and one segmenter), `evaluate_command` (one internal evaluator, `_evaluate`), `self_test`, `CommandPolicy` (self-tests on construction), `canonical_command`, `policy_digest`, `default_dialect`. Pure: no process, no environment read, no file.
3. Tests in three milestones; a scan pins "nothing under `src/` constructs it".

### Slicing of AD-1328 (decided 2026-10-16; restated)

Two slices, batched into one PR that closes #1530. **S1 (this):** the policy core, unwired. **S2:** wiring before broker admission in `RunCommandTool.invoke` and `ShellCommandAgent._run_command`; `ExecutionConfig.command_policy` and its re-export; escalation through the AD-1154 approval inbox and `ActionApprovalStore` (`src/probos/tools/action_approvals.py:111`); the AD-1224 and AD-1316 records; `probos doctor` (`src/probos/__main__.py:3106`); the opt-in starter policy; the golden byte-identical test; approval reuse in the seam. S1 leaves S2 the obligations O-S1-1..O-S1-10 below.

### Decisions (S1)

- **D1 -- S1 content and boundary.** S1 ships the rule models with parse-time validation, the tokenizer, the evaluator, the self-test, `CommandPolicy`, the canonical-command function and the policy digest, all pure and deterministic. It ships no call site, no config field, no re-export, no approval, no record, no `doctor` output and no starter policy (S2).
- **D2 -- Placement and config surface.** The models live in `src/probos/config_models/operations.py`, inserted before `class ExecutionConfig` (`:27`), because S2 attaches them as `ExecutionConfig.command_policy` and that module may import nothing from `probos` (pinned: `tests/test_ad1270e2e_operations_models.py:572-582`). They cannot live in `probos.execution` for the same reason, and a sibling `config_models` module would need an import that test forbids. The engine lives in `src/probos/execution/command_policy.py` and imports the models from `probos.config_models.operations` (precedent: `src/probos/cognitive/dreaming.py`, `src/probos/fault_issue_filings.py`). **S1 adds no field to `SystemConfig` and no name to `probos.config` or `config_models.__all__`**, so the three config checks see nothing: `check_config_facade.py` reads only `vars(probos.config)` (`scripts/check_config_facade.py:1020`); `check_config_profiles.py` and `gen_config_reference.py` walk from `SystemConfig` (`scripts/check_config_profiles.py:149`, `scripts/gen_config_reference.py:181`). Every check a new model or field touches either way is in Hidden Pins; S2's share is O-S1-1. The models declare no boolean field, so S2's attachment adds no default-`False` flag to classify (`check_config_profiles.py` gate 3).
- **D3 -- Tokenizer.** Three lexers, chosen by an explicit `dialect` argument whose default is `default_dialect()` (`cmd` on `win32`, else `posix`, the shell `create_subprocess_shell` starts); every dialect runs on any machine. Each lexer is one left-to-right pass; each `find` it does either consumes what it scans or raises, so the work is linear in the text; the only regular expressions are fullmatches of short anchored classes (`[A-Za-z0-9_]`, a duration, a nice level, a `stdbuf` option) with no nested quantifier. Bounds (from `CommandPolicyConfig`): `max_command_chars` 8192 (64..65536), `max_segments` 32 (1..256), `max_nesting` 3 (0..8, substitutions and shell wrappers share it). Over a bound is unparseable and names the bound.
  - *Compound boundaries:* `;`, `&&`, `||`, `|`, newline in all three; `|&` and `&` (background) in POSIX; `&` (sequence) in `cmd`; PowerShell's `&` is the call operator at the start of a command and unparseable elsewhere. `&&`, `||`, `|` or `|&` with nothing after is unparseable; a newline after one continues. `$( )` and backticks (POSIX) contribute their own segments, and the word holding them is *dynamic*.
  - *Quoting:* POSIX `'...'` literal, `"..."` with `\` escaping `$ \` " \` and newline, `\` outside quotes escaping one character; `cmd` `"..."` literal except `%NAME%`, `^` escaping one character outside quotes; PowerShell `'...'` literal with `''`, `"..."` with backtick escapes and `""`, backtick escaping outside quotes. A line continuation (escape + newline) is removed.
  - *Dynamic words* (a value the shell computes): POSIX `$NAME`, `${...}`, special parameters, substitutions, unquoted `* ? [ { }` and a leading `~`; `cmd` `%NAME%`; PowerShell `$name`, `${...}`, `$?`, `$^`, `$$`, and `@name` splatting.
  - *Unparseable (whole line):* an unbalanced quote, `$(`, `${` or backtick; a here-document, a POSIX here-string (`<<<`); arithmetic `$((`; `$'...'`/`$"..."`; a subshell or grouping `( )`; process substitution; `case` syntax (`;;`, `;&`); a trailing escape; a control character, a lone CR or a Unicode line break (U+0085, U+2028, U+2029); an empty command between separators; `cmd` parentheses; PowerShell `$( )`, `@( @{ @' @"`, `( ) { }`, `<`, `<#`, `--%`, smart quotes, U+2013..U+2015 dashes, an unquoted comma, non-ASCII whitespace, a background `&`; and no command at all.
  - *Unparseable (one segment):* a dynamic or empty program; a program that runs a command the policy cannot see (`eval`, `exec`, `source`, `.`, `env`, `sudo`, `xargs`, `watch`, shell keywords; `cmd`'s `call`, `start`, `for`, `if`; PowerShell's `iex`/`Invoke-Expression`, `Start-Process`, `ForEach-Object`, dot-sourcing, keywords); a `cmd` program word with `@`, `;`, `,` or `=`; a process wrapper in a form not read; **any shell program (`sh`, `bash`, `dash`, `zsh`, `ksh`, `ash`, `pwsh`, `powershell`, `cmd`) not in an unwrappable form** -- so `curl x | sh` and `bash script.sh` are unreadable, not unmatched; a shell wrapper whose script is unparseable.
  - *Kept out of the match tokens:* leading POSIX assignments, redirections with their targets, and the stripped process wrappers (`time`, `nohup`, `noglob`, `builtin`, `command` but not `command -v`, `nice` / `nice -n N`, `timeout DURATION`, `stdbuf -oL`-style options; at most four).
  - *Shell wrappers unwrapped* (evaluation replaces the segment by the script's segments; nesting counts): `sh|bash|dash|zsh|ksh|ash -c|-lc|-cl SCRIPT` with exactly that one script word; `pwsh|powershell [-NoProfile|-NoLogo|-NonInteractive]... -Command|-c SCRIPT...`; `cmd /c SCRIPT...`. No argument of a shell may be dynamic.
  - *Default for unparseable input:* `unparseable_decision`, default **`escalate`** (Design Principle 13(c): escalate, not refuse). Confirmed, with two parse-time rules: when rules exist it may not be `allow` (an unreadable line could hide any forbidden one), and it may not be looser than `unmatched_decision`.
- **D4 -- Rules and evaluation.** `pattern[0]` is a bare program name (alternatives allowed); later positions are exact words (alternatives allowed); a rule matches a segment that starts with its pattern. Program names compare by basename, and in `cmd` and PowerShell case-insensitively without `.exe/.com/.bat/.cmd`. **Restrictive rules (`escalate`, `forbid`) see through:** a path (`/usr/bin/curl` is `curl`), leading assignments, a dynamic word (it may be anything, so it matches every pattern word). **Permissive rules need proof:** an unpinned `allow` matches only a bare program name, never a path, never past assignments, never a dynamic word inside its prefix. **Pinning** (`host_executable`, `allow` rules only, one program, every path's stem equal to it): the program's path -- as written when it has a separator, else the injected `resolve_program(name)` -- must normalise (`posixpath.normpath`, or `ntpath.normcase(ntpath.normpath())` in the Windows dialects) to a pinned path; otherwise the match becomes `forbid` with `pin_violation=True`, a justification naming the path found (or "a program that does not resolve") and the alternative "run the pinned executable". With no resolver a bare name cannot be proven and is refused. A segment's decision is the strictest of its matches, else `unmatched_decision`, else (unreadable) `unparseable_decision`; the command's decision is the strictest of its segments. With rules configured, `unmatched_decision` must be declared (`allow` for a deny-list, `escalate` for an allow-list); there is no implicit default. **With no rules, `evaluate` returns `status="no_policy"`, `decision=None`, and parses nothing** -- the result S2's golden test relies on. The result lists every `RuleMatch` (rule, effective decision, justification, alternative, matched prefix, segment index, resolved program, pin violation), per-segment verdicts with their basis, the dialect and the digest; `governing` gives the matches that carry the final decision.
- **D5 -- Self-test.** Structure is validated at parse time by Pydantic (every message names the rule). Examples are judged by `self_test(config, *, dialect)`, which calls the runtime evaluator `_evaluate` -- the function `CommandPolicy.evaluate` and `evaluate_command` call -- without a resolver, so a pinned rule's examples name absolute paths and the result does not depend on the host. A `match` example passes when the rule matches it really (not as a pin violation); a `not_match` example passes when it does not. `CommandPolicy(config, dialect=...)` runs it and raises `CommandPolicySelfTestError` (a `ValueError`) whose text names the dialect, then each failing rule and example (first five, then a count). Why not a Pydantic validator: the evaluator cannot live in `config_models`, which may not import `probos` (D2). S2 builds the policy at startup, so a wrong example is a startup error naming the rule (O-S1-2).
- **D6 -- Canonical command and digest.** `canonical_command` unwraps one shell wrapper at a time (up to `max_nesting`). One simple segment with only literal words, no assignments, redirections or process wrappers gives `CanonicalCommand("argv", None, (program, *args))`, where the program is its normalised resolved path when the resolver knows it (so `git` and `/usr/bin/git` share a key), else its normalised name; the dialect is not part of an argv key. Anything else gives `("script", dialect, (exact text,))`, the text of the innermost script that could be unwrapped (the wrapper itself is dropped, so `/bin/bash -lc S` and `bash -c S` share a key; Codex keeps the `-lc`/`-c` mode, ProbOS drops it because both run `S` and the rest of the key is exact text). `key` is `sha256(b"probos.command_policy/canonical_command/v1\x00" + RFC 8785 JSON of [kind, dialect, parts])`. `policy_digest(config)` is `sha256(b"probos.command_policy/policy/v1\x00" + RFC 8785 JSON of config.model_dump(mode="json"))`, examples included: any change to the policy is a new digest. The canonicaliser is `probos.federation.ard.jcs.canonicalize`, imported lazily (precedent `src/probos/cognitive/elastic_team.py:56-65`).
- **D7 -- Tests, mutation, milestones.** M1 models and digest, M2 tokenizer and canonical command, M3 evaluator, self-test, `CommandPolicy` and the unwired scan. The mutation campaign of record runs once on the committed tree (table below).

### Obligations carried to S2

- **O-S1-1** Attach `command_policy: CommandPolicyConfig = Field(default_factory=CommandPolicyConfig)` to `ExecutionConfig`; re-export the models from `probos.config` and `config_models/__init__.py`; amend the `operations.py` docstring ("references no other config model"); regenerate `docs/development/config-facade-baseline.yaml`, the config reference and (if S2 adds a boolean) the profiles manifest; update `tests/test_ad1270e2e_operations_models.py` `EXPECTED_DUMPS["ExecutionConfig"]` (`:133`) and M1 #13 of this slice deliberately.
- **O-S1-2** Exactly one `CommandPolicy` per runtime, built at startup (a self-test failure stops startup); `probos doctor` reports `self_test(...)`, the rule count and the digest without raising.
- **O-S1-3** Dialect per path: `RunCommandTool` uses `default_dialect()`; `ShellCommandAgent` uses `"powershell"` on `win32` (`shell_command.py:250`), else `"posix"`. Evaluate the command **as it will run**, after `_strip_ps_wrapper` (`:171`, `:200`) and `_rewrite_python_interpreter` (`:173`, `:217`).
- **O-S1-4** Evaluate before broker admission; `status == "no_policy"` takes today's code path unchanged (golden byte-identical test).
- **O-S1-5** The resolver is a PATH lookup on the child's environment (`build_command_env(...)`, `tools.py:1157`) and working directory, and the same resolver feeds `evaluate` and `canonical`.
- **O-S1-6** `escalate` reaches the AD-1154 approval surface carrying `governing` rule names and justifications, and an approved command runs exactly once (BF-830); `forbid` returns the justification and the alternative; neither is a silent refusal.
- **O-S1-7** Record the decision, rule names, digest and canonical key on the AD-1224 lifecycle record and, when enabled, the AD-1316 effect record.
- **O-S1-8** Approval reuse keyed on `CanonicalCommand.key` plus the policy digest, the agent, the scope (work item or DM turn) and the approver's authority; it never upgrades `forbid` and records each reuse with the original approval's reference.
- **O-S1-9** Change M3 #16 (the unwired scan) deliberately to spare exactly the S2 wiring modules.
- **O-S1-10** The opt-in starter policy's examples pass under every dialect it targets (`self_test` per dialect in a test).

---

### Section 1 -- `src/probos/config_models/operations.py`

Two edits. Install with CRLF-preserving search and replace; each SEARCH occurs exactly once (`:8-12`, `:24-27`).

```
<<<<<<< SEARCH
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator
=======
from __future__ import annotations

import ntpath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
_ENV_NAME_SHAPE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"


class ExecutionConfig(BaseModel):
=======
_ENV_NAME_SHAPE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"

# AD-1328 S1 (#1530): the command execution policy's models. They sit beside
# ExecutionConfig because S2 attaches them as ExecutionConfig.command_policy and
# this module may not import probos. S1 neither attaches nor re-exports them: their
# only reader is probos.execution.command_policy, which no file under src/ imports
# yet (tests/test_ad1328_s1_policy_evaluation.py pins that).
CommandDecisionName = Literal["allow", "escalate", "forbid"]
#: Strictness: forbid > escalate > allow. The strictest decision wins.
COMMAND_DECISION_RANK: dict[str, int] = {"allow": 0, "escalate": 1, "forbid": 2}
_COMMAND_RULE_NAME_PATTERN = r"[a-z0-9][a-z0-9_.-]{0,63}"
_WINDOWS_PROGRAM_SUFFIXES = (".exe", ".com", ".bat", ".cmd")
_MAX_COMMAND_RULES = 256
_MAX_PATTERN_POSITIONS = 32
_MAX_TOKEN_ALTERNATIVES = 32
_MAX_TOKEN_CHARS = 256
_MAX_RULE_PROSE_CHARS = 500
_MAX_RULE_EXAMPLES = 32
_MAX_EXAMPLE_CHARS = 1024
_MAX_PINNED_PATHS = 16
_MAX_PINNED_PATH_CHARS = 1024


def windows_program_stem(program: str) -> str:
    """A program's name as Windows finds it: the basename, lower-cased, without
    ``.exe``, ``.com``, ``.bat`` or ``.cmd``. ``ntpath`` splits on both separators,
    so a POSIX path gives its basename too."""
    base = ntpath.basename(program).lower()
    for suffix in _WINDOWS_PROGRAM_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base


def _has_control_character(value: str, allowed: str = "") -> bool:
    return any((ord(char) < 32 and char not in allowed) or ord(char) == 127 for char in value)


def _check_policy_text(value: str, what: str, limit: int, *, newlines: bool = False) -> None:
    if not value.strip():
        raise ValueError(f"{what} must not be blank")
    if len(value) > limit:
        raise ValueError(f"{what} is longer than {limit} characters")
    if _has_control_character(value, "\t\n" if newlines else ""):
        raise ValueError(f"{what} contains a control character")


def _check_pattern(pattern: tuple[str | tuple[str, ...], ...], where: str) -> None:
    if not 1 <= len(pattern) <= _MAX_PATTERN_POSITIONS:
        raise ValueError(f"{where}: pattern must have 1 to {_MAX_PATTERN_POSITIONS} positions")
    for position, entry in enumerate(pattern):
        options = (entry,) if isinstance(entry, str) else entry
        if not 1 <= len(options) <= _MAX_TOKEN_ALTERNATIVES or len(set(options)) != len(options):
            raise ValueError(
                f"{where}: pattern position {position} must list 1 to "
                f"{_MAX_TOKEN_ALTERNATIVES} distinct words"
            )
        for token in options:
            if not token or len(token) > _MAX_TOKEN_CHARS or _has_control_character(token):
                raise ValueError(
                    f"{where}: pattern position {position} has an empty, over-long or "
                    "control-character word"
                )
            if position == 0 and any(char in token for char in "/\\ \t"):
                raise ValueError(
                    f"{where}: the program {token!r} must be a bare name; pin paths "
                    "with host_executable"
                )


def _check_pins(rule: CommandPolicyRule, where: str) -> None:
    pins = rule.host_executable
    if not pins:
        return
    if rule.decision != "allow":
        raise ValueError(
            f"{where}: host_executable pins an allow rule only; a {rule.decision} rule "
            "matches its program at every path"
        )
    program = rule.pattern[0]
    if not isinstance(program, str):
        raise ValueError(f"{where}: a pinned rule names one program, not alternatives")
    if len(pins) > _MAX_PINNED_PATHS or len(set(pins)) != len(pins):
        raise ValueError(f"{where}: host_executable must list at most {_MAX_PINNED_PATHS} distinct paths")
    for pin in pins:
        absolute = pin.startswith(("/", "\\\\")) or re.match(r"[A-Za-z]:[\\/]", pin) is not None
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
            raise ValueError(f"{where}: host_executable path {pin!r} is not an absolute path")
        if windows_program_stem(pin) != windows_program_stem(program):
            raise ValueError(f"{where}: host_executable path {pin!r} does not name the program {program!r}")


def _check_examples(rule: CommandPolicyRule, where: str) -> None:
    for kind, examples in (("match", rule.match), ("not_match", rule.not_match)):
        if len(examples) > _MAX_RULE_EXAMPLES:
            raise ValueError(f"{where}: at most {_MAX_RULE_EXAMPLES} {kind} examples")
        for example in examples:
            _check_policy_text(example, f"{where}: {kind} example", _MAX_EXAMPLE_CHARS, newlines=True)
    both = sorted(set(rule.match) & set(rule.not_match))
    if both:
        raise ValueError(f"{where}: {both[0]!r} is both a match and a not_match example")


class CommandPolicyRule(BaseModel):
    """One ordered token-prefix rule of the command execution policy (AD-1328, #1530).

    ``pattern`` is matched against a simple command's words from the first.
    Position 0 is the program: a bare name, compared by basename (in the Windows
    dialects case-insensitively and without its extension). Every later position is
    an exact word. A tuple at any position lists alternatives. A rule matches a
    command that starts with its pattern; later words are unconstrained.

    ``decision`` is ``allow``, ``escalate`` or ``forbid``; the strictest decision of
    every matching rule wins. ``justification`` says why; a ``forbid`` rule names the
    ``alternative`` to use instead (often the governed path), an ``escalate`` rule may.

    ``host_executable`` pins an ``allow`` rule to absolute program paths: the rule
    allows its program only at one of them, and the same name anywhere else is
    refused. ``match`` and ``not_match`` are commands the rule must and must not
    match; ``probos.execution.command_policy.self_test`` judges them with the
    evaluator itself, and a failure is a startup error naming the rule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    pattern: tuple[str | tuple[str, ...], ...]
    decision: CommandDecisionName
    justification: str
    alternative: str | None = None
    host_executable: tuple[str, ...] = ()
    match: tuple[str, ...] = ()
    not_match: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _name_is_a_slug(cls, v: str) -> str:
        if re.fullmatch(_COMMAND_RULE_NAME_PATTERN, v) is None:
            raise ValueError(
                f"command policy rule name {v!r} must be 1 to 64 lower-case letters, "
                "digits, '_', '.' or '-', starting with a letter or digit"
            )
        return v

    @model_validator(mode="after")
    def _rule_is_well_formed(self) -> CommandPolicyRule:
        where = f"command policy rule {self.name!r}"
        _check_pattern(self.pattern, where)
        _check_policy_text(self.justification, f"{where}: justification", _MAX_RULE_PROSE_CHARS)
        if self.decision == "forbid" and self.alternative is None:
            raise ValueError(f"{where}: a forbid rule must name its alternative")
        if self.decision == "allow" and self.alternative is not None:
            raise ValueError(f"{where}: an allow rule has no alternative")
        if self.alternative is not None:
            _check_policy_text(self.alternative, f"{where}: alternative", _MAX_RULE_PROSE_CHARS)
        _check_pins(self, where)
        _check_examples(self, where)
        return self


class CommandPolicyConfig(BaseModel):
    """The command execution policy for ``run_command`` (AD-1328, #1530).

    With no ``rules`` there is no policy: every command runs exactly as it does
    without one. With rules, a command is split into simple commands (segments);
    each segment takes the strictest decision of the rules that match it, or
    ``unmatched_decision`` when none does, or ``unparseable_decision`` when the
    policy cannot read it, and the command takes the strictest decision of its
    segments. The policy only adds gates: it never bypasses consensus or the
    permission ladder. The ``max_*`` fields bound the work of one evaluation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: tuple[CommandPolicyRule, ...] = ()
    unmatched_decision: CommandDecisionName | None = None
    unparseable_decision: CommandDecisionName = "escalate"
    max_command_chars: int = Field(default=8192, ge=64, le=65536)
    max_segments: int = Field(default=32, ge=1, le=256)
    max_nesting: int = Field(default=3, ge=0, le=8)

    @model_validator(mode="after")
    def _decisions_open_no_bypass(self) -> CommandPolicyConfig:
        if len(self.rules) > _MAX_COMMAND_RULES:
            raise ValueError(f"command policy: at most {_MAX_COMMAND_RULES} rules")
        seen: set[str] = set()
        for rule in self.rules:
            if rule.name in seen:
                raise ValueError(f"command policy: rule name {rule.name!r} is declared twice")
            seen.add(rule.name)
        if not self.rules:
            return self
        if self.unmatched_decision is None:
            raise ValueError(
                "command policy: rules are configured, so declare unmatched_decision "
                "(allow for a deny-list, escalate for an allow-list)"
            )
        if self.unparseable_decision == "allow":
            raise ValueError(
                "command policy: unparseable_decision may not be allow; a command the "
                "policy cannot read could hide any forbidden one"
            )
        if COMMAND_DECISION_RANK[self.unparseable_decision] < COMMAND_DECISION_RANK[self.unmatched_decision]:
            raise ValueError("command policy: unparseable_decision must be at least as strict as unmatched_decision")
        return self


class ExecutionConfig(BaseModel):
>>>>>>> REPLACE
```

### Section 2 -- NEW `src/probos/execution/command_policy.py`

```python
"""AD-1328 S1 (#1530): the command execution policy core -- pure, deterministic, unwired.

``run_command`` is governed only as a whole tool today. This module reads one
shell command line the way the shell will, splits it into simple commands
(segments), and decides each against the operator's ordered token-prefix rules
(``probos.config_models.operations.CommandPolicyConfig``):

* ``parse_command`` -- a bounded, single-pass tokenizer for three dialects:
  ``posix`` (``/bin/sh``: ``create_subprocess_shell`` and ``shell=True`` off
  Windows), ``cmd`` (``cmd.exe /c``: ``create_subprocess_shell`` on Windows) and
  ``powershell`` (``ShellCommandAgent`` on Windows, and ``pwsh -Command``
  scripts). The dialect is an explicit argument whose default comes from the
  platform, so every dialect can be exercised on any machine.
* ``evaluate_command`` -- the strictest decision over every segment, with every
  matched rule listed. With no rules it returns ``no_policy`` and parses nothing.
* ``self_test`` -- every rule's ``match`` / ``not_match`` examples, judged by the
  same evaluator. A ``CommandPolicy`` cannot be built from a policy that fails it.
* ``canonical_command`` and ``policy_digest`` -- the approval-reuse key and the
  versioned digest of the policy an approval was granted under.

What the policy sees. Restrictive rules (``escalate``, ``forbid``) see through what
can hide a program: a path (``/usr/bin/curl`` is ``curl``), leading assignments,
the stripped process wrappers, unwrapped shell wrappers, command substitution, and
a word the shell expands (it may be anything, so it matches every pattern word).
Permissive rules need proof: an ``allow`` rule matches a bare program name, or a
program resolved to one of its pinned paths, and never a segment with leading
assignments or an expanded word inside its prefix. What the tokenizer cannot
bound -- an unbalanced quote, a here-document, ``eval`` and other launchers, a
shell reading a script it was not given inline, grouping, a command over the
limits -- is unparseable and takes ``unparseable_decision``, never ``allow``.

A prefix rule still does not see a program started through another program's
arguments (``find -exec``, ``python -c``) or options placed before a subcommand
(``git -C . push``): that is the boundary of a prefix-rule language (#1530, Do
Not Build). Nothing here launches a process, reads the environment or touches a
file, and nothing under ``src/`` constructs this policy yet: AD-1328 S2 wires it
before broker admission in ``RunCommandTool`` and ``ShellCommandAgent``.
"""

from __future__ import annotations

import hashlib
import ntpath
import posixpath
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from probos.config_models.operations import (
    COMMAND_DECISION_RANK,
    CommandDecisionName,
    CommandPolicyConfig,
    CommandPolicyRule,
    windows_program_stem,
)

Dialect = Literal["posix", "cmd", "powershell"]
DIALECTS: Final[tuple[Dialect, ...]] = ("posix", "cmd", "powershell")
#: Maps a bare program name to the absolute path the shell would run, or None.
ProgramResolver = Callable[[str], str | None]

POLICY_DIGEST_SCHEME: Final = "probos.command_policy/policy/v1"
CANONICAL_KEY_SCHEME: Final = "probos.command_policy/canonical_command/v1"
_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v1\x00"
_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v1\x00"

_DEFAULT_LIMITS: Final = CommandPolicyConfig()
_SEPARATORS: Final = frozenset({";", "&&", "||", "|", "|&", "&", "\n"})
_CONTINUING: Final = frozenset({"&&", "||", "|", "|&"})
_CALL_OPERATOR: Final = "&call"
_IDENT_CHAR: Final = re.compile(r"[A-Za-z0-9_]")
_SPECIAL_PARAMETERS: Final = frozenset("0123456789@*#?$!-")
_POSIX_REDIRECTIONS: Final = ("<<<", "<<-", "&>>", "<<", ">>", ">|", ">&", "<&", "<>", "&>", ">", "<")
_CMD_REDIRECTIONS: Final = (">>", ">&", "<&", ">", "<")
_LINE_BREAKS_REFUSED: Final = frozenset("\u0085\u2028\u2029")
_PS_SMART_QUOTES: Final = frozenset("\u2018\u2019\u201a\u201b\u201c\u201d\u201e")
_PS_REFUSED: Final = _PS_SMART_QUOTES | frozenset("(){},\u2013\u2014\u2015")

_OPAQUE_PROGRAMS: Final[dict[str, frozenset[str]]] = {
    "posix": frozenset({
        "eval", "exec", "source", ".", "env", "sudo", "doas", "su", "runuser", "xargs",
        "watch", "setsid", "ionice", "flock", "chroot", "unshare", "nsenter", "trap", "!",
        "if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case",
        "esac", "select", "function", "coproc", "[[",
    }),
    "cmd": frozenset({"call", "start", "for", "if", "goto", "rem", "runas", "forfiles"}),
    "powershell": frozenset({
        "iex", "invoke-expression", "icm", "invoke-command", "start-process", "saps", "start",
        "start-job", "sajb", "start-threadjob", "foreach-object", "%", "where-object", "?",
        "foreach", "for", "while", "do", "until", "if", "else", "elseif", "switch", "function",
        "filter", "workflow", "try", "trap", ".", "invoke-item", "ii", "invoke-history", "ihy",
        "r", "set-alias", "sal", "new-alias", "nal",
    }),
}
_PROCESS_WRAPPERS: Final = frozenset({"time", "nohup", "noglob", "builtin", "command", "nice", "timeout", "stdbuf"})
_MAX_PROCESS_WRAPPERS: Final = 4
_NICE_LEVEL: Final = re.compile(r"-?[0-9]{1,3}")
_DURATION: Final = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9})?[smhd]?")
_STDBUF_OPTION: Final = re.compile(r"-[ioe](?:L|[0-9]{1,9}[KMG]?)")
_POSIX_SHELLS: Final = frozenset({"sh", "bash", "dash", "zsh", "ksh", "ash"})
_POSIX_SCRIPT_FLAGS: Final = frozenset({"-c", "-lc", "-cl"})
_PS_SHELLS: Final = frozenset({"powershell", "pwsh"})
_PS_QUIET_FLAGS: Final = frozenset({"-noprofile", "-nologo", "-noninteractive"})
_PS_COMMAND_FLAGS: Final = frozenset({"-command", "-c"})
_MAX_REPORTED_FAILURES: Final = 5


class _Unparseable(Exception):
    """Text the policy cannot read with confidence; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _OverBudget(_Unparseable):
    """A bound on the work was reached: the whole command is unparseable."""


@dataclass(frozen=True)
class _Word:
    text: str
    raw: str
    dynamic: bool
    assignment: bool


@dataclass(frozen=True)
class _Op:
    text: str
    redirect: bool


@dataclass(frozen=True)
class CommandSegment:
    """One simple command of a command line, as the policy reads it.

    ``tokens`` are the dequoted words, program first; ``dynamic[i]`` is True where
    the shell would expand word ``i`` (a variable, a substitution, a glob), so its
    value is unknown here; ``raw`` is each word as written. Leading ``NAME=value``
    ``assignments`` (POSIX), ``redirections`` (operator and target) and the stripped
    process ``wrappers`` are kept out of ``tokens``. ``depth`` counts the
    substitutions and shell wrappers around the segment. ``unparseable`` says why
    the policy cannot read this segment, or is None.
    """

    dialect: Dialect
    tokens: tuple[str, ...]
    dynamic: tuple[bool, ...]
    raw: tuple[str, ...]
    assignments: tuple[str, ...]
    redirections: tuple[str, ...]
    wrappers: tuple[str, ...]
    depth: int
    unparseable: str | None


@dataclass(frozen=True)
class ParsedCommand:
    """A command line split into segments. ``unparseable`` is set, and ``segments``
    is empty, when the line as a whole cannot be read."""

    dialect: Dialect
    segments: tuple[CommandSegment, ...]
    unparseable: str | None


@dataclass(frozen=True)
class RuleMatch:
    """One rule matching one segment.

    ``decision`` is the rule's, except that a pinned ``allow`` rule whose program is
    not at a pinned path gives ``forbid`` with ``pin_violation`` set and a
    justification naming the path found. ``matched_prefix`` is the segment's words
    the pattern covered, as they appear in the command.
    """

    rule: str
    decision: CommandDecisionName
    justification: str
    alternative: str | None
    matched_prefix: tuple[str, ...]
    segment: int
    resolved_program: str | None
    pin_violation: bool


@dataclass(frozen=True)
class SegmentVerdict:
    """The decision for one segment: by ``rule`` match, ``unmatched`` or ``unparseable``."""

    index: int
    segment: CommandSegment
    decision: CommandDecisionName
    basis: Literal["rule", "unmatched", "unparseable"]
    matches: tuple[RuleMatch, ...]


@dataclass(frozen=True)
class CommandEvaluation:
    """The policy's answer for one command line.

    ``status`` is ``no_policy`` when no rule is configured: nothing was parsed or
    decided, ``decision`` is None, and the caller runs the command exactly as it
    would without a policy. Otherwise ``decision`` is the strictest over
    ``segments``, or ``unparseable_decision`` when the whole line could not be read
    (``unparseable`` says why, and ``segments`` is empty).
    """

    status: Literal["no_policy", "evaluated"]
    decision: CommandDecisionName | None
    dialect: Dialect
    policy_digest: str | None
    segments: tuple[SegmentVerdict, ...]
    unparseable: str | None

    @property
    def matched_rules(self) -> tuple[RuleMatch, ...]:
        """Every rule match: segment by segment, and in rule order within a segment."""
        return tuple(match for verdict in self.segments for match in verdict.matches)

    @property
    def governing(self) -> tuple[RuleMatch, ...]:
        """The matches that carry the final decision; their justifications and
        alternatives are what the agent is told."""
        return tuple(match for match in self.matched_rules if match.decision == self.decision)


@dataclass(frozen=True)
class SelfTestFailure:
    """One example that does not hold for its rule."""

    rule: str
    expectation: Literal["match", "not_match"]
    example: str
    observed: str

    @property
    def message(self) -> str:
        return f"rule {self.rule!r}: {self.expectation} example {self.example!r} {self.observed}"


@dataclass(frozen=True)
class SelfTestReport:
    """Every rule's examples judged under one dialect."""

    dialect: Dialect
    examples_checked: int
    failures: tuple[SelfTestFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


class CommandPolicySelfTestError(ValueError):
    """A policy whose examples do not hold under its dialect; at startup, a startup error."""

    def __init__(self, report: SelfTestReport) -> None:
        shown = "; ".join(failure.message for failure in report.failures[:_MAX_REPORTED_FAILURES])
        extra = len(report.failures) - _MAX_REPORTED_FAILURES
        more = f" (and {extra} more)" if extra > 0 else ""
        super().__init__(f"command policy self-test failed under the {report.dialect} dialect: {shown}{more}")
        self.report = report


@dataclass(frozen=True)
class CanonicalCommand:
    """The approval-reuse identity of a command (#1530 amendment).

    ``argv``: one simple command of literal words, after unwrapping shell wrappers --
    the program as its normalised resolved path when the resolver knows it (so
    ``git`` and ``/usr/bin/git`` share a key), else its normalised name, then the
    arguments; the dialect is not part of it. ``script``: anything else -- the exact
    text of the innermost script that could be unwrapped, tagged with its dialect.
    """

    kind: Literal["argv", "script"]
    dialect: Dialect | None
    parts: tuple[str, ...]

    @property
    def key(self) -> str:
        """``CANONICAL_KEY_SCHEME``: sha256 of a domain tag and the RFC 8785 JSON of
        ``[kind, dialect, parts]``."""
        payload = _canonical_json([self.kind, self.dialect, list(self.parts)])
        return hashlib.sha256(_CANONICAL_DOMAIN + payload).hexdigest()


# --------------------------------------------------------------------------------------
# Lexers: one pass over one string each
# --------------------------------------------------------------------------------------


class _Lexer:
    """The word buffer every dialect shares. Subclasses own quoting and operators."""

    def __init__(self, text: str, depth: int, max_nesting: int) -> None:
        self.text = text
        self.i = 0
        self.depth = depth
        self.max_nesting = max_nesting
        self.items: list[_Word | _Op] = []
        self.subs: list[_Lexer] = []
        self._reset()

    def lex(self) -> None:
        raise NotImplementedError

    def _reset(self) -> None:
        self._buf: list[str] = []
        self._start = -1
        self._dynamic = False
        self._quoted = False
        self._ident = True
        self._assignment = False

    def _begin(self) -> None:
        if self._start < 0:
            self._start = self.i

    def _literal(self, chars: str, *, quoted: bool) -> None:
        self._begin()
        if quoted:
            self._quoted = True
        if not self._assignment:
            if not quoted and chars == "=" and self._buf and self._ident:
                self._assignment = True
            elif quoted or _IDENT_CHAR.fullmatch(chars) is None or (not self._buf and chars.isdigit()):
                self._ident = False
        self._buf.append(chars)

    def _mark_dynamic(self) -> None:
        self._begin()
        self._dynamic = True
        if not self._assignment:
            self._ident = False

    def _end_word(self) -> None:
        if self._start >= 0:
            raw = self.text[self._start:self.i]
            self.items.append(_Word("".join(self._buf), raw, self._dynamic, self._assignment))
            self._reset()

    def _op(self, text: str, *, redirect: bool = False) -> None:
        self._end_word()
        self.items.append(_Op(text, redirect))

    def _io_number(self, extra: frozenset[str] = frozenset()) -> str:
        """The descriptor word written directly before a redirection (``2`` in ``2>``),
        consumed; otherwise the current word ends and this returns ``""``."""
        word = "".join(self._buf)
        literal = self._start >= 0 and not self._quoted and not self._dynamic
        if literal and ((word.isascii() and word.isdigit()) or word in extra):
            self._reset()
            return word
        self._end_word()
        return ""

    def _escape(self, marker: str) -> None:
        """``marker`` escapes the next character; before a newline it continues the line."""
        if self.i + 1 >= len(self.text):
            raise _Unparseable(f"a trailing {marker!r}")
        following = self.text[self.i + 1]
        if following != "\n":
            self._literal(following, quoted=True)
        self.i += 2

    def _comment(self) -> None:
        end = self.text.find("\n", self.i)
        self.i = len(self.text) if end < 0 else end

    def _nest(self) -> None:
        if self.depth >= self.max_nesting:
            raise _Unparseable(f"command substitution nested deeper than {self.max_nesting}")


class _PosixLexer(_Lexer):
    """POSIX ``sh``."""

    def lex(self, *, closing: bool = False) -> None:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == "\n":
                self._op("\n")
                self.i += 1
            elif ch == "#" and self._start < 0:
                self._comment()
            elif ch == "\\":
                self._escape("\\")
            elif ch == "'":
                self._single_quoted()
            elif ch == '"':
                self._double_quoted()
            elif ch == "`":
                self._backtick()
            elif ch == "$":
                self._dollar(quoted=False)
            elif ch == ")" and closing:
                self._end_word()
                self.i += 1
                return
            elif ch in "()":
                raise _Unparseable("a subshell or a group")
            elif ch in "<>" or text.startswith("&>", self.i):
                self._redirection()
            elif ch in ";&|":
                self._separator()
            else:
                if ch in "*?[{}" or (ch == "~" and self._start < 0):
                    self._mark_dynamic()
                self._literal(ch, quoted=False)
                self.i += 1
        if closing:
            raise _Unparseable("an unbalanced $(")
        self._end_word()

    def _separator(self) -> None:
        pair = self.text[self.i:self.i + 2]
        if pair in (";;", ";&"):
            raise _Unparseable("case-statement syntax")
        op = pair if pair in ("&&", "||", "|&") else self.text[self.i]
        self._op(op)
        self.i += len(op)

    def _redirection(self) -> None:
        op = next(candidate for candidate in _POSIX_REDIRECTIONS if self.text.startswith(candidate, self.i))
        if op.startswith("<<"):
            raise _Unparseable("a here-string" if op == "<<<" else "a here-document")
        if op in ("<", ">") and self.text.startswith("(", self.i + 1):
            raise _Unparseable("process substitution")
        descriptor = self._io_number() if not op.startswith("&") else ""
        self._op(descriptor + op, redirect=True)
        self.i += len(op)

    def _single_quoted(self) -> None:
        end = self.text.find("'", self.i + 1)
        if end < 0:
            raise _Unparseable("an unbalanced single quote")
        self._literal(self.text[self.i + 1:end], quoted=True)
        self.i = end + 1

    def _double_quoted(self) -> None:
        text = self.text
        self._literal("", quoted=True)
        self.i += 1
        while self.i < len(text):
            ch = text[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch == "\\" and text[self.i + 1:self.i + 2] in ("$", "`", '"', "\\", "\n"):
                if text[self.i + 1] != "\n":
                    self._literal(text[self.i + 1], quoted=True)
                self.i += 2
            elif ch == "`":
                self._backtick()
            elif ch == "$":
                self._dollar(quoted=True)
            else:
                self._literal(ch, quoted=True)
                self.i += 1
        raise _Unparseable("an unbalanced double quote")

    def _dollar(self, *, quoted: bool) -> None:
        text, i = self.text, self.i
        following = text[i + 1:i + 2]
        if text.startswith("$((", i):
            raise _Unparseable("arithmetic expansion")
        if following == "(":
            self._substitution()
        elif following == "{":
            end = text.find("}", i + 2)
            if end < 0 or any(char in text[i + 2:end] for char in "$`'\"{("):
                raise _Unparseable("a parameter expansion the policy cannot bound")
            self._mark_dynamic()
            self.i = end + 1
        elif following in ("'", '"') and following and not quoted:
            raise _Unparseable("$'...' or $\"...\" quoting")
        elif following and (following in _SPECIAL_PARAMETERS or (following.isascii() and (following.isalpha() or following == "_"))):
            end = i + 2
            if following not in _SPECIAL_PARAMETERS:
                while end < len(text) and _IDENT_CHAR.fullmatch(text[end]) is not None:
                    end += 1
            self._mark_dynamic()
            self.i = end
        else:
            self._literal("$", quoted=quoted)
            self.i += 1

    def _substitution(self) -> None:
        self._nest()
        self._mark_dynamic()
        inner = _PosixLexer(self.text, self.depth + 1, self.max_nesting)
        inner.i = self.i + 2
        inner.lex(closing=True)
        self.subs.append(inner)  # its segments are judged too
        self.i = inner.i

    def _backtick(self) -> None:
        end = self.text.find("`", self.i + 1)
        if end < 0:
            raise _Unparseable("an unbalanced backtick")
        body = self.text[self.i + 1:end]
        if "\\" in body:
            raise _Unparseable("an escape inside backticks")
        self._nest()
        self._mark_dynamic()
        inner = _PosixLexer(body, self.depth + 1, self.max_nesting)
        inner.lex()
        self.subs.append(inner)  # judged like $( )
        self.i = end + 1


class _CmdLexer(_Lexer):
    """``cmd.exe /c``."""

    def lex(self) -> None:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == "\n":
                self._op("\n")
                self.i += 1
            elif ch == "^":
                self._escape("^")
            elif ch == '"':
                self._quoted_run()
            elif ch == "%":
                self.i = self._percent(self.i, len(text), quoted=False)
            elif ch in "()":  # cmd grouping
                raise _Unparseable("a parenthesised block")
            elif ch in "<>":
                descriptor = self._io_number()
                op = next(candidate for candidate in _CMD_REDIRECTIONS if text.startswith(candidate, self.i))
                self._op(descriptor + op, redirect=True)
                self.i += len(op)
            elif ch in "&|":
                pair = text[self.i:self.i + 2]
                op = pair if pair in ("&&", "||") else ch
                self._op(op)
                self.i += len(op)
            else:
                self._literal(ch, quoted=False)
                self.i += 1
        self._end_word()

    def _quoted_run(self) -> None:
        end = self.text.find('"', self.i + 1)
        if end < 0:
            raise _Unparseable("an unbalanced double quote")
        self._literal("", quoted=True)
        at = self.i + 1
        while at < end:
            if self.text[at] == "\n":
                raise _Unparseable("a newline inside quotes")
            if self.text[at] == "%":
                at = self._percent(at, end, quoted=True)
            else:
                self._literal(self.text[at], quoted=True)
                at += 1
        self.i = end + 1

    def _percent(self, at: int, limit: int, *, quoted: bool) -> int:
        """``%NAME%`` expands (a dynamic word); any other ``%`` is literal. Returns the next index."""
        end = at + 1
        while end < limit and self.text[end] not in '% \t\n"':
            end += 1
        if end < limit and self.text[end] == "%" and end > at + 1:
            self._mark_dynamic()
            return end + 1
        self._literal("%", quoted=quoted)
        return at + 1


class _PowerShellLexer(_Lexer):
    """PowerShell, as ``powershell -Command`` and ``pwsh -Command`` read a script."""

    def lex(self) -> None:
        text = self.text
        if "--%" in text:
            raise _Unparseable("the stop-parsing token --%")
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == "\n":
                self._op("\n")
                self.i += 1
            elif ch == "#" and self._start < 0:
                self._comment()
            elif ch == "`":
                self._escape("`")
            elif ch == "'":
                self._single_quoted()
            elif ch == '"':
                self._double_quoted()
            elif ch == "$":
                self._variable(quoted=False)
            elif ch == "@" and self._start < 0:
                self._splat()
            elif ch in _PS_REFUSED or ch.isspace():
                raise _Unparseable(f"{ch!r}, which PowerShell reads as syntax")
            elif ch == "<":
                raise _Unparseable("a '<', reserved in PowerShell, or a block comment")
            elif ch == ">":
                descriptor = self._io_number(frozenset({"*"}))
                op = ">>" if text.startswith(">>", self.i) else ">&" if text.startswith(">&", self.i) else ">"
                self._op(descriptor + op, redirect=True)
                self.i += len(op)
            elif ch == "&":
                self._ampersand()
            elif ch in ";|":
                op = "||" if text.startswith("||", self.i) else ch
                self._op(op)
                self.i += len(op)
            else:
                self._literal(ch, quoted=False)
                self.i += 1
        self._end_word()

    def _single_quoted(self) -> None:
        self._literal("", quoted=True)
        at = self.i + 1
        while at < len(self.text):
            ch = self.text[at]
            if ch in _PS_SMART_QUOTES:
                raise _Unparseable("a smart quote inside a quoted string")
            if ch == "'":
                if not self.text.startswith("''", at):
                    self.i = at + 1
                    return
                self._literal("'", quoted=True)
                at += 2
            else:
                self._literal(ch, quoted=True)
                at += 1
        raise _Unparseable("an unbalanced single quote")

    def _double_quoted(self) -> None:
        text = self.text
        self._literal("", quoted=True)
        self.i += 1
        while self.i < len(text):
            ch = text[self.i]
            if ch in _PS_SMART_QUOTES:
                raise _Unparseable("a smart quote inside a quoted string")
            if ch == '"' and not text.startswith('""', self.i):
                self.i += 1
                return
            if ch == '"' or (ch == "`" and self.i + 1 < len(text)):
                self._literal(text[self.i + 1], quoted=True)
                self.i += 2
            elif ch == "$":
                self._variable(quoted=True)
            else:
                self._literal(ch, quoted=True)
                self.i += 1
        raise _Unparseable("an unbalanced double quote")

    def _variable(self, *, quoted: bool) -> None:
        text, i = self.text, self.i
        following = text[i + 1:i + 2]
        if following == "(":
            raise _Unparseable("a subexpression $( )")
        if following == "{":
            end = text.find("}", i + 2)
            if end < 0:
                raise _Unparseable("an unbalanced ${")
            self._mark_dynamic()
            self.i = end + 1
        elif following and following in "?^$":
            self._mark_dynamic()
            self.i = i + 2
        elif following.isascii() and (following.isalpha() or following == "_"):
            end = i + 2
            while end < len(text) and (_IDENT_CHAR.fullmatch(text[end]) is not None or text[end] == ":"):
                end += 1
            self._mark_dynamic()
            self.i = end
        else:
            self._literal("$", quoted=quoted)
            self.i += 1

    def _splat(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if following in ("(", "{", "'", '"') and following:
            raise _Unparseable("an array, hash table or here-string")
        if following.isascii() and (following.isalpha() or following == "_"):
            end = self.i + 2
            while end < len(self.text) and _IDENT_CHAR.fullmatch(self.text[end]) is not None:
                end += 1
            self._mark_dynamic()
            self.i = end
        else:
            self._literal("@", quoted=False)
            self.i += 1

    def _ampersand(self) -> None:
        if self.text.startswith("&&", self.i):
            self._op("&&")
            self.i += 2
            return
        at_command_start = self._start < 0 and (
            not self.items or (isinstance(self.items[-1], _Op) and not self.items[-1].redirect)
        )
        if not at_command_start:
            raise _Unparseable("a background job (&)")
        self._op(_CALL_OPERATOR)
        self.i += 1


_LEXERS: Final[dict[str, type[_Lexer]]] = {
    "posix": _PosixLexer,
    "cmd": _CmdLexer,
    "powershell": _PowerShellLexer,
}


# --------------------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------------------


def default_dialect(platform: str | None = None) -> Dialect:
    """The shell ``create_subprocess_shell`` starts: ``cmd`` on Windows, else ``posix``.

    ``ShellCommandAgent`` runs PowerShell on Windows; its caller passes
    ``"powershell"`` explicitly.
    """
    return "cmd" if (sys.platform if platform is None else platform) == "win32" else "posix"


def _dialect(dialect: object) -> Dialect:
    if dialect is None:
        return default_dialect()
    if type(dialect) is not str or dialect not in DIALECTS:
        raise ValueError("command_policy_dialect_invalid")
    return cast(Dialect, dialect)


def _program_name(program: str, dialect: Dialect) -> str:
    return posixpath.basename(program) if dialect == "posix" else windows_program_stem(program)


def _is_path(program: str, dialect: Dialect) -> bool:
    return "/" in program if dialect == "posix" else any(char in program for char in "/\\:")


def _path_key(path: str, dialect: Dialect) -> str:
    return posixpath.normpath(path) if dialect == "posix" else ntpath.normcase(ntpath.normpath(path))


def _checked_text(text: str) -> str:
    """CRLF becomes LF; any other control character, or a Unicode line break, is unparseable."""
    text = text.replace("\r\n", "\n")
    for char in text:
        if (ord(char) < 32 and char not in "\t\n") or ord(char) == 127 or char in _LINE_BREAKS_REFUSED:
            raise _Unparseable("a control character or an unusual line break")
    return text


def _groups(items: list[_Word | _Op]) -> list[list[_Word | _Op]]:
    """Split lexer items at the compound boundaries."""
    groups: list[list[_Word | _Op]] = []
    current: list[_Word | _Op] = []
    pending: str | None = None  # a separator that needs a command after it
    for item in items:
        if isinstance(item, _Op) and not item.redirect and item.text in _SEPARATORS:
            if current:
                groups.append(current)
                current = []
                pending = item.text if item.text in _CONTINUING else None
            elif item.text != "\n":
                raise _Unparseable(f"an empty command before {item.text!r}")
        else:
            current.append(item)
    if current:
        groups.append(current)
    elif pending is not None:
        raise _Unparseable(f"nothing after {pending!r}")
    return groups


def _segment(group: list[_Word | _Op], dialect: Dialect, depth: int) -> CommandSegment:
    words: list[_Word] = []
    redirections: list[str] = []
    problem: str | None = None
    at = 0
    while at < len(group):
        item = group[at]
        if isinstance(item, _Word):
            words.append(item)
            at += 1
        elif item.text == _CALL_OPERATOR:
            if at:
                problem = "a misplaced call operator"
            at += 1
        else:
            target = group[at + 1] if at + 1 < len(group) else None
            if not isinstance(target, _Word):
                raise _Unparseable(f"the redirection {item.text!r} has no target")
            redirections.append(f"{item.text}{target.raw}")
            at += 2
    assignments: list[str] = []
    if dialect == "posix":
        while words and words[0].assignment:
            assignments.append(words.pop(0).raw)
    wrappers: list[str] = []
    if problem is None:
        problem = _strip_process_wrappers(words, wrappers) if dialect == "posix" else None
    if problem is None:
        problem = _program_problem(words[0], dialect) if words else "no command, only assignments or redirections"
    return CommandSegment(
        dialect=dialect,
        tokens=tuple(word.text for word in words),
        dynamic=tuple(word.dynamic for word in words),
        raw=tuple(word.raw for word in words),
        assignments=tuple(assignments),
        redirections=tuple(redirections),
        wrappers=tuple(wrappers),
        depth=depth,
        unparseable=problem,
    )


def _strip_process_wrappers(words: list[_Word], wrappers: list[str]) -> str | None:
    """Strip POSIX process wrappers that run their argument as the command, in their plain forms."""
    for _ in range(_MAX_PROCESS_WRAPPERS):
        if not words or words[0].dynamic or posixpath.basename(words[0].text) not in _PROCESS_WRAPPERS:
            return None
        take = _wrapper_width(words)
        if take is None:
            return f"{words[0].text!r} with options the policy does not read"
        if take == 0:
            return None  # ``command -v`` looks a program up; it runs nothing
        wrappers.append(" ".join(word.raw for word in words[:take]))
        del words[:take]
        if not words:
            return "a process wrapper with no command"
    if words and not words[0].dynamic and posixpath.basename(words[0].text) in _PROCESS_WRAPPERS:
        return f"more than {_MAX_PROCESS_WRAPPERS} process wrappers"
    return None


def _wrapper_width(words: list[_Word]) -> int | None:
    """Words taken by the wrapper at ``words[0]``: 0 when it runs nothing, None for a form not read."""
    name = posixpath.basename(words[0].text)
    rest = words[1:]
    if rest and rest[0].dynamic:
        return None
    first = rest[0].text if rest else None
    flagged = first is not None and first.startswith("-")
    if name == "command" and flagged:
        return 0
    if name in ("time", "nohup", "noglob", "builtin", "command"):
        return None if flagged else 1
    if name == "nice":
        if first == "-n" and len(rest) > 1 and not rest[1].dynamic and _NICE_LEVEL.fullmatch(rest[1].text):
            return 3
        return None if flagged else 1
    if name == "timeout":
        return 2 if first is not None and _DURATION.fullmatch(first) else None
    width = 1  # stdbuf
    while width < len(words) and not words[width].dynamic and _STDBUF_OPTION.fullmatch(words[width].text):
        width += 1
    return width if width > 1 else None


def _program_problem(word: _Word, dialect: Dialect) -> str | None:
    if word.dynamic:  # the shell decides the program
        return "the program is not a literal word"
    if not word.text:
        return "the program is an empty word"
    if dialect == "cmd" and (word.text.startswith("@") or any(char in word.text for char in ";,=")):
        return "a program word cmd.exe may split or hide"
    if _program_name(word.text, dialect) in _OPAQUE_PROGRAMS[dialect]:
        return f"{word.text!r} runs a command the policy cannot see"
    return None


def _shell_wrapper(segment: CommandSegment) -> tuple[str, Dialect] | str | None:
    """``(script, dialect)`` for a shell wrapper the policy unwraps; a reason for a
    shell invoked any other way (it would run commands the policy cannot see); None
    for an ordinary program."""
    if not segment.tokens:
        return None
    head = segment.tokens[0]
    name = _program_name(head, segment.dialect)
    stem = windows_program_stem(head)
    args = segment.tokens[1:]
    readable = not any(segment.dynamic)
    if name in _POSIX_SHELLS:
        if len(args) == 2 and args[0] in _POSIX_SCRIPT_FLAGS and readable:
            return args[1], "posix"
        return f"{head!r} runs commands the policy cannot see unless they are an inline script it unwraps"
    if stem in _PS_SHELLS:
        flag = 0
        while flag < len(args) and args[flag].lower() in _PS_QUIET_FLAGS:
            flag += 1
        if flag + 1 < len(args) and args[flag].lower() in _PS_COMMAND_FLAGS and readable:
            return _rest_of_line(segment, flag + 2), "powershell"
        return f"{head!r} runs a script the policy cannot see unless it is a -Command script"
    if stem == "cmd":
        if len(args) > 1 and args[0].lower() == "/c" and readable:
            return _rest_of_line(segment, 2), "cmd"
        return f"{head!r} runs commands the policy cannot see unless they follow /c"
    return None


def _rest_of_line(segment: CommandSegment, start: int) -> str:
    """The script a ``-Command`` or ``/c`` wrapper runs: one word dequoted, or the words as written."""
    if len(segment.tokens) == start + 1:
        return segment.tokens[start]
    return " ".join(segment.raw[start:])


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def parse_command(
    command: str,
    *,
    dialect: Dialect | None = None,
    limits: CommandPolicyConfig | None = None,
    unwrap_shells: bool = True,
) -> ParsedCommand:
    """Split ``command`` into segments under ``dialect`` (default: ``default_dialect()``).

    ``limits`` supplies ``max_command_chars``, ``max_segments`` and ``max_nesting``
    (default: ``CommandPolicyConfig()``'s). With ``unwrap_shells`` a shell wrapper
    the policy unwraps (``bash -lc S``, ``sh -c S``, ``cmd /c S``,
    ``pwsh -Command S``) is replaced by the segments of ``S``. Hostile text never
    raises: what cannot be read is reported as ``unparseable``.
    """
    if type(command) is not str:
        raise TypeError("command_policy_command_type_invalid")
    chosen = _dialect(dialect)
    bounds = _DEFAULT_LIMITS if limits is None else limits
    segments: list[CommandSegment] = []
    try:
        if len(command) > bounds.max_command_chars:
            raise _OverBudget(f"the command is longer than {bounds.max_command_chars} characters")
        _parse_into(command, chosen, bounds, 0, unwrap_shells, segments)
        if not segments:
            raise _Unparseable("no command")
    except _Unparseable as exc:
        return ParsedCommand(chosen, (), exc.reason)
    return ParsedCommand(chosen, tuple(segments), None)


def _parse_into(
    text: str, dialect: Dialect, bounds: CommandPolicyConfig, depth: int, unwrap: bool, out: list[CommandSegment],
) -> None:
    lexer = _LEXERS[dialect](_checked_text(text), depth, bounds.max_nesting)
    lexer.lex()
    _emit(lexer, dialect, bounds, unwrap, out)


def _emit(lexer: _Lexer, dialect: Dialect, bounds: CommandPolicyConfig, unwrap: bool, out: list[CommandSegment]) -> None:
    for group in _groups(lexer.items):
        segment = _segment(group, dialect, lexer.depth)
        wrapper = _shell_wrapper(segment) if unwrap and segment.unparseable is None else None
        if isinstance(wrapper, tuple):
            refused = _unwrap(segment, wrapper, bounds, out)
            if refused is not None:
                out.append(refused)
        else:
            out.append(segment if wrapper is None else replace(segment, unparseable=wrapper))
        if len(out) > bounds.max_segments:
            raise _OverBudget(f"more than {bounds.max_segments} segments")
    for inner in lexer.subs:
        _emit(inner, "posix", bounds, unwrap, out)


def _unwrap(
    segment: CommandSegment, wrapper: tuple[str, Dialect], bounds: CommandPolicyConfig, out: list[CommandSegment],
) -> CommandSegment | None:
    """Replace a shell-wrapper segment by its script's segments; None when that worked."""
    script, inner = wrapper
    if segment.depth >= bounds.max_nesting:
        return replace(segment, unparseable=f"shell wrappers nested deeper than {bounds.max_nesting}")
    mark = len(out)
    try:
        _parse_into(script, inner, bounds, segment.depth + 1, True, out)
    except _OverBudget:
        raise
    except _Unparseable as exc:
        del out[mark:]
        return replace(segment, unparseable=f"the wrapped script is unparseable: {exc.reason}")
    if len(out) == mark:
        return replace(segment, unparseable="the wrapped script is empty")
    return None


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------


def _require_config(config: object) -> None:
    if type(config) is not CommandPolicyConfig:
        raise TypeError("command_policy_config_type_invalid")


def _no_policy(dialect: Dialect) -> CommandEvaluation:
    return CommandEvaluation("no_policy", None, dialect, None, (), None)


def _resolve(resolve: ProgramResolver | None, program: str) -> str | None:
    if resolve is None:
        return None
    resolved = resolve(program)
    if resolved is not None and type(resolved) is not str:
        raise TypeError("command_policy_resolver_result_invalid")
    return resolved


def _strictest(decisions: Iterable[CommandDecisionName]) -> CommandDecisionName:
    return max(decisions, key=COMMAND_DECISION_RANK.__getitem__)


def _program_matches(expected: str | tuple[str, ...], program: str, dialect: Dialect) -> bool:
    names = (expected,) if isinstance(expected, str) else expected
    if dialect == "posix":
        return posixpath.basename(program) in names
    stem = windows_program_stem(program)
    return any(windows_program_stem(name) == stem for name in names)


def _match(
    rule: CommandPolicyRule, segment: CommandSegment, index: int, resolve: ProgramResolver | None,
) -> RuleMatch | None:
    restrictive = rule.decision != "allow"
    tokens = segment.tokens
    if len(tokens) < len(rule.pattern) or (segment.assignments and not restrictive):
        return None
    if not _program_matches(rule.pattern[0], tokens[0], segment.dialect):
        return None
    for position in range(1, len(rule.pattern)):
        if segment.dynamic[position]:
            if restrictive:
                continue  # an expanded word may be anything, so it matches a restrictive rule
            return None
        expected = rule.pattern[position]
        if tokens[position] not in ((expected,) if isinstance(expected, str) else expected):
            return None
    prefix = tokens[: len(rule.pattern)]
    if restrictive:
        return RuleMatch(rule.name, rule.decision, rule.justification, rule.alternative, prefix, index, None, False)
    return _allow_match(rule, segment, prefix, index, resolve)


def _allow_match(
    rule: CommandPolicyRule,
    segment: CommandSegment,
    prefix: tuple[str, ...],
    index: int,
    resolve: ProgramResolver | None,
) -> RuleMatch | None:
    program = segment.tokens[0]
    is_path = _is_path(program, segment.dialect)
    if not rule.host_executable:
        if is_path:
            return None  # a path is another binary than the bare name the rule allows, unless pinned
        return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, None, False)
    resolved = program if is_path else _resolve(resolve, program)
    pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable}
    if resolved is not None and _path_key(resolved, segment.dialect) in pinned:
        return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, resolved, False)
    found = repr(resolved) if resolved is not None else "a program that does not resolve"
    paths = ", ".join(rule.host_executable)
    return RuleMatch(
        rule.name,
        "forbid",
        f"rule {rule.name!r} allows {rule.pattern[0]} only at {paths}; {found} is not one of them",
        f"run the pinned executable: {paths}",
        prefix,
        index,
        resolved,
        True,
    )


def _judge(
    config: CommandPolicyConfig,
    segment: CommandSegment,
    index: int,
    unmatched: CommandDecisionName,
    resolve: ProgramResolver | None,
) -> SegmentVerdict:
    if segment.unparseable is not None:
        return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())
    matches = tuple(found for rule in config.rules if (found := _match(rule, segment, index, resolve)) is not None)
    if not matches:
        return SegmentVerdict(index, segment, unmatched, "unmatched", ())
    return SegmentVerdict(index, segment, _strictest(match.decision for match in matches), "rule", matches)


def _evaluate(
    config: CommandPolicyConfig,
    command: str,
    dialect: Dialect,
    resolve: ProgramResolver | None,
    digest: str,
) -> CommandEvaluation:
    """The one evaluator: ``evaluate_command``, ``CommandPolicy.evaluate`` and ``self_test`` all call it."""
    parsed = parse_command(command, dialect=dialect, limits=config)
    if parsed.unparseable is not None:
        return CommandEvaluation("evaluated", config.unparseable_decision, dialect, digest, (), parsed.unparseable)
    unmatched = cast(CommandDecisionName, config.unmatched_decision)  # declared whenever rules exist
    verdicts = tuple(_judge(config, segment, index, unmatched, resolve) for index, segment in enumerate(parsed.segments))
    return CommandEvaluation("evaluated", _strictest(v.decision for v in verdicts), dialect, digest, verdicts, None)


def evaluate_command(
    config: CommandPolicyConfig,
    command: str,
    *,
    dialect: Dialect | None = None,
    resolve_program: ProgramResolver | None = None,
) -> CommandEvaluation:
    """Judge ``command`` against ``config`` under ``dialect`` (default: the platform's).

    ``resolve_program`` maps a bare program name to the path it would run; it is
    consulted only for a pinned ``allow`` rule, and without it such a rule cannot
    prove a bare name and refuses it.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    if not config.rules:  # no policy: nothing is parsed or decided
        return _no_policy(chosen)
    return _evaluate(config, command, chosen, resolve_program, policy_digest(config))


# --------------------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------------------


def _example_problem(rule: str, expectation: str, evaluation: CommandEvaluation) -> str | None:
    own = [match for match in evaluation.matched_rules if match.rule == rule]
    matched = any(not match.pin_violation for match in own)
    if expectation == "not_match":
        return "matches it" if matched else None
    if matched:
        return None
    if evaluation.unparseable is not None:
        return f"does not match: the example is unparseable ({evaluation.unparseable})"
    unread = [verdict.segment.unparseable for verdict in evaluation.segments if verdict.segment.unparseable]
    if unread:
        return f"does not match: part of the example is unparseable ({unread[0]})"
    if own:
        return f"does not match: {own[0].justification}"
    return "does not match"


def self_test(config: CommandPolicyConfig, *, dialect: Dialect | None = None) -> SelfTestReport:
    """Judge every rule's examples with the runtime evaluator, under ``dialect``.

    No program resolver is used, so a pinned rule's examples name absolute paths
    and the result does not depend on the host. Never raises for a failing
    example: ``CommandPolicy`` turns a failed report into an error.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    digest = policy_digest(config)
    failures: list[SelfTestFailure] = []
    checked = 0
    for rule in config.rules:
        for expectation, examples in (("match", rule.match), ("not_match", rule.not_match)):
            for example in examples:
                checked += 1
                observed = _example_problem(rule.name, expectation, _evaluate(config, example, chosen, None, digest))
                if observed is not None:
                    failures.append(SelfTestFailure(rule.name, cast(Literal["match", "not_match"], expectation), example, observed))
    return SelfTestReport(chosen, checked, tuple(failures))


class CommandPolicy:
    """A command policy that has passed its self-test under one dialect.

    Construction runs ``self_test`` and raises ``CommandPolicySelfTestError`` (a
    ``ValueError``) naming each failing rule and example, so a policy whose
    examples are wrong cannot be built; AD-1328 S2 builds it at startup, where a
    failure stops startup. With no rules, ``evaluate`` returns ``no_policy`` and
    parses nothing.
    """

    def __init__(self, config: CommandPolicyConfig, *, dialect: Dialect | None = None) -> None:
        _require_config(config)
        self._config = config
        self._dialect = _dialect(dialect)
        self._digest = policy_digest(config)
        self._report = self_test(config, dialect=self._dialect)
        if not self._report.passed:
            raise CommandPolicySelfTestError(self._report)

    @property
    def config(self) -> CommandPolicyConfig:
        return self._config

    @property
    def dialect(self) -> Dialect:
        return self._dialect

    @property
    def digest(self) -> str:
        return self._digest

    @property
    def self_test_report(self) -> SelfTestReport:
        return self._report

    @property
    def configured(self) -> bool:
        """False when no rule is configured, so every command runs as it would without a policy."""
        return bool(self._config.rules)

    def evaluate(self, command: str, *, resolve_program: ProgramResolver | None = None) -> CommandEvaluation:
        if not self._config.rules:
            return _no_policy(self._dialect)
        return _evaluate(self._config, command, self._dialect, resolve_program, self._digest)

    def canonical(self, command: str, *, resolve_program: ProgramResolver | None = None) -> CanonicalCommand:
        return canonical_command(command, dialect=self._dialect, resolve_program=resolve_program, limits=self._config)


# --------------------------------------------------------------------------------------
# Canonical command and policy digest
# --------------------------------------------------------------------------------------


def _canonical_json(value: object) -> bytes:
    """RFC 8785 bytes (AD-1144's canonicaliser), imported lazily so that importing this
    module does not run the federation package ``__init__`` (precedent:
    ``probos.cognitive.elastic_team.canonicalize_projection``)."""
    from probos.federation.ard.jcs import canonicalize

    return canonicalize(value)


def policy_digest(config: CommandPolicyConfig) -> str:
    """``POLICY_DIGEST_SCHEME``: sha256 of a domain tag and the RFC 8785 JSON of the whole
    policy, examples included. Any change to the policy changes it, which is what
    expires an approval granted under the old one."""
    _require_config(config)
    return hashlib.sha256(_POLICY_DOMAIN + _canonical_json(config.model_dump(mode="json"))).hexdigest()


def _is_simple(segment: CommandSegment) -> bool:
    return (
        segment.unparseable is None
        and bool(segment.tokens)
        and not segment.assignments
        and not segment.redirections
        and not segment.wrappers
        and not any(segment.dynamic)
    )


def _canonical_program(segment: CommandSegment, resolve: ProgramResolver | None) -> str:
    program = segment.tokens[0]
    if _is_path(program, segment.dialect):
        return _path_key(program, segment.dialect)
    resolved = _resolve(resolve, program)
    if resolved is not None:
        return _path_key(resolved, segment.dialect)
    return _program_name(program, segment.dialect)


def canonical_command(
    command: str,
    *,
    dialect: Dialect | None = None,
    resolve_program: ProgramResolver | None = None,
    limits: CommandPolicyConfig | None = None,
) -> CanonicalCommand:
    """The approval-reuse identity of ``command`` (see ``CanonicalCommand``).

    Shell wrappers are unwrapped one level at a time, at most ``max_nesting``
    times; pass the same ``resolve_program`` the evaluation used.
    """
    if type(command) is not str:
        raise TypeError("command_policy_command_type_invalid")
    bounds = _DEFAULT_LIMITS if limits is None else limits
    text, chosen = command, _dialect(dialect)
    for _ in range(bounds.max_nesting + 1):
        parsed = parse_command(text, dialect=chosen, limits=bounds, unwrap_shells=False)
        if parsed.unparseable is not None or len(parsed.segments) != 1:
            break
        segment = parsed.segments[0]
        wrapper = _shell_wrapper(segment) if segment.unparseable is None else None
        if isinstance(wrapper, tuple):
            text, chosen = wrapper
            continue
        if wrapper is None and _is_simple(segment):
            program = _canonical_program(segment, resolve_program)
            return CanonicalCommand("argv", None, (program, *segment.tokens[1:]))
        break
    return CanonicalCommand("script", chosen, (text,))
```

### Section 3 -- `DECISIONS.md`

```
<<<<<<< SEARCH
## Era V — Civilization (Phases 31-36)
=======
## Era V — Civilization (Phases 31-36)

### AD-1328 S1 -- Command execution policy core: prefix rules, a three-dialect tokenizer, strictest wins, self-testing examples (2026-10-16, #1530)

- *Slicing.* Two slices in one PR that closes #1530: S1 the pure policy core, unwired (this); S2 the wiring before broker admission in `RunCommandTool` and `ShellCommandAgent._run_command`, the `ExecutionConfig.command_policy` field, escalation through the AD-1154 approval inbox, the AD-1224 and AD-1316 records, `probos doctor`, the opt-in starter policy, the golden byte-identical test and approval reuse.
- *D2 (placement).* Models in `config_models/operations.py` beside `ExecutionConfig` (that module may import nothing from `probos`, so S2 can attach them there); the engine in `probos.execution.command_policy`. S1 adds no config field and no re-export, so the facade, profile and reference checks are untouched.
- *D3 (tokenizer).* Explicit `posix`, `cmd` and `powershell` dialects (default `cmd` on Windows, else `posix`); single-pass lexers, linear work, bounds of 8,192 characters, 32 segments and nesting 3. Compound commands, substitutions and unwrapped shell wrappers are split and every segment is judged. What cannot be bounded is unparseable and takes `unparseable_decision`, default `escalate` (Design Principle 13(c)), never `allow`, never looser than `unmatched_decision`. A shell not invoked as an unwrappable inline script (`curl x | sh`, `bash script.sh`) is unparseable.
- *D4 (semantics).* Strictest wins across every matching rule; restrictive rules see through paths, assignments and expanded words, permissive rules need proof (a bare name, or a resolved path in `host_executable`, else `forbid` with the path named). With rules, `unmatched_decision` must be declared. With no rules the result is `no_policy` and nothing is parsed.
- *D5 (self-test).* Examples are judged by the runtime evaluator without a resolver; `CommandPolicy` raises `CommandPolicySelfTestError` naming each failing rule and example. Not a Pydantic validator, because the evaluator cannot live in `config_models`.
- *D6 (canonical command, digest).* An `argv` key (resolved program, literal words, dialect-free) for one simple command after unwrapping; otherwise a `script` key of the innermost script's exact text and dialect (the `-lc`/`-c` mode is dropped). Both keys and the policy digest are domain-separated sha256 over RFC 8785 JSON, versioned `.../v1`.
- *Obligations.* O-S1-1..O-S1-10 to S2, listed in the contract: attach and re-export the models, one policy per runtime built at startup, dialect per call site (PowerShell for `ShellCommandAgent` on Windows) and evaluation of the command as it will run, `no_policy` takes today's path, the resolver from the child's PATH, escalation that runs exactly once, records, approval reuse keyed on the canonical key and digest, the unwired scan changed deliberately, and starter-policy examples tested per dialect.
- Contract `prompts/ad-1328-s1-command-policy-core.md`.
>>>>>>> REPLACE
```

### Section 4 -- `PROGRESS.md`

The first 120 characters carry no ledger status keyword (`scripts/gen_ad_ledger.py:126-139`).

```
<<<<<<< SEARCH
# ProbOS Progress
=======
# ProbOS Progress

**AD-1328 slice S1 (2026-10-16), #1530 -- the command execution policy core is built and unwired; no new AD or BF number.** It adds `src/probos/execution/command_policy.py` and, in `src/probos/config_models/operations.py`, the `CommandPolicyRule` and `CommandPolicyConfig` models (not attached to `ExecutionConfig` and not re-exported). Ordered token-prefix rules with alternatives decide `allow`, `escalate` or `forbid`; the strictest decision of every matching rule wins and every match is listed; a `forbid` rule names its alternative; `host_executable` pins an `allow` rule to absolute paths and refuses the same name elsewhere. A bounded single-pass tokenizer reads `posix`, `cmd` and PowerShell (the dialect is an explicit argument), splits compound commands, substitutions and shell wrappers, and gives what it cannot read the configured `unparseable_decision` (default `escalate`, never `allow`). With no rules the result is `no_policy` and nothing is parsed. `self_test` judges every rule's `match`/`not_match` examples with the same evaluator, and `CommandPolicy` refuses to build from a policy that fails, naming the rule and the example. `canonical_command` (wrappers unwrapped, program resolved, exact script text otherwise) and `policy_digest` are versioned sha256 over RFC 8785 JSON. Nothing under `src/` constructs the policy (a scan test pins it). S2 (wiring before broker admission in both `run_command` paths, approval escalation, records, `probos doctor`, the starter policy and approval reuse) completes #1530 in the same PR. Contract `prompts/ad-1328-s1-command-policy-core.md`.
>>>>>>> REPLACE
```

### Section 5 -- `docs/research/reference-projects.md`

Review date used: 2026-10-16 (90-day interval for harnesses). Cline was overdue and examined; Claude Code was re-checked (not overdue).

```
<<<<<<< SEARCH
| Claude Code | 2026-10-15 | checked | sandbox and permission model studied for AD-1335 (#1557); lexical search in the AD-989 ripgrep absorption (2026-06-13, `DECISIONS.md`); context forking in `cognitive-sub-task-protocol.md` (2026-04-15) |
=======
| Claude Code | 2026-10-16 | checked | Bash permission rules (compound splitting, wrappers, assignments, documented limits) for AD-1328 (#1530), `prompts/ad-1328-s1-command-policy-core.md`; sandbox and permission model studied for AD-1335 (#1557); lexical search in the AD-989 ripgrep absorption (2026-06-13, `DECISIONS.md`); context forking in `cognitive-sub-task-protocol.md` (2026-04-15) |
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
| Cline | 2026-03-20 | passing | AD-360 (shadow git checkpoints, workspace access tiers) |
=======
| Cline | 2026-10-16 | checked | command auto-approval for AD-1328 (#1530), `prompts/ad-1328-s1-command-policy-core.md` (model-flagged `requires_approval`, no fixed allowlist); AD-360 (shadow git checkpoints, workspace access tiers) |
>>>>>>> REPLACE
```

No `docs/development/roadmap.md` change: it has no AD-1328 row (Absence Verified A5), and S2 records the closure.

**Regenerate the ledger right after installing Sections 3-4** (pinned by `tests/test_ad1184_ad_ledger.py`):

```
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check
```

---

## Tests (written by Builders against the installed source; tests only)

Rules for every file: never edit `src/`. Every dialect is passed explicitly (`dialect="posix"`, `"cmd"`, `"powershell"`), so each file passes on Linux CI and on Windows; only M2 #1 calls the default. No filesystem, subprocess or environment access, except M3 #16-17, which read source files. A resolver is a plain function over a dict (`lambda name: {"git": "/usr/bin/git"}.get(name)`). Configs are built with `CommandPolicyConfig.model_validate({...})` from plain dicts, as an operator's YAML would arrive. Each test asserts its own premise and has a negative control (the accepted neighbour). Parse-time refusals are `pydantic.ValidationError` whose `str()` contains the phrase named below. Use this helper shape in M3 (copy it, do not import across test files):

```python
def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})

def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}
```

### M1 `tests/test_ad1328_s1_policy_models.py` (models and digest; no engine call except `policy_digest`)

1. `test_minimal_rule_is_accepted_and_required_fields_are_required[name, pattern, decision, justification]`: each missing field is a `ValidationError`; the four together are accepted.
2. `test_rule_name_shape[upper, space, empty, sixty_five, leading_dash]`: refused, text contains `command policy rule name`; `git-push.force_1` and a 64-character name are accepted.
3. `test_alternative_rules`: `forbid` without `alternative` is refused (`a forbid rule must name its alternative`, and the text contains the rule name); `allow` with one is refused (`an allow rule has no alternative`); `escalate` with and without one is accepted; a blank justification is refused (`must not be blank`). Kills R1.
4. `test_pattern_bounds[empty, thirty_three, empty_word, empty_alternatives, duplicate_alternative, program_slash, program_backslash, program_space, control_character]`: refused with the rule name in the text; 32 positions, and alternatives at position 0 and position 2, are accepted; pattern lists arrive as tuples (`rule.pattern == ("git", ("push", "fetch"))`).
5. `test_host_executable_rules[relative, on_forbid, on_escalate, alternatives_program, basename_mismatch, duplicate]`: refused (`on_forbid` text contains `pins an allow rule only`; `basename_mismatch` contains `does not name the program`); `/usr/bin/git`, `C:\\Program Files\\Git\\cmd\\git.exe` and `\\\\server\\share\\git.exe` are accepted for pattern `["git", "status"]`. Kills R3, R4.
6. `test_example_bounds[blank, over_1024, nul, both_lists, thirty_three]`: refused; an example containing a newline and a tab, and one of exactly 1,024 characters, are accepted.
7. `test_config_defaults`: `CommandPolicyConfig()` has `rules == ()`, `unmatched_decision is None`, `unparseable_decision == "escalate"`, limits 8192/32/3, and is valid.
8. `test_config_cross_field_rules[rules_without_unmatched, unparseable_allow, unparseable_looser_than_unmatched, duplicate_names, two_hundred_fifty_seven]`: refused with `declare unmatched_decision`, `may not be allow`, `at least as strict` (`unmatched_decision="forbid"`, `unparseable_decision="escalate"`), `declared twice`, `at most 256 rules` respectively. Controls: one rule with `unmatched_decision="allow"` and default `unparseable_decision` accepted; `unmatched="forbid"`, `unparseable="forbid"` accepted; no rules with `unparseable_decision="allow"` accepted (no policy, nothing to bypass). Kills R2, R5, R6, R7.
9. `test_limit_bounds[max_command_chars, max_segments, max_nesting]`: 63 and 65537, 0 and 257, -1 and 9 refused; 64 and 65536, 1 and 256, 0 and 8 accepted.
10. `test_models_are_frozen_and_closed`: an extra field is refused on both models; assigning `rule.decision` raises `ValidationError`.
11. `test_policy_digest_known_answer`: expected = `hashlib.sha256(b"probos.command_policy/policy/v1\x00" + probos.federation.ard.jcs.canonicalize(cfg.model_dump(mode="json"))).hexdigest()`, computed in the test; the same bytes under `.../policy/v2\x00` differ (negative control); `POLICY_DIGEST_SCHEME == "probos.command_policy/policy/v1"`. Kills E31.
12. `test_policy_digest_tracks_every_change[justification, decision, rule_order, unmatched, example]`: two configs built from equal dicts have equal digests; each single change gives a different digest.
13. `test_s1_models_are_off_the_config_surface`: `probos.config` has no attribute `CommandPolicyConfig`, `CommandPolicyRule` or `windows_program_stem`; none is in `probos.config_models.__all__`; `"command_policy" not in ExecutionConfig.model_fields`. This pins D2; S2 changes it deliberately (O-S1-1).
14. `test_windows_program_stem[cases]`: `C:\\Git\\GIT.EXE` -> `git`; `/usr/bin/git` -> `git`; `x.cmd` -> `x`; `.exe` -> `.exe`; `python3.12` -> `python3.12`; `Tool.Bat` -> `tool`.

### M2 `tests/test_ad1328_s1_command_parse.py` (tokenizer and canonical command)

Assert on `ParsedCommand` / `CommandSegment` fields only. `tokens(cmd, d)` = `[s.tokens for s in parse_command(cmd, dialect=d).segments]` is a fine local helper.

1. `test_dialects`: `default_dialect("win32") == "cmd"`, `default_dialect("linux") == "posix"`, `default_dialect("darwin") == "posix"`, `parse_command("ls").dialect == default_dialect()`; `dialect="bash"` and `dialect=1` raise `ValueError("command_policy_dialect_invalid")`; a non-str command raises `TypeError`. Kills E44, E45.
2. `test_simple_words[posix, cmd, powershell]`: `git status -s` gives one segment `("git", "status", "-s")`, depth 0, nothing dynamic, `unparseable is None`.
3. `test_posix_quoting`: `git commit -m 'a b' "c d" e\ f` -> `("git","commit","-m","a b","c d","e f")`; `echo ''` -> `("echo", "")`; `echo "a\"b"` -> `'a"b'`; `echo 'it'"'"'s'` -> `"it's"`; `echo "a\\b"` (shell text `"a\\b"`) -> `a\b`; a line continuation `git \<newline>status` -> `("git","status")`.
4. `test_cmd_quoting`: `git commit -m "a b" x^&y` -> `("git","commit","-m","a b","x&y")`; `echo "a&b"` stays one segment.
5. `test_powershell_quoting`: `git commit -m 'it''s' "a""b" "c`"d"` -> `("git","commit","-m","it's",'a"b','c"d')`.
6. `test_compound_split[posix, cmd, powershell]`: posix `a; b && c || d | e |& f & g` + newline + `h` gives programs `a b c d e f g h`; cmd `a & b && c || d | e` gives `a b c d e`; powershell `a; b && c || d | e` gives `a b c d e`; a newline after `&&` continues (`a &&` newline `b` gives `a b`); blank lines are skipped.
7. `test_posix_substitution_segments`: `` echo $(curl x | sh) `id` `` gives programs `echo, curl, sh, id` (echo first), the `echo` segment's two arguments dynamic, the inner segments depth 1, and the `sh` segment unparseable (a shell with no inline script). Kills E19a, E19b.
8. `test_dynamic_words[posix_var, posix_brace, posix_glob, posix_tilde, posix_brace_expansion, cmd_percent, ps_var, ps_brace, ps_splat]` and controls `[posix_single_quoted, cmd_quoted_percent_literal, ps_single_quoted]`: `echo $HOME`, `echo ${HOME}`, `echo *.py`, `echo ~/x`, `echo {a,b}`, cmd `echo %PATH%`, powershell `echo $env:PATH`, `echo ${x}`, `git @args` have `dynamic == (False, True)`; `echo '$HOME'`, cmd `echo "100%"`, powershell `echo '$x'` have `(False, False)`. Kills E46, E47.
9. `test_unparseable_line[...]` (dialect, command, reason substring), each giving `segments == ()`: posix `echo 'a` (`single quote`), `echo "a` (`double quote`), `echo $(a` (`$(`), `` echo `a `` (`backtick`), `cat <<EOF` (`here-document`), `cat <<< x` (`here-string`), `echo $((1+2))` (`arithmetic`), `echo $'x'` (`quoting`), `(a)` (`subshell`), `diff <(a) b` (`process substitution`), `a;; b` (`case`), `a &&` (`nothing after`), `; a` (`empty command`), `echo a\` (`trailing`), `echo a` + NUL (`control`), `echo a` + CR + `b` (`control`), `echo a` + U+2028 (`line break`); cmd `(a)` (`parenthesised`), `echo "a` (`double quote`), `echo a^` (`trailing`); powershell `echo $(x)` (`subexpression`), `echo @'x'@` (`here-string`), `{x}` (`syntax`), `git --% x` (`stop-parsing`), `a < b` (`reserved`), `echo ‘x’` (`syntax`), `git` + U+00A0 + `push` (`syntax`), `git push,--force` (`syntax`), `a &` (`background`); and `""`, `"   "`, posix `# c` (`no command`). Kills E15, E17, E18, E23, E41, E42, E43.
10. `test_unparseable_segment[...]`: the line parses (`unparseable is None`) and the one segment's `unparseable` is set: posix `eval x`, `sudo x`, `env A=1 x`, `xargs rm`, `if x`, `$X arg`, `FOO=1`, `> f`, `bash script.sh`, `sh`; cmd `call x`, `start x`, `@echo off`; powershell `iex x`, `Invoke-Expression x`, `. ./x.ps1`, `& $x`. Controls: `evaluate x`, `sudoku`, `ifconfig` parse with `unparseable is None`. Kills E24, E25, E27.
11. `test_redirections_stay_out_of_tokens`: posix `git status > out 2>&1` -> tokens `("git","status")`, `redirections == (">out", "2>&1")`; cmd `dir > out` -> `(">out",)`; powershell `git log *> out` -> `("*>out",)`; posix `echo >` is unparseable (`no target`).
12. `test_leading_assignments_posix`: `A=1 B="x y" git push` -> `assignments == ("A=1", 'B="x y"')`, tokens `("git","push")`; `"A=1" git` -> tokens `("A=1","git")`, no assignments; cmd `A=1 git` -> segment unparseable (`cmd.exe may split`). Kills E28.
13. `test_process_wrappers[time, nohup, timeout, nice_n, stdbuf, command, timeout_then_nice]`: `time x`, `nohup x`, `timeout 30 x`, `nice -n 5 x`, `stdbuf -oL x`, `command x`, `timeout 30 nice x` give tokens starting `("x",)` and the wrappers recorded (`("timeout 30", "nice")` for the last); refused forms `timeout -s KILL 5 x`, `nice -5 x`, `time -p x`, `timeout` give a segment unparseable; `command -v git` is the ordinary program `command`; powershell `timeout 30 x` is the ordinary program `timeout`. Kills E29.
14. `test_shell_wrappers_unwrapped[...]`: posix `bash -lc 'git status'`, `/bin/bash -c "git status"`, `sh -c 'a && b'`; cmd `cmd /c git status`, `cmd /C "git status"`; cmd `pwsh -NoProfile -Command "git status"`; posix `powershell -c git status` give the inner segments (`("git","status")` or `a`, `b`) at depth 1 with the inner dialect (`posix`, `cmd`, `powershell`). Refused forms, each one unparseable segment: `bash -c 'x' arg0`, `bash -xc 'x'`, `bash -c $X`, `pwsh -EncodedCommand AAA`, `pwsh -File x.ps1`, `cmd /k x`, `cmd %X% x`. `parse_command(..., unwrap_shells=False)` on `bash -lc 'git status'` gives the one segment `("bash","-lc","git status")`. Kills E26, E27.
15. `test_wrapped_script_unparseable_marks_the_segment`: `bash -c 'echo "x'` parses (`unparseable is None`); its one segment's `unparseable` contains `the wrapped script is unparseable`.
16. `test_bounds`: `max_command_chars` + 1 characters is unparseable (`longer than`), exactly the bound is not; 33 segments (`a;` repeated) unparseable (`more than 32 segments`), 32 not; `$(a $(b $(c $(d))))` unparseable (`nested deeper`), `$(a $(b $(c)))` not; with `limits=CommandPolicyConfig(max_nesting=1)`, `bash -c 'bash -c x'` gives one unparseable segment (`shell wrappers nested deeper`), and with `max_nesting=2` gives `("x",)` at depth 2. Kills E20, E21, E22, E50.
17. `test_hostile_input_is_linear[cmd_percent, posix_dollar, posix_unbalanced_quote, ps_quotes, posix_backslashes, posix_brace]`: with `limits=CommandPolicyConfig(max_command_chars=65536)`, a 65,536-character command of `%a ` repeated (cmd), `$` repeated, `"` + `a` x 65,535, `''` repeated (powershell), `\\` repeated, `${a}` repeated each parses within 2.0 seconds (`time.perf_counter`); report the slowest.
18. `test_canonical_wrapper_variants_share_one_key`: posix `git status`, `bash -lc 'git status'`, `/bin/bash -lc "git status"`, `sh -c 'git  status'` share one `key` of kind `argv` and parts `("git","status")`; cmd `git status`, `cmd /c git status`, `cmd /C "git status"`, and cmd `pwsh -Command "git status"` share one key, equal to the posix one.
19. `test_canonical_program_resolution`: with `resolve_program={"git": "/usr/bin/git"}.get`, posix `git status` and `/usr/bin/git status` share a key; without a resolver they differ; cmd, `{"git": "C:\\Git\\cmd\\git.exe"}.get`: `git status` and `"C:\\GIT\\cmd\\GIT.EXE" status` share a key. Kills E34.
20. `test_canonical_script_fallback`: posix `bash -lc 'ls && pwd'` and `/bin/bash -c 'ls && pwd'` share a key, `kind == "script"`, `dialect == "posix"`, `parts == ("ls && pwd",)`; `bash -lc 'echo "a'` and `bash -lc 'echo "b'` differ, each kind `script`; `echo $HOME`, `git status > f`, `timeout 5 x`, `A=1 x`, `eval x` are each kind `script` with the exact text. Kills E33.
21. `test_canonical_key_known_answer`: `key == hashlib.sha256(b"probos.command_policy/canonical_command/v1\x00" + canonicalize([c.kind, c.dialect, list(c.parts)])).hexdigest()` for one argv and one script key; `CANONICAL_KEY_SCHEME` is `probos.command_policy/canonical_command/v1`. Kills E32.

### M3 `tests/test_ad1328_s1_policy_evaluation.py` (evaluator, self-test, policy object, unwired)

1. `test_no_rules_is_no_policy_and_parses_nothing`: `evaluate_command(CommandPolicyConfig(), "(((", dialect="posix")` has `status == "no_policy"`, `decision is None`, `segments == ()`, `unparseable is None`, `policy_digest is None` (an unparseable line, so nothing was parsed); the same with `unmatched_decision="forbid"` and no rules; `CommandPolicy(CommandPolicyConfig(), dialect="posix").evaluate("(((")` equal; `configured is False`. Control: one rule makes the same text `evaluated` with `decision == "escalate"`. Kills E11a, E11b.
2. `test_strictest_wins_with_overlapping_rules`: rules allow `git`, escalate `git push`, forbid `git push --force`, `unmatched="escalate"`: `git status` -> `allow` (one match); `git push origin` -> `escalate` (two matches in rule order); `git push --force` -> `forbid`, `matched_rules` names all three in rule order, `governing` names only the forbid rule and carries its justification and alternative. With the rules reversed, the three decisions are unchanged. Kills E1, R2-order (the rank map).
3. `test_alternatives_per_position`: forbid `[["curl", "wget"]]` matches `curl x` and `wget x`; forbid `["git", ["push", "fetch"], "--force"]` matches `git fetch --force`, not `git fetch origin`.
4. `test_one_forbidden_segment_forbids_the_command[posix_and_pipe, cmd_sequence, ps_sequence, posix_substitution, posix_wrapper, posix_pipe_to_shell]` with forbid `curl` and `unmatched="allow"`: `git status && curl x | sh`, cmd `git status & curl x`, powershell `git status; curl x`, posix `echo $(curl x)` and `bash -c 'git status; curl x'` -> `forbid`, the curl segment's verdict `forbid`/`rule`, the git segment's `allow`/`unmatched`; `echo 'curl x' | sh` -> `escalate` (the `sh` segment is unparseable, so it is not `allow`). Control: `git status && git log` -> `allow`. Kills E26 (wrapper case), E27 (pipe case).
5. `test_unmatched_and_unparseable_decisions`: one forbid rule, `unmatched="allow"`, default `unparseable_decision` (`escalate`), so the two decisions differ: `ls` -> `allow`, basis `unmatched`; `echo "x` -> `escalate` with `unparseable` set and no segments; `eval x` -> `escalate`, basis `unparseable`; with `unmatched="escalate"`, `ls` -> `escalate`; with `unparseable_decision="forbid"`, `echo "x` and `eval x` -> `forbid`. Kills E9, E10.
6. `test_restrictive_rules_see_through_and_allow_rules_need_proof`: forbid `["git", "push", "--force"]`, `unmatched="allow"`: `/usr/bin/git push --force`, `FOO=1 git push --force`, `git push $F` (an expanded word at pattern position 2) -> `forbid`. Separately allow `["git", "push"]`, `unmatched="escalate"`: `git push` and `git push $X` (the expanded word is past the pattern) -> `allow`; `FOO=1 git push`, `git $X push` (an expanded word at pattern position 1), `./git push`, `/usr/bin/git push` -> `escalate` (basis `unmatched`). Kills E3, E4, E5, E7, E28.
7. `test_windows_program_names_are_case_insensitive[cmd, powershell]`: forbid `curl`: `CURL.EXE x` and `C:\\Windows\\System32\\curl.exe x` -> `forbid`; posix `CURL x` -> `allow` (unmatched). Kills E8.
8. `test_pinning_refuses_a_same_basename_executable_outside_the_pins`: allow `["git"]`, `host_executable=["/usr/bin/git"]`, `unmatched="escalate"`, posix: resolver git -> `/usr/bin/git`: `git status` -> `allow`, `resolved_program == "/usr/bin/git"`; resolver git -> `/tmp/evil/git`: `forbid`, `pin_violation is True`, justification contains `/tmp/evil/git`, alternative contains `/usr/bin/git`; `/tmp/evil/git status` -> `forbid`; `/usr/bin/git status` (no resolver) -> `allow`; `git status` without a resolver and with a resolver returning None -> `forbid` (`does not resolve`); a resolver returning an int raises `TypeError`. cmd: pin `C:\\Program Files\\Git\\cmd\\git.exe`, command `"C:\\PROGRAM FILES\\Git\\cmd\\GIT.exe" status` -> `allow`. Kills E6.
9. `test_a_pin_violation_does_not_hide_other_matches`: the pinned allow plus forbid `["git", "push", "--force"]`: `/tmp/evil/git push --force` -> `forbid`, and `matched_rules` holds both rules (one with `pin_violation`).
10. `test_evaluation_result_shape`: for `/usr/bin/git push --force` under a forbid `git push` rule: `matched_prefix == ("/usr/bin/git", "push")`, `segment == 0`, `policy_digest == policy_digest(cfg)`, `dialect == "posix"`; `matched_rules` is a tuple of `RuleMatch`; `segments[0].segment.tokens` is the command's words.
11. `test_self_test_passes_and_counts_examples`: three rules with five examples in total that hold: `report.passed`, `examples_checked == 5`, `failures == ()`; `CommandPolicy(cfg, dialect="posix")` builds and `self_test_report == self_test(cfg, dialect="posix")`.
12. `test_a_wrong_example_names_the_rule_and_the_example[match_misses, not_match_hits, match_unparseable, pinned_match_with_bare_name]`: `CommandPolicy(cfg, dialect="posix")` raises `CommandPolicySelfTestError`, an instance of `ValueError`, whose `str()` contains the rule name, the example and `posix`; `self_test(cfg, dialect="posix")` returns the same failure (rule, expectation, example) without raising; `pinned_match_with_bare_name` (match example `git status` for a rule pinned to `/usr/bin/git`) observes `does not match`, while `/usr/bin/git status` as the example passes (control). Kills E12, E13, E14.
13. `test_self_test_runs_under_the_dialect_given`: a rule `["echo", "a&b"]` with match example `echo a^&b` passes under `cmd` and fails under `posix` (there `&` splits the command).
14. `test_report_lists_every_failure_and_the_message_stops_at_five`: seven failing `match` examples on unpinned rules (so no justification text repeats `rule '`): `len(report.failures) == 7`; the error text contains `(and 2 more)` and exactly five `rule '` occurrences.
15. `test_command_policy_surface`: `dialect`, `digest == policy_digest(cfg)`, `config is cfg`, `configured`; `evaluate(cmd)` equals `evaluate_command(cfg, cmd, dialect="posix")`; `canonical(cmd)` equals `canonical_command(cmd, dialect="posix", limits=cfg)`; a dict config raises `TypeError("command_policy_config_type_invalid")` for `CommandPolicy`, `evaluate_command`, `self_test` and `policy_digest`.
16. `test_nothing_in_src_constructs_the_policy(tmp_path)`: an AST scan of every `*.py` under `src/probos` (follow the shape of `tests/test_ad1288_s1_commission_chain.py:576-660`; copy, do not import). Offenders: outside `execution/command_policy.py`, any import of a module named `command_policy` (`import`, `from ... import`, relative); outside that file and `config_models/operations.py`, any imported name or `ast.Name` load of `CommandPolicyConfig`, `CommandPolicyRule`, `CommandPolicy`, `evaluate_command`, `canonical_command` or `policy_digest`; and any call of `CommandPolicy`. Premise: both spared files exist and define their classes. Non-vacuity: in a scratch tree each forbidden shape (`from probos.execution.command_policy import CommandPolicy`, `from probos.execution import command_policy`, `import probos.execution.command_policy as p`, `from .command_policy import evaluate_command`, `CommandPolicy(cfg)`, `from probos.config_models.operations import CommandPolicyConfig`) is flagged, and `note = "CommandPolicy is in probos.execution.command_policy"` and a docstring naming it are not. S2 changes this test deliberately (O-S1-9).
17. `test_the_policy_module_is_pure`: parse `src/probos/execution/command_policy.py`; its imports are exactly `__future__`, `hashlib`, `ntpath`, `posixpath`, `re`, `sys`, `collections.abc`, `dataclasses`, `typing`, `probos.config_models.operations` and (inside `_canonical_json` only) `probos.federation.ard.jcs`; no name `open`, `os`, `subprocess`, `asyncio` or `shutil` appears; `sys` is used only as `sys.platform`. Control: the same check flags a scratch module that imports `os`.

## What This Does NOT Change

- No call site: `RunCommandTool`, `ShellCommandAgent`, the tool executor, the effect broker, consensus and the permission ladder are untouched; nothing imports the new module (M3 #16), so a runtime behaves byte-for-byte as before.
- No config field, re-export, profile row, config-reference row or facade-baseline row (D2; M1 #13).
- No approval, escalation, record, event type, store, API, UI, startup, shutdown or `probos doctor` change; no starter policy.
- `ExecutionConfig`, the BF-890 constants and validators, and every other model in `operations.py` are byte-identical apart from the inserted block before `ExecutionConfig` and the import lines.

## Do Not Build

Wiring, approval reuse, records, `doctor` output, the starter policy (S2). OS-level sandboxing, network egress control (AD-1233's posture stands), an LLM reviewer (AD-1330, #1532), environment scrubbing (BF-890, #1529), or any policy language beyond prefix rules: no regexes, globs, argument predicates, option-order normalisation (`git -C . push`), short-flag expansion (`-f` for `--force`) or per-program argument parsers (`find -exec`, `python -c`). No tree-sitter or other parser dependency. The policy never bypasses consensus or the permission ladder; S1 cannot, as nothing calls it.

## Acceptance Criteria

1. Sections 1-5 install mechanically on `26250c9c`; each SEARCH occurs exactly once; the ledger regenerates and `--check` passes.
2. Strictest wins with overlapping rules, every match listed (M3 #2); a compound command with one forbidden segment is forbidden in all three dialects, through substitutions and shell wrappers (M3 #4).
3. A deliberately wrong example fails to build the policy with a message naming the rule and the example (M3 #12); examples are judged by the runtime evaluator under the dialect given (M3 #13).
4. Program-path pinning refuses a same-basename executable outside the pinned paths, and an unresolvable bare name (M3 #8).
5. Wrapper variants of one simple command share one canonical key; scripts differing only in untokenizable text do not (M2 #18-20).
6. With no rules the result is `no_policy` and nothing is parsed (M3 #1); nothing in `src/` constructs the policy (M3 #16); the module is pure (M3 #17); the models are off the config surface (M1 #13).
7. Every test passes on Windows and Linux (explicit dialects; no host dependence).
8. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_policy_models.py tests/test_ad1328_s1_command_parse.py tests/test_ad1328_s1_policy_evaluation.py -q -n 0`; then `tests/test_ad1270e2e_operations_models.py tests/test_ad1270e1_config_facade.py tests/test_bf890_config.py tests/test_bf890_command_env.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_bf892_spawn_env_guard.py tests/test_standing_orders_layout.py tests/test_ad1184_ad_ledger.py -q -n 0`; then `scripts/check_config_facade.py --check`, `scripts/check_config_profiles.py --check`, `scripts/gen_config_reference.py --check`, `scripts/check_architecture_principles.py --check` and `scripts/gen_ad_ledger.py --check`, each exit 0.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden Pins (enumerated)

| Pin | Evidence | Effect on S1 |
|---|---|---|
| `operations.py` imports no `probos` (`tests/test_ad1270e2e_operations_models.py:572-582`) | Section 1 adds `ntpath`, `typing`, pydantic names only | Holds. |
| No class name in two `config_models` modules (`:593-603`) | Absence A2 | New names are unique. |
| `config_models.__all__` equals its imports (`:606-618`) | `__init__.py` untouched | Holds. |
| `MOVED_MODELS` / `EXPECTED_DUMPS` (`:56`, `:133`) | `ExecutionConfig` unchanged | Holds in S1; S2 updates (O-S1-1). |
| Facade baseline (`scripts/check_config_facade.py:1020`, `vars(probos.config)`) | no re-export | Unchanged; `--check` in acceptance 8. |
| Facade G2 environment scan of `config_models/**` (`:399-402`) | Section 1 reads no environment | Unchanged. |
| Profiles gate 3 (`scripts/check_config_profiles.py:149`, reachable from `SystemConfig`) and its `config_models` env scan (`:426`) | no field; no environment read | Unchanged; S2's field adds no boolean. |
| Config reference (`scripts/gen_config_reference.py:181`) | walks `SystemConfig.model_fields` | Unchanged. |
| Selector blast radius (`scripts/select_tests.py:221`, `src/probos/config_models/*.py`) | Section 1 edits `operations.py` | The selector picks the full suite; expected. |
| Layer boundaries (`tests/test_layer_boundaries.py:16-27`, `:137-165`) | `execution` and `config_models` are not in `LAYER_MAP` | No violation, no exception entry. |
| Architecture fitness (`scripts/check_architecture_principles.py:187-188`: 500 body lines, 15 methods; ranks `:1135-1139`) | largest class `_PosixLexer` about 150 lines, 9 methods; `CommandPolicy` 8; no DB, no task | No baseline row. |
| BF-892 launch guard (`tests/test_bf892_spawn_env_guard.py:61-78`) | no launcher in Section 2 | Unaffected. |
| Retired-name scan (`tests/test_standing_orders_layout.py:139`) | no `probos-architect`/`ProbOS Supervised`/`supervised-worker.json` in the new text | Unaffected. |
| Seam contracts and store registry | no seam id, no store, no SQL | Unaffected. |
| AD ledger (`tests/test_ad1184_ad_ledger.py`; head window `scripts/gen_ad_ledger.py:126-139`) | Section 4's first 120 characters have no status keyword | Regenerate after Sections 3-4. |

## Verified Against Codebase (2026-10-16, `26250c9c`)

```
git log --oneline -1                                      -> 26250c9c Merge pull request #1570 ...
scripts/ad_ceiling.py                                     -> CEILING AD-1341 (issue titles); NEXT AD-1342; AD-1328 = #1530 only
gh issue view 1530                                        -> OPEN, "AD-1328: a command execution policy for run_command ..."
src/probos/cognitive/swe_harness/tools.py:1101            class RunCommandTool:
src/probos/cognitive/swe_harness/tools.py:1134            async def invoke(
src/probos/cognitive/swe_harness/tools.py:1151            proc = await _asyncio.create_subprocess_shell(
src/probos/cognitive/swe_harness/tools.py:1157            env=build_command_env(self._command_env_passthrough),
src/probos/cognitive/swe_harness/tools.py:1235            (RunCommandTool(runtime, command_env_passthrough=command_env_passthrough), shell_perms),
src/probos/agents/shell_command.py:55                     IntentDescriptor(name="run_command", ... requires_consensus=True, ...)
src/probos/agents/shell_command.py:161                    async def _run_command(self, command: str) -> dict[str, Any]:
src/probos/agents/shell_command.py:168-173                win32: _strip_ps_wrapper; then _rewrite_python_interpreter
src/probos/agents/shell_command.py:200, :217, :230        _strip_ps_wrapper, _rewrite_python_interpreter, _run_sync
src/probos/agents/shell_command.py:250                    args = ["powershell", "-NoProfile", "-Command", command]
src/probos/agents/shell_command.py:259-261                subprocess.Popen(..., shell=True
src/probos/execution/effect_broker.py:338-339             elif tool_id == "run_command": effect_class = "shell"
src/probos/execution/effect_broker.py:953                 class GovernedEffectBroker(_EffectDispatchMixin):
src/probos/tools/action_approvals.py:111                  class ActionApprovalStore:
src/probos/config_models/experience.py:15                 class ApprovalInboxConfig(BaseModel):  # AD-1154
src/probos/__main__.py:3106                               doctor_parser = subparsers.add_parser("doctor", ...)
src/probos/config_models/operations.py:8-12               from __future__ ...; import re; from pydantic import BaseModel, Field, field_validator
src/probos/config_models/operations.py:14-16              "This module may not import probos"
src/probos/config_models/operations.py:24-27              _ENV_NAME_SHAPE_PATTERN = ...; class ExecutionConfig(BaseModel):
src/probos/config_models/operations.py:171                command_env_passthrough: list[str] = Field(default_factory=list)
src/probos/config.py:80                                   from probos.config_models.operations import (   (explicit names)
src/probos/federation/ard/jcs.py:53                       def canonicalize(value: object) -> bytes:
src/probos/cognitive/elastic_team.py:56-65                canonicalize_projection: lazy import of jcs (precedent)
src/probos/cognitive/dreaming.py, src/probos/fault_issue_filings.py   import from probos.config_models (precedent)
pyproject.toml:9                                          requires-python = ">=3.12"
tests/test_ad1270e2e_operations_models.py:572-582         operations module imports nothing starting "probos"
tests/test_ad1270e2e_operations_models.py:593-603         class names unique across config_models
tests/test_ad1270e2e_operations_models.py:606-618         __all__ equals imports
tests/test_ad1270e2e_operations_models.py:56, :133        MOVED_MODELS; EXPECTED_DUMPS["ExecutionConfig"]
tests/test_layer_boundaries.py:16-27, :137-165            LAYER_MAP; unmapped packages -> None
scripts/check_architecture_principles.py:187-188          SRP_MAX_BODY_LINES = 500; SRP_MAX_DIRECT_METHODS = 15
scripts/check_architecture_principles.py:1135-1139        ranked layers substrate..experience
scripts/check_config_facade.py:1020                       public = sorted(name for name in vars(facade) ...)
scripts/check_config_profiles.py:149, :426                reachable from SystemConfig; config_models rglob
scripts/gen_config_reference.py:181                       for field_name, field in SystemConfig.model_fields.items():
scripts/select_tests.py:221                               "src/probos/config_models/*.py",
scripts/gen_ad_ledger.py:126-139                          status keywords; _HEAD_WINDOW = 120
tests/test_ad1288_s1_commission_chain.py:576-660          AST "nothing constructs it" scan precedent
tests/test_bf892_spawn_env_guard.py:61-78                 launcher sets
tests/test_standing_orders_layout.py:139                  RETIRED regex
docs/research/codex-harness-absorption.md:15-16           rows 2-3 point at AD-1328
docs/research/reference-projects.md:30, :33, :35          Claude Code, SWE-agent, Cline rows
PROGRESS.md:1, DECISIONS.md:11                            "# ProbOS Progress"; "## Era V — Civilization (Phases 31-36)" (each once)
```

## Absence Verified (2026-10-16, `26250c9c`)

```
A1 CLAIM: nothing else names AD-1328's module or claims the number
   RUN:   Grep "command_policy" (whole worktree); Grep "AD-1328" (whole worktree); gh issue list --search "AD-1328 in:title" --state all
   FOUND: no "command_policy" anywhere; AD-1328 only as references to #1530 (DECISIONS.md:105, three prompts, two research notes, open-ads-report); one issue, #1530
   HOLDS: yes
A2 CLAIM: no class CommandDecision / CommandPolicy* / CommandRule* exists
   RUN:   Grep "class (CommandDecision|CommandPolicy\w*|CommandRule\w*)\b" src/
   FOUND: none
   HOLDS: yes
A3 CLAIM: no existing command tokenizer to reuse (DRY)
   RUN:   Grep "shlex\.split|def split_command|def tokeni[sz]e_command" src/probos
   FOUND: none (tools.py:1138 imports shlex; nothing under src calls shlex.split)
   HOLDS: yes
A4 CLAIM: no test pins the set of classes or the text of operations.py beyond its imports
   RUN:   Grep "_OPERATIONS_SOURCE|operations\.py" tests/
   FOUND: test_ad1270e2e_operations_models.py:53 (path), :574 (import scan), :631 and :644 (selector); test_ad1246_long_run_units.py:364 and test_bf890_command_env.py:5 (docstrings)
   HOLDS: yes
A5 CLAIM: the roadmap has no AD-1328 row
   RUN:   Grep "AD-1328|#1530" docs/development/roadmap.md
   FOUND: none
   HOLDS: yes
A6 CLAIM: no checker treats execution/ or config_models/ as a ranked layer
   RUN:   Read tests/test_layer_boundaries.py:16-27, :137-165; scripts/check_architecture_principles.py:1132-1141
   FOUND: LAYER_MAP and the ranks list neither package; unmapped files return None and are skipped
   HOLDS: yes
A7 CLAIM: the config checks never enumerate config_models classes that probos.config does not import
   RUN:   Grep "reachab|orphan|every model" scripts/check_config_*.py; Grep "ClassDef|unexported" scripts/check_config_facade.py
   FOUND: only SystemConfig-rooted walks (profiles :12, :149) and the facade's vars(probos.config) (:1020)
   HOLDS: yes
```

## Prior Art and Blind Spots

- **Internal.** `docs/research/codex-harness-absorption.md` rows 2 and 3 (`:15-16`) are the absorption decision this AD executes, including Codex `prompt` mapped to escalation (Design Principle 13(c)). `docs/research/openhands-absorption.md:39` records the same stance: policy and services gate, the chain of command decides, no waiting human. BF-890's literal-twin pattern (`operations.py:14-24`) fixed the models' placement (D2).
- **OpenAI Codex `execpolicy`** ([README](https://github.com/openai/codex/tree/main/codex-rs/execpolicy), fetched 2026-10-16: "Tokens are matched in order; any `pattern` element may be a list to denote alternatives"; "The effective `decision` is the strictest severity across all matches (`forbidden` > `prompt` > `allow`)"; examples "validated at load time (think of them as unit tests)"; "basename fallback is only allowed for listed absolute paths"; with no match "`matchedRules` is an empty array and `decision` is omitted"). **Adopted:** prefix with alternatives, strictest wins, every match listed, examples as load-time tests. **Adapted:** `prompt` becomes `escalate`; justification required and the alternative a separate required field for `forbid` (Codex puts it in the justification, optionally); restrictive rules always match by basename while `allow` rules need a bare name or a pinned resolved path; no match takes a declared `unmatched_decision` rather than an omitted decision. **Rejected:** the Starlark policy language (#1530 requires Pydantic models).
- **Codex `command_canonicalization.rs`** ([source](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/src/command_canonicalization.rs), fetched 2026-10-16; the helpers it calls were not read, so its handling of `sh -c` and `cmd /c` is not known): a single plain command becomes its argv; otherwise a bash script becomes `[__codex_shell_script__, mode, script]` and a PowerShell one `[__codex_powershell_script__, script]`. **Adopted** as D6, **adapted** in two ways: the argv key resolves the program, and the script key drops the `-lc`/`-c` mode (both run the same script text).
- **Claude Code permission rules** ([docs](https://code.claude.com/docs/en/permissions), fetched 2026-10-16): separators `&&`, `||`, `;`, `|`, `|&`, `&` and newlines; "When `&&` or `||` has nothing after it ... unparseable"; deny and ask rules apply inside a subshell or command substitution; wrappers `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob` stripped, `command -v` not; "An allow rule won't match past an assignment of any other variable. A deny or ask rule matches past any leading assignment"; documented gaps: `Bash(curl *)` does not stop `/usr/bin/curl` or `sh -c 'curl ...'`, and `Bash(git push *)` does not stop `git -C . push`. **Adopted:** the separator set, dangling operators, the wrapper list in bounded forms, the restrictive/permissive asymmetry (without a safe-variable list). **Closed** the two path and `sh -c` gaps, because a forbid rule must not be bypassed by spelling. **Kept** `git -C` as the stated boundary of a prefix language.
- **Cline auto-approve** ([docs](https://docs.cline.bot/features/auto-approve), via search 2026-10-16): no fixed allowlist; the model flags `requires_approval` per command. **Rejected** as the gate (model judgement is AD-1330's reviewer, not a policy). Absorbed as a blind spot: NVD CVE-2026-30312 and CVE-2026-30313 (described by the search result as a derivative's auto-approval missing raw newlines that carry a second command; the NVD page returned no body, so this detail is unverified) -- newline is a separator in every dialect here, and a lone CR or a Unicode line break is unparseable.
- **Python `shlex`.** Rejected: it has no notion of expansion or substitution and would read `$(curl x)` as one literal word.
- **Reference projects** (`docs/research/reference-projects.md`, date used 2026-10-16, 90-day interval). Examined: Cline (overdue; checked, Section 5). Re-checked: Claude Code (not overdue). SWE-agent (overdue): two targeted searches found nothing on its command blocklist, so it was not examined; considered, deferred, and it stays overdue. Aider, Cursor and Goose (overdue): considered, deferred.
- **Blind spots raised by this slice.** (1) The two call sites run different shells on Windows: `cmd.exe` for `RunCommandTool`, PowerShell for `ShellCommandAgent` (`shell_command.py:250`), so a dialect chosen once would mis-read one of them (O-S1-3). (2) `ShellCommandAgent` rewrites the command before running it (`:171`, `:173`), so S2 must judge the rewritten text (O-S1-3). (3) PowerShell reads non-breaking spaces, smart quotes, en dashes and unquoted commas as syntax, so a lexer that treats them as letters is a bypass; they are unparseable. (4) `curl x | sh`: a shell reading from a pipe or a file is unreadable, not unmatched. (5) Windows PowerShell aliases `curl` and `wget` to `Invoke-WebRequest`; a `curl` rule does not catch `iwr`, so the operator lists alternatives. (6) Redirection targets are file writes this policy does not gate; AD-1316 file effects own them. (7) Pinned paths compare as normalised strings; whether S2's resolver follows symlinks is S2's choice (O-S1-5). (8) `max_nesting` bounds substitutions and shell wrappers together, so a deeply wrapped command is unreadable rather than slow.

## Mutation campaign of record

Run once by the orchestrator on the committed S1 tree, after M1-M3 pass. Anchors are single lines that occur exactly once in the named file; replacements are literal. Record the base commit and the sha256 of `src/probos/execution/command_policy.py` and `src/probos/config_models/operations.py`; a later candidate whose two files match reuses this campaign, and one whose files differ reruns the rows anchored in the changed file.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| E1 | command_policy.py | `return max(decisions, key=COMMAND_DECISION_RANK.__getitem__)` | `return min(decisions, key=COMMAND_DECISION_RANK.__getitem__)` | M3 #2 |
| E3 | command_policy.py | `continue  # an expanded word may be anything, so it matches a restrictive rule` | `return None` | M3 #6 (`git push $F`) |
| E4 | command_policy.py | `if len(tokens) < len(rule.pattern) or (segment.assignments and not restrictive):` | `if len(tokens) < len(rule.pattern):` | M3 #6 (`FOO=1 git push`) |
| E5 | command_policy.py | `return None  # a path is another binary than the bare name the rule allows, unless pinned` | `return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, None, False)` | M3 #6 (`./git push`) |
| E6 | command_policy.py | `if resolved is not None and _path_key(resolved, segment.dialect) in pinned:` | `if resolved is not None:` | M3 #8 |
| E7 | command_policy.py | `return posixpath.basename(program) in names` | `return program in names` | M3 #6 (`/usr/bin/git push --force`) |
| E8 | command_policy.py | `return any(windows_program_stem(name) == stem for name in names)` | `return program in names` | M3 #7 |
| E9 | command_policy.py | `return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())` | `return SegmentVerdict(index, segment, unmatched, "unparseable", ())` | M3 #5 |
| E10 | command_policy.py | `return CommandEvaluation("evaluated", config.unparseable_decision, dialect, digest, (), parsed.unparseable)` | `return CommandEvaluation("evaluated", "allow", dialect, digest, (), parsed.unparseable)` | M3 #5 |
| E11a | command_policy.py | `if not config.rules:  # no policy: nothing is parsed or decided` | `if False:` | M3 #1 |
| E11b | command_policy.py | `if not self._config.rules:` | `if False:` | M3 #1 |
| E12 | command_policy.py | `if not self._report.passed:` | `if False:` | M3 #12 |
| E13 | command_policy.py | `return "matches it" if matched else None` | `return None` | M3 #12 `not_match_hits` |
| E14 | command_policy.py | `matched = any(not match.pin_violation for match in own)` | `matched = bool(own)` | M3 #12 `pinned_match_with_bare_name` |
| E15 | command_policy.py | `if op.startswith("<<"):` | `if False:` | M2 #9 (here-document, here-string) |
| E17 | command_policy.py | `if pair in (";;", ";&"):` | `if False:` | M2 #9 (`case`) |
| E18 | command_policy.py | `elif pending is not None:` | `elif False:` | M2 #9 (`nothing after`) |
| E19a | command_policy.py | `self.subs.append(inner)  # its segments are judged too` | `pass` | M2 #7; M3 #4 `posix_substitution` |
| E19b | command_policy.py | `self.subs.append(inner)  # judged like $( )` | `pass` | M2 #7 (`id`) |
| E20 | command_policy.py | `if self.depth >= self.max_nesting:` | `if False:` | M2 #16 (substitution nesting) |
| E21 | command_policy.py | `if len(out) > bounds.max_segments:` | `if False:` | M2 #16 |
| E22 | command_policy.py | `if len(command) > bounds.max_command_chars:` | `if False:` | M2 #16 |
| E23 | command_policy.py | `if (ord(char) < 32 and char not in "\t\n") or ord(char) == 127 or char in _LINE_BREAKS_REFUSED:` | `if False:` | M2 #9 (NUL, CR, U+2028) |
| E24 | command_policy.py | `if _program_name(word.text, dialect) in _OPAQUE_PROGRAMS[dialect]:` | `if False:` | M2 #10 |
| E25 | command_policy.py | `if word.dynamic:  # the shell decides the program` | `if False:` | M2 #10 (`$X arg`, `& $x`) |
| E26 | command_policy.py | `if len(args) == 2 and args[0] in _POSIX_SCRIPT_FLAGS and readable:` | `if False:` | M2 #14; M3 #4 `posix_wrapper` |
| E27 | command_policy.py | `return f"{head!r} runs commands the policy cannot see unless they are an inline script it unwraps"` | `return None` | M2 #10 (`bash script.sh`, `sh`); M3 #4 `posix_pipe_to_shell` |
| E28 | command_policy.py | `while words and words[0].assignment:` | `while False:` | M2 #12; M3 #6 (`FOO=1 git push --force`) |
| E29 | command_policy.py | `_PROCESS_WRAPPERS: Final = frozenset({"time", "nohup", "noglob", "builtin", "command", "nice", "timeout", "stdbuf"})` | `_PROCESS_WRAPPERS: Final = frozenset()` | M2 #13 |
| E31 | command_policy.py | `_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v1\x00"` | `_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v2\x00"` | M1 #11 |
| E32 | command_policy.py | `_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v1\x00"` | `_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v2\x00"` | M2 #21 |
| E33 | command_policy.py | `if wrapper is None and _is_simple(segment):` | `if wrapper is None:` | M2 #20 |
| E34 | command_policy.py | `return _path_key(resolved, segment.dialect)` | `return _program_name(program, segment.dialect)` | M2 #19 |
| E41 | command_policy.py | `if "--%" in text:` | `if False:` | M2 #9 (`stop-parsing`) |
| E42 | command_policy.py | `elif ch in _PS_REFUSED or ch.isspace():` | `elif ch in _PS_REFUSED:` | M2 #9 (U+00A0) |
| E43 | command_policy.py | `elif ch in "()":  # cmd grouping` | `elif False:` | M2 #9 (cmd `(a)`) |
| E44 | command_policy.py | `if type(dialect) is not str or dialect not in DIALECTS:` | `if False:` | M2 #1 |
| E45 | command_policy.py | `return "cmd" if (sys.platform if platform is None else platform) == "win32" else "posix"` | `return "posix"` | M2 #1 |
| E46 | command_policy.py | `if ch in "*?[{}" or (ch == "~" and self._start < 0):` | `if False:` | M2 #8 (glob, tilde, brace) |
| E47 | command_policy.py | `if end < limit and self.text[end] == "%" and end > at + 1:` | `if False:` | M2 #8 (`%PATH%`) |
| E50 | command_policy.py | `if segment.depth >= bounds.max_nesting:` | `if False:` | M2 #16 (wrapper nesting) |
| R1 | operations.py | `if self.decision == "forbid" and self.alternative is None:` | `if False:` | M1 #3 |
| R2 | operations.py | `COMMAND_DECISION_RANK: dict[str, int] = {"allow": 0, "escalate": 1, "forbid": 2}` | `COMMAND_DECISION_RANK: dict[str, int] = {"allow": 0, "escalate": 2, "forbid": 1}` | M3 #2 (forbid over escalate); M1 #8 |
| R3 | operations.py | `if rule.decision != "allow":` | `if False:` | M1 #5 `on_forbid` |
| R4 | operations.py | `if windows_program_stem(pin) != windows_program_stem(program):` | `if False:` | M1 #5 `basename_mismatch` |
| R5 | operations.py | `if self.unmatched_decision is None:` | `if False:` | M1 #8 `rules_without_unmatched` |
| R6 | operations.py | `if self.unparseable_decision == "allow":` | `if False:` | M1 #8 `unparseable_allow` |
| R7 | operations.py | `if COMMAND_DECISION_RANK[self.unparseable_decision] < COMMAND_DECISION_RANK[self.unmatched_decision]:` | `if False:` | M1 #8 `unparseable_looser_than_unmatched` |

No mutant above can loop: each replaced condition falls through to a branch that advances the cursor. Equivalent-mutant note: E10's killer must evaluate a whole-line unparseable command (`echo "x`), and E9's a segment-level one (`eval x`), with `unmatched="allow"` and `unparseable_decision="escalate"` so the two decisions differ.

## Milestones

| M | Scope | Calls (about) |
|---|---|---|
| Install | Sections 1-5 by script, ledger regeneration (orchestrator) | n/a |
| M1 | `tests/test_ad1328_s1_policy_models.py` | 60 |
| M2 | `tests/test_ad1328_s1_command_parse.py` | 150 |
| M3 | `tests/test_ad1328_s1_policy_evaluation.py`, then the focused gate (acceptance 8) | 130 |
| Campaign | the table above, once, on the committed tree | n/a |

=== BUILDER BRIEFS ===

### Brief M1 -- `tests/test_ad1328_s1_policy_models.py`

Write tests only; never edit `src/`. Target: `probos.config_models.operations` (`CommandPolicyRule`, `CommandPolicyConfig`, `COMMAND_DECISION_RANK`, `windows_program_stem`) and `probos.execution.command_policy.policy_digest` / `POLICY_DIGEST_SCHEME`. Implement M1 #1-14 from `prompts/ad-1328-s1-command-policy-core.md` ("Tests"). Build models with `model_validate` from plain dicts. Refusals are `pydantic.ValidationError`; assert the phrase the contract names is in `str(exc)` and, for rule-level refusals, the rule's name too. For #11 compute the expected digest in the test with `hashlib` and `probos.federation.ard.jcs.canonicalize`; never call `policy_digest` to build the expectation. #13 pins that S1 is off the config surface. Mutants this file must kill: R1, R3, R4, R5, R6, R7, E31. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_policy_models.py -q -n 0`. Stop and report if a test cannot pass against the installed source; do not weaken it.

### Brief M2 -- `tests/test_ad1328_s1_command_parse.py`

Write tests only; never edit `src/`. Target: `probos.execution.command_policy` (`parse_command`, `default_dialect`, `canonical_command`, `CanonicalCommand`, `CANONICAL_KEY_SCHEME`, `CommandSegment`, `ParsedCommand`). Implement M2 #1-21. Pass `dialect=` explicitly everywhere except M2 #1, so the file passes on Linux and Windows. Write shell text with raw strings or explicit escapes and assert on `tokens`, `dynamic`, `assignments`, `redirections`, `wrappers`, `depth`, `dialect` and `unparseable` (a substring of the reason). #9 cases have `segments == ()`; #10 cases parse with `unparseable is None` and set the segment's `unparseable`. #17 is a time bound (2.0 s per case) on 65,536-character inputs with `limits=CommandPolicyConfig(max_command_chars=65536)`. For #21 compute the expected key with `hashlib` and `canonicalize`. Mutants this file must kill: E15, E17-E29, E32-E34, E41-E47, E50. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_command_parse.py -q -n 0`. Stop and report a source defect rather than weakening a test; a tokenizer that reads a command differently from the shell is a finding, not a test to relax.

### Brief M3 -- `tests/test_ad1328_s1_policy_evaluation.py`

Write tests only; never edit `src/`. Target: `probos.execution.command_policy` (`evaluate_command`, `self_test`, `CommandPolicy`, `CommandPolicySelfTestError`, `CommandEvaluation`, `RuleMatch`, `SegmentVerdict`, `SelfTestReport`, `policy_digest`, `canonical_command`). Use the `_policy` / `_rule` helpers from the contract's Tests rules (copy them). Implement M3 #1-17. Pass `dialect=` explicitly. Resolvers are dict lookups (`{"git": "/usr/bin/git"}.get`). #16 is an AST scan of `src/probos` with non-vacuity controls in `tmp_path`; follow the shape of `tests/test_ad1288_s1_commission_chain.py:576-660` (copy, do not import). #17 parses the module's own source. Mutants this file must kill: E1, E3-E14, E19a, E26-E28, R2. Then run the focused gate (contract acceptance 8): the three AD-1328 files, then the listed neighbour tests, then the five `--check` scripts, and report every count and exit code.

## Amendments after install (orchestrator, 2026-10-16)

Deviations from the text above, made after the contract was installed and its first test pass, each with its evidence. Where the installed code or tests differ from the sections above, they are authoritative.

- **A1 -- PowerShell backtick escapes (D3, Quoting).** D3 says a backtick escapes one character. Measured on pwsh 7.6.7 and Windows PowerShell 5.1.26100, in a bare word and inside double quotes: `0 a b f n r t v` after a backtick expand in both, `e` only in 7, and `u{67}` is `g` in 7 but the text `u{67}` in 5.1; every other printable ASCII character is the plain next character. Reading ``u{67}it`` as `u{67}it` let `& "`u{67}it" push --force` evade a `git push --force` rule on the `pwsh -Command` path (`ShellCommandAgent` runs 5.1, where it is not an escape). A backtick before `0 a b e f n r t u v` is now unparseable (`_PS_EXPANDING_ESCAPES`, `_PowerShellLexer._refuse_expanding_escape`, called from `_escape` and `_double_quoted`), reason "the PowerShell escape '`X', which expands to another character"; every other escape, single-quoted text and the trailing-backtick reason are unchanged. Found by the M2 Builder, reproduced by the orchestrator.
- **A2 -- `canonical_command` depth (D6).** D6 and the docstring say wrappers are unwrapped at most `max_nesting` times; the Section 3 loop unwrapped `max_nesting + 1`. It now stops at `max_nesting`, as `parse_command` does, so a line the parser refuses for nesting keys as a script holding the text at the limit.
- **A3 -- Test deviations.** M3 #16 counts `policy_digest` only where it is imported, because `authority.py:743` binds a local of that name; the other five names keep the full rule. M2 #10's cited inputs (`$X arg`, `& $x`) do not kill E25 (they stay unparseable, with another reason), so M2 adds dynamic programs with literal text (`$D/git`, `g$X`, `%X%\git`, `& $d/git`) and pins the reason; M3 #5 kills E25 as well. In `cmd`, `;` is a literal and an unparseable program word, so the `cmd` compound rows use `&` where D3 lists `;`. M1 gained boundary rows for the model bounds the first pass left unpinned (pattern word 256, prose 500, pin path 1,024, words per position 32, pins 16, control characters).
- **A4 -- New S1 -> S2 obligation, O-S1-11.** An `escalate` that comes from an unmatched or unparseable segment has an empty `governing` (no rule decided it), so the escalation seam must carry the segment `reason` and the verdict kind into the approval request and the AD-1224 / AD-1316 records; otherwise the approver sees an escalation with no cause.
- **A5 -- Mutation rows added to the campaign of record.** E51 (drop the `_escape` check), E52 (drop the `_double_quoted` check), E53 (drop one letter from `_PS_EXPANDING_ESCAPES`, ten sub-rows), E54 (widen the set to `N`), E55 (canonical guard `depth < max_nesting` replaced by `True`).
