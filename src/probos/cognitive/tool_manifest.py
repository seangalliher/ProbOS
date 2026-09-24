"""AD-1189: deferred tool schemas for the agentic loop.

With ``agentic_tools.deferred_tool_schema_threshold_bytes`` above 0, a run
withholds each native tool definition whose wire encoding is larger than the
threshold. The withheld tools are listed, one line each, in the description of
the ``load_tools`` meta-tool. The model asks for the definitions it needs, and
the dispatch refresh seam (BF-755 / AD-1241) offers them in full from the next
model call, provided that rebuild succeeds and still assembles them. Listing
and query search reuse the AD-983d :class:`CapabilityRetriever` unmodified.

An offer is run-local: it is never inherited by a delegated child, and nothing
persists across runs or turns. It governs presentation only; invocation still
goes through the registry's permission chain.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, ClassVar

from probos.cognitive.capability_retriever import CapabilityRetriever
from probos.cognitive.swe_harness.tool_call import llm_function_name
from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params
from probos.types import IntentDescriptor

logger = logging.getLogger(__name__)

LOAD_TOOLS_ID = "load_tools"
TOOL_MANIFEST_OFFER_CONTEXT_KEY = "_tool_manifest_offer"
NEVER_DEFERRED_TOOL_IDS: frozenset[str] = frozenset({"read_owned_steps", LOAD_TOOLS_ID})

# A query describes a need, not a choice: loading more than three per query
# re-inflates the offer this mode exists to shrink. Names are chosen explicitly,
# so they are bounded only by the input limit below.
_QUERY_LOAD_LIMIT = 3
# Input validation that bounds the work of one call.
_NAMES_LIMIT = 64
_QUERY_CHARS_LIMIT = 200
_UNKNOWN_ECHO_LIMIT = 8
_UNKNOWN_ECHO_CHARS = 64

_LOAD_TOOLS_DESCRIPTION = (
    "Load the full definition of tools listed below, by name or by a short "
    "query describing what you need. A loaded tool joins your tool list from "
    "your next step; call it then, with the parameters its definition "
    "declares. Tools already in your tool list need no loading."
)
_MANIFEST_HEADER = "\n\nTools you can load:\n"
_ALL_LOADED = "\n\nEvery listed tool is already loaded."
_REQUEST_NOTE = (
    "Loaded definitions join your tool list from your next step; call a tool "
    "once its full definition appears there. Names in unknown match nothing "
    "offered to you in this run."
)
_NEEDS_INPUT_ERROR = "load_tools needs names or a query."
_NAMES_ERROR = f"names must be a list of at most {_NAMES_LIMIT} strings."
_QUERY_ERROR = f"query must be a string of at most {_QUERY_CHARS_LIMIT} characters."
_INVALID_OFFER_ERROR = "load_tools received an invalid tool manifest offer."


def definition_bytes(value: object) -> int | None:
    """Wire size of *value* as httpx 0.28 encodes a request body, or ``None``.

    ``None`` means the value cannot be encoded. The caller keeps such a
    definition in full: a size that cannot be measured is never a reason to
    withhold, and the failure is the provider request's to report.
    """
    try:
        return len(
            json.dumps(
                value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
    except Exception:
        return None


def _function_name(definition: Any) -> str:
    function = definition.get("function") if isinstance(definition, dict) else None
    name = function.get("name") if isinstance(function, dict) else None
    return name if isinstance(name, str) else ""


def definition_descriptor(definition: dict[str, Any]) -> IntentDescriptor:
    """Adapt a provider tool definition to the AD-983d catalog entry.

    Total over malformed input: a missing or odd key becomes an empty string or
    an empty dict, never an exception.
    """
    function = definition.get("function") if isinstance(definition, dict) else None
    if not isinstance(function, dict):
        function = {}
    name = function.get("name")
    description = function.get("description")
    parameters = function.get("parameters")
    properties = parameters.get("properties") if isinstance(parameters, dict) else None
    params: dict[str, str] = {}
    if isinstance(properties, dict):
        for key, spec in properties.items():
            text = spec.get("description") if isinstance(spec, dict) else None
            params[str(key)] = text if isinstance(text, str) else ""
    return IntentDescriptor(
        name=name if isinstance(name, str) else "",
        params=params,
        description=description if isinstance(description, str) else "",
        tier="domain",
    )


def _render_meta(
    template: dict[str, Any], retriever: CapabilityRetriever, loadable: set[str]
) -> dict[str, Any]:
    """A fresh copy of the meta definition whose description lists *loadable*."""
    meta = copy.deepcopy(template)
    function = meta["function"]
    base = function.get("description")
    base = base if isinstance(base, str) else ""
    lines = retriever.manifest(scope=loadable) if loadable else []
    if lines:
        function["description"] = base + _MANIFEST_HEADER + "\n".join(
            f"- {name}: {line}" for name, line in lines
        )
    else:
        function["description"] = base + _ALL_LOADED
    return meta


class ToolManifestOffer:
    """One run's deferred-schema state: presentation only, never authority.

    The withheld set is frozen at the first :meth:`present`, and no name joins
    it later. A name in it counts as withheld until it is presented in full, and
    only while the latest build still assembles it. :meth:`request` admits only
    such names, and :meth:`present` iterates only the definitions this run
    already assembled, so a load can never add a tool the run was not offered.
    """

    context_key: ClassVar[str] = TOOL_MANIFEST_OFFER_CONTEXT_KEY
    meta_tool_id: ClassVar[str] = LOAD_TOOLS_ID

    __slots__ = (
        "_agent_id", "_threshold", "_frozen", "_armed", "_withheld", "_retriever",
        "_meta_template", "_offer_bytes", "_presented", "_requested", "_last_offered",
        "_last_built",
    )

    def __init__(self, *, agent_id: str, threshold_bytes: int) -> None:
        if type(agent_id) is not str or not agent_id:
            raise ValueError("A tool manifest offer requires a non-empty agent ID")
        if type(threshold_bytes) is not int or threshold_bytes <= 0:
            raise ValueError("A tool manifest threshold must be a positive integer")
        self._agent_id = agent_id
        self._threshold = threshold_bytes
        self._frozen = False
        self._armed = False
        self._withheld: frozenset[str] = frozenset()
        self._retriever: CapabilityRetriever | None = None
        self._meta_template: dict[str, Any] | None = None
        self._offer_bytes: tuple[int, int] = (0, 0)
        self._presented: set[str] = set()
        self._requested: set[str] = set()
        self._last_offered: frozenset[str] = frozenset()
        self._last_built: frozenset[str] = frozenset()

    def belongs_to(self, agent_id: str) -> bool:
        """Whether this offer was created for *agent_id*."""
        return type(agent_id) is str and agent_id == self._agent_id

    def may_defer(self, tool_id: str) -> bool:
        """False for tools whose definition must always be offered in full."""
        return type(tool_id) is str and tool_id not in NEVER_DEFERRED_TOOL_IDS

    @property
    def armed(self) -> bool:
        """True once the first build withheld something and shrank the offer."""
        return self._armed

    @property
    def withheld_count(self) -> int:
        """Number of definitions frozen as withheld at the first build."""
        return len(self._withheld)

    @property
    def offer_bytes(self) -> tuple[int, int]:
        """``(full, presented)`` wire bytes of an armed first build, else ``(0, 0)``."""
        return self._offer_bytes

    def present(
        self, definitions: list[dict[str, Any]], *, keep_full: frozenset[str]
    ) -> list[dict[str, Any]]:
        """The definitions to offer this build, with the meta definition last.

        Kept definitions are the same objects, in input order. When the offer
        is not armed, the input is returned without the meta definition. Apart
        from the first-call freeze, this only records which names its input
        assembled and its output showed, for :meth:`commit_presentation`,
        :meth:`has_pending_loads`, :meth:`request` and :meth:`withhold_call`.
        """
        meta: dict[str, Any] | None = None
        offered: list[dict[str, Any]] = []
        for definition in definitions:
            if _function_name(definition) == LOAD_TOOLS_ID:
                if meta is None:
                    meta = definition
                continue
            offered.append(definition)
        self._last_built = frozenset(_function_name(definition) for definition in offered)
        if not self._frozen:
            self._freeze(offered, meta, keep_full)
        if not self._armed or self._retriever is None or self._meta_template is None:
            return offered
        visible = self._presented | self._requested
        shown: list[dict[str, Any]] = []
        loadable: set[str] = set()
        for definition in offered:
            name = _function_name(definition)
            if name in self._withheld and name not in visible:
                loadable.add(name)
            else:
                shown.append(definition)
        self._last_offered = frozenset(
            _function_name(definition) for definition in shown
        ) | {LOAD_TOOLS_ID}
        shown.append(_render_meta(self._meta_template, self._retriever, loadable))
        return shown

    def _freeze(
        self,
        offered: list[dict[str, Any]],
        meta: dict[str, Any] | None,
        keep_full: frozenset[str],
    ) -> None:
        self._frozen = True
        if meta is None or not isinstance(meta.get("function"), dict):
            return
        withheld_definitions: list[dict[str, Any]] = []
        for definition in offered:
            name = _function_name(definition)
            if not name or name in keep_full:
                continue
            size = definition_bytes(definition)
            if size is not None and size > self._threshold:
                withheld_definitions.append(definition)
        if not withheld_definitions:
            return
        withheld = frozenset(_function_name(d) for d in withheld_definitions)
        retriever = CapabilityRetriever(
            [definition_descriptor(d) for d in withheld_definitions]
        )
        template = copy.deepcopy(meta)
        candidate = [d for d in offered if _function_name(d) not in withheld]
        candidate.append(_render_meta(template, retriever, set(withheld)))
        full = definition_bytes(offered)
        presented = definition_bytes(candidate)
        if full is None or presented is None or presented >= full:
            return
        self._withheld = withheld
        self._retriever = retriever
        self._meta_template = template
        self._offer_bytes = (full, presented)
        self._armed = True

    def commit_presentation(self) -> None:
        """Record the withheld names the last presented build showed in full."""
        self._presented |= self._last_offered & self._withheld

    def has_pending_loads(self) -> bool:
        """True while a requested definition the latest build assembles is not presented."""
        return bool((self._requested - self._presented) & self._last_built)

    def request(self, *, names: list[str] | None, query: str | None) -> dict[str, Any]:
        """Request withheld definitions the latest build assembles, by name or by query."""
        if names is not None and (
            type(names) is not list
            or len(names) > _NAMES_LIMIT
            or any(type(name) is not str for name in names)
        ):
            raise ValueError("load_tools names must be a bounded list of strings")
        if query is not None and (
            type(query) is not str or len(query) > _QUERY_CHARS_LIMIT
        ):
            raise ValueError("load_tools query must be a bounded string")
        loadable = (self._withheld & self._last_built) - self._presented
        requested: list[str] = []
        available: list[str] = []
        unknown: list[str] = []
        for name in dict.fromkeys(names or ()):
            if name in loadable:
                requested.append(name)
            elif name in self._last_offered:
                available.append(name)
            else:
                unknown.append(name)
        matched: list[str] = []
        if query and self._retriever is not None:
            matched = [
                descriptor.name
                for descriptor in self._retriever.find_intents(
                    query, scope=set(loadable), k=_QUERY_LOAD_LIMIT,
                )
            ]
        for name in matched:
            if name not in requested:
                requested.append(name)
        self._requested.update(requested)
        return {
            "requested": requested,
            "already_available": available,
            "unknown": [name[:_UNKNOWN_ECHO_CHARS] for name in unknown[:_UNKNOWN_ECHO_LIMIT]],
            "unknown_count": len(unknown),
            "query_matched": matched,
            "note": _REQUEST_NOTE,
        }

    def withhold_call(self, name: str) -> bool:
        """True, and request the definition, for a call to a still-withheld tool.

        A withheld name the latest build no longer assembles is not refused here:
        the executor resolves it as it resolves any name outside the offer.
        """
        if not self._armed or type(name) is not str:
            return False
        candidate = name if name in self._withheld else llm_function_name(name)
        if (
            candidate not in self._withheld
            or candidate in self._presented
            or candidate not in self._last_built
        ):
            return False
        self._requested.add(candidate)
        return True


class LoadToolsTool:
    """The ``load_tools`` meta-tool. Stateless: each run's offer is in its context."""

    @property
    def tool_id(self) -> str:
        return LOAD_TOOLS_ID

    @property
    def name(self) -> str:
        return LOAD_TOOLS_ID

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return _LOAD_TOOLS_DESCRIPTION

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "names": {"type": "array", "items": {"type": "string"}},
                "query": {"type": "string"},
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        run_context = context if type(context) is dict else {}
        offer = run_context.get(TOOL_MANIFEST_OFFER_CONTEXT_KEY)
        agent_id = run_context.get("agent_id")
        if (
            type(offer) is not ToolManifestOffer
            or type(agent_id) is not str
            or not offer.belongs_to(agent_id)
        ):
            return ToolResult(output=None, error=_INVALID_OFFER_ERROR)
        supplied = params if isinstance(params, dict) else {}
        names = supplied.get("names")
        query = supplied.get("query")
        if names is not None and (
            type(names) is not list
            or len(names) > _NAMES_LIMIT
            or any(type(name) is not str for name in names)
        ):
            return ToolResult(output=None, error=_NAMES_ERROR)
        if query is not None and (
            type(query) is not str or len(query) > _QUERY_CHARS_LIMIT
        ):
            return ToolResult(output=None, error=_QUERY_ERROR)
        names_given = bool(names)
        query_given = bool(query and query.strip())
        if not names_given and not query_given:
            return ToolResult(output=None, error=_NEEDS_INPUT_ERROR)
        return ToolResult(output=offer.request(
            names=names if names_given else None,
            query=query if query_given else None,
        ))


def is_load_tools_registration(registration: object) -> bool:
    """True when *registration* holds this module's ``load_tools`` meta-tool."""
    return type(getattr(registration, "tool", None)) is LoadToolsTool


def arm_tool_manifest(
    registry: Any, *, agent_id: str, threshold_bytes: int
) -> ToolManifestOffer | None:
    """Register ``load_tools`` idempotently and return a fresh run offer.

    ``None`` when another tool already holds the ``load_tools`` id: it is never
    adopted as the meta-tool, and the run offers every definition in full.
    """
    offer = ToolManifestOffer(agent_id=agent_id, threshold_bytes=threshold_bytes)
    existing = registry.get(LOAD_TOOLS_ID)
    if existing is None:
        registry.register(
            LoadToolsTool(), provider="AD-1189", tags=[LOAD_TOOLS_ID, "discovery"],
        )
    elif not is_load_tools_registration(existing):
        logger.warning(
            "AD-1189: tool id %r is registered by another provider (%r); agent %s "
            "is offered every definition in full this run rather than adopting "
            "that tool as the manifest meta-tool",
            LOAD_TOOLS_ID, getattr(existing, "provider", ""), agent_id,
        )
        return None
    return offer
