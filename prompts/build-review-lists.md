# HXI build review lists: a build's review issues and suggestions show under its message and in its failure card

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-17
**Status:** ready to build. Every anchor was read on commit `00cc6201f199` (tree `5c147a65f4e7`), the head of #1824. `git log --oneline 5275d008..HEAD -- ui/src/store ui/src/components/IntentSurface.tsx src/probos/routers/build.py src/probos/cognitive/builder.py` prints nothing, so these four paths have no commits since the issue's base. **Owning issue:** #1809 (BF-978, already allocated). Commits say `Refs #1809.` This contract is saved as `prompts/build-review-lists.md`.
**Dependencies:** none.
**Estimated tests:** 8 new vitest cases in a new file, `ui/src/__tests__/BuildReview.bf978.test.tsx`: 6 `built` cases and 2 controls. No existing test is removed or changed.

## 1. Problem

- `src/probos/routers/build.py:501-518`: BUILD_SUCCESS carries `review_issues` (`:509`) and `review_suggestions` (`:510`). The message (`:511-517`) adds only the suggestion count (`:516`).
- `src/probos/cognitive/builder.py:176-178` and `:200-202`: the failure report carries `review_result`, `review_issues` and `review_suggestions`, and `to_dict` sends them. `build.py:533-537` sends it as `report`.
- `ui/src/store/useStore.ts:3799-3807`: `build_success` passes only `data.message` to `addChatMessage`. `:3809-3821`: `build_failure` passes the report as `{ buildFailureReport: report }`.
- `ui/src/store/types.ts:195-216`: `BuildFailureReport` has `review_issues: string[]` (`:210`) and no `review_suggestions`. `rg 'review_issues|review_suggestions' ui/src` finds only `types.ts:210`.
- `ui/src/components/IntentSurface.tsx:1479-1600`: the failure card renders the category, the title, the failed tests, the raw error and the resolution buttons. It shows no review content.

The Captain therefore sees "Review suggestions: <n>" and none of the text, and never sees the review's issues.

## 2. Solution overview

The success lists travel as a new optional `buildReview` field on the chat message and on `addChatMessage`'s meta, next to `buildFailureReport`. The failure lists stay in the report, and its type gains an optional `review_suggestions`. A new component, `ui/src/components/chat/BuildReviewLists.tsx`, takes two `unknown` values, checks their shape, applies the limits and renders two titled lists. IntentSurface renders it under a message that has `buildReview` and inside the failure card. The message text is unchanged.

Heavier designs, rejected:
- Appending the lists to the message text: that text goes through ReactMarkdown (`IntentSurface.tsx:1146-1162`), so model text would be read as markdown.
- Normalising the lists in the store: this would need a second shape check for the failure report. One check at render serves both paths.
- Keeping the lists in `localStorage`: the stored chat history keeps `id`, `role`, `text` and `timestamp` (`useStore.ts:3195-3197`), and the other metadata (`buildFailureReport`, `buildProposal`) is not stored either. Out of scope.

## 3. Decisions

- **D1 (shape).**
  - `types.ts` adds `export interface BuildReviewNotes { issues?: string[]; suggestions?: string[]; }`, `ChatMessage.buildReview?: BuildReviewNotes` and `BuildFailureReport.review_suggestions?: string[]`.
  - `review_suggestions` is optional because a report from a server without it must still type-check its consumers. `rg BuildFailureReport ui/src` finds no literal of the type (section 10), so making it required would also compile. Optional states the runtime truth.
  - The `build_success` handler casts the payload fields as the failure branch casts `data.report` (`useStore.ts:3811`). It always attaches `buildReview` when it adds the message.
- **D2 (absent or malformed values).** The component treats each value as `unknown`:
  - a value that is not an array shows nothing;
  - items that are not non-empty strings are skipped before counting;
  - a list with no items left renders nothing, not even its title;
  - when both lists are empty, the component renders nothing.
  - A server that sends `null` and a report without `review_suggestions` both fall under the first rule.
- **D3 (where they render).**
  - **Success:** directly after the message bubble (`IntentSurface.tsx:1164`), before the self-mod block (`:1166`), wrapped in `maxWidth: '80%'` as the failure card is (`:1481`).
  - **Failure:** inside the card, after the failed-tests block (`:1545`) and before the raw error (`:1547`).
  - **Titles:** "Review issues" and "Review suggestions". Each list is a `ul` whose `aria-label` is its title.
- **D4 (plain text).**
  - Each item is the only child of an `li`, as a JSX text expression, so React sets it as a text node.
  - The lists are siblings of the ReactMarkdown subtree, not inside it.
  - `rg dangerouslySetInnerHTML ui/src` finds only `components/artifacts/ArtifactViewer.tsx`, so no HTML path reaches the lists.
  - ReactMarkdown is given `components` only (`:1147-1160`); this contract does not change it.
- **D5 (limits).**
  - At most 10 items per list.
  - Each item is cut at 500 code points (`Array.from(text)`, not UTF-16 units), so a cut never leaves a lone surrogate.
  - A cut item ends with U+2026 (`'\u2026'` in source); an item of exactly 500 code points is not cut.
  - When more than 10 string items remain, a line `and <k> more` follows, where k is the number of string items not shown.
  - These limits apply on both paths, because both render through `BuildReviewLists`.
- **D6 (persisted state, config, flags).** None.
  - No Python file changes, so the config reference, the facade baseline and `config/profiles` cannot move.
  - `useSettingsStore` is not touched.
  - `buildReview` is not added to the `localStorage` serialisation (`useStore.ts:3195-3197`).
- **D7 (type-check).** `npx tsc -b` covers the change. `npm run build` (CI's `ui-tests` job) adds `vite build`, which this change does not configure.

## 4. Milestones and commits

The Builder is `claude-sonnet-5.5`, with at most about 150 tool calls per milestone.
- It searches first, then reads the range.
- It runs no tests; the orchestrator runs every check in section 8.
- It stages only the named files and never uses `git add -A`.
- Every SEARCH must match exactly once at its turn. If one does not, stop and report.
- The working tree may check these files out with CRLF (`git ls-files --eol` shows `i/lf w/crlf` for the edited files in the drafting worktree). Match the anchors by line, keep each file's line endings, and write the new files with LF.

- **M1:** P1-1.
  - Subject: `Build review lists: tests for a build's review issues and suggestions in the HXI (expected failures until the build)`
  - Body: `Adds eight cases that drive the store's event handler with the IntentSurface shell open. Six fail on the base at their own assert and are marked as expected failures until the build; two controls pass on the base.` Then `Refs #1809.` and the trailer.
- **M2:** P2-1 to P2-12.
  - Subject: `HXI shows a build's review issues and suggestions as plain text under its message and in its failure card`
  - Body: `A build_success message keeps the event's review issues and suggestions as metadata, and the failure card reads both from the report. A new component renders each list as text nodes, only when it has items, with at most ten items of at most 500 code points each, then a count of the rest. The test marker becomes a no-op.` Then `Refs #1809.` and the trailer.
- **M3:** P3-1 and P3-2. The orchestrator runs the ledger generator and appends the campaign bullet.
  - Subject: `Trackers for the HXI build review lists`
  - Body: `PROGRESS.md and DECISIONS.md entries.` Then `Refs #1809.` and the trailer.

I checked the three subjects and bodies by eye: they contain none of the issue's closing words or the substrings `fix`, `close` and `resolv`, and no `AD-` or `BF-` token.

## 5. Behaviour table (after M2)

| Event | Base | After M2 |
|---|---|---|
| `build_success` with 2 issues and 3 suggestions | the message only | the message, then "Review issues" (2 items) and "Review suggestions" (3 items) |
| `build_success` with empty lists, `null` or absent fields | the message only | the message only |
| `build_failure` with a report holding both lists | the card without review content | the card with both lists, after the failed tests |
| `build_failure` with a report that has no `review_suggestions` | the card | the card; the issues list only if it has items |
| 12 items | -- | 10 items, then `and 2 more` |
| an item over 500 code points | -- | its first 500 code points, then U+2026 |
| an item containing `<img ...>` or `**x**` | -- | the literal characters |

## 6. The contract

### 6.1 M1: new test file

**P1-1** (`ui/src/__tests__/BuildReview.bf978.test.tsx`: new file)
```tsx
/** BF-978 (#1809): a build's review issues and suggestions show under its chat message and in its failure card.
 *
 * Each case opens the IntentSurface shell, sends one `build_success` or `build_failure` frame to the store's real
 * `handleEvent` inside `act`, and reads the DOM at once: no timer and no wait. The cases the base does not satisfy are
 * `built`, which is `it.fails` until M2 sets it to `it`; with BF978_RUNXFAIL=1 they run as ordinary cases, so each can be
 * seen to stop at its own assertion. Only names that exist on the base are imported. `globalThis.fetch` answers `{}` in
 * every case and is restored after it. Each title names its id and the contract's mutation rows it kills.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';
import type { WSEvent } from '../store/types';

// M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
const built = process.env.BF978_RUNXFAIL === '1' ? it : it.fails;

const GENERATION = 'c'.repeat(32);
const SUCCESS_TEXT = 'Build complete in the review case';
const FAILURE_TEXT = 'Tests failed in the review case';
const realFetch = globalThis.fetch;
let nextSequence = 0;

function frame(type: string, data: Record<string, unknown>): WSEvent {
  return { type, data, timestamp: Date.now() / 1000, stream: { generation: GENERATION, sequence: nextSequence++ } };
}

function send(type: string, data: Record<string, unknown>): void {
  act(() => {
    useStore.getState().handleEvent(frame(type, data));
  });
}

function success(issues: unknown, suggestions: unknown): Record<string, unknown> {
  return {
    build_id: 'b978', branch: 'builder/b978', commit: 'abc1234', files_written: ['src/x.py'], tests_passed: true,
    test_result: '', review: 'reviewed', review_issues: issues, review_suggestions: suggestions, message: SUCCESS_TEXT,
  };
}

function failure(review: Record<string, unknown>): Record<string, unknown> {
  return {
    build_id: 'b978',
    message: `Build failed: ${FAILURE_TEXT}`,
    report: {
      build_id: 'b978', ad_number: 0, title: '', branch_name: 'builder/b978', files_written: [], files_modified: [],
      failure_category: 'test_failure', failure_summary: FAILURE_TEXT, raw_error: '', failed_tests: [],
      error_locations: [], fix_attempts: 0, fix_descriptions: [], review_result: '', resolution_options: [], ...review,
    },
  };
}

function shown(text: string): boolean {
  return screen.queryAllByText(text).length > 0;
}

/** The texts of the list whose aria-label is `name`; the list must be shown. */
function itemsOf(name: string): string[] {
  const list = document.querySelector(`ul[aria-label="${name}"]`);
  expect(list, `the "${name}" list is shown`).not.toBeNull();
  return Array.from(list!.querySelectorAll('li')).map((li) => li.textContent ?? '');
}

beforeEach(() => {
  nextSequence = 0;
  globalThis.fetch = vi.fn().mockImplementation(
    () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  ) as unknown as typeof fetch;
  useStore.setState({
    chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map(),
    liveGeneration: null, liveSequence: 0, liveRepairEpoch: 0,
  });
  render(<IntentSurface />);
  const pill = screen.queryByText(/Ask ProbOS/);
  const clickable = pill ? pill.closest('div') : null;
  if (clickable) fireEvent.click(clickable);
  send('state_snapshot', { agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0 });
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
  useStore.setState({ chatHistory: [] });
  vi.restoreAllMocks();
});

describe('BF-978: review lists under a build_success message', () => {
  built('S1 [W1 W2 W3]: 2 issues and 3 suggestions show all five texts under the message', () => {
    send('build_success', success(['issue one', 'issue two'], ['suggestion one', 'suggestion two', 'suggestion three']));
    expect(shown(SUCCESS_TEXT)).toBe(true);
    expect(itemsOf('Review issues')).toEqual(['issue one', 'issue two']);
    expect(itemsOf('Review suggestions')).toEqual(['suggestion one', 'suggestion two', 'suggestion three']);
    expect(shown('Review issues')).toBe(true);
    expect(shown('Review suggestions')).toBe(true);
  });

  it('S2 [W13] (control): empty lists show the message and neither list', () => {
    send('build_success', success([], []));
    expect(shown(SUCCESS_TEXT)).toBe(true);
    expect(shown('Review issues')).toBe(false);
    expect(shown('Review suggestions')).toBe(false);
    expect(document.querySelector('ul[aria-label="Review issues"], ul[aria-label="Review suggestions"]')).toBeNull();
  });

  built('S3 [W12]: markup in a suggestion shows as its literal characters', () => {
    const img = '<img src=x onerror="globalThis.__bf978 = 1">';
    const md = 'use **bold** and [a link](http://example.invalid)';
    send('build_success', success([], [img, md]));
    expect(itemsOf('Review suggestions')).toEqual([img, md]);
    const list = document.querySelector('ul[aria-label="Review suggestions"]');
    expect(list!.querySelector('img, a, strong')).toBeNull();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });

  built('S4 [W6 W7]: 12 issues show the first 10, then "and 2 more"', () => {
    const twelve = Array.from({ length: 12 }, (_, i) => `issue ${String(i + 1).padStart(2, '0')}`);
    send('build_success', success(twelve, []));
    expect(itemsOf('Review issues')).toEqual(twelve.slice(0, 10));
    expect(shown('and 2 more')).toBe(true);
  });

  built('S5 [W8 W9]: an item is cut at 500 code points with an ellipsis; 500 exactly is kept whole', () => {
    const long = 'a'.repeat(600);
    const astral = 'b'.repeat(499) + '\u{1F600}' + 'c'.repeat(9);
    const edge = 'd'.repeat(500);
    send('build_success', success([long, astral, edge], []));
    expect(itemsOf('Review issues')).toEqual([
      'a'.repeat(500) + '\u2026',
      'b'.repeat(499) + '\u{1F600}' + '\u2026',
      edge,
    ]);
  });

  built('S6 [W10 W11 W13]: null shows no list; non-string and empty items are skipped', () => {
    send('build_success', success(null, [97531, null, '', 'the one real suggestion']));
    expect(itemsOf('Review suggestions')).toEqual(['the one real suggestion']);
    expect(shown('Review issues')).toBe(false);
  });
});

describe('BF-978: review lists in the build failure card', () => {
  built('F1 [W4 W5]: a report with 2 issues and 3 suggestions shows all five texts in the card', () => {
    send('build_failure', failure({
      review_issues: ['failure issue one', 'failure issue two'],
      review_suggestions: ['failure suggestion one', 'failure suggestion two', 'failure suggestion three'],
    }));
    expect(shown('Build Failed')).toBe(true);
    expect(itemsOf('Review issues')).toEqual(['failure issue one', 'failure issue two']);
    expect(itemsOf('Review suggestions')).toEqual([
      'failure suggestion one', 'failure suggestion two', 'failure suggestion three',
    ]);
  });

  it('F2 [W10 W13] (control): no issues and no review_suggestions field show neither list', () => {
    send('build_failure', failure({ review_issues: [] }));
    expect(shown('Build Failed')).toBe(true);
    expect(shown('Review issues')).toBe(false);
    expect(shown('Review suggestions')).toBe(false);
  });
});
```

### 6.2 M2: types, store, component, IntentSurface and the marker

**P2-1** (`ui/src/store/types.ts`: the report's suggestions)
SEARCH:
```ts
  review_result: string;
  review_issues: string[];
```
REPLACE:
```ts
  review_result: string;
  review_issues: string[];
  review_suggestions?: string[];  // BF-978 (#1809): optional; a report without it shows no suggestions
```

**P2-2** (`ui/src/store/types.ts`: the success lists' type)
SEARCH:
```ts
export interface TransporterChunkStatus {
```
REPLACE:
```ts
/** BF-978 (#1809): a build's review lists as the build_success event sent them; BuildReviewLists checks their shape. */
export interface BuildReviewNotes {
  issues?: string[];
  suggestions?: string[];
}

export interface TransporterChunkStatus {
```

**P2-3** (`ui/src/store/types.ts`: the chat message field)
SEARCH:
```ts
  buildFailureReport?: BuildFailureReport;
  architectProposal?: ArchitectProposalView;
}
```
REPLACE:
```ts
  buildFailureReport?: BuildFailureReport;
  buildReview?: BuildReviewNotes;  // BF-978 (#1809): set on a build_success message
  architectProposal?: ArchitectProposalView;
}
```

**P2-4** (`ui/src/store/useStore.ts`: the type import)
SEARCH:
```ts
  BuildProposal, BuildFailureReport, ArchitectProposalView, BuildQueueItem, MissionControlTask,
```
REPLACE:
```ts
  BuildProposal, BuildFailureReport, BuildReviewNotes, ArchitectProposalView, BuildQueueItem, MissionControlTask,
```

**P2-5** (same file: the `addChatMessage` meta type)
SEARCH:
```ts
  addChatMessage: (role: 'user' | 'agent' | 'system', text: string, meta?: { selfModProposal?: SelfModProposal; buildProposal?: BuildProposal; buildFailureReport?: BuildFailureReport; architectProposal?: ArchitectProposalView; agent_id?: string; callsign?: string }) => void;
```
REPLACE:
```ts
  addChatMessage: (role: 'user' | 'agent' | 'system', text: string, meta?: { selfModProposal?: SelfModProposal; buildProposal?: BuildProposal; buildFailureReport?: BuildFailureReport; buildReview?: BuildReviewNotes; architectProposal?: ArchitectProposalView; agent_id?: string; callsign?: string }) => void;
```

**P2-6** (same file: the meta spread)
SEARCH:
```ts
      ...(meta?.buildFailureReport ? { buildFailureReport: meta.buildFailureReport } : {}),
```
REPLACE:
```ts
      ...(meta?.buildFailureReport ? { buildFailureReport: meta.buildFailureReport } : {}),
      ...(meta?.buildReview ? { buildReview: meta.buildReview } : {}),
```

**P2-7** (same file: the `build_success` case)
SEARCH:
```ts
      case 'build_success': {
        soundEngine.playSelfModSpawn();
        set({ buildProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }
```
REPLACE:
```ts
      case 'build_success': {
        soundEngine.playSelfModSpawn();
        set({ buildProgress: null });
        const msg = (data.message || '') as string;
        if (msg) {
          // BF-978 (#1809): the review lists ride as metadata; BuildReviewLists checks their shape when it renders.
          get().addChatMessage('system', msg, { buildReview: { issues: data.review_issues as string[] | undefined, suggestions: data.review_suggestions as string[] | undefined } });
        }
        break;
      }
```

**P2-8** (`ui/src/components/chat/BuildReviewLists.tsx`: new file)
```tsx
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
```

**P2-9** (`ui/src/components/IntentSurface.tsx`: the import)
SEARCH:
```tsx
import { approveQueuedBuild } from '../store/buildQueueApprove';
```
REPLACE:
```tsx
import { approveQueuedBuild } from '../store/buildQueueApprove';
import { BuildReviewLists } from './chat/BuildReviewLists';
```

**P2-10** (same file: under a build_success message)
SEARCH:
```tsx
                    {/* Self-mod approval buttons */}
                    {msg.selfModProposal && msg.selfModProposal.status === 'proposed' && (
```
REPLACE:
```tsx
                    {/* Build review lists under a build_success message (BF-978) */}
                    {msg.buildReview && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        <BuildReviewLists issues={msg.buildReview.issues} suggestions={msg.buildReview.suggestions} />
                      </div>
                    )}

                    {/* Self-mod approval buttons */}
                    {msg.selfModProposal && msg.selfModProposal.status === 'proposed' && (
```

**P2-11** (same file: inside the failure card)
SEARCH:
```tsx
                        {/* Collapsible raw error */}
                        {msg.buildFailureReport.raw_error && (
```
REPLACE:
```tsx
                        {/* Review lists from the failure report (BF-978) */}
                        <BuildReviewLists
                          issues={msg.buildFailureReport.review_issues}
                          suggestions={msg.buildFailureReport.review_suggestions}
                        />

                        {/* Collapsible raw error */}
                        {msg.buildFailureReport.raw_error && (
```

**P2-12** (`ui/src/__tests__/BuildReview.bf978.test.tsx`: the marker becomes a no-op)
SEARCH:
```tsx
// M1: each built case fails on the base at its own assert; M2 replaces this marker with a no-op.
const built = process.env.BF978_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```tsx
// The built cases failed on the base at their own assert and pass now; the marker is a no-op.
const built = it;
```

M2 is P2-1 to P2-12.

### 6.3 M3: trackers

**P3-1** (`PROGRESS.md`: entry under the title; the title line occurs once)
SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**The HXI shows a build's review issues and suggestions under its message and in its failure card (2026-11-17), #1809.**
- **Base.** The build_success event carried the review's issues and suggestions, and the failure report carried both lists, but the HXI showed the message text (with a suggestion count) and the failure summary, and none of the review text.
- **Change.** A build_success message keeps both lists as message metadata; the failure card reads them from the report. A new component, `BuildReviewLists`, renders "Review issues" and "Review suggestions", each when it has items, as React text nodes: at most 10 items, each cut at 500 code points with an ellipsis, then "and <k> more". A value that is not an array shows nothing; items that are not non-empty strings are skipped. The message text and the server are unchanged. `ui/src/__tests__/BuildReview.bf978.test.tsx` adds eight cases.
- **Limits.** The lists are not kept across a reload: the stored chat history keeps id, role, text and timestamp. The Builder's readings lost on the Transporter path are #1769's review point. Contract `prompts/build-review-lists.md`; decisions in DECISIONS.md.
```

**P3-2** (`DECISIONS.md`: entry directly before the DM camera hook entry, found by its heading text, which occurs once)
SEARCH:
```markdown
### The DM camera hook bounds every step with one deadline, and the DM route's timing line survives a raised send (2026-11-16, #1808)
```
REPLACE:
```markdown
### The HXI renders a build's review lists as plain text under the message and in the failure card (2026-11-17, #1809)

- *Scope.* UI only: `ui/src/store/types.ts` (`BuildReviewNotes`, `ChatMessage.buildReview`, an optional `BuildFailureReport.review_suggestions`), `ui/src/store/useStore.ts` (the `build_success` case and `addChatMessage`'s meta), `ui/src/components/IntentSurface.tsx` (two render sites), a new `ui/src/components/chat/BuildReviewLists.tsx` and a new test file. No server, config, event or persisted-state change. Contract `prompts/build-review-lists.md`.
- *D1 (shape).* The success lists travel as an optional `buildReview` on the chat message, beside `buildFailureReport`; the failure lists stay in the report. The component checks the shape at render, so both paths share one check.
- *D2 (plain text).* Each item is a React text node in an `li`, outside the markdown renderer that draws the message text. Rejected: markdown for the items, because the text comes from a model.
- *D3 (limits).* 10 items; 500 code points, not UTF-16 units, so a cut never splits a surrogate pair; U+2026 after a cut; "and <k> more" counts the string items not shown. A non-array shows nothing; non-string and empty items are skipped.
- *Residual.* The lists are not restored after a reload. *Reversal.* Revert the commits of #1809; nothing is persisted.

### The DM camera hook bounds every step with one deadline, and the DM route's timing line survives a raised send (2026-11-16, #1808)
```

The orchestrator appends a `*Mutation campaign of record.*` bullet to the new entry after section 8.3.

## 7. Builder: may and may not

- **May:** apply the pairs in order; run `git diff --check` and `git diff --stat`; commit as section 4 says.
- **May not:**
  - edit any file not named here, in particular any Python file, `useSettingsStore` or the `localStorage` serialisation at `useStore.ts:3195-3197`;
  - change the message text, the ReactMarkdown block or any other card block;
  - add `skip`, `todo` or a retry;
  - run tests;
  - reword a SEARCH anchor.

## 8. Gates (the orchestrator runs them)

Run every UI command from `ui/`, with the shared `node_modules` junctioned in.

### 8.1 Base counts, on the merged head before M1

`npx vitest run BuildQueueApprove.bf937 useStore.test IntentSurface. AgentProfilePanel.threadKeyed App.bf710 ProfileChatTab.ad1291`. These are vitest path-substring filters; `IntentSurface.` selects the eleven `ui/src/__tests__/IntentSurface.*.test.tsx` files. Record each file's count. I did not run it.

### 8.2 Focused checks

- **After M1, default mode:** `npx vitest run BuildReview.bf978` should print `8 passed`: 6 built cases failing as expected, plus 2 controls.
- **After M1, with the marker off:** `BF978_RUNXFAIL=1` (in PowerShell, `$env:BF978_RUNXFAIL='1'`, then remove it afterwards), same command. It should print `6 failed | 2 passed`.
  - Each of S1, S3, S4, S5, S6 and F1 must stop at the `expect(list, ...)` inside `itemsOf`.
  - Before that point, S1 has already passed `shown(SUCCESS_TEXT)` and F1 has already passed `shown('Build Failed')`.
  - S2 and F2 pass.
  - A failure at an import, at `render` or in `beforeEach` is a contract defect: stop and report.
- **After M2:**
  - `npx tsc -b`: exit 0, no output.
  - `npx vitest run BuildReview.bf978` prints `8 passed`, with and without `BF978_RUNXFAIL=1`.
  - The 8.1 command: each file at its base count, all passed.
- **Python side:** no Python file changes.
  - Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check` with `PROBOS_EMBEDDINGS=local`; both pass.
  - After M3 and the ledger regeneration, run `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -n 0 -p no:randomly -q`.

| File | Why it is in the set | Expected edit |
|---|---|---|
| `ui/src/__tests__/BuildQueueApprove.bf937.test.tsx` | renders IntentSurface; drives `handleEvent` with build frames (`:160-176`) | none |
| `ui/src/__tests__/useStore.test.ts` | `addChatMessage` cases (`:191-237`), including a meta object (`:223-236`) | none |
| `ui/src/__tests__/IntentSurface.*.test.tsx` (11 files) | render IntentSurface; `selfModApprove` passes a meta object (`:44`) | none |
| `ui/src/__tests__/AgentProfilePanel.threadKeyed.test.tsx`, `App.bf710.test.tsx` | name IntentSurface (import or mock) | none |
| `ui/src/components/profile/__tests__/ProfileChatTab.ad1291.e2e.test.tsx` | sets `chatHistory` | none |

### 8.3 Mutation campaign (one row at a time, restored before the next; win32)

- **Selector:** `npx vitest run BuildReview.bf978` from `ui/`, on the M2 head.
- **Campaign of record:** record the tree id and the sha256 of `types.ts`, `useStore.ts`, `IntentSurface.tsx`, `BuildReviewLists.tsx` and the test file. Rerun only the rows whose file differs.
- **Originals:** each is a whole stripped line that occurs once in its file at the M2 head.
- **Killers:** listed as "at least". W10 and W11 make the component throw during render. React reports such an error through `act`, and vitest may also report it as an unhandled error. The row is KILLED when its named cases fail; record any other case that failed.

| Row | File | Original | Mutant | Expected killers (at least) |
|---|---|---|---|---|
| W1 (metadata dropped in build_success) | useStore | `get().addChatMessage('system', msg, { buildReview: { issues: data.review_issues as string[] \| undefined, suggestions: data.review_suggestions as string[] \| undefined } });` | `get().addChatMessage('system', msg);` | S1, S3, S4, S5, S6 |
| W2 (meta not copied to the message) | useStore | `...(meta?.buildReview ? { buildReview: meta.buildReview } : {}),` | `...({}),` | S1, S3, S4, S5, S6 |
| W3 (success site not rendered) | IntentSurface | `{msg.buildReview && (` | `{false && (` | S1, S3, S4, S5, S6 |
| W4 (failure issues not read) | IntentSurface | `issues={msg.buildFailureReport.review_issues}` | `issues={[]}` | F1 |
| W5 (failure suggestions not read) | IntentSurface | `suggestions={msg.buildFailureReport.review_suggestions}` | `suggestions={[]}` | F1 |
| W6 (no item cap) | BuildReviewLists | `const MAX_REVIEW_ITEMS = 10;` | `const MAX_REVIEW_ITEMS = 1000;` | S4 |
| W7 (no "and k more") | BuildReviewLists | `{list.more > 0 && <div style={MORE_STYLE}>{`and ${list.more} more`}</div>}` | `{null}` | S4 |
| W8 (cut by UTF-16 units) | BuildReviewLists | `const points = Array.from(text);` | `const points = text.split('');` | S5 |
| W9 (an item of exactly 500 is cut) | BuildReviewLists | `if (points.length <= MAX_REVIEW_CHARS) return text;` | `if (points.length < MAX_REVIEW_CHARS) return text;` | S5 |
| W10 (no array check) | BuildReviewLists | `if (!Array.isArray(value)) return { shown: [], more: 0 };` | `if (false) return { shown: [], more: 0 };` | S6, F2 |
| W11 (non-strings kept) | BuildReviewLists | `const strings = value.filter((item): item is string => typeof item === 'string' && item.length > 0);` | `const strings = value as string[];` | S6 |
| W12 (item rendered as HTML) | BuildReviewLists | `<li key={i}>{text}</li>` | `<li key={i} dangerouslySetInnerHTML={{ __html: text }} />` | S3 |
| W13 (empty list still titled) | BuildReviewLists | `if (list.shown.length === 0) return null;` | `if (false) return null;` | S2, S6, F2 |
| R0 (the base product) | all four | `types.ts`, `useStore.ts`, `IntentSurface.tsx` restored from the base; `BuildReviewLists.tsx` removed; marker kept as `it` | -- | S1, S3, S4, S5, S6, F1 fail; S2, F2 pass |

Record each row as KILLED (by the named case, or name the case that fired), SURVIVED or INVALID. Any survivor stops the slice for Architect triage.

### 8.4 Broad gate

Run it once, on the committed head after the last repair: `scripts/run_test_gate.py --label build-review-lists --receipt logs/gates/build-review-lists.receipt.json`. CI's `ui-tests` job runs `npm ci`, `npm run test` and `npm run build`.

## 9. Diff Reviewer: properties to verify

1. **Files.** The diff touches only:
   - `ui/src/store/types.ts`, `ui/src/store/useStore.ts`, `ui/src/components/IntentSurface.tsx`;
   - the new `ui/src/components/chat/BuildReviewLists.tsx` and `ui/src/__tests__/BuildReview.bf978.test.tsx`;
   - `PROGRESS.md`, `DECISIONS.md` and the ledger files the orchestrator regenerates.
2. **The consumer that must accept the change: IntentSurface's chat thread** (`IntentSurface.tsx:1108` onward).
   - A message without `buildReview` renders as before.
   - A failure card for a report without `review_suggestions`, or with `review_issues` that is not an array, renders without error.
   - The message text still goes through ReactMarkdown unchanged.
3. **Plain text.** Every review item reaches the DOM as the text child of an `li`, with no markdown component, no `dangerouslySetInnerHTML` and no attribute built from the item.
4. **Limits.**
   - At most 10 `li` per list.
   - Each item has at most 500 code points plus one U+2026, and an item of 500 code points or fewer is unchanged.
   - `and <k> more` appears exactly when more than 10 string items exist, and k counts them.
5. **Empty lists.** A list with no string items renders neither its title nor its `ul`.
6. **Other `addChatMessage` callers.** Every other caller compiles unchanged: the meta field is optional.
7. **Persistence.** The `localStorage` serialisation (`useStore.ts:3195-3197`) is unchanged.
8. **Marker.** After M2, `built` is `it`, and no `skip`, `todo` or `fails` remains in the new file.

## 10. Verified Against Codebase (2026-11-17, commit `00cc6201f199`, tree `5c147a65f4e7`)

```
git log --oneline 5275d008..HEAD -- ui/src/store ui/src/components/IntentSurface.tsx src/probos/routers/build.py src/probos/cognitive/builder.py
  (no output)
src/probos/routers/build.py
  501: rt.emit_event(EventType.BUILD_SUCCESS, {   509: "review_issues": ...   510: "review_suggestions": ...
  516: + (f", Review suggestions: {len(result.review_suggestions)}" ...)   536: "report": report.to_dict(),
src/probos/cognitive/builder.py
  177: review_issues: list[str] ...   178: review_suggestions: list[str] ...   201-202: both in to_dict
ui/src/store/useStore.ts
  14: BuildProposal, BuildFailureReport, ArchitectProposalView, BuildQueueItem, MissionControlTask,
  726: addChatMessage: (role: ..., meta?: { ... buildFailureReport?: BuildFailureReport; architectProposal?: ... }) => void;
  3187: ...(meta?.buildFailureReport ? { buildFailureReport: meta.buildFailureReport } : {}),
  3195-3197: const serializable = updated.map(m => ({ id: m.id, role: m.role, text: m.text, timestamp: m.timestamp, }));
  3222: handleEvent: (event: WSEvent) => {    3252: generation check for non-snapshot frames
  3799: case 'build_success': {   3804: get().addChatMessage('system', msg);
  3811: const report = data.report as BuildFailureReport | undefined;   3814: { buildFailureReport: report }
ui/src/store/types.ts
  209: review_result: string;  210: review_issues: string[];  211: resolution_options: Array<{
  218: export interface TransporterChunkStatus {   336: buildFailureReport?: BuildFailureReport;  337: architectProposal?: ...
ui/src/components/IntentSurface.tsx
  5: import ReactMarkdown from 'react-markdown';   33: import { approveQueuedBuild } from '../store/buildQueueApprove';
  1108: {chatHistory.slice(-30).map((msg) => (   1146-1162: role !== 'user' -> <ReactMarkdown components={...}>{msg.text}
  1166: {/* Self-mod approval buttons */}   1480: {msg.buildFailureReport && (   1498: Build Failed
  1547: {/* Collapsible raw error */}   1548: {msg.buildFailureReport.raw_error && (
ui/src/audio/soundEngine.ts
  141: if (!this.ctx || !this.masterGain || !this._connected) return;   (playSelfModSpawn is a no-op without init)
ui/src/__tests__/BuildQueueApprove.bf937.test.tsx
  160-162: frame() with stream { generation, sequence }   173: handleEvent(frame('state_snapshot', ...))
git show ddadd931:ui/src/__tests__/BuildQueueApprove.bf937.test.tsx | grep "RUNXFAIL ==="
  17: const built = process.env.BF937_RUNXFAIL === '1' ? it : it.fails;
ui/src/__tests__/IntentSurface.selfModApprove.test.tsx
  25-31: openShell() clicks the "Ask ProbOS" pill   41-45: render, open, addChatMessage with meta
DECISIONS.md:1766 heading of the #1808 entry (once);  PROGRESS.md "# ProbOS Progress" (once)
ui/package.json: "react": "^19.0.0", "react-markdown": "^10.1.0", "@testing-library/react": "^16.3.2"
```

## Absence Verified (2026-11-17)

- **Claim:** no UI code reads `review_issues` or `review_suggestions`.
  - Run: `rg 'review_issues|review_suggestions' ui/src`
  - Found: `types.ts:210`.
  - Holds.
- **Claim:** no literal of `BuildFailureReport` exists in UI code, tests or mocks.
  - Run: `rg 'BuildFailureReport|buildFailureReport' ui`
  - Found: `types.ts:195,336`; `IntentSurface.tsx:7,1480-1592`; `useStore.ts:14,726,3187,3811,3814`. All are types, reads or the cast.
  - Holds.
- **Claim:** no file under `ui/` outside the three source files names `build_success` or `build_failure`.
  - Run: `rg 'build_success|build_failure|buildFailureReport|review_issues|review_suggestions' ui`
  - Found: `useStore.ts`, `types.ts`, `IntentSurface.tsx`.
  - Holds (this tree has no `ui/node_modules`).
- **Claim:** one Python test reads an edited UI file, and it pins only what this change leaves as it is; no other Python test reads `types.ts`, `useStore.ts` or `IntentSurface.tsx`.
  - Run: `rg '"ui"\s*/\s*"src"|ui/src/components|IntentSurface\.tsx|useStore\.ts|store/types' tests`, then `rg -n -g '*.py' 'types\.ts|useStore|IntentSurface|"store"\s*/' tests` for a path built in pieces. The second run finds only the reader below and `test_wave_close_precheck.py:57-58,79-80`, a stub `useStore.ts` and a mock of it that the test writes into a temporary repository.
  - Found:
    - `test_ad1164_continue_or_ask.py:1082-1090` (the one reader: it reads `types.ts` and pins only the `CapabilityApprovalView` declaration, which this change does not touch);
    - `test_wave_close_precheck.py:57` (writes a stub into a temporary repo);
    - `test_ad476_specialized_builders.py:46,75` (path strings);
    - `test_ad1214_decision_pre_clearance.py:1183` (`BridgeNotifications.tsx`).
  - Holds.
- **Claim:** `dangerouslySetInnerHTML` appears only in the artifact viewer.
  - Run: `rg -l dangerouslySetInnerHTML ui/src`
  - Found: `components/artifacts/ArtifactViewer.tsx`.
  - Holds.
- **Claim:** BUILD_SUCCESS has one emitter.
  - Run: `rg 'EventType\.BUILD_SUCCESS|BuildSuccessEvent\(' src`
  - Found: `routers/build.py:501`, `events.py:611` (the field default), `events.py:609` (the class, never constructed).
  - Holds.
- **Claim:** neither title text exists in IntentSurface on the base.
  - Run: `rg 'Review issues|Review suggestions' ui/src/components/IntentSurface.tsx`
  - Found: nothing.
  - Holds.

## 11. What this does NOT change, and recorded limits

- No server change: `build.py`, `builder.py` and the event payloads are as they are.
- The Builder's readings lost on the Transporter path (`cognitive/builder.py:2538-2550`) remain #1769's review point.
- The success message text, including its suggestion count, is unchanged.
- The lists are not persisted and do not survive a reload.
- `BuildFailureReport.review_issues` keeps its type.
- Not measured: the new file was not run in this consult (read-only, no Node). The base-mode result in 8.2 is the oracle's check that the `beforeEach` order (render, open, then snapshot) shows chat messages. S2 and F2 passing on the base confirms it.

## 12. Prior art and blind spots (date used: 2026-11-17)

- This is a bug fix in ProbOS's own UI plumbing, so the external prior-art search does not apply and none was run. `docs/research/reference-projects.md` was not consulted for the same reason.
- Blind spots taken into the design:
  - a server that sends `null` or omits a field (D2, S6, F2);
  - a cut through a surrogate pair (D5, S5, W8);
  - markup and markdown in model text (D4, S3, W12);
  - a reader who expects the lists after a reload (section 11).
- Considered, deferred: a collapsed view for long lists. The 10-item and 500-code-point limits bound the height for now.

## 13. Acceptance criteria

- On the M1 head, the new file gives `8 passed` in the default mode and `6 failed | 2 passed` with `BF978_RUNXFAIL=1`, each failure at its own `expect`.
- After M2: `npx tsc -b` passes; the new file gives `8 passed` in both modes; the 8.1 set keeps its base counts.
- Every mutation row in 8.3 is KILLED by its named cases.
- `PROGRESS.md` and `DECISIONS.md` carry the M3 entries; the ledger test passes.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
