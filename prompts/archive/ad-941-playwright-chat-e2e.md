# AD-941 — Playwright e2e regression harness for the chat collaboration UX

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-941.** Builds on AD-938/939/940 (local).
**Mode:** Builder. Frontend test infrastructure. Commit local. No push.

## Goal
Stand up a Playwright end-to-end harness (none exists) with regression specs covering the four
Captain-reported chat-UX issues that the mocked-store Vitest suite missed — the integration layer where the
real store + real components + real routing interact. Deterministic, backend-free, CI-friendly.

## Design (deterministic, no backend, no live-data mutation)
- Run against **`vite dev`** (NOT preview): the store exposes a test seam `window.__store = useStore` under
  `import.meta.env.DEV` (verified `ui/src/store/useStore.ts:2654`). Preview is a prod build where DEV is
  false, so the seam is absent — use `npm run dev`.
- **Seed store state directly** via `page.evaluate` + `window.__store.setState(...)` (crew `agents`,
  `chatThreads`, `chatsOpen`, etc.). `Map`s can't cross `page.evaluate` as Maps — pass plain arrays and build
  the `Map` INSIDE the evaluate: `page.evaluate((arr)=>{ (window).__store.setState({ agents: new Map(arr) }); }, arr)`.
- **Mock the REST surface** with `page.route('**/api/**', ...)` (catch-all + specific handlers) so no backend
  is needed: `GET /api/threads`, `GET /api/threads/*/messages`, `POST /api/threads`,
  `POST /api/threads/*/messages`, `PATCH /api/threads/*`, `POST /api/threads/*/participants`, and a catch-all
  that fulfils `{}` for anything else (avatar-telemetry WS failures are already tolerated).

## Files

### 1. `ui/package.json` — devDep + script
- Add `@playwright/test` to `devDependencies` (install: `npm i -D @playwright/test` then
  `npx playwright install chromium`).
- Add scripts: `"test:e2e": "playwright test"`, `"test:e2e:ui": "playwright test --ui"`.

### 2. `ui/playwright.config.ts`
```ts
import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://localhost:5173', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```
(Confirm the vite dev port is 5173 — `vite` default. If `vite.config.ts` sets a different `server.port`, match it.)

### 3. `ui/e2e/_helpers.ts` — seeding + API mocking
- `EZRI`/`YEO` fixtures: `{ id, callsign, isCrew: true, department }` (+ a couple extra crew for the picker).
- `async function seedAgents(page, agents)`: `page.evaluate` → `window.__store.setState({ agents: new Map(agentsArr) })`.
- `async function seedThreads(page, threads)`: set `chatThreads` Map + open the panel (`chatsOpen: true`) and
  also stub the `GET /api/threads` route to return `{ threads }` so the panel's `listThreads()` fetch matches.
- `async function mockChatApi(page, { threads, messagesByThread, createdThread })`: register `page.route`
  handlers — `GET /api/threads`→`{threads}`; `GET /api/threads/:id/messages`→`{thread_id, messages: msgs}`;
  `POST /api/threads`→`createdThread` (the new group); `PATCH /api/threads/:id`→merged thread (meeting_active);
  `POST /api/threads/:id/participants`→updated thread; `POST /api/threads/:id/messages`→`{...msg, per_agent_replies: []}`;
  catch-all `**/api/**`→`{}` 200. Use URL-pattern matching; specific routes BEFORE the catch-all.
- A `gotoApp(page)` that navigates `/`, waits for the store seam (`await page.waitForFunction(() => (window).__store)`),
  then seeds.

### 4. `ui/e2e/` specs (one per issue) — assert the testids verified live
- **`group-chat-open.spec.ts` (Issue 2):** seed agents (Ezri, Yeo crew) + a `chatThreads` group
  `{id:'g1', title:'Ezri, Yeo', participants:['ezri','yeo']}`; mock `GET /api/threads`→that group + a 1:1, and
  `GET /api/threads/g1/messages`→two messages (one from ezri, one from yeo). Open CHATS, click
  `[data-testid="chat-row-g1"]`. ASSERT: the group header shows the room title "Ezri, Yeo" AND both
  participant avatars (`[aria-label="Agent Ezri"]`, `[aria-label="Agent Yeo"]`), a "Start meeting" button, and
  the **thread transcript renders the two mocked messages** (assert their text + that two distinct author
  `[data-testid="agent-avatar-badge"]` appear — the AD-936 per-author avatars). This is the headline
  regression: a group opens as a GROUP with its real transcript, NOT an empty host 1:1.
- **`add-people.spec.ts` (Issue 3):** seed agents + open a 1:1 with Ezri (no thread yet); mock `POST /api/threads`
  to return `{id:'g2', title:'Ezri, Yeo', participants:['ezri','yeo']}`. Click "Add people"
  (`[data-testid="empty-chat-add-people"]` on the empty 1:1, OR the group-header add control), pick Yeo in the
  modal/popover, confirm. ASSERT: `POST /api/threads` was called with participants containing BOTH ezri+yeo
  (intercept + capture the request body), AND the opened view is the new GROUP (header shows both avatars) —
  NOT a 1:1 with a single agent. (This encodes the Captain's "creates a chat with only Ezri / only Yeo" bug.)
- **`meeting-avatars.spec.ts` (Issue 4):** seed + open the `g1` group (hydrated); mock `PATCH /api/threads/g1`
  → meeting_active true. Click "Start meeting". ASSERT: `[data-testid="captain-slot"]` is visible AND
  `[data-testid="avatar-slot-ezri"]` + `[data-testid="avatar-slot-yeo"]` render (crew avatars). With no
  camera/screen stream, assert `[data-testid="captain-icon"]` (the icon fallback).
- **`draggable-chats.spec.ts` (Issue 1):** open CHATS; read `[data-testid="chats-panel"]` boundingBox; drag its
  header (`mouse.move/down/move/up`) by +160/+130; ASSERT the boundingBox moved by ~that delta.

### 5. `.gitignore` — add Playwright artifacts: `ui/test-results/`, `ui/playwright-report/`, `ui/.playwright/`.

## Gates
- `cd d:\ProbOS\ui; npx playwright install chromium` (one-time browser fetch).
- `cd d:\ProbOS\ui; npx playwright test` → all specs green. Report pass count.
- `cd d:\ProbOS\ui; npx vitest run` → still 1328/1 (the new e2e dir must NOT be picked up by vitest — confirm
  `vitest.config`/`vite.config` test.include excludes `e2e/**`, or name specs `*.spec.ts` and ensure vitest's
  include is `*.test.ts(x)` only; add an exclude if needed).
- `npm run build` still clean.

## Acceptance
- `npx playwright test` runs `vite dev`, seeds the store, mocks the API, and all four specs pass — encoding the
  four Captain-reported regressions so they can never silently return. Vitest unaffected (1328/1). Build clean.
- Verify Engineering-Principles compliance.

## Do NOT
- No change to app source (this is pure test infrastructure) EXCEPT, if strictly required to seed, you may rely
  on the EXISTING `window.__store` DEV seam — do NOT add new production code paths. If a testid referenced
  above is missing in the live DOM, add ONLY the minimal `data-testid` attribute (no behavior change) and note
  it. No backend/pytest. No push. Stage explicit paths (NOT `git add -A`); deletion-audit.
- Do NOT run the e2e against the operator's live backend (:18900) — the harness is self-contained (vite dev +
  mocked API). Do NOT mutate real data.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-941 row, SHIPPED + 2026-06-09 + gate note.
- `PROGRESS.md`: prepend an AD-941 block.
- `DECISIONS.md` (match where AD-940 went): AD-941 entry — Playwright e2e harness (vite-dev + `window.__store`
  seam + `page.route` API mock), the four regression specs mapping to the four issues, why e2e (the
  mocked-store Vitest gap that let AD-917/931/937 ship with the runtime bugs).
