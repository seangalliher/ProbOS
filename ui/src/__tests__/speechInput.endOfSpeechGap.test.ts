/** AD-760 — speechInput endOfSpeechGapMs accumulator. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { startListening, stopListening } from '../audio/speechInput';

interface FakeSR {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: any }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

let lastInstance: FakeSR | null = null;
function makeFakeSRCtor() {
  return vi.fn(function () {
    const sr: FakeSR = {
      continuous: false,
      interimResults: false,
      lang: '',
      onresult: null,
      onerror: null,
      onend: null,
      start: vi.fn(),
      abort: vi.fn(),
      stop: vi.fn(),
    };
    lastInstance = sr;
    return sr;
  });
}

function fireFinal(sr: FakeSR, text: string): void {
  sr.onresult?.({
    results: { length: 1, 0: { 0: { transcript: text }, isFinal: true } },
  });
}

beforeEach(() => {
  lastInstance = null;
  stopListening();
  vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('AD-760 endOfSpeechGapMs', () => {
  it('accumulates finals across utterances and fires once after gap elapses', () => {
    vi.useFakeTimers();
    const onResult = vi.fn();
    startListening(onResult, undefined, undefined, {
      continuous: true,
      interimResults: true,
      endOfSpeechGapMs: 1500,
    });
    expect(lastInstance!.continuous).toBe(true);
    expect(lastInstance!.interimResults).toBe(true);

    fireFinal(lastInstance!, 'computer');
    vi.advanceTimersByTime(500);
    expect(onResult).not.toHaveBeenCalled();
    fireFinal(lastInstance!, 'engage');
    vi.advanceTimersByTime(500);
    expect(onResult).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1500);
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('computer engage');
  });

  it('default (no endOfSpeechGapMs) fires immediately per final — v0 behavior', () => {
    const onResult = vi.fn();
    startListening(onResult);
    fireFinal(lastInstance!, 'hello world');
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('hello world');
  });

  it('stopListening flushes the pending accumulator', () => {
    vi.useFakeTimers();
    const onResult = vi.fn();
    startListening(onResult, undefined, undefined, {
      continuous: true,
      interimResults: true,
      endOfSpeechGapMs: 1500,
    });
    fireFinal(lastInstance!, 'pending text');
    vi.advanceTimersByTime(100);
    expect(onResult).not.toHaveBeenCalled();
    stopListening();
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('pending text');
  });

  it('owned cancellation discards pending text without forwarding or leaving a timer', () => {
    vi.useFakeTimers();
    const onResult = vi.fn();
    const handle = startListening(onResult, undefined, undefined, { continuous: true, endOfSpeechGapMs: 1500 });
    fireFinal(lastInstance!, 'not committed');
    expect(vi.getTimerCount()).toBe(1);
    handle.cancel();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(2000);
    expect(onResult).not.toHaveBeenCalled();
    expect(lastInstance!.abort).toHaveBeenCalledTimes(1);
  });

  it('legacy flush cannot stop a newer invocation created by its result callback', () => {
    vi.useFakeTimers();
    const nextResult = vi.fn();
    const onResult = vi.fn(() => startListening(nextResult));
    startListening(onResult, undefined, undefined, { continuous: true, endOfSpeechGapMs: 1500 });
    const retired = lastInstance!;
    fireFinal(retired, 'committed text');
    stopListening();
    expect(onResult).toHaveBeenCalledExactlyOnceWith('committed text');
    expect(lastInstance).not.toBe(retired);
    expect(lastInstance!.abort).not.toHaveBeenCalled();
    fireFinal(lastInstance!, 'next');
    expect(nextResult).toHaveBeenCalledExactlyOnceWith('next');
  });

  it('retired silence callbacks cannot flush cancelled or superseded text', () => {
    vi.useFakeTimers();
    const schedule = vi.spyOn(globalThis, 'setTimeout');
    const onResult = vi.fn();
    const handle = startListening(onResult, undefined, undefined, { continuous: true, endOfSpeechGapMs: 1500 });
    fireFinal(lastInstance!, 'first');
    const oldTimer = schedule.mock.calls[schedule.mock.calls.length - 1][0] as () => void;
    fireFinal(lastInstance!, 'second');
    oldTimer();
    expect(onResult).not.toHaveBeenCalled();
    const currentTimer = schedule.mock.calls[schedule.mock.calls.length - 1][0] as () => void;
    handle.cancel();
    currentTimer();
    expect(onResult).not.toHaveBeenCalled();
    schedule.mockRestore();
  });
});
