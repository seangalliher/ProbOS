import { beforeEach, describe, expect, it } from 'vitest';

import { liveReadFence as fence, resetLiveReadFenceForTests } from '../liveReadFence';

type After = 'nothing' | 'observe' | 'observe other' | 'item epoch' | 'newer read applied';

function afterIssue(key: string, after: After): void {
  if (after === 'observe') fence.observe(key);
  if (after === 'observe other') fence.observe(`${key}-other`);
  if (after === 'item epoch') fence.observeItemEpoch();
  if (after === 'newer read applied') fence.markApplied(key, fence.begin());
}

beforeEach(() => {
  resetLiveReadFenceForTests();
});

describe('liveReadFence (issue #1375)', () => {
  // I2: a read may apply only if issued after the key's last observation and
  // last applied read; item keys must also be issued after the item epoch.
  it.each([
    ['item:x', 'nothing', true], ['crew:p', 'nothing', true], ['room:t', 'nothing', true],
    ['item:x', 'observe', false], ['crew:p', 'observe', false], ['room:t', 'observe', false],
    ['item:x', 'observe other', true], ['crew:p', 'observe other', true], ['room:t', 'observe other', true],
    ['item:x', 'item epoch', false], ['crew:p', 'item epoch', true], ['room:t', 'item epoch', true],
    ['item:x', 'newer read applied', false], ['crew:p', 'newer read applied', false],
    ['room:t', 'newer read applied', false],
  ] as const)('accepts(%s) after %s after issue is %s', (key, after, expected) => {
    const issuedAt = fence.begin();
    afterIssue(key, after);
    expect(fence.accepts(key, issuedAt)).toBe(expected);
  });

  it.each(['observe', 'item epoch', 'newer read applied'] as const)(
    'accepts a read issued after a prior %s',
    (before) => {
      afterIssue('item:x', before);
      expect(fence.accepts('item:x', fence.begin())).toBe(true);
    },
  );

  it('never re-accepts an issue stamp older than the one already applied', () => {
    const older = fence.begin();
    const newer = fence.begin();
    fence.markApplied('item:x', newer);
    fence.markApplied('item:x', older);
    expect(fence.accepts('item:x', older)).toBe(false);
    expect(fence.accepts('item:x', fence.begin())).toBe(true);
  });

  it('drops the item entries an item epoch dominates and keeps crew and room entries', () => {
    fence.observe('item:a');
    fence.markApplied('item:b', fence.begin());
    fence.observe('crew:p');
    fence.observe('room:t');
    expect(fence.trackedKeyCount()).toBe(4);

    fence.observeItemEpoch();

    expect(fence.trackedKeyCount()).toBe(2);
    expect(fence.accepts('item:a', fence.begin())).toBe(true);
  });

  // M2: a work-item scope read is an item read, so the item epoch fences it too.
  it.each([
    ['nothing', true], ['observe', false], ['observe other', true],
    ['item epoch', false], ['newer read applied', false],
  ] as const)('accepts(scope:parent:p) after %s after issue is %s', (after, expected) => {
    const issuedAt = fence.begin();
    afterIssue('scope:parent:p', after);
    expect(fence.accepts('scope:parent:p', issuedAt)).toBe(expected);
  });

  it('drops the scope entries an item epoch dominates', () => {
    fence.observe('scope:parent:p');
    fence.markApplied('scope:parent:q', fence.begin());
    fence.observe('crew:p');
    expect(fence.trackedKeyCount()).toBe(3);

    fence.observeItemEpoch();

    expect(fence.trackedKeyCount()).toBe(1);
    expect(fence.accepts('scope:parent:p', fence.begin())).toBe(true);
  });

  it('returns the stamp it records from observe', () => {
    const before = fence.begin();
    const stamp = fence.observe('crew:p');
    expect(stamp).toBeGreaterThan(before);
    expect(fence.accepts('crew:p', stamp)).toBe(false);
    expect(fence.accepts('crew:p', fence.begin())).toBe(true);
  });

  it('starts a new session on reset and rejects reads issued before it', () => {
    const session = fence.session;
    const issuedAt = fence.begin();
    fence.observe('item:x');

    resetLiveReadFenceForTests();

    expect(fence.session).not.toBe(session);
    expect(fence.trackedKeyCount()).toBe(0);
    expect(fence.accepts('item:x', issuedAt)).toBe(false);
    expect(fence.accepts('item:x', fence.begin())).toBe(true);
  });

  it('issues strictly increasing stamps', () => {
    const first = fence.begin();
    fence.observe('item:x');
    expect(fence.begin()).toBeGreaterThan(first + 1);
  });
});
