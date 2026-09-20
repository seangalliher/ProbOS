import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { parseContinueApprovalNotice } from '../InlineCapabilityApproval';
import { ChatMessageRow } from '../ChatMessageRow';
import { loadThreadMessages, threadDtoToMessage } from '../profileTranscript';
import CapabilityRequestPanel from '../../capability/CapabilityRequestPanel';
import { useStore } from '../../../store/useStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import type { AgentProfileMessage, CapabilityApprovalView } from '../../../store/types';

const ID = 'adb66d04-9200-4ba1-ac45-cd54f5a1d7b2';
const NO_WORK = 'I have stopped and need your approval to keep going — this turn reached its step limit before I had anything to report back. The task is still open.';
const WITH_WORK = 'I have stopped and need your approval to keep going — this turn reached its step limit with the task still open. Partial work is below.';
const TAIL = ` Approve the pending request in the Bridge and I will pick up from exactly where this stopped. (Request ${ID}.)`;
const NOTICE = NO_WORK + TAIL;
function request(overrides: Partial<CapabilityApprovalView> = {}): CapabilityApprovalView {
  return { id: ID, agent_id: 'explicit-author', kind: 'continue', target: 'finish the task', rationale: 'step limit',
    created_at: 10, work_item_id: 'linked-work', status: 'pending', decided_at: null, decided_by: '',
    decision_reason: '', can_retry_fulfilment: false, payload: {
      tool_id: 'dm_agentic', action: 'continue', params: {}, scope_key: '', session_id: null, thread_id: 'thread-a',
    }, ...overrides };
}
function message(overrides: Partial<AgentProfileMessage> = {}): AgentProfileMessage {
  return { ...threadDtoToMessage({
    id: 'canonical-message', thread_id: 'thread-a', author_id: 'explicit-author', role: 'agent',
    body: NOTICE, created_at: 10, metadata: {},
  }, new Map()), ...overrides };
}
function json(body: unknown, status = 200): Response { return new Response(JSON.stringify(body), { status }); }
async function ready(row = request()): Promise<void> {
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => json({ view: 'actionable', requests: [row] })));
  await useStore.getState().refreshPendingApprovals({ queues: ['capability'] });
  expect(useStore.getState().approvalResources.capability.status).toBe('ready');
}
function renderMessage(msg = message(), activeThreadId: string | undefined = 'thread-a'): ReturnType<typeof render> {
  return render(<ChatMessageRow msg={msg} activeThreadId={activeThreadId} hostAgentId="visual-host" hostCallsign="Host" />);
}
beforeEach(() => {
  useStore.getState().cancelPendingApprovals();
  const initial = useStore.getInitialState();
  useStore.setState({
    approvalResources: initial.approvalResources, approvalPoll: initial.approvalPoll,
    approvalControllers: { capability: null, skill: null }, approvalIssuedSeq: { capability: 0, skill: 0 },
    approvalAppliedSeq: { capability: 0, skill: 0 }, approvalRequestSeq: 0, pendingApprovals: [],
    decidedApprovals: new Set(), capabilityDecidingIds: new Set(), capabilityDecisionFeedback: new Map(),
    capabilityDecisionRevision: 0, threadMessages: new Map(),
  });
  useSettingsStore.setState({ loaded: true, loading: false, snapshot: null });
});
afterEach(() => { cleanup(); useStore.getState().cancelPendingApprovals(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('AD-1216 exact unchanged notice grammar', () => {
  it('accepts both full-ID producer forms and ignores IDs inside partial work', () => {
    expect(parseContinueApprovalNotice(NOTICE)).toBe(ID);
    expect(parseContinueApprovalNotice(WITH_WORK + TAIL + '\n\n---\nPartial\n(Request another-id.)')).toBe(ID);
  });
  it.each([
    '', ` ${NOTICE}`, `> ${NOTICE}`, `\`\`\`\n${NOTICE}\n\`\`\``, `Quoted: ${NOTICE}`,
    NOTICE + '\n', NOTICE + ' ', NOTICE + '\n\n---\npartial', NOTICE.replace(ID, ID.slice(0, 12)),
    NOTICE.replace(ID, ID.toUpperCase()), NOTICE.replace('—', '-'), NOTICE.replace('Bridge', 'chat'),
    NOTICE.replace(`(Request ${ID}.)`, `(Request ${ID}).`), WITH_WORK + TAIL,
    WITH_WORK + TAIL + '\n\n---\n', WITH_WORK + TAIL + '\n---\npartial', WITH_WORK + TAIL + '\r\n\r\n---\r\npartial',
    `An ordinary notice (Request ${ID}.)`, NOTICE.replace(ID, ID.replace(/-/g, '')),
  ])('rejects lookalike notice %s', value => expect(parseContinueApprovalNotice(value)).toBeNull());
  it('handles absent values without recognizing a notice', () => {
    expect(parseContinueApprovalNotice(null as unknown as string)).toBeNull();
    expect(parseContinueApprovalNotice(undefined as unknown as string)).toBeNull();
  });
});

describe('AD-1216 explicit canonical provenance and shared actions', () => {
  it('hydrates through the actual canonical message adapter before rendering actionable chat', async () => {
    const dto = { id: 'persisted', thread_id: 'thread-a', author_id: 'explicit-author', role: 'agent',
      body: NOTICE, created_at: 10, metadata: {} };
    const transport = vi.fn<typeof fetch>(async url => String(url).startsWith('/api/threads/')
      ? json({ messages: [dto] }) : json({ view: 'actionable', requests: [request()] }));
    vi.stubGlobal('fetch', transport);
    await useStore.getState().refreshPendingApprovals({ queues: ['capability'] });
    await loadThreadMessages('thread-a', new Map(), useStore.getState().setThreadMessages);
    const hydrated = useStore.getState().threadMessages.get('thread-a')![0];
    expect(hydrated.authorId).toBe(dto.author_id);
    expect(hydrated.threadId).toBe(dto.thread_id);
    renderMessage(hydrated);
    expect(screen.getByRole('button', { name: `Approve for request ${ID}` })).toBeEnabled();
    expect(screen.getByText(NOTICE)).toBeTruthy();
    expect(screen.getByText(/exact empty scope/)).toHaveTextContent('not a wildcard or thread-specific grant');
    expect(transport.mock.calls.some(([url]) => String(url).includes('/api/threads/thread-a/messages'))).toBe(true);
  });
  it.each([
    { role: 'user' }, { role: 'system' }, { authorId: undefined }, { authorId: '' }, { authorId: ' ' },
    { authorId: 'visual-host' }, { threadId: undefined }, { threadId: '' }, { threadId: 'other-thread' },
  ] as Partial<AgentProfileMessage>[])('keeps missing/foreign provenance text-only: %j', async changed => {
    await ready();
    renderMessage(message(changed));
    expect(screen.getByText(NOTICE)).toBeTruthy();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('does not promote the known 1:1 response mirror without threadId into authority', async () => {
    await ready();
    renderMessage(message({ threadId: undefined, authorId: 'explicit-author' }));
    expect(screen.getByText(NOTICE)).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
  it.each(['other-thread', ''])('requires the actually active thread (%s)', async active => {
    await ready(); renderMessage(message(), active);
    expect(screen.queryByRole('button')).toBeNull();
  });
  it.each([
    { agent_id: 'other-author' }, { kind: 'action' },
    { payload: { ...request().payload, tool_id: 'browser' } },
    { payload: { ...request().payload, action: 'click' } },
    { payload: { ...request().payload, scope_key: 'any' } },
    { payload: { ...request().payload, thread_id: 'other-thread' } }, { payload: null },
  ])('requires the exact current continuation tuple: %j', async changed => {
    await ready(request(changed));
    renderMessage();
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('never prefix-resolves a request ID or starts a per-message read/poller', async () => {
    await ready(request({ id: ID.slice(0, 12) }));
    const transport = vi.mocked(fetch);
    const view = render(<>{[1, 2, 3].map(id => <ChatMessageRow key={id} msg={message({ id: String(id) })}
      hostAgentId="explicit-author" hostCallsign="Host" activeThreadId="thread-a" />)}</>);
    expect(screen.queryByTestId('capability-request-card')).toBeNull();
    expect(transport).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it.each(['chat', 'panel'] as const)('reconciles a %s decision across both surfaces through the shared command', async source => {
    await ready();
    const transport = vi.fn<typeof fetch>(async (_url, init) => init?.method === 'POST'
      ? json({ request: { ...request(), status: 'fulfilled', decided_at: 20, decided_by: 'captain' }, fulfilled: true })
      : json({ view: 'actionable', requests: [request()] }));
    vi.stubGlobal('fetch', transport);
    render(<><ChatMessageRow msg={message()} activeThreadId="thread-a" hostAgentId="visual" hostCallsign="Host" />
      <CapabilityRequestPanel hosted /></>);
    expect(screen.getAllByTestId('capability-request-card')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: source === 'chat' ? `Approve for request ${ID}` : 'Approve' }));
    await waitFor(() => expect(screen.queryAllByTestId('capability-request-card')).toHaveLength(0));
    expect(useStore.getState().pendingApprovals).toHaveLength(0);
    expect(useStore.getState().capabilityDecisionRevision).toBe(1);
    expect(transport.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    expect(screen.getAllByTestId('capability-decision-feedback')).toHaveLength(2);
    expect(screen.getByText(NOTICE)).toBeTruthy();
  });
  it('keeps failed reads unknown and actionless, then retires on authoritative absence', async () => {
    await ready();
    renderMessage();
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => json({}, 503)));
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    await act(async () => useStore.getState().refreshPendingApprovals({ queues: ['capability'] }));
    expect(screen.getByRole('button', { name: `Approve for request ${ID}` })).toBeDisabled();
    expect(screen.getByText(/Request state is unknown or stale/)).toBeTruthy();
    expect(screen.queryByText('No longer actionable.')).toBeNull();
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => json({ view: 'actionable', requests: [] })));
    await act(async () => useStore.getState().refreshPendingApprovals({ queues: ['capability'] }));
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('No longer actionable.');
    expect(screen.getByText(NOTICE)).toBeTruthy();
  });
});
