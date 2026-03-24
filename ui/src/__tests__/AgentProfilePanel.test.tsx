import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';

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
  it('openAgentProfile sets activeProfileAgent and clears pinnedAgent', () => {
    const mockAgent = {
      id: 'a1', agentType: 'scout', callsign: 'Wesley', pool: 'scout',
      state: 'active' as const, confidence: 0.8, trust: 0.7,
      tier: 'domain' as const, position: [0, 0, 0] as [number, number, number],
    };
    useStore.setState({ pinnedAgent: mockAgent });
    useStore.getState().openAgentProfile('a1');
    expect(useStore.getState().activeProfileAgent).toBe('a1');
    expect(useStore.getState().pinnedAgent).toBeNull();
  });

  it('closeAgentProfile clears activeProfileAgent', () => {
    useStore.setState({ activeProfileAgent: 'a1' });
    useStore.getState().closeAgentProfile();
    expect(useStore.getState().activeProfileAgent).toBeNull();
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
