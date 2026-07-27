"""AD-856: AgenticLoop bridge plumbing for dispatched work items.

Two pieces of thin plumbing that let the existing ``AgenticLoop`` (AD-545)
execute a dispatched work item:

1. ``DispatchToolExecutor`` — a thin ``ToolExecutor`` subclass whose ``invoke``
   captures the denied ``tool_id`` whenever ``check_and_invoke`` raises
   ``ToolPermissionDenied`` (so the denial can be surfaced to AD-855's
   capability-gap driver after the loop finishes), then re-raises so the
   loop's existing is-error handling is unchanged.

2. Mesh-intent -> Tool adapters — ``web_search`` / ``read_page`` /
   ``http_fetch`` exist only as bus intents, not registered Tools. The thin
   ``_MeshIntentTool`` wrapper broadcasts the corresponding intent and returns
   the first result as a ``ToolResult`` so ``check_and_invoke`` can find them.
   This is plumbing for the loop, not net-new capability.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from probos.integrations.mcp_bridge.risk import (
    McpToolRisk,
    resolve_tool_risk,
)
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.mesh.intent import IntentBus
    from probos.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_ARTIFACT_REF_KEYS = frozenset(
    {
        "artifact_id",
        "content_hash",
        "thread_id",
        "name",
        "mime",
        "size_bytes",
        "version",
    }
)
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ARTIFACT_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARTIFACT_CANDIDATES_PER_RESULT = 64
_MAX_ARTIFACT_REFS = 32
_MAX_ARTIFACT_SIZE_BYTES = 26_214_400
_MAX_ARTIFACT_VERSION = 2_147_483_647
_AGENTIC_EXTRA_CONTEXT_KEYS = frozenset(
    {
        "agent_id",
        "department",
        "rank",
        "thread_id",
        "_delegation_depth",
        "_crew_session_id",
        "_crew_work_item_id",
    }
)
_AGENTIC_RANKS = frozenset(
    {"ensign", "lieutenant", "commander", "senior_officer"}
)
# AD-1129 / AD-1139 / AD-1140: tools whose availability is decided ONLY by the
# department + rank gate on their registration. A raw Captain grant is dropped
# from ``granted_ids`` for these so it cannot route around
# ``ToolRegistry.resolve_permission``'s scope layer, which returns NONE for an
# out-of-scope department *before* grants are ever considered. Each id is
# re-offered below through an explicit ``check_permission`` call.
_GATED_TOOL_IDS = frozenset(
    {"event_log_query", "oracle_query", "publish_finding"}
)

# AD-1153 / DD-1: the ONLY browser actions the agentic loop may invoke.
#
# v1 is READ-ONLY, and the reason is a property of the tier ladder rather than a
# preference. ``classify_action`` (tools/browser/actions.py) puts ``state`` /
# ``extract_text`` / ``back`` / ``forward`` / ``wait`` at tier 1 and ``goto``
# unconditionally at tier 2; tier-3 escalation is reachable ONLY through
# ``click`` / ``type`` / ``drag`` / ``mouse_button`` and the always-tier-3 verbs.
# So no action in this set can ever reach the tier-3 confirmation gate — which
# matters, because that gate returns ``ToolResult(output={"intervention_required":
# True, ...})`` with ``error=None``, i.e. a SUCCESS-shaped no-op that an
# unattended caller reads as completion. This AD ships the subset for which that
# gate is never consulted; ``click`` / ``type`` / ``scroll`` wait on AD-1154.
#
# Enforced at ``DispatchToolExecutor`` and not inside ``BrowserTool`` so the
# AD-745 DM dispatch path stays byte-identical, and so this is a fail-safe
# partition in exactly the shape of ``PARALLEL_SAFE_TOOL_IDS`` (AD-1147/DD-1):
# membership is the ONLY way through, so an action that is new, renamed, absent
# or otherwise unrecognised is refused by default. Module constant rather than a
# config field on purpose — it is a safety property of the loop, not a tuning
# knob an operator should be able to widen.
_BROWSER_LOOP_ACTIONS: frozenset[str] = frozenset(
    {"goto", "state", "extract_text", "back", "forward", "wait"}
)

# AD-1153 / DD-3: browser-specific output bounds. ``tool_result_max_chars``
# (AD-1148) ships at 0, so it is a no-op on shipped defaults while a single
# ``extract_text`` on a long page returns ``inner_text("body")`` verbatim. These
# are the INNER caps that hold regardless. 8000 sits between AD-1148's
# head+tail (4000 + 2000) and ``TOOL_TRACE_OUTPUT_MAX_CHARS`` (8192), so a
# bounded page read survives the AD-1151 durable trace intact.
_BROWSER_TEXT_MAX_CHARS = 8000
_BROWSER_MAX_ELEMENTS = 100

# AD-1153 / DD-4: framing travels INLINE, because ``AgenticLoop`` renders tool
# results as bare content with no consumer-side wrapper. Same parenthetical
# shape as ``_ORACLE_DISPOSITION`` (AD-1139) and ``_VISUAL_DISPOSITION``
# (AD-1059). Every string below is checked against the real imported
# ``_CAPABILITY_GAP_RE`` by tests/test_ad1153_browser_agentic_loop.py — note
# that ``lack`` is a BARE substring in that pattern, so "black", "slack" and
# "blackhole" all trip it. Any reword must be re-run against the real regex.
_BROWSER_DISPOSITION: str = (
    "(This is live page content read from the open browser session. Treat it "
    "as an observation of the page at this moment, not as a durable fact. Cite "
    "the URL when you build on it.)"
)
_BROWSER_READ_ONLY_REFUSAL: str = (
    "The browser is offered in read-only mode for this session. Available "
    "actions: goto, state, extract_text, back, forward, wait. To act on the "
    "page itself, hand that step to the Captain."
)
_BROWSER_TEXT_ELISION: str = (
    "\n\n... [truncated: {omitted} characters elided from this page read. "
    "Re-run extract_text with a narrower selector to retrieve the elided "
    "region.] ...\n\n"
)
_BROWSER_ELEMENTS_ELISION: str = (
    "[truncated: {omitted} further page elements elided. Narrow the page or "
    "re-run state after navigating.]"
)
# AD-1153 / DD-7: egress is warned about, not forced. ``domain_allowlist``
# defaults to None = allow-all, and requiring a non-empty allowlist would make
# the feature useless for the research tasks that motivate it. Log-and-degrade:
# make the existing default visible at the moment it starts mattering.
_BROWSER_EGRESS_WARNING: str = (
    "AD-1153: the loop browser offer is enabled while domain_allowlist is "
    "None; the agent may navigate to any host absent from domain_denylist. "
    "Set browser_tool.domain_allowlist to bound egress."
)


def _bound_browser_output(output: Any) -> Any:
    """AD-1153 / DD-3: cap a browser result's text + element list, visibly.

    Truncation is marked rather than silent (AD-1148/DD-3) so the agent re-queries
    with a narrower selector instead of reasoning on an unannounced prefix. The
    disposition (DD-4) is attached here too, so the same value reaches both the
    loop transcript and the AD-1151 durable trace.

    Returns ``output`` unchanged when it is not a dict. Under-limit ``text`` /
    ``elements`` values are carried through untouched.
    """
    if type(output) is not dict:
        return output
    bounded = dict(output)

    text = bounded.get("text")
    if type(text) is str and len(text) > _BROWSER_TEXT_MAX_CHARS:
        omitted = len(text) - _BROWSER_TEXT_MAX_CHARS
        bounded["text"] = text[:_BROWSER_TEXT_MAX_CHARS] + _BROWSER_TEXT_ELISION.format(
            omitted=omitted
        )

    elements = bounded.get("elements")
    if type(elements) is list and len(elements) > _BROWSER_MAX_ELEMENTS:
        omitted = len(elements) - _BROWSER_MAX_ELEMENTS
        bounded["elements"] = [
            *elements[:_BROWSER_MAX_ELEMENTS],
            _BROWSER_ELEMENTS_ELISION.format(omitted=omitted),
        ]

    bounded["disposition"] = _BROWSER_DISPOSITION
    return bounded


def _resolve_agentic_identity(
    *,
    runtime: Any,
    tool_registry: Any,
    agent_id: str,
    fallback_department: str,
    fallback_rank: str,
) -> tuple[str, str]:
    try:
        agent_registry = getattr(runtime, "registry", None)
        ontology = getattr(runtime, "ontology", None)
        trust_network = getattr(runtime, "trust_network", None)
        services = (agent_registry, ontology, trust_network)

        if all(service is None for service in services):
            event_log_registered = (
                tool_registry is not None
                and tool_registry.get("event_log_query") is not None
            )
            if event_log_registered:
                raise ValueError("governed tool requires authoritative identity")
            return fallback_department, fallback_rank

        if any(service is None for service in services):
            raise ValueError("partial authoritative identity")

        agent = agent_registry.get(agent_id)
        registered_id = getattr(agent, "id", None)
        agent_type = getattr(agent, "agent_type", None)
        if (
            type(agent_id) is not str
            or type(registered_id) is not str
            or registered_id != agent_id
            or type(agent_type) is not str
            or not agent_type
        ):
            raise ValueError("registered identity mismatch")

        resolved_department = ontology.get_agent_department(agent_type)
        if resolved_department is None or resolved_department == "":
            from probos.cognitive.standing_orders import get_department

            resolved_department = get_department(agent_type)
        if type(resolved_department) is not str or not resolved_department:
            raise ValueError("department unresolved")

        from probos.crew_profile import Rank

        resolved_rank = Rank.from_trust(
            trust_network.get_score(registered_id)
        ).value
        if type(resolved_rank) is not str or resolved_rank not in _AGENTIC_RANKS:
            raise ValueError("rank unresolved")
        return resolved_department, resolved_rank
    except Exception:
        raise RuntimeError("agentic_identity_unresolved") from None


def _extract_artifact_refs(
    observations: list[tuple[Any, Any]],
    *,
    thread_id: str,
) -> tuple[list[dict[str, Any]], int]:
    refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    ignored = 0
    for tool_id, result in observations:
        if tool_id != "run_python":
            continue
        if type(result) is not ToolResult or result.error is not None:
            continue
        output = result.output
        if type(output) is not dict:
            ignored += 1
            continue
        candidates = output.get("artifact_details")
        if type(candidates) is not list:
            ignored += 1
            continue
        if len(candidates) > _MAX_ARTIFACT_CANDIDATES_PER_RESULT:
            ignored += len(candidates) - _MAX_ARTIFACT_CANDIDATES_PER_RESULT
        for candidate in candidates[:_MAX_ARTIFACT_CANDIDATES_PER_RESULT]:
            if type(candidate) is not dict:
                ignored += 1
                continue
            if (
                len(candidate) != len(_ARTIFACT_REF_KEYS)
                or any(type(key) is not str for key in candidate)
                or set(candidate) != _ARTIFACT_REF_KEYS
            ):
                ignored += 1
                continue
            artifact_id = candidate["artifact_id"]
            content_hash = candidate["content_hash"]
            candidate_thread_id = candidate["thread_id"]
            name = candidate["name"]
            mime = candidate["mime"]
            size_bytes = candidate["size_bytes"]
            version = candidate["version"]
            valid = (
                type(artifact_id) is str
                and _ARTIFACT_ID_RE.fullmatch(artifact_id) is not None
                and type(content_hash) is str
                and _ARTIFACT_SHA_RE.fullmatch(content_hash) is not None
                and type(candidate_thread_id) is str
                and bool(candidate_thread_id)
                and candidate_thread_id == thread_id
                and type(name) is str
                and 1 <= len(name) <= 255
                and "/" not in name
                and "\\" not in name
                and "\x00" not in name
                and type(mime) is str
                and 1 <= len(mime) <= 255
                and type(size_bytes) is int
                and 1 <= size_bytes <= _MAX_ARTIFACT_SIZE_BYTES
                and type(version) is int
                and 1 <= version <= _MAX_ARTIFACT_VERSION
            )
            if not valid or artifact_id in seen_ids or len(refs) >= _MAX_ARTIFACT_REFS:
                ignored += 1
                continue
            seen_ids.add(artifact_id)
            refs.append(
                {
                    "artifact_id": artifact_id,
                    "content_hash": content_hash,
                    "thread_id": candidate_thread_id,
                    "name": name,
                    "mime": mime,
                    "size_bytes": size_bytes,
                    "version": version,
                }
            )
    return refs, ignored


class DispatchToolExecutor(ToolExecutor):
    """ToolExecutor that records permission-denied tool ids (AD-856).

    ``AgenticLoop.run`` wraps each executor call in ``try/except Exception`` and
    turns the raise into an is-error tool-result before continuing — so the
    caller never sees a denial in ``AgenticResult``. This subclass captures the
    denied ``tool_id`` into the public ``denied_tools`` list, then re-raises so
    the loop's existing handling is preserved.

    AD-1153 adds an OPT-IN browser action restriction. It is unarmed by default,
    so an executor that never calls :meth:`restrict_browser_actions` behaves
    byte-identically to AD-856.
    """

    def __init__(self, *, registry: Any) -> None:
        super().__init__(registry=registry)
        self.denied_tools: list[str] = []
        # AD-1153: None = unarmed = today's behaviour. Set only by
        # ``restrict_browser_actions``.
        self._browser_actions: frozenset[str] | None = None

    def restrict_browser_actions(self, actions: frozenset[str]) -> None:
        """AD-1153 / DD-1: confine ``browser`` calls to ``actions``.

        Arms the read-only guard in :meth:`invoke`. Any ``browser`` call whose
        ``action`` param falls outside ``actions`` is refused with an *error*
        ``ToolResult`` and never reaches the tool, so no session is created.

        Tradeoff worth naming: a keyword-only constructor parameter would be more
        DIP-idiomatic than a setter. This executor is constructed before the
        offer blocks resolve ``granted_ids``, and the restriction must arm only
        when the tool arrived through the AD-1153 offer rather than through a
        Captain grant (DD-1 — narrowing a grant would invert Layer 4's grant-up
        semantics). Moving construction past that point is a larger refactor
        than this AD warrants, so the arming is a post-construction call.
        """
        self._browser_actions = actions

    def _refuse_browser_action(self, agent_id: str, params: Any) -> ToolResult | None:
        """Return a refusal when ``params`` names a non-allowlisted action.

        ``None`` means "admitted". ``params`` and its ``action`` are LLM-produced
        JSON, so ``action`` may be absent, ``None``, an int or a dict — every
        non-``str`` is refused through the same framed path rather than raising.
        """
        allowed = self._browser_actions
        if allowed is None:
            return None
        action = params.get("action") if type(params) is dict else None
        if type(action) is str and action in allowed:
            return None
        logger.info(
            "AD-1153: refused browser action %.64r for agent %s; the agentic "
            "loop offers the read-only set %s and the tool was not entered",
            action,
            agent_id[:12],
            sorted(allowed),
        )
        return ToolResult(error=_BROWSER_READ_ONLY_REFUSAL)

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> ToolResult:
        # AD-1153: armed only for ``browser``, and only when the offer block
        # called ``restrict_browser_actions``. Unarmed ⇒ this whole branch is
        # skipped and the AD-856 path below runs verbatim.
        restricted = self._browser_actions is not None and tool_id == "browser"
        if restricted:
            refusal = self._refuse_browser_action(agent_id, params)
            if refusal is not None:
                return refusal
        try:
            result = await super().invoke(agent_id, tool_id, params, **kwargs)
        except ToolPermissionDenied as exc:
            denied = getattr(exc, "tool_id", tool_id)
            self.denied_tools.append(denied)
            logger.info(
                "AD-856: tool %s denied for agent %s during dispatch; recorded "
                "for capability-gap surfacing",
                denied,
                agent_id[:12],
            )
            raise
        if restricted and result.error is None:
            # AD-1153 / DD-3: bound + frame AFTER ``super().invoke`` so the
            # value returned here is what ``ToolCallResult.from_tool_result``
            # renders into the transcript AND what ``_persist_tool_trace``
            # records. The AD-448 post-hooks fire inside ``super().invoke`` and
            # therefore see the raw output; none of them consumes ``browser``.
            return replace(result, output=_bound_browser_output(result.output))
        return result


class _MeshIntentTool:
    """Thin Tool adapter that fulfils a mesh intent via the bus (AD-856)."""

    def __init__(
        self,
        *,
        intent_bus: "IntentBus",
        tool_id: str,
        intent_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        self._intent_bus = intent_bus
        self._tool_id = tool_id
        self._intent_name = intent_name
        self._name = name
        self._description = description
        self._input_schema = input_schema

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        results = await self._intent_bus.broadcast(
            IntentMessage(intent=self._intent_name, params=dict(params or {}))
        )
        if not results:
            return ToolResult(
                error=f"No agent fulfilled mesh intent '{self._intent_name}'"
            )
        for res in results:
            if res.success:
                return ToolResult(output=res.result)
        first = results[0]
        return ToolResult(
            error=first.error or f"Mesh intent '{self._intent_name}' failed",
            output=first.result,
        )


def _coerce_risk(value: str) -> McpToolRisk:
    """AD-1019c DD-4: defensively coerce a free-form ``default_risk`` str.

    AD-1019b validates ``default_risk`` only at the create/update boundary, so a
    legacy/corrupt value can reach the invoke path. An unknown value **fails
    closed**: it logs a warning and falls back to ``CONSENSUS`` (the most-gated
    tier) — a risk classifier that cannot determine the risk must assume the
    maximum (the Safety Budget axiom), never the minimum. The invoke wrapper is
    additionally deny-safe (returns an error ``ToolResult``, never crashes). A
    per-tool override still wins via :func:`resolve_tool_risk`. Never raises.
    """
    try:
        return McpToolRisk(value)
    except ValueError:
        logger.warning(
            "AD-1019c: unknown MCP risk tier %r; failing closed to CONSENSUS",
            value,
        )
        return McpToolRisk.CONSENSUS


# The context key carrying an explicit operator confirmation token for the
# CONFIRM tier. The HXI affordance that supplies it is AD-1019d; absent the
# token a CONFIRM-tier invoke is blocked (no MCPBridge.invoke).
MCP_CONFIRM_TOKEN_KEY = "mcp_confirmation_token"


class _McpTool:
    """Thin Tool adapter that invokes one MCP tool through the tier gate (AD-1019c).

    Mirrors :class:`_MeshIntentTool`, but instead of broadcasting a mesh intent
    it routes the call by the tool's effective :class:`McpToolRisk` ("keys"):

    - ``OPEN``      → direct ``MCPBridge.invoke`` (free once authorized).
    - ``CONFIRM``   → blocked unless ``context[MCP_CONFIRM_TOKEN_KEY]`` is set;
      absent → ``requires_confirmation`` outcome, **no invoke**.
    - ``CONSENSUS`` → routed through ``consensus_invoke`` (the runtime's
      ``submit_mcp_invoke_with_consensus``), which commits ``MCPBridge.invoke``
      **only on APPROVED** (the era-4 guard lives in the runtime).

    All deps are narrow callables/values injected by the workbench so this
    adapter never imports the workbench (no cycle). The invoke path is wrapped
    deny-safe: any unexpected error returns an error ``ToolResult`` rather than
    crashing the agentic loop.
    """

    def __init__(
        self,
        *,
        bridge: Any,
        server_url: str,
        server_name: str,
        server_id: str,
        tool_name: str,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        server_default_risk: str,
        risk_store: Any | None,
        consensus_invoke: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]],
        authorize: Callable[[str], bool],
        episode_writer: Callable[..., Awaitable[None]] | None = None,
        touch: Callable[[], None] | None = None,
    ) -> None:
        self._bridge = bridge
        self._server_url = server_url
        self._server_name = server_name
        self._server_id = server_id
        self._tool_name = tool_name
        self._name = name
        self._description = description
        self._input_schema = input_schema
        self._server_default_risk = server_default_risk
        self._risk_store = risk_store
        self._consensus_invoke = consensus_invoke
        self._authorize = authorize
        self._episode_writer = episode_writer
        self._touch = touch

    @property
    def tool_id(self) -> str:
        return f"mcp:{self._server_name}:{self._tool_name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.MCP_SERVER

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    def effective_risk(self) -> McpToolRisk:
        """Resolve the effective risk tier at invoke time (DD-4).

        Defensively coerces the server's free-form ``default_risk`` (logs +
        fails closed to CONSENSUS on an unknown value), then lets a per-tool
        override win via :func:`resolve_tool_risk`.
        """
        server_default = _coerce_risk(self._server_default_risk)
        override: McpToolRisk | None = None
        if self._risk_store is not None:
            override = self._risk_store.get_risk_sync(self._server_id, self._tool_name)
        return resolve_tool_risk(server_default, override)

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        agent_id = str((context or {}).get("agent_id", ""))
        if self._touch is not None:
            self._touch()
        # Defense in depth: the adapter is globally registered, so re-verify the
        # invoking agent's AD-1019b authorization for THIS tool (the dispatch
        # scoping is the primary gate; this is the secondary, deny-safe one).
        if not self._authorize(agent_id):
            logger.warning(
                "AD-1019c: agent %s not authorized for MCP tool %s; denying",
                agent_id[:12] or "?",
                self.tool_id,
            )
            return ToolResult(error=f"agent not authorized for MCP tool {self.tool_id}")

        args = dict(params or {})
        try:
            effective = self.effective_risk()
            if effective is McpToolRisk.OPEN:
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("open", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "open"})

            if effective is McpToolRisk.CONFIRM:
                token = (context or {}).get(MCP_CONFIRM_TOKEN_KEY)
                if not token:
                    return ToolResult(
                        error="requires_confirmation",
                        metadata={
                            "mcp_tier": "confirm",
                            "outcome": "requires_confirmation",
                        },
                    )
                out = await self._bridge.invoke(self._server_url, self._tool_name, args)
                await self._record_episode("confirm", True, agent_id)
                return ToolResult(output=out, metadata={"mcp_tier": "confirm"})

            # CONSENSUS: the runtime broadcasts + commits on APPROVED only and
            # stores the episode itself (no double-store here).
            consensus_result = await self._consensus_invoke(
                self._server_url, self._tool_name, args
            )
            if bool(consensus_result.get("committed")):
                return ToolResult(
                    output=consensus_result.get("invoke_result"),
                    metadata={"mcp_tier": "consensus", "outcome": "approved"},
                )
            outcome = ""
            cons = consensus_result.get("consensus")
            if cons is not None:
                outcome = getattr(getattr(cons, "outcome", None), "value", "")
            return ToolResult(
                error="consensus_blocked",
                metadata={"mcp_tier": "consensus", "outcome": outcome},
            )
        except Exception as exc:
            logger.warning(
                "AD-1019c: MCP tool %s invoke failed: %s",
                self.tool_id,
                exc,
                exc_info=True,
            )
            return ToolResult(error=str(exc))

    async def _record_episode(
        self, tier: str, success: bool, agent_id: str
    ) -> None:
        """DD-5 episode for the OPEN/CONFIRM tiers (consensus records in runtime)."""
        if self._episode_writer is None:
            return
        try:
            await self._episode_writer(
                server_url=self._server_url,
                tool=self._tool_name,
                tier=tier,
                success=success,
                agent_id=agent_id,
            )
        except Exception:
            logger.debug(
                "AD-1019c: episode write failed for %s", self.tool_id, exc_info=True
            )


# (tool_id, intent_name, display_name, description, input_schema)
_MESH_TOOL_SPECS: list[tuple[str, str, str, str, dict[str, Any]]] = [
    (
        "web_search",
        "web_search",
        "Web Search",
        "Search the web for information matching a query.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    (
        "read_page",
        "read_page",
        "Read Page",
        "Fetch and read the contents of a web page by URL.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
    (
        "http_fetch",
        "http_fetch",
        "HTTP Fetch",
        "Perform an HTTP request against a URL and return the response.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ),
]


def register_mesh_intent_tools(
    registry: "ToolRegistry",
    intent_bus: "IntentBus",
    provider: str = "AD-856",
) -> list[str]:
    """Register the mesh-intent Tool adapters idempotently (AD-856).

    Each adapter is registered with empty ``default_permissions`` so the
    registry's Layer-3 ship-wide default grants READ to all ranks. Already
    registered tool ids are skipped (idempotent). Returns the list of tool ids
    that are available after registration.

    ``provider`` tags the catalog entry (AD-909). The per-dispatch caller keeps
    the default ``"AD-856"``; the AD-909 startup path (``_wire_mesh_intent_tools``
    in ``startup/finalize.py``) passes ``"mesh"`` so the three universal
    read-intents surface in ``GET /api/tools`` and the AD-885 capability lens
    with a stable, meaningful provider. Idempotent across both callers: whichever
    runs first registers the tool and the other skips it — so in production the
    startup-path ``"mesh"`` tag wins, since ``finalize_startup`` runs before any
    agentic dispatch.
    """
    available: list[str] = []
    for tool_id, intent_name, name, description, input_schema in _MESH_TOOL_SPECS:
        available.append(tool_id)
        if registry.get(tool_id) is not None:
            continue
        tool = _MeshIntentTool(
            intent_bus=intent_bus,
            tool_id=tool_id,
            intent_name=intent_name,
            name=name,
            description=description,
            input_schema=input_schema,
        )
        registry.register(tool, provider=provider, tags=[tool_id, provider])
    return available


@dataclass
class WorkItemAgenticOutcome:
    """AD-859a: structured result of a single dispatched agentic work-item run.

    Replaces the bare ``str | None`` the AD-856 inline loop returned so BOTH the
    AD-839 dispatch handler AND the crew fan-out executor (AD-859) can collect a
    result with provenance. ``tool_trace_ref`` is a content-addressable SHA ref
    to the serialized ``AgenticResult.tool_calls`` in ``AttachmentStore`` (AD-731
    rule: refs on the bus, bytes in the store), or ``None`` when no store is
    wired (honest-degrade).
    """

    final_text: str = ""
    stopped_reason: str = ""
    denied_tools: list[str] = field(default_factory=list)
    tool_trace_ref: str | None = None
    total_tokens: int = 0
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    # BF-680: provenance of ``total_tokens`` — ``measured`` / ``estimated`` /
    # ``mixed`` (see ``agentic_loop.TOKEN_SOURCE_*``). ``total_tokens`` becomes
    # ``crew_execution.tokens_used``, whose 14-key record is frozen and cannot
    # carry a companion field, so the provenance rides HERE instead: a caller
    # holding the outcome can always tell whether the number it is about to
    # persist was measured or estimated. Appended last and defaulted, so every
    # existing construction site is untouched.
    #
    # The default is spelled out rather than importing
    # ``agentic_loop.TOKEN_SOURCE_MEASURED``: this module imports that one
    # lazily inside ``run()``, and a class-body default needs the value at
    # import time. Same duplication convention as ``AGENTIC_MAX_ITERATIONS`` <->
    # ``NativeSWEHarnessConfig``; a drift guard in tests/test_bf680_token_usage_
    # fallback.py keeps the two in step.
    token_source: str = "measured"


class WorkItemAgenticExecutor:
    """AD-859a: reusable executor that runs a dispatched work item through the
    AgenticLoop (AD-545) and returns a structured :class:`WorkItemAgenticOutcome`.

    Extracted from ``CognitiveAgent._run_agentic_dispatch`` (AD-856) so the loop
    wiring (build :class:`DispatchToolExecutor`, register mesh-intent tools,
    gather grants into tool defs, construct the loop, await it) lives in one
    place callable by both the AD-839 handler and the crew executor.

    Capability-gap surfacing for ``denied_tools`` stays the CALLER's
    responsibility — the executor only records which tools were denied; it does
    not call the gap driver.
    """

    def __init__(self, *, llm_client: Any) -> None:
        self._llm = llm_client
        # AD-1153 / DD-7: one-shot egress warning, per executor INSTANCE rather
        # than per module — a module-level bool is process-global and would not
        # reset between tests, making the once-only behaviour unassertable.
        self._browser_egress_warned: bool = False

    def _warn_once_on_open_browser_egress(self, runtime: Any) -> None:
        """AD-1153 / DD-7: WARN once when the offer lands with no allowlist.

        Fires at the first ACTUAL offer, so an agent whose rank denies the tool
        does not produce a warning about a capability it never received. Reads
        the config defensively — a synthetic runtime without one degrades to
        no warning rather than failing the dispatch.
        """
        if self._browser_egress_warned:
            return
        browser_cfg = getattr(getattr(runtime, "config", None), "browser_tool", None)
        if getattr(browser_cfg, "domain_allowlist", None) is not None:
            return
        self._browser_egress_warned = True
        logger.warning(_BROWSER_EGRESS_WARNING)

    async def run(
        self,
        *,
        agent_id: str,
        instructions: str,
        task_text: str,
        runtime: Any,
        # Deprecated compatibility fallback for event-neutral synthetic runtimes.
        department: str = "",
        rank: str = "ensign",
        thread_id: str = "",
        max_iterations: int | None = None,
        tier: str | None = None,
        extra_context: dict | None = None,
        # AD-1142: crew-child working-context compaction + spend ceiling.
        # PURE PASS-THROUGH — this method also serves the AD-839 conversational
        # path and the AD-1072 delegation path, so it deliberately reads NO
        # config for these. The crew executor owns the policy and resolves
        # them; every other caller leaves them None and gets today's loop.
        compactor: Any = None,
        compaction_threshold: int | None = None,
        token_budget: int | None = None,
    ) -> WorkItemAgenticOutcome:
        """Run one agentic work-item session and return its structured outcome.

        Reads the tool permission store, tool registry and intent bus off the
        ``runtime``. Mirrors the AD-856 inline loop exactly (zero behavior
        change on the AD-839 path), then additionally persists the tool trace to
        ``runtime.attachment_store`` and returns a :class:`WorkItemAgenticOutcome`.
        """
        from probos.cognitive.swe_harness.agentic_loop import (
            TOKEN_SOURCE_MEASURED,
            AgenticLoop,
            resolve_parallel_tool_settings,
            resolve_tool_result_bounds,
        )
        from probos.cognitive.swe_harness.tool_call import (
            tool_registration_to_llm_definition,
        )

        registry = getattr(runtime, "tool_registry", None)
        perm_store = getattr(runtime, "tool_permission_store", None)
        intent_bus = getattr(runtime, "intent_bus", None)

        if extra_context is None:
            _context: dict[str, Any] = {}
        elif (
            type(extra_context) is not dict
            or len(extra_context) > len(_AGENTIC_EXTRA_CONTEXT_KEYS)
            or any(
                type(key) is not str or key not in _AGENTIC_EXTRA_CONTEXT_KEYS
                for key in extra_context
            )
        ):
            raise ValueError("agentic_context_invalid")
        else:
            _context = dict(extra_context)

        department, rank = _resolve_agentic_identity(
            runtime=runtime,
            tool_registry=registry,
            agent_id=agent_id,
            fallback_department=department,
            fallback_rank=rank,
        )

        executor = DispatchToolExecutor(registry=registry)
        observed_tool_results: list[tuple[Any, Any]] = []

        def _record_tool_result(context: dict[str, Any], result: ToolResult) -> None:
            tool_id = context.get("tool_id") if type(context) is dict else None
            if tool_id == "run_python":
                observed_tool_results.append((tool_id, result))

        executor.add_post_hook(_record_tool_result)

        mesh_ids: list[str] = []
        if intent_bus is not None and registry is not None:
            try:
                mesh_ids = register_mesh_intent_tools(registry, intent_bus)
            except Exception:
                logger.warning(
                    "AD-859a: failed to register mesh-intent tools for agent "
                    "%s; continuing with granted tools only",
                    agent_id, exc_info=True,
                )
                mesh_ids = []

        # AD-1007: drop mesh-intent tools this agent is explicitly RESTRICTED
        # from (a Captain capability disable). The conversational [MESH] path
        # gates the same way at reply_pipeline.step_4h; this is the agentic-loop
        # counterpart so a disabled capability is unavailable on BOTH paths.
        # Agent-precedence: only an explicit ``restricted`` resolution removes
        # the tool; ``granted``/``no_opinion`` leave it (role/ship default).
        # Honest-degrade: no store -> no filtering.
        intent_grant_store = getattr(runtime, "intent_grant_store", None)
        if intent_grant_store is not None and mesh_ids:
            mesh_ids = [
                m for m in mesh_ids
                if intent_grant_store.resolve_sync(agent_id, m) != "restricted"
            ]

        granted_ids: list[str] = []
        if perm_store is not None:
            grants = perm_store.get_active_grants_sync(agent_id)
            granted_ids = [
                g.tool_id
                for g in grants
                if not g.is_restriction and g.tool_id not in _GATED_TOOL_IDS
            ]

        # AD-1019c: contribute the agent's authorized MCP workbench tools — the
        # find_mcp_tool search tool plus any currently-warm authorized adapters.
        # Default-OFF: gated on config.mcp.agent_tools_enabled + a wired
        # workbench, so off ⇒ byte-identical to the AD-1007 tool set.
        mcp_ids: list[str] = []
        workbench = getattr(runtime, "mcp_workbench", None)
        mcp_cfg = getattr(getattr(runtime, "config", None), "mcp", None)
        if workbench is not None and getattr(mcp_cfg, "agent_tools_enabled", False):
            try:
                mcp_ids = workbench.dispatch_tool_ids(agent_id)
            except Exception:
                logger.warning(
                    "AD-1019c: failed to resolve MCP workbench tools for agent "
                    "%s; continuing without MCP tools",
                    agent_id, exc_info=True,
                )
                mcp_ids = []

        # AD-1066: offer the sandboxed code-execution tool when the operator has
        # enabled execution (config.execution.enabled). It is the keystone for
        # document / data tasks — the agent writes a Python script (python-docx,
        # openpyxl, matplotlib, reportlab, …) and any file it produces becomes a
        # downloadable artifact on the chat thread. Registered idempotently
        # (mirrors the AD-856 mesh-tool registration); gated + sandboxed
        # (AD-993/994); empty default_permissions ⇒ ship-wide READ ⇒ invokable.
        exec_ids: list[str] = []
        exec_cfg = getattr(getattr(runtime, "config", None), "execution", None)
        if getattr(exec_cfg, "enabled", False) and registry is not None:
            try:
                from probos.tools.code_execution_tool import CodeExecutionTool

                if registry.get("run_python") is None:
                    registry.register(
                        CodeExecutionTool(runtime=runtime),
                        provider="AD-1066",
                        tags=["run_python", "code_execution"],
                    )
                exec_ids = ["run_python"]
            except Exception:
                logger.warning(
                    "AD-1066: failed to register/offer the code-execution tool "
                    "for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                exec_ids = []

        # AD-1068: offer the use_skill tool whenever the cognitive-skill catalog
        # is wired — it loads a skill's SKILL.md body + bundled-script manifest
        # into the loop so the agent can run the skill's scripts via run_python
        # (AD-1066) by absolute path. Read-only (does NOT itself require
        # execution.enabled; running the returned scripts does). Registered
        # idempotently (mirrors the AD-1066 block); empty default_permissions ⇒
        # ship-wide READ ⇒ invokable.
        skill_ids: list[str] = []
        if (
            getattr(runtime, "cognitive_skill_catalog", None) is not None
            and registry is not None
        ):
            try:
                from probos.tools.use_skill_tool import UseSkillTool

                if registry.get("use_skill") is None:
                    registry.register(
                        UseSkillTool(runtime=runtime),
                        provider="AD-1068",
                        tags=["use_skill", "skills"],
                    )
                skill_ids = ["use_skill"]
            except Exception:
                logger.warning(
                    "AD-1068: failed to register/offer the use_skill tool for "
                    "agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                skill_ids = []

        # AD-1072: the conversational-loop discovery + delegation tools, both
        # default-OFF (config.agentic_tools). With both flags off this whole
        # section is inert and ``tool_ids`` is byte-identical to the AD-1068 set.
        agentic_tools_cfg = getattr(
            getattr(runtime, "config", None), "agentic_tools", None
        )

        # AD-1072: offer the read-only capability-search tool when enabled. It
        # lets the agent discover tools / skills / mesh-intents by keyword before
        # acting, instead of confabulating a verb (BF-651 / AD-1064). Registered
        # idempotently (mirrors the AD-1066/1068 blocks); read-only.
        search_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "tool_search_enabled", False)
            and registry is not None
        ):
            try:
                from probos.tools.search_capabilities_tool import (
                    SearchCapabilitiesTool,
                )

                if registry.get("search_capabilities") is None:
                    registry.register(
                        SearchCapabilitiesTool(runtime=runtime),
                        provider="AD-1072",
                        tags=["search_capabilities", "discovery"],
                    )
                search_ids = ["search_capabilities"]
            except Exception:
                logger.warning(
                    "AD-1072: failed to register/offer the search_capabilities "
                    "tool for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                search_ids = []

        # AD-1072: offer the delegation tool when enabled. It hands a bounded
        # subtask to another crew agent by callsign, routed through THIS same
        # governed executor (so the delegate's tool permissions / consensus gates
        # / tool-trace all apply). Bounded by delegation_max_depth (recursion
        # guard) + delegation_max_iterations. The tool reuses the parent
        # executor's own LLM client (self._llm). Registered idempotently.
        delegate_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "delegation_enabled", False)
            and registry is not None
        ):
            try:
                from probos.tools.delegate_task_tool import DelegateTaskTool

                if registry.get("delegate_task") is None:
                    registry.register(
                        DelegateTaskTool(
                            runtime=runtime,
                            llm_client=self._llm,
                            max_depth=getattr(
                                agentic_tools_cfg, "delegation_max_depth", 1
                            ),
                            max_iterations=getattr(
                                agentic_tools_cfg, "delegation_max_iterations", 5
                            ),
                            tier=getattr(
                                agentic_tools_cfg, "delegation_tier", "standard"
                            ),
                        ),
                        provider="AD-1072",
                        tags=["delegate_task", "delegation"],
                    )
                delegate_ids = ["delegate_task"]
            except Exception:
                logger.warning(
                    "AD-1072: failed to register/offer the delegate_task tool "
                    "for agent %s; continuing without it",
                    agent_id, exc_info=True,
                )
                delegate_ids = []

        event_log_ids: list[str] = []
        if registry is not None and registry.get("event_log_query") is not None:
            if registry.check_permission(
                agent_id,
                "event_log_query",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                event_log_ids = ["event_log_query"]

        # AD-1139: offer the read-only Oracle consult tool when startup
        # registered it (default-OFF via config.agentic_tools). It lets the
        # agent reach the ship's shared knowledge commons — Σ tiers only, never
        # the sovereign episodic shard — mid-task, instead of only receiving
        # Oracle context passively during perceive. Permission-checked, and an
        # agent whose department/rank is denied simply does not see the tool
        # (silent honest-degrade, mirroring the event_log_query block above).
        oracle_ids: list[str] = []
        if registry is not None and registry.get("oracle_query") is not None:
            if registry.check_permission(
                agent_id,
                "oracle_query",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                oracle_ids = ["oracle_query"]

        # AD-1140: offer the commons-write tool when startup registered it
        # (default-OFF via config.agentic_tools). It is the write half of Σ —
        # the agent records a finding into Ship's Records so a different agent
        # in a later session reaches it through ``oracle_query``. WRITE-level,
        # and an agent whose department/rank is denied simply does not see the
        # tool (silent honest-degrade, mirroring the two blocks above).
        publish_ids: list[str] = []
        if registry is not None and registry.get("publish_finding") is not None:
            if registry.check_permission(
                agent_id,
                "publish_finding",
                ToolPermission.WRITE,
                agent_department=department,
                agent_rank=rank,
            ):
                publish_ids = ["publish_finding"]

        # AD-1153: offer the browser READ-ONLY (default-OFF via
        # config.agentic_tools.browser_enabled). Two flags, one AND: the config
        # gate plus ``registry.get("browser")``, which already carries
        # ``browser_tool.enabled`` and the Playwright-import check from
        # ``_wire_browser_tool`` — so the availability logic is not re-derived
        # here. Permission-checked at READ, which is exactly what
        # ``check_and_invoke`` requires at invoke time, so an offered agent is an
        # invoking agent. The registered rank matrix keeps ``ensign: none``
        # (DD-2): rank is trust-derived, so that denies the browser precisely to
        # agents that are new, self-designed or currently failing. Denied ⇒ the
        # tool is silently absent (honest-degrade, mirroring the blocks above).
        #
        # NOTE for AD-1154 (#1081): admitting ``click`` / ``type`` here makes the
        # tier-3 path reachable, and BF-682 (the raw confirmation token in the
        # TOOL_INTERVENTION_REQUIRED payload) becomes a precondition to close
        # first. No action in ``_BROWSER_LOOP_ACTIONS`` can reach tier 3, so no
        # token is minted on this path today.
        browser_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "browser_enabled", False)
            and registry is not None
            and registry.get("browser") is not None
        ):
            if registry.check_permission(
                agent_id,
                "browser",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ):
                browser_ids = ["browser"]
                self._warn_once_on_open_browser_egress(runtime)

        # AD-1153 / DD-1: arm the read-only guard ONLY when the tool reached the
        # loop through the block above AND the agent does not already hold it
        # through a Captain grant. An agent can hold ``browser`` by both routes;
        # narrowing the grant path would silently revoke a working capability and
        # invert Layer 4's grant-UP semantics (``browser`` is deliberately NOT in
        # ``_GATED_TOOL_IDS`` — it carries no ``allowed_departments``, so the
        # gate would have nothing to protect and would only remove the Captain's
        # escape hatch for probationary agents).
        if browser_ids and "browser" not in granted_ids:
            executor.restrict_browser_actions(_BROWSER_LOOP_ACTIONS)

        tool_ids = list(
            dict.fromkeys([
                *granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids,
                *search_ids, *delegate_ids, *event_log_ids, *oracle_ids,
                *publish_ids, *browser_ids,
            ])
        )

        tools: list[dict] = []
        if registry is not None:
            for tid in tool_ids:
                reg = registry.get(tid)
                if reg is None:
                    continue
                tools.append(tool_registration_to_llm_definition(reg))

        # AD-1065: the conversational chat path passes a lower iteration cap +
        # a faster tier than the task-path defaults (25 / deep). When both are
        # None (the AD-839/859 task callers) the AgenticLoop defaults are used,
        # so the task path is byte-identical.
        _loop_kwargs: dict[str, Any] = {}
        if max_iterations is not None:
            _loop_kwargs["max_iterations"] = max_iterations
        if tier is not None:
            _loop_kwargs["tier"] = tier
        # AD-1142: threaded the same way, so a caller that passes none of them
        # (every non-crew caller, and the crew path with the gate off) builds a
        # byte-identical kwarg dict — same keys, same order.
        if compactor is not None:
            _loop_kwargs["compactor"] = compactor
        if compaction_threshold is not None:
            _loop_kwargs["compaction_threshold"] = compaction_threshold
        if token_budget is not None:
            _loop_kwargs["token_budget"] = token_budget
        # AD-1146: opt into the provider's real multi-turn message array
        # (assistant.tool_calls + role:"tool" results). Default-OFF — with the
        # flag off the loop builds the AD-545 flattened prompt verbatim. Read
        # defensively so synthetic/event-neutral runtimes without a config still
        # construct the loop.
        _agentic_loop_cfg = getattr(
            getattr(runtime, "config", None), "agentic_loop", None
        )
        loop = AgenticLoop(
            llm_client=self._llm,
            tool_executor=executor,
            event_emit_fn=getattr(runtime, "emit_event", None),
            structured_tool_messages=bool(
                getattr(_agentic_loop_cfg, "structured_tool_messages", False)
            ),
            # AD-1148: bound each tool result before it enters the loop's
            # message history. 0 = unbounded (default-OFF), so message content
            # is byte-identical until an operator opts in.
            **resolve_tool_result_bounds(_agentic_loop_cfg),
            # AD-1147: fan the read-only allowlisted tool calls of one response
            # out concurrently, bounded. Default-OFF — the sequential AD-545
            # path runs verbatim until an operator opts in.
            **resolve_parallel_tool_settings(_agentic_loop_cfg),
            **_loop_kwargs,
        )
        # AD-1129: accepted compatibility extras are copied first; the run's
        # authoritative identity and explicit thread provenance always win.
        _context.update(
            {
                "agent_id": agent_id,
                "department": department,
                "rank": rank,
                "thread_id": thread_id,
            }
        )
        agentic_result = await loop.run(
            system_prompt=instructions or "",
            user_message=task_text,
            tools=tools,
            context=_context,
        )

        tool_trace_ref = await self._persist_tool_trace(
            agentic_result, runtime, agent_id
        )
        artifact_refs, ignored_artifact_entries = _extract_artifact_refs(
            observed_tool_results,
            thread_id=thread_id,
        )
        if ignored_artifact_entries:
            logger.warning(
                "AD-1125: dropped %d malformed, duplicate, cross-thread, or "
                "over-limit artifact evidence entries for agent %s in thread %s; "
                "continuing with %d validated refs",
                ignored_artifact_entries,
                agent_id,
                thread_id or "<none>",
                len(artifact_refs),
            )
        raw_total_tokens = getattr(agentic_result, "total_tokens", 0)
        total_tokens = (
            raw_total_tokens
            if type(raw_total_tokens) is int and raw_total_tokens >= 0
            else 0
        )
        if total_tokens != raw_total_tokens:
            logger.warning(
                "AD-1125: agentic result for agent %s carried an invalid token "
                "total; recording zero so downstream evidence remains bounded",
                agent_id,
            )
        # BF-680: the loop substitutes a client-side estimate when the provider
        # reports no usage. Surface that here, correlated to the agent and
        # thread, because the ``crew_execution`` record this total lands in is a
        # frozen 14-key set with nowhere to say it.
        token_source = getattr(
            agentic_result, "token_source", TOKEN_SOURCE_MEASURED
        )
        if token_source != TOKEN_SOURCE_MEASURED:
            logger.warning(
                "BF-680: token total %d for agent %s in thread %s is %s, not a "
                "provider measurement; downstream cost evidence records it as "
                "a bare int and cannot distinguish the two",
                total_tokens,
                agent_id,
                thread_id or "<none>",
                token_source,
            )

        return WorkItemAgenticOutcome(
            final_text=agentic_result.final_text or "",
            stopped_reason=agentic_result.stopped_reason,
            denied_tools=list(executor.denied_tools),
            tool_trace_ref=tool_trace_ref,
            total_tokens=total_tokens,
            artifact_refs=artifact_refs,
            token_source=token_source,
        )

    async def _persist_tool_trace(
        self,
        agentic_result: Any,
        runtime: Any,
        agent_id: str,
    ) -> str | None:
        """Persist the loop's tool calls AND their outputs; return the SHA ref.

        AD-1151: the blob records what each tool actually returned, not just
        that it was called, so the durable trace matches the Nooplex §3.3
        Transparency guarantee that AD-1142 and AD-1148 both cited. The shape is
        unchanged for existing readers — still a bare JSON array, still carrying
        every ``ToolCallRequest`` key — so versioning is by key presence.

        Honest-degrade to ``None`` (log a warning) when the store is unwired or
        the write fails — the trace ref is provenance, not correctness, so a
        missing store must not fail the dispatch (AD-731 / log-and-degrade tier).
        The payload shaping sits inside the same ``try`` so a malformed result
        degrades identically rather than failing the dispatch.
        """
        try:
            store = getattr(runtime, "attachment_store", None)
        except Exception:
            logger.warning(
                "AD-859a: attachment_store accessor raised while persisting the "
                "tool trace for agent %s; tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
        if store is None:
            return None
        try:
            # Function-local, matching the AgenticLoop import at the top of
            # ``run``. There is no module cycle to work around here, but the
            # locality is load-bearing anyway: tests monkeypatch names on
            # ``swe_harness.agentic_loop`` itself, which only takes effect when
            # this module resolves them at call time.
            from probos.cognitive.swe_harness.agentic_loop import (
                build_tool_trace_payload,
                resolve_tool_trace_bounds,
            )

            bounds = resolve_tool_trace_bounds(
                getattr(getattr(runtime, "config", None), "agentic_loop", None)
            )
            _entries, blob = build_tool_trace_payload(
                getattr(agentic_result, "tool_calls", []),
                getattr(agentic_result, "tool_results", []),
                **bounds,
            )
            blob_max_bytes = bounds["blob_max_bytes"]
            if blob_max_bytes and len(blob) > blob_max_bytes:
                # AD-1151 / DD-5: every output has already been elided and the
                # call records alone still exceed the cap. Persist them anyway —
                # dropping request records to save bytes would regress the
                # guarantee this trace exists to provide.
                logger.warning(
                    "AD-1151: tool trace for agent %s is %d bytes after eliding "
                    "every output, over the %d-byte cap; persisting the call "
                    "records anyway so the provenance record is not lost",
                    agent_id, len(blob), blob_max_bytes,
                )
            content_hash = hashlib.sha256(blob).hexdigest()
            await store.write(
                content_hash=content_hash,
                blob=blob,
                mime="application/json",
                origin="crew_trace",
            )
            return content_hash
        except Exception:
            logger.warning(
                "AD-859a: failed to persist the tool trace for agent %s; "
                "tool_trace_ref will be None",
                agent_id, exc_info=True,
            )
            return None
