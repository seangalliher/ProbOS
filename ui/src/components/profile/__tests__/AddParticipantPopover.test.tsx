// AD-917: tests for the AddParticipantPopover crew picker. Seeds the REAL
// zustand store with an `agents` map (BF-287 real-fixture style, no MagicMock)
// and renders the popover directly — it has no IntentSurface coupling, so it
// renders trivially. Covers crew derivation/exclusion, prefix filtering,
// keyboard nav, mouse select, Esc, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { Agent } from '../../../store/types';
import { AddParticipantPopover } from '../AddParticipantPopover';

function mkAgent(p: {
  id: string;
  callsign: string;
  displayName?: string;
  isCrew?: boolean;
  department?: string;
}): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: p.displayName ?? '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: p.isCrew ?? true,
    position: [0, 0, 0] as [number, number, number],
    department: p.department ?? '',
  } as Agent;
}

function seedAgents(list: Agent[]): void {
  const m = new Map<string, Agent>();
  for (const a of list) m.set(a.id, a);
  useStore.setState({ agents: m });
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map() });
});

describe('AD-917 AddParticipantPopover', () => {
  it('renders one row per crew agent, excluding existing participants, captain, and non-crew', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Vex', displayName: 'Engineer', department: 'engineering' }),
      mkAgent({ id: 'a2', callsign: 'Lume', displayName: 'Science', department: 'science' }),
      mkAgent({ id: 'a3', callsign: 'Onyx', displayName: 'Security', department: 'security' }),
      mkAgent({ id: 'captain', callsign: 'Captain', isCrew: true }),
      mkAgent({ id: 'u1', callsign: 'Util', isCrew: false }),
    ]);
    render(<AddParticipantPopover existingParticipantIds={['a2']} onAdd={vi.fn()} onClose={vi.fn()} />);

    const rows = screen.getAllByTestId('add-participant-row');
    expect(rows).toHaveLength(2); // a1, a3 (a2 existing, captain by id, u1 not crew)
    const html = screen.getByTestId('add-participant-popover').innerHTML;
    expect(html).toContain('Vex');
    expect(html).toContain('Onyx');
    expect(html).not.toContain('Lume');
  });

  it('prefix input filters rows by callsign (case-insensitive startsWith)', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Vex' }),
      mkAgent({ id: 'a2', callsign: 'Vox' }),
      mkAgent({ id: 'a3', callsign: 'Onyx' }),
    ]);
    render(<AddParticipantPopover existingParticipantIds={[]} onAdd={vi.fn()} onClose={vi.fn()} />);

    fireEvent.change(screen.getByTestId('add-participant-filter'), { target: { value: 'VO' } });

    const rows = screen.getAllByTestId('add-participant-row');
    expect(rows).toHaveLength(1);
    expect(screen.getByTestId('add-participant-popover').innerHTML).toContain('Vox');
  });

  it('ArrowDown/ArrowUp move the highlight; Enter calls onAdd with the highlighted id', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Aaa' }),
      mkAgent({ id: 'a2', callsign: 'Bbb' }),
      mkAgent({ id: 'a3', callsign: 'Ccc' }),
    ]);
    const onAdd = vi.fn();
    render(<AddParticipantPopover existingParticipantIds={[]} onAdd={onAdd} onClose={vi.fn()} />);
    const input = screen.getByTestId('add-participant-filter');

    fireEvent.keyDown(input, { key: 'ArrowDown' }); // -> index 1 (a2)
    fireEvent.keyDown(input, { key: 'ArrowDown' }); // -> index 2 (a3)
    fireEvent.keyDown(input, { key: 'ArrowUp' });   // -> index 1 (a2)
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onAdd).toHaveBeenCalledWith('a2');
  });

  it('mouse click on a row calls onAdd with that id', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Aaa' }),
      mkAgent({ id: 'a2', callsign: 'Bbb' }),
    ]);
    const onAdd = vi.fn();
    render(<AddParticipantPopover existingParticipantIds={[]} onAdd={onAdd} onClose={vi.fn()} />);

    fireEvent.click(screen.getAllByTestId('add-participant-row')[1]);

    expect(onAdd).toHaveBeenCalledWith('a2');
  });

  it('Escape calls onClose', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Aaa' })]);
    const onClose = vi.fn();
    render(<AddParticipantPopover existingParticipantIds={[]} onAdd={vi.fn()} onClose={onClose} />);

    fireEvent.keyDown(screen.getByTestId('add-participant-filter'), { key: 'Escape' });

    expect(onClose).toHaveBeenCalled();
  });

  it('renders no emoji (HXI #3)', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Aaa', displayName: 'Engineer', department: 'engineering' }),
    ]);
    const { container } = render(
      <AddParticipantPopover existingParticipantIds={[]} onAdd={vi.fn()} onClose={vi.fn()} />,
    );
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
