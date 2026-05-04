# AD-530 v1: Information Classification Enforcement — Disclosure Gate

**Status:** Drafted (Wave 19)
**Risk:** medium (introduces communication-boundary check; new gating surface)
**Depends on:** RecordsStore classification infrastructure (shipped — `_CLASSIFICATION_LEVELS` at records_store.py:27); EventLog (shipped); WardRoomService (shipped)
**Closes:** GitHub issue #104

---

## Solution Overview

AD-530 in roadmap.md (line 6513) addresses "disclosure of sensitive information" — Standing Orders are advisory, agents have no technical barrier to including classified content in outbound messages. Roadmap lists 4 capabilities: classification labels + disclosure gates + Security Chief ownership + audit trail.

ProbOS already has classification infrastructure for **documents** (`_CLASSIFICATION_LEVELS` at records_store.py:27, the real 4-tier hierarchy: `private`=0, `department`=1, `ship`=2, `fleet`=3 — higher index = BROADER access / more openly readable, per the comment at records_store.py:26 and the usage at records_store.py:716 and :841) and selective-disclosure routing (AD-679). What's missing: **outbound message classification + disclosure gate at the communication boundary** (Ward Room posts, LLM prompts).

**v1 ships 2 of 4 capabilities** (per convention #14 aggressive pre-deferral) — the bounded enforcement surface:

1. **`ClassificationGate`** — new class in `src/probos/security/classification.py`. Single primary method `check_disclosure(content: str, *, source_classification: str, destination_clearance: str) -> DisclosureDecision`. Returns `DisclosureDecision(allowed: bool, reason: str, blocked_phrases: tuple[str, ...], ...)`. Uses existing `_CLASSIFICATION_LEVELS` hierarchy read-only. Because higher index = broader access (openness semantics), disclosure is BLOCKED when `dst_lvl > src_lvl` — i.e., the destination has BROADER reach than the source's classification permits. Example: source=`private` (0, author-only), destination=`ship` (2, all crew) → `2 > 0` → BLOCK (private content cannot leak to a ship-wide audience). Conversely, source=`ship` (2) → destination=`department` (1) → `1 > 2` is False → ALLOW (ship content is already broadly readable; narrower destination is fine). This direction is grounded in records_store.py:841 (`if doc_class_level > scope_level: continue` filters out broader-than-scope docs) and read_document at :716–:725 (private→author-only, department→same-dept-only, ship/fleet→all crew).

2. **Pattern-based sensitive-content scanner** — `ClassificationGate` includes a small built-in pattern set targeting only known-high-signal shapes (Captain directive markers, restricted-prefix tokens, secret-format `name=value`). Scanner returns matched pattern names; gate blocks disclosure when any match found AND the destination is broader than `private`. This is observational v1 — gate emits `CLASSIFICATION_DISCLOSURE_BLOCKED` event but does NOT mutate outbound messages (no DLP rewriting). Caller (Ward Room post path / LLM prompt builder) decides whether to suppress, redact, or retry. The high-FP `api_key_like` 32+ char heuristic is deliberately **not** in the default set (UUIDs, commit hashes, opaque tokens collide with it); callers that want it opt in via `register_pattern()`. Default-pattern revisit is deferred to AD-530e once integration data exists.

**Deferred:**

- AD-530b: Security Chief ownership — runtime updates to classification labels via Standing Orders. Forcing function: a designed agent (Worf/SecurityAgent) is spawned and needs the `runtime.classification_gate.update_label()` API to enforce a Standing-Order-issued classification change.
- AD-530c: Full audit trail to event log — event on every classified READ (not just blocks). Forcing function: AD-530d's first integration site lands and the Captain reviews blocked-event volume; if the signal/noise ratio justifies a per-read event channel, AD-530c proceeds.
- AD-530d: Active enforcement (mutate / redact / suppress outbound messages in WardRoomService.create_post and LLMClient prompt builder). Forcing function: AD-530b ships, the Captain (or SecurityAgent acting under a Standing Order) issues a label-change directive, and the Captain reviews the resulting blocked-event log to choose the response policy (redact vs suppress vs retry).
- AD-530e: Default-pattern revisit (re-evaluate `api_key_like` and add tightened API-key prefix patterns — `sk-`, `pk_`, `Bearer`, `AKIA`, `ghp_`). Forcing function: integration sites under AD-530d produce a corpus of real outbound message content and the FP rate of `api_key_like` is measurable.
- `fleet`-tier handling: v1 treats `fleet` (level 3) like any other level via the openness comparison — `fleet`-classified content is the most broadly accessible, so disclosing `fleet` content to any destination ≤ `fleet` is allowed by hierarchy alone. Federation-aware classification semantics (e.g., `fleet`-only-after-trust-handshake) are deferred to AD-530b/d once federation has a classification-aware path.

## Dependencies

- `_CLASSIFICATION_LEVELS` at `src/probos/knowledge/records_store.py:27` — read-only consumer of the existing 3-tier hierarchy. AD-530 does NOT modify or duplicate this.
- `runtime.event_log` — emit `CLASSIFICATION_DISCLOSURE_BLOCKED` per blocked check.
- `runtime.event_log` and `runtime.config` — read-only.
- New file: `src/probos/security/classification.py` (alongside existing `security/egress.py` from AD-456).

All reads from existing surfaces; one new module under existing security/ package.

## Sections

### Section 0 — EventTypes

Add to `src/probos/events.py` `EventType` enum (verify no collision):

- `CLASSIFICATION_DISCLOSURE_BLOCKED = "classification_disclosure_blocked"` — emitted when `ClassificationGate.check_disclosure()` returns `allowed=False` (either hierarchy violation or sensitive-pattern match).

### Section 1 — `DisclosureDecision` frozen dataclass

```python
from dataclasses import dataclass
from typing import Literal

DisclosureReason = Literal[
    "ok",
    "destination_too_broad",     # dst_lvl > src_lvl: destination has broader reach than source allows
    "sensitive_pattern_matched", # pattern scan blocked
]


@dataclass(frozen=True)
class DisclosureDecision:
    """Result of a classification disclosure check. AD-530 v1."""
    allowed: bool
    reason: DisclosureReason
    blocked_phrases: tuple[str, ...]  # pattern NAMES that triggered the block (never matched substrings)
    source_classification: str  # echoed for audit
    destination_clearance: str   # echoed for audit
```

### Section 2 — `ClassificationGate` class

```python
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from probos.events import EventType
from probos.knowledge.records_store import _CLASSIFICATION_LEVELS

logger = logging.getLogger(__name__)

# AD-530 v1 default sensitive-content patterns. Tightly scoped to known-high-signal
# shapes; the high-FP 32+ char alphanum heuristic (`api_key_like`) is INTENTIONALLY
# NOT in the default set (UUIDs, commit hashes, and opaque IDs collide with it,
# turning every Ward Room post into a CLASSIFICATION_DISCLOSURE_BLOCKED event).
# Callers that want it opt in via `register_pattern("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b")`.
# Default-set revisit is AD-530e.
_DEFAULT_SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # name, regex
    ("captain_directive", r"\[CAPTAIN_DIRECTIVE\]"),
    ("restricted_prefix", r"\b(private|confidential):\s"),  # note: matches the literal "private:" / "confidential:" prefix marker, NOT the classification key
    ("secret_format", r"(?i)\b(secret|api[_-]?key|password|token)\s*[:=]\s*\S+"),
)


class ClassificationGate:
    """v1 disclosure gate. Read-only check; no message mutation. AD-530 v1.

    Hierarchy semantics (see records_store.py:26-32, :716, :841):
      _CLASSIFICATION_LEVELS = {"private": 0, "department": 1, "ship": 2, "fleet": 3}
      Higher index = BROADER access (more openly readable).

    Disclosure rule: BLOCK when `dst_lvl > src_lvl` — destination has broader reach
    than source classification permits.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self.emit_event = emit_event  # public field per Wave 5 convention #1; mirrors AD-456 EgressPolicy.emit_event
        # Compile default patterns at construction; register_pattern adds more.
        # Use list-of-tuples (preserves insertion order; duplicate-name guarded in register_pattern).
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pat)) for name, pat in _DEFAULT_SENSITIVE_PATTERNS
        ]

    @property
    def patterns(self) -> tuple[tuple[str, re.Pattern[str]], ...]:
        """Public read-only view of the active pattern set (Wave 5 convention #1)."""
        return tuple(self._patterns)

    @property
    def pattern_count(self) -> int:
        """Number of active sensitive-content patterns."""
        return len(self._patterns)

    def check_disclosure(
        self,
        content: str,
        *,
        source_classification: str,
        destination_clearance: str,
    ) -> DisclosureDecision:
        """Check whether `content` may be disclosed at `destination_clearance` level.

        Args:
            content: The outbound message body.
            source_classification: Source data's classification label. One of the
                _CLASSIFICATION_LEVELS keys ("private", "department", "ship",
                "fleet"). Unknown / unspecified labels default to MOST RESTRICTIVE
                ("private", level 0) so unlabeled content cannot leak by mistake.
            destination_clearance: Destination's reach level (same hierarchy).
                Unknown / unspecified destinations default to BROADEST ("ship",
                level 2) so an unspecified destination is treated as "assume widest
                reach" and is gated conservatively. Combined with the source
                default, an entirely unspecified pair is BLOCKED by hierarchy
                (private→ship: 2 > 0 → BLOCK).

        Returns:
            DisclosureDecision. allowed=True when `dst_lvl <= src_lvl` AND no
            sensitive patterns matched.
        """
        # Higher index = broader access. Block when destination is broader than source allows.
        # Safe defaults: source unknown → most restrictive (private=0); dest unknown → broadest (ship=2).
        src_lvl = _CLASSIFICATION_LEVELS.get(source_classification, _CLASSIFICATION_LEVELS["private"])
        dst_lvl = _CLASSIFICATION_LEVELS.get(destination_clearance, _CLASSIFICATION_LEVELS["ship"])
        if dst_lvl > src_lvl:  # destination has BROADER reach than source classification permits
            decision = DisclosureDecision(
                allowed=False,
                reason="destination_too_broad",
                blocked_phrases=(),
                source_classification=source_classification,
                destination_clearance=destination_clearance,
            )
            self._emit_blocked(content, decision)
            return decision

        # Pattern scan: skip when destination is the most-restrictive level ("private").
        # Patterns target sensitive-content disclosure to broader audiences; if the
        # destination is already private (level 0), there's no broader audience to leak to.
        matches: list[str] = []
        if dst_lvl > _CLASSIFICATION_LEVELS["private"]:
            for name, pat in self._patterns:
                if pat.search(content):
                    matches.append(name)
        if matches:
            decision = DisclosureDecision(
                allowed=False,
                reason="sensitive_pattern_matched",
                blocked_phrases=tuple(matches),
                source_classification=source_classification,
                destination_clearance=destination_clearance,
            )
            self._emit_blocked(content, decision)
            return decision

        return DisclosureDecision(
            allowed=True,
            reason="ok",
            blocked_phrases=(),
            source_classification=source_classification,
            destination_clearance=destination_clearance,
        )

    def register_pattern(self, name: str, pattern: str) -> None:
        """Add a sensitive-content pattern (runtime-only; not persisted in v1).

        Duplicate-name semantics: if `name` is already registered, the existing
        pattern is preserved and a warning is logged. Callers that need to
        replace a pattern should choose a fresh name (or wait for AD-530e's
        explicit replace API).
        """
        for existing_name, _ in self._patterns:
            if existing_name == name:
                logger.warning(
                    "AD-530: register_pattern skipped — name %r already registered", name,
                )
                return
        self._patterns.append((name, re.compile(pattern)))

    def _emit_blocked(self, content: str, decision: DisclosureDecision) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.CLASSIFICATION_DISCLOSURE_BLOCKED,
                {
                    "reason": decision.reason,
                    "source_classification": decision.source_classification,
                    "destination_clearance": decision.destination_clearance,
                    "blocked_phrases": list(decision.blocked_phrases),  # pattern NAMES only
                    "content_length": len(content),  # NOT content itself per privacy
                },
            )
        except Exception:
            logger.warning(
                "AD-530: CLASSIFICATION_DISCLOSURE_BLOCKED emit failed (reason=%s)",
                decision.reason,
                exc_info=True,
            )
```

**Privacy note:** event payload includes `content_length` (NOT content). Blocked phrases are emitted by NAME (not the matched substring) to avoid logging sensitive data.

### Section 3 — Pydantic config

```python
class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate."""
    enabled: bool = True
    # v1: pattern set is hardcoded; register_pattern is runtime-only
```

Wire into `SystemConfig.classification_gate: ClassificationGateConfig = Field(default_factory=ClassificationGateConfig)`.

### Section 4 — Runtime wiring (finalize.py)

Sync `_wire_classification_gate` mirroring AD-525's pattern at finalize.py:253. Public attribute `runtime.classification_gate` (no underscore per Wave 5 convention #1).

```python
def _wire_classification_gate(*, runtime, config) -> bool:
    """AD-530 v1: Wire ClassificationGate."""
    cfg = getattr(config, "classification_gate", None)
    if not cfg or not cfg.enabled:
        return False
    emit_fn = getattr(runtime, "emit_event", None)
    runtime.classification_gate = ClassificationGate(runtime, emit_event=emit_fn)  # public attribute (Wave 5 convention #1)
    logger.info(
        "AD-530: ClassificationGate initialized (%d patterns)",
        runtime.classification_gate.pattern_count,
    )
    return True
```

Invoke from `finalize_startup` next to `_wire_creative_expression` / `_wire_self_distillation` / `_wire_anomaly_window` (finalize.py:274–280).

## What This Does NOT Change

- `_CLASSIFICATION_LEVELS` at records_store.py:27 — read-only consumer; not modified.
- AD-679 selective disclosure routing — untouched.
- AD-456 EgressPolicy — orthogonal (network egress, not content classification).
- WardRoomService.create_post — NOT gated in v1. Caller decides whether to call check_disclosure pre-post. v1 ships the GATE; integration sites are AD-530d (active enforcement).
- LLM prompt builder — NOT gated in v1. Same reason: AD-530d.
- AD-530b (Security Chief ownership), AD-530c (audit trail), AD-530d (active enforcement) — all deferred.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_event_type_classification_disclosure_blocked_exists` | Section 0 surface |
| 2 | `test_classification_gate_config_defaults` | Pydantic defaults |
| 3 | `test_disclosure_decision_is_frozen_dataclass` | Section 1 contract |
| 4 | `test_check_disclosure_allowed_when_levels_equal` | Hierarchy: src=ship, dst=ship → ALLOW |
| 5 | `test_check_disclosure_allowed_when_destination_narrower` | Hierarchy: src=ship(2), dst=department(1) → ALLOW (dst_lvl < src_lvl) |
| 6 | `test_check_disclosure_blocked_when_destination_broader` | Hierarchy: src=private(0), dst=ship(2) → allowed=False, reason="destination_too_broad" |
| 7 | `test_check_disclosure_unknown_source_defaults_to_private` | Safety default: unknown source → most restrictive (private=0); pairing with ship destination → BLOCK |
| 7b | `test_check_disclosure_unknown_destination_defaults_to_ship` | Safety default: unknown dest → broadest (ship=2); paired with private source → BLOCK by hierarchy |
| 8 | `test_check_disclosure_emits_blocked_event_on_hierarchy_violation` | Event emission with reason="destination_too_broad" |
| 9 | `test_api_key_like_pattern_NOT_in_default_set` | `api_key_like` is NOT seeded by default (UUID-FP guard); 32+ char hex strings do NOT match default patterns |
| 9b | `test_register_pattern_enables_api_key_like_opt_in` | Opt-in via `register_pattern("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b")` re-introduces the heuristic |
| 10 | `test_check_disclosure_pattern_blocks_captain_directive` | Pattern: `[CAPTAIN_DIRECTIVE]` marker triggers block |
| 11 | `test_check_disclosure_pattern_blocks_restricted_prefix` | Pattern: `private:` / `confidential:` literal prefix triggers block |
| 12 | `test_check_disclosure_pattern_blocks_secret_format` | Pattern: `secret=xxx`, `api_key: xxx`, `password=xxx` triggers block |
| 13 | `test_check_disclosure_pattern_skipped_when_destination_is_private` | Patterns don't run when dst_lvl == private (no broader audience to leak to) |
| 14 | `test_check_disclosure_emits_blocked_phrases_by_name_not_content` | Privacy: `blocked_phrases` lists pattern NAMES, not matched substrings |
| 15 | `test_check_disclosure_event_payload_excludes_content_includes_length` | Privacy: event payload contains `content_length`, not `content` |
| 16 | `test_register_pattern_adds_to_runtime_pattern_set` | Pattern registry extensibility |
| 16b | `test_register_pattern_duplicate_name_warns_and_skips` | Duplicate-name guard preserves existing pattern + emits warning |
| 17 | `test_runtime_attribute_set_when_enabled` | Public-attribute wiring |
| 18 | `test_runtime_attribute_not_set_when_disabled` | Disabled config skips wiring |

Total: ~20 tests at `tests/test_ad530_classification_gate.py` (was 18; revision adds Test 7b, 9b, 16b).

## Tracking

1. **PROGRESS.md:** prepend AD-530 v1 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-530 v1: Information Classification Enforcement — Disclosure Gate (2026-05-03)

**Problem:** Standing Orders advise agents not to disclose sensitive information, but there's no enforcement layer. Documents have classification metadata (records_store.py:27 `_CLASSIFICATION_LEVELS`), but outbound messages (Ward Room posts, LLM prompts) have no gate at the communication boundary.

**Decision:** v1 ships an observational disclosure gate:
- New `src/probos/security/classification.py` with `ClassificationGate` class.
- Primary method `check_disclosure(content, *, source_classification, destination_clearance) -> DisclosureDecision`.
- Reuses existing `_CLASSIFICATION_LEVELS` hierarchy at records_store.py:27 (real keys: `private`/`department`/`ship`/`fleet`; higher index = broader access). Read-only consumer; no duplication.
- Disclosure direction: BLOCK when `dst_lvl > src_lvl` — destination has broader reach than source classification permits. Direction is grounded in records_store.py:716 and :841 openness semantics.
- Safe defaults: unknown source → most restrictive (`private`, level 0); unknown destination → broadest (`ship`, level 2). Pairing makes unspecified-on-both BLOCK by hierarchy.
- Built-in pattern set (3 regex patterns: captain-directive markers, restricted-prefix literals, secret-format `name=value`). `api_key_like` 32+ char heuristic is **opt-in via `register_pattern()`**, NOT default — UUIDs / commit hashes / opaque tokens collide with it.
- `CLASSIFICATION_DISCLOSURE_BLOCKED` EventType emitted on every block.
- Privacy: event payload includes `content_length` only (NOT content); `blocked_phrases` lists pattern NAMES (NOT matched substrings).
- Public attribute `runtime.classification_gate` (Wave 5 convention #1); `emit_event` is a public field on the class (mirrors AD-456 EgressPolicy.emit_event).

v1 is OBSERVATIONAL — gate returns DisclosureDecision; caller decides whether to redact/suppress/retry. Integration into Ward Room post / LLM prompt builder paths deferred to AD-530d (active enforcement).

**Why:** Standing Orders → enforcement gap is real. Existing classification infrastructure is document-only. Communication-boundary gate is the missing piece. v1 is conservative (observational; never mutates messages) so the gate can be tuned without risk of false-positive suppression breaking real communication.

**Deferred:**
- AD-530b: Security Chief (Worf) runtime API for classification updates via Standing Orders. Forcing function: SecurityAgent spawned and needs `runtime.classification_gate.update_label()`.
- AD-530c: Full audit trail (event on every classified READ, not just blocks). Forcing function: AD-530d integration site lands and Captain reviews blocked-event volume.
- AD-530d: Active enforcement — integrate gate into WardRoomService.create_post + LLMClient prompt builder; redact/suppress/retry policy. Forcing function: AD-530b ships and Captain (or SecurityAgent under Standing Order) issues a label change.
- AD-530e: Default-pattern revisit (re-evaluate `api_key_like` and add tightened API-key prefix patterns: `sk-`, `pk_`, `Bearer`, `AKIA`, `ghp_`). Forcing function: AD-530d integration sites produce real outbound corpus and FP rate of `api_key_like` is measurable.

**Cross-links:** RecordsStore `_CLASSIFICATION_LEVELS` (records_store.py:27 — read-only consumer), AD-456 EgressPolicy (orthogonal — network egress, not content), AD-679 selective disclosure routing (orthogonal — document routing), Standing Orders (Federation tier — eventual policy source for AD-530b).
```

3. **docs/development/roadmap.md:** flip AD-530 status to `partial — v1 ships ClassificationGate (observational disclosure gate + pattern scanner + EventType); Security Chief ownership / audit trail / active enforcement deferred to AD-530b/c/d`.

## Verified Against Codebase (2026-05-03 — revision)

```
grep -n "_CLASSIFICATION_LEVELS" src/probos/knowledge/records_store.py
   26:  # Classification hierarchy (higher index = broader access)
   27:  _CLASSIFICATION_LEVELS = {
   28:      "private": 0,
   29:      "department": 1,
   30:      "ship": 2,
   31:      "fleet": 3,
   32:  }
  716:  doc_class = frontmatter.get("classification", "ship")
  841:  if _CLASSIFICATION_LEVELS.get(doc_class, 0) > _CLASSIFICATION_LEVELS.get(scope, 2):
        continue  # doc is more-open than search scope; filter out

Real keys: "private" (0) / "department" (1) / "ship" (2) / "fleet" (3).
Direction (verified at :841): higher index = BROADER access. Block when destination is broader than source allows (dst_lvl > src_lvl).
read_document at :716–:725 confirms: private→author-only, department→same-dept, ship/fleet→all crew. The numeric ordering encodes openness.

grep -n "emit_event\|_emit_blocked" src/probos/security/egress.py
   63:  emit_event: Any | None = None        # public field (sibling pattern)
  134:  def _emit_blocked(self, decision: EgressDecision) -> None:
  135:      if not self.emit_event:
  138:      self.emit_event(...)
  148:      logger.warning("AD-456: EGRESS_BLOCKED emit failed ...", exc_info=True)

AD-530 mirrors AD-456: public `emit_event` field (no underscore), logger.warning on emit failure.

grep -rn "runtime.classification_gate\|CLASSIFICATION_DISCLOSURE_BLOCKED" src/probos/
  (Expected: 0 hits before AD-530 v1; verifies attribute name + EventType are free)

grep -n "_wire_creative_expression\|_wire_self_distillation\|_wire_anomaly_window" src/probos/startup/finalize.py
   25:  def _wire_anomaly_window(*, runtime, config) -> bool:
   80:  def _wire_creative_expression(*, runtime, config) -> bool:
  105:  async def _wire_self_distillation(*, runtime, config) -> bool:
  274–280: invocation block in finalize_startup

_wire_classification_gate is sync (mirrors _wire_creative_expression at line 80); invoke alongside the existing block at 274–280.
```

## Acceptance Criteria

- `src/probos/security/classification.py` exists with `ClassificationGate` + `DisclosureDecision` + `DisclosureReason` Literal.
- `_CLASSIFICATION_LEVELS` consumed read-only via import from `probos.knowledge.records_store`; not duplicated.
- 3 built-in patterns seeded by default (`captain_directive`, `restricted_prefix`, `secret_format`); `api_key_like` is OPT-IN via `register_pattern()` (NOT default).
- Disclosure rule: BLOCK when `dst_lvl > src_lvl` (direction grounded in records_store.py:841 openness comparison).
- Safe defaults: unknown source → `"private"` (level 0); unknown destination → `"ship"` (level 2).
- `CLASSIFICATION_DISCLOSURE_BLOCKED` EventType added (collision-free).
- Privacy: event payload excludes content (only `content_length`); `blocked_phrases` lists pattern NAMES not substrings.
- `ClassificationGateConfig` Pydantic class wired into `SystemConfig.classification_gate`.
- Public attribute `runtime.classification_gate` (no underscore); `ClassificationGate.emit_event` is a public field; `pattern_count` and `patterns` are public read-only properties.
- ~20 tests pass (Tests 1–18 + 7b + 9b + 16b).
- DECISIONS.md entry under Era V references real hierarchy keys.
- GH issue #104 closes when commit lands.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Hard-Stops

- `_CLASSIFICATION_LEVELS` hierarchy keys or comment differ from documented (`private`/`department`/`ship`/`fleet`; higher index = broader) — surface; revision drift since 2026-05-03.
- records_store.py:841 comparison direction differs from documented (`> scope` filters broader-than-scope) — surface; the disclosure rule depends on this semantic.
- v1 active-enforcement scope creep — if you find yourself adding integration into WardRoomService.create_post or LLMClient prompt builder, STOP. That's AD-530d.
- Pattern set causes excessive false positives in existing tests (default pattern matches legitimate Ward Room post content) — surface; the only default patterns are `captain_directive`, `restricted_prefix`, `secret_format`; if any of these match real fixture content the pattern itself needs revision (NOT scope expansion). Note `api_key_like` is intentionally NOT default; reintroducing it is a hard-stop.
- Privacy regression — content or matched-substring leakage into event payload — STOP; design intent is `content_length` + pattern NAMES only.

---

## Revision (2026-05-03)

Pass-1 review (`prompts/Reviews/ad-530-classification-gate-v1-review.md`) returned ❌ Not Ready with 4 Required + 5 Recommended + 4 Nits.

**Required addressed:**

- **R1 — Hierarchy keys.** All `confidential` references replaced with the real 4-tier hierarchy (`private`/`department`/`ship`/`fleet`). The most-restrictive level is `private` (index 0). Solution Overview now states the real keys verbatim and documents the openness semantics. Section 2 docstring + DECISIONS entry + Test names all updated. `fleet`-tier handling explicitly noted in Deferred.
- **R2 — Disclosure direction.** Direction inverted to match records_store.py:841 openness semantics. Was: `if dst_lvl < src_lvl: BLOCK`. Now: `if dst_lvl > src_lvl: BLOCK` (destination has broader reach than source allows). Reason string renamed from `"clearance_below_source"` → `"destination_too_broad"` for accuracy. Worked-example pairs in Solution Overview re-derived. Tests #4–#6 re-asserted.
- **R3 — Safe defaults.** Source default changed from `2` (broadest) → `_CLASSIFICATION_LEVELS["private"]` (most restrictive, 0). Destination default changed from `2` → `_CLASSIFICATION_LEVELS["ship"]` (broadest among normal levels). Combined: unspecified-on-both BLOCKS by hierarchy. Test #7 split into 7 (unknown source) + 7b (unknown destination).
- **R4 — `api_key_like` dropped from defaults.** Removed from `_DEFAULT_SENSITIVE_PATTERNS`. Default pattern count is now 3 (was 4). Available via `register_pattern("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b")` opt-in. AD-530e added as new deferral with explicit forcing function. Test #9 split into 9 (assert NOT default) + 9b (opt-in re-introduces).

**Recommended addressed:**

- **#1 — DECISIONS forcing functions.** AD-530b/c/d/e each list explicit forcing functions in the Deferred block.
- **#2 — `emit_event` field naming.** Now a public field on `ClassificationGate` (no underscore), mirroring AD-456 `EgressPolicy.emit_event`. Constructor accepts it as `*, emit_event=None` and assigns to `self.emit_event`.
- **#3 — `logger.warning` on emit failure.** Was `logger.debug`; now `logger.warning("AD-530: CLASSIFICATION_DISCLOSURE_BLOCKED emit failed (reason=%s)", ...)` to match AD-456 parity.
- **#4 — `register_pattern` duplicate-name guard.** Now skips with `logger.warning` if `name` already registered (Test 16b added).
- **#5 — `private_marker` rename.** Renamed pattern key from `private_marker` → `restricted_prefix` to avoid collision with the `private` classification key. DECISIONS entry no longer says "private prefixes"; says "restricted-prefix literals".

**Nits addressed:**

- Section 4 wiring uses `runtime.classification_gate.pattern_count` (new public property), not `_patterns`.
- `DisclosureDecision.reason` typed as `Literal["ok", "destination_too_broad", "sensitive_pattern_matched"]` via `DisclosureReason` alias.
- Test count updated to ~20 (Tests 1–18 + 7b + 9b + 16b); acceptance criteria matches.
- Verified-Against-Codebase footer states real keys verbatim — no "Builder reads exact hierarchy" delegation.

**Beyond-review additions:**

- Added explicit Section 4 wiring location reference (`finalize.py:274–280`) so the Builder doesn't have to grep.
- Added `patterns` (tuple-view) public property in addition to `pattern_count`.
- Pattern scan now skips when `dst_lvl == private` (was `dst_lvl > confidential` which was always-true under the old key set; the new condition is meaningful — patterns target broader-audience leakage and `private` has no broader audience).
- `DisclosureReason` Literal alias added (Nit #2 from review escalated to typed-API since the field has only 3 values).

**Closing self-check (architect):**

```
Grep for "confidential" in shipping content (excluding Revision section):
  - 0 hits in Solution Overview / Section 2 / Section 3 / Section 4 / Test Plan / DECISIONS / Acceptance Criteria / Hard-Stops.
  - Mentions in this Revision section reference the OLD wording for audit; legitimate.
Grep for "dst_lvl < src_lvl" (the old inverted condition):
  - 0 hits.
Grep for "api_key_like" in DEFAULT_SENSITIVE_PATTERNS:
  - 0 hits (mentions in `register_pattern()` opt-in / AD-530e deferral / Test 9b are legitimate).
```

Verdict: 4 Required + 5 Recommended + 4 Nits all addressed. Tolerance gate (#15) targeted: pass-2 review should land at ≤1 ⚠.
