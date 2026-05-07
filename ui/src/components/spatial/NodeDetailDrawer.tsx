/**
 * AD-520: Spatial Knowledge Explorer — node detail drawer.
 *
 * Right-edge inspection drawer rendered inside SpatialExplorerPanel when
 * spatialSelectedNode !== null.
 */
import { useStore } from '../../store/useStore';

const AGENT_KEYS = ['department', 'rank', 'post', 'trust', 'on_watch'];
const EDGE_KEYS = ['relation', 'weight', 'confidence', 'source', 'target'];
const DEPT_KEYS = ['accent_color'];

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

export default function NodeDetailDrawer() {
  const sel = useStore(s => s.spatialSelectedNode);
  const setSelected = useStore(s => s.setSpatialSelectedNode);

  if (!sel) return null;

  const keys = sel.kind === 'agent' ? AGENT_KEYS : sel.kind === 'edge' ? EDGE_KEYS : DEPT_KEYS;
  const truncatedId = sel.id.length > 18 ? sel.id.slice(0, 15) + '…' : sel.id;

  return (
    <div
      data-testid="node-detail-drawer"
      style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 280,
        background: 'rgba(10,10,18,0.92)',
        borderLeft: '1px solid rgba(240,176,96,0.15)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        padding: '12px 14px',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#cccce0',
        fontSize: 11,
        overflow: 'auto',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ color: '#f0b060', fontWeight: 700, letterSpacing: 1.5, fontSize: 10 }}>
          {sel.kind.toUpperCase()} · {truncatedId}
        </div>
        <div
          data-testid="node-detail-close"
          onClick={() => setSelected(null)}
          style={{ cursor: 'pointer', color: '#8888a0', fontSize: 14, lineHeight: 1, padding: '0 4px' }}
          role="button"
          aria-label="Close detail"
        >×</div>
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          {keys.map(k => (
            <tr key={k} data-testid={`detail-row-${k}`}>
              <td style={{ color: '#666680', padding: '3px 6px 3px 0', verticalAlign: 'top', whiteSpace: 'nowrap' }}>{k}</td>
              <td style={{ color: '#cccce0', padding: '3px 0', wordBreak: 'break-word' }}>
                {formatValue(sel.payload[k])}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
