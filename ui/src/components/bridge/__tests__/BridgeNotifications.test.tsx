// AD-1053: NotificationCard renders an "Accept" button only when the
// notification carries a producer-authored suggested_action.label, and clicking
// it POSTs to /api/notifications/{id}/accept (stopPropagation so the card's ack
// handler does not also fire). HXI no-emoji guard (#3). Real component; the
// global fetch is stubbed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NotificationCard } from '../BridgeNotifications';
import cardSource from '../BridgeNotifications.tsx?raw';
import { useStore } from '../../../store/useStore';
import type { Agent, NotificationView } from '../../../store/types';
import type { NotificationContext } from '../../sidebar/threadApi';

const EMOJI_RE = /\p{Extended_Pictographic}/u;
const initialStoreState = useStore.getState();

function contextFixture(id = 'a'.repeat(64)): NotificationContext {
  return {
    kind: 'crew_session', notification_id: id, delivery_revision: 1,
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

function seedNavigation(): void {
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

function StoreNotificationCard() {
  const notification = useStore(state => state.notifications?.[0]);
  return notification ? <NotificationCard notification={notification} /> : null;
}

function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    id: 'n1',
    agent_id: 'p',
    agent_type: 'producer',
    department: 'ops',
    notification_type: 'action_required',
    title: 't',
    detail: 'd',
    action_url: '',
    created_at: 0,
    acknowledged: false,
    ...overrides,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve({ ok: true } as Response));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('AD-1053 NotificationCard accept affordance', () => {
  it('renders an Accept button and POSTs to the accept endpoint on click', () => {
    const n = makeNotification({
      suggested_action: { label: 'Do it', intent: 'direct_message' },
    });
    render(<NotificationCard notification={n} />);

    const btn = screen.getByTestId('notification-accept');
    expect(btn).toHaveTextContent('Do it');

    fireEvent.click(btn);

    // stopPropagation -> only the accept endpoint is hit, not the card's /ack.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/n1/accept', { method: 'POST' });
  });

  it('renders no Accept button when suggested_action is absent (byte-identical card)', () => {
    render(<NotificationCard notification={makeNotification()} />);

    expect(screen.queryByTestId('notification-accept')).toBeNull();
  });

  it('contains no emoji (HXI #3) in source or rendered DOM', () => {
    expect(cardSource).not.toMatch(EMOJI_RE);

    const n = makeNotification({
      suggested_action: { label: 'Do it', intent: 'direct_message' },
    });
    const { container } = render(<NotificationCard notification={n} />);

    expect(container.textContent ?? '').not.toMatch(EMOJI_RE);
  });
});

describe('issue1373 Crew failure notification context', () => {
  it.each(['pointer', 'Enter', 'Space'])('opens the exact validated room via %s with no writes', async (activation) => {
    seedNavigation();
    const context = contextFixture();
    context.session = { ...context.session, revision: 2 };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(context), { status: 200 }));
    render(<NotificationCard notification={makeNotification({ id: context.notification_id, action_url: 'javascript:unsafe()' })} />);
    const button = screen.getByRole('button', { name: 'Open room context: t' });
    const user = userEvent.setup();
    if (activation === 'pointer') await user.click(button);
    else {
      button.focus();
      await user.keyboard(activation === 'Enter' ? '{Enter}' : ' ');
    }
    await waitFor(() => expect(useStore.getState().activeProfileThreadId).toBe('room'));
    expect(useStore.getState().activeProfileAgent).toBe('host');
    expect(useStore.getState().chatThreads.get('room')).toEqual(context.thread);
    expect(useStore.getState().crewSessionsByParent.get('parent')).toEqual(context.session);
    expect(useStore.getState().threadIdByAgent.get('host')).toBe('host-dm');
    expect(useStore.getState().notificationNavigation?.destination?.updated).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(`/api/notifications/${context.notification_id}/context`, expect.objectContaining({ method: 'GET', redirect: 'error' }));
  });

  it.each(['pointer', 'Enter', 'Space'])('opens completed delivery results via %s without acknowledgement or execution', async (activation) => {
    seedNavigation();
    const context = contextFixture();
    context.session = {
      ...context.session, state: 'done', last_result_summary: 'Verified report ready',
      timestamps: { ...context.session.timestamps, first_result_at: 2, verified_at: 3 },
      progress: { total: 1, done: 1, failed: 0, active: 0, active_child: null },
      result: { artifact_id: 'verified-report', content_hash: 'c'.repeat(64), result_ref: 'd'.repeat(64), evidence_refs: ['e'.repeat(64)] },
      verification: { verifier_agent_id: 'verifier', confidence: 0.95, critique: 'Accepted', accepted_count: 1, total_count: 1, convergence_rounds: 1 },
    };
    const notification = makeNotification({
      id: context.notification_id, agent_type: 'crew_session', notification_type: 'info',
      title: 'Crew session completed', detail: 'Open the existing crew room for details.',
    });
    useStore.setState({ notifications: [notification] });
    const beforeNotifications = useStore.getState().notifications;
    expect(context.session.revision).toBe(context.delivery_revision);
    fetchMock.mockResolvedValue(new Response(JSON.stringify(context), { status: 200 }));
    const activated = vi.fn();
    render(<div onClickCapture={activated}><NotificationCard notification={notification} /></div>);
    const button = screen.getByRole('button', { name: 'Open room context: Crew session completed' });
    const user = userEvent.setup();
    if (activation === 'pointer') await user.click(button);
    else {
      button.focus();
      await user.keyboard(activation === 'Enter' ? '{Enter}' : ' ');
    }
    expect(activated).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(`/api/notifications/${context.notification_id}/context`, expect.objectContaining({ method: 'GET', redirect: 'error' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Room context opened.'));
    const state = useStore.getState();
    expect(state.activeProfileThreadId).toBe(context.thread.id);
    expect(state.activeProfileAgent).toBe('host');
    expect(state.chatThreads.get(context.thread.id)).toEqual(context.thread);
    expect(state.crewSessionsByParent.get(context.session.task_id)).toEqual(context.session);
    expect(state.crewSessionsByParent.get(context.session.task_id)?.result).toEqual(context.session.result);
    expect(state.crewSessionsByParent.get(context.session.task_id)?.verification).toEqual(context.session.verification);
    expect(state.threadIdByAgent.get('host')).toBe('host-dm');
    expect(state.notificationNavigation?.destination).toEqual({ hostId: 'host', threadId: 'room', parentId: 'parent', updated: false });
    expect(state.notifications).toBe(beforeNotifications);
    expect(state.notifications?.[0].acknowledged).toBe(false);
    expect(screen.queryByRole('button', { name: 'Retry opening context' })).toBeNull();
    expect(screen.queryByTestId('notification-accept')).toBeNull();
    expect(fetchMock.mock.calls.map(([path, init]) => ({ path, method: init.method }))).toEqual([
      { path: `/api/notifications/${context.notification_id}/context`, method: 'GET' },
    ]);
  });

  it.each([401, 404, 409, 410, 503])('retains the source view on %s and retries only a read', async (status) => {
    seedNavigation();
    fetchMock.mockImplementation(async () => new Response('{}', { status }));
    render(<NotificationCard notification={makeNotification({ id: 'a'.repeat(64) })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Context unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Retry opening context' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Context unavailable'));
    expect(fetchMock.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true);
    expect(useStore.getState().activeProfileThreadId).toBe('original-room');
  });

  it.each(['malformed', 'network', 'removed-host', 'generic'])('honestly rejects %s context without navigation', async (failure) => {
    seedNavigation();
    const context = contextFixture();
    if (failure === 'removed-host') context.thread.participants = ['removed'];
    if (failure === 'network') fetchMock.mockRejectedValue(new Error('offline'));
    else fetchMock.mockResolvedValue(new Response(JSON.stringify(failure === 'malformed'
      ? { ...context, action_url: 'https://untrusted.invalid' } : context), { status: 200 }));
    render(<NotificationCard notification={makeNotification({ id: failure === 'generic' ? 'n1' : context.notification_id })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Context unavailable'));
    expect(useStore.getState().activeProfileThreadId).toBe('original-room');
    expect(useStore.getState().chatThreads.size).toBe(0);
    if (failure === 'generic') expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each(['sequence', 'generation', 'navigation', 'away-and-back', 'unmount'])('fences pending completion on %s', async (change) => {
    seedNavigation();
    const context = contextFixture();
    let resolveContext: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(() => new Promise<Response>(resolve => { resolveContext = resolve; }));
    const view = render(<NotificationCard notification={makeNotification({ id: context.notification_id })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    expect(resolveContext).toBeTypeOf('function');
    expect(screen.getByRole('status')).toHaveTextContent('Opening room context');
    act(() => {
      if (change === 'sequence') useStore.setState({ liveSequence: 3 });
      if (change === 'generation') useStore.setState({ liveGeneration: 'c'.repeat(32) });
      if (change === 'navigation' || change === 'away-and-back') useStore.getState().openAgentProfile('elsewhere');
      if (change === 'away-and-back') useStore.getState().openGroupChatThread('original-host', 'original-room');
    });
    if (change === 'unmount') view.unmount();
    await act(async () => { resolveContext!(new Response(JSON.stringify(context), { status: 200 })); });
    expect(useStore.getState().activeProfileThreadId).toBe(change === 'sequence' ? 'room' : change === 'navigation' ? null : 'original-room');
    expect(useStore.getState().chatThreads.has('room')).toBe(change === 'sequence');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('lets a newer card activation supersede an older pending response', async () => {
    seedNavigation();
    const first = contextFixture();
    const second = contextFixture('d'.repeat(64));
    second.thread.id = 'second-room';
    second.session = { ...second.session, thread_id: 'second-room' };
    const completions = new Map<string, (response: Response) => void>();
    fetchMock.mockImplementation((path: string) => new Promise<Response>(resolve => { completions.set(path, resolve); }));
    render(<>
      <NotificationCard notification={makeNotification({ id: first.notification_id, title: 'First' })} />
      <NotificationCard notification={makeNotification({ id: second.notification_id, title: 'Second' })} />
    </>);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: First' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: Second' }));
    expect(completions.size).toBe(2);
    await act(async () => {
      completions.get(`/api/notifications/${second.notification_id}/context`)!(new Response(JSON.stringify(second)));
      completions.get(`/api/notifications/${first.notification_id}/context`)!(new Response(JSON.stringify(first)));
    });
    expect(useStore.getState().activeProfileThreadId).toBe('second-room');
    expect(useStore.getState().chatThreads.has('room')).toBe(false);
  });

  it('cancels when the mounted Bridge source hides, even if reopened before completion', async () => {
    seedNavigation();
    const context = contextFixture();
    let finish: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation(() => new Promise<Response>(resolve => { finish = resolve; }));
    const view = render(<div data-testid="bridge-source" style={{ pointerEvents: 'auto' }}>
      <NotificationCard notification={makeNotification({ id: context.notification_id })} />
    </div>);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    expect(finish).toBeTypeOf('function');
    view.rerender(<div data-testid="bridge-source" style={{ pointerEvents: 'none' }}>
      <NotificationCard notification={makeNotification({ id: context.notification_id })} />
    </div>);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('cancelled'));
    view.rerender(<div data-testid="bridge-source" style={{ pointerEvents: 'auto' }}>
      <NotificationCard notification={makeNotification({ id: context.notification_id })} />
    </div>);
    await act(async () => { finish!(new Response(JSON.stringify(context))); });
    expect(useStore.getState().activeProfileThreadId).toBe('original-room');
    expect(useStore.getState().chatThreads.size).toBe(0);
  });

  it('marks read through a separate native control without opening or accepting', () => {
    render(<NotificationCard notification={makeNotification()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Mark read' }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/n1/ack', { method: 'POST' });
  });

  it('requests governed context for the activated notification without accepting or mutating work', async () => {
    const originalState = useStore.getState();
    const notification = makeNotification({
      id: 'a'.repeat(64),
      agent_id: 'operations-officer',
      agent_type: 'crew_session',
      department: 'operations',
      notification_type: 'error',
      title: 'Crew session failed',
      detail: 'Open the existing crew room for details.',
      action_url: 'thread:failed-crew-room',
    });
    const contextPath = `/api/notifications/${notification.id}/context`;
    const ackPath = `/api/notifications/${notification.id}/ack`;
    const requests: { path: string; method: string }[] = [];
    const activated = vi.fn();
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input instanceof Request ? input.url : String(input);
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      requests.push({ path, method });
      if (path === '/api/recreation/active' && method === 'GET') {
        return new Response('{}', { status: 200 });
      }
      if (path === contextPath && method === 'GET') {
        return new Response(JSON.stringify({ detail: 'Notification context unavailable' }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (path === ackPath && method === 'POST') {
        return new Response('{}', { status: 200 });
      }
      throw new Error(`Unexpected notification request: ${method} ${path}`);
    });

    try {
      useStore.setState({
        notifications: null,
        liveGeneration: null,
        liveSequence: 0,
        activeProfileAgent: 'original-host',
        activeProfileThreadId: 'original-room',
      });
      useStore.getState().handleEvent({
        type: 'state_snapshot',
        data: {
          agents: [], connections: [], pools: [], notifications: [notification],
          system_mode: 'active', tc_n: 0, routing_entropy: 0,
        },
        timestamp: 100,
        stream: { generation: 'b'.repeat(32), sequence: 0 },
      });
      expect(useStore.getState().notifications).toEqual([notification]);
      render(<div onClickCapture={activated}><StoreNotificationCard /></div>);
      const title = screen.getByText(notification.title);
      expect(title).toBeVisible();
      expect(screen.queryByTestId('notification-accept')).toBeNull();
      requests.length = 0;

      fireEvent.click(title);

      expect(activated).toHaveBeenCalledTimes(1);
      expect(requests.filter(request => request.method !== 'GET')).toEqual(
        requests.filter(request => request.path === ackPath && request.method === 'POST'),
      );
      await waitFor(() => {
        expect(requests).toContainEqual({ path: contextPath, method: 'GET' });
      });
      expect(requests.every(request =>
        (request.path === contextPath && request.method === 'GET')
        || (request.path === ackPath && request.method === 'POST'),
      )).toBe(true);
      expect(useStore.getState().activeProfileAgent).toBe('original-host');
      expect(useStore.getState().activeProfileThreadId).toBe('original-room');
    } finally {
      cleanup();
      useStore.setState(originalState, true);
    }
  });
});
