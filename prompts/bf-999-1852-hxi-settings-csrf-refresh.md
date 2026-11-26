# BF-999 -- #1852: the HXI settings store holds a live CSRF token for every save

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (review round 1 amendment: D8 to D10, sections 6.5 to 6.8, M3)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (review round 2 amendment: D11, sections 6.9 and 6.10, M4)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (review round 3 amendment at the round-three brake: section 6.11, M5)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (review round 4 amendment at the round-four brake: section 6.12, M6)
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (review round 5 amendment at the round-five brake: section 6.13, M7)
**Status:** M1 `f7086568`, M2 `418cc977`, M3 `fa73f33a`, M4 `579c8c14`, M5 `736bf5c9` and M6 `9c553946` built; the round-5 amendment builds as M7. **Base:** main `f7acb948` (tree `f12fe25c`). **Issue:** #1852 (PR says `Refs #1852`). **Path:** `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`. **Estimated tests:** 1 new vitest file (14 cases after M3; 12 at M1); no existing test changes. **No AD.** BF-999 allocated by the orchestrator (four-source enumeration, 02:32Z); the ledger on main reads latest BF-998, next BF-999 (`docs/development/open-ads-report.md:32`).

## 1. Problem

- **Router (unchanged by this slice).** `src/probos/routers/config.py:50-71`: single-consume tokens, `_CSRF_TTL_SECONDS = 300` on `time.monotonic()`, expired when `now - t > 300`. `GET /api/config` issues one (`:247`). `POST /api/config` consumes it as its first statement (`:263-265`) and answers 403 `invalid_csrf` before it reads the body (`:267`), so a 403 save had no effect; a 200, 400, 409, 422, 500 or 503 all spend the token.
- **Store.** `ui/src/store/useSettingsStore.ts`: `loadSnapshot` (`:110-132`) and `openSettings` (`:134-166`) skip the GET once `loaded` (`:111`, `:139-143`, BF-304). `applyDraft` (`:178-233`) sends `snapshot.csrf_token` (`:191`) and relies on `openSettings()` to refresh after a 200 (`:199`) and a 403 (`:223`); that call returns early, so the token stays spent. The early return also resets the draft (`:141`), so a 403 wipes it, and it sets `open: true` (`:138`), so a 200 re-opens a dialog closed during the save.
- **Reach.** A second save, a save corrected after a 422 (or any other answered status), or a first save more than 300 s after the page's config read: 403 until reload, draft wiped. Reproduced on `f7acb948` by the #1852 probe (2 passed, both asserting the defect).

## 2. Solution

- `SettingsState` gains `csrfFetchedAt: number` (Date.now() when `snapshot.csrf_token` was fetched; 0 = none or spent). `loadSnapshot` and `openSettings` stamp it on success.
- `applyDraft`: a module-private `applying` latch (one save at a time); before each POST, if the token is spent or `>= 240000` ms old, fetch a fresh snapshot (`_fetchSnapshot`) and stamp it; mark the token spent before the POST is sent; on a 403 at the first attempt, repeat once with a fresh token; any other answer ends it. No `openSettings()` call remains in `applyDraft`.
- A failed token read sends nothing, keeps the draft, says so, and marks the token spent (`csrfFetchedAt: 0`), whether it was spent or only aged, so the next press reads first (D8).
- Rejected heavier designs: change the router (multi-use or cookie tokens: a security-control change, out of scope); a shared fetch wrapper (one caller); a public `applying` state plus a disabled APPLY button (touches `SettingsTopBar.tsx` and every test reset helper; the latch is enough).

## 3. Decisions

- **D1 Refresh policy: refresh lazily at the start of APPLY.** Refresh when the token is spent or aged. Replace `snapshot` (whole) and `csrfFetchedAt`; nothing else (`draft`, `applyStatus`, `applyMessage`, `applyErrors`, `selectedSectionId`, `search`, `yamlOpen`, `open`, `loaded` are kept). Ranked alternatives:
  - (2) A forced GET after every answered POST (the issue's proposal). Rejected:
    - It still needs the APPLY-time age check and the failed-read path, so it adds a second refresh site.
    - It costs a GET after every save even when no second save follows.
    - For the token it brings nothing the next save's refresh does not. A save changes the live config only when every field it changes is hot-reload: the router then applies them to `runtime.config` after the write (`config.py`:384-395, BF-299), and the GET snapshot (`:234`) returns them. A save that changes a restart-required field changes only the file on disk until restart (D9).
  - (3) Refresh only the token. Rejected: the GET returns the whole snapshot anyway. After a ProbOS restart, the new process's snapshot is the right one.
  - (4) Refresh on 200 and 403 only. Rejected: every answered status spends the token (`:263-265`).
  - **A failed GET** (non-ok or a throw):
    - The POST is not sent. `snapshot` is untouched and `csrfFetchedAt` is set to 0, whether the token was spent or only aged (D8).
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
- **D8 A failed refresh read marks the token spent (F1).** The refresh branch only runs once the store has decided not to send the token (spent, or `>= 240000` ms by `Date.now()`). Its failure `set` now carries `csrfFetchedAt: 0` along with the status and the message, so the next press reads first whatever `Date.now()` shows later. Before this, an aged, unspent token kept its old stamp. After a backward clock step, the next press sent it without reading.
  - Rejected: an age check on `Math.abs(Date.now() - fetchedAt)`. It would change the clock policy for every save, which is R-6's ground and covered by the resend. It still reuses the token after a backward step shorter than 240 s, and it leaves the state wrong: the stamp says "fresh" for a token the store chose to replace.
- **D9 D1's rationale is corrected for hot-reload fields (F2).** A save changes the live config only when every field it changes is hot-reload. The router then applies those fields to `runtime.config` after the write (`config.py`:384-395, BF-299), and the next `GET /api/config` returns them. A save that changes any restart-required field changes only the file on disk until restart.
  - The forced read after every save stays rejected for the two reasons that remain true: it still needs the save-time age check, and it costs a read after every save. For the token, it brings nothing the next save's refresh does not.
  - Observation, not a decision: the dialog shows "Restart required to take effect." and keeps its old snapshot even after an all-hot-reload save (blind spot 5).
- **D10 The fetch double follows the router's order and refusals (F3).**
  - (a) A POST records its token, then (after the optional hold) the token is spent and checked. Only an accepted token leads to the body being parsed. `srv.patches` now records the patch of each accepted POST. As built at M3, a body that was not JSON got 400 `invalid_json`; D11 removes that branch.
  - (b) Superseded by D11. As built at M3, the double answered 422 for any `memory.max_episodes` failing `/^-?\d+$/` and accepted any string for the other fields. The router accepts some of those values (F4), and "any string" was measured only for `'BAD'`. `tests/test_ad741_config_api.py` sends the same input value, `'not-an-int'`, but asserts only `error` and `loc[0]` (`test_ad741_config_api.py`:116-119), so the `msg` text is measured in 9c.
  - The fake `BAD` enum value goes. T3 was its only user, and only as a draft value; T12 renders the select but sets the draft directly.
  - Numbering: T1 to T12 keep their order and numbers. T3 changes in place (its values and an exact `applyErrors` check). The F1 coverage is appended as one `it.each` at the end of the file: T13 (503) and T14 (throws). Both start from an aged, unspent token.
  - The new cases check behaviour on the wire (posts and gets). They do not pin the field.
- **D11 The double answers a POST only from measured router answers (F4).**
  - Why: D10(b)'s M3 rule answered 422 for `'+5000'`, `' 5000 '`, `'5000.0'`, `'1_000'` and `true`; the router answers each of them 200 (orchestrator probe, a TestClient over the unchanged router, head `fa73f33a`). pydantic's lax integer parsing accepts more forms than any rule here can list. The same was true of the "any string" acceptance for the other fields.
  - Chosen: `MEASURED`, a table keyed by the exact body the store sends for each case's patch (four bodies), each mapped to the router's measured answer: 200, or 422 `validation_failed` with one error entry. A POST that passes the token check (a live token, `refuseEveryPost` unset) and whose body is not in the table is recorded in `unmeasured` and refused with a thrown error, which the store reports as an APPLY error, and `afterEach` fails the case on any recorded body. M5 (F5): a POST reads its body only after the optional hold, so a POST still outstanding when a case ends has not reached the table. The double counts POSTs entered and not yet answered (`outstanding`, decremented in a `finally`), and `afterEach` also fails the case when that count is not 0. M6 (F6): the count and `unmeasured` live in a per-case ledger that `beforeEach` replaces and `installServer()` captures, so a POST an earlier case left outstanding settles into that case's ledger (6.12). `readPatch` and the 400 `invalid_json` branch are removed. No case and no store path sends a non-JSON body, and the branch also answered `invalid_json` to a JSON `null` body, which the router answers 400 `patch_required` (`config.py`:271-273, read).
  - Ranked alternatives (rejected):
    - (2) The same table for `memory.max_episodes` only. It leaves the "any string" rule for `system.name` and `system.log_level`.
    - (3) Refuse only `'not-an-int'`. It flips the mismatch: `'abc'`, `'1e3'`, `5.5` and `null` get 200, where the router answers 422.
    - (4) A regex or parser imitating pydantic. It is an unmeasured model that drifts with pydantic.
  - Branches no case reaches: only the tripwire and the outstanding-POST check, by design. It is the check that no case relies on an unmeasured answer. No case exercises it, because such a case would test the double, not the store, and would have to drain `unmeasured`; 9c fires it once. The 403, 422 and 200 answers are each reached by a case. The age refusal is reached under census row S-M6 (T8 sends `t1` at 301 s).
  - Claims: every sentence in the test file that says what the router does is read in `config.py` at a cited line or measured in 9c. Labelled as not router answers: the fixed snapshot, the fixed 200 body (the store reads only a 200's status, `useSettingsStore.ts`:240-247), the hold, `failNextGet` and `refuseEveryPost`. The double ages tokens on the test's `Date.now()`, the router on `time.monotonic()` (`config.py`:55-59). The cases move only the test's clock, and no unmutated case POSTs a token older than 300 s on it.
  - Measurement (re-proof, recorded in 9c; the table's rows are predictions until then):
    - Post each of the four bodies with a fresh token through a TestClient over the unchanged router on a temporary config, and record status and body. Expected: the two log-level bodies and the `'5000'` body answer 200. The `'not-an-int'` body answers 422 with exactly one entry, `{loc: ['memory','max_episodes'], msg: 'Input should be a valid integer, unable to parse string as an integer', type: 'int_parsing'}`. Any difference is a hard stop.
    - Tripwire probe, not committed: in a scratch copy, change T3's `'5000'` to `'+5000'`. T3 must fail and its `afterEach` must name the body. Then restore.
  - Census: the store is unchanged and the double is not mutated, so no row changes. A mutant that sends a body outside the table now also fails at `afterEach`, which can only add kills; every other mutant gets the same answers as before. No rerun is required: 20 of 20, the 9b campaign of record. The runner's unmutated count stays 21 (14 + 7).

## 4. Milestones and commit subjects

| M | Files | Commit subject |
|---|---|---|
| M1 | `ui/src/store/useSettingsStore.ts`, new `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` | `the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (#1852)` |
| M2 | `PROGRESS.md`, `DECISIONS.md`, `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (generated) | `trackers and generated ledger for the HXI settings save token (#1852)` |
| M3 | `ui/src/store/useSettingsStore.ts`, the new test file, `PROGRESS.md`, `DECISIONS.md` (sections 6.5 to 6.8) | `the HXI settings store marks a token spent when its refresh read fails, and the save tests model the router's body order (#1852)` |
| M4 | the new test file, `PROGRESS.md` (sections 6.9 and 6.10) | `the HXI settings save tests answer each save only from measured router answers (#1852)` |
| M5 | the new test file (section 6.11) | `Settings store test double: fail a case that ends with a save still outstanding (#1852)` |
| M6 | the new test file (section 6.12) | `Settings store test double: give each case its own ledger of outstanding and unmeasured saves (#1852)` |
| M7 | the new test file (section 6.13) and `PROGRESS.md` (section 6.14) | `Settings store test double: state its guarantees by the code path a POST takes (#1852)` |

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
- **M3:** `npx tsc -b` clean; the M1 vitest command above with 10 files, 80 passed (the 66-test baseline plus 14); `scripts/gen_ad_ledger.py --check` current; full `npx vitest run` 0 failed.
- **M4:** the M3 gates with the same counts (predicted), plus the 9c measurements and the tripwire probe of D11.
- **M5:** the M3 gates with the same counts (predicted), plus the outstanding-POST probes of D11 (section 9d).
- **M6:** the M3 gates with the same counts (predicted), plus the ledger probes O-1 to O-4 of 6.12 (recorded in 9e).
- **M7:** the M3 gates with the same counts (predicted), plus the comment-only proof and the probes of 6.13 (recorded in 9f).
- **UI batch gates once on the candidate** (`run_test_gate.py` runs neither): `npx tsc -b`, then `npx vitest run` (0 failed).
- **Broad gate** once after M2: `scripts/run_test_gate.py --label 1852-bf999 --receipt logs/gates/1852-bf999.receipt.json`.

**A/B (measure):**
- The new file on the unrepaired `f7acb948` store: **12 cases, 10 failed, 2 passed**. The passing ones are guard rows T1 and T6.
  - Each red case fails at its first `expect(srv.posts).toEqual(...)`.
  - T4, T5, T7, T8: received `['t1']`.
  - T2, T3, T9, T10, T11, T12: received `['t1', 't1']`.
- The #1852 probe (`zzProbe1852.test.ts`) on the candidate: **2 failed**, both at `expect(srv.gets()).toBe(1)` (received 2).
- After M3, the amended file (14 cases):
  - on the round-1 store (`f7086568`): **2 failed, 12 passed**. T13 and T14 fail at `expect(srv.posts).toEqual(['t2'])`, received `['t1']`;
  - on `f7acb948`: **12 failed, 2 passed** (T1, T6). T2 to T12 fail as above; T13 and T14 fail at `expect(srv.posts).toEqual([])`, received `['t1']`.
- After M4 (T1 to T14 byte-unchanged), predicted: the same counts at the same first failing assertions on `f7086568` and on `f7acb948`.

## Verified Against Codebase (2026-11-26, tree `f7acb948`)

```
ui/src/store/useSettingsStore.ts (250 lines, read whole)
  1, 107, 211, 216, 221 contain U+2014; 41-68 SettingsState (56 openedAt); 70-81 _setNestedPath; 83 create<SettingsState>((set, get)
  96-98 initial applyErrors/applyMessage/openedAt; 110-132 loadSnapshot (111 guard; 120-128 set); 134-166 openSettings (138 open+openedAt; 139-143 early return, 141 draft reset; 152-162 set)
  168 closeSettings; 178-233 applyDraft (191 header; 196-206 200 branch, 199 openSettings(); 207-212 422; 213-217 400; 218-223 403, 223 openSettings(); 224-229 other; 230-232 catch)
src/probos/routers/config.py  50-52 _csrf_tokens, _CSRF_TTL_SECONDS = 300; 55-59 _gc_csrf (now - t > TTL); 62-66 _issue_csrf (monotonic); 69-71 _consume_csrf (pop)
  231-248 GET (234 runtime.config live; 247 csrf_token); 260-265 POST consumes first, 403 invalid_csrf; 267-270 body read after; 289-292 merge onto live config; 294-303 422; 305-307 503; 313-319 409
  374-395 BF-299: when every changed field is hot_reload, restart_required is false and each field is applied to runtime.config after the write
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
| The store never reads the router's `restart_required` flag | Grep `restart_required` in `ui/src` (round 1, head `418cc977`) | `useSettingsStore.ts`:53 (type), :240 (the status a 200 always sets); `SettingsTopBar.tsx`:112; test fixtures | yes |

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
  5. Observation, out of scope: a 200 always sets `applyStatus: 'restart_required'`, though for an all-hot-reload save the router answers `restart_required: false` and has already applied the change; the dialog's snapshot also keeps the old value until the next read. A separate issue.

## 6. Pairs

### 6.1 `ui/src/store/useSettingsStore.ts` (M1) -- run with `--utf8 U+2014` (P-6 SEARCH holds three U+2014, its REPLACE two, both in unchanged lines)

*After review round 1: pair P-6 stands as M1 committed it; 6.5 (M3) adds one line to its refresh-failure branch.*

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

*After review round 1: this block is the file as M1 committed it (12 cases); 6.6 (M3) amends it to 14 cases.*

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

*After review round 1: this block replays M2 as committed; 6.8 (M3) replaces the paragraph.*

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

*After review round 1: this block replays M2 as committed; its D1 line is superseded by 6.7 (M3).*

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

## Amendment after review round 1 (2026-11-26)

Case key addendum: T13 and T14 are the two aged-start failed-read rows (503, throws), the last `it.each` in the file.

### 6.5 `ui/src/store/useSettingsStore.ts` (M3; ASCII only, no `--utf8`)

**P-1**
SEARCH:
```
          if (typeof fresh === 'string') {
            set({
              applyStatus: 'rejected',
```
REPLACE:
```
          if (typeof fresh === 'string') {
            // The token was spent or aged: keep it marked for replacement so the next press reads first.
            set({
              csrfFetchedAt: 0,
              applyStatus: 'rejected',
```

### 6.6 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (M3; amends the committed file)

*Note (round 2 amendment): 6.9 supersedes this section's header comment, the `readPatch` helper, the 422 rule and the interface comments; the rest stands as committed at M3.*

**P-1**
SEARCH:
```
// real SettingsPanel; fetch is a double that behaves like src/probos/routers/config.py: one
// token per GET, every POST spends the token it carries before the body is read, a token older
// than 300 s is refused, and a 403 is answered before the body is read.
```
REPLACE:
```
// real SettingsPanel; fetch is a double that behaves like src/probos/routers/config.py: one
// token per GET, every POST spends the token it carries before the body is read, a token older
// than 300 s is refused, a 403 is answered before the body is read, and a memory.max_episodes
// that is not an integer is answered 422 with the router's error entry.
```

**P-2**
SEARCH:
```
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: ['INFO', 'DEBUG', 'BAD'], description: '', hot_reload: false },
```
REPLACE:
```
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: ['INFO', 'DEBUG'], description: '', hot_reload: false },
```

**P-3**
SEARCH:
```
  patches: unknown[]; // the patch each POST carried, in arrival order
```
REPLACE:
```
  patches: unknown[]; // the patch of each POST whose token was accepted, in arrival order
```

**P-4**
SEARCH:
```
function installServer(): ServerDouble {
```
REPLACE:
```
// The router reads the body only after it accepts the token; undefined stands for its 400 invalid_json.
function readPatch(body: RequestInit['body']) {
  try {
    return { patch: JSON.parse(String(body)).patch };
  } catch {
    return undefined;
  }
}

function installServer(): ServerDouble {
```

**P-5**
SEARCH:
```
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
```
REPLACE:
```
    if (init?.method === 'POST') {
      const token = (init.headers as Record<string, string>)['X-Probos-CSRF'];
      srv.posts.push(token);
      const wait = gate;
      if (wait) await wait;
      // _consume_csrf pops the token; an unknown or expired one is a 403 before the body is read.
      const issuedAt = live.get(token);
      live.delete(token);
      if (srv.refuseEveryPost || issuedAt === undefined || Date.now() - issuedAt > TOKEN_LIFETIME_MS) {
        return jsonResp({ error: 'invalid_csrf' }, 403);
      }
      const read = readPatch(init.body);
      if (!read) return jsonResp({ error: 'invalid_json' }, 400);
      const patch = read.patch;
      srv.patches.push(patch);
      // SystemConfig refuses a memory.max_episodes it cannot parse as an integer ('not-an-int');
      // it accepts '5000', 5000 and -1, and any string for system.name and system.log_level.
      const episodes = patch?.memory?.max_episodes;
      if (episodes !== undefined && !/^-?\d+$/.test(String(episodes))) {
        return jsonResp({
          error: 'validation_failed',
          errors: [{
            loc: ['memory', 'max_episodes'],
            msg: 'Input should be a valid integer, unable to parse string as an integer',
            type: 'int_parsing',
          }],
        }, 422);
      }
      const level = patch?.system?.log_level;
      srv.saved.push(level);
```

**P-6**
SEARCH:
```
    await save({ 'system.name': 'Vessel', 'system.log_level': 'BAD' });
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyErrors).toHaveLength(1);
    expect(s().draft).toEqual({ 'system.name': 'Vessel', 'system.log_level': 'BAD' });
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.patches[1]).toEqual({ system: { name: 'Vessel', log_level: 'DEBUG' } });
```
REPLACE:
```
    await save({ 'system.name': 'Vessel', 'memory.max_episodes': 'not-an-int' });
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyErrors).toEqual([{
      loc: ['memory', 'max_episodes'],
      msg: 'Input should be a valid integer, unable to parse string as an integer',
      type: 'int_parsing',
    }]);
    expect(s().draft).toEqual({ 'system.name': 'Vessel', 'memory.max_episodes': 'not-an-int' });
    await save({ 'memory.max_episodes': '5000' });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.patches[1]).toEqual({ system: { name: 'Vessel' }, memory: { max_episodes: '5000' } });
```

**P-7**
SEARCH:
```
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
  });
});
```
REPLACE:
```
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
  });

  it.each([
    { label: 'answers 503', mode: 'status' as const, reason: 'config GET failed: 503' },
    { label: 'throws', mode: 'throw' as const, reason: 'config GET error: TypeError: network down' },
  ])('an aged token whose refresh read $label sends no save, and the next press reads first after the clock steps back', async ({ mode, reason }) => {
    let now = 1000000;
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const srv = installServer();
    await s().openSettings(); // t1, never sent
    now += 240000;
    srv.failNextGet = mode;
    await save({ 'system.log_level': 'DEBUG' });
    expect(srv.posts).toEqual([]);
    expect(srv.gets).toBe(2);
    expect(s().applyStatus).toBe('rejected');
    expect(s().applyMessage).toBe(`Could not get a save token (${reason}); nothing was saved. Press APPLY to try again.`);
    expect(s().draft).toEqual({ 'system.log_level': 'DEBUG' });
    // A wall-clock correction makes t1 look 10 s old to Date.now; the store must still read before it sends.
    now = 1010000;
    await s().applyDraft();
    expect(srv.posts).toEqual(['t2']);
    expect(srv.gets).toBe(3);
    expect(srv.saved).toEqual(['DEBUG']);
    expect(s().applyStatus).toBe('restart_required');
  });
});
```

### 6.7 `DECISIONS.md` (M3; the D1 line of the BF-999 entry; supersedes that line of 6.4)

**P-1**
SEARCH:
```
- *D1.* The token is refreshed lazily, at the start of a save, when it is spent or aged; the refresh replaces the snapshot and its fetch time only, keeping the draft and every view field. Rejected: a forced read after every answered save (it still needs the save-time age check, costs a read after every save, and brings an identical snapshot, because the router snapshots the live config a save does not change before restart).
```
REPLACE:
```
- *D1.* The token is refreshed lazily, at the start of a save, when it is spent or aged; the refresh replaces the snapshot and its fetch time only, keeping the draft and every view field, and a refresh read that fails marks the token spent, so the next save reads first whatever the clock shows. Rejected: a forced read after every answered save (it still needs the save-time age check and costs a read after every save). A save changes the live config only when every field it changes is hot-reload: the router then applies them to `runtime.config` after the write (BF-299, `src/probos/routers/config.py`) and the next `GET /api/config` returns them; a save that changes a restart-required field changes only the file on disk until restart.
```

### 6.8 `PROGRESS.md` (M3; the BF-999 paragraph; supersedes 6.3)

*Note (round 2 amendment): 6.10 supersedes this REPLACE text's sentence about the fetch double.*

**P-1**
SEARCH:
```
**BF-999 (2026-11-26), #1852 -- the HXI settings store fetches a fresh CSRF token before each save, sends a save refused with 403 once more, and keeps the draft.** The router issues one single-use CSRF token per `GET /api/config`, lets it live 300 s and spends it on every `POST /api/config` before it reads the body. The store fetched one token per page load (`openSettings` and `loadSnapshot` skip the read once loaded, BF-304), so a second save, a save corrected after a 422, or a first save more than 300 s after the page's config read was answered 403 `invalid_csrf` until a reload, and the 403 path wiped the draft. `useSettingsStore` now records when its token was fetched (`csrfFetchedAt`), treats it as spent once a POST carries it, and before each save fetches a fresh snapshot and token when the last is spent or 240 s old. A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again." and the draft kept. A failed token read sends nothing, keeps the draft and says so, and the next press reads first. One save runs at a time, and a save no longer re-opens a dialog closed while it was in flight. `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (12 cases) drives the real store and the real `SettingsPanel` against a fetch double that behaves like the router; 10 are red on the unrepaired store. The router is unchanged. Mutation census: 19 of 19 killed (rows S-M1 to S-M19), run once on the overlay of f7acb948. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`.
```
REPLACE:
```
**BF-999 (2026-11-26), #1852 -- the HXI settings store fetches a fresh CSRF token before each save, sends a save refused with 403 once more, and keeps the draft.** The router issues one single-use CSRF token per `GET /api/config`, lets it live 300 s and spends it on every `POST /api/config` before it reads the body. The store fetched one token per page load (`openSettings` and `loadSnapshot` skip the read once loaded, BF-304), so a second save, a save corrected after a 422, or a first save more than 300 s after the page's config read was answered 403 `invalid_csrf` until a reload, and the 403 path wiped the draft. `useSettingsStore` now records when its token was fetched (`csrfFetchedAt`), treats it as spent once a POST carries it, and before each save fetches a fresh snapshot and token when the last is spent or 240 s old. A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again." and the draft kept. A failed token read sends nothing, keeps the draft and says so, and marks the token spent, so the next press reads first even when the token was only aged and the wall clock later steps back. One save runs at a time, and a save no longer re-opens a dialog closed while it was in flight. `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (14 cases) drives the real store and the real `SettingsPanel` against a fetch double that behaves like the router (it spends the token before it reads the body, and answers 422 for a `memory.max_episodes` the router also refuses); 12 are red on the unrepaired store. The router is unchanged. Mutation census: 20 of 20 killed (rows S-M1 to S-M20), run on the overlay of f7acb948. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`.
```

## Amendment after review round 2 (2026-11-26)

F4 (P3, injected-only): the M3 double's rule for `memory.max_episodes` answered 422 for values the router accepts. D11 replaces every rule-based answer in the double with measured answers. Only the test file and the BF-999 paragraph of `PROGRESS.md` change; T1 to T14 are byte-unchanged.

### 6.9 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (M4; amends the file as committed at `fa73f33a`; ASCII)

*Note (round 3 amendment): 6.11 amends the double's POST branch (a counter and a try/finally around the statements this section wrote) and two of its comments; the rest stands as committed at M4.*

**P-1**
SEARCH:
```
// real SettingsPanel; fetch is a double that behaves like src/probos/routers/config.py: one
// token per GET, every POST spends the token it carries before the body is read, a token older
// than 300 s is refused, a 403 is answered before the body is read, and a memory.max_episodes
// that is not an integer is answered 422 with the router's error entry.
```
REPLACE:
```
// real SettingsPanel; fetch is a double that follows the order of src/probos/routers/config.py:
// one token per GET; every POST spends the token it carries and, before the body is read,
// answers 403 for an unknown token or one older than 300 s (the router ages tokens on
// time.monotonic, the double on the test's Date.now). A POST with a live token is answered from
// MEASURED, the router's answers to the exact bodies the cases send; any other body fails the
// case. The fixed snapshot, the 200 body, the hold and the injected faults are not router answers.
```

**P-2**
SEARCH:
```
  patches: unknown[]; // the patch of each POST whose token was accepted, in arrival order
  saved: string[]; // system.log_level of each save answered 200
  failNextGet: 'none' | 'status' | 'throw';
  refuseEveryPost: boolean;
```
REPLACE:
```
  patches: unknown[]; // the patch of each POST answered 200 or 422, in arrival order
  saved: string[]; // system.log_level of each save answered 200
  failNextGet: 'none' | 'status' | 'throw'; // injected fault for the next GET, not a router answer
  refuseEveryPost: boolean; // injected: refuse live tokens too (the router refuses unknown or expired)
```

**P-3**
SEARCH:
```
// The router reads the body only after it accepts the token; undefined stands for its 400 invalid_json.
function readPatch(body: RequestInit['body']) {
  try {
    return { patch: JSON.parse(String(body)).patch };
  } catch {
    return undefined;
  }
}
```
REPLACE:
```
// The router's answer to each body a case POSTs with a live token, measured with a TestClient
// over the unchanged src/probos/routers/config.py (contract D11): 'ok' is a 200, an entry is a
// 422 validation_failed carrying it. pydantic parses integers laxly (it accepts '+5000',
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body missing
// from the table is recorded and refused, and afterEach fails the case on it.
const INT_PARSING = {
  loc: ['memory', 'max_episodes'],
  msg: 'Input should be a valid integer, unable to parse string as an integer',
  type: 'int_parsing',
};
const MEASURED = new Map<string, 'ok' | typeof INT_PARSING>([
  ['{"patch":{"system":{"log_level":"DEBUG"}}}', 'ok'],
  ['{"patch":{"system":{"log_level":"INFO"}}}', 'ok'],
  ['{"patch":{"system":{"name":"Vessel"},"memory":{"max_episodes":"not-an-int"}}}', INT_PARSING],
  ['{"patch":{"system":{"name":"Vessel"},"memory":{"max_episodes":"5000"}}}', 'ok'],
]);
const unmeasured: string[] = [];
```

**P-4**
SEARCH:
```
      const read = readPatch(init.body);
      if (!read) return jsonResp({ error: 'invalid_json' }, 400);
      const patch = read.patch;
      srv.patches.push(patch);
      // SystemConfig refuses a memory.max_episodes it cannot parse as an integer ('not-an-int');
      // it accepts '5000', 5000 and -1, and any string for system.name and system.log_level.
      const episodes = patch?.memory?.max_episodes;
      if (episodes !== undefined && !/^-?\d+$/.test(String(episodes))) {
        return jsonResp({
          error: 'validation_failed',
          errors: [{
            loc: ['memory', 'max_episodes'],
            msg: 'Input should be a valid integer, unable to parse string as an integer',
            type: 'int_parsing',
          }],
        }, 422);
      }
      const level = patch?.system?.log_level;
      srv.saved.push(level);
      return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
```
REPLACE:
```
      const sent = String(init.body);
      const answer = MEASURED.get(sent);
      if (answer === undefined) {
        unmeasured.push(sent);
        throw new Error(`fetch double: no measured router answer for ${sent}`);
      }
      const patch = JSON.parse(sent).patch;
      srv.patches.push(patch);
      if (answer !== 'ok') return jsonResp({ error: 'validation_failed', errors: [answer] }, 422);
      srv.saved.push(patch.system?.log_level);
      // The store reads only the status of a 200, so this body is fixed, not the router's per-save answer.
      return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
```

**P-5**
SEARCH:
```
  beforeEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });
```
REPLACE:
```
  beforeEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
    unmeasured.length = 0;
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
    expect(unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
  });
```

### 6.10 `PROGRESS.md` (M4; line 3, the BF-999 paragraph; supersedes 6.8)

**P-1**
SEARCH:
```
**BF-999 (2026-11-26), #1852 -- the HXI settings store fetches a fresh CSRF token before each save, sends a save refused with 403 once more, and keeps the draft.** The router issues one single-use CSRF token per `GET /api/config`, lets it live 300 s and spends it on every `POST /api/config` before it reads the body. The store fetched one token per page load (`openSettings` and `loadSnapshot` skip the read once loaded, BF-304), so a second save, a save corrected after a 422, or a first save more than 300 s after the page's config read was answered 403 `invalid_csrf` until a reload, and the 403 path wiped the draft. `useSettingsStore` now records when its token was fetched (`csrfFetchedAt`), treats it as spent once a POST carries it, and before each save fetches a fresh snapshot and token when the last is spent or 240 s old. A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again." and the draft kept. A failed token read sends nothing, keeps the draft and says so, and marks the token spent, so the next press reads first even when the token was only aged and the wall clock later steps back. One save runs at a time, and a save no longer re-opens a dialog closed while it was in flight. `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (14 cases) drives the real store and the real `SettingsPanel` against a fetch double that behaves like the router (it spends the token before it reads the body, and answers 422 for a `memory.max_episodes` the router also refuses); 12 are red on the unrepaired store. The router is unchanged. Mutation census: 20 of 20 killed (rows S-M1 to S-M20), run on the overlay of f7acb948. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`.
```
REPLACE:
```
**BF-999 (2026-11-26), #1852 -- the HXI settings store fetches a fresh CSRF token before each save, sends a save refused with 403 once more, and keeps the draft.** The router issues one single-use CSRF token per `GET /api/config`, lets it live 300 s and spends it on every `POST /api/config` before it reads the body. The store fetched one token per page load (`openSettings` and `loadSnapshot` skip the read once loaded, BF-304), so a second save, a save corrected after a 422, or a first save more than 300 s after the page's config read was answered 403 `invalid_csrf` until a reload, and the 403 path wiped the draft. `useSettingsStore` now records when its token was fetched (`csrfFetchedAt`), treats it as spent once a POST carries it, and before each save fetches a fresh snapshot and token when the last is spent or 240 s old. A 403 is answered before the router reads the body, so the store fetches a new token and sends the same patch once more; a second 403 ends with "Save token refused twice; nothing was saved. Press APPLY to try again." and the draft kept. A failed token read sends nothing, keeps the draft and says so, and marks the token spent, so the next press reads first even when the token was only aged and the wall clock later steps back. One save runs at a time, and a save no longer re-opens a dialog closed while it was in flight. `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (14 cases) drives the real store and the real `SettingsPanel` against a fetch double that spends the token before it reads the body, as the router does, and answers each save only from the router's measured answers to the four bodies the cases send (any other body fails the case); 12 are red on the unrepaired store. The router is unchanged. Mutation census: 20 of 20 killed (rows S-M1 to S-M20), run on the overlay of f7acb948. Contract `prompts/bf-999-1852-hxi-settings-csrf-refresh.md`.
```

### Verified for amendment 2 (2026-11-26, head `fa73f33a`)

```text
grep -n "_consume_csrf\|_CSRF_TTL_SECONDS\|patch_required\|invalid_json\|changed_fields" src/probos/routers/config.py
  52: _CSRF_TTL_SECONDS = 300
  69-71: _consume_csrf pops; 264-265: 403 invalid_csrf before the body
  267-270: 400 invalid_json; 271-273: 400 patch_required (non-dict patch, incl. JSON null)
  372, 433: changed_fields computed per save
grep -n "resp.status === 200" ui/src/store/useSettingsStore.ts
  240-247: the 200 branch reads no body field
grep -n "not-an-int" tests/test_ad741_config_api.py
  112: the value; 116-119 assert status, error and loc[0] only (not msg)
grep -n "function _setNestedPath\|setDraftField: (" ui/src/store/useSettingsStore.ts
  72-83, 193-196: no value coercion, so the bodies are the draft's strings in insertion order
```

Absence: no case POSTs a body that is not JSON (`applyDraft` always serialises `{ patch }`, `useSettingsStore.ts`:236), and the test file has no other 4xx branch after P-4.

## Amendment after review round 3 (2026-11-26)

F5 (P3, injected-only; the regression is the claim, not the code): the double's guard runs at teardown, but a POST held by `hold()` reads its body only after the release, so a case that ends with it outstanding passes. The Architect's decision at the round-three brake is to continue with F5 only. M5 counts the double's POSTs entered and not yet answered, and `afterEach` fails a case that ends with a non-zero count.

### 6.11 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (M5; F5; on the file as committed at `579c8c14`, LF)

*Note (round 4 amendment): 6.12 moves the module-level `outstanding` and `unmeasured` of this section into a per-case ledger; the rest stands as committed at M5.*

**F5-a** (header)
SEARCH:
```
// time.monotonic, the double on the test's Date.now). A POST with a live token is answered from
// MEASURED, the router's answers to the exact bodies the cases send; any other body fails the
// case. The fixed snapshot, the 200 body, the hold and the injected faults are not router answers.
```
REPLACE:
```
// time.monotonic, the double on the test's Date.now). A POST with a live token is answered from
// MEASURED, the router's answers to the exact bodies the cases send; any other body fails the
// case, and so does a POST still outstanding when the case ends (held or unsettled, so its body
// has not been read). The fixed snapshot, the 200 body, the hold and the injected faults are not
// router answers.
```

**F5-b** (the MEASURED comment)
SEARCH:
```
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body missing
// from the table is recorded and refused, and afterEach fails the case on it.
```
REPLACE:
```
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body missing
// from the table is recorded and refused, and afterEach fails the case on it. A POST reads its
// body only after the hold, so afterEach also fails a case that ends with a POST outstanding.
```

**F5-c** (the counter)
SEARCH:
```
const unmeasured: string[] = [];

function installServer(): ServerDouble {
```
REPLACE:
```
const unmeasured: string[] = [];
let outstanding = 0; // double POSTs entered and not yet answered or thrown

function installServer(): ServerDouble {
```

**F5-d** (the POST branch, re-indented inside try/finally; no statement changes)
SEARCH:
```
    if (init?.method === 'POST') {
      const token = (init.headers as Record<string, string>)['X-Probos-CSRF'];
      srv.posts.push(token);
      const wait = gate;
      if (wait) await wait;
      // _consume_csrf pops the token; an unknown or expired one is a 403 before the body is read.
      const issuedAt = live.get(token);
      live.delete(token);
      if (srv.refuseEveryPost || issuedAt === undefined || Date.now() - issuedAt > TOKEN_LIFETIME_MS) {
        return jsonResp({ error: 'invalid_csrf' }, 403);
      }
      const sent = String(init.body);
      const answer = MEASURED.get(sent);
      if (answer === undefined) {
        unmeasured.push(sent);
        throw new Error(`fetch double: no measured router answer for ${sent}`);
      }
      const patch = JSON.parse(sent).patch;
      srv.patches.push(patch);
      if (answer !== 'ok') return jsonResp({ error: 'validation_failed', errors: [answer] }, 422);
      srv.saved.push(patch.system?.log_level);
      // The store reads only the status of a 200, so this body is fixed, not the router's per-save answer.
      return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
    }
```
REPLACE:
```
    if (init?.method === 'POST') {
      outstanding += 1;
      try {
        const token = (init.headers as Record<string, string>)['X-Probos-CSRF'];
        srv.posts.push(token);
        const wait = gate;
        if (wait) await wait;
        // _consume_csrf pops the token; an unknown or expired one is a 403 before the body is read.
        const issuedAt = live.get(token);
        live.delete(token);
        if (srv.refuseEveryPost || issuedAt === undefined || Date.now() - issuedAt > TOKEN_LIFETIME_MS) {
          return jsonResp({ error: 'invalid_csrf' }, 403);
        }
        const sent = String(init.body);
        const answer = MEASURED.get(sent);
        if (answer === undefined) {
          unmeasured.push(sent);
          throw new Error(`fetch double: no measured router answer for ${sent}`);
        }
        const patch = JSON.parse(sent).patch;
        srv.patches.push(patch);
        if (answer !== 'ok') return jsonResp({ error: 'validation_failed', errors: [answer] }, 422);
        srv.saved.push(patch.system?.log_level);
        // The store reads only the status of a 200, so this body is fixed, not the router's per-save answer.
        return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
      } finally {
        outstanding -= 1;
      }
    }
```

**F5-e** (reset and assert)
SEARCH:
```
    unmeasured.length = 0;
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
    expect(unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
  });
```
REPLACE:
```
    unmeasured.length = 0;
    outstanding = 0;
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
    expect(outstanding, 'double POSTs still outstanding when the case ended').toBe(0);
    expect(unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
  });
```

Superseded by 6.12 (F6): the next sentence is false when a failed case's release() was scheduled to fire later. At M5 that POST's finally decremented the later case's counter. Original text: A POST left behind by a failed case never resumes, because only that case holds its `release()`. So resetting the counter to 0 in `beforeEach` cannot pass a leak on to the next case.

## Amendment after review round 4 (2026-11-26)

F6 (P3, injected-only, a double fault; the regression is M5's claim, not the code). At M5, `outstanding` and `unmeasured` were module-level and reset in `beforeEach`. A POST that an earlier, failing case left held could have its release scheduled to fire during a later case. Its `finally` then decremented the later case's count and cancelled that case's own outstanding POST, so the later case passed. The Architect's decision at the round-four brake is to continue with F6 only. M6 gives each case its own ledger, which `beforeEach` replaces and `installServer()` captures, so a POST settles into the ledger of the case whose double it entered.

### 6.12 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (M6; F6; on the file as committed at `736bf5c9`, LF, ASCII)

*Note (round 5 amendment): 6.13 narrows the guarantee sentences quoted in this section (the header, the `MEASURED` comment, C-1); the text here stands as committed at M6.*

**F6-a** (header)
SEARCH:
```
// MEASURED, the router's answers to the exact bodies the cases send; any other body fails the
// case, and so does a POST still outstanding when the case ends (held or unsettled, so its body
// has not been read). The fixed snapshot, the 200 body, the hold and the injected faults are not
// router answers.
```
REPLACE:
```
// MEASURED, the router's answers to the exact bodies the cases send. A case fails when a POST to
// a double it installed carried a live token and any other body, or is still outstanding when the
// case ends (held or unsettled, so its body has not been read). Each case records both in its own
// ledger. The fixed snapshot, the 200 body, the hold and the injected faults are not router
// answers.
```

**F6-b** (the MEASURED comment)
SEARCH:
```
// from the table is recorded and refused, and afterEach fails the case on it. A POST reads its
// body only after the hold, so afterEach also fails a case that ends with a POST outstanding.
```
REPLACE:
```
// from the table is recorded in the case's ledger and refused, and afterEach fails the case on
// it. A POST reads its body only after the hold, so afterEach also fails a case whose ledger
// still counts a POST outstanding.
```

**F6-c** (the ledger)
SEARCH:
```
const unmeasured: string[] = [];
let outstanding = 0; // double POSTs entered and not yet answered or thrown

function installServer(): ServerDouble {
  let issued = 0;
```
REPLACE:
```
// A case's record of its doubles: POSTs entered and not yet answered or thrown, and bodies with
// no measured answer. beforeEach gives each case a new ledger and installServer() captures it,
// so a POST an earlier case left outstanding settles into that case's ledger, never a later one.
interface Ledger {
  outstanding: number;
  unmeasured: string[];
}
let ledger: Ledger = { outstanding: 0, unmeasured: [] };

function installServer(): ServerDouble {
  const mine = ledger;
  let issued = 0;
```

**F6-d** (entry)
SEARCH:
```
    if (init?.method === 'POST') {
      outstanding += 1;
```
REPLACE:
```
    if (init?.method === 'POST') {
      mine.outstanding += 1;
```

**F6-e** (the tripwire)
SEARCH:
```
          unmeasured.push(sent);
```
REPLACE:
```
          mine.unmeasured.push(sent);
```

**F6-f** (exit)
SEARCH:
```
      } finally {
        outstanding -= 1;
      }
```
REPLACE:
```
      } finally {
        mine.outstanding -= 1;
      }
```

**F6-g** (reset)
SEARCH:
```
    unmeasured.length = 0;
    outstanding = 0;
  });
```
REPLACE:
```
    ledger = { outstanding: 0, unmeasured: [] };
  });
```

**F6-h** (assert)
SEARCH:
```
    expect(outstanding, 'double POSTs still outstanding when the case ended').toBe(0);
    expect(unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
```
REPLACE:
```
    expect(ledger.outstanding, 'double POSTs still outstanding when the case ended').toBe(0);
    expect(ledger.unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
```

**Claims after M6, and why each is true.** The precondition is that the file's cases run one at a time: the file has no `.concurrent`, and no `vite*.config.*` sets `sequence.concurrent`.
- C-1, "a POST to a double it installed carried a live token and any other body" fails the case. Narrowed at M7 (6.13, F7): this holds for a POST that passed the token check (a live token, `refuseEveryPost` unset); a POST the check refuses gets a 403 before `MEASURED` is consulted and is not recorded. `mine.unmeasured.push` runs before the throw, and the POST stays counted in `mine.outstanding` from entry until its `finally`. So at the case's `afterEach` either the body is in the ledger or the POST is still counted.
- C-2, "still outstanding when the case ends" fails the case. The increment comes before any `await`; the only decrement is that POST's own `finally`, on its own `mine`. `afterEach` has no `await`, so it sees one consistent state.
- C-3, "each case records both in its own ledger". `ledger` is written only at its declaration and in `beforeEach`. `installServer()` captures it into the closure constant `mine`, and every write to a ledger's fields goes through `mine`.
- C-4, "settles into that case's ledger, never a later one". This follows from C-3, whenever the release fires: inside the case, after it, through fake timers, or never.

Routes by which a case could end green, and their status:
- Several `installServer()` calls in one case: they capture the same ledger. Closed.
- A second `hold()`: POSTs waiting on the first gate stay counted until released. Closed.
- A release scheduled within the case: C-1 and C-2 hold whatever the order of microtasks. Closed.
- A release scheduled or late after the case: it touches only the old ledger. That case has already failed. Closed.
- `afterAll` drains: the file has none. If one existed, it would touch only old ledgers.
- Fake timers: the file uses none. Timers only change when a release fires, which the two release routes above already cover.
- A POST arriving after the case's `afterEach`: the spy has been restored, so it never enters that double. If it enters a later case's double, it is counted there, which gives a red result, not a green one.

Not claimed (recorded, not repaired): the double keeps its own records per case but does not isolate the store. A save that an earlier, failing case left held still delivers its response to the shared `useSettingsStore`, including its module-level `applying` latch, if released later. That can only turn a later case red, and the run is already red.

Census: the store is unchanged and no mutant touches the guard. Each body gets the same answer as before; only the guard's counting moved into the per-case ledger. No rerun is required. The campaign of record is 9d, with the 9c failing sets; predicted 20 of 20 killed. If the store blob differs from `5ee13d2e`, rerun every row.

**R-14 Round-5 stop rule.** Record, do not repair (into the #1852 landing comment's "Not covered" or a #1820 wave item), any finding in the test double that:
- (1) needs a planted or modified case that itself fails, or a modified store;
- (2) only makes a case fail that should pass, under injection;
- (3) needs cases run concurrently, a second `fetch` spy, or a double installed outside a case;
- (4) concerns behaviour the file does not claim, such as store isolation across a failed case, or the wording or order of failure messages.

Repair only:
- a sentence among C-1 to C-4, or the header, that is false for a single case which otherwise passes on the unmodified store;
- anything in the store or production behaviour;
- any `tsc`, vitest or gate failure;
- any P1 or P2.

If round 5 has only record-class findings, the item lands. A repair-class finding confined to the double is repaired by narrowing that sentence in a comment only, with no new guard code.

## Amendment after review round 5 (2026-11-26)

F7 (P3, injected-only; the regression is the claim, not the code). The test double answers a POST with a 403 for `refuseEveryPost`, an unknown token or an expired one before it reads the body or looks it up in `MEASURED`, so a POST that the token check refuses is never recorded, whatever its body. The test file's header (since M4, restated at M6), C-1, D11, R-9 and the landing text say that any other body fails the case, which is false for such a POST. The Architect's decision at the round-five brake is to continue with F7 only: M7 restates each guarantee by the code path, in comments only, and the contract and `PROGRESS.md` sentences follow. F8 (the double hands the store its error entry and snapshot objects by reference) is recorded, not repaired, and R-13's sentence about module-level state is corrected.

### 6.13 `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` (M7; F7; comment lines only; on the file as committed at `9c553946`, LF, ASCII)

Pairs on `ui/src/store/__tests__/useSettingsStore.bf999.test.tsx` as committed at `9c553946`. Comment lines only; no other byte changes.

**F7-a** (header, lines 7-12)
SEARCH:
```
// time.monotonic, the double on the test's Date.now). A POST with a live token is answered from
// MEASURED, the router's answers to the exact bodies the cases send. A case fails when a POST to
// a double it installed carried a live token and any other body, or is still outstanding when the
// case ends (held or unsettled, so its body has not been read). Each case records both in its own
// ledger. The fixed snapshot, the 200 body, the hold and the injected faults are not router
// answers.
```
REPLACE:
```
// time.monotonic, the double on the test's Date.now). A POST the token check accepts (a live
// token, and refuseEveryPost unset) is looked up in MEASURED, the router's answers to the exact
// bodies the cases send: a listed body gets its measured answer; any other body is recorded in
// its case's ledger and the double throws. A case fails when a POST to a double it installed
// passed the token check and carried any other body, or is still outstanding when the case ends
// (held or unsettled, so its body has not been read). Each case records both in its own ledger.
// A POST the token check refuses gets a 403; its body is neither read nor recorded. The fixed
// snapshot, the 200 body, the hold and the injected faults are not router answers.
```

**F7-b** (`MEASURED` comment, lines 67-70)
SEARCH:
```
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body missing
// from the table is recorded in the case's ledger and refused, and afterEach fails the case on
// it. A POST reads its body only after the hold, so afterEach also fails a case whose ledger
// still counts a POST outstanding.
```
REPLACE:
```
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body that
// passed the token check and is missing from the table is recorded in the case's ledger and the
// double throws, and afterEach fails the case on it. A refused POST never reaches the table. A
// POST reads its body only after the hold and the token check, so afterEach also fails a case
// whose ledger still counts a POST outstanding.
```

**F7-c** (ledger comment, lines 82-84)
SEARCH:
```
// A case's record of its doubles: POSTs entered and not yet answered or thrown, and bodies with
// no measured answer. beforeEach gives each case a new ledger and installServer() captures it,
// so a POST an earlier case left outstanding settles into that case's ledger, never a later one.
```
REPLACE:
```
// A case's record of its doubles: POSTs entered and not yet answered or thrown, and bodies that
// passed the token check with no measured answer. beforeEach gives each case a new ledger and
// installServer() captures it, so a POST an earlier case left outstanding settles into that
// case's ledger, never a later one.
```
If a new line is wider than the widest existing comment line, rewrap the words without changing them.

**Each narrowed sentence checked against the double's code paths (line numbers at `9c553946`).**
| sentence | code path | holds |
|---|---|---|
| "the token check accepts (a live token, and refuseEveryPost unset)" | line 122: refused when `srv.refuseEveryPost`, `issuedAt === undefined`, or older than `TOKEN_LIFETIME_MS`; live means issued (line 148), not yet popped (line 121), and no more than 300000 ms old | yes |
| "is looked up in MEASURED ... a listed body gets its measured answer" | lines 125-126; 422 with the entry at line 133; `'ok'` gives a 200 with a fixed body (line 136), which the last sentence labels | yes |
| "any other body is recorded in its case's ledger and the double throws" | line 128 `mine.unmeasured.push`, then the throw at line 129; `mine = ledger` at install (line 92) | yes, for a double installed inside a case (R-14 (3) otherwise) |
| "A case fails when a POST ... passed the token check and carried any other body" | the push comes before the throw; `afterEach` line 172 checks `unmeasured` is `[]` | yes (cases run one at a time, the 6.12 precondition) |
| "or is still outstanding when the case ends" | increment at line 113 before any await; decrement in `finally` at line 138; `afterEach` line 171 | yes; also holds under `refuseEveryPost`, because the increment comes before line 122 |
| "Each case records both in its own ledger" | `beforeEach` line 165; capture at line 92 (C-3) | yes |
| "A POST the token check refuses gets a 403; its body is neither read nor recorded" | line 123 returns before line 125 reads `init.body`; nothing is pushed | yes; this is F7's planted case, which `probe_f7.py` shows passing |
| "A refused POST never reaches the table" | line 123 returns before line 126 | yes |
| "reads its body only after the hold and the token check" | line 118, then line 122, then line 125 | yes |
| "bodies that passed the token check with no measured answer" | line 128 is reachable only past line 122 | yes |

**Claims after M7.** C-1 as narrowed (E-51), C-2, C-3 and C-4 of 6.12, each for a single case on the unmodified store, under 6.12's precondition. The quoted header and comment text inside sections 6.9 to 6.12 is the record of what M1 to M6 built. 6.13 supersedes it and does not edit it.

**Not claimed (F8, recorded for the #1820 wave).** The store keeps the 422 entry by reference (`useSettingsStore.ts`: 251, unchanged from the base). The double hands the store the module-level `INT_PARSING` object, inside a new `errors` array (line 133), and the nested objects of `SNAPSHOT`, through a one-level spread (line 149). A case that changes them in place can turn a later, unchanged case red.

**Census.** Not rerun: the store blob is unchanged, every row S-M1 to S-M20 mutates the store, and no non-comment byte of the test file changes. If the comment-stripped comparison differs, rerun every row.

**R-16 Round-6 stop rule.** Round 6 may repair only these:
- a non-comment byte of the test file that differs from `9c553946`;
- a sentence that 6.13 or E-48 to E-57 writes or changes, if it is false as written for a single case on the unmodified store. The repair is to delete that sentence, not to narrow it again;
- any `tsc`, vitest or gate failure;
- any P1 or P2;
- anything in the store or in production behaviour.

Everything else is recorded in the landing comment's "Not covered" or in the #1820 wave item. That includes any sentence the delta did not change, the historical text quoted in 6.9 to 6.12, and every class in R-14 (1) to (4). If round 6 has only record-class findings, the item goes to the gate. A deletion repair still needs a new brake decision before any round 7.
### 6.14 `PROGRESS.md` (M7; E-57; on the file as committed at `9c553946`, LF)

**E-57** (the BF-999 paragraph, line 3)
SEARCH:
```
answers each save only from the router's measured answers to the four bodies the cases send (any other body fails the case)
```
REPLACE:
```
answers each save whose token it accepts only from the router's measured answers to the four bodies the cases send (any other body of such a save fails the case)
```

## 7. Mutation census and generated-artifact commands

Each mutant is applied to the M3 candidate's store; 6.5 leaves every S-M1 to S-M19 locator unchanged. Runner: `npx vitest run src/store/__tests__/useSettingsStore.bf999.test.tsx src/components/settings/__tests__/SettingsPanel.test.tsx`. Single-line mutants are written `from -> to`; whole lines, with their indentation.

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
| S-M20 | delete `              csrfFetchedAt: 0,` (14 spaces, the refresh-failure set; locator `exact`, or `nth` 2 of the stripped line, whose first hit is the initial state) | T13, T14 (second posts assertion: `['t1']`) |

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
- **R-1 Token contract.** The router is byte-unchanged. No POST carries a token the store knows an earlier POST carried: `csrfFetchedAt` is set to 0 before `fetch` is called. A token is used only while `Date.now() - csrfFetchedAt < 240000`. A failed refresh read sets `csrfFetchedAt` to 0 (D8).
- **R-2 Draft kept on refusal.** Only the 200 branch clears `draft`/`draftCount`. The draft is kept on a 403 (both), 422, 400, other statuses, a thrown POST and a failed token read. `applyDraft` contains no `openSettings()` call.
- **R-3 No double POST.** `applying` is set before the first `await` and cleared in `finally`, which runs after every `return` inside `try`.
- **R-4 Bounded.** At most two GETs and two POSTs per press. The resend happens only on a 403 at attempt 0. No recursion and no timer.
- **R-5 What a refresh touches.** It sets `snapshot` and `csrfFetchedAt` only. `loadSnapshot` and `openSettings` change only by stamping `csrfFetchedAt` on success.
- **R-6 Clock.** `Date.now()` is used for both the stamp and the check. A wall-clock jump against the router's monotonic clock is handled by the one resend, which is untested for the clock case. T13 and T14 step `Date.now()` back after a failed refresh and require a read first (D8).
- **R-7 Types and style.**
  - `csrfFetchedAt` is in `SettingsState` and in the initial state, and `npx tsc -b` is clean.
  - No new dependency and no new `any`; new text is ASCII.
  - U+2014 remains only in the unchanged 422 and 400 messages and the untouched lines 1 and 107.
  - No token value appears in any message.
- **R-8 No other readers.** No `?raw` reader, no Python test touched, and `tests/test_ad741_config_api.py` is unchanged. The settings vitest set and the full `npx vitest run` are green.
- **R-9 Tests cross the seam.**
  - T12 clicks the real APPLY twice in one session.
  - The double spends the token before it reads the body (a 403 reads nothing) and refuses an unknown token, or one older than `300000` ms by `Date.now()` (`config.py`:55-71, read). A POST that passes the token check (a live token, `refuseEveryPost` unset) is answered only from `MEASURED`, the router's measured answers to the four bodies the cases send (D11, 9c); a POST the check refuses gets a 403 and its body is neither read nor recorded (M7, F7). Any other body of a POST that passed the check is recorded, refused with a thrown error, and fails the case in `afterEach`; so does a POST that entered the case's double and is still outstanding when the case ends (M5, F5); both are recorded in that case's own ledger (M6, F6). The snapshot, the 200 body, the hold and the injected faults are labelled as not router answers.
  - Every red case is red on `f7acb948` at its posts assertion (section 5).
- **R-10 Round-1 delta.** The store change is the one `csrfFetchedAt: 0` line and its comment in the refresh-failure `set`. T1 to T12 keep their order. T13 and T14 are appended. No component, router or other test changes.
- **R-11 Round-2 delta.** Only the test file (6.9) and the BF-999 paragraph of `PROGRESS.md` (6.10) change. T1 to T14, the store, `DECISIONS.md`, every component and every other test are byte-unchanged.
- **R-12 Round-3 delta.** Only the test file (6.11) changes: the counter, its reset, the try/finally around the unchanged POST statements, the `afterEach` assertion and three comments. T1 to T14, `MEASURED`, the store, `PROGRESS.md`, `DECISIONS.md` and every other file are byte-unchanged.
- **R-13 Round-4 delta.** Only the test file (6.12) changes: `Ledger`, `ledger`, `mine`, the three substitutions in the POST branch, the `beforeEach` reset, the two `afterEach` expects and three comments. The other statements of the POST branch, T1 to T14, `MEASURED`, the store, `PROGRESS.md`, `DECISIONS.md` and every other file are byte-unchanged. No module-level binding is reassigned except `ledger` (by `beforeEach`), and the double writes no module-level object except the ledger it captured, through `mine`; it only reads `SNAPSHOT`, `INT_PARSING` and `MEASURED`, and hands the store `INT_PARSING` itself and the nested objects of `SNAPSHOT` by reference (F8, recorded in 6.13). C-1 (as narrowed by 6.13) to C-4 of 6.12 are each true for any case of the file on the unmodified store. Findings are classified by R-14.
- **R-15 Round-5 delta (M7).** Only comment lines of the test file (6.13), the BF-999 paragraph of `PROGRESS.md` (E-57) and this contract change; the test file's non-comment lines are identical to `9c553946`. The store, `DECISIONS.md` and every other file are byte-unchanged. Findings are classified by R-16.

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

Proof: ui/src/store/__tests__/useSettingsStore.bf999.test.tsx, 14 cases with the real store and the real SettingsPanel (two APPLY clicks in one page session) against a fetch double that follows the order of src/probos/routers/config.py (a token per GET, spent by every POST before the body is read, refused after 300 s) and answers each save whose token it accepts only from the router's answers measured for the four bodies the cases send; any other body of such a save fails the case. On the unrepaired store 12 of 14 fail and the 2 guard cases pass; the two probe cases in this issue's body, which assert the defect, fail on the repair. Mutation census 20 of 20 killed.

Not covered: no browser run. Date.now() can disagree with the router's monotonic clock after a sleep or clock change; the single resend covers that case, and a failed token read marks the token spent so a clock step cannot revive it. A field edited while a save is in flight is still cleared by that save's 200 (unchanged). The APPLY button is not disabled during a save; a second press does nothing. A save of hot-reload fields takes effect at once, but the dialog still says "Restart required to take effect." (unchanged; a separate issue). The test double keeps its records per case but does not isolate the store: a save that an earlier, failing case left held still reaches the shared store if released later, which can only turn a later case red. The double also hands its constant error entry and snapshot objects to the store by reference, so a case that changes them in place can turn a later case red (recorded for #1820).
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

### 9b Review round 1 repair re-proof (orchestrator, 2026-11-26)

Measured on the oracle tree `oc1` (the M1 and M2 candidate, head `418cc977`, with the amendment pairs applied on top; `rvcbase` for the base). Every prediction of the amendment held.

- Pairs: the 10 pairs of 6.5 to 6.8 apply, each SEARCH occurring once at its turn (the store keeps CRLF throughout: 294 lines; the added lines are the comment and `csrfFetchedAt: 0,` and nothing else).
- A/B on the round-1 store (the committed `f7086568` store): the amended file has 14 cases, 2 failed (T13 and T14), 12 passed. Both fail at `expect(srv.posts).toEqual(['t2'])`, received `['t1']`.
- A/B on the original base `f7acb948`: 12 failed, 2 passed (T1 and T6). T3 still fails first at its posts assertion (`['t1', 't1']`); T14 fails at `expect(srv.posts).toEqual([])`, received `['t1']`.
- M3 candidate: the new file passes 14 of 14; the focused list gives 10 files, 80 passed; `npx tsc -b` prints nothing and exits 0 (the inferred return type of `readPatch` passes).
- The F1 probe (it asserts the defect: an aged token whose refresh fails keeps its stamp) passed on the round-1 store and now fails at its first claim, `csrfFetchedAt` being 0 where it expects 1000000, after its premises held (no POST, two reads, status rejected).
- Census (`mutants_bf999.py`, 21 cases on the unmutated candidate, all passing): rows S-M1 to S-M20 are all killed and no row survives. S-M20 is killed by exactly T13 and T14. Every killer the table names fails. Rows that fail more cases than they name: S-M2 (13), S-M3 (7), S-M5 (9), S-M6 (4), S-M7 (3), S-M8 (3), S-M10 (10), S-M11 (2), S-M13 (13), S-M14 (4), S-M15 (4) and S-M19 (11).
- Trackers: 6.7 and 6.8 apply once each; `scripts/gen_ad_ledger.py --check` still reports the ledger current without regeneration (no heading changed).
- Delta 5: the false sentence about the live config appears only in the replayed 6.4 block and in the SEARCH text of 6.7; the notes under the headings 6.1 to 6.4 (correction C-4) say what M3 supersedes. The prompt scan is clean on this file.
- Real-router facts behind F2 and F3 (a TestClient over the unchanged router, measured on the head): `system.log_level` set to `BAD` is answered 200; `memory.max_episodes` set to `not-an-int` is answered 422 with the entry `{loc: [memory, max_episodes], type: int_parsing}`; `5000`, `'5000'` and `-1` are answered 200; a bad token with a malformed body is answered 403 and a good token with one 400; a token a 400 or a 422 carried is spent; a save of `cognitive.offline_stt_enabled` is answered 200 with `restart_required` false and the next read returns the new value.

### 9c Review round 2 repair re-proof (orchestrator, 2026-11-26)

Measured on the oracle tree `oc1` (the M3 candidate, head `fa73f33a`: store `5ee13d2e`, test file `6a70f990`, `PROGRESS.md` `7cf47065`, `DECISIONS.md` `fae55d23`, all equal to the committed blobs) with the amendment pairs applied on top. Every prediction of the amendment held.

- Pairs: the five pairs of 6.9 and the pair of 6.10 apply, each SEARCH occurring once at its turn (the test file is LF in the tree, `PROGRESS.md` CRLF).
- The router's answers to the four exact bodies the cases POST (a TestClient over the unchanged router, `create_app`, a temporary config, a fresh token for each, the body sent as the raw string): the DEBUG body 200; the INFO body 200; the Vessel plus `not-an-int` body 422 `validation_failed` with exactly one entry, `{loc: [memory, max_episodes], msg: "Input should be a valid integer, unable to parse string as an integer", type: int_parsing}`; the Vessel plus `'5000'` body 200. The table in 6.9 equals these answers. The 200 bodies differ per save (`changed_fields` is `[system.log_level]`, then `[]` because the live config already says INFO, then `[memory.max_episodes, system.name]`), which is why the double's 200 body is a labelled fixed literal; the store reads only a 200's status.
- Amended file: 14 of 14 pass, so each case sends exactly one of the four bodies (any other would trip the check). The focused list gives 10 files, 80 passed; `npx tsc -b` prints nothing and exits 0 (the `Map` typing and the `expect(value, message)` form pass).
- Tripwire, fired once in a scratch copy (not committed): T3's save of `'5000'` changed to `'+5000'` gives 1 failed, 13 passed. T3 fails twice: at its own patches assertion (the POST threw, so no patch was recorded) and in `afterEach`, which names the body `{"patch":{"system":{"name":"Vessel"},"memory":{"max_episodes":"+5000"}}}`. The scratch copy was removed.
- A/B: on the original base `f7acb948` the amended file gives 12 failed, 2 passed (T1 and T6, identified by the JSON reporter); on the round-1 store the 14 cases fail only T13 and T14 (census row S-M20 removes the same line, and exactly those two cases fail). The store and T1 to T14 are byte-unchanged by 6.9.
- Census (`mutants_bf999.py`, re-run on the amended file though the amendment said no rerun was needed): 21 cases unmutated, all passing; rows S-M1 to S-M20 are all killed with the same case counts as 9b, and every named killer fails.
- `scripts/gen_ad_ledger.py --check` reports the ledger current (no heading changed). The prompt scan is clean on this file.
- Correction C-5: E-28 would have put R-11 before the R-10 line (its SEARCH is a prefix of that line); R-11 is placed after the whole R-10 line.
- Claims about the double: the old rule sentences (`behaves like`, the integer regex, `any string`, the 400 `invalid_json` branch, `readPatch`) now appear only in the replayed 6.2 and 6.6 blocks, in the SEARCH text of 6.9, and in D10 and D11 where they are marked as built at M3 and superseded.

### 9d Review round 3 repair re-proof (orchestrator, 2026-11-26)

Measured on the oracle tree `oc1` (the M4 candidate, head `579c8c14`: store `5ee13d2e`, test file `167b8d77`, `PROGRESS.md` `9a897c07`, `DECISIONS.md` `fae55d23`, all equal to the committed blobs) with the five pairs of 6.11 applied on top. Every prediction of the amendment held.

- Pairs: the five pairs of 6.11 apply, each SEARCH occurring once at its turn (the test file is LF in the tree).
- Amended file: 14 of 14 pass. The focused list gives 10 files, 80 passed; `npx tsc -b` prints nothing and exits 0 (the `init` narrowing holds inside the try).
- Probe O-1 (the reviewer's scenario, a scratch copy with one extra case appended, not committed): the case holds a POST whose body is `{"patch":{"memory":{"max_episodes":"+5000"}}}` and ends without releasing it. It now fails in `afterEach` with "double POSTs still outstanding when the case ended: expected 1 to be +0" (1 failed, 14 skipped by the name filter); on the M4 file the same case passed (round 3's probe).
- Probe O-2 (a scratch copy with `outstanding -= 1;` commented out): all 14 cases fail in `afterEach` with "double POSTs still outstanding" (expected 1, or 2 where a case sends two POSTs to 0). The scratch copies were removed and the real file is byte-identical to what 6.11 produces.
- A/B on the original base `f7acb948` (JSON reporter): 12 failed, 2 passed (T1 and T6), as at M4.
- Census (`mutants_bf999.py`, re-run on the final file though the amendment said none was needed): 21 cases unmutated, all passing; rows S-M1 to S-M20 are all killed and the failing set of every row equals the 9c campaign's, so the counter adds no kill and loses none.
- `PROGRESS.md` and `DECISIONS.md` are untouched by M5, so `scripts/gen_ad_ledger.py --check` still reports the ledger current. The prompt scan is clean on this file.
- Corrections: C-5 style placement for E-35 (the M5 gate line after the M4 line) and E-37 (R-12 after the whole R-11 line) because their SEARCH strings are prefixes of the neighbouring line; C-6 the provenance and status lines; C-7 the M5 row of the milestones table; C-8 a note under the 6.9 heading.

### 9e Review round 4 repair re-proof (orchestrator, 2026-11-26)

Measured on the oracle tree `oc1` (the M5 candidate, head `736bf5c9`: store `5ee13d2e`, test file `84268889`, `PROGRESS.md` `9a897c07`, `DECISIONS.md` `fae55d23`, all equal to the committed blobs) with the eight pairs of 6.12 applied on top. Every prediction of the amendment held.

- Pairs: the eight pairs of 6.12 apply, each SEARCH occurring once at its turn (the test file is LF in the tree). The amended file has the blob `dbfa680e`.
- Amended file: 14 of 14 pass. The focused list gives 10 files, 80 passed; `npx tsc -b` prints nothing and exits 0.
- Absence claims of 6.12, enumerated with `rg` over the amended file and the configs: no `.concurrent`, no fake timers, no `afterAll`, no `setTimeout`; `ui/vitest.config.ts` has no `sequence` key, and the only `sequence` among the `vite*.config.ts` files is a mock payload field at `ui/vite.approval-ui.config.ts:77`. The three `it.each` tables run their rows one after another.
- Probes, run by `probes_m6.py` on scratch test files in the oracle tree (removed afterwards, none committed). Each states its expected outcome and fails the run when it differs.
- Probe O-1: a control case that settles a save passes; a case that holds a POST and ends without releasing it fails in `afterEach` with "double POSTs still outstanding when the case ended: expected 1 to be +0", and that is its only failure message.
- Probe O-2: with `mine.outstanding -= 1;` commented out in the whole file, all 14 cases fail in `afterEach` with that message (14 failed, 0 passed).
- Probe O-3: the reviewer's scheduled-release scenario (fake timers; case 1 holds a measured POST and schedules its release with `setTimeout`, case 2 holds its own unmeasured POST while that release fires). On M6 both cases fail, case 2 with its own held POST counted (expected 1 to be +0). The same scenario on the M5 test file (blob `84268889`) is the control: case 1 fails and case 2 passes, which is F6 reproduced.
- Probe O-4: two `installServer()` calls in one case, the first double's POST held and never released. The case's own `expect(ledger.outstanding).toBe(1)` after the second call passes, so the ledger is shared, and the case then fails in `afterEach` with expected 1 to be +0 (one failure message). Its control case passes.
- A/B on the original base `f7acb948` (JSON reporter): 12 failed, 2 passed (T1 and T6), as at M5.
- Census (`mutants_bf999.py`, re-run on the final file though the amendment said none was needed): 21 cases unmutated, all passing; rows S-M1 to S-M20 are all killed and the verdict and failing set of every row equal the M5 campaign's, so moving the counters into a ledger adds no kill and loses none.
- `PROGRESS.md`, `DECISIONS.md` and the store are untouched by M6, so `scripts/gen_ad_ledger.py --check` still reports the ledger current. The prompt scan is clean on this file.
- Corrections: C-9 the status line keeps the comma after M3 (the answer's SEARCH starts at "and M4" and would have dropped it, because the v4 text has no comma there); C-10 a note under the 6.11 heading that 6.12 moves its module-level state into a ledger. The M6 gate line and R-13 are placed after the whole M5 and R-12 lines, as the answer says (C-5 style).

### 9f Review round 5 repair re-proof (orchestrator, 2026-11-26)

Measured on the oracle tree `oc1` (the M6 candidate, head `9c553946`: store `5ee13d2e`, test file `dbfa680e`, `PROGRESS.md` `9a897c07`, `DECISIONS.md` `fae55d23`, all equal to the committed blobs) with the three pairs of 6.13 and the pair of 6.14 applied on top. Every prediction of the amendment held.

- Pairs: the three pairs of 6.13 and the pair of 6.14 apply, each SEARCH occurring once at its turn (the test file is LF in the tree, `PROGRESS.md` is CRLF). The amended test file has the blob `40f6b459` (352 lines) and `PROGRESS.md` the blob `0bf28dc4`.
- Comment-only proof: `tokens_equal.mjs` parses the committed `9c553946` test file and the amended one with the TypeScript compiler (TSX) and compares every leaf token: the two sequences are identical (3095 tokens). Every added or removed line of `git diff -U0` (+17 -13, 30 lines) matches `^[-+]\s*//`. The widest new comment line is 96 characters and the widest existing one 109, so no line is rewrapped. The tool's own self-test passes: a comment-only edit keeps the sequence; a code edit, and an edit inside a string that holds `//`, change it; a syntax error exits 2.
- Amended file: 14 of 14 pass; `npx tsc -b` prints nothing and exits 0; A/B on the original base `f7acb948`: 12 failed, 2 passed (T1 and T6).
- Probe F7 (`probe_f7.py`, scratch files removed afterwards): a case that sends the body `{"patch":{"memory":{"max_episodes":"+5000"}}}` with `refuseEveryPost` set (two POSTs `['t1','t2']`, status `rejected`) passes, which is what 6.13 now says (a POST the token check refuses is neither read nor recorded); the control, the same save without `refuseEveryPost`, fails in `afterEach` on the unmeasured list. The result on the M6 file is the same.
- Probe F8 (the same script): a case that changes the error entry the store kept (`applyErrors[0].msg`) makes the next, unchanged case fail; the control pair passes. Recorded in 6.13, not repaired.
- No over-broad sentence left: `rg -n "carried a live token and any other body|A live-token POST|no module-level mutable"` finds no hit in the amended test file, `PROGRESS.md` or `DECISIONS.md`; in the contract it finds only the M6 pair text in 6.12, the quoted opening of C-1 (followed by its narrowing) and the old header text that 6.13 replaces. A wider search (`any other body`, `fails the case`, `answers each save`) finds the other sentences in D11, R-9, 6.14 and the landing text, each now narrowed or true as written.
- `scripts/gen_ad_ledger.py --check` still reports the ledger current after the `PROGRESS.md` edit, so the ledger pair does not change. The census is not rerun: the store blob is `5ee13d2e` and no non-comment token of the test file changed. The prompt scan is clean on this file.
- Corrections: C-11 E-49 keeps a comma after M4 (the answer's replacement would drop it); C-12 the 6.13 heading carries its path and the pairs use the contract's own labels F7-a to F7-c; C-13 the M7 row of the milestones table and the M7 gate line; C-14 R-13 names exactly what the double hands the store (`INT_PARSING` itself, the nested objects of `SNAPSHOT`); C-15 the landing text says "constant" where the answer uses another word, which the release-word scan of a posted comment flags; C-16 a note under the 6.12 heading; C-17 the M7 subject takes the branch's house style (the answer's subject has a `test(ui):` prefix that no commit on main uses); C-18 the code-path table's ellipses are written as three dots.
