# Memvid pattern 1 — QueryPlanner relational lookup

**Issue:** [#490](https://github.com/seangalliher/ProbOS/issues/490)
**Type:** Architecture Decision (cognitive — recall pipeline routing)
**Depends on:** AD-567a (`AnchorFrame`), AD-570 (`recall_by_anchor` / `recall_by_anchor_scored`), AD-606 (think-in-memory composite scoring).
**Wave:** 130

## Goal

ProbOS already has structured anchor-field recall (`EpisodicMemory.recall_by_anchor`) and pure-semantic recall (`EpisodicMemory.recall`). What it does **not** have is a router that decides between them — every query today goes through the semantic path even when the question is purely relational ("who works at X", "where is Y", "when did Z happen"). Memvid's "relational query first, vector second" pattern fixes this: classify the query shape, run the cheap structured lookup if it matches, fall back to vector similarity otherwise.

This AD ships the classifier and the router only. **Pattern 2 (`VersionRelation` enum) and pattern 3 (per-engine-version enrichment) are explicitly out of scope** and tracked as `memvid-versionrelation-v1` and `memvid-engineversion-v1` follow-ups.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/cognitive/episodic.py:1648` `async def recall(self, query: str, k: int = 5) -> list[Episode]` — pure semantic via ChromaDB cosine. No classification layer.
- ✅ `src/probos/cognitive/episodic.py:2747` `async def recall_by_anchor(*, department, channel, trigger_type, trigger_agent, watch_section, agent_id, participants, time_range, semantic_query, limit) -> list[Episode]` — fully structured anchor lookup. Already supports the WHO/WHERE/WHEN dimensions a relational query needs.
- ✅ `src/probos/cognitive/episodic.py:1755` `recall_by_anchor_scored` returns `list[RecallScore]` — useful for the fallback hybrid path.
- ✅ `src/probos/types.py:358` `class AnchorFrame` carries `participants`, `trigger_agent`, `department`, `channel`, `watch_section`, `trigger_type`, time fields. Every classifier mapping target already exists as an anchor field.
- ✅ `src/probos/protocols.py:45` `EpisodicMemoryProtocol` exposes `async def recall(query, k) -> list[Episode]`. The Protocol is the seam tests use; QueryPlanner depends on the **concrete** `EpisodicMemory` because it needs `recall_by_anchor`, which is not in the Protocol. Either widen the Protocol (preferred, 1 line) or accept `Any` (acceptable if widening risks too much fan-out — verify-first which call sites mock the Protocol).
- ✅ Grep for `class QueryPlanner` returns nothing — greenfield.
- ⚠️ Dispatch's framing was "what does the current recall pipeline look like at HEAD (post-recovery)?" Verified: HEAD has `recall` + `recall_by_anchor*` already; `recall_weighted` (`:2509`) and `recall_by_intent` (`:2005`) round it out. The QueryPlanner is therefore a **routing layer in front of existing methods**, not a new lookup engine. This prompt reflects that.

## Build Ordering Note

This prompt edits `src/probos/config.py` (D2). Four Wave 130 prompts touch that file; serialize commits in this order to avoid register-block collisions: **claude-bootstrap → AD-701 → AD-707 → Memvid-QP**. Memvid-QP is fourth (last); rebase on top of the AD-707 commit before adding `QueryPlannerConfig`.

## Scope

Add `QueryPlanner` (classification → routing decision), wire it into the recall pipeline as an opt-in pre-step controlled by config, and ship tests. Do **not** add new embeddings, do **not** modify ChromaDB metadata, do **not** introduce graph storage.

## Deliverables

### D1. New module `src/probos/cognitive/query_planner.py`

```python
"""Memvid pattern 1: route relational queries to structured anchor lookup
before falling back to semantic similarity.

Classification rules (deterministic, regex-driven, no LLM):

  WHO    : ``\\bwho\\b`` and (``\\bworks at\\b``|``\\bbelongs to\\b``|``\\bis (?:on|in)\\b``)
           → anchor.department or anchor.participants
  WHERE  : ``\\bwhere\\b`` and (``\\bis\\b``|``\\bdid\\b``)
           → anchor.channel or anchor.department
  WHEN   : ``\\bwhen\\b`` and (``\\bdid\\b``|``\\bhappened\\b``|``\\bwas\\b``)
           → anchor.watch_section / time_range

A relational match emits a ``QueryPlan`` with the ``relational`` flag set
and the resolved anchor kwargs. The caller (recall pipeline) hands those
kwargs to ``EpisodicMemory.recall_by_anchor``. If the structured lookup
returns nothing, the caller falls back to ``recall(query, k)``.

Out of scope (memvid follow-ups):
  - VersionRelation enum (memvid pattern 2 — file as memvid-versionrelation-v1)
  - per-engine-version enrichment (memvid pattern 3 — file as memvid-engineversion-v1)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

QueryShape = str  # Literal["RELATIONAL_WHO","RELATIONAL_WHERE","RELATIONAL_WHEN","SEMANTIC"]


@dataclass(frozen=True)
class QueryPlan:
    shape: QueryShape
    relational: bool
    anchor_kwargs: dict[str, Any] = field(default_factory=dict)


_WHO_RE = re.compile(
    r"\bwho\b.*?\b(works at|belongs to|is (?:on|in)|reports to)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(
    r"\bwhere\b.*?\b(?:is|did|was)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)
_WHEN_RE = re.compile(
    r"\bwhen\b.*?\b(?:did|happened|was)\b\s+([A-Za-z0-9_\- ]+)",
    re.IGNORECASE,
)


class QueryPlanner:
    """Classify a query and produce a recall plan."""

    def classify(self, query: str) -> QueryPlan:
        text = query.strip()
        if not text:
            return QueryPlan(shape="SEMANTIC", relational=False)

        m = _WHO_RE.search(text)
        if m:
            target = m.group(2).strip().rstrip("?.!,").strip()
            # Heuristic: short token = department; multi-word = participant callsign
            if " " in target:
                return QueryPlan(
                    shape="RELATIONAL_WHO", relational=True,
                    anchor_kwargs={"participants": [target], "semantic_query": text},
                )
            return QueryPlan(
                shape="RELATIONAL_WHO", relational=True,
                anchor_kwargs={"department": target.lower(), "semantic_query": text},
            )

        m = _WHERE_RE.search(text)
        if m:
            target = m.group(1).strip().rstrip("?.!,").strip()
            return QueryPlan(
                shape="RELATIONAL_WHERE", relational=True,
                anchor_kwargs={"channel": target.lower(), "semantic_query": text},
            )

        m = _WHEN_RE.search(text)
        if m:
            return QueryPlan(
                shape="RELATIONAL_WHEN", relational=True,
                anchor_kwargs={"semantic_query": text},
            )

        return QueryPlan(shape="SEMANTIC", relational=False)

    async def recall_with_fallback(
        self,
        episodic: Any,           # EpisodicMemory (concrete; needs recall_by_anchor)
        query: str,
        k: int = 5,
    ) -> list[Any]:
        """Run the planned lookup; fall back to semantic on empty.

        Always returns a list (possibly empty). Never raises on classification.
        """
        plan = self.classify(query)
        if plan.relational:
            try:
                results = await episodic.recall_by_anchor(
                    limit=k, **plan.anchor_kwargs,
                )
                if results:
                    logger.debug(
                        "Memvid: %s → %d episodes via anchor lookup",
                        plan.shape, len(results),
                    )
                    return list(results)
            except Exception:
                logger.warning(
                    "Memvid: anchor lookup raised, falling back to semantic",
                    exc_info=True,
                )
        return await episodic.recall(query, k=k)
```

### D2. Pydantic config

In `src/probos/config.py`, alongside the existing recall-pipeline config (verify-first the exact location):

```python
class QueryPlannerConfig(BaseModel):
    """Memvid pattern 1: relational query routing."""
    enabled: bool = False                 # opt-in until coverage proves out
    fall_through_on_empty: bool = True    # if relational match returns 0, run semantic
```

### D3. Pipeline wiring

In whichever recall caller is closest to the user-input boundary, gate on `cfg.cognitive.query_planner.enabled`. Verify-first: typical call sites are `cognitive_agent.py` and `runtime.py`. Add a single helper on `EpisodicMemory` (or the runtime, depending on architecture):

```python
async def recall_routed(self, query: str, k: int = 5) -> list[Episode]:
    """Memvid: classify-then-recall. Pure delegation when planner disabled."""
    if self._query_planner is None:
        return await self.recall(query, k=k)
    return await self._query_planner.recall_with_fallback(self, query, k=k)
```

Inject `_query_planner` via a setter (`set_query_planner`) per the Hebbian-injection pattern at `trust.py:150` so test fakes can substitute.

### D4. Tests — `tests/test_memvid_queryplanner_relational.py`

Required (≥ 8):

1. `test_classify_who_works_at_returns_relational_who_with_department` — query "who works at engineering" → `RELATIONAL_WHO` with `anchor_kwargs["department"] == "engineering"`.
2. `test_classify_who_works_at_multiword_uses_participants` — "who works at the bridge crew" → `participants` list (heuristic).
3. `test_classify_where_is_returns_relational_where_with_channel`.
4. `test_classify_when_did_returns_relational_when`.
5. `test_classify_plain_query_returns_semantic` — "what is consensus" → `SEMANTIC`.
6. `test_classify_empty_query_returns_semantic`.
7. `test_recall_with_fallback_uses_anchor_when_relational_hits` — fake EpisodicMemory whose `recall_by_anchor` returns `[ep]`; confirm `recall` is NOT called.
8. `test_recall_with_fallback_falls_back_when_anchor_empty` — `recall_by_anchor` returns `[]` → `recall` called with original query.
9. `test_recall_with_fallback_falls_back_on_anchor_exception` — `recall_by_anchor` raises → `recall` called.
10. `test_recall_with_fallback_uses_semantic_for_non_relational` — semantic shape goes straight to `recall`.
11. (Recommended R2) `test_classify_who_works_at_handles_trailing_punctuation_and_words` — "who works at engineering, please?" → trim behavior locks the classifier's strip discipline.

Use `_FakeEpisodic` stub instead of mocking the full Protocol — keeps tests deterministic and order-independent.

## Hard constraints (do NOT do)

- Do **not** add a `VersionRelation` enum — file as `memvid-versionrelation-v1` follow-up.
- Do **not** add per-engine-version enrichment to anchor metadata — file as `memvid-engineversion-v1` follow-up.
- Do **not** modify `recall` or `recall_by_anchor` signatures.
- Do **not** introduce LLM calls inside `classify` — regex only, deterministic, sub-millisecond.
- Do **not** widen `EpisodicMemoryProtocol` if doing so requires updating > 5 mock sites — accept `Any` and document the structural requirement.
- Do **not** default `enabled=True`.

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- All new code passes lint with full type annotations on public methods.
- 8+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_memvid_queryplanner_relational.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **memvid-versionrelation-v1**: enum for relation kinds (`HAS_PART`, `BELONGS_TO`, etc.) layered on `AnchorFrame`.
- **memvid-engineversion-v1**: per-document version anchoring so relational queries can constrain by version window.
- **AD-NNN (TBD)**: LLM-assisted query classification fallback when regex is too brittle (only after measured miss-rate justifies it).

## Revision (2026-05-08)

- **Recommended R2:** Added test #11 for the classifier's trailing-punctuation trim behavior ("who works at engineering, please?").
- **Recommended R3 (line drift):** Refreshed `trust.py:150` (was `:165`) for `set_department_lookup` injection-pattern citation.
- **Recommended R4 (log level):** Bumped `recall_with_fallback`'s anchor-failure log from `.debug` to `.warning` (anchor lookup failure is degraded operation, not normal flow).
- **Cross-cutting:** Added Build Ordering Note (config.py serialization order, Memvid-QP last) and pre-flight working-tree integrity reminder.
