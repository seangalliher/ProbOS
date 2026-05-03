# AD-487: Self-Distillation v1 — Personal Ontology Map Step

**Status:** Revised (Wave 14, pass 2)
**Risk:** medium (LLM-coupled; dreaming integration deferred)
**Depends on:** LLMClient (shipped), EpisodicMemory (shipped); AD-486 NOT required
**Closes:** GitHub issue #79

---

## Solution Overview

AD-487 in roadmap.md (line 4132) describes self-distillation as a 3-stage map-reduce: **Map** (probe knowledge domains), **Collapse** (cluster into capability categories), **Reduce** (build personal ontology). Plus daydreaming (3rd dream type) as ongoing exploration. Plus DID portability (AD-441 integration).

**v1 ships 1 of 4 capabilities** (per convention #14 aggressive pre-deferral):
1. **Map step only** — `PersonalOntologyProber` exposes `probe_domain(agent_id: str, domain: str) -> ProbeResult`. Builds an `LLMRequest` from a structured self-query template ("What do I know about [X]? Up to N sub-topics with confidence scores"), calls `runtime.llm_client.complete(request)`, parses the JSON `LLMResponse.content` into a `ProbeResult(agent_id, domain, sub_topics, confidence_scores, raw_text, probed_at)`. Rate-limited per (agent, domain, 24h). Stored in new SQLite table `agent_probes`.

**Deferred:**
- AD-487b: Collapse step — cluster probes into capability categories. Forcing function: when Map results accumulate (>=10 probes per agent).
- AD-487c: Reduce step — `PersonalOntology` data structure with capability map. Depends on AD-487b clustering output.
- AD-487d: Daydream dream type — unstructured curiosity-driven LLM probing during idle. Forcing function: when AD-487a/b/c stable + dreaming.py has bandwidth slot.
- AD-487e: DID portability integration (AD-441) — personal ontology travels with agent on transfer.

## Dependencies

- `runtime.llm_client` — read-only consumer (calls `complete(LLMRequest)` returning `LLMResponse`).
- `runtime.config` — read-only for prober config.
- New SQLite table `agent_probes` — managed by `PersonalOntologyProber.start()` itself (`CREATE TABLE IF NOT EXISTS`; no migration tool needed).
- `runtime.event_log` (via `runtime.emit_event`) — emits `ONTOLOGY_PROBE_RECORDED` and `ONTOLOGY_PROBE_RATE_LIMITED`.
- `probos.protocols.ConnectionFactory` / `DatabaseConnection` — Wave 5 convention #2 stdlib-only persistence.
- `probos.storage.sqlite_factory.default_factory` — fallback when no factory injected.

All reads from existing surfaces; one new SQLite table owned by AD-487.

## Sections

### Section 0 — EventTypes

In `src/probos/events.py`, add to the existing `EventType` enum:

- `ONTOLOGY_PROBE_RECORDED = "ontology_probe_recorded"` — emitted when a Map probe completes successfully.
- `ONTOLOGY_PROBE_RATE_LIMITED = "ontology_probe_rate_limited"` — emitted when an agent attempts a probe within the 24h window.

Verified collision-free (no existing `ONTOLOGY_*` or `PROBE_*` symbols in events.py).

### Section 1 — Create `src/probos/cognitive/self_distillation/` package

- `src/probos/cognitive/self_distillation/__init__.py` — exports `PersonalOntologyProber`, `ProbeResult`, `ProbeLLMError`, `ProbeRateLimitedError`.
- `src/probos/cognitive/self_distillation/prober.py` — implementation.

Per Wave 8/9/12 precedents — the AD owns directory creation.

### Section 2 — `ProbeResult` dataclass + exception classes

In `prober.py`:

```python
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.types import LLMRequest, LLMResponse, Priority

logger = logging.getLogger(__name__)


class ProbeLLMError(RuntimeError):
    """Raised when the LLM call backing a Map-step probe fails."""


class ProbeRateLimitedError(RuntimeError):
    """Raised when a probe is rejected because the (agent, domain) is within the 24h window."""


@dataclass(frozen=True)
class ProbeResult:
    """Single Map-step probe result. AD-487 v1 surface."""
    agent_id: str
    domain: str  # e.g., "cognitive_psychology", "naval_history", "python_async"
    sub_topics: tuple[str, ...]  # 0..max_sub_topics sub-topics extracted from LLM response
    confidence_scores: tuple[float, ...]  # aligned with sub_topics; same length
    raw_text: str  # full LLM response text for audit (always populated, even on parse failure)
    probed_at: datetime  # UTC, tz-aware
```

### Section 3 — `PersonalOntologyProber` class

Constructor follows the canonical Wave 5 convention #2 shape (verified against `assignment.py:79-93`, `clearance_grants.py:51`, `consensus/trust.py:119`, `identity.py:377`, `acm.py:97`, `cognitive/counselor.py:317`, `skill_framework.py:358`/`:477`, `persistent_tasks.py:110` — 8 peer classes, identical pattern):

```python
class PersonalOntologyProber:
    """Map-step prober: structured self-queries, rate-limited, persisted.

    AD-487 v1 surface. Collapse + Reduce + daydream deferred to AD-487b/c/d.
    """

    # Use .format(domain=domain, max_sub_topics=N) — NOT f-string. The doubled
    # braces around the example JSON are literal output the model should emit.
    PROBE_TEMPLATE = (
        "You are introspecting on your own knowledge. "
        "Answer in JSON only: "
        "{{\"sub_topics\": [...up to {max_sub_topics} strings...], "
        "\"confidence\": [{max_sub_topics} floats in 0.0-1.0]}}\n\n"
        "What do you know about {domain}?"
    )

    def __init__(
        self,
        runtime: Any,
        config: "SelfDistillationConfig",
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        # Late-bind emit_event_fn (Wave 5 convention #5 / late-bind setter pattern).
        # Public attribute per Wave 5 convention #1.
        self._emit_event_fn: Callable[..., None] | None = None

    # -- lifecycle (Rec1: replace _ensure_schema with start/stop) -------

    async def start(self) -> None:
        """Open the SQLite connection and create the schema if missing."""
        self._db = await self._connection_factory.connect(str(self._config.db_path))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        """Close the SQLite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    # -- public surface ------------------------------------------------

    async def probe_domain(self, agent_id: str, domain: str) -> ProbeResult:
        """Run a Map-step probe. Rate-limited per (agent, domain, 24h).

        Body sketch (Rec2):
            1. allowed = await self._check_rate_limit(agent_id, domain)
               if not allowed: raise ProbeRateLimitedError(...) (event already emitted)
            2. prompt = self.PROBE_TEMPLATE.format(
                   domain=domain,
                   max_sub_topics=self._config.max_sub_topics,
               )
            3. request = LLMRequest(
                   prompt=prompt,
                   system_prompt="",
                   tier="standard",
                   temperature=0.0,
                   top_p=1.0,
                   max_tokens=512,
               )
            4. try:
                   response: LLMResponse = await asyncio.wait_for(
                       self._runtime.llm_client.complete(request, priority=Priority.NORMAL),
                       timeout=self._config.llm_timeout_seconds,
                   )
               except (asyncio.TimeoutError, Exception) as e:
                   raise ProbeLLMError(...) from e
               if response.error:
                   raise ProbeLLMError(response.error)
            5. raw = response.content
               try:
                   parsed = json.loads(raw)
                   sub_topics = tuple(str(x) for x in parsed.get("sub_topics", [])
                                      [: self._config.max_sub_topics])
                   confidence = tuple(float(x) for x in parsed.get("confidence", [])
                                      [: self._config.max_sub_topics])
               except (json.JSONDecodeError, TypeError, ValueError):
                   sub_topics = ()
                   confidence = ()
               # Note: raw_text always preserved (Test #12).
            6. result = ProbeResult(
                   agent_id=agent_id,
                   domain=domain,
                   sub_topics=sub_topics,
                   confidence_scores=confidence,
                   raw_text=raw,
                   probed_at=datetime.now(timezone.utc),
               )
            7. await self._persist(result)   # emits ONTOLOGY_PROBE_RECORDED
            8. return result
        """

    async def get_recent_probes(self, agent_id: str, k: int = 10) -> list[ProbeResult]:
        """Return up to k most recent probes for agent, ordered by probed_at desc.

        Body sketch:
            await self._db.execute(
                "SELECT agent_id, domain, sub_topics_json, confidence_scores_json, "
                "raw_text, probed_at FROM agent_probes "
                "WHERE agent_id = ? ORDER BY probed_at DESC LIMIT ?",
                (agent_id, k),
            )
            rows = await self._db.fetchall()
            results = []
            for row in rows:
                results.append(ProbeResult(
                    agent_id=row[0],
                    domain=row[1],
                    sub_topics=tuple(json.loads(row[2])),
                    confidence_scores=tuple(json.loads(row[3])),
                    raw_text=row[4],
                    probed_at=datetime.fromisoformat(row[5]),  # ISO 8601 with tz (N3)
                ))
            return results
        """

    # -- private helpers -----------------------------------------------

    async def _check_rate_limit(self, agent_id: str, domain: str) -> bool:
        """True if probe is allowed; False (and emit ONTOLOGY_PROBE_RATE_LIMITED) otherwise.

        Body sketch:
            await self._db.execute(
                "SELECT probed_at FROM agent_probes "
                "WHERE agent_id = ? AND domain = ? "
                "ORDER BY probed_at DESC LIMIT 1",
                (agent_id, domain),
            )
            row = await self._db.fetchone()
            if row is None:
                return True
            last = datetime.fromisoformat(row[0])
            now = datetime.now(timezone.utc)
            window = timedelta(hours=self._config.rate_limit_hours)
            if (now - last) < window:
                if self._emit_event_fn:
                    self._emit_event_fn(
                        EventType.ONTOLOGY_PROBE_RATE_LIMITED,
                        {"agent_id": agent_id, "domain": domain,
                         "last_probed_at": last.isoformat()},
                    )
                return False
            return True
        """

    async def _persist(self, result: ProbeResult) -> None:
        """Write to agent_probes; emit ONTOLOGY_PROBE_RECORDED.

        Body sketch:
            await self._db.execute(
                "INSERT INTO agent_probes "
                "(agent_id, domain, sub_topics_json, confidence_scores_json, "
                " raw_text, probed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result.agent_id,
                    result.domain,
                    json.dumps(list(result.sub_topics)),
                    json.dumps(list(result.confidence_scores)),
                    result.raw_text,
                    result.probed_at.isoformat(),  # ISO 8601 UTC tz-aware (N3)
                ),
            )
            await self._db.commit()
            if self._emit_event_fn:
                self._emit_event_fn(
                    EventType.ONTOLOGY_PROBE_RECORDED,
                    {"agent_id": result.agent_id, "domain": result.domain,
                     "sub_topic_count": len(result.sub_topics)},
                )
        """
```

Note: `DatabaseConnection` (protocols.py:186) does not expose `.cursor()`. Use `execute / fetchone / fetchall / commit` directly per the protocol surface.

SQLite schema (module-level constant in `prober.py`):
```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    sub_topics_json TEXT NOT NULL,
    confidence_scores_json TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    probed_at TEXT NOT NULL  -- ISO 8601 UTC, tz-aware
);
CREATE INDEX IF NOT EXISTS idx_agent_probes_agent_domain
    ON agent_probes(agent_id, domain, probed_at DESC);
"""
```

### Section 4 — Pydantic config

In `src/probos/config.py`, add a `SelfDistillationConfig` model and wire it onto `SystemConfig` (root config class — verified at config.py:1805):

```python
class SelfDistillationConfig(BaseModel):
    """Configuration for AD-487 self-distillation v1 (Map step only)."""
    enabled: bool = True
    rate_limit_hours: int = 24
    llm_timeout_seconds: float = 30.0
    max_sub_topics: int = 5
    db_path: Path = Path("data/agent_probes.db")
```

Wire onto `SystemConfig`:

```python
class SystemConfig(BaseModel):
    # ... existing fields ...
    self_distillation: SelfDistillationConfig = SelfDistillationConfig()  # AD-487
```

### Section 5 — Runtime wiring (finalize.py)

Follow the established phase-function shape (verified against `_wire_anomaly_window` at finalize.py:25, `_wire_tiered_knowledge_loader` at :80, `_wire_task_context` at :107):

```python
# In src/probos/startup/finalize.py
async def _wire_self_distillation(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-487: Wire PersonalOntologyProber (Map step only) and open its SQLite handle."""
    if not config.self_distillation.enabled:
        return False

    from probos.cognitive.self_distillation.prober import PersonalOntologyProber

    prober = PersonalOntologyProber(
        runtime=runtime,
        config=config.self_distillation,
    )
    # Late-bind emit fn (Wave 5 convention #5).
    prober._emit_event_fn = getattr(runtime, "emit_event", None)
    await prober.start()
    runtime.personal_ontology_prober = prober  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-487: PersonalOntologyProber initialized (db=%s; rate_limit_hours=%d)",
        config.self_distillation.db_path,
        config.self_distillation.rate_limit_hours,
    )
    return True
```

Call site (inside `finalize_startup`, alongside the existing `_wire_anomaly_window` call near finalize.py:218):

```python
if await _wire_self_distillation(runtime=runtime, config=config):
    logger.info("AD-487: Self-distillation v1 wired during finalization")
```

Note: this phase function is `async def` (unlike `_wire_anomaly_window` which is sync), because `start()` is async. Existing async wiring inside `finalize_startup` is the precedent.

## What This Does NOT Change

- No daydreaming in dreaming.py — deferred to AD-487d.
- No Collapse/clustering — deferred to AD-487b.
- No `PersonalOntology` data structure — deferred to AD-487c. v1 stores raw probe results only.
- No DID portability integration — deferred to AD-487e.
- No AD-486 onboarding integration (Phase 3 Self-Discovery) — deferred; AD-487 v1 is callable from anywhere.
- No automatic probe scheduling — caller-driven. Background scheduling is AD-487d's territory.
- LLMClient — read-only consumer; no client modifications.
- AD-636 / AD-637f LLM rate-limiting (priority lanes, per-tier RPM) is orthogonal and untouched. AD-487's 24h per-(agent, domain) rate limit operates at the prober layer, not the LLM-token layer.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_ontology_probe_recorded_exists` | Section 0 surface |
| 2 | `test_event_type_ontology_probe_rate_limited_exists` | Section 0 surface |
| 3 | `test_self_distillation_config_defaults` | Pydantic defaults |
| 4 | `test_probe_result_is_frozen_dataclass` | Section 2 contract |
| 5 | `test_start_creates_table_and_index` | Schema idempotency via `start()` |
| 6 | `test_probe_domain_calls_llm_client_complete_with_llm_request` | Verifies `complete(LLMRequest)` invocation, prompt formatting, tier="standard" |
| 7 | `test_probe_domain_parses_json_response` | Happy path: extract sub_topics + confidence from `LLMResponse.content` |
| 8 | `test_probe_domain_persists_to_db` | DB write verification |
| 9 | `test_probe_domain_emits_recorded_event` | EventType emission via `_emit_event_fn` |
| 10 | `test_probe_domain_rate_limited_within_24h` | Raises `ProbeRateLimitedError` + emits `ONTOLOGY_PROBE_RATE_LIMITED` |
| 11 | `test_probe_domain_allowed_after_24h_window` | Cross-window probe succeeds; `probed_at` round-trips |
| 12 | `test_probe_domain_handles_malformed_json` | Falls back to empty sub_topics; `raw_text` preserved |
| 13 | `test_get_recent_probes_returns_descending_order` | Query ordering + ISO 8601 round-trip |
| 14 | `test_get_recent_probes_filters_by_agent_id` | Agent isolation |
| 15 | `test_runtime_attribute_set_when_enabled` | Public-attribute wiring via `_wire_self_distillation` |

Total: ~15 tests.

## Tracking

1. **PROGRESS.md:** prepend AD-487 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-487: Self-Distillation v1 — Personal Ontology Map Step (2026-05-03)

**Problem:** LLMs don't know what they know without prompting. Agents need systematic knowledge-domain inventory to build personal ontologies (capability map, not library copy). Roadmap describes 3-stage map-reduce + daydreaming + DID portability — too much for one wave.

**Decision:** v1 ships ONLY the Map step. `PersonalOntologyProber.probe_domain(agent_id, domain)` builds an `LLMRequest` from a structured self-query template, calls `runtime.llm_client.complete(request, priority=Priority.NORMAL)`, parses the JSON `LLMResponse.content` into a `ProbeResult` (sub_topics + confidence_scores), persists to new `agent_probes` SQLite table via the standard `ConnectionFactory` injection (Wave 5 convention #2), rate-limited per (agent, domain, 24h). Emits `ONTOLOGY_PROBE_RECORDED` + `ONTOLOGY_PROBE_RATE_LIMITED`. Wired onto `SystemConfig.self_distillation`. Lifecycle is `async start()` / `async stop()` (no private `_ensure_schema()` cross-module call).

**Why:** Map step has clean surface (LLM call + parse + persist). Collapse/Reduce need accumulated probes to be useful — premature without Map data. Daydreaming needs dreaming.py bandwidth slot (separate scope). DID portability needs ontology data structure (depends on Reduce). Convention #14 aggressive pre-deferral applied.

**Cross-AD orthogonality (non-conflict):** AD-636 priority lane semaphores and AD-637f priority classification live inside `LLMClient.complete` (llm_client.py:166, 427-457); they throttle LLM tokens by tier. AD-487's 24h per-(agent, domain) limit operates at the prober layer. No integration needed.

**Deferred:**
- AD-487b: Collapse — cluster probes into capability categories. Ships when >=10 probes accumulate per agent.
- AD-487c: Reduce — `PersonalOntology` data structure. Depends on AD-487b.
- AD-487d: Daydream dream type — idle-cycle exploration. Ships when AD-487a/b/c stable + dreaming.py bandwidth.
- AD-487e: DID portability integration (AD-441). Depends on AD-487c.

**Cross-links:** AD-486 (onboarding Phase 3 Self-Discovery — eventual consumer), AD-441 (DID portability — eventual consumer), dreaming.py (eventual daydream slot), LLMClient (read-only consumer), AD-542 (DatabaseConnection / ConnectionFactory abstraction).
```

3. **docs/development/roadmap.md:** flip AD-487 status to `partial — v1 ships Map step (PersonalOntologyProber + agent_probes table); Collapse/Reduce/Daydream/DID-portability deferred to AD-487b/c/d/e`.

## Verified Against Codebase (2026-05-03)

```
$ grep -n "^class\|async def" src/probos/cognitive/llm_client.py | head -8
  22:class BaseLLMClient(ABC):
  26:    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
  46:    async def close(self) -> None:
  49:class OpenAICompatibleClient(BaseLLMClient):
  420:    async def complete(self, request: LLMRequest, ...) -> LLMResponse:
  1060:   async def complete(self, request: LLMRequest, ...) -> LLMResponse:

$ grep -n "^class LLMRequest\|^class LLMResponse" src/probos/types.py
  227:class LLMRequest:
  240:class LLMResponse:
  # LLMRequest fields: prompt, system_prompt, tier, temperature, top_p, max_tokens, id
  # LLMResponse fields: content, model, tier, tokens_used, ..., error, request_id

$ grep -n "^class DatabaseConnection\|^class ConnectionFactory" src/probos/protocols.py
  186:class DatabaseConnection(Protocol):    # async execute/fetchone/fetchall/commit/close
  223:class ConnectionFactory(Protocol):     # async connect(db_path) -> DatabaseConnection

$ grep -n "^class SystemConfig" src/probos/config.py
  1805:class SystemConfig(BaseModel):

$ grep -n "default_factory" src/probos/storage/sqlite_factory.py
  10:class SQLiteConnectionFactory:
  28:default_factory = SQLiteConnectionFactory()

$ grep -rn "connection_factory: ConnectionFactory" src/probos/ | head
  src/probos/assignment.py:84:        connection_factory: ConnectionFactory | None = None,
  src/probos/clearance_grants.py:51:        connection_factory: ConnectionFactory | None = None,
  src/probos/consensus/trust.py:119:        connection_factory: ConnectionFactory | None = None,
  src/probos/identity.py:377:        connection_factory: ConnectionFactory | None = None,
  src/probos/acm.py:97:        connection_factory: ConnectionFactory | None = None,
  src/probos/cognitive/counselor.py:317:        connection_factory: ConnectionFactory | None = None,
  src/probos/skill_framework.py:358:        connection_factory: ConnectionFactory | None = None,
  src/probos/skill_framework.py:477:        connection_factory: ConnectionFactory | None = None,
  src/probos/persistent_tasks.py:110:        connection_factory: ConnectionFactory | None = None,

$ grep -n "ONTOLOGY_PROBE\|PROBE_RECORDED\|PROBE_RATE_LIMITED" src/probos/events.py
  (0 matches — both EventTypes are collision-free)

$ grep -n "agent_probes" src/
  (0 matches — table is new; no schema collision)

$ grep -n "def _wire_" src/probos/startup/finalize.py | head
  25:def _wire_anomaly_window(*, runtime: Any, config: "SystemConfig") -> bool:
  80:def _wire_tiered_knowledge_loader(*, runtime: Any, config: "SystemConfig") -> int:
  107:def _wire_task_context(*, runtime: Any, config: "SystemConfig") -> int:
```

## Acceptance Criteria

- `src/probos/cognitive/self_distillation/` package exists.
- `PersonalOntologyProber`, `ProbeResult`, `ProbeLLMError`, `ProbeRateLimitedError` all ship as described in Section 2/3.
- Constructor accepts `connection_factory: ConnectionFactory | None = None` (Wave 5 convention #2); `_db` is typed `DatabaseConnection | None`, not `ConnectionFactory`.
- Lifecycle is `async start()` / `async stop()`; no `_ensure_schema()` cross-module call.
- Public attribute `runtime.personal_ontology_prober` (no underscore) per Wave 5 convention #1.
- 2 new EventTypes (`ONTOLOGY_PROBE_RECORDED`, `ONTOLOGY_PROBE_RATE_LIMITED`).
- `SelfDistillationConfig` Pydantic class wired onto `SystemConfig.self_distillation` (root config class).
- `agent_probes` SQLite table created idempotently inside `start()`.
- `probe_domain` calls `runtime.llm_client.complete(LLMRequest(...))` and reads `LLMResponse.content`.
- `probed_at` round-trips through ISO 8601 with `datetime.fromisoformat(...)` (tz-aware).
- 15 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #79 closes when commit lands.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hard-Stops

- `LLMClient.complete` signature differs from the verified evidence above (BaseLLMClient.complete at llm_client.py:26) — surface; verify-first regression.
- `ConnectionFactory` / `DatabaseConnection` protocol surface differs from protocols.py:186/223 — surface.
- Existing `agent_probes` table from prior partial work — surface; verify schema compat.
- AD-636 / AD-637f LLM rate-limit infrastructure conflicts with prober-layer 24h limit (should be orthogonal — surface only if integration becomes necessary).

---

## Revision (2026-05-03)

This revision applies the four Required findings (R1-R4), all four Recommended (Rec1-Rec4), and all three Nits (N1-N3) from `prompts/Reviews/ad-487-self-distillation-v1-review.md` (pass 1, Not Ready).

### Required findings addressed

- **R1 (LLMClient.chat phantom):** Replaced every `chat()` reference with `complete(LLMRequest(...))` returning `LLMResponse`. Sites updated: Solution Overview, Dependencies, Section 3 (constructor docstring + `probe_domain` body sketch now constructs `LLMRequest(prompt, system_prompt, tier, temperature, top_p, max_tokens)` and calls `await self._runtime.llm_client.complete(request, priority=Priority.NORMAL)`, reading `response.content` and `response.error`), Test #6 renamed to `test_probe_domain_calls_llm_client_complete_with_llm_request`, Hard-Stops footer renamed, Verified-Against-Codebase footer with real grep evidence.
- **R2 (Config.self_distillation phantom):** Replaced `Config` with `SystemConfig` everywhere. Section 4 wires `self_distillation: SelfDistillationConfig = SelfDistillationConfig()` onto `SystemConfig` (verified at config.py:1805). DECISIONS.md draft updated to say `SystemConfig.self_distillation`.
- **R3 (missing connection_factory parameter, Wave 5 convention #2):** Constructor now takes `*, connection_factory: ConnectionFactory | None = None` and falls back to `probos.storage.sqlite_factory.default_factory` per the canonical pattern (verified across 8 peer classes). `_db` field re-typed `DatabaseConnection | None` (was `ConnectionFactory | None` — wrong type). `start()` opens via `self._connection_factory.connect(...)`.
- **R4 (verify-first deferred to Builder):** Replaced all three `(Builder verifies ...)` placeholders with actual grep output the architect ran at revision time. Footer now shows: `BaseLLMClient.complete` signature with line numbers, `LLMRequest` / `LLMResponse` with field lists, `DatabaseConnection` / `ConnectionFactory` with line numbers, `SystemConfig` at line 1805, `default_factory` at line 28 of `sqlite_factory.py`, the 9 peer-class `connection_factory` call sites, and the 0-hit collision check for `ONTOLOGY_PROBE` and `agent_probes`.

### Recommended folded

- **Rec1 (start/stop lifecycle):** Replaced `_ensure_schema()` cross-module call with `async start()` / `async stop()` lifecycle. `start()` opens the connection, runs `_SCHEMA`, commits. `stop()` closes the handle. Section 5 calls `await prober.start()`. Test #5 renamed to `test_start_creates_table_and_index`.
- **Rec2 (method bodies sketched):** `probe_domain`, `get_recent_probes`, `_check_rate_limit`, `_persist` all have body sketches in Section 3 docstrings (numbered steps; explicit SQL with placeholder positions; explicit `json.loads` / `json.dumps` boundaries; explicit `datetime.fromisoformat` round-trip; explicit `ProbeRateLimitedError` raise + event emission). DatabaseConnection's lack of `.cursor()` called out — bodies use `execute / fetchone / fetchall / commit` directly.
- **Rec3 (phase-function shape):** Section 5 rewritten as `async def _wire_self_distillation(*, runtime: Any, config: "SystemConfig") -> bool` per the canonical signature verified at `_wire_anomaly_window:25`, `_wire_tiered_knowledge_loader:80`, `_wire_task_context:107`. Call site colocated with the existing `_wire_anomaly_window` call near finalize.py:218. Async because `start()` is async (precedent in existing `finalize_startup`).
- **Rec4 (exception classes declared):** `ProbeLLMError` and `ProbeRateLimitedError` now declared in Section 2 alongside `ProbeResult`. Section 1 `__init__.py` exports both.

### Nits resolved

- **N1 (PROBE_TEMPLATE rendering):** Comment above the constant explicitly states "Use `.format(domain=domain, max_sub_topics=N)` — NOT f-string." Body sketch step 2 in `probe_domain` matches.
- **N2 (max_sub_topics threading):** Template now interpolates `{max_sub_topics}` so the config value flows into the prompt instead of being dead.
- **N3 (probed_at ISO 8601 round-trip):** Schema column comment says "ISO 8601 UTC, tz-aware". `_persist` uses `result.probed_at.isoformat()`. `get_recent_probes` and `_check_rate_limit` use `datetime.fromisoformat(row[...])`. `probed_at=datetime.now(timezone.utc)` enforces tz-awareness on creation.

### Beyond-review structural defects discovered during revision

None. Verify-first sweep returned all 9 peer call sites for `connection_factory: ConnectionFactory`, confirmed `LLMRequest`/`LLMResponse` field shapes, and confirmed `EventType` collision-free. Re-running `scripts/phantom-api-precheck.ps1` is required as the final mandatory closing self-check.
