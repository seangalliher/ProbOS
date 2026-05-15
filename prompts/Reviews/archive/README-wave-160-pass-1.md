# Wave 160 — First-Pass Review Summary

**Date:** 2026-05-14. **Pass:** 1. **Reviewer:** Architect.
**Prompts audited:** 5 (`ad-726`, `ad-722a-4`, `ad-722b-4`, `ad-730-2`, `ad-723a-3`).

---

## Per-prompt verdict

| # | Prompt | Verdict | Headline |
|---|---|---|---|
| 1 | `ad-726-dm-path-refactor.md` | ❌ Not Ready | `DmReplyContext` missing `_params` / `message_text`; constructor passes `sanity_result` before it's defined. |
| 2 | `ad-722a-4-divergence-auto-correction.md` | ⚠️ Conditional | Slot-clear in `step_7` runs before TTS consumer reads — correction never reaches prosody. |
| 3 | `ad-722b-4-multi-agent-telemetry-stream.md` | ⚠️ Conditional | HXI hook URL omits the `/api/agent` router prefix; will 404. |
| 4 | `ad-730-2-multi-image-dm-policy.md` | ✅ Approved | Clean three-tier policy; AD-731 invariant preserved; PIL in-memory (no subprocess hazard). |
| 5 | `ad-723a-3-sensorium-entry-metadata.md` | ✅ Approved | Pure additive frozen-dataclass extension; backward-compatible. |

---

## Required findings — total count

| Prompt | Required | Recommended | Nits |
|---|---|---|---|
| AD-726 | 3 | 4 | 3 |
| AD-722a-4 | 3 | 4 | 2 |
| AD-722b-4 | 3 | 5 | 3 |
| AD-730-2 | 0 | 6 | 3 |
| AD-723a-3 | 0 | 4 | 4 |
| **Total** | **9** | **23** | **15** |

---

## Highest-risk prompt

**AD-726** (DM-path refactor) is the highest risk by a wide margin. Three concrete Required defects all stem from the same class of error: the `DmReplyContext` shape was designed without exhaustively reading the 281-line span's local-variable dependencies. Specifically:

1. `_params` and `message_text` (used in `step_1`'s retry path) are not in the ctx — verbatim move will `NameError`.
2. `sanity_result` is passed to the ctx constructor at line 1278, but the variable doesn't exist until line 1282 (inside the moved block).
3. `_emotion: str | None = None` declaration line in the verbatim move shadows nothing useful when rebound to `self.ctx.emotion`.

None of these is structurally fatal — the verbatim move IS feasible. The fix is mechanical: add two ctx fields, drop one ctx field, re-anchor the SEARCH from line 1278 to line 1280 (where `sanity_gate` is assigned), and add a one-line carve-out to the rebind rules. Estimated revision cost: 30 minutes.

If the prompt ships as-drafted, the Builder will hit the `NameError` on the first integration-test pytest run, which is the cheapest possible failure mode but still triggers a hard-stop and a re-prompt cycle.

**AD-722a-4** is the second-highest risk because Required #1 (slot-clear timing) is a load-bearing architectural defect — the entire feature does nothing observable as drafted. Fix is one-paragraph: move the `pop()` from step_7-end to step_1-start (or pre-LLM enter_dm).

**AD-722b-4** is third-highest. The URL prefix bug is shallow but will hit silently in production (HXI hook 404s; per-agent endpoint keeps working so nothing alarms).

---

## Cross-prompt concerns

1. **AD-722a-4 / AD-726 ordering.** AD-722a-4 Section 5 appends to `DmReplyPipeline.step_7_mark_emitted`. AD-726 MUST land first (Wave 160 dispatch already specifies this). The Required #1 fix in AD-722a-4 (move slot-clear out of step_7) ALSO means AD-722a-4's pipeline-side dependency on AD-726 shrinks — option (a) clears in step_1 OR pre-LLM, so the cross-prompt seam is at a different point in the pipeline. AD-726's Section 2 step_1 skeleton must accommodate the slot-clear call. Re-coordinate after AD-722a-4 Required #1 is resolved.

2. **AD-722b-4 / AD-738b UI gate.** AD-722b-4 verification commands DO include both `vitest run` AND `npm run build` (compliance with the AD-738b standing rule). ✅ The only UI-touching prompt in the wave honors the standing rule.

3. **No license drift.** All 5 prompts are all-internal Apache 2.0. No `pyproject.toml` / `package.json` edits anywhere. ✅

4. **AD-722c-3 (#654) fold.** AD-726 Section 5 appends ONE bullet to `prompts/BUILDER-EXECUTION-PLAN.md` Standing Rules — the technical-trigger forward-marker rule. Pure docs edit. Sensible to fold into AD-726 (highest-LOC prompt in the wave). ✅

5. **`multi_replace_string_in_file` discipline.** All 5 prompts explicitly forbid adjacent-block multi-replace on `routers/agents.py`. AD-726 (281-line span), AD-722a-4 (correction branch insertion), AD-730-2 (policy hook insertion) — each uses single `replace_string_in_file`. ✅ BF-274/BF-278 lessons applied.

6. **No `asyncio.create_subprocess_*` in any prompt.** All HTTP / WS / PIL ops are in-process. BF-280 lesson applied. ✅

7. **HXI emoji rule.** AD-722b-4 is the only UI-touching prompt; its hook file is pure logic (no JSX). No emoji vector. ✅

8. **AD numbering.** Dispatch confirms next free top-level AD is AD-740 (unchanged). Wave 160 consumes zero new top-level numbers. ✅ Manually verified the dispatch claim by spot-checking that all AD numbers used are sub-AD slots or already-reserved forward markers.

---

## Recommendation

**RE-DRAFT.** Three of five prompts have Required findings (9 total) that materially affect build outcome. None is architectural — every Required finding has a mechanical fix. Estimated re-draft cost:

- AD-726: ~30 min (ctx-field additions, SEARCH anchor shift, three line-level changes).
- AD-722a-4: ~20 min (move slot-clear out of step_7; reword Section 5; tighten Section 3 pseudocode).
- AD-722b-4: ~10 min (URL prefix in hook + tests + Section 2 verification step #6 wording).

AD-730-2 and AD-723a-3 can ship without revision (Recommended fixes can land at build-time or in a follow-up nit-fix prompt).

After re-draft, a second-pass review on the three revised prompts should converge quickly — no structural defects identified, all findings are surface-mechanical. Build dispatch may proceed for prompts 4 and 5 in parallel with the re-draft cycle if the wave's build-order dependency (AD-726 first) is relaxed for the additive-only prompts. Per dispatch, the order 1 → 5 → 2 → 4 → 3 ALREADY puts AD-723a-3 second; the dispatch order can be reshuffled to 5 → 4 → (re-draft 1/2/3) without consequence.

**Build-go path:**

1. Re-draft AD-726, AD-722a-4, AD-722b-4.
2. Architect re-review (pass 2) the three revised prompts only.
3. Dispatch in the dispatch's recommended order, with the caveat that prompts 4 and 5 may ship first if the operator chooses to parallelize.
