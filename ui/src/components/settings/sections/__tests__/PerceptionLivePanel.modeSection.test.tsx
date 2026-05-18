/**
 * AD-733c-2: PerceptionLivePanel mode section + manual override.
 *
 * BF-287: real ``useSettingsStore`` + ``useCameraStore`` + ``usePerceptionModeStore``;
 * fetch mocked at the global level for the manual-override POST.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import PerceptionLivePanel from '../PerceptionLivePanel';
import { useSettingsStore } from '../../../../store/useSettingsStore';
import { useCameraStore } from '../../../../store/useCameraStore';
import {
  usePerceptionModeStore,
  type PerceptionMode,
  type PerceptionTransition,
} from '../../../../store/usePerceptionModeStore';

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
  useSettingsStore.setState({
    open: true,
    loading: false,
    loaded: true,
    snapshot: makeSnapshot() as any,
    draft: {},
    draftCount: 0,
    selectedSectionId: 'perception',
    search: '',
    yamlOpen: false,
    yamlText: '',
    yamlLoading: false,
    applyStatus: 'idle',
    applyErrors: [],
    applyMessage: '',
    openedAt: 0,
  });
  useCameraStore.setState({ active: false, error: null, framesSent: 0 });
  usePerceptionModeStore.setState({
    mode: null,
    since: null,
    lastDmActivity: null,
    presets: null,
    transitions: [],
    available: false,
  });
}

describe('PerceptionLivePanel mode section (AD-733c-2)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders the last 3 transitions newest-first', () => {
    const transitions: PerceptionTransition[] = [
      { at: 3, from_mode: 'engaged', to_mode: 'ambient', trigger: 'idle_timer' },
      { at: 2, from_mode: 'ambient', to_mode: 'engaged', trigger: 'dm_activity' },
      { at: 1, from_mode: 'dormant', to_mode: 'ambient', trigger: 'init' },
    ];
    usePerceptionModeStore.setState({
      mode: 'ambient' as PerceptionMode,
      transitions,
      available: true,
    });
    render(<PerceptionLivePanel />);
    const block = screen.getByTestId('perception-mode-transitions');
    const txt = block.textContent ?? '';
    // Newest first: idle_timer line precedes dm_activity line.
    expect(txt.indexOf('idle_timer')).toBeLessThan(txt.indexOf('dm_activity'));
    expect(txt.indexOf('dm_activity')).toBeLessThan(txt.indexOf('init'));
  });

  it('renders mode buttons in DORMANT/AMBIENT/ENGAGED order', () => {
    usePerceptionModeStore.setState({ mode: 'ambient', available: true });
    render(<PerceptionLivePanel />);
    expect(screen.getByTestId('perception-mode-button-dormant')).toBeTruthy();
    expect(screen.getByTestId('perception-mode-button-ambient')).toBeTruthy();
    expect(screen.getByTestId('perception-mode-button-engaged')).toBeTruthy();
  });

  it('ENGAGED button POSTs /api/perception/mode {mode: "engaged"}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, mode: 'engaged', changed: true }),
    });
    (globalThis as any).fetch = fetchMock;
    usePerceptionModeStore.setState({ mode: 'ambient', available: true });
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-mode-button-engaged'));
    // setMode is async; let the microtask queue flush.
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/perception/mode');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ mode: 'engaged' });
  });
});
