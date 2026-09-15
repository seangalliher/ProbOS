import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useStore } from '../store/useStore';
import { AgentProfilePanel } from '../components/profile/AgentProfilePanel';

const scrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollIntoView');

vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(), getServerPiperVoices: vi.fn(async () => null),
  speakResponse: vi.fn(), stripMarkdownForSpeech: (text: string) => text,
  onSpeechEvent: vi.fn(() => () => {}),
}));
vi.mock('../audio/speechInput', () => ({ isSpeechRecognitionSupported: () => false, startListening: vi.fn() }));
vi.mock('../components/profile/CrewAvatarPopout', () => ({ CrewAvatarPopout: () => null }));
vi.mock('../components/profile/ProfileWorkTab', () => ({ ProfileWorkTab: () => null }));
vi.mock('../components/profile/ProfileInfoTab', () => ({ ProfileInfoTab: () => null }));
vi.mock('../components/profile/ProfileServiceTab', () => ({ ProfileServiceTab: () => null }));
vi.mock('../components/profile/ProfileHealthTab', () => ({ ProfileHealthTab: () => null }));
vi.mock('../components/profile/ProfileMemoryTab', () => ({ ProfileMemoryTab: () => null }));
vi.mock('../components/profile/SelfImageTab', () => ({ SelfImageTab: () => null }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (scrollIntoViewDescriptor) Object.defineProperty(Element.prototype, 'scrollIntoView', scrollIntoViewDescriptor);
  else Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});

beforeEach(() => {
  useStore.setState({
    activeProfileAgent: null,
    profilePanelPos: { x: 100, y: 100 },
    agentConversations: new Map(),
    pinnedAgent: null,
    agents: new Map(),
  });
});

describe('AgentProfilePanel store (AD-406)', () => {
  it('opens real transcript artifacts and clears presentation across tabs, threads and agents', async () => {
    localStorage.clear();
    vi.stubGlobal('innerWidth', 1440);
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(418);
    Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
    const artifact = {
      id: 'profile-doc', thread_id: 'profile-thread', name: 'Report.docx', version: 1,
      content_hash: 'hash', mime: 'application/octet-stream', size_bytes: 1,
      created_by: 'a1', created_at: 1, supersedes: null, _pinned_from_project: false,
    };
    const agent = {
      id: 'a1', agentType: 'scout', callsign: 'Wesley', displayName: 'Scout', pool: 'scout',
      state: 'active' as const, confidence: 0.8, trust: 0.7,
      tier: 'domain' as const, isCrew: true, position: [0, 0, 0] as [number, number, number],
    };
    const message = { id: 'profile-message', role: 'agent' as const,
      text: '[Artifact: Report.docx v1 - 0 lines, application/octet-stream]', timestamp: 1 };
    useStore.setState({
      agents: new Map([['a1', agent], ['a2', { ...agent, id: 'a2', callsign: 'Other' }]]),
      activeProfileAgent: 'a1', activeProfileThreadId: null, activeThreadId: null,
      threadIdByAgent: new Map([['a1', 'profile-thread'], ['a2', 'other-thread']]),
      chatThreads: new Map([['profile-thread', { id: 'profile-thread', title: 'Report', participants: ['a1'], created_at: 1, last_active_at: 1 }]]),
      threadMessages: new Map([['profile-thread', [message]]]),
      artifactsByThread: new Map(), selectedArtifactId: null, artifactDrawerCollapsed: true, voiceEnabled: false,
    });
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      const path = String(url);
      if (path.startsWith('/api/artifacts/thread/')) return new Response(JSON.stringify({ thread_id: 'profile-thread', artifacts: [artifact] }));
      if (path === '/api/config/avatars-enabled') return new Response(JSON.stringify({ enabled: false }));
      return new Response('{}', { status: 404 });
    }));
    const user = userEvent.setup();
    render(<AgentProfilePanel />);
    const card = await screen.findByRole('button', { name: 'Open Report.docx v1' });
    await waitFor(() => expect(card).toBeEnabled());
    const closeProfile = screen.getByRole('button', { name: 'Close profile' });
    expect(closeProfile.parentElement).toHaveStyle({ flexShrink: '0', flexWrap: 'wrap' });
    expect(closeProfile.parentElement?.parentElement).toHaveStyle({ flexWrap: 'wrap', minWidth: '0' });
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(card);
    expect(screen.getByRole('dialog', { name: 'Artifacts' })).toBeInTheDocument();
    expect(useStore.getState().activeThreadId).toBeNull();
    expect(screen.getByTestId('artifact-drawer')).toHaveAttribute('data-thread-id', 'profile-thread');
    expect(screen.getByTestId('artifact-viewer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Collapse artifacts' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(card).toHaveFocus();
    await user.click(card);
    await user.click(screen.getByRole('button', { name: /^Work$/ }));
    await user.click(screen.getByRole('button', { name: /^Chat$/ }));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open Report.docx v1' }));
    act(() => useStore.setState({ activeProfileAgent: 'a2', activeThreadId: 'other-thread' }));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    act(() => useStore.setState({ activeProfileAgent: 'a1', activeThreadId: 'profile-thread' }));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open Report.docx v1' }));
    act(() => useStore.setState({ activeProfileThreadId: 'other-thread', activeThreadId: 'other-thread' }));
    expect(screen.queryByRole('dialog', { name: 'Artifacts' })).not.toBeInTheDocument();
  });

  it('openAgentProfile sets activeProfileAgent and clears pinnedAgent', () => {
    const mockAgent = {
      id: 'a1', agentType: 'scout', callsign: 'Wesley', displayName: 'Scout', pool: 'scout',
      state: 'active' as const, confidence: 0.8, trust: 0.7,
      tier: 'domain' as const, isCrew: true, position: [0, 0, 0] as [number, number, number],
    };
    useStore.setState({ pinnedAgent: mockAgent });
    useStore.getState().openAgentProfile('a1');
    expect(useStore.getState().activeProfileAgent).toBe('a1');
    expect(useStore.getState().pinnedAgent).toBeNull();
  });

  it('closeAgentProfile clears activeProfileAgent and the group-thread override', () => {
    // The group/call surface is keyed by activeProfileThreadId (AD-954a), so
    // close must clear BOTH or an agent-created group chat stays open.
    useStore.setState({ activeProfileAgent: 'a1', activeProfileThreadId: 'g1' });
    useStore.getState().closeAgentProfile();
    expect(useStore.getState().activeProfileAgent).toBeNull();
    expect(useStore.getState().activeProfileThreadId).toBeNull();
  });

  it('minimizeAgentProfile clears the group-thread override too', () => {
    useStore.setState({ activeProfileAgent: 'a1', activeProfileThreadId: 'g1' });
    useStore.getState().minimizeAgentProfile();
    expect(useStore.getState().activeProfileAgent).toBeNull();
    expect(useStore.getState().activeProfileThreadId).toBeNull();
  });

  it('panel hidden when no agent selected', () => {
    expect(useStore.getState().activeProfileAgent).toBeNull();
  });

  it('addAgentMessage creates conversation', () => {
    useStore.getState().addAgentMessage('a1', 'user', 'Hello');
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv).toBeDefined();
    expect(conv!.messages).toHaveLength(1);
    expect(conv!.messages[0].role).toBe('user');
    expect(conv!.messages[0].text).toBe('Hello');
  });

  it('addAgentMessage appends to existing conversation', () => {
    useStore.getState().addAgentMessage('a1', 'user', 'Hello');
    useStore.getState().addAgentMessage('a1', 'agent', 'Hi there');
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv!.messages).toHaveLength(2);
    expect(conv!.messages[1].role).toBe('agent');
  });

  it('minimizeAgentProfile sets minimized and clears activeProfileAgent', () => {
    useStore.getState().addAgentMessage('a1', 'user', 'test');
    useStore.setState({ activeProfileAgent: 'a1' });
    useStore.getState().minimizeAgentProfile();
    expect(useStore.getState().activeProfileAgent).toBeNull();
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv!.minimized).toBe(true);
  });

  it('markAgentRead resets unread count and minimized', () => {
    // Set up a minimized conversation with unread
    const convs = new Map();
    convs.set('a1', {
      agentId: 'a1',
      messages: [],
      unreadCount: 3,
      minimized: true,
    });
    useStore.setState({ agentConversations: convs });
    useStore.getState().markAgentRead('a1');
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv!.unreadCount).toBe(0);
    expect(conv!.minimized).toBe(false);
  });

  it('setProfilePanelPos updates position', () => {
    useStore.getState().setProfilePanelPos({ x: 200, y: 300 });
    expect(useStore.getState().profilePanelPos).toEqual({ x: 200, y: 300 });
  });

  it('unread count increments for agent messages when profile not open', () => {
    // Profile NOT open for this agent
    useStore.setState({ activeProfileAgent: null });
    useStore.getState().addAgentMessage('a1', 'agent', 'update');
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv!.unreadCount).toBe(1);
  });

  it('unread count does not increment when profile is open for that agent', () => {
    useStore.setState({ activeProfileAgent: 'a1' });
    useStore.getState().addAgentMessage('a1', 'agent', 'update');
    const conv = useStore.getState().agentConversations.get('a1');
    expect(conv!.unreadCount).toBe(0);
  });
});
