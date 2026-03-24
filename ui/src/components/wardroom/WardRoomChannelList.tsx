import { useStore } from '../../store/useStore';
import type { WardRoomChannel } from '../../store/types';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
  operations: '#b0a050',
};

function channelTypeColor(ch: WardRoomChannel): string {
  if (ch.channel_type === 'ship') return '#f0b060';
  if (ch.channel_type === 'department') return DEPT_COLORS[ch.department] || '#8888a0';
  return '#8888a0';
}

function channelOrder(ch: WardRoomChannel): number {
  if (ch.channel_type === 'ship') return 0;
  if (ch.channel_type === 'department') return 1;
  return 2;
}

export function WardRoomChannelList() {
  const channels = useStore(s => s.wardRoomChannels);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const selectChannel = useStore(s => s.selectWardRoomChannel);
  const unread = useStore(s => s.wardRoomUnread);

  const visible = channels
    .filter(c => !c.archived && c.channel_type !== 'dm')
    .sort((a, b) => {
      const oa = channelOrder(a);
      const ob = channelOrder(b);
      if (oa !== ob) return oa - ob;
      return a.name.localeCompare(b.name);
    });

  return (
    <div style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: 4 }}>
      <div style={{
        fontSize: 10, textTransform: 'uppercase' as const, letterSpacing: 1.5,
        fontWeight: 700, color: '#8888a0', padding: '8px 12px 4px',
      }}>Channels</div>
      {visible.map(ch => {
        const isActive = ch.id === activeChannel;
        const unreadCount = unread[ch.id] || 0;
        return (
          <div key={ch.id} onClick={() => selectChannel(ch.id)} style={{
            padding: '6px 12px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: isActive ? 'rgba(240, 176, 96, 0.08)' : 'transparent',
            borderLeft: isActive ? '2px solid #f0b060' : '2px solid transparent',
          }}>
            <span style={{ color: channelTypeColor(ch), fontSize: 12 }}>#</span>
            <span style={{ flex: 1, fontSize: 13, color: isActive ? '#f0b060' : '#e0dcd4' }}>
              {ch.name}
            </span>
            {unreadCount > 0 && (
              <span style={{
                background: '#f0b060',
                color: '#0a0a12',
                borderRadius: 8,
                padding: '1px 6px',
                fontSize: 10,
                fontWeight: 700,
              }}>{unreadCount}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
