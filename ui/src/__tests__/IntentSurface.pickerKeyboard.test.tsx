// AD-719c: keyboard navigation in the IntentSurface @-picker.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

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

// Deterministic callsign order. The picker dedupes and filters by prefix
// but otherwise preserves insertion order — fixture is sorted ascending so
// "third callsign" is unambiguous across CI runs.
beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map([
      ['a1', makeAgent('a1', 'alpha')],
      ['a2', makeAgent('a2', 'bravo')],
      ['a3', makeAgent('a3', 'charlie')],
    ]),
  });
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ response: '', mentions: [], per_agent_replies: [] }),
  });
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

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  return input;
}

function openPickerWithThreeMatches(): HTMLInputElement {
  render(<IntentSurface />);
  openShell();
  const input = getInput();
  // Empty prefix matches all three crew rows.
  fireEvent.change(input, { target: { value: '@' } });
  const rows = screen.queryAllByTestId('at-picker-row');
  expect(rows.length).toBe(3);
  return input;
}

function highlightedIndex(): number {
  const rows = screen.queryAllByTestId('at-picker-row');
  for (const r of rows) {
    const idx = r.getAttribute('data-picker-index');
    // The picker styles the highlighted row with a non-transparent background.
    const bg = (r as HTMLElement).style.background;
    if (bg && bg !== 'transparent') return Number(idx);
  }
  return -1;
}

describe('IntentSurface AD-719c — picker keyboard nav', () => {
  it('ArrowDown advances pickerIndex', () => {
    const input = openPickerWithThreeMatches();
    expect(highlightedIndex()).toBe(0);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(highlightedIndex()).toBe(1);
  });

  it('ArrowUp wraps to last when at top', () => {
    const input = openPickerWithThreeMatches();
    expect(highlightedIndex()).toBe(0);
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(highlightedIndex()).toBe(2);
  });

  it('Tab confirms the highlighted match', () => {
    const input = openPickerWithThreeMatches();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    // pickerIndex is now 2 → third row → "charlie".
    fireEvent.keyDown(input, { key: 'Tab' });
    expect(input.value).toContain('@charlie');
    // Picker closes after confirm.
    expect(screen.queryByTestId('at-picker-popover')).toBeNull();
  });

  it('Enter still confirms (backward compat with AD-719)', () => {
    const input = openPickerWithThreeMatches();
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    // pickerIndex is now 1 → "bravo".
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input.value).toContain('@bravo');
  });
});
