# Wave 5 Pre-Flight Hygiene Pass

**Status:** Ready for Architect (some items) + Builder (verification + commit)
**Dependencies:** None — this BLOCKS Wave 5 prompt drafting
**Estimated effort:** ~2 hours total
**Risk:** Low — verification, doc edits, tracker closures only. No production source changes.

---

## Why This Exists

The 2026-04-30 AD backlog audit ([`prompts/AD-BACKLOG-AUDIT.md`](AD-BACKLOG-AUDIT.md)) and the wave-5-8 selection plan ([`prompts/wave-5-8-ad-selection-plan.md`](wave-5-8-ad-selection-plan.md)) both flagged tracker drift and one numbering collision that need resolution before any Wave 5 prompt can be drafted. Letting those drift items through into Wave 5 risks duplicate work (AD-460), a numbering collision corrupting the AD ledger (AD-654), and an unbuildable prompt (AD-557b/c).

The reconciled plan is at [`prompts/WAVE-5-8-RECONCILED-PLAN.md`](WAVE-5-8-RECONCILED-PLAN.md).

This prompt resolves the 5 hygiene items identified there. Once committed, Wave 5 prompt drafting can begin.

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

### Section 1 — AD-460 Status Verification

**Files:** `src/probos/cognitive/journal.py`, `docs/development/roadmap.md`, `PROGRESS.md`

**Action:**

1. Read `src/probos/cognitive/journal.py` end-to-end. Identify which AD-460 sub-features are present:
   - Append-only SQLite schema (timestamp, agent, tier, model, tokens, latency, intent_id, success, cached)?
   - Token accounting per agent / model / DAG?
   - Reasoning-chain replay API?
   - Pattern-extraction queries?
   - Revert-annotation support?
2. Cross-reference with the AD-460 spec at `docs/development/roadmap.md:4154`.
3. **If 100% scope match:** flip `*(planned)*` → `*(complete)*` on line 4154, add a closure entry to PROGRESS.md following the existing AD-NNN CLOSED template, and update [`prompts/WAVE-5-8-RECONCILED-PLAN.md`](WAVE-5-8-RECONCILED-PLAN.md) Wave 6 row to drop AD-460 in favor of AD-491.
4. **If partial match:** annotate roadmap line 4154 with `*(partial — implemented portions: <list>)*` and adjust the AD-460 prompt scope to cover only the missing portions before drafting in Wave 6.
5. **If no match (existing journal.py is unrelated work):** leave AD-460 in Wave 6 as drafted; add a roadmap note that journal.py exists for an unrelated purpose.

Builder note: do NOT make code changes to `journal.py` in this hygiene pass. Source changes belong to AD-460's own build prompt.

### Section 2 — AD-654 Numbering Collision

**Files:** GitHub issues #313 and #322 (via `gh CLI`).

**Architect decision (must happen before Builder runs this section):**

- Audit recommendation: keep AD-654 = #313 (Ship State Snapshot — has roadmap detail). Renumber #322 (UAAA) to next-available.
- Architect confirms or counters this recommendation by reading both issue titles and any associated roadmap entries.

**Builder action (after architect decision):**

1. Find the next-available AD number. Run:
   ```pwsh
   d:/ProbOS/.venv/Scripts/python.exe -c "import re,pathlib; nums = sorted({int(m.group(1)) for f in [pathlib.Path('PROGRESS.md'), pathlib.Path('DECISIONS.md')] for m in re.finditer(r'AD-(\d{3,4})', f.read_text(encoding='utf-8'))}); print('next:', max(nums)+1)"
   ```
2. Use the architect's chosen issue (loser of the AD-654 collision). Rename its title via `gh issue edit <issue-number> --title "AD-NNN: <new-title>"` where NNN is the next-available number.
3. Update any references to that issue's old AD-654 designation in `docs/development/roadmap.md`.

If `gh CLI` is not authenticated, surface to architect and skip the GitHub edit; the renumbering can land in a follow-up.

### Section 3 — AD-557b/c (#11) Description Decision

**File:** GitHub issue #11.

**Architect decision (must happen before Builder runs):**

- Option A: write a 1-paragraph description grounded in the issue title + adjacent ADs (AD-557 closed parent), commit it as the issue body via `gh issue edit 11 --body "<text>"`.
- Option B: drop AD-557b/c from the buildable set, close issue #11 as "won't fix — superseded by AD-557 closed parent."

**Builder action:** apply whichever the architect chose. If Option A, paste the architect-provided text into the issue body. If Option B, close the issue with the architect's stated reason.

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

Builder cannot fully execute Sections 1, 2, 3 without architect input. The architect must answer these before Builder begins:

1. **Section 1 outcome:** if AD-460 is partial or unrelated, what's the new Wave 6 fifth slot? (Recommendation: AD-491 if AD-460 is CLOSED.)
2. **Section 2 outcome:** which issue keeps AD-654, which renumbers? (Recommendation: #313 keeps; #322 renumbers.)
3. **Section 3 outcome:** Option A (fill body) or Option B (close issue)? If A, what's the description text?

Builder should refuse to start until all three answers are recorded in this prompt's "Architect Pre-Decisions" comments OR in a follow-up message.
