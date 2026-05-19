/**
 * AD-733: CameraLiveIndicator tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';

import CameraLiveIndicator from '../CameraLiveIndicator';
import { useCameraStore } from '../../../store/useCameraStore';
import { useScreenStore } from '../../../store/useScreenStore';

function reset() {
  useCameraStore.setState({ active: false, sessionId: null, error: null, framesSent: 0, fps: 1 });
  useScreenStore.setState({ active: false, sessionId: null, error: null, framesSent: 0 });
}

describe('CameraLiveIndicator (AD-733)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when camera is not active', () => {
    render(<CameraLiveIndicator />);
    expect(screen.queryByTestId('camera-live-indicator')).toBeNull();
  });

  it('renders red dot + REVOKE button when camera is active', () => {
    act(() => { useCameraStore.setState({ active: true, sessionId: 'cam-test-123' }); });
    render(<CameraLiveIndicator />);
    expect(screen.getByTestId('camera-live-indicator')).toBeTruthy();
    expect(screen.getByTestId('camera-live-revoke')).toBeTruthy();
    expect(screen.getByText('CAMERA LIVE')).toBeTruthy();
  });

  it('BF-301: defaults to top-right corner', () => {
    act(() => { useCameraStore.setState({ active: true, indicatorCorner: 'tr' }); });
    render(<CameraLiveIndicator />);
    const indicator = screen.getByTestId('camera-live-indicator');
    expect(indicator.getAttribute('data-corner')).toBe('tr');
  });

  it('BF-301: move button cycles through all four corners and persists to localStorage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    act(() => { useCameraStore.setState({ active: true, indicatorCorner: 'tr' }); });
    render(<CameraLiveIndicator />);
    const moveBtn = screen.getByTestId('camera-live-move');

    fireEvent.click(moveBtn);
    expect(screen.getByTestId('camera-live-indicator').getAttribute('data-corner')).toBe('bl');

    fireEvent.click(moveBtn);
    expect(screen.getByTestId('camera-live-indicator').getAttribute('data-corner')).toBe('br');

    fireEvent.click(moveBtn);
    expect(screen.getByTestId('camera-live-indicator').getAttribute('data-corner')).toBe('tl');

    fireEvent.click(moveBtn);
    expect(screen.getByTestId('camera-live-indicator').getAttribute('data-corner')).toBe('tr');

    expect(setItem).toHaveBeenCalledWith('probos.camera.indicator_corner', expect.any(String));
  });
});

describe('CameraLiveIndicator — SCREEN LIVE row (AD-733-2)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when both camera and screen are inactive', () => {
    render(<CameraLiveIndicator />);
    expect(screen.queryByTestId('camera-live-indicator')).toBeNull();
    expect(screen.queryByTestId('screen-live-indicator')).toBeNull();
  });

  it('renders SCREEN LIVE row + REVOKE when only screen is active', () => {
    act(() => {
      useScreenStore.setState({ active: true, sessionId: 'scr-1' });
    });
    render(<CameraLiveIndicator />);
    expect(screen.queryByTestId('camera-live-indicator')).toBeNull();
    expect(screen.getByTestId('screen-live-indicator')).toBeTruthy();
    expect(screen.getByTestId('screen-live-revoke')).toBeTruthy();
    expect(screen.getByText('SCREEN LIVE')).toBeTruthy();
  });

  it('renders BOTH camera and screen indicators when both active', () => {
    act(() => {
      useCameraStore.setState({ active: true, sessionId: 'cam-1' });
      useScreenStore.setState({ active: true, sessionId: 'scr-1' });
    });
    render(<CameraLiveIndicator />);
    expect(screen.getByTestId('camera-live-indicator')).toBeTruthy();
    expect(screen.getByTestId('screen-live-indicator')).toBeTruthy();
  });
});
