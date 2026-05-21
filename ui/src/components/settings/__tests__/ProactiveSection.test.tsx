/**
 * AD-762: SettingsMain renders ProactiveStatusSection in the proactive branch.
 *
 * Mirrors the BF-298 PerceptionParentChild.test.tsx scaffolding pattern —
 * drives the real ``useSettingsStore`` slice directly and asserts the
 * custom-panel branch wiring (no field rows; the section payload is
 * fetched from /api/proactive/status by the component).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

import SettingsMain from '../SettingsMain';
import { useSettingsStore } from '../../../store/useSettingsStore';

const PROACTIVE_SECTION = {
  section_id: 'proactive',
  label: 'Proactive',
  glyph: '◐',
  domain: 'Core',
  description: 'Next inbox/calendar scan, work-hours, quiet-hours, and the global enable toggle.',
  fields: [] as any[],
};

function makeSnapshot() {
  return {
    config: {},
    secret_present: {},
    sections: [PROACTIVE_SECTION],
    domain_counts: { Core: 1 },
    domain_order: ['Core'],
    section_count: 1,
    config_path: '/tmp/system.yaml',
    uptime_seconds: 1,
    csrf_token: 'tk',
  };
}

function resetStore(): void {
  useSettingsStore.setState({
    open: true,
    loading: false,
    loaded: true,
    snapshot: makeSnapshot(),
    draft: {},
    draftCount: 0,
    selectedSectionId: 'proactive',
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('AD-762 SettingsMain proactive branch', () => {
  beforeEach(() => {
    resetStore();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          next_inbox_scan: '2026-05-20T14:00:00Z',
          next_calendar_scan: '2026-05-20T14:15:00Z',
          work_hours_active: false,
          quiet_hours_active: false,
          last_scan_count: { inbox: 2 },
        }),
      })),
    );
  });

  it('renders ProactiveStatusSection when section_id === "proactive"', async () => {
    render(<SettingsMain />);
    await waitFor(() => {
      expect(screen.getByText('PROACTIVE STATUS')).toBeInTheDocument();
    });
    expect(screen.getByText(/Next inbox scan/i)).toBeInTheDocument();
    expect(screen.getByText(/Disable proactive/i)).toBeInTheDocument();
  });
});
