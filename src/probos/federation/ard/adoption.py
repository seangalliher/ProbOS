"""AD-1049: governed discovery-before-design + explicit gated adopt/connect.

DD-1 governed adoption: this module adds the CONSUME-side actions that AD-1046
deliberately stopped short of — but every action is GOVERNED and default-OFF.

  * :func:`surface_discovery_candidates` — the discovery-before-design hook. BEFORE
    the self-mod pipeline designs a brand-new agent for a capability gap, it
    SURFACES any already-published resource (the ship's own catalog + the
    operator-configured discovery endpoints) that may already satisfy the intent,
    so a human can choose to connect an existing, trusted resource instead of
    growing the agent population. It VERIFIES (pure ``verify_entry``) and EMITS an
    advisory event — it NEVER permission-checks (there is no agent identity at
    DESIGN time) and NEVER adopts. The whole body is Tier-2 honest-degrade: any
    failure returns ``[]`` and lets the design path proceed unchanged.

  * :func:`connect_candidate` — the EXPLICIT, gated adopt. Strict ordering —
    permission → trust → connect — so a denied connect NEVER seeds trust and an
    under-trusted connect NEVER touches the bridge. v1 connects MCP-http servers
    only; any other resource type honest-degrades to ``connect_not_supported_v1``
    (no A2A / skill invocation, no signature issuance — those are later / commercial).

DD-8 layer discipline: imports ONLY the sibling pure ARD modules (+ stdlib). It
reads collaborators (``trust_network`` / ``tool_permission_store`` / ``mcp_bridge``)
off the runtime by public attribute, never reaching into private state.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from .access import ard_access_for_agent
from .catalog import CatalogEntry
from .catalog_projector import get_cached_catalog
from .client import ArdClient
from .media_types import MT_MCP_SERVER
from .registry_query import search_entries
from .trust_verifier import seed_trust_prior, verify_entry

logger = logging.getLogger(__name__)

# v1 minimum resulting trust score for an explicit connect. A domain-matched
# entry seeds Beta(2, 3) → 0.40 (exactly at the gate, allowed); an entry with no
# publisher-domain match seeds Beta(1, 3) → 0.25 (blocked). So v1 connects only
# resources whose URN publisher domain matches the serving endpoint host.
_DEFAULT_ADOPT_MIN_TRUST = 0.4

# Bound how many candidates the discovery-before-design hook surfaces (and, per
# external endpoint, how many entries it verifies) — a resource guard.
_MAX_SURFACE_CANDIDATES = 5


@dataclass
class AdoptionCandidate:
    """One surfaced discovery candidate (advisory — surfacing is NOT adoption)."""

    identifier: str
    display_name: str
    type: str
    source: str
    url: str = ""
    score: float = 0.0
    domain_match: bool = False


@dataclass
class ConnectResult:
    """The outcome of an explicit, gated :func:`connect_candidate` call."""

    connected: bool
    reason: str
    source: str = ""
    trust_score: float = 0.0


def _discovery_endpoints(runtime: Any) -> list[str]:
    """Read the operator-configured ARD discovery endpoint allowlist (honest-degrade)."""
    cfg = getattr(
        getattr(getattr(runtime, "config", None), "federation", None), "ard", None
    )
    endpoints = getattr(cfg, "discovery_endpoints", None)
    return list(endpoints) if isinstance(endpoints, list) else []


def _endpoint_host(endpoint: str) -> str:
    """Extract the host of a discovery endpoint URL (honest-degrade to ``""``)."""
    try:
        return urlsplit(endpoint).hostname or ""
    except Exception:  # noqa: BLE001 — honest-degrade: a bad URL contributes no host
        return ""


async def surface_discovery_candidates(
    runtime: Any, intent_meta: dict[str, Any]
) -> list[dict[str, Any]]:
    """Surface existing ARD resources that may satisfy a capability gap (governance).

    Discovery-before-design (DD-1): SURFACE — never adopt. Searches the ship's own
    catalog projection AND the operator-configured discovery endpoints for entries
    matching the gapped intent, verifies each external hit with the PURE
    ``verify_entry`` (no trust seeding — there is no agent identity at design time),
    emits an advisory ``ard_discovery_candidates`` event, and returns the surfaced
    candidate dicts (capped at ``_MAX_SURFACE_CANDIDATES``).

    Whole-body Tier-2 honest-degrade: any failure returns ``[]`` so the self-mod
    design path proceeds unchanged. This function NEVER permission-checks and NEVER
    connects — it only informs a human decision.
    """
    try:
        name = str(intent_meta.get("name", "") or "")
        description = str(intent_meta.get("description", "") or "")
        text = f"{name} {description}".strip()

        candidates: list[AdoptionCandidate] = []

        # --- own catalog (ship-local projection) ---------------------------- #
        try:
            own = await get_cached_catalog(runtime)
            for entry in search_entries(own.entries, text)[:_MAX_SURFACE_CANDIDATES]:
                candidates.append(
                    AdoptionCandidate(
                        identifier=entry.identifier,
                        display_name=entry.display_name,
                        type=entry.type,
                        source="own",
                        url=entry.url or "",
                    )
                )
        except Exception:  # noqa: BLE001 — honest-degrade: skip the own axis
            logger.warning(
                "AD-1049: own-catalog discovery surface failed for %s; skipping own axis",
                name,
                exc_info=True,
            )

        # --- external discovery endpoints (verify PURE — never adopt) ------- #
        try:
            endpoints = _discovery_endpoints(runtime)
            if endpoints:
                discovered = await ArdClient().discover(endpoints)
                for disc in discovered:
                    cat = disc.catalog
                    if cat is None:
                        continue
                    host = _endpoint_host(disc.source_endpoint)
                    hits = search_entries(cat.entries, text)[:_MAX_SURFACE_CANDIDATES]
                    for entry in hits:
                        report = verify_entry(entry, endpoint_host=host)
                        candidates.append(
                            AdoptionCandidate(
                                identifier=entry.identifier,
                                display_name=entry.display_name,
                                type=entry.type,
                                source=disc.source_endpoint,
                                url=entry.url or "",
                                score=report.score,
                                domain_match=report.domain_match,
                            )
                        )
        except Exception:  # noqa: BLE001 — honest-degrade: skip the external axis
            logger.warning(
                "AD-1049: external discovery surface failed for %s; skipping external axis",
                name,
                exc_info=True,
            )

        surfaced = [asdict(c) for c in candidates[:_MAX_SURFACE_CANDIDATES]]
        try:
            runtime.emit_event(
                "ard_discovery_candidates",
                {"intent": name, "description": description, "candidates": surfaced},
            )
        except Exception:  # noqa: BLE001 — honest-degrade: an advisory emit never blocks
            logger.warning(
                "AD-1049: emit ard_discovery_candidates failed for %s", name, exc_info=True
            )
        return surfaced
    except Exception:  # noqa: BLE001 — Tier-2: never block the design path
        logger.warning(
            "AD-1049: discovery-before-design surface failed; proceeding to design",
            exc_info=True,
        )
        return []


async def connect_candidate(
    runtime: Any,
    *,
    agent_id: str,
    catalog: str,
    resource: str,
    entry: CatalogEntry,
    endpoint_host: str,
    min_trust: float = _DEFAULT_ADOPT_MIN_TRUST,
    headers: dict[str, str] | None = None,
) -> ConnectResult:
    """Explicit, gated adopt-and-connect of one discovered ARD entry (DD-1).

    Strict ordering — permission → trust → connect — so the side effects of each
    later stage only run once the earlier gate passes:

      1. **Permission FIRST** (``ard_access_for_agent``). If the agent is not
         enabled for ``catalog/resource`` the connect refuses with
         ``permission_denied`` BEFORE any trust record is seeded — a denied connect
         must NEVER have a side effect (no trust seed, no bridge call).
      2. **Trust** (``verify_entry`` + ``seed_trust_prior``). Seed the entry's
         probationary Beta prior ONCE (a no-op if it already has a record), then
         refuse with ``trust_below_threshold`` if the resulting score < ``min_trust``.
      3. **Connect** (v1 = MCP-http only). An ``MT_MCP_SERVER`` entry with a ``url``
         is registered on ``runtime.mcp_bridge`` (``mcp_bridge_unavailable`` when the
         bridge is off; ``mcp_register_failed`` when the bridge refuses a dup/empty
         url). Any other type honest-degrades to ``connect_not_supported_v1`` (no
         A2A / skill invocation in v1).
    """
    # 1. permission FIRST — a denied connect must NEVER seed trust. A missing
    #    store is fail-safe deny (treated as no grant).
    store = getattr(runtime, "tool_permission_store", None)
    enabled, source = (
        ard_access_for_agent(store, agent_id, catalog, resource)
        if store is not None
        else (False, "default")
    )
    if not enabled:
        return ConnectResult(connected=False, reason="permission_denied", source=source)

    # 2. trust — seed the probationary prior ONCE, then gate on min_trust.
    report = verify_entry(entry, endpoint_host=endpoint_host)
    trust_score = seed_trust_prior(runtime.trust_network, entry.identifier, report)
    if trust_score < min_trust:
        return ConnectResult(
            connected=False, reason="trust_below_threshold", trust_score=trust_score
        )

    # 3. connect — v1 supports MCP-http servers only.
    if entry.type == MT_MCP_SERVER and entry.url:
        bridge = getattr(runtime, "mcp_bridge", None)
        if bridge is None:
            return ConnectResult(
                connected=False,
                reason="mcp_bridge_unavailable",
                trust_score=trust_score,
            )
        registered = bridge.register_server(entry.url, headers or None)
        if not registered:
            return ConnectResult(
                connected=False,
                reason="mcp_register_failed",
                source=entry.url,
                trust_score=trust_score,
            )
        return ConnectResult(
            connected=True,
            reason="mcp_registered",
            source=entry.url,
            trust_score=trust_score,
        )

    return ConnectResult(
        connected=False, reason="connect_not_supported_v1", trust_score=trust_score
    )
