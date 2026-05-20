/**
 * AD-746 Layer 2 — SOURCE BINDINGS UI tests.
 *
 * Verifies the per-agent CAMERA / SCREEN pills render inside the
 * existing CAMERA BINDINGS section, that clicking a pill flips the
 * binding via POST to /api/perception/sources/binding, and that the
 * pills follow HXI Principle #3 (no emoji; SVG / text glyphs only).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PerceptionLivePanel from '../PerceptionLivePanel';
import { useCameraMultiplexerStore } from '../../../../store/useCameraMultiplexerStore';
import { useSourceBindingsStore } from '../../../../store/useSourceBindingsStore';
import { useSettingsStore } from '../../../../store/useSettingsStore';

function _seedSettings() {
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
  _seedSettings();
  useCameraMultiplexerStore.setState({
    bindings: { 'counselor-001': '' },
    devices: [],
    loaded: true,
  } as any);
  useSourceBindingsStore.setState({
    bindings: { 'counselor-001': ['camera', 'screen'] },
    loaded: true,
  } as any);
});

describe('AD-746 PerceptionLivePanel SOURCE BINDINGS pills', () => {
  it('renders CAMERA and SCREEN pills for each agent in the bindings table', () => {
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const cameraPill = screen.getByTestId('perception-source-pill-counselor-001-camera');
    const screenPill = screen.getByTestId('perception-source-pill-counselor-001-screen');
    expect(cameraPill).toBeTruthy();
    expect(screenPill).toBeTruthy();
    expect(cameraPill.textContent).toBe('CAMERA');
    expect(screenPill.textContent).toBe('SCREEN');
  });

  it('pill aria-pressed reflects bound state independently per source', () => {
    useSourceBindingsStore.setState({
      bindings: { 'counselor-001': ['camera'] },
      loaded: true,
    } as any);
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const cam = screen.getByTestId('perception-source-pill-counselor-001-camera');
    const scr = screen.getByTestId('perception-source-pill-counselor-001-screen');
    expect(cam.getAttribute('aria-pressed')).toBe('true');
    expect(scr.getAttribute('aria-pressed')).toBe('false');
  });

  it('clicking a pill POSTs to /api/perception/sources/binding with toggled list', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200, ok: true,
      json: async () => ({ ok: true, sources: ['screen'] }),
    } as unknown as Response);
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    fireEvent.click(screen.getByTestId('perception-source-pill-counselor-001-camera'));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    // Find the binding POST call (refresh GETs may have fired first).
    const postCall = fetchSpy.mock.calls.find(
      ([url, init]: any[]) =>
        String(url).endsWith('/api/perception/sources/binding') &&
        init?.method === 'POST',
    );
    expect(postCall).toBeTruthy();
    const body = JSON.parse(postCall![1]!.body as string);
    expect(body.agent_id).toBe('counselor-001');
    // Camera was bound → toggling drops it; only 'screen' remains.
    expect(body.sources).toEqual(['screen']);
  });

  it('HXI Principle #3: pills are text + SVG glyphs only — no emoji', () => {
    render(<PerceptionLivePanel />);
    fireEvent.click(screen.getByTestId('perception-camera-bindings-toggle'));
    const row = screen.getByTestId('perception-source-bindings-row-counselor-001');
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
    expect(row.textContent ?? '').not.toMatch(emoji);
  });
});
