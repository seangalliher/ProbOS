import { describe, it, expect, beforeEach } from 'vitest';
import { useStore, computeLayout } from '../store/useStore';
import type { Agent } from '../store/types';

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
    groupCenters: new Map(),
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

  describe('computeLayout clustering (AD-294)', () => {
    function makeAgent(id: string, pool: string, tier: Agent['tier'] = 'domain'): Agent {
      return {
        id, agentType: pool, pool, state: 'active',
        confidence: 0.8, trust: 0.5, tier, position: [0, 0, 0],
      };
    }

    function dist(a: [number, number, number], b: [number, number, number]): number {
      return Math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2);
    }

    it('clusters agents by group', () => {
      const agents = new Map<string, Agent>();
      agents.set('med-0', makeAgent('med-0', 'medical_vitals'));
      agents.set('med-1', makeAgent('med-1', 'medical_diagnostician'));
      agents.set('core-0', makeAgent('core-0', 'filesystem'));
      agents.set('core-1', makeAgent('core-1', 'shell'));

      const poolToGroup: Record<string, string> = {
        medical_vitals: 'medical',
        medical_diagnostician: 'medical',
        filesystem: 'core',
        shell: 'core',
      };

      const { agents: laid } = computeLayout(agents, poolToGroup);
      const m0 = laid.get('med-0')!.position;
      const m1 = laid.get('med-1')!.position;
      const c0 = laid.get('core-0')!.position;
      const c1 = laid.get('core-1')!.position;

      // Same-group agents should be close together
      const medDist = dist(m0, m1);
      // Different-group agents should be far apart
      const crossDist = dist(m0, c0);

      expect(medDist).toBeLessThan(crossDist);
      expect(crossDist).toBeGreaterThan(3.0);
    });

    it('returns groupCenters with metadata', () => {
      const agents = new Map<string, Agent>();
      agents.set('med-0', makeAgent('med-0', 'medical_vitals'));
      agents.set('core-0', makeAgent('core-0', 'filesystem'));

      const poolToGroup: Record<string, string> = {
        medical_vitals: 'medical',
        filesystem: 'core',
      };
      const poolGroups = {
        medical: { name: 'medical', display_name: 'Medical', total_agents: 1, healthy_agents: 1, health_ratio: 1, pools: {} },
        core: { name: 'core', display_name: 'Core Systems', total_agents: 1, healthy_agents: 1, health_ratio: 1, pools: {} },
      };

      const { groupCenters } = computeLayout(agents, poolToGroup, poolGroups);

      expect(groupCenters.size).toBe(2);
      expect(groupCenters.has('medical')).toBe(true);
      expect(groupCenters.has('core')).toBe(true);

      const med = groupCenters.get('medical')!;
      expect(med.center).toHaveLength(3);
      expect(med.radius).toBeGreaterThan(0);
      expect(med.displayName).toBe('Medical');
      expect(med.tintHex).toBe('#c06060');

      const core = groupCenters.get('core')!;
      expect(core.displayName).toBe('Core Systems');
      expect(core.tintHex).toBe('#7090c0');
    });

    it('handles ungrouped agents', () => {
      const agents = new Map<string, Agent>();
      agents.set('med-0', makeAgent('med-0', 'medical_vitals'));
      agents.set('rogue-0', makeAgent('rogue-0', 'unknown_pool'));

      const poolToGroup: Record<string, string> = {
        medical_vitals: 'medical',
      };

      const { agents: laid, groupCenters } = computeLayout(agents, poolToGroup);
      const rogue = laid.get('rogue-0')!;

      // Ungrouped agent should not be at origin
      expect(dist(rogue.position, [0, 0, 0])).toBeGreaterThan(1.0);
      // Should have an _ungrouped group center
      expect(groupCenters.has('_ungrouped')).toBe(true);
    });

    it('keeps heartbeat agents at center', () => {
      const agents = new Map<string, Agent>();
      agents.set('hb-0', makeAgent('hb-0', 'system', 'core'));
      agents.set('med-0', makeAgent('med-0', 'medical_vitals'));

      const poolToGroup: Record<string, string> = {
        medical_vitals: 'medical',
      };

      const { agents: laid } = computeLayout(agents, poolToGroup);
      const hb = laid.get('hb-0')!;

      // Heartbeat should be very near origin
      expect(dist(hb.position, [0, 0, 0])).toBeLessThan(0.5);
    });

    it('state_snapshot populates groupCenters', () => {
      useStore.getState().handleEvent({
        type: 'state_snapshot',
        data: {
          agents: [
            { id: 'med-0', agent_type: 'vitals', pool: 'medical_vitals', state: 'active', confidence: 0.8, trust: 0.5, tier: 'domain' },
            { id: 'core-0', agent_type: 'shell', pool: 'shell', state: 'active', confidence: 0.8, trust: 0.5, tier: 'core' },
          ],
          connections: [],
          pools: [],
          system_mode: 'active',
          tc_n: 1,
          routing_entropy: 0.5,
          pool_groups: {
            medical: {
              name: 'medical', display_name: 'Medical',
              total_agents: 1, healthy_agents: 1, health_ratio: 1,
              pools: { medical_vitals: { current_size: 1, target_size: 1, agent_type: 'vitals' } },
            },
            core: {
              name: 'core', display_name: 'Core Systems',
              total_agents: 1, healthy_agents: 1, health_ratio: 1,
              pools: { shell: { current_size: 1, target_size: 1, agent_type: 'shell' } },
            },
          },
        },
        timestamp: Date.now() / 1000,
      });

      const gc = useStore.getState().groupCenters;
      expect(gc.size).toBe(2);
      expect(gc.has('medical')).toBe(true);
      expect(gc.has('core')).toBe(true);
    });
  });
});
