/**
 * AD-1011: Skill Coverage — the ship-wide skill registry view (#815 view 1).
 *
 * The civilization-level counterpart to the per-agent skill profile: for every
 * skill in the registry, how many crew hold it (and who, at what proficiency),
 * and which skills have NO holder (the coverage gap). Bound to the read-only
 * `GET /api/skills/coverage` aggregate (AD-1011 backend). The per-agent skill
 * *assignment* surface is the Profile Service tab (AD-983b/c) + SkillLibrary
 * CRUD; this is the read-only coverage lens above them.
 *
 * HXI compliance: stroke-only chrome, amber/teal accents, red gap flag, no emoji.
 */

import { useState, useEffect, useCallback } from 'react';

interface Holder {
  agent_id: string;
  callsign: string;
  proficiency: number;
  proficiency_label: string;
}

interface SkillCoverageRow {
  skill_id: string;
  name: string;
  category: string;
  holder_count: number;
  holders: Holder[];
  gap: boolean;
}

interface CoverageResponse {
  skills: SkillCoverageRow[];
  crew_count: number;
  gap_count: number;
}

export interface SkillCoverageProps {
  deps?: { fetchCoverage?: () => Promise<CoverageResponse> };
}

async function fetchCoverageApi(): Promise<CoverageResponse> {
  const resp = await fetch('/api/skills/coverage');
  if (!resp.ok) return { skills: [], crew_count: 0, gap_count: 0 };
  const data = await resp.json();
  return {
    skills: Array.isArray(data?.skills) ? data.skills : [],
    crew_count: typeof data?.crew_count === 'number' ? data.crew_count : 0,
    gap_count: typeof data?.gap_count === 'number' ? data.gap_count : 0,
  };
}

export default function SkillCoverage({ deps }: SkillCoverageProps = {}) {
  const _fetch = deps?.fetchCoverage ?? fetchCoverageApi;
  const [data, setData] = useState<CoverageResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    _fetch().then((d) => { if (alive) setData(d); }).catch(() => { if (alive) setData({ skills: [], crew_count: 0, gap_count: 0 }); });
    return () => { alive = false; };
  }, [_fetch]);

  const barWidth = useCallback((n: number): number => {
    const max = Math.max(1, data?.crew_count ?? 1);
    return Math.round((n / max) * 100);
  }, [data]);

  if (!data) {
    return <div data-testid="skill-coverage-loading" style={{ fontSize: 11, color: '#666680', padding: '6px 0' }}>Loading coverage…</div>;
  }

  return (
    <div data-testid="skill-coverage" style={{ fontFamily: "'JetBrains Mono', monospace", color: '#c8c8d4', marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: '#a8a8b8', letterSpacing: 0.5 }}>Skill Coverage</span>
        <span data-testid="skill-coverage-summary" style={{ fontSize: 10, color: '#8888a0' }}>
          {data.skills.length} skills · {data.crew_count} crew · {data.gap_count} gaps
        </span>
      </div>

      {data.skills.length === 0 ? (
        <div data-testid="skill-coverage-empty" style={{ fontSize: 11, color: '#8888a0', padding: '6px 0' }}>
          No skills in the registry.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.skills.map((s) => {
            const accent = s.gap ? '#d05050' : '#50b0a0';
            const isOpen = expanded === s.skill_id;
            return (
              <div key={s.skill_id} data-testid={`coverage-${s.skill_id}`} style={{ borderLeft: `3px solid ${accent}`, paddingLeft: 8 }}>
                <button
                  data-testid={`coverage-row-${s.skill_id}`}
                  onClick={() => setExpanded(isOpen ? null : s.skill_id)}
                  style={{ background: 'transparent', border: 'none', cursor: s.holder_count > 0 ? 'pointer' : 'default', color: '#c8c8d4', padding: '2px 0', width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10 }}
                >
                  <span style={{ fontSize: 11, minWidth: 160 }}>{s.name}</span>
                  {/* coverage bar */}
                  <span style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden', minWidth: 60 }}>
                    <span style={{ display: 'block', height: '100%', width: `${barWidth(s.holder_count)}%`, background: accent }} />
                  </span>
                  <span style={{ fontSize: 10, color: s.gap ? '#d05050' : '#8888a0', minWidth: 54, textAlign: 'right' }}>
                    {s.gap ? 'GAP' : `${s.holder_count} crew`}
                  </span>
                </button>
                {isOpen && s.holders.length > 0 && (
                  <div data-testid={`coverage-holders-${s.skill_id}`} style={{ fontSize: 9, color: '#8888a0', padding: '2px 0 6px 0' }}>
                    {s.holders.map((h) => (
                      <span key={h.agent_id} style={{ marginRight: 10 }}>
                        {h.callsign || h.agent_id} <span style={{ color: '#50b0a0' }}>({h.proficiency_label})</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export { fetchCoverageApi };
