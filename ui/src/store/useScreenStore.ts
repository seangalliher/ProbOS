/* AD-733-2 — Screen streaming Zustand store.
 *
 * Sibling of useCameraStore (NOT a merger — different lifecycles, SRP wins
 * per the AD-742c-6 precedent). v1 keeps the slice intentionally minimal:
 * the SCREEN LIVE indicator only needs active/sessionId/framesSent/error.
 * Preview-panel + corner placement are camera-only in v1.
 */

import { create } from 'zustand';

export interface ScreenState {
  active: boolean;
  sessionId: string | null;
  error: string | null;
  framesSent: number;

  setError: (msg: string | null) => void;
  setActive: (active: boolean, sessionId?: string | null) => void;
  incrementFramesSent: () => void;
  reset: () => void;
}

export const useScreenStore = create<ScreenState>((set) => ({
  active: false,
  sessionId: null,
  error: null,
  framesSent: 0,

  setError: (msg) => set({ error: msg }),
  setActive: (active, sessionId = null) => set({ active, sessionId }),
  incrementFramesSent: () => set((s) => ({ framesSent: s.framesSent + 1 })),
  reset: () => set({ active: false, sessionId: null, error: null, framesSent: 0 }),
}));
