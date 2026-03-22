/* Bridge Kanban — compact inline kanban for Bridge sidebar (AD-325) */

import { useStore } from '../../store/useStore';
import { STATUS_COLORS, DEPT_COLORS } from './BridgeCards';
import type { MissionControlTask } from '../../store/types';

function CompactCard({ task }: { task: MissionControlTask }) {
  const deptColor = DEPT_COLORS[task.department] || '#888';
  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)',
      borderLeft: `2px solid ${deptColor}`,
      borderRadius: 4,
      padding: '3px 6px',
      marginBottom: 3,
      fontSize: 9,
      color: '#ccc',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
        background: STATUS_COLORS[task.status] || '#555',
        ...(task.status === 'working' ? { animation: 'neural-pulse 1.4s ease-in-out infinite' } : {}),
      }} />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
        {task.title.slice(0, 30)}
      </span>
      {task.ad_number > 0 && (
        <span style={{ color: '#888', fontSize: 8, flexShrink: 0 }}>AD-{task.ad_number}</span>
      )}
    </div>
  );
}

export function BridgeKanban() {
  const tasks = useStore(s => s.missionControlTasks) || [];

  const columns = [
    { key: 'queued', label: 'Q', items: tasks.filter(t => t.status === 'queued') },
    { key: 'working', label: 'W', items: tasks.filter(t => t.status === 'working') },
    { key: 'review', label: 'R', items: tasks.filter(t => t.status === 'review') },
    { key: 'done', label: 'D', items: tasks.filter(t => t.status === 'done' || t.status === 'failed') },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 4,
    }}>
      {columns.map(col => (
        <div key={col.key}>
          <div style={{
            fontSize: 9, fontWeight: 700, letterSpacing: 1,
            textTransform: 'uppercase' as const, color: '#888',
            marginBottom: 4, display: 'flex', justifyContent: 'space-between',
          }}>
            {col.label}
            <span style={{
              fontSize: 8, color: col.items.length > 0 ? '#ccc' : '#444',
            }}>{col.items.length}</span>
          </div>
          {col.items.slice(0, 5).map(t => <CompactCard key={t.id} task={t} />)}
          {col.items.length > 5 && (
            <div style={{ fontSize: 8, color: '#555', textAlign: 'center' }}>
              +{col.items.length - 5} more
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
