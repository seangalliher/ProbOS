/**
 * AD-562: FilterRail — left sidebar filters for KnowledgeBrowserPanel.
 */
import { useStore } from '../../store/useStore';

const DIRECTORIES = [
  'captains-log', 'notebooks', 'duty-logs',
  'convergence-reports', 'procedures', 'manuals',
];

const CLASSIFICATIONS = ['private', 'department', 'ship', 'fleet'];

const labelStyle: React.CSSProperties = {
  fontSize: 9,
  color: '#8888a0',
  letterSpacing: 1.5,
  marginTop: 12,
  marginBottom: 6,
  textTransform: 'uppercase',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '4px 6px',
  background: 'rgba(10,10,18,0.6)',
  border: '1px solid rgba(240,176,96,0.15)',
  borderRadius: 3,
  color: '#cccce0',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: 11,
  boxSizing: 'border-box',
};

function chipStyle(active: boolean): React.CSSProperties {
  return {
    display: 'inline-block',
    padding: '2px 8px',
    margin: '2px 4px 2px 0',
    border: `1px solid ${active ? '#f0b060' : 'rgba(240,176,96,0.15)'}`,
    borderRadius: 10,
    fontSize: 10,
    color: active ? '#f0b060' : '#8888a0',
    cursor: 'pointer',
    userSelect: 'none',
    background: active ? 'rgba(240,176,96,0.08)' : 'transparent',
  };
}

export default function FilterRail() {
  const filters = useStore(s => s.knowledgeBrowserFilters);
  const setFilters = useStore(s => s.setKnowledgeBrowserFilters);

  return (
    <div data-testid="knowledge-filter-rail" style={{ padding: 10, overflowY: 'auto' }}>
      <div style={labelStyle}>Author</div>
      <input
        data-testid="filter-author"
        value={filters.author}
        placeholder="callsign"
        onChange={e => setFilters({ author: e.target.value })}
        style={inputStyle}
      />

      <div style={labelStyle}>Directory</div>
      <div>
        {DIRECTORIES.map(d => (
          <span
            key={d}
            data-testid={`filter-dir-${d}`}
            onClick={() => setFilters({ directory: filters.directory === d ? '' : d })}
            style={chipStyle(filters.directory === d)}
          >{d}</span>
        ))}
      </div>

      <div style={labelStyle}>Classification</div>
      <div>
        {CLASSIFICATIONS.map(c => (
          <span
            key={c}
            data-testid={`filter-class-${c}`}
            onClick={() => setFilters({ classification: filters.classification === c ? '' : c })}
            style={chipStyle(filters.classification === c)}
          >{c}</span>
        ))}
      </div>

      <div style={labelStyle}>Department</div>
      <input
        data-testid="filter-department"
        value={filters.department}
        placeholder="science|engineering|..."
        onChange={e => setFilters({ department: e.target.value })}
        style={inputStyle}
      />

      <div style={labelStyle}>Tags (csv)</div>
      <input
        data-testid="filter-tags"
        value={filters.tags}
        placeholder="trust,routing"
        onChange={e => setFilters({ tags: e.target.value })}
        style={inputStyle}
      />

      <div style={labelStyle}>Since</div>
      <input
        data-testid="filter-since"
        value={filters.since}
        placeholder="YYYY-MM-DD"
        onChange={e => setFilters({ since: e.target.value })}
        style={inputStyle}
      />

      <div style={labelStyle}>Until</div>
      <input
        data-testid="filter-until"
        value={filters.until}
        placeholder="YYYY-MM-DD"
        onChange={e => setFilters({ until: e.target.value })}
        style={inputStyle}
      />
    </div>
  );
}
