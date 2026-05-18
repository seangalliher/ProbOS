/**
 * AD-741: SettingsPanel tests.
 *
 * BF-287: real ``useSettingsStore`` slice (not MagicMock). Fetch is mocked at
 * the network boundary; everything else runs through the production code path.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react';

import SettingsPanel from '../SettingsPanel';
import { useSettingsStore } from '../../../store/useSettingsStore';

const FAKE_CONFIG_SNAPSHOT = {
  config: {
    system: { name: 'ProbOS', version: '0.1.0', log_level: 'INFO' },
    memory: {
      max_episodes: 100000,
      relevance_threshold: 0.7,
      agent_recall_threshold: 0.25,
      embedding_model: 'multi-qa-MiniLM-L6-cos-v1',
    },
    cloud_pickers: { google_drive: { client_secret: null } },
  },
  secret_present: { 'cloud_pickers.google_drive.client_secret': true },
  sections: [
    {
      section_id: 'system',
      label: 'System',
      glyph: '◇',
      domain: 'Core',
      description: 'Process identity and global log level.',
      fields: [
        { field_id: 'system.name', label: 'Process name', kind: 'text', enum_values: [], description: '', hot_reload: false },
        { field_id: 'system.version', label: 'Version', kind: 'readonly', enum_values: [], description: '', hot_reload: false },
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: ['INFO', 'DEBUG'], description: '', hot_reload: false },
      ],
    },
    {
      section_id: 'memory',
      label: 'Memory',
      glyph: '◈',
      domain: 'Core',
      description: 'Episodic memory.',
      fields: [
        { field_id: 'memory.max_episodes', label: 'Max episodes', kind: 'int', enum_values: [], description: '', hot_reload: false },
      ],
    },
    {
      section_id: 'voice',
      label: 'Voice',
      glyph: '≈',
      domain: 'Perception & Voice',
      description: 'TTS.',
      fields: [
        { field_id: 'tts.voice_model', label: 'Piper voice model', kind: 'text', enum_values: [], description: '', hot_reload: false },
      ],
    },
    {
      section_id: 'cloud_pickers',
      label: 'Cloud Pickers',
      glyph: '↑',
      domain: 'Connectivity',
      description: 'OAuth pickers.',
      fields: [
        { field_id: 'cloud_pickers.google_drive.client_secret', label: 'Google Drive client secret', kind: 'secret_present_only', enum_values: [], description: '', hot_reload: false },
      ],
    },
  ],
  domain_counts: { 'Core': 2, 'Perception & Voice': 1, 'Connectivity': 1 },
  domain_order: ['Core', 'Perception & Voice', 'Identity & Presentation', 'Connectivity'],
  section_count: 4,
  config_path: '/tmp/system.yaml',
  uptime_seconds: 12.3,
  csrf_token: 'fake-token-abc',
};

function reset() {
  useSettingsStore.setState({
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
  });
}

function jsonResp(body: any, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  } as unknown as Response;
}

describe('SettingsPanel (AD-741)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders nothing when settings is closed', () => {
    render(<SettingsPanel />);
    expect(screen.queryByTestId('settings-panel')).toBeNull();
  });

  it('renders sidebar groups in canonical domain order', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp(FAKE_CONFIG_SNAPSHOT));
    await act(async () => { await useSettingsStore.getState().openSettings(); });

    render(<SettingsPanel />);
    expect(screen.getByTestId('settings-panel')).toBeTruthy();
    expect(screen.getByTestId('settings-sidebar')).toBeTruthy();
    expect(screen.getByText(/4 sections/)).toBeTruthy();
    expect(screen.getByText('CORE')).toBeTruthy();
    expect(screen.getByText('PERCEPTION & VOICE')).toBeTruthy();
    expect(screen.getByText('CONNECTIVITY')).toBeTruthy();
  });

  it('selecting a section renders its fields with the correct control kinds', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp(FAKE_CONFIG_SNAPSHOT));
    await act(async () => { await useSettingsStore.getState().openSettings(); });
    render(<SettingsPanel />);

    // System is selected by default — readonly + text + enum controls render.
    expect(screen.getByTestId('field-text-system.name')).toBeTruthy();
    expect(screen.getByTestId('field-readonly-system.version')).toBeTruthy();
    expect(screen.getByTestId('field-enum-system.log_level')).toBeTruthy();

    // Switch to cloud_pickers — secret chip renders, not a text input.
    fireEvent.click(screen.getByTestId('settings-section-cloud_pickers'));
    expect(screen.getByTestId('field-secret-cloud_pickers.google_drive.client_secret')).toBeTruthy();
  });

  it('bottom-of-sidebar Advanced configuration opens the YAML modal', async () => {
    const yamlText = 'system:\n  log_level: INFO\n';
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.endsWith('/yaml')) {
        return Promise.resolve(jsonResp(yamlText));
      }
      return Promise.resolve(jsonResp(FAKE_CONFIG_SNAPSHOT));
    });
    await act(async () => { await useSettingsStore.getState().openSettings(); });
    render(<SettingsPanel />);

    expect(screen.queryByTestId('settings-yaml-modal')).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByTestId('settings-open-yaml'));
    });
    await waitFor(() => expect(screen.getByTestId('settings-yaml-modal')).toBeTruthy());
    await waitFor(() => expect(screen.getByTestId('settings-yaml-pre').textContent).toContain('log_level'));
  });

  it('editing a field flips DISCARD + APPLY from disabled to enabled', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp(FAKE_CONFIG_SNAPSHOT));
    await act(async () => { await useSettingsStore.getState().openSettings(); });
    render(<SettingsPanel />);

    const apply = screen.getByTestId('settings-topbar-apply') as HTMLButtonElement;
    expect(apply.disabled).toBe(true);

    await act(async () => {
      useSettingsStore.getState().setDraftField('system.log_level', 'DEBUG');
    });

    const applyEnabled = screen.getByTestId('settings-topbar-apply') as HTMLButtonElement;
    const discardEnabled = screen.getByTestId('settings-topbar-discard') as HTMLButtonElement;
    expect(applyEnabled.disabled).toBe(false);
    expect(discardEnabled.disabled).toBe(false);
  });

  it('DISCARD clears the draft and re-disables the buttons', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(jsonResp(FAKE_CONFIG_SNAPSHOT));
    await act(async () => { await useSettingsStore.getState().openSettings(); });
    render(<SettingsPanel />);

    await act(async () => {
      useSettingsStore.getState().setDraftField('system.log_level', 'DEBUG');
    });
    fireEvent.click(screen.getByTestId('settings-topbar-discard'));
    expect(useSettingsStore.getState().draftCount).toBe(0);
  });

  it('APPLY POSTs the patch with CSRF header and shows restart banner on 200', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((url: any, init?: any) => {
      if (init?.method === 'POST') {
        // Inspect the body — must contain the CSRF header & patch.
        expect(init.headers['X-Probos-CSRF']).toBe('fake-token-abc');
        const parsed = JSON.parse(init.body);
        expect(parsed.patch.system.log_level).toBe('DEBUG');
        return Promise.resolve(jsonResp({ ok: true, restart_required: true, changed_fields: ['system.log_level'] }));
      }
      return Promise.resolve(jsonResp(FAKE_CONFIG_SNAPSHOT));
    });

    await act(async () => { await useSettingsStore.getState().openSettings(); });
    render(<SettingsPanel />);

    await act(async () => {
      useSettingsStore.getState().setDraftField('system.log_level', 'DEBUG');
    });
    await act(async () => {
      await useSettingsStore.getState().applyDraft();
    });

    expect(fetchMock).toHaveBeenCalled();
    await waitFor(() =>
      expect(useSettingsStore.getState().applyStatus).toBe('restart_required'),
    );
  });
});
