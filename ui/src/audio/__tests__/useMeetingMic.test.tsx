/** AD-922: useMeetingMic hook tests. The STT (`../transformersStt`), the SR
 *  availability probe (`../speechInput`), and the mic-permission source
 *  (`../wakeWord`) are MOCKED; `submit` is a fake. No real audio, no real mic.
 *  The hook is a pure-DI lifecycle (it also accepts a `deps` seam), so these
 *  tests drive it through the default module mocks to prove the real wiring. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mocks = vi.hoisted(() => ({
  arm: vi.fn(() => () => {}),
  disarm: vi.fn(),
  transcriptListeners: new Set<(t: string) => void>(),
  onTranscript: vi.fn(),
  isSupported: vi.fn(() => true),
  micListeners: new Set<(s: string) => void>(),
  getMicState: vi.fn(() => 'granted'),
  onMicState: vi.fn(),
}));

vi.mock('../transformersStt', () => ({
  armTransformersStt: mocks.arm,
  disarmTransformersStt: mocks.disarm,
  onTransformersTranscript: (l: (t: string) => void) => {
    mocks.onTranscript(l);
    mocks.transcriptListeners.add(l);
    return () => mocks.transcriptListeners.delete(l);
  },
}));

vi.mock('../speechInput', () => ({
  isSpeechRecognitionSupported: () => mocks.isSupported(),
}));

vi.mock('../wakeWord', () => ({
  getMicPermissionState: () => mocks.getMicState(),
  onMicPermissionState: (l: (s: string) => void) => {
    mocks.micListeners.add(l);
    return () => mocks.micListeners.delete(l);
  },
}));

import { useMeetingMic } from '../useMeetingMic';
import useMeetingMicSource from '../useMeetingMic?raw';

function fireTranscript(text: string): void {
  for (const l of Array.from(mocks.transcriptListeners)) l(text);
}

beforeEach(() => {
  mocks.arm.mockReset().mockReturnValue(() => {});
  mocks.disarm.mockReset();
  mocks.onTranscript.mockReset();
  mocks.isSupported.mockReset().mockReturnValue(true);
  mocks.getMicState.mockReset().mockReturnValue('granted');
  mocks.transcriptListeners.clear();
  mocks.micListeners.clear();
});

describe('useMeetingMic', () => {
  it('test_transcript_in_meeting_calls_submit_with_text', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('  status report  '); });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith('status report');
  });

  it('test_arm_subscribes_and_disarms_after_transcript', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).toHaveBeenCalledTimes(1);
    act(() => { fireTranscript('hello'); });
    expect(mocks.disarm).toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_not_armed_when_meeting_inactive', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: false, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
  });

  it('test_not_armed_while_agent_speaking', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: true, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
  });

  it('test_blocked_when_mic_denied', () => {
    mocks.getMicState.mockReturnValue('denied');
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    expect(result.current.blocked).toBe(true);
    act(() => { result.current.toggleCapture(); });
    expect(mocks.arm).not.toHaveBeenCalled();
  });

  it('test_supported_false_when_sr_unavailable', () => {
    mocks.isSupported.mockReturnValue(false);
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    expect(result.current.supported).toBe(false);
  });

  it('test_second_toggle_cancels_capture', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    expect(result.current.capturing).toBe(true);
    act(() => { result.current.toggleCapture(); });
    expect(mocks.disarm).toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_empty_transcript_does_not_submit', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('   '); });
    expect(submit).not.toHaveBeenCalled();
    expect(result.current.capturing).toBe(false);
  });

  it('test_one_shot_listener_torn_down', () => {
    const submit = vi.fn();
    const { result } = renderHook(() =>
      useMeetingMic({ meetingActive: true, speaking: false, submit }),
    );
    act(() => { result.current.toggleCapture(); });
    act(() => { fireTranscript('first'); });
    act(() => { fireTranscript('second'); });
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith('first');
  });

  it('test_no_emoji_in_source', () => {
    expect(useMeetingMicSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
