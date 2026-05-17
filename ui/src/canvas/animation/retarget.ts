/** AD-721e: Bone retargeting from Mixamo (Quaternius CC0 source) to VRM
 *  Humanoid spec.
 *
 *  Why this exists. Quaternius "Ultimate Animated Character Pack" (CC0) is
 *  rigged with Mixamo bone names (``mixamorig:Hips``, ``mixamorig:LeftArm``,
 *  ...). ``@pixiv/three-vrm`` Humanoid bones use unprefixed VRM Humanoid
 *  spec names (``hips``, ``leftUpperArm``, ...). ``THREE.AnimationMixer``
 *  matches ``KeyframeTrack.name`` to scene nodes by string match -- a
 *  Mixamo-rigged clip played directly against a VRM scene SILENTLY fails:
 *  the mixer ticks, time advances, no bones move, no console warning.
 *
 *  Solution. Rewrite each track name from ``mixamorig:<X>.<channel>`` to
 *  ``<vrmName>.<channel>`` BEFORE ``mixer.clipAction(clip)``. Source bytes
 *  stay verbatim (no derivative-redistribution concerns; CC0 source is
 *  preserved on disk).
 *
 *  Tracks whose source bone has no VRM equivalent (e.g., individual finger
 *  bones, when the VRM doesn't define optional finger bones) are dropped.
 */

import * as THREE from 'three';

/** AD-721e: Mixamo -> VRM Humanoid bone-name map. Covers the 22 standard
 *  VRM Humanoid required bones. Finger / facial bones are intentionally
 *  omitted -- they are VRM-optional and silently dropped when missing. */
export const MIXAMO_TO_VRM: Readonly<Record<string, string>> = Object.freeze({
  'mixamorig:Hips': 'hips',
  'mixamorig:Spine': 'spine',
  'mixamorig:Spine1': 'chest',
  'mixamorig:Spine2': 'upperChest',
  'mixamorig:Neck': 'neck',
  'mixamorig:Head': 'head',
  'mixamorig:LeftShoulder': 'leftShoulder',
  'mixamorig:LeftArm': 'leftUpperArm',
  'mixamorig:LeftForeArm': 'leftLowerArm',
  'mixamorig:LeftHand': 'leftHand',
  'mixamorig:RightShoulder': 'rightShoulder',
  'mixamorig:RightArm': 'rightUpperArm',
  'mixamorig:RightForeArm': 'rightLowerArm',
  'mixamorig:RightHand': 'rightHand',
  'mixamorig:LeftUpLeg': 'leftUpperLeg',
  'mixamorig:LeftLeg': 'leftLowerLeg',
  'mixamorig:LeftFoot': 'leftFoot',
  'mixamorig:LeftToeBase': 'leftToes',
  'mixamorig:RightUpLeg': 'rightUpperLeg',
  'mixamorig:RightLeg': 'rightLowerLeg',
  'mixamorig:RightFoot': 'rightFoot',
  'mixamorig:RightToeBase': 'rightToes',
});

/** Parse a KeyframeTrack name like "mixamorig:LeftArm.quaternion" into its
 *  ``boneName`` and ``channel`` parts. Returns null when the track name is
 *  not Mixamo-shaped (e.g., a morph-target track) so the caller can
 *  forward it untouched. */
export function _parseMixamoTrackName(
  trackName: string,
): { boneName: string; channel: string } | null {
  const dotIdx = trackName.indexOf('.');
  if (dotIdx <= 0) return null;
  const boneName = trackName.slice(0, dotIdx);
  const channel = trackName.slice(dotIdx + 1);
  if (!boneName.startsWith('mixamorig:')) return null;
  return { boneName, channel };
}

/** AD-721e: Retarget a Mixamo-rigged AnimationClip to VRM Humanoid bone
 *  names. Returns a NEW clip with rewritten tracks; the input clip is
 *  unmodified (callers may cache the original for reuse).
 *
 *  Tracks for bones not in ``MIXAMO_TO_VRM`` are dropped with a debug
 *  log (typically finger bones not in the VRM Humanoid required set).
 *  Non-Mixamo tracks (e.g., morph-target tracks if any leak in) are
 *  passed through unchanged.
 */
export function retargetMixamoToVRM(
  clip: THREE.AnimationClip,
): THREE.AnimationClip {
  const out: THREE.KeyframeTrack[] = [];
  let dropped = 0;
  for (const track of clip.tracks) {
    const parsed = _parseMixamoTrackName(track.name);
    if (parsed === null) {
      // Non-Mixamo track -- pass through untouched.
      out.push(track);
      continue;
    }
    const vrmName = MIXAMO_TO_VRM[parsed.boneName];
    if (vrmName === undefined) {
      dropped++;
      continue;
    }
    // Clone the track with a rewritten name. Use ``clone()`` so the
    // input clip stays intact for any other consumer.
    const cloned = track.clone();
    cloned.name = `${vrmName}.${parsed.channel}`;
    out.push(cloned);
  }
  if (dropped > 0) {
    // eslint-disable-next-line no-console
    console.debug(
      `[AD-721e retarget] clip=${clip.name} dropped ${dropped} ` +
      `track(s) with no VRM Humanoid equivalent`,
    );
  }
  return new THREE.AnimationClip(clip.name, clip.duration, out, clip.blendMode);
}
