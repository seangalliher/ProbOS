import { useRef, useState } from 'react';
import Markdown from 'react-markdown';
import { useStore } from '../../store/useStore';
import type { ChatAttachment, WardRoomPost } from '../../store/types';
import { EndorsementButtons } from './WardRoomEndorsement';
import { WardRoomPostItem } from './WardRoomPostItem';
import { timeAgo } from './timeAgo';

// AD-730-1: file-picker attachments for WardRoom DM replies. Mirrors the
// ProfileChatTab pattern (same /api/agent/{id}/chat endpoint).
const ALLOWED_ATTACHMENT_MIMES = [
  'image/png', 'image/jpeg', 'image/webp', 'image/gif',
  'application/pdf', 'text/plain', 'text/markdown',
  'application/json', 'text/csv',
] as const;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

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
  // AD-730-1: pending file-picker attachments for DM replies.
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
        body: JSON.stringify({
          message: text,
          history,
          // AD-730-1: surface picker-selected attachments to the backend.
          attachment_ids: pendingAttachments.map(a => a.attachment_id),
        }),
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
      // AD-730-1: clear picker buffer regardless of outcome so the chip
      // strip resets between sends (matches ProfileChatTab).
      setPendingAttachments([]);
      useStore.getState().setWardRoomDmPending(null);
      useStore.getState().selectWardRoomThread(activeThread);
    }
  };

  // AD-730-1: upload a single file → /api/chat/attachments/multipart.
  async function uploadAttachment(file: File): Promise<void> {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setAttachError(`Too large: ${file.name} (${file.size} bytes)`);
      return;
    }
    try {
      const fd = new FormData();
      fd.append('file', file, file.name);
      const res = await fetch('/api/chat/attachments/multipart', { method: 'POST', body: fd });
      if (!res.ok) {
        let reason = 'unknown';
        try { reason = (await res.json())?.error ?? reason; } catch { /* ignore */ }
        setAttachError(`Upload failed: ${reason}`);
        return;
      }
      const data = await res.json() as ChatAttachment;
      setPendingAttachments(prev => [...prev, { ...data, filename: file.name }]);
      setAttachError(null);
    } catch (err) {
      setAttachError(`Upload error: ${(err as Error).message}`);
    }
  }

  async function onFilePickerChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    for (const file of files) {
      await uploadAttachment(file);
    }
    if (e.target) e.target.value = '';
  }

  function removePendingAttachment(id: string) {
    setPendingAttachments(prev => prev.filter(a => a.attachment_id !== id));
  }

  // AD-730-1-1: paste image from clipboard. Mirrors IntentSurface.handlePaste.
  // AD-720e (Wave 159): also accept audio MIMEs (chip-only render — see AD).
  async function handlePaste(event: React.ClipboardEvent<HTMLTextAreaElement>) {
    if (!isDm || !targetAgentId) return; // only DM threads accept attachments
    const items = Array.from(event.clipboardData?.items ?? []);
    const audioOrImageItem = items.find(
      it => it.type && (it.type.startsWith('image/') || it.type.startsWith('audio/')),
    );
    if (!audioOrImageItem) return; // text paste — let the textarea handle it
    event.preventDefault();
    const blob = audioOrImageItem.getAsFile();
    if (!blob) return;
    // Wrap as File so uploadAttachment's MIME/size guards apply uniformly.
    const ext = (blob.type.split('/')[1] || 'png').replace(/[^a-z0-9]/gi, '');
    const file = new File([blob], `pasted-${Date.now()}.${ext}`, { type: blob.type });
    await uploadAttachment(file);
  }

  // AD-730-1-1: drag/drop file upload. Targets the reply-input container; the
  // ALLOWED_ATTACHMENT_MIMES allow-list inside uploadAttachment + the
  // server-side check at /api/chat/attachments/multipart enforce MIME/size.
  // Per-AD-730-1-2 forward marker: visible drop-zone hover state deferred.
  async function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    if (!isDm || !targetAgentId) return;
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files ?? []);
    for (const file of files) {
      await uploadAttachment(file);
    }
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>) {
    if (!isDm || !targetAgentId) return;
    // Required to allow the drop event to fire.
    event.preventDefault();
  }

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

      {/* AD-730-1: attachment chip strip (DM-only). Renders above the
          textarea when the picker has staged at least one file or after a
          failed upload so the operator sees the error. */}
      {isDm && targetAgentId && (pendingAttachments.length > 0 || attachError) && (
        <div
          data-testid="wardroom-dm-attachment-chips"
          style={{
            padding: '4px 12px',
            borderTop: '1px solid rgba(255,255,255,0.04)',
            display: 'flex', flexWrap: 'wrap', gap: 4,
            fontSize: 11,
          }}
        >
          {pendingAttachments.map(a => (
            <span key={a.attachment_id} style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              background: 'rgba(240,176,96,0.10)',
              border: '1px solid rgba(240,176,96,0.25)',
              borderRadius: 4, padding: '2px 6px',
              color: '#f0b060',
              maxWidth: 200,
            }}>
              <span style={{
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>{a.filename || a.attachment_id.slice(0, 12)}</span>
              <button
                type="button"
                onClick={() => removePendingAttachment(a.attachment_id)}
                aria-label="remove attachment"
                style={{
                  background: 'transparent', border: 'none', cursor: 'pointer',
                  color: '#f0b060', fontSize: 11, padding: 0, lineHeight: 1,
                }}
              >×</button>
            </span>
          ))}
          {attachError && (
            <span style={{ color: '#ff8080' }}>{attachError}</span>
          )}
        </div>
      )}

      {/* Reply input */}
      <div
        style={{
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '8px 12px',
          display: 'flex', gap: 6,
        }}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
      >
        {/* AD-730-1: paperclip + hidden file picker (DM-only). */}
        {isDm && targetAgentId && (
          <>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ALLOWED_ATTACHMENT_MIMES.join(',')}
              onChange={onFilePickerChange}
              style={{
                position: 'absolute', width: 1, height: 1, opacity: 0,
                pointerEvents: 'none', left: -9999,
              }}
              tabIndex={-1}
              aria-hidden="true"
            />
            <button
              type="button"
              data-testid="wardroom-dm-attach-button"
              onClick={() => fileInputRef.current?.click()}
              aria-label="attach file"
              title="Attach a file"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#f0b060',
                cursor: 'pointer',
                padding: '4px',
                borderRadius: 4,
                flexShrink: 0,
                alignSelf: 'flex-end',
              }}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M11 4l-5 5a2 2 0 002.8 2.8l5-5a3 3 0 00-4.2-4.2l-5 5a4 4 0 005.7 5.7" />
              </svg>
            </button>
          </>
        )}
        <textarea
          value={replyText}
          onChange={e => setReplyText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitReply(); } }}
          onPaste={handlePaste}
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
