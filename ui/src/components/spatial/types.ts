// AD-520: Spatial Knowledge Explorer — shared types
import type {
  SpatialViewMode,
  SpatialSelection,
  SpatialGraphData,
  SpatialLayoutData,
} from '../../store/types';

export type { SpatialViewMode, SpatialSelection, SpatialGraphData, SpatialLayoutData };

export interface SpatialNode {
  id: string;
  label: string;
  type: 'agent' | 'department';
  department?: string;
  rank?: string;
  trust?: number;
  post?: string;
  on_watch?: boolean;
  accent_color?: string;
}

export interface SpatialEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  weight: number;
  confidence?: number;
}

export type GraphMode = 'org' | 'trust' | 'knowledge' | 'department';

export const DEPARTMENT_PALETTE: Record<string, string> = {
  command: '#f0b060',
  engineering: '#d8742a',
  medical: '#54c474',
  security: '#c84858',
  science: '#5ca0d4',
  'ship-systems': '#8870c4',
};

export function departmentColor(dept: string | undefined | null): string {
  if (!dept) return '#666680';
  return DEPARTMENT_PALETTE[dept.toLowerCase()] || '#888899';
}
