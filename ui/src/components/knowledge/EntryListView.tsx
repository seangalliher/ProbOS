/**
 * AD-562: EntryListView — flat list of records browser entries.
 *
 * Capped at 200 visible rows + "more" footer (no virtualization library).
 * Click row → selectKnowledgeBrowserEntry(path) → switches view to reader.
 */
import { useStore } from '../../store/useStore';
import { deptColor, classColor } from './colors';

const MAX_VISIBLE = 200;

const rowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '6px 10px',
  fontSize: 11,
  borderBottom: '1px solid rgba(240,176,96,0.06)',
  cursor: 'pointer',
};

const chipStyle = (color: string): React.CSSProperties => ({
  width: 8, height: 8, borderRadius: 2, background: color, flexShrink: 0,
});

const badgeStyle = (color: string): React.CSSProperties => ({
  fontSize: 9,
  color,
  border: `1px solid ${color}`,
  padding: '0 4px',
  borderRadius: 8,
  letterSpacing: 1,
  textTransform: 'uppercase',
});

export default function EntryListView() {
  const entries = useStore(s => s.knowledgeBrowserEntries);
  const selectEntry = useStore(s => s.selectKnowledgeBrowserEntry);

  if (!entries.length) {
    return (
      <div data-testid="knowledge-list-empty" style={{
        padding: 24, color: '#8888a0', fontSize: 12, textAlign: 'center',
      }}>
        No entries match the current filters
      </div>
    );
  }

  const visible = entries.slice(0, MAX_VISIBLE);
  const moreCount = entries.length - visible.length;

  return (
    <div data-testid="knowledge-list-view" style={{ overflowY: 'auto', height: '100%' }}>
      {visible.map(e => {
        const fm = e.frontmatter || {};
        const dept = fm.department || '';
        const cls = fm.classification || 'ship';
        const author = fm.author || '';
        const created = (fm.created || '').slice(0, 10);
        return (
          <div
            key={e.path}
            data-testid={`knowledge-list-row-${e.path}`}
            onClick={() => { void selectEntry(e.path); }}
            style={rowStyle}
          >
            <span data-testid="row-dept-chip" style={chipStyle(deptColor(dept))} />
            <span data-testid="row-class-badge" style={badgeStyle(classColor(cls))}>{cls}</span>
            <span style={{ color: '#cccce0', flex: 1, wordBreak: 'break-all' }}>{e.path}</span>
            <span style={{ color: '#8888a0' }}>@{author}</span>
            <span style={{ color: '#666680' }}>{created}</span>
          </div>
        );
      })}
      {moreCount > 0 && (
        <div
          data-testid="knowledge-list-more"
          style={{ padding: '8px 10px', fontSize: 10, color: '#666680', textAlign: 'center' }}
        >
          … {moreCount} more
        </div>
      )}
    </div>
  );
}
