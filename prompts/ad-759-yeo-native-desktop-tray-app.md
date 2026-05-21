# AD-759 - Yeo Native Desktop Tray App (packaged host + updater + single-instance)

Status: drafted (new top-level AD)
Issue: #705
Depends on: AD-751 runtime desktop primitives (already present)
Priority: 2

## Why this AD exists

AD-751 shipped desktop-runtime primitives in the Python runtime, but did not ship a native packaged desktop host. The Captain requirement is explicit: the daily-driver Yeo entry point must run as a real tray app.

This AD closes that gap by delivering a packaged desktop application that hosts the existing HXI and provides reliable OS-level tray behavior.

## Current highest AD number

Verified against `docs/development/roadmap.md` Yeo table: current highest AD is **AD-758**. This prompt assigns **AD-759**.

## Prior-art references (architecture only)

1. openclaw/openclaw-windows-node (MIT)
- Dedicated tray host app as first-class project (not a bolt-on script).
- Single-instance behavior + deep-link forwarding through IPC.
- First-run onboarding sequence with permissions checks.
- Clickable notifications and command-center diagnostics in the tray surface.
- Native packaging + updater channel + startup option.

2. hermes-desktop/hermes-desktop (MIT)
- Electron host with explicit installer artifacts per OS.
- Guided first-run install/configuration and local/remote backend mode.
- Auto-updater integrated into app lifecycle.
- Local persistence + session management inside desktop host.

3. Claude Cowork (product pattern; no code reuse)
- "Set it once" recurring tasks framing.
- "Show plan, require approval before significant actions" interaction model.
- Desktop-first handoff UX and low-friction daily briefing entry.

## Scope (v1)

Build a native packaged desktop host for Yeo tray workflows:

1. Native tray application shell (Windows first; macOS/Linux honest-degrade)
2. Single-instance lock + deep-link activation (`probos://...`) routed to running instance
3. Tray menu sections:
- status
- open chat
- daily briefing
- quick capture
- pause/resume proactive mode
- settings
- check for updates
- quit
4. Native notifications with click-through actions into app routes
5. Launch-at-login support
6. Signed installer pipeline stubs + release artifacts for Windows
7. Auto-update check/install flow with rollback-safe guardrails

## Non-scope (v1)

1. Full cross-platform parity on day one (Windows is the shipping target)
2. Re-implementing Yeo cognition or M365 logic in desktop host
3. New backend product surfaces unrelated to tray app lifecycle
4. Replacing existing browser HXI (host wraps existing UI)

## Proposed architecture

1. Host type
- Electron host app wrapping existing HXI route surfaces.

2. Process model
- Main process: tray icon, notifications, deep links, updater, single-instance lock.
- Renderer process: existing UI routes for chat/briefing/settings.
- IPC bridge: minimal, typed actions only.

3. Runtime binding
- Desktop host talks to local ProbOS runtime over existing authenticated HTTP/WebSocket APIs.
- If runtime unavailable, show repair surface and reconnect flow.

4. Security posture
- No secrets in renderer localStorage.
- Runtime token/key material stored in OS-protected keychain/credential store abstraction.
- Deep links validated and sanitized before routing.

## File targets

1. `desktop/` (new top-level workspace for host app)
2. `desktop/package.json` + build scripts
3. `desktop/src/main/*` (tray/updater/single-instance/deep links)
4. `desktop/src/preload/*` (IPC boundary)
5. `desktop/src/renderer/*` (host shell + route bridge)
6. `desktop/build/*` (packaging config)
7. `docs/getting-started/desktop.md` (operator setup)
8. `prompts/BUILDER-EXECUTION-PLAN.md` (desktop release gate bullets)

## Acceptance criteria

1. A packaged Windows installer artifact is produced in CI and can install/uninstall cleanly.
2. App boots to tray on login when enabled.
3. Single-instance lock works: second launch forwards activation intent to first instance and exits.
4. `probos://` deep links open the running instance and navigate to the expected route.
5. Notification click-through lands in the requested Yeo workflow (chat/briefing/action).
6. Updater check can detect a newer build and prompt/install update safely.
7. Runtime disconnected state is explicit and recoverable from UI.
8. Existing web HXI remains operational (no regressions in browser mode).
9. Verify all changes comply with `.github/copilot-instructions.md` engineering principles.

## Test expectations

1. Desktop main-process tests: single-instance, deep-link parsing, tray action routing, updater flow stubs.
2. Renderer tests: route handoff, disconnected-state UX, notification action navigation.
3. Smoke script: install -> launch -> tray visible -> open chat -> quit.

## Forward markers

1. AD-759-1: macOS menubar parity
2. AD-759-2: Linux tray parity
3. AD-759-3: command palette integration
4. AD-759-4: advanced staged rollout channels
5. AD-759-5: managed policy controls for large deployments
