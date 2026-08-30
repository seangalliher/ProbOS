# AD-1294 — a retrieved record must carry its author, and a retrieval score must not be called confidence

**Status:** ready to build (UNBLOCKED)
**Closes:** #1090 (BF-689).
**Depends on:** nothing. Independent of AD-1293 and AD-1295 — build in any order.
**Estimated tests:** 12–15 new.
**Files:** `src/probos/cognitive/oracle_service.py`, `src/probos/cognitive/crew_executor.py`. Both verified **clean** at `c75428bb`.

---

## Why this is its own AD, and not part of the confabulation cluster

#1090 was triaged alongside #1087 and #1200 on the hypothesis that all three are
one mechanism — *the system cannot distinguish what it did from what it said*.
For #1087 and #1200 that hypothesis held and is built as AD-1293.

**It does not hold for #1090, and forcing it in would be worse than fixing it
directly.** #1087's defect is that the record of a successful tool write *does
not exist* (successes are anonymous). #1090's is the opposite: the record exists,
is correct, is distinctly labelled at the source — and is then **dropped by two
renderers before the agent ever sees it**. Nothing about a per-turn act-ledger
helps; the fix is to stop discarding a field already in hand.

The two share a *shape* — a provenance-bearing record dropped at a seam, the
repo's dominant defect class per #1172/#1282 — but not a mechanism. Any
structural check on attribution would have to compare names in reply prose,
which is exactly the text-matching verdict AD-1285 built and deleted.

---

## Problem

#1090's framing is **partly refuted by execution.** It concludes:

> The agent had correct, complete, and *distinctly labelled* data for both. The
> summary misrepresented it. So the fix does not belong in retrieval.

The first half is true at `OracleService._query_records_semantic`. It stops being
true at the render boundary, and on one path the mislabelling is done **by the
system, in source** — not by the agent's narration.

### Defect 1 — the retrieval score is rendered to the agent *labelled* "confidence"

`crew_executor.py:675-700`, `_render_commons_entry`:

```python
    """Render one ``OracleResult`` with its AD-1139-shaped provenance marker.

    Marker carries source tier, confidence and age, so a low-confidence or
    aged entry is visibly weightable. ...
    """
    ...
    score = float(getattr(result, "score", 0.0) or 0.0)
    ...
    marker = f"{provenance} (confidence {score:.2f}"
```

The value is `OracleResult.score` — the retrieval relevance score. It is emitted
to the agent as the word `confidence`, and the docstring asserts the same
mistake.

#1090 says of the agent's reply:

> Entries 2 and 3 have **no `confidence` field at all** — those numbers are the
> Oracle's relevance `score`, relabelled as the author's belief.

On this path the agent was **faithfully repeating what the system told it**. An
agent cannot be held to a distinction the prompt does not make. Fix the source
of the claim, not the repetition of it.

### Defect 2 — `frontmatter.author` is never rendered on either path

`_query_records_semantic` (`oracle_service.py:1050-1098`) attaches the author
correctly:

```python
                metadata={
                    "path": metadata.get("path", ""),
                    "frontmatter": _decode_record_frontmatter(
                        metadata.get("frontmatter_json", ""),
                    ),
                },
```

`frontmatter` carries `author`, stamped by `write_entry`
(`records_store.py:267`, `semantic.py:433`).

Neither renderer emits it.

`oracle_service.py:715-735` (`query_and_format`) renders provenance, score, age,
`path`, and content. **No author.**

`crew_executor.py:685-700` renders provenance, mislabelled score, age, and
content. **No author, and no path either.**

**Absence verified by enumeration** (`grep '\["frontmatter"\]|get("frontmatter"'
across `src/probos/**`, 25 hits): every consumer is analysis or maintenance —
`dreaming`, `backlinks`, `knowledge_linter`, `notebook_quality`, `records_store`,
`semantic`, `gaps`, `diagnostic_context`. **Not one is a prompt-rendering path.**

The consequence matches the report exactly. On the `oracle_service` path the
agent has the author only implicitly, encoded in a path string like
`notebooks/Anvil/consolidation-anomaly-cluster.md`, and inferring a byline from a
directory name is a guess it is not obliged to get right. On the `crew_executor`
path it has **nothing at all** and any attribution it offers is invention.

### Why this is not "make the agent hedge"

It is the reverse. The agent is currently asked to attribute records whose
authorship it was never given, and to weigh entries by a number the system
mislabelled. Both fixes give it *more* true information, not less confidence.
This satisfies #13(b): reach the capability by supplying the governed data, not
by removing the capability.

---

## Solution

Two renderers stop discarding what they hold, and one stops lying about what it
holds. No new primitive, no new store, no text matching.

---

### Section 1 — stop calling a retrieval score "confidence"

`src/probos/cognitive/crew_executor.py`, `_render_commons_entry` (`:675`).

SEARCH:
```python
    marker = f"{provenance} (confidence {score:.2f}"
```
REPLACE:
```python
    marker = f"{provenance} (relevance {score:.2f}"
```

Update the docstring at `:677-682` in the same edit — it currently asserts
"Marker carries source tier, confidence and age". It must say **relevance**, and
must record why:

```
    Marker carries source tier, retrieval RELEVANCE and age, so an
    off-topic or aged entry is visibly weightable. AD-1294 (#1090): this
    said "confidence" while emitting ``OracleResult.score``. Relevance is
    how well the entry matched the query; confidence is how strongly its
    author holds the claim. They are different quantities, and an agent
    that repeated the label was repeating the system's error.
```

`oracle_service.py:727` already says `score:` and is correct. **Do not change
it**, and do not unify the two words — `score` and `relevance` both name the
right quantity. Changing a correct line to match a wrong one is how the previous
mislabel would propagate.

---

### Section 2 — render the author on the Oracle format path

`src/probos/cognitive/oracle_service.py`, `query_and_format`, the `meta_parts`
block at `:719-724`.

Add the author **before** the path, from the frontmatter already in
`r.metadata`:

```python
            fm = r.metadata.get("frontmatter")
            if isinstance(fm, dict):
                author = str(fm.get("author") or "").strip()
                if author:
                    meta_parts.append(f"by {author}")
```

Constraints:

- **`isinstance(fm, dict)` is required.** `_decode_record_frontmatter` (`:136`)
  is documented at `:141` to promise a dict, but this renderer is reached by
  tiers that do not set the key at all, and by the archive path (`:1142`) which
  sets a bare `"author"` outside any frontmatter. A `.get` on a non-dict is an
  `AttributeError` inside a formatter that currently cannot raise.
- **Absent or empty author appends nothing.** Byte-identical rendering for every
  tier that carries no author. Do **not** emit `by ?` or `by unknown` — a
  fabricated placeholder byline is the defect this AD closes.
- It participates in the existing `max_chars` budget unchanged: the line is
  built first, then length-checked at `:737`. Do not special-case it.

### Section 3 — render the author on the crew-executor path

`src/probos/cognitive/crew_executor.py`, `_render_commons_entry`.

This path currently emits no `path` and no author, so an agent summarising a
commons entry has no attribution data whatsoever. Add the author to the marker,
using the same defensive shape (`metadata` is already type-checked at `:690`
with `if type(metadata) is dict`):

```python
    author = ""
    if type(metadata) is dict:
        age = _format_consult_age(metadata.get("timestamp"))
        fm = metadata.get("frontmatter")
        if type(fm) is dict:
            author = str(fm.get("author") or "").strip()
    marker = f"{provenance} (relevance {score:.2f}"
    if author:
        marker += f", by {author}"
    if age:
        marker += f", {age}"
    marker += ")"
```

Match the file's existing `type(x) is dict` idiom rather than introducing
`isinstance` here — the surrounding code uses it deliberately for exact-type
checks.

**The marker must survive truncation.** `_MAX_ENTRY_CHARS` is 400 (`:99`) and
the docstring states the marker "is never the part that gets cut". The author is
now part of the marker, so verify by test that a content string long enough to
force truncation still emits the author.

---

### Section 4 — do NOT do these

- **No attribution checker.** Do not compare names in the reply against the
  retrieved set. That is text matching against LLM prose; AD-1285 established
  the failure mode — a genuine case reaches the guard looking identical to a
  false one, and the branch contradicts truthful replies.
- **No prompt-instruction change.** Do not add "always attribute correctly" to
  any system prompt. #1200/AD-1204's lesson: prompting an agent to distrust
  itself degrades true statements too. Supply the data instead.
- **No change to retrieval.** `_query_records_semantic` is correct. BF-679's
  identity gate is binding and held; #1090 confirms it. Do not touch
  `records_scope`, `reader_id`, or `reader_department`.
- **No `confidence` field synthesis.** If a record has no `confidence` in its
  frontmatter, it does not get one. Rendering a default would recreate the
  false-precision defect in the opposite direction.

---

## Tests

New file `tests/test_ad1294_read_provenance_rendering.py`.

**Label correctness (Section 1)**
1. `_render_commons_entry` output contains `relevance` and **not** `confidence`.
2. A result whose frontmatter *does* carry a `confidence` value renders the
   relevance number, not that value — the two are not conflated in either
   direction.

**Author on the Oracle path (Section 2)**
3. Frontmatter with `author: "Anvil"` → the rendered line contains `by Anvil`.
4. Frontmatter present but `author` empty/missing → **no** `by ` fragment;
   assert the exact pre-AD-1294 line for byte-identity.
5. `metadata["frontmatter"]` absent → byte-identical, no raise.
6. `metadata["frontmatter"]` is a **non-dict** (`""`, `None`, `[]`, `0`) → no
   raise, no `by ` fragment. One parametrised test.
7. Author is rendered alongside the existing `path`, and `score:` is still the
   label on this path (Section 1 must not have leaked here).

**Author on the crew path (Section 3)**
8. Frontmatter with an author → marker contains `by <author>`.
9. No author → marker byte-identical to pre-AD-1294 apart from the
   `confidence`→`relevance` word.
10. Non-dict `metadata` → no raise (the existing `type(metadata) is dict` guard
    still holds with the new nested read).
11. **Truncation:** content long enough to exceed `_MAX_ENTRY_CHARS` still emits
    the full marker including the author.

**The regression this AD exists to prevent**
12. End-to-end over `_query_records_semantic` → `query_and_format`: a record
    authored by A and a record authored by B render **distinct** `by` fragments,
    each matching its own `frontmatter.author`. This is the one test that
    crosses the seam — the retrieval half and the render half each working
    separately is what shipped the defect.
13. The same, over `_render_commons_entry`.

**Assert the probe reached the branch.** For every "renders nothing" test, first
assert the positive case renders something with the same fixture shape. A
formatter test that asserts an absent substring passes trivially if the
formatter was never called.

---

## What this does NOT change

- `agentic_dispatch.py`, `cognitive_agent.py`, `continue_or_ask.py`,
  `repair_verification.py`, `fault_report.py`,
  `tools/browser/url_route_guard.py` — foreign-modified, read-only.
- `episodic.py`, `types.py`, `reply_pipeline.py` — AD-1293's targets. Do not
  edit them here; the two ADs must stay independently revertible.
- Sigma retrieval, BF-684 index coverage, write-path confabulation (#1087).
- `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md`.

---

## Test gate — read this before running anything

**The tree cannot run the full Python suite at `c75428bb`.**
`src/probos/tools/browser/session.py` imports `RedirectEscalation`, removed by
in-flight foreign work; roughly **423 tests fail** on collection, unrelated to
this AD.

Gate in a **linked worktree**:

```powershell
git worktree add d:\probos-gate1294 HEAD
# apply your staged patch into the worktree, then:
cd d:\probos-gate1294
$env:PYTHONPATH='d:\probos-gate1294\src'
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

`PYTHONPATH` shadows the editable install. Prove it took:
`python -c "import probos; print(probos.__file__)"` must print the worktree path.

Known worktree artefact: **3 `test_phantom_api_precheck_*` tests fail in a linked
worktree and pass in the main tree.** Verify, then count as passes.

Focused gate while iterating:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1294_read_provenance_rendering.py tests/test_oracle_service.py tests/test_crew_executor.py -q -p no:randomly
```

Reconcile `before + new == after` on the test count.

**Existing-test warning.** Grep the test suite for the literal string
`confidence ` against `_render_commons_entry` output **before** editing. A `?raw`
or output-substring assertion may pin the current wrong label as the contract —
this repo has had four such tests in one week (BF-707, BF-710, BF-717, BF-720).
If one exists, **update it and record why inline; never delete it.**

---

## Acceptance criteria

- No renderer emits the word `confidence` for a value sourced from
  `OracleResult.score`.
- `frontmatter.author` is rendered on both paths when present, and nothing is
  rendered when absent — no placeholder byline.
- Rendering is byte-identical for every result that carries no author.
- Two records by different authors render different bylines in one end-to-end
  test per path.
- The crew marker survives `_MAX_ENTRY_CHARS` truncation with the author intact.
- No reply text is inspected anywhere in this change.
- Run the `Diff Reviewer` subagent on the staged diff **with a different model
  than the one that wrote the code**; repair Critical/High findings before
  committing.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Tracking

- `PROGRESS.md` — AD-1294 entry.
- Close **#1090**. In the closing comment, record the premise correction: the
  score-as-confidence error was **in source** at `crew_executor.py:694`, not in
  the agent's narration, so the issue's conclusion that "the fix does not belong
  in retrieval" was right about retrieval and wrong about rendering.
- No `DECISIONS.md` entry required — this is a defect repair, not an
  architectural choice.

---

## Verified Against Codebase (2026-08-29, `c75428bb`)

```
oracle_service.py:136     def _decode_record_frontmatter(raw: Any) -> dict[str, Any]:
oracle_service.py:141         to ``{}`` — Tier 2 promises a dict under ``metadata["frontmatter"]``.
oracle_service.py:704         """Query and return formatted string with provenance tags.
oracle_service.py:721             meta_parts.append(_format_age(r.metadata["timestamp"]))
oracle_service.py:723             meta_parts.append(r.metadata["path"])
oracle_service.py:727             line = f"{r.provenance} (score: {r.score:.2f}"
oracle_service.py:1050    async def _query_records_semantic(
oracle_service.py:1093                    metadata.get("frontmatter_json", ""),
oracle_service.py:1142                    "author": entry.author_callsign or entry.author_agent_type,

crew_executor.py:99       _MAX_ENTRY_CHARS = 400
crew_executor.py:675      def _render_commons_entry(result: Any) -> str:
crew_executor.py:685          provenance = f"[{getattr(result, 'source_tier', '') or 'commons'}]"
crew_executor.py:694          marker = f"{provenance} (confidence {score:.2f}"

records_store.py:267          "author": author,
semantic.py:433               "author": author,
```

### Absence verified (enumeration run, with control)

```
CLAIM: no prompt-rendering path reads OracleResult.metadata["frontmatter"]
RUN:   grep '\["frontmatter"\]|get\("frontmatter"' src/probos/**/*.py
FOUND: 25 hits across diagnostic_context, dreaming, oracle_service (its own
       producer at :1044/:1093), backlinks, knowledge_linter, notebook_quality,
       records_store, semantic, gaps
CONTROL: the term is present 25 times, so the probe discriminates; a zero result
       would have been ambiguous
HOLDS: yes — every consumer is analysis/maintenance; none renders to a prompt

CLAIM: neither renderer emits an author
RUN:   read oracle_service.py:715-740 and crew_executor.py:675-705 in full
FOUND: oracle path emits provenance, score, age, path, content
       crew path emits provenance, mislabelled score, age, content
HOLDS: yes
```

### Live-vessel context

The read path is exercised: `%LOCALAPPDATA%\ProbOS\data\semantic\chroma.sqlite3`
backs the records tier, and the `ship-records` tree carries per-author notebook
directories, which is how a path-derived guess became plausible enough to ship.
