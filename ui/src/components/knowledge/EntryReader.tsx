/**
 * AD-562: EntryReader — minimal markdown renderer for selected record.
 *
 * Custom 30-LOC renderer (no marked / react-markdown dep).
 * Supports: # headings, ## sub-headings, **bold**, [[wikilinks]], fenced code blocks.
 */
import { useStore } from '../../store/useStore';
import { deptColor, classColor } from './colors';

interface RenderedNode {
  key: string;
  el: React.ReactNode;
}

function renderInline(line: string, lineKey: string, onWiki: (target: string) => void): React.ReactNode[] {
  // Split on [[wikilink]] first, then **bold** within plain segments.
  const out: React.ReactNode[] = [];
  const wikiRe = /\[\[([^\]\n]+)\]\]/g;
  let lastIdx = 0;
  let m: RegExpExecArray | null;
  let segIdx = 0;
  while ((m = wikiRe.exec(line)) !== null) {
    if (m.index > lastIdx) {
      out.push(<span key={`${lineKey}-t-${segIdx++}`}>{renderBold(line.slice(lastIdx, m.index), `${lineKey}-b-${segIdx}`)}</span>);
    }
    const target = m[1].trim();
    out.push(
      <span
        key={`${lineKey}-w-${segIdx++}`}
        data-testid="reader-wikilink"
        onClick={() => onWiki(target)}
        style={{ color: '#f0b060', cursor: 'pointer', textDecoration: 'underline' }}
      >{target}</span>
    );
    lastIdx = wikiRe.lastIndex;
  }
  if (lastIdx < line.length) {
    out.push(<span key={`${lineKey}-t-${segIdx++}`}>{renderBold(line.slice(lastIdx), `${lineKey}-b-${segIdx}`)}</span>);
  }
  return out;
}

function renderBold(text: string, baseKey: string): React.ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/);
  return parts.map((p, i) => i % 2 === 1
    ? <b key={`${baseKey}-b-${i}`} style={{ color: '#cccce0' }}>{p}</b>
    : <span key={`${baseKey}-s-${i}`}>{p}</span>);
}

function renderMarkdown(content: string, onWiki: (target: string) => void): RenderedNode[] {
  const lines = content.split('\n');
  const out: RenderedNode[] = [];
  let inCode = false;
  let codeBuf: string[] = [];
  let codeKey = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith('```')) {
      if (inCode) {
        out.push({
          key: `code-${codeKey++}`,
          el: <pre style={{
            background: 'rgba(10,10,18,0.6)', padding: 8, borderRadius: 4,
            fontSize: 11, color: '#a0c0e0', overflowX: 'auto', margin: '6px 0',
          }}>{codeBuf.join('\n')}</pre>,
        });
        codeBuf = [];
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) { codeBuf.push(line); continue; }
    if (line.startsWith('## ')) {
      out.push({ key: `l-${i}`, el: <h3 style={{ color: '#f0b060', fontSize: 13, margin: '10px 0 4px' }}>{line.slice(3)}</h3> });
    } else if (line.startsWith('# ')) {
      out.push({ key: `l-${i}`, el: <h2 style={{ color: '#f0b060', fontSize: 15, margin: '12px 0 6px' }}>{line.slice(2)}</h2> });
    } else if (line.trim() === '') {
      out.push({ key: `l-${i}`, el: <div style={{ height: 6 }} /> });
    } else {
      out.push({ key: `l-${i}`, el: <div style={{ fontSize: 12, lineHeight: 1.5, color: '#cccce0' }}>{renderInline(line, `i-${i}`, onWiki)}</div> });
    }
  }
  if (inCode && codeBuf.length) {
    out.push({
      key: `code-${codeKey++}`,
      el: <pre style={{
        background: 'rgba(10,10,18,0.6)', padding: 8, borderRadius: 4,
        fontSize: 11, color: '#a0c0e0', overflowX: 'auto', margin: '6px 0',
      }}>{codeBuf.join('\n')}</pre>,
    });
  }
  return out;
}

export default function EntryReader() {
  const doc = useStore(s => s.knowledgeBrowserSelectedDoc);
  const selectEntry = useStore(s => s.selectKnowledgeBrowserEntry);

  if (!doc) {
    return (
      <div data-testid="knowledge-reader-empty" style={{
        padding: 24, color: '#8888a0', fontSize: 12, textAlign: 'center',
      }}>
        No entry selected
      </div>
    );
  }

  const fm = doc.frontmatter || {};
  const handleWiki = (target: string) => { void selectEntry(target); };
  const contentEmpty = !(doc.content || '').trim();
  const rendered = contentEmpty ? [] : renderMarkdown(doc.content || '', handleWiki);

  return (
    <div data-testid="knowledge-reader" style={{ padding: 14, overflowY: 'auto', height: '100%' }}>
      <div style={{ marginBottom: 10, padding: '8px 10px', background: 'rgba(10,10,18,0.4)', borderRadius: 4, fontSize: 10, color: '#8888a0' }}>
        <div data-testid="reader-frontmatter">
          <span>path: <span style={{ color: '#cccce0' }}>{doc.path}</span></span>
          {fm.author && <span> · author: <b style={{ color: '#f0b060' }}>@{fm.author}</b></span>}
          {fm.department && <span> · dept: <b style={{ color: deptColor(fm.department) }}>{fm.department}</b></span>}
          {fm.classification && <span> · class: <b style={{ color: classColor(fm.classification) }}>{fm.classification}</b></span>}
          {fm.created && <span> · created: {fm.created}</span>}
          {fm.updated && <span> · updated: {fm.updated}</span>}
          {typeof fm.revision_count === 'number' && <span> · rev: {fm.revision_count}</span>}
        </div>
        {fm.tags && fm.tags.length > 0 && (
          <div data-testid="reader-tags" style={{ marginTop: 4 }}>
            tags: {fm.tags.map(t => <span key={t} style={{ color: '#88a4c8', marginRight: 6 }}>#{t}</span>)}
          </div>
        )}
      </div>
      {rendered.length === 0
        ? <div data-testid="reader-empty-content" style={{ color: '#666680', fontStyle: 'italic' }}>(empty)</div>
        : rendered.map(n => <div key={n.key}>{n.el}</div>)}
    </div>
  );
}
