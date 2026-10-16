"""AD-1328 S1 (#1530), milestone M1 -- the command policy's models and its digest.

Targets ``CommandPolicyRule``, ``CommandPolicyConfig`` and ``windows_program_stem`` in
``probos.config_models.operations`` and ``policy_digest`` / ``POLICY_DIGEST_SCHEME`` in
``probos.execution.command_policy``. The contract is ``prompts/ad-1328-s1-command-policy-core.md``
("Tests", M1 #1-14). Models are built with ``model_validate`` from plain dicts, the way an
operator's YAML arrives, and the only engine call is ``policy_digest``. Nothing here reads a
file, starts a process or looks at the environment, so the file passes on Windows and on Linux.

How the refusal tests are built. Each one constructs the accepted neighbour first -- the same
input one change away from the refused one -- and then the refused input, so a test cannot pass
by refusing everything. Refusals are asserted on the validators' own messages
(``ValidationError.errors()``), which are a subset of ``str(exc)``: pydantic also echoes the
rejected input into ``str(exc)``, and that input carries the rule's name, so a rule name
asserted against ``str(exc)`` would pass even if the message never named the rule.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import probos.config as config_facade
import probos.config_models as config_package
from probos.config_models import operations
from probos.config_models.operations import (
    CommandPolicyConfig,
    CommandPolicyRule,
    ExecutionConfig,
    windows_program_stem,
)
from probos.execution.command_policy import POLICY_DIGEST_SCHEME, policy_digest
from probos.federation.ard.jcs import canonicalize

# ---------------------------------------------------------------------------
# Helpers (copied shape from the contract; no import across test files)
# ---------------------------------------------------------------------------


def _rule(name: str, pattern: list[Any], decision: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "pattern": pattern,
        "decision": decision,
        "justification": f"{name} because",
    }
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


def _config(*rules: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"rules": list(rules), **fields}


def _refusal(model: type[BaseModel], raw: dict[str, Any]) -> dict[str, Any]:
    """The one error ``model`` raised for ``raw``; the test fails if ``raw`` is accepted."""
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(raw)
    errors = excinfo.value.errors()
    assert len(errors) == 1, errors
    return dict(errors[0])


def _value_error(model: type[BaseModel], raw: dict[str, Any]) -> str:
    """The message of the one ``value_error`` a validator raised for ``raw``."""
    error = _refusal(model, raw)
    assert error["type"] == "value_error", error
    return str(error["msg"])


def _as_tuples(pattern: list[Any]) -> tuple[Any, ...]:
    return tuple(tuple(entry) if isinstance(entry, list) else entry for entry in pattern)


def _positions(count: int) -> list[Any]:
    """A pattern of exactly ``count`` positions: the program, then ``count - 1`` words."""
    return ["git", *(f"w{index}" for index in range(count - 1))]


def _many_rules(count: int) -> list[dict[str, Any]]:
    return [_rule(f"rule-{index}", [f"prog{index}"], "allow") for index in range(count)]


# ---------------------------------------------------------------------------
# M1 #1-6: the rule
# ---------------------------------------------------------------------------

_MINIMAL_RULE: dict[str, Any] = {
    "name": "ls-read-only",
    "pattern": ["ls"],
    "decision": "allow",
    "justification": "listing is read-only",
}


@pytest.mark.parametrize("missing", ["name", "pattern", "decision", "justification"])
def test_minimal_rule_is_accepted_and_required_fields_are_required(missing: str) -> None:
    """The four required fields alone make a rule; each one missing is a ``missing`` error."""
    rule = CommandPolicyRule.model_validate(dict(_MINIMAL_RULE))  # the accepted neighbour, first
    assert (rule.name, rule.pattern, rule.decision, rule.justification) == (
        "ls-read-only", ("ls",), "allow", "listing is read-only",
    )
    assert (rule.alternative, rule.host_executable, rule.match, rule.not_match) == (None, (), (), ())

    incomplete = {key: value for key, value in _MINIMAL_RULE.items() if key != missing}
    assert set(incomplete) == set(_MINIMAL_RULE) - {missing}
    error = _refusal(CommandPolicyRule, incomplete)
    assert (error["type"], error["loc"]) == ("missing", (missing,))


@pytest.mark.parametrize(
    "bad, good",
    [
        pytest.param("Git-push.force_1", "git-push.force_1", id="upper"),
        pytest.param("git push.force_1", "git-push.force_1", id="space"),
        pytest.param("", "g", id="empty"),
        pytest.param("a" * 65, "a" * 64, id="sixty_five"),
        pytest.param("-git-push.force_1", "git-push.force_1", id="leading_dash"),
    ],
)
def test_rule_name_shape(bad: str, good: str) -> None:
    """A rule name is 1 to 64 of ``[a-z0-9_.-]`` starting with a letter or digit."""
    accepted = CommandPolicyRule.model_validate(_rule(good, ["git"], "allow"))  # neighbour, first
    assert accepted.name == good

    error = _refusal(CommandPolicyRule, _rule(bad, ["git"], "allow"))
    assert (error["type"], error["loc"]) == ("value_error", ("name",))
    assert "command policy rule name" in error["msg"]


def test_alternative_rules() -> None:
    """``forbid`` must name its alternative, ``allow`` has none, ``escalate`` may. Kills R1."""
    forbid = CommandPolicyRule.model_validate(_rule("deny-curl", ["curl"], "forbid"))
    assert forbid.alternative == "use the governed path"
    allow = CommandPolicyRule.model_validate(_rule("allow-ls", ["ls"], "allow"))
    assert allow.alternative is None
    escalate_with = CommandPolicyRule.model_validate(
        _rule("ask-push", ["git", "push"], "escalate", alternative="open a pull request")
    )
    assert escalate_with.alternative == "open a pull request"
    escalate_without = CommandPolicyRule.model_validate(_rule("ask-push", ["git", "push"], "escalate"))
    assert escalate_without.alternative is None

    without = {key: value for key, value in _rule("deny-curl", ["curl"], "forbid").items() if key != "alternative"}
    assert "alternative" not in without
    message = _value_error(CommandPolicyRule, without)
    assert "a forbid rule must name its alternative" in message
    assert "command policy rule 'deny-curl'" in message
    # What YAML's empty ``alternative:`` arrives as, and an alternative that names nothing.
    assert "a forbid rule must name its alternative" in _value_error(
        CommandPolicyRule, _rule("deny-curl", ["curl"], "forbid", alternative=None)
    )
    blank_alternative = _value_error(CommandPolicyRule, _rule("deny-curl", ["curl"], "forbid", alternative="  "))
    assert "alternative must not be blank" in blank_alternative

    message = _value_error(CommandPolicyRule, _rule("allow-ls", ["ls"], "allow", alternative="use cat"))
    assert "an allow rule has no alternative" in message
    assert "command policy rule 'allow-ls'" in message

    message = _value_error(CommandPolicyRule, _rule("allow-ls", ["ls"], "allow", justification="   "))
    assert "justification must not be blank" in message
    assert "command policy rule 'allow-ls'" in message


_ACCEPTED_PATTERNS: list[tuple[list[Any], tuple[Any, ...]]] = [
    (_positions(32), _as_tuples(_positions(32))),
    (["git", ["push", "fetch"]], ("git", ("push", "fetch"))),
    ([["git", "hg"], "push", ["--force", "-f"]], (("git", "hg"), "push", ("--force", "-f"))),
]


@pytest.mark.parametrize(
    "bad, good, phrase",
    [
        pytest.param([], ["git"], "pattern must have 1 to 32 positions", id="empty"),
        pytest.param(_positions(33), _positions(32), "pattern must have 1 to 32 positions", id="thirty_three"),
        pytest.param(
            ["git", ""], ["git", "push"], "has an empty, over-long or control-character word", id="empty_word"
        ),
        pytest.param(
            ["git", []], ["git", ["push"]], "must list 1 to 32 distinct words", id="empty_alternatives"
        ),
        pytest.param(
            ["git", ["push", "push"]],
            ["git", ["push", "fetch"]],
            "must list 1 to 32 distinct words",
            id="duplicate_alternative",
        ),
        pytest.param(["/usr/bin/git", "push"], ["git", "push"], "must be a bare name", id="program_slash"),
        pytest.param([r"bin\git", "push"], ["git", "push"], "must be a bare name", id="program_backslash"),
        pytest.param(["git push"], ["git", "push"], "must be a bare name", id="program_space"),
        pytest.param(
            ["git", "pu\nsh"],
            ["git", "push"],
            "has an empty, over-long or control-character word",
            id="control_character",
        ),
    ],
)
def test_pattern_bounds(bad: list[Any], good: list[Any], phrase: str) -> None:
    """A pattern has 1 to 32 positions of 1 to 32 distinct words; the program is a bare name."""
    for accepted_raw, expected in _ACCEPTED_PATTERNS:
        # 32 positions; alternatives at position 0 and at position 2; lists arrive as tuples.
        assert CommandPolicyRule.model_validate(_rule("git-push", accepted_raw, "escalate")).pattern == expected
    assert CommandPolicyRule.model_validate(_rule("git-push", good, "escalate")).pattern == _as_tuples(good)

    message = _value_error(CommandPolicyRule, _rule("git-push", bad, "escalate"))
    assert phrase in message
    assert "command policy rule 'git-push'" in message


_PIN_POSIX = "/usr/bin/git"
_PIN_DRIVE = r"C:\Program Files\Git\cmd\git.exe"
_PIN_UNC = r"\\server\share\git.exe"


def _pinned(pins: list[str], decision: str = "allow", pattern: list[Any] | None = None) -> dict[str, Any]:
    return _rule("git-status", ["git", "status"] if pattern is None else pattern, decision, host_executable=pins)


@pytest.mark.parametrize(
    "bad, good, phrase",
    [
        pytest.param(_pinned(["bin/git"]), _pinned([_PIN_POSIX]), "is not an absolute path", id="relative"),
        pytest.param(
            _pinned([_PIN_POSIX], "forbid"), _pinned([_PIN_POSIX]), "pins an allow rule only", id="on_forbid"
        ),
        pytest.param(
            _pinned([_PIN_POSIX], "escalate"), _pinned([_PIN_POSIX]), "pins an allow rule only", id="on_escalate"
        ),
        pytest.param(
            _pinned([_PIN_POSIX], pattern=[["git", "hg"], "status"]),
            _pinned([_PIN_POSIX]),
            "names one program, not alternatives",
            id="alternatives_program",
        ),
        pytest.param(
            _pinned(["/usr/bin/hg"]), _pinned([_PIN_POSIX]), "does not name the program", id="basename_mismatch"
        ),
        pytest.param(
            _pinned([_PIN_POSIX, _PIN_POSIX]),
            _pinned([_PIN_POSIX, _PIN_UNC]),
            "at most 16 distinct paths",
            id="duplicate",
        ),
    ],
)
def test_host_executable_rules(bad: dict[str, Any], good: dict[str, Any], phrase: str) -> None:
    """``host_executable`` pins an ``allow`` rule's one program to absolute paths. Kills R3, R4."""
    for pin in (_PIN_POSIX, _PIN_DRIVE, _PIN_UNC):  # a POSIX, a drive and a UNC path are all accepted
        accepted = CommandPolicyRule.model_validate(_pinned([pin]))
        assert accepted.pattern == ("git", "status")
        assert accepted.host_executable == (pin,)
    assert CommandPolicyRule.model_validate(good).host_executable == tuple(good["host_executable"])

    message = _value_error(CommandPolicyRule, bad)
    assert phrase in message
    assert "command policy rule 'git-status'" in message


def _pin_of_length(length: int, program: str = "git") -> str:
    """An absolute POSIX pin of exactly ``length`` characters whose basename is ``program``."""
    tail = f"/{program}"
    path = "/" + "d" * (length - 1 - len(tail)) + tail
    assert len(path) == length
    return path


_LONG_PIN = 1024  # _MAX_PINNED_PATH_CHARS
_LONG_WORD = 256  # _MAX_TOKEN_CHARS
_LONG_PROSE = 500  # _MAX_RULE_PROSE_CHARS
_WORD_PHRASE = "has an empty, over-long or control-character word"


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda word: [word, "push"], id="program_position"),
        pytest.param(lambda word: ["git", word], id="plain_word"),
        pytest.param(lambda word: ["git", [word, "other"]], id="alternative_word"),
    ],
)
def test_pattern_word_length_bounds(build: Callable[[str], list[Any]]) -> None:
    """A pattern word is at most 256 characters: exactly 256 is accepted, 257 is refused."""
    accepted = CommandPolicyRule.model_validate(_rule("git-push", build("w" * _LONG_WORD), "escalate"))
    assert accepted.pattern == _as_tuples(build("w" * _LONG_WORD))  # the premise: 256 is valid

    message = _value_error(CommandPolicyRule, _rule("git-push", build("w" * (_LONG_WORD + 1)), "escalate"))
    assert _WORD_PHRASE in message
    assert "command policy rule 'git-push'" in message


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda words: [words, "push"], id="program_position"),
        pytest.param(lambda words: ["git", words], id="later_position"),
    ],
)
def test_pattern_alternative_count_bounds(build: Callable[[list[str]], list[Any]]) -> None:
    """A position lists at most 32 distinct words: exactly 32 is accepted, 33 is refused."""
    thirty_two = [f"a{index}" for index in range(32)]
    accepted = CommandPolicyRule.model_validate(_rule("git-push", build(thirty_two), "escalate"))
    assert accepted.pattern == _as_tuples(build(thirty_two))  # the premise: 32 is valid

    message = _value_error(CommandPolicyRule, _rule("git-push", build([*thirty_two, "a32"]), "escalate"))
    assert "must list 1 to 32 distinct words" in message
    assert "command policy rule 'git-push'" in message


@pytest.mark.parametrize("field", ["justification", "alternative"])
def test_rule_prose_length_bounds(field: str) -> None:
    """``justification`` and ``alternative`` are at most 500 characters: 500 is accepted, 501 is refused."""
    accepted = CommandPolicyRule.model_validate(
        _rule("deny-curl", ["curl"], "forbid", **{field: "p" * _LONG_PROSE})
    )
    assert getattr(accepted, field) == "p" * _LONG_PROSE  # the premise: 500 is valid

    message = _value_error(
        CommandPolicyRule, _rule("deny-curl", ["curl"], "forbid", **{field: "p" * (_LONG_PROSE + 1)})
    )
    assert f"{field} is longer than 500 characters" in message
    assert "command policy rule 'deny-curl'" in message


@pytest.mark.parametrize("field", ["justification", "alternative"])
def test_rule_prose_control_character_bounds(field: str) -> None:
    """A control character in prose is refused even though a newline is not an example's problem."""
    accepted = CommandPolicyRule.model_validate(_rule("deny-curl", ["curl"], "forbid", **{field: "use it"}))
    assert getattr(accepted, field) == "use it"

    message = _value_error(CommandPolicyRule, _rule("deny-curl", ["curl"], "forbid", **{field: "use\nit"}))
    assert f"{field} contains a control character" in message
    assert "command policy rule 'deny-curl'" in message


def test_pin_path_length_bounds() -> None:
    """A pinned path is at most 1,024 characters: exactly 1,024 is accepted, 1,025 is refused."""
    pin = _pin_of_length(_LONG_PIN)
    assert CommandPolicyRule.model_validate(_pinned([pin])).host_executable == (pin,)  # the premise

    message = _value_error(CommandPolicyRule, _pinned([_pin_of_length(_LONG_PIN + 1)]))
    assert "is not an absolute path" in message
    assert "command policy rule 'git-status'" in message


@pytest.mark.parametrize(
    "character",
    [
        pytest.param("\x00", id="nul"),
        pytest.param("\n", id="newline"),
        pytest.param("\t", id="tab"),
        pytest.param("\x1f", id="unit_separator"),
        pytest.param("\x7f", id="delete"),
    ],
)
def test_pin_control_character_bounds(character: str) -> None:
    """A control character anywhere in a pinned path refuses it; a space and a printable character do not."""
    for allowed in ("/usr/my bin/git", "/usr/~bin/git"):
        assert CommandPolicyRule.model_validate(_pinned([allowed])).host_executable == (allowed,)  # premise

    message = _value_error(CommandPolicyRule, _pinned([f"/usr/bin{character}x/git"]))
    assert "is not an absolute path" in message
    assert "command policy rule 'git-status'" in message


@pytest.mark.parametrize(
    "character",
    [
        pytest.param("\x00", id="nul"),
        pytest.param("\x1f", id="unit_separator"),
        pytest.param("\x7f", id="delete"),
    ],
)
def test_pattern_word_control_character_bounds(character: str) -> None:
    """A control character inside a pattern word is refused; a space inside a later word is not."""
    assert CommandPolicyRule.model_validate(_rule("git-push", ["git", "a b"], "escalate")).pattern == ("git", "a b")

    message = _value_error(CommandPolicyRule, _rule("git-push", ["git", f"a{character}b"], "escalate"))
    assert _WORD_PHRASE in message
    assert "command policy rule 'git-push'" in message


def test_pin_count_bounds() -> None:
    """A rule pins at most 16 distinct paths: exactly 16 is accepted, 17 distinct paths are refused."""
    sixteen = [f"/p{index}/git" for index in range(16)]
    assert CommandPolicyRule.model_validate(_pinned(sixteen)).host_executable == tuple(sixteen)  # the premise

    message = _value_error(CommandPolicyRule, _pinned([*sixteen, "/p16/git"]))
    assert "at most 16 distinct paths" in message
    assert "command policy rule 'git-status'" in message


_EXAMPLE_CASES: list[Any] = [
    pytest.param(
        lambda kind: ({kind: ["  \t "]}, {kind: ["git status"]}, f"{kind} example must not be blank"),
        id="blank",
    ),
    pytest.param(
        lambda kind: (
            {kind: ["g" * 1025]},
            {kind: ["g" * 1024]},
            f"{kind} example is longer than 1024 characters",
        ),
        id="over_1024",
    ),
    pytest.param(
        lambda kind: (
            {kind: ["git\x00status"]},
            {kind: ["git status\n\tgit log"]},  # a newline and a tab are allowed in an example
            f"{kind} example contains a control character",
        ),
        id="nul",
    ),
    pytest.param(
        lambda kind: (
            {"match": ["git status"], "not_match": ["git status"]},
            {"match": ["git status"], "not_match": ["git push"]},
            "is both a match and a not_match example",
        ),
        id="both_lists",
    ),
    pytest.param(
        lambda kind: (
            {kind: [f"git status {index}" for index in range(33)]},
            {kind: [f"git status {index}" for index in range(32)]},
            f"at most 32 {kind} examples",
        ),
        id="thirty_three",
    ),
]


@pytest.mark.parametrize("case", _EXAMPLE_CASES)
def test_example_bounds(case: Callable[[str], tuple[dict[str, Any], dict[str, Any], str]]) -> None:
    """``match`` and ``not_match`` examples are non-blank, at most 1,024 characters, at most 32 each."""
    for kind in ("match", "not_match"):
        bad, good, phrase = case(kind)
        accepted = CommandPolicyRule.model_validate(_rule("git-status", ["git", "status"], "allow", **good))
        for field, examples in good.items():
            assert getattr(accepted, field) == tuple(examples)

        message = _value_error(CommandPolicyRule, _rule("git-status", ["git", "status"], "allow", **bad))
        assert phrase in message
        assert "command policy rule 'git-status'" in message


# ---------------------------------------------------------------------------
# M1 #7-10: the config
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    """No rules, no ``unmatched_decision``, ``unparseable_decision`` escalate, limits 8192/32/3."""
    config = CommandPolicyConfig()
    assert config.rules == ()
    assert config.unmatched_decision is None
    assert config.unparseable_decision == "escalate"
    assert (config.max_command_chars, config.max_segments, config.max_nesting) == (8192, 32, 3)
    # Valid: it validates again from {} and from its own dump, and it is not just any config.
    assert CommandPolicyConfig.model_validate({}) == config
    assert CommandPolicyConfig.model_validate(config.model_dump()) == config
    tuned = CommandPolicyConfig.model_validate({"max_nesting": 0})
    assert tuned != config and tuned.max_nesting == 0


_LS = _rule("allow-ls", ["ls"], "allow")


@pytest.mark.parametrize(
    "bad, goods, phrases",
    [
        pytest.param(
            _config(_LS),
            (_config(_LS, unmatched_decision="allow"),),
            ("declare unmatched_decision",),
            id="rules_without_unmatched",
        ),
        pytest.param(
            _config(_LS, unmatched_decision="allow", unparseable_decision="allow"),
            # the default unparseable_decision, and no rules at all: nothing to bypass
            (_config(_LS, unmatched_decision="allow"), _config(unparseable_decision="allow")),
            ("may not be allow",),
            id="unparseable_allow",
        ),
        pytest.param(
            _config(_LS, unmatched_decision="forbid", unparseable_decision="escalate"),
            (_config(_LS, unmatched_decision="forbid", unparseable_decision="forbid"),),
            ("at least as strict",),
            id="unparseable_looser_than_unmatched",
        ),
        pytest.param(
            _config(_LS, _rule("allow-ls", ["cat"], "allow"), unmatched_decision="allow"),
            (_config(_LS, _rule("allow-cat", ["cat"], "allow"), unmatched_decision="allow"),),
            ("declared twice", "'allow-ls'"),  # the message names the repeated rule
            id="duplicate_names",
        ),
        pytest.param(
            _config(*_many_rules(257), unmatched_decision="allow"),
            (_config(*_many_rules(256), unmatched_decision="allow"),),
            ("at most 256 rules",),
            id="two_hundred_fifty_seven",
        ),
    ],
)
def test_config_cross_field_rules(
    bad: dict[str, Any], goods: tuple[dict[str, Any], ...], phrases: tuple[str, ...]
) -> None:
    """Rules need ``unmatched_decision``; an unreadable line may not be allowed or looser. Kills R2, R5, R6, R7."""
    for good in goods:
        accepted = CommandPolicyConfig.model_validate(good)  # the accepted neighbours, first
        assert len(accepted.rules) == len(good["rules"])

    message = _value_error(CommandPolicyConfig, bad)
    for phrase in phrases:
        assert phrase in message


@pytest.mark.parametrize(
    "field, below, low, high, above",
    [
        pytest.param("max_command_chars", 63, 64, 65536, 65537, id="max_command_chars"),
        pytest.param("max_segments", 0, 1, 256, 257, id="max_segments"),
        pytest.param("max_nesting", -1, 0, 8, 9, id="max_nesting"),
    ],
)
def test_limit_bounds(field: str, below: int, low: int, high: int, above: int) -> None:
    """Each limit accepts its two ends and refuses the value just outside either end."""
    for edge in (low, high):
        assert getattr(CommandPolicyConfig.model_validate({field: edge}), field) == edge

    for outside, kind in ((below, "greater_than_equal"), (above, "less_than_equal")):
        error = _refusal(CommandPolicyConfig, {field: outside})
        assert (error["type"], error["loc"]) == (kind, (field,))


def test_models_are_frozen_and_closed() -> None:
    """Both models refuse an unknown field; a built rule or config cannot be assigned to."""
    rule_raw = _rule("allow-ls", ["ls"], "allow")
    config_raw = _config(rule_raw, unmatched_decision="allow")
    rule = CommandPolicyRule.model_validate(rule_raw)  # the accepted neighbours, first
    config = CommandPolicyConfig.model_validate(config_raw)

    for model, raw in (
        (CommandPolicyRule, {**rule_raw, "bogus": 1}),
        (CommandPolicyConfig, {**config_raw, "bogus": 1}),
    ):
        error = _refusal(model, raw)
        assert (error["type"], error["loc"]) == ("extra_forbidden", ("bogus",))

    with pytest.raises(ValidationError) as excinfo:
        rule.decision = "forbid"  # type: ignore[misc]
    frozen = [(error["type"], error["loc"]) for error in excinfo.value.errors()]
    assert frozen == [("frozen_instance", ("decision",))]
    assert rule.decision == "allow"
    with pytest.raises(ValidationError) as excinfo:
        config.max_segments = 5  # type: ignore[misc]
    frozen = [(error["type"], error["loc"]) for error in excinfo.value.errors()]
    assert frozen == [("frozen_instance", ("max_segments",))]
    assert config.max_segments == 32


# ---------------------------------------------------------------------------
# M1 #11-12: the policy digest
# ---------------------------------------------------------------------------


def _policy_dict() -> dict[str, Any]:
    """A fresh, non-trivial policy: all three decisions, a pin, alternatives, both example lists."""
    return {
        "rules": [
            {
                "name": "allow-git-status",
                "pattern": ["git", "status"],
                "decision": "allow",
                "justification": "status only reads the repository",
                "host_executable": [_PIN_POSIX, _PIN_DRIVE],
                "match": ["git status"],
                "not_match": ["git push"],
            },
            {
                "name": "ask-git-push",
                "pattern": ["git", "push"],
                "decision": "escalate",
                "justification": "a push publishes work",
            },
            {
                "name": "deny-fetchers",
                "pattern": [["curl", "wget"]],
                "decision": "forbid",
                "justification": "downloads go through the governed fetch tool",
                "alternative": "use the governed fetch tool",
            },
        ],
        "unmatched_decision": "allow",
    }


def test_policy_digest_known_answer() -> None:
    """The digest is sha256 over a versioned domain tag and the RFC 8785 JSON of the policy. Kills E31."""
    config = CommandPolicyConfig.model_validate(_policy_dict())
    assert len(config.rules) == 3  # the premise: a policy with rules, pins and examples, not the empty one
    body = canonicalize(config.model_dump(mode="json"))
    expected = hashlib.sha256(b"probos.command_policy/policy/v1\x00" + body).hexdigest()
    other_version = hashlib.sha256(b"probos.command_policy/policy/v2\x00" + body).hexdigest()

    assert other_version != expected  # the negative control: the domain tag is part of the preimage
    assert POLICY_DIGEST_SCHEME == "probos.command_policy/policy/v1"
    assert policy_digest(config) == expected
    assert policy_digest(config) != other_version


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda raw: raw["rules"][2].update(justification="a different reason"), id="justification"),
        pytest.param(lambda raw: raw["rules"][1].update(decision="allow"), id="decision"),
        pytest.param(lambda raw: raw["rules"].reverse(), id="rule_order"),
        pytest.param(lambda raw: raw.update(unmatched_decision="escalate"), id="unmatched"),
        pytest.param(lambda raw: raw["rules"][0]["match"].append("git status --short"), id="example"),
    ],
)
def test_policy_digest_tracks_every_change(change: Callable[[dict[str, Any]], object]) -> None:
    """Equal dicts give equal digests; any single change to the policy gives a different one."""
    first = policy_digest(CommandPolicyConfig.model_validate(_policy_dict()))
    second = policy_digest(CommandPolicyConfig.model_validate(_policy_dict()))
    assert first == second  # the accepted neighbour: building twice from equal dicts is stable

    changed_raw = _policy_dict()
    change(changed_raw)
    assert changed_raw != _policy_dict()  # the premise: the change really changed the dict
    assert policy_digest(CommandPolicyConfig.model_validate(changed_raw)) != first


# ---------------------------------------------------------------------------
# M1 #13-14: the config surface and the program stem
# ---------------------------------------------------------------------------

_S1_NAMES = ("CommandPolicyConfig", "CommandPolicyRule", "windows_program_stem")


def test_s1_models_are_off_the_config_surface() -> None:
    """S1 neither attaches nor re-exports its models (D2). S2 changes this deliberately (O-S1-1)."""
    for name in _S1_NAMES:  # controls: the names exist where S1 put them ...
        assert hasattr(operations, name)
    assert hasattr(config_facade, "ExecutionConfig")  # ... and these are the surfaces that list a re-export
    assert "ExecutionConfig" in config_package.__all__
    assert "enabled" in ExecutionConfig.model_fields

    for name in _S1_NAMES:
        assert not hasattr(config_facade, name), name
        assert name not in config_package.__all__, name
    assert "command_policy" not in ExecutionConfig.model_fields


@pytest.mark.parametrize(
    "program, expected",
    [
        pytest.param(r"C:\Git\GIT.EXE", "git", id="drive_path_upper_exe"),
        pytest.param("/usr/bin/git", "git", id="posix_path"),
        pytest.param("x.cmd", "x", id="cmd_suffix"),
        pytest.param(".exe", ".exe", id="suffix_only_is_kept"),
        pytest.param("python3.12", "python3.12", id="version_dot_is_not_a_suffix"),
        pytest.param("Tool.Bat", "tool", id="mixed_case_bat"),
    ],
)
def test_windows_program_stem(program: str, expected: str) -> None:
    """The basename, lower-cased, without one of ``.exe .com .bat .cmd`` unless that is the whole name."""
    assert windows_program_stem("a.exe") == "a"  # the neighbour: the suffix rule is live
    assert windows_program_stem(program) == expected


# ---------------------------------------------------------------------------
# R-M1 (repair round 1, finding 12): text the policy digest cannot encode is refused at ingress
# ---------------------------------------------------------------------------

_UNICODE_RULE = "unicode-text"
_LONE_SURROGATE = "\ud800"  # U+D800 with no low surrogate after it: not valid Unicode text; written as an escape
_VALID_UNICODE_TEXT = ("\u00e9", "\u65e5\u672c")  # e-acute and two CJK ideographs: non-ASCII, and valid Unicode

# One case per text field the models check. Each builder puts ``text`` inside otherwise valid words, so a lone
# surrogate is the only thing wrong with the refused rule; the second value names the field in the message.
_UNICODE_FIELD_CASES: list[Any] = [
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["curl"], "forbid", justification=f"a {text} download"),
        "justification",
        id="justification",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["curl"], "forbid", alternative=f"use the {text} fetch tool"),
        "alternative",
        id="alternative",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, [f"cu{text}rl"], "escalate"),
        "pattern position 0",
        id="pattern_program",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["git", f"pu{text}sh"], "escalate"),
        "pattern position 1",
        id="pattern_word",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["git", ["status", f"lo{text}g"]], "escalate"),
        "pattern position 1",
        id="pattern_alternative",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["git"], "allow", host_executable=[f"/usr/b{text}in/git"]),
        "a host_executable path",
        id="pin",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["git", "status"], "allow", match=[f"git status {text} --short"]),
        "match example",
        id="match",
    ),
    pytest.param(
        lambda text: _rule(_UNICODE_RULE, ["git", "status"], "allow", not_match=[f"git push {text} origin"]),
        "not_match example",
        id="not_match",
    ),
]


@pytest.mark.parametrize("build, locator", _UNICODE_FIELD_CASES)
def test_lone_surrogates_are_refused_at_ingress(build: Callable[[str], dict[str, Any]], locator: str) -> None:
    """A lone surrogate in any text field is refused when the policy is read. Kills R8.

    The RFC 8785 digest cannot encode a lone surrogate, so a policy that carried one would load and then fail
    every ``policy_digest`` call. The same field holding valid non-ASCII text is accepted and digests.
    """
    digests = []
    for text in _VALID_UNICODE_TEXT:  # the accepted neighbours, first: the same field, valid non-ASCII text
        config = CommandPolicyConfig.model_validate(_config(build(text), unmatched_decision="allow"))
        assert [rule.name for rule in config.rules] == [_UNICODE_RULE]  # the premise: a policy with a rule in it
        digest = policy_digest(config)
        assert re.fullmatch("[0-9a-f]{64}", digest), digest
        digests.append(digest)
    assert digests[0] != digests[1]  # the text reaches the digest, so the field really held what the builder put in

    error = _refusal(CommandPolicyConfig, _config(build(_LONE_SURROGATE), unmatched_decision="allow"))
    assert (error["type"], error["loc"]) == ("value_error", ("rules", 0))  # the rule's own validator refused it
    message = str(error["msg"])  # the validator's message: str(exc) would echo the input, the rule's name included
    assert "not valid Unicode" in message
    assert f"command policy rule {_UNICODE_RULE!r}: {locator} " in message


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
