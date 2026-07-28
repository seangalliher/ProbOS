"""AD-706: BrowserSession — one Playwright BrowserContext per agent session.

Lazy import: ``from playwright.async_api import async_playwright`` happens
inside ``start()``, NOT module-level. Missing optional dep at import time
must not crash startup.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from probos.tools.browser.loop_host import (
    PlaywrightLoopHost,
    get_playwright_host,
    loop_supports_subprocess,
    wrap_host_object,
)

if TYPE_CHECKING:
    from probos.config import BrowserToolConfig

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


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


# AD-1052c: human-forwarded single keys (NO destructive modifier combos in v1 —
# Control+W etc. are the AD-706e tier-3 surface, deferred to a later slice).
_FORWARD_KEY_ALLOWLIST: frozenset[str] = frozenset({
    "Enter", "Tab", "Backspace", "Delete", "Escape",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown",
})
_FORWARD_TEXT_MAX: int = 4096  # mirror _EVAL_JS_MAX_SCRIPT_LEN — bound the burst


def _clamp01(v: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


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
        emit_event: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self._config = config
        self._agent_id = agent_id
        self._emit_event = emit_event
        self._created_at = time.time()
        # Most recent state() snapshot — index -> {selector, role, text, ...}
        self._last_state_index: list[dict[str, Any]] = []
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        # BF-695: set when this session's Playwright objects live on the
        # dedicated host loop. None means the running loop can spawn
        # subprocesses and every call goes straight through, unchanged.
        self._host: PlaywrightLoopHost | None = None
        self._host_checked: bool = False
        self._page_proxy: Any = None
        # AD-1052b: True when this session attached to an EXTERNAL browser via
        # connect_over_cdp. A connected session must NOT close the user's page/
        # context/browser on stop() — only disconnect.
        self._connected: bool = False
        # Last URL we navigated to (used by tier classifier for click/type)
        self._last_url: str = ""
        # AD-706c-2: compute_use trust budget. ``_compute_use_consecutive_autonomous``
        # resets on any Captain ACK; ``_compute_use_total_calls`` only resets
        # when the session is destroyed.
        self._compute_use_consecutive_autonomous: int = 0
        self._compute_use_total_calls: int = 0
        # AD-706b: recording-on-disk bookkeeping. Populated by start() when
        # ``recording_enabled`` is True; consulted by stop() to emit
        # BROWSER_RECORDING_STOPPED / FAILED events.
        self._recording_path: Path | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _ensure_host(self) -> None:
        """BF-695: decide ONCE whether Playwright needs the dedicated host loop.

        Evaluated on the loop that is about to own the session. When that loop
        can spawn subprocesses — every non-Windows platform, and Windows still
        on Proactor — nothing is started and every later call runs inline, so
        the behaviour is exactly what it was before BF-695.
        """
        if self._host_checked:
            return
        self._host_checked = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if loop_supports_subprocess(loop):
            return
        host = get_playwright_host()
        host.start()
        self._host = host
        logger.info(
            "BF-695: %s cannot spawn subprocesses, so browser session %s runs "
            "Playwright on the dedicated host loop; page calls marshal across "
            "the thread boundary.",
            type(loop).__name__, self.session_id,
        )

    async def _run_hosted(
        self, factory: Callable[[], Coroutine[Any, Any, _T]],
    ) -> _T:
        """Run ``factory()`` wherever this session's Playwright objects live."""
        host = self._host
        if host is None:
            return await factory()
        return await host.run(factory)

    async def start(self) -> None:
        """Launch Chromium and open a fresh BrowserContext."""
        self._ensure_host()
        try:
            await self._run_hosted(self._start_impl)
        finally:
            # BF-695: emitted here rather than inside ``_start_impl`` so the
            # runtime's event bus is always touched from the caller's loop,
            # never from the Playwright host thread. The ``finally`` keeps
            # STARTED paired with the STOPPED/FAILED that ``stop()`` emits off
            # the same ``_recording_path``: recording begins the moment the
            # video-enabled context exists, so a later failure while opening
            # the page must not leave a STOPPED with no STARTED.
            if self._recording_path is not None:
                self._emit_recording_event(
                    "BROWSER_RECORDING_STARTED",
                    {"session_id": self.session_id, "path": str(self._recording_path)},
                )

    async def _start_impl(self) -> None:
        """Playwright half of ``start()``. Runs on whichever loop owns the objects.

        Lazy import — ``playwright`` is an optional dependency. The default
        install must not crash on missing playwright.
        """
        # Lazy import — see class docstring.
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        self._page_proxy = None
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._config.headless)
        # AD-706b: opt-in video recording via Playwright record_video_dir.
        if getattr(self._config, "recording_enabled", False):
            recording_path = Path(
                getattr(self._config, "recording_dir", "data/browser-sessions")
            ) / self.session_id
            recording_path.mkdir(parents=True, exist_ok=True)
            self._recording_path = recording_path
            self._context = await self._browser.new_context(
                record_video_dir=str(recording_path),
            )
        else:
            self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        try:
            self._page.set_default_timeout(self._config.default_timeout_ms)
        except Exception:
            logger.debug("AD-706: set_default_timeout failed", exc_info=True)

    async def connect(self, endpoint: str) -> None:
        """AD-1052b: attach to an EXTERNAL user-launched browser over CDP."""
        self._ensure_host()
        await self._run_hosted(lambda: self._connect_impl(endpoint))

    async def _connect_impl(self, endpoint: str) -> None:
        """Playwright half of ``connect()``.

        Mirrors ``_start_impl`` but uses ``connect_over_cdp(endpoint)`` instead
        of ``launch()``. Reuses the browser's EXISTING default context + page
        (``contexts[0]`` / ``pages[0]``) so the agent drives the user's real
        logged-in session — a fresh ``new_context()`` would have no cookies.
        """
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        self._page_proxy = None
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._connected = True
        try:
            self._page.set_default_timeout(self._config.default_timeout_ms)
        except Exception:
            logger.debug("AD-1052b: set_default_timeout failed on connected page", exc_info=True)

    async def stop(self) -> None:
        """Close everything in reverse order. Idempotent.

        BF-695: the Playwright teardown runs wherever the objects live; every
        event emit stays on the caller's loop.
        """
        was_bridge = self._connected
        recording_path = self._recording_path
        recording_failed = await self._run_hosted(self._close_playwright)

        if was_bridge:
            if self._emit_event is not None:
                try:
                    from probos.events import EventType
                    self._emit_event(EventType.BROWSER_BRIDGE_DISCONNECTED, {"session_id": self.session_id})
                except Exception:
                    logger.debug("AD-1052b: disconnect event emit failed", exc_info=True)
            return

        # AD-706b: emit recording lifecycle event after context.close() finalizes
        # the .webm file. Tier-2: failures never raise.
        if recording_path is not None:
            if recording_failed:
                self._emit_recording_event(
                    "BROWSER_RECORDING_FAILED",
                    {
                        "session_id": self.session_id,
                        "path": str(recording_path),
                    },
                )
            else:
                size = 0
                try:
                    for webm in recording_path.glob("*.webm"):
                        size += webm.stat().st_size
                except Exception:
                    logger.warning(
                        "AD-706b: failed to compute recording size for %s",
                        recording_path,
                        exc_info=True,
                    )
                self._emit_recording_event(
                    "BROWSER_RECORDING_STOPPED",
                    {
                        "session_id": self.session_id,
                        "path": str(recording_path),
                        "size_bytes": size,
                    },
                )
            self._recording_path = None

    async def _close_playwright(self) -> bool:
        """Playwright half of ``stop()``. Returns True when recording finalize failed.

        Runs wherever this session's Playwright objects live. Emits nothing —
        ``stop()`` owns every event so the runtime's bus is only ever touched
        from the caller's loop.
        """
        self._page_proxy = None
        # AD-1052b: a bridge session attaches to the user's REAL browser. NEVER
        # close the user's page/context (their tabs/session). browser.close() over
        # connect_over_cdp DISCONNECTS from the browser server (Playwright docs) —
        # it does NOT quit the user's Chrome.
        if self._connected:
            if self._browser is not None:
                try:
                    await self._browser.close()  # disconnect, not terminate
                except Exception:
                    logger.debug("AD-1052b: bridge disconnect failed", exc_info=True)
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    logger.debug("AD-1052b: playwright.stop failed (bridge)", exc_info=True)
            self._page = self._context = self._browser = self._playwright = None
            self._connected = False
            return False

        recording_failed = False
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
                    # AD-706b: record_video finalization happens during
                    # _context.close(); flag the failure here.
                    if attr == "_context" and self._recording_path is not None:
                        recording_failed = True
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.debug("AD-706: playwright.stop failed", exc_info=True)
        self._page = self._context = self._browser = self._playwright = None
        return recording_failed

    def _emit_recording_event(self, event_name: str, payload: dict[str, Any]) -> None:
        """AD-706b: best-effort event emit (Tier-2 log-and-degrade)."""
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType
            event_type = getattr(EventType, event_name)
            self._emit_event(event_type, payload)
        except Exception:
            logger.debug(
                "AD-706b: recording event emit failed for %s", event_name,
                exc_info=True,
            )

    def is_expired(self) -> bool:
        """TTL check vs ``BrowserToolConfig.session_max_duration_seconds``."""
        return (time.time() - self._created_at) >= self._config.session_max_duration_seconds

    def get_streaming_url(self) -> str | None:
        """AD-706a: return MJPEG streaming endpoint when streaming is enabled.

        Returns the path-only URL ``/api/browser/sessions/{sid}/stream`` when
        ``BrowserToolConfig.streaming_enabled`` is True. Returns None when
        disabled (Wave 10 convention #14: default-OFF transitional flag).

        The HXI consumer appends the crew-scope token via the AD-706a
        query-param fallback on ``require_crew_scope``.
        """
        if not getattr(self._config, "streaming_enabled", False):
            return None
        return f"/api/browser/sessions/{self.session_id}/stream"

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
        """Active Playwright Page handle (or test fake).

        BF-695: when this session's Playwright objects live on the dedicated
        host loop, this returns a marshalling proxy instead of the raw page.
        Every async call, every sub-object (``page.mouse``, ``page.keyboard``)
        and every ``async with page.expect_*()`` then crosses to that loop;
        inert data such as ``page.url`` passes through untouched. This is the
        only seam that hands a Playwright object to a caller, so covering it
        covers every touch — actions, compute_use, credentials and the MJPEG
        streamer alike — without a single call-site edit.
        """
        page = self._page
        host = self._host
        if page is None or host is None:
            return page
        proxy = self._page_proxy
        if proxy is None:
            proxy = wrap_host_object(page, host)
            self._page_proxy = proxy
        return proxy

    @property
    def agent_id(self) -> str:
        """AD-1052a: owning agent id (public accessor for the sessions-list endpoint)."""
        return self._agent_id

    @property
    def last_url(self) -> str:
        return self._last_url

    def set_last_url(self, url: str) -> None:
        self._last_url = url

    @property
    def is_connected(self) -> bool:
        """AD-1052b: True for a bridge (connect_over_cdp) session."""
        return self._connected

    # ------------------------------------------------------------------
    # AD-1052c: human input forwarding (the Captain DRIVES the live page)
    # ------------------------------------------------------------------

    def _resolve_viewport(self) -> tuple[int, int]:
        """AD-1052c: real viewport (CSS px) for normalized-coord mapping.

        page.viewport_size is a Playwright Page PROPERTY (dict|None), not a
        coroutine. None for many connect_over_cdp pages -> config fallback.
        """
        page = self.page
        vp = getattr(page, "viewport_size", None) if page is not None else None
        if isinstance(vp, dict):
            w = int(vp.get("width") or 0)
            h = int(vp.get("height") or 0)
            if w > 0 and h > 0:
                return w, h
        return (
            int(getattr(self._config, "viewport_width", 1280)),
            int(getattr(self._config, "viewport_height", 720)),
        )

    async def forward_input(self, event: dict[str, Any]) -> dict[str, Any]:
        """AD-1052c: dispatch ONE human-forwarded input event to the live page.

        Reuses the SAME Playwright primitives the agent path uses
        (``getattr(page, "mouse"/"keyboard", None)``) — NOT the LLM-vision
        ``compute_use_click`` flow. Honest-degrades (``{"forwarded": False,
        "reason": ...}``) on no page / no handle / bad input; never raises.
        v1 kinds: click, type, key (allowlist), scroll.
        """
        page = self.page
        if page is None:
            return {"forwarded": False, "reason": "no_page"}
        kind = event.get("kind")

        if kind == "click":
            mouse = getattr(page, "mouse", None)
            if mouse is None:
                return {"forwarded": False, "reason": "no_mouse"}
            vw, vh = self._resolve_viewport()
            vx = round(_clamp01(event.get("nx", 0.0)) * vw)
            vy = round(_clamp01(event.get("ny", 0.0)) * vh)
            button = event.get("button")
            button = button if button in ("left", "right", "middle") else "left"
            await mouse.click(vx, vy, button=button)
            return {"forwarded": True, "kind": "click", "x": vx, "y": vy, "button": button}

        if kind == "scroll":
            mouse = getattr(page, "mouse", None)
            if mouse is None:
                return {"forwarded": False, "reason": "no_mouse"}
            vw, vh = self._resolve_viewport()
            vx = round(_clamp01(event.get("nx", 0.0)) * vw)
            vy = round(_clamp01(event.get("ny", 0.0)) * vh)
            await mouse.move(vx, vy)
            await mouse.wheel(_as_float(event.get("dx", 0.0)), _as_float(event.get("dy", 0.0)))
            return {"forwarded": True, "kind": "scroll", "x": vx, "y": vy}

        if kind == "type":
            keyboard = getattr(page, "keyboard", None)
            if keyboard is None:
                return {"forwarded": False, "reason": "no_keyboard"}
            text = str(event.get("text") or "")[:_FORWARD_TEXT_MAX]
            await keyboard.type(text)
            return {"forwarded": True, "kind": "type", "len": len(text)}

        if kind == "key":
            keyboard = getattr(page, "keyboard", None)
            if keyboard is None:
                return {"forwarded": False, "reason": "no_keyboard"}
            key = event.get("key")
            if key not in _FORWARD_KEY_ALLOWLIST:
                return {"forwarded": False, "reason": "key_not_allowed"}
            await keyboard.press(key)
            return {"forwarded": True, "kind": "key", "key": key}

        return {"forwarded": False, "reason": "unknown_kind"}

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
