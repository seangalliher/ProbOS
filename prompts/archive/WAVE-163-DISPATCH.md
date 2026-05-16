# Wave 163 Dispatch — Peer-Observation Governance Stack + HXI Completions + Planning + Browser Tool Classifier

**Wave size:** 11 ADs (10 buildable + 1 forward-marker-only)
**Highest AD before Wave 163:** AD-738 (per PROGRESS.md line 10). All Wave 163 AD numbers are pre-numbered forward markers — no new numbers needed.

## Theme

Two clusters + four independents.

- **Peer-observation cluster (5 ADs + 1 forward-marker):** AD-728 → AD-729 → AD-722a-6 → (AD-729b ∥ AD-729c) → AD-729d (documentation). Establishes the governance contract for cross-agent observation, the training/qualification gate, the pattern-monitoring layer, and the reinforcement-loop forward marker.
- **HXI completions (3 ADs):** AD-721d-2c finishes Wave 162's Counselor-mediated avatar revision UI; AD-719b adds the Copilot-style left rail; AD-719a makes multi-agent threads persistent under WardRoom.
- **Planning (1 AD):** AD-739 Captain Card v1.
- **Browser Tool augmentation (1 AD):** AD-706d LLM-driven tier classifier.

## Files written (12)

| # | File | Closes | Tests | Build group |
|---|---|---|---|---|
| 1 | `prompts/ad-728-vision-llm-mirror-function.md` | #586 | 12 pytest | A1 |
| 2 | `prompts/ad-729-peer-avatar-perception-umbrella.md` | #587 | 18 pytest | A2 |
| 3 | `prompts/ad-722a-6-cross-agent-divergence-observations.md` | #615 | 10 pytest | A3 |
| 4 | `prompts/ad-729b-peer-observation-boot-camp.md` | #589 | 8 pytest | A4 |
| 5 | `prompts/ad-729c-counselor-peer-observation-monitor.md` | #590 | 14 pytest | A4 |
| 6 | `prompts/ad-729d-peer-observation-reinforcement.md` | #591 | 0 (forward marker) | A5 |
| 7 | `prompts/ad-721d-2c-hxi-mediation-button.md` | #658 | 3 Vitest | B |
| 8 | `prompts/ad-719b-hxi-left-rail-agents-nav.md` | #547 | 5 Vitest | C |
| 9 | `prompts/ad-719a-wardroom-multi-agent-threads.md` | #546 | 6 pytest + 4 Vitest | D |
| 10 | `prompts/ad-739-captain-card-planning.md` | #649 | 10 pytest | E |
| 11 | `prompts/ad-706d-browser-tool-tier-classifier.md` | #519 | 10 pytest | F |
| 12 | `prompts/WAVE-163-DISPATCH.md` | (this file) | — | — |

**Estimated test count: ≈91 pytest + ≈18 Vitest = 109 new tests.**

## Build order

```
Build group A (peer-observation cluster — SEQUENCED):
  A1: AD-728 (primitive)
  A2: AD-729 (governance contract; depends A1)
  A3: AD-722a-6 (consumer; depends A1 + A2)
  A4: AD-729b + AD-729c (parallel; both depend A2)
  A5: AD-729d (forward-marker housekeeping; depends A2; no code)

Build groups B–F (independents — can run anytime, in parallel with each other):
  B: AD-721d-2c (HXI, depends on Wave 162 AD-721d-2 server endpoint)
  C: AD-719b (HXI shell refactor)
  D: AD-719a (WardRoom multi-agent threads)
  E: AD-739 (Captain Card v1)
  F: AD-706d (Browser Tool LLM classifier)
```

The peer-observation cluster MUST be built A1 → A2 → A3 → A4 (∥) → A5. The independents can be built in any order, and in parallel with A-group if Builder bandwidth allows.

## Pre-flight checklist

Before drafting any per-AD pull, the Builder MUST:

1. Confirm clean working tree: `git status` → no untracked tracked-file modifications. The 2026-05-08 working-tree-integrity lesson is non-negotiable.
2. Run the full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile` → all green.
3. Confirm UI gate clean: `cd ui ; npx vitest run` AND `cd ui ; npm run build` → both green (BF-279 / AD-738b).
4. Read the per-AD prompt fully, including the "Builder verify-first flags" section.
5. For each verify-first flag, run the indicated grep BEFORE drafting code. Phantom-API protection.

## Standing rules embedded in every prompt

Every prompt includes the Wave 163 standing block:

- **BF-274**: single `replace_string_in_file` for adjacent edits. NEVER `multi_replace_string_in_file` for adjacent SEARCH blocks.
- **BF-280**: NO `asyncio.create_subprocess_*` in runtime paths. Use `subprocess.Popen + loop.run_in_executor` (the `shell_command.py:_run_sync` pattern).
- **BF-282**: NO binary stdout capture on Windows. Use tempfile.
- **BF-286**: test scaffolding mirrors production subprocess shape (uses the same event-loop policy).
- **BF-287**: use public registry API (`registry.all()` / `registry.get(...)`), NOT `registry.agents`. Real `AgentRegistry` fixtures in tests, NOT MagicMock at the registry boundary.
- **AD-731 invariant**: image bytes flow through `AttachmentStore` SHA-256 refs. Never inline base64 in `IntentMessage.params`.
- **AD-722c-3**: forward markers use TECHNICAL triggers, NOT calendar dates.
- **AD-738b**: every UI-touching prompt requires per-commit `cd ui ; npx vitest run` AND `cd ui ; npm run build`. Vitest skips `tsc -b` — npm-build is the only way to catch the BF-279 class of stale-bundle drift.
- **Real Pydantic config fixtures**: every test uses `SystemConfig()` instances, NOT MagicMock at the config boundary. BF-287 retrospective.

## Per-commit gates

For each per-AD commit:

1. `pytest tests/ -q -n 4 --dist=loadfile` → green.
2. (UI-touching ADs only) `cd ui ; npx vitest run` → green.
3. (UI-touching ADs only) `cd ui ; npm run build` → green.
4. `git diff HEAD~1` review — confirm only the prompt's stated files are touched. NO scope creep.
5. Commit-count audit (existing orchestrator `Format-Gate2`): expected vs actual.

UI-touching ADs in Wave 163: **B (AD-721d-2c), C (AD-719b), D (AD-719a)** — all three require the full UI gate.

## Hard-stop conditions

The Builder STOPS and surfaces to the Architect if:

1. Any verify-first grep returns a result inconsistent with the prompt's claim (phantom-API).
2. Source code or test code is modified by something the Builder didn't author (working-tree-integrity).
3. A test failure persists under `-n 0` after `git stash`.
4. A prompt references a method or parameter that doesn't exist and the prompt does NOT define it (phantom-API).
5. Any change requires touching an invariant: AD-731, AD-727 trust isolation, BaseAgent / IntentMessage protocols.
6. Any prompt suggests adding a new pip or npm dependency. All 11 Wave 163 ADs are zero-new-dep.

## Wave-specific reminders (known false positives)

- **AD-728**: `BridgeAlertsConfig` does NOT exist in `config.py`. The prompt drops that reference. Builder should NOT introduce it.
- **AD-729**: `RecordsStore` exact API must be verified before Section 5. The prompt flags this — verify, don't assume.
- **AD-729b**: `QualificationConfig` exact class name must be verified. The prompt flags this — likely `BootCampConfig` or a sibling owns the field.
- **AD-729c**: AD-635 bridge alert API + AD-504 sampling-interval config — VERIFY before drafting. The issue body claims these exist but verify before wire-up.
- **AD-706d**: `_rule_based_classify_action` vs `classify_action` shape — VERIFY before extraction/rename.
- **AD-739**: `_CAPABILITY_GAP_RE` import path — VERIFY before Section 4 validation hook.
- **AD-719a**: WardRoom thread storage module path (`src/probos/wardroom/` vs `src/probos/knowledge/wardroom.py`) — VERIFY before edit.

## License posture

**Zero new pip/npm deps across all 11 ADs.** Confirmed:

- AD-728: uses existing vision tier via `runtime.llm_client.complete(LLMRequest(tier="vision"))`.
- AD-729 / 729b / 729c / 729d: pure Python + existing storage.
- AD-722a-6: template-rendered, no LLM call.
- AD-721d-2c: pure UI on existing server endpoint.
- AD-719b: pure UI consuming existing stores.
- AD-719a: extends existing WardRoom storage.
- AD-739: pure Python; pattern-absorbed from Letta (Apache-2.0) but ZERO Letta code imported.
- AD-706d: uses existing `runtime.llm_client` infrastructure.

No prompt surfaces a license decision.

## AD numbering audit

Wave 163 ADs (all pre-numbered as forward markers):

- AD-728 ✓ (filed)
- AD-729 ✓ (filed)
- AD-729b ✓ (filed)
- AD-729c ✓ (filed)
- AD-729d ✓ (filed)
- AD-722a-6 ✓ (filed)
- AD-721d-2c ✓ (filed)
- AD-719b ✓ (filed)
- AD-719a ✓ (filed)
- AD-739 ✓ (filed; was the highest, per PROGRESS.md line 10 noting AD-738 is shipped highest — AD-739 is the in-flight reservation for #649)
- AD-706d ✓ (filed)

**No collisions. No new numbers introduced.**

## Self-check pass — Required findings + revisions applied

Performed during initial drafting. Catalog of findings caught and resolved:

1. **AD-728 phantom `BridgeAlertsConfig`** — original issue body references `BridgeAlertsConfig.register(...)` for severity classification. Grep confirms no such class exists in `config.py`. **Revision applied**: AD-728 prompt drops the reference; severity flows through the `EventType.RENDER_DIVERGENCE_OBSERVED` payload's `severity` field instead. Verified-Against-Codebase footer flags this for the Builder.

2. **AD-729 hard-precondition tension with Wave 163 scope** — issue #587 says AD-729 does NOT advance to build until AD-729a Standing Orders ship. Wave 163 does NOT include AD-729a. **Revision applied**: AD-729 prompt explicitly scope-shrinks to the governance CONTRACT (DSL + dataclass + mechanical constraints + capability surface stub gated default-OFF). The contract is independently shippable; the conduct content stays at AD-729a as a forward marker. Both AD-722a-6 and AD-729b consume the CONTRACT shape, not the gated capability.

3. **AD-722a-6 hard-precondition tension** — issue body says "AD-729 family must ship and be operationally stable." Wave 163 ships AD-729's contract but not 2-quarter operational stability. **Revision applied**: AD-722a-6 ships behind dual default-OFF flags (`peer_perception_enabled` AND `cross_agent_divergence_observation_enabled`). Forward marker AD-722a-6-flip filed for the default-ON trigger.

4. **AD-729b QualificationConfig class name** — issue body uses `QualificationConfig` casually; config-class enumeration shows `BootCampConfig` but no standalone `QualificationConfig`. **Revision applied**: prompt explicitly flags this for verify-first; field-attach point is left to Builder discretion based on grep result.

5. **AD-729c AD-635 bridge alert + AD-504 sampling interval references** — issue body asserts both exist; not independently verified in Wave 163 pre-flight. **Revision applied**: both flagged as Builder-verify-first; honest-degrade fallbacks documented in the prompt.

6. **AD-739 `_CAPABILITY_GAP_RE` import** — issue body references it as the validation guard. The regex IS used in prompt-build flow but import path not confirmed. **Revision applied**: flagged for verify-first.

7. **AD-706d VisionLLMRateLimit generalizability** — issue body and Wave 162 retrospective both reference the rate-limit class as "class-level shared store, scope-keyed" (generalizable shape) but it lives in the vision module. **Revision applied**: prompt explicitly flags the generalizability question; fork to `LLMCallRateLimit` if the class proves vision-coupled.

8. **AD-719a thread storage module path** — could not deterministically locate during pre-flight (`src/probos/wardroom/` vs `src/probos/knowledge/wardroom.py`). **Revision applied**: flagged for verify-first; no other prompt-side change needed because the prompt operates on whichever module owns the storage.

9. **AD-721d-2c online-crew detection** — UI guard requires knowing whether a Counselor is online. Existing pattern not verified pre-flight. **Revision applied**: flagged for verify-first.

10. **AD-719b zustand store hooks** — exact names not verified. **Revision applied**: flagged for verify-first.

## Verification matrix

| Prompt | Phantom-API check | License check | Forward-marker style | BF-274/280/282/286/287 | AD-731 ref | Real-config-fixture |
|---|---|---|---|---|---|---|
| AD-728 | ✅ (BridgeAlertsConfig phantom dropped) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ Test 10 | ✅ Section 6 |
| AD-729 | ✅ (RecordsStore + CrewProfile + AD-480 flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ Test 18 | ✅ Section 8 |
| AD-722a-6 | ✅ (DivergenceResult + observe_peer flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ Test 10 | ✅ Section 4 |
| AD-729b | ✅ (QualificationConfig + Boot Camp hook flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ n/a noted | ✅ Section 5 |
| AD-729c | ✅ (AD-635 + AD-504 + 1:1 channel flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ n/a noted | ✅ Section 7 |
| AD-729d | ✅ no code | ✅ zero new deps | ✅ five technical triggers | ✅ n/a (doc only) | ✅ n/a | ✅ n/a |
| AD-721d-2c | ✅ (API client + endpoint response flagged) | ✅ zero new deps | ✅ n/a (UI completion) | ✅ all five cited | ✅ n/a noted | ✅ vi.mock pattern |
| AD-719b | ✅ (zustand hooks flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ n/a noted | ✅ vi.mock pattern |
| AD-719a | ✅ (storage module flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ Test 6 | ✅ Section 5 |
| AD-739 | ✅ (_CAPABILITY_GAP_RE + KnowledgeStore + Dreaming hook flagged) | ✅ zero new deps | ✅ five technical triggers | ✅ all five cited | ✅ Test 10 | ✅ Section 7 |
| AD-706d | ✅ (VisionLLMRateLimit generalizability + classify_action shape flagged) | ✅ zero new deps | ✅ technical triggers | ✅ all five cited | ✅ n/a noted | ✅ Section 6 |

## Post-sweep procedure

After all 11 ADs ship + AD-729d documentation lands:

1. Run full gate: `pytest tests/ -q -n 4 --dist=loadfile` → green.
2. Run UI gate: `cd ui ; npx vitest run` AND `cd ui ; npm run build` → both green.
3. `git push origin main` (or wave branch per current orchestrator policy).
4. `gh issue close <each issue>` per the per-AD acceptance criteria.
5. Update `PROGRESS.md` Wave 163 closure summary.
6. Update `docs/development/roadmap.md`: move shipped ADs out of forward-marker tables; add new sub-AD forward markers per each prompt's "Forward markers" section.
7. `DECISIONS.md` append all Wave 163 entries.
8. Archive prompts to `prompts/archive/wave-163/` per orchestrator convention.

## Closing note

The peer-observation cluster is the largest architectural surface this wave touches. The scope-shrink of AD-729 (governance contract only; conduct content deferred to AD-729a) keeps the wave honest — Wave 163 ships the plumbing, NOT the policy. The conduct policy ships when the Counselor has enough operational data to author it, per Captain ruling 2026-05-10.

The five-trigger forward marker for AD-729d in particular is the load-bearing safety story: reinforcement does not advance until the read-only observation has demonstrated 2 quarters of clean operation. This is the AD-722c-3 technical-trigger discipline working as intended.
