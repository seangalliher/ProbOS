# AD-926 — Inputs folder: surface a task room's attached files as a read-only Input pane

**Epic:** Task Workspace Rooms (AD-925 → AD-929), roadmap `docs/development/roadmap.md` ("Task Workspace Rooms northstar").
**Status:** Ready to build · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-925 (auto-create task-linked room; sets `chat_threads.task_id`), AD-916 (chat message attachments), AD-720 (`AttachmentStore`).
**Highest committed AD at authoring:** **AD-925** (`ebcb0eca`, local-only — 2 commits ahead of `origin/main`; NOT pushed).
**Estimated tests:** ~10 pytest (`tests/test_ad926_inputs_folder.py`) + ~3 vitest (`ui/src/components/inputs/__tests__/InputsList.test.tsx`).

---

## 1. Problem

AD-925 makes a task fan-out auto-create **one** group chat (a workspace room) with `chat_threads.task_id` set. The epic's Cowork model gives that room an **Input folder** (the files the crew use/process) and an **Output folder** (the artifacts they produce). AD-927 mounts the existing `ArtifactDrawer` as the Output pane. **AD-926 ships the Inputs surface:** a read-only backend endpoint that lists the files attached to a task room, plus a thin UI list so they're visible.

### The crux — where do "files attached to a task" live today? (VERIFIED)

There is **no native task-attachment slot.** The `WorkItem` dataclass (`src/probos/workforce.py:581`) carries only a generic `metadata: dict[str, Any]` (`:605`) — there is **no** `attachments` / `attachment_ids` / `content_hash` field (grep of `workforce.py` for those terms returns zero matches). So a task has nowhere to record "these files were attached to me" today.

What **does** exist and carries real file refs today:

- **AD-916 message attachments** (VERIFIED in `tests/test_ad916_chat_file_sharing.py:242,379`): a chat message persists `ChatThreadMessage.metadata["attachments"] = [{"content_hash": <sha>, "mime": <mime>}]`. The bytes live in the content-addressable `AttachmentStore` (AD-720) and are served by the existing `GET /api/chat/attachments/{content_hash}` (`src/probos/routers/chat.py:985`).
- **The room ↔ task link** (AD-925): a task room is a `ChatThread` with `task_id` set (`src/probos/threads/__init__.py:95`). Given a thread you can read `thread.task_id` and dereference the parent via `await runtime.work_item_store.get_work_item(task_id)` (`workforce.py:1076`, **async**).

### Decision (honest minimal path)

v1 surfaces **two sources, both scoped to a task room (thread with `task_id` set)**:

1. **Authoritative task-level inputs — a new additive convention:** `WorkItem.metadata["input_attachments"] = [{"content_hash", "mime", "filename"}]`. This is the faithful "files attached to the task / parent work-item." It is purely additive — `WorkItem.metadata` is already a free `dict`, already serialized by `to_dict()` (`workforce.py:632`); **no schema change, no migration.** Read via `get_work_item(task_id)`. **Population is deferred** (a real task-creation/seed flow that writes this key is a forward marker — see §6); v1 surfaces whatever is present and defines the contract.
2. **Real-today source — the room's message attachments (AD-916):** aggregate `metadata["attachments"]` across the room's messages. This makes the endpoint return live data the day it ships — when the Captain (or an agent) attaches a file to a message in the task room, it appears in the Inputs pane.

Both are merged, **de-duplicated by `content_hash`** (task-level wins), each tagged with a `source` field. Read-only — inputs are context, never edited in the room. The byte/download path reuses the existing `GET /api/chat/attachments/{content_hash}`; **no new blob store, no new content endpoint.**

This is faithful to the roadmap wording ("surface the files attached to the task / parent work-item … reuse AD-916 message attachments + content-addressable `AttachmentStore`") while being honest that the work-item slot is a defined-but-dormant seam until population lands.

---

## 2. Solution overview

| Piece | File | Change |
|---|---|---|
| Inputs read endpoint | `src/probos/routers/threads.py` | NEW `GET /api/threads/{thread_id}/inputs` + a private `_collect_task_inputs(...)` helper |
| UI fetch wrapper | `ui/src/components/inputs/inputsApi.ts` (NEW) | `fetchThreadInputs(threadId)` mirroring `artifactApi.ts` |
| UI thin list | `ui/src/components/inputs/InputsList.tsx` (NEW) | read-only list mirroring `ArtifactList.tsx` (stroke-SVG icons, empty state) |
| Backend tests | `tests/test_ad926_inputs_folder.py` (NEW) | ~10 pytest, BF-287 real fixtures |
| UI tests | `ui/src/components/inputs/__tests__/InputsList.test.tsx` (NEW) | ~3 vitest incl. no-emoji guard |

No production code besides the one endpoint + helper and the two new UI files. The `input_attachments` convention is introduced **by this AD** (the spec IS the migration — do not flag it as a missing field).

---

## 3. Backend — `GET /api/threads/{thread_id}/inputs`

Add to `src/probos/routers/threads.py`. Place the helper near the top (after `_get_store`) and the route after the existing `/{id}/messages` routes. Use the existing module imports (`APIRouter`, `Depends`, `HTTPException`, `get_runtime`, `logger`, `Any`).

### 3a. Helper

```python
async def _collect_task_inputs(runtime: Any, thread: Any) -> list[dict]:
    """AD-926: assemble the read-only Input list for a task room.

    Two sources, both scoped to a room whose ``thread.task_id`` is set:

      1. Authoritative task-level inputs — the additive convention
         ``WorkItem.metadata["input_attachments"] = [{content_hash, mime,
         filename}]`` (``source="task"``). Population is deferred (AD-926
         defines the contract; a future task-seed flow writes it).
      2. Real-today — AD-916 message attachments carried on the room's
         messages, ``metadata["attachments"] = [{content_hash, mime}]``
         (``source="message"``).

    Merged and de-duplicated by ``content_hash`` (task-level wins, then
    message arrival order). ``size`` is best-effort from the
    ``AttachmentStore``; a missing blob or absent store degrades to
    ``size=None`` (Tier-2 log-and-degrade) and never raises.
    """
    task_id = getattr(thread, "task_id", None)
    if not task_id:
        return []  # not a task room — no inputs

    ordered: list[dict] = []
    seen: set[str] = set()

    def _add(ref: dict, source: str) -> None:
        ch = (ref or {}).get("content_hash")
        if not ch or ch in seen:
            return
        seen.add(ch)
        ordered.append({
            "content_hash": ch,
            "mime": ref.get("mime") or "application/octet-stream",
            "filename": ref.get("filename"),  # None for AD-916 message refs
            "size": None,
            "source": source,
        })

    # (1) authoritative task-level inputs
    work_item_store = getattr(runtime, "work_item_store", None)
    if work_item_store is not None:
        try:
            wi = await work_item_store.get_work_item(task_id)
        except Exception:  # pragma: no cover - defensive
            logger.warning(
                "AD-926: get_work_item(%s) failed; surfacing message "
                "attachments only", task_id, exc_info=True,
            )
            wi = None
        if wi is not None:
            for ref in (getattr(wi, "metadata", {}) or {}).get("input_attachments", []) or []:
                if isinstance(ref, dict):
                    _add(ref, "task")

    # (2) real-today: AD-916 message attachments in the room
    store = _get_store(runtime)
    for msg in store.list_messages(thread.id, limit=500):
        for ref in (getattr(msg, "metadata", {}) or {}).get("attachments", []) or []:
            if isinstance(ref, dict):
                _add(ref, "message")

    # best-effort size enrichment via the content-addressable store
    attachment_store = getattr(runtime, "attachment_store", None)
    if attachment_store is not None:
        for entry in ordered:
            try:
                entry["size"] = await attachment_store.size(entry["content_hash"])
            except FileNotFoundError:
                entry["size"] = None  # ref present, bytes not stored yet
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    "AD-926: size(%s) failed; leaving size=None",
                    entry["content_hash"], exc_info=True,
                )
                entry["size"] = None
    return ordered
```

### 3b. Route

```python
@router.get("/{thread_id}/inputs")
async def list_thread_inputs(
    thread_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    """AD-926: read-only Input folder for a task workspace room.

    Returns the files attached to the room's task (the AD-916 message
    attachments + the ``WorkItem.metadata["input_attachments"]``
    convention), de-duplicated by ``content_hash``. A thread that is not
    a task room (``task_id`` unset) returns an empty list. Bytes are
    fetched via the existing ``GET /api/chat/attachments/{content_hash}``.
    """
    store = _get_store(runtime)
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    inputs = await _collect_task_inputs(runtime, thread)
    return {
        "thread_id": thread_id,
        "task_id": getattr(thread, "task_id", None),
        "inputs": inputs,
    }
```

Response shape (each input): `{content_hash, mime, filename | null, size | null, source}` where `source ∈ {"task","message"}`.

---

## 4. UI — thin read-only Inputs list (self-contained drop-in)

Mirror the artifacts pane (`ui/src/components/artifacts/`). **Mounting into the room / 3-pane surface is AD-929 — do NOT wire it into `GroupChatHeader`, the canvas, or any room view here.** Ship a self-contained, tested component + fetch wrapper.

### 4a. `ui/src/components/inputs/inputsApi.ts` (NEW)

Mirror `artifactApi.ts` (fetch + honest-degrade throw on non-ok). Minimal:

```ts
/**
 * AD-926: fetch wrapper for the task-room Inputs pane.
 *
 * Endpoint:  GET /api/threads/{thread_id}/inputs
 *   -> { thread_id, task_id, inputs: TaskInput[] }
 * Bytes are fetched via the existing GET /api/chat/attachments/{content_hash}.
 * Honest-degrade: non-ok responses throw so the caller's try/catch shows a
 * toast without crashing the pane.
 */
export interface TaskInput {
  content_hash: string;
  mime: string;
  filename: string | null;
  size: number | null;
  source: 'task' | 'message';
}

export async function fetchThreadInputs(threadId: string): Promise<TaskInput[]> {
  const res = await fetch(`/api/threads/${encodeURIComponent(threadId)}/inputs`);
  if (!res.ok) {
    throw new Error(`fetchThreadInputs: ${res.status}`);
  }
  const body = await res.json();
  return Array.isArray(body.inputs) ? body.inputs : [];
}

export function attachmentUrl(contentHash: string): string {
  return `/api/chat/attachments/${encodeURIComponent(contentHash)}`;
}
```

### 4b. `ui/src/components/inputs/InputsList.tsx` (NEW)

Mirror `ArtifactList.tsx`: a `mimeIcon(mime)` that returns **stroke-based inline SVG only** (HXI Design Principle #3 — no emoji; `strokeWidth: 1.5`, `strokeLinecap: 'round'`), an empty state, one `<a>`/`<button>` row per input. Each row is a download/open link to `attachmentUrl(content_hash)` (read-only — no edit/delete affordance). Show filename (or a shortened `content_hash` when `filename` is null) + the mime icon + optional size. Requirements:

- `data-testid="inputs-list"` on the container, `data-testid="inputs-list-empty"` on the empty state, `data-testid={`input-row-${content_hash}`}` per row.
- Empty state text: `No inputs yet.`
- Reuse the artifact palette constants (`AMBER = '#f0b060'`, dim grey) and the same stroke-SVG glyph style — copy `mimeIcon` from `ArtifactList.tsx` (image / text / code / generic). **No emoji anywhere.**
- Props: `{ inputs: TaskInput[] }`. Keep it presentational (no data fetching inside — the caller passes `inputs`); this keeps it trivially testable and lets AD-929 own fetching + layout.

---

## 5. Tests

### 5a. Backend — `tests/test_ad926_inputs_folder.py` (NEW, ~10 pytest, BF-287 discipline)

Use **real** substrate (no `MagicMock` at the substrate boundary — BF-287/BF-326): a real `ChatThreadStore` (`from probos.threads import ChatThreadStore`), a real `WorkItemStore` (`from probos.workforce import WorkItemStore`), and a real `FilesystemAttachmentStore` (`from probos.attachments import FilesystemAttachmentStore`) rooted under `tmp_path`. Build a `runtime` stub as a `SimpleNamespace` exposing `chat_thread_store`, `work_item_store`, and `attachment_store` (set the real stores as attributes — the production `attachment_store` is a `@property`, but the route reads it via `getattr`, so a plain attribute on the stub is correct). Invoke the endpoint by **awaiting `list_thread_inputs(thread_id, runtime=stub)` directly** (pass `runtime=` explicitly; the `Depends` default only activates under the app). TestClient is an acceptable alternative if preferred, but the direct call avoids a full `create_app` boot.

Helper: write a few blobs into the attachment store with real sha256 content hashes (`hashlib.sha256(b"...").hexdigest()`), e.g. `await store.write(sha, blob, "image/png", origin="chat_attachment")`.

Cases:

1. **Work-item inputs (authoritative):** task room (`task_id` set) whose parent `WorkItem.metadata["input_attachments"] = [{content_hash, mime, filename}]` → returned with `source="task"`, correct `filename`, and `size` equal to the stored blob length.
2. **Message inputs (real-today):** task room with a message carrying `metadata["attachments"] = [{content_hash, mime}]` (AD-916) → returned with `source="message"`, `filename=None`, correct `size`.
3. **Merge + de-dupe:** same `content_hash` present in both the work-item convention and a message → appears **once**, `source="task"` (task wins), and a distinct message-only ref also appears after it (order: task-level first, then message arrival order).
4. **No task_id → empty:** a thread with `task_id=None` (e.g. a plain 1:1 thread) → `{"task_id": None, "inputs": []}` even if its messages carry attachments.
5. **Task room, no inputs anywhere → empty:** `task_id` set, no `input_attachments`, no message attachments → `inputs == []`.
6. **Unknown blob → honest-degrade size:** a ref whose bytes are NOT in the store → `size=None`, no exception.
7. **Missing thread → 404:** unknown `thread_id` raises `HTTPException(status_code=404)`.
8. **`work_item_store=None`:** runtime stub without a work-item store → message inputs still returned, no crash (work-item source skipped).
9. **`attachment_store=None`:** runtime stub without an attachment store → entries returned with `size=None`, no crash.
10. **Metadata shape exact:** every returned entry has exactly the keys `{content_hash, mime, filename, size, source}` (assert `set(entry) == {...}`).

### 5b. UI — `ui/src/components/inputs/__tests__/InputsList.test.tsx` (NEW, ~3 vitest)

Run with `cd ui; npx vitest run`. Mirror the `ArtifactList`/`IntentSurface` test style.

1. **Renders rows:** given two `TaskInput`s, renders a row per `content_hash` (`getByTestId('inputs-list')`, two `input-row-*`), shows filename text, and each row links to `/api/chat/attachments/{content_hash}`.
2. **Empty state:** `inputs=[]` → `getByTestId('inputs-list-empty')` with text `No inputs yet.`.
3. **No-emoji guard (HXI #3):** `const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;` then `expect(container.textContent || '').not.toMatch(EMOJI_RE);` after rendering rows (icons are stroke-SVG only).

---

## 6. What this does NOT change (explicit scope guards)

- **No write/edit/delete/upload of inputs.** The pane is read-only context. No mutation endpoint, no UI edit/delete affordance.
- **No population of `WorkItem.metadata["input_attachments"]`.** v1 defines and reads the convention; wiring a real task-creation/seed flow that writes it is a **forward marker** (AD-926a or a later AD). The work-item source is a defined-but-dormant seam until then.
- **No Output pane / artifacts** — that is **AD-927** (mount `ArtifactDrawer` + the `[ARTIFACT …]` action tag).
- **No unified 3-pane workspace view and no mounting into the room/canvas/`GroupChatHeader`** — that is **AD-929**. Ship the `InputsList` as a self-contained, tested drop-in only.
- **No new blob store and no new content/download endpoint** — reuse `GET /api/chat/attachments/{content_hash}` (chat.py:985) for bytes.
- **No change to the `AttachmentStore` Protocol** and **no schema change to `WorkItem`** — `input_attachments` rides the existing free `metadata` dict.
- **No change to AD-925** (auto-create) or the `create_group_chat` path.

---

## 7. Tracking (same commit)

- **`PROGRESS.md`** — prepend an `**AD-926 shipped …**` entry **above** the current AD-925 entry at line 3.
- **`docs/development/roadmap.md`** — flip the AD-926 row in the Task Workspace table to `… — SHIPPED <date> gate-verified`.
- **`DECISIONS.md`** — append the AD-926 entry (one reason line: read-only Inputs endpoint + `input_attachments` additive convention + AD-916 message-attachment aggregation; population deferred).
- One commit: `AD-926: inputs folder — read-only task-room Input pane`.

---

## 8. Acceptance criteria

- `GET /api/threads/{thread_id}/inputs` returns `{thread_id, task_id, inputs:[{content_hash, mime, filename, size, source}]}`; task room → real inputs; non-task thread or empty → `inputs: []`; missing thread → 404.
- De-dupe by `content_hash` with task-level precedence; honest-degrade `size=None` on missing blob / absent store; never raises into the response.
- `InputsList.tsx` + `inputsApi.ts` ship as a self-contained, no-emoji, read-only list; rows link to `/api/chat/attachments/{content_hash}`.
- NEW `tests/test_ad926_inputs_folder.py` (~10, real `ChatThreadStore` + `WorkItemStore` + `FilesystemAttachmentStore`, BF-287) green.
- NEW `ui/src/components/inputs/__tests__/InputsList.test.tsx` (~3, incl. no-emoji guard) green; `cd ui; npx vitest run` + `npm run build` pass.
- Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad926_inputs_folder.py -q -n 0` then a blast-radius `-k "thread or chat or inputs or workforce or attachment"`.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Verified Against Codebase (2026-06-08)

```
# WorkItem has NO native attachment slot — only a generic metadata dict
grep -n "class WorkItem\b|metadata: dict" src/probos/workforce.py
  581: class WorkItem:
  605:     metadata: dict[str, Any] = field(default_factory=dict)
  632:     "metadata": self.metadata,            # to_dict serializes it (additive convention is free)
grep -n "attachment|content_hash|input_attachments" src/probos/workforce.py
  (no matches — confirms there is no task-attachment field today)

# get_work_item is async; returns WorkItem | None
grep -n "async def get_work_item" src/probos/workforce.py
  1076:     async def get_work_item(self, work_item_id: str) -> WorkItem | None:

# runtime stores — work_item_store may be None; attachment_store is a @property
grep -n "work_item_store|attachment_store|chat_thread_store" src/probos/runtime.py
  268:     work_item_store: WorkItemStore | None
  450:     self.chat_thread_store = ChatThreadStore(
  752:     self.work_item_store: WorkItemStore | None = None
  1482:    def attachment_store(self) -> Any:     # @property -> _get_attachment_store(self)

# AD-916 message attachment shape (VERIFIED via the AD-916 test)
grep -n "attachments" tests/test_ad916_chat_file_sharing.py
  242:  assert cap["metadata"]["attachments"] == [{"content_hash": png_sha, "mime": "image/png"}]
  379:  assert cap_row.metadata["attachments"] == [{"content_hash": txt_sha, "mime": "text/plain"}]

# ChatThread.task_id + ChatThreadMessage.metadata + sync store methods
grep -n "class ChatThread|task_id|class ChatThreadMessage|def get_thread|def list_messages|def list_threads" src/probos/threads/__init__.py
  88:  class ChatThread:
  95:      task_id: str | None = None
  131: class ChatThreadMessage:
  138:     metadata: dict = field(default_factory=dict)
  237: def get_thread(self, thread_id: str) -> ChatThread | None:        # sync
  244: def list_threads(self, *, include_archived, project_id, task_id, limit)  # AD-925 task_id filter present
  741: def list_messages(self, thread_id, *, limit=200, before=None)    # sync

# threads router — mount point, store accessor, deps
grep -n "APIRouter\(prefix|def _get_store|chat_thread_store|messages" src/probos/routers/threads.py
  28:  router = APIRouter(prefix="/api/threads", tags=["threads"])
  31:  store = getattr(runtime, "chat_thread_store", None)   # _get_store
  212: async def list_messages(...)                          # existing /{id}/messages

# AttachmentStore: size async; FilesystemAttachmentStore concrete (mime_for exists, used by chat.py)
grep -n "async def size|async def write|async def read" src/probos/attachments/store.py
  (Protocol: write/read/exists/get_path/size/unlink/list_by_origin/total_size_bytes — all async; NO mime_for in Protocol)
grep -n "def __init__|def mime_for|async def size" src/probos/attachments/filesystem_store.py
  92:   def __init__(self, root: Path) -> None:
  282:  async def size(self, content_hash: str) -> int:        # raises FileNotFoundError if absent
  359:  async def mime_for(self, content_hash: str) -> str | None:

# byte-fetch endpoint reused for download (no new content endpoint)
grep -n "chat/attachments/\{content_hash\}" src/probos/routers/chat.py
  985:  @router.get("/chat/attachments/{content_hash}")

# artifacts pattern mirrored (parallel surface; AD-927 mounts the drawer)
grep -n "prefix=\"/api/artifacts\"|getattr(runtime, \"artifact_store\"|thread/\{thread_id\}" src/probos/routers/artifacts.py
  12:  router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])
  16:  store = getattr(runtime, "artifact_store", None)
  46:  @router.get("/thread/{thread_id}")  -> {"thread_id":..., "artifacts":[...]}

# UI patterns to mirror + no-emoji guard
grep -n "fetchThreadArtifacts|mimeIcon|EMOJI_RE" ui/src/components/artifacts/artifactApi.ts ui/src/components/artifacts/ArtifactList.tsx ui/src/__tests__/IntentSurface.imagePaste.test.tsx
  artifactApi.ts:16  export async function fetchThreadArtifacts(... fetch + throw on !ok
  ArtifactList.tsx:16 function mimeIcon(mime): stroke-SVG glyphs only (no emoji)
  IntentSurface.imagePaste.test.tsx:8  const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

# collision check — clean (the only /inputs is the SEPARATE ConsultationWorkspace filesystem path, not a route)
grep -rn "input_attachments|/inputs|fetchThreadInputs|def list_inputs" src tests ui
  src/probos/consultation/workspace.py:145  f"{self._root}/inputs/{safe}"   # unrelated FS substrate (not bridged)
  (no route, convention, or UI symbol collisions)
```
