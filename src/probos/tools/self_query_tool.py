"""AD-1258: First-person telemetry through the governed tool interface."""

from __future__ import annotations

import logging
from typing import Any, Final, Protocol

from probos.tools.protocol import (
    ToolResult, ToolResultPresentation, ToolType, refuse_undeclared_params,
)

logger = logging.getLogger(__name__)

SELF_QUERY_DOMAINS: Final[tuple[str, ...]] = (
    "memory", "trust", "cognitive", "temporal", "social",
)
SELF_QUERY_OPTIONAL_DOMAINS: Final[tuple[str, ...]] = ("wellness", "authority")


class SelfQueryTelemetry(Protocol):
    """The existing telemetry reads and renderer needed by self_query."""

    async def get_memory_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_trust_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_cognitive_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_temporal_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_social_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_wellness_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_authority_state(self, agent_id: str) -> dict[str, Any]: ...

    async def get_full_snapshot(
        self, agent_id: str, *, extra_domains: tuple[str, ...] = (),
    ) -> dict[str, Any]: ...

    @staticmethod
    def render_telemetry_context(snapshot: dict[str, Any]) -> str: ...


def _fit_optional_output(
    output: dict[str, Any], telemetry: SelfQueryTelemetry,
    presentation: ToolResultPresentation | None,
) -> ToolResult:
    from probos.cognitive.decomposer import is_capability_gap
    from probos.cognitive.self_telemetry_domains import (
        filter_optional_domains, prune_optional_entry,
    )
    from probos.cognitive.swe_harness.tool_call import render_tool_output

    try:
        snapshot = filter_optional_domains(output["domains"])
        output["domains"] = snapshot
        entries = sum(
            len(snapshot.get(domain, {}).get(key, []))
            for domain, key in (
                ("authority", "held"), ("authority", "withheld"),
                ("wellness", "concerns"),
            )
        )
        for _ in range(entries + 1):
            output["rendered"] = telemetry.render_telemetry_context(snapshot)
            plain = render_tool_output(output, max_chars=0)
            if not plain:
                raise ValueError("Invalid telemetry rendering")
            if is_capability_gap(plain):
                raise ValueError("Unsafe telemetry presentation")
            if len(plain) <= 6000:
                admitted = plain if presentation is None else presentation.render_complete(output)
                if (
                    type(admitted) is str
                    and len(admitted) <= 6000
                    and not is_capability_gap(admitted)
                    and admitted == plain
                ):
                    return ToolResult(output=output)
                if admitted is not None:
                    raise ValueError("Invalid telemetry presentation admission")
            if not prune_optional_entry(snapshot):
                break
    except Exception:
        logger.warning(
            "self_query presentation check failed; complete delivery is unverified, "
            "returning an error without telemetry payloads"
        )
        return ToolResult(error="self_query: presentation check failed.")
    return ToolResult(error="self_query: result exceeds the presentation budget.")


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
            "domains for the five operational domains. Explicitly select wellness "
            "to read the Counselor's latest stored assessment of you. Select authority "
            "to read your own effective permissions and escalation route before "
            "reporting a task boundary."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domains": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(SELF_QUERY_DOMAINS + SELF_QUERY_OPTIONAL_DOMAINS),
                    },
                    "description": (
                        "Telemetry domains to read; omit for five operational domains. "
                        "Wellness and authority require explicit selection."
                    ),
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
        supported = SELF_QUERY_DOMAINS + SELF_QUERY_OPTIONAL_DOMAINS
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
                domain for domain in supported if domain in requested
            )
            unknown_domains = list(dict.fromkeys(
                domain for domain in requested if domain not in supported
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

        optional = any(domain in SELF_QUERY_OPTIONAL_DOMAINS for domain in selected)
        presentation = None
        if optional and "_tool_result_presentation" in context:
            presentation = context["_tool_result_presentation"]
            if type(presentation) is not ToolResultPresentation or not callable(
                presentation.render_complete,
            ):
                return ToolResult(error="self_query: presentation check failed.")

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
                snapshot = {
                    domain: await getattr(telemetry, f"get_{domain}_state")(agent_id)
                    for domain in selected
                }
            snapshot = dict(snapshot)
            social = snapshot.get("social")
            if isinstance(social, dict):
                snapshot["social"] = {
                    key: value
                    for key, value in social.items()
                    if key in ("routing_affinities", "interaction_breadth")
                }
            rendered = "" if optional else telemetry.render_telemetry_context(snapshot)
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
        if optional:
            return _fit_optional_output(output, telemetry, presentation)
        return ToolResult(output=output)