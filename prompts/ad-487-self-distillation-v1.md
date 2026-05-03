# AD-487: Self-Distillation v1 — Personal Ontology Map Step

**Status:** Drafted (Wave 14)
**Risk:** medium (LLM-coupled; dreaming integration deferred)
**Depends on:** LLMClient (shipped), EpisodicMemory (shipped); AD-486 NOT required
**Closes:** GitHub issue #79

---

## Solution Overview

AD-487 in roadmap.md (line 4132) describes self-distillation as a 3-stage map-reduce: **Map** (probe knowledge domains), **Collapse** (cluster into capability categories), **Reduce** (build personal ontology). Plus daydreaming (3rd dream type) as ongoing exploration. Plus DID portability (AD-441 integration).

**v1 ships 1 of 4 capabilities** (per convention #14 aggressive pre-deferral):
1. **Map step only** — `PersonalOntologyProber` exposes `probe_domain(domain: str) -> ProbeResult`. Calls LLM with structured self-query template ("What do I know about [X]? List 5 sub-topics with confidence scores."). Returns parsed `ProbeResult(domain, sub_topics, confidence_scores, raw_text)`. Rate-limited; one probe per agent per domain per 24h. Stored in new SQLite table `agent_probes`.

**Deferred:**
- AD-487b: Collapse step — cluster probes into capability categories. Forcing function: when Map results accumulate (≥10 probes per agent).
- AD-487c: Reduce step — `PersonalOntology` data structure with capability map. Depends on AD-487b clustering output.
- AD-487d: Daydream dream type — unstructured curiosity-driven LLM probing during idle. Forcing function: when AD-487a/b/c stable + dreaming.py has bandwidth slot.
- AD-487e: DID portability integration (AD-441) — personal ontology travels with agent on transfer.

## Dependencies

- `runtime.llm_client` — read-only consumer (calls `chat()` with structured prompt).
- `runtime.config` — read-only for prober config.
- New SQLite table `agent_probes` — managed by `PersonalOntologyProber` itself (no schema migration tool needed; `CREATE TABLE IF NOT EXISTS`).
- `runtime.event_log` — emits `ONTOLOGY_PROBE_RECORDED` per probe.

All reads from existing surfaces; one new SQLite table owned by AD-487.

## Sections

### Section 0 — EventTypes

- `ONTOLOGY_PROBE_RECORDED` — emitted when a Map probe completes successfully.
- `ONTOLOGY_PROBE_RATE_LIMITED` — emitted when an agent attempts a probe within the 24h window.

Verify no collision with events.py post-Wave-13.

### Section 1 — Create `src/probos/cognitive/self_distillation/` package

- `src/probos/cognitive/self_distillation/__init__.py`
- `src/probos/cognitive/self_distillation/prober.py`

Per Wave 8/9/12 precedents — owns directory creation.

### Section 2 — `ProbeResult` frozen dataclass

```python
@dataclass(frozen=True)
class ProbeResult:
    """Single Map-step probe result. AD-487 v1 surface."""
    agent_id: str
    domain: str  # e.g., "cognitive_psychology", "naval_history", "python_async"
    sub_topics: tuple[str, ...]  # 0-5 sub-topics extracted from LLM response
    confidence_scores: tuple[float, ...]  # 0-5 scores aligned with sub_topics
    raw_text: str  # full LLM response for audit
    probed_at: datetime  # UTC
```

### Section 3 — `PersonalOntologyProber` class

```python
class PersonalOntologyProber:
    """Map-step prober: structured self-queries, rate-limited, persisted.

    AD-487 v1 surface. Collapse + Reduce + daydream deferred to AD-487b/c/d.
    """

    PROBE_TEMPLATE = (
        "You are introspecting on your own knowledge. "
        "Answer in JSON: {{\"sub_topics\": [...up to 5...], \"confidence\": [0.0-1.0 each]}}\n\n"
        "What do you know about {domain}?"
    )

    def __init__(
        self,
        runtime: Any,
        config: SelfDistillationConfig,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._db: ConnectionFactory | None = None  # lazy init via connection_factory
        self._emit_event_fn: Callable[..., None] | None = None
        # Wave 5 convention #1: public attribute set externally; no leading underscore needed if exposed

    async def probe_domain(self, agent_id: str, domain: str) -> ProbeResult:
        """Run a Map-step probe. Rate-limited per (agent, domain, 24h).

        Returns:
            ProbeResult with parsed LLM output. raw_text always populated.

        Raises:
            ProbeRateLimitedError: if probe within 24h window for (agent, domain).
            ProbeLLMError: if LLM call fails after retries.
        """

    async def get_recent_probes(self, agent_id: str, k: int = 10) -> list[ProbeResult]:
        """Return up to k most recent probes for agent, ordered by probed_at desc."""

    async def _check_rate_limit(self, agent_id: str, domain: str) -> bool:
        """True if probe is allowed; False if within 24h window."""

    async def _persist(self, result: ProbeResult) -> None:
        """Write to agent_probes table. Emits ONTOLOGY_PROBE_RECORDED."""

    async def _ensure_schema(self) -> None:
        """CREATE TABLE IF NOT EXISTS agent_probes (...). Idempotent."""
```

SQLite schema:
```sql
CREATE TABLE IF NOT EXISTS agent_probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    sub_topics_json TEXT NOT NULL,
    confidence_scores_json TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    probed_at TEXT NOT NULL  -- ISO 8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_agent_probes_agent_domain
    ON agent_probes(agent_id, domain, probed_at DESC);
```

### Section 4 — Pydantic config

```python
class SelfDistillationConfig(BaseModel):
    """Configuration for AD-487 self-distillation v1 (Map step only)."""
    enabled: bool = True
    rate_limit_hours: int = 24
    llm_timeout_seconds: float = 30.0
    max_sub_topics: int = 5
    db_path: Path = Path("data/agent_probes.db")
```

Wire into `Config.self_distillation` field.

### Section 5 — Runtime wiring (finalize.py)

```python
# AD-487: Self-Distillation v1 (Map step)
sd_cfg = getattr(runtime.config, "self_distillation", None)
if sd_cfg and sd_cfg.enabled:
    runtime.personal_ontology_prober = PersonalOntologyProber(runtime, sd_cfg)
    await runtime.personal_ontology_prober._ensure_schema()
    logger.info(
        "AD-487: PersonalOntologyProber initialized (db=%s; rate_limit_hours=%d)",
        sd_cfg.db_path, sd_cfg.rate_limit_hours,
    )
```

Public attribute (Wave 5 convention #1): `runtime.personal_ontology_prober` — no leading underscore.

## What This Does NOT Change

- No daydreaming in dreaming.py — deferred to AD-487d.
- No Collapse/clustering — deferred to AD-487b.
- No `PersonalOntology` data structure — deferred to AD-487c. v1 stores raw probe results only.
- No DID portability integration — deferred to AD-487e.
- No AD-486 onboarding integration (Phase 3 Self-Discovery) — deferred; AD-487 v1 is callable from anywhere.
- No automatic probe scheduling — caller-driven. Background scheduling is AD-487d's territory.
- LLMClient — read-only consumer; no client modifications.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_ontology_probe_recorded_exists` | Section 0 surface |
| 2 | `test_event_type_ontology_probe_rate_limited_exists` | Section 0 surface |
| 3 | `test_self_distillation_config_defaults` | Pydantic defaults |
| 4 | `test_probe_result_is_frozen_dataclass` | Section 2 contract |
| 5 | `test_ensure_schema_creates_table_and_index` | Schema idempotency |
| 6 | `test_probe_domain_calls_llm_with_template` | LLM call verification (mocked) |
| 7 | `test_probe_domain_parses_json_response` | Happy path: extract sub_topics + confidence |
| 8 | `test_probe_domain_persists_to_db` | DB write verification |
| 9 | `test_probe_domain_emits_recorded_event` | EventType emission |
| 10 | `test_probe_domain_rate_limited_within_24h` | Raises ProbeRateLimitedError + emits ONTOLOGY_PROBE_RATE_LIMITED |
| 11 | `test_probe_domain_allowed_after_24h_window` | Cross-window probe succeeds |
| 12 | `test_probe_domain_handles_malformed_json` | Falls back to empty sub_topics; raw_text preserved |
| 13 | `test_get_recent_probes_returns_descending_order` | Query ordering |
| 14 | `test_get_recent_probes_filters_by_agent_id` | Agent isolation |
| 15 | `test_runtime_attribute_set_when_enabled` | Public-attribute wiring |

Total: ~15 tests.

## Tracking

1. **PROGRESS.md:** prepend AD-487 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-487: Self-Distillation v1 — Personal Ontology Map Step (2026-05-03)

**Problem:** LLMs don't know what they know without prompting. Agents need systematic knowledge-domain inventory to build personal ontologies (capability map, not library copy). Roadmap describes 3-stage map-reduce + daydreaming + DID portability — too much for one wave.

**Decision:** v1 ships ONLY the Map step. `PersonalOntologyProber.probe_domain(agent_id, domain)` calls LLM with structured self-query template, parses JSON response into `ProbeResult` (sub_topics + confidence_scores), persists to new `agent_probes` SQLite table, rate-limited per (agent, domain, 24h). Emits ONTOLOGY_PROBE_RECORDED + ONTOLOGY_PROBE_RATE_LIMITED.

**Why:** Map step has clean surface (LLM call + parse + persist). Collapse/Reduce need accumulated probes to be useful — premature without Map data. Daydreaming needs dreaming.py bandwidth slot (separate scope). DID portability needs ontology data structure (depends on Reduce). Convention #14 aggressive pre-deferral applied.

**Deferred:**
- AD-487b: Collapse — cluster probes into capability categories. Ships when ≥10 probes accumulate per agent.
- AD-487c: Reduce — PersonalOntology data structure. Depends on AD-487b.
- AD-487d: Daydream dream type — idle-cycle exploration. Ships when AD-487a/b/c stable + dreaming.py bandwidth.
- AD-487e: DID portability integration (AD-441). Depends on AD-487c.

**Cross-links:** AD-486 (onboarding Phase 3 Self-Discovery — eventual consumer), AD-441 (DID portability — eventual consumer), dreaming.py (eventual daydream slot), LLMClient (read-only consumer).
```

3. **docs/development/roadmap.md:** flip AD-487 status to `partial — v1 ships Map step (PersonalOntologyProber + agent_probes table); Collapse/Reduce/Daydream/DID-portability deferred to AD-487b/c/d/e`.

## Verified Against Codebase (2026-05-03)

```
grep -n "class LLMClient\|async def chat\|def chat" src/probos/cognitive/llm_client.py
  (Builder verifies LLMClient.chat signature at build time)

grep -n "ConnectionFactory\|connection_factory" src/probos/protocols.py
  (Builder verifies SQLite ConnectionFactory protocol — Wave 5 convention #2 stdlib-only persistence)

grep -n "class Config\b" src/probos/config.py
  (Builder verifies adding self_distillation: SelfDistillationConfig field)
```

## Acceptance Criteria

- `src/probos/cognitive/self_distillation/` package exists.
- `PersonalOntologyProber` + `ProbeResult` ship as described.
- Public attribute `runtime.personal_ontology_prober` (no underscore) per Wave 5 convention #1.
- 2 new EventTypes (`ONTOLOGY_PROBE_RECORDED`, `ONTOLOGY_PROBE_RATE_LIMITED`).
- `SelfDistillationConfig` Pydantic class wired into `Config`.
- `agent_probes` SQLite table created idempotently via `_ensure_schema()`.
- 15 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #79 closes when commit lands.

## Hard-Stops

- LLMClient.chat signature differs from assumption (Builder verifies at build time) — surface; may need adapter.
- ConnectionFactory protocol doesn't expose async cursor pattern matching v1 needs — surface; defer schema persistence.
- Existing `agent_probes` table exists from prior partial work — surface; verify schema compat.
- Rate-limit logic conflicts with global LLM rate-limit infrastructure (AD-636 priority scheduling, AD-637f) — surface; may need integration not standalone limiter.
