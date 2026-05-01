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

**File:** `src/probos/startup/communication.py` (NOT `identity.py` — verified: `vessel_name` is chosen at `communication.py:403` before `identity_registry.start()` runs).

The actual choice point for the ship name is the `vi = ontology.get_vessel_identity()` line at `communication.py:400`. By the time `_load_or_commission_ship` runs in `identity.py`, `vessel_name` has already been bound to a string parameter.

SEARCH (around `communication.py:399`):
```python
    if ontology and identity_registry:
        vi = ontology.get_vessel_identity()
        await identity_registry.start(
            instance_id=vi.instance_id,
            vessel_name=vi.name,
            version=config.system.version,
        )
```

REPLACE:
```python
    if ontology and identity_registry:
        vi = ontology.get_vessel_identity()
        # AD-499: route ontology-supplied vessel name through ShipNamingPolicy
        chosen_vessel_name = vi.name
        if config.naming.enabled:
            from probos.naming import ShipNamingPolicy
            ship_policy = ShipNamingPolicy()
            decision = ship_policy.select(
                instance_id=vi.instance_id,
                override_name=config.naming.captain_ship_override or vi.name,
            )
            chosen_vessel_name = decision.name
            try:
                emit_event_fn(EventType.SHIP_NAMED, {
                    "vessel_name": decision.name,
                    "source": decision.source,
                    "instance_id": vi.instance_id,
                })
            except Exception:
                logger.warning("AD-499: SHIP_NAMED emit failed", exc_info=True)
        await identity_registry.start(
            instance_id=vi.instance_id,
            vessel_name=chosen_vessel_name,
            version=config.system.version,
        )
```

> Verify-first: `init_communication` receives `emit_event_fn: Callable[..., Any]` as a parameter — confirmed at `src/probos/startup/communication.py:46`. `runtime` is NOT a parameter of `init_communication`; the function's existing emission pattern (lines 65, 100, 131, 267) all use `emit_event_fn` directly. `EventType` and `logger` already imported at top of `communication.py`.

---

## Section 5: Wire AgentNamingPolicy into naming ceremony

**File:** `src/probos/agent_onboarding.py` — `run_naming_ceremony` method (verified at line 465; LLM result lands as variable `chosen` at line 532; existing fallback variable is `seed_callsign` at line 467).

Find the existing validation block at the LLM-result seam (around `agent_onboarding.py:530-545`) and insert the AD-499 normalization BEFORE the existing length/empty check. The actual local variable is `chosen` (not `chosen_callsign`); the fallback is `seed_callsign` (not `fallback_callsign`).

SEARCH (around `agent_onboarding.py:531`):
```python
                lines = response.content.strip().split('\n')
                chosen = lines[0].strip().strip('"').strip("'")
                reason = lines[1].strip() if len(lines) > 1 else ""

                # Validate: not empty, not too long, not a duplicate
                if not chosen or len(chosen) > 30:
                    chosen = seed_callsign
                    reason = "Default callsign accepted."
```

REPLACE:
```python
                lines = response.content.strip().split('\n')
                chosen = lines[0].strip().strip('"').strip("'")
                reason = lines[1].strip() if len(lines) > 1 else ""

                # AD-499: validate self-chosen callsign against naming policy
                if self._config.naming.enabled:
                    from probos.naming import AgentNamingPolicy
                    extra = frozenset(self._config.naming.extra_banned_words)
                    policy = AgentNamingPolicy(banned=extra)
                    validation = policy.validate(chosen)
                    if validation.accepted:
                        chosen = validation.normalized
                    else:
                        logger.warning(
                            "AD-499: callsign '%s' rejected (%s); using seed",
                            chosen, validation.reason,
                        )
                        chosen = seed_callsign
                        reason = f"AD-499: rejected ({validation.reason}); seed accepted."

                # Validate: not empty, not too long, not a duplicate
                if not chosen or len(chosen) > 30:
                    chosen = seed_callsign
                    reason = "Default callsign accepted."
```

Then emit `AGENT_SELF_NAMED` after the registry update at line 228. Insert AFTER the existing `self._callsign_registry.set_callsign(...)` line:

```python
                        # AD-499: emit self-naming event
                        if self._event_log:
                            try:
                                await self._event_log.log(
                                    category="naming",
                                    event="agent_self_named",
                                    agent_type=agent.agent_type,
                                    data={"agent_id": agent.id, "callsign": chosen},
                                )
                            except Exception:
                                logger.warning("AD-499: AGENT_SELF_NAMED log failed", exc_info=True)
```

> Verify-first: `EventLog` API is `log(...)` not `append(...)` — verified at `src/probos/substrate/event_log.py:94`. The existing site in `agent_onboarding.py:364` uses the same `log()` shape.

> `AgentNamingPolicy.__init__` accepts `banned: frozenset[str]` (the public `banned_words` defaults are merged with the extras inside the policy class — see Section 1). Caller passes only the extras.

---

## Section 1 (extended): also tighten `AgentNamingPolicy` constructor to merge extras

The `AgentNamingPolicy.__init__` accepts an additional `banned` parameter that is merged with `_BANNED_WORDS_DEFAULT` internally:

```python
class AgentNamingPolicy:
    def __init__(self, *, banned: frozenset[str] = frozenset()) -> None:
        merged = frozenset(b.lower() for b in (banned | _BANNED_WORDS_DEFAULT))
        self._banned = merged
```

Callers pass only the extras; defaults are always applied.

## Section 6: REMOVED

Federation display integration deferred. `FederationDisplayFormat` is a pure helper introduced by Section 1 and used by future federation work. There is no existing peer-display path in `src/probos/federation/router.py` (verified — `select_peers` and `peer_has_capability` are the only public methods). Adding an unused helper to `router.py` would be dead code.

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
- **Federation integration is deferred** — `FederationDisplayFormat` is a pure helper available for future federation work. No peer-display path exists in `src/probos/federation/router.py` today (verified — only `select_peers` and `peer_has_capability` are public). Adding an unused helper would be dead code; future federation surfaces will adopt the helper at construction time.
- The naming ceremony LLM prompt is unchanged. AD-499 only validates the LLM's output.
- The seed-pool selection is **deterministic** by design. Different ProbOS instances with the same `instance_id` produce the same name; `instance_id` is a UUID v4 in practice so collisions are infinitesimal.
- **Pre-existing dead path noted:** `agent_onboarding.py:470` reads `getattr(getattr(self._config, 'system', None), 'ship_name', None)` and always falls back to `"ProbOS"` because `SystemInfo` has no `ship_name` field (only `name`, `version`, `log_level` — verified at `config.py:1384–1389`). AD-499 does NOT fix this pre-existing bug — it routes through `vi.name` (the real source of truth) instead. Document the `ship_name` attribute as an out-of-scope cleanup for a future BF.

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
- `src/probos/startup/communication.py`: ~22 lines added (Section 4 ShipNamingPolicy + SHIP_NAMED emit at the existing `vi = ontology.get_vessel_identity()` seam, line ~399).
- `src/probos/agent_onboarding.py`: ~22 lines added (Section 5: AgentNamingPolicy validation + AGENT_SELF_NAMED log).
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

## Verified Against Codebase (2026-04-30, updated 2026-05-01)

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

grep -n "vessel_name=vi.name" src/probos/startup/communication.py
  403:            vessel_name=vi.name,
  427:                        vessel_name=vi.name,

grep -n "vi = ontology.get_vessel_identity" src/probos/startup/communication.py
  400:        vi = ontology.get_vessel_identity()

grep -n "run_naming_ceremony" src/probos/agent_onboarding.py
  465:    async def run_naming_ceremony(self, agent: Any) -> str:

grep -n "seed_callsign\|chosen = lines" src/probos/agent_onboarding.py
  467:        seed_callsign = agent.callsign  # from CallsignRegistry
  532:                chosen = lines[0].strip().strip('"').strip("'")
  537:                if not chosen or len(chosen) > 30:

grep -n "self._event_log.log" src/probos/agent_onboarding.py
  364:        await self._event_log.log(

grep -n "async def log\|async def append" src/probos/substrate/event_log.py
  94:    async def log(
  (no `append` method — confirms phantom)

grep -n "class CallsignRegistry" src/probos/crew_profile.py
  305: class CallsignRegistry:

grep -n "naming_ceremony" src/probos/config.py
  1026:    naming_ceremony: bool = True  # If False, agents keep seed callsigns

grep -n "class SystemInfo" src/probos/config.py
  1384: class SystemInfo(BaseModel):
  (verified — only name/version/log_level fields; no ship_name)

grep -n "DISCLOSURE_FILTERED" src/probos/events.py
  179:    DISCLOSURE_FILTERED = "disclosure_filtered"  # AD-679

grep -rn "SHIP_NAMED\|AGENT_SELF_NAMED" src/probos/
  (no matches — names are free)

grep -rn "ShipNamingPolicy\|AgentNamingPolicy\|FederationDisplayFormat" src/probos/
  (no matches — AD-499 introduces these)

ls src/probos/federation/
  __init__.py  bridge.py  mock_transport.py  nats_transport.py  router.py  transport.py

grep -n "def " src/probos/federation/router.py
  29:    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
  36:    def peer_has_capability(self, peer_node_id: str, intent_name: str) -> bool:
  (no peer-display path — federation Section 6 deferred)

grep -n "onboarding: OnboardingConfig" src/probos/config.py
  1526:    onboarding: OnboardingConfig = OnboardingConfig()

grep -n "from pydantic import" src/probos/config.py
  10: from pydantic import BaseModel, Field, field_validator, model_validator
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-499-ship-crew-naming-conventions-review.md`:

- **Required #1 (`EventLog.append` phantom):** Section 5 now uses `self._event_log.log(category=..., event=..., data=...)` — the real EventLog API at `event_log.py:94`. Phantom `append` removed.
- **Required #2 (`_BANNED_DEFAULT`, wrong variable name):** Section 5 now keys on the real local variables (`chosen`, `seed_callsign`) from `agent_onboarding.py:530-545`. The `_BANNED_DEFAULT` splat is gone — Section 1 (extended) now folds defaults into `AgentNamingPolicy.__init__` so callers pass only extras.
- **Required #3 (Section 4 wrong layer):** Section 4 moved from `identity.py` to `startup/communication.py` line 399. SEARCH/REPLACE keyed on `vi = ontology.get_vessel_identity()`. Emit goes through `runtime.emit_event` per the AD-680 standard.
- **Required #4 (Section 6 dead code):** Section 6 removed entirely. Federation integration deferred to a future AD; documented in "What This Does NOT Change".
- **Required #5 (`SystemInfo.ship_name` pre-existing bug):** documented as out-of-scope in "What This Does NOT Change". AD-499 routes through `vi.name` (the real source of truth) and does not silently propagate the bug.
- **Recommended R1 (runtime.emit_event):** Section 4 now uses `runtime.emit_event(EventType.SHIP_NAMED, {...})` directly.
- **Recommended R2 (`banned_words` accessor):** kept as a `@property`-equivalent attribute access since the policy class is small. Non-blocking style choice.
- **Recommended R3 (test for distinct-instance distinct-name):** tracked for the test pass; the test plan should add an assertion that two distinct instance_ids produce different names with high probability. Builder discretion.
- **Recommended R4 (DECISIONS.md pool size):** the prompt's tracking section already calls for an optional DECISIONS.md entry; pool-size rationale should be included.
- **Nits:** alignment between `_CALLSIGN_RE` and the LLM prompt's "alphabetic" constraint deferred — the policy is more permissive than the LLM prompt; this asymmetry is intentional (validation accepts hyphens/underscores even if the LLM rarely produces them).

---

## Revision 2 (2026-05-01, after second-pass review)

Applied second-pass findings from `prompts/Reviews/ad-499-ship-crew-naming-conventions-review.md` (Second-Pass Review section):

- **New Required #1 (`runtime.emit_event` is wrong — `init_communication` takes `emit_event_fn`):** Section 4's emit call switched from `runtime.emit_event(...)` to `emit_event_fn(...)`. The verify-first note now correctly cites `emit_event_fn` at `communication.py:46`. The Revision-1 note above said "Emit goes through `runtime.emit_event`" — that was the slip; `init_communication`'s actual signature uses the `emit_event_fn` parameter.
- **New Nit #1 (`chosen_callsign` variable-name regression):** the AGENT_SELF_NAMED emit block in Section 5 referenced `chosen_callsign` instead of the real local `chosen`. Fixed.
- **New Nit #2 (Pre-Commit Sanity Check stale file list):** the expected-delta list still mentioned `identity.py` and `federation/router.py` from the original (pre-Revision-1) layer-relocation. Replaced with `startup/communication.py` (the real Section 4 site) and updated line counts.

No source-side rework. All 4 edits are documentation/spec corrections to make the prompt match the actual function signatures the Builder will encounter.
