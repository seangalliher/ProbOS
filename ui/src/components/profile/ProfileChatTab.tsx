import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { speakResponse, stripMarkdownForSpeech, type VoiceProfile } from '../../audio/voice';
import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
import { ArtifactCard } from '../artifacts/ArtifactCard';
import { parseArtifactStub } from '../artifacts/artifactApi';
// BF-301 (was AD-826) — voice-health response shape (mirror of /api/voice/health).
interface VoiceHealth {
  primary_stt: 'transformers' | 'whisper' | 'browser';
  engine: 'transformers' | 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
  model?: string; // BF-301: transformers model id when engine === 'transformers'
}
import {
  armConversationMode,
  disarmConversationMode,
  markAgentReplyComplete,
  type ArmOptions,
} from '../../audio/conversationController';
import { onSpeechEvent } from '../../audio/voice';
import {
  armTransformersStt as armWhisperStt,
  disarmTransformersStt as disarmWhisperStt,
  onTransformersTranscript as onWhisperTranscript,
  onTransformersTranscribing as onWhisperTranscribing,
  onTransformersProgress,
  type TransformersProgressEvent,
} from '../../audio/transformersStt';
import { MicIndicator } from './MicIndicator';
import { subscribePcm } from '../../audio/voiceActivity';
import type { ChatAttachment } from '../../store/types';
import { ModulationIndicator } from './ModulationIndicator';
import { GroupChatHeader } from './GroupChatHeader';
import { captureScreenShareFrame } from '../../hooks/useScreenShare';
import { startScreenStream, stopScreenStream } from '../../hooks/useScreenStream';
import { useScreenStore } from '../../store/useScreenStore';

interface Props {
  agentId: string;
  /** AD-792 (Wave 195): when set, this thread_id is used for chat
   * requests instead of the per-agent default in ``threadIdByAgent``.
   * Precedence: ``props.threadId ?? threadIdByAgent.get(agentId)``.
   * If the server response carries a different ``thread_id`` (route
   * mismatch / reassignment), the response is authoritative and
   * ``setThreadForAgent`` is still called to preserve the AD-791a
   * invariant that the store reflects the latest server-confirmed
   * thread. When unset, behavior is unchanged. */
  threadId?: string;
}

type ScreenMode = 'once' | 'live';
type MicMode = 'ptt' | 'conversation';

const ALLOWED_ATTACHMENT_MIMES = [
  'image/png', 'image/jpeg', 'image/webp', 'image/gif',
  'application/pdf', 'text/plain', 'text/markdown',
  'application/json', 'text/csv',
] as const;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

function getScreenModeKey(agentId: string): string {
  return `hxi_chat_screen_mode_${agentId}`;
}

function loadScreenMode(agentId: string): ScreenMode {
  return localStorage.getItem(getScreenModeKey(agentId)) === 'live' ? 'live' : 'once';
}

function getMicModeKey(agentId: string): string {
  return `hxi_chat_mic_mode_${agentId}`;
}

function loadMicMode(agentId: string): MicMode {
  return localStorage.getItem(getMicModeKey(agentId)) === 'conversation'
    ? 'conversation'
    : 'ptt';
}

/** AD-797 (Wave 197): split a message body by lines and replace any
 *  ``[Artifact: name vN - N lines, mime]`` stubs with the inline
 *  ArtifactCard component. If ``threadId`` is undefined (1:1 cold-start
 *  before a thread exists), the stub is rendered as plain text — the
 *  card cannot resolve without the thread context. */
function renderMessageBodyWithArtifacts(
  text: string, threadId: string | undefined,
): React.ReactNode {
  if (!text) return text;
  const lines = text.split('\n');
  return lines.map((line, idx) => {
    const stub = parseArtifactStub(line);
    const isLast = idx === lines.length - 1;
    if (stub && threadId) {
      return (
        <span key={idx} style={{ display: 'block' }}>
          <ArtifactCard
            threadId={threadId}
            name={stub.name}
            version={stub.version}
            lineCount={stub.lineCount}
            mime={stub.mime}
          />
          {!isLast && '\n'}
        </span>
      );
    }
    return (
      <span key={idx}>
        {line}{!isLast && '\n'}
      </span>
    );
  });
}

export function ProfileChatTab({ agentId, threadId }: Props) {
  const conversation = useStore((s) => s.agentConversations.get(agentId));
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  // BF-294b — real-time amplitude meter for MicIndicator (0..1, smoothed
  // via EMA at RAF cadence). Stays at 0 when the voiceActivity loop
  // isn't armed (App.tsx gates it on perception.vad_engagement_enabled),
  // which is the documented graceful-degrade path (#769).
  const [audioIntensity, setAudioIntensity] = useState(0);
  const intensityRef = useRef(0);       // EMA accumulator, written from onFrame
  const rafPendingRef = useRef(false);  // RAF coalescing flag

  // BF-300 — TTS-active gate. ``ttsActiveRef`` is the synchronous source
  // of truth read by the PTT click handler; ``ttsActive`` state drives
  // the MicIndicator 'muted' visual. Both update on 'start'/'end' events
  // fired by ``audio/voice.ts`` for THIS agent (or unscoped events from
  // legacy callers that don't pass agent_id).
  const ttsActiveRef = useRef(false);
  const [ttsActive, setTtsActive] = useState(false);

  // BF-294b — subscribe to voiceActivity PCM tap while listening; compute
  // RMS per frame, smooth via EMA (alpha=0.3, Discord-style), and flush
  // to state at RAF cadence to bound render churn. Unsubscribe and reset
  // when listening stops or the component unmounts.
  useEffect(() => {
    if (!listening) {
      intensityRef.current = 0;
      setAudioIntensity(0);
      return;
    }
    const EMA_ALPHA = 0.3;
    const GAIN = 3.0;
    const flushToState = () => {
      rafPendingRef.current = false;
      setAudioIntensity(intensityRef.current);
    };
    const scheduleFlush = () => {
      if (rafPendingRef.current) return;
      rafPendingRef.current = true;
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(flushToState);
      } else {
        flushToState();
      }
    };
    const unsubscribe = subscribePcm({
      onFrame(frame: Float32Array, _sampleRate: number, _score?: number) {
        let sumSq = 0;
        for (let i = 0; i < frame.length; i++) {
          const x = frame[i];
          sumSq += x * x;
        }
        const rms = frame.length > 0 ? Math.sqrt(sumSq / frame.length) : 0;
        const raw = Math.max(0, Math.min(1, rms * GAIN));
        intensityRef.current = EMA_ALPHA * raw + (1 - EMA_ALPHA) * intensityRef.current;
        scheduleFlush();
      },
    });
    return () => {
      try { unsubscribe(); } catch { /* Tier-2 — non-actionable on teardown */ }
      intensityRef.current = 0;
      rafPendingRef.current = false;
      setAudioIntensity(0);
    };
  }, [listening]);
  // BF-294: ``processing`` is true while whisperStt is running
  // transcribeBuffer (between speech_end and transcript delivery).
  // Browser-SR's onend → onresult is effectively instant, so we only
  // wire this to the whisper path. Falls back to false on error.
  const [processing, setProcessing] = useState(false);
  useEffect(() => {
    const unsub = onWhisperTranscribing((active) => {
      setProcessing(active);
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
      setProcessing(false);
    };
  }, []);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [screenMode, setScreenMode] = useState<ScreenMode>(() => loadScreenMode(agentId));
  const [screenMenuOpen, setScreenMenuOpen] = useState(false);
  const [screenShareInFlight, setScreenShareInFlight] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textInputRef = useRef<HTMLInputElement>(null);
  const screenShareButtonRef = useRef<HTMLButtonElement>(null);
  const screenShareMenuRef = useRef<HTMLDivElement>(null);
  const screenStopOriginRef = useRef<'cleanup' | null>(null);
  const previousScreenActiveRef = useRef(false);
  // AD-760: mic-mode popover (right-click on the mic button).
  const [micMode, setMicMode] = useState<MicMode>(() => loadMicMode(agentId));
  const [micMenuOpen, setMicMenuOpen] = useState(false);
  const micButtonRef = useRef<HTMLButtonElement>(null);
  const micMenuRef = useRef<HTMLDivElement>(null);
  // AD-760: empty-transcript count for the press-to-talk whisper fallback.
  const emptyTranscriptCountRef = useRef(0);
  // AD-826 — separate counter for whisper-empty transcripts so that the
  // whisper→browser fallback in primary=whisper mode is independent of
  // the browser→whisper fallback in primary=browser mode (AD-760).
  const emptyWhisperCountRef = useRef(0);
  // BF-319: ref holding the current click cycle's transcript-listener
  // unsubscribe handle. The listener was previously closed-over inside
  // the click handler with no way for the cancel branch (a second click
  // while listening) to unsubscribe it — leaving a zombie listener in
  // the global _transcriptListeners set. The next click's transcript
  // event would fan out to BOTH zombie + new listener, calling
  // sendText() twice with the same text, double-posting the Captain's
  // message AND triggering a duplicate agent reply. Storing the unsub
  // on a ref lets EVERY exit path (cancel click, agent switch, unmount)
  // tear the listener down cleanly.
  const transcriptUnsubRef = useRef<(() => void) | null>(null);
  // AD-826 — fetch voice-health on mount. The health endpoint is cheap
  // (filesystem stat); we refetch when the agent changes so a swap to
  // a tab with different STT settings honors the new config.
  const [voiceHealth, setVoiceHealth] = useState<VoiceHealth | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/voice/health');
        if (!res.ok) return;
        const data = (await res.json()) as VoiceHealth;
        if (!cancelled) setVoiceHealth(data);
      } catch {
        // Tier-2 honest-degrade — without health data, the PTT handler
        // falls through to the AD-760 browser-primary path.
      }
    })();
    return () => { cancelled = true; };
  }, [agentId]);
  // BF-301 (#775): first-load model download progress. Cleared once
  // status === 'ready' or 'done'. Drives the inline mic-affordance
  // progress bar (data-testid="bf301-progress").
  const [transformersProgress, setTransformersProgress] = useState<TransformersProgressEvent | null>(null);
  useEffect(() => {
    const unsub = onTransformersProgress((event) => {
      if (event.status === 'ready' || event.status === 'done') {
        setTransformersProgress(null);
      } else {
        setTransformersProgress(event);
      }
    });
    return () => { try { unsub(); } catch { /* Tier-2 */ } };
  }, []);
  const globalVoiceEnabled = useStore((s) => s.voiceEnabled);
  const screenActive = useScreenStore((s) => s.active);
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

  useEffect(() => {
    setScreenMode(loadScreenMode(agentId));
    setScreenMenuOpen(false);
  }, [agentId]);

  useEffect(() => {
    localStorage.setItem(getScreenModeKey(agentId), screenMode);
  }, [agentId, screenMode]);

  // AD-760: hydrate mic mode when the active agent switches.
  useEffect(() => {
    setMicMode(loadMicMode(agentId));
    setMicMenuOpen(false);
    emptyTranscriptCountRef.current = 0;
  }, [agentId]);

  // AD-760: arm / disarm the natural-conversation controller for the
  // active agent. Single-armed-controller invariant: switching agents
  // disarms the previous controller before arming the next. The arm
  // decision reads ``loadMicMode(agentId)`` directly to avoid stale
  // state during agent-switch renders (the React-state ``micMode``
  // trails ``agentId`` by one commit). ``micMode`` stays in deps so
  // popover-driven changes still re-trigger arming.
  useEffect(() => {
    const mode = loadMicMode(agentId);
    if (mode !== 'conversation' || !globalVoiceEnabled) {
      disarmConversationMode();
      return;
    }
    const armOpts: ArmOptions = {
      agentId,
      historyProvider: () => {
        const conv = useStore.getState().agentConversations.get(agentId);
        const msgs = conv?.messages ?? [];
        return msgs.slice(-20).map((m) => ({
          role: m.role === 'user' ? 'user' : 'agent',
          content: m.text,
        }));
      },
      onTranscript: (text: string) => {
        setInput(text);
      },
      // BF-290: wire agent-reply path. Without this the controller posts the
      // user transcript, gets a reply, calls _opts?.onAgentReply?.(replyText)
      // which is undefined, advances to agent_speaking, and waits forever
      // for markAgentReplyComplete() to be called. Stuck state blocks the
      // next mic press because armConversationMode returns early when armed.
      onAgentReply: (replyText: string) => {
        // 1. Append to the per-agent conversation so the operator sees it
        // in the DM thread.
        useStore.getState().addAgentMessage(agentId, 'agent', replyText);
        // 2. Speak it (when TTS is enabled for this agent) and signal
        // controller completion when the TTS 'end' event fires. When TTS
        // is disabled, signal completion immediately so the controller
        // advances to silence_pending and the silence timer can run.
        const currentTtsEnabled = localStorage.getItem(ttsKey) === '1'
          || (localStorage.getItem(ttsKey) === null && useStore.getState().voiceEnabled);
        if (!currentTtsEnabled) {
          markAgentReplyComplete();
          return;
        }
        // Subscribe BEFORE speakResponse so we don't race the 'start' event.
        // We listen for the matching 'end' for this agent_id, then unsubscribe.
        const unsub = onSpeechEvent((event) => {
          if (event.type !== 'end') return;
          if (event.agent_id && event.agent_id !== agentId) return;
          try { unsub(); } catch { /* Tier-2 */ }
          markAgentReplyComplete();
        });
        speakResponse(stripMarkdownForSpeech(replyText), voiceProfile ?? undefined, agentId);
      },
      onStateChange: (state) => {
        console.info(`AD-747/BF-290: conversation state for ${agentId}: ${state}`);
      },
    };
    console.info(`AD-760: mic mode ${mode} armed for agent ${agentId}`);
    armConversationMode(armOpts);
    return () => {
      disarmConversationMode();
    };
  }, [agentId, micMode, globalVoiceEnabled]);

  // BF-300 — persistent TTS-lifecycle subscription. Tracks every speak
  // event for this agent so the PTT click handler can refuse to start a
  // new SR session while TTS is playing (echo-loop guard), and the
  // MicIndicator can show the 'muted' visual.
  //
  // Coexists with the per-reply subscription inside ``armConversationMode``
  // (line ~256): that one fires ``markAgentReplyComplete`` on 'end' to
  // hand back to the controller; this one is purely for PTT gating and
  // does not call into the controller.
  useEffect(() => {
    const unsub = onSpeechEvent((event) => {
      if (event.agent_id && event.agent_id !== agentId) return;
      if (event.type === 'start') {
        ttsActiveRef.current = true;
        setTtsActive(true);
      } else if (event.type === 'end') {
        ttsActiveRef.current = false;
        setTtsActive(false);
      }
    });
    return () => {
      try { unsub(); } catch { /* Tier-2 */ }
    };
  }, [agentId]);

  // AD-760: dismiss the mic popover on outside click or Escape.
  useEffect(() => {
    if (!micMenuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (micMenuRef.current?.contains(target) || micButtonRef.current?.contains(target)) {
        return;
      }
      setMicMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMicMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [micMenuOpen]);

  useEffect(() => {
    if (!screenMenuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (screenShareMenuRef.current?.contains(target) || screenShareButtonRef.current?.contains(target)) {
        return;
      }
      setScreenMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setScreenMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [screenMenuOpen]);

  useEffect(() => {
    let cancelled = false;
    if (screenMode !== 'live') return () => undefined;
    const start = async () => {
      const wasActive = useScreenStore.getState().active;
      if (!wasActive) {
        await startScreenStream({ fps: 1 });
      }
      if (cancelled) return;
      if (useScreenStore.getState().active) {
        console.info(`screen_share.started agent_id=${agentId} mode=live`);
        return;
      }
      localStorage.setItem(getScreenModeKey(agentId), 'once');
      setScreenMode('once');
    };
    void start();
    return () => {
      cancelled = true;
      if (!useScreenStore.getState().active) return;
      screenStopOriginRef.current = 'cleanup';
      void stopScreenStream().finally(() => {
        console.info(`screen_share.stopped agent_id=${agentId} reason=cleanup`);
      });
    };
  }, [agentId, screenMode]);

  useEffect(() => {
    const wasActive = previousScreenActiveRef.current;
    previousScreenActiveRef.current = screenActive;
    if (!wasActive || screenActive) return;
    if (screenStopOriginRef.current === 'cleanup') {
      screenStopOriginRef.current = null;
      return;
    }
    screenStopOriginRef.current = null;
    if (screenMode === 'live') {
      console.info(`screen_share.stopped agent_id=${agentId} reason=browser-ended`);
      localStorage.setItem(getScreenModeKey(agentId), 'once');
      setScreenMode('once');
    }
  }, [agentId, screenActive, screenMode]);

  const messages = conversation?.messages ?? [];

  // AD-917: active thread id for the in-chat group-controls header. Reactive
  // (selector) so the header appears as soon as the server creates/returns a
  // thread. Mirrors the send-path precedence (props.threadId wins over the
  // per-agent default in threadIdByAgent).
  const activeThreadId = useStore((s) => threadId ?? s.threadIdByAgent.get(agentId));

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // BF-293: reset the empty-transcript counter when the agent replies so
  // the whisperStt fallback isn't surprise-triggered by stale empty
  // results from earlier conversational rounds. Counter still resets on
  // agent-switch (line ~106), on a successful browser-SR transcript
  // (line ~831), and when the fallback fires (line ~807); this closes
  // the cross-turn gap.
  useEffect(() => {
    const last = messages[messages.length - 1];
    if (last?.role === 'agent') {
      emptyTranscriptCountRef.current = 0;
    }
  }, [messages.length]);

  // AD-430b: Fetch cross-session memories on mount
  useEffect(() => {
    fetch(`/api/agent/${agentId}/chat/history`)
        .then(r => r.json())
        .then(data => setSeedMemories(data.memories || []))
        .catch(() => {});  // Non-critical
  }, [agentId]);

  // AD-795: Hydrate the input from a pending chat draft (set by the
  // Compact-mode starter chips). Subscribes via a selector so the effect
  // only fires when this agent's draft changes. The store action clears
  // the draft once we've consumed it so navigating away and back doesn't
  // re-populate the field.
  const pendingDraft = useStore((s) => s.chatDrafts[agentId] ?? '');
  const consumeChatDraft = useStore((s) => s.consumeChatDraft);
  useEffect(() => {
    if (!pendingDraft) return;
    const text = consumeChatDraft(agentId);
    if (!text) return;
    setInput(text);
    // Defer focus to the next tick so React has applied the value.
    queueMicrotask(() => {
      const el = textInputRef.current;
      if (el) {
        el.focus();
        try { el.setSelectionRange(text.length, text.length); } catch { /* ignore */ }
      }
    });
  }, [agentId, pendingDraft, consumeChatDraft]);

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

  // BF-292: sendText reads message body from the ``textArg`` parameter, NOT
  // from the ``input`` state. PTT paths call ``setInput(text)`` then schedule
  // a setTimeout; at scheduling time React has not re-rendered, so any
  // callback that reads ``input`` from closure would see ``''`` and bail at
  // the guard below. By taking the text as an argument we capture the
  // transcript at call-time and bypass the stale-closure race.
  // ``input`` is intentionally NOT in the deps array — it is not read here.
  const sendText = useCallback(async (textArg: string) => {
    const text = textArg.trim();
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

    // AD-917: route Captain sends to the group fan-out path once the active
    // thread has >=2 crew participants. AD-914 fan-out fires ONLY on
    // POST /api/threads/{id}/messages with role=="captain"; the 1:1
    // /api/agent/{id}/chat path below stays byte-identical for solo threads.
    const groupThreadId = threadId ?? useStore.getState().threadIdByAgent.get(agentId);
    if (groupThreadId) {
      const _thread = useStore.getState().chatThreads.get(groupThreadId);
      const _agents = useStore.getState().agents;
      const crewParticipantCount = (_thread?.participants ?? []).filter(
        (id) => id !== 'captain' && _agents.get(id)?.isCrew,
      ).length;
      if (_thread && crewParticipantCount >= 2) {
        try {
          // ``body`` has min_length=1 on AppendMessageRequest, so attach-only
          // sends MUST carry the '(attachment)' placeholder or the POST 422s.
          const res = await fetch(`/api/threads/${groupThreadId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              author_id: 'captain',
              role: 'captain',
              body: text || '(attachment)',
              attachment_ids: attachmentIds,
            }),
          });
          const data = await res.json();
          // AD-914 returns {**msg.to_dict(), per_agent_replies: [{agent_id,
          // callsign, text}]}. Render each reply as an agent message; v1
          // attribution is a callsign prefix on the shared conversation.
          const replies = Array.isArray(data?.per_agent_replies) ? data.per_agent_replies : [];
          for (const r of replies) {
            const replyText = typeof r?.text === 'string' ? r.text : '';
            if (!replyText) continue;
            const prefix = typeof r?.callsign === 'string' && r.callsign ? `${r.callsign}: ` : '';
            useStore.getState().addAgentMessage(agentId, 'agent', `${prefix}${replyText}`);
          }
        } catch {
          useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
        } finally {
          setSending(false);
        }
        return;
      }
    }

    try {
      // AD-791a: round-trip the chat-thread ID so subsequent turns route
      // to the same thread on the server. ``threadIdByAgent`` is empty on
      // first turn; the server creates the implicit default and returns
      // ``thread_id`` on the response, which we cache back into the map.
      // AD-792 (Wave 195): explicit ``threadId`` prop wins over the
      // per-agent default in ``threadIdByAgent``. When the prop is
      // unset, behavior is unchanged from AD-791a.
      const knownThreadId = threadId ?? useStore.getState().threadIdByAgent.get(agentId);
      const requestBody: Record<string, unknown> = {
        message: text || '(attachment)',
        history: fullHistory,
        attachment_ids: attachmentIds,
      };
      if (knownThreadId) requestBody.thread_id = knownThreadId;
      const res = await fetch(`/api/agent/${agentId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      const data = await res.json();
      // AD-791a: capture the server-assigned thread_id (whether it's the
      // implicit default created on first turn or the same one echoed
      // back on subsequent turns). Tolerate missing field so older
      // backends keep working.
      if (typeof data?.thread_id === 'string' && data.thread_id.length > 0) {
        useStore.getState().setThreadForAgent(agentId, data.thread_id);
        // AD-794: when the response carries an updated thread title
        // (first-turn auto-name fired) or any other thread fields,
        // hydrate the local chatThreads map so the future sidebar
        // (AD-792) sees the rename without a full reload.
        const _threadView = useStore.getState().chatThreads.get(data.thread_id);
        if (typeof data?.title === 'string' && data.title.length > 0) {
          const _next = _threadView
            ? { ..._threadView, title: data.title, last_active_at: Date.now() / 1000 }
            : {
                id: data.thread_id,
                title: data.title,
                participants: [agentId],
                created_at: Date.now() / 1000,
                last_active_at: Date.now() / 1000,
              };
          useStore.getState().setChatThread(_next);
        }
      }
      // AD-809: the /personality slash command returns {system: true,
      // response: "Personality set to ..."}. Render as a system note
      // rather than an agent reply, and skip TTS.
      if (data?.system === true) {
        const _sysReply = data.response || '(personality command)';
        useStore.getState().addAgentMessage(agentId, 'system', _sysReply);
        return;
      }
      const reply = data.response || '(no response)';
      useStore.getState().addAgentMessage(agentId, 'agent', reply);
      // AD-718: TTS playback for agent reply only (skip system error placeholders).
      if (ttsEnabled && reply && !reply.startsWith('(')) {
        // AD-738e-1: forward parsed emotion (v1 name) so the TTS endpoint
        // applies per-emotion prosody. ``data.emotion`` may be null on
        // older responses or when divergence detection is OFF — pass
        // ``undefined`` so the speakResponse helper omits the field.
        const _emotion = typeof data?.emotion === 'string' && data.emotion.length > 0
          ? data.emotion
          : undefined;
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId, _emotion);
      }
    } catch {
      useStore.getState().addAgentMessage(agentId, 'agent', '(communication error)');
    } finally {
      setSending(false);
    }
  }, [agentId, threadId, sending, seedMemories, ttsEnabled, voiceProfile, pendingAttachments]);

  // BF-292: thin shim for the textarea Enter-key + send-button paths. Reads
  // current ``input`` at call time and forwards to sendText. The Enter-key
  // and form-submit handlers are synchronous reactions to user keystrokes
  // where ``input`` is guaranteed to be current, so closure-staleness is not
  // a concern on this path.
  const handleSend = useCallback(() => {
    void sendText(input);
  }, [input, sendText]);

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

  async function captureScreenOnce(): Promise<void> {
    if (screenShareInFlight) return;
    setScreenShareInFlight(true);
    setAttachError(null);
    try {
      const result = await captureScreenShareFrame({ agentId });
      if (!result) {
        setAttachError('Screen share cancelled or failed.');
        return;
      }
      setPendingAttachments(prev => [...prev, {
        attachment_id: result.attachment_id,
        url: `/api/attachments/${result.attachment_id}`,
        sha256: result.attachment_id,
        mime: result.mime,
        size_bytes: result.size_bytes,
        filename: 'screen-share.jpg',
      }]);
    } finally {
      setScreenShareInFlight(false);
    }
  }

  function selectScreenMode(nextMode: ScreenMode): void {
    setScreenMenuOpen(false);
    setScreenMode(nextMode);
    localStorage.setItem(getScreenModeKey(agentId), nextMode);
    if (nextMode === 'once') {
      void stopScreenStream();
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* AD-917: in-chat group controls (rename / participants / add). Renders
          nothing until a thread exists. Mounted above the message list. */}
      {activeThreadId && <GroupChatHeader threadId={activeThreadId} />}
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
              textAlign: msg.role === 'user' ? 'right' : (msg.role === 'system' ? 'center' : 'left'),
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
                : (msg.role === 'system'
                  ? 'rgba(255, 255, 255, 0.02)'
                  : 'rgba(255, 255, 255, 0.05)'),
              border: msg.role === 'user'
                ? '1px solid rgba(240, 176, 96, 0.2)'
                : (msg.role === 'system'
                  ? '1px dashed rgba(255, 255, 255, 0.12)'
                  : '1px solid rgba(255, 255, 255, 0.06)'),
              color: msg.role === 'system' ? '#9a9a9a' : '#e0dcd4',
              fontStyle: msg.role === 'system' ? 'italic' : 'normal',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}>
              {renderMessageBodyWithArtifacts(msg.text, threadId)}
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
        <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
          <button
            ref={screenShareButtonRef}
            type="button"
            onClick={() => { void captureScreenOnce(); }}
            onContextMenu={(event) => {
              event.preventDefault();
              setScreenMenuOpen((open) => !open);
            }}
            aria-label="share screen"
            aria-pressed={screenMode === 'live' && screenActive}
            title={screenMode === 'live' && screenActive ? 'Screen share live for this agent' : 'Share screen'}
            disabled={screenShareInFlight}
            style={{
              background: screenShareInFlight || (screenMode === 'live' && screenActive)
                ? 'rgba(240, 176, 96, 0.15)'
                : 'transparent',
              border: 'none',
              color: screenShareInFlight || (screenMode === 'live' && screenActive) ? '#f0b060' : '#8888aa',
              cursor: screenShareInFlight ? 'wait' : 'pointer',
              padding: '4px',
              borderRadius: 4,
              flexShrink: 0,
              filter: screenShareInFlight || (screenMode === 'live' && screenActive)
                ? 'drop-shadow(0 0 4px rgba(240,176,96,0.45))'
                : 'drop-shadow(0 0 2px rgba(136, 136, 170, 0.3))',
              animation: screenShareInFlight || (screenMode === 'live' && screenActive)
                ? 'screen-share-pulse 1.6s ease-in-out infinite'
                : undefined,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                 stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="1.5" y="2.5" width="13" height="9" rx="1" />
              <path d="M5 14h6" />
              <path d="M8 11.5v2.5" />
              <path d="M8 8.5V4.5M6 6.5L8 4.5l2 2" />
            </svg>
          </button>
          {screenMenuOpen && (
            <div
              ref={screenShareMenuRef}
              data-testid="profile-chat-screen-share-menu"
              style={{
                position: 'absolute',
                right: 0,
                bottom: 'calc(100% + 6px)',
                minWidth: 160,
                background: 'rgba(10, 10, 18, 0.96)',
                border: '1px solid rgba(240, 176, 96, 0.25)',
                borderRadius: 8,
                boxShadow: '0 10px 24px rgba(0, 0, 0, 0.35)',
                zIndex: 30,
                overflow: 'hidden',
              }}
            >
              <button
                type="button"
                onClick={() => {
                  selectScreenMode('once');
                  void captureScreenOnce();
                }}
                data-testid="profile-chat-screen-share-capture-once"
                style={{
                  width: '100%',
                  display: 'block',
                  textAlign: 'left',
                  background: 'transparent',
                  border: 'none',
                  color: '#e0dcd4',
                  padding: '8px 12px',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                Capture once
              </button>
              <button
                type="button"
                onClick={() => selectScreenMode('live')}
                data-testid="profile-chat-screen-share-live"
                style={{
                  width: '100%',
                  display: 'block',
                  textAlign: 'left',
                  background: 'transparent',
                  border: 'none',
                  color: '#e0dcd4',
                  padding: '8px 12px',
                  cursor: 'pointer',
                  fontSize: 12,
                }}
              >
                Live screen share
              </button>
            </div>
          )}
        </div>
        <input
          ref={textInputRef}
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
        {screenMode === 'live' && screenActive && (
          <span
            data-testid="profile-chat-screen-live-indicator"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: 1.2,
              color: '#f0b060',
              fontFamily: "'JetBrains Mono', monospace",
              padding: '1px 5px',
              border: '1px solid #f0b060',
              borderRadius: 2,
              flexShrink: 0,
            }}
          >
            <svg width="9" height="9" viewBox="0 0 16 16" fill="none"
                 stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="1.5" y="2.5" width="13" height="9" rx="0.5" />
              <path d="M5 14h6" />
              <path d="M8 11.5V14" />
            </svg>
            LIVE
          </span>
        )}
        {/* AD-718 / AD-760: Mic button for STT input (parity with IntentSurface).
            Right-click (or Shift+F10) opens a per-agent mode popover:
            press-to-talk (default) vs conversation mode. */}
        {isSpeechRecognitionSupported() && (
          <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
            <button
              ref={micButtonRef}
              type="button"
              onClick={() => {
                if (micMode === 'conversation') {
                  // In conversation mode, left-click is press-to-talk
                  // preemption (PRIORITY_PRESS_TO_TALK wins per BF-318);
                  // we still drive it through the standard PTT path
                  // below — the ConversationController will see the
                  // preempt and re-arm on release. The mode-switching
                  // logic stays in the popover.
                }
                if (listening) {
                  stopListening();
                  // BF-290: also disarm whisper fallback in case the previous
                  // press armed it but the operator never spoke. stopListening
                  // only stops the browser SpeechRecognition; whisperStt is a
                  // separate subsystem that needs explicit teardown.
                  try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                  // BF-319: tear down the per-click transcript listener so
                  // a straggler transcript event (whisper-medium can take
                  // 3-4s) does not fire a zombie handler. Without this,
                  // a cancel-then-new-PTT sequence registers TWO listeners
                  // that BOTH call sendText on the next transcript →
                  // duplicate Captain message + duplicate agent reply.
                  if (transcriptUnsubRef.current) {
                    try { transcriptUnsubRef.current(); } catch { /* Tier-2 */ }
                    transcriptUnsubRef.current = null;
                  }
                  setListening(false);
                  setProcessing(false); // BF-294: cancel any pending processing visual
                  return;
                }
                // BF-300 — TTS-active gate. Refuse to start a new SR
                // session while the agent's own TTS is playing through
                // the speakers; otherwise the mic captures it and
                // auto-sends it back as a new user message (echo loop,
                // #774). The 'muted' MicIndicator state communicates
                // this state to the operator (HXI #4 motion conveys
                // state). Stop-path above is intentionally NOT gated:
                // the operator must always be able to abort.
                if (ttsActiveRef.current) {
                  console.info(
                    `BF-300: mic press ignored for agent ${agentId} — TTS playback in progress`,
                  );
                  return;
                }
                setListening(true);
                // BF-301 (was AD-826) — branch by primary_stt. Accept
                // both 'transformers' (new default) and 'whisper'
                // (deprecated alias) as the local-first engine.
                const primary = voiceHealth?.primary_stt ?? 'browser';
                const isLocalEngine = primary === 'transformers' || primary === 'whisper';
                const whisperHealthy =
                  voiceHealth?.healthy === true && voiceHealth?.backend_available === true;

                if (isLocalEngine && whisperHealthy) {
                  // AD-826 — whisper-primary path. Mirror of AD-760's
                  // structure with engines swapped: arm whisperStt first;
                  // after 2 empty whisper transcripts, fall through to
                  // browser SR for the next press.
                  if (emptyWhisperCountRef.current >= 2) {
                    emptyWhisperCountRef.current = 0;
                    console.info(
                      `AD-826: browser-SR fallback for agent ${agentId} after 2 empty whisper transcripts`,
                    );
                    let gotResult = false;
                    startListening(
                      (text) => {
                        gotResult = true;
                        setInput(text);
                        setListening(false);
                        // BF-300: terminate the continuous SR session so
                        // the upcoming TTS reply isn't captured as the
                        // next utterance (#774 echo loop).
                        try { stopListening(); } catch { /* Tier-2 */ }
                        setTimeout(() => { void sendText(text); }, 100);
                      },
                      () => {
                        // BF-293 mirror: empty browser SR in whisper-
                        // primary fallback mode does NOT increment the
                        // whisper counter; the operator already paid the
                        // whisper-empty price to get here.
                        if (!gotResult) { /* no counter update */ }
                        setListening(false);
                      },
                      () => setListening(false),
                      { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                    );
                    return;
                  }
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    transcriptUnsubRef.current = null; // BF-319: clear ref on natural completion
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    if (text && text.trim().length > 0) {
                      emptyWhisperCountRef.current = 0;
                      setInput(text);
                      setListening(false);
                      setProcessing(false);
                      // BF-314: sweep ``processing`` again after 300 ms.
                      // Belt-and-suspenders for BF-311: even when the
                      // worker's finally-block ``transcribing: false`` is
                      // delivered, a SECOND consumer (IntentSurface in
                      // wake-word mode, ConversationController if armed
                      // mid-utterance) can re-emit ``transcribing: true``
                      // for an overlapping arm cycle and leave the
                      // spinner stuck. By the time 300 ms has passed,
                      // any straggler from the previous arm cycle has
                      // arrived; force-false guarantees the spinner
                      // clears for THIS chat tab regardless of what other
                      // subsystems do.
                      setTimeout(() => setProcessing(false), 300);
                      // BF-300: disarmWhisperStt above already terminated
                      // whisper capture; nothing further needed here.
                      setTimeout(() => { void sendText(text); }, 100);
                    } else {
                      emptyWhisperCountRef.current += 1;
                      setListening(false);
                      setProcessing(false);
                      setTimeout(() => setProcessing(false), 300); // BF-314 sweep
                    }
                  });
                  transcriptUnsubRef.current = unsub; // BF-319: enable cancel-path cleanup
                  armWhisperStt();
                  return;
                }

                if (isLocalEngine && !whisperHealthy) {
                  // Honest-degrade: operator asked for the local-first
                  // engine but offline_stt_enabled is False (BF-301
                  // browser owns the model fetch, no GGML probe).
                  // Fall through to browser SR for THIS press without
                  // consuming any counter.
                  console.info(
                    `AD-826: whisper primary but unhealthy (backend_available=${voiceHealth?.backend_available}); ` +
                      `using browser SR for agent ${agentId}`,
                  );
                  let gotResult = false;
                  startListening(
                    (text) => {
                      gotResult = true;
                      setInput(text);
                      setListening(false);
                      // BF-300: terminate the continuous SR session — see 3a.
                      try { stopListening(); } catch { /* Tier-2 */ }
                      setTimeout(() => { void sendText(text); }, 100);
                    },
                    () => {
                      if (!gotResult) { /* no counter update on honest-degrade press */ }
                      setListening(false);
                    },
                    () => setListening(false),
                    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                  );
                  return;
                }

                // primary === 'browser' — AD-760 legacy path preserved verbatim.
                if (emptyTranscriptCountRef.current >= 2) {
                  // AD-760: route the next capture through whisperStt
                  // after 2 consecutive empty browser-SpeechRecognition
                  // results. One-shot — reset counter.
                  emptyTranscriptCountRef.current = 0;
                  console.info(`AD-760: whisperStt fallback for agent ${agentId} after 2 empty transcripts`);
                  const unsub = onWhisperTranscript((text: string) => {
                    try { unsub(); } catch { /* Tier-2 */ }
                    transcriptUnsubRef.current = null; // BF-319: clear ref on natural completion
                    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
                    setInput(text);
                    setListening(false);
                    setProcessing(false); // BF-311: clear spinner; worker teardown race can lose transcribing:false.
                    // BF-300: disarmWhisperStt above terminated whisper
                    // capture. The legacy AD-760 browser-SR path is not
                    // running in this fallback branch.
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  });
                  transcriptUnsubRef.current = unsub; // BF-319: enable cancel-path cleanup
                  armWhisperStt();
                  // BF-290: clear visual "listening" state so the operator can
                  // press again to abort (which now also disarms whisper via
                  // the stopListening branch above). The whisper onTranscript
                  // handler at the top of this block sets listening=false on
                  // success; this matches that semantics on the give-up path.
                  setListening(false);
                  return;
                }
                let gotResult = false;
                startListening(
                  (text) => {
                    gotResult = true;
                    emptyTranscriptCountRef.current = 0;
                    setInput(text);
                    setListening(false);
                    // BF-300: terminate the continuous SR session so the
                    // agent's TTS reply isn't captured and auto-sent as
                    // the next user message (#774 echo loop).
                    try { stopListening(); } catch { /* Tier-2 */ }
                    // BF-292: pass ``text`` as an argument so the timer
                    // does not depend on the post-render value of ``input``.
                    setTimeout(() => { void sendText(text); }, 100);
                  },
                  () => {
                    if (!gotResult) {
                      emptyTranscriptCountRef.current += 1;
                    }
                    setListening(false);
                  },
                  () => setListening(false),
                  { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
                );
              }}
              onContextMenu={(event) => {
                event.preventDefault();
                setMicMenuOpen((open) => !open);
              }}
              onKeyDown={(event) => {
                // AD-760 a11y: Shift+F10 opens the same popover.
                if (event.shiftKey && event.key === 'F10') {
                  event.preventDefault();
                  setMicMenuOpen((open) => !open);
                }
              }}
              title={
                processing ? 'Transcribing…' :
                listening ? 'Stop listening' :
                voiceHealth?.engine === 'transformers' ? `Voice input (transformers · ${voiceHealth?.model ?? 'whisper-tiny.en'})` :
                voiceHealth?.engine === 'whisper' ? 'Voice input (whisper)' :
                voiceHealth?.engine === 'browser' ? 'Voice input (browser)' :
                'Voice input'
              }
              aria-label={
                processing ? 'Transcribing speech' :
                listening ? 'Stop listening' : 'Voice input'
              }
              aria-haspopup="menu"
              aria-expanded={micMenuOpen}
              style={{
                background: listening
                  ? 'rgba(240, 176, 96, 0.12)' // amber wash, matches MicIndicator listening
                  : processing
                    ? 'rgba(160, 128, 64, 0.10)' // dim-amber wash
                    : 'transparent',
                border: 'none',
                cursor: 'pointer',
                fontSize: 14,
                padding: '4px',
                borderRadius: 4,
                transition: 'background 0.2s, filter 0.2s',
                flexShrink: 0,
                // BF-313: filter glow encodes ACTIVE state only — listening
                // or processing. Previously a permanent amber drop-shadow
                // was applied whenever micMode === 'conversation', making
                // the button look "lit" at rest and indistinguishable from
                // actually-listening. Operators reported the mic icon
                // staying amber after each transcript even after BF-311
                // cleared the processing spinner — root cause was this
                // mode-driven glow, not a real state-stuck bug. The mic
                // mode is already visible in the right-click popover; a
                // permanent glow added no information and conflicted with
                // HXI Design Principle #4 (motion/glow communicates state).
                //
                // BF-313 follow-up: the idle dim drop-shadow was also too
                // easy to misread as "still slightly on" once the real
                // listening/processing glows disappeared. Idle state now
                // renders with NO filter at all — same as the other
                // resting input-row buttons. Glow = active. No glow = idle.
                // Unambiguous.
                filter: listening
                  ? 'drop-shadow(0 0 4px #f0b060)'
                  : processing
                    ? 'drop-shadow(0 0 3px #a08040)'
                    : 'none',
              }}
            >
              <MicIndicator
                state={
                  processing
                    ? 'processing'
                    : ttsActive
                      ? 'muted'
                      : listening
                        ? 'listening'
                        : 'idle'
                }
                size={14}
                intensity={audioIntensity}
              />
            </button>
            {/* BF-301: first-load STT model download progress. */}
            {transformersProgress && transformersProgress.progress !== undefined && transformersProgress.progress < 1 && (
              <div
                data-testid="bf301-progress"
                style={{
                  position: 'absolute',
                  bottom: -4,
                  left: 0,
                  right: 0,
                  height: 2,
                  background: 'rgba(240, 176, 96, 0.15)',
                  overflow: 'hidden',
                  pointerEvents: 'none',
                }}
                title={`Loading STT model: ${Math.round((transformersProgress.progress ?? 0) * 100)}%`}
              >
                <div
                  style={{
                    width: `${Math.round((transformersProgress.progress ?? 0) * 100)}%`,
                    height: '100%',
                    background: '#f0b060',
                    transition: 'width 200ms linear',
                  }}
                />
              </div>
            )}
            {micMenuOpen && (
              <div
                ref={micMenuRef}
                data-testid="profile-chat-mic-mode-menu"
                role="menu"
                style={{
                  position: 'absolute',
                  right: 0,
                  bottom: 'calc(100% + 6px)',
                  minWidth: 160,
                  background: 'rgba(10, 10, 18, 0.96)',
                  border: '1px solid rgba(240, 176, 96, 0.25)',
                  borderRadius: 8,
                  boxShadow: '0 10px 24px rgba(0, 0, 0, 0.35)',
                  zIndex: 30,
                  overflow: 'hidden',
                }}
              >
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={micMode === 'ptt'}
                  data-testid="profile-chat-mic-mode-ptt"
                  onClick={() => {
                    localStorage.setItem(getMicModeKey(agentId), 'ptt');
                    setMicMode('ptt');
                    setMicMenuOpen(false);
                  }}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    textAlign: 'left',
                    background: 'transparent',
                    border: 'none',
                    color: '#e0dcd4',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 16 16" fill="none"
                       stroke={micMode === 'ptt' ? '#f0b060' : '#444459'}
                       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M3 8.5L6.5 12 13 4" />
                  </svg>
                  Press to talk
                </button>
                <button
                  type="button"
                  role="menuitemradio"
                  aria-checked={micMode === 'conversation'}
                  data-testid="profile-chat-mic-mode-conversation"
                  onClick={() => {
                    localStorage.setItem(getMicModeKey(agentId), 'conversation');
                    setMicMode('conversation');
                    setMicMenuOpen(false);
                  }}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    textAlign: 'left',
                    background: 'transparent',
                    border: 'none',
                    color: '#e0dcd4',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 16 16" fill="none"
                       stroke={micMode === 'conversation' ? '#f0b060' : '#444459'}
                       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M3 8.5L6.5 12 13 4" />
                  </svg>
                  Conversation mode
                </button>
              </div>
            )}
          </div>
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
        @keyframes screen-share-pulse {
          0%, 100% { opacity: 0.85; }
          50% { opacity: 1; }
        }
        @keyframes bf294-mic-listen {
          0%, 100% { opacity: 0.35; transform: scale(1.0); }
          50%      { opacity: 0.85; transform: scale(1.18); }
        }
        @keyframes bf294-mic-process {
          0%   { transform: rotate(0deg);   opacity: 0.55; }
          50%  { transform: rotate(180deg); opacity: 0.85; }
          100% { transform: rotate(360deg); opacity: 0.55; }
        }
      `}</style>
    </div>
  );
}
