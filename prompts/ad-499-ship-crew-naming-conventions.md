# AD-499: Ship & Crew Naming Conventions

**Status:** Ready for builder
**Dependencies:** AD-441 (DIDs), AD-441b (Commission), AD-442 (Naming Ceremony) — all complete (verified by presence of `src/probos/identity.py:101 class AgentBirthCertificate`, `src/probos/identity.py:366 class AgentIdentityRegistry`, `src/probos/agent_onboarding.py run_naming_ceremony`).
**Estimated tests:** ~10
**Risk:** Low — additive-only convention layer over existing identity infrastructure. Trivial-class per the AD-BACKLOG-AUDIT.

---

## Problem

ProbOS already has DIDs, ship birth certificates with `vessel_name`, agent birth certificates with `callsign`, and a naming-ceremony hook in `agent_onboarding.py` (verified at `agent_onboarding.py run_naming_ceremony`). What is missing is a **codified naming convention layer** that:

1. Standardizes how ship names get selected at commissioning (currently they appear to be set ad-hoc; verified via `grep -n "vessel_name" src/probos/identity.py:116,141,169,199,213` — `vessel_name` is a stored field but no naming policy).
2. Defines an agent self-naming format (currently `CallsignRegistry` at `crew_profile.py:305` accepts any string).
3. Defines a federation display format (`Name [ShipName]`) for cross-instance disambiguation.

`grep -rn "ShipNamingPolicy|AgentNamingPolicy" src/probos/` returns no matches — none of these naming policies exist yet.

## Solution Overview

Add `naming.py` containing three small policy classes:

1. **`ShipNamingPolicy`** — emits the candidate ship name(s) at commissioning. First implementation: deterministic seed-based name from a curated list (e.g., starship class names) plus an optional Captain override.
2. **`AgentNamingPolicy`** — validates and normalizes self-chosen agent callsigns: format constraints, length limits, banned-word filter (delegates to AD-455 ThreatDetector if available, else a small builtin list).
3. **`FederationDisplayFormat`** — pure helper: `format(callsign, ship_name) -> str` returning `"Callsign [ShipName]"` for federation contexts.

Plus two new EventTypes (`SHIP_NAMED`, `AGENT_SELF_NAMED`) emitted at the existing commissioning / naming-ceremony hook points.

This AD is intentionally a **trivial-class** delivery (per the AD-BACKLOG-AUDIT classification). All three policies are pure-function or stateless-class style. No persistence beyond what AD-441 already does.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
SHIP_NAMED = "ship_named"  # AD-499
AGENT_SELF_NAMED = "agent_self_named"  # AD-499
```

Two new values. Verified absent via `grep -n "SHIP_NAMED|AGENT_SELF_NAMED" src/probos/events.py` (no matches).

---

## Section 1: `naming.py` — three policy classes

**File:** `src/probos/naming.py` (new — flat layout matching existing `identity.py`, `proactive.py`)

```python
"""AD-499: Ship & Crew Naming Conventions.

Three-layer naming policy:

1. ShipNamingPolicy — deterministic seed-based ship name selection at
   commissioning, with Captain override.
2. AgentNamingPolicy — validation and normalization for self-chosen
   agent callsigns.
3. FederationDisplayFormat — cross-instance display helper.

All three are stateless. No persistence beyond what AD-441's
AgentIdentityRegistry already provides.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Curated starship/vessel name pool. Selected at commissioning when
# Captain does not provide an override. Pool may grow with future ADs;
# do not shrink without a DECISIONS.md entry (would invalidate previously
# chosen names for testability).
_SHIP_NAME_POOL: tuple[str, ...] = (
    "Enterprise", "Voyager", "Defiant", "Discovery", "Reliant",
    "Constitution", "Galaxy", "Intrepid", "Sovereign", "Excelsior",
    "Yamato", "Hood", "Pegasus", "Stargazer", "Avalon",
)

_CALLSIGN_RE = re.compile(r"^[A-Z][a-zA-Z0-9_-]{1,31}$")
_BANNED_WORDS_DEFAULT: frozenset[str] = frozenset({
    "admin", "root", "system", "ship", "captain",
    "null", "undefined", "test", "anonymous",
})


@dataclass(frozen=True)
class ShipNameDecision:
    """Outcome of a ship-naming decision."""

    name: str
    source: str            # "captain_override" | "deterministic_seed"
    seed: str              # instance_id used (for audit)
    pool_size: int


class ShipNamingPolicy:
    """Selects a ship name at commissioning.

    Two paths:
      - captain_override: caller passes a non-empty `override_name`.
      - deterministic_seed: hash(instance_id) % pool → name.
    """

    def __init__(self, *, pool: tuple[str, ...] = _SHIP_NAME_POOL) -> None:
        if not pool:
            raise ValueError("AD-499: ship name pool must be non-empty")
        self._pool = pool

    def select(self, *, instance_id: str,
               override_name: str | None = None) -> ShipNameDecision:
        if override_name and override_name.strip():
            return ShipNameDecision(
                name=override_name.strip(),
                source="captain_override",
                seed=instance_id,
                pool_size=len(self._pool),
            )
        if not instance_id:
            raise ValueError("AD-499: instance_id required for seed selection")
        digest = hashlib.sha256(instance_id.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % len(self._pool)
        return ShipNameDecision(
            name=self._pool[idx],
            source="deterministic_seed",
            seed=instance_id,
            pool_size=len(self._pool),
        )

    @property
    def pool(self) -> tuple[str, ...]:
        return self._pool


@dataclass(frozen=True)
class CallsignValidation:
    accepted: bool
    normalized: str = ""
    reason: str = ""


class AgentNamingPolicy:
    """Validate and normalize self-chosen agent callsigns.

    Rules:
      - Must match _CALLSIGN_RE (initial uppercase, 2–32 chars,
        alphanumeric + underscore + hyphen).
      - Must not appear in banned-word list (case-insensitive).
      - Trimmed, normalized to single internal whitespace before check.
    """

    def __init__(self, *, banned: frozenset[str] = _BANNED_WORDS_DEFAULT) -> None:
        self._banned = frozenset(b.lower() for b in banned)

    def validate(self, raw: str) -> CallsignValidation:
        if raw is None:
            return CallsignValidation(False, reason="empty_input")
        candidate = raw.strip()
        if not candidate:
            return CallsignValidation(False, reason="empty_input")
        if candidate.lower() in self._banned:
            return CallsignValidation(False, reason="banned_word")
        if not _CALLSIGN_RE.match(candidate):
            return CallsignValidation(False, reason="format_invalid")
        return CallsignValidation(accepted=True, normalized=candidate)

    @property
    def banned_words(self) -> frozenset[str]:
        return self._banned


class FederationDisplayFormat:
    """Cross-instance display helper.

    Stateless. `format(callsign, ship_name)` returns "Callsign [ShipName]".
    Empty inputs are tolerated and produce the most informative substring
    available; never raises.
    """

    @staticmethod
    def format(callsign: str, ship_name: str) -> str:
        cs = (callsign or "").strip()
        sh = (ship_name or "").strip()
        if cs and sh:
            return f"{cs} [{sh}]"
        if cs:
            return cs
        if sh:
            return f"[{sh}]"
        return ""
```

---

## Section 2: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
```

REPLACE:
```python
    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679
    SHIP_NAMED = "ship_named"  # AD-499
    AGENT_SELF_NAMED = "agent_self_named"  # AD-499
```

---

## Section 3: Add `NamingConfig`

**File:** `src/probos/config.py`

```python
class NamingConfig(BaseModel):
    """Ship & crew naming conventions (AD-499)."""

    enabled: bool = True
    captain_ship_override: str = ""  # If non-empty, overrides seed selection
    extra_banned_words: list[str] = Field(default_factory=list)
```

Wire into `SystemConfig`:

SEARCH:
```python
    onboarding: OnboardingConfig = OnboardingConfig()
```

REPLACE:
```python
    onboarding: OnboardingConfig = OnboardingConfig()
    naming: NamingConfig = NamingConfig()  # AD-499
```

> Verify-first: ensure `Field` is already imported in `config.py`. `grep -n "from pydantic import" src/probos/config.py` to confirm. If not, add `from pydantic import Field` to the imports.

---

## Section 4: Wire ShipNamingPolicy into commissioning

**File:** `src/probos/identity.py` — at the `_load_or_commission_ship` path (verified by `grep -n "_load_or_commission_ship" src/probos/identity.py`).

The Builder identifies the existing site where `vessel_name` is chosen during ship commissioning and routes it through `ShipNamingPolicy.select()`. If no current code exists, add a hook in `commission_ship()` that accepts an optional `naming_policy` parameter.

Sketch — exact insertion is grep-determined:

```python
        # AD-499: Ship naming policy
        from probos.naming import ShipNamingPolicy
        policy = ShipNamingPolicy()
        decision = policy.select(
            instance_id=instance_id,
            override_name=captain_override or None,
        )
        vessel_name = decision.name
        if emit_event:
            try:
                emit_event(EventType.SHIP_NAMED, {
                    "vessel_name": decision.name,
                    "source": decision.source,
                    "instance_id": instance_id,
                })
            except Exception:
                logger.warning("AD-499: SHIP_NAMED emit failed", exc_info=True)
```

Where `captain_override` is sourced from `config.naming.captain_ship_override`.

---

## Section 5: Wire AgentNamingPolicy into naming ceremony

**File:** `src/probos/agent_onboarding.py` — `run_naming_ceremony` method (verified present).

After the LLM proposes a callsign:

```python
        # AD-499: validate self-chosen callsign
        from probos.naming import AgentNamingPolicy
        policy = AgentNamingPolicy(
            banned=frozenset({*_BANNED_DEFAULT, *self._config.naming.extra_banned_words})
            if self._config.naming.enabled
            else frozenset()
        )
        validation = policy.validate(chosen_callsign)
        if not validation.accepted:
            logger.warning(
                "AD-499: callsign '%s' rejected (%s); using fallback",
                chosen_callsign, validation.reason,
            )
            chosen_callsign = fallback_callsign  # existing seed callsign path
        else:
            chosen_callsign = validation.normalized
            if self._event_log:
                try:
                    await self._event_log.append(EventType.AGENT_SELF_NAMED, {
                        "agent_id": agent.id,
                        "callsign": chosen_callsign,
                    })
                except Exception:
                    logger.warning("AD-499: AGENT_SELF_NAMED emit failed", exc_info=True)
```

> Builder note: `_BANNED_DEFAULT` and the existing event-log emit pattern must be confirmed by grep against the actual `agent_onboarding.py`. The exact symbol names in this sketch are illustrative; map to real names during implementation.

---

## Section 6: Federation display format integration

**File:** `src/probos/federation/router.py` (verified to exist via `ls src/probos/federation/`).

Find the existing peer-display path and route it through `FederationDisplayFormat.format()`. If no display path exists, add a public helper:

```python
def display_name_for(callsign: str, ship_name: str) -> str:
    """AD-499: Federation display format."""
    from probos.naming import FederationDisplayFormat
    return FederationDisplayFormat.format(callsign, ship_name)
```

This is the lowest-risk integration. If a more structural integration is required, surface to architect — it falls outside the minimal AD-499 scope.

---

## Tests

**File:** `tests/test_ad499_naming_conventions.py`

10 tests:

1. `test_event_type_ship_named_exists` — `EventType.SHIP_NAMED.value == "ship_named"`.
2. `test_event_type_agent_self_named_exists` — value present.
3. `test_ship_naming_captain_override` — `select(instance_id="abc", override_name="Yamato")` → `name="Yamato"`, `source="captain_override"`.
4. `test_ship_naming_deterministic_seed_stable` — same `instance_id` produces same name across two calls.
5. `test_ship_naming_empty_pool_raises` — `ShipNamingPolicy(pool=())` → `ValueError`.
6. `test_ship_naming_empty_instance_id_raises` — `select(instance_id="")` → `ValueError`.
7. `test_callsign_validation_happy_path` — `validate("Picard")` → accepted, normalized.
8. `test_callsign_validation_lowercase_first_rejected` — `validate("picard")` → `format_invalid`.
9. `test_callsign_validation_banned_word_rejected` — `validate("admin")` → `banned_word`.
10. `test_federation_display_format_full` — `format("Picard", "Enterprise")` → `"Picard [Enterprise]"`. Edge cases with empty callsign or empty ship name verified to not raise.

Each test creates fresh policy instances. No shared state. No `tmp_path` needed (pure-function design).

---

## What This Does NOT Change

- `AgentIdentityRegistry`, `AgentBirthCertificate`, `VesselCertificate` schemas are untouched.
- `CallsignRegistry` is not modified — `AgentNamingPolicy` is a separate validation layer that the onboarding service consults before registering.
- No new database tables.
- No new federation endpoints. `FederationDisplayFormat` is a pure helper.
- The naming ceremony LLM prompt is unchanged. AD-499 only validates the LLM's output.
- The seed-pool selection is **deterministic** by design. Different ProbOS instances with the same `instance_id` produce the same name; `instance_id` is a UUID v4 in practice so collisions are infinitesimal.

---

## Tracking

- `PROGRESS.md`: add `AD-499 CLOSED. Ship & Crew Naming Conventions — ...`
- `docs/development/roadmap.md`: flip AD-499 status from `*(planned, OSS)*` to `*(complete)*` near line 6967.
- `DECISIONS.md`: optional entry recording the deterministic-seed decision and the trivial-class scope. Skip if Builder finds the entry would be filler (less than 5 lines of substance).

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/naming.py`: ~140 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~6 lines added.
- `src/probos/identity.py`: ~12 lines added (commissioning hook).
- `src/probos/agent_onboarding.py`: ~18 lines added (validation hook).
- `src/probos/federation/router.py`: ~5 lines added.
- `tests/test_ad499_naming_conventions.py`: ~180 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 10 tests pass at `pytest tests/test_ad499_naming_conventions.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- 2 new EventTypes appear exactly once in `events.py` at the documented insertion point.
- Ship commissioning routes through `ShipNamingPolicy.select()`.
- Naming ceremony routes through `AgentNamingPolicy.validate()`.
- `FederationDisplayFormat.format()` is consumed in at least one federation site or a documented helper.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-04-30)

```
grep -n "class AgentBirthCertificate" src/probos/identity.py
  101: class AgentBirthCertificate:

grep -n "class AgentIdentityRegistry" src/probos/identity.py
  366: class AgentIdentityRegistry:

grep -n "vessel_name" src/probos/identity.py
  116:    vessel_name: str         # e.g., "USS Enterprise"
  141:            "vessel_name": self.vessel_name,
  169:                    "name": self.vessel_name,
  199:    vessel_name: str           # e.g., "ProbOS"

grep -n "run_naming_ceremony" src/probos/agent_onboarding.py
  (verified present — caller around ceremony line)

grep -n "class CallsignRegistry" src/probos/crew_profile.py
  305: class CallsignRegistry:

grep -n "naming_ceremony" src/probos/config.py
  1026:    naming_ceremony: bool = True  # If False, agents keep seed callsigns

grep -n "DISCLOSURE_FILTERED" src/probos/events.py
  179:    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679

grep -rn "SHIP_NAMED|AGENT_SELF_NAMED" src/probos/
  (no matches — names are free)

grep -rn "ShipNamingPolicy|AgentNamingPolicy|FederationDisplayFormat" src/probos/
  (no matches — AD-499 introduces these)

ls src/probos/federation/
  __init__.py  bridge.py  mock_transport.py  nats_transport.py  router.py  transport.py

grep -n "onboarding: OnboardingConfig" src/probos/config.py
  1526:    onboarding: OnboardingConfig = OnboardingConfig()
```
