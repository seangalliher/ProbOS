# AD-797 (Wave 197, v2) — Artifacts pane: extractor + content endpoint + UI drawer

**Wave:** 197. Single Builder commit at completion.
**Sequence:** AD-797 ([#721](https://github.com/seangalliher/ProbOS/issues/721)).
**Builds on:** AD-720 (AttachmentStore), AD-731 (refs-not-bytes), AD-791a (chat threads), AD-793 (projects + pinned_attachment_ids), Wave 195/196 sidebar + project drawer layout.

v2 addresses 5 Required findings — **the AD-797 backend substrate already exists at HEAD** (commit `9b811df6` advance-landed in Wave 195's batch). v2 is framed as an EXTENSION of the existing substrate, not greenfield.

---

## Section -1 — Substrate audit (what's already shipped)

Verified against HEAD on 2026-05-25:

- **`src/probos/artifacts/__init__.py`** — `Artifact` dataclass + `ArtifactStore`. Columns: `id, thread_id, name, version, content_hash, mime, size_bytes, created_by, created_at, supersedes`. Methods: `add_version()`, `get()`, `latest()`, `list_versions()`, `list_thread_latest()`.
- **`src/probos/routers/artifacts.py`** — 5 endpoints mounted: `POST /api/artifacts`, `GET /api/artifacts/thread/{thread_id}`, `GET /api/artifacts/thread/{thread_id}/name/{name}/versions`, `GET /api/artifacts/{artifact_id}`, `DELETE /api/artifacts/{artifact_id}`. Single-artifact endpoints return `a.to_dict()` directly (matches Wave 195/196 convention).
- **`src/probos/runtime.py:457`** — `self.artifact_store = ArtifactStore(...)` already wired.
- **`src/probos/api.py:246`** — `artifacts_router` already registered.

**Four real gaps Wave 197 closes:**

1. **Extractor**: nothing reads agent reply bodies to identify artifact-worthy blocks. Store accepts artifacts via `POST /api/artifacts`, but no automatic extraction.
2. **`GET /api/artifacts/{id}/content`**: missing endpoint to stream bytes from AttachmentStore.
3. **UI drawer**: doesn't exist; `ProfileChatTab` doesn't render artifacts.
4. **Project-pinned propagation**: AD-793 `pinned_attachment_ids` exists but `list_thread_artifacts` doesn't merge those into thread responses.

Plus one latent BF caught during review:

5. **`add_version()` race**: SELECT MAX + INSERT without `BEGIN IMMEDIATE`. Currently latent because extraction is not automated; fix in this wave (BF-324, small).

---

## Section 0 — Conceptual frame

Artifacts are *agent outputs that deserve their own surface*: code, drafts, plans, generated images. They differ from chat messages (in scrollback, conversational layer) and from attachments (Captain uploads). The drawer surfaces them with version history instead of dumping into chat scrollback.

**v1 is read-only.** Drawer renders artifacts, Captain copies/saves/pins. Live editing (AD-797a) + diff view (AD-797b) are forward markers.

HXI principles:
- **#1 The system understands the human.** Artifacts surface automatically when an agent produces qualifying output.
- **#3 No emoji.** Inline SVG matching Wave 195/196 stroke style.
- **#5 Progressive disclosure.** Drawer collapses to 28px rail when empty.
- **#11 Agentic-first.** Drawer is read-only; editing is via asking the agent.

---

## Section 1 — Extraction triggers

Extractor runs as **`step_4f_extract_artifacts`** in `DmReplyPipeline`, after existing `step_4*` parses and before `step_5_episodic_store`. It mutates `self.ctx.response_text` in place — reads body, persists artifacts to ArtifactStore + AttachmentStore, rewrites response_text with stub lines. Downstream persistence (outside the pipeline) sees the stubbed text.

Two triggers fire in order:

### 1.1 Explicit `<artifact>` tag (preferred)

```
<artifact name="grocery_list.md" mime="text/markdown">
- Eggs
- Milk
</artifact>
```

- `name` (required): must match `[A-Za-z0-9._-]+`. Non-conforming names are sanitized (path separators stripped, other chars replaced with `_`). Empty after sanitize → skipped with warning log. **Security**: the name lands in a browser `<a download={name}>` later — strict validation non-negotiable.
- `mime` (required): v1 supports `text/markdown`, `text/plain`, `text/x-*` for code, `image/png|jpeg|gif|webp`, `text/uri-list` for URL-references.

### 1.2 Fenced code block ≥ N lines (default 40)

```python
def helper():
    ...
```

Threshold from `cognitive.artifact_fenced_threshold_lines` Pydantic config (default 40).

Name + mime derivation when no `<artifact>` tag:
- If fenced block opens with `# filename: helper.py` (or `// filename: ...`, `<!-- filename: ... -->`), use that filename. Mime inferred from extension.
- Else: `artifact-{N}.{ext}` where N = `len(existing_unnamed_in_thread) + 1`, ext from fence language tag.

Language → (mime, ext) map covers 12 languages: `python|py`, `typescript|ts`, `javascript|js`, `markdown|md`, `bash|sh`, `json`, `yaml|yml`, `html`, `css`, `sql`, `rust|rs`, `go`. Default `text/plain`, `.txt`.

### 1.3 Body replacement (the scrollback-clean rule)

Extracted spans replaced with stub:

```
[Artifact: helper.py v1 - 73 lines, text/x-python]
```

**ASCII hyphen `-` (NOT em-dash)** per architect Rec1. UI regex matches literal hyphen.

---

## Section 2 — `add_version()` race-safety fix (BF-324, rolled in)

Existing `ArtifactStore.add_version()` does `SELECT MAX(version)` then INSERT without transaction. Two near-simultaneous extractions on same `(thread_id, name)` would collide on `UNIQUE (thread_id, name, version)`.

**Fix:** wrap in `BEGIN IMMEDIATE` (matches AD-791a / AD-793 convention). One short transaction, no API change.

Regression test: 4 concurrent `add_version` calls on same `(thread_id, name)`; assert versions 1/2/3/4 assigned without IntegrityError.

---

## Section 3 — Schema: NO changes

Existing schema covers v1 fully. **No ALTER TABLE.** Specifically:

- **No `type` column.** UI render branch derives from `mime`: `text/markdown` → markdown, `text/x-*` → code, `image/*` → image, `text/uri-list` → image-from-URL.
- **No `lang` column.** UI extracts lang from mime suffix (`text/x-python` → "python") for future syntax highlighting (AD-797d).
- **No `line_count` column.** Derived on-demand in LIST endpoint: read bytes, count `\n`. Image/uri-list → 0. Materialize if it becomes hot.
- **No `message_id` column.** Back-link deferred to AD-797m. v1 uses timeline (created_at + message order) for inference.

---

## Section 4 — Extractor implementation

New module: `src/probos/cognitive/dm/artifact_extractor.py`.

```python
@dataclass
class ExtractedArtifact:
    name: str
    mime: str
    content: bytes               # UTF-8 text, image bytes, or URL bytes for text/uri-list
    line_count: int              # 0 for image/*, text/uri-list
    source_span: tuple[int, int] # char offsets in original response_text

def extract_artifacts(
    response_text: str,
    *,
    fenced_threshold_lines: int = 40,
    existing_unnamed_count: int = 0,
) -> list[ExtractedArtifact]:
    """Pass 1: explicit <artifact> tags (authoritative).
    Pass 2: fenced-code scanner over remaining body with tag spans removed.
    Returns artifacts in source-position order."""

async def replace_with_stubs(
    response_text: str,
    extracted: list[ExtractedArtifact],
    *,
    artifact_store: ArtifactStore,
    attachment_store: Any,  # AttachmentStore protocol
    thread_id: str,
    created_by: str,
) -> tuple[str, list[Artifact]]:
    """For each extracted:
      1. content_hash = hashlib.sha256(blob).hexdigest()
      2. await attachment_store.write(content_hash, blob, mime, origin="agent_artifact")
      3. artifact_store.add_version(thread_id=..., name=..., content_hash=..., mime=..., size_bytes=len(blob), created_by=...)
      4. Replace source_span with stub line in response_text
    Returns (rewritten_text, [Artifact, ...]) in source order."""
```

**AttachmentStore.write signature** (verified at `attachments/store.py:38`):
```python
async def write(content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment") -> Path
```

Pass `origin="agent_artifact"` so a future GC pass (AD-797k) can distinguish artifact bytes from uploaded attachments.

---

## Section 5 — Pipeline integration

Insert `step_4f_extract_artifacts` in `cognitive/dm/reply_pipeline.py` after the last existing `step_4*` parse (the actual order at HEAD: `step_4_self_check_parse`, `step_4b_dm_outbound_parse`, `step_4c_image_gen_parse`, `step_4d_follow_up_parse`, `step_4e_action_dispatch` — Builder verifies and inserts after all of these) and before `step_5_episodic_store`.

```python
async def step_4f_extract_artifacts(self) -> None:
    """AD-797 Wave 197: extract <artifact> tags + large fenced-code blocks
    from self.ctx.response_text; persist to ArtifactStore + AttachmentStore;
    rewrite response_text with stub lines."""
    try:
        text = self.ctx.response_text or ""
        if not text:
            return
        artifact_store = getattr(self.ctx.runtime, "artifact_store", None)
        attachment_store = getattr(self.ctx.runtime, "attachment_store", None)
        if artifact_store is None or attachment_store is None:
            return
        thread_id = getattr(self.ctx, "thread_id", None)
        if not thread_id:
            return  # not in thread context — nothing to anchor extraction
        existing = artifact_store.list_thread_latest(thread_id)
        unnamed_count = sum(1 for a in existing if a.name.startswith("artifact-"))
        threshold = getattr(
            getattr(self.ctx.runtime.config, "cognitive", None),
            "artifact_fenced_threshold_lines",
            40,
        )
        extracted = extract_artifacts(
            text,
            fenced_threshold_lines=threshold,
            existing_unnamed_count=unnamed_count,
        )
        if not extracted:
            return
        new_text, _artifacts = await replace_with_stubs(
            text, extracted,
            artifact_store=artifact_store,
            attachment_store=attachment_store,
            thread_id=thread_id,
            created_by=getattr(self.ctx, "agent_id", "agent") or "agent",
        )
        self.ctx.response_text = new_text
    except Exception as exc:
        logger.warning(
            "AD-797: artifact extractor failed; response_text left intact (%s)",
            exc, exc_info=True,
        )
```

**Verify-first dependencies (Section 16):**
- `self.ctx.thread_id` / `self.ctx.agent_id` actual field names on `DmReplyContext`.
- `self.ctx.runtime.attachment_store` actual attribute name (likely `attachment_store`).

If either name differs at HEAD, Builder uses the actual name. The `getattr(..., default)` guards in the code above are defensive but Builder should NOT rely on them — confirm the names and use them directly.

**Honest-degrade:** any exception logs warning and leaves `response_text` intact. No crash propagation.

---

## Section 6 — `GET /api/artifacts/{id}/content` endpoint

Add to `src/probos/routers/artifacts.py`:

```python
from fastapi import Response

@router.get("/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: str, runtime: Any = Depends(get_runtime),
):
    """AD-797 Wave 197: stream raw bytes from AttachmentStore."""
    store = _get_store(runtime)
    a = store.get(artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    attachment_store = runtime.attachment_store
    try:
        blob = await attachment_store.read(a.content_hash)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="content_missing")
    return Response(content=blob, media_type=a.mime)
```

Returns raw bytes with `Content-Type` from `artifact.mime`. Used by drawer viewer (markdown/code/image render) and Captain's "Save to file" button.

For `mime="text/uri-list"`, the response body IS the URL (plain bytes); UI dereferences to `<img src>`.

---

## Section 7 — Project-pinned propagation

Extend `list_thread_artifacts` to merge project-pinned artifacts:

```python
@router.get("/thread/{thread_id}")
async def list_thread_artifacts(
    thread_id: str, runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    native = store.list_thread_latest(thread_id)
    native_dicts = [a.to_dict() for a in native]
    for d in native_dicts:
        d["_pinned_from_project"] = False

    pinned_dicts: list[dict] = []
    chat_thread_store = runtime.chat_thread_store
    project_store = runtime.project_store
    thread = chat_thread_store.get_thread(thread_id)
    if thread is not None and thread.project_id:
        project = project_store.get_project(thread.project_id)
        if project is not None and project.pinned_attachment_ids:
            native_hashes = {d["content_hash"] for d in native_dicts}
            for sha in project.pinned_attachment_ids:
                if sha in native_hashes:
                    continue  # native wins
                matched = store.find_first_by_hash(sha)  # NEW helper (Section 2)
                if matched is not None:
                    d = matched.to_dict()
                    d["_pinned_from_project"] = True
                    pinned_dicts.append(d)

    return {"thread_id": thread_id, "artifacts": native_dicts + pinned_dicts}
```

**New helper `ArtifactStore.find_first_by_hash(content_hash) -> Artifact | None`:** `SELECT * FROM artifacts WHERE content_hash = ? ORDER BY created_at ASC LIMIT 1`. Uses existing `idx_artifacts_hash` index. First-by-time deterministic; known limitation for cross-thread artifact identity (AD-797h forward marker).

**Response shape preserved:** `{"thread_id": ..., "artifacts": [...]}` (HEAD-compatible). Per-row `_pinned_from_project` flag is the merge signal.

Edge cases:
- Pinned SHA with no `Artifact` row (raw upload, not extracted) → skipped silently.
- Same SHA in native AND pinned → native wins (no duplicate row).

---

## Section 8 — UI drawer (CompactApp)

CompactApp is currently `[ThreadSidebar | ProfileChatTab]`. Extend to `[ThreadSidebar | ProfileChatTab | ArtifactDrawer]`.

### 8.1 Layout

- 360px expanded / 28px rail collapsed.
- localStorage persists collapsed state under `probos.artifactDrawer.collapsed`.
- Viewport `<1024px`: defaults to rail (per architect N2). Full responsive design → AD-797j.

### 8.2 Drawer content

Top to bottom:
1. Header: title "Artifacts", count badge, collapse chevron.
2. List: per-artifact row — name, version chip ("v2"), mime-derived type icon, timestamp, pinned-badge if `_pinned_from_project=true`.
3. Active viewer:
   - Header: name + version selector dropdown + Copy/Save/Pin buttons.
   - Body (render branch by mime):
     - `text/markdown` → `react-markdown` (existing dep, package.json:23).
     - `text/x-*` / `application/json|sql|yaml` → `<pre><code>` monospace, no syntax highlight (AD-797d).
     - `image/*` → `<img src={'/api/artifacts/{id}/content'}>`. Browser fetches via the content endpoint.
     - `text/uri-list` → fetch via content endpoint, parse body as URL, render `<img src={url}>`.
     - `text/plain` → `<pre>` with `white-space: pre-wrap`.
     - default → `<pre>` plain.

### 8.3 Active-thread coupling

Drawer subscribes to `useStore.activeThreadId`. On change:
1. Fetch `/api/artifacts/thread/{newId}` and replace drawer state.
2. If empty AND no pinned → collapse to rail (unless Captain manually expanded — respect their state).

### 8.4 Inline `<ArtifactCard>` in ProfileChatTab

In ProfileChatTab message-body render (Builder finds the exact line), split body by `\n` and replace lines matching:

```
^\[Artifact: (?<name>[^\]]+) v(?<version>\d+) - (?<lines>\d+) lines, (?<mime>[^\]]+)\]$
```

with `<ArtifactCard>`. On click:
- Expand drawer if collapsed.
- Dispatch `selectArtifact(matched_id)` from store.

**Card → artifact_id resolution:** the stub doesn't contain UUID. Drawer state holds `{artifactsByThread: {threadId: [Artifact, ...]}}`. Card matches `(message.thread_id, stub.name, stub.version)` against loaded list. If drawer hasn't loaded yet, card displays in waiting state; a `useEffect` retries once drawer state arrives.

---

## Section 9 — Captain actions (drawer toolbar)

1. **Copy**: `navigator.clipboard.writeText(content)` (content fetched from `/api/artifacts/{id}/content`). For `image/*`, button is disabled with tooltip "Copy not supported for images". Toast "Copied 73 lines".
2. **Save to file**: synthesizes `<a href={blobUrl} download={artifact.name}>`, programmatically clicks, revokes blob URL.
3. **Pin to project**: visible only when `thread.project_id` is non-null. Calls **existing** `POST /api/projects/{id}/pin` (AD-793) with the artifact's `content_hash` as `attachment_id`. On success, re-fetch artifacts list to pick up `_pinned_from_project=true` flag.
4. **Send to tool**: forward marker AD-797c — NOT in v1.

---

## Section 10 — Tests

### Pytest (≥10 — 12 named)

1. `test_artifact_extractor.py::test_extracts_explicit_tag` — `<artifact name="x.md" mime="text/markdown">...</artifact>` → one ExtractedArtifact.
2. `test_artifact_extractor.py::test_extracts_fenced_code_above_threshold` — 60-line python block → `mime='text/x-python'`, `name='artifact-1.py'`.
3. `test_artifact_extractor.py::test_skips_short_fenced_code` — 20-line block → no extraction.
4. `test_artifact_extractor.py::test_filename_comment_derives_name` — `# filename: helper.py` first-line comment → name picked up.
5. `test_artifact_extractor.py::test_two_extractors_in_one_reply` — explicit tag + 60-line fenced block → two ExtractedArtifacts in source order.
6. `test_artifact_extractor.py::test_name_sanitization` — `name="../../etc/passwd"` → sanitized (path separators stripped).
7. `test_artifact_store.py::test_add_version_race_safety_bf324` — 4 concurrent `add_version` (asyncio.gather + run_in_executor since store is sync) on same `(thread_id, name)`; assert versions 1/2/3/4 without IntegrityError. **BF-324 regression.**
8. `test_artifact_api.py::test_get_content_endpoint_returns_raw_bytes_and_mime` — bytes + correct Content-Type.
9. `test_artifact_api.py::test_get_content_404_when_artifact_missing` — 404 `artifact_not_found`.
10. `test_artifact_api.py::test_list_thread_includes_project_pinned` — pin SHA to project P, query different thread in P → response includes pinned artifact with `_pinned_from_project=true`.
11. `test_artifact_pipeline.py::test_reply_with_artifact_tag_persists_and_stubs_body` — DmReplyPipeline integration: ctx.response_text containing `<artifact>` → post-pipeline response_text has stub, AttachmentStore has bytes, ArtifactStore has row.
12. `test_artifact_pipeline.py::test_extractor_failure_falls_through_with_original_response_text` — monkeypatch `extract_artifacts` to raise; pipeline completes with response_text unchanged.

### Vitest (≥6 — 7 named)

1. `ArtifactDrawer.empty-state.test.tsx` — no artifacts → 28px rail.
2. `ArtifactDrawer.list-render.test.tsx` — populated list shows name + version + mime icon + pinned badge for `_pinned_from_project=true`.
3. `ArtifactDrawer.active-thread-change.test.tsx` — `activeThreadId` change refetches.
4. `ArtifactDrawer.markdown-render.test.tsx` — `text/markdown` content renders heading via react-markdown.
5. `ArtifactDrawer.copy-button.test.tsx` — clicks copy → mocked `navigator.clipboard.writeText` called.
6. `ArtifactDrawer.version-selector.test.tsx` — dropdown changes selection, viewer re-renders.
7. `ArtifactCard.inline.test.tsx` — message body with stub line renders `<ArtifactCard>`; click opens drawer + selects.

---

## Section 11 — Non-goals (Do NOT build)

- ❌ Schema changes to `artifacts` table (Section 3).
- ❌ Monaco / CodeMirror in-place editing (AD-797a).
- ❌ Diff view (AD-797b).
- ❌ "Send to tool" (AD-797c).
- ❌ Syntax highlighting (AD-797d).
- ❌ Additional artifact mimes beyond v1's set (AD-797e).
- ❌ Runtime-override of `fenced_threshold_lines` (AD-797f).
- ❌ Cross-thread artifact identity / canonical SHA-to-artifact dedup (AD-797h).
- ❌ Captain-direct artifact creation from drawer rail (AD-797i).
- ❌ Full HXI artifact drawer (AD-797j).
- ❌ AttachmentStore orphan GC (AD-797k).
- ❌ Materialized `line_count` column (deferred).
- ❌ Materialized `message_id` back-link (AD-797m).
- ❌ Changes to AttachmentStore, chat_threads, chat_thread_messages, projects schemas.

(Per architect N5: AD-797g — Captain-direct POST UI surface — is DROPPED from forward markers because POST already exists at HEAD; v1 simply does not expose it in the UI.)

---

## Section 12 — Acceptance criteria

1. Existing artifacts substrate is NOT duplicated; only the four real gaps + BF-324 close in this wave.
2. `ArtifactStore.add_version()` wraps SELECT MAX + INSERT in `BEGIN IMMEDIATE` (BF-324). New regression test passes.
3. `ArtifactStore.find_first_by_hash(content_hash)` helper added (used by project-pinned merge).
4. `cognitive/dm/artifact_extractor.py` exposes `extract_artifacts()` + `replace_with_stubs()`. Explicit `<artifact>` first; fenced ≥40 second; filename-comment name resolution; 12-language mime map; name sanitization to `[A-Za-z0-9._-]+`.
5. `DmReplyPipeline.step_4f_extract_artifacts` inserts between last `step_4*` parse and `step_5_episodic_store`. Mutates `self.ctx.response_text` in place. Honest-degrade on failure.
6. Stub format: `[Artifact: {name} v{version} - {line_count} lines, {mime}]` (ASCII hyphen).
7. `GET /api/artifacts/{artifact_id}/content` endpoint returns raw bytes from AttachmentStore with `Content-Type` from `artifact.mime`. 404 when artifact or content missing.
8. `GET /api/artifacts/thread/{thread_id}` merges project-pinned artifacts when `thread.project_id` is non-null. Native + pinned union (native wins on hash collision). Per-row `_pinned_from_project: bool` flag. Response shape stays HEAD-compatible.
9. `ArtifactDrawer.tsx` mounts in CompactApp as third flex child. 360px expanded / 28px rail. localStorage persists collapsed state. Viewport `<1024px` defaults to rail.
10. Render branches: markdown (react-markdown), code (`<pre><code>`), image (`<img>`), uri-list (URL→`<img>`), plain (`<pre>`). No new heavy deps.
11. Captain actions: Copy (`navigator.clipboard.writeText`), Save (browser `<a download>`), Pin-to-project (existing AD-793 endpoint).
12. `ArtifactCard` renders inline in ProfileChatTab in place of stub lines. Click opens drawer + selects.
13. ≥10 pytest + ≥6 vitest added. All existing tests pass. `npm run build` clean (BF-279).
14. Trackers: PROGRESS.md prepends Wave 197 entry; roadmap.md marks AD-797 SHIPPED Wave 197; GH issue #721 closed with commit hash.
15. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Section 13 — File touchpoints

| File | Change |
|---|---|
| `src/probos/artifacts/__init__.py` | MODIFY. (a) Wrap `add_version()` SELECT MAX + INSERT in `BEGIN IMMEDIATE` (BF-324). (b) Add `find_first_by_hash(content_hash) -> Artifact \| None` helper. No schema changes. |
| `src/probos/routers/artifacts.py` | MODIFY. (a) Add `GET /{artifact_id}/content` endpoint. (b) Extend `list_thread_artifacts` to merge project-pinned with `_pinned_from_project` per-row flag. |
| `src/probos/cognitive/dm/artifact_extractor.py` | NEW. `extract_artifacts()`, `replace_with_stubs()`, `ExtractedArtifact` dataclass, language→mime map, name sanitizer. |
| `src/probos/cognitive/dm/reply_pipeline.py` | MODIFY. Add `step_4f_extract_artifacts` method between last `step_4*` parse and `step_5_episodic_store`. Builder identifies exact insertion point by reading the pipeline orchestration site. |
| `src/probos/config.py` | MODIFY (small). Add `artifact_fenced_threshold_lines: int = Field(40, ge=10)` to `CognitiveConfig`. |
| `ui/src/components/artifacts/ArtifactDrawer.tsx` | NEW. ~250 LOC. Top-level drawer. |
| `ui/src/components/artifacts/ArtifactList.tsx` | NEW. List rows. |
| `ui/src/components/artifacts/ArtifactViewer.tsx` | NEW. Render branch by mime + Copy/Save/Pin toolbar. |
| `ui/src/components/artifacts/ArtifactCard.tsx` | NEW. Inline card in ProfileChatTab. |
| `ui/src/components/artifacts/artifactApi.ts` | NEW. Fetch wrappers. |
| `ui/src/CompactApp.tsx` | MODIFY. Add `<ArtifactDrawer>` as third child of existing flex container. |
| `ui/src/components/profile/ProfileChatTab.tsx` | MODIFY. Detect stub lines in message body, replace with `<ArtifactCard>`. |
| `ui/src/store/useStore.ts` | EXTEND. Add `artifactsByThread: Map<string, ArtifactView[]>` slice + actions: `hydrateArtifacts(threadId, list)`, `selectArtifact(id)`, `setDrawerCollapsed(bool)`. Add `ArtifactView` type matching HEAD `Artifact.to_dict()` + `_pinned_from_project` flag. |
| `tests/test_artifact_extractor.py` | NEW pytest. ≥6 tests. |
| `tests/test_artifact_store.py` | NEW pytest. ≥1 (BF-324 race regression). Builder checks if file exists; if so, adds to it. |
| `tests/test_artifact_api.py` | NEW pytest. ≥3 tests. |
| `tests/test_artifact_pipeline.py` | NEW pytest. ≥2 tests. |
| `ui/src/__tests__/ArtifactDrawer.empty-state.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactDrawer.list-render.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactDrawer.active-thread-change.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactDrawer.markdown-render.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactDrawer.copy-button.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactDrawer.version-selector.test.tsx` | NEW vitest. |
| `ui/src/__tests__/ArtifactCard.inline.test.tsx` | NEW vitest. |

**NOT touched** (existing substrate, no changes):
- `src/probos/runtime.py` (artifact_store wired at L457).
- `src/probos/api.py` (artifacts_router registered at L246).
- `src/probos/threads/__init__.py` (no schema changes).
- `src/probos/attachments/store.py` (no new methods).
- `src/probos/routers/projects.py` (existing `/pin` endpoint sufficient).

---

## Section 14 — Estimated scope

~700-900 LOC (smaller than v1's 900-1100 since backend substrate already exists). ~22 files (15 new, 7 modified). Single Builder commit.

Backend: ~150 LOC extractor + ~30 LOC BF-324 fix + find_first_by_hash + ~50 LOC router additions + project merge + ~30 LOC pipeline step + 10 LOC config = ~270 LOC.
UI: ~450 LOC across drawer/list/viewer/card/api/store.
Tests: ~250 LOC.

---

## Section 15 — Forward markers (consolidated)

- **AD-797a** — Live edit in drawer (Monaco / CodeMirror).
- **AD-797b** — Diff view between versions.
- **AD-797c** — "Send to tool" re-injection.
- **AD-797d** — Syntax highlighting.
- **AD-797e** — Additional mimes (`svg`, `mermaid`, `dot`, `latex`).
- **AD-797f** — Runtime-override of `fenced_threshold_lines`.
- ~~AD-797g~~ — DROPPED (POST exists at HEAD).
- **AD-797h** — Cross-thread artifact identity.
- **AD-797i** — Drawer-rail Captain-direct creation.
- **AD-797j** — Full HXI integration (responsive + canvas-friendly).
- **AD-797k** — AttachmentStore orphan GC.
- **AD-797m** — Materialized `message_id` back-link column.

---

## Section 16 — Verify-first audit checklist (Builder pre-flight)

```
grep -n "class ArtifactStore\|def add_version\|def list_thread_latest\|def find_first" src/probos/artifacts/__init__.py
    → Expected: ArtifactStore class, add_version, list_thread_latest exist.
      find_first_by_hash does NOT exist yet (this wave adds it).

grep -n "@router" src/probos/routers/artifacts.py
    → Expected: 5 existing endpoints. NO /{artifact_id}/content (this wave adds it).

grep -n "step_4\|step_5_episodic_store\|step_6\|class DmReplyPipeline" src/probos/cognitive/dm/reply_pipeline.py
    → Expected step ordering (verified at architect review):
        step_1_sanity_gate_retry, step_2_challenge_parse, step_3_move_parse,
        step_4_self_check_parse, step_4c_image_gen_parse, step_4d_follow_up_parse,
        step_4e_action_dispatch, step_4b_dm_outbound_parse, step_5_episodic_store,
        step_6_working_memory_record, step_7_divergence_check,
        step_8_mark_emitted, step_9_emotion_resolve
      Insert step_4f_extract_artifacts AFTER step_4e_action_dispatch / step_4b_dm_outbound_parse
      and BEFORE step_5_episodic_store. Confirm exact orchestration call order in the
      class body — there may be a single execute() method calling these in sequence.

grep -n "class DmReplyContext\|@dataclass" src/probos/cognitive/dm/reply_pipeline.py
    → Identify exact field names on DmReplyContext: thread_id, agent_id (or
      responder_id, etc.), runtime, response_text. The step_4f code uses these.

grep -n "BEGIN IMMEDIATE" src/probos/artifacts/__init__.py
    → Expected: ZERO matches before this wave (BF-324 — add_version not race-safe).
      After this wave: at least one match inside add_version.

grep -n "attachment_store\|attachmentstore" src/probos/runtime.py
    → Confirm the attribute name (likely self.attachment_store). Section 6 endpoint
      + extractor both depend on this attr.

grep -n "react-markdown" ui/package.json
    → Expected: ^10.1.0 at L23. No install needed.

grep -n "pinned_attachment_ids" src/probos/threads/__init__.py
    → Expected: Project dataclass field + column. Used in Section 7 merge.

read src/probos/cognitive/dm/reply_pipeline.py L80-200
    → Identify the exact orchestration site for step_4f insertion (likely an
      async def run() / execute() that calls steps in sequence).

read src/probos/routers/projects.py around POST /pin
    → Confirm payload shape {"attachment_id": "<sha>"} for the Pin-to-project
      button.

grep -n "navigator.clipboard" ui/src/
    → Expected: at least one prior usage. Reuse pattern.
```

If any verify-first item doesn't match, stop and report.

---

## Section 17 — Open questions

None. v1 → v2 collapse reflects discovered existing substrate. Wave 197 ships as a single commit covering 4 real gaps (extractor, content endpoint, project-pin merge, UI drawer) + 1 latent BF (race-safety).
