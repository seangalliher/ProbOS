# AD-759 - Yeo Native Desktop Tray App (v1: Electron host + tray + deep-link + notifications)

Status: drafted (Wave 186, scope-split applied during architect review)
Issue: #705
Depends on: AD-751 desktop-runtime primitives (Python-side; SHIPPED Wave 181)
Priority: 2

## Why this AD exists

AD-751 shipped the Python-side desktop-runtime primitives (`src/probos/experience/desktop/{tray,lifecycle,notifications,hotkey}.py`), but did not ship a native packaged desktop host. The Captain requirement is explicit: the daily-driver Yeo entry point must run as a real tray app.

This AD delivers the **v1 Electron host** that wraps the existing browser HXI and provides reliable OS-level tray behavior. **Installer, auto-update, CI release pipeline, and launch-at-login are split into forward-marker ADs** (see below).

## Current highest AD number

Verified against `docs/development/roadmap.md` Yeo table: highest SHIPPED AD is **AD-758**. AD-759..AD-766 already have prompt files queued. This prompt keeps **AD-759**. Forward markers below use the sub-letter pattern (`AD-759a..e`) to avoid collision with AD-760+.

## Scope split applied during architect review

The original AD-759 spec listed: tray host + single-instance + deep-link + notifications + launch-at-login + signed installer pipeline + auto-update + CI artifact pipeline. That is genuinely multi-day, multi-tier work and packs three different concerns (UX shell, packaging/distribution, release infrastructure) into one prompt. Splitting at architect review:

| AD | Scope | Status |
|----|-------|--------|
| **AD-759 (this prompt)** | Electron host shell, tray menu, single-instance lock, `probos://` deep-link, native notifications with click-through, runtime-disconnected repair surface | v1 — Wave 186 |
| AD-759a | Launch-at-login (Windows registry / macOS LaunchAgent / Linux .desktop autostart) | forward marker |
| AD-759b | NSIS installer + **unsigned** Windows release artifact | forward marker |
| AD-759c | Auto-update — check-only against GitHub Releases (no managed update server) | forward marker |
| AD-759d | Signed installer + EV code-signing cert workflow (commercial-overlay or operator BYO cert) | forward marker — see License posture |
| AD-759e | CI release pipeline (GH Actions matrix build for Windows/macOS/Linux) | forward marker |
| AD-759-1 | macOS menubar parity | forward marker (already in original prompt) |
| AD-759-2 | Linux tray parity | forward marker (already in original prompt) |

## Prior-art references (architecture only — no code reuse)

1. **openclaw/openclaw-windows-node** (MIT): dedicated tray host as first-class project, single-instance behavior, deep-link forwarding through IPC, first-run onboarding sequence.
2. **hermes-desktop/hermes-desktop** (MIT): Electron host pattern, explicit installer artifacts per OS, local/remote backend mode toggle.
3. **Claude Cowork** (product pattern; no code reuse): "set it once" recurring tasks framing, "show plan, require approval" interaction model.

**Architect rule:** absorb the PATTERN (architecture, IPC shape, lifecycle ordering), write own code, cite upstream as research. Do not copy source from these repos into `desktop/`. Both upstreams are MIT-licensed, so direct vendoring would be legal, but the project policy is pattern-absorption to keep license attribution surface minimal.

## License + dependency posture (Captain rule)

ProbOS OSS is Apache 2.0 — operators must be able to use the OSS without paid licenses or paid certs. All new desktop dependencies must be permissively licensed:

| Dependency | License | Role |
|-----------|---------|------|
| Electron | MIT | Host runtime (Chromium + Node) |
| electron-builder | MIT | Packaging (used at AD-759b, NOT in this AD) |
| electron-vite | MIT | Vite integration for main + preload + renderer |
| electron-updater | MIT | Auto-update (deferred to AD-759c) |

**Code-signing posture (HARD RULE):**
- OSS ships **unsigned** Windows binaries. Operators see the SmartScreen warning on first install; documented in `docs/getting-started/desktop.md` with the standard "More info → Run anyway" steps and a SHA-256 checksum the operator can verify against the GitHub Release.
- Signed binaries (Windows EV cert ~$300/yr; Apple Developer ID for macOS) become a **commercial-overlay** concern. Filed as AD-759d.
- This AD MUST NOT add code-signing scripts, cert handling, or notarization. Builder enforces this in review.

**Bundle-size disclaimer (HARD RULE):**
- Electron adds ~80 MB to the installer and ~150 MB installed footprint. The HXI bundle itself is ~3.3 MB (gzip ~920 KB) per the current `ui/dist/` build.
- This is acceptable for a desktop daily driver but must be called out in `docs/getting-started/desktop.md`. Operators with size constraints should continue to use the browser HXI.

**Auto-update posture (HARD RULE for v1):**
- No managed update server. v1 (this AD) has NO update mechanism wired.
- AD-759c will add check-only auto-update against the GitHub Releases atom feed. Install requires operator action (no silent auto-install).

## Scope (v1 — what this AD ships)

1. **Electron host shell** wrapping the existing HXI at `http://127.0.0.1:8765` (the runtime's default `bind_host`/`bind_port` per `src/probos/config.py:1012-1013`). Configurable via env var `PROBOS_RUNTIME_URL` for non-default deployments.
2. **Tray icon + menu** (Windows-first; menu items render but no-op on macOS/Linux until parity ADs):
   - Status (shows runtime-connected / -disconnected)
   - Open chat
   - Daily briefing
   - Quick capture
   - Pause / resume proactive mode
   - Settings
   - Quit
3. **Single-instance lock**: second launch forwards activation intent (`probos://...` or "show window") to the first instance via Electron's `app.requestSingleInstanceLock()` and exits with code 0.
4. **`probos://` deep-link scheme**: registered as OS-level protocol handler on first run. Payloads validated (no shell-injection, no path traversal — see Security below). Routes to existing HXI paths: `probos://chat/<agent_id>`, `probos://briefing`, `probos://settings`.
5. **Native notifications with click-through actions**: posted from runtime via existing notifications API; click navigates the renderer to the requested route.
6. **Runtime-disconnected repair surface**: if the renderer cannot reach `127.0.0.1:8765`, show an explicit error state with "Retry" and "Open browser HXI" actions. Does NOT spawn the runtime — the desktop host **assumes the runtime is started independently** (per AD-751 autostart). Spawning the Python runtime from Electron is out of scope.

## Non-scope (v1)

1. Launch-at-login (AD-759a)
2. Any installer artifact — `npm run package` produces an unpacked `dist/` only (AD-759b)
3. Auto-update (AD-759c)
4. Code-signing (AD-759d)
5. CI release pipeline (AD-759e)
6. macOS / Linux parity (AD-759-1 / AD-759-2)
7. Re-implementing Yeo cognition or M365 logic in the host
8. Replacing the browser HXI — the host wraps it; browser mode continues to work unchanged

## Proposed architecture

1. **Host type**: Electron 33+ (MIT), wrapping the existing HXI route surface via a single `BrowserWindow` pointed at `http://127.0.0.1:8765`.
2. **Process model**:
   - Main process: tray icon, notifications, deep links, single-instance lock, IPC dispatch.
   - Renderer process: existing HXI (no new React routes; the existing UI is unchanged).
   - Preload: minimal typed IPC bridge (`nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`).
3. **Runtime binding**: HTTP/WebSocket to `127.0.0.1:8765`. The HXI already handles auth via the existing API key flow — desktop host does NOT introduce new auth surface.
4. **Workspace placement**:
   - New top-level `desktop/` directory (Electron app). **Confirmed no collision**: `src/probos/experience/desktop/` is the Python-side primitives (tray.py / lifecycle.py / notifications.py / hotkey.py from AD-751); `desktop/` top-level is the Electron host. Documented in `docs/getting-started/desktop.md` to prevent operator confusion.
   - NOT a subdirectory of `ui/` — the Electron app is a sibling workspace with its own `package.json`. The existing `ui/` continues to be the browser HXI build root. The Electron app loads `http://127.0.0.1:8765` in v1 (renderer fetches the served HXI). Embedding `ui/dist/` as a local file load is deferred (would require build coupling between `ui/` and `desktop/`).

## Security posture

1. **No secrets in renderer localStorage** — REQUIRED audit during build. Builder must `grep -rn "localStorage.setItem" ui/src/` and flag any hit that stores keys/tokens/credentials. If found, file a remediation AD before this prompt lands; do NOT proceed with the desktop wrapper until the browser HXI is clean (otherwise the wrapper inherits the leak).
2. **No `nodeIntegration` in renderer**, `contextIsolation: true`, `sandbox: true` on the `BrowserWindow`. Hard requirement; review-blocker if violated.
3. **OS-protected credential storage**: ProbOS already has `src/probos/security/credential_encryption.py` (DPAPI-class abstraction). The Electron host does NOT store credentials directly — it relies on the runtime's existing keystore via authenticated HTTP. No OS-keychain code in `desktop/` in v1.
4. **Deep-link sanitization** — explicit validation rules in `desktop/src/main/deep-link.ts`:
   - Allowlist of route prefixes: `chat/`, `briefing`, `settings`, `capture`.
   - Reject any payload containing `..`, `/` outside the allowed route token position, `\`, null bytes, or non-printable chars.
   - Reject any URL whose `host` portion is non-empty (defends against `probos://attacker.example.com/path`).
   - Max payload length 256 chars.
   - Test cases REQUIRED: each rejection rule has a unit test.

## File targets

1. `desktop/` — new top-level workspace
2. `desktop/package.json` (declares Electron + electron-vite as dev deps)
3. `desktop/electron.vite.config.ts`
4. `desktop/tsconfig.json`
5. `desktop/src/main/index.ts` — main process entry
6. `desktop/src/main/tray.ts` — tray icon + menu
7. `desktop/src/main/single-instance.ts` — single-instance lock + activation IPC
8. `desktop/src/main/deep-link.ts` — `probos://` registration + sanitization
9. `desktop/src/main/notifications.ts` — native notifications + click-through routing
10. `desktop/src/preload/index.ts` — typed IPC bridge
11. `desktop/src/renderer/index.html` — shell that loads the runtime HXI URL
12. `desktop/build/icons/` — tray + window icons (PNG; SVG sources committed)
13. `docs/getting-started/desktop.md` — operator setup, unsigned-binary disclaimer, SHA-256 verification steps, bundle-size disclosure
14. `prompts/BUILDER-EXECUTION-PLAN.md` — add "desktop UI surface" rule: any `desktop/**` change requires both `cd desktop && npm run build` AND `cd desktop && npm test` in the per-wave gate

## Acceptance criteria

1. `cd desktop && npm install && npm run dev` launches the host, renders the HXI, tray icon visible.
2. Single-instance lock works: second `npm run dev` instance forwards activation and exits 0.
3. `probos://chat/test` opens the running instance and navigates the renderer to the chat route. Sanitization tests REJECT `probos://../etc/passwd`, `probos://chat/..%2f`, `probos://chat/` + 257-char payload, and `probos://attacker.com/chat`.
4. A test notification posted from the runtime fires a native OS notification; click navigates the renderer to the expected route.
5. With the runtime stopped, the host shows the disconnected-state repair surface with Retry + Open Browser HXI actions; clicking Retry re-checks the runtime; clicking Open Browser HXI opens the default browser to `http://127.0.0.1:8765`.
6. Existing web HXI continues to work unchanged (no regressions in browser mode).
7. License audit: every direct dep in `desktop/package.json` is MIT or Apache 2.0. No GPL/AGPL/LGPL/proprietary. Builder runs `npx license-checker --summary` (or equivalent) and includes the output in the commit message.
8. `cd desktop && npm test` passes (see Test expectations).
9. `cd desktop && npm run build` produces a working `dist/` directory loadable by `electron .` from that directory. **No installer artifact** — that ships in AD-759b.
10. Verify all changes comply with `.github/copilot-instructions.md` engineering principles.

## Test expectations

Tests live in `desktop/src/**/*.test.ts` and run via vitest (MIT, already in the `ui/` toolchain — same framework choice keeps the project's test surface consistent):

1. **Single-instance** unit test: `single-instance.ts` exposes a pure function that takes the second-launch argv and returns the activation payload (or `null` for invalid input). Test the pure function; Electron's `requestSingleInstanceLock()` is mocked.
2. **Deep-link sanitization** unit tests (each rule): 5+ test cases covering allowlist accept, path traversal reject, non-empty host reject, length reject, null-byte reject.
3. **Tray menu** unit test: menu construction emits the expected items in the expected order with the expected click handler identifiers. Tests the menu builder as a pure function; `Tray` and `Menu` are mocked.
4. **Disconnected-state** unit test: renderer state machine transitions correctly when the runtime fetch fails (mocked `fetch`).
5. **No E2E in v1.** Smoke verification ("install → launch → tray visible → open chat → quit") is operator-manual per `docs/getting-started/desktop.md` and is deferred to AD-759e's CI matrix. Playwright-electron is the recommended framework when AD-759e is built.

## What this does NOT change

- `ui/` (the browser HXI) — desktop host wraps it but does not modify it.
- `src/probos/experience/desktop/` (Python-side AD-751 primitives) — unchanged.
- Existing API auth, session handling, or HXI routes.
- Existing test count for `tests/` (Python test suite). All new tests live in `desktop/`.

## Tracking

- `PROGRESS.md` — add AD-759 (SHIPPED Wave 186) and forward markers AD-759a..e.
- `docs/development/roadmap.md` — append row for AD-759 in the Yeo table + forward-marker rows.
- `DECISIONS.md` — append concrete entry: AD-759 ships Electron host (MIT deps only, unsigned OSS, signed = commercial overlay AD-759d, auto-update deferred to AD-759c, installer deferred to AD-759b).

## Verified against codebase (2026-05-21)

```
grep -n "bind_host\|bind_port" src/probos/config.py
  1012:    bind_host: str = "127.0.0.1"
  1013:    bind_port: int = Field(default=8765, ge=1, le=65535)

grep -n "^class " src/probos/experience/desktop/tray.py
  14: class TrayManager:

grep -n "^class " src/probos/experience/desktop/lifecycle.py
  17: class DesktopLifecycle:

grep -n "^class " src/probos/experience/desktop/notifications.py
  14: class NotificationCenter:

ls desktop/
  (does not exist — no collision)

ls ui/
  dist/  node_modules/  public/  src/   (vite-based; App.tsx present)

grep -rn "probos://" src/ ui/src/
  (no hits — scheme is free for AD-759 to claim)

grep -n "AD-758\|AD-759" docs/development/roadmap.md
  335:| AD-758 | ... — SHIPPED Wave 181 |
  (no AD-759 row yet)
```
