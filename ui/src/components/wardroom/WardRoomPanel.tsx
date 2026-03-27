import { useStore } from '../../store/useStore';
import { WardRoomChannelList } from './WardRoomChannelList';
import { WardRoomThreadList } from './WardRoomThreadList';
import { WardRoomThreadDetail } from './WardRoomThreadDetail';
import { useEffect } from 'react';

function DmChannelList() {
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refresh = useStore(s => s.refreshWardRoomDmChannels);
  const selectChannel = useStore(s => s.selectWardRoomChannel);

  useEffect(() => { refresh(); }, [refresh]);

  if (dmChannels.length === 0) {
    return (
      <div style={{ padding: '16px', color: '#8888a0', fontSize: 11, textAlign: 'center' }}>
        No crew DMs yet. Agents at Commander rank can initiate DMs.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }}>
      {dmChannels.map(dm => (
        <div
          key={dm.channel.id}
          onClick={() => selectChannel(dm.channel.id)}
          style={{
            padding: '8px 16px',
            cursor: 'pointer',
            borderBottom: '1px solid rgba(255,255,255,0.04)',
            fontSize: 12,
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(240,176,96,0.06)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'transparent'; }}
        >
          <div style={{ color: '#c0bab0', fontWeight: 600 }}>
            {dm.channel.description || dm.channel.name}
          </div>
          <div style={{ color: '#6a6a7a', fontSize: 10, marginTop: 2 }}>
            {dm.thread_count} message{dm.thread_count !== 1 ? 's' : ''}
          </div>
        </div>
      ))}
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
  const view = useStore(s => s.wardRoomView);
  const setView = useStore(s => s.setWardRoomView);

  const channelName = channels.find(c => c.id === activeChannel)?.name || '';

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
            }}>←</span>
          )}
          <span style={{
            fontSize: 11, letterSpacing: 1.5, fontWeight: 700,
            color: '#f0b060', textTransform: 'uppercase' as const,
          }}>
            {activeThread ? `# ${channelName}` : 'WARD ROOM'}
          </span>
        </div>
        <span onClick={onClose} style={{
          cursor: 'pointer', color: '#8888a0', fontSize: 16, lineHeight: 1,
        }}>✕</span>
      </div>

      {/* View tabs (only when not in a thread) */}
      {!activeThread && (
        <div style={{
          display: 'flex', gap: 8, padding: '4px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          <span style={tabStyle(view === 'channels')} onClick={() => setView('channels')}>
            Channels
          </span>
          <span style={tabStyle(view === 'dms')} onClick={() => setView('dms')}>
            Crew DMs
          </span>
        </div>
      )}

      {/* Body */}
      {activeThread ? (
        <WardRoomThreadDetail />
      ) : view === 'dms' ? (
        <DmChannelList />
      ) : (
        <>
          <WardRoomChannelList />
          <WardRoomThreadList />
        </>
      )}
    </div>
  );
}
