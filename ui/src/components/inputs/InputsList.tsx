/**
 * AD-926: read-only Input folder list for a task workspace room.
 *
 * Presentational only — the caller passes ``inputs`` (AD-929 owns
 * fetching + layout). Each row is a download/open link to the existing
 * ``GET /api/chat/attachments/{content_hash}`` byte endpoint; there is
 * no edit/delete affordance (inputs are read-only context). Icons are
 * stroke-based inline SVG (HXI Design Principle #3 — no emoji).
 */
import type { ReactElement } from 'react';
import { attachmentUrl, type TaskInput } from './inputsApi';

const AMBER = '#f0b060';
const DIM = '#888899';

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

function formatSize(size: number | null): string {
  if (size == null) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export interface InputsListProps {
  inputs: TaskInput[];
}

export function InputsList(props: InputsListProps) {
  const { inputs } = props;
  if (inputs.length === 0) {
    return (
      <div
        style={{
          color: DIM, fontSize: 11, padding: '12px 8px', textAlign: 'center',
        }}
        data-testid="inputs-list-empty"
      >
        No inputs yet.
      </div>
    );
  }
  return (
    <div data-testid="inputs-list" style={{ overflowY: 'auto' }}>
      {inputs.map((input) => {
        const label = input.filename ?? `${input.content_hash.slice(0, 12)}…`;
        const sizeLabel = formatSize(input.size);
        return (
          <a
            key={input.content_hash}
            href={attachmentUrl(input.content_hash)}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`input-row-${input.content_hash}`}
            style={{
              display: 'flex',
              alignItems: 'center',
              width: '100%',
              gap: 6,
              background: 'transparent',
              border: '1px solid transparent',
              borderRadius: 4,
              padding: '6px 8px',
              textDecoration: 'none',
              color: '#e0dcd4',
              fontFamily: 'inherit',
              fontSize: 12,
              textAlign: 'left',
            }}
          >
            <span style={{ color: AMBER, display: 'inline-flex' }}>
              {mimeIcon(input.mime)}
            </span>
            <span style={{
              flex: '1 1 auto', minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>{label}</span>
            {sizeLabel && (
              <span style={{ color: DIM, fontSize: 10, flex: '0 0 auto' }}>
                {sizeLabel}
              </span>
            )}
          </a>
        );
      })}
    </div>
  );
}
