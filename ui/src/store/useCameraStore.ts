/* AD-733 — Camera streaming Zustand store. */

import { create } from 'zustand';

export type IndicatorCorner = 'tl' | 'tr' | 'bl' | 'br';
const INDICATOR_CORNER_KEY = 'probos.camera.indicator_corner';
const _CORNERS: readonly IndicatorCorner[] = ['tl', 'tr', 'bl', 'br'] as const;

function _loadCorner(): IndicatorCorner {
  try {
    const raw = localStorage.getItem(INDICATOR_CORNER_KEY);
    if (raw && (_CORNERS as readonly string[]).includes(raw)) {
      return raw as IndicatorCorner;
    }
  } catch {
    // SSR / private-mode / quota — fall through to default.
  }
  return 'tr';
}

function _saveCorner(corner: IndicatorCorner): void {
  try {
    localStorage.setItem(INDICATOR_CORNER_KEY, corner);
  } catch {
    // ignore persistence failure; runtime state still updated
  }
}

export interface CameraState {
  active: boolean;
  sessionId: string | null;
  error: string | null;
  fps: number;
  framesSent: number;
  /** BF-301: which screen corner the persistent indicator anchors to. */
  indicatorCorner: IndicatorCorner;

  setError: (msg: string | null) => void;
  setActive: (active: boolean, sessionId?: string | null) => void;
  incrementFramesSent: () => void;
  setFps: (fps: number) => void;
  cycleIndicatorCorner: () => void;
  setIndicatorCorner: (corner: IndicatorCorner) => void;
  reset: () => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  active: false,
  sessionId: null,
  error: null,
  fps: 1,
  framesSent: 0,
  indicatorCorner: _loadCorner(),

  setError: (msg) => set({ error: msg }),
  setActive: (active, sessionId = null) => set({ active, sessionId }),
  incrementFramesSent: () => set((s) => ({ framesSent: s.framesSent + 1 })),
  setFps: (fps) => set({ fps }),
  cycleIndicatorCorner: () =>
    set((s) => {
      const next = _CORNERS[(_CORNERS.indexOf(s.indicatorCorner) + 1) % _CORNERS.length];
      _saveCorner(next);
      return { indicatorCorner: next };
    }),
  setIndicatorCorner: (corner) => {
    _saveCorner(corner);
    set({ indicatorCorner: corner });
  },
  // BF-301: reset preserves indicatorCorner — user's spatial preference
  // should survive a camera revoke/restart cycle.
  reset: () => set({ active: false, sessionId: null, error: null, framesSent: 0 }),
}));
