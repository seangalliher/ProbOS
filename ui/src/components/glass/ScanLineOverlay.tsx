/* ScanLineOverlay — CSS-only scan line effect (AD-391) */

interface ScanLineOverlayProps {
  intensity: number; // 0-1
}

export function ScanLineOverlay({ intensity }: ScanLineOverlayProps) {
  return (
    <div
      data-testid="scan-line-overlay"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        backgroundImage:
          'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0, 0, 0, 0.03) 2px, rgba(0, 0, 0, 0.03) 4px)',
        opacity: intensity * 0.8,
        animation: 'scan-line-scroll 8s linear infinite',
        zIndex: 2,
      }}
    >
      <style>{`
        @keyframes scan-line-scroll {
          from { transform: translateY(0); }
          to { transform: translateY(4px); }
        }
      `}</style>
    </div>
  );
}
