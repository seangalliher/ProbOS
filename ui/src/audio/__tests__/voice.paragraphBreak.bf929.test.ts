/** BF-929 (#1667): a paragraph break adds a pause marker only when the paragraph does not already end a sentence.
 *
 * The defect: `stripMarkdownForSpeech` turned every paragraph break into '. ', so a paragraph that already ended
 * in a period became 'end.. Next', the sentence splitter cut after the second period and Piper read the doubled
 * period aloud as "dot". '?' gave '?.', '!' gave '!.', a closing quote gave '.".', an ellipsis gave four dots,
 * and a blank line with trailing spaces made a chunk of a lone period.
 *
 * The fixtures are synthetic. They keep the shape of the defect (paragraphs that end in a period, a second
 * paragraph, a closing-quote or bracket variant, '?' and '!', an ellipsis, a decimal) and carry no text from the
 * live call that found it: this repository is public and its tests hold no vessel data.
 *
 * The cases the unfixed tree fails are `built`, which is `it.fails` until BF-929 M2 sets it to `it`; with
 * BF929_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. Each case runs the
 * chain the call runs: the text passed to `speakResponse` is `stripMarkdownForSpeech(...)`, and with sentence
 * pipelining on, `voice.ts` cuts it with `splitIntoSentences`.
 */
import { describe, it, expect } from 'vitest';
import { splitIntoSentences } from '../voiceChunking';

const built = it;

/** What the call speaks and what Piper receives: the stripped text, and its sentence chunks. */
async function spoken(text: string): Promise<{ text: string; chunks: string[] }> {
  const { stripMarkdownForSpeech } = await import('../voice');
  const stripped = stripMarkdownForSpeech(text);
  return { text: stripped, chunks: splitIntoSentences(stripped) };
}

const P1 = 'The survey finished early and the readings were stable.';
const P2 = 'Two things changed after the second pass, and neither was a surprise.';
const P3 = 'That is all for now, so rest well.';

describe('BF-929: a paragraph break after a finished sentence adds no period', () => {
  built('keeps one period at the end of each paragraph, none doubled, and each paragraph ends a chunk', async () => {
    const { text, chunks } = await spoken([P1, P2, P3].join('\n\n'));
    expect(text).toBe(`${P1} ${P2} ${P3}`);
    expect(text).not.toContain('..');
    expect(chunks).toEqual([P1, P2, P3]);
  });

  built('does the same after a question mark and an exclamation mark', async () => {
    const { text, chunks } = await spoken('Is the survey done?\n\nYes!\n\nGood.');
    expect(text).toBe('Is the survey done? Yes! Good.');
    expect(chunks).toEqual(['Is the survey done?', 'Yes!', 'Good.']);
  });

  built('adds no period after a closing quote or bracket, and the paragraph still ends a chunk', async () => {
    const straight = await spoken('She called it "done."\n\nThe second note (see the log.)\n\nThe last note.');
    expect(straight.text).toBe('She called it "done." The second note (see the log.) The last note.');
    expect(straight.chunks).toEqual(['She called it "done."', 'The second note (see the log.)', 'The last note.']);
    const typographic = await spoken('She wrote \u201cdone.\u201d\n\nThe next line.');
    expect(typographic.text).toBe('She wrote \u201cdone.\u201d The next line.');
    expect(typographic.chunks).toEqual(['She wrote \u201cdone.\u201d', 'The next line.']);
  });

  built('keeps an ellipsis at the end of a paragraph at three dots', async () => {
    const { text, chunks } = await spoken('Wait...\n\nIt is fine.');
    expect(text).toBe('Wait... It is fine.');
    expect(chunks).toEqual(['Wait...', 'It is fine.']);
  });

  built('treats trailing spaces and a run of blank lines as one pause, and never makes a chunk of a lone period', async () => {
    const { text, chunks } = await spoken('First note. \n\n\n\nSecond note');
    expect(text).toBe('First note. Second note');
    expect(chunks).toEqual(['First note.', 'Second note']);
  });
});

describe('BF-929: what must not change', () => {
  it('still marks a paragraph that has no sentence punctuation with a pause', async () => {
    const { text, chunks } = await spoken('Status\n\nThe readings are stable.');
    expect(text).toBe('Status. The readings are stable.');
    expect(chunks).toEqual(['Status.', 'The readings are stable.']);
  });

  it('leaves a decimal alone, and still pauses after a paragraph that ends in a number', async () => {
    const { text, chunks } = await spoken('The ratio was 0.7312 on the second pass\n\nIt held at 0.7312');
    expect(text).toBe('The ratio was 0.7312 on the second pass. It held at 0.7312');
    expect(chunks).toEqual(['The ratio was 0.7312 on the second pass.', 'It held at 0.7312']);
  });

  it('leaves a single line break and an ellipsis inside a sentence alone', async () => {
    expect((await spoken('One line.\nThe next line.')).text).toBe('One line.\nThe next line.');
    expect((await spoken('Wait... what is that')).text).toBe('Wait... what is that');
  });

  it('does not cut after a closing quote when a lowercase word follows it', () => {
    expect(splitIntoSentences('He shouted "Stop!" and left. Then "Go." she said.')).toEqual([
      'He shouted "Stop!" and left.',
      'Then "Go." she said.',
    ]);
  });
});
