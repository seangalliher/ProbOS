"""AD-1043: mine representative natural-language queries per capability.

Epic #989 Foundation 4/12. Discovery clients want to know not just *that* a
capability exists but *what a human actually asked* to reach it. This miner
harvests those example queries from two in-runtime sources and returns a map
``{intent_name: [queries]}`` that the AD-1041 projector attaches to each entry.

Sources (both honest-degrade, never raise):
  * **Workflow cache** (``runtime.workflow_cache``, AD-514) — the PRIMARY,
    zero-I/O source. Each cached entry pairs a normalized NL ``pattern`` with a
    serialized DAG; the DAG's ``nodes[].intent`` are the capabilities that
    ``pattern`` reaches. Synchronous, in-memory, bounded — safe on any path.
  * **Episodic memory** (``runtime.episodic_memory``, optional) — the SECONDARY
    source, gated behind ``episodic_k``. Each recent ``Episode`` pairs raw
    ``user_input`` with its ``dag_summary['intent_types']`` (falling back to its
    ``outcomes[].intent``). ``await``s ChromaDB, so the PUBLIC AD-1042 route
    passes ``episodic_k=0`` to skip it entirely (no I/O on an unauthenticated
    endpoint — an unauthenticated-resource-consumption guard). The parameter +
    logic are kept for future authenticated / cached callers (default 50).

Layer discipline: this module imports NOTHING from ``probos`` — it reads the
runtime's ``workflow_cache`` / ``episodic_memory`` via ``getattr`` (duck-typed),
so it never triggers a cycle and stays cheap to import.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _append_capped(
    out: dict[str, list[str]], intent: str, query: str, cap: int
) -> None:
    """Append ``query`` under ``intent`` (deduped, bounded by ``cap``)."""
    if not intent or not query:
        return
    bucket = out.setdefault(intent, [])
    if len(bucket) >= cap or query in bucket:
        return
    bucket.append(query)


async def mine_representative_queries(
    runtime: Any,
    *,
    per_resource_cap: int = 5,
    episodic_k: int = 50,
) -> dict[str, list[str]]:
    """Return ``{intent_name: [representative NL queries]}`` for the live ship.

    ``per_resource_cap`` bounds the queries kept per intent. ``episodic_k``
    bounds (and gates) the episodic pass: ``episodic_k <= 0`` skips episodic
    memory entirely (the PUBLIC AD-1042 route uses this — workflow-cache only,
    zero I/O). Honest-degrade: any source failure logs-and-continues; this
    function never raises.
    """
    out: dict[str, list[str]] = {}

    # --- PRIMARY: workflow cache (sync, zero-I/O) ----------------------------
    cache = getattr(runtime, "workflow_cache", None)
    if cache is not None:
        try:
            for entry in cache.entries:
                pattern = getattr(entry, "pattern", "") or ""
                if not pattern:
                    continue
                try:
                    nodes = json.loads(getattr(entry, "dag_json", "") or "{}").get("nodes", [])
                except Exception:
                    logger.debug("AD-1043: workflow-cache dag_json parse failed", exc_info=True)
                    continue
                for node in nodes or []:
                    _append_capped(out, node.get("intent", ""), pattern, per_resource_cap)
        except Exception:
            logger.debug("AD-1043: workflow-cache mining failed", exc_info=True)

    # --- SECONDARY: episodic memory (async, gated by episodic_k) -------------
    episodic = getattr(runtime, "episodic_memory", None)
    if episodic_k > 0 and episodic is not None:
        try:
            episodes = await episodic.recent(episodic_k)
        except Exception:
            logger.debug("AD-1043: episodic recall failed", exc_info=True)
            episodes = []
        for episode in episodes or []:
            try:
                user_input = getattr(episode, "user_input", "") or ""
                if not user_input:
                    continue
                summary = getattr(episode, "dag_summary", {}) or {}
                intents = list(summary.get("intent_types", []) or [])
                if not intents:
                    intents = [
                        o.get("intent", "")
                        for o in (getattr(episode, "outcomes", []) or [])
                        if isinstance(o, dict)
                    ]
                for intent in intents:
                    _append_capped(out, intent, user_input, per_resource_cap)
            except Exception:
                logger.debug("AD-1043: episodic episode mining skipped a row", exc_info=True)

    return out


__all__ = ["mine_representative_queries"]
