# AD-1054 — OS-activity sensor (desktop foreground-window watcher → `os.activity` event)

> **Type:** Builder-ready BuildSpec (Architect-authored, verify-first). **One AD.**
> **AD:** **AD-1054** (top-level, NEW). Current highest landed top-level = **AD-1053** (actionable notifications, 2026-06-25). Zero `AD-1054+` in `PROGRESS.md`/`DECISIONS.md`. Re-confirm at build start per the OSS hard rule.
> **Date:** 2026-06-26. **Author:** ProbOS Architect.
> **Status:** Ready. **Dependencies:** none (HEAD-ready). **Estimated tests:** ~12 backend + ~8 desktop.
> **Default-OFF. Local-only. Active-window metadata ONLY — NO keystroke/screen/clipboard capture. Additive → byte-identical when the consent flag is off.**

---

## 0. One-line summary

A default-OFF, consent-gated, local-only desktop (AD-759, Electron) foreground-window watcher that POSTs active-window metadata to a new runtime ingestion endpoint, which (when consent is on) emits a new `OS_ACTIVITY` runtime event. **Pure sensor — no intelligence, no suggestions.** Nothing in OSS consumes the event (a commercial overlay consumer, out of scope here, will).

---

## 1. Problem (verified at HEAD)

`grep` for `os_activity|OS_ACTIVITY|active_window|foreground_window|GetForegroundWindow` across `src/probos` returns **ZERO** OS-activity-detection hits (the `*_active_window_seconds` matches in `config.py` are unrelated avatar-render timing fields; `cognitive/anomaly_window.py` is an unrelated anomaly window). There is no foundation for surfacing "what app/window is the Captain in" as a runtime signal.

This AD adds **only the raw sensor plumbing**: a desktop watcher, a consent flag, a runtime ingestion endpoint, and a runtime event. It is infrastructure (like heartbeat or the LAN mDNS advertiser AD-708e) — the value of any intelligence over the signal is out of scope and lives in a separate overlay consumer.

---

## 2. Verified seams (every symbol read at HEAD — citations in §11)

| Seam | Symbol / behavior | This AD uses it for |
|---|---|---|
| Desktop → runtime HTTP | `desktop/src/main/index.ts` uses global `fetch(getRuntimeUrl() + "/api/...")` with an `AbortController` + 3 s timeout (`checkRuntime` IPC, `index.ts:519-535`). `getRuntimeUrl()` returns the AD-817 resolved runtime URL. | **The ingestion path.** The watcher POSTs to `getRuntimeUrl() + "/api/os-activity"` directly from Electron main — no IPC→renderer bridge. |
| Desktop boot | `app.whenReady().then(...)` (`index.ts:454`) after `createMainWindow()` (`index.ts:334`); `app.on("window-all-closed", ...)` (`index.ts:653`). | Start the watcher (gated) in `whenReady`; stop it on quit. |
| Desktop bundling | `electron.vite.config.ts` uses `externalizeDepsPlugin()` for `main`. Anything in `dependencies` is auto-externalized (not bundled). Desktop currently has **no** `dependencies` block (only `devDependencies`). | Add `get-windows` to a NEW `dependencies` block → externalized → the native/FFI helper is never bundled. |
| Desktop tests | `vitest` (node env), `include: ["src/**/*.test.ts"]`. Existing pure/DI test conventions: `runtimeConfig.test.ts` (pure I/O), `notifications.test.ts` (`vi.mock("electron")` + DI). | The watcher's pure mapper + consent-gate are unit-tested with injected `fetch`/`activeWindow`, never loading `get-windows`. |
| Runtime EventType | `EventType(str, Enum)` (`events.py:20`); typed subclasses of `@dataclass BaseEvent` (`events.py:526`) set `event_type: EventType = field(default=..., init=False)` + domain fields with defaults; `to_dict()` → `{"type", "data", "timestamp"}`. | Add `OS_ACTIVITY = "os_activity"` + an `OSActivityEvent` dataclass. |
| Runtime emit | `runtime.emit_event(event: BaseEvent | str | EventType, data=None)` (`runtime.py:1388`) → `_emit_event` → `_emit_event_local` → `_event_listeners` (BF-639 task-retained). Accepts a `BaseEvent` directly. | The endpoint emits `runtime.emit_event(OSActivityEvent(...))`. |
| Runtime listener (test) | `runtime.add_event_listener(fn, type_filter)` (`runtime.py:1245`) appends to `_event_listeners`; listeners receive the serialized `{"type","data","timestamp"}` dict. | Test harness alternative for capturing the emitted event on the real path. |
| Config convention | `DiscoveryConfig` (AD-708e, `config.py:5774`) + `DeviceConfig` (AD-843, `config.py:5872`): a small dedicated `BaseModel` with `enabled: bool = False` as the first field, mounted on `SystemConfig` (`config.py:6101-6102`) via a one-line `Field(default_factory=...)`. No `config/system.yaml` edit. | New `OSActivityConfig` mounted on `SystemConfig`. |
| Router pattern | `routers/system.py` — `router = APIRouter(prefix="/api")` (already mounted); imports `BaseModel, Field` (pydantic), `IntentMessage`, `logger`. AD-1053 `POST /api/notifications/{id}/accept` (`system.py:426`) is the honest-degrade-HTTP-200 + `Depends(get_runtime)` pattern. | Add `POST /api/os-activity` (ingest) + `GET /api/os-activity` (consent read). No new router registration. |
| Config read endpoint | `GET /api/config` (`routers/config.py:189`) is **crew-scope-gated** (`dependencies=[Depends(require_crew_scope)]`) and redacts secrets. | **Do NOT** have the watcher read `/api/config` (auth + redaction friction). The watcher reads consent from a dedicated public `GET /api/os-activity`. |

**STOP conditions — all cleared:** (1) highest AD is 1053 → AD-1054 ✓; (2) Electron main reaches the runtime HTTP API via `fetch`+`getRuntimeUrl()` ✓; (3) the desktop takes the native dep cleanly via `externalizeDepsPlugin()` + lazy dynamic import ✓ (packaging/asar-unpack is the deferred AD-759b's concern — see §9 Build note).

---

## 3. Solution overview

**Runtime side (the testable core):**
1. `OSActivityConfig` (`enabled: bool = False`, `poll_interval_seconds: int = 5`) on `SystemConfig` — the consent gate.
2. `OS_ACTIVITY` `EventType` + an `OSActivityEvent` typed dataclass.
3. `POST /api/os-activity` — consent-gated ingestion: OFF (default) → no-op `{"ingested": False, "reason": "disabled"}` (no event); ON → validate (Pydantic) + emit `OSActivityEvent`. Honest-degrade HTTP-200.
4. `GET /api/os-activity` — the watcher's public self-gate read: returns ONLY `{enabled, poll_interval_seconds}` (no secrets).

**Desktop side (the watcher):**
5. `get-windows` (MIT) added to a new `desktop/package.json` `dependencies` block.
6. `desktop/src/main/osActivityWatcher.ts` — a pure Result→payload mapper + change-detector + a self-gating heartbeat poller (lazy `import('get-windows')`; injected `fetch`/`activeWindow` for tests).
7. Wire it from `index.ts` `whenReady` (started gated; stopped on quit).

**Two privacy gates (defense in depth):** the runtime endpoint is the authoritative security boundary (refuses when off); the watcher independently self-gates (does not call `activeWindow()` when off — the sensor does not even run without consent).

---

## 4. Implementation — runtime side

### Section 4.1 — `OSActivityConfig` (config.py)

Add the model immediately after `DeviceConfig` (ends at `config.py:5882`, before `class SystemConfig`). SEARCH/REPLACE:

```python
    enabled: bool = False  # AD-843c-1: gate device.notify bus subscription (default OFF)
    probationary_alpha: float = Field(default=1.0, gt=0.0)
    probationary_beta: float = Field(default=3.0, gt=0.0)


class SystemConfig(BaseModel):
```

→

```python
    enabled: bool = False  # AD-843c-1: gate device.notify bus subscription (default OFF)
    probationary_alpha: float = Field(default=1.0, gt=0.0)
    probationary_beta: float = Field(default=3.0, gt=0.0)


class OSActivityConfig(BaseModel):
    """AD-1054: consent gate for the desktop OS-activity sensor.

    A default-OFF, local-only foreground-window watcher in the desktop app
    (AD-759) reports active-window METADATA ONLY (app name + window title +
    optional app path/url) — NEVER keystrokes, screen content, or clipboard.
    The event is emitted in-process; this AD does not persist or export it.

    Privacy-by-design: ``enabled`` defaults False (no capture without consent);
    the desktop watcher self-gates on this flag AND the runtime ingestion
    endpoint refuses when off (defense in depth).
    """

    enabled: bool = Field(
        default=False,
        description="Consent gate for the OS-activity sensor. Default OFF (no capture without consent).",
    )
    poll_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Heartbeat cadence (seconds) the desktop watcher reads to poll the active window.",
    )


class SystemConfig(BaseModel):
```

Mount it on `SystemConfig`. SEARCH/REPLACE (anchor on the AD-843b device line):

```python
    self_mod: SelfModConfig = SelfModConfig()
    device: DeviceConfig = DeviceConfig()  # AD-843b (probationary device trust prior)
    dependency: DependencyConfig = Field(default_factory=DependencyConfig)  # AD-838c
```

→

```python
    self_mod: SelfModConfig = SelfModConfig()
    device: DeviceConfig = DeviceConfig()  # AD-843b (probationary device trust prior)
    os_activity: OSActivityConfig = Field(default_factory=OSActivityConfig)  # AD-1054 (default OFF)
    dependency: DependencyConfig = Field(default_factory=DependencyConfig)  # AD-838c
```

> **No `config/system.yaml` edit** — the flag is a config-MODEL default (False). The Captain sets the value. A default install boots byte-identical.

### Section 4.2 — `OS_ACTIVITY` EventType + `OSActivityEvent` (events.py)

Add the enum value. SEARCH/REPLACE (anchor on the Notifications/tasks block at `events.py:148`):

```python
    # Notifications / tasks
    NOTIFICATION = "notification"
    NOTIFICATION_ACK = "notification_ack"
    NOTIFICATION_SNAPSHOT = "notification_snapshot"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
```

→

```python
    # Notifications / tasks
    NOTIFICATION = "notification"
    NOTIFICATION_ACK = "notification_ack"
    NOTIFICATION_SNAPSHOT = "notification_snapshot"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"

    # OS-activity sensor (AD-1054) — raw desktop foreground-window metadata.
    # Pure sensor; emitted in-process. Nothing in OSS consumes it.
    OS_ACTIVITY = "os_activity"
```

Add the typed event class. Place it after the existing build-event dataclasses block, or adjacent to any other sensor/notification event class — anywhere after `BaseEvent` is fine. Provide it as a full new dataclass (insert at a clean location near the other `@dataclass(...)Event` definitions):

```python
@dataclass
class OSActivityEvent(BaseEvent):
    """AD-1054: a desktop OS foreground-window activity sample (pure sensor).

    Active-window METADATA ONLY — app name + window title + optional app
    executable path / browser url. NO keystrokes, screen content, or clipboard.
    ``ts`` is the client (watcher) capture time; ``BaseEvent.timestamp`` is the
    server emit time. Emitted in-process; not persisted/exported by this AD.
    """

    event_type: EventType = field(default=EventType.OS_ACTIVITY, init=False)
    active_app: str = ""
    window_title: str = ""
    app_path: str = ""
    url: str = ""
    ts: float = 0.0
```

> `file_path` (the document being edited) is a **forward** field — `get-windows` does not provide it; a deeper integration adds it in a later AD. Do **not** add an unpopulated `file_path` field now.

### Section 4.3 — ingestion + consent endpoints (routers/system.py)

Add `import time` and the events import to the top of `routers/system.py`. SEARCH/REPLACE:

```python
import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from probos.api_models import ShutdownRequest
from probos.proactive import build_proactive_status_snapshot
from probos.routers.deps import get_runtime, get_task_tracker
from probos.types import IntentMessage
```

→

```python
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from probos.api_models import ShutdownRequest
from probos.events import OSActivityEvent
from probos.proactive import build_proactive_status_snapshot
from probos.routers.deps import get_runtime, get_task_tracker
from probos.types import IntentMessage
```

Add the request model + both routes. Insert immediately after the AD-1053 `accept_notification` function (ends at `system.py:474`, before `@router.get("/emergence")`):

```python
class OSActivityIngest(BaseModel):
    """AD-1054: desktop OS-activity sensor payload — active-window metadata only."""

    active_app: str = Field(min_length=1, max_length=256)
    window_title: str = Field(default="", max_length=1024)
    app_path: str | None = Field(default=None, max_length=2048)
    url: str | None = Field(default=None, max_length=2048)
    ts: float | None = None


@router.get("/os-activity")
async def os_activity_consent(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-1054: the desktop watcher's self-gate read.

    Returns ONLY ``{enabled, poll_interval_seconds}`` (no secrets) so the
    watcher can decide whether to start polling the active window WITHOUT
    crew-scope auth. The authoritative gate is the POST endpoint below.
    """
    cfg = getattr(runtime.config, "os_activity", None)
    if cfg is None:
        return {"enabled": False, "poll_interval_seconds": 5}
    return {
        "enabled": bool(cfg.enabled),
        "poll_interval_seconds": int(cfg.poll_interval_seconds),
    }


@router.post("/os-activity")
async def ingest_os_activity(
    body: OSActivityIngest, runtime: Any = Depends(get_runtime)
) -> dict[str, Any]:
    """AD-1054: consent-gated ingestion of a desktop foreground-window sample.

    OFF (default) → no-op, NO event (byte-identical). ON → emit ``OS_ACTIVITY``.
    Pure plumbing: the event is emitted in-process and NOT persisted/exported by
    this AD. Honest-degrade HTTP-200 — never a 500.
    """
    cfg = getattr(runtime.config, "os_activity", None)
    if cfg is None or not cfg.enabled:
        # Default path: consent off → the sensor signal is dropped, no event.
        return {"ingested": False, "reason": "disabled"}
    try:
        runtime.emit_event(
            OSActivityEvent(
                active_app=body.active_app,
                window_title=body.window_title,
                app_path=body.app_path or "",
                url=body.url or "",
                ts=body.ts if body.ts is not None else time.time(),
            )
        )
    except Exception:
        logger.warning(
            "AD-1054: emit OS_ACTIVITY failed; sample dropped", exc_info=True
        )
        return {"ingested": False, "reason": "emit_error"}
    return {"ingested": True}
```

> The client supplies only metadata; FastAPI/Pydantic rejects a malformed body with 422 (a missing `active_app`, wrong type, or over-length field). The consent flag is server-authoritative — the client cannot enable capture.

---

## 5. Implementation — desktop side

### Section 5.1 — `get-windows` dependency (desktop/package.json)

Add a NEW `dependencies` block (the desktop currently has none). SEARCH/REPLACE:

```json
  "scripts": {
    "dev": "electron-vite dev",
    "build": "electron-vite build",
    "package": "electron-vite build && echo 'Installer pipeline deferred to AD-759b (no artifact produced).'",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
```

→

```json
  "scripts": {
    "dev": "electron-vite dev",
    "build": "electron-vite build",
    "package": "electron-vite build && echo 'Installer pipeline deferred to AD-759b (no artifact produced).'",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "get-windows": "^9.2.0"
  },
  "devDependencies": {
```

> **License:** `get-windows` is **MIT** (sindresorhus; the successor to `active-win`). Added as a `desktop/` runtime dependency (operator-facing Electron app), **NOT vendored**. Its Windows FFI dep `koffi` (MIT) comes transitively. **ActivityWatch (MPL-2.0)** is **pattern-absorbed only** (heartbeat poll-on-interval + local-only + opt-in consent) — **no MPL code copied**. Confirm the latest `get-windows` major at `npm install`; it is ESM-only (Node 18+) — the lazy dynamic import in §5.2 is what makes that safe.

### Section 5.2 — the watcher (NEW `desktop/src/main/osActivityWatcher.ts`)

Full new file:

```typescript
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
```

### Section 5.3 — wire it into the boot (index.ts)

Add the import (top of `index.ts`, after the other `./` imports):

```typescript
import { startOsActivityWatcher } from "./osActivityWatcher.js";
```

Add a module-scope handle next to the other lets (anchor on `let tray`):

```typescript
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
```

→

```typescript
let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let stopOsActivityWatcher: (() => void) | null = null;
```

Start it (gated by self-gate) in `whenReady`, right after `createMainWindow();`:

```typescript
    tray = new Tray(trayIcon);
    refreshTrayMenu();

    createMainWindow();

    // Preload-driven IPC handlers.
```

→

```typescript
    tray = new Tray(trayIcon);
    refreshTrayMenu();

    createMainWindow();

    // AD-1054: arm the OS-activity sensor. It self-gates on the runtime
    // consent flag (GET /api/os-activity) and does NOT capture the active
    // window unless the Captain has enabled it (default OFF). Local-only.
    stopOsActivityWatcher = startOsActivityWatcher({ getRuntimeUrl });

    // Preload-driven IPC handlers.
```

Stop it on shutdown (anchor on the existing `window-all-closed` handler, `index.ts:653`):

```typescript
  app.on("window-all-closed", () => {
```

→

```typescript
  app.on("before-quit", () => {
    if (stopOsActivityWatcher) {
      stopOsActivityWatcher();
      stopOsActivityWatcher = null;
    }
  });

  app.on("window-all-closed", () => {
```

> Verify `app.on("before-quit", ...)` is not already registered; if it is, fold the stop call into the existing handler rather than adding a second.

---

## 6. Privacy guarantees (explicit)

1. **Default-OFF (two gates):** `OSActivityConfig.enabled` defaults `False`; the watcher self-gates on `GET /api/os-activity` (does not call `activeWindow()` when off) AND the `POST /api/os-activity` endpoint refuses + emits nothing when off.
2. **Consent required to start:** no capture without the Captain enabling the flag. The sensor does not run; the endpoint is a no-op.
3. **Local-only:** the `OS_ACTIVITY` event is emitted in-process to runtime listeners. This AD does NOT persist, export, or transmit it off-host.
4. **Metadata only:** active-window app name + title (+ optional app executable path / browser url). Explicitly **NO keystrokes, NO screen content, NO clipboard**.
5. **Change-detection:** a sample is POSTed only on a window CHANGE (heartbeat poll + diff), not a continuous stream.
6. **Additive / byte-identical when off:** config default `False` + watcher self-gate + endpoint no-op → the runtime and the desktop boot identically to HEAD when consent is off.

---

## 7. Tests

### 7.1 Backend — `tests/test_ad1054_os_activity_sensor.py` (BF-287 real fixtures, `PROBOS_DATA_DIR`-isolated)

Harness (mirror AD-1053's): `FastAPI()` + `app.include_router(router)` (from `probos.routers.system`) + `app.dependency_overrides[get_runtime] = lambda: runtime` + `TestClient`. The test `runtime` uses a **real** `SystemConfig` (flip `config.os_activity.enabled`) and a thin recorder for `emit_event` (`SimpleNamespace(config=<real SystemConfig>, emit_event=captured.append)`) — the EVENT and CONFIG under test are real (real `OSActivityEvent`, real `BaseEvent.to_dict`); only the emit sink is a recorder (the AD-1053 `SimpleNamespace`-runtime idiom). *(Optional stronger variant: a real runtime + `add_event_listener` capturing the serialized dict — use if a runtime fixture is readily available.)*

| # | Test | Assert |
|---|---|---|
| 1 | `OSActivityConfig` defaults | `enabled is False`, `poll_interval_seconds == 5` |
| 2 | `SystemConfig().os_activity` | present, is `OSActivityConfig`, default OFF |
| 3 | `poll_interval_seconds` bounds | `0`/`61` → `ValidationError` (ge=1, le=60) |
| 4 | `OS_ACTIVITY` enum | `EventType.OS_ACTIVITY.value == "os_activity"` |
| 5 | `OSActivityEvent.to_dict()` | `{"type":"os_activity","data":{active_app,window_title,app_path,url,ts},"timestamp":...}` |
| 6 | `GET /api/os-activity` OFF (default) | `{"enabled": False, "poll_interval_seconds": 5}` |
| 7 | `GET /api/os-activity` ON | flip `enabled=True`, `poll_interval_seconds=10` → reflected |
| 8 | `POST /api/os-activity` OFF | `{"ingested": False, "reason": "disabled"}` AND `captured == []` (no event) |
| 9 | `POST /api/os-activity` ON | valid body → `{"ingested": True}` AND exactly one captured `OSActivityEvent` with matching `active_app`/`window_title`/`app_path`/`url` |
| 10 | `POST` ON, `ts` omitted | `ingested True`; captured event `ts > 0` (server fallback) |
| 11 | `POST` bad payload | missing `active_app` / wrong type / over-length → 422; `captured == []` |
| 12 | `POST` ON, emit raises | recorder raises → `{"ingested": False, "reason": "emit_error"}`, HTTP 200 (honest-degrade) |

### 7.2 Desktop — `desktop/src/main/osActivityWatcher.test.ts` (vitest, DI; `get-windows` never loaded)

| # | Test | Assert |
|---|---|---|
| 1 | `mapActiveWindowToPayload` well-formed | `{title, owner:{name,path}, url}` → full payload incl. `app_path`, `url`, `ts = now/1000` |
| 2 | `mapActiveWindowToPayload` minimal | `{owner:{name}}` (no title/path/url) → `window_title:""`, no `app_path`/`url` keys |
| 3 | `mapActiveWindowToPayload` bad shape | `undefined` / `{}` / `{owner:{}}` → `null` (honest-degrade) |
| 4 | `shouldEmit` | `null` prev → true; same app+title → false; changed app → true; changed title → true |
| 5 | consent gate OFF | injected `fetchImpl` → `{enabled:false}`; `activeWindowImpl` spy **never called**; no POST |
| 6 | consent gate ON | `{enabled:true}` → `activeWindowImpl` called; a POST to `/api/os-activity` fires with the mapped JSON body |
| 7 | change-detection | two ticks, same window → exactly **one** POST (2nd suppressed); a changed window → a 2nd POST |
| 8 | honest-degrade | `activeWindowImpl` throws / returns `undefined` → no POST, no throw |

Use injected `fetchImpl`/`activeWindowImpl` spies + `vi.useFakeTimers()` to advance the heartbeat; assert call counts. Mirror `notifications.test.ts` (DI) + `runtimeConfig.test.ts` (pure).

---

## 8. What this does NOT change

- **No consumer of `OS_ACTIVITY`** in OSS — nothing subscribes; the event is inert until a separate overlay consumer (out of scope) subscribes. Do not add a subscriber, an intelligence layer, a suggestion surface, or any "what to do about it" logic.
- **No `config/system.yaml` edit** — the flag is a model default.
- **No file read/write** — that is the existing OSS FileReader/FileWriter agents, not this sensor.
- **No `file_path` field** — forward-only; `get-windows` does not provide the edited-document path.
- **No desktop management console** (a separate desktop-app feature) and **no packaging/installer** work (AD-759b deferred).
- **No new router registration** — `routers/system.py` is already mounted.
- **No `/api/config` change** — the watcher reads the dedicated public consent endpoint, not the crew-scoped config snapshot.

---

## 9. Build note (forward, non-blocking)

`externalizeDepsPlugin()` keeps `get-windows` (and `koffi`) out of the electron-vite main bundle, so `npm run build` (electron-vite build) succeeds. The eventual **installer** (deferred AD-759b) must `asar`-unpack `get-windows`'s native helper + `koffi`'s prebuilt binary (`asarUnpack` / `files` config) so the externalized native code is reachable at runtime in a packaged app. Flagged forward; **not** in scope for this AD (no packaging artifact is produced today).

---

## 10. Trackers + gates

**Trackers:**
- `PROGRESS.md` — an `AD-1054 shipped` line: PLUMBING framing (default-OFF, local-only, active-window metadata only, two gates, byte-identical when off). Note "(gates a commercial overlay consumer, out of scope here)". **No** commercial / "context-aware" / assist / pricing language.
- `DECISIONS.md` — a `### AD-1054` entry, same plumbing-only framing.

**Gate commands:**
- Backend (isolated, BF-287): `Set-Location 'd:\ProbOS'; $env:PROBOS_DATA_DIR="$env:TEMP\probos_ad1054_$(Get-Random)"; New-Item -ItemType Directory -Force -Path $env:PROBOS_DATA_DIR | Out-Null; & 'd:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1054_os_activity_sensor.py -q -n 0; Remove-Item $env:PROBOS_DATA_DIR -Recurse -Force; Remove-Item Env:\PROBOS_DATA_DIR`
- Backend regression (events/config/system touched): `& 'd:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1053_actionable_notifications.py tests/test_ad637d*.py -q -n 0` (confirm the router + emit path are unbroken).
- Desktop: `cd desktop; npx vitest run` (the new watcher test + the full desktop suite, 0 regressions) and `npm install` (resolves `get-windows`) then `npm run build` (electron-vite build clean — confirms the dep externalizes).
- `get_errors` clean on every touched file.

---

## 11. Acceptance criteria

1. `OSActivityConfig` on `SystemConfig`, default `enabled=False`; a default install boots byte-identical.
2. `EventType.OS_ACTIVITY` + `OSActivityEvent` serialize per the `BaseEvent` contract.
3. `POST /api/os-activity` OFF → no-op, no event; ON → validates + emits exactly one `OSActivityEvent`; bad payload → 422; emit failure → honest-degrade HTTP-200.
4. `GET /api/os-activity` returns only `{enabled, poll_interval_seconds}` (no secrets).
5. The desktop watcher self-gates (no `activeWindow()` call when off), maps the Result correctly, change-detects, and honest-degrades; `get-windows` is never loaded under vitest.
6. `get-windows` added to `desktop/package.json` `dependencies` (MIT, not vendored); `npm run build` clean.
7. Backend + desktop gates green, 0 regressions; `get_errors` clean.
8. No commercial / assist / "context-aware" / pricing language in any OSS artifact.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 12. Verified Against Codebase (2026-06-26)

```
# Highest AD = 1053; no AD-1054+ exists
grep -n "AD-105[4-9]|AD-10[6-9][0-9]" DECISIONS.md
  (no matches)
PROGRESS.md:1  "AD-1053 shipped (2026-06-25) ... actionable accept->dispatch affordance"

# No OS-activity sensor at HEAD (GAP 1 re-confirmed)
grep "os_activity|OS_ACTIVITY|active_window|foreground_window|GetForegroundWindow" src/probos
  (only unrelated *_active_window_seconds avatar-timing fields + cognitive/anomaly_window.py)

# Desktop → runtime HTTP ingestion path
desktop/src/main/index.ts:519-535   ipcMain.handle("probos:checkRuntime") → fetch(url + "/api/health", {signal: ac.signal})
desktop/src/main/index.ts:69        function getRuntimeUrl(): string { return runtimeUrl; }  (AD-817 resolved)
desktop/src/main/index.ts:454       app.whenReady().then(() => { ... createMainWindow(); ... })
desktop/src/main/index.ts:653       app.on("window-all-closed", () => {

# Desktop bundling externalizes deps; node-env vitest
desktop/electron.vite.config.ts:5   main: { plugins: [externalizeDepsPlugin()], ... }
desktop/vitest.config.ts:4-7        environment: "node"; include: ["src/**/*.test.ts"]
desktop/package.json                only devDependencies (no dependencies block)

# Runtime event system
src/probos/events.py:20             class EventType(str, Enum)
src/probos/events.py:148-153        # Notifications / tasks ... NOTIFICATION/TASK_*
src/probos/events.py:526            class BaseEvent  (to_dict → {"type","data","timestamp"})
src/probos/runtime.py:1388          def emit_event(self, event: BaseEvent | str | EventType, data=None)
src/probos/runtime.py:1245          def add_event_listener(self, fn, type_filter)

# Config conventions
src/probos/config.py:5872-5882      class DeviceConfig(BaseModel): enabled: bool = False ...
src/probos/config.py:5774           class DiscoveryConfig(BaseModel)  (enabled default False)
src/probos/config.py:6101-6102      desktop/discovery mounted via Field(default_factory=...)
src/probos/config.py:5900           device: DeviceConfig = DeviceConfig()  # AD-843b

# Router pattern + the crew-scoped config endpoint (why a dedicated consent read)
src/probos/routers/system.py:13     from pydantic import BaseModel, Field
src/probos/routers/system.py:22     router = APIRouter(prefix="/api", tags=["system"])
src/probos/routers/system.py:426    async def accept_notification(...)  (honest-degrade HTTP-200 pattern)
src/probos/routers/config.py:189    @router.get("", dependencies=[Depends(require_crew_scope)])  (crew-scoped + redacts)
```
