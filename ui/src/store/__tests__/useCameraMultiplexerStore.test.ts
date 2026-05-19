/**
 * AD-742c-6 — useCameraMultiplexerStore tests.
 *
 * BF-287: real Zustand store; fetch + navigator.mediaDevices mocked at
 * the network/browser boundary only.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useCameraMultiplexerStore } from '../useCameraMultiplexerStore';

function reset() {
  useCameraMultiplexerStore.setState({ bindings: {}, devices: [], loaded: false });
}

describe('useCameraMultiplexerStore (AD-742c-6)', () => {
  beforeEach(reset);
  afterEach(() => { vi.restoreAllMocks(); reset(); });

  it('refresh() populates bindings (from /cameras) and devices (from enumerateDevices) in parallel', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ bindings: { e1: 'devA', e2: '' } }),
    });
    (globalThis as any).fetch = fetchMock;
    (globalThis as any).navigator = {
      mediaDevices: {
        enumerateDevices: vi.fn().mockResolvedValue([
          { deviceId: 'devA', kind: 'videoinput', label: 'Front Cam' },
          { deviceId: 'devB', kind: 'videoinput', label: 'Side Cam' },
          { deviceId: 'mic1', kind: 'audioinput', label: 'Mic' },
        ]),
      },
    };

    await useCameraMultiplexerStore.getState().refresh();
    const state = useCameraMultiplexerStore.getState();
    expect(state.bindings).toEqual({ e1: 'devA', e2: '' });
    // Filtered to videoinput only.
    expect(state.devices).toHaveLength(2);
    expect(state.devices[0].deviceId).toBe('devA');
    expect(state.loaded).toBe(true);
  });

  it('bindAgent posts to /cameras/binding and mirrors local state on 200', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, agent_id: 'e1', device_id: 'devB' }),
    });
    (globalThis as any).fetch = fetchMock;

    await useCameraMultiplexerStore.getState().bindAgent('e1', 'devB');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/perception/cameras/binding');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({ agent_id: 'e1', device_id: 'devB' });
    expect(useCameraMultiplexerStore.getState().bindings.e1).toBe('devB');
  });
});
