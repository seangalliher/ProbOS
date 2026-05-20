/** AD-718: ProfileChatTab voice integration tests. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

// Mock voice + speechInput before importing component.
const mocks = vi.hoisted(() => ({
  speakResponseMock: vi.fn(),
  startListeningMock: vi.fn(),
  stopListeningMock: vi.fn(),
  supportedRef: { v: true },
}));
const { speakResponseMock, startListeningMock, stopListeningMock, supportedRef } = mocks;

vi.mock('../audio/voice', () => ({
  getServerPiperVoices: vi.fn(async () => null),
  speakResponse: mocks.speakResponseMock,
  stripMarkdownForSpeech: (s: string) => s,
  // AD-718d-1: ModulationIndicator (transitively mounted by ProfileChatTab)
  // subscribes via onSpeechEvent — return a no-op unsubscriber.
  onSpeechEvent: vi.fn(() => () => {}),
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => mocks.supportedRef.v,
  startListening: mocks.startListeningMock,
  stopListening: mocks.stopListeningMock,
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

beforeEach(() => {
  speakResponseMock.mockReset();
  startListeningMock.mockReset();
  stopListeningMock.mockReset();
  supportedRef.v = true;
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

describe('AD-718 ProfileChatTab voice', () => {
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
    expect(stopListeningMock).toHaveBeenCalledTimes(1);
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
