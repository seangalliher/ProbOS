"""AD-1328 S1 (#1530), repair round 1, milestone R-M2b -- the closed grammar of ``parse_command``, tested.

Tests only. The contract is ``prompts/ad-1328-s1-repair-r1.md`` (R1-R5; "Tests", R-M2 items 1-7). The repaired parser
reads a construct only when its meaning is modelled; everything else is unparseable and takes ``unparseable_decision``.
This file holds the NEW tests of that grammar; the existing parser tests live in ``test_ad1328_s1_command_parse.py``.

* Every dialect is passed explicitly, so the file passes on Linux and on Windows. Nothing here starts a process, reads
  the environment or touches a file.
* The text under test is written with Python escapes wherever it carries a control character, a line break, a lone
  surrogate or a non-ASCII character (``"\\r\\n"``, ``"\\ud800"``, ``"\\u202e"``, ``"\\u00a0"``), never a literal one, so
  a CRLF checkout or an editor's encoding cannot change what is tested.
* Rule 1 of the contract: every refusal row asserts BOTH the reason substring AND, under the deny-list ``forbid
  ["curl"]`` with ``unmatched_decision="allow"``, an evaluation decision of ``escalate`` (never ``allow``).
* Rule 2 of the contract: a test that pins a reading the shell oracle (``tests/fixtures/ad1328_shell_oracle.json``)
  covers cites the oracle row id in a comment.
* Each test asserts its own premise (what the parser made of the text) and a control (the accepted neighbour, which is
  checked FIRST), so a test cannot pass because the whole machine refuses everything.

Contract tests, in order: ``test_finding_refusals`` (R-M2 #1, 108 rows), ``test_dynamic_word_arity`` (#2; kills M38,
M39, M40), ``test_state_mutators_mark_the_lookup_context`` (#3; kills M11, M15-M17, M20, M49),
``test_unwrapped_segments_inherit_context`` (#4; kills M12-M14),
``test_wrapped_scripts_are_rebuilt_from_the_words_the_launcher_receives`` (#5; kills M18),
``test_canonical_identity_follows_what_runs`` (#6; kills M44-M47) and ``test_usability_corpus`` (#7).
"""

from __future__ import annotations

import random
import re
from typing import Any

import pytest

from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_policy import (
    CanonicalCommand,
    CommandPolicy,
    CommandSegment,
    Dialect,
    ParsedCommand,
    canonical_command,
    evaluate_command,
    parse_command,
)

DIALECTS: tuple[Dialect, ...] = ("posix", "cmd", "powershell")


# --------------------------------------------------------------------------------------
# Helpers (local copies: nothing is imported across test files)
# --------------------------------------------------------------------------------------


def _deny_curl() -> CommandPolicyConfig:
    """The deny-list of the contract: forbid ``curl``, allow what no rule names, escalate what cannot be read.

    Built from a plain dict through ``model_validate``, as an operator's YAML would deliver it, in the shape of
    ``_policy`` / ``_rule`` of ``test_ad1328_s1_policy_evaluation.py``.
    """
    return CommandPolicyConfig.model_validate(
        {
            "rules": [
                {
                    "name": "no-curl",
                    "pattern": ["curl"],
                    "decision": "forbid",
                    "justification": "no-curl because",
                    "alternative": "use the governed path",
                }
            ],
            "unmatched_decision": "allow",
            "unparseable_decision": "escalate",
        }
    )


def _accepted(command: str, dialect: Dialect) -> ParsedCommand:
    """The accepted neighbour: the whole line parses, yields a segment, and every segment is readable."""
    parsed = parse_command(command, dialect=dialect)
    assert isinstance(parsed, ParsedCommand)
    assert parsed.dialect == dialect
    assert parsed.unparseable is None, f"{command!r} should parse under {dialect}: {parsed.unparseable}"
    assert parsed.segments, f"{command!r} should yield a segment under {dialect}"
    for segment in parsed.segments:
        assert isinstance(segment, CommandSegment)
        assert segment.unparseable is None, (
            f"{command!r} should be readable under {dialect}, but {segment.tokens} is not: {segment.unparseable}"
        )
    return parsed


def _flags(text: str) -> tuple[bool, ...]:
    """The contract's notation for per-word flags: ``"F,T,T"`` -> ``(False, True, True)``."""
    cleaned = text.replace(",", "").replace(" ", "")
    assert set(cleaned) <= {"F", "T"}, text
    return tuple(char == "T" for char in cleaned)


def _git_segment(parsed: ParsedCommand) -> CommandSegment:
    """The one segment whose program is ``git``."""
    found = [segment for segment in parsed.segments if segment.tokens[:1] == ("git",)]
    assert len(found) == 1, [segment.tokens for segment in parsed.segments]
    return found[0]


# --------------------------------------------------------------------------------------
# R-M2 #1 -- the refusals of the review findings, one row each
#   (id, dialect, command, scope, reason substring, accepted neighbour)
#   scope "line": segments == () and the reason is in ``unparseable``;
#   scope "segment": the line parses and its one segment carries the reason.
#   LF / CR LF / U+D800 / U+202E / U+00A0 are written as escapes; ``\u00e9`` is the letter e with an acute accent.
# --------------------------------------------------------------------------------------

FINDING_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    # F3: what a native program makes of the words (cmd, PowerShell)
    ("f3_cmd_caret", "cmd", "echo a^ b", "line", "'^'", 'echo "a b"'),
    ("f3_cmd_backslash_quote", "cmd", r'echo a\"b"', "line", "backslash before a double quote", r'echo "a\b"'),
    ("f3_cmd_backslash_closing", "cmd", r'echo "a\"', "line", "backslash before a double quote", r'echo "a\ "'),
    ("f3_cmd_doubled_quote", "cmd", 'echo "a""b"', "line", '""', 'echo "a" "b"'),
    ("f3_cmd_single_quote", "cmd", "echo 'a b'", "line", "outside quotes", 'echo "a b"'),
    ("f3_ps_empty", "powershell", "echo ''", "line", "empty argument", "echo 'x'"),
    ("f3_ps_empty_program", "powershell", "'' x", "line", "empty argument", "x 'y'"),
    ("f3_ps_embedded_quote", "powershell", "echo 'a\"b'", "line", "double quote inside an argument", "echo 'a b'"),
    (
        "f3_ps_quote_no_blank", "powershell", "echo 'it''s'", "line",
        "single quote in an argument without a blank", "echo 'it''s ok'",
    ),
    ("f3_ps_trailing_backslash", "powershell", r"echo 'a b\'", "line", "PowerShell quotes for a program", r"echo 'a\b'"),
    ("f3_ps_batch_metacharacter", "powershell", "echo 'a&b'", "line", "batch-file", "echo 'a+b'"),
    ("f3_ps_hex", "powershell", "echo 0x10", "line", "number", "echo 16"),
    ("f3_ps_leading_zero", "powershell", "echo 007", "line", "number", "echo 7"),
    ("f3_ps_suffix", "powershell", "echo 1kb", "line", "number", "echo '1kb'"),
    ("f3_cmd_trailing_blank_program", "cmd", '"git " status', "segment", "blank or a dot", '"git" status'),
    ("f3_cmd_trailing_dot_program", "cmd", "git. status", "segment", "blank or a dot", "git status"),
    ("f3_cmd_short_name", "cmd", "GIT~1.EXE status", "segment", "cmd.exe may split", "GIT.EXE status"),
    ("f3_ps_trailing_blank_program", "powershell", "& 'git ' status", "segment", "blank or a dot", "& 'git' status"),
    (
        "f3_cmd_slash_program", "cmd", "C:/Git/cmd/git.exe status", "segment",
        "cmd.exe may split", r"C:\Git\cmd\git.exe status",
    ),
    ("f3_cmd_internal_echo", "cmd", "echo.exe x", "segment", "internal command", "echo x"),
    ("f3_cmd_internal_cd", "cmd", r"cd\x", "segment", "internal command", "cd x"),
    # F4: markers the shell expands (PowerShell splats and variables, cmd percent and delayed expansion, POSIX `$`)
    ("f4_ps_splat_question", "powershell", "git push @? --force", "line", "'@' form",     "git push args --force"),
        ("f4_ps_splat_dollar", "powershell", "git push @$ x", "line", "'@' form", "git push args x"),
        ("f4_ps_splat_caret", "powershell", "git push @^ x", "line", "'@' form", "git push args x"),
    ("f4_ps_bare_dollar", "powershell", "echo $ x", "line", "'$' the policy does not model", "echo '$' x"),
        ("f4_ps_unicode_variable", "powershell", "echo $\u00e9", "line", "non-ASCII", "echo e"),
        ("f4_ps_member", "powershell", "echo $a.b", "line", "member access", "echo a.b"),
    ("f4_cmd_caret_percent", "cmd", "echo ^%X^%", "line", "'^'", "echo X"),
    ("f4_cmd_percent_substitution", "cmd", "echo %X: =%", "line", "percent", "echo X"),
    ("f4_cmd_percent_quoted", "cmd", 'echo "%X%"', "line", "percent", 'echo "X"'),
    ("f4_cmd_percent_program", "cmd", r"%X%\git push", "line", "percent", r"x\git push"),
    ("f4_cmd_delayed", "cmd", "echo !X!", "line", "delayed expansion", "echo X"),
    ("f4_posix_bare_dollar", "posix", "echo $", "line", "'$' the policy does not model", "echo '$'"),
    ("f4_posix_unicode_variable", "posix", "echo $\u00e9", "line", "'$' the policy does not model", "echo $e"),
    ("f4_posix_default_value", "posix", "echo ${X:-a}", "line", "${...}", "echo ${X}"),
    ("f4_posix_old_arithmetic", "posix", "echo $[1]", "line", "'$' the policy does not model", "echo $1"),
    # F5: process-wrapper options the policy does not read
    (
        "f5_command_dashdash", "posix", "command -- git push --force", "segment",
        "options the policy does not read", "command git push --force",
    ),
    ("f5_command_pv", "posix", "command -pv git", "segment", "options the policy does not read", "command -v git"),
    (
        "f5_nice_repeated", "posix", "nice -n 5 -n 3 git push --force", "segment",
        "options the policy does not read", "nice -n 5 git push --force",
    ),
    (
        "f5_stdbuf_terminator", "posix", "stdbuf -oL -- git push --force", "segment",
        "options the policy does not read", "stdbuf -oL git push --force",
    ),
    ("f5_stdbuf_separate", "posix", "stdbuf -o L git", "segment", "options the policy does not read", "stdbuf -oL git"),
    ("f5_stdbuf_long", "posix", "stdbuf --output=L git", "segment", "options the policy does not read", "stdbuf -oL git"),
    (
        "f5_timeout_option", "posix", "timeout --foreground 5 git", "segment",
        "options the policy does not read", "timeout 5 git",
    ),
    ("f5_nohup_dashdash", "posix", "nohup -- git", "segment", "options the policy does not read", "nohup git"),
    # F6: the transport of a cmd wrapper
    ("f6_cmd_c_quoted", "cmd", 'cmd /c "git status"', "segment", "no double quote", "cmd /c git status"),
    # F8: operators and redirections
    ("f8_posix_amp_redirect", "posix", "git status &> f", "line", "&>", "git status > f 2>&1"),
    ("f8_posix_amp_append", "posix", "git status &>> f", "line", "&>", "git status >> f 2>&1"),
    ("f8_posix_pipe_amp", "posix", "a |& b", "line", "|&", "a 2>&1 | b"),
    ("f8_posix_multi_digit", "posix", "a 10>f", "line", "multi-digit", "a 1>f"),
    ("f8_posix_named_descriptor", "posix", "a {fd}>f", "line", "{name}", "a 3>f"),
    ("f8_posix_clobber", "posix", "a >| f", "line", "does not model", "a > f"),
    ("f8_posix_duplication_word", "posix", "a >&f", "line", "descriptor duplication", "a >&2"),
    ("f8_ps_and", "powershell", "a && b", "line", "5.1", "a; b"),
    ("f8_ps_or", "powershell", "a || b", "line", "5.1", "a; b"),
    ("f8_ps_glued", "powershell", "echo a>b", "line", "written against a word", "echo a > b"),
    ("f8_ps_bad_stream", "powershell", "echo x 7>f", "line", "written against a word", "echo x 2>f"),
    ("f8_ps_merge_one", "powershell", "echo x 1>&1", "line", "stream redirection", "echo x 2>&1"),
    ("f8_cmd_multi_digit", "cmd", "echo a 12>f", "line", "written against a word", "echo a 2>f"),
    ("f8_cmd_glued", "cmd", "echo a2>f", "line", "written against a word", "echo a 2>f"),
    ("f8_cmd_duplication_word", "cmd", "echo a >&x", "line", "descriptor duplication", "echo a >&2"),
    # F9: launchers, shells and programs that run a program the policy cannot see
    (
        "f9_ps_return", "powershell", "return git push --force", "segment",
        "syntax the policy does not read", "git push --force",
    ),
    ("f9_ps_throw", "powershell", "throw git", "segment", "syntax the policy does not read", "git"),
    ("f9_ps_exit", "powershell", "exit git", "segment", "syntax the policy does not read", "git"),
    (
        "f9_cmd_env_exe", "cmd", "env.exe git push --force", "segment",
        "runs a command the policy cannot see", "git push --force",
    ),
    ("f9_ps_nice", "powershell", "nice git", "segment", "process wrapper", "git"),
    ("f9_cmd_timeout", "cmd", "timeout 30 git", "segment", "process wrapper", "git"),
    (
        "f9_posix_bash_exe", "posix", "bash.exe -c 'git status'", "segment",
        "runs commands the policy cannot see", "bash -c 'git status'",
    ),
    (
        "f9_posix_upper_bash", "posix", "BASH -c 'git status'", "segment",
        "runs commands the policy cannot see", "bash -c 'git status'",
    ),
    (
        "f9_posix_zsh", "posix", "zsh -c 'git status'", "segment",
        "runs a command the policy cannot see", "sh -c 'git status'",
    ),
    (
        "f9_posix_fish", "posix", "fish -c 'git status'", "segment",
        "runs a command the policy cannot see", "sh -c 'git status'",
    ),
    (
        "f9_posix_csh", "posix", "csh -c 'git status'", "segment",
        "runs a command the policy cannot see", "sh -c 'git status'",
    ),
    (
        "f9_posix_tcsh", "posix", "tcsh -c 'git status'", "segment",
        "runs a command the policy cannot see", "sh -c 'git status'",
    ),
    (
        "f9_posix_busybox", "posix", "busybox sh -c 'git status'", "segment",
        "runs a command the policy cannot see", "sh -c 'git status'",
    ),
    ("f9_posix_ssh", "posix", "ssh host git push", "segment", "runs a command the policy cannot see", "git push"),
    ("f9_posix_wsl", "posix", "wsl git status", "segment", "runs a command the policy cannot see", "git status"),
    ("f9_posix_npx", "posix", "npx cowsay hi", "segment", "runs a command the policy cannot see", "npm install"),
    ("f9_posix_uvx", "posix", "uvx ruff check", "segment", "runs a command the policy cannot see", "ruff check"),
    ("f9_posix_uv_run", "posix", "uv run pytest", "segment", "runs a program the policy cannot see", "uv pip install ruff"),
    ("f9_posix_uv_option_run", "posix", "uv -q run pytest", "segment", "runs a program the policy cannot see", "uv -q sync"),
    ("f9_posix_poetry_run", "posix", "poetry run pytest", "segment", "runs a program the policy cannot see", "poetry install"),
    ("f9_posix_docker_run", "posix", "docker run img x", "segment", "runs a program the policy cannot see", "docker ps"),
    ("f9_posix_subcommand_dynamic", "posix", "uv $SUB pytest", "segment", "runs a program the policy cannot see", "uv sync"),
    ("f9_cmd_bash", "cmd", 'bash -c "git status"', "segment", "starts a POSIX shell", "git status"),
    ("f9_ps_bash", "powershell", "bash -c 'git status'", "segment", "starts a POSIX shell", "git status"),
    (
        "f9_posix_pwsh", "posix", "pwsh -NoProfile -Command 'git status'", "segment",
        "starts PowerShell from a POSIX shell", "git status",
    ),
    ("f9_posix_cmd", "posix", "cmd /c git status", "segment", "starts cmd.exe", "git status"),
    ("f9_ps_cmd", "powershell", "cmd /c git status", "segment", "starts cmd.exe", "git status"),
    ("f9_posix_alias", "posix", "alias git=curl", "segment", "runs a command the policy cannot see", "git status"),
    ("f9_ps_provider_alias", "powershell", "Set-Item alias:git curl", "line", "alias:", "Set-Item x zqecho"),
    ("f9_ps_provider_env", "powershell", "Remove-Item env:PATH", "line", "env:", "Remove-Item x"),
    # F10: a quoted string at the start of a PowerShell statement is an expression, not a command
    (
        "f10_ps_expression", "powershell", '"C:/Program Files/Git/cmd/git.exe" status', "segment",
        "expression, not a command", '& "C:/Program Files/Git/cmd/git.exe" status',
    ),
    ("f10_ps_expression_single", "powershell", "'git' status", "segment", "expression, not a command", "& 'git' status"),
    # F11: line breaks
    ("f11_cmd_newline", "cmd", "git status\nx", "line", "newline", "git status & x"),
    ("f11_ps_continuation", "powershell", "echo a`\nb", "line", "continuation", "echo a` b"),
    ("f11_posix_crlf", "posix", "echo a\r\nb", "line", "carriage return", "echo a\nb"),
    ("f11_ps_crlf", "powershell", "git status\r\nls", "line", "carriage return", "git status\nls"),
    ("f11_ps_quoted_newline", "powershell", "echo 'a\nb'", "line", "newline inside a quoted string", "echo 'a b'"),
    # F12: text that is not valid Unicode
    ("f12_posix_surrogate", "posix", "echo \ud800", "line", "lone surrogate", "echo x"),
    ("f12_cmd_surrogate", "cmd", "echo \ud800", "line", "lone surrogate", "echo x"),
    ("f12_ps_surrogate", "powershell", "echo \ud800", "line", "lone surrogate", "echo x"),
    # R1: the closed grammar's own refusals
    ("r1_posix_bidi", "posix", "echo a\u202eb", "line", "formatting character", "echo ab"),
    ("r1_posix_nbsp", "posix", "git\u00a0push", "line", "unusual space", "git push"),
    ("r1_cmd_comma", "cmd", "git push,--force", "line", "outside quotes", "git push --force"),
    ("r1_ps_dashdash", "powershell", "git checkout -- x", "line", "the -- or --%", "git checkout x"),
    ("r1_ps_digit_program", "powershell", "7z x a.zip", "line", "number", "x7z x a.zip"),
    ("r1_ps_dash_program", "powershell", "-x y", "segment", "expression or an operator", "x y"),
    ("r1_ps_call_glued", "powershell", "&git status", "line", "not followed by a blank", "& git status"),
    ("r1_posix_backtick", "posix", "echo `id`", "line", "backtick", "echo $(id)"),
]


def test_finding_refusals_table_is_the_contracts_108_rows() -> None:
    ids = [row[0] for row in FINDING_REFUSALS]
    assert len(FINDING_REFUSALS) == 108
    assert len(set(ids)) == len(ids), "row ids must be unique"
    for case_id, dialect, command, scope, reason, neighbour in FINDING_REFUSALS:
        assert dialect in DIALECTS, case_id
        assert scope in ("line", "segment"), case_id
        assert reason, case_id
        assert command != neighbour, f"{case_id}: a refusal and its accepted neighbour must differ"


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"),
    FINDING_REFUSALS,
    ids=[row[0] for row in FINDING_REFUSALS],
)
def test_finding_refusals(
    case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str,
) -> None:
    # The accepted neighbour first: it parses, every segment is readable, and the deny-list lets it through, so the
    # refusal below is the one thing under test and not a machine that refuses everything.
    _accepted(neighbour, dialect)
    control = evaluate_command(_deny_curl(), neighbour, dialect=dialect)
    assert control.status == "evaluated"
    assert control.decision == "allow", f"{case_id}: the neighbour {neighbour!r} should be allowed, got {control.decision}"

    parsed = parse_command(command, dialect=dialect)
    assert parsed.dialect == dialect
    evaluation = evaluate_command(_deny_curl(), command, dialect=dialect)
    assert evaluation.status == "evaluated"

    if scope == "line":
        assert parsed.segments == (), f"{case_id}: a refused line yields no segment, got {parsed.segments}"
        assert parsed.unparseable is not None, f"{case_id}: {command!r} should be unparseable under {dialect}"
        assert reason in parsed.unparseable, f"{case_id}: expected {reason!r} in {parsed.unparseable!r}"
        assert evaluation.segments == ()
        assert evaluation.unparseable == parsed.unparseable
    else:
        assert scope == "segment"
        assert parsed.unparseable is None, f"{case_id}: the line should parse, got {parsed.unparseable!r}"
        assert len(parsed.segments) == 1, f"{case_id}: expected one segment, got {[s.tokens for s in parsed.segments]}"
        refused = parsed.segments[0].unparseable
        assert refused is not None, f"{case_id}: the segment {parsed.segments[0].tokens} should be unparseable"
        assert reason in refused, f"{case_id}: expected {reason!r} in {refused!r}"
        assert evaluation.unparseable is None
        assert [(v.decision, v.basis) for v in evaluation.segments] == [("escalate", "unparseable")]

    # Rule 1: a refusal is never an allow; under the deny-list it escalates.
    assert evaluation.decision == "escalate", f"{case_id}: expected escalate, got {evaluation.decision}"
    assert evaluation.decision != "allow"


# --------------------------------------------------------------------------------------
# R-M2 #2 -- which words are computed, and whether one stands for zero or more words      Kills M38, M39, M40
#   oracle rows that record the same marks: P15 (`$W "$W" ${W} "${W}"` -> vovo), P16 (`"$@"`), P17 (`$(...)`,
#   `"$(...)"`), P18 (`g*.txt`), P19 (`{a,b}`), P20 (tilde forms) for posix; C08 (`a*.txt b?c [d] {e} @f ~g`) for cmd;
#   S12 (`a*.txt`) for powershell.
# --------------------------------------------------------------------------------------

# (dialect, command, dynamic flags, variadic flags, number of substitution bodies that follow the first segment)
ARITY_ROWS = [
    pytest.param(
        "posix",
        'echo $X "$X" ${X} "${X}" "$@" $(a) "$(a)" *.py ~ a=~ b:~ {a,b} a~b \'$X\'',
        "F,T,T,T,T,T,T,T,T,T,T,T,T,F,F",
        "F,T,F,T,F,T,T,F,T,F,F,F,T,F,F",
        2,  # the bodies of `$(a)` and `"$(a)"` are segments of their own, after the line's
        id="posix",
    ),
    pytest.param(
        "cmd",
        'echo *.py a?b [x] {y} @f ~h a~b a@b "*"',
        "F,T,T,T,T,T,T,F,F,T",
        "F,T,T,T,T,T,T,F,F,T",
        0,
        id="cmd",
    ),
    pytest.param(
        "powershell",
        'echo *.py \'*\' \'$x\' a~b',
        "F,T,T,F,F",
        "F,T,T,F,F",
        0,
        id="powershell",
    ),
]


@pytest.mark.parametrize(("dialect", "command", "dynamic", "variadic", "bodies"), ARITY_ROWS)
def test_dynamic_word_arity(dialect: Dialect, command: str, dynamic: str, variadic: str, bodies: int) -> None:
    expected_dynamic = _flags(dynamic)
    expected_variadic = _flags(variadic)

    # control first: literal words are neither dynamic nor variadic
    literal = _accepted("echo a b", dialect).segments[0]
    assert literal.dynamic == (False, False, False)
    assert literal.variadic == (False, False, False)

    # premise: the first segment is the line itself; what follows it are the bodies of its substitutions, one level down
    parsed = _accepted(command, dialect)
    assert len(parsed.segments) == 1 + bodies, [segment.tokens for segment in parsed.segments]
    for body in parsed.segments[1:]:
        assert (body.tokens, body.depth) == (("a",), 1)
    segment = parsed.segments[0]
    assert segment.tokens[0] == "echo"
    assert len(segment.tokens) == len(expected_dynamic) == len(expected_variadic), segment.tokens  # premise: word count
    assert segment.dynamic == expected_dynamic, segment.tokens
    assert segment.variadic == expected_variadic, segment.tokens


# --------------------------------------------------------------------------------------
# R-M2 #3 -- a state mutator, a login shell or a profile changes where every program resolves
#   Kills M11, M15-M17, M20, M49
#   oracle rows for the wrapped readings: P25 (`bash -lc`), P26 (`command -p`), C11 (`powershell -NoProfile -Command`).
#   The cause of a mutator is R4's wording: "the command changes the working directory or the environment (NAME)",
#   with NAME the program as written, and it marks every segment of the line, before and after the mutator.
# --------------------------------------------------------------------------------------


def _mutator(name: str) -> str:
    return f"the command changes the working directory or the environment ({name})"


# (id, dialect, command, number of segments, cause that every segment's lookup_changed contains; None = unchanged)
LOOKUP_ROWS: list[tuple[str, str, str, int, str | None]] = [
    # state mutators
    ("posix_cd", "posix", "cd sub && git status", 2, _mutator("cd")),
    ("posix_export", "posix", "export PATH=/tmp/x && git status", 2, _mutator("export")),
    ("posix_pushd", "posix", "pushd x; git status", 2, _mutator("pushd")),
    ("posix_hash", "posix", "hash -p /tmp/git git; git status", 2, _mutator("hash")),
    ("posix_unset", "posix", "unset PATH; git status", 2, _mutator("unset")),
    ("cmd_cd", "cmd", "cd sub && git status", 2, _mutator("cd")),
    ("cmd_set", "cmd", r"set PATH=C:\x& git status", 2, _mutator("set")),
    ("cmd_path", "cmd", r"path C:\x & git status", 2, _mutator("path")),
    ("cmd_drive_change", "cmd", "D: & git status", 2, _mutator("D:")),
    ("cmd_pushd", "cmd", "pushd x & git status", 2, _mutator("pushd")),
    ("ps_set_location", "powershell", "Set-Location sub; git status", 2, _mutator("Set-Location")),
    ("ps_cd", "powershell", "cd sub; git status", 2, _mutator("cd")),
    ("ps_drive_change", "powershell", "D:; git status", 2, _mutator("D:")),
    ("ps_push_location", "powershell", "Push-Location x; git status", 2, _mutator("Push-Location")),
    # context sources
    ("posix_login_shell", "posix", "bash -lc 'git status'", 1, "login shell"),
    ("posix_command_p", "posix", "command -p git status", 1, "default PATH"),
    ("cmd_powershell_profile", "cmd", 'powershell -Command "git status"', 1, "-NoProfile"),
    # controls: nothing in the line changes the lookup context
    ("posix_control", "posix", "git status && ls", 2, "another command in the line"),
    ("cmd_control", "cmd", "git status & dir", 2, "another command in the line"),
    ("ps_control", "powershell", "git status; ls", 2, "another command in the line"),
    ("cmd_powershell_noprofile_control", "cmd", 'powershell -NoProfile -Command "git status"', 1, None),
    ("posix_single_control", "posix", "git status", 1, None),
    ("cmd_single_control", "cmd", "git status", 1, None),
    ("ps_single_control", "powershell", "git status", 1, None),
]


@pytest.mark.parametrize(
    ("dialect", "command", "segments", "cause"),
    [pytest.param(*row[1:], id=row[0]) for row in LOOKUP_ROWS],
)
def test_state_mutators_mark_the_lookup_context(
    dialect: Dialect, command: str, segments: int, cause: str | None,
) -> None:
    parsed = _accepted(command, dialect)  # premise: the line is read, so lookup_changed is the parser's judgement
    assert len(parsed.segments) == segments, [segment.tokens for segment in parsed.segments]
    for segment in parsed.segments:
        if cause is None:
            assert segment.lookup_changed is None, f"{command!r}: {segment.tokens} -> {segment.lookup_changed!r}"
        else:
            assert segment.lookup_changed is not None, f"{command!r}: {segment.tokens} has no lookup_changed"
            assert cause in segment.lookup_changed, f"{command!r}: expected {cause!r} in {segment.lookup_changed!r}"


# --------------------------------------------------------------------------------------
# R-M2 #4 -- the segments of an unwrapped script inherit the wrapper's context        Kills M12, M13, M14
#   oracle rows for the wrapped readings: P22 (`sh -c "{P} a 'b c'"`), C10 (`cmd /c {B} a b`).
# --------------------------------------------------------------------------------------

# (id, dialect, command, field of the git segment, its expected value, its depth or None, and, for the control only, the
#  program and assignments of the segment that holds the substitution: the control's premise)
INHERITANCE_ROWS: list[tuple[str, str, str, str, tuple[str, ...], int | None, tuple[str, tuple[str, ...]] | None]] = [
    ("posix_assignment", "posix", "X=1 sh -c 'git status'", "assignments", ("X=1",), 1, None),
    ("posix_process_wrapper", "posix", "nice sh -c 'git status'", "wrappers", ("nice",), None, None),
    ("posix_redirection", "posix", "sh -c 'git status' > out", "redirections", (">out",), None, None),
    ("posix_both_assignments", "posix", "X=1 sh -c 'Y=2 git status'", "assignments", ("X=1", "Y=2"), None, None),
    ("posix_substitution_in_the_script", "posix", "X=1 sh -c 'echo $(git status)'", "assignments", ("X=1",), None, None),
    ("cmd_redirection", "cmd", "cmd /c git status > out", "redirections", (">out",), None, None),
    # control: at the top level a substitution does not inherit the assignments of the command that holds it
    (
        "posix_control_top_level_substitution", "posix", "X=1 echo $(git status)", "assignments", (), None,
        ("echo", ("X=1",)),
    ),
]


@pytest.mark.parametrize(
    ("dialect", "command", "field", "expected", "depth", "holder"),
    [pytest.param(*row[1:], id=row[0]) for row in INHERITANCE_ROWS],
)
def test_unwrapped_segments_inherit_context(
    dialect: Dialect,
    command: str,
    field: str,
    expected: tuple[str, ...],
    depth: int | None,
    holder: tuple[str, tuple[str, ...]] | None,
) -> None:
    parsed = _accepted(command, dialect)
    inner = _git_segment(parsed)
    assert inner.tokens == ("git", "status")
    assert getattr(inner, field) == expected, f"{command!r}: {field} of {inner.tokens} is {getattr(inner, field)!r}"
    if depth is not None:
        assert inner.depth == depth  # the script's segment sits one wrapper below the line
    if holder is not None:
        program, assignments = holder
        held = [segment for segment in parsed.segments if segment.tokens[:1] == (program,)]
        assert [segment.assignments for segment in held] == [assignments]  # premise: the assignment exists and binds there


# --------------------------------------------------------------------------------------
# R-M2 #5 -- a wrapped script is rebuilt from the words the launcher receives            Kills M18
#   oracle rows: C10 (`cmd /c {B} a b`), C11 (`powershell -NoProfile -Command "{B} a 'b c'"`), C12 and S14
#   (`pwsh -NoProfile -Command {B} a b`), S13 (`powershell -NoProfile -Command "{B} a 'b c'"` from PowerShell).
# --------------------------------------------------------------------------------------

# (id, outer dialect, command, the script's dialect)
WRAPPED_SCRIPT_ROWS: list[tuple[str, str, str, str]] = [
    ("cmd_powershell_second_word_quoted", "cmd", 'powershell -NoProfile -Command git "push --force"', "powershell"),
    ("cmd_powershell_first_words_quoted", "cmd", 'powershell -NoProfile -Command "git push" --force', "powershell"),
    ("ps_pwsh_second_word_quoted", "powershell", "pwsh -NoProfile -Command git 'push --force'", "powershell"),
    ("cmd_cmd_words", "cmd", "cmd /c git push --force", "cmd"),
]


@pytest.mark.parametrize(
    ("outer", "command", "inner"),
    [pytest.param(*row[1:], id=row[0]) for row in WRAPPED_SCRIPT_ROWS],
)
def test_wrapped_scripts_are_rebuilt_from_the_words_the_launcher_receives(
    outer: Dialect, command: str, inner: Dialect,
) -> None:
    # control first: the script written directly under its own dialect reads the same way
    direct = _accepted("git push --force", inner)
    assert [segment.tokens for segment in direct.segments] == [("git", "push", "--force")]

    parsed = _accepted(command, outer)
    assert parsed.dialect == outer
    assert len(parsed.segments) == 1, [segment.tokens for segment in parsed.segments]  # the wrapper is replaced
    segment = parsed.segments[0]
    assert segment.tokens == ("git", "push", "--force")
    assert segment.dialect == inner
    assert segment.depth == 1


# --------------------------------------------------------------------------------------
# R-M2 #6 -- the approval-reuse identity follows what runs                              Kills M44, M45, M46, M47
#   oracle rows that cover the argv readings: P22-P24 (`sh|bash|dash -c`), C02 (`"a b"` is one word), C03 (`"a" b`
#   is `a b`), C09 and S10 (a bare program), C11 (`powershell -NoProfile -Command`).
#   (id, dialect, command, expectation, other dialect, other command):
#     "script":    the key is a script key of the exact original text; `other` is the neighbour that IS an argv key
#     "equals":    the key is an argv key equal to that of `other`
#     "differs":   the key is an argv key different from that of `other`
#     "malformed": text that is not valid Unicode: a tagged script key; `other` is another malformed text
# --------------------------------------------------------------------------------------

_MALFORMED_SCRIPT_TAG = "probos.command_policy/malformed-utf16le-hex"

CANONICAL_ROWS: list[tuple[str, str, str, str, str, str]] = [
    # script keys: the parts are exactly the original text
    ("script_posix_assignment_wrapper", "posix", "X=1 sh -c 'git status'", "script", "posix", "sh -c 'git status'"),
    ("script_posix_process_wrapper", "posix", "nice sh -c 'git status'", "script", "posix", "sh -c 'git status'"),
    ("script_posix_redirected_wrapper", "posix", "sh -c 'git status' > out", "script", "posix", "sh -c 'git status'"),
    ("script_posix_login_shell", "posix", "bash -lc 'git status'", "script", "posix", "bash -c 'git status'"),
    ("script_posix_cd", "posix", "cd x", "script", "posix", "ls x"),
    (
        "script_cmd_pwsh_without_noprofile", "cmd", 'pwsh -Command "git status"', "script", "cmd",
        'pwsh -NoProfile -Command "git status"',
    ),
    ("script_cmd_internal_command", "cmd", "dir src", "script", "cmd", "findstr src"),
    (
        "script_ps_string_program", "powershell", '"C:/x/git.exe" status', "script", "powershell",
        '& "C:/x/git.exe" status',
    ),
    # argv keys
    ("argv_posix_bash_c_is_the_program", "posix", "bash -c 'git status'", "equals", "posix", "git status"),
    (
        "argv_cmd_pwsh_noprofile_is_the_program", "cmd", 'pwsh -NoProfile -Command "git status"', "equals", "cmd",
        "git status",
    ),
    (
        "argv_ps_call_is_not_the_string", "powershell", '& "C:/x/git.exe" status', "differs", "powershell",
        '"C:/x/git.exe" status',
    ),
    ("argv_cmd_quoted_blank_is_one_word", "cmd", 'git "a b"', "differs", "cmd", "git a b"),
    ("argv_cmd_quotes_are_removed", "cmd", 'git "a" b', "equals", "cmd", "git a b"),
    # malformed text
    ("malformed_text_is_a_tagged_script", "posix", "git \ud800", "malformed", "posix", "git \udc00"),
]


@pytest.mark.parametrize(
    ("dialect", "command", "expectation", "other_dialect", "other"),
    [pytest.param(*row[1:], id=row[0]) for row in CANONICAL_ROWS],
)
def test_canonical_identity_follows_what_runs(
    dialect: Dialect, command: str, expectation: str, other_dialect: Dialect, other: str,
) -> None:
    result = canonical_command(command, dialect=dialect)
    assert isinstance(result, CanonicalCommand)
    neighbour = canonical_command(other, dialect=other_dialect)

    if expectation == "script":
        assert neighbour.kind == "argv", f"control: {other!r} should be an argv key, got {neighbour}"
        assert result.kind == "script", f"{command!r} should be a script key, got {result}"
        assert result.dialect == dialect
        assert result.parts == (command,)
        assert result.key != neighbour.key
    elif expectation == "equals":
        assert result.kind == "argv", f"{command!r} should be an argv key, got {result}"
        assert neighbour.kind == "argv", f"control: {other!r} should be an argv key, got {neighbour}"
        assert result.parts == neighbour.parts
        assert result.key == neighbour.key
    elif expectation == "differs":
        assert result.kind == "argv", f"{command!r} should be an argv key, got {result}"
        assert result.key != neighbour.key, f"{command!r} and {other!r} must not share a key"
    else:
        assert expectation == "malformed"
        assert result.kind == "script"
        assert result.dialect == dialect
        assert result.parts == (_MALFORMED_SCRIPT_TAG, command.encode("utf-16-le", "surrogatepass").hex())
        assert re.fullmatch(r"[0-9a-f]{64}", result.key), result.key
        assert re.fullmatch(r"[0-9a-f]{64}", neighbour.key), neighbour.key
        assert result.key != neighbour.key  # two different malformed texts are two different identities


# --------------------------------------------------------------------------------------
# R-M2 #7 -- the usability guard: ordinary commands stay readable and a deny-list lets them through
#   The corpus is the literal of the contract's R1 section. Every line parses, every segment's ``unparseable`` is None,
#   the tokens are as given, and under ``forbid ["curl"]`` with ``unmatched_decision="allow"`` the decision is allow.
#   `cd src && ls`, `cd src && dir` and `Set-Location src; Get-ChildItem` additionally have ``lookup_changed`` set;
#   r2: so does every row of two or more segments (another command in the line leaves a bare name's lookup unproven). Readings the oracle covers: P01-P05 and P10 (posix words, quoting, pipes), C01-C04 and C06 (cmd
#   words, quoting, pipes), S01-S04 and S07 (PowerShell words, quoting, pipes), P13, C07 and S08 (redirections).
# --------------------------------------------------------------------------------------

USABILITY_CORPUS = {
    "posix": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 -- src/probos/config.py", [("git", "diff", "HEAD~1", "--", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ("git commit -m 'fix: handle empty input'", [("git", "commit", "-m", "fix: handle empty input")]),
        ('git commit -m "fix: the \\"x\\" case"', [("git", "commit", "-m", 'fix: the "x" case')]),
        ("git add src/probos/execution/command_policy.py tests/test_x.py", [("git", "add", "src/probos/execution/command_policy.py", "tests/test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests/test_x.py -q -n 0", [("pytest", "tests/test_x.py", "-q", "-n", "0")]),
        ('pytest -k "parse and not slow" -x', [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ('pip install "requests>=2.31"', [("pip", "install", "requests>=2.31")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("uv sync", [("uv", "sync")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("npm test -- --watch=false", [("npm", "test", "--", "--watch=false")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src/probos/execution/command_policy.py", [("mypy", "src/probos/execution/command_policy.py")]),
        ("make test", [("make", "test")]),
        ("ls -la src", [("ls", "-la", "src")]),
        ("cat README.md", [("cat", "README.md")]),
        ("grep -rn 'def parse' src/probos", [("grep", "-rn", "def parse", "src/probos")]),
        ("cd src && ls", [("cd", "src"), ("ls",)]),
        ("git status && git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | tail -n 20", [("pytest", "-q"), ("tail", "-n", "20")]),
        ("python scripts/run_test_gate.py --label x --receipt logs/gates/x.receipt.json", [("python", "scripts/run_test_gate.py", "--label", "x", "--receipt", "logs/gates/x.receipt.json")]),
        ("find . -name '*.py' -newer setup.cfg", [("find", ".", "-name", "*.py", "-newer", "setup.cfg")]),
    ],
    "cmd": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 -- src/probos/config.py", [("git", "diff", "HEAD~1", "--", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ('git commit -m "fix: handle empty input"', [("git", "commit", "-m", "fix: handle empty input")]),
        ("git add src\\probos\\execution\\command_policy.py tests\\test_x.py", [("git", "add", "src\\probos\\execution\\command_policy.py", "tests\\test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests\\test_x.py -q -n 0", [("pytest", "tests\\test_x.py", "-q", "-n", "0")]),
        ('pytest -k "parse and not slow" -x', [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ('pip install "requests>=2.31"', [("pip", "install", "requests>=2.31")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src\\probos\\execution\\command_policy.py", [("mypy", "src\\probos\\execution\\command_policy.py")]),
        ("make test", [("make", "test")]),
        ("dir src", [("dir", "src")]),
        ("type README.md", [("type", "README.md")]),
        ('findstr /n "def parse" src\\probos\\config.py', [("findstr", "/n", "def parse", "src\\probos\\config.py")]),
        ("cd src && dir", [("cd", "src"), ("dir",)]),
        ("git status && git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | findstr FAILED", [("pytest", "-q"), ("findstr", "FAILED")]),
        ("python scripts\\run_test_gate.py --label x --receipt logs\\gates\\x.receipt.json", [("python", "scripts\\run_test_gate.py", "--label", "x", "--receipt", "logs\\gates\\x.receipt.json")]),
        ('"C:\\Program Files\\Git\\cmd\\git.exe" status', [("C:\\Program Files\\Git\\cmd\\git.exe", "status")]),
        ("d:\\ProbOS\\.venv\\Scripts\\python.exe -m pytest -q", [("d:\\ProbOS\\.venv\\Scripts\\python.exe", "-m", "pytest", "-q")]),
        ("git log --pretty=oneline -5", [("git", "log", "--pretty=oneline", "-5")]),
        ("echo done", [("echo", "done")]),
    ],
    "powershell": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 src/probos/config.py", [("git", "diff", "HEAD~1", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ("git commit -m 'fix: handle empty input'", [("git", "commit", "-m", "fix: handle empty input")]),
        ('git commit -m "fix: handle empty input"', [("git", "commit", "-m", "fix: handle empty input")]),
        ("git add src/probos/execution/command_policy.py tests/test_x.py", [("git", "add", "src/probos/execution/command_policy.py", "tests/test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests/test_x.py -q -n 0", [("pytest", "tests/test_x.py", "-q", "-n", "0")]),
        ("pytest -k 'parse and not slow' -x", [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ("pip install requests", [("pip", "install", "requests")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src/probos/execution/command_policy.py", [("mypy", "src/probos/execution/command_policy.py")]),
        ("make test", [("make", "test")]),
        ("Get-ChildItem src", [("Get-ChildItem", "src")]),
        ("Get-Content README.md", [("Get-Content", "README.md")]),
        ("Select-String -Path src/probos/config.py -Pattern 'def parse'", [("Select-String", "-Path", "src/probos/config.py", "-Pattern", "def parse")]),
        ("Set-Location src; Get-ChildItem", [("Set-Location", "src"), ("Get-ChildItem",)]),
        ("git status; git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | Select-Object -Last 20", [("pytest", "-q"), ("Select-Object", "-Last", "20")]),
        ("python scripts/run_test_gate.py --label x --receipt logs/gates/x.receipt.json", [("python", "scripts/run_test_gate.py", "--label", "x", "--receipt", "logs/gates/x.receipt.json")]),
        ("& 'C:\\Program Files\\Git\\cmd\\git.exe' status", [("C:\\Program Files\\Git\\cmd\\git.exe", "status")]),
        ("d:\\ProbOS\\.venv\\Scripts\\python.exe -m pytest -q", [("d:\\ProbOS\\.venv\\Scripts\\python.exe", "-m", "pytest", "-q")]),
        ("Write-Output done", [("Write-Output", "done")]),
    ],
}

# The rows whose line changes the working directory, so that every segment of it has ``lookup_changed`` set.
_CONTEXT_CHANGING = {
    ("posix", "cd src && ls"),
    ("cmd", "cd src && dir"),
    ("powershell", "Set-Location src; Get-ChildItem"),
    ("posix", "git status && git diff --stat"),
    ("posix", "pytest -q 2>&1 | tail -n 20"),
    ("cmd", "git status && git diff --stat"),
    ("cmd", "pytest -q 2>&1 | findstr FAILED"),
    ("powershell", "git status; git diff --stat"),
    ("powershell", "pytest -q 2>&1 | Select-Object -Last 20"),
}

# ``<dialect>-<n>``: n is the 1-based position of the row in its dialect's list.
_CORPUS_ROWS: list[Any] = [
    pytest.param(dialect, command, expected, id=f"{dialect}-{number}")
    for dialect, rows in USABILITY_CORPUS.items()
    for number, (command, expected) in enumerate(rows, start=1)
]


def test_usability_corpus_is_the_contracts_corpus() -> None:
    # The contract says "about 30 per dialect"; the literal block it carries has 31 rows in each of the three.
    assert tuple(USABILITY_CORPUS) == DIALECTS
    assert {dialect: len(rows) for dialect, rows in USABILITY_CORPUS.items()} == {"posix": 31, "cmd": 31, "powershell": 31}
    assert len(_CORPUS_ROWS) == 93
    for dialect, command in _CONTEXT_CHANGING:
        assert command in [row[0] for row in USABILITY_CORPUS[dialect]], (dialect, command)


@pytest.mark.parametrize(("dialect", "command", "expected"), _CORPUS_ROWS)
def test_usability_corpus(dialect: Dialect, command: str, expected: list[tuple[str, ...]]) -> None:
    parsed = _accepted(command, dialect)  # the line parses and every segment is readable
    assert [segment.tokens for segment in parsed.segments] == expected

    changed = (dialect, command) in _CONTEXT_CHANGING
    for segment in parsed.segments:
        if changed:
            assert segment.lookup_changed is not None, f"{command!r}: {segment.tokens} has no lookup_changed"
        else:
            assert segment.lookup_changed is None, f"{command!r}: {segment.tokens} -> {segment.lookup_changed!r}"

    evaluation = evaluate_command(_deny_curl(), command, dialect=dialect)
    assert evaluation.status == "evaluated"
    assert evaluation.unparseable is None
    assert evaluation.decision == "allow", f"{command!r} under {dialect}: {evaluation.decision}"


# --------------------------------------------------------------------------------------
# r1b (prompts/ad-1328-s1-repair-r1b.md) -- two PowerShell classes from the differential fuzz
#   Class A: an escaped blank that starts a bare word (oracle S15-S19 pin the accepted boundary live).
#   Class B: a dynamic word's literal text gets every character check.
# --------------------------------------------------------------------------------------

R1B_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1b_ps_escaped_blank_start", "powershell", "echo ` zz", "line", "escaped blank", "echo a` b"),
    ("r1b_ps_escaped_blank_alone", "powershell", "echo ` ", "line", "escaped blank", "echo a`  b"),
    ("r1b_ps_escaped_blank_twice", "powershell", "echo ` ` x", "line", "escaped blank", "echo x` y` z"),
    ("r1b_ps_escaped_blank_variable", "powershell", "echo ` $x", "line", "escaped blank", "echo x` b"),
    ("r1b_ps_escaped_blank_then_blank", "powershell", "xx `  ww", "line", "escaped blank", 'echo "` zz"'),
    ("r1b_ps_dynamic_quote", "powershell", 'echo *`"b jj jj', "line", "a double quote inside an argument", "echo *-b jj jj"),
    ("r1b_ps_dynamic_quote_in_quotes", "powershell", 'echo "*`"b" jj', "line", "a double quote inside an argument", 'echo "* b" jj'),
    ("r1b_ps_dynamic_batch_ampersand", "powershell", "run.bat *`&calc", "line", "batch-file program", "run.bat *-calc"),
    ("r1b_ps_dynamic_batch_percent", "powershell", "echo a%*", "line", "batch-file program", "echo a*"),
    ("r1b_ps_dynamic_tab", "powershell", 'echo "*\tb"', "line", "quotes for a program", 'echo "* b"'),
    ("r1b_ps_dynamic_blank_backslash", "powershell", "echo *` a\\", "line", "quotes for a program", "echo *` a\\b"),
    ("r1b_ps_dynamic_single_quote", "powershell", "echo *`'b", "line", "single quote in an argument without a blank", "echo *`'` b"),
    ("r1b_ps_dynamic_provider", "powershell", "Set-Item alias:* curl", "line", "alias:", "Set-Item x* zqecho"),
    ("r1b_ps_dynamic_provider_after_variable", "powershell", "Remove-Item ${x}env:PATH", "line", "a value PowerShell computes", "Remove-Item envPATH"),
    ("r1b_ps_dynamic_stop_parsing", "powershell", "echo --%*", "line", "the -- or --%", "echo -*"),
    ("r1b_ps_dynamic_dashdash", "powershell", "git checkout --$x", "line", "a value PowerShell computes", "git checkout --x"),
]


def test_r1b_refusals_table() -> None:
    ids = [row[0] for row in R1B_REFUSALS]
    assert len(R1B_REFUSALS) == 16
    assert len(set(ids)) == len(ids)
    assert not set(ids) & {row[0] for row in FINDING_REFUSALS}


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1B_REFUSALS, ids=[row[0] for row in R1B_REFUSALS],
)
def test_r1b_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


# (id, dialect, command, tokens, dynamic flags): what r1b must leave as it was.
R1B_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("s15_mid_word", "powershell", "echo a` b", ("echo", "a b"), (False, False)),  # oracle S15
    ("s16_two_escapes", "powershell", "echo x` y` z", ("echo", "x y z"), (False, False)),  # oracle S16
    ("s17_trailing", "powershell", "echo a`  b", ("echo", "a ", "b"), (False, False, False)),  # oracle S17
    ("s18_in_quotes", "powershell", 'echo "` zz"', ("echo", " zz"), (False, False)),  # oracle S18
    ("s19_glob_then_escaped_blank", "powershell", "echo *` b", ("echo", "* b"), (False, True)),
    ("dynamic_number_like", "powershell", "echo 0x1*", ("echo", "0x1*"), (False, True)),  # the number check is literal-only
    ("dynamic_dash_text", "powershell", "echo *-b", ("echo", "*-b"), (False, True)),
    ("cmd_glob_after_quote", "cmd", 'echo "a b"*', ("echo", "a b*"), (False, True)),  # cmd checks per character
    ("posix_glob_after_quote", "posix", 'echo "a b"*', ("echo", "a b*"), (False, True)),  # posix checks per character
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1B_READINGS, ids=[row[0] for row in R1B_READINGS],
)
def test_r1b_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    parsed = _accepted(command, dialect)
    assert len(parsed.segments) == 1, case_id
    assert parsed.segments[0].tokens == tokens, case_id
    assert parsed.segments[0].dynamic == dynamic, case_id


# --------------------------------------------------------------------------------------
# r1c (prompts/ad-1328-s1-repair-r1c.md) -- seed-3 fuzz
#   Class C: a PowerShell '-name:' word (oracle S20, S21 pin the accepted forms live).
#   Class D: an '=' in a cmd redirection target (oracle C13 pins '=' in ordinary arguments live).
# --------------------------------------------------------------------------------------

R1C_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1c_ps_colon_empty", "powershell", "echo -a:", "line", "'-name:' word", "echo -a:b"),
    ("r1c_ps_colon_parameter_argument", "powershell", "echo -a:-b:c", "line", "'-name:' word", "echo -a:b:c"),
    ("r1c_ps_colon_fuzz", "powershell", "wwxx kk -qq:-qq:zz ww", "line", "'-name:' word", "wwxx kk -qq:zz ww"),
    ("r1c_ps_colon_escaped_blank", "powershell", "echo -qq:` zz", "line", "'-name:' word", "echo -qq:zz"),
    ("r1c_ps_colon_variable", "powershell", "echo -a:$x", "line", "a value PowerShell computes", "echo -a x"),
    ("r1c_ps_colon_glob", "powershell", "echo -a:*", "line", "'-name:' word", "echo -a *"),
    ("r1c_ps_colon_number", "powershell", "echo -a:1kb", "line", "'-name:' word", "echo -a:kb"),
    ("r1c_ps_colon_double_colon", "powershell", "echo -a::b", "line", "'-name:' word", "echo -a:b"),
    ("r1c_ps_colon_escaped_colon", "powershell", "echo -a`:b", "line", "'-name:' word", "echo a`:b"),
    ("r1c_ps_colon_quoted", "powershell", "echo -a:'b c'", "line", "a quote inside a word", "echo -a 'b c'"),
    ("r1c_cmd_redirect_equals", "cmd", "echo x >zz=ww", "line", "'=' in a redirection target", "echo x >zz"),
    ("r1c_cmd_redirect_equals_trailing", "cmd", "echo x 2>zz=", "line", "'=' in a redirection target", "echo x 2>zz"),
    ("r1c_cmd_redirect_equals_leading", "cmd", "echo x >=zz", "line", "'=' in a redirection target", "echo x > zz"),
    ("r1c_cmd_redirect_equals_spaced", "cmd", "echo x > zz=ww", "line", "'=' in a redirection target", "echo x zz=ww"),
    ("r1c_cmd_redirect_equals_quoted", "cmd", 'echo x >"zz=ww"', "line", "'=' in a redirection target", 'echo x >"zz ww"'),
    ("r1c_cmd_input_equals", "cmd", "echo x <zz=ww", "line", "'=' in a redirection target", "echo x <zz"),
    ("r1c_cmd_duplication_equals", "cmd", "echo x 2>&1=", "line", "not one descriptor", "echo x 2>&1"),
]


def test_r1c_refusals_table() -> None:
    ids = [row[0] for row in R1C_REFUSALS]
    assert len(R1C_REFUSALS) == 17
    assert len(set(ids)) == len(ids)
    assert not set(ids) & ({row[0] for row in FINDING_REFUSALS} | {row[0] for row in R1B_REFUSALS})


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1C_REFUSALS, ids=[row[0] for row in R1C_REFUSALS],
)
def test_r1c_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1C_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    (
        "s20_colon_parameters", "powershell", "echo -a:b -a:b:c --a:b -:b -a:b:",
        ("echo", "-a:b", "-a:b:c", "--a:b", "-:b", "-a:b:"), (False,) * 6,
    ),  # oracle S20
    ("s21_colons", "powershell", "echo a:b a:b:c x: :b", ("echo", "a:b", "a:b:c", "x:", ":b"), (False,) * 5),  # S21
    ("ps_quoted_dash_colon", "powershell", "echo '-a:'", ("echo", "-a:"), (False, False)),  # a quoted word is no parameter
    ("c13_equals_arguments", "cmd", "echo a=b a= b =a", ("echo", "a=b", "a=", "b", "=a"), (False,) * 5),  # oracle C13
    ("posix_redirect_equals", "posix", "echo x >a=b", ("echo", "x"), (False, False)),  # rule D is cmd-only
    ("ps_redirect_equals", "powershell", "echo x > a=b", ("echo", "x"), (False, False)),  # rule D is cmd-only
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1C_READINGS, ids=[row[0] for row in R1C_READINGS],
)
def test_r1c_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


# --------------------------------------------------------------------------------------
# r1d (prompts/ad-1328-s1-repair-r1d.md) -- the final fuzz and the enumerative run
#   Class E: an escaped leading '~' is dynamic like a bare one (oracle S22).
#   Class F: '.', '[' or '`' after a single-dash parameter name (oracle S23 pins the accepted forms live).
# --------------------------------------------------------------------------------------

R1D_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1d_ps_dash_dot", "powershell", "echo -qq.zz", "line", "after a -name", "echo --qq.zz"),
    ("r1d_ps_dash_trailing_dot", "powershell", "echo -qq.", "line", "after a -name", "echo -qq"),
    ("r1d_ps_dash_two_words", "powershell", "echo -a.b -c.d", "line", "after a -name", "echo -a -c"),
    ("r1d_ps_dash_equals_dot", "powershell", "echo -o=a.txt", "line", "after a -name", "echo --output=a.txt"),
    ("r1d_ps_dash_underscore", "powershell", "echo -_a.b", "line", "after a -name", "echo -_ab"),
    ("r1d_ps_dash_question", "powershell", "echo -?.b", "line", "after a -name", "echo -?"),
    ("r1d_ps_dash_backtick", "powershell", "echo -qq`zz", "line", "after a -name", "echo --qq`zz"),
    ("r1d_ps_dash_backtick_dollar", "powershell", "echo -qq`$zz", "line", "after a -name", "echo -qqzz"),
    ("r1d_ps_dash_escaped_name_dot", "powershell", "echo -`qq.zz", "line", "after a -name", "echo -`qq"),
    ("r1d_ps_dash_dynamic_dot", "powershell", "echo -a*.b", "line", "after a -name", "echo -a*b"),
    ("r1d_ps_dash_dot_before_colon", "powershell", "echo -a.b:c", "line", "after a -name", "echo -a:b.c"),
    ("r1d_ps_dash_include_dot", "powershell", "gcc -I.", "line", "after a -name", "gcc -I ."),
    ("r1d_ps_dash_variable_dot", "powershell", "echo -a$x.b", "line", "member access", "echo -ax-b"),
]


def test_r1d_refusals_table() -> None:
    ids = [row[0] for row in R1D_REFUSALS]
    assert len(R1D_REFUSALS) == 13
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS} | {row[0] for row in R1B_REFUSALS} | {row[0] for row in R1C_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1D_REFUSALS, ids=[row[0] for row in R1D_REFUSALS],
)
def test_r1d_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1D_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("e_mid_word", "powershell", "echo a`~b", ("echo", "a~b"), (False, False)),  # oracle S22
    ("e_trailing", "powershell", "echo x`~", ("echo", "x~"), (False, False)),
    ("e_escaped_backtick", "powershell", "echo ``~", ("echo", "`~"), (False, False)),
    # r1e (rule G) changed this row from (False, False) to (False, True): a quoted leading '~' is dynamic too.
    ("e_quoted", "powershell", "echo '~'", ("echo", "~"), (False, True)),  # oracle S22
    # r1e (rule G) changed this row from (False, False, False) to (False, True, True): an escaped '*' or '?' is dynamic.
    ("e_escaped_glob_literal", "powershell", "echo `*.nomatch `?x", ("echo", "*.nomatch", "?x"), (False, True, True)),
    ("f_double_dash", "powershell", "echo --a.b --output=a.txt", ("echo", "--a.b", "--output=a.txt"), (False,) * 3),  # S23
    ("f_plain_parameters", "powershell", "echo -Wall -O2 -DFOO=bar -a=b", ("echo", "-Wall", "-O2", "-DFOO=bar", "-a=b"), (False,) * 5),  # S23
    ("f_no_name", "powershell", "echo - -= -.", ("echo", "-", "-=", "-."), (False,) * 4),  # S23
    ("f_colon_dot", "powershell", "echo -a:b.c", ("echo", "-a:b.c"), (False, False)),  # S23
    ("f_escaped_dash", "powershell", "echo `-a.b", ("echo", "-a.b"), (False, False)),  # S23
    ("f_escaped_name", "powershell", "echo -`qq", ("echo", "-qq"), (False, False)),  # measured: -`qq -> -qq
    ("f_dash_dash_backtick", "powershell", "echo --qq`zz", ("echo", "--qqzz"), (False, False)),  # measured: --qqzz
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1D_READINGS, ids=[row[0] for row in R1D_READINGS],
)
def test_r1d_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


# --------------------------------------------------------------------------------------
# r1e (prompts/ad-1328-s1-repair-r1e.md) -- class G: a Windows program expands what PowerShell passes it unquoted
#   (oracle S24 pins the marks; the expansion was measured with an MSYS2 ls.exe, which the argv probe cannot show).
# --------------------------------------------------------------------------------------

R1E_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1e_ps_quoted_glob_program", "powershell", "& 'g*t' status", "segment", "not a literal word", "& 'git' status"),
    ("r1e_cmd_caret_star", "cmd", "echo ^*.txt", "line", "'^'", 'echo "*.txt"'),
]


def test_r1e_refusals_table() -> None:
    ids = [row[0] for row in R1E_REFUSALS]
    assert len(R1E_REFUSALS) == 2
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS + R1B_REFUSALS + R1C_REFUSALS + R1D_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1E_REFUSALS, ids=[row[0] for row in R1E_REFUSALS],
)
def test_r1e_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1E_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("g_single_quoted_star", "powershell", "echo '*.txt'", ("echo", "*.txt"), (False, True)),  # measured: ls.exe expands
    ("g_double_quoted_question", "powershell", 'echo "?.txt"', ("echo", "?.txt"), (False, True)),
    ("g_quoted_bracket", "powershell", "echo '[ab].txt'", ("echo", "[ab].txt"), (False, True)),  # measured
    ("g_escaped_star", "powershell", "echo `*.txt", ("echo", "*.txt"), (False, True)),  # measured
    ("g_quoted_brace", "powershell", "echo '{a,b}'", ("echo", "{a,b}"), (False, True)),  # Cygwin GLOB_BRACE
    ("g_quoted_at_start", "powershell", "echo '@args.txt'", ("echo", "@args.txt"), (False, True)),  # Cygwin @file
    ("g_quoted_tilde_start", "powershell", "echo '~/x'", ("echo", "~/x"), (False, True)),  # Cygwin GLOB_TILDE
    ("g_equals_escaped_star", "powershell", "echo --x=`*", ("echo", "--x=*"), (False, True)),
    ("g_blank_keeps_literal", "powershell", "echo 'a *.txt'", ("echo", "a *.txt"), (False, False)),  # measured: quoted
    ("g_at_mid_word", "powershell", "echo 'a@b'", ("echo", "a@b"), (False, False)),
    ("g_tilde_mid_word", "powershell", "echo 'a~b'", ("echo", "a~b"), (False, False)),
    ("g_plain_quoted", "powershell", "echo 'a.txt'", ("echo", "a.txt"), (False, False)),
    ("g_cmd_quoted_glob", "cmd", 'echo "*.txt"', ("echo", "*.txt"), (False, True)),  # unchanged (:726)
    ("g_cmd_quoted_at", "cmd", 'echo "@a"', ("echo", "@a"), (False, False)),  # unchanged: cmd keeps the quotes
    ("g_posix_quoted_glob", "posix", "echo '*.txt'", ("echo", "*.txt"), (False, False)),  # unchanged
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1E_READINGS, ids=[row[0] for row in R1E_READINGS],
)
def test_r1e_readings(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


def test_r1e_quoted_wildcard_is_variadic() -> None:
    segment = parse_command("echo '*.txt'", dialect="powershell").segments[0]
    assert segment.variadic == (False, True)


def test_r1e_restrictive_rule_sees_through_a_quoted_wildcard() -> None:
    config = CommandPolicyConfig.model_validate(
        {
            "rules": [
                {
                    "name": "no-force",
                    "pattern": ["git", "push", "--force"],
                    "decision": "forbid",
                    "justification": "no force push",
                    "alternative": "push without --force",
                }
            ],
            "unmatched_decision": "allow",
            "unparseable_decision": "escalate",
        }
    )
    assert evaluate_command(config, "git push origin main", dialect="powershell").decision == "allow"  # control
    for command in ("git push '--f*'", 'git push "--f*"', "git push `--f*"):
        assert evaluate_command(config, command, dialect="powershell").decision == "forbid", command


# --------------------------------------------------------------------------------------
# r2 (prompts/ad-1328-s1-repair-r2.md) -- adversarial review round 2, F1-F5
#   F1: a value PowerShell computes ($ variable, @ splat, leading '~') is refused.
#   F2: a line of two or more segments proves no bare program's lookup context.
#   F3: terminals, consoles, PTY hosts and the other launchers are opaque.
#   F4: an assignment after a process wrapper is refused.
#   F5: a relative program path, or a POSIX path with '..', has no argv identity; a name is keyed as written.
# --------------------------------------------------------------------------------------

_R2_COMPUTED = "a value PowerShell computes"
_R2_AFTER_WRAPPER = "after the process wrapper"
_R2_ANOTHER = "another command in the line"

R2_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    # F1 -- every producer of a PowerShell computed value (review r2 executed the first on 5.1 and 7)
    ("r2_ps_env_variable", "powershell", "receiver.cmd $env:CP_WORD", "line", _R2_COMPUTED, "receiver.cmd CP_WORD"),
    ("r2_ps_plain_variable", "powershell", "echo before $x tail last", "line", _R2_COMPUTED, "echo before x tail last"),
    ("r2_ps_scoped_variable", "powershell", "echo $script:x", "line", _R2_COMPUTED, "echo script-x"),
    ("r2_ps_braced_variable", "powershell", "echo ${x}", "line", _R2_COMPUTED, "echo x"),
    ("r2_ps_braced_scoped_variable", "powershell", "echo ${env:PATH}", "line", _R2_COMPUTED, "echo env-PATH"),
    ("r2_ps_automatic_variable", "powershell", "echo $HOME", "line", _R2_COMPUTED, "echo HOME"),
    ("r2_ps_special_question", "powershell", "echo $?", "line", _R2_COMPUTED, "echo q"),
    ("r2_ps_special_caret", "powershell", "echo $^", "line", _R2_COMPUTED, "echo c"),
    ("r2_ps_special_dollar", "powershell", "echo $$", "line", _R2_COMPUTED, "echo d"),
    ("r2_ps_quoted_variable", "powershell", 'echo "$x"', "line", _R2_COMPUTED, 'echo "x"'),
    ("r2_ps_interpolated", "powershell", 'echo "a $x b"', "line", _R2_COMPUTED, 'echo "a x b"'),
    ("r2_ps_interpolated_scoped", "powershell", 'echo "$env:W"', "line", _R2_COMPUTED, 'echo "env-W"'),
    ("r2_ps_interpolated_digit", "powershell", 'echo "cost $5"', "line", _R2_COMPUTED, 'echo "cost 5"'),
    ("r2_ps_concatenated_before", "powershell", "echo pre$x", "line", _R2_COMPUTED, "echo prex"),
    ("r2_ps_concatenated_after", "powershell", "echo $x-post", "line", _R2_COMPUTED, "echo x-post"),
    ("r2_ps_splat", "powershell", "git push @args", "line", _R2_COMPUTED, "git push args"),
    ("r2_ps_splat_then_words", "powershell", "git @a --force", "line", _R2_COMPUTED, "git a --force"),
    ("r2_ps_call_variable", "powershell", "& $x", "line", _R2_COMPUTED, "& x"),
    ("r2_ps_call_variable_path", "powershell", "& $d/git push", "line", _R2_COMPUTED, "& d/git push"),
    ("r2_ps_redirect_variable", "powershell", "echo a > $null", "line", _R2_COMPUTED, "echo a > w.txt"),
    ("r2_ps_tilde", "powershell", "echo ~", "line", _R2_COMPUTED, "echo '~'"),
    ("r2_ps_tilde_path", "powershell", "echo ~/x", "line", _R2_COMPUTED, "echo '~/x'"),
    ("r2_ps_escaped_tilde", "powershell", "echo `~", "line", _R2_COMPUTED, "echo a`~b"),
    ("r2_ps_escaped_tilde_path", "powershell", "echo `~/x", "line", _R2_COMPUTED, "echo x`~"),
    ("r2_ps_escaped_tilde_name", "powershell", "echo `~x", "line", _R2_COMPUTED, "echo ``~"),
    (
        "r2_cmd_wrapped_variable", "cmd", 'powershell -NoProfile -Command "echo $x"', "segment", _R2_COMPUTED,
        'powershell -NoProfile -Command "echo x"',
    ),
    # F4 -- an assignment after a process wrapper (review r2 executed the first on bash)
    ("r2_time_assignment", "posix", "time X=1 p push --force", "segment", _R2_AFTER_WRAPPER, "time p push --force"),
    ("r2_time_twice_assignment", "posix", "time time X=1 p", "segment", _R2_AFTER_WRAPPER, "time time p"),
    ("r2_time_quoted_value", "posix", "time X='a b' p", "segment", _R2_AFTER_WRAPPER, "X='a b' p"),
    ("r2_time_assignment_only", "posix", "time X=1", "segment", _R2_AFTER_WRAPPER, "time x"),
    ("r2_time_assignment_then_wrapper", "posix", "time X=1 nice p", "segment", _R2_AFTER_WRAPPER, "time nice p"),
    ("r2_leading_then_timed_assignment", "posix", "A=1 time B=2 p", "segment", _R2_AFTER_WRAPPER, "A=1 time p"),
    ("r2_nohup_assignment", "posix", "nohup X=1 p", "segment", _R2_AFTER_WRAPPER, "nohup p"),
    ("r2_command_assignment", "posix", "command X=1 p", "segment", _R2_AFTER_WRAPPER, "command p"),
    ("r2_timeout_assignment", "posix", "timeout 5 X=1 p", "segment", _R2_AFTER_WRAPPER, "timeout 5 p"),
    ("r2_stdbuf_assignment", "posix", "stdbuf -oL X=1 p", "segment", _R2_AFTER_WRAPPER, "stdbuf -oL p"),
]


def test_r2_refusals_table() -> None:
    ids = [row[0] for row in R2_REFUSALS]
    assert len(R2_REFUSALS) == 36
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS + R1B_REFUSALS + R1C_REFUSALS + R1D_REFUSALS + R1E_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R2_REFUSALS, ids=[row[0] for row in R2_REFUSALS],
)
def test_r2_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R2_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("r2_time_program", "posix", "time p push --force", ("p", "push", "--force"), (False, False, False)),
    ("r2_time_quoted_name_is_the_program", "posix", 'time "X"=1 p', ("X=1", "p"), (False, False)),  # bash runs X=1
    ("r2_assignment_before_time", "posix", "X=1 time p", ("p",), (False,)),
    ("r2_ps_quoted_tilde", "powershell", "echo '~'", ("echo", "~"), (False, True)),  # rule G; PowerShell passes it as is
    ("r2_ps_glob_still_variadic", "powershell", "echo *.txt", ("echo", "*.txt"), (False, True)),
    ("r2_ps_single_quoted_dollar", "powershell", "echo '$x'", ("echo", "$x"), (False, False)),
    ("r2_ps_escaped_dollar", "powershell", "echo `$x", ("echo", "$x"), (False, False)),
    ("r2_posix_variable_unchanged", "posix", "echo $x", ("echo", ""), (False, True)),
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R2_READINGS, ids=[row[0] for row in R2_READINGS],
)
def test_r2_readings(case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...]) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


def _r2_policy(*rules: dict[str, Any]) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate(
        {"rules": list(rules), "unmatched_decision": "allow", "unparseable_decision": "escalate"}
    )


def _r2_forbid(program: str) -> dict[str, Any]:
    return {"name": f"no-{program}", "pattern": [program], "decision": "forbid", "justification": "r2", "alternative": "other"}


def _r2_pinned(program: str, pin: str) -> dict[str, Any]:
    return {"name": f"{program}-ok", "pattern": [program], "decision": "allow", "justification": "r2", "host_executable": [pin]}


def test_r2_computed_value_is_not_one_allowed_segment() -> None:
    # The review's executed chain: a policy forbidding `secondary` allowed `receiver.cmd $env:CP_WORD`, and both
    # PowerShell versions ran secondary.cmd. Now the line cannot be read, so it escalates.
    config = _r2_policy(_r2_forbid("secondary"))
    assert evaluate_command(config, "receiver.cmd alpha", dialect="powershell").decision == "allow"  # control
    assert evaluate_command(config, "secondary.cmd", dialect="powershell").decision == "forbid"  # control
    result = evaluate_command(config, "receiver.cmd $env:CP_WORD", dialect="powershell")
    assert result.unparseable is not None and _R2_COMPUTED in result.unparseable
    assert result.decision == "escalate"


# The literal of Section 3's r2 names, including forfiles and start, which moved out of the cmd-only set: 87.
R2_LAUNCHERS = (
    "mintty", "winpty", "wt", "windowsterminal", "conhost", "openconsole", "conemu", "conemu64", "conemuc",
    "conemuc64", "tmux", "screen", "byobu", "dtach", "abduco", "unbuffer", "socat", "rlwrap", "openvt", "xterm",
    "uxterm", "gnome-terminal", "kgx", "ptyxis", "konsole", "xfce4-terminal", "mate-terminal", "lxterminal",
    "qterminal", "terminator", "tilix", "urxvt", "rxvt", "st", "foot", "footclient", "kitty", "alacritty", "wezterm",
    "wezterm-gui", "ghostty", "terminology", "sakura", "x-terminal-emulator",
    "psexec", "psexec64", "paexec", "gsudo", "winrs", "wmic", "schtasks", "at", "batch", "mosh", "rsh",
    "start-stop-daemon", "daemonize", "chpst", "setuidgid", "envdir", "envuidgid", "softlimit", "prlimit", "cgexec",
    "systemd-nspawn", "xvfb-run", "dbus-launch", "dbus-run-session", "faketime", "fakeroot", "proot", "torsocks",
    "proxychains", "proxychains4", "tsocks", "entr", "catchsegv", "caffeinate", "sandbox-exec", "arch",
    "explorer", "rundll32", "pcalua", "xdg-open", "open", "forfiles", "start",
)


def test_r2_launcher_literal() -> None:
    assert len(R2_LAUNCHERS) == 87
    assert len(set(R2_LAUNCHERS)) == 87


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("name", R2_LAUNCHERS)
def test_r2_launchers_are_opaque(name: str, dialect: Dialect) -> None:
    _accepted("pytest -e python x", dialect)  # control: an ordinary program with the same arguments is read
    parsed = parse_command(f"{name} -e python x", dialect=dialect)
    assert parsed.unparseable is None, parsed.unparseable  # premise: the line reads; the segment is what is refused
    (segment,) = parsed.segments
    # cmd reads `start-stop-daemon` as its internal `start` first; every other case is the launcher reason
    expected = "may split" if (dialect, name) == ("cmd", "start-stop-daemon") else "runs a command the policy cannot see"
    assert segment.unparseable is not None and expected in segment.unparseable, segment.unparseable
    assert evaluate_command(_r2_policy(_r2_forbid("python")), f"{name} -e python x", dialect=dialect).decision == "escalate"


def test_r2_terminal_child_is_not_allowed() -> None:
    # The review's executed forms (cmd and PowerShell 5.1 started python through mintty while the policy allowed it).
    config = _r2_policy(_r2_forbid("python"))
    mintty = '"C:\\Program Files\\Git\\usr\\bin\\mintty.exe"'
    tail = " -w hide -h never -e python C:\\w\\terminal_marker.py tag push --force"
    assert evaluate_command(config, "python x", dialect="cmd").decision == "forbid"  # control
    for dialect, command in (("cmd", mintty + tail), ("powershell", "& " + mintty + tail), ("posix", "mintty -e python x")):
        result = evaluate_command(config, command, dialect=dialect)
        assert result.unparseable is None, (dialect, result.unparseable)
        (verdict,) = result.segments
        assert verdict.basis == "unparseable" and "runs a command the policy cannot see" in str(verdict.segment.unparseable)
        assert result.decision == "escalate", dialect


R2_LOOKUP_LINES: list[tuple[str, Dialect, str, str, str]] = [
    # (id, dialect, command, pinned program, its pin) -- review r2 executed the first two on 5.1 and 7, and posix_read
    ("ps_environment_provider", "powershell", "Set-Item Environment::PATH C:\\other; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_colon_parameters", "powershell", "Set-Item -Path:Env:PATH -Value:C:\\other; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_file_on_path", "powershell", "Copy-Item C:\\evil\\selected.cmd C:\\tools\\selected.cmd; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_mutation_after", "powershell", "selected; Set-Item Environment::PATH C:\\other", "selected", "C:\\pins\\selected.cmd"),
    ("ps_pipeline", "powershell", "Get-ChildItem | selected", "selected", "C:\\pins\\selected.cmd"),
    ("cmd_file_in_working_directory", "cmd", "copy C:\\evil\\git.exe git.exe & git status", "git", "C:\\pins\\git.exe"),
    ("posix_read", "posix", "read PATH < /dev/null; git status", "git", "/usr/bin/git"),
    ("posix_printf_v", "posix", "printf -v PATH /tmp/x; git status", "git", "/usr/bin/git"),
    ("posix_builtin_true", "posix", "true; git status", "git", "/usr/bin/git"),
    ("posix_substitution", "posix", "echo $(git status)", "git", "/usr/bin/git"),
    ("posix_wrapped_script", "posix", "sh -c 'read PATH; git status'", "git", "/usr/bin/git"),
]


@pytest.mark.parametrize(
    ("dialect", "command", "program", "pin"), [pytest.param(*row[1:], id=row[0]) for row in R2_LOOKUP_LINES],
)
def test_r2_another_segment_leaves_a_pinned_name_unproven(dialect: Dialect, command: str, program: str, pin: str) -> None:
    config = _r2_policy(_r2_pinned(program, pin))
    resolve = {program: pin}.get
    alone = evaluate_command(config, program, dialect=dialect, resolve_program=resolve)  # control: one segment proves
    assert alone.decision == "allow"
    result = evaluate_command(config, command, dialect=dialect, resolve_program=resolve)
    assert result.unparseable is None
    pinned = [verdict for verdict in result.segments if verdict.segment.tokens[:1] == (program,)]
    assert len(pinned) == 1, [verdict.segment.tokens for verdict in result.segments]
    (verdict,) = pinned
    assert verdict.segment.unparseable is None  # premise: read, so the forbid below is the lookup rule
    assert verdict.segment.lookup_changed is not None and _R2_ANOTHER in verdict.segment.lookup_changed
    (match,) = verdict.matches
    assert (match.decision, match.pin_violation) == ("forbid", True)
    assert _R2_ANOTHER in match.justification
    assert result.decision == "forbid"


def test_r2_an_absolute_path_keeps_its_proof_in_a_longer_line() -> None:
    config = _r2_policy(_r2_pinned("git", "/usr/bin/git"))
    result = evaluate_command(config, "read PATH < /dev/null; /usr/bin/git status", dialect="posix")
    assert result.segments[1].segment.lookup_changed is not None  # premise: the context is unproven
    assert result.decision == "allow"


def test_r2_a_posix_path_with_dotdot_proves_no_pin() -> None:
    control = _r2_policy(_r2_pinned("git", "/usr/bin/git"))
    assert evaluate_command(control, "/usr/bin/git status", dialect="posix").decision == "allow"  # control
    assert evaluate_command(control, "/usr/local/../bin/git status", dialect="posix").decision == "forbid"
    by_resolver = evaluate_command(control, "git status", dialect="posix", resolve_program={"git": "/usr/local/../bin/git"}.get)
    assert by_resolver.decision == "forbid"
    # r3: a '..' pin is refused when the policy is read (review r3, F3), so it never reaches evaluation
    with pytest.raises(ValueError, match=r"has a '\.' or '\.\.' component"):
        _r2_policy(_r2_pinned("git", "/opt/../usr/bin/git"))


R2_IDENTITY: list[tuple[str, Dialect, str, str, str]] = [
    # (id, dialect, an unproven spelling, the bare name, an absolute path a resolver may answer for the name)
    ("ps_dot_backslash", "powershell", ".\\selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_dot_slash", "powershell", "./selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_parent", "powershell", "sub\\..\\selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_drive_relative", "powershell", "C:selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_root_relative", "powershell", "\\tools\\selected", "selected", "C:\\pins\\selected.exe"),
    ("cmd_dot_backslash", "cmd", ".\\selected", "selected", "C:\\pins\\selected.exe"),
    ("cmd_parent", "cmd", "sub\\..\\selected", "selected", "C:\\pins\\selected.exe"),
    ("posix_dot_slash", "posix", "./selected", "selected", "/usr/bin/selected"),
    ("posix_parent", "posix", "sub/../selected", "selected", "/usr/bin/selected"),
    ("posix_absolute_parent", "posix", "/opt/x/../selected", "selected", "/usr/bin/selected"),
]


@pytest.mark.parametrize(
    ("dialect", "spelled", "bare", "answer"), [pytest.param(*row[1:], id=row[0]) for row in R2_IDENTITY],
)
def test_r2_unproven_program_paths_have_script_keys(dialect: Dialect, spelled: str, bare: str, answer: str) -> None:
    # The review: `selected` and `.\selected` shared a key under every resolver exit, yet ran different programs.
    for resolve in (None, {}.get, lambda name: None, {bare: answer}.get):
        name = canonical_command(f"{bare} a", dialect=dialect, resolve_program=resolve)
        assert name.kind == "argv"  # control
        path = canonical_command(f"{spelled} a", dialect=dialect, resolve_program=resolve)
        assert (path.kind, path.dialect, path.parts) == ("script", dialect, (f"{spelled} a",))
        assert path.key != name.key


def test_r2_absolute_paths_keep_argv_identity() -> None:
    windows = canonical_command("C:\\x\\..\\pins\\selected.exe a", dialect="cmd")  # Windows resolves '..' in the text
    assert (windows.kind, windows.parts) == ("argv", ("c:\\pins\\selected.exe", "a"))
    assert canonical_command("\\\\srv\\share\\selected.exe a", dialect="cmd").kind == "argv"  # a UNC path
    assert canonical_command("/usr/./bin/selected a", dialect="posix").parts == ("/usr/bin/selected", "a")


def test_r2_a_name_is_keyed_as_written() -> None:
    for dialect in ("cmd", "powershell"):
        plain = canonical_command("git status", dialect=dialect)
        assert plain.parts == ("git", "status")  # control
        assert canonical_command("GIT status", dialect=dialect).key == plain.key  # Windows names fold case
        assert canonical_command("git.exe status", dialect=dialect).key != plain.key  # PATHEXT may find git.cmd first
        assert canonical_command("git.cmd status", dialect=dialect).key != canonical_command("git.exe status", dialect=dialect).key
    assert canonical_command("Git status", dialect="posix").key != canonical_command("git status", dialect="posix").key
    # a resolver's relative or POSIX '..' answer is no identity: the key stays the name
    relative = canonical_command("git status", dialect="cmd", resolve_program={"git": "bin\\git.exe"}.get)
    assert relative.parts == ("git", "status")
    dotted = canonical_command("git status", dialect="posix", resolve_program={"git": "/opt/x/../bin/git"}.get)
    assert dotted.parts == ("git", "status")


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
    """Generated program names that no table refuses. Bounded: a change that taints every name must fail the test that
    asserts the count, not hang collection (mutant M128 did, before this bound)."""
    rng = random.Random(seed)
    names: dict[str, None] = {}
    for _ in range(count * 50):
        if len(names) == count:
            break
        name = "zq" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
        if _r3_untabled(name):
            names[name] = None
    return tuple(names)


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
    names = _r3_names()
    assert len(names) == 200 and all(_r3_untabled(name) for name in names)  # premise
    for head in _R3_HEADS[dialect]:
        assert policy.evaluate(f"{head} x").decision == "forbid", head  # control: each head is forbidden directly
    failures: list[tuple[str, object, object]] = []
    for name in names:
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
