/** BF-978 (#1809): a build's review issues and suggestions show under its chat message and in its failure card.
 *
 * Each case opens the IntentSurface shell, sends one `build_success` or `build_failure` frame to the store's real
 * `handleEvent` inside `act`, and reads the DOM at once: no timer and no wait. The cases the base does not satisfy are
 * `built`, which is `it.fails` until M2 sets it to `it`; with BF978_RUNXFAIL=1 they run as ordinary cases, so each can be
 * seen to stop at its own assertion. Only names that exist on the base are imported. `globalThis.fetch` answers `{}` in
 * every case and is restored after it. Each title names its id and the contract's mutation rows it kills.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import type { WSEvent } from '../store/types';

// The built cases failed on the base at their own assert and pass now; the marker is a no-op.
const built = it;

const GENERATION = 'c'.repeat(32);
const SUCCESS_TEXT = 'Build complete in the review case';
const FAILURE_TEXT = 'Tests failed in the review case';
const realFetch = globalThis.fetch;
let nextSequence = 0;

function frame(type: string, data: Record<string, unknown>): WSEvent {
  return { type, data, timestamp: Date.now() / 1000, stream: { generation: GENERATION, sequence: nextSequence++ } };
}

function send(type: string, data: Record<string, unknown>): void {
  act(() => {
    useStore.getState().handleEvent(frame(type, data));
  });
}

function success(issues: unknown, suggestions: unknown): Record<string, unknown> {
  return {
    build_id: 'b978', branch: 'builder/b978', commit: 'abc1234', files_written: ['src/x.py'], tests_passed: true,
    test_result: '', review: 'reviewed', review_issues: issues, review_suggestions: suggestions, message: SUCCESS_TEXT,
  };
}

function failure(review: Record<string, unknown>): Record<string, unknown> {
  return {
    build_id: 'b978',
    message: `Build failed: ${FAILURE_TEXT}`,
    report: {
      build_id: 'b978', ad_number: 0, title: '', branch_name: 'builder/b978', files_written: [], files_modified: [],
      failure_category: 'test_failure', failure_summary: FAILURE_TEXT, raw_error: '', failed_tests: [],
      error_locations: [], fix_attempts: 0, fix_descriptions: [], review_result: '', resolution_options: [], ...review,
    },
  };
}

function shown(text: string): boolean {
  return screen.queryAllByText(text).length > 0;
}

/** The texts of the list whose aria-label is `name`; the list must be shown. */
function itemsOf(name: string): string[] {
  const list = document.querySelector(`ul[aria-label="${name}"]`);
  expect(list, `the "${name}" list is shown`).not.toBeNull();
  return Array.from(list!.querySelectorAll('li')).map((li) => li.textContent ?? '');
}

beforeEach(() => {
  nextSequence = 0;
  globalThis.fetch = vi.fn().mockImplementation(
    () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  ) as unknown as typeof fetch;
  useStore.setState({
    chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map(),
    liveGeneration: null, liveSequence: 0, liveRepairEpoch: 0,
  });
  render(<IntentSurface />);
  const pill = screen.queryByText(/Ask ProbOS/);
  const clickable = pill ? pill.closest('div') : null;
  if (clickable) fireEvent.click(clickable);
  send('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 });
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
  useStore.setState({ chatHistory: [] });
  vi.restoreAllMocks();
});

describe('BF-978: review lists under a build_success message', () => {
  built('S1 [W1 W2 W3]: 2 issues and 3 suggestions show all five texts under the message', () => {
    send('build_success', success(['issue one', 'issue two'], ['suggestion one', 'suggestion two', 'suggestion three']));
    expect(shown(SUCCESS_TEXT)).toBe(true);
    expect(itemsOf('Review issues')).toEqual(['issue one', 'issue two']);
    expect(itemsOf('Review suggestions')).toEqual(['suggestion one', 'suggestion two', 'suggestion three']);
    expect(shown('Review issues')).toBe(true);
    expect(shown('Review suggestions')).toBe(true);
  });

  it('S2 [W13] (control): empty lists show the message and neither list', () => {
    send('build_success', success([], []));
    expect(shown(SUCCESS_TEXT)).toBe(true);
    expect(shown('Review issues')).toBe(false);
    expect(shown('Review suggestions')).toBe(false);
    expect(document.querySelector('ul[aria-label="Review issues"], ul[aria-label="Review suggestions"]')).toBeNull();
  });

  built('S3 [W12]: markup in a suggestion shows as its literal characters', () => {
    const img = '<img src=x onerror="globalThis.__bf978 = 1">';
    const md = 'use **bold** and [a link](http://example.invalid)';
    send('build_success', success([], [img, md]));
    expect(itemsOf('Review suggestions')).toEqual([img, md]);
    const list = document.querySelector('ul[aria-label="Review suggestions"]');
    expect(list!.querySelector('img, a, strong')).toBeNull();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });

  built('S4 [W6 W7]: 12 issues show the first 10, then "and 2 more"', () => {
    const twelve = Array.from({ length: 12 }, (_, i) => `issue ${String(i + 1).padStart(2, '0')}`);
    send('build_success', success(twelve, []));
    expect(itemsOf('Review issues')).toEqual(twelve.slice(0, 10));
    expect(shown('and 2 more')).toBe(true);
  });

  built('S5 [W8 W9]: an item is cut at 500 code points with an ellipsis; 500 exactly is kept whole', () => {
    const long = 'a'.repeat(600);
    const astral = 'b'.repeat(499) + '\u{1F600}' + 'c'.repeat(9);
    const edge = 'd'.repeat(500);
    send('build_success', success([long, astral, edge], []));
    expect(itemsOf('Review issues')).toEqual([
      'a'.repeat(500) + '\u2026',
      'b'.repeat(499) + '\u{1F600}' + '\u2026',
      edge,
    ]);
  });

  built('S6 [W10 W11 W13]: null shows no list; non-string and empty items are skipped', () => {
    send('build_success', success(null, [97531, null, '', 'the one real suggestion']));
    expect(itemsOf('Review suggestions')).toEqual(['the one real suggestion']);
    expect(shown('Review issues')).toBe(false);
  });
});

describe('BF-978: review lists in the build failure card', () => {
  built('F1 [W4 W5]: a report with 2 issues and 3 suggestions shows all five texts in the card', () => {
    send('build_failure', failure({
      review_issues: ['failure issue one', 'failure issue two'],
      review_suggestions: ['failure suggestion one', 'failure suggestion two', 'failure suggestion three'],
    }));
    expect(shown('Build Failed')).toBe(true);
    expect(itemsOf('Review issues')).toEqual(['failure issue one', 'failure issue two']);
    expect(itemsOf('Review suggestions')).toEqual([
      'failure suggestion one', 'failure suggestion two', 'failure suggestion three',
    ]);
  });

  it('F2 [W10 W13] (control): no issues and no review_suggestions field show neither list', () => {
    send('build_failure', failure({ review_issues: [] }));
    expect(shown('Build Failed')).toBe(true);
    expect(shown('Review issues')).toBe(false);
    expect(shown('Review suggestions')).toBe(false);
  });
});
