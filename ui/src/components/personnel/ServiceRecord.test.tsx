/** AD-897 (Wave 255) vitest — Service Record detail view (the ESR).
 * Bound to GET /api/crew/{id}/record, /standing-orders, /tools. Verifies each
 * section renders from a seeded record, empty facets degrade gracefully, and
 * the HXI no-emoji guard. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import ServiceRecord from './ServiceRecord';

const RECORD = {
  agent_id: 'agent-data',
  callsign: 'Data',
  department: 'science',
  rank: 'commander',
  lifecycle_state: 'active',
  personality: {
    openness: 0.9,
    conscientiousness: 0.8,
    extraversion: 0.3,
    agreeableness: 0.7,
    neuroticism: 0.1,
  },
  trust: '0.82',
  agency_level: 'autonomous',
  skill_count: 4,
  avg_proficiency: 0.65,
  episode_count: 142,
  cognitive_skills: [
    { name: 'Sensor Analysis', description: 'Interpret sensor sweeps', skill_id: 'cs-1' },
  ],
  cognitive_skill_count: 1,
  tools: ['scanner'],
  tool_count: 1,
  duties: [
    { duty_id: 'd-1', description: 'Morning sensor sweep', cron: '0 6 * * *', priority: 2 },
  ],
  duty_count: 1,
  active_assignments: [
    { id: 'w-1', title: 'Analyze anomaly', work_type: 'analysis', status: 'in_progress', priority: 1 },
  ],
  billet: {
    billet_id: 'ops-officer',
    title: 'Operations Officer',
    department: 'science',
    qualified: false,
    missing_qualifications: ['warp-core-cert'],
  },
};

const ORDERS = {
  agent_id: 'agent-data',
  agent_type: 'ScienceAgent',
  tiers: [
    { tier: 'federation', source_file: 'federation.md', present: true, text: 'Prime directive applies.' },
    { tier: 'ship', source_file: 'ship.md', present: true, text: 'Maintain readiness.' },
    { tier: 'department', source_file: null, present: false, text: '' },
    { tier: 'agent', source_file: null, present: false, text: '' },
  ],
};

const TOOLS = {
  agent_id: 'agent-data',
  certifications: [
    {
      grant_id: 'g-1',
      tool_id: 'scanner',
      permission: 'read',
      is_restriction: false,
      reason: 'role',
      issued_by: 'captain',
      issued_at: '2026-01-01',
      tool: { tool_id: 'scanner', description: 'Sensor scanner' },
    },
  ],
  count: 1,
};

function stubFetch(map: Record<string, any>) {
  global.fetch = vi.fn((url: string) => {
    for (const key of Object.keys(map)) {
      if (url.includes(key)) {
        return Promise.resolve({ ok: true, json: async () => map[key] }) as any;
      }
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) }) as any;
  }) as any;
}

const SUMMARY = {
  agent_id: 'agent-data',
  agent_type: 'ScienceAgent',
  callsign: 'Data',
  post: 'Operations Officer',
  department: 'science',
  rank: 'commander',
};

beforeEach(() => {
  stubFetch({ '/record': RECORD, '/standing-orders': ORDERS, '/tools': TOOLS });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ServiceRecord (AD-897)', () => {
  it('1. renders every section from a seeded record', async () => {
    render(<ServiceRecord agentId="agent-data" summary={SUMMARY} />);
    // Identity & Role
    expect(await screen.findByTestId('sr-section-identity')).toBeTruthy();
    expect(screen.getByText('Data')).toBeTruthy();
    // Skills — developmental count and cognitive-skill count are labelled
    // distinctly so the count never contradicts the visible list (BF: "Skills 0"
    // shown above a populated cognitive-skill list).
    expect(screen.getByTestId('sr-section-skills')).toBeTruthy();
    expect(await screen.findByText('Sensor Analysis')).toBeTruthy();
    expect(screen.getByText('Developmental skills')).toBeTruthy();
    expect(screen.getByTestId('sr-cognitive-skills-header').textContent).toContain('COGNITIVE SKILLS (1)');
    // Qualifications — tool cert + billet missing quals (both homes)
    expect(await screen.findByTestId('sr-tool-cert-scanner')).toBeTruthy();
    expect(await screen.findByTestId('sr-billet-missing')).toBeTruthy();
    expect(screen.getByText(/warp-core-cert/)).toBeTruthy();
    // Duties & Active Assignments
    expect(await screen.findByText('Morning sensor sweep')).toBeTruthy();
    expect(screen.getByText('Analyze anomaly')).toBeTruthy();
    // Standing Orders — present + absent tiers
    expect(await screen.findByTestId('sr-order-tier-federation')).toBeTruthy();
    expect(screen.getByTestId('sr-order-tier-department')).toBeTruthy();
    // Experience
    expect(screen.getByTestId('sr-section-experience')).toBeTruthy();
    expect(screen.getByText('0.82')).toBeTruthy();
  });

  it('2. empty facets degrade gracefully (no duties / assignments / tools)', async () => {
    const empty = {
      agent_id: 'agent-ghost',
      callsign: 'Ghost',
      department: null,
      rank: null,
      skill_count: 0,
      duties: [],
      active_assignments: [],
      cognitive_skills: [],
    };
    stubFetch({ '/record': empty, '/standing-orders': { tiers: [] }, '/tools': { certifications: [] } });
    render(<ServiceRecord agentId="agent-ghost" summary={null} />);
    expect(await screen.findByText('No standing duties.')).toBeTruthy();
    expect(screen.getByText('No active assignments.')).toBeTruthy();
    expect(screen.getByText('No tool certifications.')).toBeTruthy();
    expect(screen.getByText('No standing orders.')).toBeTruthy();
    expect(screen.getByText('No cognitive skills.')).toBeTruthy();
  });

  it('3. honest-degrades to the summary header when every fetch fails', async () => {
    stubFetch({});
    render(<ServiceRecord agentId="agent-data" summary={SUMMARY} />);
    // Identity falls back to the roster summary props.
    expect(await screen.findByText('Data')).toBeTruthy();
    expect(screen.getAllByText(/Operations Officer/).length).toBeGreaterThan(0);
    expect(screen.getByText('No standing duties.')).toBeTruthy();
  });

  it('4. fully-qualified billet renders the positive standing', async () => {
    const qualified = { ...RECORD, billet: { billet_id: 'ops-officer', title: 'Operations Officer', qualified: true, missing_qualifications: [] } };
    stubFetch({ '/record': qualified, '/standing-orders': ORDERS, '/tools': TOOLS });
    render(<ServiceRecord agentId="agent-data" summary={SUMMARY} />);
    expect(await screen.findByTestId('sr-billet-qualified')).toBeTruthy();
  });

  it('5. output contains no emoji (HXI Principle #3)', async () => {
    const { container } = render(<ServiceRecord agentId="agent-data" summary={SUMMARY} />);
    await screen.findByText('Sensor Analysis');
    expect(/\p{Extended_Pictographic}/u.test(container.textContent || '')).toBe(false);
  });
});
