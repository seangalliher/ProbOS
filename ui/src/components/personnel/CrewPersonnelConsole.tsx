/**
 * AD-896: Crew Personnel Console — the Ship's Office.
 *
 * A *separate experience*, not another profile tab: a resizable, draggable,
 * dockable window (mirroring the AD-837 Ward Room display-mode system) that
 * presents a master-detail HR surface. The left pane is the crew roster (bound
 * to `GET /api/crew/roster`); selecting an agent loads that agent's service
 * record into the right pane.
 *
 * The right detail pane is a minimal placeholder here — AD-897 (Service Record
 * detail view) fills it in. AD-896 owns only the window shell, the roster
 * master pane, and selection wiring.
 *
 * HXI compliance: stroke-only SVG glyphs, amber active state, no emoji.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useStore } from '../../store/useStore';
import { Close, Dock, Undock, Maximize, Restore } from '../icons/Glyphs';
import ServiceRecord from './ServiceRecord';
import SkillLibrary from './SkillLibrary';
import ToolCertifications from './ToolCertifications';
import RolePicker from './RolePicker';

type ConsoleView = 'roster' | 'skills' | 'tools' | 'roles';

interface RosterEntry {
  agent_id: string;
  agent_type: string;
  callsign?: string;
  post?: string | null;
  department?: string | null;
  rank?: string | null;
  assigned?: boolean;
  billet_state?: string;
  lifecycle_state?: string;
  skill_count?: number;
  tool_count?: number;
}

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

const RANK_LABELS: Record<string, string> = {
  ensign: 'ENS',
  lieutenant: 'LT',
  commander: 'CMDR',
  senior_officer: 'SR',
  senior: 'SR',
};

function deptColor(dept: string | null | undefined): string {
  if (!dept) return '#8888a0';
  return DEPT_COLORS[dept.toLowerCase()] || '#8888a0';
}

export default function CrewPersonnelConsole() {
  const open = useStore(s => s.personnelConsoleOpen);
  const close = useStore(s => s.closePersonnelConsole);
  const displayMode = useStore(s => s.personnelDisplayMode);
  const windowRect = useStore(s => s.personnelWindowRect);
  const setDisplayMode = useStore(s => s.setPersonnelDisplayMode);

  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<ConsoleView>('roster');

  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });

  // Fetch the roster when the console opens (master pane source of truth).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const resp = await fetch('/api/crew/roster');
        if (!resp.ok) {
          throw new Error(`roster fetch failed: ${resp.status}`);
        }
        const data = await resp.json();
        if (!cancelled) {
          setRoster(Array.isArray(data?.crew) ? data.crew : []);
        }
      } catch {
        // honest-degrade — show an empty roster rather than crashing the shell.
        if (!cancelled) setRoster([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Drag (floating only) — mirror Ward Room's add-on-down / remove-on-up
  // listener discipline (no always-on global listeners).
  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if (displayMode !== 'floating') return;
    setIsDragging(true);
    dragOffset.current = { x: e.clientX - windowRect.x, y: e.clientY - windowRect.y };
  }, [displayMode, windowRect]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const rect = useStore.getState().personnelWindowRect;
      const newX = Math.max(0, Math.min(window.innerWidth - rect.w, e.clientX - dragOffset.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.current.y));
      useStore.getState().setPersonnelWindowRect({ ...rect, x: newX, y: newY });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  // Resize (floating only) — bottom-right corner.
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    setIsResizing(true);
    resizeStart.current = { x: e.clientX, y: e.clientY, w: windowRect.w, h: windowRect.h };
    e.preventDefault();
    e.stopPropagation();
  }, [windowRect]);

  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      const rect = useStore.getState().personnelWindowRect;
      const dw = e.clientX - resizeStart.current.x;
      const dh = e.clientY - resizeStart.current.y;
      const nw = Math.max(480, Math.min(window.innerWidth - 40, resizeStart.current.w + dw));
      const nh = Math.max(360, Math.min(window.innerHeight - 40, resizeStart.current.h + dh));
      useStore.getState().setPersonnelWindowRect({ ...rect, w: nw, h: nh });
    };
    const onUp = () => setIsResizing(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isResizing]);

  // AD-837 container chrome derived from display mode.
  const baseChrome: React.CSSProperties = {
    background: 'rgba(10, 10, 18, 0.92)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    display: 'flex',
    flexDirection: 'column',
    fontFamily: "'JetBrains Mono', monospace",
    color: '#e0dcd4',
  };
  let containerStyle: React.CSSProperties;
  if (displayMode === 'maximized') {
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      inset: 16,
      border: '1px solid rgba(240, 176, 96, 0.25)',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
      zIndex: 30,
      opacity: open ? 1 : 0,
      visibility: open ? 'visible' : 'hidden',
      pointerEvents: open ? 'auto' : 'none',
    };
  } else if (displayMode === 'docked') {
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      top: 0, right: 0, bottom: 0,
      width: 520,
      borderLeft: '1px solid rgba(240, 176, 96, 0.15)',
      zIndex: 20,
      transform: open ? 'translateX(0)' : 'translateX(100%)',
      transition: 'transform 0.25s ease-out',
      pointerEvents: open ? 'auto' : 'none',
    };
  } else {
    // floating (default)
    containerStyle = {
      ...baseChrome,
      position: 'fixed',
      left: windowRect.x, top: windowRect.y,
      width: windowRect.w, height: windowRect.h,
      border: '1px solid rgba(240, 176, 96, 0.25)',
      borderRadius: 12,
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
      zIndex: 30,
      opacity: open ? 1 : 0,
      visibility: open ? 'visible' : 'hidden',
      pointerEvents: open ? 'auto' : 'none',
    };
  }

  // Group roster by department (master pane organization).
  const grouped: Record<string, RosterEntry[]> = {};
  for (const entry of roster) {
    const dept = entry.department || 'unbilleted';
    if (!grouped[dept]) grouped[dept] = [];
    grouped[dept].push(entry);
  }
  const deptNames = Object.keys(grouped).sort();
  const selected = roster.find(e => e.agent_id === selectedId) || null;

  return (
    <div data-testid="personnel-console" data-mode={displayMode} style={containerStyle}>
      {/* Header (drag handle in floating mode) */}
      <div
        onMouseDown={onHeaderMouseDown}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          cursor: displayMode === 'floating' ? (isDragging ? 'grabbing' : 'grab') : 'default',
          userSelect: 'none',
        }}
      >
        <span style={{
          fontSize: 11, letterSpacing: 1.5, fontWeight: 700,
          color: '#f0b060', textTransform: 'uppercase',
        }}>
          SHIP'S OFFICE
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Dock/Undock toggle */}
          <span
            role="button"
            aria-label={displayMode === 'docked' ? 'Undock Crew Personnel Console' : 'Dock Crew Personnel Console'}
            title={displayMode === 'docked' ? 'Undock to floating window' : 'Dock to sidebar'}
            onMouseDown={e => e.stopPropagation()}
            onClick={() => setDisplayMode(displayMode === 'docked' ? 'floating' : 'docked')}
            style={{ cursor: 'pointer', display: 'flex', color: displayMode === 'docked' ? '#8888a0' : '#f0b060' }}
          >
            {displayMode === 'docked' ? <Undock size={15} /> : <Dock size={15} />}
          </span>
          {/* Maximize/Restore — hidden in docked mode */}
          {displayMode !== 'docked' && (
            <span
              role="button"
              aria-label={displayMode === 'maximized' ? 'Restore Crew Personnel Console' : 'Maximize Crew Personnel Console'}
              title={displayMode === 'maximized' ? 'Restore window' : 'Maximize'}
              onMouseDown={e => e.stopPropagation()}
              onClick={() => setDisplayMode(displayMode === 'maximized' ? 'floating' : 'maximized')}
              style={{ cursor: 'pointer', display: 'flex', color: '#f0b060' }}
            >
              {displayMode === 'maximized' ? <Restore size={15} /> : <Maximize size={15} />}
            </span>
          )}
          <span
            role="button"
            aria-label="Close Crew Personnel Console"
            onClick={close}
            onMouseDown={e => e.stopPropagation()}
            style={{ cursor: 'pointer', color: '#8888a0', display: 'flex' }}
          >
            <Close size={16} />
          </span>
        </div>
      </div>

      {/* View switcher — Roster (master-detail) vs library/asset admin surfaces. */}
      <div
        data-testid="personnel-view-tabs"
        style={{
          display: 'flex', gap: 4, padding: '6px 12px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        {([
          ['roster', 'Roster'],
          ['roles', 'Roles'],
          ['skills', 'Skill Library'],
          ['tools', 'Tool Certs'],
        ] as [ConsoleView, string][]).map(([key, label]) => {
          const active = view === key;
          return (
            <button
              key={key}
              type="button"
              data-testid={`personnel-tab-${key}`}
              onClick={() => setView(key)}
              style={{
                fontSize: 10, letterSpacing: 1, fontWeight: 700,
                fontFamily: "'JetBrains Mono', monospace",
                textTransform: 'uppercase',
                color: active ? '#f0b060' : '#8888a0',
                background: 'transparent',
                border: 'none',
                borderBottom: active ? '2px solid #f0b060' : '2px solid transparent',
                padding: '4px 8px',
                cursor: 'pointer',
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      {view === 'skills' ? (
        /* Skill Library management surface (AD-898). */
        <div
          data-testid="personnel-skills-pane"
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 20 }}
        >
          <SkillLibrary />
        </div>
      ) : view === 'tools' ? (
        /* Tool certification management surface (AD-899). */
        <div
          data-testid="personnel-tools-pane"
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 20 }}
        >
          <ToolCertifications />
        </div>
      ) : view === 'roles' ? (
        /* Role-template picker surface (AD-1010). */
        <div
          data-testid="personnel-roles-pane"
          style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 20 }}
        >
          <RolePicker />
        </div>
      ) : (
      /* Master-detail body */
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Master — roster */}
        <div
          data-testid="personnel-roster-pane"
          style={{
            width: 260, flexShrink: 0, overflowY: 'auto',
            borderRight: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          {loading ? (
            <div style={{ padding: 16, color: '#666680', fontSize: 11 }}>
              Loading roster...
            </div>
          ) : roster.length === 0 ? (
            <div style={{ padding: 16, color: '#666680', fontSize: 11 }}>
              No crew aboard.
            </div>
          ) : (
            deptNames.map(dept => (
              <div key={dept}>
                <div style={{
                  padding: '8px 14px 4px',
                  fontSize: 9, letterSpacing: 1.5, fontWeight: 700,
                  color: deptColor(dept), textTransform: 'uppercase',
                }}>
                  {dept}
                </div>
                {grouped[dept].map(entry => {
                  const isSel = entry.agent_id === selectedId;
                  const rankKey = (entry.rank || '').toLowerCase();
                  return (
                    <div
                      key={entry.agent_id}
                      role="button"
                      data-testid={`personnel-roster-row-${entry.agent_id}`}
                      onClick={() => setSelectedId(entry.agent_id)}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '6px 14px',
                        cursor: 'pointer',
                        background: isSel ? 'rgba(240, 176, 96, 0.12)' : 'transparent',
                        borderLeft: isSel ? '2px solid #f0b060' : '2px solid transparent',
                      }}
                    >
                      <span style={{
                        fontSize: 12,
                        color: isSel ? '#f0b060' : '#c8c8d4',
                      }}>
                        {entry.callsign || entry.agent_type || entry.agent_id}
                      </span>
                      {rankKey && (
                        <span style={{ fontSize: 9, color: '#8888a0', letterSpacing: 1 }}>
                          {RANK_LABELS[rankKey] || rankKey.toUpperCase()}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Detail — service record (AD-897 fills this in) */}
        <div
          data-testid="personnel-record-pane"
          style={{
            flex: 1, minWidth: 0, overflowY: 'auto', padding: 24,
          }}
        >
          {selected ? (
            <ServiceRecord agentId={selected.agent_id} summary={selected} />
          ) : (
            <div style={{
              height: '100%', display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              color: '#666680', fontSize: 11, textAlign: 'center',
            }}>
              Select a crew member to view their service record.
            </div>
          )}
        </div>
      </div>
      )}

      {/* Resize handle (floating only) */}
      {displayMode === 'floating' && (
        <div
          data-testid="personnel-resize-handle"
          onMouseDown={onResizeMouseDown}
          style={{
            position: 'absolute', right: 0, bottom: 0,
            width: 16, height: 16, cursor: 'nwse-resize',
            background: 'transparent',
          }}
        />
      )}
    </div>
  );
}
