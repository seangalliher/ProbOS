/* AD-733 — Camera streaming Zustand store. */

import { create } from 'zustand';

export interface CameraState {
  active: boolean;
  sessionId: string | null;
  error: string | null;
  fps: number;
  framesSent: number;

  setError: (msg: string | null) => void;
  setActive: (active: boolean, sessionId?: string | null) => void;
  incrementFramesSent: () => void;
  setFps: (fps: number) => void;
  reset: () => void;
}

export const useCameraStore = create<CameraState>((set) => ({
  active: false,
  sessionId: null,
  error: null,
  fps: 1,
  framesSent: 0,

  setError: (msg) => set({ error: msg }),
  setActive: (active, sessionId = null) => set({ active, sessionId }),
  incrementFramesSent: () => set((s) => ({ framesSent: s.framesSent + 1 })),
  setFps: (fps) => set({ fps }),
  reset: () => set({ active: false, sessionId: null, error: null, framesSent: 0 }),
}));
