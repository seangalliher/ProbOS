/**
 * AD-746 Layer 2 — Per-agent source-binding Zustand slice.
 *
 * Sibling of ``useCameraMultiplexerStore`` (NOT a merger — different
 * endpoints, different lifecycle; SRP wins per AD-742c-6 precedent).
 * Owns the per-agent → ``list[str]`` source binding map (persisted
 * backend-side via ``ProfileStore.perception.bound_sources``).
 *
 * Endpoints:
 *   GET  /api/perception/sources                      → {bindings}
 *   POST /api/perception/sources/binding {agent_id, sources}
 */
import { create } from 'zustand';

export const ALL_SOURCES = ['camera', 'screen'] as const;
export type SourceName = (typeof ALL_SOURCES)[number];

interface SourceBindingsState {
  /** Persisted per-agent → list[source] bindings mirrored from backend.
   *  Absent key means "default: see all sources" (server-side default). */
  bindings: Record<string, string[]>;
  loaded: boolean;
  refresh: () => Promise<void>;
  /** Toggle a single source for an agent; POST updated list. */
  toggleSource: (agentId: string, source: SourceName) => Promise<void>;
  /** Set the binding to an explicit list of sources. */
  setSources: (agentId: string, sources: string[]) => Promise<void>;
}

export const useSourceBindingsStore = create<SourceBindingsState>((set, get) => ({
  bindings: {},
  loaded: false,
  refresh: async () => {
    try {
      const resp = await fetch('/api/perception/sources');
      if (!resp.ok) {
        set({ loaded: true });
        return;
      }
      const json = await resp.json();
      const raw = json?.bindings;
      if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        set({ bindings: {}, loaded: true });
        return;
      }
      const out: Record<string, string[]> = {};
      for (const [aid, srcs] of Object.entries(raw)) {
        if (Array.isArray(srcs)) {
          out[aid] = srcs.filter((s): s is string => typeof s === 'string');
        }
      }
      set({ bindings: out, loaded: true });
    } catch {
      // Tier-2 — transient failure leaves state untouched.
      set({ loaded: true });
    }
  },
  setSources: async (agentId, sources) => {
    try {
      const resp = await fetch('/api/perception/sources/binding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, sources }),
      });
      if (!resp.ok) return;
      const json = await resp.json().catch(() => ({}));
      if (json?.ok && Array.isArray(json.sources)) {
        set((state) => ({
          bindings: { ...state.bindings, [agentId]: json.sources as string[] },
        }));
      }
    } catch {
      // Tier-2 — local state unchanged; operator retry will repost.
    }
  },
  toggleSource: async (agentId, source) => {
    const current = get().bindings[agentId] ?? [...ALL_SOURCES];
    const next = current.includes(source)
      ? current.filter((s) => s !== source)
      : [...current, source];
    await get().setSources(agentId, next);
  },
}));
