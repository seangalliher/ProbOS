"""AD-706: BrowserSession — one Playwright BrowserContext per agent session.

Lazy import: ``from playwright.async_api import async_playwright`` happens
inside ``start()``, NOT module-level. Missing optional dep at import time
must not crash startup.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from probos.config import BrowserToolConfig

logger = logging.getLogger(__name__)


@dataclass
class _DomainRateState:
    """Per-domain rate state for BrowserSession.

    Deliberately a redefinition of ``probos.agents.http_fetch.DomainRateState``
    rather than an import: BrowserSession has different semantics than
    HttpFetchAgent. Specifically:

    * Default ``min_interval_seconds`` is governed by
      ``BrowserToolConfig.default_min_interval_seconds`` (1.0s), not
      HttpFetchAgent's CoinGecko-tuned 2.0/3.0s defaults.
    * No 429-driven adaptive backoff: Playwright does not surface
      ``Retry-After`` / ``X-RateLimit-*`` headers uniformly across navigation,
      click, and type actions, so the ``consecutive_429s`` field exists for
      future symmetry only and is not currently incremented.
    * The state dict is BrowserSession-scoped (per-tool), not shared with the
      HTTP fetch agent's class-level dict.
    """

    last_request_at: float = 0.0
    min_interval_seconds: float = 1.0
    consecutive_429s: int = 0  # reserved; not incremented in v1 (see docstring)


class BrowserSession:
    """Wraps a Playwright BrowserContext with per-domain rate limiting and TTL."""

    # Per-domain rate limiting (BrowserSession-scoped, NOT shared with HttpFetchAgent —
    # browser sessions have different cadence than HTTP fetches).
    _domain_state: ClassVar[dict[str, _DomainRateState]] = {}

    def __init__(
        self,
        *,
        session_id: str,
        config: BrowserToolConfig,
        agent_id: str,
    ) -> None:
        self.session_id = session_id
        self._config = config
        self._agent_id = agent_id
        self._created_at = time.time()
        # Most recent state() snapshot — index -> {selector, role, text, ...}
        self._last_state_index: list[dict[str, Any]] = []
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        # Last URL we navigated to (used by tier classifier for click/type)
        self._last_url: str = ""
        # AD-706c-2: compute_use trust budget. ``_compute_use_consecutive_autonomous``
        # resets on any Captain ACK; ``_compute_use_total_calls`` only resets
        # when the session is destroyed.
        self._compute_use_consecutive_autonomous: int = 0
        self._compute_use_total_calls: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch Chromium and open a fresh BrowserContext.

        Lazy import — ``playwright`` is an optional dependency. The default
        install must not crash on missing playwright.
        """
        # Lazy import — see class docstring.
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._config.headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        try:
            self._page.set_default_timeout(self._config.default_timeout_ms)
        except Exception:
            logger.debug("AD-706: set_default_timeout failed", exc_info=True)

    async def stop(self) -> None:
        """Close everything in reverse order. Idempotent."""
        for closer, attr in [
            (self._page, "_page"),
            (self._context, "_context"),
            (self._browser, "_browser"),
        ]:
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    logger.debug("AD-706: close %s failed", attr, exc_info=True)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("AD-706: playwright.stop failed", exc_info=True)
        self._page = self._context = self._browser = self._playwright = None

    def is_expired(self) -> bool:
        """TTL check vs ``BrowserToolConfig.session_max_duration_seconds``."""
        return (time.time() - self._created_at) >= self._config.session_max_duration_seconds

    def get_streaming_url(self) -> str | None:
        """v1: returns None.

        v2 hook for the Captain-watch surface (CDP/WebSocket bridge into an
        iframe served via routers/system.py's ``ui://`` resource path).
        Populated in AD-706a.
        """
        return None

    # ------------------------------------------------------------------
    # State snapshot bookkeeping
    # ------------------------------------------------------------------

    def record_state_snapshot(self, elements: list[dict[str, Any]]) -> None:
        """Store the most recent ``state()`` indexed-element list.

        Called by the ``state`` action handler so subsequent ``click(index=N)``
        and ``type(index=N, ...)`` calls can resolve N to a concrete selector.
        """
        self._last_state_index = list(elements)

    def resolve_index(self, index: int) -> dict[str, Any] | None:
        """Look up an element record by its state-snapshot index."""
        if 0 <= index < len(self._last_state_index):
            return self._last_state_index[index]
        return None

    @property
    def page(self) -> Any:
        """Active Playwright Page handle (or test fake)."""
        return self._page

    @property
    def last_url(self) -> str:
        return self._last_url

    def set_last_url(self, url: str) -> None:
        self._last_url = url

    # ------------------------------------------------------------------
    # AD-706c-2: compute_use trust budget
    # ------------------------------------------------------------------

    @property
    def compute_use_consecutive_autonomous(self) -> int:
        """Count of compute_use_click calls since the last Captain ACK."""
        return self._compute_use_consecutive_autonomous

    @property
    def compute_use_total_calls(self) -> int:
        """Lifetime count of compute_use_click calls on this session."""
        return self._compute_use_total_calls

    def note_compute_use_call(self) -> None:
        """Increment both counters. Called once per executed compute_use_click."""
        self._compute_use_consecutive_autonomous += 1
        self._compute_use_total_calls += 1

    def note_captain_ack(self) -> None:
        """Reset the consecutive-autonomous counter. Called when the Captain
        ACKs ANY tier-3 action — the ACK signals fresh oversight, so the
        autonomous-streak budget refreshes.
        """
        self._compute_use_consecutive_autonomous = 0

    # ------------------------------------------------------------------
    # Per-domain rate limiting
    # ------------------------------------------------------------------

    def get_domain_state(self, domain: str) -> _DomainRateState:
        """Look up or create rate state for the given domain (lower-cased host)."""
        key = (domain or "").lower()
        state = self._domain_state.get(key)
        if state is None:
            state = _DomainRateState(
                min_interval_seconds=self._config.default_min_interval_seconds,
            )
            self._domain_state[key] = state
        return state

    async def wait_for_rate_limit(self, domain: str) -> float:
        """Sleep if the domain was hit too recently. Returns the delay applied."""
        import asyncio

        if not domain:
            return 0.0
        state = self.get_domain_state(domain)
        now = time.monotonic()
        wait = 0.0
        if state.last_request_at > 0:
            elapsed = now - state.last_request_at
            if elapsed < state.min_interval_seconds:
                wait = state.min_interval_seconds - elapsed
        if wait > 0:
            wait = min(wait, 10.0)  # cap at 10s, matching http_fetch.py discipline
            logger.debug("AD-706: rate limit courtesy delay %.3fs for %s", wait, domain)
            await asyncio.sleep(wait)
        state.last_request_at = time.monotonic()
        return wait
