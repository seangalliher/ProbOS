/*
 * CompactApp — chat-only experience for the Yeo desktop tray app.
 *
 * Renders the Captain's Yeoman (callsign "Yeo") `ProfileChatTab` fullscreen,
 * with no canvas, no panels, no top nav. The intent is parity with the
 * Microsoft Copilot / Claude Chat surface: just messages and an input.
 *
 * Selected at runtime when `location.hash` includes `#compact`. The Yeo
 * Electron host loads `${RUNTIME_URL}/#compact` by default; the in-page
 * "Open full HXI" link clears the hash and reloads.
 */
import { useEffect, useMemo, useState } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { useStore } from './store/useStore';
import { ProfileChatTab } from './components/profile/ProfileChatTab';
import { YeoStarterChips } from './components/YeoStarterChips';
import { YeoEmptyGreeting } from './components/YeoEmptyGreeting';
import { ThreadSidebar, loadSidebarCollapsed } from './components/sidebar/ThreadSidebar';
import { stopCameraStream } from './hooks/useCameraStream';
import { startVoiceActivity, stopVoiceActivity } from './audio/voiceActivity';
import { useSettingsStore } from './store/useSettingsStore';

const AMBER = '#f0b060';
const DIM = '#8888a0';
const BG = '#0a0a14';

/** Bridge to the Electron preload, if present. */
interface ProbosBridge {
  setViewMode?: (mode: 'compact' | 'full') => Promise<unknown>;
}
function probosBridge(): ProbosBridge | undefined {
  return (typeof window !== 'undefined' ? (window as unknown as { probos?: ProbosBridge }).probos : undefined);
}

function switchToFull(): void {
  const bridge = probosBridge();
  if (bridge?.setViewMode) {
    void bridge.setViewMode('full');
    return;
  }
  // Browser fallback: drop the #compact hash and reload.
  const url = new URL(window.location.href);
  url.hash = '';
  window.location.replace(url.toString());
}

export default function CompactApp() {
  useWebSocket();

  const agents = useStore((s) => s.agents);
  const markAgentRead = useStore((s) => s.markAgentRead);

  // Find Yeo by callsign once agents stream in. Memoize so we don't re-derive
  // on every keystroke (agents map updates on every WS event).
  const yeo = useMemo(() => {
    for (const agent of agents.values()) {
      if (agent.callsign === 'Yeo') return agent;
    }
    return null;
  }, [agents]);

  const yeoId = yeo?.id ?? null;

  // AD-792 (Wave 195): active-thread driven agent resolution. When the
  // operator picks a thread in the sidebar, the chat panel re-mounts
  // against ``participants[0]`` (single-participant 1:1 threads in v1).
  // Fall back to Yeo when no thread is active (cold-start parity).
  const activeThreadId = useStore((s) => s.activeThreadId);
  const chatThreads = useStore((s) => s.chatThreads);
  const derivedAgentId = useMemo(() => {
    if (activeThreadId) {
      const t = chatThreads.get(activeThreadId);
      if (t && t.participants.length > 0) return t.participants[0];
    }
    return yeoId;
  }, [activeThreadId, chatThreads, yeoId]);

  // AD-795/796: render starter chips + greeting only on the empty-thread
  // state. Subscribe directly to the message count so we re-render when
  // the first turn lands (chips/greeting must disappear immediately).
  const yeoMessageCount = useStore((s) =>
    derivedAgentId ? s.agentConversations.get(derivedAgentId)?.messages.length ?? 0 : 0,
  );
  const isEmptyThread = derivedAgentId !== null && yeoMessageCount === 0;

  useEffect(() => {
    if (derivedAgentId) markAgentRead(derivedAgentId);
  }, [derivedAgentId, markAgentRead]);

  // Mirror App.tsx camera cleanup and VAD arming so audio features stay parity.
  useEffect(() => {
    const onUnload = (): void => { void stopCameraStream(); };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, []);

  /* BF-304: fetch /api/config on mount so vad_engagement_enabled is
   * available without requiring the operator to open Settings. */
  const loadSnapshot = useSettingsStore((s) => s.loadSnapshot);
  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  const vadEnabled = useSettingsStore(
    (s) => Boolean((s.snapshot?.config as { perception?: { vad_engagement_enabled?: boolean } })?.perception?.vad_engagement_enabled),
  );
  useEffect(() => {
    if (!vadEnabled) {
      stopVoiceActivity();
      return;
    }
    void startVoiceActivity();
    return () => { stopVoiceActivity(); };
  }, [vadEnabled]);

  const [waitedTooLong, setWaitedTooLong] = useState(false);
  useEffect(() => {
    if (yeoId) return;
    const t = window.setTimeout(() => setWaitedTooLong(true), 5000);
    return () => window.clearTimeout(t);
  }, [yeoId]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: BG,
        color: '#e0dcd4',
        fontFamily: "'JetBrains Mono', monospace",
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Slim title bar — agent identity + switch-to-full link. */}
      <div
        style={{
          flex: '0 0 auto',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
          background: 'rgba(10, 10, 18, 0.92)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: yeo ? AMBER : DIM,
              boxShadow: yeo ? `0 0 6px ${AMBER}` : undefined,
            }}
          />
          <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 1 }}>
            {yeo?.displayName || yeo?.callsign || 'Yeo'}
          </span>
        </div>
        <button
          type="button"
          onClick={switchToFull}
          title="Switch to the full HXI experience"
          style={{
            background: 'transparent',
            border: '1px solid rgba(240, 176, 96, 0.3)',
            color: AMBER,
            fontFamily: 'inherit',
            fontSize: 10,
            letterSpacing: 1.2,
            padding: '4px 10px',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          FULL HXI
        </button>
      </div>

      {/* Chat surface — sidebar (left) + chat (right) fill the rest of the window. */}
      <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex' }}>
        <ThreadSidebar
          initialCollapsed={loadSidebarCollapsed()}
          onThreadSelected={(tid) => useStore.getState().setActiveThread(tid)}
          activeThreadId={activeThreadId}
        />
        <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {derivedAgentId ? (
          <>
            {isEmptyThread && (
              <div style={{ flex: '0 0 auto' }}>
                <YeoEmptyGreeting />
                <YeoStarterChips agentId={derivedAgentId} />
              </div>
            )}
            <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <ProfileChatTab agentId={derivedAgentId} threadId={activeThreadId ?? undefined} />
            </div>
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: DIM,
              fontSize: 12,
              padding: 24,
              textAlign: 'center',
            }}
          >
            {waitedTooLong
              ? 'Waiting for Yeo to come online… make sure the ProbOS runtime is running.'
              : 'Connecting to Yeo…'}
          </div>
        )}
        </div>
      </div>
    </div>
  );
}
