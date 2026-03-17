/* HXI TypeScript types matching Python event schema (AD-255) */

export interface Agent {
  id: string;
  agentType: string;
  pool: string;
  state: 'spawning' | 'active' | 'degraded' | 'recycling';
  confidence: number;
  trust: number;
  tier: 'core' | 'utility' | 'domain';
  position: [number, number, number];
  createdAt?: number;
  activatedAt?: number;
}

export interface Connection {
  source: string;
  target: string;
  relType: string;
  weight: number;
}

export interface PoolInfo {
  name: string;
  agentType: string;
  size: number;
  targetSize: number;
}

export interface PoolGroupInfo {
  name: string;
  display_name: string;
  total_agents: number;
  healthy_agents: number;
  health_ratio: number;
  pools: Record<string, { current_size: number; target_size: number; agent_type: string }>;
}

export type SystemMode = 'active' | 'idle' | 'dreaming';

export interface DagNode {
  id: string;
  intent: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  params: Record<string, unknown>;
  dependsOn: string[];
}

export interface SelfModProposal {
  intent_name: string;
  intent_description: string;
  parameters: Record<string, string>;
  original_message: string;
  status: 'proposed' | 'approved' | 'rejected';
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'system';
  text: string;
  timestamp: number;
  selfModProposal?: SelfModProposal;
}

export interface WSEvent {
  type: string;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface StateSnapshot {
  agents: Array<{
    id: string;
    agent_type: string;
    pool: string;
    state: string;
    confidence: number;
    trust: number;
    tier: string;
  }>;
  connections: Array<{
    source: string;
    target: string;
    rel_type: string;
    weight: number;
  }>;
  pools: Array<{
    name: string;
    agent_type: string;
    size: number;
    target_size: number;
  }>;
  system_mode: string;
  tc_n: number;
  routing_entropy: number;
  fresh_boot?: boolean;
  pool_groups?: Record<string, PoolGroupInfo>;
}

// Animation event types for the canvas
export interface TrustUpdateEvent {
  agent_id: string;
  new_score: number;
  success: boolean;
}

export interface HebbianUpdateEvent {
  source: string;
  target: string;
  weight: number;
  rel_type: string;
}

export interface ConsensusEvent {
  intent: string;
  outcome: string;
  approval_ratio: number;
  votes: number;
  shapley: Record<string, number>;
}

export interface SystemModeEvent {
  mode: SystemMode;
  previous: string;
}

export interface AgentStateEvent {
  agent_id: string;
  pool: string;
  state: string;
  confidence: number;
  trust: number;
}
