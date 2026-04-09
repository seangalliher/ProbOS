"""Adaptive Source Governance — AD-568a/b/c/d/e + AD-570c.

Dynamic episodic vs parametric memory weighting based on task type,
retrieval quality signals, and anchor confidence.

AD-568d adds cognitive proprioception: ambient source attribution so
agents know where their knowledge originates (Johnson et al. 1993).

AD-568e adds post-decision faithfulness verification: heuristic check
that LLM responses align with recalled evidence (Self-RAG ISSUP token).

AD-570c adds natural language anchor query routing: deterministic
extraction of anchor filter parameters from NL queries (department,
watch section, agent/participant) for routing to recall_by_anchor().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RetrievalStrategy(str, Enum):
    """Retrieval strategy for episodic memory (AD-568a)."""
    NONE = "none"        # Skip episodic recall — parametric + procedural only
    SHALLOW = "shallow"  # Standard tier-based recall
    DEEP = "deep"        # Enhanced retrieval with expanded budget


# Intent-type → strategy mapping.
# Intent names come from IntentMessage.intent (plain strings).
# Unknown intents default to SHALLOW.
_INTENT_STRATEGY_MAP: dict[str, RetrievalStrategy] = {
    # NONE — creative/exploratory, no episodic benefit
    "game_challenge": RetrievalStrategy.NONE,
    "game_move": RetrievalStrategy.NONE,
    "game_spectate": RetrievalStrategy.NONE,

    # SHALLOW — routine, standard recall
    "proactive_think": RetrievalStrategy.SHALLOW,
    "ward_room_notification": RetrievalStrategy.SHALLOW,
    "direct_message": RetrievalStrategy.SHALLOW,
    "duty_assignment": RetrievalStrategy.SHALLOW,

    # DEEP — operational/diagnostic, experience is critical
    "incident_response": RetrievalStrategy.DEEP,
    "diagnostic_request": RetrievalStrategy.DEEP,
    "system_analysis": RetrievalStrategy.DEEP,
    "security_assessment": RetrievalStrategy.DEEP,
    "medical_assessment": RetrievalStrategy.DEEP,
    "build_task": RetrievalStrategy.DEEP,
    "code_review": RetrievalStrategy.DEEP,
}


def classify_retrieval_strategy(
    intent_type: str,
    *,
    episodic_count: int = 0,
    recent_confabulation_rate: float = 0.0,
) -> RetrievalStrategy:
    """Classify intent into retrieval strategy (AD-568a).

    Args:
        intent_type: The intent name string (e.g. "direct_message", "proactive_think").
        episodic_count: Number of episodes the agent has. If zero, NONE is
            always returned (no memories to retrieve).
        recent_confabulation_rate: Agent's recent confabulation rate from
            Counselor profile. High rates (>0.3) downgrade DEEP → SHALLOW.

    Returns:
        RetrievalStrategy enum value.
    """
    # No episodes at all → skip retrieval regardless of intent
    if episodic_count == 0:
        return RetrievalStrategy.NONE

    strategy = _INTENT_STRATEGY_MAP.get(intent_type, RetrievalStrategy.SHALLOW)

    # Safety: high confabulation rate → don't expand retrieval
    if strategy == RetrievalStrategy.DEEP and recent_confabulation_rate > 0.3:
        logger.info(
            "AD-568a: Downgrading DEEP→SHALLOW for intent '%s' due to "
            "confabulation rate %.2f",
            intent_type, recent_confabulation_rate,
        )
        strategy = RetrievalStrategy.SHALLOW

    return strategy


# ---------------------------------------------------------------------------
# Phase 2: Adaptive Budget Scaling (AD-568b)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetAdjustment:
    """Result of adaptive budget scaling (AD-568b)."""
    original_budget: int
    adjusted_budget: int
    reason: str
    scale_factor: float


def compute_adaptive_budget(
    base_budget: int,
    *,
    recall_scores: list[Any] | None = None,
    mean_anchor_confidence: float = 0.0,
    episode_count: int = 0,
    strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
) -> BudgetAdjustment:
    """Compute adaptive context budget based on retrieval quality (AD-568b).

    Scaling rules:
    - High-quality recalls (mean anchor confidence > 0.6): expand to 1.3x
    - Low-quality recalls (mean anchor confidence < 0.2): contract to 0.6x
    - Very few episodes (< 3): contract to 0.5x (little to retrieve)
    - NONE strategy: budget = 0
    - DEEP strategy already applied 1.5x in Phase 1; no additional scaling here

    Floor: 500 chars (always allow at least one short episode).
    Ceiling: 12000 chars (prevent context window bloat).

    Args:
        base_budget: The tier-resolved budget from resolve_recall_tier_params().
        recall_scores: List of RecallScore objects from recall_weighted().
        mean_anchor_confidence: Pre-computed mean anchor confidence.
        episode_count: Total episodes the agent has.
        strategy: The retrieval strategy from Phase 1.

    Returns:
        BudgetAdjustment with the scaled budget and reason.
    """
    if strategy == RetrievalStrategy.NONE:
        return BudgetAdjustment(
            original_budget=base_budget,
            adjusted_budget=0,
            reason="strategy=NONE, no retrieval",
            scale_factor=0.0,
        )

    # Compute mean anchor confidence from recall_scores if available
    _anchor_conf = mean_anchor_confidence
    if recall_scores:
        confs = [
            getattr(rs, 'anchor_confidence', 0.0)
            for rs in recall_scores
            if hasattr(rs, 'anchor_confidence')
        ]
        if confs:
            _anchor_conf = sum(confs) / len(confs)

    scale = 1.0
    reason_parts: list[str] = []

    # Signal 1: Anchor confidence quality
    if _anchor_conf > 0.6:
        scale *= 1.3
        reason_parts.append(f"high anchor confidence ({_anchor_conf:.2f})")
    elif _anchor_conf < 0.2 and episode_count > 0:
        scale *= 0.6
        reason_parts.append(f"low anchor confidence ({_anchor_conf:.2f})")

    # Signal 2: Episode sparsity
    if 0 < episode_count < 3:
        scale *= 0.5
        reason_parts.append(f"sparse episodes ({episode_count})")

    # Signal 3: Recall score distribution (if available)
    if recall_scores and len(recall_scores) > 0:
        scores = [
            getattr(rs, 'composite_score', 0.0)
            for rs in recall_scores
            if hasattr(rs, 'composite_score')
        ]
        if scores:
            mean_score = sum(scores) / len(scores)
            if mean_score > 0.7:
                scale *= 1.15
                reason_parts.append(f"high recall quality ({mean_score:.2f})")
            elif mean_score < 0.3:
                scale *= 0.8
                reason_parts.append(f"low recall quality ({mean_score:.2f})")

    adjusted = int(base_budget * scale)
    # Enforce floor/ceiling
    adjusted = max(500, min(12000, adjusted))

    reason = "; ".join(reason_parts) if reason_parts else "no adjustment"

    return BudgetAdjustment(
        original_budget=base_budget,
        adjusted_budget=adjusted,
        reason=reason,
        scale_factor=scale,
    )


# ---------------------------------------------------------------------------
# Phase 3: Source Priority Framing (AD-568c)
# ---------------------------------------------------------------------------


class SourceAuthority(str, Enum):
    """How authoritatively to frame episodic content (AD-568c)."""
    AUTHORITATIVE = "authoritative"  # Well-anchored, domain-relevant
    SUPPLEMENTARY = "supplementary"  # Moderate quality — consider but verify
    PERIPHERAL = "peripheral"        # Low quality — background only


@dataclass(frozen=True)
class SourceFraming:
    """Source priority framing result (AD-568c)."""
    authority: SourceAuthority
    header: str
    instruction: str


def compute_source_framing(
    *,
    mean_anchor_confidence: float = 0.0,
    recall_count: int = 0,
    mean_recall_score: float = 0.0,
    strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
) -> SourceFraming:
    """Compute source authority framing for episodic content (AD-568c).

    Args:
        mean_anchor_confidence: Mean anchor confidence of recalled episodes.
        recall_count: Number of episodes recalled.
        mean_recall_score: Mean composite score of recalled episodes.
        strategy: Retrieval strategy from Phase 1.

    Returns:
        SourceFraming with authority level, header text, and instruction text.
    """
    if strategy == RetrievalStrategy.NONE or recall_count == 0:
        return SourceFraming(
            authority=SourceAuthority.PERIPHERAL,
            header="=== SHIP MEMORY (no relevant experiences recalled) ===",
            instruction=(
                "You have no relevant episodic memories for this task. "
                "Rely on your training knowledge and standing orders. "
                "Be explicit if you are reasoning from general knowledge rather "
                "than personal experience."
            ),
        )

    # Compute authority level from quality signals
    quality_score = (mean_anchor_confidence * 0.6) + (mean_recall_score * 0.4)

    if quality_score > 0.55 and recall_count >= 3:
        return SourceFraming(
            authority=SourceAuthority.AUTHORITATIVE,
            header="=== SHIP MEMORY (verified operational experience) ===",
            instruction=(
                "These memories are well-anchored with strong contextual grounding. "
                "Prefer your operational experience over general knowledge when they "
                "conflict. Your experience aboard this vessel is authoritative for "
                "ship-specific matters."
            ),
        )
    elif quality_score > 0.3:
        return SourceFraming(
            authority=SourceAuthority.SUPPLEMENTARY,
            header="=== SHIP MEMORY (your experiences aboard this vessel) ===",
            instruction=(
                "These are your experiences. Consider them alongside your training "
                "knowledge. Where memories have strong anchors (time, place, participants), "
                "weight them more heavily. Where anchors are weak, treat as supplementary."
            ),
        )
    else:
        return SourceFraming(
            authority=SourceAuthority.PERIPHERAL,
            header="=== SHIP MEMORY (limited recollections) ===",
            instruction=(
                "These recollections have weak contextual grounding. Do not rely "
                "heavily on them. Use your training knowledge as the primary source "
                "and treat these as background context only. If uncertain, say so."
            ),
        )


# ---------------------------------------------------------------------------
# Phase 4: Cognitive Proprioception (AD-568d)
# ---------------------------------------------------------------------------


class KnowledgeSource(str, Enum):
    """Knowledge origin classification (AD-568d).

    Ambient source attribution — what kind of knowledge contributed to
    the agent's current cognitive context. Modeled on Johnson et al. (1993)
    Source Monitoring Framework.
    """
    EPISODIC = "episodic"          # Lived experience (EpisodicMemory recall)
    PARAMETRIC = "parametric"      # LLM training data (no retrieval)
    PROCEDURAL = "procedural"      # Learned procedure (Cognitive JIT)
    ORACLE = "oracle"              # Ship's Records / cross-tier knowledge
    STANDING_ORDERS = "standing_orders"  # Standing orders / constitution
    UNKNOWN = "unknown"            # Source not determined


@dataclass(frozen=True)
class SourceAttribution:
    """Source attribution snapshot for a cognitive cycle (AD-568d).

    Captures the composition of knowledge sources that contributed to
    the agent's context for a single handle_intent() call. This is the
    proprioceptive data — the agent's awareness of where its knowledge
    came from.
    """
    retrieval_strategy: RetrievalStrategy
    primary_source: KnowledgeSource
    episodic_count: int          # Number of episodic memories in context
    procedural_count: int        # Number of procedures consulted
    oracle_used: bool            # Whether Oracle service was queried
    source_framing_authority: str  # SourceAuthority value from 568c
    confabulation_rate: float    # Agent's current confabulation rate
    budget_adjustment: float     # Scale factor from 568b


def compute_source_attribution(
    *,
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
    episodic_count: int = 0,
    procedural_count: int = 0,
    oracle_used: bool = False,
    source_framing: SourceFraming | None = None,
    budget_adjustment: BudgetAdjustment | None = None,
    confabulation_rate: float = 0.0,
) -> SourceAttribution:
    """Compute source attribution from pipeline signals (AD-568d).

    Pure function — derives the primary knowledge source from the
    retrieval strategy and what was actually retrieved. This is called
    once per cognitive cycle, after recall and before prompt construction.

    Args:
        retrieval_strategy: Strategy from classify_retrieval_strategy().
        episodic_count: Number of episodes that made it into context.
        procedural_count: Number of Cognitive JIT procedures available.
        oracle_used: Whether Oracle service returned results.
        source_framing: SourceFraming from compute_source_framing().
        budget_adjustment: BudgetAdjustment from compute_adaptive_budget().
        confabulation_rate: Agent's confabulation rate from Counselor profile.

    Returns:
        SourceAttribution snapshot.
    """
    # Determine primary source from what's actually in context
    if retrieval_strategy == RetrievalStrategy.NONE:
        if procedural_count > 0:
            primary = KnowledgeSource.PROCEDURAL
        else:
            primary = KnowledgeSource.PARAMETRIC
    elif oracle_used and episodic_count == 0:
        primary = KnowledgeSource.ORACLE
    elif episodic_count > 0:
        primary = KnowledgeSource.EPISODIC
    elif procedural_count > 0:
        primary = KnowledgeSource.PROCEDURAL
    else:
        primary = KnowledgeSource.PARAMETRIC

    return SourceAttribution(
        retrieval_strategy=retrieval_strategy,
        primary_source=primary,
        episodic_count=episodic_count,
        procedural_count=procedural_count,
        oracle_used=oracle_used,
        source_framing_authority=(
            source_framing.authority.value if source_framing else "unknown"
        ),
        confabulation_rate=confabulation_rate,
        budget_adjustment=(
            budget_adjustment.scale_factor if budget_adjustment else 1.0
        ),
    )


# ---------------------------------------------------------------
# AD-568e: Faithfulness Verification
# ---------------------------------------------------------------

import re as _re

# Heuristic assertion markers — sentences likely making specific claims
_ASSERTION_PATTERN = _re.compile(
    r'\d+\.?\d*'    # Numbers (dates, counts, percentages)
    r'|[A-Z]{3,}'   # ALL_CAPS words (acronyms, names)
    r'|"[^"]*"'     # Double-quoted strings
    r"|'[^']*'"     # Single-quoted strings
)


@dataclass(frozen=True)
class FaithfulnessResult:
    """AD-568e: Post-decision faithfulness assessment.

    Heuristic check: does the response align with recalled evidence?
    Not a second LLM call — keyword overlap + claim density scoring.
    """
    score: float  # 0.0 (no evidence alignment) to 1.0 (fully grounded)
    evidence_overlap: float  # Fraction of response tokens found in evidence
    unsupported_claim_ratio: float  # Fraction of assertion-like sentences not backed by evidence
    evidence_count: int  # Number of recalled memories available
    grounded: bool  # score >= threshold (default 0.5)
    detail: str  # Human-readable summary


def check_faithfulness(
    *,
    response_text: str,
    recalled_memories: list[str],
    source_attribution: SourceAttribution | None = None,
    threshold: float = 0.5,
) -> FaithfulnessResult:
    """AD-568e: Heuristic faithfulness scoring.

    Compares the LLM response against recalled episodic memories using:
    1. Token overlap — what fraction of response content words appear in evidence
    2. Unsupported claim detection — sentences with assertion markers
       (numbers, proper nouns, specific claims) not overlapping with evidence

    Pure function, no LLM call, no I/O. Designed to run on every cognitive
    cycle without measurable latency impact.

    Returns FaithfulnessResult with grounded=True if score >= threshold.
    """
    # Edge case: no evidence to verify against — parametric response
    if not recalled_memories:
        return FaithfulnessResult(
            score=1.0,
            evidence_overlap=0.0,
            unsupported_claim_ratio=0.0,
            evidence_count=0,
            grounded=True,
            detail="No episodic evidence to verify against — parametric response",
        )

    # Edge case: parametric source attribution — self-contained
    if (
        source_attribution is not None
        and source_attribution.primary_source == KnowledgeSource.PARAMETRIC
    ):
        return FaithfulnessResult(
            score=1.0,
            evidence_overlap=0.0,
            unsupported_claim_ratio=0.0,
            evidence_count=len(recalled_memories),
            grounded=True,
            detail="Parametric primary source — faithfulness N/A",
        )

    # Edge case: empty response
    if not response_text or not response_text.strip():
        return FaithfulnessResult(
            score=1.0,
            evidence_overlap=0.0,
            unsupported_claim_ratio=0.0,
            evidence_count=len(recalled_memories),
            grounded=True,
            detail="Empty response — nothing to verify",
        )

    # Build evidence token set from all recalled memories
    evidence_tokens: set[str] = set()
    for mem in recalled_memories:
        for token in mem.lower().split():
            if len(token) > 2:  # Skip very short tokens
                evidence_tokens.add(token)

    # Tokenize response
    response_tokens = {
        t for t in response_text.lower().split() if len(t) > 2
    }

    if not response_tokens:
        return FaithfulnessResult(
            score=1.0,
            evidence_overlap=0.0,
            unsupported_claim_ratio=0.0,
            evidence_count=len(recalled_memories),
            grounded=True,
            detail="No substantive response tokens",
        )

    # 1. Evidence overlap
    overlap = response_tokens & evidence_tokens
    evidence_overlap = len(overlap) / len(response_tokens)

    # 2. Unsupported claim detection
    # Split response into sentences
    sentences = _re.split(r'[.!?]+', response_text)
    assertion_sentences = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if _ASSERTION_PATTERN.search(sent):
            assertion_sentences.append(sent)

    unsupported_claim_ratio = 0.0
    if assertion_sentences:
        unsupported = 0
        for sent in assertion_sentences:
            sent_tokens = {t for t in sent.lower().split() if len(t) > 2}
            if not sent_tokens:
                continue
            sent_overlap = len(sent_tokens & evidence_tokens) / len(sent_tokens)
            if sent_overlap < 0.3:
                unsupported += 1
        unsupported_claim_ratio = unsupported / len(assertion_sentences)

    # 3. Final score: weighted combination
    score = evidence_overlap * 0.6 + (1.0 - unsupported_claim_ratio) * 0.4
    score = round(min(1.0, max(0.0, score)), 4)
    grounded = score >= threshold

    detail = (
        f"overlap={evidence_overlap:.2f}, "
        f"claims={unsupported_claim_ratio:.2f}, "
        f"assertions={len(assertion_sentences)}, "
        f"evidence_tokens={len(evidence_tokens)}"
    )

    return FaithfulnessResult(
        score=score,
        evidence_overlap=round(evidence_overlap, 4),
        unsupported_claim_ratio=round(unsupported_claim_ratio, 4),
        evidence_count=len(recalled_memories),
        grounded=grounded,
        detail=detail,
    )


# ===========================================================================
# AD-570c: Natural Language Anchor Query Routing
# ===========================================================================

_DEPARTMENT_ALIASES: dict[str, str] = {
    # Canonical names
    "bridge": "bridge",
    "engineering": "engineering",
    "science": "science",
    "medical": "medical",
    "security": "security",
    "operations": "operations",
    # Common aliases
    "eng": "engineering",
    "sci": "science",
    "med": "medical",
    "sec": "security",
    "ops": "operations",
    "sickbay": "medical",
    "medbay": "medical",
    "lab": "science",
    "armory": "security",
    "brig": "security",
}

_WATCH_SECTIONS: dict[str, str] = {
    "mid watch": "mid",
    "morning watch": "morning",
    "forenoon watch": "forenoon",
    "forenoon": "forenoon",
    "afternoon watch": "afternoon",
    "afternoon": "afternoon",
    "first dog watch": "first_dog",
    "first dog": "first_dog",
    "second dog watch": "second_dog",
    "second dog": "second_dog",
    "first watch": "first",
}

_WATCH_HOUR_RANGES: dict[str, tuple[int, int]] = {
    "mid": (0, 4),
    "morning": (4, 8),
    "forenoon": (8, 12),
    "afternoon": (12, 16),
    "first_dog": (16, 18),
    "second_dog": (18, 20),
    "first": (20, 24),
}

# Ordered watch rotation for "last watch" resolution
_WATCH_ORDER: list[str] = [
    "mid", "morning", "forenoon", "afternoon",
    "first_dog", "second_dog", "first",
]

_AGENT_INDICATORS = _re.compile(
    r'\b(?:by|from|with|involving|about|ask)\s+(\w+)\b', _re.IGNORECASE
)


@dataclass(frozen=True)
class AnchorQuery:
    """AD-570c: Parsed anchor filter parameters from natural language query."""
    department: str = ""
    trigger_agent: str = ""
    participants: list[str] = field(default_factory=list)
    watch_section: str = ""
    time_range: tuple[float, float] | None = None
    semantic_query: str = ""
    has_anchor_signal: bool = False


def parse_anchor_query(
    query: str,
    known_callsigns: list[str] | None = None,
) -> AnchorQuery:
    """AD-570c: Extract anchor filter parameters from a natural language query.

    Pure function. No LLM call, no I/O. Returns AnchorQuery with
    has_anchor_signal=True if any dimensional filter was detected.
    When no anchor signal is found, the caller should fall through
    to normal recall_weighted() path.

    Args:
        query: Natural language query text.
        known_callsigns: Optional list of valid callsigns for bare-name matching.
            If not provided, only @mention syntax is recognized.
    """
    from datetime import datetime, timezone, timedelta

    remaining = query
    department = ""
    watch_section = ""
    time_range: tuple[float, float] | None = None
    trigger_agent = ""
    participants: list[str] = []

    # --- 1. Department pass ---
    # Sort aliases longest-first to avoid partial matches (e.g. "sec" inside "section")
    _sorted_dept_aliases = sorted(_DEPARTMENT_ALIASES.keys(), key=len, reverse=True)
    for alias in _sorted_dept_aliases:
        pattern = _re.compile(r'\b' + _re.escape(alias) + r'\b', _re.IGNORECASE)
        if pattern.search(remaining):
            department = _DEPARTMENT_ALIASES[alias]
            remaining = pattern.sub("", remaining, count=1)
            break

    # --- 2. Watch section / temporal pass ---
    # Sort longest-first
    _sorted_watch = sorted(_WATCH_SECTIONS.keys(), key=len, reverse=True)
    for phrase in _sorted_watch:
        pattern = _re.compile(r'\b' + _re.escape(phrase) + r'\b', _re.IGNORECASE)
        if pattern.search(remaining):
            watch_section = _WATCH_SECTIONS[phrase]
            remaining = pattern.sub("", remaining, count=1)
            # Compute time_range from watch section
            time_range = _watch_section_to_time_range(watch_section)
            break

    if not watch_section:
        # Check relative temporal phrases
        now = datetime.now(timezone.utc)

        _last_watch_pat = _re.compile(r'\b(?:last\s+watch|previous\s+watch)\b', _re.IGNORECASE)
        _this_watch_pat = _re.compile(r'\b(?:this\s+watch|current\s+watch)\b', _re.IGNORECASE)
        _today_pat = _re.compile(r'\btoday\b', _re.IGNORECASE)
        _yesterday_pat = _re.compile(r'\byesterday\b', _re.IGNORECASE)
        _recent_pat = _re.compile(r'\brecent\b', _re.IGNORECASE)

        if _last_watch_pat.search(remaining):
            remaining = _last_watch_pat.sub("", remaining, count=1)
            try:
                from probos.cognitive.orientation import derive_watch_section
                current_ws = derive_watch_section(now.hour)
                idx = _WATCH_ORDER.index(current_ws)
                prev_idx = (idx - 1) % len(_WATCH_ORDER)
                watch_section = _WATCH_ORDER[prev_idx]
                time_range = _watch_section_to_time_range(watch_section)
            except Exception:
                pass
        elif _this_watch_pat.search(remaining):
            remaining = _this_watch_pat.sub("", remaining, count=1)
            try:
                from probos.cognitive.orientation import derive_watch_section
                watch_section = derive_watch_section(now.hour)
                time_range = _watch_section_to_time_range(watch_section)
            except Exception:
                pass
        elif _today_pat.search(remaining):
            remaining = _today_pat.sub("", remaining, count=1)
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            time_range = (midnight.timestamp(), now.timestamp())
        elif _yesterday_pat.search(remaining):
            remaining = _yesterday_pat.sub("", remaining, count=1)
            today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_midnight = today_midnight - timedelta(days=1)
            time_range = (yesterday_midnight.timestamp(), today_midnight.timestamp())
        elif _recent_pat.search(remaining):
            remaining = _recent_pat.sub("", remaining, count=1)
            # "recent" = last 4 hours
            time_range = ((now - timedelta(hours=4)).timestamp(), now.timestamp())

    # --- 3. Agent / participant pass ---
    # First try @callsign extraction
    _at_mention = _re.search(r'@(\w+)', remaining)
    if _at_mention:
        trigger_agent = _at_mention.group(1)
        remaining = remaining[:_at_mention.start()] + remaining[_at_mention.end():]

    # Then scan indicator phrases: "by/from/with/involving/about/ask {name}"
    for match in _AGENT_INDICATORS.finditer(remaining):
        name = match.group(1)
        # Only accept if we have a callsign list to validate against
        if known_callsigns:
            _lower_callsigns = [cs.lower() for cs in known_callsigns]
            if name.lower() in _lower_callsigns:
                # Use original-case callsign
                _idx = _lower_callsigns.index(name.lower())
                resolved = known_callsigns[_idx]
                if not trigger_agent:
                    trigger_agent = resolved
                elif resolved.lower() != trigger_agent.lower():
                    participants.append(resolved)
                remaining = remaining[:match.start()] + remaining[match.end():]
                break  # Only extract first indicator match

    # --- 4. Assemble ---
    remaining = _re.sub(r'\s+', ' ', remaining).strip()

    has_signal = bool(
        department or watch_section or time_range is not None
        or trigger_agent or participants
    )

    return AnchorQuery(
        department=department,
        trigger_agent=trigger_agent,
        participants=participants,
        watch_section=watch_section,
        time_range=time_range,
        semantic_query=remaining,
        has_anchor_signal=has_signal,
    )


def _watch_section_to_time_range(watch_section: str) -> tuple[float, float] | None:
    """AD-570c: Convert a watch section name to a UTC time_range for today."""
    from datetime import datetime, timezone

    hours = _WATCH_HOUR_RANGES.get(watch_section)
    if not hours:
        return None

    now = datetime.now(timezone.utc)
    start_h, end_h = hours
    start = now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_h < 24:
        end = end.replace(hour=end_h)
    else:
        from datetime import timedelta
        end = end + timedelta(days=1)

    return (start.timestamp(), end.timestamp())
