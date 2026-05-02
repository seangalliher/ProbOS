# Wave 8 Prompt Drafting — Architect Subagent Dispatch

**Date:** 2026-05-02
**Mode:** Architect subagent (use the Architect agent type)
**Output:**
- 5 main build prompts at `prompts/ad-{469,449,472,484,475}-*.md`
- 1 Combo A prompt at `prompts/combo-A-trivial-extensions.md` (covers 8 trivial-class child ADs in a single Builder commit)
**Estimated time:** ~2–2.5 hours subagent compute (5 main prompts + 1 combo prompt covering 8 trivial extensions)

---

## Subagent Prompt — paste into `runSubagent` invocation with `agentName: Architect`

```
You are the ProbOS Architect. Draft Wave 8 of the wave-5-8 fleet sweep: 5 standard
build prompts + 1 Combo A prompt covering 8 trivial extensions in a single Builder
commit. Apply all conventions established by Waves 5/6/7 (DECISIONS.md "Wave 5
Retrospective" entry + "Wave 5-7 Retrospective Addendum" entry, both dated
2026-05-01/2026-05-02) — they are MANDATORY for Wave 8 prompts.

Verify-first against the live codebase at d:/ProbOS for every concrete claim — do
NOT draft from memory.

## Inputs (read first, in order)

1. .github/copilot-instructions.md — engineering principles, layer architecture,
   hard rules. Special attention: § Repository Boundary — OSS vs Commercial. The
   AD-450 leak is the canonical failure precedent; Commercial-tagged AD entries
   describe the extension point only — pricing / revenue model / customer counts
   / GTM language belong in commercial-roadmap.md. AD-449 in this wave IS
   Commercial-tagged.
2. prompts/review-criteria.md — review tiers and standing format.
3. DECISIONS.md "Wave 5 Retrospective" — 7 standing conventions.
4. DECISIONS.md "Wave 5-7 Retrospective Addendum" — 8 additional conventions
   (#8-15) including TYPE_CHECKING ALLOWED_EXCEPTIONS, ASCII-only comments,
   work_item_store/workforce clarity, __new__-bypass defensive-getattr, Solution
   Overview drift discipline, pool collision pre-check, aggressive
   pre-deferral, tolerance-mode decision.
5. prompts/WAVE-5-8-RECONCILED-PLAN.md — wave context and sequencing.
6. prompts/wave-5-8-ad-selection-plan.md — per-AD scope summaries.
7. prompts/AD-BACKLOG-AUDIT.md — classification table.
8. Three recent reference prompts (Wave 6 + Wave 7) showing the standard template:
   - prompts/archive/ad-451-validation-framework-hardening.md (HIGH risk;
     real-consumer wiring; flat-dataclass discipline)
   - prompts/archive/ad-456-security-infrastructure.md (HIGH risk; extends
     existing class instead of introducing new; explicit deferred sub-AD list)
   - prompts/archive/ad-463-model-diversity-neural-routing.md (HIGH risk
     foundation; aggressive pre-deferral of 6 of 10 capabilities)
9. .claude/agents/architect.md (if accessible) — architect agent standing
   instructions.

Match these reference prompts' structure and verify-first discipline.

## Wave 8 ADs to draft

### Main prompts (5)

| AD | Title | Risk | Audit Group | Roadmap line |
|---|---|---|---|---|
| AD-469 | EPS — Compute/Token Distribution | high | 4 | docs/development/roadmap.md:4185 |
| AD-449 | MCP Bridge (Commercial-tagged; OSS bridge infrastructure) | high | 4 | docs/development/roadmap.md:4111 |
| AD-472 | Channel Adapters — Multi-Platform Communication | medium | 3 | docs/development/roadmap.md:4193 |
| AD-484 | User Experience & Adoption Readiness | medium | 3 | docs/development/roadmap.md:7024 |
| AD-475 | Captain's Ready Room — Strategic Planning Interface | medium | 3 | docs/development/roadmap.md:4201 |

### Combo A prompt (1, covers 8 ADs in a single Builder commit)

A single combo prompt at prompts/combo-A-trivial-extensions.md covering these 8
trivial child ADs from the audit's Combo A recommendation:

| AD | Title | Source AD parent |
|---|---|---|
| AD-538b | Dream Consolidation Manifest | AD-538 (closed) |
| AD-572b | Captain Engagement Extensions (DM) | AD-572 (closed) |
| AD-573b | Working Memory Extensions | AD-573 (closed) |
| AD-575b | Self-Awareness Proactive + DM | AD-575 (closed) |
| AD-576b | LLM Retry with Exponential Backoff | AD-576 (closed) |
| AD-526c | Recreation System Extensions | AD-526a (closed) |
| AD-655 | Contrastive Memory Retrieval | AD-647 closed parent |
| AD-656 | Department-Specific Cognitive Profiles | AD-647 closed parent |

The combo prompt structure differs from a main prompt: it has 8 mini-sections
(one per AD) under a single overall scope, a unified test plan, and a single
tracker-update block. Each mini-section follows the same pattern (verify-first,
Section 0 events if any, implementation, tests).

## Required Sections in Each Main Prompt

Same 12 sections as Wave 6/7. Section 0 (EventTypes) is non-negotiable. See
reference prompts for the canonical structure.

## Required Structure for Combo A Prompt

```
# Combo A: 8 Trivial Extensions (Wave 8)

**Status:** Ready for builder
**Scope:** 8 child ADs grouped into a single Builder commit per audit recommendation
**Total estimated tests:** ~25-40 (3-5 per child AD)
**Risk:** Low — each child is a config knob / one-file tweak / additive helper

## Why Combo

Per AD-BACKLOG-AUDIT.md: 8 trivial extensions to already-closed parent ADs.
Each is one-file, additive, low-risk. Per-prompt overhead × 8 would multiply
Builder commit cost ~5×; combo is cleaner.

## Combo Discipline

- Each child AD is a separate H2 section (## AD-NNN: Title).
- Each child has its own Verify-First grep evidence + implementation + test plan.
- Single Section 0 (EventTypes) at the top covers all 8 children's new events.
- Single Tracker section at the bottom updates PROGRESS.md/roadmap.md for all 8.
- Single commit closes all 8 ADs with message "Combo A: AD-NNN/NNN/NNN/...
  trivial extensions".

## AD-538b: Dream Consolidation Manifest
[full mini-section: problem, solution, sections, tests, verify-first]

## AD-572b: Captain Engagement Extensions
[...]

(repeat for all 8)

## Combo Test Plan

A unified test count + a single command to run them all in one file:
prompts/build-reports/combo-A-build.md.

## Combo Tracker Updates

PROGRESS.md: add 8 entries (one per child AD).
roadmap.md: flip 8 status flags.
DECISIONS.md: no entry needed (these are extensions of closed parents).
```

## Wave-5/6/7 Standing Conventions (15 total — MANDATORY)

These are now standing rules per the DECISIONS.md retrospective entries:

**Wave 5 (#1-7):**
1. Public-attribute wiring (no leading underscore for cross-module accessors).
2. stdlib-only for runtime-written persistence (no new pyproject deps).
3. Coordinator-then-dispatch (defer write-side mechanism to sub-AD).
4. Superset-filter discipline (new hooks don't intercept existing test cases).
5. init_<phase> startup signatures (grep before claiming runtime.X is in scope).
6. Verify-first for anchor names (grep evidence in footer).
7. No-theater discipline (v1 components do real work today OR are wholly deferred).

**Wave 5-7 Addendum (#8-15):**
8. TYPE_CHECKING cross-layer + ALLOWED_EXCEPTIONS entry.
9. ASCII-only source comments (avoid Unicode arrows / em-dashes).
10. runtime.work_item_store stores items; runtime.workforce schedules them.
11. __new__-bypass defensive-getattr (use getattr(self, name, None) for paths
    BF-069-style tests may hit).
12. Solution Overview drift discipline (re-read top-of-prompt after Revision).
13. Pool template name collision pre-check (grep agent_fleet.py before drafting).
14. Aggressive pre-deferral (defer at draft time, not at review time).
15. Tolerance-mode: relaxed (1 ⚠️ on highest-risk; reverted from Wave 7 strict).

## AD-Specific Requirements

### AD-469 (EPS — Compute/Token Distribution)
- Verify-first: this depends on AD-460 (Cognitive Journal partial-complete) and
  AD-467 (Operations Crew, Wave 7 ✅). Verify the journal's existing schema
  supports per-agent token cost aggregation and that AD-467's Operations
  package is the right wiring point.
- 7 capabilities listed in roadmap. Apply convention #14: pre-defer at least 3.
  v1 likely ships: Capacity tracking + Department budgets + Captain override.
  Defer alert-aware reallocation, back-pressure, atomic budget enforcement,
  prompt caching hierarchy to AD-469b/c/d.
- Section 0 EventType: EPS_BUDGET_EXCEEDED, EPS_REALLOCATION.
- HIGH risk: cross-cutting (touches LLMClient, IntentBus budget hooks,
  HXI override surface).

### AD-449 (MCP Bridge — Commercial-tagged)
- ★ COMMERCIAL BOUNDARY ALERT: AD-449 is Commercial-tagged in the public roadmap.
  Per the AD-450 leak precedent and § Repository Boundary in copilot-instructions:
  the prompt body must describe the OSS bridge infrastructure ONLY. Do NOT include
  pricing, revenue model, customer counts, or pre-built MCP server pack pricing.
  The phrase "commercial details in commercial-roadmap.md" is the canonical
  pointer. Pre-commit hook will reject otherwise.
- Verify-first: grep for any existing MCP/JSON-RPC patterns (likely none in src/
  but verify). Likely creates src/probos/integrations/mcp_bridge/ (NEW package).
  AD-449 OWNS the directory creation.
- Apply convention #3: v1 OSS ships the bridge infrastructure (session
  management, tool routing, JSON-RPC over Streamable HTTP). Pre-built MCP
  server packs (Salesforce, ServiceNow, etc.) are commercial-only and NOT in
  this prompt — they live in the private commercial repo entirely.
- Section 0 EventType: MCP_BRIDGE_INVOKE, MCP_BRIDGE_FAILED.
- HIGH risk: new external-protocol surface; security review needed at
  Builder time. Coordinate with AD-456's existing EgressPolicy (Wave 7 ✅) —
  MCP bridge calls go through EgressPolicy.

### AD-472 (Channel Adapters — Multi-Platform)
- Verify-first: grep src/probos/channels/ for the existing Discord adapter.
  AD-472 EXTENDS this — does NOT introduce new ChannelAdapter ABC.
- 5 channel adapters listed (Discord enhancements + Slack + Telegram + WhatsApp
  + Matrix + Webhook). Apply convention #14: v1 likely ships 2-3 adapters.
  Recommend: Discord enhancements + Slack + Webhook. Defer Telegram, WhatsApp,
  Matrix, Teams to AD-472b/c/d.
- Each adapter introduction is OPT-IN via uv extras (`uv sync --extra slack`).
  No new HARD pyproject deps — match the AD-465 / Wave 6 stdlib-only convention.
- Section 0 EventType: CHANNEL_MESSAGE_RECEIVED, CHANNEL_DELIVERY_FAILED.
- MED risk: external-platform surface; rate-limit / authentication paths.

### AD-484 (User Experience & Adoption Readiness)
- Verify-first: grep `pyproject.toml` for current build/release config; grep
  `cli/` (probably src/probos/__main__.py and any bin scripts) for existing
  command structure.
- Mostly REPO-LEVEL changes (PyPI metadata, Homebrew formula, GitHub Releases
  workflow, Rich TUI wizard). NOT a Python runtime AD. Apply convention #2:
  no new pyproject deps; reuse Rich (already a dep).
- 4 capabilities (Distribution & Packaging + Onboarding Wizard + Quickstart
  Docs + Demo Mode). v1 likely ships: PyPI publishing config + `probos init`
  TUI wizard + docs. Defer Homebrew, demo mode to AD-484b.
- Section 0 EventType: none expected (UX/packaging — not runtime events).
- MED risk: most repo-level work doesn't touch runtime semantics.

### AD-475 (Captain's Ready Room — Strategic Planning Interface)
- Verify-first: grep src/probos/experience/ for existing HXI surface; grep
  src/probos/cognitive/architect.py for ArchitectAgent integration points.
- 3 capabilities (Idea Capture + Ready Room Sessions + Architecture Hierarchy).
  Apply convention #14: v1 likely ships Idea Capture + Ready Room Sessions
  with Cognitive Journal recording. Defer Architecture Hierarchy (TOGAF
  Enterprise/Solution/Technical scaffold) to AD-475b — it's a sizeable
  extension of the planning model.
- Section 0 EventType: READY_ROOM_SESSION_STARTED, IDEA_CAPTURED.
- MED risk: HXI surface (read convention 12 — Solution Overview drift was
  caught in Wave 7).

### Combo A (8 trivial extensions)

For each child AD in the combo:

- **AD-538b** — Dream Consolidation Manifest. Per-episode per-step manifest;
  skip-already-processed hint for dream consolidation. Touches dreaming.py +
  new manifest store.
- **AD-572b** — Captain Engagement DM extensions: alert injection, ward room
  activity, priority queue, task awareness. Touches proactive.py + dm_routing.
- **AD-573b** — Working Memory extensions: relational, scratchpad, dream
  pipeline, journal source, commitments. Touches working_memory.py.
- **AD-575b** — Self-awareness in proactive path + DM forwarded content.
  Touches proactive.py.
- **AD-576b** — LLM retry with exponential backoff in proactive path.
  Single-line behavior change. Touches proactive.py.
- **AD-526c** — Recreation System extensions: more games, prefs, spectators,
  holodeck integration. Touches recreation/ package.
- **AD-655** — Contrastive Memory Retrieval. cognitive/chain.py + episodic.py.
- **AD-656** — Department-Specific Cognitive Profiles. config/organization.yaml
  + chain modulation. Touches Section 0 with no new EventType (config-only).

For Combo A: keep each mini-section under ~80 lines. Verify-first discipline is
mandatory per child AD — grep evidence per child, not just at the top.

## Inter-Prompt Dependencies

- **AD-469 depends on AD-467 (Wave 7 ✅) + AD-460 (partial-complete).** No new
  prerequisites in Wave 8.
- **AD-449 builds on AD-456 (Wave 7 ✅, EgressPolicy).** AD-449 calls go
  through EgressPolicy.
- **Combo A children depend on closed parents only** (AD-538, 572, 573, 575,
  576, 526a, 647). No Wave 8 inter-AD dependencies.
- **No cross-AD source-file conflicts within Wave 8 main prompts** verified by
  the audit.
- **Combo A may touch the same files as one main prompt:** AD-572b touches
  proactive.py; AD-575b touches proactive.py; AD-576b touches proactive.py.
  AD-475 likely touches different paths but verify. Combo A's three
  proactive.py touches must be sequential within the combo (they share the
  same file), not parallel.

## Output

Write each main prompt to:
- prompts/ad-469-eps-compute-token-distribution.md
- prompts/ad-449-mcp-bridge.md
- prompts/ad-472-channel-adapters.md
- prompts/ad-484-user-experience-adoption.md
- prompts/ad-475-captains-ready-room.md

Write the Combo A prompt to:
- prompts/combo-A-trivial-extensions.md

Do NOT modify any source files. Do NOT modify PROGRESS.md / DECISIONS.md /
roadmap.md. The output of this dispatch is 6 prompt files only.

After all 6 prompts are written, run a final pre-commit check:

  git diff --cached --stat

Expected delta: 6 new files. Main prompts ~500-800 lines each (AD-469 and
AD-449 likely larger due to HIGH risk + cross-cutting); Combo A ~400-600 lines
total (~50-75 per child × 8). Total ~3000-4500 lines. No deletions.

Commit with the message:
  "Wave 8: draft prompts for AD-469, AD-449, AD-472, AD-484, AD-475 + Combo A"

Push to origin/main.

## Hard-Stop Conditions

Stop and surface to the dispatching architect (NOT the user) if:

1. AD-449's prompt body includes pricing, customer counts, or GTM language —
   the AD-450 leak precedent triggers a hard stop. Reframe to extension-point
   description only.
2. AD-469's capacity-tracking implementation requires modifications to AD-460's
   CognitiveJournal schema — surface for explicit architect approval before
   committing.
3. AD-472's adapter introduction requires NEW hard pyproject dependencies —
   each adapter must be opt-in via uv extras.
4. Combo A's eight children share file conflicts that can't be sequenced
   safely (e.g., two children rewriting the same line) — surface for re-
   bundling.
5. Any AD's Section 0 EventTypes collide with values already in events.py
   OR with another Wave 8 prompt's Section 0. Pick a different name.
6. AD-475's Architecture Hierarchy (TOGAF) scope is being absorbed into v1
   instead of deferred to AD-475b — surface; this is exactly the no-theater
   risk Wave 7 caught on AD-451 / AD-456 / AD-463.

## Acceptance Criteria

- 6 prompt files created at the listed paths.
- Each main prompt has all 12 required sections in order.
- Combo A has the 8 mini-sections + unified Section 0 + unified Tracker
  + verify-first per child.
- Each prompt has a Verified Against Codebase footer with grep evidence for
  every concrete claim.
- AD-449 contains NO pricing / GTM / customer-count language; describes the
  OSS bridge infrastructure only.
- AD-469 / AD-472 / AD-475 each apply convention #14 (aggressive pre-deferral).
  Each lists explicit v1 scope and deferred sub-AD list.
- AD-484 ships without new pyproject deps; reuses Rich.
- All 15 Wave 5/6/7 standing conventions applied consistently.
- Single commit lands; push succeeds; no source files touched.
- Pre-commit hook does NOT block (or blocks correctly with --no-verify
  justification).

Begin.
```

---

## Instructions to send to the user (for triggering the dispatch)

Same dispatch pattern as Wave 5/6/7:

1. Confirm `.claude/agents/architect.md` is present.
2. Invoke the Architect subagent with the prompt block above.
3. Wall time: 2–2.5 hours subagent compute (5 mains + Combo A).
4. When the subagent returns, you'll have 6 prompt files in `prompts/`.

After dispatch, the standard 3-pass review cadence (review → revision →
second-pass review). Wave 5/6/7 history shows fresh batches converge in 1-2
review iterations under relaxed tolerance (Wave 5: 2 + 1 mechanical fix; Wave 6:
2 clean; Wave 7: 3 due to strict tolerance choice now reverted per convention #15).

**Commercial-boundary check** is the highest-priority pre-flight item this
wave. AD-449 must not leak pricing or GTM language. The pre-commit hook will
catch some patterns; the architect should also do a final read of AD-449
before approving for review.

**Combo A is the wave's main novelty.** Watch for the 8-children-in-one-prompt
shape converging well in review — if Combo A's review pass surfaces tangled
findings that span children, the combo pattern may need refinement before
Wave 9+. If it converges cleanly, it's the standard for trivial-cluster ADs
going forward.

Most likely hard-stops:

- AD-449 commercial-boundary violation (pricing leak)
- AD-469 CognitiveJournal schema modification scope creep
- Combo A child file conflicts requiring re-bundling

All <10 min architect decisions if they surface.
