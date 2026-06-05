/**
 * AD-759 preload bridge.
 *
 * Exposes a minimal, typed `window.probos` API to the renderer. No
 * `ipcRenderer` is exposed directly. No Node APIs are forwarded.
 */

import { contextBridge, ipcRenderer } from "electron";

export type RuntimeStatus = "connected" | "connecting" | "disconnected";
export type ViewMode = "compact" | "full";

interface ProbosApi {
  getRuntimeStatus(): Promise<RuntimeStatus>;
  retryConnect(): Promise<void>;
  openExternal(url: string): Promise<void>;
  quit(): Promise<void>;
  getViewMode(): Promise<ViewMode>;
  setViewMode(mode: ViewMode): Promise<ViewMode>;
  /** BF (2026-05-22): probe runtime via main process to bypass
   * the data: URL CORS restriction in the AD-790 first-run wizard.
   * AD-817: response is extended with configuredUrl and an optional
   * mismatch payload when a different port is responding. */
  checkRuntime(): Promise<{
    ok: boolean;
    status?: number;
    error?: string;
    configuredUrl?: string;
    mismatch?: { configured: string; responding: string };
  }>;
  /** AD-817: read the current resolved runtime URL. */
  getRuntimeUrl(): Promise<string>;
  /** AD-817: persist a new runtime URL. Returns ok=false on validation failure. */
  setRuntimeUrl(value: string): Promise<{
    ok: boolean;
    runtimeUrl: string;
    error?: string;
  }>;
  /** AD-790: complete the first-run wizard and reload onto the HXI. */
  completeSetup(payload: {
    captainName: string;
    suggestedPrompt: string | null;
    setupVersion: number;
  }): Promise<{ ok: boolean }>;
  /** AD-759: reset first-run state so the wizard renders again next launch. */
  resetSetup(): Promise<{ ok: boolean }>;
  /** AD-790: read the persisted first-run state (debug + tests). */
  getFirstRunState(): Promise<unknown>;
  /** AD-847: surface a native desktop notification for a completed task.
   * When `route` is provided, clicking the notification activates the
   * window and routes there (e.g. Yeo's 1:1 chat). Fire-and-forget. */
  notifyTaskDone(payload: {
    title: string;
    body: string;
    route?: string;
  }): Promise<{ ok: boolean }>;
  onStatusChange(cb: (s: RuntimeStatus) => void): () => void;
}

const api: ProbosApi = {
  getRuntimeStatus: () => ipcRenderer.invoke("probos:getRuntimeStatus"),
  retryConnect: () => ipcRenderer.invoke("probos:retryConnect"),
  openExternal: (url: string) => ipcRenderer.invoke("probos:openExternal", url),
  quit: () => ipcRenderer.invoke("probos:quit"),
  getViewMode: () => ipcRenderer.invoke("probos:getViewMode"),
  setViewMode: (mode: ViewMode) =>
    ipcRenderer.invoke("probos:setViewMode", mode),
  checkRuntime: () => ipcRenderer.invoke("probos:checkRuntime"),
  getRuntimeUrl: () => ipcRenderer.invoke("probos:getRuntimeUrl"),
  setRuntimeUrl: (value: string) =>
    ipcRenderer.invoke("probos:setRuntimeUrl", value),
  completeSetup: (payload) =>
    ipcRenderer.invoke("probos:completeSetup", payload),
  resetSetup: () => ipcRenderer.invoke("probos:resetSetup"),
  getFirstRunState: () => ipcRenderer.invoke("probos:getFirstRunState"),
  notifyTaskDone: (payload) =>
    ipcRenderer.invoke("probos:notifyTaskDone", payload),
  onStatusChange: (cb: (s: RuntimeStatus) => void) => {
    const listener = (_e: unknown, s: RuntimeStatus): void => cb(s);
    ipcRenderer.on("probos:statusChanged", listener);
    return () => {
      ipcRenderer.removeListener("probos:statusChanged", listener);
    };
  },
};

contextBridge.exposeInMainWorld("probos", api);
