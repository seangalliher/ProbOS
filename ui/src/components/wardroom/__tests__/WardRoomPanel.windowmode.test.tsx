/** AD-837 (Wave 201) vitest — Ward Room docked ↔ floating ↔ maximized
 * window mode: header controls, geometry persistence, resize clamping, and
 * the HXI no-emoji (stroke-SVG glyph) guard. Frontend-only; no backend. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore, loadWardRoomLayout } from '../../../store/useStore';
import { WardRoomPanel } from '../WardRoomPanel';

const DEFAULT_RECT = { x: 80, y: 80, w: 720, h: 640 };

beforeEach(() => {
  localStorage.clear();
  useStore.setState({
    wardRoomOpen: true,
    wardRoomChannels: [],
    wardRoomDmChannels: [],
    wardRoomThreads: [],
    wardRoomActiveThread: null,
    wardRoomActiveChannel: null,
    wardRoomView: 'channels',
    wardRoomDisplayMode: 'docked',
    wardRoomWindowRect: { ...DEFAULT_RECT },
  });
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: async () => ({}) }) as any
  );
});

afterEach(() => {
  cleanup();
});

describe('WardRoomPanel window mode (AD-837)', () => {
  it('1. defaults to the docked 420px left sidebar', () => {
    render(<WardRoomPanel />);
    const panel = screen.getByTestId('wardroom-panel');
    expect(panel.getAttribute('data-mode')).toBe('docked');
    expect(panel.style.width).toBe('420px');
    expect(panel.style.left).toBe('0px');
  });

  it('2. Undock switches to a floating window at the persisted/default rect', () => {
    render(<WardRoomPanel />);
    fireEvent.click(screen.getByLabelText('Undock Ward Room'));
    const panel = screen.getByTestId('wardroom-panel');
    expect(panel.getAttribute('data-mode')).toBe('floating');
    expect(panel.style.left).toBe('80px');
    expect(panel.style.top).toBe('80px');
    expect(panel.style.width).toBe('720px');
    expect(panel.style.height).toBe('640px');
  });

  it('3. Maximize fills the viewport; Restore returns to the prior floating rect', () => {
    useStore.setState({ wardRoomDisplayMode: 'floating' });
    render(<WardRoomPanel />);
    fireEvent.click(screen.getByLabelText('Maximize Ward Room'));
    expect(screen.getByTestId('wardroom-panel').getAttribute('data-mode')).toBe('maximized');

    fireEvent.click(screen.getByLabelText('Restore Ward Room'));
    const panel = screen.getByTestId('wardroom-panel');
    expect(panel.getAttribute('data-mode')).toBe('floating');
    // Rect is untouched by maximize/restore — prior geometry preserved.
    expect(panel.style.width).toBe('720px');
    expect(panel.style.height).toBe('640px');
  });

  it('4. Dock returns to the sidebar; maximize control hidden in docked mode', () => {
    useStore.setState({ wardRoomDisplayMode: 'floating' });
    render(<WardRoomPanel />);
    fireEvent.click(screen.getByLabelText('Dock Ward Room'));
    expect(screen.getByTestId('wardroom-panel').getAttribute('data-mode')).toBe('docked');
    // Maximize/Restore controls are not rendered while docked.
    expect(screen.queryByLabelText('Maximize Ward Room')).toBeNull();
    expect(screen.queryByLabelText('Restore Ward Room')).toBeNull();
  });

  it('5. changing mode persists probos.wardroom.mode to localStorage', () => {
    render(<WardRoomPanel />);
    fireEvent.click(screen.getByLabelText('Undock Ward Room'));
    expect(localStorage.getItem('probos.wardroom.mode')).toBe('floating');
  });

  it('6. loadWardRoomLayout rehydrates persisted rect; falls back on malformed JSON', () => {
    localStorage.setItem('probos.wardroom.mode', 'floating');
    localStorage.setItem('probos.wardroom.rect', JSON.stringify({ x: 5, y: 6, w: 700, h: 500 }));
    const ok = loadWardRoomLayout();
    expect(ok.mode).toBe('floating');
    expect(ok.rect).toEqual({ x: 5, y: 6, w: 700, h: 500 });

    localStorage.setItem('probos.wardroom.rect', '{not valid json');
    const fallback = loadWardRoomLayout();
    expect(fallback.rect).toEqual(DEFAULT_RECT);
  });

  it('7. resize clamps below the min size to the floor (360×320)', () => {
    useStore.setState({ wardRoomDisplayMode: 'floating' });
    render(<WardRoomPanel />);
    const handle = screen.getByLabelText('Resize Ward Room');
    fireEvent.mouseDown(handle, { clientX: 100, clientY: 100 });
    // Drag far past the lower bound — should clamp, not go negative.
    fireEvent.mouseMove(window, { clientX: -900, clientY: -900 });
    fireEvent.mouseUp(window);
    const rect = useStore.getState().wardRoomWindowRect;
    expect(rect.w).toBe(360);
    expect(rect.h).toBe(320);
  });

  it('8. header controls render stroke-SVG glyphs, not emoji (HXI Principle #3)', () => {
    render(<WardRoomPanel />);
    const undock = screen.getByLabelText('Undock Ward Room');
    expect(undock.querySelector('svg')).toBeTruthy();
    // No emoji codepoints in the control label.
    expect(/\p{Extended_Pictographic}/u.test(undock.textContent || '')).toBe(false);
  });
});

describe('WardRoomPanel three-pane reading layout (AD-837a)', () => {
  it('9. docked mode stays single-column (no three-pane)', () => {
    useStore.setState({ wardRoomDisplayMode: 'docked' });
    render(<WardRoomPanel />);
    expect(screen.queryByTestId('wardroom-three-pane')).toBeNull();
  });

  it('10. maximized mode opens the three-pane channels surface', () => {
    useStore.setState({ wardRoomDisplayMode: 'maximized', wardRoomView: 'channels' });
    render(<WardRoomPanel />);
    expect(screen.getByTestId('wardroom-three-pane')).toBeTruthy();
    expect(screen.getByTestId('wardroom-pane-channels')).toBeTruthy();
    expect(screen.getByTestId('wardroom-pane-threads')).toBeTruthy();
    expect(screen.getByTestId('wardroom-pane-detail')).toBeTruthy();
  });

  it('11. wide floating window (>= threshold) opens three panes', () => {
    useStore.setState({
      wardRoomDisplayMode: 'floating',
      wardRoomWindowRect: { x: 40, y: 40, w: 900, h: 700 },
      wardRoomView: 'channels',
    });
    render(<WardRoomPanel />);
    expect(screen.getByTestId('wardroom-three-pane')).toBeTruthy();
  });

  it('12. narrow floating window (< threshold) stays single-column', () => {
    useStore.setState({
      wardRoomDisplayMode: 'floating',
      wardRoomWindowRect: { x: 40, y: 40, w: 420, h: 600 },
      wardRoomView: 'channels',
    });
    render(<WardRoomPanel />);
    expect(screen.queryByTestId('wardroom-three-pane')).toBeNull();
  });

  it('13. detail pane shows an empty-state placeholder until a thread is selected', () => {
    useStore.setState({
      wardRoomDisplayMode: 'maximized',
      wardRoomView: 'channels',
      wardRoomActiveThread: null,
    });
    render(<WardRoomPanel />);
    const empty = screen.getByTestId('wardroom-detail-empty');
    expect(empty).toBeTruthy();
    expect(empty.querySelector('svg')).toBeTruthy();
    expect(/\p{Extended_Pictographic}/u.test(empty.textContent || '')).toBe(false);
  });

  it('14. selecting a thread keeps the channel + thread rails visible in wide mode', () => {
    useStore.setState({
      wardRoomDisplayMode: 'maximized',
      wardRoomView: 'channels',
      wardRoomActiveThread: 'thread-1',
    });
    render(<WardRoomPanel />);
    // Rails persist alongside the detail pane (no narrow takeover).
    expect(screen.getByTestId('wardroom-pane-channels')).toBeTruthy();
    expect(screen.getByTestId('wardroom-pane-threads')).toBeTruthy();
    expect(screen.queryByTestId('wardroom-detail-empty')).toBeNull();
  });

  it('15. DM Log view does not use the three-pane layout even when wide', () => {
    useStore.setState({
      wardRoomDisplayMode: 'maximized',
      wardRoomView: 'dms',
      // Stub the mount-time refresh so the bare fetch mock can't corrupt the
      // dmChannels array — this test only asserts layout selection.
      refreshWardRoomDmChannels: vi.fn(),
    });
    render(<WardRoomPanel />);
    expect(screen.queryByTestId('wardroom-three-pane')).toBeNull();
  });
});
