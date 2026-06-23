/* ProbOS HXI — deep-link view reader tests (AD-841c)
 *
 * The reader is pure/DI, so these tests feed REAL hash strings plus trivial
 * fake store handles that RECORD calls (BF-287 discipline — no MagicMock-style
 * over-mocking, no React, no jsdom). Each fake method name matches a store
 * idiom verified against HEAD (setState / getState().openCrewManifest /
 * openWardRoom / openSettings).
 */

import { describe, it, expect, vi } from 'vitest';
import {
  parseViewTarget,
  dispatchViewTarget,
  applyDeepLinkView,
  VIEW_TARGETS,
  type DeepLinkDeps,
} from './deepLinkView';

function makeFakes() {
  const setStateCalls: unknown[] = [];
  const openCrewManifest = vi.fn();
  const openWardRoom = vi.fn();
  const openSettings = vi.fn();
  const deps = {
    store: {
      setState: (payload: unknown) => {
        setStateCalls.push(payload);
      },
      getState: () => ({ openCrewManifest, openWardRoom }),
    },
    settings: {
      getState: () => ({ openSettings }),
    },
  } as unknown as DeepLinkDeps;
  return { deps, setStateCalls, openCrewManifest, openWardRoom, openSettings };
}

describe('parseViewTarget', () => {
  it('returns the matching target for each #view=<id> input', () => {
    expect(parseViewTarget('#view=work')).toBe('work');
    expect(parseViewTarget('#view=system')).toBe('system');
    expect(parseViewTarget('#view=agents')).toBe('agents');
    expect(parseViewTarget('#view=wardroom')).toBe('wardroom');
    expect(parseViewTarget('#view=skills')).toBe('skills');
    expect(parseViewTarget('#view=settings')).toBe('settings');
  });

  it('returns null for empty, compact, and unknown view hashes', () => {
    expect(parseViewTarget('')).toBeNull();
    expect(parseViewTarget('#')).toBeNull();
    expect(parseViewTarget('#compact')).toBeNull();
    expect(parseViewTarget('#view=')).toBeNull();
    expect(parseViewTarget('#view=bogus')).toBeNull();
    expect(parseViewTarget('#view=canvas')).toBeNull();
  });

  it('reads the view param from a combined compact+view hash', () => {
    expect(parseViewTarget('#compact&view=system')).toBe('system');
  });
});

describe('dispatchViewTarget', () => {
  it('sets the exact store payload for work / system / skills', () => {
    const work = makeFakes();
    dispatchViewTarget('work', work.deps);
    expect(work.setStateCalls).toEqual([{ mainViewer: 'work' }]);

    const system = makeFakes();
    dispatchViewTarget('system', system.deps);
    expect(system.setStateCalls).toEqual([{ mainViewer: 'system' }]);

    const skills = makeFakes();
    dispatchViewTarget('skills', skills.deps);
    expect(skills.setStateCalls).toEqual([{ shipsLockerOpen: true }]);
  });

  it('invokes the right action for agents / wardroom / settings', () => {
    const agents = makeFakes();
    dispatchViewTarget('agents', agents.deps);
    expect(agents.openCrewManifest).toHaveBeenCalledTimes(1);

    const wardroom = makeFakes();
    dispatchViewTarget('wardroom', wardroom.deps);
    expect(wardroom.openWardRoom).toHaveBeenCalledTimes(1);

    const settings = makeFakes();
    dispatchViewTarget('settings', settings.deps);
    expect(settings.openSettings).toHaveBeenCalledTimes(1);
  });
});

describe('applyDeepLinkView', () => {
  it('dispatches and returns the target for a valid hash', () => {
    const f = makeFakes();
    expect(applyDeepLinkView('#view=agents', f.deps)).toBe('agents');
    expect(f.openCrewManifest).toHaveBeenCalledTimes(1);
  });

  it('returns null and dispatches nothing for an empty hash', () => {
    const f = makeFakes();
    expect(applyDeepLinkView('', f.deps)).toBeNull();
    expect(f.setStateCalls).toHaveLength(0);
    expect(f.openCrewManifest).not.toHaveBeenCalled();
    expect(f.openWardRoom).not.toHaveBeenCalled();
    expect(f.openSettings).not.toHaveBeenCalled();
  });
});

describe('VIEW_TARGETS', () => {
  it('contains exactly the six deep-link ids (drift guard)', () => {
    expect([...VIEW_TARGETS]).toEqual([
      'work',
      'system',
      'agents',
      'wardroom',
      'skills',
      'settings',
    ]);
    expect(VIEW_TARGETS).toHaveLength(6);
  });
});
