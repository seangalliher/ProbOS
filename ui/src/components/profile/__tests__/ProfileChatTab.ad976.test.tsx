// AD-976 / BF-618 / BF-621: meeting-mode text reveal.
//
// History: the original AD-976 coupled the text reveal to TTS
// ``speakingAgentId`` events, which burst to all-at-once when speech fired fast
// or didn't pace. BF-618 replaced that with the timer-paced progressive reveal.
// BF-621 (this contract): the Captain wants to HEAR each reply, THEN see it pop
// into the chat. So when a meeting is live AND call audio is ON, the reveal is
// driven by the AD-921 voice sequencer's per-utterance completion (the single
// clock) — text strictly follows speech, with a "{callsign} is speaking…" label
// for the duration of each utterance. When audio is OFF/muted (or this is text
// chat) the AD-960 timer-paced progressive reveal is used.
//
// The full ProfileChatTab is too heavy to render (audio/screen deps) — same
// rationale as ProfileChatTab.groupsend.test.tsx — so the BF-621 branch +
// hook-wiring contract is exercised through a FAITHFUL MIRROR of the production
// send-handler branch.
import { describe, it, expect } from 'vitest';

type Reply = { agent_id: string; callsign?: string; text?: string };
type TypingState = { agentId: string; callsign: string; verb?: string } | null;
interface SpeakHooks {
  onUtteranceStart?: (r: Reply) => void;
  onUtteranceEnd?: (r: Reply) => void;
}

// --- Mirror of the BF-621 send-handler reveal branch. ---
async function runRevealSequence(
  replies: Reply[],
  ctx: {
    meetingLive: boolean;
    callAudioOn: boolean;
    speakMeetingReplies: (r: Reply[], hooks?: SpeakHooks) => void;
    revealRepliesProgressively: (
      r: Reply[],
      deps: { appendReply: (x: Reply) => void; sleep: (ms: number) => Promise<void> },
    ) => Promise<void>;
    appendReply: (x: Reply) => void;
    setTyping: (t: TypingState) => void;
  },
): Promise<void> {
  if (ctx.meetingLive && ctx.callAudioOn) {
    // Voice-driven: hear, then see. speakMeetingReplies is fire-and-forget; the
    // hooks set the "speaking" label as each agent begins and reveal that
    // agent's text the instant it finishes.
    ctx.speakMeetingReplies(replies, {
      onUtteranceStart: (r) => ctx.setTyping({ agentId: r.agent_id, callsign: r.callsign ?? '', verb: 'speaking' }),
      onUtteranceEnd: (r) => { ctx.setTyping(null); ctx.appendReply(r); },
    });
  } else {
    await ctx.revealRepliesProgressively(replies, {
      appendReply: ctx.appendReply,
      sleep: () => Promise.resolve(),
    });
  }
}

/** A faithful fake of the AD-921 voice sequencer post-BF-621: for each
 *  non-empty reply, call onUtteranceStart, then onUtteranceEnd (mirrors
 *  speakRepliesSequentially ordering). */
function fakeVoiceSequencer() {
  return (replies: Reply[], hooks?: SpeakHooks): void => {
    for (const r of replies) {
      if (!r.text) continue;
      hooks?.onUtteranceStart?.(r);
      hooks?.onUtteranceEnd?.(r);
    }
  };
}

describe('BF-621 meeting text reveal (hear, then see)', () => {
  it('meeting + audio ON: reveals each reply via the voice sequencer, not the timer', async () => {
    const appended: Reply[] = [];
    let usedProgressive = false;
    await runRevealSequence(
      [{ agent_id: 'a1', text: 'one' }, { agent_id: 'a2', text: 'two' }],
      {
        meetingLive: true,
        callAudioOn: true,
        speakMeetingReplies: fakeVoiceSequencer(),
        revealRepliesProgressively: async () => { usedProgressive = true; },
        appendReply: (x) => appended.push(x),
        setTyping: () => { /* noop */ },
      },
    );
    // Text revealed through the voice path; the timer reveal is NOT used.
    expect(usedProgressive).toBe(false);
    expect(appended.map((r) => r.text)).toEqual(['one', 'two']);
  });

  it('meeting + audio ON: sets a "speaking" label on start, clears it before append', async () => {
    const events: string[] = [];
    await runRevealSequence(
      [{ agent_id: 'a1', callsign: 'Ezri', text: 'hi' }],
      {
        meetingLive: true,
        callAudioOn: true,
        speakMeetingReplies: fakeVoiceSequencer(),
        revealRepliesProgressively: async () => { /* unused */ },
        appendReply: () => events.push('append'),
        setTyping: (t) => events.push(t === null ? 'clear' : `speaking:${t.verb}:${t.callsign}`),
      },
    );
    // hear (speaking label) → clear → see (append).
    expect(events).toEqual(['speaking:speaking:Ezri', 'clear', 'append']);
  });

  it('meeting + audio MUTED: falls back to the timer-paced progressive reveal', async () => {
    const appended: Reply[] = [];
    let usedProgressive = false;
    let usedVoice = false;
    await runRevealSequence(
      [{ agent_id: 'a1', text: 'one' }, { agent_id: 'a2', text: 'two' }],
      {
        meetingLive: true,
        callAudioOn: false,
        speakMeetingReplies: () => { usedVoice = true; },
        revealRepliesProgressively: async (r, deps) => {
          usedProgressive = true;
          for (const x of r) deps.appendReply(x);
        },
        appendReply: (x) => appended.push(x),
        setTyping: () => { /* noop */ },
      },
    );
    expect(usedVoice).toBe(false);
    expect(usedProgressive).toBe(true);
    expect(appended.map((r) => r.text)).toEqual(['one', 'two']);
  });

  it('text chat (no meeting): uses the timer-paced progressive reveal', async () => {
    const appended: Reply[] = [];
    let usedProgressive = false;
    await runRevealSequence(
      [{ agent_id: 'a1', text: 'x' }, { agent_id: 'a2', text: 'y' }, { agent_id: 'a3', text: 'z' }],
      {
        meetingLive: false,
        callAudioOn: true,
        speakMeetingReplies: () => { throw new Error('voice must not run outside a meeting'); },
        revealRepliesProgressively: async (r, deps) => {
          usedProgressive = true;
          for (const x of r) deps.appendReply(x);
        },
        appendReply: (x) => appended.push(x),
        setTyping: () => { /* noop */ },
      },
    );
    expect(usedProgressive).toBe(true);
    expect(appended.map((r) => r.text)).toEqual(['x', 'y', 'z']);
  });
});
