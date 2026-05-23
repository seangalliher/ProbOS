/** BF-292 — PTT auto-send broken by stale handleSend closure.
 *
 * Both PTT paths (browser SpeechRecognition + whisperStt fallback) call
 * setInput(text) then schedule setTimeout(() => handleSend(), 100). Before
 * the fix, the captured handleSend closed over input='' and bailed at the
 * guard. The fix factors sendText(textArg) so the transcript is passed
 * as an argument instead of being read from stale state.
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

interface ChatCall {
  url: string;
  body: any;
}

function captureChatCalls(): { calls: ChatCall[]; fetchMock: ReturnType<typeof vi.fn> } {
  const calls: ChatCall[] = [];
  const fetchMock = vi.fn((url: any, init?: any) => {
    const target = String(url);
    if (target.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
    }
    if (target.endsWith('/profile')) {
      return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
    }
    if (target.includes('/chat')) {
      let body: any = null;
      try { body = init?.body ? JSON.parse(init.body) : null; } catch { /* tier-2 */ }
      calls.push({ url: target, body });
      return Promise.resolve({ ok: true, json: async () => ({ response: 'ack' }) }) as any;
    }
    return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
  });
  global.fetch = fetchMock as any;
  return { calls, fetchMock };
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
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('BF-292 PTT transcript reaches POST (stale closure fix)', () => {
  it('browser-SR transcript triggers POST with transcript body', async () => {
    const { calls } = captureChatCalls();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(<ProfileChatTab agentId="a1" />);
    const mic = await screen.findByLabelText('Voice input');
    fireEvent.click(mic);
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));

    const onResult = mocks.startListeningMock.mock.calls[0][0] as (t: string) => void;
    onResult('hello world');

    await vi.advanceTimersByTimeAsync(100);

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    expect(calls[0].url).toContain('/api/agent/a1/chat');
    expect(calls[0].body).toMatchObject({ message: 'hello world' });
  });

  it('whisperStt fallback transcript triggers POST with transcript body', async () => {
    const { calls } = captureChatCalls();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(<ProfileChatTab agentId="a1" />);

    // Drive two empty browser-SR results to enter whisper fallback branch.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    const onError1 = mocks.startListeningMock.mock.calls[0][1] as () => void;
    onError1();
    fireEvent.click(await screen.findByLabelText('Voice input'));
    const onError2 = mocks.startListeningMock.mock.calls[1][1] as () => void;
    onError2();

    // Press 3 — hits whisper fallback.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.armWhisperSttMock).toHaveBeenCalledTimes(1));
    expect(mocks.whisperOnTranscriptMock).toHaveBeenCalledTimes(1);

    const whisperCb = (mocks.whisperOnTranscriptMock.mock.calls as any[][])[0][0] as (t: string) => void;
    whisperCb('whisper transcript');

    await vi.advanceTimersByTimeAsync(100);

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    expect(calls[0].url).toContain('/api/agent/a1/chat');
    expect(calls[0].body).toMatchObject({ message: 'whisper transcript' });
  });

  it('empty transcript still bails — no chat POST', async () => {
    const { calls } = captureChatCalls();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(<ProfileChatTab agentId="a1" />);
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));

    const onResult = mocks.startListeningMock.mock.calls[0][0] as (t: string) => void;
    onResult('   ');

    await vi.advanceTimersByTimeAsync(100);
    // Flush any pending microtasks.
    await Promise.resolve();

    expect(calls.length).toBe(0);
  });

  it('sending=true guard still honored — no double-send', async () => {
    const calls: ChatCall[] = [];
    let resolveFirst: (v: any) => void = () => {};
    const firstPromise = new Promise((res) => { resolveFirst = res; });
    global.fetch = vi.fn((url: any, init?: any) => {
      const target = String(url);
      if (target.endsWith('/chat/history')) {
        return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
      }
      if (target.endsWith('/profile')) {
        return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
      }
      if (target.includes('/chat')) {
        let body: any = null;
        try { body = init?.body ? JSON.parse(init.body) : null; } catch { /* tier-2 */ }
        calls.push({ url: target, body });
        // First chat POST stays pending; subsequent ones would also stay pending.
        return firstPromise.then(() => ({ ok: true, json: async () => ({ response: 'ack' }) }));
      }
      return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
    }) as any;

    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ProfileChatTab agentId="a1" />);

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    const onResult1 = mocks.startListeningMock.mock.calls[0][0] as (t: string) => void;
    onResult1('first message');
    await vi.advanceTimersByTimeAsync(100);
    await waitFor(() => expect(calls.length).toBe(1));

    // Second mic press while first POST is still pending.
    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock.mock.calls.length).toBe(2));
    const onResult2 = mocks.startListeningMock.mock.calls[1][0] as (t: string) => void;
    onResult2('second message');
    await vi.advanceTimersByTimeAsync(100);
    await Promise.resolve();

    // Second was guarded by sending=true.
    expect(calls.length).toBe(1);
    expect(calls[0].body).toMatchObject({ message: 'first message' });

    resolveFirst({});
  });

  it('pending attachments attach to PTT-sent message', async () => {
    const calls: ChatCall[] = [];
    global.fetch = vi.fn((url: any, init?: any) => {
      const target = String(url);
      if (target.endsWith('/chat/history')) {
        return Promise.resolve({ ok: true, json: async () => ({ memories: [] }) }) as any;
      }
      if (target.endsWith('/profile')) {
        return Promise.resolve({ ok: true, json: async () => ({ voiceProfile: null }) }) as any;
      }
      if (target.includes('/attachments')) {
        // Upload endpoint (/api/chat/attachments/multipart).
        return Promise.resolve({
          ok: true,
          json: async () => ({ attachment_id: 'att-xyz', filename: 'pic.png' }),
        }) as any;
      }
      if (target.includes('/chat')) {
        let body: any = null;
        try { body = init?.body ? JSON.parse(init.body) : null; } catch { /* tier-2 */ }
        calls.push({ url: target, body });
        return Promise.resolve({ ok: true, json: async () => ({ response: 'ack' }) }) as any;
      }
      return Promise.resolve({ ok: true, json: async () => ({}) }) as any;
    }) as any;

    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<ProfileChatTab agentId="a1" />);

    // Pre-seed a pending attachment via the hidden file input.
    const fileInputs = document.querySelectorAll('input[type="file"]');
    expect(fileInputs.length).toBeGreaterThan(0);
    const fileInput = fileInputs[0] as HTMLInputElement;
    const file = new File([new Uint8Array([1, 2, 3])], 'pic.png', { type: 'image/png' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fireEvent.change(fileInput);

    await waitFor(() => {
      // The chip with the filename appears once the upload resolves.
      expect(screen.queryByText(/pic\.png/)).toBeTruthy();
    });

    fireEvent.click(await screen.findByLabelText('Voice input'));
    await waitFor(() => expect(mocks.startListeningMock).toHaveBeenCalledTimes(1));
    const onResult = mocks.startListeningMock.mock.calls[0][0] as (t: string) => void;
    onResult('see this');

    await vi.advanceTimersByTimeAsync(100);
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    expect(calls[0].body).toMatchObject({
      message: 'see this',
      attachment_ids: ['att-xyz'],
    });
  });

  it('textarea Enter key still sends via handleSend → sendText (regression)', async () => {
    const { calls } = captureChatCalls();
    render(<ProfileChatTab agentId="a1" />);

    const input = (await screen.findByPlaceholderText('Message...')) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'typed message' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    expect(calls[0].body).toMatchObject({ message: 'typed message' });
  });
});
