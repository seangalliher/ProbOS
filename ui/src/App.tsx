/* ProbOS HXI — Root application component */

import { useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useStore } from './store/useStore';
import { CognitiveCanvas } from './components/CognitiveCanvas';
import { FullKanban } from './components/bridge/FullKanban';
import { FullSystem } from './components/bridge/FullSystem';
import WorkBoard from './components/work/WorkBoard';
import BillDashboard from './components/BillDashboard';
import { GlassLayer } from './components/GlassLayer';
import { IntentSurface } from './components/IntentSurface';
import { DecisionSurface } from './components/DecisionSurface';
import { AgentTooltip } from './components/AgentTooltip';
import { AgentProfilePanel } from './components/profile';
import { WardRoomPanel } from './components/wardroom';
import { WelcomeOverlay } from './components/WelcomeOverlay';
import { GamePanel } from './components/GamePanel';
import CrewRosterPanel from './components/CrewRosterPanel';
import NotebooksPanel from './components/NotebooksPanel';
import BehavioralMetricsPanel from './components/BehavioralMetricsPanel';
import SpatialExplorerPanel from './components/SpatialExplorerPanel';
import KnowledgeBrowserPanel from './components/KnowledgeBrowserPanel';

// ── Top navigation ───────────────────────────────────────────────
// One flex container instead of 6 abs-positioned toggles. Items
// self-arrange so labels can grow without colliding. Visual hairline
// separators group items by purpose (people / knowledge / metrics).

interface NavButtonProps {
  label: string;
  active: boolean;
  onOpen: () => void;
  badge?: number;
  testId?: string;
}

function NavButton({ label, active, onOpen, badge, testId }: NavButtonProps) {
  if (active) return null;
  return (
    <div
      onClick={onOpen}
      data-testid={testId}
      style={{
        padding: '6px 12px',
        background: 'rgba(10, 10, 18, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(240, 176, 96, 0.15)',
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#8888a0',
        userSelect: 'none' as const,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        whiteSpace: 'nowrap' as const,
      }}
    >
      {label}
      {typeof badge === 'number' && badge > 0 && (
        <span style={{
          background: '#f0b060',
          color: '#0a0a12',
          borderRadius: 8,
          padding: '1px 6px',
          fontSize: 9,
          fontWeight: 700,
        }}>{badge}</span>
      )}
    </div>
  );
}

function NavSeparator() {
  return (
    <div style={{
      width: 1,
      height: 20,
      background: 'rgba(240, 176, 96, 0.12)',
      margin: '0 2px',
      alignSelf: 'center',
    }} />
  );
}

function TopNav() {
  const wardRoomOpen = useStore(s => s.wardRoomOpen);
  const openWardRoom = useStore(s => s.openWardRoom);
  const wardRoomUnread = useStore(s => s.wardRoomUnread);
  const totalUnread = Object.values(wardRoomUnread).reduce((sum, n) => sum + n, 0);

  const crewOpen = useStore(s => s.crewManifestOpen);
  const openCrew = useStore(s => s.openCrewManifest);

  const notebooksOpen = useStore(s => s.notebooksOpen);
  const openNotebooks = useStore(s => s.openNotebooks);

  const recordsOpen = useStore(s => s.knowledgeBrowserOpen);
  const openRecords = useStore(s => s.openKnowledgeBrowser);

  const explorerOpen = useStore(s => s.spatialExplorerOpen);
  const openExplorer = useStore(s => s.openSpatialExplorer);

  const metricsOpen = useStore(s => s.behavioralMetricsOpen);
  const openMetrics = useStore(s => s.openBehavioralMetrics);

  return (
    <div
      style={{
        position: 'fixed',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 25,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
      role="toolbar"
      aria-label="HXI panels"
    >
      {/* People */}
      <NavButton label="WARD ROOM" active={wardRoomOpen} onOpen={openWardRoom} badge={totalUnread} />
      <NavButton label="CREW" active={crewOpen} onOpen={openCrew} />
      <NavSeparator />
      {/* Knowledge */}
      <NavButton label="NOTEBOOKS" active={notebooksOpen} onOpen={openNotebooks} testId="notebooks-toggle" />
      <NavButton label="RECORDS" active={recordsOpen} onOpen={() => { void openRecords(); }} testId="knowledge-browser-toggle" />
      <NavButton label="EXPLORER" active={explorerOpen} onOpen={openExplorer} testId="spatial-explorer-toggle" />
      <NavSeparator />
      {/* Diagnostics */}
      <NavButton label="METRICS" active={metricsOpen} onOpen={openMetrics} testId="behavioral-metrics-toggle" />
    </div>
  );
}

export default function App() {
  useWebSocket();
  const mainViewer = useStore((s) => s.mainViewer);

  /* ── Global keydown: type-to-focus like Spotlight ── */
  useEffect(() => {
    function handleGlobalKey(e: KeyboardEvent) {
      // Don't capture if another input is focused
      if (document.activeElement?.tagName === 'INPUT' ||
          document.activeElement?.tagName === 'TEXTAREA') return;
      // Only printable characters
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        useStore.getState().triggerInput(e.key);
      }
    }
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, []);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {mainViewer === 'canvas' ? <CognitiveCanvas /> : mainViewer === 'kanban' ? <FullKanban /> : mainViewer === 'work' ? <WorkBoard /> : mainViewer === 'bills' ? <BillDashboard /> : <FullSystem />}
      <GlassLayer />
      <IntentSurface />
      <DecisionSurface />
      <AgentTooltip />
      <AgentProfilePanel />
      <GamePanel />
      <WardRoomPanel />
      <CrewRosterPanel />
      <NotebooksPanel />
      <BehavioralMetricsPanel />
      <SpatialExplorerPanel />
      <KnowledgeBrowserPanel />
      <TopNav />
      <WelcomeOverlay />
    </div>
  );
}
