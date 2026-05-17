// AD-721a: Captain inline avatar editor -- vitest coverage for the editor
// component (load, debounced preview, error paths, approve, cancel).
//
// Heavy three.js / r3f code is irrelevant to this test surface; the editor
// is a pure form -> fetch flow.

import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act, waitFor, cleanup } from '@testing-library/react';
import { CrewAvatarEditor, _defaultDsl, _hexToHsl, _hslToHex } from '../CrewAvatarEditor';
import type { AvatarDSLDict } from '../../../store/types';

const AGENT_ID = 'agent-bones';

function mkDsl(overrides?: Partial<AvatarDSLDict>): AvatarDSLDict {
  return { ..._defaultDsl(), ...overrides };
}

beforeEach(() => {
  // Real timers throughout -- debounce is 500ms, tests just wait 600ms.
  // Fake-timer + waitFor interaction is brittle under vitest 4 jsdom.
});

afterEach(() => {
  cleanup();
});

const DEBOUNCE_WAIT_MS = 600;
const flushDebounce = () => new Promise<void>((r) => setTimeout(r, DEBOUNCE_WAIT_MS));

describe('AD-721a CrewAvatarEditor', () => {
  test('mounts with initial DSL populated into form controls', () => {
    const dsl = mkDsl({ body: { type: 'stocky', height_cm: 185 } });
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={dsl}
        onPreviewUrlChange={() => { /* no-op */ }}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    expect((getByTestId('field-body-type') as HTMLSelectElement).value).toBe('stocky');
    expect((getByTestId('field-body-height') as HTMLInputElement).value).toBe('185');
    expect((getByTestId('field-hair-style') as HTMLSelectElement).value).toBe('medium');
    expect((getByTestId('field-expression-resting') as HTMLSelectElement).value).toBe('neutral');
  });

  test('mounts default DSL when currentDsl is null', () => {
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={null}
        onPreviewUrlChange={() => { /* no-op */ }}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    expect((getByTestId('field-body-type') as HTMLSelectElement).value).toBe('average');
    expect((getByTestId('field-body-height') as HTMLInputElement).value).toBe('170');
  });

  test('debounced preview POST on field change (single fetch after 500ms)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ attachment_id: 'sha-abc123', size_bytes: 1234 }),
    });
    (globalThis as any).fetch = fetchMock;
    const onPreviewUrlChange = vi.fn();
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={onPreviewUrlChange}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    // Three quick edits within 500ms must collapse into one preview fetch.
    fireEvent.change(getByTestId('field-body-type'), { target: { value: 'slim' } });
    fireEvent.change(getByTestId('field-body-type'), { target: { value: 'stocky' } });
    fireEvent.change(getByTestId('field-body-type'), { target: { value: 'average' } });
    expect(fetchMock).not.toHaveBeenCalled();
    await flushDebounce();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/agent/${AGENT_ID}/appearance/preview`);
    expect(init?.method).toBe('POST');
    const body = JSON.parse(init.body);
    expect(body.dsl.body.type).toBe('average');
    await waitFor(() => expect(onPreviewUrlChange).toHaveBeenCalled());
    expect(onPreviewUrlChange).toHaveBeenLastCalledWith('/api/chat/attachments/sha-abc123');
  });

  test('honest-degrade banner on 503 (commit still enabled)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    });
    (globalThis as any).fetch = fetchMock;
    const onPreviewUrlChange = vi.fn();
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={onPreviewUrlChange}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    fireEvent.change(getByTestId('field-body-type'), { target: { value: 'slim' } });
    await flushDebounce();
    await waitFor(() => {
      const banner = getByTestId('preview-banner');
      expect(banner.getAttribute('data-status')).toBe('unavailable');
    });
    // onPreviewUrlChange is called with null so the popout reverts.
    expect(onPreviewUrlChange).toHaveBeenCalledWith(null);
    // Approve button remains enabled (honest-degrade).
    const approve = getByTestId('editor-approve') as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
  });

  test('field-level error on 422 (schema violation surfaces inline)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => ({
        detail: {
          reason: 'invalid body.type',
          field_errors: { 'body.type': 'body.type must be slim|average|stocky' },
        },
      }),
    });
    (globalThis as any).fetch = fetchMock;
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={() => { /* no-op */ }}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    fireEvent.change(getByTestId('field-body-type'), { target: { value: 'slim' } });
    await flushDebounce();
    await waitFor(() => {
      expect(getByTestId('field-error-body-type').textContent).toContain('body.type must be');
    });
  });

  test('Approve calls PUT /appearance with the edited DSL', async () => {
    const calls: { url: string; init: any }[] = [];
    const fetchMock = vi.fn().mockImplementation((url: string, init: any) => {
      calls.push({ url, init });
      if (url.endsWith('/appearance/preview')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ attachment_id: 'sha-xyz' }),
        });
      }
      if (url.endsWith('/appearance') && init?.method === 'PUT') {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    });
    (globalThis as any).fetch = fetchMock;
    const onApproved = vi.fn();
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={() => { /* no-op */ }}
        onApproved={onApproved}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    fireEvent.change(getByTestId('field-hair-style'), { target: { value: 'long' } });
    await flushDebounce();
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    fireEvent.click(getByTestId('editor-approve'));
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    const putCall = calls.find((c) => c.url.endsWith('/appearance') && c.init?.method === 'PUT');
    expect(putCall).toBeDefined();
    const body = JSON.parse(putCall!.init.body);
    expect(body.dsl.hair.style).toBe('long');
  });

  test('Cancel clears the preview URL and calls onCancelled', () => {
    const onCancelled = vi.fn();
    const onPreviewUrlChange = vi.fn();
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={onPreviewUrlChange}
        onApproved={() => { /* no-op */ }}
        onCancelled={onCancelled}
      />,
    );
    fireEvent.click(getByTestId('editor-cancel'));
    expect(onPreviewUrlChange).toHaveBeenCalledWith(null);
    expect(onCancelled).toHaveBeenCalled();
  });

  test('hex<->hsl conversion roundtrip is stable for primary colors', () => {
    const cases = ['#ff0000', '#00ff00', '#0000ff', '#808080', '#2a4a6a'];
    for (const hex of cases) {
      const hsl = _hexToHsl(hex);
      const back = _hslToHex(hsl);
      // Allow 1-bit drift from rounding (HSL is lossy).
      const original = parseInt(hex.slice(1), 16);
      const restored = parseInt(back.slice(1), 16);
      const diffR = Math.abs(((original >> 16) & 0xff) - ((restored >> 16) & 0xff));
      const diffG = Math.abs(((original >> 8) & 0xff) - ((restored >> 8) & 0xff));
      const diffB = Math.abs((original & 0xff) - (restored & 0xff));
      expect(diffR + diffG + diffB).toBeLessThan(6);
    }
  });

  test('does NOT call /appearance/propose (Counselor iteration counter untouched)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ attachment_id: 'sha-zzz' }),
    });
    (globalThis as any).fetch = fetchMock;
    const { getByTestId } = render(
      <CrewAvatarEditor
        agentId={AGENT_ID}
        currentDsl={mkDsl()}
        onPreviewUrlChange={() => { /* no-op */ }}
        onApproved={() => { /* no-op */ }}
        onCancelled={() => { /* no-op */ }}
      />,
    );
    fireEvent.change(getByTestId('field-outfit-style'), { target: { value: 'tactical' } });
    await flushDebounce();
    // None of the fetches must hit the propose path (AD-721d-1 iteration
    // counter is on /propose only; the Captain editor uses /preview only).
    for (const call of fetchMock.mock.calls) {
      expect(String(call[0])).not.toMatch(/appearance\/propose/);
    }
    expect(fetchMock).toHaveBeenCalled();
  });
});
