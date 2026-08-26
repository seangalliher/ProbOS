# AD-1226 / BF-738 — an agent can recall what it produced, without carrying it

**Target repo:** OSS (`d:\ProbOS`), branch `main`.
**Closes:** BF-738 (#1197).
**Current highest AD: AD-1225. Current highest BF: BF-738. This is AD-1226.**

---

## The problem, established from the live vessel

The Captain asked Ezri for the top 15 PyPI packages. AD-1221 worked; the report was
delivered correctly and is in `chat_threads.db`. Four minutes later he asked her about
it and she said she could not see what she had sent — then explained that background
results are never written back into her episodic memory, and offered to file a proposal
to build that.

It is already built. AD-1166 stored episode `53299` at `08-08 23:01:17`, the exact second
of delivery, carrying `user_input`, `reflection`, and `outcomes[0]["response"]` with the
real table in it.

Two measured facts define the work:

1. **Nothing reads `outcomes` back.** `src/probos/cognitive/cognitive_agent.py` contains
   zero occurrences of `.outcomes`, `outcomes_json`, or `get("outcomes")`. The recall dict
   at ~L9931 is built from `user_input` and `reflection` only. Every other consumer of
   `outcomes` in `cognitive/` (`dreaming`, `procedures`, `storage_gate`,
   `importance_scorer`, `retrieval_practice`, `contradiction_detector`, `decomposer`) is a
   consolidation or scoring path; `episodic.py:1646` is the write-side `should_store` gate.
   None render outcome text into a prompt.

2. **The write cap loses most of it anyway.** `turn_promotion.py:289` stores `body[:500]`.
   Measured on this run: 1362 chars and 15 rows delivered, 500 chars and 7 rows stored, cut
   mid-word at `| charset-normalizer | 3.4.9 | The Real Fi`.

## The Captain's requirement (verbatim intent)

> I like the idea of content-addressable ref to the full body on demand. This would also
> work if there are other artifacts that are produced by the agent. If I asked the agent to
> write a book, I wouldn't want the entire book to be in episodic memory. The agent should
> be able to know what it wrote and be able to refer back to the book as needed to refresh
> its memory if I had a question on what it wrote.

Two capabilities, both required:

- **Know** — recall must say *that* something was produced, and enough about it to answer
  "did you do it?" and "what was it?" without a fetch.
- **Refer back** — the agent must be able to retrieve the full text on demand to answer a
  question about its content, in bounded pieces, without ever holding a book in context.

This is the AD-1209 shape: do not make the agent carry the state, give it a way to ask.

## Infrastructure that already exists — use it, do not duplicate it

Verified against HEAD before writing this prompt:

| Component | Location | Relevant API |
|---|---|---|
| `AttachmentStore` (AD-720) Protocol | `src/probos/attachments/store.py:32` | `async write(content_hash, blob, mime, *, origin=...) -> Path`, `async read(content_hash) -> bytes`, `async exists(...) -> bool`, `async size(...) -> int` |
| Allowed origins | `src/probos/attachments/store.py:15` | `agent_artifact` already exists (AD-797) — use it |
| `ArtifactStore` (AD-797) | `src/probos/artifacts/__init__.py:85` | `add_version(*, thread_id, name, content_hash, mime, size_bytes, created_by) -> Artifact`; `latest(*, thread_id, name) -> Artifact | None`; `Artifact` has `id, thread_id, name, version, content_hash, mime, size_bytes, created_by, created_at, supersedes` |
| Runtime handles | e.g. `src/probos/proactive.py:4425-4426` | `getattr(runtime, "artifact_store", None)`, `getattr(runtime, "attachment_store", None)` |
| Tool protocol | `src/probos/tools/protocol.py` | `ToolResult(output=..., error=..., duration_ms=...)`, `ToolType` |
| Tool reference implementation | `src/probos/tools/work_item_status_tool.py` | read-only, ownership-scoped, never raises out of `invoke` |
| Tool registration seam | `src/probos/cognitive/agentic_dispatch.py:1711-1730` | the AD-1209 `status_ids` block; `registry.get(id)`, `registry.register(tool, provider=..., tags=[...])`, then id appended in the `tool_ids` assembly at ~L1927 |
| Episode dataclass | `src/probos/types.py:556` | `user_input`, `outcomes: list[dict]`, `reflection: str | None`, `correlation_id` |
| Config | `src/probos/config.py:1012` `MemoryConfig` | add the new flag here |

---

## Config flag (one, default-OFF)

Add to `MemoryConfig` in `src/probos/config.py`:

```python
# AD-1226: carry a content-addressable ref to a produced artifact in the
# episode's outcome, render a one-line "what I produced" cue at recall, and
# offer the read-only ``recall_artifact`` tool so the full text can be
# re-read on demand instead of being carried in memory. Default-OFF: when
# False every prompt this touches is byte-identical to today.
recall_outcome_refs_enabled: bool = False
```

With the flag off, **the assembled prompt must be byte-identical to today** and the tool must
not be offered. There must be a test proving this.

---

## Step 1 — write the ref (`src/probos/cognitive/turn_promotion.py`)

In `_store_promoted_episode` (currently ~L229), when the flag is on:

1. Encode the full `body` as UTF-8; `content_hash = hashlib.sha256(blob).hexdigest()`.
2. `await attachment_store.write(content_hash, blob, "text/markdown", origin="agent_artifact")`.
3. If `runtime.artifact_store` is available and `thread_id` is non-empty, register a version:
   `add_version(thread_id=thread_id, name=f"task-{work_item_id}", content_hash=..., mime="text/markdown", size_bytes=len(blob), created_by=agent_id)`.
   Registration failure is non-fatal — the attachment ref alone is enough to fetch by.
4. Put the ref in the outcome dict alongside the existing keys:

```python
"artifact_ref": {
    "content_hash": content_hash,
    "mime": "text/markdown",
    "size_bytes": len(blob),
    "chars": len(body),
    "artifact_id": artifact.id if artifact is not None else "",
    "name": f"task-{work_item_id}",
},
```

5. Keep a **short digest** in `"response"` for the embedding and as a no-fetch fallback.
   Replace `body[:500]` with a digest capped by a named module constant
   `_OUTCOME_DIGEST_CHARS = 240`, cut on a line boundary where one exists within the cap so
   it never ends mid-table-cell. State the reason for the number in a comment: it feeds the
   semantic embedding and one rendered line, and the full text is now retrievable, so it no
   longer needs to be a partial copy of the payload (Design Principle 13a — a ceiling must
   be a decision).

Everything here is log-and-degrade. **An artifact that fails to store must never turn a
delivered report into a failed one** — that rule is already stated in the existing docstring
and must survive.

## Step 2 — render the cue (`src/probos/cognitive/cognitive_agent.py`)

**Do not change the `mem.get('input', '') or mem.get('reflection', '')` line at L8403.**
Investigation did not establish that it is a defect; showing both fields for every episode
would enlarge the memory section of every prompt for every agent, which is a separate
decision with its own budget consequences. Note it in the AD entry as an open question and
leave it alone.

Instead, when the flag is on:

1. In the recall→mem-dict construction at ~L9931, extract from the episode's **first outcome
   that carries one** a compact pair, and only when present:

```python
mem["outcome_digest"] = <the outcome's "response", already short>
mem["outcome_ref"] = <the outcome's "artifact_ref" dict>
```

   Guard defensively: `ep.outcomes` may be absent, empty, or contain non-dicts.

2. In `_format_memory_section` (~L8383-8404), after the existing content line, append **one**
   additional line when `outcome_ref` is present:

```
    -> you produced "task-70cd290af319" (1,362 chars). Re-read it with recall_artifact("7f3a9c2e...").
```

   Use the real `content_hash` (a readable prefix is fine — the tool accepts a prefix) and the
   real char count. Keep it to one line. If a digest is present but no ref, render the digest
   line only. The wording must make the *action* obvious, in the style of the AD-1209 tool
   description: the agent should read this and know it can look.

## Step 3 — the read tool (`src/probos/tools/recall_artifact_tool.py`, NEW)

Model it closely on `work_item_status_tool.py`. A `RecallArtifactTool` class satisfying the
duck-typed AD-423a `Tool` protocol:

- `tool_id = "recall_artifact"`, `name = "Recall Artifact"`, `tool_type = ToolType.UTILITY_AGENT`.
- **Description** must teach the behaviour, following the AD-1209 precedent: use this when
  asked about the content of something you produced earlier; you do not remember the text
  itself, you remember that you wrote it and can read it back; it is read-only.
- **Input schema:** `ref` (content hash or prefix of at least 8 chars, or an artifact name),
  optional `offset` (int, default 0). Required: `ref`.
- **Paging is mandatory.** Return at most `_MAX_CHARS_PER_READ = 4000` characters per call,
  plus `total_chars`, `offset`, `next_offset` (or `null` at the end), and `truncated`. This is
  the whole point of the Captain's book example: the agent must be able to walk a large
  artifact without ever holding it all. State the 4000 figure's rationale in a comment.
- **Ownership scoping**, mirroring AD-1209: resolve only artifacts this agent produced
  (`Artifact.created_by == agent_id`) or hashes referenced by that agent's own episodes. A
  miss reports an honest not-found rather than leaking another agent's output. An empty
  `agent_id` is **not** a wildcard.
- **Never raise out of `invoke`.** Every miss is an honest-degrade `ToolResult`.
- Binary/non-text mime: report the mime and size and decline to inline it, rather than
  returning mojibake.

## Step 4 — offer the tool (`src/probos/cognitive/agentic_dispatch.py`)

Add a `recall_ids` block mirroring the AD-1209 `status_ids` block at L1711-1730 exactly:
flag-gated **and** store-gated, idempotent `registry.get`/`registry.register`, wrapped in
`try/except` with a `logger.warning` that says what was lost, `recall_ids = []` on failure.
Append `*recall_ids` to the `tool_ids` assembly at ~L1927.

---

## Tests (`tests/test_ad1226_recall_artifact.py`, NEW)

Follow existing conventions: pytest + pytest-asyncio, `_Fake*` stubs over mock chains,
Arrange-Act-Assert, `test_{method}_{scenario}_{expected}` naming.

Required coverage:

1. **Flag OFF is byte-identical** — assemble the memory section for an episode carrying an
   `artifact_ref` with the flag off; assert the rendered lines equal today's output exactly,
   and that `recall_artifact` is absent from the offered `tool_ids`.
2. **Write side** — a promoted run stores the blob under `origin="agent_artifact"`, registers
   an `ArtifactStore` version, and puts a well-formed `artifact_ref` in the outcome.
3. **Write side degrades** — `attachment_store.write` raising must still deliver the report
   and still store the episode; assert the warning and that no exception escapes.
4. **Digest never cuts mid-cell** — a markdown table body produces a digest ending on a line
   boundary.
5. **Render** — flag on, the extra line appears once, carries the real char count, and names
   the tool.
6. **Render, no ref** — an ordinary episode with no `artifact_ref` renders exactly as today.
7. **Tool happy path** — full artifact under the cap returns the whole text, `truncated=False`,
   `next_offset` null.
8. **Tool paging** — an artifact larger than 4000 chars returns exactly 4000, `truncated=True`,
   a `next_offset` that when passed back returns the following slice with no gap or overlap.
   Assert the concatenation of pages reconstructs the original exactly.
9. **Tool ownership** — another agent's artifact reports not-found; empty `agent_id` is not a
   wildcard.
10. **Tool honest-degrade** — unknown hash, hash shorter than 8 chars, and an
    `attachment_store.read` raising all return a `ToolResult` rather than raising.
11. **THE CROSSING TEST** (this is the one that matters — its absence is why this shipped):
    a promoted run completes → episode is stored → recall assembles the prompt → the produced
    line appears → the tool is invoked with the ref taken **from that rendered line** → the
    original body comes back. One test, end to end, no stubbing of the middle.

## Acceptance criteria

- Full suite green. Current baseline is **22,931 nodes** (passed + skipped + failed); report
  the new count.
- Run with:
  `$env:PROBOS_DATA_DIR="$env:TEMP\ad1226_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'; & d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 > logs\ad1226-gate.log 2>&1`
  Use a **unique log filename**; a locked log returns stale content silently. Never pipe
  pytest through `Select-Object` or `Tee-Object` — it backgrounds the run.
- `get_errors` clean on every touched file.
- Mutation-check at least the crossing test and the byte-identical test: break the production
  code, confirm the test fails, **restore the file and confirm the suite is green again**.
- `config/system.yaml` is **skip-worktree**. Do not stage it. If you add the key locally,
  parse it through the real `SystemConfig` and print a neighbouring key to prove the file
  still loads.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

Named explicitly because each is tempting and none is in scope:

- **Do not** change the `input or reflection` line at L8403. Open question, separate decision.
- **Do not** add a UI surface, panel, or API route for recall. The ArtifactDrawer already
  exists and is not part of this.
- **Do not** change the `ArtifactStore` or `AttachmentStore` schemas, or add a new origin.
- **Do not** touch AD-1204 resumption, BF-732 concurrency accounting, or the work-item
  reconciler.
- **Do not** extend `WorkItemStatusTool`; this is a sibling tool, not a feature of that one.
- **Do not** build search-inside-artifact, summarisation, or cross-agent artifact sharing.
- **Do not** apply the ref mechanism to ward-room posts or group chat in this pass. Promoted
  1:1 turns only; the mechanism generalises later.
- **Do not** raise `tool_result_max_chars` or any other unrelated cap.
