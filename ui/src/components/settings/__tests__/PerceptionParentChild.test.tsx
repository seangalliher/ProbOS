/**
 * BF-298: Parent/child gating in the Perception section + status badge.
 *
 * BF-287: real ``useSettingsStore`` slice + real ``useCameraStore``;
 * fetch + camera APIs not exercised (we drive the store state directly).
 *
 * HXI Design Principle #3: assert NO emoji in the new components.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import SettingsMain from '../SettingsMain';
import PerceptionLivePanel from '../sections/PerceptionLivePanel';
import { useSettingsStore } from '../../../store/useSettingsStore';
import { useCameraStore } from '../../../store/useCameraStore';

const PERCEPTION_SECTION = {
  section_id: 'perception',
  label: 'Perception',
  glyph: '◐',
  domain: 'Perception & Voice',
  description: 'Camera + sensors',
  fields: [
    {
      field_id: 'perception.enabled',
      label: 'Perception enabled',
      kind: 'bool',
      enum_values: [],
      description: '',
      hot_reload: false,
    },
    {
      field_id: 'perception.camera.enabled',
      label: 'Camera enabled',
      kind: 'bool',
      enum_values: [],
      description: '',
      hot_reload: false,
    },
    {
      field_id: 'perception.camera_max_fps_server',
      label: 'Server max fps',
      kind: 'int',
      enum_values: [],
      description: '',
      hot_reload: false,
    },
  ],
};

function makeSnapshot(perceptionEnabled: boolean, cameraEnabled = false) {
  return {
    config: {
      perception: {
        enabled: perceptionEnabled,
        camera: { enabled: cameraEnabled },
        camera_max_fps_server: 4,
      },
    },
    secret_present: {},
    sections: [PERCEPTION_SECTION],
    domain_counts: { 'Perception & Voice': 1 },
    domain_order: ['Perception & Voice'],
    section_count: 1,
    config_path: '/tmp/system.yaml',
    uptime_seconds: 1,
    csrf_token: 'tk',
  };
}

function resetStore(snapshot: any) {
  useSettingsStore.setState({
    open: true,
    loading: false,
    loaded: true,
    snapshot,
    draft: {},
    draftCount: 0,
    selectedSectionId: 'perception',
    search: '',
    yamlOpen: false,
    yamlText: '',
    yamlLoading: false,
    applyStatus: 'idle',
    applyErrors: [],
    applyMessage: '',
    openedAt: 0,
  });
  useCameraStore.setState({ active: false, error: null, framesSent: 0 });
}

afterEach(() => {
  cleanup();
});

describe('BF-298 parent/child gating', () => {
  beforeEach(() => {
    resetStore(makeSnapshot(false));
  });

  it('master OFF -> camera.enabled child receives aria-disabled', () => {
    render(<SettingsMain />);
    const childBool = screen.getByTestId('field-bool-perception.camera.enabled');
    expect(childBool.getAttribute('aria-disabled')).toBe('true');
    expect(childBool.getAttribute('title')).toBe('Enable the Perception subsystem first.');
  });

  it('master OFF -> camera_max_fps_server number input is disabled', () => {
    render(<SettingsMain />);
    const childNumber = screen.getByTestId('field-number-perception.camera_max_fps_server');
    expect(childNumber).toBeDisabled();
  });

  it('master OFF -> master toggle itself stays enabled', () => {
    render(<SettingsMain />);
    const master = screen.getByTestId('field-bool-perception.enabled');
    expect(master.getAttribute('aria-disabled')).toBe('false');
    expect(master).not.toBeDisabled();
  });

  it('master ON -> all children enabled', () => {
    resetStore(makeSnapshot(true));
    render(<SettingsMain />);
    expect(
      screen.getByTestId('field-bool-perception.camera.enabled').getAttribute('aria-disabled'),
    ).toBe('false');
    expect(screen.getByTestId('field-number-perception.camera_max_fps_server')).not.toBeDisabled();
  });

  it('draft master toggle flip -> children re-enable without APPLY', () => {
    // Start with master OFF in snapshot, flip via draft.
    useSettingsStore.setState({
      draft: { 'perception.enabled': true },
      draftCount: 1,
    });
    render(<SettingsMain />);
    expect(
      screen.getByTestId('field-bool-perception.camera.enabled').getAttribute('aria-disabled'),
    ).toBe('false');
  });
});

describe('BF-298 perception status badge', () => {
  afterEach(() => cleanup());

  it('renders three states correctly', () => {
    // (a) subsystem OFF.
    resetStore(makeSnapshot(false));
    const { unmount: u1 } = render(<PerceptionLivePanel />);
    expect(screen.getByTestId('perception-status-badge').textContent).toBe('subsystem: OFF');
    u1();

    // (b) subsystem ON, camera inactive.
    resetStore(makeSnapshot(true));
    const { unmount: u2 } = render(<PerceptionLivePanel />);
    expect(screen.getByTestId('perception-status-badge').textContent).toBe(
      'subsystem: ON · 0 modalities active',
    );
    u2();

    // (c) subsystem ON, camera active.
    resetStore(makeSnapshot(true));
    useCameraStore.setState({ active: true, error: null, framesSent: 5 });
    render(<PerceptionLivePanel />);
    expect(screen.getByTestId('perception-status-badge').textContent).toBe(
      'subsystem: ON · camera live',
    );
  });
});
