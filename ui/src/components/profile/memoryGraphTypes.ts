/* AD-611: 3D Memory Graph type definitions. */

import { isNonnegative, isRecord, isSampleTime, validMeasurement } from '../../hooks/useProfileResource';

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
  total_episodes: number | null;
  nodes_shown: number;
  ship_wide: boolean;
  total_measurement?: MemoryGraphMeasurement;
  selection?: MemoryGraphSelection;
}

export interface MemoryGraphMeasurement {
  subject_id: string | null;
  population: string;
  unit: string;
  source: string;
  sample_started_at: string | null;
  sample_completed_at: string | null;
  status: 'available' | 'unavailable' | 'failed';
}

export interface MemoryGraphSelection {
  subject_id: string;
  population: 'registered_crew_bounded_graph' | 'agent_bounded_graph';
  unit: 'episodes';
  source: 'memory_graph.selection';
  status: 'available';
  sample_started_at: string;
  sample_completed_at: string;
  max_nodes: number;
  time_range_hours: number | null;
  bounded: true;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  meta: MemoryGraphMeta;
}

export function validMemoryGraph(
  value: unknown, agentId: string, shipWide: boolean, subjectId?: string,
): value is MemoryGraphResponse {
  if (!isRecord(value) || !isRecord(value.meta) || !Array.isArray(value.nodes) || !Array.isArray(value.edges)) return false;
  const meta = value.meta;
  if (meta.agent_id !== agentId || meta.ship_wide !== shipWide
    || !Number.isSafeInteger(meta.nodes_shown) || meta.nodes_shown !== value.nodes.length || value.nodes.length > 200
    || value.edges.length > 2000) return false;
  if (meta.total_episodes !== null && (!isNonnegative(meta.total_episodes) || !Number.isSafeInteger(meta.total_episodes))) return false;
  const nodeIds = new Set<string>();
  for (const node of value.nodes) {
    if (!isRecord(node) || typeof node.id !== 'string' || !node.id || nodeIds.has(node.id)) return false;
    if (!['label', 'channel', 'department', 'source', 'reflection', 'user_input', 'color'].every(key => typeof node[key] === 'string')) return false;
    if (!['timestamp', 'importance', 'activation', 'size'].every(key => isNonnegative(node[key]))) return false;
    if (!['agent_ids', 'participants'].every(key => Array.isArray(node[key]) && node[key].every((entry: unknown) => typeof entry === 'string'))) return false;
    nodeIds.add(node.id);
  }
  if (!value.edges.every(edge => isRecord(edge) && typeof edge.source === 'string' && nodeIds.has(edge.source)
    && typeof edge.target === 'string' && nodeIds.has(edge.target) && typeof edge.color === 'string'
    && typeof edge.type === 'string' && ['semantic', 'thread', 'temporal', 'participant'].includes(edge.type)
    && isNonnegative(edge.weight))) return false;
  if ('total_measurement' in meta) {
    const measurement = meta.total_measurement;
    if (!isRecord(measurement) || Object.keys(measurement).length !== 7
      || !['subject_id', 'population', 'unit', 'source', 'sample_started_at', 'sample_completed_at', 'status'].every(key => key in measurement)
      || !validMeasurement({ subjectId: measurement.subject_id, population: measurement.population,
        unit: measurement.unit, source: measurement.source, status: measurement.status,
        sampleStartedAt: measurement.sample_started_at, sampleCompletedAt: measurement.sample_completed_at },
      meta.total_episodes, subjectId ?? null, 'stored_agent_membership', 'episodes', 'episodic_memory.count_for_agent')) return false;
  }
  if ('selection' in meta) {
    const selection = meta.selection;
    if (!isRecord(selection) || Object.keys(selection).length !== 10
      || selection.subject_id !== (shipWide ? 'ship' : subjectId ?? (isRecord(meta.total_measurement) ? meta.total_measurement.subject_id : agentId))
      || selection.population !== (shipWide ? 'registered_crew_bounded_graph' : 'agent_bounded_graph')
      || selection.unit !== 'episodes' || selection.source !== 'memory_graph.selection' || selection.status !== 'available'
      || selection.bounded !== true || selection.max_nodes !== 200 || selection.time_range_hours !== null
      || !isSampleTime(selection.sample_started_at) || !isSampleTime(selection.sample_completed_at)
      || Date.parse(selection.sample_started_at) > Date.parse(selection.sample_completed_at)) return false;
  }
  return true;
}

export function memoryGraphSampleTime(value: MemoryGraphResponse): number | null {
  return value.meta.selection ? Date.parse(value.meta.selection.sample_completed_at) : null;
}

// Edge type visual config
export const EDGE_TYPE_CONFIG: Record<string, { color: string; opacity: number; label: string }> = {
  semantic:    { color: '#4a9eff', opacity: 0.4, label: 'Semantic' },
  thread:      { color: '#f0b060', opacity: 0.7, label: 'Thread' },
  temporal:    { color: '#6b7280', opacity: 0.2, label: 'Temporal' },
  participant: { color: '#c084fc', opacity: 0.7, label: 'Participant' },
};
