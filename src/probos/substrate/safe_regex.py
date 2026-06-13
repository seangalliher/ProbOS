"""AD-991: ReDoS-safe supplied-pattern matching.

Python's :mod:`re` is a backtracking engine, so a regex supplied by an agent or
the Captain (e.g. via the AD-989 ``search_content`` capability) is a latent ReDoS
(catastrophic-backtracking denial-of-service) vector: a pattern like ``(a+)+$``
against a long run of ``a`` characters can hang for seconds to minutes. ripgrep is
immune by construction (Rust's finite-automata regex runs in linear time); this
module absorbs the *intent* of that guarantee with a boundary guard.

``safe_compile`` rejects over-length patterns and the well-known catastrophic
signatures (nested quantifiers on a group) BEFORE compilation. This is
**defense-in-depth at the boundary** — a conservative heuristic that catches the
common ReDoS shapes, NOT a proof of linear-time execution. True linear-time safety
would require a finite-automata engine (``re2``); that is a forward marker /
optional operator dependency and is deliberately NOT a hard dependency here.
"""

from __future__ import annotations

import re

__all__ = ["UnsafePatternError", "safe_compile", "DEFAULT_MAX_PATTERN_LEN"]

DEFAULT_MAX_PATTERN_LEN: int = 1000


class UnsafePatternError(ValueError):
    """A supplied regex was rejected at the boundary: too long, structurally
    catastrophic (ReDoS-prone), or not a valid regex."""


# Catastrophic-backtracking signatures: a quantified group whose body is itself
# quantified — ``(a+)+``, ``(a*)*``, ``(a+)*``, ``(a*)+``, and the ``{n,}`` forms.
# These are the canonical ReDoS shapes. Conservative by design: a heuristic that
# catches the common cases, not an exhaustive analysis.
_NESTED_QUANTIFIER_RE = re.compile(
    r"""
    \(                 # a group opens
    [^()]*             # ... with no nested parens (keep the scan simple + bounded)
    [+*]               # whose body ends in a quantifier (+ or *)
    \)                 # the group closes
    \s*                # optional whitespace
    [+*]               # ... and the group itself is quantified  -> nested
    """,
    re.VERBOSE,
)
# ``(...{n,}){m,}`` open-ended-range variant of the same shape.
_NESTED_RANGE_RE = re.compile(r"\([^()]*\{\d+,\}\)\s*[+*{]")


def _is_catastrophic(pattern: str) -> bool:
    """True if ``pattern`` matches a known catastrophic-backtracking signature."""
    return bool(_NESTED_QUANTIFIER_RE.search(pattern) or _NESTED_RANGE_RE.search(pattern))


def safe_compile(
    pattern: str,
    *,
    flags: int = 0,
    max_len: int = DEFAULT_MAX_PATTERN_LEN,
) -> re.Pattern[str]:
    """Compile ``pattern`` only if it passes the boundary safety guard.

    Raises :class:`UnsafePatternError` when the pattern is over ``max_len``
    characters, matches a known catastrophic-backtracking signature, or is not a
    valid regex. Otherwise returns the compiled :class:`re.Pattern`. ``flags``
    are passed through to :func:`re.compile` (e.g. :data:`re.IGNORECASE`).
    """
    if pattern is None:  # type: ignore[unreachable]
        raise UnsafePatternError("pattern must not be None")
    if len(pattern) > max_len:
        raise UnsafePatternError(
            f"pattern too long ({len(pattern)} > {max_len} chars)"
        )
    if _is_catastrophic(pattern):
        raise UnsafePatternError(
            "pattern rejected: nested quantifier (catastrophic-backtracking "
            f"signature) in {pattern!r}"
        )
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise UnsafePatternError(f"invalid regex {pattern!r}: {exc}") from exc
