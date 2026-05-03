# Wave 8.5 — AD-641 Umbrella Split (Architect Subagent Dispatch)

**Date:** 2026-05-02
**Mode:** Architect subagent (`runSubagent` with `agentName: Architect`)
**Output:**
- 6 build prompts at `prompts/ad-641{a,b,c,d,e,f}-*.md`
- 1 dispatch summary at `prompts/WAVE-8.5-SPLIT-SUMMARY.md`
**Purpose:** Split the AD-641 Northstar umbrella ("Ship's Computer / Crew Integration") into 6 sub-AD prompts so Wave 9 (A/B/C sub-waves) can dispatch. Per Wave 5-8 reconciled-plan convention: **umbrella ADs must be split into sub-AD prompts before scheduling, never built directly.**
**Estimated time:** ~1-1.5 hours subagent compute.

---

## Why a meta-prompt instead of direct Wave 9 drafting

The audit and reconciled plan both flagged AD-641 as Northstar-class umbrella scope. Direct drafting of "AD-641" as one prompt produced poor builds in Wave 1-4 (umbrella ADs consistently lose verify-first discipline because the surface area exceeds working-context budget). The Wave 5 retrospective convention #14 (aggressive pre-deferral) and the audit's "umbrella ADs require split-before-schedule" rule converge on this dispatch shape.

Wave 8.5 is the split, not the build. The 6 child prompts produced here become the inputs to Wave 9A (parallel-safe: 641a, 641b, 641f), Wave 9B (cross-cutting: 641c, 641e), and Wave 9C (high-risk: 641d).

---

## Subagent Prompt — paste into `runSubagent` invocation with `agentName: Architect`

```
You are the ProbOS Architect. Wave 8.5 task: split the AD-641 "Ship's Computer / Crew Integration" Northstar umbrella into 6 sub-AD build prompts (641a-f). Wave 8 closed 6/6 ✅; Wave 9 (3 sub-waves on these children) is gated on this split landing first.

Verify-first against the live codebase at d:/ProbOS for every concrete claim — do NOT draft from memory. After drafting, run scripts/phantom-api-precheck.ps1 against all 6 produced prompts (mandatory per Wave 8 Retrospective Addendum convention #16). Iterate until the script reports 0 phantoms OR every flagged candidate is documented as a false positive in the dispatch summary.

## Inputs (read first, in order)

1. .github/copilot-instructions.md — engineering principles, layer architecture, hard rules.
2. DECISIONS.md "Wave 5 Retrospective" + "Wave 5-7 Retrospective Addendum" + "Wave 8 Retrospective Addendum" — full 19-convention running rule set.
3. prompts/AD-BACKLOG-AUDIT.md — AD-641 classification (Northstar umbrella).
4. prompts/WAVE-5-8-RECONCILED-PLAN.md — Wave 8.5/9 sequencing (search "Wave 8.5" and "Wave 9").
5. docs/development/roadmap.md — search for "AD-641" to read the umbrella scope.
6. Vibes/Nooplex_Final.md — Northstar / Cognitive Mesh integration vision (informs sub-AD scoping).
7. Three recent reference prompts (Wave 8) showing the standard template:
   - prompts/archive/ad-475-captains-ready-room.md (Captain HXI surface)
   - prompts/archive/ad-484-user-experience-adoption.md (CLI / UX surface)
   - prompts/archive/ad-449-mcp-bridge.md (HIGH-risk new-package precedent)
8. prompts/review-criteria.md — review-format reference for downstream Wave 9 review.
9. scripts/phantom-api-precheck.ps1 — dispatch-time pre-check tool (RUN before declaring done).

## Sub-AD scoping target (per reconciled plan)

The reconciled plan groups the 6 sub-ADs into 3 sub-waves by risk and parallelism:

| Sub-AD | Sub-wave | Risk | Suggested scope (verify against AD-641 umbrella + Northstar paper) |
|---|---|---|---|
| AD-641a | 9A (parallel-safe) | medium | Ship's Computer voice/persona scaffolding — runtime persona attribute, conversational identity, decomposer prompt grounding extension. |
| AD-641b | 9A (parallel-safe) | medium | Crew Integration — agent presence model, "who's on shift" tracking, presence-aware routing hints. |
| AD-641c | 9B (cross-cutting) | medium-high | Sensorium / Telemetry surface — what the Ship's Computer can "see" of runtime state (CodebaseIndex, registered agents, runtime introspection). |
| AD-641d | 9C (high-risk) | high | Captain↔Computer arbitration / command interpretation — disambiguation of Captain intent, override hierarchy, command grammar. |
| AD-641e | 9B (cross-cutting) | medium-high | Multi-modal HXI integration — visual + verbal channels coordinated; Computer voice meets HXI canvas. |
| AD-641f | 9A (parallel-safe) | medium | LCARS-era response style enforcement — calm/precise/authoritative tone, "unable to comply" over hallucination, sensor-grounded responses. |

These are SUGGESTED scopes. If the verify-first read of the AD-641 umbrella scope (in roadmap.md and Nooplex_Final.md) reveals the natural split is different, REWRITE the table in the dispatch summary and explain why. Do not force-fit if the umbrella divides more cleanly along different lines.

## Required Sections in Each Sub-AD Prompt

Same 12 sections as Wave 6/7/8 main prompts (see Wave 8 reference prompts for canonical structure). Section 0 (EventTypes) is non-negotiable. Each prompt has a Verified Against Codebase footer with grep evidence.

Apply ALL 19 standing conventions (Wave 5 #1-7, Wave 5-7 Addendum #8-15, Wave 8 Addendum #16-19). The Wave 8 conventions are especially relevant here:
- #16: phantom-API pre-check mandatory at dispatch time (RUN THE SCRIPT before declaring done)
- #17: any per-instance mutable state lives in __init__, not class scope
- #18-19: HTTP/JSON-RPC mocks must mock all attributes the code under test reads

## Aggressive Pre-Deferral (convention #14)

Each sub-AD must apply aggressive pre-deferral. Northstar umbrella scope is naturally feature-rich; a single sub-AD shipping "everything" is theater. Each sub-AD's v1 should ship 2-4 capabilities; the rest defer to grandchild ADs (641a-i / 641a-ii / etc.) at draft time.

## Inter-Prompt Dependencies (within Wave 9)

Document explicitly in each prompt's "Depends on" header:

- AD-641a (persona) is foundational for AD-641d (arbitration) and AD-641f (response style).
- AD-641b (presence) is foundational for AD-641c (sensorium — "who's on shift" feeds the sensor surface).
- AD-641c (sensorium) is foundational for AD-641d (arbitration consults sensor state) and AD-641e (HXI surfaces sensor data).
- AD-641d depends on a, b, c — hence its placement in 9C (last sub-wave).
- AD-641e depends on b, c — placement in 9B.

If verify-first reveals different dependency graph, document and revise sub-wave placement.

## Output

Write each sub-AD prompt to:
- prompts/ad-641a-<descriptive-stem>.md
- prompts/ad-641b-<descriptive-stem>.md
- prompts/ad-641c-<descriptive-stem>.md
- prompts/ad-641d-<descriptive-stem>.md
- prompts/ad-641e-<descriptive-stem>.md
- prompts/ad-641f-<descriptive-stem>.md

Pick descriptive stems based on actual scope (e.g., `ad-641a-ships-computer-persona.md`).

Write the dispatch summary to:
- prompts/WAVE-8.5-SPLIT-SUMMARY.md

The summary must include:
- Final scope table (per-sub-AD: title, sub-wave, v1 capabilities, deferred capabilities)
- Dependency graph (text or ASCII)
- phantom-api-precheck.ps1 output (paste verbatim or attach)
- Recommended Wave 9A / 9B / 9C dispatch order

After all 7 files are written, run:

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-641*.md
```

If it reports phantoms, fix them in-prompt before commit (per convention #16). If a flagged candidate is a true false positive, document it in the summary's "Pre-Check Output" section.

Commit with the message:
  "Wave 8.5: split AD-641 umbrella into 6 sub-AD prompts (641a-f); pre-check clean"

Push to origin/main.

## Hard-Stops

Stop and surface to the dispatching architect (NOT the user) if:

1. The AD-641 umbrella scope (per roadmap.md + Nooplex_Final.md) doesn't naturally divide into 6 sub-ADs — surface with a proposal for 4 or 7 children, whatever maps cleanly.
2. The Northstar paper reveals AD-641 capabilities that conflict with the existing runtime surface (e.g., requiring a runtime refactor) — surface; sub-AD scoping shouldn't smuggle in a refactor.
3. phantom-api-precheck.ps1 reports phantoms that are NOT introduced by the sub-AD prompts themselves (i.e., stale references to old class names) — fix and re-run.
4. Two or more sub-ADs would touch the same source file in mutually-incompatible ways — surface for re-bundling (or accept sequencing constraint and document).
5. Section 0 EventType collisions with values already in events.py OR with another sub-AD's Section 0 — pick different names.

## Acceptance Criteria

- 6 sub-AD prompt files created at the listed paths.
- 1 dispatch summary file at prompts/WAVE-8.5-SPLIT-SUMMARY.md.
- Each sub-AD prompt has all 12 required sections in order.
- Each prompt has a Verified Against Codebase footer with grep evidence.
- All 19 standing conventions applied consistently.
- phantom-api-precheck.ps1 reports 0 phantoms (or all flagged candidates documented as false positives in summary).
- Inter-prompt dependency graph documented in summary.
- Single commit lands; push succeeds; no source files touched.

Begin by reading the AD-641 umbrella scope in roadmap.md and the Northstar paper. Then propose the 6-sub-AD split; iterate the table until the divisions are clean. Then draft.
```

---

## Instructions to send to the user (for triggering the dispatch)

Same dispatch pattern as Wave 5/6/7/8:

1. Confirm `.claude/agents/architect.md` is present.
2. Invoke the Architect subagent with the prompt block above.
3. Wall time: ~1-1.5h subagent compute (smaller than a 6-prompt wave because all 6 sub-ADs share the AD-641 umbrella context).
4. When the subagent returns, you'll have 6 sub-AD prompts + 1 split summary in `prompts/`.

After Wave 8.5 lands, the next dispatch is **Wave 9A** (parallel-safe sub-ADs: 641a, 641b, 641f) — a standard 3-prompt review-and-build cycle. Wave 9B (641c, 641e) follows after 9A; Wave 9C (641d) follows after 9B (it depends on a, b, c).

**Wave 8.5 is also the first use of `scripts/phantom-api-precheck.ps1`.** The script's accuracy will be calibrated by this run. If the script over-flags (false-positive rate too high), tune the heuristic before Wave 9A's dispatch. If it under-flags (misses real phantoms that the architect-review pass catches), tune similarly. Calibration is part of the Wave 8.5 deliverable.

**Most likely hard-stops:**

1. Sub-AD scope doesn't divide into 6 cleanly (4 or 7 may be more natural)
2. Northstar paper reveals refactor requirements that should be separate ADs
3. Pre-check false-positive rate too high to be useful

All <15 min architect decisions if they surface.
