# Wave 154 Dispatch — Vision DM family completion + self-perception milestone

**Date:** 2026-05-12. **Architect:** Sean. **Mode:** Continuous build (one prompt = one commit).
**Theme:** Close out the AD-730/720d sub-AD family + ship the safety-constrained self-perception capability.
**Estimated wall-time:** ~10h. **Estimated test count delta:** +25 to +35.

This wave rides the now-green vision pipeline (AD-730/731/732/734) and stays inside a single subsystem to minimize context-switching cost.

---

## Inputs (read in full before any code)

1. `.github/copilot-instructions.md` — engineering / testing / logging / type-annotation rules. Every commit complies.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules (test gate, working-tree, log-and-degrade tiers).
3. The 7 prompt files at `prompts/ad-*.md` for this wave (listed below).

---

## Standing rules (carry from Wave 153)

- **Test gate (full):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` (4 workers conservative; 16 acceptable if machine handles it).
- **Per-prompt gate (focused):** `pytest tests/test_<adNNN>_*.py -v -n 0`.
- **Pre-commit hook AD-734** lives at `.git/hooks/pre-commit` and auto-runs the vision contract test (`tests/test_ad734_wire_shape_contract.py`) when any of `vision_dispatch.py`, `llm_client.py`, `routers/chat.py`, `routers/agents.py`, `config/system.yaml` is staged. **Do not bypass with `--no-verify`** — if it fires red, the bus shape regressed and you fix the regression, not the test.
- **Working tree:** if you find tracked-file modifications you didn't make, surface them. Do not `git stash` / `git reset --hard`.
- **One commit per AD.** Commit message format: `AD-NNN(x): <one-line summary> (Wave 154)`. Include `Closes #NNN` for every GH issue retired by the commit.
- **Inline blob anti-pattern.** Anything that goes into `IntentMessage.params` and could exceed 4 KB must use a content-addressable ref to `AttachmentStore` (AD-731 pattern). The bus carries refs; the store carries bytes.

---

## Build order and dependency DAG

Strict sequencing where noted; parallel where independent.

```
Group A (independent, any order):
  AD-720d-3   (#565)  ─── episodic write for /api/chat vision turn
  AD-720d-2   (#564)  ─── vision_capable on CrewProfile + gating
  BF-264-close (#636) ─── verify + close OOM crash (docs only)

Group B (sequenced — A.vision_capable must land first):
  AD-730-5    (#635)  ─── per-agent_type vision tier override

Group C (sequenced — gate before capability):
  AD-727      (#585)  ─── safety constraints (docs + safety_constraints test)
       ↓ must land before
  AD-722e     (#571)  ─── deterministic structured self-projection v1

Group D (independent UI):
  AD-730-1    (#631)  ─── WardRoomThreadDetail attach button
```

Suggested commit order: **AD-720d-3, AD-720d-2, AD-730-5, AD-727, AD-722e, AD-730-1, BF-264-close.**

---

## Per-prompt summaries (full prompts in `prompts/ad-*.md`)

| AD | GH | Files | Tests | Est |
|---|---|---|---|---|
| AD-720d-3 | [#565](https://github.com/seangalliher/ProbOS/issues/565) | `routers/chat.py` | +1 file, 3 tests | 1.5h |
| AD-720d-2 | [#564](https://github.com/seangalliher/ProbOS/issues/564) | `crew_profile.py`, `cognitive/vision_dispatch.py`, `routers/chat.py`, `routers/agents.py` | +1 file, 4 tests | 1.5h |
| AD-730-5 | [#635](https://github.com/seangalliher/ProbOS/issues/635) | `config.py`, `routers/agents.py`, `routers/chat.py`, `cognitive/cognitive_agent.py` | +1 file, 3 tests | 1h |
| AD-727 | [#585](https://github.com/seangalliher/ProbOS/issues/585) | `DECISIONS.md` (ratify), `tests/test_ad727_safety_constraints.py` (new), `docs/architecture/self-perception-framing.md` (new) | +1 file, 5 tests | 1h |
| AD-722e | [#571](https://github.com/seangalliher/ProbOS/issues/571) | `cognitive/self_perception.py` (new), `cognitive/cognitive_agent.py` (wire), `types.py` (SelfPerceptionProjection dataclass) | +1 file, 6 tests | 3h |
| AD-730-1 | [#631](https://github.com/seangalliher/ProbOS/issues/631) | `ui/src/components/wardroom/WardRoomThreadDetail.tsx`, `ui/src/__tests__/WardRoomThreadDetail.attach.test.tsx` (new) | +1 Vitest file, 3 tests | 2h |
| BF-264-close | [#636](https://github.com/seangalliher/ProbOS/issues/636) | `progress-era-5-unification.md` | 0 | 0.25h |

---

## License posture

All seven items are internal — no external code absorption. No license checks required.

---

## Acceptance for the wave as a whole

- All 7 ADs committed individually, each with `Closes #NNN`.
- Full test gate green at end of wave; baseline test count + per-prompt deltas (~25–35).
- AD-734 pre-commit hook never bypassed.
- DECISIONS.md highest-AD line in PROGRESS.md updated.
- progress-era-5-unification.md gets one bullet per shipped AD.
- All 7 prompt files moved to `prompts/archive/` after wave close.
- Orchestrator state advanced via `scripts/wave-orchestrator.ps1`.

---

## Deferrals — explicit forward markers

The following are **explicitly deferred** with AD number + GH issue tracked. The orchestrator must not advance past close without these documented:

- **AD-722e-2 (vision-LLM verification of self-render).** Deferred per AD-727 hard rule #4. New AD + GH issue filed at wave close.
- **AD-722e-3 (cross-crew visual perception).** Deferred per AD-727 hard rule #7. Existing forward marker AD-729 (#587) covers this; cite at close.
- **AD-720d-2.1 (Captain approval flow to enable vision_capable on a new agent).** v1 ships static config-driven default; the propose/approve loop is filed as a forward marker AD with new GH issue.
- **AD-730-1.1 (drag-and-drop + paste in WardRoomThreadDetail).** v1 ships file-picker paperclip only.
