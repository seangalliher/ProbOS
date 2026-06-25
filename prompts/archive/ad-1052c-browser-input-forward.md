# AD-1052c — Browser Workstation INPUT-FORWARDING (the human DRIVES the shared browser)

**Status:** Ready to build · **AD:** AD-1052c (sub-AD of AD-1052; **NO new top-level number**) · **Epic:** #965 (HXI Workspaces) · **Depends on:** AD-1052 (embedded ea5c4e7b), AD-1052a (watch 63edf0e2), AD-1052b (bridge 826e6b40) · **Est. tests:** ~17 Python + ~9 UI.

> **AD numbering (hard rule, stated):** Highest **landed top-level** = **AD-1052** (AD-1052a/b that landed at HEAD `826e6b40` are sub-ADs). AD-1052c is the next sub-AD of AD-1052 — **no new top-level number**. Verified: zero `### AD-1052c` heading at HEAD; zero `BROWSER_INPUT_*` / `forward_input` / `input_forwarding` symbols anywhere.

---

## 1. Research / Decision

### 1a. The existing agent input-action surface — REUSE vs ADD (the brief's required call)

**DECISION: ADD `BrowserSession.forward_input(event)` that REUSES the Playwright *primitives* the agent path already uses, but NOT the agent *flows*.** Evidence (HEAD `826e6b40`):

| Existing agent surface | What it does | Reusable for human input? |
|---|---|---|
| `compute_use.py:325-329` — `mouse = getattr(page, "mouse", None); await mouse.click(x, y)` | Coordinate click, but only after a **vision-LLM predicts the coords** + an `action_verify` handshake agrees (`compute_use.py` docstring). | **NO flow** — the human already knows where they clicked; the LLM-vision predict/verify is wrong-shaped and would add latency + an LLM dependency. **REUSE the primitive** (`getattr(page,"mouse",None).click(x,y)`). |
| `actions.py:144` `page.click(selector)`, `:177` `page.fill(selector,text)`, `:179` `page.type(selector,text)` | Selector/index-based (DOM-anchored). | **NO** — human input is **coordinate/normalized**, not DOM-indexed. |
| `actions.py:386-390` `_action_key_combo` → `keyboard = getattr(page,"keyboard",None); await keyboard.press(combo)` | Agent key-combo (tier-3 gated for destructive combos). | **REUSE the primitive** (`keyboard.press(key)`) under a **key allowlist** (no destructive combos in v1). |
| `actions.py:397-410` `_action_mouse_move` → `mouse.move(x,y)`; `:412-430` `_action_mouse_button` → `mouse.down/up/click` | Raw mouse primitives. | **REUSE the primitives** (`mouse.move`, `mouse.wheel`). |

**Conclusion:** there is **no single session-level method** today that takes coordinates and dispatches a raw click/type/key/scroll without the agent machinery (tier classification, index resolution, LLM vision). So **ADD `BrowserSession.forward_input(event)`** — a thin coordinate-mapping dispatch over the **same Playwright handles** (`getattr(page,"mouse",None)` / `getattr(page,"keyboard",None)`) the agent path uses. This is the minimal, DRY seam: it reuses the engine primitives and the AD-1052b gate→act→emit pattern, and invents no new dispatch.

### 1b. Coordinate mapping (the load-bearing problem) — DD-1

**Verified finding:** `BrowserToolConfig` has **NO viewport fields** (config.py:1455-1640 — `enabled`, `headless`, `streaming_*`, `bridge_*`, … but no `viewport_*`), and `BrowserSession.start()` calls `self._browser.new_context()` with **no viewport** (session.py:113/118) → Playwright's **default 1280×720**.

**Protocol (resolution-independent, no viewport leak to JS):**
1. The UI renders the AD-706a MJPEG `<img>` at a **scaled CSS size**. On a captured pointer event it computes **normalized** coords from the img's *rendered* bounding rect: `nx = (clientX - rect.left) / rect.width`, `ny = (clientY - rect.top) / rect.height` (∈ [0,1]).
2. The UI POSTs `{kind, nx, ny, …}` — **never** pixel coords, **never** the viewport size.
3. The backend de-normalizes against the session's **real viewport**: resolve via `page.viewport_size` (a Playwright `Page` **property**, returns `{width,height}` dict or `None` — *not* a coroutine), falling back to the new `config.viewport_width/viewport_height` when `None` (the bridge/CDP case, where `viewport_size` is often `None`). Then `vx = round(clamp01(nx) * vw)`, `vy = round(clamp01(ny) * vh)`.

**Why this is correct for both modes:** the MJPEG frame is `page.screenshot(type="jpeg")` of the page viewport, so the img's aspect ratio == the viewport's. Normalizing by the *rendered* img size and de-normalizing by `viewport_size` (CSS px — exactly the units `page.mouse.click(x,y)` expects) is ratio-invariant and devicePixelRatio-invariant. Launched sessions report a non-`None` `viewport_size` (1280×720); bridged sessions fall back to config. **No viewport dimension ever crosses to JS.**

**Why config fields are non-disruptive (DD-5):** `viewport_width=1280`/`viewport_height=720` are **read-only fallbacks consulted only inside `forward_input`** — they are **NOT** wired into `new_context(...)`. So launched/watch/bridge behavior stays **byte-identical**; the screenshot/stream size is unchanged.

### 1c. Governance gate (high-risk) — DD-4

Forwarding human input to **drive** a browser (especially a bridged real one) is high-risk. The human **is** the Captain (direct authority — same finding as AD-1052b's consent analysis), so the gate is **NOT** an agent quorum / HookBus / per-action ACK. It is the **AD-1052b-shaped explicit gate**:

- a **default-OFF `BrowserToolConfig.input_forwarding_enabled`** flag (off ⇒ endpoint refuses), **plus**
- an **explicit UI "Drive" toggle** (active affordance, `aria-pressed`, only shown when the flag is on — never silent), **plus**
- **audit events** that mirror AD-1052b's `BROWSER_BRIDGE_*`: `BROWSER_INPUT_REFUSED` on **every** refusal (rare, security-relevant) and `BROWSER_INPUT_FORWARDED` **once per drive-episode per session** (NOT per keystroke — avoids event spam).

### 1d. Event model — DD-2

v1 payload: `kind ∈ {click, type, key, scroll}`, `nx`, `ny` (∈[0,1]), `button ∈ {left,right,middle}`, `key` (allowlisted), `text` (length-capped), `dx`/`dy` (scroll deltas). **v1 supports exactly: `click` + `type` + `key` (allowlist) + `scroll`.** **Deferred:** `move`/hover, `drag`, file-drop (→ a later slice).

---

## 2. Verified API / File Map (HEAD `826e6b40`)

| Anchor | file:line | Role in this build |
|---|---|---|
| `BrowserSession.page` property | session.py:278 (`return self._page`) | The page handle `forward_input` dispatches on. |
| `BrowserSession.__init__` kw-only | session.py:54-86 (`session_id`, `config`, `agent_id`, `emit_event`) | Real-fixture construction in tests. |
| `start()` `new_context()` no viewport | session.py:113 / :118 | Proof the default viewport is Playwright's 1280×720. |
| `mouse.click(x,y)` primitive | compute_use.py:325-329 | The reused click primitive (`getattr(page,"mouse",None)`). |
| `keyboard.press` / `mouse.move` primitives | actions.py:386-390 / :408 / :424-430 | Reused key/move/wheel primitives. |
| `BrowserToolConfig` | config.py:1455 | ADD `input_forwarding_enabled`, `viewport_width`, `viewport_height`. |
| `bridge_enabled` / `bridge_allowed_hosts` | config.py:1624 / :1631 | Insertion sibling (add new fields **after** `bridge_allowed_hosts`, before `credential_vault`). |
| `BROWSER_BRIDGE_*` EventTypes | events.py:247-249 | INSERT `BROWSER_INPUT_FORWARDED` / `_REFUSED` **after** :249. |
| `BrowserTool.__init__` | tool.py:62-86 (`_sessions`, `_audit_log`, `_emit_event`, `_session_factory`) | ADD `_driven_sessions: set[str]`. |
| `connect_bridge_session` (gate→validate→act→emit) | tool.py:497-539 | **Mirror** for `forward_input` tool gate. |
| `get_session` / `list_sessions` / `session_count` | tool.py:540 / :544 / :563 | ADD `input_forwarding_enabled` public property near here. |
| `_safe_emit(event_type, data)` | tool.py:761-767 | Reused best-effort emit. |
| router `GET /sessions`, `BridgeConnectRequest`, `POST /bridge/connect`, `_safe_emit`, `require_crew_scope`, `get_runtime`, prefix `/api/browser` | browser_stream.py:134 / :149 / :155 / :31 | **Mirror** for `InputForwardRequest` + `POST /sessions/{id}/input`; EXTEND `GET /sessions` to surface `input_forwarding_enabled`. |
| `_MODES`, `SessionsResponse`, `_defaultFetchSessions`, `renderWatch` BrowserStreamPanel mount (`browser-watch-stream`), `renderBridge` mount | BrowserWorkstation.tsx:139 / :30 / :44 / :~283 | ADD Drive toggle + `forwardInput` prop + pass `driveEnabled`/`onForwardInput` to BOTH panel mounts. |
| `BrowserStreamPanel` `<img data-testid="browser-stream-panel-img">` | BrowserStreamPanel.tsx:64-72 | ADD `driveEnabled?`/`onForwardInput?` props + exported pure `_normalizePointer`. |
| PROGRESS.md header / newest-first | PROGRESS.md:1 / :3 | Prepend AD-1052c entry. |
| DECISIONS.md AD-1052b heading (Era V) | DECISIONS.md (after AD-1052a) | Add `### AD-1052c` after AD-1052b. |

**Phantom check (all INTRODUCED by this build — not pre-existing):** `forward_input`, `input_forwarding_enabled`, `viewport_width`, `viewport_height`, `InputForwardRequest`, `BROWSER_INPUT_FORWARDED`, `BROWSER_INPUT_REFUSED`, `_driven_sessions`, `forwardInput`, `driveEnabled`, `_normalizePointer`, `browser-watch-drive` — grep returned **zero** existing matches.

---

## 3. Files

**target_files**
- `src/probos/events.py` — 2 new EventTypes.
- `src/probos/config.py` — 3 new `BrowserToolConfig` fields.
- `src/probos/tools/browser/session.py` — `forward_input` + viewport resolver + module helpers.
- `src/probos/tools/browser/tool.py` — `forward_input` gate + `input_forwarding_enabled` property + `_driven_sessions`.
- `src/probos/routers/browser_stream.py` — `InputForwardRequest` + `POST /sessions/{id}/input`; extend `GET /sessions`.
- `ui/src/components/browser/BrowserStreamPanel.tsx` — capture props + `_normalizePointer`.
- `ui/src/components/workstation/BrowserWorkstation.tsx` — Drive toggle + `forwardInput` + wire both panel mounts; extend `SessionsResponse`.
- `DECISIONS.md`, `PROGRESS.md`.

**reference_files**
- `src/probos/tools/browser/compute_use.py` (mouse primitive), `src/probos/tools/browser/actions.py` (keyboard/mouse primitives), `tests/test_ad1052b_browser_bridge.py` (real-fixture + TestClient harness), `tests/test_ad1052a_browser_sessions.py` (endpoint harness), `ui/src/components/workstation/BrowserWorkstation.test.tsx` (UI harness).

**test_files**
- `tests/test_ad1052c_browser_input_forward.py` (NEW).
- `ui/src/components/workstation/BrowserWorkstation.test.tsx` (EXTEND), `ui/src/components/browser/BrowserStreamPanel.test.tsx` (NEW or extend).

---

## 4. Step-by-step

### Section 1 — EventTypes (`events.py`, after line 249)

Insert two members after `BROWSER_BRIDGE_DISCONNECTED`:

```python
    BROWSER_INPUT_FORWARDED = "browser_input_forwarded"        # AD-1052c: Captain took the wheel (per drive-episode)
    BROWSER_INPUT_REFUSED = "browser_input_refused"            # AD-1052c: input forward refused (disabled/no-session/no-page/key)
```

### Section 2 — Config (`config.py`, after `bridge_allowed_hosts`, before `credential_vault`)

```python
    # AD-1052c: INPUT-FORWARDING — the human DRIVES the shared browser (clicks +
    # types on the AD-706a watch canvas, forwarded to the live page). SEPARATE,
    # higher-risk gate from `enabled`/`streaming_enabled`. Default-OFF.
    input_forwarding_enabled: bool = Field(
        default=False,
        description=(
            "AD-1052c: enable forwarding human pointer/keyboard input from the "
            "HXI watch canvas to the live browser page. Higher-risk (the human "
            "drives the shared/real browser); default OFF."
        ),
    )
    # AD-1052c: viewport-mapping FALLBACK ONLY. Consulted by forward_input when
    # page.viewport_size is None (e.g. a connect_over_cdp bridge page). NOT wired
    # into new_context() — launched/watch/bridge behavior stays byte-identical.
    viewport_width: int = Field(
        default=1280, ge=1, le=16384,
        description="AD-1052c: viewport width (CSS px) fallback for normalized-coord mapping when page.viewport_size is None.",
    )
    viewport_height: int = Field(
        default=720, ge=1, le=16384,
        description="AD-1052c: viewport height (CSS px) fallback for normalized-coord mapping when page.viewport_size is None.",
    )
```

### Section 3 — `BrowserSession.forward_input` (`session.py`)

Add module-level helpers + a frozenset near the top (after the existing module constants), and the method on the **public** surface (e.g. after `set_last_url` / `is_connected`):

```python
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
```

```python
    def _resolve_viewport(self) -> tuple[int, int]:
        """AD-1052c: real viewport (CSS px) for normalized-coord mapping.

        page.viewport_size is a Playwright Page PROPERTY (dict|None), not a
        coroutine. None for many connect_over_cdp pages -> config fallback.
        """
        page = self._page
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
```

### Section 4 — `BrowserTool.forward_input` gate + property + state (`tool.py`)

In `__init__` (after `_active_viewers`/`_viewer_lock`):

```python
        # AD-1052c: session_ids that have had >=1 forwarded input (the "drive
        # episode" latch). session_ids are uuid4 (never reused) so this set
        # never needs cleanup. Emits BROWSER_INPUT_FORWARDED once per session.
        self._driven_sessions: set[str] = set()
```

Add a public property near `session_count` (Demeter — the router must not read `_config`):

```python
    @property
    def input_forwarding_enabled(self) -> bool:
        """AD-1052c: whether human input may be forwarded to a live page."""
        return bool(getattr(self._config, "input_forwarding_enabled", False))
```

Add the gate method (mirror `connect_bridge_session`, after it):

```python
    async def forward_input(
        self, session_id: str, event: dict[str, Any], *, agent_id: str,
    ) -> dict[str, Any]:
        """AD-1052c: gate -> dispatch -> audit a human-forwarded input event.

        Honest-degrade {"forwarded": False, "reason": ...} when forwarding is
        disabled, the session is gone, or the session's page rejects the event.
        Emits BROWSER_INPUT_REFUSED on every refusal; BROWSER_INPUT_FORWARDED
        once per drive-episode per session (NOT per keystroke).
        """
        if not getattr(self._config, "input_forwarding_enabled", False):
            self._safe_emit(EventType.BROWSER_INPUT_REFUSED, {"reason": "disabled", "session_id": session_id})
            return {"forwarded": False, "reason": "Input forwarding is disabled."}
        session = self._sessions.get(session_id)
        if session is None:
            self._safe_emit(EventType.BROWSER_INPUT_REFUSED, {"reason": "session_not_found", "session_id": session_id})
            return {"forwarded": False, "reason": "Session not found."}
        result = await session.forward_input(event)
        if not result.get("forwarded"):
            self._safe_emit(
                EventType.BROWSER_INPUT_REFUSED,
                {"reason": result.get("reason", "rejected"), "session_id": session_id},
            )
            return result
        if session_id not in self._driven_sessions:
            self._driven_sessions.add(session_id)
            self._safe_emit(
                EventType.BROWSER_INPUT_FORWARDED,
                {"session_id": session_id, "agent_id": agent_id},
            )
        return result
```

### Section 5 — Router (`browser_stream.py`)

Extend the existing `GET /sessions` (surface the flag for the UI Drive-toggle gate — both branches):

```python
@router.get("/sessions", dependencies=[Depends(require_crew_scope)])
async def list_browser_sessions(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"enabled": False, "sessions": [], "input_forwarding_enabled": False}
    return {
        "enabled": True,
        "sessions": browser_tool.list_sessions(),
        "input_forwarding_enabled": browser_tool.input_forwarding_enabled,
    }
```

Add the request model + endpoint (mirror `BridgeConnectRequest` / `POST /bridge/connect`):

```python
class InputForwardRequest(BaseModel):
    """AD-1052c: body for POST /api/browser/sessions/{session_id}/input."""
    kind: str
    nx: float = 0.0
    ny: float = 0.0
    button: str = "left"
    key: str | None = None
    text: str | None = None
    dx: float = 0.0
    dy: float = 0.0


@router.post("/sessions/{session_id}/input", dependencies=[Depends(require_crew_scope)])
async def forward_browser_input(
    session_id: str, body: InputForwardRequest, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1052c: gated human-input forward (thin adapter; all policy in BrowserTool)."""
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"forwarded": False, "reason": "Browser tool is disabled."}
    return await browser_tool.forward_input(session_id, body.model_dump(), agent_id="captain")
```

### Section 6 — `BrowserStreamPanel` capture + pure mapper (`BrowserStreamPanel.tsx`)

Export a pure mapper (mirrors the AD-1052 `_normalizeUrl` exported-for-test pattern) + add **optional** props that, when present, attach handlers to the `<img>` (default behavior byte-identical when absent — DD-5):

```tsx
export type ForwardInputEvent =
  | { kind: 'click'; nx: number; ny: number; button: 'left' | 'right' | 'middle' }
  | { kind: 'scroll'; nx: number; ny: number; dx: number; dy: number }
  | { kind: 'type'; text: string }
  | { kind: 'key'; key: string };

/** Pure, unit-testable: img-relative client coords -> normalized [0,1].
 *  Returns null for a zero-area rect (jsdom layout / not yet laid out). */
export function _normalizePointer(
  clientX: number, clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): { nx: number; ny: number } | null {
  if (rect.width <= 0 || rect.height <= 0) return null;
  const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);
  return {
    nx: clamp01((clientX - rect.left) / rect.width),
    ny: clamp01((clientY - rect.top) / rect.height),
  };
}
```

Props: add `driveEnabled?: boolean` and `onForwardInput?: (evt: ForwardInputEvent) => void`. In the `<img>` branch, when `driveEnabled && onForwardInput`, set `tabIndex={0}`, `cursor: 'crosshair'`, `data-driving="true"`, and attach:
- `onClick` → `_normalizePointer(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect())` → emit `{kind:'click', nx, ny, button:'left'}` (skip when null).
- `onWheel` → emit `{kind:'scroll', nx, ny, dx:e.deltaX, dy:e.deltaY}` (preventDefault).
- `onKeyDown` → if `e.key.length === 1` emit `{kind:'type', text:e.key}`, else if in the allowlist set emit `{kind:'key', key:e.key}` (preventDefault for the handled keys). Keep an exported allowlist const mirroring the backend.

When the props are absent the `<img>` is exactly the current read-only element (no `tabIndex`, no handlers).

### Section 7 — Workstation Drive toggle + wiring (`BrowserWorkstation.tsx`)

- Extend `type SessionsResponse = { enabled: boolean; sessions: SessionRow[]; input_forwarding_enabled?: boolean }`.
- Store `inputForwardingEnabled` from the fetch (`setInputForwardingEnabled(data.input_forwarding_enabled ?? false)`).
- Add `driveEnabled` component state (default `false`) + an injectable `forwardInput?: (sessionId: string, evt: ForwardInputEvent) => Promise<{forwarded:boolean; reason?:string|null}>` prop with a `_defaultForwardInput` (same-origin `POST /api/browser/sessions/${sid}/input`, no token — mirror `_defaultConnectBridge`).
- Render a **Drive toggle** button (`data-testid="browser-watch-drive"`, `aria-pressed={driveEnabled}`, stroke-SVG cursor/hand glyph, amber when active / dim when off) in the watch header next to Refresh **and** in the bridge header — **only when `inputForwardingEnabled`** (DD-5: the toggle never appears when the flag is off). Toggling flips `driveEnabled`.
- Pass `driveEnabled={driveEnabled}` and `onForwardInput={(evt) => { void _forwardInput(activeSessionId, evt); }}` to **both** `<BrowserStreamPanel>` mounts (watch: `sel.session_id`; bridge: `bridgeSession.session_id`). Keep `driveEnabled` falsy when `!inputForwardingEnabled` (belt-and-suspenders).

---

## 5. Design Decisions

- **DD-1 (coordinate protocol).** UI sends normalized `(nx,ny) ∈ [0,1]` (img-relative ÷ rendered img size); backend de-normalizes by the real viewport (`page.viewport_size` → config `viewport_width/height` fallback). Resolution-/DPR-independent; **no viewport size leaks to JS**.
- **DD-2 (event model).** v1 = `click` + `type` + `key` (allowlist) + `scroll`. **Deferred:** `move`/hover, `drag`, file-drop.
- **DD-3 (forward path).** `BrowserSession.forward_input(event)` reuses the agent path's Playwright primitives (`getattr(page,"mouse"/"keyboard",None)`), **not** the `compute_use_click` LLM-vision flow; honest-degrades on no page/handle.
- **DD-4 (governance).** Default-OFF `input_forwarding_enabled` + explicit UI Drive toggle (`aria-pressed`, only when the flag is on) + `BROWSER_INPUT_REFUSED` on every refusal + `BROWSER_INPUT_FORWARDED` **once per session drive-episode** (`_driven_sessions` latch; uuid4 ⇒ no cleanup). The endpoint refuses when the flag is off or the session is gone.
- **DD-5 (default-OFF / non-disruptive).** Drive toggle hidden/inert unless `input_forwarding_enabled`; watch stays read-only by default; the new config fields are **read-only fallbacks** (NOT wired into `new_context`) ⇒ v1 embedded + watch + bridge are byte-identical when off; `config/system.yaml` untouched; the `BrowserStreamPanel` `<img>` is unchanged when the capture props are absent.
- **DD-6 (security).** `nx/ny` clamped to `[0,1]` backend-side; `key` restricted to a non-destructive allowlist (no `Control+*` combos in v1); `text` capped at 4096; `button` validated to `{left,right,middle}`. Coords go to Playwright as **numbers**, text/keys as **literal input events** (`keyboard.type`/`press`) — **nothing is `eval`'d**, so there is no injection vector.

---

## 6. Tests

**Python — `tests/test_ad1052c_browser_input_forward.py`** (BF-287 real fixtures: real `BrowserToolConfig`/`BrowserSession`/`BrowserTool` + real `SystemConfig()` at the auth boundary; a `_FakePage` with `mouse`/`keyboard` recorders + a settable `viewport_size`; **NO real browser**; seed `tool._sessions[sid] = session`):

1. **Coord map happy path:** `viewport_size={"width":1280,"height":720}`, `forward_input({kind:'click', nx:0.5, ny:0.5})` ⇒ recorded `mouse.click(640, 360, button='left')`, returns `{forwarded:True, x:640, y:360}`.
2. **Viewport fallback:** `viewport_size=None`, config `viewport_width=1000`/`viewport_height=500`, `nx:0.5, ny:0.5` ⇒ `mouse.click(500, 250)`.
3. **Clamp:** `nx:1.5, ny:-0.2` ⇒ `mouse.click(1280, 0)` (clamped to [0,1]).
4. **Scroll:** `{kind:'scroll', nx:0.5, ny:0.5, dy:120}` ⇒ `mouse.move(640,360)` then `mouse.wheel(0,120)`.
5. **Type cap:** `{kind:'type', text:'x'*5000}` ⇒ `keyboard.type` called with a 4096-char string.
6. **Key allowlist OK:** `{kind:'key', key:'Enter'}` ⇒ `keyboard.press('Enter')`.
7. **Key allowlist reject:** `{kind:'key', key:'Control+w'}` ⇒ `{forwarded:False, reason:'key_not_allowed'}`, **no** `keyboard.press`.
8. **No page honest-degrade:** session with `_page=None` ⇒ `{forwarded:False, reason:'no_page'}`.
9. **Unknown kind:** `{kind:'paste'}` ⇒ `{forwarded:False, reason:'unknown_kind'}`.
10. **Gate OFF:** `input_forwarding_enabled=False` ⇒ `tool.forward_input(...)` returns `{forwarded:False, "Input forwarding is disabled."}` + a `BROWSER_INPUT_REFUSED` event captured (via an `emit_event` recorder), and the page mouse/keyboard were **never** touched.
11. **Gate session-not-found:** flag on, `tool.forward_input("nope", …)` ⇒ refusal + `BROWSER_INPUT_REFUSED reason=session_not_found`.
12. **FORWARDED once per episode:** flag on, two clicks on the same session ⇒ exactly **one** `BROWSER_INPUT_FORWARDED` event (and a refusal event count of 0).
13. **`input_forwarding_enabled` property:** reflects config (False default; True when set).
14. **Endpoint browser_tool None:** `TestClient` `POST /api/browser/sessions/x/input` ⇒ `{forwarded:False, "Browser tool is disabled."}`.
15. **Endpoint happy path:** seeded runtime + flag on ⇒ `200 {forwarded:True, x, y}` (get_runtime override, mirror `test_ad1052b`).
16. **`GET /sessions` surfaces the flag:** browser_tool None ⇒ `input_forwarding_enabled:false`; seeded + flag on ⇒ `input_forwarding_enabled:true`.
17. **Endpoint auth:** with `crew_scope_token` set + no token ⇒ `401` (mirror the AD-1052a auth test).

**UI — `BrowserStreamPanel.test.tsx`** (+`BrowserWorkstation.test.tsx`):
- `_normalizePointer`: midpoint → `{0.5,0.5}`; out-of-bounds clamps; zero-area rect → `null`.
- Drive toggle **hidden** when `input_forwarding_enabled:false` in the sessions response; **shown** + `aria-pressed` flips when `true` (inject `fetchSessions`).
- With `driveEnabled`, the stream `<img>` gains `tabIndex=0` + `data-driving="true"`; clicking it calls the injected `forwardInput` with a `click` event (mock `getBoundingClientRect`); without `driveEnabled` the `<img>` has no `tabIndex`/handlers.
- No-emoji guard on the new toggle (`EMOJI = /\p{Extended_Pictographic}/u`); `data-testid` present.

---

## 7. Acceptance Criteria

- **Python gate:** `d:\ProbOS\.venv\Scripts\pytest.exe tests/test_ad1052c_browser_input_forward.py -q -n 0` green; then full gate `pytest tests/ -q -n 4 --dist=loadfile` shows **no new** failures vs the recorded baseline (the 16 pre-existing xdist/ordering flakes in `ad1019e_baseline.txt` are unrelated).
- **UI gate:** `cd ui; npx vitest run` green (focused new tests + full baseline, 0 regressions) **and MANDATORY** `cd ui; npm run build` (tsc -b + vite) **clean**.
- **Default-OFF proven:** with `input_forwarding_enabled=false` the endpoint refuses + the Drive toggle is absent; the `<img>` is byte-identical when capture props are absent.
- **No `config/system.yaml` edit; no new npm dependency; layer discipline** (router → `browser_tool` public surface only; tool → `session.forward_input` public; no `_config`/`_page` cross-module reads).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 8. Do NOT build

- **Proxy / arbitrary cross-origin embedding** → AD-1052d.
- **`move`/hover, `drag`, file-drop, modifier key-combos** (Control+*, etc.) → a later slice (DD-2 deferral; combos are the AD-706e tier-3 surface).
- **Do NOT rebuild** the AD-706/706a/1052a/1052b engine, stream, session lifecycle, or governance — REUSE the primitives + the `connect_bridge_session` gate pattern + `_safe_emit`/`EventType`.
- **Do NOT mint/store a crew-scope token in JS** (AD-1052a DD-1: same-origin, no token).
- **Do NOT wire the new `viewport_*` config into `new_context()`** — they are read-only mapping fallbacks.
- **Do NOT add a new top-level AD number** — this is AD-1052c.

---

## 9. Tracking

- **DECISIONS.md** (Era V): add `### AD-1052c — Browser Workstation INPUT-FORWARDING (epic #965)` **after** the AD-1052b entry. State: highest landed top-level = AD-1052; the reuse-vs-add finding (ADD `forward_input`, reuse primitives, reject `compute_use_click`); DD-1 viewport mapping (config had no viewport ⇒ `page.viewport_size` + new fallback fields, not wired into `new_context`); DD-4 governance (flag + Drive toggle + per-episode audit); the additive count (2 Python core + 1 router + 1 config + 2 UI). End with the compliance line.
- **PROGRESS.md:3** — prepend a newest-first `**AD-1052c staged (YYYY-MM-DD) …**` entry mirroring the AD-1052b paragraph shape (headline DD-1 viewport + DD-4 governance + additive file list + gate counts + STAGED-not-committed).
- `roadmap.md` — no browser-workstation row exists (AD-1052/a/b precedent) ⇒ not touched.
