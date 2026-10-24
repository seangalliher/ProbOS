/** AD-1071 — Pure sentence-chunking + sequential-queue helpers.
 *  These test the PURE logic in voiceChunking.ts with NO Audio/fetch mocking,
 *  which is why the queue/index logic was extracted out of voice.ts. */
import { describe, it, expect, vi } from 'vitest';
import { splitIntoSentences, runPrefetchQueue } from '../voiceChunking';

describe('AD-1071 splitIntoSentences', () => {
  it('splits a multi-sentence reply into ordered chunks', () => {
    expect(splitIntoSentences('Hello world. How are you? I am fine!')).toEqual([
      'Hello world.',
      'How are you?',
      'I am fine!',
    ]);
  });

  it('returns [text] for a single sentence', () => {
    expect(splitIntoSentences('Just one sentence.')).toEqual(['Just one sentence.']);
  });

  it('returns [text] for a fragment with no terminal punctuation', () => {
    expect(splitIntoSentences('no terminal punctuation here')).toEqual([
      'no terminal punctuation here',
    ]);
  });

  it('returns [] for an empty string', () => {
    expect(splitIntoSentences('')).toEqual([]);
  });

  it('returns [] for a whitespace-only string', () => {
    expect(splitIntoSentences('   \n\t ')).toEqual([]);
  });

  it('returns [] for a non-string input', () => {
    // Defensive: callers should pass a string, but a null/undefined must not throw.
    expect(splitIntoSentences(undefined as unknown as string)).toEqual([]);
    expect(splitIntoSentences(null as unknown as string)).toEqual([]);
  });

  it('trims chunks and drops empties', () => {
    expect(splitIntoSentences('First.    Second.   Third.')).toEqual([
      'First.',
      'Second.',
      'Third.',
    ]);
  });

  it('keeps a trailing fragment as its own chunk', () => {
    expect(splitIntoSentences('First sentence. And a trailing bit')).toEqual([
      'First sentence.',
      'And a trailing bit',
    ]);
  });

  it('does NOT split on common abbreviations', () => {
    expect(splitIntoSentences('Dr. Smith went home. He was tired.')).toEqual([
      'Dr. Smith went home.',
      'He was tired.',
    ]);
    expect(splitIntoSentences('Meet Mr. Jones at 5. Then leave.')).toEqual([
      'Meet Mr. Jones at 5.',
      'Then leave.',
    ]);
  });

  it('handles multiple terminal punctuation and ellipses', () => {
    expect(splitIntoSentences('Really?! Yes.')).toEqual(['Really?!', 'Yes.']);
    expect(splitIntoSentences('Wait... what?')).toEqual(['Wait...', 'what?']);
  });

  it('splits across newlines (whitespace after terminal punctuation)', () => {
    expect(splitIntoSentences('Line one.\nLine two.')).toEqual(['Line one.', 'Line two.']);
  });

  it('caps the result at maxChunks, merging the overflow into the last chunk', () => {
    // 45 sentences "S0. S1. ... S44." with maxChunks=40 => 40 chunks, the last
    // one absorbing the 6-sentence tail.
    const src = Array.from({ length: 45 }, (_, i) => `S${i}.`).join(' ');
    const out = splitIntoSentences(src, 40);
    expect(out.length).toBe(40);
    expect(out[0]).toBe('S0.');
    expect(out[38]).toBe('S38.');
    // The final chunk holds S39..S44 merged.
    expect(out[39]).toBe('S39. S40. S41. S42. S43. S44.');
  });
});

describe('BF-918 runPrefetchQueue', () => {
  const flush = async (): Promise<void> => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };

  function harness() {
    const events: string[] = [];
    const preps: Array<() => void> = [];
    const ends: Array<() => void> = [];
    const prepare = (item: string): Promise<string> =>
      new Promise<string>((resolve) => {
        events.push(`prep:${item}`);
        preps.push(() => resolve(item));
      });
    const play = (_p: string | null, item: string): Promise<void> =>
      new Promise<void>((resolve) => {
        events.push(`play:${item}`);
        ends.push(() => { events.push(`end:${item}`); resolve(); });
      });
    return { events, preps, ends, prepare, play };
  }

  it('Q1 lookahead 0: one item at a time, in order (the AD-1071 queue)', async () => {
    const events: string[] = [];
    const ends: Array<() => void> = [];
    const prepare = async (item: string): Promise<string> => { events.push(`prep:${item}`); return item; };
    const play = (_p: string | null, item: string): Promise<void> =>
      new Promise<void>((resolve) => {
        events.push(`play:${item}`);
        ends.push(() => { events.push(`end:${item}`); resolve(); });
      });
    const done = runPrefetchQueue(['a', 'b', 'c'], prepare, play, () => true, 0);
    await flush();
    expect(events).toEqual(['prep:a', 'play:a']);
    ends[0]();
    await flush();
    expect(events).toEqual(['prep:a', 'play:a', 'end:a', 'prep:b', 'play:b']);
    ends[1]();
    await flush();
    ends[2]();
    expect(await done).toBe(3);
    expect(events).toEqual(['prep:a', 'play:a', 'end:a', 'prep:b', 'play:b', 'end:b', 'prep:c', 'play:c', 'end:c']);
  });

  it('Q2 lookahead 1: the next item is prepared while the current one plays, and plays only after it', async () => {
    const h = harness();
    const done = runPrefetchQueue(['a', 'b', 'c'], h.prepare, h.play, () => true, 1);
    await flush();
    expect(h.events).toEqual(['prep:a']); // nothing else until a is prepared
    h.preps[0]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b']);
    h.preps[1]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b']); // b is ready, a still plays, c waits
    h.ends[0]();
    await flush();
    expect(h.events).toEqual(['prep:a', 'play:a', 'prep:b', 'end:a', 'play:b', 'prep:c']);
    h.preps[2]();
    h.ends[1]();
    await flush();
    h.ends[2]();
    expect(await done).toBe(3);
  });

  it('Q3 a stop drops every prepared item that never played, including one still in flight', async () => {
    const h = harness();
    let go = true;
    const discarded: Array<string | null> = [];
    const done = runPrefetchQueue(['a', 'b', 'c'], h.prepare, h.play, () => go, 1, (p) => { discarded.push(p); });
    await flush();
    h.preps[0]();
    await flush(); // a plays, b is being prepared
    go = false;
    h.ends[0]();
    expect(await done).toBe(1);
    expect(discarded).toEqual([]); // b is still in flight
    h.preps[1]();
    await flush();
    expect(discarded).toEqual(['b']);
    expect(h.events).not.toContain('play:b');
    expect(h.events).not.toContain('prep:c');
  });

  it('Q4 a stop found after an item is prepared discards it instead of playing it', async () => {
    let go = true;
    const discarded: Array<string | null> = [];
    const play = vi.fn(async () => {});
    const prepare = async (item: string): Promise<string> => { if (item === 'a') go = false; return item; };
    expect(await runPrefetchQueue(['a', 'b'], prepare, play, () => go, 1, (p) => { discarded.push(p); })).toBe(0);
    expect(discarded).toEqual(['a']);
    expect(play).not.toHaveBeenCalled();
  });

  it('Q5 a rejected prepare plays as null, and a throwing play does not stop the queue', async () => {
    const seen: Array<string | null> = [];
    const prepare = async (item: string): Promise<string> => {
      if (item === 'b') throw new Error('synth failed');
      return item;
    };
    const play = async (p: string | null, item: string): Promise<void> => {
      seen.push(p);
      if (item === 'a') throw new Error('play failed');
    };
    expect(await runPrefetchQueue(['a', 'b', 'c'], prepare, play, () => true, 1)).toBe(3);
    expect(seen).toEqual(['a', null, 'c']);
  });

  it('Q6 nothing is prepared or played when stopped from the start, or for an empty list', async () => {
    const prepare = vi.fn(async (item: string) => item);
    const play = vi.fn(async () => {});
    expect(await runPrefetchQueue(['a'], prepare, play, () => false, 1)).toBe(0);
    expect(await runPrefetchQueue([], prepare, play, () => true, 1)).toBe(0);
    expect(prepare).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });
});
