/** AD-721d-1: AvatarDSL diff helper + amber-tint diff rendering. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));

vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: () => <div data-testid="crew-vrm" />,
}));

vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));

import { diffAvatarDsl } from '../components/profile/avatarDslDiff';
import { CrewAvatarPopout } from '../components/profile/CrewAvatarPopout';
import type { AgentSignals } from '../components/profile/avatarSignals';
import type { AvatarDSLDict } from '../store/types';

const idleSignals: AgentSignals = { trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false };

function makeDsl(overrides: Partial<AvatarDSLDict> = {}): AvatarDSLDict {
  return {
    body: { type: 'average', height_cm: 170 },
    hair: { style: 'short', color_hsl: [0, 0, 30] },
    face: { warmth: 0.5, jaw: 'neutral', eyes: 'almond' },
    outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] },
    expression_resting: 'neutral',
    notes: '',
    ...overrides,
  };
}

describe('AD-721d-1 diffAvatarDsl', () => {
  it('returns empty Set when prev is null', () => {
    expect(diffAvatarDsl(null, makeDsl())).toEqual(new Set());
  });

  it('returns changed paths when fields differ', () => {
    const prev = makeDsl({ body: { type: 'slim', height_cm: 160 } });
    const curr = makeDsl({ body: { type: 'stocky', height_cm: 160 } });
    const diff = diffAvatarDsl(prev, curr);
    expect(diff.has('body.type')).toBe(true);
    expect(diff.has('body.height_cm')).toBe(false);
  });
});

describe('AD-721d-1 parametric description renders diff highlights', () => {
  it('applies amber color on changed outfit.style field', () => {
    const prev = makeDsl({ outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] } });
    const curr = makeDsl({ outfit: { style: 'casual',  primary_color: '#2a4a6a', accents: [] } });
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
        proposedDsl={curr}
        previousDsl={prev}
        iteration={2}
        maxIterations={3}
      />,
    );
    const changedSpan = document.querySelector('[data-diff-path="outfit.style"]') as HTMLElement;
    expect(changedSpan).toBeTruthy();
    // Amber tint applied via inline style — colour token #f0b060.
    expect(changedSpan.style.color.replace(/\s/g, '').toLowerCase()).toMatch(/#f0b060|rgb\(240,176,96\)/);
    // Strike-through previous value present.
    const prevSpan = document.querySelector('[data-diff-prev="outfit.style"]') as HTMLElement;
    expect(prevSpan).toBeTruthy();
    expect(prevSpan.textContent).toBe('uniform');
  });
});
