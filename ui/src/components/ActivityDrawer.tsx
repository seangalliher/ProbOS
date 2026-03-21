/* Activity Drawer — slide-out panel for real-time agent task visibility (AD-321) */

import { useState } from 'react';
import { useStore } from '../store/useStore';
import type { AgentTaskView, TaskStepView } from '../store/types';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

const STATUS_COLORS: Record<string, string> = {
  queued: '#555566',
  working: '#ffaa44',
  review: '#66ccff',
  done: '#50c878',
  failed: '#ff5555',
};

const STEP_ICONS: Record<string, string> = {
  pending: '\u25CB',      // ○
  in_progress: '\u25D0',  // ◐
  done: '\u25CF',          // ●
  failed: '\u2715',        // ✕
};

function formatElapsed(startedAt: number): string {
  const sec = Math.max(0, Math.floor((Date.now() / 1000) - startedAt));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  if (min < 60) return `${min}m ${remSec}s`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return `${hr}h ${remMin}m`;
}

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + '\u2026';
}

/* ── Section Header ── */
function SectionHeader({
  label, count, color, defaultOpen, children,
}: {
  label: string; count: number; color: string; defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <span style={{ fontSize: 8, color: '#666' }}>{open ? '\u25BC' : '\u25B6'}</span>
        <span style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 2,
          textTransform: 'uppercase' as const,
          color,
        }}>
          {label} ({count})
        </span>
      </div>
      {open && <div style={{ padding: '4px 8px 8px' }}>{children}</div>}
    </div>
  );
}

/* ── Step List ── */
function StepList({ steps }: { steps: TaskStepView[] }) {
  return (
    <div style={{ marginTop: 6 }}>
      {steps.map((step, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: '#aaa', marginBottom: 2 }}>
          <span style={{ color: STATUS_COLORS[step.status] || '#888' }}>
            {STEP_ICONS[step.status] || '\u25CB'}
          </span>
          <span style={{ flex: 1 }}>{step.label}</span>
          {step.status === 'done' && step.duration_ms > 0 && (
            <span style={{ color: '#666', fontSize: 9 }}>{formatDurationMs(step.duration_ms)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Progress Bar ── */
function ProgressBar({ current, total }: { current: number; total: number }) {
  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
      <div style={{
        flex: 1, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.08)',
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 2,
          background: 'linear-gradient(90deg, #ffaa44, #f0b060)',
          transition: 'width 0.3s ease',
        }} />
      </div>
      <span style={{ fontSize: 9, color: '#888' }}>{pct}%</span>
    </div>
  );
}

/* ── Task Card ── */
function TaskCard({ task }: { task: AgentTaskView }) {
  const [expanded, setExpanded] = useState(false);
  const deptColor = DEPT_COLORS[task.department?.toLowerCase()] || '#666';
  const statusColor = STATUS_COLORS[task.status] || '#888';
  const isWorking = task.status === 'working';

  async function handleAction(action: 'approve' | 'reject') {
    try {
      await fetch(`/api/build/queue/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ build_id: task.id }),
      });
    } catch { /* swallow — backend unavailable */ }
  }

  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{
        marginBottom: 6,
        padding: '6px 8px 6px 12px',
        borderRadius: 6,
        background: 'rgba(255,255,255,0.03)',
        borderLeft: `3px solid ${deptColor}`,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.06)'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.background = 'rgba(255,255,255,0.03)'; }}
    >
      {/* Row 1: status dot + type badge + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: statusColor, display: 'inline-block', flexShrink: 0,
          animation: isWorking ? 'neural-pulse 2s ease-in-out infinite' : 'none',
        }} />
        <span style={{
          fontSize: 8, fontWeight: 700, textTransform: 'uppercase' as const,
          letterSpacing: 1, color: '#666', flexShrink: 0,
        }}>
          {task.type}
        </span>
        <span style={{ fontSize: 11, color: '#ddd', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {expanded ? task.title : truncate(task.title, 50)}
        </span>
      </div>

      {/* Row 2: agent · department · elapsed · AD */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3, fontSize: 10, color: '#888' }}>
        <span>{task.agent_type}</span>
        <span style={{ color: '#555' }}>{'\u00B7'}</span>
        <span style={{ textTransform: 'capitalize' as const }}>{task.department}</span>
        {task.started_at > 0 && (
          <>
            <span style={{ color: '#555' }}>{'\u00B7'}</span>
            <span>{formatElapsed(task.started_at)}</span>
          </>
        )}
        {task.ad_number > 0 && (
          <span style={{ color: deptColor, fontWeight: 600 }}>AD-{task.ad_number}</span>
        )}
      </div>

      {/* Compact progress for working tasks */}
      {!expanded && isWorking && task.step_total > 0 && (
        <div style={{ marginTop: 3, fontSize: 9, color: '#888' }}>
          step {task.step_current}/{task.step_total}
          <ProgressBar current={task.step_current} total={task.step_total} />
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div style={{ marginTop: 6 }} onClick={e => e.stopPropagation()}>
          {/* Step checklist */}
          {task.steps && task.steps.length > 0 && (
            <>
              <StepList steps={task.steps} />
              {task.step_total > 0 && (
                <ProgressBar current={task.step_current} total={task.step_total} />
              )}
            </>
          )}

          {/* Error for failed tasks */}
          {task.status === 'failed' && task.error && (
            <div style={{ marginTop: 6, fontSize: 10, color: '#ff7777', background: 'rgba(255,80,80,0.08)', padding: '4px 6px', borderRadius: 4 }}>
              {truncate(task.error, 200)}
            </div>
          )}

          {/* Metadata */}
          {task.metadata && Object.keys(task.metadata).length > 0 && (
            <div style={{ marginTop: 6, fontSize: 9, color: '#666' }}>
              {Object.entries(task.metadata).map(([k, v]) => (
                <div key={k}><span style={{ color: '#888' }}>{k}:</span> {String(v)}</div>
              ))}
            </div>
          )}

          {/* Action buttons */}
          {task.requires_action && (
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              <button
                onClick={() => handleAction('approve')}
                style={{
                  flex: 1, padding: '4px 0', borderRadius: 4, border: 'none',
                  background: 'rgba(80, 200, 120, 0.2)', color: '#50c878',
                  fontSize: 10, fontWeight: 600, cursor: 'pointer',
                }}
              >
                Approve
              </button>
              <button
                onClick={() => handleAction('reject')}
                style={{
                  flex: 1, padding: '4px 0', borderRadius: 4, border: 'none',
                  background: 'rgba(255, 85, 85, 0.15)', color: '#ff5555',
                  fontSize: 10, fontWeight: 600, cursor: 'pointer',
                }}
              >
                Reject
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Main Drawer ── */
export function ActivityDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const agentTasks = useStore((s) => s.agentTasks);
  const tasks = agentTasks ?? [];

  const needsAttention = tasks.filter(t => t.requires_action);
  const active = tasks.filter(t => t.status === 'working');
  const recent = tasks
    .filter(t => t.status === 'done' || t.status === 'failed')
    .sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0))
    .slice(0, 10);

  return (
    <div style={{
      position: 'fixed',
      top: 0, right: 0, bottom: 0,
      width: 320,
      background: 'rgba(10, 10, 18, 0.92)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(100%)',
      transition: 'transform 0.25s ease-out',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: "'JetBrains Mono', monospace",
      pointerEvents: open ? 'auto' : 'none',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 12px 10px',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <span style={{
          fontSize: 11, fontWeight: 700, letterSpacing: 2,
          textTransform: 'uppercase' as const, color: '#f0b060',
        }}>
          Activity
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', color: '#888',
            fontSize: 16, cursor: 'pointer', padding: '0 4px',
            lineHeight: 1,
          }}
        >
          {'\u00D7'}
        </button>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        {/* Needs Attention */}
        <SectionHeader
          label="Needs Attention"
          count={needsAttention.length}
          color={needsAttention.length > 0 ? '#f0b060' : '#888'}
          defaultOpen={true}
        >
          {needsAttention.length === 0
            ? <div style={{ fontSize: 10, color: '#555', fontStyle: 'italic', padding: '4px 0' }}>No tasks need attention</div>
            : needsAttention.map(t => <TaskCard key={t.id} task={t} />)
          }
        </SectionHeader>

        {/* Active */}
        <SectionHeader label="Active" count={active.length} color="#888" defaultOpen={true}>
          {active.length === 0
            ? <div style={{ fontSize: 10, color: '#555', fontStyle: 'italic', padding: '4px 0' }}>No active tasks</div>
            : active.map(t => <TaskCard key={t.id} task={t} />)
          }
        </SectionHeader>

        {/* Recent */}
        <SectionHeader label="Recent" count={recent.length} color="#888" defaultOpen={false}>
          {recent.length === 0
            ? <div style={{ fontSize: 10, color: '#555', fontStyle: 'italic', padding: '4px 0' }}>No recent tasks</div>
            : recent.map(t => <TaskCard key={t.id} task={t} />)
          }
        </SectionHeader>
      </div>
    </div>
  );
}
