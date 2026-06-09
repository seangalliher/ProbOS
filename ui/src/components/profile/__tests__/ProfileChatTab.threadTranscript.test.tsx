// AD-938: data-path tests for the thread-keyed transcript. The full
// ProfileChatTab is too heavy to import/render under jsdom (audio/screen deps —
// the groupsend/bf294b/metadata precedent), so the pure helpers are exercised
// via the extracted `profileTranscript` module + the presentational
// `ChatMessageRow`, and the send-path reconcile via a faithful mirror of the
// production sendText group branch. Real zustand store (BF-287 style); the
// threadApi network wrapper is mocked. HXI no-emoji guard included.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { Agent, AgentProfileMessage } from '../../../store/types';
import type { ThreadMessageDTO } from '../../sidebar/threadApi';

vi.mock('../../sidebar/threadApi', () => ({
  listMessages: vi.fn(),
}));
import { listMessages } from '../../sidebar/threadApi';
import { threadDtoToMessage, selectTranscriptMessages, loadThreadMessages } from '../profileTranscript';
import { ChatMessageRow } from '../ChatMessageRow';

// ?raw imports do not execute the module — safe to scan the heavy sources.
import profileChatSource from '../ProfileChatTab.tsx?raw';
import transcriptSource from '../profileTranscript.ts?raw';
import chatsPanelSource from '../../chats/ChatsPanel.tsx?raw';
import newChatSource from '../../chats/NewChatModal.tsx?raw';
import threadApiSource from '../../sidebar/threadApi.ts?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

function mkAgent(p: { id: string; callsign: string; department?: string }): Agent {
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
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: p.department ?? '',
  } as Agent;
}

function seedAgents(list: Agent[]): Map<string, Agent> {
  const m = new Map<string, Agent>();
  for (const a of list) m.set(a.id, a);
  useStore.setState({ agents: m });
  return m;
}

function mkDto(p: Partial<ThreadMessageDTO> & { id: string; role: string }): ThreadMessageDTO {
  return {
    thread_id: 't1',
    author_id: p.author_id ?? 'captain',
    body: p.body ?? 'hello',
    created_at: p.created_at ?? 1_700_000_000,
    ...p,
  };
}

beforeEach(() => {
  useStore.setState({ agents: new Map(), agentConversations: new Map(), threadMessages: new Map() });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('AD-938 threadDtoToMessage', () => {
  it('maps a captain message to a user bubble with no author identity', () => {
    const agents = seedAgents([]);
    const msg = threadDtoToMessage(mkDto({ id: 'm1', role: 'captain', author_id: 'captain', body: 'status?' }), agents);
    expect(msg).toMatchObject({ id: 'm1', role: 'user', text: 'status?' });
    expect(msg.authorId).toBeUndefined();
    expect(msg.callsign).toBeUndefined();
  });

  it('maps an agent message to an agent bubble with authorId + resolved callsign', () => {
    const agents = seedAgents([mkAgent({ id: 'a1', callsign: 'Aria', department: 'science' })]);
    const msg = threadDtoToMessage(mkDto({ id: 'm2', role: 'agent', author_id: 'a1', body: 'nominal' }), agents);
    expect(msg).toMatchObject({ id: 'm2', role: 'agent', text: 'nominal', authorId: 'a1', callsign: 'Aria' });
  });

  it('agent callsign is undefined when the author is not in the agents map (honest-degrade)', () => {
    const msg = threadDtoToMessage(mkDto({ id: 'm3', role: 'agent', author_id: 'ghost' }), new Map());
    expect(msg).toMatchObject({ role: 'agent', authorId: 'ghost' });
    expect(msg.callsign).toBeUndefined();
  });

  it('maps any non-captain/non-agent role to a system note', () => {
    const msg = threadDtoToMessage(mkDto({ id: 'm4', role: 'system', author_id: 'system', body: 'meeting ended' }), new Map());
    expect(msg).toMatchObject({ id: 'm4', role: 'system', text: 'meeting ended' });
    expect(msg.authorId).toBeUndefined();
  });

  it('preserves the epoch-seconds timestamp from created_at', () => {
    const msg = threadDtoToMessage(mkDto({ id: 'm5', role: 'agent', author_id: 'a1', created_at: 1_711_111_111 }), new Map());
    expect(msg.timestamp).toBe(1_711_111_111);
  });
});

describe('AD-938 selectTranscriptMessages', () => {
  const tm: AgentProfileMessage[] = [{ id: 't', role: 'agent', text: 'thread', timestamp: 0 }];
  const cm: AgentProfileMessage[] = [{ id: 'c', role: 'user', text: 'buffer', timestamp: 0 }];

  it('returns the thread messages when a thread is active', () => {
    expect(selectTranscriptMessages('t1', tm, cm)).toBe(tm);
  });

  it('returns [] in a thread context that has not loaded yet (threadMsgs undefined)', () => {
    expect(selectTranscriptMessages('t1', undefined, cm)).toEqual([]);
  });

  it('returns the per-agent buffer when no thread is active (cold 1:1)', () => {
    expect(selectTranscriptMessages(null, tm, cm)).toBe(cm);
  });

  it('returns [] when no thread and no buffer', () => {
    expect(selectTranscriptMessages(null, undefined, undefined)).toEqual([]);
  });
});

describe('AD-938 group transcript per-author avatars', () => {
  it('renders two DISTINCT avatars for two thread messages from different agents', () => {
    const agents = seedAgents([
      mkAgent({ id: 'a1', callsign: 'Aria', department: 'science' }),
      mkAgent({ id: 'a2', callsign: 'Lume', department: 'engineering' }),
    ]);
    const m1 = threadDtoToMessage(mkDto({ id: 'm1', role: 'agent', author_id: 'a1', body: 'one' }), agents);
    const m2 = threadDtoToMessage(mkDto({ id: 'm2', role: 'agent', author_id: 'a2', body: 'two' }), agents);
    render(
      <>
        <ChatMessageRow msg={m1} hostAgentId="a1" hostCallsign="Aria" />
        <ChatMessageRow msg={m2} hostAgentId="a1" hostCallsign="Aria" />
      </>,
    );
    const badges = screen.getAllByTestId('agent-avatar-badge');
    expect(badges).toHaveLength(2);
    expect(badges.map((b) => b.textContent)).toEqual(['A', 'L']);
  });
});

describe('AD-938 loadThreadMessages', () => {
  it('loads + maps the thread DTOs into the store via setThreadMessages', async () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Aria' })]);
    vi.mocked(listMessages).mockResolvedValue([
      mkDto({ id: 'm1', role: 'captain', author_id: 'captain', body: 'hi' }),
      mkDto({ id: 'm2', role: 'agent', author_id: 'a1', body: 'yo' }),
    ]);

    await loadThreadMessages('t1', useStore.getState().agents, (id, msgs) =>
      useStore.getState().setThreadMessages(id, msgs),
    );

    expect(listMessages).toHaveBeenCalledWith('t1');
    const stored = useStore.getState().threadMessages.get('t1')!;
    expect(stored.map((m) => m.role)).toEqual(['user', 'agent']);
    expect(stored[1]).toMatchObject({ role: 'agent', authorId: 'a1', callsign: 'Aria', text: 'yo' });
  });

  it('publishes [] when listMessages degrades to [] (Tier-2)', async () => {
    vi.mocked(listMessages).mockResolvedValue([]);
    await loadThreadMessages('t1', new Map(), (id, msgs) => useStore.getState().setThreadMessages(id, msgs));
    expect(useStore.getState().threadMessages.get('t1')).toEqual([]);
  });
});

describe('AD-938 group send reconcile (data path)', () => {
  // Faithful mirror of the ProfileChatTab.sendText group branch reconcile (the
  // per_agent_replies append). If that production branch changes, update this
  // mirror. Uses the REAL store appendThreadMessage.
  function reconcileGroupSend(
    threadId: string,
    displayText: string,
    replies: Array<{ agent_id?: string; callsign?: string; text?: string }>,
  ): void {
    const store = useStore.getState();
    store.appendThreadMessage(threadId, { id: 'cap-1', role: 'user', text: displayText, timestamp: 0 });
    for (const r of replies) {
      const replyText = typeof r?.text === 'string' ? r.text : '';
      if (!replyText) continue;
      store.appendThreadMessage(threadId, {
        id: `r-${r.agent_id}`,
        role: 'agent',
        text: replyText,
        timestamp: 0,
        authorId: typeof r?.agent_id === 'string' ? r.agent_id : undefined,
        callsign: typeof r?.callsign === 'string' ? r.callsign : undefined,
      });
    }
  }

  it('appends the Captain message + each per_agent_reply with no "callsign:" text prefix', () => {
    reconcileGroupSend('t1', 'team status?', [
      { agent_id: 'a1', callsign: 'Aria', text: 'science nominal' },
      { agent_id: 'a2', callsign: 'Lume', text: 'engines nominal' },
    ]);

    const msgs = useStore.getState().threadMessages.get('t1')!;
    expect(msgs).toHaveLength(3);
    expect(msgs[0]).toMatchObject({ role: 'user', text: 'team status?' });
    expect(msgs[1]).toMatchObject({ role: 'agent', authorId: 'a1', callsign: 'Aria', text: 'science nominal' });
    expect(msgs[2]).toMatchObject({ role: 'agent', authorId: 'a2', callsign: 'Lume', text: 'engines nominal' });
    // No "callsign: " prefix on the reply body (AD-936 header shows the author).
    expect(msgs[1].text).not.toMatch(/^Aria:/);
    expect(msgs[2].text).not.toMatch(/^Lume:/);
  });

  it('skips empty replies but still records the Captain message', () => {
    reconcileGroupSend('t1', 'ping', [{ agent_id: 'a1', callsign: 'Aria', text: '' }]);
    const msgs = useStore.getState().threadMessages.get('t1')!;
    expect(msgs).toHaveLength(1);
    expect(msgs[0]).toMatchObject({ role: 'user', text: 'ping' });
  });
});

describe('AD-938 HXI no-emoji guard (#3)', () => {
  it('changed sources contain no emoji', () => {
    for (const src of [profileChatSource, transcriptSource, chatsPanelSource, newChatSource, threadApiSource]) {
      expect(src).not.toMatch(EMOJI_RE);
    }
  });
});
