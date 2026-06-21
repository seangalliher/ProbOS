"""AD-1050: federated ARD discovery modes (referral fan-out, mode-gated).

DD-2 referral source: the v1 referral source is
``config.federation.a2a.outbound_peers[].peer_url`` — the ONLY http-addressable
federation peers. The ZeroMQ/NATS mesh peers and the gossiped ``NodeSelfModel``
carry NO http URL (they speak ``tcp://`` / the mesh transport), so they cannot be
fetched as ARD catalogs. This module deliberately does NOT reach into
``FederationRouter`` / ``_router`` for peer addresses.

Mode gate (``config.federation.ard.federation_mode``):
  * ``"none"`` (default) → ``[]`` with NO HTTP call (byte-identical when off).
  * ``"referrals"`` → fan out to the bounded ``a2a.outbound_peers`` via the
    SSRF-guarded ``ArdClient`` (``follow_redirects=False``).
  * ``"auto"`` → honest-degrades to ``"referrals"`` in v1 (a ``FederationRouter``
    trust-ranked peer selection is a documented thin extension, not v1).

DD-8 layer discipline: imports ONLY the sibling pure ARD modules (+ stdlib +
httpx for the injectable transport seam).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .catalog import AiCatalog, CatalogEntry
from .client import ArdClient, DiscoveredCatalog

logger = logging.getLogger(__name__)


def referral_endpoints(config: Any, *, max_peers: int) -> list[str]:
    """Collect bounded http referral endpoints from A2A outbound peers (DD-2).

    Reads ``config.federation.a2a.outbound_peers[].peer_url`` — the only
    http-addressable federation peers — dropping any empty url and capping the
    result at ``max_peers``. ``max_peers <= 0`` is a hard off switch (returns
    ``[]``). Honest-degrade: any malformed config returns ``[]``.
    """
    if max_peers <= 0:
        return []
    try:
        a2a = getattr(getattr(config, "federation", None), "a2a", None)
        peers = getattr(a2a, "outbound_peers", None) or []
        urls = [
            str(getattr(p, "peer_url", "") or "")
            for p in peers
            if str(getattr(p, "peer_url", "") or "")
        ]
        return urls[:max_peers]
    except Exception:  # noqa: BLE001 — honest-degrade: malformed config → no referrals
        logger.warning(
            "AD-1050: referral endpoint collection failed; no referrals", exc_info=True
        )
        return []


async def discover_federated(
    runtime: Any, *, client: httpx.AsyncClient | None = None
) -> list[DiscoveredCatalog]:
    """Fan out ARD discovery to federated referral peers (mode-gated).

    ``federation_mode == "none"`` (the default) returns ``[]`` WITHOUT any HTTP
    call — provably byte-identical when off (a test asserts the injected transport
    is never touched). ``"referrals"`` / ``"auto"`` fetch the bounded
    ``referral_endpoints`` via the SSRF-guarded ``ArdClient`` (``follow_redirects=
    False``). Pass ``client`` (an ``httpx.AsyncClient`` wrapping a ``MockTransport``)
    to inject a deterministic transport in tests.
    """
    cfg = getattr(
        getattr(getattr(runtime, "config", None), "federation", None), "ard", None
    )
    mode = getattr(cfg, "federation_mode", "none")
    if mode == "none":
        return []
    max_peers = int(getattr(cfg, "max_referral_peers", 5) or 0)
    endpoints = referral_endpoints(getattr(runtime, "config", None), max_peers=max_peers)
    if not endpoints:
        return []
    return await ArdClient(http=client).discover(endpoints)


def _catalog_entries(catalog: Any) -> list[CatalogEntry]:
    """Extract entries from an ``AiCatalog`` or ``DiscoveredCatalog`` (honest-degrade)."""
    if isinstance(catalog, DiscoveredCatalog):
        inner = catalog.catalog
        return list(inner.entries) if inner is not None else []
    entries = getattr(catalog, "entries", None)
    return list(entries) if isinstance(entries, list) else []


def merge_catalog_entries(
    catalogs: list[AiCatalog | DiscoveredCatalog],
) -> list[CatalogEntry]:
    """Flatten + dedupe entries across catalogs (dedupe by URN identifier, first-wins).

    Accepts a mixed list of ``AiCatalog`` (flatten ``.entries``) and
    ``DiscoveredCatalog`` (flatten ``.catalog.entries`` when the fetch succeeded).
    Dedupes by ``entry.identifier`` (the URN) keeping the FIRST occurrence, so a
    higher-priority / nearer peer earlier in the list wins an identifier collision.
    """
    seen: set[str] = set()
    merged: list[CatalogEntry] = []
    for catalog in catalogs:
        for entry in _catalog_entries(catalog):
            identifier = entry.identifier
            if identifier in seen:
                continue
            seen.add(identifier)
            merged.append(entry)
    return merged
