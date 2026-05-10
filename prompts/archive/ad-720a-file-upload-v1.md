# AD-720a — File upload (multipart) v1

**Status:** READY FOR BUILDER
**Wave:** 139
**Dispatch:** [prompts/WAVE-139-DISPATCH.md](prompts/WAVE-139-DISPATCH.md)
**Depends on:** AD-720 (Wave 135, SHIPPED — `AttachmentStore` Protocol, `FilesystemAttachmentStore`, JSON+base64 POST `/api/chat/attachments`, GET `/api/chat/attachments/{hash}`, `AttachmentsConfig`, `validate_image_bytes`)
**Pairs with:** AD-720d (same wave; THIS prompt ships first as commit N, AD-720d ships second as commit N+1)
**Issue:** [#549](https://github.com/seangalliher/ProbOS/issues/549)
**Risk:** **MEDIUM** — new endpoint surface + UI surface + config extension + JSON-path refactor (helper extraction). Zero new Python deps. The existing AD-720 paste test is the regression guard.
**Estimated tests:** ≥ 10 Python + ≥ 4 Vitest

> **Builder:** read [prompts/WAVE-139-DISPATCH.md](prompts/WAVE-139-DISPATCH.md) for cross-AD context, license posture, and the engineering-principles checklist. Read [prompts/BUILDER-EXECUTION-PLAN.md](prompts/BUILDER-EXECUTION-PLAN.md) for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

> **Hard order:** AD-720a is **commit N**, AD-720d is **commit N+1**. Reviewer fails any squash. AD-720d's `config.py` SEARCH/REPLACE assumes the post-AD-720a state — do NOT reorder commits.

---

## 1. Goal

Wave 135 shipped image **paste** (clipboard → `application/json` + base64). On 2026-05-10 Captain pasted Ezri's avatar; the paste path worked end-to-end. The **next two pieces** of the AD-720 three-axis split are now visible: **upload** (drag-drop + `+ Upload` button — this AD) and **vision pipe-through** (AD-720d). v1 of AD-720a adds:

- A new `POST /api/chat/attachments/multipart` endpoint **alongside** the existing JSON+base64 path. Multipart takes a single `UploadFile = File(...)`; server computes sha256 of the streamed bytes and runs the same defense-in-depth chain.
- A drag-drop overlay on the IntentSurface composer + a real `+ Upload` button replacing the tooltip-only paperclip. Both route through one `uploadAttachmentMultipart(file)` helper.
- An extended allow-list: PDF / `.txt` / `.md` / JSON / CSV (9 MIMEs total). **No `.docx`/`.xlsx`** (deferred to AD-720a-1 — needs `python-docx` / `openpyxl`).
- A new sibling validator `validate_attachment_bytes(blob, declared_mime, declared_filename)` for the new types.
- Three new `AttachmentsConfig` fields (`vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`) — added in this AD so AD-720d (commit N+1) can wire them without touching `config.py` again.

### Why now (Captain 2026-05-10)

Image paste worked; Captain explicitly asked about file upload and vision pipe-through during Wave 137 wrap. The two-AD split lets AD-720a ship the surface (endpoint + UI + config) without coupling to the chat-handler routing branch (AD-720d).

### Backwards-compat guarantee (HARD CONSTRAINT)

The existing JSON+base64 `POST /api/chat/attachments` and `GET /api/chat/attachments/{content_hash}` paths are **bit-for-bit unchanged in observable behaviour**. The JSON handler is refactored to call the new shared `_validate_and_store_attachment` helper, but its response shape, status codes, and error reasons stay identical. **The existing AD-720 paste test is the regression guard** — it must stay green at this commit without modification.

`handlePaste` in `IntentSurface.tsx` (line 434 at HEAD) is **NOT** modified by this AD. Reviewer fails any diff that mutates the paste handler body.

---

## 2. License posture

- OSS Apache 2.0 stays Apache 2.0.
- **Zero new Python deps.** `python-multipart` (FastAPI's multipart parser) — verified absent from `pyproject.toml` at HEAD. **HARD STOP** if Builder adds it; FastAPI's `UploadFile` works with the multipart parser FastAPI already pulls in transitively via `python-multipart` only when the application installs it. **Pre-flight verification:** `python -c "import multipart"` must succeed in `.venv` BEFORE writing endpoint code. If it does NOT, that is itself a hard stop — surface to Captain (the dispatch's "no new deps" rule and the FastAPI runtime requirement collide; Captain must rule on whether AD-720a-0 adds `python-multipart` as a separate dep-add AD before AD-720a). Record the import-probe result in the build report's pre-flight section.
- **Zero new JS deps.** Drag-drop uses native HTML5 (`onDragEnter`/`onDragOver`/`onDragLeave`/`onDrop`); file picker uses native `<input type="file">`; multipart upload uses native `FormData`.
- **Forbidden in v1 (HARD STOPS — see §8):**
  - `aiofiles` — verified zero hits in `pyproject.toml` at HEAD; archived prompts BF-089 / BF-094 reject it. Use `asyncio.to_thread` (the existing `FilesystemAttachmentStore` pattern).
  - `python-magic` / `libmagic` — not in dep set. Use stdlib magic-byte sniffs (extending the existing `mime.py` pattern).
  - `pypdf` / `PyPDF2` / `python-docx` / `openpyxl` — verified zero hits via `git grep "pypdf\|PyPDF\|python-docx\|openpyxl" -- pyproject.toml`. PDF text extraction is deferred to AD-720a-1; v1 ships PDF **upload + preview only**, no extraction.

---

## 3. Verified Against Codebase (2026-05-10)

```
git log --oneline -1
   87db564 (HEAD -> main, origin/main, origin/HEAD) Wave 138 retrospective: archive prompts

# AttachmentsConfig at HEAD — 4 fields, the 5 new ones land in this AD
grep -n "class AttachmentsConfig\|enabled: bool\|attachments_dir\|max_attachment_bytes\|allowed_mime_types" src/probos/config.py
   941: class AttachmentsConfig(BaseModel):
   944:     enabled: bool = True                                   # stable feature, default-on
   945:     attachments_dir: str = "data/attachments"
   946:     max_attachment_bytes: int = 10 * 1024 * 1024           # 10 MiB
   947:     allowed_mime_types: list[str] = Field(
   948:         default_factory=lambda: [
   949:             "image/png",
   950:             "image/jpeg",
   951:             "image/webp",
   952:             "image/gif",
   953:         ],
   954:     )

# Pydantic v2 field_validator import is already present
grep -n "from pydantic import" src/probos/config.py
   10: from pydantic import BaseModel, Field, field_validator, model_validator

# _MIME_TO_EXT — single source of truth, 4 entries; AD-720a extends to 9
grep -n "_MIME_TO_EXT" src/probos/attachments/filesystem_store.py
   23: _MIME_TO_EXT: dict[str, str] = {
   38:         ext = _MIME_TO_EXT.get(mime)

# validate_image_bytes — 4-MIME validator that AD-720a's new sibling delegates to
grep -n "def validate_image_bytes\|_SIGNATURES\|_ANY_OF" src/probos/attachments/mime.py
   13: _SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
   22: _ANY_OF: frozenset[str] = frozenset({"image/gif"})
   25: def validate_image_bytes(blob: bytes, declared_mime: str) -> tuple[bool, str]:

# routers/chat.py — JSON POST and GET endpoints + lazy store factory
grep -n "_get_attachment_store\|@router.post(\"/chat/attachments\")\|@router.get(\"/chat/attachments/" src/probos/routers/chat.py
   404: def _get_attachment_store(runtime: Any) -> Any:
   419: @router.post("/chat/attachments")
   537: @router.get("/chat/attachments/{content_hash}")

# fastapi imports already pulled in — UploadFile + File need to be added
grep -n "from fastapi import" src/probos/routers/chat.py
   11: from fastapi import APIRouter, Depends, HTTPException, Request

# IntentSurface — paperclip placeholder + paste handler + attachment_ids body
grep -n "paperclipTooltipOpen\|pendingAttachments\|handlePaste\|attachment_ids\|attachment-preview" ui/src/components/IntentSurface.tsx
    64:   const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
    65:   const [paperclipTooltipOpen, setPaperclipTooltipOpen] = useState(false);
   243:     const attachmentIds = pendingAttachments.map((a) => a.attachment_id);
   244:     setPendingAttachments([]);
   248:       body: JSON.stringify({ message: text, history: recentHistory, attachment_ids: attachmentIds }),
   434:   async function handlePaste(event: React.ClipboardEvent<HTMLInputElement>) {
   464:       setPendingAttachments((prev) => [...prev, data]);
   471:     setPendingAttachments((prev) => prev.filter((a) => a.attachment_id !== attachmentId));
  1837:                 <div data-testid="attachment-preview-strip" style={{
  1893:                 onPaste={handlePaste}
  1913:                 onMouseEnter={() => setPaperclipTooltipOpen(true)}
  1931:                 {paperclipTooltipOpen && (

# api_models — ChatRequest + AttachmentUploadRequest already exist
grep -n "class ChatRequest\|attachment_ids\|class AttachmentUploadRequest\|class AttachmentUploadResponse" src/probos/api_models.py
    20: class ChatRequest(BaseModel):
    24:     attachment_ids: list[str] = Field(default_factory=list)
    45: class AttachmentUploadRequest(BaseModel):
    52: class AttachmentUploadResponse(BaseModel):

# Confirms text/PDF extraction libs are absent — deferred features in v1
git grep -n "pypdf\|PyPDF\|python-docx\|openpyxl\|aiofiles\|python-multipart" pyproject.toml
   (zero matches)
```

**Dispatch contradictions surfaced (fix in this prompt only — do NOT edit the dispatch):**

1. **Dispatch §1 footnote** says `AttachmentsConfig` lines 941–954. HEAD shows lines 941–954 inclusive; verified one-for-one.
2. **Dispatch §3 helper extraction row** says the JSON handler is at lines 419–533. Confirmed at HEAD: `@router.post("/chat/attachments")` at 419; the function body extends to ~530 (last line of `return {"attachment_id": ...}` payload before the GET begins at 537).
3. **Dispatch §4 A1** says all three new fields (`vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`) land in AD-720a. Confirmed against §4 D5 wiring ("all added in AD-720a (commit N), so AD-720d's prompt SEARCH/REPLACE assumes the post-A1 state"). v1 of AD-720d does not touch `config.py` — that is the post-N constraint.
4. **`python-multipart` blocker.** FastAPI's `UploadFile` requires `python-multipart` at runtime. The dispatch's "Zero new Python deps in v1" rule (§2 + §3) and the multipart endpoint requirement collide. Builder MUST run `python -c "import multipart"` in `.venv` BEFORE writing endpoint code. If the import succeeds (transitively pulled), proceed. If it fails, **HARD STOP** and surface to Captain — the dispatch needs a precondition AD-720a-0 to add `python-multipart`. Record the result in the build report.

---

## 4. Scope (v1 only)

- Extend `AttachmentsConfig` (`src/probos/config.py`): bump `allowed_mime_types` default to 9 MIMEs, add `vision_tier: str = "standard"` with a `field_validator`, add `text_extraction_max_bytes: int = 1*1024*1024`, add `pdf_extraction_enabled: bool = False`.
- Extend `_MIME_TO_EXT` (`src/probos/attachments/filesystem_store.py`) to 9 entries. **No `application/octet-stream` fallback** — unknown MIMEs continue to raise `ValueError` per HEAD line 39.
- Add `validate_attachment_bytes(blob, declared_mime, declared_filename)` to `src/probos/attachments/mime.py`. Image MIMEs delegate to existing `validate_image_bytes`. Defense-in-depth for new types per §6 D3.
- Refactor existing `POST /api/chat/attachments` (JSON) to call a new shared `_validate_and_store_attachment` helper. Behaviour bit-for-bit preserved.
- Add new `POST /api/chat/attachments/multipart` (UploadFile) endpoint calling the same helper.
- Replace the tooltip-only paperclip in `IntentSurface.tsx` with a real `+ Upload` button + hidden `<input type="file" multiple accept="...">`. Add a drag-drop overlay over the composer.
- Extend the preview strip to render filename badges (not `<img>`) for non-image attachments.
- Tests: ≥ 10 Python + ≥ 4 Vitest.

## 5. Non-goals (deferred forward markers)

| Out of scope | Why deferred | Forward marker |
|---|---|---|
| `.docx` / `.xlsx` server-side parsing | Needs `python-docx` + `openpyxl`; not in `pyproject.toml`. Both MIT but the dep-add must be its own AD with explicit license review. | **AD-720a-1** |
| PDF **text extraction** | Needs `pypdf`; not in `pyproject.toml`. v1 ships PDF upload + preview only; the agent says "PDF extraction not yet wired" via AD-720d's stub when a PDF is sent. | **AD-720a-1** (combined with `.docx`/`.xlsx` since the AD already needs to add deps) |
| Vision pipe-through (image bytes → vision-capable agent) | Separate codepath with its own routing branch. v1 stores + previews only — `attachment_ids` is still server-ignored at the chat-handler level after this AD. | **AD-720d** (commit N+1, this wave) |
| Multi-image batch latency / context-budget evaluation | v1 supports `attachment_ids` array but the test matrix focuses on single-attachment ergonomics. | **AD-720d-1** |
| Per-agent attachment capability designation | v1 routes purely on attachment MIME, not on the receiving agent. | **AD-720d-2** |
| Streaming chunked uploads | 10 MiB hard cap from `max_attachment_bytes` makes one-shot `await file.read()` acceptable. | (not filed) |
| Audio attachments (`audio/wav` etc.) | Voice/transcription pipeline is a separate concern. | **AD-720e** (not filed; tracking only) |
| Tool-attach (BrowserTool, MCP tools) | Permission-layer change; depends on AD-706. | **AD-720b** |
| Cloud file picker (OneDrive / GDrive) | OAuth plumbing; commercial-tier scope. Public roadmap entry MUST be technical-only. | **AD-720c** |

## 6. Deliverables

### A1. Extended `AttachmentsConfig`

**File:** `src/probos/config.py` (modify, around lines 941–954)

The post-AD-720a model has 7 fields. Default-list bumps from 4 to 9 MIMEs. Three new fields:

- `vision_tier: str = "standard"` with a `field_validator` rejecting values outside `{"fast", "standard", "deep"}` at parse time (Fail-Fast principle).
- `text_extraction_max_bytes: int = 1 * 1024 * 1024` — caps bytes appended to the prompt downstream (AD-720d uses this).
- `pdf_extraction_enabled: bool = False` — comment cites AD-720a-1 forward marker.

Constraints:
- `allowed_mime_types` MUST stay under `Field(default_factory=lambda: [...])` (bare mutable defaults in Pydantic models are a review blocker).
- `vision_tier` validator uses `field_validator("vision_tier")` (Pydantic v2; verified at HEAD line 10 import).

### A2. Extended `_MIME_TO_EXT`

**File:** `src/probos/attachments/filesystem_store.py` (modify, lines 23–28)

Bump the dict to 9 entries:
```python
_MIME_TO_EXT: dict[str, str] = {
    "image/png":         "png",
    "image/jpeg":        "jpg",
    "image/webp":        "webp",
    "image/gif":         "gif",
    "application/pdf":   "pdf",
    "text/plain":        "txt",
    "text/markdown":     "md",
    "application/json":  "json",
    "text/csv":          "csv",
}
```

**HARD CONSTRAINT (DRY):** `_MIME_TO_EXT` is the single source of truth used by both the write-path extension selection AND the GET endpoint's reverse lookup. The GET endpoint at HEAD lines 558–566 has an inline `{...}.get(ext, "application/octet-stream")` reverse map for 5 image extensions; AD-720a refactors that into a module-level `_EXT_TO_MIME` derived once from `_MIME_TO_EXT.items()` (or a runtime `next((m for m,e in _MIME_TO_EXT.items() if e == ext), "application/octet-stream")`). Reviewer fails any diff that ships two parallel hardcoded dicts.

**Do NOT** add a `"application/octet-stream" → "bin"` fallback to `_MIME_TO_EXT`. Unknown MIMEs continue to raise `ValueError` per HEAD line 39.

### A3. New `validate_attachment_bytes` validator

**File:** `src/probos/attachments/mime.py` (append; do NOT modify existing `validate_image_bytes` or `_SIGNATURES`)

Signature: `def validate_attachment_bytes(blob: bytes, declared_mime: str, declared_filename: str | None = None) -> tuple[bool, str]:`

Per-MIME branches:
- `image/png` / `image/jpeg` / `image/webp` / `image/gif`: delegate to `validate_image_bytes(blob, declared_mime)`. Zero duplication.
- `application/pdf`: magic bytes `b"%PDF-"` at offset 0. Returns `(False, "header_mismatch")` on mismatch, `(False, "blob_too_short")` if `len(blob) < 5`.
- `application/json`: `try: json.loads(blob.decode("utf-8")) except (UnicodeDecodeError, json.JSONDecodeError): return (False, "json_parse_error" or "utf8_decode_error")`. **Use `errors='strict'` on the decode** — `errors='replace'` is a hard-stop anti-pattern (silent corruption is not Tier-2 acceptable for a content-type validator).
- `text/csv`: `csv.reader(io.StringIO(blob[:4096].decode("utf-8", errors="strict")))`; `next(reader)` must succeed and yield ≥ 1 column. On `csv.Error` / `UnicodeDecodeError` / `StopIteration`: return `(False, "csv_parse_error")` or `(False, "utf8_decode_error")`.
- `text/plain` / `text/markdown`: **THREE conditions** must all hold:
  1. `blob.decode("utf-8", errors="strict")` succeeds — else `(False, "utf8_decode_error")`.
  2. `declared_filename` is not None and ends with `.txt` (for `text/plain`) or `.md` (for `text/markdown`) — else `(False, "extension_mismatch")`.
  3. The MIME is in the allow-list (caller verifies before invoking the validator; this is the third tier).

  Reviewer fails any prompt that ships text-type validation by MIME alone, or that uses `errors='replace'`, or that omits the extension check.
- Unknown declared MIME: `(False, "unknown_declared_mime")`.

Return shape mirrors `validate_image_bytes`: `(True, declared_mime)` on success; `(False, reason)` otherwise.

### A4. Shared validation helper (refactor)

**File:** `src/probos/routers/chat.py` (insert after `_get_attachment_store` at line 416, before `@router.post("/chat/attachments")` at line 419)

```python
async def _validate_and_store_attachment(
    runtime: Any,
    blob: bytes,
    declared_mime: str,
    declared_filename: str | None,
    declared_hash_or_None: str | None,
) -> tuple[bool, dict[str, Any]]:
    """AD-720a: shared defense-in-depth chain for both POST endpoints.

    Returns ``(True, response_payload)`` on success, or ``(False, error_dict)``
    where ``error_dict`` is ``{"status_code": int, "body": {...}}``.
    """
```

Validation chain (in order):
1. `cfg.enabled` → else `(False, {"status_code": 503, "body": {"error": "attachments_disabled"}})`.
2. `declared_mime in cfg.allowed_mime_types` → else 415 `mime_not_allowed`.
3. `len(blob) <= cfg.max_attachment_bytes` → else 413 `too_large`.
4. **If `declared_hash_or_None is not None`:** `hashlib.sha256(blob).hexdigest() == declared_hash_or_None.lower()` → else 400 `hash_mismatch`. (Multipart path passes `None` here; JSON path passes `body.content_hash`.)
5. `validate_attachment_bytes(blob, declared_mime, declared_filename)` returns `(True, _)` → else 415 `magic_mismatch`.
6. `actual_hash = hashlib.sha256(blob).hexdigest()` (computed once; idempotent re-use of step-4 hash if available).
7. `await store.write(actual_hash, blob, declared_mime)` — wrapped in `try/except ValueError` → 400 `invalid_attachment` (path traversal / malformed hash; logged at `error` level).
8. Return `(True, {"attachment_id": actual_hash, "url": f"/api/chat/attachments/{actual_hash}", "mime": declared_mime, "size_bytes": len(blob), "sha256": actual_hash})`.

The existing JSON handler at lines 419–533 is refactored to call this helper. Behaviour MUST stay bit-for-bit equivalent — reviewer runs the existing AD-720 paste tests as the regression guard.

### A5. New multipart endpoint

**File:** `src/probos/routers/chat.py` (append, sibling to existing JSON POST)

Update the FastAPI import at line 11:
```python
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
```

New handler:
```python
@router.post("/chat/attachments/multipart")
async def upload_chat_attachment_multipart(
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720a: multipart upload endpoint. UploadFile-based.

    Server reads bytes once via ``await file.read()`` (10 MiB hard cap from
    ``cfg.max_attachment_bytes`` makes one-shot acceptable for v1; streaming
    chunked reads are out of scope). Server computes sha256 — there is no
    client-supplied content_hash on this endpoint. Calls the same shared
    ``_validate_and_store_attachment`` helper as the JSON path.
    """
```

Rules:
- **One read.** `blob = await file.read()`. No second read; `UploadFile.read()` is one-shot in v1.
- **Filename source:** `file.filename` (passed to validator for text-type extension check).
- **MIME source:** `file.content_type` (FastAPI-set from `multipart/form-data`).
- **Hash source:** server-side `hashlib.sha256(blob).hexdigest()` — **no client-supplied hash** on this endpoint. Pass `declared_hash_or_None=None` to the helper.
- On helper-returned `(False, error_dict)`: `return JSONResponse(status_code=error_dict["status_code"], content=error_dict["body"])`.
- On helper-returned `(True, payload)`: `return payload`.
- **No `await store.write` outside the helper.** The endpoint MUST NOT introduce a second blocking-IO path.

### A6. UI drag-drop overlay + file picker

**File:** `ui/src/components/IntentSurface.tsx` (modify; do NOT touch `handlePaste` at line 434 or the paste-related body lines 434–469)

1. **TS constant for allow-list** (top of file with other constants):
   ```typescript
   const ALLOWED_ATTACHMENT_MIMES = [
     'image/png', 'image/jpeg', 'image/webp', 'image/gif',
     'application/pdf', 'text/plain', 'text/markdown',
     'application/json', 'text/csv',
   ] as const;
   ```
   The string is reused as the `<input>` `accept` attribute (joined with `,`).

2. **New helper** `uploadAttachmentMultipart(file: File): Promise<ChatAttachment | null>` — POSTs to `/api/chat/attachments/multipart` via `FormData`. Returns the parsed `AttachmentUploadResponse` or `null` on error. Errors render a `system`-role chat message (`addChatMessage('system', '(Attachment upload failed: <reason>)')`) — **NEVER silent drop**.

3. **Replace the paperclip placeholder** (lines 1909–1934 at HEAD): the `onMouseEnter`/`onMouseLeave`/`onClick` tooltip-only `<button>` becomes a real `<button data-testid="attachment-paperclip" onClick={() => fileInputRef.current?.click()}>` with an inline stroke-SVG plus icon (`strokeWidth: 1.5`, `strokeLinecap: 'round'`). Hidden `<input ref={fileInputRef} type="file" multiple accept={ALLOWED_ATTACHMENT_MIMES.join(',')} onChange={onFilePickerChange} style={{display: 'none'}} />`.

4. **Drag-drop overlay** on the composer wrapper:
   - `onDragEnter`/`onDragOver`/`onDragLeave` track an `isDragOver` state.
   - When `isDragOver`, render `<div data-testid="drag-drop-overlay">` with a stroke-SVG cloud-arrow-up icon and the text "Drop to attach".
   - `onDrop` iterates `event.dataTransfer.files` and routes each through `uploadAttachmentMultipart`.
   - **No emoji.** All affordances are inline SVG (HXI Design Principle #3).

5. **Preview strip extension** (line 1837 `attachment-preview-strip`):
   - For `image/*` MIME: existing `<img>` rendering stays unchanged.
   - For non-image MIME: render a stroke-SVG file icon + filename badge + size. The remove button (`data-testid="attachment-remove"`) keeps the same testid and `onClick` behaviour.
   - Filename source for non-image: store the `File.name` from the picker/drop event in `pendingAttachments[i].filename`. Extend `ChatAttachment` in `ui/src/store/types.ts` with optional `filename?: string`.

6. **`handlePaste` (line 434) is NOT modified.** Reviewer fails any diff that touches its body.

7. **Send-path** (line 248) is NOT modified — the `attachment_ids` array continues to be sent as before. AD-720d is what wires the server-side handling.

### A7. Tests — Python (≥ 10)

**New file:** `tests/test_ad720a_multipart.py`

| # | Test | Validates |
|---|---|---|
| 1 | `test_multipart_post_png_happy` | Multipart PNG upload → 200, response includes `attachment_id`/`url`/`size_bytes`/`sha256`. |
| 2 | `test_multipart_post_pdf_happy` | Multipart PDF (with `%PDF-` magic) → 200. |
| 3 | `test_multipart_post_text_happy` | Multipart `.txt` (UTF-8, content-type `text/plain`) → 200. |
| 4 | `test_multipart_post_json_happy` | Multipart `.json` with valid JSON body → 200. |
| 5 | `test_multipart_post_csv_happy` | Multipart `.csv` with valid first row → 200. |
| 6 | `test_multipart_post_oversize_returns_413` | Blob > `max_attachment_bytes` → 413 `too_large`. |
| 7 | `test_multipart_post_disallowed_mime_returns_415` | `image/svg+xml` → 415 `mime_not_allowed`. |
| 8 | `test_multipart_post_magic_mismatch_returns_415` | PNG bytes declared as `application/pdf` → 415 `magic_mismatch`. |
| 9 | `test_multipart_post_attachments_disabled_returns_503` | `cfg.enabled = False` → 503 `attachments_disabled`. |
| 10 | `test_multipart_post_text_extension_mismatch_returns_415` | Valid UTF-8 bytes but filename `.bad`, declared `text/plain` → 415 `magic_mismatch` (extension check failed). |
| 11 | `test_helper_extraction_regression_json_path_still_200` | Existing AD-720 paste path: `POST /api/chat/attachments` (JSON+base64) with a known-good PNG still returns 200 with the same response shape after the helper extraction. **This is the JSON-path regression guard.** |

Use FastAPI's `TestClient` with `client.post("/api/chat/attachments/multipart", files={"file": ("name.ext", blob, mime)})`. Reuse `tmp_path` for the attachment dir. Fixture pattern from `tests/test_ad720_attachments_endpoint.py` (existing AD-720 test file at HEAD).

> **Test gate command (single file):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad720a_multipart.py -v -n 0 --timeout=60`. **Wave gate:** `pytest tests/ -q -n 4 --dist=loadfile` is green. **The existing `tests/test_ad720_*.py` files MUST stay green without modification.**

### A8. Tests — UI Vitest (≥ 4)

**New file:** `ui/src/__tests__/IntentSurface.dragDrop.test.tsx` — mirror the existing `IntentSurface.imagePaste.test.tsx` shape.

| # | Test | Validates |
|---|---|---|
| 1 | `test_drag_drop_overlay_shows_on_dragenter` | `fireEvent.dragEnter` on the composer makes `data-testid="drag-drop-overlay"` visible; `fireEvent.dragLeave` hides it. |
| 2 | `test_file_picker_accept_lists_all_9_mimes` | Hidden `<input type="file">` `accept` attribute string includes all 9 MIMEs (`image/png`, ..., `text/csv`). |
| 3 | `test_preview_renders_filename_badge_for_text_upload` | Drop a `.txt` `File` → preview strip renders a `data-testid="attachment-preview"` containing the filename text (NOT an `<img>`). |
| 4 | `test_error_toast_on_oversize_or_mime_reject` | Mock fetch returning 413 / 415 / 400 → a `system`-role chat message appears with the structured error reason. |
| 5 | `test_no_emoji_in_drag_drop_or_picker_affordances` | DOM scan asserts zero emoji codepoints in the drag-drop overlay and the picker button (HXI Design Principle #3). |
| 6 | `test_paste_handler_unchanged_regression` | Re-run the existing paste test scenario (paste a fixture PNG `Blob`) — POST goes to `/api/chat/attachments` (JSON), preview renders an `<img>`. **JSON-path UI regression guard.** Re-export from the existing `IntentSurface.imagePaste.test.tsx` if cleaner, or add as a separate `it()` block in the new file. |

> **Build gate (UI — HARD RULE):** `cd ui && npm run build` MUST pass AFTER writing code and BEFORE pushing. Wave 137's broken TypeScript build was the most expensive miss this week. Run `cd ui && npm run build` as a pre-push gate alongside `cd ui && npx vitest run`.

## 7. Cross-AD coordination (post-AD-720a state for AD-720d)

After this commit lands, AD-720d's prompt SEARCH/REPLACE blocks against `config.py` will see:
- `AttachmentsConfig` with 7 fields (`enabled`, `attachments_dir`, `max_attachment_bytes`, `allowed_mime_types` (9 MIMEs), `vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`).
- The new `vision_tier` `field_validator`.

AD-720d does NOT touch `config.py`. AD-720d uses `runtime.config.attachments.vision_tier`, `.text_extraction_max_bytes`, `.pdf_extraction_enabled` — all post-N field reads.

## 8. Hard-stop conditions for the Builder

Standard hard-stops from `BUILDER-EXECUTION-PLAN.md` apply, **plus**:

1. **`python-multipart` import fails in `.venv` and Builder adds it as a dep without a precondition AD.** Hard stop. Surface to Captain — dispatch's "no new deps" rule overrides; AD-720a-0 is the right place for the dep-add. Pre-flight `python -c "import multipart"` and record in build report.
2. **`aiofiles` added to `pyproject.toml` or imported.** Hard stop. Use the existing `asyncio.to_thread` pattern in `FilesystemAttachmentStore`.
3. **`libmagic` / `python-magic` added.** Hard stop. Use stdlib magic-byte sniffs.
4. **`pypdf` / `PyPDF2` / `python-docx` / `openpyxl` added.** Hard stop. PDF/DOCX/XLSX extraction is AD-720a-1.
5. **`handlePaste` body modified.** Hard stop. Reviewer greps `ui/src/components/IntentSurface.tsx` lines 434–469 for any diff.
6. **Existing JSON `POST /api/chat/attachments` response shape changed.** Hard stop. Verify via the existing AD-720 paste test staying green at this commit (`tests/test_ad720_attachments_endpoint.py`).
7. **Existing GET `/api/chat/attachments/{content_hash}` behaviour changed.** Hard stop.
8. **Validation chain copy-pasted into the multipart handler instead of using the shared helper.** Hard stop (DRY violation; reviewer's most common fail mode for parallel-endpoint patterns).
9. **`errors='replace'` on UTF-8 decode in the validator.** Hard stop. Strict only.
10. **Text-type validation by MIME alone.** Hard stop. Three conditions: extension match AND content-type allowlist AND strict UTF-8 decode.
11. **Emoji literal in the diff.** Hard stop. Inline stroke-SVG only (HXI Design Principle #3).
12. **`pyproject.toml [project.dependencies]` modified.** Hard stop. Reviewer runs `git diff <pre>..<post> -- pyproject.toml` — any change in the deps section fails.
13. **`cd ui && npm run build` not run before push, OR fails when run.** **HARD STOP — Wave 137's broken TypeScript build was the most expensive miss this week.** Builder MUST run `cd ui && npm run build` AFTER writing code and BEFORE pushing.
14. **AD-720d work mixed into this commit.** Hard stop. AD-720d is commit N+1; this commit must NOT touch the chat-handler routing branch, `vision_dispatch.py`, or `text_extractor.py`.
15. **`.gitignore` regression** for `data/attachments/*`. Hard stop (audit `git status --ignored data/attachments` post-commit).
16. **Working-tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to Captain.
17. **Architectural change required** (modify `BaseAgent`/`IntentMessage`/`ChatRequest` core protocols). Hard stop.

## 9. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specifically (Builder confirms each in the build report):
- **DRY (HARD CONSTRAINT):** `_validate_and_store_attachment` is the single helper; both POST handlers call it. `_MIME_TO_EXT` is the single source of truth for MIME ↔ extension mapping; the GET endpoint's reverse lookup uses it (no parallel hardcoded dict).
- **Defense in depth:** the chain (allowlist → size → hash → magic-bytes → store) runs on BOTH endpoints. Text MIMEs add the third tier (extension check). Magic-byte validators are stdlib-only.
- **Cloud-Ready Storage:** new code depends on the `AttachmentStore` Protocol. The lazy `_get_attachment_store(runtime)` factory stays the seam — multipart calls it, JSON path calls it.
- **Async discipline:** `await file.read()` (one-shot, 10 MiB cap). All `AttachmentStore` calls are already async. No fire-and-forget. No `asyncio.ensure_future`.
- **Three-tier exception handling:**
  - **Propagate (security):** path-traversal `ValueError` (logged at `error` level, returned as 400 `invalid_attachment`).
  - **Log-and-degrade:** UTF-8 decode / JSON parse / CSV parse errors (returned as structured 415 / 400; never silent drop).
  - **Swallow:** none. Every reject path returns a structured error.
- **Configuration via Pydantic:** all new `AttachmentsConfig` fields have sensible defaults. `vision_tier` `field_validator` rejects bad values at parse time (Fail Fast). `allowed_mime_types` stays under `Field(default_factory=lambda: [...])`.
- **No private-attr access:** the new endpoint and helper consume only public names from `AttachmentStore`, `AttachmentsConfig`. No `runtime._something` reach-through.
- **No emoji in HXI** (HXI Design Principle #3): drag-drop overlay icon, `+ Upload` button, non-image preview badges — all stroke-SVG.
- **Logging quality:** every reject path includes context (declared MIME vs sniffed, size vs cap, content_hash prefix, filename when present).
- **Type annotations:** every new public function (`validate_attachment_bytes`, `_validate_and_store_attachment`, `upload_chat_attachment_multipart`) is fully typed. The Pydantic config additions follow the existing model pattern.
- **No new top-level deps:** `pyproject.toml [project.dependencies]` is bit-for-bit identical between pre-Wave-139 and post-AD-720a commits.

## 10. Acceptance criteria

- All ≥ 10 Python tests + ≥ 4 Vitest tests pass.
- `pytest tests/ -q -n 4 --dist=loadfile` is green at this commit.
- `cd ui && npx vitest run` is green at this commit.
- **`cd ui && npm run build` is green at this commit.** (HARD RULE — Wave 137's broken TypeScript build was the most expensive miss this week. Builder MUST run this AFTER writing code and BEFORE pushing.)
- Existing `tests/test_ad720_attachment_store.py`, `tests/test_ad720_mime_validator.py`, `tests/test_ad720_attachments_endpoint.py`, and `ui/src/__tests__/IntentSurface.imagePaste.test.tsx` stay green **without modification**.
- `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-720a-file-upload-v1.md` reports zero true phantoms (the new symbols introduced by this prompt — `_validate_and_store_attachment`, `validate_attachment_bytes`, `upload_chat_attachment_multipart`, `ALLOWED_ATTACHMENT_MIMES`, `uploadAttachmentMultipart`, `attachment-paperclip`, `drag-drop-overlay` — are expected false positives; note in build report).
- `git diff <pre>..<post> -- pyproject.toml` shows no changes in `[project.dependencies]`.
- GH issue [#549](https://github.com/seangalliher/ProbOS/issues/549) closed in the merge commit.
- `git status --ignored data/attachments` post-commit shows only `.gitkeep` tracked; any blob is ignored.
- AD-720d's commit is the **immediately-following** commit in `git log`.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

**Files touched (target list):**
- **New:** `tests/test_ad720a_multipart.py`, `ui/src/__tests__/IntentSurface.dragDrop.test.tsx`.
- **Modified:** `src/probos/config.py` (extend `AttachmentsConfig`), `src/probos/attachments/filesystem_store.py` (extend `_MIME_TO_EXT`), `src/probos/attachments/mime.py` (append `validate_attachment_bytes`), `src/probos/routers/chat.py` (new helper + new multipart handler + JSON-path refactor + GET reverse-lookup DRY-ification), `ui/src/components/IntentSurface.tsx` (file picker + drag-drop + preview strip extension), `ui/src/store/types.ts` (optional `filename` on `ChatAttachment`).
- **Untouched (hard stop if modified):** `src/probos/api_models.py` (`ChatRequest` + `AttachmentUploadRequest` stay bit-for-bit), `src/probos/cognitive/llm_client.py` (AD-720d's territory), `src/probos/types.py` (`LLMRequest` is AD-720d), `pyproject.toml`, `handlePaste` body in `IntentSurface.tsx` lines 434–469.

## 11. Forward markers (file at gate-3 per `BUILDER-EXECUTION-PLAN.md` Post-Sweep step 6)

| Marker | Scope |
|---|---|
| **AD-720a-0** | (Conditional) Add `python-multipart` as an explicit Python dep if the pre-flight `import multipart` probe fails. License-clean (MIT). Only filed if the pre-flight surfaces the gap. |
| **AD-720a-1** | Add `pypdf` (PDF text extraction), `python-docx` (`.docx`), `openpyxl` (`.xlsx`). All MIT/BSD. License review at that AD. Wires the `pdf_extraction_enabled=True` path; AD-720d's PDF stub flips to real extraction. |
| **AD-720d** | Vision pipe-through (commit N+1, this wave). |
| **AD-720d-1** | Multi-image batch send: latency, prompt-context budget, degradation behaviour. |
| **AD-720d-2** | Per-agent vision capability designation. |
| **AD-720b** | Tool-attach (BrowserTool from AD-706, MCP tools from AD-449) — chat-scoped capability grants. |
| **AD-720c** | Cloud file picker (OneDrive / GDrive). Public marker is technical-only; commercial scope private. |
| **AD-720e** | Audio attachments (`audio/wav` etc.) — voice/transcription pipeline. Tracking only; not yet filed as GH issue. |

## 12. AD-numbering

Highest pre-existing AD at HEAD: **AD-721i** (per `PROGRESS.md` L11, confirmed 2026-05-10). Wave 138 added no new AD numbers (single-prompt wave AD-721b).

This wave allocates: **AD-720a** (this prompt) and **AD-720d** (commit N+1). Both numbers were reserved as forward markers in the AD-720 archive (commit Wave 135). No collisions.

Drafter re-greps `DECISIONS.md` and `decisions-era-*.md` for any `AD-720a` / `AD-720d` body labels before the Builder dispatches — none present at HEAD 2026-05-10.

## 13. Build order note

**Hard order: AD-720a is commit N, AD-720d is commit N+1.**

`pytest tests/ -q -n 4 --dist=loadfile` MUST be green at BOTH commits. AD-720d's `tests/test_ad720d_vision_pipethrough.py` test file imports from the post-AD-720a state of `src/probos/config.py` (the three new fields) — if commits are reordered, AD-720d test file fails to import.
