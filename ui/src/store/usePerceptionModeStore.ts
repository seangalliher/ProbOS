/**
 * AD-733c-2 — Perception mode Zustand slice.
 *
 * Mirrors the backend ``PerceptionModeController`` over the
 * ``/api/perception/mode`` endpoint. The badge in
 * ``CameraLiveIndicator`` and the Mode section in
 * ``PerceptionLivePanel`` subscribe to this store.
 *
 * Per HXI Design Principle #3: NO emoji. All visual differentiation is
 * stroke-color (amber active / dim inactive). Text is monospace.
 */
import { create } from 'zustand';

export type PerceptionMode = 'dormant' | 'ambient' | 'engaged';

export interface PerceptionTransition {
  at: number;
  from_mode: PerceptionMode;
  to_mode: PerceptionMode;
  trigger: string;
}

export interface PerceptionPreset {
  min_interval_seconds: number;
  novelty_threshold: number;
  baseline_max_age_seconds: number;
}

interface PerceptionModeState {
  mode: PerceptionMode | null;
  since: number | null;
  lastDmActivity: number | null;
  presets: Record<PerceptionMode, PerceptionPreset> | null;
  transitions: PerceptionTransition[];
  available: boolean;
  // AD-733c-5-4: per-agent perception modes from the backend
  // ``PerceptionEngagementRegistry`` (shipped AD-733c-5 Wave 176). Empty
  // map = legacy single-controller deployment OR registry unwired; UI
  // falls back to the single-mode badge in that case.
  perAgent: Record<string, PerceptionMode>;
  refresh: () => Promise<void>;
  setMode: (mode: PerceptionMode) => Promise<void>;
}

export const usePerceptionModeStore = create<PerceptionModeState>((set) => ({
  mode: null,
  since: null,
  lastDmActivity: null,
  presets: null,
  transitions: [],
  available: false,
  perAgent: {},
  refresh: async () => {
    try {
      const resp = await fetch('/api/perception/mode');
      if (resp.status === 503) {
        set({ available: false });
        return;
      }
      if (!resp.ok) return;
      const json = await resp.json();
      // AD-733c-5-4: parse per_agent map; defensively reject non-object
      // payloads so a backend regression cannot poison the UI.
      const rawPerAgent = json.per_agent;
      const perAgent: Record<string, PerceptionMode> = {};
      if (rawPerAgent && typeof rawPerAgent === 'object' && !Array.isArray(rawPerAgent)) {
        for (const [aid, mode] of Object.entries(rawPerAgent)) {
          if (mode === 'engaged' || mode === 'ambient' || mode === 'dormant') {
            perAgent[aid] = mode;
          }
        }
      }
      set({
        mode: json.mode as PerceptionMode,
        since: typeof json.since === 'number' ? json.since : null,
        lastDmActivity:
          typeof json.last_dm_activity === 'number' ? json.last_dm_activity : null,
        presets: json.presets ?? null,
        transitions: Array.isArray(json.transitions) ? json.transitions : [],
        available: true,
        perAgent,
      });
    } catch {
      // Tier-2: silent honest-degrade; the UI just shows the last known
      // state (or null if never fetched).
    }
  },
  setMode: async (mode: PerceptionMode) => {
    try {
      const resp = await fetch('/api/perception/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      });
      if (resp.ok) {
        const json = await resp.json();
        if (json.mode) {
          set({ mode: json.mode as PerceptionMode });
        }
      }
    } catch {
      // Tier-2: silent fail; operator can retry.
    }
  },
}));
