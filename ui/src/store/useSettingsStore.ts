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
  /** BF-999: Date.now() when snapshot.csrf_token was fetched; 0 when none was or a POST spent it. */
  csrfFetchedAt: number;
  /** BF-1000: true after a 200 that did not answer restart_required false; a page reload clears it. */
  restartPending: boolean;

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

// BF-999 (#1852): GET /api/config issues a single-use CSRF token that lives 300 s, and every
// POST /api/config spends it before reading the body (src/probos/routers/config.py). A save
// fetches a fresh token first when the last one was spent or is older than this margin.
const CSRF_REFRESH_AFTER_MS = 240000;

// BF-999: one save at a time; a press while a save is in flight sends nothing.
let applying = false;

async function _fetchSnapshot(): Promise<ConfigSnapshot | string> {
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) return `config GET failed: ${resp.status}`;
    return (await resp.json()) as ConfigSnapshot;
  } catch (err) {
    return `config GET error: ${String(err)}`;
  }
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
  csrfFetchedAt: 0,
  restartPending: false,

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
        csrfFetchedAt: Date.now(),
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
        csrfFetchedAt: Date.now(),
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
    if (applying || !get().snapshot) return;
    applying = true;
    try {
      // Reshape the flat dot-keyed draft into a nested patch dict.
      const patch: Record<string, any> = {};
      for (const [path, value] of Object.entries(get().draft)) {
        _setNestedPath(patch, path, value);
      }
      // BF-999: the router answers 403 before it reads the body, so a refused save had no
      // effect; fetch a new token and send the same patch once more. Any other answer ends it.
      for (let attempt = 0; attempt < 2; attempt++) {
        const fetchedAt = get().csrfFetchedAt;
        if (!fetchedAt || Date.now() - fetchedAt >= CSRF_REFRESH_AFTER_MS) {
          const fresh = await _fetchSnapshot();
          if (typeof fresh === 'string') {
            // The token was spent or aged: keep it marked for replacement so the next press reads first.
            set({
              csrfFetchedAt: 0,
              applyStatus: 'rejected',
              applyMessage: `Could not get a save token (${fresh}); nothing was saved. Press APPLY to try again.`,
            });
            return;
          }
          set({ snapshot: fresh, csrfFetchedAt: Date.now() });
        }
        const token = get().snapshot?.csrf_token ?? '';
        // Every POST the router answers spends the token, whatever the status.
        set({ csrfFetchedAt: 0 });
        const resp = await fetch('/api/config', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Probos-CSRF': token,
          },
          body: JSON.stringify({ patch }),
        });
        const body = await resp.json().catch(() => ({} as any));
        if (resp.status === 403 && attempt === 0) continue;
        if (resp.status === 200 && body?.restart_required === false) {
          // The router wrote the change into the running config, so show the live values.
          const fresh = await _fetchSnapshot();
          // Keep the banner when an earlier 200 on this page took the restart branch.
          const pending = get().restartPending;
          const status: SettingsState['applyStatus'] = pending ? 'restart_required' : 'success';
          const applied = pending
            ? 'Saved and applied. An earlier save asked for a restart.'
            : 'Saved and applied. This change needs no restart.';
          if (typeof fresh === 'string') {
            set({
              applyStatus: status,
              applyMessage: `${applied} Could not reload the values (${fresh}).`,
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          } else {
            set({
              snapshot: fresh,
              csrfFetchedAt: Date.now(),
              applyStatus: status,
              applyMessage: applied,
              applyErrors: [],
              draft: {},
              draftCount: 0,
            });
          }
        } else if (resp.status === 200) {
          set({
            restartPending: true,
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
            applyMessage: 'Save token refused twice; nothing was saved. Press APPLY to try again.',
          });
        } else {
          set({
            applyStatus: 'rejected',
            applyMessage: `APPLY failed (${resp.status}): ${body.error ?? 'unknown'}`,
          });
        }
        return;
      }
    } catch (err) {
      set({ applyStatus: 'rejected', applyMessage: `APPLY error: ${String(err)}` });
    } finally {
      applying = false;
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
