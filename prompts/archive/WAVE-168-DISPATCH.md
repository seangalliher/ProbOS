# Wave 168 — Dispatch

**Drafted:** 2026-05-17. **Architect:** Wave 168 batch. **Builder dispatch:** continuous build mode (one AD = one commit).

## Scope — 6 ADs

| # | AD | Issue | Lift | Tests | UI gate | Order |
|---|------|-------|------|-------|---------|-------|
| 1 | AD-705b | #556 | Doc-only (close obsolete) | 0 | No | 1 |
| 2 | AD-718b | #523 | Research audit | 0 | No | 2 |
| 3 | AD-721f | #533 | Medium UI (canvas VRMs) | +6 vitest | Yes | 3 |
| 4 | AD-721a | #528 | Medium UI (avatar editor) | +8 vitest | Yes | 4 |
| 5 | AD-721e | #532 | Medium-large (anim library) | +6 pytest, +4 vitest | Yes | 5 |
| 6 | AD-720c | #551 | Large (OAuth cloud picker) | +14 pytest, +6 vitest | Yes | 6 |

**Highest shipped AD before Wave 168:** AD-739. All 6 Wave 168 ADs are pre-filed forward markers — no new AD numbers required from architect.

**Expected test deltas:** +20 pytest, +24 vitest.

## Cluster Sequencing (DAG)

All 6 ADs are independent of each other within Wave 168.

Dependencies on shipped work:
- AD-705b → AD-738 (Piper, W157), AD-718e (multi-lang voice, W166), AD-738e-1 (per-emotion prosody, W158).
- AD-718b → AD-738 (extension-point in place).
- AD-721f → AD-721 avatar pipeline, AD-721g per-tier baselines (W167).
- AD-721a → AD-721d-3 preview endpoint (W167), AD-721d propose path (existing).
- AD-721e → CrewVRM (existing), AD-721i-1 license whitelist (W166).
- AD-720c → AD-720a multipart (W139), AD-706f credential vault (W166), AD-731 AttachmentStore invariant (W151+).

**Recommended build order** (light → heavy; UI gate prompts last):

1. **AD-705b** (doc-only, fastest)
2. **AD-718b** (research-only, no UI gate)
3. **AD-721f** (UI, lower risk than 721a/e/720c)
4. **AD-721a** (UI, uses 721d-3 preview which is mature)
5. **AD-721e** (UI + asset manifest + new endpoints)
6. **AD-720c** (heaviest, OAuth + cloud HTTP + 4 endpoints + UI)

## Standing Rules (per `prompts/BUILDER-EXECUTION-PLAN.md`)

- **BF-274** — `multi_replace_string_in_file` is dangerous when replacement blocks are adjacent. Prefer single `replace_string_in_file` for adjacent edits.
- **BF-280** — Production code paths reachable from the FastAPI runtime MUST NOT use `asyncio.create_subprocess_*`. Use `subprocess.Popen + loop.run_in_executor`. AD-721e + AD-720c do not subprocess (httpx + three.js); no exposure.
- **BF-282** — Windows subprocess binary capture: write to tempfile, not stdout. Not applicable in this wave.
- **BF-286 / BF-287** — Use real Pydantic config (`SystemConfig()`) and real registry fixtures in tests, not MagicMock at substrate boundaries. Critical for AD-720c endpoint tests.
- **AD-738b** — Every UI prompt MUST gate on `cd ui; npm run build` AND `cd ui; npx vitest run`. Applies to: AD-721f, AD-721a, AD-721e, AD-720c.
- **AD-722c-3** — Forward markers must have TECHNICAL triggers (not "when convenient"). AD-718b (Coqui/Bark), AD-720c (OneDrive/Dropbox), AD-721e (gesture pack) all need concrete triggers.
- **AD-731** — Image/file bytes flow through `AttachmentStore.write(sha, blob, mime)` SHA-256 refs. Applies to: AD-721a preview path (already shipped via AD-721d-3), AD-720c download path (critical).
- **AD-721i-1** — License whitelist (CC0/MIT/Apache/BSD/CC-BY/MPL-2.0). Applies to: AD-721e animations, AD-718b audit.
- **AD-722b-1a (BF-287)** — Phantom-via-MagicMock anti-pattern: tests setting `mock_obj.foo = X` while production reads `obj.foo` pass silently. AD-720c endpoint tests use real registry fixtures and real `SystemConfig()`.
- **No `gh issue create` / `gh issue close` body content with `{`, `}`, or `\`** (PowerShell parsing trap). Describe errors structurally.

## License Posture (per Captain rule 2026-05-09)

- **AD-705b:** Doc-only; no license touched.
- **AD-718b:** Research audit — evaluates 3 candidates. Verdicts: Coqui DEFER (MPL-2.0 lib OK; CPML weights rejected), Bark DEFER (MIT OK; heavy), ElevenLabs REJECT (paid).
- **AD-721f:** No new deps. `three`, `@react-three/fiber`, `@pixiv/three-vrm` already resident.
- **AD-721a:** No new deps. Reuses `CrewVRM` + existing endpoints.
- **AD-721e:** No new deps. CC0 animation assets operator-fetched (gitignored, not in repo). If a tiny npm dep is unavoidable, surface for Captain ruling BEFORE drafting code.
- **AD-720c:** No new deps. `httpx` + `cryptography` already resident. OAuth tokens encrypted via existing Fernet (AD-706f vault). Operator brings their own OAuth client_id/secret (BYOC).

**Zero new pip deps, zero new npm deps across all 6 ADs.**

## Quality Gates (per-commit)

After EACH AD's commit:
1. `pytest tests/ -q -n 4 --dist=loadfile` → full parallel green.
2. For UI prompts (721f, 721a, 721e, 720c):
   - `cd ui; npm run build` → tsc + vite build green.
   - `cd ui; npx vitest run` → all vitest green.
3. `git status` clean (no untracked drift, no unintended deletions).

If any gate fails: STOP. File BF entry per BUILDER-EXECUTION-PLAN hard-stop rules. Do NOT proceed to the next AD.

## Hard-Stop Conditions

1. **Phantom API surfaces.** If any prompt asserts a method/class/import path that doesn't exist in HEAD, STOP and surface to architect. (Pre-flight grep evidence in each prompt should preempt this — Wave 166/167 caught zero phantoms.)
2. **License contamination.** If any AD-718b backend audit OR AD-721e animation source has unclear license terms, REJECT — do NOT integrate.
3. **AD-731 invariant violation.** If AD-720c download path returns raw file bytes to the browser (rather than a SHA ref), STOP. This is the canonical anti-pattern from the 2026-05-11 BF-265→AD-731 arc.
4. **Vault precondition skipped.** If AD-720c OAuth token storage bypasses `runtime.credential_vault` (e.g., writes to JSON sidecar directly), STOP. Tokens MUST flow through the vault.
5. **UI build break (AD-738b).** If `npm run build` fails on any UI prompt, STOP. Vitest passing is insufficient (Wave 156→157 stale-bundle lesson).
6. **Working-tree drift.** If `git status` shows >200 deletions on tracked files the Builder didn't author, STOP per the 2026-05-08 wiped-tree memory.

## Wave 168 Files Written

```
prompts/ad-705b-close-as-obsolete.md
prompts/ad-718b-extra-tts-backends-audit.md
prompts/ad-721f-cognitive-canvas-avatar-replacement.md
prompts/ad-721a-captain-avatar-editor-ui.md
prompts/ad-721e-skeletal-animation-library.md
prompts/ad-720c-cloud-file-picker.md
prompts/WAVE-168-DISPATCH.md  (this file)
```

## Verification Matrix

| AD | Pre-flight greps | Files cited | Phantom risk |
|----|------------------|-------------|--------------|
| AD-705b | piper_backend.py ✓, AD-738/AD-718e/AD-738e-1 DECISIONS.md lines ✓, scripts/piper-voice-fetch.ps1 ✓ | DECISIONS.md only | None |
| AD-718b | voice.ts:134 backend extension ✓, src/probos/audio/tts/backends.py ✓ | docs/research/ new, DECISIONS.md | None |
| AD-721f | canvas/agents.tsx:33-34 InstancedMesh ✓, CognitiveCanvas.tsx:63 ✓, CrewVRM.tsx ✓, baseline_resolver.py ✓ | new agentVRM.tsx, modify agents.tsx | None |
| AD-721a | preview endpoint agents.py:532 ✓, AD-731 invariant agents.py:605 ✓, max_proposal_iterations agents.py:471 ✓, AvatarDSL dsl.py ✓ | new CrewAvatarEditor.tsx, modify CrewAvatarPopout.tsx | None |
| AD-721e | CrewVRM.tsx:115 A-pose ✓, CrewVRM.tsx:398 idle loop ✓, asset_manifest.py ✓, AD-721i-1 whitelist ✓ | new AnimationManifest, modify CrewVRM.tsx, new endpoints | License: must confirm Quaternius CC0 in pre-flight before commit |
| AD-720c | AttachmentStore Protocol ✓, _validate_and_store_attachment chat.py:719,763 ✓, EncryptedFileCredentialVault credentials.py:130 ✓, vault Protocol store/read/delete ✓ | new cloud_pickers/ module, new router, new UI | None — fully composed of shipped primitives |

## Required Findings + Revisions

**None at draft time.** All 6 prompts ground every concrete claim in grep evidence. Three soft notes:

1. **AD-721a** assumes `GET /agents/{agent_id}/appearance` returns the DSL. Pre-flight Builder check: if it returns only the VRM URL, add a `dsl` field to that response (small spec change documented inline in the prompt).
2. **AD-721e** chooses Quaternius "Ultimate Animated Character Pack" as the default CC0 source. Builder pre-flight: confirm the pack still ships under CC0 at https://quaternius.com — if changed (rare for CC0 releases), fall back to KayKit Character Animations (also CC0). If both unavailable, surface for Captain ruling before code.
3. **AD-720c** ships Google Drive as the v1 working provider; OneDrive + Dropbox are interface stubs with forward markers. If Captain prefers a different v1 provider (Dropbox is simpler API; OneDrive is enterprise-common), swap before build.

## Zero-New-Deps Confirmation

| AD | pip | npm | Notes |
|----|-----|-----|-------|
| AD-705b | 0 | 0 | Doc-only |
| AD-718b | 0 | 0 | Research-only — Coqui/Bark would add deps but NOT shipped |
| AD-721f | 0 | 0 | `three`, `@react-three/fiber`, `@pixiv/three-vrm` resident |
| AD-721a | 0 | 0 | Reuses CrewVRM + existing endpoints |
| AD-721e | 0 | 0 | `THREE.AnimationMixer` in resident `three`; assets operator-fetched |
| AD-720c | 0 | 0 | `httpx` + `cryptography` resident; OAuth state via stdlib `secrets` |

## Line-Pinned References (Builder shortcuts)

- **AD-705b proof points:** `DECISIONS.md:2420` (AD-738 Piper), `DECISIONS.md:3688` (AD-718e), `DECISIONS.md:2540` (AD-738e-1), `ui/src/audio/voice.ts:134` (backend extension), `src/probos/audio/tts/piper_backend.py` (10843 bytes).
- **AD-718b extension point:** `ui/src/audio/voice.ts:134`, `src/probos/audio/tts/backends.py`.
- **AD-721f canvas:** `ui/src/canvas/agents.tsx:33-34` (InstancedMesh refs), `ui/src/components/CognitiveCanvas.tsx:63` (CognitiveCanvas function), `src/probos/avatars/baseline_resolver.py` (AD-721g VRM resolver).
- **AD-721a preview path:** `src/probos/routers/agents.py:532-627` (preview endpoint), `:471` (iteration cap on propose path only), `src/probos/avatars/dsl.py` (AvatarDSL fields).
- **AD-721e CrewVRM integration:** `ui/src/components/profile/CrewVRM.tsx:115` (A-pose), `:398` (procedural idle), `src/probos/avatars/asset_manifest.py` (manifest extension).
- **AD-720c primitives:** `src/probos/attachments/store.py:14` (AttachmentStore Protocol), `src/probos/routers/chat.py:719,763` (multipart + JSON paths), `src/probos/tools/browser/credentials.py:86,130,193` (vault Protocol + EncryptedFileCredentialVault + store method), `src/probos/startup/finalize.py:175-208` (vault enablement preconditions).

## Post-Sweep Procedure

After all 6 ADs land:

1. Run full Python gate: `pytest tests/ -q -n 4 --dist=loadfile`.
2. Run full UI gate: `cd ui; npm run build && npx vitest run`.
3. `git log --oneline origin/main..HEAD` — verify 6 commits, one per AD, plus any BF commits.
4. File forward-marker GitHub issues:
   - AD-718b-1 (Coqui), AD-718b-2 (Bark).
   - AD-720c-1 (OneDrive), AD-720c-2 (Dropbox).
   - AD-721e-1 (gesture / nod / shrug / typing animations, if not in v1).
5. Close GitHub issues: #556, #523, #533, #528, #532, #551 with shipped-commit links.
6. Update `PROGRESS.md` line 2 with new test counts.
7. Update `docs/development/roadmap.md` to mark Wave 168 ADs shipped.
8. Archive Wave 168 prompts: `prompts/archive/wave-168/`.
9. Append Wave 168 close entry to PROGRESS.md change log.
10. Self-check: re-read DECISIONS.md entries for the 6 ADs; verify each ships an audit trail (parent ADs, dates, GitHub issue links).
