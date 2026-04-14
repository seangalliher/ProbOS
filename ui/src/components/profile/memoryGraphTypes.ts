/* AD-611: 3D Memory Graph type definitions. */

export interface MemoryGraphNode {
  id: string;
  label: string;
  timestamp: number;
  importance: number;
  activation: number;
  channel: string;
  department: string;
  agent_ids: string[];
  participants: string[];
  source: string;
  reflection: string;
  user_input: string;
  color: string;
  size: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  type: 'semantic' | 'thread' | 'temporal' | 'participant';
  weight: number;
  color: string;
}

export interface MemoryGraphMeta {
  agent_id: string;
  total_episodes: number;
  nodes_shown: number;
  ship_wide: boolean;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  meta: MemoryGraphMeta;
}

// Edge type visual config
export const EDGE_TYPE_CONFIG: Record<string, { color: string; opacity: number; label: string }> = {
  semantic:    { color: '#4a9eff', opacity: 0.4, label: 'Semantic' },
  thread:      { color: '#f0b060', opacity: 0.7, label: 'Thread' },
  temporal:    { color: '#6b7280', opacity: 0.2, label: 'Temporal' },
  participant: { color: '#c084fc', opacity: 0.7, label: 'Participant' },
};
