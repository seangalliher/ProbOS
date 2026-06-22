/* AD-905: ZoneStrip — categorical cognitive-zone history band for the Clinical view.
 *
 * Renders the agent's recent green/amber/red zone history as an equal-width band
 * of SVG rects (oldest → newest). A categorical companion to Sparkline: zones are
 * discrete states, not a continuous trend, so a colored band reads more honestly
 * than a line would. A fixed 0-100 viewBox scales to the container.
 *
 * HXI #3: SVG only, no emoji. HXI #4: color encodes state (green healthy / amber
 * caution / red distress / dim unknown).
 */

const ZONE_COLORS: Record<string, string> = {
  green: '#60c070',
  amber: '#f0b060',
  red: '#d05050',
};
const UNKNOWN_ZONE = '#666680';

/** Resolve a zone label to its HXI color. Exported so the ClinicalPanel readout
 * pill stays in lockstep with the strip (single source of truth). */
export function zoneColor(zone: string): string {
  return ZONE_COLORS[(zone || '').toLowerCase()] ?? UNKNOWN_ZONE;
}

interface ZoneStripProps {
  zones: { zone: string; timestamp: number }[];
  testId: string;
  ariaLabel: string;
}

export function ZoneStrip({ zones, testId, ariaLabel }: ZoneStripProps) {
  // Empty → a single dim baseline rect (no zone history yet).
  if (!zones || zones.length === 0) {
    return (
      <svg
        data-testid={testId}
        role="img"
        aria-label={ariaLabel}
        viewBox="0 0 100 12"
        preserveAspectRatio="none"
        style={{ width: '100%', height: 12, display: 'block' }}
      >
        <title>{ariaLabel}</title>
        <rect x="0" y="0" width="100" height="12" fill="#222230" />
      </svg>
    );
  }

  const segW = 100 / zones.length;

  return (
    <svg
      data-testid={testId}
      role="img"
      aria-label={ariaLabel}
      viewBox="0 0 100 12"
      preserveAspectRatio="none"
      style={{ width: '100%', height: 12, display: 'block' }}
    >
      <title>{ariaLabel}</title>
      {zones.map((z, i) => (
        <rect
          key={i}
          x={(i * segW).toFixed(3)}
          y="0"
          width={segW.toFixed(3)}
          height="12"
          fill={zoneColor(z.zone)}
        />
      ))}
    </svg>
  );
}
