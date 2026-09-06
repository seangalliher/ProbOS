"""AD-1019c: the MCP tool workbench — active search + warm lazy adapters.

The GitHub-Copilot *deferred-tool* model, for MCP tools. An agent does not carry
every authorized MCP tool in its prompt; it **searches** for one by concept
(:meth:`MCPWorkbench.find_mcp_tool`, the AD-979c RRF primitives over the agent's
AD-1019b-authorized ``{name, description}`` set), then **pulls** the chosen tool
onto its *workbench* (:meth:`pull_tool`, which registers a thin :class:`_McpTool`
adapter in the ``ToolRegistry`` — mirroring ``register_mesh_intent_tools``). The
:class:`MCPBridge` keeps the underlying client warm (its ``_clients`` cache), so
re-use within a session never re-fetches. A 24h idle-TTL reaper
(:class:`~probos.integrations.mcp_bridge.reaper.McpWorkbenchReaper`) unloads idle
adapters back to the toolbox.

Per-agent scoping uses the AD-1019b ``resolve_mcp_access`` precedence ladder (the
same resolver the management API uses) — NOT the mesh-intent ``ToolPermissionStore``
lens. Default-OFF: the workbench is only constructed when
``config.mcp.agent_tools_enabled`` is set; off ⇒ byte-identical to AD-1019b.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

from jsonschema import Draft202012Validator

from probos.cognitive.agentic_dispatch import _coerce_risk, _McpTool
from probos.cognitive.episodic import fts_or_query, reciprocal_rank_fusion
from probos.integrations.mcp_bridge.access import resolve_mcp_access
from probos.integrations.mcp_bridge.risk import McpToolRisk, resolve_tool_risk
from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params

if TYPE_CHECKING:
    from probos.integrations.mcp_bridge.store import McpServerRecord
    from probos.tools.protocol import ToolAccessGrant, ToolRegistration

logger = logging.getLogger(__name__)

_FIND_MCP_TOOL_ID = "find_mcp_tool"
MCP_DISPATCH_OFFER_CONTEXT_KEY = "_mcp_dispatch_offer"

# BF-754: bounds on an MCP server's advertised inputSchema. The schema is
# remote input that goes straight into an LLM request, so it is validated and
# bounded here rather than trusted: a hostile or broken server must not be able
# to blow up the prompt or hand the provider something it will reject.
#
# BF-757: the original pass checked SIZE and called that validation. It was not.
# Measured against the live Copilot proxy, a malformed schema is accepted here
# and then returns HTTP 500 -- which fails the agent's WHOLE turn, not just the
# one tool.
#
# The first BF-757 attempt hand-rolled a structural walk. Re-review measured it
# against the proxy and it was wrong in BOTH directions: it REJECTED `$defs` +
# local `$ref`, boolean `items`, and nine-deep nesting (all HTTP 200), and it
# ACCEPTED `type: "bogus"`, `oneOf: []`, `additionalProperties: "nope"`,
# `minimum: "zero"` and a non-string `format` (all HTTP 500). A false rejection
# silently strips a good server's parameters, which is the exact failure BF-754
# existed to fix.
#
# The proxy's own error names the authority -- "It must match JSON Schema draft
# 2020-12" -- so ask that authority instead of approximating it. Every verdict
# above then matches.
_SCHEMA_MAX_PROPERTIES = 64
_SCHEMA_MAX_BYTES = 16_384

# BF-757: a tool's advertised description is remote input on the same path. 24
# tools advertising 100 KB descriptions rendered a 2,788,502-byte tool block
# (~697k tokens) -- over the context window, so the turn dies before it starts.
_DESCRIPTION_MAX_CHARS = 4_096


def _safe_description(raw: Any) -> str:
    """BF-757: a tool description the provider will accept, always a ``str``.

    A non-string is dropped rather than coerced: ``str(some_dict)`` would put
    remote-controlled punctuation into the prompt claiming to be prose.
    """
    if not isinstance(raw, str):
        return ""
    if len(raw) <= _DESCRIPTION_MAX_CHARS:
        return raw
    return raw[:_DESCRIPTION_MAX_CHARS] + " [...truncated]"


def _safe_input_schema(
    raw: Any, server_name: str, tool_name: str
) -> dict[str, Any]:
    """BF-754: the tool's advertised JSON Schema, or a permissive fallback.

    Falling back to ``{"type": "object"}`` keeps the tool callable when a server
    advertises something unusable -- the model just has to infer the arguments,
    which is exactly the situation before this existed.

    BF-757: the returned schema is always PLAIN json data, never the object the
    caller passed. ``isinstance(x, dict)`` admits subclasses, and a subclass
    that serialises as ``{}`` while its ``get`` synthesises 250,000 nodes made
    the previous hand-rolled walk visit all of them. Round-tripping through
    json is what actually bounds the inspection, and it is also what lets the
    2020-12 check below see exactly the data the provider will see.
    """
    if not isinstance(raw, dict):
        return {"type": "object"}
    try:
        # allow_nan=False: the default emits bare ``NaN``/``Infinity``, which is
        # not JSON -- it serialises here and then dies at the provider.
        encoded = json.dumps(raw, allow_nan=False)
    except Exception:
        logger.warning(
            "BF-754: %s/%s advertises a non-serialisable inputSchema; offering "
            "it without a parameter schema", server_name, tool_name,
        )
        return {"type": "object"}
    if len(encoded) > _SCHEMA_MAX_BYTES:
        logger.warning(
            "BF-754: %s/%s inputSchema is %d bytes (max %d); offering it "
            "without a parameter schema",
            server_name, tool_name, len(encoded), _SCHEMA_MAX_BYTES,
        )
        return {"type": "object"}
    try:
        schema = json.loads(encoded)
    except Exception:
        return {"type": "object"}
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {"type": "object"}
    props = schema.get("properties")
    if props is not None and not isinstance(props, dict):
        return {"type": "object"}
    if isinstance(props, dict) and len(props) > _SCHEMA_MAX_PROPERTIES:
        logger.warning(
            "BF-754: %s/%s advertises %d properties (max %d); offering it "
            "without a parameter schema",
            server_name, tool_name, len(props), _SCHEMA_MAX_PROPERTIES,
        )
        return {"type": "object"}
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        logger.warning(
            "BF-757: %s/%s advertises an inputSchema that is not valid JSON "
            "Schema 2020-12 (%s); the provider rejects the whole request for "
            "these, so offering it without a parameter schema",
            server_name, tool_name, exc.__class__.__name__,
        )
        return {"type": "object"}
    return schema


def _tokenize(text: str) -> set[str]:
    """Deterministic token set for *text*, reusing the AD-979c tokenizer.

    Mirrors ``capability_retriever._tokenize``: :func:`fts_or_query` lowercases,
    splits on non-alphanumerics, drops <2-char tokens and dedupes, returning a
    quoted OR-string; this recovers the bare tokens as a set.
    """
    q = fts_or_query(text or "")
    if not q:
        return set()
    return {term.strip('"') for term in q.split(" OR ")}


@dataclass
class _PulledEntry:
    """One adapter currently warm on the workbench (mutable: ``last_used``)."""

    tool_id: str
    server_name: str
    tool_name: str
    last_used: float


class MCPDispatchOffer:
    """AD-1241: one run's bounded presentation window, never invocation authority.

    The workbench factory supplies only that run's preload results. Pending IDs
    are successful admissions pinned until the executor acknowledges a
    successfully assembled offer, even when its ordered IDs have not changed.
    No grants, tool payloads or run-indexed state are retained here.
    """

    __slots__ = ("_workbench", "_agent_id", "_capacity", "_selected", "_pending")

    def __init__(
        self,
        workbench: MCPWorkbench,
        agent_id: str,
        *,
        preload_limit: int,
        preloaded_ids: Sequence[str] = (),
    ) -> None:
        if type(agent_id) is not str or not agent_id:
            raise ValueError("MCP dispatch offer requires a non-empty agent ID")
        if type(preload_limit) is not int:
            raise TypeError("MCP dispatch preload limit must be an integer")
        if not isinstance(preloaded_ids, Sequence) or isinstance(preloaded_ids, (str, bytes)):
            raise TypeError("Preloaded MCP IDs must be a sequence of tool IDs")
        normalized_limit = max(0, preload_limit)
        self._workbench = workbench
        self._agent_id = agent_id
        self._capacity = max(24, normalized_limit)
        self._selected: dict[str, None] = {}
        self._pending: set[str] = set()
        for tool_id in preloaded_ids:
            if len(self._selected) >= normalized_limit:
                break
            if self._valid_tool_id(tool_id):
                self._selected[tool_id] = None

    @staticmethod
    def _valid_tool_id(tool_id: str) -> bool:
        if type(tool_id) is not str:
            return False
        parts = tool_id.split(":", 2)
        return (
            len(parts) == 3
            and parts[0] == "mcp"
            and bool(parts[1])
            and bool(parts[2])
        )

    @property
    def capacity(self) -> int:
        """Adapter capacity, excluding search and all non-MCP definitions."""
        return self._capacity

    @property
    def selected_ids(self) -> tuple[str, ...]:
        """An immutable, oldest-first snapshot for bounded authorization refresh."""
        return tuple(self._selected)

    @property
    def pending_ids(self) -> tuple[str, ...]:
        """Successful pull admissions awaiting assembly or explicit filtering."""
        return tuple(tool_id for tool_id in self._selected if tool_id in self._pending)

    def belongs_to(self, workbench: MCPWorkbench, agent_id: str) -> bool:
        """Check source ownership and consistency with executor-authored identity."""
        return (
            self._workbench is workbench
            and type(agent_id) is str
            and self._agent_id == agent_id
        )

    def admit(self, tool_id: str) -> bool:
        """Synchronously admit a successful pull, or defer when all slots are pinned.

        Call only after a successful current pull. Duplicate discovery promotes
        and pins the existing member; eviction never unregisters a warm adapter.
        """
        if not self._valid_tool_id(tool_id):
            return False
        if tool_id in self._selected:
            self._selected.pop(tool_id)
        elif len(self._selected) >= self._capacity:
            oldest = next(
                (candidate for candidate in self._selected if candidate not in self._pending),
                None,
            )
            if oldest is None:
                logger.debug(
                    "AD-1241: agent %s has %d pinned MCP offers; deferring %s "
                    "until a later discovery after publication",
                    self._agent_id[:12], self._capacity, tool_id,
                )
                return False
            self._selected.pop(oldest)
        self._selected[tool_id] = None
        self._pending.add(tool_id)
        logger.debug(
            "AD-1241: admitted an MCP pull for agent %s's next offer (%d/%d); "
            "pinning it until successful assembly or filtering",
            self._agent_id[:12], len(self._selected), self._capacity,
        )
        return True

    def acknowledge_published(self, published_ids: Sequence[str]) -> None:
        """Commit exact post-dedupe MCP survivors and release selection pins.

        Local publication is neither provider acceptance nor invocation authority.
        Omitted members are filtered/withdrawn, never repulled. Call also for
        unchanged-list publication, using cached assembly identities; selection
        or assembly failures must leave this uncalled. Invalid input changes nothing.
        """
        if not isinstance(published_ids, Sequence) or isinstance(published_ids, (str, bytes)):
            raise TypeError("Published MCP IDs must be a sequence of tool IDs")
        published: dict[str, None] = {}
        for tool_id in published_ids:
            if type(tool_id) is str and tool_id == _FIND_MCP_TOOL_ID:
                continue
            if not self._valid_tool_id(tool_id) or tool_id not in self._selected:
                raise ValueError("Published MCP IDs must belong to the current offer")
            published[tool_id] = None
        published_pins = len(self._pending.intersection(published))
        withdrawn_pins = len(self._pending) - published_pins
        removed = len(self._selected) - len(published)
        self._selected = published
        self._pending.clear()
        log = logger.info if removed else logger.debug
        log(
            "AD-1241: agent %s locally published %d MCP definitions; released "
            "%d published pins and withdrew %d filtered members (%d pending "
            "pins) after current-access, availability or definition filtering; "
            "invocation still requires current authority",
            self._agent_id[:12], len(published), published_pins, removed, withdrawn_pins,
        )


class MCPDispatchSource(Protocol):
    """Run-local MCP offers and fresh candidate selection from their source."""

    async def create_dispatch_offer(
        self, agent_id: str, *, preload_limit: int
    ) -> MCPDispatchOffer: ...

    def dispatch_tool_ids(
        self, agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]: ...

    def accepts_dispatch_offer(
        self, offer: MCPDispatchOffer, agent_id: str
    ) -> bool: ...


class _MCPGrantReader(Protocol):
    def get_active_grants_sync(
        self, principal_id: str, /
    ) -> list[ToolAccessGrant]: ...


class _MCPServerReader(Protocol):
    def list_sync(self) -> list[McpServerRecord]: ...


class _MCPRegistrationReader(Protocol):
    def get(self, tool_id: str) -> ToolRegistration | None: ...


class _MCPWorkbenchAccess:
    """Fresh MCP access and adapter selection, without lifecycle or offer state."""

    def __init__(
        self,
        *,
        registration_reader: _MCPRegistrationReader,
        server_reader: _MCPServerReader | None,
        agent_grant_reader: _MCPGrantReader | None,
        department_grant_reader: _MCPGrantReader | None,
        agent_department: Callable[[str], str],
    ) -> None:
        self._registry = registration_reader
        self._server_store = server_reader
        self._perm_store = agent_grant_reader
        self._dept_grant_store = department_grant_reader
        self._agent_department = agent_department

    def grants(
        self, agent_id: str
    ) -> tuple[list[ToolAccessGrant], list[ToolAccessGrant]]:
        """The agent's active grants + its department's grants (for the resolver)."""
        grants = (
            self._perm_store.get_active_grants_sync(agent_id)
            if self._perm_store is not None
            else []
        )
        dept = self._agent_department(agent_id)
        dept_grants = (
            self._dept_grant_store.get_active_grants_sync(dept)
            if self._dept_grant_store is not None and dept
            else []
        )
        return grants, dept_grants

    def is_authorized(
        self, agent_id: str, server_name: str, tool_name: str
    ) -> bool:
        """AD-1019b three-source resolution for one ``(server, tool)`` pair."""
        grants, dept_grants = self.grants(agent_id)
        enabled, _source = resolve_mcp_access(
            grants, server_name, tool_name, department_grants=dept_grants
        )
        return enabled

    def can_invoke_tool(
        self, agent_id: str, server_name: str, tool_name: str
    ) -> bool:
        """Recheck current server availability and grants, including warm clients."""
        try:
            record = self.record_by_name(server_name)
            return (
                record is not None
                and record.enabled
                and self.is_authorized(agent_id, server_name, tool_name)
            )
        except Exception:
            logger.warning(
                "AD-1241: current MCP server/access state for %s/%s could not "
                "be read for agent %s; denying rather than using warm authority",
                server_name, tool_name, agent_id[:12] or "?", exc_info=True,
            )
            return False

    def record_by_name(self, server_name: str) -> McpServerRecord | None:
        if self._server_store is None:
            return None
        for rec in self._server_store.list_sync():
            if rec.name == server_name:
                return rec
        return None

    def dispatch_tool_ids(
        self,
        agent_id: str,
        *,
        pulled: Mapping[str, _PulledEntry],
        register_search_tool: Callable[[], str],
        candidate_ids: Sequence[str] | None = None,
    ) -> list[str]:
        """Tool ids to add to this agent's dispatch set (AD-1019c).

        The ``find_mcp_tool`` search tool plus every currently-warm adapter the
        agent is AD-1019b-authorized for. Mirrors the AD-1007 per-agent filter,
        but the authorization source is ``resolve_mcp_access`` (not the
        mesh-intent grant store). Empty when nothing is authorized + nothing
        pulled is still a list with the search tool so the agent can discover.

        AD-1241: supplied ``candidate_ids`` limit selection to distinct ids in
        their supplied order, using fresh grant and server snapshots once per
        call. ``None`` preserves the full warm view; an empty sequence offers
        only the search tool.
        """
        if candidate_ids is not None and (
            not isinstance(candidate_ids, Sequence) or isinstance(candidate_ids, (str, bytes))
        ):
            raise TypeError("Candidate MCP IDs must be a sequence of tool IDs")
        ids = [register_search_tool()]
        if candidate_ids is not None:
            if not candidate_ids or self._server_store is None:
                return ids
            grants, dept_grants = self.grants(agent_id)
            records = {
                record.name: record for record in self._server_store.list_sync()
            }
            for tool_id in dict.fromkeys(
                candidate for candidate in candidate_ids if type(candidate) is str
            ):
                entry = pulled.get(tool_id)
                if entry is None:
                    continue
                registration = self._registry.get(tool_id)
                if registration is None or not registration.enabled:
                    continue
                record = records.get(entry.server_name)
                if record is None or not record.enabled:
                    continue
                enabled, _source = resolve_mcp_access(
                    grants, entry.server_name, entry.tool_name,
                    department_grants=dept_grants,
                )
                if enabled:
                    ids.append(tool_id)
            return ids
        for tid, entry in pulled.items():
            # BF-755 review: an adapter stays warm after an operator disables
            # its server, and authorization alone did not notice. Offering it
            # spends an LLM call on a tool that fails at the bridge. Invocation
            # was always deny-safe; this stops the wasted turn.
            record = self.record_by_name(entry.server_name)
            if record is not None and not getattr(record, "enabled", True):
                continue
            if self.is_authorized(agent_id, entry.server_name, entry.tool_name):
                ids.append(tid)
        return ids

    @property
    def enabled_server_names(self) -> list[str]:
        """AD-1239: names of the currently connected, enabled MCP servers.

        Public so ``find_mcp_tool`` can NAME them in its description instead of
        describing an abstract search. "Search for an MCP tool" told an agent
        nothing about whether anything was there to find; "servers connected:
        microsoft-learn" tells it what it can reach.
        """
        if self._server_store is None:
            return []
        try:
            return sorted(r.name for r in self._server_store.list_sync() if r.enabled)
        except Exception:
            logger.warning(
                "AD-1239: could not list MCP servers for the find_mcp_tool "
                "description; describing it without server names",
                exc_info=True,
            )
            return []


class MCPWorkbench:
    """Active MCP-tool search + warm lazy-adapter lifecycle (AD-1019c).

    Constructed once per runtime when ``config.mcp.agent_tools_enabled``. Holds
    narrow, constructor-injected dependencies (the (D) principle): the registry,
    the bridge, the four AD-1019/1019b stores, the ontology/registry for
    department resolution, and two bound runtime callables (``consensus_invoke``
    = ``submit_mcp_invoke_with_consensus`` and ``episode_writer`` =
    ``_store_mcp_invoke_episode``). It never reaches into runtime internals
    itself.
    """

    def __init__(
        self,
        *,
        tool_registry: Any,
        bridge: Any,
        consensus_invoke: Callable[
            [str, str, dict[str, Any]], Awaitable[dict[str, Any]]
        ],
        episode_writer: Callable[..., Awaitable[None]] | None,
        server_store: Any | None,
        perm_store: Any | None,
        dept_grant_store: Any | None,
        risk_store: Any | None,
        ontology: Any | None,
        agent_registry: Any | None,
    ) -> None:
        self._registry = tool_registry
        self._bridge = bridge
        self._consensus_invoke = consensus_invoke
        self._episode_writer = episode_writer
        self._server_store = server_store
        self._risk_store = risk_store
        self._ontology = ontology
        self._agent_registry = agent_registry
        self._pulled: dict[str, _PulledEntry] = {}
        self._access = _MCPWorkbenchAccess(
            registration_reader=tool_registry,
            server_reader=server_store,
            agent_grant_reader=perm_store,
            department_grant_reader=dept_grant_store,
            agent_department=self._agent_department,
        )

    # ---- department + authorization (AD-1019b resolver) ----------------

    def _agent_department(self, agent_id: str) -> str:
        """Resolve the agent's crew/governance department (honest-degrade → "")."""
        reg = self._agent_registry
        ont = self._ontology
        if reg is None or ont is None:
            return ""
        agent = reg.get(agent_id)
        if agent is None:
            return ""
        return ont.get_agent_department(getattr(agent, "agent_type", "")) or ""

    # ---- server / tool enumeration ------------------------------------

    @staticmethod
    def _bridge_key(record: "McpServerRecord") -> str:
        """The value ``MCPBridge._clients`` is keyed by: url (http) / name (stdio)."""
        return record.url if record.type == "http" else record.name

    async def _enumerate_tools(
        self, record: "McpServerRecord"
    ) -> list[dict[str, Any]]:
        """Live ``{name, description, input_schema}`` for a server's tools.

        BF-754: ``input_schema`` used to be dropped here and hardcoded to a bare
        ``{"type": "object"}`` at registration, so the model was told a tool
        existed but never told what to pass it. The live Microsoft Learn server
        advertises required parameters (``query``, ``url``) that never reached
        the offer. Never raises → [].
        """
        client = self._bridge.get_client(self._bridge_key(record))
        if client is None:
            # BF-751: this used to return silently, which made a server that was
            # registered-but-unreachable indistinguishable from one with no tools.
            logger.warning(
                "AD-1019c: MCP server %s has no bridge client, so it contributes "
                "no tools; it is registered but was never wired to the bridge",
                record.name,
            )
            return []
        try:
            raw = await client.list_tools()
        except Exception:
            logger.warning(
                "AD-1019c: list_tools failed for MCP server %s; treating as no "
                "tools (honest-degrade)",
                record.name,
                exc_info=True,
            )
            return []
        # BF-757: ``name`` and ``description`` are remote input too. A tool with
        # a non-string/empty name is dropped -- its id would be ``mcp:srv:{}``,
        # which nothing can invoke -- rather than offered and left to fail.
        out: list[dict[str, Any]] = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if not isinstance(name, str) or not name:
                logger.warning(
                    "BF-757: MCP server %s advertises a tool with a %s name; "
                    "skipping it (nothing could invoke it)",
                    record.name, type(t.get("name")).__name__,
                )
                continue
            out.append({
                "name": name,
                "description": _safe_description(t.get("description")),
                "input_schema": _safe_input_schema(
                    t.get("inputSchema"), record.name, name
                ),
            })
        return out

    def _effective_risk(
        self, record: "McpServerRecord", tool_name: str
    ) -> McpToolRisk:
        """Effective tier for a tool (DD-4 coerce of default + per-tool override)."""
        server_default = _coerce_risk(record.default_risk)
        override: McpToolRisk | None = None
        if self._risk_store is not None:
            override = self._risk_store.get_risk_sync(record.id, tool_name)
        return resolve_tool_risk(server_default, override)

    # ---- find / pull (DD-2 + DD-3) ------------------------------------

    async def find_mcp_tool(
        self, agent_id: str, concept: str, *, k: int = 8
    ) -> list[dict[str, Any]]:
        """Active search: ranked authorized MCP tools matching ``concept`` (DD-2).

        Enumerates every enabled server's live tools, scopes the candidate set to
        the agent's AD-1019b authorization (``resolve_mcp_access``), then ranks by
        AD-979c Reciprocal Rank Fusion over a name-token axis and a full-text axis
        (name + description). Deterministic, per-call, per-agent-scoped — mirrors
        ``CapabilityRetriever.find_intents``'s internals without its
        ``IntentDescriptor`` dependency. An empty query or no match returns ``[]``.

        Each result is ``{server, tool, description, risk}``.
        """
        query_tokens = _tokenize(concept)
        if not query_tokens or self._server_store is None:
            return []

        grants, dept_grants = self._access.grants(agent_id)

        # Build the authorized candidate set, keyed by a composite id.
        candidates: dict[str, dict[str, Any]] = {}
        name_tokens: dict[str, set[str]] = {}
        full_tokens: dict[str, set[str]] = {}
        for record in self._server_store.list_sync():
            if not record.enabled:
                continue
            for tool in await self._enumerate_tools(record):
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                enabled, _source = resolve_mcp_access(
                    grants, record.name, tool_name, department_grants=dept_grants
                )
                if not enabled:
                    continue
                cid = f"{record.name}:{tool_name}"
                description = tool.get("description", "")
                candidates[cid] = {
                    "server": record.name,
                    "tool": tool_name,
                    "description": description,
                    "risk": self._effective_risk(record, tool_name).value,
                }
                name_tokens[cid] = _tokenize(tool_name)
                full_tokens[cid] = _tokenize(f"{tool_name} {description}")

        if not candidates:
            return []

        def _rank(token_map: dict[str, set[str]]) -> list[str]:
            scored: list[tuple[str, int]] = []
            for cid in candidates:
                overlap = len(query_tokens & token_map.get(cid, set()))
                if overlap > 0:
                    scored.append((cid, overlap))
            scored.sort(key=lambda kv: (-kv[1], kv[0]))
            return [cid for cid, _ in scored]

        rankings = [r for r in (_rank(name_tokens), _rank(full_tokens)) if r]
        if not rankings:
            return []
        fused = reciprocal_rank_fusion(rankings)
        return [candidates[cid] for cid, _score in fused[:k]]

    async def pull_tool(
        self,
        agent_id: str,
        server_name: str,
        tool_name: str,
        *,
        descriptor: dict[str, Any] | None = None,
    ) -> bool:
        """Pull one authorized tool onto the workbench — register it warm (DD-3).

        Validates the agent's AD-1019b authorization, confirms the server
        actually exposes the tool, then registers a :class:`_McpTool` adapter in
        the ``ToolRegistry`` keyed ``mcp:{server}:{tool}`` and tracks it for the
        idle reaper. Idempotent: a re-pull refreshes ``last_used``. Returns
        ``True`` when warm; offering and invocation still require fresh checks.

        BF-754: ``descriptor`` lets a caller that has ALREADY enumerated the
        server hand the entry straight in. Without it this re-enumerated per
        pull, so a preload of N tools from S servers cost S+N ``tools/list``
        round trips every agentic turn -- 25 for one server at the default
        limit. The descriptor is still authorization-checked above.
        """
        record = self._access.record_by_name(server_name)
        if record is None or not record.enabled:
            return False
        if not self._access.is_authorized(agent_id, server_name, tool_name):
            logger.info(
                "AD-1019c: pull_tool denied — agent %s not authorized for %s/%s",
                agent_id[:12] or "?",
                server_name,
                tool_name,
            )
            return False

        match = descriptor
        if match is None:
            tools = await self._enumerate_tools(record)
            if not self._access.can_invoke_tool(agent_id, server_name, tool_name):
                logger.info(
                    "AD-1241: MCP server/access state changed while enumerating "
                    "%s/%s for agent %s; declining the pull",
                    server_name, tool_name, agent_id[:12] or "?",
                )
                return False
            match = next((t for t in tools if t.get("name") == tool_name), None)
        if match is None:
            logger.info(
                "AD-1019c: pull_tool — server %s does not expose tool %s",
                server_name,
                tool_name,
            )
            return False

        tool_id = f"mcp:{server_name}:{tool_name}"
        registration = self._registry.get(tool_id)
        if registration is not None and not registration.enabled:
            logger.info(
                "AD-1241: MCP adapter %s is disabled; declining the pull "
                "without changing its registration",
                tool_id,
            )
            return False
        if tool_id in self._pulled and registration is not None:
            self._pulled[tool_id].last_used = time.monotonic()
            return True

        adapter = _McpTool(
            bridge=self._bridge,
            server_url=self._bridge_key(record),
            server_name=server_name,
            server_id=record.id,
            tool_name=tool_name,
            name=match.get("name", tool_name),
            description=match.get("description", ""),
            # BF-754: the tool's real contract, not a bare object. Bounded and
            # validated at enumeration; a server that advertises nothing usable
            # still yields {"type": "object"} so the tool stays callable.
            input_schema=match.get("input_schema") or {"type": "object"},
            server_default_risk=record.default_risk,
            risk_store=self._risk_store,
            consensus_invoke=self._consensus_invoke,
            authorize=lambda aid, s=server_name, t=tool_name: self._access.can_invoke_tool(
                aid, s, t
            ),
            episode_writer=self._episode_writer,
            touch=lambda tid=tool_id: self._touch(tid),
        )
        self._registry.register(adapter, provider="AD-1019c", tags=[tool_id, "mcp"])
        self._pulled[tool_id] = _PulledEntry(
            tool_id=tool_id,
            server_name=server_name,
            tool_name=tool_name,
            last_used=time.monotonic(),
        )
        logger.info("AD-1019c: pulled MCP tool %s onto the workbench", tool_id)
        return True

    async def preload_open_tools(
        self, agent_id: str, *, limit: int
    ) -> list[str]:
        """AD-1239: pull the agent's OPEN-risk authorized tools so they are
        offered BY NAME, not only behind the ``find_mcp_tool`` search hop.

        A search tool is not a capability an agent can see. Offered only
        ``find_mcp_tool`` — "search for an MCP tool by what you want to do" — a
        counselor asked a documentation question reached for the browser
        instead, which advertises a concrete action vocabulary and reads like a
        thing that does something. The docs server was connected and authorized
        the whole time. Naming its tools is what makes MCP the obvious path.

        Only ``OPEN``-risk tools are preloaded. Making a CONFIRM/CONSENSUS tool
        invocable stays a deliberate act, and the search hop is what makes it
        deliberate — so this widens *discoverability*, never authorization.

        Deterministically ordered (server name, then tool name) and truncated to
        ``limit`` so the offered set is stable turn to turn; an agent that saw a
        tool last turn does not lose it to dict ordering this turn. ``limit <=
        0`` preloads nothing. Never raises — a server that cannot be enumerated
        contributes no tools.

        Cost, stated rather than inherited: this runs once per agentic turn and
        makes one live ``tools/list`` round-trip per enabled server. That is the
        same per-call cost ``find_mcp_tool`` has always paid, now on a warmer
        path — tens to a few hundred milliseconds against a turn already
        dominated by an LLM call. Deliberately NOT cached: a cache would mean a
        newly-added tool stays invisible for its TTL, and an agent being unable
        to see a tool the operator just connected is the failure this AD exists
        to end. Revisit if a vessel runs enough servers for the sum to matter.
        """
        if limit <= 0 or self._server_store is None:
            # BF-751a: INFO, not debug. This shipped as debug and the live vessel
            # runs at INFO, so "no third silent outcome" was not actually met --
            # a run that offered nothing still gave no reason why.
            logger.info(
                "AD-1239: offering no MCP tools by name to %s (limit=%d, "
                "server_store_wired=%s)",
                agent_id[:12] or "?", limit, self._server_store is not None,
            )
            return []

        grants, dept_grants = self._access.grants(agent_id)
        candidates: list[tuple[str, str, dict[str, Any]]] = []
        # BF-751a: counted so a zero-candidate result can name its own cause
        # instead of being indistinguishable from "no servers configured".
        servers_enabled = 0
        tools_seen = 0
        unauthorized = 0
        not_open = 0
        for record in self._server_store.list_sync():
            if not record.enabled:
                continue
            servers_enabled += 1
            for tool in await self._enumerate_tools(record):
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                tools_seen += 1
                enabled, _source = resolve_mcp_access(
                    grants, record.name, tool_name, department_grants=dept_grants
                )
                if not enabled:
                    unauthorized += 1
                    continue
                if self._effective_risk(record, tool_name) is not McpToolRisk.OPEN:
                    not_open += 1
                    continue
                # BF-754: carry the descriptor so pull_tool need not re-enumerate.
                candidates.append((record.name, tool_name, tool))

        pulled: list[str] = []
        for server_name, tool_name, descriptor in sorted(
            candidates, key=lambda c: (c[0], c[1])
        )[:limit]:
            if await self.pull_tool(
                agent_id, server_name, tool_name, descriptor=descriptor
            ):
                pulled.append(f"mcp:{server_name}:{tool_name}")
        if pulled:
            logger.info(
                "AD-1239: offered agent %s %d MCP tool(s) by name (%d OPEN-risk "
                "authorized candidate(s), limit %d) for consideration; publication "
                "still requires fresh access and definition checks",
                agent_id[:12] or "?", len(pulled), len(candidates), limit,
            )
        elif candidates:
            # BF-751: candidates that all failed to pull is an anomaly worth
            # hearing about — silence here is what made the live failure look
            # like "the agent ignored MCP" rather than "MCP was unreachable".
            logger.warning(
                "AD-1239: %d authorized OPEN-risk MCP tool(s) matched for agent "
                "%s but none could be pulled onto the workbench; the agent will "
                "not be offered them",
                len(candidates), agent_id[:12] or "?",
            )
        else:
            # BF-751a: name the cause. A ship with no MCP servers stays quiet;
            # one WITH servers that offered nothing has to say which filter ate
            # them, or diagnosing it costs a restart and a guess.
            log = logger.info if servers_enabled else logger.debug
            log(
                "AD-1239: offered agent %s no MCP tools by name — %d enabled "
                "server(s), %d tool(s) enumerated, %d unauthorized, %d not "
                "OPEN-risk. Zero tools enumerated from a live server usually "
                "means egress or transport; unauthorized means no grant "
                "reaches this agent.",
                agent_id[:12] or "?", servers_enabled, tools_seen,
                unauthorized, not_open,
            )
        return pulled

    def _touch(self, tool_id: str) -> None:
        entry = self._pulled.get(tool_id)
        if entry is not None:
            entry.last_used = time.monotonic()

    # ---- dispatch integration -----------------------------------------

    def register_search_tool(self) -> str:
        """Register the ``find_mcp_tool`` search Tool idempotently; return its id."""
        if self._registry.get(_FIND_MCP_TOOL_ID) is None:
            self._registry.register(
                _FindMcpToolTool(self),
                provider="AD-1019c",
                tags=[_FIND_MCP_TOOL_ID, "mcp"],
            )
        return _FIND_MCP_TOOL_ID

    async def create_dispatch_offer(
        self, agent_id: str, *, preload_limit: int
    ) -> MCPDispatchOffer:
        """Create a fresh run's offer from its own bounded OPEN-risk preload.

        Normalize the existing preload count to nonnegative P; adapter capacity
        is max(24, P). P=0 skips automatic preload even on a warm workbench,
        while leaving 24 discovery slots. The executor alone puts this value
        under MCP_DISPATCH_OFFER_CONTEXT_KEY in its invocation context.
        """
        if type(agent_id) is not str or not agent_id:
            raise ValueError("MCP dispatch offer requires a non-empty agent ID")
        if type(preload_limit) is not int:
            raise TypeError("MCP dispatch preload limit must be an integer")
        normalized_limit = max(0, preload_limit)
        preloaded_ids = await self.preload_open_tools(agent_id, limit=normalized_limit)
        offer = MCPDispatchOffer(
            self, agent_id,
            preload_limit=normalized_limit,
            preloaded_ids=preloaded_ids,
        )
        logger.debug(
            "AD-1241: created agent %s's run-local MCP offer with %d preload "
            "members and capacity %d; other warm adapters remain discoverable",
            agent_id[:12], len(offer.selected_ids), offer.capacity,
        )
        return offer

    def accepts_dispatch_offer(self, offer: MCPDispatchOffer, agent_id: str) -> bool:
        """Check concrete source ownership and the executor's exact agent identity."""
        return type(offer) is MCPDispatchOffer and offer.belongs_to(self, agent_id)

    def dispatch_tool_ids(
        self, agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        """Offer search plus authorized warm adapters, or the supplied candidates."""
        return self._access.dispatch_tool_ids(
            agent_id,
            pulled=MappingProxyType(self._pulled),
            register_search_tool=self.register_search_tool,
            candidate_ids=candidate_ids,
        )

    # ---- idle-adapter source (consumed by McpWorkbenchReaper) ----------

    def idle_tool_ids(self, ttl_seconds: float) -> list[str]:
        """Warm adapters idle longer than ``ttl_seconds`` (the reaper's input)."""
        now = time.monotonic()
        return [
            tid
            for tid, entry in self._pulled.items()
            if (now - entry.last_used) > ttl_seconds
        ]

    async def unload_tool(self, tool_id: str) -> None:
        """Unload one warm adapter back to the toolbox (unregister + untrack)."""
        self._registry.unregister(tool_id)
        self._pulled.pop(tool_id, None)
        logger.info("AD-1019c: unloaded idle MCP tool %s from the workbench", tool_id)

    @property
    def pulled_count(self) -> int:
        """Number of adapters currently warm on the workbench."""
        return len(self._pulled)

    @property
    def enabled_server_names(self) -> list[str]:
        """Names of currently connected, enabled MCP servers (AD-1239)."""
        return self._access.enabled_server_names


class _FindMcpToolTool:
    """The ``find_mcp_tool`` active-search Tool (AD-1019c DD-2).

    Search authorized tools and pull matches onto the workbench. Bounded-run
    matches are successful authorized pulls admitted for next-offer consideration,
    not guarantees of publication, provider acceptance or later invocation.
    """

    def __init__(self, workbench: MCPWorkbench) -> None:
        self._workbench = workbench

    @property
    def tool_id(self) -> str:
        return _FIND_MCP_TOOL_ID

    @property
    def name(self) -> str:
        return "Find MCP Tool"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        # AD-1239: name the connected servers and lead with retrieval. The
        # previous text -- "search for an MCP tool by what you want to do (e.g.
        # 'create a github issue')" -- described an abstract search whose only
        # example was an ACTION, so an agent with a QUESTION did not recognise
        # itself in it and reached for the browser instead.
        servers = self._workbench.enabled_server_names
        connected = (
            f" Servers connected: {', '.join(servers)}." if servers else ""
        )
        return (
            "Find a tool from a connected MCP server -- these are the preferred "
            "way to look things up, because they return structured data from an "
            "authoritative source instead of a page you have to read. Search by "
            "what you need, whether that is a lookup ('search the Microsoft "
            "documentation', 'read a docs page') or an action ('create a github "
            "issue')." + connected + " In bounded runs, returned matches are "
            "successful, currently authorized pulls admitted for next-offer "
            "consideration. Fresh access, server availability, registration and "
            "definition checks can still withdraw them before publication; "
            "invocation independently rechecks current authority."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        agent_id = str((context or {}).get("agent_id", ""))
        # AD-1179: ``query`` only. This used to accept an undeclared ``concept``
        # alias beside it -- a key the schema never named, so no caller could
        # know it existed and no drift guard could see it. An undocumented
        # accepted key is the same defect as an undeclared required one, one
        # direction over. Enumerated before removal: nothing in ``src/`` sends
        # ``concept`` to this tool (``codebase_query`` declares its own).
        #
        # Refuse an unknown key by name rather than ignoring it and searching
        # with whatever ``query`` happened to hold. The accepted set is read
        # from ``input_schema`` itself (slice 2) rather than restated here: a
        # hand-written copy beside the schema is the drift shape this AD exists
        # to remove. It is also stated generally rather than naming the retired
        # ``concept`` alias, because reading a key in order to reject it is
        # still reading a key the schema never declared -- G3 flags that,
        # correctly, and a rule that only knows one retired name would not
        # catch the next one.
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        query = str((params or {}).get("query") or "")
        if not query:
            # Never search for "" and return an empty match list inside a
            # success envelope -- that is indistinguishable from "the mesh has
            # no such tool", so a caller reads a wrong answer as a true one.
            return ToolResult(
                output=None,
                error="find_mcp_tool requires a non-empty 'query'.",
            )
        offer: MCPDispatchOffer | None = None
        if context is not None and MCP_DISPATCH_OFFER_CONTEXT_KEY in context:
            candidate = (
                context[MCP_DISPATCH_OFFER_CONTEXT_KEY]
                if type(context) is dict else None
            )
            if (
                type(candidate) is not MCPDispatchOffer
                or type(context.get("agent_id")) is not str
                or not candidate.belongs_to(self._workbench, agent_id)
            ):
                return ToolResult(
                    output=None,
                    error="find_mcp_tool received an invalid dispatch offer.",
                )
            offer = candidate
        matches = await self._workbench.find_mcp_tool(agent_id, query)
        if offer is None:
            for match in matches:
                await self._workbench.pull_tool(agent_id, match["server"], match["tool"])
            return ToolResult(output={"matches": matches})

        admitted: list[dict[str, Any]] = []
        deferred_count = 0
        failed_count = 0
        for match in matches:
            try:
                pulled = await self._workbench.pull_tool(
                    agent_id, match["server"], match["tool"]
                )
            except Exception:
                failed_count += 1
                logger.warning(
                    "AD-1241: discovery pull of %s/%s failed for agent %s; "
                    "omitting it from admitted matches and continuing ranked admission",
                    match["server"], match["tool"], agent_id[:12], exc_info=True,
                )
                continue
            if not pulled:
                failed_count += 1
                continue
            if offer.admit(f"mcp:{match['server']}:{match['tool']}"):
                admitted.append(match)
            else:
                deferred_count += 1
        return ToolResult(output={
            "matches": admitted,
            "capacity_deferred_count": deferred_count,
            "failed_pull_count": failed_count,
        })
