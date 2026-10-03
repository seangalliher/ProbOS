"""AD-854: Acquire-vs-build capability triage router (grant -> install -> build).

A **pure** decision core (no I/O, deterministic over plain data) plus a thin
async driver that performs all I/O. The pure functions map a capability need to
the cheapest reversible rung, aligned with the three governance axioms:

  - **grant**   -> Minimal Authority      (most reversible, no new code)
  - **install** -> Reversibility Preference (sandboxed, revocable)
  - **build**   -> Safety Budget          (most expensive, always Captain-gated)

The real gap surface is a plain ``str`` (``runtime._last_capability_gap`` / the
unhandled-intent name); the driver resolves it into the three booleans the pure
``triage`` consumes. There is intentionally NO ``CapabilityGap`` dataclass.

AD-1194 makes this the one ladder every gap producer files through --
``grant -> discover -> install -> forge -> build`` -- when
``capability_triage.unified_ladder_enabled`` is set; see :func:`evaluate_ladder`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from probos.approval_authority import REVIEW_TOOL_ID
from probos.capability_request import (
    BUILD_PARAMETER_MAX_CHARS,
    BUILD_PAYLOAD_KEYS,
    BUILD_TEXT_MAX_CHARS,
    MAX_BUILD_PARAMETERS,
    TRIAGE_CANDIDATE_MAX_CHARS,
    TRIAGE_MAX_CANDIDATES,
    TRIAGE_REASON_MAX_CHARS,
    TRIAGE_RECORD_VERSION,
    build_requires_consensus,
    validate_build_payload,
    validate_install_payload,
    validate_python_install_target,
)
from probos.integrations.mcp_bridge.registration import register_record
from probos.tools.protocol import ToolPermission, permission_includes

if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequest, CapabilityRequestStore
    from probos.config import CapabilityTriageConfig
    from probos.tools.permissions import ToolPermissionStore

logger = logging.getLogger(__name__)

Rung = Literal["grant", "install", "build"]


def triage(
    *,
    tool_registered: bool,
    agent_has_permission: bool,
    skill_known: bool,
) -> Rung:
    """Pick the cheapest reversible rung from three already-resolved booleans.

    1. **grant** — a registered tool the agent lacks permission for
       (``tool_registered and not agent_has_permission``).
    2. **install** — a registered-but-disabled MCP server (``skill_known``).
    3. **build** — otherwise (least reversible; always needs Captain approval).
    """
    if tool_registered and not agent_has_permission:
        return "grant"
    if skill_known:
        return "install"
    return "build"


def evaluate_grant_fast_path(
    *,
    non_destructive: bool,
    peer_precedent: bool,
    agent_trust: float,
    trust_floor: float,
    fast_path_enabled: bool,
) -> bool:
    """Decide whether a ``grant`` rung may be auto-approved without a Captain prompt.

    True only when the fast path is enabled AND the target tool is non-destructive
    AND an in-department peer already holds the grant AND the requesting agent's
    trust is at or above the configured floor. ``install`` and ``build`` never call
    this.
    """
    return (
        fast_path_enabled
        and non_destructive
        and peer_precedent
        and agent_trust >= trust_floor
    )


def _derive_tool_permission(registration: Any) -> ToolPermission:
    """Derive a tool's effective required permission from its default matrix.

    Returns the highest ``ToolPermission`` across the registration's rank
    ``default_permissions`` values. An empty matrix means the ship-wide default
    of READ (per ``ToolRegistration`` semantics).
    """
    defaults = getattr(registration, "default_permissions", None) or {}
    highest = ToolPermission.NONE
    for value in defaults.values():
        try:
            level = ToolPermission(value)
        except ValueError:
            continue
        if permission_includes(level, highest):
            highest = level
    if highest == ToolPermission.NONE:
        return ToolPermission.READ
    return highest


def _is_non_destructive(permission: ToolPermission) -> bool:
    """OBSERVE/READ are non-destructive; WRITE/FULL are destructive."""
    return not permission_includes(permission, ToolPermission.WRITE)


# AD-1213: the one definition of "destructive", public so delegated-approval
# eligibility reuses these exact objects (#1170: "do not invent a second
# definition of destructive").
derive_tool_permission = _derive_tool_permission
is_non_destructive = _is_non_destructive


def _agent_has_permission(
    permission_store: ToolPermissionStore | None,
    agent_id: str,
    tool_id: str,
) -> bool:
    """True when the agent holds an active, non-restriction grant for the tool."""
    if permission_store is None:
        return False
    grants = permission_store.get_active_grants_sync(agent_id, tool_id)
    return any(
        not g.is_restriction and g.permission != ToolPermission.NONE for g in grants
    )


def _peer_precedent(
    grants: list[Any],
    *,
    tool_id: str,
    requester_id: str,
    ontology: Any,
) -> bool:
    """True when an in-department peer already holds an active grant for the tool."""
    if ontology is None:
        return False
    req_dept = ontology.get_agent_department(requester_id)
    if req_dept is None:
        return False
    for g in grants:
        if g.tool_id != tool_id or g.is_restriction or g.agent_id == requester_id:
            continue
        holder_dept = ontology.get_agent_department(g.agent_id)
        if holder_dept is not None and holder_dept == req_dept:
            return True
    return False


def resolve_installable_mcp_server(
    mcp_server_store: Any,
    gap_target: str,
) -> Any | None:
    """AD-1215: the registered-but-disabled MCP server an ``install`` would enable.

    This is the whole meaning of the ``install`` rung (#1205): a server the ship
    already knows about, matched by id or by name, that is currently switched off.
    An already-enabled server is deliberately **not** installable — the capability
    is present, so the cheaper ``grant``/``build`` reasoning should stand instead
    of filing an install that would be a no-op.

    Matching is two-stage: an **exact id match wins over a name match**, because
    an id is unique (uuid4 + ``PRIMARY KEY``, and ``update`` refuses to change it)
    whereas a name is only unique within its own column and may equal some other
    record's id. Within the winning axis, a disabled candidate is returned if one
    exists, so an enabled record cannot mask a later installable one; ties fall to
    store order, which ``list_sync`` reports deterministically (creation order).

    Returns ``None`` when the store is absent, unreadable, or holds no match, and
    when every candidate on the winning axis is already enabled.
    """
    if mcp_server_store is None:
        return None
    try:
        records = mcp_server_store.list_sync()
    except Exception:
        logger.warning(
            "AD-1215: mcp_server_store.list_sync() failed while resolving %r; "
            "treating it as no installable server so triage falls through to build",
            gap_target,
            exc_info=True,
        )
        return None
    return _match_mcp_server(records, gap_target, disabled_only=True)


def _match_mcp_server(
    records: list[Any], gap_target: str, *, disabled_only: bool
) -> Any | None:
    by_id = [record for record in records if getattr(record, "id", None) == gap_target]
    matched = by_id or [
        record for record in records if getattr(record, "name", None) == gap_target
    ]
    for rec in matched:
        if not disabled_only or not getattr(rec, "enabled", False):
            return rec
    return None


# ── AD-1194: one ladder for every capability-gap producer ──────────────────
#
# ``triage`` above selects among the three FULFILMENT rungs. #1131 put every gap
# producer through the same policy -- AD-855's work items (a tool gap), the
# ordinary NL path (an intent gap), AD-1220's missing libraries (a package gap)
# -- and added two rungs that are deliberately never selected:
#
#   * discover SURFACES AD-1049's ARD candidates and never adopts (AD-1049 DD-1),
#     so it informs the Captain's decision without closing the gap itself;
#   * forge is SkillForge's SKILL.md package, and no current gap class is closed
#     by one: a tool gap needs a registered tool, an intent gap an agent that
#     handles the intent, a package gap the package. It is not wired to forge
#     artifacts that leave the gap open: a record marks it not applicable, with
#     its class's reason, when a build is selected, and not run when a cheaper
#     rung is, as it does every rung above the selected one.
#
# So ``selected`` is always a rung the existing store, route and fulfillers
# already handle, and the record is evidence for the Captain, never authority:
# no fulfiller reads it.

GapClass = Literal["tool", "intent", "package"]
LadderRung = Literal["grant", "discover", "install", "forge", "build"]
RungOutcome = Literal["selected", "escalated", "not_applicable", "not_run"]
#: A discover rung: gap target in, candidate labels out, ``None`` if it did not run.
DiscoverFn = Callable[[str], Awaitable["list[str] | None"]]

LADDER_ORDER: tuple[LadderRung, ...] = ("grant", "discover", "install", "forge", "build")

_SELECTED_REASONS: dict[tuple[str, str], str] = {
    ("tool", "grant"): (
        "a registered tool the agent lacks permission for; a grant is the most "
        "reversible fix"
    ),
    ("tool", "install"): (
        "a registered but disabled MCP server matches; enabling it is reversible"
    ),
    ("tool", "build"): (
        "no cheaper rung closes this gap; a new agent is designed only after "
        "Captain approval"
    ),
    ("intent", "build"): (
        "only an agent that handles this intent closes the gap; it is designed "
        "only after Captain approval"
    ),
    ("package", "install"): (
        "installing the library is the only rung that provides it; it runs only "
        "after Captain approval"
    ),
}
_FORGE_REASONS: dict[str, str] = {
    "tool": "a SKILL.md package cannot register a tool",
    "intent": "a SKILL.md package does not register an intent",
}


def unified_ladder_enabled(config: Any) -> bool:
    """AD-1194: whether gap producers file through the whole ladder.

    Reads ``config.capability_triage.unified_ladder_enabled`` and accepts only a
    real ``True``, so a missing section or a ``MagicMock`` config -- common in
    this repository's tests -- keeps every producer on its HEAD behaviour.
    """
    section = getattr(config, "capability_triage", None) if config is not None else None
    return getattr(section, "unified_ladder_enabled", False) is True


def _clean(text: str, limit: int) -> str:
    """Cut to ``limit`` and make it bindable: SQLite binds UTF-8, a lone surrogate is not."""
    return text[:limit].encode("utf-8", "replace").decode("utf-8")


@dataclass(frozen=True)
class RungVerdict:
    """What one rung concluded for a gap, and why (AD-1194)."""

    rung: LadderRung
    outcome: RungOutcome
    reason: str
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """The bounded form ``validate_triage_record`` accepts."""
        return {
            "rung": self.rung,
            "outcome": self.outcome,
            "reason": _clean(self.reason, TRIAGE_REASON_MAX_CHARS),
            "candidates": [
                _clean(candidate, TRIAGE_CANDIDATE_MAX_CHARS)
                for candidate in self.candidates[:TRIAGE_MAX_CANDIDATES]
            ],
        }


@dataclass(frozen=True)
class TriageRecord:
    """The whole ladder for one gap: every rung in order, and the one selected."""

    gap_class: GapClass
    selected: Rung
    rungs: tuple[RungVerdict, ...]

    def to_dict(self) -> dict[str, Any]:
        """What a request's ``triage`` column stores."""
        return {
            "version": TRIAGE_RECORD_VERSION,
            "gap_class": self.gap_class,
            "selected": self.selected,
            "rungs": [verdict.to_dict() for verdict in self.rungs],
        }


def evaluate_ladder(
    *,
    gap_class: GapClass,
    tool_registered: bool = False,
    agent_has_permission: bool = False,
    skill_known: bool = False,
    discovery: list[str] | None = None,
) -> TriageRecord:
    """AD-1194: walk ``grant -> discover -> install -> forge -> build`` for one gap. Pure.

    For a ``tool`` gap the selected rung is exactly what :func:`triage` returns
    for the same booleans, so routing AD-855 through the ladder cannot change
    which rung it files. An ``intent`` gap is closed only by an agent that handles
    the intent (``build``) and a ``package`` gap only by installing it. Every rung
    below the selected one records why it did not close the gap; every rung above
    it records that it did not run.

    ``discovery`` is the discover rung's result: ``None`` when it did not run, a
    list -- possibly empty -- of candidate labels when it did.
    """
    if gap_class == "package":
        selected: Rung = "install"
    elif gap_class == "intent":
        selected = "build"
    else:
        selected = triage(
            tool_registered=tool_registered,
            agent_has_permission=agent_has_permission,
            skill_known=skill_known,
        )
    cut = LADDER_ORDER.index(selected)
    rungs: list[RungVerdict] = []
    for index, rung in enumerate(LADDER_ORDER):
        if rung == selected:
            rungs.append(RungVerdict(rung, "selected", _SELECTED_REASONS[(gap_class, rung)]))
        elif index > cut:
            rungs.append(RungVerdict(rung, "not_run", f"a cheaper rung ({selected}) was selected"))
        else:
            rungs.append(_passed_over(rung, gap_class, tool_registered, discovery))
    return TriageRecord(gap_class=gap_class, selected=selected, rungs=tuple(rungs))


def _passed_over(
    rung: LadderRung,
    gap_class: GapClass,
    tool_registered: bool,
    discovery: list[str] | None,
) -> RungVerdict:
    """Why a rung below the selected one did not close the gap."""
    if rung == "grant":
        if gap_class == "intent":
            return RungVerdict(
                rung, "not_applicable",
                "an unhandled intent needs an agent that handles it; no tool grant makes one",
            )
        if gap_class == "package":
            return RungVerdict(rung, "not_applicable", "a missing library is not a tool permission")
        return RungVerdict(
            rung, "escalated",
            "the agent already holds a grant for this tool" if tool_registered
            else "no registered tool has this id",
        )
    if rung == "discover":
        if gap_class == "package":
            return RungVerdict(
                rung, "not_applicable",
                "catalog resources are agents and servers, not importable libraries",
            )
        if discovery is None:
            return RungVerdict(rung, "not_run", "discovery-before-design is off or was unavailable")
        return RungVerdict(
            rung, "escalated",
            f"{len(discovery)} candidate(s) surfaced for the Captain; discovery never adopts"
            if discovery else "no catalog resource matched",
            tuple(discovery),
        )
    if rung == "install":
        if gap_class == "intent":
            return RungVerdict(
                rung, "not_applicable",
                "MCP tools are not decomposer intents, so enabling a server cannot handle this intent",
            )
        return RungVerdict(rung, "escalated", "no registered but disabled MCP server matches")
    return RungVerdict(rung, "not_applicable", _FORGE_REASONS[gap_class])


def _discovery_applies(gap_class: GapClass, selected: Rung) -> bool:
    """Discover sits above grant, and a library is never in a catalog."""
    return gap_class != "package" and selected != "grant"


def candidate_label(candidate: dict[str, Any]) -> str:
    """One AD-1049 candidate as the short line a triage record keeps."""
    identifier = candidate.get("identifier") or candidate.get("display_name") or "?"
    kind = candidate.get("type") or "resource"
    return f"{identifier} [{kind}] via {candidate.get('source') or '?'}"


def ard_discoverer(runtime: Any, description: str = "") -> DiscoverFn:
    """AD-1049's surface as the ladder's discover rung (AD-1194).

    The rung reports "not run" unless the operator enabled
    ``federation.ard.discovery_before_design`` -- the switch AD-1049 reads. The
    surface never adopts and never raises (it degrades to ``[]``), and it still
    emits its advisory event; adopting a candidate stays an explicit Captain act.
    """

    async def _discover(gap_target: str) -> list[str] | None:
        federation = getattr(getattr(runtime, "config", None), "federation", None)
        if getattr(getattr(federation, "ard", None), "discovery_before_design", False) is not True:
            return None
        from probos.federation.ard.adoption import surface_discovery_candidates

        surfaced = await surface_discovery_candidates(
            runtime, {"name": gap_target, "description": description},
        )
        return [candidate_label(candidate) for candidate in surfaced]

    return _discover


_DESIGN_CONTEXT_KEYS = BUILD_PAYLOAD_KEYS


def _build_payload(design_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """BF-744: the design context a later approval needs, and nothing else.

    Bounded to four known keys so a caller cannot use the request payload as an
    open side-channel, and so what a Captain approves is what gets designed.

    AD-1194: normalised to what ``validate_build_payload`` accepts, because that
    is what survives a restart -- anything else would design from here and be
    lost to an approval after one. ``requires_consensus`` keeps ``fulfil_build``'s
    truthiness; texts and parameters are cut to their bounds; a text of the wrong
    type is dropped rather than stringified. Per-field bounds do not bound the
    escaped JSON, so a context still too large sheds its least important fields
    first -- execution context, then parameters, then description -- and never
    the consensus requirement.
    """
    if not isinstance(design_context, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("intent_description", "execution_context"):
        if isinstance(design_context.get(key), str):
            out[key] = _clean(design_context[key], BUILD_TEXT_MAX_CHARS)
    params = design_context.get("parameters")
    if isinstance(params, dict):
        out["parameters"] = {
            _clean(str(name), BUILD_PARAMETER_MAX_CHARS): _clean(str(value), BUILD_PARAMETER_MAX_CHARS)
            for name, value in list(params.items())[:MAX_BUILD_PARAMETERS]
        }
    if "requires_consensus" in design_context:
        out["requires_consensus"] = bool(design_context["requires_consensus"])
    for field in ("execution_context", "parameters", "intent_description"):
        if validate_build_payload(out) is not None:
            break
        logger.warning(
            "AD-1194: a build design context is over its bound; dropping %s so the "
            "rest, and the consensus requirement, survive a restart", field,
        )
        out.pop(field, None)
    return out or None


async def triage_and_file(
    *,
    gap_target: str,
    agent_id: str,
    store: CapabilityRequestStore,
    rationale: str = "",
    work_item_id: str | None = None,
    tool_registry: Any = None,
    permission_store: ToolPermissionStore | None = None,
    mcp_server_store: Any = None,
    ontology: Any = None,
    trust_network: Any = None,
    self_mod_pipeline: Any = None,
    design_context: dict[str, Any] | None = None,
    config: CapabilityTriageConfig | None = None,
    gap_class: GapClass = "tool",
    unified: bool = False,
    discover_candidates: DiscoverFn | None = None,
) -> CapabilityRequest:
    """Resolve a capability gap to a rung, file the request, and route fulfilment.

    Gathers the three booleans from the live registries, calls the pure ``triage``,
    files a :class:`CapabilityRequest` (AD-853, carrying ``work_item_id``), and on
    approval routes to the existing fulfiller for that rung:

      - **grant** — auto-approved when the grant fast path passes, then issued via
        ``ToolPermissionStore.issue_grant`` and marked fulfilled; otherwise left
        pending for the Captain. A grant of the AD-1213 review tool is always
        left pending: conferring decision authority is the Captain's alone.
      - **install** — always left pending for Captain approval (no fast path).
      - **build** — routed to ``self_mod_pipeline.handle_unhandled_intent`` which
        owns its own approval gate; marked fulfilled on a successful build.

    Honest-degrades to ``build`` (logged) when the registries needed to resolve a
    cheaper rung are absent.

    AD-1194: with ``unified=True`` the gap walks the whole ladder instead, for a
    ``gap_class`` of ``tool`` (AD-855), ``intent`` (the NL path) or ``package``
    (AD-1220). Every rung's verdict is recorded on the request, and a build is
    left PENDING for the Captain rather than designed here. ``unified=False`` is
    the body below, unchanged, and ignores the three AD-1194 parameters.
    """
    if unified:
        return await _file_through_ladder(
            gap_target=gap_target,
            gap_class=gap_class,
            agent_id=agent_id,
            store=store,
            rationale=rationale,
            work_item_id=work_item_id,
            tool_registry=tool_registry,
            permission_store=permission_store,
            mcp_server_store=mcp_server_store,
            ontology=ontology,
            trust_network=trust_network,
            design_context=design_context,
            discover_candidates=discover_candidates,
            config=config,
        )
    tool_reg = tool_registry.get(gap_target) if tool_registry is not None else None
    tool_registered = tool_reg is not None
    has_permission = _agent_has_permission(permission_store, agent_id, gap_target)
    # AD-1215: the install rung means "enable a registered MCP server". It used to
    # ask an ``extension_registry`` that no runtime ever assigned, so skill_known
    # was unconditionally False and this rung could never be selected.
    selected_server = resolve_installable_mcp_server(mcp_server_store, gap_target)
    skill_known = selected_server is not None

    if tool_registry is None and mcp_server_store is None:
        logger.warning(
            "AD-854: triage for %r has no tool/MCP registry; "
            "honest-degrading toward build",
            gap_target,
        )

    kind = triage(
        tool_registered=tool_registered,
        agent_has_permission=has_permission,
        skill_known=skill_known,
    )

    req = await store.file_request(
        agent_id=agent_id,
        kind=kind,
        target=gap_target,
        rationale=rationale,
        work_item_id=work_item_id,
        # BF-744: the design context rides on the request so a build reached
        # LATER, through Captain approval, is designed with the same governance
        # properties as one built at file time. Without it, approving a pending
        # build produced an agent with requires_consensus=False regardless of
        # what the gap actually asked for.
        payload=(
            {"install_kind": "mcp", "mcp_server_id": selected_server.id}
            if kind == "install"
            else _build_payload(design_context) if kind == "build" else None
        ),
    )
    logger.info(
        "AD-854: triaged %r for %s -> %s (request %s)",
        gap_target, agent_id, kind, req.id[:12],
    )

    if kind == "grant":
        return await _route_grant(
            req,
            store=store,
            agent_id=agent_id,
            tool_id=gap_target,
            tool_registration=tool_reg,
            permission_store=permission_store,
            ontology=ontology,
            trust_network=trust_network,
            config=config,
        )
    if kind == "build":
        return await _route_build(
            req,
            store=store,
            gap_target=gap_target,
            rationale=rationale,
            self_mod_pipeline=self_mod_pipeline,
            design_context=design_context,
        )
    # install: always Captain-gated — leave pending.
    return req


async def _file_through_ladder(
    *,
    gap_target: str,
    gap_class: GapClass,
    agent_id: str,
    store: CapabilityRequestStore,
    rationale: str,
    work_item_id: str | None,
    tool_registry: Any,
    permission_store: ToolPermissionStore | None,
    mcp_server_store: Any,
    ontology: Any,
    trust_network: Any,
    design_context: dict[str, Any] | None,
    discover_candidates: DiscoverFn | None,
    config: CapabilityTriageConfig | None,
) -> CapabilityRequest:
    """AD-1194: evaluate the whole ladder, record it on the request, file it.

    Only a grant may still be fulfilled at file time, through the unchanged fast
    path. An install and a build are always left pending for the Captain. A build
    is never designed here: the pipeline's own approval gate refuses a design when no
    console callback is wired (BF-877) and otherwise asks a console, so a file-time
    build is not one the Captain approved.
    """
    tool_reg: Any = None
    selected_server: Any = None
    tool_registered = agent_has_permission = skill_known = False
    if gap_class == "tool":
        if tool_registry is None and mcp_server_store is None:
            logger.warning(
                "AD-1194: tool gap %r has no tool/MCP registry to resolve against; "
                "the ladder records it as unregistered and escalates toward build",
                gap_target,
            )
        tool_reg = tool_registry.get(gap_target) if tool_registry is not None else None
        tool_registered = tool_reg is not None
        agent_has_permission = _agent_has_permission(permission_store, agent_id, gap_target)
        selected_server = resolve_installable_mcp_server(mcp_server_store, gap_target)
        skill_known = selected_server is not None
    evidence = {
        "tool_registered": tool_registered,
        "agent_has_permission": agent_has_permission,
        "skill_known": skill_known,
    }
    discovery: list[str] | None = None
    if discover_candidates is not None and _discovery_applies(
        gap_class, evaluate_ladder(gap_class=gap_class, **evidence).selected,
    ):
        discovery = await _run_discovery(discover_candidates, gap_target)
    record = evaluate_ladder(gap_class=gap_class, discovery=discovery, **evidence)
    kind = record.selected
    payload: dict[str, Any] | None = None
    if kind == "install":
        payload = (
            {"install_kind": "python"} if gap_class == "package"
            else {"install_kind": "mcp", "mcp_server_id": selected_server.id}
        )
    elif kind == "build":
        payload = _build_payload(design_context)
    req = await store.file_request(
        agent_id=agent_id,
        kind=kind,
        target=gap_target,
        rationale=rationale,
        work_item_id=work_item_id,
        payload=payload,
        triage=record.to_dict(),
    )
    logger.info(
        "AD-1194: %s gap %r for %s -> %s (request %s; %s)",
        gap_class, gap_target, agent_id, kind, req.id[:12],
        ", ".join(f"{verdict.rung}={verdict.outcome}" for verdict in record.rungs),
    )
    if kind == "grant":
        return await _route_grant(
            req,
            store=store,
            agent_id=agent_id,
            tool_id=gap_target,
            tool_registration=tool_reg,
            permission_store=permission_store,
            ontology=ontology,
            trust_network=trust_network,
            config=config,
        )
    return req


async def _run_discovery(discover: DiscoverFn, gap_target: str) -> list[str] | None:
    """Run the discover rung. Advisory: a failure is recorded as not run, never blocks filing."""
    try:
        found = await discover(gap_target)
    except Exception:
        logger.warning(
            "AD-1194: the discover rung failed for %r; recording it as not run and "
            "filing without candidates", gap_target, exc_info=True,
        )
        return None
    if not isinstance(found, list):
        return None
    return [str(candidate) for candidate in found][:TRIAGE_MAX_CANDIDATES]


async def _route_grant(
    req: CapabilityRequest,
    *,
    store: CapabilityRequestStore,
    agent_id: str,
    tool_id: str,
    tool_registration: Any,
    permission_store: ToolPermissionStore | None,
    ontology: Any,
    trust_network: Any,
    config: CapabilityTriageConfig | None,
) -> CapabilityRequest:
    """Evaluate the grant fast path; auto-approve + issue + fulfil when it passes."""
    if tool_id == REVIEW_TOOL_ID:
        # AD-1213: this grant confers authority to decide other agents' requests,
        # so it is the Captain's alone and the fast path never applies to it.
        logger.info(
            "AD-1213: a grant of %s to %s confers decision authority; request %s is "
            "left pending for the Captain",
            tool_id, agent_id, req.id[:12],
        )
        return req
    permission = _derive_tool_permission(tool_registration)
    non_destructive = _is_non_destructive(permission)

    grants: list[Any] = []
    if permission_store is not None:
        grants = await permission_store.list_grants(active_only=True)
    peer_precedent = _peer_precedent(
        grants, tool_id=tool_id, requester_id=agent_id, ontology=ontology
    )

    agent_trust = trust_network.get_score(agent_id) if trust_network is not None else 0.0
    fast_path_enabled = config.grant_fast_path_enabled if config is not None else False
    trust_floor = config.grant_trust_floor if config is not None else 1.0

    auto = evaluate_grant_fast_path(
        non_destructive=non_destructive,
        peer_precedent=peer_precedent,
        agent_trust=agent_trust,
        trust_floor=trust_floor,
        fast_path_enabled=fast_path_enabled,
    )
    logger.info(
        "AD-854: grant fast-path for %s on %s -> %s "
        "(non_destructive=%s, peer_precedent=%s, trust=%.3f>=%.3f, enabled=%s)",
        agent_id, tool_id, auto, non_destructive, peer_precedent,
        agent_trust, trust_floor, fast_path_enabled,
    )
    if not auto:
        return req

    if permission_store is None:
        logger.warning(
            "AD-854: grant fast-path passed for %s on %s but no permission store; "
            "leaving request %s pending",
            agent_id, tool_id, req.id[:12],
        )
        return req

    decided = await store.decide(
        req.id,
        approve=True,
        reason="grant fast-path: non-destructive + in-dept peer precedent + trust>=floor",
        decided_by="capability_triage",
    )
    if decided is None:
        # AD-1194 A-2: a ladder filing is decided on its committed row, and another
        # store decided this one first; that decision stands and no grant is issued.
        return await store.get(req.id) or req
    return await fulfil_grant(
        req.id,
        store=store,
        agent_id=agent_id,
        tool_id=tool_id,
        tool_registration=tool_registration,
        permission_store=permission_store,
        reason="AD-854 grant fast-path auto-approval",
        issued_by="capability_triage",
    ) or req


async def _route_build(
    req: CapabilityRequest,
    *,
    store: CapabilityRequestStore,
    gap_target: str,
    rationale: str,
    self_mod_pipeline: Any,
    design_context: dict[str, Any] | None = None,
) -> CapabilityRequest:
    """Route a build rung to the self-modification pipeline (own approval gate)."""
    return await fulfil_build(
        req.id,
        store=store,
        gap_target=gap_target,
        rationale=rationale,
        self_mod_pipeline=self_mod_pipeline,
        design_context=design_context,
    ) or req


# ── The fulfillers: what an approved rung actually DOES ────────────────────
#
# AD-1211. These are the *performing* half, split out from the *evaluating*
# half above so the two callers share one description of each rung:
#
#   * the file-time fast path in this module, when triage auto-approves; and
#   * ``routers/capability_requests._maybe_fulfil_on_approval``, when the
#     Captain approves a request that was left pending.
#
# Only the first caller existed before AD-1211, so approving a pending grant,
# install or build recorded the decision and did nothing else — no grant
# issued, no FULFILLED event, and ``CapabilityGapDriver`` (which resumes on
# FULFILLED only) left the linked work item blocked forever.
#
# Each returns the fulfilled request, or ``None`` when it could not fulfil.
# A ``None`` return must mean ``mark_fulfilled`` was NOT called, so the caller
# reports the failure honestly and the Captain can retry it (BF-722).


async def fulfil_grant(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    agent_id: str,
    tool_id: str,
    tool_registration: Any,
    permission_store: ToolPermissionStore | None,
    reason: str,
    issued_by: str,
) -> CapabilityRequest | None:
    """Issue the tool grant an approved ``grant`` request asked for, then fulfil it.

    The permission is derived from the tool's own default matrix rather than
    supplied by the caller, so neither path can grant wider access than the
    tool declares it needs (Minimal Authority). Returns ``None`` without
    marking fulfilled when there is no permission store to issue into.
    """
    if permission_store is None:
        logger.warning(
            "AD-1211: cannot fulfil grant request %s for %s on %s — no tool "
            "permission store is wired; the approval is recorded but no grant "
            "was issued and any work item blocked on it stays blocked",
            request_id[:12], agent_id, tool_id,
        )
        return None
    permission = _derive_tool_permission(tool_registration)
    await permission_store.issue_grant(
        agent_id,
        tool_id,
        permission,
        reason=reason,
        issued_by=issued_by,
    )
    return await store.mark_fulfilled(request_id)


def design_of(gap_target: str, rationale: str, design_context: Any) -> dict[str, Any]:
    """AD-1194 A-2: what a build request designs, from its recorded context.

    The one derivation: :func:`fulfil_build` designs with it, and the attended NL
    surfaces show and design the same, as ``handle_unhandled_intent`` keywords.
    """
    ctx = design_context if isinstance(design_context, dict) else {}
    params = ctx.get("parameters")
    return {
        "intent_name": gap_target,
        "intent_description": str(
            ctx.get("intent_description") or rationale or f"Capability gap: {gap_target}"
        ),
        "parameters": params if isinstance(params, dict) else {},
        "requires_consensus": build_requires_consensus(ctx),
        "execution_context": str(ctx.get("execution_context") or ""),
    }


async def fulfil_build(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    gap_target: str,
    rationale: str,
    self_mod_pipeline: Any,
    design_context: dict[str, Any] | None = None,
    pre_approved: bool = False,
) -> CapabilityRequest | None:
    """Run the self-mod pipeline for an approved ``build`` request, then fulfil it.

    Only an ``active`` record counts as built. The pipeline owns its own
    approval gate and its own failure modes, so anything else — ``None``, or a
    record that was rejected or never activated — leaves the request
    approved-and-unfulfilled and therefore retriable, rather than announcing an
    agent that does not exist.

    BF-744: ``design_context`` carries the four things this call used to drop.
    It passed three positionals — name, rationale, ``{}`` — so
    ``requires_consensus`` took its ``False`` default and every agent designed
    through the capability ladder shipped WITHOUT a consensus gate, however
    destructive the gap was. That contradicts the standing rule that destructive
    intents must set ``requires_consensus=True``. Absent context reproduces the
    old call exactly, so a caller that has none is unchanged.

    AD-1194: ``pre_approved`` says the Captain already approved this design on
    the capability-request route, so the pipeline's own prompt is not asked
    again. It is forwarded only when true, so every other call is unchanged.
    """
    if self_mod_pipeline is None:
        logger.warning(
            "AD-1211: cannot fulfil build request %s for %r — no self-mod "
            "pipeline is wired; the approval is recorded but nothing was built "
            "and any work item blocked on it stays blocked",
            request_id[:12], gap_target,
        )
        return None
    design = design_of(gap_target, rationale, design_context)
    record = await self_mod_pipeline.handle_unhandled_intent(
        design["intent_name"],
        design["intent_description"],
        design["parameters"],
        requires_consensus=design["requires_consensus"],
        execution_context=design["execution_context"],
        **({"pre_approved": True} if pre_approved else {}),
    )
    status = getattr(record, "status", None) if record is not None else None
    if status != "active":
        logger.warning(
            "AD-1211: build for %r (request %s) produced no active agent "
            "(status=%r); the approval stands, the request is not fulfilled "
            "and can be retried",
            gap_target, request_id[:12], status,
        )
        return None
    return await store.mark_fulfilled(request_id)


async def fulfil_install(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    target: str,
    runtime: Any,
) -> CapabilityRequest | None:
    """Install what an approved ``install`` request asked for, then fulfil it.

    Typed provenance selects either the recorded MCP ID or a Python dependency.
    MCP registration (with exact-client reuse) precedes durable enablement and
    fulfilment. Python installs use ``ensure_dependency(pre_approved=True)``
    independently of the MCP store. Legacy approvals only permit dependency
    fallback when a readable or absent MCP store proves no identity collision;
    ambiguity needs a newly typed request and fresh approval.

    Returns ``None`` without marking fulfilled when neither actor can satisfy the
    target or the install did not succeed.

    There is no file-time caller: triage leaves every ``install`` rung pending
    for the Captain, so unlike ``fulfil_grant`` / ``fulfil_build`` this one is
    reached from the approval path alone.
    """
    request = await store.get(request_id)
    if (
        request is None
        or request.kind != "install"
        or request.status != "approved"
        or request.target != target
    ):
        logger.warning(
            "Install request %s is not an approved install for this target; "
            "no installation attempted and fulfilment refused", request_id[:12],
        )
        return None
    if type(target) is not str or not target.strip():
        logger.warning(
            "AD-1236: install request %s has an empty target; no installation "
            "attempted and the request remains unfulfilled", request_id[:12],
        )
        return None
    payload = validate_install_payload(request.payload)
    if request.payload is not None and payload is None:
        logger.warning(
            "Install request %s has invalid provenance; no installation "
            "attempted, a newly typed request requires fresh approval", request_id[:12],
        )
        return None
    if payload is None or payload["install_kind"] == "mcp":
        mcp_server_store = getattr(runtime, "mcp_server_store", None)
        try:
            records = mcp_server_store.list_sync() if mcp_server_store is not None else []
        except Exception:
            logger.warning(
                "MCP store unreadable for install request %s; leaving unfulfilled "
                "without dependency installation. Legacy requests need a newly "
                "typed request through the producer and fresh approval", request_id[:12],
            )
            return None
        if payload is None:
            if any(record.id == target or record.name == target for record in records):
                logger.warning(
                    "Legacy install request %s collides with an MCP identity; "
                    "neither action is authorized. A newly typed request through "
                    "the producer requires fresh approval", request_id[:12],
                )
                return None
        else:
            server = next(
                (record for record in records if record.id == payload["mcp_server_id"]),
                None,
            )
            if server is None:
                logger.warning(
                    "Recorded MCP server for install request %s is unavailable; "
                    "leaving approved and unfulfilled without dependency installation",
                    request_id[:12],
                )
                return None
            if not await register_record(runtime, server, require_ready=True):
                return None
            enabled = await mcp_server_store.set_enabled(server.id, True)
            if enabled is None or enabled.id != server.id or not enabled.enabled:
                logger.warning(
                    "MCP enablement for request %s returned no enabled record; "
                    "keeping the registered client for retry without fulfilment",
                    request_id[:12],
                )
                return None
            logger.info(
                "MCP server %s registered and enabled for approved install request "
                "%s; marking fulfilled", server.id, request_id[:12],
            )
            return await store.mark_fulfilled(request_id)

    if validate_python_install_target(target) is None:
        logger.warning(
            "Python install request %s does not name one canonical import; "
            "no dependency installation attempted and the approval stays unfulfilled",
            request_id[:12],
        )
        return None
    ensure = getattr(runtime, "ensure_dependency", None)
    if not callable(ensure):
        logger.warning(
            "AD-1211: cannot fulfil install request %s for %r — no "
            "dependency fulfiller is available via runtime.ensure_dependency; "
            "the approval is recorded but nothing was installed and any blocked "
            "work item stays blocked",
            request_id[:12], target,
        )
        return None
    result = await ensure(target, pre_approved=True)
    if not getattr(result, "success", False):
        logger.warning(
            "AD-1211: installing %r for request %s did not succeed (%s); the "
            "approval stands, the request is not fulfilled and can be retried",
            target, request_id[:12],
            getattr(result, "error", None) or "no error reported",
        )
        return None
    return await store.mark_fulfilled(request_id)
