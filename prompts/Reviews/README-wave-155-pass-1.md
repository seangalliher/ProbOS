# Wave 155 — Pass 1 Review Sweep Summary

**Date:** 2026-05-12
**Reviewer:** Architect
**Wave:** 155 (Phoneme-accurate lip-sync v2 — real audio + real visemes)
**Prompts reviewed:** 2

---

## Per-prompt verdicts

| Prompt | Verdict | One-line justification |
|---|---|---|
| [AD-721b-1 — rhubarb backend](ad-721b-1-rhubarb-lipsync-backend-review.md) | ⚠️ Conditional | Wrong-file router wiring (Section 3a points at `runtime.py`; actual location is `api.py:191-209`) is a hard build-blocker; mime allow-list compatibility is unverified. |
| [AD-721b-2 — browser capture](ad-721b-2-browser-real-audio-capture-review.md) | ⚠️ Conditional | Hook activation contradicts itself (Section 2c gates carefully, Section 3a hardcodes `enabled: true`); cross-prompt mime dependency on AD-721b-1. |

---

## Total Required findings

**4 Required across both prompts:**

| # | Prompt | Finding |
|---|---|---|
| R1 | AD-721b-1 | Section 3a wires router in wrong file (`runtime.py` has zero `include_router` calls; FastAPI app + registration are in `api.py:121` and `api.py:191-209` respectively) |
| R2 | AD-721b-1 | `audio/webm` / `audio/wav` mime acceptance unverified in `AttachmentsConfig.allowed_mimes` — wave-killer if missing |
| R3 | AD-721b-2 | Section 2c (careful enable gating) contradicts Section 3a (hardcoded `enabled: true`); `GET /api/system/config` does not exist |
| R4 | AD-721b-2 | Mime cross-prompt dependency on AD-721b-1 R2 must be called out in "Do NOT touch" / coordination section |

R2 and R4 are the same root issue at different prompt boundaries — collapsing both via a single Section 0.5 addition in AD-721b-1 (with a coordination call-out in AD-721b-2) resolves both.

---

## Highest-risk prompt

**AD-721b-1.** Two reasons:

1. **R1 is a hard build-blocker.** The Builder will hit the wrong-file instruction in Section 3a immediately and either hard-stop or land the change in a file where it never executes (no FastAPI app in `runtime.py` to call `include_router` on). AD-721b-2 has contradictions but they're recoverable at runtime — every wrong path lands on honest-degrade, not a broken endpoint.
2. **R2 owns the validation seam.** AD-721b-1's endpoint is downstream of `_validate_and_store_attachment`. If the allow-list change isn't part of this prompt, AD-721b-2 has no way to fix it after the fact without reopening AD-721b-1.

AD-721b-2 is the **lower-risk-but-higher-leverage** prompt: every defect lands on honest-degrade (the wave still ships, just with no user-visible improvement on browsers that don't route SpeechSynthesis). AD-721b-1 has defects that prevent the wave from working at all if not fixed.

---

## Cross-prompt concerns

1. **Mime allow-list (R2 + R4).** AD-721b-2 captures `audio/webm`, uploads via the same multipart endpoint AD-721b-1 reads from. The allow-list lives in `AttachmentsConfig` (owned by AD-721b-1's seam). Coordinate the fix in AD-721b-1; cross-reference in AD-721b-2.

2. **Endpoint shape contract.** AD-721b-2's `LipSyncResponse` interface (`{backend: 'rhubarb' | 'heuristic' | 'disabled', frames: LipSyncFrame[]}`) matches AD-721b-1's endpoint return shape exactly. ✅ Aligned. No action needed.

3. **`/tools/` gitignore coverage.** Both prompts and the dispatch correctly state `/tools/` is on `.gitignore` line 3. Verified. No edit needed.

4. **AD-731 invariant.** Both prompts honor it: bytes flow through AttachmentStore (AD-720), RPC bodies carry only the sha256 ref. AD-721b-2 test #3 explicitly asserts this. ✅

5. **Build order.** AD-721b-1 → AD-721b-2 is correctly enforced by the dispatch (Group A blocks Group B on the endpoint). No reordering required.

6. **Hook activation gating (R3) blocks meaningful end-to-end smoke testing.** Until R3 is resolved, the operator post-merge can't enable the rhubarb path through normal config — they'd be relying on the hardcoded `enabled: true` plus `lipsync.backend = "rhubarb"` in `system.yaml`. This actually works (server reads config; hook always tries; server returns rhubarb when configured), but it means R3's "always-on capture" wastes per-utterance work on every browser that can't route SpeechSynthesis. Operationally tolerable, but at odds with the prompt's "honest-degrade" framing.

---

## Recommendation

**PROCEED to revision stage.**

Both prompts are structurally sound — the architecture is right, the honest-degrade contract is consistent, AD-731 is honored, license posture is clean, test coverage is realistic, and the deferral list is tracked. The Required findings are all fixable in a single revision pass (4 surgical edits) and do not require re-architecting either prompt.

The revision pass should:

1. **AD-721b-1 Section 3a:** Replace the `runtime.py` wiring instruction with the correct `api.py:191-209` two-line edit (add `avatars` to the import tuple and to the iteration tuple).
2. **AD-721b-1 add Section 0.5:** Verify and (if needed) extend `AttachmentsConfig.allowed_mimes` to cover `audio/webm` and `audio/wav`. Include a one-line config edit if the existing allow-list rejects these.
3. **AD-721b-2 Section 2c & 3a:** Resolve the `enabled` contradiction. Preferred: hardcode `enabled: false` in this prompt and file AD-721b-2.4 (forward marker) for the config-fetch surface; alternative: ship a tiny `GET /api/avatars/lipsync/status` introspection endpoint in AD-721b-1 and consume it from the hook.
4. **AD-721b-2 Section 0:** Add a "Coordination" line referencing AD-721b-1's mime allow-list change.

After revision, a Pass-2 review should be a quick spot-check focused on the four edits above. If clean, dispatch to Builder.

**Do NOT dispatch to Builder until R1 and R3 are resolved.** R2/R4 (mime allow-list) is recoverable post-build via a follow-up commit, but it's cheaper to fix in this wave than to ship a wave with zero user-visible improvement.
