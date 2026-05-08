/**
 * AD-520: Spatial Knowledge Explorer — Phase 1 Knowledge Graph View.
 *
 * Wraps react-force-graph-3d with mode chips (ORG / TRUST / KNOWLEDGE / DEPARTMENT)
 * and a department filter. Read-only — clicks dispatch setSpatialSelectedNode.
 */
import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import { useStore } from '../../store/useStore';
import type { GraphMode } from './types';
import { departmentColor } from './types';

const MODES: Array<{ id: GraphMode; label: string }> = [
  { id: 'org', label: 'ORG CHART' },
  { id: 'trust', label: 'TRUST NETWORK' },
  { id: 'knowledge', label: 'KNOWLEDGE MAP' },
  { id: 'department', label: 'DEPARTMENT VIEW' },
];

const ORG_RELATIONS = new Set(['member_of', 'reports_to']);

interface RawNode { id: unknown; type?: unknown; department?: unknown; trust?: unknown; [k: string]: unknown }
interface RawEdge { id?: unknown; source: unknown; target: unknown; relation: unknown; weight?: unknown; [k: string]: unknown }

function clampSize(trust: unknown): number {
  const t = typeof trust === 'number' && isFinite(trust) ? trust : 0.5;
  return Math.max(3, Math.min(12, t * 10));
}

export default function KnowledgeGraphView() {
  const data = useStore(s => s.spatialGraphData);
  const setSelected = useStore(s => s.setSpatialSelectedNode);
  const [mode, setMode] = useState<GraphMode>('org');
  const [activeDept, setActiveDept] = useState<string | null>(null);

  const departments = useMemo<string[]>(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const n of data.nodes as unknown as RawNode[]) {
      const d = n.department;
      if (typeof d === 'string' && d) set.add(d);
    }
    return Array.from(set).sort();
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const rawNodes = data.nodes as unknown as RawNode[];
    const rawEdges = data.edges as unknown as RawEdge[];
    const visibleIds = new Set<string>();
    const nodes = rawNodes.filter(n => {
      if (activeDept) {
        const dept = typeof n.department === 'string' ? n.department : null;
        if (n.type === 'agent' && dept !== activeDept) return false;
        if (n.type === 'department' && String(n.id) !== activeDept) return false;
      }
      visibleIds.add(String(n.id));
      return true;
    }).map(n => ({
      ...n,
      id: String(n.id),
      val: clampSize(n.trust),
      color: departmentColor(typeof n.department === 'string' ? n.department : (n.type === 'department' ? String(n.id) : null)),
    }));

    let links: Array<Record<string, unknown>> = rawEdges.filter(e =>
      visibleIds.has(String(e.source)) && visibleIds.has(String(e.target))
    );
    if (mode === 'org') {
      links = links.filter(e => ORG_RELATIONS.has(String(e.relation)));
    } else if (mode === 'trust') {
      // BF #426: cap synthesized trust edges to keep ForceGraph3D layout fluid.
      // Bucket agents by department first (eliminates the cross-dept early-skip);
      // emit at most MAX_TRUST_EDGES total, prioritizing high-trust pairs.
      const MAX_TRUST_EDGES = 200;
      const HIGH_TRUST_THRESHOLD = 0.6;
      const byDept = new Map<string, RawNode[]>();
      for (const n of nodes) {
        if (n.type !== 'agent') continue;
        const d = typeof n.department === 'string' ? n.department : '';
        if (!d) continue;
        const arr = byDept.get(d);
        if (arr) arr.push(n as unknown as RawNode); else byDept.set(d, [n as unknown as RawNode]);
      }
      type Synth = { id: string; source: string; target: string; relation: string; weight: number };
      const synth: Synth[] = [];
      let overflow = false;
      outer: for (const agents of byDept.values()) {
        for (let i = 0; i < agents.length; i++) {
          for (let j = i + 1; j < agents.length; j++) {
            const a = agents[i]; const b = agents[j];
            const ta = typeof a.trust === 'number' ? a.trust : 0.5;
            const tb = typeof b.trust === 'number' ? b.trust : 0.5;
            synth.push({
              id: `trust:${a.id}:${b.id}`,
              source: String(a.id),
              target: String(b.id),
              relation: 'trust',
              weight: (ta + tb) / 2,
            });
            if (synth.length > MAX_TRUST_EDGES * 4) {
              // Hard ceiling on raw construction so a 1000-agent dept doesn't
              // allocate millions of objects before the sort below.
              overflow = true;
              break outer;
            }
          }
        }
      }
      if (synth.length > MAX_TRUST_EDGES || overflow) {
        synth.sort((x, y) => y.weight - x.weight);
        const filtered = synth.filter(e => e.weight >= HIGH_TRUST_THRESHOLD);
        links = (filtered.length > 0 ? filtered : synth).slice(0, MAX_TRUST_EDGES) as Array<Record<string, unknown>>;
      } else {
        links = synth as Array<Record<string, unknown>>;
      }
    }
    // KNOWLEDGE MAP: no further filter — all relations
    // DEPARTMENT VIEW: keep links as-is; clustering is via node placement
    return { nodes, links };
  }, [data, mode, activeDept]);

  const linkWidth = useCallback((link: any) => {
    const w = typeof link.weight === 'number' ? link.weight : 0.5;
    return 0.5 + w * 2;
  }, []);

  const onNodeClick = useCallback((node: any) => {
    setSelected({ kind: 'agent', id: String(node.id), payload: node });
  }, [setSelected]);

  // Track container size so ForceGraph3D resizes with the panel.
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const r = el.getBoundingClientRect();
      setContainerSize({ w: Math.round(r.width), h: Math.round(r.height) });
    };
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!data || data.nodes.length === 0) {
    return (
      <div data-testid="knowledge-graph-empty" style={{
        padding: 24, color: '#8888a0', fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12, textAlign: 'center',
      }}>
        No graph data — enable in config or check ontology service
      </div>
    );
  }

  return (
    <div data-testid="knowledge-graph-view" style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 6, padding: '6px 10px', flexWrap: 'wrap' }}>
        {MODES.map(m => (
          <div
            key={m.id}
            data-testid={`graph-mode-${m.id}`}
            onClick={() => setMode(m.id)}
            style={{
              padding: '4px 8px',
              border: `1px solid ${mode === m.id ? '#f0b060' : 'rgba(240,176,96,0.15)'}`,
              borderRadius: 4,
              fontSize: 9, fontFamily: "'JetBrains Mono', monospace", letterSpacing: 1,
              color: mode === m.id ? '#f0b060' : '#8888a0', cursor: 'pointer',
              background: mode === m.id ? 'rgba(240,176,96,0.08)' : 'transparent',
            }}
          >{m.label}</div>
        ))}
      </div>
      {departments.length > 0 && (
        <div style={{ display: 'flex', gap: 4, padding: '0 10px 6px', flexWrap: 'wrap' }}>
          <div
            data-testid="dept-filter-all"
            onClick={() => setActiveDept(null)}
            style={{
              padding: '3px 6px', fontSize: 8, fontFamily: "'JetBrains Mono', monospace", letterSpacing: 1,
              border: `1px solid ${activeDept === null ? '#f0b060' : 'rgba(240,176,96,0.10)'}`,
              borderRadius: 3, color: activeDept === null ? '#f0b060' : '#666680', cursor: 'pointer',
            }}
          >ALL</div>
          {departments.map(d => (
            <div
              key={d}
              data-testid={`dept-filter-${d}`}
              onClick={() => setActiveDept(activeDept === d ? null : d)}
              style={{
                padding: '3px 6px', fontSize: 8, fontFamily: "'JetBrains Mono', monospace", letterSpacing: 1,
                border: `1px solid ${activeDept === d ? departmentColor(d) : 'rgba(240,176,96,0.10)'}`,
                borderRadius: 3, color: activeDept === d ? departmentColor(d) : '#666680', cursor: 'pointer',
              }}
            >{d.toUpperCase()}</div>
          ))}
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <ForceGraph3D
          width={containerSize.w || undefined}
          height={containerSize.h || undefined}
          graphData={filtered as any}
          nodeId="id"
          nodeVal="val"
          nodeColor={(n: any) => n.color || '#888899'}
          linkColor={() => 'rgba(136,136,160,0.4)'}
          linkWidth={linkWidth}
          backgroundColor="#0a0a12"
          onNodeClick={onNodeClick}
          enableNodeDrag={true}
          warmupTicks={20}
          cooldownTime={2000}
          dagMode={mode === 'org' ? 'td' : undefined}
        />
      </div>
    </div>
  );
}
