# AD-729 — Peer avatar perception governed by Code of Conduct (umbrella + primitives)

**Status:** Draft for Wave 163
**Dependencies:** AD-728 ✅ (Wave 163, must ship first), AD-722e-2 ✅, AD-722a-1 ✅, AD-731 invariant, AD-727 safety inheritance.
**Closes:** #587
**Estimated tests:** 18 pytest
**Build order:** SECOND — AFTER AD-728. Defines the governance contract; AD-722a-6 / AD-729b/c/d build on top.

## Scope discipline — what Wave 163 ships under AD-729

The umbrella issue #587 requires AD-729a Standing Orders, AD-729b Training, and AD-729c Counselor monitoring to ship before the **full** `observe_peer()` capability advances. Wave 163 does NOT include AD-729a in scope. Therefore:

- **In scope (Wave 163 AD-729):** the governance contract — two-register DSL, `PeerObservation` dataclass, four mechanical constraints as code, `CrewProfile.peer_perception` field, capability surface stub gated on AD-729a + AD-729b certification, RecordsStore artifact type, federation gate. The plumbing.
- **Deferred to AD-729a (separate future AD, NOT in Wave 163):** the actual Standing Orders content authored under `config/standing_orders/`. The capability stays DEFAULT-OFF until AD-729a ships AND AD-729b certification has graded at least one officer.

This is the architect call: Wave 163 ships the contract + mechanical floor; the conduct content layer ships separately. The user prompt confirms cluster sequencing AD-728 → AD-729 → AD-722a-6 → AD-729b/c/d, which matches this scope split (AD-729b/c/d build on the contract that AD-729 establishes, while AD-729a is its own filing).

## Section 0: Event Types

Add to `src/probos/events.py:EventType`:

```python
PEER_OBSERVATION_RECORDED = "peer_observation_recorded"  # AD-729: peer avatar perception
PEER_OBSERVATION_DECLINED = "peer_observation_declined"  # AD-729: capability gate / opt-out denial
PEER_OBSERVATION_PERMISSION_REQUESTED = "peer_observation_permission_requested"  # AD-729: speak-freely protocol
PEER_OBSERVATION_PERMISSION_GRANTED = "peer_observation_permission_granted"  # AD-729: speak-freely protocol
PEER_OBSERVATION_PERMISSION_DENIED = "peer_observation_permission_denied"  # AD-729: speak-freely protocol
```

All five inserted directly after `RENDER_DIVERGENCE_OBSERVED` (AD-728).

## Section 1: Two-register observation DSL

`src/probos/avatars/peer_perception.py` (new module):

```python
class ObservationRegister(str, Enum):
    OPERATIONAL = "operational"
    PERSONAL = "personal"


@dataclasses.dataclass(frozen=True)
class PeerObservation:
    observer_id: str
    observed_id: str
    register: ObservationRegister
    content: str
    timestamp: float
    decay_after: float  # epoch seconds; impressions fade after this
    permission_grant_id: str | None  # required for PERSONAL register; None for OPERATIONAL
```

Register is enforced at the DSL boundary: PERSONAL observations require a non-None `permission_grant_id` referencing a prior `PEER_OBSERVATION_PERMISSION_GRANTED` event. Content phrasing is NOT enforced here — that's the AD-729a Standing Orders + AD-729c Counselor monitoring job.

## Section 2: Four mechanical constraints (code-enforced)

1. **Trust/Hebbian read-only.** Source-scan regression test: `peer_perception.py` must not import `trust_network`, `hebbian`, or `routing.update_weight`. Verified by test.
2. **Privacy opt-out.** New `CrewProfile.peer_perception` Pydantic sub-model:
   ```python
   class PeerPerceptionProfile(BaseModel):
       enabled: bool = Field(default=True, description="Default True for crew agents; default False at AgentDesigner spawn for utility/system tiers.")
       certified: bool = Field(default=False, description="AD-729b qualification flag; capability gated on True.")
   ```
   Default-True/False split happens at the AgentDesigner / spawner level — utility and system tiers spawn with `enabled=False`. Crew agents spawn with `enabled=True, certified=False`.
3. **Backend render only.** `observe_peer()` MUST verify the analog source is the backend render path, not browser capture. Mirrors the AD-727 rule #5 check used by `verify_render_coherence`. If unavailable → honest-degrade with `skipped_reason="backend_render_unavailable"`.
4. **Cross-federation gate.** When `observed_id` belongs to a peer mesh (federation registry lookup), the call routes through the existing federation governance review path (AD-480 framework). v1 honest-degrades with `skipped_reason="federation_review_required"` — actual review wiring is a separate AD.

## Section 3: Capability surface (gated stub)

```python
def observe_peer(
    runtime: ProbOSRuntime,
    observer_id: str,
    observed_id: str,
    register: ObservationRegister,
    content: str,
    *,
    permission_grant_id: str | None = None,
) -> PeerObservation | None:
    """Returns PeerObservation on happy path; None on honest-degrade.

    Hard gates (in order):
      1. cfg.avatars.peer_perception_enabled (default False).
      2. observer's CrewProfile.peer_perception.enabled (default True for crew, False else).
      3. observer's CrewProfile.peer_perception.certified (AD-729b gate; default False).
      4. observed's CrewProfile.peer_perception.enabled (opt-out check).
      5. register == PERSONAL → permission_grant_id required and verifiable.
      6. backend render path available.
      7. federation gate (same-mesh only).
      8. rate limit: 1 observation per (observer, observed) pair per WR thread (existing thread storage).
    """
```

Each gate emits the appropriate `PEER_OBSERVATION_DECLINED` event with a structured reason code.

## Section 4: Config

Extend `AvatarsConfig`:

```python
peer_perception_enabled: bool = Field(
    default=False,
    description="AD-729 peer avatar perception capability. Default OFF until AD-729a Standing Orders ship and AD-729b certification grades at least one officer.",
)
peer_observation_decay_seconds: int = Field(
    default=86400 * 7,
    ge=3600,
    description="AD-729 impression decay window. Observations older than this are filtered from composite impressions.",
)
peer_observation_max_per_pair_per_thread: int = Field(
    default=1,
    ge=0,
    description="AD-729 mechanical floor — max observations per (observer, observed) pair per WR thread. 0 disables capability.",
)
```

## Section 5: RecordsStore artifact

Peer observations persist via `RecordsStore` at `src/probos/knowledge/records_store.py:47` (verified by Architect grep). New artifact type `peer_observation` with fields mirroring `PeerObservation`. Not anonymized — officers accountable for their observations (Captain ruling).

**Builder verify-first:** `grep -n "class.*Store" src/probos/knowledge/store.py` and confirm the exact API. If the records-store surface doesn't expose a clean `add(artifact_type=..., payload=...)` shape, surface as a hard-stop pre-flight finding before implementation.

## Section 6: Composite impressions surface

Composite impressions are returned through the existing AD-722e self-perception channel — they are NOT a separate stream. Hook point: `src/probos/cognitive/self_perception.py`. v1 adds a single optional clause to the self-perception assembly: "Crew impressions of you over the last 24h: ..." rendered ONLY when `peer_perception_enabled=True` AND the observed agent has `peer_perception.enabled=True` AND at least one undecayed observation exists.

## Section 7: Permission protocol (speak-freely)

PERSONAL register requires `permission_grant_id`. The grant flow is:

1. Observer emits `PEER_OBSERVATION_PERMISSION_REQUESTED` targeting the observed agent.
2. Observed agent's runtime hook decides grant/deny (default policy: deny silently if no explicit listener registered — opt-in, not opt-out).
3. On grant: `PEER_OBSERVATION_PERMISSION_GRANTED` emitted with a fresh `grant_id` valid for one observation within 5 minutes.
4. On deny or timeout: `PEER_OBSERVATION_PERMISSION_DENIED` emitted; no observation recorded.

v1 default listener: deny-silent. AD-729b certified officers eventually gain a real-decision listener (out of scope).

## Section 8: Tests (≥18 boundary cases)

`tests/test_ad729_peer_perception.py`:

1. operational register happy path
2. personal register without permission_grant_id → declined
3. personal register with valid permission_grant_id → recorded
4. expired permission_grant_id (>5 min) → declined
5. observed agent opt-out → declined
6. observer uncertified (default `certified=False`) → declined
7. `peer_perception_enabled=False` global flag → declined
8. utility-tier observer (default `enabled=False`) → declined
9. cross-federation observed → declined with `federation_review_required`
10. backend render unavailable → declined
11. per-pair-per-thread rate limit (1) hit → second call declined
12. trust isolation source-scan: `peer_perception.py` has zero `trust_network`/`hebbian`/`routing` imports
13. observation persists to RecordsStore artifact correctly
14. composite impression in AD-722e self-perception renders ONLY when undecayed observations exist
15. impression decay: observation older than `peer_observation_decay_seconds` filtered out
16. permission flow: REQUESTED → GRANTED → recorded chain
17. permission flow: REQUESTED → DENIED → no observation
18. AD-731 invariant: PEER_OBSERVATION_* event payloads carry no inline image bytes (peer observations are textual; verify no accidental image coupling)

Use **real `SystemConfig()` fixtures**. Use a **real `AgentRegistry`** fixture, not `MagicMock()` — BF-287 retrospective.

## Section 9: Builder Standing Rules

- BF-274: single `replace_string_in_file` for adjacent edits.
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production.
- BF-287: real registry fixture (`AgentRegistry`), not MagicMock. Public registry API only.
- AD-738b: no UI in this AD; no `npm run build` gate.
- AD-731 invariant: verified by Test 18.
- AD-722c-3: forward markers below use TECHNICAL triggers.

## What this does NOT change

- AD-728 mirror function semantics.
- AD-722a-1 / AD-722e-2 callsites.
- Trust / Hebbian / routing — peer observations are read-only with respect to all three.
- Existing CrewProfile fields outside the new `peer_perception` sub-model.
- The Standing Orders content (AD-729a, deferred).
- Captain-initiated peer observation paths (Captain commands transit existing channels; not subject to peer-perception register rules).

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #587.
- `docs/development/roadmap.md`: move AD-729 from forward markers; AD-729a explicitly listed as the next-required sub-AD.
- `DECISIONS.md`: append AD-729 entry — governance contract umbrella.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-729a — Standing Orders content.** Trigger: when Wave 163 ships AD-729 + AD-729b + AD-729c AND the Counselor has reviewed at least one quarter of operational AD-722e-2 + AD-722a-1 data showing baseline self-presentation stability. Issue stays OPEN.
- **AD-729-capability-flip — default-ON for crew.** Trigger: when AD-729a ships AND ≥3 officers have passed AD-729b certification. Issue filed.

## Acceptance Criteria

1. All Section 0-7 deliverables landed.
2. ≥18 pytest tests pass.
3. Full gate green.
4. `peer_perception_enabled` confirmed default False across all `system.yaml` defaults.
5. AD-727 trust-isolation source-scan (Test 12) explicitly verified.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "VISION_INTENT_DIVERGENCE_OBSERVED" src/probos/events.py
  204 (insertion anchor for new EventType values)

grep -n "class AvatarsConfig" src/probos/config.py
  (present)

grep -n "class CrewProfile" src/probos/
  Builder MUST verify the exact module path before adding peer_perception sub-model.

grep -n "class RecordsStore" src/probos/knowledge/records_store.py
  47: class RecordsStore  (verified — canonical class at src/probos/knowledge/records_store.py:47)
```

**Phantom-check flags for Builder:**
- `RecordsStore`: VERIFIED — `src/probos/knowledge/records_store.py:47`. Use as-is.
- `CrewProfile` exact module/class: VERIFY before Section 2 (pydantic sub-model attach point).
- AD-480 federation review path: VERIFY exists before Section 2 constraint #4 (honest-degrade fallback is the safe default if not).
