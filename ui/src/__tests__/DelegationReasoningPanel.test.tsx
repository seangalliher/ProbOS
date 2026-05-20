import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { DelegationReasoningPanel } from '../components/wardroom/DelegationReasoningPanel';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('DelegationReasoningPanel', () => {
  it('renders delegation handoff reasoning', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          from: 'Yeo',
          to: 'ArchitectAgent',
          reason: 'You asked for architecture review; ArchitectAgent is best equipped',
          status: 'Reading codebase...',
        },
      ],
    })));

    render(<DelegationReasoningPanel dagId="test-dag" />);
    expect(await screen.findByText('Delegation Reasoning')).toBeInTheDocument();
    expect(await screen.findByText(/Yeo/)).toBeInTheDocument();
    expect(await screen.findByText(/Reason:/)).toBeInTheDocument();
  });
});
