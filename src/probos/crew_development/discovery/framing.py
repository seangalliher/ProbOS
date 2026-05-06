"""Growth-mindset framing helpers (AD-512d v1).

Pure functions. No state. No I/O. No event emission.

Replaces declarative-limit phrasing ("you can't do X") with
discovery / not-yet phrasing — Dweck growth-mindset framing per
AD-512 design principle #4.
"""

from __future__ import annotations


_GROWTH_PREFIXES: tuple[str, ...] = (
    "you can't ",
    "you cannot ",
    "you don't ",
    "you do not ",
    "you are unable to ",
    "you're unable to ",
)


def frame_as_growth(limitation_text: str) -> str:
    """Rewrite a declarative-limit string in growth-mindset terms.

    Replaces leading "you can't / you cannot / you don't / you are unable
    to" with "you have not yet developed " — keeping the rest of the
    string intact.

    Idempotent: applying twice returns the same string.

    Returns the original ``limitation_text`` unchanged when no recognized
    prefix is present.
    """
    if not limitation_text:
        return limitation_text
    lower = limitation_text.lstrip().lower()
    for prefix in _GROWTH_PREFIXES:
        if lower.startswith(prefix):
            # Preserve whitespace prefix if any.
            stripped = limitation_text.lstrip()
            leading_ws = limitation_text[: len(limitation_text) - len(stripped)]
            return f"{leading_ws}you have not yet developed {stripped[len(prefix):]}"
    return limitation_text


def frame_as_discovery(struggle_text: str) -> str:
    """Wrap a struggle description as a discovery prompt.

    Returns text shaped as "Through this experience you discovered: ..."
    Keeps the original ``struggle_text`` substring so episodic encoding
    keeps the original phrasing for retrieval.

    Returns the original ``struggle_text`` unchanged when empty.
    """
    if not struggle_text:
        return struggle_text
    return f"Through this experience you discovered: {struggle_text}"
