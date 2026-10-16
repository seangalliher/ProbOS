"""AD-1328 S1 (#1530), milestone M2 -- the command tokenizer and the canonical command.

Tests only. They read ``parse_command`` and ``canonical_command`` against decisions D3 (tokenizer)
and D6 (canonical command) of ``prompts/ad-1328-s1-command-policy-core.md`` and assert on
``ParsedCommand`` / ``CommandSegment`` / ``CanonicalCommand`` fields only.

* Every dialect is passed explicitly, so the file passes on Linux and on Windows. Only
  ``test_dialects`` calls the platform default, and it compares it with ``default_dialect()``.
* No filesystem, subprocess or environment access. A resolver is a plain function over a dict;
  limits are built with ``CommandPolicyConfig.model_validate`` from plain dicts.
* An input that carries a control character, a line break, a line continuation or a non-ASCII
  character is written with an explicit escape, never a literal one, so a CRLF checkout cannot
  change what is tested.
* Each case asserts its own premise and has a negative control: the accepted neighbour, checked
  FIRST, differs from the refused input by the one thing under test.

Mutants this file kills (contract table "Mutation campaign of record"):
E15 E17 E18 E19a E19b E20 E21 E22 E23 E24 E25 E26 E27 E28 E29 E32 E33 E34 E41 E42 E43 E44 E45 E46
E47 E50. Where one row of the contract cannot kill its mutant alone (E25: an empty program is also
unparseable) a further row does, and says so beside it.
"""

from __future__ import annotations

import hashlib
import shlex
import string
import time
from typing import Any

import pytest

from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_policy import (
    CANONICAL_KEY_SCHEME,
    CanonicalCommand,
    CommandSegment,
    Dialect,
    ParsedCommand,
    canonical_command,
    default_dialect,
    parse_command,
)

DIALECTS: tuple[Dialect, ...] = ("posix", "cmd", "powershell")
_CANONICAL_DOMAIN_V1 = b"probos.command_policy/canonical_command/v1\x00"


# --------------------------------------------------------------------------------------
# Helpers (local copies: nothing is imported across test files)
# --------------------------------------------------------------------------------------


def _limits(**bounds: int) -> CommandPolicyConfig:
    """Limits as an operator's YAML would deliver them: a plain dict through ``model_validate``."""
    return CommandPolicyConfig.model_validate(bounds)


def tokens(command: str, dialect: Dialect, **kwargs: Any) -> list[tuple[str, ...]]:
    return [segment.tokens for segment in parse_command(command, dialect=dialect, **kwargs).segments]


def programs(command: str, dialect: Dialect, **kwargs: Any) -> list[str]:
    return [segment.tokens[0] for segment in parse_command(command, dialect=dialect, **kwargs).segments]


def _accepted(command: str, dialect: Dialect, **kwargs: Any) -> ParsedCommand:
    """The accepted neighbour: the whole line parses and yields at least one segment."""
    parsed = parse_command(command, dialect=dialect, **kwargs)
    assert isinstance(parsed, ParsedCommand)
    assert parsed.dialect == dialect
    assert parsed.unparseable is None, f"{command!r} should parse under {dialect}: {parsed.unparseable}"
    assert parsed.segments, f"{command!r} should yield a segment under {dialect}"
    return parsed


def _only(command: str, dialect: Dialect, **kwargs: Any) -> CommandSegment:
    """The accepted neighbour that is exactly one segment."""
    parsed = _accepted(command, dialect, **kwargs)
    assert len(parsed.segments) == 1, f"{command!r} should be one segment, got {[s.tokens for s in parsed.segments]}"
    segment = parsed.segments[0]
    assert isinstance(segment, CommandSegment)
    return segment


def _refused_line(command: str, dialect: Dialect, reason: str, **kwargs: Any) -> None:
    """The whole line is unparseable: no segment at all, and the reason contains ``reason``."""
    parsed = parse_command(command, dialect=dialect, **kwargs)
    assert parsed.dialect == dialect
    assert parsed.segments == (), f"{command!r} must yield no segment under {dialect}, got {parsed.segments}"
    assert parsed.unparseable is not None, f"{command!r} must be unparseable under {dialect}"
    assert reason in parsed.unparseable, f"{command!r}: expected {reason!r} in {parsed.unparseable!r}"


def _expected_key(kind: str, dialect: str | None, parts: tuple[str, ...], domain: bytes = _CANONICAL_DOMAIN_V1) -> str:
    # Imported lazily, as the source does: importing the federation package at collection time is not needed.
    from probos.federation.ard.jcs import canonicalize

    return hashlib.sha256(domain + canonicalize([kind, dialect, list(parts)])).hexdigest()


# --------------------------------------------------------------------------------------
# M2 #1 -- dialects                                                      Kills E44, E45
# --------------------------------------------------------------------------------------


def test_dialects() -> None:
    # The platform picks the default: cmd on win32 (what create_subprocess_shell starts there), posix elsewhere.
    for platform in ("linux", "darwin", "freebsd", "cygwin"):
        assert default_dialect(platform) == "posix", platform
    assert default_dialect("win32") == "cmd"
    assert default_dialect() in ("posix", "cmd")
    assert parse_command("ls").dialect == default_dialect()
    assert parse_command("ls", dialect=None).dialect == default_dialect()
    # An explicit dialect is honoured, whatever the host.
    for dialect in DIALECTS:
        assert parse_command("ls", dialect=dialect).dialect == dialect
    # A dialect that is not one of the three is a programming error, not an unparseable command.
    for bad in ("bash", 1, b"posix", "POSIX", ""):
        with pytest.raises(ValueError) as refused:
            parse_command("ls", dialect=bad)
        assert str(refused.value) == "command_policy_dialect_invalid", repr(bad)
    # A non-str command is a programming error too; an empty str is merely unparseable.
    assert parse_command("", dialect="posix").unparseable is not None
    for bad_command in (b"ls", 1, None, ["ls"]):
        with pytest.raises(TypeError):
            parse_command(bad_command, dialect="posix")
    # canonical_command shares both refusals.
    with pytest.raises(ValueError) as refused:
        canonical_command("ls", dialect="bash")
    assert str(refused.value) == "command_policy_dialect_invalid"
    with pytest.raises(TypeError):
        canonical_command(b"ls", dialect="posix")


# --------------------------------------------------------------------------------------
# M2 #2 -- simple words
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", DIALECTS)
def test_simple_words(dialect: Dialect) -> None:
    # Negative control: an unbalanced quote among the same words yields no segment at all.
    broken = parse_command('git status "-s', dialect=dialect)
    assert broken.segments == ()
    assert broken.unparseable is not None

    parsed = parse_command("git status -s", dialect=dialect)
    assert parsed.dialect == dialect
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    (segment,) = parsed.segments
    assert segment.dialect == dialect
    assert segment.tokens == ("git", "status", "-s")
    assert segment.raw == ("git", "status", "-s")
    assert segment.dynamic == (False, False, False)
    assert segment.assignments == ()
    assert segment.redirections == ()
    assert segment.wrappers == ()
    assert segment.depth == 0
    assert segment.unparseable is None
    # Spaces and tabs between words are not significant.
    assert tokens("  git \t status   -s  ", dialect) == [("git", "status", "-s")]


# --------------------------------------------------------------------------------------
# M2 #3 -- POSIX quoting
# --------------------------------------------------------------------------------------

POSIX_QUOTING = [
    # Negative control first: unquoted, the space splits; quoted (next row), it does not.
    pytest.param("echo a b", ("echo", "a", "b"), id="unquoted_space_splits"),
    pytest.param("echo 'a b'", ("echo", "a b"), id="single_quotes_group"),
    pytest.param(
        "git commit -m 'a b' \"c d\" e\\ f",
        ("git", "commit", "-m", "a b", "c d", "e f"),
        id="single_double_and_escaped_space",
    ),
    pytest.param("echo ''", ("echo", ""), id="empty_single_quotes_are_an_empty_word"),
    pytest.param('echo "a\\"b"', ("echo", 'a"b'), id="escaped_quote_inside_double_quotes"),
    pytest.param("echo 'it'\"'\"'s'", ("echo", "it's"), id="single_quote_spliced_through_double_quotes"),
    pytest.param('echo "a\\\\b"', ("echo", "a\\b"), id="escaped_backslash_inside_double_quotes"),
    pytest.param("git \\\nstatus", ("git", "status"), id="line_continuation_is_removed"),
    pytest.param("echo 'a\\b'", ("echo", "a\\b"), id="single_quotes_keep_a_backslash"),
    pytest.param('echo "a\\b"', ("echo", "a\\b"), id="double_quotes_keep_a_backslash_before_an_ordinary_character"),
    pytest.param('echo a"b c"d', ("echo", "ab cd"), id="adjacent_quoting_concatenates"),
    pytest.param('echo "a\\\nb"', ("echo", "ab"), id="line_continuation_inside_double_quotes"),
]


@pytest.mark.parametrize(("command", "expected"), POSIX_QUOTING)
def test_posix_quoting(command: str, expected: tuple[str, ...]) -> None:
    segment = _only(command, "posix")
    assert segment.tokens == expected
    assert segment.dynamic == (False,) * len(expected)
    assert segment.unparseable is None


# --------------------------------------------------------------------------------------
# M2 #4 -- cmd quoting
# --------------------------------------------------------------------------------------

CMD_QUOTING = [
    # Negative control first: an unquoted & separates.
    pytest.param("echo a&b", [("echo", "a"), ("b",)], id="unquoted_ampersand_separates"),  # oracle C05
    pytest.param('echo "a&b"', [("echo", "a&b")], id="quoted_ampersand_stays_one_segment"),  # oracle C02
    # `^` and a newline are refused in cmd (F3, F11): their refusal rows are in test_finding_refusals.
    pytest.param('echo a"b c"d', [("echo", "ab cd")], id="adjacent_quoting_concatenates"),  # oracle C03
]


@pytest.mark.parametrize(("command", "expected"), CMD_QUOTING)
def test_cmd_quoting(command: str, expected: list[tuple[str, ...]]) -> None:
    parsed = _accepted(command, "cmd")
    assert [segment.tokens for segment in parsed.segments] == expected
    assert all(not any(segment.dynamic) for segment in parsed.segments)


# --------------------------------------------------------------------------------------
# M2 #5 -- PowerShell quoting
# --------------------------------------------------------------------------------------

POWERSHELL_QUOTING = [
    # Negative control first: an unquoted ; separates.
    pytest.param("echo a;b", [("echo", "a"), ("b",)], id="unquoted_semicolon_separates"),
    pytest.param("echo 'a;b'", [("echo", "a;b")], id="single_quoted_semicolon_stays"),
    pytest.param(
        "git commit -m 'it''s fine' 'a b' \"c d\"",
        [("git", "commit", "-m", "it's fine", "a b", "c d")],
        id="doubled_single_quote_in_a_value_with_a_blank",  # oracle S02, S03
    ),
    pytest.param("echo 'a`b'", [("echo", "a`b")], id="single_quotes_keep_a_backtick"),
    pytest.param("echo a` b", [("echo", "a b")], id="backtick_escapes_a_space"),  # oracle S04
]


@pytest.mark.parametrize(("command", "expected"), POWERSHELL_QUOTING)
def test_powershell_quoting(command: str, expected: list[tuple[str, ...]]) -> None:
    parsed = _accepted(command, "powershell")
    assert [segment.tokens for segment in parsed.segments] == expected
    assert all(not any(segment.dynamic) for segment in parsed.segments)


# --------------------------------------------------------------------------------------
# M2 #5b -- PowerShell backtick escapes that expand to another character
# --------------------------------------------------------------------------------------

_PS_EXPANDING = "0abefnrtuv"  # a backtick before any of these is another character in PowerShell, not the plain one
_PS_REASON = "expands to another character"

# (a template with one {esc} hole, a stand-in for the escape; the escape's own trailing text)
_PS_ESCAPE_SITES = [
    pytest.param("git push a{esc}b", id="bare_word_argument"),
    pytest.param("g{esc}it status", id="bare_word_program"),
    pytest.param('git push "a{esc}b"', id="double_quoted_argument"),
    pytest.param('& "g{esc}it" status', id="double_quoted_program_via_call_operator"),
]
_PS_ESCAPE_FORMS = [
    *(pytest.param(f"`{letter}", f"`{letter}", id=f"letter_{letter}") for letter in _PS_EXPANDING),
    pytest.param("`u{67}", "`u", id="u_brace_form"),  # PowerShell 7 reads `u{67} as the character "g"
]


@pytest.mark.parametrize("template", _PS_ESCAPE_SITES)
@pytest.mark.parametrize(("escape", "named"), _PS_ESCAPE_FORMS)
def test_powershell_expanding_backtick_escapes(template: str, escape: str, named: str) -> None:
    # Negative control first: the neighbour with the plain escape `x is read, and `x is just the letter x.
    neighbour = template.format(esc="`x")
    segment = _only(neighbour, "powershell")
    assert segment.unparseable is None
    assert "x" in "".join(segment.tokens[0:3]) and not any("`" in token for token in segment.tokens)

    command = template.format(esc=escape)
    # The line is refused whole, naming the escape: no segment is left for a rule to match as another program.
    _refused_line(command, "powershell", _PS_REASON)
    _refused_line(command, "powershell", f"'{named}'")

    # Dialect isolation: these dialects do not read the PowerShell escape, so this reason is never given.
    for dialect in ("posix", "cmd"):
        other = parse_command(command, dialect=dialect)
        reasons = [other.unparseable, *(segment.unparseable for segment in other.segments)]
        assert all(reason is None or _PS_REASON not in reason for reason in reasons), (dialect, reasons)


def test_powershell_backtick_neighbours_stay_literal() -> None:
    # Every other character after a backtick is the plain next character, so the word stays readable.
    # `"`, `'` and `%` are not in the list: a word holding one is refused by the argument-value rules (F3), below.
    plain_lower = [c for c in string.ascii_lowercase if c not in _PS_EXPANDING]
    plain = [*string.ascii_uppercase, *plain_lower, *"123456789", "$", "`", "-", "(", "{", "[", "~"]
    # r1e (rule G): a finished PowerShell word with no blank that holds `*`, `?`, `[` or `{` is dynamic AND variadic
    # however it was written, because a Windows program may expand it. Here `{` and `[` sit inside the word; `~` does
    # too (only a LEADING `~` or `@` is marked), so it stays literal. This test used to assert `not any(quoted.dynamic)`
    # for every character, which pinned the pre-r1e reading of `"a`[b"` and `"a`{b"` as literal.
    now_dynamic = ("[", "{")
    stays_literal = [char for char in plain if char not in now_dynamic]
    for char in stays_literal:
        bare = _only(f"echo a`{char}b", "powershell")
        assert bare.tokens == ("echo", f"a{char}b"), char
        assert bare.unparseable is None, char
        quoted = _only(f'echo "a`{char}b"', "powershell")
        assert quoted.tokens == ("echo", f"a{char}b"), char
        assert not any(quoted.dynamic), char
    for char in now_dynamic:
        bare = _only(f"echo a`{char}b", "powershell")
        assert bare.tokens == ("echo", f"a{char}b"), char
        assert bare.unparseable is None, char
        assert bare.dynamic == (False, True), char
        assert bare.variadic == (False, True), char
        quoted = _only(f'echo "a`{char}b"', "powershell")
        assert quoted.tokens == ("echo", f"a{char}b"), char
        assert quoted.dynamic == (False, True), char
        assert quoted.variadic == (False, True), char
    # As the program word too.
    assert _only("`Ngit status", "powershell").tokens == ("Ngit", "status")
    assert _only('& "g`xit" status', "powershell").tokens == ("gxit", "status")

    # A backtick before `"`, `'` or `%` is still the plain next character, but the word then holds a character an
    # argument value may not (F3): the line is refused whole. The accepted neighbour is the same word with a letter.
    assert _only("echo a`xb", "powershell").tokens == ("echo", "axb")
    _refused_line('echo a`"b', "powershell", "double quote")
    _refused_line("echo a`'b", "powershell", "single quote")
    _refused_line("echo a`%b", "powershell", "batch-file")

    # Single-quoted text has no escapes: the backtick and the letter after it stay literal, even an expanding one.
    for letter in _PS_EXPANDING:
        assert _only(f"echo 'a`{letter}b'", "powershell").tokens == ("echo", f"a`{letter}b"), letter

    # A trailing backtick keeps its own reason, not the expanding one.
    for command in ("echo a`", "echo `"):
        parsed = parse_command(command, dialect="powershell")
        assert parsed.segments == ()
        assert parsed.unparseable is not None
        assert "a trailing" in parsed.unparseable
        assert _PS_REASON not in parsed.unparseable

    # A backtick before a newline is a line continuation: PowerShell reads it, the policy does not (F11), so the whole
    # line is refused. The accepted neighbour of each is the line the continuation would have joined.
    assert _only("git status", "powershell").tokens == ("git", "status")
    _refused_line("git `\nstatus", "powershell", "continuation")
    assert _only("git a`xb", "powershell").tokens == ("git", "axb")
    _refused_line("git a`\n`xb", "powershell", "continuation")

    # Isolation: the same text in the other dialects is read as that dialect reads it.
    for letter in _PS_EXPANDING:
        assert _only(f"echo a`{letter}b", "cmd").tokens == ("echo", f"a`{letter}b"), letter
        assert _only(f'echo "a`{letter}b"', "cmd").tokens == ("echo", f"a`{letter}b"), letter
        assert _only(f"echo 'a`{letter}b'", "posix").tokens == ("echo", f"a`{letter}b"), letter
    posix_bare = parse_command("echo a`tb", dialect="posix")  # a POSIX backtick is a substitution: its own reason
    assert posix_bare.unparseable is not None and _PS_REASON not in posix_bare.unparseable


_PS_WRAPPED_SCRIPTS = [
    # (outer dialect, a wrapper command with a {esc} hole inside the PowerShell script it carries)
    # POSIX -> PowerShell is cross-family and refused whole (F9, row f9_posix_pwsh), so no POSIX outer row is left.
    pytest.param("cmd", 'powershell -Command "echo a{esc}b"', id="cmd_powershell_command"),
]


@pytest.mark.parametrize("letter", _PS_EXPANDING)
@pytest.mark.parametrize(("outer", "template"), _PS_WRAPPED_SCRIPTS)
def test_powershell_expanding_backtick_escape_in_a_wrapped_script(outer: Dialect, template: str, letter: str) -> None:
    # Negative control first: with the plain escape `x the script is unwrapped and read as PowerShell.
    readable = _accepted(template.format(esc="`x"), outer)
    assert all(segment.unparseable is None for segment in readable.segments)
    assert readable.segments[-1].depth == 1
    assert readable.segments[-1].dialect == "powershell"

    parsed = _accepted(template.format(esc=f"`{letter}"), outer)  # the outer line reads; the script segment cannot
    unreadable = [segment for segment in parsed.segments if segment.unparseable is not None]
    assert len(unreadable) == 1
    reason = unreadable[0].unparseable
    assert reason is not None
    assert "the wrapped script is unparseable" in reason
    assert _PS_REASON in reason
    assert f"'`{letter}'" in reason
    assert unreadable[0].depth == 0  # nothing was unwrapped: the shell itself is the unreadable segment
    assert unreadable[0].tokens[0] in ("pwsh", "powershell")


# --------------------------------------------------------------------------------------
# M2 #6 -- compound boundaries
# --------------------------------------------------------------------------------------

# dialect -> (every separator the dialect reads, in one line; the programs it holds; a trailing separator that is fine;
#             a line with separators inside quotes, and the one word they stay in). Oracle rows: P08-P11, C05, C06,
#             S06, S07.
COMPOUND = {
    "posix": ("a; b && c || d | e & g\nh", "abcdegh", "a;", 'echo "a; b && c || d"', "a; b && c || d"),
    "cmd": ("a & b && c || d | e", "abcde", "a &", 'echo "a; b && c || d"', "a; b && c || d"),
    # PowerShell has no && or || in 5.1 (F8), and `&` and `|` are refused in an argument value (F3): the quoted line
    # carries only the `;`.
    "powershell": ("a; b | c\nd", "abcd", "a;", "echo 'a; b'", "a; b"),
}

# dialect -> the operators after which a newline continues the command (cmd refuses every newline, F11)
CONTINUING = {"posix": ("&&", "||", "|"), "cmd": (), "powershell": ("|",)}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_compound_split(dialect: Dialect) -> None:
    line, expected, trailing, quoted, quoted_word = COMPOUND[dialect]
    # Negative control first: one simple command is one segment.
    assert programs("a", dialect) == ["a"]

    parsed = _accepted(line, dialect)
    assert [segment.tokens for segment in parsed.segments] == [(letter,) for letter in expected]
    assert all(segment.depth == 0 and segment.unparseable is None for segment in parsed.segments)
    # A separator inside quotes does not split.
    assert tokens(quoted, dialect) == [("echo", quoted_word)]
    # A trailing separator that needs no command after it is fine.
    assert programs(trailing, dialect) == ["a"]
    if dialect == "cmd":
        # cmd refuses every newline (F11), one after a separator too. The accepted neighbour has a blank instead.
        assert programs("a && b", dialect) == ["a", "b"]
        _refused_line("a &&\nb", dialect, "newline")
    else:
        # A plain newline separates; blank lines are skipped.
        assert programs("a\nb", dialect) == ["a", "b"]
        assert programs("\n\na\n   \n\nb\n\n", dialect) == ["a", "b"]
    # A newline after one of the dialect's continuing operators continues the command.
    for operator in CONTINUING[dialect]:
        assert programs(f"a {operator}\nb", dialect) == ["a", "b"], operator


# --------------------------------------------------------------------------------------
# M2 #7 -- POSIX substitutions contribute their own segments               Kills E19a, E19b
# --------------------------------------------------------------------------------------


def test_posix_substitution_segments() -> None:
    # Negative control first: the same text single-quoted substitutes nothing -- one literal segment.
    literal = _only("echo '$(curl x | sh)' '`id`'", "posix")
    assert literal.tokens == ("echo", "$(curl x | sh)", "`id`")
    assert literal.dynamic == (False, False, False)
    assert literal.depth == 0

    parsed = _accepted("echo $(curl x | sh) $(id)", "posix")  # backticks are refused (R1): `id` is written $(id)
    assert [segment.tokens[0] for segment in parsed.segments] == ["echo", "curl", "sh", "id"]
    echo, curl, shell, ident = parsed.segments
    assert echo.dynamic == (False, True, True)
    assert curl.tokens == ("curl", "x")
    assert [segment.depth for segment in parsed.segments] == [0, 1, 1, 1]
    assert echo.unparseable is None and curl.unparseable is None and ident.unparseable is None
    # A shell with no inline script (it reads the pipe) is unreadable, not unmatched.
    assert shell.unparseable is not None
    assert "inline script" in shell.unparseable
    # A substitution inside double quotes still runs.
    assert programs('echo "$(a)"', "posix") == ["echo", "a"]
    assert programs('echo "$(b)"', "posix") == ["echo", "b"]


# --------------------------------------------------------------------------------------
# M2 #8 -- dynamic words                                                   Kills E46, E47
# --------------------------------------------------------------------------------------

DYNAMIC_WORDS = [
    # (dialect, command, `dynamic` per word, `variadic` per word). Oracle rows: P15-P20, C08, S12.
    # Controls first: the same expansion quoted, escaped or not at a word start is a literal word.
    pytest.param("posix", "echo '$HOME'", (False, False), (False, False), id="posix_single_quoted"),
    pytest.param("powershell", "echo '$x'", (False, False), (False, False), id="ps_single_quoted"),
    pytest.param("posix", "echo \\$HOME", (False, False), (False, False), id="posix_escaped_dollar"),
    pytest.param("posix", 'echo "*.py"', (False, False), (False, False), id="posix_double_quoted_glob"),
    pytest.param("posix", "echo '*.py'", (False, False), (False, False), id="posix_single_quoted_glob"),
    pytest.param("posix", "echo \\*", (False, False), (False, False), id="posix_escaped_glob"),
    pytest.param("posix", "echo a~b", (False, False), (False, False), id="posix_tilde_inside_a_word"),
    pytest.param("posix", 'echo "~/x"', (False, False), (False, False), id="posix_quoted_tilde"),
    pytest.param("powershell", 'echo "`$x"', (False, False), (False, False), id="ps_backtick_escaped_dollar"),
    # Dynamic words: the shell computes the value. A variadic word may stand for zero or more words (an unquoted POSIX
    # expansion, a glob or a brace, every cmd and PowerShell dynamic word); the others stand for exactly one (a quoted
    # POSIX expansion, a tilde).
    pytest.param("posix", "echo $HOME", (False, True), (False, True), id="posix_var"),
    pytest.param("posix", "echo ${HOME}", (False, True), (False, True), id="posix_brace"),
    pytest.param("posix", "echo *.py", (False, True), (False, True), id="posix_glob"),
    pytest.param("posix", "echo ~/x", (False, True), (False, False), id="posix_tilde"),
    pytest.param("posix", "echo {a,b}", (False, True), (False, True), id="posix_brace_expansion"),
    pytest.param("cmd", "echo *.py", (False, True), (False, True), id="cmd_glob"),
    pytest.param("powershell", "echo *.py", (False, True), (False, True), id="ps_glob"),
    pytest.param("posix", "echo $1", (False, True), (False, True), id="posix_special_parameter"),
    pytest.param("posix", 'echo "$HOME"', (False, True), (False, False), id="posix_double_quoted_var"),
    pytest.param("posix", "echo f?.py", (False, True), (False, True), id="posix_question_glob"),
    pytest.param("posix", "echo [ab]", (False, True), (False, True), id="posix_bracket_glob"),
]


@pytest.mark.parametrize(("dialect", "command", "expected", "variadic"), DYNAMIC_WORDS)
def test_dynamic_words(
    dialect: Dialect, command: str, expected: tuple[bool, ...], variadic: tuple[bool, ...]
) -> None:
    segment = _only(command, dialect)
    assert segment.dynamic == expected
    assert segment.variadic == variadic
    assert segment.tokens[0] == command.split()[0]
    assert segment.dynamic[0] is False
    assert segment.unparseable is None


# --------------------------------------------------------------------------------------
# M2 #9 -- a line the policy cannot read at all
#   Kills E15, E17, E18, E23, E41, E42, E43
# --------------------------------------------------------------------------------------


def _line(case_id: str, dialect: Dialect, command: str, reason: str, neighbour: str) -> Any:
    return pytest.param(dialect, command, reason, neighbour, id=case_id)


UNPARSEABLE_LINES = [
    # POSIX
    _line("posix_single_quote", "posix", "echo 'a", "single quote", "echo 'a'"),
    _line("posix_double_quote", "posix", 'echo "a', "double quote", 'echo "a"'),
    _line("posix_unbalanced_substitution", "posix", "echo $(a", "$(", "echo $(a)"),
    _line("posix_backtick", "posix", "echo `a", "backtick", "echo $(a)"),
    _line("posix_here_document", "posix", "cat <<EOF", "here-document", "cat < EOF"),
    _line("posix_here_document_dash", "posix", "cat <<-EOF", "here-document", "cat < EOF"),
    _line("posix_here_string", "posix", "cat <<< x", "here-string", "cat < x"),
    _line("posix_arithmetic", "posix", "echo $((1+2))", "arithmetic", "echo $(echo 3)"),
    _line("posix_ansi_c_quoting", "posix", "echo $'x'", "quoting", "echo 'x'"),
    _line("posix_locale_quoting", "posix", 'echo $"x"', "quoting", 'echo "x"'),
    _line("posix_subshell", "posix", "(a)", "subshell", "a"),
    _line("posix_process_substitution", "posix", "diff <(a) b", "process substitution", "diff a b"),
    _line("posix_output_process_substitution", "posix", "tee >(a)", "process substitution", "tee a"),
    _line("posix_case_terminator", "posix", "a;; b", "case", "a; b"),
    _line("posix_case_fallthrough", "posix", "a;& b", "case", "a; b"),
    _line("posix_dangling_and", "posix", "a &&", "nothing after", "a && b"),
    _line("posix_dangling_or", "posix", "a ||", "nothing after", "a || b"),
    _line("posix_dangling_pipe", "posix", "a |", "nothing after", "a | b"),
    _line("posix_dangling_pipe_and", "posix", "a |&", "|&", "a | b"),
    _line("posix_leading_separator", "posix", "; a", "empty command", "a"),
    _line("posix_empty_command_between_separators", "posix", "a && && b", "empty command", "a && b"),
    _line("posix_trailing_escape", "posix", "echo a\\", "trailing", "echo a\\\\"),
    _line("posix_nul", "posix", "echo a\x00", "control", "echo a\tb"),
    _line("posix_lone_cr", "posix", "echo a\rb", "control", "echo a\nb"),
    _line("posix_line_separator", "posix", "echo a\u2028", "line break", "echo a\tb"),
    _line("posix_paragraph_separator", "posix", "echo a\u2029b", "line break", "echo a\tb"),
    _line("posix_next_line", "posix", "echo a\u0085", "line break", "echo a\tb"),
    _line("posix_delete_character", "posix", "echo a\x7f", "control", "echo a\tb"),
    _line("posix_second_command_broken", "posix", 'git status; echo "a', "double quote", 'git status; echo "a"'),
    # cmd
    _line("cmd_parenthesised_block", "cmd", "(a)", "outside quotes", "a"),
    # a comma outside quotes refuses the WHOLE LINE in cmd (contract row r1_cmd_comma), not one segment
    _line("cmd_comma_in_program", "cmd", "git,status", "outside quotes", "git status"),
    _line("cmd_double_quote", "cmd", 'echo "a', "double quote", 'echo "a"'),
    _line("cmd_trailing_caret", "cmd", "echo a^", "'^'", "echo a"),
    _line("cmd_nul", "cmd", "echo a\x00", "control", "echo a\tb"),
    # PowerShell
    _line("ps_subexpression", "powershell", "echo $(x)", "subexpression", "echo x"),
    _line("ps_here_string", "powershell", "echo @'x'@", "here-string", "echo 'x'"),
    _line("ps_double_quoted_here_string", "powershell", 'echo @"x"@', "here-string", 'echo "x"'),
    _line("ps_array", "powershell", "echo @(1)", "array", "echo 1"),
    _line("ps_hash_table", "powershell", "echo @{a=1}", "hash table", "echo a=1"),
    _line("ps_braces", "powershell", "{x}", "syntax", "x"),
    _line("ps_parentheses", "powershell", "(a)", "syntax", "a"),
    _line("ps_stop_parsing", "powershell", "git --% x", "stop-parsing", "git -x x"),
    _line("ps_reserved_less_than", "powershell", "a < b", "reserved", "a > b"),
    _line("ps_block_comment", "powershell", "a <# c #> b", "reserved", "a # c"),
    _line("ps_smart_quotes", "powershell", "echo \u2018x\u2019", "syntax", "echo 'x'"),
    _line("ps_smart_quote_inside_a_string", "powershell", "echo 'a\u2019b'", "non-ASCII", "echo 'a'"),
    _line("ps_non_breaking_space", "powershell", "git\u00a0push", "syntax", "git push"),
    _line("ps_ideographic_space", "powershell", "git\u3000push", "syntax", "git push"),
    _line("ps_en_dash", "powershell", "git push \u2013force", "syntax", "git push -force"),
    _line("ps_em_dash", "powershell", "git push \u2014force", "syntax", "git push -force"),
    _line("ps_horizontal_bar", "powershell", "git push \u2015force", "syntax", "git push -force"),
    _line("ps_unquoted_comma", "powershell", "git push,--force", "syntax", "git push --force"),
    _line("ps_background_job", "powershell", "a &", "background", "& a"),
    _line("ps_nul", "powershell", "echo a\x00", "control", "echo a\tb"),
    # No command at all, in every dialect
    *[
        _line(f"{kind}_{dialect}", dialect, text, "no command", "a")
        for dialect in DIALECTS
        for kind, text in (("empty", ""), ("blank", "   "))
    ],
    _line("posix_comment_only", "posix", "# c", "no command", "a # c"),
    _line("ps_comment_only", "powershell", "# c", "no command", "a # c"),
]


@pytest.mark.parametrize(("dialect", "command", "reason", "neighbour"), UNPARSEABLE_LINES)
def test_unparseable_line(dialect: Dialect, command: str, reason: str, neighbour: str) -> None:
    _accepted(neighbour, dialect)  # the accepted neighbour first
    _refused_line(command, dialect, reason)


# --------------------------------------------------------------------------------------
# M2 #10 -- one segment the policy cannot read      Kills E24, E25 (rows with literal text), E27
# --------------------------------------------------------------------------------------


def _segment_row(case_id: str, dialect: Dialect, command: str, neighbour: str, reason: str = "") -> Any:
    return pytest.param(dialect, command, neighbour, reason, id=case_id)


UNPARSEABLE_SEGMENTS = [
    # Programs that run a command the policy cannot see; the neighbour is an ordinary program one letter away.
    _segment_row("posix_eval", "posix", "eval x", "evaluate x"),
    _segment_row("posix_sudo", "posix", "sudo x", "sudoku"),
    _segment_row("posix_env", "posix", "env A=1 x", "A=1 x"),
    _segment_row("posix_xargs", "posix", "xargs rm", "echo rm"),
    _segment_row("posix_if", "posix", "if x", "ifconfig"),
    _segment_row("posix_exec", "posix", "exec x", "echo x"),
    _segment_row("posix_source", "posix", "source x", "echo x"),
    _segment_row("posix_dot", "posix", ". ./x.sh", "./x.sh"),
    _segment_row("posix_path_spelled_env", "posix", "/usr/bin/env x", "/usr/bin/echo x"),
    _segment_row("cmd_call", "cmd", "call x", "calls x"),
    _segment_row("cmd_call_upper_case", "cmd", "CALL x", "calls x"),
    _segment_row("cmd_start", "cmd", "start x", "starts x"),
    _segment_row("ps_iex", "powershell", "iex x", "iexplore x"),
    _segment_row("ps_iex_upper_case", "powershell", "IEX x", "iexplore x"),
    _segment_row("ps_invoke_expression", "powershell", "Invoke-Expression x", "Invoke-RestMethod x"),
    _segment_row("ps_dot_source", "powershell", ". ./x.ps1", "./x.ps1"),
    _segment_row("ps_start_process", "powershell", "Start-Process x", "Start-Sleep x"),
    _segment_row("ps_foreach_object", "powershell", "ForEach-Object x", "Format-Table x"),
    # A POSIX process wrapper's name in another dialect may start a command the policy cannot see (F9).
    _segment_row("ps_timeout_process_wrapper", "powershell", "timeout 30 x", "timeouts 30 x", "process wrapper"),
    _segment_row("cmd_timeout_process_wrapper", "cmd", "timeout 30 x", "timeouts 30 x", "process wrapper"),
    # A program word cmd.exe may split or hide
    _segment_row("cmd_at_sign", "cmd", "@echo off", "echo off"),
    # `noglob` and `builtin` are launchers: they start a command the policy cannot see (contract launcher table).
    _segment_row("posix_noglob_launcher", "posix", "noglob x", "noglobs x", "runs a command the policy cannot see"),
    _segment_row("posix_builtin_launcher", "posix", "builtin x", "builtins x", "runs a command the policy cannot see"),
    # A program the shell computes. `$X arg` has no literal text, so the empty-program check refuses it
    # too: "unparseable is set" alone cannot kill E25. The reason must say the program is not a literal word, and the
    # rows with a literal remainder (`$D/git`, `g$X`) are read as ordinary programs when the
    # dynamic-program check is missing. (cmd's `%X%\git` is refused at line level since `%` is refused, F4.)
    _segment_row("posix_dynamic_program", "posix", "$X arg", "echo $X arg", "literal word"),
    _segment_row("posix_dynamic_program_with_a_path", "posix", "$D/git push", "d/git push", "literal word"),
    _segment_row("posix_dynamic_program_with_a_prefix", "posix", "g$X push", "gx push", "literal word"),
    # An empty program. (PowerShell's `'' x` is refused at line level, F3.)
    _segment_row("posix_empty_program", "posix", "'' x", "x ''", "empty word"),
    _segment_row("cmd_empty_program", "cmd", '"" x', 'x ""', "empty word"),
    # A command made of nothing but assignments or redirections
    _segment_row("posix_assignment_only", "posix", "FOO=1", "FOO=1 x"),
    _segment_row("posix_redirection_only", "posix", "> f", "x > f"),
    # A shell that is not an inline script it unwraps: it reads a file or a pipe
    _segment_row("posix_bash_script_file", "posix", "bash script.sh", "bash -c x"),
    _segment_row("posix_bare_sh", "posix", "sh", "sh -c x"),
]


@pytest.mark.parametrize(("dialect", "command", "neighbour", "reason"), UNPARSEABLE_SEGMENTS)
def test_unparseable_segment(dialect: Dialect, command: str, neighbour: str, reason: str) -> None:
    # The accepted neighbour first: an ordinary program is read, whole.
    assert _only(neighbour, dialect).unparseable is None
    # The line parses; the one segment is the unreadable part.
    parsed = _accepted(command, dialect)
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    segment = parsed.segments[0]
    assert segment.unparseable is not None
    assert reason in segment.unparseable


# --------------------------------------------------------------------------------------
# M2 #11 -- redirections stay out of the tokens
# --------------------------------------------------------------------------------------

REDIRECTIONS = [
    pytest.param("posix", "git status", ("git", "status"), (), id="posix_none"),
    pytest.param("posix", "git status > out 2>&1", ("git", "status"), (">out", "2>&1"), id="posix"),
    pytest.param("posix", "git status >out", ("git", "status"), (">out",), id="posix_no_space"),
    pytest.param("posix", "cat <in >>log", ("cat",), ("<in", ">>log"), id="posix_input_and_append"),
    pytest.param("posix", "echo 2 > f", ("echo", "2"), (">f",), id="posix_separate_digit_is_a_word"),
    pytest.param("posix", "echo 2> f", ("echo",), ("2>f",), id="posix_adjacent_digit_is_a_descriptor"),
    pytest.param("cmd", "dir > out", ("dir",), (">out",), id="cmd"),
    pytest.param("powershell", "git log *> out", ("git", "log"), ("*>out",), id="powershell"),
]


@pytest.mark.parametrize(("dialect", "command", "expected_tokens", "expected_redirections"), REDIRECTIONS)
def test_redirections_stay_out_of_tokens(
    dialect: Dialect, command: str, expected_tokens: tuple[str, ...], expected_redirections: tuple[str, ...]
) -> None:
    segment = _only(command, dialect)
    assert segment.tokens == expected_tokens
    assert segment.redirections == expected_redirections
    assert segment.dynamic == (False,) * len(expected_tokens)
    assert segment.unparseable is None


def test_redirections_stay_out_of_tokens_target_is_required() -> None:
    # Negative control first: with a target the redirection is accepted and recorded.
    assert _only("echo > f", "posix").redirections == (">f",)
    _refused_line("echo >", "posix", "no target")
    _refused_line("echo > ; a", "posix", "no target")  # a separator after the operator is not a target either


# --------------------------------------------------------------------------------------
# M2 #12 -- leading assignments                                                 Kills E28
# --------------------------------------------------------------------------------------

ASSIGNMENTS = [
    # Negative control first: no leading assignment.
    pytest.param("git push", (), ("git", "push"), id="no_assignment"),
    pytest.param('A=1 B="x y" git push', ("A=1", 'B="x y"'), ("git", "push"), id="two_leading_assignments"),
    pytest.param('"A=1" git', (), ("A=1", "git"), id="quoted_name_is_a_program_not_an_assignment"),
    pytest.param("git A=1", (), ("git", "A=1"), id="assignment_after_the_program_is_an_argument"),
]


@pytest.mark.parametrize(("command", "assignments", "expected_tokens"), ASSIGNMENTS)
def test_leading_assignments_posix(
    command: str, assignments: tuple[str, ...], expected_tokens: tuple[str, ...]
) -> None:
    segment = _only(command, "posix")
    assert segment.assignments == assignments
    assert segment.tokens == expected_tokens
    assert segment.unparseable is None


def test_leading_assignments_cmd_program_word_with_equals_is_unparseable() -> None:
    # Negative control first: without the assignment the program is read.
    assert _only("git", "cmd").unparseable is None
    parsed = _accepted("A=1 git", "cmd")
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    segment = parsed.segments[0]
    assert segment.assignments == ()
    assert segment.unparseable is not None
    assert "cmd.exe may split" in segment.unparseable


# --------------------------------------------------------------------------------------
# M2 #13 -- process wrappers                                                    Kills E29
# --------------------------------------------------------------------------------------

PROCESS_WRAPPERS = [
    pytest.param("time x", ("time",), id="time"),
    pytest.param("nohup x", ("nohup",), id="nohup"),
    pytest.param("timeout 30 x", ("timeout 30",), id="timeout"),
    pytest.param("nice -n 5 x", ("nice -n 5",), id="nice_n"),
    pytest.param("stdbuf -oL x", ("stdbuf -oL",), id="stdbuf"),
    pytest.param("command x", ("command",), id="command"),
    pytest.param("timeout 30 nice x", ("timeout 30", "nice"), id="timeout_then_nice"),
    pytest.param("time time time time x", ("time",) * 4, id="four_wrappers_is_the_limit"),
]


@pytest.mark.parametrize(("command", "wrappers"), PROCESS_WRAPPERS)
def test_process_wrappers(command: str, wrappers: tuple[str, ...]) -> None:
    # Negative control first: the wrapper's name in argument position is an ordinary word, not a wrapper.
    name = command.split()[0]
    argument = _only(f"x {name}", "posix")
    assert argument.tokens == ("x", name)
    assert argument.wrappers == ()

    segment = _only(command, "posix")
    assert segment.tokens == ("x",)
    assert segment.wrappers == wrappers
    assert segment.dynamic == (False,)
    assert segment.unparseable is None


REFUSED_PROCESS_WRAPPERS = [
    # (command in a form that is not read, the accepted neighbour)
    pytest.param("timeout -s KILL 5 x", "timeout 5 x", id="timeout_with_a_signal_option"),
    pytest.param("nice -5 x", "nice -n 5 x", id="nice_with_a_bare_level"),
    pytest.param("time -p x", "time x", id="time_with_an_option"),
    pytest.param("timeout", "timeout 5 x", id="timeout_alone"),
    pytest.param("time", "time x", id="time_with_no_command"),
    pytest.param("timeout $T x", "timeout 5 x", id="timeout_with_a_dynamic_duration"),
    pytest.param("time time time time time x", "time time time time x", id="five_wrappers"),
]


@pytest.mark.parametrize(("command", "neighbour"), REFUSED_PROCESS_WRAPPERS)
def test_process_wrappers_refused_forms_are_unparseable(command: str, neighbour: str) -> None:
    assert _only(neighbour, "posix").unparseable is None
    parsed = _accepted(command, "posix")
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    assert parsed.segments[0].unparseable is not None


@pytest.mark.parametrize(
    ("dialect", "command", "expected"),
    [
        pytest.param(
            "posix",
            "command -v git",
            ("command", "-v", "git"),
            id="posix_command_v_looks_up_and_runs_nothing",
        ),
        # `timeout 30 x` in cmd and PowerShell is a refused segment now (F9): see test_unparseable_segment.
    ],
)
def test_process_wrappers_that_wrap_nothing_stay_ordinary_programs(
    dialect: Dialect, command: str, expected: tuple[str, ...]
) -> None:
    segment = _only(command, dialect)
    assert segment.tokens == expected
    assert segment.wrappers == ()
    assert segment.unparseable is None


# --------------------------------------------------------------------------------------
# M2 #14 -- shell wrappers are unwrapped                                    Kills E26, E27
# --------------------------------------------------------------------------------------

SHELL_WRAPPERS = [
    # (outer dialect, command, the segment kept when not unwrapped, the inner segments, the inner dialect, the cause
    # every inner segment's `lookup_changed` names, or None). Oracle rows: P22, P23, P25, C10-C12, S13, S14.
    pytest.param(
        "posix",
        "bash -lc 'git status'",
        ("bash", "-lc", "git status"),
        [("git", "status")],
        "posix",
        "login shell",
        id="posix_bash_lc",
    ),
    pytest.param(
        "posix",
        '/bin/bash -c "git status"',
        ("/bin/bash", "-c", "git status"),
        [("git", "status")],
        "posix",
        None,
        id="posix_path_bash_c",
    ),
    pytest.param(
        "posix",
        "sh -c 'a && b'",
        ("sh", "-c", "a && b"),
        [("a",), ("b",)],
        "posix",
        "another command in the line",
        id="posix_sh_c_two_commands",
    ),
    pytest.param(
        "cmd",
        "cmd /c git status",
        ("cmd", "/c", "git", "status"),
        [("git", "status")],
        "cmd",
        None,
        id="cmd_c_words",
    ),
    # cmd /C takes the words, not one quoted string (F6): `cmd /C "git status"` is a refused segment.
    pytest.param(
        "cmd",
        "cmd /C git status",
        ("cmd", "/C", "git", "status"),
        [("git", "status")],
        "cmd",
        None,
        id="cmd_upper_c_words",
    ),
    pytest.param(
        "cmd",
        'pwsh -NoProfile -Command "git status"',
        ("pwsh", "-NoProfile", "-Command", "git status"),
        [("git", "status")],
        "powershell",
        None,
        id="cmd_pwsh_command",
    ),
    # POSIX -> PowerShell is cross-family and refused (F9, row f9_posix_pwsh of test_finding_refusals): no POSIX row.
]


@pytest.mark.parametrize(("dialect", "command", "kept", "expected", "inner", "lookup"), SHELL_WRAPPERS)
def test_shell_wrappers_unwrapped(
    dialect: Dialect,
    command: str,
    kept: tuple[str, ...],
    expected: list[tuple[str, ...]],
    inner: Dialect,
    lookup: str | None,
) -> None:
    # Negative control first: with unwrapping off the wrapper itself is the one segment, at depth 0.
    wrapper = _only(command, dialect, unwrap_shells=False)
    assert wrapper.tokens == kept
    assert wrapper.depth == 0

    parsed = _accepted(command, dialect)
    assert parsed.dialect == dialect
    assert [segment.tokens for segment in parsed.segments] == expected
    assert all(segment.depth == 1 for segment in parsed.segments)
    assert all(segment.dialect == inner for segment in parsed.segments)
    assert all(segment.unparseable is None for segment in parsed.segments)
    # R4: a login shell reads profile files that may change PATH; PowerShell with -NoProfile reads none; the other
    # wrappers here pass the caller's lookup context on unchanged.
    for segment in parsed.segments:
        if lookup is None:
            assert segment.lookup_changed is None, segment.tokens
        else:
            assert segment.lookup_changed is not None and lookup in segment.lookup_changed, segment.tokens


REFUSED_SHELL_FORMS = [
    # (dialect, a shell invoked in a form that is not unwrapped, the accepted neighbour)
    pytest.param("posix", "bash -c 'x' arg0", "bash -c 'x'", id="posix_extra_word_after_the_script"),
    pytest.param("posix", "bash -xc 'x'", "bash -lc 'x'", id="posix_unknown_flag_cluster"),
    pytest.param("posix", "bash -c $X", "bash -c x", id="posix_dynamic_script"),
    pytest.param("posix", "bash -c", "bash -c x", id="posix_no_script"),
    # pwsh is not unwrapped from POSIX (cross-family, F9), so its two refused forms are written for cmd.
    pytest.param("cmd", "pwsh -EncodedCommand AAA", "pwsh -NoProfile -Command AAA", id="cmd_pwsh_encoded_command"),
    pytest.param("cmd", "pwsh -File x.ps1", "pwsh -NoProfile -Command AAA", id="cmd_pwsh_file"),
    pytest.param("cmd", "cmd /k x", "cmd /c x", id="cmd_k"),
    pytest.param("cmd", "cmd /s /c x", "cmd /c x", id="cmd_s_flag"),
]


@pytest.mark.parametrize(("dialect", "command", "neighbour"), REFUSED_SHELL_FORMS)
def test_shell_wrappers_refused_forms_are_one_unparseable_segment(
    dialect: Dialect, command: str, neighbour: str
) -> None:
    assert _only(neighbour, dialect).depth == 1  # the accepted neighbour is unwrapped
    parsed = _accepted(command, dialect)
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    segment = parsed.segments[0]
    assert segment.unparseable is not None
    assert segment.depth == 0  # nothing was unwrapped: the shell itself is the unreadable segment
    assert segment.tokens[0] == command.split()[0]


# --------------------------------------------------------------------------------------
# M2 #15 -- a wrapped script that cannot be read marks its segment
# --------------------------------------------------------------------------------------


def test_wrapped_script_unparseable_marks_the_segment() -> None:
    # Negative control first: the same script, balanced, is unwrapped and read.
    balanced = _only("bash -c 'echo \"x\"'", "posix")
    assert balanced.tokens == ("echo", "x")
    assert balanced.depth == 1 and balanced.unparseable is None

    parsed = _accepted("bash -c 'echo \"x'", "posix")  # the line itself parses ...
    assert parsed.unparseable is None
    assert len(parsed.segments) == 1
    segment = parsed.segments[0]  # ... and its one segment is the unreadable part
    assert segment.unparseable is not None
    assert "the wrapped script is unparseable" in segment.unparseable
    assert segment.tokens[0] == "bash"
    assert segment.depth == 0

    # Written at the top level, the same broken quote makes the whole line unparseable instead.
    _refused_line('echo "x', "posix", "double quote")
    # The commands around a bad wrapped script are still read.
    around = _accepted("git status && bash -c 'echo \"x'", "posix")
    assert [segment.tokens[0] for segment in around.segments] == ["git", "bash"]
    assert around.segments[0].unparseable is None
    assert around.segments[1].unparseable is not None


# --------------------------------------------------------------------------------------
# M2 #16 -- bounds                                                  Kills E20, E21, E22, E50
# --------------------------------------------------------------------------------------

BOUNDS = [
    # (limits as a plain dict, accepted at the bound, refused one past it, the reason, which must name the bound)
    pytest.param({}, "a" * 8192, "a" * 8193, "longer than 8192", id="command_chars"),
    pytest.param({}, "a;" * 32, "a;" * 33, "more than 32 segments", id="segments"),
    pytest.param({}, "$(a $(b $(c)))", "$(a $(b $(c $(d))))", "nested deeper than 3", id="substitution_nesting"),
    pytest.param({"max_command_chars": 64}, "a" * 64, "a" * 65, "longer than 64", id="command_chars_from_limits"),
    pytest.param({"max_segments": 2}, "a; b", "a; b; c", "more than 2 segments", id="segments_from_limits"),
    pytest.param({"max_nesting": 1}, "$(a)", "$(a $(b))", "nested deeper than 1", id="nesting_from_limits"),
    pytest.param({"max_nesting": 0}, "a", "$(a)", "nested deeper than 0", id="no_nesting_allowed"),
]


@pytest.mark.parametrize(("limits", "accepted", "refused", "reason"), BOUNDS)
def test_bounds(limits: dict[str, int], accepted: str, refused: str, reason: str) -> None:
    config = _limits(**limits)
    parsed = _accepted(accepted, "posix", limits=config)  # at the bound: read
    assert parsed.unparseable is None
    _refused_line(refused, "posix", reason, limits=config)  # one past it: unparseable, and it names the bound


def test_bounds_the_default_limits_are_the_contracts() -> None:
    limits = CommandPolicyConfig()
    assert (limits.max_command_chars, limits.max_segments, limits.max_nesting) == (8192, 32, 3)
    # Passing no limits is passing the defaults.
    assert parse_command("a" * 8193, dialect="posix").unparseable == parse_command(
        "a" * 8193, dialect="posix", limits=limits
    ).unparseable


def test_bounds_shell_wrapper_nesting() -> None:
    command = "bash -c 'bash -c x'"
    # With room for both wrappers the inner command is read, two levels down.
    roomy = _only(command, "posix", limits=_limits(max_nesting=2))
    assert roomy.tokens == ("x",)
    assert roomy.depth == 2
    assert roomy.unparseable is None
    # With room for one, the second wrapper is one unparseable segment that names the bound.
    tight = _only(command, "posix", limits=_limits(max_nesting=1))
    assert tight.unparseable is not None
    assert "shell wrappers nested deeper than 1" in tight.unparseable
    assert tight.depth == 1
    # Substitutions and shell wrappers share one budget.
    inner = "bash -c 'echo $(a)'"
    shared = _accepted(inner, "posix", limits=_limits(max_nesting=2))
    assert [(segment.tokens[0], segment.depth) for segment in shared.segments] == [("echo", 1), ("a", 2)]
    starved = _only(inner, "posix", limits=_limits(max_nesting=1))
    assert starved.unparseable is not None
    assert "nested deeper than 1" in starved.unparseable


# --------------------------------------------------------------------------------------
# M2 #17 -- hostile input is linear
# --------------------------------------------------------------------------------------

HOSTILE_SIZE = 65536
HOSTILE_SECONDS = 2.0


def _fill(unit: str) -> str:
    return (unit * (HOSTILE_SIZE // len(unit) + 1))[:HOSTILE_SIZE]


HOSTILE_INPUTS = [
    pytest.param("cmd", _fill("%a "), id="cmd_percent"),
    pytest.param("posix", _fill("$"), id="posix_dollar"),
    pytest.param("posix", '"' + "a" * (HOSTILE_SIZE - 1), id="posix_unbalanced_quote"),
    pytest.param("powershell", _fill("''"), id="ps_quotes"),
    pytest.param("posix", _fill("\\\\"), id="posix_backslashes"),
    pytest.param("posix", _fill("${a}"), id="posix_brace"),
]


@pytest.mark.parametrize(("dialect", "command"), HOSTILE_INPUTS)
def test_hostile_input_is_linear(dialect: Dialect, command: str, record_property: Any) -> None:
    limits = _limits(max_command_chars=HOSTILE_SIZE)
    assert len(command) == HOSTILE_SIZE  # premise: exactly at the raised bound
    # Negative controls: under the default bound the input is refused before it is read (so `limits` is what lets
    # the lexer run), and one character over the raised bound is refused too.
    _refused_line(command, dialect, "longer than 8192")
    _refused_line(command + "a", dialect, f"longer than {HOSTILE_SIZE}", limits=limits)

    started = time.perf_counter()
    parsed = parse_command(command, dialect=dialect, limits=limits)
    elapsed = time.perf_counter() - started
    record_property("elapsed_seconds", round(elapsed, 4))

    assert isinstance(parsed, ParsedCommand)
    # A result is read XOR refused: never both, never neither.
    assert bool(parsed.segments) != (parsed.unparseable is not None)
    assert elapsed < HOSTILE_SECONDS, f"{dialect} {command[:12]!r}... took {elapsed:.3f}s, bound {HOSTILE_SECONDS}s"


# --------------------------------------------------------------------------------------
# M2 #18 -- wrapper variants share one canonical key
# --------------------------------------------------------------------------------------


def test_canonical_wrapper_variants_share_one_key() -> None:
    # Negative control first: another command is another key.
    other = canonical_command("git log", dialect="posix")
    assert (other.kind, other.parts) == ("argv", ("git", "log"))

    posix = [
        canonical_command(text, dialect="posix")
        for text in ("git status", "bash -c 'git status'", '/bin/bash -c "git status"', "sh -c 'git  status'")
    ]
    cmd = [
        canonical_command(text, dialect="cmd")
        for text in ("git status", "cmd /c git status", "cmd /C git status", 'pwsh -NoProfile -Command "git status"')
    ]
    for canonical in posix + cmd:
        assert isinstance(canonical, CanonicalCommand)
        assert canonical.kind == "argv"
        assert canonical.dialect is None  # the dialect is not part of an argv key
        assert canonical.parts == ("git", "status")
    assert len({canonical.key for canonical in posix}) == 1
    assert len({canonical.key for canonical in cmd}) == 1
    assert posix[0].key == cmd[0].key
    assert other.key != posix[0].key
    assert len(posix[0].key) == 64
    int(posix[0].key, 16)  # a sha256 hex digest

    # R4: a login shell, and PowerShell reading its profile, may change what a program name resolves to. Neither
    # wrapper is the plain command any more: each is a script keyed by its exact text, sharing no key with `git status`.
    login = canonical_command("bash -lc 'git status'", dialect="posix")
    profile = canonical_command('pwsh -Command "git status"', dialect="cmd")
    assert login.kind == "script"
    assert profile.kind == "script"
    assert login.key != posix[0].key
    assert profile.key != cmd[0].key


def _nested_sh(levels: int, innermost: str = "git status") -> str:
    """``levels`` POSIX ``sh -c`` wrappers around ``innermost``, each level quoted for the next."""
    text = innermost
    for _ in range(levels):
        text = f"sh -c {shlex.quote(text)}"
    return text


@pytest.mark.parametrize("max_nesting", [1, 2, 3])
def test_canonical_command_unwraps_at_most_max_nesting(max_nesting: int) -> None:
    limits = CommandPolicyConfig.model_validate({"max_nesting": max_nesting})
    within = _nested_sh(max_nesting)
    one_past = _nested_sh(max_nesting + 1)

    # Premises, with the parser: the n-wrapper line reads all the way down; one more wrapper is past the bound.
    read = _only(within, "posix", limits=limits)
    assert read.tokens == ("git", "status")
    assert read.depth == max_nesting
    refused = [
        segment.unparseable
        for segment in parse_command(one_past, dialect="posix", limits=limits).segments
        if segment.unparseable is not None
    ]
    assert len(refused) == 1
    assert refused[0] is not None and f"shell wrappers nested deeper than {max_nesting}" in refused[0]

    # For every level up to the bound all the wrappers are unwrapped and the innermost command is the argv: one key.
    plain = canonical_command("git status", dialect="posix", limits=limits)
    for level in range(1, max_nesting + 1):
        inside = canonical_command(_nested_sh(level), dialect="posix", limits=limits)
        assert (inside.kind, inside.dialect, inside.parts) == ("argv", None, ("git", "status")), level
        assert inside.key == plain.key, level

    # One wrapper past the bound the parse refuses the line, so the key is a script of the exact original text. (A2's
    # loop, which unwrapped n wrappers and kept the text left at depth n, is retired: R5.)
    past = canonical_command(one_past, dialect="posix", limits=limits)
    assert (past.kind, past.dialect, past.parts) == ("script", "posix", (one_past,))
    assert past.key != plain.key
    deeper_text = _nested_sh(max_nesting + 2)
    deeper = canonical_command(deeper_text, dialect="posix", limits=limits)
    assert (deeper.kind, deeper.dialect, deeper.parts) == ("script", "posix", (deeper_text,))
    assert deeper.key != past.key

    # The default limit is the same rule: three wrappers read, a fourth is a script of its exact text.
    assert canonical_command(_nested_sh(3), dialect="posix").kind == "argv"
    four = canonical_command(_nested_sh(4), dialect="posix")
    assert (four.kind, four.dialect, four.parts) == ("script", "posix", (_nested_sh(4),))


# --------------------------------------------------------------------------------------
# M2 #19 -- the program resolves to one path                                    Kills E34
# --------------------------------------------------------------------------------------


def test_canonical_program_resolution() -> None:
    bare, spelled = "git status", "/usr/bin/git status"
    # Without a resolver a bare name and its path are different programs to the key.
    assert canonical_command(bare, dialect="posix").key != canonical_command(spelled, dialect="posix").key

    resolve = {"git": "/usr/bin/git"}.get
    resolved = canonical_command(bare, dialect="posix", resolve_program=resolve)
    path = canonical_command(spelled, dialect="posix", resolve_program=resolve)
    assert resolved.key == path.key
    assert resolved.parts == ("/usr/bin/git", "status")
    # Another binary behind the same name is another key; a name the resolver does not know stays a name.
    elsewhere = canonical_command(bare, dialect="posix", resolve_program={"git": "/opt/bin/git"}.get)
    assert elsewhere.key != resolved.key
    assert canonical_command(bare, dialect="posix", resolve_program={}.get).parts == ("git", "status")

    # cmd compares paths case-insensitively and by normalised separators.
    cmd_resolve = {"git": "C:\\Git\\cmd\\git.exe"}.get
    assert canonical_command("git status", dialect="cmd").key != canonical_command(
        '"C:\\GIT\\cmd\\GIT.EXE" status', dialect="cmd"
    ).key
    cmd_bare = canonical_command("git status", dialect="cmd", resolve_program=cmd_resolve)
    cmd_path = canonical_command('"C:\\GIT\\cmd\\GIT.EXE" status', dialect="cmd", resolve_program=cmd_resolve)
    assert cmd_bare.key == cmd_path.key
    assert cmd_bare.parts == cmd_path.parts
    assert cmd_bare.parts[1:] == ("status",)


# --------------------------------------------------------------------------------------
# M2 #20 -- anything else is a script keyed by its exact text                   Kills E33
# --------------------------------------------------------------------------------------


def test_canonical_script_fallback() -> None:
    # Negative control first: a wrapper around ONE simple command is an argv, not a script.
    plain = canonical_command("bash -c 'ls'", dialect="posix")
    assert (plain.kind, plain.dialect, plain.parts) == ("argv", None, ("ls",))

    # R4: a login shell is not the starting lookup context, so `bash -lc 'ls'` is a script keyed by its exact text.
    login = canonical_command("bash -lc 'ls'", dialect="posix")
    assert (login.kind, login.dialect, login.parts) == ("script", "posix", ("bash -lc 'ls'",))
    assert login.key != plain.key

    one = canonical_command("bash -lc 'ls && pwd'", dialect="posix")
    two = canonical_command("/bin/bash -c 'ls && pwd'", dialect="posix")
    # The parts are the exact original text, so the wrapper, its path and its -lc/-c mode are all part of the key
    # (D6 amended): the same script behind another wrapper spelling is another key.
    assert (one.kind, one.dialect, one.parts) == ("script", "posix", ("bash -lc 'ls && pwd'",))
    assert (two.kind, two.dialect, two.parts) == ("script", "posix", ("/bin/bash -c 'ls && pwd'",))
    assert one.key != two.key
    assert one.key != canonical_command("bash -lc 'ls  &&  pwd'", dialect="posix").key  # the rest is exact text

    # Scripts that cannot be read are still keyed, by their own text.
    first = canonical_command("bash -lc 'echo \"a'", dialect="posix")
    second = canonical_command("bash -lc 'echo \"b'", dialect="posix")
    assert first.kind == second.kind == "script"
    assert first.parts == ("bash -lc 'echo \"a'",)
    assert second.parts == ("bash -lc 'echo \"b'",)
    assert first.key != second.key

    # What a key of literal words cannot represent is a script with the exact text.
    for text in ("echo $HOME", "git status > f", "timeout 5 x", "A=1 x", "eval x"):
        canonical = canonical_command(text, dialect="posix")
        assert (canonical.kind, canonical.dialect, canonical.parts) == ("script", "posix", (text,)), text
    # A script is tagged with its dialect: the same text under another shell is another key.
    posix_key = canonical_command("echo $HOME", dialect="posix").key
    assert posix_key != canonical_command("echo $HOME", dialect="powershell").key


# --------------------------------------------------------------------------------------
# M2 #21 -- the canonical key is a known answer                                 Kills E32
# --------------------------------------------------------------------------------------


def test_canonical_key_known_answer() -> None:
    assert CANONICAL_KEY_SCHEME == "probos.command_policy/canonical_command/v1"
    v2 = b"probos.command_policy/canonical_command/v2\x00"
    argv = canonical_command("git status", dialect="posix")
    script = canonical_command("bash -lc 'ls && pwd'", dialect="posix")
    for canonical in (argv, script):
        # The expectation is computed here from hashlib and the RFC 8785 canonicaliser, never from `.key`.
        assert canonical.key == _expected_key(canonical.kind, canonical.dialect, canonical.parts)
        # Negative control: the same payload under another domain tag is another key.
        assert canonical.key != _expected_key(canonical.kind, canonical.dialect, canonical.parts, domain=v2)
    # The payload is the RFC 8785 JSON of [kind, dialect, parts], pinned by hand so the answer does not depend on
    # the canonicaliser alone.
    assert argv.key == hashlib.sha256(_CANONICAL_DOMAIN_V1 + b'["argv",null,["git","status"]]').hexdigest()
    assert script.key == hashlib.sha256(
        _CANONICAL_DOMAIN_V1 + b'["script","posix",["bash -lc \'ls && pwd\'"]]'
    ).hexdigest()
    # The key is a pure function of the three fields.
    assert CanonicalCommand("argv", None, ("git", "status")).key == argv.key
