import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  isSpeechRecognitionSupported,
  startListening,
  stopListening,
  isListening,
} from '../audio/speechInput';
import { acquire, release, currentHolder, _resetForTests } from '../audio/speechRecognitionArbiter';

interface FakeSR {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: ReturnType<typeof vi.fn>;
  abort: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

let lastInstance: FakeSR | null = null;
function makeFakeSRCtor() {
  // Regular function (not arrow) so it's usable with `new`. Vitest's vi.fn wraps
  // arrows that cannot be constructors; speechInput's `new Ctor()` requires a
  // [[Construct]] slot.
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

describe('speechInput.ts (AD-474a)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();  // reset module-private activeRecognition
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('isSpeechRecognitionSupported returns false when neither vendor present', () => {
    // jsdom default has neither
    expect(isSpeechRecognitionSupported()).toBe(false);
  });

  it('isSpeechRecognitionSupported returns true with standard SpeechRecognition', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    expect(isSpeechRecognitionSupported()).toBe(true);
  });

  it('isSpeechRecognitionSupported returns true with webkit prefix', () => {
    vi.stubGlobal('webkitSpeechRecognition', makeFakeSRCtor());
    expect(isSpeechRecognitionSupported()).toBe(true);
  });

  it('startListening invokes onError when unsupported and does not throw', () => {
    const onError = vi.fn();
    startListening(vi.fn(), undefined, onError);
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('not supported'));
  });

  it('startListening configures continuous=false, interimResults=false, lang=en-US (defaults)', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    expect(lastInstance).not.toBeNull();
    expect(lastInstance!.continuous).toBe(false);
    expect(lastInstance!.interimResults).toBe(false);
    expect(lastInstance!.lang).toBe('en-US');
    expect(lastInstance!.start).toHaveBeenCalled();
  });

  it('startListening aborts any previously active session before starting', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const first = lastInstance!;
    startListening(vi.fn());
    expect(first.abort).toHaveBeenCalled();
    expect(lastInstance).not.toBe(first);
  });

  it('onresult forwards the latest final transcript to onResult', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onResult = vi.fn();
    startListening(onResult);
    // Browser SpeechRecognitionResultList is array-like with length + index access
    // and per-result isFinal. Test fake mirrors that shape.
    lastInstance!.onresult?.({ results: { length: 1, 0: { 0: { transcript: 'hello world' }, isFinal: true } } as never });
    expect(onResult).toHaveBeenCalledWith('hello world');
  });

  it('onerror swallows "aborted" but propagates other errors', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onError = vi.fn();
    startListening(vi.fn(), undefined, onError);
    lastInstance!.onerror?.({ error: 'aborted' });
    expect(onError).not.toHaveBeenCalled();
    lastInstance!.onerror?.({ error: 'no-speech' });
    expect(onError).toHaveBeenCalledWith('no-speech');
  });

  it('onend invokes onEnd callback and clears active recognition', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onEnd = vi.fn();
    startListening(vi.fn(), onEnd);
    expect(isListening()).toBe(true);
    lastInstance!.onend?.();
    expect(onEnd).toHaveBeenCalled();
    expect(isListening()).toBe(false);
  });

  it('stopListening calls abort and is safe when no active session', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    stopListening();
    expect(isListening()).toBe(false);
    // second call should not throw
    expect(() => stopListening()).not.toThrow();
  });
});

describe('speechInput.ts continuous-listen (AD-474b)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('forwards continuous=true to the SpeechRecognition instance', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    expect(lastInstance!.continuous).toBe(true);
  });

  it('forwards interimResults=true to the SpeechRecognition instance', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { interimResults: true });
    expect(lastInstance!.interimResults).toBe(true);
  });

  it('continuous mode auto-restarts a fresh recognition on onend', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    const first = lastInstance!;
    first.onend?.();
    expect(lastInstance).not.toBe(first);  // a new instance was spawned
    expect(lastInstance!.continuous).toBe(true);
    expect(lastInstance!.start).toHaveBeenCalled();
  });

  it('stopListening prevents continuous-mode auto-restart', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn(), undefined, undefined, { continuous: true });
    const first = lastInstance!;
    stopListening();
    lastInstance = null;  // reset so we can detect any new construction
    first.onend?.();
    expect(lastInstance).toBeNull();  // no new instance spawned after stop
  });

  it('continuous mode does not invoke onEnd during auto-restart cycles', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onEnd = vi.fn();
    startListening(vi.fn(), onEnd, undefined, { continuous: true });
    const first = lastInstance!;
    first.onend?.();
    expect(onEnd).not.toHaveBeenCalled();  // auto-restarted, not ended
  });

  it('with interimResults=true, onResult fires only for the latest final result', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onResult = vi.fn();
    startListening(onResult, undefined, undefined, { interimResults: true, continuous: true });
    lastInstance!.onresult?.({
      results: {
        length: 2,
        0: { 0: { transcript: 'partial' }, isFinal: false },
        1: { 0: { transcript: 'final text' }, isFinal: true },
      } as never,
    });
    expect(onResult).toHaveBeenCalledTimes(1);
    expect(onResult).toHaveBeenCalledWith('final text');
  });

  it('single-shot mode (default) does not auto-restart', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const first = lastInstance!;
    lastInstance = null;  // reset so we can detect any new construction
    first.onend?.();
    expect(lastInstance).toBeNull();  // single-shot ends cleanly
  });
});

describe('speechInput.ts VAD (AD-474c)', () => {
  beforeEach(() => {
    lastInstance = null;
    stopListening();
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('forwards opts.onSpeechEnd to recognition.onspeechend', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onSpeechEnd = vi.fn();
    startListening(vi.fn(), undefined, undefined, { onSpeechEnd });
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    expect(sr.onspeechend).toBeTypeOf('function');
    sr.onspeechend?.();
    expect(onSpeechEnd).toHaveBeenCalledTimes(1);
  });

  it('does not set onspeechend when opts.onSpeechEnd is omitted', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    startListening(vi.fn());
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    expect(sr.onspeechend ?? null).toBeNull();
  });

  it('onSpeechEnd fires before onEnd in single-shot mode', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const order: string[] = [];
    const onSpeechEnd = vi.fn(() => { order.push('speechEnd'); });
    const onEnd = vi.fn(() => { order.push('end'); });
    startListening(vi.fn(), onEnd, undefined, { onSpeechEnd });
    const sr = lastInstance as unknown as { onspeechend: (() => void) | null };
    sr.onspeechend?.();
    lastInstance!.onend?.();
    expect(order).toEqual(['speechEnd', 'end']);
  });

  it('onSpeechEnd fires per utterance in continuous mode (each restart wires a fresh handler)', () => {
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
    const onSpeechEnd = vi.fn();
    startListening(vi.fn(), undefined, undefined, { continuous: true, onSpeechEnd });
    const first = lastInstance as unknown as FakeSR & { onspeechend: (() => void) | null };
    first.onspeechend?.();
    first.onend?.();  // triggers auto-restart
    const second = lastInstance as unknown as FakeSR & { onspeechend: (() => void) | null };
    expect(second).not.toBe(first);
    second.onspeechend?.();
    expect(onSpeechEnd).toHaveBeenCalledTimes(2);
  });
});

describe('issue #1367 invocation-owned cancellation', () => {
  beforeEach(() => {
    stopListening();
    _resetForTests();
    lastInstance = null;
    vi.stubGlobal('SpeechRecognition', makeFakeSRCtor());
  });

  afterEach(() => {
    stopListening();
    _resetForTests();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('cancels idempotently and fences captured result, error, end and speech-end callbacks', () => {
    const onResult = vi.fn();
    const onEnd = vi.fn();
    const onError = vi.fn();
    const onSpeechEnd = vi.fn();
    const handle = startListening(onResult, onEnd, onError, { continuous: true, onSpeechEnd });
    const recognition = lastInstance as FakeSR & { onspeechend: () => void };
    const callbacks = { result: recognition.onresult!, error: recognition.onerror!, end: recognition.onend!, speechEnd: recognition.onspeechend };
    expect(recognition.start).toHaveBeenCalledTimes(1);
    expect(currentHolder()?.holder).toBe('press_to_talk');
    handle.cancel();
    handle.cancel();
    callbacks.result({ results: { length: 1, 0: { 0: { transcript: 'retired' }, isFinal: true } } as never });
    callbacks.error({ error: 'network' });
    callbacks.end();
    callbacks.speechEnd();
    expect(recognition.abort).toHaveBeenCalledTimes(1);
    expect(isListening()).toBe(false);
    expect(currentHolder()).toBeNull();
    expect(onResult).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(onEnd).not.toHaveBeenCalled();
    expect(onSpeechEnd).not.toHaveBeenCalled();
    expect(lastInstance).toBe(recognition);
  });

  it('does not cancel a newer invocation that uses the same holder label', () => {
    const first = startListening(vi.fn());
    const retired = lastInstance!;
    startListening(vi.fn());
    const current = lastInstance!;
    expect(current).not.toBe(retired);
    expect(retired.abort).toHaveBeenCalledTimes(1);
    first.cancel();
    expect(current.abort).not.toHaveBeenCalled();
    expect(isListening()).toBe(true);
    expect(currentHolder()?.holder).toBe('press_to_talk');
  });

  it('leaves an independent higher-priority holder alive after preemption and old cancellation', () => {
    const onPreempted = vi.fn();
    const onEnd = vi.fn();
    const handle = startListening(vi.fn(), onEnd, undefined, { holder: 'wake_word', priority: 50, continuous: true, onPreempted });
    const recognition = lastInstance!;
    const independent = acquire({ holder: 'conversation', priority: 75 });
    expect(independent).not.toBeNull();
    expect(onPreempted).toHaveBeenCalledExactlyOnceWith('conversation');
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(recognition.abort).toHaveBeenCalledTimes(1);
    handle.cancel();
    expect(currentHolder()).toEqual({ holder: 'conversation', priority: 75 });
    release(independent!);
  });

  it('cancels a queued invocation without starting it when its lease is later granted', () => {
    const independent = acquire({ holder: 'independent', priority: 200 });
    const onResult = vi.fn();
    const handle = startListening(onResult);
    expect(lastInstance).toBeNull();
    handle.cancel();
    expect(currentHolder()?.holder).toBe('independent');
    release(independent!);
    expect(lastInstance).toBeNull();
    expect(currentHolder()).toBeNull();
    expect(onResult).not.toHaveBeenCalled();
  });

  it('starts an uncancelled queued invocation on promotion and releases only its lease', () => {
    const independent = acquire({ holder: 'independent', priority: 200 });
    const handle = startListening(vi.fn());
    expect(lastInstance).toBeNull();
    release(independent!);
    expect(lastInstance!.start).toHaveBeenCalledTimes(1);
    expect(currentHolder()?.holder).toBe('press_to_talk');
    handle.cancel();
    expect(currentHolder()).toBeNull();
  });

  it('returns an inert idempotent handle when browser recognition is unavailable', () => {
    vi.unstubAllGlobals();
    const onError = vi.fn();
    const handle = startListening(vi.fn(), undefined, onError);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(() => { handle.cancel(); handle.cancel(); }).not.toThrow();
    expect(currentHolder()).toBeNull();
  });

  it.each(['construct', 'start', 'non-error'] as const)('releases its lease when the %s path fails', failure => {
    const construct = makeFakeSRCtor();
    vi.stubGlobal('SpeechRecognition', vi.fn(function () {
      if (failure !== 'start') throw failure === 'construct' ? new Error('constructor failed') : 'unavailable';
      const recognition = construct() as unknown as FakeSR;
      recognition.start.mockImplementation(() => { throw new Error('start failed'); });
      return recognition;
    }));
    const onError = vi.fn();
    const handle = startListening(vi.fn(), undefined, onError);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(isListening()).toBe(false);
    expect(currentHolder()).toBeNull();
    expect(() => handle.cancel()).not.toThrow();
    if (failure === 'start') expect(lastInstance!.abort).toHaveBeenCalledTimes(1);
  });

  it('releases its lease even when native abort throws', () => {
    const handle = startListening(vi.fn());
    lastInstance!.abort.mockImplementation(() => { throw new Error('abort failed'); });
    expect(() => handle.cancel()).not.toThrow();
    expect(currentHolder()).toBeNull();
    expect(isListening()).toBe(false);
  });

  it('does not clear a reentrant newer owner created during abort', () => {
    const handle = startListening(vi.fn());
    const retired = lastInstance!;
    retired.abort.mockImplementation(() => startListening(vi.fn(), undefined, undefined, { holder: 'new-owner' }));
    handle.cancel();
    expect(lastInstance).not.toBe(retired);
    expect(lastInstance!.start).toHaveBeenCalledTimes(1);
    expect(currentHolder()?.holder).toBe('new-owner');
    expect(isListening()).toBe(true);
  });

  it('fences the previous recognizer generation during continuous restart', () => {
    const onResult = vi.fn();
    startListening(onResult, undefined, undefined, { continuous: true });
    const retired = lastInstance!;
    const lateResult = retired.onresult!;
    const lateEnd = retired.onend!;
    retired.onend!();
    const current = lastInstance!;
    expect(current).not.toBe(retired);
    lateResult({ results: { length: 1, 0: { 0: { transcript: 'retired' } } } as never });
    lateEnd();
    expect(lastInstance).toBe(current);
    expect(onResult).not.toHaveBeenCalled();
    current.onresult!({ results: { length: 1, 0: { 0: { transcript: 'current' } } } as never });
    expect(onResult).toHaveBeenCalledExactlyOnceWith('current');
  });

  it('releases natural completion before the callback starts another owner', () => {
    const onEnd = vi.fn(() => startListening(vi.fn(), undefined, undefined, { holder: 'next' }));
    const handle = startListening(vi.fn(), onEnd);
    const retired = lastInstance!;
    retired.onend!();
    expect(onEnd).toHaveBeenCalledTimes(1);
    expect(lastInstance).not.toBe(retired);
    handle.cancel();
    expect(currentHolder()?.holder).toBe('next');
    expect(lastInstance!.abort).not.toHaveBeenCalled();
  });
});
