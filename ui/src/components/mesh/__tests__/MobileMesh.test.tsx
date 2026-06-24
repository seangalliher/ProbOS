// AD-708c-2: RTL tests for MobileMesh — the standalone 2D SVG mesh. Seeds the
// REAL useStore (BF-287: plain typed Agent/Connection fixtures, no MagicMock
// stubs), renders the component in isolation (it is wired nowhere in the app —
// AD-708c-3 does that), and asserts node/edge geometry comes from the AD-708c-1
// projection. A source-level guard proves MobileMesh pulls in no three.js /
// canvas dependency (a phone must never load three.js).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import MobileMesh from '../MobileMesh';
import { useStore } from '../../../store/useStore';
import { trustToCss, nodeRadius, confidenceToOpacity } from '../../../mesh2d/meshProjection';
import type { Agent, Connection } from '../../../store/types';

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

function seed(agents: Agent[], connections: Connection[] = []): void {
  useStore.setState({
    agents: new Map(agents.map((a) => [a.id, a])),
    connections,
  });
}

beforeEach(() => {
  useStore.setState({ agents: new Map(), connections: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('AD-708c-2 MobileMesh', () => {
  it('renders an <svg> surface even with no agents', () => {
    seed([]);
    render(<MobileMesh />);
    const svg = screen.getByTestId('mobile-mesh');
    expect(svg).toBeTruthy();
    expect(svg.tagName.toLowerCase()).toBe('svg');
  });

  it('renders one node circle per curated agent', () => {
    seed([
      makeAgent({ id: 'a' }),
      makeAgent({ id: 'b' }),
      makeAgent({ id: 'c' }),
    ]);
    render(<MobileMesh />);
    expect(screen.getAllByTestId('mobile-mesh-node')).toHaveLength(3);
  });

  it('renders only edges between in-subset nodes (out-of-subset dropped)', () => {
    seed(
      [makeAgent({ id: 'a' }), makeAgent({ id: 'b' }), makeAgent({ id: 'c' })],
      [
        { source: 'a', target: 'b', relType: 'r', weight: 0.5 },
        { source: 'a', target: 'ghost', relType: 'r', weight: 0.5 },
      ],
    );
    const { container } = render(<MobileMesh />);
    expect(container.querySelectorAll('line')).toHaveLength(1);
  });

  it('maps node circle attrs from the projection (fill/r/opacity)', () => {
    seed([makeAgent({ id: 'u', tier: 'utility', trust: 0.85, confidence: 0.7 })]);
    render(<MobileMesh />);
    const circle = screen.getByTestId('mobile-mesh-node');
    expect(circle.getAttribute('fill')).toBe(trustToCss(0.85));
    expect(circle.getAttribute('r')).toBe(String(nodeRadius('utility', 0.7)));
    expect(circle.getAttribute('opacity')).toBe(String(confidenceToOpacity(0.7)));
  });

  it('renders the svg with zero nodes and zero lines for an empty store', () => {
    seed([]);
    const { container } = render(<MobileMesh />);
    expect(screen.getByTestId('mobile-mesh')).toBeTruthy();
    expect(screen.queryAllByTestId('mobile-mesh-node')).toHaveLength(0);
    expect(container.querySelectorAll('line')).toHaveLength(0);
  });

  it('imports no three.js and no canvas module (source guard)', () => {
    // Vitest cwd is D:/ProbOS/ui; resolve from there (jsdom rewrites the meta
    // URL to a non-file scheme that readFileSync rejects).
    const raw = readFileSync(
      resolve(process.cwd(), 'src/components/mesh/MobileMesh.tsx'),
      'utf8',
    );
    // Strip comments so the component's own prose (which names the forbidden
    // modules) does not trip the substring check — only real code is inspected.
    const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toContain("from 'three'");
    expect(code).not.toContain('canvas/scene');
    expect(code).not.toContain('canvas/connections');
    expect(code).not.toContain('canvas/agents');
    // Positively confirm it consumes the AD-708c-1 pure projection.
    expect(code).toContain("from '../../mesh2d/meshProjection'");
  });
});

describe('AD-708c-4 MobileMesh breathing (reduced-motion-aware)', () => {
  it('animates the nodes when motion is allowed (jsdom default: matchMedia absent)', () => {
    useStore.setState({
      agents: new Map([
        ['a', { id: 'a', callsign: 'A', tier: 'core', trust: 0.8, confidence: 0.7 } as any],
        ['b', { id: 'b', callsign: 'B', tier: 'domain', trust: 0.5, confidence: 0.5 } as any],
      ]),
      connections: [],
    });
    const { container } = render(<MobileMesh />);
    const circle = container.querySelector('circle');
    expect(circle?.getAttribute('style')).toContain('meshBreath');
    expect(container.querySelector('style')?.textContent).toContain('@keyframes meshBreath');
  });

  it('renders the static mesh (no animation) when prefers-reduced-motion is set', () => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    }));
    useStore.setState({
      agents: new Map([['a', { id: 'a', callsign: 'A', tier: 'core', trust: 0.8, confidence: 0.7 } as any]]),
      connections: [],
    });
    const { container } = render(<MobileMesh />);
    expect(container.querySelector('circle')?.getAttribute('style')).toBeNull();
    expect(container.querySelector('style')).toBeNull();
  });

  it('stays three-free (consumes meshProjection + the reduced-motion hook, never three)', () => {
    const code = readFileSync(resolve(process.cwd(), 'src/components/mesh/MobileMesh.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
    expect(code).not.toContain("from 'three'");
    expect(code).not.toContain('canvas/scene');
    expect(code).toContain('usePrefersReducedMotion');
  });
});
