# AD-737 — Per-agent custom emotion taxonomy (v2; beyond the fixed 8)

**Status:** Ready for Builder
**AD:** AD-737 (next free top-level number after AD-736; Wave 156 highest-AD audit).
**GH issue:** [#612](https://github.com/seangalliher/ProbOS/issues/612) (closes)
**Parent ADs:** AD-722a (intent-vs-presentation divergence detector, shipped Wave 143). AD-722a-7 (manifest-driven intent rules, shipped). Explicit forward-marker reference in [src/probos/avatars/telemetry.py:184-188](src/probos/avatars/telemetry.py#L184-L188) and [src/probos/avatars/divergence_detector.py:36-37](src/probos/avatars/divergence_detector.py#L36-L37).
**Wave:** 156
**Estimated tests:** ~7-9 new in `tests/test_ad737_emotion_taxonomy.py` (NEW Python file). Plus 0 UI tests (intent rule table is loaded from the manifest; custom emotions never reach `voiceModulation.ts` in v1 — see Section 4).

---

## Captain decisions baked in

1. **Each agent declares custom emotions in their CrewProfile, not in the global manifest.** The manifest stays the SHARED vocabulary; custom emotions are agent-private. This keeps the manifest's "schema fixed; deviations require an architecture-decision review" invariant intact ([telemetry.py:155-160](src/probos/avatars/telemetry.py#L155-L160)).
2. **`inherits` is mandatory and must point at a v1 emotion.** Counselor's "professional concern" inherits from `concerned`; Worf's "controlled fury" inherits from `formal` (Worf has no `anger` in v1, so `formal` is the closest directional axis — `-1`, firmer/lower). The divergence detector resolves through `inherits` to compute `INTENT_DIRECTION` and `INTENT_EXPECTED_RULES`. The LLM hears the custom name; the rule engine reuses the parent's behaviour.
3. **Voice modulation deltas are additive, not absolute.** Each `EmotionProfile` declares `pitch_shift`, `rate_shift`, `volume_shift` (all defaulting to 0.0) which are added to the parent's manifest factors when computing the effective modulation. Magnitudes capped at ±0.15 to prevent runaway. v1 keeps the fixed 8 as-is; custom emotions are LAYERED on top.
4. **Bounded set per agent.** Max 8 custom emotions per agent. Captain canon: agents should not produce a 30-emotion zoo that's indistinguishable from no taxonomy at all.
5. **Validated at config load AND at runtime read.** Defense in depth: the Pydantic model validates structure; the divergence detector re-validates `inherits` against the live `EmotionalIntent` enum when resolving (so a stale config from a previous v1 doesn't blow up the detector).
6. **Server strips the tag regardless of name.** The existing `_TAG_RE` ([divergence_detector.py:86-89](src/probos/avatars/divergence_detector.py#L86-L89)) already matches `<intent emotion=NAME>` where NAME is `[a-zA-Z_]+`. No regex change. Unknown names (including unknown CUSTOM names) gracefully return `None` from `parse_intent_self_tag`, which short-circuits the divergence pipeline. v2 extends `parse_intent_self_tag` to accept custom names registered for the current agent.
7. **Prompt builder injects the agent's available taxonomy.** The hardcoded list at [cognitive_agent.py:3188-3193](src/probos/cognitive/cognitive_agent.py#L3188-L3193) (`warm | concerned | ...`) becomes dynamic: read the agent's custom emotions, render `v1_set + custom_set`. Token cost grows from ~10 to ~15-25 depending on how many custom emotions the agent has declared.

---

## Problem

Today the LLM has 8 emotion names available, hardcoded into the system prompt at [cognitive_agent.py:3188-3193](src/probos/cognitive/cognitive_agent.py#L3188-L3193):

```python
"After your reply, on a new line, emit "
"`<intent emotion=NAME>` where NAME is one of: "
"warm | concerned | excited | apologetic | formal | playful | "
"reassuring | neutral. The tag will be stripped server-side; "
"do not mention it in your prose."
```

Counselor (Echo) cannot reach for "professional concern" (which is distinct from raw `concerned` — more formal, less emotionally invested). Worf (if shipped) couldn't reach for "controlled fury" (the Klingon mode of firmness). The v1 taxonomy is functional but flat. Domain experts get one emotional knob per quadrant; they need finer-grained vocabulary that maps to known v1 behaviour.

The fix is NOT to expand the v1 set globally — that explodes the manifest and breaks AD-722a-7's "schema fixed" invariant. The fix is per-agent: each agent declares a small palette of custom emotions that **inherit** from a v1 emotion and add small voice deltas on top.

---

## Solution

Four pieces:

1. **New `EmotionProfile` dataclass in `crew_profile.py`** with the per-emotion voice delta fields.
2. **Add `custom_emotions: dict[str, EmotionProfile]` to `CrewProfile`** (the existing per-agent profile dataclass). Default `{}` — no behaviour change for agents that don't opt in.
3. **Extend `divergence_detector.py`** to resolve custom names through `inherits` when parsing the self-tag and computing `INTENT_DIRECTION` / `INTENT_EXPECTED_RULES`.
4. **Extend `_build_intent_self_tag_instruction` in `cognitive_agent.py`** to read the agent's `custom_emotions` and append them to the dynamic taxonomy list in the prompt.

Voice-modulation factor lookup (`apply_voice_modulation` in `telemetry.py`) extends to consume custom emotion deltas: the parent's `INTENT_RULES` factors PLUS the custom emotion's `pitch_shift`/`rate_shift`/`volume_shift` (small additive deltas, clamped).

UI is unaffected in v1. The custom name reaches the TS layer only as a string; the modulation manifest on the TS side does NOT need new entries because the server-side `apply_voice_modulation` is the authoritative computation for the divergence detector AND the per-utterance voice signal that the avatar uses. The TS `applyEmotionalModulation` continues to use the manifest's v1 set — agents that DM the Captain see modulation through the server path, which already returns the resolved `pitch_factor` / `rate_factor` / `volume_factor`. (Forward marker: TS-side custom-emotion modulation parity is AD-737a if the operator wants the in-browser path to mirror server-side resolution.)

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/crew_profile.py` | Add `EmotionProfile` dataclass + `custom_emotions: dict[str, EmotionProfile]` field on `CrewProfile`. Extend `to_dict()` / `from_dict()`. |
| `src/probos/avatars/divergence_detector.py` | Extend `parse_intent_self_tag` to accept custom names (per-agent palette lookup). Extend `INTENT_DIRECTION` / `INTENT_EXPECTED_RULES` lookup through `inherits`. |
| `src/probos/avatars/telemetry.py` | Extend `apply_voice_modulation` to accept a custom-emotion delta and compose: parent v1 rule × (1 + delta), clamped. |
| `src/probos/cognitive/cognitive_agent.py` | Rewrite `_build_intent_self_tag_instruction` to render `v1_set + custom_set` from the agent's `CrewProfile.custom_emotions`. |
| `tests/test_ad737_emotion_taxonomy.py` | NEW — 6-8 Python tests. |
| `PROGRESS.md` | Wave 156 entry; +tests count delta. |
| `DECISIONS.md` | Append AD-737 closure block. |
| `docs/development/roadmap.md` | Mark AD-737 shipped Wave 156; close [#612](https://github.com/seangalliher/ProbOS/issues/612). |

**Do NOT touch:**
- `ui/src/audio/voiceModulation.ts` — TS-side modulation continues to use the manifest's v1 set; custom emotions reach the TS layer as a string only, and the server returns resolved factors. (Forward marker AD-737a if TS-side parity is wanted.)
- `ui/src/audio/modulation_manifest.json` — manifest stays the SHARED vocabulary, untouched.
- `src/probos/avatars/modulation_manifest.json` (if a copy exists in src) — same.
- The `_REQUIRED_INTENT_EMOTIONS` tuple in [telemetry.py:99-103](src/probos/avatars/telemetry.py#L99-L103) — v1 set is fixed; do not append to it.
- `EmotionalIntent` enum in [divergence_detector.py:33-44](src/probos/avatars/divergence_detector.py#L33-L44) — v1 set is fixed; do not append to it.
- `AvatarTelemetryConfig` in `config.py` — no new config flag needed; opt-in is per-agent via their CrewProfile.
- `pyproject.toml` — no new deps.
- AD-731 invariant — this change does not touch attachments, the bus, or RPC.

---

## Section 1 — `EmotionProfile` dataclass + `CrewProfile.custom_emotions`

### 1a. New dataclass in `src/probos/crew_profile.py`

After the existing `VoiceProfile` dataclass (ends ~line 158), add:

```python
@dataclass
class EmotionProfile:
    """AD-737: per-agent custom emotion override.

    A custom emotion is a NAME the LLM may emit in the ``<intent emotion=NAME>``
    self-tag in place of (or in addition to) the v1 fixed eight. Each custom
    emotion ``inherits`` from a v1 emotion — the divergence detector resolves
    through ``inherits`` to compute INTENT_DIRECTION and INTENT_EXPECTED_RULES.

    Voice deltas (``pitch_shift``, ``rate_shift``, ``volume_shift``) are
    ADDITIVE on top of the parent's manifest factor and clamped to ±0.15.
    The parent emotion's rule fires first; the delta composes on top.

    All fields validated in ``__post_init__``.
    """
    inherits: str          # MUST be one of EmotionalIntent values
    pitch_shift: float = 0.0   # additive; clamped to [-0.15, +0.15]
    rate_shift: float = 0.0    # additive; clamped to [-0.15, +0.15]
    volume_shift: float = 0.0  # additive; clamped to [-0.15, +0.15]

    # Bound used in validators AND re-exported for callers / tests.
    SHIFT_BOUND: ClassVar[float] = 0.15

    def __post_init__(self) -> None:
        # Defer the EmotionalIntent import to avoid the avatars-pipeline
        # import cycle (crew_profile is imported very early in startup).
        from probos.avatars.divergence_detector import EmotionalIntent
        valid = {e.value for e in EmotionalIntent}
        if self.inherits not in valid:
            raise ValueError(
                f"EmotionProfile.inherits={self.inherits!r} must be one of "
                f"{sorted(valid)}"
            )
        for name in ("pitch_shift", "rate_shift", "volume_shift"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(
                    f"EmotionProfile.{name} must be a number, got {type(v).__name__}"
                )
            if abs(v) > self.SHIFT_BOUND:
                raise ValueError(
                    f"EmotionProfile.{name}={v} exceeds ±{self.SHIFT_BOUND}"
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EmotionProfile":
        return cls(**{
            k: data[k] for k in (
                "inherits", "pitch_shift", "rate_shift", "volume_shift",
            ) if k in data
        })
```

Add `from typing import ClassVar` to the existing imports at the top of `crew_profile.py` if not already present.

### 1b. Add the field to `CrewProfile`

Locate the `CrewProfile` dataclass (Builder: grep for `class CrewProfile` in `src/probos/crew_profile.py`). Add:

```python
    # AD-737: per-agent custom emotion taxonomy. Empty dict = use v1 fixed
    # eight only (no behaviour change). Names are case-sensitive; keys must
    # match the regex r"^[a-z][a-z_]{0,29}$" (lowercase, ≤ 30 chars, no
    # spaces — the parser strips by name).
    custom_emotions: dict[str, EmotionProfile] = field(default_factory=dict)
```

Add a validator in `CrewProfile.__post_init__` (or wherever existing field-validation happens):

```python
        # AD-737: validate custom_emotions
        import re
        _CUSTOM_NAME_RE = re.compile(r"^[a-z][a-z_]{0,29}$")
        if len(self.custom_emotions) > 8:
            raise ValueError(
                f"custom_emotions max 8 entries, got {len(self.custom_emotions)}"
            )
        for name, profile in self.custom_emotions.items():
            if not _CUSTOM_NAME_RE.match(name):
                raise ValueError(
                    f"custom_emotions key {name!r} must match {_CUSTOM_NAME_RE.pattern}"
                )
            if not isinstance(profile, EmotionProfile):
                raise ValueError(
                    f"custom_emotions[{name!r}] must be EmotionProfile, "
                    f"got {type(profile).__name__}"
                )
            # AD-737: forbid shadowing v1 names
            from probos.avatars.divergence_detector import EmotionalIntent
            if name in {e.value for e in EmotionalIntent}:
                raise ValueError(
                    f"custom emotion name {name!r} collides with v1 taxonomy; "
                    "use a distinct name (e.g. 'professional_concern' not 'concerned')"
                )
```

Extend `to_dict()` and `from_dict()` to round-trip `custom_emotions`. Builder: confirm the existing serialisation pattern in `CrewProfile.to_dict` / `from_dict` and mirror.

---

## Section 2 — Divergence detector: accept custom names through `inherits`

In `src/probos/avatars/divergence_detector.py`:

### 2a. Add a custom-emotion lookup helper

After the `INTENT_DIRECTION` constant (ends ~line 80), add:

```python
def _resolve_intent_name(
    name: str,
    custom_emotions: dict[str, "EmotionProfile"] | None,
) -> str | None:
    """AD-737: resolve a parsed intent name to a v1 EmotionalIntent value.

    Returns the v1 emotion name (one of EmotionalIntent.value) if ``name``
    is either (a) a v1 name directly, or (b) a custom emotion whose
    ``inherits`` field points at a v1 name. Returns ``None`` otherwise
    (caller short-circuits the divergence pipeline).

    Type annotation uses a forward reference for ``EmotionProfile`` to
    avoid the crew_profile import cycle.
    """
    if name in INTENT_EXPECTED_RULES:
        return name
    if not custom_emotions:
        return None
    profile = custom_emotions.get(name)
    if profile is None:
        return None
    parent = getattr(profile, "inherits", None)
    if parent in INTENT_EXPECTED_RULES:
        return parent
    # Defensive: stale config drift could put a bad inherits past the
    # CrewProfile validator (e.g. dataclass mutated post-construct).
    logger.debug(
        "AD-737: custom emotion %r has invalid inherits=%r; treating as unknown",
        name, parent,
    )
    return None
```

Add `from typing import TYPE_CHECKING` (already present) and inside `TYPE_CHECKING`:

```python
if TYPE_CHECKING:
    from probos.crew_profile import EmotionProfile  # noqa: F401  AD-737
```

### 2b. Extend `parse_intent_self_tag`

Find the existing function at [divergence_detector.py:172+](src/probos/avatars/divergence_detector.py#L172). Add a `custom_emotions` parameter:

```python
def parse_intent_self_tag(
    text: str,
    custom_emotions: dict[str, "EmotionProfile"] | None = None,
) -> str | None:
    """Extract the emotion name from an ``<intent emotion=NAME>`` tag.

    Returns the parsed name when it is either (a) a v1 EmotionalIntent
    value, or (b) AD-737 a custom emotion declared in ``custom_emotions``.
    Returns ``None`` for unknown names — the caller short-circuits.
    """
    if not text:
        return None
    match = _TAG_RE.search(text)
    if match is None:
        return None
    name = match.group(1).strip().lower()
    if _resolve_intent_name(name, custom_emotions) is None:
        logger.debug(
            "AD-722a: parsed intent tag with unknown emotion=%r; ignoring",
            name,
        )
        return None
    return name
```

Note: this returns the CUSTOM name (not the resolved v1 parent), so the divergence result carries the agent's authored vocabulary. The CALLER uses `_resolve_intent_name` to compute `INTENT_DIRECTION` and `INTENT_EXPECTED_RULES` when needed.

### 2c. Update the single call site: `apply_divergence_check`

Pass-1 review correction: `parse_intent_self_tag` has exactly ONE call site, and it is **not** in `routers/agents.py`. It is inside `apply_divergence_check` at [src/probos/avatars/divergence_detector.py:356](src/probos/avatars/divergence_detector.py#L356) (verified via `grep parse_intent_self_tag\(` → 2 matches: definition at 173, single call at 356). The same helper also calls `apply_voice_modulation` at line ~378.

Three threaded changes in this function:
1. Look up the agent's `custom_emotions` from `runtime.profile_store` (tier-2 log-and-degrade).
2. Pass `custom_emotions` to both `parse_intent_self_tag` and `apply_voice_modulation`.
3. **Critical scoring fix**: pre-resolve the parsed `intent` to its v1 parent via `_resolve_intent_name`, pass the *resolved* name as `intent_emotion` to `compute_divergence` (because `INTENT_EXPECTED_RULES` is keyed on v1 names; a custom name yields `frozenset()` and the `not expected and applied_set` branch returns `match_score = 0.0`). Then restore the custom name on the returned `DivergenceResult` for observability via `dataclasses.replace`.

Find the SEARCH block at [divergence_detector.py:356-388](src/probos/avatars/divergence_detector.py#L356-L388):

```python
    intent = parse_intent_self_tag(response_text)
    # Strip unconditionally when feature ON -- even on parse failure
    # (unknown emotion / malformed tag), the visible tag must not leak.
    stripped = strip_intent_self_tag(response_text)

    snap = getattr(agent, "_last_self_avatar_snap", None)
    modulation = getattr(snap, "applied_modulation", None) if snap is not None else None
    if intent is None or modulation is None:
        return stripped

    # AD-722a-7: recompute the modulation with the parsed intent so
    # ``fired_rules`` carries the ``intent_X`` rule the divergence calc
    # is keyed against. Pure function call; the cached snap's signals
    # already drove the operational-rule computation pre-reply, so we
    # reuse them. The voice profile is looked up via the profile_store
    # when available; if absent (test fakes, fresh agents), we fall back
    # to a synthetic identity baseline -- ``fired_rules`` does not depend
    # on profile baseline values, only on signal triple + intent.
    signals = getattr(snap, "current_signals", None)
    if signals is not None:
        from probos.avatars.telemetry import apply_voice_modulation
        voice_profile = _resolve_voice_profile_for_intent(runtime, agent_id)
        modulation = apply_voice_modulation(
            voice_profile, signals, intent=intent,
        )

    result = compute_divergence(
        intent_emotion=intent,
        applied_fired_rules=tuple(modulation.fired_rules),
    )
```

Replace with:

```python
    # AD-737: look up the agent's custom emotion palette (tier-2 log-and-degrade).
    custom_emotions: dict[str, Any] | None = None
    store = getattr(runtime, "profile_store", None)
    if store is not None:
        try:
            crew = store.get(agent_id) if hasattr(store, "get") else None
            custom_emotions = getattr(crew, "custom_emotions", None) if crew else None
        except Exception:
            logger.debug(
                "AD-737: profile_store custom_emotions lookup failed for %s",
                agent_id, exc_info=True,
            )

    intent = parse_intent_self_tag(response_text, custom_emotions=custom_emotions)
    # Strip unconditionally when feature ON -- even on parse failure
    # (unknown emotion / malformed tag), the visible tag must not leak.
    stripped = strip_intent_self_tag(response_text)

    snap = getattr(agent, "_last_self_avatar_snap", None)
    modulation = getattr(snap, "applied_modulation", None) if snap is not None else None
    if intent is None or modulation is None:
        return stripped

    # AD-722a-7 / AD-737: recompute the modulation with the parsed intent
    # (custom or v1) so ``fired_rules`` carries both the parent ``intent_X``
    # rule (used by ``compute_divergence``'s ``startswith('intent_')`` filter)
    # AND the ``custom_X`` tag for observability.
    signals = getattr(snap, "current_signals", None)
    if signals is not None:
        from probos.avatars.telemetry import apply_voice_modulation
        voice_profile = _resolve_voice_profile_for_intent(runtime, agent_id)
        modulation = apply_voice_modulation(
            voice_profile, signals, intent=intent,
            custom_emotions=custom_emotions,
        )

    # AD-737 critical scoring fix: ``compute_divergence`` keys ``expected``
    # on the v1 INTENT_EXPECTED_RULES table; a raw custom name yields
    # ``frozenset()`` and the ``not expected and applied_set`` branch
    # forces ``match_score = 0.0`` (silent maximum-divergence corruption).
    # Resolve to the v1 parent for scoring, then restore the custom name
    # on the DivergenceResult for downstream observability.
    resolved_v1 = _resolve_intent_name(intent, custom_emotions) or intent
    result = compute_divergence(
        intent_emotion=resolved_v1,
        applied_fired_rules=tuple(modulation.fired_rules),
    )
    if resolved_v1 != intent:
        import dataclasses as _dc
        result = _dc.replace(result, intent_emotion=intent)
```

No other call sites of `parse_intent_self_tag` exist (verified). Tests in `tests/test_ad722a_divergence_detector.py` call `parse_intent_self_tag(text)` directly with no custom_emotions kwarg — the new kwarg defaults to `None` so backward-compat is intact (Section 5 test 5 covers this).

---

## Section 3 — `apply_voice_modulation` accepts custom deltas

In `src/probos/avatars/telemetry.py`, extend the existing function ([telemetry.py:396-466](src/probos/avatars/telemetry.py#L396-L466)):

### 3a. Extend the signature

Change:

```python
def apply_voice_modulation(
    profile: Any,
    signals: AgentSignalsSnapshot,
    intent: str | None = None,
) -> ModulationSnapshot:
```

To:

```python
def apply_voice_modulation(
    profile: Any,
    signals: AgentSignalsSnapshot,
    intent: str | None = None,
    custom_emotions: dict[str, "EmotionProfile"] | None = None,
) -> ModulationSnapshot:
```

Add a `TYPE_CHECKING` import for `EmotionProfile` at module top:

```python
if TYPE_CHECKING:
    from probos.crew_profile import EmotionProfile  # noqa: F401  AD-737
```

### 3b. Resolve custom emotions through `inherits` and compose deltas

Within the intent-handling block (the `if intent is not None:` block near the end of the function), replace:

```python
    if intent is not None:
        rule = INTENT_RULES.get(intent)
        if rule is not None:
            pitch *= rule["pitch"]
            rate *= rule["rate"]
            volume *= rule["volume"]
            fired.append(rule["rule_name"])
```

With:

```python
    if intent is not None:
        # AD-737: resolve custom emotion through inherits before lookup.
        resolved_intent = intent
        delta = None
        if custom_emotions and intent in custom_emotions:
            profile_em = custom_emotions[intent]
            resolved_intent = getattr(profile_em, "inherits", intent)
            delta = profile_em
        rule = INTENT_RULES.get(resolved_intent)
        if rule is not None:
            pitch *= rule["pitch"]
            rate *= rule["rate"]
            volume *= rule["volume"]
            # AD-737: layer custom delta on top of parent factors.
            if delta is not None:
                pitch *= (1.0 + float(delta.pitch_shift))
                rate *= (1.0 + float(delta.rate_shift))
                volume *= (1.0 + float(delta.volume_shift))
                # AD-737 critical: append BOTH the parent's ``intent_X`` rule
                # name (so it survives ``compute_divergence``'s
                # ``startswith('intent_')`` filter and contributes to
                # ``match_score``) AND the ``custom_X`` tag (for
                # observability in journals, telemetry, and snapshots).
                # Pass-1 review found that appending only ``custom_X``
                # silently corrupts scoring → ``match_score = 0.0`` for
                # every custom-emotion reply. Pre-resolution at the
                # ``compute_divergence`` call site (Section 2c) keys
                # ``expected`` on the v1 parent; this dual-tag keys
                # ``applied_set`` on the same v1 anchor.
                fired.extend([rule["rule_name"], f"custom_{intent}"])
            else:
                fired.append(rule["rule_name"])
```

The final clamp on `_clamp(pitch, PITCH_BOUNDS)` etc. (already present) covers both stages.

### 3c. Update the caller in telemetry's `snapshot_for_agent`

Find the existing `apply_voice_modulation(voice_profile, signals, intent=intent_emotion, ...)` call (around [telemetry.py:719-727](src/probos/avatars/telemetry.py#L719-L727)). Add `custom_emotions=crew.custom_emotions if crew else None`:

```python
            applied_modulation = apply_voice_modulation(
                voice_profile,
                signals,
                intent=intent_emotion,
                custom_emotions=crew.custom_emotions if crew else None,
            )
```

---

## Section 4 — Prompt builder: dynamic taxonomy injection

In `src/probos/cognitive/cognitive_agent.py`, replace the `_build_intent_self_tag_instruction` body (lines 3175-3196) with:

```python
    def _build_intent_self_tag_instruction(self, observation: dict | None = None) -> str:
        """AD-722a / AD-737 (feature-gated): instruct the LLM to emit a self-tag.

        Returns a one-line instruction when
        ``avatar_telemetry.divergence_detection`` is True; empty string
        otherwise. AD-737 extends the taxonomy: in addition to the fixed
        v1 set, append the agent's custom emotions from
        ``profile_store.get(agent_id).custom_emotions``.

        Token cost: ~10-25 prompt tokens depending on custom palette size,
        + ~5 reply tokens per cycle.
        """
        del observation  # AD-723: dispatcher passes it; method ignores it.
        cfg = getattr(self._runtime, "config", None) if self._runtime else None
        tcfg = getattr(cfg, "avatar_telemetry", None)
        if not getattr(tcfg, "divergence_detection", False):
            return ""
        # v1 taxonomy (fixed).
        names: list[str] = [
            "warm", "concerned", "excited", "apologetic",
            "formal", "playful", "reassuring", "neutral",
        ]
        # AD-737: append the agent's custom emotion names if profile_store
        # is wired and the agent has any registered.
        try:
            store = getattr(self._runtime, "profile_store", None)
            if store is not None:
                crew = store.get(self.id) if hasattr(store, "get") else None
                custom = getattr(crew, "custom_emotions", None) if crew else None
                if custom:
                    # Sort for prompt stability across runs.
                    names.extend(sorted(custom.keys()))
        except Exception:
            # Tier-2 log-and-degrade: prompt construction must not fail
            # because of a profile-store read.
            logger.debug("AD-737: custom_emotions read failed", exc_info=True)
        taxonomy = " | ".join(names)
        return (
            "After your reply, on a new line, emit "
            f"`<intent emotion=NAME>` where NAME is one of: {taxonomy}. "
            "The tag will be stripped server-side; do not mention it in "
            "your prose."
        )
```

Confirm `logger` is in scope in this file (Builder: grep `^logger = ` at the top of the file).

---

## Section 5 — Tests

New file: `tests/test_ad737_emotion_taxonomy.py`. **8 tests** total (was 7; pass-1 review added the parent-equivalence correctness invariant).

### Test plan

1. **`test_emotion_profile_inherits_must_be_v1`** — Construct `EmotionProfile(inherits="not_a_v1_name")`; assert `ValueError`. Then `EmotionProfile(inherits="concerned")`; assert success.
2. **`test_emotion_profile_shift_bounds`** — `EmotionProfile(inherits="warm", pitch_shift=0.2)`; assert `ValueError` (exceeds 0.15). `EmotionProfile(inherits="warm", pitch_shift=0.1)`; assert success.
3. **`test_crew_profile_custom_emotion_collides_with_v1`** — `CrewProfile(..., custom_emotions={"concerned": EmotionProfile(inherits="formal")})`; assert `ValueError` (shadowing collision).
4. **`test_crew_profile_custom_emotions_max_8`** — Construct a `CrewProfile` with 9 custom emotions; assert `ValueError`. 8 should succeed.
5. **`test_parse_intent_self_tag_accepts_custom_name`** — Build `custom = {"professional_concern": EmotionProfile(inherits="concerned")}`. Call `parse_intent_self_tag("Some reply.\n<intent emotion=professional_concern>", custom_emotions=custom)`; assert it returns `"professional_concern"`. Without `custom_emotions`, assert it returns `None` (proves the v1-only backward-compat path is intact).
6. **`test_apply_voice_modulation_composes_custom_delta_on_inherits`** — Build a fake `signals` snapshot (responding state). Call `apply_voice_modulation(profile, signals, intent="professional_concern", custom_emotions={"professional_concern": EmotionProfile(inherits="concerned", pitch_shift=-0.1)})`. Assert the resulting `pitch_factor` is approximately `(baseline_pitch × INTENT_RULES["concerned"]["pitch"] × 0.9)`, clamped to `PITCH_BOUNDS`. **Critical assertion (per pass-1 review):** `fired_rules` must contain BOTH `"intent_concerned"` (parent rule name; required for `compute_divergence`'s `startswith("intent_")` filter and the `match_score` numerator) AND `"custom_professional_concern"` (observability tag). If only the custom tag is present, `compute_divergence` returns `match_score = 0.0` (silent scoring corruption).
7. **`test_build_intent_self_tag_instruction_includes_custom_names`** — Build a minimal `CognitiveAgent` with a fake `profile_store` that returns `CrewProfile(... custom_emotions={"professional_concern": EmotionProfile(inherits="concerned")})`. Set `runtime.config.avatar_telemetry.divergence_detection = True`. Call `_build_intent_self_tag_instruction()`. Assert the returned string contains `"professional_concern"` AND all 8 v1 names.
8. **`test_custom_emotion_divergence_score_equals_parent`** — Pass-1 review correctness invariant. Build a `CrewProfile` with `custom_emotions={"professional_concern": EmotionProfile(inherits="concerned")}` (zero shifts). Construct identical agent state + signals. Run `apply_divergence_check` twice on the same agent with the same signals, once with `response_text="reply.\n<intent emotion=professional_concern>"` and once with `response_text="reply.\n<intent emotion=concerned>"`. Assert `result_custom.match_score == result_parent.match_score` AND `result_custom.signed_divergence == result_parent.signed_divergence` AND `result_custom.magnitude == result_parent.magnitude`. Assert `result_custom.intent_emotion == "professional_concern"` (custom name surfaced) while `result_parent.intent_emotion == "concerned"` (v1 name surfaced). This pins the v2-parity contract: a custom emotion that inherits from `concerned` with no shifts must score EXACTLY as `concerned` would.

Optional 9th: **`test_unknown_inherits_in_custom_emotion_short_circuits`** — Manually mutate a constructed `EmotionProfile` to set `inherits = "not_v1"` post-construct (bypassing validator). Call `parse_intent_self_tag` with this custom; assert `None` and a DEBUG log fires. Proves the defense-in-depth at `_resolve_intent_name` works.

---

## Section 6 — What this does NOT change

- **The v1 fixed 8.** `EmotionalIntent` enum, `INTENT_EXPECTED_RULES`, `INTENT_DIRECTION`, and `_REQUIRED_INTENT_EMOTIONS` are unchanged. Custom emotions LAYER on top.
- **`modulation_manifest.json`.** Manifest schema is unchanged; the "fixed; deviations require an architecture-decision review" invariant at [telemetry.py:155-160](src/probos/avatars/telemetry.py#L155-L160) is preserved.
- **TS-side modulation (`voiceModulation.ts`).** TS continues to use the manifest's v1 INTENT_RULES. Custom emotion factors are computed SERVER-SIDE in `apply_voice_modulation`; the TS layer never sees the custom name. (Forward marker AD-737a if TS-side parity is wanted.)
- **The self-tag regex.** `<intent emotion=([a-zA-Z_]+)>` already accepts arbitrary names; no regex change needed.
- **The strip behaviour.** `strip_intent_self_tag` is name-agnostic; it strips ANY `<intent emotion=...>` tag whether v1 or custom.
- **`AvatarTelemetryConfig`.** No new config flag. Opt-in is per-agent via `CrewProfile.custom_emotions`.
- **The divergence pipeline's scoring.** `match_score`, `signed_divergence`, and `magnitude` are computed against the RESOLVED v1 parent's rules — Counselor's "professional concern" is scored against the `concerned` axis. The agent's vocabulary surfaces in the result (`intent_emotion="professional_concern"`); the math uses the parent.
- **AD-731 attachment invariant.** This change does not touch the bus, RPC, or any attachment path.
- **`pyproject.toml`.** No new dependencies.

---

## Section 7 — Verification commands

```powershell
# Focused gate
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad737_emotion_taxonomy.py -v -n 0

# Existing AD-722a tests must continue to pass (backward compat)
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722a_divergence_detector.py tests/test_ad722a_telemetry.py -v -n 0

# Full Python gate
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile

# UI gate (should remain green — no UI change)
cd ui && npx vitest run
```

Live verification (operator-driven, post-commit):

1. Edit Counselor's seed profile in `config/manuals/` (or wherever the operator stores crew seeds) to declare:
   ```yaml
   custom_emotions:
     professional_concern:
       inherits: concerned
       pitch_shift: -0.05
       rate_shift: 0.0
       volume_shift: -0.05
   ```
2. Start the runtime; enable `avatar_telemetry.divergence_detection = True` in `config/system.yaml`.
3. DM Counselor. Confirm her reply contains `<intent emotion=professional_concern>` (which the server strips).
4. Check the journal: the divergence result should record `intent_emotion="professional_concern"`, scored against the `concerned` parent axis.
5. Optional: confirm the avatar telemetry snapshot shows `fired_rules` includes `"custom_professional_concern"`.

---

## Section 8 — Tracker updates

- **`PROGRESS.md`** — Wave 156 entry. Add tests count delta (+7 Python). Reference AD-737 + closure of [#612](https://github.com/seangalliher/ProbOS/issues/612).
- **`DECISIONS.md`** — Append AD-737 closure block. Cite: (a) per-agent palette (max 8), (b) `inherits` mandatory + must be v1, (c) shift bounds ±0.15, (d) v1 invariant preserved (manifest, enum, REQUIRED_INTENT_EMOTIONS untouched), (e) forward markers (TS-side parity AD-737a, anger/contempt axis expansion AD-737b if Captain wants), (f) parent references AD-722a, AD-722a-7.

---

## Revision (2026-05-13)

Pass-1 review addressed all three Required findings (R3-R5). All findings verified against live codebase before revision.

### R3 — CRITICAL: silent scoring corruption (now fixed)

The original Section 3b appended only `f"custom_{intent}"` to `fired_rules`. Verified analysis (manifest rule_name format is `intent_<v1>` per [ui/src/audio/modulation_manifest.json:19-26](ui/src/audio/modulation_manifest.json#L19-L26)):

1. `compute_divergence` filters `applied_set = frozenset(r for r in fired if r.startswith("intent_"))` ([divergence_detector.py:249](src/probos/avatars/divergence_detector.py#L249)). A `custom_X` tag is stripped → `applied_set = frozenset()`.
2. `expected = INTENT_EXPECTED_RULES.get("professional_concern", frozenset())` → also `frozenset()` because custom names are not in the v1 table.
3. The empty-vs-non-empty branches in `compute_divergence` produce `match_score = 0.0` whenever `applied_set` differs from `expected`. With the single-tag fix that would be every custom-emotion reply — maximum divergence on a perfectly-executed intent.

**Fix applied (two coordinated changes):**

- **Section 3b** (`apply_voice_modulation`): `fired.append(f"custom_{intent}")` → `fired.extend([rule["rule_name"], f"custom_{intent}"])`. Uses `rule["rule_name"]` (manifest-sourced, e.g. `"intent_concerned"`) rather than f-string interpolation for robustness against future rule-name renames.
- **Section 2c** (`apply_divergence_check`): pre-resolve `intent` → `resolved_v1` via `_resolve_intent_name`, pass `intent_emotion=resolved_v1` to `compute_divergence`. Then use `dataclasses.replace(result, intent_emotion=intent)` to restore the custom name on the returned `DivergenceResult` for downstream observability (journals, telemetry, snapshots).

**Verified end-to-end with the dual-tag shape**: with `fired_rules = (..., "intent_concerned", "custom_professional_concern")` AND `intent_emotion=resolved_v1="concerned"`, `expected = INTENT_EXPECTED_RULES["concerned"]` (e.g. `frozenset({"intent_concerned"})`), `applied_set = frozenset({"intent_concerned"})` (custom_X stripped by filter), Jaccard = 1.0, `match_score = 1.0`, `magnitude = 0.0`. Matches the literal-`concerned` reply score exactly — pinned by new test 8 below.

**Inherits resolution path verified**: `_resolve_intent_name(name, custom_emotions)` returns `name` if name is in `INTENT_EXPECTED_RULES` (v1 short-circuit), else looks up `custom_emotions[name].inherits`, else `None`. Defense-in-depth log fires on stale `inherits`. The `or intent` fallback in Section 2c covers the case where `_resolve_intent_name` returns `None` (which would only happen if `parse_intent_self_tag` accepted a name that doesn't resolve — shouldn't happen, but safe).

### R4 — `apply_divergence_check` integration: prose → SEARCH/REPLACE

Section 2c was prose-only ("Builder: grep and find") in pass-1; this was the highest-risk Required finding alongside R3. Replaced with explicit SEARCH/REPLACE block showing all four threaded changes: `custom_emotions` lookup, `parse_intent_self_tag` kwarg, `apply_voice_modulation` kwarg, pre-resolved `compute_divergence` + `dataclasses.replace` restore. Also corrected the call-site location claim: the prompt originally said `routers/agents.py` is the call site; verified via `grep parse_intent_self_tag\\(` (2 matches: definition at line 173, single call at line 356 in `apply_divergence_check` itself). No `routers/agents.py` call site exists.

### R5 — Test updates

- **Test 6** assertion updated. Was: "Assert `fired_rules` contains `\"custom_professional_concern\"`." Now: "must contain BOTH `\"intent_concerned\"` (required for `compute_divergence`'s `startswith(\"intent_\")` filter and the `match_score` numerator) AND `\"custom_professional_concern\"` (observability tag)." Critical-rationale comment added.
- **New test 8 — `test_custom_emotion_divergence_score_equals_parent`** added. Correctness invariant: a custom emotion that inherits from `concerned` with zero shifts must produce the same `match_score` / `signed_divergence` / `magnitude` as a literal `concerned` reply when scored over identical signals. Pins the v2-parity contract end-to-end through `apply_divergence_check`. Asserts `intent_emotion` carries the custom name in the custom case and the v1 name in the parent case.
- **Test count** updated: 7 → 8 (+ optional 9th). Header line ("**Estimated tests:** ~6-8") updated to "~7-9".

### Recommended (deferred)

The 7 Recommended findings from pass-1 are accept-as-shipped:
- `EmotionProfile` non-frozen, deferred `EmotionalIntent` import inside `__post_init__`, `_CUSTOM_NAME_RE` recompile cost — all flagged as future cleanup, not blockers.
- Test 7 fixture pattern — Builder picks the closest existing `tests/test_ad722a_*.py` fixture.
- `snapshot_for_agent` SEARCH block — already present in Section 3c (verified).
- Negative interaction test (custom + v1 in same convo) — covered by test 5's "without custom_emotions returns None for the custom name" assertion plus existing AD-722a backward-compat suite.
- `from_dict` round-trip — left as future hygiene AD if needed.

### Closing self-check

- `fired.append(f"custom_` (single-tag shape) — should appear 0 times in this prompt outside the Revision section. **Verified by grep:** the only remaining occurrence is in the Revision section's R3 explanation (referring to the buggy original shape). The Section 3b REPLACE block now uses `fired.extend([rule["rule_name"], f"custom_{intent}"])`.

No scope change. Files-touched list in Section 0 unchanged. AD-731 attachment invariant still respected. v1 manifest invariant still respected.
- **`docs/development/roadmap.md`** — Mark AD-737 shipped Wave 156; close [#612](https://github.com/seangalliher/ProbOS/issues/612).

---

## Section 9 — License Disposition

| Item | License | Posture |
|---|---|---|
| ProbOS code added | Apache 2.0 (matches repo) | New file `test_ad737_emotion_taxonomy.py` and edits to `crew_profile.py`, `divergence_detector.py`, `telemetry.py`, `cognitive_agent.py` carry the same license posture as the rest of the repo. |

- **No external code absorption.** No third-party module copied, no upstream pattern adapted, no model weights.
- **No new dependencies.** `pyproject.toml` is unchanged. All additions use stdlib (re, typing, dataclasses, json).
- **All-internal confirmed.** This is a Python-layer feature extension on top of the existing AD-722a divergence-detector pipeline.

---

## Forward markers

- **AD-737a (TS-side custom-emotion modulation parity).** Today the browser's `applyEmotionalModulation` consumes the manifest's v1 INTENT_RULES only — when an agent declares `professional_concern`, the browser-side rendered modulation reverts to the v1 `concerned` factors. The avatar's voice still sounds right because the SERVER's `apply_voice_modulation` (which fires for divergence comparison) computes the resolved factors; but a future AD could thread the resolved factors through the per-utterance payload so the TS path can apply them directly without depending on a parallel lookup. Out of scope for v1.
- **AD-737b (axis expansion).** v1 has no `anger` / `contempt` / `disgust` axes. If Captain wants Klingon "controlled fury" to score as `+anger` instead of inheriting from `formal`, a future AD adds those axes to the manifest as a new shared layer. Out of scope here — would require manifest schema review per [telemetry.py:155-160](src/probos/avatars/telemetry.py#L155-L160).
- **Custom-emotion proposal flow.** Today the operator hand-edits the seed file. A future AD could let an agent propose her own custom emotions (mirroring AD-718a voice-proposal). Out of scope.

---

## Acceptance criteria

- ✅ `EmotionProfile` dataclass exists in `crew_profile.py` with bounded shift fields.
- ✅ `CrewProfile.custom_emotions: dict[str, EmotionProfile]` field exists; max 8; no v1 collision.
- ✅ `parse_intent_self_tag` accepts a `custom_emotions` kwarg; returns the custom name when registered, `None` otherwise.
- ✅ `apply_voice_modulation` accepts `custom_emotions` and composes delta on top of parent v1 factors; clamped.
- ✅ `_build_intent_self_tag_instruction` injects v1 + custom names into the LLM prompt.
- ✅ 7 new Python tests, all passing.
- ✅ All existing AD-722a tests pass unchanged (backward compat).
- ✅ Full Python gate green; UI gate unchanged.
- ✅ `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` updated.
- ✅ GH issue [#612](https://github.com/seangalliher/ProbOS/issues/612) closed with the merge commit.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-13)

```
v1 emotion taxonomy (FIXED — do not extend):
  src/probos/avatars/divergence_detector.py:33-44   class EmotionalIntent(str, Enum)
                                                    WARM, CONCERNED, EXCITED, APOLOGETIC,
                                                    FORMAL, PLAYFUL, REASSURING, NEUTRAL
  src/probos/avatars/divergence_detector.py:58-67   INTENT_EXPECTED_RULES (keyed on str value)
  src/probos/avatars/divergence_detector.py:74-80   INTENT_DIRECTION (+1 / -1 / 0)
  src/probos/avatars/telemetry.py:99-103            _REQUIRED_INTENT_EMOTIONS tuple

Forward-marker references confirming this AD's identity:
  src/probos/avatars/telemetry.py:184-188           "per-agent palettes are forward marker AD-722a-3"
  src/probos/avatars/divergence_detector.py:36-37   "Per-agent palettes is forward marker AD-722a-3 (#612)"

Existing parsing + composition pipeline to extend:
  src/probos/avatars/divergence_detector.py:86-89   _TAG_RE = re.compile(r"<intent\s+emotion\s*=\s*([a-zA-Z_]+)\s*/?\s*>", ...)
                                                    Already accepts ANY [a-zA-Z_]+ name; no regex change needed.
  src/probos/avatars/divergence_detector.py:172+    def parse_intent_self_tag(text: str) -> str | None
  src/probos/avatars/telemetry.py:396-466           def apply_voice_modulation(profile, signals, intent=None) -> ModulationSnapshot
  src/probos/avatars/telemetry.py:719-727           caller in snapshot path (will pass custom_emotions=crew.custom_emotions)

Existing prompt-builder to extend:
  src/probos/cognitive/cognitive_agent.py:3175-3196   _build_intent_self_tag_instruction
                                                       (hardcoded v1 list at lines 3188-3193)

Existing CrewProfile + VoiceProfile patterns to mirror:
  src/probos/crew_profile.py:95-160                  @dataclass class VoiceProfile (validation in __post_init__)
                                                     CrewProfile field-validation pattern to mirror
```
