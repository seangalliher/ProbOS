# AD-729d — Peer observation reinforcement loop (forward marker, NOT a build)

**Status:** FORWARD MARKER — Wave 163 ships the DECISIONS.md entry + roadmap note. No code in this AD.
**Dependencies (hard preconditions):** AD-729 ✅ (Wave 163) + AD-729a (deferred) + AD-729b ✅ (Wave 163) + AD-729c ✅ (Wave 163) + AD-729 operationally stable for ≥2 quarters with no Counselor pattern drift.
**Closes:** #591 (as the forward marker itself; the build is a future wave)
**Estimated tests:** 0 (no code)
**Build order:** LAST in the peer-observation cluster — formal closure of the forward marker.

## Why this is forward-marker-only in Wave 163

Reinforcement creates an optimization gradient that peer perception alone does not. The AD-729 mechanical constraint #1 (read-only with respect to trust) prevents trust drift; reinforcement is the natural channel where that pressure could re-enter the system through DSL drift instead. The issue body lists FIVE hard preconditions, all of which require operational data the system does not yet have:

1. AD-729 has shipped and been operationally stable for ≥2 quarters.
2. AD-729a Standing Orders extended with reinforcement-specific rules.
3. AD-729b Training extended with reinforcement content.
4. AD-729c Counselor monitoring extended with reinforcement-specific detectors.
5. Captain explicit design-stage review (Counselor + Architect joint).

None of those are met by end of Wave 163. AD-729 ships in Wave 163; operational stability takes time, not code.

## What this prompt delivers

Documentation-only deliverable confirming the forward marker is captured in three places:

1. **`DECISIONS.md`** — append AD-729d entry (currently absent from DECISIONS.md per Wave 163 verify-first check; the issue itself exists but the DECISIONS row may not). Single-paragraph entry describing the capability, the five preconditions, and the open design questions.
2. **`docs/development/roadmap.md`** — ensure AD-729d is listed in the forward-marker section with TECHNICAL triggers per AD-722c-3 (NOT calendar dates).
3. **`PROGRESS.md`** — note Wave 163 closure: "AD-729d — forward-marker preserved; no code shipped this wave."

## TECHNICAL triggers (per AD-722c-3)

The forward marker advances to a build prompt when ALL of:

- **Trigger A — operational maturity.** `EventType.PEER_OBSERVATION_RECORDED` count ≥ 100 events across ≥3 distinct observer/observed pairs over a continuous 2-quarter window.
- **Trigger B — conduct stability.** AD-729c `PEER_OBSERVATION_INTERVENTION_TIER_3` event count is 0 across the same 2-quarter window AND no `_TIER_2` events have escalated to `_TIER_3` retry.
- **Trigger C — Standing Orders ready.** AD-729a is shipped AND its Standing Orders content includes a reinforcement-specific section reviewed by Counselor.
- **Trigger D — Training ready.** AD-729b module YAML includes reinforcement content sections AND ≥3 officers have passed the extended module.
- **Trigger E — Captain explicit ruling at design stage.** Documented in DECISIONS.md.

## Open design questions (NOT answered in this forward marker — to be resolved during scoping)

Per issue body, these are recorded as Captain-leans, not final:

1. Reinforcement updates DSL directly vs. produces AD-721d Captain-approval proposals? Lean: proposals only.
2. Scoped to mentor-mentee relationships vs. any-peer-to-any-peer? Lean: mentor-mentee only in v1.
3. Does reinforcement decay? Lean: yes, mirroring AD-729 impression decay.
4. How does reinforcement interact with the Counselor's clinical role? Lean: clinical feedback bypasses peer-reinforcement entirely, uses AD-503 channel.

## Out of scope

- Code. There is no code in this AD.
- Federation reinforcement (cross-mesh) — explicitly deferred even beyond AD-729d.

## Tracking

- `PROGRESS.md`: ADD a Wave 163 entry noting AD-729d was processed as forward-marker housekeeping; issue stays OPEN until preconditions hit.
- `docs/development/roadmap.md`: confirm AD-729d listed with Triggers A-E above.
- `DECISIONS.md`: append AD-729d entry. Issue stays OPEN.
- GitHub issue #591: leave OPEN. Add a comment summarizing Wave 163 disposition.

## Acceptance Criteria

1. `DECISIONS.md` contains a single AD-729d entry with the five TECHNICAL triggers.
2. `docs/development/roadmap.md` AD-729d row exists with TECHNICAL trigger description.
3. `PROGRESS.md` Wave 163 entry notes AD-729d housekeeping.
4. GitHub issue #591 has a comment summarizing the forward-marker disposition.
5. NO source code changes. NO test changes. NO config changes.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.** (Trivial — there are no engineering changes; this AD is documentation-only.)

## Why this is its own prompt instead of folded into AD-729

Folding it in would push Wave 163 closer to scope-creep. AD-729 ships the contract; AD-729d is a future capability with its own safety story. Keeping them separate prompts preserves the architectural seam.
