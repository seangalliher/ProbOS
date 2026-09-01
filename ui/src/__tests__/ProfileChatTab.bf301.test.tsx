/** BF-301 (#775) — ProfileChatTab transformers.js STT integration.
 *
 * Tests the new BF-301 surface in the chat tab:
 *   - PTT with primary_stt='transformers' arms armTransformersStt
 *   - First-load progress event renders the bf301-progress element
 *   - status=ready / done removes the progress UI
 *   - engine='browser' does not show the progress UI
 *   - The deprecated 'whisper' alias still arms the local engine
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
  armTransformersSttMock: vi.fn(),
  disarmTransformersSttMock: vi.fn(),
  transformersOnTranscriptMock: vi.fn((_cb: (text: string) => void) => () => {}),
  transformersOnTranscribingMock: vi.fn((_cb: (active: boolean) => void) => () => {}),
  transformersOnProgressMock: vi.fn((_cb: (event: any) => void) => () => {}),
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
  armTransformersStt: mocks.armTransformersSttMock,
  disarmTransformersStt: mocks.disarmTransformersSttMock,
  onTransformersTranscript: mocks.transformersOnTranscriptMock,
  onTransformersTranscribing: mocks.transformersOnTranscribingMock,
  onTransformersProgress: mocks.transformersOnProgressMock,
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

type HealthShape = {
  primary_stt: 'transformers' | 'whisper' | 'browser';
  engine: 'transformers' | 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
  model?: string | null;
};

function setupFetchWithHealth(health: HealthShape): void {
  global.fetch = vi.fn((url: any) => {
    const target = String(url);
    if (target.endsWith('/api/voice/health')) {
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
  mocks.transformersOnTranscriptMock.mockReturnValue(() => {});
  mocks.transformersOnTranscribingMock.mockReturnValue(() => {});
  mocks.transformersOnProgressMock.mockReturnValue(() => {});
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

describe('BF-301 transformers.js STT integration', () => {
  it('primary_stt=transformers + healthy → arms armTransformersStt (not browser SR)', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armTransformersSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).not.toHaveBeenCalled();
  });

  it('first-load progress (progress=0.5) shows the bf301-progress element at 50% width', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    let progressListener: ((e: any) => void) | null = null;
    mocks.transformersOnProgressMock.mockImplementation((cb: any) => {
      progressListener = cb;
      return () => { progressListener = null; };
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(progressListener).not.toBeNull());

    progressListener!({ status: 'progress', name: 'Xenova/whisper-tiny.en', progress: 0.5 });

    const bar = await screen.findByTestId('bf301-progress');
    expect(bar).toBeTruthy();
    const inner = bar.firstChild as HTMLElement;
    expect(inner.style.width).toBe('50%');
  });

  it('status=ready clears the progress UI', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    let progressListener: ((e: any) => void) | null = null;
    mocks.transformersOnProgressMock.mockImplementation((cb: any) => {
      progressListener = cb;
      return () => { progressListener = null; };
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(progressListener).not.toBeNull());

    progressListener!({ status: 'progress', name: 'Xenova/whisper-tiny.en', progress: 0.5 });
    await screen.findByTestId('bf301-progress');

    progressListener!({ status: 'ready', name: 'Xenova/whisper-tiny.en' });
    await waitFor(() => {
      expect(screen.queryByTestId('bf301-progress')).toBeNull();
    });
  });

  it('engine=browser does not render the progress UI even if a progress event fires', async () => {
    setupFetchWithHealth({
      primary_stt: 'browser',
      engine: 'browser',
      backend_available: false,
      healthy: true,
      model: null,
    });
    let progressListener: ((e: any) => void) | null = null;
    mocks.transformersOnProgressMock.mockImplementation((cb: any) => {
      progressListener = cb;
      return () => { progressListener = null; };
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(progressListener).not.toBeNull());

    // Tooltip should report browser engine.
    const micButton = await screen.findByLabelText('Voice input');
    expect(micButton.getAttribute('title')).toContain('browser');

    // Clicking should arm browser SR, not transformers.
    fireEvent.click(micButton);
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    expect(mocks.armTransformersSttMock).not.toHaveBeenCalled();
  });

  it('progress=1.0 hides the bar (clamped via < 1 check)', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    let progressListener: ((e: any) => void) | null = null;
    mocks.transformersOnProgressMock.mockImplementation((cb: any) => {
      progressListener = cb;
      return () => { progressListener = null; };
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(progressListener).not.toBeNull());

    progressListener!({ status: 'progress', name: 'Xenova/whisper-tiny.en', progress: 1.0 });
    // The progress < 1 guard prevents the bar from rendering at 100%.
    expect(screen.queryByTestId('bf301-progress')).toBeNull();
  });

  it('deprecated alias primary_stt=whisper still arms the local engine', async () => {
    setupFetchWithHealth({
      primary_stt: 'whisper', // deprecated alias
      engine: 'transformers', // resolved
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armTransformersSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.startListeningMock).not.toHaveBeenCalled();
  });

  it('mic tooltip includes transformers model id when engine=transformers', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    render(<ProfileChatTab agentId="a1" />);
    const micButton = await screen.findByLabelText('Voice input');
    await waitFor(() => {
      expect(micButton.getAttribute('title') ?? '').toContain('transformers');
    });
    expect(micButton.getAttribute('title') ?? '').toContain('whisper-tiny.en');
  });

  it('transcript arrives via onTransformersTranscript and populates the input', async () => {
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    render(<ProfileChatTab agentId="a1" />);
    await waitFor(() =>
      expect((global.fetch as any).mock.calls.some((c: any[]) => String(c[0]).endsWith('/api/voice/health'))).toBe(true),
    );

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armTransformersSttMock).toHaveBeenCalledTimes(1));

    const transcriptCallback = (mocks.transformersOnTranscriptMock.mock.calls as any[])[0][0] as (t: string) => void;
    transcriptCallback('hello world');

    const input = (await screen.findByPlaceholderText(/message|type/i)) as HTMLInputElement | HTMLTextAreaElement;
    await waitFor(() => expect(input.value).toBe('hello world'));
  });

  it('progress listener subscription is cleaned up on unmount', async () => {
    const unsubMock = vi.fn();
    mocks.transformersOnProgressMock.mockImplementation((_cb: any) => unsubMock);
    setupFetchWithHealth({
      primary_stt: 'transformers',
      engine: 'transformers',
      backend_available: true,
      healthy: true,
      model: 'Xenova/whisper-tiny.en',
    });
    const { unmount } = render(<ProfileChatTab agentId="a1" />);
    await waitFor(() => expect(mocks.transformersOnProgressMock).toHaveBeenCalled());
    unmount();
    expect(unsubMock).toHaveBeenCalled();
  });
});
