/** BF-294 — ProfileChatTab mic visual-state regression tests.
 *
 * Three states: idle / listening / processing.
 * Priority: processing > listening > idle.
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
  onSpeechEventMock: vi.fn(() => () => {}),
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
  mocks.whisperOnTranscribingMock.mockReturnValue(() => {});
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

describe('BF-294 ProfileChatTab mic visual states', () => {
  it('idle by default, then listening after PTT click', async () => {
    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');

    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');
  });

  it('onTranscribing(true) flips state to processing (priority over listening)', async () => {
    render(<ProfileChatTab agentId="a1" />);
    await screen.findByLabelText('Voice input');

    // Capture the listener registered by ProfileChatTab's useEffect.
    expect(mocks.whisperOnTranscribingMock).toHaveBeenCalled();
    const transcribingListener = (mocks.whisperOnTranscribingMock.mock.calls[0] as unknown as [(a: boolean) => void])[0];

    // Arm listening via PTT click.
    fireEvent.click(screen.getByLabelText('Voice input'));
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('listening');

    // Whisper transcribing kicks in — processing wins over listening.
    act(() => { transcribingListener(true); });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');
  });

  it('onTranscribing(false) plus listening cleared returns to idle', async () => {
    render(<ProfileChatTab agentId="a1" />);
    await screen.findByLabelText('Voice input');
    const transcribingListener = (mocks.whisperOnTranscribingMock.mock.calls[0] as unknown as [(a: boolean) => void])[0];

    // Drive listening + processing.
    fireEvent.click(screen.getByLabelText('Voice input'));
    act(() => { transcribingListener(true); });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');

    // Simulate whisper finishing: transcribing(false) plus the browser-SR
    // onresult callback that sets listening=false.
    act(() => { transcribingListener(false); });
    const onResult = (mocks.startListeningMock.mock.calls[0] as unknown as [(text: string) => void])[0];
    act(() => { onResult('hello world'); });

    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });

  it('force-stop while processing clears both listening and processing', async () => {
    render(<ProfileChatTab agentId="a1" />);
    await screen.findByLabelText('Voice input');
    const transcribingListener = (mocks.whisperOnTranscribingMock.mock.calls[0] as unknown as [(a: boolean) => void])[0];

    // Arm both.
    fireEvent.click(screen.getByLabelText('Voice input'));
    act(() => { transcribingListener(true); });
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('processing');

    // Force-stop: click the armed button. aria-label is "Transcribing speech"
    // while processing per BF-294 wiring.
    const armed = screen.getByLabelText('Transcribing speech');
    fireEvent.click(armed);

    expect(mocks.stopListeningMock).toHaveBeenCalledTimes(1);
    expect(mocks.disarmWhisperSttMock).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('mic-indicator').getAttribute('data-bf294-state')).toBe('idle');
  });
});
