// BF-813 (#1277): a per-agent reply carrying a `status` is a server-composed
// notice, not something the agent said.
//
// Recording it with role='agent' closed a confabulation loop that reached the
// model: IntentSurface appends every reply to `chatHistory`, the store persists
// that to localStorage, and the next submit sends the last 10 entries back as
// `history` -- so the model saw an agent announcing its own policy refusal as
// its own prior turn. The backend half (keeping it out of the transcript and
// episodic sinks) does not close this path, because the UI's history is a
// separate producer.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import { speakResponse } from '../audio/voice';

vi.mock('../audio/voice', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../audio/voice')>();
  return { ...actual, speakResponse: vi.fn() };
});

function makeAgent(id: string, callsign: string) {
  return {
    id,
    agentType: callsign.toLowerCase(),
    callsign,
    displayName: `${callsign} role`,
    pool: callsign.toLowerCase(),
    state: 'active' as const,
    confidence: 0.8,
    trust: 0.7,
    tier: 'domain' as const,
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: 'science',
  };
}

function mockFanout(replies: unknown[]) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      response: '',
      mentions: ['counselor', 'worf'],
      per_agent_replies: replies,
    }),
  });
}

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map([
      ['a1', makeAgent('a1', 'counselor')],
      ['a2', makeAgent('a2', 'worf')],
    ]),
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  return input;
}

async function submitFanout() {
  render(<IntentSurface />);
  openShell();
  const input = getInput();
  const form = input.closest('form') as HTMLFormElement;
  fireEvent.change(input, { target: { value: '@counselor @worf hello team' } });
  await act(async () => {
    fireEvent.submit(form);
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('IntentSurface BF-813 — a refusal is not an agent utterance', () => {
  it('records a status-carrying reply as system, not agent', async () => {
    mockFanout([
      { agent_id: 'a1', callsign: 'counselor', text: '(refused -- not permitted)', status: 'refused' },
      { agent_id: 'a2', callsign: 'worf', text: 'Acknowledged.', status: '' },
    ]);

    await submitFanout();

    const history = useStore.getState().chatHistory;
    const agentMsgs = history.filter((m) => m.role === 'agent');
    expect(agentMsgs.length).toBe(1);
    expect(agentMsgs[0].text).toBe('Acknowledged.');
    // Not hidden -- the Captain must still see that the recipient did not
    // answer, AND which one. System messages render without attribution and
    // the history projection carries only role and text, so the callsign has
    // to be in the text itself.
    const systemMsgs = history.filter((m) => m.role === 'system');
    expect(systemMsgs.some((m) => m.text.includes('refused'))).toBe(true);
    expect(systemMsgs.some((m) => m.text.includes('@counselor'))).toBe(true);
  });

  it('does not send a refusal back as conversation history on the next turn', async () => {
    mockFanout([
      { agent_id: 'a1', callsign: 'counselor', text: '(refused -- not permitted)', status: 'refused' },
    ]);

    await submitFanout();

    // Second turn: the loop closes here, where `history` is composed.
    const input = getInput();
    const form = input.closest('form') as HTMLFormElement;
    fireEvent.change(input, { target: { value: 'and again' } });
    await act(async () => {
      fireEvent.submit(form);
      await Promise.resolve();
    });

    const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBeGreaterThanOrEqual(2);
    const body = JSON.parse(String((calls[calls.length - 1][1] as RequestInit).body));
    const roles: string[] = (body.history ?? []).map((h: { role: string }) => h.role);
    // Premise: history really was sent, otherwise this asserts nothing.
    expect(roles.length).toBeGreaterThan(0);
    const agentTurns = (body.history ?? []).filter((h: { role: string }) => h.role === 'agent');
    expect(agentTurns.some((h: { text: string }) => h.text.includes('refused'))).toBe(false);
  });

  it('still records an ordinary reply as an agent turn', async () => {
    // Control. Without this, marking EVERYTHING system would pass the tests above.
    mockFanout([
      { agent_id: 'a1', callsign: 'counselor', text: 'I hear you.' },
      { agent_id: 'a2', callsign: 'worf', text: 'Acknowledged.' },
    ]);

    await submitFanout();

    const agentMsgs = useStore.getState().chatHistory.filter((m) => m.role === 'agent');
    expect(agentMsgs.length).toBe(2);
    expect(agentMsgs.map((m) => m.callsign)).toEqual(['counselor', 'worf']);
  });

  it('speaks the first genuine reply when a refusal comes first', async () => {
    // Gating TTS on replies[0] made the fix for one silence create another:
    // a refusal in slot 0 muted a real answer in slot 1.
    useStore.setState({ voiceEnabled: true });
    mockFanout([
      { agent_id: 'a1', callsign: 'counselor', text: '(refused -- not permitted)', status: 'refused' },
      { agent_id: 'a2', callsign: 'worf', text: 'Acknowledged.', status: '' },
    ]);

    await submitFanout();

    const spoken = vi.mocked(speakResponse);
    expect(spoken).toHaveBeenCalledTimes(1);
    expect(spoken.mock.calls[0][0]).toContain('Acknowledged.');
    expect(spoken.mock.calls[0][2]).toBe('a2');
  });

  it('speaks nothing when every reply is a notice', async () => {
    // Control for the test above: the finder must not fall back to a
    // status-bearing entry just because no genuine reply exists.
    useStore.setState({ voiceEnabled: true });
    mockFanout([
      { agent_id: 'a1', callsign: 'counselor', text: '(refused -- not permitted)', status: 'refused' },
    ]);

    await submitFanout();

    expect(vi.mocked(speakResponse)).not.toHaveBeenCalled();
  });
});
