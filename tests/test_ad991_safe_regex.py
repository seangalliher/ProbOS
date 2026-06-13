"""AD-991: ReDoS-safe supplied-pattern matching tests (pure, no mocks)."""
from __future__ import annotations

import re

import pytest

from probos.substrate.safe_regex import (
    DEFAULT_MAX_PATTERN_LEN,
    UnsafePatternError,
    safe_compile,
)


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


def test_normal_pattern_compiles_and_matches():
    pat = safe_compile(r"def \w+")
    assert pat.search("def recall_for_agent(self):")
    assert not pat.search("nothing here")


def test_flags_are_honored():
    pat = safe_compile(r"hello", flags=re.IGNORECASE)
    assert pat.search("HELLO world")


def test_returns_real_compiled_pattern():
    pat = safe_compile(r"[A-Z]+_SUSPEND")
    assert isinstance(pat, re.Pattern)
    assert pat.findall("PM_SUSPEND and CPU_SUSPEND") == ["PM_SUSPEND", "CPU_SUSPEND"]


# ---------------------------------------------------------------------------
# length cap
# ---------------------------------------------------------------------------


def test_over_length_pattern_rejected():
    long_pat = "a" * (DEFAULT_MAX_PATTERN_LEN + 1)
    with pytest.raises(UnsafePatternError, match="too long"):
        safe_compile(long_pat)


def test_custom_max_len_respected():
    with pytest.raises(UnsafePatternError, match="too long"):
        safe_compile("abcdef", max_len=3)


# ---------------------------------------------------------------------------
# catastrophic signatures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        r"(a+)+",
        r"(a+)+$",
        r"(a*)*",
        r"(a+)*",
        r"(a*)+",
        r"(.*)*",
        r"(\d+)+",
        r"(ab{2,})+",
    ],
)
def test_catastrophic_signatures_rejected(evil):
    with pytest.raises(UnsafePatternError, match="nested quantifier"):
        safe_compile(evil)


def test_benign_quantifiers_not_flagged():
    # A single quantifier on a group (NOT nested) is fine.
    assert safe_compile(r"(abc)+")
    assert safe_compile(r"(foo|bar)*")
    assert safe_compile(r"a+b+c+")


# ---------------------------------------------------------------------------
# invalid regex
# ---------------------------------------------------------------------------


def test_invalid_regex_raises_unsafe_not_re_error():
    with pytest.raises(UnsafePatternError, match="invalid regex"):
        safe_compile(r"(unclosed")


def test_invalid_regex_chains_the_cause():
    try:
        safe_compile(r"[z-a]")  # bad character range
    except UnsafePatternError as exc:
        assert exc.__cause__ is not None
        assert isinstance(exc.__cause__, re.error)
    else:  # pragma: no cover
        pytest.fail("expected UnsafePatternError")
