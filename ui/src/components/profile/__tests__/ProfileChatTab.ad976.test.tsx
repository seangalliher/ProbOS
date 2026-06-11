// AD-976: meeting-mode text follows the voice. In an audio-on meeting the
// Captain should not see a reply's TEXT until its agent begins SPEAKING. The
// full ProfileChatTab is too heavy to render (audio/screen deps) — same
// rationale as ProfileChatTab.groupsend.test.tsx — so the AD-976 reveal logic
// is exercised through a FAITHFUL MIRROR of the production branch in
// ProfileChatTab.sendText + the speakingAgentId effect. If that production
// logic changes, update this mirror.
import { describe, it, expect } from 'vitest';

type Reply = { agent_id?: unknown; callsign?: string; text?: string };

// --- Mirror 1: the reveal-mode decision (ProfileChatTab.sendText group branch).
// audio-on meeting -> speech-synced staging; text chat OR muted meeting ->
// the AD-960 progressive reveal.
function decideRevealMode(meetingActive: boolean, callAudioEnabled: boolean): 'speech-synced' | 'progressive' {
  return meetingActive && callAudioEnabled ? 'speech-synced' : 'progressive';
}

// --- Mirror 2: staging (pendingMeetingRepliesRef). Keyed by agent_id; entries
// with a non-string/empty agent_id are dropped.
function stageReplies(replies: Reply[]): Map<string, Reply> {
  return new Map(
    replies
      .filter((r) => typeof r?.agent_id === 'string' && r.agent_id)
      .map((r) => [r.agent_id as string, r]),
  );
}

// --- Mirror 3: the speakingAgentId effect. Reveal each agent's staged reply
// exactly once, when (and only when) that agent starts speaking.
function makeSpeakReveal(staged: Map<string, Reply>) {
  const revealed = new Set<string>();
  const appended: Reply[] = [];
  function onSpeaking(agentId: string | null): void {
    if (!agentId) return;
    const reply = staged.get(agentId);
    if (!reply) return;
    if (revealed.has(agentId)) return;
    revealed.add(agentId);
    appended.push(reply);
  }
  return { onSpeaking, appended };
}

describe('AD-976 meeting-mode reveal mode decision', () => {
  it('audio-on meeting -> speech-synced reveal', () => {
    expect(decideRevealMode(true, true)).toBe('speech-synced');
  });
  it('muted meeting -> progressive reveal (fallback)', () => {
    expect(decideRevealMode(true, false)).toBe('progressive');
  });
  it('text chat (not a meeting) -> progressive reveal', () => {
    expect(decideRevealMode(false, true)).toBe('progressive');
    expect(decideRevealMode(false, false)).toBe('progressive');
  });
});

describe('AD-976 staging', () => {
  it('keys staged replies by agent_id', () => {
    const staged = stageReplies([
      { agent_id: 'a1', text: 'one' },
      { agent_id: 'a2', text: 'two' },
    ]);
    expect(staged.size).toBe(2);
    expect(staged.get('a1')?.text).toBe('one');
  });
  it('drops replies with a missing/blank agent_id', () => {
    const staged = stageReplies([
      { agent_id: '', text: 'blank' },
      { agent_id: 42 as unknown, text: 'num' },
      { agent_id: 'a1', text: 'ok' },
    ]);
    expect(staged.size).toBe(1);
    expect(staged.get('a1')?.text).toBe('ok');
  });
});

describe('AD-976 speech-synced reveal', () => {
  it('reveals each reply only as its agent starts speaking, in speaking order', () => {
    const staged = stageReplies([
      { agent_id: 'a1', text: 'first' },
      { agent_id: 'a2', text: 'second' },
    ]);
    const { onSpeaking, appended } = makeSpeakReveal(staged);
    // Nothing revealed before anyone speaks (the bug: text dumped up front).
    expect(appended).toEqual([]);
    // a2 speaks first (facilitator order) -> a2's text appears first.
    onSpeaking('a2');
    expect(appended.map((r) => r.text)).toEqual(['second']);
    onSpeaking(null); // gap between utterances reveals nothing
    expect(appended.map((r) => r.text)).toEqual(['second']);
    onSpeaking('a1');
    expect(appended.map((r) => r.text)).toEqual(['second', 'first']);
  });

  it('reveals each agent exactly once even if speakingAgentId repeats', () => {
    const staged = stageReplies([{ agent_id: 'a1', text: 'hi' }]);
    const { onSpeaking, appended } = makeSpeakReveal(staged);
    onSpeaking('a1');
    onSpeaking(null);
    onSpeaking('a1'); // re-entry must not double-append
    expect(appended).toHaveLength(1);
  });

  it('a speaking agent with no staged reply reveals nothing', () => {
    const staged = stageReplies([{ agent_id: 'a1', text: 'hi' }]);
    const { onSpeaking, appended } = makeSpeakReveal(staged);
    onSpeaking('ghost');
    expect(appended).toEqual([]);
  });
});
