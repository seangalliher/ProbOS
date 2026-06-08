import React from 'react';

// Shared SVG defaults per HXI Design Principle #3
const defaultProps = {
  xmlns: 'http://www.w3.org/2000/svg',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

const baseStyle: React.CSSProperties = {
  display: 'inline-block',
  verticalAlign: 'middle',
};

interface GlyphProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

export const ChevronDown: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 6 L8 10 L12 6" />
  </svg>
);

export const ChevronRight: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M6 4 L10 8 L6 12" />
  </svg>
);

export const ChevronUp: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 10 L8 6 L12 10" />
  </svg>
);

export const ArrowLeft: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M10 4 L4 8 L10 12" />
    <path d="M4 8 H13" />
  </svg>
);

export const ArrowRight: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M6 4 L12 8 L6 12" />
    <path d="M3 8 H12" />
  </svg>
);

export const ArrowUp: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 10 L8 4 L12 10" />
    <path d="M8 4 V13" />
  </svg>
);

export const ArrowDown: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 6 L8 12 L12 6" />
    <path d="M8 3 V12" />
  </svg>
);

export const Close: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 4 L12 12 M12 4 L4 12" />
  </svg>
);

// AD-917: add-participant affordance for the group-chat header (HXI #3 — stroke-SVG, no fill).
export const UserPlus: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="6" cy="5" r="2.5" />
    <path d="M2 13 a4 4 0 0 1 8 0" />
    <path d="M12 5 V9 M10 7 H14" />
  </svg>
);

// AD-837: Ward Room window controls (HXI Principle #3 — stroke-SVG, no emoji).
// Undock — detach docked sidebar into a floating window (arrow leaving a frame).
export const Undock: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M7 3 H4 A1 1 0 0 0 3 4 V12 A1 1 0 0 0 4 13 H12 A1 1 0 0 0 13 12 V9" />
    <path d="M9 3 H13 V7" />
    <path d="M13 3 L8 8" />
  </svg>
);

// Dock — re-attach a floating window back into the sidebar (arrow into a frame).
export const Dock: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M3 4 A1 1 0 0 1 4 3 H12 A1 1 0 0 1 13 4 V12 A1 1 0 0 1 12 13 H4 A1 1 0 0 1 3 12" />
    <path d="M6 4 V12" />
  </svg>
);

// Maximize — expand floating window to full screen (corner-bracket frame).
export const Maximize: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M3 6 V3 H6" />
    <path d="M10 3 H13 V6" />
    <path d="M13 10 V13 H10" />
    <path d="M6 13 H3 V10" />
  </svg>
);

// Restore — return maximized window to its prior floating size (inset frame).
export const Restore: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M6 6 H13 V13 H6 Z" />
    <path d="M6 4 V3 H11 V8 H10" />
  </svg>
);

export const Warning: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M8 3 L14 13 H2 Z" />
    <path d="M8 7 V9 M8 11 V11.5" />
  </svg>
);

export const StatusDone: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="8" r="4" fill="currentColor" stroke="none" />
  </svg>
);

export const StatusPending: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="8" r="4" />
  </svg>
);

export const StatusInProgress: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="8" r="4" />
    <path d="M8 4 A4 4 0 0 0 8 12 Z" fill="currentColor" />
  </svg>
);

export const StatusFailed: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="8" r="5" />
    <path d="M6 6 L10 10 M10 6 L6 10" />
  </svg>
);

export const Expand: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M6 4 H12 V10" />
    <path d="M12 4 L4 12" />
  </svg>
);

export const Diamond: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M8 2 L14 8 L8 14 L2 8 Z" />
  </svg>
);

export const DiamondOpen: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M8 2 L14 8 L8 14 L2 8 Z" />
  </svg>
);

export const Bullseye: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="8" r="5" />
    <circle cx="8" cy="8" r="2" />
  </svg>
);

export const Check: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M3 8 L6 11 L13 4" />
  </svg>
);

export const XMark: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M4 4 L12 12 M12 4 L4 12" />
  </svg>
);

export const Sparkle: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M8 2 L9.5 6.5 L14 8 L9.5 9.5 L8 14 L6.5 9.5 L2 8 L6.5 6.5 Z" />
  </svg>
);

export const PlayArrow: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M5 3 L13 8 L5 13 Z" />
  </svg>
);

export const Lock: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M5 8 H11 V13 H5 Z" />
    <path d="M6 8 V6 A2 2 0 0 1 10 6 V8" />
  </svg>
);

export const Unlock: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M5 8 H11 V13 H5 Z" />
    <path d="M6 8 V6 A2 2 0 0 1 10 6" />
  </svg>
);

export const Comment: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <path d="M3 3 H13 Q14 3 14 4 V10 Q14 11 13 11 H6 L3 14 V4 Q3 3 4 3 Z" />
  </svg>
);

export const Pin: React.FC<GlyphProps> = ({ size = 12, className, style }) => (
  <svg {...defaultProps} width={size} height={size} viewBox="0 0 16 16" className={className} style={{ ...baseStyle, ...style }}>
    <circle cx="8" cy="5" r="2.5" />
    <path d="M8 7.5 V14" />
  </svg>
);
