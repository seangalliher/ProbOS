/**
 * AD-795 — YeoStarterChips tests.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { YeoStarterChips, DEFAULT_CHIPS } from '../components/YeoStarterChips';
import { useStore } from '../store/useStore';

function reset() {
  useStore.setState({ chatDrafts: {} });
}

describe('YeoStarterChips (AD-795)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); });

  it('renders the default chip set', () => {
    render(<YeoStarterChips agentId="yeo-1" />);
    expect(screen.getByTestId('yeo-starter-chips')).toBeTruthy();
    for (const chip of DEFAULT_CHIPS) {
      expect(screen.getByTestId(`yeo-chip-${chip.id}`).textContent).toBe(chip.label);
    }
  });

  it('renders a custom chip set when provided', () => {
    const custom = [
      { id: 'one', label: 'One', prompt: 'one prompt' },
      { id: 'two', label: 'Two', prompt: 'two prompt' },
    ];
    render(<YeoStarterChips agentId="yeo-1" chips={custom} />);
    expect(screen.getByTestId('yeo-chip-one').textContent).toBe('One');
    expect(screen.getByTestId('yeo-chip-two').textContent).toBe('Two');
    expect(screen.queryByTestId('yeo-chip-brief')).toBeNull();
  });

  it('click inserts the chip prompt into the agent chatDraft (does not auto-send)', () => {
    render(<YeoStarterChips agentId="yeo-1" />);
    fireEvent.click(screen.getByTestId('yeo-chip-plan'));
    const plan = DEFAULT_CHIPS.find((c) => c.id === 'plan');
    expect(plan).toBeDefined();
    expect(useStore.getState().chatDrafts['yeo-1']).toBe(plan!.prompt);
  });

  it('drafts are scoped per agentId', () => {
    const { rerender } = render(<YeoStarterChips agentId="yeo-a" />);
    fireEvent.click(screen.getByTestId('yeo-chip-brief'));
    rerender(<YeoStarterChips agentId="yeo-b" />);
    fireEvent.click(screen.getByTestId('yeo-chip-code'));
    const drafts = useStore.getState().chatDrafts;
    expect(drafts['yeo-a']).toContain('Brief me');
    expect(drafts['yeo-b']).toContain('code');
  });
});
