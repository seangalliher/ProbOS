/** BF-332: WorkBoard assignee fallback + detail modal tests.
 *
 * Two regressions from the AD-834 NL task-dispatch feature:
 *  - A dispatched task showed as "Unassigned" because the bookable-resource
 *    registry was empty; the board now falls back to the agents map.
 *  - Work cards could not be opened; a click now opens a detail modal.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('../store/useStore', () => {
  const state: any = {
    workItems: [],
    bookableResources: [],
    agents: new Map(),
    workTemplates: [],
    moveWorkItem: vi.fn(),
    createWorkItem: vi.fn(),
    assignWorkItem: vi.fn(),
    createFromTemplate: vi.fn(),
    fetchWorkTemplates: vi.fn(),
  };
  const useStore = (selector?: any) => (selector ? selector(state) : state);
  (useStore as any).getState = () => state;
  (useStore as any).__state = state;
  return { useStore };
});

import WorkBoard from '../components/work/WorkBoard';
import { useStore as _useStore } from '../store/useStore';

const state = (_useStore as any).__state;

function makeItem(overrides: any = {}) {
  return {
    id: 'wi-1',
    title: 'Summarize crew morale',
    work_type: 'task',
    status: 'in_progress',
    priority: 2,
    assigned_to: 'counselor-uuid-1',
    created_by: 'captain',
    description: 'Review recent logs and summarize morale.',
    steps: [],
    tags: [],
    due_at: null,
    estimated_tokens: 0,
    metadata: { dispatchable: true },
    ...overrides,
  };
}

function makeAgent(overrides: any = {}) {
  return {
    id: 'counselor-uuid-1',
    agentType: 'counselor',
    callsign: 'Ezri',
    ...overrides,
  };
}

beforeEach(() => {
  state.workItems = [];
  state.bookableResources = [];
  state.agents = new Map();
  // The board fetches done items on mount; stub fetch to an empty list.
  (global as any).fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ work_items: [] }) }),
  );
});

describe('BF-332 WorkBoard assignee fallback', () => {
  it('shows the agent callsign when no bookable resource matches', () => {
    state.workItems = [makeItem()];
    state.agents = new Map([['counselor-uuid-1', makeAgent()]]);
    render(<WorkBoard />);
    // Callsign appears on the card; "Unassigned" should not.
    expect(screen.getAllByText('Ezri').length).toBeGreaterThan(0);
    expect(screen.queryByText('Unassigned')).toBeNull();
  });

  it('shows Unassigned when neither a resource nor an agent matches', () => {
    state.workItems = [makeItem({ assigned_to: 'ghost-uuid' })];
    state.agents = new Map();
    render(<WorkBoard />);
    expect(screen.getByText('Unassigned')).toBeTruthy();
  });

  it('prefers a bookable resource callsign over the agents map', () => {
    state.workItems = [makeItem()];
    state.bookableResources = [
      { resource_id: 'counselor-uuid-1', callsign: 'Counselor-Res', agent_type: 'counselor', department: 'counseling' },
    ];
    state.agents = new Map([['counselor-uuid-1', makeAgent()]]);
    render(<WorkBoard />);
    expect(screen.getAllByText('Counselor-Res').length).toBeGreaterThan(0);
  });
});

describe('BF-332 WorkBoard detail modal', () => {
  it('opens a detail modal when a card is clicked', () => {
    state.workItems = [makeItem()];
    state.agents = new Map([['counselor-uuid-1', makeAgent()]]);
    render(<WorkBoard />);
    // Click the card title.
    fireEvent.click(screen.getByText('Summarize crew morale'));
    // Modal surfaces the description and a Close affordance.
    expect(screen.getByText('Review recent logs and summarize morale.')).toBeTruthy();
    expect(screen.getByLabelText('Close')).toBeTruthy();
  });

  it('closes the modal when Close is clicked', () => {
    state.workItems = [makeItem()];
    state.agents = new Map([['counselor-uuid-1', makeAgent()]]);
    render(<WorkBoard />);
    fireEvent.click(screen.getByText('Summarize crew morale'));
    expect(screen.getByLabelText('Close')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Close'));
    expect(screen.queryByLabelText('Close')).toBeNull();
  });
});
