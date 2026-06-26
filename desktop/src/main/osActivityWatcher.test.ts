/**
 * AD-1054: OS-activity sensor watcher — unit tests (vitest, node env, DI).
 *
 * Pure mapper + change-detector + the self-gating heartbeat. The active-window
 * source and `fetch` are INJECTED (DI), and `get-windows` is mocked so the
 * native helper is NEVER loaded under vitest. The disabled-consent test proves
 * the lazy-import gate: with consent off, the default lazy `import("get-windows")`
 * is never reached (the import spy stays uncalled).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// The watcher's DEFAULT active-window source lazily `import("get-windows")`.
// Mock it (factory fully replaces the module — the real native code is never
// loaded, even if its prebuilt binary is absent) and spy on the import so we
// can assert it is NEVER reached when consent is off.
const { getWindowsImportSpy, activeWindowSpy } = vi.hoisted(() => ({
  getWindowsImportSpy: vi.fn(),
  activeWindowSpy: vi.fn(async () => ({
    owner: { name: "App" },
    title: "t",
  })),
}));
vi.mock("get-windows", () => {
  getWindowsImportSpy();
  return { activeWindow: activeWindowSpy };
});

import {
  mapActiveWindowToPayload,
  shouldEmit,
  startOsActivityWatcher,
  type ActiveWindowResult,
  type OSActivityConsent,
  type OSActivityPayload,
} from "./osActivityWatcher";

/** A fake `fetch`: GET → the consent body; POST → records the payload. */
function makeFetch(
  consent: OSActivityConsent,
  posts: OSActivityPayload[],
): typeof fetch {
  const fn = vi.fn(
    async (_url: unknown, init?: { method?: string; body?: string }) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)) as OSActivityPayload);
        return { ok: true, json: async () => ({ ingested: true }) };
      }
      return { ok: true, json: async () => consent };
    },
  );
  return fn as unknown as typeof fetch;
}

const RT = "http://127.0.0.1:8000";

beforeEach(() => {
  getWindowsImportSpy.mockClear();
  activeWindowSpy.mockClear();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

// --- 1-3. pure mapper -------------------------------------------------------

describe("mapActiveWindowToPayload", () => {
  it("maps a well-formed Result to the full payload", () => {
    const p = mapActiveWindowToPayload(
      {
        title: "events.py - ProbOS",
        owner: { name: "Code", path: "/bin/code" },
        url: "https://github.com/probos",
      },
      10000,
    );

    expect(p).toEqual({
      active_app: "Code",
      window_title: "events.py - ProbOS",
      app_path: "/bin/code",
      url: "https://github.com/probos",
      ts: 10,
    });
  });

  it("maps a minimal Result with no title/path/url", () => {
    const p = mapActiveWindowToPayload({ owner: { name: "App" } }, 5000);

    expect(p).toEqual({ active_app: "App", window_title: "", ts: 5 });
    expect(p).not.toHaveProperty("app_path");
    expect(p).not.toHaveProperty("url");
  });

  it("returns null for a bad/empty shape (honest-degrade)", () => {
    expect(mapActiveWindowToPayload(undefined)).toBeNull();
    expect(mapActiveWindowToPayload({})).toBeNull();
    expect(mapActiveWindowToPayload({ owner: {} })).toBeNull();
  });
});

// --- 4. change-detector -----------------------------------------------------

describe("shouldEmit", () => {
  it("emits on first sample and on app/title change, suppresses identical", () => {
    const a: OSActivityPayload = { active_app: "A", window_title: "1", ts: 0 };

    expect(shouldEmit(null, a)).toBe(true);
    expect(shouldEmit(a, { ...a })).toBe(false);
    expect(shouldEmit(a, { ...a, active_app: "B" })).toBe(true);
    expect(shouldEmit(a, { ...a, window_title: "2" })).toBe(true);
  });
});

// --- 5. consent gate OFF: no probe, no POST --------------------------------

describe("startOsActivityWatcher (consent gate)", () => {
  it("does NOT probe the active window or POST when consent is off", async () => {
    vi.useFakeTimers();
    const posts: OSActivityPayload[] = [];
    const fetchImpl = makeFetch({ enabled: false, poll_interval_seconds: 5 }, posts);
    const activeWindowImpl = vi.fn(
      async (): Promise<ActiveWindowResult> => ({ owner: { name: "App" }, title: "t" }),
    );

    const stop = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl,
      activeWindowImpl,
    });
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();
    stop();

    expect(activeWindowImpl).not.toHaveBeenCalled();
    expect(posts).toEqual([]);
  });

  // --- 6. consent gate ON: probe + POST ------------------------------------

  it("probes and POSTs the mapped payload when consent is on", async () => {
    vi.useFakeTimers();
    const posts: OSActivityPayload[] = [];
    const fetchImpl = makeFetch({ enabled: true, poll_interval_seconds: 1 }, posts);
    const activeWindowImpl = vi.fn(
      async (): Promise<ActiveWindowResult> => ({
        owner: { name: "Code", path: "/bin/code" },
        title: "x.ts",
      }),
    );

    const stop = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl,
      activeWindowImpl,
    });
    await vi.runOnlyPendingTimersAsync();
    stop();

    expect(activeWindowImpl).toHaveBeenCalled();
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({
      active_app: "Code",
      window_title: "x.ts",
      app_path: "/bin/code",
    });
    expect(typeof posts[0].ts).toBe("number");
  });

  // --- 7. change-detection -------------------------------------------------

  it("POSTs only when the active window changes", async () => {
    vi.useFakeTimers();
    const posts: OSActivityPayload[] = [];
    const fetchImpl = makeFetch({ enabled: true, poll_interval_seconds: 1 }, posts);
    let win: ActiveWindowResult = { owner: { name: "App" }, title: "one" };
    const activeWindowImpl = vi.fn(async (): Promise<ActiveWindowResult> => win);

    const stop = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl,
      activeWindowImpl,
    });
    await vi.runOnlyPendingTimersAsync(); // tick 1: prev null -> POST
    await vi.runOnlyPendingTimersAsync(); // tick 2: same window -> suppressed
    expect(posts).toHaveLength(1);

    win = { owner: { name: "App" }, title: "two" }; // title changed
    await vi.runOnlyPendingTimersAsync(); // tick 3: changed -> POST
    stop();

    expect(posts).toHaveLength(2);
    expect(posts[1].window_title).toBe("two");
  });

  // --- 8. honest-degrade ---------------------------------------------------

  it("honest-degrades when the probe throws or returns undefined (no POST, no throw)", async () => {
    vi.useFakeTimers();

    const postsThrow: OSActivityPayload[] = [];
    const throwing = vi.fn(async (): Promise<ActiveWindowResult> => {
      throw new Error("permission denied");
    });
    const stopThrow = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl: makeFetch({ enabled: true, poll_interval_seconds: 1 }, postsThrow),
      activeWindowImpl: throwing,
    });
    await vi.runOnlyPendingTimersAsync();
    stopThrow();
    expect(postsThrow).toEqual([]);

    const postsUndef: OSActivityPayload[] = [];
    const undef = vi.fn(async (): Promise<ActiveWindowResult | undefined> => undefined);
    const stopUndef = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl: makeFetch({ enabled: true, poll_interval_seconds: 1 }, postsUndef),
      activeWindowImpl: undef,
    });
    await vi.runOnlyPendingTimersAsync();
    stopUndef();
    expect(postsUndef).toEqual([]);
  });

  // --- 9. lazy-import gate: get-windows NEVER loaded when off ---------------

  it("never loads get-windows when consent is off (lazy-import gate)", async () => {
    vi.useFakeTimers();
    const posts: OSActivityPayload[] = [];
    // NOTE: no activeWindowImpl injected -> the watcher uses its DEFAULT lazy
    // `import("get-windows")` source. With consent off, that source is never
    // invoked, so the native module is never imported.
    const stop = startOsActivityWatcher({
      getRuntimeUrl: () => RT,
      fetchImpl: makeFetch({ enabled: false, poll_interval_seconds: 5 }, posts),
    });
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();
    await vi.runOnlyPendingTimersAsync();
    stop();

    expect(getWindowsImportSpy).not.toHaveBeenCalled();
    expect(activeWindowSpy).not.toHaveBeenCalled();
    expect(posts).toEqual([]);
  });
});
