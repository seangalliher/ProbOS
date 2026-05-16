/** AD-721d-2c: CrewAvatarPopout Counselor-mediation button tests. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

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

const idleSignals: AgentSignals = {
  trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false,
};

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

function openRevisionAndType(text: string) {
  fireEvent.click(screen.getByTestId('request-revision-btn'));
  const textarea = screen.getByTestId('revision-note') as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: text } });
}

beforeEach(() => {
  // testing-library cleans up automatically between tests.
});

describe('AD-721d-2c CrewAvatarPopout Counselor-mediation', () => {
  it('renders Mediate button when onMediateRevision provided AND counselor online AND note non-empty', () => {
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
        onRequestRevision={vi.fn()}
        onMediateRevision={vi.fn()}
        counselorOnline={true}
      />,
    );
    openRevisionAndType('make hair shorter');
    expect(screen.getByTestId('mediate-revision-btn')).toBeTruthy();
  });

  it('Mediate button is NOT rendered when counselor is offline', () => {
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
        onRequestRevision={vi.fn()}
        onMediateRevision={vi.fn()}
        counselorOnline={false}
      />,
    );
    openRevisionAndType('make hair shorter');
    expect(screen.queryByTestId('mediate-revision-btn')).toBeNull();
  });

  it('happy path: click Mediate → API called → refined hint + iteration chip rendered', async () => {
    const onMediateRevision = vi.fn().mockResolvedValue({
      refined_hint: 'soften the warm-amber tone',
      proposal_iteration: 2,
    });
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
        onRequestRevision={vi.fn()}
        onMediateRevision={onMediateRevision}
        counselorOnline={true}
      />,
    );
    openRevisionAndType('warmer');
    fireEvent.click(screen.getByTestId('mediate-revision-btn'));
    await waitFor(() => {
      expect(onMediateRevision).toHaveBeenCalledWith('warmer');
    });
    await waitFor(() => {
      expect(screen.getByTestId('mediate-refined-panel').textContent).toContain(
        'soften the warm-amber tone',
      );
    });
    expect(screen.getByTestId('mediate-iteration-chip').textContent).toContain('iter 2');
  });

  it('error path: server returns error → error surface displayed → original hint preserved', async () => {
    const onMediateRevision = vi.fn().mockResolvedValue({
      error: 'mediator_unreachable',
    });
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
        onRequestRevision={vi.fn()}
        onMediateRevision={onMediateRevision}
        counselorOnline={true}
      />,
    );
    openRevisionAndType('warmer');
    fireEvent.click(screen.getByTestId('mediate-revision-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('mediate-error').textContent).toContain(
        'mediator_unreachable',
      );
    });
    // Original hint preserved — Captain's input not clobbered.
    const textarea = screen.getByTestId('revision-note') as HTMLTextAreaElement;
    expect(textarea.value).toBe('warmer');
    // No refined panel rendered.
    expect(screen.queryByTestId('mediate-refined-panel')).toBeNull();
  });
});
