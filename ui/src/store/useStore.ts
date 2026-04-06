/* Zustand reactive state store — single source of truth for HXI (AD-255) */

import { create } from 'zustand';
import { soundEngine } from '../audio/soundEngine';
import type {
  Agent, Connection, PoolInfo, PoolGroupInfo, SystemMode, DagNode, ChatMessage, SelfModProposal,
  BuildProposal, BuildFailureReport, ArchitectProposalView, BuildQueueItem, MissionControlTask,
  AgentTaskView, NotificationView,
  AgentProfileMessage, AgentConversation,  // AD-406
  WardRoomChannel,  // AD-407
  WardRoomThread, WardRoomPost,  // AD-407c
  Assignment,  // AD-408
  ScheduledTaskView,  // Phase 25a
  WorkItemView, BookingView, BookableResourceView,  // AD-497
  WorkTypeDefinitionView, WorkItemTemplateView,  // AD-498
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
  utility: '#70a080',    // teal green — user-facing tools
  medical: '#c06060',    // warm red — sickbay
  self_mod: '#a078b0',   // purple — self-modification
  consensus: '#c85068',  // red — tactical
  security: '#c85068',   // red — tactical (matches red_team pool tint)
  engineering: '#b0a050', // amber — engineering/builder
  science: '#50a0b0',    // teal — science/architect
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
  poolToGroup: Record<string, string>;
  poolGroups: Record<string, PoolGroupInfo>;
  systemMode: SystemMode;
  activeDag: DagNode[] | null;
  chatHistory: ChatMessage[];
  tcN: number;
  routingEntropy: number;

  // Animation events (consumed by canvas)
  pendingConsensusFlash: ConsensusEvent | null;
  pendingSelfModBloom: string | null;  // agent_id (or agent_type fallback) of newly spawned agent
  selfModProgress: { step: string; current: number; total: number; label: string } | null;
  buildProgress: { step: string; current: number; total: number; label: string } | null;
  designProgress: { step: string; current: number; total: number; label: string } | null;
  transporterProgress: {
    phase: string;
    chunks: Array<{ chunk_id: string; description: string; target_file: string; status: string }>;
    waves_completed: number;
    total_chunks: number;
    successful: number;
    failed: number;
  } | null;
  buildQueue: BuildQueueItem[] | null;
  missionControlTasks: MissionControlTask[] | null;
  bridgeOpen: boolean;
  mainViewer: 'canvas' | 'kanban' | 'system' | 'work';
  agentTasks: AgentTaskView[] | null;
  workItems: WorkItemView[] | null;
  workBookings: BookingView[] | null;
  bookableResources: BookableResourceView[] | null;
  workTypeDefinitions: WorkTypeDefinitionView[] | null;
  workTemplates: WorkItemTemplateView[] | null;
  expandedGlassTask: string | null;
  notifications: NotificationView[] | null;
  pendingRoutingPulse: { source: string; target: string } | null;
  pendingFeedbackPulse: 'good' | 'bad' | null;

  // Connection status
  connected: boolean;

  // UI state (Fix 10, 11)
  hoveredAgent: Agent | null;
  tooltipPos: { x: number; y: number };
  pinnedAgent: Agent | null;
  // Agent Profile Panel (AD-406)
  activeProfileAgent: string | null;
  profilePanelPos: { x: number; y: number };
  agentConversations: Map<string, AgentConversation>;
  // Ward Room (AD-407)
  wardRoomChannels: WardRoomChannel[];
  // Ward Room HXI (AD-407c)
  wardRoomOpen: boolean;
  wardRoomActiveChannel: string | null;
  wardRoomThreads: WardRoomThread[];
  wardRoomActiveThread: string | null;
  wardRoomThreadDetail: { thread: WardRoomThread; posts: WardRoomPost[] } | null;
  wardRoomUnread: Record<string, number>;
  wardRoomView: 'channels' | 'dms';
  wardRoomDmChannels: { channel: { id: string; name: string; description: string; created_at: number }; latest_thread: any; thread_count: number }[];
  // Assignments (AD-408)
  assignments: Assignment[];
  // Scheduled Tasks (Phase 25a)
  scheduledTasks: ScheduledTaskView[];
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

  // Atmosphere preferences (AD-391)
  scanLinesEnabled: boolean;
  chromaticAberrationEnabled: boolean;
  dataRainEnabled: boolean;
  atmosphereIntensity: number;

  // Actions
  handleEvent: (event: WSEvent) => void;
  addChatMessage: (role: 'user' | 'system', text: string, meta?: { selfModProposal?: SelfModProposal; buildProposal?: BuildProposal; buildFailureReport?: BuildFailureReport; architectProposal?: ArchitectProposalView }) => void;
  clearAnimationEvent: (key: 'pendingConsensusFlash' | 'pendingSelfModBloom' | 'pendingRoutingPulse' | 'pendingFeedbackPulse') => void;
  setConnected: (v: boolean) => void;
  setHoveredAgent: (agent: Agent | null, pos?: { x: number; y: number }) => void;
  setPinnedAgent: (agent: Agent | null) => void;
  // Agent Profile Panel actions (AD-406)
  openAgentProfile: (agentId: string) => void;
  closeAgentProfile: () => void;
  minimizeAgentProfile: () => void;
  addAgentMessage: (agentId: string, role: 'user' | 'agent', text: string) => void;
  markAgentRead: (agentId: string) => void;
  setProfilePanelPos: (pos: { x: number; y: number }) => void;
  // Ward Room HXI actions (AD-407c)
  openWardRoom: (channelId?: string) => void;
  closeWardRoom: () => void;
  selectWardRoomChannel: (channelId: string) => void;
  selectWardRoomThread: (threadId: string) => void;
  closeWardRoomThread: () => void;
  refreshWardRoomThreads: () => void;
  refreshWardRoomUnread: () => void;
  setWardRoomView: (view: 'channels' | 'dms') => void;
  refreshWardRoomDmChannels: () => void;
  // Communications settings (AD-485)
  communicationsSettings: { dm_min_rank: string; recreation_min_rank: string };
  refreshCommunicationsSettings: () => void;
  updateCommunicationsSettings: (settings: Partial<{ dm_min_rank: string; recreation_min_rank: string }>) => void;
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
  setScanLinesEnabled: (v: boolean) => void;
  setChromaticAberrationEnabled: (v: boolean) => void;
  setDataRainEnabled: (v: boolean) => void;
  setAtmosphereIntensity: (v: number) => void;
  // Scheduled Tasks (Phase 25a)
  refreshScheduledTasks: () => Promise<void>;
  // Workforce actions (AD-497)
  moveWorkItem: (itemId: string, newStatus: string) => Promise<void>;
  assignWorkItem: (itemId: string, resourceId: string) => Promise<void>;
  createWorkItem: (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string }) => Promise<void>;
  // AD-498: Template actions
  fetchWorkTypes: () => Promise<void>;
  fetchWorkTemplates: () => Promise<void>;
  createFromTemplate: (templateId: string, variables?: Record<string, string>, overrides?: Record<string, any>) => Promise<void>;
}

/** Derive MissionControlTasks from BuildQueueItems (AD-322). */
function buildQueueToTasks(items: BuildQueueItem[]): MissionControlTask[] {
  const statusMap: Record<string, MissionControlTask['status']> = {
    queued: 'queued',
    dispatched: 'working',
    building: 'working',
    reviewing: 'review',
    merged: 'done',
    failed: 'failed',
  };
  return items.map(b => ({
    id: b.id,
    type: 'build' as const,
    title: b.title,
    department: 'engineering',
    status: statusMap[b.status] || 'queued',
    agent_type: 'builder',
    agent_id: b.builder_id || '',
    started_at: 0,
    completed_at: 0,
    priority: b.priority,
    ad_number: b.ad_number,
    error: b.error,
    metadata: { file_footprint: b.file_footprint, commit_hash: b.commit_hash, worktree_path: b.worktree_path },
  }));
}

export const useStore = create<HXIState>((set, get) => ({
  agents: new Map(),
  connections: [],
  pools: [],
  groupCenters: new Map(),
  poolToGroup: {},
  poolGroups: {},
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
  buildProgress: null,
  designProgress: null,
  transporterProgress: null,
  buildQueue: null,
  missionControlTasks: null,
  bridgeOpen: false,
  mainViewer: 'canvas' as const,
  agentTasks: null,
  workItems: null,
  workBookings: null,
  bookableResources: null,
  workTypeDefinitions: null,
  workTemplates: null,
  expandedGlassTask: null,
  notifications: null,
  pendingRoutingPulse: null,
  pendingFeedbackPulse: null,
  connected: false,
  hoveredAgent: null,
  tooltipPos: { x: 0, y: 0 },
  pinnedAgent: null,
  // Agent Profile Panel (AD-406)
  activeProfileAgent: null,
  profilePanelPos: { x: 100, y: 100 },
  agentConversations: new Map(),
  // Ward Room (AD-407)
  wardRoomChannels: [],
  // Ward Room HXI (AD-407c)
  wardRoomOpen: false,
  wardRoomActiveChannel: null,
  wardRoomThreads: [],
  wardRoomActiveThread: null,
  wardRoomThreadDetail: null,
  wardRoomUnread: {},
  wardRoomView: 'channels' as const,
  wardRoomDmChannels: [],
  communicationsSettings: { dm_min_rank: 'ensign', recreation_min_rank: 'ensign' },
  // Assignments (AD-408)
  assignments: [],
  // Scheduled Tasks (Phase 25a)
  scheduledTasks: [] as ScheduledTaskView[],
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
  ...(() => {
    try {
      const stored = localStorage.getItem('hxi_atmosphere_prefs');
      if (stored) {
        const p = JSON.parse(stored);
        return {
          scanLinesEnabled: !!p.scanLinesEnabled,
          chromaticAberrationEnabled: !!p.chromaticAberrationEnabled,
          dataRainEnabled: !!p.dataRainEnabled,
          atmosphereIntensity: typeof p.atmosphereIntensity === 'number' ? p.atmosphereIntensity : 0.3,
        };
      }
    } catch {}
    return { scanLinesEnabled: false, chromaticAberrationEnabled: false, dataRainEnabled: false, atmosphereIntensity: 0.3 };
  })(),

  setConnected: (v) => { soundEngine.setConnected(v); set({ connected: v }); },
  setHoveredAgent: (agent, pos) => set(pos ? { hoveredAgent: agent, tooltipPos: pos } : { hoveredAgent: agent }),
  setPinnedAgent: (agent) => set({ pinnedAgent: agent }),
  // Agent Profile Panel actions (AD-406)
  openAgentProfile: (agentId) => set({
    activeProfileAgent: agentId,
    pinnedAgent: null,  // dismiss tooltip when profile opens
  }),
  closeAgentProfile: () => set({ activeProfileAgent: null }),
  minimizeAgentProfile: () => {
    const agentId = get().activeProfileAgent;
    if (!agentId) return;
    const convs = new Map(get().agentConversations);
    const conv = convs.get(agentId);
    if (conv) {
      convs.set(agentId, { ...conv, minimized: true });
    }
    set({ activeProfileAgent: null, agentConversations: convs });
  },
  addAgentMessage: (agentId, role, text) => {
    const convs = new Map(get().agentConversations);
    const existing = convs.get(agentId) || {
      agentId,
      messages: [],
      unreadCount: 0,
      minimized: false,
    };
    const msg: AgentProfileMessage = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      text,
      timestamp: Date.now() / 1000,
    };
    const isOpen = get().activeProfileAgent === agentId;
    convs.set(agentId, {
      ...existing,
      messages: [...existing.messages.slice(-99), msg],
      unreadCount: (role === 'agent' && !isOpen) ? existing.unreadCount + 1 : existing.unreadCount,
      minimized: existing.minimized,
    });
    set({ agentConversations: convs });
  },
  markAgentRead: (agentId) => {
    const convs = new Map(get().agentConversations);
    const conv = convs.get(agentId);
    if (conv) {
      convs.set(agentId, { ...conv, unreadCount: 0, minimized: false });
      set({ agentConversations: convs });
    }
  },
  setProfilePanelPos: (pos) => set({ profilePanelPos: pos }),
  // Ward Room HXI actions (AD-407c)
  openWardRoom: async (channelId?: string) => {
    set({ wardRoomOpen: true });
    // Ensure channels are loaded (fallback fetch if snapshot hasn't arrived)
    let channels = get().wardRoomChannels;
    if (channels.length === 0) {
      try {
        const resp = await fetch('/api/wardroom/channels');
        if (resp.ok) {
          const data = await resp.json();
          channels = data.channels || [];
          set({ wardRoomChannels: channels });
        }
      } catch { /* swallow */ }
    }
    if (channelId) {
      get().selectWardRoomChannel(channelId);
    } else {
      if (channels.length > 0 && !get().wardRoomActiveChannel) {
        get().selectWardRoomChannel(channels[0].id);
      }
    }
    get().refreshWardRoomUnread();
  },
  closeWardRoom: () => set({ wardRoomOpen: false }),
  selectWardRoomChannel: async (channelId: string) => {
    set({ wardRoomActiveChannel: channelId, wardRoomActiveThread: null, wardRoomThreadDetail: null });
    try {
      const resp = await fetch(`/api/wardroom/channels/${channelId}/threads?limit=50&sort=recent`);
      if (resp.ok) {
        const data = await resp.json();
        set({ wardRoomThreads: data.threads || [] });
      }
    } catch { /* swallow */ }
  },
  selectWardRoomThread: async (threadId: string) => {
    set({ wardRoomActiveThread: threadId });
    try {
      const resp = await fetch(`/api/wardroom/threads/${threadId}`);
      if (resp.ok) {
        const data = await resp.json();
        set({ wardRoomThreadDetail: { thread: data.thread, posts: data.posts || [] } });
      }
    } catch { /* swallow */ }
  },
  closeWardRoomThread: () => set({ wardRoomActiveThread: null, wardRoomThreadDetail: null }),
  refreshWardRoomThreads: async () => {
    const channelId = get().wardRoomActiveChannel;
    if (!channelId) return;
    try {
      const resp = await fetch(`/api/wardroom/channels/${channelId}/threads?limit=50&sort=recent`);
      if (resp.ok) {
        const data = await resp.json();
        set({ wardRoomThreads: data.threads || [] });
      }
    } catch { /* swallow */ }
  },
  refreshWardRoomUnread: async () => {
    try {
      const resp = await fetch('/api/wardroom/notifications?agent_id=captain');
      if (resp.ok) {
        const data = await resp.json();
        set({ wardRoomUnread: data.unread || {} });
      }
    } catch { /* swallow */ }
  },
  setWardRoomView: (view: 'channels' | 'dms') => set({ wardRoomView: view }),
  refreshWardRoomDmChannels: async () => {
    try {
      const resp = await fetch('/api/wardroom/dms');
      if (resp.ok) {
        const data = await resp.json();
        set({ wardRoomDmChannels: data || [] });
      }
    } catch { /* swallow */ }
  },
  refreshCommunicationsSettings: async () => {
    try {
      const resp = await fetch('/api/system/communications/settings');
      if (resp.ok) {
        const data = await resp.json();
        set({ communicationsSettings: data });
      }
    } catch { /* swallow */ }
  },
  updateCommunicationsSettings: async (settings) => {
    try {
      const resp = await fetch('/api/system/communications/settings', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (resp.ok) {
        const data = await resp.json();
        set({ communicationsSettings: data });
      }
    } catch { /* swallow */ }
  },
  refreshScheduledTasks: async () => {
    try {
      const res = await fetch('/api/scheduled-tasks?status=pending');
      const data = await res.json();
      set({ scheduledTasks: data.tasks || [] });
    } catch { /* fail silently */ }
  },
  moveWorkItem: async (itemId: string, newStatus: string) => {
    try {
      const resp = await fetch(`/api/work-items/${itemId}/transition`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch (e) {
      console.error('Failed to move work item:', e);
    }
  },
  assignWorkItem: async (itemId: string, resourceId: string) => {
    try {
      const resp = await fetch(`/api/work-items/${itemId}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resource_id: resourceId }),
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch (e) {
      console.error('Failed to assign work item:', e);
    }
  },
  createWorkItem: async (item: { title: string; priority?: number; work_type?: string; assigned_to?: string; description?: string }) => {
    try {
      const resp = await fetch('/api/work-items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item),
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch (e) {
      console.error('Failed to create work item:', e);
    }
  },
  // AD-498: Work type and template actions
  fetchWorkTypes: async () => {
    try {
      const resp = await fetch('/api/work-types');
      if (!resp.ok) return;
      const data = await resp.json();
      set({ workTypeDefinitions: data.work_types || [] });
    } catch (e) {
      console.error('Failed to fetch work types:', e);
    }
  },
  fetchWorkTemplates: async () => {
    try {
      const resp = await fetch('/api/templates');
      if (!resp.ok) return;
      const data = await resp.json();
      set({ workTemplates: data.templates || [] });
    } catch (e) {
      console.error('Failed to fetch templates:', e);
    }
  },
  createFromTemplate: async (templateId: string, variables?: Record<string, string>, overrides?: Record<string, any>) => {
    try {
      const resp = await fetch(`/api/work-items/from-template/${templateId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variables: variables || {}, overrides: overrides || {} }),
      });
      if (!resp.ok) throw new Error(await resp.text());
    } catch (e) {
      console.error('Failed to create from template:', e);
    }
  },
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
  setScanLinesEnabled: (v) => {
    set({ scanLinesEnabled: v });
    const s = get();
    localStorage.setItem('hxi_atmosphere_prefs', JSON.stringify({
      scanLinesEnabled: v, chromaticAberrationEnabled: s.chromaticAberrationEnabled,
      dataRainEnabled: s.dataRainEnabled, atmosphereIntensity: s.atmosphereIntensity,
    }));
  },
  setChromaticAberrationEnabled: (v) => {
    set({ chromaticAberrationEnabled: v });
    const s = get();
    localStorage.setItem('hxi_atmosphere_prefs', JSON.stringify({
      scanLinesEnabled: s.scanLinesEnabled, chromaticAberrationEnabled: v,
      dataRainEnabled: s.dataRainEnabled, atmosphereIntensity: s.atmosphereIntensity,
    }));
  },
  setDataRainEnabled: (v) => {
    set({ dataRainEnabled: v });
    const s = get();
    localStorage.setItem('hxi_atmosphere_prefs', JSON.stringify({
      scanLinesEnabled: s.scanLinesEnabled, chromaticAberrationEnabled: s.chromaticAberrationEnabled,
      dataRainEnabled: v, atmosphereIntensity: s.atmosphereIntensity,
    }));
  },
  setAtmosphereIntensity: (v) => {
    const clamped = Math.max(0, Math.min(1, v));
    set({ atmosphereIntensity: clamped });
    const s = get();
    localStorage.setItem('hxi_atmosphere_prefs', JSON.stringify({
      scanLinesEnabled: s.scanLinesEnabled, chromaticAberrationEnabled: s.chromaticAberrationEnabled,
      dataRainEnabled: s.dataRainEnabled, atmosphereIntensity: clamped,
    }));
  },

  addChatMessage: (role, text, meta) => {
    const msg: ChatMessage = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      text,
      timestamp: Date.now() / 1000,
      ...(meta?.selfModProposal ? { selfModProposal: meta.selfModProposal } : {}),
      ...(meta?.buildProposal ? { buildProposal: meta.buildProposal } : {}),
      ...(meta?.buildFailureReport ? { buildFailureReport: meta.buildFailureReport } : {}),
      ...(meta?.architectProposal ? { architectProposal: meta.architectProposal } : {}),
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
            callsign: a.callsign || '',  // BF-013
            displayName: a.display_name || '',
            pool: a.pool,
            state: a.state as Agent['state'],
            confidence: a.confidence,
            trust: a.trust,
            tier: a.tier as Agent['tier'],
            isCrew: (a as any).isCrew ?? false,
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
        // Build pool→group reverse map for layout clustering (AD-291, AD-296)
        // Prefer the authoritative pool_to_group from the registry (includes pools
        // not managed by ResourcePool, like red_team). Fall back to deriving from
        // pool_groups health status for backward compatibility.
        let poolToGroup: Record<string, string> = {};
        if (snap.pool_to_group) {
          poolToGroup = snap.pool_to_group;
        } else if (snap.pool_groups) {
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
          poolToGroup,
          poolGroups: snap.pool_groups || {},
          systemMode: snap.system_mode as SystemMode,
          tcN: snap.tc_n,
          routingEntropy: snap.routing_entropy,
          ...(snap.fresh_boot ? { chatHistory: [] } : {}),
        });
        // Hydrate agent tasks from snapshot (AD-316)
        if ((data as any).tasks) {
          const tasks = (data as any).tasks as AgentTaskView[];
          const mcTasks: MissionControlTask[] = tasks.map(t => ({
            id: t.id,
            type: t.type as MissionControlTask['type'],
            title: t.title,
            department: t.department,
            status: t.status as MissionControlTask['status'],
            agent_type: t.agent_type,
            agent_id: t.agent_id,
            started_at: t.started_at,
            completed_at: t.completed_at,
            priority: t.priority,
            ad_number: t.ad_number,
            error: t.error,
            metadata: t.metadata,
          }));
          set({
            agentTasks: tasks.length > 0 ? tasks : null,
            missionControlTasks: mcTasks.length > 0 ? mcTasks : null,
          });
        }
        // Hydrate notifications from snapshot (AD-323)
        if ((data as any).notifications) {
          const notifs = (data as any).notifications as NotificationView[];
          set({ notifications: notifs.length > 0 ? notifs : null });
        }
        // Hydrate ward room channels from snapshot (AD-407c)
        if ((data as any).ward_room_channels) {
          set({ wardRoomChannels: (data as any).ward_room_channels as WardRoomChannel[] });
          get().refreshWardRoomUnread();
        }
        // Hydrate assignments from snapshot (AD-408)
        if ((data as any).assignments) {
          set({ assignments: (data as any).assignments as Assignment[] });
        }
        // Hydrate scheduled tasks from snapshot (Phase 25a)
        if ((data as any).scheduled_tasks) {
          set({ scheduledTasks: (data as any).scheduled_tasks });
        }
        // Hydrate workforce from snapshot (AD-497)
        if ((data as any).workforce) {
          const wf = (data as any).workforce;
          set({
            workItems: wf.work_items?.length ? wf.work_items : null,
            workBookings: wf.bookings?.length ? wf.bookings : null,
            bookableResources: wf.resources?.length ? wf.resources : null,
            workTypeDefinitions: wf.work_types?.length ? wf.work_types : null,
            workTemplates: wf.templates?.length ? wf.templates : null,
          });
        }
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
              callsign: '',
              displayName: '',
              pool: d.pool,
              state: d.state as Agent['state'],
              confidence: d.confidence,
              trust: d.trust,
              tier: 'domain',
              isCrew: false,
              position: [0, 0, 0],
              createdAt: Date.now(),
            };
            agents.set(d.agent_id, newAgent);
          }
          const result = computeLayout(agents, s.poolToGroup, s.poolGroups);
          return { agents: result.agents, groupCenters: result.groupCenters };
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
        // Prefer agent_id for unique bloom targeting; fall back to agent_type
        const bloomTarget = (data.agent_id || data.agent_type) as string | undefined;
        if (bloomTarget) {
          set({ pendingSelfModBloom: bloomTarget });
        }
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'build_started': {
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'build_progress': {
        const step = data.step as string;
        const current = data.current as number;
        const total = data.total as number;
        const label = (data.step_label || data.message || '') as string;
        set({ buildProgress: { step, current, total, label } });
        if (label) {
          get().addChatMessage('system', label);
        }
        break;
      }

      case 'build_generated': {
        set({ buildProgress: null });
        const msg = (data.message || '') as string;
        const builderSource = (data.builder_source || 'native') as 'native' | 'visiting';
        const proposal: BuildProposal = {
          build_id: data.build_id as string,
          title: data.title as string,
          description: data.description as string,
          ad_number: data.ad_number as number,
          file_changes: data.file_changes as BuildProposal['file_changes'],
          change_count: data.change_count as number,
          llm_output: data.llm_output as string,
          status: 'review',
          builder_source: builderSource,
        };
        get().addChatMessage('system', msg, { buildProposal: proposal });
        break;
      }

      case 'build_success': {
        soundEngine.playSelfModSpawn();
        set({ buildProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'build_failure': {
        set({ buildProgress: null });
        const report = data.report as BuildFailureReport | undefined;
        if (report) {
          const summary = report.failure_summary || (data.message as string) || 'Build failed';
          get().addChatMessage('system', summary, { buildFailureReport: report });
        } else {
          // Legacy fallback — no structured report
          const msg = (data.message || '') as string;
          if (msg) get().addChatMessage('system', msg);
        }
        break;
      }

      case 'build_resolved': {
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'build_queue_update': {
        // Full queue snapshot
        const items = (data.items || []) as BuildQueueItem[];
        set({
          buildQueue: items.length > 0 ? items : null,
          missionControlTasks: items.length > 0 ? buildQueueToTasks(items) : null,
        });
        break;
      }

      case 'build_queue_item': {
        // Single item update — upsert into existing queue
        const item = data.item as BuildQueueItem;
        if (!item) break;
        const current = get().buildQueue || [];
        const idx = current.findIndex(b => b.id === item.id);
        const updated = [...current];
        if (idx >= 0) {
          updated[idx] = item;
        } else {
          updated.push(item);
        }
        // Remove merged/failed items older than 30s (auto-clear)
        const active = updated.filter(
          b => !['merged', 'failed'].includes(b.status)
        );
        const terminal = updated.filter(
          b => ['merged', 'failed'].includes(b.status)
        );
        set({ buildQueue: [...active, ...terminal].length > 0
          ? [...active, ...terminal] : null,
          missionControlTasks: [...active, ...terminal].length > 0
          ? buildQueueToTasks([...active, ...terminal]) : null,
        });

        // Log status transitions to chat
        if (item.status === 'building') {
          get().addChatMessage('system',
            `Builder started: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}`);
        } else if (item.status === 'reviewing') {
          get().addChatMessage('system',
            `Build ready for review: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}`);
        } else if (item.status === 'merged') {
          get().addChatMessage('system',
            `Build merged: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''} → ${item.commit_hash.slice(0, 7)}`);
        } else if (item.status === 'failed') {
          get().addChatMessage('system',
            `Build failed: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''} — ${item.error}`);
        }
        break;
      }

      case 'task_created':
      case 'task_updated': {
        const tasks = (data.tasks || []) as AgentTaskView[];
        const mcTasks: MissionControlTask[] = tasks.map(t => ({
          id: t.id,
          type: t.type as MissionControlTask['type'],
          title: t.title,
          department: t.department,
          status: t.status as MissionControlTask['status'],
          agent_type: t.agent_type,
          agent_id: t.agent_id,
          started_at: t.started_at,
          completed_at: t.completed_at,
          priority: t.priority,
          ad_number: t.ad_number,
          error: t.error,
          metadata: t.metadata,
        }));
        set({
          agentTasks: tasks.length > 0 ? tasks : null,
          missionControlTasks: mcTasks.length > 0 ? mcTasks : null,
        });
        break;
      }

      // AD-497: Workforce events
      case 'work_item_created':
      case 'work_item_updated':
      case 'work_item_assigned': {
        const item = data.work_item as WorkItemView;
        if (item) {
          const current = get().workItems || [];
          const idx = current.findIndex(w => w.id === item.id);
          if (idx >= 0) {
            const updated = [...current];
            updated[idx] = item;
            set({ workItems: updated });
          } else {
            set({ workItems: [...current, item] });
          }
        }
        if (data.booking) {
          const booking = data.booking as BookingView;
          const cBookings = get().workBookings || [];
          const bIdx = cBookings.findIndex(b => b.id === booking.id);
          if (bIdx >= 0) {
            const updated = [...cBookings];
            updated[bIdx] = booking;
            set({ workBookings: updated });
          } else {
            set({ workBookings: [...cBookings, booking] });
          }
        }
        break;
      }

      case 'work_item_deleted': {
        const deletedId = data.work_item_id as string;
        if (deletedId) {
          const current = get().workItems || [];
          set({ workItems: current.filter(w => w.id !== deletedId) });
        }
        break;
      }

      case 'booking_status_changed': {
        const booking = data.booking as BookingView;
        if (booking) {
          const current = get().workBookings || [];
          const idx = current.findIndex(b => b.id === booking.id);
          if (idx >= 0) {
            const updated = [...current];
            updated[idx] = booking;
            set({ workBookings: updated });
          } else {
            set({ workBookings: [...current, booking] });
          }
        }
        break;
      }

      case 'transporter_decomposed': {
        const chunks = (data.chunks as Array<{ chunk_id: string; description: string; target_file: string }>) || [];
        const fallback = data.fallback as boolean;
        set({
          transporterProgress: {
            phase: 'decomposed',
            chunks: chunks.map(c => ({ ...c, status: 'pending' })),
            waves_completed: 0,
            total_chunks: chunks.length,
            successful: 0,
            failed: 0,
          },
        });
        const suffix = fallback ? ' (fallback)' : '';
        get().addChatMessage('system', `⬡ Transporter: decomposed into ${chunks.length} chunks${suffix}`);
        break;
      }

      case 'transporter_wave_start': {
        const wave = data.wave as number;
        const chunkIds = (data.chunk_ids as string[]) || [];
        const tp = get().transporterProgress;
        if (tp) {
          const updated = tp.chunks.map(c =>
            chunkIds.includes(c.chunk_id) ? { ...c, status: 'executing' } : c
          );
          set({ transporterProgress: { ...tp, chunks: updated } });
        }
        get().addChatMessage('system', `⬡ Wave ${wave}: ${chunkIds.length} chunks executing...`);
        break;
      }

      case 'transporter_chunk_done': {
        const chunkId = data.chunk_id as string;
        const success = data.success as boolean;
        const tp = get().transporterProgress;
        if (tp) {
          const updated = tp.chunks.map(c =>
            c.chunk_id === chunkId ? { ...c, status: success ? 'done' : 'failed' } : c
          );
          set({
            transporterProgress: {
              ...tp,
              chunks: updated,
              successful: success ? tp.successful + 1 : tp.successful,
              failed: success ? tp.failed : tp.failed + 1,
            },
          });
        }
        if (!success) {
          const err = data.error as string;
          get().addChatMessage('system', `⬡ Chunk ${chunkId} failed: ${err}`);
        }
        break;
      }

      case 'transporter_execution_done': {
        const total = data.total_chunks as number;
        const successful = data.successful as number;
        const waves = data.waves as number;
        const tp = get().transporterProgress;
        if (tp) {
          set({ transporterProgress: { ...tp, phase: 'executed', waves_completed: waves } });
        }
        get().addChatMessage('system', `⬡ Matter stream complete: ${successful}/${total} chunks in ${waves} wave(s)`);
        break;
      }

      case 'transporter_assembled': {
        const fileCount = data.file_count as number;
        const tp = get().transporterProgress;
        if (tp) {
          set({ transporterProgress: { ...tp, phase: 'assembled' } });
        }
        get().addChatMessage('system', `⬡ Rematerialized: ${fileCount} file(s) assembled`);
        break;
      }

      case 'transporter_validated': {
        const valid = data.valid as boolean;
        const errCount = (data.errors as Array<unknown>)?.length || 0;
        const warnCount = (data.warnings as Array<unknown>)?.length || 0;
        const tp = get().transporterProgress;
        if (tp) {
          set({ transporterProgress: { ...tp, phase: valid ? 'valid' : 'invalid' } });
        }
        if (valid) {
          get().addChatMessage('system', `⬡ Heisenberg compensator: all checks passed${warnCount > 0 ? ` (${warnCount} warnings)` : ''}`);
        } else {
          get().addChatMessage('system', `⬡ Heisenberg compensator: ${errCount} error(s) detected`);
        }
        // Clear transporter progress after validation
        set({ transporterProgress: null });
        break;
      }

      case 'design_started': {
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'design_progress': {
        const step = data.step as string;
        const current = data.current as number;
        const total = data.total as number;
        const label = (data.step_label || data.message || '') as string;
        set({ designProgress: { step, current, total, label } });
        if (label) {
          get().addChatMessage('system', label);
        }
        break;
      }

      case 'design_generated': {
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        const proposal: ArchitectProposalView = {
          design_id: data.design_id as string,
          title: data.title as string,
          summary: data.summary as string,
          rationale: data.rationale as string,
          roadmap_ref: data.roadmap_ref as string,
          priority: (data.priority as string || 'medium') as 'high' | 'medium' | 'low',
          dependencies: data.dependencies as string[],
          risks: data.risks as string[],
          build_spec: data.build_spec as ArchitectProposalView['build_spec'],
          llm_output: data.llm_output as string,
          status: 'review',
        };
        get().addChatMessage('system', msg, { architectProposal: proposal });
        break;
      }

      case 'design_success': {
        soundEngine.playSelfModSpawn();
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'design_failure': {
        set({ designProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }

      case 'notification':
      case 'notification_ack':
      case 'notification_snapshot': {
        const notifications = (data.notifications || []) as NotificationView[];
        set({ notifications: notifications.length > 0 ? notifications : null });
        break;
      }

      // Ward Room events (AD-407c)
      case 'ward_room_thread_created': {
        // BF-015: always refresh thread list and unread when a new thread arrives
        get().refreshWardRoomThreads();
        get().refreshWardRoomUnread();
        break;
      }
      case 'ward_room_post_created': {
        const threadId = (data as any).thread_id;
        if (get().wardRoomActiveThread === threadId) {
          get().selectWardRoomThread(threadId);
        }
        // BF-015: always refresh thread list (updates reply counts, last_activity)
        get().refreshWardRoomThreads();
        get().refreshWardRoomUnread();
        break;
      }
      case 'ward_room_endorsement':
      case 'ward_room_mod_action':
      case 'ward_room_mention': {
        get().refreshWardRoomUnread();
        break;
      }
      case 'ward_room_thread_updated': {
        // AD-424: Thread was reclassified, locked, or responder cap changed
        get().refreshWardRoomThreads();
        break;
      }

      // Assignment events (AD-408) — log only, canvas integration is Phase 2
      case 'assignment_created':
      case 'assignment_updated':
      case 'assignment_completed': {
        break;
      }

      // Scheduled Task events (Phase 25a)
      case 'scheduled_task_created':
      case 'scheduled_task_updated':
      case 'scheduled_task_cancelled':
      case 'scheduled_task_fired': {
        get().refreshScheduledTasks();
        break;
      }
      case 'scheduled_task_dag_stale': {
        // Surface as notification — stale DAGs need Captain review
        break;
      }

      default:
        break;
    }
  },
}));

export { POOL_HUES, GROUP_TINT_HEXES, computeLayout };

// Expose store in dev for console testing (e.g. Glass Bridge mock data)
if (import.meta.env.DEV) {
  (window as any).__store = useStore;
}
