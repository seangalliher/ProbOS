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
});
