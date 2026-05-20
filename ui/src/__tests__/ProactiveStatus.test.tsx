import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ProactiveStatus } from '../components/wardroom/ProactiveStatus';

describe('AD-752 ProactiveStatus', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('renders proactive status payload from API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          next_inbox_scan: '2026-05-20T14:00:00Z',
          next_calendar_scan: '2026-05-20T14:15:00Z',
          work_hours_active: true,
          quiet_hours_active: false,
          last_scan_count: { inbox: 3, calendar: 0, teams: 1 },
        }),
      }))
    );

    render(<ProactiveStatus />);

    await waitFor(() => {
      expect(screen.getByText(/Next inbox scan/i)).toBeInTheDocument();
      expect(screen.getByText(/Last scan findings: 4/i)).toBeInTheDocument();
      expect(screen.getByText(/Work-hours: active/i)).toBeInTheDocument();
    });
  });

  it('shows unavailable message when proactive endpoint fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));

    render(<ProactiveStatus />);

    await waitFor(() => {
      expect(screen.getByText('Unavailable')).toBeInTheDocument();
    });
  });
});
