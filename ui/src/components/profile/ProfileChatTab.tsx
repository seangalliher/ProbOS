import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';

interface Props {
  agentId: string;
}

export function ProfileChatTab({ agentId }: Props) {
  const conversation = useStore((s) => s.agentConversations.get(agentId));
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const messages = conversation?.messages ?? [];

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setSending(true);

    // Add user message immediately
    useStore.getState().addAgentMessage(agentId, 'user', text);

    try {
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      useStore.getState().addAgentMessage(agentId, 'agent', data.response || '(no response)');
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, input, sending]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

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

      {/* Input */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '8px 12px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
      }}>
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
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          style={{
            background: sending ? 'rgba(240, 176, 96, 0.1)' : 'rgba(240, 176, 96, 0.2)',
            border: '1px solid rgba(240, 176, 96, 0.3)',
            borderRadius: 6,
            color: '#f0b060',
            fontSize: 12,
            fontFamily: "'JetBrains Mono', monospace",
            padding: '6px 12px',
            cursor: sending ? 'default' : 'pointer',
            opacity: sending || !input.trim() ? 0.5 : 1,
          }}
        >
          {sending ? '...' : 'Send'}
        </button>
      </div>
    </div>
  );
}
