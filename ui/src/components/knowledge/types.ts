export interface KnowledgeBrowserEntry {
  path: string;
  frontmatter: {
    author?: string;
    department?: string;
    classification?: string;
    created?: string;
    updated?: string;
    revision_count?: number;
    topic_slug?: string;
    tags?: string[];
  };
}

export interface KnowledgeBrowserDoc extends KnowledgeBrowserEntry {
  content: string;
}

export interface KnowledgeReference {
  kind: 'wikilink' | 'callsign' | 'topic_slug' | 'tag';
  target: string;
  raw_match: string;
}

export interface KnowledgeBrowserBacklinks {
  path: string;
  references: KnowledgeReference[];
  referenced_by: string[];
  suggested: { path: string; similarity: number }[];
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type: string;
  department: string;
  classification: string;
  author: string;
  revision_count: number;
  is_convergence_hub: boolean;
  quality_overlay: {
    novel_content_rate: number | null;
    repetition_alerts: number | null;
    stale_rate: number | null;
  } | null;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  kind: 'backlink' | 'suggested' | 'convergence';
  similarity?: number;
}

export interface KnowledgeBrowserGraphData {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  generated_at: number;
  node_count: number;
  edge_count: number;
}

export interface KnowledgeBrowserTimelineBucket {
  date: string;
  count: number;
  by_department: Record<string, number>;
}

export interface KnowledgeBrowserTimeline {
  buckets: KnowledgeBrowserTimelineBucket[];
  total: number;
  bucket: string;
}

export interface KnowledgeBrowserFilters {
  author: string;
  department: string;
  classification: string;
  directory: string;
  tags: string;
  since: string;
  until: string;
}

export const DEFAULT_KNOWLEDGE_BROWSER_FILTERS: KnowledgeBrowserFilters = {
  author: '', department: '', classification: '',
  directory: '', tags: '', since: '', until: '',
};
