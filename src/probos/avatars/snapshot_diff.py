"""AD-722b-3: shallow-merge-friendly diff between two snapshot dicts.

Pure function. Returns a dict of CHANGED top-level fields (with their
new values). Empty dict means no significant change.

Numeric fields use a relative-change threshold; floats below the
threshold count as unchanged. Nested dicts are diffed recursively (one
level deep — matches the snapshot's flat-of-flats shape).

Fields named in ``always_skip`` are excluded from candidate set entirely
(``last_observed_at`` would otherwise change every frame).
"""
from __future__ import annotations

from typing import Any

# These change every frame by nature; never diff-trigger on them.
DEFAULT_SKIP_FIELDS: frozenset[str] = frozenset({"last_observed_at"})

_MISSING = object()


def compute_diff(
    prev: dict[str, Any] | None,
    nxt: dict[str, Any],
    threshold: float = 0.05,
    skip_fields: frozenset[str] = DEFAULT_SKIP_FIELDS,
) -> dict[str, Any]:
    """Compute changed fields. Returns ``{}`` if no significant change."""
    if prev is None:
        # First frame — every field changed; caller should send full.
        return {k: v for k, v in nxt.items() if k not in skip_fields}

    out: dict[str, Any] = {}
    for key, new_val in nxt.items():
        if key in skip_fields:
            continue
        old_val = prev.get(key, _MISSING)
        if old_val is _MISSING:
            out[key] = new_val
            continue
        if _values_differ(old_val, new_val, threshold):
            out[key] = new_val
    return out


def _values_differ(old: Any, new: Any, threshold: float) -> bool:
    if type(old) is not type(new):
        return True
    if isinstance(new, bool):
        return old != new
    if isinstance(new, (int, float)):
        try:
            o = float(old)
            n = float(new)
        except (TypeError, ValueError):
            return old != new
        if o == n:
            return False
        denom = max(abs(o), abs(n), 1e-9)
        return (abs(n - o) / denom) >= threshold
    if isinstance(new, dict):
        # One level of nested diff — same threshold applied recursively.
        nested = compute_diff(old, new, threshold, skip_fields=frozenset())
        return bool(nested)
    if isinstance(new, list):
        # Lists: change-detected if length differs OR any positional value
        # differs by the same rule. Cheap, sufficient for tuple fields
        # like degraded_reasons.
        if len(old) != len(new):
            return True
        return any(_values_differ(o, n, threshold) for o, n in zip(old, new))
    return old != new
