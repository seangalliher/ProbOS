// AD-811a: unit tests for the A2UI stub + choice-spec parse helpers.
import { describe, it, expect } from 'vitest';
import {
  A2UI_STUB_RE,
  parseA2UIStub,
  parseChoiceSpec,
  parseFormSpec,
  parseMultiSelectSpec,
} from '../a2uiApi';

describe('AD-811a parseA2UIStub', () => {
  it('matches a well-formed A2UI stub', () => {
    const got = parseA2UIStub('[A2UI: a2ui-choice-1.json v3 - choice]');
    expect(got).toEqual({ name: 'a2ui-choice-1.json', version: 3, kind: 'choice' });
  });

  it('captures the kind for a multiselect stub (AD-811b)', () => {
    const got = parseA2UIStub('[A2UI: a2ui-multiselect-1.json v1 - multiselect]');
    expect(got).toEqual({
      name: 'a2ui-multiselect-1.json', version: 1, kind: 'multiselect',
    });
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

describe('AD-811b parseMultiSelectSpec', () => {
  it('parses a valid multiselect spec', () => {
    const json = JSON.stringify({
      kind: 'multiselect', prompt: 'Pick some', options: ['A', 'B', 'C'],
    });
    expect(parseMultiSelectSpec(json)).toEqual({
      prompt: 'Pick some', options: ['A', 'B', 'C'], minSelect: 1, maxSelect: null,
    });
  });

  it('drops empty/whitespace options', () => {
    const json = JSON.stringify({
      kind: 'multiselect', prompt: 'q', options: ['A', '  ', '', 'B'],
    });
    expect(parseMultiSelectSpec(json)).toEqual({
      prompt: 'q', options: ['A', 'B'], minSelect: 1, maxSelect: null,
    });
  });

  it('returns null when kind !== "multiselect"', () => {
    expect(parseMultiSelectSpec(
      JSON.stringify({ kind: 'choice', prompt: 'q', options: ['A', 'B'] }),
    )).toBeNull();
  });

  it('returns null with fewer than 2 options', () => {
    expect(parseMultiSelectSpec(
      JSON.stringify({ kind: 'multiselect', prompt: 'q', options: ['only'] }),
    )).toBeNull();
  });

  it('defaults minSelect to 1 and maxSelect to null', () => {
    const spec = parseMultiSelectSpec(JSON.stringify({
      kind: 'multiselect', prompt: 'q', options: ['A', 'B', 'C'],
    }));
    expect(spec?.minSelect).toBe(1);
    expect(spec?.maxSelect).toBeNull();
  });

  it('clamps maxSelect down to options.length', () => {
    const json = JSON.stringify({
      kind: 'multiselect', prompt: 'q', options: ['A', 'B'],
      min_select: 1, max_select: 9,
    });
    expect(parseMultiSelectSpec(json)?.maxSelect).toBe(2);
  });

  it('clamps minSelect to options.length', () => {
    const json = JSON.stringify({
      kind: 'multiselect', prompt: 'q', options: ['A', 'B'], min_select: 5,
    });
    expect(parseMultiSelectSpec(json)?.minSelect).toBe(2);
  });

  it('returns null on malformed JSON', () => {
    expect(parseMultiSelectSpec('{not json')).toBeNull();
  });

  it('returns null on a non-object payload', () => {
    expect(parseMultiSelectSpec('42')).toBeNull();
    expect(parseMultiSelectSpec('null')).toBeNull();
  });
});

describe('AD-811b-1 parseFormSpec', () => {
  it('parses a valid form spec', () => {
    const json = JSON.stringify({
      kind: 'form', prompt: 'Tell me',
      fields: [{ label: 'Name' }, { label: 'Role', required: true }],
    });
    expect(parseFormSpec(json)).toEqual({
      prompt: 'Tell me',
      fields: [
        { label: 'Name', required: false },
        { label: 'Role', required: true },
      ],
    });
  });

  it('defaults required to false and preserves an explicit true', () => {
    const spec = parseFormSpec(JSON.stringify({
      kind: 'form', prompt: 'q',
      fields: [{ label: 'A' }, { label: 'B', required: true }],
    }));
    expect(spec?.fields[0].required).toBe(false);
    expect(spec?.fields[1].required).toBe(true);
  });

  it('drops empty/whitespace-label fields', () => {
    const json = JSON.stringify({
      kind: 'form', prompt: 'q',
      fields: [{ label: 'A' }, { label: '  ' }, { label: '' }, { label: 'B' }],
    });
    expect(parseFormSpec(json)?.fields.map((f) => f.label)).toEqual(['A', 'B']);
  });

  it('dedupes by label (order preserved)', () => {
    const json = JSON.stringify({
      kind: 'form', prompt: 'q',
      fields: [
        { label: 'A' }, { label: 'B' }, { label: 'A' },
        { label: 'C' }, { label: 'B' },
      ],
    });
    expect(parseFormSpec(json)?.fields.map((f) => f.label))
      .toEqual(['A', 'B', 'C']);
  });

  it('returns null when kind !== "form"', () => {
    expect(parseFormSpec(
      JSON.stringify({ kind: 'choice', prompt: 'q', fields: [{ label: 'A' }] }),
    )).toBeNull();
  });

  it('returns null when fields is not an array', () => {
    expect(parseFormSpec(
      JSON.stringify({ kind: 'form', prompt: 'q', fields: 'A,B' }),
    )).toBeNull();
  });

  it('returns null with zero valid fields', () => {
    expect(parseFormSpec(
      JSON.stringify({ kind: 'form', prompt: 'q', fields: [{ label: '  ' }] }),
    )).toBeNull();
  });

  it('returns null on an empty prompt', () => {
    expect(parseFormSpec(
      JSON.stringify({ kind: 'form', prompt: '  ', fields: [{ label: 'A' }] }),
    )).toBeNull();
  });

  it('returns null on malformed JSON', () => {
    expect(parseFormSpec('{not json')).toBeNull();
  });

  it('returns null on a non-object payload', () => {
    expect(parseFormSpec('42')).toBeNull();
    expect(parseFormSpec('null')).toBeNull();
  });
});
