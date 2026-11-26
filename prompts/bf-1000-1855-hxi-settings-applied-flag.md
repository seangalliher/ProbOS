# BF-1000: the HXI settings store reads the save's restart_required flag; a save the router applied at once shows "applied" and the live values

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-26 (revision 1: the orchestrator's findings F1 to F6: a null-safe flag read, the consumer table, three stale-state mutants, the double's comment, wording and counts; revision 2: G1, section 10 lists all 21 hot-reload ids, and G2, the empty-save wording in sections 1 and 6.3; revision 3: review round 1, RV1-F1, an applied save keeps the banner of a restart an earlier save still needs, and RV1-F2, the `IntentSurface.tsx` row names the main-chat STT subscription; revision 4: the pending restart is a store bit `restartPending`, not derived from `applyStatus`, because revision 3 lost the banner when a DISCARD or a refused save came between the two saves or a DISCARD came during the reload, sequences S2 to S4 of section 1)
**Corrected by:** the orchestrator, 2026-11-26: the words "in registry order" are deleted from the Absence Verified entry of section 10 (the list was printed sorted by id, which is not the declaration order of `section_registry.py`; the order was the orchestrator's wording in the revision-2 request, not the Architect's); section 8.3 names the occurrence of M6's line (2nd of 2, the line also occurs in the pre-save refresh); section 15 records the oracle results; two test additions that the orchestrator's reading of the bit's writers called for (an assertion at the end of case 1 that the second applied save shows `success`, and the fourth row of case 6, closing and reopening the dialog between the saves) with the counts they move (11 tests, M23 and M24, the base and revision 3 expectations of 8.1 and the killers of M13); the citations of the AD-1074c artifact test file in sections 7 and 10 are rewritten (a fenced block lists its path), because the phantom-symbol precheck reads the capitalised name `Artifact.ad1074c` in prose as a symbol and the gate preflight would fail on it.
**Status:** ready to build. **Owning issue:** #1855 only. Commits say `Refs #1855.`
**Base:** `d09c14f13f0251ae6704f7f05411fd3e665930c7` (= origin/main), branch `feat/bf1000-1855-hxi-settings-restart-flag-20261126`. **Number:** BF-1000 (section 10).
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 11 new tests (6 cases, one a three-row and one a four-row `it.each`) in 1 new file (`ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx`), 0 removed, 0 changed.
**Scope:** `ui/src/store/useSettingsStore.ts`, the new test file, `PROGRESS.md`, `DECISIONS.md` and the regenerated ledger files. No Python file changes.

## 1. Problem (premise table)

| Where | What it does today | Premise it gets wrong |
|---|---|---|
| `useSettingsStore.ts`:240-247, the 200 branch of `applyDraft` | sets `applyStatus: 'restart_required'` and `applyMessage: 'Restart required to take effect.'`, clears the draft; `body` is parsed at :238 and not read | that each 200 needs a restart |
| `config.py`:384-386 and :387-395 | `restart_required = not (changed_fields and all(p in hot_reload_paths ...))`; when false, each changed field is written into `runtime.config` before the answer at :433 | n/a (the router is right) |
| `useSettingsStore.ts`:240-247 | keeps the pre-save `snapshot` | that the live config did not change; `get_config` (`config.py`:232-234) returns `runtime.config`, so after an applied save the next GET holds the new value |
| `SettingsTopBar.tsx`:112 | renders `settings-restart-banner` ("PROBOS RESTART REQUIRED") for `'restart_required'` | follows the store |

Effect: a save that changes at least one field, all of them hot-reload (for example `cognitive.offline_stt_enabled`, `section_registry.py`:127-137) is live at once, yet the dialog says to restart and the store's snapshot keeps the old value until the next GET.

Constraint (review round 1 and the revision-3 probe): the base writes `'restart_required'` after each 200, so its banner reappears at each later 200 whatever came between. An earlier restart-required save leaves its change in the YAML and not in the running config; the repair must not say "No restart needed" while that is so. Measured on revision 3 (status-derived pending), with `A` answered `restart_required: true` and `B` answered `false`: S1 `A, B` and S5 `A, B, C` kept the banner, but S2 `A, DISCARD, B`, S3 `A, refused (422), B` and S4 `A, B` with a DISCARD during B's reload ended `success` with no banner; the base shows it in all three.

## 2. Overview

The store gains a public state bit `restartPending` (initial `false`). The restart branch of the 200 (today's branch) sets it to `true` with its existing `set`; no other code writes it. In the 200 branch, `body?.restart_required === false` (strict, null-safe) means applied: the store awaits `_fetchSnapshot()`, reads `get().restartPending` and makes ONE `set`: the status (`'restart_required'` when the bit is set, else `'success'`), the message, `applyErrors: []`, the cleared draft and, when the read returned a snapshot, `snapshot` and `csrfFetchedAt: Date.now()`. A failed read keeps the old snapshot and leaves `csrfFetchedAt` at 0 (set at :229), so the next press reads a token first. A 200 body that is not an object whose flag is the boolean false (flag true, missing, another value, unparsable or null) takes today's branch, which now also sets the bit.

Result: while the bit is false, an applied save shows `success` and no banner; once the bit is true, a later 200 of either kind shows the banner, as the base does after each 200. DISCARD, a refused save, `openSettings` and `loadSnapshot` leave the bit as it was.

Rejected, one line each:
- Deriving the pending restart from `applyStatus` (revision 3): DISCARD (:199) and each failure branch overwrite the status, so S2, S3 and S4 (section 1) lost the banner the base shows.
- Reading the pending status before the POST instead of after the reload: fixes S4 only; S2 and S3 still read `'idle'` or `'rejected'`.
- Keeping revision 3 and recording S2 to S4 as limits: they are regressions against the base with ordinary reach.
- A sticky bit that the banner also reads: it would keep the banner after a refused save or a DISCARD, where the base drops it until the next 200; a display change against the base, out of scope.
- The router reporting a pending restart (YAML against running config): it would also cover a page reload and a second tab, but it changes the Python API; considered, deferred (section 13).
- A new status member (`'applied'`): `'success'` is already in the union (:53) and no component reads it (section 10).
- Merging the sent patch into the old snapshot without a GET: the router coerces values (pydantic), so the live GET is the authority.
- Calling `loadSnapshot()` for the refresh: it returns early once loaded (:132) and resets `selectedSectionId`, `applyStatus` and `applyMessage` (:146-149).
- Refreshing after a restart-required save too: it does not change `runtime.config`, so the read would show nothing new.
- Keeping edits typed while the save is in flight (draft diffing): the POST window already loses them today; out of scope (section 11).
- Changing the router's answer for an empty change set: a recorded limit, not this defect.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Applied when `body?.restart_required === false`, and not otherwise | A missing, malformed or null body keeps the safe (banner) behaviour; `body` is `{}` after a parse failure (:238) and `null` for a JSON `null` |
| D2 | Await the refresh, then one `set` per outcome | On a successful read the field shows the draft value until the live value replaces it, with no frame of the old value and a cleared draft; on a failed read the old value returns with an explicit message (D4) |
| D3 | The draft is cleared in that final `set`, after the refresh | Same as D2; the cost is a longer in-flight window (section 11) |
| D4 | Messages: bit false, `Saved and applied. No restart needed.`; bit true, `Saved and applied. An earlier change still needs a restart.`; a failed read appends ` Could not reload the values (<reason>).` to either | The operator is told the save took effect, whether a restart is still owed, and why an old value is shown |
| D5 | A successful refresh records `csrfFetchedAt: Date.now()` | The refreshed snapshot carries a live token, so the next save sends it without a further GET |
| D6 | Both new `set`s clear `applyErrors` | `SettingsMain.tsx`:233-237 renders them as field errors; a stale error from an earlier refused save must not outlive an applied one |
| D7 | No change to `SettingsTopBar.tsx`, the router or the BF-999 test file | The banner keys on `applyStatus === 'restart_required'` (`SettingsTopBar.tsx`:112) and nothing else |
| D8 | The pending restart is the bit `restartPending`: `false` in the initial state, set to `true` in the restart branch's `set`, written by no other code, read by the applied branch after the reload | `applyStatus` is a display value that DISCARD and the failure branches overwrite (S2 to S4). The bit is public state like `csrfFetchedAt`, so `getInitialState()` resets it in tests; the page holds it until the page reloads. With it, the banner differs from the base in one case: an applied save while the bit is false (no 200 in this page session has taken the restart branch) |

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
  /** BF-999: Date.now() when snapshot.csrf_token was fetched; 0 when none was or a POST spent it. */
  csrfFetchedAt: number;
```
REPLACE:
```ts
  /** BF-999: Date.now() when snapshot.csrf_token was fetched; 0 when none was or a POST spent it. */
  csrfFetchedAt: number;
  /** BF-1000: true after a 200 that did not answer restart_required false; a page reload clears it. */
  restartPending: boolean;
```

**P2.** SEARCH:
```ts
  openedAt: 0,
  csrfFetchedAt: 0,
```
REPLACE:
```ts
  openedAt: 0,
  csrfFetchedAt: 0,
  restartPending: false,
```

**P3.** SEARCH:
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
          // Keep the banner while an earlier save's restart is still owed.
          const pending = get().restartPending;
          const status: SettingsState['applyStatus'] = pending ? 'restart_required' : 'success';
          const applied = pending
            ? 'Saved and applied. An earlier change still needs a restart.'
            : 'Saved and applied. No restart needed.';
          if (typeof fresh === 'string') {
            set({
              applyStatus: status,
              applyMessage: `${applied} Could not reload the values (${fresh}).`,
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          } else {
            set({
              snapshot: fresh,
              csrfFetchedAt: Date.now(),
              applyStatus: status,
              applyMessage: applied,
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          }
        } else if (resp.status === 200) {
          set({
            restartPending: true,
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

interface Answer {
  status: number;
  body: unknown;
}

const ok = (body: unknown): Answer => ({ status: 200, body });
const FIELD = 'cognitive.offline_stt_enabled';
const MODEL = 'cognitive.llm_model_fast';
const STALE = [{ loc: ['cognitive', 'offline_stt_enabled'], msg: 'x', type: 'value_error' }];
const APPLIED = ok({ ok: true, restart_required: false, changed_fields: [FIELD] });
const RESTART = ok({ ok: true, restart_required: true, changed_fields: [MODEL] });
const REFUSED: Answer = { status: 422, body: { ok: false, errors: STALE } };
const PENDING = 'Saved and applied. An earlier change still needs a restart.';

const s = () => useSettingsStore.getState();

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
  failGet: number;
  discardOnGet: number;
}

function installServer(...answers: Answer[]): Server {
  const srv: Server = { gets: 0, posts: [], live: false, failGet: 0, discardOnGet: 0 };
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) !== '/api/config') throw new Error(`unexpected request ${String(input)}`);
    if (init?.method === 'POST') {
      srv.posts.push((init.headers as Record<string, string>)['X-Probos-CSRF']);
      const answer = answers[Math.min(srv.posts.length, answers.length) - 1];
      if ((answer.body as { restart_required?: unknown } | null)?.restart_required === false) {
        srv.live = JSON.parse(String(init.body)).patch.cognitive.offline_stt_enabled;
      }
      return jsonResp(answer.body, answer.status);
    }
    srv.gets += 1;
    if (srv.gets === srv.discardOnGet) s().discardDraft();
    if (srv.gets === srv.failGet) return jsonResp({ error: 'unavailable' }, 503);
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
    expect(s().applyStatus).toBe('success');
  });

  it.each([
    { label: 'no flag', answer: ok({ ok: true, changed_fields: [FIELD] }) },
    { label: 'a flag of 0', answer: ok({ ok: true, restart_required: 0, changed_fields: [FIELD] }) },
    { label: 'a null body', answer: ok(null) },
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
    srv.failGet = 2;
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

  it('an applied save after a restart-required one keeps the restart banner, says so, and shows the live value', async () => {
    const srv = installServer(RESTART, APPLIED);
    await act(async () => { await s().openSettings(); });
    render(<SettingsPanel />);
    act(() => { s().setDraftField(MODEL, 'm2'); });
    fireEvent.click(screen.getByTestId('settings-topbar-apply'));
    await waitFor(() => expect(screen.getByTestId('settings-restart-banner')).toBeTruthy());
    act(() => { s().setDraftField(FIELD, true); });
    fireEvent.click(screen.getByTestId('settings-topbar-apply'));
    await waitFor(() =>
      expect(screen.getByTestId('settings-status-message').textContent).toBe(PENDING),
    );
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
    expect(s().applyStatus).toBe('restart_required');
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(true);
    expect(s().draft).toEqual({});
    expect(s().draftCount).toBe(0);
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(3);
  });

  it('an applied save after a restart-required one whose reload fails keeps the restart status and says both', async () => {
    const srv = installServer(RESTART, APPLIED);
    await s().openSettings();
    s().setDraftField(MODEL, 'm2');
    await s().applyDraft();
    expect(s().applyStatus).toBe('restart_required');
    srv.failGet = 3;
    await save(true);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe(`${PENDING} Could not reload the values (config GET failed: 503).`);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
    expect(s().draft).toEqual({});
    expect(s().draftCount).toBe(0);
    expect(srv.posts).toEqual(['t1', 't2']);
    expect(srv.gets).toBe(3);
  });

  it.each([
    { label: 'a DISCARD between', answers: [RESTART, APPLIED], discardOnGet: 0, between: async () => { s().setDraftField(MODEL, 'm3'); s().discardDraft(); } },
    { label: 'a refused save between', answers: [RESTART, REFUSED, APPLIED], discardOnGet: 0, between: async () => { s().setDraftField(MODEL, 'bad'); await s().applyDraft(); } },
    { label: 'a DISCARD during the reload', answers: [RESTART, APPLIED], discardOnGet: 3, between: async () => {} },
    { label: 'closing and reopening the dialog between', answers: [RESTART, APPLIED], discardOnGet: 0, between: async () => { s().closeSettings(); await s().openSettings(); } },
  ])('an applied save after a restart-required one and $label keeps the restart banner', async ({ answers, discardOnGet, between }) => {
    const srv = installServer(...answers);
    srv.discardOnGet = discardOnGet;
    await act(async () => { await s().openSettings(); });
    render(<SettingsPanel />);
    await act(async () => {
      s().setDraftField(MODEL, 'm2');
      await s().applyDraft();
      await between();
      await save(true);
    });
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe(PENDING);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(true);
  });
});
```

### 6.3 `PROGRESS.md` (M2)

**P4.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-1000 (2026-11-26), #1855 -- a settings save the router applied at once no longer says a restart is required, and the dialog shows the live values.** For a save that changes at least one field, all of them hot-reload, `POST /api/config` answers `restart_required: false` and has then already written them into the running config (BF-299); the HXI store ignored the flag, showed "Restart required to take effect." and the PROBOS RESTART REQUIRED banner after each 200, and kept its pre-save snapshot. `useSettingsStore.applyDraft` now treats a 200 whose flag is the boolean false as applied: it reloads the snapshot, then shows the live values with no field errors and, while no earlier save in this page session took the restart path, status `success` with "Saved and applied. No restart needed." A new store bit `restartPending`, set by each 200 that does not answer `restart_required: false` and kept until the page reloads, makes a later applied save keep the restart status and banner and say "Saved and applied. An earlier change still needs a restart.", also after a DISCARD or a refused save in between. When the reload fails it says so and keeps the old snapshot, and the next press reads a token first. A 200 with another flag value, a missing flag or a null body keeps the restart banner. New `ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx` (11 tests). The router is unchanged. Contract `prompts/bf-1000-1855-hxi-settings-applied-flag.md`.
```

### 6.4 `DECISIONS.md` (M2)

**P5.** SEARCH:
```markdown
### BF-999 -- the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (2026-11-26, #1852)
```
REPLACE:
```markdown
### BF-1000 -- the HXI settings store reads the save's restart_required flag and shows the live values after an applied save (2026-11-26, #1855)

- *Scope.* `ui/src/store/useSettingsStore.ts` (`applyDraft`, a new state bit `restartPending`); test `ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx`. Contract `prompts/bf-1000-1855-hxi-settings-applied-flag.md`. The router, `SettingsTopBar.tsx` and the banner are unchanged.
- *D1.* A 200 means applied when `restart_required` is the boolean false; a missing or other value, or a null body, keeps the restart banner.
- *D2.* After an applied save the store reads `GET /api/config` (the live config) and then sets the status, the message, the snapshot, empty field errors and the cleared draft in one update; the refreshed token is recorded as fresh. The read follows an applied save and no other, for display; BF-999 D1's rejection of a forced read after each save, for the token, stands.
- *D3.* The existing `'success'` member of `applyStatus` carries the applied state; no new member.
- *D4.* The pending restart is the bit `restartPending`, set by the 200 branch that keeps the restart banner (each 200 that does not answer `restart_required: false`) and written by no other code; an applied save while it is set keeps `'restart_required'` and the banner and says "Saved and applied. An earlier change still needs a restart." The status is not the record: DISCARD and the failure branches overwrite it, and a status-derived version lost the banner after a DISCARD or a refused save between the saves.
- *Rejected.* Deriving the pending restart from `applyStatus` (see D4); merging the patch into the old snapshot (the router coerces values); reusing `loadSnapshot` (it returns early once loaded and resets the view); a read after a restart-required save (the running config did not change); a bit that the banner also reads (it would change the display after a refused save or DISCARD); the router reporting a pending restart (an API change; deferred).
- *Known limits.* An edit typed between the APPLY press and the end of the reload is cleared with the draft, as one typed during the POST already was. A save with no changed field is answered `restart_required: true` by the router, shows the banner and sets the bit. The bit lives until the page reloads: a ProbOS restart without a page reload leaves it set, so later applied saves still show the banner, as each 200 did before. A refused save or DISCARD drops the banner until the next 200, as before.
- *Reversal.* Revert the commit; no API, persisted format or security control changes.

### BF-999 -- the HXI settings store fetches a fresh CSRF token before each save and keeps the draft on a refused save (2026-11-26, #1852)
```

## 7. Consumers

An applied save changes fields in `hot_reload_paths` (`config.py`:378-386) and no others: 21 ids, listed in section 10. Rows marked "unchanged" read none of them.

| Consumer | What it reads | After the change |
|---|---|---|
| `SettingsTopBar.tsx`:112 | `applyStatus === 'restart_required'` | bit false: no banner after an applied save; bit true: a 200 of either kind shows it (D8) |
| `restartPending` (new store state) | read by the applied branch of `applyDraft`; no component reads it (section 10) | new |
| `SettingsTopBar.tsx`:147-181 (`SettingsStatusBar`) | `snapshot`, `draftCount`, `applyMessage`; in sync unless `'rejected'` | shows the new messages in the existing colour |
| `SettingsMain.tsx`:216, :290 | `snapshot.config` per field | shows the live value |
| `SettingsMain.tsx`:303 | `perception.enabled` (hot-reload) | shows the live value |
| `SettingsMain.tsx`:233-237 | `applyErrors` as field errors | cleared by an applied save |
| `PerceptionLivePanel.tsx`:90; :587, :652, :669, :678 | `perception.enabled`; `perception.screen.enabled` (both hot-reload) | show the live value |
| `PerceptionLivePanel.tsx`:77 | the `cognitive` object (`llm_base_url_vision`, `llm_model_vision`: registered, not hot-reload) | unchanged |
| `IntentSurface.tsx`:112-114, the main-chat STT effect :297-318 (deps `[sttEnabled, wakeWordEnabled]`), the transcript pill :975 | `cognitive.offline_stt_enabled` (hot-reload) as a boolean selector | the main-chat STT subscription arms or disarms after the save, not at the next page load, and only while `wakeWordEnabled` is also true (:298); the wake-word loop (deps at :284) does not read the flag and does not re-run; replacing the snapshot alone does not re-run the effect |
| `CameraLiveIndicator.tsx`:77, `WakeWordTrainerPanel.tsx`:67 | hot-reload booleans | follow the live value |
| `wakeWord.ts`:290-293 | `cognitive.custom_model_filename` (not a registered field) | unchanged |
| `App.tsx`:98-108, `CompactApp.tsx`:131, `CameraLiveIndicator.tsx`:71, `ConnectPhoneCard.tsx`:54-55, `LiveToolProgress.tsx`:15, `ProfileChatTab.tsx`:1662, `useStore.ts`:2657-2658, `CapabilityRequestCard.tsx`:29 and :53 | fields that are not registered (section 10) | unchanged; whole-object selectors re-render once, as they already do on BF-999's pre-save refresh (`useSettingsStore.ts`:225) |
| `SettingsPanel.test.tsx`:192-218, `useSettingsStore.bf999.test.tsx` (router double answers `restart_required: true` at :126), `LiveToolProgress.test.tsx`:165-169 and :35 (`setState` of the initial state spread, `true`), and the two tests that restore a saved full state (listed in section 10) | the restart branch, the token sequence, whole-state replacement | unchanged: a `true` flag takes the old branch (now also setting the bit) and reads nothing more; the replacements carry the new field because they start from a real state |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Every SEARCH in section 6 counted at its turn: 1 each; the new test file does not exist.
- Run the new file on the base: cases 1, 3, 4, 5 and 6 (all four rows) fail; the three rows of case 2 pass by construction (the base shows the banner after each 200; they kill M2 and M10, section 8.3).
- On revision 3 (store blob `1f8538d6`): the first three rows of case 6 fail (status `success`, no banner: S2, S3, S4); cases 1 to 5 and the row `closing and reopening the dialog between` pass; case 6 is the reason for revision 4. On the candidate as first built (no pending read), cases 4, 5 and 6 fail; cases 4 and 5 were the reason for revision 3.

### 8.2 Focused checks on the candidate (in `ui/`)

```
npx tsc -b
npx vitest run src/store/__tests__/useSettingsStore.bf1000.test.tsx src/store/__tests__/useSettingsStore.bf999.test.tsx src/components/settings src/components/profile/__tests__/LiveToolProgress.test.tsx src/components/capability/__tests__/ApprovalWave.test.tsx
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-1000-1855
```
Expected: green; the BF-999 file and `SettingsPanel.test.tsx` pass unchanged.

### 8.3 Mutation rows (`useSettingsStore.ts`, one at a time, file restored byte for byte)

Counts are of whole stripped lines in the candidate file (326 lines). `applyErrors: [],` occurs 6 times (:118, :151, :186, :256 the failed-reload `set`, :266 the success `set`, :276 the restart branch); `draftCount: 0,` 5 times (:111, :184, :258, :268, :278); `draft: {},` 5 times (:110, :183, :257, :267, :277); `csrfFetchedAt: Date.now(),` 3 times (:148, :181, :263); `if (typeof fresh === 'string') {` 2 times (:219 the pre-save refresh, :252 the reload branch); `applyStatus: status,` 2 times (:254 the failed-reload `set`, :264 the success `set`). The other lines named below occur once.

| ID | Line (stripped) | Becomes | Killed by |
|---|---|---|---|
| M1 | `if (resp.status === 200 && body?.restart_required === false) {` | `if (resp.status === 200 && false) {` | cases 1, 3, 4, 5 and 6 |
| M2 | same line | `if (resp.status === 200 && !body?.restart_required) {` | case 2, all three rows |
| M3 | same line | `if (resp.status === 200) {` | case 2; the BF-999 file; `SettingsPanel.test.tsx`:192 |
| M4 | `snapshot: fresh,` | empty line | cases 1, 4 and 6 (the live value) |
| M5 | `csrfFetchedAt: Date.now(),` (3rd of 3) | empty line | case 1 (`['t1', 't2']`, 3 reads) |
| M6 | `if (typeof fresh === 'string') {` (2nd of 2, the reload branch) | `if (false) {` | cases 3 and 5 |
| M7 | `applyErrors: [],` (4th of 6, the failed-reload `set`) | empty line | case 3 |
| M8 | `applyErrors: [],` (5th of 6, the success `set`) | empty line | case 1 |
| M9 | `draftCount: 0,` (3rd of 5, the failed-reload `set`) | empty line | cases 3 and 5 |
| M10 | `if (resp.status === 200 && body?.restart_required === false) {` | `if (resp.status === 200 && body.restart_required === false) {` | case 2, row `a null body` (TypeError, status `rejected`) |
| M11 | `const pending = get().restartPending;` | `const pending = false;` | cases 4, 5 and 6 |
| M12 | same line | `const pending = true;` | cases 1 and 3 |
| M13 | same line | `const pending = get().applyStatus === 'restart_required';` (revision 3) | case 6, rows `a DISCARD between`, `a refused save between` and `a DISCARD during the reload` |
| M14 | `const status: SettingsState['applyStatus'] = pending ? 'restart_required' : 'success';` | `const status: SettingsState['applyStatus'] = 'success';` | cases 4, 5 and 6 |
| M15 | `applyStatus: status,` (1st of 2, the failed-reload `set`) | `applyStatus: 'success',` | case 5 |
| M16 | `applyStatus: status,` (2nd of 2, the success `set`) | `applyStatus: 'success',` | cases 4 and 6 |
| M17 | `applyMessage: applied,` | `applyMessage: 'Saved and applied. No restart needed.',` | cases 4 and 6 |
| M18 | `? 'Saved and applied. An earlier change still needs a restart.'` | `? 'Saved and applied. No restart needed.'` | cases 4, 5 and 6 |
| M19 | `restartPending: true,` | empty line | cases 4, 5 and 6 |
| M20 | `restartPending: false,` | `restartPending: true,` | cases 1 and 3 (`getInitialState()` then starts with the bit set) |
| M21 | `set({ draft: {}, draftCount: 0, applyStatus: 'idle', applyErrors: [], applyMessage: '' }),` (`discardDraft`) | `set({ restartPending: false, draft: {}, draftCount: 0, applyStatus: 'idle', applyErrors: [], applyMessage: '' }),` | case 6, rows `a DISCARD between` and `a DISCARD during the reload` |
| M22 | `applyErrors: body.errors ?? [],` (the 422 `set`) | `restartPending: false, applyErrors: body.errors ?? [],` | case 6, row `a refused save between` |
| M23 | `set({ draft: {}, draftCount: 0 });` (`openSettings`, the already-loaded reset) | `set({ restartPending: false, draft: {}, draftCount: 0 });` | case 6, row `closing and reopening the dialog between` |
| M24 | `snapshot: fresh,` | `restartPending: true, snapshot: fresh,` | case 1 (the second applied save shows `success`) |

Case 2 passes on the base by construction; it is kept because it alone kills M2 and M10. M21 to M24 stand for "no other code writes the bit" (M24: not even the applied branch).

### 8.4 The batch gate

`scripts/run_test_gate.py --label bf-1000-1855 --receipt logs/gates/bf-1000-1855.receipt.json` once on the committed head. No Python file changes, so a red Python test is triaged by the standing rules.

## 9. Diff Reviewer: properties to verify

The change claims that a 200 answered `restart_required: false` shows the live config and status `success`, or keeps `restart_required` when a save earlier in this page session needed a restart, and that a 200 with another body behaves as before and also sets that record. The consumer that must accept it is the Settings dialog (`SettingsPanel` with `SettingsTopBar` and `SettingsStatusBar`) over the unchanged `src/probos/routers/config.py`.

1. A 200 whose body is a JSON value other than an object with `restart_required` the boolean false (including `null` and the `{}` of a parse failure) reaches the same `set` as the base plus `restartPending: true`, with no extra request.
2. After an applied save, each outcome of the reload ends in exactly one `set`, which clears `applyErrors` and the draft; a failed reload leaves `snapshot` and `csrfFetchedAt` as they were before that `set`.
3. The `applying` latch is still cleared in `finally` after the reload, and a press during the reload sends nothing.
4. The other branches of `applyDraft` (403 resend, 422, 400, other status, thrown error) do not change.
5. The new test file holds its own double, imports nothing from the BF-999 file, and its token and read counts follow from the double.
6. ASCII and LF in the new text; no file outside section 4 changes.
7. `restartPending` is written by the initial state (`false`) and the restart branch's `set` (`true`) and by no other code, so DISCARD, a refused save, `openSettings` and `loadSnapshot` leave it as it was. After an applied save the final `set` writes `'restart_required'` when the bit is true (read after the reload, no await in between) and `'success'` when it is false, in both reload outcomes; the message says which (D4). Against the base, the banner differs only after an applied save while the bit is false.

## 10. Verified Against Codebase (2026-11-26, tree `d09c14f1`; candidate lines after the revision-4 6.1)

- `ui/src/store/useSettingsStore.ts` (base): `ConfigSnapshot.config: Record<string, any>` :24; `export interface SettingsState` :41; status union :53; `openedAt: number;` :56; BF-999 comment :57 and `csrfFetchedAt: number;` :58 (P1); `_fetchSnapshot` :93-101 (returns a snapshot or a string, catches every error); `draft: {},` :108; `draftCount: 0,` :109; `applyErrors: [],` :116; `openedAt: 0,` :118 and `csrfFetchedAt: 0,` :119 (P2; the other `csrfFetchedAt: 0,` is :219 in the token-failure `set`, so P2 anchors on the pair); `loadSnapshot` early return :132, view reset :146-149; `csrfFetchedAt: Date.now(),` :145 and :178; `applyErrors: [],` :148 and :183; `openSettings` once loaded writes `open`, `openedAt`, `draft` and `draftCount` and no status (:160-164); `discardDraft` :198-199; pre-save refresh :225; spend :229; `body` :238; 200 branch :240-247 (P3). Candidate: interface field :60, initial `restartPending: false,` :122, `discardDraft` :202, applied branch :243-270 (`const pending = get().restartPending;` :247), restart branch :271-279 (`restartPending: true,` :273).
- `src/probos/routers/config.py`: `get_config` :231-234 returns `runtime.config.model_dump`; `hot_reload_paths` :378-383; `restart_required` :384-386; runtime mutation :387-395; answer :433.
- `src/probos/settings/section_registry.py`:95 `cognitive.llm_model_fast` (no `hot_reload`, the restart field of cases 4 to 6); :127 `cognitive.offline_stt_enabled`, `hot_reload=True` :137; :289 `wake_word.wake_word_trainer_enabled`, :298.
- `SettingsTopBar.tsx`:64 and :81 APPLY `disabled={!dirty}`; :112 banner, :140 text, :154 `inSync`, :177 `settings-status-message`. `SettingsMain.tsx`:233-237 `errorsByField` from `applyErrors`. `IntentSurface.tsx`:112-114 `sttEnabled`; :284 the wake-word effect's deps `[wakeWordEnabled, agentsMap]`; :286 "AD-705a / BF-309: offline STT subscription for the MAIN CHAT"; :298 `if (!sttEnabled || !wakeWordEnabled) return;`; :318 deps `[sttEnabled, wakeWordEnabled]`; :975 `{sttEnabled && sttTranscribing && (`. `SettingsPanel.test.tsx`:199 answers `restart_required: true`. `useSettingsStore.bf999.test.tsx`:126 the same.
- BF number: the orchestrator's enumeration of 2026-11-26 (git subjects BF-961, issue titles BF-991, PR titles BF-982, `prompts/bf-*.md` BF-999, PROGRESS/DECISIONS BF-999, roadmap BF-927). Confirmed: `prompts/bf-99*.md` and `bf-100*` list `bf-990` to `bf-999` only; `git log --all --grep=BF-1000` is empty; `gh search issues "BF-1000"` returns no issue titled BF-1000.

### Absence Verified (2026-11-26)

- CLAIM: no component reads `applyStatus === 'success'`. RUN: Grep `applyStatus|'success'` over `ui/src` excluding tests. FOUND: the store's writers, `SettingsTopBar.tsx`:16, :112, :150, :154; the other `'success'` hits are unrelated unions (`types.ts`:970, `threadApi.ts`, `transformersStt.ts`). HOLDS.
- CLAIM (D8, property 7): `restartPending` exists nowhere before this change, and after it the writers are the initial state and the restart branch and the reader is the applied branch. RUN (revision 4): Grep `restartPending|SettingsState\b` over `ui` excluding `node_modules`. FOUND on the base: no `restartPending`; `SettingsState` at `useSettingsStore.ts`:41 and :103 only, so the new required field breaks no other object literal of that type. In the candidate the field's three code lines are P1 to P3: :60 (type), :122 (`false`), :273 (`true`), and the read :247; no file outside the store names it. HOLDS. Whole-state `setState(..., true)` in tests: Grep `useSettingsStore\.setState\(...true` over `ui/src` found three files, listed below with their lines; the first two restore a state read earlier from the store and the third spreads `getInitialState()`, so each carries the field.

```text
ui/src/__tests__/Artifact.ad1074c.test.tsx:378
ui/src/__tests__/IntentSurface.audioRender.test.tsx:102
ui/src/components/profile/__tests__/LiveToolProgress.test.tsx:35
```

- CLAIM: outside the store nothing writes `applyStatus`. RUN: Grep `applyStatus` over `ui/src` excluding `__tests__`; Grep `useSettingsStore\.setState` over `ui/src` excluding `__tests__`. FOUND: store writers only (initial state, `loadSnapshot` and `openSettings` on a first load, `discardDraft`, the token-failure `set`, the final `set`s of `applyDraft`'s branches, the catch); readers `SettingsTopBar.tsx`:16, :112, :150, :154; `setState` outside tests: no file. HOLDS. DISCARD and each failure branch overwrite the status, which is why D8 does not use it as the record.
- CLAIM: only two test files call `applyDraft` or click APPLY before this change. RUN: Grep `applyDraft|settings-topbar-apply` over `ui` excluding `node_modules`. FOUND: the store, `SettingsTopBar.tsx`, `useSettingsStore.bf999.test.tsx`, `SettingsPanel.test.tsx`. HOLDS; both answer `restart_required: true`. The other settings tests that set `applyStatus` (`ProactiveSection.test.tsx`:51, `PerceptionParentChild.test.tsx`:84, `PerceptionLivePanel.modeSection.test.tsx`:52) seed `'idle'`.
- CLAIM: the router sees 21 hot-reload ids. RUN (the orchestrator, 2026-11-26): import `probos.routers.config` and `probos.perception` (the perception section is inserted into the registry at that import), then enumerate `section_registry.SECTIONS` fields with `hot_reload` true. FOUND: 8 in `section_registry.py`: `cognitive.conversation_barge_in_enabled`, `cognitive.conversation_mode_enabled`, `cognitive.conversation_silence_timeout_ms`, `cognitive.fallback_stt_enabled`, `cognitive.offline_stt_enabled`, `cognitive.primary_stt`, `wake_word.retain_training_samples`, `wake_word.wake_word_trainer_enabled`; and 13 `perception.*`: `camera.enabled`, `enabled`, `engaged_budget_enforcement`, `engaged_call_cap_per_day`, `engaged_call_cap_per_session`, `explicit_share_enabled`, `fusion_window_ms`, `screen.enabled`, `source_fusion_enabled`, `vision_baseline_max_age_seconds`, `vision_min_interval_seconds`, `vision_novelty_threshold`, `wm_persistence_enabled`. HOLDS. A grep for `hot_reload=True` gives the same 8 and 13 per file but does not show that the router's registry holds both; the import does.
- CLAIM: `perception.vad_engagement_enabled`, `agentic_loop.event_correlation_enabled`, `discovery.enabled`, `discovery.hostname`, `approval_inbox.enabled` and `cognitive.custom_model_filename` are not registered, and no registered id starts with `discovery.`, `approval_inbox.` or `agentic_loop.`. RUN: the same enumeration (orchestrator) for the first five and the prefixes; Grep `custom_model_filename` over `section_registry.py` and `perception/__init__.py` (architect). FOUND: none registered. HOLDS: a save that changes one is answered `restart_required: true` and takes the restart branch.
- CLAIM: no tracker tool assumes a three-digit BF. RUN: Grep for BF/AD number patterns over `scripts`, `tests`, `.github`, `docs`, `src`, `ui/src`. FOUND: `gen_ad_ledger.py`:113 `\d{1,5}`, `check_dormant_classes.py`:57 `\d+`, `test_bf936_crew_code_change_orders.py`:187 `\d+`. HOLDS.
- CLAIM (RV1-F2): the wake-word effect does not read `sttEnabled`. RUN: Grep `sttEnabled|wakeWordEnabled\]` over `IntentSurface.tsx`. FOUND: :112, :298, :318, :975; the wake-word effect's deps at :284 are `[wakeWordEnabled, agentsMap]`. HOLDS.

## 11. What this does NOT change, and recorded limits

- The router and its answers, including `restart_required: true` for a save with no changed field.
- `SettingsTopBar.tsx`: the banner component, its colour, the condition it reads, and the status-bar colour of `applyMessage`.
- The BF-999 token rules and test file.
- Limit: an edit typed between the APPLY press and the end of the reload is cleared with the draft; the POST window already had this.
- Limit: after a failed reload the dialog shows the old value with an explicit message until the next read.
- Limit: `restartPending` is page-session state; in the app a page reload clears it, and no store action writes it back to `false`. A ProbOS restart without a page reload leaves it set, so later applied saves still show the banner and the pending message (the base showed the banner after each 200). A second tab does not know of it. A save the router answers `restart_required: true` with no changed field also sets it.
- Limit: a refused save or DISCARD after a restart-required save drops the banner, as on the base; while the bit is set, the next 200 of either kind shows it again, as the base's next 200 did.

## 12. Issue text (#1855, on merge)

```
Repaired as BF-1000 (contract prompts/bf-1000-1855-hxi-settings-applied-flag.md). useSettingsStore.applyDraft now reads restart_required from a 200: when it is the boolean false, the store reloads GET /api/config (the live config) and shows the live values with no field errors; while no earlier save in this page session took the restart path it shows "Saved and applied. No restart needed." with status success and no restart banner. A new store bit, restartPending, is set by each 200 that does not answer restart_required false and kept until the page reloads; while it is set, an applied save keeps the restart status and banner and says "Saved and applied. An earlier change still needs a restart.", also after a DISCARD or a refused save in between or a DISCARD during the reload (review found a status-derived first version lost the banner in those sequences). A failed reload says so, keeps the old snapshot, and the next press reads a token first. A 200 with another flag value, a missing flag or a null body keeps the restart banner and message. The router and the banner component are unchanged. Limit: the bit outlives a ProbOS restart until the page reloads, so the banner can persist as it did before. Tests: ui/src/store/__tests__/useSettingsStore.bf1000.test.tsx (11 tests; cases 1 and 3 to 6 fail on the unrepaired store, the three rows of case 2 kill the loose-flag and null-body mutants).
```

## 13. Prior art and blind spots

- Internal: BF-299 (the router's hot-reload apply), BF-304 (`loadSnapshot`), BF-999 (token refresh; its D1 rejected a forced read after every save for the token, which this does not revisit).
- External search skipped: ProbOS-specific store plumbing with no outside analogue; no row of `docs/research/reference-projects.md` was examined.
- Blind spots: the router reports a field applied when `runtime.config` changed, even if a downstream push failed (`config.py`:419-425 logs it); the store cannot see that. The router does not report a pending restart, so the store keeps its own page-session record (D8). A server-side flag (YAML against running config) would cover page reloads, other tabs and a ProbOS restart: considered, deferred, an API change. The snapshot's `uptime_seconds` could reveal a ProbOS restart and clear the bit: considered, deferred (a heuristic, and the base's banner already persists in that case).

## 14. Acceptance criteria

1. Cases 1 and 3 to 6 fail on the base, case 6 fails on revision 3, and the 11 tests pass on the candidate; M1 to M24 are killed as section 8.3 says.
2. The focused checks of 8.2 pass; the BF-999 file and `SettingsPanel.test.tsx` pass unchanged.
3. `git diff --check` is clean, the new text is ASCII, and no file outside section 4 changes.
4. The Diff Reviewer approves against section 9.
5. One receipted broad gate on the committed head is green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Results on the oracle tree (the orchestrator, 2026-11-26; revision 4 with the corrections of the header)

The oracle is a detached tree at `d09c14f1` with the six operations of section 6 (pairs P1 to P5 and the new file) applied by `contract_tools.py apply`. The base store blob is `5ee13d2e`.

- **Blobs after the operations:** the store `0de8b0fbbadc8422d51cc4b6c45c8cc09951970f` (326 lines), the new test file `7e07f33a7fca8f9e5c4d71060f47d9a4a19e221d` (206), `PROGRESS.md` `6f32d70cc5fe395d80739bc39d83f2c780636841` (1830), `DECISIONS.md` `5ee303c80dff2852e8625345d602759c32f57790` (13655).
- **The new file against three stores (section 8.1):** the base store: 11 tests, 3 passed (the three rows of case 2), 8 failed (cases 1, 3, 4, 5 and the four rows of case 6). Revision 3's store (`1f8538d6`): 8 passed, 3 failed (the first three rows of case 6). The first-built store (`d9353bf5`): 5 passed (cases 1 to 3), 6 failed (cases 4, 5 and the four rows of case 6).
- **Sequences through the real store, status after the last save** (the orchestrator's probe: A is a save answered `restart_required` true, B and C are saves answered false, the refused save of S3 is a 422, S0 is B alone; results for the base, revision 3 and the candidate in that order): S0: `restart_required`, `success`, `success`. S1 A then B: `restart_required` in all three. S2 A, DISCARD, B; S3 A, refused, B; S4 A, B with a DISCARD during the reload (the base has no reload): `restart_required`, `success`, `restart_required`. S5 A, B, C: `restart_required` in all three.
- **Candidate:** `npx tsc -b` exit 0; the vitest command of 8.2 (10 files) 172 tests passed, 0 failed (the new file 11, the BF-999 file 14).
- **Mutation rows:** the selector is the new file, the BF-999 file and `SettingsPanel.test.tsx`; unmutated, its 32 cases all passed. M1 to M24 and ten rows of the orchestrator (X1 to X10) were each KILLED, and every case a row names failed; no row survived. X1 deletes `draftCount: 0,` of the success `set`; X2 and X3 delete `draft: {},` of the failed-reload `set` and of the success `set`; X4 and X5 turn `applyStatus: status,` into `'idle'` in each of those two; X6 empties the plain applied message and X7 replaces the failed-reload message by the status message alone; X8 drops the `await` of the reload; X9 and X10 change the status and empty the message of the restart branch.
- **Ledger:** `gen_ad_ledger.py` without `--online` rewrote `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; `--check` printed "AD/BF ledger is current"; `git diff --check` was clean.
- **Added by the orchestrator after reading every writer of the bit** (by inspection, before the campaign: no case of the text as drafted would fail if the applied branch set the bit or if `openSettings` reset it): the last assertion of case 1 and the fourth row of case 6; M24 and M23 record them and are killed by them.
