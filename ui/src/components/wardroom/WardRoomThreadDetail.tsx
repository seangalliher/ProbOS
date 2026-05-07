import { useState } from 'react';
import Markdown from 'react-markdown';
import { useStore } from '../../store/useStore';
import type { WardRoomPost } from '../../store/types';
import { EndorsementButtons } from './WardRoomEndorsement';
import { WardRoomPostItem } from './WardRoomPostItem';
import { timeAgo } from './timeAgo';

// AD-574b: Resolve the target agent_id for the active DM thread by scanning
// the wardRoomDmChannels listing for the channel that owns this thread.
// Returns null when not in a DM view, when the thread has no resolvable
// channel, or when the backend could not resolve the participant.
function resolveDmTargetAgentId(
  view: 'channels' | 'dms' | 'dm-detail',
  activeChannel: string | null,
  dmChannels: { channel: { id: string }; target_agent_id: string | null }[]
): string | null {
  if (view !== 'dm-detail' || !activeChannel) return null;
  const entry = dmChannels.find(c => c.channel.id === activeChannel);
  return entry?.target_agent_id ?? null;
}

/** AD-612: Recursively flatten a post tree into chronological order. */
function flattenPosts(posts: WardRoomPost[]): WardRoomPost[] {
  const result: WardRoomPost[] = [];
  function collect(list: WardRoomPost[]) {
    for (const p of list) {
      result.push(p);
      if (p.children?.length) collect(p.children);
    }
  }
  collect(posts);
  result.sort((a, b) => a.created_at - b.created_at);
  return result;
}

export function WardRoomThreadDetail() {
  const detail = useStore(s => s.wardRoomThreadDetail);
  const activeThread = useStore(s => s.wardRoomActiveThread);
  const view = useStore(s => s.wardRoomView);
  const activeChannel = useStore(s => s.wardRoomActiveChannel);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const dmPending = useStore(s => s.wardRoomDmPending);
  const [replyText, setReplyText] = useState('');

  if (!detail || !activeThread) return null;

  const { thread, posts } = detail;
  if (!thread) return null;
  const isDm = view === 'dm-detail';
  const flatPosts = isDm ? flattenPosts(posts) : null;
  const targetAgentId = resolveDmTargetAgentId(view, activeChannel, dmChannels);
  const isThinking = dmPending?.threadId === activeThread;

  // AD-574b: Synchronous DM reply via /api/agent/{id}/chat with dual-write to
  // Ward Room. Falls back to async post-only path when not a DM view, when
  // target agent cannot be resolved, or when the chat call fails.
  const submitReply = async () => {
    const text = replyText.trim();
    if (!text || isThinking) return;
    setReplyText('');

    const postCaptain = () => fetch(`/api/wardroom/threads/${activeThread}/posts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        author_id: 'captain',
        body: text,
        author_callsign: 'Captain',
      }),
    });

    if (!isDm || !targetAgentId) {
      // Existing async path — proactive cycle responds.
      try { await postCaptain(); } catch { /* swallow */ }
      useStore.getState().selectWardRoomThread(activeThread);
      return;
    }

    // Synchronous DM path with thinking indicator + dual-write.
    useStore.getState().setWardRoomDmPending({
      threadId: activeThread,
      captainText: text,
      startedAt: Date.now(),
    });
    try {
      const history = (flatPosts ?? []).slice(-20).map(p => ({
        role: p.author_id === 'captain' ? 'user' : 'agent',
        text: p.body,
      }));
      const res = await fetch(`/api/agent/${targetAgentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      });
      if (!res.ok) throw new Error(`chat ${res.status}`);
      const data = await res.json();
      const responseText = data.response || '(no response)';

      // Dual-write: post Captain message, then agent response. Sequential to
      // preserve created_at ordering.
      await postCaptain();
      await fetch(`/api/wardroom/threads/${activeThread}/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author_id: targetAgentId,
          body: responseText,
        }),
      });
    } catch {
      // Fallback: ensure the user message lands so the proactive cycle can
      // still respond on the next think tick.
      try { await postCaptain(); } catch { /* swallow */ }
    } finally {
      useStore.getState().setWardRoomDmPending(null);
      useStore.getState().selectWardRoomThread(activeThread);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {/* Thread header — compact, fixed */}
      <div style={{ padding: '12px', borderBottom: '1px solid rgba(255,255,255,0.06)', flexShrink: 0 }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#e0dcd4' }}>
          {thread.title}
        </div>
        <div style={{ fontSize: 12, color: '#8888a0', marginTop: 4 }}>
          by {thread.author_callsign || 'unknown'} · {timeAgo(thread.created_at)}
        </div>
      </div>

      {/* Scrollable content — thread body + posts */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px' }}>
        {thread.body && (
          <div style={{ fontSize: 13, color: '#e0dcd4', padding: '12px 0', fontFamily: "'Inter', sans-serif", lineHeight: 1.5, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <Markdown>{thread.body}</Markdown>
            <div style={{ marginTop: 8 }}>
              <EndorsementButtons targetId={thread.id} targetType="thread" netScore={thread.net_score} />
            </div>
          </div>
        )}
        {!thread.body && (
          <div style={{ padding: '8px 0' }}>
            <EndorsementButtons targetId={thread.id} targetType="thread" netScore={thread.net_score} />
          </div>
        )}
        {posts.length === 0 && !isThinking && (
          <div style={{ padding: 16, color: '#666680', fontSize: 12, textAlign: 'center' as const }}>
            No replies yet
          </div>
        )}
        {isThinking && (
          <div
            data-testid="dm-thinking-indicator"
            style={{ padding: '12px 8px', color: '#8888a0', fontSize: 12, fontStyle: 'italic' }}
          >
            agent is thinking…
          </div>
        )}
        {isDm && flatPosts
          ? flatPosts.map(post => (
              <WardRoomPostItem key={post.id} post={post} threadId={activeThread} flat allPosts={flatPosts} />
            ))
          : posts.map(post => (
              <WardRoomPostItem key={post.id} post={post} threadId={activeThread} depth={0} />
            ))
        }
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
        <button
          onClick={submitReply}
          disabled={isThinking}
          style={{
            background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
            borderRadius: 4, color: isThinking ? '#666680' : '#f0b060', fontSize: 11,
            cursor: isThinking ? 'not-allowed' : 'pointer', padding: '4px 10px',
            fontFamily: "'JetBrains Mono', monospace", alignSelf: 'flex-end',
            opacity: isThinking ? 0.5 : 1,
          }}
        >Send</button>
      </div>
    </div>
  );
}
