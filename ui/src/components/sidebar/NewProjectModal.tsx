/*
 * AD-793 (Wave 196) — NewProjectModal.
 *
 * Name + description inputs + POST /api/projects. Empty name disables
 * the submit button. HXI #1: plain prose description, no structured
 * config. HXI #3: no emoji.
 */
import { useEffect, useRef, useState } from 'react';

const AMBER = '#f0b060';
const DIM = '#666680';
const TEXT = '#e0dcd4';
const BG = '#0a0a14';
const BORDER = 'rgba(240, 176, 96, 0.15)';

export interface NewProjectModalProps {
  onSubmit: (name: string, description: string) => void | Promise<void>;
  onCancel: () => void;
}

export function NewProjectModal({ onSubmit, onCancel }: NewProjectModalProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const trimmedName = name.trim();
  const canSubmit = trimmedName.length > 0 && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onSubmit(trimmedName, description.trim());
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="New project"
      data-testid="new-project-modal"
      style={{
        position: 'fixed',
        top: '40%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 10000,
        background: BG,
        border: `1px solid ${BORDER}`,
        padding: 16,
        minWidth: 360,
        color: TEXT,
        fontSize: 12,
        boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: 1.5, color: AMBER, marginBottom: 10 }}>
        NEW PROJECT
      </div>
      <label style={{ display: 'block', marginBottom: 8 }}>
        <span style={{ color: DIM, fontSize: 10, letterSpacing: 0.5 }}>Name</span>
        <input
          ref={nameRef}
          type="text"
          data-testid="new-project-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleSubmit();
          }}
          style={{
            display: 'block',
            width: '100%',
            background: 'transparent',
            border: `1px solid ${BORDER}`,
            color: TEXT,
            fontFamily: 'inherit',
            fontSize: 12,
            padding: '6px 8px',
            marginTop: 4,
            borderRadius: 2,
            outline: 'none',
          }}
        />
      </label>
      <label style={{ display: 'block', marginBottom: 12 }}>
        <span style={{ color: DIM, fontSize: 10, letterSpacing: 0.5 }}>
          Description (injected as system preamble in chat)
        </span>
        <textarea
          data-testid="new-project-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={4}
          style={{
            display: 'block',
            width: '100%',
            background: 'transparent',
            border: `1px solid ${BORDER}`,
            color: TEXT,
            fontFamily: 'inherit',
            fontSize: 12,
            padding: '6px 8px',
            marginTop: 4,
            borderRadius: 2,
            outline: 'none',
            resize: 'vertical',
          }}
        />
      </label>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button
          type="button"
          data-testid="new-project-cancel"
          onClick={onCancel}
          style={btnStyle()}
        >
          Cancel
        </button>
        <button
          type="button"
          data-testid="new-project-submit"
          onClick={() => void handleSubmit()}
          disabled={!canSubmit}
          style={btnStyle({ primary: true, disabled: !canSubmit })}
        >
          Create
        </button>
      </div>
    </div>
  );
}

function btnStyle({ primary, disabled }: { primary?: boolean; disabled?: boolean } = {}) {
  return {
    background: 'transparent',
    border: `1px solid ${primary ? AMBER : BORDER}`,
    color: primary ? AMBER : TEXT,
    fontFamily: 'inherit',
    fontSize: 11,
    padding: '4px 10px',
    borderRadius: 3,
    cursor: disabled ? 'not-allowed' : 'pointer',
    letterSpacing: 1,
    opacity: disabled ? 0.4 : 1,
  } as const;
}

export default NewProjectModal;
