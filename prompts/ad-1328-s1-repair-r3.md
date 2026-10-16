# AD-1328 S1 repair r3 -- review round 3: governed programs in argument words, relative paths as pin proof, unprovable pins

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY, gated by measurement M1 (below) before the Builder starts. Amends `prompts/ad-1328-s1-repair-r2.md` and r1 to r1e (see "Amendments"). Every SEARCH was read in the worktree as it is now and occurs once. No new AD or BF number (#1530).
**Dependencies:** r2 installed, with its tests (the r2 block of `tests/test_ad1328_s1_command_parse_repair.py` ends at `:1318`). The brake decision for this round: `logs/architect/ad1328-s1-brake-r3-out.txt` (#1530, comment 6223260220).
**Estimated tests:** about +75 cases (3 generated cases of 7,200 evaluations each, 16 named-agent cases, 4 review forms, 11 shell rows, 7 single tests, 21 relative-path rows, 1 construction test, 8 pin-model rows, 1 live test); 3 existing rows edited (Part A).

Verified against (staged blobs, `git ls-files -s`; base `26250c9c`, HEAD `ab925d69`, no unstaged change to these files):

| File | Blob |
|---|---|
| `src/probos/execution/command_policy.py` | `f2a21c321ab2c1100f75a790dc73bec61c0f9de2` |
| `src/probos/config_models/operations.py` | `d74fb9b36d4674d2ba0804325a1d566026ea05c1` |
| `tests/test_ad1328_s1_command_parse_repair.py` | `4f7cb9c3f42504006d59164087d0b9a9e6db8263` |
| `tests/test_ad1328_s1_policy_evaluation.py` | `6b028ea87850b0398d1c736145b6d5f4126c25e4` |
| `tests/test_ad1328_s1_policy_models.py` | `1161155e73425e6737537e6e08e2b6b6e823b308` |
| `tests/test_ad1328_s1_shell_oracle.py` | `c5bd3a8b6048303ff5f7d6793fed5599587290f8` |
| `tests/fixtures/ad1328_shell_oracle.json` | `0d307979a7008068a453d985f288f132f6ffd06d` (unchanged by r3) |
| `DECISIONS.md` | `16c42b6887a42d5de7c875fb9d421543629800de` |

If a blob differs, re-grep each SEARCH before installing.

## Problem

GPT-6.1 Sol, review round 3, a delta review of r2 (`logs/architect/ad1328-s1-review-r3-report.md`; evidence `logs/architect/review3-evidence/`). Three findings, all executed, none a regression except F3.

| F | What the policy does | What runs |
|---|---|---|
| F1 (P1) | `ssh-agent printf x` under `forbid ["printf"]`, `unmatched_decision: allow`: `ssh-agent` is in no table (`_LAUNCHERS_EVERYWHERE`, `command_policy.py:166-183`), so the segment is unmatched and **allowed** (`_judge`, `:1614-1626`) | `printf`, on bash, dash, cmd, PowerShell 5.1 and pwsh 7 (`launcher_property.py`); the real S2a gate let it run |
| F2 (P1) | A pin `/Users/.../root_pin_receiver.cmd` under cmd, and the line `cd /d C:\ & "\Users\...\root_pin_receiver.cmd"`: `_allow_match` (`:1585-1594`) compares `_path_key` values and never asks `_is_absolute` (`:1034`), so the root-relative program "proves" the pin and is **allowed** | the receiver on the new drive (`root_pin_property.py`) |
| F3 (P2, regression from r2) | A pin `/opt/../usr/bin/git`: `_path_key` gives None (`:1044`) and r2 drops it (`:1592`), so the rule can never allow; `self_test` judges examples only (`:1700-1706`), so with no example, or only `not_match` ones, `CommandPolicy` builds (`examples_checked=0`) and startup passes | every `git` command the rule was meant to allow is forbidden; contradicts `prompts/ad-1328-s1-repair-r2.md:984` (blind spot 4) |

## Decisions

**D-r3-1 Governed programs in argument words (F1).** The brake decision stands: the launcher table is frozen, and the class closes with one structural rule and a declared boundary. Options for where the check lives: (a) in `parse_command` / `_launcher_problem`, (b) in `_judge`. (a) is impossible without breaking the config-independence of `parse_command` and `canonical_command` (S2b's key), because the rule needs the policy's restrictive rules. **Decided: (b).** The rule, exactly:

- **Which segments.** Every segment `_judge` receives that the parser could read (`segment.unparseable is None`), so after leading assignments are popped, process wrappers stripped and shell wrappers replaced by their scripts' segments; substitution bodies are segments of their own. Only when the policy has a restrictive (`escalate` or `forbid`) rule.
- **Which words.** `tokens[at]` for every `at` from `start` to the last word, where `start` is 1, or the length of the longest pattern of an `allow` rule that matched this segment without a pin violation (the words the operator's own `allow` pattern names are what the operator allowed: `allow ["git", "rm"]` exempts `rm` in `git rm x`, never the words after it). Option words are words like any other: `-q` names no program, so it never fires. A literal word after a dynamic one is read (each position stands alone). Quoted words count: `tokens` holds the word after quote removal. A dynamic word is read by its literal text (`/usr/bin/curl$X` reads as `curl`), which only adds refusals; what its computed value names is boundary (a).
- **Name.** `windows_program_stem(tokens[at])`, the normaliser `_program_matches` already applies to a restrictive rule's program (`:1525`) in every dialect: basename on both separators, lower case, without `.exe .com .bat .cmd`.
- **Shell.** The name is in `_ARGUMENT_SHELLS = _POSIX_SHELLS | _PS_SHELLS | _OTHER_SHELLS | {"cmd"}`: refused. A shell's script is one word (`ssh-agent bash -c 'printf x'`, `x cmd /c "printf x"`), which the whole-word rule cannot see, and the policy reads a shell's script only when the shell is the program.
- **Governed program.** A restrictive rule whose program (any alternative of `pattern[0]`, by the same stem) equals the name **and** whose whole pattern matches from `at`, with the unchanged `_restrictive_cover` (`:1529-1548`) on a view of the segment that starts at `at`: a later literal word must equal the pattern word, a one-word dynamic word can be it, a variadic word can be every word still wanted. `forbid ["git","push","--force"]` fires on `x git push --force` and not on `echo git`. The anchor is never position 0: `_match` reads the program.
- **Outcome.** The segment's verdict has basis `unparseable`, `segment` replaced by one whose `unparseable` names the argument position, the word as written, and the rule or "a shell" (texts below); `matches` keeps the rules that matched the program; `decision` is the strictest of `unparseable_decision` and those matches. So the hidden word never weakens a decision (`rm -rf curl` under `forbid rm` and `forbid curl` stays `forbid`), never uses the hidden rule's own decision (matching at an argument shows the program could be started there, not that it is), and is never `allow` (`unparseable_decision` cannot be `allow` when rules exist, `operations.py:235-239`). `governing` and S2a's causes then carry the program's rule and the reason that names the argument's rule.
- **Reason texts** (substrings the tests pin): `argument {at} ({raw}) may be a program that rule {name!r} governs, started by {program!r}` and `argument {at} ({raw}) may be a shell that {program!r} starts; the policy does not read what it runs`.
- **Cost.** One stem and one dict lookup per word, against an index of restrictive rules by program stem built once per evaluation. Only a word whose stem names a restrictive program runs `_restrictive_cover`, on a view no longer than the longest such pattern (at most 32 words), so the work is linear in the words: at most `W x k x P` steps, `W` the words (at most `max_command_chars / 2`), `k` the restrictive rules for one program, `P` their pattern length (at most 32). The first refusal returns. The index costs one stem per alternative of each restrictive rule's program (at most 256 x 32). Measured in M4, not claimed.
- **What it costs.** Under any policy with a restrictive rule: an argument word that is a shell (`which bash`, `apt install zsh`, `git config core.editor bash`) escalates; so does a word that starts a governed pattern (`echo curl`, `man curl`, `git rm x` under `forbid ["rm"]`). The operator's remedy for a subcommand is an `allow` rule naming it (`allow ["git", "rm"]`). `docker exec x bash` is already refused (`_SUBCOMMAND_LAUNCHERS`). Usability only.
- **Pins and examples.** A pinned `allow` that proves its program exempts its own pattern words; a pin violation is a `forbid`, exempts nothing and stays the decision. `self_test` judges rule matches, and the rule adds and removes no `RuleMatch`, so no `match` or `not_match` example changes its result (H3).

**Declared boundary** (text B; used once, verbatim, in the module docstring, in `DECISIONS.md` and in the round-4 brief; only line breaks and backtick style differ):

> Declared boundary: a prefix rule does not see a program named (a) by a word the shell computes (a variable, a substitution, a glob) beyond that word's literal text; (b) inside a larger word: a command string, an option value or a configuration entry (`hyperfine 'printf x'`, `--exec=printf`, `git -c alias.x=!printf`); (c) by another program's files, interpreters or configuration (`python -c`, `make`, a script); (d) by any spelling that running it directly would also escape, such as a renamed copy of its binary; nor options placed before a subcommand (`git -C . push`). So a deny-list `forbid` (`unmatched_decision: allow`) is best effort. An allow-list (`unmatched_decision` `escalate` or `forbid`) is the sound mode: a program no rule allows is never allowed, though an allowed program keeps whatever reach it has to start others.

(b) is not closed by splitting words: `hyperfine "p''rintf x"` runs `printf` through a shell's quote removal, so any splitter is another open-world table. The module docstring's "every launcher this module does not unwrap is unparseable" (`:45-46`) was false and is replaced (Section 1).

**D-r3-2 A relative path proves no pin (F2).** In `_allow_match`, after the program is resolved (written path or resolver answer) and before any pin compare: `resolved` not `_is_absolute` in the segment's dialect gives a pin violation with the reason `'{resolved}' is not an absolute path, so the file it names depends on where the command runs`. And the pinned set is built by one helper, `_pin_keys(pins, dialect)`: the `_path_key` of each pin that is absolute in the dialect (a POSIX `/usr/bin/git` is root-relative to cmd.exe). Either change alone closes F2: a relative key never equals an absolute one (POSIX absolute keys start with `/`; Windows ones with a drive or `\\`). The first gives the reason; the second is shared with D-r3-3 (one definition of "a pin that can prove"). **`lookup_changed`:** unchanged and orthogonal. A bare name in a changed context is still refused as "not proven"; a written path is judged by its own text whatever the line did before, so `cd /d C:\ & \x\r.cmd` is refused as not absolute and `cd x & C:\x\r.cmd` keeps its proof. **Canonical key:** unchanged. A relative program already has a `script` key (r2, `_canonical_program`, `:1799-1800`), and a relative resolver answer already leaves the name key (`:1802`).

**D-r3-3 Pins that cannot prove (F3).**
(a) **Parse time** (`operations.py`, `_check_pins`): a pin with a `.` or `..` component, split on `/` and `\` (both forms, every platform, since the model does not know the dialect), is refused: `{where}: host_executable path {pin!r} has a '.' or '..' component; write the path without them`. Dots inside a name (`/usr/bin.d/git`, `..git`) are not components. A device path `\\.\C:\...` is refused too (its `.` is a component); write the drive path.
(b) **Construction**, options: (i) a new exception type; (ii) a `ValueError` raised in `CommandPolicy.__init__` before `self_test`; (iii) a self-test failure of a new kind. (i) and (ii) change S2a's handling and are invisible to its doctor, which calls `self_test` and never builds a `CommandPolicy` (`prompts/ad-1328-s2a-command-policy-wiring.md:495-498`). **Decided: (iii).** `self_test` reports, under its dialect, every pinned rule with no pin in `_pin_keys`: `SelfTestFailure(rule, "host_executable", ", ".join(pins), observed)`. `SelfTestFailure.expectation` widens to `Literal["match", "not_match", "host_executable"]` (additive), and `message` gives `rule 'git-ok': host_executable /usr/bin/git names no absolute path for cmd.exe, so the rule can never allow 'git' here; add the path 'git' runs from on this platform (one rule may list a POSIX path and a Windows path)`. `CommandPolicy` already raises `CommandPolicySelfTestError` for any failure, so S2a's startup stops with that text, and its doctor shows it through `failure.message` (S2a `:1128`). `examples_checked` still counts examples only. **Cross-platform:** a rule listing `/usr/bin/git` and `C:\Program Files\Git\cmd\git.exe` builds under every dialect; a rule listing only the other platform's form is refused at construction on this platform. That is intended: S2a builds one policy per serving dialect of its platform (`:526-529`), and such a rule could never allow anything there. `evaluate_command` (no self-test) fails closed: the rule just never allows.

**D-r3-4 Delivery.** Sections 1-13 are fenced pairs for `install_fenced_pairs.py` (source, `operations.py`, `DECISIONS.md`); no fixture change. The orchestrator installs them and runs M1 **before** the Builder. The Builder writes tests only (R3-M2). The usability corpus is never edited: the Builder runs it, and if a row fails it stops and reports. The real-child premise is a live test in the oracle file, not a fixture row: the oracle's row machinery finds probe segments by their program (`tests/test_ad1328_s1_shell_oracle.py:101-112`), and here the probe would be an argument. **Public API:** unchanged except the additive `SelfTestFailure.expectation` value and the `SegmentVerdict` combination "basis `unparseable` with non-empty `matches`". **Requested amendments:** S2a, four (H4-H7); S2b, none (keys unchanged, H8).

**Captain:** none. Every decision adds a refusal or a startup error and weakens no check. The round-4 scope reading in "Round-4 brief" (a command inside the declared boundary is not a P1 against this contract) applies the brake decision recorded on #1530; the Captain may overrule both.

## Section 1 -- `src/probos/execution/command_policy.py` (module docstring)

SEARCH:
```python
A prefix rule does not see a program started through another program's arguments,
files or configuration (``find -exec``, ``python -c``, ``git -c alias.x=!cmd``,
``make``) or options placed before a subcommand (``git -C . push``): that is the
boundary of a prefix-rule language (#1530, Do Not Build). A program whose purpose is
to start a program its arguments name is a launcher, and every launcher this module
does not unwrap is unparseable. Nothing here launches a process, reads the
environment or touches a file, and nothing under ``src/`` constructs this policy
yet: AD-1328 S2 wires it before broker admission.
```
REPLACE:
```python
Programs started by other programs (S1 repair r3). A launcher in this module's
table, a shell it does not unwrap and a subcommand launcher are unparseable wherever
they are the program. Any other program may start a program its arguments name, so
restrictive rules also read each argument word as if it began a command: when a
restrictive rule matches from that word (the program's normaliser and matcher), or
the word names a shell, the segment is unparseable and takes ``unparseable_decision``,
or the stricter decision of a rule matching its program. Words an ``allow`` rule's
own pattern names are exempt.

Declared boundary: a prefix rule does not see a program named (a) by a word the
shell computes (a variable, a substitution, a glob) beyond that word's literal text;
(b) inside a larger word: a command string, an option value or a configuration entry
(``hyperfine 'printf x'``, ``--exec=printf``, ``git -c alias.x=!printf``); (c) by
another program's files, interpreters or configuration (``python -c``, ``make``, a
script); (d) by any spelling that running it directly would also escape, such as a
renamed copy of its binary; nor options placed before a subcommand (``git -C .
push``). So a deny-list ``forbid`` (``unmatched_decision: allow``) is best effort. An
allow-list (``unmatched_decision`` ``escalate`` or ``forbid``) is the sound mode: a
program no rule allows is never allowed, though an allowed program keeps whatever
reach it has to start others (#1530, Do Not Build). Nothing here launches a process,
reads the environment or touches a file, and nothing under ``src/`` constructs this
policy yet: AD-1328 S2 wires it before broker admission.
```

## Section 2 -- `command_policy.py` (constant `_ARGUMENT_SHELLS`)

SEARCH:
```python
_PROCESS_WRAPPERS: Final = frozenset({"command", "nice", "nohup", "stdbuf", "time", "timeout"})
```
REPLACE:
```python
_PROCESS_WRAPPERS: Final = frozenset({"command", "nice", "nohup", "stdbuf", "time", "timeout"})
# r3: every name a shell is known by. Named as an argument it runs a script the policy does not read (review r3, F1).
_ARGUMENT_SHELLS: Final = _POSIX_SHELLS | _PS_SHELLS | _OTHER_SHELLS | {"cmd"}
```

## Section 3 -- `command_policy.py` (`SegmentVerdict` docstring)

SEARCH:
```python
    """The decision for one segment: by ``rule`` match, ``unmatched`` or ``unparseable``."""
```
REPLACE:
```python
    """The decision for one segment: by ``rule`` match, ``unmatched`` or ``unparseable``.

    r3: when an argument word may start a program a restrictive rule governs, or a shell, the basis is
    ``unparseable`` and ``segment.unparseable`` names the word, its position and the rule. ``matches`` still lists the
    rules that match the segment's program, and ``decision`` is the strictest of theirs and ``unparseable_decision``.
    """
```

## Section 4 -- `command_policy.py` (`SelfTestFailure`)

SEARCH:
```python
class SelfTestFailure:
    """One example that does not hold for its rule."""

    rule: str
    expectation: Literal["match", "not_match"]
    example: str
    observed: str

    @property
    def message(self) -> str:
        return f"rule {self.rule!r}: {self.expectation} example {self.example!r} {self.observed}"
```
REPLACE:
```python
class SelfTestFailure:
    """One example that does not hold for its rule; or (r3, ``expectation`` ``host_executable``) a pinned rule none of
    whose paths can prove its program under the dialect, ``example`` then listing the paths."""

    rule: str
    expectation: Literal["match", "not_match", "host_executable"]
    example: str
    observed: str

    @property
    def message(self) -> str:
        if self.expectation == "host_executable":
            return f"rule {self.rule!r}: host_executable {self.example} {self.observed}"
        return f"rule {self.rule!r}: {self.expectation} example {self.example!r} {self.observed}"
```

## Section 5 -- `command_policy.py` (`SelfTestReport`, `CommandPolicySelfTestError` docstrings)

SEARCH (5a):
```python
    """Every rule's examples judged under one dialect."""
```
REPLACE:
```python
    """Every rule's examples, and every pinned rule's paths (r3), judged under one dialect. ``examples_checked``
    counts the examples only."""
```

SEARCH (5b):
```python
    """A policy whose examples do not hold under its dialect; at startup, a startup error."""
```
REPLACE:
```python
    """A policy whose examples do not hold, or with a pinned rule none of whose paths can prove its program (r3),
    under its dialect; at startup, a startup error."""
```

## Section 6 -- `command_policy.py` (`_pin_keys`)

SEARCH:
```python
    return ntpath.normcase(ntpath.normpath(path))
```
REPLACE:
```python
    return ntpath.normcase(ntpath.normpath(path))


def _pin_keys(pins: tuple[str, ...], dialect: Dialect) -> frozenset[str]:
    """r3 (review r3, F2, F3): the keys of the pins that can prove a program under ``dialect``. A pin counts only when it
    is absolute there (a POSIX ``/usr/bin/git`` is root-relative to cmd.exe) and normalises (``_path_key``)."""
    return frozenset(key for pin in pins if _is_absolute(pin, dialect) and (key := _path_key(pin, dialect)) is not None)
```

## Section 7 -- `command_policy.py` (`_allow_match`, F2)

SEARCH:
```python
    pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable} - {None}  # r2: a pin with '..' proves nothing
    if resolved is not None and _path_key(resolved, segment.dialect) in pinned:
```
REPLACE:
```python
    if resolved is not None and not _is_absolute(resolved, segment.dialect):  # r3: a relative path proves no pin
        why = f"{resolved!r} is not an absolute path, so the file it names depends on where the command runs"
        return _pin_violation(rule, prefix, index, resolved, why, paths)
    pinned = _pin_keys(rule.host_executable, segment.dialect)
    if resolved is not None and _path_key(resolved, segment.dialect) in pinned:
```

## Section 8 -- `command_policy.py` (`_restrictive_index`, `_hidden_program`, `_judge`; F1)

SEARCH:
```python
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
```
REPLACE:
```python
_RestrictiveIndex = dict[str, tuple[CommandPolicyRule, ...]]


def _restrictive_index(config: CommandPolicyConfig) -> _RestrictiveIndex:
    """r3: the restrictive rules by the program name each matches (``windows_program_stem`` of each alternative), in rule
    order; empty when the policy has no restrictive rule."""
    index: dict[str, list[CommandPolicyRule]] = {}
    for rule in config.rules:
        if rule.decision == "allow":  # r3: an allow rule hides nothing
            continue
        for name in dict.fromkeys(windows_program_stem(option) for option in _options(rule.pattern[0])):
            index.setdefault(name, []).append(rule)
    return {name: tuple(rules) for name, rules in index.items()}


def _hidden_program(governed: _RestrictiveIndex, segment: CommandSegment, start: int) -> str | None:
    """r3 (review r3, F1): why an argument word may start a program the policy governs, or None.

    Each word from ``start`` (at least 1: ``_match`` reads the program) is read as if it began a command: its text (a
    dynamic word's literal text) normalised as a restrictive rule normalises a program. The segment is unreadable when
    that name is a shell, or when a restrictive rule for it matches from that word with ``_restrictive_cover``. A
    pattern covers at most its own length of words, so each view is that long and the work is linear in the words.
    """
    tokens = segment.tokens
    for at in range(start, len(tokens)):
        name = windows_program_stem(tokens[at])
        if name in _ARGUMENT_SHELLS:
            return f"argument {at} ({segment.raw[at]}) may be a shell that {tokens[0]!r} starts; the policy does not read what it runs"
        rules = governed.get(name, ())
        if not rules:
            continue
        end = at + max(len(rule.pattern) for rule in rules)
        view = replace(segment, tokens=tokens[at:end], dynamic=segment.dynamic[at:end], variadic=segment.variadic[at:end])
        hit = next((rule for rule in rules if _restrictive_cover(rule.pattern, view) is not None), None)
        if hit is not None:
            return f"argument {at} ({segment.raw[at]}) may be a program that rule {hit.name!r} governs, started by {tokens[0]!r}"
    return None


def _judge(
    config: CommandPolicyConfig,
    segment: CommandSegment,
    index: int,
    unmatched: CommandDecisionName,
    resolve: ProgramResolver | None,
    governed: _RestrictiveIndex,
) -> SegmentVerdict:
    if segment.unparseable is not None:
        return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())
    matches = tuple(found for rule in config.rules if (found := _match(rule, segment, index, resolve)) is not None)
    if governed:
        # r3: the words an allow rule's own pattern names are what the operator allowed; the reading starts after them
        start = max((len(match.matched_prefix) for match in matches if match.decision == "allow"), default=1)
        hidden = _hidden_program(governed, segment, start)
        if hidden is not None:
            decision = _strictest((config.unparseable_decision, *(match.decision for match in matches)))
            return SegmentVerdict(index, replace(segment, unparseable=hidden), decision, "unparseable", matches)
    if not matches:
```

## Section 9 -- `command_policy.py` (`_evaluate`)

SEARCH:
```python
    verdicts = tuple(_judge(config, segment, index, unmatched, resolve) for index, segment in enumerate(parsed.segments))
```
REPLACE:
```python
    governed = _restrictive_index(config)
    verdicts = tuple(
        _judge(config, segment, index, unmatched, resolve, governed) for index, segment in enumerate(parsed.segments)
    )
```

## Section 10 -- `command_policy.py` (`self_test`, F3)

SEARCH:
```python
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
```
REPLACE:
```python
    No program resolver is used, so a pinned rule's examples name absolute paths
    and the result does not depend on the host. A pinned rule none of whose
    ``host_executable`` paths is absolute under ``dialect`` fails too (r3): it could
    never allow its program, whether or not it has examples. Never raises for a
    failing example: ``CommandPolicy`` turns a failed report into an error.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    digest = policy_digest(config)
    failures: list[SelfTestFailure] = []
    checked = 0
    for rule in config.rules:
        if rule.host_executable and not _pin_keys(rule.host_executable, chosen):  # r3: review r3, F3
            program = rule.pattern[0]
            failures.append(SelfTestFailure(
                rule.name,
                "host_executable",
                ", ".join(rule.host_executable),
                f"names no absolute path for {_DIALECT_NAMES[chosen]}, so the rule can never allow {program!r} here; "
                f"add the path {program!r} runs from on this platform (one rule may list a POSIX path and a Windows path)",
            ))
        for expectation, examples in (("match", rule.match), ("not_match", rule.not_match)):
```

## Section 11 -- `command_policy.py` (`CommandPolicy` docstring)

SEARCH:
```python
    Construction runs ``self_test`` and raises ``CommandPolicySelfTestError`` (a
    ``ValueError``) naming each failing rule and example, so a policy whose
    examples are wrong cannot be built; AD-1328 S2 builds it at startup, where a
```
REPLACE:
```python
    Construction runs ``self_test`` and raises ``CommandPolicySelfTestError`` (a
    ``ValueError``) naming each failing rule and example, or a pinned rule with no
    path absolute under the dialect (r3), so a policy whose examples are wrong, or
    whose pins could never prove, cannot be built; AD-1328 S2 builds it at startup, where a
```

## Section 12 -- `src/probos/config_models/operations.py` (`_check_pins`, F3)

SEARCH:
```python
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
            raise ValueError(f"{where}: host_executable path {pin!r} is not an absolute path")
```
REPLACE:
```python
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
            raise ValueError(f"{where}: host_executable path {pin!r} is not an absolute path")
        if any(part in (".", "..") for part in re.split(r"[\\/]", pin)):
            # AD-1328 S1 r3 (review r3, F3): such a pin is not canonical, and a POSIX '..' is resolved after symbolic
            # links, so it might never prove its program. Write the path without '.' and '..' components.
            raise ValueError(f"{where}: host_executable path {pin!r} has a '.' or '..' component; write the path without them")
```

## Section 13 -- `DECISIONS.md`

SEARCH:
```
Contracts `prompts/ad-1328-s1-repair-r1.md` to `prompts/ad-1328-s1-repair-r2.md`.
```
REPLACE:
```
Review round 3 (r3) kept the launcher table frozen and added one rule: restrictive rules also read each argument word as if it began a command (the program's normaliser and matcher; words an allow rule's own pattern names are exempt), and a shell named as an argument is unparseable, so the segment takes `unparseable_decision` or a stricter decision of a rule matching its program. A program path proves a pin only when it is absolute in the dialect; a pin with a `.` or `..` component is refused when the policy is read, and a pinned rule with no path absolute in the policy's dialect fails its self-test, which stops startup. Declared boundary: a prefix rule does not see a program named (a) by a word the shell computes (a variable, a substitution, a glob) beyond that word's literal text; (b) inside a larger word: a command string, an option value or a configuration entry (`hyperfine 'printf x'`, `--exec=printf`, `git -c alias.x=!printf`); (c) by another program's files, interpreters or configuration (`python -c`, `make`, a script); (d) by any spelling that running it directly would also escape, such as a renamed copy of its binary; nor options placed before a subcommand (`git -C . push`). So a deny-list `forbid` (`unmatched_decision: allow`) is best effort. An allow-list (`unmatched_decision` `escalate` or `forbid`) is the sound mode: a program no rule allows is never allowed, though an allowed program keeps whatever reach it has to start others. Contracts `prompts/ad-1328-s1-repair-r1.md` to `prompts/ad-1328-s1-repair-r3.md`.
```

## Measurements (the orchestrator; none is claimed here)

| Id | When | What | Expected | If not |
|---|---|---|---|---|
| M1 | After installing Sections 1-13, before R3-M2 | The five `tests/test_ad1328_s1_*.py` files at `-n 0`; list every failure by node id | Exactly Part A's three: `test_finding_refusals[f9_ps_provider_alias]`, `test_r1b_refusals[r1b_ps_dynamic_provider]` (`...repair.py:814`), `test_r2_a_posix_path_with_dotdot_proves_no_pin`. All 93 `test_usability_corpus` rows pass | Send the list; the Architect amends Part A. Nobody edits the corpus |
| M2 | Same tree | The S2a starter (Section 14 of the S2a prompt) under `self_test` in all three dialects, as `boundary_inventory.py` C does | 27 example checks, 0 failures | Report |
| M3 | After R3-M2 | Wall time of `test_r3_argument_words_are_read_as_commands[*]` | Under 20 s per dialect on the Captain's host | Report; the Architect samples names per combination (still at least 200 names) |
| M4 | Same | `evaluate_command` time for `"git push " * 900` (posix, 8,100 characters) under 20 restrictive `git` rules of 5 words, and for a 65,536-character line with `max_command_chars=65536` | Linear: well under 1 s each | Report |
| M5 | Same | The review's probes: `launcher_property.py`, `root_pin_property.py`, `probe_r3_f3.py`; `boundary_inventory.py` F3 universe | The first two fail their bypass assertion (decision no longer `allow`); `probe_r3_f3.py` prints model refusals for the `..` pins, construction refusals for (cmd, `/usr/bin/git`) and (posix, `C:\...`), and stops at its line 45 (model refusal); the F3 universe's `missing` is empty | Report |
| M6 | A POSIX host with `ssh-agent` (CI or a Linux scratch) | `test_r3_ssh_agent_runs_its_argument_as_a_child` | Passes; on Windows it skips with the POSIX-rows reason | Report the stdout and stderr |
| M7 | Same | The differential harness at the capped worker count | Unchanged from r2 (r3 changes no parse): 0 real mismatches | Report |
| M8 | R3-M3 | M145-M173 and the full `command_policy.py` campaign rerun | Each killed or listed as equivalent | Stop and report the survivor |
| M9 | Against S2a | S2a's suite with this module | Passes, apart from H4-H7 | Send failures for the S2a repair |

## Tests (milestone R3-M2, Builder, tests only)

### Part A -- existing tests that change

| File:line (blob above) | Change | Why |
|---|---|---|
| `test_ad1328_s1_command_parse_repair.py:255` (`f9_ps_provider_alias`) | neighbour `"Set-Item x curl"` -> `"Set-Item x zqecho"` | r3 reads argument 2: under `_deny_curl` the neighbour now escalates, and the neighbour must be allowed (`:307-309`) |
| `...repair.py:797` (`r1b_ps_dynamic_provider`) | neighbour `"Set-Item x* curl"` -> `"Set-Item x* zqecho"` | same |
| `...repair.py:1266-1267` (`test_r2_a_posix_path_with_dotdot_proves_no_pin`, the dotted pin) | Replace the two lines with: comment `# r3: a '..' pin is refused when the policy is read (review r3, F3), so it never reaches evaluation`, then `with pytest.raises(ValueError, match=r"has a '\.' or '\.\.' component"):` / `    _r2_policy(_r2_pinned("git", "/opt/../usr/bin/git"))` | R3-3a. The written-path rows above it (`:1261-1265`) stay and still kill M133 |
| Any other failure M1 lists | None until the Architect amends this table | -- |

### Part B1 -- appended to `tests/test_ad1328_s1_command_parse_repair.py` (after the r2 block)

Imports, in the top block: `import random` after `import re`; `CommandPolicy` added to the `probos.execution.command_policy` import. No private name is imported: "in no table" is proven by behaviour (`_r3_untabled`).

```python
# --------------------------------------------------------------------------------------
# r3 (prompts/ad-1328-s1-repair-r3.md) -- adversarial review round 3, F1
#   Restrictive rules read every argument word as if it began a command; a shell named as an argument is refused.
#   The launcher table is frozen: the property uses generated names that no table of the module refuses or marks.
# --------------------------------------------------------------------------------------

_R3_GOVERNED = "may be a program that rule"
_R3_SHELL = "may be a shell that"


def _r3_policy(*rules: dict[str, Any]) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate(
        {"rules": list(rules), "unmatched_decision": "allow", "unparseable_decision": "escalate"}
    )


def _r3_rule(name: str, pattern: list[Any], decision: str, **extra: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {"name": name, "pattern": pattern, "decision": decision, "justification": "r3", **extra}
    if decision == "forbid":
        rule["alternative"] = "other"
    return rule


_R3_NO_PRINTF = _r3_rule("no-printf", ["printf"], "forbid")


def _r3_untabled(name: str) -> bool:
    """True when every dialect reads ``{name} x`` as an ordinary program: no launcher, shell, keyword, wrapper or mutator
    table refuses, strips or marks it, and it is not a cmd internal (those get a script key)."""
    for dialect in DIALECTS:
        parsed = parse_command(f"{name} x", dialect=dialect)
        if parsed.unparseable is not None or len(parsed.segments) != 1:
            return False
        (segment,) = parsed.segments
        if segment.unparseable is not None or segment.tokens != (name, "x") or segment.lookup_changed is not None:
            return False
        if canonical_command(f"{name} x", dialect=dialect).kind != "argv":
            return False
    return True


def _r3_names(count: int = 200, seed: int = 13283) -> tuple[str, ...]:
    rng = random.Random(seed)
    names: dict[str, None] = {}
    while len(names) < count:
        name = "zq" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
        if _r3_untabled(name):
            names[name] = None
    return tuple(names)


R3_NAMES = _r3_names()
_R3_LAUNCHER_SPELLINGS: dict[str, tuple[str, ...]] = {
    "posix": ("{n}", "/opt/r3/bin/{n}", "'/opt/r3 tools/{n}'"),
    "cmd": ("{n}", "C:\\r3\\bin\\{n}.exe", '"C:\\r3 tools\\{n}.exe"'),
    "powershell": ("{n}", "C:\\r3\\bin\\{n}.exe", "& 'C:\\r3 tools\\{n}.exe'"),
}
_R3_OPTIONS = ("", " -q", " -q --zz")
_R3_HEADS: dict[str, tuple[str, ...]] = {
    "posix": ("printf", "/usr/bin/printf", "PRINTF.Exe"),
    "cmd": ("printf", "C:\\r3\\bin\\printf.exe", "PRINTF.Exe"),
    "powershell": ("printf", "C:\\r3\\bin\\printf.exe", "PRINTF.Exe"),
}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_r3_argument_words_are_read_as_commands(dialect: Dialect) -> None:
    # Review r3, F1: `ssh-agent printf x` was allowed while `printf x` was forbidden. 200 seeded names in no table,
    # crossed with each launcher spelling, 0-2 option words and each spelling of the forbidden head.
    policy = CommandPolicy(_r3_policy(_R3_NO_PRINTF), dialect=dialect)
    assert len(R3_NAMES) == 200 and all(_r3_untabled(name) for name in R3_NAMES)  # premise
    for head in _R3_HEADS[dialect]:
        assert policy.evaluate(f"{head} x").decision == "forbid", head  # control: each head is forbidden directly
    failures: list[tuple[str, object, object]] = []
    for name in R3_NAMES:
        for spelling in _R3_LAUNCHER_SPELLINGS[dialect]:
            launcher = spelling.format(n=name)
            for options in _R3_OPTIONS:
                control = policy.evaluate(f"{launcher}{options} zqecho x")  # control: an ungoverned child is allowed
                if control.decision != "allow":
                    failures.append((f"{launcher}{options} zqecho x", control.decision, control.unparseable))
                    continue
                expected = f"argument {1 + len(options.split())} ("
                for head in _R3_HEADS[dialect]:
                    command = f"{launcher}{options} {head} x"
                    result = policy.evaluate(command)
                    reasons = [str(verdict.segment.unparseable) for verdict in result.segments]
                    held = any(expected in reason and "rule 'no-printf'" in reason for reason in reasons)
                    if result.decision != "escalate" or not held:
                        failures.append((command, result.decision, reasons))
    assert failures == [], failures[:10]


R3_REAL_LAUNCHERS = ("ssh-agent", "gpg-agent", "ssh-pageant", "runcon")


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("name", R3_REAL_LAUNCHERS)
def test_r3_the_reviewed_agents_do_not_allow_a_forbidden_child(name: str, dialect: Dialect) -> None:
    # Review r3, F1 CLASS: the documented command-argument forms of these four (ssh-agent's child was executed).
    config = _r3_policy(_R3_NO_PRINTF)
    assert evaluate_command(config, f"{name} zqecho x", dialect=dialect).decision == "allow"  # control
    result = evaluate_command(config, f"{name} printf x", dialect=dialect)
    assert result.decision == "escalate"
    (verdict,) = result.segments
    assert verdict.basis == "unparseable" and _R3_GOVERNED in str(verdict.segment.unparseable)


R3_REVIEW_FORMS: list[tuple[str, Dialect, str]] = [
    # launcher_property.py executed these: the child ran (exit 0, its marker printed) while the policy said allow
    ("posix", "posix", "/usr/bin/ssh-agent /usr/bin/printf '\\002O'"),
    ("cmd", "cmd", '"C:\\Program Files\\Git\\usr\\bin\\ssh-agent.exe" /usr/bin/printf "\\002O"'),
    ("powershell", "powershell", "& 'C:\\Program Files\\Git\\usr\\bin\\ssh-agent.exe' /usr/bin/printf '\\002O'"),
    ("powershell_agent", "powershell", "& 'C:\\Program Files\\Git\\usr\\bin\\ssh-agent.exe' /usr/bin/printf ordinary-child"),
]


@pytest.mark.parametrize(("dialect", "command"), [pytest.param(*row[1:], id=row[0]) for row in R3_REVIEW_FORMS])
def test_r3_the_review_forms_escalate(dialect: Dialect, command: str) -> None:
    result = evaluate_command(_r3_policy(_R3_NO_PRINTF), command, dialect=dialect)
    assert result.unparseable is None  # premise: the line is read
    (verdict,) = result.segments
    assert verdict.segment.tokens[1] == "/usr/bin/printf"  # premise
    assert result.decision == "escalate"
    assert "argument 1 (/usr/bin/printf)" in str(verdict.segment.unparseable)


R3_SHELL_ARGUMENTS: list[tuple[str, Dialect, str, str]] = [
    # (id, dialect, a shell named as an argument, the same line with an ungoverned word)
    ("posix_bash_c", "posix", "ssh-agent bash -c 'printf x'", "ssh-agent zqecho -c 'zqecho x'"),
    ("posix_sh_script", "posix", "zqlaunch sh script.sh", "zqlaunch zqecho script.sh"),
    ("posix_dash_path", "posix", "zqlaunch /bin/dash -c x", "zqlaunch /bin/zqecho -c x"),
    ("posix_other_shell_last", "posix", "zqlaunch zsh", "zqlaunch zqecho"),
    ("posix_which", "posix", "which bash", "which zqecho"),
    ("cmd_cmd_string", "cmd", 'zqlaunch cmd /c "printf x"', 'zqlaunch zqecho /c "zqecho x"'),
    ("cmd_pwsh_suffix", "cmd", "zqlaunch PWSH.EXE -Command x", "zqlaunch ZQECHO.EXE -Command x"),
    ("cmd_wsl", "cmd", "zqlaunch wsl x", "zqlaunch zqecho x"),
    ("ps_powershell", "powershell", "zqlaunch powershell -Command x", "zqlaunch zqecho -Command x"),
    ("ps_quoted_pwsh_path", "powershell", "zqlaunch 'C:\\Program Files\\PowerShell\\7\\pwsh.exe' -c x", "zqlaunch 'C:\\Program Files\\PowerShell\\7\\zqecho.exe' -c x"),
    ("ps_bash", "powershell", "zqlaunch bash -c x", "zqlaunch zqecho -c x"),
]


@pytest.mark.parametrize(
    ("dialect", "command", "neighbour"), [pytest.param(*row[1:], id=row[0]) for row in R3_SHELL_ARGUMENTS],
)
def test_r3_a_shell_named_as_an_argument_is_refused(dialect: Dialect, command: str, neighbour: str) -> None:
    deny = _r3_policy(_R3_NO_PRINTF)
    assert evaluate_command(deny, neighbour, dialect=dialect).decision == "allow"  # control first
    _accepted(command, dialect)  # premise: the parser reads the line; the refusal below is r3's
    result = evaluate_command(deny, command, dialect=dialect)
    assert result.decision == "escalate"
    assert any(_R3_SHELL in str(verdict.segment.unparseable) for verdict in result.segments)


def test_r3_allow_pattern_words_are_exempt() -> None:
    forbid_rm = _r3_rule("no-rm", ["rm"], "forbid")
    plain = _r3_policy(_r3_rule("git-ok", ["git"], "allow"), forbid_rm)
    result = evaluate_command(plain, "git rm x", dialect="posix")
    (verdict,) = result.segments
    assert (result.decision, verdict.basis) == ("escalate", "unparseable")
    assert "argument 1 (rm)" in str(verdict.segment.unparseable)
    assert [match.rule for match in verdict.matches] == ["git-ok"]  # the program's own match is kept
    named = _r3_policy(_r3_rule("git-rm-ok", ["git", "rm"], "allow"), forbid_rm)
    assert evaluate_command(named, "git rm x", dialect="posix").decision == "allow"  # the operator allowed `git rm`
    after = evaluate_command(named, "git rm rm", dialect="posix")  # the exemption ends with the allow rule's words
    assert after.decision == "escalate" and "argument 2 (rm)" in str(after.segments[0].segment.unparseable)


def test_r3_a_pin_violation_does_not_exempt() -> None:
    config = _r3_policy(
        _r3_rule("git-rm-ok", ["git", "rm"], "allow", host_executable=["/usr/bin/git"]), _r3_rule("no-rm", ["rm"], "forbid"),
    )
    assert evaluate_command(config, "/usr/bin/git rm x", dialect="posix").decision == "allow"  # control: a proven pin
    result = evaluate_command(config, "/tmp/evil/git rm x", dialect="posix")
    (verdict,) = result.segments
    assert (result.decision, verdict.basis) == ("forbid", "unparseable")
    assert [(match.rule, match.pin_violation) for match in verdict.matches] == [("git-rm-ok", True)]
    assert "argument 1 (rm)" in str(verdict.segment.unparseable)


def test_r3_a_forbidden_program_keeps_its_forbid() -> None:
    config = _r3_policy(_r3_rule("no-rm", ["rm"], "forbid"), _r3_rule("no-curl", ["curl"], "forbid"))
    result = evaluate_command(config, "rm -rf curl", dialect="posix")
    (verdict,) = result.segments
    assert (result.decision, verdict.decision, verdict.basis) == ("forbid", "forbid", "unparseable")
    assert [match.rule for match in result.governing] == ["no-rm"]
    assert "argument 2 (curl)" in str(verdict.segment.unparseable)


def test_r3_a_rule_matches_from_the_argument_with_its_whole_pattern() -> None:
    config = _r3_policy(_r3_rule("no-rm-rf", ["rm", "-rf"], "forbid"))
    assert evaluate_command(config, "rm -rf x", dialect="posix").decision == "forbid"  # control
    assert evaluate_command(config, "zqlaunch rm x", dialect="posix").decision == "allow"  # as `rm x` itself: no match
    for dialect, command in (
        ("posix", "zqlaunch rm -rf x"),
        ("posix", "zqlaunch rm $X"),  # a variadic word can be `-rf`: the same matcher as for the program
        ("cmd", "zqlaunch -q rm -rf"),
        ("powershell", "zqlaunch RM.exe -rf x"),
    ):
        result = evaluate_command(config, command, dialect=dialect)
        assert result.decision == "escalate", (dialect, command)
        assert "rule 'no-rm-rf'" in str(result.segments[0].segment.unparseable), (dialect, command)


def test_r3_rule_alternatives_and_spellings() -> None:
    config = _r3_policy(_r3_rule("no-fetchers", [["Curl", "wget.exe"]], "forbid"))
    for dialect, command in (
        ("posix", "zqlaunch curl x"),
        ("cmd", "zqlaunch WGET x"),
        ("powershell", "zqlaunch 'C:\\x\\Curl.EXE' x"),
        ("posix", "zqlaunch /usr/bin/curl$X"),  # a dynamic word is read by its literal text
    ):
        assert evaluate_command(config, "zqlaunch zqecho x", dialect=dialect).decision == "allow"  # control
        result = evaluate_command(config, command, dialect=dialect)
        assert result.decision == "escalate", (dialect, command)
        assert "rule 'no-fetchers'" in str(result.segments[0].segment.unparseable), (dialect, command)


def test_r3_only_restrictive_rules_read_arguments() -> None:
    mixed = _r3_policy(_r3_rule("git-ok", ["git"], "allow"), _R3_NO_PRINTF)
    assert evaluate_command(mixed, "zqlaunch printf x", dialect="posix").decision == "escalate"  # control
    assert evaluate_command(mixed, "zqlaunch git status", dialect="posix").decision == "allow"  # an allow rule hides nothing
    # With no restrictive rule there is nothing a word could hide, so no argument is read, not even a shell. An allowed
    # program keeps its own reach: the declared boundary's last sentence.
    allow_list = CommandPolicyConfig.model_validate(
        {"rules": [_r3_rule("zq-ok", ["zqlaunch"], "allow")], "unmatched_decision": "escalate"}
    )
    assert evaluate_command(allow_list, "zqecho x", dialect="posix").decision == "escalate"  # control: an allow-list
    assert evaluate_command(allow_list, "zqlaunch bash -c x", dialect="posix").decision == "allow"
```

### Part B2 -- appended to `tests/test_ad1328_s1_policy_evaluation.py`

It reuses `_policy`, `_rule`, `_resolver`; `CommandPolicy`, `CommandPolicySelfTestError`, `evaluate_command` and `self_test` are imported already.

```python
# --------------------------------------------------------------------------------------
# r3 (prompts/ad-1328-s1-repair-r3.md) -- review round 3, F2 (relative paths) and F3 (pins that cannot prove)
# --------------------------------------------------------------------------------------

_R3_PINS = ["C:\\r3\\receiver.cmd", "/r3/receiver.cmd", "/r3/receiver"]

R3_RELATIVE_PROGRAMS: list[tuple[str, str, str, str | None]] = [
    # (id, dialect, command, the resolver's answer for `receiver`, or None for no resolver)
    ("cmd_root_relative", "cmd", "\\r3\\receiver.cmd x", None),
    ("cmd_root_relative_after_drive_change", "cmd", "cd /d C:\\ & \\r3\\receiver.cmd x", None),  # review r3, F2
    ("cmd_root_relative_dotdot", "cmd", "\\x\\..\\r3\\receiver.cmd x", None),
    ("cmd_drive_relative", "cmd", "C:r3\\receiver.cmd x", None),
    ("cmd_drive_relative_after_drive_change", "cmd", "cd /d C:\\ & C:r3\\receiver.cmd x", None),
    ("cmd_dot_relative", "cmd", ".\\r3\\receiver.cmd x", None),
    ("cmd_parent_relative", "cmd", "..\\r3\\receiver.cmd x", None),
    ("cmd_resolver_root_relative", "cmd", "receiver x", "\\r3\\receiver.cmd"),
    ("cmd_resolver_root_relative_slash", "cmd", "receiver x", "/r3/receiver.cmd"),
    ("cmd_resolver_drive_relative", "cmd", "receiver x", "C:r3\\receiver.cmd"),
    ("cmd_resolver_dot_relative", "cmd", "receiver x", ".\\receiver.cmd"),
    ("ps_root_relative", "powershell", "\\r3\\receiver.cmd x", None),
    ("ps_root_relative_slash", "powershell", "/r3/receiver.cmd x", None),
    ("ps_drive_relative", "powershell", "C:r3\\receiver.cmd x", None),
    ("ps_dot_relative", "powershell", ".\\r3\\receiver.cmd x", None),
    ("ps_after_location_change", "powershell", "cd C:\\; \\r3\\receiver.cmd x", None),
    ("ps_resolver_root_relative", "powershell", "receiver x", "\\r3\\receiver.cmd"),
    ("posix_dot_relative", "posix", "./r3/receiver x", None),
    ("posix_relative", "posix", "r3/receiver x", None),
    ("posix_parent_relative", "posix", "../r3/receiver x", None),
    ("posix_resolver_relative", "posix", "receiver x", "r3/receiver"),
]


@pytest.mark.parametrize(
    ("dialect", "command", "answer"), [pytest.param(*row[1:], id=row[0]) for row in R3_RELATIVE_PROGRAMS],
)
def test_r3_a_relative_program_path_proves_no_pin(dialect: str, command: str, answer: str | None) -> None:
    config = _policy(_rule("receiver-ok", ["receiver"], "allow", host_executable=_R3_PINS), unmatched="escalate")
    absolute = "/r3/receiver" if dialect == "posix" else "C:\\r3\\receiver.cmd"
    assert evaluate_command(config, f"{absolute} x", dialect=dialect).decision == "allow"  # control: written absolute
    resolved = evaluate_command(config, "receiver x", dialect=dialect, resolve_program=_resolver({"receiver": absolute}))
    assert resolved.decision == "allow"  # control: a resolver's absolute answer
    resolve = None if answer is None else _resolver({"receiver": answer})
    result = evaluate_command(config, command, dialect=dialect, resolve_program=resolve)
    assert result.unparseable is None, result.unparseable  # premise: the line is read
    (verdict,) = [v for v in result.segments if "receiver" in v.segment.tokens[0]]
    assert verdict.segment.unparseable is None  # premise: read, so the forbid below is the pin check
    (match,) = verdict.matches
    assert (match.decision, match.pin_violation) == ("forbid", True)
    assert "is not an absolute path" in match.justification, match.justification
    assert result.decision == "forbid"


def test_r3_a_pin_no_path_of_the_dialect_can_prove_fails_construction() -> None:
    windows = "C:\\Program Files\\Git\\cmd\\git.exe"
    both = _policy(_rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git", windows]), unmatched="escalate")
    for dialect in ("posix", "cmd", "powershell"):
        assert CommandPolicy(both, dialect=dialect).configured is True  # control: one rule lists both platforms' paths
    unc = _policy(_rule("git-ok", ["git"], "allow", host_executable=["//server/share/git"]), unmatched="escalate")
    assert self_test(unc, dialect="cmd").passed is True  # control: '//server/share' is absolute in both
    for dialect, pins, named in (
        ("cmd", ["/usr/bin/git"], "cmd.exe"),
        ("powershell", ["/usr/bin/git"], "PowerShell"),
        ("posix", [windows], "a POSIX shell"),
        ("posix", ["\\\\server\\share\\git.exe"], "a POSIX shell"),
    ):
        for examples in ({}, {"not_match": ["git status"]}):  # the review: no example, or only not_match ones
            config = _policy(_rule("git-ok", ["git"], "allow", host_executable=pins, **examples), unmatched="escalate")
            report = self_test(config, dialect=dialect)
            assert report.examples_checked == len(examples.get("not_match", []))
            assert report.passed is False
            first = report.failures[0]
            assert (first.rule, first.expectation, first.example) == ("git-ok", "host_executable", ", ".join(pins))
            assert first.message.startswith(f"rule 'git-ok': host_executable {', '.join(pins)} names no absolute path for {named}")
            with pytest.raises(CommandPolicySelfTestError) as raised:
                CommandPolicy(config, dialect=dialect)
            text = str(raised.value)
            for needle in ("git-ok", dialect, "add the path 'git' runs from", first.message):
                assert needle in text, needle
```

### Part B3 -- appended to `tests/test_ad1328_s1_policy_models.py`

It reuses `_pinned`, `_value_error`, `_PIN_POSIX`, `_PIN_DRIVE`, `_PIN_UNC` (`:218-224`).

```python
# r3 (prompts/ad-1328-s1-repair-r3.md) -- review round 3, F3: a pin is written without '.' and '..' components


@pytest.mark.parametrize(
    "pin",
    [
        "/opt/../usr/bin/git",
        "/usr/./bin/git",
        "/usr/bin/../bin/git",
        "C:\\tools\\..\\git.exe",
        "C:\\tools\\.\\git.exe",
        "C:/tools/../git.exe",
        "\\\\server\\share\\..\\git.exe",
        "\\\\.\\C:\\tools\\git.exe",
    ],
)
def test_r3_a_pin_with_a_dot_component_is_refused(pin: str) -> None:
    for good in (_PIN_POSIX, _PIN_DRIVE, _PIN_UNC, "/usr/bin.d/git", "C:\\tools\\..git\\git.exe"):  # dots inside names
        assert CommandPolicyRule.model_validate(_pinned([good])).host_executable == (good,)  # control
    message = _value_error(CommandPolicyRule, _pinned([pin]))
    assert "has a '.' or '..' component" in message
    assert "command policy rule 'git-status'" in message
```

### Part C -- appended to `tests/test_ad1328_s1_shell_oracle.py`

Imports: add `CommandPolicyConfig` to the `probos.config_models.operations` import and `evaluate_command` to the `probos.execution.command_policy` import.

```python
def test_r3_ssh_agent_runs_its_argument_as_a_child(tmp_path: Path) -> None:
    """Review r3, F1 (executed with Git for Windows' ssh-agent under bash, dash, cmd, PowerShell 5.1 and pwsh 7,
    2026-10-16, ``launcher_property.py``): ssh-agent runs the program its arguments name. The policy part runs on every
    host. The live part runs where POSIX rows run (off Windows: MSYS transport is not the reference), with bash,
    ssh-agent and printf on PATH; otherwise it skips and names the cause."""
    config = CommandPolicyConfig.model_validate(
        {
            "rules": [{"name": "no-printf", "pattern": ["printf"], "decision": "forbid", "justification": "r3", "alternative": "other"}],
            "unmatched_decision": "allow",
            "unparseable_decision": "escalate",
        }
    )
    text = "ssh-agent printf R3CHILD"
    assert evaluate_command(config, "printf R3CHILD", dialect="posix").decision == "forbid"  # control
    assert evaluate_command(config, text, dialect="posix").decision == "escalate"
    reason = _live_skip_reason({"text": text, "requires": ["ssh-agent", "printf"]}, "bash", paths=("python", "probe.py"))
    if reason is not None:
        pytest.skip(reason)
    completed = _run_shell("bash", text, dict(os.environ), tmp_path)
    assert (completed.returncode, completed.stdout) == (0, "R3CHILD"), completed.stderr  # the premise: the child ran
```

Run at `-n 0`: the five `tests/test_ad1328_s1_*.py` files. All must pass (POSIX live rows and the Part C live part skip on Windows).

## Mutation campaign (rows added; each anchor is one line, unique after r3)

In every table cell, `\|` is the Markdown escape for a literal `|`; type `|`. `command_policy.py` and `operations.py` change, so the whole `command_policy.py` campaign is rerun on the committed tree (r1 rule), plus M145-M173. Record the base commit and the sha256 of each file; mark it the campaign of record.

| Id | File | Anchor | Mutant | Killer |
|---|---|---|---|---|
| M145 | command_policy.py | `_ARGUMENT_SHELLS: Final = _POSIX_SHELLS \| _PS_SHELLS \| _OTHER_SHELLS \| {"cmd"}` | `_ARGUMENT_SHELLS: Final = frozenset()` | `test_r3_a_shell_named_as_an_argument_is_refused[*]` |
| M146 | command_policy.py | same | drop `\| {"cmd"}` | `...refused[cmd_cmd_string]` |
| M147 | command_policy.py | `if name in _ARGUMENT_SHELLS:` | `if False:` | shell rows |
| M148 | command_policy.py | `rules = governed.get(name, ())` | `rules = ()` | `test_r3_argument_words_are_read_as_commands[*]`; agents; review forms |
| M149 | command_policy.py | `if not rules:` | `if False:` | every r3 test (`max()` of nothing raises) |
| M150 | command_policy.py | `end = at + max(len(rule.pattern) for rule in rules)` | `end = at + 1` | `test_r3_a_rule_matches_from_the_argument_with_its_whole_pattern` |
| M151 | command_policy.py | `hit = next((rule for rule in rules if _restrictive_cover(rule.pattern, view) is not None), None)` | `hit = rules[0]` | same (`zqlaunch rm x` allowed) |
| M152 | command_policy.py | `for at in range(start, len(tokens)):` | `for at in range(start, len(tokens) - 1):` | shell rows `posix_other_shell_last`, `posix_which` |
| M153 | command_policy.py | same | `for at in range(start + 1, len(tokens)):` | generated (no option words); agents |
| M154 | command_policy.py | `if governed:` | `if False:` | every r3 escalation |
| M155 | command_policy.py | same | `if True:` | `test_r3_only_restrictive_rules_read_arguments` (allow-list) |
| M156 | command_policy.py | `start = max((len(match.matched_prefix) for match in matches if match.decision == "allow"), default=1)` | `start = 1` | `test_r3_allow_pattern_words_are_exempt` |
| M157 | command_policy.py | same | `..., default=0)` | evaluation `test_one_forbidden_segment_forbids_the_command` (curl's basis `rule`) |
| M158 | command_policy.py | same | drop `if match.decision == "allow"` | `test_r3_a_pin_violation_does_not_exempt` (basis) |
| M159 | command_policy.py | `hidden = _hidden_program(governed, segment, start)` | `hidden = None` | every r3 escalation |
| M160 | command_policy.py | `decision = _strictest((config.unparseable_decision, *(match.decision for match in matches)))` | `decision = config.unparseable_decision` | `test_r3_a_forbidden_program_keeps_its_forbid`; `test_r3_a_pin_violation_does_not_exempt` |
| M161 | command_policy.py | `return SegmentVerdict(index, replace(segment, unparseable=hidden), decision, "unparseable", matches)` | `return SegmentVerdict(index, segment, decision, "unparseable", matches)` | reason assertions (generated, shells, agents) |
| M162 | command_policy.py | same | `... "unparseable", ())` | `test_r3_a_forbidden_program_keeps_its_forbid` (governing); `test_r3_allow_pattern_words_are_exempt` (matches) |
| M163 | command_policy.py | `if rule.decision == "allow":  # r3: an allow rule hides nothing` | `if False:` | `test_r3_only_restrictive_rules_read_arguments` (`zqlaunch git status`) |
| M164 | command_policy.py | `for name in dict.fromkeys(windows_program_stem(option) for option in _options(rule.pattern[0])):` | `for name in _options(rule.pattern[0]):` | `test_r3_rule_alternatives_and_spellings` |
| M165 | command_policy.py | `return frozenset(key for pin in pins if _is_absolute(pin, dialect) and (key := _path_key(pin, dialect)) is not None)` | drop `_is_absolute(pin, dialect) and` | `test_r3_a_pin_no_path_of_the_dialect_can_prove_fails_construction` |
| M166 | command_policy.py | `if resolved is not None and not _is_absolute(resolved, segment.dialect):  # r3: a relative path proves no pin` | `if False:` | `test_r3_a_relative_program_path_proves_no_pin[*]` (reason) |
| M167 | command_policy.py | `why = f"{resolved!r} is not an absolute path, so the file it names depends on where the command runs"` | `why = f"{resolved!r} is not one of them"` | same |
| M168 | command_policy.py | `if rule.host_executable and not _pin_keys(rule.host_executable, chosen):  # r3: review r3, F3` | `if False:` | construction test |
| M169 | command_policy.py | same | `if not _pin_keys(rule.host_executable, chosen):` | evaluation `test_self_test_passes_and_counts_examples` |
| M170 | command_policy.py | `if self.expectation == "host_executable":` | `if False:` | construction test (`message`) |
| M171 | operations.py | `if any(part in (".", "..") for part in re.split(r"[\\/]", pin)):` | `if False:` | `test_r3_a_pin_with_a_dot_component_is_refused[*]`; repair `test_r2_a_posix_path_with_dotdot_proves_no_pin` (amended) |
| M172 | operations.py | same | `re.split(r"/", pin)` | `...refused[C:\\tools\\..\\git.exe]` and the other backslash rows |
| M173 | operations.py | same | `part == ".."` | `...refused[/usr/./bin/git]`, `[C:\\tools\\.\\git.exe]`, `[\\\\.\\C:...]` |

**Retired:** M142 (its anchor, r2's pinned-set line, is replaced by `_pin_keys`; M165 and M168 cover the helper).

**Equivalent mutants, not listed:**
- `... and (key := _path_key(pin, dialect)) is not None` -> drop the `is not None` test: `_path_key` is None only for a POSIX `..`, which the model now refuses (M171).
- `pinned = _pin_keys(...)` -> r2's set: M166 refuses every relative resolved path first, and no relative key equals an absolute one.

**Earlier killers whose inputs now reach r3 first** (rerun them; a survivor is rewritten, never deleted): killers that assert only a **decision** on a line whose argument words name a governed program or a shell. Suspects: M143's 87 sub-rows (`test_r2_launchers_are_opaque`: its decision line no longer discriminates; its parse-reason line still does), the r1 launcher-table and `_SUBCOMMAND_LAUNCHERS` rows of `test_finding_refusals` (parse reason), `test_r2_terminal_child_is_not_allowed` (reason substring). Rewrite rule for a survivor: replace the governed child by an ungoverned word (`zqecho`), so the decision under the deny-list is `allow` without the old check and `escalate` with it.

## Closure enumeration

| F | Producer or exit | Closed by |
|---|---|---|
| F1 | Words of a posix segment: bare, quoted, escaped, `$`/glob/`~` (dynamic, read by literal text), after leading assignments are popped and process wrappers stripped | `_hidden_program` (Section 8), positions `start..end` |
| F1 | Words of a cmd segment (bare, quoted) and a PowerShell segment (bare, quoted, escaped, wildcard; after `&` the called word is the program) | same |
| F1 | Segments of unwrapped `sh/bash/dash -c`, `cmd /c`, `powershell/pwsh -Command` scripts and of POSIX substitution bodies | Each is a segment `_judge` receives |
| F1 | Position 0 | `_match` (unchanged): never read twice |
| F1 | Words an allow rule's pattern names (proven) | Exempt by the operator's rule; a pin violation exempts nothing (M158) |
| F1 | Spellings: bare, absolute or relative path on either separator, quoted, any case, `.exe .com .bat .cmd` | `windows_program_stem`, as for a restrictive program (`:1525`) |
| F1 | Pattern words after the anchor: literal, one-word dynamic, variadic | `_restrictive_cover` on the view (unchanged matcher) |
| F1 | A shell word: `_POSIX_SHELLS`, `_PS_SHELLS`, `_OTHER_SHELLS`, `cmd`, any spelling | `_ARGUMENT_SHELLS` |
| F1 | A segment the parser already refused | `unparseable_decision`, unchanged (at least as strict) |
| F1 | A policy with no restrictive rule | Not read: nothing is governed |
| F1 | Exits: decision | Strictest of `unparseable_decision` and the program's matches; never `allow` |
| F1 | Exits: S2a | `governing` (the program's rules) and basis `unparseable` with `segment.unparseable` (S2a `_causes`, `:338-350`) |
| F1 | Redirection targets (`> printf`) | Not a word of the command: a file, not a program |
| F1 | Named launchers whose child is dynamic, at position 0 | The frozen table (unchanged) |
| F1 | Everything else | Declared boundary (a)-(d) |
| F2 | `resolved` from a written path (any dialect) | Section 7: not `_is_absolute` -> violation |
| F2 | `resolved` from the resolver (bare name, lookup unchanged) | same |
| F2 | Bare name, lookup changed | Unchanged violation "not proven" |
| F2 | Resolver None, `{}`, omitted; non-str | Unchanged ("does not resolve"; `TypeError`) |
| F2 | Pin keys | `_pin_keys`: absolute in the dialect only |
| F2 | Canonical key | Unchanged (r2: relative -> script; relative answer -> name) |
| F3 | Pin text at parse | Section 12: `.`/`..` components on either separator |
| F3 | Pins at construction, per dialect | Section 10: `SelfTestFailure("host_executable")` -> `CommandPolicySelfTestError` |
| F3 | Exits: `self_test` (S2a doctor), `CommandPolicy` (S2a startup), `evaluate_command` (no self-test) | Report; raise; fails closed (never allows) |

## Round-4 brief (insert verbatim)

> Delta review of `prompts/ad-1328-s1-repair-r3.md` against the r2 candidate. In scope, and only these: (1) a regression introduced by r3; (2) a literal argument word the r3 rule should catch but does not, that is, a whole word at an argument position whose normalised name is a shell, or from which a restrictive rule's pattern matches, while the policy has a restrictive rule and the word is not exempted by a proven `allow` pattern; (3) a program path that is not absolute in the dialect still proving a pin; (4) a pin that can never prove, passing construction. Declared boundary (the policy makes no claim here; a finding inside it is a follow-up, not a P1 against this contract): [text B]. Any other finding needs a new brake decision; there is no automatic round 5.

## Amendments (what r3 overrides)

| Earlier text | r3 |
|---|---|
| Module docstring `:41-46`, "every launcher this module does not unwrap is unparseable"; `find -exec` listed as unseen | False (review r3, F1). Replaced by the argument rule and text B (`find . -exec rm` is now read) |
| r2 D-r2-3 (the launcher table grows by name) | Table frozen; the argument rule closes the class |
| r2 Section 11a, `pinned = {...} - {None}`; mutation M142 | `_pin_keys`; M142 retired |
| r2 blind spot 4 and `prompts/ad-1328-s1-repair-r2.md:984`: "a POSIX pin containing `..` ... its rule's self-test fails at startup" | False (review r3, F3). Refused at parse (Section 12) and at construction (Section 10) |
| r1 R5 pin comparison: normalised paths | Absolute in the dialect only (Sections 6, 7) |
| `SelfTestFailure.expectation`: `match`, `not_match` | Adds `host_executable` |
| `SegmentVerdict`: basis `unparseable` has no matches | It may carry the program's matches (Section 3) |
| Brake: "one real-child oracle row" | A live test in the oracle file (D-r3-4) |

## Hidden pins (enumerated)

| Id | Pin | Where | Effect |
|---|---|---|---|
| H1 | S1 tests that build a pinned `CommandPolicy` or self-test under a mismatched dialect | Absence A1 | None exist |
| H2 | Usability corpus, 93 rows under `_deny_curl` | `...repair.py:628-727`, `:772-775` | No argument word is `curl` or a shell (A2); M1 confirms |
| H3 | Rule examples (S1 tests, S2a starter) | `self_test`, `_example_problem` (`:1671-1685`) | r3 adds and removes no `RuleMatch`; M2 confirms the starter |
| H4 | S2a doctor remediation: "Correct each named rule's pattern or example" | S2a prompt `:1133-1136` | **S2a amendment:** "pattern, example or host_executable path" |
| H5 | S2a startup and doctor text | S2a `:612`, `:1128` | **S2a amendment:** a test that a rule pinned only to the other platform's path stops startup and fails the doctor with the new text (under `platform="win32"` and `"linux"`) |
| H6 | S2a B19 (`tests/test_ad1328_s2a_shell_agent.py:640-655` in the S2a worktree): pins `C:\d1\tool.CMD` and `/d1/tool.CMD` under win32 | S2a worktree | Builds (the drive pin proves). `/d1/tool.CMD` no longer proves under cmd or PowerShell. Refusal unchanged; **S2a amendment:** recheck any justification text it asserts |
| H7 | S2a `_causes` reads basis `unparseable` via `segment.unparseable` and rules via `governing` | S2a `:333-351`; worktree `command_gate.py:236-243` | Holds. **S2a amendment:** no S2a test may assume basis `unparseable` implies `matches == ()`; M9 |
| H8 | S2b key | `canonical_command` | Unchanged: parse and `_canonical_program` untouched |
| H9 | Oracle fixture | `tests/fixtures/ad1328_shell_oracle.json` | Unchanged |
| H10 | S2a replay of `operations.py` | S2a Section 1 anchors: module docstring, the S1 comment `:28-32`, `command_env_passthrough` | No overlap with `_check_pins` (`:106-127`). Lines after `:125` move down by 4; S2a's pairs are text-anchored, so only its cited line numbers shift |

## What This Does NOT Change

Parsing, lexers, `canonical_command` and keys, `CANONICAL_KEY_SCHEME`/`POLICY_DIGEST_SCHEME`, the launcher tables, `_restrictive_cover`, `_match`, `_canonical_program`, the oracle fixture, S2b. Public names and signatures, apart from the additive `SelfTestFailure.expectation` value.

## Tracking

`DECISIONS.md` (Section 13). No PROGRESS or roadmap change (same AD, same PR).

## Acceptance Criteria

- Sections 1-13 are installed exactly; M1 matches Part A, or Part A is amended first.
- Parts A to C are applied; the five files pass at `-n 0`.
- M2-M7 and M9 as stated; M145-M173 killed or listed as equivalent; the rest of the campaign rerun with no survivor.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, blobs above)

```
command_policy.py:41-48     module docstring boundary paragraph (Section 1 SEARCH, once)
command_policy.py:155-161   _POSIX_SHELLS, _PS_SHELLS, _OTHER_SHELLS; :162 _PROCESS_WRAPPERS (Section 2 anchor)
command_policy.py:166-194   _LAUNCHERS_EVERYWHERE, _LAUNCHERS (frozen; untouched)
command_policy.py:209-216   _SUBCOMMAND_LAUNCHERS (docker exec/run)
command_policy.py:283-311   CommandSegment: tokens, dynamic, raw, variadic (one constructor, :1139-1151, sets all)
command_policy.py:345-352   SegmentVerdict (docstring :346); :385-396 SelfTestFailure; :400-409 SelfTestReport; :412-420 error
command_policy.py:1013      default_dialect: "cmd" on win32
command_policy.py:1034-1045 _is_absolute; _path_key (posix '..' -> None at :1044; :1045 the Section 6 anchor)
command_policy.py:1266-1280 _launcher_problem; :1283-1317 _shell_wrapper ("cmd" at :1309)
command_policy.py:1513-1527 _strictest, _options, _program_matches (restrictive: windows_program_stem, :1525)
command_policy.py:1529-1548 _restrictive_cover (reads tokens, dynamic, variadic only)
command_policy.py:1551-1568 _match (`if restrictive:` :1558, so r3 names its flag `governed`)
command_policy.py:1571-1596 _allow_match (:1592-1593 Section 7 anchor; no _is_absolute before r3)
command_policy.py:1614-1626 _judge; :1641 its only caller (_evaluate)
command_policy.py:1671-1707 _example_problem, self_test (:1691-1701 Section 10 anchor)
command_policy.py:1710-1727 CommandPolicy (:1713-1715 Section 11 anchor)
command_policy.py:1794-1806 _canonical_program (unchanged)
operations.py:49-57         windows_program_stem; :106-127 _check_pins (:124-125 Section 12 anchor; `re` imported)
operations.py:235-241       unparseable_decision never allow, and at least as strict as unmatched
repair test:52-72 _deny_curl; :255, :797 neighbours; :301-309 neighbour must be allowed; :628-727 corpus
repair test:1144-1155 _r2_policy, _r2_pinned; :1260-1267 dotted-pin test
evaluation test:40-64 _policy, _rule, _resolver, _only_segment; :565 _pinned_git_rule; :588, :718 pinned posix/posix
models test:45 _rule; :218-224 _PIN_POSIX, _PIN_DRIVE, _PIN_UNC, _pinned; :262 _value_error
oracle test:38-39 imports; :101-112 _probe_segments; :270-300 _live_skip_reason; :303-320 _run_shell
DECISIONS.md:21             "Contracts `...r1.md` to `...r2.md`." (1 occurrence)
S2a prompt:333-351 _causes; :495-498 doctor self_test; :526-529 a CommandPolicy per serving dialect; :1125-1137 doctor text
review3-evidence: launcher_property.py:10-31, root_pin_property.py:7-17, probe_r3_f3.py:22-30 (forms reused in Parts B, C)
```

## Absence Verified (2026-10-16)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | No S1 test builds a pinned `CommandPolicy` or self-test under a dialect its pins cannot prove | Grep `host_executable\|CommandPolicy\(\|self_test\(` in `tests/test_ad1328_s1_*.py` | Pinned constructions: evaluation `:588` (via `:565`, posix), `:718` (posix); every `CommandPolicy(` passes `dialect=`; Windows pins are used only through `evaluate_command` | yes |
| A2 | No usability row has an argument word that is `curl` or a shell | Read `...repair.py:628-727` | none (`C:\...\cmd\git.exe` is a program, position 0) | yes; M1 measures |
| A3 | Deny-list neighbours with `curl` or a shell at an argument | Grep double-quoted strings with a shell name or `curl` after a word, in `tests/test_ad1328_s1_*.py` | `...repair.py:255`, `:797`; the rest are position 0 or inside one word (`echo 'curl x'`, evaluation `:194`) | yes for double-quoted strings; M1 covers the rest |
| A4 | `_judge` has one caller; `_restrictive_cover`, `_path_key` are not called elsewhere in `src/` | Grep `_judge\(\|_restrictive_cover\(\|_path_key\(\|_is_absolute\(` in `src/` | `:1559`, `:1592-1593`, `:1641`, `:1800-1803` | yes |
| A5 | No existing test asserts the old "is not one of them" text for a relative path | Grep `is not one of them` in `tests/` | none | yes |
| A6 | S2a's pinned test configs match their dialect | Grep `host_executable\|platform=` and the pins in `D:\ProbOS-worktrees\ad1328-s2a\tests\test_ad1328_s2a*.py` | gate `:150` `/usr/bin/git` with `linux` (`:428`, `:440`); tool `:503` linux/posix; `:546`, gate `:1159` `C:\tools\git.EXE` with win32; real shells `:192` drive path with win32; agent `:645-652` drive + posix pins with win32 (H6) | yes |
| A7 | S2a reads `SelfTestFailure` only through `.message` | Grep `\.expectation\|SelfTestFailure` in the S2a prompt and its worktree's `src/` | prompt `:1128` (`failure.message`); worktree only its own copy of this module | yes |
| A8 | The new names are free | Grep `_ARGUMENT_SHELLS\|_pin_keys\|_hidden_program\|_RestrictiveIndex\|if governed\|rule\.decision == "allow"` in `src/probos/` | none | yes |

## Not verified

- No Python or shell was run here (the bridge denies both). Every number in "Measurements" is the orchestrator's.
- The staged tree id `ffc0b9e9...` was not recomputed (`git write-tree` is not allowed); the blobs above are from `git ls-files -s`.
- That each Part B line parses as intended (`C:r3\...` under cmd, `cd C:\; ...` under PowerShell, `--zz` under PowerShell): every such test asserts its premise or control first, so a wrong reading fails loudly instead of passing.
- ssh-agent's behaviour on Linux (runs the command, prints nothing else): M6.

## Prior Art and Blind Spots

A repair of a reviewed grammar under a brake decision: no external search, and `docs/research/reference-projects.md` was not consulted. Blind spots, considered and deferred:

1. Command-string runners outside the table (`hyperfine`, `watchexec`, `parallel`, `bsub`): boundary (b). Under a deny-list this stays best effort; text B says so to the operator.
2. Attached option values (`-eprintf`): boundary (b).
3. Table-launcher names at an argument position followed by a dynamic word (`x sudo $Y`): boundary (a), since the dynamic word is in the arguments of a program not in the table. Reading table names at arguments was rejected: it would escalate `npm start`, `docker start`, `git bisect start`.
4. Usability: `git rm` under `forbid ["rm"]`; remedy `allow ["git", "rm"]`. A follow-up may surface this hint in the reason.
5. Device-path pins (`\\.\C:\...`) are now refused; write the drive path.
6. Worst-case cost under an operator-written pathological config (256 rules for one program, 32 words each): M4 measures the realistic case; the config is trusted.

=== BUILDER BRIEFS ===

### Brief R3-M2 -- tests (effort: high, at most 120 calls)

Contract: `prompts/ad-1328-s1-repair-r3.md`. The source, `operations.py` and `DECISIONS.md` are installed and frozen: edit nothing under `src/`, `tests/fixtures/` or in `DECISIONS.md`.

1. First run the five `tests/test_ad1328_s1_*.py` files at `-n 0`. If anything fails that Part A does not name, STOP and report each node id and its message. Do not edit the usability corpus, ever.
2. Apply Part A exactly, row by row.
3. Append Part B1, B2 and B3 to their files and Part C to the oracle file, with the imports each part names.
4. Run the five files at `-n 0`.

If a premise or control assertion fails, stop and report the case and the observed value. Do not weaken an assertion or change a reason substring. Report the counts, the skips with their reasons, and the wall time of `test_r3_argument_words_are_read_as_commands[*]` (M3).

### Brief R3-M3 -- mutation campaign (effort: high, at most 150 calls)

Use the committed R3-M2 tree. Run the baseline green first. Count each anchor: it must occur exactly once. Apply one mutant at a time, with a `.mutbak` restore in `finally`, and run the five files serially. Record the base commit, the sha256 of `command_policy.py`, `operations.py` and each test file, and each result as KILLED / INERT / INVALID with its killer. Rerun the earlier `command_policy.py` rows; for each suspect named under "Earlier killers", record which assertion killed it. If a mutant survives, stop and report it with the test that should have killed it. Do not edit source or the table.

## Amendments after install

None yet.
