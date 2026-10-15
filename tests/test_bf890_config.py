"""BF-890 (#1529): parse-time validation of ``execution.command_env_passthrough``.

``ExecutionConfig`` refuses, when the config loads, an operator-declared
environment variable name that is not a plain identifier, that starts with
``PROBOS_``, or that is shaped like a credential (a credential WORD anywhere in
the name, or a credential SEGMENT as a whole ``_``-separated part). The
validator sits in ``probos.config_models.operations``, which may not import
``probos``, so it carries literal twins of the rule that
``probos.execution.command_env`` owns.

Each refusal test asserts its own premise first (which single rule can refuse
the name), then the refusal, then an accepted neighbour as the negative
control. ``test_validator_agrees_with_the_owner_rule`` crosses the seam between
the twin and its owner on behaviour; the constants themselves are compared in
``tests/test_bf890_command_env.py``.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from pydantic import ValidationError

from probos.config import ExecutionConfig, SystemConfig
from probos.config_models import operations
from probos.execution import command_env

_FIELD = "command_env_passthrough"
_DOTTED_FIELD = "execution.command_env_passthrough"
_NOTHING_TRIPPED = {"prefix": False, "word": False, "segment": False}


def _rules_tripped(name: str) -> dict[str, bool]:
    """Which of the validator's three credential rules *name* trips, read from its own twins."""
    upper = name.upper()
    return {
        "prefix": upper.startswith(operations._RUNTIME_ENV_NAME_PREFIX),
        "word": any(word in upper for word in operations._CREDENTIAL_ENV_NAME_WORDS),
        "segment": any(
            part in operations._CREDENTIAL_ENV_NAME_SEGMENTS for part in upper.split("_")
        ),
    }


def _is_plain_shape(name: str) -> bool:
    return re.fullmatch(operations._ENV_NAME_SHAPE_PATTERN, name) is not None


def _assert_plain_and_untripped(name: str) -> None:
    """Premise for an accepted neighbour: a plain name that trips none of the credential rules."""
    assert _is_plain_shape(name)
    assert _rules_tripped(name) == _NOTHING_TRIPPED


def _refusal(names: list[str]) -> dict[str, Any]:
    """The first error ExecutionConfig reports for *names*; fails the test if it accepts them."""
    with pytest.raises(ValidationError) as excinfo:
        ExecutionConfig(command_env_passthrough=names)
    first = excinfo.value.errors()[0]
    assert first["loc"][0] == _FIELD
    assert first["type"] == "value_error"
    return first


def _load(names: list[str]) -> list[str] | None:
    """What ExecutionConfig keeps for *names*, or None when it refuses them at load."""
    try:
        config = ExecutionConfig(command_env_passthrough=names)
    except ValidationError as exc:
        assert exc.errors()[0]["loc"][0] == _FIELD
        return None
    return config.command_env_passthrough


def test_default_is_empty() -> None:
    # Premise: the field is declared on ExecutionConfig, and SystemConfig carries one.
    assert _FIELD in ExecutionConfig.model_fields
    assert isinstance(SystemConfig().execution, ExecutionConfig)

    assert ExecutionConfig().command_env_passthrough == []
    assert SystemConfig().execution.command_env_passthrough == []


def test_declared_names_are_trimmed_and_deduplicated() -> None:
    declared = [" FOO_HOME ", "FOO_HOME", "BAR"]
    # Premise: both distinct names are plain on their own, and the padded form is not a
    # plain name until it is trimmed, so only trimming lets it through to be deduplicated.
    assert command_env.env_name_refusal("FOO_HOME") is None
    assert command_env.env_name_refusal("BAR") is None
    assert command_env.env_name_refusal(declared[0]) == "unknown_shape"

    kept = ExecutionConfig(command_env_passthrough=declared).command_env_passthrough

    assert kept == ["FOO_HOME", "BAR"]

    # Control: distinct names are all kept, in the order given (not sorted, none dropped).
    distinct = ["JAVA_HOME", "BAR", "FOO_HOME"]
    assert ExecutionConfig(command_env_passthrough=distinct).command_env_passthrough == distinct


_WORD_CASES: list[tuple[str, str]] = [
    ("OPENAI_API_KEY", "OPENAI_API_BASE"),
    ("GH_TOKEN", "GH_HOST"),
    ("CLIENT_SECRET", "CLIENT_ID"),
    ("DB_PASSWORD", "DB_HOST"),
]


@pytest.mark.parametrize(
    "name, neighbour", _WORD_CASES, ids=[name for name, _ in _WORD_CASES]
)
def test_credential_word_name_is_refused_at_load(name: str, neighbour: str) -> None:
    # Premise: only the credential-WORD rule can refuse this name. No whole segment from
    # the segment list, no PROBOS_ prefix, so it carries a word and nothing else.
    assert _rules_tripped(name) == {"prefix": False, "word": True, "segment": False}
    assert not any(
        part in operations._CREDENTIAL_ENV_NAME_SEGMENTS for part in name.upper().split("_")
    )
    # Premise: the neighbour differs only by the word and trips nothing.
    _assert_plain_and_untripped(neighbour)

    _refusal([name])

    # Control: the accepted neighbour is kept as given.
    assert _load([neighbour]) == [neighbour]


_SEGMENT_CASES: list[tuple[str, str]] = [
    ("GH_PAT", "GH_PATH"),
    ("DB_PASS", "DB_HOST"),
    ("MYSQL_PWD", "MYSQL_HOME"),
    ("SENTRY_DSN", "SENTRY_ORG"),
]


@pytest.mark.parametrize(
    "name, neighbour", _SEGMENT_CASES, ids=[name for name, _ in _SEGMENT_CASES]
)
def test_credential_segment_name_is_refused_at_load(name: str, neighbour: str) -> None:
    # Premise: only the credential-SEGMENT rule can refuse this name. No credential word
    # anywhere in it, no PROBOS_ prefix.
    assert _rules_tripped(name) == {"prefix": False, "word": False, "segment": True}
    assert not any(word in name.upper() for word in operations._CREDENTIAL_ENV_NAME_WORDS)
    # Premise: the neighbour trips nothing. GH_PATH is the sharp one: PAT counts only as a
    # whole segment, so PATH is not caught by it.
    _assert_plain_and_untripped(neighbour)

    _refusal([name])

    # Control: the accepted neighbour is kept as given.
    assert _load([neighbour]) == [neighbour]


_PREFIX_CASES: list[tuple[str, str]] = [
    ("PROBOS_DATA_DIR", "DATA_DIR"),
    ("PROBOS_LLM_URL", "LLM_URL"),
]


@pytest.mark.parametrize(
    "name, neighbour", _PREFIX_CASES, ids=[name for name, _ in _PREFIX_CASES]
)
def test_runtime_prefix_is_refused_at_load(name: str, neighbour: str) -> None:
    # Premise: only the PROBOS_ prefix can refuse this name: no credential word, no
    # credential segment.
    assert _rules_tripped(name) == {"prefix": True, "word": False, "segment": False}
    # Premise: the neighbour is the same name without the prefix and trips nothing.
    assert name == operations._RUNTIME_ENV_NAME_PREFIX + neighbour
    _assert_plain_and_untripped(neighbour)

    _refusal([name])

    # Control: the accepted neighbour is kept as given.
    assert _load([neighbour]) == [neighbour]


_SHAPE_CASES: list[tuple[str, str, str]] = [
    ("empty", "", "A"),
    ("inner-space", "A B", "A_B"),
    ("equals-sign", "X=Y", "X_Y"),
    ("leading-digit", "1ABC", "_1ABC"),
]


@pytest.mark.parametrize(
    "name, neighbour",
    [(name, neighbour) for _, name, neighbour in _SHAPE_CASES],
    ids=[label for label, _, _ in _SHAPE_CASES],
)
def test_unknown_shape_is_refused_at_load(name: str, neighbour: str) -> None:
    # Premise: not a plain variable name, and it trips none of the credential rules, so
    # only the shape check can refuse it.
    assert not _is_plain_shape(name)
    assert _rules_tripped(name) == _NOTHING_TRIPPED
    # Premise: the neighbour is a plain name that trips nothing.
    _assert_plain_and_untripped(neighbour)

    _refusal([name])

    # Control: the accepted neighbour is kept as given.
    assert _load([neighbour]) == [neighbour]


# (id, name, the verdict command_env.env_name_refusal gives it). Every name is already
# trimmed. The sample mixes accepted names, each credential rule, the prefix and the shape.
_AGREEMENT_CASES: list[tuple[str, str, str | None]] = [
    ("plain-JAVA_HOME", "JAVA_HOME", None),
    ("plain-PATH-is-not-the-PAT-segment", "PATH", None),
    ("plain-leading-underscore", "_LEADING_UNDERSCORE", None),
    ("plain-lowercase", "lower_case_name", None),
    ("plain-PROBOS-without-underscore", "PROBOS", None),
    ("plain-PROBOS-not-at-the-start", "NOT_PROBOS_HOME", None),
    ("word-OPENAI_API_KEY", "OPENAI_API_KEY", "credential_shaped"),
    ("word-GH_TOKEN", "GH_TOKEN", "credential_shaped"),
    ("word-CLIENT_SECRET", "CLIENT_SECRET", "credential_shaped"),
    ("word-DB_PASSWORD", "DB_PASSWORD", "credential_shaped"),
    ("word-lowercase-github_token", "github_token", "credential_shaped"),
    ("segment-GH_PAT", "GH_PAT", "credential_shaped"),
    ("segment-DB_PASS", "DB_PASS", "credential_shaped"),
    ("segment-MYSQL_PWD", "MYSQL_PWD", "credential_shaped"),
    ("segment-SENTRY_DSN", "SENTRY_DSN", "credential_shaped"),
    ("segment-AWS_CREDS", "AWS_CREDS", "credential_shaped"),
    ("prefix-PROBOS_DATA_DIR", "PROBOS_DATA_DIR", "credential_shaped"),
    ("prefix-lowercase-probos_llm_url", "probos_llm_url", "credential_shaped"),
    ("shape-empty", "", "unknown_shape"),
    ("shape-inner-space", "A B", "unknown_shape"),
    ("shape-equals-sign", "X=Y", "unknown_shape"),
    ("shape-leading-digit", "1ABC", "unknown_shape"),
    ("shape-non-ascii-letter", "\u00dcBER_HOME", "unknown_shape"),
]


@pytest.mark.parametrize(
    "name, owner_verdict",
    [(name, verdict) for _, name, verdict in _AGREEMENT_CASES],
    ids=[label for label, _, _ in _AGREEMENT_CASES],
)
def test_validator_agrees_with_the_owner_rule(name: str, owner_verdict: str | None) -> None:
    # Premise: the sample is already trimmed, so the owner rule (which does not trim)
    # judges the very string the validator judges after its own strip().
    assert name == name.strip()
    # Premise: the owner rule gives the verdict this sample was chosen to carry, so the
    # sample really does mix accepted names with every kind of refusal.
    assert command_env.env_name_refusal(name) == owner_verdict

    kept = _load([name])

    assert (kept is not None) == (command_env.env_name_refusal(name) is None)
    if kept is not None:
        assert kept == [name]


def test_system_config_loads_a_declared_name() -> None:
    # Premise: SystemConfig carries an ExecutionConfig under "execution", and JAVA_HOME is
    # a plain name that trips no credential rule.
    assert isinstance(SystemConfig().execution, ExecutionConfig)
    _assert_plain_and_untripped("JAVA_HOME")

    config = SystemConfig.model_validate(
        {"execution": {"command_env_passthrough": ["JAVA_HOME"]}}
    )

    assert config.execution.command_env_passthrough == ["JAVA_HOME"]

    # Control: the same path refuses a credential-shaped name, so the validator really is
    # reached from the system config, and the error is located under execution.
    assert _rules_tripped("GH_TOKEN") != _NOTHING_TRIPPED
    with pytest.raises(ValidationError) as excinfo:
        SystemConfig.model_validate(
            {"execution": {"command_env_passthrough": ["GH_TOKEN"]}}
        )
    assert excinfo.value.errors()[0]["loc"] == ("execution", _FIELD)


_MESSAGE_CASES: list[tuple[str, str, str]] = [
    ("shape", "A B", "A_B"),
    ("credential-word", "GH_TOKEN", "GH_HOST"),
    ("runtime-prefix", "PROBOS_DATA_DIR", "DATA_DIR"),
]


@pytest.mark.parametrize(
    "name, neighbour",
    [(name, neighbour) for _, name, neighbour in _MESSAGE_CASES],
    ids=[label for label, _, _ in _MESSAGE_CASES],
)
def test_refusal_message_names_the_field(name: str, neighbour: str) -> None:
    # Premise: the owner rule refuses the name and accepts the neighbour, so the refusal
    # under test is a real one and the neighbour a real accepted control.
    assert command_env.env_name_refusal(name) is not None
    assert command_env.env_name_refusal(neighbour) is None

    refusal = _refusal([name])

    assert _DOTTED_FIELD in refusal["msg"]

    # Control: the accepted neighbour raises nothing, so there is no message to confuse.
    assert _load([neighbour]) == [neighbour]
