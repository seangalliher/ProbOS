# AD-530 v1: Information Classification Enforcement — Disclosure Gate

**Status:** Drafted (Wave 19)
**Risk:** medium (introduces communication-boundary check; new gating surface)
**Depends on:** RecordsStore classification infrastructure (shipped — `_CLASSIFICATION_LEVELS` at records_store.py:27); EventLog (shipped); WardRoomService (shipped)
**Closes:** GitHub issue #104

---

## Solution Overview

AD-530 in roadmap.md (line 6513) addresses "disclosure of sensitive information" — Standing Orders are advisory, agents have no technical barrier to including classified content in outbound messages. Roadmap lists 4 capabilities: classification labels + disclosure gates + Security Chief ownership + audit trail.

ProbOS already has classification infrastructure for **documents** (`_CLASSIFICATION_LEVELS` at records_store.py:27 with `ship`/`department`/`confidential` levels) and selective-disclosure routing (AD-679). What's missing: **outbound message classification + disclosure gate at the communication boundary** (Ward Room posts, LLM prompts).

**v1 ships 2 of 4 capabilities** (per convention #14 aggressive pre-deferral) — the bounded enforcement surface:

1. **`ClassificationGate`** — new class in `src/probos/security/classification.py`. Single primary method `check_disclosure(content: str, source_classification: str, destination_clearance: str) -> DisclosureDecision`. Returns `DisclosureDecision(allowed: bool, reason: str, blocked_phrases: tuple[str, ...])`. Uses existing `_CLASSIFICATION_LEVELS` hierarchy (higher index = broader access; `ship`=2, `department`=1, `confidential`=0). Disclosure ALLOWED when `source_clearance >= destination_clearance` (same hierarchy as records_store.read_document at :716).

2. **Pattern-based sensitive-content scanner** — `ClassificationGate` includes a small built-in pattern set for `confidential` content: API key formats (heuristic), Captain DM phrases (`[CAPTAIN_DIRECTIVE]`, `private:`), config-secret formats. Scanner returns matched phrases; gate blocks disclosure when any match found AND destination clearance < confidential. This is observational v1 — gate emits `CLASSIFICATION_DISCLOSURE_BLOCKED` event but does NOT mutate outbound messages (no DLP rewriting). Caller (Ward Room post path / LLM prompt builder) decides whether to suppress, redact, or retry.

**Deferred:**

- AD-530b: Security Chief ownership — runtime updates to classification labels via Standing Orders. Forcing function: a designed agent (Worf/SecurityAgent) needs the runtime API.
- AD-530c: Audit trail to event log — full classified-data-access logging. v1 only emits events on BLOCK; deferred AD adds event for every classified READ.
- AD-530d: Active enforcement (mutate / redact / suppress outbound messages) — v1 is observational. Forcing function: Captain decides redact vs suppress is the correct response policy.

## Dependencies

- `_CLASSIFICATION_LEVELS` at `src/probos/knowledge/records_store.py:27` — read-only consumer of the existing 3-tier hierarchy. AD-530 does NOT modify or duplicate this.
- `runtime.event_log` — emit `CLASSIFICATION_DISCLOSURE_BLOCKED` per blocked check.
- `runtime.event_log` and `runtime.config` — read-only.
- New file: `src/probos/security/classification.py` (alongside existing `security/egress.py` from AD-456).

All reads from existing surfaces; one new module under existing security/ package.

## Sections

### Section 0 — EventTypes

- `CLASSIFICATION_DISCLOSURE_BLOCKED` — emitted when `ClassificationGate.check_disclosure()` returns allowed=False.

Verify no collision with events.py.

### Section 1 — `DisclosureDecision` frozen dataclass

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DisclosureDecision:
    """Result of a classification disclosure check. AD-530 v1."""
    allowed: bool
    reason: str  # e.g., "ok", "clearance_below_source", "sensitive_pattern_matched"
    blocked_phrases: tuple[str, ...]  # phrases that triggered the block; empty when allowed
    source_classification: str  # echoed for audit
    destination_clearance: str   # echoed for audit
```

### Section 2 — `ClassificationGate` class

```python
import re
from collections.abc import Iterable

from probos.knowledge.records_store import _CLASSIFICATION_LEVELS

# AD-530 v1 sensitive content patterns. Tightly scoped to known-high-risk shapes;
# false positives prefer to NOT block (caller decides). Pattern set extensible
# via register_pattern() (runtime-only; no persistence in v1).
_DEFAULT_SENSITIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # name, regex
    ("api_key_like", r"\b[A-Za-z0-9_-]{32,}\b"),  # 32+ char alphanum-ish tokens (heuristic)
    ("captain_directive", r"\[CAPTAIN_DIRECTIVE\]"),
    ("private_marker", r"\b(private|confidential):\s"),
    ("secret_format", r"(?i)\b(secret|api[_-]?key|password|token)\s*[:=]\s*\S+"),
)


class ClassificationGate:
    """v1 disclosure gate. Read-only check; no message mutation. AD-530 v1."""

    def __init__(
        self,
        runtime: Any,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        # Compile default patterns at construction; register_pattern adds more
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pat)) for name, pat in _DEFAULT_SENSITIVE_PATTERNS
        ]

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
            source_classification: Source data's classification label (one of the
                _CLASSIFICATION_LEVELS keys: "ship", "department", "confidential",
                or "unspecified" for safe-default).
            destination_clearance: Destination's clearance level (same hierarchy).

        Returns:
            DisclosureDecision. allowed=True when destination_clearance >=
            source_classification level AND no sensitive patterns matched.
        """
        # Hierarchy check: lower index = higher restriction
        src_lvl = _CLASSIFICATION_LEVELS.get(source_classification, 2)  # default: ship-level
        dst_lvl = _CLASSIFICATION_LEVELS.get(destination_clearance, 2)
        if dst_lvl < src_lvl:  # destination cannot see this restriction
            decision = DisclosureDecision(
                allowed=False,
                reason="clearance_below_source",
                blocked_phrases=(),
                source_classification=source_classification,
                destination_clearance=destination_clearance,
            )
            self._emit_blocked(content, decision)
            return decision

        # Pattern scan: if any sensitive pattern matches AND destination < confidential
        matches: list[str] = []
        confidential_lvl = _CLASSIFICATION_LEVELS.get("confidential", 0)
        if dst_lvl > confidential_lvl:
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
        """Add a sensitive-content pattern (runtime-only; not persisted in v1)."""
        self._patterns.append((name, re.compile(pattern)))

    def _emit_blocked(self, content: str, decision: DisclosureDecision) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.CLASSIFICATION_DISCLOSURE_BLOCKED,
                {
                    "reason": decision.reason,
                    "source_classification": decision.source_classification,
                    "destination_clearance": decision.destination_clearance,
                    "blocked_phrases": list(decision.blocked_phrases),
                    "content_length": len(content),  # NOT content itself per privacy
                },
            )
        except Exception:
            logger.debug("AD-530: emit_event failed", exc_info=True)
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
    runtime.classification_gate = ClassificationGate(runtime, emit_event=runtime.emit_event)
    logger.info("AD-530: ClassificationGate initialized (%d patterns)", len(runtime.classification_gate._patterns))
    return True
```

Invoke from `finalize_startup` next to `_wire_creative_expression` / `_wire_self_distillation` / `_wire_anomaly_window`.

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
| 4 | `test_check_disclosure_allowed_when_clearance_equal` | Hierarchy: same level |
| 5 | `test_check_disclosure_allowed_when_clearance_higher` | Hierarchy: dst >= src |
| 6 | `test_check_disclosure_blocked_when_clearance_lower` | Hierarchy: dst < src returns allowed=False, reason="clearance_below_source" |
| 7 | `test_check_disclosure_unspecified_classification_defaults_to_ship` | Default behavior on unknown classification |
| 8 | `test_check_disclosure_emits_blocked_event_on_clearance_failure` | Event emission |
| 9 | `test_check_disclosure_pattern_blocks_api_key_like_token` | Pattern: 32+ char alphanumeric |
| 10 | `test_check_disclosure_pattern_blocks_captain_directive` | Pattern: CAPTAIN_DIRECTIVE marker |
| 11 | `test_check_disclosure_pattern_blocks_private_marker` | Pattern: private/confidential prefix |
| 12 | `test_check_disclosure_pattern_blocks_secret_format` | Pattern: secret=xxx, api_key:xxx |
| 13 | `test_check_disclosure_pattern_skipped_when_destination_is_confidential` | Patterns don't block confidential destinations |
| 14 | `test_check_disclosure_emits_blocked_phrases_by_name_not_content` | Privacy: blocked_phrases lists names, not matched substrings |
| 15 | `test_check_disclosure_event_payload_excludes_content_includes_length` | Privacy: content not in event payload |
| 16 | `test_register_pattern_adds_to_runtime_pattern_set` | Pattern registry extensibility |
| 17 | `test_runtime_attribute_set_when_enabled` | Public-attribute wiring |
| 18 | `test_runtime_attribute_not_set_when_disabled` | Disabled config skips wiring |

Total: ~18 tests at `tests/test_ad530_classification_gate.py`.

## Tracking

1. **PROGRESS.md:** prepend AD-530 v1 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
### AD-530 v1: Information Classification Enforcement — Disclosure Gate (2026-05-03)

**Problem:** Standing Orders advise agents not to disclose sensitive information, but there's no enforcement layer. Documents have classification metadata (records_store.py:27 `_CLASSIFICATION_LEVELS`), but outbound messages (Ward Room posts, LLM prompts) have no gate at the communication boundary.

**Decision:** v1 ships an observational disclosure gate:
- New `src/probos/security/classification.py` with `ClassificationGate` class.
- Primary method `check_disclosure(content, source_classification, destination_clearance) -> DisclosureDecision`.
- Reuses existing `_CLASSIFICATION_LEVELS` hierarchy (no duplication).
- Built-in pattern set (4 regex patterns for api-key shapes, captain-directive markers, private prefixes, secret formats).
- `CLASSIFICATION_DISCLOSURE_BLOCKED` EventType emitted on every block.
- Privacy: event payload includes `content_length` only (NOT content); blocked_phrases lists names (NOT matched substrings).
- Public attribute `runtime.classification_gate` (Wave 5 convention #1).

v1 is OBSERVATIONAL — gate returns DisclosureDecision; caller decides whether to redact/suppress/retry. Integration into Ward Room post / LLM prompt builder paths deferred to AD-530d (active enforcement).

**Why:** Standing Orders → enforcement gap is real. Existing classification infrastructure is document-only. Communication-boundary gate is the missing piece. v1 is conservative (observational; never mutates messages) so the gate can be tuned without risk of false-positive suppression breaking real communication.

**Deferred:**
- AD-530b: Security Chief (Worf) runtime API for classification updates via Standing Orders.
- AD-530c: Full audit trail (event on every classified READ, not just blocks).
- AD-530d: Active enforcement — integrate gate into WardRoomService.create_post + LLMClient prompt builder; redact/suppress/retry policy.

**Cross-links:** RecordsStore `_CLASSIFICATION_LEVELS` (records_store.py:27 — read-only consumer), AD-456 EgressPolicy (orthogonal — network egress, not content), AD-679 selective disclosure routing (orthogonal — document routing), Standing Orders (Federation tier — eventual policy source for AD-530b).
```

3. **docs/development/roadmap.md:** flip AD-530 status to `partial — v1 ships ClassificationGate (observational disclosure gate + pattern scanner + EventType); Security Chief ownership / audit trail / active enforcement deferred to AD-530b/c/d`.

## Verified Against Codebase (2026-05-03)

```
grep -n "_CLASSIFICATION_LEVELS\|class.*Classification" src/probos/knowledge/records_store.py
   27: _CLASSIFICATION_LEVELS = { ... }
  108-110: validate via _CLASSIFICATION_LEVELS
  716: doc_class = frontmatter.get("classification", "ship")
  841: _CLASSIFICATION_LEVELS.get(doc_class, 0) > _CLASSIFICATION_LEVELS.get(scope, 2)
  (Builder reads exact hierarchy at line 27-32 to match)

grep -n "EgressPolicy\|class EgressPolicy" src/probos/security/egress.py
  (Builder verifies sibling module pattern — AD-456)

grep -rn "runtime.classification_gate" src/probos/
  (Expected: 0 hits before AD-530 v1; verifies attribute name is free)
```

## Acceptance Criteria

- `src/probos/security/classification.py` exists with `ClassificationGate` + `DisclosureDecision`.
- `_CLASSIFICATION_LEVELS` consumed read-only; not duplicated.
- 4 built-in patterns seeded; `register_pattern()` extensibility.
- `CLASSIFICATION_DISCLOSURE_BLOCKED` EventType added (collision-free).
- Privacy: event payload excludes content; blocked_phrases lists names not substrings.
- `ClassificationGateConfig` Pydantic class wired into SystemConfig.
- Public attribute `runtime.classification_gate` (no underscore).
- 18 tests pass.
- DECISIONS.md entry under Era V.
- GH issue #104 closes when commit lands.

## Hard-Stops

- `_CLASSIFICATION_LEVELS` hierarchy keys differ from assumption (`ship`/`department`/`confidential`) — surface; gate must use the real keys.
- v1 active-enforcement scope creep — if you find yourself adding integration into WardRoomService.create_post or LLMClient prompt builder, STOP. That's AD-530d.
- Pattern set causes excessive false positives in existing tests (pattern matches legitimate Ward Room post content) — surface; tune patterns or defer pattern scan to AD-530d.
- Privacy regression — content or matched-substring leakage into event payload — STOP; design intent is content_length + phrase names only.
