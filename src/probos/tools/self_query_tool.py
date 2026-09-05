"""AD-1258: First-person telemetry through the governed tool interface."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final, Protocol

from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params

logger = logging.getLogger(__name__)

SELF_QUERY_DOMAINS: Final[tuple[str, ...]] = (
    "memory", "trust", "cognitive", "temporal", "social",
)


class SelfQueryTelemetry(Protocol):
    """The existing telemetry reads and renderer needed by self_query."""

    async def get_memory_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_cognitive_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_social_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_full_snapshot(self, agent_id: str) -> dict[str, Any]: ...

    @staticmethod
    def render_telemetry_context(snapshot: dict[str, Any]) -> str: ...


class SelfQueryTool:
    """Read telemetry for the invocation context's exact agent identity."""

    def __init__(self, *, telemetry: SelfQueryTelemetry | None) -> None:
        self._telemetry = telemetry

    @property
    def tool_id(self) -> str:
        return "self_query"

    @property
    def name(self) -> str:
        return "Self Query"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Read your own current telemetry before describing yourself or your "
            "capabilities. Ground first-person claims in the returned metrics. "
            f"Select domains from {', '.join(SELF_QUERY_DOMAINS)}, or omit "
            "domains for a full snapshot."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domains": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(SELF_QUERY_DOMAINS)},
                    "description": "Telemetry domains to read; omit for all domains.",
                },
            },
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "domains": {"type": "object"},
                "rendered": {"type": "string"},
                "unknown_domains": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["agent_id", "domains", "rendered", "unknown_domains"],
            "additionalProperties": False,
        }

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        if type(params) is not dict:
            return ToolResult(error="self_query: params must be an object.")
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        if type(context) is not dict:
            return ToolResult(
                error="self_query: context must be an object with an agent_id.",
            )
        agent_id = context.get("agent_id")
        if type(agent_id) is not str or not agent_id.strip():
            return ToolResult(
                error="self_query: context agent_id must be a nonempty string.",
            )

        selected = SELF_QUERY_DOMAINS
        unknown_domains: list[str] = []
        if "domains" in params:
            requested = params["domains"]
            if type(requested) is not list or any(
                type(domain) is not str for domain in requested
            ):
                return ToolResult(
                    error="self_query: domains must be an array of strings.",
                )
            selected = tuple(
                domain for domain in SELF_QUERY_DOMAINS if domain in requested
            )
            unknown_domains = list(dict.fromkeys(
                domain for domain in requested if domain not in SELF_QUERY_DOMAINS
            ))

        output: dict[str, Any] = {
            "agent_id": agent_id,
            "domains": {},
            "rendered": "",
            "unknown_domains": unknown_domains,
        }
        if not selected:
            return ToolResult(
                output=output,
                error="self_query: select at least one recognized domain.",
            )

        telemetry = self._telemetry
        if telemetry is None:
            logger.warning(
                "AD-1258: self_query telemetry service is unavailable; "
                "returning an error without reading telemetry",
            )
            return ToolResult(
                output=output,
                error="self_query: telemetry service unavailable.",
            )
        try:
            if selected == SELF_QUERY_DOMAINS:
                snapshot = await telemetry.get_full_snapshot(agent_id)
            else:
                getters: dict[str, Callable[[str], Awaitable[dict[str, Any]]]] = dict(
                    zip(SELF_QUERY_DOMAINS, (
                        telemetry.get_memory_state,
                        telemetry.get_trust_state,
                        telemetry.get_cognitive_state,
                        telemetry.get_temporal_state,
                        telemetry.get_social_state,
                    )),
                )
                snapshot = {
                    domain: await getters[domain](agent_id) for domain in selected
                }
            rendered = telemetry.render_telemetry_context(snapshot)
        except Exception:
            logger.warning(
                "AD-1258: self_query collection or rendering failed for domains "
                "%s; returning an error without telemetry payloads",
                selected,
            )
            return ToolResult(
                output=output,
                error="self_query: telemetry query failed.",
            )

        output["domains"] = snapshot
        output["rendered"] = rendered
        return ToolResult(output=output)