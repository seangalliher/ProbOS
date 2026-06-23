/**
 * AD-841f: inline Connection-diagnostics panel HTML.
 *
 * Rendered by the Electron main process when the captain picks
 * "Connection diagnostics…" from the tray. Same inline-HTML strategy as
 * `disconnectedHtml()` / `setupHtml()` — no separate renderer artifact.
 *
 * Shows the resolved runtime URL (AD-817) + the live connection status
 * (AD-759 state machine) and offers a Retry affordance that REUSES the
 * existing `window.probos.retryConnect()` bridge (probos:retryConnect IPC).
 * Pure — no Electron import — so it is unit-testable.
 */

import type { ConnectionStatus } from "./trayMenu.js";

export interface DiagnosticsHtmlOptions {
  runtimeUrl: string;
  status: ConnectionStatus;
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "Connected",
  connecting: "Connecting…",
  disconnected: "Disconnected",
};

export function diagnosticsHtml({ runtimeUrl, status }: DiagnosticsHtmlOptions): string {
  // Escape the URL for the JS string context (mirrors setupHtml); the
  // displayed URL is interpolated raw into <code> (mirrors disconnectedHtml,
  // runtimeUrl is validated upstream by isValidRuntimeUrl).
  const safeUrl = JSON.stringify(runtimeUrl);
  const statusText = STATUS_LABEL[status];
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>ProbOS — Connection diagnostics</title>
<style>
  body { background: #0a0a14; color: #e8e8f0; font-family: system-ui, sans-serif;
         display: flex; align-items: center; justify-content: center;
         height: 100vh; margin: 0; }
  .card { max-width: 480px; padding: 32px; border: 1px solid #2a2a3a;
          border-radius: 12px; background: #14141e; }
  h1 { font-size: 18px; margin: 0 0 16px; color: #f0b060; }
  dl { margin: 0; }
  dt { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
       color: #888; margin-top: 12px; }
  dd { margin: 4px 0 0; font-size: 13px; color: #c0c0c8; }
  code { background: #0a0a14; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
  .status-connected { color: #80c080; }
  .status-connecting { color: #f0b060; }
  .status-disconnected { color: #d08080; }
  .row { display: flex; gap: 12px; margin-top: 24px; }
  button { background: #1f1f2e; color: #e8e8f0; border: 1px solid #3a3a50;
           padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  button:hover { background: #2a2a3e; }
  button.primary { border-color: #f0b060; color: #f0b060; }
</style>
</head>
<body>
  <div class="card">
    <h1>Connection diagnostics</h1>
    <dl>
      <dt>Runtime URL</dt>
      <dd><code>${runtimeUrl}</code></dd>
      <dt>Status</dt>
      <dd class="status-${status}">${statusText}</dd>
    </dl>
    <div class="row">
      <button class="primary" id="retry">Retry connection</button>
      <button id="openBrowser">Open in browser</button>
    </div>
  </div>
  <script>
    document.getElementById('retry').addEventListener('click', () => {
      window.probos?.retryConnect();
    });
    document.getElementById('openBrowser').addEventListener('click', () => {
      window.probos?.openExternal(${safeUrl});
    });
  </script>
</body>
</html>`;
}
