# AD-720d-1 — Multi-Image Batch Send (Latency + Episodic Per-Attachment Timing)

**AD:** AD-720d-1 (forward marker filed by AD-720d Wave 139).
**GH issues closed:** [#563](https://github.com/seangalliher/ProbOS/issues/563).
**Parent ADs:** AD-720d (vision pipe-through, Wave 139), AD-720d-3 (vision episodic write, Wave 154 commit `21ad0834`), AD-731 (content-addressable refs, Wave 152), BF-277 (list-shape system message for Ollama, 2026-05-12).
**Wave:** 154. **Estimated tests:** +5. **Estimated wall-time:** ~1h.

---

## Solution Overview

The wire shape already supports multi-image batches: `build_multimodal_messages` (`src/probos/cognitive/vision_dispatch.py:152`) builds a single user message with N image content blocks from N `attachment_ids`. The vision pipeline (BF-268..BF-277) accepts list-shape content end-to-end. **No production code change is required to make multi-image work** — what is missing is:

1. **Per-attachment timing in the episodic outcome** so dreaming/recall can correlate latency with image count and per-image resolve cost. Today the episode records `image_count` (`routers/chat.py:391`, `routers/agents.py` mirror) but a single `duration_ms`.
2. **Degradation behavior under partial-resolve.** `_resolve_one` (`vision_dispatch.py:127`) emits a `failed_to_load` text block when a single attachment can't be fetched from the store. Today the message still ships but no metric records the partial. Add a `failed_image_count` outcome field.
3. **Test coverage for the multi-image case** — `test_ad720d_*` and `test_ad731_*` files cover single-image wire shape; nothing exercises N=3+.
4. **A soft warning when image count exceeds a configurable budget** (default 5). Default-off semantics: log-only, never block.

All four are additive and Tier-2 log-and-degrade.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/cognitive/vision_dispatch.py` | 152–270 (`build_multimodal_messages`) + 294 (internal caller in `augment_prompt_with_attachment_text`) | Return per-attachment `(attachment_id, mime, resolve_ms, ok: bool)` records alongside `(messages, image_ids)`. Update the internal destructure to discard the new third element. |
| `src/probos/routers/chat.py` | 300 (destructure) + 280–410 (vision branch episode write) | Accept new 3-tuple; record `per_attachment_timing` + `failed_image_count` in episode outcomes. |
| `src/probos/routers/agents.py` | 914 (destructure inside DM vision branch in `agent_chat`) + 1228–1252 (DM episode `outcomes` block) | Accept new 3-tuple; same enrichment for per-agent DM episodes. **Skip lines 1106–1145 — owned by AD-724.** |
| `src/probos/config.py` | 1112–1142 (`AttachmentsConfig`, plural) | New field `multi_image_warn_threshold: int = 5`. Place near `pdf_extraction_enabled`. |
| `tests/test_ad720d_1_multi_image.py` | NEW | 5 boundary tests. |

`build_multimodal_messages` callers must accept the new return tuple shape. **Live grep confirms three production destructure sites** (all of which must be updated in this commit):

- `src/probos/routers/chat.py:300` (Captain chat vision branch)
- `src/probos/routers/agents.py:914` (per-agent DM vision branch in `agent_chat`)
- `src/probos/cognitive/vision_dispatch.py:294` (internal in `augment_prompt_with_attachment_text` — discards the new element)

The AD-734 wire-shape contract test asserts the bus message shape, NOT the function's return arity, so signature drift across these three callers is bounded only by reviewer/Builder vigilance — the destructure update must land in the same commit.

---

## Section 1 — Per-attachment timing in `build_multimodal_messages`

In `src/probos/cognitive/vision_dispatch.py`, change the return signature from
`tuple[list[dict[str, Any]], list[str]]` to
`tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]`
where the third element is a list of `{"attachment_id": str, "mime": str | None, "resolve_ms": float, "ok": bool}` records, ordered to match `attachment_ids`.

Wrap the existing `_resolve_one` calls in `time.monotonic()` boundaries and collect the records:

```python
import time  # already imported at module top

# Replace the asyncio.gather / for loop with timing-aware version:
per_attachment: list[dict[str, Any]] = []
resolved_pairs: list[tuple[str, tuple[str | None, bytes | None, dict[str, Any] | None]]] = []

async def _timed_resolve(aid: str) -> tuple[str, tuple, float]:
    t0 = time.monotonic()
    out = await _resolve_one(
        aid, store, mime_lookup,
        text_extraction_max_bytes, pdf_extraction_enabled,
    )
    return aid, out, (time.monotonic() - t0) * 1000.0

results = await asyncio.gather(*(_timed_resolve(aid) for aid in attachment_ids))

for attachment_id, (mime, blob, failure_item), resolve_ms in results:
    ok = failure_item is None
    per_attachment.append({
        "attachment_id": attachment_id,
        "mime": mime,
        "resolve_ms": round(resolve_ms, 2),
        "ok": ok,
    })
    # ... existing append-to-content logic ...
```

**Preserve the entire body of the existing `for attachment_id, (mime, blob, failure_item) in zip(attachment_ids, resolved):` loop verbatim** (~95 lines spanning vision_dispatch.py:175–269: AD-731 ref-shape emission with the BF-278 restoration note, PDF stub, text extraction with three error tiers). Only the loop header changes (the unpack now also yields `resolve_ms`, computed in the gather step) and the `per_attachment.append({...})` line is added at the top of the loop body. Do NOT summarize or paraphrase the existing body — the BF-278 ref-shape protection and the multi-tier failure handling must survive intact.

Return the new 3-tuple:

```python
return (messages, image_ids, per_attachment)
```

Update `augment_prompt_with_attachment_text` (also in `vision_dispatch.py:273`) to destructure the third element and discard it:

```python
messages, image_ids, _per = await build_multimodal_messages(...)
```

(Anchor SEARCH on the existing line `messages, image_ids = await build_multimodal_messages(` at `vision_dispatch.py:294`.)

---

## Section 2 — Update DM + chat callers

In `src/probos/routers/chat.py:300`:

```python
messages, image_ids, per_attachment = await build_multimodal_messages(...)
```

Then in the episode `outcomes` block (around line 388–393):

```python
outcomes=[{
    "intent": "captain_chat_vision",
    "success": True,
    "response": (llm_response.content or "")[:500],
    "has_image_attachment": True,
    "image_count": len(image_ids),
    "failed_image_count": sum(1 for r in per_attachment if not r["ok"]),
    "per_attachment_timing": per_attachment,
    "attachment_ids": list(req.attachment_ids),
    "llm_tier": tier,
    "llm_model": getattr(llm_response, "model", ""),
}],
```

In `src/probos/routers/agents.py` at **line 914** (the `messages, image_ids = await build_multimodal_messages(...)` call inside `agent_chat`'s DM vision branch), update the destructure:

```python
messages, image_ids, per_attachment = await build_multimodal_messages(
    ...
)
```

Then, in the **DM episode `outcomes` block at lines 1228–1252** (where `"has_image_attachment": has_image_attachment` is currently the only image-aware field), add the same enrichment fields. Note: `per_attachment` is computed inside the `if req.attachment_ids:` block at ~890–920; ensure it is in scope when the episode is built (initialize `per_attachment: list[dict[str, Any]] = []` alongside `vision_messages: list[dict[str, object]] | None = None` at line 894 so the episode block sees an empty list when there are no attachments):

```python
outcomes=[{
    "intent": "direct_message",
    "success": True,
    "response": response_text[:500],
    "session_type": "1:1",
    "callsign": callsign,
    "source": "hxi_profile",
    "agent_type": agent.agent_type,
    "has_image_attachment": has_image_attachment,
    # AD-720d-1: per-attachment timing + partial-resolve metric.
    "image_count": len(image_ids) if has_image_attachment else 0,
    "failed_image_count": sum(1 for r in per_attachment if not r["ok"]),
    "per_attachment_timing": per_attachment,
}],
```

**Do NOT touch lines 1106–1145** — that region is the AD-724 DM sanity-gate / retry block, owned by the AD-724 prompt in this same wave.

---

## Section 3 — Soft budget warning

In `src/probos/config.py`, add to `AttachmentsConfig` (around line 1130, after `pdf_extraction_enabled`):

```python
multi_image_warn_threshold: int = 5  # AD-720d-1: log-only soft warning
```

In `routers/chat.py` and `routers/agents.py`, after `image_ids` is computed and before the LLM call:

```python
if cfg_attach.multi_image_warn_threshold and len(image_ids) > cfg_attach.multi_image_warn_threshold:
    logger.warning(
        "AD-720d-1: vision turn includes %d images (threshold=%d); "
        "this may exceed the LLM's effective context budget — proceeding "
        "without truncation. attachment_ids=%s",
        len(image_ids),
        cfg_attach.multi_image_warn_threshold,
        list(req.attachment_ids),
    )
```

Default-on (warn at >5). To disable, set the threshold to `0` in `config/system.yaml`.

---

## What This Does NOT Change

- The wire shape (AD-731 ref-form). Per-image content blocks remain `{"type": "image", "source": {"type": "attachment_ref", ...}}`.
- The honest-degrade path (AD-732). Vision unconfigured / unhealthy still short-circuits before any image resolution.
- Cache, rate-limiter, ModelRouter — all unchanged.
- No new HTTP request shape on the LLM side. Ollama / OpenAI / Anthropic adapters unchanged.
- No UI changes. The picker already supports multi-select.
- No truncation policy. If the operator sends 100 images, we warn but still try.

---

## Test Plan (`tests/test_ad720d_1_multi_image.py`)

Pure-function tests for `build_multimodal_messages` + a single integration test that walks `routers/chat.py` with mocked store + LLM client. Use `_FakeAttachmentStore` pattern from existing AD-731 tests (grep `tests/test_ad731_*.py` for the fixture).

1. **`test_multi_image_three_attachments_returns_three_image_blocks`** — happy path: 3 image attachments → `len(image_ids) == 3`, content array has 3 image blocks + 1 text prompt.
2. **`test_per_attachment_timing_records_one_per_input`** — `len(per_attachment) == len(attachment_ids)`, each record has `resolve_ms >= 0` and matching `attachment_id`.
3. **`test_partial_resolve_one_failure_others_succeed`** — edge: 3 attachments, middle one missing from store → `image_ids` excludes failed one, `per_attachment[1]["ok"] is False`, content array still has 2 image blocks + 1 failure note.
4. **`test_zero_attachments_returns_empty_per_attachment`** — empty/None: `attachment_ids=[]` → `per_attachment == []`, `image_ids == []`, content has 1 text block.
5. **`test_warn_threshold_logs_when_exceeded`** — integration: build a DM vision request with 6 images and `multi_image_warn_threshold=5` → assert the warning was emitted (caplog).

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad720d_1_multi_image.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad731_content_addressable_vision.py tests/test_ad734_wire_shape_contract.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracker Updates

- **PROGRESS.md**: bump test count; bullet under Wave 154.
- **DECISIONS.md**: append `### AD-720d-1` (one paragraph).
- **docs/development/roadmap.md**: mark #563 closed.

---

## Verified Against Codebase (2026-05-12)

```
grep -n "async def build_multimodal_messages" src/probos/cognitive/vision_dispatch.py
  152: async def build_multimodal_messages(
grep -rn "await build_multimodal_messages" src/probos
  src/probos/routers/chat.py:300            messages, image_ids = await build_multimodal_messages(
  src/probos/routers/agents.py:914          messages, image_ids = await build_multimodal_messages(
  src/probos/cognitive/vision_dispatch.py:294   messages, image_ids = await build_multimodal_messages(
  (THREE production destructure sites — all must be updated in this commit;
   tests in test_ad731_*.py and test_ad734_*.py also destructure but are
   updated in the same commit by adjusting test expectations.)
grep -n "image_count" src/probos/routers/chat.py
  391:                                "image_count": len(image_ids),
grep -n "has_image_attachment" src/probos/routers/agents.py
  895:    has_image_attachment = False
  1019:                    has_image_attachment = True
  1053:        _params["has_image_attachment"] = True
  1240:                    "has_image_attachment": has_image_attachment,
  (Episode outcomes block at 1228–1252; per_attachment must be in scope.)
grep -n "per_attachment" src/probos
  (no hits — new field)
grep -n "class AttachmentsConfig" src/probos/config.py
  1112: class AttachmentsConfig(BaseModel):
  (NOTE: class name is plural "AttachmentsConfig" — NOT "AttachmentConfig".)
grep -n "pdf_extraction_enabled" src/probos/config.py
  ~1130 (placement anchor for new multi_image_warn_threshold field)
grep -n "AD-720d-3: episodic write" src/probos/routers/chat.py
  ~378-410: present (vision episode block)
```

---

## Revision (2026-05-12)

Applied pass-1 review findings:

**Required (2 addressed):**

1. **Phantom config class name `AttachmentConfig` → `AttachmentsConfig`.** Replaced all four occurrences (Files-to-Modify table, Section 3 prose + grep instruction, verification footer). Pinned line ~1130 "after `pdf_extraction_enabled`" so the Builder has an unambiguous insertion anchor.

2. **Third caller of `build_multimodal_messages` missed.** Section 2 now explicitly enumerates all three production destructure sites (`routers/chat.py:300`, `routers/agents.py:914`, `cognitive/vision_dispatch.py:294`) and instructs the Builder to update agents.py:914 with the new 3-tuple destructure. The verification footer's grep block now lists all three. Section 2's agents.py episodic write site is pinned to lines 1228–1252 (live grep verified the existing `has_image_attachment` outcome dict at line 1240) and explicitly excludes lines 1106–1145 (the AD-724 sanity-gate region) to prevent cross-prompt collision.

**Recommended folded:**

- **#1 (Section 1 hand-waves the loop body)** — added an explicit "preserve the entire body of the existing loop verbatim" instruction with a forward-pointer to the BF-278 ref-shape protection and the AD-731 ref-shape emission span (vision_dispatch.py:181–203).
- **#3 (`_time` import alias unnecessary)** — dropped the alias; live grep confirms `time` is already imported at module top of `vision_dispatch.py`.
- **#5 (pin agents.py episodic write line range)** — done in Section 2; line 1228–1252 cited explicitly with the AD-724 region carve-out.
- **#6 (cross-prompt collision risk with AD-724)** — explicit "Do NOT touch lines 1106–1145" instruction added in Section 2.

**Recommended deferred (scope/test-surface):**

- **#2 (signature-drift `inspect.signature` test)** — valid hardening but adds a 6th test outside the dispatch's `+5` test budget. The three explicit destructure-site updates plus the AD-734 wire-shape test combined provide adequate coverage for v1; can add the contract test as a follow-up if drift recurs.
- **#4 (cap soft-warning log on `req.attachment_ids` length)** — valid log-hygiene fix but the warn threshold is 5 by default; the warning fires only when count > 5, and an operator sending 100+ images will see one capped log line per turn at most. Acceptable for v1.

**Nits not addressed:** all four Nits are documentation-style or future-test enhancements; no source/spec change needed.

