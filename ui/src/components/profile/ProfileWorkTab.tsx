/* Profile Work Tab — agent's work items, bookings, duty schedule (AD-497) */

import { useState, useEffect, useCallback } from 'react';
import { useStore } from '../../store/useStore';
import type { WorkItemView, BookingView, BookableResourceView } from '../../store/types';

const PRIORITY_COLORS: Record<number, string> = {
  1: '#d05050', 2: '#e08040', 3: '#d0b050', 4: '#5090d0', 5: '#888',
};
const STATUS_COLORS: Record<string, string> = {
  open: '#8888a0', scheduled: '#50a0d0', in_progress: '#50b0a0',
  review: '#f0b060', done: '#80c878', failed: '#d05050',
  cancelled: '#666', blocked: '#d07050', draft: '#666680',
};

function formatElapsed(ts: number): string {
  const sec = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.floor(min / 60)}h ${min % 60}m ago`;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return `${n}`;
}

interface Props { agentId: string }

export function ProfileWorkTab({ agentId }: Props) {
  const workItems = useStore(s => s.workItems);
  const workBookings = useStore(s => s.workBookings);
  const bookableResources = useStore(s => s.bookableResources);
  const agents = useStore(s => s.agents);
  const scheduledTasks = useStore(s => s.scheduledTasks);
  const moveWorkItem = useStore(s => s.moveWorkItem);
  const assignWorkItem = useStore(s => s.assignWorkItem);
  const createWorkItem = useStore(s => s.createWorkItem);

  const [showCreate, setShowCreate] = useState(false);
  const [createTitle, setCreateTitle] = useState('');
  const [createPriority, setCreatePriority] = useState(3);
  const [completedItems, setCompletedItems] = useState<WorkItemView[]>([]);
  const [sectionsOpen, setSectionsOpen] = useState<Record<string, boolean>>({
    active: true, blocked: true, completed: false, duty: true,
  });
  const [reassignItem, setReassignItem] = useState<string | null>(null);

  // Find UUID for this agent (bookable resources use UUID as resource_id)
  const agentResource = (bookableResources ?? []).find(r =>
    r.agent_type === agents.get(agentId)?.agentType
  );
  const agentUuid = agentResource?.resource_id ?? agentId;

  const myItems = (workItems ?? []).filter(w => w.assigned_to === agentUuid);
  const activeItems = myItems.filter(w => ['open', 'scheduled', 'in_progress', 'review'].includes(w.status));
  const blockedItems = myItems.filter(w => ['failed', 'blocked'].includes(w.status));
  const myBookings = (workBookings ?? []).filter(b => b.resource_id === agentUuid);

  // Fetch completed items on mount
  useEffect(() => {
    fetch(`/api/work-items?assigned_to=${agentUuid}&status=done&limit=10`)
      .then(r => r.ok ? r.json() : { work_items: [] })
      .then(d => setCompletedItems(d.work_items || []))
      .catch(() => {});
  }, [agentUuid]);

  const toggle = (section: string) => setSectionsOpen(s => ({ ...s, [section]: !s[section] }));

  const handleCreate = useCallback(async () => {
    if (!createTitle.trim()) return;
    await createWorkItem({ title: createTitle.trim(), priority: createPriority, work_type: 'task', assigned_to: agentUuid });
    setCreateTitle('');
    setCreatePriority(3);
    setShowCreate(false);
  }, [createTitle, createPriority, agentUuid, createWorkItem]);

  const getBooking = (itemId: string): BookingView | undefined =>
    myBookings.find(b => b.work_item_id === itemId && b.status === 'active');

  // Duty schedule from scheduledTasks
  const dutyItems = (scheduledTasks ?? []).filter(t => {
    // Filter by agent if the task has an associated channel or agent
    return true; // Show all duties for now — agent filtering can be refined
  });

  const availableAgents = (bookableResources ?? []).filter(r => r.active && r.display_on_board);

  const cardStyle = {
    marginBottom: 6, padding: '7px 9px',
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: 6, fontSize: 11,
  };

  const sectionHeader = (label: string, count: number, key: string) => (
    <div
      onClick={() => toggle(key)}
      style={{
        cursor: 'pointer', padding: '5px 0', fontSize: 11, fontWeight: 600,
        color: '#8888a0', display: 'flex', alignItems: 'center', gap: 4,
        userSelect: 'none', marginTop: key === 'active' ? 0 : 8,
      }}
    >
      <span style={{ fontSize: 8 }}>{sectionsOpen[key] ? '▼' : '▶'}</span>
      {label} ({count})
    </div>
  );

  const renderCard = (item: WorkItemView, showActions = false) => {
    const booking = getBooking(item.id);
    const stepsComplete = item.steps.filter(s => s.status === 'completed').length;
    return (
      <div key={item.id} style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: PRIORITY_COLORS[item.priority] || '#888', display: 'inline-block', flexShrink: 0 }} />
            <span style={{ fontWeight: 600, color: '#c8d0e0' }}>
              {item.title.length > 35 ? item.title.slice(0, 35) + '\u2026' : item.title}
            </span>
          </div>
          <span style={{
            fontSize: 9, padding: '1px 5px', borderRadius: 3,
            background: 'rgba(255,255,255,0.05)',
            color: STATUS_COLORS[item.status] || '#8888a0',
          }}>{item.status.replace('_', ' ')}</span>
        </div>
        <div style={{ color: '#666680', fontSize: 10, display: 'flex', gap: 8 }}>
          {booking && <span>{formatTokens(booking.total_tokens_consumed)} tokens</span>}
          {item.work_type !== 'task' && (
            <span style={{ padding: '0 4px', background: 'rgba(80,144,208,0.15)', borderRadius: 2, color: '#5090d0' }}>
              {item.work_type}
            </span>
          )}
        </div>
        {item.steps.length > 0 && (
          <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.06)', marginTop: 4, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${(stepsComplete / item.steps.length) * 100}%`,
              background: STATUS_COLORS[item.status] || '#5090d0', borderRadius: 2, transition: 'width 0.3s ease',
            }} />
          </div>
        )}
        {showActions && (
          <div style={{ marginTop: 5, display: 'flex', gap: 4 }}>
            <button onClick={() => setReassignItem(reassignItem === item.id ? null : item.id)} style={actionBtnStyle}>Reassign</button>
            <button onClick={() => moveWorkItem(item.id, 'cancelled')} style={actionBtnStyle}>Cancel</button>
            {item.status === 'failed' && <button onClick={() => moveWorkItem(item.id, 'open')} style={actionBtnStyle}>Retry</button>}
          </div>
        )}
        {reassignItem === item.id && (
          <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 3 }}>
            {availableAgents.filter(a => a.resource_id !== agentUuid).map(a => (
              <button key={a.resource_id} onClick={() => { assignWorkItem(item.id, a.resource_id); setReassignItem(null); }}
                style={{ ...actionBtnStyle, fontSize: 9 }}>
                {a.callsign || a.agent_type}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  const actionBtnStyle: React.CSSProperties = {
    padding: '2px 6px', fontSize: 9, borderRadius: 3, cursor: 'pointer',
    background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
    color: '#aaa',
  };

  return (
    <div style={{ padding: '8px 12px', overflowY: 'auto', height: '100%' }}>
      {/* Create button */}
      <div style={{ marginBottom: 6 }}>
        {!showCreate ? (
          <button onClick={() => setShowCreate(true)} style={{
            padding: '3px 8px', fontSize: 10, borderRadius: 4, cursor: 'pointer',
            background: 'rgba(80,176,160,0.15)', border: '1px solid rgba(80,176,160,0.3)', color: '#50b0a0',
          }}>+ Create Task</button>
        ) : (
          <div style={{ ...cardStyle, background: 'rgba(80,176,160,0.05)', border: '1px solid rgba(80,176,160,0.2)' }}>
            <input
              value={createTitle} onChange={e => setCreateTitle(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder="Task title..."
              autoFocus
              style={{
                width: '100%', padding: '3px 6px', fontSize: 11, borderRadius: 3,
                background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)',
                color: '#c8d0e0', outline: 'none', marginBottom: 4, boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <select value={createPriority} onChange={e => setCreatePriority(Number(e.target.value))}
                style={{ fontSize: 10, padding: '2px 4px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa', borderRadius: 3 }}>
                {[1,2,3,4,5].map(p => <option key={p} value={p}>P{p}</option>)}
              </select>
              <button onClick={handleCreate} style={{ ...actionBtnStyle, color: '#50b0a0', borderColor: 'rgba(80,176,160,0.3)' }}>Create</button>
              <button onClick={() => setShowCreate(false)} style={actionBtnStyle}>Cancel</button>
            </div>
          </div>
        )}
      </div>

      {/* Active Work */}
      {sectionHeader('Active Work', activeItems.length, 'active')}
      {sectionsOpen.active && (activeItems.length > 0
        ? activeItems.map(item => renderCard(item))
        : <div style={{ color: '#444', fontSize: 10, padding: '4px 0' }}>No active work</div>
      )}

      {/* Blocked */}
      {blockedItems.length > 0 && (
        <>
          {sectionHeader('Blocked', blockedItems.length, 'blocked')}
          {sectionsOpen.blocked && blockedItems.map(item => renderCard(item, true))}
        </>
      )}

      {/* Completed */}
      {sectionHeader('Completed', completedItems.length, 'completed')}
      {sectionsOpen.completed && (completedItems.length > 0
        ? completedItems.map(item => (
            <div key={item.id} style={cardStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: '#80c878', fontSize: 10 }}>&#10003;</span>
                  <span style={{ color: '#8888a0' }}>{item.title.length > 35 ? item.title.slice(0, 35) + '\u2026' : item.title}</span>
                </div>
                <span style={{ color: '#555', fontSize: 9 }}>{formatElapsed(item.updated_at)}</span>
              </div>
            </div>
          ))
        : <div style={{ color: '#444', fontSize: 10, padding: '4px 0' }}>No completed items</div>
      )}

      {/* Duty Schedule */}
      {dutyItems.length > 0 && (
        <>
          {sectionHeader('Duty Schedule', dutyItems.length, 'duty')}
          {sectionsOpen.duty && dutyItems.map((t, i) => (
            <div key={i} style={{ ...cardStyle, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: '#666', fontSize: 10, fontFamily: 'monospace' }}>
                  {t.next_run_at ? new Date(t.next_run_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'}
                </span>
                <span style={{ color: '#aaa' }}>{t.name}</span>
              </div>
              <span style={{ fontSize: 10 }}>
                {t.status === 'completed' ? <span style={{ color: '#80c878' }}>&#10003;</span>
                  : t.status === 'running' ? <span style={{ color: '#f0b060' }}>&#9203;</span>
                  : <span style={{ color: '#555' }}>&middot;</span>}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
