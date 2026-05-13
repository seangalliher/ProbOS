# Review: AD-721b-1 — Server-side rhubarb-lip-sync backend
**Verdict:** ⚠️ Conditional
**Wrong-file router wiring is a hard build-blocker; mime-allow-list compatibility is unverified across the wave.**

## Required (must fix before building)

1. **Section 3a wires the router in the wrong file.** The prompt instructs the Builder to "In `src/probos/runtime.py`, find the existing `app.include_router(...)` calls (search for `include_router(chat`)". Verified: `runtime.py` contains **zero** `include_router` calls. The FastAPI app is constructed in [src/probos/api.py](src/probos/api.py#L121) and routers are registered in a single tuple-iteration block at [src/probos/api.py](src/probos/api.py#L191-L209):
   ```
   from probos.routers import (
       ontology, system, ..., chat, ..., nl_graph_query,
   )
   for r in (
       ontology, system, ..., chat, ..., nl_graph_query,
   ):
       app.include_router(r.router)
   ```
   The Builder needs explicit instructions to add `avatars` to BOTH the import line AND the iteration tuple in `api.py`, not to `runtime.py`. As written, the Builder will either (a) silently land an `include_router` call in runtime.py that never executes, or (b) hard-stop hunting for a pattern that doesn't exist.

2. **`audio/webm` (and `audio/wav`) mime acceptance is unverified in the attachment-validation chain.** AD-721b-2 captures audio as `audio/webm` (Section 1, `mimeType ?? 'audio/webm'`) and uploads via `POST /api/chat/attachments/multipart`, which delegates to `_validate_and_store_attachment` ([src/probos/routers/chat.py](src/probos/routers/chat.py#L614)) — the same chain that enforces `AttachmentsConfig.allowed_mimes`. Neither prompt verifies the existing allow-list includes `audio/webm` (or `audio/wav` as the rhubarb-friendly fallback). If the allow-list rejects audio mimes, **the entire wave is dead-on-arrival**: every browser capture will 415 before reaching `/api/avatars/lipsync`, and the rhubarb backend will look broken when it never receives input. Required: add a "Section 0.5 — Verify mime allow-list" with explicit grep against the live `AttachmentsConfig.allowed_mimes` default, and either confirm coverage OR include the one-line config addition in this prompt (since it owns the validation chain seam).

## Recommended

1. **Test #2 (`test_is_available_false_when_version_probe_times_out`)** writes a "fake `rhubarb` script that sleeps forever" then explicitly skips on Windows. The same coverage is achievable cross-platform by monkeypatching `asyncio.create_subprocess_exec` to return a stub process whose `communicate()` hangs (mirrors the pattern in test #4). Eliminates the platform skip and the awkward shell-script fixture.

2. **Test count framing.** The prompt header says "≥ 10 new tests" but Section 4 lists 14 (numbered 1-14 across five test groups). Lock the lower bound to the actual count (14) so the Builder doesn't trim and call it done at 10.

3. **Section 1c (`config/system.yaml` example) is conditional** ("If `config/system.yaml` already has an `attachments:` block, add a documented example after it"). Conditional instructions cause Builders to skip silently when the condition isn't met. Either grep `system.yaml` now and lock the instruction unconditionally, or explicitly state "no edit if the block is absent — operator-facing docs cover the opt-in instead."

4. **`--machineReadable` flag is "verify against rhubarb docs" deferred to the Builder.** Architect should lock the flag name now from upstream rhubarb v1.13.0 release notes rather than push verification to build-time. The hedge "if the flag name has changed... the subprocess still works without it (just noisier stderr)" is true but the safer path is to omit `--machineReadable` entirely if it's not load-bearing — fewer moving parts, no version-coupling.

## Nits

1. Test list mixes "boundary tests" (group of 2 at #13/#14) with the higher-numbered groups; renumber as `1-12` core + `13-14` boundary, or split into separate `### Boundary tests (2 tests)` sub-section header (already done — but the count in the section title says "2" while #13 is correctly labeled).

2. Module docstring in `rhubarb_backend.py` says "Tier-2 log-and-degrade: every callable in this module returns either None or an empty list on failure". Minor consistency: `is_available` returns `bool`, not `None | bool`. Restate as "returns False / None / empty list".

3. `_resolve_binary_path` returns `Path | None`; the `with_exe` branch uses `p.with_suffix(p.suffix + ".exe")` for files with an existing suffix and `p.with_suffix(".exe")` for suffix-less files. The `+ ".exe"` concatenation produces `.exe.exe` if `p.suffix == ".exe"` already (e.g., operator wrote a Windows-style path). Add a `if p.suffix.lower() == ".exe": return None` guard or use `p.parent / (p.name + ".exe")`.

## Verified

- ✅ MIT license verification command and result documented.
- ✅ `/tools/` is on `.gitignore` line 3 (verified: `(Get-Content .gitignore)[2] == "/tools/"`).
- ✅ `_get_attachment_store` exists at [src/probos/routers/chat.py](src/probos/routers/chat.py#L599) and is safely importable from a sibling router.
- ✅ `AttachmentStore` Protocol at [src/probos/attachments/store.py](src/probos/attachments/store.py#L14) defines `async exists(content_hash) -> bool` and `async get_path(content_hash) -> Path` — prompt's `await store.exists(...)` and `await store.get_path(...)` usage matches.
- ✅ `AttachmentsConfig` at [src/probos/config.py](src/probos/config.py#L1112), wired into `Config` at [src/probos/config.py](src/probos/config.py#L3352). `from typing import Any, Literal` already at [src/probos/config.py](src/probos/config.py#L7) — no new import needed.
- ✅ 9→15 viseme mapping table is complete (all 9 Preston Blair shapes mapped, "X" → "sil" idle is sensible) with documented rationale (consonant-side lossy because renderer uses vowel morphs only).
- ✅ Subprocess invocation uses `asyncio.create_subprocess_exec` (no `shell=True`) with explicit `asyncio.wait_for` timeout and `proc.kill()` on timeout — secure, no zombies.
- ✅ Honest-degrade tier consistently applied (Tier-2 log-and-degrade) across all entry points; explicit guarantee none ever raise.
- ✅ Auto `.exe` append on Windows (modulo Nit #3) is sensible operator-friendly behavior.
- ✅ Endpoint correctly enforces 64-char lowercase-hex `attachment_id` shape and returns 400/404 with `detail` strings.
- ✅ AD-731 invariant honored: bytes flow through AttachmentStore, endpoint body carries only the sha256 ref.
- ✅ License Disposition section complete with MIT verification, operator-provided binary posture, and gitignore coverage statement.
- ✅ Type annotations on every public function. `VisemeFrame` is `frozen=True` dataclass.
- ✅ Logging includes file/timeout/stderr context per Engineering Principles.
- ✅ Phase ordering (review-criteria #10): N/A — adds a new router, no startup-phase consumer.
- ✅ Path collision check: existing `agents.py` uses `prefix="/api/agent"` (singular); new `avatars.py` uses `/api/avatars` (plural) — no collision.

---

### Re-review (pass-2) — 2026-05-12

**Verdict:** ✅ Approved
**All 2 pass-1 Required findings addressed against the live codebase. No new Required introduced. Two cosmetic counting inconsistencies remain at Recommended tier.**

#### Pass-1 Required — verification

| # | Finding | Resolution in revision | Live-codebase verification |
|---|---|---|---|
| R1 | Section 3a wired router in wrong file (`runtime.py`) | Section 3a rewritten as SEARCH/REPLACE against `src/probos/api.py:191-209` (import tuple + iteration tuple, single block). `runtime.py` removed from Files-touched table; explicit "do NOT touch" added. | ✅ `read_file src/probos/api.py 185-215` confirms the actual block at lines 191-209 matches the prompt's SEARCH verbatim — same 30 router names in the same order in both the import tuple and the iteration tuple. The REPLACE adds `avatars` to BOTH tuples. Builder will hit a unique match. |
| R2 | `audio/webm` / `audio/wav` mime acceptance unverified | New Section 0.5 added (own ed by this prompt). 0.5a extends `AttachmentsConfig.allowed_mime_types` default; 0.5b extends `attachments/mime.py._SIGNATURES`. 2 new regression tests (#15, #16). | ✅ `config.py:1112-1135` matches the SEARCH block exactly (9 MIMEs in documented order). `mime.py:15-26` matches the SEARCH block exactly. Magic bytes correct: WebM EBML header `\x1a\x45\xdf\xa3` is the canonical EBML magic; WAV `RIFF` at offset 0 + `WAVE` at offset 8 is the canonical RIFF/WAVE container. The short-circuit at `mime.py:87-88` (`if declared_mime in _SIGNATURES: return validate_image_bytes(...)`) means audio MIMEs added to `_SIGNATURES` automatically flow through magic-byte validation — no `_NON_IMAGE_MIMES` extension needed, as the prompt states. |

#### New Required findings

**None.** The revision is surgical and confined to the two flagged areas. No new architectural surface introduced. The endpoint contract, `LipSyncConfig` shape, `rhubarb_backend.py` API, and 9→15 viseme mapping table are unchanged from pass-1.

#### Internal consistency — Solution Overview / Files-touched / verification footer

- ✅ **Files-touched table** lists `attachments/mime.py` (new from revision) and removes `runtime.py` (correct — wiring is in `api.py` now).
- ✅ **Section 0.5 + Section 1c + Section 5** all agree: no `system.yaml` edit (verified zero `attachments|allowed_mime|lipsync` hits).
- ✅ **Verified Against Codebase** footer extended with the new grep evidence: `api.py` router-registration block, `runtime.py` zero-include_router, `_SIGNATURES` short-circuit, `system.yaml` zero-hit confirmation. Each grep claim is now load-bearing.
- ✅ **Acceptance criteria** updated to enumerate Section 0.5 deliverables (allow-list + `_SIGNATURES` extension) and the `runtime.py` zero-hit invariant.
- ✅ **Test gates** correctly sequence Section 0.5 tests before Section 1/2/3 (the endpoint tests #10-12 depend on the allow-list extension being in place).

#### Recommended (cosmetic, not blocking)

1. **Subsection counting nit.** The "Endpoint integration" sub-section header in Section 4 says "(3 tests)" but lists 4 tests (#9, #10, #11, #12). The header total "≥ 16" is correct (3 + 4 + 1 + 4 + 2 + 2 = 16). Builder should write 4 endpoint tests as enumerated.

2. **Stale comment in `mime.py:86`.** The existing comment `# Image MIMEs: delegate verbatim.` becomes misleading after audio MIMEs join `_SIGNATURES`. The prompt's Section 0.5b doesn't address this. Either re-word to `# Magic-byte-validated MIMEs: delegate verbatim.` or leave as-is; functional behavior is correct either way. Builder may catch it during review.

3. **`validate_image_bytes` function name** is now load-bearing for audio MIMEs too. Renaming would be a larger refactor; the docstring `"Return (True, sniffed_mime) if blob's magic bytes match"` is technically accurate for any MIME. Defer to a future hygiene AD if it bothers anyone.

#### Verified (pass-2 spot-check)

- ✅ Section 3a SEARCH block matches `api.py:191-209` byte-for-byte (30 router names in identical order, same indentation, same comment header `# ── Router registrations (AD-516) ──`).
- ✅ Section 0.5a SEARCH block matches `config.py:1124-1135` byte-for-byte.
- ✅ Section 0.5b SEARCH block matches `mime.py:15-26` byte-for-byte.
- ✅ EBML magic `\x1a\x45\xdf\xa3` is the standard WebM container header (EBML element ID 0x1A45DFA3).
- ✅ RIFF/WAVE conjunction (RIFF at offset 0 + WAVE at offset 8) is correct WAV identification — analogous to the existing WebP entry (RIFF + WEBP at offset 8). rhubarb's native WAV support documented in upstream README.
- ✅ Section 1a `LipSyncConfig` insertion point ("immediately after `AttachmentsConfig`") is unambiguous; `class AttachmentsConfig` ends before the next `class` definition in `config.py`.
- ✅ Test #15 (`test_attachments_default_allows_audio_webm_and_wav`) and #16 (`test_validate_attachment_bytes_accepts_audio_mime_magic_bytes`) cover both new gates with happy + negative paths.
- ✅ `_resolve_binary_path` rewrite eliminates the `.exe.exe` concatenation (Nit #3) — `p.parent / (p.name + ".exe")` gated on `p.suffix.lower() != ".exe"`.
- ✅ Test #2 (`test_is_available_false_when_version_probe_times_out`) now uses cross-platform monkeypatch instead of `pytest.mark.skipif` (Recommended #1 from pass-1).
- ✅ `--machineReadable` flag dropped from subprocess invocation (Recommended #4).
- ✅ Section 1c locked unconditionally to "no edit" (Recommended #3).
- ✅ Acceptance criteria includes the standing line: "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."
