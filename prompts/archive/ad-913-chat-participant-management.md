# AD-913 — Chat-thread participant management

**One-line:** Add idempotent `add_participant` / `remove_participant` to `ChatThreadStore` and the `POST` / `DELETE /api/threads/{id}/participants` REST routes — the substrate foundation for "start a 1:1, then add crew" and "the Captain joins an agent-created chat."

**Status:** Ready to build
**Target repo:** OSS (`d:\ProbOS`)
**Epic:** Ad-hoc crew collaboration (group chat → meeting) — Phase 1, foundation AD
**Dependencies:** none (this AD is the foundation the rest of the epic depends on)
**Estimated tests:** +14 (new file `tests/test_ad913_participant_management.py`)
**Current highest committed AD:** **AD-912** (DECISIONS.md:23, PROGRESS.md:5). AD-913 is unused.

---

## Context

The epic substrate is the AD-791 `ChatThreadStore` — a SQLite-backed, Teams-style group-DM where `participants` are first-class (a JSON `list[str]` column), **not** the Ward Room forum (Captain's ruling, 2026-06-07; recorded in the `roadmap.md` northstar block "Ad-hoc crew collaboration (group chat → meeting)").

Today the store can `create_thread`, `get_thread`, `update_thread`, `set_title`, append messages, and find/create a default 1:1 — but there is **no way to mutate the participant set of an existing thread**. AD-913 adds exactly that, at the store layer and over REST. Everything downstream (AD-914 fan-out, AD-919 "join") calls these two methods.

### Verified codebase anchors (grep'd 2026-06-07)

Store — `src/probos/threads/__init__.py`:
- Schema column: `participants TEXT NOT NULL,  -- JSON list[str]` (line 44).
- `ChatThread` dataclass (line ~93): `participants: list[str]`; `to_dict()` emits `"participants": list(self.participants)` and `"last_active_at": self.last_active_at`.
- `_connect()` (line 176): `sqlite3.connect(str(self._db_path), isolation_level=None)`, `row_factory = sqlite3.Row`, `PRAGMA foreign_keys = ON`. Injected `self._clock` (default `time.time`) and `self._id_factory`.
- `get_thread(thread_id) -> ChatThread | None` (line 230).
- `update_thread(...)` (line 260) is the return-shape precedent: mutate, then `return self.get_thread(thread_id)`, returning `None` only when the row is missing.
- **`set_title(lock=True)` (line 315) is the `BEGIN IMMEDIATE` read-modify-write precedent** (line 327): `conn.execute("BEGIN IMMEDIATE")` → `try:` SELECT → modify → UPDATE → `conn.execute("COMMIT")` → `except Exception: conn.execute("ROLLBACK"); raise`. Mirror this exactly.
- `append_message` is the precedent for bumping activity: `UPDATE chat_threads SET last_active_at = ? WHERE id = ?`. (`set_title` does **not** bump `last_active_at`; your new methods must, on the mutating path.)
- `_row_to_thread(row)` (line 984) parses `participants=json.loads(row["participants"]) if row["participants"] else []`.
- **No `add_participant` / `remove_participant` exists** — confirmed by grep (only `_row_to_thread` matched). Both methods are net-new.

Router — `src/probos/routers/threads.py`:
- `router = APIRouter(prefix="/api/threads", tags=["threads"])` (line 25).
- `_get_store(runtime)` (line 28): `getattr(runtime, "chat_thread_store", None)`; raises `HTTPException(status_code=503, detail="Chat thread store not available")` when `None` (line 31).
- 404 convention: `raise HTTPException(status_code=404, detail="Thread not found")` (lines 125, 144, 173, …).
- Request models are `pydantic.BaseModel` + `Field`; handlers are `async def`, take `runtime: Any = Depends(get_runtime)`, and return `thread.to_dict()`.

Registration — `src/probos/api.py`:
- `threads` is imported (line 211) and included in the `for r in (...)` loop via `app.include_router(r.router)` (line 254). **New routes ride the existing registration — `api.py` does NOT need to change.**

Tests — `tests/test_ad791_chat_threads.py`:
- Store tests construct `ChatThreadStore(tmp_path / "threads.db")` directly (real store, no mocks).
- REST `client` fixture (lines 125–137): real store → `runtime = SimpleNamespace(chat_thread_store=store)` → `app = FastAPI(); app.include_router(threads_router.router); app.dependency_overrides[get_runtime] = lambda: runtime` → `return TestClient(app), store`. Mirror this in the new test file.

---

## Solution overview

1. Two synchronous store methods, race-safe via `BEGIN IMMEDIATE`, idempotent, returning the updated `ChatThread` (or `None` when the thread is missing), bumping `last_active_at` only when the participant set actually changes.
2. Two REST routes on the existing `threads` router: `POST /{thread_id}/participants` (JSON body `{agent_id}`) and `DELETE /{thread_id}/participants/{agent_id}`.

### Design decisions (read before building)

- **Idempotency = true no-op.** Re-adding a present member, or removing an absent one, performs **no write** and does **not** bump `last_active_at`; it still returns the (unchanged) thread. `last_active_at` is bumped **only** on the mutating path. This is the literal reading of "is a no-op" + "Update `last_active_at`". *(Flagged to the Captain as the one interpretive call — see report.)*
- **POST 400 vs 422.** The scope requires **400** for missing/empty `agent_id`. Pydantic `Field(..., min_length=1)` would yield **422**, so do **not** use it. Declare the body field as `agent_id: str = ""` (defaulting a missing field to empty) and do an explicit `if not body.agent_id.strip(): raise HTTPException(status_code=400, ...)`. This makes both *missing* and *empty* → 400.
- **DELETE has no 400 path.** `agent_id` is a path segment; an empty one makes the URL not match the route (FastAPI 404/405), so no explicit 400 is needed or reachable. Removing an absent-but-nonempty `agent_id` is the no-op success case (200 + unchanged thread).
- **No registry validation.** AD-913 does **not** check `agent_id` against the `AgentRegistry`; add/remove are pure participant-list operations. (A future AD may add validation.) Therefore **no `AgentRegistry` fixture is needed** — the real `ChatThreadStore` on `tmp_path` is the only substrate fixture (BF-287: real fixtures at the substrate boundary, no MagicMock).

---

## Implementation

### Section 1 — Store methods (`src/probos/threads/__init__.py`)

Add both methods to `ChatThreadStore`, immediately after `set_title` / `is_title_locked` (i.e. in the "title-lock + personality helpers" block, near line ~360) so they sit next to the `BEGIN IMMEDIATE` precedent. Mirror the `set_title(lock=True)` transaction shape exactly.

```python
def add_participant(self, thread_id: str, agent_id: str) -> ChatThread | None:
    """AD-913: add an agent to a thread's participant set (idempotent).

    Returns the updated ``ChatThread``, or ``None`` when the thread row
    is missing. Adding an agent already present is a no-op (no
    duplicate, no ``last_active_at`` bump). The read-modify-write of the
    JSON ``participants`` column runs under ``BEGIN IMMEDIATE`` for race
    safety, matching the ``set_title(lock=True)`` pattern.
    """
    with self._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT participants FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            current = json.loads(row["participants"]) if row["participants"] else []
            if agent_id not in current:
                current.append(agent_id)
                conn.execute(
                    "UPDATE chat_threads SET participants = ?, last_active_at = ? "
                    "WHERE id = ?",
                    (json.dumps(current), self._clock(), thread_id),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return self.get_thread(thread_id)

def remove_participant(self, thread_id: str, agent_id: str) -> ChatThread | None:
    """AD-913: remove an agent from a thread's participant set (idempotent).

    Returns the updated ``ChatThread``, or ``None`` when the thread row
    is missing. Removing an agent that is not present is a no-op (no
    write, no ``last_active_at`` bump). Removes every copy defensively
    in case a pre-existing duplicate slipped in. ``BEGIN IMMEDIATE``
    read-modify-write per ``set_title(lock=True)``.
    """
    with self._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT participants FROM chat_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            current = json.loads(row["participants"]) if row["participants"] else []
            if agent_id in current:
                current = [p for p in current if p != agent_id]
                conn.execute(
                    "UPDATE chat_threads SET participants = ?, last_active_at = ? "
                    "WHERE id = ?",
                    (json.dumps(current), self._clock(), thread_id),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return self.get_thread(thread_id)
```

Notes:
- Returning from inside the `with` (the missing-thread `return None`) is fine — the context manager closes the connection on exit. `COMMIT` of a no-write `IMMEDIATE` transaction is valid and harmless.
- `self._clock()` (not `time.time()`) so the injected test clock drives `last_active_at` deterministically.

### Section 2 — REST routes (`src/probos/routers/threads.py`)

Add a request model alongside the existing models (after `AppendMessageRequest`, ~line 70):

```python
class ParticipantRequest(BaseModel):
    # AD-913: declared as a plain str with an empty default (NOT
    # Field(..., min_length=1)) so a missing OR empty agent_id is
    # caught by the explicit 400 check below — min_length would 422.
    agent_id: str = ""
```

Add the two routes. Place them after `append_message` and before the AD-794 `auto-name` route for locality (registration order is **not** load-bearing here — both paths are unambiguous and don't overlap the `/{thread_id}` templates):

```python
# AD-913: chat-thread participant management. Foundation for the
# ad-hoc group-chat epic — "add crew to a 1:1" (POST) and "the Captain
# joins an agent-created chat" / "remove a participant" (DELETE).
@router.post("/{thread_id}/participants")
async def add_participant(
    thread_id: str,
    body: ParticipantRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    agent_id = body.agent_id.strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    thread = store.add_participant(thread_id, agent_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


@router.delete("/{thread_id}/participants/{agent_id}")
async def remove_participant(
    thread_id: str,
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    thread = store.remove_participant(thread_id, agent_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()
```

### Section 3 — `api.py`

No change. The `threads` router is already imported and registered (api.py:211, :254); the new routes ride that registration. **Do not edit `api.py`.**

---

## Tests — `tests/test_ad913_participant_management.py` (new file, +14)

Use the AD-791 patterns: real `ChatThreadStore(tmp_path / "threads.db")` at the store layer; the REST `client` fixture copied from `tests/test_ad791_chat_threads.py:125-137` (real store → `SimpleNamespace(chat_thread_store=store)` → `app.include_router(threads_router.router)` → `dependency_overrides[get_runtime]`). **No MagicMock at the substrate boundary (BF-287).** For the two `last_active_at` tests, pass a deterministic monotonic clock into the store, e.g.:

```python
def _seq_clock():
    n = {"t": 0}
    def _c():
        n["t"] += 1
        return float(n["t"])
    return _c
# store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
```

Store-level (8):
1. `test_add_participant_appends` — create 1:1 `["a1"]`, `add_participant(id, "a2")` → participants `["a1","a2"]`; returns a `ChatThread`.
2. `test_add_participant_idempotent_no_duplicate` — add `"a2"` twice → `"a2"` appears exactly once; length stable.
3. `test_add_participant_bumps_last_active_at` — monotonic clock; capture `created_at`, add a new agent, assert returned `last_active_at > created_at`.
4. `test_add_participant_idempotent_does_not_bump_last_active_at` — monotonic clock; add `"a2"`, record `last_active_at`, add `"a2"` again, assert `last_active_at` unchanged.
5. `test_add_participant_missing_thread_returns_none` — `add_participant("nope", "a1") is None`.
6. `test_remove_participant_removes` — 2-party thread, remove one → gone; other remains.
7. `test_remove_participant_absent_is_noop` — remove an agent not present → participants unchanged, returns the thread (not `None`).
8. `test_remove_participant_missing_thread_returns_none` — `remove_participant("nope", "a1") is None`.

REST-level (6):
9. `test_rest_add_participant_happy` — create via `POST /api/threads`, then `POST /api/threads/{id}/participants` `{"agent_id":"a2"}` → 200; body `participants` contains `"a2"`.
10. `test_rest_add_participant_404_missing_thread` — POST to `/api/threads/missing/participants` `{"agent_id":"a2"}` → 404.
11. `test_rest_add_participant_400_empty_agent_id` — POST `{"agent_id":""}` → 400.
12. `test_rest_add_participant_400_missing_agent_id` — POST `{}` → 400 (proves the `= ""` default + explicit check; **not** 422).
13. `test_rest_remove_participant_happy` — create with `participants:["a1","a2"]`, `DELETE /api/threads/{id}/participants/a2` → 200; `participants` no longer contains `"a2"`.
14. `test_rest_remove_participant_404_missing_thread` — `DELETE /api/threads/missing/participants/a2` → 404.

---

## What this does NOT change (Do NOT build)

- **No fan-out / cross-agent visibility / message broadcast / prompt injection** — that is **AD-914**. AD-913 only mutates the participant list.
- **Do NOT touch the Ward Room** (`routers/wardroom*.py`, forum substrate). The epic substrate is `ChatThreadStore`, not the forum.
- **No UI** — no `.tsx`, no @-picker, no LeftRail wiring. UI is **AD-917 / AD-919**.
- **Do NOT change the legacy `/api/agent/{id}/chat` path** or `routers/agents.py`.
- **Do NOT edit `api.py`** — the `threads` router is already registered.
- **Do NOT validate `agent_id` against the `AgentRegistry`** — out of scope; pure list ops.
- **Do NOT add** turn-taking, convergence, attachments, projects/task linkage, or meeting/voice/avatar anything.
- **Do NOT change** the `ChatThread` dataclass, the `chat_threads` schema, or `to_dict()` (the `participants` column already exists).

---

## Tracking

- **PROGRESS.md** — add the AD-913 shipped entry (header line + era-5 file if that's the live convention).
- **DECISIONS.md** — add the `AD-913: Chat-thread participant management` entry.
- **roadmap.md** — the AD-913 row in the "Ad-hoc crew collaboration" northstar table is a forward marker; leave it (PROGRESS/DECISIONS carry shipped state per repo convention).
- **Session memory** `/memories/session/group-chat-epic.md` — flip the status-log line for AD-913 to shipped.

---

## Acceptance criteria

1. `add_participant` / `remove_participant` exist on `ChatThreadStore`, are synchronous, idempotent, use `BEGIN IMMEDIATE`, return the updated `ChatThread` or `None` for a missing thread, and bump `last_active_at` only on the mutating path.
2. `POST /api/threads/{id}/participants` (body `{agent_id}`) and `DELETE /api/threads/{id}/participants/{agent_id}` exist on the `threads` router: 200 + `thread.to_dict()` on success, 404 missing thread, 400 missing/empty `agent_id` (POST), 503 via `_get_store` when the store is absent.
3. New file `tests/test_ad913_participant_management.py` with the 14 enumerated tests, all passing, using real `ChatThreadStore` fixtures (no MagicMock at the substrate boundary).
4. `api.py` unchanged; legacy `/api/agent/{id}/chat` unchanged; Ward Room untouched; no UI.
5. Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad913_participant_management.py tests/test_ad791_chat_threads.py -v -n 0`.
6. Full gate green (no regressions): `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-07)

```
grep -n "participants TEXT NOT NULL" src/probos/threads/__init__.py
  44:    participants TEXT NOT NULL,           -- JSON list[str]
grep -n "def _connect" src/probos/threads/__init__.py
  176:    def _connect(self) -> sqlite3.Connection:
grep -n "def get_thread" src/probos/threads/__init__.py
  230:    def get_thread(self, thread_id: str) -> ChatThread | None:
grep -n "def update_thread" src/probos/threads/__init__.py
  260:    def update_thread(
grep -n "def set_title" src/probos/threads/__init__.py
  315:    def set_title(
grep -n 'conn.execute("BEGIN IMMEDIATE")' src/probos/threads/__init__.py
  327: (set_title lock=True — canonical read-modify-write pattern to mirror)
grep -n "def _row_to_thread" src/probos/threads/__init__.py
  984:    participants=json.loads(row["participants"]) if row["participants"] else []
grep -n "add_participant\|remove_participant" src/probos/threads/__init__.py
  (no match — both methods are net-new)

grep -n "router = APIRouter" src/probos/routers/threads.py
  25:router = APIRouter(prefix="/api/threads", tags=["threads"])
grep -n "def _get_store" src/probos/routers/threads.py
  28:def _get_store(runtime: Any):
  31:        raise HTTPException(status_code=503, detail="Chat thread store not available")
grep -n 'status_code=404' src/probos/routers/threads.py
  125/144/173/...: raise HTTPException(status_code=404, detail="Thread not found")

grep -n "threads" src/probos/api.py
  211:        threads,  # AD-791 (Wave 193): chat-threads substrate
  254:        app.include_router(r.router)   # threads ridealong — no api.py change needed

tests/test_ad791_chat_threads.py:125-137  — real-store `client` fixture to mirror
DECISIONS.md:23  — "### AD-912: ..." (highest committed; AD-913 unused)
PROGRESS.md:5    — "**AD-912 shipped (2026-06-07).** ..."
```
```
