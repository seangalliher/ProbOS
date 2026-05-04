# Wave 29 Dispatch — AD-683 v1 Ship State Snapshot for Cold-Start Onboarding

**Issue:** [#313](https://github.com/seang/ProbOS/issues/313)
**Prompt:** [`prompts/ad-683-ship-state-snapshot-v1.md`](prompts/ad-683-ship-state-snapshot-v1.md)
**Estimated tests:** 8 (six-floor + 2 for full collector-degradation coverage)
**Test count baseline:** 10912 → expected 10920
**Hard deps:** AD-638 (Boot Camp Onboarding) — shipped at HEAD `b76b8a8`. `runtime.boot_camp` and `BootCampCoordinator.activate()` both verified live.

## Wave shape

Single-prompt wave. Mirrors Wave 27 (AD-657) and Wave 28 (AD-658) cadence —
one observational data-aggregator AD shipped end-to-end with builder + capture
+ render + tests. No dependent siblings.

## What v1 ships (1-of-N per convention #14)

1. `ShipStateSnapshot` frozen dataclass + `DepartmentSummary` + `WardRoomTopicSummary` sub-dataclasses.
2. `ShipStateSnapshotBuilder` async aggregator service — read-only collectors over `runtime.ontology`, `runtime.work_item_store`, `runtime.ward_room`. Each collector is log-and-degrade.
3. `ShipStateSnapshotConfig(enabled=True)` + `SystemConfig.ship_state_snapshot` Pydantic field.
4. `_wire_ship_state_snapshot` sync wirer in `startup/finalize.py`. Public attribute `runtime.ship_state_snapshot` (the builder).
5. Capture-at-activation: `BootCampCoordinator.activate()` awaits `builder.build()` once at the end and stashes on `coord.ship_state_snapshot`.
6. DM-path render: `cognitive_agent._build_user_message` prepends `--- Ship State Snapshot ---` block when `_boot_camp_active` and snapshot present.
7. New EventType `SHIP_STATE_SNAPSHOT_CAPTURED` (counts-only payload — no titles, no department names, no thread bodies).

## Deferred (explicitly out-of-scope for v1)

- AD-683b — per-agent personalization (filter snapshot to agent's department/billet)
- AD-683c — snapshot deltas / refreshes within a single boot-camp run
- AD-683d — federation sync of snapshot across nodes
- AD-683e — chain-path injection (ANALYZE / EVALUATE / COMPOSE)
- AD-683f — Ward Room post-path injection
- AD-683g — snapshot persistence (ChromaDB / disk / journal)
- `PlanOfDayService` (AD-477) refactor to share aggregator — only if AD-683b adoption justifies extraction.

## Data sources & their public APIs (verified at HEAD `b76b8a8`)

| Snapshot field | Source attribute | Public API |
|---|---|---|
| `vessel_name`, `uptime_seconds`, `active_crew_count` | `runtime.ontology` | `get_vessel_identity()` + `get_vessel_state()` (service.py:84, :91) |
| `alert_condition` | `runtime.ontology` | `get_alert_condition() -> str` (service.py:102) |
| `departments` | `runtime.ontology` | `get_departments() -> list[Department]` (service.py:122) + `get_crew_agent_types()` / `get_assignment_for_agent()` / `get_post_for_agent()` for crew-count derivation (verified via runtime.py:833-870 call-sites) |
| `open_work_item_count`, `open_work_item_titles` | `runtime.work_item_store` | `await list_work_items(status="open", limit=5)` (workforce.py:1066) |
| `recent_ward_room_topics` | `runtime.ward_room` | `await list_channels()` (service.py:241) + `await list_threads(channel_id, limit=3, sort="recent")` (service.py:288) |

## Phantom-API pre-check

```
pwsh scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-683-ship-state-snapshot-v1.md
=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0
```

**Clean — 0 candidates.** Script's intra-prompt-symbol-introduction handling
correctly recognized `ShipStateSnapshot`, `ShipStateSnapshotBuilder`,
`DepartmentSummary`, `WardRoomTopicSummary`, `runtime.ship_state_snapshot`,
`ShipStateSnapshotConfig`, `SystemConfig.ship_state_snapshot`,
`_wire_ship_state_snapshot`, and `EventType.SHIP_STATE_SNAPSHOT_CAPTURED` as
defined within the prompt itself. All consumed APIs (ontology / work_item_store
/ ward_room / cognitive_agent / boot_camp / events / config) verified live in
the prompt's `## Verified Against Codebase` footer.

## Standing rules (re-stated for Wave 29)

- Test gate: `pytest tests/ -q -n 8 --dist=loadfile`. Triage gate: `-n 0`.
- Hard-stop conditions: phantom API in implementation; architectural change
  required (modify BaseAgent / IntentMessage / runtime startup ordering past
  the documented `getattr(..., None)` guard); tests fail under serial after
  passing under parallel (rare — almost always the reverse).
- Watch for the **wirer-startup-ordering** subtlety documented in Section 5c:
  `_wire_ship_state_snapshot` runs in `finalize_startup`; `BootCampCoordinator`
  construction at runtime.py:1580 happens during `start()`. The
  `getattr(self, "ship_state_snapshot", None)` guard makes either ordering
  safe — Builder is observational; if the builder is None at coordinator
  construction, snapshot stays None forever for that run. **At build time,
  decide whether to move the wirer earlier.** Default: leave the wirer in
  `finalize_startup` and accept None-snapshot for first activation; document
  in PROGRESS.md if the build flips to early-wire.
- Privacy: `SHIP_STATE_SNAPSHOT_CAPTURED` payload contains COUNTS ONLY. Do
  NOT add titles, department names, channel names, or thread bodies. This
  mirrors the AD-530 / AD-478 privacy invariant (term length, not term
  content). Test 4 directly asserts this.
- Convention #15 swallow tier in cognitive_agent injection: `render_text`
  failure must not break `_build_user_message`. Logged at `debug` level
  (not warning — the snapshot is purely additive).

## Common false positives to NOT flag

- "`runtime.ship_state_snapshot` is missing" — introduced by Section 4 wirer.
- "`SHIP_STATE_SNAPSHOT_CAPTURED` enum value missing" — introduced by Section 0.
- "`SystemConfig.ship_state_snapshot` field missing" — introduced by Section 3.
- "`ShipStateSnapshotConfig` class missing" — introduced by Section 3.
- "`BootCampCoordinator.ship_state_snapshot` attribute missing" — introduced by Section 5a.
- "`_wire_ship_state_snapshot` function missing" — introduced by Section 4.
- "`probos.onboarding` package missing" — introduced by Section 1.
- "`Any | None` for `ship_state_builder`/`ship_state_snapshot` typings in `BootCampCoordinator`" — intentional forward-reference circular-import avoidance; documented in Section 5a.

## Wave plan state

`prompts/wave-plan.yaml` Wave 29 entry already retargeted to AD-683 (see
pending diff committed alongside this draft). `id="29"`, `title="AD-683 v1
Ship State Snapshot for Cold-Start Onboarding"`, `prompt_paths` updated,
`issues_to_close=[313]`, `status: pending`.

## Tracking on close

- `progress-era-4-evolution.md` — append new CLOSED entry at top, mirror Wave 28 (AD-658) format.
- `docs/development/roadmap.md` line 7086 — flip AD-683 entry to *(Complete, OSS, Issue #313)* with delivered-summary paragraph.
- `DECISIONS.md` — no new entry (single-AD v1, sibling-pattern shipped, no architectural choice requires preservation).
- `PROGRESS.md` line 102 — leave the existing renumber-resolution note in place; AD-683 closure is recorded in the era file.

## Build report

After build commit, append a build report to `prompts/build-reports/wave-29.md`
with: test count delta, hard-stop count, phantom-API recurrence count (expected
0), pre-flight ordering decision (wirer left late vs moved early), and any
review-time anti-patterns caught.
