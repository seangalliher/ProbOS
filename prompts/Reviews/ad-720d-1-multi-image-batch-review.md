# Review: AD-720d-1 — Multi-Image Batch Send (Latency + Episodic Per-Attachment Timing)
**Verdict:** ⚠️ Conditional
**Two Required spec defects: phantom config class name + missed third caller of `build_multimodal_messages`. Both will fail at first vision DM after the commit.**

## Required (must fix before building)

1. **Phantom config class name `AttachmentConfig`.** Files-to-Modify table and Section 3 both say "`AttachmentConfig` (search `class AttachmentConfig`)". Live grep confirms no such class exists. The actual class is `class AttachmentsConfig(BaseModel):` (plural) at [src/probos/config.py:1112](src/probos/config.py#L1112). The verification footer admits the gap: "(caller: verify line; field is additive — placement near other vision config)". A Builder following the prompt's grep instruction literally will hit zero results. **Fix:** replace `AttachmentConfig` with `AttachmentsConfig` in the Files-to-Modify table, in Section 3's prose, and pin the line ("around line 1130, after `pdf_extraction_enabled`").

2. **Third caller of `build_multimodal_messages` missed.** Live grep returns 3 destructure sites for `messages, image_ids = await build_multimodal_messages`:
   - `src/probos/routers/chat.py:300`
   - `src/probos/routers/agents.py:914` (the DM vision branch)
   - `src/probos/cognitive/vision_dispatch.py:294` (inside `augment_prompt_with_attachment_text`)
   The prompt's verification footer cites only chat.py:300 and vision_dispatch.py:294 — **agents.py:914 is missing**. The dispatch text and the prompt body are also internally inconsistent ("Today there are exactly two call sites: routers/chat.py:300 and routers/agents.py..." then immediately mentions vision_dispatch.py:294 as a third). After the function's return arity changes from 2-tuple to 3-tuple, agents.py:914 raises `ValueError: too many values to unpack (expected 2)` on the first DM with an image attachment. **Fix:** Section 2 must explicitly include agents.py:914 as a destructure site (`messages, image_ids, per_attachment = await build_multimodal_messages(...)`) and the verification footer must list all 3 callers.

## Recommended (should fix)

1. **Section 1 hand-waves the loop body.** Example REPLACE shows `# ... existing append-to-content logic ...`. The real loop body in [vision_dispatch.py:175-269](src/probos/cognitive/vision_dispatch.py#L175-L269) is ~95 lines (image AD-731 ref shape including the BF-278 restoration note, PDF stub, text extraction with three error tiers). The Builder must preserve all of it inside the new `for ... in results:` loop. State explicitly: "The entire body of the existing `for attachment_id, (mime, blob, failure_item) in zip(attachment_ids, resolved):` loop is preserved verbatim — only the loop header changes (to add `resolve_ms` and `ok` to the unpack) and the `per_attachment.append({...})` line is added at the top of the loop body." Otherwise a Builder summarizing the body would silently regress the BF-278 ref-shape protection.

2. **Signature-drift gap acknowledged but not closed.** Dispatch claim: "AD-734 hook will catch any wire-shape regression but not signature drift." That is correct — AD-734's contract test asserts the bus message shape (refs not blobs), not the function's return arity. Once Required #2 is fixed (all 3 callers updated in the same commit), the risk is bounded by the test count gate. To close the gap programmatically, add a focused test that imports both `routers.chat.captain_chat` and `routers.agents.agent_chat` vision branches with a mocked `build_multimodal_messages` returning a 3-tuple, and asserts neither raises. Alternatively a one-line `inspect.signature` assertion in the new test file.

3. **`_time` import alias is unnecessary.** Section 1 suggests `import time as _time` "if not already imported as time". Live read confirms `vision_dispatch.py` does NOT import `time`. Just `import time` at module top — no `_time` alias needed.

4. **Soft warning logs full `req.attachment_ids`.** When count exceeds 5 the warning includes `attachment_ids=list(req.attachment_ids)`. With 100+ attachments this produces an unbounded log line. Cap at first N (e.g., `list(req.attachment_ids)[:10]` + "...") for log hygiene.

5. **Section 2 punts on `routers/agents.py` episodic write existence.** "Apply the same destructure + outcome enrichment if there is an episodic write site (verify there is — AD-720d-3 added one). If there isn't an episodic write on the per-agent DM side yet, mirror the chat.py pattern." The prompt should resolve this ambiguity itself — grep for `AD-720d-3` in `routers/agents.py`, find the episode block, pin the line range, and instruct the Builder explicitly. Leaving "mirror the chat.py pattern" to the Builder's judgement is what produced the BF-273 / BF-274 ambiguity in the wave-153 vision arc.

6. **Cross-prompt collision risk with AD-724.** Both prompts modify `routers/agents.py:~1100-1220`. AD-724 inserts a retry block after the sanity-gate call (lines 1106-1110). AD-720d-1 Section 2 says "DM vision branch (around line ~1100-1220)" but the actual vision-branch destructure is at line 914 (well above) and the episodic write site is unspecified. Tighten AD-720d-1's agents.py instructions to: (a) destructure at line 914, (b) episodic write at the line range that AD-720d-3 introduced (the prompt must verify and cite it), (c) explicitly skip lines 1106-1145 (the AD-724 sanity-gate / retry region). Otherwise the dispatch's "no two prompts touch the same lines" claim is unverified.

## Nits (style/minor)

1. `_FakeAttachmentStore` reference: "grep `tests/test_ad731_*.py` for the fixture" — cite the exact file path so the Builder doesn't have to disambiguate (likely `tests/test_ad731_content_addressable_vision.py`).
2. `per_attachment_timing` outcomes-blob shape uses dicts. A typed `dataclass` (or `TypedDict`) would be more discoverable for downstream dreaming/recall queries. Acceptable for v1 since outcomes are written to ChromaDB as JSON anyway.
3. Test #5 (`test_warn_threshold_logs_when_exceeded`) is described as "integration: build a DM vision request with 6 images" — clarify whether this exercises chat.py, agents.py, or both. Pure-router caplog tests are easier to keep deterministic.
4. The test plan does NOT cover: (a) the new `failed_image_count` outcome field for partial-resolve case, (b) the warn-threshold disabled (`= 0`) case. Both are 2-3 line additions and both are listed in the Verification commands path.

## Verified (looks good)

- `async def build_multimodal_messages(` at [vision_dispatch.py:152](src/probos/cognitive/vision_dispatch.py#L152) — confirmed.
- Current return signature `tuple[list[dict[str, Any]], list[str]]` at line 161 — confirmed; arity change is well-defined.
- `_resolve_one` returning `(mime, blob, failure_item)` at [vision_dispatch.py:96-145](src/probos/cognitive/vision_dispatch.py#L96-L145) — confirmed; the existing zip unpack is `for attachment_id, (mime, blob, failure_item) in zip(...)` at line 175.
- AD-731 ref-shape emission with BF-278 restoration note at [vision_dispatch.py:181-203](src/probos/cognitive/vision_dispatch.py#L181-L203) — confirmed intact (the prompt's "What This Does NOT Change" section correctly preserves this invariant).
- `cfg_attach = getattr(runtime.config, "attachments", None)` at [chat.py:289](src/probos/routers/chat.py#L289) and [agents.py:897](src/probos/routers/agents.py#L897) — variable name verified.
- AD-734 wire-shape contract test exists at `tests/test_ad734_wire_shape_contract.py` — confirmed; pre-commit hook will fire on this commit per the dispatch.
- `image_count` outcome field at [chat.py:391](src/probos/routers/chat.py#L391) — confirmed; per_attachment_timing addition is additive.
- AttachmentStore SHA-256 ref invariant (AD-731) preserved — verified the prompt does not introduce inline blobs into IntentMessage.params.
- Phase ordering: no new finalize-phase services; reads only existing `runtime.config.attachments` (constructor-time).

---

### Re-review (pass-2)
**Verdict:** ✅ Approved
**Both pass-1 Required findings genuinely resolved; no new Required introduced.**

#### Pass-1 Required disposition

1. **Phantom config class name `AttachmentConfig` → `AttachmentsConfig` (pass-1 Required #1) — RESOLVED.** Live grep confirms only `class AttachmentsConfig(BaseModel):` exists at [src/probos/config.py:1112](src/probos/config.py#L1112) (plural). Revised prompt replaces the name in all four occurrences (Files-to-Modify table, Section 3 prose, Section 3 grep instruction, verification footer). Builder following the prompt's grep instruction will hit the correct class.

2. **Third caller of `build_multimodal_messages` missed (pass-1 Required #2) — RESOLVED.** Live grep confirms exactly three production destructure sites: [chat.py:300](src/probos/routers/chat.py#L300), [agents.py:914](src/probos/routers/agents.py#L914), [vision_dispatch.py:294](src/probos/cognitive/vision_dispatch.py#L294). Revised Section 2 now explicitly enumerates all three with destructure code; revised verification footer's grep block lists all three. Section 1's instruction for `augment_prompt_with_attachment_text` to `_per`-discard the new third element handles the internal caller. After landing, no caller will raise `ValueError: too many values to unpack`.

   Cross-prompt collision risk also closed: Section 2 explicitly says "**Skip lines 1106–1145 — owned by AD-724.**" Episodic write site pinned to lines 1228–1252; live grep confirms `has_image_attachment` at [agents.py:1240](src/probos/routers/agents.py#L1240) inside the episode `outcomes` block.

#### Folded Recommendeds

- **#1 (Section 1 hand-waves the loop body)**: Section 1 now states "Preserve the entire body of the existing `for ...` loop verbatim (~95 lines spanning vision_dispatch.py:175–269)" with a forward-pointer to the BF-278 ref-shape protection. Verified — vision_dispatch.py:175-269 reads as the prompt describes. Ref-shape emission with BF-278 note at lines 184-203 confirmed intact in HEAD.
- **#3 (`_time` import alias)**: Dropped. Section 1 now says "import time  # already imported at module top." Verified — `vision_dispatch.py` imports `time` (also `asyncio`, etc.) at module top.
- **#5 (pin agents.py episodic write line range)**: Done. Section 2 cites lines 1228-1252 explicitly; pinning matches HEAD.
- **#6 (cross-prompt collision)**: Done. Explicit "Do NOT touch lines 1106–1145" in Section 2 + "**Skip lines 1106–1145 — owned by AD-724.**" in Files-to-Modify table.

Deferrals (#2 `inspect.signature` contract test, #4 cap log on `req.attachment_ids`) carry written rationale; acceptable per Convention #15 deferral standard.

`per_attachment` scope concern is well-addressed: prompt instructs Builder to "initialize `per_attachment: list[dict[str, Any]] = []` alongside `vision_messages: list[dict[str, object]] | None = None` at line 894." Verified — `vision_messages` initialized at HEAD line 894 outside the `if req.attachment_ids:` block, so `per_attachment` initialized in the same scope will be visible to the episode write at line 1228+.

#### New Required findings — NONE

#### New Recommendeds — NONE

#### Nits

1. Section 3 says "around line 1130, after `pdf_extraction_enabled`." Live HEAD has `pdf_extraction_enabled: bool = False` at line 1144 (14-line drift from "1130"). Within "around line N" tolerance per review-criteria #6; the textual anchor ("after `pdf_extraction_enabled`") is unambiguous. No Builder impact.

#### Verified Improvements

- Phantom class name fully scrubbed; verification footer cites `class AttachmentsConfig` (plural) explicitly.
- All 3 destructure sites enumerated in both Section 2 prose and the verification footer.
- Loop-body verbatim-preservation instruction prevents BF-278 ref-shape regression risk.
- Cross-prompt collision with AD-724 explicitly carved out — both prompts can safely land in either order on `routers/agents.py`.
- `per_attachment` scope clearly handled at line 894 init point.
- `_time` alias cleanup matches live HEAD imports.
- AD-734 wire-shape contract test acknowledged as not-catching signature drift; the in-commit triple-caller update closes that gap.
- No new layer violations; no new untested code paths beyond the +5 test plan; no new phantom APIs.


