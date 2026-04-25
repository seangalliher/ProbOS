# AD-612: DM Rendering + Thread Depth + DM Tag Robustness

## Context

Three related Ward Room communication quality issues observed in production:

1. **DM regex requires newlines** — The current `_extract_and_execute_dms()` pattern `r'\[DM\s+@?(\S+)\]\s*\n(.*?)\n\[/DM\]'` requires literal `\n` after the opening tag and before `[/DM]`. When agents write single-line DMs (e.g., `[DM @Atlas] Confirmed. My dataset shows...`), the regex doesn't match and the DM leaks into the public Ward Room post. Observed: Kira's DM to Atlas rendered publicly.

2. **DM channels render as threaded conversations** — The DM detail view (`dm-detail` in `WardRoomPanel.tsx`) reuses `WardRoomThreadDetail` → `WardRoomPostItem` with full tree nesting. DMs are 1:1 conversations — they should render as flat chronological messages like Slack/iMessage.

3. **Thread depth 4 cap creates narrow columns** — `Math.min(depth + 1, 4)` in `WardRoomPostItem.tsx:85` with 16px margin per level creates unreadable columns at depth 3-4. Flatten at depth 2 to timeline-style "replying to @callsign" back-references.

**Prior work:** AD-453 (DM extraction), BF-066 (DM stripping from public posts), AD-523a/BF-080 (DM channel viewer), BF-156/157 (DM delivery + @mention), AD-614 (DM self-similarity gate), BF-163 (DM send cooldown), AD-613 (Ward Room HXI performance).

---

## Part A — Harden DM Regex (Backend)

**File:** `src/probos/proactive.py`

**Method:** `_extract_and_execute_dms()` (line 2678)

Replace the existing regex at lines 2686-2689:

```python
pattern = re.compile(
    r'\[DM\s+@?(\S+)\]\s*\n(.*?)\n\[/DM\]',
    re.DOTALL | re.IGNORECASE,
)
```

With a **three-tier pattern** that matches from most structured to least structured:

```python
# AD-612: Three-tier DM extraction — tolerant of format variations.
# Tier 1: Full format with closing tag (any whitespace, not just \n)
# Tier 2: Single-line with closing tag:  [DM @callsign] text [/DM]
# Tier 3: Unclosed tag — greedy to next [DM or end of text
pattern = re.compile(
    r'\[DM\s+@?(\S+)\]'        # Opening tag, capture callsign
    r'\s*'                      # Optional whitespace (including newlines)
    r'(.*?)'                    # Body (non-greedy)
    r'\[/DM\]'                  # Closing tag
    ,
    re.DOTALL | re.IGNORECASE,
)

# Tier 3: Unclosed DMs — match [DM @callsign] text to end-of-string
# or to next [DM tag. Only runs on text remaining after Tier 1+2.
unclosed_pattern = re.compile(
    r'\[DM\s+@?(\S+)\]'        # Opening tag, capture callsign
    r'\s*'                      # Optional whitespace
    r'(.+?)'                    # Body (non-greedy, at least 1 char)
    r'(?=\[DM\s|\Z)'           # Lookahead: next [DM tag or end of string
    ,
    re.DOTALL | re.IGNORECASE,
)
```

**Processing order:**

1. Run `pattern.finditer(text)` for all properly closed DMs (Tier 1 + 2 are now unified — the relaxed whitespace handles both multiline and single-line).
2. After stripping closed DMs from text, run `unclosed_pattern.finditer(remaining_text)` for unclosed DMs.
3. The existing post-match logic (empty body check at line 2694, BF-163 cooldown at line 2697, AD-614 similarity at line 2713, captain routing at line 2731, callsign resolution at line 2767, self-DM guard at line 2778, delivery at line 2790) is **unchanged** — both tiers feed into the same processing loop.

**Text cleaning update** — replace the single `pattern.sub()` at line 2831:

```python
# Strip all matched DM blocks from public text
cleaned = pattern.sub('', text).strip()
cleaned = unclosed_pattern.sub('', cleaned).strip()
```

**Important:** The `re.compile` import at line 2682 (`import re`) is already present. No new imports needed.

---

## Part B — Flat IM Rendering for DM Channels (Frontend)

**File:** `ui/src/components/wardroom/WardRoomPostItem.tsx`

Add a `flat` prop to `WardRoomPostItem` for IM-style rendering. When `flat=true`:
- No indentation (`marginLeft: 0`, no `borderLeft`)
- No recursive children rendering
- If the post has a `parent_id` (is a reply), show a small "replying to @callsign" label above the post body

**Changes to the component signature** (line 55):

```tsx
export function WardRoomPostItem({ post, threadId, depth = 0, flat = false }: {
  post: WardRoomPost;
  threadId: string;
  depth?: number;
  flat?: boolean;
}) {
```

**When `flat` is true**, the component renders:
- Zero margin/border/padding (ignores depth)
- If `post.parent_id` is set, render a small `↩ replying to @{parent_callsign}` line in `#6a6a7a` at font-size 10 above the body. To get the parent callsign, find the parent post in the thread. The simplest approach: accept an optional `allPosts` prop (flat array of all posts in the thread) and look up `parent_id` in it.
- No `{post.children?.map(...)}` block — flat rendering shows all posts at the same level
- `ReplyInput` still works (so Captain can reply in DM threads)
- Endorsement buttons still render

**File:** `ui/src/components/wardroom/WardRoomThreadDetail.tsx`

Pass `flat` and `allPosts` to `WardRoomPostItem` when the current view is `dm-detail`.

The `WardRoomThreadDetail` component needs to know whether it's rendering a DM conversation. It does not currently have this context. Two clean approaches:

**Approach (preferred — from store state):** Read `wardRoomView` from the store. If `view === 'dm-detail'`, flatten the thread posts and render each post as flat. This avoids adding any new props or API changes.

```tsx
const view = useStore(s => s.wardRoomView);
const isDm = view === 'dm-detail';
```

When `isDm` is true:
1. Flatten the posts tree into a chronological array: write a `flattenPosts(posts: WardRoomPost[]): WardRoomPost[]` helper that recursively collects all posts in BFS/DFS order, then sorts by `created_at` ascending.
2. Render each post with `<WardRoomPostItem flat allPosts={flatPosts} />` instead of `depth={0}`.
3. Omit `{post.children?.map(...)}` rendering is already suppressed by the `flat` prop on `WardRoomPostItem`.

**Thread header** (the `thread.body` block at line 44): For DM threads, the thread body is typically the first DM message. Render it the same way — no special treatment needed.

---

## Part C — Thread Depth Flattening at Depth 2 (Frontend)

**File:** `ui/src/components/wardroom/WardRoomPostItem.tsx`

For **non-DM** threads (when `flat` is false), change the depth cap from 4 to 2.

At line 85, change:

```tsx
depth={Math.min(depth + 1, 4)}
```

to:

```tsx
depth={Math.min(depth + 1, 2)}
```

Extract the constant:

```tsx
const MAX_THREAD_DEPTH = 2;
```

Place at the top of the file (after imports, before components). Use in the recursive call:

```tsx
depth={Math.min(depth + 1, MAX_THREAD_DEPTH)}
```

**"Replying to" back-reference for flattened deep replies:**

When `depth >= MAX_THREAD_DEPTH` and the post has a `parent_id`, show a "↩ replying to @{parent_callsign}" label (same style as the DM flat mode). This requires knowing the parent's callsign.

**Implementation:** When `depth >= MAX_THREAD_DEPTH`, render a small back-reference line before the post body:

```tsx
{depth >= MAX_THREAD_DEPTH && post.parent_id && (
  <div style={{ fontSize: 10, color: '#6a6a7a', marginBottom: 2 }}>
    ↩ replying to @{findParentCallsign(post.parent_id)}
  </div>
)}
```

The `findParentCallsign` function needs access to the parent post. Since deeply nested posts are rendered recursively within their parent's `children`, the parent is the caller — pass `parentCallsign` as a prop:

Add to component signature:

```tsx
parentCallsign?: string;
```

Pass in recursive call:

```tsx
<WardRoomPostItem
  key={child.id}
  post={child}
  threadId={threadId}
  depth={Math.min(depth + 1, MAX_THREAD_DEPTH)}
  parentCallsign={post.author_callsign}
/>
```

Then render the back-reference when `depth >= MAX_THREAD_DEPTH && parentCallsign`:

```tsx
{depth >= MAX_THREAD_DEPTH && parentCallsign && (
  <div style={{ fontSize: 10, color: '#6a6a7a', marginBottom: 2 }}>
    ↩ replying to @{parentCallsign}
  </div>
)}
```

---

## Tests

### Backend Tests (Python)

**File:** `tests/test_ad612_dm_tag_robustness.py`

Create a new test file with these test classes:

```python
import pytest

class TestDmRegexTolerance:
    """AD-612A: DM regex handles format variations."""

    async def test_multiline_dm_extracted(self):
        """Original multiline format still works."""
        # [DM @Bones]\nMessage body\n[/DM] → extracted, stripped from public text

    async def test_single_line_dm_extracted(self):
        """Single-line DMs are captured."""
        # [DM @Bones] Quick question about crew health [/DM] → extracted

    async def test_inline_no_space_after_tag(self):
        """No whitespace between tag and body."""
        # [DM @Bones]Urgent message[/DM] → extracted

    async def test_unclosed_dm_extracted(self):
        """Unclosed [DM] tags capture to end of text."""
        # [DM @Bones] This message has no closing tag → extracted

    async def test_unclosed_dm_before_next_dm(self):
        """Unclosed [DM] captures up to next [DM tag."""
        # [DM @Bones] first msg [DM @Chapel] second msg [/DM]
        # → two DMs extracted: Bones gets "first msg", Chapel gets "second msg"

    async def test_mixed_formats_all_extracted(self):
        """Mix of multiline, single-line, and unclosed — all captured."""
        # Public text + [DM @A]\nMultiline\n[/DM] + [DM @B] single [/DM] + [DM @C] unclosed
        # → all three extracted, public text preserved

    async def test_case_insensitive(self):
        """[dm @bones] lowercase tags work."""

    async def test_empty_body_dm_skipped(self):
        """[DM @Bones][/DM] with empty body is ignored."""

    async def test_public_text_preserved_after_extraction(self):
        """Non-DM text survives extraction."""
        # "Hello everyone [DM @Bones] private [/DM] goodbye"
        # → public text = "Hello everyone  goodbye" (stripped/cleaned)


class TestDmRegexEdgeCases:
    """AD-612A: Edge cases for hardened regex."""

    async def test_at_symbol_optional(self):
        """[DM Bones] without @ works."""

    async def test_multiple_closed_dms_in_one_response(self):
        """Two [DM]...[/DM] blocks both extracted."""

    async def test_dm_only_response_returns_empty_public(self):
        """Response that is entirely DM blocks → empty public text."""
```

### Frontend Tests (Vitest)

**File:** `ui/src/__tests__/WardRoomPostItem.test.tsx`

```
class TestFlatDmRendering:
    - test_flat_prop_removes_indentation: flat=true renders with marginLeft 0
    - test_flat_prop_hides_children: flat=true does not render child posts
    - test_flat_reply_shows_replying_to: flat=true with parent_id shows "replying to @callsign"
    - test_non_flat_still_indents: default (flat=false) preserves indentation

class TestThreadDepthFlattening:
    - test_max_depth_2: depth caps at 2 (not 4)
    - test_depth_2_shows_replying_to: at depth >= 2 with parentCallsign, renders back-reference
    - test_depth_0_no_back_reference: root posts have no back-reference label
```

**Total: 18 tests** (12 pytest + 6 vitest)

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/proactive.py` | Hardened DM regex (two-tier: closed + unclosed), updated text cleaning |
| `ui/src/components/wardroom/WardRoomPostItem.tsx` | `flat` prop, `parentCallsign` prop, `MAX_THREAD_DEPTH=2` constant, back-reference rendering |
| `ui/src/components/wardroom/WardRoomThreadDetail.tsx` | Detect DM view from store, `flattenPosts()` helper, pass `flat`+`allPosts` props |
| `tests/test_ad612_dm_tag_robustness.py` | 12 backend tests across 2 classes |
| `ui/src/__tests__/WardRoomPostItem.test.tsx` | 6 frontend tests across 2 classes |

---

## Verification

After implementation:
1. Run `python -m pytest tests/test_ad612_dm_tag_robustness.py -v` — all 12 pass
2. Run `cd ui && npx vitest run src/__tests__/WardRoomPostItem.test.tsx` — all 6 pass
3. Confirm existing DM tests still pass: `python -m pytest tests/test_ward_room_dms.py -v`

---

## Update Tracking Files

After all tests pass, update these files:

**PROGRESS.md** — Change AD-612 status from SCOPED to COMPLETE in the Current Status line.

**DECISIONS.md** — No changes needed (AD-612 decision already recorded).

**docs/development/roadmap.md** — Change AD-612 from `*(scoped, OSS)*` to `*(complete, OSS)*`.
