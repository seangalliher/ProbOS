/** AD-761: ProfileChatTab screen-share parity tests. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

const mocks = vi.hoisted(() => ({
  captureScreenShareFrameMock: vi.fn(),
  startScreenStreamMock: vi.fn(),
  stopScreenStreamMock: vi.fn(),
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
  isSpeechRecognitionSupported: () => false,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

vi.mock('../hooks/useScreenShare', () => ({
  captureScreenShareFrame: mocks.captureScreenShareFrameMock,
}));

vi.mock('../hooks/useScreenStream', () => ({
  startScreenStream: mocks.startScreenStreamMock,
  stopScreenStream: mocks.stopScreenStreamMock,
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useScreenStore } from '../store/useScreenStore';
import { useStore } from '../store/useStore';

function setScreenStreamActive(active: boolean): void {
  useScreenStore.setState({
    active,
    sessionId: active ? 'screen-session-1' : null,
    error: null,
    framesSent: 0,
  });
}

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

function renderProfileChatTab(agentId = 'agent-007') {
  return render(<ProfileChatTab agentId={agentId} />);
}

beforeEach(() => {
  mocks.captureScreenShareFrameMock.mockReset();
  mocks.startScreenStreamMock.mockReset();
  mocks.stopScreenStreamMock.mockReset();
  mocks.speakResponseMock.mockReset();
  setScreenStreamActive(false);
  useStore.setState({
    voiceEnabled: false,
    agentConversations: new Map(),
  });
  localStorage.clear();
  setDefaultFetch();
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  mocks.captureScreenShareFrameMock.mockResolvedValue({
    attachment_id: 'sha256-screen-1',
    mime: 'image/jpeg',
    size_bytes: 128,
  });
  mocks.startScreenStreamMock.mockImplementation(async () => {
    setScreenStreamActive(true);
  });
  mocks.stopScreenStreamMock.mockImplementation(async () => {
    setScreenStreamActive(false);
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  setScreenStreamActive(false);
});

describe('AD-761 ProfileChatTab screen share', () => {
  it('left click captures one screen frame and stages the returned attachment', async () => {
    renderProfileChatTab();

    const button = screen.getByLabelText('share screen');
    fireEvent.click(button);

    await waitFor(() => {
      expect(mocks.captureScreenShareFrameMock).toHaveBeenCalledWith({ agentId: 'agent-007' });
    });
    expect(await screen.findByText('screen-share.jpg')).toBeTruthy();
  });

  it('surfaces attachError when screen capture fails', async () => {
    mocks.captureScreenShareFrameMock.mockResolvedValueOnce(null);
    renderProfileChatTab();

    fireEvent.click(screen.getByLabelText('share screen'));

    expect(await screen.findByText('Screen share cancelled or failed.')).toBeTruthy();
  });

  it('right click opens the screen-share popover with capture and live modes', async () => {
    renderProfileChatTab();

    fireEvent.contextMenu(screen.getByLabelText('share screen'));

    const menu = await screen.findByTestId('profile-chat-screen-share-menu');
    expect(menu).toBeTruthy();
    expect(screen.getByTestId('profile-chat-screen-share-capture-once').textContent).toBe('Capture once');
    expect(screen.getByTestId('profile-chat-screen-share-live').textContent).toBe('Live screen share');
  });

  it('selecting live screen share starts the stream and persists the agent preference', async () => {
    renderProfileChatTab();

    fireEvent.contextMenu(screen.getByLabelText('share screen'));
    fireEvent.click(screen.getByTestId('profile-chat-screen-share-live'));

    await waitFor(() => {
      expect(mocks.startScreenStreamMock).toHaveBeenCalledWith({ fps: 1 });
    });
    expect(localStorage.getItem('hxi_chat_screen_mode_agent-007')).toBe('live');
    expect(screen.getByTestId('profile-chat-screen-live-indicator')).toBeTruthy();
  });

  it('unmounting while live stops the screen stream', async () => {
    const { unmount } = renderProfileChatTab();

    fireEvent.contextMenu(screen.getByLabelText('share screen'));
    fireEvent.click(screen.getByTestId('profile-chat-screen-share-live'));

    await waitFor(() => expect(mocks.startScreenStreamMock).toHaveBeenCalledTimes(1));

    unmount();

    await waitFor(() => {
      expect(mocks.stopScreenStreamMock).toHaveBeenCalledTimes(1);
    });
  });

  it('stops the prior live stream before starting the next agent stream', async () => {
    const { rerender } = renderProfileChatTab('agent-alpha');

    fireEvent.contextMenu(screen.getByLabelText('share screen'));
    fireEvent.click(screen.getByTestId('profile-chat-screen-share-live'));

    await waitFor(() => expect(mocks.startScreenStreamMock).toHaveBeenCalledTimes(1));

    localStorage.setItem('hxi_chat_screen_mode_agent-beta', 'live');
    rerender(<ProfileChatTab agentId="agent-beta" />);

    await waitFor(() => expect(mocks.startScreenStreamMock).toHaveBeenCalledTimes(2));
    expect(mocks.stopScreenStreamMock).toHaveBeenCalled();
    expect(mocks.stopScreenStreamMock.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.startScreenStreamMock.mock.invocationCallOrder[1],
    );
  });
});