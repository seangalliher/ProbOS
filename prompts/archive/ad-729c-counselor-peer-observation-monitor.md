# AD-729c — Counselor pattern-monitoring for peer observation conduct

**Status:** Draft for Wave 163
**Dependencies:** AD-729 ✅ (Wave 163, provides `PeerObservation` + RecordsStore artifact), AD-635 (bridge alert mechanism).
**Closes:** #590
**Estimated tests:** 14 pytest
**Build order:** FIFTH — AFTER AD-729. Can build in parallel with AD-729b.

## Scope discipline

Wave 163 ships seven `Protocol`-conformant pattern detectors + three-tier escalation wiring + aggregate health metrics on the EXISTING Counselor dashboard (no new dashboard). Captain's discretion at Tier-3 is the existing AD-635 bridge alert mechanism — AD-729c only emits, doesn't act.

## Section 0: Event Types

Add to `src/probos/events.py:EventType`:

```python
PEER_OBSERVATION_PATTERN_FLAGGED = "peer_observation_pattern_flagged"  # AD-729c: pattern detector hit
PEER_OBSERVATION_INTERVENTION_TIER_1 = "peer_observation_intervention_tier_1"  # private coaching
PEER_OBSERVATION_INTERVENTION_TIER_2 = "peer_observation_intervention_tier_2"  # recertification triggered
PEER_OBSERVATION_INTERVENTION_TIER_3 = "peer_observation_intervention_tier_3"  # bridge alert
```

Inserted after AD-722a-6's `CROSS_AGENT_DIVERGENCE_OBSERVED`.

## Section 1: Pattern detector Protocol

`src/probos/cognitive/peer_observation_monitor.py` (new module):

```python
class PeerObservationPatternDetector(Protocol):
    name: str

    def evaluate(
        self,
        observations: Sequence[PeerObservation],
        *,
        observer_id: str | None = None,
        observed_id: str | None = None,
        now: float,
    ) -> PatternFinding | None:
        ...


@dataclasses.dataclass(frozen=True)
class PatternFinding:
    detector: str
    subject_observer_id: str | None  # the officer the concern is about
    subject_observed_id: str | None  # the officer being observed (if relevant)
    severity: Literal["info", "warn", "critical"]
    evidence: dict[str, Any]  # detector-specific structured evidence
```

## Section 2: Seven detectors (one per pattern from issue body)

Each detector is its own class implementing the Protocol. Individually testable.

1. `FrequencyDriftDetector` — observer's per-peer observation rate significantly exceeds her overall rate.
2. `RegisterDriftDetector` — OPERATIONAL register observations whose phrasing crosses into evaluative language (regex-based; the same kind of phrasing check AD-727 rule #8 uses, but evaluative-not-renderer).
3. `CascadeSignalDetector` — multiple officers observe the same peer in rapid succession without prior independent-observation history.
4. `StaticImpressionDetector` — an observer's impressions of a peer that don't update over time despite the peer's measurable state changing (AD-722e self-perception data is the state baseline).
5. `PermissionDenialPatternDetector` — observer repeatedly requests permission from a peer who denies.
6. `SycophancyPatternDetector` — concentration of disproportionately positive observations of high-trust officers from low-trust officers (uses trust READ-ONLY — never writes).
7. `PrivilegedTierLeakageDetector` — observations that surface clinical/security signals into channels lacking clearance.

Each detector returns `PatternFinding | None`. Composition is the responsibility of the orchestrator.

## Section 3: Orchestrator (sampling Counselor service)

`PeerObservationMonitor` class wraps the seven detectors. Driven by a fixed 60-second interval timer (hardcoded constant `_MONITOR_INTERVAL_SECONDS = 60` at module top). The 60s value is pinned pending forward marker **AD-729c-1** (config field on `ClinicalTelemetryConfig` at `src/probos/config.py:3134`, deferred until first operator feedback). Do NOT introduce a config field in this AD — keep the constant in-module with a `# AD-729c-1: forward marker` comment.

On each tick:
1. Reads recent PeerObservations from RecordsStore (window = max impression-decay window across detectors).
2. Runs each detector.
3. For each finding, runs three-tier escalation logic (Section 4).
4. Updates aggregate health metrics on the existing Counselor health dashboard surface (Builder verify: locate the existing Counselor dashboard data source — likely `src/probos/cognitive/counselor.py` health-snapshot method).

## Section 4: Three-tier escalation

State machine per `(detector, observer_id)` pair:

- **Tier 1** (first finding): emit `PEER_OBSERVATION_INTERVENTION_TIER_1` event. Counselor sends a private message via the existing 1:1 channel (verify: `CounselorAgent` 1:1 message API). Coaching tone — descriptive of the pattern, suggests action.
- **Tier 2** (finding persists across two sampling intervals): emit `_TIER_2` event. Call `set_peer_observation_certified(observer_id, False, reason="AD-729c tier-2 intervention")`. AD-729b retake required.
- **Tier 3** (finding persists post-recertification): emit `_TIER_3` event. Surface to bridge via existing AD-635 bridge alert mechanism (verify the exact alert API — issue body claims it exists).

State persists across runtime restarts via a sidecar JSON file `<data_dir>/peer_observation_intervention_state.json` (mirrors AD-720d-2.1 atomic-write pattern).

## Section 5: Aggregate health metrics

Metrics surfaced on the existing Counselor health dashboard:

- Total observations per channel / register / period.
- Permission-request-to-grant ratio.
- Per-pair observation distribution skewness.
- Time-since-impression-update distribution.

Privacy preserving — individual observation IDs are NOT surfaced unless the Counselor is actively investigating a flagged pattern (i.e., a `PatternFinding` exists).

## Section 6: Counselor's own conduct constraint

Source-scan regression test: `peer_observation_monitor.py` and the changes to `counselor.py` MUST NOT contain any code that makes a PeerObservation OF a crew member from the Counselor's own observer_id outside her clinical role. AD-729a Section 3 violation (privileged-tier leakage — clinical → non-clinical). Easiest enforcement: the orchestrator NEVER calls `observe_peer()` itself; it only consumes pre-existing observations from RecordsStore.

## Section 7: Tests (≥14 boundary cases)

`tests/test_ad729c_peer_observation_monitor.py`:

1-7. Each detector: positive case (pattern present → PatternFinding) + negative case (pattern absent → None). 14 cases minimum just from detectors. (Actually 7 positive + 7 negative = 14; the issue body says ≥14 — this exactly hits the floor.)
8. Three-tier escalation: Tier 1 happy path (first finding → private message + event).
9. Three-tier escalation: Tier 2 trigger after persistence → certification revoked.
10. Three-tier escalation: Tier 3 trigger after persistence post-recert → AD-635 bridge alert emitted.
11. Aggregate metrics correctness: known fixture → known aggregate values.
12. Sampling rate honored: monitor runs at the fixed 60s cadence (`_MONITOR_INTERVAL_SECONDS`), not more frequently.
13. Integration with existing Counselor service is read-only (source-scan: monitor module has no `trust_network.record_outcome` calls).
14. Counselor's-own-conduct constraint: source-scan confirms monitor never calls `observe_peer()` from Counselor's observer_id.

Plus boundary cases for full coverage:
15. Intervention state survives runtime restart (sidecar reload).
16. Aggregate metrics privacy: when no PatternFinding exists, individual observation IDs are NOT exposed in the dashboard payload.

Use **real `SystemConfig()` fixtures** + **real `AgentRegistry`** + **real RecordsStore fixture** (in-memory variant if needed) — BF-287 retrospective.

## Section 8: Builder Standing Rules

- BF-274: single replace for adjacent edits.
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production.
- BF-287: real registry/profile/records-store fixtures.
- AD-738b: no UI in this AD (no `npm run build` gate). The Counselor health dashboard is a backend snapshot; UI consumption is existing.
- AD-731 invariant: n/a (no image flows in this AD).
- AD-722c-3: forward markers below use TECHNICAL triggers.

## What this does NOT change

- AD-729 governance contract.
- AD-504 cognitive-zone monitoring semantics (this AD does not bind to AD-504 cadence; it runs at a fixed 60s interval pending AD-729c-1).
- AD-552 peer repetition credits.
- AD-635 bridge alert mechanism — only consumed, never modified.
- The Counselor's clinical role — Counselor still bypasses peer-perception entirely in clinical channels.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #590.
- `docs/development/roadmap.md`: move AD-729c from forward markers.
- `DECISIONS.md`: append AD-729c entry — pattern monitoring + three-tier escalation.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-729c-1 — Sampling interval as ClinicalTelemetryConfig field.** Trigger: first operator request to tune the 60s cadence, OR first production data showing the rate is wrong. Forward marker.
- **AD-729c-2 — LLM-assisted phrasing-drift detection.** Trigger: when regex-based `RegisterDriftDetector` produces ≥20 findings with manual review confirming ≥80% precision. Issue filed.
- **AD-729c-3 — Cross-mesh pattern detection.** Trigger: when federation peer-observation arrives via AD-480 review path. Issue filed.

## Acceptance Criteria

1. All Section 1-6 deliverables landed.
2. ≥14 pytest tests pass (target 16 with the extras).
3. Full gate green.
4. Source-scan tests (Test 13, 14) explicitly verify Counselor-own-conduct + trust-read-only.
5. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "class CounselorAgent" src/probos/cognitive/counselor.py
  (present — verified by mediate_appearance_revision at counselor.py:489)
```

**Builder verify-first flags:**
- AD-729c-1 sampling-interval config field — DEFERRED forward marker. This AD hardcodes 60s via `_MONITOR_INTERVAL_SECONDS`; do NOT add a config field.
- AD-635 bridge alert API — VERIFY signature before Section 4 Tier 3 wiring.
- Counselor 1:1 message channel API — VERIFY before Section 4 Tier 1.
- Counselor health dashboard data source — VERIFY before Section 5.
