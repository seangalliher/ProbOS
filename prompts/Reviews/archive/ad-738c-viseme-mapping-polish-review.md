# Review: AD-738c — Polish rhubarb→Oculus viseme mapping (mouth-shape accuracy)
**Verdict:** ✅ Approved
**One-line headline.** Two independent cheap-polish edits with sound rationale, clean default-kwarg backward-compat, and good boundary tests.

## Required (must fix before building)
*(none)*

## Recommended
1. **Empirical threshold (`_B_LONG_DURATION_MS = 80.0`) is unsourced.** Captain's smoke samples 2026-05-12 / 2026-05-13 are referenced but no captured data is in the repo. If the value turns out wrong post-build, Captain reviews via the smoke step. Suggest adding an env-var fallback in the SAME pass (`os.environ.get("PROBOS_AD738C_B_VOWEL_MS")` parse with default 80.0) so Captain can A/B without recompile. The prompt's comment already mentions this env var — but the implementation block doesn't actually wire it. Either implement it or remove the comment. (Builder pick — both acceptable.)

## Nits
1. Prompt's claim "around line 264-270" for the `_parse_rhubarb_output` call site is slightly off (actual: line 280). Builder must grep for `_map_preston_blair_to_oculus(value)` to locate; the prompt's "current code" block matches exactly.
2. Frame-emission code at the call site adds a `duration_s` local (good — avoids recomputing `float(end - start)` for both `duration=` and `duration_ms=`). ✓
3. Section 2's `0.20 ≥ 0.20` threshold assertion in the Vitest test uses `toBeGreaterThanOrEqual(0.20)`, but the new CH residual is bumped to **0.20** exactly — boundary-tight. Acceptable but if values drift down by floating-point round-trip, the test could false-fail. Use a tolerance (`>= 0.199`) or assert exact equality.

## Verified
- `_PRESTON_BLAIR_TO_OCULUS` at [rhubarb_backend.py#L41](src/probos/avatars/rhubarb_backend.py#L41) — current table matches prompt's "CURRENT" block exactly.
- `_map_preston_blair_to_oculus(pb: str) -> str` at [rhubarb_backend.py#L67](src/probos/avatars/rhubarb_backend.py#L67); signature change adds a default-valued kwarg (backward-compat preserved).
- Call site at [rhubarb_backend.py#L280](src/probos/avatars/rhubarb_backend.py#L280) (prompt says 264-270; off by ~10 lines but text matches). Duration is reachable: rhubarb's `mouthCues` carry `start`/`end`; `float(end - start) * 1000.0` is correct unit conversion.
- `VISEME_TARGETS` at [lipSyncTrack.ts#L70](ui/src/audio/lipSyncTrack.ts#L70); 9 consonant rows match prompt's "CURRENT" block byte-for-byte.
- `_VISEME_TARGETS` export at [lipSyncTrack.ts#L262](ui/src/audio/lipSyncTrack.ts#L262) — Vitest can import the symbol. ✓
- 4 pytest test cases cover happy path, new behavior, isolation, integration — all boundary classes covered.
- AD-738c slot-reuse: original forward marker → AD-738h (renumbered by AD-738a Section 3). Build order #4 follows #2. ✓
- License: all-internal; Preston Blair and Oculus shape sets are industry conventions not copyrighted code. ✓
- HXI Design Principles: "motion communicates state" (Principle #4) — bumped residuals make consonant motion more visible, aligning with the principle.
- BF-279 UI gate: prompt explicitly runs `npm run build` in verification commands. ✓
- AD-721b-3 (#561) forward marker preserved as the proper long-term fix. ✓

### Re-review (pass-2): unchanged, verdict re-affirmed ✅
