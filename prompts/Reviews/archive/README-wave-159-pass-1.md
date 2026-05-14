# Wave 159 — Sweep Summary, Pass 1

**Date:** 2026-05-14. **Reviewer:** Architect. **Prompts reviewed:** 5. **Total Required findings:** 5.

---

## Per-prompt verdict

| # | Prompt | AD | Verdict | One-line justification |
|---|---|---|---|---|
| 1 | `prompts/ad-722c-telemetry-history.md` | AD-722c | ✅ Approved | All verify-first claims hold; JSONL pattern + Tier-2 hooks + 6 boundary tests are clean. |
| 2 | `prompts/ad-722d-records-auto-write.md` | AD-722d | ⚠️ Conditional | Section 2 ships sketched-then-corrected `_classify` body (BF-274 class footgun for Builder). One Required rewrite. |
| 3 | `prompts/ad-722b-3-snapshot-diff.md` | AD-722b-3 | ✅ Approved | Diff machinery + `type` field versioning sound; one file-table hint (`useAvatarTelemetry.ts`) is wrong but prompt instructs Builder to grep. |
| 4 | `prompts/ad-720e-audio-attachments.md` | AD-720e + AD-738e-2 | ❌ Not Ready | 3 Required fixes: (a) Section 2 invents `_ANY_OF_SIGNATURES` when `_ANY_OF` already exists at `mime.py:32`; (b) Section 5 (ProfileChatTab) targets non-existent `handlePaste`/`<img>` structure; (c) Section 4 "message renderer" cited doesn't exist in WardRoom either (chip-only render). |
| 5 | `prompts/ad-725-dm-subintent-dispatch.md` | AD-725 | ⚠️ Conditional | One attribute-name bug: `runtime.oracle_service` does not exist (correct name is `runtime.oracle` per AD-686). `hasattr` guard prevents crash but silently dead-branches the largest classifier pattern set. |

---

## Highest-risk prompt

**`ad-720e-audio-attachments.md`** (3 Required findings). The UI scope assumptions in Sections 4 + 5 are fundamentally mismatched against live code (`ProfileChatTab.tsx` has no `<img>` render to mirror; `WardRoomThreadDetail.tsx` renders chips only). The magic-byte matcher direction would have Builder invent a parallel mechanism (`_ANY_OF_SIGNATURES`) when the existing one (`_ANY_OF` frozenset) handles the case in one literal-extension edit. Builder following the prompt as-written would either (a) stop at Section 4/5 needing architect input, or (b) ship a non-functional MP3 magic-byte check (all-required semantics on 4 alternative sync bytes is impossible to match).

**Second-highest:** `ad-725-dm-subintent-dispatch.md` — the oracle attribute-name bug silently degrades the feature without crashing. Less severe (Tier-2 hasattr defense holds) but ships a dead branch.

---

## Cross-prompt concerns

1. **Build Group A ordering (1 → 2 → 3) is mandatory and correctly identified.** AD-722c lands the JSONL writer hook + AvatarTelemetryConfig history fields. AD-722d adds the records writer hook AFTER the AD-722c hook. AD-722b-3 wraps the WS frame in `{"type": "snapshot", ...}`. All three modify the same `_publish_loop` block (`routers/agents.py:707`/`737`) but at distinct insertion points. Dispatch's "AD-722d hook MUST go after AD-722c history-append" instruction is explicit. Verified independence at the config layer (three sets of non-overlapping fields).

2. **AD-722c writer hook receives the snapshot OBJECT (`_hist.append(snap)`), AD-722b-3 wraps the snapshot DICT (`{**snap_dict, "type": "snapshot"}`).** Operating on different representations — no contention. JSONL persistence remains "replay-complete" (full snapshot dicts) as the AD-722b-3 prompt's "What this does NOT change" section asserts. Compatible.

3. **AD-738e-2 numbering renumber is valid.** DECISIONS.md AD-738e-1:2569 reserves AD-738e-2 as a forward marker for "noise_w / sentence_silence per-emotion overrides." Renumber to `AD-738e-2-prosody` per Captain instruction; canonical `AD-738e-2` slot now holds the Refs-trailer standing rule (#653). Wave-158 precedent supports renumbering unbuilt forward markers (per user-memory standing rule). DECISIONS.md AD-738e-1 forward-markers line is the single edit point. Acceptable; **not** a hard-rule violation.

4. **License: no `pyproject.toml` or `ui/package.json` edits in any of the 5 prompts.** All-internal Apache 2.0. ✓

5. **AD-738b UI gate (`npm run build`) included in verification commands for the 2 UI-touching prompts (AD-722b-3 and AD-720e). ✓** AD-722c, AD-722d, AD-725 correctly omit (no UI changes).

6. **HXI design principle #3 (no emoji, inline SVG only).** AD-720e Section 3 uses inline SVG file-icon + native `<audio controls>`. AD-722b-3 doesn't touch UI rendering. ✓

7. **Phase-ordering audit (review-criteria §10).** AD-722d is the only prompt with cross-phase wiring (records_writer constructed in finalize after `_records_store` is wired in Phase 4). The two-phase pattern (None at construction, populate in finalize) is correctly modeled; dispatch's wave-specific reminder flags this for the reviewer (no false-positive on the initial None assignment).

8. **`multi_replace_string_in_file` hazard (BF-274/278).** All five prompts use SEARCH/REPLACE-style modifications with adequate context. AD-722d Section 2 is the riskiest because the file is NEW — no SEARCH/REPLACE — but the body contains the sketch-then-correct pattern flagged in the AD-722d review. Forcing the sketch out of the body removes the risk.

---

## Recommendation

**PROCEED to revision. Do NOT re-draft.**

All 5 Required findings are surgical:

| Prompt | Required Fix | Est. revision |
|---|---|---|
| AD-722d | Rewrite Section 2 `_classify` body to use `self._prior_div_mag` parallel dict directly; drop the sketch + design note | ~10 min |
| AD-720e #1 | Replace Section 2's invented `_ANY_OF_SIGNATURES` direction with one-line edit: add `audio/mpeg` + `audio/mp4` to existing `_ANY_OF` frozenset at `mime.py:32` | ~5 min |
| AD-720e #2 | Rescope Section 5 (ProfileChatTab): either drop entirely (Section 1's allow-list extension covers ProfileChatTab) or pivot to chip-level player extension | ~15 min |
| AD-720e #3 | Rescope Section 4 (WardRoom render block): same options — drop render extension OR chip-level player. `handlePaste` MIME-filter half stays. | ~10 min |
| AD-725 | Substitute `runtime.oracle` for `runtime.oracle_service` in Section 2 `_dispatch`; cite AD-686 in the Builder-verification footnote | ~5 min |

**Total revision wall-time estimate: ~45 min.** Architect drafts revisions; second-pass review verifies; Builder dispatches.

**Recommended scope-collapse for AD-720e (Recommended-tier, not Required):** scope the AD to "audio playback in IntentSurface; chip-only in WardRoom/ProfileChatTab; forward-marker AD-720e-3 for inline player in chip surfaces." Closes #566 with the operator-visible behavior (drag MP3 into chat → renders `<audio>`) while collapsing UI scope from 3 components to 1. Would simplify Sections 4 + 5 to MIME-filter extensions only.

---

## Audit trail

- **AD numbering:** Wave 159 consumes zero new top-level AD numbers. Current highest top-level AD per DECISIONS.md is **AD-739** (Captain Card planning placeholder, line 2457). Next free top-level AD remains **AD-740**. Verified.
- **Sub-ADs in wave:** AD-722c, AD-722d, AD-722b-3 (sub-slots of AD-722); AD-720e (sub-slot of AD-720); AD-725 (forward-marker slot reserved in AD-722/AD-723 family); AD-738e-2 (slot reuse, prosody marker renumbered to `AD-738e-2-prosody`).
- **Working tree integrity (2026-05-08 lesson):** verified clean before this review pass (`git status --porcelain` empty modulo untracked review artifacts). All file claims grep-confirmed against HEAD.

---

**Next step:** Architect drafts revisions for AD-722d Section 2, AD-720e Sections 2/4/5, AD-725 oracle attribute. Second-pass review verifies. Then Builder dispatch in order 1 → 2 → 3 → 4 → 5.
