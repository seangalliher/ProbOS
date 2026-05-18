/**
 * AD-733: CameraLiveIndicator tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';

import CameraLiveIndicator from '../CameraLiveIndicator';
import { useCameraStore } from '../../../store/useCameraStore';

function reset() {
  useCameraStore.setState({ active: false, sessionId: null, error: null, framesSent: 0, fps: 1 });
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
});
