# AD-933b — Richer group escalation subset: agent image-gen in a room

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-933b** (sub-AD of AD-933). Builds on AD-933.
**Mode:** Builder. Code + tests + gates + commit local. No push. **Sequence after AD-933a** (both touch
`thread_fanout.py`).

## Scope (deliberately minimal)
AD-933 wired 5 escalation steps into the group fan-out. AD-933b adds **one** more channel-agnostic step —
`step_4c_image_gen_parse` (AD-730-3) — so an agent can generate an image inside a group chat, and surfaces
the generated SHA refs onto the persisted group message. **`step_4d_follow_up_parse` is explicitly NOT
added** (its `conversation_pacing_scheduler` re-injects a synthesized user-turn — ambiguous target in a
multi-agent room; deferred as forward marker **AD-933b-2**). No other step is added.

## Why step_4c is group-safe (verified vs HEAD)
`reply_pipeline.py:step_4c_image_gen_parse` reads `ctx.sanity_gate`, `ctx.runtime.config.avatars.image_gen_*`,
calls `dispatch_image_gen(runtime, agent_id, prompt)`, appends the SHA to `ctx.generated_attachment_ids`, and
honest-degrades (marker stripped, operator message appended) when the tier is disabled. Nothing in it is
1:1- or avatar-scoped. The ONLY gap is **surfacing**: `build_response()` exposes `generated_attachment_ids`
on the 1:1 response, but the group fan-out returns `{agent_id, callsign, text}` and never calls
`build_response()` — so a group-generated image would be created + stored but invisible.

## Changes
### 1. `src/probos/cognitive/dm/reply_pipeline.py` — add 4c to the subset
In `_escalation_steps()`, add `self.step_4c_image_gen_parse` in **run()-order** (4c precedes 4e in
`_full_steps`), so the tuple becomes:
`(self.step_4c_image_gen_parse, self.step_4e_action_dispatch, self.step_4i_notebook_parse,
self.step_4h_mesh_read_parse, self.step_4f_extract_artifacts, self.step_4g_create_task_parse)`.
Update the docstring's Included list to add 4c (AD-730-3 image-gen) and note AD-933b. No other change; `run()`
and `_full_steps()` stay byte-identical (4c is already in `_full_steps`, so the 1:1 path is unaffected).

### 2. `src/probos/routers/thread_fanout.py` — surface generated refs
In `_send_one`, after `await pipeline.run_escalation_only()` (and the existing
`reply_text = pipeline.ctx.response_text or reply_text`), capture
`generated_ids = list(pipeline.ctx.generated_attachment_ids or [])`. When non-empty, include them in the
`store.append_message(...)` metadata: extend the existing
`metadata={"intent_id": intent.id, "fanout": "ad914"}` with `"generated_attachment_ids": generated_ids`.
(Backend-only: the refs are now persisted on the message row — AD-916 already established
`metadata`-carried attachment refs on chat messages. UI rendering of group-generated images is forward
marker **AD-933b-3**.) Do NOT change the `{agent_id, callsign, text}` return shape. Keep it inside the
existing Tier-2 block; if the pipeline failed, `generated_ids` is `[]` and metadata is unchanged.

## Tests — `tests/test_ad933b_group_image_gen.py` (BF-287), floor +5
Real fixtures per AD-933/AD-933a. Monkeypatch `probos.cognitive.dm.reply_pipeline.dispatch_image_gen` (or
inject via the runtime config + a fake image tier) to return `{"ok": True, "attachment_id": "sha-xyz"}` for
the success case and `{"ok": False, "message": "image tier disabled"}` for the degrade case.
1. **`run_escalation_only()` now runs 6 steps incl. 4c** — spy the step methods; assert exactly
   {4c,4e,4i,4h,4f,4g} invoked, the other 11 NOT.
2. **`run()` still 17, byte-identical order** — regression guard.
3. **Group `[GEN_IMAGE ...]` surfaces the ref** — a canned reply containing `[GEN_IMAGE a cat]` → the
   persisted group message metadata has `generated_attachment_ids == ["sha-xyz"]` and the marker is stripped
   from the persisted text.
4. **Disabled tier honest-degrades** — `dispatch_image_gen` returns `ok:False`; reply persisted (operator
   message appended, marker stripped), metadata has no `generated_attachment_ids` (or empty), no crash.
5. **Plain reply unchanged** — no marker → metadata is exactly `{"intent_id", "fanout"}`, no new key.

## Gates
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad933b_group_image_gen.py -q -n 0 -p no:cacheprovider`
- Blast: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "thread or chat or fanout or reply or pipeline or image or escalat" -q -p no:cacheprovider`

## Acceptance
- Group fan-out runs 4c; generated SHA refs persisted on the message metadata; honest-degrade on disabled
  tier; `run()`/1:1 unchanged; return shape unchanged. Engineering Principles compliance verified.

## Do NOT
- Do NOT add `step_4d_follow_up` (AD-933b-2) or any other step. No UI work (AD-933b-3). No change to
  `build_response`, the 1:1 path, `DmReplyContext`, `IntentMessage`, the facilitator, or the Ward Room. No
  push. Explicit-path stage; deletion-audit.

## Trackers (after gates green)
- roadmap AD-933b SHIPPED + date; PROGRESS.md block; DECISIONS.md AD-933b entry (image-gen added + ref
  surfacing; step_4d/UI deferred as AD-933b-2/AD-933b-3).
