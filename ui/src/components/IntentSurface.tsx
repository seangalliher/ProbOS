/* Intent Surface — Conversation Anchor: "The Process Is Everything" */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import { speakResponse } from '../audio/voice';
import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';
import { soundEngine } from '../audio/soundEngine';

/* ── spring easing ── */
const spring = 'cubic-bezier(0.34, 1.56, 0.64, 1)';

/* ── style helpers ── */
const glass = (opacity = 0.75) => ({
  background: `rgba(10, 10, 18, ${opacity})`,
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(240, 176, 96, 0.15)',
});

/* ── per-message feedback state ── */
type FeedbackStatus = { disabled: boolean; confirmText: string };

export function IntentSurface() {
  const [input, setInput] = useState('');
  const [active, setActive] = useState(false);
  const [feedbackMap, setFeedbackMap] = useState<Record<string, FeedbackStatus>>({});
  const [listening, setListening] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const chatHistory = useStore((s) => s.chatHistory);
  const activeDag = useStore((s) => s.activeDag);
  const addChatMessage = useStore((s) => s.addChatMessage);
  const processing = useStore((s) => s.processing);
  const setProcessing = useStore((s) => s.setProcessing);
  const pendingChar = useStore((s) => s.pendingChar);
  const consumePendingChar = useStore((s) => s.consumePendingChar);
  const voiceEnabled = useStore((s) => s.voiceEnabled);

  /* ── consume pending char from global keydown ── */
  useEffect(() => {
    if (pendingChar && !active) {
      const char = consumePendingChar();
      setActive(true);
      setInput(char);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [pendingChar, active, consumePendingChar]);

  /* ── auto-scroll thread to bottom ── */
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [chatHistory]);

  /* ── scroll to bottom when conversation opens ── */
  useEffect(() => {
    if (active && threadRef.current) {
      setTimeout(() => {
        if (threadRef.current) {
          threadRef.current.scrollTop = threadRef.current.scrollHeight;
        }
      }, 100); // slight delay for expand animation to complete
    }
  }, [active]);

  /* ── click outside to collapse ── */
  useEffect(() => {
    if (!active) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setActive(false);
        setInput('');
      }
    }
    // Delay to avoid catching the click that opened
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 100);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [active]);

  /* ── DAG progress text ── */
  const dagProgress = activeDag && activeDag.length > 0
    ? (() => {
        const done = activeDag.filter((n) => n.status === 'completed').length;
        return `\u26A1 ${done}/${activeDag.length} tasks`;
      })()
    : null;

  /* ── message count for badge ── */
  const msgCount = chatHistory.length;

  /* ── pill click ── */
  function handlePillClick() {
    if (active) return;
    setActive(true);
    setTimeout(() => inputRef.current?.focus(), 50);
  }

  /* ── submit ── */
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || processing) return;

    addChatMessage('user', text);
    setInput('');
    // Keep active — pill stays open, input stays focused
    setProcessing(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      const response = data.response
        || data.reflection
        || (data.results && Object.keys(data.results).length > 0
            ? Object.values(data.results as Record<string, { output?: string }>)
                .map((r) => r.output).filter(Boolean).join('\n') || 'Done.'
            : '')
        || (data.correction ? `Correction applied: ${data.correction.changes || 'OK'}` : '')
        || '(No response)';

      addChatMessage('system', response);
      // Voice output if enabled
      if (voiceEnabled && response && !response.startsWith('(')) {
        speakResponse(response);
      }
      // Intent routing chime
      soundEngine.playIntentRouting();
    } catch {
      addChatMessage('system', '(Connection error)');
    } finally {
      setProcessing(false);
      // Re-focus input after response
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }

  /* ── Escape key ── */
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      setActive(false);
      setInput('');
      inputRef.current?.blur();
    }
  }

  /* ── feedback helper with visual confirmation ── */
  async function handleFeedback(msgId: string, kind: 'good' | 'bad' | 'correct', msgText: string) {
    if (feedbackMap[msgId]?.disabled) return;

    // Correct: pre-fill input and return (no API call yet)
    if (kind === 'correct') {
      setInput(`correct: ${msgText.slice(0, 100)}\n`);
      setFeedbackMap((m) => ({ ...m, [msgId]: { disabled: true, confirmText: '' } }));
      setTimeout(() => inputRef.current?.focus(), 50);
      return;
    }

    const command = kind === 'good' ? '/feedback good' : '/feedback bad';
    const confirmLabel = kind === 'good' ? '\u2713 Learned' : '\u2713 Noted';

    // Trigger canvas pulse
    useStore.setState({ pendingFeedbackPulse: kind });

    // Disable all icons for this message, show confirmation
    setFeedbackMap((m) => ({ ...m, [msgId]: { disabled: true, confirmText: confirmLabel } }));

    // Fade confirmation after 2s
    setTimeout(() => {
      setFeedbackMap((m) => {
        const entry = m[msgId];
        if (!entry) return m;
        return { ...m, [msgId]: { ...entry, confirmText: '' } };
      });
    }, 2000);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: command }),
      });
      await res.json();
      // Confirmation shown inline on button — NOT as a chat message
    } catch {
      // Show error inline on the button
      setFeedbackMap((m) => ({ ...m, [msgId]: { disabled: true, confirmText: '\u2717 Failed' } }));
    }
  }

  return (
    <>
      {/* ── Canvas dim overlay when active ── */}
      {active && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 5,
          background: 'rgba(0, 0, 0, 0.15)',
          pointerEvents: 'none',
          transition: 'opacity 0.3s ease',
        }} />
      )}

      {/* ── Main container — bottom-center ── */}
      <div
        ref={containerRef}
        style={{
          position: 'fixed',
          bottom: 48,
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 20,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          width: active ? '55%' : 'auto',
          maxWidth: active ? '80%' : undefined,
          transition: `width 0.3s ${spring}`,
          pointerEvents: 'none',
        }}
      >
        {/* ── Conversation container (thread + input) ── */}
        {active ? (
          <div style={{
            ...glass(0.75),
            borderRadius: 16,
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            pointerEvents: 'auto',
            animation: 'rise-in 0.3s ease-out',
            boxShadow: '0 0 24px rgba(240, 176, 96, 0.08)',
          }}>
            {/* ── Thread ── */}
            {chatHistory.length > 0 && (
              <div
                ref={threadRef}
                style={{
                  maxHeight: '40vh',
                  overflowY: 'auto',
                  padding: '16px 20px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                {chatHistory.slice(-30).map((msg) => (
                  <div key={msg.id} style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  }}>
                    <div style={{
                      maxWidth: '80%',
                      padding: '8px 12px',
                      borderRadius: 10,
                      fontSize: 13,
                      lineHeight: 1.5,
                      fontFamily: "'Inter', sans-serif",
                      background: msg.role === 'user'
                        ? 'rgba(240, 176, 96, 0.12)'
                        : 'rgba(136, 164, 200, 0.1)',
                      color: msg.role === 'user' ? '#f0d0a0' : '#c8d0e0',
                      border: msg.role === 'user'
                        ? '1px solid rgba(240, 176, 96, 0.15)'
                        : '1px solid rgba(136, 164, 200, 0.12)',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}>
                      {msg.text}
                    </div>

                    {/* Inline feedback icons for system messages */}
                    {msg.role === 'system' && (
                      <div style={{
                        display: 'flex', gap: 4, marginTop: 4, marginLeft: 4,
                        alignItems: 'center',
                      }}>
                        {(() => {
                          const fb = feedbackMap[msg.id];
                          const disabled = fb?.disabled ?? false;
                          const buttons = [
                            { icon: '\uD83D\uDC4D', kind: 'good' as const, title: 'Approve' },
                            { icon: '\uD83D\uDC4E', kind: 'bad' as const, title: 'Reject' },
                            { icon: '\u270F\uFE0F', kind: 'correct' as const, title: 'Correct' },
                          ];
                          return (
                            <>
                              {buttons.map(({ icon, kind, title }) => (
                                <button
                                  key={kind}
                                  onClick={() => handleFeedback(msg.id, kind, msg.text)}
                                  title={title}
                                  disabled={disabled}
                                  style={{
                                    background: 'rgba(128, 128, 160, 0.08)',
                                    border: '1px solid rgba(128, 128, 160, 0.12)',
                                    borderRadius: 4, padding: '2px 5px',
                                    cursor: disabled ? 'default' : 'pointer',
                                    fontSize: 11,
                                    opacity: disabled ? 0.25 : 0.5,
                                    transition: 'opacity 0.2s, background 0.2s',
                                    pointerEvents: disabled ? 'none' : 'auto',
                                  }}
                                  onMouseEnter={(e) => {
                                    if (!disabled) {
                                      (e.target as HTMLElement).style.opacity = '1';
                                      (e.target as HTMLElement).style.background = 'rgba(240, 176, 96, 0.15)';
                                    }
                                  }}
                                  onMouseLeave={(e) => {
                                    if (!disabled) {
                                      (e.target as HTMLElement).style.opacity = '0.5';
                                      (e.target as HTMLElement).style.background = 'rgba(128, 128, 160, 0.08)';
                                    }
                                  }}
                                >
                                  {icon}
                                </button>
                              ))}
                              {fb?.confirmText && (
                                <span style={{
                                  fontSize: 10, color: '#80c878', fontFamily: 'monospace',
                                  marginLeft: 4,
                                  animation: 'fade-confirm 2s ease-out forwards',
                                }}>
                                  {fb.confirmText}
                                </span>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* ── Processing indicator ── */}
            {processing && (
              <div style={{
                padding: '4px 20px 8px',
                display: 'flex', gap: 6, alignItems: 'center',
              }}>
                {dagProgress ? (
                  <span style={{
                    fontSize: 12, fontFamily: 'monospace', color: '#f0b060',
                  }}>
                    {dagProgress}
                  </span>
                ) : (
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        style={{
                          width: 5, height: 5, borderRadius: '50%',
                          background: '#f0b060',
                          animation: `pulse-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* ── Input + Reset ── */}
            <form
              onSubmit={handleSubmit}
              style={{
                display: 'flex', alignItems: 'center',
                padding: '8px 16px',
                borderTop: chatHistory.length > 0 ? '1px solid rgba(240, 176, 96, 0.1)' : 'none',
                gap: 8,
              }}
            >
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask ProbOS..."
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: '#e0dcd4',
                  fontSize: 14,
                  fontFamily: "'Inter', sans-serif",
                  padding: '6px 0',
                }}
              />
              {/* Mic button for voice input */}
              {isSpeechRecognitionSupported() && (
                <button
                  type="button"
                  onClick={() => {
                    if (listening) {
                      stopListening();
                      setListening(false);
                    } else {
                      setListening(true);
                      startListening(
                        (text) => {
                          setInput(text);
                          setListening(false);
                          // Auto-submit after recognition
                          setTimeout(() => {
                            const form = inputRef.current?.closest('form');
                            if (form) form.requestSubmit();
                          }, 100);
                        },
                        () => setListening(false),
                        () => setListening(false),
                      );
                    }
                  }}
                  title={listening ? 'Stop listening' : 'Voice input'}
                  style={{
                    background: listening ? 'rgba(200, 56, 72, 0.2)' : 'transparent',
                    border: 'none',
                    color: listening ? '#c84858' : 'rgba(224, 220, 212, 0.3)',
                    cursor: 'pointer',
                    fontSize: 14,
                    padding: '4px',
                    borderRadius: 4,
                    transition: 'color 0.2s',
                    flexShrink: 0,
                    animation: listening ? 'pulse-mic 1s ease-in-out infinite' : undefined,
                  }}
                  onMouseEnter={(e) => { if (!listening) (e.target as HTMLElement).style.color = 'rgba(240, 176, 96, 0.7)'; }}
                  onMouseLeave={(e) => { if (!listening) (e.target as HTMLElement).style.color = 'rgba(224, 220, 212, 0.3)'; }}
                >
                  {'\uD83C\uDFA4'}
                </button>
              )}
              {chatHistory.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    useStore.setState({ chatHistory: [] });
                  }}
                  title="Clear conversation"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'rgba(224, 220, 212, 0.3)',
                    cursor: 'pointer',
                    fontSize: 14,
                    padding: '4px',
                    borderRadius: 4,
                    transition: 'color 0.2s',
                    flexShrink: 0,
                  }}
                  onMouseEnter={(e) => { (e.target as HTMLElement).style.color = 'rgba(200, 56, 72, 0.7)'; }}
                  onMouseLeave={(e) => { (e.target as HTMLElement).style.color = 'rgba(224, 220, 212, 0.3)'; }}
                >
                  🗑
                </button>
              )}
            </form>
          </div>
        ) : (
          /* ── Resting Pill ── */
          <div
            onClick={handlePillClick}
            style={{
              width: 160,
              height: 40,
              ...glass(0.5),
              borderRadius: 24,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 16px',
              cursor: 'pointer',
              pointerEvents: 'auto',
              position: 'relative',
              animation: !processing ? 'pulse-pill 1.2s ease-in-out infinite' : undefined,
              boxShadow: '0 0 8px rgba(240, 176, 96, 0.05)',
              transition: 'box-shadow 0.3s ease',
            }}
          >
            <span style={{
              color: 'rgba(224, 220, 212, 0.5)',
              fontSize: 13,
              fontFamily: "'Inter', sans-serif",
              userSelect: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              whiteSpace: 'nowrap',
            }}>
              <span style={{ fontSize: 14 }}>{'\u2726'}</span>
              Ask ProbOS...
            </span>

            {/* Message count badge */}
            {msgCount > 0 && (
              <span style={{
                position: 'absolute',
                top: -8,
                right: -4,
                fontSize: 10,
                color: 'rgba(224, 220, 212, 0.4)',
                fontFamily: 'monospace',
                minWidth: 16,
                textAlign: 'center',
              }}>
                {msgCount > 99 ? '99+' : msgCount}
              </span>
            )}
          </div>
        )}
      </div>

      {/* ── Keyframe animations (injected once) ── */}
      <style>{`
        @keyframes pulse-pill {
          0%, 100% { opacity: 0.85; }
          50% { opacity: 0.95; }
        }
        @keyframes pulse-dot {
          0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1.2); }
        }
        @keyframes rise-in {
          from { opacity: 0; transform: translateY(30px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fade-confirm {
          0% { opacity: 1; }
          70% { opacity: 1; }
          100% { opacity: 0; }
        }
        @keyframes pulse-mic {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }
      `}</style>
    </>
  );
}
