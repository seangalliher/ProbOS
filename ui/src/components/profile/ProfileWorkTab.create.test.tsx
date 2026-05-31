/**
 * AD-834: NL task creation + dispatch toggle in the HXI Work Tab.
 * Verifies the create form forwards a natural-language `description` and a
 * `metadata.dispatchable` flag (gated on the "Dispatch to agent now" toggle).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ProfileWorkTab } from './ProfileWorkTab';
import { useStore } from '../../store/useStore';

const createWorkItem = vi.fn<(item: Record<string, unknown>) => Promise<void>>(
  async () => {},
);

function resetStore() {
  useStore.setState({
    workItems: [],
    workBookings: [],
    bookableResources: [],
    agents: new Map(),
    scheduledTasks: [],
    workTemplates: [],
    createWorkItem,
  });
}

beforeEach(() => {
  createWorkItem.mockClear();
  resetStore();
  // The component fetches completed items on mount; stub it.
  global.fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ work_items: [] }),
  })) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openCreateForm() {
  render(<ProfileWorkTab agentId="agent-1" />);
  fireEvent.click(screen.getByText('+ Create Task'));
}

describe('ProfileWorkTab create form (AD-834)', () => {
  it('renders instructions textarea and dispatch toggle', () => {
    openCreateForm();
    expect(
      screen.getByPlaceholderText(/Describe what the agent should do/),
    ).toBeTruthy();
    expect(screen.getByText('Dispatch to agent now')).toBeTruthy();
    expect(screen.getByRole('checkbox')).toBeTruthy();
  });

  it('create payload includes description and dispatchable metadata when toggle is on', () => {
    openCreateForm();
    fireEvent.change(screen.getByPlaceholderText('Task title...'), {
      target: { value: 'Summarize the report' },
    });
    fireEvent.change(
      screen.getByPlaceholderText(/Describe what the agent should do/),
      { target: { value: 'Read q3.pdf and write a one-page summary' } },
    );
    fireEvent.click(screen.getByText('Create'));

    expect(createWorkItem).toHaveBeenCalledTimes(1);
    const payload = createWorkItem.mock.calls[0][0];
    expect(payload.title).toBe('Summarize the report');
    expect(payload.description).toBe('Read q3.pdf and write a one-page summary');
    expect(payload.metadata).toEqual({ dispatchable: true });
  });

  it('omits dispatchable metadata when the toggle is off', () => {
    openCreateForm();
    fireEvent.change(screen.getByPlaceholderText('Task title...'), {
      target: { value: 'Draft task' },
    });
    fireEvent.click(screen.getByRole('checkbox')); // toggle OFF (default on)
    fireEvent.click(screen.getByText('Create'));

    expect(createWorkItem).toHaveBeenCalledTimes(1);
    const payload = createWorkItem.mock.calls[0][0];
    expect(payload.metadata).toBeUndefined();
  });
});
