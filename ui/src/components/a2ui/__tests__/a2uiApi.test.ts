// AD-811a: unit tests for the A2UI stub + choice-spec parse helpers.
import { describe, it, expect } from 'vitest';
import {
  A2UI_STUB_RE,
  parseA2UIStub,
  parseChoiceSpec,
} from '../a2uiApi';

describe('AD-811a parseA2UIStub', () => {
  it('matches a well-formed A2UI stub', () => {
    const got = parseA2UIStub('[A2UI: a2ui-choice-1.json v3 - choice]');
    expect(got).toEqual({ name: 'a2ui-choice-1.json', version: 3 });
  });

  it('exposes the regex for reuse', () => {
    expect(A2UI_STUB_RE.test('[A2UI: x.json v1 - choice]')).toBe(true);
  });

  it('rejects an artifact stub (different shape)', () => {
    expect(parseA2UIStub('[Artifact: helper.py v1 - 73 lines, text/x-python]'))
      .toBeNull();
  });

  it('rejects plain text', () => {
    expect(parseA2UIStub('just a normal line')).toBeNull();
    expect(parseA2UIStub('')).toBeNull();
  });

  it('rejects a stub with a non-numeric version', () => {
    expect(parseA2UIStub('[A2UI: x.json vX - choice]')).toBeNull();
  });
});

describe('AD-811a parseChoiceSpec', () => {
  it('parses a valid choice spec', () => {
    const json = JSON.stringify({
      kind: 'choice', prompt: 'Pick one', options: ['A', 'B', 'C'],
    });
    expect(parseChoiceSpec(json)).toEqual({
      prompt: 'Pick one', options: ['A', 'B', 'C'],
    });
  });

  it('drops empty/whitespace options', () => {
    const json = JSON.stringify({
      kind: 'choice', prompt: 'q', options: ['A', '  ', '', 'B'],
    });
    expect(parseChoiceSpec(json)).toEqual({ prompt: 'q', options: ['A', 'B'] });
  });

  it('returns null on malformed JSON', () => {
    expect(parseChoiceSpec('{not json')).toBeNull();
  });

  it('returns null when kind !== "choice"', () => {
    expect(parseChoiceSpec(
      JSON.stringify({ kind: 'form', prompt: 'q', options: ['A', 'B'] }),
    )).toBeNull();
  });

  it('returns null on an empty prompt', () => {
    expect(parseChoiceSpec(
      JSON.stringify({ kind: 'choice', prompt: '  ', options: ['A', 'B'] }),
    )).toBeNull();
  });

  it('returns null with fewer than 2 options', () => {
    expect(parseChoiceSpec(
      JSON.stringify({ kind: 'choice', prompt: 'q', options: ['only'] }),
    )).toBeNull();
  });

  it('returns null when options is not an array', () => {
    expect(parseChoiceSpec(
      JSON.stringify({ kind: 'choice', prompt: 'q', options: 'A,B' }),
    )).toBeNull();
  });

  it('returns null on a non-object payload', () => {
    expect(parseChoiceSpec('42')).toBeNull();
    expect(parseChoiceSpec('null')).toBeNull();
  });
});
