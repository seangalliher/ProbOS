/* Three.js scene setup — dark field, trust spectrum, mode grading (Fix 2, 3, 5) */

import * as THREE from 'three';

// Trust spectrum: high=warm amber, medium=blue-white, low=cool violet, new=silver
// Widened bands: high >= 0.7, medium 0.35-0.7, low < 0.35 (Fix 3)
export function trustToColor(trust: number): THREE.Color {
  if (trust >= 0.7) {
    return new THREE.Color().lerpColors(
      new THREE.Color('#e8963c'),
      new THREE.Color('#f0b060'),
      Math.min((trust - 0.7) / 0.3, 1),
    );
  } else if (trust >= 0.35) {
    return new THREE.Color().lerpColors(
      new THREE.Color('#6690b8'),
      new THREE.Color('#88a4c8'),
      (trust - 0.35) / 0.35,
    );
  } else if (trust > 0) {
    return new THREE.Color().lerpColors(
      new THREE.Color('#5848a0'),
      new THREE.Color('#7060a8'),
      trust / 0.35,
    );
  }
  return new THREE.Color('#a0a8b8');
}

// Pool tint colors — subtle hue identity per pool
const _poolTintCache: Record<string, THREE.Color> = {};
const POOL_TINT_HEXES: Record<string, string> = {
  system: '#c8a070',
  filesystem: '#7090c0',
  filesystem_writers: '#70b0a0',
  directory: '#60b0a0',
  search: '#60c0c0',
  shell: '#c8a060',
  http: '#7070b8',
  introspect: '#9090b0',
  red_team: '#c85068',
  web_search: '#6080b8',
  page_reader: '#70a0b0',
  weather: '#70b0c8',
  news: '#a09090',
  translator: '#8078b0',
  summarizer: '#a07890',
  calculator: '#b0a070',
  todo_manager: '#80a070',
  note_taker: '#70a080',
  scheduler: '#a08880',
  skills: '#a078b0',
  system_qa: '#a0a058',
};

// 70% trust color + 30% pool tint for visual variety even when trust is similar (Fix 3)
export function poolTintBlend(trust: number, pool: string): THREE.Color {
  const trustColor = trustToColor(trust);
  let tint = _poolTintCache[pool];
  if (!tint) {
    const hex = POOL_TINT_HEXES[pool] || '#8888a0';
    tint = new THREE.Color(hex);
    _poolTintCache[pool] = tint;
  }
  return trustColor.clone().lerp(tint, 0.3);
}

// Confidence -> emissive intensity (0..1 -> 0.4..2.2) — brighter range (Fix 2)
export function confidenceToIntensity(confidence: number): number {
  return 0.4 + confidence * 1.8;
}

// Tier-based node sizing (Fix 5)
const TIER_BASE_SIZE: Record<string, number> = {
  core: 0.22,
  utility: 0.28,
  domain: 0.35,
};

export function agentNodeSize(tier: string, confidence: number): number {
  const base = TIER_BASE_SIZE[tier] || 0.28;
  return base + confidence * 0.15;
}

// System mode color grading (Fix 2 — higher bloom)
export interface ModeGrading {
  tint: THREE.Color;
  bloomStrength: number;
  bloomRadius: number;
}

export function modeGrading(mode: string): ModeGrading {
  switch (mode) {
    case 'dreaming':
      return {
        tint: new THREE.Color('#2a1810'),
        bloomStrength: 2.5,
        bloomRadius: 0.8,
      };
    case 'idle':
      return {
        tint: new THREE.Color('#0f0e14'),
        bloomStrength: 1.8,
        bloomRadius: 0.6,
      };
    default: // active
      return {
        tint: new THREE.Color('#0a0a12'),
        bloomStrength: 1.5,
        bloomRadius: 0.5,
      };
  }
}
