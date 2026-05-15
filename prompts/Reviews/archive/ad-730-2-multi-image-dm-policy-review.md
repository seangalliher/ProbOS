# Review: AD-730-2 — Multi-image DM policy
**Verdict:** ✅ Approved
**Three-tier policy is correctly scoped; Pillow integration is in-memory BytesIO (no subprocess hazard); AD-731 invariant preserved via new content-addressable refs.**

## Required (must fix before building)

(none)

## Recommended

1. **`store.put(bytes, mime)` signature is asserted but not verified in `Verified Against Codebase`.**
   The block at the end says "Builder verifies the `put` signature in `src/probos/attachments/filesystem_store.py`; if different, adjust." That's a Builder TODO at build-time, not a prompt-time verification. Move the `put` signature check into the verification block: grep `def put` in `filesystem_store.py` and quote the actual signature. If `put` is async (`async def put`) the Section 2 `await store.put(...)` is correct; if sync, the `await` is wrong.

2. **PIL `img.thumbnail` modifies the image in place AND drops EXIF metadata silently.** For vision-LLM consumption, EXIF orientation is irrelevant (the OpenAI/Anthropic adapters re-rasterize). Add a one-line comment in `downscale_if_needed` documenting the EXIF-strip side effect ("AD-730-2: thumbnail drops EXIF; harmless for vision-LLM consumption — re-rasterized at vendor boundary.").

3. **`captain_id` fallback to `"default"` is silent.** When `getattr(runtime, "captain_id", None)` returns `None`, budget tracking keys all captains to `"default"` — multi-captain deployments collapse to a single budget. Currently single-captain-per-deployment is the v1 assumption, but the fallback should log INFO once at startup wiring (Section 4) so operators see the bucket name being used. Alternative: log WARNING the first time a budget check uses `"default"` (use a `_logged_default_warning` module-level flag).

4. **`deque.setdefault` is used inside `check_budget`** — fine for a single-event-loop process, but `dict.setdefault` is the right method on `tracker` (which is `dict[str, deque]`). Re-read: `q = tracker.setdefault(captain_id, deque())` — that's `dict.setdefault` (correct). Just confirming; the variable naming made me look twice.

5. **`PIL.Image.thumbnail((max_dim, max_dim))` cap is symmetric.** A 4000x100 banner image with `max_dim=1024` will result in 1024x25 (preserves aspect ratio). That's fine; the bounding-box semantics are documented. No fix needed; flag for the future that "aspect-ratio-preserving thumbnail" is the chosen semantic over "scale-to-fit-area" — record the choice in DECISIONS.md.

6. **Budget tracker race condition is documented as "in-memory dict + per-process state."** Single-process / single-event-loop runtime: no real race. If the wave-160 or future fleet adds multi-process workers (uvicorn `--workers 2+`), the budget would be per-worker, not per-Captain. Document this in the AD-730-2-1 forward-marker description ("Advances ALSO when the runtime moves to multi-worker mode and per-worker budgets become observably unfair").

## Nits

1. Section 5 test #5 `test_downscale_oversize_image_substitutes_ref` — generate a 2048x2048 PNG via PIL in `setup`. Confirm PIL is available in the test environment (verified). Add a comment noting PIL is a test-time dep.
2. The dispatch claim "Pillow already installed" is verified `PIL 12.2.0` — explicit version pin in `pyproject.toml`?  Grep to confirm; if Pillow is a transitive dep of another package, document the source.
3. `HTTPException(status_code=e.status_code, detail=e.detail, headers=headers)` — `headers` kwarg supported in FastAPI ≥ 0.65. ProbOS pins something newer (verified by existing usage of headers kwarg in routers). OK.

## Verified

- AttachmentsConfig at `config.py:1189`; `multi_image_warn_threshold` at line 1239; `vision_tier_overrides` at line 1245 — insertion point between is clean. ✅
- `build_multimodal_messages` call at `routers/agents.py:1076` — anchor matches. ✅
- AD-731 invariant: original `req.attachment_ids` are preserved; `_trans` map produces a NEW ref tuple for re-passing to `build_multimodal_messages`. ✅
- Hard cap (Tier-1, strict reject) + downscale (Tier-2) + budget (Tier-2) — asymmetric tier choice is intentional and documented. ✅
- Forward markers AD-730-2-1 (persistent budget) and AD-730-2-2 (per-agent-type override) have technical triggers. ✅
- No new pip / npm deps. Pillow HPND-permissive, Apache 2.0 compatible. ✅
- No `multi_replace_string_in_file` adjacency hazard (Section 3 is a single insertion block before `if image_ids:`). ✅
- No `asyncio.create_subprocess_*` (all PIL ops in-memory via BytesIO). ✅
- No binary-on-stdout hazard (BF-282 not applicable — no subprocess at all). ✅
- 9 boundary tests cover all three tiers + Tier-2 fallbacks. ✅

## Build-go criteria

Approved as-is. Recommended fixes can land at build-time or in a follow-up nit-fix prompt.


### Re-review (pass-2): unchanged, verdict re-affirmed ✅

Prompt was not modified between pass-1 and pass-2 (confirmed: no `## Revision (2026-05-14)` section). Pass-1 verdict (✅ Approved — clean three-tier policy; AD-731 invariant preserved; PIL in-memory, no subprocess hazard) stands. The 6 Recommended and 3 Nit findings remain Builder-discretion; none block dispatch.
