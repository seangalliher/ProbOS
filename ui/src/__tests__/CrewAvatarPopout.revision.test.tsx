/** AD-721d-1: CrewAvatarPopout revision-cycle tests. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

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

beforeEach(() => {
  // Clean DOM between tests — testing-library cleans up automatically.
});

describe('AD-721d-1 CrewAvatarPopout revision-cycle', () => {
  it('renders Request revision button when proposedDsl is set', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
        proposedDsl={makeDsl()}
        iteration={1}
        maxIterations={3}
      />,
    );
    expect(screen.getByTestId('request-revision-btn')).toBeTruthy();
  });

  it('clicking Request revision opens the textarea with counter 0/280', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
        proposedDsl={makeDsl()}
        iteration={1}
        maxIterations={3}
      />,
    );
    fireEvent.click(screen.getByTestId('request-revision-btn'));
    expect(screen.getByTestId('revision-textarea-wrap')).toBeTruthy();
    expect(screen.getByTestId('revision-counter').textContent).toBe('0 / 280');
  });

  it('Submit calls onRequestRevision with the typed note', async () => {
    const onRequestRevision = vi.fn();
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
        proposedDsl={makeDsl()}
        iteration={1}
        maxIterations={3}
        onRequestRevision={onRequestRevision}
      />,
    );
    fireEvent.click(screen.getByTestId('request-revision-btn'));
    const textarea = screen.getByTestId('revision-note') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'make hair shorter' } });
    fireEvent.click(screen.getByTestId('submit-revision-btn'));
    // Wait microtask for the async onClick.
    await Promise.resolve();
    expect(onRequestRevision).toHaveBeenCalledWith('make hair shorter');
  });

  it('at iteration cap, Request revision is disabled with tooltip', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
        proposedDsl={makeDsl()}
        iteration={3}
        maxIterations={3}
      />,
    );
    const btn = screen.getByTestId('request-revision-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute('aria-disabled')).toBe('true');
    expect(btn.getAttribute('title') || '').toMatch(/Maximum revisions reached/);
  });
});
