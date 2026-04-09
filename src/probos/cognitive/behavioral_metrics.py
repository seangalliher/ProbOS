"""AD-569: Observation-Grounded Crew Intelligence Metrics.

Five behavioral metrics that examine the *content and consequence* of
crew collaboration, complementing the information-theoretic emergence
metrics (AD-557).

Metrics:
  1. Analytical Frame Diversity — distinct analytical perspectives per thread
  2. Synthesis Detection — novel insights not attributable to any single agent
  3. Cross-Department Trigger Rate — inter-department investigation cascades
  4. Convergence Correctness — quality of converged conclusions (when verifiable)
  5. Anchor-Grounded Emergence — emergence backed by independent observations

Research grounding: Woolley et al. (2010), Riedl (2025), Wegner (1987) TMS,
Hutchins (1995) distributed cognition, Shaffer et al. (2016) ENA.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from probos.config import BehavioralMetricsConfig
from probos.knowledge.embeddings import (
    embed_text,
    compute_similarity,
    _cosine_similarity,
)

logger = logging.getLogger(__name__)


@dataclass
class BehavioralSnapshot:
    """Ship-level behavioral metrics at a point in time."""

    timestamp: float = 0.0

    # Metric 1: Analytical Frame Diversity
    frame_diversity_score: float = 0.0  # 0-1, mean cross-thread frame diversity
    frame_diversity_threads: int = 0  # Threads analyzed for frame diversity
    department_representation: dict[str, int] = field(default_factory=dict)  # dept -> count

    # Metric 2: Synthesis Detection
    synthesis_rate: float = 0.0  # Fraction of threads with detected synthesis
    synthesis_threads: int = 0  # Threads with synthesis detected
    total_novel_elements: int = 0  # Total novel elements across all threads

    # Metric 3: Cross-Department Trigger Rate
    cross_dept_trigger_rate: float = 0.0  # Fraction of cross-dept triggers vs total
    trigger_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    trigger_events: int = 0  # Total cross-department trigger events

    # Metric 4: Convergence Correctness
    convergence_events: int = 0  # Total convergence events detected
    verified_correct: int = 0  # Convergences with positive outcome feedback
    verified_incorrect: int = 0  # Convergences with negative outcome feedback
    unverified: int = 0  # Convergences without ground truth
    convergence_correctness_rate: float | None = None  # correct / (correct + incorrect)

    # Metric 5: Anchor-Grounded Emergence
    anchor_grounded_rate: float = 0.0
    anchor_independence_score: float = 0.0
    anchor_analyzed_threads: int = 0

    # Aggregate
    threads_analyzed: int = 0
    behavioral_quality_score: float = 0.0  # Composite 0-1 score

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return asdict(self)


class BehavioralMetricsEngine:
    """Computes observation-grounded behavioral metrics for crew collaboration.

    Follows the same pattern as EmergenceMetricsEngine (AD-557):
    - Called during dream cycle (Step 13)
    - Stores rolling snapshot history
    - Exposes latest_snapshot and snapshots properties
    - Read-only consumer of Ward Room and episodic memory data
    """

    def __init__(
        self,
        config: BehavioralMetricsConfig | None = None,
        observable_state_verifier: Any = None,  # AD-583f
    ) -> None:
        self._config = config or BehavioralMetricsConfig()
        self._snapshots: deque[BehavioralSnapshot] = deque(maxlen=self._config.max_snapshots)
        self._verifier = observable_state_verifier

    def set_observable_verifier(self, verifier: Any) -> None:
        """AD-583f: Late-bind observable state verifier."""
        self._verifier = verifier

    @property
    def latest_snapshot(self) -> BehavioralSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshots(self) -> list[BehavioralSnapshot]:
        return list(self._snapshots)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    async def compute_behavioral_metrics(
        self,
        ward_room: Any,
        episodic_memory: Any | None = None,
        get_department: Callable[[str], str | None] | None = None,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> BehavioralSnapshot:
        """Compute all five behavioral metrics from Ward Room thread data."""
        cfg = self._config
        now = time.time()

        # 1. Retrieve qualifying threads
        since = now - (cfg.thread_lookback_hours * 3600)
        threads = await ward_room.browse_threads(
            agent_id="",
            channels=None,
            limit=100,
            since=since,
        )

        # 2. Collect thread data with posts
        qualifying_threads: list[dict[str, Any]] = []
        for thread in threads:
            thread_id = thread.id if hasattr(thread, "id") else thread.get("id", "")
            thread_data = await ward_room.get_thread(thread_id)
            if thread_data is None:
                continue

            posts_raw = (
                thread_data.get("posts", [])
                if isinstance(thread_data, dict)
                else getattr(thread_data, "posts", [])
            )
            posts: list[dict[str, Any]] = []
            for p in posts_raw:
                if isinstance(p, dict):
                    posts.append(p)
                else:
                    posts.append({
                        "id": getattr(p, "id", ""),
                        "author_id": getattr(p, "author_id", ""),
                        "author_callsign": getattr(p, "author_callsign", ""),
                        "body": getattr(p, "body", ""),
                        "created_at": getattr(p, "created_at", 0.0),
                    })

            unique_authors = {p["author_id"] for p in posts if p.get("author_id")}
            if len(unique_authors) < cfg.min_thread_contributors:
                continue
            if len(posts) < cfg.min_thread_posts:
                continue

            qualifying_threads.append({
                "thread_id": thread_id,
                "posts": posts,
                "unique_authors": unique_authors,
                "channel_id": (
                    thread.channel_id
                    if hasattr(thread, "channel_id")
                    else thread.get("channel_id", "")
                ),
                "channel_name": (
                    thread.channel_name
                    if hasattr(thread, "channel_name")
                    else thread.get("channel_name", "")
                ),
                "title": (
                    thread.title
                    if hasattr(thread, "title")
                    else thread.get("title", "")
                ),
            })

        threads_analyzed = len(qualifying_threads)
        if threads_analyzed == 0:
            snapshot = BehavioralSnapshot(timestamp=now, threads_analyzed=0)
            self._snapshots.append(snapshot)
            return snapshot

        # 3. Compute each metric
        frame_result = self._compute_frame_diversity(qualifying_threads, get_department)
        synthesis_result = self._compute_synthesis_detection(qualifying_threads)
        trigger_result = self._compute_cross_dept_triggers(qualifying_threads, get_department)
        convergence_result = await self._compute_convergence_correctness(qualifying_threads)
        anchor_result = await self._compute_anchor_grounded_emergence(
            qualifying_threads, episodic_memory
        )

        # 4. Composite score
        available_scores = [
            frame_result["score"],
            synthesis_result["rate"],
            trigger_result["rate"],
            anchor_result["grounded_rate"],
        ]
        if convergence_result["correctness_rate"] is not None:
            available_scores.append(convergence_result["correctness_rate"])

        behavioral_quality = (
            sum(available_scores) / len(available_scores) if available_scores else 0.0
        )

        snapshot = BehavioralSnapshot(
            timestamp=now,
            threads_analyzed=threads_analyzed,
            # Metric 1
            frame_diversity_score=frame_result["score"],
            frame_diversity_threads=frame_result["threads"],
            department_representation=frame_result["dept_counts"],
            # Metric 2
            synthesis_rate=synthesis_result["rate"],
            synthesis_threads=synthesis_result["threads_with_synthesis"],
            total_novel_elements=synthesis_result["novel_count"],
            # Metric 3
            cross_dept_trigger_rate=trigger_result["rate"],
            trigger_pairs=trigger_result["pairs"],
            trigger_events=trigger_result["events"],
            # Metric 4
            convergence_events=convergence_result["total"],
            verified_correct=convergence_result["correct"],
            verified_incorrect=convergence_result["incorrect"],
            unverified=convergence_result["unverified"],
            convergence_correctness_rate=convergence_result["correctness_rate"],
            # Metric 5
            anchor_grounded_rate=anchor_result["grounded_rate"],
            anchor_independence_score=anchor_result["independence_score"],
            anchor_analyzed_threads=anchor_result["analyzed_threads"],
            # Aggregate
            behavioral_quality_score=behavioral_quality,
        )

        self._snapshots.append(snapshot)

        # Emit event
        if emit_event_fn:
            try:
                from probos.events import EventType

                await emit_event_fn(EventType.BEHAVIORAL_METRICS_UPDATED, {
                    "behavioral_quality_score": behavioral_quality,
                    "threads_analyzed": threads_analyzed,
                    "frame_diversity": frame_result["score"],
                    "synthesis_rate": synthesis_result["rate"],
                    "cross_dept_trigger_rate": trigger_result["rate"],
                    "anchor_grounded_rate": anchor_result["grounded_rate"],
                })
            except Exception:
                logger.debug("AD-569: Event emission failed", exc_info=True)

        return snapshot

    # ------------------------------------------------------------------
    # Metric 1: Analytical Frame Diversity
    # ------------------------------------------------------------------

    def _compute_frame_diversity(
        self,
        threads: list[dict[str, Any]],
        get_department: Callable[[str], str | None] | None,
    ) -> dict[str, Any]:
        """Metric 1: Analytical Frame Diversity.

        For each multi-department thread, compute embedding-based diversity
        of per-department contributions. High diversity = different departments
        bring genuinely different analytical frames.
        """
        cfg = self._config
        diversity_scores: list[float] = []
        dept_counts: dict[str, int] = defaultdict(int)
        analyzed = 0

        for thread in threads:
            if not get_department:
                continue

            # Group posts by department
            dept_posts: dict[str, list[str]] = defaultdict(list)
            for post in thread["posts"]:
                author = post.get("author_id", "")
                body = post.get("body", "")
                if not author or not body:
                    continue
                dept = get_department(author)
                if dept:
                    dept_posts[dept].append(body)
                    dept_counts[dept] += 1

            if len(dept_posts) < cfg.frame_diversity_min_departments:
                continue

            # Compute per-department centroid embeddings
            dept_embeddings: dict[str, list[float]] = {}
            for dept, bodies in dept_posts.items():
                combined = " ".join(b[:500] for b in bodies)[:2000]
                dept_embeddings[dept] = embed_text(combined)

            # Pairwise cosine distance between department centroids
            depts = list(dept_embeddings.keys())
            if len(depts) < 2:
                continue

            distances: list[float] = []
            for i in range(len(depts)):
                for j in range(i + 1, len(depts)):
                    sim = _cosine_similarity(
                        dept_embeddings[depts[i]], dept_embeddings[depts[j]]
                    )
                    distances.append(1.0 - sim)  # distance = diversity

            if distances:
                diversity_scores.append(sum(distances) / len(distances))
                analyzed += 1

        score = sum(diversity_scores) / len(diversity_scores) if diversity_scores else 0.0
        return {"score": score, "threads": analyzed, "dept_counts": dict(dept_counts)}

    # ------------------------------------------------------------------
    # Metric 2: Synthesis Detection
    # ------------------------------------------------------------------

    def _compute_synthesis_detection(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 2: Synthesis Detection.

        For each thread, embed the full concatenated thread body and each
        individual contribution. Synthesis is present when the combined
        thread embedding is sufficiently different from the most-similar
        individual post embedding.
        """
        cfg = self._config
        synthesis_count = 0
        total_novel = 0
        eligible = 0

        for thread in threads:
            posts = thread["posts"]
            if len(posts) < cfg.synthesis_min_thread_posts:
                continue

            eligible += 1

            all_bodies = [p.get("body", "") for p in posts if p.get("body")]
            if not all_bodies:
                continue

            thread_text = " ".join(all_bodies)[:3000]
            thread_embedding = embed_text(thread_text)

            # Per-post embeddings
            post_embeddings: list[list[float]] = []
            for body in all_bodies:
                post_embeddings.append(embed_text(body[:1000]))

            # Max similarity of thread embedding to any single post
            max_sim = (
                max(
                    _cosine_similarity(thread_embedding, pe) for pe in post_embeddings
                )
                if post_embeddings
                else 1.0
            )

            novelty = 1.0 - max_sim
            if novelty >= cfg.synthesis_novelty_threshold:
                synthesis_count += 1
                total_novel += 1

        rate = synthesis_count / eligible if eligible > 0 else 0.0
        return {
            "rate": rate,
            "threads_with_synthesis": synthesis_count,
            "novel_count": total_novel,
        }

    # ------------------------------------------------------------------
    # Metric 3: Cross-Department Trigger Rate
    # ------------------------------------------------------------------

    def _compute_cross_dept_triggers(
        self,
        threads: list[dict[str, Any]],
        get_department: Callable[[str], str | None] | None,
    ) -> dict[str, Any]:
        """Metric 3: Cross-Department Trigger Rate.

        Detect temporal sequences where activity in one department is
        followed by activity in another department on a similar topic.
        """
        cfg = self._config
        if not get_department:
            return {"rate": 0.0, "pairs": [], "events": 0}

        # Group threads by department (inferred from first author)
        dept_threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for thread in threads:
            first_author = ""
            for p in thread["posts"]:
                if p.get("author_id"):
                    first_author = p["author_id"]
                    break
            if not first_author:
                continue
            dept = get_department(first_author)
            if dept:
                first_time = min(
                    (p.get("created_at", 0.0) for p in thread["posts"] if p.get("created_at")),
                    default=0.0,
                )
                topic_text = (
                    thread.get("title", "")
                    + " "
                    + (thread["posts"][0].get("body", "") if thread["posts"] else "")
                )[:1000]
                dept_threads[dept].append({
                    **thread,
                    "dept": dept,
                    "start_time": first_time,
                    "_topic_text": topic_text,
                    "_topic_emb": embed_text(topic_text),
                })

        if len(dept_threads) < 2:
            return {"rate": 0.0, "pairs": [], "events": 0}

        window_secs = cfg.trigger_correlation_window_hours * 3600
        trigger_events = 0
        trigger_pairs: list[tuple[str, str, float]] = []
        total_dept_activity = sum(len(v) for v in dept_threads.values())

        depts = list(dept_threads.keys())
        for i in range(len(depts)):
            for j in range(len(depts)):
                if i == j:
                    continue
                dept_a, dept_b = depts[i], depts[j]
                for ta in dept_threads[dept_a]:
                    for tb in dept_threads[dept_b]:
                        time_diff = tb["start_time"] - ta["start_time"]
                        if time_diff <= 0 or time_diff > window_secs:
                            continue
                        sim = _cosine_similarity(ta["_topic_emb"], tb["_topic_emb"])
                        if sim >= cfg.trigger_topic_similarity_threshold:
                            trigger_events += 1
                            trigger_pairs.append((dept_a, dept_b, round(sim, 3)))

        rate = trigger_events / total_dept_activity if total_dept_activity > 0 else 0.0
        rate = min(rate, 1.0)

        return {"rate": rate, "pairs": trigger_pairs[:20], "events": trigger_events}

    # ------------------------------------------------------------------
    # Metric 4: Convergence Correctness
    # ------------------------------------------------------------------

    async def _compute_convergence_correctness(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 4: Convergence Correctness.

        Detect convergence (multiple agents saying similar things) and track
        whether converged conclusions have verifiable outcomes. AD-583f
        populates correctness via ObservableStateVerifier (satisfies AD-569d).
        """
        cfg = self._config
        convergence_events = 0

        for thread in threads:
            posts = thread["posts"]
            if len(posts) < cfg.convergence_min_agreeing + 1:
                continue

            # Group posts by author and embed
            author_embeddings: dict[str, list[float]] = {}
            for post in posts:
                author = post.get("author_id", "")
                body = post.get("body", "")
                if not author or not body or author in author_embeddings:
                    continue
                author_embeddings[author] = embed_text(body[:1000])

            if len(author_embeddings) < cfg.convergence_min_agreeing:
                continue

            # Check for pairwise convergence
            authors = list(author_embeddings.keys())
            agreeing_pairs = 0
            total_pairs = 0
            for i in range(len(authors)):
                for j in range(i + 1, len(authors)):
                    sim = _cosine_similarity(
                        author_embeddings[authors[i]],
                        author_embeddings[authors[j]],
                    )
                    total_pairs += 1
                    if sim >= cfg.convergence_similarity_threshold:
                        agreeing_pairs += 1

            if total_pairs > 0 and agreeing_pairs / total_pairs >= 0.5:
                convergence_events += 1

        # AD-583f: Verify converging claims against observable state
        if self._verifier and convergence_events > 0:
            all_claims: list[str] = []
            for thread in threads:
                for post in thread["posts"]:
                    body = post.get("body", "")
                    if body:
                        all_claims.append(body[:500])

            try:
                results = await self._verifier.verify_claims(all_claims[:10])
                correct = sum(1 for r in results if r.verified is True)
                incorrect = sum(1 for r in results if r.verified is False)
                total_verified = correct + incorrect
                return {
                    "total": convergence_events,
                    "correct": correct,
                    "incorrect": incorrect,
                    "unverified": convergence_events - total_verified,
                    "correctness_rate": correct / total_verified if total_verified > 0 else None,
                }
            except Exception:
                logger.debug("AD-583f: Verification in convergence correctness failed", exc_info=True)

        return {
            "total": convergence_events,
            "correct": 0,
            "incorrect": 0,
            "unverified": convergence_events,
            "correctness_rate": None,
        }

    # ------------------------------------------------------------------
    # Metric 5: Anchor-Grounded Emergence
    # ------------------------------------------------------------------

    async def _compute_anchor_grounded_emergence(
        self,
        threads: list[dict[str, Any]],
        episodic_memory: Any | None,
    ) -> dict[str, Any]:
        """Metric 5: Anchor-Grounded Emergence.

        Check whether emergent insights are backed by independently-observed
        evidence via compute_anchor_independence() from social_verification.
        """
        cfg = self._config

        if not episodic_memory:
            return {"grounded_rate": 0.0, "independence_score": 0.0, "analyzed_threads": 0}

        try:
            from probos.cognitive.social_verification import compute_anchor_independence
        except ImportError:
            return {"grounded_rate": 0.0, "independence_score": 0.0, "analyzed_threads": 0}

        independence_scores: list[float] = []
        grounded_count = 0
        analyzed = 0

        for thread in threads:
            agent_ids = list(thread["unique_authors"])
            if len(agent_ids) < 2:
                continue

            try:
                all_episodes: list[Any] = []
                for agent_id in agent_ids[:5]:
                    eps = await episodic_memory.recall(
                        query="",
                        agent_id=agent_id,
                        limit=10,
                    )
                    if eps:
                        all_episodes.extend(eps)

                if len(all_episodes) < cfg.anchor_independence_min_episodes:
                    continue

                independence = compute_anchor_independence(all_episodes)
                independence_scores.append(independence)
                analyzed += 1

                if independence > 0.3:
                    grounded_count += 1

            except Exception:
                logger.debug(
                    "AD-569: Anchor analysis failed for thread %s",
                    thread.get("thread_id"),
                )
                continue

        mean_independence = (
            sum(independence_scores) / len(independence_scores)
            if independence_scores
            else 0.0
        )
        grounded_rate = grounded_count / analyzed if analyzed > 0 else 0.0

        return {
            "grounded_rate": grounded_rate,
            "independence_score": mean_independence,
            "analyzed_threads": analyzed,
        }
