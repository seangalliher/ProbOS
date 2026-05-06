# AD-523b — Crew Notebooks Browser (HXI Panel)

**Status:** Build prompt for Wave 77.
**Issue:** #98 (parent umbrella AD-523).
**Depends on:** AD-434 (Ship's Records / RecordsStore — shipped), AD-513 (CrewRosterPanel pattern — shipped).
**Estimated tests:** +12 to +18 (window [+12, +18]). Vitest-only (HXI panel + store slice + types) — no pytest delta expected since all backend endpoints already exist.

## Problem

Ship's Records `data/ship-records/notebooks/` holds agent-authored knowledge (the roadmap entry at `docs/development/roadmap.md:2775` cites "168+ entries across 11 crew members as of 2026-03-29"). The HXI has zero surface for it — the Captain can see crew rosters, ward room, work boards, bills, but not the knowledge those crew members are writing. AD-562 is the long-term Obsidian-style replacement, but it's planned and large; AD-523b ships the lightweight tabular browser now so the institutional memory becomes visible to the Captain immediately.

The backend is fully built. Verify-first against HEAD `4479ec4`:

```
src/probos/knowledge/records_store.py:700  async def read_entry(self, path, reader_id, reader_department="") -> dict | None
src/probos/knowledge/records_store.py:730  async def list_entries(self, directory="", *, author="", status="", tags=None, classification="") -> list[dict]
src/probos/knowledge/records_store.py:818  async def search(self, query, scope="ship") -> list[dict]
src/probos/knowledge/records_store.py:854  async def get_stats(self) -> dict

src/probos/routers/records.py:18  GET /api/records/stats
src/probos/routers/records.py:25  GET /api/records/documents?directory=&author=&status=&classification=
src/probos/routers/records.py:46  GET /api/records/documents/{path:path}?reader=
src/probos/routers/records.py:84  GET /api/records/notebooks/{callsign}
src/probos/routers/records.py:120  GET /api/records/search?q=&scope=
```

Every notebook entry is markdown with YAML frontmatter (`author`, `department`, `topic`, `tags`, `classification`, `created`, `updated`). The classification access control at records_store.py:719-727 already enforces private/department/ship/fleet; the Captain reads with `reader=captain` (default in records.py:46) and gets the full corpus.

The gap is purely the HXI panel. The pattern is `CrewRosterPanel` (AD-513) — a floating panel with a toggle button in `App.tsx`, a Zustand store slice, and a list/detail layout.

## Solution Overview

One new floating panel `NotebooksPanel` with three views inside it:

1. **Author list view** — left column, callsigns grouped by department, entry count per callsign.
2. **Entry list view** — middle column once a callsign is selected, sorted newest-first, showing topic + classification badge + updated timestamp.
3. **Entry detail view** — right column once an entry is selected, rendering frontmatter metadata + markdown body.

Plus a search box that calls `/api/records/search?q=&scope=ship` and renders results inline (replacing the entry list view when active). All read-only.

Browse-by-department is achieved by department-grouping the author list (no separate "department" filter needed — Captain sees the natural department clusters via grouping headers).

The component fetches `/api/records/documents?directory=notebooks` once on open, groups client-side by path prefix (`notebooks/<callsign>/...`) to derive the author list, then fetches `/api/records/documents/{path}?reader=captain` lazily per entry click. Search calls `/api/records/search` and renders flat results.

No new backend endpoints, no new tests on the Python side. Frontend-only.

---

## Section 1 — Store Types

**File:** `ui/src/store/types.ts` — append a new types block at the bottom of the file (after the existing `CrewManifestEntry` block at line 549).

```ts
// AD-523b: Crew Notebooks Browser
export interface NotebookFrontmatter {
  author?: string;
  department?: string;
  topic?: string;
  tags?: string[];
  classification?: 'private' | 'department' | 'ship' | 'fleet';
  created?: string;
  updated?: string;
  status?: string;
}

export interface NotebookEntry {
  path: string;                     // e.g. "notebooks/atlas/topic-slug.md"
  frontmatter: NotebookFrontmatter;
}

export interface NotebookAuthor {
  callsign: string;                 // path segment after "notebooks/"
  department: string;               // most common department in this author's entries
  entryCount: number;
}

export interface NotebookDetail {
  path: string;
  frontmatter: NotebookFrontmatter;
  content: string;                  // markdown body
}

export interface NotebookSearchResult {
  path: string;
  frontmatter: NotebookFrontmatter;
  score: number;
  snippet: string;
}
```

---

## Section 2 — Store Slice

**File:** `ui/src/store/useStore.ts`.

### 2a. Import (add to existing types import at line 19, mirroring `CrewManifestEntry  // AD-513`)

```ts
===SEARCH===
  CrewManifestEntry,  // AD-513
===REPLACE===
  CrewManifestEntry,  // AD-513
  NotebookEntry,      // AD-523b
  NotebookAuthor,     // AD-523b
  NotebookDetail,     // AD-523b
  NotebookSearchResult,  // AD-523b
===END REPLACE===
```

### 2b. State shape (insert immediately after the existing `crewManifest:` field, around line 261)

```ts
===SEARCH===
  crewManifestOpen: boolean;
  crewManifest: CrewManifestEntry[] | null;
===REPLACE===
  crewManifestOpen: boolean;
  crewManifest: CrewManifestEntry[] | null;
  // AD-523b: Crew Notebooks Browser
  notebooksOpen: boolean;
  notebooksAuthors: NotebookAuthor[];
  notebooksEntries: NotebookEntry[];          // entries for currently selected author
  notebooksSelectedAuthor: string | null;     // callsign or null
  notebooksSelectedEntry: NotebookDetail | null;
  notebooksSearchQuery: string;
  notebooksSearchResults: NotebookSearchResult[] | null;  // null = not in search mode
  notebooksLoading: boolean;
===END REPLACE===
```

### 2c. Action signatures (insert after the existing `closeCrewManifest:` declaration, around line 304)

```ts
===SEARCH===
  openCrewManifest: () => void;
  closeCrewManifest: () => void;
===REPLACE===
  openCrewManifest: () => void;
  closeCrewManifest: () => void;
  // AD-523b
  openNotebooks: () => Promise<void>;
  closeNotebooks: () => void;
  selectNotebookAuthor: (callsign: string) => Promise<void>;
  selectNotebookEntry: (path: string) => Promise<void>;
  setNotebookSearchQuery: (q: string) => void;
  runNotebookSearch: () => Promise<void>;
  clearNotebookSearch: () => void;
===END REPLACE===
```

### 2d. Initial state (insert after the existing `crewManifest: null,` around line 477)

```ts
===SEARCH===
  crewManifestOpen: false,
  crewManifest: null,
===REPLACE===
  crewManifestOpen: false,
  crewManifest: null,
  // AD-523b
  notebooksOpen: false,
  notebooksAuthors: [],
  notebooksEntries: [],
  notebooksSelectedAuthor: null,
  notebooksSelectedEntry: null,
  notebooksSearchQuery: '',
  notebooksSearchResults: null,
  notebooksLoading: false,
===END REPLACE===
```

### 2e. Action implementations (insert after the existing `closeCrewManifest:` action, around line 542)

```ts
===SEARCH===
  closeCrewManifest: () => set({ crewManifestOpen: false }),
===REPLACE===
  closeCrewManifest: () => set({ crewManifestOpen: false }),
  // AD-523b: Crew Notebooks Browser
  openNotebooks: async () => {
    set({ notebooksOpen: true, notebooksLoading: true });
    try {
      const res = await fetch('/api/records/documents?directory=notebooks');
      if (!res.ok) {
        set({ notebooksLoading: false });
        return;
      }
      const data = await res.json();
      const docs: NotebookEntry[] = (data.documents || []).map((d: any) => ({
        path: d.path || '',
        frontmatter: (d.frontmatter || {}) as any,
      }));
      // Group by author callsign (path = "notebooks/<callsign>/<file>.md")
      const groups = new Map<string, { count: number; depts: Map<string, number> }>();
      for (const e of docs) {
        const parts = e.path.split('/');
        if (parts.length < 3 || parts[0] !== 'notebooks') continue;
        const cs = parts[1];
        if (!groups.has(cs)) groups.set(cs, { count: 0, depts: new Map() });
        const g = groups.get(cs)!;
        g.count += 1;
        const dept = e.frontmatter.department || '';
        if (dept) g.depts.set(dept, (g.depts.get(dept) || 0) + 1);
      }
      const authors: NotebookAuthor[] = Array.from(groups.entries()).map(([cs, g]) => {
        let topDept = '';
        let topCount = 0;
        for (const [d, c] of g.depts.entries()) {
          if (c > topCount) { topDept = d; topCount = c; }
        }
        return { callsign: cs, department: topDept, entryCount: g.count };
      }).sort((a, b) => a.callsign.localeCompare(b.callsign));
      set({ notebooksAuthors: authors, notebooksLoading: false });
    } catch {
      set({ notebooksLoading: false });
    }
  },
  closeNotebooks: () => set({
    notebooksOpen: false,
    notebooksSelectedAuthor: null,
    notebooksSelectedEntry: null,
    notebooksEntries: [],
    notebooksSearchQuery: '',
    notebooksSearchResults: null,
  }),
  selectNotebookAuthor: async (callsign: string) => {
    set({
      notebooksSelectedAuthor: callsign,
      notebooksSelectedEntry: null,
      notebooksLoading: true,
      notebooksSearchResults: null,
    });
    try {
      const res = await fetch(`/api/records/documents?directory=notebooks/${encodeURIComponent(callsign)}`);
      if (!res.ok) {
        set({ notebooksEntries: [], notebooksLoading: false });
        return;
      }
      const data = await res.json();
      const entries: NotebookEntry[] = (data.documents || []).map((d: any) => ({
        path: d.path || '',
        frontmatter: (d.frontmatter || {}) as any,
      }));
      // Sort newest first by frontmatter.updated || created
      entries.sort((a, b) => {
        const ta = a.frontmatter.updated || a.frontmatter.created || '';
        const tb = b.frontmatter.updated || b.frontmatter.created || '';
        return tb.localeCompare(ta);
      });
      set({ notebooksEntries: entries, notebooksLoading: false });
    } catch {
      set({ notebooksEntries: [], notebooksLoading: false });
    }
  },
  selectNotebookEntry: async (path: string) => {
    set({ notebooksLoading: true });
    try {
      const res = await fetch(`/api/records/documents/${path.split('/').map(encodeURIComponent).join('/')}?reader=captain`);
      if (!res.ok) {
        set({ notebooksSelectedEntry: null, notebooksLoading: false });
        return;
      }
      const data = await res.json();
      set({
        notebooksSelectedEntry: {
          path: data.path || path,
          frontmatter: (data.frontmatter || {}) as any,
          content: data.content || '',
        },
        notebooksLoading: false,
      });
    } catch {
      set({ notebooksSelectedEntry: null, notebooksLoading: false });
    }
  },
  setNotebookSearchQuery: (q: string) => set({ notebooksSearchQuery: q }),
  runNotebookSearch: async () => {
    const q = get().notebooksSearchQuery.trim();
    if (!q) {
      set({ notebooksSearchResults: null });
      return;
    }
    set({ notebooksLoading: true });
    try {
      const res = await fetch(`/api/records/search?q=${encodeURIComponent(q)}&scope=ship`);
      if (!res.ok) {
        set({ notebooksSearchResults: [], notebooksLoading: false });
        return;
      }
      const data = await res.json();
      const all: NotebookSearchResult[] = (data.results || []).map((r: any) => ({
        path: r.path || '',
        frontmatter: (r.frontmatter || {}) as any,
        score: r.score || 0,
        snippet: r.snippet || '',
      }));
      // Filter to notebooks/* only — search runs over all records
      const filtered = all.filter(r => r.path.startsWith('notebooks/'));
      set({ notebooksSearchResults: filtered, notebooksLoading: false });
    } catch {
      set({ notebooksSearchResults: [], notebooksLoading: false });
    }
  },
  clearNotebookSearch: () => set({ notebooksSearchQuery: '', notebooksSearchResults: null }),
===END REPLACE===
```

---

## Section 3 — Panel Component

**New file:** `ui/src/components/NotebooksPanel.tsx`. Mirrors the floating-panel pattern from `ui/src/components/CrewRosterPanel.tsx` (AD-513) — fixed-position container, dim background, close glyph, three-column layout.

```tsx
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

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

const CLASS_COLORS: Record<string, string> = {
  private: '#7060a8',
  department: '#88a4c8',
  ship: '#f0b060',
  fleet: '#e0c070',
};

function deptColor(dept: string): string {
  return DEPT_COLORS[(dept || '').toLowerCase()] || '#8888a0';
}

function classColor(cls: string): string {
  return CLASS_COLORS[(cls || '').toLowerCase()] || '#8888a0';
}

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
```

---

## Section 4 — App Wiring + Toggle

**File:** `ui/src/App.tsx`.

### 4a. Import (after `import CrewRosterPanel from './components/CrewRosterPanel';` at line 19)

```tsx
===SEARCH===
import CrewRosterPanel from './components/CrewRosterPanel';

function CrewRosterToggle() {
===REPLACE===
import CrewRosterPanel from './components/CrewRosterPanel';
import NotebooksPanel from './components/NotebooksPanel';

function NotebooksToggle() {
  const open = useStore(s => s.notebooksOpen);
  const openNotebooks = useStore(s => s.openNotebooks);

  if (open) return null;

  return (
    <div
      onClick={() => openNotebooks()}
      data-testid="notebooks-toggle"
      style={{
        position: 'fixed',
        top: 12, left: 200,
        zIndex: 25,
        padding: '6px 12px',
        background: 'rgba(10, 10, 18, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid rgba(240, 176, 96, 0.15)',
        borderRadius: 6,
        cursor: 'pointer',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.5,
        fontFamily: "'JetBrains Mono', monospace",
        color: '#8888a0',
        userSelect: 'none' as const,
      }}
    >
      NOTEBOOKS
    </div>
  );
}

function CrewRosterToggle() {
===END REPLACE===
```

### 4b. Mount in App tree (immediately after `<CrewRosterToggle />`, around line 135)

```tsx
===SEARCH===
      <CrewRosterPanel />
      <CrewRosterToggle />
      <WelcomeOverlay />
===REPLACE===
      <CrewRosterPanel />
      <CrewRosterToggle />
      <NotebooksPanel />
      <NotebooksToggle />
      <WelcomeOverlay />
===END REPLACE===
```

---

## Section 5 — Vitest Component Tests

**New file:** `ui/src/__tests__/NotebooksPanel.test.tsx`. Vitest + React Testing Library. Mirrors the existing `WardRoomPanel.test.tsx` mocking pattern.

Required test cases:

1. **`renders nothing when notebooksOpen is false`** — store default state. Asserts `queryByTestId('notebooks-panel')` is null.
2. **`renders panel and fetches authors on open`** — `vi.spyOn(global, 'fetch')` returning a `documents` payload with three notebooks across two callsigns. Calls `openNotebooks()`. Asserts the panel appears; asserts both callsigns appear under their derived department headers; asserts entry count badges match.
3. **`selecting an author fetches that author's entries sorted newest first`** — second fetch mock for `directory=notebooks/<callsign>`. Asserts the entries column populates; the topmost entry has the most recent `updated` timestamp.
4. **`selecting an entry fetches detail and renders body + frontmatter`** — third fetch mock for `documents/{path}`. Asserts the detail column shows the topic title, the author/dept/classification metadata row, and the markdown body in `notebooks-detail-body`.
5. **`classification badge uses the correct color per level`** — render an entry with `classification: 'private'` and assert the inline style color matches the violet from `CLASS_COLORS.private`.
6. **`search runs against /api/records/search and filters to notebooks/* paths`** — fourth fetch mock returning 2 notebooks/* hits + 1 captains-log/ hit. Asserts only the 2 notebook hits render in the entries column. Asserts the result count text is "2 results".
7. **`clearing search returns to author-selected entries view`** — runs search then clicks the clear button. Asserts the previously selected author's entries reappear.
8. **`closing the panel resets selection state`** — open, select author, select entry, close. Re-open and assert no entry is selected, no author is selected, search is empty.

Test scaffolding pattern (do not paste verbatim — adapt from `WardRoomPanel.test.tsx`):

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import NotebooksPanel from '../components/NotebooksPanel';
import { useStore } from '../store/useStore';

describe('NotebooksPanel (AD-523b)', () => {
  beforeEach(() => {
    useStore.setState({
      notebooksOpen: false,
      notebooksAuthors: [],
      notebooksEntries: [],
      notebooksSelectedAuthor: null,
      notebooksSelectedEntry: null,
      notebooksSearchQuery: '',
      notebooksSearchResults: null,
      notebooksLoading: false,
    });
    vi.restoreAllMocks();
  });
  // ... per-test fetch stubs ...
});
```

---

## What This Does NOT Change

- **No backend changes.** All endpoints exist. Do not add `/api/records/notebooks` (no callsign) — the existing `documents?directory=notebooks` is sufficient and groups happen client-side.
- **No new pytest tests.** Backend is verify-only.
- **No write surface.** Captain is read-only; agents continue writing via `[NOTEBOOK]` blocks in `proactive.py`. Do not add a "create entry" button or `POST` call.
- **No version history UI.** `GET /api/records/history/{path}` exists but is out of scope — defer to AD-562.
- **No 3D graph view, no backlinks, no quality overlays.** Those are AD-562's surface; AD-523b is the lightweight tabular browser AD-562 will eventually replace.
- **No Captain's Log / Duty Logs / Reports / Operations / Manuals views.** Those would be AD-523c work, which is closed-as-superseded by AD-562 in this wave.
- **No classification override UI.** The Captain reads with `reader=captain` and gets unrestricted access; no role-switching control.
- **No HXI Welcome Overlay change, no main viewer change, no canvas change.**
- **No Pydantic config change, no new EventType, no runtime attribute, no startup wiring.**

---

## Tracking Updates

1. **`PROGRESS.md`** — append a one-line entry under the Wave 77 banner reflecting AD-523b complete + AD-523a verify-only + AD-523c closed-as-superseded by AD-562.
2. **`docs/development/roadmap.md:2774-2776`** — flip AD-523b status from planned to **complete**, add a one-line "Implemented in Wave 77" note. Flip AD-523c status from planned to **closed (superseded by AD-562)**, leaving the existing supersession note intact. Tag the umbrella AD-523 entry as `*(Complete — all sub-ADs resolved, OSS, Issue #98)*`.
3. **No `DECISIONS.md` change.** AD-523/523a/523b/523c all already have entries in `decisions-era-4-evolution.md:1690-1696` and the supersession entry at :2337/2350. Append-only log; do not rewrite.

---

## Acceptance Criteria

1. `git status` shows: 1 new file (`ui/src/components/NotebooksPanel.tsx`), 1 new test file (`ui/src/__tests__/NotebooksPanel.test.tsx`), 3 modified files (`ui/src/store/types.ts`, `ui/src/store/useStore.ts`, `ui/src/App.tsx`), plus the two tracking-only edits (`PROGRESS.md`, `docs/development/roadmap.md`).
2. **No source changes** under `src/probos/` (Python). No new pytest test files. No edits to `routers/records.py` or `knowledge/records_store.py`.
3. **Vitest gate** `cd ui && npx vitest run` passes including the 8 new tests in `NotebooksPanel.test.tsx`.
4. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` reports **11498 collected** (Δ = 0 vs baseline). HXI changes do not change Python collection.
5. The HXI runs (`/system` start path unchanged); opening the NOTEBOOKS toggle shows the panel; closing it returns to canvas.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: HXI emoji prohibition (no emoji in any new component; classification labels and stroke-only badges per HXI Design Principle #3); SOLID-S (NotebooksPanel does only browse/search, not write); cloud-ready storage rule (no DB access from frontend); type annotations on all exported interfaces (Section 1); no fire-and-forget tasks; no hardcoded secrets or paths.

---

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  4479ec47b30cb8eb3a19b7ef0ba6caaefe940515

# Backend endpoints exist:
grep -n "async def" src/probos/knowledge/records_store.py | Select-String "list_entries|read_entry|search|get_stats"
  248:    async def write_notebook(
  700:    async def read_entry(
  730:    async def list_entries(
  818:    async def search(self, query: str, scope: str = "ship") -> list[dict]:
  854:    async def get_stats(self) -> dict:

grep -n "@router\." src/probos/routers/records.py
  18:@router.get("/stats")
  25:@router.get("/documents")
  46:@router.get("/documents/{path:path}")
  61:@router.post("/captains-log")
  72:@router.get("/captains-log")
  82:@router.get("/notebooks/{callsign}")
  94:@router.post("/notebooks/{callsign}")
  120:@router.get("/search")
  131:@router.get("/history/{path:path}")

# Floating-panel pattern source:
ui/src/components/CrewRosterPanel.tsx:1-50 — AD-513 pattern this file mirrors.
ui/src/store/useStore.ts:260-261 — crewManifestOpen + crewManifest state shape.
ui/src/store/useStore.ts:303-304 — openCrewManifest / closeCrewManifest signatures.
ui/src/store/useStore.ts:476-477 — initial state default block.
ui/src/store/useStore.ts:523-542 — async fetch pattern.
ui/src/App.tsx:19 — import CrewRosterPanel.
ui/src/App.tsx:22-50 — CrewRosterToggle pattern.
ui/src/App.tsx:133-135 — mount order in App tree.

# Notebooks dir layout (verified empty in dev workspace; production has 168+ entries per roadmap.md:2775):
data/ship-records/notebooks/  exists, structure is notebooks/<callsign>/<topic-slug>.md

# AD-523a confirmed shipped via BF-080:
docs/development/roadmap.md:7356 — "BF-080 ... Closed ... Also satisfies AD-523a."
docs/development/roadmap.md:2774 — "AD-523a: DM Channel Viewer — ✅ COMPLETE (via BF-080)."
ui/src/store/useStore.ts — selectDmChannel action; dm-detail wardRoomView state.

# AD-523c confirmed superseded by AD-562:
decisions-era-4-evolution.md:2337 — "AD-562 supersedes and absorbs this."
decisions-era-4-evolution.md:2350 — "AD-562 supersedes AD-523c | AD-523c was a simpler browsing view. AD-562 is the full-featured replacement."
docs/development/roadmap.md:4237 — "AD-523c (Ship's Records Dashboard — AD-562 supersedes/absorbs this planned feature)"
```

Every concrete claim above maps to a grep hit.

---

## Review History

- **Pass 1 (initial draft):** Verified backend complete; HXI panel pattern matches CrewRosterPanel; section structure mirrors WardRoomPanel three-column layout; tests follow WardRoomPanel.test.tsx mocking style; no NATS/Bills/runtime entanglement.
- **Pass 2 (verify-first sweep):** Confirmed all 5 records_store methods, all 9 router endpoints, all 7 store anchor lines, all 3 App.tsx anchors. No phantom APIs in build prompt — every method/endpoint cited exists at HEAD `4479ec4`. Confirmed `ui/src/__tests__/` is the canonical Vitest location (8 existing tests there; pattern proven).
- **Pass 3 (anti-pattern scan):** No defensive `getattr` (TypeScript file). No mutable defaults. No `obj._private` chains. No bare `except`. No emoji in Section 3 (per HXI Design Principle #3 — close glyph is `×` Unicode multiplication sign, classification badges are stroke-style boxed labels). No `_method` access from outside owning module. No fire-and-forget tasks (`openNotebooks` is awaited; fetches are awaited inside async actions). No hardcoded credentials or absolute paths. Backend boundary respected — frontend reads via REST only.
- **Pass 4 (Wave-10 reframe + commercial-leak audit):** Reframe is justified per Captain rule (1 buildable + 2 verify-only siblings; not a deferral — 523a is already shipped, 523c is officially absorbed). Test delta sized within +12/+18 window (8 vitest + ~5 buffer for happy-path + edge variations the Builder may add). Commercial leak: AD-523/523b are tagged OSS in roadmap.md; no pricing/revenue/customer language in this prompt. AD-562 reference is to a PLANNED OSS+commercial AD; the public roadmap entry at roadmap.md:4225 already carries the `*(planned, OSS+commercial)*` tag — no new commercial detail introduced here. No `*(Commercial)*` deferrals filed.
