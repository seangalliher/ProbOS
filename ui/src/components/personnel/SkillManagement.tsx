/**
 * AD-902: Developmental (T3) skill management view.
 *
 * The governed write surface for an agent's developmental skill records,
 * composed inside the Service Record (AD-897) skills section, mirroring how
 * AD-901's StandingOrders is composed inside the orders section. Four verbs
 * over the AgentSkillService (AD-428) crew-prefixed endpoints:
 *   1. Acquire — give the agent a skill from the registry catalog.
 *   2. Re-level — step proficiency up/down (down-level is two-step confirm).
 *   3. Suspend — soft, reversible boolean toggle (two-step confirm).
 *   4. Reinstate — clear the suspension.
 *
 * Every mutation is reversible (idempotent upsert / two-way level moves / soft
 * suspend), so there is no new consensus gate (Minimal Authority).
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji, honest-degrade.
 */

import { useState, useEffect, useCallback } from 'react';

interface SkillRecord {
  skill_id: string;
  name?: string;
  category?: string;
  proficiency: number;
  proficiency_label?: string;
  suspended?: boolean;
}

interface RegistrySkill {
  skill_id: string;
  name?: string;
  category?: string;
}

interface Props {
  agentId: string;
}

const PROFICIENCY_LABELS: Record<number, string> = {
  1: 'FOLLOW',
  2: 'ASSIST',
  3: 'APPLY',
  4: 'ENABLE',
  5: 'ADVISE',
  6: 'LEAD',
  7: 'SHAPE',
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

export default function SkillManagement({ agentId }: Props) {
  const [skills, setSkills] = useState<SkillRecord[]>([]);
  const [catalog, setCatalog] = useState<RegistrySkill[]>([]);
  const [pick, setPick] = useState('');
  const [confirmDownId, setConfirmDownId] = useState<string | null>(null);
  const [confirmSuspendId, setConfirmSuspendId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!agentId) return;
    try {
      const resp = await fetch(`/api/crew/${agentId}/skills`);
      if (!resp.ok) {
        setSkills([]);
        return;
      }
      const data = await resp.json();
      setSkills(Array.isArray(data?.skills) ? data.skills : []);
    } catch {
      setSkills([]);
    }
  }, [agentId]);

  const loadCatalog = useCallback(async () => {
    try {
      const resp = await fetch('/api/skills/registry');
      if (!resp.ok) {
        setCatalog([]);
        return;
      }
      const data = await resp.json();
      setCatalog(Array.isArray(data?.skills) ? data.skills : []);
    } catch {
      setCatalog([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await Promise.all([refresh(), loadCatalog()]);
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh, loadCatalog]);

  const acquire = useCallback(async () => {
    if (!pick) return;
    setError(null);
    try {
      const resp = await fetch(`/api/crew/${agentId}/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: pick, proficiency: 1 }),
      });
      if (!resp.ok) {
        let detail = 'Skill could not be acquired.';
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* keep default */
        }
        setError(detail);
        return;
      }
      setPick('');
      await refresh();
    } catch {
      setError('Acquisition failed.');
    }
  }, [agentId, pick, refresh]);

  const reLevel = useCallback(async (skillId: string, level: number) => {
    if (level < 1 || level > 7) return;
    try {
      const resp = await fetch(`/api/crew/${agentId}/skills/${skillId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proficiency: level }),
      });
      if (resp.ok) await refresh();
    } catch {
      /* honest-degrade */
    } finally {
      setConfirmDownId(null);
    }
  }, [agentId, refresh]);

  const suspend = useCallback(async (skillId: string) => {
    try {
      const resp = await fetch(`/api/crew/${agentId}/skills/${skillId}`, { method: 'DELETE' });
      if (resp.ok) await refresh();
    } catch {
      /* honest-degrade */
    } finally {
      setConfirmSuspendId(null);
    }
  }, [agentId, refresh]);

  const reinstate = useCallback(async (skillId: string) => {
    try {
      const resp = await fetch(`/api/crew/${agentId}/skills/${skillId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ suspended: false }),
      });
      if (resp.ok) await refresh();
    } catch {
      /* honest-degrade */
    }
  }, [agentId, refresh]);

  const held = new Set(skills.map(s => s.skill_id));
  const acquirable = catalog.filter(c => !held.has(c.skill_id));

  return (
    <div data-testid="skill-management">
      <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '4px 0 8px' }}>
        DEVELOPMENTAL SKILLS
      </div>

      {skills.length === 0 ? (
        <div style={{ fontSize: 11, color: '#666680' }}>No developmental skills.</div>
      ) : (
        skills.map(s => {
          const level = s.proficiency || 1;
          const label = PROFICIENCY_LABELS[level] || (s.proficiency_label || '').toUpperCase();
          return (
            <div
              key={s.skill_id}
              data-testid={`skill-row-${s.skill_id}`}
              data-suspended={s.suspended ? 'true' : 'false'}
              style={{
                border: '1px solid rgba(80,176,160,0.2)',
                background: s.suspended ? 'rgba(102,102,128,0.06)' : 'transparent',
                borderRadius: 4,
                padding: '8px 10px',
                margin: '6px 0',
                opacity: s.suspended ? 0.6 : 1,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 11, color: '#c8c8d4' }}>
                  {s.name || s.skill_id}
                  {s.category && <span style={{ color: '#666680' }}> &middot; {s.category}</span>}
                  {s.suspended && <span style={{ color: '#8888a0' }}> (suspended)</span>}
                </span>
                <span style={{ fontSize: 9, letterSpacing: 1, color: '#50b0a0' }}>{label}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <button
                  type="button"
                  data-testid={`skill-up-${s.skill_id}`}
                  onClick={() => reLevel(s.skill_id, level + 1)}
                  disabled={level >= 7}
                  style={{ ...chipStyle('#50b0a0'), opacity: level >= 7 ? 0.4 : 1 }}
                >
                  Level up
                </button>
                {confirmDownId === s.skill_id ? (
                  <button
                    type="button"
                    data-testid={`skill-down-confirm-${s.skill_id}`}
                    onClick={() => reLevel(s.skill_id, level - 1)}
                    style={chipStyle('#d0a030')}
                  >
                    Confirm down-level
                  </button>
                ) : (
                  <button
                    type="button"
                    data-testid={`skill-down-${s.skill_id}`}
                    onClick={() => setConfirmDownId(s.skill_id)}
                    disabled={level <= 1}
                    style={{ ...chipStyle('#8888a0'), opacity: level <= 1 ? 0.4 : 1 }}
                  >
                    Level down
                  </button>
                )}
                {s.suspended ? (
                  <button
                    type="button"
                    data-testid={`skill-reinstate-${s.skill_id}`}
                    onClick={() => reinstate(s.skill_id)}
                    style={chipStyle('#f0b060')}
                  >
                    Reinstate
                  </button>
                ) : confirmSuspendId === s.skill_id ? (
                  <button
                    type="button"
                    data-testid={`skill-suspend-confirm-${s.skill_id}`}
                    onClick={() => suspend(s.skill_id)}
                    style={chipStyle('#d05050')}
                  >
                    Confirm suspend
                  </button>
                ) : (
                  <button
                    type="button"
                    data-testid={`skill-suspend-${s.skill_id}`}
                    onClick={() => setConfirmSuspendId(s.skill_id)}
                    style={chipStyle('#8888a0')}
                  >
                    Suspend
                  </button>
                )}
              </div>
            </div>
          );
        })
      )}

      {/* Acquire a developmental skill from the registry catalog. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
        <select
          data-testid="skill-acquire-pick"
          value={pick}
          onChange={e => setPick(e.target.value)}
          style={{
            flex: 1,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: '#c8c8d4',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(240,176,96,0.2)',
            borderRadius: 4,
            padding: '4px 6px',
          }}
        >
          <option value="">Select a skill to acquire...</option>
          {acquirable.map(c => (
            <option key={c.skill_id} value={c.skill_id}>
              {c.name || c.skill_id}
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid="skill-acquire-submit"
          onClick={acquire}
          disabled={!pick}
          style={{
            ...chipStyle('#f0b060'),
            opacity: pick ? 1 : 0.4,
            cursor: pick ? 'pointer' : 'default',
          }}
        >
          Acquire
        </button>
      </div>
      {error && (
        <div data-testid="skill-acquire-error" style={{ fontSize: 10, color: '#d05050', marginTop: 4 }}>
          {error}
        </div>
      )}
    </div>
  );
}
