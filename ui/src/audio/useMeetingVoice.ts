/** AD-921: thin React wrapper over the meetingVoice sequencer. Injects the
 *  real ``speakResponse`` / ``onSpeechEvent`` / ``stripMarkdownForSpeech``,
 *  gates on the meeting being active AND call audio being enabled, exposes
 *  ``speakingAgentId`` (the AD-923 indicator seam), and supersedes an
 *  in-flight batch when the Captain sends again (generation token -- no
 *  talk-over across re-sends). */

import { useCallback, useEffect, useRef, useState } from 'react';
import { speakResponse, onSpeechEvent, stripMarkdownForSpeech, prewarmTts } from './voice';
import {
  speakRepliesSequentially,
  createVoiceProfileResolver,
  type PerAgentReply,
} from './meetingVoice';
import { useStore } from '../store/useStore';

export interface UseMeetingVoiceOptions {
  /** True when the active thread's ``metadata.meeting_active`` is set. */
  meetingActive: boolean;
  /** AD-972: the crew participant agent_ids in the room. When the meeting is
   *  active their voice profiles are prefetched (cache-warmed) so the FIRST
   *  reply's TTS is not gated on a cold ``/api/agent/{id}/profile`` fetch. */
  participantAgentIds?: string[];
}

export interface UseMeetingVoiceResult {
  /** Speak the AD-914 ``per_agent_replies`` in facilitator (array) order,
   *  one at a time. Self-gates on ``meetingActive && callAudioEnabled``;
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

  // AD-972: move the cold voice-profile fetch + TTS backend probe OFF the
  // first-utterance critical path. When the meeting opens we prewarm the TTS
  // status probe and prefetch every room participant's voice profile (seconds
  // before any reply arrives), so ``speakRepliesSequentially``'s per-utterance
  // ``resolveProfile`` is a cache hit and the first agent speaks as soon as the
  // synth returns. Keyed on a joined id string so a new array identity each
  // render does not re-run the prefetch. Tier-2: failures cache as the default
  // voice; nothing blocks.
  const participantKey = (opts.participantAgentIds ?? []).join(',');
  useEffect(() => {
    if (!opts.meetingActive) return;
    prewarmTts();
    for (const id of participantKey ? participantKey.split(',') : []) {
      if (id) void resolverRef.current(id);
    }
  }, [opts.meetingActive, participantKey]);

  const speakReplies = useCallback((replies: PerAgentReply[]): void => {
    if (!meetingActiveRef.current) return;
    // AD-949: gate on the call-scoped ``callAudioEnabled`` (default ON) instead
    // of the Ship's-Computer ``voiceEnabled`` — group/meeting voice is now
    // audible by default in a live call and muted only via the in-call control.
    if (!useStore.getState().callAudioEnabled) return;
    if (!Array.isArray(replies) || replies.length === 0) return;
    const myGen = ++genRef.current;
    // AD-972: kick off ALL reply profile fetches up front (promise-cached, so
    // this dedupes with the meeting-open prewarm). By the time the sequential
    // sequencer awaits speaker N, its profile is resolved / in-flight — no cold
    // fetch gap between speakers.
    for (const r of replies) void resolverRef.current(r.agent_id);
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
