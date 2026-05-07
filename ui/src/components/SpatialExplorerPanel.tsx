/**
 * AD-520: Spatial Knowledge Explorer — host panel.
 *
 * 720×640 floating panel hosting the Phase 1 KnowledgeGraphView and
 * Phase 2 ShipLayoutView via a view-mode tab switcher. Read-only.
 * Mount fetches /api/ontology/graph + /api/ontology/spatial-layout once;
 * refresh button re-invokes both. ESC closes.
 */
import { useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import KnowledgeGraphView from './spatial/KnowledgeGraphView';
import ShipLayoutView from './spatial/ShipLayoutView';
import NodeDetailDrawer from './spatial/NodeDetailDrawer';
import type { SpatialGraphData, SpatialLayoutData } from '../store/types';

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

export default function SpatialExplorerPanel() {
  const open = useStore(s => s.spatialExplorerOpen);
  const close = useStore(s => s.closeSpatialExplorer);
  const viewMode = useStore(s => s.spatialViewMode);
  const setViewMode = useStore(s => s.setSpatialViewMode);
  const graphData = useStore(s => s.spatialGraphData);
  const layoutData = useStore(s => s.spatialLayoutData);
  const setGraphData = useStore(s => s.setSpatialGraphData);
  const setLayoutData = useStore(s => s.setSpatialLayoutData);
  const selected = useStore(s => s.spatialSelectedNode);

  const refresh = useCallback(async () => {
    const [g, l] = await Promise.all([
      fetchJson<SpatialGraphData>('/api/ontology/graph?include_edges=true'),
      fetchJson<SpatialLayoutData>('/api/ontology/spatial-layout'),
    ]);
    setGraphData(g);
    setLayoutData(l);
  }, [setGraphData, setLayoutData]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, close]);

  if (!open) return null;

  const tabStyle = (active: boolean) => ({
    padding: '6px 12px',
    border: `1px solid ${active ? '#f0b060' : 'rgba(240,176,96,0.15)'}`,
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: 10,
    letterSpacing: 1.5,
    fontFamily: "'JetBrains Mono', monospace",
    color: active ? '#f0b060' : '#8888a0',
    background: active ? 'rgba(240,176,96,0.08)' : 'transparent',
    userSelect: 'none' as const,
  });

  const iconBtnStyle = {
    padding: '4px 8px',
    border: '1px solid rgba(240,176,96,0.15)',
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: 14,
    lineHeight: 1,
    fontFamily: "'JetBrains Mono', monospace",
    color: '#8888a0',
    background: 'transparent',
    userSelect: 'none' as const,
  };

  const isEmpty = !graphData && !layoutData;

  return (
    <div
      data-testid="spatial-explorer-panel"
      style={{
        position: 'fixed',
        top: 80, left: 80,
        width: 720, height: 640,
        zIndex: 30,
        background: 'rgba(10,10,18,0.85)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(240,176,96,0.15)',
        borderRadius: 8,
        display: 'flex', flexDirection: 'column',
        color: '#cccce0',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', borderBottom: '1px solid rgba(240,176,96,0.10)',
      }}>
        <div style={{ color: '#f0b060', fontWeight: 700, letterSpacing: 2, fontSize: 11 }}>
          SPATIAL EXPLORER
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <div
            data-testid="spatial-tab-graph"
            onClick={() => setViewMode('graph')}
            style={tabStyle(viewMode === 'graph')}
          >GRAPH</div>
          <div
            data-testid="spatial-tab-ship"
            onClick={() => setViewMode('ship')}
            style={tabStyle(viewMode === 'ship')}
          >SHIP LAYOUT</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <div
            data-testid="spatial-refresh"
            onClick={() => { void refresh(); }}
            style={iconBtnStyle}
            role="button"
            aria-label="Refresh"
          >↻</div>
          <div
            data-testid="spatial-close"
            onClick={close}
            style={iconBtnStyle}
            role="button"
            aria-label="Close"
          >×</div>
        </div>
      </div>
      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        {isEmpty ? (
          <div data-testid="spatial-empty" style={{
            padding: 24, color: '#8888a0', fontSize: 12, textAlign: 'center',
          }}>
            No spatial data — enable in config or check ontology service
          </div>
        ) : viewMode === 'graph' ? (
          <KnowledgeGraphView />
        ) : (
          <ShipLayoutView />
        )}
        {selected && <NodeDetailDrawer />}
      </div>
    </div>
  );
}
