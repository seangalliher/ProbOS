/* AD-733 — Camera streaming Zustand store. */

import { create } from 'zustand';

export type IndicatorCorner = 'tl' | 'tr' | 'bl' | 'br';
export interface PreviewPosition { x: number; y: number }
const INDICATOR_CORNER_KEY = 'probos.camera.indicator_corner';
const PREVIEW_ENABLED_KEY = 'probos.camera.preview_enabled';
const PREVIEW_POSITION_KEY = 'probos.camera.preview_position';
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

function _loadPreview(): boolean {
  try {
    return localStorage.getItem(PREVIEW_ENABLED_KEY) === 'true';
  } catch {
    return false;
  }
}

function _savePreview(enabled: boolean): void {
  try {
    localStorage.setItem(PREVIEW_ENABLED_KEY, enabled ? 'true' : 'false');
  } catch {
    // ignore
  }
}

function _loadPreviewPosition(): PreviewPosition | null {
  try {
    const raw = localStorage.getItem(PREVIEW_POSITION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed.x === 'number' &&
      typeof parsed.y === 'number' &&
      Number.isFinite(parsed.x) &&
      Number.isFinite(parsed.y)
    ) {
      return { x: parsed.x, y: parsed.y };
    }
  } catch {
    // ignore corrupt entry; fall back to corner default
  }
  return null;
}

function _savePreviewPosition(pos: PreviewPosition | null): void {
  try {
    if (pos === null) {
      localStorage.removeItem(PREVIEW_POSITION_KEY);
    } else {
      localStorage.setItem(PREVIEW_POSITION_KEY, JSON.stringify(pos));
    }
  } catch {
    // ignore
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
  /** BF-302: operator preview panel — mirror video + force-describe button. */
  previewEnabled: boolean;
  /** BF-305: free-drag pixel position; null = default corner (bottom-left). */
  previewPosition: PreviewPosition | null;

  setError: (msg: string | null) => void;
  setActive: (active: boolean, sessionId?: string | null) => void;
  incrementFramesSent: () => void;
  setFps: (fps: number) => void;
  cycleIndicatorCorner: () => void;
  setIndicatorCorner: (corner: IndicatorCorner) => void;
  togglePreview: () => void;
  setPreviewPosition: (pos: PreviewPosition) => void;
  resetPreviewPosition: () => void;
  reset: () => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  active: false,
  sessionId: null,
  error: null,
  fps: 1,
  framesSent: 0,
  indicatorCorner: _loadCorner(),
  previewEnabled: _loadPreview(),
  previewPosition: _loadPreviewPosition(),

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
  togglePreview: () =>
    set((s) => {
      const next = !s.previewEnabled;
      _savePreview(next);
      return { previewEnabled: next };
    }),
  setPreviewPosition: (pos) => {
    _savePreviewPosition(pos);
    set({ previewPosition: pos });
  },
  resetPreviewPosition: () => {
    _savePreviewPosition(null);
    set({ previewPosition: null });
  },
  // BF-301: reset preserves indicatorCorner — user's spatial preference
  // should survive a camera revoke/restart cycle.
  reset: () => set({ active: false, sessionId: null, error: null, framesSent: 0 }),
}));
