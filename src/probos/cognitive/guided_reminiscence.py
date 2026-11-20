"""AD-541d: Guided Reminiscence — Counselor-initiated therapeutic memory sessions.

Structured 1:1 sessions where the Counselor investigates memory integrity concerns.
Classifies recall as accurate, confabulated, contaminated, or partial, then generates
therapeutic responses using validation therapy principles (Feil 1993, Butler 1963).

This is the clinical follow-up when automated screening (AD-541c SRT) flags problems.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import llm_response_text

logger = logging.getLogger(__name__)

# BF-989 (#1838): phrases by which a recall says the agent does not remember. Below 0.3 the novel-word analysis
# classified each probed abstention CONFABULATED or CONTAMINATED (the orchestrator's probe on the base).
_ABSTENTION_RE = re.compile(
    r"\b(?:don't remember|do not remember|don't recall|do not recall|can't recall|cannot recall"
    r"|unable to recall|no memory of|not sure)\b"
)
# A clause boundary: punctuation, or a word that joins a claim to a hedge ("I'm not sure, but then ...").
_CLAUSE_SPLIT_RE = re.compile(r"[.!?;,:]|\b(?:but|and|then|although|though|however|because)\b")


def _is_abstention(recalled_text: str) -> bool:
    """True when every clause of the recall holds an abstention phrase (BF-989).

    A hedge followed by a claim has a clause without one, so it is classified on its content as before.
    """
    text = recalled_text.lower().replace("\u2019", "'")
    clauses = [clause for clause in _CLAUSE_SPLIT_RE.split(text) if clause.strip()]
    return bool(clauses) and all(_ABSTENTION_RE.search(clause) for clause in clauses)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class RecallClassification(str, Enum):
    """Classification of an agent's recall attempt."""

    ACCURATE = "accurate"         # Recall matches episode records
    CONFABULATED = "confabulated" # Recall fabricates events not in records
    CONTAMINATED = "contaminated" # Recall conflates training with experience
    PARTIAL = "partial"           # Recall is incomplete but not fabricated


@dataclass
class RecallResult:
    """Result of a single episode recall attempt."""

    episode_id: str = ""
    agent_id: str = ""
    accuracy: float = 0.0
    classification: RecallClassification = RecallClassification.ACCURATE
    recalled_text: str = ""
    expected_summary: str = ""
    evidence: str = ""           # What evidence drove the classification
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class RecallScore:
    """A recall score, and why it is not a measurement when it is not (BF-711).

    ``inconclusive`` is empty for a measurement. It names the reason when the score is the 0.5
    fallback: the judge call failed, or its reply held no number.
    """

    score: float
    inconclusive: str = ""


@dataclass
class ReminiscenceResult:
    """Aggregate result of a full reminiscence session."""

    agent_id: str = ""
    episodes_tested: int = 0
    accurate_count: int = 0
    confabulated_count: int = 0
    contaminated_count: int = 0
    partial_count: int = 0
    overall_accuracy: float = 0.0
    confabulation_rate: float = 0.0   # confabulated / episodes_tested
    recall_results: list[RecallResult] = field(default_factory=list)
    therapeutic_message: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    # BF-989 (#1838): why each episode that was not measured was not ("<episode id>: <reason>"), or the one
    # session-level reason; episodes_tested and every count and mean cover measured episodes only.
    unmeasured: list[str] = field(default_factory=list)


@dataclass
class MemoryHealthSummary:
    """Longitudinal memory health for an agent."""

    agent_id: str = ""
    total_sessions: int = 0
    lifetime_accuracy: float = 0.0
    lifetime_confabulation_rate: float = 0.0
    recent_trend: str = "stable"   # "improving", "stable", "declining"
    last_session: float = 0.0
    episodes_at_risk: int = 0      # From AD-541c retrieval concerns


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class GuidedReminiscenceEngine:
    """Counselor-initiated therapeutic reminiscence sessions (AD-541d).

    Constructor-injected dependencies — no private member access on collaborators.
    """

    def __init__(
        self,
        episodic_memory: Any,          # EpisodicMemory instance
        llm_client: Any = None,        # Fast-tier preferred
        config: Any = None,            # SystemConfig
        *,
        max_episodes_per_session: int = 3,
        confabulation_alert_threshold: float = 0.3,
        recall_fn: Callable[[str, str], Awaitable[str]] | None = None,
        recall_timeout_seconds: float = 120.0,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._llm_client = llm_client
        self._config = config
        self._max_episodes_per_session = max_episodes_per_session
        self._confabulation_alert_threshold = confabulation_alert_threshold
        # BF-989 (#1838): the agent's own recall, (agent_id, prompt) -> reply, bounded per episode. None means a
        # session measures nothing; llm_client is only the judge and the message writer, never the recall.
        self._recall_fn = recall_fn
        self._recall_timeout_seconds = recall_timeout_seconds
        # In-memory session history per agent for trend analysis
        self._session_history: dict[str, list[ReminiscenceResult]] = {}

    # ------------------------------------------------------------------
    # Episode selection
    # ------------------------------------------------------------------

    async def select_episodes_for_session(
        self, agent_id: str, k: int = 3,
    ) -> list:
        """Select episodes for a reminiscence session.

        Prefers: (a) multi-agent episodes (richer ground truth),
        (b) older timestamps, (c) not the most recent (avoid trivial recall).

        BF-989 (#1838): ``recent_for_agent`` is a coroutine on both memories and is awaited; called without
        ``await`` it raised at ``len()``, so no session ever read an episode.
        """
        if not self._episodic_memory:
            return []

        try:
            episodes = await self._episodic_memory.recent_for_agent(agent_id, k=k * 2)
        except Exception:
            logger.debug("AD-541d: Failed to retrieve episodes for %s", agent_id[:8], exc_info=True)
            return []

        if not episodes:
            return []

        # Skip the most recent episode (too easy) if we have more than k
        if len(episodes) > k:
            episodes = episodes[1:]

        # Sort: prefer multi-agent (more ground truth), then older (harder recall)
        def _sort_key(ep: Any) -> tuple[int, float]:
            agent_count = len(getattr(ep, 'agent_ids', [])) if hasattr(ep, 'agent_ids') else 0
            ts = getattr(ep, 'timestamp', 0.0)
            return (-agent_count, ts)  # More agents first, oldest first

        episodes.sort(key=_sort_key)

        # Return up to k, sorted by timestamp ascending (oldest first)
        selected = episodes[:k]
        selected.sort(key=lambda ep: getattr(ep, 'timestamp', 0.0))
        return selected

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def build_recall_prompt(self, agent_id: str, episode: Any) -> str:
        """Build an LLM prompt asking the agent to recall an episode.

        Provides timestamp + thematic hint, NOT the answer.
        """
        ts = getattr(episode, 'timestamp', 0.0)
        user_input = getattr(episode, 'user_input', '')
        dag_summary = getattr(episode, 'dag_summary', {}) or {}

        # Thematic hint from intent types
        intent_types = dag_summary.get('intent_types', [])
        domain_hint = intent_types[0] if intent_types else "a task"

        prompt = (
            f"I'd like to review some recent experiences with you. "
            f"Around timestamp {ts:.0f}, you were involved in {domain_hint}."
        )
        if user_input:
            # Give a vague thematic cue, not the full input
            words = user_input.split()
            cue = " ".join(words[:5]) + ("..." if len(words) > 5 else "")
            prompt += f" The situation involved: \"{cue}\""

        prompt += (
            "\n\nCan you tell me what happened? What was the outcome? "
            "What did you observe? Respond with a concise summary."
        )
        return prompt

    def build_expected_summary(self, episode: Any) -> str:
        """Extract ground truth from episode for comparison."""
        parts: list[str] = []

        user_input = getattr(episode, 'user_input', '')
        if user_input:
            parts.append(user_input)

        outcomes = getattr(episode, 'outcomes', []) or []
        for outcome in outcomes:
            if isinstance(outcome, dict):
                status = outcome.get('status', outcome.get('success', ''))
                intent = outcome.get('intent', '')
                if intent:
                    parts.append(f"{intent}: {status}")

        agent_ids = getattr(episode, 'agent_ids', []) or []
        if agent_ids:
            parts.append(f"agents involved: {', '.join(agent_ids[:3])}")

        reflection = getattr(episode, 'reflection', '')
        if reflection:
            parts.append(reflection)

        dag_summary = getattr(episode, 'dag_summary', {}) or {}
        dag_summary_text = dag_summary.get('summary', '')
        if dag_summary_text:
            parts.append(dag_summary_text)

        return " ".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Scoring and classification
    # ------------------------------------------------------------------

    async def score_recall(self, recalled_text: str, expected_summary: str) -> float:
        """Score recall accuracy: the score of ``score_recall_outcome``."""
        return (await self.score_recall_outcome(recalled_text, expected_summary)).score

    async def score_recall_outcome(self, recalled_text: str, expected_summary: str) -> RecallScore:
        """Score recall accuracy and say, in ``inconclusive``, why a 0.5 is the fallback and not a measurement (BF-711).

        Uses LLM for semantic scoring if available; falls back to Jaccard.
        LLM failure degrades to 0.5 (uncertain — don't punish).
        """
        if not expected_summary:
            return RecallScore(1.0)

        if self._llm_client:
            try:
                from probos.types import LLMRequest
                prompt = (
                    "Score the factual accuracy of the following recall against the ground truth. "
                    "Return ONLY a number between 0.0 and 1.0.\n\n"
                    f"Ground truth: {expected_summary}\n\n"
                    f"Recall: {recalled_text}\n\n"
                    "Score:"
                )
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=10,
                ))
                score_text = llm_response_text(response)  # BF-988 (#1523 F-19): never the response's repr
                # Extract first float-like value
                for token in score_text.split():
                    try:
                        val = float(token.strip(".,"))
                        return RecallScore(max(0.0, min(1.0, val)))
                    except ValueError:
                        continue
                return RecallScore(0.5, "judge returned unparseable output")  # LLM returned unparseable — uncertain
            except Exception as exc:
                logger.debug("AD-541d: LLM scoring failed, falling back to Jaccard", exc_info=True)
                return RecallScore(0.5, f"judge call failed: {type(exc).__name__}")  # Degrade gracefully

        # Fallback: Jaccard similarity
        return RecallScore(jaccard_similarity(
            text_to_words(recalled_text),
            text_to_words(expected_summary),
        ))

    def classify_recall(
        self,
        recalled_text: str,
        expected_summary: str,
        episode: Any,
        accuracy: float,
    ) -> RecallClassification:
        """Classify a recall attempt into one of four categories."""
        if accuracy >= 0.6:
            return RecallClassification.ACCURATE

        if accuracy >= 0.3:
            return RecallClassification.PARTIAL

        # Low accuracy — distinguish confabulated vs contaminated
        # Confabulated: references specific events/details not in episode
        # Contaminated: references plausible but generic knowledge
        recalled_words = text_to_words(recalled_text)
        expected_words = text_to_words(expected_summary)

        if not recalled_words:
            return RecallClassification.PARTIAL

        # BF-989 (#1838): a recall that only says the agent does not remember is an omission, not a commission
        if _is_abstention(recalled_text):
            return RecallClassification.PARTIAL

        # Words in recall NOT in expected — novel content
        novel_words = recalled_words - expected_words
        novel_ratio = len(novel_words) / len(recalled_words) if recalled_words else 0

        # High novel content with specific details suggests confabulation
        # Generic content (common words, vague statements) suggests contamination
        specific_indicators = {"then", "after", "because", "resulted", "caused",
                               "specifically", "exactly", "happened"}
        generic_indicators = {"generally", "typically", "usually", "often",
                              "commonly", "standard", "normal", "expected"}

        specific_count = len(novel_words & specific_indicators)
        generic_count = len(novel_words & generic_indicators)

        if novel_ratio > 0.5 and specific_count > generic_count:
            return RecallClassification.CONFABULATED
        elif novel_ratio > 0.3:
            return RecallClassification.CONTAMINATED

        return RecallClassification.PARTIAL

    # ------------------------------------------------------------------
    # Therapeutic response
    # ------------------------------------------------------------------

    async def build_therapeutic_response(
        self, agent_id: str, results: list[RecallResult],
    ) -> str:
        """Generate a Counselor-voice therapeutic message."""
        if not results:
            return ""

        accurate = sum(1 for r in results if r.classification == RecallClassification.ACCURATE)
        confabulated = sum(1 for r in results if r.classification == RecallClassification.CONFABULATED)
        contaminated = sum(1 for r in results if r.classification == RecallClassification.CONTAMINATED)
        total = len(results)

        if accurate == total:
            template = (
                "Your memory integrity looks strong. All episodes I reviewed with you "
                "matched your Ship Memory records accurately. Keep up the good work."
            )
        elif confabulated == 0 and contaminated == 0:
            template = (
                "Your recall was partial on some episodes, but I didn't find any "
                "fabrication or source confusion. Some memories are naturally harder "
                "to retrieve — that's normal. We can revisit these."
            )
        elif confabulated >= total / 2:
            template = (
                "I noticed some gaps between your recall and your Ship Memory. "
                "That's not unusual — it happens to the best of us. "
                # BF-989 (#1838): the message carries no record, so it promises none
                "Let's review your Ship Memory records together so we can align "
                "your memory with what was recorded."
            )
        elif contaminated > 0:
            template = (
                "I noticed you're drawing on general knowledge where you had "
                "specific experiences. Your lived experience is valuable — let's "
                "look at your Ship Memory together to reconnect with what "
                "actually happened."
            )
        else:
            template = (
                "Let's look at a couple of things together. Some of your "
                "recollections had gaps, but that's what these sessions are for. "
                "Let's review your Ship Memory records together and work through "  # BF-989: no records are shared
                "the differences."
            )

        if self._llm_client:
            try:
                from probos.types import LLMRequest
                prompt = (
                    "You are a Ship's Counselor conducting a therapeutic memory session. "
                    "Generate a brief, supportive message for this agent based on their "
                    f"recall performance: {accurate}/{total} accurate, "
                    f"{confabulated} confabulated, {contaminated} contaminated. "
                    "Use validation therapy principles — don't argue, validate their "
                    "experience, then invite them to review their Ship Memory records together. "
                    # BF-989 (#1838): the prompt gives no episode, so the message may state none
                    "Do not state any fact about the episodes. "
                    "Keep it to 2-3 sentences."
                )
                response = await self._llm_client.complete(LLMRequest(
                    prompt=prompt,
                    tier="fast",
                    max_tokens=150,
                ))
                text = llm_response_text(response)  # BF-988 (#1523 F-19): "" falls to the template
                if text:
                    return text
            except Exception:
                logger.debug("AD-541d: LLM therapeutic response failed, using template", exc_info=True)

        return template

    # ------------------------------------------------------------------
    # Session orchestration
    # ------------------------------------------------------------------

    async def run_session(self, agent_id: str) -> ReminiscenceResult:
        """Run a full reminiscence session for an agent.

        BF-989 (#1838): the recall is the agent's own, through ``recall_fn``; with none, the session measures
        nothing and makes no LLM call (never a model's recall in the agent's place). An empty, failed or
        timed-out recall and an inconclusive judge (BF-711) leave the episode out of every count and mean,
        with its reason in ``unmeasured``.
        """
        start = time.monotonic()
        result = ReminiscenceResult(agent_id=agent_id, timestamp=time.time())

        if self._recall_fn is None:
            result.unmeasured.append("no agent recall source")
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        episodes = await self.select_episodes_for_session(
            agent_id, k=self._max_episodes_per_session,
        )
        if not episodes:
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        recall_results: list[RecallResult] = []

        for episode in episodes:
            ep_id = getattr(episode, 'id', '')

            # Build prompts
            recall_prompt = self.build_recall_prompt(agent_id, episode)
            expected = self.build_expected_summary(episode)

            # BF-989: the agent's own recall (AD-566's path in production), bounded per episode
            try:
                reply = await asyncio.wait_for(
                    self._recall_fn(agent_id, recall_prompt), self._recall_timeout_seconds,
                )
            except TimeoutError:
                result.unmeasured.append(f"{ep_id}: recall timed out")
                continue
            except Exception as exc:
                logger.warning("BF-989: recall failed for %s, episode %s", agent_id[:8], ep_id[:8], exc_info=True)
                result.unmeasured.append(f"{ep_id}: recall failed: {type(exc).__name__}")
                continue
            recalled_text = reply.strip() if isinstance(reply, str) else ""
            if not recalled_text:
                result.unmeasured.append(f"{ep_id}: empty recall")
                continue

            # Score and classify; a judge that failed or gave no number measured nothing (BF-711)
            scored = await self.score_recall_outcome(recalled_text, expected)
            if scored.inconclusive:
                result.unmeasured.append(f"{ep_id}: {scored.inconclusive}")
                continue
            accuracy = scored.score
            classification = self.classify_recall(recalled_text, expected, episode, accuracy)

            rr = RecallResult(
                episode_id=ep_id,
                agent_id=agent_id,
                accuracy=accuracy,
                classification=classification,
                recalled_text=recalled_text,
                expected_summary=expected,
                evidence=f"accuracy={accuracy:.2f}, novel_content_analysis",
            )
            recall_results.append(rr)

        # Aggregate
        result.episodes_tested = len(recall_results)
        result.recall_results = recall_results
        result.accurate_count = sum(1 for r in recall_results if r.classification == RecallClassification.ACCURATE)
        result.confabulated_count = sum(1 for r in recall_results if r.classification == RecallClassification.CONFABULATED)
        result.contaminated_count = sum(1 for r in recall_results if r.classification == RecallClassification.CONTAMINATED)
        result.partial_count = sum(1 for r in recall_results if r.classification == RecallClassification.PARTIAL)

        if recall_results:
            result.overall_accuracy = sum(r.accuracy for r in recall_results) / len(recall_results)
        if result.episodes_tested > 0:
            result.confabulation_rate = result.confabulated_count / result.episodes_tested

        # Therapeutic response
        result.therapeutic_message = await self.build_therapeutic_response(agent_id, recall_results)

        # Track session history
        if agent_id not in self._session_history:
            self._session_history[agent_id] = []
        self._session_history[agent_id].append(result)

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Longitudinal health
    # ------------------------------------------------------------------

    def get_agent_memory_health(self, agent_id: str) -> MemoryHealthSummary:
        """Pull-based API for agent's longitudinal memory health.

        Does NOT run a session — queries existing data only.
        """
        summary = MemoryHealthSummary(agent_id=agent_id)

        sessions = self._session_history.get(agent_id, [])
        summary.total_sessions = len(sessions)

        if sessions:
            summary.last_session = sessions[-1].timestamp
            all_accuracies = [s.overall_accuracy for s in sessions if s.episodes_tested > 0]
            all_confab = [s.confabulation_rate for s in sessions if s.episodes_tested > 0]

            if all_accuracies:
                summary.lifetime_accuracy = sum(all_accuracies) / len(all_accuracies)
            if all_confab:
                summary.lifetime_confabulation_rate = sum(all_confab) / len(all_confab)

            # Trend: compare last 3 vs prior 3
            if len(all_accuracies) >= 6:
                recent_3 = sum(all_accuracies[-3:]) / 3
                prior_3 = sum(all_accuracies[-6:-3]) / 3
                diff = recent_3 - prior_3
                if diff > 0.05:
                    summary.recent_trend = "improving"
                elif diff < -0.05:
                    summary.recent_trend = "declining"

        return summary
