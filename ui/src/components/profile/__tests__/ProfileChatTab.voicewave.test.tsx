// BF-623 + AD-985: arm-effect gating assertions for ProfileChatTab. The full
// ProfileChatTab is too heavy to render under jsdom (audio/screen deps — the
// groupsend/threadTranscript precedent), and the conversation-mode arm effect's
// branch logic is what these two changes touch. ?raw imports do not execute the
// module, so we scan the source to PROVE the wiring: BF-623 gates the 1:1 path
// on the per-surface `ttsEnabled` (not the global `voiceEnabled`), and AD-985
// adds the meeting branch (group fan-out submit + AD-922 echo gate). The
// controller behaviour itself is covered by conversationController.group.test.ts.
import { describe, it, expect } from 'vitest';

// ?raw imports do not execute the module — safe to scan the heavy source.
import profileChatSource from '../ProfileChatTab.tsx?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

describe('BF-623 1:1 conversation-mode gate', () => {
  it('arms the 1:1 path on the mic-mode selection alone (conversation mode IS the opt-in)', () => {
    // Reading (B): the open mic is an input affordance; arming depends ONLY on
    // the mic-mode selection, not any voice-output flag. The 1:1 branch builds
    // armOpts unconditionally once past the mode + meeting guards.
    expect(profileChatSource).toContain("if (mode !== 'conversation')");
    expect(profileChatSource).toContain('const armOpts: ArmOptions = {');
  });

  it('no longer couples conversation-mode arming to the global voice flag', () => {
    // The old gate `mode !== 'conversation' || !globalVoiceEnabled` is gone.
    expect(profileChatSource).not.toContain("!== 'conversation' || !globalVoiceEnabled");
  });

  it('does not gate 1:1 arming on the per-agent TTS toggle either', () => {
    // The transient `if (!ttsEnabled) { disarmConversationMode(); ... }` gate
    // (an earlier BF-623 draft) must NOT be present — speaking is decided
    // per-reply in onAgentReply, not at arm time.
    expect(profileChatSource).not.toMatch(/if \(!ttsEnabled\) \{\s*disarmConversationMode\(\);/);
  });
});

describe('AD-985 group-meeting open-mic wiring', () => {
  it('branches the arm effect on an active meeting', () => {
    expect(profileChatSource).toContain('if (meetingActive)');
  });

  it('gates the meeting open-mic on the call-scoped callAudioEnabled flag', () => {
    // Inside the meeting branch, bail when call audio is off (AD-949 decoupling).
    expect(profileChatSource).toMatch(/if \(meetingActive\)[\s\S]*?if \(!callAudioEnabled\)/);
  });

  it('uses the AD-922 meeting-wide echo gate (speakingAgentId != null)', () => {
    expect(profileChatSource).toContain('canListen: () => speakingAgentIdRef.current == null');
  });

  it('routes the meeting utterance through the group send path (submitTranscript -> sendText)', () => {
    expect(profileChatSource).toMatch(/submitTranscript: async \(text: string\) => \{[\s\S]*?sendTextRef\.current/);
  });

  it('keeps the send ref current for the meeting submit', () => {
    expect(profileChatSource).toContain('sendTextRef.current = sendText;');
  });

  it('mirrors speakingAgentId into the echo-gate ref', () => {
    expect(profileChatSource).toMatch(/speakingAgentIdRef\.current = speakingAgentId;/);
  });

  it('re-runs arming when agent / mode / meeting / call-audio state changes', () => {
    // The relocated effect depends on the meeting + call-audio flags so entering
    // or leaving a call re-arms the controller for the right surface.
    //
    // The trailing `[^\]]*` is deliberate: this guards that those deps are
    // PRESENT, not that the array is closed to additions. BF-718 appended
    // `threadId` because onAgentReply now resolves the claim scope, and an
    // exact-array match would have read that correct addition as a regression.
    expect(profileChatSource).toMatch(
      /\[agentId, micMode, meetingActive, callAudioEnabled, voiceProfile, ttsKey[^\]]*\]/,
    );
  });
});

describe('HXI no-emoji guard', () => {
  it('the arm-effect region carries no emoji', () => {
    // Cheap whole-file scan; the source is plain TS/JSX (SVG icons, no emoji).
    expect(EMOJI_RE.test(profileChatSource)).toBe(false);
  });
});
