# Review: AD-726 — DM post-LLM cleanup pipeline extraction
**Verdict:** ❌ Not Ready
**Verbatim-move is structurally possible, but the prompt's `DmReplyContext` shape is missing two load-bearing fields and constructs a third before it's defined.**

## Required (must fix before building)

1. **`step_1_sanity_gate_retry` needs `_params`, `message_text`, and `IntentMessage` — none are in `DmReplyContext`.**
   `src/probos/routers/agents.py:1300-1307` builds the retry intent:
   ```python
   retry_intent = IntentMessage(
       intent="direct_message",
       params={**_params, "text": message_text + retry_hint, "is_retry": True},
       target_agent_id=agent_id,
       ttl_seconds=60.0,
   )
   ```
   `_params` is built at `routers/agents.py:1216` and `message_text` is mutated across lines 1046, 1196, 1215 — both are local to `agent_chat` and used INSIDE the moved span. The prompt's `DmReplyContext` (Section 2) defines `req_message`, `response_text`, `sanity_gate`, etc., but does NOT include `_params` or `message_text`. The verbatim move will `NameError` on the first retry. **Add `params: dict[str, object]` and `message_text: str` to `DmReplyContext`** and thread them through Section 3's constructor call. `IntentMessage` should be lazy-imported inside `step_1_sanity_gate_retry` (matching the lazy-import pattern Section 2 prescribes).

2. **Section 3 constructor passes `sanity_result=sanity_result` but `sanity_result` is undefined at the replace anchor (line 1278).**
   `sanity_result` is first assigned at `routers/agents.py:1282`, INSIDE the `if response_text and sanity_gate is not None:` block that the prompt is extracting. At line 1278 (the SEARCH anchor), the name does not yet exist in the local scope. The `DmReplyPipeline(DmReplyContext(..., sanity_result=sanity_result, ...))` call will raise `NameError`. **Remove `sanity_result` from the `DmReplyContext` dataclass AND from the Section 3 ctor call** — it's a per-step local, created and consumed entirely inside `step_1_sanity_gate_retry`.

3. **`build_response` field-naming mismatch with existing code.**
   The current code (lines 1553-1559) builds the response dict with `"emotion": _emotion` (local name `_emotion` with underscore). The prompt's `DmReplyContext` exposes `emotion` (no underscore). The mapping is fine, but Section 3's instruction list at the bottom of Section 2 reads "Replace `_emotion` with `self.ctx.emotion`" — this rebinding must apply both to the assignment in `step_8` (line 1544: `_emotion: str | None = None` and the eventual assignment at line 1550) AND in `build_response`. Confirm by re-reading: the prompt's `build_response` already reads `self.ctx.emotion`, so this is consistent — but **`step_8_emotion_resolve` must STOP redeclaring `_emotion: str | None = None`** (the verbatim copy of line 1544 would create a local `_emotion` that shadows nothing and isn't read). Change the body to initialize `self.ctx.emotion` directly (or leave as-is and let the final assignment `self.ctx.emotion = ...` cover it). The verbatim-rebind rule needs an explicit carve-out for the `_emotion: str | None = None` declaration line — turn it into `# AD-726: emotion lives on ctx; pre-initialized in DmReplyContext default.`

## Recommended

1. **Net delta math is off by one.** Section 3 says "Net delta on `routers/agents.py`: -281 lines + 16 lines = -265 lines." The replace block in Section 3 is 16 SOURCE lines after the comment header (including blank lines). Counting the prompt's literal REPLACE block: 16 lines. The replaced span is 1278..1559 inclusive = 282 lines (verified by `1559 - 1278 + 1`). Delta = 16 - 282 = **-266 net**, not -265. `agent_chat` post-refactor = 574 - 266 = **308 lines**. Trivially wrong number; update the SCOPE STATEMENT and Acceptance Criteria. Doesn't block the build, but the Acceptance check "shrinks by exactly 265 net lines" will fail off-by-one.

2. **Top-level guard in `run()` collides with the verbatim-move discipline.** Each existing step body has its OWN `try/except` (most are `logger.debug` or `logger.warning` Tier-2). Wrapping with another `try/except` in `run()` is harmless but means a test like "step 5 raises" will be caught by the OUTER guard rather than the per-step guard — changing the OBSERVABLE log content (`AD-726: pipeline step X raised`) vs. the original (`AD-573: Working memory DM record failed`). This violates the verbatim-behavior contract for the rare path. Either (a) drop the top-level guard and rely on per-step Tier-2 (each step is already wrapped), or (b) document in the SCOPE STATEMENT that "outer guard log lines are NEW; pre-existing inner Tier-2 logs still fire on their original paths." Tests will fail if they grep for the original AD-N log strings on synthetic exception injection.

3. **The 8-step claim vs. the description's count.** SCOPE STATEMENT lists "Six pipeline steps" in the intro paragraph then enumerates 1-8 in the same paragraph. Recommend updating to "Eight pipeline steps" for consistency with the actual count.

4. **`DmReplyContext` should not store `sanity_gate` AND require step_1 to re-fetch it.** The current code at line 1280 does `sanity_gate = getattr(runtime, "dm_sanity_gate", None)` THEN the post-LLM block uses it. The prompt's Section 3 passes `sanity_gate=sanity_gate` — confirm the variable IS in scope at line 1278 (it should be, but line 1280 is the assignment so at line 1278 it isn't yet). **Verify the actual assignment line for `sanity_gate` in agent_chat.** If it's at line 1280 (immediately after the AD-724 comment), then line 1278 is BEFORE the assignment too — same NameError class as `sanity_result`. Re-anchor the SEARCH to start AT the `sanity_gate = getattr(...)` line (line 1280), and reposition the AD-724 comment INSIDE the replace block so the constructor is built where `sanity_gate` IS defined. Easiest fix: move the SEARCH anchor to line 1280 (the assignment) and shift the AD-724 comment into the REPLACE block as a one-line `# AD-724: DM sanity gate (extracted to DmReplyPipeline.step_1).`

## Nits

1. Section 2 docstring says "Eight ordered steps" but the run() loop and method definitions show eight — the SCOPE STATEMENT prose miscounts. Already covered in Recommended #3.
2. Section 5's instruction "near line 35-50" for the BEP append target is approximate; a unique anchor like `BF-274 multi_replace_string_in_file hazard` is given but the line range is fluff. Drop the line numbers; keep the anchor string.
3. `field` is imported from `dataclasses` in Section 2's skeleton but is never used (the ctx fields use plain defaults, not `field(default_factory=...)`). Drop the unused import.

## Verified

- 281-line verbatim span IS structurally extractable as 8 independent steps. Read `routers/agents.py:1278..1559`; each step's block is bounded by a blank-line + comment header, no shared mutable state EXCEPT what the prompt threads via ctx (`response_text`, `game_move_result`, `_emotion`).
- All public API anchors confirmed: `apply_divergence_check` at `divergence_detector.py:372`, `resolve_emotion_to_v1` (line 131), `SensoriumEntry` frozen at `cognitive_agent.py:95-115`, `_DM_SELF_WRAPPED_KEYS` 2 entries at line 472.
- Lazy-import pattern in step bodies (`from probos.X import Y` inside method) matches the existing inline code's pattern.
- Section 5 (AD-722c-3 / #654 fold) is a single docs append; low risk.
- No `multi_replace_string_in_file` on the 281-line span (BF-274 hazard explicitly forbidden).
- No new pip / npm deps. Apache 2.0 internal.
- 9 listed regression test files are real (verified by file_search precedent in the Wave 159 prompt review history).

## Build-go criteria

Required findings 1, 2, 3 fixed → re-review for verbatim-move discipline (single re-read of `routers/agents.py:1278..1559` against the revised ctx-field list to confirm every local-variable read in the moved bodies maps to a ctx field). After re-review, MED risk classification holds.


### Re-review (pass-2) — 2026-05-14

**Verdict:** ✅ Approved.

All 3 Required findings from pass-1 are resolved in the prompt's `## Revision (2026-05-14)` block and reflected in the body:

1. **ctx fields params / message_text** verified at `prompts/ad-726-dm-path-refactor.md:148-149`:
   `\\\python
   params: dict[str, object]
   message_text: str
   \\\`
   Rebind-rules carve-out at the bottom of Section 2 maps step_1's retry-intent _params → self.ctx.params and message_text → self.ctx.message_text. `IntentMessage` is lazy-imported inside step_1.
2. **sanity_result removed from ctx**, explicit comment at line 154-155: *"NOTE: sanity_result is intentionally NOT a ctx field — it is produced and consumed entirely within step_1_sanity_gate_retry."* Carve-out in rebind rules confirms.
3. **_emotion: str | None = None declaration line** carved out in rebind rules ("DROPPED — ctx.emotion already defaults to None"); uild_response reads self.ctx.emotion consistently.

Span and delta math both re-verified:
- 1278..1572 = 295 lines (re-quoted at lines 18, 60, 65-69, 190, 244, 296).
- REPLACE block = 23 lines; net delta = -272; post-refactor gent_chat ≈ 302 lines. Acceptance criterion now reads "Builder reports exact count" rather than the off-by-one "-265" claim.

Pass-1 Recommended #4 (sanity_gate undefined at line 1278) is resolved by hoisting sanity_gate = getattr(runtime, "dm_sanity_gate", None) into the REPLACE block BEFORE the pipeline construction. SEARCH anchor remains the # AD-724: DM sanity gate ... comment (unique). step_2/step_3 also read self.ctx.sanity_gate — single hoist serves all three.

Cross-prompt seam with AD-722a-4 (pass-2): AD-722a-4 now prepends a 5-line slot-clear guard to step_1_sanity_gate_retry. AD-726's step_1 docstring + verbatim body provides the unique SEARCH anchor for that prepend. No collision with AD-726's own SEARCH/REPLACE (which targets outers/agents.py:1278, not eply_pipeline.py). ✅

No new Required findings. Recommended #2 (outer-guard log content) and #3 (step-count prose) were absorbed inline (SCOPE STATEMENT now reads "Eight pipeline steps"; outer-guard logs documented as additive). All Nits remain Builder-discretion.

**Risk classification:** MED (unchanged from pass-1 build-go criteria).
