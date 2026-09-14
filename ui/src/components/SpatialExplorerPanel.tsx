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
import { idleResource, loadingResource, requestResource, resourceMessage } from '../utils/resourceState';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isVector(value: unknown): value is [number, number, number] {
  return Array.isArray(value) && value.length === 3
    && value.every(coordinate => typeof coordinate === 'number' && Number.isFinite(coordinate));
}

function isGraph(value: unknown): value is SpatialGraphData {
  return isRecord(value) && typeof value.generated_at === 'number' && Number.isFinite(value.generated_at)
    && Array.isArray(value.nodes) && value.nodes.every(node => isRecord(node) && typeof node.id === 'string')
    && Array.isArray(value.edges) && value.edges.every(edge => isRecord(edge)
      && typeof edge.source === 'string' && typeof edge.target === 'string' && typeof edge.relation === 'string');
}

function isLayout(value: unknown): value is SpatialLayoutData {
  return isRecord(value) && value.schema_version === 1 && Array.isArray(value.decks)
    && value.decks.every(deck => isRecord(deck) && typeof deck.deck_id === 'string'
      && typeof deck.name === 'string' && (deck.department_id === null || typeof deck.department_id === 'string')
      && isVector(deck.position) && isVector(deck.dimensions) && typeof deck.accent_color === 'string'
      && isRecord(deck.post_offsets) && Object.values(deck.post_offsets).every(isVector));
}

export default function SpatialExplorerPanel() {
  const open = useStore(s => s.spatialExplorerOpen);
  const close = useStore(s => s.closeSpatialExplorer);
  const viewMode = useStore(s => s.spatialViewMode);
  const setViewMode = useStore(s => s.setSpatialViewMode);
  const setGraphData = useStore(s => s.setSpatialGraphData);
  const setLayoutData = useStore(s => s.setSpatialLayoutData);
  const setSelected = useStore(s => s.setSpatialSelectedNode);
  const selected = useStore(s => s.spatialSelectedNode);
  const [graph, setGraph] = useState(() => idleResource<SpatialGraphData>());
  const [layout, setLayout] = useState(() => idleResource<SpatialLayoutData>());
  const snapshot = useRef({ graph, layout });
  const request = useRef<AbortController | null>(null);

  // Draggable + resizable. Position/size local — declared before any early
  // return so hooks order is stable across renders.
  const [pos, setPos] = useState({ x: 80, y: 80 });
  const [size, setSize] = useState({ w: 720, h: 640 });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; origW: number; origH: number } | null>(null);

  const refresh = useCallback(() => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const graphUrl = '/api/ontology/graph?include_edges=true';
    const layoutUrl = '/api/ontology/spatial-layout';
    const nextGraph = loadingResource(snapshot.current.graph, graphUrl);
    const nextLayout = loadingResource(snapshot.current.layout, layoutUrl);
    snapshot.current = { graph: nextGraph, layout: nextLayout };
    setGraph(nextGraph);
    setLayout(nextLayout);
    setSelected(null);
    void requestResource(graphUrl, nextGraph, isGraph, data => data.nodes.length === 0, controller.signal).then(result => {
      if (!result || controller.signal.aborted) return;
      snapshot.current.graph = result;
      setGraphData(result.data);
      setGraph(result);
    });
    void requestResource(layoutUrl, nextLayout, isLayout, data => data.decks.length === 0, controller.signal).then(result => {
      if (!result || controller.signal.aborted) return;
      snapshot.current.layout = result;
      setLayoutData(result.data);
      setLayout(result);
    });
  }, [setGraphData, setLayoutData, setSelected]);

  useEffect(() => {
    if (!open) return;
    refresh();
    return () => {
      request.current?.abort();
      snapshot.current = { graph: idleResource<SpatialGraphData>(), layout: idleResource<SpatialLayoutData>() };
      setGraphData(null);
      setLayoutData(null);
      setSelected(null);
    };
  }, [open, refresh, setGraphData, setLayoutData, setSelected]);

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
          <button
            type="button"
            data-testid="spatial-tab-graph"
            onClick={() => setViewMode('graph')}
            aria-pressed={viewMode === 'graph'}
            style={tabStyle(viewMode === 'graph')}
          >GRAPH</button>
          <button
            type="button"
            data-testid="spatial-tab-ship"
            onClick={() => setViewMode('ship')}
            aria-pressed={viewMode === 'ship'}
            style={tabStyle(viewMode === 'ship')}
          >SHIP LAYOUT</button>
        </div>
        <div data-no-drag="1" style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            data-testid="spatial-refresh"
            onClick={refresh}
            style={iconBtnStyle}
            aria-label="Refresh"
            title="Refresh"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
              <path d="M13 6a5 5 0 1 0 0 4M13 2v4H9" />
            </svg>
          </button>
          <button
            type="button"
            data-testid="spatial-close"
            onClick={close}
            style={iconBtnStyle}
            aria-label="Close"
            title="Close"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" />
            </svg>
          </button>
        </div>
      </div>
      <div style={{ padding: '6px 14px', fontSize: 11 }}>
        {([['Graph', graph], ['Ship layout', layout]] as const).map(([label, resource]) => (
          <div key={label} role="status" aria-label={`${label} status`} aria-live="polite">
            {label}: {resourceMessage(resource.status)}
            {resource.refreshing && ' Refreshing last successful snapshot.'}
            {resource.stale && ' Stale snapshot.'}
            {resource.observedAt !== null && <> Last successful observation: <time dateTime={new Date(resource.observedAt).toISOString()}>{new Date(resource.observedAt).toLocaleTimeString()}</time>.</>}
          </div>
        ))}
      </div>
      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        {viewMode === 'graph'
          ? graph.data !== null && graph.lastSuccess === 'ready' && <KnowledgeGraphView />
          : layout.data !== null && (layout.lastSuccess === 'ready' || layout.status === 'empty') && <ShipLayoutView />}
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
