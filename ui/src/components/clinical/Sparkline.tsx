/* AD-905: Sparkline — reusable pure-SVG trend primitive for the Clinical view.
 *
 * Mirrors the inline Sparkline in BehavioralMetricsPanel (deliberately NOT a
 * shared import — that one is private to the behavioral panel) but adds two
 * things the clinical streams need: (a) an optional fixed [min,max]
 * normalization window for bounded series like self-similarity (0..1), so a
 * flat-but-high series reads as high rather than auto-scaling to fill the band;
 * and (b) full a11y (role=img + aria-label + <title>).
 *
 * A fixed 0-100 viewBox scales to the container via width/height 100% — no DOM
 * measurement. HXI #3: stroke-only SVG, strokeWidth 1.5, amber default, no emoji.
 */

interface SparklineProps {
  values: number[];
  color?: string;
  testId: string;
  ariaLabel: string;
  min?: number;
  max?: number;
}

export function Sparkline({
  values,
  color = '#f0b060',
  testId,
  ariaLabel,
  min,
  max,
}: SparklineProps) {
  const finite = values.filter(v => typeof v === 'number' && isFinite(v));

  // Empty/single-point series → dashed baseline (nothing to trend yet).
  if (finite.length < 2) {
    return (
      <svg
        data-testid={testId}
        role="img"
        aria-label={ariaLabel}
        viewBox="0 0 100 24"
        preserveAspectRatio="none"
        style={{ width: '100%', height: 24, display: 'block' }}
      >
        <title>{ariaLabel}</title>
        <path
          d="M0,12 L100,12"
          stroke="#444458"
          strokeWidth={1}
          strokeDasharray="2 3"
          fill="none"
        />
      </svg>
    );
  }

  // Normalize to the caller-provided window when given (e.g. 0..1 for a bounded
  // metric), else to the data's own min/max.
  const lo = typeof min === 'number' && isFinite(min) ? min : Math.min(...finite);
  const hi = typeof max === 'number' && isFinite(max) ? max : Math.max(...finite);
  const range = hi - lo;
  const denom = range > 1e-9 ? range : 1;
  const stepX = 100 / (finite.length - 1);
  const points = finite
    .map((v, i) => {
      const x = i * stepX;
      // Invert Y: high value → top of the viewBox.
      const y = 22 - ((v - lo) / denom) * 20;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg
      data-testid={testId}
      role="img"
      aria-label={ariaLabel}
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      style={{ width: '100%', height: 24, display: 'block' }}
    >
      <title>{ariaLabel}</title>
      <polyline
        points={points}
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}
