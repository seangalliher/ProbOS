/* BF-302 — CameraPreviewPanel tests. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';

import CameraPreviewPanel from '../CameraPreviewPanel';
import { useCameraStore } from '../../../store/useCameraStore';

vi.mock('../../../hooks/useCameraStream', () => ({
  getCameraStream: () => null,
  forceNextFrame: vi.fn(),
}));

function reset() {
  useCameraStore.setState({
    active: false, sessionId: null, error: null, framesSent: 0, fps: 1,
    indicatorCorner: 'tr', previewEnabled: false, previewCorner: 'bl',
  });
  // BF-303: stub fetch so the polling effect doesn't hit a real network.
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({ observations: [] }),
  })));
}

describe('CameraPreviewPanel (BF-302)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when camera is inactive', () => {
    act(() => { useCameraStore.setState({ active: false, previewEnabled: true }); });
    render(<CameraPreviewPanel />);
    expect(screen.queryByTestId('camera-preview-panel')).toBeNull();
  });

  it('renders nothing when preview is disabled', () => {
    act(() => { useCameraStore.setState({ active: true, previewEnabled: false }); });
    render(<CameraPreviewPanel />);
    expect(screen.queryByTestId('camera-preview-panel')).toBeNull();
  });

  it('renders video + force button + frames counter when both active and previewEnabled', () => {
    act(() => { useCameraStore.setState({ active: true, previewEnabled: true, framesSent: 17 }); });
    render(<CameraPreviewPanel />);
    expect(screen.getByTestId('camera-preview-panel')).toBeTruthy();
    expect(screen.getByTestId('camera-preview-video')).toBeTruthy();
    expect(screen.getByTestId('camera-preview-force')).toBeTruthy();
    expect(screen.getByText(/sent: 17/)).toBeTruthy();
  });

  it('FORCE DESCRIBE button calls forceNextFrame', async () => {
    const mod = await import('../../../hooks/useCameraStream');
    const spy = mod.forceNextFrame as ReturnType<typeof vi.fn>;
    spy.mockClear();
    act(() => { useCameraStore.setState({ active: true, previewEnabled: true }); });
    render(<CameraPreviewPanel />);
    fireEvent.click(screen.getByTestId('camera-preview-force'));
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('uses its own previewCorner (BF-303), independent of indicator corner', () => {
    act(() => {
      useCameraStore.setState({
        active: true, previewEnabled: true,
        indicatorCorner: 'tr', previewCorner: 'br',
      });
    });
    render(<CameraPreviewPanel />);
    const panel = screen.getByTestId('camera-preview-panel');
    expect(panel.getAttribute('data-corner')).toBe('br');
    expect(panel.style.bottom).toBe('8px');
    expect(panel.style.right).toBe('8px');
  });

  it('move button cycles preview corner (BF-303)', () => {
    act(() => {
      useCameraStore.setState({ active: true, previewEnabled: true, previewCorner: 'bl' });
    });
    render(<CameraPreviewPanel />);
    fireEvent.click(screen.getByTestId('camera-preview-move'));
    expect(screen.getByTestId('camera-preview-panel').getAttribute('data-corner')).toBe('br');
  });
});
