# AD-720 — Chat attachments v1: image paste from clipboard

**Wave:** 135
**Depends on:** **AD-719 (same wave; AD-719 MUST land as commit N before this AD lands as commit N+1 — HARD ORDER)**, AD-721 BF #539 (`_resolve_avatars_dir` path-traversal pattern)
**Issue:** [#514](https://github.com/seangalliher/ProbOS/issues/514)
**Risk:** MEDIUM (new storage Protocol + new endpoint + new MIME validator + UI paste handler; defense-in-depth required end-to-end)
**Estimated tests:** ≥ 14 Python + 1 Vitest

> **Builder:** read `prompts/WAVE-135-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Add **chat attachments** to the Ship's Computer chat. v1 ships **orthogonal piece 1 of 3** — **image paste from clipboard** into `IntentSurface.tsx`. Pasted images are uploaded as base64 in the existing `application/json` request body to a new `POST /api/chat/attachments` endpoint, validated server-side (size + MIME + magic-bytes), persisted under `data/attachments/<sha256>.<ext>` via a new `AttachmentStore` Protocol with a single v1 `FilesystemAttachmentStore` implementation, and rendered as inline thumbnails above the input chip strip.

Two further pieces are explicit forward markers:
- **(2) File upload via drag-drop / `+ Upload`** → AD-720a (introduces `UploadFile` + `multipart/form-data`).
- **(3) Tool-attach (BrowserTool, MCP)** → AD-720b (depends on AD-706 having bedded in).

## 2. License posture

- OSS Apache 2.0 stays Apache 2.0.
- **No new third-party deps.** Image paste uses browser-native `ClipboardEvent`, `Blob.arrayBuffer()`, and `crypto.subtle.digest`. Server uses stdlib `base64`, `hashlib`, `imghdr`, plus `asyncio.to_thread` for blocking file I/O.
- **Forbidden in v1 (HARD STOPS — see §8):**
  - `aiofiles` — verified zero hits in `pyproject.toml` at HEAD; archived prompts BF-089 and BF-094 explicitly reject it. Use `asyncio.to_thread`.
  - `python-magic` / `libmagic` — not in dep set. Use stdlib `imghdr` + manual magic-byte sniff (E6).
  - `UploadFile` / `multipart/form-data` / `python-multipart` — verified zero hits across `src/probos/` and `ui/src/` at HEAD. Belongs to AD-720a.
- M365 Copilot and VS Code Chat tool-attach UIs are absorbed as **patterns only** — no code, no CSS, no SVG, no string copy.

## 3. Verified Against Codebase (2026-05-09)

```
grep -n "router = APIRouter" src/probos/routers/chat.py
   23: router = APIRouter(prefix="/api", tags=["chat"])
        # AD-720 mounts POST /api/chat/attachments on THIS router.

grep -rn "UploadFile\|multipart/form-data\|FormData\|aiofiles" src/probos/ ui/src/
   (zero hits — confirmed v1 deliberately avoids the pattern)

grep -n "def _resolve_avatars_dir\|_platform_data_dir" src/probos/routers/system.py
  641: def _resolve_avatars_dir(configured: str) -> Path:
  649:     from probos.runtime import _platform_data_dir
  658:     return (_platform_data_dir().joinpath(*parts) if parts else _platform_data_dir()).resolve()
        # BF #539 path-traversal-safe pattern. AD-720 mirrors EXACTLY for attachments_dir.

grep -n "data/avatars" .gitignore
   31: !data/avatars/
   32: data/avatars/*.vrm
   34-39: data/avatars/**/*.{vrm,blend,fbx,glb,dsl.yaml,dsl.json}
        # AD-720 mirrors this exactly for data/attachments/.

grep -n "class AvatarsConfig\|class ChatConfig\|class AttachmentsConfig" src/probos/config.py
  # AvatarsConfig exists (Wave 133); ChatConfig / AttachmentsConfig do NOT exist.
  # Builder picks ONE of: (a) new AttachmentsConfig model, (b) extend an existing
  # config model that owns chat-relevant settings. Verify-first what owns
  # chat-relevant knobs before creating a parallel class (Wave 5 anti-pattern).

grep -n "class ChatRequest\|class ChatResponse" src/probos/api_models.py
   20: class ChatRequest(BaseModel):
   25: class ChatResponse(BaseModel):
        # AD-720 adds optional attachment_ids to ChatRequest, no change to
        # ChatResponse (AD-719 already extended ChatResponse this wave).

grep -n "import imghdr\|import hashlib\|import base64" src/probos/
   # imghdr/hashlib/base64 are stdlib; no dep additions needed.

grep -n "fanout\|per_agent_replies" src/probos/api_models.py
   # AD-719 (commit N) adds per_agent_replies. AD-720 (commit N+1) sees this
   # at HEAD by the time it builds. Hard ordering enforced in §8.
```

**Dispatch contradictions surfaced (fix in this prompt only — do NOT edit the dispatch):**

1. Dispatch §3 row "Configuration via Pydantic" allows the Builder to pick between a new `ChatConfig` and extending an existing model. Drafter pre-checked HEAD: **no `ChatConfig` exists**; the Wave-133 sibling pattern is `AvatarsConfig` in `config.py:922`. **Recommendation: introduce `AttachmentsConfig` (parallel to `AvatarsConfig`)** — keeps chat-attachments knobs cohesive and avoids polluting an unrelated model. Builder confirms in the build report.
2. Dispatch §3 row "Defense in depth" lists `imghdr` + magic bytes. **`imghdr` is deprecated as of Python 3.11 and removed in Python 3.13.** v1 should rely **primarily on the magic-bytes sniff** (E6) and use `imghdr.what()` as a **secondary cross-check only when available** (try/except `ImportError` / `DeprecationWarning`). The MIME validator's correctness must NOT depend on `imghdr` being present.
3. Dispatch §3 row "Async discipline" says "decode synchronously into bytes (the body is already in memory)". Confirmed correct for v1. The persisted `open(...).write(...)` MUST go through `asyncio.to_thread(...)`, NOT a bare blocking call inside the async handler.

## 4. Scope (v1 only)

- New `src/probos/attachments/` package with `store.py` (Protocol), `filesystem_store.py` (v1 implementation), `mime.py` (magic-bytes validator), `__init__.py`.
- New `AttachmentsConfig` Pydantic model in `src/probos/config.py` (or extend the existing config root — Builder verifies and picks one; default is "create a parallel `AttachmentsConfig`").
- New endpoint `POST /api/chat/attachments` mounted on the existing `chat.py` router.
- `ChatRequest` extension: optional `attachment_ids: list[str] = Field(default_factory=list)`.
- `ChatMessage` (UI) extension: optional `attachments?: ChatAttachment[]`.
- Image paste UI in `IntentSurface.tsx` — `paste` event → SHA-256 client-side → base64 → POST → preview thumbnail above input chip strip.
- Paperclip icon (placeholder for AD-720a) showing tooltip "Paste an image to attach (more coming soon)".
- `data/attachments/.gitkeep` + `.gitignore` audit.
- Tests: ≥ 14 Python + 1 Vitest.

## 5. Non-goals (deferred forward markers)

| Out of scope | Why deferred | Forward marker |
|---|---|---|
| File upload via drag-drop / `+ Upload` button | Introduces `UploadFile` + `multipart/form-data` — its own architectural surface. | **AD-720a** |
| Tool attach (BrowserTool, MCP tools) | Permission-layer change (chat-scoped capability grants); depends on AD-706. | **AD-720b** |
| Cloud file picker (OneDrive / GDrive) | OAuth plumbing; commercial-tier scope. **Public roadmap entry MUST be technical-only — no pricing or BYOL-vs-managed positioning.** | **AD-720c (technical-only public marker; commercial scope private)** |
| Vision pipe-through (image bytes → vision-capable agent) | Separate codepath with its own prompt-injection threat surface. v1 stores + displays only — bytes never enter an LLM prompt. | **AD-720d** |
| Image-processing subprocess (thumbnails, resize) | Out of scope. Thumbnails are CSS-only (`max-width: 256px`). | n/a |
| Per-agent attachment metadata or attribution | v1 attachments are turn-scoped, not agent-scoped. | n/a |

## 6. Deliverables

### E1. `AttachmentStore` Protocol

**New file:** `src/probos/attachments/__init__.py` (empty or minimal `__all__`).
**New file:** `src/probos/attachments/store.py`

```python
"""AD-720: AttachmentStore Protocol — content-addressed blob storage seam.

The Cloud-Ready-Storage principle: consumers depend on this Protocol;
v1 ships a single FilesystemAttachmentStore implementation; commercial
overlay can swap to S3/Azure Blob without changing chat router or UI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AttachmentStore(Protocol):
    """Content-addressed (sha256) attachment blob store."""

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        """Persist blob keyed by content_hash. Idempotent — re-write of the
        same hash is a no-op. Returns the resolved on-disk path.
        """
        ...

    async def read(self, content_hash: str) -> bytes:
        """Return the stored blob bytes. Raises FileNotFoundError if absent."""
        ...

    async def exists(self, content_hash: str) -> bool:
        """True iff a blob with this content_hash is stored."""
        ...

    async def get_path(self, content_hash: str) -> Path:
        """Return the resolved absolute path of the blob file (without reading)."""
        ...

    async def size(self, content_hash: str) -> int:
        """Return size in bytes of the stored blob."""
        ...
```

### E2. `FilesystemAttachmentStore` v1 implementation

**New file:** `src/probos/attachments/filesystem_store.py`

- Constructor: `FilesystemAttachmentStore(root: Path)`. The caller resolves `root` via `_resolve_attachments_dir()` (E3) before construction.
- Filename shape: `<sha256>.<ext>`. The `<ext>` is derived from the validated MIME (`image/png` → `.png`, `image/jpeg` → `.jpg`, `image/webp` → `.webp`, `image/gif` → `.gif`).
- All blocking I/O wrapped in `asyncio.to_thread(...)` — **no `aiofiles`, no bare blocking calls inside `async def`.**
- `write` is **idempotent**: if the target file already exists, return its path without rewriting (skip `to_thread` entirely).
- All path joins go through `Path.resolve()` + `is_relative_to(root)` check; reject any sha that fails the check (defensive — sha256 hex shouldn't traverse, but defense in depth).

```python
"""AD-720: Filesystem AttachmentStore — v1 implementation."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MIME_TO_EXT = {
    "image/png":  "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif":  "gif",
}


class FilesystemAttachmentStore:
    """Filesystem-backed AttachmentStore. Content-addressed by sha256."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_hash: str, mime: str) -> Path:
        ext = _MIME_TO_EXT.get(mime)
        if ext is None:
            raise ValueError(f"AD-720: MIME {mime!r} not in allowed set")
        # sha256 hex is 64 chars [0-9a-f]; sanity-check the input.
        if len(content_hash) != 64 or not all(c in "0123456789abcdef" for c in content_hash):
            raise ValueError(f"AD-720: malformed content_hash {content_hash!r}")
        candidate = (self._root / f"{content_hash}.{ext}").resolve()
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"AD-720: path traversal rejected for {content_hash!r}")
        return candidate

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
        path = self._path_for(content_hash, mime)
        if path.exists():
            return path  # idempotent
        await asyncio.to_thread(path.write_bytes, blob)
        return path

    async def read(self, content_hash: str) -> bytes:
        # Ext-agnostic read by globbing on hash prefix.
        matches = await asyncio.to_thread(lambda: list(self._root.glob(f"{content_hash}.*")))
        if not matches:
            raise FileNotFoundError(content_hash)
        return await asyncio.to_thread(matches[0].read_bytes)

    async def exists(self, content_hash: str) -> bool:
        matches = await asyncio.to_thread(lambda: list(self._root.glob(f"{content_hash}.*")))
        return bool(matches)

    async def get_path(self, content_hash: str) -> Path:
        matches = await asyncio.to_thread(lambda: list(self._root.glob(f"{content_hash}.*")))
        if not matches:
            raise FileNotFoundError(content_hash)
        return matches[0]

    async def size(self, content_hash: str) -> int:
        path = await self.get_path(content_hash)
        return await asyncio.to_thread(lambda: path.stat().st_size)
```

### E3. Path-traversal-safe directory resolver

**File:** `src/probos/attachments/store.py` (append) **OR** `src/probos/routers/chat.py` (Builder picks; do not duplicate the existing `_resolve_avatars_dir` helper at `routers/system.py:641`).

```python
def _resolve_attachments_dir(configured: str) -> Path:
    """Mirror of routers/system.py:641 _resolve_avatars_dir, BF #539 pattern.

    Roots `configured` under _platform_data_dir(); strips a leading "data/"
    since _platform_data_dir() already terminates in /data.
    """
    from probos.runtime import _platform_data_dir
    parts = Path(configured).parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    return (_platform_data_dir().joinpath(*parts) if parts else _platform_data_dir()).resolve()
```

### E4. `AttachmentsConfig` Pydantic model

**File:** `src/probos/config.py` (insert near `AvatarsConfig` around line 922 — same neighborhood)

```python
class AttachmentsConfig(BaseModel):
    """AD-720: chat attachments configuration."""
    enabled: bool = True
    attachments_dir: str = "data/attachments"
    max_attachment_bytes: int = 10 * 1024 * 1024  # 10 MiB
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/webp", "image/gif"]
    )
```

- Wire `AttachmentsConfig` into the root config object (mirror how `AvatarsConfig` is wired — Builder verifies the exact hookup).
- **`enabled: bool = True`** is NOT a transitional flag (Wave 10 convention #14 only requires default-False on transitional flags). Image paste is a stable feature with a kill switch.
- **`Field(default_factory=lambda: [...])`** — bare mutable default `= [...]` is a hard-stop anti-pattern (Wave 5 convention).

### E5. Attachment ingest endpoint

**File:** `src/probos/routers/chat.py` (append on the existing `router = APIRouter(prefix="/api", tags=["chat"])`)

Request body Pydantic model (add to `src/probos/api_models.py`):

```python
class AttachmentUploadRequest(BaseModel):
    content_hash: str   # client-computed sha256 hex
    blob_b64: str       # base64-encoded raw bytes
    mime: str           # declared MIME type


class AttachmentUploadResponse(BaseModel):
    attachment_id: str  # == content_hash
    url: str            # browser-fetchable URL (e.g. /api/chat/attachments/<hash>)
    mime: str
    size_bytes: int
    sha256: str
```

Endpoint validation (in order — fail-fast, return structured error JSON with appropriate status):

1. `req.mime in cfg.attachments.allowed_mime_types` → else **415 Unsupported Media Type** with `{"error": "mime_not_allowed", "mime": req.mime}`.
2. `base64.b64decode(req.blob_b64, validate=True)` → on `binascii.Error` return **400 Bad Request** with `{"error": "invalid_base64"}`.
3. `len(decoded) <= cfg.attachments.max_attachment_bytes` → else **413 Payload Too Large** with `{"error": "too_large", "size": len(decoded), "max": cfg.attachments.max_attachment_bytes}`.
4. `hashlib.sha256(decoded).hexdigest() == req.content_hash` → else **400 Bad Request** with `{"error": "hash_mismatch"}`.
5. `validate_image_bytes(decoded, req.mime)` (E6) returns `(True, sniffed_mime)` AND `sniffed_mime == req.mime` → else **415 Unsupported Media Type** with `{"error": "magic_mismatch", "declared": req.mime, "sniffed": sniffed_mime}`.
6. `await store.write(req.content_hash, decoded, req.mime)` — idempotent.
7. Return `AttachmentUploadResponse(attachment_id=hash, url=f"/api/chat/attachments/{hash}", mime=req.mime, size_bytes=len(decoded), sha256=hash)`.

Idempotency: re-uploading the same `content_hash` returns the existing record's response (same `url`, `size_bytes`) without rewriting the file. Tested in E9 #14.

> **No `await store.write` outside the `asyncio.to_thread` envelope** — the store's own implementation handles that. The endpoint must NOT introduce a second blocking-IO path.

### E6. Magic-bytes validator

**New file:** `src/probos/attachments/mime.py`

```python
"""AD-720: defense-in-depth MIME validator. stdlib-only, no libmagic."""
from __future__ import annotations

# Magic-byte signatures for the four allowed MIMEs.
# Each entry: (declared_mime, [list of (offset, signature_bytes)])
_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    "image/png":  [(0, b"\x89PNG\r\n\x1a\n")],
    "image/jpeg": [(0, b"\xff\xd8\xff")],
    "image/gif":  [(0, b"GIF87a"), (0, b"GIF89a")],
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],
}


def validate_image_bytes(blob: bytes, declared_mime: str) -> tuple[bool, str]:
    """Return (True, sniffed_mime) if the blob's magic bytes match declared_mime.

    Returns (False, reason) otherwise. Reason is one of:
      "unknown_declared_mime", "header_mismatch", "blob_too_short".
    """
    if declared_mime not in _SIGNATURES:
        return (False, "unknown_declared_mime")
    sigs = _SIGNATURES[declared_mime]
    for offset, sig in sigs:
        end = offset + len(sig)
        if len(blob) < end:
            return (False, "blob_too_short")
    # All required signatures must match (WebP needs both RIFF + WEBP).
    for offset, sig in sigs:
        if blob[offset:offset + len(sig)] != sig:
            return (False, "header_mismatch")
    return (True, declared_mime)
```

> **Why not `imghdr`:** deprecated in Py 3.11, removed in Py 3.13 (per §3 finding 2). The validator's correctness must NOT depend on `imghdr`. If the Builder wants a secondary cross-check, wrap `imghdr.what()` in a try/except `ImportError` and use it for logging only — never as the primary decision.

### E7. Image-paste UI

**File:** `ui/src/components/IntentSurface.tsx`

- Add a `paste` event listener on the input. When `event.clipboardData.items` contains an item with `type.startsWith('image/')`:
  1. `event.preventDefault()`.
  2. `const blob = item.getAsFile()`.
  3. `const buf = await blob.arrayBuffer()` → `const hash = bufferToHexSha256(buf)` (use `crypto.subtle.digest('SHA-256', buf)`).
  4. `const b64 = bufferToBase64(buf)`.
  5. POST to `/api/chat/attachments` with `{content_hash: hash, blob_b64: b64, mime: blob.type}`.
  6. On success: append to local `pendingAttachments: ChatAttachment[]` state.
  7. On failure: render a structured error message in chat (`addChatMessage('system', '(Attachment upload failed: <reason>)')`).
- **Client-side guard:** before POST, reject blobs `> 10 * 1024 * 1024` (mirror server's `max_attachment_bytes` default). Show structured error.
- **Render preview thumbnails** above the recipient chip strip:
  - `<img src={attachment.url} style={{ maxWidth: 256, maxHeight: 256, borderRadius: 4 }} />`
  - Inline-SVG `x` button (12×12, `strokeWidth: 1.5`, `strokeLinecap: 'round'`) to remove pre-send.
  - **No emoji.**
- On Send (existing handler), include `attachment_ids: pendingAttachments.map(a => a.attachment_id)` in the `/api/chat` body and clear `pendingAttachments`.
- Add a small **paperclip icon** (inline SVG) in the input toolbar — clicking it opens a tooltip "Paste an image to attach (more coming soon)" and does NOTHING else in v1. The visual real estate signals AD-720a is on the way without promising unbuilt features.

**File:** `ui/src/store/types.ts` (extend the AD-719-widened `ChatMessage`):

```typescript
export interface ChatAttachment {
  attachment_id: string;
  url: string;
  mime: string;
  sha256: string;
  size_bytes: number;
}

export interface ChatMessage {
  // ...AD-719 fields above...
  attachments?: ChatAttachment[];   // AD-720
}
```

> **Hard-stop reminder:** AD-720 builds on AD-719's already-widened `ChatMessage`. If the Builder finds that `role` is still `'user' | 'system'` at HEAD before this commit, **STOP** — AD-719's commit N is missing.

### E8. `data/attachments/` bootstrap + `.gitignore` audit

**New file:** `data/attachments/.gitkeep` (empty file).

**File:** `.gitignore` — add a block mirroring the AD-721 / `data/avatars/*` shape at L30-39 exactly:

```gitignore
# AD-720: attachments dir is shipped (with .gitkeep), but image blobs are not.
!data/attachments/
data/attachments/*
!data/attachments/.gitkeep
```

> Reviewer audits `git status --ignored data/attachments` post-commit — any actual image file committed is a hard stop (§8).

### E9. Tests — Python (≥ 14 boundary tests)

**New file:** `tests/test_ad720_attachment_store.py`

| # | Test | Validates |
|---|---|---|
| 1 | `test_filesystem_store_write_persists_blob` | After `await store.write(hash, blob, "image/png")`, file exists at `<root>/<hash>.png`. |
| 2 | `test_filesystem_store_write_is_idempotent` | Second `write` of same hash does NOT rewrite file (same mtime). |
| 3 | `test_filesystem_store_exists_round_trip` | `exists(hash)` is False, then write, then True. |
| 4 | `test_filesystem_store_size_returns_byte_count` | `size(hash) == len(blob)`. |
| 5 | `test_filesystem_store_read_returns_original_bytes` | `await store.read(hash) == blob`. |
| 6 | `test_filesystem_store_path_traversal_rejected` | Malformed `content_hash` (e.g. `"../../etc/passwd"`) raises `ValueError`. |
| 7 | `test_filesystem_store_unknown_mime_rejected` | `write(hash, blob, "image/svg+xml")` raises `ValueError`. |
| 8 | `test_filesystem_store_uses_asyncio_to_thread` | `monkeypatch.setattr("asyncio.to_thread", spy)` — confirms `to_thread` is invoked at least once on `write`. |

**New file:** `tests/test_ad720_mime_validator.py`

| # | Test | Validates |
|---|---|---|
| 9 | `test_validate_png_happy` | `(True, "image/png")` for a real PNG header. |
| 10 | `test_validate_jpeg_happy` | `(True, "image/jpeg")` for `\xff\xd8\xff` header. |
| 11 | `test_validate_webp_happy` | `(True, "image/webp")` for `RIFF....WEBP` header. |
| 12 | `test_validate_gif_happy` | `(True, "image/gif")` for both `GIF87a` and `GIF89a`. |
| 13 | `test_validate_header_mismatch_rejected` | PNG bytes declared as `image/jpeg` → `(False, "header_mismatch")`. |
| 14 | `test_validate_blob_too_short_rejected` | Blob shorter than signature → `(False, "blob_too_short")`. |
| 15 | `test_validate_unknown_declared_mime_rejected` | `image/svg+xml` declared → `(False, "unknown_declared_mime")`. |

**New file:** `tests/test_ad720_attachments_endpoint.py`

| # | Test | Validates |
|---|---|---|
| 16 | `test_post_attachment_happy_path` | Valid PNG → 200, response includes correct `attachment_id`/`url`/`size_bytes`/`sha256`. |
| 17 | `test_post_attachment_oversized_returns_413` | Blob > `max_attachment_bytes` → 413 `too_large`. |
| 18 | `test_post_attachment_disallowed_mime_returns_415` | `image/svg+xml` → 415 `mime_not_allowed`. |
| 19 | `test_post_attachment_magic_mismatch_returns_415` | PNG bytes declared as JPEG → 415 `magic_mismatch`. |
| 20 | `test_post_attachment_invalid_base64_returns_400` | Non-base64 garbage → 400 `invalid_base64`. |
| 21 | `test_post_attachment_hash_mismatch_returns_400` | Computed sha256 ≠ declared `content_hash` → 400 `hash_mismatch`. |
| 22 | `test_post_attachment_idempotent_reupload_returns_200` | Same `content_hash` posted twice → second returns 200 with same `attachment_id`/`url`; only ONE file on disk. |

> **Test gate command (single file):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad720_attachment_store.py tests/test_ad720_mime_validator.py tests/test_ad720_attachments_endpoint.py -v -n 0 --timeout=60`. **Wave gate:** `pytest tests/ -q -n 16 --dist=loadfile` is green.

### E10. Tests — UI (Vitest)

**New file:** `ui/src/__tests__/IntentSurface.imagePaste.test.tsx`

Component-level coverage:

1. Pasting a fixture PNG `Blob` triggers a POST to `/api/chat/attachments` with the expected body shape.
2. Successful upload renders an `<img>` preview with `src === response.url`.
3. Clicking the inline-SVG `x` removes the preview.
4. Pasting a 20MB blob (oversize) renders a structured error message and does NOT POST.
5. Pasting an `image/svg+xml` blob renders a structured error message (or simply does nothing — Builder picks; v1 silently ignores non-allowed clipboard items in step 1 of the handler).
6. **No emoji in the paperclip / preview-close affordances** — DOM scan rejects emoji codepoints.

Mock `/api/chat/attachments` with `vi.fn()` returning a stub `AttachmentUploadResponse`.

## 7. Cross-AD integration

| Touchpoint | AD-720 (this AD) | AD-719 (commit N — already at HEAD) |
|---|---|---|
| `ChatMessage` shape | Adds `attachments?: ChatAttachment[]`. | Already widened `role`, added `agent_id`/`callsign`. |
| `IntentSurface.tsx` | Adds paste handler, preview thumbnails, paperclip icon (placeholder). | Already owns input area, `@`-picker, chip strip. |
| `/api/chat` request body | Adds optional `attachment_ids: list[str]` field; server resolves IDs via `AttachmentStore.exists()` before forwarding. **Bytes never enter the LLM prompt in v1.** | Pass-through `mentions`. |
| `/api/chat` response body | No change. | Already added `mentions` + `per_agent_replies`. |
| Episodic writes | Episode metadata records `attachment_ids` (NOT the bytes) when the turn carried attachments. | Already writes one episode per fan-out reply. |
| Configuration | New `AttachmentsConfig` (E4). | None. |
| **Build order** | **AD-720 ships SECOND as commit N+1.** | **AD-719 ships FIRST as commit N.** Builder MUST NOT interleave commits. |

## 8. Hard-stop conditions for the Builder

Standard hard-stops from `BUILDER-EXECUTION-PLAN.md` apply, **plus** (verbatim from `WAVE-135-DISPATCH.md` §8):

1. **`UploadFile` introduced in v1.** Hard stop. v1 deliberately ships JSON-body image paste with base64. `UploadFile` belongs to AD-720a.
2. **`aiofiles` added to `pyproject.toml` or imported anywhere.** Hard stop. Use `asyncio.to_thread`.
3. **`libmagic` / `python-magic` dependency added.** Hard stop. Use stdlib magic-byte sniff (E6).
4. **`subprocess.run` introduced under `src/probos/attachments/`.** Hard stop. Async only; v1 ships no image-processing subprocess.
5. **`exec` / `eval` / `compile` on attachment metadata or chat content.** Hard stop. Reviewer greps the diff.
6. **Working-tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain.
7. **Emoji literal in the diff.** Hard stop. Inline SVG only.
8. **`.gitignore` regression.** If the Builder forgets to gitignore `data/attachments/*`, hard stop. Audit `git status --ignored data/attachments` before merge.
9. **Image bytes piped into a decomposer or LLM-tier prompt.** Hard stop. v1 ships pure storage + display. Vision pipe-through is AD-720d.
10. **Pricing / commercial-tier language landing in the public roadmap entry for AD-720c.** Hard stop. The `*(Commercial)*` tag means "see private repo," NOT permission to inline pricing.
11. **AD-719 not at HEAD before AD-720 commit lands.** Hard stop. Pre-flight: `git log --oneline -5` shows AD-719's commit immediately before this one. If the AD-719 commit is missing, AD-720 has nothing to build on.
12. **Architectural change required** (modify `BaseAgent`/`IntentMessage`/`ChatRequest` core protocols). Hard stop.

## 9. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specifically (Builder confirms each in the build report):
- **Storage abstraction (Protocol):** `AttachmentStore` is a `typing.Protocol`. Consumers depend on the Protocol; v1 ships a single `FilesystemAttachmentStore` implementation. **No direct `aiosqlite.connect()` in this AD.**
- **Cloud-Ready Storage:** documented extension point — commercial overlay can swap to S3 / Azure Blob without changing chat router or UI. Note this in the new module's docstring.
- **Defense in depth (E5 ordered validations):** client guard → MIME allow-list → base64 decode → size cap → hash verify → magic-bytes sniff → write. Each tier independently rejects bad input.
- **Async discipline:** `asyncio.to_thread` for ALL blocking I/O. No bare `open(...).write(...)`. No `aiofiles`.
- **No private-attr access:** the chat router talks to the store through the Protocol, never reaching into `_root` or other private attrs.
- **Three-tier exception handling:**
  - **Propagate:** path-traversal `ValueError` (security), hash mismatch (data integrity).
  - **Log-and-degrade:** transient I/O errors during `asyncio.to_thread` (warn + 500 with structured body).
  - **Swallow:** none.
- **Configuration via Pydantic:** `AttachmentsConfig` with `Field(default_factory=...)` for the list, sensible defaults so ProbOS boots without operator config.
- **No emoji in HXI** (HXI Design Principle #3): paperclip icon, preview-close `x`, all SVG.
- **Logging quality:** every reject path includes context (declared MIME vs sniffed, size vs cap, content_hash prefix).
- **Type annotations:** every public method on `AttachmentStore`, `FilesystemAttachmentStore`, `validate_image_bytes`, and the new endpoint is fully typed.

## 10. Acceptance criteria

- All ≥ 14 Python tests + 1 Vitest test pass.
- `pytest tests/ -q -n 16 --dist=loadfile` is green (or `-n 8` with build-report note).
- `cd ui && npx vitest run` is green.
- Phantom-API pre-check on this prompt body returns zero true phantoms (the `.tsx` and `APIRouter` candidates are known false positives — note in build report).
- GH issue [#514](https://github.com/seangalliher/ProbOS/issues/514) closed in the merge commit.
- `git status --ignored data/attachments` post-commit shows only `.gitkeep` tracked; any blob is ignored.
- AD-719's commit is the **immediately-prior** commit in `git log` — verify pre-flight.
- **Files touched (target list):**
  - **New:** `src/probos/attachments/__init__.py`, `src/probos/attachments/store.py`, `src/probos/attachments/filesystem_store.py`, `src/probos/attachments/mime.py`, `data/attachments/.gitkeep`, `tests/test_ad720_attachment_store.py`, `tests/test_ad720_mime_validator.py`, `tests/test_ad720_attachments_endpoint.py`, `ui/src/__tests__/IntentSurface.imagePaste.test.tsx`.
  - **Modified:** `src/probos/routers/chat.py` (new endpoint), `src/probos/api_models.py` (new request/response models, `attachment_ids` on `ChatRequest`), `src/probos/config.py` (new `AttachmentsConfig` + root wiring), `ui/src/store/types.ts` (new `ChatAttachment` + extend `ChatMessage`), `ui/src/components/IntentSurface.tsx` (paste handler + previews + paperclip), `.gitignore`.
  - **Untouched (hard stop if modified):** `src/probos/consensus/**`, `src/probos/routers/agents.py`, anything related to `UploadFile`, `aiofiles`, `python-magic`.

## 11. Forward markers (file at gate-3 per `BUILDER-EXECUTION-PLAN.md` Post-Sweep step 6)

| Marker | Scope |
|---|---|
| **AD-720a** | File upload via `UploadFile` + `multipart/form-data` (drag-drop, `+ Upload` button). Pulls in `python-multipart`. |
| **AD-720b** | Tool attach (BrowserTool from AD-706, MCP tools from AD-449) — chat-scoped capability grants via the AD-423a/AD-423c permission layer. |
| **AD-720c** | Cloud file picker (OneDrive / GDrive) via OAuth. **Public marker is technical-only:** "OAuth-bound cloud file source for chat attachments." Pricing tier, BYOL-vs-managed positioning, and commercial scope live in the private commercial repo per `.github/copilot-instructions.md` "Repository Boundary" rule. |
| **AD-720d** | Vision pipe-through — image bytes piped to a vision-capable agent's LLM prompt. Separate prompt-injection threat surface; ships its own validator + rate-limit. |

## 12. AD-numbering

Highest pre-existing AD at HEAD: **AD-721i** (per `PROGRESS.md` L11, confirmed 2026-05-09).

| AD | Status |
|---|---|
| AD-719 | Same wave; ships FIRST as commit N. See `prompts/ad-719-multi-agent-chat-v1.md`. |
| AD-719a / 719b / 719c | Reserved forward markers (AD-719's). |
| **AD-720** | **THIS PROMPT — issue #514. Ships SECOND as commit N+1.** |
| AD-720a / 720b / 720c / 720d | Reserved forward markers (file at gate-3). |
| AD-721 / 721a–721i | In flight or shipped (Wave 133/134). |

No collisions. Drafter re-greps `DECISIONS.md` and `decisions-era-*.md` for any `AD-720a`/`b`/`c`/`d` labels before finalizing — none present at HEAD 2026-05-09.
