/** AD-792 (Wave 195) vitest — CompactApp mounts ThreadSidebar
 * alongside the ProfileChatTab and propagates active-thread switches
 * through the store. Heavy ProfileChatTab + audio / VAD / WS
 * subsystems are mocked so this test focuses on the sidebar-host
 * contract. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useStore } from '../store/useStore';

const scrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');
const chatMode = vi.hoisted(() => ({ real: false }));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(), getServerPiperVoices: vi.fn(async () => null),
  speakResponse: vi.fn(), stripMarkdownForSpeech: (text: string) => text,
  onSpeechEvent: vi.fn(() => () => {}),
}));
vi.mock('../audio/speechInput', () => ({ isSpeechRecognitionSupported: () => false, startListening: vi.fn() }));

// Mock heavy subsystems CompactApp transitively imports.
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: () => {} }));
vi.mock('../hooks/useCameraStream', () => ({ stopCameraStream: vi.fn() }));
vi.mock('../audio/voiceActivity', () => ({
  startVoiceActivity: vi.fn(),
  stopVoiceActivity: vi.fn(),
  subscribePcm: vi.fn(() => () => {}),
}));
vi.mock('../store/useSettingsStore', () => ({
  useSettingsStore: Object.assign(
    (sel: any) => sel({ snapshot: null, loadSnapshot: async () => {} }),
    { getState: () => ({ snapshot: null, loadSnapshot: async () => {} }) },
  ),
}));
// Stub ProfileChatTab + chips so we can assert on the agentId prop without
// dragging in TTS / VAD / attachments.
vi.mock('../components/profile/ProfileChatTab', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../components/profile/ProfileChatTab')>();
  return {
    ProfileChatTab: (props: React.ComponentProps<typeof actual.ProfileChatTab>) => chatMode.real
      ? <actual.ProfileChatTab {...props} />
      : <div data-testid="profile-chat-stub" data-agent-id={props.agentId} data-thread-id={props.threadId ?? ''} />,
  };
});
vi.mock('../components/YeoStarterChips', () => ({ YeoStarterChips: () => null }));
vi.mock('../components/YeoEmptyGreeting', () => ({ YeoEmptyGreeting: () => null }));

import CompactApp from '../CompactApp';

beforeEach(() => {
  chatMode.real = false;
  localStorage.clear();
  useStore.setState({
    agents: new Map([
      ['yeo-id', { id: 'yeo-id', callsign: 'Yeo', displayName: 'Yeo' } as any],
      ['agent-2', { id: 'agent-2', callsign: 'Bones', displayName: 'Bones' } as any],
    ]),
    chatThreads: new Map([
      [
        't1',
        {
          id: 't1',
          title: 'Yeo thread',
          participants: ['yeo-id'],
          created_at: 1,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
        },
      ],
      [
        't2',
        {
          id: 't2',
          title: 'Bones thread',
          participants: ['agent-2'],
          created_at: 1,
          last_active_at: Date.now() / 1000,
          pinned: false,
          archived: false,
        },
      ],
    ]),
    activeThreadId: null,
    threadIdByAgent: new Map(),
    agentConversations: new Map(),
  });
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ threads: [] }) }) as any);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (scrollIntoViewDescriptor) Object.defineProperty(Element.prototype, 'scrollIntoView', scrollIntoViewDescriptor);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

describe('CompactApp sidebar integration', () => {
  it('opens through the real chat renderer and does not replay across thread changes or workspace suppression', async () => {
    chatMode.real = true;
    vi.stubGlobal('innerWidth', 1440);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(418);
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
    const artifact = {
      id: 'compact-doc', thread_id: 't1', name: 'Report.docx', version: 1,
      content_hash: 'hash', mime: 'application/octet-stream', size_bytes: 1,
      created_by: 'yeo-id', created_at: 1, supersedes: null, _pinned_from_project: false,
    };
    useStore.setState({
      activeThreadId: 't1', activeProfileThreadId: null,
      threadMessages: new Map([['t1', [{ id: 'compact-message', role: 'agent',
        text: '[Artifact: Report.docx v1 - 0 lines, application/octet-stream]', timestamp: 1 }]]]),
      artifactsByThread: new Map(), selectedArtifactId: null, artifactDrawerCollapsed: true, voiceEnabled: false,
    });
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      const path = String(url);
      if (path.startsWith('/api/artifacts/thread/')) return new Response(JSON.stringify({ thread_id: 't1', artifacts: [artifact] }));
      return new Response('{}', { status: 404 });
    }));
    const user = userEvent.setup();
    render(<CompactApp />);
    const card = await screen.findByRole('button', { name: 'Open Report.docx v1' });
    await waitFor(() => expect(card).toBeEnabled());
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(card);
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Collapse artifacts' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(card).toHaveFocus();
    await user.click(card);
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    await user.click(screen.getByTestId('thread-row-t2'));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    await user.click(screen.getByTestId('thread-row-t1'));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open Report.docx v1' }));
    act(() => {
      const threads = new Map(useStore.getState().chatThreads);
      threads.set('t1', { ...threads.get('t1')!, task_id: 'task-1' });
      useStore.setState({ chatThreads: threads });
    });
    expect(screen.queryByTestId('artifact-drawer')).not.toBeInTheDocument();
    act(() => {
      const threads = new Map(useStore.getState().chatThreads);
      threads.set('t1', { ...threads.get('t1')!, task_id: undefined });
      useStore.setState({ chatThreads: threads });
    });
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-collapsed', 'true');
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
  });

  it('mounts ThreadSidebar alongside ProfileChatTab on cold-start (Yeo)', async () => {
    render(<CompactApp />);
    await waitFor(() => {
      expect(screen.getByTestId('thread-sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('profile-chat-stub')).toBeInTheDocument();
    });
    const chat = screen.getByTestId('profile-chat-stub');
    const conversation = screen.getByTestId('compact-conversation');
    expect(conversation).toContainElement(chat);
    expect(conversation).toContainElement(screen.getByTestId('artifact-drawer'));
    expect(conversation).not.toContainElement(screen.getByTestId('thread-sidebar'));
    expect(chat.getAttribute('data-agent-id')).toBe('yeo-id');
  });

  it('selecting a different thread re-mounts the chat against participants[0]', async () => {
    render(<CompactApp />);
    await screen.findByTestId('thread-sidebar');
    // Switch active thread via the sidebar row.
    await act(async () => {
      fireEvent.click(screen.getByTestId('thread-row-t2'));
    });
    await waitFor(() => {
      const chat = screen.getByTestId('profile-chat-stub');
      expect(chat.getAttribute('data-agent-id')).toBe('agent-2');
      expect(chat.getAttribute('data-thread-id')).toBe('t2');
    });
  });
});
