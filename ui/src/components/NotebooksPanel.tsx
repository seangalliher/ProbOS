/**
 * AD-523b: Crew Notebooks Browser.
 *
 * Floating panel showing Ship's Records notebook entries by author with
 * markdown body view + ship-wide search. Read-only for Captain (agents
 * write via [NOTEBOOK] blocks in the proactive loop).
 *
 * Backend: GET /api/records/documents, /api/records/documents/{path},
 * /api/records/search — all shipped under AD-434.
 */

import { useEffect } from 'react';
import { useStore } from '../store/useStore';
import { deptColor, classColor } from './knowledge/colors';

function formatTimestamp(iso: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch {
    return iso;
  }
}

export default function NotebooksPanel() {
  const open = useStore(s => s.notebooksOpen);
  const close = useStore(s => s.closeNotebooks);
  const authors = useStore(s => s.notebooksAuthors);
  const entries = useStore(s => s.notebooksEntries);
  const selectedAuthor = useStore(s => s.notebooksSelectedAuthor);
  const selectedEntry = useStore(s => s.notebooksSelectedEntry);
  const selectAuthor = useStore(s => s.selectNotebookAuthor);
  const selectEntry = useStore(s => s.selectNotebookEntry);
  const searchQuery = useStore(s => s.notebooksSearchQuery);
  const searchResults = useStore(s => s.notebooksSearchResults);
  const setQuery = useStore(s => s.setNotebookSearchQuery);
  const runSearch = useStore(s => s.runNotebookSearch);
  const clearSearch = useStore(s => s.clearNotebookSearch);
  const loading = useStore(s => s.notebooksLoading);
  const openNotebooks = useStore(s => s.openNotebooks);

  // Refresh on open
  useEffect(() => {
    if (open && authors.length === 0) {
      openNotebooks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const inSearchMode = searchResults !== null;

  // Department-grouped author list
  const grouped = new Map<string, typeof authors>();
  for (const a of authors) {
    const d = a.department || 'unassigned';
    if (!grouped.has(d)) grouped.set(d, []);
    grouped.get(d)!.push(a);
  }
  const deptOrder = Array.from(grouped.keys()).sort();

  return (
    <div
      data-testid="notebooks-panel"
      style={{
        position: 'fixed',
        top: 60, left: 60, right: 60, bottom: 60,
        zIndex: 30,
        background: 'rgba(10, 10, 18, 0.95)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(240, 176, 96, 0.25)',
        borderRadius: 8,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#c0bab0',
      }}
    >
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: '#f0b060', fontSize: 12, fontWeight: 700, letterSpacing: 1.5 }}>CREW NOTEBOOKS</span>
          <span style={{ color: '#6a6a7a', fontSize: 10 }}>Ship's Records — read-only</span>
        </div>
        <div
          onClick={close}
          data-testid="notebooks-close"
          style={{ cursor: 'pointer', padding: '4px 10px', color: '#8888a0', fontSize: 12 }}
        >
          ×
        </div>
      </div>

      {/* Search bar */}
      <div style={{ padding: '8px 18px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', gap: 8 }}>
        <input
          type="text"
          placeholder="Search all notebooks..."
          value={searchQuery}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') runSearch(); }}
          data-testid="notebooks-search-input"
          style={{
            flex: 1,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: '#c0bab0',
            padding: '6px 10px',
            borderRadius: 4,
            fontFamily: 'inherit',
            fontSize: 11,
          }}
        />
        {inSearchMode && (
          <button
            onClick={clearSearch}
            data-testid="notebooks-search-clear"
            style={{
              background: 'transparent', border: '1px solid rgba(255,255,255,0.12)',
              color: '#8888a0', fontSize: 10, padding: '6px 12px', cursor: 'pointer', borderRadius: 4,
            }}
          >
            CLEAR
          </button>
        )}
      </div>

      {/* Body — three columns */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Column 1: Authors */}
        <div data-testid="notebooks-authors" style={{ width: 220, borderRight: '1px solid rgba(255,255,255,0.06)', overflowY: 'auto' }}>
          {loading && authors.length === 0 && (
            <div style={{ padding: 16, color: '#6a6a7a', fontSize: 11 }}>Loading…</div>
          )}
          {!loading && authors.length === 0 && (
            <div style={{ padding: 16, color: '#6a6a7a', fontSize: 11 }}>No notebooks yet.</div>
          )}
          {deptOrder.map(dept => (
            <div key={dept}>
              <div style={{
                padding: '6px 14px', fontSize: 9, letterSpacing: 1.2,
                color: deptColor(dept), textTransform: 'uppercase',
                background: 'rgba(255,255,255,0.02)',
              }}>{dept}</div>
              {grouped.get(dept)!.map(a => {
                const isSelected = a.callsign === selectedAuthor && !inSearchMode;
                return (
                  <div
                    key={a.callsign}
                    onClick={() => selectAuthor(a.callsign)}
                    data-testid={`notebooks-author-${a.callsign}`}
                    style={{
                      padding: '6px 14px',
                      cursor: 'pointer',
                      background: isSelected ? 'rgba(240,176,96,0.10)' : 'transparent',
                      borderLeft: isSelected ? '2px solid #f0b060' : '2px solid transparent',
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      fontSize: 11,
                    }}
                  >
                    <span style={{ color: isSelected ? '#f0b060' : '#c0bab0' }}>{a.callsign}</span>
                    <span style={{ color: '#6a6a7a', fontSize: 10 }}>{a.entryCount}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Column 2: Entries OR Search Results */}
        <div data-testid="notebooks-entries" style={{ width: 320, borderRight: '1px solid rgba(255,255,255,0.06)', overflowY: 'auto' }}>
          {inSearchMode ? (
            <>
              <div style={{ padding: '8px 14px', fontSize: 10, color: '#6a6a7a' }}>
                {searchResults!.length} result{searchResults!.length === 1 ? '' : 's'}
              </div>
              {searchResults!.map(r => (
                <div
                  key={r.path}
                  onClick={() => selectEntry(r.path)}
                  data-testid={`notebooks-search-result-${r.path}`}
                  style={{
                    padding: '8px 14px', cursor: 'pointer',
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    fontSize: 11,
                  }}
                >
                  <div style={{ color: '#c0bab0', fontWeight: 600 }}>{r.frontmatter.topic || r.path.split('/').pop()}</div>
                  <div style={{ color: '#6a6a7a', fontSize: 10, marginTop: 2 }}>
                    {(r.frontmatter.author || '') + ' · score ' + r.score.toFixed(2)}
                  </div>
                  {r.snippet && (
                    <div style={{ color: '#8888a0', fontSize: 10, marginTop: 4, lineHeight: 1.4 }}>{r.snippet}…</div>
                  )}
                </div>
              ))}
            </>
          ) : selectedAuthor ? (
            entries.length === 0 ? (
              <div style={{ padding: 16, color: '#6a6a7a', fontSize: 11 }}>No entries.</div>
            ) : (
              entries.map(e => {
                const isSelected = selectedEntry?.path === e.path;
                return (
                  <div
                    key={e.path}
                    onClick={() => selectEntry(e.path)}
                    data-testid={`notebooks-entry-${e.path}`}
                    style={{
                      padding: '8px 14px', cursor: 'pointer',
                      borderBottom: '1px solid rgba(255,255,255,0.04)',
                      background: isSelected ? 'rgba(240,176,96,0.06)' : 'transparent',
                      fontSize: 11,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: isSelected ? '#f0b060' : '#c0bab0', fontWeight: 600 }}>
                        {e.frontmatter.topic || e.path.split('/').pop()}
                      </span>
                      {e.frontmatter.classification && (
                        <span style={{
                          fontSize: 9, padding: '1px 5px', borderRadius: 3,
                          background: 'rgba(255,255,255,0.04)',
                          color: classColor(e.frontmatter.classification),
                          fontWeight: 700, letterSpacing: 0.5,
                        }}>{e.frontmatter.classification.toUpperCase()}</span>
                      )}
                    </div>
                    <div style={{ color: '#6a6a7a', fontSize: 10, marginTop: 2 }}>
                      {formatTimestamp(e.frontmatter.updated || e.frontmatter.created || '')}
                    </div>
                  </div>
                );
              })
            )
          ) : (
            <div style={{ padding: 16, color: '#6a6a7a', fontSize: 11 }}>Select an author or search.</div>
          )}
        </div>

        {/* Column 3: Detail */}
        <div data-testid="notebooks-detail" style={{ flex: 1, overflowY: 'auto', padding: '14px 20px' }}>
          {selectedEntry ? (
            <>
              <div style={{ marginBottom: 14 }}>
                <div style={{ color: '#f0b060', fontSize: 14, fontWeight: 700, marginBottom: 4 }}>
                  {selectedEntry.frontmatter.topic || selectedEntry.path}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 10, color: '#8888a0' }}>
                  {selectedEntry.frontmatter.author && <span>author: <b style={{ color: '#c0bab0' }}>{selectedEntry.frontmatter.author}</b></span>}
                  {selectedEntry.frontmatter.department && <span>dept: <b style={{ color: deptColor(selectedEntry.frontmatter.department) }}>{selectedEntry.frontmatter.department}</b></span>}
                  {selectedEntry.frontmatter.classification && <span>class: <b style={{ color: classColor(selectedEntry.frontmatter.classification) }}>{selectedEntry.frontmatter.classification}</b></span>}
                  {selectedEntry.frontmatter.updated && <span>updated: <b style={{ color: '#c0bab0' }}>{formatTimestamp(selectedEntry.frontmatter.updated)}</b></span>}
                </div>
                {selectedEntry.frontmatter.tags && selectedEntry.frontmatter.tags.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {selectedEntry.frontmatter.tags.map(t => (
                      <span key={t} style={{
                        fontSize: 9, padding: '1px 6px', borderRadius: 3,
                        background: 'rgba(255,255,255,0.04)', color: '#8888a0',
                      }}>{t}</span>
                    ))}
                  </div>
                )}
              </div>
              <pre data-testid="notebooks-detail-body" style={{
                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11, lineHeight: 1.55, color: '#c0bab0',
                margin: 0,
              }}>{selectedEntry.content}</pre>
            </>
          ) : (
            <div style={{ color: '#6a6a7a', fontSize: 11 }}>Select an entry to read.</div>
          )}
        </div>
      </div>
    </div>
  );
}
