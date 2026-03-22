/* ProbOS HXI — Root application component */

import { useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useStore } from './store/useStore';
import { CognitiveCanvas } from './components/CognitiveCanvas';
import { FullKanban } from './components/bridge/FullKanban';
import { IntentSurface } from './components/IntentSurface';
import { DecisionSurface } from './components/DecisionSurface';
import { AgentTooltip } from './components/AgentTooltip';
import { WelcomeOverlay } from './components/WelcomeOverlay';

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
      {mainViewer === 'canvas' ? <CognitiveCanvas /> : <FullKanban />}
      <IntentSurface />
      <DecisionSurface />
      <AgentTooltip />
      <WelcomeOverlay />
    </div>
  );
}
