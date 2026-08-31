"""AD-1072: SearchCapabilitiesTool — discover what the ship can do.

The read-only discovery half of the AD-1072 keystone pair. An agent in the
AD-1065 conversational ``AgenticLoop`` already has ``run_python`` (AD-1066) and
``use_skill`` (AD-1068); this tool lets it *find* a capability before invoking
one, instead of guessing or confabulating a verb that does not exist (the
BF-651 / AD-1064 confabulation class).

It queries the AD-1001 "Ship's Locker" catalog (``list_capability_catalog``)
across three axes — **tools** (ToolRegistry), **skills** (CognitiveSkillCatalog),
and **mesh intents** (live IntentDescriptors) — keyword-ranks the matches, and
returns the top handful as ``{name, kind, description, held_by?}``.

Governance: strictly read-only — it only *describes* capabilities, it never
invokes or mutates anything. Offered to the loop when
``config.agentic_tools.tool_search_enabled``. The tool never raises out of
``invoke`` — every miss / failure becomes an honest-degrade ``ToolResult`` the
loop can reason over (AD-592).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params

logger = logging.getLogger(__name__)

# Cap the result list so a broad query can't flood the loop context.
_MAX_RESULTS = 10
# Ranking weights: a hit in the name is worth more than one in the description.
_NAME_WEIGHT = 3
_DESC_WEIGHT = 1
# Catalog axis key → the ``kind`` label surfaced to the agent.
_AXES: tuple[tuple[str, str], ...] = (
    ("tools", "tool"),
    ("skills", "skill"),
    ("mesh_intents", "intent"),
)
# AD-1179: the ``kind`` vocabulary, declared ONCE and derived from the ordered
# axis table above, so the schema enum and the narrowing gate cannot disagree.
#
# Derived from ``_AXES`` rather than from ``_SPECIFIC_KINDS`` deliberately:
# ``_SPECIFIC_KINDS`` used to be a set literal, and Python string hashing is
# randomised per process, so ``list(a_set)`` would emit a different enum order
# on every boot and the wire bytes an LLM receives would vary run to run. The
# ordered tuple is the schema's source; the frozenset below is membership only
# -- exactly the ``_AGENT_ACTIONS`` / ``_AGENT_ACTION_SET`` pattern.
_KINDS: tuple[str, ...] = tuple(label for _, label in _AXES) + ("all",)
_SPECIFIC_KINDS: frozenset[str] = frozenset(_KINDS) - {"all"}


def _tokens(text: str) -> set[str]:
    """Case-insensitive alphanumeric token set for keyword overlap."""
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


class SearchCapabilitiesTool:
    """AD-1072: search the ship's capability catalog (tools / skills / mesh
    intents) by keyword. Read-only discovery.

    Satisfies the AD-423a ``Tool`` protocol (duck-typed — no inheritance).
    Constructed with the runtime so it can call ``list_capability_catalog``.
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "search_capabilities"

    @property
    def name(self) -> str:
        return "Search Capabilities"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Search the ship's capabilities by keyword to discover what is "
            "available before you act. Returns the best-matching tools, skills, "
            "and mesh intents as {name, kind, description}. Use this when you are "
            "unsure whether a capability exists or what it is called, instead of "
            "guessing. Pass 'kind' to narrow the search to 'tool', 'skill', or "
            "'intent' (default 'all'). Read-only — it only describes capabilities."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for (e.g. 'word document').",
                },
                "kind": {
                    "type": "string",
                    "enum": list(_KINDS),
                    "description": "Which axis to search (default 'all').",
                },
            },
            "required": ["query"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        query = str((params or {}).get("query") or "").strip()
        if not query:
            return ToolResult(
                output={"results": [], "count": 0, "message": "query required"},
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        kind = str((params or {}).get("kind") or "all").strip().lower()
        axes = _AXES
        if kind in _SPECIFIC_KINDS:
            axes = tuple(a for a in _AXES if a[1] == kind)

        try:
            from probos.routers.tools import list_capability_catalog

            catalog = await list_capability_catalog(self._runtime)
            qtokens = _tokens(query)

            scored: list[tuple[int, str, dict[str, Any]]] = []
            for axis_key, kind_label in axes:
                for cand in catalog.get(axis_key, []) or []:
                    cand_name = str(cand.get("name") or cand.get("id") or "")
                    desc = str(cand.get("description") or "")
                    score = (
                        _NAME_WEIGHT * len(qtokens & _tokens(cand_name))
                        + _DESC_WEIGHT * len(qtokens & _tokens(desc))
                    )
                    if score <= 0:
                        continue
                    item: dict[str, Any] = {
                        "name": cand_name,
                        "kind": kind_label,
                        "description": desc,
                    }
                    # held_by exists on tools / skills only (mesh intents are
                    # ship-served → no per-agent holders).
                    if "held_by" in cand:
                        item["held_by"] = list(cand.get("held_by") or [])
                    scored.append((score, cand_name.lower(), item))

            scored.sort(key=lambda s: (-s[0], s[1]))
            results = [item for _score, _name, item in scored[:_MAX_RESULTS]]
            return ToolResult(
                output={"results": results, "count": len(results)},
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )
        except Exception as exc:
            logger.warning(
                "AD-1072: capability search failed for agent=%s query=%r: %s",
                (context or {}).get("agent_id", "?"), query, exc, exc_info=True,
            )
            return ToolResult(error=f"search_failed: {exc}")
