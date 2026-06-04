import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import CrewCollaborationPanel from './CrewCollaborationPanel';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function stubFetch(payload: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => payload }),
  );
}

describe('CrewCollaborationPanel', () => {
  it('pulses in_progress children and settles done children', async () => {
    stubFetch({
      parent: { id: 'p1', title: 'Crew goal', status: 'in_progress' },
      count: 2,
      children: [
        { id: 'a', title: 'Subtask A', status: 'in_progress', assigned_to: null, verdict: null, rounds: null },
        { id: 'b', title: 'Subtask B', status: 'done', assigned_to: null, verdict: null, rounds: null },
      ],
    });

    render(<CrewCollaborationPanel parentId="p1" />);

    await waitFor(() => {
      expect(screen.getByTestId('crew-collaboration-panel')).toBeTruthy();
    });
    const cards = screen.getAllByTestId('crew-subtask-card');
    expect(cards).toHaveLength(2);
    const a = cards.find(c => c.getAttribute('data-status') === 'in_progress')!;
    const b = cards.find(c => c.getAttribute('data-status') === 'done')!;
    // in_progress -> pulse animation class; done -> static (no pulse class).
    expect(a.className).toContain('crew-subtask-pulse');
    expect(b.className).not.toContain('crew-subtask-pulse');
  });

  it('shows a verdict when present and pending state when null', async () => {
    stubFetch({
      parent: { id: 'p1', title: 'Crew goal', status: 'done' },
      count: 2,
      children: [
        {
          id: 'a', title: 'Subtask A', status: 'done', assigned_to: null, rounds: 2,
          verdict: { accepted: true, confidence: 0.91, critique: 'Looks complete.', verifier_agent_id: 'v1' },
        },
        { id: 'b', title: 'Subtask B', status: 'in_progress', assigned_to: null, verdict: null, rounds: null },
      ],
    });

    render(<CrewCollaborationPanel parentId="p1" />);

    await waitFor(() => {
      expect(screen.getByTestId('crew-collaboration-panel')).toBeTruthy();
    });
    expect(screen.getByTestId('crew-subtask-verdict')).toBeTruthy();
    expect(screen.getByText('accepted')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-pending')).toBeTruthy();
  });

  it('renders nothing when the tree has no children payload', async () => {
    stubFetch({});
    const { container } = render(<CrewCollaborationPanel parentId="p1" />);
    await waitFor(() => {
      expect(container.querySelector('[data-testid="crew-collaboration-panel"]')).toBeNull();
    });
  });
});
