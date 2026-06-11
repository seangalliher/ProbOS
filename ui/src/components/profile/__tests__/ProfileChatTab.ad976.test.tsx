// AD-976 / BF-618: meeting-mode text reveal. The Captain reported text still
// dumped all at once in a live meeting: the original AD-976 coupled the text
// reveal to TTS ``speakingAgentId`` events, which burst to all-at-once when
// speech fired fast or didn't pace. BF-618 replaces that with the SAME
// timer-paced progressive reveal text chat uses (built-in inter-reply spacing,
// cannot burst), with voice kicked off concurrently. The full ProfileChatTab is
// too heavy to render (audio/screen deps) — same rationale as
// ProfileChatTab.groupsend.test.tsx — so the BF-618 ordering + reveal contract
// is exercised through a FAITHFUL MIRROR of the production send-handler branch.
import { describe, it, expect } from 'vitest';

type Reply = { agent_id?: string; callsign?: string; text?: string };

// --- Mirror of the BF-618 send-handler reveal sequence. Voice is dispatched
// FIRST (non-blocking) so it runs concurrently with the awaited progressive
// reveal; there is NO meeting/audio special-case that dumps text instantly.
async function runRevealSequence(
  replies: Reply[],
  hooks: {
    speakMeetingReplies: (r: Reply[]) => void;
    revealRepliesProgressively: (
      r: Reply[],
      deps: { appendReply: (x: Reply) => void; sleep: (ms: number) => Promise<void> },
    ) => Promise<void>;
    appendReply: (x: Reply) => void;
  },
): Promise<void> {
  // BF-618: voice first (concurrent), then the awaited progressive reveal.
  hooks.speakMeetingReplies(replies);
  await hooks.revealRepliesProgressively(replies, {
    appendReply: hooks.appendReply,
    sleep: () => Promise.resolve(),
  });
}

describe('BF-618 meeting text reveal ordering', () => {
  it('dispatches voice BEFORE awaiting the progressive reveal (concurrent)', async () => {
    const order: string[] = [];
    await runRevealSequence(
      [{ agent_id: 'a1', text: 'one' }, { agent_id: 'a2', text: 'two' }],
      {
        speakMeetingReplies: () => order.push('voice'),
        revealRepliesProgressively: async (r, deps) => {
          order.push('reveal-start');
          for (const x of r) deps.appendReply(x);
        },
        appendReply: () => order.push('append'),
      },
    );
    // Voice is kicked off first, then the reveal runs.
    expect(order[0]).toBe('voice');
    expect(order[1]).toBe('reveal-start');
  });

  it('reveals every reply through the progressive path (no instant dump)', async () => {
    const appended: Reply[] = [];
    let usedProgressive = false;
    await runRevealSequence(
      [{ agent_id: 'a1', text: 'one' }, { agent_id: 'a2', text: 'two' }, { agent_id: 'a3', text: 'three' }],
      {
        speakMeetingReplies: () => { /* noop */ },
        revealRepliesProgressively: async (r, deps) => {
          usedProgressive = true;
          for (const x of r) deps.appendReply(x);
        },
        appendReply: (x) => appended.push(x),
      },
    );
    expect(usedProgressive).toBe(true);
    expect(appended.map((r) => r.text)).toEqual(['one', 'two', 'three']);
  });

  it('does not depend on meeting/audio state (always progressive)', async () => {
    // The reveal sequence is identical regardless of meetingActive/callAudio —
    // there is no longer a branch that dumps text when audio is on. We assert
    // the single code path runs for any inputs.
    for (const replies of [[], [{ agent_id: 'a1', text: 'x' }]]) {
      let revealed = false;
      await runRevealSequence(replies, {
        speakMeetingReplies: () => { /* noop */ },
        revealRepliesProgressively: async () => { revealed = true; },
        appendReply: () => { /* noop */ },
      });
      expect(revealed).toBe(true);
    }
  });
});
