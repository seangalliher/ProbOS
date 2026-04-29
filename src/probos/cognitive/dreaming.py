"""Dreaming engine — offline consolidation of Hebbian weights, trust, and pre-warming.

During idle periods the system replays recent episodes, strengthens successful
pathways, prunes weak connections, and pre-warms likely upcoming workflows
based on temporal patterns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from probos.cognitive.contradiction_detector import detect_contradictions
from probos.cognitive.episode_clustering import cluster_episodes
from probos.cognitive.similarity import jaccard_similarity, text_to_words  # AD-551
from probos.cognitive.gap_predictor import predict_gaps, detect_gaps, map_gap_to_skill, trigger_qualification_if_needed
from probos.cognitive.procedures import (
    extract_procedure_from_cluster,
    extract_chain_procedure,
    extract_procedure_from_observation,
    extract_compound_procedure_from_cluster,
    extract_negative_procedure_from_cluster,
    evolve_fix_procedure,
    evolve_derived_procedure,
    evolve_fix_from_fallback,
    diagnose_procedure_health,
    confirm_evolution_with_llm,
    evolve_with_retry,
)
from probos.config import (
    DreamingConfig,
    EVOLUTION_COOLDOWN_SECONDS,
    PROCEDURE_MIN_SELECTIONS,
    PROCEDURE_MATCH_THRESHOLD,
    REACTIVE_COOLDOWN_SECONDS,
    PROACTIVE_SCAN_INTERVAL_SECONDS,
)
from probos.config import (  # AD-537: observation config
    OBSERVATION_MAX_THREADS_PER_DREAM,
    OBSERVATION_MIN_TRUST,
    OBSERVATION_WARD_ROOM_LOOKBACK_HOURS,
)
from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — dream consolidation mutates trust
from probos.mesh.routing import HebbianRouter, REL_INTENT
from probos.types import DreamReport, Episode, MemorySource

logger = logging.getLogger(__name__)


class DreamingEngine:
    """Performs a single dream cycle: replay, prune, trust consolidation, pre-warm."""

    _confidence_tracker: Any = None
    _knowledge_linter: Any = None
    _quality_trigger: Any = None
    _quality_router: Any = None

    def __init__(
        self,
        router: HebbianRouter,
        trust_network: TrustNetwork,
        episodic_memory: Any,
        config: DreamingConfig,
        idle_scale_down_fn: Any = None,
        gap_prediction_fn: Any = None,
        contradiction_resolve_fn: Any = None,  # AD-403
        llm_client: Any = None,  # AD-532: procedure extraction
        procedure_store: Any = None,  # AD-533: persistent procedure storage
        ward_room: Any = None,  # AD-537: observational learning from Ward Room
        agent_id: str = "",  # AD-537: the dreaming agent's ID
        trust_network_lookup: Any = None,  # AD-537: fn(agent_id) -> trust score
        emergence_metrics_engine: Any = None,  # AD-557: emergence metrics engine
        get_department: Any = None,  # AD-557: fn(agent_id) -> department name
        records_store: Any = None,  # AD-551: Ship's Records for notebook consolidation
        notebook_quality_engine: Any = None,  # AD-555: notebook quality metrics
        retrieval_practice_engine: Any = None,  # AD-541c: spaced retrieval therapy
        retrieval_llm_client: Any = None,  # AD-541c: fast-tier LLM for recall practice
        activation_tracker: Any = None,  # AD-567d: activation-based memory lifecycle
        behavioral_metrics_engine: Any = None,  # AD-569: behavioral metrics engine
        counselor: Any = None,  # AD-568d: Counselor agent for source metric updates
        dream_wm_bridge: Any = None,  # AD-671: working memory bridge
        episodic_procedural_bridge: Any = None,  # AD-572: cross-cycle procedural bridge
    ) -> None:
        self.router = router
        self.trust_network = trust_network
        self.episodic_memory = episodic_memory
        self.config = config
        self.pre_warm_intents: list[str] = []
        self._idle_scale_down_fn = idle_scale_down_fn
        self._gap_prediction_fn = gap_prediction_fn
        self._last_clusters: list[Any] = []  # AD-531: most recent dream cycle clusters
        self._contradiction_resolve_fn = contradiction_resolve_fn
        self._last_consolidated_count: int = 0  # Cursor for micro-dream dedup
        self._llm_client = llm_client  # AD-532: for procedure extraction
        self._procedure_store = procedure_store  # AD-533: persistent procedure storage
        self._ward_room = ward_room  # AD-537: observational learning
        self._agent_id = agent_id  # AD-537: dreaming agent ID
        self._trust_network_lookup = trust_network_lookup  # AD-537: trust score lookup
        self._emergence_metrics_engine = emergence_metrics_engine  # AD-557
        self._get_department = get_department  # AD-557: department lookup
        self._records_store = records_store  # AD-551: Ship's Records
        self._notebook_quality_engine = notebook_quality_engine  # AD-555
        self._retrieval_practice_engine = retrieval_practice_engine  # AD-541c
        self._retrieval_llm_client = retrieval_llm_client  # AD-541c
        self._activation_tracker = activation_tracker  # AD-567d
        self._behavioral_metrics_engine = behavioral_metrics_engine  # AD-569
        self._counselor = counselor  # AD-568d
        self._dream_wm_bridge = dream_wm_bridge  # AD-671
        self._episodic_procedural_bridge = episodic_procedural_bridge  # AD-572
        self._confidence_tracker: Any = None  # AD-444
        self._knowledge_linter: Any = None  # AD-563
        self._quality_trigger: Any = None  # AD-564
        self._quality_router: Any = None  # AD-565
        self._agent_wm: Any = None  # AD-671: late-bound working memory
        self._last_procedures: list[Any] = []  # AD-532: most recent extracted procedures
        self._extracted_cluster_ids: set[str] = set()  # AD-532: already-processed clusters
        self._addressed_degradations: dict[str, float] = {}  # AD-532b: procedure_id -> timestamp
        self._extraction_candidates: dict[str, float] = {}  # AD-532e: intent_type -> timestamp
        self._reactive_cooldowns: dict[str, float] = {}  # AD-532e: agent_id -> last reactive check

    def set_ward_room(self, ward_room: Any) -> None:
        """BF-106: Late-bind ward_room (available after Phase 7)."""
        self._ward_room = ward_room

    def set_agent_wm(self, wm: Any) -> None:
        """AD-671: Late-bind agent working memory for dream-WM bridge."""
        self._agent_wm = wm

    def set_get_department(self, get_department: Any) -> None:
        """BF-106: Late-bind department lookup (available after Phase 7)."""
        self._get_department = get_department

    def set_records_store(self, records_store: Any) -> None:
        """BF-106: Late-bind records store. No-op if already set via constructor."""
        if self._records_store is None:
            self._records_store = records_store
        self._fallback_learning_queue: list[dict[str, Any]] = []  # AD-534b: fallback evidence for dream-time processing
        self._observed_threads: set[str] = set()  # AD-537: already-observed thread IDs

    def set_confidence_tracker(self, tracker: Any) -> None:
        """AD-444: Late-bind confidence tracker."""
        self._confidence_tracker = tracker

    def set_knowledge_linter(self, linter: Any) -> None:
        """AD-563: Late-bind knowledge linter."""
        self._knowledge_linter = linter

    def set_quality_trigger(self, trigger: Any) -> None:
        """AD-564: Late-bind quality consolidation trigger."""
        self._quality_trigger = trigger

    def set_quality_router(self, router: Any) -> None:
        """AD-565: Late-bind quality router."""
        self._quality_router = router

    @property
    def last_clusters(self) -> list[Any]:
        """Most recent episode clusters from the last dream cycle (AD-531)."""
        return self._last_clusters

    @property
    def last_procedures(self) -> list[Any]:
        """Most recent procedures extracted from the last dream cycle (AD-532)."""
        return self._last_procedures

    async def micro_dream(self) -> dict[str, Any]:
        """Lightweight consolidation of recent episodes only (Tier 1).

        Unlike dream_cycle(), this only replays new episodes to update
        Hebbian weights. Pruning and trust consolidation happen in the
        full idle dream. Returns a summary dict.
        """
        if not self.episodic_memory:
            return {"episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0}

        stats = await self.episodic_memory.get_stats()
        current_count = stats.get("total", 0)

        if current_count <= self._last_consolidated_count:
            return {"episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0}

        new_count = current_count - self._last_consolidated_count
        episodes = await self.episodic_memory.recent(k=min(new_count, 10))

        if not episodes:
            return {"episodes_replayed": 0, "weights_strengthened": 0, "weights_weakened": 0}

        strengthened = self._replay_episodes(episodes)
        self._last_consolidated_count = current_count

        # AD-567d: Reinforce replayed episodes (sleep replay strengthens memories)
        if self._activation_tracker and self.config.activation_enabled:
            try:
                replayed_ids = [ep.id for ep in episodes]
                if replayed_ids:
                    await self._activation_tracker.record_batch_access(
                        replayed_ids, access_type="dream_replay"
                    )
            except Exception:
                logger.debug("AD-567d: micro_dream activation reinforcement failed", exc_info=True)

        logger.debug("micro-dream: replayed=%d strengthened=%d", len(episodes), strengthened)

        return {
            "episodes_replayed": len(episodes),
            "weights_strengthened": strengthened,
            "weights_weakened": 0,
        }

    async def _get_importance_map(self, episode_ids: list[str]) -> dict[str, int]:
        """AD-598: Build importance map from stored episode metadata."""
        if not self.episodic_memory or not self.episodic_memory._collection:
            return {}
        try:
            result = self.episodic_memory._collection.get(
                ids=episode_ids,
                include=["metadatas"],
            )
            importance_map: dict[str, int] = {}
            if result and result.get("ids") and result.get("metadatas"):
                for eid, meta in zip(result["ids"], result["metadatas"]):
                    if meta:
                        importance_map[eid] = int(meta.get("importance", 5))
            return importance_map
        except Exception:
            logger.debug("AD-598: Failed to load importance map", exc_info=True)
            return {}

    async def dream_cycle(self) -> DreamReport:
        """Execute one full dream pass.

        Steps:
        0. Flush un-consolidated episodes via micro_dream (composable)
        1. (removed — micro_dream owns incremental consolidation)
        2. Prune — decay all weights and remove below-threshold connections
        3. Trust consolidation — boost/penalize agents based on track records
        4. Pre-warm — identify temporal intent sequences for faster routing
        5. Idle scale-down
        6. Episode clustering (AD-531)
        7. Procedure extraction from success clusters (AD-532)
        8. Gap prediction
        9. Emergence metrics (AD-557)
        10. Notebook quality metrics (AD-555)
        11. Spaced retrieval therapy (AD-541c)
        12. Activation-based memory pruning (AD-567d / AD-462b / AD-593)
        13. Behavioral metrics (AD-569)
        14. Source attribution consolidation (AD-568d)
        15. Reflection episode promotion (AD-599)
        """
        t_start = time.monotonic()
        wm_entries_flushed = 0
        wm_priming_entries = 0
        bridged_procedures = 0
        dream_wm_bridge = getattr(self, "_dream_wm_bridge", None)

        # AD-671: Pre-dream WM flush — capture session state before consolidation
        if dream_wm_bridge:
            try:
                flush_result = dream_wm_bridge.pre_dream_flush(
                    wm=getattr(self, "_agent_wm", None),
                    agent_id=self._agent_id,
                )
                if flush_result.get("flushed") and flush_result.get("episode"):
                    await self.episodic_memory.store(flush_result["episode"])
                    wm_entries_flushed = flush_result.get("entry_count", 0)
                    logger.debug(
                        "AD-671: Pre-dream WM flush stored %d entries as session summary",
                        wm_entries_flushed,
                    )
            except Exception:
                logger.debug("AD-671: Pre-dream WM flush failed (non-fatal)", exc_info=True)

        # Step 0: Flush any un-consolidated episodes (compose with micro-dream)
        micro_report = await self.micro_dream()

        episodes = await self.episodic_memory.recent(k=self.config.replay_episode_count)

        if not episodes:
            return DreamReport(
                episodes_replayed=micro_report["episodes_replayed"],
                weights_strengthened=micro_report["weights_strengthened"],
                duration_ms=(time.monotonic() - t_start) * 1000,
                wm_entries_flushed=wm_entries_flushed,
                wm_priming_entries=wm_priming_entries,
            )

        # Step 2: Prune
        weights_pruned = self._prune_weights()

        # Step 3: Trust consolidation
        trust_adjustments = self._consolidate_trust(episodes)

        # Step 3.5: Contradiction detection (AD-403)
        contradictions = detect_contradictions(episodes)
        contradictions_found = len(contradictions)
        if contradictions and self._contradiction_resolve_fn:
            try:
                self._contradiction_resolve_fn(contradictions)
            except Exception as e:
                logger.debug("Contradiction resolve callback failed: %s", e)

        # Step 4: Pre-warm
        pre_warm = self._compute_pre_warm(episodes)
        self.pre_warm_intents = pre_warm

        # Step 5: Idle pool scale-down (if scaler wired)
        if self._idle_scale_down_fn:
            try:
                await self._idle_scale_down_fn()
            except Exception as e:
                logger.debug("Idle scale-down failed: %s", e)

        # Step 6: Episode clustering (AD-531, replaces dead extract_strategies)
        # BF-169: Partition by primary intent_type before clustering to prevent
        # high-volume intents (ward_room_post) from drowning out other types.
        clusters_found = 0
        clusters: list = []
        try:
            episode_ids = [ep.id for ep in episodes]
            embeddings = await self.episodic_memory.get_embeddings(episode_ids)
            if embeddings:
                # BF-169: Group episodes by primary intent_type
                intent_groups: dict[str, list] = {}
                for ep in episodes:
                    primary_intent = ""
                    for outcome in getattr(ep, "outcomes", []):
                        intent = outcome.get("intent", "")
                        if intent:
                            primary_intent = intent
                            break
                    if not primary_intent:
                        primary_intent = "_unknown"
                    intent_groups.setdefault(primary_intent, []).append(ep)

                # Cluster each intent group independently
                for intent_key, intent_episodes in intent_groups.items():
                    intent_embs = {
                        ep.id: embeddings[ep.id]
                        for ep in intent_episodes
                        if ep.id in embeddings
                    }
                    if not intent_embs:
                        continue
                    intent_clusters = cluster_episodes(
                        episodes=intent_episodes,
                        embeddings=intent_embs,
                        distance_threshold=0.15,
                        min_episodes=3,
                    )
                    clusters.extend(intent_clusters)
                clusters_found = len(clusters)
                self._last_clusters = clusters
                if clusters_found > 0:
                    # AD-567d: Compose anchor provenance for each cluster
                    try:
                        from probos.cognitive.anchor_provenance import summarize_cluster_anchors
                        for cluster in clusters:
                            matched_eps = [ep for ep in episodes if ep.id in cluster.episode_ids]
                            cluster.anchor_summary = summarize_cluster_anchors(matched_eps)
                    except Exception:
                        logger.debug("AD-567d: Cluster anchor provenance failed (non-critical)", exc_info=True)
                    logger.info(
                        "Episode clustering: %d clusters found (%d success-dominant, %d failure-dominant)",
                        clusters_found,
                        sum(1 for c in clusters if c.is_success_dominant),
                        sum(1 for c in clusters if c.is_failure_dominant),
                    )
            else:
                logger.debug("Episode clustering skipped: no embeddings available")
        except Exception as e:
            logger.debug("Episode clustering failed (non-critical): %s", e)

        # Step 7: Procedure extraction from success clusters (AD-532)
        procedures_extracted = 0
        chain_procedures_extracted = 0  # AD-632g
        procedures: list = []
        if self._llm_client and clusters:
            for cluster in clusters:
                # Only extract from success-dominant clusters
                if not cluster.is_success_dominant:
                    continue
                # Skip clusters we've already processed (in-memory)
                if cluster.cluster_id in self._extracted_cluster_ids:
                    continue
                # Skip clusters already persisted (cross-session, AD-533)
                if self._procedure_store:
                    try:
                        if await self._procedure_store.has_cluster(cluster.cluster_id):
                            self._extracted_cluster_ids.add(cluster.cluster_id)  # warm cache
                            continue
                    except Exception:
                        pass  # fall through to in-memory check only
                try:
                    # Get the actual Episode objects for this cluster
                    matched_episodes = [
                        ep for ep in episodes
                        if ep.id in cluster.episode_ids
                    ]
                    if not matched_episodes:
                        continue
                    # AD-632g: Try chain-aware extraction first (0 LLM calls)
                    procedure = extract_chain_procedure(cluster, matched_episodes)
                    if procedure is not None:
                        chain_procedures_extracted += 1
                    # AD-532d: Route to compound extraction for multi-agent clusters
                    elif len(cluster.participating_agents) >= 2:
                        procedure = await extract_compound_procedure_from_cluster(
                            cluster=cluster,
                            episodes=matched_episodes,
                            llm_client=self._llm_client,
                        )
                    else:
                        procedure = await extract_procedure_from_cluster(
                            cluster=cluster,
                            episodes=matched_episodes,
                            llm_client=self._llm_client,
                        )
                    if procedure:
                        # AD-567d: Attach anchor provenance to procedure
                        if cluster.anchor_summary:
                            try:
                                from probos.cognitive.anchor_provenance import build_procedure_provenance
                                procedure.source_anchors = build_procedure_provenance(
                                    cluster.anchor_summary, cluster.cluster_id
                                )
                            except Exception:
                                pass
                        procedures.append(procedure)
                        procedures_extracted += 1
                        self._extracted_cluster_ids.add(cluster.cluster_id)
                        # AD-533: Persist to store (BF-169: pre-save dedup gate)
                        if self._procedure_store:
                            try:
                                # BF-169: Check semantic similarity before saving
                                skip_save = False
                                query_text = f"{procedure.name}. {procedure.description}"
                                existing = await self._procedure_store.find_matching(
                                    query_text, n_results=3, min_compilation_level=0,
                                )
                                for match in existing:
                                    if match.get("score", 0.0) >= 0.85:
                                        # Also require shared intent_type
                                        match_intents = set(match.get("intent_types", []))
                                        proc_intents = set(cluster.intent_types)
                                        if match_intents & proc_intents:
                                            logger.info(
                                                "Skipping duplicate procedure '%s' "
                                                "(%.1f%% similar to existing '%s')",
                                                procedure.name,
                                                match["score"] * 100,
                                                match.get("name", match.get("id", "?")),
                                            )
                                            skip_save = True
                                            break
                                if not skip_save:
                                    await self._procedure_store.save(procedure)
                            except Exception as e:
                                logger.debug(
                                    "Procedure persistence failed (non-critical): %s", e
                                )
                        logger.info(
                            "Procedure extracted from cluster %s: '%s' (%d steps)",
                            cluster.cluster_id[:8],
                            procedure.name,
                            len(procedure.steps),
                        )
                except Exception as e:
                    logger.debug(
                        "Procedure extraction failed for cluster %s (non-critical): %s",
                        cluster.cluster_id[:8], e,
                    )
            self._last_procedures = procedures

        # Step 7b: Procedure evolution from degraded metrics (AD-532b)
        procedures_evolved = 0
        if self._llm_client and self._procedure_store:
            try:
                procedures_evolved = await self._evolve_degraded_procedures(episodes, procedures)
            except Exception as e:
                logger.debug("Procedure evolution scan failed (non-critical): %s", e)

        # Step 7c: Negative procedure extraction from failure clusters (AD-532c)
        negative_procedures_extracted = 0
        if self._llm_client and clusters:
            for cluster in clusters:
                # Only extract from failure-dominant clusters
                if not cluster.is_failure_dominant:
                    continue
                # Skip clusters we've already processed (same dedup set as positive)
                if cluster.cluster_id in self._extracted_cluster_ids:
                    continue
                # Skip clusters already persisted (cross-session, AD-533)
                if self._procedure_store:
                    try:
                        if await self._procedure_store.has_cluster(cluster.cluster_id):
                            self._extracted_cluster_ids.add(cluster.cluster_id)
                            continue
                    except Exception:
                        pass
                try:
                    # Get the actual Episode objects for this cluster
                    matched_episodes = [
                        ep for ep in episodes
                        if ep.id in cluster.episode_ids
                    ]
                    if not matched_episodes:
                        continue
                    # Find relevant contradictions (AD-403) for this cluster's intent types
                    relevant_contradictions = [
                        c for c in contradictions
                        if c.intent in cluster.intent_types
                    ] if contradictions else []
                    procedure = await extract_negative_procedure_from_cluster(
                        cluster=cluster,
                        episodes=matched_episodes,
                        llm_client=self._llm_client,
                        contradictions=relevant_contradictions or None,
                    )
                    if procedure:
                        procedures.append(procedure)
                        negative_procedures_extracted += 1
                        self._extracted_cluster_ids.add(cluster.cluster_id)
                        # AD-533: Persist to store (BF-169: pre-save dedup gate)
                        if self._procedure_store:
                            try:
                                skip_save = False
                                query_text = f"{procedure.name}. {procedure.description}"
                                existing = await self._procedure_store.find_matching(
                                    query_text, n_results=3, min_compilation_level=0,
                                    exclude_negative=False,
                                )
                                for match in existing:
                                    if match.get("score", 0.0) >= 0.85:
                                        match_intents = set(match.get("intent_types", []))
                                        proc_intents = set(cluster.intent_types)
                                        if match_intents & proc_intents:
                                            logger.info(
                                                "Skipping duplicate negative procedure '%s' "
                                                "(%.1f%% similar to existing '%s')",
                                                procedure.name,
                                                match["score"] * 100,
                                                match.get("name", match.get("id", "?")),
                                            )
                                            skip_save = True
                                            break
                                if not skip_save:
                                    await self._procedure_store.save(procedure)
                            except Exception as e:
                                logger.debug(
                                    "Negative procedure persistence failed (non-critical): %s", e
                                )
                        logger.info(
                            "Negative procedure extracted from cluster %s: '%s' (%d steps)",
                            cluster.cluster_id[:8],
                            procedure.name,
                            len(procedure.steps),
                        )
                except Exception as e:
                    logger.debug(
                        "Negative extraction failed for cluster %s (non-critical): %s",
                        cluster.cluster_id[:8], e,
                    )

        # Step 7d: Fallback learning (AD-534b)
        fallback_stats: dict[str, Any] = {"evolved": 0, "processed": 0}
        try:
            fallback_stats = await self._process_fallback_learning()
            if fallback_stats.get("evolved", 0) > 0:
                logger.debug("Step 7d: Evolved %d procedures from fallback evidence", fallback_stats["evolved"])
        except Exception as e:
            logger.debug("Step 7d fallback learning failed: %s", e)

        # Step 7e: Observational learning from Ward Room (AD-537)
        procedures_observed = 0
        observation_threads_scanned = 0
        try:
            obs_stats = await self._process_observational_learning()
            procedures_observed = obs_stats.get("observed", 0)
            observation_threads_scanned = obs_stats.get("scanned", 0)
            if procedures_observed > 0:
                logger.debug(
                    "Step 7e: Observed %d procedures from %d threads",
                    procedures_observed, observation_threads_scanned,
                )
        except Exception as e:
            logger.debug("Step 7e observational learning failed: %s", e)

        # Step 7f: Procedure lifecycle maintenance (AD-538)
        procedures_decayed = 0
        procedures_archived = 0
        dedup_candidates_found = 0
        decay_results: list[dict] = []  # AD-539: captured for Step 8
        try:
            if self._procedure_store:
                # Decay first (may create Level 1 candidates for archival)
                decay_results = await self._procedure_store.decay_stale_procedures()
                procedures_decayed = len(decay_results)
                if procedures_decayed > 0:
                    logger.debug("Step 7f: Decayed %d procedures", procedures_decayed)

                # Archive Level 1 procedures unused for LIFECYCLE_ARCHIVE_DAYS
                archive_results = await self._procedure_store.archive_stale_procedures()
                procedures_archived = len(archive_results)
                if procedures_archived > 0:
                    logger.debug("Step 7f: Archived %d procedures", procedures_archived)

                # Dedup detection (flag only, no auto-merge)
                dedup_results = await self._procedure_store.find_duplicate_candidates()
                dedup_candidates_found = len(dedup_results)
                if dedup_candidates_found > 0:
                    for dup in dedup_results:
                        logger.debug(
                            "Step 7f dedup candidate: '%s' ↔ '%s' (similarity %.3f)",
                            dup["primary_name"], dup["duplicate_name"], dup["similarity"],
                        )
        except Exception as e:
            logger.debug("Step 7f lifecycle maintenance failed: %s", e)

        # Step 7g: Notebook consolidation + cross-agent convergence (AD-551)
        notebook_consolidations = 0
        notebook_entries_archived = 0
        convergence_reports_generated = 0
        convergence_reports: list[dict] = []
        try:
            if self._records_store and self.config.notebook_consolidation_enabled:
                # --- Intra-agent consolidation ---
                all_entries = await self._records_store.list_entries("notebooks/")
                # Group by agent callsign (path: notebooks/{callsign}/...)
                agents_entries: dict[str, list[dict]] = {}
                for entry in all_entries:
                    parts = entry["path"].split("/")
                    if len(parts) >= 2:
                        agent_cs = parts[1]
                        agents_entries.setdefault(agent_cs, []).append(entry)

                threshold = self.config.notebook_consolidation_threshold
                min_entries = self.config.notebook_consolidation_min_entries

                for agent_cs, entries in agents_entries.items():
                    if len(entries) < min_entries:
                        continue
                    # Load content for each entry
                    loaded: list[dict] = []
                    for ent in entries:
                        try:
                            doc = await self._records_store.read_entry(
                                ent["path"], reader_id="system",
                            )
                            if doc:
                                loaded.append({**ent, "_content": doc.get("content", ""), "_doc": doc})
                        except Exception:
                            pass
                    if len(loaded) < min_entries:
                        continue
                    # Pairwise similarity → single-linkage clustering
                    n = len(loaded)
                    adj: dict[int, set[int]] = {i: set() for i in range(n)}
                    for i in range(n):
                        words_i = text_to_words(loaded[i]["_content"])
                        for j in range(i + 1, n):
                            words_j = text_to_words(loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
                            if sim >= threshold:
                                adj[i].add(j)
                                adj[j].add(i)
                    # BFS to find connected components
                    visited: set[int] = set()
                    clusters: list[list[int]] = []
                    for start in range(n):
                        if start in visited:
                            continue
                        if not adj[start]:
                            continue
                        queue = [start]
                        component: list[int] = []
                        while queue:
                            node = queue.pop(0)
                            if node in visited:
                                continue
                            visited.add(node)
                            component.append(node)
                            queue.extend(adj[node] - visited)
                        if len(component) >= min_entries:
                            clusters.append(component)
                    # Consolidate each cluster
                    for cluster_indices in clusters:
                        cluster_items = [loaded[i] for i in cluster_indices]
                        # Primary = most recent (by updated or created timestamp)
                        def _sort_key(item: dict) -> str:
                            fm = item.get("frontmatter", {})
                            return fm.get("updated", fm.get("created", ""))
                        cluster_items.sort(key=_sort_key, reverse=True)
                        primary = cluster_items[0]
                        others = cluster_items[1:]
                        # Build consolidated content
                        primary_content = primary["_content"]
                        unique_observations: list[str] = []
                        for other in others:
                            other_content = other["_content"].strip()
                            if other_content and other_content != primary_content.strip():
                                unique_observations.append(other_content)
                        consolidated = primary_content
                        if unique_observations:
                            consolidated += "\n\n## Consolidated Observations\n\n"
                            consolidated += "\n\n---\n\n".join(unique_observations)
                        # Write consolidated entry
                        await self._records_store.write_entry(
                            author=primary.get("frontmatter", {}).get("author", "system"),
                            path=primary["path"],
                            content=consolidated,
                            message=f"AD-551: Consolidated {len(cluster_items)} entries",
                        )
                        # Archive non-primary entries
                        for other in others:
                            try:
                                old_path = self._records_store._safe_path(other["path"])
                                new_dir = old_path.parent / "_archived"
                                new_dir.mkdir(parents=True, exist_ok=True)
                                new_path = new_dir / old_path.name
                                old_path.rename(new_path)
                                try:
                                    await self._records_store._git("add", "-A")
                                except Exception:
                                    pass
                                notebook_entries_archived += 1
                            except Exception:
                                logger.debug("AD-551: Failed to archive %s", other["path"])
                        notebook_consolidations += 1
                    if notebook_consolidations:
                        logger.debug(
                            "Step 7g: Consolidated %d notebook clusters for agent %s",
                            len(clusters), agent_cs,
                        )

                # --- Cross-agent convergence detection ---
                conv_min_agents = self.config.notebook_convergence_min_agents
                conv_min_depts = self.config.notebook_convergence_min_departments
                conv_threshold = self.config.notebook_convergence_threshold
                # Collect entries with department info
                agent_dept_entries: list[dict] = []
                for agent_cs, entries in agents_entries.items():
                    dept = ""
                    if self._get_department and agent_cs:
                        try:
                            dept = self._get_department(agent_cs) or ""
                        except Exception:
                            pass
                    for ent in entries:
                        fm = ent.get("frontmatter", {})
                        dept_resolved = fm.get("department", dept)
                        agent_dept_entries.append({
                            **ent, "agent": agent_cs, "department": dept_resolved,
                        })
                # Need entries from enough agents/departments
                unique_agents = {e["agent"] for e in agent_dept_entries}
                unique_depts = {e["department"] for e in agent_dept_entries if e["department"]}
                if len(unique_agents) >= conv_min_agents and len(unique_depts) >= conv_min_depts:
                    # Load content for cross-agent comparison
                    cross_loaded: list[dict] = []
                    for ent in agent_dept_entries:
                        try:
                            doc = await self._records_store.read_entry(
                                ent["path"], reader_id="system",
                            )
                            if doc:
                                cross_loaded.append({
                                    **ent, "_content": doc.get("content", ""),
                                })
                        except Exception:
                            pass
                    # Find cross-agent matches
                    n_cross = len(cross_loaded)
                    cross_adj: dict[int, set[int]] = {i: set() for i in range(n_cross)}
                    for i in range(n_cross):
                        words_i = text_to_words(cross_loaded[i]["_content"])
                        for j in range(i + 1, n_cross):
                            if cross_loaded[i]["agent"] == cross_loaded[j]["agent"]:
                                continue  # skip same-agent pairs
                            words_j = text_to_words(cross_loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
                            if sim >= conv_threshold:
                                cross_adj[i].add(j)
                                cross_adj[j].add(i)
                    # BFS for convergence clusters
                    cross_visited: set[int] = set()
                    for start in range(n_cross):
                        if start in cross_visited or not cross_adj[start]:
                            continue
                        queue = [start]
                        component: list[int] = []
                        while queue:
                            node = queue.pop(0)
                            if node in cross_visited:
                                continue
                            cross_visited.add(node)
                            component.append(node)
                            queue.extend(cross_adj[node] - cross_visited)
                        cluster_entries = [cross_loaded[i] for i in component]
                        cluster_agents = {e["agent"] for e in cluster_entries}
                        cluster_depts = {e["department"] for e in cluster_entries if e["department"]}
                        if len(cluster_agents) >= conv_min_agents and len(cluster_depts) >= conv_min_depts:
                            # Compute coherence = avg pairwise similarity
                            pairs = 0
                            total_sim = 0.0
                            for ci in range(len(component)):
                                wi = text_to_words(cluster_entries[ci]["_content"])
                                for cj in range(ci + 1, len(component)):
                                    wj = text_to_words(cluster_entries[cj]["_content"])
                                    total_sim += jaccard_similarity(wi, wj)
                                    pairs += 1
                            coherence = total_sim / pairs if pairs else 0.0
                            # Infer topic from most common words
                            from collections import Counter as _Counter
                            all_words: list[str] = []
                            for ce in cluster_entries:
                                all_words.extend(ce["_content"].lower().split()[:50])
                            common = _Counter(all_words).most_common(3)
                            topic = "-".join(w for w, _ in common) if common else "unknown"
                            # Build perspectives
                            perspectives = ""
                            for ce in cluster_entries:
                                snippet = ce["_content"][:300].strip()
                                perspectives += f"\n### {ce['agent']} ({ce['department']})\n\n{snippet}\n"
                            # Intersection content
                            word_sets = [text_to_words(ce["_content"]) for ce in cluster_entries]
                            shared_words = set.intersection(*word_sets) if word_sets else set()
                            shared_summary = " ".join(sorted(shared_words)[:30]) if shared_words else "(computed intersection)"
                            import datetime as _dt
                            ts_slug = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
                            report_path = f"reports/convergence/convergence-{ts_slug}.md"
                            report_content = (
                                f"## Convergence Report\n\n"
                                f"**Agents:** {', '.join(sorted(cluster_agents))}\n\n"
                                f"**Departments:** {', '.join(sorted(cluster_depts))}\n\n"
                                f"**Coherence:** {coherence:.3f}\n\n"
                                f"## Contributing Perspectives\n{perspectives}\n"
                                f"## Convergent Finding\n\n{shared_summary}\n"
                            )
                            try:
                                await self._records_store.write_entry(
                                    author="system",
                                    path=report_path,
                                    content=report_content,
                                    message=f"AD-551: Convergence report ({topic})",
                                    classification="ship",
                                    tags=["convergence", "ad-551"],
                                )
                            except Exception:
                                logger.debug("AD-551: Failed to write convergence report")
                            conv_data = {
                                "agents": sorted(cluster_agents),
                                "departments": sorted(cluster_depts),
                                "coherence": coherence,
                                "topic": topic,
                                "report_path": report_path,
                            }
                            # AD-567d: Enrich with provenance
                            try:
                                from probos.cognitive.anchor_provenance import enrich_convergence_report
                                conv_data = enrich_convergence_report(conv_data, cluster_entries)
                            except Exception:
                                pass
                            convergence_reports.append(conv_data)
                            convergence_reports_generated += 1
                            # Emit event
                            if hasattr(self, "_emit_event_fn") and self._emit_event_fn:
                                try:
                                    self._emit_event_fn("convergence_detected", conv_data)
                                except Exception:
                                    pass
                            # AD-583: Check anchor independence for wrong convergence
                            try:
                                from types import SimpleNamespace as _NS583
                                from probos.cognitive.social_verification import compute_anchor_independence
                                _episodes_583 = []
                                for ce in cluster_entries:
                                    _fm = ce.get("frontmatter", ce.get("_doc", {}).get("frontmatter", {}))
                                    _anch = _NS583(
                                        duty_cycle_id=_fm.get("duty_cycle_id", ""),
                                        channel_id=_fm.get("channel_id", ""),
                                        thread_id=_fm.get("thread_id", ""),
                                    )
                                    _ts583 = 0.0
                                    _upd = _fm.get("updated", "")
                                    if _upd:
                                        try:
                                            _ts583 = _dt.datetime.fromisoformat(_upd).timestamp()
                                        except Exception:
                                            pass
                                    _episodes_583.append(_NS583(anchors=_anch, timestamp=_ts583))
                                _ind_score = compute_anchor_independence(_episodes_583)
                                _ind_threshold = 0.3
                                try:
                                    _ind_threshold = self.config.convergence_independence_threshold
                                except Exception:
                                    pass
                                conv_data["independence_score"] = _ind_score
                                conv_data["independence"] = "low" if _ind_score < _ind_threshold else "high"
                                if _ind_score < _ind_threshold:
                                    # Emit wrong convergence event
                                    if hasattr(self, "_emit_event_fn") and self._emit_event_fn:
                                        try:
                                            self._emit_event_fn("wrong_convergence_detected", {
                                                "agents": sorted(cluster_agents),
                                                "departments": sorted(cluster_depts),
                                                "topic": topic,
                                                "coherence": coherence,
                                                "independence_score": _ind_score,
                                                "source": "dream_consolidation",
                                            })
                                        except Exception:
                                            pass
                                    logger.warning(
                                        "AD-583: Wrong convergence in dream — topic='%s', independence=%.3f",
                                        topic, _ind_score,
                                    )
                            except Exception:
                                logger.debug("AD-583: Dream independence scoring failed", exc_info=True)
                if convergence_reports_generated:
                    logger.debug(
                        "Step 7g: Detected %d convergence events", convergence_reports_generated,
                    )
        except Exception as e:
            logger.debug("Step 7g notebook consolidation failed (non-critical): %s", e)

        # Step 7h: Cross-cycle episodic-procedural bridge (AD-572)
        episodic_clusters = self._last_clusters
        episodic_procedural_bridge = getattr(self, "_episodic_procedural_bridge", None)
        if episodic_procedural_bridge and episodic_clusters:
            try:
                bridged = await episodic_procedural_bridge.bridge_episodes_to_procedures(
                    episodes, episodic_clusters,
                )
                bridged_procedures = len(bridged)
                if bridged_procedures > 0:
                    if self._procedure_store:
                        for proc in bridged:
                            try:
                                await self._procedure_store.save(proc)
                            except Exception as e:
                                logger.warning(
                                    "Step 7h: Failed to save bridged procedure for cluster %s; continuing dream cycle: %s",
                                    proc.origin_cluster_id,
                                    e,
                                )
                    procedures.extend(bridged)
                    logger.debug("Step 7h: Bridged %d cross-cycle procedures", bridged_procedures)
            except Exception as e:
                logger.warning("Step 7h episodic-procedural bridge failed; continuing dream cycle: %s", e)

        # Step 8: Enhanced capability gap detection (AD-385 + AD-539)
        gaps_predicted = 0
        gaps_classified = 0
        qualification_paths_triggered = 0
        gap_reports_generated = 0
        try:
            # Build procedure health results from active procedures
            procedure_health_results: list[dict] = []
            if self._procedure_store:
                try:
                    active = await self._procedure_store.list_active()
                    for p in active[:50]:  # Cap scan size
                        pid = p.get("id", "")
                        if pid:
                            metrics = await self._procedure_store.get_quality_metrics(pid)
                            if metrics:
                                eff_rate = metrics.get("effective_rate", 1.0)
                                fallback_rate = metrics.get("fallback_rate", 0.0)
                                completion_rate = metrics.get("completion_rate", 1.0)
                                diagnosis = ""
                                if fallback_rate > 0.3:
                                    diagnosis = "FIX:high_fallback_rate"
                                elif completion_rate < 0.5:
                                    diagnosis = "FIX:low_completion"
                                elif eff_rate < 0.5:
                                    diagnosis = "DERIVED:low_effective_rate"
                                if diagnosis:
                                    procedure_health_results.append({
                                        "id": pid,
                                        "name": p.get("name", pid),
                                        "diagnosis": diagnosis,
                                        "intent_types": p.get("intent_types", []),
                                        "failure_rate": 1.0 - eff_rate,
                                        "total_selections": metrics.get("total_selections", 0),
                                    })
                except Exception:
                    pass

            gap_reports = detect_gaps(
                episodes=episodes,
                clusters=self._last_clusters,
                procedure_decay_results=decay_results,
                procedure_health_results=procedure_health_results,
                agent_id=self._agent_id,
                agent_type=getattr(self, "_agent_type", ""),
            )

            # Map to skills and trigger qualifications (if Skill Framework available)
            skill_service = getattr(self._procedure_store, "_skill_service", None) if self._procedure_store else None
            for i, gap in enumerate(gap_reports):
                if skill_service:
                    gap_reports[i] = await map_gap_to_skill(gap, skill_service)
                    gap_reports[i] = await trigger_qualification_if_needed(gap, skill_service)
                    if gap_reports[i].qualification_path_id:
                        qualification_paths_triggered += 1

            gaps_predicted = len(gap_reports)
            gaps_classified = sum(1 for g in gap_reports if g.gap_type)
            gap_reports_generated = len(gap_reports)

            # Write gap reports to Ship's Records (if available)
            records_store = self._records_store  # AD-551: direct access
            if records_store and gap_reports:
                for gap in gap_reports:
                    try:
                        import yaml
                        content = yaml.dump(gap.to_dict(), default_flow_style=False, sort_keys=False)
                        await records_store.write_entry(
                            author="system",
                            path=f"reports/gap-reports/{gap.id}.md",
                            content=content,
                            message=f"Gap report: {gap.description}",
                            classification="ship",
                            topic="gap_analysis",
                            tags=["ad-539", gap.gap_type, gap.priority],
                        )
                    except Exception:
                        pass

            # Backward-compatible callback
            if gap_reports and self._gap_prediction_fn:
                try:
                    self._gap_prediction_fn(gap_reports)
                except Exception as e:
                    logger.debug("Gap prediction callback failed: %s", e)
        except Exception as e:
            logger.debug("Step 8 gap detection failed: %s", e)

        # Step 9: Emergence metrics (AD-557)
        emergence_capacity = None
        coordination_balance = None
        groupthink_risk = False
        fragmentation_risk = False
        tom_effectiveness = None
        if self._emergence_metrics_engine and self._ward_room:
            try:
                snapshot = await self._emergence_metrics_engine.compute_emergence_metrics(
                    ward_room=self._ward_room,
                    trust_network=self.trust_network,
                    hebbian_router=self.router,
                    get_department=self._get_department,
                )
                emergence_capacity = snapshot.emergence_capacity
                coordination_balance = snapshot.coordination_balance
                groupthink_risk = snapshot.groupthink_risk
                fragmentation_risk = snapshot.fragmentation_risk
                tom_effectiveness = snapshot.tom_effectiveness
                logger.debug(
                    "Step 9 emergence: capacity=%.3f, balance=%.3f, "
                    "pairs=%d (%d significant)",
                    snapshot.emergence_capacity,
                    snapshot.coordination_balance,
                    snapshot.pairs_analyzed,
                    snapshot.significant_pairs,
                )
                # AD-583: Populate provenance_independence (AD-559 reservation)
                try:
                    from probos.cognitive.social_verification import compute_anchor_independence as _cai583
                    if self.episodic_memory:
                        _sample = await self.episodic_memory.recent(k=20)
                        if _sample:
                            _prov_score = _cai583(_sample)
                            snapshot.provenance_independence = _prov_score
                except Exception:
                    logger.debug("AD-583: Provenance independence computation failed", exc_info=True)
            except Exception as e:
                logger.debug("Step 9 emergence metrics failed: %s", e)

        # Step 10: Notebook Quality Metrics (AD-555)
        notebook_quality_score = None
        notebook_quality_agents = 0
        quality_snapshot = None
        if self._notebook_quality_engine:
            try:
                _records = self._records_store
                if _records:
                    _staleness = 72.0
                    if hasattr(self, 'config') and hasattr(self.config, 'notebook_staleness_hours'):
                        _staleness = self.config.notebook_staleness_hours
                    quality_snapshot = await self._notebook_quality_engine.compute_quality_metrics(
                        _records, staleness_hours=_staleness
                    )
                    notebook_quality_score = quality_snapshot.system_quality_score
                    notebook_quality_agents = len(quality_snapshot.per_agent)
                    logger.info(
                        "AD-555 Step 10: Notebook quality computed — score=%.3f, agents=%d, entries=%d",
                        quality_snapshot.system_quality_score,
                        len(quality_snapshot.per_agent),
                        quality_snapshot.total_entries,
                    )
            except Exception:
                logger.debug("AD-555 Step 10: Quality metrics failed", exc_info=True)

        confidence_suppressed = 0
        if self._confidence_tracker is not None:
            try:
                for entry in self._confidence_tracker.get_all_entries().values():
                    if self._confidence_tracker.auto_supersede_check(entry.entry_path):
                        confidence_suppressed += 1
                if confidence_suppressed > 0:
                    logger.info(
                        "AD-444 Step 10: %d entries below auto-supersede threshold",
                        confidence_suppressed,
                    )
            except Exception:
                logger.debug("AD-444 Step 10: confidence cross-ref failed", exc_info=True)

        lint_score = None
        lint_issues_found = 0
        if self._knowledge_linter:
            try:
                lint_report = await self._knowledge_linter.lint_all()
                lint_score = lint_report.lint_score
                lint_issues_found = (
                    len(lint_report.inconsistencies)
                    + len(lint_report.coverage_gaps)
                )
                if lint_issues_found > 0:
                    logger.info(
                        "AD-563 Step 10: Lint completed — score=%.3f, issues=%d "
                        "(inconsistencies=%d, gaps=%d, xrefs=%d)",
                        lint_report.lint_score,
                        lint_issues_found,
                        len(lint_report.inconsistencies),
                        len(lint_report.coverage_gaps),
                        len(lint_report.cross_ref_suggestions),
                    )
            except Exception:
                logger.debug("AD-563 Step 10: Lint failed", exc_info=True)

        forced_consolidation_count = 0
        if self._quality_trigger and quality_snapshot:
            try:
                if self._quality_trigger.check_and_trigger(quality_snapshot):
                    forced_consolidation_count += 1
                    logger.info("AD-564 Step 10: Forced consolidation triggered")
            except Exception:
                logger.debug("AD-564 Step 10: trigger check failed", exc_info=True)

        if self._quality_router and quality_snapshot:
            try:
                for agent_quality in quality_snapshot.per_agent:
                    agent_id = agent_quality.callsign
                    if agent_id:
                        self._quality_router.update_quality(
                            agent_id,
                            agent_quality.quality_score,
                        )
                weights = self._quality_router.get_all_weights()
                if weights:
                    logger.info(
                        "AD-565 Step 10: Quality routing updated for %d agents",
                        len(weights),
                    )
            except Exception:
                logger.debug("AD-565 Step 10: quality router update failed", exc_info=True)

        # Step 11: Spaced Retrieval Therapy (AD-541c)
        retrieval_practices = 0
        retrieval_accuracy = None
        retrieval_concerns = 0
        if (
            self._retrieval_practice_engine
            and self._retrieval_llm_client
            and self.config.active_retrieval_enabled
        ):
            try:
                rp_result = await self._step_11_retrieval_practice(episodes)
                retrieval_practices = rp_result.get("practices", 0)
                if rp_result.get("accuracies"):
                    retrieval_accuracy = sum(rp_result["accuracies"]) / len(rp_result["accuracies"])
                retrieval_concerns = rp_result.get("concerns", 0)
                if retrieval_practices:
                    logger.info(
                        "AD-541c Step 11: Retrieval practice — %d trials, avg accuracy=%.2f, concerns=%d",
                        retrieval_practices,
                        retrieval_accuracy or 0.0,
                        retrieval_concerns,
                    )
            except Exception:
                logger.debug("AD-541c Step 11: Retrieval practice failed", exc_info=True)

        # Step 12: Activation-Based Memory Pruning (AD-567d / AD-462b / AD-593)
        activation_pruned = 0
        activation_reinforced = 0
        if (
            self._activation_tracker
            and self.config.activation_enabled
            and self.episodic_memory
        ):
            try:
                # Reinforcement: dream replayed these episodes — record access
                replayed_ids = [ep.id for ep in episodes]
                if replayed_ids:
                    await self._activation_tracker.record_batch_access(
                        replayed_ids, access_type="dream_replay"
                    )
                    activation_reinforced = len(replayed_ids)

                # AD-593: Episode pool pressure detection
                _pool_pressure = 1.0
                try:
                    _total_episodes = self.episodic_memory._collection.count() if self.episodic_memory._collection else 0
                    if _total_episodes > self.config.episode_pressure_threshold:
                        _pool_pressure = self.config.episode_pressure_multiplier
                        logger.info(
                            "AD-593: Episode pool pressure active (%d episodes > %d threshold, multiplier=%.1f)",
                            _total_episodes, self.config.episode_pressure_threshold, _pool_pressure,
                        )
                except Exception:
                    _total_episodes = 0

                # --- Standard tier: episodes older than prune_min_age_hours ---
                _standard_cutoff = time.time() - (self.config.prune_min_age_hours * 3600)
                _standard_candidates = await self.episodic_memory.get_episode_ids_older_than(_standard_cutoff)

                if _standard_candidates:
                    _standard_fraction = min(
                        self.config.prune_max_fraction * _pool_pressure, 0.50
                    )  # Cap at 50% even under pressure
                    # AD-598: Importance-aware pruning
                    _importance_map = await self._get_importance_map(_standard_candidates)
                    if _importance_map:
                        low_activation = await self._activation_tracker.find_low_activation_episodes_with_importance(
                            all_episode_ids=_standard_candidates,
                            importance_map=_importance_map,
                            threshold=self.config.activation_prune_threshold,
                            max_prune_fraction=_standard_fraction,
                        )
                    else:
                        low_activation = await self._activation_tracker.find_low_activation_episodes(
                            all_episode_ids=_standard_candidates,
                            threshold=self.config.activation_prune_threshold,
                            max_prune_fraction=_standard_fraction,
                        )
                    if low_activation:
                        await self.episodic_memory.evict_by_ids(
                            low_activation, reason="activation_decay"
                        )
                        activation_pruned += len(low_activation)
                        logger.info(
                            "AD-567d Step 12: Standard pruned %d episodes (threshold=%.1f, fraction=%.2f)",
                            len(low_activation),
                            self.config.activation_prune_threshold,
                            _standard_fraction,
                        )

                # --- AD-593 Aggressive tier: episodes older than aggressive_prune_min_age_hours ---
                if self.config.aggressive_prune_enabled:
                    _aggressive_cutoff = time.time() - (self.config.aggressive_prune_min_age_hours * 3600)
                    _aggressive_candidates = await self.episodic_memory.get_episode_ids_older_than(_aggressive_cutoff)

                    if _aggressive_candidates:
                        _aggressive_fraction = min(
                            self.config.aggressive_prune_max_fraction * _pool_pressure, 0.50
                        )
                        # AD-598: Importance-aware pruning
                        _agg_importance_map = await self._get_importance_map(_aggressive_candidates)
                        if _agg_importance_map:
                            aggressive_pruned = await self._activation_tracker.find_low_activation_episodes_with_importance(
                                all_episode_ids=_aggressive_candidates,
                                importance_map=_agg_importance_map,
                                threshold=self.config.aggressive_prune_threshold,
                                max_prune_fraction=_aggressive_fraction,
                            )
                        else:
                            aggressive_pruned = await self._activation_tracker.find_low_activation_episodes(
                                all_episode_ids=_aggressive_candidates,
                                threshold=self.config.aggressive_prune_threshold,
                                max_prune_fraction=_aggressive_fraction,
                            )
                        if aggressive_pruned:
                            await self.episodic_memory.evict_by_ids(
                                aggressive_pruned, reason="activation_decay_aggressive"
                            )
                            activation_pruned += len(aggressive_pruned)
                            logger.info(
                                "AD-593 Step 12: Aggressive pruned %d episodes (threshold=%.1f, age>%dh, fraction=%.2f)",
                                len(aggressive_pruned),
                                self.config.aggressive_prune_threshold,
                                self.config.aggressive_prune_min_age_hours,
                                _aggressive_fraction,
                            )

                # Cleanup old access records
                await self._activation_tracker.cleanup_old_accesses()
            except Exception:
                logger.debug("AD-567d Step 12: Activation pruning failed", exc_info=True)

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

        # Step 14: Source Attribution Consolidation (AD-568d)
        _source_attr_result: dict[str, Any] = {}
        try:
            _source_attr_result = await self._step_14_source_attribution(episodes)
        except Exception:
            logger.debug("AD-568d: Dream step 14 (source attribution) failed")

        # Step 15: Reflection Episode Promotion (AD-599)
        reflections_created = 0
        try:
            if self.config.reflection_enabled and self.episodic_memory:
                reflections_created = await self._step_15_reflection_promotion(
                    episodes=episodes,
                    clusters=clusters,
                    convergence_reports=convergence_reports,
                    emergence_capacity=emergence_capacity,
                    coordination_balance=coordination_balance,
                    notebook_consolidations=notebook_consolidations,
                    behavioral_quality_score=behavioral_quality_score,
                )
                if reflections_created:
                    logger.info(
                        "AD-599 Step 15: Created %d reflection episodes",
                        reflections_created,
                    )
        except Exception:
            logger.debug("AD-599 Step 15: Reflection promotion failed", exc_info=True)

        # AD-671: Post-dream WM seed — prime next session with dream insights
        agent_wm = getattr(self, "_agent_wm", None)
        if dream_wm_bridge and agent_wm:
            try:
                cycle_id = f"{self._agent_id}_{int(time.time())}"
                partial_report = DreamReport(
                    procedures_extracted=procedures_extracted,
                    procedures_evolved=procedures_evolved,
                    gaps_classified=gaps_classified,
                    emergence_capacity=emergence_capacity,
                    notebook_consolidations=notebook_consolidations,
                    reflections_created=reflections_created,
                    activation_pruned=activation_pruned,
                    contradictions_found=contradictions_found,
                    bridged_procedures=bridged_procedures,
                )
                wm_priming_entries = dream_wm_bridge.post_dream_seed(
                    wm=agent_wm,
                    dream_report=partial_report,
                    dream_cycle_id=cycle_id,
                )
            except Exception:
                logger.debug("AD-671: Post-dream WM seed failed (non-fatal)", exc_info=True)

        duration_ms = (time.monotonic() - t_start) * 1000

        report = DreamReport(
            episodes_replayed=micro_report["episodes_replayed"],
            weights_strengthened=micro_report["weights_strengthened"],
            weights_pruned=weights_pruned,
            trust_adjustments=trust_adjustments,
            pre_warm_intents=pre_warm,
            duration_ms=duration_ms,
            clusters_found=clusters_found,
            clusters=clusters,
            procedures_extracted=procedures_extracted,
            chain_procedures_extracted=chain_procedures_extracted,  # AD-632g
            procedures=procedures,
            bridged_procedures=bridged_procedures,
            procedures_evolved=procedures_evolved,
            negative_procedures_extracted=negative_procedures_extracted,
            fallback_evolutions=fallback_stats.get("evolved", 0),
            fallback_events_processed=fallback_stats.get("processed", 0),
            gaps_predicted=gaps_predicted,
            contradictions_found=contradictions_found,
            procedures_observed=procedures_observed,
            observation_threads_scanned=observation_threads_scanned,
            procedures_decayed=procedures_decayed,
            procedures_archived=procedures_archived,
            dedup_candidates_found=dedup_candidates_found,
            # AD-539: Gap → Qualification Pipeline
            gaps_classified=gaps_classified,
            qualification_paths_triggered=qualification_paths_triggered,
            gap_reports_generated=gap_reports_generated,
            # AD-557: Emergence metrics
            emergence_capacity=emergence_capacity,
            coordination_balance=coordination_balance,
            groupthink_risk=groupthink_risk,
            fragmentation_risk=fragmentation_risk,
            tom_effectiveness=tom_effectiveness,
            # AD-551: Notebook consolidation
            notebook_consolidations=notebook_consolidations,
            notebook_entries_archived=notebook_entries_archived,
            convergence_reports_generated=convergence_reports_generated,
            convergence_reports=convergence_reports,
            # AD-555: Notebook quality
            notebook_quality_score=notebook_quality_score,
            notebook_quality_agents=notebook_quality_agents,
            # AD-563: Knowledge linting
            lint_score=lint_score,
            lint_issues_found=lint_issues_found,
            # AD-564: Forced consolidation
            forced_consolidations=forced_consolidation_count,
            # AD-541c: Spaced Retrieval Therapy
            retrieval_practices=retrieval_practices,
            retrieval_accuracy=retrieval_accuracy,
            retrieval_concerns=retrieval_concerns,
            # AD-567d: Activation-based lifecycle
            activation_pruned=activation_pruned,
            activation_reinforced=activation_reinforced,
            # AD-569: Behavioral metrics
            behavioral_quality_score=behavioral_quality_score,
            frame_diversity_score=frame_diversity_score,
            synthesis_rate=synthesis_rate,
            cross_dept_trigger_rate=cross_dept_trigger_rate,
            anchor_grounded_rate=anchor_grounded_rate,
            # AD-568d: Source attribution
            source_attribution=_source_attr_result,
            # AD-568e: Faithfulness verification
            mean_faithfulness_score=_source_attr_result.get("mean_faithfulness_score"),
            unfaithful_episodes=_source_attr_result.get("unfaithful_episodes", 0),
            # AD-599: Reflection episodes
            reflections_created=reflections_created,
            # AD-671: Dream-WM bridge
            wm_entries_flushed=wm_entries_flushed,
            wm_priming_entries=wm_priming_entries,
        )

        logger.info(
            "dream-cycle: flushed=%d strengthened=%d pruned=%d trust_adjusted=%d "
            "clusters=%d procedures=%d evolved=%d negatives=%d fallback_evolved=%d "
            "observed=%d decayed=%d archived=%d dedup=%d gaps=%d classified=%d "
            "qual_paths=%d gap_reports=%d contradictions=%d "
            "activation_pruned=%d activation_reinforced=%d "
            "wm_flushed=%d wm_primed=%d",
            report.episodes_replayed,
            report.weights_strengthened,
            report.weights_pruned,
            report.trust_adjustments,
            report.clusters_found,
            procedures_extracted,
            procedures_evolved,
            negative_procedures_extracted,
            fallback_stats.get("evolved", 0),
            procedures_observed,
            procedures_decayed,
            procedures_archived,
            dedup_candidates_found,
            report.gaps_predicted,
            gaps_classified,
            qualification_paths_triggered,
            gap_reports_generated,
            report.contradictions_found,
            activation_pruned,
            activation_reinforced,
            wm_entries_flushed,
            wm_priming_entries,
        )

        return report

    async def _evolve_degraded_procedures(
        self, episodes: list[Episode], procedures: list,
    ) -> int:
        """Scan active procedures for degraded metrics and evolve. Returns count of evolved."""
        active = await self._procedure_store.list_active()
        if not active:
            return 0

        evolved_count = 0
        now = time.time()

        for entry in active:
            proc_id = entry["id"]
            metrics = await self._procedure_store.get_quality_metrics(proc_id)
            if not metrics:
                continue

            diagnosis = diagnose_procedure_health(metrics, min_selections=PROCEDURE_MIN_SELECTIONS)
            if not diagnosis:
                continue

            # Anti-loop guard: skip if addressed recently
            last_attempt = self._addressed_degradations.get(proc_id, 0.0)
            if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
                continue

            # Load full procedure
            parent = await self._procedure_store.get(proc_id)
            if not parent:
                continue

            # Find fresh episodes via recall_by_intent for each intent type
            fresh_episodes: list = []
            seen_ids: set = set()
            for intent_type in (parent.intent_types or []):
                try:
                    recalled = await self.episodic_memory.recall_by_intent(intent_type)
                    for ep in recalled:
                        if ep.id not in seen_ids:
                            fresh_episodes.append(ep)
                            seen_ids.add(ep.id)
                except Exception:
                    continue

            # Limit to 10 most recent
            fresh_episodes = fresh_episodes[:10]

            if not fresh_episodes:
                self._addressed_degradations[proc_id] = now
                continue

            # Dispatch to appropriate evolution function
            result = None
            if diagnosis.startswith("FIX:"):
                result = await evolve_fix_procedure(
                    parent, diagnosis, metrics, fresh_episodes, self._llm_client,
                )
            elif diagnosis.startswith("DERIVED:"):
                result = await evolve_derived_procedure(
                    [parent], fresh_episodes, self._llm_client,
                )

            # Record attempt regardless of outcome
            self._addressed_degradations[proc_id] = time.time()

            if result is None:
                continue

            # Persist evolved procedure
            try:
                await self._procedure_store.save(
                    result.procedure,
                    content_diff=result.content_diff,
                    change_summary=result.change_summary,
                )
            except Exception as e:
                logger.debug("Failed to save evolved procedure: %s", e)
                continue

            # FIX: deactivate parent. DERIVED: parents stay active.
            if diagnosis.startswith("FIX:"):
                try:
                    await self._procedure_store.deactivate(
                        parent.id, superseded_by=result.procedure.id,
                    )
                except Exception as e:
                    logger.debug("Failed to deactivate parent procedure: %s", e)

            procedures.append(result.procedure)
            evolved_count += 1
            logger.info(
                "Procedure evolved (%s): '%s' -> '%s'",
                result.procedure.evolution_type,
                parent.name,
                result.procedure.name,
            )

        return evolved_count

    async def _attempt_procedure_evolution(
        self,
        parent: Any,  # Procedure
        diagnosis: str,
        metrics: dict[str, Any],
        require_confirmation: bool = False,
    ) -> bool:
        """Shared diagnosis+evolve logic for Step 7b and proactive scan.

        Returns True if evolution succeeded.
        """
        proc_id = parent.id
        now = time.time()

        # Anti-loop guard
        last_attempt = self._addressed_degradations.get(proc_id, 0.0)
        if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
            return False

        # LLM confirmation gate (proactive only)
        if require_confirmation:
            evidence = (
                f"total_selections={metrics.get('total_selections', 0)}, "
                f"fallback_rate={metrics.get('fallback_rate', 0.0):.2f}, "
                f"completion_rate={metrics.get('completion_rate', 0.0):.2f}, "
                f"effective_rate={metrics.get('effective_rate', 0.0):.2f}"
            )
            confirmed = await confirm_evolution_with_llm(
                parent.name, diagnosis, evidence, self._llm_client,
            )
            if not confirmed:
                self._addressed_degradations[proc_id] = now
                return False

        # Recall fresh episodes
        fresh_episodes: list = []
        seen_ids: set = set()
        for intent_type in (parent.intent_types or []):
            try:
                recalled = await self.episodic_memory.recall_by_intent(intent_type)
                for ep in recalled:
                    if ep.id not in seen_ids:
                        fresh_episodes.append(ep)
                        seen_ids.add(ep.id)
            except Exception:
                continue
        fresh_episodes = fresh_episodes[:10]

        if not fresh_episodes:
            self._addressed_degradations[proc_id] = now
            return False

        # Dispatch to appropriate evolution function with retry
        result = None
        if diagnosis.startswith("FIX:"):
            result = await evolve_with_retry(
                evolve_fix_procedure,
                parent, diagnosis, metrics, fresh_episodes, self._llm_client,
            )
        elif diagnosis.startswith("DERIVED:"):
            result = await evolve_with_retry(
                evolve_derived_procedure,
                [parent], fresh_episodes, self._llm_client,
            )

        self._addressed_degradations[proc_id] = time.time()

        if result is None:
            return False

        # Persist
        try:
            await self._procedure_store.save(
                result.procedure,
                content_diff=result.content_diff,
                change_summary=result.change_summary,
            )
        except Exception as e:
            logger.debug("Failed to save evolved procedure: %s", e)
            return False

        if diagnosis.startswith("FIX:"):
            try:
                await self._procedure_store.deactivate(
                    parent.id, superseded_by=result.procedure.id,
                )
            except Exception as e:
                logger.debug("Failed to deactivate parent procedure: %s", e)

        logger.info(
            "Procedure evolved (%s): '%s' -> '%s'",
            result.procedure.evolution_type,
            parent.name,
            result.procedure.name,
        )
        return True

    async def on_task_execution_complete(self, event_data: dict[str, Any]) -> None:
        """AD-532e: Reactive trigger — analyze post-execution for evolution opportunities."""
        try:
            # Guard clauses
            if event_data.get("used_procedure"):
                return
            if not event_data.get("success"):
                return
            if not self._procedure_store or not self._llm_client:
                return

            agent_id = event_data.get("agent_id", "")
            intent_type = event_data.get("intent_type", "")

            # Rate limit per agent
            now = time.time()
            last_check = self._reactive_cooldowns.get(agent_id, 0.0)
            if now - last_check < REACTIVE_COOLDOWN_SECONDS:
                return
            self._reactive_cooldowns[agent_id] = now

            # Find matching procedure
            match = await self._procedure_store.find_matching(
                intent_type, threshold=PROCEDURE_MATCH_THRESHOLD,
            )
            if not match:
                self._extraction_candidates[intent_type] = now
                return

            proc_id = match.get("id", "")
            metrics = await self._procedure_store.get_quality_metrics(proc_id)
            if not metrics:
                return

            diagnosis = diagnose_procedure_health(
                metrics, min_selections=PROCEDURE_MIN_SELECTIONS,
            )
            if not diagnosis:
                return

            # Load full procedure and attempt evolution
            parent = await self._procedure_store.get(proc_id)
            if not parent:
                return

            await self._attempt_procedure_evolution(
                parent, diagnosis, metrics, require_confirmation=True,
            )

        except Exception as e:
            logger.debug("Reactive trigger failed (non-critical): %s", e)

    async def on_procedure_fallback_learning(self, event_data: dict[str, Any]) -> None:
        """AD-534b: Queue fallback evidence for dream-time targeted evolution."""
        try:
            if not self._procedure_store or not self._llm_client:
                return

            from probos.config import MAX_FALLBACK_QUEUE_SIZE

            # Queue cap — FIFO eviction
            if len(self._fallback_learning_queue) >= MAX_FALLBACK_QUEUE_SIZE:
                self._fallback_learning_queue.pop(0)

            self._fallback_learning_queue.append(event_data)
            logger.debug(
                "Fallback learning event queued: type=%s procedure=%s",
                event_data.get("fallback_type", ""),
                event_data.get("procedure_name", ""),
            )
        except Exception as e:
            logger.debug("Fallback learning handler failed (non-critical): %s", e)

    async def _process_fallback_learning(self) -> dict[str, Any]:
        """AD-534b: Dream Step 7d — process fallback learning queue for targeted FIX evolution.

        Returns stats dict with evolved/processed/skipped_cooldown/negative_veto_flagged.
        """
        empty_stats = {"evolved": 0, "processed": 0, "skipped_cooldown": 0, "negative_veto_flagged": 0}
        if not self._fallback_learning_queue or not self._procedure_store or not self._llm_client:
            return empty_stats

        # Drain queue
        queue = list(self._fallback_learning_queue)
        self._fallback_learning_queue.clear()

        # Group by procedure_id — most recent wins
        by_proc: dict[str, dict[str, Any]] = {}
        for event in queue:
            proc_id = event.get("procedure_id", "")
            if proc_id:
                by_proc[proc_id] = event  # later events overwrite earlier

        evolved_count = 0
        skipped_cooldown = 0
        negative_veto_flagged = 0
        now = time.time()

        for proc_id, event in by_proc.items():
            try:
                fallback_type = event.get("fallback_type", "")

                # Anti-loop guard
                last_attempt = self._addressed_degradations.get(proc_id, 0.0)
                if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
                    skipped_cooldown += 1
                    continue

                # Handle negative_veto — flag for extraction, no evolution
                if fallback_type == "negative_veto":
                    intent_type = event.get("intent_type", "")
                    if intent_type:
                        self._extraction_candidates[intent_type] = now
                    negative_veto_flagged += 1
                    logger.debug(
                        "Fallback learning: negative_veto for %s flagged as extraction candidate",
                        proc_id[:8],
                    )
                    continue

                # Load procedure
                parent = await self._procedure_store.get(proc_id)
                if not parent or not parent.is_active:
                    continue

                # Gather fresh episodes
                fresh_episodes: list = []
                seen_ids: set = set()
                for intent_type in (parent.intent_types or []):
                    try:
                        recalled = await self.episodic_memory.recall_by_intent(intent_type)
                        for ep in recalled:
                            if ep.id not in seen_ids:
                                fresh_episodes.append(ep)
                                seen_ids.add(ep.id)
                    except Exception:
                        continue
                fresh_episodes = fresh_episodes[:10]

                # Call evolution with retry
                result = await evolve_with_retry(
                    evolve_fix_from_fallback,
                    parent,
                    fallback_type,
                    event.get("llm_response", ""),
                    event.get("rejection_reason", ""),
                    fresh_episodes,
                    self._llm_client,
                )

                # Record attempt regardless of outcome
                self._addressed_degradations[proc_id] = time.time()

                if result is None:
                    continue

                # Persist evolved procedure
                try:
                    await self._procedure_store.save(
                        result.procedure,
                        content_diff=result.content_diff,
                        change_summary=result.change_summary,
                    )
                except Exception as e:
                    logger.debug("Failed to save fallback-evolved procedure: %s", e)
                    continue

                # execution_failure → deactivate parent (it demonstrably failed)
                # near-miss types → keep parent active (it wasn't tried)
                if fallback_type == "execution_failure":
                    try:
                        await self._procedure_store.deactivate(
                            parent.id, superseded_by=result.procedure.id,
                        )
                    except Exception as e:
                        logger.debug("Failed to deactivate parent procedure: %s", e)

                evolved_count += 1
                logger.info(
                    "Fallback FIX evolution: '%s' -> '%s' (type=%s)",
                    parent.name, result.procedure.name, fallback_type,
                )

            except Exception as e:
                logger.debug("Fallback learning failed for %s: %s", proc_id[:8], e)
                continue

        return {
            "evolved": evolved_count,
            "processed": len(queue),
            "skipped_cooldown": skipped_cooldown,
            "negative_veto_flagged": negative_veto_flagged,
        }

    async def _process_observational_learning(self) -> dict[str, int]:
        """AD-537: Dream Step 7e — scan Ward Room threads for observational learning.

        Returns stats dict with observed/scanned counts.
        """
        stats: dict[str, int] = {"observed": 0, "scanned": 0}

        if not self._ward_room or not self._llm_client or not self._procedure_store:
            return stats
        if not self._agent_id:
            return stats

        try:
            lookback = OBSERVATION_WARD_ROOM_LOOKBACK_HOURS * 3600
            since_ts = time.time() - lookback
            max_threads = OBSERVATION_MAX_THREADS_PER_DREAM

            threads = await self._ward_room.browse_threads(
                agent_id=self._agent_id,
                limit=max_threads,
                since=since_ts,
                sort="recent",
            )
        except Exception as e:
            logger.debug("Step 7e: Failed to fetch Ward Room threads: %s", e)
            return stats

        for thread in threads:
            thread_id = getattr(thread, "id", "")
            if not thread_id:
                continue

            stats["scanned"] += 1

            # Skip already-observed threads
            if thread_id in self._observed_threads:
                continue

            # Skip DM channels (teaching path, not observation)
            channel_name = getattr(thread, "channel_name", "") or ""
            if channel_name.startswith("dm:"):
                continue

            # Skip own threads
            author_id = getattr(thread, "author_id", "")
            if author_id == self._agent_id:
                continue

            # Get author trust
            author_trust = 0.5
            if self._trust_network_lookup:
                try:
                    author_trust = self._trust_network_lookup(author_id)
                except Exception:
                    pass

            if author_trust < OBSERVATION_MIN_TRUST:
                continue

            # Format thread content
            title = getattr(thread, "title", "")
            body = getattr(thread, "body", "")
            author_callsign = getattr(thread, "author_callsign", author_id)
            thread_content = f"Thread: {title}\nAuthor: {author_callsign}\n\n{body}"

            # Extract procedure
            try:
                procedure = await extract_procedure_from_observation(
                    thread_content=thread_content,
                    observer_agent_type=self._agent_id,
                    author_callsign=author_callsign,
                    author_trust=author_trust,
                    llm_client=self._llm_client,
                )
            except Exception as e:
                logger.debug("Step 7e: Extraction failed for thread %s: %s", thread_id[:8], e)
                self._observed_threads.add(thread_id)
                continue

            if procedure is None:
                self._observed_threads.add(thread_id)
                continue

            # Check for semantic duplicates (direct experience takes priority)
            try:
                existing = await self._procedure_store.find_matching(
                    procedure.name,
                    n_results=1,
                )
                if existing and existing[0].get("score", 0) > 0.8:
                    self._observed_threads.add(thread_id)
                    continue
            except Exception:
                pass  # ChromaDB not available — skip dedup

            # Tag with thread provenance
            procedure.tags.append(f"ward_room_thread:{thread_id}")

            try:
                await self._procedure_store.save(procedure)
                stats["observed"] += 1
                logger.info(
                    "Observed procedure '%s' from %s's discussion",
                    procedure.name, author_callsign,
                )
            except Exception as e:
                logger.debug("Step 7e: Failed to save observed procedure: %s", e)

            self._observed_threads.add(thread_id)

        return stats

    async def proactive_procedure_scan(self) -> dict[str, Any]:
        """AD-532e: Proactive trigger — periodic health scan of all active procedures."""
        if not self._procedure_store or not self._llm_client:
            return {"scanned": 0, "evolved": 0, "skipped_cooldown": 0}

        scanned = 0
        evolved = 0
        skipped_cooldown = 0

        try:
            active = await self._procedure_store.list_active()
            if not active:
                return {"scanned": 0, "evolved": 0, "skipped_cooldown": 0}

            now = time.time()
            for entry in active:
                scanned += 1
                proc_id = entry["id"]

                try:
                    metrics = await self._procedure_store.get_quality_metrics(proc_id)
                    if not metrics:
                        continue

                    diagnosis = diagnose_procedure_health(
                        metrics, min_selections=PROCEDURE_MIN_SELECTIONS,
                    )
                    if not diagnosis:
                        continue

                    # Anti-loop guard check
                    last_attempt = self._addressed_degradations.get(proc_id, 0.0)
                    if now - last_attempt < EVOLUTION_COOLDOWN_SECONDS:
                        skipped_cooldown += 1
                        continue

                    parent = await self._procedure_store.get(proc_id)
                    if not parent:
                        continue

                    success = await self._attempt_procedure_evolution(
                        parent, diagnosis, metrics, require_confirmation=True,
                    )
                    if success:
                        evolved += 1
                except Exception as e:
                    logger.debug(
                        "Proactive scan failed for procedure %s (non-critical): %s",
                        proc_id, e,
                    )

        except Exception as e:
            logger.debug("Proactive procedure scan failed (non-critical): %s", e)

        return {"scanned": scanned, "evolved": evolved, "skipped_cooldown": skipped_cooldown}

    def _replay_episodes(self, episodes: list[Episode]) -> int:
        """Replay episodes: strengthen weights for successes, weaken for failures."""
        strengthened = 0

        for episode in episodes:
            intents = self._extract_intents(episode)
            agent_ids = episode.agent_ids

            for outcome in episode.outcomes:
                intent = outcome.get("intent", "")
                success = outcome.get("success", False)

                if not intent:
                    continue

                # Strengthen/weaken the connection between this intent and
                # each agent that participated in the episode
                for agent_id in agent_ids:
                    if success:
                        current = self.router.get_weight(intent, agent_id, REL_INTENT)
                        new_weight = min(
                            1.0,
                            current + self.config.pathway_strengthening_factor,
                        )
                        self.router._weights[(intent, agent_id, REL_INTENT)] = new_weight
                        self.router._compat_weights[(intent, agent_id)] = new_weight
                        strengthened += 1
                    else:
                        current = self.router.get_weight(intent, agent_id, REL_INTENT)
                        new_weight = max(
                            0.0,
                            current - self.config.pathway_weakening_factor,
                        )
                        self.router._weights[(intent, agent_id, REL_INTENT)] = new_weight
                        self.router._compat_weights[(intent, agent_id)] = new_weight

        return strengthened

    def _prune_weights(self) -> int:
        """Apply decay and remove connections below prune threshold."""
        # First apply standard Hebbian decay
        self.router.decay_all()

        # Then remove anything below our (potentially higher) prune threshold
        pruned = 0
        keys_to_remove = []
        for key, weight in self.router._weights.items():
            if weight < self.config.prune_threshold:
                keys_to_remove.append(key)
                pruned += 1

        for key in keys_to_remove:
            del self.router._weights[key]

        # Rebuild compat view
        self.router._compat_weights.clear()
        for (src, tgt, _), w in self.router._weights.items():
            self.router._compat_weights[(src, tgt)] = w

        return pruned

    def _consolidate_trust(self, episodes: list[Episode]) -> int:
        """Adjust trust based on agent track records in recent episodes.

        Agents with many successes get a trust boost (alpha increment).
        Agents with many failures get a trust penalty (beta increment).
        """
        # Count successes and failures per agent across episodes
        agent_successes: Counter[str] = Counter()
        agent_failures: Counter[str] = Counter()

        for episode in episodes:
            all_success = all(o.get("success", False) for o in episode.outcomes) if episode.outcomes else False
            all_failed = all(not o.get("success", True) for o in episode.outcomes) if episode.outcomes else False

            for agent_id in episode.agent_ids:
                if all_success:
                    agent_successes[agent_id] += 1
                if all_failed:
                    agent_failures[agent_id] += 1

        adjustments = 0

        # Boost agents with consistent success (threshold: >1 successful episode)
        for agent_id, count in agent_successes.items():
            if count > 1:
                self.trust_network.record_outcome(
                    agent_id,
                    success=True,
                    weight=self.config.trust_boost,
                    source="dream_consolidation",
                )
                adjustments += 1

        # Penalize agents appearing in multiple failed episodes
        for agent_id, count in agent_failures.items():
            if count > 1:
                self.trust_network.record_outcome(
                    agent_id,
                    success=False,
                    weight=self.config.trust_penalty,
                    source="dream_consolidation",
                )
                adjustments += 1

        return adjustments

    def _compute_pre_warm(self, episodes: list[Episode]) -> list[str]:
        """Analyze temporal patterns to predict likely next intents.

        Looks at sequential intent pairs across episodes to find common
        transitions (e.g., list_directory -> read_file).
        """
        # Build bigram counts of intent sequences
        bigram_counts: Counter[str] = Counter()

        for episode in episodes:
            intents = self._extract_intents(episode)
            for i in range(len(intents) - 1):
                # The intent that follows another is a candidate for pre-warming
                bigram_counts[intents[i + 1]] += 1

        # Also count standalone intent frequency for recency weighting
        intent_freq: Counter[str] = Counter()
        for episode in episodes:
            for intent in self._extract_intents(episode):
                intent_freq[intent] += 1

        # Combine bigram successors with frequency
        combined: Counter[str] = Counter()
        for intent, count in bigram_counts.items():
            combined[intent] += count * 2  # Transition patterns weighted 2x
        for intent, count in intent_freq.items():
            combined[intent] += count

        # Return top-K
        return [intent for intent, _ in combined.most_common(self.config.pre_warm_top_k)]

    @staticmethod
    def _extract_intents(episode: Episode) -> list[str]:
        """Extract ordered list of intents from an episode's outcomes."""
        intents: list[str] = []
        for outcome in episode.outcomes:
            intent = outcome.get("intent", "")
            if intent:
                intents.append(intent)
        return intents

    async def _step_11_retrieval_practice(
        self, episodes: list[Episode],
    ) -> dict[str, Any]:
        """AD-541c: Spaced Retrieval Therapy — active recall practice per agent."""
        if not self.config.active_retrieval_enabled:
            return {"practices": 0, "accuracies": [], "concerns": 0}
        engine = self._retrieval_practice_engine
        llm = self._retrieval_llm_client
        if not engine or not llm:
            return {"practices": 0, "accuracies": [], "concerns": 0}

        # Collect unique agent IDs across all episodes
        agent_ids: set[str] = set()
        for ep in episodes:
            for aid in ep.agent_ids:
                agent_ids.add(aid)

        practices = 0
        accuracies: list[float] = []
        total_concerns = 0

        for agent_id in agent_ids:
            # Select episodes due for practice
            selected = engine.select_episodes_for_practice(episodes, agent_id)
            if not selected:
                continue

            for ep in selected:
                try:
                    prompt = engine.build_recall_prompt(ep)
                    expected = engine.build_expected_text(ep)
                    if not expected:
                        continue

                    # Fast-tier LLM recall
                    from probos.types import LLMRequest
                    req = LLMRequest(
                        prompt=prompt,
                        tier="fast",
                        max_tokens=256,
                    )
                    resp = await llm.complete(req)
                    recalled_text = resp.content if resp and resp.content else ""

                    # Score and update schedule
                    accuracy = engine.score_recall(recalled_text, expected)
                    sched = engine.update_schedule(agent_id, ep.id, accuracy)
                    await engine._save_schedule(sched)

                    practices += 1
                    accuracies.append(accuracy)
                except Exception:
                    logger.debug(
                        "Retrieval practice failed for agent=%s episode=%s",
                        agent_id[:8], ep.id[:8], exc_info=True,
                    )

            # Check for concerns after practicing
            concerns = engine.get_counselor_concerns(agent_id)
            if concerns:
                total_concerns += len(concerns)
                # Emit concern event if emit function available
                if hasattr(self, "_emit_event_fn") and self._emit_event_fn:
                    stats = engine.get_agent_recall_stats(agent_id)
                    try:
                        self._emit_event_fn("retrieval_practice_concern", {
                            "agent_id": agent_id,
                            "episodes_at_risk": stats.get("episodes_at_risk", 0),
                            "avg_recall_accuracy": stats.get("avg_recall_accuracy", 0.0),
                        })
                    except Exception:
                        pass

        return {
            "practices": practices,
            "accuracies": accuracies,
            "concerns": total_concerns,
        }

    # ---------------------------------------------------------------
    # Step 14: Source Attribution Consolidation (AD-568d)
    # ---------------------------------------------------------------
    async def _step_14_source_attribution(
        self, episodes: list[Any],
    ) -> dict[str, Any]:
        """Dream step 14: Consolidate source attribution patterns (AD-568d/e).

        Aggregates source attribution metadata from recent episodes to:
        1. Compute running confabulation rate estimate
        2. Measure source diversity (healthy agents use multiple sources)
        3. Update Counselor's CognitiveProfile with findings
        4. (AD-568e) Aggregate per-episode faithfulness scores

        Returns dict with consolidation metrics for DreamReport.
        """
        result: dict[str, Any] = {
            "episodes_with_attribution": 0,
            "source_distribution": {},
            "mean_confabulation_rate": 0.0,
            "source_diversity_score": 0.0,
            # AD-568e: Faithfulness aggregation
            "mean_faithfulness_score": 0.0,
            "unfaithful_episodes": 0,
            "faithfulness_episodes_assessed": 0,
        }

        if not episodes:
            return result

        # Extract source attribution and faithfulness from episode metadata
        attributions: list[dict[str, Any]] = []
        _faithfulness_scores: list[float] = []  # AD-568e

        for ep in episodes:
            # Try metadata attr first (test mocks), then dag_summary (real episodes)
            _meta = getattr(ep, 'metadata', None) or {}
            if isinstance(_meta, str):
                try:
                    import json
                    _meta = json.loads(_meta)
                except Exception:
                    _meta = {}
            if not isinstance(_meta, dict):
                _meta = {}

            # Also check dag_summary (where _store_action_episode puts data)
            _dag = getattr(ep, 'dag_summary', None) or {}
            if isinstance(_dag, str):
                try:
                    import json
                    _dag = json.loads(_dag)
                except Exception:
                    _dag = {}
            if not isinstance(_dag, dict):
                _dag = {}

            # Source attribution: check both locations
            _attr = _meta.get("source_attribution") or _dag.get("source_attribution")
            if _attr and isinstance(_attr, dict):
                attributions.append(_attr)

            # AD-568e: Extract faithfulness score
            _faith_score = _meta.get("faithfulness_score") or _dag.get("faithfulness_score")
            if _faith_score is not None:
                try:
                    _faithfulness_scores.append(float(_faith_score))
                except (ValueError, TypeError):
                    pass

        # Source attribution aggregation
        if attributions:
            result["episodes_with_attribution"] = len(attributions)

            # 1. Source distribution
            source_counts: dict[str, int] = {}
            for attr in attributions:
                src = attr.get("primary_source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
            result["source_distribution"] = source_counts

            # 2. Mean confabulation rate from attribution snapshots
            confab_rates = [
                attr.get("confabulation_rate", 0.0) for attr in attributions
            ]
            mean_confab = sum(confab_rates) / len(confab_rates) if confab_rates else 0.0
            result["mean_confabulation_rate"] = round(mean_confab, 4)

            # 3. Source diversity score (Shannon entropy normalized to [0, 1])
            total = sum(source_counts.values())
            if total > 0 and len(source_counts) > 1:
                import math
                entropy = -sum(
                    (c / total) * math.log2(c / total)
                    for c in source_counts.values()
                    if c > 0
                )
                max_entropy = math.log2(len(source_counts))
                diversity = entropy / max_entropy if max_entropy > 0 else 0.0
            else:
                diversity = 0.0
            result["source_diversity_score"] = round(diversity, 4)

            # 4. Update Counselor profile if available
            try:
                if self._counselor and hasattr(self._counselor, 'update_source_metrics'):
                    await self._counselor.update_source_metrics(
                        agent_id=self._agent_id,
                        confabulation_rate=mean_confab,
                        source_diversity=diversity,
                        source_distribution=source_counts,
                    )
            except Exception:
                logger.debug("AD-568d: Could not update Counselor source metrics")

        # AD-568e: Aggregate faithfulness scores
        if _faithfulness_scores:
            _mean_faithfulness = sum(_faithfulness_scores) / len(_faithfulness_scores)
            _unfaithful_count = sum(1 for s in _faithfulness_scores if s < 0.5)
            result["mean_faithfulness_score"] = round(_mean_faithfulness, 4)
            result["unfaithful_episodes"] = _unfaithful_count
            result["faithfulness_episodes_assessed"] = len(_faithfulness_scores)

        return result

    async def _step_15_reflection_promotion(
        self,
        *,
        episodes: list,
        clusters: list,
        convergence_reports: list[dict],
        emergence_capacity: float | None,
        coordination_balance: float | None,
        notebook_consolidations: int,
        behavioral_quality_score: float | None,
    ) -> int:
        """AD-599: Promote dream consolidation insights into recallable episodes.

        Scans this dream cycle's outputs for high-value analytical insights and
        creates [Reflection] episodes in EpisodicMemory. These synthetic episodes
        are semantically rich and naturally score well on pattern/trend queries
        without custom retrieval logic.

        Returns the number of reflection episodes created.

        Rate limiting: max ``config.reflection_max_per_cycle`` per dream cycle.
        Deduplication: content-hash check against existing episodes (write-once
        guard in EpisodicMemory.store() handles collisions).
        """
        import hashlib

        from probos.types import AnchorFrame

        max_reflections = self.config.reflection_max_per_cycle
        importance = self.config.reflection_min_importance
        created = 0

        # Collect candidate reflection texts from this cycle's outputs.
        # Each candidate is (content_text, agent_ids_list).
        candidates: list[tuple[str, list[str]]] = []

        # Source 1: Convergence reports (Step 7g) — cross-agent analytical findings
        for conv in convergence_reports:
            agents = conv.get("agents", [])
            topic = conv.get("topic", "unknown")
            coherence = conv.get("coherence", 0.0)
            depts = conv.get("departments", [])
            text = (
                f"[Reflection] Convergence detected across {len(agents)} agents "
                f"in {len(depts)} departments on topic '{topic}' "
                f"(coherence={coherence:.3f}). "
                f"Agents: {', '.join(agents)}. "
                f"Departments: {', '.join(depts)}."
            )
            independence = conv.get("independence", "")
            if independence:
                text += f" Independence: {independence}."
            candidates.append((text, agents))

        # Source 2: Emergence metrics snapshot (Step 9)
        if emergence_capacity is not None:
            parts = [
                f"[Reflection] Dream cycle emergence snapshot: "
                f"capacity={emergence_capacity:.3f}",
            ]
            if coordination_balance is not None:
                parts.append(f"coordination_balance={coordination_balance:.3f}")
            if behavioral_quality_score is not None:
                parts.append(f"behavioral_quality={behavioral_quality_score:.3f}")
            text = ", ".join(parts) + "."
            candidates.append((text, []))

        # Source 3: Notebook consolidation summary (Step 7g)
        if notebook_consolidations > 0:
            text = (
                f"[Reflection] Dream consolidation merged {notebook_consolidations} "
                f"redundant notebook clusters. Knowledge base compacted."
            )
            candidates.append((text, []))

        # Source 4: Cluster-level patterns (Step 6) — only dominant clusters
        for cluster in clusters:
            if len(getattr(cluster, "episode_ids", [])) < 5:
                continue  # Only reflect on substantial clusters
            is_success = getattr(cluster, "is_success_dominant", False)
            is_failure = getattr(cluster, "is_failure_dominant", False)
            if not (is_success or is_failure):
                continue
            ep_count = len(cluster.episode_ids)
            label = "success" if is_success else "failure"
            cluster_id = getattr(cluster, "cluster_id", "unknown")
            # Extract agent participation from cluster episodes
            cluster_ep_ids = set(cluster.episode_ids)
            cluster_agents: list[str] = []
            for ep in episodes:
                if ep.id in cluster_ep_ids:
                    cluster_agents.extend(ep.agent_ids)
            cluster_agents = sorted(set(cluster_agents))
            text = (
                f"[Reflection] Identified {label}-dominant pattern cluster "
                f"(cluster_id={cluster_id}) "
                f"with {ep_count} episodes. "
                f"Agents involved: {', '.join(cluster_agents[:5])}."
            )
            anchor_summary = getattr(cluster, "anchor_summary", None)
            if anchor_summary:
                text += f" Anchor context: {str(anchor_summary)[:200]}."
            candidates.append((text, cluster_agents[:5]))

        # Apply rate limit — take the first N candidates (convergence > emergence > notebook > clusters)
        candidates = candidates[:max_reflections]

        now = time.time()

        for content_text, involved_agents in candidates:
            # Deterministic ID from content hash — prevents duplicates across cycles
            content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16]
            episode_id = f"reflection-{content_hash}"

            # Build AnchorFrame with dream provenance
            anchors = AnchorFrame(
                trigger_type="dream_consolidation",
            )

            episode = Episode(
                id=episode_id,
                timestamp=now,
                user_input=content_text,
                dag_summary={
                    "type": "reflection",
                    "source": "dream_consolidation",
                    "involved_agents": involved_agents,
                },
                outcomes=[],
                reflection=content_text,
                agent_ids=[],
                duration_ms=0.0,
                source=MemorySource.REFLECTION,
                anchors=anchors,
                importance=importance,
            )

            try:
                await self.episodic_memory.store(episode)
                created += 1
            except Exception:
                logger.debug(
                    "AD-599: Failed to store reflection episode %s",
                    episode_id[:12],
                    exc_info=True,
                )

        return created


class DreamScheduler:
    """Background scheduler that triggers dream cycles during idle periods."""

    def __init__(
        self,
        engine: DreamingEngine,
        idle_threshold_seconds: float = 300.0,
        dream_interval_seconds: float = 600.0,
        micro_dream_interval_seconds: float = 10.0,
    ) -> None:
        self.engine = engine
        self.idle_threshold_seconds = idle_threshold_seconds
        self.dream_interval_seconds = dream_interval_seconds
        self.micro_dream_interval_seconds = micro_dream_interval_seconds

        self._last_activity_time: float = time.monotonic()
        self._last_dream_time: float = 0.0
        self._last_micro_dream_time: float = 0.0
        self._micro_dream_count: int = 0
        self._last_proactive_scan_time: float = 0.0  # AD-532e
        self._is_dreaming: bool = False
        self._emergent_detector: Any = None  # BF-100: Set via set_emergent_detector()
        self._task: asyncio.Task[None] | None = None
        self._last_dream_report: DreamReport | None = None
        self._stopped = False
        self._post_dream_fn: Any = None  # Optional callback(dream_report) after each cycle
        self._pre_dream_fn: Any = None  # Optional callback() before each cycle (AD-254)
        self._post_micro_dream_fn: Any = None  # Optional callback(micro_report) after micro-dream
        self._emit_event_fn: Callable[..., Any] | None = None  # AD-503: Event emission

    @property
    def is_dreaming(self) -> bool:
        return self._is_dreaming

    @property
    def last_dream_report(self) -> DreamReport | None:
        return self._last_dream_report

    def record_activity(self) -> None:
        """Record that user activity occurred (resets idle timer)."""
        self._last_activity_time = time.monotonic()

    def start(self) -> None:
        """Start the background monitoring task."""
        if self._task is not None:
            return
        self._stopped = False
        self._last_activity_time = time.monotonic()
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def force_dream(self) -> DreamReport:
        """Force an immediate dream cycle (for /dream now command)."""
        self._is_dreaming = True
        if self._emergent_detector:
            self._emergent_detector.set_dreaming(True)
        if self._pre_dream_fn:
            try:
                self._pre_dream_fn()
            except Exception as e:
                logger.debug("Pre-dream callback failed: %s", e)
        try:
            report = await self.engine.dream_cycle()
            self._last_dream_report = report
            self._last_dream_time = time.monotonic()
            # AD-503: Emit dream complete event
            if self._emit_event_fn:
                try:
                    self._emit_event_fn(
                        "dream_complete",
                        {
                            "dream_type": "full",
                            "duration_ms": getattr(report, "duration_ms", 0),
                            "episodes_replayed": len(getattr(report, "episodes_replayed", [])),
                            "clusters_found": getattr(report, "clusters_found", 0),
                            "notebook_consolidations": getattr(report, "notebook_consolidations", 0),
                            "convergence_reports_generated": getattr(report, "convergence_reports_generated", 0),
                        },
                    )
                except Exception:
                    logger.debug("Dream complete event emission failed", exc_info=True)
            if self._post_dream_fn:
                try:
                    self._post_dream_fn(report)
                except Exception as e:
                    logger.debug("Post-dream callback failed: %s", e)
            return report
        finally:
            self._is_dreaming = False
            if self._emergent_detector:
                self._emergent_detector.set_dreaming(False)

    async def _monitor_loop(self) -> None:
        """Background loop: micro-dream every 10s, full dream when idle."""
        while not self._stopped:
            try:
                await asyncio.sleep(1.0)

                if self._is_dreaming:
                    continue

                now = time.monotonic()

                # Tier 1: Micro-dream every N seconds (unconditional, lightweight)
                if now - self._last_micro_dream_time >= self.micro_dream_interval_seconds:
                    try:
                        report = await self.engine.micro_dream()
                        self._last_micro_dream_time = now
                        if report.get("episodes_replayed", 0) > 0:
                            self._micro_dream_count += 1
                            # AD-503: Emit dream complete event (micro)
                            if self._emit_event_fn:
                                try:
                                    self._emit_event_fn(
                                        "dream_complete",
                                        {
                                            "dream_type": "micro",
                                            "episodes_replayed": report.get("episodes_replayed", 0),
                                        },
                                    )
                                except Exception:
                                    logger.debug("Micro-dream complete event emission failed", exc_info=True)
                            if self._post_micro_dream_fn:
                                try:
                                    self._post_micro_dream_fn(report)
                                except Exception as e:
                                    logger.debug("Post-micro-dream callback failed: %s", e)
                    except Exception as e:
                        logger.debug("Micro-dream failed: %s", e)

                # Tier 1.5: Proactive procedure scan (AD-532e)
                if (
                    not self._is_dreaming
                    and self._last_proactive_scan_time is not None
                    and now - self._last_proactive_scan_time >= PROACTIVE_SCAN_INTERVAL_SECONDS
                ):
                    try:
                        scan_result = await self.engine.proactive_procedure_scan()
                        self._last_proactive_scan_time = now
                        if scan_result.get("evolved", 0) > 0:
                            logger.debug("Proactive scan evolved %d procedures", scan_result["evolved"])
                    except Exception as e:
                        logger.debug("Proactive procedure scan failed: %s", e)

                # Tier 2: Full dream when idle long enough
                idle_time = now - self._last_activity_time
                time_since_last_dream = now - self._last_dream_time

                if (
                    idle_time >= self.idle_threshold_seconds
                    and time_since_last_dream >= self.dream_interval_seconds
                ):
                    self._is_dreaming = True
                    if self._emergent_detector:
                        self._emergent_detector.set_dreaming(True)
                    if self._pre_dream_fn:
                        try:
                            self._pre_dream_fn()
                        except Exception as e:
                            logger.debug("Pre-dream callback failed: %s", e)
                    try:
                        report = await self.engine.dream_cycle()
                        self._last_dream_report = report
                        self._last_dream_time = time.monotonic()
                        # AD-503: Emit dream complete event (monitor loop, full)
                        if self._emit_event_fn:
                            try:
                                self._emit_event_fn(
                                    "dream_complete",
                                    {
                                        "dream_type": "full",
                                        "duration_ms": getattr(report, "duration_ms", 0),
                                        "episodes_replayed": len(getattr(report, "episodes_replayed", [])),
                                        "clusters_found": getattr(report, "clusters_found", 0),
                                        "notebook_consolidations": getattr(report, "notebook_consolidations", 0),
                                        "convergence_reports_generated": getattr(report, "convergence_reports_generated", 0),
                                    },
                                )
                            except Exception:
                                logger.debug("Dream complete event emission failed", exc_info=True)
                        if self._post_dream_fn:
                            try:
                                self._post_dream_fn(report)
                            except Exception as e:
                                logger.debug("Post-dream callback failed: %s", e)
                    except Exception as e:
                        logger.warning("Dream cycle failed: %s", e)
                    finally:
                        self._is_dreaming = False
                        if self._emergent_detector:
                            self._emergent_detector.set_dreaming(False)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Dream monitor error: %s", e)

    # ------------------------------------------------------------------
    # AD-514: Public API for callback injection
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        *,
        pre_dream: Callable | None = None,
        post_dream: Callable | None = None,
        post_micro_dream: Callable | None = None,
    ) -> None:
        """Set lifecycle callbacks for dream events."""
        if pre_dream is not None:
            self._pre_dream_fn = pre_dream
        if post_dream is not None:
            self._post_dream_fn = post_dream
        if post_micro_dream is not None:
            self._post_micro_dream_fn = post_micro_dream

    def set_emergent_detector(self, detector: Any) -> None:
        """Wire EmergentDetector for BF-100 dream cycle suppression."""
        self._emergent_detector = detector

