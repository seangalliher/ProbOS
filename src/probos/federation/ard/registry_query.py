"""AD-1044/AD-1045: pure in-memory keyword search + faceting over an ARD catalog.

Epic #989 Discovery 5/12 & 6/12. The AD-1044 ``POST /ard/search`` and AD-1045
``POST /ard/explore`` / ``GET /ard/agents`` endpoints rank and browse the
AD-1041 catalog projection. This module is the ranking/faceting ENGINE behind
them — a pure keyword scorer modelled on ``CodebaseIndex.query`` (per-token
additive field weighting), not a new ML index.

Layer discipline (AD-1040 purity invariant): this module imports NOTHING from
the rest of ``probos`` — only stdlib (``re``) + the pure ``.catalog`` types. So
it stays cheap to import and can never trigger a router/runtime import cycle.
The router (``routers/ard.py``) owns the pydantic request models and passes the
already-parsed ``text`` / ``type`` / ``tags`` as plain values, so the pydantic
models never reach this pure module.
"""

from __future__ import annotations

import re
from typing import Any

from .catalog import CatalogEntry

# Token shape mirrors CodebaseIndex.query / fts_or_query: lowercase alnum runs,
# drop single-character noise tokens.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Per-field additive weights (a token that "contains-matches" a field adds the
# field's weight). Name is the strongest signal, representative queries the
# weakest — they are illustrative, not authoritative.
_W_NAME = 5
_W_CAPS = 4
_W_TAGS = 3
_W_DESC = 2
_W_REPR = 1


def _tokens(text: str) -> list[str]:
    """Lowercase the text and return its alphanumeric tokens (len >= 2)."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def search_entries(
    entries: list[CatalogEntry],
    text: str,
    *,
    type: str | None = None,
    tags: list[str] | None = None,
) -> list[CatalogEntry]:
    """Filter then keyword-rank ``entries`` (relevance only — never trust).

    Filter is applied FIRST (spec §7.1):
      * ``type`` — exact ``entry.type`` (media-type) match.
      * ``tags`` — the entry must contain EVERY requested tag (AND).

    Then, if ``text`` has no usable tokens, the filtered list is returned as-is
    (honest-degrade: an empty query is a browse). Otherwise each entry gets a
    per-token additive score over its fields (``display_name`` x5, ``capabilities``
    x4, ``tags`` x3, ``description`` x2, ``representative_queries`` x1, by lowercased
    substring containment); score-0 entries are dropped and the survivors are
    sorted by ``(-score, identifier)`` (stable, deterministic).
    """
    # --- filter FIRST --------------------------------------------------------
    filtered: list[CatalogEntry] = list(entries)
    if type:
        filtered = [e for e in filtered if e.type == type]
    if tags:
        required = [t for t in tags if t]
        if required:
            filtered = [e for e in filtered if all(t in e.tags for t in required)]

    tokens = _tokens(text)
    if not tokens:
        # Honest-degrade: no usable query text → the filtered set is the result.
        return filtered

    scored: list[tuple[int, CatalogEntry]] = []
    for entry in filtered:
        name_l = (entry.display_name or "").lower()
        caps_l = " ".join(entry.capabilities).lower()
        tags_l = " ".join(entry.tags).lower()
        desc_l = (entry.description or "").lower()
        repr_l = " ".join(entry.representative_queries).lower()
        score = 0
        for tok in tokens:
            if tok in name_l:
                score += _W_NAME
            if tok in caps_l:
                score += _W_CAPS
            if tok in tags_l:
                score += _W_TAGS
            if tok in desc_l:
                score += _W_DESC
            if tok in repr_l:
                score += _W_REPR
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda pair: (-pair[0], pair[1].identifier))
    return [entry for _, entry in scored]


def facet_entries(entries: list[CatalogEntry]) -> dict[str, dict[str, int]]:
    """Count entries by media-``type``, by ``tag``, and by ship-local ``axis``.

    Returns ``{"types": {media_type: count}, "tags": {tag: count},
    "axes": {axis: count}}``. The ``axes`` map reads ``entry.data["axis"]`` when
    ``data`` is a dict (the inline ship-local entries carry it); reference
    entries (``url``-based, ``data`` is None) contribute no axis.
    """
    types: dict[str, int] = {}
    tags: dict[str, int] = {}
    axes: dict[str, int] = {}
    for entry in entries:
        if entry.type:
            types[entry.type] = types.get(entry.type, 0) + 1
        for tag in entry.tags:
            tags[tag] = tags.get(tag, 0) + 1
        data: Any = entry.data
        if isinstance(data, dict):
            axis = data.get("axis")
            if axis:
                axes[axis] = axes.get(axis, 0) + 1
    return {"types": types, "tags": tags, "axes": axes}


__all__ = ["search_entries", "facet_entries"]
