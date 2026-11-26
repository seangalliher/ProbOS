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
const DONE = 'Saved and applied. This change needs no restart.';
const PENDING = 'Saved and applied. An earlier save asked for a restart.';

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
      expect(screen.getByTestId('settings-status-message').textContent).toBe(DONE),
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
    expect(s().applyMessage).toBe(`${DONE} Could not reload the values (config GET failed: 503).`);
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

  it('applied saves after a restart-required one keep the restart banner, say so, and show the live value', async () => {
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
    await act(async () => { await save(false); });
    expect(screen.getByTestId('settings-status-message').textContent).toBe(PENDING);
    expect(screen.getByTestId('settings-restart-banner')).toBeTruthy();
    expect(s().applyStatus).toBe('restart_required');
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
    expect(srv.posts).toEqual(['t1', 't2', 't3']);
    expect(srv.gets).toBe(4);
  });

  it('an applied save after a restart-required one whose reload fails keeps the restart status and says both, and so does the next applied save', async () => {
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
    await save(false);
    expect(s().applyStatus).toBe('restart_required');
    expect(s().applyMessage).toBe(PENDING);
    expect(s().snapshot?.config.cognitive.offline_stt_enabled).toBe(false);
    expect(srv.posts).toEqual(['t1', 't2', 't4']);
    expect(srv.gets).toBe(5);
  });

  it.each([
    { label: 'a DISCARD between', answers: [RESTART, APPLIED], discardOnGet: 0, between: async () => { s().setDraftField(MODEL, 'm3'); s().discardDraft(); } },
    { label: 'a refused save between', answers: [RESTART, REFUSED, APPLIED], discardOnGet: 0, between: async () => { s().setDraftField(FIELD, 'bad'); await s().applyDraft(); } },
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
