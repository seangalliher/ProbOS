# AD-569: Observation-Grounded Crew Intelligence Metrics

**Status:** Build prompt — ready for builder
**Depends on:** AD-557 (EmergenceMetricsEngine) ✅, Ward Room threads ✅, Social verification (AD-567f) ✅
**Pattern:** Follow EmergenceMetricsEngine (AD-557) template exactly

## Problem

Existing Tier 3 probes (AD-566e) measure mathematical properties of the communication graph (PID synergy ratios, Gini coefficients, entropy) but not the *content and consequence* of collaboration. An agent cluster producing novel multi-perspective analysis scores the same as redundant chatter because the probes don't examine what was said or what resulted.

AD-569 adds the behavioral complement — five metrics that examine observable collaboration quality.

## Deliverables Overview

This is a multi-phased build. Execute phases in order.

### Phase 1: Engine + Config + Snapshot (foundation)
- NEW: `src/probos/cognitive/behavioral_metrics.py` — `BehavioralMetricsEngine` + `BehavioralSnapshot`
- MODIFY: `src/probos/config.py` — `BehavioralMetricsConfig` + wire into `SystemConfig`

### Phase 2: Five Metrics (the computation)
- All five metrics implemented inside `BehavioralMetricsEngine.compute_behavioral_metrics()`

### Phase 3: Dream Step + Startup Wiring
- MODIFY: `src/probos/cognitive/dreaming.py` — Dream Step 13, constructor param, DreamReport fields
- MODIFY: `src/probos/types.py` — DreamReport fields
- MODIFY: `src/probos/startup/dreaming.py` — instantiate + wire engine
- MODIFY: `src/probos/startup/results.py` — add to DreamingResult
- MODIFY: `src/probos/runtime.py` — store engine reference

### Phase 4: API Routes
- MODIFY: `src/probos/routers/system.py` — `/behavioral-metrics` + `/behavioral-metrics/history`

### Phase 5: Qualification Probes
- NEW: `src/probos/cognitive/behavioral_probes.py` — 5 Tier 3 probes
- MODIFY: `src/probos/runtime.py` — register probes

### Phase 6: Events
- MODIFY: `src/probos/events.py` — new event types

### Phase 7: Tests
- NEW: `tests/test_behavioral_metrics.py` — comprehensive tests

---

## Phase 1: Engine + Config + Snapshot

### 1a. `BehavioralMetricsConfig` in `src/probos/config.py`

Add this Pydantic `BaseModel` class near `EmergenceMetricsConfig` (around line 664):

```python
class BehavioralMetricsConfig(BaseModel):
    """AD-569: Observation-Grounded Crew Intelligence Metrics."""

    # Thread analysis
    thread_lookback_hours: float = 72.0  # How far back to analyze threads
    min_thread_contributors: int = 2  # Minimum unique authors for a qualifying thread
    min_thread_posts: int = 3  # Minimum posts for a qualifying thread

    # Frame Diversity (Metric 1)
    frame_diversity_min_departments: int = 2  # Need 2+ departments represented

    # Synthesis Detection (Metric 2)
    synthesis_novelty_threshold: float = 0.35  # Cosine distance threshold for "novel"
    synthesis_min_thread_posts: int = 4  # Threads need 4+ posts for synthesis analysis

    # Cross-Department Trigger (Metric 3)
    trigger_correlation_window_hours: float = 24.0  # Window for topic trigger correlation
    trigger_topic_similarity_threshold: float = 0.6  # Cosine similarity for "same topic"

    # Convergence Correctness (Metric 4)
    convergence_similarity_threshold: float = 0.75  # When posts are "converging"
    convergence_min_agreeing: int = 2  # Minimum agents agreeing for convergence

    # Anchor-Grounded Emergence (Metric 5)
    anchor_independence_min_episodes: int = 3  # Minimum episodes for anchor analysis

    # Snapshot history
    max_snapshots: int = 100  # Rolling window of historical snapshots
```

Add to `SystemConfig` class (around line 786, near `emergence_metrics`):

```python
behavioral_metrics: BehavioralMetricsConfig = BehavioralMetricsConfig()
```

### 1b. NEW FILE: `src/probos/cognitive/behavioral_metrics.py`

```python
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
from probos.knowledge.embeddings import embed_text, compute_similarity

logger = logging.getLogger(__name__)
```

#### `BehavioralSnapshot` dataclass

```python
@dataclass
class BehavioralSnapshot:
    """Ship-level behavioral metrics at a point in time."""

    timestamp: float = 0.0

    # Metric 1: Analytical Frame Diversity
    frame_diversity_score: float = 0.0  # 0-1, mean cross-thread frame diversity
    frame_diversity_threads: int = 0  # Threads analyzed for frame diversity
    department_representation: dict[str, int] = field(default_factory=dict)  # dept → contribution count

    # Metric 2: Synthesis Detection
    synthesis_rate: float = 0.0  # Fraction of threads with detected synthesis
    synthesis_threads: int = 0  # Threads with synthesis detected
    total_novel_elements: int = 0  # Total novel elements across all threads

    # Metric 3: Cross-Department Trigger Rate
    cross_dept_trigger_rate: float = 0.0  # Fraction of cross-dept triggers vs total dept activity
    trigger_pairs: list[tuple[str, str, float]] = field(default_factory=list)  # (dept_a, dept_b, similarity)
    trigger_events: int = 0  # Total cross-department trigger events

    # Metric 4: Convergence Correctness
    convergence_events: int = 0  # Total convergence events detected
    verified_correct: int = 0  # Convergences with positive outcome feedback
    verified_incorrect: int = 0  # Convergences with negative outcome feedback
    unverified: int = 0  # Convergences without ground truth
    convergence_correctness_rate: float | None = None  # correct / (correct + incorrect), None if no ground truth

    # Metric 5: Anchor-Grounded Emergence
    anchor_grounded_rate: float = 0.0  # Fraction of emergence backed by independent anchors
    anchor_independence_score: float = 0.0  # Mean anchor independence across analyzed threads
    anchor_analyzed_threads: int = 0  # Threads with sufficient anchor data

    # Aggregate
    threads_analyzed: int = 0
    behavioral_quality_score: float = 0.0  # Composite 0-1 score (mean of available metrics)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return asdict(self)
```

#### `BehavioralMetricsEngine` class

```python
class BehavioralMetricsEngine:
    """Computes observation-grounded behavioral metrics for crew collaboration.

    Follows the same pattern as EmergenceMetricsEngine (AD-557):
    - Called during dream cycle (Step 13)
    - Stores rolling snapshot history
    - Exposes latest_snapshot and snapshots properties
    - Read-only consumer of Ward Room and episodic memory data
    """

    def __init__(self, config: BehavioralMetricsConfig | None = None) -> None:
        self._config = config or BehavioralMetricsConfig()
        self._snapshots: deque[BehavioralSnapshot] = deque(maxlen=self._config.max_snapshots)

    @property
    def latest_snapshot(self) -> BehavioralSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshots(self) -> list[BehavioralSnapshot]:
        return list(self._snapshots)
```

#### Core computation method

```python
    async def compute_behavioral_metrics(
        self,
        ward_room: Any,
        episodic_memory: Any | None = None,
        get_department: Callable[[str], str | None] | None = None,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> BehavioralSnapshot:
        """Compute all five behavioral metrics from Ward Room thread data.

        Args:
            ward_room: WardRoomService for thread data access.
            episodic_memory: EpisodicMemory for anchor analysis (Metric 5).
            get_department: fn(agent_id) -> department name or None.
            emit_event_fn: Optional event emission callback.

        Returns:
            BehavioralSnapshot with all computed metrics.
        """
        cfg = self._config
        now = time.time()

        # 1. Retrieve qualifying threads (same pattern as EmergenceMetricsEngine)
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

            posts_raw = thread_data.get("posts", []) if isinstance(thread_data, dict) else getattr(thread_data, "posts", [])
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
                "channel_id": thread.channel_id if hasattr(thread, "channel_id") else thread.get("channel_id", ""),
                "channel_name": thread.channel_name if hasattr(thread, "channel_name") else thread.get("channel_name", ""),
                "title": thread.title if hasattr(thread, "title") else thread.get("title", ""),
            })

        threads_analyzed = len(qualifying_threads)
        if threads_analyzed == 0:
            snapshot = BehavioralSnapshot(timestamp=now, threads_analyzed=0)
            self._snapshots.append(snapshot)
            return snapshot

        # 3. Compute each metric
        # Metric 1
        frame_result = self._compute_frame_diversity(qualifying_threads, get_department)
        # Metric 2
        synthesis_result = await self._compute_synthesis_detection(qualifying_threads)
        # Metric 3
        trigger_result = self._compute_cross_dept_triggers(qualifying_threads, get_department)
        # Metric 4
        convergence_result = await self._compute_convergence_correctness(qualifying_threads)
        # Metric 5
        anchor_result = await self._compute_anchor_grounded_emergence(
            qualifying_threads, episodic_memory
        )

        # 4. Composite score (mean of available non-None metrics)
        available_scores = [
            frame_result["score"],
            synthesis_result["rate"],
            trigger_result["rate"],
            anchor_result["grounded_rate"],
        ]
        # Include convergence correctness only if we have ground truth
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
```

---

## Phase 2: Five Metric Implementations

All private methods on `BehavioralMetricsEngine`. Implement in the same file.

### Metric 1: Analytical Frame Diversity

Measures whether agents from different departments bring distinct analytical perspectives.

```python
    def _compute_frame_diversity(
        self,
        threads: list[dict[str, Any]],
        get_department: Callable[[str], str | None] | None,
    ) -> dict[str, Any]:
        """Metric 1: Analytical Frame Diversity.

        For each multi-department thread, compute embedding-based diversity
        of per-department contributions. High diversity = different departments
        bring genuinely different analytical frames (not just restating).

        Returns dict with keys: score, threads, dept_counts.
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

            # Pairwise cosine distance (1 - similarity) between department centroids
            depts = list(dept_embeddings.keys())
            if len(depts) < 2:
                continue

            distances: list[float] = []
            for i in range(len(depts)):
                for j in range(i + 1, len(depts)):
                    sim = compute_similarity(dept_embeddings[depts[i]], dept_embeddings[depts[j]])
                    distances.append(1.0 - sim)  # distance = diversity

            if distances:
                diversity_scores.append(sum(distances) / len(distances))
                analyzed += 1

        score = sum(diversity_scores) / len(diversity_scores) if diversity_scores else 0.0
        return {"score": score, "threads": analyzed, "dept_counts": dict(dept_counts)}
```

### Metric 2: Synthesis Detection

Identifies novel elements in multi-agent threads that can't be attributed to any single contributor.

```python
    async def _compute_synthesis_detection(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 2: Synthesis Detection.

        For each thread, embed the full concatenated thread body and each
        individual contribution. Novel elements = aspects of the thread
        embedding that have low similarity to ALL individual contributions.

        Approach: compare the thread's overall embedding against each
        individual post's embedding. If the thread embedding is
        dissimilar from the most-similar individual post (max similarity
        to any single post is still below threshold), synthesis is present.

        Returns dict with keys: rate, threads_with_synthesis, novel_count.
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

            # Thread-level embedding (concatenation of all bodies)
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
            max_sim = max(
                compute_similarity(thread_embedding, pe) for pe in post_embeddings
            ) if post_embeddings else 1.0

            # If the combined thread is sufficiently different from any single
            # post, synthesis occurred — the whole > sum of parts
            novelty = 1.0 - max_sim
            if novelty >= cfg.synthesis_novelty_threshold:
                synthesis_count += 1
                total_novel += 1  # Count each synthesizing thread as one novel element

        rate = synthesis_count / eligible if eligible > 0 else 0.0
        return {
            "rate": rate,
            "threads_with_synthesis": synthesis_count,
            "novel_count": total_novel,
        }
```

### Metric 3: Cross-Department Trigger Rate

Measures how often a finding in one department drives investigation in another.

```python
    def _compute_cross_dept_triggers(
        self,
        threads: list[dict[str, Any]],
        get_department: Callable[[str], str | None] | None,
    ) -> dict[str, Any]:
        """Metric 3: Cross-Department Trigger Rate.

        Detect temporal sequences where activity in one department channel
        is followed by activity in another department channel on a similar
        topic. Uses thread titles + first post embeddings for topic matching.

        Returns dict with keys: rate, pairs, events.
        """
        cfg = self._config
        if not get_department:
            return {"rate": 0.0, "pairs": [], "events": 0}

        # Group threads by department (inferred from channel or first author)
        dept_threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for thread in threads:
            # Determine department from first author
            first_author = ""
            for p in thread["posts"]:
                if p.get("author_id"):
                    first_author = p["author_id"]
                    break
            if not first_author:
                continue
            dept = get_department(first_author)
            if dept:
                # Get thread start time from first post
                first_time = min(
                    (p.get("created_at", 0.0) for p in thread["posts"] if p.get("created_at")),
                    default=0.0,
                )
                dept_threads[dept].append({
                    **thread,
                    "dept": dept,
                    "start_time": first_time,
                    "_topic_text": (thread.get("title", "") + " " +
                                    (thread["posts"][0].get("body", "") if thread["posts"] else ""))[:1000],
                })

        if len(dept_threads) < 2:
            return {"rate": 0.0, "pairs": [], "events": 0}

        # Embed topic texts
        for dept, dthreads in dept_threads.items():
            for dt in dthreads:
                dt["_topic_emb"] = embed_text(dt["_topic_text"])

        # Find cross-department triggers: thread in dept A precedes
        # similar-topic thread in dept B within the correlation window
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
                        # B must follow A within window
                        time_diff = tb["start_time"] - ta["start_time"]
                        if time_diff <= 0 or time_diff > window_secs:
                            continue
                        # Topic similarity check
                        sim = compute_similarity(ta["_topic_emb"], tb["_topic_emb"])
                        if sim >= cfg.trigger_topic_similarity_threshold:
                            trigger_events += 1
                            trigger_pairs.append((dept_a, dept_b, round(sim, 3)))

        rate = trigger_events / total_dept_activity if total_dept_activity > 0 else 0.0
        # Cap at 1.0 (can exceed if same activity triggers multiple depts)
        rate = min(rate, 1.0)

        return {"rate": rate, "pairs": trigger_pairs[:20], "events": trigger_events}
```

### Metric 4: Convergence Correctness

Tracks whether converged conclusions are actually correct. Since automated ground truth is limited, this metric primarily *records* convergence events and supports future feedback annotation.

```python
    async def _compute_convergence_correctness(
        self,
        threads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Metric 4: Convergence Correctness.

        Detect convergence (multiple agents saying similar things) and
        track whether converged conclusions have verifiable outcomes.

        For now: detect convergence events and classify as unverified.
        Ground truth integration (human feedback, incident resolution)
        is deferred to AD-569d. This builds the detection infrastructure.

        Returns dict with keys: total, correct, incorrect, unverified, correctness_rate.
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
                    continue  # Use first post per author for convergence
                author_embeddings[author] = embed_text(body[:1000])

            if len(author_embeddings) < cfg.convergence_min_agreeing:
                continue

            # Check for pairwise convergence
            authors = list(author_embeddings.keys())
            agreeing_pairs = 0
            total_pairs = 0
            for i in range(len(authors)):
                for j in range(i + 1, len(authors)):
                    sim = compute_similarity(
                        author_embeddings[authors[i]],
                        author_embeddings[authors[j]],
                    )
                    total_pairs += 1
                    if sim >= cfg.convergence_similarity_threshold:
                        agreeing_pairs += 1

            # Convergence = majority of pairs agree
            if total_pairs > 0 and agreeing_pairs / total_pairs >= 0.5:
                convergence_events += 1

        # Ground truth: deferred to AD-569d
        # For now, all convergence events are unverified
        return {
            "total": convergence_events,
            "correct": 0,
            "incorrect": 0,
            "unverified": convergence_events,
            "correctness_rate": None,  # No ground truth yet
        }
```

### Metric 5: Anchor-Grounded Emergence

Checks whether emergent insights are backed by independently-observed evidence.

```python
    async def _compute_anchor_grounded_emergence(
        self,
        threads: list[dict[str, Any]],
        episodic_memory: Any | None,
    ) -> dict[str, Any]:
        """Metric 5: Anchor-Grounded Emergence.

        For qualifying threads, check whether the contributing agents'
        episodic memories have independent anchor provenance. Uses
        compute_anchor_independence() from social_verification.

        High anchor independence + synthesis = genuine collaborative insight.
        Low anchor independence + synthesis = potential cascade confabulation.

        Returns dict with keys: grounded_rate, independence_score, analyzed_threads.
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
            # Get agent IDs that participated
            agent_ids = list(thread["unique_authors"])
            if len(agent_ids) < 2:
                continue

            # Retrieve recent episodes for these agents
            try:
                all_episodes: list[Any] = []
                for agent_id in agent_ids[:5]:  # Cap at 5 agents
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

                # "Grounded" if independence score exceeds threshold (0.3 from social_verification config default)
                if independence > 0.3:
                    grounded_count += 1

            except Exception:
                logger.debug("AD-569: Anchor analysis failed for thread %s", thread.get("thread_id"))
                continue

        mean_independence = (
            sum(independence_scores) / len(independence_scores)
            if independence_scores else 0.0
        )
        grounded_rate = grounded_count / analyzed if analyzed > 0 else 0.0

        return {
            "grounded_rate": grounded_rate,
            "independence_score": mean_independence,
            "analyzed_threads": analyzed,
        }
```

---

## Phase 3: Dream Step + Startup Wiring

### 3a. MODIFY `src/probos/types.py` — Add DreamReport fields

After the `# AD-557: Emergence metrics` block (line ~453), add:

```python
    # AD-569: Behavioral metrics
    behavioral_quality_score: float | None = None
    frame_diversity_score: float | None = None
    synthesis_rate: float | None = None
    cross_dept_trigger_rate: float | None = None
    anchor_grounded_rate: float | None = None
```

### 3b. MODIFY `src/probos/cognitive/dreaming.py`

**Constructor** — Add parameter after `activation_tracker` (line ~76):

```python
        behavioral_metrics_engine: Any = None,  # AD-569: behavioral metrics engine
```

Store it:

```python
        self._behavioral_metrics_engine = behavioral_metrics_engine  # AD-569
```

**Dream Step 13** — Add after Step 12 (activation-based pruning, after line ~917):

```python
        # Step 13: Behavioral Metrics (AD-569)
        behavioral_quality_score = None
        frame_diversity_score = None
        synthesis_rate = None
        cross_dept_trigger_rate = None
        anchor_grounded_rate = None
        if self._behavioral_metrics_engine and self._ward_room:
            try:
                bm_snapshot = await self._behavioral_metrics_engine.compute_behavioral_metrics(
                    ward_room=self._ward_room,
                    episodic_memory=self.episodic_memory,
                    get_department=self._get_department,
                )
                behavioral_quality_score = bm_snapshot.behavioral_quality_score
                frame_diversity_score = bm_snapshot.frame_diversity_score
                synthesis_rate = bm_snapshot.synthesis_rate
                cross_dept_trigger_rate = bm_snapshot.cross_dept_trigger_rate
                anchor_grounded_rate = bm_snapshot.anchor_grounded_rate
                logger.debug(
                    "Step 13 behavioral metrics: quality=%.3f, diversity=%.3f, "
                    "synthesis=%.3f, triggers=%.3f, anchored=%.3f, threads=%d",
                    bm_snapshot.behavioral_quality_score,
                    bm_snapshot.frame_diversity_score,
                    bm_snapshot.synthesis_rate,
                    bm_snapshot.cross_dept_trigger_rate,
                    bm_snapshot.anchor_grounded_rate,
                    bm_snapshot.threads_analyzed,
                )
            except Exception as e:
                logger.debug("Step 13 behavioral metrics failed: %s", e)
```

**DreamReport construction** — In the `report = DreamReport(...)` block (around line 921+), add after the activation fields:

```python
            # AD-569: Behavioral metrics
            behavioral_quality_score=behavioral_quality_score,
            frame_diversity_score=frame_diversity_score,
            synthesis_rate=synthesis_rate,
            cross_dept_trigger_rate=cross_dept_trigger_rate,
            anchor_grounded_rate=anchor_grounded_rate,
```

### 3c. MODIFY `src/probos/startup/dreaming.py`

**Import** — Add at top with other imports (after line 16):

```python
from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
```

**Instantiate** — After `notebook_quality_engine` creation (around line 71):

```python
    # AD-569: Behavioral Metrics Engine
    behavioral_metrics_engine = BehavioralMetricsEngine(config.behavioral_metrics)
```

**Wire to DreamingEngine** — Add parameter to the `DreamingEngine(...)` constructor call (around line 111):

```python
            behavioral_metrics_engine=behavioral_metrics_engine,
```

**Store on result** — In the `DreamingResult(...)` construction (around line 236), add:

```python
        behavioral_metrics_engine=behavioral_metrics_engine,
```

### 3d. MODIFY `src/probos/startup/results.py`

Add to `DreamingResult` dataclass (after `retrieval_practice_engine`):

```python
    behavioral_metrics_engine: Any = None  # AD-569
```

### 3e. MODIFY `src/probos/runtime.py`

**Field declaration** — After `self._emergence_metrics_engine` (around line 485):

```python
        self._behavioral_metrics_engine: Any = None  # AD-569
```

**Wire from startup** — After `self._notebook_quality_engine` assignment (around line 1259):

```python
        self._behavioral_metrics_engine = dream_result.behavioral_metrics_engine  # AD-569
```

---

## Phase 4: API Routes

### MODIFY `src/probos/routers/system.py`

Add after the `/emergence/history` route (around line 214):

```python
@router.get("/behavioral-metrics")
async def get_behavioral_metrics(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-569: Return cached behavioral metrics from last dream cycle."""
    engine = getattr(runtime, "_behavioral_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Behavioral metrics engine not wired"}
    snapshot = engine.latest_snapshot
    if not snapshot:
        return {"status": "no_data", "message": "No behavioral metrics computed yet"}
    return {"status": "ok", **snapshot.to_dict()}


@router.get("/behavioral-metrics/history")
async def get_behavioral_metrics_history(
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-569: Return behavioral metrics time series."""
    engine = getattr(runtime, "_behavioral_metrics_engine", None)
    if not engine:
        return {"status": "not_available", "snapshots": []}
    snapshots = engine.snapshots
    return {
        "status": "ok",
        "count": len(snapshots),
        "snapshots": [s.to_dict() for s in snapshots[-limit:]],
    }
```

---

## Phase 5: Qualification Probes

### NEW FILE: `src/probos/cognitive/behavioral_probes.py`

Five Tier 3 probes — one per behavioral metric. Same pattern as `collective_tests.py`.

```python
"""AD-569: Tier 3 Behavioral Qualification Probes.

Five crew-wide probes measuring observable collaboration quality.
Read-only consumers of BehavioralMetricsEngine snapshots.
No LLM calls, no triggering new computations.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.cognitive.qualification import TestResult

logger = logging.getLogger(__name__)

CREW_AGENT_ID = "__crew__"


def _skip_result(test_name: str, reason: str) -> TestResult:
    """Return a skip-passing TestResult."""
    return TestResult(
        agent_id=CREW_AGENT_ID,
        test_name=test_name,
        tier=3,
        score=0.0,
        passed=True,
        timestamp=time.time(),
        duration_ms=0.0,
        details={"skipped": True, "reason": reason},
    )


class FrameDiversityProbe:
    """Measures analytical frame diversity across departments."""

    @property
    def name(self) -> str:
        return "frame_diversity"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Analytical Frame Diversity — distinct perspectives per department in multi-agent threads"

    @property
    def threshold(self) -> float:
        return 0.0  # Profile measurement

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.frame_diversity_score,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "frame_diversity_score": snapshot.frame_diversity_score,
                "threads_analyzed": snapshot.frame_diversity_threads,
                "department_representation": snapshot.department_representation,
            },
        )


class SynthesisDetectionProbe:
    """Measures synthesis rate — novel insights from collaboration."""

    @property
    def name(self) -> str:
        return "synthesis_detection"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Synthesis Detection — novel elements not attributable to any single agent"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.synthesis_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "synthesis_rate": snapshot.synthesis_rate,
                "synthesis_threads": snapshot.synthesis_threads,
                "total_novel_elements": snapshot.total_novel_elements,
            },
        )


class CrossDeptTriggerProbe:
    """Measures cross-department investigation trigger rate."""

    @property
    def name(self) -> str:
        return "cross_dept_trigger_rate"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Cross-Department Trigger Rate — findings in one department driving investigation in another"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.cross_dept_trigger_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "trigger_rate": snapshot.cross_dept_trigger_rate,
                "trigger_events": snapshot.trigger_events,
                "trigger_pairs": snapshot.trigger_pairs[:10],
            },
        )


class ConvergenceCorrectnessProbe:
    """Measures correctness rate of converged conclusions."""

    @property
    def name(self) -> str:
        return "convergence_correctness"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Convergence Correctness — quality of converged agent conclusions (when verifiable)"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        score = snapshot.convergence_correctness_rate if snapshot.convergence_correctness_rate is not None else 0.0
        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=score,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "convergence_events": snapshot.convergence_events,
                "verified_correct": snapshot.verified_correct,
                "verified_incorrect": snapshot.verified_incorrect,
                "unverified": snapshot.unverified,
                "correctness_rate": snapshot.convergence_correctness_rate,
            },
        )


class AnchorGroundedEmergenceProbe:
    """Measures emergence backed by independent anchor provenance."""

    @property
    def name(self) -> str:
        return "anchor_grounded_emergence"

    @property
    def tier(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Anchor-Grounded Emergence — insights backed by independently-observed evidence"

    @property
    def threshold(self) -> float:
        return 0.0

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        engine = getattr(runtime, "_behavioral_metrics_engine", None)
        if not engine:
            return _skip_result(self.name, "Behavioral metrics engine not available")
        snapshot = engine.latest_snapshot
        if not snapshot:
            return _skip_result(self.name, "No behavioral snapshot available")

        return TestResult(
            agent_id=CREW_AGENT_ID,
            test_name=self.name,
            tier=3,
            score=snapshot.anchor_grounded_rate,
            passed=True,
            timestamp=time.time(),
            duration_ms=0.0,
            details={
                "grounded_rate": snapshot.anchor_grounded_rate,
                "independence_score": snapshot.anchor_independence_score,
                "analyzed_threads": snapshot.anchor_analyzed_threads,
            },
        )
```

### MODIFY `src/probos/runtime.py` — Register probes

After the AD-566e probe registration block (around line 1197), add:

```python
            # AD-569: Register Tier 3 behavioral probes
            from probos.cognitive.behavioral_probes import (
                FrameDiversityProbe,
                SynthesisDetectionProbe,
                CrossDeptTriggerProbe,
                ConvergenceCorrectnessProbe,
                AnchorGroundedEmergenceProbe,
            )
            for test_cls in (FrameDiversityProbe, SynthesisDetectionProbe, CrossDeptTriggerProbe, ConvergenceCorrectnessProbe, AnchorGroundedEmergenceProbe):
                self._qualification_harness.register_test(test_cls())
```

---

## Phase 6: Events

### MODIFY `src/probos/events.py`

Add after the AD-557 events (around line 132):

```python
    BEHAVIORAL_METRICS_UPDATED = "behavioral_metrics_updated"  # AD-569: behavioral snapshot computed
```

---

## Phase 7: Tests

### NEW FILE: `tests/test_behavioral_metrics.py`

Implement the following test classes. Use `pytest` and `pytest-asyncio`. Follow the same mock patterns as `tests/test_emergence_metrics.py`.

**Test Class 1: `TestBehavioralMetricsConfig`** (3 tests)
1. `test_default_config` — verify all defaults are set
2. `test_custom_config` — override specific fields, verify
3. `test_config_on_system_config` — `SystemConfig().behavioral_metrics` exists and is correct type

**Test Class 2: `TestBehavioralSnapshot`** (3 tests)
1. `test_default_snapshot` — all fields have sensible defaults
2. `test_to_dict` — serialization works, all fields present
3. `test_snapshot_with_data` — construct with real values, verify

**Test Class 3: `TestBehavioralMetricsEngine`** (4 tests)
1. `test_engine_init` — engine initializes with config
2. `test_latest_snapshot_none` — no computation yet → None
3. `test_snapshots_empty` — no computation yet → empty list
4. `test_snapshot_history_limit` — max_snapshots deque works

**Test Class 4: `TestFrameDiversity`** (4 tests)
1. `test_frame_diversity_multi_dept` — 2+ departments → positive diversity score
2. `test_frame_diversity_single_dept` — single department → score 0.0
3. `test_frame_diversity_no_department_fn` — no get_department → score 0.0
4. `test_frame_diversity_identical_posts` — same content across depts → low diversity

**Test Class 5: `TestSynthesisDetection`** (3 tests)
1. `test_synthesis_detected` — diverse multi-agent thread → synthesis_rate > 0
2. `test_no_synthesis_similar_posts` — all posts similar → no synthesis
3. `test_synthesis_below_min_posts` — too few posts → skipped

**Test Class 6: `TestCrossDeptTriggers`** (3 tests)
1. `test_trigger_detected` — sequential cross-dept similar topics → trigger_events > 0
2. `test_no_trigger_single_dept` — single department → rate 0
3. `test_no_trigger_dissimilar_topics` — cross-dept but different topics → rate 0

**Test Class 7: `TestConvergenceCorrectness`** (3 tests)
1. `test_convergence_detected` — similar posts from multiple agents → events > 0
2. `test_convergence_unverified` — all events are unverified (no ground truth yet)
3. `test_no_convergence_diverse_posts` — very different posts → no convergence

**Test Class 8: `TestAnchorGroundedEmergence`** (3 tests)
1. `test_anchor_analysis_with_memory` — mock episodic_memory + social_verification → positive score
2. `test_anchor_no_memory` — no episodic_memory → score 0
3. `test_anchor_insufficient_episodes` — fewer than min_episodes → skipped

**Test Class 9: `TestComputeBehavioralMetrics`** (3 tests — full integration)
1. `test_full_computation` — mock ward_room with qualifying threads → snapshot with all metrics populated
2. `test_empty_threads` — no qualifying threads → snapshot with zeros
3. `test_event_emission` — verify BEHAVIORAL_METRICS_UPDATED event emitted

**Test Class 10: `TestBehavioralProbes`** (5 tests — one per probe)
1. `test_frame_diversity_probe` — mock runtime with engine → TestResult
2. `test_synthesis_probe` — mock runtime → TestResult
3. `test_cross_dept_trigger_probe` — mock runtime → TestResult
4. `test_convergence_correctness_probe` — mock runtime → TestResult
5. `test_anchor_grounded_probe` — mock runtime → TestResult

**Test Class 11: `TestAPIRoutes`** (2 tests)
1. `test_behavioral_metrics_endpoint` — mock runtime → 200 with snapshot data
2. `test_behavioral_metrics_history` — mock runtime → 200 with snapshots list

**Mock patterns for Ward Room:**

```python
# Use this pattern for mocking ward_room in tests:

class MockThread:
    def __init__(self, thread_id, channel_id="ch-1", channel_name="engineering", title="Test Thread"):
        self.id = thread_id
        self.channel_id = channel_id
        self.channel_name = channel_name
        self.title = title

class MockWardRoom:
    def __init__(self, threads_data: list[dict]):
        self._threads = threads_data  # list of {"thread": MockThread, "posts": [...]}

    async def browse_threads(self, agent_id="", channels=None, limit=50, since=0.0):
        return [td["thread"] for td in self._threads]

    async def get_thread(self, thread_id: str):
        for td in self._threads:
            if td["thread"].id == thread_id:
                return {"posts": td["posts"]}
        return None
```

**Total expected tests: ~36**

---

## Engineering Principles Compliance

| Principle | How Satisfied |
|-----------|--------------|
| **SOLID/S** | `BehavioralMetricsEngine` — one responsibility (compute behavioral metrics). Each probe is a single class. |
| **SOLID/O** | Engine is open for extension (add new metrics), closed for modification (each metric is a private method). |
| **SOLID/D** | Constructor injection of config, ward_room, episodic_memory. No direct imports of concrete services. |
| **SOLID/I** | Probes depend on `TestResult` protocol, not entire runtime. Engine depends on narrow ward_room interface. |
| **Law of Demeter** | Engine accesses ward_room via public API (`browse_threads`, `get_thread`). No private member access. |
| **Fail Fast** | Each metric wrapped in try/except with log-and-degrade. Dream step follows existing pattern. |
| **DRY** | Reuses `embed_text`/`compute_similarity` from knowledge.embeddings. Thread retrieval follows AD-557 pattern. `_skip_result` shared helper for probes. |
| **Cloud-Ready** | No direct SQLite. Ward Room data accessed through service API. Config via Pydantic model. |
| **Defense in Depth** | Input validation at Thread level (min contributors, min posts). Graceful degradation when dependencies missing. |

## Scope Boundary

**In scope:**
- `BehavioralMetricsEngine` with 5 metrics
- `BehavioralSnapshot` dataclass
- `BehavioralMetricsConfig` on SystemConfig
- Dream Step 13 integration
- DreamReport fields
- API routes (`/behavioral-metrics`, `/behavioral-metrics/history`)
- 5 Tier 3 qualification probes
- `BEHAVIORAL_METRICS_UPDATED` event
- ~36 tests

**Out of scope (deferred):**
- AD-569d: Ground truth feedback loop for Convergence Correctness
- AD-569f: Psychometric measurement infrastructure (ICC, r_wg, G-theory, MTMM)
- AD-569g: HXI Behavioral Dashboard
- Thread "concluded" lifecycle (inferred from thread maturity signals instead)
- VitalsMonitor integration

## Builder Instructions

Execute: `Read and execute the build prompt in d:\ProbOS\prompts\ad-569-behavioral-metrics.md`

Build phases 1-7 in order. Run tests after each phase to catch regressions early. Final verification:
1. All new tests pass
2. Existing emergence metrics tests still pass (`tests/test_emergence_metrics.py`)
3. Existing collective tests still pass (`tests/test_collective_tests.py`)
4. Import `BehavioralMetricsConfig` from `probos.config` — verify no circular imports
5. Verify `SystemConfig().behavioral_metrics` returns correct type
