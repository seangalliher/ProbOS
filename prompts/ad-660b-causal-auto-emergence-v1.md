# AD-660b v1 — Causal Reasoning: Automatic Invocation + Emergence Integration

**Status:** ready
**Dependencies:** AD-660 (Wave 32, shipped), AD-504 SelfMonitoringConcernEvent (shipped), AD-557 emergence events (shipped via `dream_adapter._event_emitter`)
**Estimated tests:** 12 new + 1 existing-test fix (AD-660 default-disabled assertion flipped)
**Closes:** GH issue #411

---

## Problem

AD-660 (Wave 32) shipped the four-step causal-reasoning template + journal storage + an opt-in counselor concern hook gated by `CausalReasoningConfig.enabled = False`. Three follow-up gaps remain before the framework is operational:

1. **Default-disabled gate.** The counselor `_on_self_monitoring_concern` hook never fires out-of-the-box. Captain wants it on by default — but uncapped LLM invocation per concern is a runaway-cost risk.
2. **AD-557 emergence events are dead-letter for causal reasoning.** `dream_adapter.py:120-135` already emits `EMERGENCE_METRICS_UPDATED`, `GROUPTHINK_WARNING`, and `FRAGMENTATION_WARNING`. Counselor `_on_groupthink_warning` (`counselor.py:1727`) and `_on_fragmentation_warning` (`counselor.py:1853`) currently log-only. No causal artifact is produced when the mesh detects coordination pathology.
3. **Hypotheses are unranked. Diagnostic actions are surfaced as plain strings.** Downstream consumers cannot prioritize hypotheses by novelty, and there is no structured channel to surface "this action is recommended for human review" — even though Captain wants the framework to advance from "fill template" to "propose next steps".

## Solution

v1 closes all three gaps in one cycle, with a hard boundary at action *recommendation* (no execution). Action execution requires sandboxed runtime which is AD-456b territory (Wave 55, not yet shipped) — that boundary is documented and tested.

### Scope

1. **Default-on flip + per-bucket rate limit.** `CausalReasoningConfig.enabled` default flips `False → True`. New field `max_invocations_per_hour: int = 5` (`field_validator` >= 1). New per-bucket sliding-window rate limiter on `CausalReasoner` instance keyed on `bucket: str` (= `agent_id` for concern hook, `"_emergence:groupthink"` / `"_emergence:fragmentation"` for emergence hooks). When window is full, `analyze()` returns a degraded template tagged with `trigger_summary="<rate-limited>"` and skips the LLM call. Logged at `INFO`.
2. **Emergence integration.** Two new convenience methods on `CausalReasoner`: `analyze_groupthink(data)` and `analyze_fragmentation(data)`. Each synthesizes a trigger string from the AD-557 payload (`redundancy_ratio` / `synergy_ratio` + `pairs_analyzed`) and a synthetic agent id (`"_ship_emergence"`), then delegates to `analyze()`. Counselor `_on_groupthink_warning` and `_on_fragmentation_warning` get the same `try/except` causal-reasoning hook block that already exists in `_on_self_monitoring_concern` (gated by `runtime.causal_reasoner is not None`, never raises).
3. **Hypothesis ranking + recommended actions.** Two new fields on `CausalReasoningTemplate` (frozen dataclass — fields appended last, both defaulted, preserves field-order rule):
   - `ranked_hypotheses: list[dict[str, Any]]` — each entry `{"hypothesis": str, "score": float, "rank": int, "novelty": float}`. Score = `confidence × novelty`. Novelty = `1.0 - max_jaccard` over hypothesis-token-set vs the last 10 templates' hypotheses (token = lowercased word, len ≥ 3, no punctuation). Empty journal → novelty `1.0`. Sorted desc by score; `rank` 1-indexed.
   - `recommended_actions: list[dict[str, Any]]` — one entry per `diagnostic_actions` item, shape `{"action": str, "status": "recommended", "needs_sandbox": True}`. Pure projection — no execution. The `needs_sandbox=True` marker is the explicit hand-off to AD-456b (Wave 55).
4. **Journal schema migration.** Two new nullable JSON columns on `causal_templates` table: `ranked_hypotheses_json`, `recommended_actions_json`. Migration via idempotent `ALTER TABLE ADD COLUMN` wrapped in try/except (handles warm boot on existing DBs). `record_causal_template` writes JSON-serialized values; `get_recent_causal_templates` decodes them back to `list[dict]` with safe fallbacks.

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Diagnostic action EXECUTION.** v1 logs `recommended_actions` to the journal so a human (or AD-456b sandboxed runtime, Wave 55) can act on them. Executing arbitrary LLM-suggested actions inside the agent runtime requires the AD-456b sandbox (Wave 55, not yet shipped). This is THE legitimate boundary — do not bypass.
- **Cross-agent template aggregation** (AD-660c).
- **Persistence of rate-limit state across restart** — in-memory only; deque resets on boot. Rationale: rate limiter is a runaway-cost guard, not an audit trail; an hour of grace post-restart is acceptable.
- **Decomposer / Ship's Computer integration** — analysis remains internal-only.
- **HXI surface for templates** (AD-660d).
- **Emergence handlers for `EMERGENCE_METRICS_UPDATED`** (the snapshot event) — only `GROUPTHINK_WARNING` + `FRAGMENTATION_WARNING` get hooks, because those are the *anomaly* signals (the snapshot fires every dream cycle and would drive rate-limit exhaustion immediately).
- **New EventType, new Pydantic config beyond the 1 new field, new module, new pool, new agent.**

---

## Verified Against Codebase (HEAD `1d6b728`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `CausalReasoningTemplate` frozen dc | `cognitive/causal_reasoning.py` | 39-40 | `@dataclass(frozen=True)\nclass CausalReasoningTemplate:` |
| `CausalReasoner.__init__(runtime, *, max_tokens=700, tier="standard")` | `cognitive/causal_reasoning.py` | 130-148 | `class CausalReasoner:` + ctor signature |
| `CausalReasoner.analyze(*, trigger, agent_id, context=None, source_event_ref=None)` | `cognitive/causal_reasoning.py` | 150-227 | `async def analyze(self, *, trigger: str, agent_id: str, ...)` |
| `CausalReasoner.analyze_concern(concern_data)` | `cognitive/causal_reasoning.py` | 232-267 | `async def analyze_concern(self, concern_data: dict[str, Any]) -> CausalReasoningTemplate \| None:` |
| `_empty_template(...)` helper | `cognitive/causal_reasoning.py` | 109 | `def _empty_template(*, agent_id, trigger_summary, source_event_ref):` |
| `CausalReasoningConfig` (`enabled=False`, `max_tokens=700`, `tier="standard"`) | `config.py` | 402-415 | `class CausalReasoningConfig(BaseModel):` |
| `SystemConfig.causal_reasoning` field | `config.py` | 2262 | `causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660` |
| `_wire_causal_reasoner` wirer | `startup/finalize.py` | 350-368 | `def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:` |
| `_wire_causal_reasoner` cascade slot | `startup/finalize.py` | 861 | `if _wire_causal_reasoner(runtime=runtime, config=config):` |
| `runtime.causal_reasoner = CausalReasoner(...)` | `startup/finalize.py` | 358-362 | wirer body |
| Counselor `_on_self_monitoring_concern` causal hook (template) | `cognitive/counselor.py` | 1011-1023 | `# AD-660: Opt-in causal reasoning hook.` block |
| Counselor `_on_groupthink_warning` (extension target) | `cognitive/counselor.py` | 1727 | `async def _on_groupthink_warning(self, data: dict[str, Any]) -> None:` |
| Counselor `_on_fragmentation_warning` (extension target) | `cognitive/counselor.py` | 1853 | `async def _on_fragmentation_warning(self, data: dict[str, Any]) -> None:` |
| Counselor event subscription (already includes both warnings) | `cognitive/counselor.py` | 683-684 | `EventType.GROUPTHINK_WARNING, EventType.FRAGMENTATION_WARNING,` |
| Counselor dispatcher | `cognitive/counselor.py` | 901-904 | `elif event_type == EventType.GROUPTHINK_WARNING.value:` etc. |
| Emergence event emission site | `dream_adapter.py` | 120-135 | `self._event_emitter(EventType.EMERGENCE_METRICS_UPDATED, ...)` then `if dream_report.groupthink_risk: ... GROUPTHINK_WARNING ...` |
| Groupthink payload shape | `dream_adapter.py` | 128-130 | `{"redundancy_ratio": getattr(dream_report, "redundancy_ratio", 0.0)}` |
| Fragmentation payload shape | `dream_adapter.py` | 132-135 | `{"synergy_ratio": ..., "pairs_analyzed": ...}` |
| `CognitiveJournal.record_causal_template` | `cognitive/journal.py` | 372-405 | `async def record_causal_template(self, template: Any) -> None:` |
| `CognitiveJournal.get_recent_causal_templates` | `cognitive/journal.py` | 407-451 | `async def get_recent_causal_templates(...)` |
| `_SCHEMA_CAUSAL_TEMPLATES` (table create) | `cognitive/journal.py` | 90-104 | schema literal |
| `await self._db.executescript(_SCHEMA_CAUSAL_TEMPLATES)` start path | `cognitive/journal.py` | 149 | start hook (migration insertion point) |
| Existing AD-660 test that asserts default-disabled | `tests/test_ad660_causal_reasoning.py` | 174-184 | `assert sys_cfg.causal_reasoning.enabled is False  # default` |
| Per-bucket rate-limit precedent (HttpFetchAgent class-level dict) | `agents/http_fetch.py` | 79-80 | `_domain_state: ClassVar[dict[str, DomainRateState]] = {}` |

**No GROUPTHINK_WARNING / FRAGMENTATION_WARNING dataclass exists** in `events.py`. The handlers consume raw `data: dict[str, Any]` payloads from the event bus. AD-660b matches that shape (no event dataclass added).

---

## Implementation

### Section 0 — Update `CausalReasoningConfig` defaults + add rate-limit field

**File:** `src/probos/config.py`

`SEARCH` block (around line 402-415):
```python
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
```

`REPLACE`:
```python
class CausalReasoningConfig(BaseModel):
    """AD-660 v1 + AD-660b: Agent Causal Reasoning Framework.

    v1 (AD-660) shipped the four-step template + journal storage + opt-in
    counselor concern hook. AD-660b flips the default ON, adds AD-557
    emergence-warning hooks (groupthink + fragmentation) on the same path,
    introduces hypothesis ranking + recommended-action surfacing, and adds
    a per-bucket sliding-window rate limiter to bound LLM cost.

    Default-on is safe because (a) the rate limiter caps invocations per
    bucket per hour, (b) `analyze()` is fire-and-forget — never raises into
    callers, and (c) downstream consumers (counselor hooks, journal) treat
    every result as best-effort.
    """

    enabled: bool = True  # AD-660b: default-on (rate-limited)
    max_tokens: int = 700
    tier: str = "standard"
    max_invocations_per_hour: int = 5  # AD-660b: per-bucket rate cap

    @field_validator("max_invocations_per_hour")
    @classmethod
    def _validate_rate_cap(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_invocations_per_hour must be >= 1")
        return v
```

Verify `field_validator` is already imported at top of `config.py` (it is — used by `DiagnosticContextConfig` line 352+).

### Section 1 — Extend `CausalReasoningTemplate` with two new fields

**File:** `src/probos/cognitive/causal_reasoning.py`

`SEARCH` block (around line 39-64):
```python
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
```

`REPLACE`:
```python
@dataclass(frozen=True)
class CausalReasoningTemplate:
    """Structured causal-reasoning artifact (AD-660 v1 + AD-660b).

    Immutable record of one analysis pass. The four list fields correspond
    to the Lee et al. (arXiv:2603.28052) Meta-Harness proposer's four-step
    causal-reasoning protocol. AD-660b adds:
      - ranked_hypotheses: confidence × novelty ranking of testable_hypotheses
      - recommended_actions: structured projection of diagnostic_actions for
        downstream review (execution requires AD-456b sandbox — Wave 55).
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
    # AD-660b: ranked hypotheses (score = confidence × novelty); empty when no hypotheses
    ranked_hypotheses: list[dict[str, Any]] = dataclass_field(default_factory=list)
    # AD-660b: recommended actions (projection of diagnostic_actions); empty when no actions
    recommended_actions: list[dict[str, Any]] = dataclass_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ISO-format datetime for JSON-friendly storage / API
        d["triggered_at"] = self.triggered_at.isoformat()
        return d
```

Adjust the imports near the top of the file (around line 24):

`SEARCH`:
```python
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
```

`REPLACE`:
```python
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
```

### Section 2 — Add per-bucket rate limiter + ranking helpers + emergence methods

**File:** `src/probos/cognitive/causal_reasoning.py`

Insert at the top of the module (after the existing `_MAX_FIELD_CHARS = 500` constant, around line 36):

```python
# AD-660b: per-bucket sliding-window rate-limit constants
_RATE_WINDOW_SECONDS = 3600.0  # 1 hour
_HYPOTHESIS_NOVELTY_LOOKBACK = 10  # last N templates considered for novelty
_MIN_NOVELTY_TOKEN_LEN = 3  # filter "the", "is", "and" etc.

# AD-660b: synthetic agent id for ship-level emergence triggers
_SHIP_EMERGENCE_AGENT_ID = "_ship_emergence"


def _tokenize_for_novelty(text: str) -> set[str]:
    """Lowercase tokenization for Jaccard novelty (AD-660b).

    Drops short tokens and non-alphanumerics. Returns a set for O(1) overlap.
    """
    if not text:
        return set()
    out: set[str] = set()
    buf: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            buf.append(ch)
        elif buf:
            tok = "".join(buf)
            if len(tok) >= _MIN_NOVELTY_TOKEN_LEN:
                out.add(tok)
            buf = []
    if buf:
        tok = "".join(buf)
        if len(tok) >= _MIN_NOVELTY_TOKEN_LEN:
            out.add(tok)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity in [0,1]. Returns 0.0 if either set empty."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _rank_hypotheses(
    hypotheses: list[str],
    confidence: float,
    prior_hypothesis_token_sets: list[set[str]],
) -> list[dict[str, Any]]:
    """Score and rank hypotheses by confidence × novelty (AD-660b).

    Novelty for each hypothesis = 1.0 - max-Jaccard against any prior
    hypothesis token set. Empty prior list → novelty 1.0 for every hypothesis.
    Returns a list of {hypothesis, score, rank, novelty} dicts, sorted desc
    by score; rank is 1-indexed.
    """
    if not hypotheses:
        return []
    scored: list[dict[str, Any]] = []
    for h in hypotheses:
        tokens = _tokenize_for_novelty(h)
        if not prior_hypothesis_token_sets:
            novelty = 1.0
        else:
            max_sim = max(
                _jaccard(tokens, prior) for prior in prior_hypothesis_token_sets
            )
            novelty = max(0.0, 1.0 - max_sim)
        score = max(0.0, min(1.0, confidence)) * novelty
        scored.append({
            "hypothesis": h,
            "score": round(score, 4),
            "novelty": round(novelty, 4),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, entry in enumerate(scored, start=1):
        entry["rank"] = i
    return scored


def _recommended_actions_from(actions: list[str]) -> list[dict[str, Any]]:
    """Project diagnostic_actions to structured recommended_actions (AD-660b).

    Each entry: {action, status="recommended", needs_sandbox=True}. The
    needs_sandbox flag is the explicit hand-off marker for AD-456b — v1
    does NOT execute these actions.
    """
    return [
        {"action": a, "status": "recommended", "needs_sandbox": True}
        for a in actions
    ]
```

Now extend `CausalReasoner.__init__` to add the rate-limit state. `SEARCH` (around line 137-148):

```python
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
```

`REPLACE`:
```python
    def __init__(
        self,
        runtime: Any,
        *,
        max_tokens: int = 700,
        tier: str = "standard",
        max_invocations_per_hour: int = 5,
        clock: Any = None,  # AD-660b: injectable for tests; defaults to time.time
    ) -> None:
        self._runtime = runtime
        self._max_tokens = max_tokens
        self._tier = tier
        self._max_invocations_per_hour = max(1, int(max_invocations_per_hour))
        # AD-660b: per-bucket sliding-window timestamps (in-memory; resets on restart)
        self._rate_buckets: dict[str, deque[float]] = {}
        self._clock = clock if clock is not None else time.time
```

Add imports near the top (after `import uuid`):

`SEARCH`:
```python
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any
```

`REPLACE`:
```python
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any
```

### Section 3 — Wire rate limiter, ranking, and recommended actions into `analyze()`

**File:** `src/probos/cognitive/causal_reasoning.py`

`SEARCH` (the entire `async def analyze(...)` body — around line 150-227). Match starting at the method signature through the final return. Use this anchor SEARCH:

```python
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
```

Replace the entire method body (everything between the docstring close and the existing `return CausalReasoningTemplate(...)` block). The full SEARCH/REPLACE pair below replaces signature + body together to keep the SEARCH unique:

`SEARCH` (full method, exact text from existing file):
```python
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
```

`REPLACE`:
```python
    async def analyze(
        self,
        *,
        trigger: str,
        agent_id: str,
        context: dict[str, Any] | None = None,
        source_event_ref: str | None = None,
        bucket: str | None = None,  # AD-660b: rate-limit bucket key (defaults to agent_id)
    ) -> CausalReasoningTemplate:
        """Run one causal-reasoning pass via the LLM.

        Returns a CausalReasoningTemplate. On any LLM failure, JSON-parse
        failure, or rate-limit rejection, returns a degraded (empty-list,
        confidence=0.0) template. Never raises.

        AD-660b adds:
          - per-bucket sliding-window rate limiting (default bucket=agent_id);
          - hypothesis ranking via Jaccard novelty against the last 10 templates;
          - structured recommended_actions surface for downstream review.
        """
        rate_bucket = bucket or agent_id
        if not self._check_rate_limit(rate_bucket):
            logger.info(
                "AD-660b: causal_reasoner rate-limited bucket=%s "
                "(>%d invocations in %.0fs); returning degraded template",
                rate_bucket, self._max_invocations_per_hour, _RATE_WINDOW_SECONDS,
            )
            tmpl = _empty_template(
                agent_id=agent_id,
                trigger_summary="<rate-limited>",
                source_event_ref=source_event_ref,
            )
            return tmpl

        ctx_json = ""
        if context:
            try:
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

        hypotheses = _coerce_list(parsed.get("testable_hypotheses"))
        diagnostic_actions = _coerce_list(parsed.get("diagnostic_actions"))
        confidence = _coerce_confidence(parsed.get("confidence"))

        # AD-660b: hypothesis ranking via novelty over last N templates
        prior_token_sets = await self._gather_prior_hypothesis_tokens()
        ranked = _rank_hypotheses(hypotheses, confidence, prior_token_sets)
        recommended = _recommended_actions_from(diagnostic_actions)

        return CausalReasoningTemplate(
            template_id=uuid.uuid4().hex[:16],
            agent_id=agent_id,
            triggered_at=datetime.now(timezone.utc),
            trigger_summary=trigger[:_MAX_FIELD_CHARS],
            what_changed=_coerce_list(parsed.get("what_changed")),
            confounded_variables=_coerce_list(parsed.get("confounded_variables")),
            testable_hypotheses=hypotheses,
            diagnostic_actions=diagnostic_actions,
            confidence=confidence,
            source_event_ref=source_event_ref,
            ranked_hypotheses=ranked,
            recommended_actions=recommended,
        )

    # ------------------------------------------------------------------
    # AD-660b: rate-limit + novelty helpers
    # ------------------------------------------------------------------

    def _check_rate_limit(self, bucket: str) -> bool:
        """Sliding-window per-bucket rate check. Returns True if call may proceed.

        On True, records the timestamp. On False, leaves the deque untouched.
        """
        now = float(self._clock())
        cutoff = now - _RATE_WINDOW_SECONDS
        bucket_deque = self._rate_buckets.get(bucket)
        if bucket_deque is None:
            bucket_deque = deque()
            self._rate_buckets[bucket] = bucket_deque
        # Drop expired
        while bucket_deque and bucket_deque[0] < cutoff:
            bucket_deque.popleft()
        if len(bucket_deque) >= self._max_invocations_per_hour:
            return False
        bucket_deque.append(now)
        return True

    async def _gather_prior_hypothesis_tokens(self) -> list[set[str]]:
        """Collect token sets of recent hypotheses for novelty scoring.

        Reads from `runtime.cognitive_journal.get_recent_causal_templates`
        (AD-660 surface). Best-effort — any failure returns []. Caps at
        _HYPOTHESIS_NOVELTY_LOOKBACK rows.
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return []
        try:
            rows = await journal.get_recent_causal_templates(
                limit=_HYPOTHESIS_NOVELTY_LOOKBACK,
            )
        except Exception:
            logger.debug("AD-660b: novelty lookback failed", exc_info=True)
            return []
        out: list[set[str]] = []
        for row in rows:
            for h in row.get("testable_hypotheses", []) or []:
                if isinstance(h, str):
                    out.append(_tokenize_for_novelty(h))
        return out

    # ------------------------------------------------------------------
    # AD-660b: emergence convenience methods
    # ------------------------------------------------------------------

    async def analyze_groupthink(
        self, data: dict[str, Any],
    ) -> CausalReasoningTemplate:
        """Run causal reasoning on an AD-557 GROUPTHINK_WARNING payload.

        Synthesizes a ship-level trigger from `redundancy_ratio`. Uses the
        synthetic agent id `_ship_emergence` and the bucket
        `_emergence:groupthink` for rate-limiting.
        """
        redundancy = float(data.get("redundancy_ratio", 0.0) or 0.0)
        trigger = (
            f"Mesh groupthink risk detected — redundancy_ratio={redundancy:.3f}. "
            "Crew may be echoing rather than complementing. "
            "Diagnose the coordination failure and propose discriminating actions."
        )
        return await self.analyze(
            trigger=trigger,
            agent_id=_SHIP_EMERGENCE_AGENT_ID,
            context={"kind": "groupthink", "redundancy_ratio": redundancy},
            source_event_ref="groupthink_warning",
            bucket="_emergence:groupthink",
        )

    async def analyze_fragmentation(
        self, data: dict[str, Any],
    ) -> CausalReasoningTemplate:
        """Run causal reasoning on an AD-557 FRAGMENTATION_WARNING payload."""
        synergy = float(data.get("synergy_ratio", 0.0) or 0.0)
        pairs = int(data.get("pairs_analyzed", 0) or 0)
        trigger = (
            f"Mesh fragmentation risk detected — synergy_ratio={synergy:.3f} "
            f"across {pairs} pairs. Crew may not be building on each other's "
            "contributions. Diagnose and propose synergy-restoring actions."
        )
        return await self.analyze(
            trigger=trigger,
            agent_id=_SHIP_EMERGENCE_AGENT_ID,
            context={
                "kind": "fragmentation",
                "synergy_ratio": synergy,
                "pairs_analyzed": pairs,
            },
            source_event_ref="fragmentation_warning",
            bucket="_emergence:fragmentation",
        )
```

Note: `analyze_concern` (existing AD-660 surface, line 232) does NOT need editing — it delegates to `analyze()`, which now applies the rate limit transparently using `agent_id` as the default bucket.

### Section 4 — Pass `max_invocations_per_hour` from wirer

**File:** `src/probos/startup/finalize.py`

`SEARCH` (around line 350-368):
```python
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

`REPLACE`:
```python
def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1 + AD-660b: Wire CausalReasoner template-fill service."""
    cfg = getattr(config, "causal_reasoning", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.causal_reasoning import CausalReasoner

    runtime.causal_reasoner = CausalReasoner(
        runtime,
        max_tokens=cfg.max_tokens,
        tier=cfg.tier,
        max_invocations_per_hour=cfg.max_invocations_per_hour,
    )
    logger.info(
        "AD-660b: CausalReasoner initialized "
        "(template + journal + concern hook + emergence hooks; "
        "rate=%d/hr/bucket)",
        cfg.max_invocations_per_hour,
    )
    return True
```

### Section 5 — Counselor emergence hooks invoke causal reasoner

**File:** `src/probos/cognitive/counselor.py`

`SEARCH` (around line 1727-1743 — `_on_groupthink_warning`):
```python
    async def _on_groupthink_warning(self, data: dict[str, Any]) -> None:
        """AD-557: Respond to groupthink risk — redundancy dominates synergy."""
        redundancy_ratio = data.get("redundancy_ratio", 0.0)
        top_pairs = data.get("top_synergy_pairs", [])
        # AD-583: Escalate to ERROR for extreme groupthink
        if redundancy_ratio > 0.9:
            logger.error(
                "AD-557: Extreme groupthink — redundancy_ratio=%.3f, "
                "AD-583 wrong convergence detection may provide targeted response",
                redundancy_ratio,
            )
        else:
            logger.warning(
                "AD-557: Groupthink warning — redundancy_ratio=%.3f, "
                "agents may be echoing rather than complementing",
                redundancy_ratio,
            )
```

`REPLACE`:
```python
    async def _on_groupthink_warning(self, data: dict[str, Any]) -> None:
        """AD-557 + AD-660b: Respond to groupthink risk — redundancy dominates synergy."""
        redundancy_ratio = data.get("redundancy_ratio", 0.0)
        top_pairs = data.get("top_synergy_pairs", [])
        # AD-583: Escalate to ERROR for extreme groupthink
        if redundancy_ratio > 0.9:
            logger.error(
                "AD-557: Extreme groupthink — redundancy_ratio=%.3f, "
                "AD-583 wrong convergence detection may provide targeted response",
                redundancy_ratio,
            )
        else:
            logger.warning(
                "AD-557: Groupthink warning — redundancy_ratio=%.3f, "
                "agents may be echoing rather than complementing",
                redundancy_ratio,
            )

        # AD-660b: Causal reasoning hook for emergence anomalies.
        # Rate-limited at the reasoner level (bucket=_emergence:groupthink).
        # Fire-and-forget — must NOT raise into the existing handler path.
        try:
            reasoner = getattr(self._runtime, "causal_reasoner", None) if self._runtime else None
            journal = self._cognitive_journal
            if reasoner is not None:
                template = await reasoner.analyze_groupthink(data)
                if journal is not None:
                    await journal.record_causal_template(template)
        except Exception:
            logger.debug("AD-660b: groupthink causal hook failed", exc_info=True)
```

`SEARCH` (around line 1853-1862 — `_on_fragmentation_warning`):
```python
    async def _on_fragmentation_warning(self, data: dict[str, Any]) -> None:
        """AD-557: Respond to fragmentation risk — synergy near zero."""
        synergy_ratio = data.get("synergy_ratio", 0.0)
        pairs_analyzed = data.get("pairs_analyzed", 0)
        logger.warning(
            "AD-557: Fragmentation warning — synergy_ratio=%.3f across %d pairs, "
            "agents may not be building on each other's contributions",
            synergy_ratio, pairs_analyzed,
        )
```

`REPLACE`:
```python
    async def _on_fragmentation_warning(self, data: dict[str, Any]) -> None:
        """AD-557 + AD-660b: Respond to fragmentation risk — synergy near zero."""
        synergy_ratio = data.get("synergy_ratio", 0.0)
        pairs_analyzed = data.get("pairs_analyzed", 0)
        logger.warning(
            "AD-557: Fragmentation warning — synergy_ratio=%.3f across %d pairs, "
            "agents may not be building on each other's contributions",
            synergy_ratio, pairs_analyzed,
        )

        # AD-660b: Causal reasoning hook (bucket=_emergence:fragmentation).
        try:
            reasoner = getattr(self._runtime, "causal_reasoner", None) if self._runtime else None
            journal = self._cognitive_journal
            if reasoner is not None:
                template = await reasoner.analyze_fragmentation(data)
                if journal is not None:
                    await journal.record_causal_template(template)
        except Exception:
            logger.debug("AD-660b: fragmentation causal hook failed", exc_info=True)
```

### Section 6 — Journal schema migration + persist new fields

**File:** `src/probos/cognitive/journal.py`

`SEARCH` (around line 90-104 — `_SCHEMA_CAUSAL_TEMPLATES`):
```python
_SCHEMA_CAUSAL_TEMPLATES = """
CREATE TABLE IF NOT EXISTS causal_templates (
    template_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    triggered_at REAL NOT NULL,
    trigger_summary TEXT,
    what_changed TEXT,
    confounded_variables TEXT,
    testable_hypotheses TEXT,
    diagnostic_actions TEXT,
    confidence REAL,
    source_event_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_causal_templates_triggered_at ON causal_templates(triggered_at);
CREATE INDEX IF NOT EXISTS idx_causal_templates_agent ON causal_templates(agent_id);
"""
```

`REPLACE`:
```python
_SCHEMA_CAUSAL_TEMPLATES = """
CREATE TABLE IF NOT EXISTS causal_templates (
    template_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    triggered_at REAL NOT NULL,
    trigger_summary TEXT,
    what_changed TEXT,
    confounded_variables TEXT,
    testable_hypotheses TEXT,
    diagnostic_actions TEXT,
    confidence REAL,
    source_event_ref TEXT,
    ranked_hypotheses_json TEXT,
    recommended_actions_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_causal_templates_triggered_at ON causal_templates(triggered_at);
CREATE INDEX IF NOT EXISTS idx_causal_templates_agent ON causal_templates(agent_id);
"""

# AD-660b: idempotent migration for warm-boot DBs created under AD-660 v1.
_MIGRATIONS_CAUSAL_TEMPLATES_AD660B = (
    "ALTER TABLE causal_templates ADD COLUMN ranked_hypotheses_json TEXT",
    "ALTER TABLE causal_templates ADD COLUMN recommended_actions_json TEXT",
)
```

`SEARCH` (around line 149 — `executescript(_SCHEMA_CAUSAL_TEMPLATES)`):
```python
        await self._db.executescript(_SCHEMA_CAUSAL_TEMPLATES)
```

`REPLACE`:
```python
        await self._db.executescript(_SCHEMA_CAUSAL_TEMPLATES)
        # AD-660b: idempotent ALTER TABLE for warm-boot DBs that pre-date AD-660b.
        # Each ALTER raises OperationalError when the column already exists; that
        # is the success signal — swallow it.
        for stmt in _MIGRATIONS_CAUSAL_TEMPLATES_AD660B:
            try:
                await self._db.execute(stmt)
            except Exception:
                pass
        await self._db.commit()
```

`SEARCH` (around line 384-401 — INSERT statement in `record_causal_template`):
```python
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
                    json.dumps(template.what_changed),
                    json.dumps(template.confounded_variables),
                    json.dumps(template.testable_hypotheses),
                    json.dumps(template.diagnostic_actions),
                    float(template.confidence),
                    template.source_event_ref,
                ),
            )
```

`REPLACE`:
```python
            await self._db.execute(
                """INSERT OR IGNORE INTO causal_templates
                   (template_id, agent_id, triggered_at, trigger_summary,
                    what_changed, confounded_variables, testable_hypotheses,
                    diagnostic_actions, confidence, source_event_ref,
                    ranked_hypotheses_json, recommended_actions_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    template.template_id,
                    template.agent_id,
                    triggered_ts,
                    template.trigger_summary,
                    json.dumps(template.what_changed),
                    json.dumps(template.confounded_variables),
                    json.dumps(template.testable_hypotheses),
                    json.dumps(template.diagnostic_actions),
                    float(template.confidence),
                    template.source_event_ref,
                    json.dumps(getattr(template, "ranked_hypotheses", []) or []),
                    json.dumps(getattr(template, "recommended_actions", []) or []),
                ),
            )
```

In `get_recent_causal_templates` JSON-decode loop (around line 437-450), extend the decoded-key tuple to include the two new fields. `SEARCH`:

```python
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = json.loads(raw) if isinstance(raw, str) else []
```

`REPLACE`:
```python
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = json.loads(raw) if isinstance(raw, str) else []
```

(No textual change — this stops the AD-660 decode loop on the four list-of-string columns. The two new JSON columns are decoded by a small follow-up block immediately after.)

Now extend the loop with a separate decode for the two new columns. `SEARCH` (the existing decode loop AND the close of the `for row in rows:` block — around line 437-450):

```python
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = json.loads(raw) if isinstance(raw, str) else []
                    except (ValueError, TypeError):
                        d[key] = []
                out.append(d)
```

`REPLACE`:
```python
                for key in (
                    "what_changed", "confounded_variables",
                    "testable_hypotheses", "diagnostic_actions",
                ):
                    raw = d.get(key, "[]")
                    try:
                        d[key] = json.loads(raw) if isinstance(raw, str) else []
                    except (ValueError, TypeError):
                        d[key] = []
                # AD-660b: decode list-of-dict columns (default to empty list)
                for json_col, dest_key in (
                    ("ranked_hypotheses_json", "ranked_hypotheses"),
                    ("recommended_actions_json", "recommended_actions"),
                ):
                    raw = d.pop(json_col, None) if json_col in d else None
                    if not isinstance(raw, str):
                        d[dest_key] = []
                        continue
                    try:
                        decoded = json.loads(raw)
                        d[dest_key] = decoded if isinstance(decoded, list) else []
                    except (ValueError, TypeError):
                        d[dest_key] = []
                out.append(d)
```

> Builder note: the existing `get_recent_causal_templates` body uses `SELECT *` so the two new columns appear automatically in `dict(row)`; the decode block above moves them under the public Python field names.

### Section 7 — Update existing AD-660 default-disabled assertion

**File:** `tests/test_ad660_causal_reasoning.py`

`SEARCH`:
```python
def test_wirer_skips_when_config_disabled() -> None:
    """AD-660: _wire_causal_reasoner returns False when config disabled."""
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    assert sys_cfg.causal_reasoning.enabled is False  # default
    runtime = SimpleNamespace()
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is False
    assert not hasattr(runtime, "causal_reasoner")
```

`REPLACE`:
```python
def test_wirer_skips_when_config_disabled() -> None:
    """AD-660 + AD-660b: _wire_causal_reasoner returns False when config disabled.

    AD-660b flipped the default to enabled=True. This test now constructs
    an explicitly-disabled config to exercise the skip path.
    """
    from probos.config import CausalReasoningConfig, SystemConfig
    from probos.startup.finalize import _wire_causal_reasoner

    sys_cfg = SystemConfig()
    sys_cfg.causal_reasoning = CausalReasoningConfig(enabled=False)
    runtime = SimpleNamespace()
    wired = _wire_causal_reasoner(runtime=runtime, config=sys_cfg)
    assert wired is False
    assert not hasattr(runtime, "causal_reasoner")
```

### Section 8 — New test file `tests/test_ad660b_causal_auto_emergence.py`

12 tests. Each test isolated; tests use `SimpleNamespace`, `AsyncMock`, and tmp_path-backed `CognitiveJournal` for the journal round-trip cases.

```python
"""AD-660b: Causal Reasoning Auto-Invocation + Emergence Integration — focused tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.causal_reasoning import (
    CausalReasoner,
    CausalReasoningTemplate,
    _jaccard,
    _rank_hypotheses,
    _recommended_actions_from,
    _tokenize_for_novelty,
)
from probos.cognitive.journal import CognitiveJournal


def _llm_response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(content=json.dumps(payload))


def _make_runtime(*, llm_payload: dict | None = None, journal: CognitiveJournal | None = None):
    response = _llm_response(llm_payload or {
        "what_changed": ["x"],
        "confounded_variables": [],
        "testable_hypotheses": ["latency caused regression"],
        "diagnostic_actions": ["roll back prompt"],
        "confidence": 0.5,
    })
    return SimpleNamespace(
        llm_client=SimpleNamespace(complete=AsyncMock(return_value=response)),
        cognitive_journal=journal,
    )


# ----- Test 1: template field shape & defaults --------------------------------

def test_template_has_ranked_hypotheses_and_recommended_actions_fields() -> None:
    t = CausalReasoningTemplate(
        template_id="t1",
        agent_id="a1",
        triggered_at=datetime.now(timezone.utc),
        trigger_summary="x",
        what_changed=[],
        confounded_variables=[],
        testable_hypotheses=[],
        diagnostic_actions=[],
        confidence=0.0,
    )
    assert t.ranked_hypotheses == []
    assert t.recommended_actions == []
    d = t.to_dict()
    assert d["ranked_hypotheses"] == []
    assert d["recommended_actions"] == []


# ----- Test 2: analyze() populates ranked_hypotheses + recommended_actions ----

@pytest.mark.asyncio
async def test_analyze_populates_ranking_and_recommendations() -> None:
    runtime = _make_runtime(llm_payload={
        "what_changed": ["new prompt"],
        "confounded_variables": [],
        "testable_hypotheses": [
            "fast tier insufficient",
            "prompt regression broke evaluate",
        ],
        "diagnostic_actions": ["pin tier=standard", "roll back prompt"],
        "confidence": 0.8,
    })
    reasoner = CausalReasoner(runtime)
    template = await reasoner.analyze(trigger="t", agent_id="a1")
    assert len(template.ranked_hypotheses) == 2
    # ranks 1-indexed and descending by score
    ranks = [r["rank"] for r in template.ranked_hypotheses]
    assert ranks == [1, 2]
    scores = [r["score"] for r in template.ranked_hypotheses]
    assert scores[0] >= scores[1]
    # empty journal => novelty 1.0 for all
    assert template.ranked_hypotheses[0]["novelty"] == 1.0
    # recommended_actions mirrors diagnostic_actions
    actions = template.recommended_actions
    assert len(actions) == 2
    assert all(a["status"] == "recommended" and a["needs_sandbox"] is True for a in actions)
    assert {a["action"] for a in actions} == {"pin tier=standard", "roll back prompt"}


# ----- Test 3: novelty scoring — identical hypothesis to prior --------------

def test_novelty_zero_when_hypothesis_matches_prior_token_set() -> None:
    prior = [_tokenize_for_novelty("fast tier insufficient for evaluate")]
    ranked = _rank_hypotheses(
        ["fast tier insufficient for evaluate"], 0.9, prior,
    )
    assert ranked[0]["novelty"] == 0.0
    assert ranked[0]["score"] == 0.0


# ----- Test 4: novelty scoring — fully novel hypothesis ----------------------

def test_novelty_one_when_no_token_overlap() -> None:
    prior = [_tokenize_for_novelty("alpha beta gamma")]
    ranked = _rank_hypotheses(
        ["delta epsilon zeta"], 0.6, prior,
    )
    assert ranked[0]["novelty"] == 1.0
    assert ranked[0]["score"] == pytest.approx(0.6, abs=1e-4)


# ----- Test 5: empty journal => novelty 1.0 for every hypothesis -----------

def test_novelty_one_when_no_prior_history() -> None:
    ranked = _rank_hypotheses(["any new hypothesis"], 0.4, [])
    assert ranked[0]["novelty"] == 1.0
    assert ranked[0]["score"] == pytest.approx(0.4, abs=1e-4)


# ----- Test 6: rate limiter — under threshold passes ------------------------

@pytest.mark.asyncio
async def test_rate_limit_allows_up_to_threshold() -> None:
    fixed = [1000.0]  # mutable clock
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=3, clock=lambda: fixed[0],
    )
    for _ in range(3):
        t = await reasoner.analyze(trigger="t", agent_id="a1")
        assert t.trigger_summary != "<rate-limited>"
    assert runtime.llm_client.complete.await_count == 3


# ----- Test 7: rate limiter — at threshold rejects --------------------------

@pytest.mark.asyncio
async def test_rate_limit_rejects_above_threshold() -> None:
    fixed = [1000.0]
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=2, clock=lambda: fixed[0],
    )
    await reasoner.analyze(trigger="t", agent_id="a1")
    await reasoner.analyze(trigger="t", agent_id="a1")
    rejected = await reasoner.analyze(trigger="t", agent_id="a1")
    assert rejected.trigger_summary == "<rate-limited>"
    # LLM was NOT called for the rejected invocation
    assert runtime.llm_client.complete.await_count == 2


# ----- Test 8: rate limiter — window expiry resets counter ------------------

@pytest.mark.asyncio
async def test_rate_limit_resets_after_window_expiry() -> None:
    fixed = [1000.0]
    runtime = _make_runtime()
    reasoner = CausalReasoner(
        runtime, max_invocations_per_hour=1, clock=lambda: fixed[0],
    )
    t1 = await reasoner.analyze(trigger="t", agent_id="a1")
    assert t1.trigger_summary != "<rate-limited>"
    # within window — rejected
    rejected = await reasoner.analyze(trigger="t", agent_id="a1")
    assert rejected.trigger_summary == "<rate-limited>"
    # advance past window (3600s + epsilon)
    fixed[0] = 1000.0 + 3601.0
    t3 = await reasoner.analyze(trigger="t", agent_id="a1")
    assert t3.trigger_summary != "<rate-limited>"
    assert runtime.llm_client.complete.await_count == 2


# ----- Test 9: analyze_groupthink builds trigger and uses emergence bucket --

@pytest.mark.asyncio
async def test_analyze_groupthink_builds_trigger_and_uses_emergence_bucket() -> None:
    runtime = _make_runtime()
    # Force tight rate to verify the bucket key isolates emergence from agent_id traffic.
    reasoner = CausalReasoner(runtime, max_invocations_per_hour=1)
    # Burn the agent-bucket budget under a real agent id
    await reasoner.analyze(trigger="x", agent_id="a1")
    # Groupthink uses bucket="_emergence:groupthink" — fresh budget
    template = await reasoner.analyze_groupthink({"redundancy_ratio": 0.85})
    assert template.trigger_summary != "<rate-limited>"
    assert template.agent_id == "_ship_emergence"
    assert template.source_event_ref == "groupthink_warning"
    # The synthesized trigger surfaced redundancy_ratio (verified via LLM call args)
    call_args = runtime.llm_client.complete.await_args_list[-1]
    sent = call_args.args[0]
    assert "redundancy_ratio=0.850" in sent.prompt or "0.850" in sent.prompt


# ----- Test 10: analyze_fragmentation builds trigger ------------------------

@pytest.mark.asyncio
async def test_analyze_fragmentation_builds_trigger() -> None:
    runtime = _make_runtime()
    reasoner = CausalReasoner(runtime)
    template = await reasoner.analyze_fragmentation({
        "synergy_ratio": 0.05,
        "pairs_analyzed": 12,
    })
    assert template.agent_id == "_ship_emergence"
    assert template.source_event_ref == "fragmentation_warning"
    call_args = runtime.llm_client.complete.await_args_list[-1]
    sent = call_args.args[0]
    assert "synergy_ratio=0.050" in sent.prompt
    assert "12 pairs" in sent.prompt


# ----- Test 11: counselor groupthink hook fires reasoner + journal ----------

@pytest.mark.asyncio
async def test_counselor_groupthink_handler_invokes_causal_reasoner() -> None:
    """Smoke: _on_groupthink_warning awaits reasoner.analyze_groupthink + journal.record."""
    from probos.cognitive.counselor import Counselor

    reasoner = SimpleNamespace(analyze_groupthink=AsyncMock(
        return_value=SimpleNamespace(template_id="g1"),
    ))
    journal = SimpleNamespace(record_causal_template=AsyncMock())
    runtime = SimpleNamespace(causal_reasoner=reasoner, cognitive_journal=journal)

    counselor = Counselor.__new__(Counselor)
    counselor.id = "counselor-1"
    counselor._runtime = runtime
    # `_cognitive_journal` is a property on Counselor that reads runtime.cognitive_journal;
    # for the bare instance we shortcut via direct attribute injection.
    counselor.__dict__["_cognitive_journal"] = journal  # property override

    # Direct call (skipping event-bus wiring)
    await counselor._on_groupthink_warning({"redundancy_ratio": 0.7})

    reasoner.analyze_groupthink.assert_awaited_once()
    journal.record_causal_template.assert_awaited_once()


# ----- Test 12: default-on config + journal round-trip with new fields -----

@pytest.mark.asyncio
async def test_default_enabled_and_journal_roundtrip_with_new_fields(tmp_path: Path) -> None:
    from probos.config import SystemConfig

    sys_cfg = SystemConfig()
    # AD-660b: default flipped to True
    assert sys_cfg.causal_reasoning.enabled is True
    assert sys_cfg.causal_reasoning.max_invocations_per_hour == 5

    journal = CognitiveJournal(db_path=str(tmp_path / "j.db"))
    await journal.start()
    try:
        t = CausalReasoningTemplate(
            template_id="rt-b1",
            agent_id="ops-1",
            triggered_at=datetime.now(timezone.utc),
            trigger_summary="trip",
            what_changed=[],
            confounded_variables=[],
            testable_hypotheses=["h"],
            diagnostic_actions=["do x"],
            confidence=0.5,
            source_event_ref="evt:b1",
            ranked_hypotheses=[{"hypothesis": "h", "score": 0.5, "rank": 1, "novelty": 1.0}],
            recommended_actions=[{"action": "do x", "status": "recommended", "needs_sandbox": True}],
        )
        await journal.record_causal_template(t)
        rows = await journal.get_recent_causal_templates(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["ranked_hypotheses"] == [
            {"hypothesis": "h", "score": 0.5, "rank": 1, "novelty": 1.0},
        ]
        assert row["recommended_actions"] == [
            {"action": "do x", "status": "recommended", "needs_sandbox": True},
        ]
    finally:
        await journal.stop()
```

> **Test 11 builder note:** if `Counselor.__init__` makes the bare `__new__` instance unusable, fall back to constructing a real `Counselor` with stub dependencies via the existing test pattern in `tests/test_ad660_causal_reasoning.py:Test #8` (which already constructs a runtime and a real `Counselor` indirectly through the wirer). Test 11's only job is to confirm the hook awaits `analyze_groupthink` and `record_causal_template` — any equivalent shape is acceptable.

---

## What This Does NOT Change

- `OracleService` and Tier 6/7 dispatch — untouched.
- `ProcessChainExecutor`, Bills, Watch Bill, ConsultationWorkspace — untouched.
- Decomposer / Ship's Computer / agent registration — no new intent, no new agent, no new pool.
- `EmergenceMetricsEvent`, `dream_adapter._event_emitter`, dream cycle Step 9 — handlers added at the *consumer* (counselor); emission path unchanged.
- All AD-660 v1 surfaces (`analyze`, `analyze_concern`, journal store/read) remain backward-compatible. New rate-limit / new fields are additive.
- No HXI surface, no API endpoint, no CLI command, no new EventType.

---

## Tracking

- **PROGRESS.md**: prepend AD-660b CLOSED entry above current top entry (AD-686b).
- **docs/development/roadmap.md**: flip the AD-660 entry status from `Phase 1 (template + journal + counselor concern hook) shipped — Phase 2 (auto-invocation + emergence) deferred to AD-660b` to include AD-660b shipped; add AD-660b sub-entry under AD-660 noting `Closes #411`.
- **DECISIONS.md**: prepend AD-660b entry above current top of Era V (`AD-686b` block).
- **No new ADs** other than AD-660b itself.

---

## Acceptance Criteria

1. All 12 new tests in `tests/test_ad660b_causal_auto_emergence.py` pass.
2. Existing 8 tests in `tests/test_ad660_causal_reasoning.py` pass (1 test updated in Section 7).
3. Full pytest gate `-n 8 --dist=loadfile` test count = baseline 11170 + 12 = **11182**.
4. `sys_cfg.causal_reasoning.enabled` defaults to `True`. `max_invocations_per_hour` defaults to `5` and `field_validator` rejects values < 1.
5. Counselor `_on_groupthink_warning` and `_on_fragmentation_warning` invoke the causal reasoner and write to the journal when `runtime.causal_reasoner` is set; both swallow exceptions.
6. CausalReasoningTemplate exposes `ranked_hypotheses` and `recommended_actions` with safe defaults (empty list); `to_dict` round-trips them; journal persists and reads them back.
7. `_check_rate_limit` is correct: rejects above `max_invocations_per_hour`, recovers after the 3600 s window expires, isolates buckets so `_emergence:*` and per-`agent_id` traffic share no budget.
8. No diagnostic-action execution code is added. `recommended_actions` carries `needs_sandbox=True` as the AD-456b hand-off marker.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase

See **Verified Against Codebase** table at the top of this prompt. All concrete claims (file paths, line numbers, method signatures, payload field names, AD-557 emission point, counselor handler line numbers, journal schema location) were confirmed via grep at HEAD `1d6b728` on 2026-05-05.
