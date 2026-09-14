/** AD-721: CrewAvatarPopout test — fallback selection + close + agent_id routing. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

const popoutMocks = vi.hoisted(() => ({
  vrmRendered: { v: false },
  parametricRendered: { v: false },
  loadFailEmitter: { fn: null as null | (() => void) },
  editorPreview: { fn: null as null | ((url: string | null) => void) },
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
    return <div data-testid="crew-vrm" data-agent-id={props.agentId} data-vrm-url={props.vrmUrl} />;
  },
}));

vi.mock('../components/profile/CrewAvatarEditor', () => ({
  CrewAvatarEditor: (props: { onPreviewUrlChange: (url: string | null) => void }) => {
    popoutMocks.editorPreview.fn = props.onPreviewUrlChange;
    return <button data-testid="test-avatar-editor" onClick={() => props.onPreviewUrlChange('/avatars/editor-preview.vrm')}>Preview</button>;
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
  popoutMocks.editorPreview.fn = null;
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

  it.each(['asset', 'participant'] as const)('recovers from a failed VRM after the %s identity changes', identity => {
    const initial = {
      agentId: 'ezri',
      appearance: { vrm_url: '/avatars/ezri.vrm', expression_overrides: {}, color_palette_hint: '' },
      departmentColor: '#5090d0', agentSignals: idleSignals, onClose: vi.fn(),
    };
    const { rerender } = render(<CrewAvatarPopout {...initial} />);
    const oldError = popoutMocks.loadFailEmitter.fn!;
    expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe(initial.appearance.vrm_url);
    act(() => oldError());
    expect(screen.queryByTestId('crew-vrm')).toBeNull();
    expect(screen.getByTestId('parametric-avatar')).toBeTruthy();
    const next = identity === 'asset'
      ? { ...initial, appearance: { ...initial.appearance, vrm_url: '/avatars/repaired.vrm' } }
      : { ...initial, agentId: 'yeo' };

    rerender(<CrewAvatarPopout {...next} />);

    expect(screen.queryByTestId('crew-vrm')?.getAttribute('data-vrm-url')).toBe(next.appearance.vrm_url);
    expect(screen.queryByTestId('crew-vrm')?.getAttribute('data-agent-id')).toBe(next.agentId);
    act(() => oldError());
    expect(screen.getByTestId('crew-vrm').getAttribute('data-agent-id')).toBe(next.agentId);
    expect(screen.queryByTestId('parametric-avatar')).toBeNull();
  });

  it('shows a recoverable asset error and ignores the prior attempt after explicit retry', () => {
    render(<CrewAvatarPopout
      agentId="ezri"
      appearance={{ vrm_url: '/avatars/ezri.vrm', expression_overrides: {}, color_palette_hint: '' }}
      departmentColor="#5090d0" agentSignals={idleSignals} onClose={vi.fn()}
    />);
    expect(screen.getByTestId('crew-vrm')).toBeTruthy();
    const oldError = popoutMocks.loadFailEmitter.fn!;
    act(() => oldError());
    expect(screen.getByRole('status', { name: 'Avatar asset status' }).textContent).toContain('Avatar unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry avatar' }));
    expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe('/avatars/ezri.vrm');
    act(() => oldError());
    expect(screen.getByTestId('crew-vrm')).toBeTruthy();
    expect(screen.queryByRole('status', { name: 'Avatar asset status' })).toBeNull();
  });

  it('does not carry editor preview state or an old editor callback to another participant', () => {
    const initial = {
      agentId: 'ezri',
      appearance: { vrm_url: '/avatars/ezri.vrm', expression_overrides: {}, color_palette_hint: '' },
      departmentColor: '#5090d0', agentSignals: idleSignals, onClose: vi.fn(),
    };
    const { rerender } = render(<CrewAvatarPopout {...initial} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit avatar' }));
    fireEvent.click(screen.getByTestId('test-avatar-editor'));
    const oldPreview = popoutMocks.editorPreview.fn!;
    expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe('/avatars/editor-preview.vrm');

    rerender(<CrewAvatarPopout {...initial} agentId="yeo"
      appearance={{ ...initial.appearance, vrm_url: '/avatars/yeo.vrm' }} />);

    expect(screen.queryByTestId('test-avatar-editor')).toBeNull();
    expect(screen.getByTestId('crew-vrm').getAttribute('data-agent-id')).toBe('yeo');
    expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe('/avatars/yeo.vrm');
    act(() => oldPreview('/avatars/retired.vrm'));
    expect(screen.getByTestId('crew-vrm').getAttribute('data-vrm-url')).toBe('/avatars/yeo.vrm');
  });
});
