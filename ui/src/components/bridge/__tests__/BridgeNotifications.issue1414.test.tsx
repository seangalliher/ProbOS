// #1414 item 14 (BF-998): when the live fence refuses a notification's room-context read and no
// session is cached for its parent, the card opens nothing and offers a retry, instead of opening a
// room whose session band never renders and leaving the focus request pending. Real NotificationCard,
// real store and real liveReadFence (reset before each test by src/test/setup.ts); fetch is stubbed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { NotificationCard } from '../BridgeNotifications';
import { useStore } from '../../../store/useStore';
import { liveReadFence } from '../../../store/liveReadFence';
import type { Agent, NotificationView } from '../../../store/types';
import type { NotificationContext } from '../../sidebar/threadApi';

const initialStoreState = useStore.getState();
const REFUSED = 'Context unavailable: the room changed while it was loading. Retry to check again.';

function roomContext(): NotificationContext {
  return {
    kind: 'crew_session', notification_id: 'f'.repeat(64), delivery_revision: 1,
    thread: {
      id: 'room', task_id: 'parent', title: 'Failed room', participants: ['host'],
      project_id: null, pinned: false, archived: false, personality_override: null,
      workspace_root: null, created_at: 1, last_active_at: 3, preprompt: null,
      model: null, metadata: {},
    },
    session: {
      task_id: 'parent', thread_id: 'room', goal: 'Prepare report', origin: 'captain',
      originator_id: 'captain', facilitator_id: 'host', owner_ids: ['host'],
      state: 'failed', revision: 1, success_criteria: ['Complete'], expected_deliverable: 'Report',
      timestamps: { created_at: 1, transitioned_at: 3, started_at: 2, first_result_at: null, verified_at: null, completed_at: 3 },
      progress: { total: 1, done: 0, failed: 1, active: 0, active_child: null },
      last_result_summary: '', blocker: null, result: null, verification: null, duplicate_resume_count: 0,
    },
  };
}

function seedSourceView(): void {
  const host: Agent = {
    id: 'host', agentType: 'crew', callsign: 'Host', displayName: 'Host', pool: 'bridge',
    state: 'active', confidence: 1, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
  };
  useStore.setState({
    agents: new Map([['host', host]]), activeProfileAgent: 'original-host',
    activeProfileThreadId: 'original-room', activeThreadId: null,
    threadIdByAgent: new Map([['host', 'host-dm']]), chatThreads: new Map(),
    crewSessionsByParent: new Map(), notificationNavigation: null,
    liveGeneration: 'b'.repeat(32), liveSequence: 0,
  });
}

function notification(id: string): NotificationView {
  return {
    id, agent_id: 'p', agent_type: 'producer', department: 'ops',
    notification_type: 'action_required', title: 't', detail: 'd',
    action_url: '', created_at: 0, acknowledged: false,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('#1414 item 14: a notification context read the live fence refuses', () => {
  it('opens nothing, leaves no request pending, and its retry opens the room', async () => {
    seedSourceView();
    const context = roomContext();
    let answer: ((response: Response) => void) | undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>(settle => { answer = settle; }));
    render(<NotificationCard notification={notification(context.notification_id)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    expect(answer).toBeTypeOf('function');
    // A live write to the parent lands after the read was issued; nothing cached a session for it.
    liveReadFence.observe(`crew:${context.session.task_id}`);
    await act(async () => { answer!(new Response(JSON.stringify(context), { status: 200 })); });

    // A/B: on the base the card hydrated nothing, opened the room and reported 'Room context opened.'
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(REFUSED));
    const refused = useStore.getState();
    expect(refused.notificationNavigation).toBeNull();
    expect(refused.activeProfileAgent).toBe('original-host');
    expect(refused.activeProfileThreadId).toBe('original-room');
    expect(refused.crewSessionsByParent.has(context.session.task_id)).toBe(false);
    expect(refused.chatThreads.has(context.thread.id)).toBe(false);

    fetchMock.mockImplementationOnce(async () => new Response(JSON.stringify(context), { status: 200 }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry opening context' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Room context opened.'));
    const opened = useStore.getState();
    expect(opened.activeProfileAgent).toBe('host');
    expect(opened.activeProfileThreadId).toBe(context.thread.id);
    expect(opened.crewSessionsByParent.get(context.session.task_id)).toEqual(context.session);
    expect(opened.notificationNavigation?.destination).toEqual({
      hostId: 'host', threadId: context.thread.id, parentId: context.session.task_id, updated: false,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
