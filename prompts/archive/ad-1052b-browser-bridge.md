# AD-1052b — Browser Workstation BRIDGE mode (connect to an EXTERNAL user-launched browser)

**Epic #965 · sub-AD of AD-1052 (NO new top-level number) · HEAD `63edf0e2` · default-OFF**

Slice 3 of the browser workstation. The Captain launches their own Chrome with
`--remote-debugging-port=9222`; ProbOS's AD-706 `BrowserTool` connects to it over CDP
(`chromium.connect_over_cdp(endpoint)`) so an agent can drive the user's **real** browser
(with their logged-in sessions). HIGH-RISK → gated behind a default-OFF `bridge_enabled`
flag (separate from `enabled`), an explicit `confirm:true` consent step, and an SSRF host
allowlist. v1 embedded + AD-1052a watch unchanged.

---

## Research / Decision (verified against the live codebase at HEAD 63edf0e2)

**1. `connect_over_cdp` injection point.** `BrowserSession.start()`
([session.py:96](../src/probos/tools/browser/session.py#L96)) launches via
`self._browser = await self._playwright.chromium.launch(headless=self._config.headless)`.
The bridge adds a **sibling `connect()` method** (NOT a branch inside `start()` — keeps
`start()` byte-identical, DD-5) that calls `connect_over_cdp(endpoint)` instead of `launch()`.

**2. Playwright lifecycle / disconnect-not-close (the headline safety property — VERIFIED).**
Per the official Playwright Python docs (`class-browser` → `close`): *"In case this browser
is obtained using browser_type.launch(), closes the browser and all of its pages. **In case
this browser is connected to, clears all created contexts belonging to this browser and
disconnects from the browser server.**"* So `browser.close()` over `connect_over_cdp`
**disconnects** — it does **NOT** quit the user's Chrome. The in-repo precedent
[task_sessions/browser.py:88](../src/probos/task_sessions/browser.py#L88) confirms the
team's pattern: `connect_over_cdp(url)` → `browser.contexts[0] if browser.contexts else
new_context()` → `context.pages[0] if context.pages else new_page()`, and on CDP cleanup
calls `browser.close()` **only** (never `context.close()` / `page.close()` — those are the
user's real context/tabs). **DD-1**: bridge reuses the **existing** `contexts[0]`/`pages[0]`
(the user's logged-in session — `new_context()` would be a fresh cookie-less context, defeating
the purpose); `stop()` for a connected session calls `browser.close()` (disconnect) +
`playwright.stop()` and **never** closes the page/context.

**3. Consent primitive — DEVIATION from the named-slice prose, flagged + justified.**
The AD-1052/1052a slice-boundary prose
([DECISIONS.md:23](../DECISIONS.md), [PROGRESS.md:5](../PROGRESS.md)) pre-committed AD-1052b
to a *"HookBus/consensus consent gate."* Verify-first shows that is the **wrong primitive**:
  - `runtime.submit_mcp_invoke_with_consensus`
    ([runtime.py:3201](../src/probos/runtime.py#L3201)) is a multi-agent **quorum** vote +
    red-team for **agent-initiated MCP tool invokes**. A Captain connecting to the Captain's
    **own** browser is not a subject of an agent vote — the Captain **is** the authority.
    Wrong authority model.
  - The HookBus `PRE_TOOL_USE` gate ([hooks/bus.py:48](../src/probos/hooks/bus.py#L48), fired
    at [finalize.py:3383](../src/probos/startup/finalize.py#L3383)) gates **agent dispatch /
    tool invocation** inside the cognitive pipeline. The HXI connect endpoint does not flow
    through agent dispatch; threading the HookBus into a UI router is over-engineering.
  - The AD-706 tier-3 `_pending_confirmations` flow
    ([tool.py:76](../src/probos/tools/browser/tool.py#L76)) is a per-**action** Captain ACK,
    not a session-creation consent.

  **DECISION (DD-2):** the right-sized primitive for "a one-time per-bridge-session Captain
  approval" is the **explicit-confirm endpoint gate** — a default-OFF `bridge_enabled` config
  flag + an explicit `confirm:true` body param (the Captain's affirmative consent, sent only
  on an explicit Connect gesture after reading the consent note) + an **audit event** reusing
  BrowserTool's existing `_audit_log` + `EventType` emission (the AD-706 governance surface).
  This is honest: the Captain is the authority, consent is one-time-per-connect (not per-action),
  and it reuses existing AD-706 governance rather than inventing a consent system. **The slice
  prose's "HookBus/consensus" is superseded; record the rationale in the AD-1052b DECISIONS
  entry.**

**4. SSRF allowlist (DD-3).** Connecting ProbOS to an attacker-supplied CDP endpoint is an
exfil/SSRF vector. The CDP endpoint **host** is validated against
`BrowserToolConfig.bridge_allowed_hosts` (default `["127.0.0.1","localhost","[::1]"]`) in the
**backend** (`BrowserTool`, the authoritative gate — not just the UI). Non-localhost hosts are
refused. Host parsing mirrors `BrowserTool._check_domain`'s `urlparse(...).hostname` pattern.

**5. CDP screencast over a connected page — reuse the watch surface FREE (DD-6).** The AD-706a
stream ([browser_stream.py](../src/probos/routers/browser_stream.py) `_generate`) produces
frames via `await page.screenshot(type="jpeg", quality=...)` — **not** CDP `Page.startScreencast`.
`page.screenshot()` works over **any** Playwright `Page`, including a `connect_over_cdp` page.
So when `streaming_enabled` is on, the bridge "connected" view reuses the AD-1052a
`BrowserStreamPanel` with **zero** new streaming code. When `streaming_enabled` is off,
`get_streaming_url()` returns `None` → `BrowserStreamPanel` honest-degrades to
"Streaming not enabled" while the bridge is still connected.

---

## Verified API / file map (file:line + phantom checks)

| Concern | Anchor (HEAD 63edf0e2) | Action |
|---|---|---|
| Launch injection point | [session.py:96](../src/probos/tools/browser/session.py#L96) `chromium.launch(headless=...)` | Add sibling `connect()` (does `connect_over_cdp`) |
| Lifecycle / teardown | [session.py:122](../src/probos/tools/browser/session.py#L122) `async def stop()` | Add connected branch: disconnect, not close |
| `__init__` handles | [session.py:54-82](../src/probos/tools/browser/session.py#L54) | Add `self._connected: bool = False` |
| Public props | [session.py:227-240](../src/probos/tools/browser/session.py#L227) (`page`/`agent_id`/`last_url`) | Add `is_connected` property |
| CDP precedent | [task_sessions/browser.py:88](../src/probos/task_sessions/browser.py#L88) | Reference (contexts[0]/pages[0]; browser.close only) |
| Tool ctor / seams | [tool.py:62-89](../src/probos/tools/browser/tool.py#L62) (`_sessions`,`_session_factory`,`_audit_log`,`_emit_event`,`_safe_emit`) | Reuse |
| Session-create precedent | [tool.py:432](../src/probos/tools/browser/tool.py#L432) `_get_or_create_session` | Sibling `connect_bridge_session` |
| Host parse precedent | [tool.py ~520](../src/probos/tools/browser/tool.py) `_check_domain` (`urlparse().hostname`) | Mirror for `_validate_cdp_endpoint` |
| Config | [config.py:1474](../src/probos/config.py#L1474) `enabled: bool = False` | Add `bridge_enabled`, `bridge_allowed_hosts` |
| Sessions endpoint | [browser_stream.py:134](../src/probos/routers/browser_stream.py#L134) `GET /sessions` | Add `POST /bridge/connect` (same router) |
| Auth dep | [browser_stream.py:21](../src/probos/routers/browser_stream.py#L21) `require_crew_scope` | Reuse on new endpoint |
| EventTypes | [events.py:239](../src/probos/events.py#L239) `BROWSER_RECORDING_FAILED` | Insert 3 new after (Section 0) |
| Stream is page-bound | [browser_stream.py](../src/probos/routers/browser_stream.py) `await page.screenshot(type="jpeg")` | Works over connected page → DD-6 |
| UI mode model | [BrowserWorkstation.tsx `_MODES`](../ui/src/components/workstation/BrowserWorkstation.tsx) bridge `disabled:true` | Flip → `false`; drop `title` |
| UI body | BrowserWorkstation.tsx `mode === 'bridge' ? <browser-mode-pending>` | Replace with `renderBridge()` |
| Consensus primitive (NOT used) | [runtime.py:3201](../src/probos/runtime.py#L3201) | Cite + reject in DD-2 |
| HookBus PRE_TOOL_USE (NOT used) | [hooks/bus.py:48](../src/probos/hooks/bus.py#L48) | Cite + reject in DD-2 |

**Phantom checks (introduced by THIS spec — confirmed absent at HEAD):** `bridge_enabled`,
`bridge_allowed_hosts`, `connect_bridge_session`, `_validate_cdp_endpoint`, `BROWSER_BRIDGE_*`,
`connect()`/`is_connected` on `BrowserSession`, `BridgeConnectRequest`, the UI `connectBridge`
prop + `browser-bridge-*` testids. (`_connected`/`is_connected` exist only in
`mesh/nats_bus.py` — different module, no collision.)

---

## Files

**target_files**
- `src/probos/events.py` — 3 new EventTypes (Section 0)
- `src/probos/config.py` — `BrowserToolConfig.bridge_enabled` + `bridge_allowed_hosts`
- `src/probos/tools/browser/session.py` — `connect()`, `_connected`, `is_connected`, `stop()` branch
- `src/probos/tools/browser/tool.py` — `connect_bridge_session()`, `_validate_cdp_endpoint()`
- `src/probos/routers/browser_stream.py` — `POST /api/browser/bridge/connect`
- `ui/src/components/workstation/BrowserWorkstation.tsx` — enable bridge mode + `renderBridge()` + props
- `DECISIONS.md`, `PROGRESS.md`

**reference_files**
- `src/probos/task_sessions/browser.py` (connect_over_cdp precedent)
- `tests/test_ad706_browser_tool.py` (`_FakeSession`/`_session_factory` seam)
- `tests/test_ad1052a_browser_sessions.py` (endpoint harness)
- `tests/test_ad706a_browser_streaming.py` (stream + seed pattern)

**test_files**
- `tests/test_ad1052b_browser_bridge.py` (NEW — Python)
- `ui/src/components/workstation/BrowserWorkstation.test.tsx` (EXTEND — bridge tests + 2 obsolete rewrites)

---

## Section 0 — Event Types (insert immediately after `BROWSER_RECORDING_FAILED`, events.py:239)

```python
    BROWSER_BRIDGE_CONNECTED = "browser_bridge_connected"        # AD-1052b: connected to an external CDP browser
    BROWSER_BRIDGE_REFUSED = "browser_bridge_refused"            # AD-1052b: bridge connect refused (disabled/consent/allowlist/unreachable)
    BROWSER_BRIDGE_DISCONNECTED = "browser_bridge_disconnected"  # AD-1052b: bridge session torn down (disconnect, not close)
```

---

## Step-by-step

### Section 1 — `BrowserSession`: connect path + disconnect-not-close (session.py)

1. In `__init__` (after `self._page: Any = None`, ~line 67) add:
   ```python
   # AD-1052b: True when this session attached to an EXTERNAL browser via
   # connect_over_cdp. A connected session must NOT close the user's page/
   # context/browser on stop() — only disconnect.
   self._connected: bool = False
   ```
2. Add a `connect()` method (sibling to `start()`, after `start()`):
   ```python
   async def connect(self, endpoint: str) -> None:
       """AD-1052b: attach to an EXTERNAL user-launched browser over CDP.

       Mirrors ``start()`` but uses ``connect_over_cdp(endpoint)`` instead of
       ``launch()``. Reuses the browser's EXISTING default context + page
       (``contexts[0]`` / ``pages[0]``) so the agent drives the user's real
       logged-in session — a fresh ``new_context()`` would have no cookies.
       """
       from playwright.async_api import async_playwright  # type: ignore[import-not-found]

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
   ```
3. Add an `is_connected` property (next to `page`/`agent_id`/`last_url`, ~line 240):
   ```python
   @property
   def is_connected(self) -> bool:
       """AD-1052b: True for a bridge (connect_over_cdp) session."""
       return self._connected
   ```
4. In `stop()`, add a **connected early-return branch at the very top** (before the existing
   launched-session teardown — leave that path byte-identical, DD-5):
   ```python
   async def stop(self) -> None:
       """Close everything in reverse order. Idempotent."""
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
           if self._emit_event is not None:
               try:
                   from probos.events import EventType
                   self._emit_event(EventType.BROWSER_BRIDGE_DISCONNECTED, {"session_id": self.session_id})
               except Exception:
                   logger.debug("AD-1052b: disconnect event emit failed", exc_info=True)
           self._page = self._context = self._browser = self._playwright = None
           self._connected = False
           return
       # ... EXISTING launched-session teardown unchanged ...
   ```

### Section 2 — Config flags (config.py, in `BrowserToolConfig`, after the AD-706b recording block)

```python
    # AD-1052b: BRIDGE mode — connect to an EXTERNAL user-launched browser over
    # CDP. SEPARATE, higher-risk gate from `enabled` (driving the user's real
    # logged-in browser). Default-OFF (Wave 10 convention #14). Bridge requires
    # BOTH enabled=True (the tool is wired at all) AND bridge_enabled=True.
    bridge_enabled: bool = Field(
        default=False,
        description=(
            "AD-1052b: enable BRIDGE mode (connect_over_cdp to an external "
            "user-launched Chrome). Higher-risk than headless; default OFF."
        ),
    )
    bridge_allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "[::1]"],
        description=(
            "AD-1052b: SSRF allowlist — the CDP endpoint host must match one of "
            "these (case-insensitive exact match). Refuses arbitrary remote CDP "
            "endpoints (exfil/SSRF guard). Localhost-only by default."
        ),
    )
```

### Section 3 — `BrowserTool`: consent + allowlist + connect (tool.py)

Add `_validate_cdp_endpoint` and `connect_bridge_session` (siblings of `_get_or_create_session`):

```python
    def _validate_cdp_endpoint(self, endpoint: str) -> str:
        """AD-1052b: return the host if allowed, else "" (refused).

        Accepts http/https/ws/wss CDP endpoints; the HOST must be in
        bridge_allowed_hosts (case-insensitive). Defense-in-depth against SSRF.
        """
        if not endpoint or not isinstance(endpoint, str):
            return ""
        try:
            parsed = urlparse(endpoint)
        except Exception:
            return ""
        if parsed.scheme.lower() not in ("http", "https", "ws", "wss"):
            return ""
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        allow = [h.lower() for h in (self._config.bridge_allowed_hosts or [])]
        return host if host in allow else ""

    async def connect_bridge_session(
        self, endpoint: str, *, agent_id: str, confirm: bool,
    ) -> dict[str, Any]:
        """AD-1052b: consent-gated, allowlist-validated CDP bridge connect.

        Honest-degrade (returns {"connected": False, "reason": ...}) when bridge
        is disabled, consent is not given, the endpoint host is not allowed, or
        the connect fails. On success stores the session and returns
        {"connected": True, "session_id", "streaming_url"}.
        """
        if not getattr(self._config, "bridge_enabled", False):
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "disabled"})
            return {"connected": False, "reason": "Bridge mode is disabled."}
        if confirm is not True:
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "consent"})
            return {"connected": False, "reason": "Connection consent is required."}
        host = self._validate_cdp_endpoint(endpoint)
        if not host:
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "endpoint_not_allowed"})
            return {"connected": False, "reason": "Endpoint not allowed."}

        new_id = uuid.uuid4().hex
        session = self._session_factory(
            session_id=new_id, config=self._config, agent_id=agent_id, emit_event=self._emit_event,
        )
        try:
            await session.connect(endpoint)
        except Exception:
            logger.warning("AD-1052b: bridge connect to %s failed", endpoint, exc_info=True)
            self._safe_emit(EventType.BROWSER_BRIDGE_REFUSED, {"reason": "unreachable", "host": host})
            return {"connected": False, "reason": f"Could not connect to {endpoint}"}

        self._sessions[new_id] = session
        self._safe_emit(
            EventType.BROWSER_BRIDGE_CONNECTED,
            {"session_id": new_id, "agent_id": agent_id, "host": host},
        )
        return {
            "connected": True,
            "session_id": new_id,
            "streaming_url": session.get_streaming_url(),
        }
```

> NOTE: `connect_bridge_session` builds the session via `self._session_factory` (the existing
> test seam) so tests inject a `_FakeSession` whose `connect()` needs no real Chrome.

### Section 4 — Connect endpoint (browser_stream.py)

Add `from pydantic import BaseModel` to the imports, then after the `GET /sessions` route:

```python
class BridgeConnectRequest(BaseModel):
    """AD-1052b: body for POST /api/browser/bridge/connect."""
    endpoint: str
    confirm: bool = False


@router.post("/bridge/connect", dependencies=[Depends(require_crew_scope)])
async def connect_browser_bridge(
    body: BridgeConnectRequest, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1052b: consent-gated, allowlist-validated CDP bridge connect.

    Honest-degrade: returns {"connected": False, "reason": "Browser tool is
    disabled."} when the tool is off (runtime.browser_tool unset). All policy
    (bridge_enabled / confirm / allowlist) lives in BrowserTool — this is a thin
    adapter. Same require_crew_scope posture as the stream / sessions list.
    """
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"connected": False, "reason": "Browser tool is disabled."}
    return await browser_tool.connect_bridge_session(
        body.endpoint, agent_id="captain", confirm=body.confirm,
    )
```

### Section 5 — Enable bridge in the UI (BrowserWorkstation.tsx)

1. Flip the `_MODES` bridge entry: `{ id: 'bridge', label: 'Bridge', disabled: false }` (drop `title`).
2. Extend `Props` + add the default connect fetch:
   ```tsx
   type BridgeConnectResponse = {
     connected: boolean; reason?: string | null;
     session_id?: string | null; streaming_url?: string | null;
   };
   type Props = NativeWorkstationProps & {
     fetchSessions?: () => Promise<SessionsResponse>;
     connectBridge?: (endpoint: string) => Promise<BridgeConnectResponse>;
   };
   const _defaultConnectBridge = async (endpoint: string): Promise<BridgeConnectResponse> => {
     const res = await fetch('/api/browser/bridge/connect', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({ endpoint, confirm: true }),  // explicit Captain consent (DD-2)
     });
     if (!res.ok) throw new Error(`bridge ${res.status}`);
     return res.json();
   };
   ```
3. Add bridge state (`_initialBridge` default endpoint `http://127.0.0.1:9222`), a
   `bridgeState: 'idle'|'connecting'|'connected'|'refused'`, `bridgeReason`, `bridgeSession`
   (`{session_id, streaming_url}`). `onConnect` calls `_connectBridge(endpoint)`; on
   `connected:true` → `bridgeState='connected'` + store the session; else
   `bridgeState='refused'` + `bridgeReason = res.reason`; on reject →
   `bridgeReason='Could not connect to ' + endpoint`.
4. `renderBridge()` (testid `browser-bridge`): an endpoint input
   (`browser-bridge-endpoint`, default `http://127.0.0.1:9222`), an explicit **consent note**
   (`browser-bridge-consent-note`: "Connecting lets an agent drive this external browser with
   your logged-in sessions."), a **Connect** button (`browser-bridge-connect`). On connected →
   reuse `<BrowserStreamPanel sessionId streamingUrl />` (no token, DD-1) under testid
   `browser-bridge-stream`; on refused → `browser-bridge-reason` showing the reason. HXI:
   stroke-SVG glyph, amber/dim, no emoji, data-testid on every control.
5. Replace the body branch `mode === 'bridge' ? <browser-mode-pending> : ...` with
   `mode === 'bridge' ? renderBridge() : ...` (remove the `browser-mode-pending` div).

---

## Tests

### Python — `tests/test_ad1052b_browser_bridge.py` (BF-287 real fixtures, NO real Chrome)

Reuse the `_FakeSession(BrowserSession)` + `tool._session_factory` seam
(test_ad706_browser_tool.py:112) and the `_make_runtime`/`_make_app`/`_crew_pass_through`/
TestClient harness (test_ad1052a_browser_sessions.py).

**Session (real `BrowserSession`):**
1. `test_session_connect_attaches_existing_context_page` — monkeypatch
   `playwright.async_api.async_playwright` to a fake whose
   `chromium.connect_over_cdp` returns a fake browser with `contexts=[ctx]`,
   `ctx.pages=[page]`; `await sess.connect("http://127.0.0.1:9222")`; assert
   `sess.page is page`, `sess.is_connected is True`, and `new_context`/`new_page` NOT called.
2. `test_session_stop_connected_disconnects_not_closes` — `_connected=True`; fake
   `_browser`/`_context`/`_page` (AsyncMock `close`), `_playwright` (AsyncMock `stop`);
   `await sess.stop()`; assert `_browser.close` awaited once, `_page.close` & `_context.close`
   **NOT** called, `_playwright.stop` awaited once, `is_connected is False`, handles `None`,
   `BROWSER_BRIDGE_DISCONNECTED` emitted.
3. `test_session_stop_launched_unchanged` — `_connected=False`; fake handles; `stop()` calls
   page+context+browser close (DD-5 regression guard).

**Tool (`_FakeSession` factory; no playwright):**
4. `bridge_disabled` — `enabled=True, bridge_enabled=False`; `connect_bridge_session(...,
   confirm=True)` → `{connected:False}`, reason contains "Bridge mode is disabled"; no session
   stored; `BROWSER_BRIDGE_REFUSED` emitted.
5. `requires_confirm` — `bridge_enabled=True`, `confirm=False` → refused (reason "consent");
   no session.
6. `endpoint_not_allowed` — `bridge_enabled=True`, `endpoint="http://evil.example.com:9222"`,
   `confirm=True` → refused (reason "not allowed"); no session.
7. `localhost_happy_path` — `bridge_enabled=True, streaming_enabled=True`; `_FakeSession.connect`
   sets `_connected=True`; `endpoint="http://127.0.0.1:9222"`, `confirm=True` →
   `{connected:True, session_id, streaming_url:"/api/browser/sessions/<sid>/stream"}`; session
   in `tool._sessions`; `BROWSER_BRIDGE_CONNECTED` emitted.
8. `unreachable` — `_FakeSession.connect` raises `ConnectionError` → `{connected:False}`,
   reason contains "Could not connect"; no session stored.
9. `validate_cdp_endpoint_allowlist` — unit-test `_validate_cdp_endpoint` directly:
   `127.0.0.1`/`localhost`/`[::1]` ok; `evil.com` rejected; `http://127.0.0.1.evil.com:9222`
   rejected (host ≠ allowlist); `file:///x` rejected; `""` rejected.
10. `custom_allowlist` — `bridge_allowed_hosts=["10.0.0.5"]`; `10.0.0.5` allowed; `127.0.0.1`
    now refused.

**Endpoint (TestClient):**
11. `endpoint_tool_disabled_honest_degrade` — `rt.browser_tool=None`; POST
    `/api/browser/bridge/connect` `{endpoint, confirm:true}` → 200
    `{connected:False, reason:"Browser tool is disabled."}`.
12. `endpoint_connects` — real `BrowserTool(bridge_enabled=True, streaming_enabled=True)` with
    `_session_factory=_FakeSession`; POST → 200 `{connected:True, session_id, streaming_url}`.
13. `endpoint_auth_token_set_401` — `crew_scope_token="secret"`, no token → 401 (mirror /sessions).

### UI — `BrowserWorkstation.test.tsx` (extend; inject `connectBridge`)

**Obsolete-contract rewrites (pre-authorized):**
- "defaults to Embedded active; Watch enabled and Bridge **disabled**" → assert
  `bridge.disabled === false` (rename "...Watch and Bridge enabled").
- "keeps Embedded active when a disabled mode segment is clicked" (clicks `browser-mode-bridge`)
  → repurpose to "clicking Bridge switches to bridge mode and shows the endpoint input"
  (assert `browser-mode-bridge` aria-pressed `true` + `browser-bridge-endpoint` present).
  Remove any `browser-mode-pending` assertion (the div is gone).

**New bridge tests:**
- Clicking Bridge shows the endpoint input (default `http://127.0.0.1:9222`), the consent note,
  and the Connect button.
- Connect calls `connectBridge(endpoint)`; on `{connected:true, streaming_url}` mounts the
  stream `<img>` (`browser-stream-panel-img`, src == streaming_url, no `token=`).
- Connected with `streaming_url:null` → `browser-stream-panel-unavailable` (honest-degrade).
- Refused (`{connected:false, reason}`) → `browser-bridge-reason` shows the reason.
- `connectBridge` rejects → `browser-bridge-reason` shows "Could not connect…".
- No emoji (HXI #3) + data-testids on the bridge controls; the consent note is present (DD-2).

---

## DD-1..DD-6

- **DD-1 (connect path; disconnect-not-close):** `BrowserSession.connect()` does
  `connect_over_cdp(endpoint)` and reuses `contexts[0]`/`pages[0]` (the user's real logged-in
  session). `stop()` for a connected session calls `browser.close()` (Playwright-documented
  disconnect) + `playwright.stop()` and **never** closes the user's page/context. Gated by the
  new `bridge_enabled` flag.
- **DD-2 (consent — headline):** explicit-confirm endpoint gate = default-OFF `bridge_enabled`
  + explicit `confirm:true` body param + `BROWSER_BRIDGE_CONNECTED`/`REFUSED` audit events.
  The MCP-consensus quorum, HookBus `PRE_TOOL_USE`, and tier-3 `_pending_confirmations`
  primitives were evaluated and rejected (wrong authority model / wrong layer / wrong scope —
  see Research §3). **Supersedes the slice prose's "HookBus/consensus consent gate."**
- **DD-3 (SSRF allowlist):** `_validate_cdp_endpoint` enforces `bridge_allowed_hosts`
  (localhost-only default) in the **backend** (authoritative), refusing arbitrary remote CDP
  endpoints.
- **DD-4 (honest-degrade chain):** `enabled=False` → "Browser tool is disabled" ·
  `bridge_enabled=False` → "Bridge mode is disabled" · `confirm!=True` → "Connection consent is
  required" · host not allowed → "Endpoint not allowed" · connect raises → "Could not connect to
  <endpoint>" · connected + `streaming_enabled` off → `BrowserStreamPanel` "Streaming not
  enabled" · all on → live MJPEG of the user's real browser.
- **DD-5 (default-OFF / non-disruptive):** bridge lights up only under `enabled` +
  `bridge_enabled` + `confirm`. `start()` and the launched `stop()` path are byte-identical; v1
  embedded + AD-1052a watch unchanged; no existing surface changes; `config/system.yaml`
  untouched (Pydantic defaults give zero-config boot).
- **DD-6 (reuse the watch surface):** the AD-706a stream is `page.screenshot()`-based →
  page-bound → works over a `connect_over_cdp` page → the bridge "connected" view reuses
  `BrowserStreamPanel` with no new streaming code.

---

## Acceptance criteria

- Focused Python green: `d:\ProbOS\.venv\Scripts\pytest.exe tests/test_ad1052b_browser_bridge.py tests/test_ad1052a_browser_sessions.py tests/test_ad706_browser_tool.py tests/test_ad706a_browser_streaming.py -q -n 4`.
- Full Python gate green (no regressions): `d:\ProbOS\.venv\Scripts\pytest.exe tests/ -q -n 4`.
- Focused UI green: `cd ui; npx vitest run src/components/workstation/BrowserWorkstation.test.tsx`.
- Full UI baseline green + **MANDATORY** `cd ui; npm run build` clean.
- **Default-OFF:** with `bridge_enabled=False` (default) the connect endpoint honest-degrades
  "Bridge mode is disabled"; no behavior change to embedded/watch.
- **Consent enforced:** `confirm!=True` is refused; the UI sends `confirm:true` only on the
  explicit Connect gesture; a `BROWSER_BRIDGE_REFUSED`/`CONNECTED` audit event fires.
- **Allowlist enforced:** non-localhost CDP hosts are refused in the backend.
- **Disconnect-not-close:** the connected `stop()` test proves the user's page/context are never
  closed.
- **No `config/system.yaml` change.**
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- Input forwarding / human-drives-the-shared-browser (CDP `Input.dispatch*`) → **AD-1052c**.
- Cross-origin reverse proxy → **AD-1052d**.
- Rebuilding the AD-706 engine, the AD-706a stream, or inventing a new consent system — REUSE all three.
- No HookBus/consensus wiring for the connect (explicitly rejected in DD-2).
- No crew-scope token minted/stored in JS (AD-1052a DD-1 stands).

## Tracking

- **DECISIONS.md:** add `### AD-1052b — Browser Workstation BRIDGE mode (epic #965)` after the
  AD-1052a section (DECISIONS.md:31). Record DD-1..DD-6 and the **explicit supersession** of the
  "HookBus/consensus consent gate" prose with the cited rationale.
- **PROGRESS.md:** prepend an AD-1052b entry (newest-first, line 3): headline, DD-1..DD-6, the
  honest-degrade chain, the consent-primitive decision, test counts, gate results,
  `config/system.yaml` untouched.
