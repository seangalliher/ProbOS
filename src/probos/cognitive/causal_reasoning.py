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
from collections import deque
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any

from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


_MAX_LIST_LEN = 8           # cap each step's list length post-parse
_MAX_FIELD_CHARS = 500      # truncate any single bullet

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
            return _empty_template(
                agent_id=agent_id,
                trigger_summary="<rate-limited>",
                source_event_ref=source_event_ref,
            )

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
