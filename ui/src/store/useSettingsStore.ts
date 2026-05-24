/* AD-741 — Settings panel store (separate slice to keep useStore.ts unchanged). */

import { create } from 'zustand';

export interface FieldDescriptorDTO {
  field_id: string;
  label: string;
  kind: 'text' | 'readonly' | 'enum' | 'bool' | 'int' | 'float' | 'secret_present_only';
  enum_values: string[];
  description: string;
  hot_reload: boolean;
}

export interface SectionDescriptorDTO {
  section_id: string;
  label: string;
  glyph: string;
  domain: string;
  description: string;
  fields: FieldDescriptorDTO[];
}

export interface ConfigSnapshot {
  config: Record<string, any>;
  secret_present: Record<string, boolean>;
  sections: SectionDescriptorDTO[];
  domain_counts: Record<string, number>;
  domain_order: string[];
  section_count: number;
  config_path: string;
  uptime_seconds: number;
  csrf_token: string;
}

export interface ApplyError {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface SettingsState {
  open: boolean;
  loading: boolean;
  loaded: boolean;
  snapshot: ConfigSnapshot | null;
  draft: Record<string, any>;
  draftCount: number;
  selectedSectionId: string;
  search: string;
  yamlOpen: boolean;
  yamlText: string;
  yamlLoading: boolean;
  applyStatus: 'idle' | 'success' | 'restart_required' | 'rejected';
  applyErrors: ApplyError[];
  applyMessage: string;
  openedAt: number;

  loadSnapshot: () => Promise<void>;
  openSettings: () => Promise<void>;
  closeSettings: () => void;
  setDraftField: (fieldId: string, value: any) => void;
  discardDraft: () => void;
  applyDraft: () => Promise<void>;
  selectSection: (id: string) => void;
  setSearch: (q: string) => void;
  openYaml: () => Promise<void>;
  closeYaml: () => void;
}

function _setNestedPath(target: Record<string, any>, path: string, value: any): void {
  const parts = path.split('.');
  let cursor: Record<string, any> = target;
  for (let i = 0; i < parts.length - 1; i++) {
    const key = parts[i];
    if (typeof cursor[key] !== 'object' || cursor[key] === null) {
      cursor[key] = {};
    }
    cursor = cursor[key];
  }
  cursor[parts[parts.length - 1]] = value;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  open: false,
  loading: false,
  loaded: false,
  snapshot: null,
  draft: {},
  draftCount: 0,
  selectedSectionId: 'system',
  search: '',
  yamlOpen: false,
  yamlText: '',
  yamlLoading: false,
  applyStatus: 'idle',
  applyErrors: [],
  applyMessage: '',
  openedAt: 0,

  /**
   * BF-304: fetch /api/config without opening the Settings dialog.
   *
   * Called from App.tsx / CompactApp.tsx on mount so subsystems that
   * read ``s.snapshot?.config?...`` (notably the Silero VAD loop in
   * App.tsx, which gates on ``perception.vad_engagement_enabled``)
   * activate immediately rather than waiting for the operator to
   * open Settings. Idempotent — skips the fetch when ``loaded`` is
   * already true.
   */
  loadSnapshot: async () => {
    if (get().loaded || get().loading) return;
    set({ loading: true });
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) {
        set({ loading: false, applyMessage: `config GET failed: ${resp.status}` });
        return;
      }
      const snapshot: ConfigSnapshot = await resp.json();
      set({
        snapshot,
        loading: false,
        loaded: true,
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        applyStatus: 'idle',
        applyErrors: [],
        applyMessage: '',
      });
    } catch (err) {
      set({ loading: false, applyMessage: `config GET error: ${String(err)}` });
    }
  },

  openSettings: async () => {
    // BF-304: reuse loadSnapshot so opening the dialog after an
    // already-mounted load is a near-instant no-op instead of a
    // second round-trip.
    set({ open: true, openedAt: Date.now() });
    if (get().loaded) {
      // Reset transient draft state but keep the loaded snapshot.
      set({ draft: {}, draftCount: 0 });
      return;
    }
    set({ loading: true });
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) {
        set({ loading: false, applyMessage: `config GET failed: ${resp.status}` });
        return;
      }
      const snapshot: ConfigSnapshot = await resp.json();
      set({
        snapshot,
        loading: false,
        loaded: true,
        selectedSectionId: snapshot.sections[0]?.section_id ?? 'system',
        draft: {},
        draftCount: 0,
        applyStatus: 'idle',
        applyErrors: [],
        applyMessage: '',
      });
    } catch (err) {
      set({ loading: false, applyMessage: `config GET error: ${String(err)}` });
    }
  },

  closeSettings: () => set({ open: false }),

  setDraftField: (fieldId, value) => {
    const next = { ...get().draft, [fieldId]: value };
    set({ draft: next, draftCount: Object.keys(next).length });
  },

  discardDraft: () =>
    set({ draft: {}, draftCount: 0, applyStatus: 'idle', applyErrors: [], applyMessage: '' }),

  applyDraft: async () => {
    const { draft, snapshot } = get();
    if (!snapshot) return;
    // Reshape the flat dot-keyed draft into a nested patch dict.
    const patch: Record<string, any> = {};
    for (const [path, value] of Object.entries(draft)) {
      _setNestedPath(patch, path, value);
    }
    try {
      const resp = await fetch('/api/config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Probos-CSRF': snapshot.csrf_token,
        },
        body: JSON.stringify({ patch }),
      });
      const body = await resp.json().catch(() => ({} as any));
      if (resp.status === 200) {
        // Refresh snapshot to get a fresh CSRF token; THEN set the
        // restart-required status so it survives the re-open call.
        await get().openSettings();
        set({
          applyStatus: 'restart_required',
          applyMessage: 'Restart required to take effect.',
          applyErrors: [],
          draft: {},
          draftCount: 0,
        });
      } else if (resp.status === 422) {
        set({
          applyStatus: 'rejected',
          applyErrors: body.errors ?? [],
          applyMessage: 'Validation failed — see field errors below.',
        });
      } else if (resp.status === 400 && body.error === 'secret_field_readonly') {
        set({
          applyStatus: 'rejected',
          applyMessage: 'Secret fields are read-only here — edit system.yaml directly.',
        });
      } else if (resp.status === 403) {
        set({
          applyStatus: 'rejected',
          applyMessage: 'CSRF token expired — re-opening Settings.',
        });
        await get().openSettings();
      } else {
        set({
          applyStatus: 'rejected',
          applyMessage: `APPLY failed (${resp.status}): ${body.error ?? 'unknown'}`,
        });
      }
    } catch (err) {
      set({ applyStatus: 'rejected', applyMessage: `APPLY error: ${String(err)}` });
    }
  },

  selectSection: (id) => set({ selectedSectionId: id }),
  setSearch: (q) => set({ search: q }),

  openYaml: async () => {
    set({ yamlOpen: true, yamlLoading: true });
    try {
      const resp = await fetch('/api/config/yaml');
      const text = resp.ok ? await resp.text() : `# Failed to load YAML (${resp.status})`;
      set({ yamlText: text, yamlLoading: false });
    } catch (err) {
      set({ yamlText: `# Error: ${String(err)}`, yamlLoading: false });
    }
  },

  closeYaml: () => set({ yamlOpen: false }),
}));
