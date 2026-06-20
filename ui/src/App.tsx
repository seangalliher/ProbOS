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
import { MicPermissionHint } from './components/MicPermissionHint';
import { AgentProfilePanel } from './components/profile';
import { WardRoomPanel } from './components/wardroom';
import { WelcomeOverlay } from './components/WelcomeOverlay';
import { GamePanel } from './components/GamePanel';
import CrewRosterPanel from './components/CrewRosterPanel';
import CrewPersonnelConsole from './components/personnel/CrewPersonnelConsole';
import NotebooksPanel from './components/NotebooksPanel';
import ChatsPanel from './components/chats/ChatsPanel';
import BehavioralMetricsPanel from './components/BehavioralMetricsPanel';
import CommercialOverlayBadge from './components/CommercialOverlayBadge';
import SpatialExplorerPanel from './components/SpatialExplorerPanel';
import KnowledgeBrowserPanel from './components/KnowledgeBrowserPanel';
import SettingsPanel from './components/settings/SettingsPanel';
import { ShipsLockerPanel } from './components/bridge/ShipsLockerPanel';
import { McpServersPanel } from './components/mcp/McpServersPanel';
import { WorkstationPanel } from './components/workstation/WorkstationPanel';
import { WorkspacePanel } from './components/workspace/WorkspacePanel';
import { useSettingsStore } from './store/useSettingsStore';
import CameraLiveIndicator from './components/perception/CameraLiveIndicator';
import CameraPreviewPanel from './components/perception/CameraPreviewPanel';
import { stopCameraStream } from './hooks/useCameraStream';
import { startVoiceActivity, stopVoiceActivity } from './audio/voiceActivity';

// AD-944: the top-center "HXI panels" toolbar was retired — its nine launches
// now live in the Bridge command stations (communications / personnel / science /
// command). See ui/src/components/bridge/stations.tsx.

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

  /* AD-733: release the camera stream on page unload — never leave the
   * MediaStream alive across navigation. */
  useEffect(() => {
    const onUnload = () => { void stopCameraStream(); };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, []);

  /* BF-304: fetch /api/config on app mount so the snapshot is
   * populated immediately, without requiring the operator to open
   * the Settings dialog. App-level selectors that gate on snapshot
   * values (notably vad_engagement_enabled below) need the config
   * available at first paint, not after a manual interaction. */
  const loadSnapshot = useSettingsStore((s) => s.loadSnapshot);
  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  /* AD-733c-7-5: arm/disarm the browser-side Silero VAD loop in sync
   * with the snapshot toggle. Solo-Captain deployments (default
   * vad_engagement_enabled=false) render no audio context, no mic
   * prompt, no first-paint regression. */
  const vadEnabled = useSettingsStore(
    (s) => Boolean((s.snapshot?.config as any)?.perception?.vad_engagement_enabled),
  );
  useEffect(() => {
    if (!vadEnabled) {
      stopVoiceActivity();
      return;
    }
    void startVoiceActivity();
    return () => { stopVoiceActivity(); };
  }, [vadEnabled]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      {mainViewer === 'canvas' ? <CognitiveCanvas /> : mainViewer === 'kanban' ? <FullKanban /> : mainViewer === 'work' ? <WorkBoard /> : mainViewer === 'bills' ? <BillDashboard /> : <FullSystem />}
      <GlassLayer />
      <IntentSurface />
      <DecisionSurface />
      <AgentTooltip />
      {/* AD-736: mic-permission state surface (renders only on denied/unavailable). */}
      <MicPermissionHint />
      <AgentProfilePanel />
      <GamePanel />
      <WardRoomPanel />
      <CrewRosterPanel />
      <CrewPersonnelConsole />
      <NotebooksPanel />
      <ChatsPanel />
      <BehavioralMetricsPanel />
      <SpatialExplorerPanel />
      <KnowledgeBrowserPanel />
      <SettingsPanel />
      <ShipsLockerPanel />
      <McpServersPanel />
      <WorkstationPanel />
      <WorkspacePanel />
      <CameraLiveIndicator />
      <CameraPreviewPanel />
      {/* AD-944: the commercial-overlay status badge outlived the retired toolbar.
          It is invisible in the default OSS build (renders null when no overlay is
          loaded) but must stay mounted. Re-homed to the vacated top-left band. */}
      <div style={{ position: 'fixed', top: 12, left: 12, zIndex: 25 }}>
        <CommercialOverlayBadge />
      </div>
      <WelcomeOverlay />
    </div>
  );
}
