/**
 * AD-733c-7-5 — CameraLiveIndicator SPEECH badge.
 *
 * BF-287: real Zustand stores; the test asserts against the badge's
 * data-fresh attribute + color after a real ``noteSpeechEvent()`` call
 * and after the flash window decays.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';

import CameraLiveIndicator from '../CameraLiveIndicator';
import { useCameraStore } from '../../../store/useCameraStore';
import { usePerceptionModeStore } from '../../../store/usePerceptionModeStore';
import { useSettingsStore } from '../../../store/useSettingsStore';

function makeSnapshot(vadEnabled: boolean) {
  return {
    config: {
      perception: { enabled: true, vad_engagement_enabled: vadEnabled },
      cognitive: { llm_base_url_vision: '', llm_model_vision: '' },
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

function reset(vadEnabled: boolean) {
  useCameraStore.setState({
    active: true,
    sessionId: 'cam-1',
    error: null,
    framesSent: 0,
    fps: 1,
  });
  usePerceptionModeStore.setState({
    mode: 'ambient',
    since: null,
    lastDmActivity: null,
    presets: null,
    transitions: [],
    available: true,
    perAgent: {},
    lastSpeechAt: null,
  });
  useSettingsStore.setState({ snapshot: makeSnapshot(vadEnabled) as any } as any);
}

describe('CameraLiveIndicator SPEECH badge (AD-733c-7-5)', () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

  it('hidden when disabled; flashes amber on event then fades to dim after 1.5s', () => {
    // (1) Disabled posture — badge absent (back-compat regression).
    reset(false);
    const { unmount } = render(<CameraLiveIndicator />);
    expect(screen.queryByTestId('perception-speech-badge')).toBeNull();
    unmount();

    // (2) Enabled posture — flash + decay.
    vi.useFakeTimers();
    reset(true);
    render(<CameraLiveIndicator />);
    const before = screen.getByTestId('perception-speech-badge');
    expect(before.getAttribute('data-fresh')).toBe('false');

    act(() => { usePerceptionModeStore.getState().noteSpeechEvent(); });
    const fresh = screen.getByTestId('perception-speech-badge');
    expect(fresh.getAttribute('data-fresh')).toBe('true');
    expect(fresh.getAttribute('style')).toMatch(/240, ?176, ?96|f0b060/i);

    act(() => { vi.advanceTimersByTime(1600); });
    const decayed = screen.getByTestId('perception-speech-badge');
    expect(decayed.getAttribute('data-fresh')).toBe('false');
  });
});
