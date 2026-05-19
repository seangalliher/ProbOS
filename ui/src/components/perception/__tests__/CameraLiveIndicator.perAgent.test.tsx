/**
 * AD-733c-5-4: per-agent perception badges in CameraLiveIndicator +
 * PerceptionLivePanel. Real Zustand stores; fetch mocked at the network
 * boundary only (BF-287).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';

import CameraLiveIndicator from '../CameraLiveIndicator';
import PerceptionLivePanel from '../../settings/sections/PerceptionLivePanel';
import { useCameraStore } from '../../../store/useCameraStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { usePerceptionModeStore } from '../../../store/usePerceptionModeStore';

function makeSnapshot() {
  return {
    config: {
      perception: { enabled: true },
      cognitive: {
        llm_base_url_vision: 'http://localhost:11434',
        llm_model_vision: 'qwen3.6:27b',
      },
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
  useCameraStore.setState({
    active: false,
    sessionId: null,
    error: null,
    framesSent: 0,
    fps: 1,
  });
  usePerceptionModeStore.setState({
    mode: null,
    since: null,
    lastDmActivity: null,
    presets: null,
    transitions: [],
    available: false,
    perAgent: {},
  });
  useSettingsStore.setState({
    snapshot: makeSnapshot() as any,
  } as any);
}

describe('CameraLiveIndicator per-agent badges (AD-733c-5-4)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders per-agent badges when perAgent has 2+ entries', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      usePerceptionModeStore.setState({
        mode: 'ambient',
        available: true,
        perAgent: { e1: 'engaged', e2: 'ambient' },
      });
    });
    render(<CameraLiveIndicator />);
    const e1 = screen.getByTestId('perception-per-agent-badge-e1');
    const e2 = screen.getByTestId('perception-per-agent-badge-e2');
    expect(e1.getAttribute('data-mode')).toBe('engaged');
    expect(e2.getAttribute('data-mode')).toBe('ambient');
    expect(e1.textContent).toBe('E1:ENG');
    expect(e2.textContent).toBe('E2:AMB');
    // Amber for engaged, mid-amber for ambient.
    expect(e1.getAttribute('style')).toMatch(/240, ?176, ?96|f0b060/i);
    expect(e2.getAttribute('style')).toMatch(/160, ?120, ?64|a07840/i);
    // Single-mode badge suppressed when per-agent surface active.
    expect(screen.queryByTestId('perception-mode-badge')).toBeNull();
  });

  it('falls back to single mode badge when perAgent has < 2 entries', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      usePerceptionModeStore.setState({
        mode: 'ambient',
        available: true,
        perAgent: {},
      });
    });
    render(<CameraLiveIndicator />);
    const badge = screen.getByTestId('perception-mode-badge');
    expect(badge.textContent).toBe('AMBIENT');
    expect(screen.queryByTestId('perception-per-agent-badges')).toBeNull();
  });
});

describe('PerceptionLivePanel per-agent table (AD-733c-5-4)', () => {
  beforeEach(() => {
    reset();
    // Panel calls fetch on mount via the mode-store refresh ticker. Stub
    // it so the test does not hit the network.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({}),
    }));
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); reset(); });

  it('renders per-agent table when registry has 2+ entries', () => {
    act(() => {
      usePerceptionModeStore.setState({
        mode: 'ambient',
        available: true,
        perAgent: { e1: 'engaged', e2: 'dormant' },
      });
    });
    render(<PerceptionLivePanel />);
    const table = screen.getByTestId('perception-per-agent-table');
    expect(table).toBeTruthy();
    const r1 = screen.getByTestId('perception-per-agent-row-e1');
    const r2 = screen.getByTestId('perception-per-agent-row-e2');
    expect(r1.textContent).toMatch(/E1.*ENGAGED/);
    expect(r2.textContent).toMatch(/E2.*DORMANT/);
  });
});
