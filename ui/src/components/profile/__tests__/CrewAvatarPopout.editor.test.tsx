// AD-721a: integration smoke -- CrewAvatarPopout mounts the editor when
// the "edit" toggle is clicked, and the editor is dismissed by Cancel.
// Verifies the title-bar plumbing without exercising the three.js canvas.

import { describe, expect, test, vi, afterEach } from 'vitest';
import { render, fireEvent, cleanup } from '@testing-library/react';

// Stub the heavy three.js / r3f / VRM modules so the popout can mount
// under jsdom. The integration assertion only cares about the title-bar
// toggle and the editor mount/unmount.
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children: _children }: any) => null,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));
vi.mock('../CrewVRM', () => ({ CrewVRM: () => null }));
vi.mock('../ParametricAvatar', () => ({ ParametricAvatar: () => null }));

import { CrewAvatarPopout } from '../CrewAvatarPopout';

const SIGNALS = {
  trust_delta: 0,
  load: 0,
  working_state: 'idle' as const,
  tier3_alert: false,
};

afterEach(() => cleanup());

describe('AD-721a CrewAvatarPopout editor integration', () => {
  test('mounts the editor when the title-bar edit toggle is clicked', () => {
    const { getByTestId, queryByTestId } = render(
      <CrewAvatarPopout
        agentId="agent-bones"
        appearance={{
          vrm_url: '',
          expression_overrides: {},
          color_palette_hint: '',
          dsl: null,
        }}
        departmentColor="#6090f0"
        agentSignals={SIGNALS as any}
        onClose={() => { /* no-op */ }}
      />,
    );
    expect(queryByTestId('crew-avatar-editor')).toBeNull();
    fireEvent.click(getByTestId('avatar-edit-toggle'));
    expect(getByTestId('crew-avatar-editor')).toBeTruthy();
  });

  test('Counselor edit toggle is disabled while a propose iteration is pending', () => {
    const { getByTestId } = render(
      <CrewAvatarPopout
        agentId="agent-spock"
        appearance={{
          vrm_url: '',
          expression_overrides: {},
          color_palette_hint: '',
          dsl: null,
        }}
        departmentColor="#6090f0"
        agentSignals={SIGNALS as any}
        onClose={() => { /* no-op */ }}
        proposedDsl={{
          body: { type: 'average', height_cm: 170 },
          hair: { style: 'medium', color_hsl: [0, 0, 30] },
          face: { warmth: 0.5, jaw: 'neutral', eyes: 'almond' },
          outfit: { style: 'uniform', primary_color: '#2a4a6a', accents: [] },
          expression_resting: 'neutral',
          notes: '',
        }}
      />,
    );
    const toggle = getByTestId('avatar-edit-toggle') as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
  });

  test('Cancel inside editor returns popout to non-edit state', () => {
    const { getByTestId, queryByTestId } = render(
      <CrewAvatarPopout
        agentId="agent-bones"
        appearance={{
          vrm_url: '',
          expression_overrides: {},
          color_palette_hint: '',
          dsl: null,
        }}
        departmentColor="#6090f0"
        agentSignals={SIGNALS as any}
        onClose={() => { /* no-op */ }}
      />,
    );
    fireEvent.click(getByTestId('avatar-edit-toggle'));
    expect(queryByTestId('crew-avatar-editor')).toBeTruthy();
    fireEvent.click(getByTestId('editor-cancel'));
    expect(queryByTestId('crew-avatar-editor')).toBeNull();
  });
});
