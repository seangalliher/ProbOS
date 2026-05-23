/** BF-290 — ProfileChatTab voice input regression tests.
 *
 * Two production-blocking bugs:
 *  1. PTT stuck after whisper fallback (listening state not cleared on
 *     give-up + whisper subscription leak on next press).
 *  2. Conversation mode missing onAgentReply/onStateChange handlers, so
 *     agent replies silently dropped and controller stuck in
 *     agent_speaking forever.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

vi.mock('../audio/voice', () => ({
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

vi.mock('../audio/whisperStt', () => ({
  armWhisperStt: mocks.armWhisperSttMock,
  disarmWhisperStt: mocks.disarmWhisperSttMock,
  onTranscript: mocks.whisperOnTranscriptMock,
  onTranscribing: vi.fn(() => () => {}),
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

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
  Object.values(mocks).forEach((m) => {
    if (typeof m === 'function' && 'mockReset' in m) (m as any).mockReset();
  });
  mocks.armConversationModeMock.mockReturnValue(() => {});
  mocks.whisperOnTranscriptMock.mockReturnValue(() => {});
  mocks.onSpeechEventMock.mockReturnValue(() => {});
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

describe('BF-290 PTT toggle + whisper fallback cleanup', () => {
  it('two presses: start then stop also disarms whisper fallback', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');

    // 1st press — starts browser SR.
    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);

    // 2nd press — stops browser SR + disarms whisper (BF-290 cleanup).
    const armed = await screen.findByLabelText('Stop listening');
    fireEvent.click(armed);
    expect(mocks.stopListeningMock).toHaveBeenCalledTimes(1);
    expect(mocks.disarmWhisperSttMock).toHaveBeenCalledTimes(1);
    await screen.findByLabelText('Voice input');
  });

  it('PTT recovers after whisper fallback give-up (BF-290 setListening(false))', async () => {
    render(<ProfileChatTab agentId="a1" />);

    // Press 1 — empty (drive onError to increment emptyTranscriptCountRef).
    fireEvent.click(await screen.findByLabelText('Voice input'));
    const onError1 = mocks.startListeningMock.mock.calls[0][1] as () => void;
    onError1();
    // Press 2 — empty.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    const onError2 = mocks.startListeningMock.mock.calls[1][1] as () => void;
    onError2();

    // Press 3 — must hit whisper fallback branch and NOT call startListening.
    const beforeStartCount = mocks.startListeningMock.mock.calls.length;
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock.mock.calls.length).toBe(beforeStartCount);
    expect(mocks.whisperOnTranscriptMock).toHaveBeenCalledTimes(1);

    // BF-290: after arming whisper, listening visual state must be reset
    // so the operator can press again to abort. If setListening(false)
    // is missing, the button stays in 'Stop listening' aria state.
    await screen.findByLabelText('Voice input');

    // Press 4 — operator gave up. Must stop + disarm whisper.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    // Mic press starts a fresh session (listening was false, so the
    // non-listening branch runs). After arming whisper above, the empty
    // counter was reset; this press goes to the startListening path.
    // BF-290 disarm happens on the OTHER branch (stop). Drive it: press
    // again to trigger stop.
    const armed4 = await screen.findByLabelText('Stop listening');
    fireEvent.click(armed4);
    expect(mocks.stopListeningMock).toHaveBeenCalledTimes(1);
    expect(mocks.disarmWhisperSttMock).toHaveBeenCalledTimes(1);

    // Press 5 — fresh start works.
    const beforeStart5 = mocks.startListeningMock.mock.calls.length;
    fireEvent.click(await screen.findByLabelText('Voice input'));
    expect(mocks.startListeningMock.mock.calls.length).toBe(beforeStart5 + 1);
  });
});

describe('BF-290 conversation mode handler wiring', () => {
  it('armConversationMode receives onAgentReply AND onStateChange handlers', async () => {
    localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation');
    useStore.setState({ voiceEnabled: true });
    render(<ProfileChatTab agentId="a1" />);

    await waitFor(() => expect(mocks.armConversationModeMock).toHaveBeenCalled());
    const opts = (mocks.armConversationModeMock.mock.calls as any[][])[0][0] as any;
    expect(opts).toEqual(
      expect.objectContaining({
        onAgentReply: expect.any(Function),
        onStateChange: expect.any(Function),
      }),
    );
  });

  it('onAgentReply appends message, speaks, and signals completion on TTS end', async () => {
    localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation');
    localStorage.setItem('hxi_chat_tts_a1', '1');
    useStore.setState({ voiceEnabled: true, agentConversations: new Map() });
    render(<ProfileChatTab agentId="a1" />);

    await waitFor(() => expect(mocks.armConversationModeMock).toHaveBeenCalled());
    const opts = (mocks.armConversationModeMock.mock.calls as any[][])[0][0] as any;
    const onAgentReply = opts.onAgentReply as (text: string) => void;

    const subscribeCountBefore = mocks.onSpeechEventMock.mock.calls.length;
    onAgentReply('Hello, Captain.');

    // 1. Message appended to per-agent conversation.
    await waitFor(() => {
      const conv = useStore.getState().agentConversations.get('a1');
      expect(conv?.messages.some((m) => m.role === 'agent' && m.text === 'Hello, Captain.')).toBe(true);
    });

    // 2. speakResponse invoked with (text, voiceProfile, agentId).
    expect(mocks.speakResponseMock).toHaveBeenCalledTimes(1);
    const [spokenText, , spokenAgentId] = (mocks.speakResponseMock.mock.calls as any[][])[0];
    expect(spokenText).toBe('Hello, Captain.');
    expect(spokenAgentId).toBe('a1');

    // 3. Subscribed to speech events (one new subscription from onAgentReply,
    //    on top of any subscriptions the component made on mount).
    expect(mocks.onSpeechEventMock.mock.calls.length).toBe(subscribeCountBefore + 1);
    const speechListener = (mocks.onSpeechEventMock.mock.calls as any[][])[subscribeCountBefore][0] as (e: any) => void;

    // 4. Driving the matching 'end' event invokes markAgentReplyComplete.
    speechListener({ type: 'end', agent_id: 'a1', utterance: {} });
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);

    // 5. Second turn — onAgentReply works repeatedly.
    onAgentReply('Second turn.');
    await waitFor(() => {
      const conv = useStore.getState().agentConversations.get('a1');
      expect(conv?.messages.filter((m) => m.role === 'agent').length).toBe(2);
    });
    expect(mocks.speakResponseMock).toHaveBeenCalledTimes(2);
  });

  it('onAgentReply with TTS disabled signals completion immediately (no speakResponse)', async () => {
    localStorage.setItem('hxi_chat_mic_mode_a1', 'conversation');
    localStorage.setItem('hxi_chat_tts_a1', '0');
    useStore.setState({ voiceEnabled: true, agentConversations: new Map() });
    render(<ProfileChatTab agentId="a1" />);

    await waitFor(() => expect(mocks.armConversationModeMock).toHaveBeenCalled());
    const opts = (mocks.armConversationModeMock.mock.calls as any[][])[0][0] as any;
    const onAgentReply = opts.onAgentReply as (text: string) => void;

    const subscribeCountBefore = mocks.onSpeechEventMock.mock.calls.length;
    onAgentReply('Hi.');

    // Message still appended.
    await waitFor(() => {
      const conv = useStore.getState().agentConversations.get('a1');
      expect(conv?.messages.some((m) => m.text === 'Hi.')).toBe(true);
    });

    // TTS not invoked.
    expect(mocks.speakResponseMock).not.toHaveBeenCalled();

    // Completion signaled immediately.
    expect(mocks.markAgentReplyCompleteMock).toHaveBeenCalledTimes(1);

    // No NEW speech event subscription from onAgentReply (we shortcut
    // before subscribing; the component may have mount-time subscriptions).
    expect(mocks.onSpeechEventMock.mock.calls.length).toBe(subscribeCountBefore);
  });
});
