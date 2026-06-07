/**
 * AD-898: Skill Library management view — the admin console for AD-895.
 *
 * The writable skill-definition library surface: browse and filter the
 * definitions (`GET /api/skills/definitions`), create (`POST`), edit (`PUT`),
 * and retire (`DELETE`) a definition. Destructive retire is gated behind an
 * explicit two-step confirm, and the AD-895 server-side guards (duplicate,
 * dangling-prerequisite, built-in protected, in-use protected) are surfaced
 * inline rather than swallowed.
 *
 * Thin UI over the governed AD-895 endpoints — no new consensus gate; the
 * validation and protection model lives behind the HTTP surface.
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji.
 */

import { useState, useEffect, useCallback } from 'react';

interface SkillDef {
  skill_id: string;
  name: string;
  category: string;
  description: string;
  domain: string;
  prerequisites: string[];
  decay_rate_days: number;
  origin: string;
}

interface DraftForm {
  skill_id: string;
  name: string;
  category: string;
  description: string;
  domain: string;
  prerequisites: string;
  decay_rate_days: number;
}

const CATEGORIES = ['pcc', 'role', 'acquired'];

const CATEGORY_LABELS: Record<string, string> = {
  pcc: 'Professional Core',
  role: 'Role',
  acquired: 'Acquired',
};

const EMPTY_FORM: DraftForm = {
  skill_id: '',
  name: '',
  category: 'role',
  description: '',
  domain: '*',
  prerequisites: '',
  decay_rate_days: 14,
};

const chipStyle = (color: string): React.CSSProperties => ({
  fontSize: 10,
  fontFamily: "'JetBrains Mono', monospace",
  letterSpacing: 0.5,
  color,
  background: 'transparent',
  border: `1px solid ${color}`,
  borderRadius: 3,
  padding: '3px 8px',
  cursor: 'pointer',
});

const fieldStyle: React.CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  color: '#c8c8d4',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid rgba(240,176,96,0.2)',
  borderRadius: 4,
  padding: '5px 8px',
};

export default function SkillLibrary() {
  const [definitions, setDefinitions] = useState<SkillDef[]>([]);
  const [filterCategory, setFilterCategory] = useState('');
  const [mode, setMode] = useState<'create' | 'edit' | null>(null);
  const [form, setForm] = useState<DraftForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const qs = filterCategory ? `?category=${encodeURIComponent(filterCategory)}` : '';
      const resp = await fetch(`/api/skills/definitions${qs}`);
      if (!resp.ok) {
        setDefinitions([]);
        return;
      }
      const data = await resp.json();
      setDefinitions(Array.isArray(data?.definitions) ? data.definitions : []);
    } catch {
      setDefinitions([]);
    }
  }, [filterCategory]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refresh();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const openCreate = useCallback(() => {
    setForm(EMPTY_FORM);
    setFormError(null);
    setMode('create');
  }, []);

  const openEdit = useCallback((d: SkillDef) => {
    setForm({
      skill_id: d.skill_id,
      name: d.name,
      category: d.category,
      description: d.description,
      domain: d.domain,
      prerequisites: (d.prerequisites || []).join(', '),
      decay_rate_days: d.decay_rate_days,
    });
    setFormError(null);
    setMode('edit');
  }, []);

  const closeForm = useCallback(() => {
    setMode(null);
    setFormError(null);
  }, []);

  const submitForm = useCallback(async () => {
    if (!form.name.trim()) {
      setFormError('Name is required.');
      return;
    }
    if (mode === 'create' && !form.skill_id.trim()) {
      setFormError('Skill ID is required.');
      return;
    }
    setFormError(null);
    const prerequisites = form.prerequisites
      .split(',')
      .map(p => p.trim())
      .filter(Boolean);
    const payload = {
      skill_id: form.skill_id.trim(),
      name: form.name.trim(),
      category: form.category,
      description: form.description,
      domain: form.domain.trim() || '*',
      prerequisites,
      decay_rate_days: form.decay_rate_days,
    };
    const url =
      mode === 'create'
        ? '/api/skills/definitions'
        : `/api/skills/definitions/${encodeURIComponent(form.skill_id)}`;
    const method = mode === 'create' ? 'POST' : 'PUT';
    try {
      const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        let detail = 'Skill rejected.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setFormError(detail);
        return;
      }
      closeForm();
      await refresh();
    } catch {
      setFormError('Request failed.');
    }
  }, [form, mode, closeForm, refresh]);

  const retire = useCallback(async (skillId: string) => {
    setRowError(null);
    try {
      const resp = await fetch(`/api/skills/definitions/${encodeURIComponent(skillId)}`, {
        method: 'DELETE',
      });
      if (!resp.ok) {
        let detail = 'Retire rejected.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setRowError(detail);
        return;
      }
      await refresh();
    } catch {
      setRowError('Retire failed.');
    } finally {
      setConfirmDeleteId(null);
    }
  }, [refresh]);

  return (
    <div data-testid="skill-library" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
      {/* Header — filter + new */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span style={{ fontSize: 11, letterSpacing: 1.5, fontWeight: 700, color: '#f0b060' }}>
          SKILL LIBRARY
        </span>
        <select
          data-testid="skill-filter-category"
          value={filterCategory}
          onChange={e => setFilterCategory(e.target.value)}
          style={{ ...fieldStyle, width: 'auto' }}
        >
          <option value="">All categories</option>
          {CATEGORIES.map(c => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="skill-new"
          onClick={openCreate}
          style={{ ...chipStyle('#f0b060'), marginLeft: 'auto' }}
        >
          New Skill
        </button>
      </div>

      {/* Definition list */}
      {definitions.length === 0 ? (
        <div style={{ fontSize: 11, color: '#666680' }}>No skill definitions.</div>
      ) : (
        definitions.map(d => {
          const builtin = d.origin === 'builtin';
          return (
            <div
              key={d.skill_id}
              data-testid={`skill-row-${d.skill_id}`}
              style={{
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 4,
                padding: '8px 10px',
                margin: '6px 0',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, color: '#c8c8d4' }}>{d.name}</span>
                <span style={{ fontSize: 9, letterSpacing: 1, color: '#8888a0' }}>
                  {(CATEGORY_LABELS[d.category] || d.category).toUpperCase()}
                </span>
              </div>
              {d.description && (
                <div style={{ fontSize: 10, color: '#8888a0', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                  {d.description.length > 240 ? `${d.description.slice(0, 240)}\u2026` : d.description}
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 9, color: '#666680' }}>{d.domain}</span>
                {builtin && (
                  <span style={{ fontSize: 9, color: '#50b0a0', letterSpacing: 1 }}>BUILT-IN</span>
                )}
                <button
                  type="button"
                  data-testid={`skill-edit-${d.skill_id}`}
                  onClick={() => openEdit(d)}
                  style={{ ...chipStyle('#8888a0'), marginLeft: 'auto' }}
                >
                  Edit
                </button>
                {confirmDeleteId === d.skill_id ? (
                  <button
                    type="button"
                    data-testid={`skill-delete-confirm-${d.skill_id}`}
                    onClick={() => retire(d.skill_id)}
                    style={chipStyle('#d05050')}
                  >
                    Confirm retire
                  </button>
                ) : (
                  <button
                    type="button"
                    data-testid={`skill-delete-${d.skill_id}`}
                    onClick={() => {
                      setRowError(null);
                      setConfirmDeleteId(d.skill_id);
                    }}
                    style={chipStyle('#d05050')}
                  >
                    Retire
                  </button>
                )}
              </div>
            </div>
          );
        })
      )}

      {rowError && (
        <div data-testid="skill-row-error" style={{ fontSize: 10, color: '#d05050', marginTop: 6 }}>
          {rowError}
        </div>
      )}

      {/* Create / Edit form */}
      {mode && (
        <div
          data-testid="skill-form"
          style={{
            marginTop: 14,
            border: '1px solid rgba(240,176,96,0.25)',
            borderRadius: 6,
            padding: 12,
          }}
        >
          <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, marginBottom: 8 }}>
            {mode === 'create' ? 'NEW SKILL DEFINITION' : 'EDIT SKILL DEFINITION'}
          </div>
          {mode === 'create' && (
            <input
              data-testid="skill-form-id"
              value={form.skill_id}
              onChange={e => setForm({ ...form, skill_id: e.target.value })}
              placeholder="skill_id"
              style={{ ...fieldStyle, marginBottom: 6 }}
            />
          )}
          <input
            data-testid="skill-form-name"
            value={form.name}
            onChange={e => setForm({ ...form, name: e.target.value })}
            placeholder="Name"
            style={{ ...fieldStyle, marginBottom: 6 }}
          />
          <select
            data-testid="skill-form-category"
            value={form.category}
            onChange={e => setForm({ ...form, category: e.target.value })}
            style={{ ...fieldStyle, marginBottom: 6 }}
          >
            {CATEGORIES.map(c => (
              <option key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
          <textarea
            data-testid="skill-form-description"
            value={form.description}
            onChange={e => setForm({ ...form, description: e.target.value })}
            placeholder="Description"
            rows={2}
            style={{ ...fieldStyle, marginBottom: 6, resize: 'vertical' }}
          />
          <input
            data-testid="skill-form-domain"
            value={form.domain}
            onChange={e => setForm({ ...form, domain: e.target.value })}
            placeholder="Domain (* for all)"
            style={{ ...fieldStyle, marginBottom: 6 }}
          />
          <input
            data-testid="skill-form-prerequisites"
            value={form.prerequisites}
            onChange={e => setForm({ ...form, prerequisites: e.target.value })}
            placeholder="Prerequisites (comma-separated skill_ids)"
            style={{ ...fieldStyle, marginBottom: 8 }}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              type="button"
              data-testid="skill-form-submit"
              onClick={submitForm}
              style={chipStyle('#f0b060')}
            >
              {mode === 'create' ? 'Create' : 'Save'}
            </button>
            <button
              type="button"
              data-testid="skill-form-cancel"
              onClick={closeForm}
              style={chipStyle('#8888a0')}
            >
              Cancel
            </button>
          </div>
          {formError && (
            <div data-testid="skill-form-error" style={{ fontSize: 10, color: '#d05050', marginTop: 6 }}>
              {formError}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
