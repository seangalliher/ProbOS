import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { timeAgo } from './timeAgo';
import { ArrowUp, Comment } from '../icons/Glyphs';

export function WardRoomThreadList() {
  const threads = useStore(s => s.wardRoomThreads);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const channels = useStore(s => s.wardRoomChannels);
  const selectThread = useStore(s => s.selectWardRoomThread);

  const channelName = channels.find(c => c.id === activeChannel)?.name || '';

  const [composing, setComposing] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');

  const submitThread = async () => {
    if (!title.trim() || !activeChannel) return;
    try {
      await fetch(`/api/wardroom/channels/${activeChannel}/threads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: 'captain',
          title: title.trim(),
          body: body.trim(),
          author_callsign: 'Captain',
        }),
      });
      setTitle('');
      setBody('');
      setComposing(false);
      useStore.getState().refreshWardRoomThreads();
    } catch { /* swallow */ }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{
        fontSize: 13, fontWeight: 600, color: '#f0b060', padding: '8px 12px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        # {channelName}
      </div>

      <div style={{ flex: 1, overflowY: 'auto' }}>
        {threads.length === 0 && (
          <div style={{ padding: 16, color: '#666680', fontSize: 12, textAlign: 'center' as const }}>
            No threads yet
          </div>
        )}
        {threads.map(t => (
          <div key={t.id} onClick={() => selectThread(t.id)} style={{
            padding: '10px 12px',
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            cursor: 'pointer',
          }}>
            {t.pinned && <span style={{ color: '#f0b060', fontSize: 10, fontWeight: 700 }}>PINNED</span>}
            <div style={{ fontSize: 14, color: '#e0dcd4', fontWeight: 500 }}>
              {t.title}
            </div>
            <div style={{ fontSize: 11, color: '#8888a0', marginTop: 4 }}>
              by {t.author_callsign || 'unknown'} · {timeAgo(t.last_activity)}
            </div>
            <div style={{ fontSize: 11, color: '#666680', marginTop: 4, display: 'flex', gap: 12 }}>
              <span><ArrowUp size={10} /> {t.net_score}</span>
              <span><Comment size={10} /> {t.reply_count}</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '8px 12px' }}>
        {!composing ? (
          <div onClick={() => setComposing(true)} style={{
            padding: '8px 12px',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 6,
            cursor: 'pointer',
            color: '#8888a0',
            fontSize: 12,
          }}>New Thread...</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Thread title"
              autoFocus
              style={{
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 4, padding: '6px 8px', color: '#e0dcd4', fontSize: 13,
                fontFamily: "'Inter', sans-serif", outline: 'none',
              }}
            />
            <textarea
              value={body}
              onChange={e => setBody(e.target.value)}
              placeholder="Body (optional)"
              rows={3}
              style={{
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 4, padding: '6px 8px', color: '#e0dcd4', fontSize: 12,
                fontFamily: "'Inter', sans-serif", outline: 'none', resize: 'none',
              }}
            />
            <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button onClick={() => setComposing(false)} style={{
                background: 'transparent', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 4, color: '#8888a0', fontSize: 11, cursor: 'pointer', padding: '4px 10px',
                fontFamily: "'JetBrains Mono', monospace",
              }}>Cancel</button>
              <button onClick={submitThread} style={{
                background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
                borderRadius: 4, color: '#f0b060', fontSize: 11, cursor: 'pointer', padding: '4px 10px',
                fontFamily: "'JetBrains Mono', monospace",
              }}>Post</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
