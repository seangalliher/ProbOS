/* DataRainOverlay — matrix-style falling hex characters (AD-391) */

import { useRef, useEffect } from 'react';

interface DataRainOverlayProps {
  intensity: number; // 0-1
  stateColor: string; // hex color from bridge state
}

const CHARS = '0123456789ABCDEF\u2588\u2593\u2592';

export function DataRainOverlay({ intensity, stateColor }: DataRainOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Size canvas to parent
    const resize = () => {
      canvas.width = canvas.parentElement?.clientWidth ?? window.innerWidth;
      canvas.height = canvas.parentElement?.clientHeight ?? window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    const colWidth = 14;
    const cols = Math.floor(canvas.width / colWidth);
    // Density scales with intensity
    const activeCols = Math.max(1, Math.floor(cols * (0.3 + intensity * 0.7)));

    // Initialize column positions (randomized)
    const drops: number[] = new Array(cols).fill(0).map(() => Math.random() * canvas.height);
    const speeds: number[] = new Array(cols).fill(0).map(() => 30 + Math.random() * 30);
    // Select which columns are active
    const activeSet = new Set<number>();
    const indices = Array.from({ length: cols }, (_, i) => i);
    for (let i = indices.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [indices[i], indices[j]] = [indices[j], indices[i]];
    }
    for (let i = 0; i < activeCols; i++) activeSet.add(indices[i]);

    let lastTime = performance.now();

    const draw = (now: number) => {
      const dt = (now - lastTime) / 1000;
      lastTime = now;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = "10px 'JetBrains Mono', monospace";

      for (let i = 0; i < cols; i++) {
        if (!activeSet.has(i)) continue;

        drops[i] += speeds[i] * dt;
        if (drops[i] > canvas.height + 20) {
          drops[i] = -20;
        }

        const x = i * colWidth;
        const y = drops[i];

        // Fade: top = full opacity, bottom = 0
        const fadeRatio = 1 - Math.max(0, Math.min(1, y / canvas.height));
        const alpha = fadeRatio * intensity * 0.25;

        if (alpha > 0.01) {
          ctx.fillStyle = stateColor;
          ctx.globalAlpha = alpha;
          const char = CHARS[Math.floor(Math.random() * CHARS.length)];
          ctx.fillText(char, x, y);
        }
      }
      ctx.globalAlpha = 1;

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', resize);
    };
  }, [intensity, stateColor]);

  return (
    <canvas
      ref={canvasRef}
      data-testid="data-rain-overlay"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 1,
      }}
    />
  );
}
