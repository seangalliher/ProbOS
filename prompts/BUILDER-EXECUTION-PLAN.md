# Builder Execution Plan — Continuous Build of 20 Approved Prompts

**Date:** 2026-04-27
**Architect:** Approved all 20 prompts in `prompts/ad-*.md` (see [Reviews/README.md](Reviews/README.md))
**Mode:** Continuous — Builder must complete all 20 ADs in one session without pausing for Captain review between waves.
**Estimated AD range:** AD-444, 563, 564, 565, 571, 572, 573, 574, 579a, 579b, 579c, 586, 600, 602, 604, 606, 608, 609, 610, 673

---

## Standing Orders for the Builder

1. **Read each prompt fully before starting.** The prompts are self-contained specs. Do not improvise.
2. **Comply with `.github/copilot-instructions.md`** — every AD's Acceptance Criteria explicitly requires this.
3. **Run the full test suite after each AD:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
   - If tests fail, fix and re-run before moving to the next AD.
   - Report the test count after each AD completes.
4. **Update PROGRESS.md and DECISIONS.md** after each AD. Append the new AD entry to `DECISIONS.md` and update the "highest AD" / test count lines in `PROGRESS.md`.
5. **Commit per AD.** One commit per AD with message `AD-NNN: <title>`. This makes bisection easy if a later AD breaks something.
6. **Do not stop between ADs.** Continue through all 20 unless a hard blocker appears (test failure that cannot be fixed in 2 attempts, missing API not specified in the prompt, or repository-state corruption).
7. **If a hard blocker appears,** report the AD number, the blocker, what was attempted, and stop. Do NOT skip ahead to the next AD.
8. **Do not expand scope.** Each prompt has explicit "Do Not Build" guards. Respect them.
9. **Type annotations on all new public methods.** No bare log messages. Hold task references for `create_task()`. Use `dataclasses.replace()` for frozen dataclasses. Use `Field(default_factory=...)` for mutable Pydantic defaults. (Standard ProbOS engineering principles.)

---

## Build Order

Order is dependency-layered. Within a wave, ADs are independent and could in principle be built in any order, but build them in the listed sequence to keep diffs small and reviewable.

### Wave A — Independent Foundations (10 ADs)

These have no dependencies on other ADs in this sweep. Each can be built and tested in isolation.

| # | AD | Prompt | Notes |
|---|---|---|---|
| 1 | AD-444 | [ad-444-knowledge-confidence-scoring.md](ad-444-knowledge-confidence-scoring.md) | KnowledgeStore confidence + decay; late-bind setter pattern |
| 2 | AD-563 | [ad-563-knowledge-linting.md](ad-563-knowledge-linting.md) | Lint pass in dream cycle; word-boundary regex preferred over `.split()` |
| 3 | AD-564 | [ad-564-quality-triggered-consolidation.md](ad-564-quality-triggered-consolidation.md) | Forced consolidation triggers; cooldown + daily limit |
| 4 | AD-565 | [ad-565-quality-informed-routing.md](ad-565-quality-informed-routing.md) | **Verify first:** confirm `NotebookQualitySnapshot.per_agent` schema |
| 5 | AD-573 | [ad-573-memory-budget-accounting.md](ad-573-memory-budget-accounting.md) | Per-cycle scope; tier model with disabled passthrough |
| 6 | AD-579a | [ad-579a-pinned-knowledge-buffer.md](ad-579a-pinned-knowledge-buffer.md) | PinnedFact dataclass field order is correct — verify import succeeds |
| 7 | AD-579b | [ad-579b-temporal-validity-windows.md](ad-579b-temporal-validity-windows.md) | Backward-compatible 0.0 defaults |
| 8 | AD-586 | [ad-586-task-contextual-standing-orders.md](ad-586-task-contextual-standing-orders.md) | Tier 5.5 in compose_instructions; create empty `general.md` (zero bytes) |
| 9 | AD-602 | [ad-602-question-adaptive-retrieval.md](ad-602-question-adaptive-retrieval.md) | StrEnum QuestionType; classification priority is TEMPORAL > CAUSAL > SOCIAL > FACTUAL |
| 10 | AD-610 | [ad-610-utility-storage-gating.md](ad-610-utility-storage-gating.md) | **Verify first:** confirm `probos.cognitive.similarity.jaccard_similarity` exists |

**Gate:** Full test suite green. Snapshot test count and report.

### Wave B — One-Step Dependencies (5 ADs)

| # | AD | Prompt | Depends On |
|---|---|---|---|
| 11 | AD-571 | [ad-571-agent-tier-trust-separation.md](ad-571-agent-tier-trust-separation.md) | Standalone, but enables Wave C trust filtering. **Verify first:** `outcomes_for()` exists on TrustNetwork |
| 12 | AD-572 | [ad-572-episodic-procedural-bridge.md](ad-572-episodic-procedural-bridge.md) | **Verify first:** `EpisodeCluster.intent_types` exists; `Procedure.evolution_type` accepts `"BRIDGED"` |
| 13 | AD-574 | [ad-574-episodic-decay-reconsolidation.md](ad-574-episodic-decay-reconsolidation.md) | Episode importance field |
| 14 | AD-579c | [ad-579c-validity-aware-dream-consolidation.md](ad-579c-validity-aware-dream-consolidation.md) | AD-579b validity fields |
| 15 | AD-600 | [ad-600-transactive-memory.md](ad-600-transactive-memory.md) | Episode metadata. Verify `decay()` method spec is complete in the prompt |

**Gate:** Full test suite green. Snapshot test count and report.

### Wave C — Two-Step Dependencies (5 ADs)

| # | AD | Prompt | Notes |
|---|---|---|---|
| 16 | AD-604 | [ad-604-spreading-activation.md](ad-604-spreading-activation.md) | **Verify first:** `_format_recall_score` helper location/signature; `recall_by_anchor_scored` keyword args |
| 17 | AD-606 | [ad-606-think-in-memory.md](ad-606-think-in-memory.md) | **Verify first:** working-memory method name (`get_conclusions` vs `recent_conclusions`); `ConclusionEntry.conclusion_type` field |
| 18 | AD-608 | [ad-608-retroactive-memory-evolution.md](ad-608-retroactive-memory-evolution.md) | Includes both `update_episode_metadata()` and `get_episode_metadata()` specs — implement both |
| 19 | AD-609 | [ad-609-multi-faceted-distillation.md](ad-609-multi-faceted-distillation.md) | **Verify first:** `EpisodeCluster.is_failure_dominant`, `is_success_dominant`, `participating_agents`, `anchor_summary`, `variance` properties |
| 20 | AD-673 | [ad-673-anomaly-window-detection.md](ad-673-anomaly-window-detection.md) | Uses `_add_event_listener_fn` callback pattern; `tag_recent()` is a stub returning 0 — that is intentional |

**Gate:** Full test suite green. Final test count.

---

## Per-AD Workflow

For each AD in order:

1. `git status` — confirm clean working tree.
2. Read the full prompt.
3. Execute any **Verify first** steps listed above (search the codebase for the named symbol/signature). If verification fails, the prompt's assumption is wrong — STOP and report.
4. Implement per the prompt:
   - Edit named files only.
   - Honor "Do Not Build" guards.
   - Match the dataclass / Pydantic / async / typing patterns from `.github/copilot-instructions.md`.
5. Add tests as specified in the prompt's Test Plan.
6. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`.
   - On failure: diagnose, fix, re-run. Allow up to 2 fix attempts. If still failing, STOP and report.
7. Append to `DECISIONS.md`: `AD-NNN: <title> — <one-line summary>`.
8. Update `PROGRESS.md`: bump highest AD, update test count.
9. `git add -A && git commit -m "AD-NNN: <title>"`.
10. Move to next AD immediately. Do NOT pause for review.

---

## Inter-Wave Reporting (brief)

After Wave A, B, and C complete, emit a one-line summary:
```
Wave <X> complete. ADs: <list>. Tests: <N> passing. Commits: <N>.
```

Do not pause. Continue to the next wave.

---

## Final Report

After AD-673 completes:
1. Run the full test suite one more time.
2. Report:
   - Total ADs built: 20
   - Total tests added: <delta>
   - Final test count: <N>
   - Total commits: 20
   - Any items deferred to follow-up ADs (e.g., the "expose runtime public properties" tracking AD noted in Reviews/README.md).
3. STOP. Captain reviews and merges.

---

## Hard Stop Conditions

Stop immediately and report if any of these occur:

- A `Verify first` step fails (the prompt assumes an API/symbol that doesn't exist).
- Tests fail and 2 fix attempts don't recover.
- A prompt instructs writing to a file outside its declared `target_files`.
- An import cycle, layer violation, or circular dependency is detected.
- The `.venv` becomes corrupted or `pytest` cannot start.
- Any AD requires modifying core protocols (`BaseAgent`, `IntentMessage`, `IntentResult`) — these are out of scope for this batch.

When stopping, report:
1. AD number where you stopped.
2. What was attempted.
3. Exact error / blocker.
4. State of the working tree (clean / dirty / partial commit).

---

## Notes

- The reviews in [Reviews/](Reviews/) document the verdict for each prompt — useful background context.
- The Architect's pre-flight verifications (the "Verify first" lines above) are the highest-risk items. Doing them at the top of each AD prevents the most common failure mode (building against a phantom API).
- After this batch, the next architectural milestone is the deferred "expose runtime public properties" AD — do not start it as part of this build.
