"""AD-1051: publish the ship's ARD catalog to a configured registry (default-OFF).

DD-3 publish (default-OFF + secret-free): when ``federation.ard.registry_url`` is
configured, POST the ship's catalog PROJECTION to that registry so a federated
registry can index the ship's capabilities. The posted body is
``get_cached_catalog().to_dict()`` — the SAME projection the public
``/.well-known/ai-catalog.json`` serves, which is DD-7 secret-free by construction
(the AD-1041 projector reads only non-secret fields). A test asserts the posted
JSON carries none of the credential field-name sentinels.

Default-OFF: an empty ``registry_url`` is a no-op (``no_registry_url``) with NO
HTTP call — provably byte-identical when off. SSRF guard: the bounded ``httpx``
POST uses ``follow_redirects=False`` + a bounded timeout, and targets ONLY the
operator-configured ``registry_url`` (never an entry url). Honest-degrade: any
failure returns ``{published: False, reason: str(exc)[:200]}``.

DD-8 layer discipline: imports ONLY the sibling pure projector (+ stdlib + httpx).
No signature ISSUANCE here (that is commercial).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .catalog_projector import get_cached_catalog

logger = logging.getLogger(__name__)

_PUBLISH_TIMEOUT = 10.0


@dataclass
class PublishResult:
    """The outcome of a :func:`publish_catalog` call."""

    published: bool
    status_code: int | None = None
    reason: str = ""


async def publish_catalog(
    runtime: Any, *, http: httpx.AsyncClient | None = None
) -> PublishResult:
    """POST the ship's secret-free catalog projection to the configured registry.

    Default-OFF: an empty ``federation.ard.registry_url`` is a no-op
    (``{published: False, reason: "no_registry_url"}``) with NO HTTP call. Otherwise
    POST ``get_cached_catalog().to_dict()`` (DD-7 secret-free) with a bounded
    ``httpx`` request (``follow_redirects=False`` SSRF guard + ``_PUBLISH_TIMEOUT``).
    ``response.is_success`` → ``published``; a non-2xx is ``http_error`` (carrying
    the status code); any exception honest-degrades to ``str(exc)[:200]``. Pass
    ``http`` (an ``httpx.AsyncClient`` over a ``MockTransport``) to inject a
    deterministic transport in tests.
    """
    cfg = getattr(
        getattr(getattr(runtime, "config", None), "federation", None), "ard", None
    )
    registry_url = str(getattr(cfg, "registry_url", "") or "").strip()
    if not registry_url:
        return PublishResult(published=False, reason="no_registry_url")

    try:
        catalog = await get_cached_catalog(runtime)
        body = catalog.to_dict()
        if http is not None:
            resp = await http.post(
                registry_url,
                json=body,
                follow_redirects=False,
                timeout=_PUBLISH_TIMEOUT,
            )
        else:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=_PUBLISH_TIMEOUT
            ) as client:
                resp = await client.post(
                    registry_url,
                    json=body,
                    follow_redirects=False,
                    timeout=_PUBLISH_TIMEOUT,
                )
        if resp.is_success:
            return PublishResult(published=True, status_code=resp.status_code)
        return PublishResult(
            published=False, status_code=resp.status_code, reason="http_error"
        )
    except Exception as exc:  # noqa: BLE001 — honest-degrade: publish never raises
        logger.warning(
            "AD-1051: catalog publication to %s failed (%s)",
            registry_url,
            exc,
            exc_info=True,
        )
        return PublishResult(published=False, reason=str(exc)[:200])
