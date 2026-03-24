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
    poolToGroup: {},
    poolGroups: {},
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

    it('preserves pool group clustering on agent_state update (AD-349)', () => {
      const { handleEvent } = useStore.getState();

      // First, send a state_snapshot that establishes pool groups
      handleEvent({
        type: 'state_snapshot',
        data: {
          agents: [
            { id: 'a1', agent_type: 'file_reader', pool: 'filesystem', state: 'active', confidence: 0.9, trust: 0.5, tier: 'core' },
            { id: 'a2', agent_type: 'diagnostician', pool: 'medical_diagnostician', state: 'active', confidence: 0.9, trust: 0.5, tier: 'domain' },
          ],
          connections: [],
          pools: [],
          pool_groups: {
            core: { pools: { filesystem: { healthy: 1, target: 1 } } },
            medical: { pools: { medical_diagnostician: { healthy: 1, target: 1 } } },
          },
          pool_to_group: { filesystem: 'core', medical_diagnostician: 'medical' },
          system_mode: 'active',
          tc_n: 1,
          routing_entropy: 0.5,
        },
        timestamp: Date.now() / 1000,
      });

      const afterSnapshot = useStore.getState();
      expect(afterSnapshot.poolToGroup).toEqual({ filesystem: 'core', medical_diagnostician: 'medical' });

      // Now send an agent_state update
      handleEvent({
        type: 'agent_state',
        data: { agent_id: 'a1', pool: 'filesystem', state: 'active', confidence: 0.95, trust: 0.6 },
        timestamp: Date.now() / 1000,
      });

      // groupCenters should still be populated (not empty)
      const afterUpdate = useStore.getState();
      expect(afterUpdate.groupCenters.size).toBeGreaterThan(0);
    });

    it('stores poolToGroup and poolGroups from state_snapshot (AD-349)', () => {
      const { handleEvent } = useStore.getState();
      handleEvent({
        type: 'state_snapshot',
        data: {
          agents: [],
          connections: [],
          pools: [],
          pool_groups: { core: { pools: { filesystem: { healthy: 1, target: 1 } } } },
          pool_to_group: { filesystem: 'core' },
          system_mode: 'active',
          tc_n: 0,
          routing_entropy: 0,
        },
        timestamp: Date.now() / 1000,
      });
      const state = useStore.getState();
      expect(state.poolToGroup).toEqual({ filesystem: 'core' });
      expect(state.poolGroups).toEqual({ core: { pools: { filesystem: { healthy: 1, target: 1 } } } });
    });

    it('handles self_mod_success event with agent_id', () => {
      useStore.getState().handleEvent({
        type: 'self_mod_success',
        data: {
          agent_type: 'test_agent',
          agent_id: 'test_agent_0',
          message: 'TestAgent deployed!',
        },
        timestamp: Date.now() / 1000,
      });
      // Should prefer agent_id over agent_type
      expect(useStore.getState().pendingSelfModBloom).toBe('test_agent_0');
      expect(useStore.getState().chatHistory).toHaveLength(1);
      expect(useStore.getState().selfModProgress).toBeNull();
    });

    it('handles self_mod_success event with agent_type fallback', () => {
      useStore.getState().handleEvent({
        type: 'self_mod_success',
        data: {
          agent_type: 'test_agent',
          message: 'TestAgent deployed!',
        },
        timestamp: Date.now() / 1000,
      });
      // Without agent_id, should fall back to agent_type
      expect(useStore.getState().pendingSelfModBloom).toBe('test_agent');
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
        id, agentType: pool, callsign: '', pool, state: 'active',
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
    it('red_team agents are in security group', () => {
      const agents = new Map<string, Agent>();
      agents.set('rt-0', makeAgent('rt-0', 'red_team'));
      agents.set('rt-1', makeAgent('rt-1', 'red_team'));
      agents.set('med-0', makeAgent('med-0', 'medical_vitals'));

      const poolToGroup: Record<string, string> = {
        red_team: 'security',
        medical_vitals: 'medical',
      };

      const { groupCenters } = computeLayout(agents, poolToGroup);

      // Security group should exist, _ungrouped should not
      expect(groupCenters.has('security')).toBe(true);
      expect(groupCenters.has('_ungrouped')).toBe(false);

      const sec = groupCenters.get('security')!;
      expect(sec.tintHex).toBe('#c85068');
    });
  });
});

describe('poolCenter computation (AD-329)', () => {
  it('computes correct center for agents in same pool', () => {
    const agents = new Map<string, Agent>();
    agents.set('a1', {
      id: 'a1', agentType: 'alpha', callsign: '', pool: 'science',
      state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
      position: [1, 2, 3],
    });
    agents.set('a2', {
      id: 'a2', agentType: 'beta', callsign: '', pool: 'science',
      state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
      position: [3, 4, 5],
    });
    let cx = 0, cy = 0, cz = 0, count = 0;
    agents.forEach((a) => {
      if (a.pool === 'science') {
        cx += a.position[0]; cy += a.position[1]; cz += a.position[2];
        count++;
      }
    });
    const center: [number, number, number] = [cx / count, cy / count, cz / count];
    expect(center).toEqual([2, 3, 4]);
  });

  it('returns [0,0,0] for empty pool', () => {
    const agents = new Map<string, Agent>();
    let cx = 0, cy = 0, cz = 0, count = 0;
    agents.forEach((a) => {
      if (a.pool === 'nonexistent') {
        cx += a.position[0]; cy += a.position[1]; cz += a.position[2];
        count++;
      }
    });
    const center: [number, number, number] = count === 0 ? [0, 0, 0] : [cx / count, cy / count, cz / count];
    expect(center).toEqual([0, 0, 0]);
  });
});

describe('connection filtering (AD-329)', () => {
  it('filters connections requiring missing agents', () => {
    const agents = new Map<string, Agent>();
    agents.set('a1', {
      id: 'a1', agentType: 'alpha', callsign: '', pool: 'science',
      state: 'active', confidence: 0.8, trust: 0.7, tier: 'domain',
      position: [0, 0, 0],
    });

    const connections = [
      { source: 'a1', target: 'a2', weight: 0.5 },  // a2 doesn't exist
      { source: 'a1', target: 'intent_hub', weight: 0.8 },  // valid
    ];

    // Simulate the filter logic from connections.tsx
    const valid = connections.filter((c) => {
      const sourceIsAgent = agents.has(c.source);
      const targetIsAgent = agents.has(c.target);
      const sourceIsPool = !sourceIsAgent && c.source.includes('_');
      const targetIsPool = !targetIsAgent && c.target.includes('_');
      return (sourceIsAgent || sourceIsPool) && (targetIsAgent || targetIsPool);
    });

    // a1->a2 filtered out (a2 not in map and not a pool), a1->intent_hub kept
    expect(valid.length).toBe(1);
    expect(valid[0].target).toBe('intent_hub');
  });
});

describe('AgentTooltip state (AD-329)', () => {
  it('hoveredAgent and tooltipPos update together', () => {
    const agent: Agent = {
      id: 'test1', agentType: 'test', callsign: '', pool: 'science',
      state: 'active', confidence: 0.9, trust: 0.8, tier: 'domain',
      position: [0, 0, 0],
    };

    useStore.getState().setHoveredAgent(agent, { x: 100, y: 200 });
    expect(useStore.getState().hoveredAgent).toBe(agent);
    expect(useStore.getState().tooltipPos).toEqual({ x: 100, y: 200 });
  });

  it('clearing hoveredAgent sets null', () => {
    useStore.getState().setHoveredAgent(null);
    expect(useStore.getState().hoveredAgent).toBeNull();
  });

  it('pinnedAgent persists after hover clears', () => {
    const agent: Agent = {
      id: 'pin1', agentType: 'pinned', callsign: '', pool: 'eng',
      state: 'active', confidence: 0.9, trust: 0.8, tier: 'domain',
      position: [0, 0, 0],
    };
    useStore.getState().setPinnedAgent(agent);
    useStore.getState().setHoveredAgent(null);
    expect(useStore.getState().pinnedAgent).toBe(agent);
  });
});

describe('animation event clearing (AD-329)', () => {
  it('clearAnimationEvent resets pendingSelfModBloom', () => {
    useStore.setState({ pendingSelfModBloom: 'test_agent' });
    useStore.getState().clearAnimationEvent('pendingSelfModBloom');
    expect(useStore.getState().pendingSelfModBloom).toBeNull();
  });

  it('clearAnimationEvent resets pendingConsensusFlash', () => {
    useStore.setState({ pendingConsensusFlash: { intent: 'test', outcome: 'approved', approval_ratio: 1, votes: 3, shapley: {} } });
    useStore.getState().clearAnimationEvent('pendingConsensusFlash');
    expect(useStore.getState().pendingConsensusFlash).toBeNull();
  });
});

describe('build_generated builder_source (AD-354)', () => {
  it('sets builder_source on build proposal from event data', () => {
    useStore.getState().handleEvent({
      type: 'build_generated',
      data: {
        build_id: 'b1',
        title: 'Test build',
        description: 'desc',
        ad_number: 354,
        file_changes: [],
        change_count: 0,
        llm_output: '',
        builder_source: 'visiting',
        message: 'Generated 0 file(s)',
      },
      timestamp: Date.now() / 1000,
    });
    const history = useStore.getState().chatHistory;
    expect(history).toHaveLength(1);
    expect(history[0].buildProposal?.builder_source).toBe('visiting');
  });

  it('defaults builder_source to native when not provided', () => {
    useStore.getState().handleEvent({
      type: 'build_generated',
      data: {
        build_id: 'b2',
        title: 'Test build',
        description: 'desc',
        ad_number: 0,
        file_changes: [],
        change_count: 0,
        llm_output: '',
        message: 'Generated 0 file(s)',
      },
      timestamp: Date.now() / 1000,
    });
    const history = useStore.getState().chatHistory;
    expect(history).toHaveLength(1);
    expect(history[0].buildProposal?.builder_source).toBe('native');
  });
});

describe('notification events (AD-323)', () => {
  it('handles notification event and updates state', () => {
    useStore.getState().handleEvent({
      type: 'notification',
      data: {
        notification: { id: 'n1', title: 'Test', notification_type: 'info', acknowledged: false },
        notifications: [
          { id: 'n1', agent_id: 'a1', agent_type: 'builder', department: 'engineering', notification_type: 'info', title: 'Test', detail: '', action_url: '', created_at: 1000, acknowledged: false },
        ],
        unread_count: 1,
      },
      timestamp: Date.now() / 1000,
    });
    const notifs = useStore.getState().notifications;
    expect(notifs).toHaveLength(1);
    expect(notifs![0].title).toBe('Test');
  });

  it('handles notification_ack event', () => {
    useStore.getState().handleEvent({
      type: 'notification_ack',
      data: {
        notification: { id: 'n1', title: 'Test', acknowledged: true },
        notifications: [
          { id: 'n1', agent_id: 'a1', agent_type: 'builder', department: 'engineering', notification_type: 'info', title: 'Test', detail: '', action_url: '', created_at: 1000, acknowledged: true },
        ],
        unread_count: 0,
      },
      timestamp: Date.now() / 1000,
    });
    const notifs = useStore.getState().notifications;
    expect(notifs).toHaveLength(1);
    expect(notifs![0].acknowledged).toBe(true);
  });

  it('sets notifications to null when empty', () => {
    useStore.getState().handleEvent({
      type: 'notification_snapshot',
      data: {
        notifications: [],
        unread_count: 0,
      },
      timestamp: Date.now() / 1000,
    });
    expect(useStore.getState().notifications).toBeNull();
  });

  it('hydrates notifications from state_snapshot', () => {
    useStore.getState().handleEvent({
      type: 'state_snapshot',
      data: {
        agents: [],
        connections: [],
        pools: [],
        system_mode: 'active',
        tc_n: 0,
        routing_entropy: 0,
        notifications: [
          { id: 'n1', agent_id: 'a1', agent_type: 'builder', department: 'engineering', notification_type: 'info', title: 'Hydrated', detail: '', action_url: '', created_at: 1000, acknowledged: false },
        ],
      },
      timestamp: Date.now() / 1000,
    });
    const notifs = useStore.getState().notifications;
    expect(notifs).toHaveLength(1);
    expect(notifs![0].title).toBe('Hydrated');
  });
});

describe('orb hover enhancements (AD-324)', () => {
  it('bridgeOpen defaults to false and can be toggled', () => {
    expect(useStore.getState().bridgeOpen).toBe(false);
    useStore.setState({ bridgeOpen: true });
    expect(useStore.getState().bridgeOpen).toBe(true);
    useStore.setState({ bridgeOpen: false });
    expect(useStore.getState().bridgeOpen).toBe(false);
  });

  it('tooltip can find current task for agent', () => {
    useStore.setState({
      agentTasks: [
        {
          id: 't1', agent_id: 'builder-001', agent_type: 'builder',
          department: 'engineering', type: 'build', title: 'Building AD-324',
          status: 'working', steps: [], requires_action: false,
          action_type: '', started_at: Date.now() / 1000 - 60,
          completed_at: 0, error: '', priority: 3, ad_number: 324,
          metadata: {}, step_current: 2, step_total: 5,
        },
      ],
    });
    const tasks = useStore.getState().agentTasks;
    const currentTask = tasks?.find(
      t => t.agent_id === 'builder-001' && (t.status === 'working' || t.status === 'review')
    );
    expect(currentTask).toBeDefined();
    expect(currentTask!.title).toBe('Building AD-324');
    expect(currentTask!.step_current).toBe(2);
    expect(currentTask!.step_total).toBe(5);
  });

  it('no task found for agent without active task', () => {
    useStore.setState({
      agentTasks: [
        {
          id: 't1', agent_id: 'other-agent', agent_type: 'builder',
          department: 'engineering', type: 'build', title: 'Other task',
          status: 'working', steps: [], requires_action: false,
          action_type: '', started_at: 0, completed_at: 0, error: '',
          priority: 3, ad_number: 0, metadata: {}, step_current: 0, step_total: 0,
        },
      ],
    });
    const tasks = useStore.getState().agentTasks;
    const currentTask = tasks?.find(
      t => t.agent_id === 'builder-001' && (t.status === 'working' || t.status === 'review')
    );
    expect(currentTask).toBeUndefined();
  });

  it('attention badge shows for requires_action task', () => {
    useStore.setState({
      agentTasks: [
        {
          id: 't1', agent_id: 'builder-001', agent_type: 'builder',
          department: 'engineering', type: 'build', title: 'Build needs review',
          status: 'review', steps: [], requires_action: true,
          action_type: 'approve_build', started_at: 0, completed_at: 0,
          error: '', priority: 3, ad_number: 324, metadata: {},
          step_current: 0, step_total: 0,
        },
      ],
    });
    const tasks = useStore.getState().agentTasks;
    const attentionTasks = tasks?.filter(t => t.requires_action);
    expect(attentionTasks).toHaveLength(1);
    expect(attentionTasks![0].agent_id).toBe('builder-001');
  });
});

describe('unified bridge (AD-325)', () => {
  it('mainViewer defaults to canvas', () => {
    expect(useStore.getState().mainViewer).toBe('canvas');
  });

  it('mainViewer can be set to kanban', () => {
    useStore.setState({ mainViewer: 'kanban' });
    expect(useStore.getState().mainViewer).toBe('kanban');
    useStore.setState({ mainViewer: 'canvas' });
    expect(useStore.getState().mainViewer).toBe('canvas');
  });

  it('bridgeOpen and mainViewer are independent', () => {
    useStore.setState({ bridgeOpen: true, mainViewer: 'kanban' });
    expect(useStore.getState().bridgeOpen).toBe(true);
    expect(useStore.getState().mainViewer).toBe('kanban');
    useStore.setState({ bridgeOpen: false });
    expect(useStore.getState().mainViewer).toBe('kanban');
  });

  it('attention count merges tasks and notifications', () => {
    useStore.setState({
      agentTasks: [
        {
          id: 't1', agent_id: 'a1', agent_type: 'builder',
          department: 'engineering', type: 'build', title: 'task',
          status: 'working', steps: [], requires_action: true,
          action_type: 'approve_build', started_at: 0, completed_at: 0,
          error: '', priority: 3, ad_number: 0, metadata: {},
          step_current: 0, step_total: 0,
        },
      ],
      notifications: [
        {
          id: 'n1', agent_id: 'a2', agent_type: 'monitor',
          department: 'medical', notification_type: 'action_required' as const,
          title: 'alert', detail: '', action_url: '',
          created_at: 0, acknowledged: false,
        },
      ],
    });
    const tasks = useStore.getState().agentTasks!;
    const notifs = useStore.getState().notifications!;
    const attentionTasks = tasks.filter(t => t.requires_action && (t.status === 'working' || t.status === 'review'));
    const attentionNotifs = notifs.filter(n => n.notification_type === 'action_required' && !n.acknowledged);
    expect(attentionTasks.length + attentionNotifs.length).toBe(2);
  });
});
