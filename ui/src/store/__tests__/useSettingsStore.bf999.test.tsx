// BF-999 (#1852): the HXI settings store fetches a fresh single-use CSRF token before a save
// whenever the last one was spent by a POST or is 240 s old, sends a save the router refused
// with 403 once more, and keeps the draft on every refused save. Real useSettingsStore and the
// real SettingsPanel; fetch is a double that follows the order of src/probos/routers/config.py:
// one token per GET; every POST spends the token it carries and, before the body is read,
// answers 403 for an unknown token or one older than 300 s (the router ages tokens on
// time.monotonic, the double on the test's Date.now). A POST with a live token is answered from
// MEASURED, the router's answers to the exact bodies the cases send. A case fails when a POST to
// a double it installed carried a live token and any other body, or is still outstanding when the
// case ends (held or unsettled, so its body has not been read). Each case records both in its own
// ledger. The fixed snapshot, the 200 body, the hold and the injected faults are not router
// answers.
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
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: ['INFO', 'DEBUG'], description: '', hot_reload: false },
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
  patches: unknown[]; // the patch of each POST answered 200 or 422, in arrival order
  saved: string[]; // system.log_level of each save answered 200
  failNextGet: 'none' | 'status' | 'throw'; // injected fault for the next GET, not a router answer
  refuseEveryPost: boolean; // injected: refuse live tokens too (the router refuses unknown or expired)
  restart: () => void; // the server forgets every token it issued
  hold: () => () => void; // POSTs wait until the returned release() is called
}

// The router's answer to each body a case POSTs with a live token, measured with a TestClient
// over the unchanged src/probos/routers/config.py (contract D11): 'ok' is a 200, an entry is a
// 422 validation_failed carrying it. pydantic parses integers laxly (it accepts '+5000',
// ' 5000 ', '5000.0', '1_000' and true), so no rule here stands for the router: a body missing
// from the table is recorded in the case's ledger and refused, and afterEach fails the case on
// it. A POST reads its body only after the hold, so afterEach also fails a case whose ledger
// still counts a POST outstanding.
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
      mine.outstanding += 1;
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
          mine.unmeasured.push(sent);
          throw new Error(`fetch double: no measured router answer for ${sent}`);
        }
        const patch = JSON.parse(sent).patch;
        srv.patches.push(patch);
        if (answer !== 'ok') return jsonResp({ error: 'validation_failed', errors: [answer] }, 422);
        srv.saved.push(patch.system?.log_level);
        // The store reads only the status of a 200, so this body is fixed, not the router's per-save answer.
        return jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] });
      } finally {
        mine.outstanding -= 1;
      }
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
    ledger = { outstanding: 0, unmeasured: [] };
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSettingsStore.setState(useSettingsStore.getInitialState(), true);
    expect(ledger.outstanding, 'double POSTs still outstanding when the case ended').toBe(0);
    expect(ledger.unmeasured, 'POST bodies the double has no measured router answer for').toEqual([]);
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
