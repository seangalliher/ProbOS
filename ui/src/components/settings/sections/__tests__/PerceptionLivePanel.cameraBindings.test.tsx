/**
 * AD-742c-6 — PerceptionLivePanel CAMERA BINDINGS section tests.
 *
 * BF-287: real Zustand stores; fetch + enumerateDevices mocked at the
 * boundary only.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, act, waitFor } from '@testing-library/react';

import PerceptionLivePanel from '../PerceptionLivePanel';
import { useSettingsStore } from '../../../../store/useSettingsStore';
import { useCameraStore } from '../../../../store/useCameraStore';
import { usePerceptionModeStore } from '../../../../store/usePerceptionModeStore';
import { useCameraMultiplexerStore } from '../../../../store/useCameraMultiplexerStore';

function makeSnapshot() {
  return {
    config: {
      perception: { enabled: true },
      cognitive: { llm_base_url_vision: 'x', llm_model_vision: 'y' },
    },
    secret_present: {},
    sections: [],
    domain_counts: {},
    domain_order: [],
    section_count: 0,
    config_path: '/tmp/system.yaml',
    uptime_seconds: 1,
    csrf_token: 'tk',
  };
}

function reset() {
  useSettingsStore.setState({ snapshot: makeSnapshot() as any } as any);
  useCameraStore.setState({ active: false, error: null, framesSent: 0 });
  usePerceptionModeStore.setState({
    mode: null,
    since: null,
    lastDmActivity: null,
    presets: null,
    transitions: [],
    available: false,
    perAgent: {},
    lastSpeechAt: null,
  });
  useCameraMultiplexerStore.setState({ bindings: {}, devices: [], loaded: false });
}

describe('PerceptionLivePanel CAMERA BINDINGS (AD-742c-6)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('CAMERA BINDINGS section collapsed by default; table absent until toggle', () => {
    render(<PerceptionLivePanel />);
    expect(screen.getByTestId('perception-camera-bindings-toggle')).toBeTruthy();
    expect(screen.queryByTestId('perception-camera-bindings-table')).toBeNull();
  });

  it('toggle expands the table; clicking again collapses it', async () => {
    // Stub fetch + enumerateDevices for the refresh that fires on expand.
    (globalThis as any).fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ bindings: {} }),
    });
    (globalThis as any).navigator = {
      mediaDevices: { enumerateDevices: vi.fn().mockResolvedValue([]) },
    };
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    expect(screen.getByTestId('perception-camera-bindings-table')).toBeTruthy();
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    expect(screen.queryByTestId('perception-camera-bindings-table')).toBeNull();
  });

  it('binding dropdown POSTs to /api/perception/cameras/binding', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({  // refresh /cameras
        ok: true, json: async () => ({ bindings: { e1: '' } }),
      })
      .mockResolvedValueOnce({  // bindAgent POST
        ok: true, json: async () => ({ ok: true, agent_id: 'e1', device_id: 'devA' }),
      });
    (globalThis as any).fetch = fetchMock;
    (globalThis as any).navigator = {
      mediaDevices: {
        enumerateDevices: vi.fn().mockResolvedValue([
          { deviceId: 'devA', kind: 'videoinput', label: 'Cam' },
        ]),
      },
    };

    // Seed the bindings directly so the row renders without waiting on
    // the async refresh — the dropdown change is the load-bearing
    // assertion in this test.
    act(() => {
      useCameraMultiplexerStore.setState({
        bindings: { e1: '' },
        devices: [{ deviceId: 'devA', kind: 'videoinput', label: 'Cam' } as MediaDeviceInfo],
        loaded: true,
      });
    });
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const select = await screen.findByTestId('perception-camera-binding-select-e1');
    fireEvent.change(select, { target: { value: 'devA' } });

    await waitFor(() => {
      const bindCall = fetchMock.mock.calls.find(
        ([url]) => url === '/api/perception/cameras/binding',
      );
      expect(bindCall).toBeDefined();
      const [, init] = bindCall!;
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body as string)).toEqual({ agent_id: 'e1', device_id: 'devA' });
    });
  });

  it('single-camera deployments render bit-for-bit identical UI to HEAD (no CAMS label, no expanded table)', () => {
    // Empty bindings = solo posture.
    render(<PerceptionLivePanel />);
    expect(screen.queryByTestId('perception-cams-label')).toBeNull();
    expect(screen.queryByTestId('perception-camera-bindings-table')).toBeNull();
  });
});
