# AD-1328 S2b repair r1 -- a live scoped denial dominates every approval of the same command, under any request id

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16 -- repair contract for review round 1 (Diff Reviewer GPT-6.1 Sol, `logs/architect/ad1328-s2b-review-r1-report.md`), finding 1 only.

**Status:** Ready for build. No new AD or BF number (AD-1328 / #1530, slice S2b, PR 2).
**Base:** the staged S2b candidate, tree `6740e4e0ebffcacd247d0b5970374e90719f9290` over HEAD `324b2931` (branch `feat/ad1328-s2b-20261016-2400b14c`, base main `2400b14c`). Every SEARCH below occurs exactly once in the CURRENT file on that tree.
**Dependencies:** S2b contract `prompts/ad-1328-s2b-command-policy-escalation.md` (D4 "Denial: stored for a non-empty scope and refused there"; M1-M4). S1, S2a and the record schema are untouched.
**Estimated tests:** 5 new test functions (about 14 cases) in three existing S2b files, plus 2 deliberate edits in M1.

## Classification (Captain's rule of 2026-10-16 17:59)

| # | Finding | Class | Decision |
|---|---|---|---|
| 1 | Scoped denial does not override an existing approval for the same identity | P1, ordinary, regression | **Repaired here.** P1, and an approval the Captain denied running is the policy allowing what it was told to forbid. |
| 2 | Queued admission outlives expiry or work-item closure | P2, contention only | **#1523 follow-up.** Both reproductions needed a *second* SQLite writer holding `BEGIN IMMEDIATE` (probe `test_review_boundaries.py:236`, `:273`, `:450`). Production has none: own file `command_approvals.db` (`startup/communication.py:313`), one connection (`command_approvals.py:265`), every write under one `asyncio.Lock` (`:316`, `:365`), so the window is a lock wait plus a thread hop, in milliseconds. The command is one the policy escalated and the Captain approved for that scope, and the call began inside the window. Even after a fix, a work item can still close during the spawn, so revalidation narrows the window but cannot close it. After this repair, a denial landing during the wait **is** honoured, because the denial check runs inside the compare-and-set. |
| 3 | A second `start()` orphans the first connection | P3, injected only | **#1523 follow-up.** One `start` in production (`communication.py:313`), `stop` at `shutdown.py:1755`, and no re-entry caller. |

## Problem

`CommandEscalations.resolve` (`src/probos/execution/command_escalation.py:230-242`) admits the newest `active` row for (agent, scope, canonical key, digest) before it reads a `denied` row, and `SqliteCommandApprovalStore.use` (`command_approvals.py:367-373`) compare-and-sets on the approval's own `request_id` without looking at any other row. Two requests can carry one identity, and then end `["active", "denied"]`; the next call runs (reproduced: `approved_run`, exit 0). The producers of a second request id for one identity, enumerated by the reviewer and confirmed in source:

- spelling variants that canonicalise alike (the payload's display `command` differs, so AD-1154 dedup does not fold them);
- concurrent filing (`_file`, `:308-345`; the count and the insert are not one transaction);
- a single-use approval already used, which then files again (`find` hides a used thread or none row, `:349`);
- a failed scope lookup, or an approval lookup or use fault, which files again (`:243-248`).

There are two decision writers, `fulfil_approval` (`:250-292`, writes `active`) and `record_denial` (`:294-306`, writes `denied`). Both reach the store through `record_decision` (`command_approvals.py:290-330`). The exits are `resolve`'s `approved_run`/`reuse`, `denied` and `filed` outcomes.

## Solution (decided)

Enforce in the store, by identity rather than by request id, at the two points where an approval becomes effective:

1. **`use` (the authority).** The compare-and-set UPDATE gains `AND NOT EXISTS (<a live denied row for this row's agent, scope, canonical key and digest>)`. It is one SQL statement, so it holds whichever decision came first, and it holds when a denial lands between `find` and `use` or during the lock wait. It also holds across connections. A run admitted before the denial stands: it was committed and spawned under a live approval. Later reuses are refused.
2. **`record_decision` for `active` (activation).** An `active` row is not inserted while a live denial of the same identity stands, using one `INSERT OR IGNORE ... SELECT ... WHERE ? = 'denied' OR NOT EXISTS (...)`. `fulfil_approval` already returns None for `row is None`. The request then stays `approved` and is not marked fulfilled (BF-722 retry: it records once the denial expires or its scope ends), and a new warning says why. This keeps the evidence honest: no `fulfilled` request and no `active` row for a command that cannot run. Denials are never gated: a second denial is recorded.
3. **`resolve` ordering stays as it is.** When `use` refuses because of a denial, the existing fall-through (`:239-242`) finds the denial and returns the `denied` frame with the denial's request id. A denial lookup that raises files the command for review, so it is never run (`:243-248`, unchanged).

`find` is unchanged (its tests pin "active and denied never see each other", M1 `:395-412`). A denial matches regardless of who denied it, which fails toward refusal. It matches only an unexpired denial (`expires_at > now`): a denial ends with its TTL (7 days or 1 hour), and a work-item denial also stops mattering when its item ends, because nothing in an ended scope is admitted. Empty-scope denials are never written (`record_denial`, `:297`), so the clause is vacuous there.

## Section 1: `src/probos/execution/command_approvals.py`

Module docstring: state the dominance rule.

```
<<<<<<< SEARCH
  policy digest. Approval writes ``active``; denial writes ``denied``. A replay of the
  decision changes nothing.
* ``use`` admits one run by one compare-and-set, committed before the caller starts
=======
  policy digest. Approval writes ``active``; denial writes ``denied``. A replay of the
  decision changes nothing.
* A live denial dominates (repair r1): while an unexpired ``denied`` row exists for the
  same agent, scope, canonical key and digest -- under any request id -- ``use`` admits
  no run (checked inside its compare-and-set) and ``record_decision`` records no
  ``active`` row. A run admitted before the denial stands; nothing after it is admitted.
* ``use`` admits one run by one compare-and-set, committed before the caller starts
>>>>>>> REPLACE
```

`record_decision`: gate activation on a live denial (one statement; denials are never gated).

```
<<<<<<< SEARCH
        """Write the decision on one filed escalation; the first decision wins.

        Returns the row as stored. Raises ``ValueError`` for an identity that is not
        well formed. ``approver_authority`` is always the Captain's.
        """
=======
        """Write the decision on one filed escalation; the first decision wins.

        Returns the row as stored, or None when an ``active`` decision was not recorded
        because a live denial of the same identity stands (repair r1). Raises
        ``ValueError`` for an identity that is not well formed. ``approver_authority``
        is always the Captain's.
        """
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
                await db.execute(
                    f"INSERT OR IGNORE INTO command_approvals ({_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        request_id, agent_id, scope_key, canonical_key, policy_digest, state,
                        approver, APPROVER_AUTHORITY, now, now + float(ttl_seconds),
                    ),
                )
=======
                await db.execute(
                    f"INSERT OR IGNORE INTO command_approvals ({_COLUMNS}) "
                    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0 "
                    "WHERE ? = 'denied' OR NOT EXISTS (SELECT 1 FROM command_approvals "
                    "WHERE agent_id = ? AND scope_key = ? AND canonical_key = ? AND policy_digest = ? "
                    "AND state = 'denied' AND expires_at > ?)",
                    (
                        request_id, agent_id, scope_key, canonical_key, policy_digest, state,
                        approver, APPROVER_AUTHORITY, now, now + float(ttl_seconds),
                        state, agent_id, scope_key, canonical_key, policy_digest, now,
                    ),
                )
>>>>>>> REPLACE
```

`use`: the compare-and-set refuses while a live denial of the row's identity stands. The first line (`UPDATE command_approvals SET uses`) and the St1 line are kept byte for byte (hidden pins below).

```
<<<<<<< SEARCH
        One transaction: the compare-and-set on the approval, then the use row. It is
        committed before the caller starts the command, so a crash afterwards can lose
        a run but never repeat one (nothing replays it).
        """
=======
        One transaction: the compare-and-set on the approval, then the use row. It is
        committed before the caller starts the command, so a crash afterwards can lose
        a run but never repeat one (nothing replays it). The compare-and-set also fails
        while a live denial of the same agent, scope, canonical key and digest stands,
        under any request id (repair r1).
        """
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
                    "AND expires_at > ? AND approver = ? AND approver_authority = ? "
                    "AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",
                    (request_id, agent_id, scope_key, now, CAPTAIN, APPROVER_AUTHORITY),
                )
=======
                    "AND expires_at > ? AND approver = ? AND approver_authority = ? "
                    "AND NOT EXISTS (SELECT 1 FROM command_approvals AS denial "
                    "WHERE denial.agent_id = command_approvals.agent_id "
                    "AND denial.scope_key = command_approvals.scope_key "
                    "AND denial.canonical_key = command_approvals.canonical_key "
                    "AND denial.policy_digest = command_approvals.policy_digest "
                    "AND denial.state = 'denied' AND denial.expires_at > ?) "
                    "AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",
                    (request_id, agent_id, scope_key, now, CAPTAIN, APPROVER_AUTHORITY, now),
                )
>>>>>>> REPLACE
```

(The St1 line's unqualified `scope_key` and `uses` sit outside the subquery, so they still name the updated row. `idx_command_approvals_identity` (`:79-80`) covers the subquery.)

## Section 2: `src/probos/execution/command_escalation.py`

Module docstring item 2: say that the denial wins over an approval.

```
<<<<<<< SEARCH
2. **A denial** in this scope: refused; nothing is filed again.
=======
2. **A denial** in this scope: refused; nothing is filed again. A live denial of the
   same command wins over any approval of it, under any request id: the store admits no
   run and records no approval while it stands (repair r1).
>>>>>>> REPLACE
```

`fulfil_approval` docstring and the new warning when the store declined to activate:

```
<<<<<<< SEARCH
        approved, well-formed command escalation, was not decided by the Captain, was
        filed under another policy digest than the running one, or its work item ended.
        """
=======
        approved, well-formed command escalation, was not decided by the Captain, was
        filed under another policy digest than the running one, its work item ended, or
        a live denial of the same command in the same scope stands (any request id).
        """
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
        if row is None or row.state != "active":
            return None
=======
        if row is None:
            logger.warning(
                "AD-1328: command approval %s was not recorded: a denial of the same command "
                "for agent %s in scope %s still stands; it grants nothing",
                ask.request_id[:12], ask.agent_id[:12], ask.scope_key[:40] or "-",
            )
            return None
        if row.state != "active":
            return None
>>>>>>> REPLACE
```

No other source file changes.

## Tests (Builders write them; tests only, never edit `src/`)

Rules as for the S2b contract: real SQLite in `tmp_path`, an injected `clock=` where time matters, no real shell (the files' existing spawn recorders), every test asserting its premise and a negative control, and OS-independent assertions (gates built with `platform="linux"` as the files already do).

### Deliberate edits (M1, `tests/test_ad1328_s2b_approval_store.py`), each with a `# AD-1328 S2b repair r1:` comment

- `test_record_decision_first_wins_and_validates`, line `:338`: the per-case control `record_decision(**_decision(request_id=f"req-ok-{case}"))` lands in the identity `req-2` denied at `:328`, which is now refused by design. Record it with `canonical_key=OTHER_KEY`. `:330` (`req-2` active replay == denied) holds unchanged.
- `test_use_admits_nothing_outside_the_approval`, line `:617`: the `denied` fixture row shares the approval's identity, so the negative control at `:642-644` would now be refused. Record it with `canonical_key=OTHER_KEY`. The `denied_row` case still returns None (its state is `denied`).

Every other existing M1-M4 test holds unchanged (enumerated under Hidden Pins).

### New in M1 `tests/test_ad1328_s2b_approval_store.py`

1. `test_live_denial_blocks_use_across_requests[work_item, thread]`. This is the approve-then-deny order. Record `req-a` `active` (ttl 600), then `req-d` `denied` (ttl 100) with the same identity. Premises: both rows exist, `find(active)` returns `req-a`, and `uses == 0`. Then `use(req-a)` is None, `get(req-a)` is unchanged, and `list_uses(req-a) == []`. Control (expiry): set the clock past `req-d.expires_at` but before `req-a.expires_at`, and `use(req-a)` is `approved_run`. Kills St4, St9.
2. `test_denial_of_another_identity_does_not_block[agent, scope, key, digest]`. The same as #1, but `req-d` changes one of `agent_id=OTHER_AGENT`, `scope_key=OTHER_WORK_SCOPE`, `canonical_key=OTHER_KEY`, `policy_digest=OTHER_DIGEST`. `use(req-a)` is `approved_run`. Premise: `find(req-d's identity, state="denied")` returns `req-d`. Kills St5-St8.
3. `test_denial_between_find_and_use_and_after_a_run`. This is the race, enacted deterministically, in a work-item scope. `req-a` active, `find` returns it, `use` gives `approved_run`; record `req-d` denied (same identity); `use(req-a)` is None; `uses` stays 1 and `list_uses` has length 1. Control: a second approval `req-b` with `OTHER_KEY` admits `approved_run` after the denial.
4. `test_activation_refused_while_a_denial_stands`. This is the deny-then-approve order. Record `req-d` denied (ttl 100), then `record_decision(req-a, state="active")` is None, `get(req-a)` is None and `find(active)` is None. A second denial `req-d2` of the same identity is recorded (`state == "denied"`). Controls: `req-k` active with `OTHER_KEY` is recorded; with the clock past `req-d2.expires_at`, the retry `record_decision(req-a, active)` returns an `active` row and `use` admits `approved_run` (BF-722 retry). Kills St10, St11, St12.

### New in M2 `tests/test_ad1328_s2b_escalation_service.py`

5. `test_denial_dominates_an_approval_of_the_same_command[approve_then_deny, deny_then_approve]` in `_ctx(item="W1")`. File `_PUSH` (`"git push origin main"`) and its variant `"git  push origin main"` (two spaces) through `_resolve`. Premises: the two verdicts' `canonical.key` are equal, the request ids differ, and two requests are pending. If the keys differ, stop and report; do not change the variant to pass. Use the request store's `decide` and the service, exactly as the file's helpers do.
   - **approve_then_deny:** approve A, and `fulfil_approval` returns `fulfilled`. Then deny B, and `record_denial` is True. `resolve(A's verdict)` gives a message starting `_denied_head(B)`, approval `{"state": "denied", "request_id": B, "use_id": None}` and `runs is False`. `approvals.get(A).uses == 0` and nothing new is filed.
   - **deny_then_approve:** deny B and `record_denial`. Approve A, and `fulfil_approval` returns None. A's request status stays `approved`, `mark_fulfilled` is not called (spy), `approvals.get(A)` is None, and caplog holds `"was not recorded: a denial of the same command"` with no `_PUSH` text. `resolve` then gives `denied` with B's id.
   - Controls (both orders): `_PUSH_OTHER` in W1 files; `_PUSH` in `_ctx(item="W2")` files.
6. `test_reuse_stops_when_a_denial_lands`. In W1: approve A and resolve gives `approved_run`. File the variant B and deny it (`record_denial`). Resolve gives `denied` (not `reuse`), and `approvals.get(A).uses == 1`.

### New in M4 `tests/test_ad1328_s2b_seam_and_wiring.py`

7. `test_seam_denial_dominates_an_earlier_approval` crosses tool -> registry -> service -> request store -> REST decision -> store -> tool, with real stores and `decide_capability_request` via `_approve`. Setup: `gate = _gate(_policy(_ASK_PUSH))`, `_route`, and one `_work_item`. Call `PUSH` and the variant `"git  push origin"` through `_call`. Premise: two pending requests. Then `_approve(A)` has `fulfilled` true, and re-issuing `PUSH` spawns once (`approved_run`, the control). Then `_approve(B, approve=False)`, and re-issuing `PUSH` gives no new spawn (`spawns.commands` length still 1), an error containing `"denied this command"` and `f"request {B}"`, metadata approval `denied` with B's id, and no new pending request. The variant premise is the same as #5: stop if the keys differ.

### Mutation rows to add (file `execution/command_approvals.py`; rerun St1-St3 as well, since the file changed)

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| St4 | execution/command_approvals.py | `"AND denial.state = 'denied' AND denial.expires_at > ?) "` | `"AND 0 AND denial.expires_at > ?) "` | M1 #1, #3; M2 #5 approve_then_deny, #6; M4 #7 |
| St5 | execution/command_approvals.py | `"WHERE denial.agent_id = command_approvals.agent_id "` | `"WHERE 1 "` | M1 #2 agent |
| St6 | execution/command_approvals.py | `"AND denial.scope_key = command_approvals.scope_key "` | `""` | M1 #2 scope |
| St7 | execution/command_approvals.py | `"AND denial.canonical_key = command_approvals.canonical_key "` | `""` | M1 #2 key |
| St8 | execution/command_approvals.py | `"AND denial.policy_digest = command_approvals.policy_digest "` | `""` | M1 #2 digest |
| St9 | execution/command_approvals.py | `"AND denial.state = 'denied' AND denial.expires_at > ?) "` | `"AND denial.state = 'denied' AND ? IS NOT NULL) "` | M1 #1 expiry control |
| St10 | execution/command_approvals.py | `"WHERE ? = 'denied' OR NOT EXISTS (SELECT 1 FROM command_approvals "` | `"WHERE ? = 'denied' OR 1 OR NOT EXISTS (SELECT 1 FROM command_approvals "` | M1 #4; M2 #5 deny_then_approve |
| St11 | execution/command_approvals.py | `"WHERE ? = 'denied' OR NOT EXISTS (SELECT 1 FROM command_approvals "` | `"WHERE ? = 'never' OR NOT EXISTS (SELECT 1 FROM command_approvals "` | M1 #4 second denial recorded |
| St12 | execution/command_approvals.py | `"AND state = 'denied' AND expires_at > ?)",` | `"AND state = 'denied' AND ? IS NOT NULL)",` | M1 #4 retry-after-expiry control |

Every replacement keeps the bound-parameter count, so each mutant is semantic, not a crash. St4 and St9 share an anchor, and so do St10 and St11; each anchor occurs exactly once in the file (the record subquery's lines are spelled differently from `use`'s and from `find`'s). Equivalent-mutant note: none expected. St5-St8 over-block (fail closed); they are listed so that the identity controls are proven to discriminate. If any row survives, stop and report it; do not weaken it.

## Hidden pins (enumerated)

| Pin | Evidence | Effect |
|---|---|---|
| `sql.startswith("UPDATE command_approvals SET uses")` | `tests/test_ad1328_s2b_approval_store.py:592` | The first line of the UPDATE is unchanged. Holds. |
| `"INSERT INTO command_approval_uses"` in the failing wrapper and the statement order | `:104`, `:593` | Untouched. Holds. |
| St1 anchor `"AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",` occurs once | `command_approvals.py:371` vs `find`'s different line `:349` | Kept byte for byte. Holds; rerun St1-St3. |
| `find` semantics (active and denied never mix; a denial does not displace the approval in `find`) | M1 `:395-412` (`:407`) | `find` is untouched. Holds. |
| First decision wins and a replay returns the first row | M1 `:323-330` | Holds (the PK conflict still ignores; `req-2`'s own denial blocks its active replay, and `get` returns the denial either way). |
| Activation control in the denied identity | M1 `:338` | Deliberate edit. |
| Use-refusal fixture shares identity | M1 `:617`, `:642-644` | Deliberate edit. |
| Denial with a different command or scope | M2 `:907-910`, `:948-950`, `:1313-1316`; M3 `:676`, `:686`; M4 `:558-565` | Different canonical keys. Hold. |
| A re-made decision on one request id | M2 `:933-946` | Holds: the same row, so first wins. |
| Log lines carry no command text | M2 `:1301-1332` | The new warning logs ids and scope only. Holds. |
| SRP method counts | `SqliteCommandApprovalStore` 10, `CommandEscalations` 7 | No method added. Holds. |
| Property B cost (9 approval DB calls per approved call) | review report line 36 | The statement count is unchanged (two statements extended). Holds. |

## What This Does NOT Change

- Findings 2 and 3, which go to #1523 as follow-ups. Finding 2: sample the admission time and revalidate the scope after the lock. Finding 3: make `start`/`stop` ownership idempotent.
- `find`, `get`, `list_uses`, the schema and indexes, `resolve`'s ordering, `record_denial`, the router, the tool, `command_gate.py`, the record schema v2, S1, S2a and every frame's text.
- No way to undo a denial. Approving a later request does not lift a live denial, and a deliberate override is out of scope ("considered, deferred"). The denial ends with its TTL or its work item.

## Acceptance Criteria

1. Sections 1-2 install mechanically and each SEARCH occurs exactly once.
2. Both decision orders and the find/use race hold: M1 #1-#4, M2 #5-#6, and the crossing test M4 #7.
3. Mutation rows St4-St12 are killed and St1-St3 rerun and are killed. Record the base and the file's sha256 as the campaign of record.
4. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2b_approval_store.py tests/test_ad1328_s2b_escalation_service.py tests/test_ad1328_s2b_tool_router_shell.py tests/test_ad1328_s2b_seam_and_wiring.py -q -n 0`. Also rerun the reviewer's probes `logs/architect/review1-evidence/test_review_boundaries.py -n 0`: `test_scoped_denial_dominates_overlapping_request` and `test_scoped_denial_dominates_sequential_canonical_variants` now pass. The two finding-2 probes still fail (accepted, #1523).
5. Every test passes on Windows and Linux.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots

A ProbOS-specific store invariant, so no external search was run. Internal precedent: AD-1323's continue-extension permits (`continue_extension_permits.py`, single compare-and-set) put the authority inside the one statement; this repair does the same rather than ordering reads in `resolve`. Considered, rejected: (a) reordering `resolve` to look up the denial first, because it leaves the find/use race and the other-connection case open; (b) gating only in `fulfil_approval` with a `find`, because that is not atomic and misses approve-then-deny. Blind spot recorded: a denial recorded during a `use`'s lock wait is honoured (the subquery runs at UPDATE time), but its `now` is sampled before the lock, so a denial that expires during the wait still blocks. That errs toward refusal and is accepted.

## Verified Against Codebase (2026-10-16, tree `6740e4e0`, HEAD `324b2931`)

```
Read src/probos/execution/command_approvals.py (419 lines, staged = working tree)
  290-330 record_decision: INSERT OR IGNORE ... VALUES (...) under self._lock; returns await self.get(request_id)
  332-354 find: identity + state + expires_at > ? + (state <> 'active' OR work_item OR uses = 0)
  356-397 use: UPDATE ... WHERE request_id/agent/scope/state='active'/expires_at/approver/authority; St1 line :371
  79-80   idx_command_approvals_identity ON (agent_id, scope_key, canonical_key, policy_digest, state)
  263-277 start/stop (finding 3)
Read src/probos/execution/command_escalation.py (395 lines)
  230-248 resolve: find(active) -> _scope_open -> use -> (scope) find(denied) -> except -> _file
  280-292 fulfil_approval: record_decision(active) ; "if row is None or row.state != \"active\": return None" (:285, once)
  294-306 record_denial: refuses empty scope (:297)
grep -n "command_approval" src/probos/startup/communication.py
  313: store = SqliteCommandApprovalStore(db_path=str(data_dir / "command_approvals.db"))
grep -n "INSERT|UPDATE command_approvals|statements" tests/test_ad1328_s2b_*.py
  approval_store.py:104, :592-593 (wrapper pins; see Hidden Pins)
grep -n 'state="denied"|record_denial|approve=False' tests/test_ad1328_s2b_*.py
  approval_store.py:323-330, :404-409, :617 ; escalation_service.py:888-968, :1315 ; seam_and_wiring.py:540, :576 ; tool_router_shell.py:686-727
grep -n "^PUSH|^_PUSH|^def _gate|^async def _call|^async def _approve" tests/test_ad1328_s2b_{seam_and_wiring,escalation_service}.py
  seam_and_wiring.py:68 PUSH = "git push origin"; :107 _gate(platform="linux"); :325 _approve; :370 _call
  escalation_service.py:93-95 _PUSH/_PUSH_OTHER/_PUSH_THIRD; :143 platform="linux"; :319 _approve
Probe evidence (logs/architect/review1-evidence/test_review_boundaries.py)
  :36-54, :411-439 finding 1 (concurrent filing; double-space variant, canonical keys equal on linux)
  :236, :273, :450 finding 2 reproductions each hold an external sqlite3 BEGIN IMMEDIATE
```

## Absence Verified (2026-10-16)

```
CLAIM: no other connection writes command_approvals.db in production (finding 2 is contention-only)
RUN:   Grep "command_approval|SqliteCommandApprovalStore" src/probos/startup/communication.py ; Read command_approvals.py:263-277
FOUND: one constructor (:313) with its own file; start() opens the store's single connection; all writes under self._lock
HOLDS: yes -- the reviewer's probes needed a second raw sqlite3 connection to queue the UPDATE

CLAIM: no existing S2b test other than M1 :338 and :617 records an active row beside a live denial of the same identity and then expects it usable
RUN:   Grep 'state="denied"|record_denial|approve=False' tests/test_ad1328_s2b_*.py, each hit read
FOUND: M2 :907-950 and :1313 use another command or scope, or the same request id; M3 :676/:686 use _OTHER_COMMAND; M4 :558 uses a neighbour command
HOLDS: yes
```
