/** BF-978 (#1809): a build's review issues and suggestions, under its chat message and in its failure card.
 *
 * The texts come from a model, so each item renders as a React text node: no markdown and no HTML. A value that is not
 * an array shows nothing; items that are not non-empty strings are skipped. At most MAX_REVIEW_ITEMS items show per
 * list, each cut at MAX_REVIEW_CHARS code points with a trailing ellipsis; "and <k> more" counts the string items not
 * shown. A list with no items renders nothing, not even its title.
 */
import type { CSSProperties } from 'react';

const MAX_REVIEW_ITEMS = 10;
const MAX_REVIEW_CHARS = 500;

const SECTION_STYLE: CSSProperties = {
  padding: '6px 12px',
  borderRadius: 6,
  background: 'rgba(136, 164, 200, 0.06)',
  border: '1px solid rgba(136, 164, 200, 0.12)',
  fontSize: 11,
  color: '#a0a8b8',
  marginBottom: 8,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
};
const TITLE_STYLE: CSSProperties = { color: '#f0d0a0', marginBottom: 4, fontSize: 11 };
const LIST_STYLE: CSSProperties = { margin: 0, paddingLeft: 18 };
const MORE_STYLE: CSSProperties = { marginTop: 2, color: '#8888a0' };

interface ReviewList {
  shown: string[];
  more: number;
}

function clip(text: string): string {
  const points = Array.from(text);
  if (points.length <= MAX_REVIEW_CHARS) return text;
  return points.slice(0, MAX_REVIEW_CHARS).join('') + '\u2026';
}

function reviewList(value: unknown): ReviewList {
  if (!Array.isArray(value)) return { shown: [], more: 0 };
  const strings = value.filter((item): item is string => typeof item === 'string' && item.length > 0);
  return {
    shown: strings.slice(0, MAX_REVIEW_ITEMS).map(clip),
    more: Math.max(0, strings.length - MAX_REVIEW_ITEMS),
  };
}

function ReviewSection({ title, list }: { title: string; list: ReviewList }) {
  if (list.shown.length === 0) return null;
  return (
    <div style={SECTION_STYLE}>
      <div style={TITLE_STYLE}>{title}</div>
      <ul aria-label={title} style={LIST_STYLE}>
        {list.shown.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
      {list.more > 0 && <div style={MORE_STYLE}>{`and ${list.more} more`}</div>}
    </div>
  );
}

export function BuildReviewLists({ issues, suggestions }: { issues?: unknown; suggestions?: unknown }) {
  return (
    <>
      <ReviewSection title="Review issues" list={reviewList(issues)} />
      <ReviewSection title="Review suggestions" list={reviewList(suggestions)} />
    </>
  );
}
