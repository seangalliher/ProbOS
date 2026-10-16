"""AD-1328 S1 (#1530), M3: the command policy evaluator, self-test, policy object and the unwired scan.

Tests only. The contract is ``prompts/ad-1328-s1-command-policy-core.md`` ("Tests", M3). Every dialect is passed
explicitly (``posix``, ``cmd`` or ``powershell``), so the file passes on Linux and on Windows and never depends on the
host shell. Nothing here starts a process or reads the environment; a program resolver is a plain function over a dict.
Only the last two tests read files (the policy's own source and the source tree, as UTF-8), and the first of them also
writes a scratch tree under ``tmp_path``.

Each test asserts its own premise (what the tokenizer made of the text it is about) and a control: the accepted
neighbour of every refused case is checked first, so a test cannot pass because the whole machine refuses everything.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest

from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_policy import (
    CommandEvaluation,
    CommandPolicy,
    CommandPolicySelfTestError,
    RuleMatch,
    SegmentVerdict,
    SelfTestReport,
    canonical_command,
    evaluate_command,
    policy_digest,
    self_test,
)

# --------------------------------------------------------------------------------------
# Helpers (copied from the contract; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


def _resolver(table: dict[str, str]) -> Callable[[str], str | None]:
    """A program resolver as S2's PATH lookup would answer: the path a bare name runs, or None."""
    return lambda name: table.get(name)


def _verdicts(result: CommandEvaluation) -> list[tuple[str, str, str]]:
    """Each segment as ``(program, decision, basis)``: what was decided for every simple command, and why."""
    return [(v.segment.tokens[0] if v.segment.tokens else "", v.decision, v.basis) for v in result.segments]


def _only_segment(result: CommandEvaluation) -> SegmentVerdict:
    assert result.unparseable is None, result.unparseable
    assert len(result.segments) == 1, [v.segment.tokens for v in result.segments]
    return result.segments[0]


# --------------------------------------------------------------------------------------
# 1. No rules: no policy, and nothing is parsed
# --------------------------------------------------------------------------------------


def test_no_rules_is_no_policy_and_parses_nothing() -> None:
    unreadable = "((("
    # control first: with one rule the same text IS evaluated, and being unreadable it takes unparseable_decision
    governed = _policy(_rule("ask-git", ["git"], "escalate"))
    control = evaluate_command(governed, unreadable, dialect="posix")
    assert control.status == "evaluated"
    assert control.decision == "escalate"
    assert control.unparseable is not None  # premise: the text is unreadable, so a parse of it would show
    assert control.segments == ()
    assert control.policy_digest == policy_digest(governed)
    assert CommandPolicy(governed, dialect="posix").configured is True

    for config in (CommandPolicyConfig(), CommandPolicyConfig(unmatched_decision="forbid")):
        assert config.rules == ()  # premise: no rule is configured
        for command in (unreadable, "git status"):
            result = evaluate_command(config, command, dialect="posix")
            assert result.status == "no_policy", command
            assert result.decision is None
            assert result.segments == ()  # nothing was parsed, not even a readable command
            assert result.unparseable is None
            assert result.policy_digest is None
            assert result.dialect == "posix"
        policy = CommandPolicy(config, dialect="posix")
        assert policy.configured is False
        assert policy.evaluate(unreadable) == evaluate_command(config, unreadable, dialect="posix")
        assert policy.evaluate(unreadable).status == "no_policy"
        assert policy.evaluate("git status") == evaluate_command(config, "git status", dialect="posix")


# --------------------------------------------------------------------------------------
# 2-3. Matching: strictest wins, every match listed, alternatives per position
# --------------------------------------------------------------------------------------


def _git_stack(*, reverse: bool) -> CommandPolicyConfig:
    rules = [
        _rule("git-ok", ["git"], "allow"),
        _rule("git-push", ["git", "push"], "escalate"),
        _rule("no-force", ["git", "push", "--force"], "forbid"),
    ]
    return _policy(*(reversed(rules) if reverse else rules), unmatched="escalate")


def test_strictest_wins_with_overlapping_rules() -> None:
    expected = {  # command -> (decision, the matching rules in declaration order, the rules that govern)
        "git status": ("allow", ["git-ok"], ["git-ok"]),  # control: the permissive neighbour comes first
        "git push origin": ("escalate", ["git-ok", "git-push"], ["git-push"]),
        "git push --force": ("forbid", ["git-ok", "git-push", "no-force"], ["no-force"]),
    }
    for reverse in (False, True):
        config = _git_stack(reverse=reverse)
        assert config.unmatched_decision == "escalate"  # premise: "allow" below comes from a rule, not a default
        for command, (decision, matching, governing) in expected.items():
            result = evaluate_command(config, command, dialect="posix")
            where = (reverse, command)
            assert _only_segment(result).basis == "rule", where
            assert result.status == "evaluated"
            assert result.decision == decision, where
            # every match is listed, in rule order (the order the policy declares them in)
            assert [m.rule for m in result.matched_rules] == (matching[::-1] if reverse else matching), where
            assert sorted(m.rule for m in result.governing) == governing, where

    result = evaluate_command(_git_stack(reverse=False), "git push --force", dialect="posix")
    (governing,) = result.governing  # only the forbid rule governs, and it carries what the agent is told
    assert governing.rule == "no-force"
    assert governing.decision == "forbid"
    assert governing.justification == "no-force because"
    assert governing.alternative == "use the governed path"
    escalated = evaluate_command(_git_stack(reverse=False), "git push origin", dialect="posix")
    assert [(m.rule, m.alternative) for m in escalated.governing] == [("git-push", None)]


def test_alternatives_per_position() -> None:
    program = _policy(_rule("no-fetchers", [["curl", "wget"]], "forbid"))
    assert evaluate_command(program, "git x", dialect="posix").decision == "allow"  # control
    for command in ("curl x", "wget x"):
        result = evaluate_command(program, command, dialect="posix")
        assert result.decision == "forbid", command
        assert [m.rule for m in result.matched_rules] == ["no-fetchers"], command

    later = _policy(_rule("no-force", ["git", ["push", "fetch"], "--force"], "forbid"))
    for command in ("git fetch origin", "git pull --force", "git push origin"):  # control: near misses
        result = evaluate_command(later, command, dialect="posix")
        assert (result.decision, result.matched_rules) == ("allow", ()), command
    for command in ("git push --force", "git fetch --force"):
        result = evaluate_command(later, command, dialect="posix")
        assert result.decision == "forbid", command
        assert [m.rule for m in result.matched_rules] == ["no-force"], command


# --------------------------------------------------------------------------------------
# 4. One forbidden segment forbids the command, in every dialect
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dialect", "command", "expected", "decision"),
    [
        pytest.param(
            "posix",
            "git status && curl x | sh",
            (("git", "allow", "unmatched"), ("curl", "forbid", "rule"), ("sh", "escalate", "unparseable")),
            "forbid",
            id="posix_and_pipe",
        ),
        pytest.param(
            "cmd", "git status & curl x", (("git", "allow", "unmatched"), ("curl", "forbid", "rule")), "forbid",
            id="cmd_sequence",
        ),
        pytest.param(
            "powershell", "git status; curl x", (("git", "allow", "unmatched"), ("curl", "forbid", "rule")), "forbid",
            id="ps_sequence",
        ),
        pytest.param(
            "posix", "echo $(curl x)", (("echo", "allow", "unmatched"), ("curl", "forbid", "rule")), "forbid",
            id="posix_substitution",
        ),
        pytest.param(
            "posix", "bash -c 'git status; curl x'", (("git", "allow", "unmatched"), ("curl", "forbid", "rule")),
            "forbid", id="posix_wrapper",
        ),
        pytest.param(
            "posix", "echo 'curl x' | sh", (("echo", "allow", "unmatched"), ("sh", "escalate", "unparseable")),
            "escalate", id="posix_pipe_to_shell",
        ),
    ],
)
def test_one_forbidden_segment_forbids_the_command(
    dialect: str, command: str, expected: tuple[tuple[str, str, str], ...], decision: str,
) -> None:
    config = _policy(_rule("no-curl", ["curl"], "forbid"))  # unmatched="allow"
    # control: the accepted neighbour, a compound command with nothing forbidden in it
    # PowerShell has no ``&&`` (F8), so its control joins the two commands with ``;``
    control_command = "git status; git log" if dialect == "powershell" else "git status && git log"
    control = evaluate_command(config, control_command, dialect=dialect)
    assert _verdicts(control) == [("git", "allow", "unmatched"), ("git", "allow", "unmatched")]
    assert control.decision == "allow"

    result = evaluate_command(config, command, dialect=dialect)
    assert result.unparseable is None  # premise: the line was read, and split into the segments below
    assert _verdicts(result) == list(expected)
    assert result.decision == decision
    curl_at = [at for at, (program, _, _) in enumerate(expected) if program == "curl"]
    if curl_at:  # the rule decided the curl segment, and the match says which segment it was
        assert [(m.rule, m.segment) for m in result.matched_rules] == [("no-curl", curl_at[0])]
        assert [m.rule for m in result.governing] == ["no-curl"]
    else:  # nothing matched: the shell reading a pipe is unreadable, so it is not "allow"
        assert result.matched_rules == ()
        assert all(verdict.matches == () for verdict in result.segments)


# --------------------------------------------------------------------------------------
# 5. Unmatched and unparseable decisions
# --------------------------------------------------------------------------------------


def test_unmatched_and_unparseable_decisions() -> None:
    config = _policy(_rule("no-curl", ["curl"], "forbid"))  # unmatched="allow", unparseable_decision="escalate"
    assert (config.unmatched_decision, config.unparseable_decision) == ("allow", "escalate")  # premise: they differ

    listed = evaluate_command(config, "ls", dialect="posix")  # control: readable and unmatched
    assert (listed.decision, _verdicts(listed)) == ("allow", [("ls", "allow", "unmatched")])
    assert listed.matched_rules == ()

    whole_line_cases = ('echo "x', "", "   ")  # a quote that never closes, and no command at all
    for command in whole_line_cases:
        whole_line = evaluate_command(config, command, dialect="posix")
        assert whole_line.status == "evaluated", command
        assert whole_line.decision == "escalate", command
        assert whole_line.unparseable is not None, command
        assert whole_line.segments == (), command  # no segments at all

    # a segment the policy cannot read: the line parses, the one segment is unreadable and takes the same decision
    for command in ("eval x", "c*rl x", "$X arg"):  # a launcher, a globbed program, a program the shell computes
        result = evaluate_command(config, command, dialect="posix")
        assert result.unparseable is None, command  # premise: the line as a whole was read
        only = _only_segment(result)
        assert only.segment.unparseable is not None, command
        assert (only.decision, only.basis, only.matches) == ("escalate", "unparseable", ()), command
        assert result.decision == "escalate", command

    strict_unmatched = _policy(_rule("no-curl", ["curl"], "forbid"), unmatched="escalate")
    assert evaluate_command(strict_unmatched, "ls", dialect="posix").decision == "escalate"
    assert _only_segment(evaluate_command(strict_unmatched, "ls", dialect="posix")).basis == "unmatched"

    strict_unparseable = _policy(_rule("no-curl", ["curl"], "forbid"), unparseable_decision="forbid")
    assert evaluate_command(strict_unparseable, "ls", dialect="posix").decision == "allow"  # control: still unmatched
    for command in (*whole_line_cases, "eval x"):
        assert evaluate_command(strict_unparseable, command, dialect="posix").decision == "forbid", command


_PS_ESCAPED_PROGRAMS = [
    # (dialect, a command that runs `git push --force` through an escape PowerShell expands, its accepted twin)
    pytest.param(
        "powershell", '& "`u{67}it" push --force', '& "git" push --force', "expands to another character",
        id="call_operator_u_brace",
    ),
    pytest.param(
        "powershell", "& g`u{69}t push --force", "& git push --force", "expands to another character",
        id="call_operator_bare_u_brace",
    ),
    pytest.param(
        "powershell", "g`u{69}t push --force", "git push --force", "expands to another character",
        id="bare_program_u_brace",
    ),
    # (no posix -> pwsh row: PowerShell started from a POSIX shell is cross-family and refused, F9 f9_posix_pwsh)
    # cmd's lexer marks any word holding a brace as dynamic (oracle row C08), so this wrapper is refused before its
    # script is read: the reason is the wrapper's, not the escape's. The next row has no brace and reaches the check.
    pytest.param(
        "cmd", 'powershell -Command "g`u{69}t push --force"', 'powershell -Command "git push --force"',
        "runs a script the policy cannot see",
        id="powershell_wrapper_from_cmd",
    ),
    pytest.param(
        "cmd", 'powershell -Command "g`bit push --force"', 'powershell -Command "git push --force"',
        "the PowerShell escape",
        id="powershell_wrapper_from_cmd_escape_reaches_the_check",
    ),
]


@pytest.mark.parametrize(("dialect", "command", "twin", "reason_text"), _PS_ESCAPED_PROGRAMS)
@pytest.mark.parametrize("unparseable_decision", ["escalate", "forbid"])
@pytest.mark.parametrize("unmatched_decision", ["allow", "escalate"])
def test_powershell_escaped_program_is_not_unmatched(
    dialect: str, command: str, twin: str, reason_text: str, unparseable_decision: str, unmatched_decision: str
) -> None:
    config = _policy(
        _rule("no-force", ["git", "push", "--force"], "forbid"),
        unmatched=unmatched_decision,
        unparseable_decision=unparseable_decision,
    )

    # control first: the accepted twin spells the same program plainly, is read, and the rule forbids it
    plain = evaluate_command(config, twin, dialect=dialect)
    assert plain.unparseable is None
    assert plain.decision == "forbid"
    assert [m.rule for m in plain.matched_rules] == ["no-force"]
    assert _only_segment(plain).basis == "rule"

    # the escaped spelling (PowerShell turns the escape into another character, so it may run `git`) is not read:
    # it takes unparseable_decision, never the unmatched decision, never "allow"
    escaped = evaluate_command(config, command, dialect=dialect)
    assert escaped.status == "evaluated"
    assert escaped.decision == unparseable_decision
    assert escaped.decision != "allow"
    assert escaped.matched_rules == ()
    reasons = [escaped.unparseable] if escaped.unparseable is not None else [
        verdict.segment.unparseable for verdict in escaped.segments
    ]
    assert len(reasons) >= 1
    assert all(reason is not None and reason_text in reason for reason in reasons), reasons
    if reason_text == "the PowerShell escape":  # the row that reaches the escape check names the expansion too
        assert all("expands to another character" in reason for reason in reasons), reasons
    assert all(verdict.basis == "unparseable" for verdict in escaped.segments)  # a segment-level refusal, if any


# --------------------------------------------------------------------------------------
# 6-7. What a rule sees through, and what an allow rule needs proof of
# --------------------------------------------------------------------------------------


def test_restrictive_rules_see_through_and_allow_rules_need_proof() -> None:
    seen_through = {
        "/usr/bin/git push --force": lambda s: s.tokens[0] == "/usr/bin/git",  # a path
        "FOO=1 git push --force": lambda s: s.assignments == ("FOO=1",) and s.tokens[0] == "git",  # an assignment
        "git push $F": lambda s: s.dynamic == (False, False, True),  # an expanded word at pattern position 2
    }
    for decision in ("forbid", "escalate"):  # both restrictive decisions see through what can hide a program
        restrictive = _policy(_rule("no-force", ["git", "push", "--force"], decision))
        for command in ("git push --force", "git push origin"):  # control: the plain spelling, and a different word
            plain = evaluate_command(restrictive, command, dialect="posix")
            assert plain.decision == (decision if command.endswith("--force") else "allow"), (decision, command)
        for command, premise in seen_through.items():
            result = evaluate_command(restrictive, command, dialect="posix")
            assert premise(_only_segment(result).segment), command
            assert result.decision == decision, (decision, command)
            assert [m.rule for m in result.matched_rules] == ["no-force"], (decision, command)

    allow = _policy(_rule("push-ok", ["git", "push"], "allow"), unmatched="escalate")
    for command in ("git push", "git push $X"):  # the expanded word is past the pattern, so it does not matter
        result = evaluate_command(allow, command, dialect="posix")
        assert (result.decision, _only_segment(result).basis) == ("allow", "rule"), command
        assert [m.rule for m in result.matched_rules] == ["push-ok"], command
    past_the_pattern = _only_segment(evaluate_command(allow, "git push $X", dialect="posix"))
    assert past_the_pattern.segment.dynamic == (False, False, True)  # premise: the expanded word is the third
    unproven = {
        "FOO=1 git push": lambda s: s.assignments == ("FOO=1",),  # past an assignment
        "git $X push": lambda s: s.dynamic == (False, True, False),  # an expanded word at pattern position 1
        "./git push": lambda s: s.tokens[0] == "./git",  # a path is another binary than the bare name
        "/usr/bin/git push": lambda s: s.tokens[0] == "/usr/bin/git",
    }
    for command, premise in unproven.items():
        result = evaluate_command(allow, command, dialect="posix")
        assert premise(_only_segment(result).segment), command
        assert (result.decision, _only_segment(result).basis) == ("escalate", "unmatched"), command
        assert result.matched_rules == (), command


@pytest.mark.parametrize("dialect", ["cmd", "powershell"])
def test_windows_program_names_are_case_insensitive(dialect: str) -> None:
    config = _policy(_rule("no-curl", ["curl"], "forbid"))
    assert evaluate_command(config, "curl x", dialect=dialect).decision == "forbid"  # control: the plain spelling
    for command, program in (
        ("CURL.EXE x", "CURL.EXE"),
        (r"C:\Windows\System32\curl.exe x", r"C:\Windows\System32\curl.exe"),
    ):
        result = evaluate_command(config, command, dialect=dialect)
        assert _only_segment(result).segment.tokens[0] == program  # premise: the word as it was written
        assert result.decision == "forbid", command
        assert [m.rule for m in result.matched_rules] == ["no-curl"], command

    # POSIX too: a restrictive rule folds the program spelling in every dialect (R3), so ``CURL x`` and ``curl.exe x``
    # are the forbidden ``curl``. This loop used to pin the opposite (POSIX names are case sensitive and keep their
    # extension, so both spellings were ``allow``), which let a respelling slip past a deny-list.
    assert evaluate_command(config, "curl x", dialect="posix").decision == "forbid"  # control
    for command in ("CURL x", "curl.exe x"):
        result = evaluate_command(config, command, dialect="posix")
        assert (result.decision, _only_segment(result).basis) == ("forbid", "rule"), command
    # ... but an allow rule stays exact: a spelling it does not name is not proven, so it is not allowed
    exact = _policy(_rule("curl-ok", ["curl"], "allow"), unmatched="escalate")
    assert evaluate_command(exact, "curl x", dialect="posix").decision == "allow"  # control: the spelling it names
    spelled = evaluate_command(exact, "CURL x", dialect="posix")
    assert (spelled.decision, _only_segment(spelled).basis) == ("escalate", "unmatched")
    assert spelled.matched_rules == ()

    # alternatives at the program position compare the same way (the stem of each name)
    either = _policy(_rule("no-fetchers", [["curl", "wget"]], "forbid"))
    assert evaluate_command(either, "git x", dialect=dialect).decision == "allow"  # control
    for command in ("WGET.EXE x", r"C:\Tools\Curl.exe x"):
        result = evaluate_command(either, command, dialect=dialect)
        assert (result.decision, [m.rule for m in result.matched_rules]) == ("forbid", ["no-fetchers"]), command


# --------------------------------------------------------------------------------------
# 8-9. Pinning an allow rule to program paths
# --------------------------------------------------------------------------------------


def test_pinning_refuses_a_same_basename_executable_outside_the_pins() -> None:
    config = _policy(_rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git"]), unmatched="escalate")

    # control: the pinned program, found by the resolver
    asked: list[str] = []

    def at_usr_bin(name: str) -> str | None:
        asked.append(name)
        return {"git": "/usr/bin/git"}.get(name)

    proven = evaluate_command(config, "git status", dialect="posix", resolve_program=at_usr_bin)
    assert (proven.decision, _only_segment(proven).basis) == ("allow", "rule")
    (match,) = proven.matched_rules
    assert (match.rule, match.decision, match.pin_violation) == ("git-ok", "allow", False)
    assert match.resolved_program == "/usr/bin/git"
    assert asked == ["git"]  # the resolver is asked for the bare name, once
    asked.clear()
    # a path as written needs no resolver (it is not consulted), and the pin is compared normalised
    for command in ("/usr/bin/git status", "/usr/bin/./git status"):
        by_path = evaluate_command(config, command, dialect="posix", resolve_program=at_usr_bin)
        assert by_path.decision == "allow", command
        assert [m.resolved_program for m in by_path.matched_rules] == [_only_segment(by_path).segment.tokens[0]]
    # POSIX `..` is resolved after symlinks, so a path with `..` proves no pin (r2); this row used to pin the defect
    dotted = evaluate_command(config, "/usr/local/../bin/git status", dialect="posix", resolve_program=at_usr_bin)
    assert dotted.decision == "forbid"
    (dotted_match,) = dotted.matched_rules
    assert dotted_match.pin_violation is True
    assert asked == []
    assert evaluate_command(config, "/usr/bin/git status", dialect="posix").decision == "allow"  # no resolver at all

    evil = evaluate_command(config, "git status", dialect="posix", resolve_program=_resolver({"git": "/tmp/evil/git"}))
    assert (evil.decision, _only_segment(evil).basis) == ("forbid", "rule")
    (violation,) = evil.matched_rules
    assert violation.pin_violation is True
    assert violation.decision == "forbid"
    assert violation.resolved_program == "/tmp/evil/git"
    assert "/tmp/evil/git" in violation.justification
    assert violation.alternative is not None and "/usr/bin/git" in violation.alternative
    assert [m.rule for m in evil.governing] == ["git-ok"]

    outside = evaluate_command(config, "/tmp/evil/git status", dialect="posix")  # a path: refused whatever resolves
    assert outside.decision == "forbid"
    (outside_match,) = outside.matched_rules
    assert outside_match.pin_violation is True
    assert "/tmp/evil/git" in outside_match.justification

    for resolve in (None, _resolver({}), lambda name: None):  # no resolver, or one that cannot place the name
        unresolved = evaluate_command(config, "git status", dialect="posix", resolve_program=resolve)
        assert unresolved.decision == "forbid"
        (unproven,) = unresolved.matched_rules
        assert unproven.pin_violation is True
        assert unproven.resolved_program is None
        assert "does not resolve" in unproven.justification
    def not_a_path(name: str) -> int:
        return 3  # a resolver that answers with something that is not a path

    with pytest.raises(TypeError, match="command_policy_resolver_result_invalid"):
        evaluate_command(config, "git status", dialect="posix", resolve_program=not_a_path)  # type: ignore[arg-type]

    # cmd: the same program, any case and quoting, at the pinned path
    pinned = _policy(
        _rule("git-ok", ["git"], "allow", host_executable=[r"C:\Program Files\Git\cmd\git.exe"]), unmatched="escalate",
    )
    elsewhere = evaluate_command(pinned, r'"C:\Tools\git.exe" status', dialect="cmd")  # control: not the pinned path
    assert elsewhere.decision == "forbid"
    assert [m.pin_violation for m in elsewhere.matched_rules] == [True]
    shouted = evaluate_command(pinned, r'"C:\PROGRAM FILES\Git\cmd\GIT.exe" status', dialect="cmd")
    assert shouted.decision == "allow"
    assert [(m.pin_violation, m.resolved_program) for m in shouted.matched_rules] == [
        (False, r"C:\PROGRAM FILES\Git\cmd\GIT.exe")
    ]
    lower = _resolver({"git": r"c:\program files\git\cmd\git.exe"})  # a resolver answers in its own case
    assert evaluate_command(pinned, "git status", dialect="cmd", resolve_program=lower).decision == "allow"

    # several pins are alternatives: any one proves the program, and a refusal names all of them
    pins = ["/usr/bin/git", "/usr/local/bin/git"]
    two = _policy(_rule("git-ok", ["git"], "allow", host_executable=pins), unmatched="escalate")
    for path in pins:
        found = evaluate_command(two, "git status", dialect="posix", resolve_program=_resolver({"git": path}))
        assert found.decision == "allow", path
    outside_pins = _resolver({"git": "/opt/git/bin/git"})
    refused = evaluate_command(two, "git status", dialect="posix", resolve_program=outside_pins)
    assert refused.decision == "forbid"
    (refusal,) = refused.matched_rules
    assert refusal.alternative is not None
    assert all(pin in refusal.alternative for pin in pins)


def test_a_pin_violation_does_not_hide_other_matches() -> None:
    config = _policy(
        _rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git"]),
        _rule("no-force", ["git", "push", "--force"], "forbid"),
        unmatched="escalate",
    )
    # control: at the pinned path both rules match, neither as a violation
    pinned = evaluate_command(config, "/usr/bin/git push --force", dialect="posix")
    assert pinned.decision == "forbid"
    assert [(m.rule, m.decision, m.pin_violation) for m in pinned.matched_rules] == [
        ("git-ok", "allow", False),
        ("no-force", "forbid", False),
    ]

    evil = evaluate_command(config, "/tmp/evil/git push --force", dialect="posix")
    assert evil.decision == "forbid"
    assert [(m.rule, m.decision, m.pin_violation) for m in evil.matched_rules] == [
        ("git-ok", "forbid", True),
        ("no-force", "forbid", False),
    ]
    assert [m.rule for m in evil.governing] == ["git-ok", "no-force"]  # both carry the final decision


# --------------------------------------------------------------------------------------
# 10. The shape of an evaluation
# --------------------------------------------------------------------------------------


def test_evaluation_result_shape() -> None:
    config = _policy(_rule("no-push", ["git", "push"], "forbid"))
    result = evaluate_command(config, "/usr/bin/git push --force", dialect="posix")
    assert isinstance(result, CommandEvaluation)
    assert (result.status, result.decision, result.unparseable) == ("evaluated", "forbid", None)
    assert result.dialect == "posix"
    assert result.policy_digest == policy_digest(config)
    assert isinstance(result.matched_rules, tuple)
    assert isinstance(result.segments, tuple) and all(isinstance(v, SegmentVerdict) for v in result.segments)
    assert all(isinstance(m, RuleMatch) for m in result.matched_rules)
    (match,) = result.matched_rules
    assert match.matched_prefix == ("/usr/bin/git", "push")
    assert match.segment == 0
    assert match.rule == "no-push"
    assert (match.decision, match.justification) == ("forbid", "no-push because")
    assert match.alternative == "use the governed path"
    assert (match.resolved_program, match.pin_violation) == (None, False)  # a restrictive rule resolves nothing
    (verdict,) = result.segments
    assert verdict.segment.tokens == ("/usr/bin/git", "push", "--force")
    assert (verdict.index, verdict.decision, verdict.basis, verdict.matches) == (0, "forbid", "rule", (match,))
    assert result.governing == (match,)

    # the index is the segment's place in the command, not always 0
    later = evaluate_command(config, "git status && /usr/bin/git push --force", dialect="posix")
    assert [(v.index, v.decision) for v in later.segments] == [(0, "allow"), (1, "forbid")]
    assert [(m.segment, m.matched_prefix) for m in later.matched_rules] == [(1, ("/usr/bin/git", "push"))]


# --------------------------------------------------------------------------------------
# 11-14. The self-test, and the policy object that runs it
# --------------------------------------------------------------------------------------


def _push_rule(**examples: object) -> dict:
    return _rule("no-push", ["git", "push"], "forbid", **examples)


def _pinned_git_rule(**examples: object) -> dict:
    return _rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git"], **examples)


def test_self_test_passes_and_counts_examples() -> None:
    # the no-force not_match example ("git push origin") is matched by ANOTHER rule (git-ok); it must not count against
    # no-force, so the judge looks at the rule the example belongs to
    config = _policy(
        _rule(
            "no-force", ["git", "push", "--force"], "forbid",
            match=["git push --force origin"], not_match=["git push origin"],
        ),
        _rule("git-ok", ["git"], "allow", match=["git status"]),
        _rule("no-curl", ["curl"], "forbid", match=["curl x"], not_match=["wget x"]),
        _rule("no-sudo", ["sudo"], "escalate"),  # a rule without examples adds nothing to the count
        unmatched="escalate",
    )
    report = self_test(config, dialect="posix")
    assert isinstance(report, SelfTestReport)
    assert report.passed is True
    assert report.examples_checked == 5
    assert report.failures == ()
    assert report.dialect == "posix"

    policy = CommandPolicy(config, dialect="posix")  # builds: a policy whose examples hold
    assert policy.self_test_report == report

    # edge: nothing to check is not a failure
    assert self_test(CommandPolicyConfig(), dialect="posix") == SelfTestReport("posix", 0, ())
    assert self_test(_policy(_rule("no-sudo", ["sudo"], "escalate")), dialect="posix").examples_checked == 0


@pytest.mark.parametrize(
    ("wrong", "expectation", "example", "observed", "fixed"),
    [
        pytest.param(
            _push_rule(match=["git status"]), "match", "git status", "does not match",
            _push_rule(match=["git push origin"]), id="match_misses",
        ),
        pytest.param(
            _push_rule(not_match=["git push origin"]), "not_match", "git push origin", "matches it",
            _push_rule(not_match=["git status"]), id="not_match_hits",
        ),
        pytest.param(
            _push_rule(match=['git push "origin']), "match", 'git push "origin',
            "does not match: the example is unparseable",
            _push_rule(match=['git push "origin"']), id="match_unparseable",
        ),
        pytest.param(
            _push_rule(match=["eval git push"]), "match", "eval git push",
            "does not match: part of the example is unparseable",
            _push_rule(match=["git push --force"]), id="match_segment_unparseable",
        ),
        pytest.param(
            _pinned_git_rule(match=["git status"]), "match", "git status", "does not match",
            _pinned_git_rule(match=["/usr/bin/git status"]), id="pinned_match_with_bare_name",
        ),
    ],
)
def test_a_wrong_example_names_the_rule_and_the_example(
    wrong: dict, expectation: str, example: str, observed: str, fixed: dict,
) -> None:
    # control: the corrected example holds, so the policy builds and its self-test passes
    mended = _policy(fixed, unmatched="escalate")
    assert self_test(mended, dialect="posix").passed is True
    assert CommandPolicy(mended, dialect="posix").configured is True

    config = _policy(wrong, unmatched="escalate")
    report = self_test(config, dialect="posix")  # reports the failure; it does not raise
    assert report.passed is False
    assert report.examples_checked == 1
    (failure,) = report.failures
    assert (failure.rule, failure.expectation, failure.example) == (wrong["name"], expectation, example)
    assert failure.observed.startswith(observed)

    with pytest.raises(CommandPolicySelfTestError) as raised:
        CommandPolicy(config, dialect="posix")
    assert isinstance(raised.value, ValueError)
    text = str(raised.value)
    for needle in (wrong["name"], example, "posix", failure.message):
        assert needle in text, needle


def test_self_test_runs_under_the_dialect_given() -> None:
    config = _policy(_rule("echo-backslash", ["echo", "a\\b"], "forbid", match=["echo a\\b"]))
    # premise: cmd keeps ``a\b`` as one word; in POSIX a backslash quotes the next character, so ``\b`` is ``b``
    # (the example used to be ``echo a^&b``, but ``^`` is refused in cmd now, so cmd could no longer hold it)
    in_cmd = _only_segment(evaluate_command(config, "echo a\\b", dialect="cmd"))
    assert in_cmd.segment.tokens == ("echo", "a\\b")
    in_posix = evaluate_command(config, "echo a\\b", dialect="posix")
    assert [v.segment.tokens for v in in_posix.segments] == [("echo", "ab")]
    assert in_posix.matched_rules == ()

    # control first: under cmd the example holds
    assert self_test(config, dialect="cmd").passed is True
    assert CommandPolicy(config, dialect="cmd").dialect == "cmd"

    report = self_test(config, dialect="posix")
    assert report.dialect == "posix"
    assert report.passed is False
    assert [(f.rule, f.expectation, f.example) for f in report.failures] == [("echo-backslash", "match", "echo a\\b")]
    with pytest.raises(CommandPolicySelfTestError, match="posix"):
        CommandPolicy(config, dialect="posix")


def _failing_policy(count: int) -> CommandPolicyConfig:
    """``count`` rules on one pattern, each with one ``match`` example it does not match (unpinned, so no
    justification text is added to a failure and ``rule '`` appears once per failure)."""
    return _policy(*(_rule(f"r{n}", ["git", "push"], "forbid", match=[f"ls n{n}"]) for n in range(count)))


def test_report_lists_every_failure_and_the_message_stops_at_five() -> None:
    for count in (5, 6):  # control: the boundary. Five are all shown, a sixth is counted
        report = self_test(_failing_policy(count), dialect="posix")
        assert len(report.failures) == count
        with pytest.raises(CommandPolicySelfTestError) as raised:
            CommandPolicy(_failing_policy(count), dialect="posix")
        text = str(raised.value)
        assert text.count("rule '") == 5
        assert ("(and 1 more)" in text) == (count == 6)
        assert "(and" not in text or count == 6

    config = _failing_policy(7)
    report = self_test(config, dialect="posix")
    assert report.examples_checked == 7
    assert len(report.failures) == 7
    assert [f.example for f in report.failures] == [f"ls n{n}" for n in range(7)]  # in rule order
    with pytest.raises(CommandPolicySelfTestError) as raised:
        CommandPolicy(config, dialect="posix")
    text = str(raised.value)
    assert "(and 2 more)" in text
    assert text.count("rule '") == 5  # the first five, then a count
    for shown in report.failures[:5]:
        assert shown.message in text
    for hidden in report.failures[5:]:
        assert hidden.example not in text


# --------------------------------------------------------------------------------------
# 15. The policy object, across the whole chain
# --------------------------------------------------------------------------------------


def test_command_policy_surface() -> None:
    # operator YAML arrives as a plain dict; the chain below runs from there to what an agent is told
    config = CommandPolicyConfig.model_validate(
        {
            "unmatched_decision": "escalate",
            "rules": [
                _rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git"], match=["/usr/bin/git status"]),
                _rule("no-force", ["git", "push", "--force"], "forbid", not_match=["git push origin"]),
            ],
        }
    )
    policy = CommandPolicy(config, dialect="posix")
    assert policy.dialect == "posix"
    assert policy.digest == policy_digest(config)
    assert policy.config is config
    assert policy.configured is True
    assert policy.self_test_report == self_test(config, dialect="posix")

    resolve = _resolver({"git": "/usr/bin/git"})
    for command in ("git status", "git push --force", "bash -c 'git status && ls'", "ls", 'echo "x', "eval x"):
        assert policy.evaluate(command) == evaluate_command(config, command, dialect="posix"), command
        assert policy.evaluate(command, resolve_program=resolve) == evaluate_command(
            config, command, dialect="posix", resolve_program=resolve
        ), command
        assert policy.canonical(command) == canonical_command(command, dialect="posix", limits=config), command
        assert policy.canonical(command, resolve_program=resolve) == canonical_command(
            command, dialect="posix", resolve_program=resolve, limits=config
        ), command

    # the resolver reaches the evaluation and the canonical command through the object (so it is not ignored)
    assert policy.evaluate("git status").decision == "forbid"  # a bare name nothing resolves
    assert policy.evaluate("git status", resolve_program=resolve).decision == "allow"
    assert policy.canonical("git status").parts == ("git", "status")
    assert policy.canonical("git status", resolve_program=resolve).parts == ("/usr/bin/git", "status")
    # ... and the policy's own bounds reach it too
    no_force = _policy(_rule("no-force", ["git", "push", "--force"], "forbid"), max_nesting=0)
    shallow = CommandPolicy(no_force, dialect="posix")
    assert shallow.canonical("bash -c 'git status'").kind == "script"
    assert canonical_command("bash -c 'git status'", dialect="posix").kind == "argv"  # control: the default bound

    # the chain end to end: a compound command through a wrapper, what is decided and what the agent is told
    # AD-1328 S1 r2 (F2): a line of two or more segments proves no bare program's lookup context, so the chain pins its
    # programs by absolute path; the bare spelling is asserted below (the contract's Part A did not list this row).
    result = policy.evaluate("/usr/bin/git status && bash -c '/usr/bin/git push --force origin'", resolve_program=resolve)
    assert [v.decision for v in result.segments] == ["allow", "forbid"]
    assert result.decision == "forbid"
    (told,) = result.governing
    assert (told.rule, told.justification) == ("no-force", "no-force because")
    assert told.alternative == "use the governed path"
    assert policy.canonical("git status", resolve_program=resolve).key == canonical_command(
        "/usr/bin/git status", dialect="posix"
    ).key

    # the same chain with bare names (r2, F2): neither segment proves its lookup context, so each pinned `allow` becomes
    # a pin violation and the agent is told to run the pinned executable, besides the rule that forbids the force push
    bare = policy.evaluate("git status && bash -c 'git push --force origin'", resolve_program=resolve)
    assert [v.decision for v in bare.segments] == ["forbid", "forbid"]
    assert bare.decision == "forbid"
    assert [(m.rule, m.pin_violation) for m in bare.matched_rules if m.rule == "git-ok"] == [("git-ok", True)] * 2
    assert {g.alternative for g in bare.governing} == {"run the pinned executable: /usr/bin/git", "use the governed path"}

    # a config that is not a CommandPolicyConfig is refused at every door, and a dict is what an operator wrote
    for bad in (config.model_dump(), {}, None):
        with pytest.raises(TypeError, match="^command_policy_config_type_invalid$"):
            CommandPolicy(bad, dialect="posix")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="^command_policy_config_type_invalid$"):
            evaluate_command(bad, "ls", dialect="posix")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="^command_policy_config_type_invalid$"):
            self_test(bad, dialect="posix")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="^command_policy_config_type_invalid$"):
            policy_digest(bad)  # type: ignore[arg-type]

    # the other arguments are checked too: a dialect that is none of the three, and a command that is not text
    for bad_dialect in ("bash", 1):
        with pytest.raises(ValueError, match="^command_policy_dialect_invalid$"):
            evaluate_command(config, "ls", dialect=bad_dialect)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="^command_policy_dialect_invalid$"):
            self_test(config, dialect=bad_dialect)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="^command_policy_dialect_invalid$"):
            CommandPolicy(config, dialect=bad_dialect)  # type: ignore[arg-type]
    for bad_command in (None, 3, b"ls"):
        with pytest.raises(TypeError, match="^command_policy_command_type_invalid$"):
            evaluate_command(config, bad_command, dialect="posix")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="^command_policy_command_type_invalid$"):
            policy.evaluate(bad_command)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# R-M3. S1 repair R1 (prompts/ad-1328-s1-repair-r1.md): the repaired evaluator
# --------------------------------------------------------------------------------------


def test_dynamic_words_align_with_restrictive_patterns() -> None:
    # An expanded word is zero or more words when unquoted and exactly one when quoted (oracle rows P15 and P18 for
    # posix, C08 for cmd, S12 and S24 for powershell). A restrictive rule must catch every way the expansion can
    # line up with its pattern; an allow rule must not take an expansion inside its pattern as proof.
    deny = _policy(_rule("no-force", ["git", "push", "--force"], "forbid"))
    assert deny.unmatched_decision == "allow"  # premise: nothing but the rule can forbid
    for command, decision in (("git push --force", "forbid"), ("git status", "allow")):  # control: plain words
        assert evaluate_command(deny, command, dialect="posix").decision == decision, command
    # premise (P15): ``$W`` may be zero or more words, ``"$W"`` exactly one
    assert _only_segment(evaluate_command(deny, "git $W", dialect="posix")).segment.variadic == (False, True)
    assert _only_segment(evaluate_command(deny, 'git "$W"', dialect="posix")).segment.variadic == (False, False)

    for dialect, command in (
        ("posix", "git $W"),  # ``$W`` may be ``push --force``
        ("posix", "git $W --force"),
        ("posix", "git push $F"),
        ("posix", 'git "$W" --force'),  # ``"$W"`` is one word, and may be ``push``
        ("posix", 'git "$A" "$B"'),
        ("powershell", "git *"),
        ("powershell", "git '*'"),
        ("cmd", "git push *"),
    ):
        result = evaluate_command(deny, command, dialect=dialect)
        only = _only_segment(result)
        assert any(only.segment.dynamic), (dialect, command)  # premise: the shell computes a word
        assert (result.decision, only.basis) == ("forbid", "rule"), (dialect, command)
        assert [m.rule for m in result.matched_rules] == ["no-force"], (dialect, command)

    # the match says how far the pattern reached: the expanded word stands in the second place, as its literal text
    (match,) = evaluate_command(deny, "git $W", dialect="posix").matched_rules
    assert match.matched_prefix == ("git", "")

    # an expansion cannot fill a place the command lacks (``"$W"`` is one word and the pattern needs two), nor stand
    # in for a word the command spells out differently
    for command in ('git "$W"', "git status $W"):
        result = evaluate_command(deny, command, dialect="posix")
        only = _only_segment(result)
        assert any(only.segment.dynamic), command  # premise: a word is computed, and the pattern still cannot fit
        assert (result.decision, only.basis) == ("allow", "unmatched"), command
        assert result.matched_rules == (), command

    # an allow rule needs proof: an expansion where the pattern wants a literal is none, one past the pattern is fine
    allow = _policy(_rule("push-ok", ["git", "push"], "allow"), unmatched="escalate")
    plain = evaluate_command(allow, "git push", dialect="posix")  # control: the plain spelling
    assert (plain.decision, _only_segment(plain).basis) == ("allow", "rule")
    for command in ("git $W", "git push$X"):
        result = evaluate_command(allow, command, dialect="posix")
        only = _only_segment(result)
        assert any(only.segment.dynamic), command  # premise: a word the pattern needs is computed
        assert (result.decision, only.basis) == ("escalate", "unmatched"), command
        assert result.matched_rules == (), command
    for command in ("git push $X", 'git push "$X"'):
        result = evaluate_command(allow, command, dialect="posix")
        only = _only_segment(result)
        assert only.segment.dynamic == (False, False, True), command  # premise: only the third word is computed
        assert (result.decision, only.basis) == ("allow", "rule"), command
        assert [m.rule for m in result.matched_rules] == ["push-ok"], command


def _git_verdict(result: CommandEvaluation) -> SegmentVerdict:
    """The verdict of the one segment that runs git (a compound command has others, such as ``cd sub``)."""
    git = [v for v in result.segments if v.segment.tokens and v.segment.tokens[0] in ("git", "/usr/bin/git")]
    assert len(git) == 1, [v.segment.tokens for v in result.segments]
    return git[0]


def test_pin_proof_needs_the_starting_lookup_context() -> None:
    # The resolver answers for the context a command STARTS in. A line that changes it (a cd, PATH, a login shell,
    # ``command -p``, a PowerShell profile) leaves a bare name unproven, and the pinned allow rule then forbids it
    # (oracle rows P25 for bash -lc, C11 and S13 for powershell -NoProfile -Command).
    pinned = _policy(_rule("git-ok", ["git"], "allow", host_executable=["/usr/bin/git"]), unmatched="escalate")
    resolve = _resolver({"git": "/usr/bin/git"})
    start = evaluate_command(pinned, "git status", dialect="posix", resolve_program=resolve)  # control
    assert (start.decision, _only_segment(start).basis) == ("allow", "rule")
    assert [(m.pin_violation, m.resolved_program) for m in start.matched_rules] == [(False, "/usr/bin/git")]

    for command, cause in {
        "cd sub && git status": "changes the working directory or the environment (cd)",
        "export PATH=/tmp/x && git status": "changes the working directory or the environment (export)",
        "command -p git status": "default PATH",
        "bash -lc 'git status'": "login shell",
    }.items():
        result = evaluate_command(pinned, command, dialect="posix", resolve_program=resolve)
        verdict = _git_verdict(result)
        assert verdict.segment.lookup_changed is not None, command  # premise: the line says its context changed
        (match,) = verdict.matches
        assert (match.decision, match.pin_violation) == ("forbid", True), command
        assert (verdict.decision, verdict.basis, result.decision) == ("forbid", "rule", "forbid"), command
        assert "not proven" in match.justification and cause in match.justification, command

    # a path is its own proof, whatever the context did; and a script that changes nothing keeps the starting context
    result = evaluate_command(pinned, "cd sub && /usr/bin/git status", dialect="posix", resolve_program=resolve)
    verdict = _git_verdict(result)
    assert verdict.segment.lookup_changed is not None  # premise: the context did change, and the path still proves it
    assert (verdict.decision, verdict.basis) == ("allow", "rule")
    assert [(m.pin_violation, m.resolved_program) for m in verdict.matches] == [(False, "/usr/bin/git")]
    wrapped = evaluate_command(pinned, "bash -c 'git status'", dialect="posix", resolve_program=resolve)
    verdict = _only_segment(wrapped)
    assert (verdict.segment.depth, verdict.segment.lookup_changed) == (1, None)  # premise: unwrapped, context kept
    assert (wrapped.decision, verdict.basis) == ("allow", "rule")

    windows_git = "C:\\Program Files\\Git\\cmd\\git.exe"
    pinned_cmd = _policy(_rule("git-ok", ["git"], "allow", host_executable=[windows_git]), unmatched="escalate")
    resolve_cmd = _resolver({"git": windows_git})
    start = evaluate_command(pinned_cmd, "git status", dialect="cmd", resolve_program=resolve_cmd)  # control
    assert (start.decision, _only_segment(start).basis) == ("allow", "rule")
    for command, cause in {
        'powershell -Command "git status"': "-NoProfile",
        "cd x & git status": "changes the working directory or the environment (cd)",
    }.items():
        result = evaluate_command(pinned_cmd, command, dialect="cmd", resolve_program=resolve_cmd)
        verdict = _git_verdict(result)
        assert verdict.segment.lookup_changed is not None, command  # premise: the line says its context changed
        (match,) = verdict.matches
        assert (match.decision, match.pin_violation, verdict.decision) == ("forbid", True, "forbid"), command
        assert "not proven" in match.justification and cause in match.justification, command
    no_profile = evaluate_command(
        pinned_cmd, 'powershell -NoProfile -Command "git status"', dialect="cmd", resolve_program=resolve_cmd
    )
    verdict = _only_segment(no_profile)
    assert (verdict.segment.depth, verdict.segment.lookup_changed) == (1, None)  # premise: no profile, context kept
    assert (no_profile.decision, verdict.basis) == ("allow", "rule")


def test_inherited_assignments_block_an_allow_match() -> None:
    # The assignment before ``sh -c`` is inherited by the commands of its script (oracle rows P14 and P22), and an
    # allow rule never matches a command that runs under assignments. A restrictive rule still matches it.
    allow = _policy(_rule("status-ok", ["git", "status"], "allow"), unmatched="escalate")
    plain = evaluate_command(allow, "sh -c 'git status'", dialect="posix")  # control: no assignment, so allowed
    only = _only_segment(plain)
    assert (only.segment.assignments, only.segment.depth) == ((), 1)  # premise: unwrapped, nothing inherited
    assert (plain.decision, only.basis) == ("allow", "rule")

    inherited = evaluate_command(allow, "X=1 sh -c 'git status'", dialect="posix")
    only = _only_segment(inherited)
    assert (only.segment.tokens, only.segment.assignments) == (("git", "status"), ("X=1",))  # premise: inherited
    assert (inherited.decision, only.basis) == ("escalate", "unmatched")
    assert inherited.matched_rules == ()

    deny = _policy(_rule("no-force", ["git", "push", "--force"], "forbid"))
    forbidden = evaluate_command(deny, "X=1 sh -c 'git push --force'", dialect="posix")
    only = _only_segment(forbidden)
    assert only.segment.assignments == ("X=1",)  # premise: the same inherited assignment
    assert (forbidden.decision, only.basis) == ("forbid", "rule")
    assert [m.rule for m in forbidden.matched_rules] == ["no-force"]


def test_a_powershell_string_is_not_an_invocation() -> None:
    # A quoted string at the start of a PowerShell statement is an expression, which PowerShell prints and does not
    # run; only the call operator runs it (oracle row S01 for the call operator).
    config = _policy(_rule("esc-git", ["git"], "escalate"))  # unmatched="allow"
    invoked = evaluate_command(config, '& "C:/x/git.exe" status', dialect="powershell")  # control: the call operator
    only = _only_segment(invoked)
    assert only.segment.tokens == ("C:/x/git.exe", "status")  # premise: read as an invocation of that path
    assert (invoked.decision, only.basis) == ("escalate", "rule")
    assert [m.rule for m in invoked.matched_rules] == ["esc-git"]

    bare = evaluate_command(config, '"C:/x/git.exe" status', dialect="powershell")
    only = _only_segment(bare)  # the line is read; its one segment is what is refused
    assert only.segment.unparseable is not None and "an expression, not a command" in only.segment.unparseable
    assert (bare.decision, only.basis) == ("escalate", "unparseable")
    assert bare.matched_rules == ()  # never taken for the rule's git


def test_wrapper_option_forms_never_reach_allow() -> None:
    # A process wrapper the policy reads is stripped and what it runs is judged (oracle row P26). A wrapper in an
    # option form it does not read could be hiding the program, so its segment is refused: ``escalate``, never ``allow``.
    config = _policy(_rule("no-force", ["git", "push", "--force"], "forbid"))  # unmatched="allow"
    for command in ("command git push --force", "nice -n 5 git push --force", "stdbuf -oL git push --force"):
        result = evaluate_command(config, command, dialect="posix")  # control: the accepted forms
        only = _only_segment(result)
        assert only.segment.wrappers != (), command  # premise: the wrapper was stripped
        assert only.segment.tokens == ("git", "push", "--force"), command
        assert (result.decision, only.basis) == ("forbid", "rule"), command

    dash_p = evaluate_command(config, "command -p git push --force", dialect="posix")
    only = _only_segment(dash_p)
    assert only.segment.wrappers == ("command -p",)  # premise: ``-p`` is read as a wrapper option
    assert (dash_p.decision, only.basis) == ("forbid", "rule")

    for command in (
        "command -- git push --force",
        "nice -n 5 -n 3 git push --force",
        "stdbuf -oL -- git push --force",
    ):
        result = evaluate_command(config, command, dialect="posix")
        only = _only_segment(result)  # the line is read; its one segment is what is refused
        assert only.segment.unparseable is not None, command
        assert "options the policy does not read" in only.segment.unparseable, command
        assert (result.decision, only.basis) == ("escalate", "unparseable"), command
        assert result.matched_rules == (), command


def test_transport_follows_what_the_launcher_receives() -> None:
    # cmd hands the words after ``-Command`` to PowerShell as they are, and PowerShell joins them with one blank into
    # the script it runs: ``git`` and ``push --force`` are the script ``git push --force`` (oracle rows C11 and C12).
    config = _policy(_rule("no-force", ["git", "push", "--force"], "forbid"))  # unmatched="allow"
    one_word = evaluate_command(config, 'powershell -NoProfile -Command "git push --force"', dialect="cmd")  # control
    assert (one_word.decision, _only_segment(one_word).basis) == ("forbid", "rule")
    other = evaluate_command(config, 'powershell -NoProfile -Command git "push origin"', dialect="cmd")  # control
    assert (other.decision, _only_segment(other).basis) == ("allow", "unmatched")

    split = evaluate_command(config, 'powershell -NoProfile -Command git "push --force"', dialect="cmd")
    only = _only_segment(split)
    assert (only.segment.depth, only.segment.tokens) == (1, ("git", "push", "--force"))  # premise: joined, then read
    assert (split.decision, only.basis) == ("forbid", "rule")
    assert [m.rule for m in split.matched_rules] == ["no-force"]


def test_restrictive_rules_fold_the_program_spelling_in_every_dialect() -> None:
    deny = _policy(_rule("no-curl", ["curl"], "forbid"))  # unmatched="allow"
    plain = evaluate_command(deny, "curl x", dialect="posix")  # control: the plain spelling
    assert (plain.decision, _only_segment(plain).basis) == ("forbid", "rule")
    other = evaluate_command(deny, "git x", dialect="posix")  # control: another program is not caught
    assert (other.decision, _only_segment(other).basis) == ("allow", "unmatched")
    for dialect, command in (
        ("posix", "CURL x"),
        ("posix", "curl.exe x"),
        ("posix", "/usr/bin/CURL x"),
        ("cmd", "CURL x"),
        ("cmd", "curl.exe x"),
        ("powershell", "CURL x"),
        ("powershell", "curl.exe x"),
    ):
        result = evaluate_command(deny, command, dialect=dialect)
        only = _only_segment(result)
        assert (result.decision, only.basis) == ("forbid", "rule"), (dialect, command)
        assert [m.rule for m in result.matched_rules] == ["no-curl"], (dialect, command)

    # an allow rule stays exact: a spelling it does not name is not proven
    allow = _policy(_rule("curl-ok", ["curl"], "allow"), unmatched="escalate")
    named = evaluate_command(allow, "curl x", dialect="posix")  # control: the spelling it names
    assert (named.decision, _only_segment(named).basis) == ("allow", "rule")
    spelled = evaluate_command(allow, "CURL x", dialect="posix")
    assert (spelled.decision, _only_segment(spelled).basis) == ("escalate", "unmatched")
    assert spelled.matched_rules == ()


def test_malformed_text_is_judged_not_raised() -> None:
    # Text that is not valid Unicode (a lone surrogate) is unreadable: judged ``escalate``, never ``allow``, and never
    # an exception; its approval key is still computed.
    cfg = _policy(_rule("no-curl", ["curl"], "forbid"))  # unmatched="allow", unparseable_decision="escalate"
    assert (cfg.unmatched_decision, cfg.unparseable_decision) == ("allow", "escalate")  # premise: they differ
    for dialect in ("posix", "cmd", "powershell"):
        readable = evaluate_command(cfg, "git x", dialect=dialect)  # control: the accepted neighbour
        assert (readable.decision, _only_segment(readable).basis) == ("allow", "unmatched"), dialect
        malformed = evaluate_command(cfg, "git \ud800", dialect=dialect)
        assert malformed.status == "evaluated", dialect
        assert malformed.decision == "escalate", dialect
        assert malformed.unparseable is not None and "lone surrogate" in malformed.unparseable, dialect
        assert malformed.segments == (), dialect

    policy = CommandPolicy(cfg, dialect="posix")
    assert policy.canonical("git x").kind == "argv"  # control: readable text has an argv key
    key = policy.canonical("git \ud800").key  # does not raise
    assert len(key) == 64 and key != policy.canonical("git x").key


# --------------------------------------------------------------------------------------
# 16. Not wired: nothing under src/ constructs the policy (S2 changes this deliberately: O-S1-9)
# --------------------------------------------------------------------------------------

_SRC_PROBOS = Path(__file__).resolve().parent.parent / "src" / "probos"
_OWNER = "execution/command_policy.py"  # the module that defines the policy: spared by the whole scan
_MODELS = "config_models/operations.py"  # the module that defines its models: spared by the names rule only
_MODULE = "command_policy"
_CONSTRUCTED = "CommandPolicy"
_IMPORTED_NAMES = frozenset(
    {
        "CommandPolicyConfig",
        "CommandPolicyRule",
        "CommandPolicy",
        "evaluate_command",
        "canonical_command",
        "policy_digest",
    }
)
# ``policy_digest`` is also an ordinary local name: execution/authority.py binds one and reads it a few lines on, and
# cognitive/execution_profile.py has a field of that name. A bare read of it proves nothing, so it counts only when
# imported (the contract's literal rule, any ``ast.Name`` load of it, flags authority.py).
_LOADED_NAMES = _IMPORTED_NAMES - {"policy_digest"}


def _references(tree: ast.AST, *, names: bool = True) -> list[str]:
    """Direct syntactic references in ``tree`` to the policy.

    Always: an import of a module named ``command_policy`` (``import``, ``from ... import``, relative), and a call
    whose callee is ``CommandPolicy`` (a name or an attribute). With ``names``: an imported name from
    ``_IMPORTED_NAMES`` and a load of a name in ``_LOADED_NAMES``. Not found here: a lookup by string (``getattr``,
    ``importlib``), which this scan does not assert either way, and an attribute load such as
    ``module.evaluate_command``.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == _MODULE:
                    found.append(f"import of {alias.name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            if _MODULE in [(node.module or "").split(".")[-1], *(alias.name for alias in node.names)]:
                found.append(f"import-from of {_MODULE} at line {node.lineno}")
            if names:
                taken = [alias.name for alias in node.names if alias.name in _IMPORTED_NAMES]
                found.extend(f"import of {name} at line {node.lineno}" for name in taken)
        elif isinstance(node, ast.Call):
            func = node.func
            callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if callee == _CONSTRUCTED:
                found.append(f"call of {callee} at line {node.lineno}")
        elif names and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in _LOADED_NAMES:
            found.append(f"load of {node.id} at line {node.lineno}")
    return found


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def _scan(
    root: Path, owner: str | None, models: str | None,
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Every ``*.py`` under ``root`` bar ``owner``: ``(considered, parsed, offenders)`` as relative posix paths.

    ``models`` is scanned, but the names rule is off for it. A file is parsed only when its text names the module or
    one of the names (no other file can reference them), and ``offenders`` maps each parsed file to its references.
    """
    needles = (_MODULE, *_IMPORTED_NAMES)
    considered: list[str] = []
    parsed: list[str] = []
    offenders: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == owner:
            continue
        considered.append(relative)
        text = path.read_text(encoding="utf-8-sig")
        if not any(needle in text for needle in needles):
            continue
        parsed.append(relative)
        references = _references(ast.parse(text, filename=str(path)), names=relative != models)
        if references:
            offenders[relative] = references
    return considered, parsed, offenders


_ALLOWED_SHAPES = (
    'note = "CommandPolicy is in probos.execution.command_policy"',
    '"""A docstring that names CommandPolicy, evaluate_command and probos.execution.command_policy."""',
    "from probos.config_models.operations import ExecutionConfig",
    "from probos.execution.command_policy_notes import Notes",
    "policy = CommandPolicyFactory(cfg)",
    "policy_digest = sha(b'x')\nrecord = {'policy_sha256': policy_digest}",
)
_FORBIDDEN_SHAPES = (
    "from probos.execution.command_policy import CommandPolicy",
    "from probos.execution import command_policy",
    "import probos.execution.command_policy as p",
    "import probos.execution.command_policy",
    "from .command_policy import evaluate_command",
    "from . import command_policy",
    "CommandPolicy(cfg)",
    "registry.CommandPolicy(cfg)",
    "async def f():\n    return CommandPolicy(cfg)",
    "from probos.config_models.operations import CommandPolicyConfig",
    "from probos.config_models.operations import CommandPolicyRule as Rule",
    "def late():\n    from probos.execution.command_policy import policy_digest\n",
    "result = evaluate_command",
    "key = canonical_command",
    "config = CommandPolicyConfig.model_validate({})",
)


def test_nothing_in_src_constructs_the_policy(tmp_path: Path) -> None:
    """No file under ``src/probos`` bar the policy module itself imports it, constructs it or takes its names.

    The scan is AST-based, so a string or a docstring that merely names the module or a class is not a reference, and
    it is not vacuous: each shape it exists to forbid is flagged, in a snippet, in a scratch tree and in the real files
    that define the names.
    """
    # premise: the two modules the scan spares are where it expects them, and define what the scan is about
    owner_tree = _parse(_SRC_PROBOS / _OWNER)
    models_tree = _parse(_SRC_PROBOS / _MODELS)
    owner_defs = {n.name for n in ast.walk(owner_tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
    assert {"CommandPolicy", "evaluate_command", "canonical_command", "policy_digest"} <= owner_defs
    model_classes = {n.name for n in ast.walk(models_tree) if isinstance(n, ast.ClassDef)}
    assert {"CommandPolicyConfig", "CommandPolicyRule"} <= model_classes

    # the walker flags each shape it forbids, and not a string, a docstring, a near miss or an unrelated local name
    for snippet in _ALLOWED_SHAPES:
        assert _references(ast.parse(snippet)) == [], snippet
    for snippet in _FORBIDDEN_SHAPES:
        assert _references(ast.parse(snippet)), snippet
    # the models module is spared the names rule only: it still may not import the policy module
    assert _references(ast.parse("from probos.config_models.operations import CommandPolicyConfig"), names=False) == []
    assert _references(ast.parse("from probos.execution import command_policy"), names=False)
    assert _references(ast.parse("CommandPolicy(cfg)"), names=False)
    # ... nor only on snippets: the real files that define the names are flagged when nothing spares them
    assert _references(owner_tree)
    assert _references(models_tree)
    assert _references(models_tree, names=False) == []  # ... and the exemption is what spares the models module

    # a scratch tree: every shape in a file of its own (flagged or not), plus the owner, the models module, neighbours
    scratch = tmp_path / "scratch"
    files = {
        "execution/command_policy.py": "from probos.config_models.operations import CommandPolicyConfig\n"
        "class CommandPolicy:\n    pass\nPOLICY = CommandPolicy(None)\n",
        "config_models/operations.py": "class CommandPolicyRule:\n    pass\nclass CommandPolicyConfig:\n"
        "    rules: tuple[CommandPolicyRule, ...] = ()\n",
        "config_models/other.py": "from probos.config_models.operations import CommandPolicyRule\n",
        "tools/declares.py": '"""Names CommandPolicy and probos.execution.command_policy in text only."""\n'
        "MODULE = 'probos.execution.command_policy'\nCLASS = 'CommandPolicy'\n",
        "tools/unrelated.py": "VALUE = 1\n",
    }
    forbidden_files = [f"forbidden/shape_{number:02d}.py" for number in range(len(_FORBIDDEN_SHAPES))]
    for relative, snippet in zip(forbidden_files, _FORBIDDEN_SHAPES):
        files[relative] = snippet + "\n"
    for number, snippet in enumerate(_ALLOWED_SHAPES):
        files[f"allowed/shape_{number:02d}.py"] = snippet + "\n"
    for relative, text in files.items():
        target = scratch / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    considered, parsed, offenders = _scan(scratch, _OWNER, _MODELS)
    assert [path for path in offenders if path.startswith("forbidden/")] == forbidden_files  # each forbidden shape
    assert not [path for path in offenders if path.startswith("allowed/")]  # and none of the allowed ones
    # exempt per file, not per directory
    assert sorted(set(offenders) - set(forbidden_files)) == ["config_models/other.py"]
    assert "tools/declares.py" in parsed and "tools/declares.py" not in offenders  # strings only: parsed, not flagged
    assert "tools/unrelated.py" in considered and "tools/unrelated.py" not in parsed  # it names nothing: not parsed
    assert _OWNER not in considered  # premise: the owner was spared
    assert _MODELS in considered and _MODELS in parsed  # premise: the models module was scanned, names rule off
    assert _MODELS not in offenders
    # control: the two exemptions are the only things sparing the owner and the models module
    _, _, unspared = _scan(scratch, None, None)
    assert {_OWNER, _MODELS} <= set(unspared)

    # the real tree: the scan reached it, and it holds no reference ...
    considered, parsed, offenders = _scan(_SRC_PROBOS, _OWNER, _MODELS)
    assert {"execution/authority.py", "config_models/__init__.py", "config.py"} <= set(considered)  # it walked the tree
    assert _OWNER not in considered  # premise: the owner was spared
    assert _MODELS in considered  # premise: the models module was scanned, with the names rule off
    assert offenders == {}
    # ... and the same scan with nothing spared finds the real files that define the names, so no path or layout slip
    # can hide a reference
    _, _, unspared = _scan(_SRC_PROBOS, None, None)
    assert set(unspared) == {_OWNER, _MODELS}


# --------------------------------------------------------------------------------------
# 17. The policy module is pure: no process, environment or file access
# --------------------------------------------------------------------------------------

_POLICY_SOURCE = _SRC_PROBOS / _OWNER
_PURE_IMPORTS = frozenset(
    {
        "__future__",
        "hashlib",
        "ntpath",
        "posixpath",
        "re",
        "sys",
        "unicodedata",
        "collections.abc",
        "dataclasses",
        "typing",
        "probos.config_models.operations",
    }
)
_LAZY_IMPORTS = {"_canonical_json": frozenset({"probos.federation.ard.jcs"})}
_IMPURE_NAMES = frozenset({"open", "os", "subprocess", "asyncio", "shutil", "__import__"})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _import_scopes(tree: ast.AST) -> dict[str | None, frozenset[str]]:
    """Every module ``tree`` imports, keyed by the function it is imported in (None: at module level)."""
    parents = _parents(tree)
    scopes: dict[str | None, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules = {"." * node.level + (node.module or "")}
        else:
            continue
        scope: str | None = None
        cursor = parents.get(node)
        while cursor is not None and scope is None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = cursor.name
            cursor = parents.get(cursor)
        scopes.setdefault(scope, set()).update(modules)
    return {scope: frozenset(modules) for scope, modules in scopes.items()}


def _impurities(source: str) -> list[str]:
    """Why ``source`` is not a pure module: an import outside the expected set, an impure name, or a use of ``sys``
    other than ``sys.platform``."""
    tree = ast.parse(source)
    parents = _parents(tree)
    scopes = _import_scopes(tree)
    problems: list[str] = []
    if scopes.get(None, frozenset()) != _PURE_IMPORTS:
        problems.append(f"module-level imports are {sorted(scopes.get(None, frozenset()))}")
    for scope, modules in scopes.items():
        if scope is not None and modules != _LAZY_IMPORTS.get(scope, frozenset()):
            problems.append(f"{scope}() imports {sorted(modules)}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        if node.id in _IMPURE_NAMES:
            problems.append(f"the name {node.id} at line {node.lineno}")
        if node.id == "sys":
            parent = parents.get(node)
            if not (isinstance(parent, ast.Attribute) and parent.value is node and parent.attr == "platform"):
                problems.append(f"sys is used as more than sys.platform at line {node.lineno}")
    return problems


def test_the_policy_module_is_pure() -> None:
    source = _POLICY_SOURCE.read_text(encoding="utf-8-sig")
    # premise: the check sees what it should: the module-level imports, and the one lazy import in _canonical_json
    expected_scopes = {None: _PURE_IMPORTS, "_canonical_json": _LAZY_IMPORTS["_canonical_json"]}
    assert dict(_import_scopes(ast.parse(source))) == expected_scopes
    tree = ast.parse(source)
    assert any(isinstance(n, ast.Name) and n.id == "sys" for n in ast.walk(tree))  # sys.platform is used, and allowed

    assert _impurities(source) == []

    # control: the same check flags a scratch module that imports os, and each other way to become impure
    assert _impurities("import os\n")
    for label, scratch in {
        "import os": source + "\nimport os\n",
        "from os import environ": source + "\nfrom os import environ\n",
        "subprocess inside a function": source + "\n\ndef _launch():\n    import subprocess\n    return subprocess\n",
        "the open builtin": source + "\nTEXT = open('x').read()\n",
        "sys.exit": source + "\nsys.exit(1)\n",
        "sys as a value": source + "\nPLATFORM = sys\n",
        "a lazy import in another function": source
        + "\n\ndef _other():\n    from probos.federation.ard.jcs import canonicalize\n",
        "the lazy import at module level": source + "\nfrom probos.federation.ard.jcs import canonicalize\n",
        "asyncio": source + "\nLOOP = asyncio\n",
        "__import__": source + "\nMODULE = __import__('os')\n",
    }.items():
        assert _impurities(scratch), label


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
