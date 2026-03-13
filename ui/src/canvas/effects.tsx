/* Post-processing effects — bloom with mode-based grading (Fix 2) */

import { EffectComposer, Bloom, Noise } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import { useStore } from '../store/useStore';
import { modeGrading } from './scene';

export function Effects() {
  const systemMode = useStore((s) => s.systemMode);
  const grading = modeGrading(systemMode);

  return (
    <EffectComposer>
      <Bloom
        intensity={grading.bloomStrength}
        luminanceThreshold={0.1}
        luminanceSmoothing={0.4}
        mipmapBlur
        levels={7}
      />
      <Noise
        premultiply
        blendFunction={BlendFunction.ADD}
        opacity={0.02}
      />
    </EffectComposer>
  );
}
