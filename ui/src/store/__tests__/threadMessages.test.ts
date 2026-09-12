// AD-938: tests for the thread-keyed display-transcript store slice
// (threadMessages + setThreadMessages/appendThreadMessage). Real zustand store
// via useStore.getState()/setState (BF-287 real-fixture style, no MagicMock).
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { useStore } from '../useStore';
import type { AgentProfileMessage } from '../types';

function mkMsg(id: string, role: AgentProfileMessage['role'] = 'agent'): AgentProfileMessage {
  return { id, role, text: id, timestamp: 1_700_000_000 };
}

afterEach(() => {
  useStore.setState({ threadMessages: new Map() });
});

describe('group reply memory', () => {
  const initialConversations = useStore.getState().agentConversations;
  const initialProfile = useStore.getState().activeProfileAgent;
  const row = (id = 'reply', threadId = 't1'): AgentProfileMessage => ({
    id, threadId, role: 'agent', authorId: 'crew', callsign: 'Crew',
    text: 'same words', timestamp: 42, metadata: { fanout: 'ad914', emotion: 'calm' },
    emotion: 'calm',
  });
  const mirror = (message: AgentProfileMessage): void => {
    useStore.getState().addAgentMessage('host', 'agent', message.text, { message });
  };
  beforeEach(() => {
    useStore.setState({ agentConversations: new Map(), activeProfileAgent: null });
  });
  afterEach(() => {
    useStore.setState({ agentConversations: initialConversations, activeProfileAgent: initialProfile });
  });

  it('preserves memory fields and leaves retained identity replay and unread count unchanged', () => {
    mirror(row());
    const before = useStore.getState().agentConversations;
    expect(before.get('host')?.messages).toEqual([row()]);
    expect(before.get('host')?.unreadCount).toBe(1);
    mirror(row());
    expect(useStore.getState().agentConversations).toBe(before);
  });

  it('keeps same prose with distinct IDs and the same ID from distinct threads in memory', () => {
    mirror(row());
    mirror(row('other'));
    mirror(row('reply', 't2'));
    expect(useStore.getState().agentConversations.get('host')?.messages)
      .toEqual([row(), row('other'), row('reply', 't2')]);
    expect(useStore.getState().agentConversations.get('host')?.unreadCount).toBe(3);
  });

  it('deduplicates memory before the 100-row cap without moving retained identities', () => {
    const messages = Array.from({ length: 101 }, (_, index) => row(`reply-${index}`));
    for (const message of messages.slice(0, 100)) mirror(message);
    const before = useStore.getState().agentConversations;
    mirror(messages[0]);
    expect(useStore.getState().agentConversations).toBe(before);
    mirror(messages[100]);
    expect(useStore.getState().agentConversations.get('host')?.messages).toEqual(messages.slice(1));
    expect(useStore.getState().agentConversations.get('host')?.unreadCount).toBe(101);
  });

  it.each([
    { id: '' }, { id: ' padded ' }, { id: 'bad\nidentity' }, { id: 'x'.repeat(129) },
    { threadId: undefined }, { threadId: '' }, { authorId: '' }, { authorId: undefined },
    { text: '' }, { text: ' ' }, { timestamp: NaN }, { timestamp: Infinity }, { timestamp: -1 },
    { role: 'user' }, { optimistic: true }, { metadata: [] }, { metadata: 'invalid' },
  ])('rejects invalid memory input without mutation: %j', (invalid) => {
    const before = useStore.getState().agentConversations;
    mirror({ ...row(), ...invalid } as AgentProfileMessage);
    expect(useStore.getState().agentConversations).toBe(before);
  });

  it('rejects null memory rows and mismatched call arguments without mutation', () => {
    const store = useStore.getState();
    const before = store.agentConversations;
    store.addAgentMessage('host', 'agent', 'same words', { message: null as unknown as AgentProfileMessage });
    store.addAgentMessage('', 'agent', 'same words', { message: row() });
    store.addAgentMessage('host', 'user', 'same words', { message: row() });
    store.addAgentMessage('host', 'agent', 'different words', { message: row() });
    store.addAgentMessage('host', 'agent', 'same words', { message: row(), authorId: 'other' });
    expect(useStore.getState().agentConversations).toBe(before);
  });

  it.each([undefined, null])('accepts memory without metadata: %j', (metadata) => {
    const message = { ...row(), metadata };
    useStore.setState({ activeProfileAgent: 'host' });
    mirror(message);
    expect(useStore.getState().agentConversations.get('host')?.messages).toEqual([message]);
    expect(useStore.getState().agentConversations.get('host')?.unreadCount).toBe(0);
  });

  it('reuses transient request identity without claiming persistence', () => {
    const message = { ...row('transient:request-reply'), metadata: undefined };
    mirror(message);
    mirror(message);
    expect(useStore.getState().agentConversations.get('host')?.messages).toEqual([message]);
  });

  it('preserves no-options legacy memory and author-only options without prose deduplication', () => {
    const store = useStore.getState();
    store.addAgentMessage('host', 'agent', 'same words');
    store.addAgentMessage('host', 'agent', 'same words');
    store.addAgentMessage('host', 'agent', 'same words', { authorId: 'crew', callsign: 'Crew' });
    const messages = useStore.getState().agentConversations.get('host')!.messages;
    expect(messages).toHaveLength(3);
    expect(new Set(messages.map(message => message.id)).size).toBe(3);
    for (const message of messages) {
      expect(message.id).not.toMatch(/^transient:/);
      expect(message.threadId).toBeUndefined();
      expect(message.timestamp).toBeGreaterThan(0);
    }
    expect(Object.keys(messages[0]).sort()).toEqual(['id', 'role', 'text', 'timestamp']);
    expect(messages[2]).toMatchObject({ authorId: 'crew', callsign: 'Crew' });
    expect(useStore.getState().agentConversations.get('host')?.unreadCount).toBe(3);
  });
});

describe('thread reply reconciliation', () => {
  const row = (id: string, timestamp = 42): AgentProfileMessage => ({
    id, threadId: 't1', role: 'agent', authorId: 'a1', text: 'same words', timestamp,
  });

  it('seeds an empty thread and reconciles repeated identity without moving timestamp ties', () => {
    const store = useStore.getState();
    expect(store.reconcileThreadMessage('t1', row('first'))).toBe(true);
    expect(store.reconcileThreadMessage('t1', row('second'))).toBe(true);
    expect(store.reconcileThreadMessage('t1', { ...row('first'), text: 'canonical update' })).toBe(false);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([
      { ...row('first'), text: 'canonical update' }, row('second'),
    ]);
  });

  it('deduplicates before the cap and does not let an older receipt evict a newer row', () => {
    const store = useStore.getState();
    const messages = Array.from({ length: 200 }, (_, index) => row(`row-${index}`, index + 1));
    store.setThreadMessages('t1', [...messages, messages[199]]);
    expect(store.reconcileThreadMessage('t1', messages[199])).toBe(false);
    expect(useStore.getState().threadMessages.get('t1')).toEqual(messages);
    expect(store.reconcileThreadMessage('t1', row('old', 0))).toBe(false);
    expect(useStore.getState().threadMessages.get('t1')).toEqual(messages);
  });

  it('orders delayed receipts chronologically without changing timestamps or another room', () => {
    const store = useStore.getState();
    store.setThreadMessages('t2', [mkMsg('unrelated')]);
    store.reconcileThreadMessage('t1', row('new', 20));
    store.reconcileThreadMessage('t1', row('older', 10));
    expect(useStore.getState().threadMessages.get('t1')).toEqual([row('older', 10), row('new', 20)]);
    expect(useStore.getState().threadMessages.get('t2')).toEqual([mkMsg('unrelated')]);
  });

  it.each([
    { id: '' }, { threadId: 'other' }, { text: '' }, { authorId: '' },
    { timestamp: NaN }, { timestamp: -1 },
  ])('rejects invalid rows without mutation: %j', (invalid) => {
    const before = useStore.getState().threadMessages;
    expect(useStore.getState().reconcileThreadMessage('t1', { ...row('reply'), ...invalid })).toBe(false);
    expect(useStore.getState().threadMessages).toBe(before);
  });

  it('rejects an empty thread identity', () => {
    expect(useStore.getState().reconcileThreadMessage('', { ...row('reply'), threadId: '' })).toBe(false);
    expect(useStore.getState().threadMessages.size).toBe(0);
  });

  it('correlates only the exact Captain token and retains distinct identical sends', () => {
    const store = useStore.getState();
    const captain = (id: string, token: unknown, optimistic = true): AgentProfileMessage => ({
      id, threadId: 't1', role: 'user', authorId: 'captain', text: 'same words',
      timestamp: 42, optimistic, metadata: { client_message_id: token },
    });
    store.setThreadMessages('t1', [captain('pending-one', 'one'), captain('pending-two', 'two')]);
    store.reconcileThreadMessage('t1', captain('canonical-one', 'one', false));
    expect(useStore.getState().threadMessages.get('t1')?.map(message => message.id))
      .toEqual(['pending-two', 'canonical-one']);
    store.reconcileThreadMessage('t1', captain('canonical-two', 'two', false));
    expect(useStore.getState().threadMessages.get('t1')?.map(message => message.id))
      .toEqual(['canonical-one', 'canonical-two']);
  });

  it.each([null, undefined, '', ' ', 12, {}])('does not correlate invalid tokens: %j', (token) => {
    const pending: AgentProfileMessage = {
      ...row('pending'), role: 'user', authorId: 'captain', optimistic: true,
      metadata: { client_message_id: token },
    };
    useStore.getState().setThreadMessages('t1', [pending]);
    useStore.getState().reconcileThreadMessage('t1', { ...pending, id: 'canonical', optimistic: false });
    expect(useStore.getState().threadMessages.get('t1')).toHaveLength(2);
  });

  it('does not correlate another role, author, or room', () => {
    const pending: AgentProfileMessage = {
      ...row('pending'), role: 'user', authorId: 'captain', optimistic: true,
      metadata: { client_message_id: 'token' },
    };
    const store = useStore.getState();
    store.setThreadMessages('t1', [pending]);
    store.reconcileThreadMessage('t1', { ...pending, id: 'agent', optimistic: false, role: 'agent' });
    store.reconcileThreadMessage('t1', { ...pending, id: 'other-author', optimistic: false, authorId: 'other' });
    store.reconcileThreadMessage('t2', { ...pending, id: 'other-room', optimistic: false, threadId: 't2' });
    expect(useStore.getState().threadMessages.get('t1')?.[0]).toEqual(pending);
    expect(useStore.getState().threadMessages.get('t1')).toHaveLength(3);
  });

  it('prefers authoritative snapshot collisions while retaining new local identities in tie order', () => {
    const store = useStore.getState();
    store.setThreadMessages('t1', [row('removed'), row('first'), row('second')]);
    const baseline = useStore.getState().threadMessages.get('t1')!;
    store.reconcileThreadMessage('t1', { ...row('first'), text: 'new receipt' });
    store.reconcileThreadMessage('t1', row('new'));
    expect(useStore.getState().threadMessages.get('t1')?.find(message => message.id === 'first')?.text)
      .toBe('new receipt');
    const canonical = { ...row('first'), text: 'server normalized body', metadata: { canonical: true } };
    store.setThreadMessages('t1', [row('second'), canonical], baseline);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([
      row('second'), canonical, row('new'),
    ]);
  });

  it('does not resurrect evicted rows from a launch baseline or union subsequent snapshots', () => {
    const store = useStore.getState();
    const messages = Array.from({ length: 200 }, (_, index) => row(`row-${index}`, index + 1));
    store.setThreadMessages('t1', messages);
    const baseline = useStore.getState().threadMessages.get('t1')!;
    store.reconcileThreadMessage('t1', row('new', 201));
    store.setThreadMessages('t1', messages, baseline);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([...messages.slice(1), row('new', 201)]);
    store.reconcileThreadMessage('t1', row('old', 0));
    expect(useStore.getState().threadMessages.get('t1')).toHaveLength(200);
    const nextBaseline = useStore.getState().threadMessages.get('t1')!;
    store.setThreadMessages('t1', [], nextBaseline);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([]);
  });

  it('preserves arrivals into an initially empty snapshot', () => {
    useStore.getState().reconcileThreadMessage('t1', row('new'));
    useStore.getState().setThreadMessages('t1', [], []);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([row('new')]);
  });

  it.each(['solo', 'transient-group'])('retains identity-bearing arrivals without preserving uncorrelated legacy mirrors: %s', (mode) => {
    const store = useStore.getState();
    const canonical = row('saved-reply');
    const legacy = mode === 'solo'
      ? { id: 'local-reply', role: 'agent' as const, text: canonical.text, timestamp: 43 }
      : { ...row('transient:local-reply', 43) };
    store.appendThreadMessage('t1', legacy);
    store.setThreadMessages('t1', [canonical]);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([canonical]);
    store.setThreadMessages('t1', []);
    const baseline = useStore.getState().threadMessages.get('t1')!;
    store.appendThreadMessage('t1', legacy);
    store.reconcileThreadMessage('t1', row('new-canonical', 44));
    expect(useStore.getState().threadMessages.get('t1')?.some(message => message.id === legacy.id)).toBe(true);
    store.setThreadMessages('t1', [canonical], baseline);
    expect(useStore.getState().threadMessages.get('t1')).toEqual([canonical, row('new-canonical', 44)]);
  });

  it('rejects null and invalid boundary inputs without mutation', () => {
    const store = useStore.getState();
    const before = store.threadMessages;
    expect(store.reconcileThreadMessage(null as unknown as string, row('new'))).toBe(false);
    expect(store.reconcileThreadMessage('t1', null as unknown as AgentProfileMessage)).toBe(false);
    store.setThreadMessages('t1', null as unknown as AgentProfileMessage[]);
    store.setThreadMessages('', []);
    store.setThreadMessages('t1', [], null as unknown as AgentProfileMessage[]);
    expect(useStore.getState().threadMessages).toBe(before);
  });
});

describe('AD-938 threadMessages store slice', () => {
  it('boots with an empty threadMessages map', () => {
    expect(useStore.getState().threadMessages).toBeInstanceOf(Map);
    expect(useStore.getState().threadMessages.size).toBe(0);
  });

  it('setThreadMessages sets a thread list and replaces it on a second call (immutable Map)', () => {
    const before = useStore.getState().threadMessages;
    useStore.getState().setThreadMessages('t1', [mkMsg('a'), mkMsg('b')]);
    const after = useStore.getState().threadMessages;
    expect(after).not.toBe(before); // new Map reference (reactive update)
    expect(after.get('t1')?.map((m) => m.id)).toEqual(['a', 'b']);

    useStore.getState().setThreadMessages('t1', [mkMsg('c')]);
    expect(useStore.getState().threadMessages.get('t1')?.map((m) => m.id)).toEqual(['c']);
  });

  it('setThreadMessages keeps other threads isolated', () => {
    useStore.getState().setThreadMessages('t1', [mkMsg('a')]);
    useStore.getState().setThreadMessages('t2', [mkMsg('b')]);
    expect(useStore.getState().threadMessages.get('t1')?.[0].id).toBe('a');
    expect(useStore.getState().threadMessages.get('t2')?.[0].id).toBe('b');
  });

  it('appendThreadMessage appends to an existing list (and seeds an empty one)', () => {
    useStore.getState().appendThreadMessage('t1', mkMsg('a'));
    useStore.getState().appendThreadMessage('t1', mkMsg('b'));
    expect(useStore.getState().threadMessages.get('t1')?.map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('appendThreadMessage caps the list to the last 200 messages', () => {
    for (let i = 0; i < 250; i++) {
      useStore.getState().appendThreadMessage('t1', mkMsg(`m${i}`));
    }
    const list = useStore.getState().threadMessages.get('t1')!;
    expect(list).toHaveLength(200);
    expect(list[0].id).toBe('m50');   // oldest retained
    expect(list[199].id).toBe('m249'); // newest
  });
});
