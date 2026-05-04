# AD-661 v1 — Full Diagnostic Context for Agent Self-Improvement (Pull-Based Assembly)

**GitHub issue:** #320
**Wave:** 33
**Status:** draft
**Estimated tests:** 8 (exceeds 7 floor)
**Test count baseline:** 10942 (post-Wave-32, commit `4787c9d`) → expected 10950
**Builds on:** AD-658 (chain traces, Wave 28), AD-657 (dream trace exemplars, Wave 27), AD-434 (Ship's Records — referenced, not consumed in v1)

---

## v1 Scope (HARD LIMITS)

v1 ships a **pull-based** diagnostic-context assembly service. **No automatic
invocation. No continuous diagnostic stream. No semantic search. No summary
fallback. No push-based notifications.** A caller (Science/Bridge agent,
operator, or future analyzer) explicitly invokes `assemble(query=..., budget_tokens=...)`
and receives a structured `DiagnosticBundle` of raw artifacts within budget.

The service is a **token-budgeted aggregator over already-shipped surfaces**
(AD-658 chain traces, AD-657 procedure exemplars, episodic memory `get_by_ids`).
v1 introduces no new persistence, no new EventType, and no LLM calls.

---

## Problem

After Waves 27/28 we now persist rich diagnostic artifacts:
- AD-658 chain traces — every chain step (`chain_id, step_index, step_name,
  sub_task_type, tier, agent_id, intent, started_at, duration_ms, success,
  error_truncated, communication_context, chain_trust_band, trust_score, ...`)
  in the `chain_traces` SQLite table on `CognitiveJournal`.
- AD-657 procedure exemplars — `Procedure.trace_exemplars: list[str]`
  (top-N source episode IDs by importance), resolvable via
  `EpisodicMemory.get_by_ids()`.
- AD-434 Ship's Records — Git-backed markdown frontmatter store at
  `runtime.records_store` (NOT consumed in v1; deferred AD-661b).

But **there is no single read surface** that assembles these into a coherent,
token-budgeted bundle for an agent doing diagnostic analysis. Today a Bridge
or Science agent that wants "show me what just happened" must:
1. Know AD-658 exists and call `runtime.cognitive_journal.get_recent_chain_traces(...)`.
2. Know AD-657 exists and walk `procedure_store.list_active() → procedure_store.get(id) → episodic_memory.get_by_ids(p.trace_exemplars)`.
3. Hand-merge results into a context fitting the LLM token budget.

This couples diagnostic consumers to persistence-layer details and forces
each consumer to reinvent budget management. v1 fixes the read-side seam.

---

## Solution Overview

New module `src/probos/cognitive/diagnostic_context.py`:

```
DiagnosticBundle (frozen dataclass)
├── query: str
├── chain_traces: list[dict]            # AD-658 rows, keyword-matched + budget-clipped
├── procedures: list[dict]              # {id, name, description, intent_types,
│                                       #  exemplar_episodes: list[dict]}
├── episodes: list[dict]                # deduped exemplar episodes, keyword-matched
├── total_estimated_tokens: int
├── truncated: bool
└── to_dict() → dict[str, Any]

DiagnosticContextService
└── async assemble(*, query: str,
                   budget_tokens: int = 8000,
                   agent_id: str | None = None,
                   since: datetime | None = None) -> DiagnosticBundle
```

Plus:
- `DiagnosticContextConfig` Pydantic model on `SystemConfig.diagnostic_context`
  (default-enabled — observation-only read service, no live mutation, see
  *Default rationale* below).
- Sync `_wire_diagnostic_context` in `startup/finalize.py` mirroring
  `_wire_chain_optimizer` shape.
- Public attribute `runtime.diagnostic_context_service`.
- Optional FastAPI router `routers/diagnostic_context.py` with
  `GET /api/diagnostic-context?query=...&budget=...&agent_id=...&since=...`.

### Default rationale (deviation from Wave-10 transitional-flag convention)

`enabled: bool = True` because v1 is a **read-only aggregator** — it neither
mutates state nor emits events nor consumes external resources at boot. The
Wave-10 `enabled=False` convention applies to **transitional features that
change agent behavior on first commit**; `DiagnosticContextService` is
invisible until a caller invokes `assemble()`. Document the deviation in
`Recommended` section of review.

### Allocation strategy

Default split (configurable via `DiagnosticContextConfig` ratios):
- **40% chain_traces** (`chain_trace_ratio: float = 0.4`)
- **30% procedures + inline exemplars** (`procedure_ratio: float = 0.3`)
- **30% deduped episode bodies** (`episode_ratio: float = 0.3`)

Ratios sum to 1.0 (Pydantic `field_validator` enforces; tolerance ±0.01).
Filling order: chain_traces → procedures → episodes; if any section
under-fills its allocation, **remainder is NOT redistributed in v1**
(deferred AD-661c — keeps allocation deterministic for diagnostic
reproducibility).

### Token estimator

Use the existing precedent at `agent_working_memory.py:35`:
`CHARS_PER_TOKEN = 4`. Estimator helper:
```python
def _estimate_tokens(text: str, *, chars_per_token: int = 4) -> int:
    return max(1, len(text) // chars_per_token)
```
v1 does **not** call any tokenizer library (no `tiktoken` dep). Document the
heuristic in the `DiagnosticBundle` docstring.

### Query relevance (v1 = keyword filter only, NO semantic search)

```python
def _matches(text: str, keywords: list[str]) -> bool:
    """Case-insensitive substring match. Empty keywords → always match."""
    if not keywords:
        return True
    haystack = (text or "").lower()
    return any(kw in haystack for kw in keywords)
```

Keywords derived by splitting `query` on whitespace and lowercasing; tokens
shorter than 3 chars are dropped. Empty effective keyword list → "include
all" (just budget-clip). v1 explicitly does **not** call
`EpisodicMemory.recall()` (which uses ChromaDB embedding similarity =
semantic search, out of scope).

Filter targets:
- chain_traces: `step_name`, `sub_task_type`, `intent`, `error_truncated`, `communication_context`
- procedures: `name`, `description`, `intent_types` (joined as comma-separated)
- episodes: `text` field (and any `summary` if present)

---

## Verified Anchors (against HEAD `4787c9d`, Wave 32 archive)

```
grep -n "async def get_recent_chain_traces" src\probos\cognitive\journal.py
  335:    async def get_recent_chain_traces(

grep -n "async def record_chain_trace" src\probos\cognitive\journal.py
  297:    async def record_chain_trace(self, trace: Any) -> None:

grep -n "CREATE TABLE IF NOT EXISTS chain_traces" src\probos\cognitive\journal.py
  57: CREATE TABLE IF NOT EXISTS chain_traces (

grep -n "trace_exemplars" src\probos\cognitive\procedures.py
  97:    trace_exemplars: list[str] = field(default_factory=list)
  128:        "trace_exemplars": self.trace_exemplars,
  163:        trace_exemplars=data.get("trace_exemplars", []),

grep -n "async def get_by_ids" src\probos\cognitive\episodic.py
  1132:    async def get_by_ids(self, episode_ids: list[str]) -> list[Episode]:

grep -n "async def list_active" src\probos\cognitive\procedure_store.py
  471:    async def list_active(

grep -n "async def get" src\probos\cognitive\procedure_store.py
  451:    async def get(self, procedure_id: str) -> "Any | None":

grep -n "runtime.records_store" src\probos\creative\output_writer.py
  61:            rs = getattr(self._runtime, "records_store", None)        # AD-434 confirmed live; NOT consumed in v1

grep -n "CHARS_PER_TOKEN" src\probos\cognitive\agent_working_memory.py
  35: CHARS_PER_TOKEN = 4

grep -n "_wire_chain_optimizer" src\probos\startup\finalize.py
  214: def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
  537:     if _wire_chain_optimizer(runtime=runtime, config=config):

grep -n "chain_traces, chain_optimizer" src\probos\api.py
  195:        workforce, build, design, chat, chain_traces, chain_optimizer,
  203:        workforce, build, design, chat, chain_traces, chain_optimizer,
```

All 11 prompt-asserted symbols verified live.

---

## Section 0: Module skeleton — `src/probos/cognitive/diagnostic_context.py`

NEW FILE. Full content:

```python
"""AD-661 v1: Diagnostic Context Service — pull-based, token-budgeted assembly
of raw diagnostic artifacts (chain traces, procedure exemplars, episodes).

v1 hard limits: no automatic invocation, no continuous stream, no semantic
search, no summary fallback, no LLM calls. Read-only aggregator over
already-shipped surfaces (AD-658, AD-657).

Builds on:
- AD-658 chain_traces (CognitiveJournal.get_recent_chain_traces)
- AD-657 trace_exemplars (Procedure.trace_exemplars + EpisodicMemory.get_by_ids)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4  # Same precedent as agent_working_memory.py:35


def _estimate_tokens(text: str, *, chars_per_token: int = CHARS_PER_TOKEN) -> int:
    """Heuristic token estimator — len(text) // chars_per_token, min 1.

    v1 deliberately does NOT depend on tiktoken or any tokenizer library.
    """
    if not text:
        return 0
    return max(1, len(text) // chars_per_token)


def _extract_keywords(query: str, *, min_len: int = 3) -> list[str]:
    """Split on whitespace, lowercase, drop tokens shorter than min_len."""
    if not query:
        return []
    return [tok.lower() for tok in query.split() if len(tok) >= min_len]


def _matches(text: str | None, keywords: list[str]) -> bool:
    """Case-insensitive substring match. Empty keywords → always True."""
    if not keywords:
        return True
    if not text:
        return False
    haystack = text.lower()
    return any(kw in haystack for kw in keywords)


@dataclass(frozen=True)
class DiagnosticBundle:
    """Token-budgeted bundle of raw diagnostic artifacts.

    Field types are intentionally `list[dict]` (not typed dataclasses) — v1
    is a thin pass-through over journal rows and episode metadata; consumers
    should treat the bundle as a read-only snapshot, not a typed model.

    `total_estimated_tokens` uses the `len(text) // 4` heuristic — see
    `_estimate_tokens()`.
    """

    query: str
    chain_traces: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_tokens: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chain_traces": list(self.chain_traces),
            "procedures": list(self.procedures),
            "episodes": list(self.episodes),
            "total_estimated_tokens": self.total_estimated_tokens,
            "truncated": self.truncated,
        }


class DiagnosticContextService:
    """Pull-based diagnostic-context assembler.

    Construction mirrors AD-659 ChainOptimizer / AD-660 CausalReasoner sibling
    shape: `__init__(runtime, *, default_budget_tokens=..., chain_trace_ratio=...,
    procedure_ratio=..., episode_ratio=..., chars_per_token=...)`.

    `assemble()` never raises — every collector is wrapped in try/except →
    log-and-degrade. A failure in one section yields an empty section, not a
    failed bundle.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        default_budget_tokens: int = 8000,
        chain_trace_ratio: float = 0.4,
        procedure_ratio: float = 0.3,
        episode_ratio: float = 0.3,
        chars_per_token: int = CHARS_PER_TOKEN,
    ) -> None:
        self._runtime = runtime
        self._default_budget_tokens = default_budget_tokens
        self._chain_trace_ratio = chain_trace_ratio
        self._procedure_ratio = procedure_ratio
        self._episode_ratio = episode_ratio
        self._chars_per_token = chars_per_token

    async def assemble(
        self,
        *,
        query: str,
        budget_tokens: int | None = None,
        agent_id: str | None = None,
        since: datetime | None = None,
    ) -> DiagnosticBundle:
        """Assemble a token-budgeted diagnostic bundle.

        Args:
            query: Natural-language query for keyword filtering.
            budget_tokens: Max total tokens; falls back to default_budget_tokens.
            agent_id: Optional filter for chain_traces (passed to AD-658 surface).
            since: Optional Unix-time lower bound for chain_traces.

        Returns:
            DiagnosticBundle. Never raises.
        """
        budget = max(1, budget_tokens if budget_tokens is not None else self._default_budget_tokens)
        keywords = _extract_keywords(query)

        chain_budget = int(budget * self._chain_trace_ratio)
        procedure_budget = int(budget * self._procedure_ratio)
        episode_budget = budget - chain_budget - procedure_budget  # absorb int-trunc remainder

        truncated = False

        # --- chain traces ----------------------------------------------------
        try:
            since_ts = since.timestamp() if since is not None else None
            chain_rows, chain_truncated = await self._collect_chain_traces(
                keywords=keywords,
                budget_tokens=chain_budget,
                agent_id=agent_id,
                since=since_ts,
            )
        except Exception:
            logger.warning("AD-661: chain_traces collection failed", exc_info=True)
            chain_rows, chain_truncated = [], False
        truncated = truncated or chain_truncated

        # --- procedures + inline exemplars ----------------------------------
        try:
            procedures, exemplar_episode_index, proc_truncated = await self._collect_procedures(
                keywords=keywords,
                budget_tokens=procedure_budget,
            )
        except Exception:
            logger.warning("AD-661: procedure collection failed", exc_info=True)
            procedures, exemplar_episode_index, proc_truncated = [], {}, False
        truncated = truncated or proc_truncated

        # --- episodes (deduped exemplars, keyword-filtered) ------------------
        try:
            episodes, ep_truncated = self._collect_episodes(
                keywords=keywords,
                budget_tokens=episode_budget,
                exemplar_episode_index=exemplar_episode_index,
            )
        except Exception:
            logger.warning("AD-661: episode collection failed", exc_info=True)
            episodes, ep_truncated = [], False
        truncated = truncated or ep_truncated

        # --- total tokens ---------------------------------------------------
        total = sum(self._row_tokens(r) for r in chain_rows) \
              + sum(self._row_tokens(p) for p in procedures) \
              + sum(self._row_tokens(e) for e in episodes)

        return DiagnosticBundle(
            query=query,
            chain_traces=chain_rows,
            procedures=procedures,
            episodes=episodes,
            total_estimated_tokens=total,
            truncated=truncated,
        )

    # --- collectors -----------------------------------------------------------

    async def _collect_chain_traces(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
        agent_id: str | None,
        since: float | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            return [], False
        # Pull a generous slice; budget-clip after filter.
        raw = await journal.get_recent_chain_traces(
            limit=200, agent_id=agent_id, since=since,
        )
        accepted: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for row in raw:
            haystack = " ".join(str(row.get(k) or "") for k in (
                "step_name", "sub_task_type", "intent",
                "error_truncated", "communication_context",
            ))
            if not _matches(haystack, keywords):
                continue
            cost = self._row_tokens(row)
            if used + cost > budget_tokens:
                truncated = True
                break
            accepted.append(row)
            used += cost
        return accepted, truncated

    async def _collect_procedures(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], bool]:
        store = getattr(self._runtime, "procedure_store", None)
        episodic = getattr(self._runtime, "episodic_memory", None)
        if store is None or not hasattr(store, "list_active"):
            return [], {}, False
        try:
            summaries = await store.list_active()
        except Exception:
            logger.debug("AD-661: list_active failed", exc_info=True)
            return [], {}, False

        procedures: list[dict[str, Any]] = []
        exemplar_index: dict[str, dict[str, Any]] = {}
        used = 0
        truncated = False

        for summary in summaries:
            haystack = " ".join(str(summary.get(k) or "") for k in (
                "name", "description",
            )) + " " + ",".join(summary.get("intent_types", []) or [])
            if not _matches(haystack, keywords):
                continue

            full = None
            try:
                full = await store.get(summary["id"])
            except Exception:
                logger.debug("AD-661: procedure get failed", exc_info=True)
            if full is None:
                continue

            exemplar_dicts: list[dict[str, Any]] = []
            if episodic is not None and getattr(full, "trace_exemplars", None):
                try:
                    eps = await episodic.get_by_ids(list(full.trace_exemplars))
                except Exception:
                    logger.debug("AD-661: get_by_ids failed", exc_info=True)
                    eps = []
                for ep in eps:
                    ep_dict = self._episode_to_dict(ep)
                    if ep_dict["id"] in exemplar_index:
                        continue
                    exemplar_index[ep_dict["id"]] = ep_dict
                    exemplar_dicts.append(ep_dict)

            entry = {
                "id": getattr(full, "id", summary.get("id", "")),
                "name": getattr(full, "name", summary.get("name", "")),
                "description": getattr(full, "description", ""),
                "intent_types": list(getattr(full, "intent_types", []) or []),
                "compilation_level": getattr(full, "compilation_level", 1),
                "exemplar_episodes": exemplar_dicts,
            }
            cost = self._row_tokens(entry)
            if used + cost > budget_tokens:
                truncated = True
                break
            procedures.append(entry)
            used += cost

        return procedures, exemplar_index, truncated

    def _collect_episodes(
        self,
        *,
        keywords: list[str],
        budget_tokens: int,
        exemplar_episode_index: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        # v1 source: deduped exemplars across all in-bundle procedures.
        # NO call into EpisodicMemory.recall() — that is semantic search.
        accepted: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for ep_id, ep_dict in exemplar_episode_index.items():
            if not _matches(ep_dict.get("text", ""), keywords):
                continue
            cost = self._row_tokens(ep_dict)
            if used + cost > budget_tokens:
                truncated = True
                break
            accepted.append(ep_dict)
            used += cost
        return accepted, truncated

    # --- helpers ---------------------------------------------------------------

    def _row_tokens(self, row: dict[str, Any]) -> int:
        # Estimate tokens by serializing values to a single string.
        return _estimate_tokens(
            " ".join(str(v) for v in row.values()),
            chars_per_token=self._chars_per_token,
        )

    @staticmethod
    def _episode_to_dict(ep: Any) -> dict[str, Any]:
        return {
            "id": getattr(ep, "id", ""),
            "text": getattr(ep, "text", "") or "",
            "agent_id": getattr(ep, "agent_id", ""),
            "agent_type": getattr(ep, "agent_type", ""),
            "timestamp": getattr(ep, "timestamp", 0.0),
            "importance": getattr(ep, "importance", 0.0),
            "intent_type": getattr(ep, "intent_type", ""),
        }
```

---

## Section 1: Config — `DiagnosticContextConfig`

In `src/probos/config.py`, add after `CausalReasoningConfig` (~line 350 area, immediately before next config class):

```
===SEARCH===
class CausalReasoningConfig(BaseModel):
===REPLACE===
class DiagnosticContextConfig(BaseModel):
    """AD-661 v1: Diagnostic Context Service — pull-based bundle assembly.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `assemble()`. See AD-661 prompt for the convention deviation rationale.
    """

    enabled: bool = True
    default_budget_tokens: int = 8000
    chain_trace_ratio: float = 0.4
    procedure_ratio: float = 0.3
    episode_ratio: float = 0.3
    chars_per_token: int = 4

    @field_validator("chain_trace_ratio", "procedure_ratio", "episode_ratio")
    @classmethod
    def _ratio_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("ratio must be in [0.0, 1.0]")
        return v

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> "DiagnosticContextConfig":
        total = self.chain_trace_ratio + self.procedure_ratio + self.episode_ratio
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"ratios must sum to 1.0 (±0.01); got {total:.4f}"
            )
        return self


class CausalReasoningConfig(BaseModel):
===END REPLACE===
```

Then add `field_validator`/`model_validator` to imports at the top of `config.py` if not already present — verify with grep before editing; almost all sibling configs use `field_validator`, so the import is likely already present.

In `SystemConfig` (around line 2042, immediately after `causal_reasoning: CausalReasoningConfig`):

```
===SEARCH===
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
===REPLACE===
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
===END REPLACE===
```

---

## Section 2: Wirer — `_wire_diagnostic_context`

In `src/probos/startup/finalize.py`, add the wirer function immediately after `_wire_causal_reasoner` (line ~258):

```
===SEARCH===
def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1: Wire CausalReasoner template-fill service."""
    cfg = getattr(config, "causal_reasoning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.causal_reasoning import CausalReasoner

    runtime.causal_reasoner = CausalReasoner(
        runtime,
        max_tokens=cfg.max_tokens,
        tier=cfg.tier,
    )
    logger.info(
        "AD-660: CausalReasoner v1 initialized "
        "(template + journal + counselor concern hook)"
    )
    return True
===REPLACE===
def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1: Wire CausalReasoner template-fill service."""
    cfg = getattr(config, "causal_reasoning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.causal_reasoning import CausalReasoner

    runtime.causal_reasoner = CausalReasoner(
        runtime,
        max_tokens=cfg.max_tokens,
        tier=cfg.tier,
    )
    logger.info(
        "AD-660: CausalReasoner v1 initialized "
        "(template + journal + counselor concern hook)"
    )
    return True


def _wire_diagnostic_context(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-661 v1: Wire DiagnosticContextService pull-based assembly service."""
    cfg = getattr(config, "diagnostic_context", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.diagnostic_context import DiagnosticContextService

    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        chars_per_token=cfg.chars_per_token,
    )
    logger.info(
        "AD-661: DiagnosticContextService v1 initialized "
        "(pull-based, keyword-only, budget=%d)",
        cfg.default_budget_tokens,
    )
    return True
===END REPLACE===
```

In `finalize_startup()`, register the wirer immediately after `_wire_causal_reasoner` invocation (line ~540):

```
===SEARCH===
    if _wire_causal_reasoner(runtime=runtime, config=config):
        logger.info("AD-660: CausalReasoner v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
===REPLACE===
    if _wire_causal_reasoner(runtime=runtime, config=config):
        logger.info("AD-660: CausalReasoner v1 wired during finalization")

    if _wire_diagnostic_context(runtime=runtime, config=config):
        logger.info("AD-661: DiagnosticContextService v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
===END REPLACE===
```

---

## Section 3: Optional API endpoint — `routers/diagnostic_context.py`

NEW FILE `src/probos/routers/diagnostic_context.py`:

```python
"""ProbOS API — Diagnostic Context routes (AD-661)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostic-context", tags=["diagnostic-context"])


@router.get("")
async def get_diagnostic_context(
    query: str = "",
    budget: int = 8000,
    agent_id: str | None = None,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-661 v1: Pull-based diagnostic-context bundle.

    Args:
        query: Keyword filter (whitespace-split, lowercased, ≥3 chars retained).
        budget: Token budget (default 8000, hard cap 32000).
        agent_id: Optional chain-trace agent filter.
        since: Optional Unix-timestamp lower bound for chain traces.
    """
    service = getattr(runtime, "diagnostic_context_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="diagnostic_context disabled")

    since_dt = (
        datetime.fromtimestamp(since, tz=timezone.utc) if since is not None else None
    )
    bundle = await service.assemble(
        query=query,
        budget_tokens=min(max(budget, 1), 32000),
        agent_id=agent_id,
        since=since_dt,
    )
    return bundle.to_dict()
```

In `src/probos/api.py` (line 195 + 203), add `diagnostic_context` to the import tuple AND the for-loop tuple:

```
===SEARCH===
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    ):
        app.include_router(r.router)
===REPLACE===
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic, diagnostic_context,
    ):
        app.include_router(r.router)
===END REPLACE===
```

**Twin-block SEARCH/REPLACE risk**: the import tuple and the for-loop tuple are
byte-identical except for `from probos.routers import (` vs `for r in (`.
Bundling both edits into one combined SEARCH/REPLACE block (as shown) avoids
ambiguous matches. Same pattern used successfully in Wave 31 / AD-659.

---

## Section 4: Tests — `tests/test_ad661_diagnostic_context.py`

NEW FILE. 8 tests (exceeds 7 floor):

```python
"""AD-661 v1 — DiagnosticContextService tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.cognitive.diagnostic_context import (
    CHARS_PER_TOKEN,
    DiagnosticBundle,
    DiagnosticContextService,
    _estimate_tokens,
    _extract_keywords,
    _matches,
)


# --- Test 1: bundle frozen + to_dict round-trip ---
def test_bundle_frozen_and_to_dict_roundtrip() -> None:
    b = DiagnosticBundle(
        query="cpu",
        chain_traces=[{"chain_id": "c1", "step_name": "evaluate"}],
        procedures=[{"id": "p1", "name": "diagnose"}],
        episodes=[{"id": "e1", "text": "..."}],
        total_estimated_tokens=42,
        truncated=False,
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        b.query = "other"  # type: ignore[misc]
    d = b.to_dict()
    assert d["query"] == "cpu"
    assert d["chain_traces"][0]["step_name"] == "evaluate"
    assert d["total_estimated_tokens"] == 42
    assert d["truncated"] is False
    # to_dict returns a copy — mutating must not affect the bundle.
    d["chain_traces"].append({"chain_id": "c2"})
    assert len(b.chain_traces) == 1


# --- Test 2: keyword extractor + matcher ---
def test_keyword_extraction_and_matching() -> None:
    assert _extract_keywords("CPU usage spike") == ["cpu", "usage", "spike"]
    assert _extract_keywords("a b CPU") == ["cpu"]  # short tokens dropped
    assert _extract_keywords("") == []
    assert _matches("Step CPU evaluate", ["cpu"]) is True
    assert _matches("Step CPU evaluate", ["disk"]) is False
    assert _matches("anything", []) is True  # empty kw → include all
    assert _matches(None, ["cpu"]) is False
    assert _estimate_tokens("a" * 16) == 4
    assert _estimate_tokens("") == 0


# --- Test 3: chain_trace inclusion respects keyword + budget ---
@pytest.mark.asyncio
async def test_chain_trace_keyword_filter_and_budget() -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=[
        {"chain_id": "c1", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu_check", "intent": "diagnose",
         "error_truncated": "", "communication_context": ""},
        {"chain_id": "c2", "step_index": 0, "step_name": "REPORT",
         "sub_task_type": "ward_room_post", "intent": "compose",
         "error_truncated": "", "communication_context": ""},
        {"chain_id": "c3", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu_check", "intent": "diagnose",
         "error_truncated": "x" * 6000,  # forces budget overflow on its own
         "communication_context": ""},
    ])
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=2000)
    bundle = await svc.assemble(query="cpu", budget_tokens=2000)
    # "cpu" matches c1 and c3 (sub_task_type cpu_check); REPORT row excluded.
    assert all("cpu" in r["sub_task_type"] for r in bundle.chain_traces)
    # Budget should clip — c3's huge error_truncated > chain_budget (40% of 2000 = 800).
    assert bundle.truncated is True


# --- Test 4: procedure exemplar resolution via get_by_ids ---
@pytest.mark.asyncio
async def test_procedure_exemplar_resolution() -> None:
    proc = SimpleNamespace(
        id="p1", name="diagnose cpu",
        description="Investigate cpu spikes via memory check",
        intent_types=["diagnose"], compilation_level=2,
        trace_exemplars=["ep_a", "ep_b"],
    )
    store = MagicMock()
    store.list_active = AsyncMock(return_value=[
        {"id": "p1", "name": "diagnose cpu",
         "description": "Investigate cpu spikes via memory check",
         "intent_types": ["diagnose"], "compilation_level": 2},
    ])
    store.get = AsyncMock(return_value=proc)

    ep_a = SimpleNamespace(id="ep_a", text="cpu went to 100", agent_id="a1",
                           agent_type="science", timestamp=1.0,
                           importance=0.9, intent_type="diagnose")
    ep_b = SimpleNamespace(id="ep_b", text="cpu cooled down", agent_id="a1",
                           agent_type="science", timestamp=2.0,
                           importance=0.7, intent_type="diagnose")
    episodic = MagicMock()
    episodic.get_by_ids = AsyncMock(return_value=[ep_a, ep_b])

    runtime = SimpleNamespace(
        cognitive_journal=None, procedure_store=store, episodic_memory=episodic,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu")
    assert len(bundle.procedures) == 1
    assert bundle.procedures[0]["id"] == "p1"
    assert len(bundle.procedures[0]["exemplar_episodes"]) == 2
    episodic.get_by_ids.assert_awaited_once_with(["ep_a", "ep_b"])
    # Episodes flat list deduped — both exemplars appear once.
    ep_ids = [e["id"] for e in bundle.episodes]
    assert sorted(ep_ids) == ["ep_a", "ep_b"]


# --- Test 5: budget truncation sets truncated=True ---
@pytest.mark.asyncio
async def test_budget_truncation_sets_flag() -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(return_value=[
        {"chain_id": f"c{i}", "step_index": 0, "step_name": "EVALUATE",
         "sub_task_type": "cpu", "intent": "diagnose",
         "error_truncated": "x" * 800, "communication_context": ""}
        for i in range(50)
    ])
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=1000)
    bundle = await svc.assemble(query="cpu", budget_tokens=1000)
    # 50 rows × ~200 tokens each >> 400-token chain budget.
    assert bundle.truncated is True
    assert len(bundle.chain_traces) < 50


# --- Test 6: episode dedup across multiple procedures ---
@pytest.mark.asyncio
async def test_episode_dedup_across_procedures() -> None:
    p1 = SimpleNamespace(
        id="p1", name="cpu", description="cpu check",
        intent_types=[], compilation_level=1,
        trace_exemplars=["ep_shared", "ep_a"],
    )
    p2 = SimpleNamespace(
        id="p2", name="cpu fallback", description="cpu fallback action",
        intent_types=[], compilation_level=1,
        trace_exemplars=["ep_shared", "ep_b"],
    )
    store = MagicMock()
    store.list_active = AsyncMock(return_value=[
        {"id": "p1", "name": "cpu", "description": "cpu check",
         "intent_types": [], "compilation_level": 1},
        {"id": "p2", "name": "cpu fallback",
         "description": "cpu fallback action",
         "intent_types": [], "compilation_level": 1},
    ])
    store.get = AsyncMock(side_effect=[p1, p2])

    eps = {
        "ep_shared": SimpleNamespace(
            id="ep_shared", text="cpu shared", agent_id="a", agent_type="x",
            timestamp=1.0, importance=0.5, intent_type=""),
        "ep_a": SimpleNamespace(
            id="ep_a", text="cpu A", agent_id="a", agent_type="x",
            timestamp=2.0, importance=0.4, intent_type=""),
        "ep_b": SimpleNamespace(
            id="ep_b", text="cpu B", agent_id="a", agent_type="x",
            timestamp=3.0, importance=0.4, intent_type=""),
    }
    episodic = MagicMock()
    episodic.get_by_ids = AsyncMock(side_effect=lambda ids: [eps[i] for i in ids if i in eps])

    runtime = SimpleNamespace(
        cognitive_journal=None, procedure_store=store, episodic_memory=episodic,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=8000)
    bundle = await svc.assemble(query="cpu")
    ep_ids = [e["id"] for e in bundle.episodes]
    assert ep_ids.count("ep_shared") == 1
    assert sorted(ep_ids) == ["ep_a", "ep_b", "ep_shared"]


# --- Test 7: collector failure degrades to empty section ---
@pytest.mark.asyncio
async def test_collector_failure_degrades_gracefully(caplog: pytest.LogCaptureFixture) -> None:
    journal = MagicMock()
    journal.get_recent_chain_traces = AsyncMock(side_effect=RuntimeError("db down"))
    runtime = SimpleNamespace(
        cognitive_journal=journal, procedure_store=None, episodic_memory=None,
    )
    svc = DiagnosticContextService(runtime, default_budget_tokens=2000)
    with caplog.at_level("WARNING"):
        bundle = await svc.assemble(query="cpu")
    assert bundle.chain_traces == []
    assert bundle.procedures == []
    assert bundle.episodes == []
    assert any("AD-661" in rec.message for rec in caplog.records)


# --- Test 8: API endpoint happy path + 503 when disabled ---
def test_api_endpoint_happy_path_and_503() -> None:
    from fastapi import FastAPI
    from probos.routers import diagnostic_context as dc_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(dc_router.router)

    # disabled runtime → 503
    disabled_runtime = SimpleNamespace(diagnostic_context_service=None)
    app.dependency_overrides[get_runtime] = lambda: disabled_runtime
    with TestClient(app) as client:
        resp = client.get("/api/diagnostic-context", params={"query": "cpu"})
        assert resp.status_code == 503

    # enabled runtime → 200 + bundle shape
    fake_bundle = DiagnosticBundle(
        query="cpu",
        chain_traces=[{"chain_id": "c1"}],
        procedures=[],
        episodes=[],
        total_estimated_tokens=10,
        truncated=False,
    )
    fake_service = MagicMock()
    fake_service.assemble = AsyncMock(return_value=fake_bundle)
    enabled_runtime = SimpleNamespace(diagnostic_context_service=fake_service)
    app.dependency_overrides[get_runtime] = lambda: enabled_runtime
    with TestClient(app) as client:
        resp = client.get(
            "/api/diagnostic-context",
            params={"query": "cpu", "budget": 4000, "agent_id": "a1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "cpu"
        assert body["chain_traces"][0]["chain_id"] == "c1"
    fake_service.assemble.assert_awaited_once()
    kwargs = fake_service.assemble.await_args.kwargs
    assert kwargs["query"] == "cpu"
    assert kwargs["budget_tokens"] == 4000
    assert kwargs["agent_id"] == "a1"
```

---

## What this AD does NOT change

v1 ships pull-based assembly only. The following are **explicitly out of scope**:

- **No automatic invocation.** No agent calls `assemble()` on its own; v1 only
  surfaces the read seam.
- **No continuous diagnostic stream / WebSocket.** REST GET only.
- **No semantic search.** v1 uses substring keyword matching only.
  `EpisodicMemory.recall()` is **not** called. (Deferred AD-661d.)
- **No summary fallback.** When the bundle is over-budget, sections truncate
  and `truncated=True`; we do not invoke an LLM to summarize. (Deferred AD-661e.)
- **No push-based notifications.** No EventType, no emit on assemble.
- **No AD-434 Ship's Records integration.** `runtime.records_store` is not
  consumed by v1. (Deferred AD-661b.)
- **No retroactive backfill.** Operates only over already-persisted artifacts.
- **No persistence of bundles.** Bundles are ephemeral; assembling is a pure
  read.
- **No cross-bundle dedup.** Each `assemble()` call is independent.
- **No scoring / ranking beyond `list_active` natural order** (which is
  `total_completions DESC`). v1 keyword-filters and budget-clips in that order.
- **No agent tier / department filtering.** v1 takes only `agent_id` as a
  filter (passed straight to AD-658). (Deferred AD-661f.)
- **No remainder redistribution between sections.** Under-filling one section
  does not grant its budget to another. (Deferred AD-661c.)
- **No HXI surface.** UI integration deferred.

---

## Standing Conventions

- **Verify-first**: 11 anchors confirmed against HEAD `4787c9d` — see
  *Verified Anchors* section.
- **Wave 5 convention #1**: public attribute `runtime.diagnostic_context_service`.
- **Wave 5 convention #14 (transitional default)**: deviation noted —
  `enabled=True` because v1 is read-only and invisible until called.
  Documented in `DiagnosticContextConfig` docstring.
- **AD-660 retrospective lesson — `_cognitive_journal` collision**:
  `CognitiveAgent` defines `_cognitive_journal` as a `@property` at
  `cognitive_agent.py:265`. **Do NOT** declare a same-name field on any
  class derived from `CognitiveAgent`. AD-661 v1 does not subclass
  `CognitiveAgent` (the service is plain), so this trap does not apply
  here — but flag for future AD-661 consumers.
- **Three-tier exception handling**: collectors are tier-2 (log-and-degrade
  via `logger.warning("AD-661: ...", exc_info=True)`); inner ChromaDB / journal
  failures are tier-1 (`logger.debug`).
- **Mutable defaults**: `DiagnosticBundle` uses `field(default_factory=list)`
  for list fields per Pydantic standard.
- **Frozen dataclass field-ordering**: all `DiagnosticBundle` fields have
  defaults; the only required field is `query` (placed first). No ordering
  trap.
- **Sibling shape parity**: `_wire_diagnostic_context` mirrors
  `_wire_chain_optimizer`/`_wire_causal_reasoner` exactly.
- **Twin-block SEARCH/REPLACE**: Section 3 api.py edit bundles the import
  tuple + for-loop tuple into one combined block.

---

## Acceptance Criteria

1. **Implementation**: Sections 0–3 applied; new module
   `src/probos/cognitive/diagnostic_context.py`, new router
   `src/probos/routers/diagnostic_context.py`, `DiagnosticContextConfig`
   added to `config.py`, wirer in `startup/finalize.py`, router registered
   in `api.py`.
2. **Wirer**: Default config → `runtime.diagnostic_context_service` is a
   `DiagnosticContextService` instance after `finalize_startup`.
3. **Public attribute**: `runtime.diagnostic_context_service` (Wave 5
   convention #1).
4. **No regressions**: Full gate `pytest tests/ -q -n 8 --dist=loadfile`
   passes. Test count moves from 10942 → 10950 (+8).
5. **Verify all changes comply with the Engineering Principles in
   `.github/copilot-instructions.md`.**
6. **Tracking updates**:
   - `PROGRESS.md`: add `AD-661 v1 CLOSED` paragraph at top of Wave-32
     section.
   - `docs/development/roadmap.md`: flip AD-661 entry status to ✅
     (or add it if absent).
   - `DECISIONS.md`: NO new entry (single-AD wave, in scope of #320).
7. **GH issue close**: `#320` with build-summary comment per dispatch.
8. **Single commit**: `AD-661 v1: DiagnosticContextService — pull-based
   diagnostic bundle assembly (#320)`.

---

## Phantom-API Pre-Check

Run before commit:

```
pwsh scripts\phantom-api-precheck.ps1 -PromptPath prompts\ad-661-diagnostic-context-v1.md
```

Expected FPs (document in dispatch):
- `DiagnosticBundle`, `DiagnosticContextService`, `DiagnosticContextConfig`,
  `_wire_diagnostic_context`, `_estimate_tokens`, `_extract_keywords`,
  `_matches`, `_collect_chain_traces`, `_collect_procedures`,
  `_collect_episodes` — all introduced by this prompt.
- `SimpleNamespace`, `AsyncMock`, `MagicMock`, `TestClient`, `FastAPI`,
  `APIRouter`, `Depends`, `HTTPException`, `field_validator`,
  `model_validator` — stdlib / third-party.
- `runtime.diagnostic_context_service` — introduced by this prompt.

0 NEW phantoms expected.

---

## Tracking & Issue

- Closes GH issue #320.
- Wave 33 (single-prompt wave).
- Test count target: 10942 → 10950 (+8).
