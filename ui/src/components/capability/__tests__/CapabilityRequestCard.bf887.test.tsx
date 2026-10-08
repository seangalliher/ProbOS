import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import type { Agent, CapabilityApprovalView } from '../../../store/types';
import { useStore } from '../../../store/useStore';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { CapabilityRequestCard } from '../CapabilityRequestCard';

// BF-887 (#1163 runbook row 3): the Bridge card named Ezri as her agent id.
const REQUEST_ID = '94c4506a-aba5-42b8-b437-73649bcf70c8';
const AGENT_ID = 'counselor_counselor_0_67c601cb';

function row(): CapabilityApprovalView {
  return {
    id: REQUEST_ID, agent_id: AGENT_ID, kind: 'continue',
    target: 'continue: For each of the top 15 Python packages on PyPI, tell me the release date of its current version and its license.',
    rationale: 'The conversational turn reached its step limit after 1 pass(es) with the task still open.',
    created_at: 10, work_item_id: 'c01dbd32efd5', status: 'pending', decided_at: null,
    decided_by: '', decision_reason: '', can_retry_fulfilment: false,
    payload: {
      tool_id: 'dm_agentic', action: 'continue', params: {}, scope_key: '', session_id: null,
      thread_id: 'e879c64b78d24d6382e28555c9fec943',
    },
  };
}

function crew(callsign: string): Agent {
  return {
    id: AGENT_ID, agentType: 'counselor', callsign, displayName: 'Counselor', pool: 'counselor',
    state: 'active', confidence: 0.8, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
  };
}

function requester(): HTMLElement {
  return within(screen.getByTestId('capability-request-card')).getByTestId('capability-requesting-agent');
}

beforeEach(() => {
  // Loaded already, so the card's standing-approval policy read never reaches the network.
  useSettingsStore.setState({ loaded: true, loading: false, snapshot: {
    config: { approval_inbox: { standing_rules_enabled: false } }, secret_present: {}, sections: [],
    domain_counts: {}, domain_order: [], section_count: 0, config_path: '', uptime_seconds: 0, csrf_token: '',
  } });
});
afterEach(() => {
  cleanup();
  useStore.setState({ agents: useStore.getInitialState().agents });
});

describe('BF-887 the approval card names the requesting agent', () => {
  it('names the agent by callsign and keeps the id as the tooltip', () => {
    useStore.setState({ agents: new Map([[AGENT_ID, crew('Ezri')]]) });
    render(<CapabilityRequestCard requestId={REQUEST_ID} request={row()} />);
    const card = screen.getByTestId('capability-request-card');
    expect(card.textContent).toContain(`Request ${REQUEST_ID} \u00b7 Agent Ezri`);
    expect(card.textContent).not.toContain(`Agent ${AGENT_ID}`);
    expect(requester().textContent).toBe('Ezri');
    expect(requester()).toHaveAttribute('title', AGENT_ID);
  });

  it('falls back to the agent id when the roster does not know the agent', () => {
    useStore.setState({ agents: new Map() });
    render(<CapabilityRequestCard requestId={REQUEST_ID} request={row()} />);
    expect(requester().textContent).toBe(AGENT_ID);
    expect(requester()).toHaveAttribute('title', AGENT_ID);
  });

  it('falls back to the agent id when the callsign is blank', () => {
    useStore.setState({ agents: new Map([[AGENT_ID, crew('')]]) });
    render(<CapabilityRequestCard requestId={REQUEST_ID} request={row()} />);
    expect(requester().textContent).toBe(AGENT_ID);
  });

  it('shows a callsign literally, with invisible characters escaped', () => {
    useStore.setState({ agents: new Map([[AGENT_ID, crew('Ez\u202eri')]]) });
    render(<CapabilityRequestCard requestId={REQUEST_ID} request={row()} />);
    expect(requester().textContent).toBe('Ez\\u202eri');
  });
});
