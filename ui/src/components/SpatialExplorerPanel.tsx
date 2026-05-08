/**
 * AD-520: Spatial Knowledge Explorer — host panel.
 *
 * 720×640 floating panel hosting the Phase 1 KnowledgeGraphView and
 * Phase 2 ShipLayoutView via a view-mode tab switcher. Read-only.
 * Mount fetches /api/ontology/graph + /api/ontology/spatial-layout once;
 * refresh button re-invokes both. ESC closes.
 */
import { useEffect, useCallback, useRef, useState } from 'react';
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

  // Draggable + resizable. Position/size local — declared before any early
  // return so hooks order is stable across renders.
  const [pos, setPos] = useState({ x: 80, y: 80 });
  const [size, setSize] = useState({ w: 720, h: 640 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null);

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

  const onHeaderPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    // Skip drag when click originated on a button/tab control.
    if ((e.target as HTMLElement).closest('[data-no-drag="1"]')) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
  };
  const onHeaderPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    const maxX = window.innerWidth - 80;  // keep at least a strip onscreen
    const maxY = window.innerHeight - 40;
    setPos({
      x: Math.max(-size.w + 80, Math.min(maxX, dragRef.current.origX + dx)),
      y: Math.max(0, Math.min(maxY, dragRef.current.origY + dy)),
    });
  };
  const onHeaderPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    dragRef.current = null;
  };

  const onResizePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    resizeRef.current = { startX: e.clientX, startY: e.clientY, origW: size.w, origH: size.h };
  };
  const onResizePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!resizeRef.current) return;
    const dw = e.clientX - resizeRef.current.startX;
    const dh = e.clientY - resizeRef.current.startY;
    setSize({
      w: Math.max(360, Math.min(window.innerWidth - 40, resizeRef.current.origW + dw)),
      h: Math.max(300, Math.min(window.innerHeight - 40, resizeRef.current.origH + dh)),
    });
  };
  const onResizePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    resizeRef.current = null;
  };

  return (
    <div
      data-testid="spatial-explorer-panel"
      style={{
        position: 'fixed',
        top: pos.y, left: pos.x,
        width: size.w, height: size.h,
        zIndex: 30,
        background: 'rgba(10,10,18,0.85)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(240,176,96,0.15)',
        borderRadius: 8,
        display: 'flex', flexDirection: 'column',
        color: '#cccce0',
        fontFamily: "'JetBrains Mono', monospace",
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
    >
      <div
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={onHeaderPointerUp}
        onPointerCancel={onHeaderPointerUp}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', borderBottom: '1px solid rgba(240,176,96,0.10)',
          cursor: 'move', userSelect: 'none', touchAction: 'none',
        }}
      >
        <div style={{ color: '#f0b060', fontWeight: 700, letterSpacing: 2, fontSize: 11 }}>
          SPATIAL EXPLORER
        </div>
        <div data-no-drag="1" style={{ display: 'flex', gap: 6 }}>
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
        <div data-no-drag="1" style={{ display: 'flex', gap: 6 }}>
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
      <div
        data-testid="spatial-resize-handle"
        onPointerDown={onResizePointerDown}
        onPointerMove={onResizePointerMove}
        onPointerUp={onResizePointerUp}
        onPointerCancel={onResizePointerUp}
        aria-label="Resize"
        style={{
          position: 'absolute',
          right: 0, bottom: 0,
          width: 16, height: 16,
          cursor: 'nwse-resize',
          touchAction: 'none',
          background:
            'linear-gradient(135deg, transparent 0 50%, rgba(240,176,96,0.35) 50% 60%, transparent 60% 70%, rgba(240,176,96,0.35) 70% 80%, transparent 80%)',
          borderBottomRightRadius: 8,
        }}
      />
    </div>
  );
}
