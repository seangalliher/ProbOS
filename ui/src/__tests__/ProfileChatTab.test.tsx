/** AD-730 (Wave 151): ProfileChatTab attachment send integration tests.
 *
 * These tests verify the per-agent DM attachment flow that AD-730 pipes
 * through to the vision tier on the backend. The UI itself doesn't change
 * for AD-730 — these cases lock down the existing send/clear behavior so
 * the backend vision pipe-through has a stable surface to rely on.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../audio/voice', () => ({
  speakResponse: vi.fn(),
  stripMarkdownForSpeech: (s: string) => s,
  // AD-718d-1: ModulationIndicator (transitively mounted by ProfileChatTab)
  // subscribes via onSpeechEvent — return a no-op unsubscriber.
  onSpeechEvent: vi.fn(() => () => {}),
}));

vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => false,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

import { ProfileChatTab } from '../components/profile/ProfileChatTab';
import { useStore } from '../store/useStore';

interface ChatPostBody {
  message: string;
  history: unknown[];
  attachment_ids: string[];
}

let lastChatPost: ChatPostBody | null = null;

beforeEach(() => {
  lastChatPost = null;
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  useStore.setState({
    voiceEnabled: false,
    agentConversations: new Map(),
  });
  localStorage.clear();

  global.fetch = vi.fn((url: any, init?: any) => {
    const u = String(url);
    if (u.endsWith('/chat/history')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ memories: [] }),
      }) as any;
    }
    if (u.endsWith('/profile')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ voiceProfile: null }),
      }) as any;
    }
    if (u.endsWith('/chat/attachments/multipart')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          attachment_id: 'sha256-fixture-image',
          mime: 'image/png',
          size: 64,
        }),
      }) as any;
    }
    if (u.endsWith('/chat') && init?.method === 'POST') {
      lastChatPost = JSON.parse(init.body) as ChatPostBody;
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          response: 'I can see the image you attached, Captain.',
        }),
      }) as any;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }) as any;
  }) as any;
});

function findFileInput(container: HTMLElement): HTMLInputElement {
  const el = container.querySelector('input[type="file"]') as HTMLInputElement | null;
  if (!el) throw new Error('file input not found');
  return el;
}

describe('AD-730 ProfileChatTab attachment send', () => {
  it('sends image attachment and renders agent response', async () => {
    const { container } = render(<ProfileChatTab agentId="agent-007" />);

    // Wait for initial profile/history fetches to settle.
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    // Simulate user picking an image file.
    const fileInput = findFileInput(container);
    const file = new File([new Uint8Array([1, 2, 3, 4])], 'shot.png', { type: 'image/png' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Wait for the attachment chip to appear.
    await screen.findByText('shot.png');

    // Type the prompt and send.
    const input = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'what is this?' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    await waitFor(() => expect(lastChatPost).not.toBeNull());
    expect(lastChatPost?.message).toBe('what is this?');
    expect(lastChatPost?.attachment_ids).toEqual(['sha256-fixture-image']);

    // Agent reply renders.
    await screen.findByText('I can see the image you attached, Captain.');
  });

  it('shows attachment chip after upload and clears on send', async () => {
    const { container } = render(<ProfileChatTab agentId="agent-007" />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());

    const fileInput = findFileInput(container);
    const file = new File([new Uint8Array([5, 6, 7])], 'diagram.png', { type: 'image/png' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Chip with filename present.
    await screen.findByText('diagram.png');
    expect(screen.queryByLabelText('remove attachment')).toBeTruthy();

    // Send the message.
    const input = screen.getByPlaceholderText('Message...') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'review this' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // After send, chip is gone; attachment_ids was forwarded.
    await waitFor(() => expect(lastChatPost).not.toBeNull());
    expect(lastChatPost?.attachment_ids).toEqual(['sha256-fixture-image']);
    await waitFor(() => expect(screen.queryByText('diagram.png')).toBeNull());
    expect(screen.queryByLabelText('remove attachment')).toBeNull();
  });
});
