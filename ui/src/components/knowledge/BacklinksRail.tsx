/**
 * AD-562: BacklinksRail — right sidebar showing references / referenced_by / suggested.
 *
 * Visible only when knowledgeBrowserSelectedPath != null AND view === 'reader'.
 */
import { useStore } from '../../store/useStore';

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 9,
  color: '#8888a0',
  letterSpacing: 1.5,
  marginTop: 14,
  marginBottom: 6,
  textTransform: 'uppercase',
};

const linkStyle: React.CSSProperties = {
  display: 'block',
  padding: '3px 4px',
  fontSize: 11,
  color: '#cccce0',
  cursor: 'pointer',
  borderRadius: 3,
  wordBreak: 'break-all',
};

const emptyStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#666680',
  fontStyle: 'italic',
  padding: '3px 4px',
};

export default function BacklinksRail() {
  const data = useStore(s => s.knowledgeBrowserBacklinks);
  const selectEntry = useStore(s => s.selectKnowledgeBrowserEntry);

  if (!data) {
    return (
      <div data-testid="knowledge-backlinks-rail" style={{ padding: 10 }}>
        <div style={emptyStyle}>—</div>
      </div>
    );
  }

  const renderRefs = (refs: { target: string; raw_match: string }[]) => {
    if (!refs.length) return <div style={emptyStyle}>—</div>;
    return refs.map((r, i) => (
      <span
        key={`${r.target}-${i}`}
        data-testid="backlink-ref-target"
        style={linkStyle}
      >{r.raw_match}</span>
    ));
  };

  const renderPaths = (paths: string[], testid: string) => {
    if (!paths.length) return <div style={emptyStyle}>—</div>;
    return paths.map(p => (
      <span
        key={p}
        data-testid={testid}
        onClick={() => { void selectEntry(p); }}
        style={linkStyle}
      >{p}</span>
    ));
  };

  const renderSuggested = (s: { path: string; similarity: number }[]) => {
    if (!s.length) return <div style={emptyStyle}>—</div>;
    return s.map(item => (
      <span
        key={item.path}
        data-testid="backlink-suggested"
        onClick={() => { void selectEntry(item.path); }}
        style={linkStyle}
      >{item.path} <span style={{ color: '#666680' }}>({item.similarity.toFixed(2)})</span></span>
    ));
  };

  return (
    <div
      data-testid="knowledge-backlinks-rail"
      style={{ padding: 10, overflowY: 'auto', borderLeft: '1px solid rgba(240,176,96,0.10)' }}
    >
      <div style={sectionLabelStyle}>Referenced by</div>
      {renderPaths(data.referenced_by, 'backlink-incoming')}

      <div style={sectionLabelStyle}>References</div>
      {renderRefs(data.references)}

      <div style={sectionLabelStyle}>Suggested</div>
      {renderSuggested(data.suggested)}
    </div>
  );
}
