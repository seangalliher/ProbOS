/**
 * AD-733c-2: CameraLiveIndicator mode badge tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';

import CameraLiveIndicator from '../CameraLiveIndicator';
import { useCameraStore } from '../../../store/useCameraStore';
import { usePerceptionModeStore } from '../../../store/usePerceptionModeStore';

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
  });
}

describe('CameraLiveIndicator mode badge (AD-733c-2)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders amber ENGAGED badge when mode is engaged', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      usePerceptionModeStore.setState({ mode: 'engaged', available: true });
    });
    render(<CameraLiveIndicator />);
    const badge = screen.getByTestId('perception-mode-badge');
    expect(badge.getAttribute('data-mode')).toBe('engaged');
    expect(badge.textContent).toBe('ENGAGED');
    // Amber color #f0b060
    expect(badge.getAttribute('style')).toMatch(/240, ?176, ?96|f0b060/i);
  });

  it('renders dim DORMANT badge when mode is dormant', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      usePerceptionModeStore.setState({ mode: 'dormant', available: true });
    });
    render(<CameraLiveIndicator />);
    const badge = screen.getByTestId('perception-mode-badge');
    expect(badge.getAttribute('data-mode')).toBe('dormant');
    expect(badge.textContent).toBe('DORMANT');
  });

  it('does NOT render the badge when mode is null (controller unavailable)', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      usePerceptionModeStore.setState({ mode: null, available: false });
    });
    render(<CameraLiveIndicator />);
    expect(screen.queryByTestId('perception-mode-badge')).toBeNull();
  });
});
