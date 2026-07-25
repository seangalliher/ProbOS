"""AD-1139: governed, read-only Oracle query tool for the AgenticLoop.

Gives a crew agent a way to consult the ship's **shared knowledge commons**
in the middle of a task. Until now Σ reached an agent only *passively* — the
Oracle result is injected as ``observation["_oracle_context"]`` during
``perceive``, and only for agents that resolve to ``RecallTier.ORACLE``. An
agent already working a task had no way to ask the ship a question.

**DD-1 — Σ tiers only; never Tier 1 (load-bearing).** The tier list is
hard-coded to :data:`SIGMA_TIERS`. ``episodic`` is never queried, is not
reachable through any parameter this tool accepts, and is filtered out of the
merged feed on the way back. That last filter is not redundant: BF-675 relabels
episode-derived Tier 5 rows as ``"episodic"`` precisely so ``_apply_access_policy``
can act on them, so a future path that re-enables episodes in the semantic layer
would otherwise leak one agent's sovereign shard (AD-397 / AD-607e) into
another's task context. Because it reads strictly fewer tiers than the passive
ORACLE-tier injection already does, this tool is a privilege *reduction*, not an
escalation.

**DD-2 — framing is inline (load-bearing).** ``AgenticLoop`` renders a tool
result as bare content; unlike the ``analyze`` / ``compose`` sub-task consumers
there is no outer "Cross-Tier Knowledge" wrapper to explain where the text came
from. Live testing showed agents find unframed Oracle content jarring — it just
appears. So the framing travels *with* the payload: a disposition preamble
modelled on ``_VISUAL_DISPOSITION`` (AD-1059) plus per-entry
``ProvenanceEnvelope.render()`` markers (AD-677) carrying source tier,
confidence and age.

**DD-3 — gap-regex safe.** Every string this module authors is checked against
``probos.cognitive.decomposer._CAPABILITY_GAP_RE`` in the tests. A tool result
that trips that regex would be mistaken for the LLM reporting a capability gap
and would spuriously trigger self-modification.

**DD-4 — bounded.** Result count, per-entry size and total characters are all
capped, well under ``SensoriumConfig.warning_chars``.

**DD-6 — read-only.** ``ToolPermission.READ``; no write path. Any Oracle
failure degrades to a framed empty result rather than an exception.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)

# DD-1: the Σ (commons) tiers, in Oracle tier order. ``episodic`` (Tier 1) is
# deliberately absent — it is the sovereign per-agent shard, not the commons.
# This is a module constant rather than config on purpose: it is a safety
# property of the tool, not a knob an operator should be able to widen.
SIGMA_TIERS: tuple[str, ...] = (
    "records",
    "semantic",
    "graph",
    "archive",
    "operational",
    "health",
)

# The one tier label that must never reach an agent through this tool.
SOVEREIGN_TIER = "episodic"

# DD-4 bounds. ``SensoriumConfig.warning_chars`` is 10_000, so a full result
# stays comfortably inside a single agent's context budget even when several
# lookups happen in one loop.
_MAX_RESULTS = 8
_MAX_ENTRY_CHARS = 1200
_MAX_OUTPUT_CHARS = 6000
# Room held back from the entry budget so the omission note below always fits.
_NOTE_RESERVE = 280
_MAX_QUERY_CHARS = 512
# Per-tier fan-out handed to the Oracle. 3 x 6 tiers = 18 candidates competing
# for the _MAX_RESULTS slots after merge/sort.
_K_PER_TIER = 3
# Only ``query`` and ``kind`` exist; anything else is rejected (DD-1 — there is
# no tier-list parameter to smuggle a sovereign tier through).
_ALLOWED_KEYS = frozenset({"query", "kind"})

_HEADER = "## Cross-Tier Knowledge (Ship's Records)"

# DD-2/DD-3: parenthetical, states the default behaviour plus the explicit
# exception, no imperative — the shape ``_VISUAL_DISPOSITION`` established for
# the visual feed (perception/working_memory.py). Wording avoids capability-gap
# phrasing so it never trips ``_CAPABILITY_GAP_RE``.
_ORACLE_DISPOSITION: str = (
    "(These entries come from the ship's shared knowledge stores, not from your "
    "own memory — treat them as reference material rather than as something you "
    "lived through. Each entry is prefixed with its source tier, a confidence "
    "score and an age, so weigh a low-confidence or STALE entry lightly. Cite an "
    "entry when you actually rely on it; otherwise do not narrate this lookup.)"
)

# BF-294 lesson: an empty result is stated explicitly rather than rendered as a
# bare header, so the agent reads "the commons held nothing" instead of
# inventing a reason for the silence.
_EMPTY_BODY: str = (
    "The ship's shared knowledge stores returned nothing for this query. Work "
    "from what you already hold, or query again with different wording."
)

_ENTRY_ELISION = " …[entry shortened]"


def _omission_note(omitted: int) -> str:
    """DD-4: report entries dropped for budget, so the elision stays visible."""
    noun = "entry" if omitted == 1 else "entries"
    return (
        f"({omitted} further {noun} elided to stay inside the context budget. "
        "Query again with narrower wording to reach them.)"
    )


def _cap_entry(rendered: str) -> str:
    """Bound one rendered envelope, preserving its provenance marker.

    The marker is the first ~50 characters of ``render()`` and the cap is far
    larger, so trimming the tail only ever removes content — the source tier,
    confidence and age an agent needs to weigh the entry always survive.
    """
    if len(rendered) <= _MAX_ENTRY_CHARS:
        return rendered
    keep = _MAX_ENTRY_CHARS - len(_ENTRY_ELISION)
    return rendered[:keep] + _ENTRY_ELISION


def _render(envelopes: list[Any]) -> tuple[str, int]:
    """Render the framed, provenance-tagged payload. Returns (text, rendered).

    The header and disposition are emitted unconditionally — DD-2 requires the
    framing to be present even when the commons returned nothing, because the
    empty case is exactly where an unexplained result is most confusing.
    """
    head = f"{_HEADER}\n\n{_ORACLE_DISPOSITION}\n"
    if not envelopes:
        return f"{head}\n{_EMPTY_BODY}\n", 0

    selected = envelopes[:_MAX_RESULTS]
    entry_budget = _MAX_OUTPUT_CHARS - _NOTE_RESERVE
    out = head
    rendered = 0
    for envelope in selected:
        candidate = f"{out}\n{_cap_entry(envelope.render())}\n"
        # The first entry is always admitted: a header with no entries and no
        # explanation reads as unexplained silence, which is the confabulation
        # shape this framing exists to prevent. ``_cap_entry`` bounds it, and
        # the caller's final bound is the backstop.
        if rendered and len(candidate) > entry_budget:
            break
        out = candidate
        rendered += 1

    omitted = len(envelopes) - rendered
    if omitted > 0:
        out = f"{out}\n{_omission_note(omitted)}\n"
    return out, rendered


class OracleQueryTool:
    """Read-only cross-tier query over the ship's shared knowledge commons.

    Satisfies the AD-423a ``Tool`` protocol structurally — no inheritance.
    Constructed with the ``OracleService`` (constructor injection) so the tool
    depends on the query surface rather than reaching through the runtime.
    """

    def __init__(self, *, oracle: Any) -> None:
        self._oracle = oracle

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "oracle_query"

    @property
    def name(self) -> str:
        return "Oracle Query"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return (
            "Consult the ship's shared knowledge commons for material relevant "
            "to the task you are working: ship's records, the semantic index, "
            "the knowledge graph, the archive, operational state and health "
            "telemetry. Read-only. Every entry comes back tagged with its "
            "source tier, a confidence score and an age. Each agent's personal "
            "episodic memory is sovereign and private, so this tool reads only "
            "the shared commons. Pass 'kind' to narrow to one tier."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": _MAX_QUERY_CHARS,
                    "description": (
                        "What to look up in the shared knowledge commons."
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": [*SIGMA_TIERS, "all"],
                    "default": "all",
                    "description": (
                        "Narrow the search to one shared tier (default 'all')."
                    ),
                },
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "description": (
                "A framed block: a disposition preamble followed by each entry "
                "prefixed with its provenance marker."
            ),
        }

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        raw = params if type(params) is dict else {}
        actor = ""
        if type(context) is dict and type(context.get("agent_id")) is str:
            actor = context["agent_id"]

        if any(type(key) is not str or key not in _ALLOWED_KEYS for key in raw):
            return self._invalid("parameter", started)

        query = raw.get("query")
        query = query.strip() if type(query) is str else ""
        if not query or len(query) > _MAX_QUERY_CHARS:
            return self._invalid("query", started)

        tiers = self._resolve_tiers(raw.get("kind"))
        if tiers is None:
            return self._invalid("kind", started)

        envelopes = await self._commons_envelopes(query, tiers, actor)
        text, rendered = _render(envelopes)
        return ToolResult(
            output=self._bounded(text),
            duration_ms=(time.monotonic() - started) * 1000.0,
            metadata={
                "tiers": list(tiers),
                "returned_count": rendered,
                "candidate_count": len(envelopes),
            },
        )

    # ── Internals ─────────────────────────────────────────────────
    @staticmethod
    def _resolve_tiers(raw_kind: Any) -> list[str] | None:
        """Map the optional ``kind`` parameter onto a Σ-only tier list.

        DD-1: the result is always a subset of :data:`SIGMA_TIERS`. A ``kind``
        the tool does not recognise — including ``"episodic"`` — is rejected
        rather than silently widened, so the sovereign tier has no path in.
        """
        if raw_kind is None:
            return list(SIGMA_TIERS)
        if type(raw_kind) is not str:
            return None
        kind = raw_kind.strip().lower()
        if kind in ("", "all"):
            return list(SIGMA_TIERS)
        if kind in SIGMA_TIERS:
            return [kind]
        return None

    async def _commons_envelopes(
        self,
        query: str,
        tiers: list[str],
        actor: str,
    ) -> list[Any]:
        """Query the Oracle and keep only commons-tier envelopes.

        DD-6: the Oracle is consulted best-effort. ``query_with_provenance``
        already absorbs its own failures, and this method absorbs anything the
        import or the projection raises, so the caller always receives a list
        and the framed empty result carries the honest outcome.

        ``agent_id`` is deliberately not forwarded: it scopes Tier 1 recall
        only, and Tier 1 is never queried here (Minimal Authority).
        """
        try:
            from probos.cognitive.provenance import query_with_provenance

            envelopes = await query_with_provenance(
                self._oracle,
                query_text=query,
                k_per_tier=_K_PER_TIER,
                tiers=tiers,
            )
        except Exception:
            logger.warning(
                "AD-1139: Oracle consult failed for agent %s; returning the "
                "framed empty result so the loop keeps its own reasoning",
                actor or "<unknown>",
                exc_info=True,
            )
            return []

        commons: list[Any] = []
        dropped = 0
        for envelope in envelopes:
            tier = getattr(getattr(envelope, "tag", None), "source_tier", "")
            if tier in SIGMA_TIERS:
                commons.append(envelope)
                continue
            dropped += 1
        if dropped:
            logger.warning(
                "AD-1139: dropped %d non-commons result(s) for agent %s; the "
                "sovereign episodic shard stays out of shared task context",
                dropped,
                actor or "<unknown>",
            )
        return commons

    @staticmethod
    def _bounded(text: str) -> str:
        """DD-4: final hard cap, reusing the AD-1148 loop bound.

        The renderer already fits inside the budget, so this is a defence-in-
        depth no-op on the normal path. A failed import degrades to a plain
        slice rather than shipping an unbounded result.
        """
        try:
            from probos.cognitive.swe_harness.agentic_loop import (
                truncate_tool_output,
            )

            return truncate_tool_output(text, max_chars=_MAX_OUTPUT_CHARS)
        except Exception:
            logger.warning(
                "AD-1139: shared tool-result bound was unreachable; applying "
                "the local character cap so the result stays inside budget",
                exc_info=True,
            )
            return text[:_MAX_OUTPUT_CHARS]

    @staticmethod
    def _invalid(code: str, started: float) -> ToolResult:
        return ToolResult(
            error=f"oracle_query_invalid:{code}",
            duration_ms=(time.monotonic() - started) * 1000.0,
        )
