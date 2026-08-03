# AD-1176: WorkItem.project_id — the work-management spine

**Repo:** OSS (`d:\ProbOS`), branch `main`, HEAD `5c666a9b`
**Type:** AD. Already reserved by **#1107** — do not mint a new number.
**Issue:** #1107

---

## Scope decision (read this first)

Issue #1107 asks for two things: `project_id` on `WorkItem`, **and** "standing and chartered
projects with automatic resolution".

**Only the first is buildable today.** Verified 2026-08-03: the terms *standing project* and
*chartered project* appear **nowhere in the codebase, config, docs, DECISIONS or roadmap** —
searched `standing`, `charter`, `chartered` in a project context. `Project`
(`threads/__init__.py:1504`) has `id`, `name`, `created_at`, `last_active_at`, `description`,
`pinned_attachment_ids`, `archived` — no `kind`, `tier`, `status` or `category`. The
classification does not exist to resolve against.

Defining that taxonomy is a product decision (what *is* a standing project, what does automatic
resolution pick, what happens on conflict) and belongs to the Captain, not the Builder. The
issue itself says the remaining work-management decomposition "needs re-deriving".

**So this AD builds the substrate only.** It is purely additive, has zero consolidation risk,
and is the thing every later course depends on. The taxonomy stays on #1107 as a follow-up.

---

## Problem

`WorkItem` has no `project_id`. Projects exist and are fully wired for threads —
`Project`/`ProjectStore` (`threads/__init__.py:1504`/`:1534`), CRUD at `routers/projects.py`,
and `ChatThread.project_id` (`threads/__init__.py:224`, a soft optional reference). Work items
cannot belong to a project, so there is no way to group, filter or report on a body of work.

---

## Decision

Add `project_id: str | None = None` to `WorkItem`, migrate the table, thread it through the
store's read/write paths, and expose it for creation and filtering.

### Why this is low risk

- **`WorkItem` has no non-defaulted fields** (`workforce.py:619-657`, 23 fields, all defaulted,
  not frozen) — so field position is unconstrained and a new defaulted field is safe.
- **`_row_to_work_item` maps BY NAME**, not positionally (`workforce.py:4892`,
  `row["id"]`, `row["title"]`, …). This is the important difference from the AD-1017/AD-1019b
  precedent in `mcp_bridge/store.py:70`, whose comments carefully preserve a *positional*
  `row[19]` invariant. Here `ALTER TABLE ADD COLUMN` appending to the end cannot disturb
  anything, because nothing reads by index.
- **The INSERT names its columns explicitly** (`workforce.py:2050`), so adding one is a local
  edit, not a positional reshuffle.

### The work

1. **Dataclass** — `project_id: str | None = None` on `WorkItem`, placed next to `parent_id` so
   the grouping keys read together.

2. **Schema** — add `project_id TEXT` to the `CREATE TABLE` (`workforce.py:1019`) **and** a
   migration for existing databases. Follow the `persistent_tasks.py:140` idiom:

   ```python
   try:
       await self._db.execute("ALTER TABLE work_items ADD COLUMN project_id TEXT")
       await self._db.commit()
   except sqlite3.OperationalError:
       pass  # column already exists — migration idempotency
   ```

   Put it where the other post-CREATE migrations run in `start()`. A fresh DB gets the column
   from `CREATE TABLE`; an existing one gets it from the `ALTER`. Both must end up identical.

3. **Read/write paths** — `_row_to_work_item` (`:4892`), the INSERT (`:2050`), and
   `update_work_item`'s mutable-field set (`:3005`). `project_id` is **mutable** — work gets
   reassigned to a project after the fact, which is the normal case.

4. **`list_work_items`** (`:2147`) gains `project_id: str | None = None`, filtered **in SQL**
   alongside `status`/`assigned_to`/`work_type`/`parent_id`, not in memory. (`tags` is the
   in-memory one; do not copy that pattern here.)

5. **API** (`routers/workforce.py`) — `POST /api/work-items` accepts `project_id` in its body;
   `GET /api/work-items` accepts it as a query parameter. These handlers take raw
   `Request.json()` dicts today and define no Pydantic models — **do not introduce them in this
   AD.** Match the existing style; a model refactor is separate work.

6. **`project_id` is a SOFT reference.** No foreign key, no existence check at insert — matching
   `ChatThread.project_id`, which is also soft. A work item pointing at a deleted project simply
   stops matching that filter.

---

## Target files

| File | Change |
|---|---|
| `src/probos/workforce.py` | dataclass field; CREATE TABLE column; migration; `_row_to_work_item`; INSERT; update path; `list_work_items` filter. |
| `src/probos/routers/workforce.py` | accept `project_id` on create; query param on list. |
| `tests/test_ad1176_work_item_project.py` | NEW. |

---

## Acceptance criteria

The house rule that matters most here: **cache-only store tests mask column-mapping bugs.**
`WorkItemStore` supports `db_path=""` (cache-only, `start()` gates on `if self.db_path:` at
`:2009`), and a cache-only test would never execute `_row_to_work_item`, the INSERT column
alignment, or the migration. The existing `tests/test_workforce.py` fixture already uses a real
temp DB — follow it.

1. **Real-DB round trip.** Create a work item with a `project_id`, `stop()` the store, reopen a
   NEW store over the same file, and assert `project_id` reloads — *and* that every pre-existing
   field still reloads correctly beside it. This is the test that catches a column-mapping bug.
2. **Migration from a pre-AD-1176 schema.** Hand-create a `work_items` table WITHOUT
   `project_id`, insert a row, then open a `WorkItemStore` over it and assert (a) `start()`
   succeeds, (b) the old row loads with `project_id is None`, (c) a new row can be written and
   read back with a `project_id`. **Do not skip this by only testing a fresh DB** — a fresh DB
   takes the `CREATE TABLE` path and never exercises the `ALTER`.
3. **Migration is idempotent** — calling `start()` twice over the same file does not raise.
4. **Default is `None`** — a work item created without a `project_id` round-trips as `None`, and
   existing callers are unaffected.
5. **Filter by project** — `list_work_items(project_id=...)` returns only that project's items;
   an unknown id returns `[]`; `None` returns everything (the pre-AD behaviour).
6. **Filter composes** with `status` / `work_type` / `assigned_to`.
7. **`project_id` is updatable** via `update_work_item`, including setting it back to `None`.
8. **API** — `POST /api/work-items` with a `project_id` persists it; `GET /api/work-items?project_id=`
   filters. Per the house rule, every new endpoint behaviour needs happy path + error + input
   validation.
9. **Soft reference** — a work item whose project was deleted still loads; it just stops matching
   the filter. Assert rather than assume.

Expected: **14–18 new tests.**

### Gates

```powershell
$env:PROBOS_DATA_DIR="$env:TEMP\ad1176_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
& d:/ProbOS/.venv/Scripts/python.exe -m pytest `
  tests/test_ad1176_work_item_project.py `
  tests/test_workforce.py `
  tests/test_ad1080_work_item_steps.py `
  tests/test_ad791a_chat_threads_wiring.py `
  -q -n 0
```

(If a listed path does not exist, substitute the real one and SAY SO — do not silently drop a
gate.)

Then ONE full gate, run **synchronously**. Pipe through `Tee-Object -FilePath <log>`, never
`Select-Object` — a buffering pipe is what silences the run and gets it backgrounded.

**Baseline is 22,502 NODES** (AD-1178's gate: 22,501 passed + 1 environmental failure — carry
NODES, not passed). Reconcile `22,502 + <new tests> == passed + failed` and show the arithmetic.

---

## Do NOT build

- **Do not** define standing or chartered projects, a project `kind`/`tier`/`category`, or any
  automatic resolution. Undefined today; Captain's call; stays on #1107.
- **Do not** add Pydantic request/response models to `routers/workforce.py`. It uses raw dicts;
  match it.
- **Do not** add a foreign key or an existence check on `project_id`.
- **Do not** change `delete_project` cascade behaviour. Work items are deliberately not swept;
  note it as a follow-up rather than deciding it here.
- **Do not** change `ProjectStore`, `Project`, or `routers/projects.py`.
- **Do not** touch `crew_execution`'s 14-key evidence set or `SubtaskResult` — both are frozen
  and adding a key breaks recovery on every restart.
- **Do not** edit `PROGRESS.md`, `DECISIONS.md`, or the roadmap.
- **Do not** stage `config/system.yaml` (skip-worktree).

## Notes

- Stage before the full gate (`test_ad1123_bounded_federation_relay.py` reads *unstaged* diff).
- str-replace end-anchor trap: whatever appears at either END of `oldString` must reappear in
  `newString`. `workforce.py` is large with many similar dict/SQL literals — read the full
  surrounding construct before each edit and verify the neighbour survived.
- No config field is added, so `scripts/gen_config_reference.py` is NOT needed here.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
