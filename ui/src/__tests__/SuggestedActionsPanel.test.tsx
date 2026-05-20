import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { SuggestedActionsPanel } from '../components/wardroom/SuggestedActionsPanel';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SuggestedActionsPanel', () => {
  it('renders suggested actions from API', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: '1',
          label: 'Review meeting notes',
          emoji: 'review',
          agent: 'ArchitectAgent',
          score: 0.91,
          metadata: { intent: 'review_notes', context: 'meeting' },
        },
      ],
    })));

    render(<SuggestedActionsPanel />);
    expect(await screen.findByText('Suggested Actions')).toBeInTheDocument();
    expect(await screen.findByText('Review meeting notes')).toBeInTheDocument();
  });
});
