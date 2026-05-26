/**
 * AD-797 (Wave 197): per-artifact list rows for the drawer.
 *
 * Each row shows name + version chip + mime-derived type icon +
 * timestamp + pinned badge (when ``_pinned_from_project=true``).
 * Click selects the artifact in the viewer.
 */
import type { ReactElement } from 'react';
import type { ArtifactView } from '../../store/useStore';

const AMBER = '#f0b060';
const DIM = '#888899';
const PINNED_AMBER = 'rgba(240, 176, 96, 0.85)';

function mimeIcon(mime: string): ReactElement {
  // Stroke-based SVG glyphs only (HXI Design Principle #3 — no emoji).
  const common = {
    width: 12, height: 12, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  if (mime === 'text/markdown') {
    return (
      <svg {...common} aria-label="markdown">
        <path d="M3 7h18v10H3z" />
        <path d="M7 14V10l2 2 2-2v4" />
        <path d="M16 10v4" /><path d="M14 12l2 2 2-2" />
      </svg>
    );
  }
  if (mime.startsWith('image/') || mime === 'text/uri-list') {
    return (
      <svg {...common} aria-label="image">
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <circle cx="9" cy="11" r="2" />
        <path d="M21 17l-5-5-7 7" />
      </svg>
    );
  }
  if (mime.startsWith('text/x-') || mime === 'application/json' ||
      mime === 'application/yaml' || mime === 'application/sql') {
    return (
      <svg {...common} aria-label="code">
        <path d="M8 6l-6 6 6 6" /><path d="M16 6l6 6-6 6" />
      </svg>
    );
  }
  return (
    <svg {...common} aria-label="text">
      <path d="M5 4h14v16H5z" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  );
}

function formatTimestamp(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString();
}

export interface ArtifactListProps {
  artifacts: ArtifactView[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function ArtifactList(props: ArtifactListProps) {
  const { artifacts, selectedId, onSelect } = props;
  if (artifacts.length === 0) {
    return (
      <div
        style={{
          color: DIM, fontSize: 11, padding: '12px 8px', textAlign: 'center',
        }}
        data-testid="artifact-list-empty"
      >
        No artifacts yet.
      </div>
    );
  }
  return (
    <div data-testid="artifact-list" style={{ overflowY: 'auto' }}>
      {artifacts.map((a) => {
        const isSelected = a.id === selectedId;
        return (
          <button
            key={a.id}
            type="button"
            onClick={() => onSelect(a.id)}
            data-testid={`artifact-row-${a.id}`}
            style={{
              display: 'flex',
              alignItems: 'center',
              width: '100%',
              gap: 6,
              background: isSelected ? 'rgba(240, 176, 96, 0.10)' : 'transparent',
              border: '1px solid '
                + (isSelected ? 'rgba(240, 176, 96, 0.3)' : 'transparent'),
              borderRadius: 4,
              padding: '6px 8px',
              cursor: 'pointer',
              color: '#e0dcd4',
              fontFamily: 'inherit',
              fontSize: 12,
              textAlign: 'left',
            }}
          >
            <span style={{ color: AMBER, display: 'inline-flex' }}>
              {mimeIcon(a.mime)}
            </span>
            <span style={{
              flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{a.name}</span>
            <span style={{
              flex: '0 0 auto',
              fontSize: 10, color: AMBER,
              border: '1px solid rgba(240, 176, 96, 0.3)',
              borderRadius: 3, padding: '0 4px',
            }}>v{a.version}</span>
            {a._pinned_from_project && (
              <span
                data-testid={`artifact-pinned-badge-${a.id}`}
                title="Pinned at project"
                style={{
                  flex: '0 0 auto', fontSize: 9, letterSpacing: 0.5,
                  color: PINNED_AMBER,
                  border: `1px solid ${PINNED_AMBER}`,
                  borderRadius: 3, padding: '0 3px',
                }}
              >PIN</span>
            )}
            <span style={{
              flex: '0 0 auto', color: DIM, fontSize: 10,
            }}>{formatTimestamp(a.created_at)}</span>
          </button>
        );
      })}
    </div>
  );
}
