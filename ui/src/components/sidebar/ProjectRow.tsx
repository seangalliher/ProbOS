/*
 * AD-793 (Wave 196) — ProjectRow: expandable Projects-section entry.
 *
 * Renders a chevron + project name + thread count line. When expanded,
 * the parent ThreadSidebar nests `<ThreadRow>` children below this row.
 *
 * HXI #3: inline SVG icons (no emoji, no Material). Stroke-based.
 * HXI #4: amber active state on hover; dim default.
 *
 * Pure presentational: state lives in the parent (expansion map +
 * localStorage persistence). Right-click opens the ProjectContextMenu.
 */
import type { CSSProperties } from 'react';

const AMBER = '#f0b060';
const DIM = '#666680';
const TEXT = '#e0dcd4';

export interface ProjectRowProps {
  projectId: string;
  name: string;
  threadCount: number;
  expanded: boolean;
  onToggle: (projectId: string) => void;
  onContextMenu: (projectId: string, x: number, y: number) => void;
}

function GlyphChevronDown({ open }: { open: boolean }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 24 24"
      fill="none"
      stroke={AMBER}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transform: open ? 'rotate(0deg)' : 'rotate(-90deg)',
        transition: 'transform 0.15s',
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

function GlyphFolder() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke={AMBER}
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0 }}
      aria-hidden="true"
    >
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
    </svg>
  );
}

export function ProjectRow({
  projectId,
  name,
  threadCount,
  expanded,
  onToggle,
  onContextMenu,
}: ProjectRowProps) {
  const rowStyle: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    margin: '1px 4px',
    fontSize: 12,
    color: TEXT,
    cursor: 'pointer',
    borderRadius: 4,
    userSelect: 'none',
  };
  return (
    <div
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-label={`Project ${name} (${threadCount} threads)`}
      data-testid={`project-row-${projectId}`}
      onClick={() => onToggle(projectId)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(projectId, e.clientX, e.clientY);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onToggle(projectId);
        } else if (e.key === 'F10' && e.shiftKey) {
          e.preventDefault();
          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
          onContextMenu(projectId, rect.left + 8, rect.bottom);
        }
      }}
      style={rowStyle}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.background = 'rgba(240, 176, 96, 0.08)';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = 'transparent';
      }}
    >
      <GlyphChevronDown open={expanded} />
      <GlyphFolder />
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          flex: 1,
        }}
      >
        {name}
      </span>
      <span style={{ color: DIM, fontSize: 10, flexShrink: 0 }}>{threadCount}</span>
    </div>
  );
}

export default ProjectRow;
