/** BF-293 — Agent reply resets the PTT empty-transcript counter so the
 * whisperStt fallback isn't surprise-armed by stale empty results from
 * earlier conversational rounds.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

vi.mock('../audio/transformersStt', () => ({
  armTransformersStt: mocks.armWhisperSttMock,
  disarmTransformersStt: mocks.disarmWhisperSttMock,
  onTransformersTranscript: mocks.whisperOnTranscriptMock,
  onTransformersTranscribing: vi.fn(() => () => {}),
  onTransformersProgress: vi.fn(() => () => {}),
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

function setupFetch() {
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
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  setupFetch();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('BF-293 empty-transcript counter reset on agent reply', () => {
  it('counter accumulates across consecutive empty browser-SR presses (baseline)', async () => {
    render(<ProfileChatTab agentId="a1" />);

    // Press 1 — empty
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    const onError1 = mocks.startListeningMock.mock.calls[0][1] as () => void;
    onError1();

    // Press 2 — empty
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(2));
    const onError2 = mocks.startListeningMock.mock.calls[1][1] as () => void;
    onError2();

    // Press 3 — counter is now >= 2, must route through whisper fallback
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(2);
  });

  it('agent reply resets the counter so third press uses browser SR, not whisper fallback', async () => {
    render(<ProfileChatTab agentId="a1" />);

    // Two empty presses to load the counter to 2.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    (mocks.startListeningMock.mock.calls[0][1] as () => void)();

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(2));
    (mocks.startListeningMock.mock.calls[1][1] as () => void)();

    // Agent reply appended — effect on [messages.length] resets the counter.
    await act(async () => {
      useStore.getState().addAgentMessage('a1', 'agent', 'hello');
    });

    // Press 3 — counter was reset; should re-arm browser SR, NOT whisper.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(3));
    expect(mocks.armWhisperSttMock).not.toHaveBeenCalled();
  });

  it('user message append does NOT reset the counter', async () => {
    render(<ProfileChatTab agentId="a1" />);

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    (mocks.startListeningMock.mock.calls[0][1] as () => void)();

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(2));
    (mocks.startListeningMock.mock.calls[1][1] as () => void)();

    // User-side append must NOT reset.
    await act(async () => {
      useStore.getState().addAgentMessage('a1', 'user', 'typed text');
    });

    // Press 3 — counter still >= 2; must route to whisper fallback.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(2);
  });
});
