"""Token provenance shared by live loops and durable crew execution readers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from probos.crew_utils import CREW_EXECUTION_KEYS

TokenSource = Literal["measured", "estimated", "mixed"]
TOKEN_SOURCE_MEASURED: TokenSource = "measured"
TOKEN_SOURCE_ESTIMATED: TokenSource = "estimated"
TOKEN_SOURCE_MIXED: TokenSource = "mixed"
CREW_EXECUTION_TOKEN_USAGE_KEY = "crew_execution_token_usage"
_USAGE_KEYS = frozenset({"version", "tokens_used", "token_source"})
_MAX_TOKENS = 2**63 - 1


@dataclass(frozen=True)
class CrewExecutionTokenUsage:
    tokens_used: int
    token_source: TokenSource
    version: Literal[1] = 1


def _source(value: object) -> TokenSource:
    if type(value) is str:
        if value == TOKEN_SOURCE_MEASURED:
            return TOKEN_SOURCE_MEASURED
        if value == TOKEN_SOURCE_ESTIMATED:
            return TOKEN_SOURCE_ESTIMATED
        if value == TOKEN_SOURCE_MIXED:
            return TOKEN_SOURCE_MIXED
    raise ValueError("crew_execution_token_usage_invalid")


def merge_token_sources(sources: Iterable[str]) -> TokenSource:
    """BF-680 provenance union; an empty prefix contains no estimate."""
    values = {_source(source) for source in sources}
    if TOKEN_SOURCE_MIXED in values or {
        TOKEN_SOURCE_MEASURED, TOKEN_SOURCE_ESTIMATED,
    }.issubset(values):
        return TOKEN_SOURCE_MIXED
    if TOKEN_SOURCE_ESTIMATED in values:
        return TOKEN_SOURCE_ESTIMATED
    return TOKEN_SOURCE_MEASURED


def _execution_tokens(execution: object) -> int:
    if (
        not isinstance(execution, Mapping)
        or set(execution) != CREW_EXECUTION_KEYS
        or type(execution["version"]) is not int
        or execution["version"] != 1
        or type(execution["tokens_used"]) is not int
        or not 0 <= execution["tokens_used"] <= _MAX_TOKENS
    ):
        raise ValueError("crew_execution_token_usage_invalid")
    return execution["tokens_used"]


def build_crew_execution_token_usage(
    *, execution: Mapping[str, Any], token_source: str,
) -> dict[str, Any]:
    """Qualify the original execution count, never verification-inclusive spend."""
    return {
        "version": 1,
        "tokens_used": _execution_tokens(execution),
        "token_source": _source(token_source),
    }


def read_crew_execution_token_usage(
    metadata: Mapping[str, Any],
) -> CrewExecutionTokenUsage | None:
    """Absent means unknown; any present invalid or orphaned sibling fails closed."""
    if not isinstance(metadata, Mapping):
        raise ValueError("crew_execution_token_usage_invalid")
    if CREW_EXECUTION_TOKEN_USAGE_KEY not in metadata:
        return None
    usage = metadata[CREW_EXECUTION_TOKEN_USAGE_KEY]
    if (
        type(usage) is not dict
        or set(usage) != _USAGE_KEYS
        or type(usage["version"]) is not int
        or usage["version"] != 1
        or type(usage["tokens_used"]) is not int
        or usage["tokens_used"] != _execution_tokens(metadata.get("crew_execution"))
    ):
        raise ValueError("crew_execution_token_usage_invalid")
    return CrewExecutionTokenUsage(
        tokens_used=usage["tokens_used"], token_source=_source(usage["token_source"]),
    )
