import { useState } from 'react';
import Markdown from 'react-markdown';
import { useStore } from '../../store/useStore';
import { EndorsementButtons } from './WardRoomEndorsement';
import { WardRoomPostItem } from './WardRoomPostItem';
import { timeAgo } from './timeAgo';

export function WardRoomThreadDetail() {
  const detail = useStore(s => s.wardRoomThreadDetail);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const [replyText, setReplyText] = useState('');

  if (!detail || !activeThread) return null;

  const { thread, posts } = detail;

  const submitReply = async () => {
    if (!replyText.trim()) return;
    try {
      await fetch(`/api/wardroom/threads/${activeThread}/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: 'captain',
          body: replyText.trim(),
          author_callsign: 'Captain',
        }),
      });
      setReplyText('');
      useStore.getState().selectWardRoomThread(activeThread);
    } catch { /* swallow */ }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {/* Thread header */}
      <div style={{ padding: '12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#e0dcd4' }}>
          {thread.title}
        </div>
        <div style={{ fontSize: 12, color: '#8888a0', marginTop: 4 }}>
          by {thread.author_callsign || 'unknown'} · {timeAgo(thread.created_at)}
        </div>
        {thread.body && (
          <div style={{ fontSize: 13, color: '#e0dcd4', marginTop: 8, fontFamily: "'Inter', sans-serif", lineHeight: 1.5 }}>
            <Markdown>{thread.body}</Markdown>
          </div>
        )}
        <div style={{ marginTop: 8 }}>
          <EndorsementButtons targetId={thread.id} targetType="thread" netScore={thread.net_score} />
        </div>
      </div>

      {/* Posts */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px' }}>
        {posts.length === 0 && (
          <div style={{ padding: 16, color: '#666680', fontSize: 12, textAlign: 'center' as const }}>
            No replies yet
          </div>
        )}
        {posts.map(post => (
          <WardRoomPostItem key={post.id} post={post} threadId={activeThread} depth={0} />
        ))}
      </div>

      {/* Reply input */}
      <div style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
        padding: '8px 12px',
        display: 'flex', gap: 6,
      }}>
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitReply(); } }}
          placeholder="Reply..."
          rows={2}
          style={{
            flex: 1, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 4, padding: '6px 8px', color: '#e0dcd4', fontSize: 12,
            fontFamily: "'Inter', sans-serif", outline: 'none', resize: 'none',
          }}
        />
        <button onClick={submitReply} style={{
          background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
          borderRadius: 4, color: '#f0b060', fontSize: 11, cursor: 'pointer', padding: '4px 10px',
          fontFamily: "'JetBrains Mono', monospace", alignSelf: 'flex-end',
        }}>Send</button>
      </div>
    </div>
  );
}
