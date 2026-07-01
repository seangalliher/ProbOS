/** AD-1071 — Pure sentence-chunking + sequential-queue helpers.
 *  These test the PURE logic in voiceChunking.ts with NO Audio/fetch mocking,
 *  which is why the queue/index logic was extracted out of voice.ts. */
import { describe, it, expect, vi } from 'vitest';
import { splitIntoSentences, runSentenceQueue } from '../voiceChunking';

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

describe('AD-1071 runSentenceQueue', () => {
  it('processes items strictly in order, next only after prev resolves', async () => {
    const events: string[] = [];
    const resolvers: Array<() => void> = [];
    let active = 0;
    const processOne = (item: string): Promise<void> =>
      new Promise<void>((resolve) => {
        events.push(`start:${item}`);
        active += 1;
        // Only ever one item in flight at a time.
        expect(active).toBe(1);
        resolvers.push(() => {
          active -= 1;
          events.push(`end:${item}`);
          resolve();
        });
      });

    const done = runSentenceQueue(['a', 'b', 'c'], processOne);
    await Promise.resolve();
    // Only the first item has started.
    expect(events).toEqual(['start:a']);

    resolvers[0]();
    await Promise.resolve();
    await Promise.resolve();
    expect(events).toEqual(['start:a', 'end:a', 'start:b']);

    resolvers[1]();
    await Promise.resolve();
    await Promise.resolve();
    expect(events).toEqual(['start:a', 'end:a', 'start:b', 'end:b', 'start:c']);

    resolvers[2]();
    const processed = await done;
    expect(events).toEqual([
      'start:a', 'end:a', 'start:b', 'end:b', 'start:c', 'end:c',
    ]);
    expect(processed).toBe(3);
  });

  it('honest-degrade: a throwing processOne does not abort the rest', async () => {
    const seen: string[] = [];
    const processOne = async (item: string): Promise<void> => {
      seen.push(item);
      if (item === 'b') throw new Error('synth failed');
    };
    const processed = await runSentenceQueue(['a', 'b', 'c'], processOne);
    // All three were attempted despite 'b' failing.
    expect(seen).toEqual(['a', 'b', 'c']);
    expect(processed).toBe(3);
  });

  it('stops early when shouldContinue returns false (cancellation)', async () => {
    const seen: string[] = [];
    let gen = 1;
    const processOne = async (item: string): Promise<void> => {
      seen.push(item);
      // Simulate a newer reply superseding this queue after the first item.
      if (item === 'a') gen = 2;
    };
    const processed = await runSentenceQueue(
      ['a', 'b', 'c'],
      processOne,
      () => gen === 1,
    );
    // 'a' ran (gen was 1 at its check); before 'b' the token went stale => stop.
    expect(seen).toEqual(['a']);
    expect(processed).toBe(1);
  });

  it('processes nothing for an empty item list', async () => {
    const processOne = vi.fn(async () => {});
    const processed = await runSentenceQueue([], processOne);
    expect(processed).toBe(0);
    expect(processOne).not.toHaveBeenCalled();
  });
});
