/* AD-708c-1: pure 2D mesh projection for the PADD mobile shell (#484 / AD-708).
 *
 * Re-derives the desktop HXI's visual-language semantics (trust -> color,
 * confidence -> luminance, tier + confidence -> size) and a fresh 2D
 * concentric-ring-by-tier layout, returning plain numbers + CSS color strings.
 *
 * THE LOAD-BEARING CONSTRAINT: this module MUST NOT import `three`,
 * `canvas/scene.ts`, `canvas/agents.tsx`, or any module that pulls three.
 * Doing so would drag the Three.js stack into the mobile Rollup chunk and
 * break the AD-708b lazy-three boundary (a phone must never load three.js).
 * The formulas below are RE-DERIVED from `ui/src/canvas/scene.ts` (trustToColor,
 * confidenceToIntensity, agentNodeSize) and the `useStore.ts` computeLayout
 * tier-radius ordering (core 3.5 / utility 5.5 / domain 7.5), NOT imported.
 * The only allowed store reference is the type-only `Agent` import (erased at
 * build). A source-level test asserts there is no three.js import and no
 * canvas-scene import (it strips comments first, so this prose is exempt).
 *
 * v1 simplifications (documented): the desktop `poolTintBlend` mixes a 30% pool
 * tint into the trust color. The 2D projection OMITS the pool tint — trust is
 * the dominant 70% term, so trust alone carries the band semantics for a small
 * curated subset. No animation here either (pulse/flash is AD-708c-4).
 */

import type { Agent, Connection } from '../store/types'; // type-only — the ONLY store reference

export interface MeshNode {
  id: string;
  callsign: string;
  tier: 'core' | 'utility' | 'domain';
  x: number; // px within the viewport
  y: number; // px within the viewport
  radius: number; // px
  color: string; // CSS '#rrggbb' from trust
  opacity: number; // 0.25..1 from confidence
}

export interface MeshViewport {
  width: number;
  height: number;
}

export interface MeshEdge {
  x1: number; // px — source node x within the viewport
  y1: number; // px — source node y
  x2: number; // px — target node x
  y2: number; // px — target node y
  opacity: number; // 0.4..0.9 from connection weight
}

// --- Trust spectrum stops (re-derived from scene.ts `trustToColor`) ----------
// high >= 0.7 amber, medium 0.35-0.7 blue, low > 0 violet, new == 0 silver.
const TRUST_HIGH_LO = '#e8963c';
const TRUST_HIGH_HI = '#f0b060';
const TRUST_MED_LO = '#6690b8';
const TRUST_MED_HI = '#88a4c8';
const TRUST_LOW_LO = '#5848a0';
const TRUST_LOW_HI = '#7060a8';
const TRUST_NEW = '#a0a8b8';

// --- Tier sizing (re-derived from scene.ts `TIER_BASE_SIZE` / agentNodeSize) -
const TIER_BASE: Record<string, number> = {
  core: 0.22,
  utility: 0.28,
  domain: 0.35,
};
const TIER_BASE_FALLBACK = 0.28;
// Maps the desktop's world-unit node size (~0.22..0.5) to phone px (~6..14).
const PX_SCALE = 28;

// --- 2D ring layout (mirrors the desktop tier-radius ordering 3.5/5.5/7.5) ---
// Expressed as fractions of min(width, height) / 2 so the rings scale to any
// viewport: core inner / utility mid / domain outer.
const RING_FRACTION: Record<'core' | 'utility' | 'domain', number> = {
  core: 0.3,
  utility: 0.55,
  domain: 0.8,
};

function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function toHexByte(v: number): string {
  const clamped = v < 0 ? 0 : v > 255 ? 255 : v;
  return Math.round(clamped).toString(16).padStart(2, '0');
}

/**
 * Component-wise sRGB lerp between two '#rrggbb' stops (the 2D equivalent of the
 * desktop THREE.Color.lerpColors). `t` is clamped to [0, 1].
 */
function lerpHex(a: string, b: string, t: number): string {
  const tt = clamp01(t);
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  const r = ar + (br - ar) * tt;
  const g = ag + (bg - ag) * tt;
  const bl = ab + (bb - ab) * tt;
  return `#${toHexByte(r)}${toHexByte(g)}${toHexByte(bl)}`;
}

/**
 * Trust -> CSS color string. Re-derives `scene.ts` trustToColor's four bands
 * with the same hex stops and thresholds (0.7, 0.35, 0). Trust is clamped to
 * [0, 1] for the band math so out-of-range values never produce an invalid hex.
 */
export function trustToCss(trust: number): string {
  const t = clamp01(trust);
  if (t >= 0.7) {
    return lerpHex(TRUST_HIGH_LO, TRUST_HIGH_HI, Math.min((t - 0.7) / 0.3, 1));
  }
  if (t >= 0.35) {
    return lerpHex(TRUST_MED_LO, TRUST_MED_HI, (t - 0.35) / 0.35);
  }
  if (t > 0) {
    return lerpHex(TRUST_LOW_LO, TRUST_LOW_HI, t / 0.35);
  }
  return TRUST_NEW;
}

/**
 * Confidence -> opacity. Normalizes the desktop `confidenceToIntensity`
 * (0.4 + c*1.8, range 0.4..2.2) to a [0.25, 1] opacity. The 0.25 floor keeps
 * low-confidence nodes faintly visible rather than fully transparent.
 */
export function confidenceToOpacity(confidence: number): number {
  const intensity = 0.4 + confidence * 1.8; // confidenceToIntensity, re-derived
  const norm = intensity / 2.2;
  if (norm < 0.25) return 0.25;
  if (norm > 1) return 1;
  return norm;
}

/**
 * Tier + confidence -> node radius in px. Re-derives the desktop `agentNodeSize`
 * (TIER_BASE[tier] + c*0.15) and scales it into phone px. An unknown tier falls
 * back to the utility base (mirroring scene.ts's `|| 0.28`).
 */
export function nodeRadius(tier: string, confidence: number): number {
  const base = TIER_BASE[tier] ?? TIER_BASE_FALLBACK;
  const size = base + confidence * 0.15; // agentNodeSize, re-derived
  return Math.round(size * PX_SCALE * 100) / 100;
}

/**
 * Progressive disclosure (HXI #5): a deterministic curated subset for the small
 * mobile mesh. Crew first (isCrew), then trust descending, then callsign
 * ascending as a stable tiebreak; capped at `limit`. Pure — the input array is
 * not mutated (a copy is sorted). `[]` -> `[]`.
 */
export function selectMeshAgents(agents: Agent[], limit = 24): Agent[] {
  if (agents.length === 0) return [];
  const sorted = [...agents].sort((a, b) => {
    if (a.isCrew !== b.isCrew) return a.isCrew ? -1 : 1;
    if (b.trust !== a.trust) return b.trust - a.trust;
    if (a.callsign < b.callsign) return -1;
    if (a.callsign > b.callsign) return 1;
    return 0;
  });
  return sorted.slice(0, limit);
}

/**
 * Concentric-ring-by-tier 2D layout: core inner / utility mid / domain outer,
 * mirroring the desktop tier-radius ordering (3.5 / 5.5 / 7.5) as ring-radius
 * fractions of min(width, height) / 2. Agents are evenly angularly spaced within
 * their tier ring, centered on the viewport. Deterministic. One MeshNode per
 * input agent, each with color/opacity/radius derived from its agent. `[]` ->
 * `[]`. A single node sits ON its tier ring (at the top), not dead-center.
 *
 * The caller curates the input (e.g. via `selectMeshAgents`); this stays
 * composable and does NOT curate internally.
 */
export function computeMeshLayout(agents: Agent[], viewport: MeshViewport): MeshNode[] {
  if (agents.length === 0) return [];

  const cx = viewport.width / 2;
  const cy = viewport.height / 2;
  const maxR = Math.min(viewport.width, viewport.height) / 2;

  const buckets: Record<'core' | 'utility' | 'domain', Agent[]> = {
    core: [],
    utility: [],
    domain: [],
  };
  for (const agent of agents) {
    if (agent.tier === 'core') buckets.core.push(agent);
    else if (agent.tier === 'utility') buckets.utility.push(agent);
    else buckets.domain.push(agent);
  }

  const nodes: MeshNode[] = [];
  const tiers: Array<'core' | 'utility' | 'domain'> = ['core', 'utility', 'domain'];
  for (const tier of tiers) {
    const ring = buckets[tier];
    const ringR = maxR * RING_FRACTION[tier];
    const n = ring.length;
    ring.forEach((agent, i) => {
      // Even angular spacing starting at the top (-PI/2). With a single node
      // (n === 1) the angle stays -PI/2 -> the node sits on the ring, not center.
      const angle = -Math.PI / 2 + (n > 0 ? (2 * Math.PI * i) / n : 0);
      nodes.push({
        id: agent.id,
        callsign: agent.callsign,
        tier,
        x: cx + ringR * Math.cos(angle),
        y: cy + ringR * Math.sin(angle),
        radius: nodeRadius(agent.tier, agent.confidence),
        color: trustToCss(agent.trust),
        opacity: confidenceToOpacity(agent.confidence),
      });
    });
  }
  return nodes;
}

/**
 * Projects store `connections` onto the curated mesh nodes. Builds an id -> node
 * map, then for each connection emits a line between the source and target nodes'
 * (x, y). Any edge with an endpoint OUTSIDE the curated subset (no matching node)
 * is DROPPED — the mobile mesh only shows edges between visible nodes. Opacity
 * encodes weight: min(0.4 + weight * 0.5, 0.9) (0.4 floor keeps faint edges
 * visible; 0.9 cap leaves headroom under the nodes). Pure, deterministic. `[]`
 * inputs -> `[]`.
 */
export function computeMeshEdges(nodes: MeshNode[], connections: Connection[]): MeshEdge[] {
  if (nodes.length === 0 || connections.length === 0) return [];
  const byId = new Map<string, MeshNode>();
  for (const n of nodes) byId.set(n.id, n);
  const edges: MeshEdge[] = [];
  for (const c of connections) {
    const a = byId.get(c.source);
    const b = byId.get(c.target);
    if (!a || !b) continue; // endpoint outside the curated subset -> drop
    edges.push({
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      opacity: Math.min(0.4 + c.weight * 0.5, 0.9),
    });
  }
  return edges;
}
