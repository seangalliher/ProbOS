/**
 * AD-562: Ship's Records Knowledge Browser — host panel.
 *
 * 800×640 floating panel hosting four sub-views (List/Reader/Graph/Timeline)
 * via a view-mode tab switcher, with a left FilterRail and right BacklinksRail
 * (rail visible only in reader view + selection).
 */
import { useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import EntryListView from './knowledge/EntryListView';
import EntryReader from './knowledge/EntryReader';
import RecordsGraphView from './knowledge/RecordsGraphView';
import TimelineView from './knowledge/TimelineView';
import FilterRail from './knowledge/FilterRail';
import BacklinksRail from './knowledge/BacklinksRail';

export default function KnowledgeBrowserPanel() {
  const open = useStore(s => s.knowledgeBrowserOpen);
  const close = useStore(s => s.closeKnowledgeBrowser);
  const view = useStore(s => s.knowledgeBrowserView);
  const setView = useStore(s => s.setKnowledgeBrowserView);
  const refresh = useStore(s => s.refreshKnowledgeBrowser);
  const selectedPath = useStore(s => s.knowledgeBrowserSelectedPath);
  const loading = useStore(s => s.knowledgeBrowserLoading);

  const triggerRefresh = useCallback(() => { void refresh(); }, [refresh]);

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

  const showBacklinksRail = view === 'reader' && !!selectedPath;
  const gridTemplateColumns = showBacklinksRail ? '220px 1fr 240px' : '220px 1fr';

  return (
    <div
      data-testid="knowledge-browser-panel"
      style={{
        position: 'fixed',
        top: 90, left: 90,
        width: 800, height: 640,
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
          KNOWLEDGE BROWSER
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <div data-testid="knowledge-tab-list" onClick={() => setView('list')} style={tabStyle(view === 'list')}>LIST</div>
          <div data-testid="knowledge-tab-reader" onClick={() => setView('reader')} style={tabStyle(view === 'reader')}>READER</div>
          <div data-testid="knowledge-tab-graph" onClick={() => setView('graph')} style={tabStyle(view === 'graph')}>GRAPH</div>
          <div data-testid="knowledge-tab-timeline" onClick={() => setView('timeline')} style={tabStyle(view === 'timeline')}>TIMELINE</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <div
            data-testid="knowledge-refresh"
            onClick={triggerRefresh}
            style={iconBtnStyle}
            role="button"
            aria-label="Refresh"
          >↻</div>
          <div
            data-testid="knowledge-close"
            onClick={close}
            style={iconBtnStyle}
            role="button"
            aria-label="Close"
          >×</div>
        </div>
      </div>
      <div style={{
        flex: 1, minHeight: 0,
        display: 'grid', gridTemplateColumns, gap: 0,
      }}>
        <div style={{
          borderRight: '1px solid rgba(240,176,96,0.10)', overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
        }}>
          <FilterRail />
        </div>
        <div style={{ position: 'relative', minWidth: 0, overflow: 'hidden' }}>
          {loading && (
            <div data-testid="knowledge-loading" style={{
              position: 'absolute', top: 6, right: 10, fontSize: 10, color: '#666680',
            }}>loading…</div>
          )}
          {view === 'list' && <EntryListView />}
          {view === 'reader' && <EntryReader />}
          {view === 'graph' && <RecordsGraphView />}
          {view === 'timeline' && <TimelineView />}
        </div>
        {showBacklinksRail && (
          <div style={{ overflow: 'hidden' }}>
            <BacklinksRail />
          </div>
        )}
      </div>
    </div>
  );
}
