# AD-817 — Desktop Wizard Runtime URL Configurable + Mismatch Detection

**Status:** Ready for Builder
**Dependencies:** AD-759 (Electron tray host), AD-790 (first-run wizard), BF-324 (env-overridable URL)
**Closes:** #749
**Estimated tests:** 6 new (+ existing 60+ desktop tests must remain green)
**Scope guardrails:** desktop/ only. Do NOT touch `src/probos/`, do NOT touch the OSS runtime, do NOT touch `C:\Users\seang\AppData\Local\ProbOS\`.

---

## Problem

`desktop/src/main/index.ts:52` resolves the runtime URL exactly once at module-load:

```ts
const RUNTIME_URL = process.env.PROBOS_RUNTIME_URL ?? "http://127.0.0.1:8765";
```

The value is then consumed by `urlForViewMode()` (line 94), the disconnected-state HTML (line 130, 143), the AD-790 setup wizard render (lines 222, 306, 457), `openExternal` origin gate (line 399), and the `checkRuntime` IPC handler (line 413).

Two operator-facing failure modes:

1. **Wrong default.** Captain's runtime listens on port **18900**, but the desktop defaults to **8765**. The wizard's runtime-check fires `fetch('http://127.0.0.1:8765/api/health')`, gets connection refused, and reports "Could not reach the runtime" — even though the runtime is healthy on 18900.
2. **No remediation path.** The operator cannot change the URL without setting the `PROBOS_RUNTIME_URL` env var *before* launching Electron. There is no settings UI, no wizard input, and no way to recover from a refused health probe without restarting the desktop host.

Issue #749 calls for: configurable URL in the wizard, persistence across restarts, and a "doctor" mismatch surface when desktop-configured ≠ runtime-responding.

## Solution overview

1. Extract a pure `runtime-config.ts` module that owns URL resolution (file > env > default) and persistence, mirroring `firstRun.ts`. Default flips from `8765` → `18900` per Captain's stated preference.
2. Convert the `const RUNTIME_URL` module-binding into a function `getRuntimeUrl()` that reads the resolved value live, so IPC mutations propagate without restart.
3. Add IPC handlers `probos:getRuntimeUrl` and `probos:setRuntimeUrl`.
4. Extend the wizard's runtime-check step (`setupHtml.ts`) with a URL input and a debounced inline health probe.
5. Extend the `probos:checkRuntime` IPC handler to scan a short port candidate list when the configured URL fails — return `{ ok: false, mismatch: { configured, responding } }` so the wizard can surface a precise remediation message.
6. Add a tray menu entry "Runtime URL…" that opens the wizard's runtime step in re-entry mode (operator can change URL post-setup without `Reset Setup…`).

No new npm dependency. The existing JSON-in-userData pattern (already used by `firstRun.ts` and `desktop-prefs.json`) is sufficient — adding `electron-store` is unjustified weight given how thin the surface is.

---

## What This Does NOT Change

- The OSS runtime (`src/probos/**`). Zero Python edits.
- The HXI bundle (`ui/src/**`). Zero React edits.
- `electron-store` is **not** added. The existing JSON-in-userData pattern is reused.
- The AD-790 first-run wizard's other three steps (Welcome, Captain Card, Suggested prompts) are untouched.
- The disconnected-state HTML's button labels and layout. Only the URL string source is rewired.
- Window CSP policy (BF-324 already opened `127.0.0.1:*`).

---

## Implementation

### Section 1 — `desktop/src/main/runtimeConfig.ts` (new file)

Mirror the shape of `firstRun.ts`: pure node:fs I/O, no Electron import, fully testable under vitest.

```ts
/**
 * AD-817: runtime URL persistence + resolution for the Yeo desktop host.
 *
 * Resolution order (highest priority first):
 *   1. Persisted value in <userData>/runtime-config.json
 *   2. PROBOS_RUNTIME_URL environment variable
 *   3. Built-in default (DEFAULT_RUNTIME_URL)
 *
 * Pure-function I/O — no Electron API dependency — so the module is
 * testable under Vitest without spinning the full Electron host.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * BF-324 already validated 127.0.0.1:* through CSP. This default is a
 * polite breaking change for operators previously relying on 8765 —
 * documented in the AD-817 release note; behaviour falls back to the
 * env var, so anyone who has set PROBOS_RUNTIME_URL=http://127.0.0.1:8765
 * is unaffected.
 */
export const DEFAULT_RUNTIME_URL = "http://127.0.0.1:18900";

/** Common ports the runtime is likely to bind in dev/prod configurations. */
export const PORT_CANDIDATES: ReadonlyArray<number> = [
  18900, 8765, 8000, 8080,
];

export interface RuntimeConfig {
  runtimeUrl: string;
}

export function configFilePath(userDataDir: string): string {
  return join(userDataDir, "runtime-config.json");
}

/** Validate that a string looks like an http(s)://host[:port] URL with no path. */
export function isValidRuntimeUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const u = new URL(value);
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    // Reject paths/search/hash — runtime URL is an origin only.
    if (u.pathname !== "/" && u.pathname !== "") return false;
    if (u.search || u.hash) return false;
    return true;
  } catch {
    return false;
  }
}

/** Strip any trailing slash for consistent string concatenation downstream. */
export function normaliseRuntimeUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

export function loadRuntimeConfig(userDataDir: string): RuntimeConfig | null {
  const path = configFilePath(userDataDir);
  if (!existsSync(path)) return null;
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Partial<RuntimeConfig>;
    if (!isValidRuntimeUrl(parsed.runtimeUrl)) return null;
    return { runtimeUrl: normaliseRuntimeUrl(parsed.runtimeUrl) };
  } catch {
    return null;
  }
}

export function saveRuntimeConfig(
  userDataDir: string,
  config: RuntimeConfig,
): RuntimeConfig {
  if (!isValidRuntimeUrl(config.runtimeUrl)) {
    throw new Error(`invalid runtime URL: ${config.runtimeUrl}`);
  }
  const normalised: RuntimeConfig = {
    runtimeUrl: normaliseRuntimeUrl(config.runtimeUrl),
  };
  const path = configFilePath(userDataDir);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(normalised, null, 2), "utf-8");
  return normalised;
}

export interface ResolveOptions {
  userDataDir: string;
  env?: NodeJS.ProcessEnv;
}

/**
 * Resolve the runtime URL using the documented precedence. Pure — the env
 * argument is injectable so tests don't have to mutate process.env.
 */
export function resolveRuntimeUrl({
  userDataDir,
  env = process.env,
}: ResolveOptions): string {
  const stored = loadRuntimeConfig(userDataDir);
  if (stored) return stored.runtimeUrl;
  const envUrl = env.PROBOS_RUNTIME_URL;
  if (typeof envUrl === "string" && isValidRuntimeUrl(envUrl)) {
    return normaliseRuntimeUrl(envUrl);
  }
  return DEFAULT_RUNTIME_URL;
}
```

### Section 2 — `desktop/src/main/index.ts` rewire `RUNTIME_URL`

Replace the `const` module binding with a mutable resolved value and a getter so all existing read sites pick up changes.

```ts
// SEARCH (line 52, exact match)
const RUNTIME_URL = process.env.PROBOS_RUNTIME_URL ?? "http://127.0.0.1:8765";

// REPLACE WITH
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
```

Then update every site that previously read `RUNTIME_URL` to call `getRuntimeUrl()` instead. The full set (verified by grep on 2026-05-23):

| Line | Original                                                                                  | Replacement                                                                                       |
| ---- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 94   | `return \`${RUNTIME_URL}${route}${hash}\`;`                                                | `return \`${getRuntimeUrl()}${route}${hash}\`;`                                                    |
| 130  | `` <code>${RUNTIME_URL}</code> ``                                                          | `` <code>${getRuntimeUrl()}</code> ``                                                              |
| 143  | `window.probos?.openExternal('${RUNTIME_URL}');`                                          | `window.probos?.openExternal('${getRuntimeUrl()}');`                                              |
| 222  | `setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })`                                      | `setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })`                                          |
| 306  | `setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })`                                      | `setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })`                                          |
| 399  | `if (typeof url === "string" && url.startsWith(RUNTIME_URL))`                              | `if (typeof url === "string" && url.startsWith(getRuntimeUrl()))`                                 |
| 413  | `const r = await fetch(RUNTIME_URL + "/api/health", { ... });`                            | (see Section 4 — `checkRuntime` is also extended)                                                  |
| 457  | `setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })`                                      | `setupHtml({ runtimeUrl: getRuntimeUrl(), appVersion })`                                          |

In `bootstrap()` / `app.whenReady().then(...)` resolve the URL **before** `createMainWindow()`:

```ts
// SEARCH (inside app.whenReady().then(() => { ... }), before viewMode is assigned)
  app.whenReady().then(() => {
    viewMode = readViewMode();

// REPLACE WITH
  app.whenReady().then(() => {
    runtimeUrl = resolveRuntimeUrl({ userDataDir: app.getPath("userData") });
    logInfo("runtime URL resolved", { runtimeUrl });
    viewMode = readViewMode();
```

### Section 3 — New IPC handlers `runtime:url:get` / `runtime:url:set`

Use the existing `probos:` channel prefix for consistency.

Add inside the existing `app.whenReady().then(...)` IPC block (alongside `probos:getViewMode` etc.):

```ts
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
```

### Section 4 — Extend `probos:checkRuntime` with mismatch scan

Replace the existing handler (currently at line 408-418):

```ts
ipcMain.handle("probos:checkRuntime", async () => {
  const configured = getRuntimeUrl();
  const probe = async (url: string): Promise<{ ok: boolean; status?: number; error?: string }> => {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), 3000);
    try {
      const r = await fetch(url + "/api/health", { method: "GET", signal: ac.signal });
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

  // Mismatch scan: try other common ports on 127.0.0.1 to detect a
  // misconfigured-URL scenario. Bounded by PORT_CANDIDATES so we don't
  // turn a health probe into a port scanner.
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
```

### Section 5 — Preload bridge (`desktop/src/preload/index.ts`)

Add the new methods to the typed bridge.

```ts
// SEARCH
  /** BF (2026-05-22): probe runtime via main process to bypass
   * the data: URL CORS restriction in the AD-790 first-run wizard. */
  checkRuntime(): Promise<{ ok: boolean; status?: number; error?: string }>;

// REPLACE WITH
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
```

And in the `api` object:

```ts
// SEARCH
  checkRuntime: () => ipcRenderer.invoke("probos:checkRuntime"),
  completeSetup: (payload) =>

// REPLACE WITH
  checkRuntime: () => ipcRenderer.invoke("probos:checkRuntime"),
  getRuntimeUrl: () => ipcRenderer.invoke("probos:getRuntimeUrl"),
  setRuntimeUrl: (value: string) => ipcRenderer.invoke("probos:setRuntimeUrl", value),
  completeSetup: (payload) =>
```

### Section 6 — Wizard URL input (`desktop/src/main/setupHtml.ts`)

Update the runtime-check step to expose an input and a debounced probe that surfaces mismatch information. Replace the step-1 section and the `probeBtn` handler:

```html
<!-- SEARCH (the entire step-1 section through the closing </section>) -->
    <section class="step" data-step="1">
      <h1>Runtime connection</h1>
      <p>Yeo connects to the ProbOS runtime at <code>${runtimeUrl}</code>.
         Click below to verify it's reachable.</p>
      <button id="probe-btn" type="button">Check runtime</button>
      <div class="runtime-status" id="probe-result">Not checked yet.</div>
    </section>

<!-- REPLACE WITH -->
    <section class="step" data-step="1">
      <h1>Runtime connection</h1>
      <p>Yeo connects to the ProbOS runtime at the URL below. The default is
         <code>http://127.0.0.1:18900</code>; change it if your runtime listens
         on a different port.</p>
      <input id="runtime-url-input" type="text"
             value="${runtimeUrl}"
             spellcheck="false"
             placeholder="http://127.0.0.1:18900" />
      <button id="probe-btn" type="button" style="margin-top:12px;">Check runtime</button>
      <div class="runtime-status" id="probe-result">Not checked yet.</div>
    </section>
```

Replace the inline `probeBtn` handler:

```js
// SEARCH (the existing probeBtn.addEventListener('click', async () => { ... }); block)
    probeBtn.addEventListener('click', async () => {
      probeResult.textContent = 'Checking...';
      probeResult.className = 'runtime-status';
      try {
        // BF (2026-05-22): use main-process IPC instead of renderer
        // fetch. The wizard is loaded from a data: URL which has a null
        // origin; cross-origin fetch to 127.0.0.1 fails CORS preflight.
        const probos = window.probos;
        const r = probos && typeof probos.checkRuntime === 'function'
          ? await probos.checkRuntime()
          : { ok: false, error: 'IPC bridge missing (preload not loaded?)' };
        if (r.ok) {
          probeResult.textContent = 'OK - ProbOS runtime is responding.';
          probeResult.className = 'runtime-status ok';
        } else if (r.status) {
          probeResult.textContent = 'Runtime returned status ' + r.status + '.';
          probeResult.className = 'runtime-status fail';
        } else {
          // Show the underlying error to aid diagnosis.
          probeResult.textContent = 'Could not reach the runtime: ' +
            (r.error || 'unknown error') +
            '. Make sure probos serve is running at ' + RUNTIME_URL + '.';
          probeResult.className = 'runtime-status fail';
        }
      } catch (err) {
        probeResult.textContent = 'Probe threw: ' + String(err);
        probeResult.className = 'runtime-status fail';
      }
    });

// REPLACE WITH
    const urlInput = document.getElementById('runtime-url-input');

    async function persistAndProbe() {
      const value = (urlInput.value || '').trim();
      probeResult.textContent = 'Saving...';
      probeResult.className = 'runtime-status';
      const setRes = await window.probos?.setRuntimeUrl(value);
      if (!setRes || !setRes.ok) {
        probeResult.textContent = 'Invalid URL: ' + (setRes && setRes.error
          ? setRes.error
          : 'expected http(s)://host[:port] with no path');
        probeResult.className = 'runtime-status fail';
        return;
      }
      probeResult.textContent = 'Checking ' + setRes.runtimeUrl + '...';
      try {
        const r = await window.probos?.checkRuntime();
        if (!r) {
          probeResult.textContent = 'IPC bridge missing (preload not loaded?)';
          probeResult.className = 'runtime-status fail';
          return;
        }
        if (r.ok) {
          probeResult.textContent = 'OK - ProbOS runtime is responding at '
            + (r.configuredUrl || setRes.runtimeUrl) + '.';
          probeResult.className = 'runtime-status ok';
        } else if (r.mismatch) {
          probeResult.textContent =
            'Desktop is configured to reach ' + r.mismatch.configured +
            ', but only ' + r.mismatch.responding +
            ' is responding. Update the URL above and Check again.';
          probeResult.className = 'runtime-status fail';
        } else if (r.status) {
          probeResult.textContent = 'Runtime returned status ' + r.status + '.';
          probeResult.className = 'runtime-status fail';
        } else {
          probeResult.textContent = 'Could not reach the runtime: ' +
            (r.error || 'unknown error') + '.';
          probeResult.className = 'runtime-status fail';
        }
      } catch (err) {
        probeResult.textContent = 'Probe threw: ' + String(err);
        probeResult.className = 'runtime-status fail';
      }
    }

    probeBtn.addEventListener('click', persistAndProbe);
```

The wizard now exposes the URL input and persists every probe before re-checking — so a successful health response is on the *currently-persisted* URL, not the previous default.

### Section 7 — Tray menu "Runtime URL…" entry

`desktop/src/main/trayMenu.ts` already takes an `onResetSetup` callback. Add a new `onOpenRuntimeSettings` callback driven by index.ts that reloads the wizard step 1.

For the minimum viable implementation: re-use the existing `setupHtml` rendering but seed a query string the wizard reads on `DOMContentLoaded` to jump straight to step 1. Simplest realisation:

```ts
// In desktop/src/main/trayMenu.ts, extend the menu builder options + items.
// Add a new "Runtime URL..." entry between "Reset Setup..." and "Quit".
```

Builder may choose between **(a)** adding a new menu entry that calls `mainWindow.loadURL(...setupHtml...)` with a step-jump hash, or **(b)** deferring this to a follow-up AD if the menu wiring grows beyond +20 LOC. If deferred, file a follow-up issue titled "AD-817b: tray menu entry to re-open runtime URL settings post-onboarding" and reference it in the commit message. **Acceptance does not require the tray menu entry** — sections 1-6 deliver the persistence + wizard input + mismatch detection that #749 calls out.

---

## Tests

Add `desktop/src/main/runtimeConfig.test.ts` (mirrors `firstRun.test.ts` shape):

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  DEFAULT_RUNTIME_URL,
  configFilePath,
  isValidRuntimeUrl,
  loadRuntimeConfig,
  normaliseRuntimeUrl,
  resolveRuntimeUrl,
  saveRuntimeConfig,
} from "./runtimeConfig";

describe("runtimeConfig (AD-817)", () => {
  let tmp: string;
  beforeEach(() => { tmp = mkdtempSync(join(tmpdir(), "yeo-rtcfg-")); });
  afterEach(() => { rmSync(tmp, { recursive: true, force: true }); });

  it("isValidRuntimeUrl accepts http and https origins, rejects everything else", () => {
    expect(isValidRuntimeUrl("http://127.0.0.1:18900")).toBe(true);
    expect(isValidRuntimeUrl("https://example.com")).toBe(true);
    expect(isValidRuntimeUrl("http://127.0.0.1:18900/api/x")).toBe(false);
    expect(isValidRuntimeUrl("ftp://x")).toBe(false);
    expect(isValidRuntimeUrl("")).toBe(false);
    expect(isValidRuntimeUrl(null)).toBe(false);
  });

  it("normaliseRuntimeUrl strips trailing slashes", () => {
    expect(normaliseRuntimeUrl("http://x:1/")).toBe("http://x:1");
    expect(normaliseRuntimeUrl("http://x:1///")).toBe("http://x:1");
  });

  it("resolveRuntimeUrl returns the built-in default when no file or env present", () => {
    expect(resolveRuntimeUrl({ userDataDir: tmp, env: {} })).toBe(DEFAULT_RUNTIME_URL);
  });

  it("resolveRuntimeUrl prefers env var over default", () => {
    const got = resolveRuntimeUrl({
      userDataDir: tmp,
      env: { PROBOS_RUNTIME_URL: "http://127.0.0.1:9000" },
    });
    expect(got).toBe("http://127.0.0.1:9000");
  });

  it("resolveRuntimeUrl prefers persisted file over env and default", () => {
    saveRuntimeConfig(tmp, { runtimeUrl: "http://127.0.0.1:7777" });
    const got = resolveRuntimeUrl({
      userDataDir: tmp,
      env: { PROBOS_RUNTIME_URL: "http://127.0.0.1:9000" },
    });
    expect(got).toBe("http://127.0.0.1:7777");
  });

  it("loadRuntimeConfig returns null when the file is missing, malformed, or has an invalid URL", () => {
    expect(loadRuntimeConfig(tmp)).toBeNull();
    writeFileSync(configFilePath(tmp), "not json", "utf-8");
    expect(loadRuntimeConfig(tmp)).toBeNull();
    writeFileSync(configFilePath(tmp), JSON.stringify({ runtimeUrl: "ftp://x" }), "utf-8");
    expect(loadRuntimeConfig(tmp)).toBeNull();
  });

  it("saveRuntimeConfig throws on invalid URL and round-trips on valid URL", () => {
    expect(() => saveRuntimeConfig(tmp, { runtimeUrl: "not a url" })).toThrow();
    const saved = saveRuntimeConfig(tmp, { runtimeUrl: "http://127.0.0.1:18900/" });
    expect(saved.runtimeUrl).toBe("http://127.0.0.1:18900");
    const reloaded = loadRuntimeConfig(tmp);
    expect(reloaded?.runtimeUrl).toBe("http://127.0.0.1:18900");
  });
});
```

That's 7 tests. The "4+ new tests" acceptance from the issue is satisfied. **The Builder should NOT** write integration tests that boot Electron — `setupHtml`'s inline JS is rendered into a data: URL at runtime and not unit-testable from vitest without a headless Electron harness (which the desktop suite doesn't currently use). The runtimeConfig.ts module + grep verification of the rewired sites is the testable contract.

---

## Acceptance Criteria

1. `cd desktop && npm test` is green; new `runtimeConfig.test.ts` contributes ≥ 6 tests; existing tests remain green.
2. `cd desktop && npm run build` succeeds with zero new warnings.
3. `desktop/src/main/index.ts` no longer contains the string literal `"http://127.0.0.1:8765"` anywhere. Default lives once, in `runtimeConfig.ts`.
4. `grep -n "RUNTIME_URL" desktop/src/main/index.ts` returns only the JSDoc comment lines (lines 4, 8-10). All runtime read sites use `getRuntimeUrl()`.
5. New preload methods `getRuntimeUrl` / `setRuntimeUrl` are exposed and typed in `ProbosApi`.
6. Mismatch payload from `probos:checkRuntime` includes `{ configured, responding }` keys and the wizard surfaces them in the inline status block.
7. One commit message: `AD-817: desktop runtime URL configurable + mismatch detection. Closes #749.`
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

After landing:

- `PROGRESS.md` Era-5: append CLOSED entry "AD-817 — Desktop wizard runtime URL configurable + mismatch detection".
- `docs/development/roadmap.md`: if the row for #749 still says OPEN, flip to CLOSED with commit SHA.
- `DECISIONS.md`: append a one-paragraph entry summarising the resolution order (file > env > default) and the polite default flip 8765 → 18900.

---

## Verified Against Codebase (2026-05-23)

```
git show 8743c77e --stat
  (BF-299 head; no desktop/ files touched.)

grep -n "RUNTIME_URL\|8765" desktop/src/main/index.ts
   8: pointed at `PROBOS_RUNTIME_URL` env var
   9: (default `http://127.0.0.1:8765`; BF-324 widened CSP so any
  52: const RUNTIME_URL = process.env.PROBOS_RUNTIME_URL ?? "http://127.0.0.1:8765";
  94: return `${RUNTIME_URL}${route}${hash}`;
 130: <code>${RUNTIME_URL}</code>
 143: window.probos?.openExternal('${RUNTIME_URL}');
 222: setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })
 306: setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })
 399: if (typeof url === "string" && url.startsWith(RUNTIME_URL))
 413: const r = await fetch(RUNTIME_URL + "/api/health", {
 457: setupHtml({ runtimeUrl: RUNTIME_URL, appVersion })

ls desktop/src/main/
  chatWithAgent.test.ts, chatWithAgent.ts,
  connectionStateMachine.test.ts, connectionStateMachine.ts,
  deepLink.test.ts, deepLink.ts,
  firstRun.test.ts, firstRun.ts,
  index.ts, logger.ts, notifications.ts,
  setupHtml.ts, singleInstance.test.ts, singleInstance.ts,
  trayMenu.test.ts, trayMenu.ts
  (No doctor.ts exists — mismatch detection lives in checkRuntime IPC; no
   new "Doctor" component is required to satisfy #749's "doctor surface".)

grep -n "electron-store" desktop/package.json
  (no match — dependency is NOT present and is NOT added by this AD.)

cat desktop/vitest.config.ts
  environment: "node", include: ["src/**/*.test.ts"], globals: true
  (Tests are pure-node, no Electron harness required.)

PROGRESS.md highest AD scan:
  AD-789, AD-819, AD-820, AD-822, AD-823, AD-824, AD-825, AD-826
  AD-817 is unused in PROGRESS.md and matches the title of GH issue #749.
  Current highest: AD-826. AD-817 is reserved by the issue and is safe to use.
```
