# AD-926a — Task-level multi-file upload (the population path AD-926 deferred)

**Status:** Ready to build · **Depends on:** AD-926 (inputs READ endpoint + `input_attachments` convention), AD-929 (Files rail), AD-916/AD-720a (chat attachment uploader) · **Estimated tests:** +13 (≈10 pytest + ≈8 Vitest across 2 files)

**One-line summary.** Let the Captain attach **one OR MORE** files to a task (work item) in a single action; each file is validated + stored once in the content-addressable `AttachmentStore` (sha256) via the **reused** chat uploader, and a ref `{content_hash, mime, filename}` is appended to the parent `WorkItem.metadata["input_attachments"]` — so the files immediately surface as the task room's **Inputs** via the **existing** AD-926 `GET /api/threads/{id}/inputs` endpoint and the AD-929 Files rail.

---

## Problem

AD-926 shipped the **READ** half of the task Inputs folder. [`_collect_task_inputs`](../src/probos/routers/threads.py#L38) returns an honest union of:

1. the **authoritative** convention `WorkItem.metadata["input_attachments"] = [{content_hash, mime, filename}]` (`source="task"`), and
2. AD-916 message attachments (`source="message"`).

But source (1) is a **defined-but-dormant seam** — the convention is documented on the `WorkItem` dataclass ([`workforce.py:606-611`](../src/probos/workforce.py#L606)) and read by the endpoint, yet **nothing writes it**. `git grep AD-926a` returns only two forward-marker comments ([`workforce.py:609`](../src/probos/workforce.py#L609), [`test_ad926_inputs_folder.py:7`](../tests/test_ad926_inputs_folder.py#L7)). The Captain asked: *"I should be able to attach multiple files as context inputs for a task."*

**AD-926a is the missing WRITE/population path.** The read (AD-926) and the display (AD-929 rail) already work — AD-926a is the only missing piece.

---

## Solution overview

| Layer | Change |
|---|---|
| Backend endpoint | NEW `POST /api/work-items/{work_item_id}/inputs` in [`routers/workforce.py`](../src/probos/routers/workforce.py) — multipart `files: list[UploadFile]`, validate+store each via the **reused** `_validate_and_store_attachment`, append refs to `metadata["input_attachments"]` via a **single read-merge-write**, return the updated task-level input list. Honest-degrade per file. |
| UI affordance | WorkspaceFilesRail Inputs section gets a **"+ Attach"** button (`<input type="file" multiple>`), gated on `taskId` present; new `inputsApi.attachTaskInputs(workItemId, files)` posts one multipart request and updates the rail. |
| Convention | Already exists (AD-926). AD-926a **populates** it. No schema change, no migration. |

**This is purely additive.** No change to the `AttachmentStore` Protocol, the `WorkItem` schema, the AD-926 read endpoint, or the AD-925 create path.

---

## Verified against the codebase (2026-06-08, HEAD `2eb8cabd`)

### Reused uploader (do NOT write a parallel uploader)

```
src/probos/routers/chat.py:772
  async def _validate_and_store_attachment(
      runtime, blob, declared_mime, declared_filename, declared_hash_or_None,
      *, origin="chat_attachment") -> tuple[bool, dict[str, Any]]
```
- Defense-in-depth chain: feature gate (`cfg.enabled`) → MIME allowlist (`cfg.allowed_mime_types`) → size cap (`cfg.max_attachment_bytes`) → sha256 → magic-byte `validate_attachment_bytes` → idempotent `store.write(actual_hash, blob, mime, origin=...)`.
- **Success →** `(True, {"attachment_id": sha, "url": "/api/chat/attachments/{sha}", "mime", "size_bytes", "sha256"})`. **Note: the success dict has NO `filename`** — take `filename` from the `UploadFile`.
- **Reject →** `(False, {"status_code": int, "body": {"error": ...}, "headers"?: {...}})`.
- Internally calls [`_get_attachment_store(runtime)`](../src/probos/routers/chat.py#L757) (lazy cache keyed `id(runtime)`, reads `runtime.config.attachments`).

```
src/probos/routers/chat.py:953   @router.post("/chat/attachments/multipart")
  file: UploadFile = File(...);  blob = await file.read()
  -> _validate_and_store_attachment(runtime, blob,
       file.content_type or "application/octet-stream",
       declared_filename=file.filename, declared_hash_or_None=None)
```
This is the exact shape to mirror, generalized to a **list**.

```
src/probos/config.py:2098  class AttachmentsConfig(BaseModel)
  enabled = True · max_attachment_bytes = 10 MiB
  allowed_mime_types includes: image/png, image/jpeg, image/webp, image/gif,
    application/pdf, text/plain, text/markdown, application/json, text/csv
src/probos/attachments/mime.py:152
  text/plain | text/markdown REQUIRE strict-UTF-8 + a filename ending .txt / .md.
  Image MIMEs are magic-byte sniffed (a non-image blob declared image/png is REJECTED).
```
→ **Test design:** happy-path files use `text/plain` with a `.txt` filename and UTF-8 bytes (passes all gates). The "bad file skipped" case uses an oversize blob OR a mime/extension mismatch.

### Origin tag (decision: use the DEFAULT)

```
src/probos/attachments/store.py:16    ATTACHMENT_ORIGINS  (no "task_input")
src/probos/attachments/filesystem_store.py:160  _normalize_origin -> unknown coerces to "chat_attachment"
src/probos/attachments/reaper.py:30   _LRU_EVICTION_ORDER: chat_attachment is LAST (most durable); only perception_frame sweeps by age
```
→ **Do NOT introduce a `task_input` origin** — it would coerce to `chat_attachment` anyway (with a warning). Call `_validate_and_store_attachment` **without an `origin` override**; the default `chat_attachment` is exactly the right semantics for operator-attached inputs (operator intent, never age-reaped, last to LRU-evict). Zero reaper risk, no new code.

### WorkItemStore — the read-merge-write crux

```
src/probos/workforce.py:1081  async def get_work_item(work_item_id) -> WorkItem | None
src/probos/workforce.py:1135  async def update_work_item(work_item_id, **updates) -> WorkItem | None
src/probos/workforce.py:918   _JSON_FIELDS  = {... "metadata" ...}   (json.dumps on write)
                              _IMMUTABLE_FIELDS = {id, created_at, created_by}  (metadata is mutable)
```
**CRITICAL:** `update_work_item(id, metadata=X)` writes a **whole-column REPLACE** (`metadata` is JSON-serialized and the column is overwritten) — there is **no native merge**, and **no `BEGIN IMMEDIATE` / optimistic concurrency**. So the read-merge-write MUST happen at the call site, and must preserve every other `metadata` key plus existing `input_attachments`.

### Where work-item routes live + the AD-926 read shape

```
src/probos/routers/workforce.py:14   router = APIRouter(prefix="/api", tags=["workforce"])
src/probos/routers/workforce.py:103-247  POST /work-items, GET /work-items/{id}, PATCH /work-items/{id},
   POST .../transition, .../assign, .../claim, DELETE /work-items/{id}
   Pattern: `if not runtime.work_item_store: raise HTTPException(503, ...)`;
            `body = await request.json()`; `if not item: raise HTTPException(404, ...)`;
            `broadcast({"type": "work_item_updated", "data": {...}})`
src/probos/routers/workforce.py:8    from fastapi import APIRouter, Depends, HTTPException, Request   # ADD: File, UploadFile
src/probos/routers/workforce.py:10   from probos.routers.deps import get_runtime, get_ws_broadcast
src/probos/routers/threads.py:38     _collect_task_inputs reads wi.metadata["input_attachments"]
                                      refs as {content_hash, mime, filename}; source="task"
src/probos/routers/threads.py:389    @router.get("/{thread_id}/inputs")  list_thread_inputs
```
→ `POST /api/work-items/{work_item_id}/inputs` (in the workforce router) is the consistent prefix. The ref shape AD-926a writes — `{content_hash, mime, filename}` — is **exactly** what `_collect_task_inputs` reads.

### UI seams

```
ui/src/components/workspace/WorkspaceFilesRail.tsx
   props: { threadId }              (add taskId?: string | null)
   INPUTS section ~L208: <InputsList inputs={inputs} />   (add the "+ Attach" button here)
   owns fetchThreadInputs + local `inputs` state (self-contained)
ui/src/components/inputs/inputsApi.ts
   fetchThreadInputs(threadId) -> TaskInput[]; TaskInput {content_hash, mime, filename, size, source}
ui/src/components/profile/ProfileChatTab.tsx
   :494  workspaceThread = useStore(s => chatThreads.get(activeThreadId))   (has task_id)
   :496  showWorkspaceFiles = !!activeThreadId && isWorkspaceRoom(workspaceThread, agentsMap)
   :760  uploadAttachment(file): FormData {append('file', file, file.name)} -> POST /api/chat/attachments/multipart
   :1606 <WorkspaceFilesRail threadId={activeThreadId} />     (add taskId prop)
ui/src/store/useStore.ts:216   AD791aChatThreadView.task_id?: string | null
```

### AD-926a is unused
`git grep AD-926a` → only forward-marker comments. No endpoint, no route, no UI. Highest AD-numbered work = **AD-929**. HEAD `2eb8cabd` (origin/main), tree clean.

---

## Section 0 — Decisions (read before building)

1. **Endpoint prefix:** `POST /api/work-items/{work_item_id}/inputs` in `routers/workforce.py` (consistent with the other `/work-items/...` routes — NOT under `routers/threads.py`, because inputs are owned by the **work item**, and a thread learns about them via its `task_id`).
2. **Multipart multiple-file shape:** `files: list[UploadFile] = File(...)` (FastAPI native).
3. **Read-merge-write:** **single RMW per request** — validate+store **all N files first**, accumulate refs, then **one** `get_work_item` → merge → `update_work_item(metadata=merged)`. This eliminates the intra-request race. Preserve all other metadata keys + existing `input_attachments`; **dedupe by `content_hash`** (idempotent re-upload).
4. **Origin:** default `chat_attachment` (omit the kwarg). See verified note above.
5. **Authority:** operator/Captain-facing. Mirror the existing work-item mutation routes (`PATCH` / `transition` / `assign` / `delete`) — they have **no consensus gate and no per-caller authority check** (HXI/operator endpoints). Attaching a file is **additive, reversible, low-risk** (Safety Budget axiom) → **no `requires_consensus`, no quorum.** State this in the docstring.
6. **Honest-degrade per file:** a rejected file (oversize / mime mismatch / disallowed) is collected into a `skipped` list — it does **not** 500 the whole request. Good files still attach.

---

## Section 1 — Backend endpoint

### 1a. Imports

In [`src/probos/routers/workforce.py`](../src/probos/routers/workforce.py), extend the FastAPI import:

```python
# SEARCH
from fastapi import APIRouter, Depends, HTTPException, Request
# REPLACE
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
```

### 1b. The route

Add **after** the `DELETE /work-items/{work_item_id}` route and **before** the `# -- Bookings --` section header (≈ line 248):

```python
@router.post("/work-items/{work_item_id}/inputs")
async def attach_work_item_inputs(
    work_item_id: str,
    files: list[UploadFile] = File(...),
    runtime: Any = Depends(get_runtime),
    broadcast: Callable = Depends(get_ws_broadcast),
) -> dict[str, Any]:
    """AD-926a: attach one or more context-input files to a work item (task).

    The WRITE/population path for the AD-926 ``input_attachments`` convention.
    Each file is validated + stored once in the content-addressable
    ``AttachmentStore`` (sha256) via the SHARED chat uploader
    (``_validate_and_store_attachment`` — same defense-in-depth gate, default
    ``origin="chat_attachment"`` = operator intent, never age-reaped), then a
    ref ``{content_hash, mime, filename}`` is appended to the parent
    ``WorkItem.metadata["input_attachments"]``. The files then surface as the
    task room's Inputs via the existing ``GET /api/threads/{id}/inputs``.

    Operator/Captain action: reversible, additive, low-risk — no consensus
    gate (Safety Budget axiom), mirroring the other work-item mutation routes.

    Honest-degrade per file: a rejected file (oversize / mime mismatch /
    disallowed) is collected into ``skipped`` rather than failing the request.
    A single read-merge-write per request (all files stored first, then one
    metadata merge) preserves every other ``metadata`` key plus any existing
    inputs and dedupes by ``content_hash``.
    """
    if not runtime.work_item_store:
        raise HTTPException(503, "Workforce engine not enabled")
    wi = await runtime.work_item_store.get_work_item(work_item_id)
    if not wi:
        raise HTTPException(404, "Work item not found")

    from probos.routers.chat import _validate_and_store_attachment

    new_refs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for f in files:
        blob = await f.read()
        ok, result = await _validate_and_store_attachment(
            runtime,
            blob,
            f.content_type or "application/octet-stream",
            declared_filename=f.filename,
            declared_hash_or_None=None,
        )
        if not ok:
            skipped.append({
                "filename": f.filename,
                "error": (result.get("body") or {}).get("error", "rejected"),
            })
            continue
        new_refs.append({
            "content_hash": result["sha256"],
            "mime": result["mime"],
            "filename": f.filename,
        })

    # Single read-merge-write: preserve all other metadata keys + existing
    # inputs; dedupe by content_hash (idempotent re-upload). update_work_item
    # replaces the metadata column wholesale, so the merge MUST happen here.
    if new_refs:
        meta = dict(getattr(wi, "metadata", {}) or {})
        existing = list(meta.get("input_attachments", []) or [])
        seen = {
            r.get("content_hash")
            for r in existing
            if isinstance(r, dict)
        }
        for ref in new_refs:
            if ref["content_hash"] not in seen:
                existing.append(ref)
                seen.add(ref["content_hash"])
        meta["input_attachments"] = existing
        updated = await runtime.work_item_store.update_work_item(
            work_item_id, metadata=meta,
        )
        wi = updated or wi
        broadcast({
            "type": "work_item_updated",
            "data": {"work_item": wi.to_dict()},
        })

    # Return the task-level input list (mirrors the AD-926 read shape,
    # source="task"). size is best-effort from the content-addressable store.
    attachment_store = getattr(runtime, "attachment_store", None)
    inputs: list[dict[str, Any]] = []
    for ref in (getattr(wi, "metadata", {}) or {}).get("input_attachments", []) or []:
        if not isinstance(ref, dict):
            continue
        ch = ref.get("content_hash")
        size: int | None = None
        if attachment_store is not None and ch:
            try:
                size = await attachment_store.size(ch)
            except Exception:  # pragma: no cover - defensive, Tier-2
                size = None
        inputs.append({
            "content_hash": ch,
            "mime": ref.get("mime") or "application/octet-stream",
            "filename": ref.get("filename"),
            "size": size,
            "source": "task",
        })

    return {"work_item_id": work_item_id, "inputs": inputs, "skipped": skipped}
```

> `Any` and `Callable` are already imported in this module (used by the existing routes). Confirm before adding.

---

## Section 2 — UI: `inputsApi.attachTaskInputs`

In [`ui/src/components/inputs/inputsApi.ts`](../ui/src/components/inputs/inputsApi.ts), append:

```typescript
/**
 * AD-926a: attach one or more context-input files to a work item (task).
 *
 * Posts a single multipart request (all files under the `files` field) to
 * POST /api/work-items/{work_item_id}/inputs. The server validates + stores
 * each file once (content-addressable, sha256), appends refs to the work
 * item's input_attachments, and returns the updated task-level input list.
 * Honest-degrade: a non-ok response throws so the caller can show a toast.
 */
export async function attachTaskInputs(
  workItemId: string,
  files: File[],
): Promise<TaskInput[]> {
  const fd = new FormData();
  for (const f of files) {
    fd.append('files', f, f.name);
  }
  const res = await fetch(
    `/api/work-items/${encodeURIComponent(workItemId)}/inputs`,
    { method: 'POST', body: fd },
  );
  if (!res.ok) {
    throw new Error(`attachTaskInputs: ${res.status}`);
  }
  const body = await res.json();
  return Array.isArray(body.inputs) ? body.inputs : [];
}
```

---

## Section 3 — UI: the "+ Attach" affordance on the Files rail

### 3a. `WorkspaceFilesRail` gains a `taskId` prop + attach handler

In [`ui/src/components/workspace/WorkspaceFilesRail.tsx`](../ui/src/components/workspace/WorkspaceFilesRail.tsx):

- Import `attachTaskInputs` alongside `fetchThreadInputs`.
- Extend the props:

```typescript
// SEARCH
export interface WorkspaceFilesRailProps {
  threadId: string;
}

export function WorkspaceFilesRail(props: WorkspaceFilesRailProps) {
  const { threadId } = props;
// REPLACE
export interface WorkspaceFilesRailProps {
  threadId: string;
  /** AD-926a: the room's work item id (thread.task_id). When set, the
   *  Inputs section shows a multi-file "+ Attach" affordance. */
  taskId?: string | null;
}

export function WorkspaceFilesRail(props: WorkspaceFilesRailProps) {
  const { threadId, taskId } = props;
```

- Add an attach handler near the other callbacks (mirrors `ProfileChatTab.uploadAttachment` — multipart FormData, one request for all files). On success, update the rail's local `inputs` state from the returned list:

```typescript
const handleAttach = useCallback(async (files: File[]) => {
  if (!taskId || files.length === 0) return;
  try {
    const updated = await attachTaskInputs(taskId, files);
    setInputs(updated);
  } catch {
    // honest-degrade — the attach failed; the rail keeps its current list.
  }
}, [taskId]);
```

- In the INPUTS section (the `<div data-testid="workspace-files-inputs-label">INPUTS</div>` block, ≈ line 208), render the "+ Attach" button **only when `taskId` is set** (there must be a work item to hold the inputs). Use a hidden `<input type="file" multiple>` and inline stroke-SVG (HXI #3 — **no emoji**):

```tsx
<div
  data-testid="workspace-files-inputs-label"
  style={{
    display: 'flex', alignItems: 'center', gap: 6,
    fontSize: 10, letterSpacing: 1.5, color: DIM,
    padding: '8px 10px 4px',
  }}
>
  <span style={{ flex: '1 1 auto' }}>INPUTS</span>
  {taskId && (
    <label
      data-testid="workspace-files-attach"
      title="Attach files to this task"
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 3,
        color: AMBER, cursor: 'pointer', fontSize: 10,
      }}
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth={1.5}
        strokeLinecap="round" strokeLinejoin="round" aria-label="attach">
        <path d="M12 5v14M5 12h14" />
      </svg>
      Attach
      <input
        type="file"
        multiple
        data-testid="workspace-files-attach-input"
        style={{ display: 'none' }}
        onChange={(e) => {
          const picked = Array.from(e.target.files ?? []);
          void handleAttach(picked);
          if (e.target) e.target.value = '';
        }}
      />
    </label>
  )}
</div>
```

### 3b. `ProfileChatTab` passes `taskId`

In [`ui/src/components/profile/ProfileChatTab.tsx`](../ui/src/components/profile/ProfileChatTab.tsx#L1606):

```tsx
// SEARCH
      {showWorkspaceFiles && activeThreadId && <WorkspaceFilesRail threadId={activeThreadId} />}
// REPLACE
      {showWorkspaceFiles && activeThreadId && (
        <WorkspaceFilesRail
          threadId={activeThreadId}
          taskId={workspaceThread?.task_id ?? null}
        />
      )}
```

> `workspaceThread` is already in scope (the `isWorkspaceRoom` gate selector at :494). No new store selector needed.

---

## Section 4 — Tests

### 4a. `tests/test_ad926a_task_file_upload.py` (BF-287 — real stores, ≈10)

Harness mirrors [`test_ad926_inputs_folder.py`](../tests/test_ad926_inputs_folder.py): real `WorkItemStore(db_path=str(tmp_path/"crew.db"), emit_event=lambda *a, **k: None, tick_interval=1000)` with `await start()/stop()`, real `FilesystemAttachmentStore`, real `ChatThreadStore`. The endpoint is invoked by awaiting `attach_work_item_inputs` directly with a `SimpleNamespace` runtime + `broadcast=lambda *a, **k: None`.

**Two write-path wiring requirements** (different from the AD-926 read test):
- The runtime stub needs a **real `config`** (`SystemConfig()`) so the validate gates read real `config.attachments` (enabled, mime allowlist, size cap).
- Seed the chat uploader's store cache so the write lands in the test store (AD-916 e2e precedent):
  ```python
  from probos.routers import chat as chat_router
  chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = attach_store
  ```
- Build `UploadFile`s from bytes:
  ```python
  import io
  from starlette.datastructures import Headers, UploadFile
  def _upload(name, blob, mime):
      return UploadFile(file=io.BytesIO(blob), filename=name,
                        headers=Headers({"content-type": mime}))
  ```
- Happy-path files: `text/plain` with `.txt` filenames + UTF-8 bytes (passes the magic-byte + extension gate at [`mime.py:152`](../src/probos/attachments/mime.py#L152)).

Cases:
1. **Two files attach** → two refs appended to `metadata["input_attachments"]`; survive a `get_work_item` read-back with correct `{content_hash, mime, filename}`.
2. **Bytes land in the store** → `await attach_store.read(sha)` returns the original blob for each file's real sha256.
3. **Second upload APPENDS, never clobbers** → seed the work item's `metadata` with a sentinel key (e.g. `{"owner": "captain"}`) **and** one pre-existing input ref; after attaching a new file, assert the sentinel key survives, the pre-existing ref survives, and the new ref is present (3 total).
4. **Duplicate content_hash is idempotent** → attaching the same blob twice yields exactly one ref.
5. **Bad file skipped per file (no 500)** → attach one good `.txt` + one oversize blob (`> max_attachment_bytes`, or a mime/extension mismatch); response `skipped` has the bad one, `inputs` has the good one, status is 200-equivalent (no raise).
6. **404 / 503** → unknown `work_item_id` raises `HTTPException(404)`; `work_item_store=None` raises `HTTPException(503)`.
7. **Integration with AD-926 read** → create a `ChatThreadStore` thread with `task_id=work_item.id`, attach 2 files, then `await list_thread_inputs(thread.id, runtime=...)` returns both with `source="task"`.
8. **Empty files list** → no refs written, returns the current inputs (no-op).

### 4b. Vitest — `WorkspaceFilesRail.attach.test.tsx` (≈5) + `inputsApi.attach.test.ts` (≈3)

`inputsApi.attach.test.ts` (`vi.stubGlobal('fetch', ...)`):
- builds FormData with each file under `files`, POSTs to `/api/work-items/{id}/inputs`.
- returns `body.inputs` on ok; throws on non-ok.
- no-emoji guard on the source (`?raw` import, `/\p{Extended_Pictographic}/u`).

`WorkspaceFilesRail.attach.test.tsx` (mirror the existing `WorkspaceFilesRail.test.tsx` mock pattern — `vi.mock` `inputsApi`/`artifactApi`, real store BF-287, render expanded):
- attach button + `<input type="file" multiple>` render when `taskId` is set.
- attach button is **absent** when `taskId` is null/undefined.
- selecting 2 files calls `attachTaskInputs(taskId, [file1, file2])` and updates the rendered Inputs list from the returned array.
- no-emoji guard (`container.innerHTML`).

Baseline: AD-929 vitest **1225 passed / 1 skipped** (207 files) → require ≥ baseline + new tests. Run `cd ui; npx vitest run; npm run build`.

---

## What this does NOT change (Do NOT build)

- **No input edit / versioning.** Inputs are immutable context; the editable side is artifacts/outputs (AD-797/AD-927). Do not add a re-upload-as-new-version flow.
- **No delete-input.** v1 is attach-only (forward marker **AD-926a-1** if a trivial DELETE is wanted later).
- **No atomic store-level metadata merge.** The single-RMW-per-request pattern is sufficient for an operator-driven manual action. A store-level `append_input_attachments` with `BEGIN IMMEDIATE` (mirroring `ChatThreadStore.set_title`) to harden the cross-request race is a forward marker (**AD-926a-2**). Do not refactor `update_work_item`.
- **No new attachment origin.** Use the default `chat_attachment` (omit the kwarg).
- **No kanban / `WorkBoard` card attach button.** The Files rail Inputs section is the v1 surface (a WorkBoard card attach action is a forward marker).
- **No change to** the `AttachmentStore` Protocol, the `WorkItem` schema/dataclass, the AD-926 read endpoint/`_collect_task_inputs`, the AD-925 create path, or the message-attachment (`source="message"`) path.
- **No consensus gate / quorum / new EventType / new config field.**

---

## Tracking

- **`PROGRESS.md`** — prepend an AD-926a block (the WRITE/population path for the AD-926 Inputs convention; reused uploader; single read-merge-write; operator authority; Files-rail attach affordance).
- **`docs/development/roadmap.md`** — add an AD-926a row (or flip the AD-926 row's "population deferred → AD-926a" note to SHIPPED and add the AD-926a row).
- **`DECISIONS.md`** — append the AD-926a entry (endpoint prefix; single RMW preserving other keys + dedupe; default origin; no-consensus operator authority; non-goals + forward markers AD-926a-1/AD-926a-2).
- **Commit** local only (epic held for Captain review/push, per the Task Workspace Rooms convention): `AD-926a: task-level multi-file upload (populate input_attachments)`.

---

## Acceptance criteria

1. `POST /api/work-items/{work_item_id}/inputs` accepts multipart `files: list[UploadFile]`, validates+stores each via the **reused** `_validate_and_store_attachment` (default origin), and appends `{content_hash, mime, filename}` refs to `WorkItem.metadata["input_attachments"]` via a **single read-merge-write** that preserves all other metadata keys + existing inputs and dedupes by `content_hash`.
2. A bad/oversize file is **skipped per file** (returned in `skipped`), never 500s the request; good files still attach.
3. 404 when the work item is missing; 503 when `work_item_store` is None.
4. The attached files surface via the **existing** AD-926 `GET /api/threads/{id}/inputs` with `source="task"` (integration test) and render in the AD-929 Files rail.
5. UI: the Files rail Inputs section shows a multi-file **"+ Attach"** button **only when `taskId` is set**; selecting files posts one multipart request and updates the list. No emoji (HXI #3).
6. `tests/test_ad926a_task_file_upload.py` (≈10, BF-287 real stores) + `WorkspaceFilesRail.attach.test.tsx` (≈5) + `inputsApi.attach.test.ts` (≈3) all pass; full pytest blast-radius (`-k "work_item or workforce or thread or chat or input or attachment"`) and full `npx vitest run` + `npm run build` green.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Gate commands

```powershell
# Focused pytest
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad926a_task_file_upload.py tests/test_ad926_inputs_folder.py -q -n 0 -p no:cacheprovider
# Blast-radius pytest
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "work_item or workforce or thread or chat or input or attachment" -q -p no:cacheprovider
# UI
cd ui; npx vitest run; npm run build
```
