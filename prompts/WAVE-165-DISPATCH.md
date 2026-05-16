# Wave 165 — Dispatch (single AD)

**Author:** Architect
**Date:** 2026-05-16
**Mode:** continuous-build (single AD; commit on green tests)
**Standing rules:** [BUILDER-EXECUTION-PLAN.md](BUILDER-EXECUTION-PLAN.md) in full.

## Build

| # | AD | Prompt | Tests | Closes |
|---|---|---|---|---|
| 1 | AD-728d | [ad-728d-self-image-awareness-skill.md](ad-728d-self-image-awareness-skill.md) | +7 | `gh issue` filed 2026-05-16 ("AD-728d: self-image-awareness skill (LLM-discoverable self-check capability)") |

## Pre-flight

```pwsh
git status                                          # clean tree required
git log --oneline -1                                # baseline HEAD
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select-Object -Last 3   # baseline test count
```

## Per-prompt workflow

1. Read [ad-728d-self-image-awareness-skill.md](ad-728d-self-image-awareness-skill.md) in full.
2. Apply Section 1 (new SKILL.md file).
3. Apply Section 2 (DmSanityGate regex + helpers).
4. Apply Section 3 (DmReplyPipeline new step + renumber + ctx field).
5. Apply Section 4 (new test file).
6. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad728d_self_image_awareness_skill.py -v -n 0`
7. Full parallel gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
8. Commit: `git commit -m "AD-728d: self-image-awareness skill (Wave 165)" -m "<body>" -m "Closes #<issue>"`
9. Update `PROGRESS.md` + `decisions-era-5-unification.md` per the prompt's Tracking section.

## Hard-stop conditions

- DmReplyPipeline step renumbering breaks any existing test → STOP. The renumber is mechanical; failures here mean a test was importing or referencing the old step name. Surface to architect with the failing test file + line.
- `find_augmentation_skills` returns the new skill for an unintended intent (e.g. it leaks into `command_execution` or `consensus_vote`) → STOP. The skill's `probos-intents` list is authoritative; if the catalog matches outside that list there is a regression in `skill_catalog.py`. Surface.
- `check_own_render` task reference is GC'd before completion (`RuntimeWarning: coroutine was never awaited` in test output) → STOP. The ctx field is supposed to prevent this. Surface.
- Any change to `CognitiveAgent.check_own_render`, `verify_render_coherence`, or the four `avatars.render_self_check_*` Pydantic fields → STOP. AD-728c is the source of truth for those; this AD only adds an invocation path.

## Wave-specific reminders

- **Real fixtures only.** Use real `SystemConfig`, real `DmSanityGate`, real `CognitiveSkillEntry`. No `MagicMock` at substrate boundaries (BF-287).
- **Renumbering the pipeline tuple AND the method names AND the docstring comments is one logical step.** Don't ship the tuple change without the method renames or the runtime will crash on first DM.
- **The skill's `probos-intents` field lists `proactive_think` and `ward_room_notification`** even though the parser only handles DM. This is intentional discoverability; do not reduce the list to just `direct_message`.
- **The lax strip regex (`_SELF_CHECK_STRIP_RE`) is broader than the strict match regex (`_SELF_CHECK_RE`)** by design. Don't collapse them.
- **`record_observation` signature has no `category` kwarg** (per AD-728c retrospective). The skill body doesn't touch this — but if the test fixture builds one, use `summary, *, source, metadata, knowledge_source`.

## Post-build report

| Field | Value |
|---|---|
| Baseline test count | (from pre-flight) |
| Final test count | (expected baseline + 7) |
| Files changed | `config/skills/self-image-awareness/SKILL.md` (new), `src/probos/cognitive/dm_sanity_gate.py`, `src/probos/cognitive/dm/reply_pipeline.py`, `tests/test_ad728d_self_image_awareness_skill.py` (new) |
| New dependencies | none (verify with `git diff pyproject.toml ui/package.json` → empty) |
| Forward markers filed | none |
| GitHub issues closed | the AD-728d issue filed 2026-05-16 |
