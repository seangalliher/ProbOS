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
import {
  threadDtoToMessage, selectTranscriptMessages, loadThreadMessages,
  buildTranscriptItems, transcriptDayLabel, TRANSCRIPT_RENDER_CAP, type TranscriptItem,
  createSpeechLedger, admitMessages, isSpeakableAgentMessage, speechKeyFor,
  SPEECH_SCOPE_CAP,
} from '../profileTranscript';
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

describe('BF-718 speech ledger', () => {
  const agentMsg = (text: string, authorId = 'a1'): AgentProfileMessage => (
    { id: `${text}-${Math.random()}`, role: 'agent', text, timestamp: 0, authorId }
  );

  it('admits a message once and never again, whatever id it carries', () => {
    const ledger = createSpeechLedger();
    const first = admitMessages(ledger, 's', [agentMsg('hello')], { seed: false });
    const second = admitMessages(ledger, 's', [agentMsg('hello')], { seed: false });
    expect(first.map((m) => m.text)).toEqual(['hello']);
    expect(second).toEqual([]);
  });

  it('records without admitting when seeding', () => {
    const ledger = createSpeechLedger();
    expect(admitMessages(ledger, 's', [agentMsg('history')], { seed: true })).toEqual([]);
    // Seeded content stays silent when it reappears in a later live pass.
    expect(admitMessages(ledger, 's', [agentMsg('history')], { seed: false })).toEqual([]);
  });

  it('keeps scopes independent, so one thread cannot silence another', () => {
    const ledger = createSpeechLedger();
    admitMessages(ledger, 'thread-a', [agentMsg('same words')], { seed: false });
    const other = admitMessages(ledger, 'thread-b', [agentMsg('same words')], { seed: false });
    expect(other.map((m) => m.text)).toEqual(['same words']);
  });

  it('distinguishes identical text from different authors', () => {
    const ledger = createSpeechLedger();
    admitMessages(ledger, 's', [agentMsg('acknowledged', 'a1')], { seed: false });
    const peer = admitMessages(ledger, 's', [agentMsg('acknowledged', 'a2')], { seed: false });
    expect(peer.map((m) => m.authorId)).toEqual(['a2']);
  });

  it('evicts oldest first past the cap, and bounds the scope', () => {
    const ledger = createSpeechLedger();
    const filler = Array.from({ length: SPEECH_SCOPE_CAP }, (_, i) => agentMsg(`m${i}`));
    admitMessages(ledger, 's', filler, { seed: true });
    expect(ledger.scopes.get('s')?.size).toBe(SPEECH_SCOPE_CAP);

    admitMessages(ledger, 's', [agentMsg('newest')], { seed: true });
    expect(ledger.scopes.get('s')?.size).toBe(SPEECH_SCOPE_CAP);
    // m0 was evicted, so it is speakable again; the newest entry is not.
    expect(admitMessages(ledger, 's', [agentMsg('m0')], { seed: false }).length).toBe(1);
    expect(admitMessages(ledger, 's', [agentMsg('newest')], { seed: false })).toEqual([]);
  });

  it('never admits a non-agent message', () => {
    const ledger = createSpeechLedger();
    const captain: AgentProfileMessage = { id: 'c', role: 'user', text: 'hi', timestamp: 0 };
    expect(admitMessages(ledger, 's', [captain], { seed: false })).toEqual([]);
    expect(isSpeakableAgentMessage(captain)).toBe(false);
  });

  it('rejects placeholders and blank text, and accepts ordinary prose', () => {
    expect(isSpeakableAgentMessage(agentMsg('(no response)'))).toBe(false);
    expect(isSpeakableAgentMessage(agentMsg('  (error: timeout)  '))).toBe(false);
    expect(isSpeakableAgentMessage(agentMsg('   '))).toBe(false);
    expect(isSpeakableAgentMessage(agentMsg('A perfectly ordinary reply.'))).toBe(true);
  });

  it('keys on trimmed text, so whitespace drift is not a second utterance', () => {
    expect(speechKeyFor({ role: 'agent', authorId: 'a1', text: ' hello ' }))
      .toBe(speechKeyFor({ role: 'agent', authorId: 'a1', text: 'hello' }));
  });

  it('does not let the Captain\u2019s own words claim the agent\u2019s identical reply', () => {
    // The default author is applied to EVERY row, so without role in the key a
    // Captain message "Echo me" claims the agent's reply of the same text and
    // the reply goes silent.
    const ledger = createSpeechLedger();
    const captain: AgentProfileMessage = { id: 'c', role: 'user', text: 'Echo me', timestamp: 0 };
    const reply: AgentProfileMessage = { id: 'a', role: 'agent', text: 'Echo me', timestamp: 0 };

    admitMessages(ledger, 's', [captain], { seed: false, defaultAuthorId: 'ezri' });
    const spoken = admitMessages(ledger, 's', [reply], { seed: false, defaultAuthorId: 'ezri' });

    expect(spoken.map((m) => m.text)).toEqual(['Echo me']);
  });
});

describe('AD-1056 buildTranscriptItems', () => {
  // Local-time anchor (no TZ designator => parsed as local), so day bucketing is
  // timezone-independent: every date below is built in the SAME local frame.
  const NOW = new Date('2026-06-27T12:00:00').getTime();
  const sec = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);
  const mkMsg = (id: string, timestamp: number, text = 'hi'): AgentProfileMessage =>
    ({ id, role: 'agent', text, timestamp });
  const msgItems = (its: TranscriptItem[]) =>
    its.filter((i): i is Extract<TranscriptItem, { kind: 'msg' }> => i.kind === 'msg');
  const dayItems = (its: TranscriptItem[]) =>
    its.filter((i): i is Extract<TranscriptItem, { kind: 'day' }> => i.kind === 'day');

  it('returns [] for no messages', () => {
    expect(buildTranscriptItems([], { nowMs: NOW })).toEqual([]);
  });

  it('inserts ONE day separator before a single-day run', () => {
    const items = buildTranscriptItems([
      mkMsg('m1', sec('2026-06-27T09:00:00')),
      mkMsg('m2', sec('2026-06-27T10:00:00')),
    ], { nowMs: NOW });
    expect(items.map(i => i.kind)).toEqual(['day', 'msg', 'msg']);
    expect(items[0]).toMatchObject({ kind: 'day', label: 'Today' });
  });

  it('inserts a separator at each LOCAL-day boundary', () => {
    const items = buildTranscriptItems([
      mkMsg('m1', sec('2026-06-25T09:00:00')),
      mkMsg('m2', sec('2026-06-26T10:00:00')),
      mkMsg('m3', sec('2026-06-27T11:00:00')),
    ], { nowMs: NOW });
    expect(items.map(i => i.kind)).toEqual(['day', 'msg', 'day', 'msg', 'day', 'msg']);
    const labels = dayItems(items).map(i => i.label);
    expect(labels[1]).toBe('Yesterday');
    expect(labels[2]).toBe('Today');
  });

  it('labels Today / Yesterday / an explicit date for older days', () => {
    expect(transcriptDayLabel(sec('2026-06-27T01:00:00'), NOW)).toBe('Today');
    expect(transcriptDayLabel(sec('2026-06-26T23:00:00'), NOW)).toBe('Yesterday');
    const older = transcriptDayLabel(sec('2026-06-20T08:00:00'), NOW);
    expect(older).not.toBe('Today');
    expect(older).not.toBe('Yesterday');
    expect(older.length).toBeGreaterThan(0);
  });

  it('caps to the most recent ``cap`` messages (newest kept)', () => {
    const base = sec('2026-06-27T00:00:00');
    const msgs = Array.from({ length: 250 }, (_, i) => mkMsg(`m${i}`, base + i * 60));
    const rendered = msgItems(buildTranscriptItems(msgs, { nowMs: NOW, cap: 50 }));
    expect(rendered).toHaveLength(50);
    expect(rendered[0].msg.id).toBe('m200');   // the last 50 of 250
    expect(rendered[49].msg.id).toBe('m249');
  });

  it('cap=0 disables the cap (renders all)', () => {
    const base = sec('2026-06-27T00:00:00');
    const msgs = Array.from({ length: 5 }, (_, i) => mkMsg(`m${i}`, base + i * 60));
    expect(msgItems(buildTranscriptItems(msgs, { nowMs: NOW, cap: 0 }))).toHaveLength(5);
  });

  it('defaults to TRANSCRIPT_RENDER_CAP when no cap is given', () => {
    const base = sec('2026-06-27T00:00:00');
    const msgs = Array.from({ length: TRANSCRIPT_RENDER_CAP + 10 }, (_, i) => mkMsg(`m${i}`, base + i * 60));
    expect(msgItems(buildTranscriptItems(msgs, { nowMs: NOW }))).toHaveLength(TRANSCRIPT_RENDER_CAP);
  });

  it('does not force a separator for a message with no/invalid timestamp', () => {
    const items = buildTranscriptItems([
      mkMsg('m1', 0),
      mkMsg('m2', sec('2026-06-27T10:00:00')),
    ], { nowMs: NOW });
    expect(items.map(i => i.kind)).toEqual(['msg', 'day', 'msg']);
  });

  it('day separator ids are unique + stable', () => {
    const items = buildTranscriptItems([
      mkMsg('m1', sec('2026-06-26T09:00:00')),
      mkMsg('m2', sec('2026-06-27T11:00:00')),
    ], { nowMs: NOW });
    const dayIds = dayItems(items).map(i => i.id);
    expect(new Set(dayIds).size).toBe(dayIds.length);
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

describe('AD-1133 live transcript repair wiring', () => {
  it('uses the strict repair outcome and existing DTO mapper', () => {
    expect(profileChatSource).toContain('repairThreadMessages(targetThreadId)');
    expect(profileChatSource).toContain('threadDtoToMessage(message, current.agents)');
    expect(profileChatSource).toContain('message.id === triggerMessageId');
  });

  it('drops stale room and stream results before replacing messages', () => {
    expect(profileChatSource).toContain('currentOwner.threadId !== targetThreadId');
    expect(profileChatSource).toContain('current.liveGeneration !== generation');
    // BF-720: the room and the stream AUTHORITY are what make a result stale.
    // This assertion also used to pin ``current.liveSequence !== sequence``,
    // and that pin held the defect in place: a sequence advance within the same
    // generation means only that another frame arrived, which one always does
    // at the moment a work item finishes and its report is promoted. It
    // discarded a fetched-and-correct transcript and left a promoted report
    // invisible for 17.5 minutes (#1159). Ordering between two refreshes of one
    // thread is enforced by ``requestId`` + ``transcriptInFlightRef`` instead.
    expect(profileChatSource).not.toContain('current.liveSequence !== sequence');
  });
});

describe('AD-1056/1057 transcript layout + scroll guards', () => {
  it('AD-1056: renders day separators via buildTranscriptItems', () => {
    expect(profileChatSource).toMatch(/buildTranscriptItems\(messages\)/);
    expect(profileChatSource).toMatch(/<DaySeparator\b/);
    expect(profileChatSource).toMatch(/data-testid="chat-day-separator"/);
  });

  it('AD-1056: snaps instantly on bulk load, animates only incremental messages', () => {
    // Bulk load / context switch jumps with NO animation...
    expect(profileChatSource).toMatch(/el\.scrollTop = el\.scrollHeight/);
    expect(profileChatSource).toMatch(/behavior: 'auto'/);
    // ...the incremental-follow path still smooth-scrolls.
    expect(profileChatSource).toMatch(/behavior: 'smooth'/);
    // The disorienting unconditional smooth-on-every-length-change effect is gone.
    expect(profileChatSource).not.toMatch(/Auto-scroll on new messages/);
  });

  it('AD-1057: transcript + input are flex-anchored so the input never floats up', () => {
    // minHeight:0 lets the scroll container overflow-scroll instead of growing
    // the column; flexShrink:0 keeps the input row pinned to the bottom.
    expect(profileChatSource).toMatch(/minHeight: 0/);
    expect(profileChatSource).toMatch(/flexShrink: 0/);
  });
});

describe('AD-1058 call-control wiring', () => {
  it('renders the CallMenu in a top bar for a 1:1 crew chat', () => {
    expect(profileChatSource).toMatch(/<CallMenu\b/);
    expect(profileChatSource).toMatch(/data-testid="chat-call-bar"/);
    expect(profileChatSource).toMatch(/showCallMenu = .*isCrew.*meetingParticipantIds\.length < 2/);
  });

  it('starts a call by ensuring the canonical 1:1 thread (no message first)', () => {
    expect(profileChatSource).toMatch(/getOrCreateAgentThread\(agentId\)/);
    expect(profileChatSource).toMatch(/setMeetingActive\(tid, true\)/);
    // a video call also starts the shared camera; audio call does not.
    expect(profileChatSource).toMatch(/if \(video\) void startCameraStream\(\)/);
  });
});
