/**
 * AD-742c-6 — Camera multiplexer Zustand slice.
 *
 * Sibling of ``useCameraStore`` (NOT a merger — different endpoints,
 * different lifecycles; SRP wins). Owns the per-agent → device_id map
 * (persisted backend-side via ``ProfileStore``) AND the browser-side
 * enumeration of available ``MediaDeviceInfo`` entries.
 *
 * Endpoints (frozen — shipped Wave 176 by AD-742c):
 *   GET  /api/perception/cameras                     → {bindings}
 *   POST /api/perception/cameras/binding {agent_id, device_id}
 */
import { create } from 'zustand';

interface CameraMultiplexerState {
  /** Persisted per-agent → device_id bindings, mirrored from backend. */
  bindings: Record<string, string>;
  /** Browser-enumerated video devices. */
  devices: MediaDeviceInfo[];
  /** True once both ``refresh()`` halves resolved at least once. */
  loaded: boolean;
  /** Refresh both bindings (HTTP) and devices (browser enumeration). */
  refresh: () => Promise<void>;
  /** Persist a binding; on 200 mirror into local state. */
  bindAgent: (agentId: string, deviceId: string) => Promise<void>;
  /** Convenience: clear a binding (POST empty device_id). */
  clearAgent: (agentId: string) => Promise<void>;
}

export const useCameraMultiplexerStore = create<CameraMultiplexerState>((set, get) => ({
  bindings: {},
  devices: [],
  loaded: false,
  refresh: async () => {
    const [bindingsResult, devicesResult] = await Promise.allSettled([
      (async (): Promise<Record<string, string>> => {
        const resp = await fetch('/api/perception/cameras');
        if (!resp.ok) return {};
        const json = await resp.json();
        const raw = json?.bindings;
        if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
        const out: Record<string, string> = {};
        for (const [aid, dev] of Object.entries(raw)) {
          if (typeof dev === 'string') out[aid] = dev;
        }
        return out;
      })(),
      (async (): Promise<MediaDeviceInfo[]> => {
        const md = (globalThis as any).navigator?.mediaDevices;
        if (!md || typeof md.enumerateDevices !== 'function') return [];
        const all = await md.enumerateDevices();
        return all.filter((d: MediaDeviceInfo) => d.kind === 'videoinput');
      })(),
    ]);
    const bindings = bindingsResult.status === 'fulfilled' ? bindingsResult.value : {};
    const devices = devicesResult.status === 'fulfilled' ? devicesResult.value : [];
    set({ bindings, devices, loaded: true });
  },
  bindAgent: async (agentId, deviceId) => {
    try {
      const resp = await fetch('/api/perception/cameras/binding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, device_id: deviceId }),
      });
      if (!resp.ok) return;
      const json = await resp.json().catch(() => ({}));
      if (json?.ok) {
        set((state) => {
          const next = { ...state.bindings };
          if (deviceId) next[agentId] = deviceId;
          else delete next[agentId];
          return { bindings: next };
        });
      }
    } catch {
      // Tier-2: transient network failure — local state unchanged so
      // the operator's next dropdown change retries the round-trip.
    }
  },
  clearAgent: async (agentId) => {
    await get().bindAgent(agentId, '');
  },
}));
