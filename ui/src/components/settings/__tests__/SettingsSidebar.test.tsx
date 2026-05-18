/**
 * AD-741: SettingsSidebar search filter tests.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';

import SettingsSidebar from '../SettingsSidebar';
import { useSettingsStore } from '../../../store/useSettingsStore';

const FAKE_SNAPSHOT = {
  config: {},
  secret_present: {},
  sections: [
    {
      section_id: 'system',
      label: 'System',
      glyph: '◇',
      domain: 'Core',
      description: '',
      fields: [
        { field_id: 'system.log_level', label: 'Log level', kind: 'enum', enum_values: [], description: '', hot_reload: false },
      ],
    },
    {
      section_id: 'voice',
      label: 'Voice',
      glyph: '≈',
      domain: 'Perception & Voice',
      description: '',
      fields: [
        { field_id: 'tts.voice_model', label: 'Piper voice model', kind: 'text', enum_values: [], description: '', hot_reload: false },
      ],
    },
  ],
  domain_counts: { 'Core': 1, 'Perception & Voice': 1 },
  domain_order: ['Core', 'Perception & Voice', 'Identity & Presentation', 'Connectivity'],
  section_count: 2,
  config_path: '',
  uptime_seconds: 0,
  csrf_token: 'tok',
};

function reset() {
  useSettingsStore.setState({
    snapshot: FAKE_SNAPSHOT as any,
    search: '',
    selectedSectionId: 'system',
  });
}

describe('SettingsSidebar — search (AD-741)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('search filter matches by section label', () => {
    render(<SettingsSidebar />);
    fireEvent.change(screen.getByTestId('settings-search'), { target: { value: 'voice' } });
    expect(screen.queryByTestId('settings-section-voice')).toBeTruthy();
    expect(screen.queryByTestId('settings-section-system')).toBeNull();
  });

  it('search filter matches by field label across sections', () => {
    render(<SettingsSidebar />);
    fireEvent.change(screen.getByTestId('settings-search'), { target: { value: 'piper' } });
    // 'Piper voice model' field label is inside the Voice section.
    expect(screen.queryByTestId('settings-section-voice')).toBeTruthy();
    expect(screen.queryByTestId('settings-section-system')).toBeNull();

    // Same query also returns 'log level' search for the System section.
    act(() => {
      useSettingsStore.setState({ search: 'log level' });
    });
    expect(screen.queryByTestId('settings-section-system')).toBeTruthy();
    expect(screen.queryByTestId('settings-section-voice')).toBeNull();
  });

  it('shows no-results placeholder when search matches nothing', () => {
    render(<SettingsSidebar />);
    fireEvent.change(screen.getByTestId('settings-search'), { target: { value: 'zzz-no-match' } });
    expect(screen.getByTestId('settings-search-no-results')).toBeTruthy();
  });
});
