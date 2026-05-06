/**
 * AD-569g: HXI Behavioral Metrics Dashboard (v1, no facet breakdown).
 *
 * Floating panel surfacing the five content-level behavioral metrics
 * computed by BehavioralMetricsEngine (AD-569). Read-only — Captain
 * views; engine writes via Dream Step 13.
 *
 * Backend: GET /api/behavioral-metrics, /api/behavioral-metrics/history
 * (both shipped under AD-569).
 *
 * Facet breakdown (department × stimulus × occasion) lands with AD-569f.
 */

import { useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { BehavioralSnapshot } from '../store/types';

interface MetricDef {
  key: keyof BehavioralSnapshot;
  label: string;
  color: string;
  description: string;
  nullable?: boolean;
}

const METRICS: MetricDef[] = [
  {
    key: 'frame_diversity_score',
    label: 'Frame Diversity',
    color: '#50b0a0',
    description: 'Diversity of analytical lenses applied across investigation threads.',
  },
  {
    key: 'synthesis_rate',
    label: 'Synthesis',
    color: '#f0b060',
    description: 'Rate at which threads produce emergent novel insights beyond input elements.',
  },
  {
    key: 'cross_dept_trigger_rate',
    label: 'Cross-Dept Trigger',
    color: '#a070d0',
    description: "One department's findings triggering another department's investigation (silo-breaking).",
  },
  {
    key: 'convergence_correctness_rate',
    label: 'Convergence Correctness',
    color: '#70c080',
    description: 'Convergences observably verified as correct against ground truth.',
    nullable: true,
  },
  {
    key: 'anchor_grounded_rate',
    label: 'Anchor-Grounded Emergence',
    color: '#d0a030',
    description: 'Emergent insights with verified provenance / source-anchor independence.',
  },
];

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

function deptColor(dept: string): string {
  return DEPT_COLORS[(dept || '').toLowerCase()] || '#8888a0';
}

function relativeTime(ts: number): string {
  if (!ts || !isFinite(ts)) return '';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function isoTime(ts: number): string {
  if (!ts || !isFinite(ts)) return '';
  try {
    return new Date(ts * 1000).toISOString();
  } catch {
    return '';
  }
}

interface SparklineProps {
  values: number[];
  color: string;
  testId: string;
}

/**
 * Pure-SVG sparkline using a fixed 0-100 viewBox. No DOM measurement —
 * the SVG scales to its container via `width/height: 100%`.
 *
 * Empty/single-point series → dashed baseline path. ≥2 points → polyline.
 */
function Sparkline({ values, color, testId }: SparklineProps) {
  const finite = values.filter(v => typeof v === 'number' && isFinite(v));

  if (finite.length < 2) {
    return (
      <svg
        data-testid={testId}
        viewBox="0 0 100 24"
        preserveAspectRatio="none"
        style={{ width: '100%', height: 24, display: 'block' }}
      >
        <path
          d="M0,12 L100,12"
          stroke="#444458"
          strokeWidth={1}
          strokeDasharray="2 3"
          fill="none"
        />
      </svg>
    );
  }

  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const range = max - min;
  const denom = range > 1e-9 ? range : 1;
  const stepX = finite.length > 1 ? 100 / (finite.length - 1) : 0;
  const points = finite
    .map((v, i) => {
      const x = i * stepX;
      // Invert Y: high score → top of viewBox
      const y = 22 - ((v - min) / denom) * 20;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg
      data-testid={testId}
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      style={{ width: '100%', height: 24, display: 'block' }}
    >
      <polyline
        points={points}
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

function formatScore(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v as number)) return '—';
  return (v as number).toFixed(2);
}

function formatPercent(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v as number)) return '—';
  return `${Math.round((v as number) * 100)}%`;
}

export default function BehavioralMetricsPanel() {
  const open = useStore(s => s.behavioralMetricsOpen);
  const close = useStore(s => s.closeBehavioralMetrics);
  const refresh = useStore(s => s.refreshBehavioralMetrics);
  const latest = useStore(s => s.behavioralMetricsLatest);
  const history = useStore(s => s.behavioralMetricsHistory);
  const loading = useStore(s => s.behavioralMetricsLoading);
  const error = useStore(s => s.behavioralMetricsError);

  // ESC-to-close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, close]);

  if (!open) return null;

  const compositeScore = latest ? latest.behavioral_quality_score : null;
  const isEmpty = !latest && !loading && !error;

  return (
    <div
      data-testid="behavioral-metrics-panel"
      style={{
        position: 'fixed',
        top: 60, left: 60, right: 60, bottom: 60,
        zIndex: 30,
        background: 'rgba(10, 10, 18, 0.95)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(240, 176, 96, 0.25)',
        borderRadius: 8,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#c0bab0',
      }}
    >
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ color: '#f0b060', fontSize: 12, fontWeight: 700, letterSpacing: 1.5 }}>
            BEHAVIORAL METRICS
          </span>
          <span style={{ color: '#6a6a7a', fontSize: 10 }}>
            Crew intelligence — observed
          </span>
          {latest && (
            <div
              data-testid="behavioral-metrics-composite"
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 6,
                marginLeft: 8,
                opacity: loading ? 0.6 : 1,
                transition: 'opacity 0.4s ease',
              }}
            >
              <span style={{ color: '#8888a0', fontSize: 9, letterSpacing: 1 }}>QUALITY</span>
              <span style={{ color: '#f0b060', fontSize: 16, fontWeight: 700 }}>
                {formatPercent(compositeScore)}
              </span>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {latest && (
            <span
              data-testid="behavioral-metrics-timestamp"
              title={isoTime(latest.timestamp)}
              style={{ color: '#6a6a7a', fontSize: 10 }}
            >
              {relativeTime(latest.timestamp)}
            </span>
          )}
          <div
            onClick={() => refresh()}
            data-testid="behavioral-metrics-refresh"
            title="Refresh"
            style={{
              cursor: 'pointer', padding: '4px 10px',
              color: '#8888a0', fontSize: 12,
              userSelect: 'none' as const,
            }}
          >
            ↻
          </div>
          <div
            onClick={close}
            data-testid="behavioral-metrics-close"
            style={{
              cursor: 'pointer', padding: '4px 10px',
              color: '#8888a0', fontSize: 12,
              userSelect: 'none' as const,
            }}
          >
            ×
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 18 }}>
        {error && (
          <div
            data-testid="behavioral-metrics-error"
            style={{ color: '#a04848', fontSize: 11, padding: 12 }}
          >
            {error}
          </div>
        )}

        {loading && !latest && !error && (
          <div
            data-testid="behavioral-metrics-loading"
            style={{ color: '#6a6a7a', fontSize: 11, padding: 12 }}
          >
            Computing behavioral metrics…
          </div>
        )}

        {isEmpty && (
          <div
            data-testid="behavioral-metrics-empty"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 200,
              color: '#8888a0',
              fontSize: 12,
              textAlign: 'center' as const,
              padding: 24,
              lineHeight: 1.5,
            }}
          >
            Behavioral metrics will appear after the first dream cycle (Step 13).
          </div>
        )}

        {latest && (
          <div
            data-testid="behavioral-metrics-tiles"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
              gap: 14,
            }}
          >
            {METRICS.map(m => {
              const raw = latest[m.key] as number | null | undefined;
              const display = m.nullable && raw === null ? '—' : formatScore(raw as number);
              const series = history.map(s => s[m.key] as number | null);
              const numericSeries = series
                .map(v => (v === null || v === undefined ? NaN : (v as number)))
                .filter(v => isFinite(v));
              return (
                <div
                  key={m.key as string}
                  data-testid={`behavioral-tile-${m.key}`}
                  title={m.description}
                  style={{
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: 6,
                    padding: 14,
                    background: 'rgba(255,255,255,0.02)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{
                    fontSize: 9, letterSpacing: 1.4,
                    color: m.color, textTransform: 'uppercase' as const,
                  }}>
                    {m.label}
                  </div>
                  <div
                    data-testid={`behavioral-score-${m.key}`}
                    style={{ fontSize: 24, fontWeight: 700, color: '#c0bab0' }}
                  >
                    {display}
                  </div>
                  <Sparkline
                    values={numericSeries}
                    color={m.color}
                    testId={`behavioral-sparkline-${m.key}`}
                  />
                  {m.key === 'frame_diversity_score' && latest.department_representation && (
                    <div
                      data-testid="behavioral-dept-chips"
                      style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}
                    >
                      {Object.entries(latest.department_representation).map(([dept, count]) => (
                        <span
                          key={dept}
                          style={{
                            fontSize: 9,
                            padding: '2px 6px',
                            borderRadius: 3,
                            background: 'rgba(255,255,255,0.04)',
                            color: deptColor(dept),
                            letterSpacing: 0.5,
                          }}
                        >
                          {dept}·{count}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{
        padding: '10px 18px',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        fontSize: 10,
        color: '#6a6a7a',
        letterSpacing: 0.5,
      }}>
        Facet breakdown (department × stimulus × occasion) lands with AD-569f.
      </div>
    </div>
  );
}
