/** AD-1321: WorkBoard value band / stakes display, creation and confirmation. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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
    confirmWorkItemValueContext: vi.fn(),
  };
  const useStore = (selector?: any) => (selector ? selector(state) : state);
  (useStore as any).getState = () => state;
  (useStore as any).__state = state;
  return { useStore };
});
vi.mock('../components/workspace/ownedStepsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/workspace/ownedStepsApi')>();
  return {
    ...actual,
    fetchOwnedSteps: vi.fn().mockResolvedValue({
      version: 1, mode: 'unmanaged', parent_id: 'wi-1', requested_item_id: 'wi-1',
      reference: null, rows: [], previous_cursor: null, next_cursor: null,
      recovery: [], finalization: 'none',
    }),
  };
});

import WorkBoard from '../components/work/WorkBoard';
import { useStore as _useStore } from '../store/useStore';

const state = (_useStore as any).__state;

const proposed = {
  source_kind: 'agent', source_id: 'ensign-7', recorded_at: 1, inherited_template_id: null,
  confirmed_by: null, confirmed_at: null, confirmation_kind: null,
};
const confirmed = {
  ...proposed, source_kind: 'captain', source_id: 'captain',
  confirmed_by: 'captain', confirmed_at: 2, confirmation_kind: 'captain',
};

function makeItem(overrides: any = {}) {
  return {
    id: 'wi-1', title: 'Seal the breach', work_type: 'task', status: 'in_progress',
    priority: 2, assigned_to: null, created_by: 'captain', description: 'Seal it.',
    steps: [], tags: [], due_at: null, estimated_tokens: 0, metadata: {},
    ...overrides,
  };
}

beforeEach(() => {
  state.workItems = [];
  state.workTemplates = [];
  state.createWorkItem.mockReset();
  state.confirmWorkItemValueContext.mockReset();
  (global as any).fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ work_items: [], count: 0 }) }),
  );
});

describe('AD-1321 WorkBoard cards', () => {
  it('shows no value or stakes labels when the item carries none', () => {
    state.workItems = [makeItem()];
    render(<WorkBoard />);
    expect(screen.queryByTestId('work-card-value-band')).toBeNull();
    expect(screen.queryByTestId('work-card-stakes')).toBeNull();
  });

  it('labels an unconfirmed proposal as unconfirmed and a confirmed one plainly', () => {
    state.workItems = [
      makeItem({ value_band: 'critical', value_band_provenance: proposed,
                 stakes: 'low', stakes_provenance: confirmed }),
    ];
    render(<WorkBoard />);
    expect(screen.getByTestId('work-card-value-band').textContent).toContain('critical');
    expect(screen.getByTestId('work-card-value-band').textContent).toContain('unconfirmed');
    expect(screen.getByTestId('work-card-stakes').textContent).toContain('low');
    expect(screen.getByTestId('work-card-stakes').textContent).not.toContain('unconfirmed');
  });
});

describe('AD-1321 WorkBoard quick create', () => {
  it('sends the chosen band and stakes, and omits them when unset', async () => {
    render(<WorkBoard />);
    fireEvent.click(screen.getByText('+ Quick Create'));
    fireEvent.change(screen.getByPlaceholderText('Card title...'), { target: { value: 'Plain' } });
    fireEvent.click(screen.getByText('Add'));
    await waitFor(() => expect(state.createWorkItem).toHaveBeenCalledTimes(1));
    expect(state.createWorkItem.mock.calls[0][0]).not.toHaveProperty('value_band');
    expect(state.createWorkItem.mock.calls[0][0]).not.toHaveProperty('stakes');

    fireEvent.click(screen.getByText('+ Quick Create'));
    fireEvent.change(screen.getByPlaceholderText('Card title...'), { target: { value: 'Valued' } });
    fireEvent.change(screen.getByLabelText('Value band'), { target: { value: 'significant' } });
    fireEvent.change(screen.getByLabelText('Stakes'), { target: { value: 'severe' } });
    fireEvent.click(screen.getByText('Add'));
    await waitFor(() => expect(state.createWorkItem).toHaveBeenCalledTimes(2));
    expect(state.createWorkItem.mock.calls[1][0]).toMatchObject({
      title: 'Valued', value_band: 'significant', stakes: 'severe',
    });
  });
});

describe('AD-1321 WorkBoard detail modal', () => {
  it('shows provenance and confirms through the store, surfacing API errors', async () => {
    state.workItems = [
      makeItem({ value_band: 'moderate', value_band_provenance: proposed }),
    ];
    state.confirmWorkItemValueContext.mockResolvedValueOnce({ ok: false, error: 'value_context_confirmation_conflict' });
    render(<WorkBoard />);
    fireEvent.click(screen.getByText('Seal the breach'));
    const row = await screen.findByTestId('work-board-value-band');
    expect(row.textContent).toContain('proposed by ensign-7');
    expect(row.textContent).toContain('unconfirmed');

    fireEvent.click(screen.getByTestId('work-board-confirm-value'));
    expect(state.confirmWorkItemValueContext).toHaveBeenCalledWith('wi-1');
    expect((await screen.findByTestId('work-board-confirm-error')).textContent)
      .toContain('value_context_confirmation_conflict');
    // The failed confirmation leaves the item pending: the button is still offered.
    expect(screen.getByTestId('work-board-confirm-value')).toBeTruthy();
  });

  it('offers no confirm button once everything declared is confirmed', async () => {
    state.workItems = [
      makeItem({ value_band: 'moderate', value_band_provenance: confirmed,
                 stakes: 'high', stakes_provenance: { ...confirmed, inherited_template_id: 'bug_report' } }),
    ];
    render(<WorkBoard />);
    fireEvent.click(screen.getByText('Seal the breach'));
    const stakes = await screen.findByTestId('work-board-stakes');
    expect(stakes.textContent).toContain('from template bug_report');
    expect(stakes.textContent).toContain('confirmed by captain');
    expect(screen.queryByTestId('work-board-confirm-value')).toBeNull();
  });

  it('offers no value rows or confirm button for an item without values', async () => {
    state.workItems = [makeItem()];
    render(<WorkBoard />);
    fireEvent.click(screen.getByText('Seal the breach'));
    await screen.findByText('Seal it.');
    expect(screen.queryByTestId('work-board-value-band')).toBeNull();
    expect(screen.queryByTestId('work-board-confirm-value')).toBeNull();
  });
});

describe('AD-1321 WorkBoard template preview', () => {
  it('previews a template value and stakes only when the template defines them', () => {
    state.workTemplates = [
      { template_id: 't1', name: 'Valued', category: 'ops', variables: [], value_band: 'critical', stakes: 'high' },
      { template_id: 't2', name: 'Bare', category: 'ops', variables: [] },
    ];
    render(<WorkBoard />);
    fireEvent.click(screen.getByText(/Template/));
    fireEvent.click(screen.getByText('Valued'));
    expect(screen.getByTestId('template-value-preview').textContent).toBe('value critical, stakes high');
  });

  it('shows no preview for a template without values', () => {
    state.workTemplates = [{ template_id: 't2', name: 'Bare', category: 'ops', variables: [] }];
    render(<WorkBoard />);
    fireEvent.click(screen.getByText(/Template/));
    fireEvent.click(screen.getByText('Bare'));
    expect(screen.queryByTestId('template-value-preview')).toBeNull();
  });
});