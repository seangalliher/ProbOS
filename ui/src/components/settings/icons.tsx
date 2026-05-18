/* AD-741 — Stroke-SVG icons for the Settings panel.
 *
 * Per HXI Design Principle #3 (no emoji, no Material icons): every glyph is
 * an inline SVG with strokeWidth=1.5 and strokeLinecap=round. Active state
 * uses amber (#f0b060); inactive uses dim (#666680).
 */

interface IconProps {
  size?: number;
  active?: boolean;
}

const STROKE_ACTIVE = '#f0b060';
const STROKE_INACTIVE = '#666680';

function _stroke(active: boolean): string {
  return active ? STROKE_ACTIVE : STROKE_INACTIVE;
}

function svgWrap(size: number, active: boolean, children: any) {
  const s = size;
  const stroke = _stroke(active);
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke={stroke}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={active ? { filter: 'drop-shadow(0 0 4px rgba(240,176,96,0.4))' } : undefined}
    >
      {children}
    </svg>
  );
}

export function ControlPanelIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <rect x="3" y="6" width="18" height="3" />
      <rect x="3" y="11" width="18" height="3" />
      <rect x="3" y="16" width="18" height="3" />
    </>
  ));
}

export function SystemIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, <polygon points="12,3 21,12 12,21 3,12" />);
}

export function LlmTiersIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <circle cx="12" cy="12" r="3" />
      <circle cx="12" cy="12" r="9" />
    </>
  ));
}

export function MemoryIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <polygon points="12,3 21,9 21,15 12,21 3,15 3,9" />
  ));
}

export function PerceptionIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <rect x="4" y="6" width="16" height="12" rx="2" />
      <circle cx="12" cy="12" r="3" />
    </>
  ));
}

export function VoiceIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <path d="M4 12 Q 7 7, 10 12 T 16 12 T 22 12" />
    </>
  ));
}

export function AvatarsIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <circle cx="12" cy="8" r="3" />
      <path d="M5 19 Q 12 13, 19 19" />
    </>
  ));
}

export function WardRoomIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, <polygon points="12,3 19,12 12,21 5,12" />);
}

export function FederationIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <circle cx="6" cy="6" r="2" />
      <circle cx="18" cy="6" r="2" />
      <circle cx="12" cy="18" r="2" />
      <line x1="7" y1="7" x2="11" y2="17" />
      <line x1="17" y1="7" x2="13" y2="17" />
      <line x1="8" y1="6" x2="16" y2="6" />
    </>
  ));
}

export function ChannelsIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <line x1="4" y1="7" x2="20" y2="7" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="17" x2="20" y2="17" />
    </>
  ));
}

export function CloudIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <path d="M7 17 Q 4 17, 4 14 Q 4 11, 7 11 Q 7 7, 12 7 Q 17 7, 17 11 Q 20 11, 20 14 Q 20 17, 17 17 Z" />
      <line x1="12" y1="14" x2="12" y2="20" />
      <polyline points="9,17 12,14 15,17" />
    </>
  ));
}

export function ToolsIcon({ size = 14, active = false }: IconProps) {
  return svgWrap(size, active, (
    <>
      <path d="M14 4 L 20 10 L 14 16 L 12 14 L 8 18 L 6 16 L 10 12 L 8 10 Z" />
    </>
  ));
}

export const SECTION_ICONS: Record<string, (p: IconProps) => any> = {
  system: SystemIcon,
  llm_tiers: LlmTiersIcon,
  memory: MemoryIcon,
  perception: PerceptionIcon,
  voice: VoiceIcon,
  avatars: AvatarsIcon,
  ward_room: WardRoomIcon,
  federation: FederationIcon,
  channels: ChannelsIcon,
  cloud_pickers: CloudIcon,
  tools: ToolsIcon,
};

export function SectionIcon({
  sectionId,
  size = 14,
  active = false,
}: { sectionId: string; size?: number; active?: boolean }) {
  const Component = SECTION_ICONS[sectionId];
  if (Component) return Component({ size, active });
  return svgWrap(size, active, <circle cx="12" cy="12" r="3" />);
}
