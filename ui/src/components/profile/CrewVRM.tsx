/** AD-721 D5: VRM loader + viewer with expression-channel mapping
 *  and TTS-driven mouth animation.
 *
 *  Subscribes to AD-718's `onSpeechEvent` and drives the `aa` blend shape
 *  from a Web Audio analyser (or a synthetic amplitude curve when real-audio
 *  capture is unavailable — see AD-721 D5 / `speechAmplitude.ts`).
 */

import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, type VRM } from '@pixiv/three-vrm';
import { onSpeechEvent } from '../../audio/voice';
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
import type { AgentSignals } from './avatarSignals';

interface Props {
  vrmUrl: string;
  agentId: string;
  expressionOverrides: Record<string, number>;
  signals: AgentSignals;
  onLoadError: () => void;
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

export function CrewVRM({ vrmUrl, agentId, expressionOverrides, signals, onLoadError }: Props) {
  const vrmRef = useRef<VRM | null>(null);
  const analyserRef = useRef<AnalyserNode | FakeAnalyser | null>(null);
  const speakingRef = useRef(false);

  // Load the VRM once per URL change.
  useEffect(() => {
    if (!vrmUrl) return;
    let mounted = true;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      vrmUrl,
      (gltf: any) => {
        if (!mounted) return;
        const vrm = gltf.userData.vrm as VRM | undefined;
        if (!vrm) {
          onLoadError();
          return;
        }
        vrmRef.current = vrm;
      },
      undefined,
      (_err: unknown) => onLoadError(),
    );
    return () => { mounted = false; };
  }, [vrmUrl, onLoadError]);

  // Subscribe to TTS events for mouth animation.
  useEffect(() => {
    const off = onSpeechEvent((e) => {
      if (e.agent_id !== agentId) return;
      if (e.type === 'start') {
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
        vrmRef.current?.expressionManager?.setValue('aa', 0);
      }
    });
    return off;
  }, [agentId]);

  useFrame((_state, delta) => {
    const vrm = vrmRef.current;
    if (!vrm) return;
    applyExpressionsFromSignals(vrm, signals, expressionOverrides);

    if (speakingRef.current && analyserRef.current) {
      const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i];
      const amp = sum / buf.length / 255;
      vrm.expressionManager?.setValue('aa', Math.min(0.9, amp * 1.4));
    }
    vrm.update(delta);
  });

  return vrmRef.current ? <primitive object={vrmRef.current.scene} /> : null;
}

export { applyExpressionsFromSignals as _applyExpressionsFromSignals };
