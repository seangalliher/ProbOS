"""AD-860: Adversarial verification + convergence gate for crew sub-tasks.

The crew fan-out executor (AD-859) drives a parent's child sub-tasks to
completion and collects a :class:`SubtaskResult` per child. Those results are
*unverified* — a single agent's self-asserted output. :class:`SubtaskVerifier`
is the semantic sibling of the deterministic ``RedTeamAgent``: instead of
re-executing tools, it runs an **independent** crew member as an LLM judge that
tries to *refute* the result against the sub-task's declared acceptance
criterion (``expected_output``), or — when no criterion was declared — against a
free-text "find the flaw" critique prompt (honest-degrade).

Independence is the point: the verifier agent MUST differ from the producer
agent (picked from :meth:`AgentRegistry.all` excluding the producer id). If no
independent agent is available, the result is honest-degraded to ``unverified``
with a logged reason — an agent is never allowed to verify itself.

Convergence: a refuted result is re-run through the **public** AD-859a
:class:`WorkItemAgenticExecutor` with the critique appended to the task text,
up to :attr:`AgenticDispatchConfig.max_convergence_rounds` (Safety Budget). A
still-refuted result after the last round is escalated as ``unverified`` — never
silently accepted.

Attribution maps each verdict to the real :class:`Vote` shape so AD-861 can
compute Shapley values. This module does NOT call ``compute_shapley_values``
(that is AD-861) and does NOT add a ``done -> in_progress`` duty transition
(re-run via the AD-859a executor is state-machine-independent).

BF-778: no path in this module writes verifier trust, and none should. ``verify()``
used to record each verdict against the :class:`TrustNetwork` at judgement time with
``success=verdict.accepted`` -- which paid a verifier to accept and penalised every
refusal, inverting the point of an adversarial layer. Whether a judgement was CORRECT
is not knowable when it is made; it becomes knowable only once a correction either
closes the gap the refusal named or fails to.

AD-1282 (BF-782, #1246): that resolution is observed and attributed OUTSIDE this
module, on the session path, because that is the only path that retains the round
history needed to see it. ``converge_for_session`` accumulates the rounds;
``crew_trust.derive_completed_crew_trust_effects`` credits a refusal that a later
round resolved; delivery is durable and idempotent through the crew trust outbox.
This module supplies the judgements and nothing else -- deliberately, so that a
verdict cannot be paid for at the moment it is made. See BF-783 (#1247) for the
remaining acceptance-incentive question.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from probos.tools.protocol import (
    ToolAccessGrant,
    ToolPermission,
    ToolRegistration,
    ToolResult,
    ToolType,
)
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.types import LLMRequest, Vote

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_executor import SubtaskResult
    from probos.cognitive.mcp_workbench import MCPDispatchOffer, MCPDispatchSource
    from probos.consensus.trust import TrustNetwork
    from probos.substrate.registry import AgentRegistry
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

# Convergence status constants — what the loop concluded for a sub-task.
_STATUS_CONVERGED = "converged"
_STATUS_UNVERIFIED = "unverified"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SESSION_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SESSION_RESULT_BYTES = 65_536
_MAX_SESSION_TASK_BYTES = 32_768
_MAX_SESSION_CRITIQUE_BYTES = 8_192
_MAX_SESSION_CRITIQUE_CODEPOINTS = 2_048
_MAX_SESSION_SUMMARY_CODEPOINTS = 4_096
_MAX_SESSION_TOKENS = 9_223_372_036_854_775_807
_MAX_SESSION_PROJECTION_SOURCE_TOOLS = 1_000
_MAX_SESSION_PROJECTED_TOOLS = 2_008
_MAX_SESSION_PROJECTION_SCHEMA_NODES = 4_096
_MAX_SESSION_PROJECTION_SCHEMA_BYTES = 262_144
_MAX_SESSION_PROJECTION_TAGS = 64
_MAX_SESSION_PROJECTION_DEFAULTS = 32
_SESSION_ARTIFACT_KEYS = {
    "artifact_id",
    "content_hash",
    "thread_id",
    "name",
    "mime",
    "size_bytes",
    "version",
}

SessionVerificationFailureCode = Literal[
    "independent_verifier_unavailable",
    "verification_defect",
    "correction_capability_denied",
    "correction_budget_exhausted",
    "correction_execution_defect",
    "convergence_exhausted",
]


def validate_session_denied_tools(value: Any) -> tuple[str, ...] | None:
    """Return one exact detached denied-tool tuple, or ``None`` when invalid."""
    if type(value) not in (list, tuple):
        return None
    if len(value) > 64:
        return None
    validated: list[str] = []
    for tool_id in value:
        if (
            type(tool_id) is not str
            or not tool_id
            or "\x00" in tool_id
            or len(tool_id) > 256
            or tool_id in validated
        ):
            return None
        try:
            if len(tool_id.encode("utf-8", errors="strict")) > 1_024:
                return None
        except (UnicodeEncodeError, UnicodeError):
            return None
        validated.append(tool_id)
    return tuple(validated)


_MISSING_VERDICT_FIELD = object()
"""Sentinel: distinguishes an absent ``accepted`` from a present ``False``."""


@dataclass
class VerificationVerdict:
    """The outcome of one adversarial verification pass over a sub-task result.

    ``accepted`` is the judge's decision (did the result survive refutation),
    ``confidence`` is the judge's self-reported confidence in ``[0, 1]``,
    ``critique`` is the human-readable flaw/justification (fed back into the
    convergence re-run on refusal), and ``verifier_agent_id`` is the independent
    agent that rendered the verdict (empty string when honest-degraded because
    no independent verifier was available).

    ``verification_defect`` marks a verdict that is refused because the
    VERIFICATION failed, not because the work did (BF-777): an unparseable
    reply, a non-bool ``accepted``, or an unavailable judge. Such a verdict
    still refuses -- the conservative direction -- but it is not evidence about
    the producer, so it must never be fed back as a convergence critique and
    never resolves into verifier trust. The session path already separates
    these as ``verification_defect``; this brings the legacy path in line.
    """

    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str
    verification_defect: bool = False


@dataclass
class ConvergenceOutcome:
    """The terminal result of the verify -> re-run -> re-verify loop.

    ``result`` is the (possibly re-run-updated) :class:`SubtaskResult`,
    ``verdict`` is the final verification verdict, ``status`` is one of
    ``converged`` / ``unverified``, and ``rounds`` is how many re-run rounds
    were spent (0 when the first verdict already accepted).
    """

    result: "SubtaskResult"
    verdict: VerificationVerdict
    status: str
    rounds: int = 0


@dataclass(frozen=True)
class SessionVerificationPass:
    status: Literal["accepted", "refuted", "unavailable", "malformed", "error"]
    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str
    tokens_used: int
    failure_code: SessionVerificationFailureCode | None


@dataclass(frozen=True)
class SessionVerificationRound:
    round_index: int
    result_revision: int
    result_text: str
    result_sha256: str
    result_summary: str
    stopped_reason: str
    correction_tokens: int
    verifier_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[dict[str, Any], ...]
    verdict: SessionVerificationPass


@dataclass(frozen=True)
class SessionCorrectionTerminalAttempt:
    attempt_index: int
    attempted_revision: int
    stopped_reason: str
    result_text: str
    result_sha256: str | None
    result_summary: str
    correction_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[dict[str, Any], ...]
    denied_tools: tuple[str, ...]
    failure_code: SessionVerificationFailureCode


@dataclass(frozen=True)
class SessionConvergenceOutcome:
    result: "SubtaskResult"
    accepted: bool
    status: str
    rounds_used: int
    failure_code: SessionVerificationFailureCode | None
    history: tuple[SessionVerificationRound, ...]
    terminal_attempt: SessionCorrectionTerminalAttempt | None


@dataclass(frozen=True, slots=True)
class _SessionExecutionConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class _SessionMcpConfig:
    agent_tools_enabled: bool


@dataclass(frozen=True, slots=True)
class _SessionAgenticToolsConfig:
    tool_search_enabled: bool
    delegation_enabled: bool
    delegation_max_depth: int
    delegation_max_iterations: int
    delegation_tier: str


@dataclass(frozen=True, slots=True)
class _SessionCorrectionConfig:
    execution: _SessionExecutionConfig
    mcp: _SessionMcpConfig
    agentic_tools: _SessionAgenticToolsConfig


@dataclass(frozen=True, slots=True)
class _SessionPermissionStore:
    source: Any
    agent_id: str
    discovery_grants: tuple[ToolAccessGrant, ...]

    def get_active_grants_sync(
        self,
        agent_id: str,
        tool_id: str | None = None,
    ) -> list[ToolAccessGrant]:
        if agent_id != self.agent_id:
            return []
        if tool_id is None:
            return [replace(grant) for grant in self.discovery_grants]
        normalized = _session_projection_tool_id(tool_id)
        if normalized is None or self.source is None:
            return [_session_permission_denial(agent_id, tool_id)]
        try:
            grants = _session_detach_active_grants(
                self.source.get_active_grants_sync(agent_id, normalized),
                agent_id=agent_id,
                expected_tool_id=normalized,
            )
        except Exception:
            return [_session_permission_denial(agent_id, normalized)]
        return [replace(grant) for grant in grants]


@dataclass(frozen=True, slots=True)
class _SessionIntentGrantStore:
    source: Any
    restricted_ids: frozenset[str]

    def resolve_sync(self, agent_id: str, intent_name: str) -> str:
        if intent_name in self.restricted_ids:
            return "no_opinion"
        if self.source is None:
            return "no_opinion"
        return self.source.resolve_sync(agent_id, intent_name)


@dataclass(frozen=True, slots=True)
class _SessionMcpToolIds:
    tool_ids: tuple[str, ...]
    agent_id: str = ""
    source: MCPDispatchSource | None = None
    synchronize: Callable[[Sequence[str]], list[str]] | None = None

    async def create_dispatch_offer(
        self, agent_id: str, *, preload_limit: int
    ) -> MCPDispatchOffer:
        """Return the original finder's offer without acquiring its ownership."""
        if type(agent_id) is not str or not agent_id or agent_id != self.agent_id:
            raise ValueError("session_correction_mcp_agent_invalid")
        if type(preload_limit) is not int:
            raise TypeError("MCP dispatch preload limit must be an integer")
        if self.source is None or self.synchronize is None:
            raise ValueError("session_correction_mcp_unavailable")
        if self.synchronize(("find_mcp_tool",)) != ["find_mcp_tool"]:
            raise ValueError("session_correction_mcp_unavailable")
        offer = await self.source.create_dispatch_offer(
            agent_id, preload_limit=preload_limit
        )
        if not self.accepts_dispatch_offer(offer, agent_id):
            raise ValueError("session_correction_mcp_offer_invalid")
        return offer

    def accepts_dispatch_offer(
        self, offer: MCPDispatchOffer, agent_id: str
    ) -> bool:
        """Require this projection's exact agent and the original source owner."""
        from probos.cognitive.mcp_workbench import MCPDispatchOffer

        return (
            type(offer) is MCPDispatchOffer
            and type(agent_id) is str
            and bool(agent_id)
            and agent_id == self.agent_id
            and self.source is not None
            and self.source.accepts_dispatch_offer(offer, agent_id)
        )

    def dispatch_tool_ids(
        self, agent_id: str, *, candidate_ids: Sequence[str] | None = None
    ) -> list[str]:
        """Keep the legacy snapshot, or synchronize only fresh source selections."""
        if candidate_ids is None:
            return list(self.tool_ids)
        candidates = _session_mcp_projection_ids(candidate_ids)
        if (
            type(agent_id) is not str
            or not agent_id
            or agent_id != self.agent_id
            or self.source is None
            or self.synchronize is None
        ):
            return []
        if self.synchronize(("find_mcp_tool",)) != ["find_mcp_tool"]:
            return []
        selected = self.source.dispatch_tool_ids(agent_id, candidate_ids=candidate_ids)
        if type(selected) is not list:
            raise ValueError("session_correction_mcp_selection_invalid")
        selected_ids = _session_mcp_projection_ids(selected)
        allowed = {"find_mcp_tool", *candidates}
        if any(tool_id not in allowed for tool_id in selected_ids):
            raise ValueError("session_correction_mcp_selection_invalid")
        return self.synchronize(selected_ids)


class _ProjectedToolDefinition:
    def __init__(
        self,
        *,
        tool_id: str,
        name: str,
        tool_type: ToolType,
        description: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description
        self._input_schema = input_schema
        self._output_schema = output_schema

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return dict(self._input_schema)

    @property
    def output_schema(self) -> dict[str, Any]:
        return dict(self._output_schema)

    async def invoke(
        self,
        _params: dict[str, Any],
        _context: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(error=f"Projected definition {self._tool_id} has no local executor")


class _SessionProjectedToolRegistry(ToolRegistry):
    def __init__(
        self,
        *,
        source_registry: Any,
        source_backed_ids: frozenset[str],
        explicit_denial_ids: frozenset[str],
    ) -> None:
        super().__init__()
        self._source_registry = source_registry
        self._source_backed_ids = source_backed_ids
        self._explicit_denial_ids = explicit_denial_ids

    def synchronize_mcp_definitions(self, tool_ids: Sequence[str]) -> list[str]:
        """Install bounded detached metadata for freshly selected source MCP IDs."""
        candidates = _session_mcp_projection_ids(tool_ids)
        definitions: dict[str, dict[str, Any]] = {}
        for tool_id in candidates:
            if tool_id in self._explicit_denial_ids:
                continue
            is_search = tool_id == "find_mcp_tool"
            parts = tool_id.split(":", 2)
            if not is_search and (
                len(parts) != 3 or parts[0] != "mcp" or not parts[1] or not parts[2]
            ):
                continue
            if is_search and tool_id not in self._source_backed_ids:
                continue
            current = self.get(tool_id)
            if current is not None and (
                tool_id not in self._source_backed_ids
                or not current.enabled
                or type(current.tool) is not _ProjectedToolDefinition
                or (not is_search and current.tool_type is not ToolType.MCP_SERVER)
            ):
                continue
            try:
                registration = self._source_registry.get(tool_id)
            except Exception:
                logger.warning(
                    "AD-1241: correction MCP metadata for %s could not be read; "
                    "leaving this definition unavailable without changing its source",
                    tool_id, exc_info=True,
                )
                continue
            definition = _session_projection_registration(registration)
            expected_type = ToolType.UTILITY_AGENT if is_search else ToolType.MCP_SERVER
            if (
                definition is None
                or definition["enabled"] is not True
                or definition["tool"].tool_id != tool_id
                or definition["tool"].tool_type is not expected_type
            ):
                continue
            definitions[tool_id] = definition

        new_source_ids = set(definitions).difference(self._source_backed_ids)
        new_definition_count = sum(self.get(tool_id) is None for tool_id in definitions)
        if (
            len(self._source_backed_ids) + len(new_source_ids)
            > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
            or self.count() + new_definition_count > _MAX_SESSION_PROJECTED_TOOLS
        ):
            logger.warning(
                "AD-1241: %d selected MCP definitions exceed correction projection "
                "limits; leaving the whole batch unoffered and the projection unchanged",
                len(definitions),
            )
            return []

        installed = 0
        for tool_id, definition in definitions.items():
            current_definition = _session_projection_registration(self.get(tool_id))
            unchanged = (
                current_definition is not None
                and all(
                    current_definition[key] == value
                    for key, value in definition.items() if key != "tool"
                )
                and all(
                    getattr(current_definition["tool"], attribute)
                    == getattr(definition["tool"], attribute)
                    for attribute in (
                        "tool_id", "name", "tool_type", "description",
                        "input_schema", "output_schema",
                    )
                )
            )
            if not unchanged:
                _session_register_projected_definition(self, definition)
                installed += 1
            self._source_backed_ids = self._source_backed_ids | {tool_id}
        logger.debug(
            "AD-1241: correction synchronized %d MCP definitions (%d installed, "
            "%d unavailable); invocation remains governed by the original registry",
            len(definitions), installed, len(candidates) - len(definitions),
        )
        return list(definitions)

    async def check_and_invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        *,
        required: ToolPermission = ToolPermission.READ,
        agent_department: str | None = None,
        agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        if tool_id in self._explicit_denial_ids:
            raise ToolPermissionDenied(
                agent_id,
                tool_id,
                required,
                ToolPermission.NONE,
                reason=f"Projected correction capability {tool_id} is unavailable",
            )
        if tool_id in self._source_backed_ids:
            return await self._source_registry.check_and_invoke(
                agent_id,
                tool_id,
                params,
                required=required,
                agent_department=agent_department,
                agent_rank=agent_rank,
                agent_types=agent_types,
                context=dict(context or {}),
            )
        return await super().check_and_invoke(
            agent_id,
            tool_id,
            params,
            required=required,
            agent_department=agent_department,
            agent_rank=agent_rank,
            agent_types=agent_types,
            context=dict(context or {}),
        )


@dataclass(frozen=True, slots=True)
class _SessionCorrectionRuntime:
    config: _SessionCorrectionConfig
    tool_registry: Any
    tool_permission_store: Any
    attachment_store: Any
    artifact_store: Any
    intent_bus: Any
    intent_grant_store: Any
    mcp_workbench: MCPDispatchSource | None
    cognitive_skill_catalog: Any
    emit_event: None = None
    event_emit_fn: None = None


@dataclass(frozen=True, slots=True)
class _NormalizedSessionCorrectionOutcome:
    valid: bool
    stopped_reason: Literal[
        "complete",
        "error",
        "max_iterations",
        "token_budget",
        "execution_exception",
    ]
    result_text: str
    correction_tokens: int
    tool_trace_ref: str | None
    artifact_refs: tuple[dict[str, Any], ...]
    denied_tools: tuple[str, ...]


def _session_projection_string(
    value: Any,
    *,
    maximum_codepoints: int,
    maximum_bytes: int,
    allow_empty: bool = True,
) -> str | None:
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or "\x00" in value
        or len(value) > maximum_codepoints
    ):
        return None
    try:
        if len(value.encode("utf-8", errors="strict")) > maximum_bytes:
            return None
    except UnicodeError:
        return None
    return value


def _session_projection_tool_id(value: Any) -> str | None:
    return _session_projection_string(
        value,
        maximum_codepoints=256,
        maximum_bytes=1_024,
        allow_empty=False,
    )


def _session_mcp_projection_ids(value: Sequence[str]) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
    ):
        raise ValueError("session_correction_mcp_selection_invalid")
    normalized: list[str] = []
    for tool_id in value:
        candidate = _session_projection_tool_id(tool_id)
        if candidate is None:
            raise ValueError("session_correction_mcp_selection_invalid")
        normalized.append(candidate)
    return tuple(dict.fromkeys(normalized))


def _session_detach_active_grants(
    value: Any,
    *,
    agent_id: str,
    expected_tool_id: str | None = None,
) -> tuple[ToolAccessGrant, ...]:
    if (
        type(value) is not list
        or len(value) > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
    ):
        raise ValueError("session_correction_projection_invalid")
    detached: list[ToolAccessGrant] = []
    for grant in value:
        try:
            tool_id = _session_projection_tool_id(grant.tool_id)
            if (
                type(grant) is not ToolAccessGrant
                or grant.agent_id != agent_id
                or tool_id is None
                or (
                    expected_tool_id is not None
                    and tool_id != expected_tool_id
                )
                or type(grant.permission) is not ToolPermission
                or type(grant.is_restriction) is not bool
                or type(grant.revoked) is not bool
                or grant.revoked
                or _session_projection_string(
                    grant.id,
                    maximum_codepoints=1_024,
                    maximum_bytes=1_024,
                ) is None
                or _session_projection_string(
                    grant.reason,
                    maximum_codepoints=32_768,
                    maximum_bytes=32_768,
                ) is None
                or _session_projection_string(
                    grant.issued_by,
                    maximum_codepoints=1_024,
                    maximum_bytes=1_024,
                ) is None
                or type(grant.issued_at) not in (int, float)
                or not math.isfinite(float(grant.issued_at))
                or (
                    grant.expires_at is not None
                    and (
                        type(grant.expires_at) not in (int, float)
                        or not math.isfinite(float(grant.expires_at))
                    )
                )
                or grant.revoked_at is not None
            ):
                raise ValueError("session_correction_projection_invalid")
            detached.append(replace(grant, tool_id=tool_id))
        except (AttributeError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("session_correction_projection_invalid") from exc
    return tuple(detached)


def _session_permission_denial(
    agent_id: str,
    tool_id: Any,
) -> ToolAccessGrant:
    safe_tool_id = (
        tool_id
        if _session_projection_tool_id(tool_id) is not None
        else "invalid_projected_tool"
    )
    return ToolAccessGrant(
        id="crew-session-live-permission-denial",
        agent_id=agent_id,
        tool_id=safe_tool_id,
        permission=ToolPermission.NONE,
        is_restriction=True,
        reason="Live correction permission could not be proven.",
        issued_by="crew_session_projection",
    )


def _session_projection_json_object(value: Any) -> dict[str, Any] | None:
    if type(value) is not dict:
        return None
    nodes = 0
    string_bytes = 0
    seen: set[int] = set()

    def _detach(current: Any, depth: int = 0) -> Any:
        nonlocal nodes, string_bytes
        nodes += 1
        if nodes > _MAX_SESSION_PROJECTION_SCHEMA_NODES or depth > 32:
            raise ValueError("session_projection_schema_invalid")
        if current is None or type(current) in (bool, int):
            return current
        if type(current) is float:
            if not math.isfinite(current):
                raise ValueError("session_projection_schema_invalid")
            return current
        if type(current) is str:
            detached_string = _session_projection_string(
                current,
                maximum_codepoints=_MAX_SESSION_PROJECTION_SCHEMA_BYTES,
                maximum_bytes=_MAX_SESSION_PROJECTION_SCHEMA_BYTES,
            )
            if detached_string is None:
                raise ValueError("session_projection_schema_invalid")
            encoded = detached_string.encode("utf-8", errors="strict")
            string_bytes += len(encoded)
            if string_bytes > _MAX_SESSION_PROJECTION_SCHEMA_BYTES:
                raise ValueError("session_projection_schema_invalid")
            return detached_string
        if type(current) not in (list, dict):
            raise ValueError("session_projection_schema_invalid")
        identity = id(current)
        if identity in seen:
            raise ValueError("session_projection_schema_invalid")
        seen.add(identity)
        if type(current) is list:
            return [_detach(item, depth + 1) for item in current]
        detached: dict[str, Any] = {}
        for key, item in current.items():
            if type(key) is not str:
                raise ValueError("session_projection_schema_invalid")
            detached_key = _detach(key, depth + 1)
            detached[detached_key] = _detach(item, depth + 1)
        return detached

    try:
        bounded = _detach(value)
        encoded = json.dumps(
            bounded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > _MAX_SESSION_PROJECTION_SCHEMA_BYTES:
            return None
        detached = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None
    return detached if type(detached) is dict else None


def _session_projection_registration(registration: Any) -> dict[str, Any] | None:
    try:
        if type(registration) is not ToolRegistration:
            return None
        tool = registration.tool
        tool_id = _session_projection_tool_id(tool.tool_id)
        name = _session_projection_string(
            tool.name,
            maximum_codepoints=256,
            maximum_bytes=1_024,
        )
        description = _session_projection_string(
            tool.description,
            maximum_codepoints=32_768,
            maximum_bytes=131_072,
        )
        tool_type = tool.tool_type
        input_schema = _session_projection_json_object(tool.input_schema)
        output_schema = _session_projection_json_object(tool.output_schema)
        domain = _session_projection_string(
            registration.domain,
            maximum_codepoints=256,
            maximum_bytes=1_024,
        )
        department = (
            None
            if registration.department is None
            else _session_projection_string(
                registration.department,
                maximum_codepoints=256,
                maximum_bytes=1_024,
            )
        )
        provider = _session_projection_string(
            registration.provider,
            maximum_codepoints=256,
            maximum_bytes=1_024,
        )
        if (
            type(registration.tags) is not list
            or len(registration.tags) > _MAX_SESSION_PROJECTION_TAGS
            or type(registration.default_permissions) is not dict
            or len(registration.default_permissions) > _MAX_SESSION_PROJECTION_DEFAULTS
            or (
                registration.restricted_to is not None
                and (
                    type(registration.restricted_to) is not list
                    or len(registration.restricted_to) > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
                )
            )
        ):
            return None
        tags = list(registration.tags)
        defaults = dict(registration.default_permissions)
        restricted_to = (
            None
            if registration.restricted_to is None
            else list(registration.restricted_to)
        )
        if (
            tool_id is None
            or name is None
            or description is None
            or not isinstance(tool_type, ToolType)
            or input_schema is None
            or output_schema is None
            or any(type(tag) is not str for tag in tags)
            or any(_session_projection_tool_id(tag) is None for tag in tags)
            or any(
                _session_projection_tool_id(key) is None
                or type(value) is not str
                or value not in {"none", "observe", "read", "write", "full"}
                for key, value in defaults.items()
            )
            or (
                restricted_to is not None
                and any(
                    _session_projection_tool_id(value) is None
                    for value in restricted_to
                )
            )
            or domain is None
            or (
                registration.department is not None
                and department is None
            )
            or provider is None
            or type(registration.enabled) is not bool
            or type(registration.concurrency) is not str
            or registration.concurrency not in {"concurrent", "exclusive"}
            or (
                registration.lock_timeout_seconds is not None
                and (
                    type(registration.lock_timeout_seconds) not in (int, float)
                    or not math.isfinite(float(registration.lock_timeout_seconds))
                    or float(registration.lock_timeout_seconds) <= 0.0
                )
            )
        ):
            return None
        return {
            "tool": _ProjectedToolDefinition(
                tool_id=tool_id,
                name=name,
                tool_type=tool_type,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
            ),
            "domain": domain,
            "department": department,
            "tags": tags,
            "provider": provider,
            "enabled": registration.enabled,
            "default_permissions": defaults,
            "restricted_to": restricted_to,
            "concurrency": registration.concurrency,
            "lock_timeout_seconds": registration.lock_timeout_seconds,
        }
    except Exception:
        return None


def _session_register_projected_definition(
    registry: ToolRegistry,
    definition: dict[str, Any],
) -> None:
    registry.register(
        definition["tool"],
        domain=definition["domain"],
        department=definition["department"],
        tags=definition["tags"],
        provider=definition["provider"],
        enabled=definition["enabled"],
        default_permissions=definition["default_permissions"],
        restricted_to=definition["restricted_to"],
        concurrency=definition["concurrency"],
        lock_timeout_seconds=definition["lock_timeout_seconds"],
    )


def _session_denied_definition(tool_id: str) -> dict[str, Any]:
    tool_type = (
        ToolType.MCP_SERVER
        if tool_id == "find_mcp_tool" or tool_id.startswith("mcp:")
        else ToolType.DETERMINISTIC_FUNCTION
    )
    return {
        "tool": _ProjectedToolDefinition(
            tool_id=tool_id,
            name=tool_id,
            tool_type=tool_type,
            description="Capability unavailable in event-neutral correction context.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        "domain": "*",
        "department": None,
        "tags": [tool_id],
        "provider": "crew_session_projection",
        "enabled": True,
        "default_permissions": {},
        "restricted_to": None,
        "concurrency": "concurrent",
        "lock_timeout_seconds": None,
    }


def _session_correction_runtime(
    runtime: Any,
    *,
    agent_id: str,
    department: str,
    rank: str,
) -> _SessionCorrectionRuntime:
    """Build one event-neutral governed capability projection for correction."""
    from probos.cognitive.agentic_dispatch import register_mesh_intent_tools

    del department, rank
    source_registry = getattr(runtime, "tool_registry", None)
    source_permissions = getattr(runtime, "tool_permission_store", None)
    if source_registry is None:
        source_registry = ToolRegistry()
    try:
        raw_grants = (
            source_permissions.get_active_grants_sync(agent_id)
            if source_permissions is not None
            else []
        )
        detached_grants = _session_detach_active_grants(
            raw_grants,
            agent_id=agent_id,
        )
    except Exception as exc:
        raise ValueError("session_correction_projection_invalid") from exc
    projected_permission_store = _SessionPermissionStore(
        source=source_permissions,
        agent_id=agent_id,
        discovery_grants=detached_grants,
    )

    config = getattr(runtime, "config", None)
    execution_cfg = getattr(config, "execution", None)
    mcp_cfg = getattr(config, "mcp", None)
    agentic_cfg = getattr(config, "agentic_tools", None)
    projected_config = _SessionCorrectionConfig(
        execution=_SessionExecutionConfig(
            enabled=getattr(execution_cfg, "enabled", False) is True,
        ),
        mcp=_SessionMcpConfig(
            agent_tools_enabled=getattr(mcp_cfg, "agent_tools_enabled", False) is True,
        ),
        agentic_tools=_SessionAgenticToolsConfig(
            tool_search_enabled=getattr(agentic_cfg, "tool_search_enabled", False) is True,
            delegation_enabled=getattr(agentic_cfg, "delegation_enabled", False) is True,
            delegation_max_depth=int(getattr(agentic_cfg, "delegation_max_depth", 1)),
            delegation_max_iterations=int(
                getattr(agentic_cfg, "delegation_max_iterations", 5)
            ),
            delegation_tier=str(getattr(agentic_cfg, "delegation_tier", "standard")),
        ),
    )

    selected: dict[str, list[str]] = {}

    def _source_registration(tool_id: Any) -> Any:
        normalized = _session_projection_tool_id(tool_id)
        if normalized is None:
            return None
        try:
            return source_registry.get(normalized)
        except Exception:
            return None

    def _select(tool_id: Any, representation: str) -> None:
        normalized = _session_projection_tool_id(tool_id)
        if normalized is None:
            raise ValueError("session_correction_projection_invalid")
        if (
            normalized not in selected
            and len(selected) >= _MAX_SESSION_PROJECTED_TOOLS
        ):
            raise ValueError("session_correction_projection_invalid")
        selected.setdefault(normalized, []).append(representation)

    for grant in detached_grants:
        if getattr(grant, "is_restriction", None) is False:
            reg = _source_registration(grant.tool_id)
            _select(
                grant.tool_id,
                (
                    "source"
                    if _session_projection_registration(reg) is not None
                    else "deny"
                ),
            )

    intent_policy = getattr(runtime, "intent_grant_store", None)
    restricted_mesh_ids: set[str] = set()
    intent_bus = getattr(runtime, "intent_bus", None)
    mesh_tool_ids: list[str] = []
    if intent_bus is not None:
        try:
            mesh_tool_ids = register_mesh_intent_tools(
                ToolRegistry(),
                intent_bus,
                provider="crew_session_projection_catalog",
            )[:_MAX_SESSION_PROJECTION_SOURCE_TOOLS]
        except Exception:
            mesh_tool_ids = []
    for tool_id in mesh_tool_ids:
        try:
            restricted = (
                intent_policy is not None
                and intent_policy.resolve_sync(agent_id, tool_id) == "restricted"
            )
        except Exception:
            restricted = True
        if restricted:
            restricted_mesh_ids.add(tool_id)
            _select(tool_id, "deny")
        else:
            reg = _source_registration(tool_id)
            source_available = _session_projection_registration(reg) is not None
            _select(
                tool_id,
                (
                    "source"
                    if source_available
                    else "mesh"
                ),
            )

    mcp_ids: list[str] = []
    workbench = getattr(runtime, "mcp_workbench", None)
    if projected_config.mcp.agent_tools_enabled:
        find_registration = _source_registration("find_mcp_tool")
        find_available = _session_projection_registration(find_registration) is not None
        mcp_ids = ["find_mcp_tool"]
        if find_available:
            try:
                raw_mcp_ids = workbench.dispatch_tool_ids(agent_id)
            except Exception as exc:
                raise ValueError("session_correction_projection_invalid") from exc
            if (
                type(raw_mcp_ids) is not list
                or len(raw_mcp_ids) > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
            ):
                raise ValueError("session_correction_projection_invalid")
            for tool_id in raw_mcp_ids:
                normalized = _session_projection_tool_id(tool_id)
                if normalized is None:
                    raise ValueError("session_correction_projection_invalid")
                mcp_ids.append(normalized)
        else:
            raw_mcp_ids = []
        if not find_available:
            try:
                registrations = source_registry.list_tools(enabled_only=True)
            except Exception as exc:
                raise ValueError("session_correction_projection_invalid") from exc
            if (
                type(registrations) is not list
                or len(registrations) > _MAX_SESSION_PROJECTION_SOURCE_TOOLS
            ):
                raise ValueError("session_correction_projection_invalid")
            for registration in registrations:
                try:
                    if type(registration) is not ToolRegistration:
                        raise ValueError("session_correction_projection_invalid")
                    if (
                        registration.tool_type is ToolType.MCP_SERVER
                        or "mcp" in registration.tags
                        or "mcp" in registration.provider.lower()
                    ):
                        normalized = _session_projection_tool_id(registration.tool_id)
                        if normalized is None:
                            raise ValueError("session_correction_projection_invalid")
                        mcp_ids.append(normalized)
                except (AttributeError, TypeError, ValueError, UnicodeError) as exc:
                    raise ValueError("session_correction_projection_invalid") from exc
        mcp_ids = list(dict.fromkeys(mcp_ids))
        for tool_id in mcp_ids:
            reg = _source_registration(tool_id)
            _select(
                tool_id,
                (
                    "source"
                    if find_available
                    and _session_projection_registration(reg) is not None
                    else "deny"
                ),
            )

    runtime_ids: list[str] = []
    if projected_config.execution.enabled:
        runtime_ids.append("run_python")
    if getattr(runtime, "cognitive_skill_catalog", None) is not None:
        runtime_ids.append("use_skill")
    if projected_config.agentic_tools.tool_search_enabled:
        runtime_ids.append("search_capabilities")
    if projected_config.agentic_tools.delegation_enabled:
        runtime_ids.append("delegate_task")
    for tool_id in runtime_ids:
        reg = _source_registration(tool_id)
        _select(
            tool_id,
            "source" if _session_projection_registration(reg) is not None else "deny",
        )

    source_definitions: dict[str, dict[str, Any]] = {}
    for tool_id, choices in selected.items():
        if "source" not in choices:
            continue
        definition = _session_projection_registration(
            _source_registration(tool_id),
        )
        if definition is None:
            choices[:] = [choice for choice in choices if choice != "source"]
            choices.append("deny")
        else:
            source_definitions[tool_id] = definition
    source_ids = frozenset(source_definitions)
    mesh_ids = frozenset(
        tool_id
        for tool_id, choices in selected.items()
        if "source" not in choices and "mesh" in choices
    )
    denied_ids = frozenset(
        tool_id
        for tool_id, choices in selected.items()
        if "source" not in choices and "mesh" not in choices
    )
    registry = _SessionProjectedToolRegistry(
        source_registry=source_registry,
        source_backed_ids=source_ids,
        explicit_denial_ids=denied_ids,
    )
    registry.set_permission_store(projected_permission_store)
    for tool_id in selected:
        if tool_id in mesh_ids:
            continue
        definition = (
            source_definitions.get(tool_id)
            if tool_id in source_ids
            else _session_denied_definition(tool_id)
        )
        if definition is not None:
            _session_register_projected_definition(registry, definition)
    if intent_bus is not None and mesh_ids:
        register_mesh_intent_tools(
            registry,
            intent_bus,
            provider="crew_session_projection",
        )
    return _SessionCorrectionRuntime(
        config=projected_config,
        tool_registry=registry,
        tool_permission_store=projected_permission_store,
        attachment_store=getattr(runtime, "attachment_store", None),
        artifact_store=getattr(runtime, "artifact_store", None),
        intent_bus=intent_bus,
        intent_grant_store=_SessionIntentGrantStore(
            source=intent_policy,
            restricted_ids=frozenset(restricted_mesh_ids),
        ),
        mcp_workbench=_SessionMcpToolIds(
            tuple(dict.fromkeys(mcp_ids)),
            agent_id=agent_id,
            source=workbench,
            synchronize=registry.synchronize_mcp_definitions,
        ),
        cognitive_skill_catalog=(
            object() if "use_skill" in selected else None
        ),
    )


class SubtaskVerifier:
    """Adversarially verify crew sub-task results and drive them to convergence.

    Constructor injection (Dependency Inversion): every collaborator is supplied
    by the caller so the verifier depends on abstractions, not concretions, and
    is trivially testable with fakes.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        work_item_store: "WorkItemStore",
        agent_registry: "AgentRegistry",
        trust_network: "TrustNetwork",
        agentic_executor: "WorkItemAgenticExecutor",
        runtime: Any,
        max_convergence_rounds: int = 2,
        ontology: Any = None,
    ) -> None:
        self._llm = llm_client
        self._store = work_item_store
        self._registry = agent_registry
        self._trust = trust_network
        self._executor = agentic_executor
        self._runtime = runtime
        self._max_rounds = max(1, int(max_convergence_rounds))
        # AD-866 (optional, Dependency Inversion): when wired, verifier selection
        # prefers a department peer or the producer's chief over a random
        # independent agent. Default ``None`` preserves the AD-860 any-independent
        # behavior verbatim for every existing call site.
        self._ontology = ontology

    # ------------------------------------------------------------------ public

    async def verify(self, result: "SubtaskResult") -> VerificationVerdict:
        """Run one adversarial verification pass over ``result``.

        Picks an independent verifier (different from the producer), resolves the
        declared acceptance criterion from the work item's metadata, asks the
        LLM judge to refute the result, and returns the
        :class:`VerificationVerdict`. Honest-degrades to an ``unverified``
        verdict (empty ``verifier_agent_id``) when no independent agent is
        available.

        BF-778: this writes NO trust. It used to record the verifier with
        ``success=verdict.accepted``, which paid it to accept.
        """
        verifier_id = self._pick_independent_verifier(result.agent_id)
        if verifier_id is None:
            logger.warning(
                "AD-860: no independent verifier available for sub-task %s "
                "(producer=%s); honest-degrading to unverified — an agent is "
                "never allowed to verify itself",
                result.work_item_id, result.agent_id,
            )
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique="No independent verifier available; result unverified.",
                verifier_agent_id="",
                verification_defect=True,
            )

        expected = await self._resolve_expected_output(result.work_item_id)
        request = LLMRequest(
            prompt=self._build_judge_prompt(result, expected),
            system_prompt=self._JUDGE_SYSTEM_PROMPT,
            tier="standard",
        )
        try:
            response = await self._llm.complete(request)
            verdict = self._parse_verdict(getattr(response, "content", ""), verifier_id)
        except Exception:
            logger.warning(
                "AD-860: LLM judge call failed for sub-task %s (verifier=%s); "
                "honest-degrading to refuted (unverified) — never silently "
                "accept an unjudged result",
                result.work_item_id, verifier_id, exc_info=True,
            )
            verdict = VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique="LLM judge unavailable; result could not be verified.",
                verifier_agent_id=verifier_id,
                verification_defect=True,
            )

        # BF-778: no trust write here. This used to record the VERIFIER with
        # success=verdict.accepted, which paid it to accept and penalised every
        # refusal -- exactly inverting what an adversarial layer is for. The
        # correctness of a judgement is not knowable at the moment it is made;
        # it becomes knowable when a correction either closes the gap the
        # refusal named or contradicts it. AD-1282: that resolution is attributed
        # on the session path, which is the only path that keeps the round
        # history -- `crew_trust.derive_completed_crew_trust_effects` credits a
        # refusal followed by a later round. `verify_for_session` has always had
        # this shape.
        return verdict

    async def converge(
        self,
        result: "SubtaskResult",
        *,
        instructions: str,
        task_text: str,
    ) -> ConvergenceOutcome:
        """Verify ``result`` and, on refusal, re-run + re-verify to convergence.

        Loops up to ``max_convergence_rounds``: verify; if accepted, converged;
        if refuted, re-run the sub-task through the public AD-859a
        :class:`WorkItemAgenticExecutor` with the critique appended to
        ``task_text``, update ``result.output`` from the re-run, then re-verify.
        A still-refuted result after the final round is escalated as
        ``unverified`` — never silently accepted.

        BF-777: a verification DEFECT (unparseable reply, non-bool or absent
        ``accepted``, judge unavailable, no independent verifier) terminates
        immediately as ``unverified``, on ANY round. It is a failure of the
        VERIFIER, not evidence about the producer, so re-running the producer
        against it would be asking them to fix someone else's protocol error.

        BF-778: this writes no trust in either direction, on any path.
        """
        verdict = await self.verify(result)
        if verdict.accepted:
            return ConvergenceOutcome(
                result=result, verdict=verdict, status=_STATUS_CONVERGED, rounds=0
            )
        if verdict.verification_defect:
            return self._defective_outcome(result, verdict, rounds=0)

        rounds = 0
        while rounds < self._max_rounds:
            rounds += 1
            critiqued_task = f"{task_text}\n\nCRITIQUE:\n{verdict.critique}"
            try:
                outcome = await self._executor.run(
                    agent_id=result.agent_id,
                    instructions=instructions,
                    task_text=critiqued_task,
                    runtime=self._runtime,
                )
                result.output = outcome.final_text or result.output
            except Exception:
                logger.warning(
                    "AD-860: convergence re-run failed for sub-task %s "
                    "(producer=%s, round=%d); keeping prior output and "
                    "re-verifying",
                    result.work_item_id, result.agent_id, rounds, exc_info=True,
                )
            verdict = await self.verify(result)
            if verdict.accepted:
                # BF-778: NO trust is recorded here, in either direction.
                #
                # An earlier revision credited a refusal whose re-run changed
                # the output and was then accepted, calling that "the refusal
                # was knowably correct". It is not. A whitespace-only edit
                # satisfies it, so the credit is farmable -- and the incentive
                # it creates is strictly worse than neutral: accepting pays 0,
                # refusing pays (chance any later edit is accepted) x credit, so
                # refusing weakly dominates. That is BF-778 mirrored, not fixed.
                #
                # Judging correctness needs real adjudication. AD-1282 (BF-782,
                # #1246) resolved where that lives: the SESSION path, which keeps
                # the round history and attributes through the crew trust outbox.
                # This legacy path is single-shot by design and has no production
                # caller, so it stays neutral -- crediting here would be a second
                # write for a judgement the session path already pays.
                return ConvergenceOutcome(
                    result=result,
                    verdict=verdict,
                    status=_STATUS_CONVERGED,
                    rounds=rounds,
                )
            if verdict.verification_defect:
                # BF-777: checked after EVERY verify, not only the first. A
                # defect surfacing on round 2 would otherwise re-run the
                # producer against "Unparseable judge response: ..." as if it
                # were a critique -- the exact thing the pre-loop guard exists
                # to prevent, one round later.
                return self._defective_outcome(result, verdict, rounds=rounds)

        logger.warning(
            "AD-860: sub-task %s (producer=%s) still refuted after %d "
            "convergence round(s); escalating as unverified — not silently "
            "accepting a refuted result",
            result.work_item_id, result.agent_id, rounds,
        )
        return ConvergenceOutcome(
            result=result, verdict=verdict, status=_STATUS_UNVERIFIED, rounds=rounds
        )

    def _defective_outcome(
        self,
        result: "SubtaskResult",
        verdict: VerificationVerdict,
        *,
        rounds: int,
    ) -> ConvergenceOutcome:
        """Terminate convergence on a VERIFIER failure (BF-777).

        The producer's work was never actually judged, so re-running them
        against the defect text would be asking them to fix someone else's
        protocol error.
        """
        logger.warning(
            "BF-777: verification of sub-task %s (producer=%s) failed as a "
            "VERIFIER defect after %d round(s) (%s); escalating as unverified "
            "without re-running the producer -- their work was never judged",
            result.work_item_id, result.agent_id, rounds, verdict.critique,
        )
        return ConvergenceOutcome(
            result=result, verdict=verdict, status=_STATUS_UNVERIFIED, rounds=rounds
        )

    @staticmethod
    def verdict_to_vote(verdict: VerificationVerdict) -> Vote:
        """Map a verdict to the real :class:`Vote` shape for AD-861 attribution.

        AD-861 builds the Shapley input from these votes; this module does NOT
        call ``compute_shapley_values`` itself.
        """
        return Vote(
            agent_id=verdict.verifier_agent_id,
            approved=verdict.accepted,
            confidence=verdict.confidence,
            reason=verdict.critique,
        )

    async def verify_for_session(
        self,
        result: "SubtaskResult",
        *,
        expected_output: str | None,
        excluded_agent_ids: frozenset[str],
    ) -> SessionVerificationPass:
        """Strictly judge one session result without trust or learning writes."""
        try:
            verifier_id = self._pick_live_session_verifier(excluded_agent_ids)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Session verifier selection failed for child %s; verification "
                "will fail closed without a trust update",
                getattr(result, "work_item_id", "?"),
                exc_info=True,
            )
            return SessionVerificationPass(
                status="error",
                accepted=False,
                confidence=0.0,
                critique="Verifier execution failed.",
                verifier_agent_id="",
                tokens_used=0,
                failure_code="verification_defect",
            )
        if verifier_id is None:
            return SessionVerificationPass(
                status="unavailable",
                accepted=False,
                confidence=0.0,
                critique="No eligible independent verifier is available.",
                verifier_agent_id="",
                tokens_used=0,
                failure_code="independent_verifier_unavailable",
            )
        try:
            result_text = self._session_result_text(
                result.output,
                maximum_bytes=(
                    262_144
                    if getattr(result, "spec_id", None) == "crew-session-final"
                    else _MAX_SESSION_RESULT_BYTES
                ),
            )
            expected = self._session_expected_output(expected_output)
            response = await self._llm.complete(LLMRequest(
                prompt=self._build_session_judge_prompt(result_text, expected),
                system_prompt=self._JUDGE_SYSTEM_PROMPT,
                tier="standard",
            ))
            tokens = self._session_tokens(getattr(response, "tokens_used", None))
            content = getattr(response, "content", None)
            return self._parse_session_verdict(content, verifier_id, tokens)
        except asyncio.CancelledError:
            raise
        except ValueError:
            return SessionVerificationPass(
                status="malformed",
                accepted=False,
                confidence=0.0,
                critique="Verifier response was malformed.",
                verifier_agent_id=verifier_id,
                tokens_used=0,
                failure_code="verification_defect",
            )
        except Exception:
            logger.warning(
                "Session verifier call failed for child %s using verifier %s; "
                "verification will fail closed without a trust update",
                getattr(result, "work_item_id", "?"),
                verifier_id,
                exc_info=True,
            )
            return SessionVerificationPass(
                status="error",
                accepted=False,
                confidence=0.0,
                critique="Verifier execution failed.",
                verifier_agent_id=verifier_id,
                tokens_used=0,
                failure_code="verification_defect",
            )

    async def converge_for_session(
        self,
        result: "SubtaskResult",
        *,
        instructions: str,
        task_text: str,
        expected_output: str | None,
        parent_id: str,
        thread_id: str,
        department: str,
        rank: str,
    ) -> SessionConvergenceOutcome:
        """Converge one child with bounded revisions and no learning writes."""
        current = replace(
            result,
            artifact_refs=[dict(ref) for ref in result.artifact_refs],
            blocked_dependency_ids=list(result.blocked_dependency_ids),
        )
        self._session_id(parent_id)
        self._session_id(thread_id)
        self._session_id(current.work_item_id)
        self._session_id(current.agent_id)
        normalized_instructions = self._session_task_input(instructions)
        normalized_task = self._session_task_input(task_text)
        if type(department) is not str or type(rank) is not str:
            raise ValueError("session_correction_context_invalid")
        initial_text = self._session_result_text(current.output)
        initial_artifacts = self._session_artifact_refs(
            current.artifact_refs,
            thread_id=thread_id,
        )
        initial_trace = self._session_trace_ref(current.tool_trace_ref)
        current = replace(
            current,
            output=initial_text,
            tool_trace_ref=initial_trace,
            artifact_refs=[dict(ref) for ref in initial_artifacts],
        )
        verdict = await self.verify_for_session(
            current,
            expected_output=expected_output,
            excluded_agent_ids=frozenset({current.agent_id}),
        )
        history: list[SessionVerificationRound] = [
            self._session_round(
                round_index=0,
                result_text=initial_text,
                correction_tokens=0,
                tool_trace_ref=initial_trace,
                artifact_refs=initial_artifacts,
                verdict=verdict,
            )
        ]
        terminal = self._terminal_for_verdict(
            current,
            verdict,
            rounds_used=0,
            history=history,
        )
        if terminal is not None:
            return terminal

        max_rounds = min(self._max_rounds, 8)
        for attempt_index in range(1, max_rounds + 1):
            critiqued_task = (
                f"{normalized_task}\n\nCRITIQUE:\n{verdict.critique}"
            )
            try:
                critiqued_task = self._session_task_input(critiqued_task)
            except ValueError:
                terminal_attempt = self._session_terminal_attempt(
                    attempt_index=attempt_index,
                    attempted_revision=len(history) + 1,
                    stopped_reason="execution_exception",
                    result_text="",
                    correction_tokens=0,
                    tool_trace_ref=None,
                    artifact_refs=(),
                    denied_tools=(),
                    failure_code="correction_execution_defect",
                )
                return self._session_terminal_outcome(
                    current,
                    status="failed",
                    rounds_used=attempt_index,
                    failure_code="correction_execution_defect",
                    history=history,
                    terminal_attempt=terminal_attempt,
                )
            try:
                outcome = await self._executor.run(
                    agent_id=current.agent_id,
                    instructions=normalized_instructions,
                    task_text=critiqued_task,
                    runtime=_session_correction_runtime(
                        self._runtime,
                        agent_id=current.agent_id,
                        department=department,
                        rank=rank,
                    ),
                    department=department,
                    rank=rank,
                    thread_id=thread_id,
                    extra_context={
                        "_crew_session_id": parent_id,
                        "_crew_work_item_id": current.work_item_id,
                    },
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Session correction failed for child %s on attempt %d; "
                    "the child will fail closed and no later revision will run",
                    current.work_item_id,
                    attempt_index,
                    exc_info=True,
                )
                terminal_attempt = self._session_terminal_attempt(
                    attempt_index=attempt_index,
                    attempted_revision=len(history) + 1,
                    stopped_reason="execution_exception",
                    result_text="",
                    correction_tokens=0,
                    tool_trace_ref=None,
                    artifact_refs=(),
                    denied_tools=(),
                    failure_code="correction_execution_defect",
                )
                return self._session_terminal_outcome(
                    current,
                    status="failed",
                    rounds_used=attempt_index,
                    failure_code="correction_execution_defect",
                    history=history,
                    terminal_attempt=terminal_attempt,
                )

            normalized_outcome = self._normalize_correction_outcome(
                outcome,
                thread_id=thread_id,
            )
            terminal_attempt = self._classify_correction_terminal(
                normalized_outcome,
                attempt_index=attempt_index,
                attempted_revision=len(history) + 1,
            )
            if terminal_attempt is not None:
                status = (
                    "blocked"
                    if terminal_attempt.failure_code in {
                        "correction_capability_denied",
                        "correction_budget_exhausted",
                    }
                    else "failed"
                )
                return self._session_terminal_outcome(
                    current,
                    status=status,
                    rounds_used=attempt_index,
                    failure_code=terminal_attempt.failure_code,
                    history=history,
                    terminal_attempt=terminal_attempt,
                )

            corrected_text = normalized_outcome.result_text
            correction_tokens = normalized_outcome.correction_tokens
            correction_trace = normalized_outcome.tool_trace_ref
            correction_artifacts = normalized_outcome.artifact_refs
            current = replace(
                current,
                output=corrected_text,
                tool_trace_ref=correction_trace,
                actual_tokens=correction_tokens,
                artifact_refs=[dict(ref) for ref in correction_artifacts],
            )
            verdict = await self.verify_for_session(
                current,
                expected_output=expected_output,
                excluded_agent_ids=frozenset({current.agent_id}),
            )
            history.append(self._session_round(
                round_index=len(history),
                result_text=corrected_text,
                correction_tokens=correction_tokens,
                tool_trace_ref=correction_trace,
                artifact_refs=correction_artifacts,
                verdict=verdict,
            ))
            terminal = self._terminal_for_verdict(
                current,
                verdict,
                rounds_used=attempt_index,
                history=history,
            )
            if terminal is not None:
                return terminal

        return self._session_terminal_outcome(
            current,
            status="unverified",
            rounds_used=max_rounds,
            failure_code="convergence_exhausted",
            history=history,
            terminal_attempt=None,
        )

    # ------------------------------------------------------------------ internals

    _JUDGE_SYSTEM_PROMPT = (
        "You are an adversarial verifier on a crew of collaborating agents. "
        "Your job is to find flaws, missing requirements, or unsupported "
        "claims in another agent's work — NOT to be agreeable. Respond ONLY "
        "with a single JSON object of the form "
        '{"accepted": <bool>, "confidence": <0..1 float>, "critique": '
        '"<short reason>"}. Set "accepted" to true only if the work is correct '
        "and complete; otherwise false with a concrete critique."
    )

    def _pick_live_session_verifier(
        self,
        excluded_agent_ids: frozenset[str],
    ) -> str | None:
        if type(excluded_agent_ids) is not frozenset or any(
            type(agent_id) is not str
            or _SESSION_ID_RE.fullmatch(agent_id) is None
            for agent_id in excluded_agent_ids
        ):
            raise ValueError("session_verifier_exclusions_invalid")
        agents = self._registry.all()
        if type(agents) is not list:
            raise ValueError("session_verifier_registry_invalid")
        for candidate in agents:
            candidate_id = getattr(candidate, "id", None)
            if (
                type(candidate_id) is not str
                or _SESSION_ID_RE.fullmatch(candidate_id) is None
                or candidate_id in excluded_agent_ids
            ):
                continue
            if self._registry.get(candidate_id) is not candidate:
                continue
            if getattr(candidate, "is_alive", None) is not True:
                continue
            return candidate_id
        return None

    @staticmethod
    def _session_id(value: Any) -> str:
        if type(value) is not str or _SESSION_ID_RE.fullmatch(value) is None:
            raise ValueError("session_id_invalid")
        return value

    @staticmethod
    def _session_result_text(
        value: Any,
        *,
        maximum_bytes: int = _MAX_SESSION_RESULT_BYTES,
    ) -> str:
        if type(value) is not str or "\x00" in value:
            raise ValueError("session_result_invalid")
        normalized = value.strip()
        try:
            encoded = normalized.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("session_result_invalid") from exc
        if not normalized or len(encoded) > maximum_bytes:
            raise ValueError("session_result_invalid")
        return normalized

    @staticmethod
    def _session_task_input(value: Any) -> str:
        if type(value) is not str or "\x00" in value:
            raise ValueError("session_correction_context_invalid")
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > _MAX_SESSION_TASK_BYTES:
            raise ValueError("session_correction_context_invalid")
        return normalized

    @staticmethod
    def _session_expected_output(value: Any) -> str | None:
        if value is None:
            return None
        if type(value) is not str or "\x00" in value:
            raise ValueError("session_expected_output_invalid")
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > 262_144:
            raise ValueError("session_expected_output_invalid")
        return normalized

    @staticmethod
    def _session_tokens(value: Any) -> int:
        if type(value) is not int or not 0 <= value <= _MAX_SESSION_TOKENS:
            raise ValueError("session_tokens_invalid")
        return value

    @staticmethod
    def _session_trace_ref(value: Any) -> str | None:
        if value is None:
            return None
        if type(value) is not str or _SESSION_SHA_RE.fullmatch(value) is None:
            raise ValueError("session_trace_ref_invalid")
        return value

    @classmethod
    def _session_artifact_refs(
        cls,
        value: Any,
        *,
        thread_id: str,
    ) -> tuple[dict[str, Any], ...]:
        if type(value) is not list or len(value) > 32:
            raise ValueError("session_artifact_refs_invalid")
        detached: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in value:
            if type(raw) is not dict or set(raw) != _SESSION_ARTIFACT_KEYS:
                raise ValueError("session_artifact_refs_invalid")
            artifact_id = cls._session_id(raw["artifact_id"])
            content_hash = raw["content_hash"]
            ref_thread = raw["thread_id"]
            name = raw["name"]
            mime = raw["mime"]
            size_bytes = raw["size_bytes"]
            version = raw["version"]
            if (
                artifact_id in seen
                or type(content_hash) is not str
                or _SESSION_SHA_RE.fullmatch(content_hash) is None
                or ref_thread != thread_id
                or type(name) is not str
                or not name
                or len(name) > 255
                or "\x00" in name
                or "/" in name
                or "\\" in name
                or _session_projection_string(
                    name,
                    maximum_codepoints=255,
                    maximum_bytes=1_024,
                    allow_empty=False,
                ) is None
                or type(mime) is not str
                or not mime
                or len(mime) > 255
                or "\x00" in mime
                or _session_projection_string(
                    mime,
                    maximum_codepoints=255,
                    maximum_bytes=1_024,
                    allow_empty=False,
                ) is None
                or type(size_bytes) is not int
                or not 1 <= size_bytes <= 26_214_400
                or type(version) is not int
                or not 1 <= version <= 2_147_483_647
            ):
                raise ValueError("session_artifact_refs_invalid")
            seen.add(artifact_id)
            detached.append({key: raw[key] for key in (
                "artifact_id",
                "content_hash",
                "thread_id",
                "name",
                "mime",
                "size_bytes",
                "version",
            )})
        return tuple(detached)

    @staticmethod
    def _build_session_judge_prompt(
        result_text: str,
        expected_output: str | None,
    ) -> str:
        if expected_output is None:
            return (
                "Independently verify this produced result for correctness, "
                "completeness, and supported claims.\n\n"
                f"PRODUCED RESULT:\n{result_text}\n\n"
                "Return only the exact JSON verdict object."
            )
        return (
            "Independently verify whether the produced result satisfies the "
            "complete expected-output contract.\n\n"
            f"EXPECTED OUTPUT:\n{expected_output}\n\n"
            f"PRODUCED RESULT:\n{result_text}\n\n"
            "Return only the exact JSON verdict object."
        )

    @staticmethod
    def _parse_session_verdict(
        content: Any,
        verifier_id: str,
        tokens: int,
    ) -> SessionVerificationPass:
        if (
            type(content) is not str
            or len(content.encode("utf-8")) > 16_384
        ):
            raise ValueError("session_verdict_invalid")
        def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            if len({key for key, _value in pairs}) != len(pairs):
                raise ValueError("session_verdict_invalid")
            return dict(pairs)
        try:
            payload = json.loads(
                content,
                object_pairs_hook=_object_without_duplicates,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("session_verdict_invalid") from exc
        if type(payload) is not dict or set(payload) != {
            "accepted",
            "confidence",
            "critique",
        }:
            raise ValueError("session_verdict_invalid")
        accepted = payload["accepted"]
        confidence = payload["confidence"]
        critique = payload["critique"]
        if (
            type(accepted) is not bool
            or type(confidence) not in (int, float)
            or not math.isfinite(float(confidence))
            or not 0.0 <= float(confidence) <= 1.0
            or type(critique) is not str
            or "\x00" in critique
        ):
            raise ValueError("session_verdict_invalid")
        normalized_critique = critique.strip()
        if (
            accepted and not normalized_critique
            or len(normalized_critique) > _MAX_SESSION_CRITIQUE_CODEPOINTS
            or len(normalized_critique.encode("utf-8")) > _MAX_SESSION_CRITIQUE_BYTES
        ):
            raise ValueError("session_verdict_invalid")
        return SessionVerificationPass(
            status="accepted" if accepted else "refuted",
            accepted=accepted,
            confidence=float(confidence),
            critique=normalized_critique,
            verifier_agent_id=verifier_id,
            tokens_used=tokens,
            failure_code=None,
        )

    @staticmethod
    def _session_round(
        *,
        round_index: int,
        result_text: str,
        correction_tokens: int,
        tool_trace_ref: str | None,
        artifact_refs: tuple[dict[str, Any], ...],
        verdict: SessionVerificationPass,
    ) -> SessionVerificationRound:
        return SessionVerificationRound(
            round_index=round_index,
            result_revision=round_index + 1,
            result_text=result_text,
            result_sha256=hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
            result_summary=result_text.strip()[:_MAX_SESSION_SUMMARY_CODEPOINTS],
            stopped_reason="complete",
            correction_tokens=correction_tokens,
            verifier_tokens=verdict.tokens_used,
            tool_trace_ref=tool_trace_ref,
            artifact_refs=tuple(dict(ref) for ref in artifact_refs),
            verdict=verdict,
        )

    def _terminal_for_verdict(
        self,
        result: "SubtaskResult",
        verdict: SessionVerificationPass,
        *,
        rounds_used: int,
        history: list[SessionVerificationRound],
    ) -> SessionConvergenceOutcome | None:
        if verdict.status == "accepted":
            return self._session_terminal_outcome(
                result,
                status="converged",
                rounds_used=rounds_used,
                failure_code=None,
                history=history,
                terminal_attempt=None,
            )
        if verdict.status == "unavailable":
            return self._session_terminal_outcome(
                result,
                status="blocked",
                rounds_used=rounds_used,
                failure_code="independent_verifier_unavailable",
                history=history,
                terminal_attempt=None,
            )
        if verdict.status in {"malformed", "error"}:
            return self._session_terminal_outcome(
                result,
                status="failed",
                rounds_used=rounds_used,
                failure_code="verification_defect",
                history=history,
                terminal_attempt=None,
            )
        return None

    @staticmethod
    def _session_terminal_outcome(
        result: "SubtaskResult",
        *,
        status: str,
        rounds_used: int,
        failure_code: SessionVerificationFailureCode | None,
        history: list[SessionVerificationRound],
        terminal_attempt: SessionCorrectionTerminalAttempt | None,
    ) -> SessionConvergenceOutcome:
        return SessionConvergenceOutcome(
            result=result,
            accepted=status == "converged",
            status=status,
            rounds_used=rounds_used,
            failure_code=failure_code,
            history=tuple(history),
            terminal_attempt=terminal_attempt,
        )

    @classmethod
    def _session_terminal_attempt(
        cls,
        *,
        attempt_index: int,
        attempted_revision: int,
        stopped_reason: str,
        result_text: str,
        correction_tokens: int,
        tool_trace_ref: str | None,
        artifact_refs: tuple[dict[str, Any], ...],
        denied_tools: tuple[str, ...],
        failure_code: SessionVerificationFailureCode,
    ) -> SessionCorrectionTerminalAttempt:
        result_hash = (
            hashlib.sha256(result_text.encode("utf-8")).hexdigest()
            if result_text
            else None
        )
        return SessionCorrectionTerminalAttempt(
            attempt_index=attempt_index,
            attempted_revision=attempted_revision,
            stopped_reason=stopped_reason,
            result_text=result_text,
            result_sha256=result_hash,
            result_summary=result_text.strip()[:_MAX_SESSION_SUMMARY_CODEPOINTS],
            correction_tokens=correction_tokens,
            tool_trace_ref=tool_trace_ref,
            artifact_refs=tuple(dict(ref) for ref in artifact_refs),
            denied_tools=denied_tools,
            failure_code=failure_code,
        )

    @classmethod
    def _classify_correction_terminal(
        cls,
        outcome: _NormalizedSessionCorrectionOutcome,
        *,
        attempt_index: int,
        attempted_revision: int,
    ) -> SessionCorrectionTerminalAttempt | None:
        if not outcome.valid:
            failure: SessionVerificationFailureCode = "correction_execution_defect"
        elif outcome.denied_tools:
            failure: SessionVerificationFailureCode = "correction_capability_denied"
        elif outcome.stopped_reason == "token_budget":
            failure = "correction_budget_exhausted"
        elif outcome.stopped_reason == "complete" and outcome.result_text:
            return None
        else:
            failure = "correction_execution_defect"
        return cls._session_terminal_attempt(
            attempt_index=attempt_index,
            attempted_revision=attempted_revision,
            stopped_reason=outcome.stopped_reason,
            result_text=outcome.result_text,
            correction_tokens=outcome.correction_tokens,
            tool_trace_ref=outcome.tool_trace_ref,
            artifact_refs=outcome.artifact_refs,
            denied_tools=outcome.denied_tools,
            failure_code=failure,
        )

    @classmethod
    def _normalize_correction_outcome(
        cls,
        outcome: Any,
        *,
        thread_id: str,
    ) -> _NormalizedSessionCorrectionOutcome:
        try:
            raw_reason = getattr(outcome, "stopped_reason")
            raw_text = getattr(outcome, "final_text")
            raw_tokens = getattr(outcome, "total_tokens")
            raw_trace = getattr(outcome, "tool_trace_ref")
            raw_artifacts = getattr(outcome, "artifact_refs")
            raw_denied = getattr(outcome, "denied_tools")
        except Exception:
            return _NormalizedSessionCorrectionOutcome(
                valid=False,
                stopped_reason="execution_exception",
                result_text="",
                correction_tokens=0,
                tool_trace_ref=None,
                artifact_refs=(),
                denied_tools=(),
            )

        valid = True
        stopped_reason: Literal[
            "complete",
            "error",
            "max_iterations",
            "token_budget",
            "execution_exception",
        ] = "execution_exception"
        if type(raw_reason) is str and raw_reason in {
            "complete",
            "error",
            "max_iterations",
            "token_budget",
        }:
            stopped_reason = raw_reason
        else:
            valid = False

        result_text = ""
        if type(raw_text) is str and "\x00" not in raw_text:
            candidate = raw_text.strip()
            try:
                encoded = candidate.encode("utf-8", errors="strict")
            except UnicodeError:
                valid = False
            else:
                if len(encoded) <= _MAX_SESSION_RESULT_BYTES:
                    result_text = candidate
                else:
                    valid = False
        else:
            valid = False

        try:
            correction_tokens = cls._session_tokens(raw_tokens)
        except (TypeError, ValueError):
            correction_tokens = 0
            valid = False
        try:
            tool_trace_ref = cls._session_trace_ref(raw_trace)
        except (TypeError, ValueError):
            tool_trace_ref = None
            valid = False
        try:
            artifact_refs = cls._session_artifact_refs(
                raw_artifacts,
                thread_id=thread_id,
            )
        except Exception:
            artifact_refs = ()
            valid = False
        try:
            denied_tools = validate_session_denied_tools(raw_denied)
        except Exception:
            denied_tools = None
        if denied_tools is None:
            denied_tools = ()
            valid = False
        return _NormalizedSessionCorrectionOutcome(
            valid=valid,
            stopped_reason=stopped_reason,
            result_text=result_text,
            correction_tokens=correction_tokens,
            tool_trace_ref=tool_trace_ref,
            artifact_refs=artifact_refs,
            denied_tools=denied_tools,
        )

    def _pick_independent_verifier(self, producer_id: str) -> str | None:
        """Return an agent id that differs from ``producer_id``, or ``None``.

        Independence is the gate: the producer can never verify itself.

        AD-866 selection order (only when an ``ontology`` was wired):

        1. **Department peer** — an alive agent ``!= producer`` in the *same
           department* as the producer (the most qualified independent judge).
        2. **Authority chain** — the producer's chief (a superior post's alive
           agent) when no peer is available.
        3. **Any independent** (AD-860 behavior) — the first registered agent
           whose id is not the producer's.
        4. **None** — honest-degrade to ``unverified``.

        When no ontology is wired (default), steps 1–2 are skipped and the
        AD-860 any-independent path runs verbatim. Any ontology lookup error is
        Tier-2 log-and-degraded — it falls through to step 3, never propagates.
        """
        try:
            agents = self._registry.all()
        except Exception:
            logger.warning(
                "AD-860: agent registry lookup failed while picking a verifier "
                "for producer %s; treating as no independent agent available",
                producer_id, exc_info=True,
            )
            return None

        if self._ontology is not None:
            try:
                peer = self._pick_department_peer(producer_id, agents)
                if peer is not None:
                    return peer
                chief = self._pick_authority_chief(producer_id, agents)
                if chief is not None:
                    return chief
            except Exception:
                logger.warning(
                    "AD-866: ontology-aware verifier selection failed for "
                    "producer %s; falling back to any-independent selection",
                    producer_id, exc_info=True,
                )

        for agent in agents:
            agent_id = getattr(agent, "id", None)
            if agent_id and agent_id != producer_id:
                return agent_id
        return None

    def _agent_type_for(self, producer_id: str, agents: list[Any]) -> str | None:
        """Map a producer ``agent_id`` to its ``agent_type`` via the registry."""
        for agent in agents:
            if getattr(agent, "id", None) == producer_id:
                return getattr(agent, "agent_type", None)
        return None

    def _pick_department_peer(self, producer_id: str, agents: list[Any]) -> str | None:
        """AD-866 step 1: first alive same-department agent ``!= producer``."""
        producer_type = self._agent_type_for(producer_id, agents)
        if producer_type is None:
            return None
        producer_dept = self._ontology.get_agent_department(producer_type)
        if producer_dept is None:
            return None
        for agent in agents:
            agent_id = getattr(agent, "id", None)
            if not agent_id or agent_id == producer_id:
                continue
            if self._registry.get(agent_id) is None:
                continue  # dead/unregistered — excluded
            cand_type = getattr(agent, "agent_type", None)
            if cand_type is None:
                continue
            if self._ontology.get_agent_department(cand_type) == producer_dept:
                return agent_id
        return None

    def _pick_authority_chief(self, producer_id: str, agents: list[Any]) -> str | None:
        """AD-866 step 2: the producer's chief — an alive superior-post agent.

        Walks the producer's chain of command and returns the first superior
        post's live wired agent ``!= producer``. Dead/unwired posts are skipped.
        """
        producer_type = self._agent_type_for(producer_id, agents)
        if producer_type is None:
            return None
        producer_post = self._ontology.get_post_for_agent(producer_type)
        if producer_post is None:
            return None
        for post in self._ontology.get_chain_of_command(producer_post.id):
            if post.id == producer_post.id:
                continue  # the producer's own post is not a superior
            for assignment in self._ontology.get_agents_for_post(post.id):
                cand_id = getattr(assignment, "agent_id", None)
                if not cand_id or cand_id == producer_id:
                    continue
                if self._registry.get(cand_id) is None:
                    continue  # superior post unfilled by a live agent — excluded
                return cand_id
        return None

    async def _resolve_expected_output(self, work_item_id: str) -> str | None:
        """Resolve the declared acceptance criterion from the work item.

        AD-858 persists ``expected_output`` into the work item metadata (the
        AD-860 one-line dispatch fix). Honest-degrades to ``None`` — the
        free-text critique path — when the item or key is absent.
        """
        try:
            wi = await self._store.get_work_item(work_item_id)
        except Exception:
            logger.warning(
                "AD-860: work item lookup failed for %s; falling back to the "
                "free-text critique path",
                work_item_id, exc_info=True,
            )
            return None
        if wi is None:
            return None
        expected = (wi.metadata or {}).get("expected_output")
        return expected if isinstance(expected, str) and expected else None

    def _build_judge_prompt(
        self, result: "SubtaskResult", expected: str | None
    ) -> str:
        """Build the judge prompt, anchored to ``expected`` when declared."""
        if expected:
            return (
                "A crew member produced the following result for a sub-task "
                "with a DECLARED acceptance criterion. Decide whether the "
                "result satisfies that criterion.\n\n"
                f"DECLARED ACCEPTANCE CRITERION:\n{expected}\n\n"
                f"PRODUCED RESULT:\n{result.output}\n\n"
                "Does the result satisfy the declared acceptance criterion? "
                "Respond with the JSON verdict object."
            )
        return (
            "A crew member produced the following result for a sub-task. No "
            "explicit acceptance criterion was declared, so judge it on "
            "general correctness, completeness, and whether every claim is "
            "supported.\n\n"
            f"PRODUCED RESULT:\n{result.output}\n\n"
            "Find any flaw, missing requirement, or unsupported claim. Respond "
            "with the JSON verdict object."
        )

    def _parse_verdict(self, content: str, verifier_id: str) -> VerificationVerdict:
        """Parse the judge's JSON response into a verdict (robust to non-JSON).

        Honest-degrades an unparseable response to a refuted verdict — the
        conservative direction — so a malformed judge reply never silently
        accepts a result. BF-777: that also covers a parseable reply whose
        ``accepted`` is not a real bool. ``bool("false")`` is ``True``, so the
        old coercion read a refusal as an approval, which is the one direction
        this parser must never fail in.
        """
        raw = (content or "").strip()
        payload = self._extract_json_object(raw)
        if payload is None:
            logger.warning(
                "AD-860: judge response was not parseable JSON (verifier=%s); "
                "honest-degrading to refuted so an unparseable reply never "
                "silently accepts a result",
                verifier_id,
            )
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique=f"Unparseable judge response: {raw[:200]}",
                verifier_agent_id=verifier_id,
                verification_defect=True,
            )
        accepted_raw = payload.get("accepted", _MISSING_VERDICT_FIELD)
        # Exact type check, matching the strict sibling `_parse_session_verdict`.
        # A MISSING field is malformed too: defaulting it to False produced an
        # ordinary-looking refusal that the producer was then asked to fix.
        if type(accepted_raw) is not bool:
            missing = accepted_raw is _MISSING_VERDICT_FIELD
            logger.warning(
                "BF-777: judge returned %s 'accepted' (%r, verifier=%s); "
                "honest-degrading to a verification DEFECT rather than "
                "coercing -- bool('false') is True, so coercion reads a "
                "refusal as an approval",
                "no" if missing else "a non-bool",
                None if missing else accepted_raw,
                verifier_id,
            )
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique=(
                    "Malformed judge verdict: 'accepted' was "
                    + (
                        "absent" if missing
                        else f"{type(accepted_raw).__name__}, not bool"
                    )
                ),
                verifier_agent_id=verifier_id,
                verification_defect=True,
            )
        accepted = accepted_raw
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        critique = str(payload.get("critique", "")).strip()
        return VerificationVerdict(
            accepted=accepted,
            confidence=confidence,
            critique=critique,
            verifier_agent_id=verifier_id,
        )

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any] | None:
        """Extract the first top-level JSON object from ``raw``, or ``None``."""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
