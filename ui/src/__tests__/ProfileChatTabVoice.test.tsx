/** AD-718: ProfileChatTab voice integration tests. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import React from 'react';

// Mock voice + speechInput before importing component.
const mocks = vi.hoisted(() => ({
  speakResponseMock: vi.fn(),
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  cancelListeningMock: vi.fn(),
  supportedRef: { v: true },
  realSpeech: false,
}));
const { speakResponseMock, startListeningMock, stopListeningMock, supportedRef } = mocks;

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  // AD-718d-1: ModulationIndicator (transitively mounted by ProfileChatTab)
  // subscribes via onSpeechEvent — return a no-op unsubscriber.
  onSpeechEvent: vi.fn(() => () => {}),
}));

vi.mock('../audio/speechInput', async importOriginal => {
  const actual = await importOriginal<typeof import('../audio/speechInput')>();
  return {
    ...actual,
    isSpeechRecognitionSupported: () => mocks.realSpeech ? actual.isSpeechRecognitionSupported() : mocks.supportedRef.v,
    startListening: (...args: Parameters<typeof actual.startListening>) =>
      mocks.realSpeech ? actual.startListening(...args) : mocks.startListeningMock(...args),
    stopListening: () => mocks.realSpeech ? actual.stopListening() : mocks.stopListeningMock(),
  };
});

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';
import { _resetForTests as resetArbiter, currentHolder } from '../audio/speechRecognitionArbiter';

class _FakeRecognition {
  static instances: _FakeRecognition[] = [];
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  abort = vi.fn(() => this.onend?.());
  stop = vi.fn(() => this.onend?.());

  constructor() { _FakeRecognition.instances.push(this); }
}

beforeEach(() => {
  speakResponseMock.mockReset();
  startListeningMock.mockReset();
  stopListeningMock.mockReset();
  mocks.cancelListeningMock.mockReset();
  startListeningMock.mockReturnValue({ cancel: mocks.cancelListeningMock });
  supportedRef.v = true;
  mocks.realSpeech = false;
  _FakeRecognition.instances = [];
  // jsdom does not implement scrollIntoView.
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  useStore.setState({
    voiceEnabled: false,
    agentConversations: new Map(),
  });
  // Clear per-agent TTS preferences so localStorage persistence between tests
  // doesn't override the global-default fallback path.
  localStorage.clear();

  // fetch: chat/history, profile, then chat
  global.fetch = vi.fn((url: any, init?: any) => {
    const u = String(url);
    if (u.endsWith('/chat/history')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ memories: [] }) }) as any;
    }
    if (u.endsWith('/profile')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          voiceProfile: { voice_name: '', pitch: 1.05, rate: 0.92, volume: 0.85 },
        }),
      }) as any;
    }
    if (u.endsWith('/chat') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ response: 'Hello, Captain.' }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
  }) as any;
});

afterEach(async () => {
  cleanup();
  const actual = await vi.importActual<typeof import('../audio/speechInput')>('../audio/speechInput');
  actual.stopListening();
  resetArbiter();
  vi.unstubAllGlobals();
});

describe('AD-718 ProfileChatTab voice', () => {
  it('aborts its real browser recognizer when a listening profile unmounts', async () => {
    mocks.realSpeech = true;
    vi.stubGlobal('SpeechRecognition', _FakeRecognition);
    const view = render(<ProfileChatTab agentId="agent-007" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Voice input' }));
    await screen.findByRole('button', { name: 'Stop listening' });
    expect(_FakeRecognition.instances).toHaveLength(1);
    const recognition = _FakeRecognition.instances[0]!;
    expect(recognition.start).toHaveBeenCalledTimes(1);
    expect(recognition.abort).not.toHaveBeenCalled();

    view.unmount();

    expect(recognition.abort).toHaveBeenCalledTimes(1);
  });

  it.each(['agent', 'thread'] as const)('cancels recognition on %s replacement and discards a captured retired callback', async change => {
    mocks.realSpeech = true;
    vi.stubGlobal('SpeechRecognition', _FakeRecognition);
    const view = render(<ProfileChatTab agentId="agent-007" threadId="thread-one" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Voice input' }));
    await screen.findByRole('button', { name: 'Stop listening' });
    const retired = _FakeRecognition.instances[0]!;
    expect(retired.start).toHaveBeenCalledTimes(1);
    const lateResult = retired.onresult!;
    view.rerender(<ProfileChatTab agentId={change === 'agent' ? 'agent-008' : 'agent-007'} threadId="thread-two" />);
    await screen.findByRole('button', { name: 'Voice input' });
    expect(retired.abort).toHaveBeenCalledTimes(1);
    act(() => lateResult({ results: { length: 1, 0: { 0: { transcript: 'retired input' }, isFinal: true } } }));
    expect(screen.getByPlaceholderText('Message...')).toHaveValue('');
    expect(currentHolder()).toBeNull();
  });

  it('does not abort a newer profile recognizer when the earlier profile unmounts', async () => {
    mocks.realSpeech = true;
    vi.stubGlobal('SpeechRecognition', _FakeRecognition);
    const first = render(<ProfileChatTab agentId="agent-007" />);
    fireEvent.click(await within(first.container).findByRole('button', { name: 'Voice input' }));
    const earlier = _FakeRecognition.instances[0]!;
    const second = render(<ProfileChatTab agentId="agent-008" />);
    fireEvent.click(await within(second.container).findByRole('button', { name: 'Voice input' }));
    expect(_FakeRecognition.instances).toHaveLength(2);
    const current = _FakeRecognition.instances[1]!;
    expect(earlier.abort).toHaveBeenCalledTimes(1);
    first.unmount();
    expect(current.abort).not.toHaveBeenCalled();
    expect(currentHolder()?.holder).toBe('press_to_talk');
    second.unmount();
    expect(current.abort).toHaveBeenCalledTimes(1);
    expect(currentHolder()).toBeNull();
  });

  it('does not acquire capture during StrictMode replay and cancels exactly the explicit mic start', async () => {
    mocks.realSpeech = true;
    vi.stubGlobal('SpeechRecognition', _FakeRecognition);
    const view = render(<ProfileChatTab agentId="agent-007" />, { reactStrictMode: true });
    const button = await screen.findByRole('button', { name: 'Voice input' });
    expect(_FakeRecognition.instances).toHaveLength(0);
    fireEvent.click(button);
    expect(_FakeRecognition.instances).toHaveLength(1);
    view.unmount();
    expect(_FakeRecognition.instances[0]!.abort).toHaveBeenCalledTimes(1);
  });

  it('mic button renders only when speech recognition supported', async () => {
    supportedRef.v = false;
    render(<ProfileChatTab agentId="agent-007" />);
    expect(screen.queryByLabelText('Voice input')).toBeNull();
  });

  it('mic button click toggles listening state', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    const btn = await screen.findByLabelText('Voice input');
    fireEvent.click(btn);
    expect(startListeningMock).toHaveBeenCalledTimes(1);
    // After click, listening=true → button label updates to "Stop listening"
    const stopBtn = await screen.findByLabelText('Stop listening');
    fireEvent.click(stopBtn);
    expect(mocks.cancelListeningMock).toHaveBeenCalledTimes(1);
    expect(stopListeningMock).not.toHaveBeenCalled();
  });

  it('agent reply triggers speakResponse when voiceEnabled is true', async () => {
    useStore.setState({ voiceEnabled: true });
    render(<ProfileChatTab agentId="agent-007" />);
    // Wait for initial fetches (profile, history) to settle.
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const input = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hello' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(speakResponseMock).toHaveBeenCalled());
    const [text, profile, agentId] = speakResponseMock.mock.calls[0];
    expect(text).toContain('Hello, Captain.');
    expect(agentId).toBe('agent-007');
    expect(profile).toMatchObject({ pitch: 1.05, rate: 0.92 });
  });

  it('agent reply does not trigger speakResponse when voiceEnabled is false', async () => {
    render(<ProfileChatTab agentId="agent-007" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const input = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hello' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // Wait for the agent reply to land.
    await waitFor(() => {
      const conv = useStore.getState().agentConversations.get('agent-007');
      const msgs = conv?.messages ?? [];
      expect(msgs.some(m => m.text.includes('Hello, Captain.'))).toBe(true);
    });
    expect(speakResponseMock).not.toHaveBeenCalled();
  });

  it("system error placeholders starting with '(' do not trigger TTS", async () => {
    useStore.setState({ voiceEnabled: true });
    // Force the chat POST to reject so handleSend lands '(communication error)'.
    global.fetch = vi.fn((url: any, init?: any) => {
      const u = String(url);
      if (u.endsWith('/chat/history')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ memories: [] }) }) as any;
      }
      if (u.endsWith('/profile')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
      }
      if (u.endsWith('/chat') && init?.method === 'POST') {
        return Promise.reject(new Error('boom')) as any;
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
    }) as any;

    render(<ProfileChatTab agentId="agent-007" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const input = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'hello' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => {
      const conv = useStore.getState().agentConversations.get('agent-007');
      expect(conv?.messages?.some(m => m.text.includes('communication error'))).toBe(true);
    });
    expect(speakResponseMock).not.toHaveBeenCalled();
  });
});
