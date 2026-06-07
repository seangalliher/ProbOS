/**
 * AD-897: Service Record detail view — the Workday-style ESR.
 *
 * The per-agent personnel profile rendered inside the Crew Personnel Console
 * (AD-896), filling the detail pane the shell left as a placeholder. Read-only:
 * the grant/revoke and skill-edit actions live in AD-898/899.
 *
 * Bound to three backend reads, fetched in parallel keyed on the selected
 * agent_id:
 *   - `GET /api/crew/{id}/record`          — ACM consolidated profile + billet
 *                                            + active_assignments
 *   - `GET /api/crew/{id}/standing-orders` — the four standing-order tiers
 *   - `GET /api/crew/{id}/tools`           — certified tool grants
 *
 * Sectioned for progressive disclosure: Identity & Role, Skills & Proficiency,
 * Qualifications (tool certs + billet qualification standing — both homes),
 * Duties & Active Assignments, Standing Orders, Experience. Each facet
 * honest-degrades to a calm empty state.
 *
 * HXI compliance: stroke-only chrome, amber accents, no emoji.
 */

import { useState, useEffect } from 'react';
import StandingOrders from './StandingOrders';
import SkillManagement from './SkillManagement';

interface Personality {
  openness?: number;
  conscientiousness?: number;
  extraversion?: number;
  agreeableness?: number;
  neuroticism?: number;
}

interface Duty {
  duty_id: string;
  description: string;
  cron?: string | null;
  interval_seconds?: number | null;
  priority?: number;
}

interface Assignment {
  id: string;
  title: string;
  work_type?: string;
  status?: string;
  priority?: number;
}

interface Billet {
  billet_id?: string;
  title?: string | null;
  department?: string | null;
  qualified?: boolean;
  missing_qualifications?: string[];
}

interface CognitiveSkill {
  name: string;
  description: string;
  skill_id: string;
}

interface CrewRecord {
  agent_id?: string;
  callsign?: string;
  display_name?: string;
  department?: string;
  rank?: string;
  lifecycle_state?: string;
  personality?: Personality;
  trust?: string;
  agency_level?: string;
  skill_count?: number;
  avg_proficiency?: number;
  episode_count?: number;
  cognitive_skills?: CognitiveSkill[];
  cognitive_skill_count?: number;
  tools?: string[];
  tool_count?: number;
  duties?: Duty[];
  duty_count?: number;
  active_assignments?: Assignment[];
  billet?: Billet;
}

interface OrderTier {
  tier: string;
  source_file?: string | null;
  present: boolean;
  text: string;
}

interface ToolCert {
  grant_id: string;
  tool_id: string;
  permission: string;
  is_restriction: boolean;
  reason?: string | null;
  issued_by?: string | null;
  issued_at?: string | null;
  tool?: { tool_id?: string; description?: string } | null;
}

interface RosterSummary {
  agent_id: string;
  agent_type: string;
  callsign?: string;
  post?: string | null;
  department?: string | null;
  rank?: string | null;
}

interface Props {
  agentId: string;
  summary?: RosterSummary | null;
}

const BIG_FIVE: Array<[keyof Personality, string]> = [
  ['openness', 'Openness'],
  ['conscientiousness', 'Conscientiousness'],
  ['extraversion', 'Extraversion'],
  ['agreeableness', 'Agreeableness'],
  ['neuroticism', 'Neuroticism'],
];

function sectionHeader(label: string): React.CSSProperties {
  return {
    fontSize: 10,
    letterSpacing: 1.5,
    fontWeight: 700,
    color: '#f0b060',
    textTransform: 'uppercase',
    margin: '20px 0 8px',
    paddingBottom: 4,
    borderBottom: '1px solid rgba(240, 176, 96, 0.15)',
  };
}

function Bar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: '#50b0a0', borderRadius: 2 }} />
    </div>
  );
}

export default function ServiceRecord({ agentId, summary }: Props) {
  const [record, setRecord] = useState<CrewRecord | null>(null);
  const [tiers, setTiers] = useState<OrderTier[]>([]);
  const [certs, setCerts] = useState<ToolCert[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    setLoading(true);
    setRecord(null);
    setTiers([]);
    setCerts([]);
    (async () => {
      const safeJson = async (url: string): Promise<any | null> => {
        try {
          const resp = await fetch(url);
          if (!resp.ok) return null;
          return await resp.json();
        } catch {
          return null;
        }
      };
      const [rec, orders, tools] = await Promise.all([
        safeJson(`/api/crew/${agentId}/record`),
        safeJson(`/api/crew/${agentId}/standing-orders`),
        safeJson(`/api/crew/${agentId}/tools`),
      ]);
      if (cancelled) return;
      // honest-degrade: the record endpoint can return roster-shaped or null
      // data; only accept an object that carries an agent_id facet.
      setRecord(rec && typeof rec === 'object' && 'agent_id' in rec ? rec : null);
      setTiers(Array.isArray(orders?.tiers) ? orders.tiers : []);
      setCerts(Array.isArray(tools?.certifications) ? tools.certifications : []);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const rec = record || {};
  const callsign = rec.callsign || summary?.callsign || summary?.agent_type || agentId;
  const department = rec.department || summary?.department || null;
  const rank = rec.rank || summary?.rank || null;
  const post = rec.billet?.title || summary?.post || null;
  const personality = rec.personality || {};
  const duties = rec.duties || [];
  const assignments = rec.active_assignments || [];
  const cognitiveSkills = rec.cognitive_skills || [];
  const billet = rec.billet;

  const labelRow = (label: string, value: React.ReactNode) => (
    <div style={{ display: 'flex', gap: 12, fontSize: 11, padding: '2px 0' }}>
      <span style={{ width: 130, flexShrink: 0, color: '#8888a0' }}>{label}</span>
      <span style={{ color: '#c8c8d4' }}>{value}</span>
    </div>
  );

  return (
    <div data-testid="service-record">
      {loading && (
        <div style={{ fontSize: 11, color: '#666680', marginBottom: 8 }}>
          Loading service record...
        </div>
      )}

      {/* Identity & Role */}
      <div data-testid="sr-section-identity">
        <div style={{ fontSize: 16, fontWeight: 700, color: '#f0b060', letterSpacing: 0.5 }}>
          {callsign}
        </div>
        <div style={{ fontSize: 11, color: '#8888a0', marginTop: 2 }}>
          {post || 'Unbilleted'}{department ? ` \u00b7 ${department}` : ''}
        </div>
        <div style={{ marginTop: 12 }}>
          {labelRow('Rank', rank || '\u2014')}
          {labelRow('Department', department || '\u2014')}
          {labelRow('Post / Billet', post || 'Unbilleted')}
          {rec.lifecycle_state && labelRow('Lifecycle', rec.lifecycle_state)}
        </div>
        {Object.keys(personality).length > 0 && (
          <div style={{ marginTop: 12 }} data-testid="sr-personality">
            {BIG_FIVE.map(([key, label]) => {
              const v = personality[key];
              if (typeof v !== 'number') return null;
              return (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '2px 0' }}>
                  <span style={{ width: 130, flexShrink: 0, fontSize: 10, color: '#8888a0' }}>{label}</span>
                  <Bar value={v} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Skills & Proficiency */}
      <div data-testid="sr-section-skills">
        <div style={sectionHeader('Skills & Proficiency')}>Skills &amp; Proficiency</div>
        {labelRow('Developmental skills', String(rec.skill_count ?? 0))}
        {typeof rec.avg_proficiency === 'number' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
            <span style={{ width: 130, flexShrink: 0, fontSize: 11, color: '#8888a0' }}>Avg proficiency</span>
            <Bar value={rec.avg_proficiency} />
          </div>
        )}
        <div
          data-testid="sr-cognitive-skills-header"
          style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '10px 0 4px' }}
        >
          COGNITIVE SKILLS ({rec.cognitive_skill_count ?? cognitiveSkills.length})
        </div>
        {cognitiveSkills.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680', padding: '4px 0' }}>No cognitive skills.</div>
        ) : (
          cognitiveSkills.map(s => (
            <div key={s.skill_id} style={{ fontSize: 11, padding: '3px 0' }}>
              <span style={{ color: '#c8c8d4' }}>{s.name}</span>
              <span style={{ color: '#666680' }}> — {s.description}</span>
            </div>
          ))
        )}
        <div style={{ marginTop: 12 }}>
          <SkillManagement agentId={agentId} />
        </div>
      </div>

      {/* Qualifications — both homes: tool certs (AD-894) + billet quals (AD-595d) */}
      <div data-testid="sr-section-qualifications">
        <div style={sectionHeader('Qualifications')}>Qualifications</div>
        <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '4px 0' }}>
          CERTIFIED TOOLS
        </div>
        {certs.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680' }}>No tool certifications.</div>
        ) : (
          certs.map(c => (
            <div
              key={c.grant_id}
              data-testid={`sr-tool-cert-${c.tool_id}`}
              style={{ fontSize: 11, padding: '2px 0', color: c.is_restriction ? '#d05050' : '#c8c8d4' }}
            >
              {c.tool_id} · {c.permission}{c.is_restriction ? ' (restricted)' : ''}
            </div>
          ))
        )}
        <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '10px 0 4px' }}>
          BILLET QUALIFICATION STANDING
        </div>
        {!billet ? (
          <div style={{ fontSize: 11, color: '#666680' }}>No billet assigned.</div>
        ) : billet.qualified ? (
          <div style={{ fontSize: 11, color: '#50b0a0' }} data-testid="sr-billet-qualified">
            Fully qualified for {billet.title || billet.billet_id}.
          </div>
        ) : (
          <div data-testid="sr-billet-missing">
            <div style={{ fontSize: 11, color: '#d0a030' }}>
              Missing qualifications for {billet.title || billet.billet_id}:
            </div>
            {(billet.missing_qualifications || []).map(m => (
              <div key={m} style={{ fontSize: 11, color: '#c8c8d4', paddingLeft: 8 }}>· {m}</div>
            ))}
          </div>
        )}
      </div>

      {/* Duties & Active Assignments */}
      <div data-testid="sr-section-duties">
        <div style={sectionHeader('Duties & Active Assignments')}>Duties &amp; Active Assignments</div>
        <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '4px 0' }}>
          STANDING DUTIES
        </div>
        {duties.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680' }}>No standing duties.</div>
        ) : (
          duties.map(d => (
            <div key={d.duty_id} style={{ fontSize: 11, padding: '2px 0' }}>
              <span style={{ color: '#c8c8d4' }}>{d.description}</span>
              {d.cron && <span style={{ color: '#666680' }}> ({d.cron})</span>}
            </div>
          ))
        )}
        <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '10px 0 4px' }}>
          ACTIVE ASSIGNMENTS
        </div>
        {assignments.length === 0 ? (
          <div style={{ fontSize: 11, color: '#666680' }}>No active assignments.</div>
        ) : (
          assignments.map(a => (
            <div key={a.id} style={{ fontSize: 11, padding: '2px 0' }}>
              <span style={{ color: '#c8c8d4' }}>{a.title}</span>
              {a.status && <span style={{ color: '#666680' }}> — {a.status}</span>}
            </div>
          ))
        )}
      </div>

      {/* Standing Orders — read-only four tiers (AD-893) + governed Directives panel (AD-900/901) */}
      <div data-testid="sr-section-orders">
        <div style={sectionHeader('Standing Orders')}>Standing Orders</div>
        <StandingOrders agentId={agentId} tiers={tiers} />
      </div>

      {/* Experience */}
      <div data-testid="sr-section-experience">
        <div style={sectionHeader('Experience')}>Experience</div>
        {labelRow('Trust', rec.trust || '\u2014')}
        {labelRow('Earned agency', rec.agency_level || '\u2014')}
        {labelRow('Episodes', String(rec.episode_count ?? 0))}
      </div>
    </div>
  );
}
