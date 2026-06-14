/** AD-1000c + AD-1002: Profile Service Configuration tab — the per-agent hub.
 *
 *  The "button on the profile card" from the Agent Customizations epic (#944):
 *  a dedicated, crew-only tab that gives each agent's configuration a first-class
 *  home. Hosts the full set of axes (VS Code Agent Customizations parity):
 *    - Capabilities (AD-983c/1000b CapabilityPanel: Tools · Skills · mesh)
 *    - Instructions (AD-1002: the composing Standing-Order tiers + identity)
 *    - Model (AD-1002: the agent's resolved LLM tier)
 *
 *  Instructions + Model are READ-ONLY (the standing-order tiers + tier selection
 *  are configured elsewhere; this surfaces what shapes the agent). HXI: stroke/
 *  text only, no emoji.
 */
import { useEffect, useState, useCallback } from 'react';
import { CapabilityPanel } from './CapabilityPanel';

const _AMBER = '#f0b060';
const _DIM = '#666680';

export interface InstructionTier {
  tier: string;
  source_file: string | null;
  present: boolean;
  char_count: number;
}
export interface AgentInstructions {
  agent_type: string;
  department: string | null;
  instructions: { present: boolean; char_count: number; preview: string };
  standing_order_tiers: InstructionTier[];
  model: { resolved_tier: string; available_tiers: string[]; note: string };
}

export async function fetchInstructions(agentId: string): Promise<AgentInstructions> {
  const resp = await fetch(`/api/agent/${agentId}/instructions`);
  if (!resp.ok) throw new Error(`instructions fetch failed: ${resp.status}`);
  return resp.json();
}

function tierLabel(tier: string): string {
  switch (tier) {
    case 'federation': return 'Federation';
    case 'ship': return 'Ship';
    case 'department': return 'Department';
    case 'agent': return 'Personal';
    default: return tier;
  }
}

interface InstructionsProps {
  agentId: string;
  fetcher?: (agentId: string) => Promise<AgentInstructions>;
}

/** AD-1002: read-only Instructions + Model sections. */
export function InstructionsSection({ agentId, fetcher }: InstructionsProps) {
  const _fetch = fetcher ?? fetchInstructions;
  const [info, setInfo] = useState<AgentInstructions | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try { setInfo(await _fetch(agentId)); } catch { setError(true); }
  }, [agentId, _fetch]);

  useEffect(() => { void load(); }, [load]);

  if (error) {
    return <div data-testid="instructions-error" style={{ color: _DIM, fontSize: 11, padding: '4px 0' }}>Instructions unavailable.</div>;
  }
  if (info === null) {
    return <div data-testid="instructions-loading" style={{ color: _DIM, fontSize: 11, padding: '4px 0' }}>Loading…</div>;
  }

  return (
    <div data-testid="instructions-section">
      <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '14px 0 4px' }}>
        INSTRUCTIONS
      </div>
      <div style={{ color: _DIM, fontSize: 10, marginBottom: 6 }}>
        The standing-order tiers that compose this agent's behavior. Read-only.
      </div>
      {info.standing_order_tiers.map((t) => (
        <div
          key={t.tier}
          data-testid={`instr-tier-${t.tier}`}
          style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0', fontSize: 11 }}
        >
          <span style={{ color: t.present ? '#c8d0e0' : _DIM, minWidth: 96 }}>{tierLabel(t.tier)}</span>
          <span style={{ color: t.present ? _AMBER : '#555568', fontSize: 9 }}>
            {t.present ? `${t.char_count} chars` : 'none'}
          </span>
          {t.source_file && <span style={{ color: '#555568', fontSize: 9, fontFamily: 'monospace' }}>{t.source_file}</span>}
        </div>
      ))}

      <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, margin: '14px 0 4px' }}>
        MODEL
      </div>
      <div data-testid="model-resolved" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
        <span style={{ color: '#c8d0e0', minWidth: 96 }}>Tier</span>
        <span style={{ color: _AMBER, fontSize: 11 }}>{info.model.resolved_tier}</span>
      </div>
      <div style={{ color: _DIM, fontSize: 10, marginTop: 4 }}>
        Available: {info.model.available_tiers.join(' · ') || 'none'}
      </div>
      <div style={{ color: '#555568', fontSize: 9, lineHeight: 1.5, marginTop: 4 }}>{info.model.note}</div>
    </div>
  );
}

interface Props {
  agentId: string;
  /** Optional injected fetchers, forwarded to children (tests). */
  deps?: React.ComponentProps<typeof CapabilityPanel>['deps'] & {
    fetchInstructions?: (agentId: string) => Promise<AgentInstructions>;
  };
}

export function ProfileServiceTab({ agentId, deps }: Props) {
  return (
    <div
      data-testid="profile-service-tab"
      style={{ padding: '10px 12px', overflowY: 'auto', height: '100%', fontSize: 12 }}
    >
      <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, marginBottom: 6 }}>
        SERVICE CONFIGURATION
      </div>
      <div style={{ color: '#666680', fontSize: 10, lineHeight: 1.6, marginBottom: 10 }}>
        <strong style={{ color: '#8888a0' }}>Tools</strong> are callable functions
        wired into this agent&apos;s context (file I/O, web, run code) &mdash; the
        Copilot sense of &ldquo;tool.&rdquo;{' '}
        <strong style={{ color: '#8888a0' }}>Skills</strong> are cognitive
        specialties from its role.{' '}
        <strong style={{ color: '#8888a0' }}>Capabilities</strong> are mesh intents
        it can request: &ldquo;Serves&rdquo; are this agent&apos;s own specialty
        (only it fulfils them); &ldquo;Can request&rdquo; is the ship-wide surface
        any agent can call. Tools and skills are enabled per agent.
      </div>
      <CapabilityPanel agentId={agentId} deps={deps} />
      <InstructionsSection agentId={agentId} fetcher={deps?.fetchInstructions} />
    </div>
  );
}
