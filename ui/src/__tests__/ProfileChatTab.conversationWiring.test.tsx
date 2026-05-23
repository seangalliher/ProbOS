/** AD-760 — ProfileChatTab conversation-mode + mic popover tests. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  armConversationModeMock: vi.fn(() => () => {}),
  disarmConversationModeMock: vi.fn(),
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

describe('AD-760 ProfileChatTab mic-mode popover', () => {
  it('right-click on mic opens popover with PTT + Conversation items', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.contextMenu(mic);
    const menu = await screen.findByTestId('profile-chat-mic-mode-menu');
    expect(menu).toBeTruthy();
    expect(screen.getByTestId('profile-chat-mic-mode-ptt')).toBeTruthy();
    expect(screen.getByTestId('profile-chat-mic-mode-conversation')).toBeTruthy();
  });

  it('Shift+F10 on focused mic opens the same popover', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.keyDown(mic, { key: 'F10', shiftKey: true });
    expect(await screen.findByTestId('profile-chat-mic-mode-menu')).toBeTruthy();
  });

  it('selecting Conversation persists mode and arms the controller', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.contextMenu(mic);
    fireEvent.click(await screen.findByTestId('profile-chat-mic-mode-conversation'));
    await waitFor(() => {
      expect(localStorage.getItem('hxi_chat_mic_mode_agent-007')).toBe('conversation');
    });
    await waitFor(() => {
      expect(mocks.armConversationModeMock).toHaveBeenCalled();
    });
    const calls = mocks.armConversationModeMock.mock.calls;
    const opts = (calls[calls.length - 1] as unknown as [{ agentId: string }])[0];
    expect(opts.agentId).toBe('agent-007');
  });

  it('mode hydrates on agent switch and disarms previous agent', async () => {
    localStorage.setItem('hxi_chat_mic_mode_agent-A', 'conversation');
    localStorage.setItem('hxi_chat_mic_mode_agent-B', 'ptt');
    const { rerender } = render(<ProfileChatTab agentId="agent-A" />);
    await waitFor(() => {
      expect(mocks.armConversationModeMock).toHaveBeenCalled();
    });
    const armCallsBefore = mocks.armConversationModeMock.mock.calls.length;
    const disarmCallsBefore = mocks.disarmConversationModeMock.mock.calls.length;
    rerender(<ProfileChatTab agentId="agent-B" />);
    // Switching to a PTT agent disarms (the effect cleanup + the new
    // PTT effect both call disarmConversationMode).
    await waitFor(() => {
      expect(mocks.disarmConversationModeMock.mock.calls.length).toBeGreaterThan(disarmCallsBefore);
    });
    // No additional arm for agent-B since it's PTT.
    expect(mocks.armConversationModeMock.mock.calls.length).toBe(armCallsBefore);
  });

  it('voiceEnabled flip false disarms but preserves persisted preference', async () => {
    localStorage.setItem('hxi_chat_mic_mode_agent-007', 'conversation');
    render(<ProfileChatTab agentId="agent-007" />);
    await waitFor(() => expect(mocks.armConversationModeMock).toHaveBeenCalled());
    useStore.setState({ voiceEnabled: false });
    await waitFor(() => expect(mocks.disarmConversationModeMock).toHaveBeenCalled());
    expect(localStorage.getItem('hxi_chat_mic_mode_agent-007')).toBe('conversation');
  });
});

describe('AD-760 ProfileChatTab PTT call site', () => {
  it('passes continuous + interimResults + endOfSpeechGapMs=1500', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.click(mic);
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(1);
    const args = mocks.startListeningMock.mock.calls[0];
    const opts = args[3];
    expect(opts).toMatchObject({
      continuous: true,
      interimResults: true,
      endOfSpeechGapMs: 1500,
    });
  });

  it('whisperStt fallback triggers after 2 consecutive empty transcripts', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const mic = await screen.findByLabelText('Voice input');

    // 1st click — captures handlers, fires onEnd with no result.
    fireEvent.click(mic);
    const onEnd1 = mocks.startListeningMock.mock.calls[0][1] as () => void;
    onEnd1();

    // 2nd click — same, empty.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    const onEnd2 = mocks.startListeningMock.mock.calls[1][1] as () => void;
    onEnd2();

    // 3rd click — must NOT call startListening; should arm whisper.
    const beforeCount = mocks.startListeningMock.mock.calls.length;
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock.mock.calls.length).toBe(beforeCount);
  });
});
