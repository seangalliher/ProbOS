# BF-073: Database Hardening — Missing Indexes & Foreign Key Enforcement

## Problem

Two database integrity issues found during code review:

### 1. Missing Indexes — MEDIUM

Frequent `WHERE` queries run without supporting indexes. As data grows, these degrade to full table scans:

| Database | Table.Column | Query Pattern |
|----------|-------------|---------------|
| `ward_room.db` | `threads.channel_id` | `WHERE channel_id = ?` (every channel view) |
| `ward_room.db` | `posts.thread_id` | `WHERE thread_id = ?` (every thread view) |
| `ward_room.db` | `posts.author_id` | Author-based lookups |
| `persistent_tasks.db` | `tasks.status` | `WHERE status = ?` |
| `persistent_tasks.db` | `tasks.webhook_name` | `WHERE webhook_name = ?` |
| `assignments.db` | `assignments.status` | `WHERE status = ?` |

**Note:** `ward_room.db` has only 1 index (endorsement uniqueness constraint). `persistent_tasks.db` and `assignments.db` have 0 indexes.

### 2. Foreign Key Enforcement Disabled — MEDIUM

SQLite requires `PRAGMA foreign_keys = ON` to be executed **per connection**. Only `identity.py:397` enables this. The 11 other `aiosqlite.connect()` locations do not, making all foreign key constraints purely documentary:

| File | Line | Database |
|------|------|----------|
| `ward_room.py` | 219 | `ward_room.db` — threads→channels, posts→threads FK declared but unenforced |
| `persistent_tasks.py` | 121 | `persistent_tasks.db` |
| `assignment.py` | 90 | `assignments.db` |
| `workforce.py` | 949 | `workforce.db` |
| `acm.py` | 107 | `acm.db` |
| `skill_framework.py` | 325, 426 | `skills.db` |
| `event_log.py` | 43 | `events.db` |
| `journal.py` | 63 | `cognitive_journal.db` |
| `consensus/trust.py` | 106 | `trust.db` |
| `mesh/routing.py` | 69 | `hebbian_weights.db` |

## Solution

### Part A: Add Missing Indexes

Add `CREATE INDEX IF NOT EXISTS` statements to the schema definitions in each affected module. Using `IF NOT EXISTS` ensures safe schema migration — the indexes apply on next boot with zero migration logic needed.

### Part B: Enable Foreign Keys

Add `PRAGMA foreign_keys = ON` to every `aiosqlite.connect()` call's post-connection setup, matching the existing pattern in `identity.py:397`.

## Files to Modify

### 1. `src/probos/ward_room.py`

Add indexes to the `_SCHEMA` string (after the existing table definitions, around line 194):

```sql
CREATE INDEX IF NOT EXISTS idx_threads_channel ON threads(channel_id);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_channel ON mod_actions(channel_id);
```

Add PRAGMA after the `aiosqlite.connect()` call at line 219. In the `start()` method, right after `self._db = await aiosqlite.connect(self.db_path)`:

```python
await self._db.execute("PRAGMA foreign_keys = ON")
```

### 2. `src/probos/persistent_tasks.py`

Add indexes to the schema definition:

```sql
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_webhook ON tasks(webhook_name);
```

Add PRAGMA after `aiosqlite.connect()` at line 121:

```python
await self._db.execute("PRAGMA foreign_keys = ON")
```

### 3. `src/probos/assignment.py`

Add indexes to the schema definition:

```sql
CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
```

Add PRAGMA after `aiosqlite.connect()` at line 90:

```python
await self._db.execute("PRAGMA foreign_keys = ON")
```

### 4. Remaining aiosqlite connections — PRAGMA only

Add `PRAGMA foreign_keys = ON` after the connect call in each of these files. These databases may not have FK constraints today, but enabling the pragma is a defensive best practice that ensures any future FK additions are enforced:

- **`src/probos/workforce.py:949`** — after `aiosqlite.connect()`
- **`src/probos/acm.py:107`** — after `aiosqlite.connect()`
- **`src/probos/skill_framework.py:325` and `:426`** — after both `aiosqlite.connect()` calls
- **`src/probos/substrate/event_log.py:43`** — after `aiosqlite.connect()`
- **`src/probos/cognitive/journal.py:63`** — after `aiosqlite.connect()`
- **`src/probos/consensus/trust.py:106`** — after `aiosqlite.connect()`
- **`src/probos/mesh/routing.py:69`** — after `aiosqlite.connect()`

**Pattern to follow** (from `identity.py:396-397`):

```python
self._db = await aiosqlite.connect(str(db_path))
await self._db.execute("PRAGMA foreign_keys = ON")
```

**Important:** The PRAGMA must be executed **before** `executescript()` or any schema DDL, because `executescript()` implicitly commits and foreign key enforcement must be enabled before any FK-related operations.

### 5. Tests

Add tests in a new file `tests/test_database_hardening.py`:

```python
"""Tests for BF-073: Database indexes and foreign key enforcement."""
```

Test cases:

**Index verification** (verify indexes exist after schema creation):

1. **Ward Room indexes exist**: Start WardRoomService, query `sqlite_master` for `idx_threads_channel`, `idx_posts_thread`, `idx_posts_author`
2. **PersistentTasks indexes exist**: Start the service, verify `idx_tasks_status`, `idx_tasks_webhook` in sqlite_master
3. **Assignment indexes exist**: Start AssignmentService, verify `idx_assignments_status` in sqlite_master

**Foreign key enforcement**:

4. **Ward Room FK enforced**: Insert a thread with invalid `channel_id` → should raise IntegrityError
5. **Ward Room FK accepted**: Insert a thread with valid `channel_id` → succeeds
6. **PRAGMA applied on connect**: For each service, verify `PRAGMA foreign_keys` returns 1 after start

**Regression**:

7. **Existing Ward Room operations unaffected**: Create channel → create thread → create post → verify all succeed
8. **Existing assignment operations unaffected**: Basic assignment creation still works

## Implementation Notes

- `CREATE INDEX IF NOT EXISTS` is safe to run on existing databases — it's a no-op if the index already exists. No migration logic needed.
- `PRAGMA foreign_keys = ON` is a per-connection setting. It does NOT retroactively validate existing data. Orphaned rows created before FK enforcement will remain. This is acceptable — enforcement prevents new violations going forward.
- Do NOT skip `identity.py` — it already has the PRAGMA. Leave it as-is.
- The PRAGMA line should go immediately after `aiosqlite.connect()`, before any `executescript()` or `commit()` calls.
- Some of these databases may not have any FK constraints declared. The PRAGMA is still safe to enable — it's a no-op when there are no FKs.
- Ward Room has the most impact — the `threads.channel_id → channels.id` and `posts.thread_id → threads.id` foreign keys will now be enforced, preventing orphaned threads/posts from invalid cascading operations.

## Acceptance Criteria

- [ ] Ward Room has indexes on `threads.channel_id`, `posts.thread_id`, `posts.author_id`
- [ ] PersistentTasks has indexes on `tasks.status`, `tasks.webhook_name`
- [ ] Assignments has index on `assignments.status`
- [ ] All 12 `aiosqlite.connect()` locations have `PRAGMA foreign_keys = ON`
- [ ] All new tests pass
- [ ] Existing tests unaffected (especially Ward Room's 137 tests)
