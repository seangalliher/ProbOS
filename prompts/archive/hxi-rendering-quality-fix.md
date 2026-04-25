# HXI Rendering Quality Fix — Dithering and Color Banding

## Problem

The HXI canvas has visible color banding (dithering/stepping) in the bloom glow gradients, especially where dark background meets glow halos. Smooth gradients show visible steps instead of continuous blending. This is a common WebGL post-processing artifact.

## Fixes (apply all 4)

### Fix 1: High-precision framebuffer + retina rendering

**File:** `ui/src/components/CognitiveCanvas.tsx`

In the `<Canvas>` component, update the `gl` prop and add `dpr`:

```tsx
<Canvas
  camera={{ position: [0, 6, 12], fov: 50, near: 0.1, far: 100 }}
  gl={{ 
    antialias: true, 
    alpha: false, 
    powerPreference: 'high-performance',
    depth: true,
    stencil: false,
  }}
  dpr={[1, 2]}
  // ... rest unchanged
```

The `dpr={[1, 2]}` renders at up to 2x pixel density on retina displays, eliminating pixelation. The `stencil: false` frees GPU memory for higher-quality color output.

### Fix 2: Add subtle noise dither to break color banding

**File:** `ui/src/canvas/effects.tsx`

Add a `Noise` effect after `Bloom` in the `EffectComposer`. This adds imperceptible grain that breaks visible color steps in dark gradients:

```tsx
import {
  EffectComposer,
  Bloom,
  Noise,
} from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';

// Inside the Effects component return:
<EffectComposer>
  <Bloom
    intensity={...existing...}
    luminanceThreshold={...existing...}
    luminanceSmoothing={...existing...}
    mipmapBlur
    levels={7}
  />
  <Noise
    premultiply
    blendFunction={BlendFunction.ADD}
    opacity={0.02}
  />
</EffectComposer>
```

The `opacity={0.02}` is nearly invisible to the eye but eliminates visible banding steps. This is standard practice in film, games, and real-time rendering.

### Fix 3: Increase bloom mipmap levels

**File:** `ui/src/canvas/effects.tsx`

Add `levels={7}` to the `Bloom` effect if not already present. More mipmap levels = smoother bloom gradient transitions:

```tsx
<Bloom
  intensity={...current value...}
  luminanceThreshold={...current value...}
  luminanceSmoothing={...current value...}
  mipmapBlur
  levels={7}
/>
```

### Fix 4: Reduce tone mapping exposure

**File:** `ui/src/components/CognitiveCanvas.tsx`

ACES filmic tone mapping can crush dark gradients, making banding worse. Reduce exposure slightly:

```tsx
onCreated={({ gl }) => {
  gl.toneMapping = 3; // ACESFilmicToneMapping
  gl.toneMappingExposure = 1.0;  // reduce from 1.2 to 1.0
}}
```

## After applying all 4 fixes

1. Rebuild: `cd ui && npm run build`
2. Refresh the browser
3. Check: bloom gradients should transition smoothly, no visible stepping
4. Run Python tests to confirm no regressions: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Do NOT Change

- No Python code changes
- No store/event changes
- No layout or positioning changes
- No new dependencies (Noise is part of `@react-three/postprocessing` already installed)
