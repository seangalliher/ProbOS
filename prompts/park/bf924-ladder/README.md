# BF-924 slice 2 (PARKED): AD-535's ladder takes effect

**Status: parked 2026-10-25. This branch (`park/bf924-ladder`) is never opened as a PR and is not for merge.** It keeps the work that BF-924 (#1654) split off at its fourth round-three brake, so that slice 2 can start from it.

## What happened

BF-924 (#1654) found that the AD-535/536 procedure-compilation clamp read an attribute nothing sets. Review round 1 found that promotion and demotion wrote only the `compilation_level` column while `get` rebuilds a procedure from its JSON snapshot, so AD-535's ladder never took effect. The contract chose to make it take effect (D10, disclosed effect E8), and six review rounds then found read-then-write races in the procedure store's writers that D10 turned into dispatch effects: the success count, the promotion, the failure demotion, the metadata merge (`merge_procedures`), decay (`decay_stale_procedures`) and restore. Round 6 found two P2 defects with ordinary reach outside the last repair's delta (the merge and decay writers), and the Architect's fourth round-three brake split the ladder's activation off. BF-924 part 1 (the clamp and live-trust helper, D9, D17, D18 and all of M2) ships without it and says "Part of #1654"; the issue stays open for this slice.

## What this branch holds

- **History.** The BF-924 contract with Amendments A1 to A6 at `64178a5a` (`prompts/bf-924-trust-inputs-through-real-apis.md`: decisions D1 to D29 in section 3, effects E1 to E20 in section 5, mutation rows R1 to R59 in section 10, properties in section 14, the register in section 18), the M1 candidate `5aa7a25b` and the M2 candidate `8e4e5cad` (scratch commits built by tool from that contract; every Builder file was blob-equal to the contract applied by tool; the M1 list of 21 test files passed 704, the M2 list 1,035). The shipped contract is the reduced A7 version.
- **`reviews/`** the round 4, 5 and 6 reports (`gpt-6.1-sol`): every property of D24 to D28 held under real-object probes; round 6's open findings are below.
- **`probes/`** the reviewers' real-object probes: `test_r5_validation_epoch.py` and its control (Guided outcomes must not supply Level 4's threshold), `test_shared_outcome_order.py` (a stale success must not overwrite another agent's later demotion), `test_additional_lifecycle.py` (a real `CounselorAgent` through a rejected compound step), `test_r6_merge_boundary.py` (finding 1), `test_r6_level_epochs.py` (findings 2 to 4), `test_r6_pre_m1_activation.py` (the control that passes on the base and fails with D10, by design) and `test_result_paths.py` (the rig the others load; one expectation, row `clamped-guided-success-capped`, is changed by design for D28). Run them through a guarded home (`USERPROFILE` and `HOME` redirected to an empty directory) with `BF924_SOURCE_TREE` or `PYTHONPATH` pointing at a checkout of this branch; a probe puts that checkout's `src` first on `sys.path` and asserts it.

## Slice 2's entry conditions (D32)

1. Every write statement on `procedure_records` (22, all in `procedure_store.py`) reads inside `_index_write` or compares and sets on what it read, enumerated by statement, not by the fields it names.
2. A level generation that every level change increments, carried by each replay decision and required by the success increment and the promotion (finding 4: a count at a level must hold only successes executed since that level was set). This changes the persisted schema: slice 2's contract decides the migration and whether it needs the Captain.
3. An atomic, floor-preserving demotion (a stale failure must not raise a restored row).
4. The round-5 epoch probe and the round-6 merge, decay and epoch probes pass, and the count of active procedures whose column and snapshot already disagree (R10) is decided before activation.
5. D10, D15, D16 and D20 to D29 are re-reviewed whole on that design.

## Open findings of round 6 (register rows R28 to R32 of the contract)

- R29 `merge_procedures` writes back a stale whole snapshot (`procedure_store.py:2061-2081`).
- R30 `decay_stale_procedures` selects before the lock and writes `old_level - 1` with no recheck (`:1658-1690`).
- R31 an unconditional stale failure demotion can raise a restored Level 1 row to Level 2 (`cognitive_agent.py:2791-2795`, `procedure_store.py:1179-1180`).
- R32 the count epoch (an ABA case at the same numeric level) needs a generation.
