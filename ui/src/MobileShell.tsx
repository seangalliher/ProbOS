/* MobileShell — full-screen chat surface for a real handheld PADD (AD-708b).
   Routed from main.tsx ONLY when isPadDevice() (coarse pointer AND 'mobile'
   width). Reuses ProfileChatTab against the Captain's Yeoman (callsign 'Yeo'),
   the same default CompactApp uses, but WITHOUT Electron-tray semantics.
   Progressive disclosure (HXI #5): chat is the minimal viable mobile surface;
   2D mesh (AD-708c) + gestures (AD-708d) are later increments. NO emoji (HXI #3). */
import { useEffect, useMemo, useState } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useStore } from './store/useStore';
import { useSettingsStore } from './store/useSettingsStore';
import { ProfileChatTab } from './components/profile/ProfileChatTab';
import MobileMesh from './components/mesh/MobileMesh';
import type { MeshViewport } from './mesh2d/meshProjection';

const AMBER = '#f0b060';
const DIM = '#8888a0';
const BG = '#0a0a14';

/** Header height (8px*2 padding + ~17px line + 1px border) subtracted from the
 *  window height to size the mesh body. A constant (not a measured ref) so the
 *  viewport is non-zero under jsdom, which performs no layout. */
const HEADER_H = 34;

/** Escape hatch / kill-switch: force the full desktop HXI via the `#desktop`
 *  hash + reload. Mirrors CompactApp's browser fallback, NO Electron bridge. */
function switchToFullHxi(): void {
  const url = new URL(window.location.href);
  url.hash = 'desktop';
  window.location.replace(url.toString());
}

export default function MobileShell() {
  useWebSocket();

  const agents = useStore((s) => s.agents);
  const loadSnapshot = useSettingsStore((s) => s.loadSnapshot);

  const yeoId = useMemo(() => {
    for (const agent of agents.values()) {
      if (agent.callsign === 'Yeo') return agent.id;
    }
    return null;
  }, [agents]);

  useEffect(() => { void loadSnapshot(); }, [loadSnapshot]);

  const [waitedTooLong, setWaitedTooLong] = useState(false);
  useEffect(() => {
    if (yeoId) return;
    const t = window.setTimeout(() => setWaitedTooLong(true), 5000);
    return () => window.clearTimeout(t);
  }, [yeoId]);

  // AD-708c-3: chat<->mesh body toggle. Default 'chat' -> the phone lands on the
  // AD-708b chat surface; the 2D mesh is opt-in via the header toggle.
  const [view, setView] = useState<'chat' | 'mesh'>('chat');

  // Measure the body on mount and on window resize. window.innerWidth/Height
  // are non-zero under jsdom (no layout), so the mesh gets a real viewport in
  // tests; a clientWidth-based ref would read 0. Mirrors usePadDevice (AD-708a).
  const [meshViewport, setMeshViewport] = useState<MeshViewport>(() => ({
    width: typeof window !== 'undefined' ? window.innerWidth : 360,
    height: typeof window !== 'undefined' ? Math.max(window.innerHeight - HEADER_H, 0) : 360,
  }));
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onResize = (): void =>
      setMeshViewport({ width: window.innerWidth, height: Math.max(window.innerHeight - HEADER_H, 0) });
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div data-testid="mobile-shell" style={{ position: 'fixed', inset: 0, background: BG,
      color: '#e0dcd4', fontFamily: "'JetBrains Mono', monospace",
      display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', padding: '8px 12px',
        borderBottom: '1px solid rgba(240, 176, 96, 0.15)', background: 'rgba(10, 10, 18, 0.92)' }}>
        <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 1 }}>Yeo</span>
        <div data-testid="mobile-view-toggle" role="group" aria-label="Chat or mesh view"
          style={{ display: 'flex', border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 4, overflow: 'hidden' }}>
          <button type="button" data-testid="mobile-toggle-chat" aria-pressed={view === 'chat'}
            onClick={() => setView('chat')}
            style={{ background: view === 'chat' ? 'rgba(240, 176, 96, 0.15)' : 'transparent',
              border: 'none', color: view === 'chat' ? AMBER : DIM, fontFamily: 'inherit',
              fontSize: 10, letterSpacing: 1.2, padding: '4px 12px', cursor: 'pointer' }}>
            CHAT
          </button>
          <button type="button" data-testid="mobile-toggle-mesh" aria-pressed={view === 'mesh'}
            onClick={() => setView('mesh')}
            style={{ background: view === 'mesh' ? 'rgba(240, 176, 96, 0.15)' : 'transparent',
              border: 'none', color: view === 'mesh' ? AMBER : DIM, fontFamily: 'inherit',
              fontSize: 10, letterSpacing: 1.2, padding: '4px 12px', cursor: 'pointer' }}>
            MESH
          </button>
        </div>
        <button type="button" onClick={switchToFullHxi} title="Switch to the full HXI experience"
          style={{ background: 'transparent', border: '1px solid rgba(240, 176, 96, 0.3)',
            color: AMBER, fontFamily: 'inherit', fontSize: 10, letterSpacing: 1.2,
            padding: '4px 10px', borderRadius: 4, cursor: 'pointer' }}>
          FULL HXI
        </button>
      </div>
      {view === 'chat' ? (
        <div data-testid="mobile-shell-chat" style={{ flex: '1 1 auto', minHeight: 0,
          display: 'flex', flexDirection: 'column' }}>
          {yeoId ? (
            <ProfileChatTab agentId={yeoId} />
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: DIM, fontSize: 12, padding: 24, textAlign: 'center' }}>
              {waitedTooLong
                ? 'Waiting for Yeo to come online… make sure the ProbOS runtime is running.'
                : 'Connecting to Yeo…'}
            </div>
          )}
        </div>
      ) : (
        <div data-testid="mobile-shell-mesh" style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden' }}>
          <MobileMesh viewport={meshViewport} />
        </div>
      )}
    </div>
  );
}
