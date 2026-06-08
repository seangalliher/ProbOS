/** AD-921: thin React wrapper over the meetingVoice sequencer. Injects the
 *  real ``speakResponse`` / ``onSpeechEvent`` / ``stripMarkdownForSpeech``,
 *  gates on the meeting being active AND voice being enabled, exposes
 *  ``speakingAgentId`` (the AD-923 indicator seam), and supersedes an
 *  in-flight batch when the Captain sends again (generation token -- no
 *  talk-over across re-sends). */

import { useCallback, useEffect, useRef, useState } from 'react';
import { speakResponse, onSpeechEvent, stripMarkdownForSpeech } from './voice';
import {
  speakRepliesSequentially,
  createVoiceProfileResolver,
  type PerAgentReply,
} from './meetingVoice';
import { useStore } from '../store/useStore';

export interface UseMeetingVoiceOptions {
  /** True when the active thread's ``metadata.meeting_active`` is set. */
  meetingActive: boolean;
}

export interface UseMeetingVoiceResult {
  /** Speak the AD-914 ``per_agent_replies`` in facilitator (array) order,
   *  one at a time. Self-gates on ``meetingActive && voiceEnabled``;
   *  no-ops otherwise. Reference-stable. */
  speakReplies: (replies: PerAgentReply[]) => void;
  /** The agent currently speaking (``null`` between utterances / when idle).
   *  AD-923 presence-indicator seam. */
  speakingAgentId: string | null;
}

export function useMeetingVoice(opts: UseMeetingVoiceOptions): UseMeetingVoiceResult {
  const [speakingAgentId, setSpeakingAgentId] = useState<string | null>(null);

  // Hold gating in a ref so ``speakReplies`` can stay reference-stable and be
  // called imperatively from ProfileChatTab's send callback without churning
  // its dependency array (BF-292 stale-closure discipline: read live state at
  // call time, not from closure).
  const meetingActiveRef = useRef(opts.meetingActive);
  useEffect(() => { meetingActiveRef.current = opts.meetingActive; }, [opts.meetingActive]);

  // One generation per batch: a newer batch supersedes the older one so two
  // Captain sends never talk over each other, and a stale onSpeakingChange
  // from a superseded batch can't clobber the current speakingAgentId.
  const genRef = useRef(0);
  const resolverRef = useRef(createVoiceProfileResolver());

  const speakReplies = useCallback((replies: PerAgentReply[]): void => {
    if (!meetingActiveRef.current) return;
    if (!useStore.getState().voiceEnabled) return;
    if (!Array.isArray(replies) || replies.length === 0) return;
    const myGen = ++genRef.current;
    void speakRepliesSequentially(replies, {
      speak: speakResponse,
      subscribe: onSpeechEvent,
      resolveProfile: resolverRef.current,
      strip: stripMarkdownForSpeech,
      onSpeakingChange: (id) => { if (genRef.current === myGen) setSpeakingAgentId(id); },
      shouldContinue: () => genRef.current === myGen,
    });
  }, []);

  return { speakReplies, speakingAgentId };
}
