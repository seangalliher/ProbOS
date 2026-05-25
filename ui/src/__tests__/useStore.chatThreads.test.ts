/**
 * AD-791a vitest #12 — useStore.chatThreads hydration.
 *
 * Asserts the new state slices added by AD-791a:
 *   - ``chatThreads: Map<thread_id, AD791aChatThreadView>`` is hydrated
 *     from a /api/threads payload via ``hydrateChatThreads``.
 *   - ``setChatThread`` upserts a single thread without wiping the rest
 *     of the map.
 *   - ``setActiveThread`` mutates ``activeThreadId``.
 *   - Existing ``agentConversations`` slice continues to behave
 *     identically (no regression — the additions are purely additive).
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore, type AD791aChatThreadView } from '../store/useStore';

function makeThread(id: string, title = id): AD791aChatThreadView {
  return {
    id,
    title,
    participants: ['agent-' + id],
    created_at: 1000,
    last_active_at: 1000,
    pinned: false,
    archived: false,
    metadata: { is_default: true },
  };
}

beforeEach(() => {
  useStore.setState({
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    activeThreadId: null,
    agentConversations: new Map(),
  });
});

describe('AD-791a useStore.chatThreads slice', () => {
  it('hydrateChatThreads populates the chatThreads map keyed by id', () => {
    const payload = [makeThread('t1', 'Ezri'), makeThread('t2', 'Worf')];
    useStore.getState().hydrateChatThreads(payload);

    const map = useStore.getState().chatThreads;
    expect(map.size).toBe(2);
    expect(map.get('t1')?.title).toBe('Ezri');
    expect(map.get('t2')?.title).toBe('Worf');
  });

  it('setChatThread upserts without clearing existing entries', () => {
    useStore.getState().hydrateChatThreads([makeThread('t1', 'Ezri')]);
    useStore.getState().setChatThread(makeThread('t2', 'Worf'));

    const map = useStore.getState().chatThreads;
    expect(map.size).toBe(2);
    expect(map.get('t1')?.title).toBe('Ezri');
    expect(map.get('t2')?.title).toBe('Worf');

    // Update an existing entry — title swap propagates without wiping
    // siblings.
    useStore.getState().setChatThread({ ...makeThread('t1', 'Ezri Dax') });
    expect(useStore.getState().chatThreads.get('t1')?.title).toBe('Ezri Dax');
    expect(useStore.getState().chatThreads.size).toBe(2);
  });

  it('setActiveThread updates activeThreadId; null clears selection', () => {
    expect(useStore.getState().activeThreadId).toBeNull();
    useStore.getState().setActiveThread('t1');
    expect(useStore.getState().activeThreadId).toBe('t1');
    useStore.getState().setActiveThread(null);
    expect(useStore.getState().activeThreadId).toBeNull();
  });

  it('setThreadForAgent populates threadIdByAgent and survives hydration calls', () => {
    useStore.getState().setThreadForAgent('agent-ezri', 'thread-1');
    useStore.getState().setThreadForAgent('agent-worf', 'thread-2');
    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-1');
    expect(useStore.getState().threadIdByAgent.get('agent-worf')).toBe('thread-2');

    // ``hydrateChatThreads`` must not clear the agent→thread mapping.
    useStore.getState().hydrateChatThreads([makeThread('t-foo')]);
    expect(useStore.getState().threadIdByAgent.get('agent-ezri')).toBe('thread-1');
  });

  it('does NOT regress agentConversations — adding a thread leaves it untouched', () => {
    // Pre-populate the existing slice via the legacy addAgentMessage path.
    useStore.getState().addAgentMessage('agent-ezri', 'user', 'hi');
    expect(useStore.getState().agentConversations.get('agent-ezri')?.messages.length).toBe(1);

    useStore.getState().hydrateChatThreads([makeThread('t1')]);
    useStore.getState().setActiveThread('t1');

    // agentConversations still has the seeded message — additive slices
    // are isolated from the legacy data model.
    expect(useStore.getState().agentConversations.get('agent-ezri')?.messages.length).toBe(1);
  });
});
