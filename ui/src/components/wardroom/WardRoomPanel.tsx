import { useStore } from '../../store/useStore';
import { WardRoomChannelList } from './WardRoomChannelList';
import { WardRoomThreadList } from './WardRoomThreadList';
import { WardRoomThreadDetail } from './WardRoomThreadDetail';
import { useEffect } from 'react';
import { ArrowRight, ArrowLeft, Close } from '../icons/Glyphs';

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

  const channelName = channels.find(c => c.id === activeChannel)?.name || '';
  const dmChannelInfo = dmChannels.find(d => d.channel.id === activeChannel)?.channel;

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

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, bottom: 0,
      width: 420,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      borderRight: '1px solid rgba(240, 176, 96, 0.15)',
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(-100%)',
      transition: 'transform 0.25s ease-out',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: "'JetBrains Mono', monospace",
      pointerEvents: open ? 'auto' : 'none',
      color: '#e0dcd4',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {activeThread && (
            <span onClick={closeThread} style={{
              cursor: 'pointer', color: '#8888a0', fontSize: 14, marginRight: 4,
            }}><ArrowLeft size={14} /></span>
          <span style={{
            fontSize: 11, letterSpacing: 1.5, fontWeight: 700,
            color: '#f0b060', textTransform: 'uppercase' as const,
          }}>
            {activeThread ? `# ${channelName}` : 'WARD ROOM'}
          </span>
        </div>
        <span onClick={onClose} style={{
          cursor: 'pointer', color: '#8888a0', fontSize: 16, lineHeight: 1,
        }}><Close size={16} /></span>
      </div>

      {/* View tabs (only when not in a thread or dm-detail) */}
      {!activeThread && view !== 'dm-detail' && (
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
      {activeThread ? (
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
    </div>
  );
}
