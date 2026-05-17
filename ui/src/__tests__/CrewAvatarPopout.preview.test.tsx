/** AD-721d-3: CrewAvatarPopout preview-render button tests. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));

vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: ({ vrmUrl }: any) => <div data-testid="crew-vrm" data-vrm-url={vrmUrl} />,
}));

vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));

import { CrewAvatarPopout } from '../components/profile/CrewAvatarPopout';
import type { AgentSignals } from '../components/profile/avatarSignals';
import type { AvatarDSLDict } from '../store/types';

const idleSignals: AgentSignals = { trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false };

function makeDsl(): AvatarDSLDict {
  return {
    body: { type: 'average', height_cm: 170 },
    hair: { style: 'short', color_hsl: [0, 0, 30] },
    face: { warmth: 0.5, jaw: 'neutral', eyes: 'almond' },
    outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] },
    expression_resting: 'neutral',
    notes: '',
  };
}

describe('AD-721d-3 CrewAvatarPopout preview-render', () => {
  it('clicking "Render preview" invokes onRenderPreview', () => {
    const onRender = vi.fn();
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
        onRenderPreview={onRender}
      />,
    );
    fireEvent.click(screen.getByTestId('render-preview-btn'));
    expect(onRender).toHaveBeenCalledTimes(1);
  });

  it('swaps preview pane to CrewVRM when previewVrmUrl is set', () => {
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
        previewVrmUrl="/api/chat/attachments/deadbeef"
        onRenderPreview={() => {}}
      />,
    );
    const vrm = screen.getByTestId('crew-vrm');
    expect(vrm.getAttribute('data-vrm-url')).toBe('/api/chat/attachments/deadbeef');
  });

  it('shows "preview unavailable" inline and disables double-click during in-flight', () => {
    const onRender = vi.fn();
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
        onRenderPreview={onRender}
        previewInFlight={true}
        previewError="renderer_unavailable"
      />,
    );
    expect(screen.getByTestId('preview-error').textContent).toContain('preview unavailable');
    const btn = screen.getByTestId('render-preview-btn') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    expect(onRender).not.toHaveBeenCalled();
  });
});
