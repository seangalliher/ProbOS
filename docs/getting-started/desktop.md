# ProbOS Desktop (Yeo) — Getting Started

> **AD-759 v1** — Electron tray host wrapping the existing browser HXI.
> Installer + signed binaries + auto-update + CI release pipeline are
> deferred to follow-on ADs (see "What's deferred" below).

## What this is

`desktop/` is an Electron-based native tray host that wraps the existing
ProbOS HXI (browser UI at `http://127.0.0.1:8765`). It provides:

- A system-tray icon with menu (Open chat, Daily briefing, Quick capture,
  Pause/Resume proactive mode, Settings, Quit).
- Single-instance lock (a second launch forwards the activation and exits).
- `probos://` deep-link scheme (e.g. `probos://briefing?date=today`) with
  strict input sanitization.
- Native OS notifications with click-through routing.
- A disconnected-state repair surface when the runtime is unreachable.

The desktop host does **not** spawn the Python runtime. It assumes the
runtime is already running (via the AD-751 desktop-runtime primitives or
`probos serve`).

## Disclaimers (please read)

### Bundle size

Electron adds approximately **~80 MB to the installer** and **~150 MB
installed**. The HXI bundle itself is ~3.3 MB. If installed footprint is a
concern, continue using the browser HXI at `http://127.0.0.1:8765`.

### Unsigned binaries (when AD-759b ships)

The OSS ships **unsigned** Windows binaries. On first launch you will see
the Windows SmartScreen warning ("Windows protected your PC").

To run anyway:

1. Click **More info**.
2. Click **Run anyway**.

To verify a downloaded binary against the SHA-256 published with the
GitHub Release:

```pwsh
Get-FileHash -Algorithm SHA256 .\ProbOS-Desktop-Setup.exe
```

Compare the result to the `SHA256SUMS` file on the release page.

Signed Windows binaries (requires an EV code-signing certificate, ~$300/yr)
and Apple Developer ID notarization for macOS are deferred to AD-759d.
The OSS will remain unsigned; signed binaries are a commercial-overlay
deliverable.

## Run from source

Prerequisites: Node.js 20+, npm.

```pwsh
cd desktop
npm install
npm run dev
```

This will launch the Electron host pointed at `http://127.0.0.1:8765`.
Set `PROBOS_RUNTIME_URL` to override the runtime URL for non-default
deployments. For example, if your runtime binds to port `18900`:

```pwsh
$env:PROBOS_RUNTIME_URL = "http://127.0.0.1:18900"
npm run dev
```

The renderer's Content-Security-Policy allows any `http://127.0.0.1:*`
origin (BF-324), so no rebuild is required when changing the runtime
port.

Run the unit tests:

```pwsh
cd desktop
npx vitest run
```

Build a packaged renderer (no installer in v1):

```pwsh
cd desktop
npm run build
```

## Packaged binaries

Pre-built installers are **deferred to AD-759b**. Until then, run the
desktop host from source via `npm run dev`.

## What's deferred

| Forward marker | Scope |
|----------------|-------|
| AD-759a | Launch-at-login (Windows registry / macOS LaunchAgent / Linux .desktop) |
| AD-759b | NSIS installer + unsigned Windows release artifact |
| AD-759c | Auto-update (check-only against GitHub Releases) |
| AD-759d | Signed installer + EV code-signing workflow (commercial overlay) |
| AD-759e | CI release pipeline (GH Actions Win/macOS/Linux matrix) |
| AD-759-1 | macOS menubar parity |
| AD-759-2 | Linux tray parity |

## Security posture

- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`.
- Renderer talks to the main process via a minimal preload bridge
  (`window.probos`); no `ipcRenderer` is exposed directly.
- Deep-link payloads are validated against an allowlist before any
  route navigation (no shell metacharacters, no path traversal, no
  control chars, length ≤ 2048).
- No credentials are stored by the desktop host. Authentication is
  handled by the existing runtime keystore via authenticated HTTP.
