/* Bridge Kanban — compact inline kanban for Bridge sidebar (AD-325) */

import { useMemo } from 'react';

import { useStore } from '../../store/useStore';
import { useWorkItemInterest, useWorkItemScopes } from '../../store/workItemReconciliation';
import { formatWorkItemCount, summarizeWorkItems } from '../../store/workItemSummary';
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
  const workItems = useStore(s => s.workItems);
  // Issue #1375: the open Operations station keeps the work-item population loaded.
  useWorkItemInterest();
  const scopes = useWorkItemScopes();
  const summary = useMemo(() => summarizeWorkItems(workItems ?? [], scopes), [workItems, scopes]);

  // The build pipeline keeps its population; done and failed builds sit in their own columns.
  const columns = [
    { key: 'queued', label: 'Q', items: tasks.filter(t => t.status === 'queued') },
    { key: 'working', label: 'W', items: tasks.filter(t => t.status === 'working') },
    { key: 'review', label: 'R', items: tasks.filter(t => t.status === 'review') },
    { key: 'done', label: 'D', items: tasks.filter(t => t.status === 'done') },
    { key: 'failed', label: 'F', items: tasks.filter(t => t.status === 'failed') },
  ];

  return (
    <div>
      <div role="group" aria-label="Work items" style={{ marginBottom: 8 }}>
        <div style={SECTION_LABEL}>Work items</div>
        <div style={{ fontSize: 9, color: '#ccc' }}>
          <span data-testid="bridge-work-not-done">{formatWorkItemCount(summary, 'notDone')}</span> not done
          {' \u00b7 '}<span data-testid="bridge-work-failed">{formatWorkItemCount(summary, 'failed')}</span> failed
          {' \u00b7 '}<span data-testid="bridge-work-blocked">{formatWorkItemCount(summary, 'blocked')}</span> blocked
        </div>
        <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>
          Conversation continuations:{' '}
          <span data-testid="bridge-work-continuations-not-done">
            {formatWorkItemCount(summary, 'notDone', summary.continuations.notDone)}
          </span> not done, <span data-testid="bridge-work-continuations-failed">
            {formatWorkItemCount(summary, 'failed', summary.continuations.failed)}
          </span> failed
        </div>
      </div>
      <div role="group" aria-label="Build pipeline">
        <div style={SECTION_LABEL}>Build pipeline</div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${columns.length}, 1fr)`,
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
                <span data-testid={`build-pipeline-${col.key}-count`} style={{
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
      </div>
    </div>
  );
}

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 9, fontWeight: 700, letterSpacing: 1, textTransform: 'uppercase', color: '#666', marginBottom: 4,
};
