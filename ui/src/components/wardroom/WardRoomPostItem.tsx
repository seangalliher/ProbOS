import { useState } from 'react';
import { useStore } from '../../store/useStore';
import type { WardRoomPost } from '../../store/types';
import { EndorsementButtons } from './WardRoomEndorsement';
import { timeAgo } from './timeAgo';

function ReplyInput({ threadId, parentId, onDone }: {
  threadId: string;
  parentId: string;
  onDone: () => void;
}) {
  const [text, setText] = useState('');

  const submit = async () => {
    if (!text.trim()) return;
    try {
      await fetch(`/api/wardroom/threads/${threadId}/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: 'captain',
          body: text.trim(),
          parent_id: parentId,
          author_callsign: 'Captain',
        }),
      });
      setText('');
      onDone();
      useStore.getState().selectWardRoomThread(threadId);
    } catch { /* swallow */ }
  };

  return (
    <div style={{ marginTop: 6, display: 'flex', gap: 6 }}>
      <input
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') submit(); }}
        placeholder="Reply..."
        style={{
          flex: 1, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 4, padding: '4px 8px', color: '#e0dcd4', fontSize: 12,
          fontFamily: "'Inter', sans-serif", outline: 'none',
        }}
      />
      <button onClick={submit} style={{
        background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
        borderRadius: 4, color: '#f0b060', fontSize: 11, cursor: 'pointer', padding: '4px 10px',
        fontFamily: "'JetBrains Mono', monospace",
      }}>Send</button>
    </div>
  );
}

export function WardRoomPostItem({ post, threadId, depth = 0 }: {
  post: WardRoomPost;
  threadId: string;
  depth?: number;
}) {
  const [replying, setReplying] = useState(false);

  return (
    <div style={{
      marginLeft: depth * 16,
      borderLeft: depth > 0 ? '1px solid rgba(255,255,255,0.08)' : 'none',
      paddingLeft: depth > 0 ? 12 : 0,
      paddingTop: 8,
      paddingBottom: 4,
    }}>
      <div style={{ fontSize: 12, color: '#f0b060' }}>
        {post.author_callsign || 'unknown'}
        <span style={{ color: '#666680', marginLeft: 8 }}>{timeAgo(post.created_at)}</span>
      </div>
      <div style={{ fontSize: 13, color: '#e0dcd4', marginTop: 2, fontFamily: "'Inter', sans-serif" }}>
        {post.body}
      </div>
      <div style={{ fontSize: 11, color: '#666680', marginTop: 4, display: 'flex', gap: 12, alignItems: 'center' }}>
        <EndorsementButtons targetId={post.id} targetType="post" netScore={post.net_score} />
        <span onClick={() => setReplying(!replying)} style={{ cursor: 'pointer', color: '#8888a0' }}>Reply</span>
      </div>
      {replying && (
        <ReplyInput threadId={threadId} parentId={post.id} onDone={() => setReplying(false)} />
      )}
      {post.children?.map(child => (
        <WardRoomPostItem key={child.id} post={child} threadId={threadId} depth={Math.min(depth + 1, 4)} />
      ))}
    </div>
  );
}
