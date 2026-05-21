/**
 * AD-759 main process entry.
 *
 * Boot order (per build prompt):
 *   1. Single-instance lock (forward `probos://` argv on second-launch).
 *   2. Register `probos://` as default protocol client.
 *   3. Create tray icon + menu.
 *   4. Create main window pointed at `PROBOS_RUNTIME_URL` env var
 *      (default `http://127.0.0.1:8765`; BF-324 widened CSP so any
 *      127.0.0.1:* port works without rebuilding).
 *   5. On `did-fail-load`, render the disconnected-state HTML.
 *   6. Listen for `second-instance` and route any new deep-link.
 *
 * The Electron host assumes the ProbOS runtime is already running via the
 * AD-751 lifecycle primitives — it does NOT spawn Python.
 */

import {
  app,
  BrowserWindow,
  Menu,
  MenuItemConstructorOptions,
  Tray,
  nativeImage,
  shell,
  ipcMain,
} from "electron";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { parseDeepLink } from "./deepLink.js";
import {
  acquireSingleInstanceLock,
  decideSecondInstanceAction,
} from "./singleInstance.js";
import { buildTrayMenu, ConnectionStatus, type ViewMode } from "./trayMenu.js";
import {
  createConnectionStateMachine,
  type ConnectionStateMachine,
} from "./connectionStateMachine.js";
import { notify } from "./notifications.js";
import { logInfo, logWarn } from "./logger.js";

const RUNTIME_URL = process.env.PROBOS_RUNTIME_URL ?? "http://127.0.0.1:8765";

// Window size presets per view mode. Compact ≈ Microsoft Copilot / Claude Chat
// dimensions (narrow, tall, single-column). Full = the legacy HXI canvas.
const WINDOW_SIZE: Record<ViewMode, { width: number; height: number }> = {
  compact: { width: 480, height: 760 },
  full: { width: 1200, height: 800 },
};

function prefsPath(): string {
  return join(app.getPath("userData"), "desktop-prefs.json");
}

function readViewMode(): ViewMode {
  // Env var wins (useful for E2E / packaging overrides); otherwise the
  // persisted user choice; otherwise default to compact (chat-first).
  const envMode = process.env.PROBOS_DESKTOP_MODE;
  if (envMode === "compact" || envMode === "full") return envMode;
  try {
    const raw = readFileSync(prefsPath(), "utf-8");
    const parsed = JSON.parse(raw) as { viewMode?: string };
    if (parsed.viewMode === "full") return "full";
    if (parsed.viewMode === "compact") return "compact";
  } catch {
    /* missing or malformed prefs file — fall through */
  }
  return "compact";
}

function writeViewMode(mode: ViewMode): void {
  try {
    writeFileSync(prefsPath(), JSON.stringify({ viewMode: mode }), "utf-8");
  } catch (err) {
    logWarn("failed to persist viewMode preference", { err: String(err) });
  }
}

function urlForViewMode(mode: ViewMode, route = "/"): string {
  // Hash routing keeps the FastAPI SPA mount intact — the runtime serves the
  // same `index.html` on every path; the renderer reads `location.hash` to
  // switch between full HXI and the chat-only Yeo surface.
  const hash = mode === "compact" ? "#compact" : "";
  return `${RUNTIME_URL}${route}${hash}`;
}

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let proactivePaused = false;
let viewMode: ViewMode = "compact";
const connection: ConnectionStateMachine = createConnectionStateMachine("connecting");

function disconnectedHtml(): string {
  // In-line HTML (no separate renderer process). Buttons emit IPC via the
  // preload's exposed `window.probos` bridge.
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>ProbOS — Runtime unreachable</title>
<style>
  body { background: #0a0a14; color: #e8e8f0; font-family: system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center;
         height: 100vh; margin: 0; }
  .card { max-width: 480px; padding: 32px; border: 1px solid #2a2a3a;
          border-radius: 12px; background: #14141e; }
  h1 { font-size: 18px; margin: 0 0 12px; color: #f0b060; }
  p { line-height: 1.5; color: #aaaab8; }
  .row { display: flex; gap: 12px; margin-top: 24px; }
  button { background: #1f1f2e; color: #e8e8f0; border: 1px solid #3a3a50;
           padding: 8px 16px; border-radius: 6px; cursor: pointer;
           font-size: 13px; }
  button:hover { background: #2a2a3e; }
  button.primary { border-color: #f0b060; color: #f0b060; }
</style>
</head>
<body>
  <div class="card">
    <h1>ProbOS runtime unreachable</h1>
    <p>The desktop host could not reach the runtime at <code>${RUNTIME_URL}</code>.
       Make sure the ProbOS service is running.</p>
    <div class="row">
      <button class="primary" id="retry">Retry</button>
      <button id="openBrowser">Open in browser</button>
      <button id="quit">Quit</button>
    </div>
  </div>
  <script>
    document.getElementById('retry').addEventListener('click', () => {
      window.probos?.retryConnect();
    });
    document.getElementById('openBrowser').addEventListener('click', () => {
      window.probos?.openExternal('${RUNTIME_URL}');
    });
    document.getElementById('quit').addEventListener('click', () => {
      window.probos?.quit();
    });
  </script>
</body>
</html>`;
}

function showAndRoute(route: string): void {
  if (!mainWindow) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
  // Route by appending the path; if the renderer is currently on the
  // disconnected fallback this will trigger a fresh runtime load.
  const target = urlForViewMode(viewMode, route);
  mainWindow.loadURL(target).catch((err: unknown) => {
    logWarn("route load failed; renderer may show disconnected state", {
      target,
      err: String(err),
    });
  });
}

function applyViewMode(mode: ViewMode): void {
  viewMode = mode;
  writeViewMode(mode);
  if (mainWindow) {
    const { width, height } = WINDOW_SIZE[mode];
    mainWindow.setSize(width, height);
    mainWindow.loadURL(urlForViewMode(mode)).catch((err: unknown) => {
      logWarn("view-mode reload failed", { mode, err: String(err) });
    });
  }
  refreshTrayMenu();
}

function refreshTrayMenu(): void {
  if (!tray) return;
  const items = buildTrayMenu({
    status: connection.state,
    proactivePaused,
    viewMode,
    onOpenRoute: (route) => showAndRoute(route),
    onToggleProactive: () => {
      proactivePaused = !proactivePaused;
      logInfo("proactive mode toggled (local only in v1)", {
        paused: proactivePaused,
      });
      refreshTrayMenu();
    },
    onToggleViewMode: () => {
      const next: ViewMode = viewMode === "compact" ? "full" : "compact";
      logInfo("view-mode toggled", { from: viewMode, to: next });
      applyViewMode(next);
    },
    onCheckForUpdates: () => {
      logInfo("check-for-updates clicked; no-op in v1 (AD-759c)");
    },
    onQuit: () => app.quit(),
  });
  const template: MenuItemConstructorOptions[] = items.map((i) => ({
    label: i.label,
    enabled: i.enabled,
    type: i.type,
    toolTip: i.toolTip,
    click: i.click,
  }));
  tray.setContextMenu(Menu.buildFromTemplate(template));
  tray.setToolTip(`ProbOS (${connection.state})`);
}

function createMainWindow(): void {
  const preloadPath = app.isPackaged
    ? join(__dirname, "../preload/index.js")
    : join(fileURLToPath(new URL("../preload/index.js", import.meta.url)));

  const { width, height } = WINDOW_SIZE[viewMode];
  mainWindow = new BrowserWindow({
    width,
    height,
    show: true,
    backgroundColor: "#0a0a14",
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      preload: preloadPath,
    },
  });

  mainWindow.webContents.on("did-start-loading", () => {
    connection.send({ type: "load-start" });
    refreshTrayMenu();
  });

  mainWindow.webContents.on("did-finish-load", () => {
    const wasDisconnected = connection.state === "disconnected";
    connection.send({ type: "load-success" });
    refreshTrayMenu();
    if (wasDisconnected) {
      notify(
        { title: "ProbOS", body: "Runtime reconnected." },
        { showAndRoute },
      );
    }
  });

  mainWindow.webContents.on(
    "did-fail-load",
    (_e, errorCode, description) => {
      logWarn("renderer failed to load runtime URL", {
        errorCode,
        description,
      });
      connection.send({ type: "load-failure", errorCode, description });
      refreshTrayMenu();
      mainWindow?.loadURL(
        "data:text/html;charset=utf-8," + encodeURIComponent(disconnectedHtml()),
      );
    },
  );

  mainWindow.loadURL(urlForViewMode(viewMode));
}

function handleDeepLinkArg(raw: string): void {
  const parsed = parseDeepLink(raw);
  if (!parsed.ok) {
    logWarn("deep-link rejected; no-op", { raw, reason: parsed.reason });
    return;
  }
  logInfo("deep-link accepted; routing", { route: parsed.route });
  showAndRoute(parsed.route);
}

function bootstrap(): void {
  if (!acquireSingleInstanceLock(app)) {
    // Second instance — Electron has already forwarded argv to the primary
    // via the OS; we just exit.
    return;
  }

  if (process.defaultApp) {
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient("probos", process.execPath, [
        process.argv[1],
      ]);
    }
  } else {
    app.setAsDefaultProtocolClient("probos");
  }

  app.on("second-instance", (_event, argv) => {
    const action = decideSecondInstanceAction(argv);
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
    if (action.forwardedDeepLink) {
      handleDeepLinkArg(action.forwardedDeepLink);
    }
  });

  // macOS deep-link delivery path (no-op on Windows; harmless to register).
  app.on("open-url", (event, url) => {
    event.preventDefault();
    handleDeepLinkArg(url);
  });

  app.whenReady().then(() => {
    viewMode = readViewMode();
    // Tray icon: empty native image is acceptable on Windows for now;
    // real icon assets are AD-759b deliverable.
    const trayIcon = nativeImage.createEmpty();
    tray = new Tray(trayIcon);
    refreshTrayMenu();

    createMainWindow();

    // Preload-driven IPC handlers.
    ipcMain.handle("probos:getRuntimeStatus", () => connection.state);
    ipcMain.handle("probos:retryConnect", () => {
      connection.send({ type: "manual-retry" });
      refreshTrayMenu();
      mainWindow?.loadURL(urlForViewMode(viewMode));
    });
    ipcMain.handle("probos:openExternal", (_e, url: string) => {
      if (typeof url === "string" && url.startsWith(RUNTIME_URL)) {
        shell.openExternal(url);
      } else {
        logWarn("openExternal rejected; URL outside runtime origin", { url });
      }
    });
    ipcMain.handle("probos:quit", () => app.quit());
    ipcMain.handle("probos:getViewMode", () => viewMode);
    ipcMain.handle("probos:setViewMode", (_e, mode: unknown) => {
      if (mode !== "compact" && mode !== "full") {
        logWarn("setViewMode rejected; invalid value", { mode });
        return viewMode;
      }
      applyViewMode(mode);
      return viewMode;
    });

    // Subscribe renderer to status changes (handled by preload's event channel).
    connection.subscribe((s: ConnectionStatus) => {
      mainWindow?.webContents.send("probos:statusChanged", s);
    });

    // Any deep-link in initial argv (cold-start launch from URL).
    for (const arg of process.argv.slice(1)) {
      if (arg.toLowerCase().startsWith("probos://")) {
        handleDeepLinkArg(arg);
      }
    }

    logInfo("tray initialized", { status: connection.state });
  });

  app.on("window-all-closed", () => {
    // Keep running in tray on Windows; only quit on explicit menu Quit.
    if (process.platform === "darwin") {
      app.quit();
    }
  });
}

bootstrap();
