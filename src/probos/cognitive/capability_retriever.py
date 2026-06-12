"""AD-983d: the deferred-tool retriever — manifest + lazy ``find_intents``.

The GitHub Copilot *deferred-tool* model, for ProbOS. An agent (or the
decomposer) always sees a cheap **manifest** — ``name`` + one-line description —
of the capabilities in scope, and pays for full detail (params + ``usage_hint``)
only for the few it retrieves *by concept* this turn. Selection becomes
**retrieval over a catalog**, not enumeration of a long flat list — the fix for
the two failures that appear as the intent catalog grows to hundreds:
context blowout (every param table rendered every turn) and selection
degradation (a long near-duplicate list makes the model worse at picking).

**Deterministic by construction.** ``find_intents`` fuses two *lexical* rankings
(a name-token axis and a full-text axis over description + ``usage_hint`` +
param text) via the AD-979c :func:`reciprocal_rank_fusion`. For a given
``(scope, concept, catalog)`` the ranking is always identical, so plans and
tests are reproducible (the PromptBuilder's sorted-stable contract, preserved).

**Vocabulary-mismatch safety (the AD-979c hybrid principle).** Matching over the
*full* descriptor text — not just its name — surfaces a capability encoded under
different words than the query (e.g. *"look something up on the web"* still finds
``web_search`` via its description, not its name). An optional ``dense_ranking``
argument lets a future semantic axis be fused through the *same* RRF call (the
forward extension point), but the default path is deterministic lexical only —
no nondeterministic embedding in the hot path.
"""

from __future__ import annotations

from probos.cognitive.episodic import fts_or_query, reciprocal_rank_fusion
from probos.types import IntentDescriptor


def _tokenize(text: str) -> set[str]:
    """Deterministic token set for *text*, reusing the AD-979c tokenizer.

    :func:`fts_or_query` lowercases, splits on non-alphanumerics (so
    ``web_search`` → ``web``, ``search``), drops tokens shorter than 2 chars,
    and dedupes. It returns a quoted OR-string (``'"web" OR "search"'``) or
    ``""``; this recovers the bare tokens as a set (``""`` → empty set).
    """
    q = fts_or_query(text or "")
    if not q:
        return set()
    return {term.strip('"') for term in q.split(" OR ")}


def _one_line(text: str, *, limit: int = 80) -> str:
    """First-line, whitespace-collapsed, length-capped form of *text*."""
    line = " ".join((text or "").split())
    if len(line) > limit:
        return line[: limit - 1].rstrip() + "\u2026"
    return line


class CapabilityRetriever:
    """A deterministic index over a catalog of :class:`IntentDescriptor`.

    Built once from the full catalog; queried with a per-call ``scope`` (the
    set of intent names an agent is granted ∩ live pools — AD-983a/b) so the
    same index serves every agent. Stateless across calls; safe to share.
    """

    def __init__(self, descriptors: list[IntentDescriptor]) -> None:
        # Deduplicate by name (first occurrence wins), preserving determinism.
        seen: set[str] = set()
        self._descriptors: list[IntentDescriptor] = []
        for d in descriptors:
            if d.name and d.name not in seen:
                seen.add(d.name)
                self._descriptors.append(d)
        self._by_name: dict[str, IntentDescriptor] = {
            d.name: d for d in self._descriptors
        }
        # Precompute token sets once (deterministic; reused across queries).
        self._name_tokens: dict[str, set[str]] = {
            d.name: _tokenize(d.name) for d in self._descriptors
        }
        self._full_tokens: dict[str, set[str]] = {
            d.name: self._descriptor_tokens(d) for d in self._descriptors
        }

    @staticmethod
    def _descriptor_tokens(d: IntentDescriptor) -> set[str]:
        """Full searchable token set: name + description + usage_hint + params.

        Matching over the whole surface (not just the name) is what catches a
        vocabulary mismatch on the name — the AD-979c hybrid principle.
        """
        parts: list[str] = [d.name, d.description, d.usage_hint]
        for key, val in (d.params or {}).items():
            parts.append(str(key))
            parts.append(str(val))
        return _tokenize(" ".join(p for p in parts if p))

    @property
    def catalog_size(self) -> int:
        """Number of (deduplicated) descriptors in the catalog."""
        return len(self._descriptors)

    def _scoped(self, scope: set[str] | None) -> list[IntentDescriptor]:
        if scope is None:
            return list(self._descriptors)
        return [d for d in self._descriptors if d.name in scope]

    def manifest(self, *, scope: set[str] | None = None) -> list[tuple[str, str]]:
        """Always-loaded tier: ``[(name, one_line_description), ...]``.

        Sorted by name (deterministic), scoped to ``scope`` (the agent's granted
        ∩ live set) or the whole catalog when ``scope is None``. Cheap — names
        plus one line each, never the full param tables. Per-agent scoping is
        the *first* filter: an agent granted 8 of 400 sees a manifest of 8, so
        the AD-983b grants do double duty (governance **and** context reduction).
        """
        return [
            (d.name, _one_line(d.description))
            for d in sorted(self._scoped(scope), key=lambda d: d.name)
        ]

    def find_intents(
        self,
        concept: str,
        *,
        scope: set[str] | None = None,
        k: int = 8,
        dense_ranking: list[str] | None = None,
    ) -> list[IntentDescriptor]:
        """Lazy detail: ``tool_search`` for ProbOS.

        Return up to ``k`` full :class:`IntentDescriptor` objects matching
        ``concept``, ranked by AD-979c Reciprocal Rank Fusion over a name-token
        axis and a full-text axis (scoped to ``scope`` when given). Full params
        + ``usage_hint`` are fetched only for the matched few, then the DAG
        (decomposer) / affordance block (AD-983a) is built against them.

        Deterministic: the same ``(scope, concept, catalog)`` always yields the
        same order. ``dense_ranking`` (a list of intent names from a future
        semantic axis) is fused through the same RRF when provided — the forward
        extension point; the default path is deterministic lexical only. An
        empty query or no lexical match returns ``[]``.
        """
        candidates = self._scoped(scope)
        query_tokens = _tokenize(concept)
        if not candidates:
            return []

        def _rank(token_map: dict[str, set[str]]) -> list[str]:
            scored: list[tuple[str, int]] = []
            for d in candidates:
                overlap = len(query_tokens & token_map.get(d.name, set()))
                if overlap > 0:
                    scored.append((d.name, overlap))
            # Higher overlap first, then name ascending — deterministic.
            scored.sort(key=lambda kv: (-kv[1], kv[0]))
            return [name for name, _ in scored]

        rankings: list[list[str]] = []
        if query_tokens:
            rankings.append(_rank(self._name_tokens))
            rankings.append(_rank(self._full_tokens))
        # Optional semantic axis (forward marker), scoped + fused identically.
        if dense_ranking:
            scoped_names = {d.name for d in candidates}
            rankings.append([n for n in dense_ranking if n in scoped_names])

        rankings = [r for r in rankings if r]
        if not rankings:
            return []
        fused = reciprocal_rank_fusion(rankings)
        return [self._by_name[name] for name, _score in fused[:k]]
