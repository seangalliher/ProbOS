/* Zustand reactive state store — single source of truth for HXI (AD-255) */

import { create } from 'zustand';
import { soundEngine } from '../audio/soundEngine';
import type {
  Agent, Connection, PoolInfo, SystemMode, DagNode, ChatMessage, SelfModProposal,
  StateSnapshot, TrustUpdateEvent, HebbianUpdateEvent,
  ConsensusEvent, SystemModeEvent, AgentStateEvent, WSEvent,
} from './types';

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

function computeLayout(agents: Map<string, Agent>): Map<string, Agent> {
  // Collect all agents by tier
  const heartbeat: string[] = [];
  const core: string[] = [];
  const utility: string[] = [];
  const domain: string[] = [];

  agents.forEach((a, id) => {
    if (a.pool === 'system') heartbeat.push(id);
    else if (a.tier === 'core') core.push(id);
    else if (a.tier === 'utility') utility.push(id);
    else domain.push(id);
  });

  // Sort by pool for cluster adjacency on the sphere
  const byPool = (a: string, b: string) => {
    const poolA = agents.get(a)?.pool || '';
    const poolB = agents.get(b)?.pool || '';
    return poolA.localeCompare(poolB);
  };
  core.sort(byPool);
  utility.sort(byPool);
  domain.sort(byPool);

  const updated = new Map(agents);

  // Heartbeat at center — tight cluster
  heartbeat.forEach((id, i) => {
    const agent = updated.get(id);
    if (!agent) return;
    const offset = (i - (heartbeat.length - 1) / 2) * 0.25;
    updated.set(id, { ...agent, position: [offset * 0.5, 0, offset * 0.3] });
  });

  // Fibonacci sphere distribution for even spacing
  function fibonacciSphere(ids: string[], radius: number) {
    const n = ids.length;
    if (n === 0) return;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    ids.forEach((id, i) => {
      const agent = updated.get(id);
      if (!agent) return;

      const y = 1 - (i / (n - 1 || 1)) * 2; // y from 1 to -1
      const radiusAtY = Math.sqrt(1 - y * y);
      const theta = goldenAngle * i;

      const x = Math.cos(theta) * radiusAtY * radius;
      const z = Math.sin(theta) * radiusAtY * radius;
      const yPos = y * radius * 0.6; // compress Y so it's not too tall

      updated.set(id, { ...agent, position: [x, yPos, z] });
    });
  }

  // Place tiers on concentric spheres
  fibonacciSphere(core, 3.5);     // inner sphere
  fibonacciSphere(utility, 5.5);  // middle sphere
  fibonacciSphere(domain, 7.5);   // outer sphere

  return updated;
}

export interface HXIState {
  // Data
  agents: Map<string, Agent>;
  connections: Connection[];
  pools: PoolInfo[];
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
        set({
          agents: computeLayout(agentMap),
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
          return { agents: computeLayout(agents) };
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

export { POOL_HUES };
