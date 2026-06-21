"""AD-1046: ARD discovery client — the consume side of ARD (DD-1 SSRF-guarded).

DD-1 SSRF guard: ``ArdClient`` fetches with a BOUNDED direct ``httpx`` request
using ``follow_redirects=False`` (the SSRF guard the mesh ``http_fetch`` agent
deliberately lacks — see DD-4), a bounded ``timeout`` (``_DEFAULT_TIMEOUT``) and
a truncate-then-parse size cap (``_MAX_CATALOG_BYTES``). It fetches ONLY the
endpoints the caller passes — the operator-configured
``federation.ard.discovery_endpoints`` allowlist — and it NEVER dereferences a
catalog entry's ``url`` field (entry urls are opaque references, not fetch
targets, in v1).

DD-6 honest-degrade: each endpoint is isolated in its own try/except, so one bad
endpoint never breaks the others. DD-5 consume-only: no adoption / connect /
invoke (AD-1049+); this module only fetches + parses public catalog envelopes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from .catalog import AiCatalog
from .catalog_parse import catalog_from_dict

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0
_MAX_CATALOG_BYTES = 2_000_000
_WELL_KNOWN_SUFFIX = "/.well-known/ai-catalog.json"


@dataclass
class DiscoveredCatalog:
    """One discovery result: the parsed catalog OR an isolated error string."""

    source_endpoint: str
    catalog: AiCatalog | None = None
    error: str = ""


class ArdClient:
    """Bounded ARD discovery client (DD-1 SSRF-guarded fetch + parse).

    Pass a pre-built ``http`` (e.g. wrapping an ``httpx.MockTransport``) to inject
    a deterministic transport in tests; otherwise each fetch builds a short-lived
    bounded client and closes it. An injected client is NEVER closed by this
    class — the caller owns its lifecycle. Whether self-created or injected, every
    request passes ``follow_redirects=False`` so the SSRF guard holds regardless
    of an injected client's own default.
    """

    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._http = http
        self._timeout = timeout

    def _well_known_url(self, endpoint: str) -> str:
        """Map a base endpoint to its ``ai-catalog.json`` well-known URL.

        Pass-through if the endpoint already targets a ``.json`` document or a
        ``.well-known`` path; otherwise append the standard well-known suffix.
        """
        ep = endpoint.rstrip("/")
        if ep.endswith(".json") or ".well-known" in ep:
            return endpoint
        return ep + _WELL_KNOWN_SUFFIX

    async def _get_bytes(self, url: str) -> bytes:
        """Bounded SSRF-guarded GET → truncated body bytes.

        ``follow_redirects=False`` is passed on EVERY request (not just the
        client default) so an injected client cannot weaken the guard. The body
        is truncated to ``_MAX_CATALOG_BYTES`` BEFORE parsing.
        """
        if self._http is not None:
            resp = await self._http.get(
                url, follow_redirects=False, timeout=self._timeout
            )
            return resp.content[:_MAX_CATALOG_BYTES]
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=self._timeout
        ) as client:
            resp = await client.get(url, follow_redirects=False, timeout=self._timeout)
            return resp.content[:_MAX_CATALOG_BYTES]

    async def _post_bytes(self, url: str, payload: dict) -> bytes:
        """Bounded SSRF-guarded POST → truncated body bytes (see ``_get_bytes``)."""
        if self._http is not None:
            resp = await self._http.post(
                url, json=payload, follow_redirects=False, timeout=self._timeout
            )
            return resp.content[:_MAX_CATALOG_BYTES]
        async with httpx.AsyncClient(
            follow_redirects=False, timeout=self._timeout
        ) as client:
            resp = await client.post(
                url, json=payload, follow_redirects=False, timeout=self._timeout
            )
            return resp.content[:_MAX_CATALOG_BYTES]

    async def _fetch_manifest(self, endpoint: str) -> DiscoveredCatalog:
        """Fetch + parse one endpoint's catalog; isolate all failures (DD-6)."""
        url = self._well_known_url(endpoint)
        try:
            body = await self._get_bytes(url)
            data = json.loads(body)
            catalog = catalog_from_dict(data)
            return DiscoveredCatalog(source_endpoint=endpoint, catalog=catalog)
        except Exception as exc:  # noqa: BLE001 — DD-6 honest-degrade per endpoint
            logger.warning(
                "AD-1046: ARD discovery failed for %s (%s); skipping endpoint",
                endpoint,
                exc,
            )
            return DiscoveredCatalog(source_endpoint=endpoint, error=str(exc))

    async def discover(self, endpoints: list[str]) -> list[DiscoveredCatalog]:
        """Fetch every endpoint's catalog; one bad endpoint never breaks others.

        Returns one ``DiscoveredCatalog`` per endpoint (preserving input order).
        Fetches ONLY the passed endpoints (the operator allowlist) — never an
        entry's ``url`` field.
        """
        results: list[DiscoveredCatalog] = []
        for endpoint in endpoints:
            results.append(await self._fetch_manifest(endpoint))
        return results

    async def search_registry(
        self, endpoint: str, *, text: str = "", page_size: int = 20
    ) -> AiCatalog:
        """Query a remote ARD registry's ``POST /ard/search`` (consume-only).

        Bounded + SSRF-guarded like ``discover``. Parses the registry response's
        ``results`` array into an ``AiCatalog``. DD-6 honest-degrade: any failure
        returns an empty catalog.
        """
        url = endpoint.rstrip("/") + "/ard/search"
        payload = {"query": {"text": text}, "pageSize": page_size}
        try:
            body = await self._post_bytes(url, payload)
            data = json.loads(body)
            results = data.get("results", []) if isinstance(data, dict) else []
            return catalog_from_dict({"entries": results})
        except Exception as exc:  # noqa: BLE001 — DD-6 honest-degrade
            logger.warning(
                "AD-1046: ARD registry search failed for %s (%s)", endpoint, exc
            )
            return AiCatalog()
