/* Intent Surface — Conversation Anchor: "The Process Is Everything" */

import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { useStore } from '../store/useStore';
import type { SelfModProposal } from '../store/types';
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
  const [vibeMode, setVibeMode] = useState<Record<string, boolean>>({});
  const [vibeInput, setVibeInput] = useState<Record<string, string>>({});
  const [enrichedSpec, setEnrichedSpec] = useState<Record<string, string | null>>({});
  const [enriching, setEnriching] = useState<Record<string, boolean>>({});
  const inputRef = useRef<HTMLInputElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const chatHistory = useStore((s) => s.chatHistory);
  const activeDag = useStore((s) => s.activeDag);
  const addChatMessage = useStore((s) => s.addChatMessage);
  const processing = useStore((s) => s.processing);
  const pendingRequests = useStore((s) => s.pendingRequests);
  const incPendingRequests = useStore((s) => s.incPendingRequests);
  const decPendingRequests = useStore((s) => s.decPendingRequests);
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

  /* ── submit (non-blocking) ── */
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;

    addChatMessage('user', text);
    setInput('');
    incPendingRequests();

    // Fire-and-forget — user can keep typing immediately
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
      .then((res) => res.json())
      .then((data) => {
        const response = data.response
          || data.reflection
          || (data.results && Object.keys(data.results).length > 0
              ? Object.values(data.results as Record<string, { output?: string }>)
                  .map((r) => r.output).filter(Boolean).join('\n') || 'Done.'
              : '')
          || (data.correction ? `Correction applied: ${data.correction.changes || 'OK'}` : '')
          || '(No response)';

        if (data.self_mod_proposal) {
          addChatMessage('system', response, {
            selfModProposal: data.self_mod_proposal as SelfModProposal,
          });
        } else {
          addChatMessage('system', response);
        }
        if (voiceEnabled && response && !response.startsWith('(')) {
          // Strip markdown formatting for cleaner TTS
          const cleanText = response
            .replace(/\*\*(.+?)\*\*/g, '$1')
            .replace(/\*(.+?)\*/g, '$1')
            .replace(/#{1,6}\s/g, '')
            .replace(/[-•]\s/g, '')
            .replace(/---+/g, '')
            .replace(/`(.+?)`/g, '$1')
            .replace(/\[(.+?)\]\(.+?\)/g, '$1')
            .replace(/\n{2,}/g, '. ')
            .trim();
          speakResponse(cleanText);
        }
        soundEngine.playIntentRouting();
      })
      .catch(() => {
        addChatMessage('system', '(Request failed or timed out)');
      })
      .finally(() => {
        decPendingRequests();
      });
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

  /* ── approve self-mod proposal ── */
  const approveSelfMod = useCallback(async (proposal: SelfModProposal) => {
    addChatMessage('system', 'Starting agent design...');

    try {
      await fetch('/api/selfmod/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intent_name: proposal.intent_name,
          intent_description: proposal.intent_description,
          parameters: proposal.parameters || {},
          original_message: proposal.original_message || '',
        }),
      });
      // Progress and results come via WebSocket events
    } catch {
      addChatMessage('system', '(Self-mod request failed)');
    }
  }, [addChatMessage]);

  /* ── skip self-mod proposal ── */
  const skipSelfMod = useCallback(() => {
    addChatMessage('system', 'Skipped \u2014 no agent created.');
  }, [addChatMessage]);

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
          bottom: 44,
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
                  maxHeight: 'calc(100vh - 200px)',
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
                      whiteSpace: msg.role === 'user' ? 'pre-wrap' : undefined,
                      wordBreak: 'break-word',
                    }}>
                      {msg.role === 'user' ? msg.text : (
                        <ReactMarkdown
                          components={{
                            p: ({children}) => <p style={{ margin: '4px 0' }}>{children}</p>,
                            strong: ({children}) => <strong style={{ color: '#f0d0a0' }}>{children}</strong>,
                            h2: ({children}) => <h2 style={{ fontSize: 14, margin: '8px 0 4px', color: '#f0d0a0' }}>{children}</h2>,
                            h3: ({children}) => <h3 style={{ fontSize: 13, margin: '6px 0 3px', color: '#f0d0a0' }}>{children}</h3>,
                            ul: ({children}) => <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul>,
                            ol: ({children}) => <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol>,
                            li: ({children}) => <li style={{ margin: '2px 0' }}>{children}</li>,
                            code: ({children}) => <code style={{ background: 'rgba(240, 176, 96, 0.1)', padding: '1px 4px', borderRadius: 3, fontSize: 12 }}>{children}</code>,
                            hr: () => <hr style={{ border: 'none', borderTop: '1px solid rgba(136, 164, 200, 0.15)', margin: '8px 0' }} />,
                            a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#88a4c8' }}>{children}</a>,
                          }}
                        >
                          {msg.text}
                        </ReactMarkdown>
                      )}
                    </div>

                    {/* Self-mod approval buttons */}
                    {msg.selfModProposal && msg.selfModProposal.status === 'proposed' && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => approveSelfMod(msg.selfModProposal!)}
                            style={{
                              background: 'rgba(80, 200, 120, 0.2)',
                              border: '1px solid rgba(80, 200, 120, 0.4)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#80c878', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(80, 200, 120, 0.35)'; }}
                            onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'rgba(80, 200, 120, 0.2)'; }}
                          >
                            {'\u2728'} Build Agent
                          </button>
                          <button
                            onClick={() => setVibeMode(prev => ({ ...prev, [msg.id]: true }))}
                            style={{
                              background: 'rgba(200, 160, 80, 0.15)',
                              border: '1px solid rgba(200, 160, 80, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#e8b860', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(200, 160, 80, 0.3)'; }}
                            onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'rgba(200, 160, 80, 0.15)'; }}
                          >
                            {'\uD83C\uDFA8'} Design Agent
                          </button>
                          <button
                            onClick={skipSelfMod}
                            style={{
                              background: 'rgba(128, 128, 160, 0.1)',
                              border: '1px solid rgba(128, 128, 160, 0.2)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#8888a0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(128, 128, 160, 0.2)'; }}
                            onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'rgba(128, 128, 160, 0.1)'; }}
                          >
                            {'\u274C'} Skip
                          </button>
                        </div>

                        {/* Vibe mode: description input */}
                        {vibeMode[msg.id] && !enrichedSpec[msg.id] && (
                          <div style={{ marginTop: 12, width: '100%' }}>
                            <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>
                              Describe how this agent should work:
                            </div>
                            <textarea
                              value={vibeInput[msg.id] || ''}
                              onChange={(e) => setVibeInput(prev => ({ ...prev, [msg.id]: e.target.value }))}
                              placeholder="e.g., Search DuckDuckGo for the person's name, parse the top results, find LinkedIn profile links..."
                              style={{
                                width: '100%', minHeight: 60, padding: 8,
                                background: 'rgba(10, 10, 18, 0.6)',
                                border: '1px solid rgba(240, 176, 96, 0.2)',
                                borderRadius: 8, color: '#c8d0e0', fontSize: 13,
                                fontFamily: "'Inter', sans-serif", resize: 'vertical',
                              }}
                            />
                            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                              <button
                                onClick={async () => {
                                  setEnriching(prev => ({ ...prev, [msg.id]: true }));
                                  try {
                                    const res = await fetch('/api/selfmod/enrich', {
                                      method: 'POST',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({
                                        intent_name: msg.selfModProposal!.intent_name,
                                        intent_description: msg.selfModProposal!.intent_description,
                                        parameters: msg.selfModProposal!.parameters,
                                        user_guidance: vibeInput[msg.id] || '',
                                      }),
                                    });
                                    const data = await res.json();
                                    setEnrichedSpec(prev => ({ ...prev, [msg.id]: data.enriched }));
                                  } catch {
                                    setEnrichedSpec(prev => ({ ...prev, [msg.id]: vibeInput[msg.id] || '' }));
                                  } finally {
                                    setEnriching(prev => ({ ...prev, [msg.id]: false }));
                                  }
                                }}
                                disabled={!(vibeInput[msg.id] || '').trim() || enriching[msg.id]}
                                style={{
                                  background: 'rgba(80, 200, 120, 0.2)',
                                  border: '1px solid rgba(80, 200, 120, 0.4)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#80c878', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                  opacity: (!(vibeInput[msg.id] || '').trim() || enriching[msg.id]) ? 0.5 : 1,
                                }}
                              >
                                {enriching[msg.id] ? '\uD83D\uDD04 Enriching...' : '\u2728 Enrich Spec'}
                              </button>
                              <button
                                onClick={() => {
                                  setVibeMode(prev => ({ ...prev, [msg.id]: false }));
                                  setVibeInput(prev => ({ ...prev, [msg.id]: '' }));
                                }}
                                style={{
                                  background: 'rgba(128, 128, 160, 0.1)',
                                  border: '1px solid rgba(128, 128, 160, 0.2)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#8888a0', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Enriched spec display */}
                        {enrichedSpec[msg.id] && (
                          <div style={{ marginTop: 12, width: '100%' }}>
                            <div style={{ fontSize: 12, color: '#f0b060', marginBottom: 6 }}>
                              {'\uD83D\uDCCB'} Enriched Agent Spec:
                            </div>
                            <div style={{
                              padding: 12, borderRadius: 8,
                              background: 'rgba(240, 176, 96, 0.06)',
                              border: '1px solid rgba(240, 176, 96, 0.15)',
                              fontSize: 13, lineHeight: 1.6, color: '#c8d0e0',
                              whiteSpace: 'pre-wrap',
                            }}>
                              {enrichedSpec[msg.id]}
                            </div>
                            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                              <button
                                onClick={() => {
                                  approveSelfMod({
                                    ...msg.selfModProposal!,
                                    intent_description: enrichedSpec[msg.id]!,
                                  });
                                  setVibeMode(prev => ({ ...prev, [msg.id]: false }));
                                  setEnrichedSpec(prev => ({ ...prev, [msg.id]: null }));
                                  setVibeInput(prev => ({ ...prev, [msg.id]: '' }));
                                }}
                                style={{
                                  background: 'rgba(80, 200, 120, 0.2)',
                                  border: '1px solid rgba(80, 200, 120, 0.4)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#80c878', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                                onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'rgba(80, 200, 120, 0.35)'; }}
                                onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'rgba(80, 200, 120, 0.2)'; }}
                              >
                                {'\uD83D\uDE80'} Build This Agent
                              </button>
                              <button
                                onClick={() => setEnrichedSpec(prev => ({ ...prev, [msg.id]: null }))}
                                style={{
                                  background: 'rgba(128, 128, 160, 0.1)',
                                  border: '1px solid rgba(128, 128, 160, 0.2)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#8888a0', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                              >
                                {'\u270F\uFE0F'} Edit
                              </button>
                              <button
                                onClick={() => {
                                  setVibeMode(prev => ({ ...prev, [msg.id]: false }));
                                  setEnrichedSpec(prev => ({ ...prev, [msg.id]: null }));
                                  setVibeInput(prev => ({ ...prev, [msg.id]: '' }));
                                }}
                                style={{
                                  background: 'rgba(128, 128, 160, 0.1)',
                                  border: '1px solid rgba(128, 128, 160, 0.2)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#8888a0', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

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

            {/* ── Pending requests indicator ── */}
            {pendingRequests > 0 && (
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
                    <span style={{
                      fontSize: 12, fontFamily: 'monospace', color: '#f0b060',
                      marginLeft: 4,
                    }}>
                      {pendingRequests} pending
                    </span>
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
                    localStorage.removeItem('hxi_chat_history');
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
              animation: pendingRequests === 0 ? 'pulse-pill 1.2s ease-in-out infinite' : undefined,
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
