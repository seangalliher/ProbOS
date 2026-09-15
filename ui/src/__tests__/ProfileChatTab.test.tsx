/** AD-730 (Wave 151): ProfileChatTab attachment send integration tests.
 *
 * These tests verify the per-agent DM attachment flow that AD-730 pipes
 * through to the vision tier on the backend. The UI itself doesn't change
 * for AD-730 — these cases lock down the existing send/clear behavior so
 * the backend vision pipe-through has a stable surface to rely on.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
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
    chatsOpen: false,
    agentConversations: new Map(),
    activeProfileThreadId: null,
    threadIdByAgent: new Map(),
    chatThreads: new Map(),
    artifactsByThread: new Map(),
    threadMessages: new Map(),
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
  it('preserves a focused host control when the conversation mounts', async () => {
    render(<><button type="button" autoFocus>Chat view</button><ProfileChatTab agentId="agent-007" /></>);
    expect(screen.getByRole('button', { name: 'Chat view' })).toHaveFocus();
    expect(screen.getByPlaceholderText('Message...')).not.toHaveFocus();
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  });

  it('focuses the conversation when its launcher closes without changing the draft', async () => {
    useStore.setState({ chatsOpen: true });
    const view = render(<ProfileChatTab agentId="agent-007" />);
    const input = screen.getByPlaceholderText('Message...');
    expect(input).not.toHaveFocus();
    fireEvent.change(input, { target: { value: 'Unsent draft' } });
    act(() => useStore.getState().closeChats());
    expect(input).toHaveFocus();
    expect(input).toHaveValue('Unsent draft');
    expect(input).toHaveStyle({ minWidth: '120px', maxWidth: '100%' });
    expect(input.parentElement).toHaveStyle({ flexWrap: 'wrap' });
    view.rerender(<ProfileChatTab agentId="agent-008" />);
    expect(screen.getByPlaceholderText('Message...')).toHaveFocus();
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  });

  it('keeps task status in an independently keyboard-scrollable region', async () => {
    useStore.setState({ chatThreads: new Map([['task-thread', {
      id: 'task-thread', title: 'Task', participants: ['agent-007'], created_at: 1, last_active_at: 1, task_id: 'task-parent',
    }]]) });
    render(<ProfileChatTab agentId="agent-007" threadId="task-thread" />);
    const status = screen.getByRole('region', { name: 'Task status' });
    expect(status).toHaveAttribute('tabindex', '0');
    expect(status).toHaveStyle({ maxHeight: 'min(180px, 25%)', overflowY: 'auto', minHeight: '0' });
    expect(screen.getByRole('log', { name: 'Conversation transcript' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  });

  it.each(['prop', 'profile', 'default'])('forwards real artifact activation using the resolved %s thread', async (source) => {
    const onArtifactOpen = vi.fn();
    const artifact = {
      id: 'doc-open', thread_id: 'resolved-thread', name: 'Report.docx', version: 1,
      content_hash: 'hash', mime: 'application/octet-stream', size_bytes: 1,
      created_by: 'agent-007', created_at: 1, supersedes: null, _pinned_from_project: false,
    };
    useStore.setState({
      activeProfileThreadId: source === 'profile' ? 'resolved-thread' : null,
      threadIdByAgent: new Map([['agent-007', source === 'default' ? 'resolved-thread' : 'fallback-thread']]),
      artifactsByThread: new Map([['resolved-thread', [artifact]]]),
      threadMessages: new Map([['resolved-thread', [{
        id: 'artifact-message', role: 'agent', text: '[Artifact: Report.docx v1 - 0 lines, application/octet-stream]', timestamp: 1,
      }]]]),
    });
    render(<ProfileChatTab agentId="agent-007" threadId={source === 'prop' ? 'resolved-thread' : undefined} onArtifactOpen={onArtifactOpen} />);
    const card = await screen.findByRole('button', { name: 'Open Report.docx v1' });
    fireEvent.click(card);
    expect(onArtifactOpen).toHaveBeenCalledTimes(1);
    expect(onArtifactOpen).toHaveBeenCalledWith({ artifactId: artifact.id, threadId: 'resolved-thread', opener: card });
    expect(useStore.getState().selectedArtifactId).toBe(artifact.id);
  });

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
