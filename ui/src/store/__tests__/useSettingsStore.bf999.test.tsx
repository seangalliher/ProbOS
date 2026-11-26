// BF-999 (#1852): the HXI settings store fetches a fresh single-use CSRF token before a save
// whenever the last one was spent by a POST or is 240 s old, sends a save the router refused
// with 403 once more, and keeps the draft on every refused save. Real useSettingsStore and the
// real SettingsPanel; fetch is a double that behaves like src/probos/routers/config.py: one
// token per GET, every POST spends the token it carries before the body is read, a token older
// than 300 s is refused, a 403 is answered before the body is read, and a memory.max_episodes
// that is not an integer is answered 422 with the router's error entry.
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
  patches: unknown[]; // the patch of each POST whose token was accepted, in arrival order
  saved: string[]; // system.log_level of each save answered 200
  failNextGet: 'none' | 'status' | 'throw';
  refuseEveryPost: boolean;
  restart: () => void; // the server forgets every token it issued
  hold: () => () => void; // POSTs wait until the returned release() is called
}

// The router reads the body only after it accepts the token; undefined stands for its 400 invalid_json.
function readPatch(body: RequestInit['body']) {
  try {
    return { patch: JSON.parse(String(body)).patch };
  } catch {
    return undefined;
  }
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
