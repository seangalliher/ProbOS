# Wave 162 Dispatch — Doubled forward-marker batch

**Status:** ready
**Date drafted:** 2026-05-15
**Wave size:** 10 ADs, ~10h estimated (doubled from Waves 160/161 after both shipped in ~half their estimates).
**Issues to close:** #657, #562, #645, #611, #610, #602, #642, #644, #588, #618.
**License posture:** **9 of 10 ADs are zero-dep.** AD-720a-1 (#562) ADDS three permissive pip deps: `pypdf>=4.0` (BSD-3-Clause), `python-docx>=1.1` (MIT), `openpyxl>=3.1` (MIT). All Apache-2.0-compatible. No copyleft. Captain approval required at acceptance.

---

## Inputs (read-first)

1. `.github/copilot-instructions.md` — engineering principles, layer discipline, anti-pattern catalog.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules, gate commands, hard-stop classes.
3. `prompts/review-criteria.md` — review tier format.
4. This file.
5. The 10 per-AD prompts (listed below).
6. `PROGRESS.md` for current AD numbering. **Verified at draft time: highest AD on `main` = AD-739. Wave 162 sub-ADs (`-1`, `-2`, `-2-1`, `-1a`, etc.) do NOT claim new AD-NNN numbers — all hang off existing parent ADs (722a, 722b, 720a, 720d, 721d, 722e, 729, 706c). No collision with the AD-NNN namespace.** Highest BF = 286.

---

## Prompts in this wave (build order)

| Order | Prompt | Closes | Tier | Touches | Est. tests |
|-------|--------|--------|------|---------|------------|
| 1 | `prompts/ad-722b-1a-magicmock-test-cleanup.md` | #657 | hygiene | 8 test files, `routers/auth.py` | 0 net |
| 2 | `prompts/ad-729a-peer-observation-standing-orders.md` | #588 | docs/yaml | `config/standing_orders/{peer_observation.md(new), ship.md, counselor.md}` | +6 pytest |
| 3 | `prompts/ad-721d-2-counselor-mediated-avatar-revision.md` | #618 | feature | `agents/counselor.py`, `routers/agents.py`, `api_models.py`, `events.py`, `ui/CrewAvatarPopout.tsx` | +8 pytest, +2 vitest |
| 4 | `prompts/ad-722a-2-chain-path-divergence.md` | #611 | extension | `cognitive_agent.py`, `avatars/divergence_detector.py`, `events.py` | +10 pytest |
| 5 | `prompts/ad-720d-2-1-captain-vision-approval.md` | #645 | feature | `routers/agents.py`, `crew_profile.py`, `avatars/vision_proposal_history.py(new)`, `events.py`, `config.py`, `runtime.py` | +8 pytest |
| 6 | `prompts/ad-706c-1-browser-tool-visual-verify.md` | #642 | feature | `tools/browser/{actions.py, tool.py}`, `events.py` | +9 pytest |
| 7 | `prompts/ad-722a-1-vision-llm-intent-divergence.md` | #610 | feature | `avatars/vision_intent_divergence.py(new)`, `cognitive_agent.py`, `events.py`, `config.py`, `runtime.py` | +9 pytest |
| 8 | `prompts/ad-722e-2-vision-self-render-verify.md` | #644 | feature | `cognitive/self_render_verify.py(new)`, `cognitive/self_perception.py`, `events.py`, `config.py`, `runtime.py` | +9 pytest |
| 9 | `prompts/ad-720a-1-document-text-extraction.md` | #562 | feature + DEPS | `cognitive/text_extractor.py`, `routers/agents.py`, `config.py`, `pyproject.toml`, `THIRD_PARTY_LICENSES.md` | +12 pytest |
| 10 | `prompts/ad-722b-5-federation-telemetry-push.md` | #602 | **CONDITIONAL** | `federation/{bridge.py, telemetry_relay.py(new)}`, fleet broadcaster module, `config.py`, `runtime.py` | +8 pytest |

**Build order rationale:**

- **#1 (AD-722b-1a)** — pure refactor / anti-pattern cleanup. Warm-up. Zero risk.
- **#2 (AD-729a)** — docs + yaml only. Cheap. Unblocks AD-729 capability AD for future waves.
- **#3 (AD-721d-2)** — independent UX flow on shipped AD-721d-1 substrate. First feature.
- **#4 (AD-722a-2)** — extends shipped AD-722a (Wave 143) + AD-723 (Wave 144). Adds chain-path detection.
- **#5 (AD-720d-2.1)** — independent approval flow; mirrors AD-721d-1 pattern.
- **#6 (AD-706c-1)** — BrowserTool + vision tier verify. All primitives shipped. Independent.
- **#7 (AD-722a-1)** — first vision-LLM intent-divergence detector. Coordinates with #8.
- **#8 (AD-722e-2)** — vision-LLM self-render verify. Companion to #7. **Coordination point:** Both ADs touch vision-LLM rate-limit + AD-727 phrasing regex. Builder picks ONE pattern (recommended: independent class-dict per detector; consolidate in future AD-728 build).
- **#9 (AD-720a-1)** — adds 3 deps. Run after the eight zero-dep ADs to keep "no new deps" gate clean.
- **#10 (AD-722b-5)** — federation; most complex; transport-layer touch. **CONDITIONAL** — see prompt Section 0. If federation streaming primitive doesn't exist, STOP and write design doc instead.

**Inter-AD coordination notes:**

- **#7 + #8 share infrastructure.** Both introduce vision-LLM rate limiting at 3/hr/agent (AD-728 ceiling) and AD-727 phrasing-regex enforcement. Implement in #7 (lands first), reuse in #8 (lands second). If a clean shared primitive emerges, Builder may file forward marker AD-728-1 (shared `VisionLLMBudget` class) for a future wave.
- **#3 (AD-721d-2)** writes to AD-721d-4 sidecar (Wave 161). #5 (AD-720d-2.1) writes a SIMILAR sidecar (vision_proposal_history.py). Both mirror the AD-721d-4 atomic-write pattern — Builder should NOT factor out a shared base class in this wave (premature abstraction).
- **#9 (AD-720a-1)** is the only AD that modifies `pyproject.toml`. The `pip install -e .` step happens AFTER the eight zero-dep commits; if any subsequent gate fails, the failure is attributable to the dep additions.
- **#10 (AD-722b-5)** has a hard pre-flight gate. The Builder MUST grep `federation/bridge.py` for streaming-style primitives before any source edits. STOP/surface if absent.

---

## Standing rules (per-prompt — embedded but restated here)

| Rule | Summary |
|------|---------|
| **BF-274** | Single `replace_string_in_file` for adjacent edits. NEVER `multi_replace_string_in_file`. Three vision-pipeline regressions in 24h traced to this tool's adjacent-context heuristic (BF-274, BF-278). |
| **BF-280** | No `asyncio.create_subprocess_*` in runtime paths. ProbOS uses `WindowsSelectorEventLoop`; async subprocess raises `NotImplementedError`. Use the `shell_command.py:_run_sync` pattern. None of Wave 162's ADs introduce subprocess calls — flagged for the standing rule. |
| **BF-282** | No binary subprocess output captured via stdout on Windows. Write to tempfile. None of Wave 162's ADs introduce binary subprocess output. (AD-720a-1's pypdf/python-docx/openpyxl operate on `bytes` in-memory — no subprocess.) |
| **BF-286** | Test scaffolding mirrors production subprocess shape. (N/A this wave.) |
| **AD-738b** | UI gate = `cd ui ; npx vitest run` AND `cd ui ; npm run build`. Vitest skips `tsc -b`; Vitest greens are NOT a build proof. AD-721d-2 is the only UI-touching AD this wave. |
| **AD-722c-3** | Forward markers use TECHNICAL triggers, NOT commercial-tier language. ("When AD-X ships," "when N callers exist," "when file size > Y" — NOT "when Enterprise tier needs X.") Each prompt's forward markers (AD-720a-1-1, AD-722b-5a, AD-706c-1a, AD-722e-2a, AD-721d-2a/b, AD-720d-2.1a/b) follow this rule. |
| **AD-731** | Image bytes flow through AttachmentStore SHA-256 refs. AD-722a-1, AD-706c-1, AD-722e-2 all consume vision tier — all use refs, never inline base64. AD-720a-1's `bytes` argument is the ALREADY-RESOLVED-from-store payload; the bus path stays ref-only. |
| **No emoji** | All log messages and any new UI strings are ASCII / inline SVG. |
| **Real configs in tests** | Per AD-722b-1a (#1 this wave): NEW test files use `SystemConfig()` directly, not `MagicMock(spec=SystemConfig)`. |

---

## Per-AD hard-stops (wave-specific)

- **#1 (AD-722b-1a)** — If any of the 8 MagicMock removals breaks an unrelated test (full parallel gate red after a single migration), STOP and surface. The MagicMock fixture may have been hiding a real bug.
- **#3 (AD-721d-2)** — Vitest passes ≠ build passes. `cd ui ; npm run build` MUST green before commit. If button placement breaks CrewAvatarPopout tooltips / bloom / canvas raycasting, STOP (HXI canvas regression class).
- **#7 / #8** — If `_resolve_attachment_refs_for_openai` shape has drifted since BF-268, STOP and confirm with a live cat-image smoke against the running ProbOS instance (test_ad732_vision_tier passes alone is NOT sufficient — production-vs-test divergence is a real failure mode per memory entry 2026-05-12).
- **#9 (AD-720a-1)** — After `pip install -e .` confirms deps installed, run `pip show pypdf python-docx openpyxl` and capture the License: field for each. If ANY does not match BSD-3 / MIT / MIT, STOP and surface to Architect — PyPI metadata drift requires Captain re-approval.
- **#10 (AD-722b-5)** — Pre-flight Section 0 gate is HARD. If `FederationBridge` lacks streaming primitives, STOP and write design doc; do not invent transport.

---

## Pre-flight checklist (run BEFORE any per-prompt work)

```powershell
# 1. Working tree integrity (2026-05-08 lesson — large unauthored deletions = stop-the-line).
git status
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5

# 2. PID file presence — Builder must avoid hitting the live runtime if Captain has ProbOS running.
Get-Content data/probos.pid -ErrorAction SilentlyContinue

# 3. Parallel gate baseline.
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile

# 4. Serial gate baseline (known flakes only — do not fix here).
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_callsign_routing.py tests/test_ad719_chat_fanout.py -q -n 0

# 5. UI baseline.
cd ui
npx vitest run
npm run build
cd ..

# 6. AD numbering anchor confirmation.
# Builder confirms: highest AD-NNN in PROGRESS.md / DECISIONS.md / roadmap.md is AD-739.
# Wave 162's ADs are sub-IDs of existing parents — no new AD-NNN claimed.
```

If pre-flight is dirty (failures NOT in the known-flake set, or `git status` shows untracked tracked-file modifications you didn't make), STOP and surface to Architect.

---

## Per-prompt workflow

For each AD in build order:

1. **Read the prompt end-to-end** (including Verified Against Codebase footer — confirm grep evidence still matches HEAD).
2. **For #10 ONLY:** run Section 0 pre-flight CONDITIONAL gate before any source edits. STOP if federation streaming primitive absent.
3. **Apply changes** per the SEARCH/REPLACE blocks and new-file specs. BF-274 — single replace_string_in_file for adjacent edits.
4. **Run focused gate**: `pytest tests/test_adNNN*.py -v -n 0` for the AD's tests.
5. **Run full parallel gate**: `pytest tests/ -q -n 4 --dist=loadfile`.
6. **For UI-touching prompts** (#3 only this wave): also run `cd ui ; npx vitest run` AND `cd ui ; npm run build`.
7. **For #9 only**: `pip show pypdf python-docx openpyxl` license capture.
8. **Commit** with message format: `AD-NNN-suffix: <one-line summary> (Wave 162)`. Body lists test count delta and closed issue.
9. **Update tracking**:
   - `PROGRESS.md` "Wave 162 in flight" block (add new bullet).
   - `DECISIONS.md` (append AD entry).
   - `docs/development/roadmap.md` forward markers per the prompt's "Forward markers" section.
10. **Move on** to the next AD.

---

## Per-commit quality gates

Every commit MUST satisfy:

- [ ] Focused test file green at `-n 0` (test isolation proved).
- [ ] Full parallel gate `pytest -q -n 4 --dist=loadfile` green.
- [ ] For UI commits: `npm run build` green (NOT just vitest).
- [ ] No new `multi_replace_string_in_file` usages.
- [ ] No new `asyncio.create_subprocess_*` usages.
- [ ] No new emoji in production code paths.
- [ ] No new MagicMock(spec=SystemConfig) introductions (AD-722b-1a is removing them; do not re-introduce).
- [ ] Commit message references the AD AND the closed issue.
- [ ] Working tree clean except the AD's intended changes (`git diff --stat` before commit — extra changes are MORE concerning than missing ones, per BF-278 lesson).

---

## Pre-commit deletion sanity check (HARD RULE per BUILDER-EXECUTION-PLAN)

Before EVERY commit:

```powershell
git diff --numstat | Sort-Object {[int]$_.Split("`t")[1]} -Descending | Select-Object -First 5
```

If any tracked file shows >200 deletions you did not author, STOP. This is the 2026-05-08 incident class and was reinforced by the BF-274 / BF-278 sequence (multi_replace_string_in_file silent over-deletion).

---

## Post-sweep gate-3 close

After all 10 prompts commit:

1. Final full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile`.
2. Final UI gate: `cd ui ; npx vitest run ; npm run build`.
3. `THIRD_PARTY_LICENSES.md` includes the three AD-720a-1 entries.
4. Archive sweep: move all 10 prompt files + this dispatch into `prompts/archive/`.
5. Generate `prompts/build-reports/wave-162-report.md` with: AD count, test delta, dep additions, BF count (should be 0), forward markers filed.
6. Push.

---

## Forward markers expected to be filed during this wave

Per the Captain rule (memory entry 2026-05-08): every deferral MUST have an AD number AND a GitHub issue before wave close.

| Marker | Parent AD | Trigger (technical) |
|--------|-----------|---------------------|
| AD-720a-1-1 | AD-720a-1 | Flip `pdf_extraction_enabled` to True after operator feedback confirms quality |
| AD-720a-1-2 | AD-720a-1 | OCR pipeline for scanned PDFs (image-bearing pages) |
| AD-720d-2.1a | AD-720d-2.1 | HXI UI surface for Captain pending-approval list |
| AD-720d-2.1b | AD-720d-2.1 | Auto-deny TTL when Captain unresponsive for >N hours (autonomous-Captain mode) |
| AD-721d-2a | AD-721d-2 | `source` field on ProposalEntry if AD-721d-1 doesn't carry one |
| AD-721d-2b | AD-721d-2 | Per-domain mediator selection (Engineering officer mediates engineering avatars) |
| AD-722a-1a | AD-722a-1 | HXI surface for vision-divergence events in SelfImageTab |
| AD-722b-5a | AD-722b-5 | HXI surface to render remote agents with `origin_mesh_id` badge |
| AD-722e-2a | AD-722e-2 | HXI SelfImageTab surface for render-coherence observations |
| AD-706c-1a | AD-706c-1 | Journal aggregation for verification pass/fail rates (AD-674 calibration consumer) |
| AD-706c-3 | AD-706c-1 | Cloud vision API integration — Anthropic computer-use beta |
| AD-728-1 | #7+#8 | Shared `VisionLLMBudget` primitive (if pattern emerges) |

Each forward marker MUST be filed as a GH issue before wave close — `gh issue create` with the technical trigger, AD-722c-3 phrasing.
