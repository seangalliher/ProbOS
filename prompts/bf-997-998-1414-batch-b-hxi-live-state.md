# BF-997 / BF-998 -- #1414 Batch B: HXI live state (B1, B2, B3)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-25
**Status:** ready to build. **Base:** `fc57a8b2` (Batch A's merge, tree `a96ffd10`). The pairs were drafted against `8447d6ef` and re-proved on the post-A tree (see 'Re-proof on the post-Batch-A base'); 6.8 and 6.9 are anchored on Batch A's text. **Issue:** #1414 items 8, 11, 12, 14. **Suggested path:** `prompts/bf-997-998-1414-batch-b-hxi-live-state.md`. **Estimated tests:** 1 new Python file (5 cases), 1 new vitest file (1 case), 1 Playwright spec gains one stubbed read, one assertion and a re-pinned list of denied reads, 1 existing pin updated with its reason inline.

## 1. Problem

- **Item 11.**
  - `MAX_WORKFORCE_ITEMS = 100` (`src/probos/ws_event_stream.py:41`). The seam `list_ws_visible_work_items` has no status filter and returns up to 101 rows as an overflow sentinel (`src/probos/workforce.py:7869-7898`).
  - When 101 rows come back, `build_ws_workforce_snapshot` raises `ws_workforce_source_overflow` (`src/probos/routers/workforce.py:115-117`). `serve` then accepts and immediately ends the socket with 1013 "snapshot unavailable" (`ws_event_stream.py:659-667`).
  - The HXI's `onopen` resets the backoff to 1 s on every attempt, and `onclose` drops the live authority and reconnects after that delay (`ui/src/hooks/useWebSocket.ts:32-36`, `:49-63`; probe P2). So once a vessel has more than 100 board-visible items, every tab reconnects about once a second and receives no live event of any kind.
- **Item 12.**
  - Both drop sites request the resync marker only for correlated tool events (`ws_event_stream.py:380-396` at ingress, `:571-586` at the final envelope).
  - A work-item frame over 256 KiB, or a `crew_session_projection` over 256 KiB (the projector publishes through `_publish_projector` -> `_publish_delta`, `:546-554`), is dropped silently. The HXI's view of that work stays stale until something else re-reads it.
- **Item 14.**
  - `hydrateCrewSession` returns false when a live write to the parent lands after the read was issued (`ui/src/store/useStore.ts:2323-2326`). `NotificationCard` ignores that result: it opens the room and sets a focus request (`ui/src/components/bridge/BridgeNotifications.tsx:183-192`).
  - With no session cached, the panel renders no session band (`ui/src/components/crew/CrewCollaborationPanel.tsx:794-798`, `:835-842`). The focus step therefore returns early (`ui/src/components/profile/ProfileChatTab.tsx:1019-1020`).
  - The effect does not run again when the band mounts later, so the request stays pending with its destination set.
- **Item 8.**
  - The task rail asks the owned-steps route first and reads the legacy checklist only for an unmanaged parent (`ui/src/components/workspace/WorkspaceFilesRail.tsx:403-424`).
  - `taskViewportFixture` answers only the legacy `/steps?limit=1001` read (`ui/e2e/conversation-viewport.spec.ts:842`). The isolation helper aborts any read it has no answer for (`ui/e2e/_helpers.ts:226-227`).
  - So every `task matrix:` test (`:956`) stops at `:1156`.

## 2. Solution

- **B1.**
  - The router slices the seam's result to `limit` (D1).
  - A module-level `_resyncs_on_drop` (correlated tool events, plus identified work-state events) replaces `_is_correlated_tool_event` at the two drop sites (D2).
  - Inside `WSEventStreamHub` only two conditions and their log text change. The class span stays 492, under the 500 trigger.
  - Rejected: new branches in the hub (they cross the trigger and move the architecture baseline), and a wire flag (D1).
- **B2.** One guard before the room opens (D3). The store, the fence and `ProfileChatTab.tsx` are unchanged.
- **B3.** One canned unmanaged answer, one assertion, and the baseline's denied list re-pinned (D4). No workflow change.

## 3. Decisions

D1 to D7 as stated above this contract; they are recorded in `DECISIONS.md` (6.9).

## 4. Milestones and commit subjects

| M | Slice | Files | Commit subject |
|---|---|---|---|
| M1 | B1 | `src/probos/routers/workforce.py`, `src/probos/ws_event_stream.py`, `tests/test_ad1133_live_crew_session_refresh.py` (one pin), new `tests/test_bf997_ws_snapshot_and_work_state_resync.py` | `the HXI event stream keeps the socket past 100 work items and asks for a resync when it drops a work-state frame (#1414 B1)` |
| M2 | B2 | `ui/src/components/bridge/BridgeNotifications.tsx`, new `ui/src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx` | `a notification's room read refused by the live fence navigates nowhere and offers a retry (#1414 B2)` |
| M3 | B3 | `ui/e2e/conversation-viewport.spec.ts` | `the issue1369 Playwright suite answers the owned-steps read the task rail makes and re-pins the baseline's denied reads (#1414 B3)` |
| M4 | trackers and generated artifacts | `PROGRESS.md`, `DECISIONS.md`, `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` (generated) | `trackers and generated artifacts for #1414 Batch B` |

**Overlap with Batch A** (A's file list as given in the brief):

| File or artifact | On Batch A's list | Action on the post-A base |
|---|---|---|
| `PROGRESS.md` | yes | 6.8 anchors on `# ProbOS Progress`; B's lines go above A's. Re-prove. |
| `DECISIONS.md` | yes | 6.9 anchors on A's heading. Re-prove. |
| ledger pair | yes | Regenerate at M4. |
| `src/probos/routers/workforce.py`, `src/probos/ws_event_stream.py`, `tests/test_ad1133_live_crew_session_refresh.py`, `ui/src/components/bridge/BridgeNotifications.tsx`, `ui/e2e/conversation-viewport.spec.ts`, both new test files | no | Re-prove anyway (cheap). |
| `architecture-baseline.yaml`, config facade baseline, config reference, config profiles, `file_durations.json`, event-type tables, route inventory | A moves only the facade baseline | This batch moves none of them (section 7). |

## 5. Builder may / may not; Gates

**The Builder may:**
- if importing `_FakeWebSocket`, `_Runtime` or `_wait_until` from `tests/test_ad1133_live_crew_session_refresh.py` fails collection, copy those three helpers into the new file verbatim, with a comment naming their source;
- if P6 shows that the owned-steps read carries a query string, key the canned answer on that exact key (nothing else changes);
- rewrap a comment to the line length.

**The Builder may not:**
- add or remove any line inside `class WSEventStreamHub`. The span must stay at 492; `scripts/check_architecture_principles.py --check` proves it.
- change `MAX_WORKFORCE_ITEMS`, the seam `list_ws_visible_work_items` or its SQL, or the snapshot's keys;
- touch `useStore.ts`, `workItemReconciliation.ts`, `liveReadFence.ts`, `useWebSocket.ts`, `ProfileChatTab.tsx` or `CrewCollaborationPanel.tsx`;
- change the baseline's denied list other than by 6.7 P-2, make it anything but an exact sorted equality, or add a fixture to the baseline test; or add a Playwright suite to `.github/workflows/ci.yml`;
- weaken or delete any existing assertion other than the pin in 6.3, which carries its reason inline;
- add `hasattr` or `getattr` guards, or any configuration field.

**Hard stop (return to the Architect):** after M3, P6 shows any failing test, or the baseline's denied set differs from 6.7 P-2's list in any run. A missing thread read would mean its timing is not settled; do not loosen the list, return.

**Focused gates.** Python is `d:/ProbOS/.venv/Scripts/python.exe`, always with `-n 0`. Run UI commands in `ui/` with the linked `node_modules`.
- **M1:**
  - `-m pytest tests/test_bf997_ws_snapshot_and_work_state_resync.py tests/test_ad1133_live_crew_session_refresh.py tests/test_issue1375_work_state_reconciliation.py tests/test_ad1174_live_tool_progress.py -q -n 0`
  - `-m pytest tests/test_workforce.py -k list_ws_visible_work_items -q -n 0`
  - `scripts/check_architecture_principles.py --check`
  - consumer regression (no UI file changes): `npx vitest run src/store/__tests__/workItemReconciliation.test.ts src/hooks/useWebSocket.test.ts`
- **M2:**
  - `npx vitest run src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx src/components/bridge/__tests__/BridgeNotifications.test.tsx src/components/bridge/__tests__/BridgeNotifications.preClear.test.tsx src/__tests__/WorkStateReconciliation.issue1375.test.tsx`
  - `npx tsc -b`
  - `-m pytest tests/test_ad1214_decision_pre_clearance.py -k agree_on_the_offer_marker -q -n 0`
- **M3 (probe P6; port 5189 free, or set `PROBOS_ISSUE1369_PORT`; each tree needs its own `npm ci`, because Vite refuses to serve a module that a linked `node_modules` places outside the project root):**
  - A/B red on the base: `npx playwright test -c playwright.issue1369.config.ts` (about 12 minutes on the base, 8 on a green tree). Measured on `8447d6ef` (Playwright 1.60, Chromium, Windows; two runs, `--grep-invert "task matrix"` and `--grep "task matrix"`): 71 tests, 33 failed and 38 passed.
    - All 32 `task matrix:` tests fail at `conversation-viewport.spec.ts:1156` (`await expect.poll(() => isolation.deliveries.map(delivery => delivery.key)).toContain(stepKey)`: "Error: expect(received).toContain(expected) // indexOf"), 12 to 15 s each. The poll for `GET /api/work-items/viewport-group-task/steps?limit=1001` never arrives, because the rail asks the owned-steps route first and the isolation helper aborts it.
    - The baseline test `baseline: fresh desktop Alpha conversation preserves usable chat and Send` fails at `:379`: its pinned denied list differs from the reads the app makes now (one pinned read is no longer requested and three are requested and not pinned; 6.7 P-2).
  - Green after M3: the same command gives "71 passed" and 0 failed. Measured on the post-A oracle: "71 passed (7.3m)".
- **After M3, UI batch gates (outside `run_test_gate.py`):** `npx tsc -b`, then `npx vitest run`.
- **M4:** the commands in section 7, then `-m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

**Broad gate:** once, after M4: `scripts/run_test_gate.py --label 1414-batch-b --receipt logs/gates/1414-batch-b.receipt.json`.

**A/B red on `8447d6ef`:**
- Three of the five cases in the new Python file are red there, each at the assertion its comment names. The two rows of `test_a_drop_that_names_no_work_row_keeps_the_silent_drop` are guard rows and are green on both (measured on `8447d6ef`: 3 failed, 2 passed).
- The updated `test_ad1133` pin is red there, because the function raises.
- The vitest case is red there: the status reads "Room context opened.".

## Re-proof on the post-Batch-A base (orchestrator, 2026-11-25)

Batch A merged as `fc57a8b2` (tree `a96ffd10`). It changes none of the files of 6.1 to 6.7 and no file under `ui/` (the blobs are identical on `8447d6ef` and `fc57a8b2`; `ui/package-lock.json` too), so the pairs of 6.1 to 6.7 apply unchanged. The oracle is the post-A tree plus the pairs of M1 to M3. Measured:
- M1: the four-file Python list 160 passed; `-k list_ws_visible_work_items` 8 passed; `scripts/check_architecture_principles.py --check` passes (srp-size 90) and the hub span is 492; `npx vitest run src/store/__tests__/workItemReconciliation.test.ts src/hooks/useWebSocket.test.ts` 165 passed.
- M2: the four vitest files 77 passed; `npx tsc -b` clean; `test_ad1214_decision_pre_clearance.py -k agree_on_the_offer_marker` 1 passed.
- M3: Playwright, the candidate, "71 passed (7.3m)". The base run (33 failed, 38 passed) is not repeated: no `ui/` file differs between the two bases.
- A/B on the clean post-A base: the new Python file's three red cases and the updated `test_ad1133` pin fail (4 failed, 129 passed over the two files), and the vitest case fails ("Room context opened.").
- Mutation census (section 7): 17 of 17 rows killed (B1 9, B2 5, B3 3), the baseline clean, each verdict equal to the census on `8447d6ef`.

## Verified Against Codebase (2026-11-25)

```
src/probos/ws_event_stream.py (781 lines)
  41 MAX_WORKFORCE_ITEMS = 100; 58-62 _WORK_ITEM_EVENTS; 69-83 _is_correlated_tool_event (only callers :380, :572)
  241-249 build_ws_state_snapshot; 291 class WSEventStreamHub (span 291-782 = 492); 307-314 projector publish=_publish_projector
  358-365 request_resync (coalesced flag); 367-396 ingress (380-390 tool resync, 391-396 silent drop); 401-407 ingress overflow resync
  526-534 route failure resync; 546-554 _publish_projector; 556-589 _publish_delta (571-580 tool resync, 581-586 silent drop)
  591-620 resync marker; 643-667 serve (659-667 snapshot failure -> 1013 "snapshot unavailable"); 751-781 stop
src/probos/routers/workforce.py  106-122 build_ws_workforce_snapshot (115-117 raise); 440-513 get_owned_work_item_steps (485-507 unmanaged shape, ordinal 1-based)
src/probos/workforce.py  2761-2780 WorkItemStore(emit_event=...); 3285-3294 _event_work_item_projection ({} for None); 7662-7706 create_work_item; 7776-7779 emits WORK_ITEM_CREATED; 7869-7898 seam (ORDER BY priority ASC, created_at DESC, id ASC; LIMIT limit+1); 941-952 WorkItem (no description cap)
src/probos/crew_session_live.py  212,219 self._publish; 271-272, 363-374 existing resyncs; 278-347 route_event; 440-441 _publish("crew_session_projection", ...)
src/probos/protocols.py:47-49  _emit -> self._emit_event(event_type, data)
ui/src/hooks/useWebSocket.ts  32-36 onopen resets backoff; 49-63 onclose clears liveGeneration, reconnects (P2)
ui/src/store/useStore.ts  1367-1379 isStateSnapshotData (no workforce check); 2322-2340 beginLiveRead, hydrateCrewSession (2326 fence false)
  3241-3251 snapshot -> observeItemEpoch; 3260-3268 resync_required -> liveRepairEpoch+1, observeItemEpoch; 3401-3410 workforce -> applySnapshotRows
  3420-3465 crew_session_projection reducer; 4211-4218 workItemReconciler
ui/src/store/workItemReconciliation.ts  370-374 observeItemEpoch -> repair; 377-394 applySnapshotRows (upsert only); 430-438 repair; 455-467 markStale
ui/src/store/liveReadFence.ts  53-57 observe; 64-68 accepts; 79-85 resetLiveReadFenceForTests; ui/src/test/setup.ts:26-30 resets per test
ui/src/components/bridge/BridgeNotifications.tsx  96-194 handleOpen (116-127 cancel; 154 beginLiveRead; 163 pending=null; 183-185 setChatThread/hydrate/open); 341-345 Retry shown when message has "unavailable" or "cancelled"
ui/src/components/profile/ProfileChatTab.tsx  1006-1036 focus effect (1019-1020 band not connected -> return); 2436-2446 band ref passed to the panel
ui/src/components/crew/CrewCollaborationPanel.tsx  599-603 cached session; 759-761 reload on liveRepairEpoch; 794-798, 835-842 band only with a session
ui/src/components/workspace/WorkspaceFilesRail.tsx  403-424 owned-steps first, legacy steps when unmanaged; 841-848 confirm via updateTaskStep; 1154-1183 TodosList when not managed/error/loading
ui/src/components/workspace/ownedStepsApi.ts  105-116 UnmanagedOwnedStepsView (exported); 222-237 decodeTodo; 372-391 decodeUnmanaged (exact keys, <=20 rows); 441-459 fetchOwnedSteps (no query by default)
ui/e2e/conversation-viewport.spec.ts  9-10 type imports; 379-388 baseline exact denied list; 759-850 taskViewportFixture (841-842); 956 task matrix; 1155-1157; 1198-1202 writes list; 1231 write-denial assertion
ui/e2e/_helpers.ts  188-228 fixtures by exact "METHOD path?query" key, else abort
ui/tsconfig.json:21 include ["src"]; ui/vitest.config.ts:15 excludes e2e/**; ui/playwright.issue1369.config.ts:3,11,34-38; ui/vite.issue1369.config.ts:4
scripts/check_architecture_principles.py  187 SRP_MAX_BODY_LINES = 500; 188 SRP_MAX_DIRECT_METHODS = 15; 559-569 span = end_lineno - lineno + 1
docs/development/architecture-baseline.yaml:1037-1044  probos.ws_event_stream::WSEventStreamHub triggers [methods]
scripts/run_test_gate.py:1097-1130  preflight phases (Python only; no tsc/vitest)
scripts/gen_ad_ledger.py  126-139 status words, 120-char head; 217-220 DECISIONS heading with no status word = shipped
tests/test_ad1133_live_crew_session_refresh.py  172-258 _Runtime; 398-426 _FakeWebSocket; 440-445 _wait_until; 448-491 tool drop resync; 494-529 unidentifiable tool drop; 564-575 work_store; 616-630 overflow pin; 1434-1461 hostile event type; 2334-2359 agents overflow 1013
tests/test_issue1375_work_state_reconciliation.py:94  zero resync_required in the native_failed scenario
tests/test_workforce.py:626-641  seam sentinel pin (unchanged)
tests/test_ad1214_decision_pre_clearance.py:1183-1186  reads two constant lines of BridgeNotifications.tsx
ui/src/components/bridge/__tests__/BridgeNotifications.test.tsx:11,111-120  ?raw emoji check
ui/src/__tests__/WorkStateReconciliation.issue1375.test.tsx:1190-1224  fenced read with a cached live session still opens
ui/src/store/__tests__/workItemReconciliation.test.ts:488, 1388, 1403-1420  snapshot upsert-only; resync re-reads
prompts/archive/ad-1133-live-crew-session-thread-refresh.md:256, 272-274  "Any source overflow closes 1013"; "Overflow closes 1013"
DECISIONS.md:3864  ### AD-1133 (2026-07-23) - bounded live CrewSession and room refresh (#1052)
```

**P9, every drop site, by family:**

| Site | Families that reach it | Today | After B1 |
|---|---|---|---|
| `ws_event_stream.py:380-390` ingress | identified `agentic_tool_call_started/completed` | resync | unchanged |
| `:391-396` ingress | every other runtime event, the three work-item events included | silent | a work-item event naming `work_item.id` resyncs; the rest silent |
| `:571-580` final envelope | identified tool events | resync | unchanged |
| `:581-586` final envelope | runtime events routed `publish` (`crew_session_live.py:302-303,318,333,342-347`) and the projector's `crew_session_projection` (`:440`) | silent | a work-item event naming its id, and a projection naming `parent_id`, resync; the rest silent |
| Already resync (not `Dropped` sites) | ingress overflow `:401-407`, route failure `:526-534`, projector backlog `crew_session_live.py:271-272`, projection error `:363-374`, client queue `ws_event_stream.py:630-641` | resync or 1013 | unchanged |

## Absence Verified (2026-11-25)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Nothing in the UI would read a truncation flag | Grep `work_items_truncated\|workforce\.work_items\|wf\.work_items\|\.workforce` in `ui/` (excluding node_modules) | `useStore.ts:3402-3410` only (plus an unrelated `ad1192_backend.py:44` import) | yes |
| `build_ws_workforce_snapshot` has one production caller | Grep `build_ws_workforce_snapshot\|ws_workforce_source_overflow\|MAX_WORKFORCE_ITEMS` over the repo | `ws_event_stream.py:22,41,244-246`; tests `test_ad1133:30,610,629-630,654`; the archived prompt | yes |
| No test pins a silent work-item drop | Grep `Dropped\|prior state\|_finalize_frame\|_publish_delta\|_prepare_ingress\|resync_required` in `tests/` | `test_ad1133:459-484,1996,2490,2636,2714`; `test_ad1359:302-305`; `test_issue1375:94` (no oversized frame there) | yes |
| No test or script reads the text of the two Python files | Grep `ws_event_stream\.py\|routers/workforce\.py\|crew_session_live\.py` in `tests/`, `scripts/` | docstring citations only: `test_ad1275:697`, `test_bf900:601` (`routers/workforce.py:223`, which drifts by +2 lines; not asserted) | yes |
| No test or script reads the drop log text | Grep `Dropped correlated\|progress delivery is incomplete\|_is_correlated_tool_event` over the repo | `ws_event_stream.py` only | yes |
| No `?raw` or `readFileSync` of `useStore.ts` | Grep `\?raw\|readFileSync` in `ui/` | none of `useStore`; `BridgeNotifications.tsx?raw` at `BridgeNotifications.test.tsx:11` (emoji only) | yes |
| The workforce 1013 clause is written only in the AD-1133 prompt | Grep `1013\|Overflow closes\|source_overflow` in `docs/**/*.md`, `DECISIONS.md`, `prompts/archive/ad-1133-*.md` | `ad-1133-...md:174,216,256,272-274,523`; `DECISIONS.md:5040-5042` is AD-1013 | yes |
| Only `taskViewportFixture` serves a task | Grep `taskViewportFixture\(\|crew-tasks\|fixtures\.set\(\`GET /api/work-items` in the spec | `:759,842,967` | yes |
| e2e is outside `tsc -b` and vitest | Read `ui/tsconfig.json`, `ui/vitest.config.ts` | include `["src"]`; exclude `e2e/**` | yes |
| No workflow runs Playwright | Grep `playwright` (case-insensitive) in `.github/workflows` | `ci.yml:53` comment only | yes |
| A new test file needs no durations entry | Read `tests/test_ci_shards.py:499-508` | unknown files are weighed at the known mean | yes |
| BF-997 and BF-998 are free | Glob `prompts/**/bf-99*`; `git log --all -i --grep "BF-99[7-9]"`; Grep `BF-99[7-9]` in the trackers and `docs/development/`; `gh issue list --state all --search` | top is `bf-993`; none; none; no title hit | yes |

## Prior Art and Blind Spots

- **External search:** skipped. This is ProbOS-specific hub and HXI plumbing. Internal prior art: the AD-1133 contract (bounded snapshot, resync marker) and the #1375 reconciliation design (upsert-only snapshot, a repair epoch on every snapshot). B1 extends both rather than adding a new mechanism.
- **Blind spots:**
  1. One work item whose string field exceeds 65,536 characters, or a snapshot over 1 MiB, still ends the socket with 1013 on every reconnect (`ws_event_stream.py:659-667`, `_bounded_string` `:91-104`). The tab is blind in the same way, but this is latent.
     - Recommendation: a #1820 row.
     - Not done here: it needs per-row detaching in the router, and the router cannot import the wire module (`ws_event_stream.py:22` imports the router).
  2. `useWebSocket.ts` resets its backoff on each `onopen`, so any socket the server accepts and then ends is retried about once a second (P2). Considered, deferred: a #1820 row.
  3. More than 1,000 agents still ends the socket with 1013, by design (`test_ad1133:2334-2359`).
  4. The projector's classification drops (`crew_session_live.py:286-314`) are not size drops and stay silent.
  5. A projection without `parent_id` never comes from the projector, so the `parent_id` check has no killer (review property B1-8).

## 6. Pairs

### 6.1 `src/probos/routers/workforce.py` (M1)

**P-1**
SEARCH:
```
    visible_items = await store.list_ws_visible_work_items(limit=limit)
    if len(visible_items) > limit:
        raise ValueError("ws_workforce_source_overflow")
    return {
```
REPLACE:
```
    # #1414 item 11: past the cap the snapshot carries the first ``limit`` rows in the
    # store's order (priority, then newest) instead of failing the whole socket. The
    # HXI upserts snapshot rows without removing any and re-reads every bucket on each
    # snapshot, so a partial list is correct and the rest arrives by REST.
    visible_items = (await store.list_ws_visible_work_items(limit=limit))[:limit]
    return {
```

### 6.2 `src/probos/ws_event_stream.py` (M1)

**P-1** (module level, outside the hub)
SEARCH:
```
    return all(
        type(data.get(key)) is int and data[key] >= 0
        for key in ("iteration", "tool_call_index")
    )


@dataclass(slots=True)
class _DetachBudget:
```
REPLACE:
```
    return all(
        type(data.get(key)) is int and data[key] >= 0
        for key in ("iteration", "tool_call_index")
    )


def _resyncs_on_drop(event_type: object, data: object) -> bool:
    """Whether a dropped frame asks every client for the existing resync marker.

    A correlated tool event does. Since #1414 item 12 so does a work-item frame
    naming its ``work_item.id``, or a crew-session projection naming its
    ``parent_id``: dropping one leaves the HXI's view of that work stale until
    something else re-reads it. A drop that names no row keeps clients on their
    prior state.
    """
    if _is_correlated_tool_event(event_type, data):
        return True
    if type(event_type) is EventType:
        event_type = event_type.value
    if type(event_type) is not str or type(data) is not dict:
        return False
    if event_type in _WORK_ITEM_EVENTS:
        record, key = data.get("work_item"), "id"
    elif event_type == "crew_session_projection":
        record, key = data, "parent_id"
    else:
        return False
    if type(record) is not dict:
        return False
    value = record.get(key)
    return type(value) is str and bool(value.strip()) and len(value) <= 128


@dataclass(slots=True)
class _DetachBudget:
```

**P-2** (ingress; same line count)
SEARCH:
```
            if _is_correlated_tool_event(
                raw_event_type, event.get("data") if type(event) is dict else None,
            ):
                logger.warning(
                    "Dropped correlated tool event type %s because bounded wire "
                    "finalization failed; progress delivery is incomplete and "
                    "the existing resync marker is requested",
                    event_name,
                )
```
REPLACE:
```
            if _resyncs_on_drop(
                raw_event_type, event.get("data") if type(event) is dict else None,
            ):
                logger.warning(
                    "Dropped event type %s because bounded wire finalization "
                    "failed; the delivery is incomplete and the existing resync "
                    "marker is requested",
                    event_name,
                )
```

**P-3** (final envelope; same line count)
SEARCH:
```
            if _is_correlated_tool_event(event_type, data):
                logger.warning(
                    "Dropped correlated tool event type %s because its final bounded "
                    "envelope was invalid; progress delivery is incomplete and "
                    "the existing resync marker is requested",
                    event_type,
                )
```
REPLACE:
```
            if _resyncs_on_drop(event_type, data):
                logger.warning(
                    "Dropped event type %s because its final bounded envelope "
                    "was invalid; the delivery is incomplete and the existing "
                    "resync marker is requested",
                    event_type,
                )
```

### 6.3 `tests/test_ad1133_live_crew_session_refresh.py` (M1)

**P-1**
SEARCH:
```
async def test_ws_workforce_snapshot_ordinary_overflow_is_stable(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    for index in range(101):
        await work_store.create_work_item(
            id=f"ordinary-{index:03d}",
            title="Ordinary",
            created_at=float(index),
            updated_at=float(index),
        )
    runtime = _Runtime(tmp_path, work_items=work_store)

    with pytest.raises(ValueError, match="^ws_workforce_source_overflow$"):
        await build_ws_workforce_snapshot(runtime, limit=100)
```
REPLACE:
```
async def test_ws_workforce_snapshot_ordinary_overflow_is_stable(
    tmp_path: Path,
    work_store: WorkItemStore,
) -> None:
    # BF-997 (#1414 item 11) supersedes AD-1133's "Overflow closes 1013" for the
    # workforce source: past the cap the snapshot keeps the first 100 rows in the
    # store's order (newest first here), and the HXI re-reads the rest by REST.
    # Every other snapshot overflow still ends the socket with 1013
    # (test_snapshot_source_overflow_closes_1013_without_partial_frame).
    for index in range(101):
        await work_store.create_work_item(
            id=f"ordinary-{index:03d}",
            title="Ordinary",
            created_at=float(index),
            updated_at=float(index),
        )
    runtime = _Runtime(tmp_path, work_items=work_store)

    snapshot = await build_ws_workforce_snapshot(runtime, limit=100)

    assert [item["id"] for item in snapshot["work_items"]] == [
        f"ordinary-{index:03d}" for index in range(100, 0, -1)
    ]
```

### 6.4 `tests/test_bf997_ws_snapshot_and_work_state_resync.py` new file (M1)

```python
"""BF-997 (#1414 items 11 and 12): the HXI event stream past 100 work items, and dropped work-state frames.

Item 11: past the 100-row cap the WebSocket snapshot carries the first 100 rows in the
store's order instead of ending the socket with 1013. Item 12: a dropped work-item frame,
or a dropped crew-session projection, that names its row requests the existing resync
marker; a drop that names no row keeps the silent drop. Real WorkItemStore and the real
WSEventStreamHub on the AD-1133 test websocket.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.workforce import WorkItemStore
from probos.ws_event_stream import MAX_FRAME_BYTES, WSEventStreamHub
from tests.test_ad1133_live_crew_session_refresh import _FakeWebSocket, _Runtime, _wait_until

OVERSIZED = "x" * (MAX_FRAME_BYTES + 1)


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[tuple[_Runtime, WorkItemStore]]:
    """A runtime whose real WorkItemStore emits its post-commit events to the runtime's listeners."""
    runtime = _Runtime(tmp_path)
    store = WorkItemStore(
        db_path=str(tmp_path / "work.db"),
        emit_event=runtime.emit,
        connection_factory=SQLiteConnectionFactory(),
        tick_interval=1_000,
    )
    await store.start()
    runtime.work_item_store = store
    try:
        yield runtime, store
    finally:
        await store.stop()


async def _serve(runtime: _Runtime) -> tuple[WSEventStreamHub, _FakeWebSocket, asyncio.Task[None]]:
    hub = WSEventStreamHub(runtime)
    await hub.start()
    runtime.add_event_listener(hub.ingress)
    socket = _FakeWebSocket()
    connection = asyncio.create_task(hub.serve(socket))
    return hub, socket, connection


async def _stop(hub: WSEventStreamHub, connection: asyncio.Task[None]) -> None:
    await hub.stop()
    await asyncio.gather(connection, return_exceptions=True)


async def test_a_snapshot_past_the_cap_carries_the_first_100_rows_and_the_socket_stays_live(
    wired: tuple[_Runtime, WorkItemStore],
) -> None:
    runtime, store = wired
    for index in range(101):
        await store.create_work_item(
            id=f"ordinary-{index:03d}",
            title="Ordinary",
            created_at=float(index),
            updated_at=float(index),
        )
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: bool(socket.sent) or socket.close_code is not None)
        # A/B: on the base the hub ended the socket with 1013 "snapshot unavailable" and sent nothing.
        assert socket.close_code is None
        snapshot = json.loads(socket.sent[0])
        assert snapshot["type"] == "state_snapshot"
        workforce = snapshot["data"]["workforce"]
        # The store orders by priority, then newest first: the oldest row is the one left out.
        assert [row["id"] for row in workforce["work_items"]] == [
            f"ordinary-{index:03d}" for index in range(100, 0, -1)
        ]
        # No new wire field: the HXI needs none (D1).
        assert set(workforce) == {"work_items", "bookings", "resources"}
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) == 2)
        delivered = json.loads(socket.sent[1])
        assert delivered["type"] == "system_mode"
        assert delivered["stream"] == {"generation": hub.generation, "sequence": 1}
        assert socket.close_code is None
    finally:
        await _stop(hub, connection)


async def test_a_dropped_work_item_frame_requests_the_resync_marker(
    wired: tuple[_Runtime, WorkItemStore],
) -> None:
    runtime, store = wired
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        # The real store commits the row, then emits work_item_created past the 256 KiB frame bound.
        await store.create_work_item(id="oversized", title="Oversized", description=OVERSIZED)
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) >= 2)
        # A/B: on the base the frame was dropped silently and system_mode arrived here as sequence 1.
        marker = json.loads(socket.sent[1])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"] == {"generation": hub.generation, "sequence": 1}
        await _wait_until(lambda: len(socket.sent) == 3)
        following = json.loads(socket.sent[2])
        assert following["type"] == "system_mode"
        assert following["stream"]["sequence"] == 2
        assert await store.get_work_item("oversized") is not None
    finally:
        await _stop(hub, connection)


async def test_a_dropped_crew_session_projection_requests_the_resync_marker(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        # The projector publishes through the callback the hub gave it; this is that path.
        publish = hub._projector._publish
        assert publish == hub._publish_projector
        publish(
            "crew_session_projection",
            {"parent_id": "parent", "thread_id": "room", "goal": OVERSIZED},
            hub.generation,
        )
        runtime.emit("system_mode", {"mode": "active"})
        await _wait_until(lambda: len(socket.sent) >= 2)
        # A/B: on the base the projection was dropped silently and system_mode arrived here.
        marker = json.loads(socket.sent[1])
        assert marker["type"] == "resync_required" and marker["data"] == {}
        assert marker["stream"]["sequence"] == 1
        await _wait_until(lambda: len(socket.sent) == 3)
        assert json.loads(socket.sent[2])["stream"]["sequence"] == 2
    finally:
        await _stop(hub, connection)


@pytest.mark.parametrize("event", [
    pytest.param(
        {"type": "work_item_updated", "data": {"work_item": {}, "blob": OVERSIZED}},
        id="work-item-frame-naming-no-row",
    ),
    pytest.param(
        {"type": "game_update", "data": {"blob": OVERSIZED}},
        id="other-family-oversized",
    ),
])
async def test_a_drop_that_names_no_work_row_keeps_the_silent_drop(
    tmp_path: Path,
    event: dict[str, Any],
) -> None:
    runtime = _Runtime(tmp_path)
    hub, socket, connection = await _serve(runtime)
    try:
        await _wait_until(lambda: len(socket.sent) == 1)
        hub.ingress({**event, "timestamp": 1.0})
        hub.ingress({"type": "system_mode", "data": {"mode": "active"}, "timestamp": 2.0})
        await _wait_until(lambda: len(socket.sent) == 2)
        assert json.loads(socket.sent[1])["type"] == "system_mode"
        assert hub.sequence == 1
    finally:
        await _stop(hub, connection)
```

### 6.5 `ui/src/components/bridge/BridgeNotifications.tsx` (M2)

**P-1**
SEARCH:
```
    current.setChatThread(thread);
    current.hydrateCrewSession(session.task_id, session, issuedAt);
    current.openGroupChatThread(hostId, thread.id);
```
REPLACE:
```
    // #1414 item 14: a read the live fence refuses, with no session cached for the parent, would
    // open a room whose session band never renders, so its focus step could never run. Open nothing.
    if (!current.hydrateCrewSession(session.task_id, session, issuedAt)
      && !useStore.getState().crewSessionsByParent.has(session.task_id)) {
      cancel();
      setMessage('Context unavailable: the room changed while it was loading. Retry to check again.');
      return;
    }
    current.setChatThread(thread);
    current.openGroupChatThread(hostId, thread.id);
```

### 6.6 `ui/src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx` new file (M2)

```tsx
// #1414 item 14 (BF-998): when the live fence refuses a notification's room-context read and no
// session is cached for its parent, the card opens nothing and offers a retry, instead of opening a
// room whose session band never renders and leaving the focus request pending. Real NotificationCard,
// real store and real liveReadFence (reset before each test by src/test/setup.ts); fetch is stubbed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { NotificationCard } from '../BridgeNotifications';
import { useStore } from '../../../store/useStore';
import { liveReadFence } from '../../../store/liveReadFence';
import type { Agent, NotificationView } from '../../../store/types';
import type { NotificationContext } from '../../sidebar/threadApi';

const initialStoreState = useStore.getState();
const REFUSED = 'Context unavailable: the room changed while it was loading. Retry to check again.';

function roomContext(): NotificationContext {
  return {
    kind: 'crew_session', notification_id: 'f'.repeat(64), delivery_revision: 1,
    thread: {
      id: 'room', task_id: 'parent', title: 'Failed room', participants: ['host'],
      project_id: null, pinned: false, archived: false, personality_override: null,
      workspace_root: null, created_at: 1, last_active_at: 3, preprompt: null,
      model: null, metadata: {},
    },
    session: {
      task_id: 'parent', thread_id: 'room', goal: 'Prepare report', origin: 'captain',
      originator_id: 'captain', facilitator_id: 'host', owner_ids: ['host'],
      state: 'failed', revision: 1, success_criteria: ['Complete'], expected_deliverable: 'Report',
      timestamps: { created_at: 1, transitioned_at: 3, started_at: 2, first_result_at: null, verified_at: null, completed_at: 3 },
      progress: { total: 1, done: 0, failed: 1, active: 0, active_child: null },
      last_result_summary: '', blocker: null, result: null, verification: null, duplicate_resume_count: 0,
    },
  };
}

function seedSourceView(): void {
  const host: Agent = {
    id: 'host', agentType: 'crew', callsign: 'Host', displayName: 'Host', pool: 'bridge',
    state: 'active', confidence: 1, trust: 0.5, tier: 'domain', isCrew: true, position: [0, 0, 0],
  };
  useStore.setState({
    agents: new Map([['host', host]]), activeProfileAgent: 'original-host',
    activeProfileThreadId: 'original-room', activeThreadId: null,
    threadIdByAgent: new Map([['host', 'host-dm']]), chatThreads: new Map(),
    crewSessionsByParent: new Map(), notificationNavigation: null,
    liveGeneration: 'b'.repeat(32), liveSequence: 0,
  });
}

function notification(id: string): NotificationView {
  return {
    id, agent_id: 'p', agent_type: 'producer', department: 'ops',
    notification_type: 'action_required', title: 't', detail: 'd',
    action_url: '', created_at: 0, acknowledged: false,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('#1414 item 14: a notification context read the live fence refuses', () => {
  it('opens nothing, leaves no request pending, and its retry opens the room', async () => {
    seedSourceView();
    const context = roomContext();
    let answer: ((response: Response) => void) | undefined;
    fetchMock.mockImplementationOnce(() => new Promise<Response>(settle => { answer = settle; }));
    render(<NotificationCard notification={notification(context.notification_id)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open room context: t' }));
    expect(answer).toBeTypeOf('function');
    // A live write to the parent lands after the read was issued; nothing cached a session for it.
    liveReadFence.observe(`crew:${context.session.task_id}`);
    await act(async () => { answer!(new Response(JSON.stringify(context), { status: 200 })); });

    // A/B: on the base the card hydrated nothing, opened the room and reported 'Room context opened.'
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(REFUSED));
    const refused = useStore.getState();
    expect(refused.notificationNavigation).toBeNull();
    expect(refused.activeProfileAgent).toBe('original-host');
    expect(refused.activeProfileThreadId).toBe('original-room');
    expect(refused.crewSessionsByParent.has(context.session.task_id)).toBe(false);
    expect(refused.chatThreads.has(context.thread.id)).toBe(false);

    fetchMock.mockImplementationOnce(async () => new Response(JSON.stringify(context), { status: 200 }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry opening context' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Room context opened.'));
    const opened = useStore.getState();
    expect(opened.activeProfileAgent).toBe('host');
    expect(opened.activeProfileThreadId).toBe(context.thread.id);
    expect(opened.crewSessionsByParent.get(context.session.task_id)).toEqual(context.session);
    expect(opened.notificationNavigation?.destination).toEqual({
      hostId: 'host', threadId: context.thread.id, parentId: context.session.task_id, updated: false,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
```

### 6.7 `ui/e2e/conversation-viewport.spec.ts` (M3)

**P-1**
SEARCH:
```
import type { CrewSessionDetailProjection, StartWorkResult } from '../src/store/types';
import type { TodoStep } from '../src/components/workspace/todosApi';
```
REPLACE:
```
import type { CrewSessionDetailProjection, StartWorkResult } from '../src/store/types';
import type { TodoStep } from '../src/components/workspace/todosApi';
import type { UnmanagedOwnedStepsView } from '../src/components/workspace/ownedStepsApi';
```

**P-2**
SEARCH:
```
    expect(sends).toHaveLength(1);
    expect([...new Set(deniedHttp)].sort()).toEqual([
      'GET /api/capability-requests?status=pending',
      'GET /api/config',
      'GET /api/perception/budget',
      'GET /api/recreation/active',
      'GET /api/skill-requests?status=pending',
      'GET /api/system/extensions',
      'GET /api/voice/health',
      'GET /api/wardroom/dms',
    ]);
```
REPLACE:
```
    expect(sends).toHaveLength(1);
    // The baseline answers only the reads chat and Send need. Every other read is denied and pinned
    // here as an exact list, so a read the app starts making fails this test until it is classified.
    // Denied: the Bridge's polls (approvals, faults, config, voice, extensions, recreation,
    // perception budget, DMs), which this test does not exercise, and the thread read ProfileChatTab
    // makes to bind live tool progress (AD-1174), which the DM tests answer and assert.
    // Re-pinned for #1414 item 8: 4b7dfb3b moved the capability poll to /actionable, b4378fb4
    // (AD-1207) added the faults poll and 5c362508 (AD-1174) added the thread read.
    expect([...new Set(deniedHttp)].sort()).toEqual([
      'GET /api/capability-requests/actionable',
      'GET /api/config',
      'GET /api/faults?limit=50&offset=0',
      'GET /api/perception/budget',
      'GET /api/recreation/active',
      'GET /api/skill-requests?status=pending',
      'GET /api/system/extensions',
      'GET /api/threads/baseline-alpha',
      'GET /api/voice/health',
      'GET /api/wardroom/dms',
    ]);
```

**P-3**
SEARCH:
```
  fixtures.set(`GET /api/crew-tasks/${parentId}`, () => started ? { session } : undefined);
  fixtures.set(`GET /api/work-items/${parentId}/steps?limit=1001`, () => started ? { steps, gate_completion: true } : undefined);
```
REPLACE:
```
  fixtures.set(`GET /api/crew-tasks/${parentId}`, () => started ? { session } : undefined);
  fixtures.set(`GET /api/work-items/${parentId}/steps?limit=1001`, () => started ? { steps, gate_completion: true } : undefined);
  // #1414 item 8: the task rail asks the owned-steps route first and reads the legacy checklist
  // above only for an unmanaged parent. Shape: get_owned_work_item_steps in routers/workforce.py
  // (1-based ordinal). The rail's decodeUnmanaged checks it at run time; tsc -b does not read e2e/.
  fixtures.set(`GET /api/work-items/${parentId}/owned-steps`, () => {
    if (!started) return undefined;
    const view: UnmanagedOwnedStepsView = {
      version: 1, mode: 'unmanaged', parent_id: parentId, requested_item_id: parentId, reference: null,
      rows: steps.map((todo, index) => ({ ordinal: index + 1, todo })),
      previous_cursor: null, next_cursor: null, recovery: [], finalization: 'none',
    };
    return view;
  });
```

**P-4**
SEARCH:
```
          expect(isolation.deniedHttp.filter(request => /^(POST|PATCH|PUT|DELETE) /.test(request.key))).toEqual([]);
          expect(rendered).toHaveProperty('activeMedia', []);
```
REPLACE:
```
          expect(isolation.deniedHttp.filter(request => /^(POST|PATCH|PUT|DELETE) /.test(request.key))).toEqual([]);
          expect(isolation.deniedHttp.filter(request => request.key.includes('/owned-steps')).map(request => request.key),
            'every owned-steps read is answered').toEqual([]);
          expect(rendered).toHaveProperty('activeMedia', []);
```

### 6.8 `PROGRESS.md` (M4)

**P-1**
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-997 (2026-11-25), #1414 -- the HXI event stream keeps the socket past 100 work items, and a work-state frame it cannot send asks clients for a resync.** With more than 100 board-visible work items, `build_ws_workforce_snapshot` raised `ws_workforce_source_overflow`. `serve` then ended the socket with 1013 "snapshot unavailable", and since the HXI resets its backoff on every open, each tab reconnected about once a second and received no live event of any kind. The snapshot now carries the first 100 rows in the store's order (priority, then newest) and adds no field: `tests/test_bf997_ws_snapshot_and_work_state_resync.py::test_a_snapshot_past_the_cap_carries_the_first_100_rows_and_the_socket_stays_live` runs a real `WorkItemStore` with 101 rows through the real hub, and the socket then delivers a later event. The HXI already upserts snapshot rows without removing any and re-reads every bucket on each snapshot (`ui/src/store/__tests__/workItemReconciliation.test.ts`, "upserts snapshot rows without removing records the snapshot omits"). `tests/test_ad1133_live_crew_session_refresh.py::test_ws_workforce_snapshot_ordinary_overflow_is_stable` now expects those 100 rows, with the reason inline. Every other snapshot failure still ends the socket with 1013 (`test_snapshot_source_overflow_closes_1013_without_partial_frame`). At both drop sites, a work-item frame that names its row, or a crew-session projection that names its parent, and fails the 256 KiB wire bound now requests the existing resync marker. `test_a_dropped_work_item_frame_requests_the_resync_marker` proves this through the real store, and `test_a_dropped_crew_session_projection_requests_the_resync_marker` through the projector's publish callback. A dropped frame that names no row, or belongs to another family, stays silent (`test_a_drop_that_names_no_work_row_keeps_the_silent_drop`). The hub class keeps its 492-line span. Mutation census: 9 of 9 killed (rows B1-M1 to B1-M9; B1-M10 is a review property), run once on the overlay of fc57a8b2. Contract `prompts/bf-997-998-1414-batch-b-hxi-live-state.md`.

**BF-998 (2026-11-25), #1414 -- a notification's room-context read that the live fence refuses, with no session cached, navigates nowhere and offers a retry.** `hydrateCrewSession` returns false when a live write to the parent lands after the read was issued. The card ignored that: it opened the room and set a focus request. With no session cached, the room's session band never rendered, so the focus step returned early and the request stayed pending. Now the card opens nothing and clears the request. It says "Context unavailable: the room changed while it was loading. Retry to check again.", and its existing Retry reads again and opens the room (`ui/src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx`, with the real store and the real `liveReadFence`). A refused read whose parent already holds a live session still opens the room (`ui/src/__tests__/WorkStateReconciliation.issue1375.test.tsx`, "M4 an opened notification keeps a live projection written while its older-issued context read was in flight"). Mutation census: 5 of 5 killed (rows B2-M1 to B2-M5), run once on the overlay of fc57a8b2. Contract `prompts/bf-997-998-1414-batch-b-hxi-live-state.md`.

**#1414 item 8 (2026-11-25) -- the issue1369 Playwright suite answers the owned-steps read the task rail makes before its checklist.** The rail asks `GET /api/work-items/{id}/owned-steps` first and reads the legacy checklist only for an unmanaged parent. The suite denied that read, so every `task matrix:` test stopped before its checklist. `ui/e2e/conversation-viewport.spec.ts` now answers the read with an unmanaged view, in the shape `get_owned_work_item_steps` serves, and asserts that no owned-steps read is denied. The baseline test's exact list of denied reads is re-pinned to the reads the app makes now (`4b7dfb3b` moved the capability poll to `/actionable`, `b4378fb4` added the faults poll and `5c362508` the thread read), each denied by design. `npx playwright test -c playwright.issue1369.config.ts` in `ui/`: 33 of 71 failed on the base (the 32 `task matrix:` tests at the poll for the legacy steps read, and the baseline test at its denied-list pin), and 71 passed after. No workflow runs this suite. The change is test-only and takes no BF number.
```

### 6.9 `DECISIONS.md` (M4; anchored on Batch A's heading)

**P-1**
SEARCH:
```
### BF-994 / BF-995 / BF-996 -- #1414 Batch A: init's provider format and timeout, setup's redaction, the HXI save's base file (2026-11-25, #1414)
```
REPLACE:
```
### BF-997 / BF-998 -- #1414 Batch B: the HXI event stream past 100 work items, dropped work-state frames, a refused notification read (2026-11-25, #1414)

- *Scope.* `routers/workforce.py` (`build_ws_workforce_snapshot`), `ws_event_stream.py` (`_resyncs_on_drop` and the two drop sites), `ui/src/components/bridge/BridgeNotifications.tsx`; tests `tests/test_bf997_ws_snapshot_and_work_state_resync.py`, `ui/src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx`, and the test-only `ui/e2e/conversation-viewport.spec.ts` change for item 8. Contract `prompts/bf-997-998-1414-batch-b-hxi-live-state.md`.
- *D1.* Past the 100-row cap, the WebSocket snapshot carries the first 100 rows in the store's order and adds no field. The HXI already upserts snapshot rows without removing any and re-reads every bucket on each snapshot, so a partial list is correct. This supersedes AD-1133's workforce clauses (`prompts/archive/ad-1133-live-crew-session-thread-refresh.md:256` as it applies to the workforce source, and `:272-274`). Every other snapshot overflow still ends the socket with 1013. Rejected: a truncation flag (it duplicates the repair the HXI already runs) and a status filter or a larger cap (it still has a cliff).
- *D2.* A dropped frame requests the existing resync marker when it is a correlated tool event (unchanged), a work-item event naming `work_item.id`, or a crew-session projection naming `parent_id`. IDs-only message and artifact frames, and every other family, keep the silent drop. Rejected: resync on any work-item drop (an empty projection names no row) and resync on every drop.
- *D3.* When a notification's room-context read is refused by the live fence and no session is cached for the parent, the card opens nothing, clears the request and offers its existing retry. With a session cached, it opens as before. Rejected: re-running the focus step when the band mounts (it touches `ProfileChatTab.tsx`, which eight source-reading tests cover).
- *D4.* Item 8 is test-only: one canned owned-steps answer in the shape the router serves, and the baseline's exact denied list re-pinned to the reads the app makes now (`4b7dfb3b`, `b4378fb4`, `5c362508`). The baseline answers only what chat and Send need. No workflow is added.
- *Reversal.* Revert the slice's commit; each slice is independent. The `test_ad1133` pin reverts with BF-997.

### BF-994 / BF-995 / BF-996 -- #1414 Batch A: init's provider format and timeout, setup's redaction, the HXI save's base file (2026-11-25, #1414)
```

If 6.9 runs against `8447d6ef` instead, anchor on `### Acclimation S1 -- the AD-486 Birth Chamber and the department activation scheduler deleted (2026-11-25, #1700, AD-1355)`.

## 7. Mutation census and generated-artifact commands

| Row | Mutant | Killer (runner) |
|---|---|---|
| B1-M1 | the router raises `ws_workforce_source_overflow` again | `test_a_snapshot_past_the_cap_carries_the_first_100_rows_and_the_socket_stays_live`, `test_ad1133...::test_ws_workforce_snapshot_ordinary_overflow_is_stable` (pytest) |
| B1-M2 | the slice keeps the last 100 rows (`[-limit:]`) | the same two (pytest) |
| B1-M3 | no slice (101 rows) | the same two (pytest) |
| B1-M4 | the ingress site calls `_is_correlated_tool_event` again | `test_a_dropped_work_item_frame_requests_the_resync_marker` (pytest) |
| B1-M5 | the final-envelope site calls `_is_correlated_tool_event` again | `test_a_dropped_crew_session_projection_requests_the_resync_marker` (pytest) |
| B1-M6 | `_resyncs_on_drop` ignores whether the row is named | `test_a_drop_that_names_no_work_row_keeps_the_silent_drop[work-item-frame-naming-no-row]` (pytest) |
| B1-M7 | `_resyncs_on_drop` returns True for every event | `test_a_drop_that_names_no_work_row_keeps_the_silent_drop[other-family-oversized]` and `[work-item-frame-naming-no-row]`, `test_ad1133...::test_unidentifiable_tool_drop_does_not_add_resync[*]` (pytest) |
| B1-M8 | the correlated-tool clause is removed | `test_ad1133...::test_correlated_tool_finalization_drop_requests_existing_empty_resync` (pytest) |
| B1-M9 | the `EventType` normalization is removed | `test_a_dropped_work_item_frame_requests_the_resync_marker` (the store emits an `EventType` member) (pytest) |
| B1-M10 | the projection branch accepts a missing `parent_id` | no test; Diff Reviewer property B1-8 |
| B2-M1 | the guard is removed | `BridgeNotifications.issue1414.test.tsx` (vitest) |
| B2-M2 | the guard refuses whenever hydrate returns false | `WorkStateReconciliation.issue1375.test.tsx` "M4 an opened notification keeps a live projection ..." (vitest) |
| B2-M3 | the refusal skips `cancel()` | `BridgeNotifications.issue1414.test.tsx` (`notificationNavigation` null) (vitest) |
| B2-M4 | the message lacks "unavailable" | `BridgeNotifications.issue1414.test.tsx` (no Retry button) (vitest) |
| B2-M5 | `setChatThread` stays before the guard | `BridgeNotifications.issue1414.test.tsx` (`chatThreads.has` false) (vitest) |
| B3-M1 | the owned-steps answer is removed | the `task matrix:` tests at the `:1156` poll (2 of 2 sampled under `--max-failures 2`; all 32 on the base, which lacks the answer), and 6.7 P-4's assertion (Playwright) |
| B3-M2 | the answer gains an extra key, which `decodeUnmanaged` rejects | the `task matrix:` tests (2 of 2 sampled under `--max-failures 2`; record the runner's error line, do not predict it) (Playwright) |
| B3-M3 | the baseline's list loses an entry or reverts to the base list | `baseline: fresh desktop Alpha conversation preserves usable chat and Send` at the 6.7 P-2 assertion (Playwright); the revert is proved by the base run (33 failed, 38 passed) |

Generated artifacts, in order, at M4 on the post-A base (interpreter `d:/ProbOS/.venv/Scripts/python.exe`):

1. Apply 6.8 and 6.9.
2. `scripts/gen_ad_ledger.py`. BF-997 and BF-998 appear as shipped through the `DECISIONS.md` heading; item 8 adds no row. Measured on the post-A oracle: shipped 636 -> 638, the BF list ends `980-998`, the highest BF is BF-998 and the next BF-999.
3. The `--check` runs of `scripts/gen_ad_ledger.py`, `scripts/check_architecture_principles.py`, `scripts/check_config_facade.py`, `scripts/gen_config_reference.py`, `scripts/check_config_profiles.py`, `scripts/check_seam_contracts.py` and `scripts/check_store_registry.py`.
4. `scripts/run_test_gate.py --preflight-only`.

These artifacts do not move:
- `architecture-baseline.yaml`: the hub span is still 492 and its method count is unchanged; `_resyncs_on_drop` is a module function.
- the config facade baseline, the config reference and the profiles: no config change.
- event-type tables: no `EventType` change.
- route inventory: no route change.
- `file_durations.json`: a new file is weighed at the mean (`test_ci_shards.py:499-508`).

Preflight phases that fail if a step is missing:
- `ad-ledger`, if step 2 is skipped after the tracker edits;
- `architecture-fitness`, if any line lands inside `WSEventStreamHub` (a new `lines` trigger, then the sha pin in `test_ad1324_srp_layout`);
- `compile`, on a syntax error;
- `phantom-api`, if this contract is staged with a new name written in call form in prose.

**Pin census:**

| Path or artifact | Readers in `tests/`, `scripts/`, `ui/src`, `ui/e2e` | Pins bytes, hash, lines or counts |
|---|---|---|
| `src/probos/routers/workforce.py` | `test_ad1133:30` (import); docstrings `test_ad1275:697`, `test_bf900:601` | none (the `:223` docstring citation drifts by +2 and is not asserted) |
| `src/probos/ws_event_stream.py` | imports at `test_ad1133:42-50`, `test_ad1174:20,32`, `test_ad1359:302`, `tests/fixtures/ad1174_progress_bridge.py:29,276`, `tests/fixtures/issue1375_work_state_bridge.py:81,87`; scanned by `scripts/check_architecture_principles.py` | the baseline row `probos.ws_event_stream::WSEventStreamHub` (`[methods]`): the span must stay <= 500, and the baseline sha is pinned by `test_ad1324_srp_layout` |
| `tests/test_ad1133_live_crew_session_refresh.py` | the new BF-997 file imports three helpers | none |
| `ui/src/components/bridge/BridgeNotifications.tsx` | `?raw` at `BridgeNotifications.test.tsx:11` (emoji); `tests/test_ad1214_decision_pre_clearance.py:1183-1186` (two constant lines, untouched); imported by `BridgePanel.tsx`, `BridgeNotifications.preClear.test.tsx`, `WorkStateReconciliation.issue1375.test.tsx:17` | content pins on untouched lines only; the new text is ASCII |
| `ui/e2e/conversation-viewport.spec.ts` | `playwright.issue1369.config.ts:11`; `playwright.config.ts:10` (testDir only; no workflow runs it) | none; vitest and `tsc -b` exclude it |
| both new test files | none | none |
| `PROGRESS.md`, `DECISIONS.md` | `scripts/gen_ad_ledger.py` | the ledger pair (regenerated); both are on Batch A's list |
| ledger pair | `tests/test_ad1184_ad_ledger.py`, preflight `ad-ledger` | regenerated at M4; on Batch A's list |

UI gates the batch must keep green: `npx tsc -b` (it reads `BridgeNotifications.tsx` and the new vitest file) and `npx vitest run`. The orchestrator runs both once after M3; `run_test_gate.py` runs neither.

## 8. Diff Reviewer brief (per slice) and #1414 landing comment

**B1. Consumer that must accept it:** `ui/src/store/useStore.ts`: `:3241-3251` (snapshot), `:3260-3268` (`resync_required`), `:3401-3410` (workforce rows), and `workItemReconciliation.ts:370-394`.
- B1-1: `build_ws_workforce_snapshot` never raises for row count. It returns at most `limit` rows, the first `limit` in the seam's order. The seam, its SQL and its `limit + 1` sentinel are unchanged.
- B1-2: the snapshot's `workforce` keys are exactly `work_items`, `bookings` and `resources`, with no new field. `useStore.ts:3402-3410` reads only those, `applySnapshotRows` upserts without removing, and `observeItemEpoch` runs at `:3251` before the rows apply.
- B1-3: every other snapshot failure still ends the socket with 1013 "snapshot unavailable" (`test_ad1133:2334-2359`).
- B1-4: both drop sites call `_resyncs_on_drop`. It returns True only for an identified correlated tool event, a work-item event with a bounded non-blank `work_item.id`, or a `crew_session_projection` with a bounded non-blank `parent_id`. Every other drop keeps its warning and requests nothing.
- B1-5: `_resyncs_on_drop` checks `type(...) is EventType/str/dict` before any `.get`, and never stringifies or calls into an unknown object (`test_ad1133:1434-1461` still passes).
- B1-6: no line is added to or removed from `class WSEventStreamHub` (span 492), and the architecture baseline is unchanged.
- B1-7: the `test_ad1133` pin keeps its name, states its reason inline, and asserts the 100 ids in order.
- B1-8: the projection branch rejects a missing, blank, over-128-character or non-string `parent_id`.

**B2. Consumers:** the `NotificationCard` source view, and `ProfileChatTab.tsx:1006-1036` (unchanged).
- B2-1: the refusal happens only when `hydrateCrewSession` returns false and a fresh `useStore.getState()` holds no session for `session.task_id`. With a cached session the path is as before.
- B2-2: on refusal: no `setChatThread`, no `openGroupChatThread`, no navigation with a destination. `cancel()` leaves `notificationNavigation` null.
- B2-3: the message contains "unavailable", so the existing Retry button renders. It is ASCII, with no emoji.
- B2-4: `setChatThread` moving after the hydrate is safe, because `hydrateCrewSession` reads no chat thread.
- B2-5: `test_ad1214:1183-1186` and the emoji `?raw` check still hold.

**B3. Consumer:** the rail's `decodeUnmanaged` (`ownedStepsApi.ts:372-391`), the isolation helper (`_helpers.ts:188-228`) and the baseline's own route (base `:160-214`).
- B3-1: the answer is served only after Start Work. Its keys are exactly the unmanaged view's, with ordinals 1-based, `reference` null and `finalization` `'none'`, and there are at most 20 rows.
- B3-2: no expectation is weakened. The baseline's denied list stays an exact sorted equality and changes only as 6.7 P-2 states: one entry renamed, two added, none dropped. The baseline answers no new read. The writes list (base `:1198-1202`) is unchanged, and the owned-steps assertion only adds.
- B3-3: the import is `import type`, and no workflow file changes.
- B3-4: each re-pinned read traces to the app: `/api/capability-requests/actionable` (`useStore.ts:2770`, `4b7dfb3b`), `/api/faults?limit=50&offset=0` (`useFaultReports.ts:60`, `b4378fb4`), `/api/threads/baseline-alpha` (`ProfileChatTab.tsx:751`, then `threadApi.ts:576`, `5c362508`; tool-progress binding only, answered and asserted by the DM tests at base `:728` and `:1497`).

**#1414 landing comment:**

```
Batch B (HXI live state) is merged in <PR #...> (<sha>), gated by <receipt path, receipt sha>.

- [x] Item 11 (the WS snapshot drops the socket with 1013 above 100 rows): BF-997. Past the cap the snapshot carries the first 100 rows in the store's order; the HXI re-reads the rest by REST. Proof: tests/test_bf997_ws_snapshot_and_work_state_resync.py, a real WorkItemStore with 101 rows through the real hub. Every other snapshot overflow still ends the socket with 1013.
- [x] Item 12 (dropped work-item frames never request a resync): BF-997. A dropped work-item frame naming its row, or a dropped crew-session projection naming its parent, now requests the existing resync marker at both drop sites; drops naming no row stay silent.
- [x] Item 14 (notification focus handoff skipped after a fenced hydrate): BF-998. With no session cached, the card opens nothing, clears the request and offers a retry; with a session cached it opens as before. Proof: ui/src/components/bridge/__tests__/BridgeNotifications.issue1414.test.tsx, real store and real fence.
- [x] Item 8 (issue1369 Playwright suite red): the suite answers the owned-steps read the task rail makes, and the baseline's exact denied list is re-pinned to the reads the app now makes (4b7dfb3b, b4378fb4, 5c362508). 33 of 71 failed on the base; 71 passed after. Test-only, no BF. Running e2e suites in CI is out of scope; nothing filed.

Mutation census: B1 9/9 (B1-M10 is a review property), B2 5/5, B3 3/3 killed.
Residuals for #1820 (latent): a single row over the 64K-character string bound, or a snapshot over 1 MiB, still ends the socket with 1013; the HXI resets its reconnect backoff on every open.
Not ticked here: items 1, 9, 10 and 13 (item 1 shipped earlier; Batch C; the item 10 consolidation; item 13 as a limit).
```

The comment ticks items 8, 11, 12 and 14. It does not tick item 1 (shipped earlier, outside this batch) or items 9, 10 and 13.
