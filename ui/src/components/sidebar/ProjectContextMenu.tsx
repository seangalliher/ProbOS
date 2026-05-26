/*
 * AD-793 (Wave 196) — ProjectContextMenu.
 *
 * Right-click menu for a project row: Rename / Edit description /
 * Archive / Delete. Delete opens a separate confirmation modal with
 * unparent (default) vs cascade radio + double-confirmation for
 * cascade.
 */
import { useEffect, useRef, useState } from 'react';

const AMBER = '#f0b060';
const DIM = '#666680';
const TEXT = '#e0dcd4';
const BG = '#0a0a14';
const BORDER = 'rgba(240, 176, 96, 0.15)';
const BG_HOVER = 'rgba(240, 176, 96, 0.08)';

export interface ProjectContextMenuProps {
  projectId: string;
  x: number;
  y: number;
  onRename: () => void;
  onEditDescription: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onClose: () => void;
}

export function ProjectContextMenu({
  projectId,
  x,
  y,
  onRename,
  onEditDescription,
  onArchive,
  onDelete,
  onClose,
}: ProjectContextMenuProps) {
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
  const menuWidth = 200;
  const menuHeight = 160;
  const adjX = x + menuWidth > vw ? Math.max(0, vw - menuWidth - 4) : x;
  const adjY = y + menuHeight > vh ? Math.max(0, vh - menuHeight - 4) : y;

  return (
    <div
      ref={menuRef}
      data-testid={`project-context-menu-${projectId}`}
      role="menu"
      style={{
        position: 'fixed',
        top: adjY,
        left: adjX,
        zIndex: 9999,
        background: BG,
        border: `1px solid ${BORDER}`,
        boxShadow: '0 4px 12px rgba(0,0,0,0.6)',
        minWidth: menuWidth,
        padding: 4,
        fontSize: 12,
        color: TEXT,
        fontFamily: 'inherit',
      }}
    >
      <MenuItem testid="project-ctx-rename" label="Rename" onClick={onRename} />
      <MenuItem
        testid="project-ctx-edit-description"
        label="Edit description"
        onClick={onEditDescription}
      />
      <MenuItem testid="project-ctx-archive" label="Archive" onClick={onArchive} />
      <MenuItem
        testid="project-ctx-delete"
        label="Delete"
        onClick={onDelete}
        danger
      />
    </div>
  );
}

function MenuItem({
  label,
  onClick,
  testid,
  danger,
}: {
  label: string;
  onClick: () => void;
  testid: string;
  danger?: boolean;
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
        color: danger ? '#d06868' : TEXT,
        borderRadius: 2,
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = BG_HOVER)}
      onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')}
    >
      {label}
    </div>
  );
}

// ---------- Delete confirmation modal with cascade radio ---------------

export interface ProjectDeleteConfirmProps {
  projectName: string;
  threadCount: number;
  onConfirm: (cascade: boolean) => void;
  onCancel: () => void;
}

export function ProjectDeleteConfirm({
  projectName,
  threadCount,
  onConfirm,
  onCancel,
}: ProjectDeleteConfirmProps) {
  const [mode, setMode] = useState<'unparent' | 'cascade'>('unparent');
  const [cascadeConfirmed, setCascadeConfirmed] = useState(false);

  function handleConfirm() {
    if (mode === 'cascade' && !cascadeConfirmed) {
      // Double-confirmation gate.
      setCascadeConfirmed(true);
      return;
    }
    onConfirm(mode === 'cascade');
  }

  const cascadeBtnLabel =
    mode === 'cascade' && !cascadeConfirmed
      ? `Delete ${threadCount} threads?`
      : 'Delete';

  return (
    <div
      role="dialog"
      aria-label="Confirm delete project"
      data-testid="project-delete-confirm"
      style={{
        position: 'fixed',
        top: '40%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 10000,
        background: BG,
        border: `1px solid ${BORDER}`,
        padding: 16,
        minWidth: 380,
        color: TEXT,
        fontSize: 12,
        boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
      }}
    >
      <div style={{ marginBottom: 12 }}>
        Delete project <strong>{projectName}</strong>?
      </div>
      <div style={{ marginBottom: 8 }}>
        <label
          style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}
        >
          <input
            type="radio"
            name="project-delete-mode"
            data-testid="project-delete-mode-unparent"
            checked={mode === 'unparent'}
            onChange={() => {
              setMode('unparent');
              setCascadeConfirmed(false);
            }}
          />
          <span>
            Unparent {threadCount} threads (move back to Recents). Default — safe.
          </span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <input
            type="radio"
            name="project-delete-mode"
            data-testid="project-delete-mode-cascade"
            checked={mode === 'cascade'}
            onChange={() => setMode('cascade')}
          />
          <span style={{ color: '#d06868' }}>
            Delete {threadCount} threads + messages (cascade).
          </span>
        </label>
      </div>
      {mode === 'cascade' && cascadeConfirmed && (
        <div
          data-testid="project-delete-cascade-warning"
          style={{ color: '#d06868', marginBottom: 8, fontSize: 11 }}
        >
          This will permanently delete {threadCount} threads and their messages.
          Click Delete again to confirm.
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button
          type="button"
          data-testid="project-delete-cancel"
          onClick={onCancel}
          style={btnStyle()}
        >
          Cancel
        </button>
        <button
          type="button"
          data-testid="project-delete-confirm-btn"
          onClick={handleConfirm}
          style={btnStyle({ danger: mode === 'cascade' })}
        >
          {cascadeBtnLabel}
        </button>
      </div>
    </div>
  );
}

function btnStyle({ danger }: { danger?: boolean } = {}) {
  return {
    background: 'transparent',
    border: `1px solid ${danger ? '#d06868' : BORDER}`,
    color: danger ? '#d06868' : AMBER,
    fontFamily: 'inherit',
    fontSize: 11,
    padding: '4px 10px',
    borderRadius: 3,
    cursor: 'pointer',
    letterSpacing: 1,
  } as const;
}

// ---------- Edit description modal -------------------------------------

export interface EditDescriptionModalProps {
  projectName: string;
  initialDescription: string;
  onSubmit: (description: string) => void;
  onCancel: () => void;
}

export function EditDescriptionModal({
  projectName,
  initialDescription,
  onSubmit,
  onCancel,
}: EditDescriptionModalProps) {
  const [draft, setDraft] = useState(initialDescription);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);
  return (
    <div
      role="dialog"
      aria-label="Edit project description"
      data-testid="edit-description-modal"
      style={{
        position: 'fixed',
        top: '40%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 10000,
        background: BG,
        border: `1px solid ${BORDER}`,
        padding: 16,
        minWidth: 380,
        color: TEXT,
        fontSize: 12,
        boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: 1.5, color: AMBER, marginBottom: 10 }}>
        EDIT DESCRIPTION — {projectName}
      </div>
      <textarea
        data-testid="edit-description-textarea"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={6}
        style={{
          display: 'block',
          width: '100%',
          background: 'transparent',
          border: `1px solid ${BORDER}`,
          color: TEXT,
          fontFamily: 'inherit',
          fontSize: 12,
          padding: '6px 8px',
          borderRadius: 2,
          outline: 'none',
          resize: 'vertical',
          marginBottom: 12,
        }}
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button
          type="button"
          data-testid="edit-description-cancel"
          onClick={onCancel}
          style={btnStyle()}
        >
          Cancel
        </button>
        <button
          type="button"
          data-testid="edit-description-save"
          onClick={() => onSubmit(draft)}
          style={btnStyle()}
        >
          Save
        </button>
      </div>
    </div>
  );
}

export default ProjectContextMenu;
