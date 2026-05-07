/**
 * AD-562: TimelineView — pure-SVG dept-stacked histogram of entry creation by day.
 */
import { useStore } from '../../store/useStore';
import { deptColor } from './colors';
import { useState } from 'react';

const VIEWBOX_W = 100;
const VIEWBOX_H = 100;
const PAD_X = 4;
const PAD_Y = 4;

export default function TimelineView() {
  const tl = useStore(s => s.knowledgeBrowserTimeline);
  const [hover, setHover] = useState<number | null>(null);

  if (!tl || tl.total === 0) {
    return (
      <div data-testid="knowledge-timeline-empty" style={{
        padding: 24, color: '#8888a0', fontSize: 12, textAlign: 'center',
      }}>
        No timeline data
      </div>
    );
  }

  const buckets = tl.buckets;
  const n = buckets.length;
  const maxCount = Math.max(...buckets.map(b => b.count), 1);
  const barW = (VIEWBOX_W - 2 * PAD_X) / Math.max(n, 1);

  return (
    <div data-testid="knowledge-timeline-view" style={{ padding: 10, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: 10, color: '#8888a0', marginBottom: 6 }}>
        Total: {tl.total} entries across {n} day-bucket{n === 1 ? '' : 's'}
      </div>
      <svg
        viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
        style={{ width: '100%', height: '100%', flex: 1 }}
        preserveAspectRatio="none"
      >
        {buckets.map((b, i) => {
          const x = PAD_X + i * barW;
          const totalH = ((VIEWBOX_H - 2 * PAD_Y) * b.count) / maxCount;
          let yOffset = VIEWBOX_H - PAD_Y;
          const segs: React.ReactNode[] = [];
          const depts = Object.entries(b.by_department);
          for (const [dept, c] of depts) {
            const segH = (totalH * c) / b.count;
            yOffset -= segH;
            segs.push(
              <rect
                key={`${b.date}-${dept}`}
                data-testid={`timeline-bar-${b.date}-${dept}`}
                x={x}
                y={yOffset}
                width={Math.max(barW - 0.5, 0.5)}
                height={segH}
                fill={deptColor(dept)}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            );
          }
          return <g key={b.date} data-testid={`timeline-bar-${b.date}`}>{segs}</g>;
        })}
      </svg>
      {hover !== null && buckets[hover] && (
        <div data-testid="timeline-tooltip" style={{
          fontSize: 10, color: '#cccce0', padding: '4px 6px',
          background: 'rgba(10,10,18,0.85)', borderRadius: 3, marginTop: 4,
        }}>
          {buckets[hover].date}: {buckets[hover].count} entries — {Object.entries(buckets[hover].by_department).map(([d, c]) => `${d}:${c}`).join(', ')}
        </div>
      )}
    </div>
  );
}
