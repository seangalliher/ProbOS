# AD-739 — Captain Card: operator self-card, always-in-context (v1)

**Status:** Draft for Wave 163
**Dependencies:** Existing KnowledgeStore (verify), existing `prompt_builder.build_system_prompt` (`src/probos/cognitive/prompt_builder.py:163`), existing AD-588/589/592 confabulation guard / `_CAPABILITY_GAP_RE`.
**Closes:** #649
**Estimated tests:** 10 pytest
**Build order:** Independent of the peer-observation cluster.

## Scope discipline — what v1 ships

Issue #649 is explicitly a planning AD. Wave 163 ships:

- **Data model.** `CaptainCard` Pydantic model with the fields below.
- **Storage.** KnowledgeStore record with Git-backed versioning.
- **Single injection surface.** Stitched into `prompt_builder.build_system_prompt` for ALL CognitiveAgent system prompts.
- **Card maintenance.** A single dreaming-consolidation hook that refreshes the Card from correction-feedback episodes. NO agent-writable surface.

Wave 163 does NOT ship (forward markers):

- Per-department overlays. v1 is single base Card. (AD-739a forward marker.)
- AD-733a recognition-embedding integration. avatar_ref is stored but not consumed. (AD-733a remains open.)
- Multi-operator support. (AD-739b forward marker.)

## Section 0: Data model

`src/probos/captain_card/card.py` (new module):

```python
class CaptainCard(BaseModel):
    """Operator self-card, always stitched into CognitiveAgent prompts.

    System-maintained — NOT agent-self-edited. Updates flow through
    Dreaming consolidation + correction-feedback only.
    """
    # Identity
    name: str
    callsign: str | None
    role: str

    # Voice / style
    tone: str = Field(default="direct", description="Default tonal anchor.")
    formatting_preferences: list[str] = Field(default_factory=list)

    # Active context
    current_project: str | None = None
    current_wave: str | None = None

    # Known preferences (short bullet form)
    preferences: list[str] = Field(default_factory=list, max_length=10)

    # Recent high-importance corrections (≤3 entries)
    recent_corrections: list[CorrectionRef] = Field(default_factory=list, max_length=3)

    # Identity recognition anchor (AD-733a coupling — STORED, not consumed in v1)
    avatar_ref: str | None = Field(
        default=None,
        description="AttachmentStore SHA-256 ref of the Captain's recognition image. Reserved for AD-733a streaming-vision coupling; v1 does not consume."
    )

    # Versioning
    version: int = Field(default=1)
    updated_at: float
```

`CorrectionRef` is a small dataclass `{episode_id: str, summary: str, timestamp: float}`. Summary is template-rendered from the correction episode, NOT free-form — predictability matters for prompt injection.

**Token budget target:** the rendered Card text MUST be ≤500 tokens. Renderer (Section 3) enforces truncation.

## Section 1: Config

Extend `CognitiveConfig` (verify class name; the existing config-class list confirms `CognitiveConfig`):

```python
captain_card_enabled: bool = Field(
    default=True,
    description="AD-739 Captain Card injection into CognitiveAgent system prompts. Default ON.",
)
captain_card_path: str = Field(
    default="captain_card",
    description="AD-739 KnowledgeStore record key.",
)
captain_card_max_tokens: int = Field(
    default=500,
    ge=100,
    le=1500,
    description="AD-739 token budget for rendered Card text injected into system prompts.",
)
captain_card_refresh_min_interval_seconds: int = Field(
    default=3600,
    ge=60,
    description="AD-739 minimum interval between Dreaming-driven Card refreshes.",
)
```

Defaults reasoned: default-ON because the Card is a benign context anchor; small token budget; refresh hourly at most to avoid Dreaming overhead.

## Section 2: Storage via KnowledgeStore

KnowledgeStore is Git-backed (per ProbOS architecture). The Card record persists at the configured key. Versioning is free — each save commits.

**Builder verify-first:** the exact KnowledgeStore API surface (likely `store.put(key, payload)` / `store.get(key)`). Confirm the class name in `src/probos/knowledge/store.py` before drafting persistence code.

Updates flow through `update_captain_card(card: CaptainCard) -> None` — single mutation path. No partial-update API in v1; the whole Card is rewritten each refresh (small object, Git-friendly).

## Section 3: Prompt injection

In `src/probos/cognitive/prompt_builder.py:build_system_prompt`, after the existing system identity preamble but BEFORE the system context / intent registry, inject:

```
## Captain
{rendered_captain_card}
```

The renderer (`render_card_for_prompt(card: CaptainCard, max_tokens: int) -> str`) produces a compact YAML-like block. Truncation logic: if rendered text exceeds the budget, truncate the `preferences` and `recent_corrections` lists from the tail until the budget fits.

Source-scan regression test: `prompt_builder.py` after edit MUST include a single `{captain_card}` injection point and must NOT inject the Card MULTIPLE times.

## Section 4: Validation at prompt boundary

Per issue body — "Validated at the prompt boundary. Card content passes through the `_CAPABILITY_GAP_RE` + confabulation-guard surfaces (AD-588/589/592 lineage) before injection."

In `render_card_for_prompt`, after building the rendered text:

1. Run `_CAPABILITY_GAP_RE` against the rendered text. If it matches (e.g., the text accidentally contains a phrase like "I can't ..."), strip the matching line(s) and log a WARNING.
2. NO LLM call in the renderer. Validation is pure regex (zero new latency).

**Builder verify-first:** confirm `_CAPABILITY_GAP_RE` import path. The regex IS used somewhere in prompt-build flow per the issue body.

## Section 5: Dreaming integration

In the existing Dreaming consolidation loop (verify file: `src/probos/cognitive/dreaming.py`), add a single hook at the end of each consolidation cycle:

```python
def _maybe_refresh_captain_card(self) -> None:
    """AD-739: refresh the Captain Card from recent correction-feedback episodes.

    Throttled by `captain_card_refresh_min_interval_seconds`. No-op if
    not enough time has passed or no high-importance corrections since
    last refresh.
    """
```

The refresh function reads correction-feedback episodes since the last refresh, ranks by importance, picks the top N (≤3) for `recent_corrections`, and rewrites the Card. NO LLM call — template-driven aggregation only. (LLM-driven refresh is forward marker AD-739c.)

## Section 6: Bootstrap

On first runtime startup with no Card yet, write a minimal default Card:

```python
CaptainCard(
    name="Captain",
    callsign=None,
    role="Operator",
    tone="direct",
    formatting_preferences=[],
    current_project=None,
    current_wave=None,
    preferences=[],
    recent_corrections=[],
    avatar_ref=None,
    version=1,
    updated_at=time.time(),
)
```

Subsequent edits flow through correction-feedback + Dreaming. NO operator-facing setup wizard in v1 (forward marker AD-739d for the wizard).

## Section 7: Tests (≥10 pytest)

`tests/test_ad739_captain_card.py`:

1. Default-bootstrap Card created on first startup.
2. Card persists across runtime restart (KnowledgeStore round-trip).
3. `render_card_for_prompt` produces output within token budget for a populated Card.
4. Truncation: oversized Card → `preferences`/`recent_corrections` truncated; identity fields preserved.
5. `_CAPABILITY_GAP_RE` validation: rendered text containing a gap phrase has the line stripped.
6. Prompt injection: `build_system_prompt` output contains the rendered Card once (regex-count = 1).
7. `captain_card_enabled=False` → no Card injection in system prompt.
8. Dreaming refresh respects `captain_card_refresh_min_interval_seconds` throttle.
9. Dreaming refresh: ≥3 new correction-feedback episodes → Card updates with top 3 in `recent_corrections`.
10. AD-731 invariant: `avatar_ref` field is a SHA-256 string when set, NOT inline bytes. Schema-level enforcement via Pydantic str type + a regex validator.

Use **real `SystemConfig()` fixtures** + real KnowledgeStore (in-memory variant if needed). NO MagicMock at config boundary — BF-287.

## Section 8: Builder Standing Rules

- BF-274: single replace for adjacent edits, ESPECIALLY in `prompt_builder.py` (load-bearing module).
- BF-280: no `asyncio.create_subprocess_*`.
- BF-282: no binary stdout.
- BF-286: test scaffolding mirrors production prompt-builder shape.
- BF-287: real Config / real KnowledgeStore fixtures.
- AD-738b: no UI in this AD; no `npm run build` gate.
- AD-731 invariant: verified by Test 10 (avatar_ref is SHA-256 string, no inline bytes).
- AD-722c-3: forward markers below use TECHNICAL triggers.
- License posture: ZERO new pip deps. Confirmed.

## What this does NOT change

- The existing `prompt_builder.build_system_prompt` behavior outside the injection point.
- The Dreaming consolidation loop semantics outside the new hook.
- KnowledgeStore API.
- Any agent's `instructions` string — agents are CognitiveAgents with their own instructions; the Card is operator-context, not agent-personality.
- Episodic memory, trust, Hebbian routing — Card is READ-ONLY w.r.t. all three.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #649.
- `docs/development/roadmap.md`: move AD-739 from forward markers; AD-739a/b/c/d sub-AD forward markers filed.
- `DECISIONS.md`: append AD-739 entry — v1 data model + KnowledgeStore + single injection surface.

## Forward markers (TECHNICAL triggers per AD-722c-3)

- **AD-739a — Per-department overlays.** Trigger: when ≥3 departments use the Card in distinct ways (different preferences referenced per department). Issue filed.
- **AD-739b — Multi-operator support.** Trigger: when AD-379-equivalent multi-operator runtime ships. Issue filed.
- **AD-739c — LLM-driven Dreaming refresh.** Trigger: when template-driven refresh has produced ≥20 Card updates AND manual review shows template missing important context. Issue filed.
- **AD-739d — Operator setup wizard.** Trigger: when Card has been used by ≥3 operators and bootstrap-default friction is documented in a BF. Issue filed.
- **AD-733a coupling.** Trigger: when AD-733a streaming-vision lands AND needs the recognition anchor (already stored in `avatar_ref` field — zero schema change required).

## Acceptance Criteria

1. All Section 0-6 deliverables landed.
2. ≥10 pytest tests pass.
3. Full gate green.
4. `prompt_builder.py` injection point is single-instance (regex-verified in Test 6).
5. Zero new pip deps confirmed.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "def build_system_prompt" src/probos/cognitive/prompt_builder.py
  163

grep -n "class CognitiveConfig" src/probos/config.py
  (present per config-class enumeration)
```

**Builder verify-first flags:**
- `_CAPABILITY_GAP_RE` exact module — VERIFY before Section 4.
- KnowledgeStore API surface (`store.put` / `store.get` / equivalent) — VERIFY before Section 2.
- Dreaming consolidation hook location — VERIFY before Section 5.
- Existing prompt-build flow does NOT already include something Card-like — confirm by reading lines around `build_system_prompt:163` before injecting.

## License posture

Zero new pip/npm deps. Confirmed. The Letta-style pattern is inspirational only (no Letta code imported). Letta is Apache-2.0; ProbOS is Apache-2.0 — even if pattern-absorption needed re-export, it would be compatible. But ZERO code copy. ZERO dep add.
