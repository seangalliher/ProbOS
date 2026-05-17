# AD-706a — Captain-watch streaming bridge (MJPEG-over-HTTP v1)

**Status:** Draft v1.
**Closes:** #516.
**Dependencies:** AD-706 BrowserSession. AD-722b-1 `require_crew_scope`. AD-597a `McpAppFrame` (HXI iframe substrate).
**Estimated tests:** +9 pytest + 3 vitest. **0 new pip/npm deps.**

> **Substrate touch-point (Captain review):** Section 5 extends `routers/auth.py:require_crew_scope` to fall back to `?token=` query-param when the `Authorization:` header is absent. This is needed because the `<img src>` element cannot set headers. The extension is small, byte-compatible with existing header-only callers, but it modifies the AD-722b-1 substrate. AD-706b also depends on this extension.

---

## Problem

`BrowserSession.get_streaming_url()` at `src/probos/tools/browser/session.py:117` returns `None` in v1 — the Captain cannot observe what the agent is doing in the browser. Forward-marked from AD-706 (Wave 132).

## Solution

**MJPEG over HTTP**, not WebRTC. Rationale:
- WebRTC requires STUN/TURN + SDP negotiation + a long-lived peer connection. For local-machine HXI watching a local Playwright session, that complexity is unjustified.
- MJPEG is `multipart/x-mixed-replace; boundary=frame` — every browser renders it natively in an `<img>` tag. Zero client-side JS, zero new deps.
- Trade-off: bandwidth (no compression beyond per-frame JPEG) is acceptable for localhost/LAN. Federation streaming is a forward marker (AD-706a-1).

Capture frames via Playwright's `page.screenshot()` at a configurable interval (default 4 fps = 250ms). The screenshot pipeline already exists in `actions.py:_action_screenshot` and `action_verify` — extract the JPEG-encoded path into a reusable helper.

### Section 0 — Event Types

Add to `event_log.py` after `CREDENTIAL_FILL_REQUESTED`:

- `BROWSER_STREAM_OPENED` — Captain-watch viewer connected.
- `BROWSER_STREAM_CLOSED` — viewer disconnected (clean or error).
- `BROWSER_STREAM_FRAME_DROPPED` — backpressure: viewer too slow, frame skipped (logged at debug, event at warning threshold).

### Section 1 — Config

Extend `BrowserToolConfig` in `src/probos/config.py`:

```python
streaming_enabled: bool = False  # default-OFF transitional gate
streaming_fps: int = 4  # ge=1, le=15 — higher fps quickly overwhelms localhost MJPEG
streaming_jpeg_quality: int = 60  # ge=20, le=95
streaming_max_concurrent_viewers: int = 4  # ge=1, le=16
```

### Section 2 — Endpoint

New file `src/probos/routers/browser_stream.py`:

```python
@router.get("/api/browser/sessions/{session_id}/stream", dependencies=[Depends(require_crew_scope)])
async def stream_browser_session(session_id: str, runtime: Any = Depends(get_runtime)):
```

Returns a `StreamingResponse` with `media_type="multipart/x-mixed-replace; boundary=frame"`. The generator:

1. Resolves the session via `runtime.browser_tool.get_session(session_id)` — verify the BrowserTool exposes this method; if not, add `BrowserTool.get_session(session_id) -> BrowserSession | None`.
2. If session not found: HTTP 404.
3. If `cfg.streaming_max_concurrent_viewers` exhausted: HTTP 503 with `Retry-After: 5`.
4. Emit `BROWSER_STREAM_OPENED`.
5. Loop until client disconnects:
   - `jpeg_bytes = await session.page.screenshot(type="jpeg", quality=cfg.streaming_jpeg_quality)`.
   - Yield `b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"`.
   - `await asyncio.sleep(1.0 / cfg.streaming_fps)`.
   - Catch `asyncio.CancelledError`: emit `BROWSER_STREAM_CLOSED`, re-raise.
   - Catch any other Exception: emit `BROWSER_STREAM_CLOSED` with reason, log warning, return.
6. Track per-runtime viewer count via the public `runtime.browser_tool.acquire_viewer_slot()` / `release_viewer_slot()` methods (Section 2a). Call `acquire_viewer_slot()` in a `try`, `release_viewer_slot()` in `finally`. The 503 gate above uses `runtime.browser_tool.active_viewers` (read-only property).

### Section 2a — Public viewer-slot API on `BrowserTool`

Demeter / SOLID: the streaming router MUST NOT reach into private attributes. Expose three public surfaces on `BrowserTool`:

```python
===SEARCH===
        self._sessions: dict[str, BrowserSession] = {}
        # Token -> {token, session_id, action, params, created_at}
        self._pending_confirmations: dict[str, dict[str, Any]] = {}
        # Lazily-started reaper task; reference held per Async Discipline.
        self._reaper_task: asyncio.Task[Any] | None = None
        self._reaper_stop = asyncio.Event()
        # Allow tests to substitute a session factory.
        self._session_factory: Any = BrowserSession
===REPLACE===
        self._sessions: dict[str, BrowserSession] = {}
        # Token -> {token, session_id, action, params, created_at}
        self._pending_confirmations: dict[str, dict[str, Any]] = {}
        # Lazily-started reaper task; reference held per Async Discipline.
        self._reaper_task: asyncio.Task[Any] | None = None
        self._reaper_stop = asyncio.Event()
        # Allow tests to substitute a session factory.
        self._session_factory: Any = BrowserSession
        # AD-706a: Captain-watch streaming viewer accounting. Public API
        # (acquire_viewer_slot / release_viewer_slot / active_viewers) so the
        # streaming router doesn't reach across module boundaries — Demeter.
        self._active_viewers: int = 0
        self._viewer_lock = asyncio.Lock()
===END REPLACE===
```

Add the public methods on `BrowserTool` (place near other accessors; verify insertion point):

```python
    # ------------------------------------------------------------------
    # AD-706a viewer accounting
    # ------------------------------------------------------------------

    @property
    def active_viewers(self) -> int:
        """Current count of open streaming viewers across all sessions."""
        return self._active_viewers

    async def acquire_viewer_slot(self) -> bool:
        """Attempt to reserve a streaming viewer slot.

        Returns True on success; False when the configured
        ``streaming_max_concurrent_viewers`` cap is exhausted. Callers MUST
        pair every successful acquire with a ``release_viewer_slot()`` in
        ``finally``.
        """
        async with self._viewer_lock:
            cap = int(getattr(self._config, "streaming_max_concurrent_viewers", 0) or 0)
            if cap > 0 and self._active_viewers >= cap:
                return False
            self._active_viewers += 1
            return True

    async def release_viewer_slot(self) -> None:
        """Release a viewer slot previously acquired via acquire_viewer_slot()."""
        async with self._viewer_lock:
            if self._active_viewers > 0:
                self._active_viewers -= 1
```

### Section 3 — Populate `get_streaming_url`

Modify `BrowserSession.get_streaming_url()` to return `f"/api/browser/sessions/{self.session_id}/stream"` **only when** `self._config.streaming_enabled` is True. Otherwise keep returning `None`.

The Captain's HXI consumes the URL via the existing `McpAppFrame` (AD-597a):

```tsx
<McpAppFrame src={session.streaming_url} title={`Browser session ${session.id}`} />
```

— but no UI build is in scope for this AD beyond the prop-pass change (Section 4).

### Section 4 — HXI consumer

New component `ui/src/components/browser/BrowserStreamPanel.tsx`:

```tsx
type Props = { sessionId: string; streamingUrl: string | null; token?: string; };
export function BrowserStreamPanel({ sessionId, streamingUrl, token }: Props): JSX.Element { ... }
```

Renders:
- If `streamingUrl == null`: stroke-based SVG glyph + text "Streaming not enabled" (HXI Design Principle #3, no emoji).
- Otherwise: `<img src={fullUrl} alt={...} style={{maxWidth:'100%'}} />` where `fullUrl` appends `?token=${token}` when token is set (BF-291 / AD-722b-1 query-param convention for static surfaces).

This component is NOT yet wired into a parent panel in v1 — forward marker AD-706a-parent-wire covers integration into the agent-detail surface.

### Section 5 — Auth

Endpoint uses `Depends(require_crew_scope)` — Bearer header path. The HTTP path supports both header AND `?token=` query param for `<img>`-tag friendliness; extend `require_crew_scope` to fall back to `request.query_params.get("token")` when the `Authorization:` header is absent. This is a small extension to AD-722b-1 — document in DECISIONS as part of this AD's footprint.

Alternative considered: keep `require_crew_scope` header-only and add a separate `require_crew_scope_or_query_token` dep for `<img>` surfaces. Picking the **single-dep extension** (BF-274 pattern — don't fork APIs when one extension covers both shapes).

Explicit edit at `src/probos/routers/auth.py:40`:

```python
===SEARCH===
from fastapi import Depends, Header, HTTPException, WebSocket
===REPLACE===
from fastapi import Depends, Header, HTTPException, Request, WebSocket
===END REPLACE===
```

```python
===SEARCH===
async def require_crew_scope(
    authorization: str | None = Header(default=None),
    runtime: Any = Depends(get_runtime),
) -> None:
    """FastAPI dependency: enforce ``Authorization: Bearer <token>`` when configured.

    When ``auth.crew_scope_token`` is empty, this dependency is a pass-through -
    backward-compatible with single-operator HXI installs.

    When configured, missing/malformed/wrong tokens raise HTTP 401.
    """
    expected = _configured_token(runtime)
    if not expected:
        return  # auth disabled
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="missing_or_malformed_authorization"
        )
    presented = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid_token")
===REPLACE===
async def require_crew_scope(
    request: Request,
    authorization: str | None = Header(default=None),
    runtime: Any = Depends(get_runtime),
) -> None:
    """FastAPI dependency: enforce crew-scope token when configured.

    AD-722b-1: primary path is ``Authorization: Bearer <token>`` header.
    AD-706a: query-param fallback (``?token=...``) when the header is absent.
    The ``<img src>`` element cannot set HTTP headers, so MJPEG streaming
    needs the query-param surface. Header-only callers are unchanged.

    When ``auth.crew_scope_token`` is empty, this dependency is a pass-through —
    backward-compatible with single-operator HXI installs. When configured,
    missing / malformed / wrong tokens raise HTTP 401.
    """
    expected = _configured_token(runtime)
    if not expected:
        return  # auth disabled

    presented = ""
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer "):].strip()
    else:
        # AD-706a: query-param fallback for static surfaces (<img>, <video>).
        # Empty string is treated as "no token presented" — NOT a pass.
        query_token = request.query_params.get("token", "") or ""
        presented = query_token.strip()
        if not presented:
            raise HTTPException(
                status_code=401, detail="missing_or_malformed_authorization"
            )

    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid_token")
===END REPLACE===
```

**Regression-protect existing header-only callers.** Add a test asserting that the header path still works unchanged for `routers/agents.py:803` and `routers/agents.py:834` callers (or whichever current call sites depend on `require_crew_scope`). The new `request: Request` first positional is FastAPI-injected — it does NOT affect the public dependency signature seen by `Depends(require_crew_scope)`.

### Tests

`tests/test_ad706a_browser_streaming.py` (+9):

1. `test_streaming_disabled_by_default` — `cfg.streaming_enabled == False`; `session.get_streaming_url() is None`.
2. `test_streaming_enabled_populates_url` — flip flag, assert returned URL.
3. `test_endpoint_404_on_unknown_session`.
4. `test_endpoint_503_when_viewer_cap_exhausted`.
5. `test_endpoint_emits_open_and_close_events` — connect, disconnect, verify event log.
6. `test_endpoint_yields_jpeg_frames_at_configured_fps` — stub `page.screenshot()` returning fake JPEG bytes; assert N frames in T seconds (loose bound, ±30%).
7. `test_endpoint_decrements_viewer_count_on_disconnect`.
8. `test_endpoint_requires_crew_scope_token_when_configured` — 401 without token.
9. `test_endpoint_accepts_query_param_token` — `?token=xxx` succeeds.
10. `test_require_crew_scope_header_only_callers_unchanged` — regression: hit an existing `Depends(require_crew_scope)` endpoint (e.g. `routers/agents.py:803` or `:834`) with header only (no `?token=`). MUST pass (no behavior change for AD-722b-1 callers).
11. `test_require_crew_scope_empty_query_token_rejected` — `?token=` (empty value) MUST 401, not pass. Empty string is not a valid token.

`ui/src/__tests__/BrowserStreamPanel.test.tsx` (+4 vitest):

1. `renders_no_stream_glyph_when_url_null`.
2. `renders_img_with_url_when_provided`.
3. `appends_token_query_param_when_token_present`.
4. `omits_token_query_param_when_token_empty_string` — token=`""` MUST NOT append `?token=` to the URL.

All tests use real `BrowserToolConfig()` + stubbed Playwright page (BF-287). Streaming generator tested via `httpx.AsyncClient.stream()`.

## What This Does NOT Change

- BrowserSession lifecycle, TTL, rate limiting unchanged.
- `_action_screenshot` action handler unchanged (the streaming path uses `page.screenshot()` directly).
- WebRTC, recorded-video-MP4, and Federation-hop streaming are forward-marked, NOT implemented.
- HXI parent panel wiring deferred to AD-706a-parent-wire.

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #516.
- `DECISIONS.md` — append AD-706a with MJPEG vs WebRTC rationale + `require_crew_scope` query-param extension note.

Forward markers (TECHNICAL triggers):
- AD-706a-1 — Federation-hop streaming (cross-mesh Captain-watch). Trigger: AD-722b-5a federation streaming primitive lands.
- AD-706a-2 — WebRTC upgrade with adaptive bitrate. Trigger: ≥3 operator reports of MJPEG bandwidth issues OR LAN viewer count exceeds 8.
- AD-706a-parent-wire — Wire `BrowserStreamPanel` into agent-detail HXI surface. Trigger: HXI agent-detail panel refactor lands OR Captain demand.
- AD-706a-frame-diff — Diff-based frame transmission (only changed regions). Trigger: bandwidth profiling shows >70% of frame bytes are unchanged regions.

## Acceptance Criteria

- 11 pytest + 4 vitest green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+11. Vitest: previous +N → ≥+4.
- `cd ui && npm run build` GREEN (AD-738b standing rule).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- No new pip/npm deps.

## Verified Against Codebase (2026-05-16)

```
grep -n "def get_streaming_url" src/probos/tools/browser/session.py
  117:    def get_streaming_url(self) -> str | None:

grep -n "class BrowserToolConfig" src/probos/config.py
  936: class BrowserToolConfig(BaseModel):

grep -n "require_crew_scope" src/probos/routers/auth.py
  40: async def require_crew_scope(

grep -n "McpAppFrame" ui/src/components/McpAppFrame.tsx
  7: export function McpAppFrame(props: McpAppFrameProps) {

grep -n "_action_screenshot" src/probos/tools/browser/actions.py
  199: async def _action_screenshot(session: BrowserSession, params: dict[str, Any]) -> dict[str, Any]:
```

Playwright `page.screenshot(type="jpeg", quality=N)` is the documented Playwright API (verified against Playwright Python docs, version pinned in `pyproject.toml`).
