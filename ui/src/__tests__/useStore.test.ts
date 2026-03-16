import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';

beforeEach(() => {
  // Reset store between tests
  useStore.setState({
    agents: new Map(),
    connections: [],
    pools: [],
    chatHistory: [],
    connected: false,
    systemMode: 'active',
    tcN: 0,
    routingEntropy: 0,
    pendingSelfModBloom: null,
    pendingConsensusFlash: null,
    pendingRoutingPulse: null,
    pendingFeedbackPulse: null,
    selfModProgress: null,
    pendingRequests: 0,
  });
  // Clear localStorage
  localStorage.clear();
});

describe('useStore', () => {
  describe('addChatMessage', () => {
    it('adds a user message to chat history', () => {
      useStore.getState().addChatMessage('user', 'Hello');
      const history = useStore.getState().chatHistory;
      expect(history).toHaveLength(1);
      expect(history[0].role).toBe('user');
      expect(history[0].text).toBe('Hello');
    });

    it('adds a system message to chat history', () => {
      useStore.getState().addChatMessage('system', 'Welcome');
      const history = useStore.getState().chatHistory;
      expect(history).toHaveLength(1);
      expect(history[0].role).toBe('system');
    });

    it('limits history to 50 messages', () => {
      for (let i = 0; i < 60; i++) {
        useStore.getState().addChatMessage('user', `msg ${i}`);
      }
      expect(useStore.getState().chatHistory.length).toBeLessThanOrEqual(50);
    });

    it('persists to localStorage', () => {
      useStore.getState().addChatMessage('user', 'stored');
      const stored = localStorage.getItem('hxi_chat_history');
      expect(stored).toBeTruthy();
      const parsed = JSON.parse(stored!);
      expect(parsed).toHaveLength(1);
      expect(parsed[0].text).toBe('stored');
    });

    it('attaches selfModProposal when provided', () => {
      useStore.getState().addChatMessage('system', 'gap', {
        selfModProposal: {
          intent_name: 'test',
          intent_description: 'test desc',
          parameters: {},
          original_message: 'test',
          status: 'proposed',
        },
      });
      const msg = useStore.getState().chatHistory[0];
      expect(msg.selfModProposal).toBeDefined();
      expect(msg.selfModProposal!.intent_name).toBe('test');
    });
  });

  describe('handleEvent', () => {
    it('handles agent_state for new agent', () => {
      useStore.getState().handleEvent({
        type: 'agent_state',
        data: {
          agent_id: 'test-1',
          pool: 'test_pool',
          state: 'active',
          confidence: 0.8,
          trust: 0.5,
        },
        timestamp: Date.now() / 1000,
      });
      const agents = useStore.getState().agents;
      expect(agents.has('test-1')).toBe(true);
      expect(agents.get('test-1')!.confidence).toBe(0.8);
    });

    it('handles agent_state update for existing agent', () => {
      // Add agent first
      useStore.getState().handleEvent({
        type: 'agent_state',
        data: {
          agent_id: 'test-1',
          pool: 'test_pool',
          state: 'active',
          confidence: 0.8,
          trust: 0.5,
        },
        timestamp: Date.now() / 1000,
      });
      // Update it
      useStore.getState().handleEvent({
        type: 'agent_state',
        data: {
          agent_id: 'test-1',
          pool: 'test_pool',
          state: 'active',
          confidence: 0.95,
          trust: 0.7,
        },
        timestamp: Date.now() / 1000,
      });
      const agent = useStore.getState().agents.get('test-1');
      expect(agent!.confidence).toBe(0.95);
      expect(agent!.trust).toBe(0.7);
    });

    it('handles self_mod_success event', () => {
      useStore.getState().handleEvent({
        type: 'self_mod_success',
        data: {
          agent_type: 'test_agent',
          message: 'TestAgent deployed!',
        },
        timestamp: Date.now() / 1000,
      });
      expect(useStore.getState().pendingSelfModBloom).toBe('test_agent');
      expect(useStore.getState().chatHistory).toHaveLength(1);
      expect(useStore.getState().selfModProgress).toBeNull();
    });

    it('handles self_mod_progress event', () => {
      useStore.getState().handleEvent({
        type: 'self_mod_progress',
        data: {
          step: 'designing',
          current: 1,
          total: 5,
          step_label: 'Designing agent code...',
        },
        timestamp: Date.now() / 1000,
      });
      const progress = useStore.getState().selfModProgress;
      expect(progress).toBeDefined();
      expect(progress!.step).toBe('designing');
      expect(progress!.current).toBe(1);
    });

    it('clears selfModProgress on self_mod_failure', () => {
      // Set progress first
      useStore.setState({ selfModProgress: { step: 'testing', current: 3, total: 5, label: 'test' } });
      useStore.getState().handleEvent({
        type: 'self_mod_failure',
        data: { message: 'failed' },
        timestamp: Date.now() / 1000,
      });
      expect(useStore.getState().selfModProgress).toBeNull();
    });

    it('clears chat on fresh_boot state_snapshot', () => {
      useStore.getState().addChatMessage('user', 'old message');
      expect(useStore.getState().chatHistory).toHaveLength(1);

      useStore.getState().handleEvent({
        type: 'state_snapshot',
        data: {
          agents: [],
          connections: [],
          pools: [],
          system_mode: 'active',
          tc_n: 0,
          routing_entropy: 0,
          fresh_boot: true,
        },
        timestamp: Date.now() / 1000,
      });
      expect(useStore.getState().chatHistory).toHaveLength(0);
    });
  });

  describe('connection state', () => {
    it('setConnected updates state', () => {
      useStore.getState().setConnected(true);
      expect(useStore.getState().connected).toBe(true);
    });
  });

  describe('processing state', () => {
    it('incPendingRequests increments', () => {
      useStore.getState().incPendingRequests();
      expect(useStore.getState().pendingRequests).toBe(1);
    });

    it('decPendingRequests decrements', () => {
      useStore.getState().incPendingRequests();
      useStore.getState().decPendingRequests();
      expect(useStore.getState().pendingRequests).toBe(0);
    });

    it('decPendingRequests floors at 0', () => {
      useStore.getState().decPendingRequests();
      expect(useStore.getState().pendingRequests).toBe(0);
    });
  });
});
