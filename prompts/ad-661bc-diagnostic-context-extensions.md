# AD-661b + AD-661c (Combo Wave 45) — DiagnosticContextService extensions

**Status:** Ready for build
**Dependencies:** AD-661 v1 (Wave 33, commit 9119f50), AD-594a (Wave 44 — only `runtime.records_store` reuse, no consultation surface touched)
**Closes:** GH issue #412 (AD-661b — Ship's Records consumption), GH issue #413 (AD-661c — budget remainder redistribution)
**Estimated tests:** 12 new (over 10 floor by 2). Baseline 11109 → expected 11121.

---

## Problem

AD-661 v1 shipped a 3-tier pull-based diagnostic-context aggregator (chain_traces / procedures / episodes) with a hard 40/30/30 split and **no remainder redistribution** when a tier under-fills. Two known follow-ups remained open:

1. **AD-661b (#412)** — bundle has no Ship's Records (AD-434) coverage. The Lee et al. Meta-Harness proposer (arXiv:2603.28052) calls for *all* available raw diagnostic context; system records (post-mortems, design notes, ship logs, fleet reports) are a first-class source. AD-434 RecordsStore has been shipped for many waves and `runtime.records_store` is already public. v1 chose to defer rather than expand v1 scope.
2. **AD-661c (#413)** — when a tier (e.g. procedures) only produces 200 tokens against a 2400-token allocation, the remaining 2200 tokens go unused even though chain_traces or episodes may have more candidate items waiting. v1 deliberately punted this optimization.

Captain's "no trivial deferral" rule for Wave 45: ship both extensions in one Builder cycle.

## Solution overview

**AD-661b** — promote allocation to 4 tiers. Add `records: list[dict]` field to `DiagnosticBundle`. Implement `_collect_records()` collector reading `runtime.records_store.list_entries()` + `read_entry()` (existing public API), filter by query keyword substring on title + content excerpt, normalize each record to a flat dict, cap at `_MAX_RECORDS_CANDIDATES=30` before token-trim, contribute to `total_estimated_tokens`. Backward compat: missing/disabled `records_store` → `records=[]`.

**AD-661c** — implement two-pass remainder redistribution. Pass 1: each tier fills up to its allocated budget. Pass 2: redistribute total unused tokens to tiers in priority order (chain_traces > procedures > episodes > records) while candidates remain. Configurable via `redistribute_remainder: bool = True` (default on). `truncated=True` only when the **total** budget is exhausted AND at least one tier still has candidate items.

New 4-tier allocation defaults: **30% chain_traces / 25% procedures / 25% episodes / 20% records** (sum 1.0). Pydantic `model_validator` updated to 4 ratios.

---

## Verified Against Codebase (2026-05-04, HEAD `3c44903`)

```
grep -n "class DiagnosticBundle" src/probos/cognitive/diagnostic_context.py
  53: @dataclass(frozen=True)
  54: class DiagnosticBundle:

grep -n "default_factory=DiagnosticContextConfig" src/probos/config.py
  2235:        default_factory=DiagnosticContextConfig

grep -n "class DiagnosticContextConfig" src/probos/config.py
  352: class DiagnosticContextConfig(BaseModel):

grep -n "_ratios_sum_to_one" src/probos/config.py
  376:    def _ratios_sum_to_one(self) -> "DiagnosticContextConfig":

grep -n "def list_entries" src/probos/knowledge/records_store.py
  730:    async def list_entries(

grep -n "def read_entry" src/probos/knowledge/records_store.py
  700:    async def read_entry(

grep -n "def records_store" src/probos/runtime.py
  960:    def records_store(self):

grep -n "_wire_diagnostic_context" src/probos/startup/finalize.py
  370:def _wire_diagnostic_context(*, runtime: Any, config: "SystemConfig") -> bool:
  835:    if _wire_diagnostic_context(runtime=runtime, config=config):

grep -n "diagnostic-context" src/probos/routers/diagnostic_context.py
  15: router = APIRouter(prefix="/api/diagnostic-context", tags=["diagnostic-context"])

grep -n "_records_store = None" tests/conftest.py
  236:    rt._records_store = None
```

`RecordsStore.list_entries` signature confirmed: `(directory="", *, author="", status="", tags=None, classification="")` returning `list[{"path": str, "frontmatter": dict}]`. `RecordsStore.read_entry(path, reader_id, reader_department)` returns `{"frontmatter", "content", "path"}` or `None` with classification gate (private/department denied unless reader matches; ship/fleet readable by all). v1 uses module-level synthetic reader `_RECORDS_READER_ID = "_diagnostic_context_system"` + empty department → naturally surfaces only `ship`/`fleet` classifications, which is the correct safe default for system-level diagnostic context. Per-agent records authorization is out of scope (future AD-661f).

AD-692 edge classification: `KnowledgeEdge` classification gating (Wave 42) is **orthogonal** — different domain (graph edges vs markdown records). RecordsStore already carries its own per-record classification field handled inside `read_entry`. **Do not introduce edge-style gating decorators here.**

---

## Section 0 — Module-level constants (AD-661b)

Add these near `CHARS_PER_TOKEN` at the top of `src/probos/cognitive/diagnostic_context.py`:

```python
# AD-661b: Ship's Records collection caps
_MAX_RECORDS_CANDIDATES = 30  # absolute cap on records pulled from records_store before token-trim
_RECORDS_READER_ID = "_diagnostic_context_system"  # synthetic privileged reader (sees ship/fleet only)
_RECORDS_CONTENT_EXCERPT_CHARS = 1200  # truncate raw record content before inclusion in bundle dict
```

`_RECORDS_READER_ID` is the documented v1 system-context reader. With empty department, the classification gate naturally yields ship+fleet records only; private/department records are filtered out by RecordsStore itself. Documented in module docstring + config docstring.

---

## Section 1 — Config — `DiagnosticContextConfig` 4-ratio update (AD-661b + AD-661c)

In `src/probos/config.py`, replace the existing `DiagnosticContextConfig` body. Use SEARCH/REPLACE:

```
===SEARCH===
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
===REPLACE===
class DiagnosticContextConfig(BaseModel):
    """AD-661 v1 + AD-661b/c: Diagnostic Context Service — pull-based bundle assembly.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `assemble()`. See AD-661 prompt for the convention deviation rationale.

    AD-661b adds a 4th allocation tier (`records_ratio`) for Ship's Records
    (AD-434). The synthetic system-context reader naturally surfaces only
    ship/fleet records; per-agent record authorization is deferred (AD-661f).

    AD-661c adds `redistribute_remainder` (default True): unused budget from
    under-filled tiers is redistributed to other tiers in priority order
    (chain_traces > procedures > episodes > records) while candidates remain.
    """

    enabled: bool = True
    default_budget_tokens: int = 8000
    chain_trace_ratio: float = 0.30
    procedure_ratio: float = 0.25
    episode_ratio: float = 0.25
    records_ratio: float = 0.20
    chars_per_token: int = 4
    redistribute_remainder: bool = True

    @field_validator(
        "chain_trace_ratio", "procedure_ratio", "episode_ratio", "records_ratio",
    )
    @classmethod
    def _ratio_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("ratio must be in [0.0, 1.0]")
        return v

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> "DiagnosticContextConfig":
        total = (
            self.chain_trace_ratio
            + self.procedure_ratio
            + self.episode_ratio
            + self.records_ratio
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"ratios must sum to 1.0 (±0.01); got {total:.4f}"
            )
        return self
===END REPLACE===
```

---

## Section 2 — `DiagnosticBundle` — add `records` field

In `src/probos/cognitive/diagnostic_context.py`:

```
===SEARCH===
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
===REPLACE===
@dataclass(frozen=True)
class DiagnosticBundle:
    """Token-budgeted bundle of raw diagnostic artifacts.

    Field types are intentionally `list[dict]` (not typed dataclasses) — v1
    is a thin pass-through over journal rows, episode metadata, and record
    excerpts; consumers should treat the bundle as a read-only snapshot.

    `total_estimated_tokens` uses the `len(text) // 4` heuristic — see
    `_estimate_tokens()`.

    AD-661b adds `records` (Ship's Records — AD-434). Empty when
    `runtime.records_store` is None or no records match the query.
    """

    query: str
    chain_traces: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_tokens: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "chain_traces": list(self.chain_traces),
            "procedures": list(self.procedures),
            "episodes": list(self.episodes),
            "records": list(self.records),
            "total_estimated_tokens": self.total_estimated_tokens,
            "truncated": self.truncated,
        }
===END REPLACE===
```

---

## Section 3 — `DiagnosticContextService.__init__` — add records + redistribute knobs

```
===SEARCH===
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
===REPLACE===
    def __init__(
        self,
        runtime: Any,
        *,
        default_budget_tokens: int = 8000,
        chain_trace_ratio: float = 0.30,
        procedure_ratio: float = 0.25,
        episode_ratio: float = 0.25,
        records_ratio: float = 0.20,
        chars_per_token: int = CHARS_PER_TOKEN,
        redistribute_remainder: bool = True,
    ) -> None:
        self._runtime = runtime
        self._default_budget_tokens = default_budget_tokens
        self._chain_trace_ratio = chain_trace_ratio
        self._procedure_ratio = procedure_ratio
        self._episode_ratio = episode_ratio
        self._records_ratio = records_ratio
        self._chars_per_token = chars_per_token
        self._redistribute_remainder = redistribute_remainder
===END REPLACE===
```

---

## Section 4 — `assemble()` rewrite — 4 tiers + redistribution

Rewrite the assemble method body to a candidate-collection + redistribution model. Replace from the `async def assemble(` definition through the end of `assemble()` (the existing method is bounded by the next `# --- collectors ---` comment block at roughly line 175). Use SEARCH/REPLACE; the SEARCH block is the existing implementation from `async def assemble(` through `truncated=truncated,` `)` of the bundle-build expression.

```
===SEARCH===
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
===REPLACE===
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

        AD-661b: 4th tier `records` (Ship's Records). Empty when records_store
        unavailable or no matches.

        AD-661c: When ``redistribute_remainder=True`` (default), unused budget
        from any under-filled tier is redistributed to other tiers in priority
        order (chain_traces > procedures > episodes > records) while
        candidates remain.
        """
        budget = max(
            1,
            budget_tokens if budget_tokens is not None else self._default_budget_tokens,
        )
        keywords = _extract_keywords(query)

        # Per-tier base allocations — episodes absorbs int-trunc remainder of the
        # initial split (mirrors v1 behavior); records is computed last.
        chain_budget = int(budget * self._chain_trace_ratio)
        procedure_budget = int(budget * self._procedure_ratio)
        records_budget = int(budget * self._records_ratio)
        episode_budget = max(
            0, budget - chain_budget - procedure_budget - records_budget,
        )

        # --- gather candidates per tier (all candidates, no per-tier budget clip) ---
        try:
            since_ts = since.timestamp() if since is not None else None
            chain_candidates = await self._gather_chain_trace_candidates(
                keywords=keywords, agent_id=agent_id, since=since_ts,
            )
        except Exception:
            logger.warning("AD-661: chain_traces collection failed", exc_info=True)
            chain_candidates = []

        try:
            proc_entries, exemplar_episode_index = (
                await self._gather_procedure_candidates(keywords=keywords)
            )
        except Exception:
            logger.warning("AD-661: procedure collection failed", exc_info=True)
            proc_entries, exemplar_episode_index = [], {}

        try:
            episode_candidates = self._gather_episode_candidates(
                keywords=keywords,
                exemplar_episode_index=exemplar_episode_index,
            )
        except Exception:
            logger.warning("AD-661: episode collection failed", exc_info=True)
            episode_candidates = []

        try:
            record_candidates = await self._gather_record_candidates(
                keywords=keywords,
            )
        except Exception:
            logger.warning("AD-661: records collection failed", exc_info=True)
            record_candidates = []

        # --- two-pass fill: per-tier allocation, then optional redistribution ---
        candidates_by_tier: dict[str, list[dict[str, Any]]] = {
            "chain_traces": chain_candidates,
            "procedures": proc_entries,
            "episodes": episode_candidates,
            "records": record_candidates,
        }
        allocations: dict[str, int] = {
            "chain_traces": chain_budget,
            "procedures": procedure_budget,
            "episodes": episode_budget,
            "records": records_budget,
        }
        filled, truncated = self._fill_with_redistribution(
            candidates_by_tier=candidates_by_tier,
            allocations=allocations,
            total_budget=budget,
            redistribute=self._redistribute_remainder,
        )

        chain_rows = filled["chain_traces"]
        procedures = filled["procedures"]
        episodes = filled["episodes"]
        records = filled["records"]

        total = (
            sum(self._row_tokens(r) for r in chain_rows)
            + sum(self._row_tokens(p) for p in procedures)
            + sum(self._row_tokens(e) for e in episodes)
            + sum(self._row_tokens(r) for r in records)
        )

        return DiagnosticBundle(
            query=query,
            chain_traces=chain_rows,
            procedures=procedures,
            episodes=episodes,
            records=records,
            total_estimated_tokens=total,
            truncated=truncated,
        )
===END REPLACE===
```

---

## Section 5 — Replace `_collect_*` collectors with `_gather_*` candidate producers

The existing `_collect_chain_traces` / `_collect_procedures` / `_collect_episodes` did per-tier budget clipping inline. The new model gathers candidates and lets `_fill_with_redistribution` do the budget bookkeeping centrally. Rewrite each collector to drop the `budget_tokens` arg and return only the candidate list (preserving order). The procedure collector still returns the exemplar index.

```
===SEARCH===
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
===REPLACE===
    async def _gather_chain_trace_candidates(
        self,
        *,
        keywords: list[str],
        agent_id: str | None,
        since: float | None,
    ) -> list[dict[str, Any]]:
        """AD-661b/c: gather all keyword-matching chain trace rows (no budget clip)."""
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None or not hasattr(journal, "get_recent_chain_traces"):
            return []
        raw = await journal.get_recent_chain_traces(
            limit=200, agent_id=agent_id, since=since,
        )
        accepted: list[dict[str, Any]] = []
        for row in raw:
            haystack = " ".join(str(row.get(k) or "") for k in (
                "step_name", "sub_task_type", "intent",
                "error_truncated", "communication_context",
            ))
            if not _matches(haystack, keywords):
                continue
            accepted.append(row)
        return accepted
===END REPLACE===
```

```
===SEARCH===
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
===REPLACE===
    async def _gather_procedure_candidates(
        self,
        *,
        keywords: list[str],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """AD-661b/c: gather procedure entries + cross-procedure exemplar index (no budget clip)."""
        store = getattr(self._runtime, "procedure_store", None)
        episodic = getattr(self._runtime, "episodic_memory", None)
        if store is None or not hasattr(store, "list_active"):
            return [], {}
        try:
            summaries = await store.list_active()
        except Exception:
            logger.debug("AD-661: list_active failed", exc_info=True)
            return [], {}

        procedures: list[dict[str, Any]] = []
        exemplar_index: dict[str, dict[str, Any]] = {}

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
            procedures.append(entry)

        return procedures, exemplar_index
===END REPLACE===
```

```
===SEARCH===
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
===REPLACE===
    def _gather_episode_candidates(
        self,
        *,
        keywords: list[str],
        exemplar_episode_index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """AD-661b/c: deduped exemplars, keyword-filtered (no budget clip).

        Source: deduped exemplars across all in-bundle procedures.
        Explicitly NOT calling ``EpisodicMemory.recall()`` (that is semantic
        search and is out of scope for v1 / AD-661b).
        """
        accepted: list[dict[str, Any]] = []
        for ep_dict in exemplar_episode_index.values():
            if not _matches(ep_dict.get("text", ""), keywords):
                continue
            accepted.append(ep_dict)
        return accepted
===END REPLACE===
```

---

## Section 6 — New `_gather_record_candidates` (AD-661b)

Append immediately before the `# --- helpers ---` divider in `diagnostic_context.py`:

```
===SEARCH===
    # --- helpers ---------------------------------------------------------------

    def _row_tokens(self, row: dict[str, Any]) -> int:
===REPLACE===
    async def _gather_record_candidates(
        self,
        *,
        keywords: list[str],
    ) -> list[dict[str, Any]]:
        """AD-661b: keyword-filter Ship's Records and normalize to flat dicts.

        Reader identity is the synthetic ``_RECORDS_READER_ID`` with empty
        department; this naturally surfaces only ``ship``/``fleet`` records via
        ``RecordsStore.read_entry()``'s built-in classification gate. Per-agent
        record authorization is deferred (AD-661f).

        Hard-caps the candidate list at ``_MAX_RECORDS_CANDIDATES`` before
        token-trim; truncates raw record content to
        ``_RECORDS_CONTENT_EXCERPT_CHARS`` to keep individual records bounded.
        """
        store = getattr(self._runtime, "records_store", None)
        if store is None or not hasattr(store, "list_entries"):
            return []
        try:
            entries = await store.list_entries()
        except Exception:
            logger.debug("AD-661b: list_entries failed", exc_info=True)
            return []

        accepted: list[dict[str, Any]] = []
        for entry in entries:
            fm = entry.get("frontmatter") or {}
            path = entry.get("path") or ""
            title = str(fm.get("title") or path)
            # Keyword phase 1: title — cheap.
            if _matches(title, keywords):
                content_excerpt = await self._read_record_excerpt(store, path)
            else:
                # Keyword phase 2: full content — only if title missed and we
                # still need to consider this record.
                content_excerpt = await self._read_record_excerpt(store, path)
                if not _matches(content_excerpt, keywords):
                    continue
            accepted.append({
                "path": path,
                "title": title,
                "summary_excerpt": content_excerpt,
                "classification": str(fm.get("classification") or "ship"),
                "author": str(fm.get("author") or ""),
                "status": str(fm.get("status") or ""),
                "tags": list(fm.get("tags") or []),
            })
            if len(accepted) >= _MAX_RECORDS_CANDIDATES:
                break
        return accepted

    async def _read_record_excerpt(self, store: Any, path: str) -> str:
        """Read record content via ``read_entry``, truncate to excerpt length.

        Returns empty string on any failure or denial (denied records simply
        do not surface in diagnostic context — same v1 graceful-degradation
        contract).
        """
        try:
            doc = await store.read_entry(
                path,
                reader_id=_RECORDS_READER_ID,
                reader_department="",
            )
        except Exception:
            logger.debug("AD-661b: read_entry failed for %s", path, exc_info=True)
            return ""
        if not doc:
            return ""
        content = str(doc.get("content") or "")
        if len(content) > _RECORDS_CONTENT_EXCERPT_CHARS:
            content = content[:_RECORDS_CONTENT_EXCERPT_CHARS]
        return content

    # --- helpers ---------------------------------------------------------------

    def _row_tokens(self, row: dict[str, Any]) -> int:
===END REPLACE===
```

---

## Section 7 — New `_fill_with_redistribution` helper (AD-661c)

Append immediately after the existing `_episode_to_dict` static method (final method in the class). Use SEARCH/REPLACE anchored on the closing of `_episode_to_dict`:

```
===SEARCH===
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
===REPLACE===
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

    # --- AD-661c: budget allocation + redistribution -------------------------

    # Priority order for redistribution: chain traces are richest diagnostic
    # signal; records the broadest. Order is deliberately stable — used by both
    # tests and the redistribution loop.
    _TIER_PRIORITY: tuple[str, ...] = (
        "chain_traces", "procedures", "episodes", "records",
    )

    def _fill_with_redistribution(
        self,
        *,
        candidates_by_tier: dict[str, list[dict[str, Any]]],
        allocations: dict[str, int],
        total_budget: int,
        redistribute: bool,
    ) -> tuple[dict[str, list[dict[str, Any]]], bool]:
        """Two-pass fill across tiers, optional remainder redistribution.

        Pass 1: each tier fills up to its allocated budget in priority order.
        Pass 2 (only when ``redistribute`` is True): walk tiers in priority
        order again, topping up tiers that have remaining candidates while the
        global budget still has room.

        Returns ``(filled_by_tier, truncated)``. ``truncated`` is True iff the
        global budget is exhausted AND at least one tier still has unconsumed
        candidates.
        """
        filled: dict[str, list[dict[str, Any]]] = {
            tier: [] for tier in self._TIER_PRIORITY
        }
        consumed_index: dict[str, int] = {tier: 0 for tier in self._TIER_PRIORITY}
        used_total = 0

        # Pass 1 — per-tier hard allocation.
        for tier in self._TIER_PRIORITY:
            tier_budget = max(0, int(allocations.get(tier, 0)))
            candidates = candidates_by_tier.get(tier, [])
            tier_used = 0
            idx = 0
            while idx < len(candidates):
                cost = self._row_tokens(candidates[idx])
                if tier_used + cost > tier_budget:
                    break
                filled[tier].append(candidates[idx])
                tier_used += cost
                used_total += cost
                idx += 1
            consumed_index[tier] = idx

        # Pass 2 — optional redistribution of the unused remainder.
        if redistribute and used_total < total_budget:
            for tier in self._TIER_PRIORITY:
                candidates = candidates_by_tier.get(tier, [])
                idx = consumed_index[tier]
                while idx < len(candidates) and used_total < total_budget:
                    cost = self._row_tokens(candidates[idx])
                    if used_total + cost > total_budget:
                        break
                    filled[tier].append(candidates[idx])
                    used_total += cost
                    idx += 1
                consumed_index[tier] = idx
                if used_total >= total_budget:
                    break

        # Truncated iff budget exhausted AND at least one tier still has
        # candidates left over.
        truncated = any(
            consumed_index[tier] < len(candidates_by_tier.get(tier, []))
            for tier in self._TIER_PRIORITY
        )
        return filled, truncated
===END REPLACE===
```

---

## Section 8 — Wirer (AD-661b + AD-661c)

`_wire_diagnostic_context` already passes 5 named kwargs; extend to 7. In `src/probos/startup/finalize.py`:

```
===SEARCH===
    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        chars_per_token=cfg.chars_per_token,
    )
===REPLACE===
    runtime.diagnostic_context_service = DiagnosticContextService(
        runtime,
        default_budget_tokens=cfg.default_budget_tokens,
        chain_trace_ratio=cfg.chain_trace_ratio,
        procedure_ratio=cfg.procedure_ratio,
        episode_ratio=cfg.episode_ratio,
        records_ratio=cfg.records_ratio,
        chars_per_token=cfg.chars_per_token,
        redistribute_remainder=cfg.redistribute_remainder,
    )
===END REPLACE===
```

The router (`src/probos/routers/diagnostic_context.py`) already returns `bundle.to_dict()`, which now includes the new `records` key automatically. **No router edit required** — verify in tests.

---

## Section 9 — Tests (≥10; plan = 12)

New test file: `tests/test_ad661bc_records_redistribution.py`. Reuse the v1 fixture style (`SimpleNamespace` + `MagicMock` + `AsyncMock`). Builder must NOT modify `tests/test_ad661_diagnostic_context.py` — those v1 tests must continue to pass unchanged (back-compat invariant: chain_traces/procedures/episodes content unchanged when records absent and redistribution disabled).

Test plan (each is its own `def test_*`):

1. **`test_config_4_ratios_validate_and_default`** — `DiagnosticContextConfig()` default ratios sum to 1.0; explicit `records_ratio=0.5` with other defaults raises ValueError; `redistribute_remainder` default True.
2. **`test_bundle_includes_records_field`** — `DiagnosticBundle(query="x", records=[{"path":"r1"}])`; `to_dict()["records"]` is present and a copy.
3. **`test_records_gathered_when_store_has_matches`** — stub `records_store.list_entries` returns 3 entries (2 keyword-matching titles, 1 non-matching); `read_entry` returns content; bundle.records has the 2 hits with normalized fields (path/title/summary_excerpt/classification).
4. **`test_records_empty_when_no_records_store`** — `runtime.records_store = None`; bundle.records == [].
5. **`test_records_empty_when_keyword_no_match`** — list_entries returns 3 entries, none matching title or content; records == [].
6. **`test_records_excerpt_truncated`** — `read_entry` returns 5000-char content; record's `summary_excerpt` is exactly `_RECORDS_CONTENT_EXCERPT_CHARS` long.
7. **`test_records_contribute_to_total_estimated_tokens`** — measure `bundle.total_estimated_tokens` with vs without records_store, assert delta > 0 and approximately equal to records' summed `_row_tokens` cost.
8. **`test_redistribute_under_fill_in_tier_flows_to_others`** — allocate budget=2000 with all four ratios. Stub procedures empty (0 candidates) so its 500-token slice is unused. Stub chain_traces with many small candidates (~50 tokens each). With `redistribute_remainder=True`, total used tokens approach 2000 and chain_traces holds *more* than its 600-token allocation. With `redistribute_remainder=False`, chain_traces is capped at 600.
9. **`test_truncated_false_when_all_candidates_fit`** — small candidate sets totaling well under budget; `bundle.truncated is False` even with redistribute=True.
10. **`test_truncated_true_when_budget_exhausted_with_candidates_left`** — overflow chain_traces with huge rows; budget=200; assert truncated is True.
11. **`test_redistribution_priority_order_chain_first`** — allocate small budgets; provide enough candidates in chain_traces and records that both *want* the redistribution remainder; assert chain_traces fills before records does (compare extra item count beyond per-tier cap).
12. **`test_v1_backcompat_chain_procedures_episodes_unchanged`** — repeat the v1 happy-path test (procedure exemplar resolution as in `test_procedure_exemplar_resolution`) with records_store=None and `redistribute_remainder=False`; assert chain/procedure/episode bundle content matches v1 expectations exactly.

API smoke is implicitly covered — `to_dict()` returning `records` + the existing endpoint returning `bundle.to_dict()` means a test asserting the new key in the existing API test would round-trip; explicit API test deferred unless drift discovered.

---

## What this AD does NOT change (out of scope by design)

- **Semantic search** of records (still keyword-only). Future AD if signal demands it.
- **Per-agent records authorization** — uses synthetic system reader (`_RECORDS_READER_ID`); private/department records remain hidden from the bundle. Deferred AD-661f.
- **AD-692-style classification gating** — RecordsStore has its own classification (read_entry enforces it); no edge-style decorator wrapping needed.
- **records-aware HXI surface** — out of scope.
- **AD-661d push notifications** — still deferred.
- **AD-661e LLM summarization fallback** — still deferred.
- New EventType, new agent, new pool, new Pydantic config beyond the 2 added fields, new module, decomposer changes, ChromaDB read paths, federation export.

---

## Tracking updates

- **PROGRESS.md** — prepend new entry: `AD-661b + AD-661c v1 CLOSED. Ship's Records consumption + budget remainder redistribution (combo Wave 45). Closes #412 + #413.` Document 4-ratio defaults, redistribute default, synthetic reader id, test count delta.
- **docs/development/roadmap.md** — flip AD-661b row + AD-661c row from Scoped → Complete; record combo wave landing.
- **DECISIONS.md** — single combined entry under Era V: `### AD-661b + AD-661c — DiagnosticContextService Ship's Records + Budget Remainder Redistribution`. Document the synthetic reader rationale, the 30/25/25/20 default split, and the priority-order redistribution algorithm.

---

## Acceptance criteria

1. `DiagnosticBundle.records: list[dict]` field exists, `default_factory=list`, present in `to_dict()`.
2. `DiagnosticContextConfig` carries `records_ratio` (default 0.20) and `redistribute_remainder` (default True). Validator covers all 4 ratios; mismatched sum raises.
3. `DiagnosticContextService.__init__` accepts `records_ratio` + `redistribute_remainder` kwargs.
4. `_wire_diagnostic_context` passes both new kwargs.
5. `_gather_record_candidates` reads records via `runtime.records_store.list_entries()` + `read_entry()` using the synthetic system reader; truncates content to `_RECORDS_CONTENT_EXCERPT_CHARS`; caps at `_MAX_RECORDS_CANDIDATES`. Tier-2 log-and-degrade.
6. `_fill_with_redistribution` performs two-pass fill in `_TIER_PRIORITY` order; truncated iff candidates remain after global budget is exhausted.
7. All 12 new tests in `tests/test_ad661bc_records_redistribution.py` pass.
8. **All 8 existing AD-661 v1 tests in `tests/test_ad661_diagnostic_context.py` continue to pass unmodified.** This is the back-compat invariant.
9. Full test gate (`pytest tests/ -q -n 8 --dist=loadfile`) passes, no test count regression. Baseline 11109 → expected 11121 (+12).
10. Phantom-API pre-check shows 0 NEW phantoms; intro-not-in-index FPs documented in dispatch.
11. GH issues #412 and #413 close together via the combined commit message.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (final pre-flight, HEAD `3c44903`)

```
grep -n "default_budget_tokens=cfg.default_budget_tokens" src/probos/startup/finalize.py
  379:        default_budget_tokens=cfg.default_budget_tokens,

grep -n "exemplar_episode_index" src/probos/cognitive/diagnostic_context.py
  157:            episodes, ep_truncated = self._collect_episodes(
  159:                exemplar_episode_index=exemplar_episode_index,
  267:        exemplar_episode_index: dict[str, dict[str, Any]],

grep -n "test_episode_dedup_across_procedures\|test_procedure_exemplar_resolution" tests/test_ad661_diagnostic_context.py
  86: async def test_procedure_exemplar_resolution() -> None:
  146: async def test_episode_dedup_across_procedures() -> None:
```

All 11 anchors live at HEAD `3c44903`. Records read API confirmed: `RecordsStore.list_entries` + `read_entry`. No edge-style classification gate dependency. Conftest `rt._records_store = None` confirms the None-path is exercised by the existing test fleet.
