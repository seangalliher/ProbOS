/**
 * AD-763: ConnectorsSection renders folder/calendar lists from the mocked
 * Graph discovery endpoints, multiselect toggles update local state, and
 * Save PUTs /api/connectors/scan-config.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react';

import ConnectorsSection from '../components/settings/sections/ConnectorsSection';

const SCAN_CONFIG = {
  inbox: {
    folders: ['Inbox'],
    lookback_hours: 24,
    importance_filter: 'any' as const,
    unread_only: false,
    sender_allowlist: [],
    sender_denylist: [],
  },
  calendar: {
    calendar_ids: ['primary'],
    lookahead_hours: 24,
    include_declined: false,
  },
};

const FOLDERS = {
  folders: [
    { id: 'Inbox', displayName: 'Inbox', parentFolderId: null, totalItemCount: 5 },
    { id: 'Important', displayName: 'Important', parentFolderId: 'Inbox', totalItemCount: 2 },
  ],
};

const CALENDARS = {
  calendars: [
    { id: 'primary', name: 'Primary', isDefaultCalendar: true, canEdit: true },
    { id: 'team', name: 'Team', isDefaultCalendar: false, canEdit: false },
  ],
};

function installFetchMock(putCapture?: { calls: { url: string; init?: RequestInit }[] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        putCapture?.calls.push({ url, init });
        const body = JSON.parse(String(init.body));
        return { ok: true, status: 200, json: async () => body } as any;
      }
      if (url === '/api/connectors/scan-config') {
        return { ok: true, status: 200, json: async () => SCAN_CONFIG } as any;
      }
      if (url === '/api/connectors/m365/mail-folders') {
        return { ok: true, status: 200, json: async () => FOLDERS } as any;
      }
      if (url === '/api/connectors/m365/calendars') {
        return { ok: true, status: 200, json: async () => CALENDARS } as any;
      }
      return { ok: false, status: 404, json: async () => ({}) } as any;
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-763 ConnectorsSection', () => {
  beforeEach(() => {
    installFetchMock();
  });

  it('renders mail folders from the discovery endpoint', async () => {
    render(<ConnectorsSection />);
    // Expand the M365 subsection
    fireEvent.click(screen.getByText('MICROSOFT 365'));
    await waitFor(() => {
      expect(screen.getByTestId('folder-Inbox')).toBeInTheDocument();
      expect(screen.getByTestId('folder-Important')).toBeInTheDocument();
    });
  });

  it('renders calendars from the discovery endpoint', async () => {
    render(<ConnectorsSection />);
    fireEvent.click(screen.getByText('MICROSOFT 365'));
    await waitFor(() => {
      expect(screen.getByTestId('calendar-primary')).toBeInTheDocument();
      expect(screen.getByTestId('calendar-team')).toBeInTheDocument();
    });
  });

  it('toggles folder selection in local state', async () => {
    render(<ConnectorsSection />);
    fireEvent.click(screen.getByText('MICROSOFT 365'));
    await waitFor(() => screen.getByTestId('folder-Important'));
    const important = screen.getByTestId('folder-Important') as HTMLInputElement;
    expect(important.checked).toBe(false);
    fireEvent.click(important);
    expect((screen.getByTestId('folder-Important') as HTMLInputElement).checked).toBe(true);
  });

  it('Save PUTs the scan-config endpoint with current state', async () => {
    const capture = { calls: [] as { url: string; init?: RequestInit }[] };
    installFetchMock(capture);
    render(<ConnectorsSection />);
    fireEvent.click(screen.getByText('MICROSOFT 365'));
    await waitFor(() => screen.getByTestId('connectors-save'));
    fireEvent.click(screen.getByTestId('connectors-save'));
    await waitFor(() => {
      expect(capture.calls.length).toBe(1);
    });
    expect(capture.calls[0].url).toBe('/api/connectors/scan-config');
    expect(capture.calls[0].init?.method).toBe('PUT');
    const body = JSON.parse(String(capture.calls[0].init?.body));
    expect(body.inbox.folders).toEqual(['Inbox']);
    expect(body.calendar.calendar_ids).toEqual(['primary']);
  });

  it('honest-degrades when /m365/mail-folders returns 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/connectors/scan-config') {
          return { ok: true, status: 200, json: async () => SCAN_CONFIG } as any;
        }
        if (url === '/api/connectors/m365/mail-folders') {
          return { ok: false, status: 401, json: async () => ({}) } as any;
        }
        return { ok: false, status: 404, json: async () => ({}) } as any;
      }),
    );
    render(<ConnectorsSection />);
    fireEvent.click(screen.getByText('MICROSOFT 365'));
    await waitFor(() => {
      expect(screen.getByText(/Sign in to Microsoft 365/i)).toBeInTheDocument();
    });
  });
});
