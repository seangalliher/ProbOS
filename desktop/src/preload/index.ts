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
   * the data: URL CORS restriction in the AD-790 first-run wizard. */
  checkRuntime(): Promise<{ ok: boolean; status?: number; error?: string }>;
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
  onStatusChange: (cb: (s: RuntimeStatus) => void) => {
    const listener = (_e: unknown, s: RuntimeStatus): void => cb(s);
    ipcRenderer.on("probos:statusChanged", listener);
    return () => {
      ipcRenderer.removeListener("probos:statusChanged", listener);
    };
  },
};

contextBridge.exposeInMainWorld("probos", api);
