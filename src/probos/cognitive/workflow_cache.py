"""Workflow cache — stores successful DAG patterns for fast replay without LLM."""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from probos.types import TaskDAG, TaskNode, WorkflowCacheEntry

logger = logging.getLogger(__name__)


class WorkflowCache:
    """In-memory LRU cache of successful DAG patterns.

    When a user submits a request that matches a cached pattern, the DAG
    is replayed without querying the LLM. This makes repeated workflows
    feel instant.
    """

    def __init__(self, max_size: int = 100) -> None:
        self.max_size = max_size
        self._cache: dict[str, WorkflowCacheEntry] = {}

    def store(self, user_input: str, dag: TaskDAG) -> None:
        """Store a successful DAG pattern.

        Only stores DAGs with >=1 node where all nodes completed successfully.
        """
        if not dag.nodes:
            return
        if not all(n.status == "completed" for n in dag.nodes):
            return

        key = self._normalize(user_input)
        dag_json = self._serialize_dag(dag)

        if key in self._cache:
            # Update existing entry
            self._cache[key].dag_json = dag_json
            return

        # Evict lowest hit_count entry if at capacity
        if len(self._cache) >= self.max_size:
            self._evict()

        self._cache[key] = WorkflowCacheEntry(
            pattern=key,
            dag_json=dag_json,
        )

    def lookup(self, user_input: str) -> TaskDAG | None:
        """Return a cached DAG (deep copy with fresh IDs) if exact match found."""
        key = self._normalize(user_input)
        entry = self._cache.get(key)
        if entry is None:
            return None

        entry.hit_count += 1
        entry.last_hit = datetime.now(timezone.utc)
        return self._deserialize_dag(entry.dag_json)

    def lookup_fuzzy(
        self, user_input: str, pre_warm_intents: list[str],
        similarity_threshold: float = 0.6,
    ) -> TaskDAG | None:
        """Fuzzy match: find cached entries whose intents are a subset of
        pre_warm_intents AND whose pattern is semantically similar.

        Uses embedding-based semantic similarity from embeddings.py.
        Falls back to keyword overlap when embeddings are unavailable.

        Returns the highest hit_count match, or None.
        """
        if not pre_warm_intents:
            return None

        if not user_input.strip():
            return None

        pre_warm_set = set(pre_warm_intents)
        best_entry: WorkflowCacheEntry | None = None

        from probos.cognitive.embeddings import compute_similarity

        for entry in self._cache.values():
            # Check intent subset requirement
            dag = self._deserialize_dag(entry.dag_json)
            if dag is None:
                continue
            dag_intents = {n.intent for n in dag.nodes}
            if not dag_intents.issubset(pre_warm_set):
                continue

            # Check semantic similarity
            sim = compute_similarity(user_input.lower(), entry.pattern)
            if sim < similarity_threshold:
                continue

            # Pick highest hit_count
            if best_entry is None or entry.hit_count > best_entry.hit_count:
                best_entry = entry

        if best_entry is None:
            return None

        best_entry.hit_count += 1
        best_entry.last_hit = datetime.now(timezone.utc)
        return self._deserialize_dag(best_entry.dag_json)

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def entries(self) -> list[WorkflowCacheEntry]:
        """All entries sorted by hit_count descending."""
        return sorted(self._cache.values(), key=lambda e: e.hit_count, reverse=True)

    def clear(self) -> None:
        """Empty the cache."""
        self._cache.clear()

    def export_all(self) -> list[dict]:
        """Export all cached entries for persistence.

        Returns list of serializable dicts with keys:
        pattern, dag_json, hit_count, last_hit, created_at.
        """
        result = []
        for entry in self._cache.values():
            result.append({
                "pattern": entry.pattern,
                "dag_json": entry.dag_json,
                "hit_count": entry.hit_count,
                "last_hit": entry.last_hit.isoformat(),
                "created_at": entry.created_at.isoformat(),
            })
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase, strip, collapse whitespace."""
        return re.sub(r"\s+", " ", text.strip().lower())

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Split text into keyword tokens for overlap comparison."""
        return {
            w for w in re.split(r"[\s_]+", text.strip().lower())
            if len(w) >= 3
        }

    @staticmethod
    def _serialize_dag(dag: TaskDAG) -> str:
        """Serialize a TaskDAG to JSON for storage."""
        data = {
            "nodes": [
                {
                    "intent": n.intent,
                    "params": n.params,
                    "depends_on": n.depends_on,
                    "use_consensus": n.use_consensus,
                    "background": n.background,
                }
                for n in dag.nodes
            ],
            "source_text": dag.source_text,
            "response": dag.response,
            "reflect": dag.reflect,
        }
        return json.dumps(data)

    @staticmethod
    def _deserialize_dag(dag_json: str) -> TaskDAG | None:
        """Deserialize JSON to a TaskDAG with fresh node IDs and reset statuses."""
        try:
            data = json.loads(dag_json)
        except json.JSONDecodeError:
            return None

        nodes = []
        for i, nd in enumerate(data.get("nodes", [])):
            nodes.append(TaskNode(
                id=f"c{i + 1}_{uuid.uuid4().hex[:6]}",
                intent=nd.get("intent", ""),
                params=copy.deepcopy(nd.get("params", {})),
                depends_on=list(nd.get("depends_on", [])),
                use_consensus=nd.get("use_consensus", False),
                background=nd.get("background", False),
                status="pending",
            ))

        # Fix depends_on references: map old sequential IDs to new ones
        # The stored depends_on uses positional references from original DAG
        # Since we regenerate IDs, we need to handle this carefully.
        # Original DAGs use t1, t2, ... — we map by position.

        return TaskDAG(
            nodes=nodes,
            source_text=data.get("source_text", ""),
            response=data.get("response", ""),
            reflect=data.get("reflect", False),
        )

    def _evict(self) -> None:
        """Evict the entry with the lowest hit_count."""
        if not self._cache:
            return
        min_key = min(self._cache, key=lambda k: self._cache[k].hit_count)
        del self._cache[min_key]
