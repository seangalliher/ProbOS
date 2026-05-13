# Wave 154 Dispatch — Small Follow-On Cleanup (DM hardening + Multimodal small wins + HXI polish)

**Date:** 2026-05-12. **Architect:** Sean. **Mode:** Continuous build (one prompt = one commit).
**Theme:** Seven GH issues across three loosely-coupled themes. None depend on each other; parallel-safe.
**Estimated wall-time:** ~8h. **Estimated test count delta:** +20 to +30 (Python + Vitest combined).

> **Scope reduction (architect, pre-dispatch).** AD-722b-1 (crew-scope auth on telemetry, #598) was deferred to a future security-focused wave. First HTTP auth in the codebase merits explicit security review beyond a small-cleanup wave's tolerance. #598 stays open.

> **Label collision note.** The previous Wave 154 (vision DM family + self-perception milestone) shipped its 7 commits informally without a `wave-plan.yaml` entry — the orchestrator never tracked it; that work is archived at `prompts/archive/WAVE-154-DISPATCH.md`. THIS Wave 154 is the formal yaml-tracked Wave 154. The yaml id "154" is the next free slot after id "153" (vision tier). Operators reading `git log` will see "Wave 154" twice across non-overlapping commit ranges; that is the expected state.

---

## Wave goal

Close out a backlog of small ergonomic + safety follow-ons that have been deferred as forward markers across Waves 139, 150, 151, 152, 153, and the informal 154. None require new architecture. None modify the cognitive chain or the vision wire shape. Each is bounded by an existing parent AD with explicit deliverables.

---

## Inputs (read in full before any code)

1. `.github/copilot-instructions.md` — engineering / testing / logging / type-annotation rules. Every commit complies.
2. `prompts/BUILDER-EXECUTION-PLAN.md` — standing rules (test gate, working-tree, log-and-degrade tiers).
3. `prompts/review-criteria.md` — review tiers (Required / Recommended / Nits / Verified).
4. The 5 prompt files for this wave (listed below).

---

## Standing rules (carry from Wave 153)

- **Test gate (full):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
- **Per-prompt gate (focused):** `pytest tests/test_<adNNN>_*.py -v -n 0`.
- **UI gate:** `cd ui; npx vitest run`.
- **Pre-commit hook AD-734** lives at `.git/hooks/pre-commit` and auto-runs the vision contract test when staged files include `vision_dispatch.py`, `llm_client.py`, `routers/chat.py`, `routers/agents.py`, `config/system.yaml`. **Do not bypass with `--no-verify`** — if it fires red on AD-720d-1, the wire shape regressed.
- **Working tree:** if you find tracked-file modifications you didn't make, surface them. Do not `git stash` / `git reset --hard`.
- **One commit per AD.** Commit message format: `AD-NNN(x): <one-line summary> (Wave 154)`. Include `Closes #NNN` for every GH issue retired by the commit.
- **Inline blob anti-pattern.** Anything that goes into `IntentMessage.params` and could exceed 4 KB must use a content-addressable ref to `AttachmentStore` (AD-731). AD-720d-1 in this wave preserves that invariant — verify per-attachment timing fields stay small.
- **License hygiene.** AD-724-2 uses stdlib `difflib.SequenceMatcher` (verified `pip show rapidfuzz` returned 1 — not installed; do not add it).

---

## Pre-flight checklist (run BEFORE the first prompt build)

1. `git status --short` — clean tree (only the 5 new prompt files + this dispatch + wave-plan.yaml diff). The orchestrator's later commit step handles those.
2. `git pull` — confirm at HEAD `84b9309c` or later.
3. **Close GH #647 as duplicate of #646** before AD-730-1-1 commits — this is a documentation-only `gh issue close 647 --reason 'duplicate of #646' --comment '...'` step. Do this manually, not as part of any AD commit.
4. Run baseline test count and record:
   - `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile --co` (or `-q --no-header` and grep "passed" from a fast run if `--co` is too slow).
   - Note the number for the post-wave delta check.
5. Run `./scripts/phantom-api-precheck.ps1 prompts/ad-724-dm-hardening.md prompts/ad-730-1-1-drag-paste-image.md prompts/ad-720d-1-multi-image-batch.md prompts/ad-719-718-hxi-polish.md` and confirm 0 phantoms (or all flagged are documented false positives in this dispatch).
6. Confirm Vitest baseline: `cd ui; npx vitest run` — note count.

---

## Build order — parallel-safe

These four prompts touch independent areas of the codebase. Recommended commit order is alphabetical by AD; the Builder may interleave or parallelize:

| Order | AD(s) | Prompt | Touches | GH | Tests |
|---|---|---|---|---|---|
| 1 | AD-719c + AD-718d-1 | `ad-719-718-hxi-polish.md` | UI only (`IntentSurface.tsx`, new `ModulationIndicator.tsx`, `ProfileChatTab.tsx`) | #548, #553 | +6 Vitest |
| 2 | AD-720d-1 | `ad-720d-1-multi-image-batch.md` | `cognitive/vision_dispatch.py`, `routers/chat.py`, `routers/agents.py`, `config.py` | #563 | +5 |
| 3 | AD-724-1/2/5 | `ad-724-dm-hardening.md` | `cognitive/dm_sanity_gate.py`, `routers/agents.py`, `proactive.py`, `config.py` | #627, #628, #629 | +12 to +18 |
| 4 | AD-730-1-1 | `ad-730-1-1-drag-paste-image.md` | UI only (`WardRoomThreadDetail.tsx`) | #646 | +3 Vitest |

No dependency arrows between prompts. The wave is parallel-safe at the file level (no two prompts touch the same lines).

---

## Per-commit gate

After each AD commits:

1. **Focused gate** — the per-prompt verification command from each prompt's "Verification commands" section.
2. **Full Python gate** — `pytest tests/ -q -n 4 --dist=loadfile`. Test count must be **non-decreasing**. If a previously-green test goes red, triage per BUILDER-EXECUTION-PLAN hard-stop rules.
3. **UI gate** (only when the AD touched `ui/`) — `cd ui; npx vitest run`. Same non-decreasing rule.
4. **AD-734 pre-commit hook** — must pass on the AD-720d-1 commit specifically. The added third return-tuple element changes the function signature; the contract test must continue to assert the bus shape (refs not blobs).

---

## GH issues closed by this wave

- **#548** — AD-719c picker keyboard nav.
- **#553** — AD-718d-1 modulation activity indicator.
- **#563** — AD-720d-1 multi-image batch + per-attachment timing.
- **#627** — AD-724-1 DM sanity gate one-shot retry.
- **#628** — AD-724-2 DM repetition similarity beyond exact-prefix.
- **#629** — AD-724-5 DM sanity gate lifted into WR/chain reply paths.
- **#646** — AD-730-1-1 WardRoomThreadDetail drag/drop + paste image.

**Deferred (not closed by this wave):** #598 — AD-722b-1 crew-scope auth. See scope-reduction note above.

Pre-flight (NOT a commit, NOT in any AD): **close #647 as duplicate of #646**.

---

## Hard-stop conditions

The Builder stops and surfaces to the Architect when:

1. **Phantom API in implementation.** Any prompt's SEARCH/REPLACE references a method/attribute/signature that does not exist on the live target. Verify against the current codebase, not the prompt's claim. (The verify-first footers in each prompt are the source of truth — but the source itself can have shifted since drafting.)
2. **Architectural deviation required.** Any prompt cannot land without modifying a load-bearing invariant (uniform NATS transport, content-addressable refs, consensus gating, trust scoring, layer boundaries). The bug is in the prompt, not the architecture — escalate to Architect for prompt revision.
3. **Pre-flight tracked-tree pollution.** Any tracked-file modification at HEAD that the Builder did not make. Apply the BUILDER-EXECUTION-PLAN triage tree (commit Architect-authored docs; surface unidentified source mods).
4. **AD-720d-1 specific:** if the AD-734 pre-commit hook fires red on the multi-image commit, the third tuple element is leaking blob bytes into outcomes. Stop, do not bypass the hook, escalate.
5. **Test count regression.** Any non-environmental serial-mode test failure that does not resolve after a single re-run.

---

## Post-wave procedure

1. Update `prompts/wave-plan.yaml` entry status from `drafted` → `shipped`.
2. Move all 4 prompts to `prompts/archive/`.
3. **Do NOT move `prompts/WAVE-154-DISPATCH.md` to archive yet** — there is already a `prompts/archive/WAVE-154-DISPATCH.md` from the informal previous Wave 154. Rename this dispatch to `prompts/archive/WAVE-154-FORMAL-DISPATCH.md` to avoid the collision.
4. Append a single retrospective bullet to PROGRESS.md noting wave-id label collision (one line; this is for future archaeology).
5. Update `decisions-era-5-unification.md` highest-AD line if AD-724-x / AD-720d-1 / AD-719c / AD-718d-1 / AD-730-1-1 push it higher than AD-734.
6. **Do NOT** file forward-marker AD-722b-2 from this wave — it will be filed when AD-722b-1 ships from its own dedicated wave.

---

## Deferrals — explicit forward markers

- **AD-722b-1** (crew-scope auth on telemetry, #598) — deferred from this wave to a security-focused wave per pre-dispatch architect review.
- **AD-722b-2** (full auth design — rotation, TLS, multi-operator, audit log). Filed alongside AD-722b-1 in its dedicated wave.
- **AD-724-3** (strict mode for the DM sanity gate — Tier-3 propagate). Already in the AD-724 family roadmap; not in this wave.
- **AD-730-1-2** (drop-zone visible hover state in WardRoomThreadDetail). Optional polish; not in this wave.
- **AD-720d-1.1** (context-budget truncation policy when image count exceeds the warn threshold). v1 only warns, never truncates.

---

## Risk acknowledgments

- **AD-724-2 SequenceMatcher** is O(n×m). The default `repetition_similarity_threshold=0.85` keeps the cost bounded by the repetition prefix length (~100 chars) since the exact-prefix check still gates the fast path.
- **AD-720d-1** changes a function return signature (`build_multimodal_messages`). Two call sites updated in the same commit; one is in the same module (`vision_dispatch.py:294`). The AD-734 hook will catch any wire-shape regression but not signature drift — verify both callers compile.
