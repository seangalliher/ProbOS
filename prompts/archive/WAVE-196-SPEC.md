# AD-793 (Wave 196, v2) — Projects (long-lived context groups owning N threads + pinned files)

**Wave:** 196. Single Builder commit at completion.
**Sequence:** AD-793 ([#717](https://github.com/seangalliher/ProbOS/issues/717)).
**Builds on:** AD-791a (Wave 193) substrate, Wave 194 (auto-name + personality), Wave 195 (sidebar with reserved Projects placeholder).

v2 addresses 3 Required architect findings (wiring location at `runtime.py:444` not `startup/finalize.py`; `AttachmentStore.exists()` is async + must be `await`ed; canonical context-injection order is `visual → project → recall → user`) + 6 Recommended cleanups.

**The threads side is already done.** `chat_threads.project_id TEXT` exists since AD-791a (`threads/__init__.py:45`). `ChatThread.project_id` dataclass field exists. The threads router already supports `project_id` on create/patch/list-filter. Wave 196 adds the **Projects half** + flips the sidebar's placeholder section into a real one.

---

## Section 0 — Conceptual frame

Projects are long-lived context groups, owning N threads and pinned artifacts. Mirrors Claude "Projects" and Microsoft Teams "channels under a team" affordances. The Captain juggles multiple parallel concerns (ProbOS development, LinkedIn newsletter, household admin); Projects let related threads cluster under a shared description.

**The description IS the project's defining contribution.** Captain-authored "what this project is about" injects as a system-message preamble to every chat turn inside threads belonging to the project. That preamble is on TOP of (not in place of) the agent's birth-certificate instructions and per-thread `preprompt`. **Canonical message_text assembly order** (top-down, what the LLM reads first → last):

```
visual context        (AD-733a)
   ↓
project preamble      ← NEW in AD-793 (when thread.project_id is set + description non-empty)
   ↓
targeted recall       (AD-725)
   ↓
user message
```

Note: `agent.instructions` (birth-cert personality) and `thread.preprompt` are part of the LLM's separate **system_prompt** field (not `message_text`); they are unchanged by this AD. Project preamble joins the user-message-text composition chain because it represents per-turn Captain-authored framing, not durable agent identity.

Each tier adds *additional* context without overriding the prior tier. Project deletion does NOT delete contained threads by default — unparenting is the safe choice, with cascade as opt-in.

HXI design principles relevant here:
- **#1 The system understands the human.** Project description is plain prose, not structured config. Captain writes "This is for the ProbOS commercial overlay roadmap" once; every thread inside benefits.
- **#3 No emoji.** Project chevron + folder iconography are inline SVG stroke icons matching the Wave 195 ThreadRow visual language. Builder must NOT reach for emoji or Material icons.
- **#9 Alert-driven layout.** Projects with unread threads bold higher in the sidebar (defer unread visual to AD-792a; v1 just renders the section).

---

## Section 1 — SQLite schema

Add to `threads/__init__.py` `_SCHEMA` (additive; idempotent via `IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',  -- injected as preamble; default-empty allowed
    pinned_attachment_ids TEXT NOT NULL DEFAULT '[]',  -- JSON list[str] (SHA-256 refs into AttachmentStore, AD-720/731)
    archived INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_active_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects (archived);
CREATE INDEX IF NOT EXISTS idx_projects_last_active ON projects (last_active_at);
```

**Migration-safety:** the table is new — `CREATE TABLE IF NOT EXISTS` is sufficient. No PRAGMA table_info migration needed.

**Why JSON list for pinned_attachment_ids:** matches the existing `chat_threads.participants` precedent (JSON list[str]). A separate many-to-many `project_attachments` table is over-engineered for v1; expected scale is <50 pins per project. If we need ordering, ranking, or per-pin metadata later, AD-793a forward marker covers migration to a junction table.

`last_active_at` updates whenever a thread inside the project gets a new message (handled in `ProjectStore.touch(project_id)` called from the message-append path).

---

## Section 2 — Project dataclass + store

Add to `threads/__init__.py`:

```python
@dataclass
class Project:
    id: str
    name: str
    created_at: float
    last_active_at: float
    description: str = ""
    pinned_attachment_ids: list[str] = field(default_factory=list)
    archived: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "pinned_attachment_ids": list(self.pinned_attachment_ids),
            "archived": self.archived,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }
```

Add `ProjectStore` class (or extend `ChatThreadStore` — Builder picks the cleaner layout, but **prefer a separate `ProjectStore`** since the surfaces are decoupled). Required methods:

| Method | Behavior |
|---|---|
| `create_project(name, description="", pinned_attachment_ids=None) -> Project` | Generate UUID4 id, persist row, return `Project`. **Set `last_active_at = created_at` at creation** so the order-by-last-active list is deterministic for freshly-created empty projects. |
| `get_project(project_id) -> Project \| None` | Lookup by id. |
| `list_projects(*, include_archived=False, limit=100) -> list[Project]` | Ordered by `last_active_at DESC`. |
| `update_project(project_id, *, name=None, description=None, archived=None) -> Project \| None` | PATCH semantics — only set provided fields. Returns updated record or None if missing. |
| `delete_project(project_id, *, cascade=False) -> int` | If `cascade=True`, also delete contained threads + their messages (use the existing `ChatThreadStore.delete_thread` cascade pattern from AD-791). If False, set `project_id=NULL` on all threads owned by this project (unparent), then delete the project row. Returns `affected_threads` count (unparented or cascaded). |
| `pin_attachment(project_id, attachment_id) -> Project \| None` | Append SHA to `pinned_attachment_ids` if not already present. Idempotent. |
| `unpin_attachment(project_id, attachment_id) -> Project \| None` | Remove SHA from `pinned_attachment_ids`. Idempotent. |
| `touch(project_id, *, now=None) -> None` | Bump `last_active_at`. Called from the **router-level append-message handler** in `routers/threads.py` (see Section 4 below for the call site — NOT from inside `threads/__init__.py`'s message-append code, to keep the threads module decoupled from the projects layer). |

**Transactions:** all multi-step writes (delete with cascade, delete with unparent, pin add) use `BEGIN IMMEDIATE` per the AD-791a race-safety convention.

**Honest-degrade:** lookup methods return `None` on missing row; never raise. Mutation methods return the updated record or `None` if the underlying row vanished mid-operation.

---

## Section 3 — REST endpoints

New file: `src/probos/routers/projects.py`. Follows the same shape as `routers/threads.py`. Mount on the same router prefix in startup wiring.

| Method | Path | Behavior | Response |
|---|---|---|---|
| `GET` | `/api/projects` | List. Query params: `include_archived=false`, `limit=100`. | `{"projects": [Project.to_dict(), ...]}` |
| `GET` | `/api/projects/{id}` | Single. | `Project.to_dict()` directly (NOT wrapped — matches POST /api/threads precedent from Wave 195 review). |
| `POST` | `/api/projects` | Create. Body: `{"name": str, "description"?: str, "pinned_attachment_ids"?: list[str]}`. | `Project.to_dict()` directly. |
| `PATCH` | `/api/projects/{id}` | Update. Body: any of `{"name"?, "description"?, "archived"?}`. | Updated `Project.to_dict()` directly. |
| `DELETE` | `/api/projects/{id}` | Delete. Query: `cascade=false` (default — unparent threads). | `{"deleted": true, "affected_threads": int, "cascade": bool}` |
| `POST` | `/api/projects/{id}/pin` | Pin attachment. **`async def`** — Body: `{"attachment_id": str}`. SHA must exist in AttachmentStore (validate via `await _get_attachment_store(runtime).exists(sha)` — `exists()` is async per `attachments/store.py:60`); 400 if missing. 400 (not 404) is consistent with "the request was syntactically valid but the referenced data is unknown to us" and avoids implying the projects API exposes attachments as sub-resources. | Updated `Project.to_dict()`. |
| `POST` | `/api/projects/{id}/unpin` | Unpin attachment. Body: `{"attachment_id": str}`. Idempotent. | Updated `Project.to_dict()`. |

**Note on response shape:** every single-project body return is the project dict DIRECTLY, NOT wrapped in `{"project": {...}}`. This matches the Wave 195 review correction (`POST /api/threads` returns `thread.to_dict()` directly). LIST is `{"projects": [...]}` matching `GET /api/threads`'s `{"threads": [...]}` precedent.

**Cross-router import:** `_get_attachment_store` lives in `probos.routers.chat` and is imported across routers (precedent at `routers/avatars.py:55`). Reuse the existing helper; do not duplicate.

**Tests:** at minimum (1) happy path, (2) error (400 on pin with non-existent SHA, 404 on PATCH/DELETE missing id), (3) input validation per the OSS API test requirement.

---

## Section 4 — System-context injection (the actual cognitive contribution)

The chat flow at `routers/agents.py` already assembles `message_text` for the receiving agent. The existing composition runs in this code order:

- **L2073-76**: targeted-recall prepend (AD-725) — runs FIRST in code, lands BELOW visual context.
- **L2078+**: visual-context prepend (AD-733a) — runs LAST in code, lands ON TOP.

On-the-wire order today (top-down in the assembled `message_text`): **`visual → recall → user`**.

Wave 196 inserts the **project preamble BETWEEN the recall prepend and the visual prepend** so the final order is **`visual → project → recall → user`** (matches Section 0 diagram + Section 10 acceptance #6). The project preamble sits immediately under the present-tense sensory frame (visual) and above retrieval (recall), reflecting that it's the most stable Captain-authored framing.

```python
# ===== existing L2073-76 (recall prepend) runs HERE FIRST =====
if targeted_recall_block is not None:
    message_text = f"{targeted_recall_block}\n\n{message_text}"
# message_text now = "recall + user"

# ===== NEW (AD-793): project preamble inserts SECOND =====
_project_preamble: str | None = None
if thread is not None and thread.project_id:
    try:
        _project_store = getattr(runtime, "project_store", None)
        if _project_store is not None:
            _project = _project_store.get_project(thread.project_id)
            if _project is not None and _project.description.strip():
                _project_preamble = (
                    f"--- Project: {_project.name} ---\n"
                    f"{_project.description.strip()}\n"
                    f"--- End Project Context ---"
                )
    except Exception:
        logger.debug("AD-793: project preamble lookup failed", exc_info=True)

if _project_preamble is not None:
    message_text = f"{_project_preamble}\n\n{message_text}"
# message_text now = "project + recall + user"

# ===== existing L2078+ (visual prepend) runs LAST =====
# After visual prepend: message_text = "visual + project + recall + user"  ✅
```

**Honest-degrade:** when project_store is missing, the project row is deleted, or the description is empty, the preamble is silently omitted (Tier-2 log-and-degrade). No crash.

**Delimiter framing (`--- Project: ... ---` / `--- End Project Context ---`):** locked in for v1 per BF-294's "explicit context framing prevents confabulation" lesson. Matches AD-733a's visual-context delimiter pattern. ~12 tokens of overhead is noise next to the description body and provenance is the more durable property.

**Touch-on-message-append call site:** when a message lands in a thread that belongs to a project, `project_store.touch(thread.project_id)` MUST be called to bump `last_active_at`. **Do it at the router layer**, NOT inside `threads/__init__.py`. Specifically: in `routers/threads.py`'s POST `/api/threads/{id}/messages` handler (the existing append-message endpoint), after the successful `chat_thread_store.append_message(...)` call, look up `runtime.project_store` and if the thread has a non-null `project_id`, call `touch(project_id)`. This keeps the threads substrate module decoupled from the projects layer (option (a) from architect Rec3). Honest-degrade on touch failure.

**Pinned attachments:** v1 does NOT auto-inject pinned attachments into the chat context — that's AD-793a forward marker (would require attachment-type aware decisions about whether to embed inline vs reference vs render-to-text). The pin list is metadata that the Captain + agent can reference, not auto-context.

---

## Section 5 — Sidebar wiring (replace Wave 195's placeholder)

Wave 195's `ThreadSidebar.tsx` rendered a Projects section header with body "Coming with AD-793." Replace that:

1. **Hydration:** on mount, fire `GET /api/projects` in parallel with the existing `GET /api/threads`. Both go into store. New store slice: `projects: Map<string, ProjectView>` + `hydrateProjects(...)` action.

2. **Projects section rendering:**
   - Each project renders as an expandable row: chevron + project name + thread count (e.g., "ProbOS Development (4)").
   - Click chevron to expand/collapse; persisted to localStorage under `probos.sidebar.projects.expanded` (JSON dict keyed by project_id).
   - Expanded: list threads where `thread.project_id == project.id`, sorted by `last_active_at desc`. Same `<ThreadRow>` component as Recents.
   - Empty project (no threads): show "No threads yet" dim line.

3. **Recents section filter:** existing Recents filter must exclude threads with `project_id != null` (those belong to a project section). Pinned section is unaffected — pinning a thread overrides project grouping (pinned threads always render in Pinned regardless of project membership). Confirmed match to Claude's behavior; document the precedent in the component comment.

4. **Project right-click menu** (parallel to ThreadRow's menu):
   - Rename (PATCH name)
   - Edit description (opens a modal with a textarea + Save; PATCH description)
   - Archive (PATCH archived=true; project disappears from sidebar)
   - Delete (confirmation modal: "Delete project? Threads will be [unparented OR deleted].") — radio choice between unparent (default) and cascade. DELETE with `?cascade=true|false`.

5. **New project affordance:** a small "+" button on the Projects section header. Click → modal with name + description inputs → POST `/api/projects`. Empty name = button disabled. On success, the new project appears in the sidebar.

6. **Move thread to project:** ThreadRow's existing right-click menu gains a "Move to project…" item. Opens a submenu listing existing projects + "None (unparent)". Selecting a project sends `PATCH /api/threads/{id}` with `{project_id: <id>}`. The thread re-grouping is reactive via the store.

---

## Section 6 — Delete semantics (cascade vs unparent)

The default is **unparent** (set `project_id=NULL` on contained threads, then delete the project row). The Captain's confirmation modal radio defaults to unparent. Cascade requires an explicit click + a second confirmation ("This will permanently delete N threads and their messages. Continue?").

Episodes and AD-541b anchors are preserved in BOTH paths (matches AD-791a Section 11 acceptance #7 — episode immutability across thread/project deletion).

---

## Section 7 — Moving threads between projects

`PATCH /api/threads/{id}` with `{project_id: <new_id_or_null>}` already works (Wave 193 / AD-791a). v1 ships nothing new on the backend; this section exists to document that the sidebar UI calls it and to make explicit that:

- Setting `project_id=null` unparents the thread → it returns to the Recents section.
- Moving between projects: thread immediately re-groups under the new project; sidebar updates reactively.
- Moving a pinned thread into a project: thread STAYS in Pinned section (pinning > project grouping). Documented above.

No new endpoint; no new test (the PATCH endpoint's project_id semantics were covered by Wave 193 tests).

---

## Section 8 — Tests

### Pytest (≥12 tests — 12 named below)

1. `test_project_crud.py::test_create_project_happy_path` — POST returns project dict directly, includes generated id, `last_active_at == created_at`.
2. `test_project_crud.py::test_get_project_missing_returns_404`
3. `test_project_crud.py::test_patch_project_name_only` — PATCH semantics (other fields unchanged).
4. `test_project_crud.py::test_delete_project_unparent_default` — assert threads' project_id becomes NULL.
5. `test_project_crud.py::test_delete_project_cascade_removes_threads_and_messages` — assert threads + messages gone; episodes preserved.
6. `test_project_crud.py::test_list_projects_orders_by_last_active`
7. `test_project_pin.py::test_pin_attachment_validates_sha_exists` — 400 when SHA absent from AttachmentStore. Awaits `exists()`.
8. `test_project_pin.py::test_pin_unpin_idempotent` — double-pin / unpin-missing → no error, no duplicate.
9. `test_project_context_injection.py::test_project_description_prepended_to_chat` — create project + thread; send message; assert agent.act received the project preamble in message_text.
10. `test_project_context_injection.py::test_no_preamble_when_project_id_null`
11. `test_project_context_injection.py::test_empty_description_omitted` — project with `description=""` does not inject `--- Project: ...---` block.
12. `test_project_context_injection.py::test_ordering_visual_project_recall_user` — **substring-index assertion** to guard against future regressions that swap recall/project/visual order. Specifically: assert `mt.index(visual_marker) < mt.index(project_marker) < mt.index(recall_marker) < mt.index(user_marker)`. Without this test, future changes to agents.py could silently reorder the chain (the spec's R3 defect is exactly this regression class).
13. `test_project_touch.py::test_message_append_in_project_thread_bumps_last_active` — thread in project receives message via POST `/api/threads/{id}/messages` → project.last_active_at updates. Test invokes the **router endpoint** (not `ChatThreadStore.append_message` directly) so the touch call-site at the router layer is exercised.

### Vitest (≥4)

1. `ThreadSidebar.projects-section.test.tsx` — projects render with thread counts; chevron toggles expand state; localStorage persists.
2. `ThreadSidebar.new-project.test.tsx` — "+" button → modal → POST → new project in store; name-empty disables submit.
3. `ThreadSidebar.move-thread-to-project.test.tsx` — right-click ThreadRow → "Move to project…" → submenu → PATCH thread.project_id → thread re-groups.
4. `ThreadSidebar.delete-project-modal.test.tsx` — DELETE confirmation modal with unparent/cascade radio; default unparent; cascade requires second confirmation.

---

## Section 9 — Non-goals (Do NOT build)

- ❌ Auto-injecting pinned attachments into chat context (AD-793a forward marker).
- ❌ Per-attachment pin metadata (notes, ordering, type tags) — JSON list of SHAs is sufficient for v1.
- ❌ Many-to-many `project_attachments` junction table (AD-793b forward marker — defer until pin count or query complexity demands it).
- ❌ Project sharing / collaboration / export (AD-793c forward marker).
- ❌ Per-project LLM tier override (e.g., "always use deep for this project"). Threads already have per-thread `model` field from AD-791a; project-level inheritance is AD-793d forward marker.
- ❌ Project-level personality override (parallel to thread.personality_override AD-809). Forward marker AD-793e.
- ❌ Pinned attachments rendering in the sidebar. v1 stores them; UI is forward marker AD-793f.
- ❌ Schema or API changes to AttachmentStore. We CALL `await store.exists(sha)`; we do not modify the store.
- ❌ Changes to `chat_threads` schema (the `project_id` column already exists from AD-791a).

---

## Section 10 — Acceptance criteria

1. New `projects` table created additively in `threads/__init__.py` `_SCHEMA`. `CREATE TABLE IF NOT EXISTS` ensures idempotent migration on warm boot.
2. `Project` dataclass + `ProjectStore` (or `ChatThreadStore` extension) implements CRUD + pin/unpin + touch + delete-with-cascade-or-unparent.
3. New `src/probos/routers/projects.py` exposes GET/POST/PATCH/DELETE `/api/projects` + `/api/projects/{id}/pin` + `/api/projects/{id}/unpin`. Mounted in startup wiring next to `routers/threads`.
4. Response shapes: single-project endpoints return `Project.to_dict()` DIRECTLY (not wrapped); LIST returns `{"projects": [...]}`.
5. Chat flow (`routers/agents.py`) injects project description as preamble BELOW visual context, ABOVE targeted recall and user message. Empty descriptions are silently omitted. Missing/deleted projects log at debug and degrade silently.
6. `message_text` order: visual (AD-733a) → project preamble (AD-793) → targeted recall (AD-725) → user message.
7. Thread-message-append in a thread with `project_id` bumps `project.last_active_at`.
8. Delete project defaults to unparent (`cascade=false`); cascade requires explicit query param + double-confirmation in the UI. Episodes/anchors preserved in both paths.
9. Sidebar replaces Wave 195's "Coming with AD-793" placeholder with a real Projects section: expandable rows, thread grouping, right-click menu, "+" button, "Move to project…" affordance.
10. Recents section filters out threads with non-null `project_id` (they appear under their project instead). Pinned section is unaffected (pinning overrides project grouping).
11. ≥8 pytest + ≥4 vitest added. All existing tests still pass. `npm run build` clean per BF-279.
12. Trackers updated: PROGRESS.md prepends a Wave 196 entry; roadmap.md marks AD-793 SHIPPED Wave 196; GH issue #717 closed with commit hash + acceptance summary.
13. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 11 — File touchpoints

| File | Change |
|---|---|
| `src/probos/threads/__init__.py` | EXTEND. Add `projects` table to `_SCHEMA`. Add `Project` dataclass. Add `ProjectStore` class with CRUD + pin + delete-with-cascade-or-unparent + touch. |
| `src/probos/routers/projects.py` | NEW. ~250 LOC; mirrors `routers/threads.py` shape. |
| `src/probos/runtime.py` | MODIFY (~L444). Wire `self.project_store = ProjectStore(db_path)` next to the existing `self.chat_thread_store = ChatThreadStore(...)` line. Same module that wires `artifact_store`, `task_session_store`, etc. **NOT** `startup/finalize.py` — chat_thread_store does not live there. |
| (Router registration) | MODIFY. Register the `routers/projects.py` router next to where `routers/threads.py` is included in the FastAPI app factory. Builder identifies the include site by grepping for `include_router.*threads`. |
| `src/probos/routers/agents.py` | MODIFY. Insert project preamble BETWEEN the existing recall prepend (L2073-76) and visual prepend (L2078+) per Section 4 above. ~20 lines added. |
| `src/probos/routers/threads.py` | MODIFY. In the POST `/api/threads/{id}/messages` handler, after a successful `chat_thread_store.append_message(...)`, look up the thread's `project_id`; if non-null and `runtime.project_store` is wired, call `project_store.touch(project_id)`. Honest-degrade on failure (debug log + continue). |
| `ui/src/store/useStore.ts` | EXTEND. Add `projects: Map<string, ProjectView>` slice + `hydrateProjects`, `setProject`, `removeProject` actions. Add `ProjectView` type definition (mirrors backend `Project.to_dict()`). |
| `ui/src/components/sidebar/ThreadSidebar.tsx` | MODIFY. Replace placeholder Projects section (the line containing literal text "Coming with AD-793.") with real expandable rendering. Add hydration of `/api/projects` on mount. Add **client-side** Recents-filter to exclude threads with non-null `project_id` (no backend `recents()` filter change — per architect Rec5). |
| `ui/src/components/sidebar/ProjectRow.tsx` | NEW. Expandable row component (chevron + name + count + nested threads). SVG icons only (HXI #3). |
| `ui/src/components/sidebar/NewProjectModal.tsx` | NEW. Name + description inputs + POST. |
| `ui/src/components/sidebar/ProjectContextMenu.tsx` | NEW (or extend existing menu). Rename / Edit description / Archive / Delete-with-cascade-radio. |
| `ui/src/components/sidebar/MoveToProjectMenu.tsx` | NEW. Submenu under ThreadRow's right-click "Move to project…" item. |
| `ui/src/components/sidebar/threadApi.ts` | EXTEND (Wave 195). Add `projectApi.ts` sibling OR inline project fetch wrappers — Builder picks. |
| `ui/src/__tests__/ThreadSidebar.render.test.tsx` | MODIFY (Wave 195 carry-over). Line 37 asserts the literal placeholder text "Coming with AD-793." — this assertion BREAKS the moment the placeholder is replaced. Either replace with an assertion about the real Projects section header, or delete this assertion and let the new `ThreadSidebar.projects-section.test.tsx` carry the coverage. |
| `tests/test_project_crud.py` | NEW pytest. ≥6 tests. |
| `tests/test_project_pin.py` | NEW pytest. ≥2 tests. |
| `tests/test_project_context_injection.py` | NEW pytest. ≥4 tests (includes the ordering substring-index test #12). |
| `tests/test_project_touch.py` | NEW pytest. ≥1 test. |
| `ui/src/__tests__/ThreadSidebar.projects-section.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.new-project.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.move-thread-to-project.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ThreadSidebar.delete-project-modal.test.tsx` | NEW vitest. |

---

## Section 12 — Estimated scope

~600-800 LOC raw (backend + UI + tests). ~17 files touched. One Builder commit.

---

## Section 13 — Forward markers (new)

- **AD-793a** — auto-inject pinned attachments into chat context (attachment-type aware decisions: inline-image vs file-ref vs render-to-text).
- **AD-793b** — many-to-many `project_attachments` junction table for per-pin metadata (notes, ordering, type tags).
- **AD-793c** — project sharing / collaboration / export.
- **AD-793d** — per-project LLM tier override (e.g., "always use deep for this project") — inheriting into contained threads.
- **AD-793e** — per-project personality override (parallel to thread.personality_override AD-809).
- **AD-793f** — pinned attachments rendering in the sidebar (file chips below the project header).

---

## Section 14 — Verify-first audit checklist (Builder pre-flight)

```
grep -n "project_id" src/probos/threads/__init__.py
    → Expected: column at L45, index at L54, dataclass field at L79, to_dict at L101.

grep -n "project_id" src/probos/routers/threads.py
    → Expected: PATCH + create + list-filter all support project_id (AD-791a).

grep -n "^def _get_attachment_store\|async def exists" src/probos/routers/chat.py src/probos/attachments/store.py src/probos/attachments/filesystem_store.py
    → Expected:
        routers/chat.py: def _get_attachment_store(runtime) -> FilesystemAttachmentStore
        attachments/store.py:60 — async def exists(self, content_hash) -> bool
        attachments/filesystem_store.py:271 — async def exists
      The pin endpoint MUST be `async def` and `await` the call.

grep -n "targeted_recall_block\|message_text = f" src/probos/routers/agents.py
    → Expected:
        L1826  targeted_recall_block: str | None = None  (assignment site)
        L2073-76  recall prepend (FIRST in code → ends up BELOW visual)
        L2078+  AD-733a visual prepend (LAST in code → ends up ON TOP)
      Builder inserts the project preamble BETWEEN L2076 and L2078.
      Final on-the-wire order MUST be: visual → project → recall → user.

grep -n "chat_thread_store\|ChatThreadStore" src/probos/runtime.py
    → Expected: self.chat_thread_store = ChatThreadStore(...) around L444.
      Project store wires next to it.
      NOT in startup/finalize.py (zero matches there — architect-verified).

grep -n "include_router.*threads\|threads_router" src/probos/
    → Find where the threads router is mounted on the FastAPI app.
      Mount projects router at the same site.

read src/probos/routers/threads.py around the POST /api/threads/{id}/messages handler
    → Identify the exact line after successful append_message where the
      project_store.touch(project_id) call inserts. Builder must NOT modify
      threads/__init__.py for this — touch is router-layer only.

grep -n "Coming with AD-793" ui/
    → Expected:
        ThreadSidebar.tsx:~819 — placeholder string present (Wave 195)
        __tests__/ThreadSidebar.render.test.tsx:37 — test asserting it.
      Both must be updated (test assertion changes OR is removed).

grep -n "hydrateChatThreads\|chatThreads:" ui/src/store/useStore.ts
    → Expected: Map + hydrate + per-entry update pattern at L297-410, L603-606, L1034-1052.
      Projects slice mirrors this shape exactly.

grep -n "BEGIN IMMEDIATE" src/probos/threads/__init__.py
    → Expected: race-safety pattern. ProjectStore delete + pin operations reuse it.

read src/probos/routers/threads.py:60-180
    → Re-confirm response-shape precedents:
        POST /api/threads → thread.to_dict() DIRECTLY (L113-115)
        LIST → {threads: [...]}  (L82)
        /search → {query, results}  (L93-94)
        /recents → {recents: [...]}  (L101)
      Match these shapes exactly for the projects router.
```

If any of these don't match, stop and report.

---

## Section 15 — Open questions

None. Delimiter framing for description injection (originally drafted as an open question) locked into Section 4 per architect Rec4: keep `--- Project: ... ---` / `--- End Project Context ---` framing for BF-294 provenance reasons.
