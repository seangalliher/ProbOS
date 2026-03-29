/* Crew Scrumban Board — full-page workforce view (AD-497) */

import { useState, useEffect, useCallback, useMemo, DragEvent } from 'react';
import { useStore } from '../../store/useStore';
import type { WorkItemView, BookableResourceView, WorkItemTemplateView } from '../../store/types';

// ── Column config ──────────────────────────────────────────────────
type ColKey = 'backlog' | 'ready' | 'in_progress' | 'review' | 'done';

interface ColConfig {
  key: ColKey;
  label: string;
  statuses: string[];
  targetStatus: string;   // status to set on drop
  wipLimit: number | null; // null = no limit
}

const COLUMNS: ColConfig[] = [
  { key: 'backlog',     label: 'BACKLOG',     statuses: ['draft', 'open'], targetStatus: 'open',        wipLimit: null },
  { key: 'ready',       label: 'READY',       statuses: ['scheduled'],     targetStatus: 'scheduled',   wipLimit: null },
  { key: 'in_progress', label: 'IN PROGRESS', statuses: ['in_progress'],   targetStatus: 'in_progress', wipLimit: 10 },
  { key: 'review',      label: 'REVIEW',      statuses: ['review'],        targetStatus: 'review',      wipLimit: 5 },
  { key: 'done',        label: 'DONE',        statuses: ['done'],          targetStatus: 'done',        wipLimit: null },
];

const PRIORITY_COLORS: Record<number, string> = {
  1: '#d05050', 2: '#e08040', 3: '#d0b050', 4: '#5090d0', 5: '#888',
};

const WORK_TYPE_COLORS: Record<string, string> = {
  card: '#8888a0', task: '#5090d0', work_order: '#9070c0', duty: '#50b0a0', incident: '#d05050',
};

type SwimLane = 'none' | 'department' | 'priority' | 'agent';

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}K`;
  return `${n}`;
}

function relTime(ts: number): string {
  const diff = ts - Date.now() / 1000;
  const abs = Math.abs(diff);
  if (abs < 3600) return `${Math.round(abs / 60)}m`;
  if (abs < 86400) return `${Math.round(abs / 3600)}h`;
  return `${Math.round(abs / 86400)}d`;
}

// ── Work Card ──────────────────────────────────────────────────────
function WorkCard({ item, resources, onDragStart }: {
  item: WorkItemView;
  resources: BookableResourceView[];
  onDragStart: (e: DragEvent, id: string) => void;
}) {
  const agent = resources.find(r => r.resource_id === item.assigned_to);
  const stepsComplete = item.steps.filter(s => s.status === 'completed').length;
  const overdue = item.due_at && item.due_at < Date.now() / 1000;

  return (
    <div
      draggable
      onDragStart={e => onDragStart(e, item.id)}
      style={{
        padding: '7px 9px', marginBottom: 4, borderRadius: 5, cursor: 'grab',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.07)',
        fontSize: 11, transition: 'opacity 0.15s',
      }}
    >
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4, marginBottom: 3 }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', flexShrink: 0, marginTop: 2,
          background: PRIORITY_COLORS[item.priority] || '#888', display: 'inline-block',
        }} />
        <span style={{ fontWeight: 600, color: '#c8d0e0', lineHeight: 1.25, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
          {item.title}
        </span>
      </div>

      {/* Meta row */}
      <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{
          fontSize: 9, padding: '0 4px', borderRadius: 2,
          background: `${(WORK_TYPE_COLORS[item.work_type] || '#888')}20`,
          color: WORK_TYPE_COLORS[item.work_type] || '#888',
        }}>{item.work_type}</span>
        {agent ? (
          <span style={{ fontSize: 9, color: '#8888a0', display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#50b0a0', display: 'inline-block' }} />
            {agent.callsign || agent.agent_type}
          </span>
        ) : (
          <span style={{ fontSize: 9, color: '#555' }}>Unassigned</span>
        )}
        {item.estimated_tokens > 0 && (
          <span style={{ fontSize: 9, color: '#666' }}>{formatTokens(item.estimated_tokens)} &#8859;</span>
        )}
        {item.due_at && (
          <span style={{ fontSize: 9, color: overdue ? '#d05050' : '#8888a0' }}>
            {overdue ? 'overdue ' : 'in '}{relTime(item.due_at)}
          </span>
        )}
      </div>

      {/* Tags */}
      {item.tags.length > 0 && (
        <div style={{ display: 'flex', gap: 3, marginTop: 3, flexWrap: 'wrap' }}>
          {item.tags.slice(0, 3).map(t => (
            <span key={t} style={{ fontSize: 8, padding: '0 3px', borderRadius: 2, background: 'rgba(255,255,255,0.06)', color: '#777' }}>{t}</span>
          ))}
          {item.tags.length > 3 && <span style={{ fontSize: 8, color: '#555' }}>+{item.tags.length - 3}</span>}
        </div>
      )}

      {/* Step progress bar */}
      {item.steps.length > 0 && (
        <div style={{ height: 2, borderRadius: 1, background: 'rgba(255,255,255,0.06)', marginTop: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%', width: `${(stepsComplete / item.steps.length) * 100}%`,
            background: '#50b0a0', borderRadius: 1, transition: 'width 0.3s ease',
          }} />
        </div>
      )}
    </div>
  );
}

// ── Main Board ─────────────────────────────────────────────────────
export default function WorkBoard() {
  const workItems = useStore(s => s.workItems);
  const bookableResources = useStore(s => s.bookableResources);
  const workTemplates = useStore(s => s.workTemplates);
  const moveWorkItem = useStore(s => s.moveWorkItem);
  const createWorkItem = useStore(s => s.createWorkItem);
  const assignWorkItem = useStore(s => s.assignWorkItem);
  const createFromTemplate = useStore(s => s.createFromTemplate);
  const fetchWorkTemplates = useStore(s => s.fetchWorkTemplates);

  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<ColKey | null>(null);
  const [swimLane, setSwimLane] = useState<SwimLane>('none');
  const [showFilters, setShowFilters] = useState(false);
  const [filterDepts, setFilterDepts] = useState<Set<string>>(new Set());
  const [filterAgents, setFilterAgents] = useState<Set<string>>(new Set());
  const [filterPriorities, setFilterPriorities] = useState<Set<number>>(new Set());
  const [filterTypes, setFilterTypes] = useState<Set<string>>(new Set());
  const [showQuickCreate, setShowQuickCreate] = useState(false);
  const [quickTitle, setQuickTitle] = useState('');
  const [quickPriority, setQuickPriority] = useState(3);
  const [wipWarning, setWipWarning] = useState<string | null>(null);
  const [showBlocked, setShowBlocked] = useState(false);
  const [quickWorkType, setQuickWorkType] = useState('card');
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<WorkItemTemplateView | null>(null);
  const [templateVars, setTemplateVars] = useState<Record<string, string>>({});

  // Fetch done items on mount
  const [doneItems, setDoneItems] = useState<WorkItemView[]>([]);
  useEffect(() => {
    fetch('/api/work-items?status=done&limit=20')
      .then(r => r.ok ? r.json() : { work_items: [] })
      .then(d => setDoneItems(d.work_items || []))
      .catch(() => {});
    if (!workTemplates) fetchWorkTemplates();
  }, []);

  const allItems = useMemo(() => {
    const active = workItems ?? [];
    // Merge done items that aren't already in the live list
    const activeIds = new Set(active.map(i => i.id));
    const merged = [...active, ...doneItems.filter(d => !activeIds.has(d.id))];
    return merged;
  }, [workItems, doneItems]);

  const resources = bookableResources ?? [];

  // Filter logic
  const filtered = useMemo(() => {
    return allItems.filter(item => {
      if (filterPriorities.size > 0 && !filterPriorities.has(item.priority)) return false;
      if (filterTypes.size > 0 && !filterTypes.has(item.work_type)) return false;
      if (filterAgents.size > 0 && (!item.assigned_to || !filterAgents.has(item.assigned_to))) return false;
      if (filterDepts.size > 0) {
        const agent = resources.find(r => r.resource_id === item.assigned_to);
        if (!agent || !filterDepts.has(agent.department)) return false;
      }
      return true;
    });
  }, [allItems, filterPriorities, filterTypes, filterAgents, filterDepts, resources]);

  const blockedItems = filtered.filter(i => ['failed', 'cancelled', 'blocked'].includes(i.status));

  // Items per column
  const colItems = useMemo(() => {
    const map: Record<ColKey, WorkItemView[]> = { backlog: [], ready: [], in_progress: [], review: [], done: [] };
    for (const item of filtered) {
      for (const col of COLUMNS) {
        if (col.statuses.includes(item.status)) {
          if (col.key === 'done') {
            if (map.done.length < 20) map.done.push(item);
          } else {
            map[col.key].push(item);
          }
          break;
        }
      }
    }
    return map;
  }, [filtered]);

  // Swim lane grouping
  const lanes = useMemo(() => {
    if (swimLane === 'none') return [{ key: '__all', label: '', items: filtered }];
    const groups = new Map<string, WorkItemView[]>();
    for (const item of filtered) {
      let key = '';
      if (swimLane === 'department') {
        const agent = resources.find(r => r.resource_id === item.assigned_to);
        key = agent?.department || 'Unassigned';
      } else if (swimLane === 'priority') {
        key = `P${item.priority}`;
      } else if (swimLane === 'agent') {
        const agent = resources.find(r => r.resource_id === item.assigned_to);
        key = agent?.callsign || agent?.agent_type || 'Unassigned';
      }
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(item);
    }
    return Array.from(groups.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, items]) => ({ key, label: key, items }));
  }, [filtered, swimLane, resources]);

  // Unique departments and agents for filters
  const departments = useMemo(() => [...new Set(resources.map(r => r.department).filter(Boolean))].sort(), [resources]);
  const agentList = useMemo(() => resources.filter(r => r.active && r.display_on_board), [resources]);
  const workTypes = useMemo(() => [...new Set(allItems.map(i => i.work_type))].sort(), [allItems]);

  // Drag handlers
  const handleDragStart = useCallback((e: DragEvent, id: string) => {
    e.dataTransfer.setData('text/plain', id);
    setDragId(id);
  }, []);

  const handleDragOver = useCallback((e: DragEvent, col: ColKey) => {
    e.preventDefault();
    setDropTarget(col);
  }, []);

  const handleDrop = useCallback(async (e: DragEvent, col: ColConfig) => {
    e.preventDefault();
    setDropTarget(null);
    const itemId = e.dataTransfer.getData('text/plain');
    if (!itemId) return;
    setDragId(null);

    // WIP warning (soft limit)
    if (col.wipLimit && colItems[col.key].length >= col.wipLimit) {
      setWipWarning(`${col.label} is at WIP limit (${col.wipLimit})`);
      setTimeout(() => setWipWarning(null), 3000);
    }

    await moveWorkItem(itemId, col.targetStatus);
  }, [moveWorkItem, colItems]);

  const handleDragEnd = useCallback(() => {
    setDragId(null);
    setDropTarget(null);
  }, []);

  // Quick create
  const handleQuickCreate = useCallback(async () => {
    if (!quickTitle.trim()) return;
    await createWorkItem({ title: quickTitle.trim(), priority: quickPriority, work_type: quickWorkType });
    setQuickTitle('');
    setQuickPriority(3);
    setQuickWorkType('card');
    setShowQuickCreate(false);
  }, [quickTitle, quickPriority, quickWorkType, createWorkItem]);

  const handleTemplateCreate = useCallback(async () => {
    if (!selectedTemplate) return;
    await createFromTemplate(selectedTemplate.template_id, templateVars);
    setSelectedTemplate(null);
    setTemplateVars({});
    setShowTemplatePicker(false);
  }, [selectedTemplate, templateVars, createFromTemplate]);

  // Toggle filter set helpers
  const toggleSet = <T,>(setFn: React.Dispatch<React.SetStateAction<Set<T>>>, val: T) => {
    setFn(prev => {
      const next = new Set(prev);
      next.has(val) ? next.delete(val) : next.add(val);
      return next;
    });
  };

  if (!workItems && !doneItems.length) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#555568', fontSize: 13 }}>
        Workforce not enabled or no work items yet.
      </div>
    );
  }

  const renderColumn = (col: ColConfig, items: WorkItemView[]) => {
    const count = items.length;
    const atLimit = col.wipLimit !== null && count >= col.wipLimit;
    return (
      <div
        key={col.key}
        onDragOver={e => handleDragOver(e, col.key)}
        onDragLeave={() => setDropTarget(null)}
        onDrop={e => handleDrop(e, col)}
        style={{
          flex: 1, minWidth: 160, display: 'flex', flexDirection: 'column',
          background: dropTarget === col.key ? 'rgba(80,176,160,0.06)' : 'transparent',
          borderRadius: 6, transition: 'background 0.15s',
          borderRight: col.key !== 'done' ? '1px solid rgba(255,255,255,0.04)' : 'none',
        }}
      >
        {/* Column header */}
        <div style={{
          padding: '6px 8px', fontSize: 10, fontWeight: 700, letterSpacing: 0.8,
          color: atLimit ? '#d0b050' : '#8888a0', borderBottom: '1px solid rgba(255,255,255,0.06)',
          display: 'flex', justifyContent: 'space-between',
        }}>
          <span>{col.label}</span>
          <span style={{ fontWeight: 400, color: atLimit ? '#d0b050' : '#666' }}>
            {count}{col.wipLimit ? `/${col.wipLimit}` : ''}
          </span>
        </div>
        {/* Cards */}
        <div style={{ padding: '4px 6px', overflowY: 'auto', flex: 1, minHeight: 80 }}>
          {items.map(item => (
            <WorkCard key={item.id} item={item} resources={resources} onDragStart={handleDragStart} />
          ))}
        </div>
      </div>
    );
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', fontFamily: "'JetBrains Mono', monospace" }} onDragEnd={handleDragEnd}>
      {/* Toolbar */}
      <div style={{
        padding: '8px 16px', display: 'flex', alignItems: 'center', gap: 10,
        borderBottom: '1px solid rgba(255,255,255,0.06)', flexShrink: 0,
      }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#c8d0e0', letterSpacing: 1 }}>CREW WORK BOARD</span>
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowFilters(!showFilters)} style={toolbarBtn}>
          Filters {showFilters ? '▴' : '▾'}
        </button>
        <select value={swimLane} onChange={e => setSwimLane(e.target.value as SwimLane)} style={{ ...toolbarBtn, cursor: 'pointer' }}>
          <option value="none">No Swim Lanes</option>
          <option value="department">By Department</option>
          <option value="priority">By Priority</option>
          <option value="agent">By Agent</option>
        </select>
        <button onClick={() => setShowQuickCreate(!showQuickCreate)} style={{ ...toolbarBtn, color: '#50b0a0', borderColor: 'rgba(80,176,160,0.3)' }}>
          + Quick Create
        </button>
        <button onClick={() => setShowTemplatePicker(!showTemplatePicker)} style={{ ...toolbarBtn, color: '#9070c0', borderColor: 'rgba(144,112,192,0.3)' }}>
          From Template
        </button>
      </div>

      {/* WIP warning */}
      {wipWarning && (
        <div style={{ padding: '4px 16px', fontSize: 10, color: '#d0b050', background: 'rgba(208,176,80,0.08)' }}>
          &#9888; {wipWarning}
        </div>
      )}

      {/* Filter bar */}
      {showFilters && (
        <div style={{ padding: '6px 16px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 10 }}>
          {/* Department */}
          <div>
            <span style={{ color: '#8888a0', marginRight: 4 }}>Dept:</span>
            {departments.map(d => (
              <button key={d} onClick={() => toggleSet(setFilterDepts, d)}
                style={{ ...filterChip, background: filterDepts.has(d) ? 'rgba(80,144,208,0.2)' : 'rgba(255,255,255,0.04)', color: filterDepts.has(d) ? '#5090d0' : '#777' }}>
                {d}
              </button>
            ))}
          </div>
          {/* Agent */}
          <div>
            <span style={{ color: '#8888a0', marginRight: 4 }}>Agent:</span>
            {agentList.map(a => (
              <button key={a.resource_id} onClick={() => toggleSet(setFilterAgents, a.resource_id)}
                style={{ ...filterChip, background: filterAgents.has(a.resource_id) ? 'rgba(80,176,160,0.2)' : 'rgba(255,255,255,0.04)', color: filterAgents.has(a.resource_id) ? '#50b0a0' : '#777' }}>
                {a.callsign || a.agent_type}
              </button>
            ))}
          </div>
          {/* Priority */}
          <div>
            <span style={{ color: '#8888a0', marginRight: 4 }}>Priority:</span>
            {[1,2,3,4,5].map(p => (
              <button key={p} onClick={() => toggleSet(setFilterPriorities, p)}
                style={{ ...filterChip, background: filterPriorities.has(p) ? `${PRIORITY_COLORS[p]}30` : 'rgba(255,255,255,0.04)', color: filterPriorities.has(p) ? PRIORITY_COLORS[p] : '#777' }}>
                P{p}
              </button>
            ))}
          </div>
          {/* Work Type */}
          <div>
            <span style={{ color: '#8888a0', marginRight: 4 }}>Type:</span>
            {workTypes.map(t => (
              <button key={t} onClick={() => toggleSet(setFilterTypes, t)}
                style={{ ...filterChip, background: filterTypes.has(t) ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.04)', color: filterTypes.has(t) ? '#ccc' : '#777' }}>
                {t}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Quick create inline */}
      {showQuickCreate && (
        <div style={{ padding: '6px 16px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 6, alignItems: 'center' }}>
          <input value={quickTitle} onChange={e => setQuickTitle(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleQuickCreate()}
            placeholder="Card title..." autoFocus
            style={{ flex: 1, padding: '4px 8px', fontSize: 11, borderRadius: 4, background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#c8d0e0', outline: 'none' }}
          />
          <select value={quickWorkType} onChange={e => setQuickWorkType(e.target.value)}
            style={{ fontSize: 10, padding: '3px 4px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa', borderRadius: 3 }}>
            {['card', 'task', 'work_order', 'duty', 'incident'].map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={quickPriority} onChange={e => setQuickPriority(Number(e.target.value))}
            style={{ fontSize: 10, padding: '3px 4px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa', borderRadius: 3 }}>
            {[1,2,3,4,5].map(p => <option key={p} value={p}>P{p}</option>)}
          </select>
          <button onClick={handleQuickCreate} style={{ ...toolbarBtn, color: '#50b0a0' }}>Add</button>
          <button onClick={() => setShowQuickCreate(false)} style={toolbarBtn}>&#10005;</button>
        </div>
      )}

      {/* Template picker */}
      {showTemplatePicker && (
        <div style={{ padding: '6px 16px', borderBottom: '1px solid rgba(255,255,255,0.04)', fontSize: 11 }}>
          {!selectedTemplate ? (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {Object.entries(
                (workTemplates ?? []).reduce<Record<string, WorkItemTemplateView[]>>((acc, t) => {
                  (acc[t.category] = acc[t.category] || []).push(t);
                  return acc;
                }, {})
              ).map(([cat, templates]) => (
                <div key={cat} style={{ marginRight: 8 }}>
                  <div style={{ fontSize: 9, color: '#8888a0', fontWeight: 600, textTransform: 'uppercase', marginBottom: 2 }}>{cat}</div>
                  {templates.map(t => (
                    <button key={t.template_id} onClick={() => { setSelectedTemplate(t); setTemplateVars({}); }}
                      style={{ ...toolbarBtn, display: 'block', marginBottom: 2, color: '#c8d0e0', textAlign: 'left' }}>
                      {t.name}
                    </button>
                  ))}
                </div>
              ))}
              <button onClick={() => setShowTemplatePicker(false)} style={{ ...toolbarBtn, marginLeft: 'auto' }}>&#10005;</button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ color: '#9070c0', fontWeight: 600 }}>{selectedTemplate.name}</span>
              {selectedTemplate.variables.map(v => (
                <input key={v} placeholder={v} value={templateVars[v] || ''} onChange={e => setTemplateVars(prev => ({ ...prev, [v]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && handleTemplateCreate()}
                  style={{ padding: '3px 6px', fontSize: 11, borderRadius: 3, background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', color: '#c8d0e0', outline: 'none', width: 120 }}
                />
              ))}
              <button onClick={handleTemplateCreate} style={{ ...toolbarBtn, color: '#9070c0' }}>Create</button>
              <button onClick={() => setSelectedTemplate(null)} style={toolbarBtn}>Back</button>
              <button onClick={() => setShowTemplatePicker(false)} style={toolbarBtn}>&#10005;</button>
            </div>
          )}
        </div>
      )}

      {/* Board body */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
        {swimLane === 'none' ? (
          <div style={{ display: 'flex', height: '100%', minHeight: 200 }}>
            {COLUMNS.map(col => renderColumn(col, colItems[col.key]))}
          </div>
        ) : (
          lanes.map(lane => {
            // Per-lane column breakdown
            const laneColItems: Record<ColKey, WorkItemView[]> = { backlog: [], ready: [], in_progress: [], review: [], done: [] };
            for (const item of lane.items) {
              for (const col of COLUMNS) {
                if (col.statuses.includes(item.status)) {
                  if (col.key === 'done' && laneColItems.done.length >= 20) break;
                  laneColItems[col.key].push(item);
                  break;
                }
              }
            }
            return (
              <div key={lane.key}>
                <div style={{ padding: '4px 16px', fontSize: 10, fontWeight: 700, color: '#8888a0', background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.04)', letterSpacing: 0.5 }}>
                  {lane.label}
                </div>
                <div style={{ display: 'flex', minHeight: 80 }}>
                  {COLUMNS.map(col => renderColumn(col, laneColItems[col.key]))}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Blocked/Failed row */}
      {blockedItems.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', flexShrink: 0 }}>
          <div onClick={() => setShowBlocked(!showBlocked)}
            style={{ padding: '5px 16px', fontSize: 10, fontWeight: 600, color: '#d07050', cursor: 'pointer', userSelect: 'none' }}>
            <span style={{ fontSize: 8 }}>{showBlocked ? '▼' : '▶'}</span> Blocked/Failed ({blockedItems.length})
          </div>
          {showBlocked && (
            <div style={{ padding: '4px 16px 8px', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {blockedItems.map(item => (
                <div key={item.id} style={{
                  padding: '5px 8px', borderRadius: 4, fontSize: 10,
                  background: 'rgba(208,80,80,0.06)', border: '1px solid rgba(208,80,80,0.15)',
                  maxWidth: 200,
                }}>
                  <div style={{ fontWeight: 600, color: '#c8d0e0' }}>
                    {item.title.length > 30 ? item.title.slice(0, 30) + '\u2026' : item.title}
                  </div>
                  <div style={{ color: '#d07050', fontSize: 9 }}>{item.status}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const toolbarBtn: React.CSSProperties = {
  padding: '3px 8px', fontSize: 10, borderRadius: 4, cursor: 'pointer',
  background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', color: '#aaa',
  fontFamily: "'JetBrains Mono', monospace",
};

const filterChip: React.CSSProperties = {
  padding: '1px 6px', fontSize: 9, borderRadius: 3, cursor: 'pointer', marginRight: 3, marginBottom: 2,
  border: '1px solid rgba(255,255,255,0.08)',
  fontFamily: "'JetBrains Mono', monospace",
};
