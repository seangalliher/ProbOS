/* Mission Control — Captain's Kanban Dashboard (AD-322) */

import { useStore } from '../store/useStore';
import type { MissionControlTask } from '../store/types';

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

function elapsedTime(task: MissionControlTask): string {
  if (task.started_at <= 0) return '';
  const end = task.completed_at > 0 ? task.completed_at : Date.now() / 1000;
  const secs = Math.floor(end - task.started_at);
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

const STATUS_COLORS: Record<string, string> = {
  queued: '#555566',
  working: '#ffaa44',
  review: '#66ccff',
  done: '#50c878',
  failed: '#ff5555',
};

function TaskCard({ task }: { task: MissionControlTask }) {
  const deptColor = DEPT_COLORS[task.department] || '#888';

  return (
    <div style={{
      background: 'rgba(255, 255, 255, 0.03)',
      border: '1px solid rgba(255, 255, 255, 0.06)',
      borderLeft: `3px solid ${deptColor}`,
      borderRadius: 6,
      padding: '8px 10px',
      marginBottom: 6,
      fontSize: 11,
      color: '#e0dcd4',
    }}>
      {/* Title line */}
      <div style={{ fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: STATUS_COLORS[task.status] || '#555',
          ...(task.status === 'working' ? { animation: 'neural-pulse 1.4s ease-in-out infinite' } : {}),
        }} />
        {task.ad_number > 0 && (
          <span style={{ color: deptColor, fontSize: 10 }}>AD-{task.ad_number}</span>
        )}
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {task.title.slice(0, 40)}
        </span>
      </div>
      {/* Meta line */}
      <div style={{ fontSize: 9, color: '#888', display: 'flex', gap: 8, marginLeft: 12 }}>
        <span>{task.agent_type}</span>
        {task.started_at > 0 && <span>{elapsedTime(task)}</span>}
        <span style={{ marginLeft: 'auto', textTransform: 'capitalize' }}>{task.department}</span>
      </div>
      {/* Action buttons for review status */}
      {task.status === 'review' && (
        <div style={{ marginTop: 6, display: 'flex', gap: 6, marginLeft: 12 }}>
          <button
            style={{
              padding: '2px 8px', borderRadius: 4,
              border: '1px solid rgba(80, 200, 120, 0.3)',
              background: 'rgba(80, 200, 120, 0.15)',
              color: '#50c878', fontSize: 10, fontWeight: 600, cursor: 'pointer',
            }}
            onClick={async () => {
              try {
                await fetch('/api/build/queue/approve', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ build_id: task.id }),
                });
              } catch { /* ignore */ }
            }}
          >
            Approve
          </button>
          <button
            style={{
              padding: '2px 8px', borderRadius: 4,
              border: '1px solid rgba(255, 85, 85, 0.3)',
              background: 'rgba(255, 85, 85, 0.15)',
              color: '#ff5555', fontSize: 10, fontWeight: 600, cursor: 'pointer',
            }}
            onClick={async () => {
              try {
                await fetch('/api/build/queue/reject', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ build_id: task.id }),
                });
              } catch { /* ignore */ }
            }}
          >
            Reject
          </button>
        </div>
      )}
      {/* Error for failed */}
      {task.status === 'failed' && task.error && (
        <div style={{ color: '#ff5555', fontSize: 9, marginTop: 4, marginLeft: 12 }}>
          {task.error.slice(0, 80)}
        </div>
      )}
    </div>
  );
}

export function MissionControl() {
  const tasks = useStore(s => s.missionControlTasks) || [];

  const columns = [
    { key: 'queued', label: 'QUEUED', items: tasks.filter(t => t.status === 'queued') },
    { key: 'working', label: 'WORKING', items: tasks.filter(t => t.status === 'working') },
    { key: 'review', label: 'REVIEW', items: tasks.filter(t => t.status === 'review') },
    { key: 'done', label: 'DONE', items: tasks.filter(t => t.status === 'done' || t.status === 'failed') },
  ];

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 15,
      background: '#0a0a12',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid rgba(208, 160, 48, 0.15)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        <span style={{
          color: '#d0a030', fontSize: 12, fontWeight: 700,
          letterSpacing: 2, textTransform: 'uppercase',
        }}>
          Mission Control
        </span>
        <span style={{ color: '#555', fontSize: 10 }}>
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Kanban columns */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 12,
        padding: 16,
        flex: 1,
        overflow: 'hidden',
      }}>
        {columns.map(col => (
          <div key={col.key} style={{
            background: 'rgba(255, 255, 255, 0.01)',
            borderRadius: 8,
            padding: 10,
            overflow: 'auto',
            display: 'flex',
            flexDirection: 'column',
          }}>
            {/* Column header */}
            <div style={{
              textTransform: 'uppercase',
              letterSpacing: 2,
              fontSize: 10,
              color: '#888',
              marginBottom: 10,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexShrink: 0,
            }}>
              {col.label}
              <span style={{
                background: col.items.length > 0 ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.04)',
                borderRadius: '50%',
                width: 18, height: 18,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 9,
                color: col.items.length > 0 ? '#e0dcd4' : '#555',
              }}>{col.items.length}</span>
            </div>
            {/* Cards */}
            <div style={{ flex: 1, overflow: 'auto' }}>
              {col.items.map(task => <TaskCard key={task.id} task={task} />)}
              {col.items.length === 0 && (
                <div style={{
                  color: '#333', fontSize: 10, textAlign: 'center',
                  padding: '20px 0', fontStyle: 'italic',
                }}>
                  No tasks
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
