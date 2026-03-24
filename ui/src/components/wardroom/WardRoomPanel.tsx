import { useStore } from '../../store/useStore';
import { WardRoomChannelList } from './WardRoomChannelList';
import { WardRoomThreadList } from './WardRoomThreadList';
import { WardRoomThreadDetail } from './WardRoomThreadDetail';

export function WardRoomPanel() {
  const open = useStore(s => s.wardRoomOpen);
  const onClose = useStore(s => s.closeWardRoom);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const closeThread = useStore(s => s.closeWardRoomThread);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const channels = useStore(s => s.wardRoomChannels);

  const channelName = channels.find(c => c.id === activeChannel)?.name || '';

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

      {/* Body */}
      {activeThread ? (
        <WardRoomThreadDetail />
      ) : (
        <>
          <WardRoomChannelList />
          <WardRoomThreadList />
        </>
      )}
    </div>
  );
}
