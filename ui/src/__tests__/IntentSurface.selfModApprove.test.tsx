/** AD-1194 A-2: the Build Agent click names the build request its proposal filed. */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import type { SelfModProposal } from '../store/types';

const PROPOSAL: SelfModProposal = {
  intent_name: 'wipe_disk',
  intent_description: 'wipe a disk',
  parameters: { device: 'which disk' },
  original_message: 'please wipe the spare disk',
  status: 'proposed',
};

beforeEach(() => {
  useStore.setState({ chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map() });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

async function clickBuildAgent(proposal: SelfModProposal): Promise<Record<string, unknown> | null> {
  let body: Record<string, unknown> | null = null;
  global.fetch = vi.fn().mockImplementation((url: unknown, init?: { body?: string }) => {
    if (String(url) === '/api/selfmod/approve') {
      body = JSON.parse(init?.body ?? 'null');
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
  render(<IntentSurface />);
  openShell();
  act(() => {
    useStore.getState().addChatMessage('system', 'I can build one.', { selfModProposal: proposal });
  });
  fireEvent.click(await screen.findByText('Build Agent'));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return body;
}

describe('AD-1194 A-2 Build Agent click', () => {
  it('names the build request its proposal filed', async () => {
    const body = await clickBuildAgent({ ...PROPOSAL, capability_request_id: 'req-123' });

    expect(body).toEqual({
      intent_name: 'wipe_disk',
      intent_description: 'wipe a disk',
      parameters: { device: 'which disk' },
      original_message: 'please wipe the spare disk',
      capability_request_id: 'req-123',
    });
  });

  it('sends the body as before when the proposal filed no request', async () => {
    const body = await clickBuildAgent(PROPOSAL);

    expect(body).not.toBeNull();
    expect(Object.keys(body ?? {})).toEqual([
      'intent_name', 'intent_description', 'parameters', 'original_message',
    ]);
  });
});
