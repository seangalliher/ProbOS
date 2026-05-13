# Wave 155 — Pass 2 Review Sweep Summary

**Date:** 2026-05-12
**Reviewer:** Architect
**Wave:** 155 (Phoneme-accurate lip-sync v2 — real audio + real visemes)
**Prompts re-reviewed:** 2
**Convention:** #15 (relaxed) — APPROVE if 2✅ OR ≤1⚠️ on highest-risk only, no ❌; otherwise REJECT.

---

## Per-prompt pass-2 verdicts

| Prompt | Pass-1 | Pass-2 | One-line justification |
|---|---|---|---|
| [AD-721b-1 — rhubarb backend](ad-721b-1-rhubarb-lipsync-backend-review.md) | ⚠️ Conditional | **✅ Approved** | R1 + R2 cleanly resolved with verified SEARCH/REPLACE blocks against `api.py:191-209` and `config.py:1124-1135` + `mime.py:15-26`. Magic bytes (EBML, RIFF/WAVE) correct. No new Required. |
| [AD-721b-2 — browser capture](ad-721b-2-browser-real-audio-capture-review.md) | ⚠️ Conditional | **✅ Approved** | R3 resolved via "always-on" architecture (Captain Decision #3 + Section 2c + Section 3a all aligned; `GET /api/system/config` orphan removed). R4 cross-prompt seam called out in new Coordination sub-section. No new Required. |

---

## Final wave verdict

**✅ APPROVE**

Both prompts approved with no `⚠️` or `❌`. Convention #15 (relaxed) condition "2✅" satisfied.

---

## Highest-risk prompt

**AD-721b-1.** Unchanged from pass-1. Reasons remain:

1. AD-721b-1 owns the validation seam (mime allow-list + magic-byte sigs in Section 0.5). If those extensions miss, AD-721b-2 has no recovery path — every browser capture upload silently 415s and the wave ships zero user-visible improvement. Pass-2 verified the SEARCH blocks match the live files byte-for-byte, so the Builder will land both extensions correctly.
2. AD-721b-1 introduces the `POST /api/avatars/lipsync` endpoint and the `rhubarb_backend.py` subprocess wrapper. Endpoint defects land on `HTTPException` rather than honest-degrade; subprocess defects land on `[]` empty schedule (honest-degrade), but the endpoint is the load-bearing surface that AD-721b-2 consumes.

AD-721b-2 remains lower-risk-but-higher-leverage: every defective path lands on AD-721b v1 heuristic (preserved bit-for-bit), so even a partial AD-721b-2 ship is a no-op rather than a regression.

---

## Cross-prompt re-verification

| Concern | Pass-1 status | Pass-2 status |
|---|---|---|
| Mime allow-list seam (R2 + R4) | Open — needed allow-list owner identification | ✅ Resolved — AD-721b-1 Section 0.5 owns both gates; AD-721b-2 Coordination block calls it out; `config.py` + `mime.py` added to AD-721b-2's "Do NOT touch" |
| Endpoint shape contract | ✅ Aligned | ✅ Still aligned — `{backend, frames}` shape unchanged in both prompts |
| `/tools/` gitignore coverage | ✅ Verified line 3 | ✅ Unchanged |
| AD-731 invariant (refs not blobs) | ✅ Honored | ✅ Honored — test #3 in AD-721b-2 explicitly asserts JSON body with ref, not base64 |
| Build order (AD-721b-1 → AD-721b-2) | ✅ Enforced by dispatch | ✅ Reasserted in AD-721b-2 Coordination block |
| Hook activation gating | ⚠️ Contradiction (R3) | ✅ Resolved — always-on, server-side honest-degrade. No orphaned `GET /api/system/config` reference |

---

## Cosmetic findings (Recommended tier — do NOT block dispatch)

1. **AD-721b-1 Section 4 sub-section "Endpoint integration (3 tests)" lists 4 tests** (#9, #10, #11, #12). Header total `≥ 16` is correct.
2. **AD-721b-2 test count divergence.** Header says "≥ 6", Section 4 heading says "≥ 7", revision table claims "7 → 6 (3 + 3 + 1)", actual enumerated count is **8** (4 pure + 3 hook + 1 regression). Builder writing the 8 listed tests satisfies all three lower-bound figures. Pure-cosmetic.
3. **AD-721b-1 stale comment in `mime.py:86`** (`# Image MIMEs: delegate verbatim.`) becomes misleading after audio MIMEs join `_SIGNATURES`. Functional behavior is correct; comment-staleness only.

These do not satisfy the "any new Required → REJECT" condition. They are book-keeping nits and can be fixed during build or in a one-line follow-up commit.

---

## Recommendation

**ADVANCE to GATE 1.**

Both prompts are now Builder-ready:

- All pass-1 Required findings (R1, R2, R3, R4) cleanly addressed with verified SEARCH/REPLACE blocks against the live codebase.
- No new Required findings introduced by the revisions.
- "Always-on, server-side honest-degrade" framing is consistent end-to-end across Captain decisions, Section 2c, Section 3a code, Section 3a code-comments, and Section 4 test list.
- Cross-prompt seam ownership is unambiguous (AD-721b-1 owns the validator extensions; AD-721b-2 consumes them).
- The honest-degrade contract is end-to-end testable: capture-fail → server-fail → degraded-empty → CrewVRM heuristic-fallback → AD-721 D5 amplitude-final-fallback.

The orchestrator may dispatch AD-721b-1 to the Builder immediately. AD-721b-2 dispatches after AD-721b-1 commit lands (Group A → Group B serialization).
