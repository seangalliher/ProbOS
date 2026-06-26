/**
 * AD-1054: OS-activity sensor — a default-OFF, consent-gated, local-only
 * foreground-window watcher for the ProbOS desktop host (AD-759).
 *
 * PRIVACY (load-bearing):
 *   - Default OFF: the watcher self-gates on the runtime consent flag
 *     (GET /api/os-activity); it does NOT call activeWindow() when consent
 *     is off, so the sensor does not even run without consent. The runtime
 *     POST endpoint independently refuses when off (defense in depth).
 *   - Active-window METADATA ONLY (app name + title + optional app path/url).
 *     NEVER keystrokes, screen content, or clipboard.
 *   - Local-only: the payload POSTs to the local runtime; nothing leaves the
 *     host from this module.
 *   - Change-detection: a sample is POSTed only when the active window
 *     CHANGES (heartbeat + diff), not as a continuous stream.
 *
 * The `get-windows` import is LAZY (inside the poll) and the active-window
 * source is injectable, so this module loads under Vitest (and with the lib
 * absent) without pulling the native/FFI helper — mirroring the AD-708e
 * lazy-zeroconf pattern.
 */

import { logInfo, logWarn } from "./logger.js";

/** Subset of the `get-windows` Result we consume (metadata only). */
export interface ActiveWindowResult {
  title?: string;
  owner?: { name?: string; path?: string };
  url?: string;
}

/** The wire payload POSTed to the runtime ingestion endpoint. */
export interface OSActivityPayload {
  active_app: string;
  window_title: string;
  app_path?: string;
  url?: string;
  ts: number;
}

export interface OSActivityConsent {
  enabled: boolean;
  poll_interval_seconds: number;
}

export interface OSActivityWatcherDeps {
  getRuntimeUrl: () => string;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
  /**
   * Injectable active-window source; defaults to a lazy `get-windows` import.
   * Returns undefined when no window is focused / the platform is unsupported.
   */
  activeWindowImpl?: () => Promise<ActiveWindowResult | undefined>;
  /** Fixed fallback cadence (ms) used until the runtime reports its interval. */
  intervalMs?: number;
}

/** Pure: map a `get-windows` Result → the wire payload (or null on bad shape). */
export function mapActiveWindowToPayload(
  result: ActiveWindowResult | undefined,
  now: number = Date.now(),
): OSActivityPayload | null {
  if (!result || !result.owner || !result.owner.name) {
    // Honest-degrade: no focused window / unsupported platform → nothing to report.
    return null;
  }
  const payload: OSActivityPayload = {
    active_app: result.owner.name,
    window_title: typeof result.title === "string" ? result.title : "",
    ts: now / 1000,
  };
  if (result.owner.path) payload.app_path = result.owner.path;
  if (result.url) payload.url = result.url;
  return payload;
}

/** Pure: emit only when the active window changed (app or title). */
export function shouldEmit(
  prev: OSActivityPayload | null,
  next: OSActivityPayload,
): boolean {
  if (prev === null) return true;
  return prev.active_app !== next.active_app ||
    prev.window_title !== next.window_title;
}

/** Lazy default active-window source — never imported at module top. */
async function defaultActiveWindow(): Promise<ActiveWindowResult | undefined> {
  // Dynamic import so Vitest / a lib-absent host never loads the native helper,
  // and so the ESM-only `get-windows` works regardless of this bundle's format.
  const mod = await import("get-windows");
  return (await mod.activeWindow()) as ActiveWindowResult | undefined;
}

/**
 * Start the heartbeat watcher. Returns a stop() handle (clears the timer).
 * The loop ALWAYS re-reads consent first, so toggling consent on later starts
 * capture without a restart, and toggling off stops it.
 */
export function startOsActivityWatcher(deps: OSActivityWatcherDeps): () => void {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const activeWindowImpl = deps.activeWindowImpl ?? defaultActiveWindow;
  const fallbackMs = deps.intervalMs ?? 5000;

  let prev: OSActivityPayload | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  async function readConsent(): Promise<OSActivityConsent> {
    try {
      const r = await fetchImpl(deps.getRuntimeUrl() + "/api/os-activity", {
        method: "GET",
      });
      if (!r.ok) return { enabled: false, poll_interval_seconds: 5 };
      const j = (await r.json()) as Partial<OSActivityConsent>;
      return {
        enabled: Boolean(j.enabled),
        poll_interval_seconds:
          typeof j.poll_interval_seconds === "number" && j.poll_interval_seconds > 0
            ? j.poll_interval_seconds
            : 5,
      };
    } catch {
      // Honest-degrade: runtime unreachable → treat as disabled, retry next tick.
      return { enabled: false, poll_interval_seconds: 5 };
    }
  }

  async function tick(): Promise<void> {
    if (stopped) return;
    const consent = await readConsent();
    let nextDelayMs = fallbackMs;
    if (consent.enabled) {
      nextDelayMs = consent.poll_interval_seconds * 1000;
      try {
        // Capture ONLY when consent is on — the sensor does not run when off.
        const result = await activeWindowImpl();
        const payload = mapActiveWindowToPayload(result);
        if (payload && shouldEmit(prev, payload)) {
          prev = payload;
          try {
            await fetchImpl(deps.getRuntimeUrl() + "/api/os-activity", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify(payload),
            });
          } catch {
            // Honest-degrade: a failed POST drops one sample; no throw.
          }
        }
      } catch (err) {
        // Honest-degrade: activeWindow undefined / Wayland / permission denied.
        logWarn("AD-1054: active-window probe failed; skipping sample", {
          err: String(err),
        });
      }
    } else {
      prev = null; // forget last state while disabled
    }
    if (!stopped) timer = setTimeout(() => void tick(), nextDelayMs);
  }

  logInfo("AD-1054: OS-activity watcher armed (self-gates on runtime consent)");
  timer = setTimeout(() => void tick(), 0);

  return function stop(): void {
    stopped = true;
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
  };
}
