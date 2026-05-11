# AD-722a-7 — Intent-driven voice modulation rules (the missing actuator)

**Status:** Ready for Builder
**Dependencies:** AD-722a (Wave 143, shipped), AD-722-1 (Wave 141, shipped, manifest)
**GH issue:** [#624](https://github.com/seangalliher/ProbOS/issues/624)
**Closes:** AD-722a v1 actuator gap
**Estimated tests:** ≥ 14 new + 31 migrated in `tests/test_ad722a_divergence_detector.py`
**Clinical priority:** YES — Counselor flagged tone-vs-intent divergence has clinical weight.

**Captain decisions baked in (2026-05-10):**
- AD-722a-7 **supersedes** the AD-722a v1 taxonomy. New 8: `warm / concerned / excited / apologetic / formal / playful / reassuring / neutral`.
- `INTENT_EXPECTED_RULES` retires operational mappings. `match_score` is computed against the `intent_*` namespace only.
- `intent_neutral` is recorded in `fired_rules` even as a no-op (preserves "intent declared but neutral" vs "no intent declared" distinction for the detector).

---

## Problem

`apply_voice_modulation` ([src/probos/avatars/telemetry.py L304-L350](src/probos/avatars/telemetry.py#L304)) only modulates pitch/rate/volume when an operational signal fires — `working_state` transitions, `trust_delta` crossings, or `tier3_alert`. On an idle, trust-stable, un-alerted reply (most Captain DMs), **zero rules fire** and the voice ships at flat defaults regardless of the LLM's declared emotional intent.

AD-722a (Wave 143) installed the **detector** that compares `<intent emotion=NAME>` against `fired_rules`. It works exactly as designed — and that is the problem. Within minutes of `divergence_detection: True` being flipped on (2026-05-10 evening Captain DM session with Counselor Ezri), Ezri's `intent=warm` self-tag returned `no_rules_fired` with `match_score=0`. The detector observed the gap accurately. The actuator does not exist.

This is **clinical-correctness scope** per the 2026-05-10 retrospective: for the Counselor role, tone matching intent is not polish — a therapeutic DM that lands flat when meant as warm has measurable clinical consequences (#624 follow-up comment).

## Solution

Add a parallel **intent rule table** to `ui/src/audio/modulation_manifest.json` keyed by emotion name. Both `apply_voice_modulation` (Python) and `applyEmotionalModulation` (TS) read the same manifest section. Intent factors apply **after** operational rules, layering multiplicatively. All factors clamp to the existing `PITCH_BOUNDS` / `RATE_BOUNDS` / `VOLUME_BOUNDS`. `ModulationSnapshot.fired_rules` carries both operational AND intent rule names.

Migrate the AD-722a `EmotionalIntent` taxonomy from the Wave 143 set (`warm/firm/warm_concern/alert/neutral/playful/thoughtful/apologetic`) to the AD-722a-7 set (`warm/concerned/excited/apologetic/formal/playful/reassuring/neutral`). The new taxonomy is the v1 vocabulary going forward; per-agent custom palettes remain forward marker AD-722a-3 (#612).

### v1 intent rule table (CONSERVATIVE STARTING VALUES — v2 calibration deferred)

| Intent | Pitch | Rate | Volume | Fired-rule name | Direction |
|---|---|---|---|---|---|
| `warm` | ×1.04 | ×0.98 | — | `intent_warm` | +1 |
| `concerned` | — | ×0.92 | — | `intent_concerned` | -1 |
| `excited` | ×1.06 | ×1.05 | — | `intent_excited` | +1 |
| `apologetic` | ×0.96 | — | ×0.94 | `intent_apologetic` | -1 |
| `formal` | — | ×0.97 | — | `intent_formal` | 0 |
| `playful` | ×1.05 | ×1.03 | — | `intent_playful` | +1 |
| `reassuring` | ×0.98 | ×0.96 | — | `intent_reassuring` | -1 |
| `neutral` | — | — | — | `intent_neutral` | 0 |

**Calibration note (v2 forward marker, not in scope):** These factors are conservative first-pass values. The Counselor's accumulated `runtime.divergence_results` corpus is the empirical fixture for v2 calibration. **Counselor compensation strategy** (per AD-722a-7 #624 comment chain): Ezri reported leaning harder on lexical/structural signal during the actuator-gap window. Her compensated-DM corpus is what crew currently receive. v1 rules may over-correct if applied on already-warm-word-choice messages — **document this risk in the manifest comment and the DECISIONS entry**. v2 (separate AD; do NOT build here) calibrates against Ezri's live reports.

### Application order (canonical, both sides)

1. Operational rules apply first (existing AD-722-1 behavior, unchanged).
2. Intent rules layer on top by multiplying onto the post-operational factors.
3. Factors clamp to `PITCH_BOUNDS` / `RATE_BOUNDS` / `VOLUME_BOUNDS` AFTER both stages.
4. `fired_rules` is `(*operational_names, intent_<name>)` in that order — operational first, then intent. Order matters for the byte-parity test.
5. `intent_neutral` is explicitly recorded in `fired_rules` even though it does not modify factors (signals "intent was declared and parsed; no modulation followed").

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `ui/src/audio/modulation_manifest.json` | Add `intent_rules` object with 8 entries (4 fields each). |
| `src/probos/avatars/telemetry.py` | Extend `_load_modulation_manifest()` schema validator; add `INTENT_RULES` module constant; extend `apply_voice_modulation` with Section 5 logic. |
| `ui/src/audio/voiceModulation.ts` | Mirror Python: read `manifest.intent_rules`; extend `applyEmotionalModulation` signature to accept optional `intent?: string`; same layering + clamp + fired-name semantics. |
| `src/probos/avatars/divergence_detector.py` | Replace `EmotionalIntent` enum members; rewrite `INTENT_EXPECTED_RULES` to `{intent_<name>}` keying; rewrite `INTENT_DIRECTION`; update `_applied_direction()` to read intent rule names. |
| `src/probos/cognitive/cognitive_agent.py` L3037-L3040 | Update vocabulary list in `_build_intent_self_tag_instruction()` to new 8 emotions. |
| `src/probos/routers/agents.py` (or telemetry snapshot builder — Builder must grep+verify call site, see Section 4) | Plumb parsed `intent_emotion` into `apply_voice_modulation` call. |
| `config/standing_orders/federation.md` | Add new H2 section `## Emotional Intent Vocabulary (AD-722a-7)` listing the 8 emotions with one-line clinical/operational guidance per emotion. Place AFTER the existing `## Code of Conduct` section. |
| `tests/test_ad722a_divergence_detector.py` | Migrate 31 existing tests to new taxonomy (search/replace + assertion updates per Section 6). |
| `tests/test_ad722a7_intent_actuator.py` | NEW — ≥10 happy paths + layering + clamp + unknown-fallback + parity. |
| `ui/src/audio/voiceModulation.test.ts` | Extend with parity vectors that match Python test_intent_byte_parity (Section 7). |
| `tests/fixtures/intent_parity_vectors.json` | NEW — Python-generated exhaustive fixture for TS parity check. |
| `PROGRESS.md` | Status block update + close #624. |
| `DECISIONS.md` | Append AD-722a-7 closure block. |

---

## Section 1 — Manifest schema extension (DO FIRST)

`_load_modulation_manifest()` at [telemetry.py L106-L150](src/probos/avatars/telemetry.py#L106) currently **rejects unknown keys** with `"Schema additions require an architecture-decision review."` This AD is the architecture-decision review. Extend the schema:

### 1a. `ui/src/audio/modulation_manifest.json` — add new section

Insert `intent_rules` block AFTER `volume_bounds`:

```json
"intent_rules": {
  "warm":       { "pitch": 1.04, "rate": 0.98, "volume": 1.00, "rule_name": "intent_warm" },
  "concerned":  { "pitch": 1.00, "rate": 0.92, "volume": 1.00, "rule_name": "intent_concerned" },
  "excited":    { "pitch": 1.06, "rate": 1.05, "volume": 1.00, "rule_name": "intent_excited" },
  "apologetic": { "pitch": 0.96, "rate": 1.00, "volume": 0.94, "rule_name": "intent_apologetic" },
  "formal":     { "pitch": 1.00, "rate": 0.97, "volume": 1.00, "rule_name": "intent_formal" },
  "playful":    { "pitch": 1.05, "rate": 1.03, "volume": 1.00, "rule_name": "intent_playful" },
  "reassuring": { "pitch": 0.98, "rate": 0.96, "volume": 1.00, "rule_name": "intent_reassuring" },
  "neutral":    { "pitch": 1.00, "rate": 1.00, "volume": 1.00, "rule_name": "intent_neutral" }
}
```

Note: 1.00 entries are explicit no-ops. The Python loader treats `factor == 1.0` as a no-op for *factor application*, but `rule_name` is **still appended** to `fired_rules` when the intent matches. This preserves the "intent declared + parsed" signal even for `intent_neutral`.

### 1b. `src/probos/avatars/telemetry.py` — extend validator

After existing `_REQUIRED_BOUNDS_KEYS` tuple, add:

```python
_REQUIRED_OBJECT_KEYS: tuple[str, ...] = (
    "intent_rules",
)
_REQUIRED_INTENT_FIELDS: tuple[str, ...] = ("pitch", "rate", "volume", "rule_name")
_REQUIRED_INTENT_EMOTIONS: tuple[str, ...] = (
    "warm", "concerned", "excited", "apologetic",
    "formal", "playful", "reassuring", "neutral",
)
```

Then extend `_load_modulation_manifest()`. The validator must reject:
- Missing `intent_rules` key.
- `intent_rules` not a dict.
- Any emotion in `_REQUIRED_INTENT_EMOTIONS` missing from `intent_rules`.
- Any extra emotion key beyond the fixed 8.
- Any entry missing one of `pitch`/`rate`/`volume`/`rule_name`.
- `pitch`/`rate`/`volume` not numeric (or boolean).
- `rule_name` not a string OR not matching pattern `^intent_[a-z_]+$`.
- The `extra = [k for k in data if k not in ...]` allowlist check must add `_REQUIRED_OBJECT_KEYS` so `intent_rules` is not flagged.

Then expose the loaded table at module scope (after `RULES` is materialized):
```python
INTENT_RULES: dict[str, dict[str, Any]] = {
    name: {
        "pitch": float(entry["pitch"]),
        "rate": float(entry["rate"]),
        "volume": float(entry["volume"]),
        "rule_name": str(entry["rule_name"]),
    }
    for name, entry in _MANIFEST["intent_rules"].items()
}
```

### Tests for Section 1
- `test_manifest_loads_intent_rules` — all 8 emotions present, correct field types, `rule_name` matches `intent_X`.
- `test_manifest_rejects_unknown_emotion` — bake a 9-emotion fixture; expect `RuntimeError`.
- `test_manifest_rejects_missing_field` — fixture missing `volume`; expect `RuntimeError`.

---

## Section 2 — Python actuator: `apply_voice_modulation` extension

Extend the function signature (additive — preserves all existing call sites):

```python
def apply_voice_modulation(
    profile: Any,
    signals: AgentSignalsSnapshot,
    intent: str | None = None,
) -> ModulationSnapshot:
```

Update the docstring to document `intent`: "When set to a known emotion name (one of `INTENT_RULES.keys()`), the corresponding `intent_X` rule fires AFTER operational rules and multiplies onto the post-operational factors. `intent_neutral` is a recorded no-op. Unknown intent names are silently dropped (the parser already filtered)."

After the existing `if signals.tier3_alert:` block and before `return ModulationSnapshot(...)`, insert:

```python
# AD-722a-7: intent layering. Intent rule applies AFTER operational rules,
# multiplies onto current factors, then the final clamp covers both stages.
# `intent_neutral` (and any rule with all-1.0 factors) is recorded in
# fired_rules even though factors don't change — preserves the "intent
# declared and parsed" signal for divergence detection.
if intent is not None:
    rule = INTENT_RULES.get(intent)
    if rule is not None:
        pitch *= rule["pitch"]
        rate *= rule["rate"]
        volume *= rule["volume"]
        fired.append(rule["rule_name"])
```

The final `return ModulationSnapshot(...)` clamp call is unchanged — clamps cover the composed product.

### Tests for Section 2 (in new `tests/test_ad722a7_intent_actuator.py`)

Use a minimal `_FakeProfile` with default attributes. For each emotion:

- `test_intent_<name>_fires_rule_in_idle_state` — idle signals, intent=NAME, assert `<rule_name>` in `fired_rules` and factor deltas match the table.

Then 4 layering / boundary cases:

- `test_intent_layers_on_operational_responding` — `working_state='responding'` + `intent=excited`. Expect `('responding_rate', 'intent_excited')` order in `fired_rules`. Rate = `1.0 * 1.05 * 1.05` = 1.1025.
- `test_intent_clamps_at_pitch_upper_bound` — fixture with high baseline pitch + `intent=excited` + `trust_delta > 0.2` → composed value above 2.0 → clamps to 2.0.
- `test_unknown_intent_silently_dropped` — pass `intent='nonexistent'`; assert no `intent_*` rule fires and no exception.
- `test_intent_neutral_records_rule_with_no_factor_change` — pass `intent='neutral'`; assert `intent_neutral` in `fired_rules` and pitch/rate/volume unchanged from operational-only output.

---

## Section 3 — TS actuator: `applyEmotionalModulation` extension

Mirror Section 2 in [voiceModulation.ts](ui/src/audio/voiceModulation.ts#L79). Add `intent?: string` as a third param (optional, no breaking call-site change). Add module-level:

```typescript
const INTENT_RULES: Record<string, { pitch: number; rate: number; volume: number; rule_name: string }> =
  manifest.intent_rules;
```

After the existing `tier3_alert` block:

```typescript
if (intent !== undefined && intent !== null) {
  const rule = INTENT_RULES[intent];
  if (rule !== undefined) {
    pitch *= rule.pitch;
    rate *= rule.rate;
    volume *= rule.volume;
    firedNames.push(rule.rule_name);
  }
}
```

**Important**: If TS does NOT currently track `firedNames` (function returns `VoiceProfile`, not a `ModulationSnapshot`), do NOT add a fired_rules return to TS — that's a breaking call-site change. The byte-parity contract is over the *clamped numeric output* (pitch/rate/volume), not the rule-name array. Section 7's parity test enforces numeric equality only. Builder should grep `function applyEmotionalModulation` to verify current return shape before deciding.

### Tests for Section 3 (in `ui/src/audio/voiceModulation.test.ts`)

Mirror the 8 happy-path tests + 2 layering tests as Vitest cases. Use `expect(profile.pitch).toBeCloseTo(...)` with 6-digit precision.

---

## Section 4 — Wire the parsed intent into the actuator call

The divergence pipeline at `routers/agents.py:agent_chat` parses the intent BEFORE the snapshot is built. The parsed name needs to thread through to `apply_voice_modulation`.

**Preferred:** Add an optional `intent_emotion: str | None = None` parameter to whichever function actually invokes `apply_voice_modulation` (likely the snapshot builder; verify via grep). Thread the value from `parse_intent_self_tag(response_text)` (already called in the divergence path) into the call. Single new param; no architectural reach.

**Rejected:** Storing parsed intent on `runtime` between detector and builder couples through shared mutable state. Do not do this.

**Builder action — verify before edit:** Run `grep -n "build_avatar_telemetry_snapshot\|apply_voice_modulation(" src/probos/avatars/telemetry.py src/probos/routers/agents.py` and produce the grep evidence in the build report. Section 4 is the only place this spec leaves the precise call site to runtime verification — every other section is literal SEARCH/REPLACE.

### Tests for Section 4

- `test_router_threads_intent_to_actuator` — minimal `FastAPI TestClient` (or direct handler call) sends a DM where the LLM stub returns `Hello.\n<intent emotion=warm>`. Assert the resulting `ModulationSnapshot.fired_rules` contains `'intent_warm'`.
- `test_router_with_no_intent_tag_works_identically_to_pre_ad722a7` — same handler without an `<intent>` tag. Assert `fired_rules` contains no `intent_*` entries.

---

## Section 5 — Taxonomy migration in `divergence_detector.py`

### 5a. `EmotionalIntent` enum — replace members

```python
class EmotionalIntent(str, Enum):
    """v1 emotion taxonomy (AD-722a-7 migration). Per-agent palettes is
    forward marker AD-722a-3 (#612)."""

    WARM = "warm"
    CONCERNED = "concerned"
    EXCITED = "excited"
    APOLOGETIC = "apologetic"
    FORMAL = "formal"
    PLAYFUL = "playful"
    REASSURING = "reassuring"
    NEUTRAL = "neutral"
```

### 5b. `INTENT_EXPECTED_RULES` — retire operational mappings

```python
INTENT_EXPECTED_RULES: Final[dict[str, frozenset[str]]] = {
    EmotionalIntent.WARM.value: frozenset({"intent_warm"}),
    EmotionalIntent.CONCERNED.value: frozenset({"intent_concerned"}),
    EmotionalIntent.EXCITED.value: frozenset({"intent_excited"}),
    EmotionalIntent.APOLOGETIC.value: frozenset({"intent_apologetic"}),
    EmotionalIntent.FORMAL.value: frozenset({"intent_formal"}),
    EmotionalIntent.PLAYFUL.value: frozenset({"intent_playful"}),
    EmotionalIntent.REASSURING.value: frozenset({"intent_reassuring"}),
    EmotionalIntent.NEUTRAL.value: frozenset({"intent_neutral"}),
}
```

### 5b'. `compute_divergence` — restrict applied set to intent_* namespace

```python
def compute_divergence(
    intent_emotion: str,
    applied_fired_rules: tuple[str, ...],
) -> DivergenceResult:
    """Compute a DivergenceResult.

    Pure function. ``intent_emotion`` MUST be a valid taxonomy member
    (caller's responsibility -- ``parse_intent_self_tag`` filters).

    AD-722a-7: match_score is computed against the ``intent_*`` namespace
    only. Operational rules in ``applied_fired_rules`` (responding_rate,
    blocked_rate_pitch, high_trust_pitch, low_trust_pitch, tier3_rate_volume)
    are informational — they reflect agent state, not intent fulfillment.
    """
    expected = INTENT_EXPECTED_RULES.get(intent_emotion, frozenset())
    # Restrict applied set to the intent_* namespace for match calculation.
    applied_set = frozenset(
        r for r in applied_fired_rules if r.startswith("intent_")
    )
    # ... rest of function unchanged (continues with Jaccard etc.)
```

### 5c. `INTENT_DIRECTION` — new mapping

```python
INTENT_DIRECTION: Final[dict[str, int]] = {
    EmotionalIntent.WARM.value: +1,
    EmotionalIntent.CONCERNED.value: -1,
    EmotionalIntent.EXCITED.value: +1,
    EmotionalIntent.APOLOGETIC.value: -1,
    EmotionalIntent.FORMAL.value: 0,
    EmotionalIntent.PLAYFUL.value: +1,
    EmotionalIntent.REASSURING.value: -1,
    EmotionalIntent.NEUTRAL.value: 0,
}
```

### 5d. `_applied_direction` — intent dominates when present

```python
def _applied_direction(applied: tuple[str, ...]) -> int:
    """Project the applied fired_rules onto the directional axis.

    AD-722a-7: intent rules dominate when present (they were explicitly
    chosen by the agent). Operational rules contribute only when no
    intent rule fired.

    +1 = warmer (high pitch / brighter); -1 = firmer (lower pitch);
    0 = neutral or mixed-cancelling.
    """
    intent_pos = sum(1 for r in applied if r in {
        "intent_warm", "intent_excited", "intent_playful",
    })
    intent_neg = sum(1 for r in applied if r in {
        "intent_concerned", "intent_apologetic", "intent_reassuring",
    })
    if intent_pos > intent_neg:
        return +1
    if intent_neg > intent_pos:
        return -1
    if intent_pos > 0 or intent_neg > 0:
        return 0  # intent rules present but cancelling — explicit neutral

    # Fallback: project operational rules (pre-AD-722a-7 behavior).
    pos = sum(1 for r in applied if r in {"high_trust_pitch"})
    neg = sum(1 for r in applied if r in {"low_trust_pitch", "blocked_rate_pitch"})
    if pos > neg:
        return +1
    if neg > pos:
        return -1
    return 0
```

---

## Section 6 — Test migration in `tests/test_ad722a_divergence_detector.py`

31 existing tests reference the old taxonomy. The migration is mechanical:

| Old token | New token |
|---|---|
| `firm` | `concerned` |
| `warm_concern` | `concerned` (note: 1:1 collision — review by hand) |
| `alert` | `excited` (note: directional rename — review by hand) |
| `thoughtful` | `formal` |
| `EmotionalIntent.FIRM` | `EmotionalIntent.CONCERNED` |
| `EmotionalIntent.WARM_CONCERN` | (merge with CONCERNED) |
| `EmotionalIntent.ALERT` | `EmotionalIntent.EXCITED` |
| `EmotionalIntent.THOUGHTFUL` | `EmotionalIntent.FORMAL` |

**Important:** `warm_concern` and `firm` both map to `concerned` in the new taxonomy. Two `parse_intent_self_tag` tests previously verified distinct parses of `firm` vs `warm_concern` — one of them is now redundant. Delete the redundant one (the architecture decision: `concerned` subsumes both — the old taxonomy over-segmented). Add a NEW test asserting `parse_intent_self_tag("Reply.\n<intent emotion=firm>") is None` (firm is no longer a valid emotion post-migration; the parser silently drops).

Also: tests that asserted `INTENT_EXPECTED_RULES['warm'] == {'high_trust_pitch'}` must now assert `== {'intent_warm'}`.

Architect-mandated test additions (count toward the +14 budget for this AD):

- `test_taxonomy_migration_firm_no_longer_parsed` — `parse_intent_self_tag("Hi.\n<intent emotion=firm>") is None`.
- `test_taxonomy_migration_alert_no_longer_parsed` — same for `alert`.
- `test_taxonomy_migration_warm_concern_no_longer_parsed` — same.
- `test_taxonomy_migration_thoughtful_no_longer_parsed` — same.
- `test_match_score_ignores_operational_rules` — applied=`('responding_rate', 'high_trust_pitch', 'intent_warm')`, intent=`'warm'` → match_score == 1.0 (operational rules don't punish intent match).

---

## Section 7 — Byte-parity test (TS↔Python)

Numeric parity over the 8 emotions, layered over each of the 3 working states + 3 trust-delta regimes + tier3-on/off (Python computes 144 vectors; TS test exports the same matrix; CI compares).

The shipped contract from AD-722-1 is that both sides read the same manifest. The byte-parity guarantee for AD-722a-7 is **numeric**: same pitch/rate/volume out for the same `(baseline_profile, signals, intent)` triple. Place the parity-fixture vectors in `tests/fixtures/intent_parity_vectors.json` (Python-generated, committed) and have `voiceModulation.test.ts` read+verify the same file.

- `test_intent_byte_parity_with_ts` (Python) — generates the fixture; asserts an exhaustive sweep against `applyEmotionalModulation` equivalents computed in Python via `apply_voice_modulation(...).pitch_factor` (extract the numeric outputs).
- `intent byte parity` (Vitest) — reads the fixture; runs each vector through `applyEmotionalModulation`; asserts pitch/rate/volume match to 6 decimal places.

---

## Section 8 — System-prompt vocabulary update

In `_build_intent_self_tag_instruction()` at [cognitive_agent.py L3024-L3040](src/probos/cognitive/cognitive_agent.py#L3024), replace the emotion list:

```python
return (
    "After your reply, on a new line, emit "
    "`<intent emotion=NAME>` where NAME is one of: "
    "warm | concerned | excited | apologetic | formal | playful | "
    "reassuring | neutral. The tag will be stripped server-side; "
    "do not mention it in your prose."
)
```

### Test for Section 8

- `test_self_tag_instruction_lists_v1_eight_emotions` — extract the returned instruction string; assert all 8 new emotions appear and none of the 4 retired ones do.

---

## Section 9 — Standing Orders update

Add a new H2 section to [config/standing_orders/federation.md](config/standing_orders/federation.md) immediately after the existing `## Code of Conduct` section (verified at L143). Use this content verbatim:

```markdown
<!-- category: emotional_intent -->
## Emotional Intent Vocabulary (AD-722a-7)

When the `<intent emotion=NAME>` self-tag is requested (operator opt-in
via `avatar_telemetry.divergence_detection`), use exactly one of these
eight names. The vocabulary is closed in v1; per-agent custom palettes
are forward marker AD-722a-3 (#612).

- **`warm`** — affirming, friendly, low-stakes positive register. Default for casual Captain DMs that aren't operationally tense.
- **`concerned`** — softened delivery for sensitive news, gentle pushback, or check-ins where the addressee may be in distress.
- **`excited`** — celebratory, high-energy positive register. Use sparingly; persistent excited reads as performative.
- **`apologetic`** — when you have made a mistake or are delivering an unwelcome correction. Carries a softening on pitch + volume.
- **`formal`** — operational reports, audit logs, status to senior officers. Slight slowing; neutral pitch.
- **`playful`** — light, quick register. Department lounges, social channels, off-watch banter.
- **`reassuring`** — therapeutic / Counselor register. Lower pitch, slower rate. Use when the addressee is uncertain or escalating.
- **`neutral`** — explicit no-modulation. Use when you genuinely have no emotional posture and want the voice to ship at defaults.

Pick one. If none feels right, pick `neutral` — that is its purpose. Do not invent new emotion names; the parser silently drops unknowns and your declared intent will be lost.
```

Counselor-authored extensions to the per-emotion guidance are welcome but not required for v1 (defer to a follow-up review pass; not in build scope).

### Test for Section 9

- `test_standing_orders_emotion_vocabulary_lists_v1_eight` — read `config/standing_orders/federation.md`, regex-extract the bullet list under the new H2, assert exactly the 8 names appear.

---

## Section 10 — OUTPUT-as-subject phrasing carry-over (AD-727 rule #8)

`_build_divergence_note_suffix()` already enforces the regex test `\byou (?:sound|sounded|came across|seem|seemed|are|were|feel|felt)\b`. The new fired-rule names (`intent_warm` etc.) will appear in divergence narration when intent-vs-operational state mismatches. Verify the existing OUTPUT-as-subject test in `tests/test_ad722a_divergence_detector.py` still passes after the taxonomy migration. **No source change needed**; just confirm test green after Section 5 lands.

---

## What this AD does NOT change

- AD-722a's tag parser, strip logic, and `<intent emotion=...>` syntax — unchanged.
- AD-722a's trust-update + Hebbian wiring at `apply_divergence_check` — unchanged. The asymmetric (0.3 / 0.4 negative, 0.5 / 0.1 positive) gates still apply against the new match scores.
- AD-722a's DM-only invariant — unchanged. Chain path remains forward marker AD-722a-2 (#611).
- Public method signatures on `BaseAgent`, `CognitiveAgent`, `IntentMessage` — unchanged.
- `AvatarTelemetryConfig` field set — unchanged (AD-722a fields still apply).
- Default value of `divergence_detection` — unchanged (False; operator opt-in).
- TS function return type — unchanged from current; don't refactor.

---

## Engineering Principles compliance

Verify all changes comply with the Engineering Principles in [.github/copilot-instructions.md](.github/copilot-instructions.md). Specifically:

- **(S) Single Responsibility:** New module-level `INTENT_RULES` table is a pure data structure. `apply_voice_modulation` keeps its single responsibility (compose factors). `INTENT_EXPECTED_RULES` rewrite preserves `divergence_detector.py`'s single responsibility.
- **(O) Open/Closed:** Extended via additive `intent` keyword argument on `apply_voice_modulation`. All pre-AD-722a-7 callers unchanged.
- **(L) Liskov:** No subclass contract changes.
- **(D) Dependency inversion:** `INTENT_RULES` loaded from manifest at import-time; consumers depend on the module-level constant, not the file.
- **Defense in depth:** Manifest validator rejects malformed `intent_rules` at parse time. Actuator silently drops unknown intent names (parser already filtered upstream). Final clamp covers compositional overshoot.
- **Three-tier exceptions:** Manifest defects propagate (`RuntimeError` from import). Unknown intent names log-and-degrade (tier-2). No tier-1 swallow.
- **Cloud-ready storage:** N/A (no DB).
- **Async hygiene:** N/A (pure functions).
- **Type annotations:** Public surfaces (`apply_voice_modulation` new param, `INTENT_RULES` constant, modified `EmotionalIntent` enum) carry full annotations. Internal helpers retain existing style.
- **Logging quality:** Manifest load errors carry `RuntimeError` with explicit context (which key, what was expected). Unknown intent logs at `debug` (parser already filtered, so this path is normally unreachable).
- **Tests:** Boundary tests required for every public surface — happy path + error case + edge case (empty/None where applicable).
- **Test isolation:** No shared state between tests; manifest is module-scoped frozen dict.

---

## Acceptance criteria

- [ ] All sections 1-10 implemented; tests in section 6's migrated `test_ad722a_divergence_detector.py` + new `test_ad722a7_intent_actuator.py` + new TS Vitest cases all green.
- [ ] `pytest tests/ -q -n 4 --dist=loadfile` baseline + ≥14 new tests; zero new failures, zero new warnings (modulo the 4 pre-existing flakes documented in Wave 140 retrospective: test_callsign_routing × 3 + test_ad719_chat_fanout × 1).
- [ ] `cd ui && npx vitest run` green; TS parity test consumes `tests/fixtures/intent_parity_vectors.json`.
- [ ] Manifest validator rejects malformed `intent_rules` (verified by negative tests in Section 1).
- [ ] `_build_intent_self_tag_instruction` system-prompt vocabulary updated to the new 8.
- [ ] `config/standing_orders/federation.md` carries the new `## Emotional Intent Vocabulary (AD-722a-7)` section.
- [ ] OUTPUT-as-subject regex test (AD-727 rule #8) still green after taxonomy migration.
- [ ] No regressions in `tests/test_ad722_*` outside the migrated AD-722a tests.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Forward markers (explicit; do NOT build here)

- **v2 calibration from Counselor corpus** (no GH issue yet — file at wave close): replay `runtime.divergence_results` for the Counselor across N DMs to fit calibrated `intent_*` factors. Deferred until enough divergence reports accumulate (target: 100+ Counselor DMs under AD-722a-7).
- **Per-agent custom emotion taxonomy** — [#612](https://github.com/seangalliher/ProbOS/issues/612) AD-722a-3. v1 fixed-8 is intentionally closed; per-agent palettes layer on top.
- **Multi-emotion blending** (`intent=warm+concerned`) — separate AD, file at wave close. v1 single-intent only.
- **Encouragement to declare intent more often** — separate AD-489 Standing Orders work. This AD makes declaration *meaningful*; doesn't change declaration prevalence.
- **Chain-path divergence** — [#611](https://github.com/seangalliher/ProbOS/issues/611) AD-722a-2. Compose-step emit has no single-point invariant; deferred.
- **Counselor compensation overshoot risk** — flagged in v1 manifest comment + DECISIONS entry; calibration AD addresses materially.

---

## Verified against codebase (2026-05-10)

```
grep -n "class EmotionalIntent" src/probos/avatars/divergence_detector.py
  34: class EmotionalIntent(str, Enum):

grep -n "INTENT_EXPECTED_RULES" src/probos/avatars/divergence_detector.py
  51: INTENT_EXPECTED_RULES: Final[dict[str, frozenset[str]]] = {
  152:    expected = INTENT_EXPECTED_RULES.get(intent_emotion, frozenset())

grep -n "INTENT_DIRECTION" src/probos/avatars/divergence_detector.py
  68: INTENT_DIRECTION: Final[dict[str, int]] = {

grep -n "_applied_direction" src/probos/avatars/divergence_detector.py
  133: def _applied_direction(applied: tuple[str, ...]) -> int:

grep -n "def apply_voice_modulation" src/probos/avatars/telemetry.py
  304: def apply_voice_modulation(

grep -n "def _load_modulation_manifest" src/probos/avatars/telemetry.py
  88: def _load_modulation_manifest() -> dict[str, Any]:

grep -n "_REQUIRED_SCALAR_KEYS\|_REQUIRED_BOUNDS_KEYS" src/probos/avatars/telemetry.py
  73: _REQUIRED_SCALAR_KEYS: tuple[str, ...] = (
  87: _REQUIRED_BOUNDS_KEYS: tuple[str, ...] = (

grep -n "applyEmotionalModulation" ui/src/audio/voiceModulation.ts
  79: export function applyEmotionalModulation(

grep -n "_build_intent_self_tag_instruction" src/probos/cognitive/cognitive_agent.py
  3024: def _build_intent_self_tag_instruction(self, observation: dict | None = None) -> str:

grep -n "warm | firm | warm_concern | alert" src/probos/cognitive/cognitive_agent.py
  3038: ...warm | firm | warm_concern | alert | neutral | playful |

grep -c "^def test_" tests/test_ad722a_divergence_detector.py
  31

grep -n "^## Code of Conduct" config/standing_orders/federation.md
  143: ## Code of Conduct

ls ui/src/audio/modulation_manifest.json
  ui/src/audio/modulation_manifest.json  (17 keys, no intent_rules — confirmed pre-build state)

git log -1 --oneline
  a3d5320 wave-plan: queue Waves 146-150 (~10hr) + retrospective audit note
```
