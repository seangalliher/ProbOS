/** BF-812: IntentSurface must show an AD-698 policy refusal as policy state.
 *
 *  The chat POST chain was `.then((res) => res.json())` with no `res.ok`
 *  check, so a 403 refusal body fell through every branch to the final
 *  `'(No response)'` fallback. That tells the Captain the agent had nothing to
 *  say — a refusal wearing an outage costume.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act, fireEvent, waitFor } from '@testing-library/react';

import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

let chatBody: unknown = { response: 'ok' };
let chatStatus = 200;

function installFetch(): void {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/chat') {
      return Promise.resolve({
        ok: chatStatus >= 200 && chatStatus < 300,
        status: chatStatus,
        json: () => Promise.resolve(chatBody),
      } as Response);
    }
    return Promise.resolve({
      ok: true, status: 200, json: () => Promise.resolve({}),
    } as Response);
  }));
}

function openShell(): void {
  // The shell starts collapsed as a pill; clicking it mounts the input.
  const pillText = screen.queryByText(/Ask ProbOS/);
  const clickable = pillText?.closest('div');
  if (clickable) fireEvent.click(clickable);
}

async function ask(text = 'do the thing'): Promise<void> {
  openShell();
  // IntentSurface renders outside the RTL container, so query the document —
  // the same approach IntentSurface.atMention.test.tsx uses.
  const input = document.querySelector(
    'input[placeholder="Ask ProbOS..."]',
  ) as HTMLInputElement | null;
  if (input === null) throw new Error('chat input not rendered');
  fireEvent.change(input, { target: { value: text } });
  await act(async () => {
    fireEvent.submit(input.closest('form')!);
    await Promise.resolve();
  });
}

function chatTexts(): Array<{ role: string; text: string }> {
  return useStore.getState().chatHistory.map((m) => ({ role: m.role, text: m.text }));
}

beforeEach(() => {
  chatBody = { response: 'ok' };
  chatStatus = 200;
  installFetch();
  useStore.setState({ chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map() });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('BF-812 IntentSurface renders a policy refusal as policy state', () => {
  it('names the refusal instead of falling through to "(No response)"', async () => {
    chatStatus = 403;
    chatBody = { error: 'intent_denied', reason: 'rbac' };
    render(<IntentSurface />);

    await ask();

    await waitFor(() => {
      expect(chatTexts().some((m) => m.text.includes('rbac'))).toBe(true);
    });
    const denial = chatTexts().find((m) => m.text.includes('rbac'));
    expect(denial?.role).toBe('system');
    expect(chatTexts().some((m) => m.text.includes('(No response)'))).toBe(false);
  });

  it('leaves an ordinary reply untouched', async () => {
    chatBody = { response: 'acknowledged' };
    render(<IntentSurface />);

    await ask();

    await waitFor(() => {
      expect(chatTexts().some((m) => m.text === 'acknowledged')).toBe(true);
    });
    expect(chatTexts().some((m) => m.text.toLowerCase().includes('policy refused')))
      .toBe(false);
  });
});
