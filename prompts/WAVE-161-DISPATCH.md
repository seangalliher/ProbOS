# Wave 161 Dispatch — Forward-marker follow-ups

**Status:** ready
**Date drafted:** 2026-05-15
**Wave size:** 5 ADs, ~10h estimated.
**Issues to close:** #655, #656, #625, #620 (+ duplicate #623), #598.
**License posture:** All five ADs are pure internal changes — no new pip/npm deps. `pyproject.toml`, `ui/package.json`, `.gitignore` stay untouched.

---

## Inputs (read-first)

1. `.github/copilot-instructions.md` — engineering principles, layer discipline, anti-pattern catalog.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules, gate commands, hard-stop classes.
3. `prompts/review-criteria.md` — review tier format.
4. This file.
5. The 5 per-AD prompts (listed below).
6. `PROGRESS.md` for current AD numbering. **Verified at draft time: highest AD on `main` = AD-738. Wave 161 sub-ADs (`-1`, `-2`, `-2-1`, etc.) do NOT claim new AD-NNN numbers — they all hang off existing parent ADs.**

---

## Prompts in this wave (build order)

| Order | Prompt | Closes | Touches | Est. tests |
|-------|--------|--------|---------|------------|
| 1 | `prompts/ad-723a-2-wr-sensorium-consumer.md` | #625 | `src/probos/cognitive/cognitive_agent.py` | +6 pytest |
| 2 | `prompts/ad-730-2-1-image-budget-persistence.md` | #656 | `src/probos/attachments/{image_policy.py, image_budget_store.py(new)}`, `runtime.py`, `config.py` | +5 pytest |
| 3 | `prompts/ad-721d-4-avatar-proposal-history-persist.md` | #620 (+#623 dup) | `src/probos/avatars/proposal_history.py`, `runtime.py`, `config.py` | +5 pytest |
| 4 | `prompts/ad-722b-1-telemetry-crew-scope-auth.md` | #598 | `src/probos/routers/{auth.py(new), agents.py}`, `config.py` | +8 pytest |
| 5 | `prompts/ad-722b-4a-fleet-hook-integration.md` | #655 | `ui/src/{components/CognitiveCanvas.tsx, store/useStore.ts, __tests__/}` | +4 vitest |

**Build order rationale:**
- ADs 1-4 are server-only (pytest). AD 5 is UI-only (vitest + `npm run build`). Building 1-4 first keeps gate semantics simple; AD 5 closes the wave with the UI gate.
- AD 4 (auth) is **CONDITIONAL** — see its prompt for the scope flag. If the WS handshake auth pattern proves fragile, split into AD-722b-1 (HTTP) + AD-722b-1a (WS) and surface to Architect mid-wave.
- ADs are otherwise independent. No cross-AD test dependencies.

---

## Standing rules (per-prompt — embedded but restated here)

| Rule | Summary |
|------|---------|
| **BF-274** | Use single `replace_string_in_file` for adjacent edits; do NOT use `multi_replace_string_in_file`. Three vision-pipeline regressions in 24h traced to this tool's adjacent-context heuristic. |
| **BF-280** | No `asyncio.create_subprocess_*` in runtime paths. ProbOS uses `WindowsSelectorEventLoop`; async subprocess raises `NotImplementedError`. Use the `shell_command.py:_run_sync` pattern. (None of the Wave 161 ADs introduce subprocess calls — flagged here for the standing rule.) |
| **BF-282** | No binary subprocess output captured via stdout on Windows. Write to tempfile. (None of the Wave 161 ADs introduce binary subprocess output.) |
| **BF-286** | Test scaffolding mirrors production subprocess shape. (N/A this wave.) |
| **AD-738b** | UI gate = `cd ui ; npx vitest run` AND `cd ui ; npm run build`. Vitest skips `tsc -b`; Vitest greens are NOT a build proof. |
| **AD-722c-3** | Forward markers use TECHNICAL triggers, NOT commercial-tier language. ("When AD-X ships," "when N callers exist," "when file size > Y" — NOT "when Enterprise tier needs X.") |
| **AD-731** | Image attachments still flow through AttachmentStore SHA-256 refs. Wave 161 ADs touch BUDGET / TELEMETRY / WIRING — none touch the attachment payload path itself. |
| **No emoji** | All log messages and any new UI strings are ASCII / inline SVG. |

---

## Per-AD hard-stops (wave-specific)

- **AD-722b-4a** — If integrating the hook breaks tooltips, bloom position, or canvas raycasting → **STOP** (HXI Canvas regression class). Re-run manually after integration; surface if any regress.
- **AD-722b-1** — Auth must work for BOTH HTTP and WebSocket. If WS auth pattern differs significantly from HTTP (Starlette query_params not populated pre-accept, close-code semantics inconsistent), **may need to split** into AD-722b-1 (HTTP) + AD-722b-1a (WS) — surface BEFORE making that split call.
- **AD-723a-2** — Must not regress AD-723a-1 DM consumer tests. Run `pytest tests/test_ad723a_1_consumer_migration.py -v -n 0` immediately before and after the change.

---

## Pre-flight checklist (run BEFORE any per-prompt work)

```powershell
# 1. Clean working tree (untracked .pyc / __pycache__ ok; no tracked changes).
git status

# 2. Verify pidfile presence — Builder must avoid hitting the live runtime
#    if Captain has ProbOS running. If data/probos.pid exists, the kill
#    script will skip the live PID. See scripts/kill-stale-pytest.ps1.
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
```

If pre-flight is dirty (failures NOT in the known-flake set, or `git status` shows untracked tracked-file modifications you didn't make), STOP and surface to Architect. Working-tree integrity is a known failure class (2026-05-08 lesson).

---

## Per-prompt workflow

For each AD in order:

1. **Read the prompt end-to-end** (including Verified Against Codebase footer — confirm grep evidence still matches HEAD).
2. **Apply changes** per the SEARCH/REPLACE blocks and new-file specs.
3. **Run focused gate**: `pytest tests/test_adNNN*.py -v -n 0` for the AD's tests.
4. **Run full parallel gate**: `pytest tests/ -q -n 4 --dist=loadfile`.
5. **For UI-touching prompts** (only AD-722b-4a in this wave): also run `cd ui ; npx vitest run` AND `cd ui ; npm run build`.
6. **Commit** with message format: `AD-NNN-suffix: <one-line summary> (Wave 161)`. Body lists test count delta and closed issue.
7. **Update tracking**:
   - `PROGRESS.md` "Wave 161 in flight" block (add new bullet).
   - `DECISIONS.md` (append AD entry).
   - `docs/development/roadmap.md` forward markers per the prompt's "Forward markers" section.
8. **Move on** to the next AD.

---

## Per-commit quality gates

Every commit MUST satisfy:

- [ ] Focused test file green at `-n 0` (test isolation proved).
- [ ] Full parallel gate `pytest -q -n 4 --dist=loadfile` green.
- [ ] For UI commits: `npm run build` green (NOT just vitest).
- [ ] No new `multi_replace_string_in_file` usages.
- [ ] No new `asyncio.create_subprocess_*` usages.
- [ ] No new emoji in production code paths.
- [ ] Commit message references the AD AND the closed issue.
- [ ] Working tree is clean except the AD's intended changes (run `git diff --stat` before committing — extra changes are MORE concerning than missing ones, per the BF-278 lesson).

---

## Hard-stop conditions (wave-wide)

Halt and surface to Architect when any of these fire:

1. **Phantom API surfaces in implementation** — a method/attribute the prompt asserts doesn't actually exist at HEAD. Apply the verify-first check before claiming.
2. **Architectural change required** — Builder discovers the AD as drafted requires modifying a protocol (`BaseAgent`, `IntentMessage`, `Protocol`-typed interface), or violates the layer discipline (Substrate ← Cognitive, Experience → Cognitive internals).
3. **Tracked-file modifications NOT made by Builder** — `git status` shows tracked files modified that the Builder did not author. This is a stop-the-line event per the 2026-05-08 lesson.
4. **Live runtime kill risk** — any `Stop-Process`/`taskkill`/`Kill-Process` command in any operation. Use `scripts/kill-stale-pytest.ps1` with pidfile exclusion. NEVER `Get-Process python | Stop-Process` while the Captain may have ProbOS running.
5. **Vision pipeline regression** — if any test in `tests/test_ad732_*.py` or any vision-tier test starts failing during this wave, STOP. The 10-guard vision stack is load-bearing.
6. **AD-723a-1 regression** — Wave 161 explicitly includes AD-723a-2 which sits next to AD-723a-1. If `tests/test_ad723a_1_consumer_migration.py` fails after the AD-723a-2 build step, this is a primary regression gate and triggers immediate revert.

---

## Wave-specific reminders

- **AD-721d-4 issue numbering** — Both #620 and #623 exist on GH with identical title/body. The prompt targets #620; close #623 as duplicate in the same commit message (`Closes #620. Duplicate of #623 — also closed.`).
- **AD-722b-1 substrate framing** — This is the FIRST time the codebase ships an auth dep. The pattern this AD establishes (default-OFF, `hmac.compare_digest`, single dep file at `routers/auth.py`) becomes the template for future waves. If anything about the pattern feels off in review, surface BEFORE shipping — substrate is harder to change than feature code.
- **AD-722b-4a / SensoriumLayer trap** — Wave 160 retrospectives noted a phantom IDENTITY trap involving `SensoriumLayer` (PROPRIOCEPTION/INTEROCEPTION/EXTEROCEPTION). The Wave 161 task brief reminded about this. **Verification: SensoriumLayer is a real enum at `cognitive_agent.py:54` with those exact members** — the trap is using it where `SensoriumPath` (the path enum at line 62) is wanted. AD-723a-2's prompt explicitly calls this out. Don't import SensoriumLayer in any Wave 161 commit.

---

## Build groups (DAG)

```
[1] AD-723a-2 ──┐
[2] AD-730-2-1 ──┤
[3] AD-721d-4 ──┼─→ [4] AD-722b-1 ──→ [5] AD-722b-4a
[4 surfaces      │
   scope first]  │
```

1-3 are independent server-only changes. 4 (auth) is a substrate change that needs scope-confirm before code lands. 5 (UI fleet hook) closes the wave under the UI gate.

---

## Post-sweep procedure

After all 5 ADs ship:

1. Mark `prompts/wave-plan.yaml` Wave 161 `status: done` and list `prompt_paths`.
2. Archive prompts to `prompts/archive/` per the standing pattern.
3. Update `PROGRESS.md` header — increment shipped wave, refresh test counts, move Wave 161 from "in flight" to "shipped" block.
4. Update `docs/development/roadmap.md` with the 8 forward markers filed (2 from AD-722b-4a, 2 from AD-730-2-1, 2 from AD-723a-2, 2 from AD-721d-4, 4 from AD-722b-1).
5. Commit with message `wave-plan: mark Wave 161 shipped + archive prompts (~5 ADs)`.
6. Push.

---

## Build report (at wave close — fill in)

| Item | Value |
|------|-------|
| ADs shipped | 5 (AD-723a-2, AD-730-2-1, AD-721d-4, AD-722b-1, AD-722b-4a) |
| Issues closed | #625, #656, #620, #623 (dup), #598, #655 |
| Pytest delta | +24 (TBD at ship — sum of per-AD estimates: 6+5+5+8 = 24) |
| Vitest delta | +4 (AD-722b-4a only) |
| Forward markers filed | ~12 (TBD) |
| New BFs filed | TBD |
| Commit count | 5 + 1 (wave-close) = 6 |
| Quarantines added | 0 expected (none of the Wave 161 ADs touch known-flaky areas) |

---

## Done definition

- All 5 prompts shipped under the per-AD acceptance criteria.
- Full pytest gate green at `-n 4 --dist=loadfile`.
- Full vitest gate green AND `npm run build` green.
- All 6 issues closed.
- Working tree clean.
- `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`, `prompts/wave-plan.yaml` all updated.
- Wave 161 commit pushed to `origin/main`.
