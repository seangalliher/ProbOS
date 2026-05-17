// AD-721b-2: useLipSyncCapture hook lifecycle tests.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useLipSyncCapture } from '../useLipSyncCapture';
import * as voice from '../voice';
import * as lipSyncCapture from '../lipSyncCapture';

let listener: ((evt: voice.SpeechEvent) => void) | null = null;
const unsub = vi.fn();

beforeEach(() => {
  listener = null;
  unsub.mockClear();
  vi.spyOn(voice, 'onSpeechEvent').mockImplementation((fn) => {
    listener = fn;
    return unsub;
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function fireStart() {
  if (!listener) throw new Error('listener not registered');
  act(() => listener!({
    type: 'start',
    agent_id: 'agent-1',
    utterance: {} as SpeechSynthesisUtterance,
    source: 'browser',
  }));
}

function fireStartFromServer() {
  if (!listener) throw new Error('listener not registered');
  act(() => listener!({
    type: 'start',
    agent_id: 'agent-1',
    utterance: {} as SpeechSynthesisUtterance,
    source: 'server',
  }));
}

describe('useLipSyncCapture', () => {
  it('BF-293: server-source start events do NOT trigger capture', async () => {
    // When the server-streamed Piper path fires its 'start' event (after
    // visemes have already been injected via injectLipSyncFrames), the
    // hook MUST NOT capture audio or upload anything. Otherwise it
    // races the server visemes and burns a rhubarb call on webm.
    const captureSpy = vi.spyOn(lipSyncCapture, 'captureUtteranceAudio');
    const uploadSpy = vi.spyOn(lipSyncCapture, 'uploadAudioForLipSync');

    renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-1' }),
    );
    fireStartFromServer();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(captureSpy).not.toHaveBeenCalled();
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it('exposes empty frames when capture returns null', async () => {
    vi.spyOn(lipSyncCapture, 'captureUtteranceAudio').mockResolvedValue(null);
    const uploadSpy = vi.spyOn(lipSyncCapture, 'uploadAudioForLipSync');

    const { result } = renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-1' }),
    );
    expect(result.current.frames).toEqual([]);
    fireStart();
    // Wait one microtask flush for the async IIFE to resolve.
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(result.current.frames).toEqual([]);
    expect(result.current.capturing).toBe(false);
    // Upload was never called because capture returned null.
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it('sets frames when server returns rhubarb backend', async () => {
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' });
    vi.spyOn(lipSyncCapture, 'captureUtteranceAudio').mockResolvedValue(blob);
    vi.spyOn(lipSyncCapture, 'uploadAudioForLipSync').mockResolvedValue({
      backend: 'rhubarb',
      frames: [{ time: 0, duration: 0.1, viseme: 'aa' }],
    });

    const { result } = renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-1' }),
    );
    fireStart();
    await act(async () => {
      // Two microtask flushes — one for captureUtteranceAudio, one for upload.
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.frames).toHaveLength(1);
    expect(result.current.frames[0]).toEqual({
      time: 0,
      duration: 0.1,
      viseme: 'aa',
    });
  });

  it('does not setState after unmount even when upload resolves later', async () => {
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' });
    vi.spyOn(lipSyncCapture, 'captureUtteranceAudio').mockResolvedValue(blob);
    // Deferred upload — resolve after unmount.
    let resolveUpload: (v: any) => void = () => {};
    const uploadPromise = new Promise((resolve) => { resolveUpload = resolve; });
    vi.spyOn(lipSyncCapture, 'uploadAudioForLipSync').mockReturnValue(
      uploadPromise as any,
    );

    const { result, unmount } = renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-1' }),
    );
    fireStart();
    // Let captureUtteranceAudio resolve.
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    // Unmount BEFORE the upload resolves.
    unmount();
    // Now resolve the upload.
    resolveUpload({
      backend: 'rhubarb',
      frames: [{ time: 0, duration: 0.1, viseme: 'aa' }],
    });
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    // frames must remain []; mounted=false should have short-circuited setState.
    expect(result.current.frames).toEqual([]);
    // Subscription was unwound.
    expect(unsub).toHaveBeenCalled();
  });

  it('AD-738: receives injected frames from voice.ts via injectLipSyncFrames', async () => {
    const { injectLipSyncFrames } = await import('../useLipSyncCapture');
    const { result } = renderHook(() =>
      useLipSyncCapture({ enabled: true, agentId: 'agent-1' }),
    );
    expect(result.current.frames).toEqual([]);
    const visemes = [{ time: 0, duration: 0.1, viseme: 'aa' }];
    act(() => injectLipSyncFrames(visemes, 'agent-1'));
    expect(result.current.frames).toEqual(visemes);
    // Mismatched agentId must NOT update state.
    act(() => injectLipSyncFrames(
      [{ time: 0, duration: 0.2, viseme: 'oh' }],
      'other-agent',
    ));
    expect(result.current.frames).toEqual(visemes);
  });
});
