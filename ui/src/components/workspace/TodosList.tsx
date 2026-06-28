/**
 * AD-1083: room Todo checklist rows — the AD-1080 senior-validation loop made
 * visible in the workspace sidecar. Each row: status glyph + label + (for a
 * submitted step) Confirm / Reject affordances for the Captain. Done = green
 * check, rejected = red x, submitted = amber dot (awaiting validation),
 * in_progress = amber ring, pending = dim ring.
 *
 * HXI Design Principle #3 — inline stroke-SVG glyphs only, no emoji.
 */
import type { TodoStep } from './todosApi';

const AMBER = '#f0b060';
const DIM = '#666680';
const GREEN = '#60c070';
const RED = '#d05050';

const COMMON = {
  width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function statusGlyph(status: TodoStep['status']) {
  if (status === 'done') {
    return <svg {...COMMON} style={{ color: GREEN }} aria-label="done"><path d="M20 6L9 17l-5-5" /></svg>;
  }
  if (status === 'rejected') {
    return <svg {...COMMON} style={{ color: RED }} aria-label="rejected"><path d="M6 6l12 12M18 6L6 18" /></svg>;
  }
  if (status === 'submitted') {
    return <svg {...COMMON} style={{ color: AMBER }} aria-label="awaiting review"><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></svg>;
  }
  if (status === 'in_progress') {
    return <svg {...COMMON} style={{ color: AMBER }} aria-label="in progress"><circle cx="12" cy="12" r="9" /></svg>;
  }
  return <svg {...COMMON} style={{ color: DIM }} aria-label="pending"><circle cx="12" cy="12" r="9" /></svg>;
}

export interface TodosListProps {
  steps: TodoStep[];
  onConfirm: (index: number) => void;
  onReject: (index: number) => void;
}

export function TodosList(props: TodosListProps) {
  const { steps, onConfirm, onReject } = props;
  if (steps.length === 0) {
    return (
      <div data-testid="todos-empty" style={{ fontSize: 11, color: DIM, padding: '6px 10px' }}>
        No todos yet.
      </div>
    );
  }
  return (
    <ul data-testid="todos-list" style={{ listStyle: 'none', margin: 0, padding: '2px 0' }}>
      {steps.map((s, i) => (
        <li key={i} data-testid={`todo-row-${i}`}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px' }}>
          <span style={{ flex: '0 0 auto', display: 'inline-flex' }}>{statusGlyph(s.status)}</span>
          <span style={{
            flex: '1 1 auto', fontSize: 11,
            color: s.status === 'done' ? DIM : '#cfcfe0',
            textDecoration: s.status === 'done' ? 'line-through' : 'none',
          }}>
            {i + 1}. {s.label}
          </span>
          {s.status === 'submitted' && (
            <span style={{ flex: '0 0 auto', display: 'inline-flex', gap: 4 }}>
              <button type="button" data-testid={`todo-confirm-${i}`} title="Confirm"
                onClick={() => onConfirm(i)}
                style={{ background: 'transparent', border: 'none', color: GREEN, cursor: 'pointer', padding: 2 }}>
                <svg {...COMMON} aria-label="confirm"><path d="M20 6L9 17l-5-5" /></svg>
              </button>
              <button type="button" data-testid={`todo-reject-${i}`} title="Send back"
                onClick={() => onReject(i)}
                style={{ background: 'transparent', border: 'none', color: RED, cursor: 'pointer', padding: 2 }}>
                <svg {...COMMON} aria-label="reject"><path d="M6 6l12 12M18 6L6 18" /></svg>
              </button>
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
