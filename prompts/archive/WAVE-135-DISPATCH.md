# WAVE 135 DISPATCH — Multi-agent chat + chat attachments (AD-719 + AD-720)

**Wave:** 135
**Mode:** main
**Depends on:** 134
**Builder required:** yes
**Issues to close:** [#513](https://github.com/seangalliher/ProbOS/issues/513) (AD-719), [#514](https://github.com/seangalliher/ProbOS/issues/514) (AD-720)
**Date:** 2026-05-09

---

## 1. Goal

Bring the Ship's Computer chat (`ui/src/components/IntentSurface.tsx`) up the M365-Copilot bar in two minimum-viable slices that ship together but are independently testable.

- **AD-719** evolves the single-target chat into a **multi-agent chat** addressed by `@<callsign>`. v1 picks **mental model (a) — Captain addresses one or more crew in a single turn from `IntentSurface`**, fan-out happens server-side, replies render inline with attribution. The richer "crew-see-each-other thread" (mental model b) and the "replace IntentSurface with a Copilot-style left rail + Agents nav" (mental model c) are explicitly deferred to AD-719a / AD-719b. Scope-reframe rationale in §7.
- **AD-720** adds **chat attachments**. v1 picks **image paste from clipboard** (orthogonal piece 1 of 3 — simplest, no `multipart/form-data` plumbing needed in v1). File upload via drag-drop / `+ Upload` (orthogonal piece 2) and tool-attach (orthogonal piece 3, depends on AD-706 BrowserTool + AD-449 MCP Bridge) are deferred to AD-720a / AD-720b. Scope-reframe rationale in §7.

Both prompts follow the existing `IntentSurface` ↔ `/api/chat` ↔ runtime decomposer pipeline; neither replaces it. The runtime already understands `@<callsign>` mentions (`src/probos/cognitive/decomposer.py:252-369`, `_callsign_map` + `set_callsign_map()`), so AD-719 v1 is mostly a UI + response-shape change, not a new routing primitive.

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `IntentSurface.tsx` Ship's Computer chat | L29 `export function IntentSurface`; L172 + L249 fetch `/api/chat`; addChatMessage uses `'user' \| 'system'` (`ui/src/store/types.ts:195`). | **Extend.** Add `@<callsign>` autocomplete + a multi-recipient chip strip; widen `ChatMessage.role` to `'user' \| 'agent' \| 'system'` and add `agent_id?: string` so per-turn attribution renders an avatar + callsign. |
| `ProfileChatTab.tsx` 1:1 DM chat (AD-718 reference pattern) | L10 `export function ProfileChatTab({ agentId })`; L88 `await fetch('/api/agent/${agentId}/chat'...)`; existing voice-profile fetch + TTS toggle pattern. | **Pattern reference only.** AD-720's image-paste UI mirrors AD-718's per-agent control affordance (icon-button + state hook), but AD-719 does NOT subsume `ProfileChatTab` — DMs and multi-agent chat coexist. |
| `decomposer.py` callsign mapping | L252 `self._callsign_map: dict[str, str] = {}` (BF-013); L271 `set_callsign_map(...)`; L369 `callsign_map=self._callsign_map or None`. | **Reuse as-is.** AD-719 does NOT introduce a new mention parser; it surfaces the existing one via the response payload (a fanned-out `mentions: list[str]` per turn). |
| `routers/agents.py` (`/api/agent`) | L27 `router = APIRouter(prefix="/api/agent", ...)`. L355 `POST /{agent_id}/chat`, L551 `GET /{agent_id}/chat/history`. | **Per-agent DM endpoints stay as-is.** AD-719 does NOT add multi-target chat under `/api/agent` — multi-recipient chat is the Ship's Computer surface (`/api/chat`). |
| Ship's Computer chat endpoint (`/api/chat`) | **PINNED:** `src/probos/routers/chat.py` — `router = APIRouter(prefix="/api", tags=["chat"])` (L23) + `@router.post("/chat")` (L26). The handler delegates to `runtime.process_natural_language(...)` (L143-L149). The `@callsign` DM short-circuit at L107-L126 already exists (BF-009/AD-397) and routes via `runtime.intent_bus.send(IntentMessage(intent="direct_message", ...))`. | **Extend the response shape, not the URL.** Add `mentions: list[str]` + `per_agent_replies: list[{agent_id, callsign, text}]` to the response so the UI can render N attributed replies from one POST. Backwards-compatible with single-target callers. The existing single-target DM short-circuit (L107-L126) stays as-is for one-mention cases; multi-mention fan-out is a NEW branch. |
| `routers/wardroom.py` (`/api/wardroom`) | L20 `router = APIRouter(prefix="/api/wardroom", ...)`. Channels → threads model with multi-participant DMs (L70 `/dms`, L160 `/channels`, L182 `/channels/{id}/threads`). | **Pattern reference only — NOT consumed by AD-719 v1.** WardRoom is crew-to-crew + Captain DMs persistence. AD-719 v1 is *transient* multi-agent turn-based exchange in the Ship's Computer surface. v2 (AD-719a) MAY adopt WardRoom storage to make threads persistent; explicit out-of-scope for v1 (§7). |
| AD-485 (recent communications surface), AD-636 (Captain DMs), AD-594/AD-594b (crew consultation primitives) | Decisions appended in DECISIONS.md (verify-first the exact line numbers when drafting). AD-594/AD-594b is the consult/consensus primitive; AD-636 is the Captain-DM surface. | **Do NOT collapse into AD-719.** AD-719 v1 is fan-out + attribution; consensus/quorum among the responding crew is **explicitly out of scope** (§7). If the Captain wants the crew to deliberate, they invoke AD-594b's `consult()` primitive — not the multi-agent chat surface. |
| AD-706 BrowserTool (Wave 132) | Computer Use tool registered via AD-423a `ToolRegistry` with rank-graded permissions. | **Pattern reference for AD-720 v2 (AD-720b "tool attach").** AD-720 v1 image paste is independent of AD-706. AD-720b will be the surface that lets the Captain attach `BrowserTool` / MCP tools to a chat. |
| AD-423a Tool Layer + AD-423c Onboarding (Tool permissions) | Tool registry + permission grants. | **Pattern reference only — used by AD-720b.** v1 ships no tool-attach UI. |
| AD-449 MCP Bridge tools | MCP-exposed tools available to agents. | **Pattern reference for AD-720b.** Not consumed by v1. |
| `data/avatars/` directory (AD-721 / AD-721d) | Existing data directory under `data/` with `.gitkeep` + `.gitignore` exclusions. | **Pattern reference for AD-720's `data/attachments/` directory** (issue #514 calls this out). v1 image paste persists images under `data/attachments/<sha256-hash>.<ext>` with `.gitkeep` + `.gitignore` exclusion mirroring the avatars pattern. |
| `multipart/form-data` / `UploadFile` / `FormData` | **Verified:** zero hits across `src/probos/` and `ui/src/` (grep confirmed). | **No prior pattern.** AD-720 v1 deliberately avoids introducing the pattern — image paste piggybacks on existing `application/json` POST body using base64-encoded image data. The Builder MUST NOT introduce `UploadFile` in v1. AD-720a will introduce it for file upload, with its own dispatch. |
| **M365 Copilot UI** (issue #513 reference) | Microsoft proprietary. | **PATTERN absorption ONLY.** No code, no CSS, no SVG glyphs, no string copy from the M365 surface. The `@`-picker affordance and chip strip are commodities; we re-implement from scratch using HXI design principles (§3 row "No emoji"). |
| **VS Code Chat tool-attach UI** (issue #514 reference for v2) | Microsoft proprietary. | **PATTERN absorption ONLY.** Surface AD-720b separately when its time comes. v1 ships nothing tool-attach-shaped. |
| `@pixiv/three-vrm`, Blender, saturday06 VRM-Addon (Wave 134 deps) | Avatar-rendering only. | **Not consumed by Wave 135.** Mentioned only to disambiguate scope. |

**Top-level license posture:** OSS Apache 2.0 stays Apache 2.0. M365 Copilot and VS Code Chat are absorbed as **patterns only** (M365 is proprietary, VS Code Chat is MIT but we still replicate by hand to avoid string/asset propagation). No new third-party deps required for v1 of either AD. Image paste uses browser-native `ClipboardEvent` + `Blob` APIs.

---

## 3. Engineering-principles checklist

Builder must verify each in the per-prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Storage abstraction (Protocol)** | Image attachment storage (AD-720) | New `AttachmentStore` defined as a `typing.Protocol` (read/write/get_path/exists/size by content-hash key). v1 ships a single `FilesystemAttachmentStore` implementation rooted under `data/attachments/`. **No direct `aiosqlite.connect()`** introduced; metadata (sha256, mime, size, owner_chat_id) lives in a small JSONL append log next to the blobs OR on an existing store — drafter picks one and justifies in the prompt body. |
| **Defense in depth** | Image paste end-to-end (AD-720) | (1) Client-side: reject Blobs > `chat.max_attachment_bytes` before upload. (2) Server-side: re-validate size against the same config knob. (3) **MIME sniff + extension + magic bytes** — accept ONLY `image/png`, `image/jpeg`, `image/webp`, `image/gif` for v1; sniff via `imghdr` (stdlib) AND verify the first 8/12 bytes match the format's magic header (`\x89PNG\r\n\x1a\n` for PNG, `\xff\xd8\xff` for JPEG, `RIFF...WEBP` for WebP, `GIF87a`/`GIF89a` for GIF). (4) Path resolution via a single `_resolve_attachments_dir()` helper rooted under `_platform_data_dir()` (mirror the AD-721 BF #539 path-traversal-safe pattern). (5) Content-addressed filename: `<sha256>.<ext>` — no operator-supplied filename ever lands on disk. |
| **Async discipline** | Server reads of base64 image bytes (AD-720) | If the request body contains an inline base64 payload, the handler decodes synchronously into a `bytes` object (the body is already in memory — FastAPI buffered it). If a future variant adds streamed `UploadFile` (deferred to AD-720a), use `await file.read(<chunk>)` with a hard byte cap and **chunked accumulation**, NOT `await file.read()` without a size limit. **Forbid** `subprocess.run`; if any image-processing subprocess (e.g. for thumbnails) is introduced, it is `asyncio.create_subprocess_exec` only. v1 ships NO image-processing subprocess — thumbnails are CSS-only via `max-width`. |
| **No private-attr access** | UI store + decomposer wiring (AD-719) | The multi-recipient response handler reads only public fields on `ChatMessage` and the runtime's public chat handler. No reaching into `_callsign_map` directly — the runtime already exposes the parsed `mentions: list[str]` through `decomposer.set_callsign_map` + the `@mention` substrate. |
| **No emoji in HXI** (HXI Design Principle #3) | `@`-picker, attachment paperclip icon, chip-strip "remove" `x`, image preview close affordance | All glyphs inline SVG with `strokeWidth: 1.5`, `strokeLinecap: round`. Active state amber `#f0b060`, inactive `#666680`. Reviewer fails the prompt on any emoji literal in the diff. |
| **Test gates** | Both prompts | Per-prompt: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad719_*.py tests/test_ad720_*.py -v -n 0`. Full gate: `pytest tests/ -q -n 16 --dist=loadfile` matches the standing rule in `BUILDER-EXECUTION-PLAN.md` and `pyproject.toml` L93 `addopts`. **UI tests:** `cd ui && npx vitest run` MUST be green; both prompts ship at least one Vitest component test (AD-719: `IntentSurface.atMention.test.tsx`; AD-720: `IntentSurface.imagePaste.test.tsx`). |
| **Episodic completeness** | Multi-agent exchanges (AD-719) | Every fanned-out reply MUST produce its own episode in the episodic memory (one episode per `(captain_turn, replying_agent)` pair), not a single merged episode for the whole turn. **PINNED call-site:** `src/probos/runtime.py:2870` — Step 6 of `process_natural_language(...)`, currently `await self.episodic_memory.store(episode)` inside the single-DAG path. AD-719's fan-out branch wraps a `for reply in per_agent_replies:` loop that builds one `Episode` per reply (using `self.dream_adapter.build_episode(...)` when present, else the `Episode(...)` fallback at L2861-2870) and `await`s each `store()` call. The DM short-circuit in `routers/chat.py:107-126` does NOT currently write an episode — that gap stays as-is in v1; AD-719's loop only covers the multi-mention NL fan-out path. Reviewer fails the prompt if any multi-mention fan-out branch skips the write. |
| **Consensus + trust integrity** | 2+ crew speak (AD-719) | Multi-target chat is **NOT consensus**. Each crewmember replies independently with their own trust update from the Captain's eventual feedback signal (AD-485/AD-636 follow-up surface). Builder MUST NOT introduce a quorum vote here, and MUST NOT couple multiple crew replies into a single trust update. If the Captain wants deliberation, they invoke `consult()` (AD-594b). The prompt body explicitly forbids touching `consensus/quorum.py`, `consensus/shapley.py`, or any `consult()` plumbing. |
| **Defense-in-depth: prompt injection via image** | Image paste payload (AD-720) | Pasted images go into the chat as an attached blob. They are NOT sent through any LLM as base64 in the system prompt without the Captain explicitly invoking a vision-capable agent. v1 ships pure storage + display. The "show this image to the agent" path is deferred to AD-720c (vision pipe-through). Reviewer fails the prompt if any v1 codepath stuffs raw base64 into a decomposer or LLM-tier prompt. |
| **Configuration via Pydantic** | New chat-attachment knobs (AD-720) | New `ChatConfig` (or extend the existing config — drafter verifies which Pydantic model owns chat-relevant settings at HEAD). Fields: `attachments_enabled: bool = True`, `attachments_dir: str = "data/attachments"`, `max_attachment_bytes: int = 10 * 1024 * 1024` (10 MiB), `allowed_mime_types: list[str] = Field(default_factory=lambda: ["image/png", "image/jpeg", "image/webp", "image/gif"])`. Bare mutable defaults are **forbidden** (Wave 5 convention) — use `Field(default_factory=...)` for the list. |
| **Cloud-Ready Storage** | Filesystem store as v1 (AD-720) | The `AttachmentStore` Protocol is the seam. v1 implementation is filesystem-only; commercial overlay can swap to S3 / Azure Blob without the chat router or UI changing. Documented as an extension point in `docs/development/`. |

---

## 4. AD-719 scope — Multi-agent chat (`@<callsign>` fan-out + per-turn attribution)

**Issue:** [#513](https://github.com/seangalliher/ProbOS/issues/513). Mental model **(a) chosen for v1**: Captain types a single turn in `IntentSurface`, mentions zero-or-more crew with `@<callsign>`, the runtime fans out, each mentioned crewmember replies inline with avatar + callsign attribution. Default routing (no mention) stays Ship's Computer.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | Widen `ChatMessage.role` and add `agent_id` | `ui/src/store/types.ts` (modify L195-204) | `role: 'user' \| 'agent' \| 'system'`. Add `agent_id?: string` and `callsign?: string`. Existing `'system'` callers stay valid (system messages are not crew replies). |
| **D2** | Multi-recipient response shape | `ui/src/components/IntentSurface.tsx` (modify L160-208 send path) | When `/api/chat` returns `per_agent_replies: [{agent_id, callsign, text}, ...]` (new field, see D5), the UI renders one `ChatMessage` per reply with `role: 'agent'`. When the field is absent (single-target / Ship's Computer reply), behavior is unchanged. **Backward compatible.** |
| **D3** | `@`-picker autocomplete | `ui/src/components/IntentSurface.tsx` (extend the input area) | Typing `@` opens a popover listing live crew (callsign + display_name + tier badge). Filter by typed prefix. **v1 ships mouse-click + Enter-to-confirm only** (Captain ruling 2026-05-09). Arrow-key navigation (↑/↓), Esc-to-close, and Tab-completion are explicitly DEFERRED to AD-719c. The `@` popover MUST close on outside-click and on input-blur. Crew list sourced from existing `useStore` agents snapshot — drafter verifies the exact selector at HEAD (likely `s.agents` or similar; do NOT add a new fetch). |
| **D4** | Recipient chip strip | `ui/src/components/IntentSurface.tsx` (extend) | Selected mentions render as chips above/below the input. Each chip has an inline-SVG `x` to remove. **No emoji in the remove affordance.** Multi-select supported (Captain can mention 1..N crew per turn). |
| **D5** | Server-side fan-out + response shape | The router file owning `/api/chat` (drafter verify-first; likely `src/probos/api.py` or `src/probos/routers/system.py`). | Parse `mentions` from the message, route to each addressed agent in parallel via `asyncio.gather`, return `{response, per_agent_replies, mentions}`. When `mentions` is empty, respond as today (Ship's Computer single reply, `per_agent_replies` omitted). Response model is a new Pydantic `ChatResponse` with backward-compat optional fields. |
| **D6** | Episodic write per fan-out reply | runtime path that produces the chat reply | Drafter verifies the exact call-site at HEAD, then ensures the loop over fanned-out replies writes one episode per `(captain_turn_id, agent_id)`. Reviewer fails if any branch skips. |
| **D7** | Per-turn attribution UI (avatar + callsign + tier badge) | `ui/src/components/IntentSurface.tsx` (extend message render); NEW `ui/src/components/AgentAvatarBadge.tsx` (new) | **PINNED:** `CrewAvatarPopout.tsx` (AD-721, `ui/src/components/profile/CrewAvatarPopout.tsx:37`) is a heavy 3D VRM popout — wrong for inline 24-32px chat attribution. `AgentProfilePanel.tsx:195-198` uses an inline 8x8 colored circle (`background: deptColor, borderRadius: '50%'`) — too small. **Decision: extract a NEW lightweight `AgentAvatarBadge.tsx`** that renders a 24-32px colored circle (color from a shared `DEPT_COLORS` map) with the agent's first-letter-of-callsign as a centered initial. Component signature: `<AgentAvatarBadge agentId={string} callsign={string} department={string} size={24 | 32} />`. Used ONLY in IntentSurface multi-reply rendering for v1. **Do NOT refactor `AgentProfilePanel.tsx:195-198`'s 8x8 dot to use the new component** — that's scope creep and lands separately. **Do NOT use `CrewAvatarPopout`** — it's the 3D VRM surface. **Do NOT introduce a third-party avatar lib.** If `DEPT_COLORS` is currently inline in `AgentProfilePanel.tsx:22`, the drafter MAY extract it to `ui/src/utils/deptColors.ts` (small, low-risk) and import from both call-sites. |
| **D8** | Tests — Python | `tests/test_ad719_chat_fanout.py` (new) — boundary cases on the fan-out router: zero mentions (Ship's Computer reply only), one mention (single fan-out), N mentions (parallel fan-out), unknown callsign (returns Ship's Computer reply with a structured warning), mention of an offline agent (returns a "agent unavailable" stub for that recipient, others succeed); `tests/test_ad719_episodic_writes.py` (new) — asserts one episode per fan-out reply. | Target ≥ 12 Python tests. |
| **D9** | Tests — UI (Vitest) | `ui/src/__tests__/IntentSurface.atMention.test.tsx` (new) | Component-level: typing `@e` opens picker, `Enter` adds the matched crewmember as a chip, multiple chips render attribution per reply, removing a chip via the SVG `x` works, no emoji in any rendered glyph (assert via querying for codepoints outside BMP / common emoji ranges). |
| **D10** | Out-of-scope inside AD-719 | n/a | (a) Persistent multi-agent thread storage (deferred AD-719a — adopt WardRoom). (b) Side-nav recent agents list (Copilot left rail) deferred AD-719b. (c) Voice on multi-agent surface deferred AD-718-1. (d) Consensus / quorum within chat — never in this surface; use AD-594b `consult()`. |

### Scope-reframe note (Wave 10 lesson #5)
Issue #513's full scope (autocomplete, `+ Add agent`, side-nav with recent agents, multi-agent reply ordering, attribution) is the upper edge of one AD. v1 picks **mental model (a)** — Captain @-mentions fan-out — because (1) the runtime already supports `@<callsign>` parsing, (2) UI changes are concentrated in `IntentSurface.tsx`, (3) it does not require a new persistence layer. **(b) "crew see each other and chime in"** is a separate forward marker (AD-719a) because it requires shared thread storage (WardRoom adoption) + a routing decision about whether agents observe other agents' messages mid-thread. **(c) "replace IntentSurface with Copilot left rail"** is deferred (AD-719b) because it is a UI refactor, not a feature. The Captain MAY upgrade v1 → v2 later without rewriting v1's primitives.

---

## 5. AD-720 scope — Chat attachments v1: image paste from clipboard

**Issue:** [#514](https://github.com/seangalliher/ProbOS/issues/514). v1 ships **orthogonal piece 1 of 3** — image paste. Drag-drop file upload (piece 2) and tool-attach (piece 3) are deferred (§7).

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **E1** | `AttachmentStore` Protocol | `src/probos/attachments/store.py` (new) | `class AttachmentStore(Protocol):` with `async def write(self, content_hash: str, blob: bytes, mime: str) -> Path`, `async def read(self, content_hash: str) -> bytes`, `async def exists(self, content_hash: str) -> bool`, `async def get_path(self, content_hash: str) -> Path`, `async def size(self, content_hash: str) -> int`. Pydantic-style structural typing — consumers depend on this Protocol, not on the filesystem implementation. |
| **E2** | `FilesystemAttachmentStore` v1 implementation | `src/probos/attachments/filesystem_store.py` (new) | Constructor: `FilesystemAttachmentStore(root: Path)`. Resolves `root` via `_resolve_attachments_dir()` (E3). Filenames are content-addressed `<sha256>.<ext>` only. **Async I/O — PINNED to `asyncio.to_thread(open(...).write)` (Captain ruling 2026-05-09).** `aiofiles` is NOT in `pyproject.toml` (verified — zero hits) and is explicitly forbidden as a new dependency by archived prompts BF-089 and BF-094. The project standard is `run_in_executor` / `asyncio.to_thread`. **Hard stop:** any commit that adds `aiofiles` to `pyproject.toml` or imports `aiofiles` is rejected. |
| **E3** | Path-traversal-safe directory resolver | `src/probos/attachments/store.py` or shared util (drafter picks; do NOT duplicate AD-721 BF #539's `_resolve_avatars_dir`) | `_resolve_attachments_dir(cfg) -> Path` rooted under `_platform_data_dir()` matching the existing pattern in `routers/system.py:641`. Returns an absolute, resolved, `is_relative_to`-checked path. Reuses or mirrors the AD-721 BF #539 helper exactly. |
| **E4** | Config additions | `src/probos/config.py` — drafter identifies the existing model that owns chat or attachments-relevant settings at HEAD (likely a new `ChatConfig` or `AttachmentsConfig`; drafter verifies whether one already exists before creating a new model — Wave 5 anti-pattern of adding parallel config classes). | Fields per §3 row "Configuration via Pydantic". `attachments_enabled: bool = True` — note this is **NOT** a transitional flag (Wave 10 convention #14 only requires default-False on transitional flags; image paste is a stable feature). Allowed-MIME list uses `Field(default_factory=...)`. |
| **E5** | Attachment ingest endpoint | **PINNED:** `src/probos/routers/chat.py` (router prefix `/api`, see §2 row "Ship's Computer chat endpoint"). | `POST /api/chat/attachments` (new route on the same `chat.py` router). Body: `{content_hash: str, blob_b64: str, mime: str}` (JSON, no `multipart/form-data` — see §3 row "Async discipline" for why v1 deliberately defers `UploadFile`). Validates: (1) declared encoded length implicitly bounded by FastAPI request-body cap; (2) **post-decode** raw size ≤ `max_attachment_bytes` (explicit check after `base64.b64decode` — reject 413 if exceeded); (3) `mime in allowed_mime_types`; (4) decoded base64 size matches the declared length to ±1 byte (base64 padding tolerance); (5) magic-bytes match the declared MIME (E6). Returns `{attachment_id, url, mime, size_bytes, sha256}`. **Idempotent**: re-uploading the same content_hash returns the existing record without rewriting. |
| **E6** | Magic-bytes validator | `src/probos/attachments/mime.py` (new) | `validate_image_bytes(blob: bytes, declared_mime: str) -> tuple[bool, str]` — uses `imghdr.what()` (stdlib) AND verifies the first 8/12 bytes match the format-specific magic header. Returns `(True, sniffed_mime)` on agreement, `(False, reason)` otherwise. Reviewer flags any `magic`/`python-magic` dep introduction (libmagic is not in our dep set). |
| **E7** | Image-paste UI | `ui/src/components/IntentSurface.tsx` (extend) | Listen for `paste` event on the input. When `event.clipboardData.items` contains an image, read the `Blob`, compute SHA-256 client-side via `crypto.subtle.digest`, base64-encode (or send via `Blob.arrayBuffer()` + base64 encode), POST to `/api/chat/attachments`. Render an inline preview thumbnail (CSS `max-width: 256px`) above the input chip strip with an inline-SVG `x` to remove before sending. **No emoji in the paperclip / preview close affordance.** Failure modes (network error, oversized blob, disallowed MIME) render structured messages — never silent. |
| **E8** | `data/attachments/` bootstrap | `data/attachments/.gitkeep` (new) + `.gitignore` audit | Add `data/attachments/*` to `.gitignore` (preserve `.gitkeep`). Mirror the AD-721 `data/avatars/` pattern exactly. Reviewer fails if any actual image file gets committed. |
| **E9** | Tests — Python | `tests/test_ad720_attachment_store.py` (new) — Protocol shape, write/read/exists/size, path-traversal rejection, idempotent re-upload returns same hash; `tests/test_ad720_mime_validator.py` (new) — happy paths for each allowed MIME, magic-bytes mismatch rejection, oversized rejection, MIME-extension mismatch rejection; `tests/test_ad720_attachments_endpoint.py` (new) — happy path, oversized 413, disallowed MIME 415, magic-mismatch 415, base64-size-mismatch 400, idempotent re-upload 200 with existing record. | Target ≥ 14 Python tests. |
| **E10** | Tests — UI (Vitest) | `ui/src/__tests__/IntentSurface.imagePaste.test.tsx` (new) | Component-level: paste fixture image → preview renders, remove button (SVG `x`) clears it, oversize blob shows structured error, disallowed MIME shows structured error. No emoji in any rendered glyph. |

### Scope-reframe note
Three orthogonal pieces in issue #514: (1) image paste, (2) file upload (drag-drop / `+ menu`), (3) tool attach. v1 ships **(1) image paste** because it's the only one that does NOT require new content-types on the request boundary (`multipart/form-data`) AND does NOT depend on AD-706/AD-449/AD-423a tool plumbing. (2) file upload introduces `UploadFile` and goes to AD-720a. (3) tool attach is its own architectural surface — chat-scoped capability grants are a permission-layer change — and goes to AD-720b after AD-706 has bedded in. Issue #514's "All agents" / cloud-file picker (M365 OneDrive / GDrive) is OAuth-bound and **belongs to a future commercial tier**; the OSS roadmap entry MUST NOT include pricing or BYOL-vs-managed positioning (per `.github/copilot-instructions.md` "Repository Boundary" rule).

---

## 6. Cross-AD integration points

| Integration point | AD-719 responsibility | AD-720 responsibility |
|---|---|---|
| `IntentSurface.tsx` | Owns the input area, `@`-picker, chip strip, multi-reply rendering. | Adds the paste handler + preview thumbnail + paperclip icon (forward affordance for AD-720a). v1 paperclip icon does NOTHING when clicked except show a tooltip "Paste an image to attach (more coming soon)" — keeps the visual real estate but does not promise unbuilt features. |
| `ChatMessage` shape | Widens `role`; adds `agent_id`, `callsign`. | Adds optional `attachments?: ChatAttachment[]` with `{attachment_id, url, mime, sha256, size_bytes}`. |
| `/api/chat` request body | Passes through `mentions` (parsed by decomposer) — no body shape change required. | Adds optional `attachment_ids: string[]` field — backward compat default `[]`. Server resolves IDs via `AttachmentStore.exists()` before forwarding to the runtime. v1 does NOT inline the image bytes into the LLM prompt. |
| `/api/chat` response body | Adds `per_agent_replies` + `mentions`. | No change. |
| Episodic writes | One episode per fanned-out reply. | If the Captain's turn included attachments, the episode metadata records `attachment_ids` (NOT the bytes). |
| Configuration | None. | New chat-attachments config (E4). |
| **Build order** | AD-719 prompt is independent. **HARD ORDERING (Captain ruling 2026-05-09):** AD-719 ships FIRST as commit N. The Builder MUST land AD-719's full diff (including the widened `ChatMessage.role: 'user' \| 'agent' \| 'system'` and `agent_id?` / `callsign?` fields in `ui/src/store/types.ts`) before opening AD-720. | AD-720 ships SECOND as commit N+1, building on top of AD-719's widened shape and ADDING `attachments?: ChatAttachment[]` to the same `ChatMessage` type. **The Builder MUST NOT interleave commits across the two ADs.** Each AD lands as one self-contained commit; full pytest + Vitest gates are green between commits N and N+1. AD-720's UI tests assume the AD-719 widening is already at HEAD — no "rolled back" branch coverage required. |

---

## 7. Out-of-scope / deferred

| Deferred item | Why deferred | Where it lands |
|---|---|---|
| Multi-agent thread persistence (crew see each other; mental model b) | Requires shared thread storage (WardRoom adoption) + agent-observes-thread routing. Architectural surface, not a v1 polish. | **AD-719a** — forward marker, file at gate-3. |
| Copilot-style left rail + Agents nav (mental model c) | UI refactor, not a feature. v1 keeps `IntentSurface` shape. | **AD-719b** — forward marker, file at gate-3. |
| Voice on multi-agent chat | Specified in issue #513 as deferred to AD-718-1. | AD-718-1 (already filed). |
| Consensus / quorum within chat | Wrong surface — use `consult()` (AD-594b). | n/a — never in this surface. |
| File upload (drag-drop / `+ Upload`) | Introduces `UploadFile` + `multipart/form-data` — its own architectural surface. | **AD-720a** — forward marker, file at gate-3. |
| Tool attach (AD-706 BrowserTool, AD-449 MCP tools) | Permission-layer change (chat-scoped capability grants); depends on AD-706 having bedded in. | **AD-720b** — forward marker, file at gate-3. |
| Cloud file picker (OneDrive / GDrive) | OAuth plumbing; belongs to a future commercial tier. **Public roadmap entry MUST NOT include pricing or BYOL-vs-managed positioning** — only the technical extension point (per `.github/copilot-instructions.md` "Repository Boundary" rule). | **AD-720c (commercial)** — public forward marker is technical-only ("OAuth-bound cloud file source"); commercial scope (managed vs BYOL) lives in the private commercial repo. |
| Vision pipe-through (image bytes → LLM) | v1 stores + displays only. Sending images to a vision-capable agent is a separate codepath with its own prompt-injection threat surface. | **AD-720d** — forward marker, file at gate-3. |
| Persistent multi-agent chat history under WardRoom | Issue #513 lists this as out of scope for v1 ("use existing Ward Room storage" if/when threading goes persistent). | Folded into AD-719a. |

**Scope-reframe note (Wave 10 lesson #5):** AD-719's draft (D1–D9, ~12 tests) is right at the upper edge of one AD. AD-720's draft (E1–E10, ~14 tests) is a tight v1 because the UI surface is small and the server-side is one new endpoint + one new module. The `@`-picker keyboard-nav state machine (↑/↓/Esc/Tab) has been pinned as DEFERRED to AD-719c (Captain ruling 2026-05-09, see §4 D3); v1 ships mouse + Enter only.

---

## 8. Hard-stop conditions for the Builder

Standard hard-stop rules from `BUILDER-EXECUTION-PLAN.md` apply, **plus**:

1. **Phantom field on `ChatMessage`.** If AD-719's tests reference a `ChatMessage` field the Builder didn't actually add (e.g. `mentions: string[]` instead of agreed-on `agent_id` + `callsign`), STOP — do not silently add the field elsewhere.
2. **`UploadFile` introduced in v1.** Hard stop. AD-720 v1 deliberately ships JSON-body image paste with base64. `UploadFile` belongs to AD-720a.
3. **`subprocess.run` introduced under `src/probos/attachments/`.** Hard stop. Async only.
4. **`exec`/`eval`/`compile` on attachment metadata or chat content.** Hard stop. Reviewer greps the diff.
5. **Working-tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to the Captain (per `/memories/probos-architect-learnings.md` 2026-05-08 incident).
6. **Emoji literal in the diff.** Hard stop. Inline SVG only.
7. **Consensus/quorum coupling.** Any commit that touches `src/probos/consensus/` from AD-719 — hard stop. Multi-target chat is fan-out, not deliberation.
8. **`libmagic` / `python-magic` dependency added.** Hard stop. Use stdlib `imghdr` + magic-byte sniff per E6.
9. **`.gitignore` regression.** If the Builder forgets to gitignore `data/attachments/*`, hard stop. Audit `git status --ignored data/attachments` before merge.
10. **Episodic write skipped on a fan-out branch.** Hard stop. Every reply produces an episode.
11. **Pricing / commercial-tier language landing in the public roadmap entry for AD-720c.** Hard stop (the `*(Commercial)*` tag is "see private repo," NOT permission to inline pricing). Reviewer audits any roadmap edit in the wave's diff.
12. **PROGRESS.md L11 stale.** Pre-flight: confirm `current highest AD: AD-721i` is the current line. If stale, update in-wave; if not, leave alone. Do NOT fold this into a separate BF.

---

## 9. Acceptance criteria

- **Test count target:** AD-719 ≥ 12 Python tests + 1 Vitest test; AD-720 ≥ 14 Python tests + 1 Vitest test. Wave gate: full `pytest tests/ -q -n 16 --dist=loadfile` is green AND `cd ui && npx vitest run` is green. **Fallback:** if the dev machine regresses on `-n 16` (worker crashes from heavy fixtures), drop to `-n 8` and document in the build report — do NOT silently switch to `-n auto` (xdist + ChromaDB fixture concurrency is the documented BF #466 failure mode).
- **Files touched (target list — drafter refines):**
  - **New:** `src/probos/attachments/__init__.py`, `src/probos/attachments/store.py`, `src/probos/attachments/filesystem_store.py`, `src/probos/attachments/mime.py`, `data/attachments/.gitkeep`, plus 5 new Python test files and 2 new Vitest files.
  - **Modified:** `ui/src/store/types.ts`, `ui/src/components/IntentSurface.tsx`, `src/probos/routers/chat.py` (PINNED — owns `/api/chat`), `src/probos/config.py`, `.gitignore`. Possibly `ui/src/store/useStore.ts` if the multi-recipient render path needs a store helper.
  - **`.gitignore` diff (PINNED — mirror exactly the AD-721 BF #539 / `data/avatars/*` shape at `.gitignore:30-39`):**
    ```gitignore
    # AD-720: attachments dir is shipped (with .gitkeep), but image blobs are not.
    !data/attachments/
    data/attachments/*
    !data/attachments/.gitkeep
    ```
- **GH issues to close:** [#513](https://github.com/seangalliher/ProbOS/issues/513) (AD-719), [#514](https://github.com/seangalliher/ProbOS/issues/514) (AD-720).
- **Forward markers to file at gate-3 (BUILDER-EXECUTION-PLAN Post-Sweep step 6):** AD-719a (persistent multi-agent threads under WardRoom), AD-719b (Copilot-style left rail), AD-719c (`@`-picker keyboard-nav polish, pinned-deferred), AD-720a (file upload via `UploadFile`), AD-720b (tool attach), AD-720c (cloud file picker — **technical-only public marker**; commercial scope private), AD-720d (vision pipe-through).
- **Engineering principles compliance line (mandatory in each prompt):** *"Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."*
- **Phantom-API pre-check:** drafter runs `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-719-multi-agent-chat-v1.md prompts/ad-720-chat-attachments-image-paste-v1.md` AFTER writing the prompt bodies. Zero phantoms is the bar.
- **Verify-first against HEAD:** every concrete file/line/method citation greps to a hit at HEAD (or the prompt explicitly creates that entity). The router owning `/api/chat` is PINNED in §2 / D5 / E5 to `src/probos/routers/chat.py` — drafter does NOT need to re-verify, but MAY confirm with a single grep before drafting.

---

## 10. AD-numbering verification

**Highest pre-existing AD: AD-721i** (per `PROGRESS.md` L11, confirmed via grep 2026-05-09).

| AD | Status |
|---|---|
| AD-718 | SHIPPED — per-agent voice profile (referenced at `agents.py:224`). |
| AD-718-1 | Forward marker — voice on multi-agent surface. |
| AD-719 | **THIS WAVE — issue #513.** |
| AD-719a | **Reserved (forward marker)** — persistent multi-agent threads under WardRoom. |
| AD-719b | **Reserved (forward marker)** — Copilot-style left rail + Agents nav. |
| AD-719c | **Reserved (forward marker)** — `@`-picker keyboard-nav polish (↑/↓/Esc/Tab); pinned-deferred per §4 D3 Captain ruling. |
| AD-720 | **THIS WAVE — issue #514.** |
| AD-720a | **Reserved (forward marker)** — file upload via `UploadFile` + `multipart/form-data`. |
| AD-720b | **Reserved (forward marker)** — tool attach (depends on AD-706 + AD-449). |
| AD-720c | **Reserved (forward marker, *Commercial* tier — public marker is technical-only)** — cloud file picker (OneDrive / GDrive) via OAuth. |
| AD-720d | **Reserved (forward marker)** — vision pipe-through (image bytes → vision-capable agent). |
| AD-721 / 721a–721j | Already in flight or shipped (Wave 133/134). |

**Newly reserved sub-AD numbers (filed at gate-3 as forward markers):** AD-719a, AD-719b, AD-719c, AD-720a, AD-720b, AD-720c, AD-720d. **No collisions** with the existing 718 / 721 ladders. Drafter MUST re-grep `DECISIONS.md` and `decisions-era-*.md` for any of these labels before finalizing — never assume.

---

## Final report (Architect)

**Pre-draft validation (mandatory):** Before drafting either prompt body, the architect MUST validate that all `Class.method` and `module.path` references in this dispatch resolve at HEAD. Run `pwsh scripts/phantom-api-precheck.ps1 prompts/WAVE-135-DISPATCH.md` and surface any phantoms in the final report under a dedicated "Phantom-API pre-check" subsection. Zero phantoms is the bar; if any are found, fix the dispatch first, then draft.

Drafter writes both prompts (`prompts/ad-719-multi-agent-chat-v1.md`, `prompts/ad-720-chat-attachments-image-paste-v1.md`) only after the Captain approves this dispatch. After both prompts are written, the drafter returns ONE message containing:

1. One-line summary per prompt.
2. Verify-first findings (any contradictions with this dispatch — in particular, the exact router file owning `/api/chat`, the exact Pydantic model owning chat config, the exact UI selector exposing live crew callsigns).
3. Risk classification per prompt (LOW / MEDIUM / HIGH).
4. AD-719: confirmed multi-recipient response shape; confirmed `@`-picker keyboard-nav scope (v1 vs deferred to AD-719c).
5. AD-720: confirmed `aiofiles` vs `asyncio.to_thread` async-I/O choice; confirmed magic-byte validator covers all four allowed MIMEs.
6. Forward markers filed (AD-719a, AD-719b, AD-720a, AD-720b, AD-720c-public-only, AD-720d).
7. Standing-convention concerns surfaced (commercial-tier leak audit, no-emoji audit, `UploadFile` audit).
8. Audit trail: file paths actually read; URLs fetched (issue bodies).
