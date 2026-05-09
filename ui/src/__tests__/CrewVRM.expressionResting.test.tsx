/** AD-721d D9: multi-mesh face-split regression test — direct repro of
 *  AD-721 BF de4107b. The VRM expression manager binding only updates the
 *  first face mesh on multi-material face splits; ``applyRestingExpressionMultiMesh``
 *  must drive every face mesh that carries a matching morph target.
 */
import { describe, it, expect } from 'vitest';

import { applyRestingExpressionMultiMesh } from '../components/profile/CrewVRM';

/**
 * Build a fake mesh-like object with a morph target dictionary mapping the
 * given morph name to index 2, and an influences array of length 4.
 */
function fakeFaceMesh(morphName: string) {
  return {
    isMesh: true,
    morphTargetDictionary: { Other_A: 0, Other_B: 1, [morphName]: 2, Other_D: 3 },
    morphTargetInfluences: [0, 0, 0, 0],
  };
}

/** Minimal scene shim: traverse() invokes cb for every direct child. */
function fakeScene(children: any[]) {
  return {
    traverse(cb: (o: any) => void) {
      cb(this); // root
      for (const c of children) cb(c);
    },
  };
}

describe('CrewVRM — multi-mesh face-split (AD-721d D9 regression of BF de4107b)', () => {
  it('updates EVERY face mesh that carries the gentle_smile morph (3-mesh fixture)', () => {
    const m1 = fakeFaceMesh('Fcl_MTH_A');
    const m2 = fakeFaceMesh('Fcl_MTH_A');
    const m3 = fakeFaceMesh('Fcl_MTH_A');
    const scene = fakeScene([m1, m2, m3]);

    const updated = applyRestingExpressionMultiMesh(scene, 'gentle_smile', 1.0);

    expect(updated).toBe(3);
    // All 3 face meshes' morphTargetInfluences[2] (the Fcl_MTH_A index) must be 1.
    expect(m1.morphTargetInfluences[2]).toBe(1.0);
    expect(m2.morphTargetInfluences[2]).toBe(1.0);
    expect(m3.morphTargetInfluences[2]).toBe(1.0);
    // Other indices remain untouched.
    expect(m1.morphTargetInfluences[0]).toBe(0);
    expect(m2.morphTargetInfluences[1]).toBe(0);
    expect(m3.morphTargetInfluences[3]).toBe(0);
  });

  it('skips meshes that do not carry a candidate morph (mixed scene)', () => {
    const faceMesh = fakeFaceMesh('Fcl_ALL_Joy');
    const bodyMesh = {
      isMesh: true,
      morphTargetDictionary: { something_else: 0 },
      morphTargetInfluences: [0],
    };
    const scene = fakeScene([faceMesh, bodyMesh]);

    const updated = applyRestingExpressionMultiMesh(scene, 'gentle_smile', 1.0);

    expect(updated).toBe(1);
    expect(faceMesh.morphTargetInfluences[2]).toBe(1.0);
    expect(bodyMesh.morphTargetInfluences[0]).toBe(0);
  });

  it('returns 0 and writes nothing for the neutral resting expression', () => {
    const m1 = fakeFaceMesh('Fcl_MTH_A');
    const scene = fakeScene([m1]);

    const updated = applyRestingExpressionMultiMesh(scene, 'neutral', 1.0);

    expect(updated).toBe(0);
    expect(m1.morphTargetInfluences[2]).toBe(0);
  });

  it('respects the weight argument when driving morphs', () => {
    const m1 = fakeFaceMesh('Fcl_MTH_A');
    const m2 = fakeFaceMesh('Fcl_MTH_A');
    const scene = fakeScene([m1, m2]);

    applyRestingExpressionMultiMesh(scene, 'gentle_smile', 0.42);

    expect(m1.morphTargetInfluences[2]).toBeCloseTo(0.42, 5);
    expect(m2.morphTargetInfluences[2]).toBeCloseTo(0.42, 5);
  });
});
