# BF-999 -- #1852: the HXI settings store holds a live CSRF token for every save

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Status:** ready to prove on the oracle. **Base:** main `f7acb948` (tree `f12fe25c`). **Issue:** #1852 (PR says `Refs #1852`). **Path:** `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`. **Estimated tests:** 1 new vitest file (12 cases); no existing test changes. **No AD.** BF-999 allocated by the orchestrator (four-source enumeration, 02:32Z); the ledger on main reads latest BF-998, next BF-999 (`docs/development/open-ads-report.md:32`).

## 1. Problem

- **Router (unchanged by this slice).** `src/probos/routers/config.py:50-71`: single-consume tokens, `_CSRF_TTL_SECONDS = 300` on `time.monotonic()`, expired when `now - t > 300`. `GET /api/config` issues one (`:247`). `POST /api/config` consumes it as its first statement (`:263-265`) and answers 403 `invalid_csrf` before it reads the body (`:267`), so a 403 save had no effect; a 200, 400, 409, 422, 500 or 503 all spend the token.
- **Store.** `ui/src/store/useSettingsStore.ts`: `loadSnapshot` (`:110-132`) and `openSettings` (`:134-166`) skip the GET once `loaded` (`:111`, `:139-143`, BF-304). `applyDraft` (`:178-233`) sends `snapshot.csrf_token` (`:191`) and relies on `openSettings()` to refresh after a 200 (`:199`) and a 403 (`:223`); that call returns early, so the token stays spent. The early return also resets the draft (`:141`), so a 403 wipes it, and it sets `open: true` (`:138`), so a 200 re-opens a dialog closed during the save.
- **Reach.** A second save, a save corrected after a 422 (or any other answered status), or a first save more than 300 s after the page's config read: 403 until reload, draft wiped. Reproduced on `f7acb948` by the #1852 probe (2 passed, both asserting the defect).

## 2. Solution

- `SettingsState` gains `csrfFetchedAt: number` (Date.now() when `snapshot.csrf_token` was fetched; 0 = none or spent). `loadSnapshot` and `openSettings` stamp it on success.
- `applyDraft`: a module-private `applying` latch (one save at a time); before each POST, if the token is spent or `>= 240000` ms old, fetch a fresh snapshot (`_fetchSnapshot`) and stamp it; mark the token spent before the POST is sent; on a 403 at the first attempt, repeat once with a fresh token; any other answer ends it. No `openSettings()` call remains in `applyDraft`.
- A failed token read sends nothing, keeps the draft, says so, and leaves the token spent, so the next press reads first.
- Rejected heavier designs: change the router (multi-use or cookie tokens: a security-control change, out of scope); a shared fetch wrapper (one caller); a public `applying` state plus a disabled APPLY button (touches `SettingsTopBar.tsx` and every test reset helper; the latch is enough).

## 3. Decisions

- **D1 Refresh policy: refresh lazily at the start of APPLY.** Refresh when the token is spent or aged. Replace `snapshot` (whole) and `csrfFetchedAt`; nothing else (`draft`, `applyStatus`, `applyMessage`, `applyErrors`, `selectedSectionId`, `search`, `yamlOpen`, `open`, `loaded` are kept). Ranked alternatives:
  - (2) A forced GET after every answered POST (the issue's proposal). Rejected:
    - It still needs the APPLY-time age check and the failed-read path, so it adds a second refresh site.
    - It costs a GET after every save even when no second save follows.
    - After a 200 it brings an identical snapshot. The router snapshots and merges onto the live `runtime.config` (`config.py:234`, `:289-290`), which a save does not change before restart.
  - (3) Refresh only the token. Rejected: the GET returns the whole snapshot anyway. After a ProbOS restart, the new process's snapshot is the right one.
  - (4) Refresh on 200 and 403 only. Rejected: every answered status spends the token (`:263-265`).
  - **A failed GET** (non-ok or a throw):
    - The POST is not sent. `snapshot` is untouched and `csrfFetchedAt` stays 0.
    - `applyStatus: 'rejected'`, with `applyMessage` `Could not get a save token (<reason>); nothing was saved. Press APPLY to try again.`. `<reason>` is `config GET failed: <status>` or `config GET error: <err>`.
- **D2 The 403 policy: the store fetches a new token and resends the same patch once.** This is safe: the router answers 403 before reading the body (`:263-267`).
  - If the resend is answered, its answer sets the status as usual.
  - A second 403 gives `applyStatus: 'rejected'` and `applyMessage: 'Save token refused twice; nothing was saved. Press APPLY to try again.'`. The draft is kept and the token is left spent.
  - With D1 in place, a 403 means the server lost a live token: a ProbOS restart with the page still loaded, which a restart-required save invites, or a wall-clock jump. Asking the operator to press again would be a failure the store can repair safely.
  - One resend only: a second 403 on a token fetched moments earlier is not expiry, and looping would hide it.
  - Rejected: refresh and prompt the operator (the AD-741 spec at `prompts/archive/ad-741-settings-control-panel.md:432`; superseded here).
- **D3 Token age: refresh before sending at `>= 240000` ms by `Date.now()`, with the D2 resend as a backstop.** Ranked:
  - (1) Both: chosen.
  - (2) The 403 resend alone. It works, but every save after four idle minutes costs a refused POST, and it leans on the backstop for a predictable case.
  - (3) The age check alone. It does not cover a server restart.
  - Why 240 s: the client stamps the token when the GET answer arrives, after the server issued it. The 60 s margin covers the GET latency and the POST transit.
  - The clock source is `Date.now()`, as `openedAt` already uses (`:138`). Tests drive it with `vi.spyOn(Date, 'now')`.
- **D4 `openSettings` early return: unchanged.** Refreshing on open would cost a GET on every open and would still need D1, because the token ages while the dialog stays open. APPLY reads first, so the dialog never shows a state whose APPLY fails for the token.
- **D5 Concurrency: a module-private `let applying = false` latch.**
  - It is set synchronously before the first await and cleared in `finally`. A second press returns at once: no queue and no second POST.
  - The 200 branch no longer calls `openSettings()`. So a save no longer re-opens a dialog closed while it was in flight, and no longer bumps `openedAt`, which has no reader (Grep `openedAt` in `ui/src`: the store and four test reset helpers only). `closeSettings` needs no guard.
  - Rejected: an in-flight promise (no caller awaits the return; `SettingsTopBar.tsx`:80 ignores it) and a public `applying` field (see section 2).
- **D6 State shape: `csrfFetchedAt: number` is public in `SettingsState`.** Its initial value is 0, and it is stamped by `loadSnapshot`, `openSettings` and the APPLY refresh.
  - Public, so `getInitialState()` resets it and tests can observe it. Partial `setState` callers keep compiling, because `setState` takes a `Partial`.
  - A test that sets `snapshot` directly leaves `csrfFetchedAt` at 0, so its APPLY would read first. No such test calls `applyDraft`: Absence Verified, row 6.
  - Rejected: a second `csrfSpent` boolean (two fields for one fact) and a module-private stamp (test resets through `setState` would not reach it).
- **D7 Messages.** The 200, 422, 400, other-status and network-error texts are byte-unchanged; the 422 and 400 texts keep their U+2014. The 403 text is replaced and the refresh-failure text is new. New text is ASCII.

## 4. Milestones and commit subjects

| M | Files | Commit subject |
|---|---|---|
| M1 | `ui/src/store/useSettingsStore.ts`, new `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` | `the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (#1852)` |
| M2 | `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (generated) | `trackers and generated ledger for the HXI settings save token (#1852)` |

Subjects are ASCII and contain no AD- or BF- token. They contain no "close", "fix" or "resolve" substring.

## 5. Builder may / may not; Gates

**The Builder may:** rewrap a comment to the line length; nothing else beyond the pairs.

**The Builder may not:**
- touch `src/probos/routers/config.py`, `SettingsTopBar.tsx`, `SettingsPanel.tsx` or any other component;
- touch any existing test;
- change `CSRF_REFRESH_AFTER_MS`, the resend bound or any message text;
- add a dependency, an `any` (beyond the existing `{} as any`), an emoji, or a `hasattr`/`getattr`-style guard;
- re-add an `openSettings()` call to `applyDraft`.

**Hard stop (return to the Architect):** any measured number below differs, a census row survives, or `tsc -b` reports anything.

**Focused gates** (run in `ui/`; Python is `d:/ProbOS/.venv/Scripts/python.exe`, always with `-n 0`):
- **M1:** `npx tsc -b` clean, and the vitest command below with 10 files, 78 passed (the 66-test baseline plus 12):

```text
npx vitest run src/store/__tests__/useSettingsStore.bf999.test.tsx src/components/settings src/__tests__/IntentSurface.audioRender.test.tsx src/__tests__/MobileShell.test.tsx src/__tests__/CompactApp.sidebar-integration.test.tsx
```
- **M2:** `scripts/gen_ad_ledger.py --check`; `-m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **UI batch gates once on the candidate** (`run_test_gate.py` runs neither): `npx tsc -b`, then `npx vitest run` (0 failed).
- **Broad gate** once after M2: `scripts/run_test_gate.py --label 1852-bf999 --receipt logs/gates/1852-bf999.receipt.json`.

**A/B (measure):**
- The new file on the unrepaired `f7acb948` store: **12 cases, 10 failed, 2 passed**. The passing ones are guard rows T1 and T6.
  - Each red case fails at its first `expect(srv.posts).toEqual(...)`.
  - T4, T5, T7, T8: received `['t1']`.
  - T2, T3, T9, T10, T11, T12: received `['t1', 't1']`.
- The #1852 probe (`zzProbe1852.test.ts`) on the candidate: **2 failed**, both at `expect(srv.gets()).toBe(1)` (received 2).

## Verified Against Codebase (2026-11-26, tree `f7acb948`)

```
ui/src/store/useSettingsStore.ts (250 lines, read whole)
  1, 107, 211, 216, 221 contain U+2014; 41-68 SettingsState (56 openedAt); 70-81 _setNestedPath; 83 create<SettingsState>((set, get)
  96-98 initial applyErrors/applyMessage/openedAt; 110-132 loadSnapshot (111 guard; 120-128 set); 134-166 openSettings (138 open+openedAt; 139-143 early return, 141 draft reset; 152-162 set)
  168 closeSettings; 178-233 applyDraft (191 header; 196-206 200 branch, 199 openSettings(); 207-212 422; 213-217 400; 218-223 403, 223 openSettings(); 224-229 other; 230-232 catch)
src/probos/routers/config.py  50-52 _csrf_tokens, _CSRF_TTL_SECONDS = 300; 55-59 _gc_csrf (now - t > TTL); 62-66 _issue_csrf (monotonic); 69-71 _consume_csrf (pop)
  231-248 GET (234 runtime.config live; 247 csrf_token); 260-265 POST consumes first, 403 invalid_csrf; 267-270 body read after; 289-292 merge onto live config; 294-303 422; 305-307 503; 313-319 409
ui/src/components/settings/SettingsTopBar.tsx  13 applyDraft; 79-82 APPLY onClick={applyDraft} disabled={!dirty} testid settings-topbar-apply; 112-141 settings-restart-banner; 176-179 settings-status-message
ui/src/components/settings/SettingsPanel.tsx  13-17 renders only when open; 35 SettingsTopBar; 46 SettingsStatusBar
ui/src/components/settings/__tests__/SettingsPanel.test.tsx  77-95 reset (no csrfFetchedAt); 192-218 APPLY 200 case (every GET answers token fake-token-abc)
ui/src/__tests__/CompactApp.sidebar-integration.test.tsx:28-33, ui/src/__tests__/MobileShell.test.tsx:15-20  untyped vi.mock factories (snapshot, loadSnapshot only)
setState callers are Partial, `as any` or getInitialState(): ApprovalWave.test.tsx:64, IntentSurface.audioRender.test.tsx:68-71, LiveToolProgress.test.tsx:35,43, liveToolProgress.shells.test.tsx:102, Artifact.ad1074c.test.tsx:378, ConnectPhoneCard.test.tsx:18
ui/tsconfig.json:13-16,21 (react-jsx, strict, noUnused* false, include src); ui/vitest.config.ts:7,9,15 (jsdom, setup, e2e excluded); ui/package.json:32,46 zustand ^5, vitest ^4.1.0
ui/src/test/setup.ts:26-30 resets no settings state
scripts/gen_ad_ledger.py:126-139 status words in a 120-char head; 217-220 a DECISIONS heading with no status word = shipped
docs/development/open-ads-report.md:32 BF-998 / next BF-999; :53 shipped BF 638; :150 BF list ends 980-998
PROGRESS.md:1 "# ProbOS Progress"; DECISIONS.md:13 BF-997 / BF-998 heading (top entry)
```

## Absence Verified (2026-11-26)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Only the store sends `X-Probos-CSRF` from the UI | Grep `X-Probos-CSRF` over the repo (node_modules excluded) | `useSettingsStore.ts:191`, `SettingsPanel.test.tsx:196`; the rest are Python tests and prompts | yes |
| Only the store reads `csrf_token` in UI source | Grep `csrf\|CSRF` in `ui/src` | `useSettingsStore.ts:32,191,197,221`; the rest are test fixtures | yes |
| No other UI code reads or posts `/api/config` | Grep `/api/config` in `ui/src` excluding `__tests__` | store `:114,:146,:187,:241` (yaml); `AgentProfilePanel.tsx`:171 `/api/config/avatars-enabled` (served by `routers/system.py:960`, issues no token) | yes |
| Only `config.py` issues or spends tokens | Grep `_issue_csrf\|_consume_csrf\|_csrf_tokens\|_CSRF_TTL` in `*.py` | `config.py` only | yes |
| No test or script reads the store's messages | Grep `CSRF token expired\|re-opening Settings\|Restart required to take effect\|Validation failed` (prompts excluded) | the store only (plus unrelated Python `Validation failed` strings) | yes |
| `applyDraft` has one production caller and one existing test caller | Grep `applyDraft` in `ui/src` | `SettingsTopBar.tsx`:13,80; `SettingsPanel.test.tsx:211` (opens through `openSettings`) | yes |
| No `?raw` or `readFileSync` of the store; no Python or script reader | Grep `useSettingsStore[^'"]*\?raw\|store/useSettingsStore\.ts` in `ui/`; Grep `useSettingsStore` in `tests/` and `scripts/` | none; none | yes |
| `openedAt` has no reader | Grep `openedAt` in `ui/src` | store `:56,:98,:138`; four test reset helpers | yes |

## Prior Art and Blind Spots

- **External:**
  - The OWASP CSRF Prevention Cheat Sheet ranks per-request tokens as stronger than per-session tokens, at a known usability cost: a page can hold a token that is no longer valid. This is that cost.
  - Adopted: the per-request scheme stays, and the client fetches a token before each state-changing request. https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
  - `docs/research/reference-projects.md` has no CSRF, zustand or HXI row (Grep: 0). No overdue project applies.
- **Blind spots:**
  1. The wall clock (`Date.now`) and the router's monotonic clock can disagree after a sleep or a clock change; D2's resend covers it (review property R-6).
  2. A field edited while a save is in flight is still cleared by that save's 200 (unchanged behaviour).
  3. The APPLY button is not disabled during a save. A second press does nothing (D5). Considered, deferred.
  4. BF-996's 409 `config_unreadable` takes the generic branch and spends the token like any status; covered by D1.

## 6. Pairs

### 6.1 `ui/src/store/useSettingsStore.ts` (M1) -- run with `--utf8 U+2014` (P-6 SEARCH holds three U+2014, its REPLACE two, both in unchanged lines)

**P-1**
SEARCH:
```
  cursor[parts[parts.length - 1]] = value;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
```
REPLACE:
```
  cursor[parts[parts.length - 1]] = value;
}

// BF-999 (#1852): GET /api/config issues a single-use CSRF token that lives 300 s, and every
// POST /api/config spends it before reading the body (src/probos/routers/config.py). A save
// fetches a fresh token first when the last one was spent or is older than this margin.
const CSRF_REFRESH_AFTER_MS = 240000;

// BF-999: one save at a time; a press while a save is in flight sends nothing.
let applying = false;

async function _fetchSnapshot(): Promise<ConfigSnapshot | string> {
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) return `config GET failed: ${resp.status}`;
    return (await resp.json()) as ConfigSnapshot;
  } catch (err) {
    return `config GET error: ${String(err)}`;
  }
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
```

**P-2**
SEARCH:
```
  applyMessage: string;
  openedAt: number;

  loadSnapshot: () => Promise<void>;
```
REPLACE:
```
  applyMessage: string;
  openedAt: number;
  /** BF-999: Date.now() when snapshot.csrf_token was fetched; 0 when none was or a POST spent it. */
  csrfFetchedAt: number;

  loadSnapshot: () => Promise<void>;
```

**P-3**
SEARCH:
```
  applyErrors: [],
  applyMessage: '',
  openedAt: 0,
```
REPLACE:
```
  applyErrors: [],
  applyMessage: '',
  openedAt: 0,
  csrfFetchedAt: 0,
```

**P-4** (loadSnapshot)
SEARCH:
```
        loading: false,
        loaded: true,
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        applyStatus: 'idle',
```
REPLACE:
```
        loading: false,
        loaded: true,
        csrfFetchedAt: Date.now(),
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        applyStatus: 'idle',
```

**P-5** (openSettings)
SEARCH:
```
        loaded: true,
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        draft: {},
        draftCount: 0,
```
REPLACE:
```
        loaded: true,
        csrfFetchedAt: Date.now(),
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        draft: {},
        draftCount: 0,
```

**P-6** (applyDraft; contains U+2014)
SEARCH:
```
  applyDraft: async () => {
    const { draft, snapshot } = get();
    if (!snapshot) return;
    // Reshape the flat dot-keyed draft into a nested patch dict.
    const patch: Record<string, any> = {};
    for (const [path, value] of Object.entries(draft)) {
      _setNestedPath(patch, path, value);
    }
    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Probos-CSRF': snapshot.csrf_token,
        },
        body: JSON.stringify({ patch }),
      });
      const body = await resp.json().catch(() => ({} as any));
      if (resp.status === 200) {
        // Refresh snapshot to get a fresh CSRF token; THEN set the
        // restart-required status so it survives the re-open call.
        await get().openSettings();
        set({
          applyStatus: 'restart_required',
          applyMessage: 'Restart required to take effect.',
          applyErrors: [],
          draft: {},
          draftCount: 0,
        });
      } else if (resp.status === 422) {
        set({
          applyStatus: 'rejected',
          applyErrors: body.errors ?? [],
          applyMessage: 'Validation failed — see field errors below.',
        });
      } else if (resp.status === 400 && body.error === 'secret_field_readonly') {
        set({
          applyStatus: 'rejected',
          applyMessage: 'Secret fields are read-only here — edit system.yaml directly.',
        });
      } else if (resp.status === 403) {
        set({
          applyStatus: 'rejected',
          applyMessage: 'CSRF token expired — re-opening Settings.',
        });
        await get().openSettings();
      } else {
        set({
          applyStatus: 'rejected',
          applyMessage: `APPLY failed (${resp.status}): ${body.error ?? 'unknown'}`,
        });
      }
    } catch (err) {
      set({ applyStatus: 'rejected', applyMessage: `APPLY error: ${String(err)}` });
    }
  },
```
REPLACE:
```
  applyDraft: async () => {
    if (applying || !get().snapshot) return;
    applying = true;
    try {
      // Reshape the flat dot-keyed draft into a nested patch dict.
      const patch: Record<string, any> = {};
      for (const [path, value] of Object.entries(get().draft)) {
        _setNestedPath(patch, path, value);
      }
      // BF-999: the router answers 403 before it reads the body, so a refused save had no
      // effect; fetch a new token and send the same patch once more. Any other answer ends it.
      for (let attempt = 0; attempt < 2; attempt++) {
        const fetchedAt = get().csrfFetchedAt;
        if (!fetchedAt || Date.now() - fetchedAt >= CSRF_REFRESH_AFTER_MS) {
          const fresh = await _fetchSnapshot();
          if (typeof fresh === 'string') {
            set({
              applyStatus: 'rejected',
              applyMessage: `Could not get a save token (${fresh}); nothing was saved. Press APPLY to try again.`,
            });
            return;
          }
          set({ snapshot: fresh, csrfFetchedAt: Date.now() });
        }
        const token = get().snapshot?.csrf_token ?? '';
        // Every POST the router answers spends the token, whatever the status.
        set({ csrfFetchedAt: 0 });
        const resp = await fetch('/api/config', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Probos-CSRF': token,
          },
          body: JSON.stringify({ patch }),
        });
        const body = await resp.json().catch(() => ({} as any));
        if (resp.status === 403 && attempt === 0) continue;
        if (resp.status === 200) {
          set({
            applyStatus: 'restart_required',
            applyMessage: 'Restart required to take effect.',
            applyErrors: [],
            draft: {},
            draftCount: 0,
          });
        } else if (resp.status === 422) {
          set({
            applyStatus: 'rejected',
            applyErrors: body.errors ?? [],
            applyMessage: 'Validation failed — see field errors below.',
          });
        } else if (resp.status === 400 && body.error === 'secret_field_readonly') {
          set({
            applyStatus: 'rejected',
            applyMessage: 'Secret fields are read-only here — edit system.yaml directly.',
          });
        } else if (resp.status === 403) {
          set({
            applyStatus: 'rejected',
            applyMessage: 'Save token refused twice; nothing was saved. Press APPLY to try again.',
          });
        } else {
          set({
            applyStatus: 'rejected',
            applyMessage: `APPLY failed (${resp.status}): ${body.error ?? 'unknown'}`,
          });
        }
        return;
      }
    } catch (err) {
      set({ applyStatus: 'rejected', applyMessage: `APPLY error: ${String(err)}` });
    } finally {
      applying = false;
    }
  },
```

### 6.2 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` new file (M1)

```tsx
// BF-999 (#1852): the HXI settings store fetches a fresh single-use CSRF token before a save
// whenever the last one was spent by a POST or is 240 s old, sends a save the router refused
// with 403 once more, and keeps the draft on every refused save. Real useSettingsStore and the
// real SettingsPanel; fetch is a double that behaves like src/probos/routers/config.py: one
// token per GET, every POST spends the token it carries before the body is read, a token older
// than 300 s is refused, and a 403 is answered before the body is read.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsPanel from '../../components/settings/SettingsPanel';
import { useSettingsStore } from '../useSettingsStore';

const TOKEN_LIFETIME_MS = 300000; // routers/config.py _CSRF_TTL_SECONDS

const SNAPSHOT = {
  config: { system: { name: 'ProbOS', log_level: 'INFO' } },
  secret_present: {},
  sections: [
    {
      section_id: 'system',
      label: 'System',
      glyph: '*',
      domain: 'Core',
      description: 'Process identity and global log level.',
      fields: [
        { field_id: 'system.name', label: 'Process name', kind: 'text', enum_values: [], description: '', hot_reload: false },
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: ['INFO', 'DEBUG', 'BAD'], description: '', hot_reload: false },
      ],
    },
  ],
  domain_counts: { Core: 1 },
  domain_order: ['Core'],
  section_count: 1,
  config_path: '/tmp/system.yaml',
  uptime_seconds: 1,
};

function jsonResp(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

interface ServerDouble {
  gets: number; // every GET /api/config, answered or not
  posts: string[]; // the token each POST carried, in arrival order
  patches: unknown[]; // the patch each POST carried, in arrival order
  saved: string[]; // system.log_level of each save answered 200
  failNextGet: 'none' | 'status' | 'throw';
  refuseEveryPost: boolean;
  restart: () => void; // the server forgets every token it issued
  hold: () => () => void; // POSTs wait until the returned release() is called
}

function installServer(): ServerDouble {
  let issued = 0;
  const live = new Map<string, number>();
  let gate: Promise<void> | null = null;
  const srv: ServerDouble = {
    gets: 0,
    posts: [],
    patches: [],
    saved: [],
    failNextGet: 'none',
    refuseEveryPost: false,
    restart: () => live.clear(),
    hold: () => {
      let release: () => void = () => {};
      gate = new Promise<void>((resolve) => { release = resolve; });
      return () => { gate = null; release(); };
    },
  };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) !== '/api/config') throw new Error(`unexpected request ${String(input)}`);
    if (init?.method === 'POST') {
      const token = (init.headers as Record<string, string>)['X-Probos-CSRF'];
      const patch = JSON.parse(String(init.body)).patch;
      srv.posts.push(token);
      srv.patches.push(patch);
      const wait = gate;
      if (wait) await wait;
      // _consume_csrf pops the token; an unknown or expired one is a 403 before the body is read.
      const issuedAt = live.get(token);
      live.delete(token);
      if (srv.refuseEveryPost || issuedAt === undefined || Date.now() - issuedAt > TOKEN_LIFETIME_MS) {
        return jsonResp({ error: 'invalid_csrf' }, 403);
      }
      const level = patch?.system?.log_level;
      if (level === 'BAD') {
        return jsonResp({
          error: 'validation_failed',
          errors: [{ loc: ['system', 'log_level'], msg: 'Input should be INFO or DEBUG', type: 'enum' }],
        }, 422);
      }
      srv.saved.push(level);
      return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
    }
    srv.gets += 1;
    const failure = srv.failNextGet;
    srv.failNextGet = 'none';
    if (failure === 'status') return jsonResp({ error: 'unavailable' }, 503);
    if (failure === 'throw') throw new TypeError('network down');
    issued += 1;
    const token = `t${issued}`;
    live.set(token, Date.now());
    return jsonResp({ ...SNAPSHOT, csrf_token: token });
  });
  return srv;
}

const s = () => useSettingsStore.getState();

async function save(fields: Record<string, string>): Promise<void> {
  for (const [id, value] of Object.entries(fields)) s().setDraftField(id, value);
  await s().applyDraft();
}

describe('BF-999 the settings store holds a live CSRF token for every save (#1852)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });

  it('the first save sends the token the page mount read was issued', async () => {
    const srv = installServer();
    await s().loadSnapshot(); // App.tsx and CompactApp.tsx on mount
    await s().openSettings(); // loaded: no second read
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(['t1']);
    expect(srv.gets).toBe(1);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
  });

  it('two saves in one page session each send a fresh token', async () => {
    const srv = installServer();
    await s().openSettings();
    await save({ 'system.log_level': 'DEBUG' });
    s().closeSettings();
    await s().openSettings();
    await save({ 'system.log_level': 'INFO' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(2);
    expect(srv.saved).toEqual(['DEBUG', 'INFO']);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe('Restart required to take effect.');
  });

  it('a save refused by validation keeps the draft, and the corrected save sends every field with a fresh token', async () => {
    const srv = installServer();
    await s().openSettings();
    await save({ 'system.name': 'Vessel', 'system.log_level': 'BAD' });
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyErrors).toHaveLength(1);
    expect(s().draft).toEqual({ 'system.name': 'Vessel', 'system.log_level': 'BAD' });
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.patches[1]).toEqual({ system: { name: 'Vessel', log_level: 'DEBUG' } });
    expect(srv.gets).toBe(2);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyErrors).toEqual([]);
  });

  it('a save refused with 403 is sent once more with a fresh token and succeeds', async () => {
    const srv = installServer();
    await s().openSettings();
    srv.restart(); // the token the dialog holds is gone, as after a ProbOS restart with the page loaded
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(2);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe('Restart required to take effect.');
  });

  it('a second 403 stops after one resend, keeps the draft, and the next press reads first', async () => {
    const srv = installServer();
    await s().openSettings();
    srv.refuseEveryPost = true;
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(2);
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyMessage).toBe('Save token refused twice; nothing was saved. Press APPLY to try again.');
    expect(s().draft).toEqual({ 'system.log_level': 'DEBUG' });
    expect(s().draftCount).toBe(1);
    srv.refuseEveryPost = false;
    await s().applyDraft();
    expect(srv.posts).toEqual(['t1', 't2', 't3']);
    expect(srv.gets).toBe(3);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
  });

  it.each([
    { label: '239.999 s old is sent as it is', ageMs: 239999, posts: ['t1'], gets: 1 },
    { label: '240 s old is replaced before use', ageMs: 240000, posts: ['t2'], gets: 2 },
    { label: 'past the router lifetime of 300 s is replaced before use', ageMs: 301000, posts: ['t2'], gets: 2 },
  ])('a token $label', async ({ ageMs, posts, gets }) => {
    let now = 1000000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const srv = installServer();
    await s().openSettings();
    now += ageMs;
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(posts);
    expect(srv.gets).toBe(gets);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
  });

  it.each([
    { label: 'answers 503', mode: 'status' as const, reason: 'config GET failed: 503' },
    { label: 'throws', mode: 'throw' as const, reason: 'config GET error: TypeError: network down' },
  ])('a token read that $label sends no save, keeps the draft, and the next press reads first', async ({ mode, reason }) => {
    const srv = installServer();
    await s().openSettings();
    await save({ 'system.log_level': 'DEBUG' });
    srv.failNextGet = mode;
    await save({ 'system.log_level': 'INFO' });
    expect(srv.posts).toEqual(['t1']);
    expect(srv.gets).toBe(2);
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyMessage).toBe(`Could not get a save token (${reason}); nothing was saved. Press APPLY to try again.`);
    expect(s().draft).toEqual({ 'system.log_level': 'INFO' });
    await s().applyDraft();
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(3);
    expect(srv.saved).toEqual(['DEBUG', 'INFO']);
    expect(s().applyStatus).toBe('restart_required');
  });

  it('a second press while a save is in flight sends nothing, and closing the dialog meanwhile leaves it closed', async () => {
    const srv = installServer();
    await s().openSettings();
    s().setDraftField('system.log_level', 'DEBUG');
    const release = srv.hold();
    const first = s().applyDraft();
    const second = s().applyDraft();
    s().closeSettings();
    release();
    await Promise.all([first, second]);
    expect(srv.posts).toEqual(['t1']);
    expect(srv.gets).toBe(1);
    expect(s().open).toBe(false);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
  });

  it('two APPLY clicks in the Settings dialog both save, each with its own token', async () => {
    const srv = installServer();
    await act(async () => { await s().openSettings(); });
    render(<SettingsPanel />);
    act(() => { s().setDraftField('system.log_level', 'DEBUG'); });
    fireEvent.click(screen.getByTestId('settings-topbar-apply'));
    await waitFor(() => expect(s().draftCount).toBe(0));
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
    act(() => { s().setDraftField('system.log_level', 'INFO'); });
    fireEvent.click(screen.getByTestId('settings-topbar-apply'));
    await waitFor(() => expect(s().draftCount).toBe(0));
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.saved).toEqual(['DEBUG', 'INFO']);
    await waitFor(() =>
      expect(screen.getByTestId('settings-status-message').textContent).toBe('Restart required to take effect.'),
    );
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
  });
});
```

Case key for sections 5 and 7: T1 to T5 are the five single `it`s in order; T6, T7 and T8 are the three age rows; T9 and T10 are the two failed-read rows (503, throws); T11 is the in-flight case; T12 is the dialog case.

### 6.3 `PROGRESS.md` (M2)

**P-1**
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-999 (2026-11-26), #1852 -- the HXI settings store fetches a fresh CSRF token before each save, sends a save refused with 403 once more, and keeps the draft.** The router issues one single-use CSRF token per `GET /api/config`, lets it live 300 s and spends it on every `POST /api/config` before it reads the body. The store fetched one token per page load (`openSettings` and `loadSnapshot` skip the read once loaded, BF-304), so a second save, a save corrected after a 422, or a first save more than 300 s after the page's config read was answered 403 `invalid_csrf` until a reload, and the 403 path wiped the draft. `useSettingsStore` now records when its token was fetched (`csrfFetchedAt`), treats it as spent once a POST carries it, and before each save fetches a fresh snapshot and token when the last is spent or 240 s old. A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again." and the draft kept. A failed token read sends nothing, keeps the draft and says so, and the next press reads first. One save runs at a time, and a save no longer re-opens a dialog closed while it was in flight. `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (12 cases) drives the real store and the real `SettingsPanel` against a fetch double that behaves like the router; 10 are red on the unrepaired store. The router is unchanged. Mutation census: 19 of 19 killed (rows S-M1 to S-M19), run once on the overlay of f7acb948. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`.
```

### 6.4 `DECISIONS.md` (M2; anchored on the top heading)

**P-1**
SEARCH:
```
### BF-997 / BF-998 -- #1414 Batch B: the HXI event stream past 100 work items, dropped work-state frames, a refused notification read (2026-11-25, #1414)
```
REPLACE:
```
### BF-999 -- the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (2026-11-26, #1852)

- *Scope.* `ui/src/store/useSettingsStore.ts` (`applyDraft`, `csrfFetchedAt`, `_fetchSnapshot`); test `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx`. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`. The router (`src/probos/routers/config.py`) and its CSRF scheme are unchanged.
- *D1.* The token is refreshed lazily, at the start of a save, when it is spent or aged; the refresh replaces the snapshot and its fetch time only, keeping the draft and every view field. Rejected: a forced read after every answered save (it still needs the save-time age check, costs a read after every save, and brings an identical snapshot, because the router snapshots the live config a save does not change before restart).
- *D2.* A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends the save with the draft kept. This supersedes the AD-741 spec's "re-fetch config to refresh token, prompt operator to re-apply" (`prompts/archive/ad-741-settings-control-panel.md:432`).
- *D3.* A token is replaced before use at 240 s by `Date.now()`, 60 s inside the router's 300 s lifetime; D2's resend covers a server restart and a wall-clock jump.
- *D4.* `openSettings` keeps its early return; reading on every open would still need D1's save-time check.
- *D5.* One save at a time: a module-private latch set before the first await and cleared in `finally`. A save no longer calls `openSettings`, so it never re-opens a dialog closed while it was in flight.
- *D6.* `csrfFetchedAt` is public state (0 = none or spent) so the store's initial state resets it.
- *Reversal.* Revert the commit; no API, persisted format or security control changes.

### BF-997 / BF-998 -- #1414 Batch B: the HXI event stream past 100 work items, dropped work-state frames, a refused notification read (2026-11-25, #1414)
```

## 7. Mutation census and generated-artifact commands

Each mutant is applied to the M1 candidate's store. Runner: `npx vitest run src/store/__tests__/useSettingsStore.bf999.test.tsx src/components/settings/__tests__/SettingsPanel.test.tsx`. Single-line mutants are written `from -> to`; whole lines, with their indentation.

| Row | Mutant | Killer (vitest), first failing assertion |
|---|---|---|
| S-M1 | `    if (applying \|\| !get().snapshot) return;` -> `    if (!get().snapshot) return;` | T11 (posts `['t1','t2']`) |
| S-M2 | `      applying = false;` -> `      // applying = false;` | T2 (posts `['t1']`); every later case in the file fails too |
| S-M3 | `        set({ csrfFetchedAt: 0 });` -> `        // set({ csrfFetchedAt: 0 });` | T2 (posts `['t1','t1','t2']`), T3, T9, T10, T12 |
| S-M4 | delete `        csrfFetchedAt: Date.now(),` in loadSnapshot (pair below) | T1 (posts `['t2']`) |
| S-M5 | delete `        csrfFetchedAt: Date.now(),` in openSettings (pair below) | T2 (posts `['t2','t3']`) |
| S-M6 | `        if (!fetchedAt \|\| Date.now() - fetchedAt >= CSRF_REFRESH_AFTER_MS) {` -> `        if (!fetchedAt) {` | T7 (posts `['t1']`), T8 (posts `['t1','t2']`) |
| S-M7 | the same line with `>=` -> `>` | T7 |
| S-M8 | `const CSRF_REFRESH_AFTER_MS = 240000;` -> `... = 300000;` | T7 |
| S-M9 | `const CSRF_REFRESH_AFTER_MS = 240000;` -> `... = 200000;` | T6 (posts `['t2']`) |
| S-M10 | the S-M6 line -> `        if (true) {` | T1 (posts `['t2']`), T6 |
| S-M11 | `        if (resp.status === 403 && attempt === 0) continue;` -> `        // if (resp.status === 403 && attempt === 0) continue;` | T4 (posts `['t1']`) |
| S-M12 | two edits: `      for (let attempt = 0; attempt < 2; attempt++) {` -> `< 3`, and `attempt === 0) continue;` -> `attempt < 2) continue;` in the S-M11 line | T5 (posts `['t1','t2','t3']`) |
| S-M13 | the S-M11 line -> `        if (attempt === 0) continue;` | T1 (posts `['t1','t2']`) |
| S-M14 | `          if (typeof fresh === 'string') {` -> `          if (typeof fresh === 'number') {` (tsc refuses it; vitest does not type-check) | T9, T10 (posts `['t1','','t2']`) |
| S-M15 | `              applyStatus: 'rejected',` (14 spaces, the refresh-failure set) -> that line plus `              csrfFetchedAt: Date.now(),` | T9, T10 (second posts assertion: `['t1','t1','t2']`) |
| S-M16 | the final 403 branch re-opens (pair below) | T5 (draft `{}`) |
| S-M17 | `        if (resp.status === 200) {` -> that line plus `          await get().openSettings();` | T11 (`open` true) |
| S-M18 | `          set({ snapshot: fresh, csrfFetchedAt: Date.now() });` -> `          set({ snapshot: fresh, csrfFetchedAt: Date.now(), draft: {}, draftCount: 0 });` | T5 (draft `{}`) |
| S-M19 | the same line -> `          set({ csrfFetchedAt: Date.now() });` | T2 (posts `['t1','t1','t1']`) |

Multi-line mutant pairs:
- S-M4 SEARCH `        loaded: true,` / `        csrfFetchedAt: Date.now(),` / `        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',` / `        applyStatus: 'idle',` -> the same without the second line.
- S-M5 SEARCH `        loaded: true,` / `        csrfFetchedAt: Date.now(),` / `        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',` / `        draft: {},` -> the same without the second line.
- S-M16 SEARCH `            applyMessage: 'Save token refused twice; nothing was saved. Press APPLY to try again.',` / `          });` -> those two lines plus `          await get().openSettings();`.

Equivalent mutants, so not census rows:
- the loop bound `< 3` alone (the `attempt === 0` resend condition already bounds it);
- moving the spent mark after the response (with the latch in place, a token reused after a network error is either still live or draws one 403 and the resend).

Review property R-6 covers the clock.

Guard: `SettingsPanel.test.tsx` "APPLY POSTs the patch with CSRF header and shows restart banner on 200" stays green on the candidate.

**Generated artifacts at M2** (interpreter `d:/ProbOS/.venv/Scripts/python.exe`):
1. Apply 6.3 and 6.4.
2. Run `scripts/gen_ad_ledger.py`. Expected:
   - BF-999 shows as shipped through the `DECISIONS.md` heading;
   - shipped BF goes from 638 to 639 and the BF list ends `980-999` (`open-ads-report.md:53,150`);
   - the Ceilings row reads BF-999 / next **BF-1000** / highest with code BF-999;
   - the AD counts are unchanged (AD-1361 / next AD-1362).
3. Run `scripts/gen_ad_ledger.py --check`, then `-m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

**These artifacts do not move:** `architecture-baseline.yaml`, the config facade baseline, the config reference and profiles, the event-type tables, the route inventory and `file_durations.json`. No Python file, config field, EventType or route changes.

**Pin census:**

| Path | Readers | Pins |
|---|---|---|
| `ui/src/store/useSettingsStore.ts` | consumers: `SettingsTopBar.tsx`:13,80 (`applyDraft`), `SettingsPanel`, `SettingsMain`, `SettingsSidebar`, `PerceptionLivePanel`, `App.tsx`, `CompactApp.tsx`, `MobileShell.tsx`, `deepLinkView.ts:83`, `stations.tsx:204`. Tests: two untyped `vi.mock` factories; Partial or `as any` `setState` callers; `getInitialState()` users | none (no `?raw`, no Python or script reader) |
| new test file | none | none |
| `PROGRESS.md`, `DECISIONS.md` | `scripts/gen_ad_ledger.py` | ledger pair, regenerated |
| ledger pair | `tests/test_ad1184_ad_ledger.py`, preflight `ad-ledger` | regenerated at M2 |

## 8. Diff Reviewer brief and #1852 landing comment

**Consumer that must accept it:** the Settings dialog: `SettingsTopBar.tsx`:79-82 (APPLY calls `applyDraft`), `:112-141` (banner) and `:147-182` (status message), mounted by `SettingsPanel.tsx`. Contract it must honour: `routers/config.py:50-71, 247, 263-267`.
- **R-1 Token contract.** The router is byte-unchanged. No POST carries a token the store knows an earlier POST carried: `csrfFetchedAt` is set to 0 before `fetch` is called. A token is used only while `Date.now() - csrfFetchedAt < 240000`.
- **R-2 Draft kept on refusal.** Only the 200 branch clears `draft`/`draftCount`. The draft is kept on a 403 (both), 422, 400, other statuses, a thrown POST and a failed token read. `applyDraft` contains no `openSettings()` call.
- **R-3 No double POST.** `applying` is set before the first `await` and cleared in `finally`, which runs after every `return` inside `try`.
- **R-4 Bounded.** At most two GETs and two POSTs per press. The resend happens only on a 403 at attempt 0. No recursion and no timer.
- **R-5 What a refresh touches.** It sets `snapshot` and `csrfFetchedAt` only. `loadSnapshot` and `openSettings` change only by stamping `csrfFetchedAt` on success.
- **R-6 Clock.** `Date.now()` is used for both the stamp and the check. A wall-clock jump against the router's monotonic clock is handled by the one resend. This property is untested.
- **R-7 Types and style.**
  - `csrfFetchedAt` is in `SettingsState` and in the initial state, and `npx tsc -b` is clean.
  - No new dependency and no new `any`; new text is ASCII.
  - U+2014 remains only in the unchanged 422 and 400 messages and the untouched lines 1 and 107.
  - No token value appears in any message.
- **R-8 No other readers.** No `?raw` reader, no Python test touched, and `tests/test_ad741_config_api.py` is unchanged. The settings vitest set and the full `npx vitest run` are green.
- **R-9 Tests cross the seam.**
  - T12 clicks the real APPLY twice in one session.
  - The double consumes before it reads the body and refuses at `> 300000` ms, as the router does.
  - Every red case is red on `f7acb948` at its posts assertion (section 5).

**#1852 landing comment:**

```
Shipped in <PR #...> (<sha>), gated by <receipt path, receipt sha>.

BF-999. The HXI settings store (ui/src/store/useSettingsStore.ts) now:
- records when its CSRF token was fetched and treats it as spent once a POST carries it;
- before each save, fetches a fresh snapshot and token when the last was spent or is 240 s old (60 s inside the router's 300 s lifetime);
- on a 403 (answered before the router reads the body, so that save had no effect) fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again.";
- keeps the draft on every refused save (403, 422, 400, other statuses, a network error, a failed token read); only a 200 clears it;
- runs one save at a time, and no longer re-opens a dialog closed while a save was in flight.
The router and its CSRF scheme are unchanged.

Proof: ui/src/store/__tests__/useSettingsStore.bf999.test.tsx, 12 cases with the real store and the real SettingsPanel (two APPLY clicks in one page session) against a fetch double that behaves like src/probos/routers/config.py (a token per GET, spent by every POST before the body is read, refused after 300 s). On the unrepaired store 10 of 12 fail and the 2 guard cases pass; the two probe cases in this issue's body, which assert the defect, fail on the repair. Mutation census 19 of 19 killed.

Not covered: no browser run. Date.now() can disagree with the router's monotonic clock after a sleep or clock change; the single resend covers that case. A field edited while a save is in flight is still cleared by that save's 200 (unchanged). The APPLY button is not disabled during a save; a second press does nothing.
```

## 9. Orchestrator re-proof (2026-11-26)

Measured on the oracle tree `oc1` (main `f7acb948`, tree `f12fe25c`, `npm ci` run in `ui/`) after the Architect's draft. Every prediction of sections 5 and 7 held; the only change is the formatting of C-1 to C-3.

- Pairs: the six store pairs, the new file, the `PROGRESS.md` pair and the `DECISIONS.md` pair apply, each SEARCH occurring once at its turn. The store keeps CRLF throughout (292 lines after the pairs).
- A/B: the new file alone on the unchanged `f7acb948` store gives 12 cases, 10 failed, 2 passed (T1 and T6). Each red case fails at its first `expect(srv.posts).toEqual(...)`: T2, T3, T9, T10, T11 and T12 received `['t1', 't1']`; T4, T5, T7 and T8 received `['t1']`.
- Candidate: the new file passes 12 of 12; the M1 focused list gives 10 files, 78 passed; `npx tsc -b` prints nothing and exits 0.
- The #1852 probe (two cases that assert the defect) passes on `f7acb948` and fails both cases on the candidate, at `expect(srv.gets()).toBe(1)` with received 2.
- Census (runner `mutants_bf999.py`, vitest on the new file and `SettingsPanel.test.tsx`, 19 cases on the unmutated candidate, all passing): rows S-M1 to S-M19 are all killed and no row survives. Every killer the table names fails. Twelve rows fail exactly their named killers; S-M2 (11 cases), S-M3 (7), S-M5 (9), S-M10 (10), S-M11 (2: T4 and T5), S-M13 (11) and S-M19 (9) fail more. The store is restored byte for byte after every row.
- M2: `scripts/gen_ad_ledger.py` moves the shipped BF count from 638 to 639 and the Ceilings row to BF-999 / next BF-1000 / highest with code BF-999; the AD counts do not move. `--check` reports the ledger current and `tests/test_ad1184_ad_ledger.py` gives 33 passed. The pair also carries the generator's date and head cells, so the real tree regenerates it and the oracle's copy is not committed.
- Gate preflight on the staged oracle (`scripts/run_test_gate.py --preflight-only`): exit 0. Its seven `--check` scripts (config reference, config profiles, config facade, AD ledger, seam contracts, architecture principles, store registry), `compileall` and the prompt scan all pass.

Orchestrator corrections C-1 to C-3 (prose only; no pair text changes). The preflight's prompt scan (`scripts/phantom-api-precheck.ps1`) first failed with 3 phantom symbols: it reads a file name with a line number inside one code span (the settings top bar, the agent profile panel) and the sidebar-integration test file named in the inline vitest command as `<Class>.<method>` symbols. It masks a code span only when the closing backtick follows the file name at once, and it skips fenced blocks that are not python. So the line numbers now follow a closed code span, and the M1 vitest command is a fenced `text` block. The scan is clean.
