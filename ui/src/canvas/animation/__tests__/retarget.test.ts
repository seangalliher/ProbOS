// AD-721e: bone retargeting helper tests.
//
// Validates the Mixamo -> VRM Humanoid rewrite on KeyframeTrack names. The
// retarget step runs at clip-load time before mixer.clipAction(clip) so the
// AnimationMixer can bind to the VRM scene's bone nodes.

import { describe, expect, test } from 'vitest';
import * as THREE from 'three';
import {
  retargetMixamoToVRM,
  MIXAMO_TO_VRM,
  _parseMixamoTrackName,
} from '../retarget';

function mkVectorKeyframeTrack(name: string, count = 3): THREE.VectorKeyframeTrack {
  const times = new Float32Array(count);
  for (let i = 0; i < count; i++) times[i] = i;
  const values = new Float32Array(count * 3);
  for (let i = 0; i < count * 3; i++) values[i] = i * 0.1;
  return new THREE.VectorKeyframeTrack(name, times as any, values as any);
}

function mkQuaternionKeyframeTrack(name: string, count = 3): THREE.QuaternionKeyframeTrack {
  const times = new Float32Array(count);
  for (let i = 0; i < count; i++) times[i] = i;
  const values = new Float32Array(count * 4);
  for (let i = 0; i < count * 4; i += 4) {
    values[i] = 0; values[i + 1] = 0; values[i + 2] = 0; values[i + 3] = 1;
  }
  return new THREE.QuaternionKeyframeTrack(name, times as any, values as any);
}

describe('AD-721e retargetMixamoToVRM', () => {
  test('rewrites mixamorig:* track names to VRM Humanoid names', () => {
    const tracks: THREE.KeyframeTrack[] = [
      mkVectorKeyframeTrack('mixamorig:Hips.position'),
      mkQuaternionKeyframeTrack('mixamorig:LeftArm.quaternion'),
      mkQuaternionKeyframeTrack('mixamorig:RightFoot.quaternion'),
    ];
    const clip = new THREE.AnimationClip('idle', 1.0, tracks);
    const retargeted = retargetMixamoToVRM(clip);
    const names = retargeted.tracks.map((t) => t.name).sort();
    expect(names).toEqual([
      'hips.position',
      'leftUpperArm.quaternion',
      'rightFoot.quaternion',
    ].sort());
    // Track count preserved (every input bone had a VRM mapping).
    expect(retargeted.tracks.length).toBe(3);
    // Keyframe values preserved verbatim (deep equal first track's first triple).
    const original = (tracks[0].values as Float32Array).slice(0, 3);
    const out = (retargeted.tracks[0].values as Float32Array).slice(0, 3);
    expect(Array.from(out)).toEqual(Array.from(original));
  });

  test('drops tracks with no VRM equivalent (finger bones, etc.)', () => {
    const tracks: THREE.KeyframeTrack[] = [
      mkQuaternionKeyframeTrack('mixamorig:Hips.quaternion'),
      // Finger bones -- VRM Humanoid finger bones are optional and our map
      // intentionally omits them. Must be dropped.
      mkQuaternionKeyframeTrack('mixamorig:LeftHandIndex3.quaternion'),
      mkQuaternionKeyframeTrack('mixamorig:RightHandThumb2.quaternion'),
    ];
    const clip = new THREE.AnimationClip('idle', 1.0, tracks);
    const retargeted = retargetMixamoToVRM(clip);
    expect(retargeted.tracks.length).toBe(1);
    expect(retargeted.tracks[0].name).toBe('hips.quaternion');
  });

  test('passes through non-Mixamo tracks unchanged (morph-target tracks etc.)', () => {
    const morphTrack = mkVectorKeyframeTrack('Wolf3D_Head.morphTargetInfluences[0]');
    const mixamoTrack = mkQuaternionKeyframeTrack('mixamorig:Head.quaternion');
    const clip = new THREE.AnimationClip('mixed', 1.0, [morphTrack, mixamoTrack]);
    const retargeted = retargetMixamoToVRM(clip);
    const names = new Set(retargeted.tracks.map((t) => t.name));
    expect(names.has('Wolf3D_Head.morphTargetInfluences[0]')).toBe(true);
    expect(names.has('head.quaternion')).toBe(true);
    expect(retargeted.tracks.length).toBe(2);
  });

  test('returns a new clip; input clip is unmodified', () => {
    const inTracks = [mkQuaternionKeyframeTrack('mixamorig:Hips.quaternion')];
    const clip = new THREE.AnimationClip('orig', 2.5, inTracks);
    const out = retargetMixamoToVRM(clip);
    expect(out).not.toBe(clip);
    expect(out.duration).toBe(2.5);
    expect(clip.tracks[0].name).toBe('mixamorig:Hips.quaternion');
    expect(out.tracks[0].name).toBe('hips.quaternion');
  });

  test('_parseMixamoTrackName extracts bone + channel correctly', () => {
    expect(_parseMixamoTrackName('mixamorig:Hips.position')).toEqual({
      boneName: 'mixamorig:Hips',
      channel: 'position',
    });
    expect(_parseMixamoTrackName('Wolf3D_Head.morphTargetInfluences[0]')).toBeNull();
    expect(_parseMixamoTrackName('no_dot')).toBeNull();
  });

  test('MIXAMO_TO_VRM covers the 22 required VRM Humanoid bones', () => {
    // The frozen map should have exactly 22 entries (per VRM Humanoid spec).
    expect(Object.keys(MIXAMO_TO_VRM).length).toBe(22);
    // Spot-check the corner cases that frequently break in custom rigs.
    expect(MIXAMO_TO_VRM['mixamorig:LeftArm']).toBe('leftUpperArm');
    expect(MIXAMO_TO_VRM['mixamorig:LeftForeArm']).toBe('leftLowerArm');
    expect(MIXAMO_TO_VRM['mixamorig:Spine2']).toBe('upperChest');
  });
});
