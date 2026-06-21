# AD-1052 — Browser / Web-App Workstation (v1: embedded-iframe mode + unifying mode model)

**Epic:** #965 (HXI Workspaces) — the **third and last** workstation type (monaco=AD-1021 ✅, mcp-app=AD-1024 ✅, **browser=AD-1052**).
**Status:** Ready to build. **Slice:** v1 of a 3-slice plan (this file = v1; AD-1052a/b/c/d = named follow-ons, NOT built here).
**Type:** Architecture Decision (Experience layer — HXI native workstation component).
**Estimated tests:** ~14 vitest (2 new files + 1 count bump). **No pytest** (pure-UI, no backend).
**Verified against HEAD `b39ff727`.**

---

## AD numbering (verify-first — the brief's assumed number was wrong)

- Highest **landed** in `DECISIONS.md`: **AD-1038**.
- **AD-1039 is RESERVED** — AD-1038 DD-7 ("know"-down-weighting in consensus, deferred). Grep: `DECISIONS.md:119`, `PROGRESS.md:15,17`, `tests/test_ad1038_remember_know_render.py:10`.
- **AD-1040 → AD-1051 are RESERVED** — the ARD Integration epic drafts (`prompts/ard-epic-decisions-draft.md:3`: *"highest landed AD-1038, AD-1039 reserved … this epic is AD-1040 → AD-1051"*; draft prompt files `prompts/ad-1040..1051-*.md` exist, none landed).
- **Next free top-level: `AD-1052` → this is AD-1052.** Slices get letter suffixes (AD-1052a..d). No collision (no `### AD-1052` heading exists; grep clean).

---

## Research findings (absorbed patterns — sources named)

The Captain's requirement: one browser workstation flexible enough for **headless** (agent drives, human watches), **bridge/external** (control a real separate Chrome the human also uses), and **embedded/shared** (a browser surface inside the HXI both human and agents see/drive, "like VS Code browser sharing"). Distilled architecture:

| Mode | Mature-tool pattern absorbed | Source | ProbOS fit |
|---|---|---|---|
| **Headless + programmatic** | `chromium.launch({headless:true})` then a screenshot→action→screenshot loop; live view via CDP `Page.startScreencast` → `screencastFrame{data:b64,metadata}` events (or repeated `Page.captureScreenshot{jpeg}`). | Playwright `BrowserType.launch` (Apache-2.0, playwright.dev); CDP `Page` domain (chromedevtools.github.io/devtools-protocol/tot/Page); Anthropic computer-use-demo screenshot-loop (MIT). | **Already shipped as AD-706.** `BrowserSession.start()` launches `chromium.launch(headless=config.headless)`; AD-706a streams via `page.screenshot(type="jpeg")` over MJPEG. |
| **Attach-to-external (bridge)** | `chromium.connectOverCDP('http://localhost:9222')` attaches to an already-running Chrome started with `--remote-debugging-port`; `noDefaults` is "useful when attaching to a user's daily-driver browser." The user must launch Chrome with the debug port **and a separate `--user-data-dir`** (Chrome blocks automating the default profile). Chromium-only; "significantly lower fidelity than the Playwright protocol." | Playwright `BrowserType.connectOverCDP` (playwright.dev). | **Not yet built** → AD-1052b. High-risk (drives the human's real browser) → consent gate. |
| **Embedded / shared in an IDE** | A webview = "an `iframe` the extension controls." JS off by default (`enableScripts`), CSP via `<meta http-equiv="Content-Security-Policy">`, `localResourceRoots` restriction. **Arbitrary cross-origin sites that send `X-Frame-Options`/`frame-ancestors` CSP cannot be iframed** — that's why VS Code's Live Preview proxies local content and Simple Browser only frames permissive URLs. True "sharing" of an arbitrary site needs a real browser process + a screencast surface (CDP `startScreencast` → canvas), with the human's clicks forwarded back as CDP `Input.dispatchMouseEvent/dispatchKeyEvent`. | VS Code Webview API (code.visualstudio.com/api/extension-guides/webview); CDP `Input`/`Page` domains. | **v1 embedded = sandboxed `<iframe src=url>`** (Simple-Browser style, for embeddable URLs). **True shared-screencast = AD-1052a (watch) + AD-1052c (input-forward).** |
| **Agentic action vocabulary** | navigate · click(index|x,y) · type · scroll · screenshot · back/forward, in a screenshot→action loop. | Anthropic Computer Use / browser-use (MIT; cited verbatim in `tools/browser/tool.py` docstring). | **= the AD-706 vocabulary** (`goto/state/click/type/scroll/screenshot/wait/back/forward/extract_text` + AD-706c-2 `compute_use_click` + AD-706e `drag/key_combo/mouse_move/mouse_button/upload_file/download/eval_js`). |

**ProbOS-fit synthesis — one type, one mode, one contract.** A single `browser` workstation type with `mode ∈ {embedded, watch, bridge}` sharing **one observation/action contract = the AD-706 vocabulary**:
- **Observation:** `screenshot` (b64 / MJPEG frame) + `state` (indexed DOM) + `url` + `title`.
- **Action:** `navigate(url)` · `click(index|x,y)` · `type(text)` · `scroll(dir,amount)` · `key(combo)` · `back/forward`.

The three modes are different **transports/surfaces over the same contract**: *embedded* = a native iframe (the live page IS the observation; the human drives it natively, no forwarding needed); *watch* = MJPEG observation of an AD-706 headless session (agent drives); *bridge* = the same AD-706 vocabulary aimed at an attached external Chrome. **v1 ships the `embedded` surface + the mode model that names `watch`/`bridge` as follow-ons; the AD-706 engine is REUSED (never rebuilt) by the follow-on slices that drive it.**

---

## Slice boundary

| AD | Scope | Build here? |
|---|---|---|
| **AD-1052 (v1)** | `browser` native workstation component, **embedded-iframe mode** (sandboxed `<iframe>` to a human-entered URL) + the unifying **mode model** (embedded active; watch/bridge named + disabled) + a reachable overlay + `nativeWorkstations` registration. **Pure-UI, default-OFF, no backend, no `config/system.yaml` change.** | ✅ **YES** |
| **AD-1052a** | **watch/screencast** mode: mount the already-built AD-706a `BrowserStreamPanel` (MJPEG `<img>`), add `GET /api/browser/sessions` + `BrowserTool.list_sessions()`, and wire the crew-scope token into the HXI. The AD-706 engine-reuse + "human watches the agent's live browser (shared)". | ❌ named follow-on |
| **AD-1052b** | **bridge-external** mode: `BrowserSession.connect_over_cdp()` via Playwright `connectOverCDP` to a user-launched Chrome (`--remote-debugging-port`), behind a **HookBus/consensus consent gate** (driving the human's real browser is high-risk). | ❌ named follow-on |
| **AD-1052c** | **bidirectional input-forwarding**: the human clicks/types on the watch canvas → forwarded as CDP `Input.dispatch*` / AD-706c-2 `compute_use_click` + AD-706e `type/scroll`. Destructive-capable → governance. Builds on AD-1052a. | ❌ named follow-on |
| **AD-1052d** | **proxied embedding** for arbitrary cross-origin (server-side reverse proxy stripping `X-Frame-Options`/CSP so any URL frames). Security-sensitive. | ❌ named follow-on |

**Why `watch` is NOT in v1 (the honest finding).** The AD-706a MJPEG stream is guarded by `require_crew_scope`. **There is no crew-scope token anywhere in `ui/src`** (grep = 0 matches). `require_crew_scope` is a *pass-through when `auth.crew_scope_token` is empty* (the default, `routers/auth.py:52`), so watch would work token-free in default dev — **but the moment an operator sets the token, the HXI `<img>` 401s.** Exposing the crew-scope token (which authorizes *all* crew-scoped endpoints) to browser JS is a real security decision that deserves its own AD. Watch is also only useful when `browser_tool.enabled` **AND** `streaming_enabled` **AND** an agent has a live session — too precondition-heavy for the v1 surface. The embedded-iframe mode has **one** precondition (`workstations.enabled`) and is immediately, reliably useful. So v1 = embedded; the AD-706 engine reuse + the token security decision land in AD-1052a.

---

## Verified API / file map (HEAD `b39ff727`)

### The backend `browser` type is ALREADY registered (mirrors AD-1021's situation exactly)
- `src/probos/startup/finalize.py:217` `_wire_workstation_types`, baselines tuple:
  ```python
  baselines = (("monaco","Code Editor","monaco"), ("browser","Browser","browser"), ("chat","Chat","chat"))
  ```
  registered native (`WorkstationRender(kind="native", component_key="browser")`), gated on `WorkstationsConfig.enabled`. **The AD's only job is the `browser` React native component + registering it in `nativeWorkstations.ts`** — identical to how AD-1021 supplied `monaco`'s component for an already-registered type.
- `src/probos/workstations/registry.py:62` — `WorkstationRender` docstring explicitly names `browser` as a planned native `component_key` ("monaco/browser/chat").
- `src/probos/config.py:3050` `WorkstationsConfig.enabled=False` (default-OFF). `config.py:1455` `BrowserToolConfig(enabled=False, headless=True, streaming_enabled=False)`.

### The UI render seam (confirmed-exists)
- `ui/src/components/workstation/WorkstationLauncher.tsx:31` — `NativeWorkstationProps = { typeId: string; doc?: WorkstationDoc | null }`. `WorkstationRender` (same file) resolves `deps.nativeComponents[type.id]` → `<Native typeId doc />`, else a "not yet available" placeholder.
- `ui/src/components/workstation/nativeWorkstations.ts:18` — `{ monaco: CodeWorkstation, 'mcp-app': …gallery… }`. **ADD `browser: BrowserWorkstation`.**
- `ui/src/components/workstation/WorkstationPanel.tsx` (AD-1021) — the overlay to MIRROR: store-flag `workstationOpen` gated, mounted-but-null when closed, Escape/X close, renders `<CodeWorkstation typeId="monaco" />` directly. Mounted at `App.tsx:119`.
- `ui/src/components/workstation/CodeWorkstation.tsx` — the component to mirror: `NativeWorkstationProps`, `doc = propDoc !== undefined ? propDoc : storeDoc`, Copy/Download (`IconCopy`/`IconDownload`), `_AMBER='#f0b060'`/`_DIM='#666680'`, stroke-SVG `strokeWidth:1.5`, `data-testid` on every interactive element, NO emoji.
- `ui/src/components/workspace/WorkspacePanel.tsx:88` (AD-1023) — `nativeComponents` default = `nativeWorkstations`, so adding `browser` there **auto-composes into the AD-1023 container** for free.
- `ui/src/components/McpAppFrame.tsx:12` (AD-597a) — the sandbox *pattern* to reuse: `external ? 'allow-scripts' : 'allow-scripts allow-same-origin'`. (It hardcodes `src='/api/mcp/resource?uri='+…`, so it can't render an arbitrary URL — v1 builds its **own** `<iframe>`; reuse the sandbox discipline, not the component.)

### Store + entry-point seam
- `ui/src/store/useStore.ts:374` (`workstationOpen` type) / `:900` (default) / `:1144` (`openWorkstation`) — the AD-1021 flag pattern. The simplest mirror is `mcpServersOpen`/`mcpAppsOpen`/`shipsLockerOpen`: a boolean toggled via `useStore.setState({ xOpen: true })`, closed via `setState({ xOpen: false })` — **no dedicated action**.
- `ui/src/App.tsx:118-121` mounts `<McpServersPanel/> <WorkstationPanel/> <WorkspacePanel/> <McpAppsPanel/>` — **ADD `<BrowserWorkstationPanel/>` here.**
- `ui/src/components/bridge/stations.tsx:163-173` engineering `actions[]` — the launch-action mirror:
  ```tsx
  { id: 'mcp-apps-toggle', label: 'MCP Apps', onInvoke: () => useStore.setState({ mcpAppsOpen: true }) },
  { id: 'workstation-toggle', label: 'Workstation', onInvoke: () => useStore.getState().openWorkstation({ kind:'scratch', … }) },
  ```
  **ADD** `{ id: 'browser-workstation-toggle', label: 'Browser', onInvoke: () => useStore.setState({ browserWorkstationOpen: true }) }`. Co-located `ui/src/components/bridge/__tests__/stations.test.tsx` likely asserts an action count → bump it (AD-1024 obsolete-contract precedent).
- `ui/src/store/types.ts:86` `WorkstationDoc` — **NOT extended** in v1 (the browser workstation is self-contained; it ignores `doc`, exactly as the AD-1024 `mcp-app` adapter ignores `typeId`/`doc`). Forward marker AD-1052e = doc-driven deep-link (initial URL).

### The AD-706 engine to REUSE (do NOT rebuild — for the follow-on slices)
- `src/probos/tools/browser/{tool.py,session.py,actions.py,credentials.py,compute_use.py,llm_classifier.py,recording_reaper.py}`. `BrowserTool.tool_id="browser"`, `invoke(params,context)`, owns `_sessions` (`tool.py:468 get_session`). `session.py:start()` → `chromium.launch(headless=self._config.headless)`; `get_streaming_url()` → `/api/browser/sessions/{sid}/stream` when `streaming_enabled`.
- `ui/src/components/browser/BrowserStreamPanel.tsx` (AD-706a) — `<img src=streamingUrl>` + optional `token?` prop, **already built, NOT yet wired** (forward marker AD-706a-parent-wire). This is AD-1052a's embedded-watch surface.
- `src/probos/routers/browser_stream.py` — `GET /api/browser/sessions/{sid}/stream` (`require_crew_scope` + `?token=`). Registered in `api.py:200,236`.

### Phantom checks (all confirmed-exist, none fabricated)
`nativeWorkstations`, `NativeWorkstationProps`, `WorkstationPanel`, `CodeWorkstation`, `workstationOpen`, `mcpAppsOpen`, `mcp-apps-toggle`, `_wire_workstation_types` browser baseline, `WorkspacePanel` `nativeComponents` default — **all verified present at HEAD `b39ff727`.** No new EventType, no new config field, no `config/system.yaml` change.

---

## Implementation (v1)

### Step 1 — `BrowserWorkstation.tsx` (NEW, `ui/src/components/workstation/`)
A self-contained native workstation component. `NativeWorkstationProps` (`{ typeId, doc? }`); v1 ignores `doc` (self-contained, mirrors the AD-1024 `mcp-app` adapter). Internal state: `mode: 'embedded' | 'watch' | 'bridge'` (default `'embedded'`), `urlInput: string`, `committedUrl: string | null`.

- **Toolbar (HXI #3):** a **mode selector** (3 stroke-SVG segmented buttons: Embedded active; Watch + Bridge **disabled** with `title="Available in AD-1052a"` / `"AD-1052b"`), a URL textbox + Go button (embedded mode), a Reload button. Amber active `#f0b060` / dim `#666680`. Every control has a `data-testid`. NO emoji.
- **Embedded body:** a sandboxed `<iframe data-testid="browser-workstation-iframe" src={committedUrl} sandbox="allow-scripts allow-same-origin allow-forms allow-popups" referrerPolicy="no-referrer" style={{ border:0, width:'100%', height:'100%' }} />`. Render the iframe only when `committedUrl` is set, else an empty-state ("Enter a URL to load a page").
- **URL validation (defense-in-depth):** a `_normalizeUrl(raw)` helper — accept only `http:`/`https:` (prepend `https://` when scheme-less); **reject `javascript:`/`data:`/`file:`/`blob:`** → return null → show an inline "Only http(s) URLs are supported." notice. Never put unvalidated input into `src`.
- **Honest-degrade note:** a dismissible inline banner under the toolbar: *"Some sites refuse to embed (X-Frame-Options / CSP frame-ancestors). For those, use Watch mode (AD-1052a) or Bridge mode (AD-1052b)."* (Static text — v1 does not attempt to detect the refusal, which is not reliably observable cross-origin.)
- **Watch/Bridge bodies:** a placeholder pane (`data-testid="browser-workstation-mode-pending"`) naming the follow-on AD. The selector buttons for these are `disabled` so they're un-clickable in v1 (the placeholder is only reachable if a future doc forces the mode — defensive).

### Step 2 — `BrowserWorkstationPanel.tsx` (NEW, `ui/src/components/workstation/`)
**Mirror `WorkstationPanel.tsx` exactly.** Store-flag `browserWorkstationOpen` gated → `if (!open) return null;`. Full-screen overlay (same styles as `WorkstationPanel`: `position:fixed; inset:0; zIndex:30; …`). Header: stroke-SVG browser glyph (a framed window + an address bar line — NO emoji) + title "BROWSER WORKSTATION" + a one-line subtitle. Close via header X (`data-testid="browser-workstation-close"`) and Escape (`useEffect` keydown). Body renders `<BrowserWorkstation typeId="browser" />` directly. Close = `useStore.setState({ browserWorkstationOpen: false })`.

### Step 3 — register + wire
- `nativeWorkstations.ts`: add `browser: BrowserWorkstation` (import it). This auto-composes into the AD-1023 `WorkspacePanel` and is what the AD-1022 launcher-seam test exercises.
- `store/useStore.ts`: add `browserWorkstationOpen: boolean` to the state type (next to `workstationOpen` ~`:374`), default `false` (next to `:900`). **No action** (mirror `mcpServersOpen`/`mcpAppsOpen`).
- `App.tsx`: import + mount `<BrowserWorkstationPanel />` after `<WorkspacePanel />` (`:120`).
- `bridge/stations.tsx`: add the `browser-workstation-toggle` engineering action (after `workstation-toggle`, `:172`).

### Step 4 — tests
- `BrowserWorkstation.test.tsx` (NEW, co-located, ~8): default mode = embedded; valid URL commits → iframe `src` set with the sandbox attr; scheme-less URL gets `https://` prepended; `javascript:`/`file:` rejected → notice shown, no iframe; Watch/Bridge buttons are `disabled`; empty-state before a URL; honest-degrade banner renders + dismisses; **no-emoji** guard (`/\p{Extended_Pictographic}/u` over `?raw`); `data-testid` present.
- `BrowserWorkstationPanel.test.tsx` (NEW, co-located, ~5): null when `browserWorkstationOpen` false (and renders nothing / no iframe); renders `BrowserWorkstation` when open; Escape closes (flag → false); X closes; **launcher-seam** test — mount `WorkstationRender`/`WorkstationLauncher` with `deps.nativeComponents={ browser: BrowserWorkstation }` and a `{ id:'browser', render_kind:'native', available:true }` type → asserts `BrowserWorkstation` renders (proves the AD-1022 seam, mirrors AD-1021's launcher-seam test); no-emoji guard.
- `bridge/__tests__/stations.test.tsx`: bump the engineering action-count assertion by 1 (obsolete-contract update, AD-1024 precedent). Add an assertion that the `browser-workstation-toggle` action sets `browserWorkstationOpen`.

---

## Design decisions

- **DD-1 (one type, one mode model, one contract).** A single `browser` type with `mode ∈ {embedded, watch, bridge}` over the AD-706 observation/action contract (screenshot+state+url+title / navigate+click+type+scroll+key+back/forward). v1 ships `embedded`; `watch`/`bridge` are named + disabled in the selector.
- **DD-2 (reuse, don't rebuild).** v1's embedded mode is a UI surface (sandboxed iframe) — it touches **no** browser engine. The AD-706 Playwright engine (already shipped) is reused **only by the follow-on slices** (1052a watch, 1052b bridge, 1052c input-forward). v1 adds **zero** Python.
- **DD-3 (embedded = iframe, not screencast).** v1 embedded renders a native sandboxed `<iframe>` (VS Code Simple-Browser pattern) — works for embeddable URLs, human-driven, no engine. True shared-screencast of arbitrary sites (CDP `startScreencast` → canvas + `Input.dispatch*` forwarding) = AD-1052a + AD-1052c. Stated honestly because arbitrary cross-origin sites can't be iframed (X-Frame-Options/CSP).
- **DD-4 (self-contained component, no `WorkstationDoc` churn).** v1 ignores `doc` (mirrors the AD-1024 `mcp-app` adapter). No `WorkstationDoc` kind-union expansion. Doc-driven initial URL = AD-1052e.
- **DD-5 (reachable host = a dedicated overlay).** Mirror AD-1021's `WorkstationPanel`: a `BrowserWorkstationPanel` overlay gated on `browserWorkstationOpen`, mounted in `App.tsx`, launched from the Engineering station. The AD-1022 launcher/AD-1023 container compose it too (registered in `nativeWorkstations`), proven by the launcher-seam test.
- **DD-6 (security).** Embedded iframe `sandbox="allow-scripts allow-same-origin allow-forms allow-popups"` — for a *cross-origin* frame, `allow-same-origin` only grants the framed site access to **its own** origin storage (Same-Origin Policy still blocks any access to the parent HXI origin). URL-scheme allowlist (`http`/`https` only) blocks `javascript:`/`data:`/`file:` injection. `referrerPolicy="no-referrer"`. The high-risk surfaces — bridge (drives the human's real browser) and input-forwarding (Computer-Use on a shared browser) — are **destructive-capable and gated behind a HookBus/consensus consent model in AD-1052b/c**, never in v1.
- **DD-7 (default-OFF, non-disruptive).** Backend type registration is gated on `WorkstationsConfig.enabled` (already the case). The overlay is gated on `browserWorkstationOpen=false`. Both off ⇒ byte-identical; the only always-on change is the inert `nativeWorkstations` map entry + the Engineering launch action (both no-ops until workstations are enabled / the panel is opened). **No `config/system.yaml` change.**

---

## Acceptance criteria

- `cd ui; npx vitest run` — establish the current full baseline FIRST (do not hardcode; ~256 files at HEAD). After: **full suite ≥ baseline + new tests, 0 regressions**; focused `BrowserWorkstation.test.tsx` + `BrowserWorkstationPanel.test.tsx` green; the `stations.test.tsx` count bump green.
- `cd ui; npm run build` — **MANDATORY, exit 0** (vitest misses TS drift). No materially larger main chunk (BrowserWorkstation is a tiny presentational component; no new heavy dep).
- **No backend / pytest changes** in v1 (pure-UI). If the Builder finds itself editing any `src/probos/**` file, **STOP** — that's out of v1 scope.
- Default-OFF proven: with `browserWorkstationOpen=false` the panel renders null and loads no iframe; with `WorkstationsConfig.enabled=false` the type is absent from the catalog (unchanged backend behavior).
- **No `config/system.yaml` change. No new npm dependency. No emoji** (stroke-SVG only). Every interactive element has a `data-testid`. Deps-injectable where the AD-1021/1023 precedents are.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Do NOT build (explicit out-of-scope)
- The AD-706 Playwright **engine** (already shipped — reuse, never rebuild).
- **Watch/screencast** mode wiring, `GET /api/browser/sessions`, `BrowserTool.list_sessions()`, `BrowserStreamPanel` mount, crew-scope-token-in-HXI → **AD-1052a**.
- **Bridge-external** `connectOverCDP` + consent gate → **AD-1052b**. **Bidirectional input-forwarding** → **AD-1052c**. **Cross-origin proxy** → **AD-1052d**. **Doc-driven initial URL** → **AD-1052e**.
- Any `WorkstationDoc` type change, any backend file, any `config/system.yaml` edit, any new EventType.
- Do NOT reference the commercial AD-C-022 immersive cockpit (it registers through the AD-1022 iframe seam in the private overlay — out of bounds for OSS).

## Tracking
- `DECISIONS.md`: append a `### AD-1052 — Browser/Web-App Workstation (v1: embedded-iframe + mode model)` entry — the 7 DDs, the slice boundary (1052a/b/c/d/e forward markers), the research synthesis (one type/mode/contract), default-OFF, files. (Shipped-only, append at ship time.)
- `PROGRESS.md`: prepend the AD-1052 block (v1 scope, mode model, AD-706-reuse-deferred-to-1052a rationale, test counts, gate results).
- `docs/development/roadmap.md`: mark the epic #965 browser-workstation row shipped (v1) with the 1052a–e forward markers.
