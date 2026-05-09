/** AD-721 D3: 3D avatar popout — VRM viewer with parametric fallback. */

import { Suspense, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { CrewVRM } from './CrewVRM';
import { ParametricAvatar } from './ParametricAvatar';
import type { AgentSignals } from './avatarSignals';

export interface CrewAppearance {
  vrm_url: string;
  expression_overrides: Record<string, number>;
  color_palette_hint: string;
}

interface Props {
  agentId: string;
  appearance: CrewAppearance | null;
  departmentColor: string;
  agentSignals: AgentSignals;
  onClose: () => void;
}

export function CrewAvatarPopout({
  agentId,
  appearance,
  departmentColor,
  agentSignals,
  onClose,
}: Props) {
  const [loadFailed, setLoadFailed] = useState(false);
  const useVRM = !!appearance?.vrm_url && !loadFailed;
  const tint = appearance?.color_palette_hint || departmentColor;

  return (
    <div
      role="dialog"
      aria-label={`Avatar — ${agentId}`}
      style={{
        position: 'fixed',
        right: 24,
        bottom: 24,
        width: 320,
        height: 480,
        background: 'rgba(10, 10, 18, 0.92)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 12,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        zIndex: 30,
        animation: 'popout-in 220ms ease-out',
      }}
    >
      <button
        onClick={onClose}
        aria-label="Close avatar"
        style={{
          position: 'absolute',
          top: 6,
          right: 6,
          background: 'none',
          border: 'none',
          color: '#8888a0',
          fontSize: 16,
          cursor: 'pointer',
          zIndex: 1,
        }}
      >
        {/* Inline SVG close glyph (HXI Design Principle #3 — no emoji). */}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
             strokeWidth="1.5" strokeLinecap="round">
          <line x1="3" y1="3" x2="13" y2="13" />
          <line x1="13" y1="3" x2="3" y2="13" />
        </svg>
      </button>
      <Canvas camera={{ position: [0, 1.4, 1.5], fov: 30 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, 4, 2]} intensity={0.8} />
        <Suspense fallback={null}>
          {useVRM ? (
            <CrewVRM
              vrmUrl={appearance!.vrm_url}
              agentId={agentId}
              expressionOverrides={appearance!.expression_overrides}
              signals={agentSignals}
              onLoadError={() => setLoadFailed(true)}
            />
          ) : (
            <ParametricAvatar tint={tint} signals={agentSignals} agentId={agentId} />
          )}
        </Suspense>
      </Canvas>
    </div>
  );
}
