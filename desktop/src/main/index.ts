/**
 * AD-759 main process entry.
 *
 * Boot order (per build prompt):
 *   1. Single-instance lock (forward `probos://` argv on second-launch).
 *   2. Register `probos://` as default protocol client.
 *   3. Create tray icon + menu.
 *   4. Create main window pointed at the AD-817 resolved runtime URL
 *      (persisted file > `PROBOS_RUNTIME_URL` env > built-in default;
 *      BF-324 widened CSP so any 127.0.0.1:* port works without
 *      rebuilding).
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
import { buildTrayMenu, ConnectionStatus, type TrayMenuItem, type ViewMode, type ViewTarget } from "./trayMenu.js";
import {
  createConnectionStateMachine,
  type ConnectionStateMachine,
} from "./connectionStateMachine.js";
import { notify, coerceTaskDonePayload } from "./notifications.js";
import { logInfo, logWarn } from "./logger.js";
import {
  completeFirstRun,
  isFirstRun,
  loadState,
  resetFirstRun,
} from "./firstRun.js";
import { setupHtml } from "./setupHtml.js";
import { diagnosticsHtml } from "./diagnosticsHtml.js";
import {
  DEFAULT_RUNTIME_URL,
  PORT_CANDIDATES,
  isValidRuntimeUrl,
  normaliseRuntimeUrl,
  resolveRuntimeUrl,
  saveRuntimeConfig,
} from "./runtimeConfig.js";

/**
 * AD-817: runtime URL is now operator-configurable via the wizard and
 * the tray menu. The value resolves at app startup (resolveRuntimeUrl)
 * and is mutated in-place by the `probos:setRuntimeUrl` IPC handler so
 * downstream readers (urlForViewMode, disconnectedHtml, setupHtml,
 * checkRuntime, openExternal gate) always see the current value.
 */
let runtimeUrl = DEFAULT_RUNTIME_URL;

function getRuntimeUrl(): string {
  return runtimeUrl;
}

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
  return `${getRuntimeUrl()}${route}${hash}`;
}

/**
 * AD-841d: FULL-mode deep link to a management surface. The AD-841c reader
 * (`ui/src/deepLinkView.ts`) maps `#view=<id>` to a surface that exists ONLY in
 * `<App>` (not `<CompactApp>`) — so we MUST NOT append `#compact`. The
 * `#view=<id>` hash IS the entire hash.
 */
function urlForManagementView(id: ViewTarget): string {
  return `${getRuntimeUrl()}/#view=${id}`;
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
    <p>The desktop host could not reach the runtime at <code>${getRuntimeUrl()}</code>.
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
      window.probos?.openExternal('${getRuntimeUrl()}');
    });
    document.getElementById('quit').addEventListener('click', () => {
      window.probos?.quit();
    });
  </script>
</body>
</html>`;
}

function showAndRoute(route: string): void {
  // BF (2026-05-22): if the captain closed the only window, mainWindow
  // points at a destroyed BrowserWindow. Recreate it so tray clicks +
  // deep links still work after the window has been closed.
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    if (!mainWindow) {
      logWarn("createMainWindow did not produce a window; route ignored", { route });
      return;
    }
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

/**
 * AD-841d: show the main window (recreating it if the captain closed it —
 * mirrors showAndRoute's guard) and load a management deep link in FULL mode.
 * The pure tray builder calls `onOpenView(id)`; the Electron side effect is here.
 */
function showManagementView(id: ViewTarget): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    if (!mainWindow) {
      logWarn("createMainWindow did not produce a window; view ignored", { id });
      return;
    }
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  const target = urlForManagementView(id);
  mainWindow.loadURL(target).catch((err: unknown) => {
    logWarn("management deep-link load failed", { target, err: String(err) });
  });
}

/**
 * AD-841f: show the main window (recreating it if the captain closed it —
 * mirrors showManagementView's guard) and load the Connection diagnostics
 * panel (runtime URL + live connection status + a Retry button that reuses
 * the existing probos:retryConnect IPC via window.probos.retryConnect()).
 * The pure tray builder calls `onShowDiagnostics()`; the side effect is here.
 */
function showConnectionDiagnostics(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    if (!mainWindow) {
      logWarn("createMainWindow did not produce a window; diagnostics ignored", {});
      return;
    }
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
  mainWindow
    .loadURL(
      "data:text/html;charset=utf-8," +
        encodeURIComponent(
          diagnosticsHtml({ runtimeUrl: getRuntimeUrl(), status: connection.state }),
        ),
    )
    .catch((err: unknown) => {
      logWarn("diagnostics panel load failed", { err: String(err) });
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

/**
 * AD-841d: map a pure TrayMenuItem to Electron's template, RECURSING into
 * `submenu`. The previous flat map dropped `submenu`, so the AD-815b
 * "Chat with…" and AD-841d "Management" submenus rendered empty.
 */
function trayItemToTemplate(i: TrayMenuItem): MenuItemConstructorOptions {
  return {
    label: i.label,
    enabled: i.enabled,
    type: i.type,
    toolTip: i.toolTip,
    click: i.click,
    submenu: i.submenu?.map(trayItemToTemplate),
  };
}

function refreshTrayMenu(): void {
  if (!tray) return;
  const items = buildTrayMenu({
    status: connection.state,
    proactivePaused,
    viewMode,
    onOpenRoute: (route) => showAndRoute(route),
    onOpenView: (id) => showManagementView(id),
    onShowDiagnostics: () => showConnectionDiagnostics(),
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
    onResetSetup: () => {
      const removed = resetFirstRun(app.getPath("userData"));
      logInfo("Reset Setup clicked (tray)", { removed });
      if (removed && mainWindow) {
        const appVersion = app.getVersion();
        mainWindow.loadURL(
          "data:text/html;charset=utf-8," +
            encodeURIComponent(setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })),
        );
      }
    },
    onQuit: () => app.quit(),
  });
  const template: MenuItemConstructorOptions[] = items.map(trayItemToTemplate);
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

  // BF (2026-05-22): null the module-level reference when the window
  // is destroyed so subsequent tray clicks / deep links recreate it
  // instead of throwing 'Object has been destroyed' inside showAndRoute.
  mainWindow.on("closed", () => {
    mainWindow = null;
    refreshTrayMenu();
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

  // AD-790: first-run wizard takes precedence over the runtime URL.
  // Until completeSetup IPC fires, we render the inline setupHtml. Once
  // first-run state is `complete`, subsequent boots skip straight to
  // the runtime URL.
  if (isFirstRun(app.getPath("userData"))) {
    const appVersion = app.getVersion();
    mainWindow.loadURL(
      "data:text/html;charset=utf-8," +
        encodeURIComponent(setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })),
    );
    logInfo("first-run wizard rendered", { userData: app.getPath("userData") });
  } else {
    mainWindow.loadURL(urlForViewMode(viewMode));
  }
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
    runtimeUrl = resolveRuntimeUrl({ userDataDir: app.getPath("userData") });
    logInfo("runtime URL resolved", { runtimeUrl });
    viewMode = readViewMode();
    // Tray icon: amber bioluminescent dot (matches HXI palette #f0b060).
    // Resolved relative to the built main bundle at out/main/index.js;
    // resources/ sits two levels up. Falls back to an empty image only
    // if the asset is missing so the tray still appears.
    const iconCandidates = [
      // dev: out/main/index.js → ../../resources/tray-icon.png
      join(__dirname, "../../resources/tray-icon.png"),
      // packaged: process.resourcesPath is the asar root
      process.resourcesPath
        ? join(process.resourcesPath, "tray-icon.png")
        : "",
    ].filter(Boolean);
    let trayIcon = nativeImage.createEmpty();
    for (const candidate of iconCandidates) {
      const img = nativeImage.createFromPath(candidate);
      if (!img.isEmpty()) {
        trayIcon = img;
        break;
      }
    }
    if (trayIcon.isEmpty()) {
      logWarn("Tray icon asset not found; tray will render without icon", {
        candidates: iconCandidates,
      });
    }
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
      if (typeof url === "string" && url.startsWith(getRuntimeUrl())) {
        shell.openExternal(url);
      } else {
        logWarn("openExternal rejected; URL outside runtime origin", { url });
      }
    });
    ipcMain.handle("probos:quit", () => app.quit());
    // AD-847: native desktop notification for a completed task. The
    // renderer-supplied payload is untrusted across the context-isolation
    // boundary, so coerce it first; a valid `route` (e.g. Yeo's 1:1 chat)
    // makes the notification click activate the window and route there.
    ipcMain.handle("probos:notifyTaskDone", (_e, payload: unknown) => {
      const coerced = coerceTaskDonePayload(payload);
      if (!coerced) {
        logWarn("notifyTaskDone rejected; invalid payload");
        return { ok: false };
      }
      notify(coerced, { showAndRoute });
      return { ok: true };
    });
    // BF (2026-05-22): renderer fetches from data: URLs are blocked by
    // CORS (null origin). Probe the runtime from the main process where
    // no CORS applies and return the result to the AD-790 wizard.
    ipcMain.handle("probos:checkRuntime", async () => {
      const configured = getRuntimeUrl();
      const probe = async (
        url: string,
      ): Promise<{ ok: boolean; status?: number; error?: string }> => {
        const ac = new AbortController();
        const timer = setTimeout(() => ac.abort(), 3000);
        try {
          const r = await fetch(url + "/api/health", {
            method: "GET",
            signal: ac.signal,
          });
          clearTimeout(timer);
          return { ok: r.ok, status: r.status };
        } catch (err) {
          clearTimeout(timer);
          return { ok: false, error: String(err) };
        }
      };

      const primary = await probe(configured);
      if (primary.ok) {
        return { ok: true, status: primary.status, configuredUrl: configured };
      }

      // Mismatch scan: try other common ports on the configured host to
      // detect a misconfigured-URL scenario. Bounded by PORT_CANDIDATES
      // so we don't turn a health probe into a port scanner.
      let configuredHost = "127.0.0.1";
      let configuredPort = "";
      try {
        const u = new URL(configured);
        configuredHost = u.hostname;
        configuredPort = u.port;
      } catch {
        /* configured was validated earlier; defensive only */
      }

      for (const port of PORT_CANDIDATES) {
        if (String(port) === configuredPort) continue;
        const candidate = `http://${configuredHost}:${port}`;
        const result = await probe(candidate);
        if (result.ok) {
          return {
            ok: false,
            status: primary.status,
            error: primary.error,
            configuredUrl: configured,
            mismatch: { configured, responding: candidate },
          };
        }
      }

      return {
        ok: false,
        status: primary.status,
        error: primary.error,
        configuredUrl: configured,
      };
    });

    ipcMain.handle("probos:getRuntimeUrl", () => getRuntimeUrl());
    ipcMain.handle("probos:setRuntimeUrl", (_e, value: unknown) => {
      if (!isValidRuntimeUrl(value)) {
        logWarn("setRuntimeUrl rejected; invalid URL", { value });
        return { ok: false, runtimeUrl: getRuntimeUrl(), error: "invalid URL" };
      }
      const next = normaliseRuntimeUrl(value);
      try {
        saveRuntimeConfig(app.getPath("userData"), { runtimeUrl: next });
      } catch (err) {
        logWarn("setRuntimeUrl persist failed", { err: String(err) });
        return { ok: false, runtimeUrl: getRuntimeUrl(), error: String(err) };
      }
      runtimeUrl = next;
      logInfo("runtime URL updated", { runtimeUrl: next });
      return { ok: true, runtimeUrl: next };
    });
    ipcMain.handle("probos:getViewMode", () => viewMode);
    ipcMain.handle("probos:setViewMode", (_e, mode: unknown) => {
      if (mode !== "compact" && mode !== "full") {
        logWarn("setViewMode rejected; invalid value", { mode });
        return viewMode;
      }
      applyViewMode(mode);
      return viewMode;
    });

    // AD-790: first-run wizard completion + reset.
    ipcMain.handle("probos:completeSetup", (_e, payload: unknown) => {
      const userData = app.getPath("userData");
      completeFirstRun(userData);
      const detail =
        payload && typeof payload === "object"
          ? (payload as Record<string, unknown>)
          : {};
      logInfo("first-run setup completed", {
        captainName: typeof detail.captainName === "string" ? detail.captainName : "(unset)",
        hasSuggestedPrompt: typeof detail.suggestedPrompt === "string" && detail.suggestedPrompt.length > 0,
      });
      // Reload onto the runtime URL now that setup is done.
      mainWindow?.loadURL(urlForViewMode(viewMode));
      return { ok: true };
    });
    ipcMain.handle("probos:resetSetup", () => {
      const removed = resetFirstRun(app.getPath("userData"));
      logInfo("first-run state reset requested", { removed });
      if (removed) {
        // Reload onto the wizard so the operator sees it immediately.
        const appVersion = app.getVersion();
        mainWindow?.loadURL(
          "data:text/html;charset=utf-8," +
            encodeURIComponent(setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })),
        );
      }
      return { ok: removed };
    });
    ipcMain.handle("probos:getFirstRunState", () => loadState(app.getPath("userData")));

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
