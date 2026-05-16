# AD-729b — Boot Camp / Qualification training for peer observation conduct

**Status:** Draft for Wave 163
**Dependencies:** AD-729 ✅ (Wave 163, provides `CrewProfile.peer_perception.certified` field), AD-683 (existing Boot Camp framework), AD-595 (existing Qualification framework), AD-357 (Earned Agency rank tiers).
**Closes:** #589
**Estimated tests:** 8 pytest
**Build order:** FOURTH — AFTER AD-729 (needs the `certified` field). Can build in parallel with AD-729c.

## Scope discipline

Wave 163 ships the **mechanical gate** (CrewProfile flag, capability-surface check, retake flow, Boot Camp + Qualification integration hooks) plus the **module-scaffolding YAML** with placeholder content. The full case-study content from AD-729c monitoring data is deferred — placeholders are stable enough that AD-729c can add real cases later without schema churn.

## Section 0: Config

Extend `QualificationConfig` at `src/probos/config.py:3345` (canonical attach class for graduation/certification fields, verified by Architect grep). `BootCampConfig` at line 334 also exists but `QualificationConfig` is semantically more appropriate for graduation gates:

```python
# On QualificationConfig (src/probos/config.py:3345):
peer_observation_module_path: str = Field(
    default="config/manuals/peer_observation_conduct.yaml",
    description="AD-729b training module YAML path. Loaded at Boot Camp graduation gate.",
)
peer_observation_certification_required: bool = Field(
    default=False,
    description="AD-729b: when True, Boot Camp graduation blocks unless module passed. Default False — flips to True after AD-729a Standing Orders ship.",
)
```

**Verified (Architect grep):** `QualificationConfig` at `src/probos/config.py:3345` is the canonical attach class. `BootCampConfig` at `src/probos/config.py:334` is a sibling — do NOT use it for these fields.

## Section 1: Training module YAML scaffold

`config/manuals/peer_observation_conduct.yaml`:

```yaml
# AD-729b — Peer observation conduct training module
# Six sections per AD-729b issue body. Worked examples + scenarios + role-plays.
# Case-study section initially placeholder; populated from AD-729c monitoring corpus.

module:
  id: peer_observation_conduct
  version: 1
  required_for_ranks: [Lieutenant, LieutenantCommander, Commander, Captain]  # AD-357 Earned Agency floor
  sections:
    - id: theory
      reading_refs: ["AD-729a", "AD-489", "naval_speak_freely_primer.md"]
    - id: register_identification
      worked_examples: [...]  # 12 entries per AD-729b spec
    - id: phrasing_practice
      scenarios: [...]  # 6 entries
    - id: permission_protocol
      role_plays: [...]  # 3 entries
    - id: pattern_recognition
      case_studies: []  # populated from AD-729c corpus when available
    - id: final_assessment
      pass_threshold: 0.8
```

Scaffold with placeholder content marked `# TODO(AD-729a)` so it's clear which sections are content-deferred. The YAML SCHEMA is the deliverable; full content is a sub-AD.

## Section 2: Capability-gate integration

`observe_peer()` in `src/probos/avatars/peer_perception.py` already reads `CrewProfile.peer_perception.certified` (per AD-729 Section 3 Gate 3). AD-729b adds:

1. **Certification grading function.** `src/probos/cognitive/peer_observation_training.py:grade_module(agent_id, responses) -> bool`. Tier-2 honest-degrade: parse failures, malformed YAML → False (not certified). Pass/fail is deterministic from rubric, NOT LLM-graded in v1 (LLM grading is forward marker AD-729b-2).
2. **CrewProfile mutation API.** `set_peer_observation_certified(agent_id, value, *, reason)` — mirrors the AD-720d-2.1 `set_vision_capable` shape (per PROGRESS.md line 16). Atomic write, event-logged.
3. **New EventType `PEER_OBSERVATION_CERTIFIED`** and `PEER_OBSERVATION_CERTIFICATION_REVOKED` (the latter for the AD-729c second-tier intervention that clears the flag).

## Section 3: Boot Camp + Qualification integration hooks

In whichever module owns Boot Camp graduation (Builder verify: likely `src/probos/cognitive/bootcamp.py` or `src/probos/agents/bootcamp/*.py` — confirm by grep before editing):

- Add a graduation pre-check: if `BootCampConfig.peer_observation_certification_required=True`, the graduating agent must have `CrewProfile.peer_perception.certified=True`.
- On graduation failure for this reason, surface as a Tier-2 log-and-degrade ("Agent X cannot graduate Boot Camp until peer-observation module passed") — recoverable, not fatal.

For Qualification at Lieutenant tier (AD-357 floor), same gate.

## Section 4: Retake flow

Failure to pass is coachable. `grade_module()` returning False does NOT brick the agent — it leaves `certified=False`. Agent can retake by re-invoking the grading function with new responses. v1 retake is unrate-limited; AD-729c's three-tier intervention adds rate limiting at the second-tier intervention layer.

## Section 5: Tests (≥8 boundary cases)

`tests/test_ad729b_peer_observation_training.py`:

1. module YAML loads correctly, schema validated
2. grading rubric produces consistent pass for fixture answers above threshold
3. grading rubric produces consistent fail for fixture answers below threshold
4. Boot Camp blocks graduation when `peer_observation_certification_required=True` and agent uncertified
5. Boot Camp permits graduation when `peer_observation_certification_required=False` (default)
6. Qualification at Lieutenant tier blocks promotion when uncertified (and flag True)
7. `set_peer_observation_certified(agent_id, True, reason=...)` mutates CrewProfile atomically + emits event
8. certification persists across runtime restart (CrewProfile is already persisted; this verifies the new field is in the persisted shape)

Use **real `SystemConfig()` fixtures**; load the actual YAML scaffold from `config/manuals/peer_observation_conduct.yaml` (not a MagicMock'd dict).

## Section 6: Builder Standing Rules

- BF-274: single replace for adjacent edits.
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production.
- BF-287: real registry/profile fixtures.
- AD-738b: no UI in this AD (no `npm run build` gate).
- AD-731 invariant: n/a (no image flows).
- AD-722c-3: forward markers below use TECHNICAL triggers.

## What this does NOT change

- AD-729 governance contract — AD-729b only consumes the `certified` field already defined.
- The default value of `peer_observation_certification_required` — stays False until AD-729a Standing Orders ship.
- Existing Boot Camp / Qualification flows for non-peer-observation matters.
- The actual content of the training module (placeholder scaffolding only).

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #589.
- `docs/development/roadmap.md`: move AD-729b from forward markers; AD-729b-2 LLM-graded variant filed.
- `DECISIONS.md`: append AD-729b entry — mechanical gate + module schema; content deferred to AD-729a alignment.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-729b-2 — LLM-graded module.** Trigger: when AD-729b deterministic rubric has graded ≥10 officers AND grading consistency is verified. Issue filed.
- **AD-729b-flip — `peer_observation_certification_required` default True.** Trigger: when AD-729a Standing Orders ship AND AD-729b module content is complete (Counselor sign-off). Issue filed.

## Acceptance Criteria

1. All Section 0-4 deliverables landed.
2. ≥8 pytest tests pass.
3. Full gate green.
4. YAML scaffold parses; module loader produces a usable in-memory representation.
5. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "class BootCampConfig" src/probos/config.py
  (present — confirmed in config-class enumeration)

grep -n "set_vision_capable" src/probos/
  (AD-720d-2.1 — pattern reused for set_peer_observation_certified)
```

**Builder verify-first flags:**
- Exact `QualificationConfig` class name + module — VERIFY before Section 0 fields.
- Boot Camp graduation hook location — VERIFY before Section 3 integration.
- `CrewProfile` exact persistence shape — VERIFY (must already be persisted per AD-729 Section 2).
