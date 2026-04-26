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

function CrewRosterToggle() {
  const open = useStore(s => s.crewManifestOpen);
  const openManifest = useStore(s => s.openCrewManifest);

  if (open) return null;

  return (
    <div
      onClick={() => openManifest()}
      style={{
        position: 'fixed',
        top: 12, left: 130,
        zIndex: 25,
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
      }}
    >
      CREW
    </div>
  );
}

function WardRoomToggle() {
  const open = useStore(s => s.wardRoomOpen);
  const openWardRoom = useStore(s => s.openWardRoom);
  const closeWardRoom = useStore(s => s.closeWardRoom);
  const unread = useStore(s => s.wardRoomUnread);
  const totalUnread = Object.values(unread).reduce((sum, n) => sum + n, 0);

  if (open) return null;

  return (
    <div
      onClick={() => openWardRoom()}
      style={{
        position: 'fixed',
        top: 12, left: 12,
        zIndex: 25,
        padding: '6px 12px',
        background: 'rgba(10, 10, 18, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: `1px solid rgba(240, 176, 96, ${open ? 0.35 : 0.15})`,
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: open ? '#f0b060' : '#8888a0',
        userSelect: 'none' as const,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      WARD ROOM
      {totalUnread > 0 && (
        <span style={{
          background: '#f0b060',
          color: '#0a0a12',
          borderRadius: 8,
          padding: '1px 6px',
          fontSize: 9,
          fontWeight: 700,
        }}>{totalUnread}</span>
      )}
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
      <WardRoomToggle />
      <CrewRosterPanel />
      <CrewRosterToggle />
      <WelcomeOverlay />
    </div>
  );
}
