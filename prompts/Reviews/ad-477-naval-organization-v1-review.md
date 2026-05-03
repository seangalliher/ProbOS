# Review: AD-477 — Naval Organization Protocols v1 (Captain's Log + Plan of the Day)

**Verdict:** ⚠️ Conditional
**Pre-deferral honesty solid; AD-566 read-only confirmed; Section 0 clean — but two consumer-side phantoms (`runtime.dreaming_engine` attribute, episodic by-date query) and one phantom kwarg value (`status="pending"`) need resolution before Builder.**

---

## Required (must fix before building)

1. **`runtime.dreaming_engine` is a phantom attribute.** Solution Overview lists it as a "read-only consumer (recent dream consolidation summaries)" and Section 2's `CaptainsLogService.generate_for_date` aggregates "Dream consolidation summaries (if dreaming_engine has run)". Verified against codebase:

   ```
   grep -n "self.dreaming_engine\|self\._dreaming_engine" src/probos/runtime.py
     (zero hits)
   grep -n "dream_scheduler" src/probos/runtime.py
     1022: if self.dream_scheduler and self.dream_scheduler.is_dreaming:
     2102: if self.dream_scheduler and self.dream_scheduler.is_dreaming:
     2912: "state": "dreaming" if self.dream_scheduler.is_dreaming else "idle",
   ```

   Runtime carries `runtime.dream_scheduler` (a `DreamScheduler`); the `DreamingEngine` instance is internal to `startup/dreaming.py` and stored in `StartupResults.dreaming_engine`, but **never exposed on the runtime object**. This is the same shape as the already-mitigated `runtime.duty_schedule_tracker` phantom — pre-defer or rewire before Builder.

   Hard-Stop #1 ("Existing `runtime.dreaming_engine` attribute name doesn't match — surface; may need different consumer pattern") acknowledges the risk but punts to Builder discovery. Per Wave 9 retrospective convention #21 (proactive structural-defect sweep), structural defects must be resolved at draft time, not at build time.

   **Resolution paths (pick one):**
   - **(a) Drop dream-consolidation from v1**, add a NOTE mirroring the duty-tracker negative-framing pattern, and defer to AD-477g (forcing function: runtime exposes `runtime.dreaming_engine` as a public attribute, OR `DreamScheduler` exposes a `recent_consolidation_summaries(...)` accessor). Update Section 2 docstring accordingly. **(Recommended.)**
   - **(b)** Switch consumer to `runtime.dream_scheduler` AND specify the exact summary-query API the service uses. Verify-first grep against `src/probos/cognitive/dreaming.py` for the live method name and signature; document grep evidence in the Verified Against Codebase section. Higher build risk because the consumer-side API on `DreamScheduler` for "recent consolidation summaries" is not enumerated in the prompt and is not obviously present (no `consolidation_summaries`, `recent_dreams`, or similar grep hit).

2. **Episodic memory by-date query is unspecified / phantom-by-omission.** Section 2's `CaptainsLogService.generate_for_date(date)` docstring says: "Top N episodes from episodic memory (importance >= threshold) **for the date**." Verified against codebase:

   ```
   grep -n "def recent\|def list_\|def by_date\|def for_date\|def in_range" src/probos/cognitive/episodic.py
     1747: async def recent_for_agent(self, agent_id: str, k: int = 5) -> list[Episode]:
     1832: async def recent(self, k: int = 10) -> list[Episode]:
   ```

   No by-date / by-time-range query exists. `recent(k)` returns the most-recent K regardless of date; `recent_for_agent(agent_id, k)` indexes by agent. The prompt does not specify whether the service should:
   - call `recent(k=top_episodes_count)` and filter Python-side by `episode.timestamp` falling within the requested date,
   - use ChromaDB metadata-filter queries (no example exists in v1),
   - or aggregate per-agent via `recent_for_agent` over the agent registry.

   Builder will face an unresolved spec at Section 2 implementation. Per convention #21, fix at draft:

   **Required:** Specify the exact retrieval pattern in Section 2's `generate_for_date` docstring. Recommended pattern given the live API: call `await self._runtime.episodic_memory.recent(k=N)` (where N is `top_episodes_count * 4` to give headroom), filter by `episode.timestamp` falling within `[date_start, date_end]` Python-side, then filter by `importance >= threshold`, then take the top `top_episodes_count` by importance. Add to Verified Against Codebase block.

3. **`status="pending"` is a phantom kwarg value (not kwarg name).** Section 3 docstring + Test #8 use `runtime.work_item_store.list_work_items(status="pending")`. AD-685 kwarg pre-check validates the kwarg NAME (`status`) but not the kwarg VALUE. Verified against codebase:

   ```
   grep -n "class WorkItemStatus\|^    [A-Z_]+\s*=" src/probos/workforce.py | head -10
       41: class WorkItemStatus(str, Enum):
       44: OPEN = "open"
       46: IN_PROGRESS = "in_progress"
       59: COMPLETED = "completed"
   ```

   Canonical "active / not yet started" status is `"open"` (initial_status of single-agent work type per workforce.py:160). There is no `"pending"` value in `WorkItemStatus`. Test #8 will pass an empty result list; Section 3's docstring will mislead Builder.

   **Required:** Replace `status="pending"` with `status="open"` in (a) Section 3 docstring under `generate_for_date`, (b) Test #8 in the Test Plan table, and (c) any incidental references. Add the live enum signature to the Verified Against Codebase footer.

## Recommended (should fix)

1. **Section 4 Pydantic config uses bare-mutable defaults.** The composite class declares:

   ```python
   class NavalOrganizationConfig(BaseModel):
       captains_log: CaptainsLogConfig = CaptainsLogConfig()
       plan_of_day: PlanOfDayConfig = PlanOfDayConfig()
   ```

   Pydantic v2 generally handles `BaseModel` instances as defaults via copy-on-instantiation, BUT Wave 5 anti-pattern list (and Wave 8 convention #17) calls out bare mutable defaults explicitly. Use the safer pattern:

   ```python
   class NavalOrganizationConfig(BaseModel):
       captains_log: CaptainsLogConfig = Field(default_factory=CaptainsLogConfig)
       plan_of_day: PlanOfDayConfig = Field(default_factory=PlanOfDayConfig)
   ```

   Same fix for `output_dir: Path = Path("data/captains_log")` if Pydantic v2 strict mode is engaged anywhere in the boot path (low priority — `Path(...)` is immutable).

2. **Verified Against Codebase block missing three asserted APIs.** Per convention #16 (mandatory pre-check audit trail):
   - No grep evidence for `runtime.ward_room.list_threads(...)` (it exists at `ward_room/service.py:289` — `async def list_threads(channel_id, limit=50, offset=0, sort="recent", include_archived=False)`; add the line).
   - No grep evidence for the dream-consolidation summary API (will be moot once Required #1 resolves).
   - No grep evidence for the episodic by-date pattern (will be moot once Required #2 resolves).

   Add explicit grep blocks for each consumer surface the v1 services touch — convention #16 is now mandatory pre-flight artifact.

3. **Test #12 should explicitly assert `CancelledError` is re-raised.** The async-discipline standing rule (and dispatch-time reminder #5) requires `catch + cleanup + re-raise` for long-running async loops. The current test name "test_stop_cancels_task_cleanly" allows a Builder to write a test that swallows `CancelledError` silently and still passes. Recommend tightening the test description to "task cancellation surfaces `CancelledError` to caller after cleanup" — Builder will then write the assertion correctly.

## Nits

1. The DECISIONS.md draft entry says "Public attributes (no underscore per Wave 5 convention #1)" — true, but consider also stating the convention number for the captains_log_start_task / plan_of_day_start_task attributes (also public, easy to miss).

2. Section 5 wiring uses `getattr(runtime.config, "naval_organization", None)` — fine, but if `Config.naval_organization` field is added (per the spec), the `getattr` defensive read is unnecessary and slightly weaker than direct access. Consider direct attribute access once the field is registered, with `if naval_cfg is None or not naval_cfg.captains_log.enabled: return` early-out.

3. Test count "~14 tests" with no failing test row for the dream-summary path. If Required #1 resolves via path (a), test count drops by zero (no test removed). If path (b), add a test for the dream consumer. Consider noting the contingency in the Test Plan.

## Verified

- **Pre-deferral honesty.** No Qualification Programs / 3M / Damage Control / SORM / scheduled-duties functionality smuggled into v1. Section 2 (CaptainsLogService) and Section 3 (PlanOfDayService) are scope-clean. The `duty_schedule_tracker` NOTE under Dependencies is correctly negative-framing (audit trail, not assertion). ✓
- **AD-566 / 539 / 595e read-only.** Grep confirms no `from probos.qualification_battery` or `from probos.gap_pipeline` imports; no `qualification_*` writes from `naval/`. AD-477b's deferral footprint is preserved. ✓
- **Section 0 EventType collision.** Grep `events.py` for `CAPTAINS_LOG_GENERATED|PLAN_OF_DAY_GENERATED` returns zero hits — clean. ✓
- **Public-attribute wiring (Wave 5 convention #1).** `runtime.captains_log_service`, `runtime.plan_of_day_service`, `runtime.captains_log_start_task`, `runtime.plan_of_day_start_task` — all no-underscore. ✓
- **Output paths don't collide with existing `data/` subdirectories.** `data/captains_log/` and `data/plan_of_day/` are not in `data/` listing. ✓
- **`runtime.work_item_store` and `runtime.episodic_memory` are public.** Verified at `runtime.py:202, 212` and via 20+ consumer call-sites. ✓
- **`runtime.ward_room.list_threads` exists.** `ward_room/service.py:289` — kwargs `channel_id`, `limit=50`, `offset=0`, `sort="recent"`, `include_archived=False`. ✓
- **AD-685 kwarg pre-check (when re-run).** Will catch `status="pending"` only as a kwarg name (which is valid). The value-drift defect is review-tier. Banked as future tooling-hygiene candidate (AD-685c/e: enum-value validation against live enum members) — log in retrospective if it recurs.
- **Layer discipline.** New `src/probos/naval/` package; no cross-layer imports flagged. Read-only consumers respect Substrate -> Mesh -> Cognitive layering.
- **Tracking section complete.** PROGRESS.md prepend, DECISIONS.md Era V entry, roadmap.md AD-477 status flip — all listed. Closes GH #71.
- **Hard-stops appropriately scoped.** #2/#3/#4 are real possible build-time discoveries; #1 is the structural-defect punt that Required #1 above resolves at draft time.

---

## Cross-AD Verification Summary

| Check | Result |
|---|---|
| AD-566 modified by v1? | NO ✓ (read-only consumer not even wired in v1; AD-477b deferred extends) |
| AD-539 modified by v1? | NO ✓ |
| AD-595e modified by v1? | NO ✓ |
| Standing Orders modified? | NO ✓ (AD-477e SORM extension deferred) |
| AD-500 / AD-500a-1 boundary respected? | YES ✓ (duty tracker NOTE preserves deferral) |
| AD-685 kwarg pre-check applicable? | YES — should mechanically pass for kwarg names; misses kwarg values (Required #3 escalates this manually) |

**Wave 9B structural-defect pattern recurrence count: 1** (`runtime.dreaming_engine` attribute existence is structurally identical to the already-mitigated `runtime.duty_schedule_tracker` phantom). Plus one new shape: phantom kwarg VALUE (`status="pending"`) that AD-685 v1 doesn't catch — bank for AD-685c/e tooling-hygiene candidate.

**Verdict logic.** 3 Required findings ⇒ ⚠️ Conditional under convention #15 (relaxed tolerance, 1 ⚠️ allowed). All three are mechanical fixes with concrete resolution paths. Recommend: revise per Required #1-3 + Recommended #1-2; second pass should converge to ✅ unless Required #1's path (b) surfaces deeper consumer-side gaps on `DreamScheduler`.
