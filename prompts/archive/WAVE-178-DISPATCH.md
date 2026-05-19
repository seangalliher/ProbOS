# WAVE 178 — DISPATCH

**Drafted:** 2026-05-19
**Status:** GATE 1 (architect-only). Pass-1 complete. Awaiting Captain review.
**Posture:** **High-value architectural fork** — the **see → discuss → act** ladder that bridges ProbOS from agentic-perception (Waves 170-177) into agentic-action. This wave introduces the workstation → agentic collaboration loop the HXI vision (Design Principle #11) has been pointing at.
**Builder dispatch:** NOT in this turn. Architect-only draft.

## Slate

| # | AD | Closes | Tests | Build order |
|---|----|--------|-------|-------------|
| 1 | AD-733-2 | [#668](https://github.com/seangalliher/ProbOS/issues/668) (narrowed) | +8 pytest, +5 vitest | First (introduces `source="screen"` on `vision_observation`; AD-744 reuses) |
| 2 | AD-744 | (new — filed at wave close) | +8 pytest, +6 vitest | Second (introduces DM-attached share-frame contract; AD-745 consumes) |
| 3 | AD-745 | (new — filed at wave close) | +18 pytest, +6 vitest | Third (action handoff substrate; reuses AD-744 frame contract + AD-706 BrowserTool) |

Total: **+34 pytest, +17 vitest.** **Zero new pip deps.** **Zero new npm deps.** **0-line diff on all 5 license files** (`LICENSE`, `THIRD_PARTY_LICENSES.md`, `pyproject.toml`, `package.json`, `package-lock.json`).

## Highest current AD

**Before Wave 178:** AD-743 (top-level, shipped Wave 176).

**Confirmed via:**

```
Select-String -Path PROGRESS.md,DECISIONS.md,docs\development\roadmap.md,prompts\wave-plan.yaml \
  -Pattern "AD-74[0-9]|AD-75[0-9]|AD-76[0-9]" -AllMatches | Sort-Object -Unique
  → AD-740, AD-741, AD-742, AD-743 (highest is AD-743)
```

**Wave 178 assignments:**

- **AD-733-2** — existing forward marker (#668 OPEN since Wave 170); narrowed scope (multi-camera already shipped via AD-742c bound_agent_ids).
- **AD-744** — NEW top-level. Interactive share-to-agent.
- **AD-745** — NEW top-level. Conversation → action handoff (browser scope v1).

**After Wave 178:** Highest AD = **AD-745**. Two new top-level ADs filed. Seven new forward markers from AD-745 (AD-745-1..7), three new forward markers from AD-744 (AD-744-1..3), two new forward markers from AD-733-2 (AD-733-2-1..2).

## Drafted prompts

| # | Prompt |
|---|--------|
| 1 | `prompts/ad-733-2-passive-screen-sensing.md` |
| 2 | `prompts/ad-744-interactive-share-to-agent.md` |
| 3 | `prompts/ad-745-conversation-action-handoff.md` |

## Research deliverable

`prompts/RESEARCH-wave-178.md` — prior-art table covering 13 projects (Anthropic computer-use, browser-use, OpenAI Operator, OmniParser, SeeAct, Playwright MCP, Khoj, Open Interpreter, WebArena/VisualWebArena, CogAgent/ShowUI/LLaVA-Next, MultiOn/Adept/Rabbit, LiveKit/Pipecat, MakeHuman/VRoid/UX references). License-aware absorption matrix per project. Six architectural decisions surfaced with rationale. Top 3 absorption sources + top 3 anti-patterns. Four open questions for Captain.

## Cross-AD dependency graph

```
AD-733-2  ──introduces──▶  source="screen" on vision_observation
                                      │
                                      ▼
AD-744    ──introduces──▶  DM-attached share-frame contract
                          (force=true + agent_ids + source=screen)
                                      │
                                      ▼
AD-745    ──introduces──▶  [ACTION: ...] bracket marker + dispatch
                          (BrowserTool + tier 1/2/3 ladder + episodes)
```

**Build order: 1 → 2 → 3, strictly serial.** Each AD's contract is consumed by the next.

## Build order rationale

1. **AD-733-2 first.** It adds the `source` form field to `POST /api/perception/camera/frame` and `params["source"]` on the `vision_observation` IntentMessage. AD-744 consumes both verbatim.
2. **AD-744 second.** It introduces the convention that a frame can be both supervisor-bypassed (`force=true`) AND agent-bound (`agent_ids`) — the DM-attached frame contract. AD-745's dispatch path treats every Captain-shared frame as a potential action precursor.
3. **AD-745 third.** Highest-risk file is `src/probos/cognitive/dm/pipeline.py` (load-bearing). Building last means the previous two prompts have already exercised the perception substrate end-to-end and confirmed `force=true` + `agent_ids` propagate correctly.

## Pre-flight gate (Builder MUST run before each prompt)

```pwsh
git status --porcelain
# expect: clean working tree (only the Wave 178 prompts + tracker
# updates dirty before commit; clean after each prompt's commit)

git log --oneline -1
# expect: HEAD = "wave-plan: queue Wave 178 (AD-733-2 + AD-744 + AD-745) + prior-art research"

.\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select -Last 3
# baseline from PROGRESS.md line 4 at wave start; the gate is to confirm the
# baseline is green before each prompt.

cd ui; npx vitest run 2>&1 | Select -Last 3
cd ui; npm run build
# both must exit 0 BEFORE wave starts (BF-279 stale-bundle baseline).
```

Per-prompt pre-flight: each prompt has its own Verified-Against-Codebase block with grep anchors. Builder MUST verify each anchor at HEAD before locking edits. **Hard-stop on any missing anchor.**

## Hard-stop conditions

Builder must stop and surface (not work around) on any of:

1. Pre-flight grep finds a missing anchor on any prompt.
2. Pre-flight gate fails — baseline pytest OR vitest OR `npm run build` not green.
3. New pip dep introduced (license diff non-zero on `pyproject.toml` or `THIRD_PARTY_LICENSES.md`).
4. New npm dep introduced (license diff non-zero on `package.json` / `package-lock.json`).
5. AD-731 invariant violated — image bytes leak into any RPC message (rerun source-scan after each commit).
6. AD-541b anchor missing on any executed action path (AD-745).
7. Captain-ACK gate bypassed on any tier-2+ verb (AD-745).
8. Action executes on Captain's logged-in browser profile instead of BrowserSession's isolated context (AD-745 safety invariant).

## Architectural decisions surfaced (NOT auto-resolved — Captain decides at wave close)

Per RESEARCH-wave-178.md §11:

1. **AD-721j re-scope.** Re-scope to "Blender as a target application of AD-745-1 DesktopActionTool"? Default rec: yes.
2. **OS-scope honest-degrade v1.** When Captain shares non-browser surface, AD-745 v1 describes-only? Default rec: yes; OS scope = AD-745-1.
3. **Consensus on destructive actions.** Multi-agent quorum on destructive-pattern URL matches, OR Captain-ACK-only for v1? Default rec: Captain-ACK only; quorum = AD-745-2.
4. **Per-action vs per-plan ACK.** v1 ships per-action; multi-step plans = AD-745-6 forward marker.

## Top concern per AD

| AD | Top concern |
|----|-------------|
| AD-733-2 | The per-source rate-bucket key change (from `session_id` → `(session_id, source)`) must be verified byte-compatible with the existing AD-733 camera flow. **One test specifically asserts pure-camera throughput unchanged.** |
| AD-744 | The frame uploaded with `session_id=share_<agentId>_<ms>` MUST NOT collide with AD-733a's per-session working-memory bucket OR overwrite the AD-733c-1 force-describe cache. **Tested explicitly.** |
| AD-745 | The `[ACTION:]` bracket marker must NOT trigger on adversarial DM text (e.g., the Captain pastes a JSON snippet for reference). Parser regex must be strict (`[ACTION: {...}]` literal prefix); malformed JSON skipped silently with WARNING. Forward marker AD-745-8 if Captain reports false-positive triggers. |

## Safety / consensus posture summary

| Surface | requires_consensus | Captain ACK | Rationale |
|---------|-------------------|-------------|-----------|
| AD-733-2 `vision_observation` source=screen | False | None (passive sensor) | Same as camera. Sensor input, not destructive. |
| AD-744 share frame | False | Implicit (Captain clicks "Share") | Captain explicitly invokes the share. |
| AD-745 tier-1 verbs (screenshot/state/scroll/mouse_move) | False | None | Observation-only. |
| AD-745 tier-2 verbs (click/type/drag/key_combo non-destructive/mouse_button) | False | In-thread ACK card | Existing AD-706e UX. |
| AD-745 tier-3 verbs (compute_use_click/eval_js/upload_file/download/destructive key_combo) | False (v1) | Modal confirmation | Captain-ACK floor; AD-745-2 forward marker promotes to quorum. |
| AD-745 destructive-URL pattern match | False (v1) | Modal confirmation | Forces any verb to tier-3; AD-745-2 promotes to quorum. |

## Tracker files updated this commit

1. `prompts/RESEARCH-wave-178.md` — NEW.
2. `prompts/ad-733-2-passive-screen-sensing.md` — NEW.
3. `prompts/ad-744-interactive-share-to-agent.md` — NEW.
4. `prompts/ad-745-conversation-action-handoff.md` — NEW.
5. `prompts/WAVE-178-DISPATCH.md` — NEW (this file).
6. `prompts/wave-plan.yaml` — Wave 178 block appended (status: drafting).
7. `PROGRESS.md` — Wave 178 in-flight block inserted at top.
8. `docs/development/roadmap.md` — 3 new rows (AD-744, AD-745) + AD-733-2 row updated.
9. **NO change to DECISIONS.md** (BUILDER-EXECUTION-PLAN convention — DECISIONS append happens at ship time, not draft time).

## Final report (per user spec)

1. **Highest AD.** Before: AD-743. After (post-ship Wave 178): AD-745. Two new top-level ADs (AD-744, AD-745). One existing forward marker (AD-733-2) consumed.
2. **Prior-art top 3 absorption + top 3 anti-patterns.** Sources: Anthropic computer-use (MIT quickstart), browser-use (MIT), OmniParser/SeeAct (MIT/Apache). Anti-patterns: agent-emits-raw-executable-code, single-tool-agent god class, hidden cross-surface context without operator visibility. License-clean across the board; zero deps land this wave.
3. **Six architectural decisions** documented in RESEARCH-wave-178.md §7: action grammar = AD-706 `_HANDLERS` reuse; grounding = DOM-first + compute_use_click fallback (v1) + SOM forward marker; tool agents = BrowserTool only in v1 (DesktopActionTool deferred); scope = browser only; sandbox = BrowserSession isolated context; per-agent screen scoping = sibling `useScreenMultiplexerStore`; AD-721j = re-scope to AD-745 consumer.
4. **Three prompts drafted** under `prompts/`.
5. **Top concern per AD** documented above.
6. **Cross-AD dependency graph** documented above.
7. **Overlap with #538 / AD-721j**: re-scope recommended (RESEARCH §11 q1).
8. **Safety/consensus matrix** documented above.
9. **Tracker files updated** documented above.
10. **Commit SHA**: filled in after `git commit && git push`.
11. **Blockers**: NONE for drafting. Four Captain decisions surfaced (RESEARCH §11) that should land before Builder dispatch; none of them block GATE 1 review.

---

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`, especially the consensus + minimal-authority + reversibility requirements for destructive screen-action intents.**
