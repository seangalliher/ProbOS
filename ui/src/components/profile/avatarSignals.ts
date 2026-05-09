/** AD-721 D4: Map runtime signals → VRM expression channels.
 *
 * v1 derives signals from the existing useStore. Conservative mapping —
 * unknown agents return all-zero signals (idle, no alert) rather than
 * throwing. Real agent telemetry shapes evolve; this helper keeps the
 * popout decoupled from the store schema.
 */

import type { Agent } from '../../store/types';

export interface AgentSignals {
  trust_delta: number;       // last cycle trust delta, [-1, +1]
  load: number;              // 0..1 (1 = LLM call active)
  working_state: 'idle' | 'responding' | 'blocked';
  tier3_alert: boolean;
}

const ZERO: AgentSignals = {
  trust_delta: 0,
  load: 0,
  working_state: 'idle',
  tier3_alert: false,
};

/** Read signals from the Zustand store. Pure function over the store snapshot. */
export function deriveAgentSignals(
  agentId: string,
  store: { agents?: Map<string, Agent> | null; processing?: boolean | null; notifications?: { tier?: string }[] | null },
): AgentSignals {
  if (!store) return { ...ZERO };
  const agent = store.agents?.get?.(agentId);
  if (!agent) return { ...ZERO };

  // Map state → working_state.
  let working_state: AgentSignals['working_state'] = 'idle';
  if (agent.state === 'degraded') working_state = 'blocked';
  else if (agent.state === 'active' && store.processing) working_state = 'responding';

  // Trust delta: v1 has no per-agent delta on the store; expose 0 and let
  // future revisions wire it. (Trust history → delta belongs in the store.)
  const trust_delta = 0;

  const load = store.processing ? 1.0 : 0.0;

  // Tier-3 alert: any notification flagged tier=3 surfaces here.
  const tier3_alert = !!store.notifications?.some(n => n?.tier === '3' || n?.tier === 'tier3');

  return { trust_delta, load, working_state, tier3_alert };
}
