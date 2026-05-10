# WAVE 139 DISPATCH — File upload (multipart) + Vision pipe-through — AD-720a + AD-720d

**Wave:** 139
**Mode:** main
**Depends on:** 135 (AD-720 v1 image paste, [#514](https://github.com/seangalliher/ProbOS/issues/514) — `AttachmentStore` Protocol, `FilesystemAttachmentStore`, JSON+base64 POST `/api/chat/attachments`, GET `/api/chat/attachments/{hash}`, `AttachmentsConfig`, `validate_image_bytes`).
**Builder required:** yes
**Issues to close:** [#549](https://github.com/seangalliher/ProbOS/issues/549) (AD-720a), [#552](https://github.com/seangalliher/ProbOS/issues/552) (AD-720d).
**Date:** 2026-05-10

---

## 1. Goal

Wave 135 shipped AD-720 v1 — image paste from clipboard. On 2026-05-10 Captain pasted Ezri's avatar and Ezri replied "I have no visual input capability. Image processing is not part of the current configuration." That's correct per the AD-720d deferral, but the gap is now visible. Captain explicitly asked about vision pipe-through during Wave 137 wrap. **Wave 139 closes the two pieces of the AD-720 three-axis split that v1 deferred.**

- **AD-720a** (commit N) — file upload via `UploadFile` + `multipart/form-data`. Adds drag-drop overlay + `+ Upload` button on the IntentSurface composer. Reuses the existing `AttachmentStore` Protocol and `FilesystemAttachmentStore` from Wave 135. Adds a multipart endpoint **alongside** the JSON+base64 path (image paste keeps working bit-for-bit). Extends the allow-list with PDF / plain text / JSON / CSV.
- **AD-720d** (commit N+1) — vision pipe-through. Wires the dead `ChatRequest.attachment_ids` field (verified at HEAD: UI sends it, server ignores it — `git grep "attachment_ids" -- 'src/probos/**/*.py'` returns zero matches inside any handler) into the chat path. Image attachments route to a vision-capable LLM via the existing `LLMClient` tier system. Non-image attachments get inline text extraction and a clearly-delimited `<ATTACHMENT>` block appended to the prompt.

**Hard scope constraints (no Captain ruling needed — pre-applied):**

1. AD-720a v1 = drag-drop + `+ Upload` button. Multipart endpoint additive, JSON+base64 path **not removed**.
2. AD-720a allowed types extend to: PDF, `.txt`/`.md` plain text, JSON, CSV. **No `.docx`/`.xlsx`** (defer to AD-720a-1 — needs `python-docx` / `openpyxl` deps not in `pyproject.toml`).
3. AD-720a max-size cap stays at `chat.max_attachment_bytes` (10 MiB). Single source of truth.
4. AD-720d uses the runtime's existing `LLMClient` tier system. **No new LLM provider deps.**
5. AD-720d: **PDF text extraction is deferred to AD-720a-1** because neither `PyPDF2` nor `pypdf` is in `pyproject.toml` at HEAD (`git grep "pypdf\|PyPDF" -- pyproject.toml` returns empty). v1 ships text/JSON/CSV extraction (stdlib only). PDF can be uploaded and previewed but its bytes are not extracted into the prompt — agent says "I see a PDF named X.pdf attached but PDF text extraction is not yet wired."
6. No emoji in HXI. Drag-drop affordances stroke-SVG only.
7. Defense in depth: same magic-bytes + extension + content-type validation pattern as v1, extended to the new types.
8. **Build order is HARD**: AD-720a ships first (commit N) — adds endpoints + extended config + UI. AD-720d ships second (commit N+1) — wires the routing.

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `src/probos/attachments/store.py` `AttachmentStore` Protocol + `_resolve_attachments_dir` | Verified at HEAD lines 14–58. Async `write/read/exists/get_path/size`, content-addressed by sha256, path-traversal-safe resolver mirroring `routers/system.py:_resolve_avatars_dir`. | **Reuse verbatim.** AD-720a does NOT extend the Protocol — multipart upload still calls `store.write(content_hash, blob, mime)`. The existing 5 methods cover everything multipart needs. |
| `src/probos/attachments/filesystem_store.py` `FilesystemAttachmentStore._MIME_TO_EXT` | Verified at HEAD lines 23–28. Hardcoded 4-image dict (`png/jpeg/webp/gif`). | **Extend to a module-level table mapping every allowed MIME to its extension.** New entries: `application/pdf → pdf`, `text/plain → txt`, `text/markdown → md`, `application/json → json`, `text/csv → csv`. Reviewer fails the prompt if `_MIME_TO_EXT` is duplicated — there must be one source of truth, used by both write-path extension selection and the GET endpoint's reverse lookup. |
| `src/probos/attachments/mime.py` `validate_image_bytes(blob, declared_mime) -> (ok, sniffed_or_reason)` | Verified at HEAD lines 21–53. Magic-byte signatures table for the 4 image MIMEs; alternative-vs-conjunction support via `_ANY_OF`. | **Add a new sibling validator `validate_attachment_bytes(blob, declared_mime, declared_filename) -> (ok, reason)`** in the same module. Image MIMEs delegate to `validate_image_bytes` (no duplication). PDF: magic bytes `%PDF-` at offset 0. JSON: parse-attempt with a bounded reader (no full-tree walk; just `json.loads` of the bytes — already O(n) but bounded by the 10 MiB cap). CSV: parse first row via `csv.reader` on a `StringIO` of the first 4 KiB; reject if `Error` raised. text/plain + text/markdown: NO magic bytes, validate by **(a)** extension match (`.txt` / `.md`) AND **(b)** content-type allow-list AND **(c)** strict UTF-8 decode (`bytes.decode('utf-8', errors='strict')`). Reviewer fails any prompt that uses `errors='replace'` for the text-validation path — silent corruption is not Tier-2 acceptable for a content type validator. |
| `src/probos/api_models.py` `ChatRequest.attachment_ids: list[str]` | Verified at HEAD lines 20–24. Field is plumbed from UI but `git grep "attachment_ids" -- 'src/probos/**/*.py'` returns zero matches inside any router/agent/handler — the field is currently dead on the server side. | **AD-720d wires this for the first time.** No model change needed for AD-720d. AD-720a does NOT touch `ChatRequest`. |
| `src/probos/routers/chat.py` POST `/api/chat/attachments` (lines 419–533) + GET `/api/chat/attachments/{content_hash}` (lines 537–567) | Verified at HEAD. POST is JSON-only (`AttachmentUploadRequest` model with `content_hash`/`blob_b64`/`mime`). GET serves by sha256 with extension→MIME inference. `_get_attachment_store(runtime)` is the lazy-cached factory at lines 404–416. | **AD-720a adds `POST /api/chat/attachments/multipart`** as a sibling endpoint. The JSON path is **not removed**. The new multipart endpoint takes a single `UploadFile = File(...)`; server computes sha256 of the streamed bytes, runs the new `validate_attachment_bytes` validator, and writes through the same `_get_attachment_store(runtime)` factory. **Zero behaviour change to the JSON path or the GET path.** Reviewer fails any diff that mutates the JSON-path branch. |
| `src/probos/config.py` `AttachmentsConfig` (lines 941–954) | Verified at HEAD. Fields: `enabled: bool = True`, `attachments_dir: str = "data/attachments"`, `max_attachment_bytes: int = 10*1024*1024`, `allowed_mime_types: list[str]` (default 4 image MIMEs via `Field(default_factory=...)`). Pydantic v2 `BaseModel`. | **Extend `allowed_mime_types` default to the 9-MIME list:** `image/png, image/jpeg, image/webp, image/gif, application/pdf, text/plain, text/markdown, application/json, text/csv`. **Add `vision_tier: str = "standard"`** (AD-720d field — drives the LLMClient tier choice when an image attachment is present). **Add `text_extraction_max_bytes: int = 1*1024*1024`** (AD-720d — cap on bytes appended to the prompt; oversize text/JSON/CSV gets truncated with a `[TRUNCATED]` marker). **Add `pdf_extraction_enabled: bool = False`** with a comment pointing at AD-720a-1 — defaults False because PDF extraction is deferred. Drafter must keep mutable list defaults under `Field(default_factory=lambda: [...])` per existing pattern (private memory pattern: bare mutable defaults in Pydantic models are a review blocker). |
| `src/probos/cognitive/llm_client.py` `OpenAICompatibleClient` tier system | Verified at HEAD lines 46–207. Three tiers (fast/standard/deep), per-tier `httpx.AsyncClient` deduped by `(base_url, api_format)`, model name resolved from `tier_config(tier)`. `complete(request: LLMRequest, *, priority)` is the entry point. `LLMRequest` is in `probos/types.py`. | **Read-only at the LLMClient level.** AD-720d does NOT modify `OpenAICompatibleClient`. The vision dispatch module formats messages and selects the configured `vision_tier` (default `"standard"` — `claude-sonnet-4-6` per the HEAD default, which is multimodal-capable). If `vision_tier` resolves to an unhealthy tier, AD-720d falls back to a text-only stub message and logs a structured warning — never silent drop. |
| UI `ui/src/components/IntentSurface.tsx` paperclip placeholder + paste handler | Verified at HEAD lines 63–65 (`pendingAttachments` state + `paperclipTooltipOpen` flag), 243–248 (POST body includes `attachment_ids`), 411–469 (`handlePaste` — clipboard image only, JSON+base64 POST). Test `ui/src/__tests__/IntentSurface.imagePaste.test.tsx` covers paste / preview / remove / oversize / mime-reject. | **Extend the paperclip into a real file picker.** Replace the tooltip-only placeholder with a `<button>` opening a hidden `<input type="file" multiple accept="...">` (the `accept` attribute lists the 9 allowed MIMEs verbatim from `AttachmentsConfig.allowed_mime_types` — drafter pins via a TS constant that the prompt declares). Add a drag-drop overlay covering the composer surface; on drop, route each file through the same upload helper that the file picker uses. **Paste path stays bit-for-bit unchanged.** Reviewer fails any diff that touches `handlePaste`. |
| Vision pipe-through prior art (no upstream) | Pattern absorption from `OpenAICompatibleClient` shape. Anthropic / OpenAI multimodal message format is industry-standard `{role, content: [{type: "text" | "image_url" | "image", ...}]}` — neither vendor's SDK is needed; the existing httpx-based client posts JSON to `/v1/chat/completions` already. | **Pure pattern absorption.** AD-720d adds `src/probos/cognitive/vision_dispatch.py` (new module) that builds the multimodal `messages` payload from `(prompt: str, attachment_ids: list[str], store: AttachmentStore) -> list[dict]`. Implementation reads each attachment's bytes, base64-encodes it, and appends an `{type: "image", source: {type: "base64", media_type, data}}` content-item per image — Anthropic's documented format (also accepted by Claude 4 family via the existing Copilot proxy at `127.0.0.1:8080`). For non-image attachments, the helper extracts text via the new `text_extractor` module (also new, in `src/probos/cognitive/text_extractor.py`) and appends a delimited block. **Zero new third-party deps. Zero new LLM provider SDKs.** |

**Top-level license posture:** Apache 2.0 stays Apache 2.0. **Zero new Python deps in v1.** Zero new JS deps. The deferred `python-docx` / `openpyxl` / `pypdf` adoption goes through AD-720a-1 with explicit license review at that time (all three are MIT/BSD, but the dep-add must be its own AD).

---

## 3. Engineering-principles checklist

Builder must verify each in the per-AD prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Tier-3 propagate (security)** | AD-720a defense-in-depth | Path traversal, malformed hash, magic-byte mismatch, oversize, unknown MIME — all return structured error JSON with appropriate HTTP status (400/413/415/503). **No `except Exception: pass`** anywhere in the upload validator chain. |
| **Tier-2 log-and-degrade** | AD-720d vision-tier failure, text-extraction failure | If the vision tier is unreachable, log `logger.warning("AD-720d vision dispatch unavailable for tier=%s; falling back to text-only message naming the attachments", tier)` and append a text-only `<ATTACHMENT name="..." mime="..." note="vision unavailable" />` block. Speech path / chat path **never silently drops** the attachment. |
| **DRY (HARD CONSTRAINT)** | AD-720a multipart vs JSON path | The validation chain (MIME allowlist → size cap → sha256 → magic-byte sniff → idempotent write) MUST be extracted into one helper `_validate_and_store_attachment(store, blob, declared_mime, declared_hash_or_None) -> (success_dict | error_response)`. Both POST handlers (JSON and multipart) call the helper. **Reviewer fails any diff that copy-pastes the validation chain into the multipart handler.** Existing JSON handler (lines 419–533) is refactored to call the helper as part of AD-720a; behaviour stays bit-for-bit. |
| **Defense in depth** | AD-720a magic-byte validators for new types | PDF (`%PDF-`), JSON (parse-attempt), CSV (first-row parse-attempt), text/plain + text/markdown (extension + content-type + strict UTF-8). Reviewer fails any prompt that ships text-type validation by MIME alone. |
| **Cloud-Ready Storage** | AD-720a + AD-720d | New code depends on the `AttachmentStore` Protocol (`store.py`), never on `FilesystemAttachmentStore` directly. The lazy factory `_get_attachment_store(runtime)` (lines 404–416) stays as the seam — multipart calls it, vision dispatch calls it. Commercial-overlay swap remains intact. |
| **No emoji in HXI** (HXI Design Principle #3) | AD-720a UI | Drag-drop affordance is stroke-SVG only. The `+ Upload` button uses an inline `<svg>` plus icon (stroke-width 1.5, round caps, amber active / dim inactive per the HXI palette — same pattern as the existing paperclip placeholder). Reviewer fails on any emoji literal in the diff. |
| **Async discipline** | AD-720a multipart streaming, AD-720d store reads | UploadFile reads use the FastAPI async API (`await file.read()` in one shot is acceptable because `max_attachment_bytes` is hard-capped at 10 MiB; streaming chunked reads are out of scope for v1). All `AttachmentStore` calls are already async. AD-720d's `vision_dispatch.build_multimodal_messages` is async (it calls `store.read`). No fire-and-forget. No `asyncio.ensure_future`. |
| **Fail Fast** | AD-720a config validation | `AttachmentsConfig` extension uses Pydantic `field_validator` to reject `vision_tier` values not in `{"fast", "standard", "deep"}` at parse time, not at dispatch time. |
| **No private-attr access** | AD-720d wiring | `vision_dispatch` consumes only public names from `LLMClient`, `AttachmentStore`, `AttachmentsConfig`. Reviewer fails any `runtime._something` reach-through. |
| **No new top-level deps** | Whole wave | `pyproject.toml` is **unchanged in this wave**. Reviewer fails any diff that touches `[project.dependencies]`. PDF / DOCX / XLSX deps are AD-720a-1's problem. |
| **Test gates** | All deliverables | AD-720a: ≥ 10 Python (multipart 200 happy path, multipart MIME-not-allowed 415, multipart oversize 413, multipart sha256 mismatch 400, multipart magic-byte mismatch 415 for PDF, multipart text/plain UTF-8 reject 400, multipart JSON parse reject 400, multipart CSV first-row reject 400, multipart attachments-disabled 503, helper extraction regression — JSON path still returns 200 on a known-good blob). AD-720d: ≥ 8 Python (vision-tier image routing builds the right multimodal payload, text/plain inline extraction appended, text/markdown inline extraction appended, JSON inline extraction appended, CSV inline extraction appended, oversize text gets truncated with `[TRUNCATED]` marker, vision tier unavailable falls back to text-only stub naming the attachment, PDF attachment with `pdf_extraction_enabled=False` produces the deferred-feature stub). UI: ≥ 4 Vitest (drag-drop overlay shows on dragenter, file picker accepts the 9 MIMEs, preview strip renders a non-image filename for non-image attachments, error toast on oversize / mime-reject / hash-mismatch). |

---

## 4. AD-720a v1 scope (commit N — ships first)

**Issue:** [#549](https://github.com/seangalliher/ProbOS/issues/549).

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **A1** | Extended config | `src/probos/config.py` `AttachmentsConfig` | `allowed_mime_types` default extends to 9 MIMEs (verbatim list above). New `text_extraction_max_bytes: int = 1*1024*1024`. New `pdf_extraction_enabled: bool = False` (commented as AD-720a-1 forward marker). New `vision_tier: str = "standard"` with a `field_validator` rejecting values outside `{"fast", "standard", "deep"}`. **AD-720d also adds fields to this model** — drafter MUST coordinate the two prompts so AD-720d's prompt SEARCH/REPLACE matches the post-AD-720a state of the file. |
| **A2** | Extended `_MIME_TO_EXT` | `src/probos/attachments/filesystem_store.py` | Module-level dict expands to 9 entries. Hardcoded fallback `"application/octet-stream" → "bin"` is **NOT** added — unknown MIMEs must continue to raise `ValueError` per existing behaviour at HEAD line 39. Reviewer fails any diff that loosens that contract. |
| **A3** | New attachment validator | `src/probos/attachments/mime.py` | Add `validate_attachment_bytes(blob: bytes, declared_mime: str, declared_filename: str | None = None) -> tuple[bool, str]`. Image MIMEs delegate to existing `validate_image_bytes`. PDF: magic `%PDF-`. JSON: bounded `json.loads(blob.decode('utf-8', errors='strict'))` — wrap in try/except returning `(False, "json_parse_error")` or `(False, "utf8_decode_error")`. CSV: first-row parse via `csv.reader(io.StringIO(blob[:4096].decode('utf-8', errors='strict')))` — `next(reader)` must succeed and return ≥ 1 column. Text: `blob.decode('utf-8', errors='strict')` succeeds AND `declared_filename` ends with `.txt` (for `text/plain`) or `.md` (for `text/markdown`). Reviewer flags any other arrangement. |
| **A4** | Multipart endpoint | `src/probos/routers/chat.py` (new handler, sibling to existing JSON POST) | New `@router.post("/chat/attachments/multipart")` with signature `async def upload_chat_attachment_multipart(file: UploadFile = File(...), runtime: Any = Depends(get_runtime)) -> dict[str, Any]:`. Reads bytes once via `await file.read()`. Server computes sha256 (no client-supplied hash). Calls the new shared helper `_validate_and_store_attachment(...)`. Returns the same response shape as the JSON endpoint (`{attachment_id, url, mime, size_bytes, sha256}`). MIME source: `file.content_type` (FastAPI-set from `multipart/form-data`). Filename source: `file.filename` (passed to the validator for text-type extension check). |
| **A5** | Shared validation helper | `src/probos/routers/chat.py` (refactor) | New module-private `async def _validate_and_store_attachment(runtime, blob, declared_mime, declared_filename, declared_hash_or_None) -> tuple[bool, dict]`. Returns `(True, response_payload)` on success or `(False, JSONResponse(...) `-shape error dict). Existing JSON POST is refactored to call this helper — reviewer verifies bit-for-bit response equivalence by running the existing AD-720 paste test (`tests/test_chat_attachments_*`) against the refactored code as part of A4's CI gate. |
| **A6** | UI drag-drop overlay + file picker | `ui/src/components/IntentSurface.tsx` (extend) | Replace the tooltip-only paperclip with a real `<button data-testid="attachment-paperclip">` that opens a hidden `<input ref={fileInputRef} type="file" multiple accept="..." onChange={...}>`. The `accept` attribute is built from a TS constant `ALLOWED_ATTACHMENT_MIMES` (9 entries — drafter pins). Add a drag-drop overlay (`onDragEnter` / `onDragOver` / `onDragLeave` / `onDrop` on the composer wrapper); when a drag is in progress, render a `<div data-testid="drag-drop-overlay">` with a stroke-SVG cloud-arrow-up icon (no emoji). On drop OR file-picker change, route each file through the new helper `uploadAttachmentMultipart(file: File): Promise<ChatAttachment>` (added in this AD) which POSTs to `/api/chat/attachments/multipart` via `FormData`. **`handlePaste` is NOT touched.** |
| **A7** | UI preview strip extension | `ui/src/components/IntentSurface.tsx` | Existing `attachment-preview` strip renders only `<img>` tags today. Extend to render an icon + filename badge for non-image attachments. The icon mapping (`pdf` / `text` / `json` / `csv`) is a small switch on MIME prefix — one stroke-SVG per group, no emoji. The remove button (`attachment-remove`) keeps the same testid and behaviour. |
| **A8** | Tests (Python) | `tests/test_ad720a_multipart.py` (new) | ≥ 10 tests per the Engineering Principles checklist row above. Use FastAPI's `TestClient` with `client.post("/api/chat/attachments/multipart", files={"file": ("name.ext", blob, mime)})`. Cover happy path PNG, happy path PDF, happy path text, happy path JSON, happy path CSV, oversize, MIME-not-allowed, magic-mismatch, attachments-disabled, and helper-extraction regression (existing JSON path still 200s). Reuse `tmp_path` for the attachment dir. Fixture lives in `conftest.py` pattern from existing AD-720 tests. |
| **A9** | Tests (Vitest) | `ui/src/__tests__/IntentSurface.dragDrop.test.tsx` (new — mirror the existing `IntentSurface.imagePaste.test.tsx` shape) | ≥ 4 tests: (a) drag-drop overlay appears on `dragenter` and disappears on `dragleave`; (b) file picker `accept` attribute lists all 9 MIMEs; (c) preview strip renders a filename badge (not an `<img>`) for a `.txt` upload; (d) error toast / `system` message on oversize, MIME-not-allowed, hash-mismatch (mock fetch responses 413 / 415 / 400). |

### Wiring

| What | Change |
|---|---|
| Endpoint registration | New POST `/api/chat/attachments/multipart` is added in the same `APIRouter` (`router.post(...)` at module scope in `src/probos/routers/chat.py`). No new router file. |
| Helper visibility | `_validate_and_store_attachment` is module-private (`_` prefix). Not re-exported. |
| `_get_attachment_store(runtime)` | Unchanged. Both endpoints call it. |
| FastAPI imports | Add `UploadFile, File` to the existing `fastapi` import (line 11 at HEAD). |
| Backward compat | JSON+base64 POST `/api/chat/attachments` and GET `/api/chat/attachments/{content_hash}` are bit-for-bit unchanged. The existing AD-720 paste test must stay green. |

---

## 5. AD-720d v1 scope (commit N+1 — ships second)

**Issue:** [#552](https://github.com/seangalliher/ProbOS/issues/552).

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | Vision dispatch module | `src/probos/cognitive/vision_dispatch.py` (new) | Public exports: `async def build_multimodal_messages(prompt: str, attachment_ids: list[str], store: AttachmentStore, store_mime_lookup: Callable[[str], str], *, text_extraction_max_bytes: int) -> list[dict]`. Returns the OpenAI/Anthropic-shape `messages` content array: `[{role: "user", content: [{type: "text", text: ...}, {type: "image", source: {type: "base64", media_type: "image/png", data: "..."}}, ...]}]`. For non-image MIMEs: appends `{type: "text", text: "<ATTACHMENT name=... mime=...>...extracted text...</ATTACHMENT>"}`. The MIME lookup callable lets the caller resolve `attachment_id → mime` via the file extension on disk (the GET endpoint already does this — extract the same logic into a tiny helper exported from `attachments/filesystem_store.py` to avoid duplication). |
| **D2** | Text extractor module | `src/probos/cognitive/text_extractor.py` (new) | Public exports: `async def extract_text(blob: bytes, mime: str, *, max_bytes: int) -> tuple[str, bool]` returning `(extracted_text, was_truncated)`. text/plain + text/markdown: `blob.decode('utf-8', errors='strict')`. JSON: `json.dumps(json.loads(blob.decode('utf-8')), indent=2)` (pretty-print for the LLM). CSV: `blob.decode('utf-8', errors='strict')` — passed through as-is (the LLM handles CSV reasoning natively). PDF: raises `NotImplementedError("AD-720a-1: PDF extraction not yet wired")` — the dispatch layer catches it and produces the stub message. If `len(extracted_text.encode('utf-8'))` > `max_bytes`, truncate at the byte boundary (decode-safe via `text.encode()[:max_bytes].decode('utf-8', errors='ignore')`) and append `\n[TRUNCATED]`. Returns `was_truncated=True` in that case. |
| **D3** | Routing decision in chat path | `src/probos/routers/chat.py` (extend the main `chat` handler) | After the slash-command + DM branches, BEFORE the existing decompose/dispatch path, check: `if req.attachment_ids and runtime.config.attachments.enabled:`. If any attachment is `image/*` (resolved via the filesystem store + extension): instead of the existing decomposer call, build the multimodal messages array via `vision_dispatch.build_multimodal_messages(...)` and call `runtime.llm_client.complete(LLMRequest(messages=..., tier=runtime.config.attachments.vision_tier))` directly. The response text is returned in the standard `{"response": ..., "dag": None, "results": None}` shape (no DAG when in pure-vision-reply mode). For attachment-only-non-image cases (text/JSON/CSV/PDF): append the extracted text block(s) to `req.message`, and proceed through the normal decomposer path with the augmented prompt. |
| **D4** | Vision-tier health fallback | `src/probos/routers/chat.py` (inside D3) | If `runtime.llm_client.get_health_status()["tiers"][vision_tier]["status"] != "operational"`: log structured warning `logger.warning("AD-720d vision tier=%s unavailable; returning text-only stub naming attachments", vision_tier)` and return a stub response of the form `"I see <N> attachment(s) — <comma-list of filenames-or-ids> — but vision processing is currently unavailable. Try again in a moment."` Reviewer fails any silent-drop branch. |
| **D5** | Tests (Python) | `tests/test_ad720d_vision_pipethrough.py` (new) | ≥ 8 tests: (a) image attachment routes to `llm_client.complete` with a multimodal `messages` array (assert content array contains an `image` item); (b) text/plain attachment appends a `<ATTACHMENT>` block to the prompt; (c) text/markdown attachment appends a `<ATTACHMENT>` block; (d) JSON attachment appends a pretty-printed JSON `<ATTACHMENT>` block; (e) CSV attachment appends a CSV `<ATTACHMENT>` block; (f) oversize text/JSON/CSV gets truncated with `[TRUNCATED]` marker; (g) vision tier unhealthy → text-only stub message naming the attachments (assert no LLM call made); (h) PDF attachment with `pdf_extraction_enabled=False` produces a "PDF extraction not yet wired" stub. Use a `MockLLMClient` whose `complete` records the request and returns a canned `LLMResponse`. The store fixture pre-writes blobs under known sha256s. |

### Wiring

| What | Change |
|---|---|
| New module imports in `chat.py` | `from probos.cognitive.vision_dispatch import build_multimodal_messages`. `from probos.cognitive.text_extractor import extract_text`. |
| `LLMRequest` shape | At HEAD `LLMRequest` accepts a `prompt: str` field. AD-720d adds an optional `messages: list[dict] | None = None` field — when set, takes precedence over `prompt`. The OpenAI-compatible client is already posting OpenAI-shape JSON (`messages` array); the change is small and additive. **Reviewer verifies the existing `prompt`-shaped path stays bit-for-bit equivalent when `messages` is None.** Builder must grep `LLMRequest(` across `src/` to confirm no caller breaks. |
| `AttachmentsConfig` fields used | `vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`, `enabled` — all added in AD-720a (commit N), so AD-720d's prompt SEARCH/REPLACE assumes the post-A1 state. |
| `LLMClient` mutation | Zero. AD-720d treats `OpenAICompatibleClient` as read-only. The vision dispatch is a pure formatter. |

---

## 6. What this wave does NOT change

| Out-of-scope | AD | Reason |
|---|---|---|
| `.docx` / `.xlsx` server-side parsing | **AD-720a-1** (forward marker, file in this wave's tracking) | Needs `python-docx` and `openpyxl` — not in `pyproject.toml` at HEAD (verified via `git grep`). License-clean (both MIT) but the dep-add must be its own AD with explicit license review. |
| PDF text extraction | **AD-720a-1** (combined with .docx/.xlsx since the AD already needs to add deps) | Neither `pypdf` nor `PyPDF2` in `pyproject.toml` at HEAD. v1 ships PDF upload but the bytes are not extracted — the deferred stub message names the attachment. |
| Multi-image batch send (e.g. 3 images in one user turn) | **AD-720d-1** (forward marker) | v1 supports multiple `attachment_ids` in the array but the test matrix focuses on single-image. Multi-image latency, prompt-context budget, and degradation behaviour need a separate evaluation. |
| Per-agent vision capability designation (not all crew should have vision) | **AD-720d-2** (forward marker) | v1 routes purely based on attachment MIME, not based on the receiving agent. Captain may want Counselor to "see" but Engineering to text-only. Defer to AD-720d-2. |
| `text_extraction_max_bytes` streaming chunked reads | (not filed) | 10 MiB hard cap from `max_attachment_bytes` makes one-shot reads acceptable for v1. |
| New LLM provider deps (Anthropic SDK, OpenAI SDK) | (not filed; explicit non-goal) | Existing `httpx`-based `OpenAICompatibleClient` posts OpenAI-shape JSON which Anthropic's `/v1/messages` endpoint and the Copilot proxy at `127.0.0.1:8080` both accept. |
| HXI 3D / VRM / lipsync surfaces | (Wave 138 territory) | Wave 139 touches zero VRM / avatar code. |
| Audio attachments (`audio/wav` etc.) | **AD-720e** (not filed; flagged in this prompt for tracking) | Voice/transcription pipeline is a separate concern. v1 explicitly does not add audio MIMEs to the allow-list. |

Reviewer fails the prompt if it touches `voice.ts`, any VRM file, the cognitive canvas, or `pyproject.toml`'s `[project.dependencies]` array.

---

## 7. Tracking

After Wave 139 ships:

1. **`PROGRESS.md`** — flip the AD-720a + AD-720d rows to ✅ in the Wave 139 section. One-line outcome each ("multipart endpoint + drag-drop UI, 9-MIME allow-list, helper extraction" / "vision pipe-through routing, inline text extraction for txt/md/json/csv, vision-tier health fallback").
2. **`docs/development/roadmap.md`** — close Wave 139 row. Add forward-marker rows: AD-720a-1 (`.docx`/`.xlsx`/PDF parsing — needs new deps), AD-720d-1 (multi-image batch), AD-720d-2 (per-agent vision designation). File GH issues for all three (mirror Wave 138's pattern of filing markers as issues).
3. **`DECISIONS.md` + `decisions-era-5-unification.md`** — append AD-720a + AD-720d entries. Cite (a) the JSON-path-stays-untouched constraint, (b) the helper-extraction DRY rule, (c) the vision-tier-fallback never-silent-drop rule, (d) the PDF-deferred-to-AD-720a-1 trade-off (no new deps in this wave), (e) the `LLMRequest.messages` additive field.
4. **GH issues** — close [#549](https://github.com/seangalliher/ProbOS/issues/549) and [#552](https://github.com/seangalliher/ProbOS/issues/552) with summary comments. File AD-720a-1 / AD-720d-1 / AD-720d-2 markers if not already filed.

---

## 8. Acceptance criteria (wave-level)

The Builder must, by the end of the wave:

1. ✅ Two commits, in order: AD-720a (commit N) before AD-720d (commit N+1). Reviewer fails any squash.
2. ✅ `pytest tests/ -q -n 4 --dist=loadfile` green at both commits. Test count delta: ≥ +18 (≥ 10 for AD-720a + ≥ 8 for AD-720d).
3. ✅ `cd ui && npx vitest run` green at commit N (AD-720a UI), test count delta: ≥ +4. (AD-720d adds zero UI tests.)
4. ✅ Existing AD-720 paste tests (`ui/src/__tests__/IntentSurface.imagePaste.test.tsx` and any `tests/test_chat_attachments*`) stay green at both commits. Reviewer fails any modification of the paste-test file body.
5. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-720a-multipart-upload.md` clean.
6. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-720d-vision-pipethrough.md` clean.
7. ✅ `pyproject.toml [project.dependencies]` is **bit-for-bit identical** between pre-Wave-139 and post-Wave-139 commits. Reviewer runs `git diff <pre>..<post> -- pyproject.toml` — any change in the deps section is a hard fail.
8. ✅ Manual smoke (Captain runs after merge): drag a `.txt` file onto the composer → uploads + previews as a filename badge → send → agent quotes the file content. Paste an image → agent describes it (assuming vision tier is operational). Drag a `.pdf` → uploads + previews → send → agent says "PDF extraction not yet wired" (deferred-feature stub).
9. ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 9. Risk classification

| AD | Risk | Subcategory drivers |
|---|---|---|
| **AD-720a** | **MEDIUM** | New endpoint surface + UI surface + config extension. JSON path refactor (helper extraction) is the highest single-source-of-regression — guard with the existing AD-720 paste test staying green. No new deps, no LLM changes. UI drag-drop is well-understood Vitest territory. |
| **AD-720d** | **MEDIUM-HIGH** | Wires a previously-dead `attachment_ids` field into the live chat path. Conditional branch in the main chat handler is the highest-blast-radius change in the wave. The `LLMRequest.messages` additive field is a small but real shape change — Builder must grep all `LLMRequest(...)` call sites to confirm no caller depends on `messages` being absent. Vision-tier health fallback is the never-silent-drop guarantee — under-tested means a real-world outage produces a confusing user experience. |
| **Wave 139 cumulative** | **MEDIUM-HIGH** | Two ADs, one a config + endpoint extension, one a chat-path branch. Build order is HARD — AD-720d's tests assume AD-720a's `AttachmentsConfig` fields exist. If commits are reordered, AD-720d test file fails to import. |

**Subcategories:**
- **Bundle size:** zero new MB (no new JS deps, no new model weights).
- **Browser compatibility:** drag-drop + FormData are universal; no new browser APIs.
- **Backend impact:** one new endpoint, one config extension, two new modules, one chat-handler branch.
- **Regression surface:**
  - AD-720a: JSON paste path (mitigated by helper-extraction regression test).
  - AD-720d: existing chat-path code (mitigated by routing only when `req.attachment_ids` is non-empty AND `cfg.enabled is True` — zero-attachment case is bit-for-bit unchanged).

---

## 10. Wave-specific reminders for the prompt drafter

1. **Build order is HARD.** Two prompts: `prompts/ad-720a-multipart-upload.md` (commit N) and `prompts/ad-720d-vision-pipethrough.md` (commit N+1). The AD-720d prompt's SEARCH/REPLACE blocks for `config.py` MUST match the post-AD-720a state — drafter writes AD-720a first, then drafts AD-720d against the projected post-N file.
2. **`pyproject.toml` is OFF-LIMITS.** No new deps. Both prompts must include this in their "What this does NOT change" section.
3. **The JSON+base64 path is ASLEEP.** Both prompts must explicitly state that `handlePaste` in `IntentSurface.tsx` and the existing `POST /api/chat/attachments` JSON handler are not modified beyond the helper extraction (which is behaviour-preserving). Reviewer fails any diff that materially changes them.
4. **Helper extraction is the DRY anchor.** `_validate_and_store_attachment(runtime, blob, declared_mime, declared_filename, declared_hash_or_None)` is called from BOTH POST handlers. The JSON-path refactor is part of AD-720a — Builder must run the existing AD-720 paste test as the regression guard.
5. **`LLMRequest.messages` is the smallest possible additive change.** Drafter must grep every `LLMRequest(` instantiation across `src/` and add a one-line "verified caller compat" footer to the AD-720d prompt listing all the call sites and confirming none assume `messages is None`.
6. **PDF text extraction is DEFERRED to AD-720a-1.** v1 stops at upload + preview. The text extractor's PDF branch raises `NotImplementedError("AD-720a-1: PDF extraction not yet wired")` and the dispatch layer catches it. **Reviewer fails any prompt that ships PDF parsing code path that depends on a missing dep.**
7. **Vision-tier fallback is the never-silent-drop rule.** The AD-720d prompt MUST include a test for the unhealthy-tier path. Without that test, the silent-drop regression is undefended.
8. **No emoji.** Drag-drop overlay icon, file-picker plus button, non-image preview badges — all stroke-SVG. Reviewer fails on any emoji literal.
9. **Defense-in-depth for text MIMEs has THREE conditions:** extension match AND content-type allowlist AND strict UTF-8 decode. Reviewer fails any prompt that ships `errors='replace'` for the validator.
10. **Verify-first.** Before any concrete file/line/method citation in the prompt body, drafter greps HEAD and pastes the result in the prompt's `## Verified Against Codebase (YYYY-MM-DD)` footer. Especially: every line number cited from `src/probos/routers/chat.py`, `src/probos/attachments/filesystem_store.py`, `src/probos/attachments/mime.py`, `src/probos/config.py`, and `ui/src/components/IntentSurface.tsx` MUST have a grep hit shown. The current Wave 138 dispatch's verified-footer pattern is the template.

---

## Verified Against Codebase (2026-05-10)

```
git log --oneline -1
  87db564 (HEAD -> main, origin/main, origin/HEAD) Wave 138 retrospective: archive prompts

git grep -n "AttachmentStore\|FilesystemAttachmentStore\|AttachmentsConfig\|validate_image_bytes" -- 'src/probos/**/*.py'
  src/probos/attachments/store.py:14: class AttachmentStore(Protocol):
  src/probos/attachments/store.py:43: def _resolve_attachments_dir(configured: str) -> Path:
  src/probos/attachments/filesystem_store.py:30: class FilesystemAttachmentStore:
  src/probos/attachments/mime.py:21: def validate_image_bytes(blob: bytes, declared_mime: str) -> tuple[bool, str]:
  src/probos/config.py:941: class AttachmentsConfig(BaseModel):
  src/probos/config.py:945:    attachments_dir: str = "data/attachments"
  src/probos/config.py:946:    max_attachment_bytes: int = 10 * 1024 * 1024
  src/probos/config.py:3109:    attachments: AttachmentsConfig = Field(default_factory=AttachmentsConfig)

git grep -n "attachment_ids\|attachments_dir\|/chat/attachments" -- 'src/probos/**/*.py'
  src/probos/api_models.py:24: attachment_ids: list[str] = Field(default_factory=list)
  src/probos/routers/chat.py:419: @router.post("/chat/attachments")
  src/probos/routers/chat.py:537: @router.get("/chat/attachments/{content_hash}")
  (zero matches for "attachment_ids" inside any handler — the field is currently dead on the server side)

git grep -n "pypdf\|PyPDF\|python-docx\|openpyxl" -- pyproject.toml
  (no matches — confirms PDF extraction must be deferred to AD-720a-1)

git grep -n "_MIME_TO_EXT\|allowed_mime_types" -- 'src/probos/**/*.py'
  src/probos/attachments/filesystem_store.py:23: _MIME_TO_EXT: dict[str, str] = {
  src/probos/config.py:947:    allowed_mime_types: list[str] = Field(

git grep -n "tier_config\|vision\|multimodal" -- 'src/probos/cognitive/llm_client.py'
  src/probos/cognitive/llm_client.py:101: for tier in ("fast", "standard", "deep"):
  src/probos/cognitive/llm_client.py:102:     self._tier_configs[tier] = self._config.tier_config(tier)
  (zero matches for "vision" or "multimodal" — confirms the vision_dispatch module is genuinely new)

git grep -n "handlePaste\|paperclip\|attachment-preview" -- 'ui/src/components/IntentSurface.tsx'
  ui/src/components/IntentSurface.tsx:65: const [paperclipTooltipOpen, setPaperclipTooltipOpen] = useState(false);
  ui/src/components/IntentSurface.tsx:243: const attachmentIds = pendingAttachments.map((a) => a.attachment_id);
  ui/src/components/IntentSurface.tsx:248: body: JSON.stringify({ message: text, history: recentHistory, attachment_ids: attachmentIds }),
  ui/src/components/IntentSurface.tsx:411: /* AD-720: image paste from clipboard */
  ui/src/components/IntentSurface.tsx:437: if (!imageItem) return; // text paste — let the input handle it
  ui/src/components/IntentSurface.tsx:449: const res = await fetch('/api/chat/attachments', {
```

All concrete claims in this dispatch are grounded in these grep hits. Drafter must reproduce this footer (with same-day grep output) in each per-AD prompt.
