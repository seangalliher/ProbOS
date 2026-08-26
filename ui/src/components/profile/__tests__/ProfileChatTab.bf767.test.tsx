/** BF-767 — conversation-mode turn completion must correlate on the UTTERANCE.
 *
 *  ``speakResponse``'s FIRST action is to cancel whatever is speaking
 *  (``speechSynthesis.cancel()`` / ``_activeAudio.pause()``), and that
 *  cancellation emits a terminal 'end' carrying the SAME agent_id as the reply
 *  that superseded it. Because the completion listener is armed one line BEFORE
 *  ``speakResponse`` is called, that death rattle lands in the listener belonging
 *  to the utterance that has not started yet — and an agent-only match completed
 *  the turn on it. The barge-in guard then detaches and the silence timer starts
 *  while the agent is still audibly talking.
 *
 *  The ``speakResponse`` mock below models that ordering faithfully: on each
 *  call it first fires the previous utterance's 'end' (same agent_id, the OLD
 *  id) into every armed listener, then mints and returns this call's id — the
 *  BF-767 contract.
 *
 *  Assertions are on whether the TURN COMPLETED (``markAgentReplyComplete``
 *  call count), never on which branch ran.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  armConversationModeMock: vi.fn(() => () => {}),
  disarmConversationModeMock: vi.fn(),
  markAgentReplyCompleteMock: vi.fn(),
  armWhisperSttMock: vi.fn(),
  disarmWhisperSttMock: vi.fn(),
  whisperOnTranscriptMock: vi.fn(() => () => {}),
  speakResponseMock: vi.fn(),
  onSpeechEventMock: vi.fn(() => () => {}),
}));

vi.mock('../../../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: mocks.onSpeechEventMock,
  prewarmTts: vi.fn(),
}));

vi.mock('../../../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../../../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationModeMock,
  disarmConversationMode: mocks.disarmConversationModeMock,
  markAgentReplyComplete: mocks.markAgentReplyCompleteMock,
}));

vi.mock('../../../audio/transformersStt', () => ({
  armTransformersStt: mocks.armWhisperSttMock,
  disarmTransformersStt: mocks.disarmWhisperSttMock,
  onTransformersTranscript: mocks.whisperOnTranscriptMock,
  onTransformersTranscribing: vi.fn(() => () => {}),
  onTransformersProgress: vi.fn(() => () => {}),
}));

import { ProfileChatTab } from '../ProfileChatTab';
import { useStore } from '../../../store/useStore';

const AGENT_ID = 'a1';

interface DrivenSpeechEvent {
  type: 'start' | 'end';
  agent_id?: string;
  utterance?: unknown;
  utterance_id?: number;
}
type SpeechListener = (e: DrivenSpeechEvent) => void;

/** Every listener ProfileChatTab has armed, in registration order. */
let listeners: SpeechListener[] = [];
/** Mirrors voice.ts's ``_speakGeneration``. */
let generation = 0;
/** The id of the utterance a subsequent speakResponse would cancel. */
let inFlightId: number | null = null;

/** voice.ts fires each listener inside its own try/catch (Tier-2). */
function fireToAll(event: DrivenSpeechEvent): void {
  for (const fn of [...listeners]) {
    try { fn(event); } catch { /* Tier-2 */ }
  }
}

function setDefaultFetch(): void {
  global.fetch = vi.fn((url: unknown) => {
    const target = String(url);
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as never;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as never;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as never;
  }) as never;
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  listeners = [];
  generation = 0;
  inFlightId = null;

  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.whisperOnTranscriptMock.mockReturnValue(() => {});
  mocks.onSpeechEventMock.mockImplementation(((fn: SpeechListener) => {
    listeners.push(fn);
    return () => {
      const i = listeners.indexOf(fn);
      if (i >= 0) listeners.splice(i, 1);
    };
  }) as never);
  mocks.speakResponseMock.mockImplementation(((
    _text: string, _profile: unknown, agentId?: string,
  ) => {
    // voice.ts cancels first: the SUPERSEDED utterance emits its terminal
    // 'end' with the SAME agent_id, before this call's utterance exists.
    if (inFlightId !== null) {
      fireToAll({ type: 'end', agent_id: agentId, utterance: {}, utterance_id: inFlightId });
    }
    generation += 1;
    inFlightId = generation;
    return generation;
  }) as never);

  localStorage.clear();
  localStorage.setItem(`hxi_chat_mic_mode_${AGENT_ID}`, 'conversation');
  localStorage.setItem(`hxi_chat_tts_${AGENT_ID}`, '1');
  useStore.setState({ voiceEnabled: true, agentConversations: new Map() });
  setDefaultFetch();
  if (!(Element.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView) {
    (Element.prototype as unknown as { scrollIntoView: unknown }).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

async function mountAndCaptureOnAgentReply(): Promise<(text: string) => void> {
  render(<ProfileChatTab agentId={AGENT_ID} />);
  await waitFor(() => expect(mocks.armConversationModeMock).toHaveBeenCalled());
  const [[opts]] = mocks.armConversationModeMock.mock.calls as unknown as
    Array<[{ onAgentReply: (text: string) => void }]>;
  return opts.onAgentReply;
}

describe('BF-767 conversation-mode completion correlates on the utterance', () => {
  it('does not complete the new turn on the cancelled utterance\'s end', async () => {
    const onAgentReply = await mountAndCaptureOnAgentReply();

    // Turn 1 starts speaking and is still in flight.
    act(() => { onAgentReply('First reply.'); });
    expect(mocks.speakResponseMock).toHaveBeenCalledTimes(1);
    expect(mocks.markAgentReplyCompleteMock).not.toHaveBeenCalled();

    // Turn 2 arrives while turn 1 is mid-utterance. speakResponse cancels
    // turn 1, whose terminal 'end' (same agent_id) reaches BOTH listeners.
    act(() => { onAgentReply('Second reply.'); });
    expect(mocks.speakResponseMock).toHaveBeenCalledTimes(2);

    // HEADLINE: exactly ONE completion — turn 1's, for the utterance that
    // genuinely ended. Turn 2 has not been spoken yet, so it must still be
    // waiting. Pre-fix this is 2: turn 2 completed on turn 1's death rattle.
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);
  });

  it('completes the turn on its own utterance end', async () => {
    const onAgentReply = await mountAndCaptureOnAgentReply();

    act(() => { onAgentReply('First reply.'); });
    act(() => { onAgentReply('Second reply.'); });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);

    // Turn 2's OWN utterance finishes.
    const secondId = mocks.speakResponseMock.mock.results[1].value as number;
    act(() => {
      fireToAll({ type: 'end', agent_id: AGENT_ID, utterance: {}, utterance_id: secondId });
    });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(2);
  });

  it('does not complete an agent-scoped turn on a bare end with no agent_id', async () => {
    const onAgentReply = await mountAndCaptureOnAgentReply();

    act(() => { onAgentReply('Solo reply.'); });
    const soloId = mocks.speakResponseMock.mock.results[0].value as number;

    // An unattributed utterance elsewhere in the app ends (IntentSurface's
    // Ship's Computer path has no agent to attribute to).
    act(() => { fireToAll({ type: 'end', utterance: {}, utterance_id: 9999 }); });
    expect(mocks.markAgentReplyCompleteMock).not.toHaveBeenCalled();

    // This agent's own utterance ending still completes the turn.
    act(() => {
      fireToAll({ type: 'end', agent_id: AGENT_ID, utterance: {}, utterance_id: soloId });
    });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);
  });
});
