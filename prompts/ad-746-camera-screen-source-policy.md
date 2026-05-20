# AD-746 — Camera + screen source policy (layered fusion + per-agent binding)

**Status:** drafted (Wave 180, builds **third**; runs after BF-317 + BF-318).
**Issue:** [#682](https://github.com/seangalliher/ProbOS/issues/682).
**Prior-art:** `prompts/RESEARCH-issues-2026-05-19.md` (Issue B —
Pipecat `VisionAggregator` pattern absorbed BSD-2-Clause; LiveKit
`MultiModalContext` pattern absorbed Apache 2.0; Anthropic /
ChatGPT / Operator validate per-agent binding).
**Estimated work:** 1 day.
**Dependencies:** AD-733-2 (screen sensing, shipped Wave 178);
AD-733a (`VisionConsumer`, shipped Wave 171); AD-742c (per-agent
camera binding, shipped Wave 176) — extends but does not break any.
**License posture:** zero new pip / npm deps; pure pattern absorption
from BSD-2-Clause + Apache 2.0 references. **0-line diff on all 5
license files.**

---

## Problem

After AD-733a (camera) and AD-733-2 (screen) shipped, both sources
emit `vision_observation` intents with `params.source ∈ {camera,
screen}`. Both flow into the **same** `VisionConsumer._handle`
(`src/probos/perception/consumer.py:307`). Captain reported the two
sources "fight for attention" — measured symptoms:

1. **Budget burn doubles.** AD-733c-6 engaged-mode vision-call cap
   counts BOTH sources' calls against the same per-session ceiling
   (default 200). With both active, the cap hits in half the time.
2. **WM incoherence.** Each agent's `VisionWorkingMemory` ring
   buffer (capacity 8) interleaves camera frames and screen frames;
   the agent's prompt context becomes a confused mix
   (`render_for_prompt` block at `working_memory.py`).
3. **Episodic noise.** AD-541b anchors fire twice per real-world
   event (once per source).

## Solution overview (v1 = Layer 1 + Layer 2)

Per RESEARCH recommendation: ship **Option B (fusion) + Option C
(per-agent binding) as a layered solution. Defer Option A (raw
priority knob) as forward marker AD-746-1.**

### Layer 1 — `VisionAggregator` (Pipecat-style fusion)

A new module inserted between the source admitters (camera + screen
upload endpoints) and the existing `VisionConsumer`. Default
behavior preserved when only one source is active (passthrough).

- New class `VisionAggregator` in
  `src/probos/perception/aggregator.py`.
- Subscribes to `vision_observation` intent BEFORE `VisionConsumer`.
- Per-session, when a frame arrives, opens an 800 ms (configurable)
  debounce window. If a frame from the OTHER source arrives within
  the window, the two are fused into a single composite intent
  message: `params.attachment_refs: list[str]` (list of the two SHAs)
  + `params.sources: list[str]` (`["camera", "screen"]`), the legacy
  `params.attachment_ref` field set to the **primary** (defined as
  whichever frame arrived first), and `params.fused: True`.
- If the window expires with only one frame, the frame is passed
  through unchanged (legacy single-source contract preserved).
- AD-731 invariant: refs only; the aggregator never inlines bytes.
- AD-733c-6 budget: a fused multimodal call counts as **one** vision-
  tier call, not two.

### Layer 2 — Per-agent `bound_sources`

Extend `CrewProfile.perception.camera_device_id` shape (AD-742c) with
a new `bound_sources: list[Literal["camera", "screen"]]` field.

- Default value: `["camera", "screen"]` (back-compat: existing
  agents see both, identical to today's behavior).
- `VisionConsumer._handle` early branch (extending the AD-742c
  `bound_agent_ids` filter at `consumer.py:~430`): when the
  observation's `params.source` (or `params.sources` for fused
  frames) does NOT intersect the active agent's `bound_sources`,
  the frame is dropped for THAT agent's WM and episodic anchor.
- For fused frames, the agent sees the frame if AT LEAST ONE of
  the fused sources is in their `bound_sources` (operator intent:
  "Counselor binds to camera" should still observe a fused
  camera+screen tick because the camera half is relevant).

### Configuration

Two new fields on `PerceptionConfig`
(`src/probos/config.py:2099`):
- `source_fusion_enabled: bool = True` (Layer 1 master switch;
  hot-reload).
- `fusion_window_ms: int = 800` (Pipecat default; hot-reload, ge=100
  le=5000).

One new field on `PerceptionProfile`
(`src/probos/crew_profile.py:330`):
- `bound_sources: list[str] = field(default_factory=lambda:
  ["camera", "screen"])` (Layer 2). `from_dict` defaults to both
  sources when the key is absent (back-compat).

Both layers default-ON in v1: Layer 1 is opt-out via the master
switch (the symptom budget-burn was material in production);
Layer 2 defaults to ALL sources per agent (back-compat). Operator
binding via new API surface.

### API surface

New routes in `src/probos/routers/perception.py`:
- `GET /api/perception/sources` — returns `{bindings: {agent_id:
  list[str]}}` mirror of AD-742c camera-binding shape.
- `POST /api/perception/sources/binding` — `{agent_id, sources:
  list[str]}`; validates each source ∈ `_VALID_SOURCES`
  (already a `frozenset({"camera", "screen"})` at line 128); 404
  on unknown agent (mirrors AD-742c); persists via
  `ProfileStore.update`.

Both behind `require_crew_scope`. AD-731 source-scan extends to
`aggregator.py` (no `b64encode` / `base64.b64`).

### HXI surface

Extend `PerceptionLivePanel.tsx` CAMERA BINDINGS section (AD-742c-6)
into SOURCE BINDINGS:
- Per-agent row gains a second column of stroke-SVG check pills
  (`CAMERA` / `SCREEN`) toggleable independently. Amber
  `#f0b060` when bound, dim `#666680` when unbound (HXI #3).
- `usePerceptionSourcesStore` Zustand sibling slice
  (`useSourceBindingsStore`) tracks the GET response + POST
  setter. SRP wins per AD-742c-6 precedent (NOT merged into
  `useCameraMultiplexerStore`).

### Episodic anchor

The AD-541b anchor written by `VisionConsumer` extends its existing
metadata block with `sources: list[str]` (was `source: str`).
Single-source frames record `["camera"]` or `["screen"]`;
fused frames record both. The legacy `source` field stays for one
release as a forward-compat alias (writes the first element of
`sources`); forward marker AD-746-5 retires it after one wave of
no-regression observation.

## Non-scope (v1)

- NO Option A raw priority knob (forward marker **AD-746-1**).
  Pre-empting fusion when one source dominates is a later concern;
  v1 fusion treats both sources symmetrically.
- NO cross-modal salience scorer (forward marker **AD-746-2**).
  Fusion treats both frames as equal evidence in v1.
- NO audio as a third fused source (forward marker **AD-746-3**;
  pairs with AD-747).
- NO browser-side fusion preview (forward marker **AD-746-4**).
- NO removal of the legacy `source` field on the anchor (forward
  marker **AD-746-5**).
- NO change to `VisionConsumer._describe()` LLM call shape — the
  fused frame is built by `build_multimodal_messages` from the
  list of refs; the OpenAI image_url + data-URL shape is already
  list-aware (BF-268 / BF-277). One-image vs two-image is a count
  difference, not a shape difference.
- NO change to AD-742c camera binding semantics (`bound_agent_ids` on
  the intent message stays exactly as-is — `bound_sources` is
  per-agent profile data, not per-frame).

## File targets

| File | Change |
|---|---|
| `src/probos/perception/aggregator.py` | **NEW.** `VisionAggregator` class with 800 ms debounce window + fused intent message construction. ~180 lines. |
| `src/probos/perception/consumer.py` | Extend the AD-742c `bound_agent_ids` early branch (line ~430) to also filter against the active agent's `bound_sources`. ~20 lines. |
| `src/probos/config.py` | `PerceptionConfig` (line 2099): two new fields (`source_fusion_enabled`, `fusion_window_ms`). |
| `src/probos/crew_profile.py` | `PerceptionProfile` (line 330): new `bound_sources` field; `__post_init__` validator (subset of `{"camera","screen"}`); `from_dict` / `to_dict` roundtrip. |
| `src/probos/routers/perception.py` | Two new endpoints (`GET /api/perception/sources`, `POST /api/perception/sources/binding`). |
| `src/probos/startup/finalize.py` | Wire `VisionAggregator` next to `VisionConsumer` when `perception.enabled` AND `source_fusion_enabled` are True. |
| `src/probos/settings/section_registry.py` | Two new `FieldDescriptor`s in the Perception section (AD-741). |
| `ui/src/components/settings/sections/PerceptionLivePanel.tsx` | CAMERA BINDINGS → SOURCE BINDINGS row extension (stroke-SVG check pills). |
| `ui/src/store/useSourceBindingsStore.ts` | **NEW.** Zustand sibling slice. |

**Tests** (NOT inside `src/probos/` or `ui/src/` — these are the
exception per the standing dispatch rule: tests live in `tests/` and
`ui/src/__tests__/` but the Builder is the one who writes them):

| Test file | Count | Coverage |
|---|---|---|
| `tests/test_ad746_vision_aggregator.py` | +10 pytest | Single-source passthrough; two-source fusion within window; window expiry → passthrough; AD-731 source-scan; AD-733c-6 budget = 1 call per fused observation; primary-ref preserved on fused; sources list contains both; sources list ordering deterministic; aggregator handles missing source field (legacy intent → defaults to "camera"); cancellation cleanup. |
| `tests/test_ad746_source_binding.py` | +4 pytest | Default bound_sources = both; binding restricts WM fan-out; binding restricts episodic anchor; fused frame visible when one of two sources in binding. |
| `ui/src/__tests__/PerceptionLivePanel.sourceBindings.test.tsx` | +4 vitest | SOURCE BINDINGS section renders for ≥2 cameras OR any agent with screen binding; CAMERA / SCREEN pills render independently; click flips binding via POST; HXI #3 — no emoji in pills. |

Total: **+14 pytest, +4 vitest.**

## Acceptance criteria

1. `pytest tests/test_ad746_*.py -v -n 0` — 14 new tests pass.
2. Full gate `pytest tests/ -q -n 4 --dist=loadfile` — green; baseline
   pytest count = HEAD + 14.
3. `cd ui; npx vitest run` — full gate green; +4 new tests pass.
4. `cd ui; npm run build` — exit 0.
5. **AD-731 invariant preserved** —
   `test_ad731_invariant_no_inline_base64_in_perception_modules`
   extended to scan `aggregator.py`.
6. **AD-733c-6 budget invariant preserved** — fused frames count as
   1 vision call (regression test in `test_ad746_vision_aggregator.py`).
7. **AD-742c invariant preserved** — `bound_agent_ids` on the intent
   message still works exactly as today; the new `bound_sources` is
   per-agent profile data, not per-intent.
8. **Captain smoke**: with camera + screen both streaming, observe
   that Counselor (bound to `["camera"]`) sees only camera frames in
   her DM context, and Operations (bound to `["screen"]`) sees only
   screen frames. WM is source-coherent per agent.
9. **Honest-degrade preserved**: when `source_fusion_enabled=False`,
   the aggregator is bypassed (the consumer subscribes directly to
   the bus); zero behavior delta vs HEAD.
10. Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.

## Forward markers

- **AD-746-1** — Raw priority knob (preempt fusion when one source
  dominates; Vapi-style interruption-sensitivity).
- **AD-746-2** — Cross-modal salience scorer (CLIP-style novelty
  weighting per source per tick).
- **AD-746-3** — Audio as a third fused source (mic context join;
  pairs with AD-747).
- **AD-746-4** — Browser-side fusion preview (Captain sees composed
  multimodal prompt before send).
- **AD-746-5** — Retire legacy `source: str` anchor field after one
  wave of no-regression on the new `sources: list[str]` shape.

## Verified Against Codebase (2026-05-19)

```
grep -n "class VisionConsumer\|INTENT_NAME" src/probos/perception/consumer.py
  77: class VisionConsumer:
  80:     INTENT_NAME = "vision_observation"

grep -n "bound_agent_ids" src/probos/perception/consumer.py
  ~420: _bound_raw = msg.params.get("bound_agent_ids")

grep -n "_VALID_SOURCES\|source: str = Form" src/probos/routers/perception.py
  128: _VALID_SOURCES: frozenset[str] = frozenset({"camera", "screen"})
  141:     source: str = Form("camera"),

grep -n "camera_device_id" src/probos/crew_profile.py
  337:     - ``camera_device_id`` belongs to AD-742c (per-agent camera). Empty
  348:     camera_device_id: str = ""
  358:             camera_device_id=str(data.get("camera_device_id", "")),

grep -n "class PerceptionProfile" src/probos/crew_profile.py
  330: class PerceptionProfile:

grep -n "class PerceptionConfig" src/probos/config.py
  2099: class PerceptionConfig(BaseModel):

grep -n "class PerceptionEngagementRegistry" src/probos/perception/engagement_registry.py
  25: class PerceptionEngagementRegistry:
```

All anchors confirmed at HEAD (`4beaba7e`).
