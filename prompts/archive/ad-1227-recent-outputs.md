# AD-1227 — an agent knows what it has made, without asking its memory

**Target repo:** OSS (`d:\ProbOS`), branch `main`.
**Addresses:** BF-739 (#1198).
**Current highest AD: AD-1226. Current highest BF: BF-740. This is AD-1227.**

---

## Why this exists

AD-1226 shipped and is correct. Verified live on the reference vessel 2026-08-09, work item
`712ebc8d645f`: the episode carries a well-formed `artifact_ref`, the bytes are in the
attachment store under `origin="agent_artifact"`, the `ArtifactStore` row exists. Every write
worked.

The agent still told the Captain it could not see what it had sent.

The ref-bearing episode never reaches the prompt. Measured against a snapshot of the live
store using the real `EpisodicMemory.recall_for_agent` at `k=10`:

| question asked | rank of the episode carrying the ref |
|---|---|
| *"Are you able to see the results you provided to me?"* | **absent** — only 2 episodes returned |
| the exact original request text | **5** |
| *"what version did you report for pydantic"* | **7** |

For the question that actually failed, **rank 1 is the agent's own previous denial** — *"The
task shows as done, but I don't have visibility into the actual output it produced."* A wrong
answer, once given, is stored and preferentially recalled for the question that produced it.

Three causes compound and none is cheaply fixable by ranking:

1. AD-1166's outcome episode is a **semantic twin** of its own acknowledgement — both carry
   the Captain's request verbatim, differing only in the `[1:1 background task]` vs
   `[1:1 with Ezri]` prefix. The conversational prefix is nearer a conversational query.
   Measured: 5 episodes hold the request text, 3 of them twins.
2. **Dream consolidation manufactures competitors that narrate the failure** — four episodes
   of the form *"The Captain requested a PyPI top-15 list ~1.5h ago. Three separate task IDs
   were opened…"* outrank the episode recording the success, and more arrive over time.
3. The embedded `chroma:document` is `user_input` + `reflection` only, never the outcome
   digest, so a question about the **content** cannot match the episode holding it.

## The decision

**"What have I produced recently?" is not a similarity question and must not be answered by
one.** The artifact register already knows the answer exactly. Read it directly.

Tuning importance or thresholds to make one episode win would pit a single constant against
an unbounded, self-replenishing population of competitors. That is not a fight worth entering
and it would change recall for every agent.

This AD adds a small, deterministic, bounded register of what the agent has made, sourced from
`ArtifactStore` by owner. No embeddings, no ranking, no competition.

## Infrastructure verified against HEAD

| Component | Location | Notes |
|---|---|---|
| `ArtifactStore` | `src/probos/artifacts/__init__.py:85` | has `add_version`, `get`, `latest`, `list_versions`, `list_thread_latest`, `count_thread_latest`, `delete`, `find_first_by_hash` — **no by-creator query exists**; you will add one |
| `list_thread_latest` | same file, L302 | the pattern to mirror: INNER JOIN on `MAX(version)`, `ORDER BY created_at DESC`, int-validated limit raising `ValueError("artifact_list_limit_invalid")` |
| `_SCHEMA` | same file, L38 | indexes are `CREATE INDEX IF NOT EXISTS`, run via `executescript` on construction — adding one is idempotent and needs no migration |
| `Artifact` | same file, L57 | `id, thread_id, name, version, content_hash, mime, size_bytes, created_by, created_at, supersedes` |
| DM prompt emit | `src/probos/cognitive/cognitive_agent.py:8828` | `_emit("episodic", [...], salience=...)` — the DM path |
| Ward-room emit | same file, L9152 | **out of scope, do not touch** |
| Flag | `MemoryConfig.recall_outcome_refs_enabled` | AD-1226's flag; reuse it, do not add a second |
| Hash prefix constant | same file, `_PRODUCED_HASH_CHARS = 12` | the register must use this same constant so the rendered ref is exactly what `recall_artifact` accepts |
| Tool | `src/probos/tools/recall_artifact_tool.py` | accepts a hash prefix of ≥8 chars, ownership-scoped on `created_by == agent_id` |

`created_by` is the agent's `.id` (e.g. `counselor_counselor_0_67c601cb`), **not** the sovereign
uuid used for episodes — confirmed on the live row. Query the register with `self.id`.

---

## Step 1 — the store query (`src/probos/artifacts/__init__.py`)

Add an index to `_SCHEMA`:

```sql
CREATE INDEX IF NOT EXISTS idx_artifacts_creator ON artifacts (created_by, created_at);
```

Add a method mirroring `list_thread_latest` in structure and validation:

```python
def list_recent_by_creator(
    self, created_by: str, *, limit: int | None = None,
) -> list[Artifact]:
```

- Latest version only, grouped by `(thread_id, name)` — name uniqueness is per thread, so
  grouping by `name` alone would collapse two different threads' artifacts that share a name.
- `ORDER BY created_at DESC`.
- An empty/blank `created_by` returns `[]` — **it is not a wildcard**. This mirrors the
  ownership rule in `recall_artifact_tool` and `work_item_status_tool`; an anonymous caller
  must not enumerate the ship's output.
- Validate `limit` exactly as `list_thread_latest` does, same `ValueError` message.

## Step 2 — the rendered register (`src/probos/cognitive/cognitive_agent.py`)

A **module-level** function, not a method:

```python
def _format_recent_outputs(runtime: Any, agent_id: str) -> list[str]:
```

This is not stylistic. AD-1226's first implementation made `_format_memory_section` call a
second instance method and broke the AD-979d `_Holder` stub, whose docstring pins the contract
that the renderer needs only `.id`/`._runtime` plus `_confabulation_guard`. Keep prompt helpers
free of instance coupling.

Returns `[]` — meaning no emit at all, byte-identical prompt — when **any** of:
- `_recall_outcome_refs_on(runtime)` is False,
- `runtime.artifact_store` is absent,
- `agent_id` is blank,
- the agent has produced nothing,
- the store raises (log-and-degrade, `logger.warning` naming what was lost).

Otherwise render a compact block. Newest first, `_RECENT_OUTPUTS_LIMIT = 3` (a named constant
with its rationale stated: this is an always-present section, so it is charged to every turn's
budget; three is enough to cover "the thing I just made" plus recent context without becoming a
catalogue). Shape:

```
=== WHAT YOU HAVE PRODUCED ===
Things you made. You do not carry their text — read one back with recall_artifact.
  "task-712ebc8d645f" (1,333 bytes, 12m ago) -> recall_artifact("c1a8be361c54")
  "what-is-ai.docx" v3 (37,395 bytes, 42d ago) -> recall_artifact("66d3d67edaf8")
=== END ===
```

- The hash prefix MUST be `content_hash[:_PRODUCED_HASH_CHARS]` — the same constant AD-1226's
  memory cue uses, so both surfaces name an identifier the tool actually resolves.
- Show `v{version}` only when `version > 1`; a first version is noise.
- Use the existing `format_duration` helper for the age, consistent with the memory section.

Emit it in the **DM path only**, immediately after the `_emit("episodic", ...)` block at
~L8828, as `_emit("recent_outputs", segments)`. Do not pass a salience. Do not touch the
ward-room emit at ~L9152.

## Step 3 — tests (`tests/test_ad1227_recent_outputs.py`, NEW)

pytest + pytest-asyncio, `_Fake*` stubs over mock chains, AAA, descriptive names.

**Store:**
1. Returns only the caller's artifacts; another creator's are excluded.
2. Blank `created_by` returns `[]` and is not a wildcard.
3. Latest version only — three versions of one name yield one row at the highest version.
4. Two threads sharing an artifact name both appear (proves grouping is by `(thread_id, name)`).
5. Newest first.
6. `limit` validation raises `ValueError("artifact_list_limit_invalid")` for `0`, `-1`, `True`,
   `"3"`.

**Render:**
7. Flag OFF → `[]` → prompt byte-identical.
8. No `artifact_store` → `[]`.
9. No artifacts → `[]`, and specifically **no empty header block**.
10. Store raising → `[]` plus a warning, no exception escapes.
11. Rendered line carries the name, a formatted byte count, and a hash prefix of exactly
    `_PRODUCED_HASH_CHARS`.
12. `v2` shows a version marker; `v1` does not.

**The two that matter most:**

13. **Independent of episodic memory.** Build the register with `runtime.episodic_memory = None`
    and assert it still renders. This is the whole point of the AD: BF-739 happened because the
    only path to this information went through semantic recall. A test that would still pass if
    someone quietly reintroduced that dependency is worthless.
14. **THE CROSSING TEST.** A promoted run completes (real `_store_promoted_episode` with a real
    `FilesystemAttachmentStore` and real `ArtifactStore`) → the register is rendered → the hash
    is parsed **out of the rendered line** → `RecallArtifactTool.invoke` with that hash returns
    the original body byte-for-byte. Nothing stubbed in the middle, and **no `EpisodicMemory`
    involved anywhere in the test**. This is the mechanical equivalent of the Captain's live
    test and it must pass deterministically.

## Acceptance criteria

- Full suite green. Baseline **22,967 nodes** (22,933 passed + 34 skipped); report the new count.
- Run with a **unique** log filename:
  `$env:PROBOS_DATA_DIR="$env:TEMP\ad1227_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'; & d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 > logs\ad1227-gate.log 2>&1`
  Never pipe pytest through `Select-Object`/`Tee-Object` — it backgrounds the run. **Run it to
  completion and read the summary line**; a partial run is not evidence.
- `tests/test_ad979d_slice2_live_wiring.py` and `tests/test_ad1226_recall_artifact.py` must both
  still pass — the first is the duck-typed-renderer canary, the second is the feature this
  builds on.
- `get_errors` clean on every touched file.
- Mutation-check the crossing test and the flag-off test: break production, confirm the right
  test fails, **restore and confirm the suite is green again**.
- `config/system.yaml` is skip-worktree. Do not stage it and do not edit it.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- **Do not** change recall ranking, `agent_recall_threshold`, importance scoring, salience, or
  dream consolidation. BF-739 documents why; those are the losing fight this AD avoids.
- **Do not** persist `Episode.correlation_id` — that is BF-740 (#1199), separately filed.
- **Do not** add the outcome digest to the embedded `chroma:document`. Real, listed in BF-739
  as cause 3, and its own decision.
- **Do not** touch the ward-room prompt path, the AD-1226 write side, or `recall_artifact` itself.
- **Do not** add a second config flag, a UI surface, or an API route.
- **Do not** widen `recall_artifact` ownership or change its paging.
