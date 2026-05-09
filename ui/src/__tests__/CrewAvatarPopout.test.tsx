/** AD-721: CrewAvatarPopout test — fallback selection + close + agent_id routing. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const popoutMocks = vi.hoisted(() => ({
  vrmRendered: { v: false },
  parametricRendered: { v: false },
  loadFailEmitter: { fn: null as null | (() => void) },
}));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
}));

vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: (props: any) => {
    popoutMocks.vrmRendered.v = true;
    // Expose the load-fail handler so tests can trigger it.
    popoutMocks.loadFailEmitter.fn = props.onLoadError;
    return <div data-testid="crew-vrm" />;
  },
}));

vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => {
    popoutMocks.parametricRendered.v = true;
    return <div data-testid="parametric-avatar" />;
  },
}));

import { CrewAvatarPopout } from '../components/profile/CrewAvatarPopout';
import type { AgentSignals } from '../components/profile/avatarSignals';

const idleSignals: AgentSignals = { trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false };

beforeEach(() => {
  popoutMocks.vrmRendered.v = false;
  popoutMocks.parametricRendered.v = false;
  popoutMocks.loadFailEmitter.fn = null;
});

describe('AD-721 CrewAvatarPopout', () => {
  it('renders parametric fallback when appearance.vrm_url is empty', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={{ vrm_url: '', expression_overrides: {}, color_palette_hint: '' }}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
      />,
    );
    expect(popoutMocks.parametricRendered.v).toBe(true);
    expect(popoutMocks.vrmRendered.v).toBe(false);
  });

  it('renders parametric fallback when appearance is null', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
      />,
    );
    expect(popoutMocks.parametricRendered.v).toBe(true);
  });

  it('renders VRM when appearance.vrm_url is set', () => {
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={{ vrm_url: '/avatars/echo.vrm', expression_overrides: {}, color_palette_hint: '' }}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
      />,
    );
    expect(popoutMocks.vrmRendered.v).toBe(true);
    expect(popoutMocks.parametricRendered.v).toBe(false);
  });

  it('falls back to parametric when VRM onLoadError fires', () => {
    const { rerender } = render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={{ vrm_url: '/avatars/echo.vrm', expression_overrides: {}, color_palette_hint: '' }}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
      />,
    );
    expect(popoutMocks.vrmRendered.v).toBe(true);
    // Trigger load failure.
    popoutMocks.loadFailEmitter.fn?.();
    rerender(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={{ vrm_url: '/avatars/echo.vrm', expression_overrides: {}, color_palette_hint: '' }}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={() => {}}
      />,
    );
    expect(popoutMocks.parametricRendered.v).toBe(true);
  });

  it('close button invokes onClose', () => {
    const onClose = vi.fn();
    render(
      <CrewAvatarPopout
        agentId="agent-007"
        appearance={null}
        departmentColor="#d0a030"
        agentSignals={idleSignals}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByLabelText('Close avatar'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
