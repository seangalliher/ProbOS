/** BF-300 — PTT mic must not capture TTS playback as the next utterance.
 *
 * Issue: #774 (echo loop). Fixes:
 *  - Layer 1: explicit stopListening / disarmWhisperStt in every PTT result callback.
 *  - Layer 2: ttsActive gate refuses new SR sessions during TTS playback.
 *  - MicIndicator 'muted' visual signals the gate to the operator.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
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
  whisperOnTranscribingMock: vi.fn(() => () => {}),
  speakResponseMock: vi.fn(),
  onSpeechEventMock: vi.fn((_fn: any) => () => {}),
}));

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  onSpeechEvent: mocks.onSpeechEventMock,
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

vi.mock('../audio/conversationController', () => ({
  armConversationMode: mocks.armConversationModeMock,
  disarmConversationMode: mocks.disarmConversationModeMock,
  markAgentReplyComplete: mocks.markAgentReplyCompleteMock,
}));

vi.mock('../audio/transformersStt', () => ({
  armTransformersStt: mocks.armWhisperSttMock,
  disarmTransformersStt: mocks.disarmWhisperSttMock,
  onTransformersTranscript: mocks.whisperOnTranscriptMock,
  onTransformersTranscribing: mocks.whisperOnTranscribingMock,
  onTransformersProgress: vi.fn(() => () => {}),
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

// Capture every onSpeechEvent listener registered by ProfileChatTab.
// The component registers two: one inside armConversationMode (BF-290)
// and one at the top level (BF-300). Tests dispatch by iterating the
// captured listeners so we exercise the production code path exactly.
const speechListeners: Array<(e: any) => void> = [];

function setDefaultFetch(): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  }) as any;
}

beforeEach(() => {
  speechListeners.length = 0;
  Object.values(mocks).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m) (m as any).mockReset();
  });
  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.whisperOnTranscriptMock.mockReturnValue(() => {});
  mocks.whisperOnTranscribingMock.mockReturnValue(() => {});
  mocks.onSpeechEventMock.mockImplementation((fn: any) => {
    speechListeners.push(fn);
    return () => {
      const i = speechListeners.indexOf(fn);
      if (i >= 0) speechListeners.splice(i, 1);
    };
  });
  localStorage.clear();
  useStore.setState({
    voiceEnabled: true,
    agentConversations: new Map(),
  });
  setDefaultFetch();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

function dispatchSpeechEvent(type: 'start' | 'end', agentId?: string): void {
  // Fire only the top-level BF-300 listener — the BF-290 listener is
  // scoped to in-flight agent replies and is per-call. To be safe,
  // dispatch to ALL listeners; the BF-290 one no-ops unless its inner
  // state matches.
  act(() => {
    for (const fn of [...speechListeners]) {
      try {
        fn({ type, agent_id: agentId, utterance: {} as any });
      } catch {
        /* ignore */
      }
    }
  });
}

describe('BF-300 — PTT mic does not capture TTS playback', () => {
  it('browser-SR result callback calls stopListening before sendText fires', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
    const onResult = (mocks.startListeningMock.mock.calls[0] as any)[0] as (t: string) => void;

    // Fire the result. stopListening MUST be called synchronously,
    // inside the result callback (before the 100 ms sendText timer
    // fires). We don't fake timers because findByLabelText's polling
    // relies on real setTimeout; the synchronous-stopListening check
    // doesn't need timer manipulation.
    act(() => { onResult('hello ezri'); });
    expect(mocks.stopListeningMock).toHaveBeenCalledTimes(1);
  });

  it('whisper-primary onTranscript path disarms whisper before sendText', async () => {
    // Wire whisper as primary + healthy so the click takes the
    // whisper-onTranscript branch (line ~957).
    global.fetch = vi.fn((url: any) => {
      const target = String(url);
      if (target.endsWith('/voice/health')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            primary_stt: 'whisper',
            engine: 'whisper',
            backend_available: true,
            healthy: true,
          }),
        }) as any;
      }
      if (target.endsWith('/chat/history')) {
        return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
      }
      if (target.endsWith('/profile')) {
        return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
    }) as any;

    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');

    // Let the voice-health fetch resolve.
    await act(async () => { await Promise.resolve(); });

    fireEvent.click(mic);
    expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1);
    const onTranscript = (mocks.whisperOnTranscriptMock.mock.calls[0] as any)[0] as (t: string) => void;

    act(() => { onTranscript('hello ezri'); });
    // disarmWhisperStt fires synchronously inside the transcript callback,
    // BEFORE the 100 ms setTimeout(sendText).
    expect(mocks.disarmWhisperSttMock).toHaveBeenCalledTimes(1);
  });

  it('clicking the mic while TTS is playing is a no-op (ttsActive gate)', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');

    // Wait for the BF-300 useEffect to register its onSpeechEvent listener.
    expect(speechListeners.length).toBeGreaterThan(0);

    dispatchSpeechEvent('start', 'a1');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).not.toHaveBeenCalled();
    expect(mocks.armWhisperSttMock).not.toHaveBeenCalled();
  });

  it('after onSpeechEvent("end"), mic click works normally', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');

    dispatchSpeechEvent('start', 'a1');
    dispatchSpeechEvent('end', 'a1');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
  });

  it('MicIndicator shows muted state during TTS playback', async () => {
    render(<ProfileChatTab agentId="a1" />);
    await screen.findByLabelText('Voice input');

    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
    dispatchSpeechEvent('start', 'a1');
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('muted');
    dispatchSpeechEvent('end', 'a1');
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });
});
