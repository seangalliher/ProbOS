# AD-728 — Vision-LLM mirror function (digital-analog render coherence)

**Status:** Draft for Wave 163
**Dependencies:** AD-722a-1 ✅ (Wave 162, ships `VisionLLMRateLimit` + `is_render_phrased()`), AD-722e-2 ✅ (Wave 162, ships `SelfRenderVerifier` pattern), AD-731 (image-bytes-as-refs invariant), AD-727 safety inheritance.
**Closes:** #586
**Estimated tests:** 12 pytest
**Build order:** PRIMITIVE — build FIRST in Wave 163; AD-722a-6 + AD-729 family consume the output shape.

## Problem

ProbOS has two parallel agent representations: the digital `AvatarDSL` (source of truth) and the analog backend-rendered image. They are supposed to be in sync but drift silently. Today nobody knows when the renderer diverges from the digital model. AD-722e-2 already verifies self-render coherence at the agent's own perception layer; AD-728 generalizes that into a **trigger-driven mirror function** with a third trigger (Captain on-demand) plus a new alert payload type with phrasing-rule enforcement.

## Solution overview

A new module `src/probos/avatars/render_verification.py` exposes `verify_render_coherence(agent_id, trigger) -> RenderCoherenceResult`. It REUSES AD-722a-1's `VisionLLMRateLimit` (new scope key `render_verification`) and `is_render_phrased()` AD-727 rule #8 phrasing helper — both already exported from `src/probos/avatars/vision_intent_divergence.py`. New `EventType.RENDER_DIVERGENCE_OBSERVED`. Default-OFF flag `AvatarsConfig.render_verification_enabled`. Per-agent hourly cap aligned with AD-728 ceiling already in `AvatarsConfig`.

NOT BUILT in this AD: the backend render pipeline itself (AD-721i territory). When `AvatarsConfig.backend_render_enabled` is False, the function honest-degrades with `coherent=None, skipped_reason="backend_render_unavailable"` — never raises.

## Section 0: Event Types

Add to `src/probos/events.py:EventType`:

```python
RENDER_DIVERGENCE_OBSERVED = "render_divergence_observed"  # AD-728: vision-LLM render coherence mirror
```

Inserted directly after `VISION_INTENT_DIVERGENCE_OBSERVED` (the AD-722a-1 line). The event payload is the **renderer**, not the agent — see Hard Rule 8 below.

## Section 1: Config

Extend `AvatarsConfig` (`src/probos/config.py`):

```python
render_verification_enabled: bool = Field(
    default=False,
    description="AD-728 vision-LLM render-coherence mirror. Default OFF until AD-721i backend renderer is stable.",
)
render_verification_max_per_hour_per_agent: int = Field(
    default=3,
    ge=0,
    description="AD-728 per-agent hourly cap for render-verification vision calls. 0 disables.",
)
```

No new top-level config class. `BridgeAlertsConfig` does NOT exist (verify-first pass: there's no such class in `config.py`); render-divergence severity is conveyed via the `EventType.RENDER_DIVERGENCE_OBSERVED` payload's `severity` field, not a separate config registration.

## Section 2: `RenderCoherenceResult` dataclass

`src/probos/avatars/render_verification.py`:

```python
@dataclasses.dataclass(frozen=True)
class RenderCoherenceResult:
    agent_id: str
    trigger: str  # "captain_command" | "divergence_followup" | "agent_initiated_stub"
    coherent: bool | None  # None on honest-degrade
    digital_description: str
    analog_description: str | None
    divergence_summary: str | None
    skipped_reason: str | None
    timestamp: float
```

## Section 3: `verify_render_coherence` function

Module-level function (NOT a class — mirrors AD-722e-2's `SelfRenderVerifier.verify` shape but for cross-trigger callers):

- Reads `cfg.avatars.render_verification_enabled`; if False → honest-degrade with `skipped_reason="disabled"`.
- Builds digital description via the SAME AD-722e projection helper used by `SelfRenderVerifier` (import, do not reimplement).
- Resolves the backend-rendered image ref via the existing AD-721i backend-render API. If the API is absent → `skipped_reason="backend_render_unavailable"`.
- Acquires `VisionLLMRateLimit` slot under scope `render_verification`, agent-keyed. If exhausted → `skipped_reason="rate_limited"`.
- Resolves the image SHA-256 ref through `AttachmentStore` and builds multimodal messages via the existing `build_multimodal_messages` helper. **AD-731 invariant: never inline base64 in the IntentMessage; bytes flow through AttachmentStore.**
- Calls `runtime.llm_client.complete(LLMRequest(tier="vision", ...))`. Honest-degrade on every exception.
- Validates the vision LLM output through `is_render_phrased()`. If the output is NOT renderer-phrased (says "Ezri looks tired" instead of "Render output for Ezri shows..."), re-prompt once with the AD-727 rule #8 phrasing constraint repeated; if still not renderer-phrased, drop the analog description (`analog_description=None`) and set `skipped_reason="phrasing_rejected"`.
- Compares digital vs analog (simple string compare baseline; richer scoring deferred to forward marker AD-728a).
- Emits `EventType.RENDER_DIVERGENCE_OBSERVED` only when `coherent is False`. Coherent observations are NOT logged (cost discipline).

## Section 4: Trigger surfaces

Wire three triggers:

1. **Captain command** — new slash command in `experience/shell.py` `/verify-render <agent_id>`. Calls `verify_render_coherence(agent_id, trigger="captain_command")`. Surfaces result through the standard Rich panel.
2. **AD-722a divergence-followup** — `VisionIntentDivergenceDetector` gains an OPTIONAL post-hook that, on detected divergence and when `cfg.avatars.render_verification_followup_enabled=True` (default False), invokes the mirror with `trigger="divergence_followup"`. Rate limit shared so a single suspicious moment can cost at most 2 vision calls (intent-detector + mirror).
3. **Agent-initiated stub** — `trigger="agent_initiated_stub"` accepted but hard-rejected with `skipped_reason="agent_initiated_disabled"`. Acceptance criteria: the path exists so future ADs flip a config flag.

## Section 5: Hard Rule 8 — phrasing semantics

Mirror outputs surface the RENDERER as subject of any divergence diagnostic, NEVER the agent. The phrasing test is:

```python
def test_render_divergence_phrasing_is_renderer_subject():
    """The RENDER_DIVERGENCE_OBSERVED event payload's `divergence_summary`
    field must read as a renderer-subject statement, not an agent-subject
    statement. Verified by `is_render_phrased()` (AD-727 rule #8)."""
```

Examples:
- ✅ "Render output for Ezri differs from her digital state"
- ❌ "Ezri looks different than she should"

## Section 6: Tests (≥12 boundary cases)

`tests/test_ad728_render_verification.py`:

1. coherent case (digital + analog descriptions match)
2. divergent case (descriptions differ → `RENDER_DIVERGENCE_OBSERVED` emitted)
3. `render_verification_enabled=False` → honest-degrade
4. backend renderer unavailable → honest-degrade (`skipped_reason="backend_render_unavailable"`)
5. vision-LLM failure → honest-degrade
6. rate-limit exceeded → honest-degrade
7. each trigger path: captain_command happy, divergence_followup happy, agent_initiated_stub rejected
8. `RENDER_DIVERGENCE_OBSERVED` payload integrity (renderer-subject, agent_id, trigger, timestamps)
9. phrasing rejection: vision LLM says "Ezri looks tired" → analog_description dropped, `skipped_reason="phrasing_rejected"`
10. AD-731 invariant test: assert IntentMessage.params NEVER contains inline base64 image bytes
11. trust-isolation test (source-scan regression): grep `render_verification.py` for `trust_network` / `hebbian` → must be empty (AD-727 rule #1)
12. coherent observations are NOT logged (cost discipline)

Use **real `SystemConfig()` fixtures** at the config boundary — no MagicMock at config edges (BF-287 retrospective).

## Section 7: Builder Standing Rules

- BF-274: use single `replace_string_in_file` calls for adjacent edits. NO `multi_replace_string_in_file` for adjacent SEARCH blocks.
- BF-280: NO `asyncio.create_subprocess_*` in runtime paths. None expected here (no subprocess calls).
- BF-282: NO binary stdout capture on Windows. None expected here.
- BF-286: any new test scaffolding mirrors production subprocess shape (n/a here).
- BF-287: use public registry API (`registry.all()` / `registry.get(...)`), NOT `registry.agents`.
- AD-738b: no UI surface in this AD, so no `npm run build` gate. Confirmed.
- AD-731 invariant: image bytes flow through `AttachmentStore` SHA-256 refs. Verified by Test 10.
- Real Pydantic config fixtures in tests (NOT MagicMock at the config boundary).
- AD-722c-3: any forward marker filed by this prompt uses TECHNICAL triggers (e.g. "when AD-721i backend renderer ships and `cfg.avatars.backend_render_enabled` defaults True").

## What this does NOT change

- AD-722a-1 / AD-722e-2 callsite wiring (those still ship default-OFF in their existing files).
- `VisionLLMRateLimit` semantics — AD-728 ONLY adds a new scope key; the rate-limit class itself is untouched.
- `is_render_phrased()` regex — reused as-is.
- The backend render pipeline (AD-721i forward marker, out of scope).
- Auto-correction of render divergence (future AD).

## Tracking

- `PROGRESS.md`: add CLOSED entry under Wave 163 referencing #586.
- `docs/development/roadmap.md`: move AD-728 from forward markers to shipped.
- `DECISIONS.md`: append AD-728 entry — primitive, gating contract for AD-722a-6 / AD-729 / future render hygiene.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-728a — Richer coherence scoring.** Trigger: when `RENDER_DIVERGENCE_OBSERVED` event volume exceeds 50 events/quarter, replace string-compare with embedding-distance scoring. Issue filed.
- **AD-728b — Auto-correction proposals.** Trigger: when AD-728a embedding scoring is stable AND the renderer drift pattern catalog has ≥10 distinct categorized causes. Issue filed.

## Acceptance Criteria

1. All Section 1-5 deliverables landed.
2. ≥12 pytest tests pass (`pytest tests/test_ad728_render_verification.py -v -n 0`).
3. Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
4. AD-731 invariant test (Test 10) explicitly asserts no inline image bytes in `IntentMessage.params`.
5. AD-727 trust-isolation test (Test 11) source-scans `render_verification.py` for `trust_network`/`hebbian` — must be empty.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "VISION_INTENT_DIVERGENCE_OBSERVED" src/probos/events.py
  204: VISION_INTENT_DIVERGENCE_OBSERVED = "vision_intent_divergence_observed"  # AD-722a-1

grep -n "class AvatarsConfig" src/probos/config.py
  (present — confirmed in config-class enumeration)

grep -n "VisionLLMRateLimit\|is_render_phrased" src/probos/avatars/vision_intent_divergence.py
  (both exported per AD-722a-1 PROGRESS.md entry)

grep -n "SelfRenderVerifier" src/probos/cognitive/self_render_verify.py
  (AD-722e-2 ships this — reuse digital-projection helper)
```

**Phantom check:** `BridgeAlertsConfig` referenced in the original issue body does NOT exist in `src/probos/config.py`. This prompt drops that reference and uses `EventType.RENDER_DIVERGENCE_OBSERVED` payload's `severity` field instead. Builder MUST NOT introduce a new config class for this.
