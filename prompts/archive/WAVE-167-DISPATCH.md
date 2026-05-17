# Wave 167 — Avatar UX polish + tool integration

**Architect:** Wave 167 ready 2026-05-17
**Theme:** Avatar UX polish + tool integration. 5 ADs, all materializing pre-filed forward markers.
**Highest shipped AD before Wave 167:** AD-739 (Captain Card data model, Wave 166).
**Wave 167 ADs:** all forward markers (AD-721d-3 / AD-721g / AD-721h / AD-721i-2 / AD-720b) — **no new AD numbers needed**.

---

## ⚠️ Required Captain ruling — read before build

The dispatch brief for **AD-720b** said "Captain attaches a tool **output** (browser session screenshot, MCP resource) to a DM via attachment marker." The actual issue #550 body says "attach AD-706 BrowserTool / AD-449 MCP tools to a chat surface as scoped **capability grants**." These are different features. The Architect drafted per the issue body (capability grants), because:

1. The screenshot-attach path already works today — BrowserTool already writes screenshots to AttachmentStore (`tools/browser/compute_use.py:174-176`) and they ride existing `attachment_ids` through chat.
2. The capability-grant path is a real gap — there's a `/tool-access grant` shell command but no HXI equivalent.

If the Captain wants the attachment-marker feature instead: file a new issue, assign AD-720c, and either swap the AD-720b prompt or run both in a future wave. Builder: do **not** start AD-720b until Captain confirms scope. The other 4 ADs are independent of this ruling.

---

## Build groups (DAG)

All 5 ADs are independent — no inter-AD dependencies inside the wave. Recommended order optimizes for risk and operator visibility:

| Order | AD | Issue | Risk | Notes |
|---|---|---|---|---|
| 1 | AD-721d-3 | #619 | Medium | New endpoint + new UI button. Wires AD-721i renderer to UI. Most user-visible. |
| 2 | AD-721g | #534 | Low | Pure resolver + config. No subprocess, no UI surface change. Easy gate. |
| 3 | AD-721h | #535 | Medium | Multipart upload. Reuses AD-720a pattern. Has UI surface (drag/drop). |
| 4 | AD-720b | #550 | Medium | Awaits Captain scope ruling. Permissions endpoint + UI slash-command. |
| 5 | AD-721i-2 | #543 | Trivial | Research only — single markdown file. No code, no tests. |

---

## Verification matrix (Architect pre-flight)

| Claim | File | Line | Status |
|---|---|---|---|
| `BlenderRenderer.render() -> Path` async | `src/probos/avatars/blender_renderer.py` | 113 | ✅ confirmed |
| Renderer outputs `.vrm` only (no PNG path) | `src/probos/avatars/_blender/render_avatar.py` | 75–102 | ✅ confirmed (informs AD-721d-3 design — client-side three.js renders VRM, no backend PNG synthesis) |
| `propose_appearance` on CognitiveAgent | `src/probos/cognitive/cognitive_agent.py` | 3477 | ✅ |
| `iteration_count` in proposal_history | `src/probos/avatars/proposal_history.py` | 169 | ✅ |
| Propose endpoint | `src/probos/routers/agents.py` | 394 | ✅ |
| PUT persist endpoint | `src/probos/routers/agents.py` | 499 | ✅ |
| Multipart upload helper | `src/probos/routers/chat.py` | 763 | ✅ |
| `_validate_and_store_attachment` | `src/probos/routers/chat.py` | 621 | ✅ |
| `_get_attachment_store` | `src/probos/routers/chat.py` | 606 | ✅ |
| `AvatarsConfig` | `src/probos/config.py` | 1166 | ✅ |
| `dsl_drafts_dir` | `src/probos/config.py` | 1174 | ✅ |
| `renderer_enabled` transitional default-False | `src/probos/config.py` | 1175 | ✅ |
| `max_vrm_size_bytes` 25 MB | `src/probos/config.py` | 1171 | ✅ |
| Avatar serve route | `src/probos/routers/system.py` | 639 | ✅ |
| `_resolve_avatars_dir` | `src/probos/routers/system.py` | 669 | ✅ |
| `Rank` enum (ensign/lt/cmdr/senior) | `src/probos/crew_profile.py` | 30 | ✅ |
| `Rank.from_trust` | `src/probos/crew_profile.py` | 39 | ✅ |
| `AppearanceProfile.vrm_url` | `src/probos/crew_profile.py` | 266 | ✅ |
| `ToolPermissionStore.issue_grant` | `src/probos/tools/permissions.py` | 110 | ✅ (NOT `grant_access` as a naive guess might propose) |
| BrowserTool screenshot → AttachmentStore | `src/probos/tools/browser/compute_use.py` | 154–176 | ✅ (informs AD-720b scope clarification) |
| MCP bridge | `src/probos/federation/mcp_server.py` | 3 | ✅ AD-449 shipped |
| Chat UI multipart pattern | `ui/src/components/IntentSurface.tsx` | 525 | ✅ |
| `AgentProfilePanel.tsx` Design avatar button | `ui/src/components/profile/AgentProfilePanel.tsx` | 225 | ✅ |
| `CrewVRM.tsx` three.js loader | `ui/src/components/profile/CrewVRM.tsx` | 13, 250 | ✅ |

**No phantom APIs surfaced.** Zero pre-flight revisions needed (vs Wave 166 which caught `is_compute_use_tier_configured` phantom).

## Required findings from self-check

1. **AD-720b scope mismatch (Required, Captain ruling).** Documented above and at top of `ad-720b-chat-tool-attach.md`. Builder gate: do not start AD-720b until Captain confirms.
2. **AD-721d-3 renderer-output shape (Recommended, informs design).** The renderer outputs VRM, not PNG. The prompt correctly designs around client-side three.js rendering of the unpersisted VRM via AttachmentStore. No backend PNG synthesis added — that would be scope creep and would require Pillow/Blender headless-render-image work.
3. **BF-280 latent risk in `blender_renderer.py` (Out of scope, noted).** `asyncio.create_subprocess_exec` exists at `blender_renderer.py:178`. Known under SelectorEventLoop. AD-721d-3 prompt explicitly says: do not fix here. File a forward marker if you want; do not "fix" it as a Wave 167 side-effect.
4. **`ToolPermissionStore` method name is `issue_grant`, not `grant_access`** — AD-720b prompt uses the real name.
5. **VRM upload size cap reuses existing 25 MB default** — AD-721h does not introduce a new size config.

## Zero-new-deps confirmation

| AD | New pip | New npm | Notes |
|---|---|---|---|
| AD-721d-3 | 0 | 0 | reuses BlenderRenderer + AttachmentStore + three.js (already present) |
| AD-721g | 0 | 0 | pure resolver |
| AD-721h | 0 | 0 | reuses FastAPI UploadFile + AttachmentStore |
| AD-721i-2 | 0 | 0 | research-only, single markdown file |
| AD-720b | 0 | 0 | reuses ToolPermissionStore |

**Total Wave 167 dep delta: 0.**

## Standing rules embedded in every prompt

Each of the 5 prompts cites these where applicable:

- **BF-274**: single-replace for adjacent edits (no `multi_replace_string_in_file` with overlapping contexts in vision-pipeline-adjacent code).
- **BF-280**: no `asyncio.create_subprocess_exec` in new code reachable from FastAPI. AD-721d-3 reuses the existing BlenderRenderer surface but does not introduce a new subprocess call site.
- **BF-282**: subprocess that emits binary on Windows → tempfile, not stdout pipe. N/A in Wave 167; no new subprocess wrappers.
- **BF-286 / BF-287**: real Pydantic `Config()`, real `AgentRegistry`, real `FilesystemAttachmentStore` in tests. MagicMock at substrate boundaries is the canonical anti-pattern. Every prompt's test section calls this out.
- **AD-731 invariant**: image / VRM bytes ride AttachmentStore SHA-256 refs. AD-721d-3 + AD-721h both honor this (dual-write for AD-721h: content-addressed AttachmentStore copy + named avatars_dir cache).
- **AD-738b UI gate**: `cd ui; npm run build` AND `cd ui; npx vitest run` for every prompt that touches `ui/src/**`. Applies to AD-721d-3, AD-721h, AD-720b.
- **AD-722c-3 TECHNICAL forward markers**: deferrals filed as forward markers in roadmap + GitHub issue, not just inline TODO.
- **AD-721i-1 license whitelist**: CC0/MIT/Apache/BSD/CC-BY only for any bytes the operator installs. AD-721g manifest defaults to empty strings — no bytes shipped.

## Per-prompt acceptance gates

Each prompt's "Acceptance Criteria" section embeds the standing line:
> Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Test gate commands

| Mode | Command | When |
|---|---|---|
| Full parallel gate | `pytest tests/ -q -n 4 --dist=loadfile` | Pre-flight, per-prompt, post-wave |
| Focused per-prompt gate | `pytest tests/test_ad7xxx_*.py -v -n 0` | Single-file verification |
| Triage gate | `pytest tests/<failing_file> -q -n 0` | Confirm parallel failure is environmental |
| UI gate | `cd ui; npx vitest run` AND `cd ui; npm run build` | Every prompt that touches `ui/src/**` |

`-n auto` is forbidden until AD-682 lands.

## Expected wave deltas

| AD | pytest | vitest | Notes |
|---|---|---|---|
| AD-721d-3 | +8 | +3 | Endpoint + UI preview button |
| AD-721g | +9 | 0 | Pure resolver |
| AD-721h | +8 | +4 | Multipart endpoint + drag/drop UI |
| AD-720b | +10 | +4 | Permission endpoint + slash-command UI |
| AD-721i-2 | 0 | 0 | Research only |
| **Total** | **+35** | **+11** | |

**Target test count after Wave 167:** ~13874 + 35 = ~13909 pytest, 667 + 11 = 678 vitest.

## Hard-stop conditions (per BUILDER-EXECUTION-PLAN)

Per the standard rules, hard-stops in this wave:

1. AD-720b scope ruling not received from Captain → skip AD-720b, build the other 4.
2. Phantom API found in any prompt (none expected — pre-flight clean) → revise prompt, do not patch on the fly.
3. >200-line tracked-file deletion appears in `git diff` between prompts → STOP. Working-tree integrity check.
4. UI gate (`npm run build`) fails → fix the build before committing. Do **not** ship a green vitest with a red `npm run build` (AD-738b lesson).
5. Test suite drops below ~13800 pytest at any inter-prompt gate → investigate before continuing.

## Tracking

After each prompt ships:

- PROGRESS.md: append AD line, update test count line 3.
- `docs/development/roadmap.md`: append AD line, close the GH issue, add `(shipped Wave 167)`.
- `DECISIONS.md`: append AD record (single paragraph).
- `prompts/wave-plan.yaml`: bump status to `shipped`.

After all 5 prompts ship:

- Archive sweep: move `prompts/ad-7*.md` to `prompts/archive/wave-167/`.
- Update `prompts/wave-plan.yaml` Wave 167 status.
- Final commit: `wave-plan: mark Wave 167 shipped + archive prompts`.

## Files written by Architect (this wave)

```
prompts/ad-721d-3-avatar-preview-before-persist.md
prompts/ad-721g-per-tier-baseline-vrms.md
prompts/ad-721h-browser-vrm-upload-ui.md
prompts/ad-721i-2-vroid-cli-evaluation.md
prompts/ad-720b-chat-tool-attach.md
prompts/WAVE-167-DISPATCH.md  (this file)
```

---

## Line-pinned references (for Builder convenience)

- AD-721i renderer surface: `src/probos/avatars/blender_renderer.py:113` (`async def render(self, dsl, agent_id) -> Path`).
- AD-721d-1 propose endpoint: `src/probos/routers/agents.py:394`.
- AD-721d-1 iteration_count: `src/probos/avatars/proposal_history.py:169`.
- AD-721d-1 PUT persist: `src/probos/routers/agents.py:499`.
- AD-720a multipart upload: `src/probos/routers/chat.py:763`.
- AD-720a shared validator: `src/probos/routers/chat.py:621` (`_validate_and_store_attachment`).
- AD-720a `_get_attachment_store`: `src/probos/routers/chat.py:606`.
- AD-720 attachment marker: **does not exist as a literal `[ATTACH ...]` syntax in code.** Chat uses `attachment_ids: list[str]` on the request body (`api_models.py:24, 153`). The "marker" framing in the dispatch brief is incorrect — flagged in the AD-720b prompt.
- AD-706 BrowserTool screenshot: `src/probos/tools/browser/compute_use.py:154` (capture), `:174-176` (sha256 + AttachmentStore.write).
- ToolPermissionStore.issue_grant: `src/probos/tools/permissions.py:110`.
- AvatarsConfig: `src/probos/config.py:1166`.
- Rank.from_trust: `src/probos/crew_profile.py:39`.
- HXI Design-avatar button: `ui/src/components/profile/AgentProfilePanel.tsx:225`.
- HXI multipart upload pattern: `ui/src/components/IntentSurface.tsx:525`.
- HXI VRM loader: `ui/src/components/profile/CrewVRM.tsx:13` (import), `:250` (filename resolver).

---

## Builder dispatch

1. Read `prompts/BUILDER-EXECUTION-PLAN.md` standing rules.
2. Read this dispatch file in full.
3. Read each AD prompt before starting its build.
4. **Captain ruling required on AD-720b scope before that prompt is built.** Other 4 ADs may proceed independently.
5. Per-prompt: full parallel gate after each commit. UI prompts include `npm run build`.
6. Hard-stop conditions as listed.

Builder ready. Wave 167 dispatched.
