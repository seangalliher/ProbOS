# Wave 5 Pre-Flight Hygiene Pass

**Status:** Ready for Architect (some items) + Builder (verification + commit)
**Dependencies:** None — this BLOCKS Wave 5 prompt drafting
**Estimated effort:** ~2 hours total
**Risk:** Low — verification, doc edits, tracker closures only. No production source changes.

---

## Why This Exists

The 2026-04-30 AD backlog audit ([`prompts/AD-BACKLOG-AUDIT.md`](AD-BACKLOG-AUDIT.md)) and the wave-5-8 selection plan ([`prompts/wave-5-8-ad-selection-plan.md`](wave-5-8-ad-selection-plan.md)) both flagged tracker drift before any Wave 5 prompt can be drafted.

**Architect-resolved on 2026-04-30 (no Builder action needed):**
- AD-460 marked partial-complete; reasoning-replay scope closed (DECISIONS.md entry; Wave 6 slot swapped to AD-491).
- AD-654 numbering collision: #313 renumbered to AD-683; #322 keeps AD-654.
- AD-557b/c (#11) closed as won't-fix-now.

**Remaining for Builder:**
- ~47 stale GitHub issues for already-closed ADs need batch-closure.
- `prompts/wave-5-8-ad-selection-plan.md` needs AD-455 directory-ownership note.

The reconciled plan is at [`prompts/WAVE-5-8-RECONCILED-PLAN.md`](WAVE-5-8-RECONCILED-PLAN.md).

## What This Does NOT Change

- No production source code changes. No new tests.
- No prompt drafting for Wave 5 ADs.
- No changes to `DECISIONS.md` content (only metadata fixes if needed).

## Verified Against Codebase (2026-04-30)

```
grep -n "class CognitiveJournal" src/probos/cognitive/journal.py
  56: class CognitiveJournal:

grep -n "AD-460" docs/development/roadmap.md
  832: **Cognitive Journal (Token Ledger)** *(AD-460)*
  4154: **AD-460: ... *(planned)* — Append-only SQLite recording...

grep -rn "cognitive_services" .github/
  (no matches — audit's doc-drift claim was a false positive)

grep -rn "src/probos/security/" src/probos/
  (no matches — directory does not exist)

# Highest currently-allocated AD number to inform AD-654 collision rename
grep -rn "AD-68[0-9]\|AD-69[0-9]" PROGRESS.md DECISIONS.md
  # Builder runs this; expected highest is AD-682 from the audit context.
```

## Implementation

### Section 1 — AD-460 Status (RESOLVED — skip)

**Status:** Already applied by architect on 2026-04-30. Roadmap status flipped to `*(partial)*`, DECISIONS.md AD-460 entry added, PROGRESS.md updated, Wave 6 fifth slot swapped to AD-491.

**Builder action:** none. Verify by `grep -n "AD-460" docs/development/roadmap.md DECISIONS.md PROGRESS.md` and confirm the new entries are present.

### Section 2 — AD-654 Numbering Collision (RESOLVED — skip)

**Status:** Already applied by architect on 2026-04-30. Issue #313 renumbered to AD-683 (title + body updated). Roadmap header (line 7082) and entry updated. Issue #322 keeps AD-654.

**Builder action:** none. Verify by `grep -n "AD-683" docs/development/roadmap.md` and `gh issue view 313 --json title` (expect `AD-683:` prefix).

### Section 3 — AD-557b/c (#11) Description (RESOLVED — skip)

**Status:** Already closed by architect on 2026-04-30 with won't-fix-now reasoning. AD-557 closed parent preserves the deferral history.

**Builder action:** none. Verify by `gh issue view 11 --json state` (expect `CLOSED`).

### Section 4 — Stale GitHub Issue Cleanup (47 issues)

**Files:** GitHub issues for already-closed ADs (per the audit's stale-list).

**Builder action:**

1. Re-run the audit's stale-detection logic against the current main:
   ```pwsh
   # Pseudo-code; adapt to gh CLI:
   gh issue list --label "type: ad" --state open --json number,title --limit 200 \
     | python -c "process: for each AD-NNN title, check if PROGRESS.md or DECISIONS.md marks it CLOSED|COMPLETE. Output stale list."
   ```
2. For each stale issue: `gh issue close <number> --comment "Closed per tracker state. PROGRESS.md / DECISIONS.md mark this AD as complete. Reopened only if scope is reverted."`
3. Total expected: ~47 closures. If the count differs significantly from 47, surface — that means either the audit was wrong or new ADs landed since.

If `gh CLI` is unavailable, batch the issue numbers into a follow-up file and skip this section. Surface the file path so the architect can run it manually.

### Section 5 — `src/probos/security/` Plan Note

**File:** `prompts/wave-5-8-ad-selection-plan.md`.

**Action:** add a line to the AD-455 row noting "owns `src/probos/security/__init__.py` creation, mirroring AD-676's `governance/` precedent." Single-line addition. No source changes.

### Section 6 — Update Trackers

**Files:** `PROGRESS.md`, `docs/development/roadmap.md`.

Add hygiene-pass entries documenting what was done:

- `PROGRESS.md`: add a single line at the top: `Hygiene Pass 2026-04-30: AD-460 status verified, AD-654 collision resolved (renumbered #XXX → AD-NNN), AD-557b/c clarified, 47 stale GitHub issues closed. See prompts/hygiene-wave5-prereq.md.`
- `docs/development/roadmap.md`: update AD-460 status per Section 1's outcome; update AD-654 row(s) per Section 2's outcome.

## Acceptance Criteria

- AD-460 status reflects reality (CLOSED / partial / unrelated as determined).
- AD-654 collision resolved — both issues have distinct AD numbers.
- AD-557b/c (#11) either has a body OR is closed.
- ~47 stale GitHub issues closed (or batched for follow-up if `gh CLI` unavailable).
- `prompts/wave-5-8-ad-selection-plan.md` carries the AD-455 directory-ownership note.
- `PROGRESS.md` and `docs/development/roadmap.md` reflect the changes.
- All five sections committed in one descriptive commit.

## Pre-Commit Sanity Check (per BUILDER-EXECUTION-PLAN)

```pwsh
git diff --cached --stat
```

Expected delta:
- `PROGRESS.md`: ~3-5 lines added.
- `docs/development/roadmap.md`: ~2-5 lines changed (AD-460 + AD-654 status updates).
- `prompts/wave-5-8-ad-selection-plan.md`: 1-2 lines added.

If any file shows >50 deletions, STOP. Tracker files are append-mostly.

## Tracking

- `PROGRESS.md`: hygiene-pass log entry.
- `docs/development/roadmap.md`: AD-460 + AD-654 status updates.
- `DECISIONS.md`: no entry needed (this is process hygiene, not architecture).
- GitHub issues: ~48-49 issue mutations (47 closures + AD-654 rename + #11 close-or-fill).

## Commit Message

```
Hygiene wave-5 prereq: AD-460 status verified, AD-654 renumbered, AD-557b/c resolved, stale GitHub issues closed
```

## Engineering Principles Applied

- **Verify-first:** every claim backed by grep of the live codebase before action.
- **Fail-fast:** if `gh CLI` is unauthenticated, surface immediately rather than proceeding with stale data.
- **No scope creep:** code is untouched. This is process work only.
- **Reversibility:** all changes are tracker edits or GitHub state mutations. Trivial to revert if something is wrong.

## Future Work (out of scope)

- A CI hook or scheduled job that auto-syncs PROGRESS.md state into GitHub issue closures. AD candidate: "AD-684: Tracker Sync Automation."
- An audit subagent run after every wave to catch new drift early. Should be cheap once it's a recurring pattern.

---

## Architect Pre-Decisions Required

All architect pre-decisions are resolved as of 2026-04-30. Builder can execute Sections 4 and 5 immediately. Sections 1-3 are documentation-only verification.
