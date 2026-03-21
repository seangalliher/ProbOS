/* Intent Surface — Conversation Anchor: "The Process Is Everything" */

import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { useStore } from '../store/useStore';
import type { SelfModProposal, BuildProposal, BuildFailureReport, ArchitectProposalView } from '../store/types';
import { speakResponse } from '../audio/voice';
import { startListening, stopListening, isSpeechRecognitionSupported } from '../audio/speechInput';
import { soundEngine } from '../audio/soundEngine';
import { MissionControl } from './MissionControl';
import { ActivityDrawer } from './ActivityDrawer';
import { NotificationDropdown } from './NotificationDropdown';

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
  const [buildCodeExpanded, setBuildCodeExpanded] = useState<Record<string, boolean>>({});
  const [designSpecExpanded, setDesignSpecExpanded] = useState<Record<string, boolean>>({});
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
  const transporterProgress = useStore((s) => s.transporterProgress);
  const buildQueue = useStore((s) => s.buildQueue);
  const missionControlView = useStore((s) => s.missionControlView);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const agentTasks = useStore((s) => s.agentTasks);
  const notifications = useStore((s) => s.notifications);
  const needsAttentionCount = agentTasks?.filter(t => t.requires_action).length ?? 0;
  const unreadCount = notifications?.filter(n => !n.acknowledged).length ?? 0;

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
  }, [chatHistory, pendingRequests]);

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
        return `\u25C8 ${done}/${activeDag.length} tasks`;
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
    useStore.setState({ activeDag: [] }); // Clear stale DAG so neural pulse shows

    // Send last 10 messages as conversation context for reference resolution
    const recentHistory = chatHistory.slice(-10).map(m => ({
      role: m.role,
      text: m.text.slice(0, 300),
    }));

    // Fire-and-forget — user can keep typing immediately
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: recentHistory }),
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

  /* ── approve build proposal ── */
  const approveBuild = useCallback(async (proposal: BuildProposal) => {
    addChatMessage('system', `Executing build: ${proposal.title}...`);
    try {
      await fetch('/api/build/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          build_id: proposal.build_id,
          file_changes: proposal.file_changes,
          title: proposal.title,
          description: proposal.description,
          ad_number: proposal.ad_number,
        }),
      });
    } catch {
      addChatMessage('system', '(Build approval request failed)');
    }
  }, [addChatMessage]);

  /* ── reject build proposal ── */
  const rejectBuild = useCallback(() => {
    addChatMessage('system', 'Build rejected by Captain.');
  }, [addChatMessage]);

  /* ── approve architect proposal → forward to builder ── */
  const approveDesign = useCallback(async (proposal: ArchitectProposalView) => {
    addChatMessage('system', `Forwarding "${proposal.title}" to Builder...`);
    try {
      await fetch('/api/design/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          design_id: proposal.design_id,
        }),
      });
    } catch {
      addChatMessage('system', '(Design approval request failed)');
    }
  }, [addChatMessage]);

  /* ── reject architect proposal ── */
  const rejectDesign = useCallback(() => {
    addChatMessage('system', 'Design proposal rejected by Captain.');
  }, [addChatMessage]);

  return (
    <>
      {/* ── Notification bell toggle (AD-323) ── */}
      <button
        onClick={() => setNotifOpen(prev => !prev)}
        style={{
          position: 'fixed',
          top: 12,
          right: 210,
          zIndex: 25,
          padding: '3px 8px',
          borderRadius: 4,
          border: '1px solid rgba(255, 255, 255, 0.15)',
          background: notifOpen ? 'rgba(240, 176, 96, 0.2)' : 'transparent',
          color: unreadCount > 0 ? '#f0b060' : (notifOpen ? '#f0b060' : '#888'),
          fontSize: 9,
          fontWeight: 600,
          cursor: 'pointer',
          letterSpacing: 1,
          pointerEvents: 'auto',
        }}
      >
        {'NOTIF' + (unreadCount > 0 ? ` (${unreadCount})` : '')}
      </button>

      {/* ── Notification Dropdown (AD-323) ── */}
      <NotificationDropdown open={notifOpen} onClose={() => setNotifOpen(false)} />

      {/* ── Activity Drawer toggle (AD-321) ── */}
      <button
        onClick={() => setDrawerOpen(prev => !prev)}
        style={{
          position: 'fixed',
          top: 12,
          right: 110,
          zIndex: 25,
          padding: '3px 8px',
          borderRadius: 4,
          border: '1px solid rgba(255, 255, 255, 0.15)',
          background: drawerOpen ? 'rgba(240, 176, 96, 0.2)' : 'transparent',
          color: drawerOpen ? '#f0b060' : '#888',
          fontSize: 9,
          fontWeight: 600,
          cursor: 'pointer',
          letterSpacing: 1,
          pointerEvents: 'auto',
        }}
      >
        {'ACTIVITY' + (needsAttentionCount > 0 ? ` (${needsAttentionCount})` : '')}
      </button>

      {/* ── Mission Control toggle (AD-322) ── */}
      <button
        onClick={() => useStore.setState((s) => ({ missionControlView: !s.missionControlView }))}
        style={{
          position: 'fixed',
          top: 12,
          right: 12,
          zIndex: 25,
          padding: '3px 8px',
          borderRadius: 4,
          border: '1px solid rgba(255, 255, 255, 0.15)',
          background: missionControlView ? 'rgba(208, 160, 48, 0.2)' : 'transparent',
          color: missionControlView ? '#d0a030' : '#888',
          fontSize: 9,
          fontWeight: 600,
          cursor: 'pointer',
          letterSpacing: 1,
          pointerEvents: 'auto',
        }}
      >
        {missionControlView ? 'HXI' : 'MISSION CTRL'}
      </button>

      {/* ── Mission Control overlay (AD-322) ── */}
      {missionControlView && <MissionControl />}

      {/* ── Activity Drawer (AD-321) ── */}
      <ActivityDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

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
                              background: 'rgba(102, 255, 136, 0.1)',
                              border: '1px solid rgba(102, 255, 136, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#66ff88', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                              display: 'flex', alignItems: 'center',
                              textShadow: '0 0 8px rgba(102, 255, 136, 0.5)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.1)'; }}
                          >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#66ff88" strokeWidth="2" strokeLinejoin="round" style={{ marginRight: 6, filter: 'drop-shadow(0 0 4px #66ff88) drop-shadow(0 0 8px rgba(102, 255, 136, 0.4))' }}><polygon points="8,1 14,4.5 14,11.5 8,15 2,11.5 2,4.5" /></svg>
                            Build Agent
                          </button>
                          <button
                            onClick={() => setVibeMode(prev => ({ ...prev, [msg.id]: true }))}
                            style={{
                              background: 'rgba(187, 136, 255, 0.1)',
                              border: '1px solid rgba(187, 136, 255, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#bb88ff', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                              display: 'flex', alignItems: 'center',
                              textShadow: '0 0 8px rgba(187, 136, 255, 0.5)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(187, 136, 255, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(187, 136, 255, 0.1)'; }}
                          >
                            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#bb88ff" strokeWidth="2" strokeLinecap="round" style={{ marginRight: 6, filter: 'drop-shadow(0 0 4px #bb88ff) drop-shadow(0 0 8px rgba(187, 136, 255, 0.4))' }}><path d="M4 2c0 4 8 4 8 8s-8 4-8 8" /><path d="M12 2c0 4-8 4-8 8s8 4 8 8" /></svg>
                            Design Agent
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
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.1)'; }}
                          >
                            {'\u2014'} Skip
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
                                  background: 'rgba(102, 255, 136, 0.1)',
                                  border: '1px solid rgba(102, 255, 136, 0.35)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#66ff88', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                  opacity: (!(vibeInput[msg.id] || '').trim() || enriching[msg.id]) ? 0.5 : 1,
                                  textShadow: '0 0 8px rgba(102, 255, 136, 0.5)',
                                }}
                              >
                                {enriching[msg.id] ? '\u25CB Enriching...' : '\u25C7 Enrich Spec'}
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
                            <div style={{ fontSize: 12, color: '#ffcc66', marginBottom: 6, textShadow: '0 0 6px rgba(255, 204, 102, 0.4)' }}>
                              {'\u25CE'} Enriched Agent Spec:
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
                                  background: 'rgba(102, 255, 136, 0.1)',
                                  border: '1px solid rgba(102, 255, 136, 0.35)',
                                  borderRadius: 8, padding: '6px 16px',
                                  color: '#66ff88', cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                  textShadow: '0 0 8px rgba(102, 255, 136, 0.5)',
                                }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.2)'; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.1)'; }}
                              >
                                {'\u2B22'} Build This Agent
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
                                {'\u25C7'} Edit
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

                    {/* Build proposal approval buttons */}
                    {msg.buildProposal && msg.buildProposal.status === 'review' && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        {/* File change summary */}
                        <div style={{
                          padding: '8px 12px',
                          borderRadius: 8,
                          background: 'rgba(176, 160, 80, 0.08)',
                          border: '1px solid rgba(176, 160, 80, 0.2)',
                          fontSize: 12,
                          color: '#c8d0e0',
                          marginBottom: 8,
                        }}>
                          <div style={{ color: '#b0a050', marginBottom: 4, fontWeight: 600 }}>
                            Generated {msg.buildProposal.change_count} file(s):
                          </div>
                          {msg.buildProposal.file_changes.map((fc, i) => (
                            <div key={i} style={{ marginLeft: 8, color: '#a0a8b8' }}>
                              {'\u2022'} {fc.path} ({fc.mode})
                            </div>
                          ))}
                        </div>

                        {/* Collapsible code view */}
                        <button
                          onClick={() => setBuildCodeExpanded(prev => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                          style={{
                            background: 'rgba(128, 128, 160, 0.08)',
                            border: '1px solid rgba(128, 128, 160, 0.15)',
                            borderRadius: 6, padding: '4px 12px',
                            color: '#8888a0', cursor: 'pointer', fontSize: 12,
                            fontFamily: "'Inter', sans-serif",
                            marginBottom: 8,
                          }}
                        >
                          {buildCodeExpanded[msg.id] ? '\u25BC Hide Code' : '\u25B6 View Code'}
                        </button>
                        {buildCodeExpanded[msg.id] && (
                          <pre style={{
                            padding: 12, borderRadius: 8,
                            background: 'rgba(10, 10, 18, 0.8)',
                            border: '1px solid rgba(128, 128, 160, 0.15)',
                            fontSize: 11, lineHeight: 1.4, color: '#a0a8b8',
                            maxHeight: 300, overflowY: 'auto',
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            marginBottom: 8,
                          }}>
                            {msg.buildProposal.llm_output}
                          </pre>
                        )}

                        {/* Action buttons */}
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => approveBuild(msg.buildProposal!)}
                            style={{
                              background: 'rgba(102, 255, 136, 0.1)',
                              border: '1px solid rgba(102, 255, 136, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#66ff88', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                              textShadow: '0 0 8px rgba(102, 255, 136, 0.5)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(102, 255, 136, 0.1)'; }}
                          >
                            {'\u2B22'} Approve Build
                          </button>
                          <button
                            onClick={rejectBuild}
                            style={{
                              background: 'rgba(128, 128, 160, 0.1)',
                              border: '1px solid rgba(128, 128, 160, 0.2)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#8888a0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.1)'; }}
                          >
                            Reject
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Build failure diagnostic card (AD-346) */}
                    {msg.buildFailureReport && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        {/* Failure header */}
                        <div style={{
                          padding: '8px 12px',
                          borderRadius: 8,
                          background: 'rgba(255, 85, 85, 0.08)',
                          border: '1px solid rgba(255, 85, 85, 0.2)',
                          fontSize: 12,
                          color: '#c8d0e0',
                          marginBottom: 8,
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                            <span style={{
                              color: '#ff5555',
                              fontWeight: 600,
                              fontSize: 13,
                            }}>
                              Build Failed
                            </span>
                            <span style={{
                              padding: '1px 6px',
                              borderRadius: 4,
                              background: 'rgba(255, 85, 85, 0.15)',
                              border: '1px solid rgba(255, 85, 85, 0.3)',
                              color: '#ff8888',
                              fontSize: 10,
                              textTransform: 'uppercase',
                              letterSpacing: '0.5px',
                            }}>
                              {msg.buildFailureReport.failure_category.replace('_', ' ')}
                            </span>
                          </div>
                          {msg.buildFailureReport.ad_number > 0 && (
                            <div style={{ color: '#a0a8b8', marginBottom: 2 }}>
                              AD-{msg.buildFailureReport.ad_number}: {msg.buildFailureReport.title}
                            </div>
                          )}
                          <div style={{ color: '#8888a0', fontSize: 11 }}>
                            {msg.buildFailureReport.files_written.length + msg.buildFailureReport.files_modified.length} file(s) changed
                            {msg.buildFailureReport.branch_name && ` | Branch: ${msg.buildFailureReport.branch_name}`}
                            {msg.buildFailureReport.fix_attempts > 0 && ` | ${msg.buildFailureReport.fix_attempts} fix attempt(s)`}
                          </div>
                        </div>

                        {/* Failed tests list */}
                        {msg.buildFailureReport.failed_tests.length > 0 && (
                          <div style={{
                            padding: '6px 12px',
                            borderRadius: 6,
                            background: 'rgba(255, 85, 85, 0.04)',
                            border: '1px solid rgba(255, 85, 85, 0.1)',
                            fontSize: 11,
                            color: '#a0a8b8',
                            marginBottom: 8,
                          }}>
                            <div style={{ color: '#ff8888', marginBottom: 4, fontSize: 11 }}>
                              Failed tests:
                            </div>
                            {msg.buildFailureReport.failed_tests.map((t, i) => (
                              <div key={i} style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: 10 }}>
                                {'\u2022'} {t}
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Collapsible raw error */}
                        {msg.buildFailureReport.raw_error && (
                          <>
                            <button
                              onClick={() => setBuildCodeExpanded(prev => ({ ...prev, [`fail-${msg.id}`]: !prev[`fail-${msg.id}`] }))}
                              style={{
                                background: 'rgba(128, 128, 160, 0.08)',
                                border: '1px solid rgba(128, 128, 160, 0.15)',
                                borderRadius: 6, padding: '4px 12px',
                                color: '#8888a0', cursor: 'pointer', fontSize: 12,
                                fontFamily: "'Inter', sans-serif",
                                marginBottom: 8,
                              }}
                            >
                              {buildCodeExpanded[`fail-${msg.id}`] ? '\u25BC Hide Error Output' : '\u25B6 View Error Output'}
                            </button>
                            {buildCodeExpanded[`fail-${msg.id}`] && (
                              <pre style={{
                                padding: 12, borderRadius: 8,
                                background: 'rgba(10, 10, 18, 0.8)',
                                border: '1px solid rgba(255, 85, 85, 0.15)',
                                fontSize: 11, lineHeight: 1.4, color: '#a0a8b8',
                                maxHeight: 300, overflowY: 'auto',
                                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                marginBottom: 8,
                              }}>
                                {msg.buildFailureReport.raw_error}
                              </pre>
                            )}
                          </>
                        )}

                        {/* Resolution buttons */}
                        {msg.buildFailureReport.resolution_options.length > 0 && (
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            {msg.buildFailureReport.resolution_options.map((opt) => (
                              <button
                                key={opt.id}
                                title={opt.description}
                                onClick={async () => {
                                  try {
                                    await fetch('/api/build/resolve', {
                                      method: 'POST',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({
                                        build_id: msg.buildFailureReport!.build_id,
                                        resolution: opt.id,
                                      }),
                                    });
                                  } catch (e) {
                                    console.error('Resolution failed:', e);
                                  }
                                }}
                                style={{
                                  background: opt.id === 'abort'
                                    ? 'rgba(128, 128, 160, 0.1)'
                                    : opt.id === 'commit_override'
                                    ? 'rgba(255, 200, 50, 0.1)'
                                    : 'rgba(102, 180, 255, 0.1)',
                                  border: `1px solid ${
                                    opt.id === 'abort'
                                      ? 'rgba(128, 128, 160, 0.2)'
                                      : opt.id === 'commit_override'
                                      ? 'rgba(255, 200, 50, 0.3)'
                                      : 'rgba(102, 180, 255, 0.3)'
                                  }`,
                                  borderRadius: 8, padding: '6px 16px',
                                  color: opt.id === 'abort'
                                    ? '#8888a0'
                                    : opt.id === 'commit_override'
                                    ? '#ffc832'
                                    : '#66b4ff',
                                  cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.opacity = '0.8';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.opacity = '1';
                                }}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Architect proposal review */}
                    {msg.architectProposal && msg.architectProposal.status === 'review' && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        {/* Proposal overview card */}
                        <div style={{
                          padding: '10px 14px',
                          borderRadius: 8,
                          background: 'rgba(80, 160, 176, 0.08)',
                          border: '1px solid rgba(80, 160, 176, 0.2)',
                          fontSize: 12,
                          color: '#c8d0e0',
                          marginBottom: 8,
                        }}>
                          <div style={{ color: '#50a0b0', marginBottom: 6, fontWeight: 600, fontSize: 13 }}>
                            {'\u2609'} {msg.architectProposal.title}
                          </div>
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Summary:</strong> {msg.architectProposal.summary}
                          </div>
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Rationale:</strong> {msg.architectProposal.rationale}
                          </div>
                          {msg.architectProposal.roadmap_ref && (
                            <div style={{ marginBottom: 4 }}>
                              <strong style={{ color: '#a0a8b8' }}>Roadmap:</strong> {msg.architectProposal.roadmap_ref}
                            </div>
                          )}
                          <div style={{ marginBottom: 4 }}>
                            <strong style={{ color: '#a0a8b8' }}>Priority:</strong>{' '}
                            <span style={{ color: msg.architectProposal.priority === 'high' ? '#ff8866' : msg.architectProposal.priority === 'low' ? '#88aa88' : '#b0a050' }}>
                              {msg.architectProposal.priority}
                            </span>
                          </div>

                          {/* Build spec file targets */}
                          {msg.architectProposal.build_spec.target_files.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#a0a8b8' }}>Target files:</strong>
                              {msg.architectProposal.build_spec.target_files.map((f, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#80c8a0' }}>
                                  {'\u2022'} {f}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Risks */}
                          {msg.architectProposal.risks.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#cc8866' }}>Risks:</strong>
                              {msg.architectProposal.risks.map((r, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#cc9977' }}>
                                  {'\u26A0'} {r}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Dependencies */}
                          {msg.architectProposal.dependencies.length > 0 && (
                            <div style={{ marginTop: 6 }}>
                              <strong style={{ color: '#a0a8b8' }}>Dependencies:</strong>
                              {msg.architectProposal.dependencies.map((d, i) => (
                                <div key={i} style={{ marginLeft: 8, color: '#8888a0' }}>
                                  {'\u2192'} {d}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Collapsible full spec */}
                        <button
                          onClick={() => setDesignSpecExpanded(prev => ({ ...prev, [msg.id]: !prev[msg.id] }))}
                          style={{
                            background: 'rgba(80, 160, 176, 0.08)',
                            border: '1px solid rgba(80, 160, 176, 0.15)',
                            borderRadius: 6, padding: '4px 12px',
                            color: '#50a0b0', cursor: 'pointer', fontSize: 12,
                            fontFamily: "'Inter', sans-serif",
                            marginBottom: 8,
                          }}
                        >
                          {designSpecExpanded[msg.id] ? '\u25BC Hide Full Spec' : '\u25B6 View Full Spec'}
                        </button>
                        {designSpecExpanded[msg.id] && (
                          <pre style={{
                            padding: 12, borderRadius: 8,
                            background: 'rgba(10, 10, 18, 0.8)',
                            border: '1px solid rgba(80, 160, 176, 0.15)',
                            fontSize: 11, lineHeight: 1.4, color: '#a0a8b8',
                            maxHeight: 300, overflowY: 'auto',
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                            marginBottom: 8,
                          }}>
                            {msg.architectProposal.build_spec.description || msg.architectProposal.llm_output}
                          </pre>
                        )}

                        {/* Action buttons */}
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            onClick={() => approveDesign(msg.architectProposal!)}
                            style={{
                              background: 'rgba(80, 160, 176, 0.1)',
                              border: '1px solid rgba(80, 160, 176, 0.35)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#50d0e0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                              textShadow: '0 0 8px rgba(80, 160, 176, 0.5)',
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(80, 160, 176, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(80, 160, 176, 0.1)'; }}
                          >
                            {'\u2609'} Approve & Build
                          </button>
                          <button
                            onClick={rejectDesign}
                            style={{
                              background: 'rgba(128, 128, 160, 0.1)',
                              border: '1px solid rgba(128, 128, 160, 0.2)',
                              borderRadius: 8, padding: '6px 16px',
                              color: '#8888a0', cursor: 'pointer', fontSize: 13,
                              fontFamily: "'Inter', sans-serif",
                            }}
                            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.2)'; }}
                            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(128, 128, 160, 0.1)'; }}
                          >
                            Reject
                          </button>
                        </div>
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
                          const buttons: { icon: React.ReactNode; kind: 'good' | 'bad' | 'correct'; title: string }[] = [
                            { icon: <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#8888aa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ filter: 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}><polyline points="4,10 8,5 12,10" /></svg>, kind: 'good', title: 'Approve' },
                            { icon: <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#8888aa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ filter: 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}><polyline points="4,6 8,11 12,6" /></svg>, kind: 'bad', title: 'Reject' },
                            { icon: <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#8888aa" strokeWidth="2" strokeLinejoin="round" style={{ filter: 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))' }}><polygon points="8,2 14,8 8,14 2,8" /></svg>, kind: 'correct', title: 'Correct' },
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
                                      e.currentTarget.style.opacity = '1';
                                      e.currentTarget.style.background = 'rgba(102, 255, 255, 0.1)';
                                      const svg = e.currentTarget.querySelector('svg');
                                      if (svg) { svg.setAttribute('stroke', '#66ffff'); svg.style.filter = 'drop-shadow(0 0 4px #66ffff)'; }
                                    }
                                  }}
                                  onMouseLeave={(e) => {
                                    if (!disabled) {
                                      e.currentTarget.style.opacity = '0.5';
                                      e.currentTarget.style.background = 'rgba(128, 128, 160, 0.08)';
                                      const svg = e.currentTarget.querySelector('svg');
                                      if (svg) { svg.setAttribute('stroke', '#8888aa'); svg.style.filter = 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))'; }
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

            {/* ── Transporter progress card (BF-004) ── */}
            {transporterProgress && (
              <div style={{ marginTop: 8, maxWidth: '80%', padding: '0 20px' }}>
                {/* Header: phase badge + progress fraction */}
                <div style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  background: 'rgba(80, 200, 224, 0.08)',
                  border: '1px solid rgba(80, 200, 224, 0.2)',
                  fontSize: 12,
                  color: '#c8d0e0',
                  marginBottom: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{
                      padding: '1px 6px',
                      borderRadius: 4,
                      background: 'rgba(80, 200, 224, 0.15)',
                      border: '1px solid rgba(80, 200, 224, 0.3)',
                      color: '#50c8e0',
                      fontSize: 10,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}>
                      {transporterProgress.phase}
                    </span>
                    <span style={{ color: '#8888a0', fontSize: 11 }}>
                      {transporterProgress.successful} / {transporterProgress.total_chunks} chunks
                    </span>
                  </div>

                  {/* Progress bar */}
                  <div style={{
                    height: 4,
                    borderRadius: 2,
                    background: 'rgba(80, 200, 224, 0.15)',
                    overflow: 'hidden',
                    marginBottom: 8,
                  }}>
                    {transporterProgress.total_chunks > 0 && (
                      <>
                        <div style={{
                          height: '100%',
                          width: `${(transporterProgress.successful / transporterProgress.total_chunks) * 100}%`,
                          background: '#50c8e0',
                          borderRadius: 2,
                          transition: 'width 0.3s ease',
                          float: 'left',
                        }} />
                        {transporterProgress.failed > 0 && (
                          <div style={{
                            height: '100%',
                            width: `${(transporterProgress.failed / transporterProgress.total_chunks) * 100}%`,
                            background: '#ff5555',
                            borderRadius: 2,
                            transition: 'width 0.3s ease',
                            float: 'left',
                          }} />
                        )}
                      </>
                    )}
                  </div>

                  {/* Chunk list */}
                  {transporterProgress.chunks.map((chunk) => (
                    <div key={chunk.chunk_id} style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      marginBottom: 3,
                    }}>
                      <span style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        flexShrink: 0,
                        background: chunk.status === 'done' ? '#50c878'
                          : chunk.status === 'failed' ? '#ff5555'
                          : chunk.status === 'executing' ? '#ffaa44'
                          : '#555566',
                        ...(chunk.status === 'executing' ? {
                          animation: 'neural-pulse 1.4s ease-in-out infinite',
                        } : {}),
                      }} />
                      <span style={{ fontSize: 11, color: '#c8d0e0' }}>
                        {chunk.description}
                      </span>
                      <span style={{
                        fontSize: 10,
                        color: '#8888a0',
                        fontFamily: 'monospace',
                        marginLeft: 'auto',
                      }}>
                        {chunk.target_file}
                      </span>
                    </div>
                  ))}

                  {/* Footer stats */}
                  {(transporterProgress.waves_completed > 0 || transporterProgress.failed > 0) && (
                    <div style={{
                      display: 'flex',
                      gap: 12,
                      marginTop: 6,
                      fontSize: 10,
                      color: '#8888a0',
                    }}>
                      {transporterProgress.waves_completed > 0 && (
                        <span>Waves: {transporterProgress.waves_completed}</span>
                      )}
                      {transporterProgress.failed > 0 && (
                        <span style={{ color: '#ff5555' }}>
                          Failed: {transporterProgress.failed}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ── Build Queue Dashboard (AD-373) ── */}
            {buildQueue && buildQueue.length > 0 && (
              <div style={{ marginTop: 8, maxWidth: '80%', padding: '0 20px' }}>
                <div style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  background: 'rgba(176, 160, 80, 0.08)',
                  border: '1px solid rgba(176, 160, 80, 0.2)',
                  fontSize: 12,
                  color: '#c8d0e0',
                }}>
                  {/* Header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{
                      padding: '1px 6px',
                      borderRadius: 4,
                      background: 'rgba(176, 160, 80, 0.15)',
                      border: '1px solid rgba(176, 160, 80, 0.3)',
                      color: '#b0a050',
                      fontSize: 10,
                      fontWeight: 600,
                      textTransform: 'uppercase' as const,
                      letterSpacing: '0.5px',
                    }}>
                      Build Queue
                    </span>
                    <span style={{ color: '#8888a0', fontSize: 11 }}>
                      {buildQueue.filter(b => !['merged', 'failed'].includes(b.status)).length} active
                    </span>
                  </div>

                  {/* Build items list */}
                  {buildQueue.map((item) => (
                    <div key={item.id} style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      marginBottom: 6,
                      padding: '4px 0',
                      borderBottom: '1px solid rgba(176, 160, 80, 0.1)',
                    }}>
                      {/* Status dot */}
                      <span style={{
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        flexShrink: 0,
                        background: item.status === 'merged' ? '#50c878'
                          : item.status === 'failed' ? '#ff5555'
                          : item.status === 'reviewing' ? '#b0a050'
                          : item.status === 'building' ? '#ffaa44'
                          : item.status === 'dispatched' ? '#6688cc'
                          : '#555566',
                        ...(item.status === 'building' ? {
                          animation: 'neural-pulse 1.4s ease-in-out infinite',
                        } : {}),
                      }} />

                      {/* Title + AD number */}
                      <span style={{ fontSize: 11, color: '#c8d0e0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.title}
                        {item.ad_number > 0 && (
                          <span style={{ color: '#8888a0', marginLeft: 4 }}>AD-{item.ad_number}</span>
                        )}
                      </span>

                      {/* Status badge */}
                      <span style={{
                        padding: '1px 5px',
                        borderRadius: 3,
                        fontSize: 9,
                        fontWeight: 600,
                        textTransform: 'uppercase' as const,
                        letterSpacing: '0.3px',
                        background: item.status === 'reviewing' ? 'rgba(176, 160, 80, 0.2)' : 'rgba(128, 128, 160, 0.15)',
                        color: item.status === 'reviewing' ? '#b0a050'
                          : item.status === 'merged' ? '#50c878'
                          : item.status === 'failed' ? '#ff5555'
                          : '#8888a0',
                        border: item.status === 'reviewing' ? '1px solid rgba(176, 160, 80, 0.3)' : '1px solid rgba(128, 128, 160, 0.2)',
                      }}>
                        {item.status}
                      </span>

                      {/* Approve / Reject buttons for reviewing items */}
                      {item.status === 'reviewing' && (
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: '1px solid rgba(80, 200, 120, 0.3)',
                              background: 'rgba(80, 200, 120, 0.15)',
                              color: '#50c878',
                              fontSize: 10,
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                            onClick={async () => {
                              try {
                                await fetch('/api/build/queue/approve', {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ build_id: item.id }),
                                });
                              } catch { /* ignore */ }
                            }}
                          >
                            Approve
                          </button>
                          <button
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: '1px solid rgba(255, 85, 85, 0.3)',
                              background: 'rgba(255, 85, 85, 0.15)',
                              color: '#ff5555',
                              fontSize: 10,
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                            onClick={async () => {
                              try {
                                await fetch('/api/build/queue/reject', {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ build_id: item.id }),
                                });
                              } catch { /* ignore */ }
                            }}
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </div>
                  ))}

                  {/* File footprint for reviewing items */}
                  {buildQueue.filter(b => b.status === 'reviewing').map((item) => (
                    item.file_footprint.length > 0 && (
                      <div key={`fp-${item.id}`} style={{
                        marginTop: 4,
                        padding: '4px 8px',
                        background: 'rgba(176, 160, 80, 0.05)',
                        borderRadius: 4,
                        fontSize: 10,
                        color: '#8888a0',
                        fontFamily: 'monospace',
                      }}>
                        {item.file_footprint.map((f, i) => (
                          <div key={i}>{f}</div>
                        ))}
                      </div>
                    )
                  ))}
                </div>
              </div>
            )}

            {/* ── Neural pulse processing indicator ── */}
            {pendingRequests > 0 && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '12px 20px',
                color: 'rgba(255, 204, 102, 0.7)',
                fontSize: 12,
                fontFamily: "'Inter', sans-serif",
              }}>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  {[0, 1, 2].map((i) => (
                    <div key={i} style={{
                      width: 6, height: 6,
                      borderRadius: '50%',
                      background: 'linear-gradient(135deg, #ffcc66, #66ccff)',
                      filter: 'drop-shadow(0 0 3px #ffcc66)',
                      animation: `neural-pulse 1.4s ease-in-out ${i * 0.2}s infinite`,
                    }} />
                  ))}
                </div>
                <span style={{
                  color: '#ffcc66',
                  textShadow: '0 0 6px rgba(255, 204, 102, 0.4)',
                  animation: 'neural-pulse 2s ease-in-out infinite',
                  letterSpacing: '0.5px',
                }}>
                  {dagProgress || 'thinking'}
                </span>
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
                    filter: listening ? 'drop-shadow(0 0 4px #ff6666)' : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
                  }}
                  onMouseEnter={(e) => { if (!listening) { e.currentTarget.style.color = '#ffcc66'; e.currentTarget.style.filter = 'drop-shadow(0 0 4px #ffcc66)'; } }}
                  onMouseLeave={(e) => { if (!listening) { e.currentTarget.style.color = '#8888aa'; e.currentTarget.style.filter = 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))'; } }}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={listening ? '#ff6666' : 'currentColor'} strokeWidth="2" strokeLinecap="round">
                    <line x1="8" y1="2" x2="8" y2="9" />
                    <path d="M5 7c0 1.7 1.3 3 3 3s3-1.3 3-3" />
                    <line x1="8" y1="12" x2="8" y2="14" />
                    <line x1="6" y1="14" x2="10" y2="14" />
                  </svg>
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
                    color: '#8888aa',
                    cursor: 'pointer',
                    fontSize: 14,
                    padding: '4px',
                    borderRadius: 4,
                    transition: 'color 0.2s, filter 0.2s',
                    flexShrink: 0,
                    filter: 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = '#ff6666'; e.currentTarget.style.filter = 'drop-shadow(0 0 4px #ff6666) drop-shadow(0 0 8px rgba(255, 102, 102, 0.4))'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = '#8888aa'; e.currentTarget.style.filter = 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))'; }}
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <circle cx="8" cy="8" r="6" opacity="0.5" />
                    <line x1="5" y1="5" x2="11" y2="11" />
                    <line x1="11" y1="5" x2="5" y2="11" />
                  </svg>
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
        @keyframes neural-pulse {
          0%, 100% { opacity: 0.2; transform: scale(0.8); }
          50% { opacity: 1.0; transform: scale(1.2); }
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
