// AD-931: tests for the unified CHATS panel (supersedes the AD-919
// GroupChatListPanel test). Mocks the threadApi list/participant wrappers and
// seeds the REAL store (agents + the chatsOpen flag) so the isChat filter
// (1:1 + group, task rooms excluded), agent-created badge, avatars, Join
// (addParticipant 'captain'), and the per-host open-on-click (AD-937
// openGroupChatThread override) are exercised end-to-end through the store — BF-287
// real-fixture style, no MagicMock at the store boundary. Includes the HXI
// no-emoji guard. Test #1 FLIPS the AD-919 contract: 1:1s are now INCLUDED.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within, type RenderResult } from '@testing-library/react';
import { useStore, type AD791aChatThreadView } from '../../../store/useStore';
import type { Agent, CrewSessionSummaryProjection, RoomSummary } from '../../../store/types';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  getThread: vi.fn(),
  repairRoomSummaries: vi.fn(),
  createThread: vi.fn(),
}));

import { listThreads, addParticipant, repairRoomSummaries } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';

function mkAgent(p: { id: string; callsign: string; isCrew?: boolean; department?: string }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
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

function mkThread(over: Partial<AD791aChatThreadView> & { id: string }): AD791aChatThreadView {
  return {
    title: 'Room',
    participants: [],
    created_at: 0,
    last_active_at: 0,
    ...over,
  };
}

const AGENTS: Agent[] = [
  mkAgent({ id: 'mccoy', callsign: 'Bones', department: 'science' }),
  mkAgent({ id: 'scotty', callsign: 'Scott', department: 'engineering' }),
];

// g1 — two crew, no created_by_agent -> group, Captain-built.
const G1 = mkThread({ id: 'g1', title: 'Bridge Sync', participants: ['mccoy', 'scotty'] });
// g2 — agent-created, Captain already joined.
const G2 = mkThread({
  id: 'g2',
  title: 'Diagnostics',
  participants: ['mccoy', 'scotty', 'captain'],
  metadata: { created_by_agent: 'mccoy' },
});
// g3 — single crew, no created_by_agent -> 1:1, now INCLUDED (AD-931).
const G3 = mkThread({ id: 'g3', title: 'Sickbay 1:1', participants: ['mccoy'] });
// g4 — agent-created, NOT joined by the Captain.
const G4 = mkThread({
  id: 'g4',
  title: 'Warp Core',
  participants: ['scotty', 'mccoy'],
  metadata: { created_by_agent: 'scotty' },
});
// t1 — AD-925 task room (task_id set) -> EXCLUDED from the chats list.
const T1 = mkThread({ id: 't1', title: 'Task Room', participants: ['mccoy', 'scotty'], task_id: 'task-1' });
const ALL = [G1, G2, G3, G4, T1];

function seedAgents(list: Agent[]): Map<string, Agent> {
  const am = new Map<string, Agent>();
  for (const a of list) am.set(a.id, a);
  return am;
}

async function renderOpen(
  threads: AD791aChatThreadView[] = ALL,
  agents: Agent[] = AGENTS,
  roomSummaries: Record<string, RoomSummary> = {},
): Promise<RenderResult> {
  vi.mocked(listThreads).mockResolvedValue(threads);
  vi.mocked(repairRoomSummaries).mockResolvedValue({
    kind: 'success', summaries: roomSummaries,
  });
  useStore.setState({
    agents: seedAgents(agents),
    chatsOpen: true,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeProfileAgent: null,
    activeProfileThreadId: null,
    crewSessionSummariesByThread: new Map(),
    roomSummariesByThread: new Map(),
  });
  const r = render(<ChatsPanel />);
  // Wait for the on-open fetch to populate the list (g1 is always a chat).
  await screen.findByTestId('chat-row-g1');
  return r;
}

afterEach(() => {
  cleanup();
  useStore.setState({
    agents: new Map(),
    chatsOpen: false,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeProfileAgent: null,
    activeProfileThreadId: null,
    crewSessionSummariesByThread: new Map(),
    roomSummariesByThread: new Map(),
  });
  vi.clearAllMocks();
});

describe('AD-931 ChatsPanel', () => {
  it('updates live room fields from the authoritative store map without reopen', async () => {
    await renderOpen();
    const liveSummary: RoomSummary = {
      outputs: 2,
      steps_total: 4,
      steps_done: 3,
      topic: 'Live navigation report',
    };
    useStore.getState().hydrateRoomSummaries({ g1: liveSummary });
    expect(await screen.findByTestId('room-badge-g1')).toHaveTextContent('3/4');
    expect(screen.getByTestId('room-badge-g1')).toHaveTextContent('2 out');
  });

  it('does no reconnect summary work while closed', async () => {
    vi.mocked(repairRoomSummaries).mockClear();
    useStore.setState({ chatsOpen: false, liveRepairEpoch: 9 });
    render(<ChatsPanel />);
    await Promise.resolve();
    expect(repairRoomSummaries).not.toHaveBeenCalled();
  });

  it('lists 1:1, group, AND task rooms (AD-1093)', async () => {
    await renderOpen();
    expect(screen.getByTestId('chat-row-g1')).toBeTruthy();
    expect(screen.getByTestId('chat-row-g2')).toBeTruthy();
    // g3 (1:1) is now INCLUDED — the AD-919 exclusion contract flips.
    expect(screen.getByTestId('chat-row-g3')).toBeTruthy();
    expect(screen.getByTestId('chat-row-g4')).toBeTruthy();
    // AD-1093: task rooms are the work rooms — now INCLUDED in Crew Collaboration.
    expect(screen.getByTestId('chat-row-t1')).toBeTruthy();
  });

  it('badges agent-created chats only', async () => {
    await renderOpen();
    const g1row = screen.getByTestId('chat-row-g1');
    const g2row = screen.getByTestId('chat-row-g2');
    const g3row = screen.getByTestId('chat-row-g3');
    const g4row = screen.getByTestId('chat-row-g4');
    expect(g1row.querySelector('[data-testid="chat-agent-badge"]')).toBeNull();
    expect(g3row.querySelector('[data-testid="chat-agent-badge"]')).toBeNull();
    expect(g2row.querySelector('[data-testid="chat-agent-badge"]')).not.toBeNull();
    expect(g4row.querySelector('[data-testid="chat-agent-badge"]')).not.toBeNull();
  });

  it('renders a participant avatar for each crew member (group row)', async () => {
    await renderOpen();
    const g1row = screen.getByTestId('chat-row-g1');
    expect(g1row.querySelectorAll('[data-testid="agent-avatar-badge"]')).toHaveLength(2);
  });

  it('1:1 row shows no Join control', async () => {
    await renderOpen();
    expect(screen.queryByTestId('chat-join-g3')).toBeNull();
    expect(screen.queryByTestId('chat-joined-g3')).toBeNull();
  });

  it('Join calls addParticipant(threadId, "captain") once', async () => {
    vi.mocked(addParticipant).mockResolvedValue(null);
    await renderOpen();
    fireEvent.click(screen.getByTestId('chat-join-g4'));
    await waitFor(() => expect(addParticipant).toHaveBeenCalledWith('g4', 'captain'));
    expect(addParticipant).toHaveBeenCalledTimes(1);
  });

  it('Join flips the row from join control to a "Joined" marker', async () => {
    vi.mocked(addParticipant).mockResolvedValue(
      mkThread({
        id: 'g4',
        title: 'Warp Core',
        participants: ['scotty', 'mccoy', 'captain'],
        metadata: { created_by_agent: 'scotty' },
        last_active_at: 1,
      }),
    );
    await renderOpen();
    expect(screen.getByTestId('chat-join-g4')).toBeTruthy();
    fireEvent.click(screen.getByTestId('chat-join-g4'));
    await waitFor(() => expect(screen.queryByTestId('chat-joined-g4')).not.toBeNull());
    expect(screen.queryByTestId('chat-join-g4')).toBeNull();
  });

  it('clicking a group row opens the chat in the first crew host via the AD-937 override', async () => {
    await renderOpen();
    fireEvent.click(screen.getByTestId('chat-row-g1'));
    // AD-937: open-on-click addresses the chat via the group override
    // (activeProfileThreadId), NOT the host's single threadIdByAgent 1:1 slot.
    // AD-971: handleOpen is async (re-fetches the thread) -> await the result.
    await waitFor(() => expect(useStore.getState().activeProfileThreadId).toBe('g1'));
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBeUndefined();
  });

  it('clicking a 1:1 row opens the chat in its single crew host via the AD-937 override', async () => {
    await renderOpen();
    fireEvent.click(screen.getByTestId('chat-row-g3'));
    await waitFor(() => expect(useStore.getState().activeProfileThreadId).toBe('g3'));
    expect(useStore.getState().activeProfileAgent).toBe('mccoy');
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBeUndefined();
  });

  it('AD-937: after opening a group, reopening the host profile clears the override (1:1 reachable)', async () => {
    await renderOpen();
    // Bind mccoy's 1:1 default first (simulating a prior 1:1 send round-trip).
    useStore.getState().setThreadForAgent('mccoy', 'mccoy-1to1');
    fireEvent.click(screen.getByTestId('chat-row-g1')); // open the group g1
    await waitFor(() => expect(useStore.getState().activeProfileThreadId).toBe('g1'));
    // Reopen mccoy from the roster -> the override clears, the 1:1 slot intact.
    useStore.getState().openAgentProfile('mccoy');
    expect(useStore.getState().activeProfileThreadId).toBeNull();
    expect(useStore.getState().threadIdByAgent.get('mccoy')).toBe('mccoy-1to1');
  });

  it('sorts un-joined agent-created chats to the top (HXI #9)', async () => {
    await renderOpen();
    const rows = screen.getAllByTestId(/^chat-row-/);
    const ids = rows.map((el) => el.getAttribute('data-testid'));
    const i4 = ids.indexOf('chat-row-g4');
    const i1 = ids.indexOf('chat-row-g1');
    const i2 = ids.indexOf('chat-row-g2');
    expect(i4).toBeGreaterThanOrEqual(0);
    expect(i4).toBeLessThan(i1);
    expect(i4).toBeLessThan(i2);
  });

  it('uses the validated session goal and hydrates compact session context', async () => {
    const session: CrewSessionSummaryProjection = {
      task_id: 'task-1',
      thread_id: 't1',
      goal: 'Resolve the long-range navigation anomaly with verified evidence',
      state: 'blocked_needs_captain',
      facilitator_id: 'scotty',
      owner_ids: ['scotty', 'mccoy'],
      progress: { total: 4, done: 2, failed: 0, active: 2 },
      last_result_summary: 'The crew needs approval for the final source.',
      blocker: { reason: 'Approve source', since: 10, duration_seconds: 90 },
      needs_attention: true,
      result_artifact_id: null,
      verified_at: null,
    };
    await renderOpen(ALL, AGENTS, {
      t1: { outputs: 0, steps_total: 0, steps_done: 0, topic: session.goal, session },
    });

    const title = await screen.findByText(session.goal);
    expect((title as HTMLElement).style.whiteSpace).toBe('normal');
    const row = screen.getByTestId('chat-row-t1');
    const context = screen.getByTestId('room-session-t1');
    expect(row.getAttribute('data-needs-attention')).toBe('true');
    expect(row.style.minWidth).toBe('0px');
    expect(context.style.minWidth).toBe('0px');
    expect(context.textContent).toContain('blocked_needs_captain');
    expect(context.textContent).toContain('Facilitator scotty');
    expect(useStore.getState().crewSessionSummariesByThread.get('t1')).toEqual(session);

    fireEvent.change(screen.getByTestId('rooms-search'), { target: { value: 'navigation anomaly' } });
    expect(screen.getByTestId('chat-row-t1')).toBeTruthy();
  });

  it('renders the same complete compact session context for a one-owner row', async () => {
    const session: CrewSessionSummaryProjection = {
      task_id: 'task-solo',
      thread_id: 'g3',
      goal: 'Prepare the verified medical readiness brief',
      state: 'done',
      facilitator_id: 'mccoy',
      owner_ids: ['mccoy'],
      progress: { total: 3, done: 2, failed: 1, active: 0 },
      last_result_summary: 'Readiness brief accepted.',
      blocker: null,
      needs_attention: false,
      result_artifact_id: 'artifact-medical',
      verified_at: Date.now() / 1000 - 120,
    };
    await renderOpen(ALL, AGENTS, {
      g3: { outputs: 1, steps_total: 3, steps_done: 2, topic: session.goal, session },
    });

    const row = screen.getByTestId('chat-row-g3');
    const context = screen.getByTestId('room-session-g3');
    expect(row.textContent).toContain(session.goal);
    expect(context.textContent).toContain('done · 2/3 done · 0 active · 1 failed');
    expect(context.textContent).toContain('Facilitator mccoy · Owners mccoy');
    expect(context.textContent).toContain('Readiness brief accepted.');
    expect(context.textContent).toContain('Result artifact-medical · verified');
    expect(row.textContent).not.toContain('\u2713');
  });

  it('retains exact generic non-session one-owner markup and styles', async () => {
    await renderOpen();

    const row = screen.getByTestId('chat-row-g3');
    const title = screen.getByText('Bones');
    expect(row.textContent).toContain('Bones');
    expect(row.hasAttribute('data-needs-attention')).toBe(false);
    expect(row.querySelector('[data-testid="room-session-g3"]')).toBeNull();
    expect(row.querySelector('[data-testid="chat-agent-badge"]')).toBeNull();
    expect(screen.queryByTestId('chat-join-g3')).toBeNull();
    expect(row.style.display).toBe('flex');
    expect(row.style.alignItems).toBe('center');
    expect(row.style.gap).toBe('8px');
    expect(row.style.minWidth).toBe('');
    expect(title.style.fontSize).toBe('13px');
    expect(title.style.fontWeight).toBe('600');
    expect(title.style.minWidth).toBe('');
    expect(title.style.overflowWrap).toBe('');
    expect(title.style.whiteSpace).toBe('');
  });

  it('retains exact generic non-session group markup and styles', async () => {
    await renderOpen();

    const row = screen.getByTestId('chat-row-g1');
  const title = within(row).getByText('Bones, Scott');
    expect(row.hasAttribute('data-needs-attention')).toBe(false);
    expect(row.querySelector('[data-testid="room-session-g1"]')).toBeNull();
    expect(row.style.display).toBe('');
    expect(row.style.minWidth).toBe('');
    expect(title.style.fontSize).toBe('13px');
    expect(title.style.fontWeight).toBe('600');
    expect(title.style.minWidth).toBe('');
    expect(title.style.overflowWrap).toBe('');
    expect(title.style.whiteSpace).toBe('');
  });

  it('keeps the legacy generic room badge including its checkmark', async () => {
    await renderOpen(ALL, AGENTS, {
      g1: { outputs: 0, steps_total: 3, steps_done: 2, topic: 'Generic work' },
    });

    expect(screen.getByTestId('room-badge-g1').textContent).toBe('\u2713 2/3');
  });

  it('renders session verification at epoch zero', async () => {
    const session: CrewSessionSummaryProjection = {
      task_id: 'task-solo',
      thread_id: 'g3',
      goal: 'Archive the verified readiness brief',
      state: 'done',
      facilitator_id: 'mccoy',
      owner_ids: ['mccoy'],
      progress: { total: 1, done: 1, failed: 0, active: 0 },
      last_result_summary: 'Archive complete.',
      blocker: null,
      needs_attention: false,
      result_artifact_id: 'artifact-epoch',
      verified_at: 0,
    };
    await renderOpen(ALL, AGENTS, {
      g3: { outputs: 1, steps_total: 1, steps_done: 1, topic: session.goal, session },
    });

    const context = screen.getByTestId('room-session-g3');
    expect(context.textContent).toContain('verified');
    expect(context.textContent).toContain('1970');
  });

  it('Needs You includes blocked sessions before existing unjoined alerts', async () => {
    const blocked: CrewSessionSummaryProjection = {
      task_id: 'task-1',
      thread_id: 't1',
      goal: 'Captain decision needed',
      state: 'blocked_needs_captain',
      facilitator_id: 'mccoy',
      owner_ids: ['mccoy', 'scotty'],
      progress: { total: 1, done: 0, failed: 0, active: 1 },
      last_result_summary: '',
      blocker: { reason: 'Choose route', since: 10, duration_seconds: 30 },
      needs_attention: true,
      result_artifact_id: null,
      verified_at: null,
    };
    await renderOpen(ALL, AGENTS, {
      t1: { outputs: 0, steps_total: 0, steps_done: 0, topic: blocked.goal, session: blocked },
    });
    fireEvent.click(screen.getByTestId('rooms-filter-needs'));

    const ids = screen.getAllByTestId(/^chat-row-/).map(row => row.getAttribute('data-testid'));
    expect(ids).toEqual(['chat-row-t1', 'chat-row-g4']);
    expect(screen.getByTestId('chat-row-t1').getAttribute('data-needs-attention')).toBe('true');
  });

  it('self-gates: renders nothing when closed', () => {
    useStore.setState({ agents: seedAgents(AGENTS), chatsOpen: false });
    const { container } = render(<ChatsPanel />);
    expect(screen.queryByTestId('chats-panel')).toBeNull();
    expect(container.innerHTML).toBe('');
  });

  it('contains no emoji (HXI #3 stroke-SVG only)', async () => {
    const { container } = await renderOpen();
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
