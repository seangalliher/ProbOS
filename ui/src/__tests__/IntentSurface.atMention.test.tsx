// AD-719: Component-level test for IntentSurface @-mention picker, chip strip,
// and per-agent fan-out reply rendering.

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

// Common emoji ranges. Asserting absence verifies HXI Design Principle #3.
const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

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

beforeEach(() => {
  // Reset store to a known shape for each test.
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map([
      ['a1', makeAgent('a1', 'counselor')],
      ['a2', makeAgent('a2', 'worf')],
      ['a3', makeAgent('a3', 'echo')],
    ]),
  });
  // Mock fetch with a fan-out response.
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      response: '',
      mentions: ['counselor', 'worf'],
      per_agent_replies: [
        { agent_id: 'a1', callsign: 'counselor', text: 'I hear you.' },
        { agent_id: 'a2', callsign: 'worf', text: 'Acknowledged.' },
      ],
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openShell() {
  // The pill is a div containing "Ask ProbOS..." (it's not a button).
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    // The clickable element is the parent div that owns onClick.
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount — pill click did not activate the shell');
  return input;
}

describe('IntentSurface AD-719 — multi-agent chat', () => {
  it('typing @c opens picker with matching crew', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '@c' } });
    const popover = screen.queryByTestId('at-picker-popover');
    expect(popover).toBeTruthy();
    const rows = screen.queryAllByTestId('at-picker-row');
    expect(rows.length).toBeGreaterThanOrEqual(1);
    expect(rows[0].textContent).toContain('counselor');
  });

  it('Enter on focused picker row replaces token with @callsign and adds chip', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '@c' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input.value).toContain('@counselor');
    const chips = screen.queryAllByTestId('recipient-chip');
    expect(chips.length).toBe(1);
    expect(chips[0].textContent).toContain('@counselor');
  });

  it('removing a chip via SVG x clears the @callsign from the input', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '@counselor hi' } });
    let chips = screen.queryAllByTestId('recipient-chip');
    expect(chips.length).toBe(1);
    const removeBtn = screen.getByTestId('chip-remove');
    fireEvent.click(removeBtn);
    chips = screen.queryAllByTestId('recipient-chip');
    expect(chips.length).toBe(0);
    expect(input.value).not.toContain('@counselor');
  });

  it('multi-mention fan-out renders one ChatMessage per per_agent_reply with attribution', async () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    const form = input.closest('form') as HTMLFormElement;
    fireEvent.change(input, { target: { value: '@counselor @worf hello team' } });
    await act(async () => {
      fireEvent.submit(form);
      // allow the fetch then-chain to resolve
      await Promise.resolve();
      await Promise.resolve();
    });
    const history = useStore.getState().chatHistory;
    const agentMsgs = history.filter((m) => m.role === 'agent');
    expect(agentMsgs.length).toBe(2);
    const callsigns = agentMsgs.map((m) => m.callsign);
    expect(callsigns).toContain('counselor');
    expect(callsigns).toContain('worf');
  });

  it('renders no emoji codepoints anywhere in the input/picker/chip surface', () => {
    render(<IntentSurface />);
    openShell();
    const input = getInput();
    fireEvent.change(input, { target: { value: '@c' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    const chipText = (screen.queryByTestId('recipient-chip-strip')?.textContent ?? '');
    expect(EMOJI_RE.test(chipText)).toBe(false);
    const pickerText = (screen.queryByTestId('at-picker-popover')?.textContent ?? '');
    expect(EMOJI_RE.test(pickerText)).toBe(false);
  });
});
