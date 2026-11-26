# BF-1000: the HXI settings store reads the save's restart_required flag; a save the router applied at once shows "applied" and the live values

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (revision 1: the orchestrator's findings F1 to F6: a null-safe flag read, the consumer table, three stale-state mutants, the double's comment, wording and counts; revision 2: G1, section 10 lists all 21 hot-reload ids, and G2, the empty-save wording in sections 1 and 6.3)
**Corrected by:** the orchestrator, 2026-11-26: the words "in registry order" are deleted from the Absence Verified entry of section 10 (the list was printed sorted by id, which is not the declaration order of `section_registry.py`; the order was the orchestrator's wording in the revision-2 request, not the Architect's).
**Status:** ready to build. **Owning issue:** #1855 only. Commits say `Refs #1855.`
**Base:** `d09c14f13f0251ae6704f7f05411fd3e665930c7` (= origin/main), branch `feat/bf1000-1855-hxi-settings-restart-flag-20261126`. **Number:** BF-1000 (section 10).
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 5 new tests (3 cases, one of them a three-row `it.each`) in 1 new file (`ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx`), 0 removed, 0 changed.
**Scope:** `ui/src/store/useSettingsStore.ts`, the new test file, `PROGRESS.md`, `DECISIONS.md` and the regenerated ledger files. No Python file changes.

## 1. Problem (premise table)

| Where | What it does today | Premise it gets wrong |
|---|---|---|
| `useSettingsStore.ts`:240-247, the 200 branch of `applyDraft` | sets `applyStatus: 'restart_required'` and `applyMessage: 'Restart required to take effect.'`, clears the draft; `body` is parsed at :238 and not read | that every 200 needs a restart |
| `config.py`:384-386 and :387-395 | `restart_required = not (changed_fields and all(p in hot_reload_paths ...))`; when false, each changed field is written into `runtime.config` before the answer at :433 | n/a (the router is right) |
| `useSettingsStore.ts`:240-247 | keeps the pre-save `snapshot` | that the live config did not change; `get_config` (`config.py`:232-234) returns `runtime.config`, so after an applied save the next GET holds the new value |
| `SettingsTopBar.tsx`:112 | renders `settings-restart-banner` ("PROBOS RESTART REQUIRED") for `'restart_required'` | follows the store |

Effect: a save that changes at least one field, all of them hot-reload (for example `cognitive.offline_stt_enabled`, `section_registry.py`:127-137) is live at once, yet the dialog says to restart and the store's snapshot keeps the old value until the next GET.

## 2. Overview

In the 200 branch, `body?.restart_required === false` (strict, null-safe) means applied. Then the store awaits `_fetchSnapshot()` and makes ONE `set`: `applyStatus: 'success'`, a short message, `applyErrors: []`, the cleared draft and, when the read returned a snapshot, `snapshot` and `csrfFetchedAt: Date.now()`. A failed read keeps the old snapshot and leaves `csrfFetchedAt` at 0 (set at :229), so the next press reads a token first. Any other 200 body (flag true, missing, not the boolean false, unparsable or null) takes today's branch unchanged.

Rejected, one line each:
- A new status member (`'applied'`): `'success'` is already in the union (:53) and nothing reads it (section 10); a new member changes the type for no reader.
- Merging the sent patch into the old snapshot without a GET: the router coerces values (pydantic), so the live GET is the authority.
- Calling `loadSnapshot()` for the refresh: it returns early once loaded (:132) and resets `selectedSectionId`, `applyStatus` and `applyMessage` (:146-149).
- Refreshing after every 200: a restart-required save does not change `runtime.config`, so the read would show nothing new.
- Keeping edits typed while the save is in flight (draft diffing): the POST window already loses them today; out of scope (section 11).
- Changing the router's answer for an empty change set: a recorded limit, not this defect.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Applied only when `body?.restart_required === false` | A missing, malformed or null body keeps the safe (banner) behaviour; `body` is `{}` after a parse failure (:238) and `null` for a JSON `null` |
| D2 | Await the refresh, then one `set` per outcome | The field shows the draft value until the live value replaces it; no frame shows the old value with the draft cleared |
| D3 | The draft is cleared in that final `set`, after the refresh | Same as D2; the cost is a longer in-flight window (section 11) |
| D4 | Messages: `Saved and applied. No restart needed.`; when the read fails, `Saved and applied. No restart needed. Could not reload the values (<reason>).` | The operator sees the old value in that case and is told why |
| D5 | A successful refresh records `csrfFetchedAt: Date.now()` | The refreshed snapshot carries a live token, so the next save sends it without a further GET |
| D6 | Both new `set`s clear `applyErrors` | `SettingsMain.tsx`:233-237 renders them as field errors; a stale error from an earlier refused save must not outlive an applied one |
| D7 | No change to `SettingsTopBar.tsx`, the router or the BF-999 test file | The banner already keys on `'restart_required'` only |

## 4. Milestones and commits

- **M1:** 6.1 and 6.2. Subject: `HXI settings store reads the save's restart_required flag`
- **M2:** 6.3 and 6.4, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Trackers for the settings applied flag`

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Stage explicit paths only.

## 5. Builder: may and may not

- **May:** apply the pairs in order, run `gen_ad_ledger.py` (M2), `git diff --check`, `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, add `skip`/`only`/a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `ui/src/store/useSettingsStore.ts` (M1)

**P1.** SEARCH:
```ts
        if (resp.status === 200) {
          set({
            applyStatus: 'restart_required',
            applyMessage: 'Restart required to take effect.',
            applyErrors: [],
            draft: {},
            draftCount: 0,
          });
        } else if (resp.status === 422) {
```
REPLACE:
```ts
        if (resp.status === 200 && body?.restart_required === false) {
          // The router wrote the change into the running config, so show the live values.
          const fresh = await _fetchSnapshot();
          if (typeof fresh === 'string') {
            set({
              applyStatus: 'success',
              applyMessage: `Saved and applied. No restart needed. Could not reload the values (${fresh}).`,
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          } else {
            set({
              snapshot: fresh,
              csrfFetchedAt: Date.now(),
              applyStatus: 'success',
              applyMessage: 'Saved and applied. No restart needed.',
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          }
        } else if (resp.status === 200) {
          set({
            applyStatus: 'restart_required',
            applyMessage: 'Restart required to take effect.',
            applyErrors: [],
            draft: {},
            draftCount: 0,
          });
        } else if (resp.status === 422) {
```

### 6.2 `ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx` (New file, M1)

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import SettingsPanel from '../../components/settings/SettingsPanel';
import { useSettingsStore } from '../useSettingsStore';

const FIELD = 'cognitive.offline_stt_enabled';
const APPLIED = { ok: true, restart_required: false, changed_fields: [FIELD] };
const STALE = [{ loc: ['cognitive', 'offline_stt_enabled'], msg: 'x', type: 'value_error' }];

function jsonResp(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

interface Server {
  gets: number;
  posts: string[];
  live: boolean;
  failNextGet: boolean;
}

function installServer(answer: unknown): Server {
  const srv: Server = { gets: 0, posts: [], live: false, failNextGet: false };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) !== '/api/config') throw new Error(`unexpected request ${String(input)}`);
    if (init?.method === 'POST') {
      srv.posts.push((init.headers as Record<string, string>)['X-Probos-CSRF']);
      if ((answer as { restart_required?: unknown } | null)?.restart_required === false) {
        srv.live = JSON.parse(String(init.body)).patch.cognitive.offline_stt_enabled;
      }
      return jsonResp(answer);
    }
    srv.gets += 1;
    if (srv.failNextGet) {
      srv.failNextGet = false;
      return jsonResp({ error: 'unavailable' }, 503);
    }
    return jsonResp({
      config: { cognitive: { offline_stt_enabled: srv.live } },
      secret_present: {},
      sections: [{
        section_id: 'cognitive', label: 'Cognitive', glyph: '*', domain: 'Core', description: '',
        fields: [{ field_id: FIELD, label: 'Offline STT', kind: 'bool', enum_values: [], description: '', hot_reload: true }],
      }],
      domain_counts: { Core: 1 },
      domain_order: ['Core'],
      section_count: 1,
      config_path: '/tmp/system.yaml',
      uptime_seconds: 1,
      csrf_token: `t${srv.gets}`,
    });
  });
  return srv;
}

const s = () => useSettingsStore.getState();

async function save(value: boolean): Promise<void> {
  s().setDraftField(FIELD, value);
  await s().applyDraft();
}

describe('BF-1000 the settings store reads restart_required from a 200 (#1855)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
  });

  it('an applied save shows no restart banner, the live value and a clear draft and errors, and the next save needs no extra read', async () => {
    const srv = installServer(APPLIED);
    await act(async () => { await s().openSettings(); });
    render(<SettingsPanel />);
    act(() => { useSettingsStore.setState({ applyErrors: STALE }); });
    act(() => { s().setDraftField(FIELD, true); });
    fireEvent.click(screen.getByTestId('settings-topbar-apply'));
    await waitFor(() =>
      expect(screen.getByTestId('settings-status-message').textContent).toBe('Saved and applied. No restart needed.'),
    );
    expect(screen.queryByTestId('settings-restart-banner')).toBeNull();
    expect(s().applyStatus).toBe('success');
    expect(s().applyErrors).toEqual([]);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(true);
    expect(s().draft).toEqual({});
    expect(s().draftCount).toBe(0);
    expect(srv.posts).toEqual(['t1']);
    expect(srv.gets).toBe(2);
    await act(async () => { await save(false); });
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(3);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
  });

  it.each([
    { label: 'no flag', answer: { ok: true, changed_fields: [FIELD] } as unknown },
    { label: 'a flag of 0', answer: { ok: true, restart_required: 0, changed_fields: [FIELD] } as unknown },
    { label: 'a null body', answer: null as unknown },
  ])('a 200 with $label keeps the restart status and the snapshot, and reads nothing more', async ({ answer }) => {
    const srv = installServer(answer);
    await s().openSettings();
    await save(true);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe('Restart required to take effect.');
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
    expect(srv.gets).toBe(1);
  });

  it('an applied save whose reload fails still reports applied, keeps the old values, and the next press reads a token first', async () => {
    const srv = installServer(APPLIED);
    await s().openSettings();
    useSettingsStore.setState({ applyErrors: STALE });
    srv.failNextGet = true;
    await save(true);
    expect(s().applyStatus).toBe('success');
    expect(s().applyMessage).toBe('Saved and applied. No restart needed. Could not reload the values (config GET failed: 503).');
    expect(s().applyErrors).toEqual([]);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
    expect(s().draft).toEqual({});
    expect(s().draftCount).toBe(0);
    expect(srv.posts).toEqual(['t1']);
    expect(srv.gets).toBe(2);
    await save(false);
    expect(srv.posts).toEqual(['t1', 't3']);
    expect(srv.gets).toBe(4);
  });
});
```

### 6.3 `PROGRESS.md` (M2)

**P2.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-1000 (2026-11-26), #1855 -- a settings save the router applied at once no longer says a restart is required, and the dialog shows the live values.** For a save that changes at least one field, all of them hot-reload, `POST /api/config` answers `restart_required: false` and has then already written them into the running config (BF-299); the HXI store ignored the flag, showed "Restart required to take effect." and the PROBOS RESTART REQUIRED banner after every 200, and kept its pre-save snapshot. `useSettingsStore.applyDraft` now treats a 200 whose flag is the boolean false as applied: it reloads the snapshot, then sets status `success` with "Saved and applied. No restart needed.", the live values and no field errors; when the reload fails it says so and keeps the old snapshot, and the next press reads a token first. Any other 200, including a null body, keeps the restart banner. New `ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx` (5 tests). The router is unchanged. Contract `prompts/bf-1000-1855-hxi-settings-applied-flag.md`.
```

### 6.4 `DECISIONS.md` (M2)

**P3.** SEARCH:
```markdown
### BF-999 -- the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (2026-11-26, #1852)
```
REPLACE:
```markdown
### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)

- *Scope.* `ui/src/store/useSettingsStore.ts` (`applyDraft`); test `ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx`. Contract `prompts/bf-1000-1855-hxi-settings-applied-flag.md`. The router, `SettingsTopBar.tsx` and the banner are unchanged.
- *D1.* A 200 means applied only when `restart_required` is the boolean false; a missing or other value, or a null body, keeps the restart banner.
- *D2.* After an applied save the store reads `GET /api/config` (the live config) and then sets the status, the message, the snapshot, empty field errors and the cleared draft in one update; the refreshed token is recorded as fresh. This is a read after an applied save only, for display; BF-999 D1's rejection of a forced read after every save, for the token, stands.
- *D3.* The existing `'success'` member of `applyStatus` carries the applied state; no new member.
- *Rejected.* Merging the patch into the old snapshot (the router coerces values); reusing `loadSnapshot` (it returns early once loaded and resets the view); a read after a restart-required save (the running config did not change).
- *Known limits.* An edit typed between the APPLY press and the end of the reload is cleared with the draft, as one typed during the POST already was. A save with no changed field is answered `restart_required: true` by the router and still shows the banner.
- *Reversal.* Revert the commit; no API, persisted format or security control changes.

### BF-999 -- the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (2026-11-26, #1852)
```

## 7. Consumers

An applied save changes only fields in `hot_reload_paths` (`config.py`:378-386): 21 ids, listed in section 10. Rows marked "unchanged" read no such field.

| Consumer | What it reads | After the change |
|---|---|---|
| `SettingsTopBar.tsx`:112 | `applyStatus === 'restart_required'` | no banner for `'success'` |
| `SettingsTopBar.tsx`:147-181 (`SettingsStatusBar`) | `snapshot`, `draftCount`, `applyMessage`; in sync unless `'rejected'` | shows the new message in the existing colour |
| `SettingsMain.tsx`:216, :290 | `snapshot.config` per field | shows the live value |
| `SettingsMain.tsx`:303 | `perception.enabled` (hot-reload) | shows the live value |
| `SettingsMain.tsx`:233-237 | `applyErrors` as field errors | cleared by an applied save |
| `PerceptionLivePanel.tsx`:90; :587, :652, :669, :678 | `perception.enabled`; `perception.screen.enabled` (both hot-reload) | show the live value |
| `PerceptionLivePanel.tsx`:77 | the `cognitive` object (`llm_base_url_vision`, `llm_model_vision`: registered, not hot-reload) | unchanged |
| `IntentSurface.tsx`:112-113 and the effect whose deps are at :318 | `cognitive.offline_stt_enabled` (hot-reload) | the wake-word loop arms or disarms after the save, not at the next page load; the selector returns a boolean, so replacing the snapshot alone does not re-run it |
| `CameraLiveIndicator.tsx`:77, `WakeWordTrainerPanel.tsx`:67 | hot-reload booleans | follow the live value |
| `wakeWord.ts`:290-293 | `cognitive.custom_model_filename` (not a registered field) | unchanged |
| `App.tsx`:98-108, `CompactApp.tsx`:131, `CameraLiveIndicator.tsx`:71, `ConnectPhoneCard.tsx`:54-55, `LiveToolProgress.tsx`:15, `ProfileChatTab.tsx`:1662, `useStore.ts`:2657-2658, `CapabilityRequestCard.tsx`:29 and :53 | fields that are not registered (section 10) | unchanged; whole-object selectors re-render once, as they already do on BF-999's pre-save refresh (`useSettingsStore.ts`:225) |
| `SettingsPanel.test.tsx`:192-218, `useSettingsStore.bf999.test.tsx` (router double answers `restart_required: true` at :126), `LiveToolProgress.test.tsx`:165-169 | the restart branch, the token sequence | unchanged: a `true` flag takes the old branch and reads nothing more |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Every SEARCH in section 6 counted at its turn: 1 each; the new test file does not exist.
- Run the new file on the base: cases 1 and 3 fail; the three rows of case 2 pass (they kill M2 and M10; section 8.3).

### 8.2 Focused checks on the candidate (in `ui/`)

```
npx tsc -b
npx vitest run src/store/__tests__/useSettingsStore.bf1000.test.tsx src/store/__tests__/useSettingsStore.bf999.test.tsx src/components/settings src/components/profile/__tests__/LiveToolProgress.test.tsx src/components/capability/__tests__/ApprovalWave.test.tsx
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-1000-1855
```
Expected: all green; the BF-999 file and `SettingsPanel.test.tsx` pass unchanged.

### 8.3 Mutation rows (`useSettingsStore.ts`, one at a time, file restored byte for byte)

Counts are of whole stripped lines in the candidate file. `applyErrors: [],` occurs 6 times (:116, :148, :183, then the failed-reload `set`, the success `set`, the restart branch); `draftCount: 0,` 5 times (:109, :181, then the failed-reload `set`, the success `set`, the restart branch); `csrfFetchedAt: Date.now(),` 3 times (:145, :178, then the success `set`).

| ID | Line (stripped) | Becomes | Killed by |
|---|---|---|---|
| M1 | `if (resp.status === 200 && body?.restart_required === false) {` | `if (resp.status === 200 && false) {` | cases 1 and 3 |
| M2 | same line | `if (resp.status === 200 && !body?.restart_required) {` | case 2, all three rows |
| M3 | same line | `if (resp.status === 200) {` | case 2; the BF-999 file; `SettingsPanel.test.tsx`:192 |
| M4 | `snapshot: fresh,` | empty line | case 1 (the live value) |
| M5 | `csrfFetchedAt: Date.now(),` (3rd of 3) | empty line | case 1 (`['t1', 't2']`, 3 reads) |
| M6 | `if (typeof fresh === 'string') {` | `if (false) {` | case 3 |
| M7 | `applyErrors: [],` (4th of 6, the failed-reload `set`) | empty line | case 3 |
| M8 | `applyErrors: [],` (5th of 6, the success `set`) | empty line | case 1 |
| M9 | `draftCount: 0,` (3rd of 5, the failed-reload `set`) | empty line | case 3 |
| M10 | `if (resp.status === 200 && body?.restart_required === false) {` | `if (resp.status === 200 && body.restart_required === false) {` | case 2, row `a null body` (TypeError, status `rejected`) |

Case 2 passes on the base by construction (the base shows the banner for every 200); it is kept because it alone kills M2 and M10.

### 8.4 The batch gate

`scripts/run_test_gate.py --label bf-1000-1855 --receipt logs/gates/bf-1000-1855.receipt.json` once on the committed head. No Python file changes, so a red Python test is triaged by the standing rules.

## 9. Diff Reviewer: properties to verify

The change claims that a 200 answered `restart_required: false` shows status `success` and the live config, and that any other 200 behaves as before. The consumer that must accept it is the Settings dialog (`SettingsPanel` with `SettingsTopBar` and `SettingsStatusBar`) over the unchanged `src/probos/routers/config.py`.

1. A 200 whose body is any JSON value other than an object with `restart_required` the boolean false (including `null` and the `{}` of a parse failure) reaches the same `set` as the base, with no extra request.
2. After an applied save, each outcome of the reload ends in exactly one `set`, which clears `applyErrors` and the draft; a failed reload leaves `snapshot` and `csrfFetchedAt` as they were before that `set`.
3. The `applying` latch is still cleared in `finally` after the reload, and a press during the reload sends nothing.
4. No other branch of `applyDraft` (403 resend, 422, 400, other status, thrown error) changes.
5. The new test file holds its own double, imports nothing from the BF-999 file, and its token and read counts follow from the double.
6. ASCII and LF in all new text; no file outside section 4 changes.

## 10. Verified Against Codebase (2026-11-26, tree `d09c14f1`)

- `ui/src/store/useSettingsStore.ts`: `ConfigSnapshot.config: Record<string, any>` :24; status union :53; `csrfFetchedAt` :58; `_fetchSnapshot` :93-101 (returns a snapshot or a string, catches every error); `loadSnapshot` early return :132, view reset :146-149; `csrfFetchedAt: Date.now(),` :145 and :178; `draftCount: 0,` :109 and :181; `applyErrors: [],` :116 (initial state, indented two spaces), :148 and :183; pre-save refresh :225; spend :229; `body` :238; 200 branch :240-247; outer catch :272-273; `finally` clears `applying` :274-276.
- `src/probos/routers/config.py`: `get_config` :231-234 returns `runtime.config.model_dump`; `hot_reload_paths` :378-383; `restart_required` :384-386; runtime mutation :387-395; answer :433.
- `src/probos/settings/section_registry.py`:127 `cognitive.offline_stt_enabled`, `hot_reload=True` :137; :289 `wake_word.wake_word_trainer_enabled`, :298.
- `SettingsTopBar.tsx`:112 banner, :140 text, :154 `inSync`, :177 `settings-status-message`. `SettingsMain.tsx`:233-237 `errorsByField` from `applyErrors`. `SettingsPanel.test.tsx`:199 answers `restart_required: true`. `useSettingsStore.bf999.test.tsx`:126 the same.
- BF number: the orchestrator's enumeration of 2026-11-26 (git subjects BF-961, issue titles BF-991, PR titles BF-982, `prompts/bf-*.md` BF-999, PROGRESS/DECISIONS BF-999, roadmap BF-927). Confirmed: `prompts/bf-99*.md` and `bf-100*` list `bf-990` to `bf-999` only; `git log --all --grep=BF-1000` is empty; `gh search issues "BF-1000"` returns no issue titled BF-1000.

### Absence Verified (2026-11-26)

- CLAIM: nothing reads `applyStatus === 'success'`. RUN: Grep `applyStatus|'success'` over `ui/src` excluding tests. FOUND: the store's writers, `SettingsTopBar.tsx`:16, :112, :150, :154; the other `'success'` hits are unrelated unions (`types.ts`:970, `threadApi.ts`, `transformersStt.ts`). HOLDS.
- CLAIM: only two test files call `applyDraft` or click APPLY. RUN: Grep `applyDraft|settings-topbar-apply` over `ui` excluding `node_modules`. FOUND: the store, `SettingsTopBar.tsx`, `useSettingsStore.bf999.test.tsx`, `SettingsPanel.test.tsx`. HOLDS; both answer `restart_required: true`. The other settings tests that set `applyStatus` (`ProactiveSection.test.tsx`:51, `PerceptionParentChild.test.tsx`:84, `PerceptionLivePanel.modeSection.test.tsx`:52) seed `'idle'`.
- CLAIM: the router sees 21 hot-reload ids. RUN (the orchestrator, 2026-11-26): import `probos.routers.config` and `probos.perception` (the perception section is inserted into the registry at that import), then enumerate `section_registry.SECTIONS` fields with `hot_reload` true. FOUND: 8 in `section_registry.py`: `cognitive.conversation_barge_in_enabled`, `cognitive.conversation_mode_enabled`, `cognitive.conversation_silence_timeout_ms`, `cognitive.fallback_stt_enabled`, `cognitive.offline_stt_enabled`, `cognitive.primary_stt`, `wake_word.retain_training_samples`, `wake_word.wake_word_trainer_enabled`; and 13 `perception.*`: `camera.enabled`, `enabled`, `engaged_budget_enforcement`, `engaged_call_cap_per_day`, `engaged_call_cap_per_session`, `explicit_share_enabled`, `fusion_window_ms`, `screen.enabled`, `source_fusion_enabled`, `vision_baseline_max_age_seconds`, `vision_min_interval_seconds`, `vision_novelty_threshold`, `wm_persistence_enabled`. HOLDS. A grep for `hot_reload=True` gives the same 8 and 13 per file but does not show that the router's registry holds both; the import does.
- CLAIM: `perception.vad_engagement_enabled`, `agentic_loop.event_correlation_enabled`, `discovery.enabled`, `discovery.hostname`, `approval_inbox.enabled` and `cognitive.custom_model_filename` are not registered, and no registered id starts with `discovery.`, `approval_inbox.` or `agentic_loop.`. RUN: the same enumeration (orchestrator) for the first five and the prefixes; Grep `custom_model_filename` over `section_registry.py` and `perception/__init__.py` (architect). FOUND: none registered. HOLDS: a save that changes one is answered `restart_required: true` and takes the unchanged branch.
- CLAIM: no tracker tool assumes a three-digit BF. RUN: Grep for BF/AD number patterns over `scripts`, `tests`, `.github`, `docs`, `src`, `ui/src`. FOUND: `gen_ad_ledger.py`:113 `\d{1,5}`, `check_dormant_classes.py`:57 `\d+`, `test_bf936_crew_code_change_orders.py`:187 `\d+`. HOLDS.

## 11. What this does NOT change, and recorded limits

- The router and its answers, including `restart_required: true` for a save with no changed field.
- `SettingsTopBar.tsx`: the banner component, its colour, and the status-bar colour of `applyMessage`.
- The BF-999 token rules and test file.
- Limit: an edit typed between the APPLY press and the end of the reload is cleared with the draft; the POST window already had this.
- Limit: after a failed reload the dialog shows the old value with an explicit message until the next read.

## 12. Issue text (#1855, on merge)

```
Repaired as BF-1000 (contract prompts/bf-1000-1855-hxi-settings-applied-flag.md). useSettingsStore.applyDraft now reads restart_required from a 200: when it is the boolean false, the store reloads GET /api/config (the live config) and shows "Saved and applied. No restart needed." with status success, no field errors and no restart banner; a failed reload says so, keeps the old snapshot, and the next press reads a token first. Any other 200, including a null body, keeps the restart banner and message. The router is unchanged. Tests: ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx (5 tests; cases 1 and 3 fail on the unrepaired store, the three rows of case 2 kill the loose-flag and null-body mutants).
```

## 13. Prior art and blind spots

- Internal: BF-299 (the router's hot-reload apply), BF-304 (`loadSnapshot`), BF-999 (token refresh; its D1 rejected a forced read after every save for the token, which this does not revisit).
- External search skipped: ProbOS-specific store plumbing with no outside analogue; no row of `docs/research/reference-projects.md` was examined.
- Blind spots: the router reports a field applied when `runtime.config` changed, even if a downstream push failed (`config.py`:419-425 logs it); the store cannot see that. Two tabs: the other tab keeps its snapshot until its next read.

## 14. Acceptance criteria

1. Cases 1 and 3 fail on the base and all 5 tests pass on the candidate; M1 to M10 are killed as section 8.3 says.
2. The focused checks of 8.2 pass; the BF-999 file and `SettingsPanel.test.tsx` pass unchanged.
3. `git diff --check` is clean, all new text is ASCII, and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
