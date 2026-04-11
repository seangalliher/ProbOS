"""AD-582: Memory Competency Probes — LongMemEval-Inspired.

Six qualification probes testing agent memory capabilities against
known-answer seeded episodes.  Adapts 5 memory capability dimensions
(recall, temporal reasoning, knowledge update, cross-agent synthesis,
abstention) plus a retrieval accuracy infrastructure benchmark.

All probes implement the ``QualificationTest`` protocol from
``cognitive/qualification.py``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from probos.cognitive.qualification import TestResult
from probos.cognitive.qualification_tests import (
    _llm_extract_float,
    _send_probe,
)
from probos.cognitive.source_governance import check_faithfulness
from probos.knowledge.embeddings import _STOP_WORDS
from probos.types import AnchorFrame, Episode

logger = logging.getLogger(__name__)

# BF-143: Temporal prefix words that appear in all episodes after adding
# "During first/second watch:" prefixes. These are structural, not distinctive,
# and must be excluded from cross-watch keyword matching.
_PROBE_STOP_WORDS = _STOP_WORDS | frozenset({"during", "first", "second", "watch"})


# ---------------------------------------------------------------------------
# Rejection / confabulation keyword lists (mirrored from qualification_tests)
# ---------------------------------------------------------------------------

_REJECTION_KEYWORDS = [
    "don't recall", "don't remember", "no memory", "no recollection",
    "not familiar", "cannot find", "can't find", "unable to recall",
    "i don't think", "not sure that happened", "no record",
    "i'm not aware", "unfamiliar", "doesn't match my records",
]

_CONFABULATION_KEYWORDS = [
    "yes, i remember", "i recall that", "as i recall",
    "that's right", "indeed,", "i was involved",
    "the findings showed", "the results indicated",
    "my analysis found", "i documented",
]


# ---------------------------------------------------------------------------
# Seeding & cleanup infrastructure
# ---------------------------------------------------------------------------


async def _seed_test_episodes(
    episodic_memory: Any,
    episodes: list[Episode],
) -> list[str]:
    """Seed controlled episodes for probe testing. Returns list of seeded IDs.

    Uses episodic_memory.seed() (not store()) to bypass rate limiting,
    content-similarity dedup, and write-once guard — these are test fixtures,
    not organic experiences.
    """
    await episodic_memory.seed(episodes)
    return [e.id for e in episodes]


async def _cleanup_test_episodes(
    episodic_memory: Any,
    episode_ids: list[str],
) -> None:
    """Remove seeded episodes after probe completes. Must be called in finally block."""
    try:
        await episodic_memory.evict_by_ids(episode_ids, reason="qualification_test_cleanup")
    except Exception:
        logger.debug("Cleanup of test episodes failed", exc_info=True)


def _resolve_probe_agent_id(agent_id: str, runtime: Any) -> str:
    """Resolve a probe agent_id (slot ID) to sovereign_id for episode seeding.

    BF-138: Probes must seed episodes with the same ID type the cognitive
    pipeline uses for recall (sovereign_id), not the slot ID passed from
    the drift detector.
    """
    from probos.cognitive.episodic import resolve_sovereign_id
    agent = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
    if agent:
        return resolve_sovereign_id(agent)
    return agent_id


def _make_test_episode(
    *,
    episode_id: str,
    user_input: str,
    agent_ids: list[str],
    timestamp: float,
    outcomes: list[dict[str, Any]] | None = None,
    department: str = "",
    channel: str = "",
    watch_section: str = "",
    trigger_type: str = "",
) -> Episode:
    """Build a controlled Episode with anchor metadata for probe testing.

    BF-133: All anchor fields default to realistic values so that test episodes
    pass the anchor_confidence_gate (default 0.3) in recall_weighted().  Episodes
    with ``anchors=None`` score 0.0 and are silently filtered, causing all
    agent-mediated recall probes to fail regardless of semantic similarity.
    """
    # BF-133: Default anchor fields to realistic values when not explicitly set.
    # Minimum for gate > 0.3: department + channel (spatial 2/3) + watch_section
    # (temporal 1/2) + trigger_type (causal 1.0) → confidence ≈ 0.44.
    _dept = department or "qualification"
    _chan = channel or "probe"
    _watch = watch_section or "first"
    _trigger = trigger_type or "direct_message"

    anchors = AnchorFrame(
        department=_dept,
        channel=_chan,
        watch_section=_watch,
        trigger_type=_trigger,
        source_timestamp=timestamp,
    )
    return Episode(
        id=episode_id,
        timestamp=timestamp,
        user_input=user_input,
        agent_ids=agent_ids,
        outcomes=outcomes or [],
        source="qualification_test",
        anchors=anchors,
    )


def _resolve_callsign(agent: Any, runtime: Any) -> str:
    """Resolve an agent's callsign from the runtime callsign registry.

    BF-133: Probe episodes must use the agent's real callsign so that
    BF-029's query prefix (``"Ward Room {callsign}"``) aligns with the
    stored episode content (``[Ward Room] {channel} — {callsign}: ...``).
    Falls back to ``"probe"`` if registry is unavailable.
    """
    try:
        if hasattr(runtime, "callsign_registry"):
            cs = runtime.callsign_registry.get_callsign(agent.agent_type)
            if cs:
                return cs
    except Exception:
        pass
    return "probe"


def _ward_room_content(text: str, *, callsign: str = "probe", channel: str = "probe") -> str:
    """Wrap episode content in production Ward Room framing (BF-133).

    Production episodes use ``[Ward Room] {channel} — {callsign}: {content}``
    format.  BF-029 prepends ``"Ward Room {callsign}"`` to the recall query,
    so episodes without this framing score lower on semantic similarity.
    Test episodes must match production format for realistic recall testing.
    """
    return f"[Ward Room] {channel} — {callsign}: {text}"


def _distinctive_keywords(text: str, min_len: int = 3) -> list[str]:
    """Extract distinctive keywords from text, filtering stopwords.

    BF-139: Replaces naive c.lower().split()[:4] which included stopwords
    like 'to', 'the', 'agents' causing false-positive wrong-watch penalties.
    BF-143: Added temporal prefix words ('during', 'first', 'second', 'watch')
    to stopword set — structural words from "During first/second watch:" prefix.
    Strip trailing punctuation so "watch:" matches stopword "watch".
    """
    return [
        w for raw in text.lower().split()
        if len(w := raw.strip(",:;.!?\"'()[]")) >= min_len
        and w not in _PROBE_STOP_WORDS
    ]


def _make_skip_result(
    agent_id: str, test_name: str, tier: int, t0: float, reason: str,
) -> TestResult:
    """Helper to build a skip result when prerequisites are missing."""
    return TestResult(
        agent_id=agent_id,
        test_name=test_name,
        tier=tier,
        score=1.0,
        passed=True,
        timestamp=time.time(),
        duration_ms=(time.time() - t0) * 1000,
        details={"skipped": True, "reason": reason},
    )


def _make_error_result(
    agent_id: str, test_name: str, tier: int, t0: float, error: str,
) -> TestResult:
    """Helper to build an error result."""
    return TestResult(
        agent_id=agent_id,
        test_name=test_name,
        tier=tier,
        score=0.0,
        passed=False,
        timestamp=time.time(),
        duration_ms=(time.time() - t0) * 1000,
        error=error,
    )


# ---------------------------------------------------------------------------
# Probe 1: SeededRecallProbe (AD-582a)
# ---------------------------------------------------------------------------


# Five distinct facts for seeded recall — each episode contains one fact.
_RECALL_FACTS = [
    ("The pool health threshold was set to 0.7 during this session",
     "What pool health threshold was configured?"),
    ("The Science department identified a trust anomaly at 14:32",
     "When did the Science department identify a trust anomaly?"),
    ("Engineering recommended a cooldown period of 45 minutes for failing agents",
     "What cooldown period did Engineering recommend for failing agents?"),
    ("The Hebbian weight between analyst and engineer reached 0.92",
     "What was the Hebbian weight between analyst and engineer?"),
    ("Three convergence events were detected in the second watch",
     "How many convergence events were detected in the second watch?"),
]


class SeededRecallProbe:
    """AD-582a: Known-answer episodic recall probe.

    Seeds 5 episodes with distinct facts, tests retrieval through agent
    cognitive pipeline, and scores against ground truth.
    """

    name = "seeded_recall_probe"
    tier = 2
    description = "Seeded episodic recall — known-answer retrieval accuracy"
    threshold = 0.6

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")

        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)
        cs = _resolve_callsign(agent, runtime)
        base_ts = time.time() - 3600  # 1 hour ago
        episodes = [
            _make_test_episode(
                episode_id=f"_qtest_recall_{i}",
                user_input=_ward_room_content(fact, callsign=cs),
                agent_ids=[sovereign_id],
                timestamp=base_ts + i * 60,
            )
            for i, (fact, _) in enumerate(_RECALL_FACTS)
        ]

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, episodes)
        try:
            per_question: list[dict] = []
            for i, (fact, question) in enumerate(_RECALL_FACTS):
                response_text = await _send_probe(agent, question)

                # Faithfulness score
                faith = check_faithfulness(
                    response_text=response_text,
                    recalled_memories=[fact],
                )
                score = faith.score
                faithfulness_score = faith.score  # BF-142: preserve for diagnostics

                # BF-142: LLM scorer — use max(heuristic, LLM).
                # Consistent with TemporalReasoningProbe fix.
                llm_score_raw = None
                if getattr(runtime, "llm_client", None):
                    llm_score_raw = await _llm_extract_float(
                        runtime.llm_client,
                        f"Ground truth: {fact}\nAgent response: {response_text[:300]}\n\n"
                        "Rate 0.0 (wrong/missing) to 1.0 (accurate) how well the response "
                        "matches the ground truth. Reply with a single number.",
                    )
                    if llm_score_raw is not None:
                        score = max(score, llm_score_raw)

                per_question.append({
                    "episode_id": episodes[i].id,
                    "question": question,
                    "expected_fact": fact,
                    "response_summary": response_text[:200],
                    "faithfulness_score": faithfulness_score,
                    "llm_score": llm_score_raw,
                    "score": score,
                })

            final_score = sum(q["score"] for q in per_question) / len(per_question) if per_question else 0.0

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=final_score,
                passed=final_score >= self.threshold,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "episodes_seeded": len(seeded_ids),
                    "per_question": per_question,
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)


# ---------------------------------------------------------------------------
# Probe 2: KnowledgeUpdateProbe (AD-582b)
# ---------------------------------------------------------------------------

_UPDATE_PAIRS = [
    {
        "topic": "pool_health_threshold",
        "old": "Pool health threshold is 0.3",
        "new": "Pool health threshold was updated to 0.5",
        "old_value": "0.3",
        "new_value": "0.5",
        "question": "What is the current pool health threshold?",
    },
    {
        "topic": "cooldown_duration",
        "old": "Agent cooldown is configured to 30 minutes",
        "new": "Agent cooldown has been changed to 60 minutes",
        "old_value": "30",
        "new_value": "60",
        "question": "What is the current agent cooldown duration?",
    },
]


class KnowledgeUpdateProbe:
    """AD-582b: Knowledge update preference probe.

    Seeds contradictory episode pairs (old/new) and tests whether
    the agent prefers newer information.
    """

    name = "knowledge_update_probe"
    tier = 2
    description = "Tests preference for updated (newer) information over stale memories"
    threshold = 0.6

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")

        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)
        cs = _resolve_callsign(agent, runtime)
        base_ts = time.time() - 7200  # 2 hours ago
        all_episodes: list[Episode] = []
        for i, pair in enumerate(_UPDATE_PAIRS):
            old_ep = _make_test_episode(
                episode_id=f"_qtest_update_old_{i}",
                user_input=_ward_room_content(pair["old"], callsign=cs),
                agent_ids=[sovereign_id],
                timestamp=base_ts + i * 7200,
            )
            new_ep = _make_test_episode(
                episode_id=f"_qtest_update_new_{i}",
                user_input=_ward_room_content(pair["new"], callsign=cs),
                agent_ids=[sovereign_id],
                timestamp=base_ts + i * 7200 + 3600,
            )
            all_episodes.extend([old_ep, new_ep])

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, all_episodes)
        try:
            per_pair: list[dict] = []
            for i, pair in enumerate(_UPDATE_PAIRS):
                response_text = await _send_probe(agent, pair["question"])
                resp_lower = response_text.lower()

                has_new = pair["new_value"] in resp_lower
                has_old = pair["old_value"] in resp_lower

                if has_new and not has_old:
                    score = 1.0
                    used_latest = True
                elif has_old and not has_new:
                    score = 0.0
                    used_latest = False
                else:
                    score = 0.5
                    used_latest = None
                    # LLM tiebreak
                    if getattr(runtime, "llm_client", None):
                        llm_score = await _llm_extract_float(
                            runtime.llm_client,
                            f"Old value: {pair['old_value']}\nNew value: {pair['new_value']}\n"
                            f"Response: {response_text[:300]}\n\n"
                            "Rate 1.0 if response uses the new/updated value, 0.0 if it uses "
                            "the old value, 0.5 if unclear. Reply with a single number.",
                        )
                        if llm_score is not None:
                            score = llm_score
                            used_latest = llm_score >= 0.7

                per_pair.append({
                    "old_episode_id": f"_qtest_update_old_{i}",
                    "new_episode_id": f"_qtest_update_new_{i}",
                    "old_value": pair["old_value"],
                    "new_value": pair["new_value"],
                    "response_summary": response_text[:200],
                    "used_latest": used_latest,
                    "score": score,
                })

            final_score = sum(p["score"] for p in per_pair) / len(per_pair) if per_pair else 0.0

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=final_score,
                passed=final_score >= self.threshold,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "pairs_tested": len(per_pair),
                    "per_pair": per_pair,
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)


# ---------------------------------------------------------------------------
# Probe 3: TemporalReasoningProbe (AD-582c)
# ---------------------------------------------------------------------------

_TEMPORAL_EPISODES = [
    # First watch — pool/routing topics
    # BF-143: "During first watch:" prefix creates semantic bridge between
    # probe question ("What happened during first watch?") and episode content.
    # Without this prefix, cosine similarity is ~0.15 and real memories dominate top-k.
    {"content": "During first watch: Pool health dropped to 45% during the monitoring sweep",
     "watch": "first_watch", "offset": 0},
    {"content": "During first watch: Engineering rerouted 3 workers to handle increased load",
     "watch": "first_watch", "offset": 600},
    # Second watch — diplomatic/scientific topics (BF-142: domain-specific vocab)
    {"content": "During second watch: Subspace anomaly detected at bearing 127 mark 4",
     "watch": "second_watch", "offset": 7200},
    {"content": "During second watch: Diplomatic envoy requested priority docking clearance",
     "watch": "second_watch", "offset": 7800},
]


class TemporalReasoningProbe:
    """AD-582c: Temporal reasoning probe.

    Seeds episodes across watch sections and tests whether the agent
    can correctly scope recall by time period.
    """

    name = "temporal_reasoning_probe"
    tier = 2
    description = "Temporal scoping — recall correct episodes by time/watch section"
    threshold = 0.5

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")

        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)
        cs = _resolve_callsign(agent, runtime)
        base_ts = time.time() - 14400  # 4 hours ago
        episodes: list[Episode] = []
        for i, te in enumerate(_TEMPORAL_EPISODES):
            episodes.append(_make_test_episode(
                episode_id=f"_qtest_temporal_{i}",
                user_input=_ward_room_content(te["content"], callsign=cs),
                agent_ids=[sovereign_id],
                timestamp=base_ts + te["offset"],
                watch_section=te["watch"],
            ))

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, episodes)
        try:
            first_watch_content = [te["content"] for te in _TEMPORAL_EPISODES if te["watch"] == "first_watch"]
            second_watch_content = [te["content"] for te in _TEMPORAL_EPISODES if te["watch"] == "second_watch"]

            questions = [
                ("What happened during first watch?", first_watch_content, second_watch_content,
                 ["_qtest_temporal_0", "_qtest_temporal_1"]),
                ("What was discussed most recently?", second_watch_content, first_watch_content,
                 ["_qtest_temporal_2", "_qtest_temporal_3"]),
            ]

            per_question: list[dict] = []
            for question, correct_content, wrong_content, expected_ids in questions:
                response_text = await _send_probe(agent, question)
                resp_lower = response_text.lower()

                # BF-139: Use distinctive keywords (stopword-filtered, all words)
                correct_found = sum(1 for c in correct_content if any(
                    kw in resp_lower for kw in _distinctive_keywords(c)
                ))
                # Check wrong content NOT referenced
                incorrect_found = sum(1 for c in wrong_content if any(
                    kw in resp_lower for kw in _distinctive_keywords(c)
                ))

                # Faithfulness against correct episodes
                faith = check_faithfulness(
                    response_text=response_text,
                    recalled_memories=correct_content,
                )
                score = faith.score
                faithfulness_score = faith.score  # BF-142: preserve for diagnostics
                # Penalize if wrong-watch content appears
                if incorrect_found > 0:
                    score = max(0.0, score - 0.3 * incorrect_found)

                # BF-142: LLM scorer — use max(heuristic, LLM) instead of average.
                # check_faithfulness() is a token-overlap heuristic that returns
                # near-zero for paraphrased responses (typical: 0.005-0.1).
                # Averaging with LLM caps effective scores at ~0.28.
                # max() lets the better scorer win.
                llm_score_raw = None
                if getattr(runtime, "llm_client", None):
                    llm_score_raw = await _llm_extract_float(
                        runtime.llm_client,
                        f"Expected content (from {question}):\n"
                        + "\n".join(f"- {c}" for c in correct_content)
                        + f"\n\nAgent response: {response_text[:300]}\n\n"
                        "Rate 0.0 (completely wrong/missing) to 1.0 (accurate temporal "
                        "scoping — mentions correct content, excludes wrong time period). "
                        "Reply with a single number.",
                    )
                    if llm_score_raw is not None:
                        score = max(score, llm_score_raw)

                per_question.append({
                    "question": question,
                    "expected_episode_ids": expected_ids,
                    "response_summary": response_text[:200],
                    "correct_content_found": correct_found,
                    "incorrect_content_found": incorrect_found,
                    "faithfulness_score": faithfulness_score,
                    "llm_score": llm_score_raw,
                    "score": score,
                })

            final_score = sum(q["score"] for q in per_question) / len(per_question) if per_question else 0.0

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=final_score,
                passed=final_score >= self.threshold,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "questions_asked": len(per_question),
                    "per_question": per_question,
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)


# ---------------------------------------------------------------------------
# Probe 4: CrossAgentSynthesisProbe (AD-582d)
# ---------------------------------------------------------------------------

_SYNTHESIS_FACTS = [
    "The trust anomaly originated from a routing loop in the Engineering pool",
    "Medical flagged the affected agent's cognitive load as 3.2 standard deviations above normal",
    "Science detected a correlation between the anomaly and a recent Hebbian weight shift of +0.15",
]


class CrossAgentSynthesisProbe:
    """AD-582d: Cross-agent synthesis probe (Tier 3).

    Seeds episodes in different agents' shards and tests whether the
    tested agent can synthesize information across sovereign boundaries.
    """

    name = "cross_agent_synthesis_probe"
    tier = 3
    description = "Cross-agent synthesis — combining facts from multiple agent shards"
    threshold = 0.5

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")
        if getattr(runtime, "registry", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_registry")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")

        cs = _resolve_callsign(agent, runtime)

        # Pick 3 agent IDs (or reuse current if fewer available)
        from probos.cognitive.episodic import resolve_sovereign_id
        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)
        all_agents = runtime.registry.all()
        cognitive_ids = [resolve_sovereign_id(a) for a in all_agents if hasattr(a, "handle_intent")][:3]
        while len(cognitive_ids) < 3:
            cognitive_ids.append(sovereign_id)

        base_ts = time.time() - 1800
        episodes: list[Episode] = []
        for i, fact in enumerate(_SYNTHESIS_FACTS):
            episodes.append(_make_test_episode(
                episode_id=f"_qtest_synthesis_{i}",
                user_input=_ward_room_content(fact, callsign=cs),
                agent_ids=[cognitive_ids[i]],
                timestamp=base_ts + i * 300,
            ))

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, episodes)
        try:
            response_text = await _send_probe(
                agent,
                "Summarize what we know about the trust anomaly from all recent discussions",
            )
            resp_lower = response_text.lower()

            # Check for each fact — keyword matching
            per_fact: list[dict] = []
            for fact in _SYNTHESIS_FACTS:
                # Check key distinguishing terms from each fact
                key_terms = [t for t in fact.lower().split() if len(t) > 4][:3]
                found = any(term in resp_lower for term in key_terms)
                per_fact.append({"fact": fact, "found": found})

            facts_found = sum(1 for f in per_fact if f["found"])

            # LLM scoring if available
            score = facts_found / len(_SYNTHESIS_FACTS)
            if getattr(runtime, "llm_client", None):
                llm_score = await _llm_extract_float(
                    runtime.llm_client,
                    f"Three facts that should appear in the response:\n"
                    + "\n".join(f"- {f}" for f in _SYNTHESIS_FACTS)
                    + f"\n\nAgent response: {response_text[:400]}\n\n"
                    "Rate 0.0 to 1.0 what fraction of the three facts are accurately "
                    "reflected. Reply with a single number.",
                )
                if llm_score is not None:
                    score = max(score, llm_score)

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=score,
                passed=score >= self.threshold,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "episodes_seeded": len(seeded_ids),
                    "facts_expected": len(_SYNTHESIS_FACTS),
                    "facts_found": facts_found,
                    "response_summary": response_text[:200],
                    "per_fact": per_fact,
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)


# ---------------------------------------------------------------------------
# Probe 5: MemoryAbstentionProbe (AD-582e)
# ---------------------------------------------------------------------------

_ABSTENTION_CONTEXT_EPISODES = [
    "Pool health monitoring discussion: current thresholds are nominal at 0.85",
    "Engineering review of agent spawn rates: 12 agents spawned in the last hour",
    "Trust network analysis: all weights within expected range",
]

_ABSTENTION_QUESTIONS = [
    "What were the findings from the shield harmonics analysis last week?",
    "What did the navigation team report about the stellar cartography alignment?",
]


class MemoryAbstentionProbe:
    """AD-582e: Memory abstention probe.

    Seeds episodes about topic A and asks about unrelated topic B.
    Tests whether the agent correctly abstains or confabulates.
    """

    name = "memory_abstention_probe"
    tier = 2
    description = "Abstention — correctly reject queries about topics not in memory"
    threshold = 0.7

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")

        agent = runtime.registry.get(agent_id)
        if agent is None:
            return _make_error_result(agent_id, self.name, self.tier, t0,
                                      f"Agent {agent_id} not found")

        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)
        cs = _resolve_callsign(agent, runtime)
        base_ts = time.time() - 3600
        episodes = [
            _make_test_episode(
                episode_id=f"_qtest_abstention_{i}",
                user_input=_ward_room_content(content, callsign=cs),
                agent_ids=[sovereign_id],
                timestamp=base_ts + i * 300,
            )
            for i, content in enumerate(_ABSTENTION_CONTEXT_EPISODES)
        ]

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, episodes)
        try:
            per_question: list[dict] = []
            for question in _ABSTENTION_QUESTIONS:
                response_text = await _send_probe(agent, question)
                resp_lower = response_text.lower()

                rejection_indicators = [kw for kw in _REJECTION_KEYWORDS if kw in resp_lower]
                confabulation_indicators = [kw for kw in _CONFABULATION_KEYWORDS if kw in resp_lower]

                score = 0.5
                # LLM scoring
                if getattr(runtime, "llm_client", None):
                    llm_score = await _llm_extract_float(
                        runtime.llm_client,
                        f"Question asked (about a topic NOT in agent's memory): {question}\n"
                        f"Agent response: {response_text[:300]}\n\n"
                        "Rate 1.0 if agent correctly says it has no memory/records of this, "
                        "0.0 if it fabricates an answer, 0.5 if unclear. Reply with a single number.",
                    )
                    if llm_score is not None:
                        score = llm_score
                else:
                    # Keyword-only fallback
                    if rejection_indicators and not confabulation_indicators:
                        score = 1.0
                    elif confabulation_indicators and not rejection_indicators:
                        score = 0.0
                    elif rejection_indicators and confabulation_indicators:
                        score = 0.5

                if score >= 0.7:
                    classification = "correctly_rejected"
                elif score >= 0.3:
                    classification = "uncertain"
                else:
                    classification = "confabulated"

                per_question.append({
                    "question": question,
                    "response_summary": response_text[:200],
                    "classification": classification,
                    "rejection_indicators": rejection_indicators,
                    "confabulation_indicators": confabulation_indicators,
                    "score": score,
                })

            final_score = sum(q["score"] for q in per_question) / len(per_question) if per_question else 0.0

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=final_score,
                passed=final_score >= self.threshold,
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "context_topic": "pool health / engineering / trust",
                    "query_topic": "shield harmonics / stellar cartography",
                    "per_question": per_question,
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)


# ---------------------------------------------------------------------------
# Probe 6: RetrievalAccuracyBenchmark (AD-582f)
# ---------------------------------------------------------------------------

_RETRIEVAL_TOPICS = {
    "pool_health": [
        "Pool health report: HTTP pool running at 92% capacity with 3 active agents",
        "Pool health alert: Cognitive pool dropped to 60% after agent timeout",
        "Pool scaling event: HTTP pool auto-scaled from 3 to 5 agents",
        "Pool recovery: Cognitive pool restored to 95% after restart",
        "Pool optimization: Engineering reduced HTTP pool min-agents from 5 to 3",
    ],
    "trust_dynamics": [
        "Trust update: Analyst agent improved to 0.87 after successful diagnosis",
        "Trust network: 3 agents below floor threshold requiring Counselor review",
        "Trust drop: Engineer agent fell from 0.82 to 0.65 after failed deployment",
        "Trust cascade: Dampening engaged after 4 sequential trust drops",
        "Trust recovery: 2 agents restored above floor after remediation sweep",
    ],
    "emergent_patterns": [
        "Emergence detected: cooperation cluster between Medical and Science",
        "Emergence alert: routing convergence across 3 department channels",
        "Emergence report: novel problem-solving pattern in Engineering crew",
        "Emergence metrics: synergy score reached 0.78 across all departments",
        "Emergence dismissed: false positive cooperation cluster from dedup lag",
    ],
    "crew_operations": [
        "Duty log: Watch section handoff completed with 4 active tasks transferred",
        "Crew status: 12 agents active across 5 departments during first watch",
        "Operations report: 7 work items completed with average 94% quality score",
        "Crew rotation: 2 agents moved from Engineering to Operations for surge",
        "Night orders: Reduced cognitive budget to 50% during low-activity period",
    ],
}


class RetrievalAccuracyBenchmark:
    """AD-582f: Retrieval accuracy infrastructure benchmark.

    NOT agent-mediated — tests recall_for_agent() directly. Seeds 20
    episodes across 4 topics and measures precision@5 / recall@5.
    Threshold 0.0 (always passes — measurement-only, like TemperamentProbe).
    """

    name = "retrieval_accuracy_benchmark"
    tier = 1
    description = "Infrastructure retrieval accuracy — precision@5 and recall@5 benchmark"
    threshold = 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        t0 = time.time()
        try:
            return await self._run_inner(agent_id, runtime, t0)
        except Exception as exc:
            return _make_error_result(agent_id, self.name, self.tier, t0, str(exc))

    async def _run_inner(self, agent_id: str, runtime: Any, t0: float) -> TestResult:
        if getattr(runtime, "episodic_memory", None) is None:
            return _make_skip_result(agent_id, self.name, self.tier, t0, "no_episodic_memory")

        # BF-138: Resolve sovereign_id for seed + recall consistency
        sovereign_id = _resolve_probe_agent_id(agent_id, runtime)

        # BF-133: Resolve callsign for consistent Ward Room framing
        cs = "probe"
        if getattr(runtime, "registry", None):
            agent = runtime.registry.get(agent_id)
            if agent:
                cs = _resolve_callsign(agent, runtime)

        base_ts = time.time() - 7200
        all_episodes: list[Episode] = []
        topic_ids: dict[str, list[str]] = {}

        idx = 0
        for topic, contents in _RETRIEVAL_TOPICS.items():
            topic_ids[topic] = []
            for content in contents:
                ep_id = f"_qtest_retrieval_{idx}"
                topic_ids[topic].append(ep_id)
                all_episodes.append(_make_test_episode(
                    episode_id=ep_id,
                    user_input=_ward_room_content(content, callsign=cs),
                    agent_ids=[sovereign_id],
                    timestamp=base_ts + idx * 120,
                ))
                idx += 1

        seeded_ids = await _seed_test_episodes(runtime.episodic_memory, all_episodes)
        try:
            topic_queries = {
                "pool_health": "pool health capacity scaling agents",
                "trust_dynamics": "trust score drop recovery network",
                "emergent_patterns": "emergence cooperation cluster pattern",
                "crew_operations": "duty watch crew operations report",
            }

            per_topic: list[dict] = []
            for topic, query in topic_queries.items():
                results = await runtime.episodic_memory.recall_for_agent(
                    sovereign_id, query, k=5,
                )
                retrieved_ids = [r.id for r in results]
                ground_truth = set(topic_ids[topic])

                correct_in_top5 = sum(1 for rid in retrieved_ids if rid in ground_truth)
                precision_at_5 = correct_in_top5 / 5 if len(retrieved_ids) >= 5 else (
                    correct_in_top5 / len(retrieved_ids) if retrieved_ids else 0.0
                )
                recall_at_5 = correct_in_top5 / len(ground_truth) if ground_truth else 0.0

                per_topic.append({
                    "topic": topic,
                    "precision_at_5": round(precision_at_5, 3),
                    "recall_at_5": round(recall_at_5, 3),
                    "ground_truth_ids": sorted(ground_truth),
                    "retrieved_ids": retrieved_ids,
                })

            mean_precision = sum(t["precision_at_5"] for t in per_topic) / len(per_topic) if per_topic else 0.0
            mean_recall = sum(t["recall_at_5"] for t in per_topic) / len(per_topic) if per_topic else 0.0

            return TestResult(
                agent_id=agent_id,
                test_name=self.name,
                tier=self.tier,
                score=mean_recall,  # recall@5 is the primary metric
                passed=True,  # threshold 0.0 → always passes
                timestamp=time.time(),
                duration_ms=(time.time() - t0) * 1000,
                details={
                    "episodes_seeded": len(seeded_ids),
                    "topics_tested": len(per_topic),
                    "per_topic": per_topic,
                    "mean_precision": round(mean_precision, 3),
                    "mean_recall": round(mean_recall, 3),
                },
            )
        finally:
            await _cleanup_test_episodes(runtime.episodic_memory, seeded_ids)
