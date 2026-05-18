# Wave 169 — Dispatch

**Drafted:** 2026-05-17. **Architect:** Wave 169 batch. **Builder dispatch mode:** continuous build (one AD = one commit).

## Scope — 2 ADs

| # | AD | Issue | Lift | Tests | UI gate | Order |
|---|-----|-------|------|-------|---------|-------|
| 1 | AD-740 | #664 | Small/focused (drift detector) | +8 pytest | No | 1 (light) |
| 2 | AD-730-3 | #633 | Large (image gen + tier + governance) | +14 pytest (~+18 incl. eight-guard) | Conditional* | 2 (heavy) |

\* AD-730-3 does NOT modify the HXI in v1. It MAY require a one-grep check on `ui/src/**` for existing `attachment_ids` handling on the agent-reply surface; missing handling is filed as forward marker AD-730-3-4, not built.

**Highest shipped AD before Wave 169:** AD-739.
**New AD numbers:** AD-740 (drift detector — AD-739a was already taken by Captain Card per-department overlay forward marker, so the drift detector advances cleanly to AD-740). AD-730-3 is a pre-existing sub-AD of AD-730 (Wave 151 — already in issue #633 title).

**Expected test deltas:** +22 pytest minimum (+8 AD-740 / +14 AD-730-3 core, +4 eight-guard regression in AD-730-3 = +18 likely).
**Expected vitest deltas:** 0.

## Cluster Sequencing (DAG)

The two ADs are **independent of each other** within Wave 169.

Dependencies on shipped work:

- **AD-740** → AD-722a-5 ring buffer (W143), AD-728c `check_own_render` (W164), AD-728d skill (W165).
- **AD-730-3** → AD-730 image consumption (W151), AD-731 AttachmentStore SHA refs (W151), AD-732 vision-tier + 8-guard (W153), AD-727 governance pattern (W148), AD-728d bracket-marker shape (W165), AD-541b anchored episodes (Wave ~135).

**Recommended build order** (light → heavy):

1. **AD-740** (drift detector) — pure read-only summary, +8 tests, no UI, no new deps, no new tier, no new bus shape. Lowest risk.
2. **AD-730-3** (image gen) — new tier (sixth peer), new bracket marker, new pipeline step, new module, response-shape additive change, governance hook. Highest risk.

## Standing Rules (per `prompts/BUILDER-EXECUTION-PLAN.md`)

- **BF-274** — `multi_replace_string_in_file` is dangerous when replacement blocks are adjacent. Prefer single `replace_string_in_file` for adjacent edits. **CRITICAL for AD-730-3 Section 5** (DmReplyContext + pipeline step tuple + build_response live within 50 lines of each other).
- **BF-280** — Production code paths reachable from the FastAPI runtime MUST NOT use `asyncio.create_subprocess_*`. Use `subprocess.Popen + loop.run_in_executor`. **Not applicable in this wave** — both ADs use `httpx`/in-process state only.
- **BF-282** — Windows subprocess binary capture: tempfile, not stdout. **Not applicable in this wave**.
- **BF-286 / BF-287** — Use real Pydantic config (`SystemConfig()`) and real registry/store fixtures in tests, not MagicMock at substrate boundaries. **Critical for AD-730-3 AttachmentStore tests** — use hand-rolled `_FakeAttachmentStore` (in-memory dict). Critical for AD-740 — use hand-rolled `_FakeRuntime` with a real `collections.deque` for divergence history.
- **AD-722b-1a / BF-287** — Phantom-via-MagicMock anti-pattern: MagicMock auto-creates any attribute, so `mock.foo = X` while production reads `obj.foo` passes silently. Tests in this wave use real `SystemConfig()` and dataclass fakes throughout.
- **AD-738b** — UI prompts MUST gate on `cd ui; npm run build` AND `cd ui; npx vitest run`. **AD-740 = no UI. AD-730-3 = no UI in v1** (HXI render filed as forward marker AD-730-3-4 if absent).
- **AD-731** — Image/file bytes flow through `AttachmentStore.write(sha, blob, mime)` SHA-256 refs. Bus carries refs; store carries bytes. **CRITICAL for AD-730-3** — every byte of generated image goes through the store. NO inline base64 in `IntentMessage.params`, NO inline base64 in `build_response()`'s output. Source-scan tests in AD-730-3 enforce this.
- **AD-732 + 8-guard catalog** (Wave 153, user-memory 2026-05-12) — when adding a new LLM tier, EVERY tier-enumerating piece of infrastructure must explicitly handle the new tier or explicitly bypass. **CRITICAL for AD-730-3** — prompt enumerates all 8 surfaces in a table; builder MUST verify each. BF-269 (no fallback), BF-272 (no cache), BF-273 (no ModelRouter routing) all apply.
- **BF-274 working-tree check** — Run `git diff --numstat HEAD | sort -k2nr | head -5` at session start. Any tracked file with >200 deletions you didn't author → STOP and surface. The 2026-05-08 wipe is the canonical lesson.
- **AD-722c-3** — Forward markers must have TECHNICAL triggers (not "when convenient"). AD-740-1/-2/-3 and AD-730-3-1 through -6 all have explicit triggers in the prompts.
- **AD-721i-1** — License whitelist (CC0/MIT/Apache/BSD/CC-BY/MPL-2.0). **0-line license diff in both ADs** — verified: no new pip deps, no new npm deps.
- **`gh issue create` / `gh issue close` body** must NOT contain `{`, `}`, or `\` literally (PowerShell parsing trap). Describe errors structurally.
- **Pidfile safety** (user-memory 2026-05-12 BF-275) — never broadcast-kill python.exe by path. Use `scripts/kill-stale-pytest.ps1` which reads `data/probos.pid` and excludes the live runtime.

## License Posture (per Captain rule 2026-05-09)

- **AD-740:** 0-line license diff. stdlib only (`collections.deque`, `logging`). No new dep.
- **AD-730-3:** 0-line license diff. `httpx` already resident (Wave 162). `base64`/`hashlib`/`logging`/`re`/`asyncio` stdlib. **OpenAI Images API v1 wire shape** is vendor-neutral — used by openrouter, litellm, AUTOMATIC1111 / ComfyUI / SD.next OpenAI-compat adapters. No SDK dep on `openai` package.

## Pre-Flight Checklist

Before dispatching Builder:

1. ✅ Architect drafted both prompts with verified-against-codebase grep evidence.
2. ✅ AD numbering verified — AD-740 chosen because AD-739a is taken (Captain Card per-department overlay forward marker).
3. ✅ Issue bodies (#664, #633) re-read and Architect considerations surfaced in prompts.
4. ✅ Eight-guard catalog enumerated in AD-730-3 (table + acceptance test list).
5. ⬜ Builder runs working-tree integrity check (`git diff --numstat HEAD | sort -k2nr | head -5`). Tree must be clean apart from any architect-authored prompts/Reviews artifacts.
6. ⬜ Builder runs full pre-wave gate: `pytest tests/ -q -n 4 --dist=loadfile`. Note the baseline test count.
7. ⬜ AD-740 dispatched.
8. ⬜ AD-740 full gate runs green (+8 pytest, ≥7 strict increase allowing one pre-existing flake budget).
9. ⬜ AD-740 commit + `gh issue close 664`.
10. ⬜ AD-730-3 dispatched.
11. ⬜ AD-730-3 full gate runs green (+14 to +18 pytest depending on eight-guard test inclusion).
12. ⬜ AD-730-3 commit + `gh issue close 633` + GH forward-marker issues filed for AD-730-3-1 through AD-730-3-5 (and -6/-7 if Section 6/8 fall back to forward markers).
13. ⬜ `prompts/wave-plan.yaml` Wave 169 entry updated to `status: shipped`.
14. ⬜ Archive both prompts to `prompts/archive/`.
15. ⬜ `prompts/wave-orchestrator-state.json` advanced to `current_stage: shipped`.

## Per-Commit Quality Gates

After EACH AD commit:

```powershell
cd d:\ProbOS
.\.venv\Scripts\Activate.ps1
pytest tests/ -q -n 4 --dist=loadfile
```

If a parallel-mode test fails, retry the failing file at `-n 0`:

```powershell
pytest tests/<failing_file>.py -q -n 0
```

If it passes serially, classify as environmental — document in the build report and proceed. If it fails serially, follow the triage decision tree in `prompts/BUILDER-EXECUTION-PLAN.md` (`git stash` Builder changes, rerun, etc.).

## Hard-Stop Conditions (Builder MUST surface to Architect)

1. **AD-740 Section 3 reveals signature drift** on `check_own_render` / `_working_memory` / `record_observation`. Do NOT fabricate the call.
2. **AD-730-3 Section 5 forces step renumbering** (the prompt uses letter-suffix `step_4c_` precisely to AVOID this). If renumbering is unavoidable, hard-stop.
3. **AD-730-3 Section 6 episodic API mismatch** — if no clean `store_episode` signature exists, file AD-730-3-6 forward marker and SKIP the section. NOT a hard-stop; document the path.
4. **Eight-guard audit fails** — if any of the 8 tier-enumerating surfaces in AD-730-3 cannot be touched without architectural changes, hard-stop.
5. **Working-tree wipe detected** at session start (>200-line tracked deletions Builder didn't author).
6. **Phantom-via-MagicMock found in existing tests** that Builder edits transitively — flag for follow-on hygiene AD but do NOT block this wave.
7. **License diff > 0 lines** — if any new pip/npm dep is silently introduced, hard-stop and surface for Captain license ruling.

## Wave-Specific Reminders (known false positives in these prompts)

- **AD-740 Section 1**: `affect_drift_threshold` defaults to 0.7 (issue specified "default ~0.7"); operators can override per-call OR globally via `AvatarsConfig`. Not a deviation from issue.
- **AD-730-3 Section 5**: the new step is named `step_4c_image_gen_parse` (not `step_5_*`) **specifically** to avoid the trailing 5-step renumber that AD-728d did. Reviewers tempted to "fix" the suffix MUST resist — letter suffix is intentional architectural choice for additive insertion.
- **AD-730-3 Section 6**: anchored episode write is fallback-OK to forward marker. Don't block on it.
- **AD-730-3 Section 8**: HXI rendering of agent-emitted `attachment_ids` is explicitly out-of-scope. Don't extend the HXI even if it looks like a 5-minute change.
- **AD-730-3 wellness review**: v1 is logger.WARNING only. Interactive Captain ACK is AD-730-3-1 territory. Don't over-build governance.

## Post-Sweep Procedures

After both ADs ship:

1. Update `PROGRESS.md` line listing both AD-740 and AD-730-3 entries (full detail with file list, test count, invariants).
2. Update `progress-era-5-unification.md` with full AD entries.
3. Update `DECISIONS.md` with full AD entries including the 8-guard catalog table reproduced for AD-730-3.
4. Update `docs/development/roadmap.md` Bug Tracker / Forward Markers section with: AD-740-1, AD-740-2, AD-740-3, AD-730-3-1, AD-730-3-2, AD-730-3-3, AD-730-3-4, AD-730-3-5 (and -6/-7 if filed).
5. File GH forward-marker issues for each: AD-740-1/-2/-3 and AD-730-3-1/-2/-3/-4/-5 (per Captain rule 2026-05-08: forward markers materialise as filed issues before wave close).
6. Archive `prompts/ad-740-drift-detector.md` and `prompts/ad-730-3-agent-image-generation.md` to `prompts/archive/`.
7. Archive this dispatch file to `prompts/archive/WAVE-169-DISPATCH.md`.
8. Mark `prompts/wave-plan.yaml` Wave 169 `status: shipped`.
9. Advance `prompts/wave-orchestrator-state.json` to next wave.

## Architect Sign-Off

Both prompts have undergone verify-first review:

- **Pass 1 (grep against live codebase):** every asserted API/method/signature/constant in both prompts has been grep-verified against HEAD. Specific verifications:
  - `_LLM_TIERS` constant location (line 31, llm_client.py) — verified.
  - `_TIER_ORDER` exclusion semantics (line 38) — verified.
  - `class AttachmentStore` Protocol (line 14, attachments/store.py) + `write(sha, blob, mime)` signature — verified.
  - `runtime.divergence_history` lifecycle (lines 557-577, divergence_detector.py) + `DivergenceHistoryEntry.result.match_score` field (lines 160-167 + 183-189) — verified.
  - `class DmReplyContext` (line 28, reply_pipeline.py) + `step_4_self_check_parse` (line 268) + `build_response` (line 505) — verified.
  - `extract_self_check` / `strip_self_check` adjacency pattern (lines 207-227, dm_sanity_gate.py) — verified.
  - `class AvatarsConfig` (line 1183, config.py) + `render_self_check_enabled` (line 1301) — verified.
  - `_validate_and_store_attachment` helper (line 621, chat.py) — verified.
  - `is_vision_tier_configured` + `VISION_UNCONFIGURED_MESSAGE` import surface (chat.py:345-347, agents.py:1849-1851) — verified.
  - `AgentChatRequest` shape (api_models.py:146) + absence of `AgentChatResponse` Pydantic model (the agent chat reply is currently an untyped dict returned from `build_response`) — verified.
  - AD-739 highest shipped (PROGRESS.md line 4) + AD-739a taken (Captain Card per-department overlays) — verified.

- **Pass 2 (post-fix re-read):** prompts read top-to-bottom for internal consistency, scope creep, missing acceptance criteria. No major rewrites required.

**GATE 1 verdict: APPROVED.**
