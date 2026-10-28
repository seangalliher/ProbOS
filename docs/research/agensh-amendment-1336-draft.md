# Draft: AD-1289 (#1336) amendment from Agensh

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28. Revised the same day to the Captain's scaled-back decision.

This file is a staging draft and has not been posted. Part A is the text to append to the body of #1336. Part B is the decision record and the grep evidence, and stays here.

---

## Part A — text to append to #1336

## Amendment (2026-10-28): disproved approaches, from Agensh

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28. Applied on the Captain's approval, YYYY-MM-DD.

**Prior art:** Agensh (Zhan et al., Microsoft Research, arXiv 2609.26781). Absorption note: `docs/research/agensh-organization-harness-absorption.md`. Agensh workers record each falsified approach as a `FAIL` entry on a shared board, so that peers do not spend budget repeating it. The paper ablates no mechanism and does not normalize compute: every configuration gets the same wall clock, with one model session per worker. Nothing shows that `FAIL` entries help on their own.

### Added decision

- **A disproved approach is recorded as `evidence` with the marker `disproved: true`.** No new kind is added, following #1337's CORAL precedent. Reason: the entry is evidence about an approach, and a marker can be filtered on without every consumer learning a new kind.
  - The entry states what was tried and why it failed, and links at least one further `evidence` or `artifact_ref` entry.
  - Only an agent writes one. The service never writes it on the agent's behalf (AD-1231).
- **Teammates in the same CrewSession see it before repeating it.** The bounded board read that a worker receives when its attempt starts includes the session's current `disproved` entries.
  - Slots declared `independence`, and review, verification and adjudication slots, are excluded until they submit. This follows #1337's rule that workers read outcomes, not reasoning.
- **No retry ban.** To retry deliberately, an agent first files a `challenge` that targets the entry. Like any other entry, it can be superseded and is never deleted.

### Added acceptance

- A `disproved` entry without a linked `evidence` or `artifact_ref` is refused before mutation.
- A worker starting an attempt receives the session's current `disproved` entries in its bounded read. An independence-declared or review slot does not receive them before it submits.
- A `challenge` targeting a `disproved` entry is accepted. Reads report the entry's current disposition, and the entry stays auditable.
- No code path writes a `disproved` entry on an agent's behalf.

---

## Part B — not for posting

### Decision record

**The Captain, 2026-10-28.** Scaled back from the first draft.

- **Ownership stays as #1336 is written:** CrewSession-owned (option 3). Nothing is widened, so no ratification is needed.
- **Dropped:**
  - re-keying ownership to work items, and the membership rule for ordinary work items;
  - area claims and declared scope;
  - overlap notices;
  - urgent mid-turn delivery and its delivery table;
  - the three trial flags and their trial arms.
- **Reason:** persistent crew already collaborate on one task through CrewSession. It decomposes the plan, assigns by capability × trust × department (AD-864), deduplicates ingress (AD-1128) and finalizes on verification (AD-1126). Agensh's claim and overlap machinery compensates for having no planner, and ProbOS has one.
- **Form chosen:** `evidence` with a `disproved` marker, not a new kind. This follows #1337's CORAL precedent.

**Effects on other issues:**
- **#1337 (AD-1290):** no cross-reference is needed. The marker is agent-written and sits beside CORAL's service-written ledger entries, which also use `evidence`. Neither changes the other.
- **AD-1310 (#1361):** no note is needed. No new kind is added, so the canvas's object list is unchanged.
- **AD-1348 (#1630):** no interaction. Work permits are untouched.

No new AD or BF number is allocated, because this is an amendment to AD-1289.

### Verified Against Codebase (2026-10-28, HEAD `791d15fc`, matches `origin/main`)

```
gh api repos/seangalliher/ProbOS/issues/1336 --jq .body
  Decision: "Add a typed mission blackboard owned by the durable CrewSession/team instance"
  Kinds: claim, evidence, challenge, decision, dissent, question, artifact_ref ("optional target-entry reference")

gh api repos/seangalliher/ProbOS/issues/1337 --jq .body
  CORAL amendment (2026-10-25): "These use existing AD-1289 entry kinds; no new kind is added."
  "Workers read outcomes, not reasoning." Independence-declared slots read no peer claim before they submit

grep -n "independence: IndependencePolicy" src/probos/cognitive/elastic_team.py
  255: independence: IndependencePolicy

grep -n "AD-864\|AD-1126" src/probos/cognitive/crew_assignment.py src/probos/cognitive/crew_finalizer.py
  crew_assignment.py:1: """AD-864: Capability × trust × department → agent_id resolution for crew sub-tasks.
  crew_finalizer.py:1:  """AD-1126: verified CrewSession finalization and result publication."""

grep -n "AD-1128" DECISIONS.md
  2525: ### AD-1128 (2026-07-21) - unified CrewSession ingress and dedup (#1047)

grep -n "resolve -> delegate" src/probos/cognitive/crew_orchestrator.py
  23: resolve -> delegate -> fan-out -> verify -> synthesize
```

### Absence Verified (2026-10-28)

```
CLAIM: #1336 is unbuilt, so the marker needs no schema migration
RUN:   Grep -i "blackboard" src/probos
FOUND: 0 matches
HOLDS: yes
```

AD-1128 is CrewSession *ingress* deduplication: it prevents duplicate sessions. It is not sub-task overlap detection. The Captain's reason does not rely on it for that: sub-task allocation is done by the planner and AD-864 assignment.
