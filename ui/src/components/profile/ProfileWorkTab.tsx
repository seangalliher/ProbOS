import { useStore } from '../../store/useStore';

const STATUS_COLORS: Record<string, string> = {
  working: '#50b0a0',
  review: '#f0b060',
  queued: '#8888a0',
  done: '#80c878',
  failed: '#d05050',
};

function formatElapsed(startedAt: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - startedAt));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

interface Props {
  agentId: string;
}

export function ProfileWorkTab({ agentId }: Props) {
  const agentTasks = useStore((s) => s.agentTasks);

  const tasks = (agentTasks ?? []).filter(t => t.agent_id === agentId);

  if (tasks.length === 0) {
    return (
      <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40, padding: '0 20px' }}>
        No active tasks assigned to this agent.
      </div>
    );
  }

  return (
    <div style={{ padding: '8px 12px', overflowY: 'auto', height: '100%' }}>
      {tasks.map(task => (
        <div key={task.id} style={{
          marginBottom: 8,
          padding: '8px 10px',
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 6,
          fontSize: 12,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontWeight: 600, color: '#c8d0e0' }}>
              {task.title.length > 40 ? task.title.slice(0, 40) + '\u2026' : task.title}
            </span>
            <span style={{ color: STATUS_COLORS[task.status] || '#8888a0', fontSize: 10 }}>
              {task.status}
            </span>
          </div>
          {task.step_total > 0 && (
            <div style={{ color: '#8888a0', fontSize: 10, marginBottom: 4 }}>
              Step {task.step_current} of {task.step_total}
              {task.steps?.[task.step_current - 1]?.label && `: ${task.steps[task.step_current - 1].label}`}
            </div>
          )}
          {task.started_at > 0 && (
            <div style={{ color: '#666680', fontSize: 10 }}>
              Elapsed: {formatElapsed(task.started_at)}
            </div>
          )}
          {task.step_total > 0 && (
            <div style={{
              height: 3, borderRadius: 2,
              background: 'rgba(255,255,255,0.06)',
              marginTop: 4, overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${(task.step_current / task.step_total) * 100}%`,
                background: STATUS_COLORS[task.status] || '#5090d0',
                borderRadius: 2,
                transition: 'width 0.3s ease',
              }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
