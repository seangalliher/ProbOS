"""AD-813: remote skill/pack marketplace BROWSE — fetch + pure parse (read-only).

Client side of the operator-configured marketplace registry. **BROWSE ONLY —
nothing is downloaded, written, scanned, loaded, or executed** (install is a
later slice, AD-813b, behind the operator trust gate). This module only fetches
a registry index document and parses it into inert descriptors.

SSRF guard (the #1 invariant, mirrored from the AD-1046 ``ArdClient``): the
registry URL is the operator-configured value passed in by the caller — never an
entry's own ``url`` field, never a request-supplied host. ``follow_redirects=
False`` is passed on EVERY request so an injected client cannot weaken the guard,
and the body is truncated to ``max_bytes`` BEFORE parsing.

DI: ``http`` is injectable (an ``httpx.AsyncClient`` wrapping a ``MockTransport``)
so the fetch + honest-degrade paths are exercised with no network. An injected
client is NEVER closed by this module — the caller owns its lifecycle.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketplaceEntry:
    """One inert marketplace descriptor (mirrors the AD-1003b scanner shape).

    ``skills`` / ``agents`` list the components the registry entry DECLARES —
    they are opaque names, never opened, fetched, or executed. ``source`` records
    the registry the entry came from (the operator-configured URL).
    """

    name: str
    version: str = ""
    description: str = ""
    skills: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the BROWSE API response."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "skills": list(self.skills),
            "agents": list(self.agents),
            "source": self.source,
        }


@dataclass(frozen=True)
class MarketplaceFetchResult:
    """The result of a marketplace fetch — entries OR an isolated error string.

    ``error`` is a SHORT, generic reason (never an internal message/traceback);
    it is empty on success. Honest-degrade: a fetch failure yields empty
    ``entries`` plus a non-empty ``error`` rather than raising.
    """

    entries: list[MarketplaceEntry]
    error: str = ""


def _coerce_str_list(value: Any) -> list[str]:
    """Coerce a registry field to ``list[str]``, dropping non-strings (honest-degrade)."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def parse_marketplace_index(data: Any, *, source: str = "") -> list[MarketplaceEntry]:
    """Parse a registry index document into inert descriptors (PURE honest-degrade).

    Accepts ``{"packs": [...]}``, ``{"entries": [...]}``, or a bare list of entry
    dicts. Mirrors the AD-1003b scanner descriptor field names, accepting either
    ``skills`` / ``agents`` or the scanner's ``skill_paths`` / ``agent_paths``. A
    malformed entry (non-dict, or missing a usable ``name``) is SKIPPED — one bad
    entry never hides the others, and this function NEVER raises.
    """
    if isinstance(data, dict):
        raw_entries = data.get("packs")
        if raw_entries is None:
            raw_entries = data.get("entries")
        if raw_entries is None:
            raw_entries = []
    elif isinstance(data, list):
        raw_entries = data
    else:
        return []

    if not isinstance(raw_entries, list):
        return []

    entries: list[MarketplaceEntry] = []
    for raw in raw_entries:
        try:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            skills_raw = raw.get("skills")
            if skills_raw is None:
                skills_raw = raw.get("skill_paths")
            agents_raw = raw.get("agents")
            if agents_raw is None:
                agents_raw = raw.get("agent_paths")
            entries.append(
                MarketplaceEntry(
                    name=name,
                    version=str(raw.get("version", "") or ""),
                    description=str(raw.get("description", "") or ""),
                    skills=_coerce_str_list(skills_raw),
                    agents=_coerce_str_list(agents_raw),
                    source=source,
                )
            )
        except Exception:  # noqa: BLE001 — honest-degrade: skip one malformed entry
            logger.warning(
                "AD-813: skipping a malformed marketplace entry; scan continues",
                exc_info=True,
            )
            continue
    return entries


async def fetch_marketplace_index(
    registry_url: str,
    *,
    query: str = "",
    http: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
    max_bytes: int = 2_000_000,
    source: str = "",
) -> MarketplaceFetchResult:
    """Fetch + parse the operator-configured registry index (SSRF-guarded).

    GETs ``registry_url`` (the CONFIGURED host — never request-supplied) with
    ``params={"q": query}`` when ``query`` is non-empty (a SEARCH TERM that never
    changes the host). ``follow_redirects=False`` is passed on EVERY request; the
    body is truncated to ``max_bytes`` before parsing. Uses the injected ``http``
    client when given (and never closes it), else a short-lived owned client.

    Honest-degrade: a ``>= 400`` status, a timeout/network failure, or invalid
    JSON returns an empty :class:`MarketplaceFetchResult` carrying a SHORT generic
    ``error`` — it NEVER raises and NEVER leaks internals into the error string.
    """
    params = {"q": query} if query else None
    try:
        if http is not None:
            resp = await http.get(
                registry_url, params=params, follow_redirects=False, timeout=timeout
            )
        else:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=timeout
            ) as client:
                resp = await client.get(
                    registry_url,
                    params=params,
                    follow_redirects=False,
                    timeout=timeout,
                )
        if resp.status_code >= 400:
            return MarketplaceFetchResult([], error=f"registry returned {resp.status_code}")
        body = resp.content[:max_bytes]
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("AD-813: marketplace registry returned invalid JSON; honest-degrade")
        return MarketplaceFetchResult([], error="invalid registry response")
    except Exception as exc:  # noqa: BLE001 — honest-degrade (never leak internals)
        logger.warning(
            "AD-813: marketplace fetch failed (%s); honest-degrade", type(exc).__name__
        )
        return MarketplaceFetchResult([], error="registry unreachable")

    entries = parse_marketplace_index(data, source=source or registry_url)
    return MarketplaceFetchResult(entries=entries)
