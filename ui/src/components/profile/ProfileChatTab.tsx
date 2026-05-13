import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
import type { ChatAttachment } from '../../store/types';
import { ModulationIndicator } from './ModulationIndicator';

interface Props {
  agentId: string;
}

const ALLOWED_ATTACHMENT_MIMES = [
  'image/png', 'image/jpeg', 'image/webp', 'image/gif',
  'application/pdf', 'text/plain', 'text/markdown',
  'application/json', 'text/csv',
] as const;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

export function ProfileChatTab({ agentId }: Props) {
  const conversation = useStore((s) => s.agentConversations.get(agentId));
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const globalVoiceEnabled = useStore((s) => s.voiceEnabled);
  // Per-agent TTS toggle: defaults to global setting; persisted in localStorage.
  const ttsKey = `hxi_chat_tts_${agentId}`;
  const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
    const stored = localStorage.getItem(ttsKey);
    return stored === null ? globalVoiceEnabled : stored === '1';
  });
  useEffect(() => {
    localStorage.setItem(ttsKey, ttsEnabled ? '1' : '0');
  }, [ttsEnabled, ttsKey]);
  const [voiceProfile, setVoiceProfile] = useState<VoiceProfile | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [seedMemories, setSeedMemories] = useState<{role: string; text: string}[]>([]);

  const messages = conversation?.messages ?? [];

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // AD-430b: Fetch cross-session memories on mount
  useEffect(() => {
    fetch(`/api/agent/${agentId}/chat/history`)
        .then(r => r.json())
        .then(data => setSeedMemories(data.memories || []))
        .catch(() => {});  // Non-critical
  }, [agentId]);

  // AD-718: Fetch per-agent voice profile (Tier-2 log-and-degrade on failure).
  // Refetches when ProfileInfoTab dispatches `voice-profile-updated` for this agent.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(`/api/agent/${agentId}/profile`)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (!cancelled && data?.voiceProfile) setVoiceProfile(data.voiceProfile); })
        .catch(() => {});
    };
    load();
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as { agentId?: string } | undefined;
      if (!detail || detail.agentId === agentId) load();
    };
    window.addEventListener('voice-profile-updated', handler);
    return () => {
      cancelled = true;
      window.removeEventListener('voice-profile-updated', handler);
    };
  }, [agentId]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if ((!text && pendingAttachments.length === 0) || sending) return;
    setInput('');
    setSending(true);

    // AD-430b: Capture conversation history BEFORE adding current message
    const conv = useStore.getState().agentConversations.get(agentId);
    const history = (conv?.messages || [])
        .slice(-20)  // Last 20 messages (10 exchanges)
        .map(m => ({
            role: m.role === 'user' ? 'user' : 'agent',
            text: m.text,
        }));

    // Prepend seed memories on first message (no prior conversation)
    const fullHistory = conv?.messages?.length ? history : [...seedMemories, ...history];

    // Compose display text including attachment filenames (so the user sees
    // their own message with the attachments listed).
    const attachmentSummary = pendingAttachments.length
      ? '\n\n' + pendingAttachments.map(a => `[attached: ${a.filename || a.attachment_id}]`).join('\n')
      : '';
    const displayText = (text || '(attachment)') + attachmentSummary;

    // Add user message immediately (after capturing history)
    useStore.getState().addAgentMessage(agentId, 'user', displayText);

    const attachmentIds = pendingAttachments.map(a => a.attachment_id);
    setPendingAttachments([]);

    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text || '(attachment)',
          history: fullHistory,
          attachment_ids: attachmentIds,
        }),
      });
      const data = await res.json();
      const reply = data.response || '(no response)';
      useStore.getState().addAgentMessage(agentId, 'agent', reply);
      // AD-718: TTS playback for agent reply only (skip system error placeholders).
      if (ttsEnabled && reply && !reply.startsWith('(')) {
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);
      }
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, input, sending, seedMemories, ttsEnabled, voiceProfile, pendingAttachments]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Message list */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '8px 12px',
      }}>
        {messages.length === 0 && (
          <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40 }}>
            Send a message to start a conversation.
          </div>
        )}
        {messages.map(msg => (
          <div
            key={msg.id}
            style={{
              marginBottom: 8,
              textAlign: msg.role === 'user' ? 'right' : 'left',
            }}
          >
            <div style={{
              display: 'inline-block',
              maxWidth: '85%',
              padding: '6px 10px',
              borderRadius: 8,
              fontSize: 12,
              lineHeight: 1.5,
              background: msg.role === 'user'
                ? 'rgba(240, 176, 96, 0.15)'
                : 'rgba(255, 255, 255, 0.05)',
              border: msg.role === 'user'
                ? '1px solid rgba(240, 176, 96, 0.2)'
                : '1px solid rgba(255, 255, 255, 0.06)',
              color: '#e0dcd4',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {msg.text}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Attachment chips */}
      {(pendingAttachments.length > 0 || attachError) && (
        <div style={{
          padding: '4px 12px',
          borderTop: '1px solid rgba(255,255,255,0.04)',
          display: 'flex', flexWrap: 'wrap', gap: 4,
          fontSize: 11,
        }}>
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

      {/* Input */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '8px 12px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
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
          }}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M11 4l-5 5a2 2 0 002.8 2.8l5-5a3 3 0 00-4.2-4.2l-5 5a4 4 0 005.7 5.7" />
          </svg>
        </button>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message..."
          disabled={sending}
          style={{
            flex: 1,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 6,
            color: '#e0dcd4',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '6px 10px',
            outline: 'none',
          }}
        />
        {/* Per-agent speaker toggle: independent of the global voice button. */}
        <button
          type="button"
          onClick={() => setTtsEnabled(v => !v)}
          title={ttsEnabled ? 'Mute this agent' : 'Speak this agent\'s replies'}
          aria-label={ttsEnabled ? 'Mute agent voice' : 'Enable agent voice'}
          aria-pressed={ttsEnabled}
          style={{
            background: ttsEnabled ? 'rgba(240, 176, 96, 0.15)' : 'transparent',
            border: 'none',
            color: ttsEnabled ? '#f0b060' : '#8888aa',
            cursor: 'pointer',
            padding: '4px',
            borderRadius: 4,
            flexShrink: 0,
            filter: ttsEnabled
              ? 'drop-shadow(0 0 4px #f0b060)'
              : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M2 6v4l3 3h1V3H5L2 6z" />
            {ttsEnabled ? (
              <>
                <path d="M9 5.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5" />
                <path d="M11 3.5c1.2 1.2 2 2.7 2 4.5s-.8 3.3-2 4.5" />
              </>
            ) : (
              <path d="M14 5l-5 6" />
            )}
          </svg>
        </button>
        {/* AD-718d-1: voice modulation activity indicator (pulses while
            applyEmotionalModulation is shaping a speech utterance). */}
        <ModulationIndicator agentId={agentId} />
        {/* AD-718: Mic button for STT input (parity with IntentSurface). */}
        {isSpeechRecognitionSupported() && (
          <button
            type="button"
            onClick={() => {
              if (listening) {
                stopListening();
                setListening(false);
                return;
              }
              setListening(true);
              startListening(
                (text) => {
                  setInput(text);
                  setListening(false);
                  setTimeout(() => handleSend(), 100);
                },
                () => setListening(false),
                () => setListening(false),
              );
            }}
            title={listening ? 'Stop listening' : 'Voice input'}
            aria-label={listening ? 'Stop listening' : 'Voice input'}
            style={{
              background: listening ? 'rgba(255, 102, 102, 0.15)' : 'transparent',
              border: 'none',
              color: listening ? '#ff6666' : '#8888aa',
              cursor: 'pointer',
              fontSize: 14,
              padding: '4px',
              borderRadius: 4,
              transition: 'color 0.2s, filter 0.2s',
              flexShrink: 0,
              animation: listening ? 'pulse-mic 1s ease-in-out infinite' : undefined,
              filter: listening
                ? 'drop-shadow(0 0 4px #ff6666)'
                : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                 stroke={listening ? '#ff6666' : 'currentColor'}
                 strokeWidth="2" strokeLinecap="round">
              <line x1="8" y1="2" x2="8" y2="9" />
              <path d="M5 7c0 1.7 1.3 3 3 3s3-1.3 3-3" />
              <line x1="8" y1="12" x2="8" y2="14" />
              <line x1="6" y1="14" x2="10" y2="14" />
            </svg>
          </button>
        )}
        <button
          onClick={handleSend}
          disabled={sending || (!input.trim() && pendingAttachments.length === 0)}
          style={{
            background: sending ? 'rgba(240, 176, 96, 0.1)' : 'rgba(240, 176, 96, 0.2)',
            border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 6,
            color: '#f0b060',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '6px 12px',
            cursor: sending ? 'default' : 'pointer',
            opacity: sending || (!input.trim() && pendingAttachments.length === 0) ? 0.5 : 1,
          }}
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
      {/* AD-718: Listening pulse keyframe (mirrors IntentSurface.tsx). */}
      <style>{`
        @keyframes pulse-mic {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
