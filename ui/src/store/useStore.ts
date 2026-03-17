/* Zustand reactive state store — single source of truth for HXI (AD-255) */

import { create } from 'zustand';
import { soundEngine } from '../audio/soundEngine';
import type {
  Agent, Connection, PoolInfo, PoolGroupInfo, SystemMode, DagNode, ChatMessage, SelfModProposal,
  StateSnapshot, TrustUpdateEvent, HebbianUpdateEvent,
  ConsensusEvent, SystemModeEvent, AgentStateEvent, WSEvent,
} from './types';

export interface GroupCenter {
  center: [number, number, number];
  radius: number;
  displayName: string;
  tintHex: string;
}

// Pool-based layout — Fibonacci sphere distribution
const POOL_HUES: Record<string, [number, number, number]> = {
  system: [0.15, 0.08, 0.04],
  filesystem: [0.04, 0.06, 0.15],
  filesystem_writers: [0.04, 0.12, 0.12],
  directory: [0.04, 0.12, 0.10],
  search: [0.04, 0.12, 0.14],
  shell: [0.15, 0.10, 0.04],
  http: [0.06, 0.04, 0.14],
  introspect: [0.08, 0.08, 0.12],
  red_team: [0.16, 0.04, 0.06],
  web_search: [0.04, 0.08, 0.14],
  page_reader: [0.06, 0.10, 0.12],
  weather: [0.06, 0.12, 0.14],
  news: [0.10, 0.08, 0.10],
  translator: [0.08, 0.06, 0.14],
  summarizer: [0.10, 0.06, 0.10],
  calculator: [0.12, 0.10, 0.06],
  todo_manager: [0.08, 0.10, 0.06],
  note_taker: [0.06, 0.10, 0.08],
  scheduler: [0.10, 0.08, 0.08],
  skills: [0.10, 0.06, 0.12],
};

const GROUP_TINT_HEXES: Record<string, string> = {
  core: '#7090c0',       // cool blue — infrastructure
  bundled: '#70a080',    // teal green — user-facing tools
  medical: '#c06060',    // warm red — sickbay
  self_mod: '#a078b0',   // purple — self-modification
  consensus: '#c85068',  // red — tactical
  security: '#c85068',   // red — tactical (matches red_team pool tint)
};

function computeLayout(
  agents: Map<string, Agent>,
  poolToGroup?: Record<string, string>,
  poolGroups?: Record<string, PoolGroupInfo>,
): { agents: Map<string, Agent>; groupCenters: Map<string, GroupCenter> } {
  const updated = new Map(agents);
  const groupCenters = new Map<string, GroupCenter>();

  // 1. Heartbeat agents at center
  const heartbeatIds: string[] = [];
  agents.forEach((a, id) => {
    if (a.pool === 'system') heartbeatIds.push(id);
  });
  heartbeatIds.forEach((id, i) => {
    const agent = updated.get(id);
    if (!agent) return;
    const offset = (i - (heartbeatIds.length - 1) / 2) * 0.25;
    updated.set(id, { ...agent, position: [offset * 0.5, 0, offset * 0.3] });
  });

  // If no pool group data, fall back to flat Fibonacci sphere layout
  if (!poolToGroup || Object.keys(poolToGroup).length === 0) {
    const core: string[] = [];
    const utility: string[] = [];
    const domain: string[] = [];

    agents.forEach((a, id) => {
      if (a.pool === 'system') return;
      if (a.tier === 'core') core.push(id);
      else if (a.tier === 'utility') utility.push(id);
      else domain.push(id);
    });

    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    function fibonacciSphere(ids: string[], radius: number) {
      const n = ids.length;
      if (n === 0) return;
      ids.forEach((id, i) => {
        const agent = updated.get(id);
        if (!agent) return;
        const y = 1 - (i / (n - 1 || 1)) * 2;
        const radiusAtY = Math.sqrt(1 - y * y);
        const theta = goldenAngle * i;
        const x = Math.cos(theta) * radiusAtY * radius;
        const z = Math.sin(theta) * radiusAtY * radius;
        const yPos = y * radius * 0.6;
        updated.set(id, { ...agent, position: [x, yPos, z] });
      });
    }
    fibonacciSphere(core, 3.5);
    fibonacciSphere(utility, 5.5);
    fibonacciSphere(domain, 7.5);

    return { agents: updated, groupCenters };
  }

  // 2. Bucket non-heartbeat agents by group
  const groups: Record<string, string[]> = {};
  const ungrouped: string[] = [];

  agents.forEach((a, id) => {
    if (a.pool === 'system') return;
    const groupName = poolToGroup[a.pool];
    if (groupName) {
      (groups[groupName] ??= []).push(id);
    } else {
      ungrouped.push(id);
    }
  });

  // 3. Compute group center positions on a spacing sphere
  const groupNames = Object.keys(groups).sort();
  if (ungrouped.length > 0) groupNames.push('_ungrouped');

  const groupCenterRadius = 6.0;
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  const totalGroups = groupNames.length;

  groupNames.forEach((gName, gi) => {
    const ids = gName === '_ungrouped' ? ungrouped : groups[gName];
    if (!ids || ids.length === 0) return;

    // Fibonacci point for this group's center
    const y = 1 - (gi / (totalGroups - 1 || 1)) * 2;
    const radiusAtY = Math.sqrt(1 - y * y);
    const theta = goldenAngle * gi;
    const cx = Math.cos(theta) * radiusAtY * groupCenterRadius;
    const cz = Math.sin(theta) * radiusAtY * groupCenterRadius;
    const cy = y * groupCenterRadius * 0.5;  // compress Y

    // Mini Fibonacci sphere for agents within this group
    const clusterRadius = 0.8 + Math.sqrt(ids.length) * 0.4;

    ids.forEach((id, ai) => {
      const agent = updated.get(id);
      if (!agent) return;
      const n = ids.length;
      const ay = 1 - (ai / (n - 1 || 1)) * 2;
      const ar = Math.sqrt(1 - ay * ay);
      const at = goldenAngle * ai;
      const ax = Math.cos(at) * ar * clusterRadius + cx;
      const az = Math.sin(at) * ar * clusterRadius + cz;
      const ayPos = ay * clusterRadius * 0.6 + cy;
      updated.set(id, { ...agent, position: [ax, ayPos, az] });
    });

    // Store group center for shell rendering
    const displayName = poolGroups?.[gName]?.display_name || gName;
    const tintHex = GROUP_TINT_HEXES[gName] || '#8888a0';
    groupCenters.set(gName, {
      center: [cx, cy, cz],
      radius: clusterRadius,
      displayName,
      tintHex,
    });
  });

  return { agents: updated, groupCenters };
}

export interface HXIState {
  // Data
  agents: Map<string, Agent>;
  connections: Connection[];
  pools: PoolInfo[];
  groupCenters: Map<string, GroupCenter>;
  systemMode: SystemMode;
  activeDag: DagNode[] | null;
  chatHistory: ChatMessage[];
  tcN: number;
  routingEntropy: number;

  // Animation events (consumed by canvas)
  pendingConsensusFlash: ConsensusEvent | null;
  pendingSelfModBloom: string | null;  // agent_id of newly spawned agent
  selfModProgress: { step: string; current: number; total: number; label: string } | null;
  pendingRoutingPulse: { source: string; target: string } | null;
  pendingFeedbackPulse: 'good' | 'bad' | null;

  // Connection status
  connected: boolean;

  // UI state (Fix 10, 11)
  hoveredAgent: Agent | null;
  tooltipPos: { x: number; y: number };
  pinnedAgent: Agent | null;
  showIntro: boolean;
  showLegend: boolean;

  // Conversation state
  showHistory: boolean;
  pinnedResponse: boolean;
  responseText: string;
  responseVisible: boolean;
  processing: boolean;
  pendingRequests: number;
  pendingChar: string;

  // Audio state
  soundEnabled: boolean;
  voiceEnabled: boolean;

  // Actions
  handleEvent: (event: WSEvent) => void;
  addChatMessage: (role: 'user' | 'system', text: string, meta?: { selfModProposal?: SelfModProposal }) => void;
  clearAnimationEvent: (key: 'pendingConsensusFlash' | 'pendingSelfModBloom' | 'pendingRoutingPulse' | 'pendingFeedbackPulse') => void;
  setConnected: (v: boolean) => void;
  setHoveredAgent: (agent: Agent | null, pos?: { x: number; y: number }) => void;
  setPinnedAgent: (agent: Agent | null) => void;
  setShowIntro: (v: boolean) => void;
  setShowLegend: (v: boolean) => void;
  setShowHistory: (v: boolean) => void;
  setPinnedResponse: (v: boolean) => void;
  setResponseText: (text: string) => void;
  setResponseVisible: (v: boolean) => void;
  setProcessing: (v: boolean) => void;
  incPendingRequests: () => void;
  decPendingRequests: () => void;
  triggerInput: (char: string) => void;
  consumePendingChar: () => string;
  setSoundEnabled: (v: boolean) => void;
  setVoiceEnabled: (v: boolean) => void;
}

export const useStore = create<HXIState>((set, get) => ({
  agents: new Map(),
  connections: [],
  pools: [],
  groupCenters: new Map(),
  systemMode: 'active',
  activeDag: null,
  chatHistory: (() => {
    try {
      const stored = localStorage.getItem('hxi_chat_history');
      if (stored) return JSON.parse(stored) as ChatMessage[];
    } catch {}
    return [];
  })(),
  tcN: 0,
  routingEntropy: 0,
  pendingConsensusFlash: null,
  pendingSelfModBloom: null,
  selfModProgress: null,
  pendingRoutingPulse: null,
  pendingFeedbackPulse: null,
  connected: false,
  hoveredAgent: null,
  tooltipPos: { x: 0, y: 0 },
  pinnedAgent: null,
  showIntro: typeof localStorage !== 'undefined' && !localStorage.getItem('hxi_seen_intro'),
  showLegend: false,
  showHistory: false,
  pinnedResponse: false,
  responseText: '',
  responseVisible: false,
  processing: false,
  pendingRequests: 0,
  pendingChar: '',
  soundEnabled: false,
  voiceEnabled: false,

  setConnected: (v) => { soundEngine.setConnected(v); set({ connected: v }); },
  setHoveredAgent: (agent, pos) => set(pos ? { hoveredAgent: agent, tooltipPos: pos } : { hoveredAgent: agent }),
  setPinnedAgent: (agent) => set({ pinnedAgent: agent }),
  setShowIntro: (v) => set({ showIntro: v }),
  setShowLegend: (v) => set({ showLegend: v }),
  setShowHistory: (v) => set({ showHistory: v }),
  setPinnedResponse: (v) => set({ pinnedResponse: v }),
  setResponseText: (text) => set({ responseText: text }),
  setResponseVisible: (v) => set({ responseVisible: v }),
  setProcessing: (v) => set({ processing: v }),
  incPendingRequests: () => set((s) => ({ pendingRequests: s.pendingRequests + 1 })),
  decPendingRequests: () => set((s) => ({ pendingRequests: Math.max(0, s.pendingRequests - 1) })),
  triggerInput: (char) => set({ pendingChar: char }),
  consumePendingChar: () => {
    const char = get().pendingChar;
    set({ pendingChar: '' });
    return char;
  },
  setSoundEnabled: (v) => {
    set({ soundEnabled: v });
    localStorage.setItem('hxi_sound_enabled', v ? '1' : '0');
    if (v && !soundEngine.initialized) soundEngine.init();
    soundEngine.setMuted(!v);
  },
  setVoiceEnabled: (v) => {
    set({ voiceEnabled: v });
    localStorage.setItem('hxi_voice_enabled', v ? '1' : '0');
  },

  addChatMessage: (role, text, meta) => {
    const msg: ChatMessage = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      text,
      timestamp: Date.now() / 1000,
      ...(meta?.selfModProposal ? { selfModProposal: meta.selfModProposal } : {}),
    };
    set((s) => {
      const updated = [...s.chatHistory.slice(-49), msg];
      try {
        const serializable = updated.map(m => ({
          id: m.id, role: m.role, text: m.text, timestamp: m.timestamp,
        }));
        localStorage.setItem('hxi_chat_history', JSON.stringify(serializable));
      } catch {}
      return { chatHistory: updated };
    });
  },

  clearAnimationEvent: (key) => set({ [key]: null }),

  handleEvent: (event: WSEvent) => {
    const { type, data } = event;

    switch (type) {
      case 'state_snapshot': {
        const snap = data as unknown as StateSnapshot;
        // Fresh boot: clear persisted chat history
        if (snap.fresh_boot) {
          localStorage.removeItem('hxi_chat_history');
        }
        const agentMap = new Map<string, Agent>();
        for (const a of snap.agents) {
          agentMap.set(a.id, {
            id: a.id,
            agentType: a.agent_type,
            pool: a.pool,
            state: a.state as Agent['state'],
            confidence: a.confidence,
            trust: a.trust,
            tier: a.tier as Agent['tier'],
            position: [0, 0, 0],
          });
        }
        const connections: Connection[] = snap.connections.map((c) => ({
          source: c.source,
          target: c.target,
          relType: c.rel_type,
          weight: c.weight,
        }));
        const pools: PoolInfo[] = snap.pools.map((p) => ({
          name: p.name,
          agentType: p.agent_type,
          size: p.size,
          targetSize: p.target_size,
        }));
        // Build pool→group reverse map for layout clustering (AD-291)
        const poolToGroup: Record<string, string> = {};
        if (snap.pool_groups) {
          for (const [groupName, groupInfo] of Object.entries(snap.pool_groups)) {
            for (const poolName of Object.keys(groupInfo.pools || {})) {
              poolToGroup[poolName] = groupName;
            }
          }
        }
        const layoutResult = computeLayout(agentMap, poolToGroup, snap.pool_groups);
        set({
          agents: layoutResult.agents,
          groupCenters: layoutResult.groupCenters,
          connections,
          pools,
          systemMode: snap.system_mode as SystemMode,
          tcN: snap.tc_n,
          routingEntropy: snap.routing_entropy,
          ...(snap.fresh_boot ? { chatHistory: [] } : {}),
        });
        break;
      }

      case 'agent_state': {
        const d = data as unknown as AgentStateEvent;
        set((s) => {
          const agents = new Map(s.agents);
          const existing = agents.get(d.agent_id);
          if (existing) {
            agents.set(d.agent_id, {
              ...existing,
              state: d.state as Agent['state'],
              confidence: d.confidence,
              trust: d.trust,
            });
          } else {
            // New agent — self-mod bloom!
            const agentType = d.pool.startsWith('designed_') ? d.pool.slice(9) : d.pool;
            const newAgent: Agent = {
              id: d.agent_id,
              agentType,
              pool: d.pool,
              state: d.state as Agent['state'],
              confidence: d.confidence,
              trust: d.trust,
              tier: 'domain',
              position: [0, 0, 0],
              createdAt: Date.now(),
            };
            agents.set(d.agent_id, newAgent);
          }
          return { agents: computeLayout(agents).agents };
        });
        break;
      }

      case 'trust_update': {
        const d = data as unknown as TrustUpdateEvent;
        soundEngine.playTrustPing(d.new_score > (d as any).old_score);
        set((s) => {
          const agents = new Map(s.agents);
          const agent = agents.get(d.agent_id);
          if (agent) {
            agents.set(d.agent_id, { ...agent, trust: d.new_score });
          }
          return { agents };
        });
        break;
      }

      case 'hebbian_update': {
        const d = data as unknown as HebbianUpdateEvent;
        set((s) => {
          const connections = [...s.connections];
          const idx = connections.findIndex(
            (c) => c.source === d.source && c.target === d.target
          );
          if (idx >= 0) {
            connections[idx] = { ...connections[idx], weight: d.weight };
          } else {
            connections.push({
              source: d.source,
              target: d.target,
              relType: d.rel_type,
              weight: d.weight,
            });
          }
          return { connections };
        });
        break;
      }

      case 'consensus': {
        const d = data as unknown as ConsensusEvent;
        soundEngine.playConsensus();
        set({ pendingConsensusFlash: d });
        break;
      }

      case 'system_mode': {
        const d = data as unknown as SystemModeEvent;
        const prev = get().systemMode;
        if (d.mode === 'dreaming' && prev !== 'dreaming') soundEngine.playDreamEnter();
        if (d.mode !== 'dreaming' && prev === 'dreaming') soundEngine.playDreamExit();
        set({ systemMode: d.mode });
        break;
      }

      case 'node_start': {
        soundEngine.playIntentRouting();
        set((s) => {
          const target = data.agent_id as string | undefined;
          const source = data.intent as string | undefined;
          const updates: Partial<typeof s> = {};

          if (target && source) {
            updates.pendingRoutingPulse = { source, target };

            // Flash the target agent
            const agents = new Map(s.agents);
            const agent = agents.get(target);
            if (agent) {
              agents.set(target, { ...agent, activatedAt: Date.now() });
              updates.agents = agents;
            }
          }
          return updates;
        });
        // Also update DAG node status
        set((s) => {
          if (!s.activeDag) return {};
          const nodeId = data.node_id as string;
          return {
            activeDag: s.activeDag.map((n) =>
              n.id === nodeId ? { ...n, status: 'running' as const } : n
            ),
          };
        });
        break;
      }

      case 'node_complete': {
        set((s) => {
          if (!s.activeDag) return {};
          const nodeId = data.node_id as string;
          return {
            activeDag: s.activeDag.map((n) =>
              n.id === nodeId ? { ...n, status: 'completed' as const } : n
            ),
          };
        });
        break;
      }

      case 'node_failed': {
        soundEngine.playError();
        set((s) => {
          if (!s.activeDag) return {};
          const nodeId = data.node_id as string;
          return {
            activeDag: s.activeDag.map((n) =>
              n.id === nodeId ? { ...n, status: 'failed' as const } : n
            ),
          };
        });
        break;
      }

      case 'decompose_complete': {
        const dag = data.dag as { nodes?: Array<{ id: string; intent: string; params?: Record<string, unknown>; depends_on?: string[] }> } | undefined;
        if (dag && dag.nodes) {
          set({
            activeDag: dag.nodes.map((n) => ({
              id: n.id,
              intent: n.intent,
              status: 'pending' as const,
              params: n.params || {},
              dependsOn: n.depends_on || [],
            })),
          });
        }
        break;
      }

      case 'self_mod_failure':
      case 'self_mod_retry_complete': {
        set({ selfModProgress: null });
        const msg = (data.message || data.response || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'self_mod_started':
      case 'self_mod_import_approved': {
        const msg = (data.message || data.response || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'self_mod_progress': {
        const step = data.step as string;
        const current = data.current as number;
        const total = data.total as number;
        const label = (data.step_label || data.message || '') as string;
        set({ selfModProgress: { step, current, total, label } });
        if (label) {
          get().addChatMessage('system', label);
        }
        break;
      }

      case 'self_mod_success': {
        soundEngine.playSelfModSpawn();
        set({ selfModProgress: null });
        const agentType = data.agent_type as string | undefined;
        if (agentType) {
          set({ pendingSelfModBloom: agentType });
        }
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      default:
        break;
    }
  },
}));

export { POOL_HUES, GROUP_TINT_HEXES, computeLayout };
