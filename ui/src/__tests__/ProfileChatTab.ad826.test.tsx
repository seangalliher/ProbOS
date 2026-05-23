/** AD-826 — whisper-first STT priority for ProfileChatTab PTT handler.
 *
 * Tests the branching by ``cognitive.primary_stt`` from
 * ``/api/voice/health``:
 *   1. whisper-primary + healthy → armWhisperStt first
 *   2. whisper-primary + unhealthy → browser SR (honest-degrade)
 *   3. browser-primary (regression) → AD-760 path preserved
 *   4. whisper-primary: 2 empty whisper → browser SR on 3rd press
 *   5. browser-primary: 2 empty browser SR → whisper on 3rd (regression)
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
  whisperOnTranscribingMock: vi.fn(() => () => {}),
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
  onTranscribing: mocks.whisperOnTranscribingMock,
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

type HealthShape = {
  primary_stt: 'whisper' | 'browser';
  engine: 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
};

function setupFetchWithHealth(health: HealthShape | null): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/api/voice/health')) {
      if (health === null) {
        return Promise.resolve({ ok: false, json: async () => ({}) }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => health }) as any;
    }
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
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('AD-826 whisper-first STT priority', () => {
  it('whisper-primary + healthy → arms whisperStt, not browser SR', async () => {
    setupFetchWithHealth({
      primary_stt: 'whisper',
      engine: 'whisper',
      backend_available: true,
      healthy: true,
    });
    render(<ProfileChatTab agentId="a1" />);

    // Wait for voice-health fetch to resolve.
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).not.toHaveBeenCalled();
  });

  it('whisper-primary + unhealthy → honest-degrades to browser SR', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    setupFetchWithHealth({
      primary_stt: 'whisper',
      engine: 'whisper',
      backend_available: false,
      healthy: false,
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    expect(mocks.armWhisperSttMock).not.toHaveBeenCalled();
    expect(infoSpy).toHaveBeenCalledWith(expect.stringContaining('AD-826: whisper primary but unhealthy'));
    infoSpy.mockRestore();
  });

  it('browser-primary (regression) → arms browser SR, AD-760 path preserved', async () => {
    setupFetchWithHealth({
      primary_stt: 'browser',
      engine: 'browser',
      backend_available: false,
      healthy: true,
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    expect(mocks.armWhisperSttMock).not.toHaveBeenCalled();
  });

  it('whisper-primary: 2 empty whisper transcripts → browser SR on 3rd press', async () => {
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {});
    setupFetchWithHealth({
      primary_stt: 'whisper',
      engine: 'whisper',
      backend_available: true,
      healthy: true,
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    // Press 1 — whisper armed, fire empty transcript.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    const onTranscript1 = (mocks.whisperOnTranscriptMock.mock.calls as any[])[0][0] as (text: string) => void;
    onTranscript1('');

    // Press 2 — whisper armed again, empty.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(2));
    const onTranscript2 = (mocks.whisperOnTranscriptMock.mock.calls as any[])[1][0] as (text: string) => void;
    onTranscript2('');

    // Press 3 — counter now >= 2, must fall through to browser SR.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(2);
    expect(infoSpy).toHaveBeenCalledWith(
      expect.stringContaining('AD-826: browser-SR fallback'),
    );
    infoSpy.mockRestore();
  });

  it('browser-primary: 2 empty browser SR → whisper on 3rd press (AD-760 regression)', async () => {
    setupFetchWithHealth({
      primary_stt: 'browser',
      engine: 'browser',
      backend_available: false,
      healthy: true,
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    (mocks.startListeningMock.mock.calls[0][1] as () => void)();

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(2));
    (mocks.startListeningMock.mock.calls[1][1] as () => void)();

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).toHaveBeenCalledTimes(2);
  });
});
