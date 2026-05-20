/**
 * AD-746 Layer 2 — SOURCE BINDINGS panel tests.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PerceptionLivePanel from '../components/settings/sections/PerceptionLivePanel';
import { useCameraMultiplexerStore } from '../store/useCameraMultiplexerStore';
import { useSourceBindingsStore } from '../store/useSourceBindingsStore';
import { useSettingsStore } from '../store/useSettingsStore';

function seedSettings() {
  useSettingsStore.setState({
    snapshot: {
      config: {
        perception: { enabled: true, camera: { enabled: false } },
        cognitive: {
          llm_base_url_vision: 'http://localhost:11434',
          llm_model_vision: 'qwen3.6:27b',
        },
      },
    } as any,
  } as any);
}

beforeEach(() => {
  vi.restoreAllMocks();
  seedSettings();
  useCameraMultiplexerStore.setState({
    bindings: {},
    devices: [],
    loaded: true,
  } as any);
  useSourceBindingsStore.setState({
    bindings: {},
    loaded: true,
  } as any);
});

describe('AD-746 SOURCE BINDINGS panel', () => {
  it('renders SOURCE BINDINGS for >=2 camera bindings or any screen binding', () => {
    useCameraMultiplexerStore.setState({
      bindings: { 'counselor-001': '', 'ops-001': '' },
      devices: [],
      loaded: true,
    } as any);
    render(<PerceptionLivePanel />);
    expect(screen.getByText('SOURCE BINDINGS')).toBeTruthy();

    useCameraMultiplexerStore.setState({
      bindings: { 'counselor-001': '' },
      devices: [],
      loaded: true,
    } as any);
    useSourceBindingsStore.setState({
      bindings: { 'counselor-001': ['screen'] },
      loaded: true,
    } as any);
    render(<PerceptionLivePanel />);
    expect(screen.getAllByText('SOURCE BINDINGS').length).toBeGreaterThan(0);
  });

  it('renders CAMERA and SCREEN pills independently', () => {
    useCameraMultiplexerStore.setState({
      bindings: { 'counselor-001': '' },
      devices: [],
      loaded: true,
    } as any);
    useSourceBindingsStore.setState({
      bindings: { 'counselor-001': ['camera'] },
      loaded: true,
    } as any);

    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const cameraPill = screen.getByTestId('perception-source-pill-counselor-001-camera');
    const screenPill = screen.getByTestId('perception-source-pill-counselor-001-screen');
    expect(cameraPill.getAttribute('aria-pressed')).toBe('true');
    expect(screenPill.getAttribute('aria-pressed')).toBe('false');
  });

  it('clicking a source pill POSTs the updated binding list', async () => {
    useCameraMultiplexerStore.setState({
      bindings: { 'counselor-001': '' },
      devices: [],
      loaded: true,
    } as any);
    useSourceBindingsStore.setState({
      bindings: { 'counselor-001': ['camera', 'screen'] },
      loaded: true,
    } as any);

    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true, sources: ['screen'] }),
    } as unknown as Response);

    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    fireEvent.click(screen.getByTestId('perception-source-pill-counselor-001-camera'));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    const postCall = fetchSpy.mock.calls.find(
      ([url, init]: any[]) =>
        String(url).endsWith('/api/perception/sources/binding') &&
        init?.method === 'POST',
    );
    expect(postCall).toBeTruthy();
    const body = JSON.parse(postCall![1]!.body as string);
    expect(body.agent_id).toBe('counselor-001');
    expect(body.sources).toEqual(['screen']);
  });

  it('uses no emoji in SOURCE pills (HXI #3)', () => {
    useCameraMultiplexerStore.setState({
      bindings: { 'counselor-001': '' },
      devices: [],
      loaded: true,
    } as any);
    useSourceBindingsStore.setState({
      bindings: { 'counselor-001': ['camera', 'screen'] },
      loaded: true,
    } as any);

    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const row = screen.getByTestId('perception-source-bindings-row-counselor-001');
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
    expect(row.textContent ?? '').not.toMatch(emoji);
  });
});
