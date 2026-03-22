/* GlassTaskCard — center-stage task card on the glass surface (AD-388) */

import type { AgentTaskView } from '../../store/types';
import { useStore } from '../../store/useStore';
import { DEPT_COLORS, STATUS_COLORS, formatElapsed, truncate } from '../bridge/BridgeCards';

interface GlassTaskCardProps {
  task: AgentTaskView;
  elevated?: boolean;
}

export function GlassTaskCard({ task, elevated }: GlassTaskCardProps) {
  const deptColor = DEPT_COLORS[task.department?.toLowerCase()] || '#666';
  const statusColor = STATUS_COLORS[task.status] || '#888';
  const isWorking = task.status === 'working';
  const needsAttention = task.requires_action;
  const pct = task.step_total > 0 ? Math.round((task.step_current / task.step_total) * 100) : 0;

  return (
    <div
      className={needsAttention ? 'glass-card-attention' : undefined}
      onClick={(e) => {
        e.stopPropagation();
        useStore.setState({ bridgeOpen: true });
      }}
      style={{
        width: 280,
        padding: '10px 14px 10px 17px',
        background: 'rgba(26, 26, 46, 0.7)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: needsAttention
          ? '1px solid rgba(240, 176, 96, 0.35)'
          : '1px solid rgba(255, 255, 255, 0.08)',
        borderLeft: `3px solid ${deptColor}`,
        borderRadius: 2,
        boxShadow: needsAttention
          ? '0 2px 12px rgba(240, 176, 96, 0.15), 0 2px 8px rgba(0, 0, 0, 0.4)'
          : '0 2px 8px rgba(0, 0, 0, 0.4)',
        cursor: 'pointer',
        pointerEvents: 'auto' as const,
        transform: elevated ? 'translateY(-8px)' : 'none',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        animation: needsAttention ? 'glass-attention 2s ease-in-out infinite' : undefined,
      }}
    >
      {/* Top row: status dot + AD number + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: statusColor, display: 'inline-block',
          animation: isWorking ? 'neural-pulse 2s ease-in-out infinite' : 'none',
        }} />
        {task.ad_number > 0 && (
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, fontWeight: 400, color: deptColor, flexShrink: 0,
          }}>
            AD-{task.ad_number}
          </span>
        )}
        <span style={{
          fontFamily: "'Inter', sans-serif",
          fontSize: 14, fontWeight: 600, color: '#e0e0e0',
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {truncate(task.title, 50)}
        </span>
      </div>

      {/* Middle: progress bar */}
      {task.step_total > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, color: '#808090',
          }}>
            {task.step_current}/{task.step_total}
          </span>
          <div style={{
            flex: 1, height: 3, borderRadius: 1, background: 'rgba(255,255,255,0.06)',
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

      {/* Bottom row: agent_type + elapsed + department */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, marginTop: 6,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10, fontWeight: 400, color: '#808090',
      }}>
        <span>{task.agent_type}</span>
        {task.started_at > 0 && (
          <>
            <span style={{ color: '#555' }}>{'\u00B7'}</span>
            <span>{formatElapsed(task.started_at)}</span>
          </>
        )}
        <span style={{ marginLeft: 'auto', textTransform: 'capitalize' as const }}>
          {task.department}
        </span>
      </div>
    </div>
  );
}
