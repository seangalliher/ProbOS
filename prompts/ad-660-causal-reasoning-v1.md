# AD-660 v1: Agent Causal Reasoning Framework (TEMPLATE + JOURNAL + INTEGRATION POINT)

**Closes:** #319. Standalone wave (depends on AD-504 SelfMonitoringConcernEvent surface and AD-557 emergence metrics — both shipped).

**Hard limit:** v1 ships **template + journal storage + opt-in integration point ONLY**. There is **NO automatic causal inference engine** — the LLM fills the four-step template; ProbOS does NOT compute causal structure or rank hypotheses. The integration call-site is gated by `CausalReasoningConfig.enabled` (default `False`), so out of the box AD-660 is observational scaffolding. Action execution, hypothesis ranking, automatic invocation on every concern, and any inference engine are explicitly deferred to AD-660b/c.

## Scope (v1)

A structured causal reasoning template that agents fill out when encountering unexpected outcomes, persisted alongside chain traces in the existing `CognitiveJournal`.

**v1 Deliverables:**

1. `CausalReasoningTemplate` **frozen** dataclass with the four research-paper steps + provenance fields.
2. `CausalReasoner` service with `analyze(trigger, context)` that calls the standard-tier LLM with a structured prompt and parses JSON into the template. Degrades to an empty template on parse failure.
3. `CognitiveJournal.record_causal_template()` + `get_recent_causal_templates()` mirroring the chain-trace persistence shape (new `causal_templates` table, INSERT OR IGNORE, prune-aware).
4. `CausalReasoningConfig` Pydantic config (`enabled: bool = False`).
5. `runtime.causal_reasoner` public attribute + finalize wirer mirroring `_wire_chain_optimizer`.
6. **Integration POINT** in `counselor._on_self_monitoring_concern`: a guarded call-site clearly marked with AD-660. With `enabled=False`, the path is a no-op. With `enabled=True`, the reasoner runs against the concern payload.

**Not in v1 (deferred):** automatic invocation across all concern paths; inference engine; hypothesis ranking; diagnostic-action execution; integration with AD-557 emergence-metrics events (groupthink/fragmentation warnings); cross-agent causal correlation; dedup; chain-trace co-correlation.

---

## Section 0: New Symbols Introduced By This Prompt

These do NOT exist at HEAD. The phantom-API pre-check correctly flags them (treated as FPs).

- `CausalReasoningTemplate` — Section 2 (NEW frozen dataclass)
- `CausalReasoner` — Section 3 (NEW service class)
- `CausalReasoner.analyze(trigger, context)` — Section 3
- `CausalReasoner.analyze_concern(concern_data)` — Section 3
- `CognitiveJournal.record_causal_template()` — Section 4
- `CognitiveJournal.get_recent_causal_templates()` — Section 4
- `causal_templates` SQLite table — Section 4 schema
- `CausalReasoningConfig` — Section 5 (NEW Pydantic class)
- `runtime.causal_reasoner` public attribute — Section 6 wirer
- `_wire_causal_reasoner` — Section 6
- AD-660 hook in `counselor._on_self_monitoring_concern` — Section 7

---

## Section 1: Verified Against Codebase (HEAD: post-Wave-31, commit at draft time)

```text
# AD-504/506a self-monitoring concern surface
grep -n "SELF_MONITORING_CONCERN" src/probos/events.py
  127: SELF_MONITORING_CONCERN = "self_monitoring_concern"  # AD-506a: amber zone
  672: class SelfMonitoringConcernEvent(BaseEvent):
  674:     event_type: EventType = field(default=EventType.SELF_MONITORING_CONCERN, init=False)

grep -n "SELF_MONITORING_CONCERN" src/probos/cognitive/counselor.py
  677:   EventType.SELF_MONITORING_CONCERN,  # AD-506a
  889:   elif event_type == EventType.SELF_MONITORING_CONCERN.value:
  890:       await self._on_self_monitoring_concern(data)
  979:   async def _on_self_monitoring_concern(self, data: dict[str, Any]) -> None:

# Journal pattern to mirror (AD-658 chain_traces)
grep -n "_SCHEMA_CHAIN_TRACES\|record_chain_trace\|get_recent_chain_traces" src/probos/cognitive/journal.py
  55: _SCHEMA_CHAIN_TRACES = """
  56: CREATE TABLE IF NOT EXISTS chain_traces (
  128:    await self._db.executescript(_SCHEMA_CHAIN_TRACES)
  164:    # AD-658: extend retention to chain_traces
  185:    # AD-658: row-count cap on chain_traces
  257:    async def record_chain_trace(self, trace: Any) -> None:
  295:    async def get_recent_chain_traces(

# Wirer to mirror (AD-659)
grep -n "_wire_chain_optimizer\|_wire_duty_scope_provider" src/probos/startup/finalize.py
  200: def _wire_duty_scope_provider(*, runtime: Any, config: "SystemConfig") -> bool:
  214: def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
  517:    if _wire_chain_optimizer(runtime=runtime, config=config):

# Config to mirror
grep -n "ChainOptimizerConfig\|chain_optimizer:" src/probos/config.py
  336: class ChainOptimizerConfig(BaseModel):
  2019:    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659

# LLM-fill / JSON-parse pattern
grep -n "extract_json\|complete(request)" src/probos/cognitive/sub_tasks/evaluate.py
  20: from probos.utils.json_extract import extract_json
  638:    response = await self._llm_client.complete(request)
  661:    parsed = extract_json(content)

grep -n "class LLMRequest\|class LLMResponse" src/probos/types.py
  227: class LLMRequest:
  240: class LLMResponse:

# Runtime LLM client surface
grep -n "self.llm_client" src/probos/runtime.py
  346:    self.llm_client: BaseLLMClient = llm_client or MockLLMClient()
```

Every concrete claim below maps back to one of those greps.

---

## Section 2: New Module — `src/probos/cognitive/causal_reasoning.py`

CREATE new file. The dataclass is **frozen** (immutable artifact like an episode); `confidence: float` is the LLM's self-reported confidence in its own causal account, not an inference-engine score.

```python
"""Causal Reasoning Framework — structured metacognitive template (AD-660 v1).

Agents (or system services on their behalf) fill a four-step causal-reasoning
template when an unexpected outcome triggers analysis:

    1. what_changed             — observable deltas from baseline
    2. confounded_variables     — overlapping changes that cannot be cleanly isolated
    3. testable_hypotheses      — falsifiable explanations
    4. diagnostic_actions       — concrete next steps to discriminate hypotheses

v1 is TEMPLATE + STORAGE + INTEGRATION POINT only — there is no causal-inference
engine. The LLM fills the template; ProbOS persists the artifact. Hypothesis
ranking, action execution, and automatic invocation are deferred to AD-660b/c.

Built on AD-504 SelfMonitoringConcernEvent surface and AD-557 emergence
metrics as the trigger sources, but v1 only wires AD-504 (counselor concern
hook). AD-557 wiring is AD-660b.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


_MAX_LIST_LEN = 8           # cap each step's list length post-parse
_MAX_FIELD_CHARS = 500      # truncate any single bullet


@dataclass(frozen=True)
class CausalReasoningTemplate:
    """Structured causal-reasoning artifact (AD-660 v1).

    Immutable record of one analysis pass. The four list fields correspond
    to the Lee et al. (arXiv:2603.28052) Meta-Harness proposer's four-step
    causal-reasoning protocol.
    """

    template_id: str
    agent_id: str
    triggered_at: datetime
    trigger_summary: str
    what_changed: list[str]
    confounded_variables: list[str]
    testable_hypotheses: list[str]
    diagnostic_actions: list[str]
    confidence: float                         # 0.0–1.0; LLM's self-reported confidence
    source_event_ref: str | None = None       # opt. correlation id / event token

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ISO-format datetime for JSON-friendly storage / API
        d["triggered_at"] = self.triggered_at.isoformat()
        return d


_SYSTEM_PROMPT = """You are a metacognitive analyst helping an autonomous agent
diagnose an unexpected outcome. Fill the four-step causal reasoning template.

Return ONLY a JSON object with these exact keys (lists may be empty if you
genuinely have no hypothesis to offer — do NOT pad):

{
  "what_changed": ["short bullets of observable deltas from baseline"],
  "confounded_variables": ["overlapping changes that cannot be cleanly isolated"],
  "testable_hypotheses": ["falsifiable explanations of the unexpected outcome"],
  "diagnostic_actions": ["concrete next steps to discriminate hypotheses"],
  "confidence": 0.0
}

confidence is your self-reported confidence in your own causal account
(0.0 = guessing, 1.0 = strong evidence). Do NOT fabricate. If context is
sparse, return short lists and low confidence."""


def _coerce_list(raw: Any) -> list[str]:
    """Normalize an LLM-returned list field. Truncates length and per-item chars."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw[:_MAX_LIST_LEN]:
        if not isinstance(item, str):
            item = str(item)
        out.append(item[:_MAX_FIELD_CHARS])
    return out


def _coerce_confidence(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _empty_template(
    *,
    agent_id: str,
    trigger_summary: str,
    source_event_ref: str | None,
) -> CausalReasoningTemplate:
    """Degraded template — used when the LLM returns unparseable output."""
    return CausalReasoningTemplate(
        template_id=uuid.uuid4().hex[:16],
        agent_id=agent_id,
        triggered_at=datetime.now(timezone.utc),
        trigger_summary=trigger_summary[:_MAX_FIELD_CHARS],
        what_changed=[],
        confounded_variables=[],
        testable_hypotheses=[],
        diagnostic_actions=[],
        confidence=0.0,
        source_event_ref=source_event_ref,
    )


class CausalReasoner:
    """Fill a CausalReasoningTemplate via the LLM (AD-660 v1).

    v1 is on-demand only — no background loop, no automatic invocation
    across concern paths. Caller decides when to invoke. The integration
    point in counselor._on_self_monitoring_concern is gated by
    CausalReasoningConfig.enabled (default False).
    """

    def __init__(
        self,
        runtime: Any,
        *,
        max_tokens: int = 700,
        tier: str = "standard",
    ) -> None:
        self._runtime = runtime
        self._max_tokens = max_tokens
        self._tier = tier

    async def analyze(
        self,
        *,
        trigger: str,
        agent_id: str,
        context: dict[str, Any] | None = None,
        source_event_ref: str | None = None,
    ) -> CausalReasoningTemplate:
        """Run one causal-reasoning pass via the LLM.

        Returns a CausalReasoningTemplate. On any LLM failure or JSON-parse
        failure, returns a degraded (empty-list, confidence=0.0) template.
        Never raises.
        """
        ctx_json = ""
        if context:
            try:
                # Best-effort serialization; truncated for prompt-budget safety.
                ctx_json = json.dumps(context, default=str)[:4000]
            except (TypeError, ValueError):
                ctx_json = ""
        user_prompt = (
            f"Trigger:\n{trigger[:1500]}\n\n"
            f"Context (JSON):\n{ctx_json}\n\n"
            "Fill the four-step causal reasoning template now."
        )

        llm_client = getattr(self._runtime, "llm_client", None)
        if llm_client is None:
            logger.debug("AD-660: causal_reasoner has no llm_client; degraded.")
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_SYSTEM_PROMPT,
            tier=self._tier,
            temperature=0.0,
            max_tokens=self._max_tokens,
        )
        try:
            response = await llm_client.complete(request)
        except Exception:
            logger.warning("AD-660: causal_reasoner LLM call failed", exc_info=True)
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None
        if not isinstance(parsed, dict):
            logger.debug(
                "AD-660: causal_reasoner JSON parse failed (%d chars); degraded.",
                len(content),
            )
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        return CausalReasoningTemplate(
            template_id=uuid.uuid4().hex[:16],
            agent_id=agent_id,
            triggered_at=datetime.now(timezone.utc),
            trigger_summary=trigger[:_MAX_FIELD_CHARS],
            what_changed=_coerce_list(parsed.get("what_changed")),
            confounded_variables=_coerce_list(parsed.get("confounded_variables")),
            testable_hypotheses=_coerce_list(parsed.get("testable_hypotheses")),
            diagnostic_actions=_coerce_list(parsed.get("diagnostic_actions")),
            confidence=_coerce_confidence(parsed.get("confidence")),
            source_event_ref=source_event_ref,
        )

    async def analyze_concern(
        self, concern_data: dict[str, Any],
    ) -> CausalReasoningTemplate | None:
        """Convenience: run analyze() against an AD-504 concern payload.

        Returns None if the payload lacks an agent_id (defensive — a malformed
        concern event must not crash the integration point).
        """
        agent_id = concern_data.get("agent_id") or ""
        if not agent_id:
            return None
        callsign = concern_data.get("agent_callsign", agent_id[:8])
        zone = concern_data.get("zone", "amber")
        sim = concern_data.get("similarity_ratio", 0.0)
        vel = concern_data.get("velocity_ratio", 0.0)
        trigger = (
            f"Agent {callsign} entered {zone} zone — "
            f"similarity_ratio={sim:.2f}, velocity_ratio={vel:.2f}. "
            "Diagnose the unexpected behavior change."
        )
        # Persist a lightweight correlation token so analyst can join with the
        # original event downstream. v1 has no real correlation_id surface.
        source_event_ref = f"self_monitoring_concern:{agent_id}"
        return await self.analyze(
            trigger=trigger,
            agent_id=agent_id,
            context={
                "zone": zone,
                "similarity_ratio": sim,
                "velocity_ratio": vel,
                "callsign": callsign,
            },
            source_event_ref=source_event_ref,
        )
```

---

## Section 3: Journal Storage — extend `src/probos/cognitive/journal.py`

Mirror the AD-658 chain_traces shape exactly. Three changes:

### 3a. Add table schema constant after `_SCHEMA_CHAIN_TRACES` (around line 87):

```search
CREATE INDEX IF NOT EXISTS idx_chain_traces_chain_id ON chain_traces(chain_id);
"""


class CognitiveJournal:
```

```replace
CREATE INDEX IF NOT EXISTS idx_chain_traces_chain_id ON chain_traces(chain_id);
"""

_SCHEMA_CAUSAL_TEMPLATES = """
CREATE TABLE IF NOT EXISTS causal_templates (
    template_id         TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL DEFAULT '',
    triggered_at        REAL NOT NULL DEFAULT 0.0,
    trigger_summary     TEXT NOT NULL DEFAULT '',
    what_changed        TEXT NOT NULL DEFAULT '[]',
    confounded_variables TEXT NOT NULL DEFAULT '[]',
    testable_hypotheses TEXT NOT NULL DEFAULT '[]',
    diagnostic_actions  TEXT NOT NULL DEFAULT '[]',
    confidence          REAL NOT NULL DEFAULT 0.0,
    source_event_ref    TEXT
);

CREATE INDEX IF NOT EXISTS idx_causal_templates_triggered_at ON causal_templates(triggered_at);
CREATE INDEX IF NOT EXISTS idx_causal_templates_agent ON causal_templates(agent_id);
"""


class CognitiveJournal:
```

### 3b. Schema execution — extend `start()` (after the chain_traces executescript at line 128):

```search
        # AD-658: chain harness traces (separate from per-LLM-call journal rows)
        await self._db.executescript(_SCHEMA_CHAIN_TRACES)

    async def stop(self) -> None:
```

```replace
        # AD-658: chain harness traces (separate from per-LLM-call journal rows)
        await self._db.executescript(_SCHEMA_CHAIN_TRACES)
        # AD-660: causal-reasoning templates
        await self._db.executescript(_SCHEMA_CAUSAL_TEMPLATES)

    async def stop(self) -> None:
```

### 3c. Prune extension — extend the chain_traces row-count cap block (around line 199):

```search
                cursor = await self._db.execute(
                    "DELETE FROM chain_traces WHERE rowid IN "
                    "(SELECT rowid FROM chain_traces ORDER BY started_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("CognitiveJournal pruned: %d entries removed", deleted)

        return deleted
```

```replace
                cursor = await self._db.execute(
                    "DELETE FROM chain_traces WHERE rowid IN "
                    "(SELECT rowid FROM chain_traces ORDER BY started_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount

        # AD-660: extend retention + row-cap to causal_templates
        if retention_days > 0:
            cursor = await self._db.execute(
                "DELETE FROM causal_templates WHERE triggered_at < ?", (cutoff,)
            )
            deleted += cursor.rowcount
        if max_rows > 0:
            cursor = await self._db.execute("SELECT COUNT(*) FROM causal_templates")
            row = await cursor.fetchone()
            total_templates = row[0] if row else 0
            if total_templates > max_rows:
                excess = total_templates - max_rows
                cursor = await self._db.execute(
                    "DELETE FROM causal_templates WHERE rowid IN "
                    "(SELECT rowid FROM causal_templates ORDER BY triggered_at ASC LIMIT ?)",
                    (excess,),
                )
                deleted += cursor.rowcount

        if deleted > 0:
            await self._db.commit()
            logger.info("CognitiveJournal pruned: %d entries removed", deleted)

        return deleted
```

### 3d. Add `record_causal_template` + `get_recent_causal_templates` AFTER `get_recent_chain_traces` (immediately before `get_reasoning_chain` at line ~330):

```search
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []

    async def get_reasoning_chain(
```

```replace
            return [dict(row) for row in rows]
        except Exception:
            logger.debug("Chain trace query failed", exc_info=True)
            return []

    async def record_causal_template(self, template: Any) -> None:
        """AD-660: Persist a CausalReasoningTemplate. Fire-and-forget — never raises.

        Accepts any object exposing the CausalReasoningTemplate field set
        via attribute lookup. List fields are JSON-serialized; triggered_at
        is stored as Unix-epoch float (datetime.timestamp()). Conflict on
        template_id is silently dropped via INSERT OR IGNORE.
        """
        if not self._db:
            return
        try:
            triggered_ts = template.triggered_at.timestamp()
            await self._db.execute(
                """INSERT OR IGNORE INTO causal_templates
                   (template_id, agent_id, triggered_at, trigger_summary,
                    what_changed, confounded_variables, testable_hypotheses,
                    diagnostic_actions, confidence, source_event_ref)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    template.template_id,
                    template.agent_id,
                    triggered_ts,
                    template.trigger_summary,
                    __import__("json").dumps(template.what_changed),
                    __import__("json").dumps(template.confounded_variables),
                    __import__("json").dumps(template.testable_hypotheses),
                    __import__("json").dumps(template.diagnostic_actions),
                    float(template.confidence),
                    template.source_event_ref,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.debug("Causal template record failed", exc_info=True)

    async def get_recent_causal_templates(
        self,
        *,
        limit: int = 50,
        agent_id: str | None = None,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """AD-660: Return recent causal templates, most recent first.

        Args:
            limit: Max rows.
            agent_id: Optional filter by agent.
            since: Optional Unix-timestamp lower bound on triggered_at.

        List fields are returned JSON-decoded back to list[str].
        """
        if not self._db:
            return []
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if agent_id is not None:
                clauses.append("agent_id = ?")
                params.append(agent_id)
            if since is not None:
                clauses.append("triggered_at >= ?")
                params.append(since)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            cursor = await self._db.execute(
                f"SELECT * FROM causal_templates {where} ORDER BY triggered_at DESC LIMIT ?",
                params,
            )
            rows = await cursor.fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = __import__("json").loads(raw) if isinstance(raw, str) else []
                    except (ValueError, TypeError):
                        d[key] = []
                out.append(d)
            return out
        except Exception:
            logger.debug("Causal template query failed", exc_info=True)
            return []

    async def get_reasoning_chain(
```

> **Builder note:** the `__import__("json")` idiom matches the existing nearby code style and avoids touching the import block. If you prefer to add `import json` at the top (the file already has `import sqlite3`/`import time`), that is acceptable but keep it a single edit. Do NOT add other unrelated imports.

---

## Section 4: Config — extend `src/probos/config.py`

### 4a. Add `CausalReasoningConfig` IMMEDIATELY AFTER `ChainOptimizerConfig` (after config.py:342, before `class StepInstructionConfig`):

```search
class ChainOptimizerConfig(BaseModel):
    """AD-659 v1: Cognitive Chain Self-Optimization analysis service.

    v1 is analysis-only — produces OptimizationProposal instances which
    require Captain approval. apply_proposal() raises NotImplementedError;
    automatic application is deferred to AD-659b.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20


class StepInstructionConfig(BaseModel):
```

```replace
class ChainOptimizerConfig(BaseModel):
    """AD-659 v1: Cognitive Chain Self-Optimization analysis service.

    v1 is analysis-only — produces OptimizationProposal instances which
    require Captain approval. apply_proposal() raises NotImplementedError;
    automatic application is deferred to AD-659b.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20


class CausalReasoningConfig(BaseModel):
    """AD-660 v1: Agent Causal Reasoning Framework.

    v1 ships the four-step causal-reasoning template + journal storage +
    one opt-in integration point in counselor's amber-zone handler. The
    LLM fills the template; ProbOS persists it. There is no inference
    engine, no automatic invocation, no action execution.

    Disabled by default — enable to activate the counselor concern hook.
    """

    enabled: bool = False  # opt-in until validated
    max_tokens: int = 700
    tier: str = "standard"


class StepInstructionConfig(BaseModel):
```

### 4b. Register on `SystemConfig` IMMEDIATELY AFTER the `chain_optimizer` field (config.py:2019):

```search
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
```

```replace
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
```

> If `config.py:2019` has slightly different surrounding text at build time (e.g., a sibling field landed first), keep the AD-660 field immediately adjacent to the AD-659 field. Order MUST be `chain_optimizer` then `causal_reasoning`.

---

## Section 5: Wirer — extend `src/probos/startup/finalize.py`

### 5a. Add `_wire_causal_reasoner` IMMEDIATELY AFTER `_wire_chain_optimizer` (after finalize.py:237):

```search
def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1: Wire ChainOptimizer analysis-only proposal service."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.chain_optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-659: ChainOptimizer v1 initialized "
        "(analysis-only; apply path deferred to AD-659b)"
    )
    return True
```

```replace
def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1: Wire ChainOptimizer analysis-only proposal service."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.chain_optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-659: ChainOptimizer v1 initialized "
        "(analysis-only; apply path deferred to AD-659b)"
    )
    return True


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
```

### 5b. Invoke the wirer (after the `_wire_chain_optimizer` call at finalize.py:517):

```search
    if _wire_chain_optimizer(runtime=runtime, config=config):
```

> **Builder note:** read the surrounding 5 lines. The pattern is `if _wire_X(runtime=runtime, config=config):` followed by a block (likely `wired += 1` / `pass` / similar). Mirror that block exactly. Insert the new call immediately after the existing one.

```replace
    if _wire_chain_optimizer(runtime=runtime, config=config):
```

> *(actual SEARCH/REPLACE for 5b: extend by one line — keep the existing block body intact. If the existing block is a single statement, simply add the AD-660 call as a sibling `if` after it. If the call is `if _wire_chain_optimizer(...):  # noqa` or has post-call body, keep that body and append the new `if _wire_causal_reasoner(...):` with identical body shape. The Builder must verify the actual block at HEAD before editing.)*

---

## Section 6: Integration POINT — `src/probos/cognitive/counselor.py`

ONE guarded block inserted into `_on_self_monitoring_concern` (counselor.py:979 region). The hook is FIRE-AND-FORGET — must NOT raise into the existing counselor path (which already does its own clinical assessment).

```search
        # Persist to profile
        await self._save_profile_and_assessment(agent_id, assessment)

        # No DM, no intervention — amber is informational for the Counselor.
        # She tracks the pattern. If it escalates to red, _on_circuit_breaker_trip handles it.
```

```replace
        # Persist to profile
        await self._save_profile_and_assessment(agent_id, assessment)

        # AD-660: Opt-in causal reasoning hook.
        # Fires only when CausalReasoningConfig.enabled (default False).
        # Records a CausalReasoningTemplate alongside the chain traces.
        # Fire-and-forget — must NOT raise into the existing counselor path.
        try:
            reasoner = getattr(self._runtime, "causal_reasoner", None)
            journal = getattr(self._runtime, "cognitive_journal", None)
            if reasoner is not None:
                template = await reasoner.analyze_concern(data)
                if template is not None and journal is not None:
                    await journal.record_causal_template(template)
        except Exception:
            logger.debug("AD-660: causal_reasoner concern hook failed", exc_info=True)

        # No DM, no intervention — amber is informational for the Counselor.
        # She tracks the pattern. If it escalates to red, _on_circuit_breaker_trip handles it.
```

> **Builder note:** verify Counselor has `self._runtime` (or equivalent) at HEAD. If the field is named differently (e.g. `self.runtime`), adjust the `getattr` argument. The pattern of `getattr(self._runtime, "X", None)` is the same as elsewhere in counselor.py — grep for `self._runtime` first to confirm.

---

## Section 7: Tests — `tests/test_ad660_causal_reasoning.py`

CREATE new test file. Eight focused tests — one above the seven floor.

```python
"""AD-660 v1: Agent Causal Reasoning Framework — focused unit tests."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.causal_reasoning import (
    CausalReasoner,
    CausalReasoningTemplate,
)
from probos.cognitive.journal import CognitiveJournal


# ----- Test 1: dataclass shape -------------------------------------------------

def test_template_is_frozen_and_round_trips_to_dict() -> None:
    t = CausalReasoningTemplate(
        template_id="abc123",
        agent_id="agent-1",
        triggered_at=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        trigger_summary="Latency spiked",
        what_changed=["new prompt", "new tier"],
        confounded_variables=["both shipped same day"],
        testable_hypotheses=["prompt change caused regression"],
        diagnostic_actions=["roll back prompt only"],
        confidence=0.7,
        source_event_ref="self_monitoring_concern:agent-1",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        t.confidence = 0.9  # type: ignore[misc]
    d = t.to_dict()
    assert d["template_id"] == "abc123"
    assert d["confidence"] == 0.7
    assert d["what_changed"] == ["new prompt", "new tier"]
    assert d["triggered_at"] == "2026-05-04T12:00:00+00:00"
    assert d["source_event_ref"] == "self_monitoring_concern:agent-1"


# ----- Test 2: happy path — synthetic LLM JSON -------------------------------

@pytest.mark.asyncio
async def test_analyze_happy_path_with_synthetic_llm_output() -> None:
    fake_response = SimpleNamespace(content=json.dumps({
        "what_changed": ["modulation_v2 enabled", "tier=fast forced"],
        "confounded_variables": ["both rolled out same dream cycle"],
        "testable_hypotheses": ["fast tier insufficient for evaluate step"],
        "diagnostic_actions": ["pin tier=standard for evaluate; re-run"],
        "confidence": 0.6,
    }))
    fake_llm = SimpleNamespace(complete=AsyncMock(return_value=fake_response))
    runtime = SimpleNamespace(llm_client=fake_llm)
    reasoner = CausalReasoner(runtime)

    template = await reasoner.analyze(
        trigger="Evaluate latency p95 doubled",
        agent_id="science-1",
        context={"step": "evaluate", "tier": "fast"},
        source_event_ref="evt:abc",
    )

    assert template.agent_id == "science-1"
    assert template.confidence == 0.6
    assert "modulation_v2 enabled" in template.what_changed
    assert template.testable_hypotheses == [
        "fast tier insufficient for evaluate step"
    ]
    assert template.source_event_ref == "evt:abc"
    fake_llm.complete.assert_awaited_once()


# ----- Test 3: degraded path — JSON parse failure ----------------------------

@pytest.mark.asyncio
async def test_analyze_returns_degraded_template_on_parse_failure() -> None:
    fake_response = SimpleNamespace(content="<no JSON here, just prose>")
    fake_llm = SimpleNamespace(complete=AsyncMock(return_value=fake_response))
    runtime = SimpleNamespace(llm_client=fake_llm)
    reasoner = CausalReasoner(runtime)

    template = await reasoner.analyze(
        trigger="Unknown failure",
        agent_id="medical-1",
    )
    assert template.agent_id == "medical-1"
    assert template.what_changed == []
    assert template.confounded_variables == []
    assert template.testable_hypotheses == []
    assert template.diagnostic_actions == []
    assert template.confidence == 0.0


# ----- Test 4: journal round-trip --------------------------------------------

@pytest.mark.asyncio
async def test_journal_record_and_retrieve_round_trip(tmp_path: Path) -> None:
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        t = CausalReasoningTemplate(
            template_id="rt-1",
            agent_id="ops-1",
            triggered_at=datetime.now(timezone.utc),
            trigger_summary="trip",
            what_changed=["a", "b"],
            confounded_variables=["c"],
            testable_hypotheses=["h1", "h2"],
            diagnostic_actions=["d1"],
            confidence=0.4,
            source_event_ref="evt:ops",
        )
        await journal.record_causal_template(t)
        rows = await journal.get_recent_causal_templates(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["template_id"] == "rt-1"
        assert row["agent_id"] == "ops-1"
        assert row["what_changed"] == ["a", "b"]
        assert row["testable_hypotheses"] == ["h1", "h2"]
        assert row["confidence"] == 0.4
        assert row["source_event_ref"] == "evt:ops"
    finally:
        await journal.stop()


# ----- Test 5: agent_id filter -----------------------------------------------

@pytest.mark.asyncio
async def test_journal_get_recent_filters_by_agent_id(tmp_path: Path) -> None:
    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        for i, aid in enumerate(["a1", "a2", "a1"]):
            t = CausalReasoningTemplate(
                template_id=f"f-{i}",
                agent_id=aid,
                triggered_at=datetime.now(timezone.utc),
                trigger_summary="trig",
                what_changed=[],
                confounded_variables=[],
                testable_hypotheses=[],
                diagnostic_actions=[],
                confidence=0.0,
            )
            await journal.record_causal_template(t)
        only_a1 = await journal.get_recent_causal_templates(limit=10, agent_id="a1")
        assert {r["agent_id"] for r in only_a1} == {"a1"}
        assert len(only_a1) == 2
    finally:
        await journal.stop()


# ----- Test 6: analyze_concern degrades on missing agent_id ------------------

@pytest.mark.asyncio
async def test_analyze_concern_returns_none_on_missing_agent_id() -> None:
    runtime = SimpleNamespace(llm_client=SimpleNamespace(complete=AsyncMock()))
    reasoner = CausalReasoner(runtime)
    result = await reasoner.analyze_concern({"zone": "amber"})
    assert result is None
    runtime.llm_client.complete.assert_not_awaited()


# ----- Test 7: integration point — disabled config = no-op -------------------

def test_wirer_skips_when_config_disabled() -> None:
    """AD-660: _wire_causal_reasoner returns False when config disabled."""
    from probos.config import CausalReasoningConfig, SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    assert sys_cfg.causal_reasoning.enabled is False  # default
    runtime = SimpleNamespace()
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is False
    assert not hasattr(runtime, "causal_reasoner")


# ----- Test 8: integration point — enabled config = wired + reasoner runs ----

@pytest.mark.asyncio
async def test_wirer_creates_runtime_attribute_when_enabled() -> None:
    """AD-660: _wire_causal_reasoner sets runtime.causal_reasoner when enabled."""
    from probos.config import CausalReasoningConfig, SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    sys_cfg.causal_reasoning = CausalReasoningConfig(enabled=True)
    runtime = SimpleNamespace(llm_client=SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="{}")),
    ))
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is True
    assert isinstance(runtime.causal_reasoner, CausalReasoner)
    # Smoke: analyze_concern with valid payload returns a (degraded but real) template.
    template = await runtime.causal_reasoner.analyze_concern(
        {"agent_id": "a1", "agent_callsign": "alpha", "zone": "amber",
         "similarity_ratio": 0.9, "velocity_ratio": 1.2}
    )
    assert template is not None
    assert template.agent_id == "a1"
    assert template.confidence == 0.0  # empty JSON `{}` → degraded
```

---

## What This Does NOT Change

- **No causal-inference engine.** The LLM fills the four-step template; ProbOS does not compute do-calculus, structural equation models, counterfactuals, or anything that resembles causal *inference*. The artifact is a structured *narrative* of causal reasoning, not a graph.
- **No automatic invocation.** The integration point is exactly ONE call-site (counselor amber-zone handler) gated by `CausalReasoningConfig.enabled`. Out of the box, `enabled=False` makes the entire framework a no-op. AD-557 emergence-event integration (groupthink/fragmentation warnings) is deferred to AD-660b.
- **No hypothesis ranking.** The `testable_hypotheses` list is whatever the LLM returned, in LLM-returned order. No scoring, no de-dup, no priors.
- **No diagnostic-action execution.** `diagnostic_actions` is text only. Nothing runs. AD-660c will optionally surface them as Captain-actionable proposals (mirroring the AD-659 OptimizationProposal pattern).
- **No new EventType.** The reasoner does not emit; consumers read the journal. AD-660b may add `CAUSAL_TEMPLATE_RECORDED` if downstream signals justify it.
- **No persistence beyond the new SQLite table.** No ChromaDB, no S3, no Git knowledge store integration.
- **No retroactive backfill.** Concerns that fired before AD-660 v1 ships are not re-analyzed.
- **No API endpoint.** Read access via `runtime.cognitive_journal.get_recent_causal_templates()` only. `/api/causal-templates` is AD-660b.
- **No HXI surface.** Templates are not rendered into the Captain's Bridge or HXI dashboard.
- **No counselor logic changes.** The hook does not influence the existing assessment, profile-save, or zone-recovery flows. It runs after `_save_profile_and_assessment` strictly as a side-channel.
- **No `ChainOptimizer` integration.** Causal templates and optimization proposals are independent artifacts in v1. AD-660d may join them on `source_event_ref`.

---

## Tracking

- **PROGRESS.md** — append a closure entry summarising the deliverables (template, journal, config, wirer, hook), the test count delta (target +8), and the explicit deferrals (660b: AD-557 hook + automatic invocation + API; 660c: action proposals; 660d: optimizer join).
- **docs/development/roadmap.md** — flip AD-660 entry from `*(Future)*` to `*(Complete v1, OSS, Issue #319)*`. Add forward-refs for AD-660b/c/d.
- **DECISIONS.md** — no new entry. v1 is a scaffolding AD; AD-660b crosses the threshold for a decision entry when it adds the AD-557 hook + API.

---

## Acceptance Criteria

- All 8 new tests in `tests/test_ad660_causal_reasoning.py` pass at `-n 0`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` shows delta of `+8` (or `+7` if Test 1 frozen-check is collapsed; flag in build report) over Wave 31 baseline of **10935 passed**.
- `CausalReasoningTemplate` is `@dataclass(frozen=True)` (mutating fields raises).
- `CausalReasoner.analyze()` and `.analyze_concern()` NEVER raise — both degrade to empty/None on any failure path (LLM error, JSON parse, missing agent_id).
- `CognitiveJournal.record_causal_template()` and `.get_recent_causal_templates()` follow the AD-658 chain-trace persistence pattern: INSERT OR IGNORE, fire-and-forget, prune-aware.
- `CausalReasoningConfig.enabled` defaults to `False`. With the default config, `runtime.causal_reasoner` is NOT created and the counselor hook is a no-op.
- The counselor hook is wrapped in `try/except logger.debug(...)` so it cannot break the existing `_on_self_monitoring_concern` flow.
- The new `causal_templates` table is created in `CognitiveJournal.start()` and pruned in `prune()` — both age-based and row-cap branches.
- No new EventType. No new API router. No HXI changes.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Standing Conventions Confirmed

- **#1 Public attribute.** `runtime.causal_reasoner` is set as a public attribute via the wirer; no underscore-prefixed private alternative.
- **#3 Default-False transitional flag.** `CausalReasoningConfig.enabled = False` per Wave 10 lesson.
- **#14 No breaking change on first commit.** With default config, AD-660 is invisible at runtime — the new table is created idempotently but no service is constructed and no integration runs.
- **#15 Three-pass review tolerance.** v1 has narrow surface (1 new file, 4 modified files, 1 new config, 8 tests). Expect approval at pass-1.
- **Privacy invariant.** Template fields are bounded to `_MAX_FIELD_CHARS` and lists to `_MAX_LIST_LEN`. No secrets, no full prompts, no episode IDs persisted in v1 (v1 stores only `source_event_ref` token, not raw event payload).
- **Layer discipline.** New module `cognitive/causal_reasoning.py` lives in the cognitive layer. It depends on `types.LLMRequest`, `utils.json_extract`, and `runtime.llm_client` — no substrate or experience-layer imports.

---

## Out-of-Scope Reminders for Builder

- Do NOT add a `/api/causal-templates` router. Storage is journal-only in v1.
- Do NOT subscribe to `EMERGENCE_METRICS_UPDATED` / `GROUPTHINK_WARNING` / `FRAGMENTATION_WARNING`. AD-660b owns the AD-557 surface.
- Do NOT add HXI rendering, no ASCII rendering, no shell command, no Captain notification.
- Do NOT add a periodic background `asyncio.create_task` analyze loop. Invocation is by integration-point only.
- Do NOT mutate `data` (the concern payload) inside the hook. The dict is shared with downstream subscribers.
- Do NOT add ChromaDB persistence. SQLite only.
- Do NOT change the existing `_SCHEMA_CHAIN_TRACES` block — extend by adding `_SCHEMA_CAUSAL_TEMPLATES` adjacent.
