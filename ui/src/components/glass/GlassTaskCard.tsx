/* GlassTaskCard — center-stage task card on the glass surface (AD-388, AD-392) */

import type { AgentTaskView } from '../../store/types';
import { useStore } from '../../store/useStore';
import { DEPT_COLORS, STATUS_COLORS, formatElapsed, truncate } from '../bridge/BridgeCards';

export const TRUST_COLORS = {
  low: '#7060a8',
  medium: '#88a4c8',
  high: '#f0b060',
};

export function trustBand(trust: number): 'low' | 'medium' | 'high' {
  if (trust < 0.35) return 'low';
  if (trust <= 0.7) return 'medium';
  return 'high';
}

interface GlassTaskCardProps {
  task: AgentTaskView;
  elevated?: boolean;
  trust?: number;
  compact?: boolean;
  isGazed?: boolean;
}

export function GlassTaskCard({ task, elevated, trust = 0.5, compact, isGazed }: GlassTaskCardProps) {
  const deptColor = DEPT_COLORS[task.department?.toLowerCase()] || '#666';
  const statusColor = STATUS_COLORS[task.status] || '#888';
  const isWorking = task.status === 'working';
  const needsAttention = task.requires_action;
  const pct = task.step_total > 0 ? Math.round((task.step_current / task.step_total) * 100) : 0;

  const band = trustBand(trust);
  const trustColor = TRUST_COLORS[band];

  // Trust-driven dimensions
  const cardWidth = compact ? 'calc(100% - 32px)' : (band === 'high' ? 240 : 280);
  const borderWidth = band === 'low' ? 4 : (band === 'high' ? 2 : 3);
  const bgAlpha = band === 'low' ? 0.85 : (band === 'high' ? 0.65 : 0.75);
  const titleSize = (compact || band === 'high') ? 12 : 14;
  const systemSize = (compact || band === 'high') ? 9 : 10;
  const cardPadding = (compact || band === 'high') ? '10px 12px 10px 15px' : '14px 16px 14px 19px';

  return (
    <div
      className={needsAttention ? 'glass-card-attention' : undefined}
      onClick={(e) => {
        e.stopPropagation();
        useStore.setState((s) => ({
          expandedGlassTask: s.expandedGlassTask === task.id ? null : task.id,
        }));
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        useStore.setState({ bridgeOpen: true });
      }}
      style={{
        width: cardWidth,
        padding: cardPadding,
        background: `rgba(10, 10, 18, ${bgAlpha})`,
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: needsAttention
          ? '1px solid rgba(240, 176, 96, 0.35)'
          : '1px solid rgba(255, 255, 255, 0.08)',
        borderLeft: `${borderWidth}px solid ${deptColor}`,
        borderRadius: 6,
        boxShadow: needsAttention
          ? '0 2px 12px rgba(240, 176, 96, 0.15), 0 2px 8px rgba(0, 0, 0, 0.4)'
          : '0 2px 8px rgba(0, 0, 0, 0.4)',
        cursor: 'pointer',
        pointerEvents: 'auto' as const,
        transform: `${elevated ? 'translateY(-8px)' : ''} ${isGazed ? 'scale(1.03)' : ''}`.trim() || 'none',
        transition: 'opacity 0.3s ease, transform 0.2s ease-out, box-shadow 0.2s ease-out, width 0.3s ease',
        animation: needsAttention ? 'glass-attention 2s ease-in-out infinite' : undefined,
      }}
    >
      {/* Top row: status dot + AD number + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
          background: statusColor, display: 'inline-block',
          animation: isWorking ? 'neural-pulse 2s ease-in-out infinite' : 'none',
        }} />
        {task.ad_number > 0 && (
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: systemSize, fontWeight: 400, color: deptColor, flexShrink: 0,
          }}>
            AD-{task.ad_number}
          </span>
        )}
        <span style={{
          fontFamily: "'Inter', sans-serif",
          fontSize: titleSize, fontWeight: 600, color: '#e0e0e0',
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {truncate(task.title, 50)}
        </span>
      </div>

      {/* Middle: progress bar */}
      {task.step_total > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: systemSize, color: '#808090',
          }}>
            {task.step_current}/{task.step_total}
          </span>
          <div style={{
            flex: 1, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.06)',
            overflow: 'hidden',
          }}>
            <div style={{
              width: `${pct}%`, height: '100%', borderRadius: 1,
              background: deptColor,
              transition: 'width 0.3s ease',
            }} />
          </div>
        </div>
      )}

      {/* Bottom row: agent_type + elapsed + trust dot + department */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginTop: 10,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: systemSize, fontWeight: 400, color: '#808090',
      }}>
        <span>{task.agent_type}</span>
        {task.started_at > 0 && (
          <>
            <span style={{ color: '#555' }}>{'\u00B7'}</span>
            <span>{formatElapsed(task.started_at)}</span>
          </>
        )}
        <span style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
          background: trustColor, display: 'inline-block',
          marginLeft: 'auto',
        }} />
        <span style={{ textTransform: 'capitalize' as const }}>
          {task.department}
        </span>
      </div>
    </div>
  );
}
