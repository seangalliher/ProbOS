/** AD-721 D5: VRM loader + viewer with expression-channel mapping
 *  and TTS-driven mouth animation.
 *
 *  Subscribes to AD-718's `onSpeechEvent` and drives the `aa` blend shape
 *  from a Web Audio analyser (or a synthetic amplitude curve when real-audio
 *  capture is unavailable — see AD-721 D5 / `speechAmplitude.ts`).
 */

import { useEffect, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName, type VRM } from '@pixiv/three-vrm';
import { onSpeechEvent, getActiveAudioTimeMs } from '../../audio/voice';
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
import {
  buildHeuristicTrack,
  type LipSyncTrack,
  type VowelKey,
  type VisemeKey,
  _VISEME_TARGETS,
} from '../../audio/lipSyncTrack';
import { useLipSyncCapture } from '../../audio/useLipSyncCapture';
import type { LipSyncFrame } from '../../audio/lipSyncCapture';
import type { AgentSignals } from './avatarSignals';

/** AD-721b: collect every mesh whose ``morphTargetDictionary`` contains any
 *  of the candidate names. Refactor of the inline traverse block previously
 *  used for the legacy single-vowel ``aa`` set; now also called once per
 *  vowel for the new viseme-weighted driver. Behaviourally identical to the
 *  old block when called with the legacy candidate list (same first-match
 *  semantics, same iteration order). */
export function _collectMorphMeshes(
  scene: any,
  candidates: readonly string[],
): { mesh: any; index: number }[] {
  const out: { mesh: any; index: number }[] = [];
  scene.traverse((o: any) => {
    if (!o.isMesh || !o.morphTargetDictionary) return;
    for (const key of candidates) {
      if (key in o.morphTargetDictionary) {
        out.push({ mesh: o, index: o.morphTargetDictionary[key] });
        break;
      }
    }
  });
  return out;
}

/** AD-721b: per-vowel morph candidate names. Mirrors VRM 1.0 preset names
 *  (``aa/ih/ou/ee/oh``) + VRoid 0.x ``Fcl_MTH_*`` + lowercase aliases. */
export const VOWEL_CANDIDATES: Record<VowelKey, readonly string[]> = {
  aa: ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'],
  ih: ['Fcl_MTH_I', 'I', 'i', 'mouth_i', 'M_I', 'ih'],
  ou: ['Fcl_MTH_U', 'U', 'u', 'mouth_u', 'M_U', 'ou'],
  ee: ['Fcl_MTH_E', 'E', 'e', 'mouth_e', 'M_E', 'ee'],
  oh: ['Fcl_MTH_O', 'O', 'o', 'mouth_o', 'M_O', 'oh'],
};

interface Props {
  vrmUrl: string;
  agentId: string;
  expressionOverrides: Record<string, number>;
  signals: AgentSignals;
  onLoadError: () => void;
  // AD-721d: agent-authored DSL resting expression. When set, the resting
  // morph is driven across EVERY face mesh that carries the corresponding
  // ``Fcl_*`` morph target — direct mitigation of AD-721 BF de4107b
  // (multi-material face splits where the VRM expression manager binding
  // only points at the first face mesh).
  restingExpression?: string | null;
}

// AD-721d: DSL resting-expression names → ordered list of VRM morph candidates.
// First matching morph in a mesh's morphTargetDictionary wins for that mesh.
const RESTING_EXPRESSION_MORPHS: Record<string, readonly string[]> = {
  neutral: [],
  gentle_smile: ['Fcl_MTH_A', 'Fcl_ALL_Joy', 'Joy', 'happy'],
  focused: ['Fcl_ALL_Sorrow', 'Fcl_BRW_Angry', 'angry'],
  alert: ['Fcl_ALL_Surprised', 'Fcl_EYE_Surprised', 'surprised'],
};

/** AD-721d: Drive the DSL-specified resting expression across every face mesh
 * carrying a matching morph target. Direct regression mitigation for the
 * AD-721 BF de4107b multi-material face-split issue: the expression manager
 * binding only updates the first face mesh, so we iterate all meshes whose
 * morphTargetDictionary advertises one of the candidate morph names and write
 * morphTargetInfluences directly.
 *
 * Exported for unit testing — the D9 Vitest fixture invokes this with a
 * 3-face-mesh scene and asserts all 3 indices update.
 */
export function applyRestingExpressionMultiMesh(
  scene: any,
  restingExpression: string,
  weight: number = 1.0,
): number {
  const candidates = RESTING_EXPRESSION_MORPHS[restingExpression];
  if (!candidates || candidates.length === 0) return 0;
  let updated = 0;
  scene.traverse((o: any) => {
    if (!o.isMesh || !o.morphTargetDictionary || !o.morphTargetInfluences) return;
    for (const key of candidates) {
      if (key in o.morphTargetDictionary) {
        const idx = o.morphTargetDictionary[key];
        o.morphTargetInfluences[idx] = weight;
        updated++;
        break;
      }
    }
  });
  return updated;
}

/** Set a relaxed A-pose so VRMs without an animation clip don't ship as
 *  T-pose ("arms straight out"). Most VRMs default arms ~90° outward; this
 *  rotates upper arms ~60° down at the shoulder and adds a small elbow bend. */
function applyAPose(vrm: VRM): void {
  const h = vrm.humanoid;
  if (!h) return;
  const set = (name: VRMHumanBoneName, x: number, y: number, z: number) => {
    const node = h.getNormalizedBoneNode(name);
    if (node) node.rotation.set(x, y, z);
  };
  // Z-rotation on shoulders pulls arms down. Sign convention varies by VRM
  // exporter — for VRoid/most VRM 0.x the LEFT upper arm needs negative Z and
  // the RIGHT needs positive Z (the opposite of T-pose intuition).
  set(VRMHumanBoneName.LeftUpperArm, 0, 0, -1.2);
  set(VRMHumanBoneName.RightUpperArm, 0, 0, 1.2);
  set(VRMHumanBoneName.LeftLowerArm, 0, -0.15, -0.1);
  set(VRMHumanBoneName.RightLowerArm, 0, 0.15, 0.1);
  // Slight shoulder relax.
  set(VRMHumanBoneName.LeftShoulder, 0, 0, -0.05);
  set(VRMHumanBoneName.RightShoulder, 0, 0, 0.05);
}

function applyExpressionsFromSignals(vrm: VRM, signals: AgentSignals, overrides: Record<string, number>): void {
  const em = vrm.expressionManager;
  if (!em) return;

  // Reset known channels first to avoid drift.
  for (const name of ['happy', 'sad', 'angry', 'surprised', 'lookUp', 'oh', 'relaxed']) {
    em.setValue(name, 0);
  }

  if (signals.trust_delta > 0) {
    em.setValue('happy', Math.min(1, signals.trust_delta * 2));
  } else if (signals.trust_delta < 0) {
    em.setValue('sad', Math.min(1, -signals.trust_delta * 2));
  }
  if (signals.load > 0.5) {
    em.setValue('lookUp', 0.3);
    em.setValue('oh', 0.3);
  }
  if (signals.working_state === 'blocked') {
    em.setValue('angry', 0.4);
  }
  if (signals.tier3_alert) {
    em.setValue('surprised', 0.6);
  }

  // Overrides bias the baseline AFTER signal-driven weights.
  for (const [name, weight] of Object.entries(overrides)) {
    try {
      em.setValue(name, weight);
    } catch (_err) {
      // Unknown blend-shape names degrade silently — the VRM might not implement them.
    }
  }
}

/** AD-721b-2: sample a rhubarb-derived viseme schedule at ``elapsedMs`` and
 *  return per-vowel weights. Linear scan — schedules are short (typical ~50
 *  frames for a 5s utterance). Reuses ``_VISEME_TARGETS`` so the AD-721b v1
 *  vowel-weighting stays consistent. */
function _sampleRhubarbFrames(
  frames: LipSyncFrame[],
  elapsedMs: number,
): { aa: number; ih: number; ou: number; ee: number; oh: number } {
  const zero = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
  const t = elapsedMs / 1000;
  let active: LipSyncFrame | null = null;
  for (const f of frames) {
    if (t >= f.time && t < f.time + f.duration) { active = f; break; }
  }
  if (!active) return zero;
  const target = _VISEME_TARGETS[active.viseme as VisemeKey] ?? zero;
  return {
    aa: target.aa,
    ih: target.ih,
    ou: target.ou,
    ee: target.ee,
    oh: target.oh,
  };
}

export function CrewVRM({ vrmUrl, agentId, expressionOverrides, signals, onLoadError, restingExpression }: Props) {
  const vrmRef = useRef<VRM | null>(null);
  // BF: also keep VRM in state so React mounts <primitive> after load.
  // Updating a ref alone does not trigger a re-render, which previously
  // meant the avatar scene was loaded but never inserted into the R3F tree
  // until some unrelated event (e.g. dragging the window) re-rendered.
  const [vrmReady, setVrmReady] = useState<VRM | null>(null);
  const analyserRef = useRef<AnalyserNode | FakeAnalyser | null>(null);
  const speakingRef = useRef(false);
  // Cache which mouth blendshape names this VRM actually exposes — different
  // exporters use different names (preset 'aa', VRoid 'A', VRM0 'Fcl_MTH_A', etc.)
  const mouthShapesRef = useRef<string[]>([]);
  // Direct morph-target driver: many VRoid 0.x exports split the face into
  // multiple meshes (one per material) and the VRM expression bindings only
  // point at the first one. We collect ALL meshes that have Fcl_MTH_A and
  // drive their morphTargetInfluences directly so the entire face animates.
  const directMouthMeshesRef = useRef<{ mesh: any; index: number }[]>([]);
  // Low-pass smoothed mouth value so the motion feels natural rather than
  // raw analyser noise. Adjusted with exponential smoothing in useFrame.
  const smoothedMouthRef = useRef(0);
  // AD-721b: per-vowel expression-name candidates (subset of VOWEL_CANDIDATES
  // that the loaded VRM actually exposes via expressionManager). Cached at
  // load time alongside mouthShapesRef.
  const vowelShapesRef = useRef<Record<VowelKey, string[]>>(
    { aa: [], ih: [], ou: [], ee: [], oh: [] }
  );
  // AD-721b: per-vowel direct-mesh sets. BF de4107b multi-mesh fix
  // generalised from the single ``aa`` axis to all five vowels. Each entry
  // is the morphTargetInfluences index for that vowel on that mesh.
  const directVowelMeshesRef = useRef<Record<VowelKey, { mesh: any; index: number }[]>>(
    { aa: [], ih: [], ou: [], ee: [], oh: [] }
  );
  // AD-721b: per-vowel smoothed weight, exponential-blended in useFrame.
  const smoothedVowelsRef = useRef<Record<VowelKey, number>>(
    { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 }
  );
  // AD-721b: active viseme track (null = fallback to amplitude path).
  const currentTrackRef = useRef<LipSyncTrack | null>(null);
  const startedAtMsRef = useRef<number>(0);

  // AD-721b-2: real-audio capture path. Always-on — honest-degrade chains
  // end-to-end on the server (capture-fail → 0-byte short-circuit, server-fail
  // → backend: "heuristic" → empty frames). When the server returns a non-empty
  // rhubarb schedule, prefer it. When empty, fall through to the existing
  // heuristic path (currentTrackRef from buildHeuristicTrack).
  const lipsync = useLipSyncCapture({ enabled: true, agentId });
  const realFramesRef = useRef<LipSyncFrame[]>([]);
  useEffect(() => { realFramesRef.current = lipsync.frames; }, [lipsync.frames]);

  // Load the VRM once per URL change.
  useEffect(() => {
    if (!vrmUrl) return;
    let mounted = true;
    // Resolve bare filenames (e.g. "Ezri.vrm") against the avatar-serving API.
    // Absolute / root-relative URLs are passed through.
    const resolvedUrl =
      /^(https?:|\/|blob:|data:)/.test(vrmUrl) ? vrmUrl : `/api/system/avatars/${vrmUrl}`;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      resolvedUrl,
      (gltf: any) => {
        if (!mounted) return;
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) {
          onLoadError();
          return;
        }
        // VRM 0.x models face -Z; rotate so they face the camera (+Z).
        // No-op for VRM 1.0 models, which already face +Z.
        try { VRMUtils.rotateVRM0(vrm); } catch (_e) { /* older lib versions */ }
        // Disable frustum culling — tight camera + skinned meshes can clip otherwise.
        vrm.scene.traverse((obj: any) => { obj.frustumCulled = false; });
        // Lower the arms — VRMs ship in T-pose by default.
        applyAPose(vrm);
        // AD-721 diagnostics: log material + texture status to console so we
        // can tell whether a "white blob" is a lighting issue vs a texture
        // decode / MToon-default-color issue.
        const matSummary: { name: string; type: string; map: boolean; color?: string }[] = [];
        vrm.scene.traverse((obj: any) => {
          if (obj.isMesh && obj.material) {
            const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
            for (const m of mats) {
              matSummary.push({
                name: obj.name,
                type: m.type || m.constructor?.name,
                map: !!m.map,
                color: m.color?.getHexString?.(),
              });
            }
          }
        });
        // eslint-disable-next-line no-console
        console.log('[AD-721 VRM loaded]', { url: vrmUrl, meta: vrm.meta, materials: matSummary });
        const em: any = vrm.expressionManager;
        const candidates = ['aa', 'a', 'A', 'Fcl_MTH_A', 'mouth_a', 'M_A'];
        const found: string[] = [];
        if (em) {
          // VRM 1.0: em.expressions is a list with name strings.
          // VRM 0.x: em.blendShapeGroups; @pixiv/three-vrm normalises to expressions.
          const known = new Set<string>();
          (em.expressions ?? []).forEach((x: any) => { if (x?.expressionName) known.add(x.expressionName); });
          (em._expressionMap ? Object.keys(em._expressionMap) : []).forEach((n: string) => known.add(n));
          for (const name of candidates) {
            if (known.has(name)) found.push(name);
          }
        }
        mouthShapesRef.current = found;
        // Collect every mesh with a recognised mouth-open morph target so
        // we can drive them all directly (works around incomplete VRM
        // expression bindings on multi-material face meshes).
        // AD-721 BF de4107b: legacy single-vowel ``aa`` set — kept for the
        // fallback amplitude path when buildHeuristicTrack returns null.
        const morphCandidates = ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'];
        directMouthMeshesRef.current = _collectMorphMeshes(vrm.scene, morphCandidates);

        // AD-721b: per-vowel mesh sets for the viseme-weighted driver. Each
        // vowel gets its own collection across ALL face meshes — the
        // BF de4107b multi-mesh guarantee generalised to all five vowels.
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        const known = new Set<string>();
        if (em) {
          (em.expressions ?? []).forEach((x: any) => {
            if (x?.expressionName) known.add(x.expressionName);
          });
          (em._expressionMap ? Object.keys(em._expressionMap) : [])
            .forEach((n: string) => known.add(n));
        }
        for (const v of vowelKeys) {
          directVowelMeshesRef.current[v] = _collectMorphMeshes(
            vrm.scene, VOWEL_CANDIDATES[v]
          );
          vowelShapesRef.current[v] = (VOWEL_CANDIDATES[v] as readonly string[])
            .filter((n) => known.has(n));
        }
        // AD-721d: apply DSL resting expression across every face mesh
        // carrying a matching morph target (multi-mesh face-split fix).
        if (restingExpression && restingExpression !== 'neutral') {
          applyRestingExpressionMultiMesh(vrm.scene, restingExpression, 1.0);
        }
        vrmRef.current = vrm;
        setVrmReady(vrm);
      },
      undefined,
      (err: unknown) => {
        // eslint-disable-next-line no-console
        console.warn('[AD-721 VRM load failed]', { url: resolvedUrl, err });
        onLoadError();
      },
    );
    return () => { mounted = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vrmUrl]);

  // Subscribe to TTS events for mouth animation.
  useEffect(() => {
    const off = onSpeechEvent((e) => {
      if (e.agent_id !== agentId) return;
      if (e.type === 'start') {
        // AD-721b: try the heuristic viseme track first; fall back to the
        // AD-721 D5 amplitude analyser path when the track is null/empty.
        const text = e.utterance.text ?? '';
        const rate = e.utterance.rate || 1.0;
        currentTrackRef.current = buildHeuristicTrack(text, { rate });
        startedAtMsRef.current = (typeof performance !== 'undefined'
          ? performance.now() : Date.now());
        // Always wire the analyser too — fallback path needs it AND it costs
        // nothing when the viseme track is active (we just don't read it).
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
        currentTrackRef.current = null;
        lipsync.reset();   // AD-721b-2: clear stale rhubarb frames
        // Close all detected mouth shapes (legacy single-vowel set).
        const em = vrmRef.current?.expressionManager;
        if (em) for (const n of mouthShapesRef.current) em.setValue(n, 0);
        for (const { mesh, index } of directMouthMeshesRef.current) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
        }
        // AD-721b: zero ALL 5 vowels across ALL meshes (generalises the
        // single-vowel zero above to the new per-vowel sets).
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          if (em) for (const n of vowelShapesRef.current[v]) em.setValue(n, 0);
          for (const { mesh, index } of directVowelMeshesRef.current[v]) {
            if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
          }
          smoothedVowelsRef.current[v] = 0;
        }
      }
    });
    return off;
  }, [agentId]);

  useFrame((_state, delta) => {
    const vrm = vrmRef.current;
    if (!vrm) return;
    applyExpressionsFromSignals(vrm, signals, expressionOverrides);

    // Idle body animation: breathing + gentle sway. Adds life when no clip exists.
    const t = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
    const h = vrm.humanoid;
    const head = h?.getNormalizedBoneNode(VRMHumanBoneName.Head);
    const chest = h?.getNormalizedBoneNode(VRMHumanBoneName.Chest)
                ?? h?.getNormalizedBoneNode(VRMHumanBoneName.UpperChest)
                ?? h?.getNormalizedBoneNode(VRMHumanBoneName.Spine);
    if (head) {
      const sway = Math.sin(t * 0.6) * 0.03;
      const bob = Math.sin(t * 1.4) * 0.015;
      const speakBob = speakingRef.current ? Math.sin(t * 5) * 0.04 : 0;
      head.rotation.y = sway;
      head.rotation.x = bob + speakBob;
    }
    if (chest) {
      // Subtle breathing — 0.25 Hz, ±1.5%.
      const breathe = 1 + Math.sin(t * 2 * Math.PI * 0.25) * 0.015;
      chest.scale.set(breathe, breathe, breathe);
    }

    if (speakingRef.current) {
      const em = vrm.expressionManager;
      const rhubarbFrames = realFramesRef.current;
      const track = currentTrackRef.current;
      if (rhubarbFrames.length > 0) {
        // AD-721b-2: prefer the real-audio rhubarb schedule when present.
        // BF-283 (2026-05-13): anchor to audio.currentTime when an <audio>
        // element is playing (Piper TTS path) — playbackRate scales it
        // automatically so AD-735 volume + AD-737 emotion rate modulation
        // never drift visemes from audio. Fall back to wall-clock when the
        // audio element is null (e.g. SpeechSynthesisUtterance fallback —
        // rhubarbFrames is empty in that case so this branch isn't hit,
        // but the fallback keeps the contract sound).
        const audioMs = getActiveAudioTimeMs();
        const elapsed = audioMs !== null
          ? audioMs
          : ((typeof performance !== 'undefined'
              ? performance.now() : Date.now()) - startedAtMsRef.current);
        const w = _sampleRhubarbFrames(rhubarbFrames, elapsed);
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          const target = w[v];
          const k = target > smoothedVowelsRef.current[v] ? 0.30 : 0.18;
          smoothedVowelsRef.current[v] +=
            (target - smoothedVowelsRef.current[v]) * k;
          const value = smoothedVowelsRef.current[v];
          if (em) for (const n of vowelShapesRef.current[v]) em.setValue(n, value);
        }
      } else if (track) {
        // AD-721b viseme-weighted path: sample the track at the current
        // elapsed time, smooth per-vowel (faster attack than release), and
        // write each vowel's smoothed weight to its expression name AND to
        // every direct mesh in directVowelMeshesRef.
        const now = (typeof performance !== 'undefined'
          ? performance.now() : Date.now());
        const elapsed = now - startedAtMsRef.current;
        const w = track.sample(elapsed);
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          const target = w[v];
          // 60-fps coefficients pinned per dispatch §3 (HXI Principle #4):
          // attack ~50 ms (k≈0.30), release ~100 ms (k≈0.18).
          const k = target > smoothedVowelsRef.current[v] ? 0.30 : 0.18;
          smoothedVowelsRef.current[v] +=
            (target - smoothedVowelsRef.current[v]) * k;
          const value = smoothedVowelsRef.current[v];
          if (em) for (const n of vowelShapesRef.current[v]) em.setValue(n, value);
        }
      } else {
        // Tier-2 fallback: AD-721 D5 amplitude path verbatim.
        let amp = 0;
        if (analyserRef.current) {
          const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
          analyserRef.current.getByteFrequencyData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i];
          amp = sum / buf.length / 255;
        }
        const target = Math.min(1.0, amp * 1.6);
        const k = target > smoothedMouthRef.current ? 0.30 : 0.18;
        smoothedMouthRef.current += (target - smoothedMouthRef.current) * k;
        const value = smoothedMouthRef.current;
        if (em) {
          const targets = mouthShapesRef.current.length > 0
            ? mouthShapesRef.current : ['aa', 'a', 'A'];
          for (const n of targets) em.setValue(n, value);
        }
      }
    } else if (smoothedMouthRef.current > 0.01) {
      smoothedMouthRef.current *= 0.6;
    }
    // Run expression manager + bone update first.
    vrm.update(delta);
    // Direct-write morph influences AFTER vrm.update() so the expression
    // manager doesn't clobber them on multi-mesh face splits.
    if (currentTrackRef.current) {
      // AD-721b: per-vowel direct write across ALL meshes per vowel.
      const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
      for (const v of vowelKeys) {
        const value = smoothedVowelsRef.current[v];
        for (const { mesh, index } of directVowelMeshesRef.current[v]) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = value;
        }
      }
    } else {
      // Fallback: AD-721 BF de4107b legacy single-vowel direct write.
      const v = smoothedMouthRef.current;
      for (const { mesh, index } of directMouthMeshesRef.current) {
        if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = v;
      }
    }
  });

  return vrmReady ? <primitive object={vrmReady.scene} /> : null;
}

export { applyExpressionsFromSignals as _applyExpressionsFromSignals };
