# Wave 19 — AD-530 v1 Information Classification Enforcement (Disclosure Gate)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly.
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit + GH #104 closure.
**Estimated time:** ~2 hours total subagent compute.

---

## Wave 19 scope

| AD | Title | Risk |
|---|---|---|
| AD-530 v1 | Information Classification Enforcement — Disclosure Gate | medium |

v1 ships 2 of 4 capabilities (classification labels via existing _CLASSIFICATION_LEVELS reuse + observational disclosure gate with pattern scanner). Security Chief ownership (AD-530b), audit trail (AD-530c), active enforcement (AD-530d) all deferred. Read-only consumer of records_store hierarchy.

**Closes GH issue:** #104.

---

## Stage 1 — Architect: Review Pass 1

Standard review dispatch. Wave 19 specific attention:

1. **Pre-deferral honesty.** v1 ships 2 of 4 capabilities. Verify NO Security Chief runtime updates, full audit trail, or active enforcement (mutation/redaction) smuggled in.
2. **`_CLASSIFICATION_LEVELS` reuse.** Gate must consume existing hierarchy at records_store.py:27 — NOT duplicate it. Verify by grep that there's no parallel `_CLASSIFICATION_LEVELS` definition in the new module.
3. **AD-685 + AD-685b coverage.** Pre-check now catches kwarg-name + method-name phantoms. Architect-discretion sweep is light.
4. **Privacy invariant.** Event payload must include `content_length` (NOT content); `blocked_phrases` must be names (NOT matched substrings). Verify by reading test cases — privacy regression would be catastrophic.
5. **Public-attribute discipline.** `runtime.classification_gate` — NO leading underscore.
6. **Pattern set false-positive risk.** 4 built-in patterns including `api_key_like` (32+ char alphanum). Verify the pattern wouldn't match common legitimate content (UUIDs, agent_ids, hashes). Architect risk-rates this; v1 acceptable if BLOCKED-by-default-when-uncertain stays out (gate is observational; caller decides).

Hard-stops per dispatch.

After review + sweep summary:
- Single commit: `Wave 19 review pass 1: AD-530 v1 reviewed, N findings (M Required)`
- Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-03)`. Run extended pre-check.

Single commit: `Wave 19 revision: apply review findings to AD-530 v1`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-19-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 19` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Standard Builder dispatch. Wave 19 specific reminders:

- v1 ships 2 of 4 capabilities ONLY (gate + pattern scanner).
- OBSERVATIONAL — gate returns DisclosureDecision; never mutates messages.
- DO NOT integrate into WardRoomService.create_post or LLMClient prompt builder (that's AD-530d).
- Reuse `_CLASSIFICATION_LEVELS` from records_store.py:27 (NOT duplicate).
- Privacy invariant: event payload has content_length (NOT content); blocked_phrases lists names (NOT substrings).
- Public attribute `runtime.classification_gate` (no underscore).
- Section 0: 1 new EventType (CLASSIFICATION_DISCLOSURE_BLOCKED).
- Test target: ~18 tests.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3 closes GH #104.**

```pwsh
gh issue close 104 --comment "AD-530 v1 closed in Wave 19 — see DECISIONS.md (ClassificationGate observational disclosure gate + pattern scanner + EventType shipped; Security Chief ownership / audit trail / active enforcement deferred to AD-530b/c/d)" --reason completed
```

Retrospective: optional. Heuristic — write only if AD-685b catches a phantom OR pattern-set false-positive rate surfaces a new convention.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-19.md and README-wave-19-pass-2.md
- 1 source commit (AD-530 v1)
- Full gate green; +18 tests
- 0 hard-stops
- GH issue #104 closed
- DECISIONS.md entry for AD-530 v1 under Era V
