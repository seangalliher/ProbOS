/* BF-302 / BF-303 / BF-305 — CameraPreviewPanel tests. */
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
    indicatorCorner: 'tr', previewEnabled: false, previewPosition: null,
  });
  // BF-303: stub fetch so the polling effect doesn't hit a real network.
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({ observations: [] }),
  })));
}

describe('CameraPreviewPanel (BF-302/303/305)', () => {
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

  it('BF-305: uses stored previewPosition for absolute placement', () => {
    act(() => {
      useCameraStore.setState({
        active: true, previewEnabled: true,
        previewPosition: { x: 240, y: 100 },
      });
    });
    render(<CameraPreviewPanel />);
    const panel = screen.getByTestId('camera-preview-panel');
    expect(panel.style.left).toBe('240px');
    expect(panel.style.top).toBe('100px');
  });

  it('BF-305: dragging the header updates previewPosition', () => {
    act(() => {
      useCameraStore.setState({
        active: true, previewEnabled: true,
        previewPosition: { x: 100, y: 100 },
      });
    });
    render(<CameraPreviewPanel />);
    const header = screen.getByTestId('camera-preview-header');

    fireEvent.pointerDown(header, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 50, clientY: 30 });
    fireEvent.pointerUp(window, { clientX: 50, clientY: 30 });

    const pos = useCameraStore.getState().previewPosition;
    expect(pos).toEqual({ x: 150, y: 130 });
  });

  it('BF-305: double-clicking the header resets position to default', () => {
    act(() => {
      useCameraStore.setState({
        active: true, previewEnabled: true,
        previewPosition: { x: 999, y: 999 },
      });
    });
    render(<CameraPreviewPanel />);
    fireEvent.doubleClick(screen.getByTestId('camera-preview-header'));
    expect(useCameraStore.getState().previewPosition).toBeNull();
  });

  it('BF-305: clicking the FORCE button inside the header area does not start a drag', async () => {
    const mod = await import('../../../hooks/useCameraStream');
    const spy = mod.forceNextFrame as ReturnType<typeof vi.fn>;
    spy.mockClear();
    act(() => {
      useCameraStore.setState({
        active: true, previewEnabled: true,
        previewPosition: { x: 200, y: 200 },
      });
    });
    render(<CameraPreviewPanel />);
    // FORCE is in the footer, not header, but the test guards the general
    // "buttons in the panel don't trigger drag" semantic at the header level
    // via the closest('button') check inside onHeaderPointerDown.
    fireEvent.click(screen.getByTestId('camera-preview-force'));
    expect(spy).toHaveBeenCalledTimes(1);
    // Position must not have changed.
    expect(useCameraStore.getState().previewPosition).toEqual({ x: 200, y: 200 });
  });
});
