import { useStore } from '../../store/useStore';
import { WardRoomChannelList } from './WardRoomChannelList';
import { WardRoomThreadList } from './WardRoomThreadList';
import { WardRoomThreadDetail } from './WardRoomThreadDetail';
import { useEffect, useState, useRef, useCallback } from 'react';
import { ArrowRight, ArrowLeft, Close, Dock, Undock, Maximize, Restore } from '../icons/Glyphs';

/** AD-485/BF-054/BF-080: DM Activity Log — chronological feed with navigation */
function DmActivityLog() {
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refresh = useStore(s => s.refreshWardRoomDmChannels);
  const selectDm = useStore(s => s.selectDmChannel);
  const isOpen = useStore(s => s.wardRoomOpen);

  // BF-054 / AD-613: auto-refresh only when DM tab is visible AND panel is open
  useEffect(() => {
    if (!isOpen) return;
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, [refresh, isOpen]);

  if (dmChannels.length === 0) {
    return (
      <div style={{ padding: '16px', color: '#8888a0', fontSize: 11, textAlign: 'center' }}>
        No DM activity yet. Crew members can initiate direct messages with each other.
      </div>
    );
  }

  // Flatten all threads from all DM channels into a chronological feed
  const allEntries: { channel: any; thread: any }[] = [];
  for (const dm of dmChannels) {
    if (dm.latest_thread) {
      allEntries.push({ channel: dm.channel, thread: dm.latest_thread });
    }
  }
  allEntries.sort((a, b) => {
    const aTime = a.thread.created_at || a.thread.last_activity || 0;
    const bTime = b.thread.created_at || b.thread.last_activity || 0;
    return bTime - aTime;
  });

  const isCaptainDm = (name: string) => name.toLowerCase().includes('captain');

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
      {allEntries.map((entry, i) => {
        const t = entry.thread;
        const ch = entry.channel;
        const ts = t.created_at ? new Date(t.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        const preview = (t.body || '').slice(0, 120) + ((t.body || '').length > 120 ? '…' : '');
        const entryId = t.id || `${i}`;
        const captainBadge = isCaptainDm(ch.name);

        return (
          <div
            key={entryId}
            style={{
              padding: '8px 16px',
              borderBottom: '1px solid rgba(255,255,255,0.04)',
              fontSize: 12,
              cursor: 'pointer',
            }}
            onClick={() => selectDm(ch.id)}
            onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(240,176,96,0.06)'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
          >
            {/* Header — always visible */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <span style={{ color: '#6a6a7a', fontSize: 10 }}>{ts}</span>
              <span style={{ color: '#c0bab0', fontWeight: 600, fontSize: 11 }}>
                {ch.description || ch.name}
              </span>
              {captainBadge && (
                <span style={{
                  fontSize: 9, padding: '1px 5px', borderRadius: 3,
                  background: 'rgba(240,176,96,0.15)', color: '#f0b060',
                  fontWeight: 700, letterSpacing: 0.5,
                }}>CPT</span>
              )}
            </div>

            {/* Body — preview */}
            <div style={{ color: '#8888a0', fontSize: 11, lineHeight: 1.4 }}>
              {preview}
            </div>

            {/* BF-080: click entry to view full conversation */}
            <div style={{ marginTop: 4 }}>
              <span style={{ fontSize: 10, color: '#6a6a7a' }}>
                View conversation <ArrowRight size={10} />
              </span>
            </div>
          </div>
        );
      })}
      <div style={{ padding: '8px 16px', color: '#6a6a7a', fontSize: 10, textAlign: 'center' }}>
        {dmChannels.length} conversation{dmChannels.length !== 1 ? 's' : ''} total
      </div>
    </div>
  );
}

export function WardRoomPanel() {
  const open = useStore(s => s.wardRoomOpen);
  const onClose = useStore(s => s.closeWardRoom);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const closeThread = useStore(s => s.closeWardRoomThread);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const channels = useStore(s => s.wardRoomChannels);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const view = useStore(s => s.wardRoomView);
  const setView = useStore(s => s.setWardRoomView);

  // AD-837: window display mode (docked ↔ floating ↔ maximized).
  const displayMode = useStore(s => s.wardRoomDisplayMode);
  const windowRect = useStore(s => s.wardRoomWindowRect);
  const setDisplayMode = useStore(s => s.setWardRoomDisplayMode);

  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });

  // Drag (floating only) — mirror AgentProfilePanel's add-on-down /
  // remove-on-up listener discipline (no always-on global listeners).
  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if (displayMode !== 'floating') return;
    setIsDragging(true);
    dragOffset.current = { x: e.clientX - windowRect.x, y: e.clientY - windowRect.y };
  }, [displayMode, windowRect]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const rect = useStore.getState().wardRoomWindowRect;
      const newX = Math.max(0, Math.min(window.innerWidth - rect.w, e.clientX - dragOffset.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.current.y));
      useStore.getState().setWardRoomWindowRect({ ...rect, x: newX, y: newY });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  // Resize (floating only) — bottom-right corner, same min/clamp shape as
  // AgentProfilePanel (min 360×320, max viewport-40).
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    setIsResizing(true);
    resizeStart.current = { x: e.clientX, y: e.clientY, w: windowRect.w, h: windowRect.h };
    e.preventDefault();
    e.stopPropagation();
  }, [windowRect]);

  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      const rect = useStore.getState().wardRoomWindowRect;
      const dw = e.clientX - resizeStart.current.x;
      const dh = e.clientY - resizeStart.current.y;
      const nw = Math.max(360, Math.min(window.innerWidth - 40, resizeStart.current.w + dw));
      const nh = Math.max(320, Math.min(window.innerHeight - 40, resizeStart.current.h + dh));
      useStore.getState().setWardRoomWindowRect({ ...rect, w: nw, h: nh });
    };
    const onUp = () => setIsResizing(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isResizing]);

  const channelName = channels.find(c => c.id === activeChannel)?.name || '';
  const dmChannelInfo = dmChannels.find(d => d.channel.id === activeChannel)?.channel;

  // AD-837a: when the panel is opened up wide (maximized, or a floating window
  // resized past the three-pane threshold), the channels experience expands
  // into a Slack/Discord-style reading surface — channel rail | thread list |
  // thread detail, all visible at once — instead of the narrow stacked column.
  // Docked (420px) and narrow floating stay single-column (regression-safe).
  const effectiveWidth =
    displayMode === 'maximized' ? window.innerWidth - 32
    : displayMode === 'floating' ? windowRect.w
    : 420;
  const isWide = effectiveWidth >= 680;

  const tabStyle = (active: boolean) => ({
    padding: '4px 12px',
    fontSize: 10,
    letterSpacing: 1,
    fontWeight: 600 as const,
    cursor: 'pointer' as const,
    color: active ? '#f0b060' : '#6a6a7a',
    borderBottom: active ? '2px solid #f0b060' : '2px solid transparent',
    textTransform: 'uppercase' as const,
  });

  // AD-837: container chrome derived from display mode. The docked branch is
  // byte-equivalent to the pre-AD-837 sidebar (regression-safe default);
  // floating/maximized are windows gated by opacity/visibility (a window does
  // not slide in from the edge). The body components render identically in all
  // three modes — only the outer chrome changes.
  const baseChrome = {
    background: 'rgba(10, 10, 18, 0.92)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    display: 'flex',
    flexDirection: 'column' as const,
    fontFamily: "'JetBrains Mono', monospace",
    color: '#e0dcd4',
  };
  let containerStyle: React.CSSProperties;
  if (displayMode === 'floating') {
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      left: windowRect.x, top: windowRect.y,
      width: windowRect.w, height: windowRect.h,
      border: '1px solid rgba(240, 176, 96, 0.25)',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
      zIndex: 30,
      opacity: open ? 1 : 0,
      visibility: open ? 'visible' : 'hidden',
      pointerEvents: open ? 'auto' : 'none',
    };
  } else if (displayMode === 'maximized') {
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      inset: 16,
      border: '1px solid rgba(240, 176, 96, 0.25)',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
      zIndex: 30,
      opacity: open ? 1 : 0,
      visibility: open ? 'visible' : 'hidden',
      pointerEvents: open ? 'auto' : 'none',
    };
  } else {
    // docked (default) — unchanged 420px left sidebar.
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      top: 0, left: 0, bottom: 0,
      width: 420,
      borderRight: '1px solid rgba(240, 176, 96, 0.15)',
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(-100%)',
      transition: 'transform 0.25s ease-out',
      pointerEvents: open ? 'auto' : 'none',
    };
  }

  return (
    <div data-testid="wardroom-panel" data-mode={displayMode} style={containerStyle}>
      {/* Header (drag handle in floating mode) */}
      <div
        onMouseDown={onHeaderMouseDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          cursor: displayMode === 'floating' ? (isDragging ? 'grabbing' : 'grab') : 'default',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {activeThread && !isWide && (
            <span onClick={closeThread} onMouseDown={e => e.stopPropagation()} style={{
              cursor: 'pointer', color: '#8888a0', fontSize: 14, marginRight: 4,
            }}><ArrowLeft size={14} /></span>
          )}
          <span style={{
            fontSize: 11, letterSpacing: 1.5, fontWeight: 700,
            color: '#f0b060', textTransform: 'uppercase' as const,
          }}>
            {activeThread && !isWide ? `# ${channelName}` : 'WARD ROOM'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* AD-837: Dock/Undock toggle */}
          <span
            role="button"
            aria-label={displayMode === 'docked' ? 'Undock Ward Room' : 'Dock Ward Room'}
            title={displayMode === 'docked' ? 'Undock to floating window' : 'Dock to sidebar'}
            onMouseDown={e => e.stopPropagation()}
            onClick={() => setDisplayMode(displayMode === 'docked' ? 'floating' : 'docked')}
            style={{ cursor: 'pointer', display: 'flex', color: displayMode === 'docked' ? '#8888a0' : '#f0b060' }}
          >
            {displayMode === 'docked' ? <Undock size={15} /> : <Dock size={15} />}
          </span>
          {/* AD-837: Maximize/Restore — hidden in docked mode */}
          {displayMode !== 'docked' && (
            <span
              role="button"
              aria-label={displayMode === 'maximized' ? 'Restore Ward Room' : 'Maximize Ward Room'}
              title={displayMode === 'maximized' ? 'Restore window' : 'Maximize'}
              onMouseDown={e => e.stopPropagation()}
              onClick={() => setDisplayMode(displayMode === 'maximized' ? 'floating' : 'maximized')}
              style={{ cursor: 'pointer', display: 'flex', color: '#f0b060' }}
            >
              {displayMode === 'maximized' ? <Restore size={15} /> : <Maximize size={15} />}
            </span>
          )}
          <span onClick={onClose} onMouseDown={e => e.stopPropagation()} style={{
            cursor: 'pointer', color: '#8888a0', fontSize: 16, lineHeight: 1, display: 'flex',
          }}><Close size={16} /></span>
        </div>
      </div>

      {/* View tabs (Channels / DM Log). Always shown in wide mode (the channel
          rail is persistent); in narrow mode hidden once a thread is open. */}
      {view !== 'dm-detail' && (isWide || !activeThread) && (
        <div style={{
          display: 'flex', gap: 8, padding: '4px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <span style={tabStyle(view === 'channels')} onClick={() => setView('channels')}>
            Channels
          </span>
          <span style={tabStyle(view === 'dms')} onClick={() => setView('dms')}>
            DM Log
          </span>
        </div>
      )}

      {/* Body */}
      {isWide && view === 'channels' ? (
        /* AD-837a: three-pane reading surface — channel rail | thread list |
           thread detail, all visible simultaneously. */
        <div data-testid="wardroom-three-pane" style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          <div data-testid="wardroom-pane-channels" style={{
            width: 230, flexShrink: 0, overflowY: 'auto',
            borderRight: '1px solid rgba(255,255,255,0.06)',
          }}>
            <WardRoomChannelList />
          </div>
          <div data-testid="wardroom-pane-threads" style={{
            width: 320, flexShrink: 0, display: 'flex', flexDirection: 'column',
            minHeight: 0, borderRight: '1px solid rgba(255,255,255,0.06)',
          }}>
            <WardRoomThreadList />
          </div>
          <div data-testid="wardroom-pane-detail" style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            {activeThread ? (
              <WardRoomThreadDetail />
            ) : (
              <div data-testid="wardroom-detail-empty" style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 12,
                color: '#666680', padding: 32, textAlign: 'center' as const,
              }}>
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#444458"
                     strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <div style={{ fontSize: 12, letterSpacing: 0.5 }}>
                  Select a thread to read the full discussion
                </div>
              </div>
            )}
          </div>
        </div>
      ) : activeThread ? (
        <WardRoomThreadDetail />
      ) : view === 'dm-detail' ? (
        <>
          {/* BF-080: DM detail header with back navigation */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 16px',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            <span
              onClick={() => setView('dms')}
              style={{ cursor: 'pointer', color: '#8888a0', fontSize: 14 }}
            ><ArrowLeft size={14} /></span>
            <span style={{ fontSize: 11, color: '#c0bab0', fontWeight: 600 }}>
              {dmChannelInfo?.description || dmChannelInfo?.name || 'DM Conversation'}
            </span>
          </div>
          <WardRoomThreadList />
        </>
      ) : view === 'dms' ? (
        <DmActivityLog />
      ) : (
        <>
          <WardRoomChannelList />
          <WardRoomThreadList />
        </>
      )}

      {/* AD-837: resize handle (floating only, bottom-right corner) —
          mirrors AgentProfilePanel's nwse-resize handle. */}
      {displayMode === 'floating' && (
        <div
          onMouseDown={onResizeMouseDown}
          aria-label="Resize Ward Room"
          title="Drag to resize"
          style={{
            position: 'absolute',
            right: 0,
            bottom: 0,
            width: 14,
            height: 14,
            cursor: 'nwse-resize',
            zIndex: 5,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#8888a0"
               strokeWidth="1.25" strokeLinecap="round">
            <line x1="5" y1="14" x2="14" y2="5" />
            <line x1="9" y1="14" x2="14" y2="9" />
          </svg>
        </div>
      )}
    </div>
  );
}
