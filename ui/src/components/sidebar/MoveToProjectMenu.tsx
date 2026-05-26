/*
 * AD-793 (Wave 196) — MoveToProjectMenu.
 *
 * Submenu under ThreadRow's right-click "Move to project…" item.
 * Lists existing projects + a "None (unparent)" option. Selecting
 * an option sends PATCH /api/threads/{id} with the new project_id
 * value. The parent handles the PATCH + store update.
 */
import { useEffect, useRef } from 'react';
import type { ProjectView } from '../../store/useStore';

const AMBER = '#f0b060';
const DIM = '#666680';
const TEXT = '#e0dcd4';
const BG = '#0a0a14';
const BORDER = 'rgba(240, 176, 96, 0.15)';
const BG_HOVER = 'rgba(240, 176, 96, 0.08)';

export interface MoveToProjectMenuProps {
  threadId: string;
  x: number;
  y: number;
  projects: ProjectView[];
  currentProjectId?: string | null;
  onPick: (newProjectId: string | null) => void;
  onClose: () => void;
}

export function MoveToProjectMenu({
  threadId,
  x,
  y,
  projects,
  currentProjectId,
  onPick,
  onClose,
}: MoveToProjectMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const vw = typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1024;
  const vh = typeof window !== 'undefined' && window.innerHeight ? window.innerHeight : 768;
  const menuWidth = 220;
  const menuHeight = Math.min(48 + projects.length * 28, 320);
  const adjX = x + menuWidth > vw ? Math.max(0, vw - menuWidth - 4) : x;
  const adjY = y + menuHeight > vh ? Math.max(0, vh - menuHeight - 4) : y;

  return (
    <div
      ref={menuRef}
      role="menu"
      data-testid={`move-to-project-menu-${threadId}`}
      style={{
        position: 'fixed',
        top: adjY,
        left: adjX,
        zIndex: 10001,
        background: BG,
        border: `1px solid ${BORDER}`,
        boxShadow: '0 4px 12px rgba(0,0,0,0.6)',
        minWidth: menuWidth,
        maxHeight: 320,
        overflowY: 'auto',
        padding: 4,
        fontSize: 12,
        color: TEXT,
        fontFamily: 'inherit',
      }}
    >
      <div
        style={{
          fontSize: 9,
          letterSpacing: 1.5,
          color: DIM,
          padding: '4px 10px 6px',
          textTransform: 'uppercase',
        }}
      >
        Move to project
      </div>
      <Item
        testid={`move-to-project-none-${threadId}`}
        label="None (unparent)"
        active={currentProjectId == null}
        onClick={() => onPick(null)}
      />
      {projects.length === 0 ? (
        <div
          style={{ padding: '6px 10px', color: DIM, fontSize: 11 }}
          data-testid="move-to-project-empty"
        >
          No projects yet
        </div>
      ) : (
        projects.map((p) => (
          <Item
            key={p.id}
            testid={`move-to-project-${p.id}`}
            label={p.name}
            active={currentProjectId === p.id}
            onClick={() => onPick(p.id)}
          />
        ))
      )}
    </div>
  );
}

function Item({
  label,
  onClick,
  testid,
  active,
}: {
  label: string;
  onClick: () => void;
  testid: string;
  active: boolean;
}) {
  return (
    <div
      role="menuitem"
      tabIndex={0}
      data-testid={testid}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick();
      }}
      style={{
        padding: '6px 10px',
        cursor: 'pointer',
        color: active ? AMBER : TEXT,
        borderRadius: 2,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = BG_HOVER)}
      onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
    >
      {active ? '• ' : ''}
      {label}
    </div>
  );
}

export default MoveToProjectMenu;
