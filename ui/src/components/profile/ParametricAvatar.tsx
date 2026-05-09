/** AD-721 D7: Parametric fallback avatar — soft-glow capsule + emissive pulse.
 *
 * Renders when `appearance.vrm_url` is empty OR the VRM load throws.
 * Department-tinted; `useFrame` drives breathing/pulse/blocked-tilt animations
 * that encode `working_state`. Tier-3 alert flashes red rim.
 */

import { useRef, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { onSpeechEvent } from '../../audio/voice';
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
import type { AgentSignals } from './avatarSignals';

/** Map ProbOS palette tokens → hex. THREE.Color doesn't recognise "amber" etc. */
const PALETTE: Record<string, string> = {
  amber: '#f0b060',
  bridge: '#d0a030',
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  violet: '#9060c0',
  blue: '#5090d0',
  gold: '#d0a030',
};

function resolveTint(input: string): string {
  if (!input) return '#f0b060';
  if (input.startsWith('#') || input.startsWith('rgb')) return input;
  return PALETTE[input.toLowerCase()] ?? '#f0b060';
}

interface Props {
  tint: string;
  signals: AgentSignals;
  agentId?: string;
}

export function ParametricAvatar({ tint, signals, agentId }: Props) {
  const resolved = resolveTint(tint);
  const meshRef = useRef<THREE.Mesh | null>(null);
  const matRef = useRef<THREE.MeshStandardMaterial | null>(null);
  // TTS amplitude (mouth analogue: scale Y).
  const analyserRef = useRef<AnalyserNode | FakeAnalyser | null>(null);
  const speakingRef = useRef(false);

  useEffect(() => {
    const off = onSpeechEvent((e) => {
      if (agentId && e.agent_id !== agentId) return;
      if (e.type === 'start') {
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
      }
    });
    return off;
  }, [agentId]);

  useFrame((_state, _delta) => {
    const mesh = meshRef.current;
    const mat = matRef.current;
    if (!mesh || !mat) return;
    const t = (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;

    // Working-state animations.
    let scaleY = 1.0;
    let emissive = 0.5;
    let tiltZ = 0.0;
    if (signals.working_state === 'idle') {
      scaleY = 1.0 + 0.05 * Math.sin(2 * Math.PI * 0.3 * t);  // 0.3 Hz breathing
      emissive = 0.5;
    } else if (signals.working_state === 'responding') {
      scaleY = 1.0 + 0.08 * Math.sin(2 * Math.PI * 1.2 * t);  // 1.2 Hz pulse
      emissive = 0.8;
    } else if (signals.working_state === 'blocked') {
      tiltZ = 0.18;
      emissive = 0.3;
    }

    // TTS-driven mouth analogue: scale Y by amplitude.
    if (speakingRef.current && analyserRef.current) {
      const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
      analyserRef.current.getByteFrequencyData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i];
      const amp = sum / buf.length / 255;  // 0..1
      scaleY += Math.min(0.3, amp * 0.35);
    }

    mesh.scale.set(1, scaleY, 1);
    mesh.rotation.z = tiltZ;
    mat.emissiveIntensity = emissive;

    // Tier-3 alert: red rim flash at 2 Hz overrides tint.
    if (signals.tier3_alert) {
      const flash = 0.5 + 0.5 * Math.sin(2 * Math.PI * 2 * t);
      mat.emissive.set(new THREE.Color(1, 0.2 + flash * 0.2, 0.2));
    } else {
      mat.emissive.set(new THREE.Color(resolved));
    }
  });

  return (
    <group position={[0, 1.4, 0]}>      <mesh ref={meshRef}>
        <capsuleGeometry args={[0.32, 0.6, 8, 16]} />
        <meshStandardMaterial
          ref={matRef}
          color={resolved}
          emissive={resolved}
          emissiveIntensity={0.5}
          roughness={0.6}
          metalness={0.1}
        />
      </mesh>
      <pointLight color={resolved} intensity={1.0} distance={2.0} />
    </group>
  );
}
