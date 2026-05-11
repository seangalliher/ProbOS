// AD-722: agent-observable avatar telemetry surface.
// Mouth-active is best-effort — see telemetry.py docstring for semantics.
// No emoji — all icons are inline <svg> with strokeWidth: 1.5, strokeLinecap: round.
import { useEffect, useState } from 'react';

const AMBER = '#f0b060';
const DIM = '#666680';

interface AgentSignals {
  trust_delta: number;
  load: number;
  working_state: string;
  tier3_alert: boolean;
}

interface ModulationSnapshot {
  pitch_factor: number;
  rate_factor: number;
  volume_factor: number;
  fired_rules: string[];
}

interface DslSummary {
  body_type: string;
  hair_style: string;
  primary_color: string;
  outfit_style: string;
  color_palette_hint: string;
}

interface AvatarTelemetry {
  agent_id: string;
  expression_resting: string | null;
  current_signals: AgentSignals;
  mouth_active: boolean;
  applied_modulation: ModulationSnapshot | null;
  dsl_summary: DslSummary | null;
  last_observed_at: number;
  degraded_reasons: string[];
}

// AD-722a-5: divergence history surface types.
interface DivergenceResultPayload {
  intent_emotion: string;
  applied_fired_rules: string[];
  match_score: number;
  signed_divergence: number;
  magnitude: number;
}

interface DivergenceHistoryEntryPayload {
  timestamp: number;
  result: DivergenceResultPayload;
  note: string;  // server-rendered OUTPUT-subject note
}

interface DivergenceAggregatePayload {
  window_size: number;
  total: number;
  diverged: number;
  percentage: number;
}

interface DivergenceHistoryPayload {
  agent_id: string;
  history: DivergenceHistoryEntryPayload[];
  aggregate: DivergenceAggregatePayload;
}

const HISTORY_POLL_MS = 5000;  // Lower frequency than telemetry -- history changes only on reply.
const HISTORY_LIMIT = 20;

const POLL_MS = 2000;

interface SelfImageTabProps {
  agentId: string;
  isActive: boolean;
}

export function SelfImageTab({ agentId, isActive }: SelfImageTabProps) {
  const [snap, setSnap] = useState<AvatarTelemetry | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isActive || !agentId) return;
    let cancelled = false;
    let pollIntervalId: ReturnType<typeof setInterval> | null = null;
    let ws: WebSocket | null = null;
    let wsOpened = false;
    let wsTimeoutId: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = () => {
      fetch(`/api/agent/${agentId}/avatar-telemetry`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((data) => {
          if (!cancelled) {
            setSnap(data);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    };

    const startPollFallback = () => {
      // AD-722b: poll fallback — fires when WS open never arrives, or after
      // a previously-open WS closes without recovery. Idempotent.
      if (pollIntervalId !== null) return;
      fetchOnce();
      pollIntervalId = setInterval(fetchOnce, POLL_MS);
    };

    const stopPollFallback = () => {
      if (pollIntervalId !== null) {
        clearInterval(pollIntervalId);
        pollIntervalId = null;
      }
    };

    // AD-722b: open WS first; fall back to poll on error/close-before-open
    // or 5 s open-timeout.
    try {
      const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProto}//${window.location.host}/api/agent/${agentId}/avatar-telemetry-stream`;
      ws = new WebSocket(wsUrl);

      wsTimeoutId = setTimeout(() => {
        if (!wsOpened && !cancelled) {
          // Open never arrived — fall back to polling.
          startPollFallback();
        }
      }, 5000);

      ws.onopen = () => {
        wsOpened = true;
        if (wsTimeoutId !== null) {
          clearTimeout(wsTimeoutId);
          wsTimeoutId = null;
        }
        // Suppress polling — WS is the live channel now.
        stopPollFallback();
      };

      ws.onmessage = (ev) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(ev.data as string);
          if (data && data.type === 'ping') return;
          if (data && data.type === 'error') {
            setError(String(data.reason ?? 'ws_error'));
            return;
          }
          setSnap(data);
          setError(null);
        } catch {
          // Ignore malformed frames.
        }
      };

      ws.onerror = () => {
        if (!wsOpened && !cancelled) {
          startPollFallback();
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        // Whether or not we had opened, fall back to poll. Reconnect with
        // backoff is forward marker AD-722b-6.
        startPollFallback();
      };
    } catch {
      // Constructor threw (e.g. WebSocket undefined in jsdom). Fall back.
      startPollFallback();
    }

    return () => {
      cancelled = true;
      if (wsTimeoutId !== null) {
        clearTimeout(wsTimeoutId);
        wsTimeoutId = null;
      }
      if (ws !== null) {
        try { ws.close(); } catch { /* ignore */ }
        ws = null;
      }
      stopPollFallback();
    };
  }, [agentId, isActive]);

  if (!snap && !error) {
    return (
      <div data-testid="self-image-loading" style={{ padding: 16, color: DIM }}>
        Awaiting telemetry…
      </div>
    );
  }

  return (
    <div data-testid="self-image-tab" style={{ padding: 12, fontSize: 12, color: '#cccce0' }}>
      <style>{`
        @keyframes ad722-pulse {
          0%, 100% { opacity: 1; }
          50%      { opacity: 0.45; }
        }
        .ad722-pulse-amber {
          animation: ad722-pulse 1.1s ease-in-out infinite;
        }
      `}</style>
      {error && (
        <div data-testid="self-image-error" style={{ color: AMBER, marginBottom: 8 }}>
          telemetry error: {error}
        </div>
      )}

      {snap?.dsl_summary ? (
        <PanelDslSummary dsl={snap.dsl_summary} expression={snap.expression_resting} />
      ) : (
        <PanelHeader title="DSL summary">
          <span style={{ color: DIM }}>no DSL persisted</span>
        </PanelHeader>
      )}

      <PanelSignals signals={snap?.current_signals} />
      <PanelModulation mod={snap?.applied_modulation ?? null} />
      <PanelMouthActive active={!!snap?.mouth_active} />

      {snap && snap.degraded_reasons.length > 0 && (
        <PanelDegraded reasons={snap.degraded_reasons} />
      )}

      <PanelDivergenceHistory agentId={agentId} isActive={isActive} />
    </div>
  );
}

function PanelDivergenceHistory({
  agentId,
  isActive,
}: {
  agentId: string;
  isActive: boolean;
}) {
  // AD-722a-5: divergence history panel.
  // Auto-hides on 503 (feature off). Renders empty-history fallback when
  // history is empty but feature is on. No emoji -- stroke-only SVG.
  // AD-727 rule #8: every rendered note is OUTPUT-subject. The server
  // pre-renders the note string in `entry.note` so phrasing is server-
  // authoritative and inherits the Python regex test gate.
  const [payload, setPayload] = useState<DivergenceHistoryPayload | null>(null);
  const [disabled, setDisabled] = useState<boolean>(false);

  useEffect(() => {
    if (!isActive || !agentId) return;
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const fetchOnce = () => {
      fetch(`/api/agent/${agentId}/avatar-telemetry/divergence-history?limit=${HISTORY_LIMIT}`)
        .then((r) => {
          if (r.status === 503) {
            if (!cancelled) setDisabled(true);
            return null;
          }
          if (!r.ok) return Promise.reject(new Error(`HTTP ${r.status}`));
          return r.json();
        })
        .then((data) => {
          if (!cancelled && data !== null) {
            setPayload(data);
            setDisabled(false);
          }
        })
        .catch(() => {
          // Tier-2: silent degrade. Don't surface fetch errors here --
          // the main telemetry error banner already covers connectivity.
        });
    };

    fetchOnce();
    intervalId = setInterval(fetchOnce, HISTORY_POLL_MS);

    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [agentId, isActive]);

  if (disabled) return null;
  if (!payload) {
    return (
      <PanelHeader title="Divergence history">
        <span data-testid="divergence-loading" style={{ color: DIM }}>
          loading…
        </span>
      </PanelHeader>
    );
  }

  const { history, aggregate } = payload;
  // Defense in depth -- treat malformed payloads (missing aggregate / history)
  // as not-yet-loaded rather than crashing the parent panel.
  if (!aggregate || !Array.isArray(history)) {
    return (
      <PanelHeader title="Divergence history">
        <span data-testid="divergence-loading" style={{ color: DIM }}>
          loading…
        </span>
      </PanelHeader>
    );
  }
  const pct = Math.round(aggregate.percentage * 100);

  return (
    <PanelHeader title="Divergence history">
      <div data-testid="divergence-aggregate" style={{ marginBottom: 6 }}>
        {aggregate.total === 0 ? (
          <span style={{ color: DIM }}>no divergences recorded</span>
        ) : (
          <span>
            Of the last <strong>{aggregate.total}</strong> replies,{' '}
            <strong style={{ color: AMBER }}>{aggregate.diverged}</strong> had
            non-zero intent-vs-output divergence (<strong>{pct}%</strong>).
          </span>
        )}
      </div>
      <div
        data-testid="divergence-history-list"
        style={{
          maxHeight: 160,
          overflowY: 'auto',
          fontSize: 11,
          borderTop: `1px solid ${DIM}`,
          paddingTop: 4,
        }}
      >
        {history.length === 0 ? (
          <span style={{ color: DIM }}>(empty)</span>
        ) : (
          history.map((entry, i) => (
            <div
              key={`${entry.timestamp}-${i}`}
              data-testid="divergence-history-entry"
              style={{ marginBottom: 4 }}
            >
              <span style={{ color: DIM }}>
                {new Date(entry.timestamp * 1000).toISOString().substring(11, 19)}{' '}
              </span>
              <span>{entry.note}</span>
            </div>
          ))
        )}
      </div>
    </PanelHeader>
  );
}

function PanelHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 10 }}>
      <h4 data-testid={`panel-header-${title.toLowerCase().replace(/\s+/g, '-')}`}
          style={{ margin: '0 0 4px 0', fontSize: 11, color: AMBER, letterSpacing: '0.04em' }}>
        {title.toUpperCase()}
      </h4>
      <div style={{ paddingLeft: 6 }}>{children}</div>
    </section>
  );
}

function PanelDslSummary({ dsl, expression }: { dsl: DslSummary; expression: string | null }) {
  return (
    <PanelHeader title="DSL summary">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <svg width="16" height="16" aria-hidden="true">
          <rect width="16" height="16" fill={dsl.primary_color} stroke={DIM} strokeWidth={1} />
        </svg>
        <span data-testid="dsl-primary-color">{dsl.primary_color}</span>
      </div>
      <div data-testid="dsl-body">body: {dsl.body_type}</div>
      <div data-testid="dsl-hair">hair: {dsl.hair_style}</div>
      <div data-testid="dsl-outfit">outfit: {dsl.outfit_style}</div>
      <div data-testid="dsl-expression">expression: {expression ?? '—'}</div>
    </PanelHeader>
  );
}

function PanelSignals({ signals }: { signals: AgentSignals | undefined }) {
  if (!signals) {
    return (
      <PanelHeader title="Current signals">
        <span style={{ color: DIM }}>no data</span>
      </PanelHeader>
    );
  }
  const stateActive = signals.working_state !== 'idle';
  return (
    <PanelHeader title="Current signals">
      <div data-testid="signal-working-state" style={{ color: stateActive ? AMBER : DIM }}>
        working_state: {signals.working_state}
      </div>
      <div data-testid="signal-trust-delta">
        trust_delta: {signals.trust_delta >= 0 ? '+' : ''}{signals.trust_delta}
      </div>
      <div data-testid="signal-load">load: {signals.load}</div>
      <div data-testid="signal-tier3-alert">
        <svg width="14" height="14" aria-hidden="true" style={{ verticalAlign: 'middle' }}>
          <path
            d="M7 2 L13 12 L1 12 Z"
            fill="none"
            stroke={signals.tier3_alert ? AMBER : DIM}
            strokeWidth={1.5}
            strokeLinecap="round"
          />
        </svg>
        {' '}tier3_alert: {signals.tier3_alert ? 'yes' : 'no'}
      </div>
    </PanelHeader>
  );
}

function PanelModulation({ mod }: { mod: ModulationSnapshot | null }) {
  if (!mod) {
    return (
      <PanelHeader title="Voice modulation">
        <span style={{ color: DIM }}>voice profile unavailable</span>
      </PanelHeader>
    );
  }
  return (
    <PanelHeader title="Voice modulation">
      <div data-testid="mod-pitch">pitch_factor: {mod.pitch_factor}</div>
      <div data-testid="mod-rate">rate_factor: {mod.rate_factor}</div>
      <div data-testid="mod-volume">volume_factor: {mod.volume_factor}</div>
      <div data-testid="mod-fired-rules">
        fired_rules: {mod.fired_rules.length === 0 ? 'none' : mod.fired_rules.join(', ')}
      </div>
    </PanelHeader>
  );
}

function PanelMouthActive({ active }: { active: boolean }) {
  return (
    <PanelHeader title="Mouth active">
      <span
        data-testid="mouth-active-indicator"
        className={active ? 'ad722-pulse-amber' : ''}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
      >
        <svg width="14" height="14" aria-hidden="true">
          <circle
            cx="7" cy="7" r="5"
            fill="none"
            stroke={active ? AMBER : DIM}
            strokeWidth={1.5}
            strokeLinecap="round"
          />
        </svg>
        <span style={{ color: active ? AMBER : DIM }}>{active ? 'speaking' : 'silent'}</span>
      </span>
    </PanelHeader>
  );
}

function PanelDegraded({ reasons }: { reasons: string[] }) {
  // Split reasons into "informational" (normal startup states like an
  // unmodified crew profile) and "real failures" (parser errors, missing
  // runtime services, etc.). Only real failures get the amber DEGRADED
  // warning; informational reasons show as a quiet gray note.
  const INFORMATIONAL = new Set([
    'crew_profile_default',  // server step 2 — no live profile, using typed defaults
    'crew_profile_seeded',   // server step 2 — no live profile, using seed YAML
    'appearance_profile_missing',  // legacy — kept for older snapshots
    'dsl_not_persisted',     // expected — agent hasn't proposed an avatar yet
    'insufficient_trust_history',  // expected — agent hasn't accumulated history yet
  ]);
  const informational = reasons.filter((r) => INFORMATIONAL.has(r));
  const failures = reasons.filter((r) => !INFORMATIONAL.has(r));

  if (failures.length === 0 && informational.length === 0) return null;

  return (
    <>
      {failures.length > 0 && (
        <section
          data-testid="degraded-strip"
          style={{
            marginTop: 8,
            padding: 6,
            border: `1px solid ${AMBER}`,
            borderRadius: 4,
            color: AMBER,
            fontSize: 11,
          }}
        >
          <div style={{ marginBottom: 2, letterSpacing: '0.04em' }}>DEGRADED</div>
          {failures.map((r) => (
            <div key={r} data-testid={`degraded-reason-${r}`}>
              • {r}
            </div>
          ))}
        </section>
      )}
      {informational.length > 0 && (
        <section
          data-testid="informational-strip"
          style={{
            marginTop: 8,
            padding: 6,
            border: `1px solid ${DIM}`,
            borderRadius: 4,
            color: DIM,
            fontSize: 11,
          }}
        >
          <div style={{ marginBottom: 2, letterSpacing: '0.04em' }}>NOTE</div>
          {informational.map((r) => (
            <div key={r} data-testid={`degraded-reason-${r}`}>
              • {r}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
