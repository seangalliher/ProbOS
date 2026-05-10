/** AD-721b v1: Multi-mesh face-split regression guard.
 *
 *  Synthetic VRM fixture with 7 mock face meshes:
 *   - Meshes A-E (5): carry ALL 5 vowel morphs (Fcl_MTH_A/I/U/E/O).
 *   - Meshes F-G (2): carry ONLY Fcl_MTH_A (the BF de4107b face-split pattern
 *     where the I/U/E/O bindings were lost during VRoid export).
 *
 *  Asserts ``_collectMorphMeshes`` returns the correct mesh sets per vowel
 *  and that a per-vowel direct-write loop touches every mesh in each set. */
import { describe, it, expect, beforeEach } from 'vitest';
import {
  _collectMorphMeshes,
  VOWEL_CANDIDATES,
} from '../../components/profile/CrewVRM';
import type { VowelKey } from '../lipSyncTrack';

interface MockMesh {
  isMesh: boolean;
  name: string;
  morphTargetDictionary: Record<string, number>;
  morphTargetInfluences: number[];
}

interface MockScene {
  meshes: MockMesh[];
  traverse(cb: (o: any) => void): void;
}

function _allFiveVowelMesh(name: string): MockMesh {
  return {
    isMesh: true,
    name,
    morphTargetDictionary: {
      Fcl_MTH_A: 0,
      Fcl_MTH_I: 1,
      Fcl_MTH_U: 2,
      Fcl_MTH_E: 3,
      Fcl_MTH_O: 4,
    },
    morphTargetInfluences: [0, 0, 0, 0, 0],
  };
}

function _onlyAaMesh(name: string): MockMesh {
  return {
    isMesh: true,
    name,
    morphTargetDictionary: {
      Fcl_MTH_A: 0,
    },
    morphTargetInfluences: [0],
  };
}

function _buildScene(): MockScene {
  const meshes: MockMesh[] = [
    _allFiveVowelMesh('FaceA'),
    _allFiveVowelMesh('FaceB'),
    _allFiveVowelMesh('FaceC'),
    _allFiveVowelMesh('FaceD'),
    _allFiveVowelMesh('FaceE'),
    _onlyAaMesh('FaceF'),
    _onlyAaMesh('FaceG'),
  ];
  return {
    meshes,
    traverse(cb) { for (const m of meshes) cb(m); },
  };
}

describe('AD-721b multi-mesh face-split regression (BF de4107b generalised)', () => {
  let scene: MockScene;
  beforeEach(() => { scene = _buildScene(); });

  it('_collectMorphMeshes(scene, VOWEL_CANDIDATES.aa) returns all 7 meshes', () => {
    const out = _collectMorphMeshes(scene, VOWEL_CANDIDATES.aa);
    expect(out).toHaveLength(7);
    // Every entry points at index 0 (Fcl_MTH_A) on its mesh.
    for (const e of out) {
      expect(e.index).toBe(0);
    }
  });

  it('_collectMorphMeshes(scene, VOWEL_CANDIDATES.ih) returns only the 5 fully-bound meshes', () => {
    const out = _collectMorphMeshes(scene, VOWEL_CANDIDATES.ih);
    expect(out).toHaveLength(5);
    const names = out.map((e) => (e.mesh as MockMesh).name).sort();
    expect(names).toEqual(['FaceA', 'FaceB', 'FaceC', 'FaceD', 'FaceE']);
    // None of the entries should be FaceF or FaceG.
    expect(names).not.toContain('FaceF');
    expect(names).not.toContain('FaceG');
  });

  it('per-vowel direct-write loop touches every mesh in each per-vowel set', () => {
    const targets: Record<VowelKey, number> = {
      aa: 1.0, ih: 0.5, ou: 0, ee: 0, oh: 0,
    };
    const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
    // Simulate the per-vowel direct-write loop from CrewVRM useFrame (D4).
    for (const v of vowelKeys) {
      const entries = _collectMorphMeshes(scene, VOWEL_CANDIDATES[v]);
      const value = targets[v];
      for (const { mesh, index } of entries) {
        if ((mesh as MockMesh).morphTargetInfluences) {
          (mesh as MockMesh).morphTargetInfluences[index] = value;
        }
      }
    }
    // Verify the aa axis was written on all 7 meshes:
    for (const m of scene.meshes) {
      expect(m.morphTargetInfluences[m.morphTargetDictionary.Fcl_MTH_A]).toBe(1.0);
    }
    // Verify the ih axis was written on the 5 fully-bound meshes:
    for (const name of ['FaceA', 'FaceB', 'FaceC', 'FaceD', 'FaceE']) {
      const m = scene.meshes.find((x) => x.name === name)!;
      expect(m.morphTargetInfluences[m.morphTargetDictionary.Fcl_MTH_I]).toBe(0.5);
    }
    // Verify the ih axis is absent on FaceF / FaceG (they don't carry I).
    for (const name of ['FaceF', 'FaceG']) {
      const m = scene.meshes.find((x) => x.name === name)!;
      expect(m.morphTargetDictionary.Fcl_MTH_I).toBeUndefined();
      // Their single morphTargetInfluences entry stays at the aa write (1.0).
      expect(m.morphTargetInfluences).toHaveLength(1);
      expect(m.morphTargetInfluences[0]).toBe(1.0);
    }
  });
});
