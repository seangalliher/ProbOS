# AD-720d — Vision pipe-through v1

**Status:** READY FOR BUILDER
**Wave:** 139
**Dispatch:** [prompts/WAVE-139-DISPATCH.md](prompts/WAVE-139-DISPATCH.md)
**Depends on:** **AD-720a (same wave; AD-720a MUST land as commit N before this AD lands as commit N+1 — HARD ORDER)**, AD-720 (Wave 135, SHIPPED — `AttachmentStore`, `FilesystemAttachmentStore`, `validate_image_bytes`)
**Pairs with:** AD-720a (commit N)
**Issue:** [#552](https://github.com/seangalliher/ProbOS/issues/552)
**Risk:** **MEDIUM-HIGH** — wires a previously-dead `attachment_ids` field into the live chat path. New conditional branch in the main chat handler is the highest-blast-radius change in the wave. Additive `LLMRequest.messages` field is a real shape change (one-line, additive, but every `LLMRequest(...)` call site verified against §3 below). Vision-tier health fallback is the never-silent-drop guarantee.
**Estimated tests:** ≥ 8 Python, 0 Vitest

> **Builder:** read [prompts/WAVE-139-DISPATCH.md](prompts/WAVE-139-DISPATCH.md) for cross-AD context, license posture, and the engineering-principles checklist. Read [prompts/BUILDER-EXECUTION-PLAN.md](prompts/BUILDER-EXECUTION-PLAN.md) for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

> **Hard order:** AD-720a is **commit N**, AD-720d is **commit N+1**. Reviewer fails any squash. This prompt's `runtime.config.attachments.vision_tier` / `text_extraction_max_bytes` / `pdf_extraction_enabled` reads ASSUME AD-720a's `config.py` extension already landed.

---

## 1. Goal

Wave 135 added `ChatRequest.attachment_ids: list[str]` (`api_models.py:24`). Wave 139 commit N (AD-720a) adds the multipart upload endpoint + the drag-drop UI. **The server-side handler still ignores the `attachment_ids` field.** AD-720d wires it for the first time.

When the user sends a chat turn with one or more `attachment_ids`:
- **Image attachments** route to a vision-capable LLM via the existing `LLMClient` tier system. The handler builds a multimodal `messages` array (Anthropic/OpenAI shape — `[{role: "user", content: [{type: "text", text: ...}, {type: "image", source: {type: "base64", media_type: ..., data: ...}}, ...]}]`) and calls `runtime.llm_client.complete(LLMRequest(messages=..., tier=cfg.vision_tier))` directly, bypassing the decomposer.
- **Non-image attachments** (text/markdown/JSON/CSV) get inline text extraction; the extracted text is appended to `req.message` as a `<ATTACHMENT name="..." mime="...">...</ATTACHMENT>` block, and the augmented prompt flows through the normal decomposer path.
- **PDF attachments** (with `pdf_extraction_enabled=False` — the v1 default) produce a deferred-feature stub: "I see a PDF named `<filename>.pdf` attached but PDF text extraction is not yet wired (AD-720a-1)." No bytes enter any prompt.
- **Vision-tier unhealthy** → log structured warning + return a text-only stub naming the attachments. **Never silent drop.**

The existing zero-attachment chat path is bit-for-bit unchanged.

### Why now (Captain 2026-05-10)

> "I pasted Ezri's avatar and she said 'I have no visual input capability.'"

That was correct per the AD-720d deferral, but the gap is now visible. Captain explicitly asked about vision pipe-through during Wave 137 wrap. AD-720a ships the upload surface; AD-720d closes the routing loop.

### Backwards-compat guarantee (HARD CONSTRAINTS)

1. **Zero-attachment chat turns are bit-for-bit unchanged.** The new branch only fires when `req.attachment_ids` is non-empty AND `cfg.attachments.enabled is True`.
2. **Existing slash-command + DM + at-mention fan-out branches run BEFORE the attachment branch.** Reviewer verifies the insertion point is AFTER the at-mention fan-out (which returns) and the DM single-mention return, but BEFORE the `runtime.process_natural_language(req.message, ...)` call at the chat handler's main path.
3. **`LLMRequest.messages` is additive.** When `messages is None` (every existing call site at HEAD), the OpenAI-compatible client behaves exactly as today (POSTs the `prompt`-shape body). Reviewer verifies via the existing `test_*` files staying green and the call-site audit in §3.
4. **No silent drop.** The vision-tier-unhealthy path returns a structured stub message naming the attachments; it does NOT 500, does NOT drop the turn, and does NOT swallow the request.

---

## 2. License posture

- OSS Apache 2.0 stays Apache 2.0.
- **Zero new Python deps.** Multimodal payload formatting uses stdlib `base64` + `json`. Text extraction uses stdlib `json` + `csv` + `io`. The Copilot proxy at `127.0.0.1:8080` accepts Anthropic-shape multimodal `messages` JSON via the existing `httpx`-based `OpenAICompatibleClient`.
- **Zero new JS deps.** AD-720d ships zero UI changes.
- **Forbidden in v1 (HARD STOPS — see §8):**
  - Anthropic / OpenAI vendor SDKs. The existing `httpx`-based client posts OpenAI-compatible `messages` JSON which Anthropic's `/v1/messages` endpoint and the Copilot proxy both accept. Reviewer fails any `import anthropic` or `import openai` in the diff.
  - `pypdf` / `PyPDF2` — PDF text extraction is AD-720a-1.
  - `python-docx` / `openpyxl` — DOCX/XLSX extraction is AD-720a-1.
- **Pattern absorption:** Anthropic / OpenAI multimodal message shapes are industry-standard public API contracts; absorbing the shape (not vendor code) is clean for an Apache 2.0 project.

---

## 3. Verified Against Codebase (2026-05-10)

```
git log --oneline -1
   87db564 (HEAD -> main, origin/main, origin/HEAD) Wave 138 retrospective: archive prompts

# attachment_ids — UI sends it, server ignores it (this AD wires it)
grep -n "attachment_ids" src/probos/api_models.py
    24:     attachment_ids: list[str] = Field(default_factory=list)

git grep -n "attachment_ids" -- 'src/probos/**/*.py'
    src/probos/api_models.py:24:    attachment_ids: list[str] = Field(default_factory=list)
    (zero matches in any router/agent/handler — confirms the field is currently dead server-side)

# Chat handler entry — insertion point for the attachment branch
grep -n "runtime.process_natural_language\|extract_callsign_mention" src/probos/routers/chat.py
   126:     if is_directed_mention(text):           # at-mention fan-out (returns inside)
   225:     mention = extract_callsign_mention(text) # single-DM (returns inside)
   265:         dag_result = await asyncio.wait_for(
   266:             runtime.process_natural_language(  # MAIN NL DECOMPOSER PATH
   267:                 req.message,

# LLMRequest at HEAD — `prompt: str` field; AD-720d adds `messages: list[dict] | None = None`
grep -n "^class LLMRequest\|^    prompt:\|^    messages:" src/probos/types.py
   227: class LLMRequest:
   230:     prompt: str
   (no messages field at HEAD — confirms additive change)

# LLMClient.complete entry point — read-only at the LLMClient level for AD-720d
grep -n "async def complete\|def get_health_status" src/probos/cognitive/llm_client.py
    27:     async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
    32:     def get_health_status(self) -> dict[str, Any]:

# AttachmentsConfig — POST-AD-720a state (commit N) is what this prompt assumes
# At HEAD before AD-720a:
grep -n "class AttachmentsConfig" src/probos/config.py
   941: class AttachmentsConfig(BaseModel):
   #     fields at HEAD: enabled, attachments_dir, max_attachment_bytes, allowed_mime_types
   #     post-AD-720a (commit N): + vision_tier, text_extraction_max_bytes, pdf_extraction_enabled

# vision/multimodal — confirms vision_dispatch and text_extractor are genuinely new
git grep -n "vision\|multimodal" src/probos/cognitive/llm_client.py
    (zero matches)

# Confirms the vision_dispatch.py and text_extractor.py modules don't exist
Test-Path src/probos/cognitive/vision_dispatch.py    → False
Test-Path src/probos/cognitive/text_extractor.py     → False

# AttachmentStore Protocol public surface — read/exists/get_path/size are the methods AD-720d uses
grep -n "class AttachmentStore\|async def " src/probos/attachments/store.py
   14: class AttachmentStore(Protocol):
   17:     async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:
   22:     async def read(self, content_hash: str) -> bytes:
   25:     async def exists(self, content_hash: str) -> bool:
   28:     async def get_path(self, content_hash: str) -> Path:
   31:     async def size(self, content_hash: str) -> int:

# LLMRequest call-site audit — every caller at HEAD uses kwargs (confirmed safe for additive `messages`)
git grep -n "LLMRequest(" -- 'src/probos/**/*.py' | head -30
    src/probos/agent_onboarding.py:594:                LLMRequest(
    src/probos/cognitive/agent_designer.py:282:    request = LLMRequest(prompt=prompt, tier="deep", max_tokens=4096)
    src/probos/cognitive/agent_patcher.py:110:                LLMRequest(
    src/probos/consensus/escalation.py:233:    request = LLMRequest(
    src/probos/cognitive/architect.py:300:                selection_request = LLMRequest(
    src/probos/cognitive/builder.py:631:    request = LLMRequest(
    src/probos/cognitive/builder.py:884:        request = LLMRequest(
    src/probos/cognitive/builder.py:1882:        request = LLMRequest(
    src/probos/cognitive/builder.py:2799:            fix_request = LLMRequest(
    src/probos/cognitive/causal_reasoning.py:311:    request = LLMRequest(
    src/probos/cognitive/code_reviewer.py:100:    request = LLMRequest(
    src/probos/cognitive/cognitive_agent.py:1712:    request = LLMRequest(
    src/probos/cognitive/cognitive_agent.py:2703:    request = LLMRequest(
    src/probos/cognitive/cognitive_agent.py:2930:    request = LLMRequest(
    src/probos/cognitive/cognitive_agent.py:4075:            llm_request = LLMRequest(
    src/probos/cognitive/communication_benchmarks.py:124:    llm_response = await llm_client.complete(LLMRequest(
    src/probos/runtime.py:3705:        request = LLMRequest(prompt=prompt, tier=tier, max_tokens=2048)
    src/probos/cognitive/correction_detector.py:104:        LLMRequest(prompt=prompt, tier="fast", max_tokens=512),
    src/probos/cognitive/decomposer.py:374:    request = LLMRequest(
    src/probos/cognitive/decomposer.py:458:    request = LLMRequest(
    src/probos/cognitive/dreaming.py:2515:        req = LLMRequest(
    (... all use kwargs — none rely on `messages` being absent because the field doesn't exist yet at HEAD)
```

**Call-site safety verdict (LLMRequest.messages additive field):** Every caller at HEAD uses `LLMRequest(prompt=..., tier=..., ...)` kwargs. Adding an optional `messages: list[dict] | None = None` field is safe — no positional caller breaks, no kwarg conflict (no caller already uses a `messages=` kwarg). The OpenAI-compatible client's request-build logic must check `request.messages is not None` before using it; when `None`, the existing `prompt`-shape codepath runs unchanged. **Reviewer verifies via the existing `tests/` LLM tests staying green at this commit.**

**Dispatch contradictions surfaced (fix in this prompt only — do NOT edit the dispatch):**

1. **Dispatch §5 D3 says** "After the slash-command + DM branches, BEFORE the existing decompose/dispatch path, check: `if req.attachment_ids and runtime.config.attachments.enabled:`." Confirmed insertion point in `chat.py` is AFTER the at-mention fan-out's return at ~line 217, AFTER the single-DM return at ~line 252, BEFORE `runtime.process_natural_language` at line 266. The actual line numbers shift slightly post-AD-720a (the JSON-path refactor reflows nearby code); Builder pins the insertion point semantically (after both early-return branches, before the main `runtime.process_natural_language` call), not by line number.
2. **Dispatch §5 D4 vision-tier health key.** Verified `LLMClient.get_health_status()` at HEAD `llm_client.py:32` returns `{"tiers": {tier: {"status": "operational" | ...}}, "overall": ...}`. The exact "operational" string is the success literal (verified in the default-implementation literal at `llm_client.py:36–39`). AD-720d treats any non-`"operational"` value as unhealthy.
3. **Dispatch §5 D2 PDF branch.** `extract_text(blob, "application/pdf", ...)` raises `NotImplementedError("AD-720a-1: PDF extraction not yet wired")`. The dispatch layer catches it and produces the deferred-feature stub. **Reviewer fails any prompt that ships PDF parsing code path that depends on a missing dep.**

---

## 4. Scope (v1 only)

- New module `src/probos/cognitive/vision_dispatch.py` — formats multimodal `messages` payload from `(prompt, attachment_ids, store, mime_lookup, *, text_extraction_max_bytes)`.
- New module `src/probos/cognitive/text_extractor.py` — extracts plain text / markdown / JSON / CSV. Raises `NotImplementedError` for PDF.
- Additive field `messages: list[dict] | None = None` on `LLMRequest` (`src/probos/types.py`).
- One-line behaviour update in `OpenAICompatibleClient` request-build path (`src/probos/cognitive/llm_client.py`): when `request.messages is not None`, pass it through verbatim to the `messages` field of the outgoing JSON body; else use the existing `prompt`-shape codepath unchanged. Reviewer verifies the existing test suite stays green.
- New conditional branch in the chat handler (`src/probos/routers/chat.py`): after early-return branches, before the main NL-decomposer call.
- Tiny helper in `src/probos/attachments/filesystem_store.py` to derive MIME from the on-disk extension (`mime_for_attachment_id(content_hash) -> str | None`) — the GET endpoint already does this inline at HEAD lines 558–566; AD-720d extracts the helper for DRY reuse by `vision_dispatch`. (After AD-720a's DRY-ification of the GET reverse lookup, the helper is a thin call-through.)
- Tests: ≥ 8 Python, 0 Vitest.

## 5. Non-goals (deferred forward markers)

| Out of scope | Why deferred | Forward marker |
|---|---|---|
| PDF text extraction | Needs `pypdf`; not in `pyproject.toml`. v1 stub names the attachment and says extraction is not yet wired. | **AD-720a-1** |
| `.docx` / `.xlsx` text extraction | Needs `python-docx` + `openpyxl`. | **AD-720a-1** |
| Multi-image batch latency / context-budget evaluation | v1 supports `attachment_ids` array but the test matrix focuses on single-image. Multi-image latency, prompt-context budget, and degradation behaviour need a separate evaluation. | **AD-720d-1** |
| Per-agent vision capability designation | v1 routes purely on attachment MIME, not on the receiving agent. Captain may want Counselor to "see" but Engineering to text-only. | **AD-720d-2** |
| Streaming vision responses | v1 calls `complete(...)` and returns the whole response. Streaming is a separate concern. | (not filed) |
| Audio attachments | Voice/transcription pipeline is its own arc. | **AD-720e** |
| Image-processing subprocess (resize before vision call) | Out of scope. Bytes are sent as-is to the vision tier. | (not filed) |
| Per-agent attachment metadata in episodic | v1 episode metadata records `attachment_ids` (not bytes) — same as AD-720 already does. AD-720d does not change episodic shape. | (not filed) |

## 6. Deliverables

### D1. Vision dispatch module

**New file:** `src/probos/cognitive/vision_dispatch.py`

Public exports:
```python
async def build_multimodal_messages(
    prompt: str,
    attachment_ids: list[str],
    store: AttachmentStore,
    mime_lookup: Callable[[str], str | None],
    *,
    text_extraction_max_bytes: int,
    pdf_extraction_enabled: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """AD-720d: build the OpenAI/Anthropic-shape ``messages`` content array.

    Returns ``(messages, image_attachment_ids)`` where ``messages`` is the
    one-element list ``[{"role": "user", "content": [<content_items>]}]``,
    and ``image_attachment_ids`` is the subset of ``attachment_ids`` whose
    MIME is ``image/*`` (the caller uses this to decide whether the turn
    should route via the vision tier or the standard text path).

    Content-item shape per attachment MIME:
      - image/*: ``{"type": "image", "source": {"type": "base64",
                   "media_type": "<mime>", "data": "<b64>"}}``  (Anthropic shape)
      - text/* | application/json: ``{"type": "text",
                   "text": "<ATTACHMENT name=\"...\" mime=\"...\">...</ATTACHMENT>"}``
      - application/pdf with pdf_extraction_enabled=False: ``{"type": "text",
                   "text": "<ATTACHMENT name=\"...\" mime=\"application/pdf\"
                            note=\"PDF extraction not yet wired (AD-720a-1)\" />"}``

    The user's text ``prompt`` is included as the FIRST content item:
      ``{"type": "text", "text": prompt}``

    Tier-2 log-and-degrade: if a single attachment fails to load (FileNotFound,
    extraction error other than NotImplementedError), log a structured warning
    and append a ``<ATTACHMENT name="..." mime="..." note="failed_to_load" />``
    text block. Other attachments still render. **Never silent drop.**
    """
```

Implementation rules:
- One read per attachment. `blob = await store.read(content_hash)`. MIME via the `mime_lookup(content_hash)` callable.
- Image MIMEs base64-encode the bytes once. `data = base64.b64encode(blob).decode("ascii")`.
- Non-image MIMEs route through `text_extractor.extract_text(blob, mime, max_bytes=text_extraction_max_bytes)`; the returned `(text, was_truncated)` is wrapped in the `<ATTACHMENT>` block. Truncated extractions append `\n[TRUNCATED]` already (the extractor's job).
- PDF branch: `pdf_extraction_enabled=False` → emit the deferred-feature stub directly (don't call extractor). `pdf_extraction_enabled=True` → call extractor; the extractor raises `NotImplementedError` until AD-720a-1 wires it; this AD's dispatch catches the exception and emits the same stub.
- **No private-attr access.** The module consumes `AttachmentStore` (Protocol), `mime_lookup` (callable), and stdlib only.
- **Async discipline.** All `store.read` calls are `await`-ed. No fire-and-forget. Multiple attachments: `asyncio.gather` is acceptable and recommended for the read-then-encode batch.

### D2. Text extractor module

**New file:** `src/probos/cognitive/text_extractor.py`

Public export:
```python
async def extract_text(
    blob: bytes,
    mime: str,
    *,
    max_bytes: int,
) -> tuple[str, bool]:
    """AD-720d: extract text from non-image attachment bytes.

    Returns ``(extracted_text, was_truncated)``.

    Branches:
      - text/plain | text/markdown:
          ``blob.decode("utf-8", errors="strict")``  (raises UnicodeDecodeError on bad bytes)
      - application/json:
          ``json.dumps(json.loads(blob.decode("utf-8")), indent=2)``  (pretty-print)
      - text/csv:
          ``blob.decode("utf-8", errors="strict")``  (pass-through; LLM handles CSV reasoning)
      - application/pdf:
          raises ``NotImplementedError("AD-720a-1: PDF extraction not yet wired")``

    Truncation: if ``len(extracted_text.encode("utf-8")) > max_bytes``,
    truncate at the byte boundary (decode-safe via
    ``text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")``)
    and append ``\\n[TRUNCATED]``. Returns ``was_truncated=True``.

    Unknown MIME: raises ``ValueError(f"unsupported MIME for text extraction: {mime!r}")``.
    """
```

Implementation rules:
- **`errors='strict'` on all decodes.** Reviewer fails any `errors='replace'` (silent corruption is not Tier-2 acceptable for a content-type validator/extractor).
- The `errors='ignore'` on the truncation re-decode is the ONLY ignore allowed and only because we deliberately drop a trailing partial multibyte char to stay under the byte cap.
- No subprocess, no external tools. stdlib only.
- `csv.reader` is NOT used here (the extractor passes CSV text through; the LLM reasons over CSV natively). `csv.reader` is in the AD-720a `validate_attachment_bytes` validator only.

### D3. Additive `LLMRequest.messages` field

**File:** `src/probos/types.py` (modify dataclass at line 226–239)

Add one line:
```python
@dataclass
class LLMRequest:
    """A request to the LLM client."""

    prompt: str
    system_prompt: str = ""
    tier: str = "standard"
    temperature: float = 0.0
    top_p: float | None = None
    max_tokens: int = 2048
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tools: list[dict] | None = None
    tool_choice: str = "auto"
    # AD-720d: when set, takes precedence over `prompt` for multimodal turns.
    messages: list[dict] | None = None
```

`LLMRequest` is a `@dataclass` (not frozen). The new field has a default of `None`, so every existing call site at HEAD continues to construct the dataclass with the same kwargs and gets `messages=None`. The audit in §3 confirms zero positional callers.

### D4. `OpenAICompatibleClient` request-build update

**File:** `src/probos/cognitive/llm_client.py` (modify the request-build site that constructs the outgoing JSON body)

When `request.messages is not None`, pass the `messages` array verbatim as the `"messages"` field of the outgoing JSON body. **Skip the `prompt`-based message synthesis.** Tier resolution, model resolution, headers, timeout, rate limiting — all unchanged.

When `request.messages is None`: the existing codepath runs verbatim. **Reviewer verifies via the existing LLM client tests staying green at this commit.** (No new test for the `messages is None` path is required; the existing tests already cover it.)

Builder picks the smallest possible diff. Search for the function that builds the OpenAI/Anthropic JSON body (likely a private method on `OpenAICompatibleClient` named like `_build_request_body`, `_build_payload`, or inlined in `complete`). Add a one-line conditional. Reviewer fails any diff that materially refactors the request-build path beyond this addition.

### D5. MIME-by-content-hash helper

**File:** `src/probos/attachments/filesystem_store.py` (append)

```python
def mime_for_attachment_id(content_hash: str, *, _store_root: Path) -> str | None:
    """AD-720d: derive MIME from the on-disk extension.

    Returns the MIME or None if the attachment isn't stored. Uses the
    module-level _MIME_TO_EXT dict as the single source of truth (AD-720a
    DRY-ified the GET endpoint's reverse lookup against the same dict).
    """
```

After AD-720a's DRY refactor, the GET endpoint at `chat.py` calls this helper instead of inlining the reverse lookup. AD-720d's `vision_dispatch.build_multimodal_messages` calls it via the `mime_lookup` callable.

If AD-720a's DRY refactor used a different name (`_ext_to_mime`, `derive_mime_from_path`, etc.) and didn't expose it module-level, the Builder reconciles in this AD — pick one name, expose it once, call it from both sites. Reviewer fails any diff that ships two parallel reverse-lookup paths.

### D6. Routing branch in chat handler

**File:** `src/probos/routers/chat.py` (modify the main `chat` function)

Insert AFTER the at-mention fan-out branch (`is_directed_mention(text)` block returns at ~line 217 at HEAD) and AFTER the single-DM branch (`mention = extract_callsign_mention(text)` returns at ~line 252 at HEAD), and BEFORE the `runtime.process_natural_language` call at ~line 266 at HEAD. **Pin the insertion point semantically** (between the early-return branches and the main NL path) — the JSON-path helper extraction in AD-720a may shift line numbers slightly.

Pseudocode:
```python
# AD-720d: vision pipe-through + non-image inline extraction
cfg_attach = getattr(runtime.config, "attachments", None)
if req.attachment_ids and cfg_attach is not None and cfg_attach.enabled:
    from probos.attachments.filesystem_store import mime_for_attachment_id
    from probos.cognitive.vision_dispatch import build_multimodal_messages
    from probos.cognitive.text_extractor import extract_text   # noqa: F401 (used by vision_dispatch)
    from probos.types import LLMRequest

    store = _get_attachment_store(runtime)
    # Mime lookup — _store_root injection per AD-720a's helper signature
    def _mime_for(h: str) -> str | None:
        return mime_for_attachment_id(h, _store_root=store._root)  # AD-720d uses public API only — see note*
    # *NOTE: ``_store_root`` is a private kwarg on the helper (one-arg public
    # ``mime_for_attachment_id(h)`` is preferable; Builder picks based on
    # AD-720a's actual final shape — reviewer fails any private-attr reach
    # from the dispatch module itself; keeping the bridge in chat.py is acceptable
    # because the chat router already calls _get_attachment_store).

    messages, image_ids = await build_multimodal_messages(
        prompt=text,
        attachment_ids=req.attachment_ids,
        store=store,
        mime_lookup=_mime_for,
        text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
        pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
    )

    if image_ids:
        # Vision-tier health check
        health = runtime.llm_client.get_health_status()
        tier = cfg_attach.vision_tier
        tier_status = (health.get("tiers", {}).get(tier) or {}).get("status")
        if tier_status != "operational":
            logger.warning(
                "AD-720d vision tier=%s unavailable (status=%s); returning text-only "
                "stub naming attachments. attachment_ids=%s",
                tier, tier_status, req.attachment_ids,
            )
            stub = (
                f"I see {len(req.attachment_ids)} attachment(s) "
                f"({', '.join(req.attachment_ids[:3])}"
                f"{'...' if len(req.attachment_ids) > 3 else ''}) "
                f"but vision processing is currently unavailable. Try again in a moment."
            )
            return {"response": stub, "dag": None, "results": None}
        # Vision-tier-routed completion
        llm_response = await runtime.llm_client.complete(
            LLMRequest(prompt="", messages=messages, tier=tier, max_tokens=2048),
        )
        return {"response": llm_response.content or "(no response)", "dag": None, "results": None}

    # Non-image only: synthesize an augmented prompt and fall through to NL path
    text_blocks = [
        m.get("text", "")
        for m in messages[0]["content"]
        if m.get("type") == "text" and m.get("text") != text  # skip the user prompt itself
    ]
    if text_blocks:
        req = req.model_copy(update={"message": text + "\n\n" + "\n\n".join(text_blocks)})
        text = req.message  # keep local mirror in sync
```

Rules:
- **The only `runtime.llm_client.complete` call in this branch is for the image-routed path.** Non-image attachments fall through to `runtime.process_natural_language` (the existing decomposer path) with an augmented prompt.
- **The `LLMRequest(prompt="", messages=messages, ...)` construction sets `prompt=""` because `messages` takes precedence in D4's request-build update.** The empty prompt is never observed (the request-build skips the `prompt`-shape path when `messages is not None`).
- **Vision-tier health check is non-negotiable.** Reviewer fails any branch that calls `complete()` without first checking `get_health_status()`.
- **The fall-through (non-image-only) path** preserves the existing decomposer + episodic + slash-command + reflection codepath. The augmented prompt gets the same treatment as a normal text turn.

### D7. Tests — Python (≥ 8)

**New file:** `tests/test_ad720d_vision_pipethrough.py`

Use a `MockLLMClient` (or a small stub) whose `complete` records the request and returns a canned `LLMResponse`. The store fixture pre-writes blobs under known sha256s. The runtime config has `attachments.enabled=True`, `vision_tier="standard"`, `text_extraction_max_bytes=1024`, `pdf_extraction_enabled=False`.

| # | Test | Validates |
|---|---|---|
| 1 | `test_image_attachment_routes_via_vision_tier` | Send a chat turn with one PNG `attachment_id`. Assert `MockLLMClient.complete` was called with an `LLMRequest` whose `messages` contains a `{"type": "image", "source": {"type": "base64", ...}}` content item. Assert `tier=="standard"` (cfg default). Assert the response is the mock's canned text. |
| 2 | `test_text_plain_attachment_appends_block_and_decomposes` | Send a chat turn with one `text/plain` `attachment_id`. Assert `runtime.process_natural_language` was called with an augmented prompt containing `<ATTACHMENT name="..." mime="text/plain">...</ATTACHMENT>` and the original user text. Assert `MockLLMClient.complete` was NOT called for vision. |
| 3 | `test_text_markdown_attachment_appends_block` | Same as #2 with `text/markdown`. |
| 4 | `test_json_attachment_appends_pretty_block` | Send a chat turn with one `application/json` attachment. Assert the augmented prompt's `<ATTACHMENT>` block contains pretty-printed JSON (indent=2). |
| 5 | `test_csv_attachment_appends_block` | Same for `text/csv`. |
| 6 | `test_oversize_text_truncated` | Send a `text/plain` attachment whose UTF-8 size exceeds `text_extraction_max_bytes`. Assert the augmented prompt's `<ATTACHMENT>` block ends with `[TRUNCATED]`. |
| 7 | `test_vision_tier_unhealthy_returns_text_only_stub` | Mock `get_health_status()` to return `{"tiers": {"standard": {"status": "unreachable"}}}`. Send a PNG attachment. Assert response is the structured stub naming the attachment. Assert `MockLLMClient.complete` was NOT called. Assert a `WARNING`-level log entry mentions `AD-720d vision tier=standard unavailable`. |
| 8 | `test_pdf_attachment_with_extraction_disabled_emits_stub` | Send a PDF attachment with `pdf_extraction_enabled=False`. Assert the augmented prompt's `<ATTACHMENT>` block contains `note="PDF extraction not yet wired (AD-720a-1)"`. Assert no `NotImplementedError` propagates. |
| 9 | `test_zero_attachment_chat_unchanged_regression` | Send a chat turn with empty `attachment_ids`. Assert the new branch is NOT entered (verify by asserting `runtime.process_natural_language` is called with the un-augmented `req.message`). **Zero-attachment regression guard.** |
| 10 | `test_attachments_disabled_skips_branch` | `cfg.enabled = False` with non-empty `attachment_ids`. Assert the new branch is skipped and the standard decomposer path runs. |

> **Test gate command (single file):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad720d_vision_pipethrough.py -v -n 0 --timeout=60`. **Wave gate:** `pytest tests/ -q -n 4 --dist=loadfile` is green at BOTH commits. **The existing `tests/test_ad720_*.py` and `tests/test_ad720a_*.py` files MUST stay green without modification.**

## 7. Cross-AD integration

| Touchpoint | AD-720d (this AD) | AD-720a (commit N — at HEAD when this builds) |
|---|---|---|
| `AttachmentsConfig` | Reads `vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`. | Adds the three fields. |
| `_MIME_TO_EXT` reverse lookup | Calls `mime_for_attachment_id` helper. | DRY-ifies the GET endpoint's reverse lookup against the same module-level dict. |
| `LLMRequest` | Adds optional `messages: list[dict] | None = None`. | No change to `LLMRequest`. |
| `OpenAICompatibleClient` | One-line conditional in request-build. | No change to LLM client. |
| Chat handler | New conditional branch (image → vision tier; non-image → augmented prompt). | New multipart endpoint sibling; JSON path refactored to call shared helper. |
| `IntentSurface.tsx` | No change. | Drag-drop overlay + file picker + extended preview strip. |
| Episodic writes | No change in episodic shape. The augmented prompt flows through the existing `runtime.process_natural_language` codepath; episodic continues to record `req.message` (now augmented) and `attachment_ids`. The image-routed path bypasses the decomposer and therefore does NOT write an episode in v1 — **forward marker AD-720d-3 (file at gate-3) tracks adding episodic writes for vision-routed turns**. | No change in episodic shape. |
| **Build order** | **AD-720d ships SECOND as commit N+1.** | **AD-720a ships FIRST as commit N.** Builder MUST NOT interleave commits or squash. |

## 8. Hard-stop conditions for the Builder

Standard hard-stops from `BUILDER-EXECUTION-PLAN.md` apply, **plus**:

1. **AD-720a not at HEAD before AD-720d builds.** Hard stop. Pre-flight: `git log --oneline -5` shows AD-720a's commit immediately before this one. If the AD-720a commit is missing, AD-720d's `config.py` SEARCH/REPLACE assumptions are wrong — STOP.
2. **`request.messages is None` codepath altered.** Hard stop. The existing `prompt`-shape codepath MUST stay bit-for-bit unchanged. Existing LLM tests are the regression guard.
3. **`runtime.llm_client.complete` called without prior `get_health_status()` check on the vision-routed path.** Hard stop (silent-drop regression).
4. **PDF parsing code path that depends on `pypdf` / `PyPDF2` ships in this AD.** Hard stop. AD-720a-1 is the right place. v1 emits the deferred-feature stub.
5. **`errors='replace'` on UTF-8 decode in the extractor.** Hard stop. Strict only (the `errors='ignore'` re-decode after byte-boundary truncation is the ONLY allowed ignore).
6. **`subprocess.run` introduced in `vision_dispatch.py` or `text_extractor.py`.** Hard stop. Async stdlib only.
7. **`exec` / `eval` / `compile` on attachment metadata or extracted text.** Hard stop.
8. **Anthropic / OpenAI vendor SDK imported.** Hard stop. The existing `httpx`-based client posts the multimodal `messages` JSON.
9. **`pyproject.toml [project.dependencies]` modified.** Hard stop.
10. **Existing AD-720 paste tests modified.** Hard stop.
11. **Existing AD-720a multipart tests modified.** Hard stop.
12. **`cd ui && npm run build` not run before push, OR fails when run.** **HARD STOP — Wave 137's broken TypeScript build was the most expensive miss this week.** Even though AD-720d ships zero UI changes, the build gate MUST be run AFTER writing code and BEFORE pushing — a transitive `pyproject.toml` import / type-export shift could break the bundle.
13. **Image bytes routed to a non-vision-capable tier without checking `vision_tier` is operational first.** Hard stop. The `cfg.attachments.vision_tier` field is the canonical knob; never hardcode `"standard"`.
14. **Working-tree integrity.** Pre-flight `git diff --numstat | sort -k2nr | head -5` + scan for tracked-file deletions > 200 lines that the Builder did not author. STOP and surface to Captain.
15. **Architectural change required** (modify `BaseAgent`/`IntentMessage`/`ChatRequest` core protocols beyond the additive `LLMRequest.messages` field). Hard stop.

## 9. Engineering principles compliance

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

Specifically (Builder confirms each in the build report):
- **DRY:** `mime_for_attachment_id` is the single source of truth for content-hash → MIME. The GET endpoint and `vision_dispatch` both call it. `_MIME_TO_EXT` is the single source of truth for MIME ↔ extension (after AD-720a's DRY-ification).
- **Defense in depth:** the vision branch only fires when `req.attachment_ids` is non-empty AND `cfg.enabled is True`. The vision-tier health check fires before any LLM call. Validators on the attachment bytes already ran at upload time (AD-720 / AD-720a); the dispatch reads stored bytes only.
- **Cloud-Ready Storage:** `vision_dispatch` consumes the `AttachmentStore` Protocol. Commercial overlay can swap to S3 / Azure Blob without changing `vision_dispatch.py`.
- **Async discipline:** all `store.read` and `complete` calls are `await`-ed. `asyncio.gather` for parallel attachment reads is acceptable. No fire-and-forget. No `asyncio.ensure_future`.
- **Three-tier exception handling:**
  - **Propagate (security):** path traversal during `store.read` (already raised by the store; passes through).
  - **Log-and-degrade (Tier-2):** vision-tier unhealthy → structured stub message + WARN log. Single attachment `FileNotFoundError` → `<ATTACHMENT note="failed_to_load" />` block + WARN log + other attachments still render.
  - **Swallow:** none. Every failure path produces a structured user-visible signal.
- **Configuration via Pydantic:** all knobs (`vision_tier`, `text_extraction_max_bytes`, `pdf_extraction_enabled`) come from `AttachmentsConfig` (added in AD-720a). Hardcoded `"standard"` or `1*1024*1024` literals in `chat.py` / `vision_dispatch.py` are review blockers.
- **No private-attr access:** `vision_dispatch` consumes only public names from `LLMClient`, `AttachmentStore`, `AttachmentsConfig`. The chat-router bridge `_mime_for` callable is the only place that touches `store._root` (and only because the helper signature requires it; if AD-720a exposes a one-arg `mime_for_attachment_id(content_hash)` instead, drop the bridge).
- **Logging quality:** every degrade path logs with full context (tier, status, attachment_ids, count).
- **Type annotations:** every new public function (`build_multimodal_messages`, `extract_text`, `mime_for_attachment_id`) is fully typed.
- **No new top-level deps:** `pyproject.toml` is bit-for-bit unchanged.

## 10. Acceptance criteria

- All ≥ 8 Python tests pass.
- `pytest tests/ -q -n 4 --dist=loadfile` is green at this commit.
- `cd ui && npx vitest run` is green at this commit (no UI changes; just verifies AD-720a's tests still pass).
- **`cd ui && npm run build` is green at this commit.** (HARD RULE — Wave 137's broken TypeScript build was the most expensive miss this week.)
- Existing `tests/test_ad720_*.py`, `tests/test_ad720a_*.py`, and the existing LLM client tests stay green **without modification**.
- `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-720d-vision-pipe-through-v1.md` reports zero true phantoms (the new symbols introduced by this prompt — `build_multimodal_messages`, `extract_text`, `mime_for_attachment_id`, `LLMRequest.messages`, `vision_dispatch`, `text_extractor` — are expected false positives; note in build report).
- `git diff <pre>..<post> -- pyproject.toml` shows zero changes.
- GH issue [#552](https://github.com/seangalliher/ProbOS/issues/552) closed in the merge commit.
- AD-720a's commit is the **immediately-prior** commit in `git log` — verify pre-flight.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

**Files touched (target list):**
- **New:** `src/probos/cognitive/vision_dispatch.py`, `src/probos/cognitive/text_extractor.py`, `tests/test_ad720d_vision_pipethrough.py`.
- **Modified:** `src/probos/types.py` (additive `messages` field on `LLMRequest`), `src/probos/cognitive/llm_client.py` (one-line conditional in request-build), `src/probos/attachments/filesystem_store.py` (append `mime_for_attachment_id` helper), `src/probos/routers/chat.py` (new conditional branch in main `chat` handler).
- **Untouched (hard stop if modified):** `src/probos/config.py` (AD-720a already extended; AD-720d does not touch), `src/probos/api_models.py`, `src/probos/attachments/store.py`, `src/probos/attachments/mime.py`, `ui/src/**` (zero UI changes in AD-720d), `pyproject.toml`.

## 11. Forward markers (file at gate-3 per `BUILDER-EXECUTION-PLAN.md` Post-Sweep step 6)

| Marker | Scope |
|---|---|
| **AD-720a-1** | PDF / DOCX / XLSX text extraction. Adds `pypdf`, `python-docx`, `openpyxl`. Flips `pdf_extraction_enabled` default to `True` in a follow-up grandchild AD (default-True on a transitional flag is breaking-change anti-pattern; use AD-720a-1-1 for the default flip). |
| **AD-720d-1** | Multi-image batch send: latency, prompt-context budget, degradation behaviour, per-attachment timing in episodic. |
| **AD-720d-2** | Per-agent vision capability designation. Captain may want Counselor to "see" but Engineering to text-only. Adds an agent-level capability flag to the routing decision. |
| **AD-720d-3** | Episodic writes for vision-routed turns. v1 of AD-720d bypasses the decomposer for image-only turns and therefore does not write an episode; AD-720d-3 closes that gap with a vision-specific episode source tag. |
| **AD-720b** | Tool-attach (BrowserTool from AD-706, MCP tools from AD-449). |
| **AD-720c** | Cloud file picker (OneDrive / GDrive). Public marker is technical-only; commercial scope private. |
| **AD-720e** | Audio attachments — voice/transcription pipeline. |

## 12. AD-numbering

Highest pre-existing AD at HEAD: **AD-721i** (per `PROGRESS.md` L11, confirmed 2026-05-10). Wave 138 added no new AD numbers (single-prompt wave AD-721b).

This wave allocates: **AD-720a** (commit N, sibling prompt) and **AD-720d** (this prompt, commit N+1). Both numbers were reserved as forward markers in the AD-720 archive (commit Wave 135). No collisions.

Drafter re-greps `DECISIONS.md` and `decisions-era-*.md` for any `AD-720d` body labels before the Builder dispatches — none present at HEAD 2026-05-10.

## 13. Build order note

**Hard order: AD-720a is commit N, AD-720d is commit N+1.**

`pytest tests/ -q -n 4 --dist=loadfile` MUST be green at BOTH commits. AD-720d's `tests/test_ad720d_vision_pipethrough.py` test file imports `runtime.config.attachments.vision_tier` / `.text_extraction_max_bytes` / `.pdf_extraction_enabled` — fields that only exist in `AttachmentsConfig` after AD-720a's extension lands. If commits are reordered, AD-720d test file fails to construct the runtime config.
