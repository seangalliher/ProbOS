// AD-708c-1: unit tests for the pure 2D mesh projection module. Real `Agent`
// fixtures (plain typed objects — BF-287: no MagicMock-style stubs). Covers the
// re-derived visual language (trust -> color, confidence -> opacity, tier ->
// radius), the curated subset selection, the 2D ring layout, and a source-level
// guard proving the module pulls in no three.js / canvas-scene dependency.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  trustToCss,
  confidenceToOpacity,
  nodeRadius,
  selectMeshAgents,
  computeMeshLayout,
  type MeshViewport,
} from '../meshProjection';
import type { Agent } from '../../store/types';

// --- fixtures ---------------------------------------------------------------
function makeAgent(over: Partial<Agent> & { id: string }): Agent {
  return {
    id: over.id,
    agentType: over.agentType ?? 'cognitive',
    callsign: over.callsign ?? over.id,
    displayName: over.displayName ?? over.callsign ?? over.id,
    pool: over.pool ?? 'domain',
    state: over.state ?? 'active',
    confidence: over.confidence ?? 0.5,
    trust: over.trust ?? 0.5,
    tier: over.tier ?? 'domain',
    isCrew: over.isCrew ?? false,
    position: over.position ?? [0, 0, 0],
    createdAt: over.createdAt,
    activatedAt: over.activatedAt,
  };
}

const HEX_RE = /^#[0-9a-f]{6}$/;

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

/** True if every channel of `c` lies within the inclusive range of lo..hi. */
function between(c: string, lo: string, hi: string): boolean {
  const [r, g, b] = hexToRgb(c);
  const [lr, lg, lb] = hexToRgb(lo);
  const [hr, hg, hb] = hexToRgb(hi);
  const inRange = (v: number, a: number, z: number): boolean =>
    v >= Math.min(a, z) && v <= Math.max(a, z);
  return inRange(r, lr, hr) && inRange(g, lg, hg) && inRange(b, lb, hb);
}

// ============================================================================
describe('AD-708c-1 trustToCss', () => {
  it('trust 0 returns the silver/new stop', () => {
    expect(trustToCss(0)).toBe('#a0a8b8');
  });

  it('trust 0.2 lands in the violet (low) band', () => {
    expect(between(trustToCss(0.2), '#5848a0', '#7060a8')).toBe(true);
  });

  it('trust 0.5 lands in the blue (medium) band', () => {
    expect(between(trustToCss(0.5), '#6690b8', '#88a4c8')).toBe(true);
  });

  it('trust 0.85 lands in the amber (high) band', () => {
    expect(between(trustToCss(0.85), '#e8963c', '#f0b060')).toBe(true);
  });

  it('the 0.35 boundary is the blue band low stop exactly', () => {
    expect(trustToCss(0.35)).toBe('#6690b8');
  });

  it('the 0.7 boundary is the amber band low stop exactly', () => {
    expect(trustToCss(0.7)).toBe('#e8963c');
  });

  it('clamps trust > 1 to the amber high stop and < 0 to silver, always valid hex', () => {
    expect(trustToCss(1.5)).toBe('#f0b060');
    expect(trustToCss(-0.5)).toBe('#a0a8b8');
    expect(trustToCss(1.5)).toMatch(HEX_RE);
    expect(trustToCss(-0.5)).toMatch(HEX_RE);
  });
});

describe('AD-708c-1 confidenceToOpacity', () => {
  it('confidence 0 returns the 0.25 floor', () => {
    expect(confidenceToOpacity(0)).toBe(0.25);
  });

  it('confidence 1 returns full opacity', () => {
    expect(confidenceToOpacity(1)).toBe(1);
  });

  it('is monotonic increasing across the mid range', () => {
    const a = confidenceToOpacity(0.3);
    const b = confidenceToOpacity(0.5);
    const c = confidenceToOpacity(0.7);
    const d = confidenceToOpacity(0.9);
    expect(a).toBeLessThan(b);
    expect(b).toBeLessThan(c);
    expect(c).toBeLessThan(d);
  });

  it('clamps out-of-range confidence to [0.25, 1]', () => {
    expect(confidenceToOpacity(2)).toBe(1);
    expect(confidenceToOpacity(-1)).toBe(0.25);
  });
});

describe('AD-708c-1 nodeRadius', () => {
  it('core < utility < domain at equal confidence', () => {
    const core = nodeRadius('core', 0.5);
    const utility = nodeRadius('utility', 0.5);
    const domain = nodeRadius('domain', 0.5);
    expect(core).toBeLessThan(utility);
    expect(utility).toBeLessThan(domain);
  });

  it('rises with confidence', () => {
    expect(nodeRadius('core', 0)).toBeLessThan(nodeRadius('core', 1));
  });

  it('an unknown tier falls back to the utility base', () => {
    expect(nodeRadius('bogus', 0.5)).toBe(nodeRadius('utility', 0.5));
  });
});

describe('AD-708c-1 selectMeshAgents', () => {
  it('empty input returns empty', () => {
    expect(selectMeshAgents([])).toEqual([]);
  });

  it('sorts all crew before non-crew', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'n1', isCrew: false, trust: 0.9, callsign: 'Nova' }),
      makeAgent({ id: 'c1', isCrew: true, trust: 0.2, callsign: 'Yeo' }),
      makeAgent({ id: 'n2', isCrew: false, trust: 0.8, callsign: 'Atlas' }),
      makeAgent({ id: 'c2', isCrew: true, trust: 0.1, callsign: 'Data' }),
    ];
    const result = selectMeshAgents(agents);
    expect(result.slice(0, 2).every((a) => a.isCrew)).toBe(true);
    expect(result.slice(2).every((a) => !a.isCrew)).toBe(true);
  });

  it('sorts trust descending within a crew/non-crew group', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'a', isCrew: false, trust: 0.3, callsign: 'A' }),
      makeAgent({ id: 'b', isCrew: false, trust: 0.9, callsign: 'B' }),
      makeAgent({ id: 'c', isCrew: false, trust: 0.6, callsign: 'C' }),
    ];
    const trusts = selectMeshAgents(agents).map((a) => a.trust);
    expect(trusts).toEqual([0.9, 0.6, 0.3]);
  });

  it('caps at the limit', () => {
    const agents: Agent[] = Array.from({ length: 30 }, (_, i) =>
      makeAgent({ id: `a${i}`, trust: i / 30, callsign: `A${i}` }),
    );
    expect(selectMeshAgents(agents, 24)).toHaveLength(24);
  });

  it('is deterministic for equal trust via callsign ascending tiebreak', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'z', isCrew: false, trust: 0.5, callsign: 'Zeta' }),
      makeAgent({ id: 'a', isCrew: false, trust: 0.5, callsign: 'Alpha' }),
      makeAgent({ id: 'm', isCrew: false, trust: 0.5, callsign: 'Mu' }),
    ];
    expect(selectMeshAgents(agents).map((a) => a.callsign)).toEqual(['Alpha', 'Mu', 'Zeta']);
  });

  it('does not mutate the input array', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'a', isCrew: false, trust: 0.1, callsign: 'A' }),
      makeAgent({ id: 'b', isCrew: true, trust: 0.9, callsign: 'B' }),
    ];
    const snapshotIds = agents.map((a) => a.id);
    selectMeshAgents(agents);
    expect(agents.map((a) => a.id)).toEqual(snapshotIds);
  });
});

describe('AD-708c-1 computeMeshLayout', () => {
  const viewport: MeshViewport = { width: 360, height: 640 };
  const cx = viewport.width / 2;
  const cy = viewport.height / 2;

  it('empty input returns empty', () => {
    expect(computeMeshLayout([], viewport)).toEqual([]);
  });

  it('a single node sits on its tier ring, not dead-center', () => {
    const nodes = computeMeshLayout([makeAgent({ id: 'solo', tier: 'core' })], viewport);
    expect(nodes).toHaveLength(1);
    const n = nodes[0];
    // Not both coordinates equal the center.
    expect(n.x === cx && n.y === cy).toBe(false);
    // It lies on the core ring (distance from center > 0).
    const dist = Math.hypot(n.x - cx, n.y - cy);
    expect(dist).toBeGreaterThan(0);
  });

  it('places every node within the viewport bounds with distinct positions', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'c1', tier: 'core', trust: 0.8, confidence: 0.9 }),
      makeAgent({ id: 'c2', tier: 'core', trust: 0.4, confidence: 0.3 }),
      makeAgent({ id: 'u1', tier: 'utility', trust: 0.5, confidence: 0.6 }),
      makeAgent({ id: 'd1', tier: 'domain', trust: 0.1, confidence: 0.2 }),
      makeAgent({ id: 'd2', tier: 'domain', trust: 0.95, confidence: 1 }),
    ];
    const nodes = computeMeshLayout(agents, viewport);
    expect(nodes).toHaveLength(agents.length);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(viewport.width);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(viewport.height);
    }
    const keys = nodes.map((n) => `${n.x.toFixed(4)},${n.y.toFixed(4)}`);
    expect(new Set(keys).size).toBe(nodes.length);
  });

  it('orders rings by tier — a core node is nearer center than a domain node', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'core', tier: 'core' }),
      makeAgent({ id: 'domain', tier: 'domain' }),
    ];
    const nodes = computeMeshLayout(agents, viewport);
    const core = nodes.find((n) => n.id === 'core')!;
    const domain = nodes.find((n) => n.id === 'domain')!;
    const coreDist = Math.hypot(core.x - cx, core.y - cy);
    const domainDist = Math.hypot(domain.x - cx, domain.y - cy);
    expect(coreDist).toBeLessThan(domainDist);
  });

  it('derives each node color/opacity/radius from its agent', () => {
    const agent = makeAgent({ id: 'x', tier: 'utility', trust: 0.85, confidence: 0.7 });
    const nodes = computeMeshLayout([agent], viewport);
    const n = nodes[0];
    expect(n.color).toBe(trustToCss(0.85));
    expect(n.opacity).toBe(confidenceToOpacity(0.7));
    expect(n.radius).toBe(nodeRadius('utility', 0.7));
    expect(n.tier).toBe('utility');
    expect(n.callsign).toBe(agent.callsign);
  });

  it('is deterministic — two calls deep-equal', () => {
    const agents: Agent[] = [
      makeAgent({ id: 'a', tier: 'core' }),
      makeAgent({ id: 'b', tier: 'utility' }),
      makeAgent({ id: 'c', tier: 'domain' }),
    ];
    expect(computeMeshLayout(agents, viewport)).toEqual(computeMeshLayout(agents, viewport));
  });
});

describe('AD-708c-1 three-free guard', () => {
  it('the module source imports no three.js and no canvas-scene module', () => {
    // Vitest runs with its root as cwd (D:/ProbOS/ui), so resolve the module
    // from there rather than import.meta.url (jsdom rewrites the meta URL to a
    // non-file scheme, which readFileSync rejects).
    const raw = readFileSync(resolve(process.cwd(), 'src/mesh2d/meshProjection.ts'), 'utf8');
    // Strip comments so the module's own explanatory prose (which names the
    // forbidden modules) does not trip the substring check — only real code
    // (imports) is inspected.
    const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toContain("from 'three'");
    expect(code).not.toContain('canvas/scene');
    expect(code).not.toContain('canvas/agents');
    // Positively confirm the ONLY store reference is the type-only Agent import.
    expect(code).toContain("import type { Agent } from '../store/types'");
  });
});
