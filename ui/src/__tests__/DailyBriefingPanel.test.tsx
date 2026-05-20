import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { DailyBriefingPanel } from '../components/wardroom/DailyBriefingPanel';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('DailyBriefingPanel', () => {
  it('renders briefing from API payload', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        inboxSummary: 'Overnight inbox: 12 new emails (3 flagged)',
        calendarSummary: 'Calendar: 5 meetings today, 2 free slots',
        suggestedActions: ['Review meeting notes', 'Approve PR'],
      }),
    })));

    render(<DailyBriefingPanel />);
    expect(await screen.findByText('Daily Briefing')).toBeInTheDocument();
    expect(await screen.findByText(/Overnight inbox:/)).toBeInTheDocument();
    expect(await screen.findByText(/Calendar:/)).toBeInTheDocument();
  });
});
