# AD-1346 M1a: `IdentityRef` and the `IdentityService` facade (epic #1601, checklist M1, first slice)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20
**Status:** build-ready contract. **Tier: HIGH** (identity; a shared contract M3 freezes on). Confirmed, not lowered.
**Number:** rides under **AD-1346** (the epic). No new number: M3 (#1604) also takes none. Ceiling run 2026-10-20 with `scripts/ad_ceiling.py`: AD-1346 (git subjects and issue titles), next free AD-1347. BF ceiling BF-909 (orchestrator's run). Nothing allocated here.
**Base:** `origin/main` `b67e9e60be0e7bb873438b63d3c1ea1d55f57c40`.
**Dependencies:** BF-907 (merged, PR #1600: `resolve_slot_id`). Blocks M3 (#1604): M3's contract is drafted on the `IdentityRef` this slice freezes.
**Not concurrent with:** BF-908 (in review). It edits `runtime.py` around Phase 1a (`:2765-2773` on this base), `startup/finalize.py` and `credential_store.py`. This slice touches none of those regions. Its nearest `runtime.py` anchor is `:2801-2806`. Re-verify Section 3 after BF-908 merges.
**Estimated tests:** 16 new (13 unit and structural, 3 real-boot). No existing test changes.

---

## Problem

Trust is keyed by **slot id** (BF-907, `DECISIONS.md:243`). An agent's identity takes six forms (`docs/architecture/architecture-review-2026-10-20.md:74-81`): slot id, certificate UUID, `did:probos` DID, asset-tag UUID, callsign and agent type. BF-907 added one resolver, `AgentIdentityRegistry.resolve_slot_id` (`src/probos/identity.py:804-827`), and only trust and the stop route use it (`consensus/trust.py:305`, `startup/trust_identity.py:51,57`, `routers/agent_stop.py:62`). The review counts at least 18 other local resolvers (`architecture-review-2026-10-20.md:84`).

M3 (#1604) will record a shadow admission decision for every unit of work, for at least 7 days. If it records raw agent ids, its evidence carries BF-907's mismatch between sovereign UUID and slot, and its record schema would have to migrate inside the window. M3 needs one typed identity, resolved in one place, with a frozen JSON form, **before** its contract is drafted.

Three facts constrain the design:

1. `resolve_slot_id` deliberately returns **None for a slot id** (`identity.py:808-810`, pinned by `tests/test_bf907_trust_identity.py:340-342`), so it cannot be the facade's whole answer.
2. `get_by_slot` is `self._slot_cache.get(slot_id)` (`identity.py:794`). An unhashable key raises `TypeError`. `CallsignRegistry.resolve` calls `callsign.lower()` (`crew_profile.py:715`), so a non-string raises `AttributeError`. The facade must guard both.
3. **Crew certificates are issued in Phase 7, not Phase 2.** At wiring the onboarding service has `ontology=None` (`runtime.py:2797`), so a crew agent's certificate is deferred (`agent_onboarding.py:430-431`). `startup/communication.py:895-921` issues it later. Non-crew agents get an asset tag at wiring (`agent_onboarding.py:461-476`). A facade built at Phase 2 must therefore hold **references**, not copies.

## Solution

1. Add a new top-level module, `src/probos/identity_service.py`. It holds:
   - **`IdentityRef`**: a frozen value with five `str` fields (`slot_id`, `sovereign_id`, `did`, `callsign`, `agent_type`) and a stable `to_dict()`.
   - **`IdentityService`**: a synchronous facade with two public methods, `resolve(key)` for machine keys and `resolve_callsign(callsign)` for names. Both work by delegation to `AgentIdentityRegistry` (`get_by_slot`, `get_asset_by_slot`, `resolve_slot_id`, which owns `parse_did`) and to `CallsignRegistry` (`resolve`, `get_callsign`).
2. The runtime builds the facade **once, at Phase 2 entry**, before any agent is wired, and exposes it as `runtime.identity_service`. Shutdown releases it together with the identity registry.
3. **No consumer migrates in this slice.** Behaviour is unchanged for every existing caller. There is no route, no persisted schema, no config field and no new event type.

---

## Decisions

| # | Decision | Rejected alternative | Why |
|---|---|---|---|
| D1 | **The number rides under AD-1346**, as M3 (#1604) does. | Its own AD | It is a slice of the epic's checklist item M1, and the epic holds the number. |
| D2 | **`IdentityRef` v1 fields, frozen for M3.** `slot_id` is authoritative (the store key, per BF-907). `sovereign_id` holds the certificate UUID or, for an asset, the asset-tag UUID, with the same meaning as `agent.sovereign_id` (`agent_onboarding.py:456,475`). `did` is the agent DID, or `""` for an asset. `callsign` is the **live** callsign at resolution time (`CallsignRegistry.get_callsign`), or `""`. `agent_type` is the certificate's agent type or the asset type. All are exact `str`. `slot_id` and `sovereign_id` are non-empty. | Carrying `embodiment` now; carrying the certificate's birth callsign | Embodiment arrives with AD-1342 as an **additive** key. The certificate's callsign is a birth record, and the naming ceremony changes the live one (`crew_profile.py:752-759`). |
| D3 | **Equality and hash use `(slot_id, sovereign_id)`.** The other three fields are `compare=False`. A slot reused by another identity (`reassign_slot`, `identity.py:1573-1607`) gives a different ref. A callsign change does not. | Slot only; all fields | With slot-only equality, two agents that occupied one slot in turn would be the same ref. With all fields, a naming ceremony would split one agent. The store key stays `ref.slot_id`. |
| D4 | **The frozen JSON form.** `to_dict()` returns exactly `IDENTITY_REF_KEYS = ("slot_id", "sovereign_id", "did", "callsign", "agent_type")`, in that order, every value a `str`. **Evolution rule:** a v1 key is never renamed, removed or retyped. A new key is appended, and readers must not require it. A test pins this (T10). M1a has no `from_dict`. M3's records are read back as dicts. | A version key; a `from_dict` | Additive keys need no version. A `from_dict` would be a second way to construct a ref (D5). |
| D5 | **Only the facade constructs a ref in `src/`.** An AST test (T12) finds exactly the two constructions in `identity_service.py` and none elsewhere under `src/probos`. Tests may construct one directly. | A private constructor token | Python cannot enforce privacy. A structural test can, and it fails when a new construction appears. |
| D6 | **Two methods, because a callsign is a name, not a key.** `resolve(key)` accepts a slot id, certificate UUID, agent DID or asset-tag UUID. `resolve_callsign(callsign)` accepts a callsign. `resolve("Meridian")` returns None. | One `resolve` that tries every form | Free text would then resolve to an agent. Each future migration family knows which form it holds. |
| D7 | **Precedence.** A slot is looked up first: its certificate, then its asset tag. Any other key goes through `resolve_slot_id`, and its slot through the same lookup. **The certificate wins** on a slot that has both. | Asset first | The live boot can give one slot both. `is_crew_agent` falls back to a legacy set when `ontology` is None at Phase 2 (`crew_utils.py:73-76`), and Phase 7 issues the certificate (`communication.py:899`). Onboarding's last write is the certificate (`communication.py:920`). |
| D8 | **None, never an exception, for a bad key.** An empty, non-string, unknown or callsign-shaped key returns None, as does an identity bound to more than one slot (`resolve_slot_id`'s rule, `identity.py:822-826`). `resolve_callsign` returns None when the callsign is unknown, when no live agent has it, and when its live agent has no certificate or tag. Corrupt registry data (a stored certificate with an empty UUID) **propagates** through `IdentityRef.__post_init__`, because it is a data-integrity fault (tier 3). The facade never creates, changes or persists an identity. | Raising `KeyError` for unknown keys | Every caller today treats "no identity" as a value. M3 must record an unresolved principal rather than crash a dispatch. |
| D9 | **Location and shape.** `src/probos/identity_service.py` is a top-level module, so it is unranked in the layer check (`check_architecture_principles.py:80-82`). At runtime it imports only `__future__`, `dataclasses` and `typing`. The two registries are imported only under `TYPE_CHECKING` (T13). It is synchronous, with no awaits, I/O or locks: M3's `decide()` is "a library on the dispatch loop … no awaits" (#1604, blind spot 3). It holds references to both registries, so it sees every later certificate, tag and callsign change. | Methods on `AgentIdentityRegistry` | That class already has 30 direct methods (`identity.py:529-1650`, over the 15-method SRP trigger, `check_architecture_principles.py:188`). The facade composes over it. |
| D10 | **Wiring.** The facade is built in `ProbOSRuntime.start` **after the onboarding service and before `create_agent_fleet`** (`runtime.py:2804-2806`), from `infra.identity_registry` (typed non-optional, `startup/results.py:83`) and `self.callsign_registry` (built in `__init__`, `runtime.py:723-725`). Shutdown sets it to None inside the identity-registry block (`startup/shutdown.py:1429-1433`). | Building it in `boot_infrastructure`; building it next to `runtime.py:2760` | `boot_infrastructure` does not receive the callsign registry. The second site is 5 lines from BF-908's Phase 1a region. |
| D11 | **No checker rule in M1a. It goes to M1b, the first migration slice (telemetry).** Reasons: (a) the dominant ad-hoc shape is an **expression**, `getattr(agent, 'sovereign_id', None) or agent.id` (`proactive.py:2488-2489`, `cognitive_agent.py:10283-10291`, per the BF-907 contract's table), not a call, so a detector built before any family has migrated would freeze an unproven premise; (b) the baseline is meaningful only once the facade has a consumer to migrate to; (c) the only code added between M1a and M1b is M3, whose contract I draft, and it is bound below to use the facade. **M1b's detector premise:** an AST rule over `src/probos` (excluding `identity.py` and `identity_service.py`) flags (1) a `BoolOp(Or)` with an operand reading attribute or `getattr` name `sovereign_id`; (2) a call to `parse_did`, `resolve_slot_id`, `get_by_slot` or `get_asset_by_slot`; (3) a `.resolve(` call on a receiver named `callsign_registry` or `_callsign_registry`. Counts are kept per file against the review's list (`architecture-review-2026-10-20.md:84`), re-verified on M1b's base, plus a premise test that the detector flags BF-907's pre-fix line. | Carrying a regex count now | A guard whose detector misses the real shape gives false assurance. |
| D12 | **No reason code for an unresolved identity in v1.** | A `Resolution` result type (W3C DID Resolution distinguishes `notFound` from `invalidDid`) | No consumer needs it yet. If M3's shadow period shows unresolved principals, an additive reason can follow. |

**Binding on M3's contract (recorded here, not built):** the principal of a decision is `IdentityService.resolve(agent_id)`. A record embeds `ref.to_dict()` and keys on `ref.slot_id`. A None is recorded as an unresolved principal carrying the raw key, never as a guessed key. Crew agents are unresolved between Phase 2 and Phase 7 (Problem, fact 3). M3 calls the facade on the event loop only (blind spot 8).

---

## Implementation

Each section can be built on its own in the order given. Stage only the paths named. Never `git add -A`.

### Section 1: `src/probos/identity_service.py` (new file, full content)

```python
"""AD-1346 M1a: one identity reference, resolved in one place.

Trust and the other slot-keyed stores key an agent by its deployment slot id
(BF-907). Every other form an agent's identity takes resolves to that slot here,
by delegation to the registry that owns the form:

* a slot id: ``AgentIdentityRegistry.get_by_slot`` and ``get_asset_by_slot``;
* a birth-certificate UUID, a did:probos agent DID or an asset-tag UUID:
  ``AgentIdentityRegistry.resolve_slot_id`` (BF-907's resolver, which owns
  ``parse_did``);
* a callsign: ``CallsignRegistry.resolve`` and ``get_callsign``.

The facade copies no resolution logic and holds references, so a certificate,
tag or callsign change is seen at the next call. It never creates or changes an
identity, persists nothing and is synchronous: AD-1346 M3's admission decision
calls it on the dispatch loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.crew_profile import CallsignRegistry
    from probos.identity import AgentIdentityRegistry

#: AD-1346 M1a (frozen for M3): the keys of ``IdentityRef.to_dict()``, in order. A later
#: key (AD-1342's embodiment) is appended; none of these is ever renamed, removed or
#: retyped, so a record that embeds a ref never migrates.
IDENTITY_REF_KEYS: tuple[str, ...] = ("slot_id", "sovereign_id", "did", "callsign", "agent_type")


@dataclass(frozen=True, slots=True)
class IdentityRef:
    """One agent's identity as ``IdentityService`` resolved it (the only constructor in ``src``).

    ``slot_id`` is the authoritative key: trust and the other slot-keyed stores key by it
    (BF-907). ``sovereign_id`` is the birth-certificate UUID, or the asset-tag UUID for an
    asset, as ``agent.sovereign_id`` is set at onboarding. ``did`` is the agent DID ("" for an
    asset). ``callsign`` is the live callsign when resolved ("" if none). ``agent_type`` is the
    certificate's agent type or the asset type.

    Two refs are equal when ``slot_id`` and ``sovereign_id`` are, so a slot reused by another
    identity is a different ref; ``did``, ``callsign`` and ``agent_type`` take no part.
    """

    slot_id: str
    sovereign_id: str
    did: str = field(compare=False)
    callsign: str = field(compare=False)
    agent_type: str = field(compare=False)

    def __post_init__(self) -> None:
        for name in IDENTITY_REF_KEYS:
            if type(getattr(self, name)) is not str:
                raise TypeError(f"IdentityRef.{name} must be a str")
        if not self.slot_id or not self.sovereign_id:
            raise ValueError("IdentityRef needs a slot id and a sovereign id")

    def to_dict(self) -> dict[str, str]:
        """The stable JSON form (``IDENTITY_REF_KEYS``, in order) for records that embed a ref."""
        return {name: getattr(self, name) for name in IDENTITY_REF_KEYS}


class IdentityService:
    """AD-1346 M1a: the one place an identity in any form resolves to an ``IdentityRef``.

    Consumers: AD-1346 M3's admission service (the principal of a shadow decision) and the
    M1 slices that retire the local resolvers one family at a time.
    """

    def __init__(self, identity_registry: AgentIdentityRegistry, callsign_registry: CallsignRegistry) -> None:
        if identity_registry is None or callsign_registry is None:
            raise TypeError("IdentityService needs the identity registry and the callsign registry")
        self._identities = identity_registry
        self._callsigns = callsign_registry

    def resolve(self, key: str) -> IdentityRef | None:
        """The ref for a slot id, a birth-certificate UUID, an agent DID or an asset-tag UUID.

        A slot id is looked up first; any other key goes through BF-907's ``resolve_slot_id``.
        None for an empty or non-string key, an unknown key, a callsign (use
        ``resolve_callsign``) and an identity bound to more than one slot. Never raises for a
        key; never creates or changes an identity.
        """
        if type(key) is not str or not key:
            return None
        ref = self._ref_for_slot(key)
        if ref is not None:
            return ref
        slot_id = self._identities.resolve_slot_id(key)
        if slot_id is None:
            return None
        return self._ref_for_slot(slot_id)

    def resolve_callsign(self, callsign: str) -> IdentityRef | None:
        """The ref of the live agent a callsign names, through ``CallsignRegistry.resolve``.

        None for an empty or non-string callsign, an unknown callsign, a callsign with no live
        agent and a live agent with no certificate or asset tag. Where several live agents
        share the callsign's type, ``CallsignRegistry.resolve`` picks one, as it does for its
        other callers.
        """
        if type(callsign) is not str or not callsign:
            return None
        entry = self._callsigns.resolve(callsign)
        if entry is None:
            return None
        agent_id = entry.get("agent_id")
        if type(agent_id) is not str or not agent_id:
            return None
        return self._ref_for_slot(agent_id)

    def _ref_for_slot(self, slot_id: str) -> IdentityRef | None:
        """The ref of a slot: its birth certificate first, else its asset tag, else None."""
        cert = self._identities.get_by_slot(slot_id)
        if cert is not None:
            return IdentityRef(
                slot_id=slot_id,
                sovereign_id=cert.agent_uuid,
                did=cert.did,
                callsign=self._callsigns.get_callsign(cert.agent_type),
                agent_type=cert.agent_type,
            )
        tag = self._identities.get_asset_by_slot(slot_id)
        if tag is not None:
            return IdentityRef(
                slot_id=slot_id,
                sovereign_id=tag.asset_uuid,
                did="",
                callsign=self._callsigns.get_callsign(tag.asset_type),
                agent_type=tag.asset_type,
            )
        return None
```

Notes for the Builder:
- `IdentityService` has 4 methods and is well under the SRP triggers.
- Do not add a `from_dict`, a module-level singleton, a cache, a logger call per resolution or an `async` method. Each would break D4, D9 or T13 to T15.
- `if slot_id is None:` is kept for typing (mypy). Removing it would be an equivalent mutant, because `get_by_slot(None)` returns None. That is why it is not in the mutation table.

### Section 2: `src/probos/runtime.py`, declarations

**2a.** In the `TYPE_CHECKING` block (`runtime.py:158`).

SEARCH:
```python
    from probos.identity import AgentIdentityRegistry
    from probos.identity_key_binding import IdentityKeyBinding  # AD-1196
    from probos.infrastructure.backup import BackupResult, BackupService
```
REPLACE:
```python
    from probos.identity import AgentIdentityRegistry
    from probos.identity_key_binding import IdentityKeyBinding  # AD-1196
    from probos.identity_service import IdentityService  # AD-1346 M1a
    from probos.infrastructure.backup import BackupResult, BackupService
```

**2b.** In the class-level annotations.

SEARCH:
```python
    identity_registry: AgentIdentityRegistry | None
    identity_key_binding: IdentityKeyBinding | None  # AD-1196
    pool_scaler: PoolScaler | None
```
REPLACE:
```python
    identity_registry: AgentIdentityRegistry | None
    identity_key_binding: IdentityKeyBinding | None  # AD-1196
    identity_service: IdentityService | None  # AD-1346 M1a: built at Phase 2 entry, released with the identity registry
    pool_scaler: PoolScaler | None
```

**2c.** In `__init__`.

SEARCH:
```python
        # --- Sovereign Agent Identity (AD-441) ---
        self.identity_registry: AgentIdentityRegistry | None = None
        self.identity_key_binding: IdentityKeyBinding | None = None  # AD-1196
```
REPLACE:
```python
        # --- Sovereign Agent Identity (AD-441) ---
        self.identity_registry: AgentIdentityRegistry | None = None
        self.identity_key_binding: IdentityKeyBinding | None = None  # AD-1196
        self.identity_service: IdentityService | None = None  # AD-1346 M1a: set at Phase 2 entry in start()
```

`runtime.py:3` is `from __future__ import annotations`, so the annotations are not evaluated at runtime.

### Section 3: `src/probos/runtime.py`, construction at Phase 2 entry

SEARCH:
```python
            ward_room=None,
            acm=None,
        )

        fleet = await create_agent_fleet(
```
REPLACE:
```python
            ward_room=None,
            acm=None,
        )

        # AD-1346 M1a: the one identity facade, over the registry Phase 1 started and the
        # callsign registry built in __init__. Built before any agent is wired; it holds
        # references, so the crew certificates Phase 7 issues resolve through it.
        from probos.identity_service import IdentityService

        self.identity_service = IdentityService(infra.identity_registry, self.callsign_registry)

        fleet = await create_agent_fleet(
```

`infra` is the local bound at `runtime.py:2748` in the same method. `infra.identity_registry` is typed `"AgentIdentityRegistry"`, not optional (`startup/results.py:83`). Do not pass `self.identity_registry`: it is typed `| None`.

### Section 4: `src/probos/startup/shutdown.py`, release with the registry

SEARCH:
```python
    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        with steps("identity registry stop", runtime.identity_registry):
            await runtime.identity_registry.stop()
        runtime.identity_registry = None
```
REPLACE:
```python
    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        with steps("identity registry stop", runtime.identity_registry):
            await runtime.identity_registry.stop()
        runtime.identity_registry = None
        runtime.identity_service = None  # AD-1346 M1a: the facade holds the registry; released with it
```

This is not a guarded `steps(...)` call, so `test_every_guarded_step_in_shutdown_has_a_case_in_this_file` (`tests/test_issue1419_failed_start_rollback.py:1392`) and `test_every_step_that_stops_a_component_hands_that_component_to_the_guard` (`:1399`) are unaffected. The line sits inside the `if` block, so a fake runtime without a registry gains no attribute.

---

## Tests

All state lives in `tmp_path`. The live data directory is never read. Nothing sleeps. Use the live shapes from `tests/test_bf907_trust_identity.py:60-67`: `SURGEON_SLOT`, `SURGEON_SECOND_SLOT`, `COUNSELOR_SLOT`, `TOOL_SLOT`, `RUNTIME_ID`, `PEER_KEY`. Define the constants and fixtures **locally**, mirroring `:75-121`: a real `AgentIdentityRegistry(data_dir=tmp_path / "identity")`, `start()`, then `start(instance_id=..., vessel_name=..., version="1")`, and an `_issue` helper over `resolve_or_issue` with the same keyword names (`identity.py:1004-1014`). Do not import from another test module.

### File 1: `tests/test_ad1346_identity_service.py` (unit and structural; 13 tests)

Shared fixtures:
- `registry` as above.
- `callsigns`: a real `CallsignRegistry()` (`crew_profile.py:663`). `load_from_profiles(str(tmp_path / "profiles"))` reads YAML files `surgeon.yaml` (`callsign: Meridian`), `counselor.yaml` (`callsign: Ezri`) and `scout.yaml` (`callsign: Wesley`) (`crew_profile.py:669-703`). It is bound with `bind_registry(agents)` to a real `AgentRegistry()` (`substrate/registry.py:24`). In that registry, `await agents.register(SimpleNamespace(id=..., agent_type=..., pool=<agent_type>, is_alive=True))` registers the live agents a test needs. `get_by_pool` matches on `pool` (`registry.py:61-62`).
- `service = IdentityService(registry, callsigns)`.

| # | Test | Proves | Does not prove |
|---|---|---|---|
| T1 | `test_resolve_a_slot_id_gives_its_certificate_ref` | `resolve(SURGEON_SLOT)` returns a ref with `slot_id == SURGEON_SLOT`, `sovereign_id == cert.agent_uuid`, `did == cert.did`, `callsign == "Meridian"`, `agent_type == "surgeon"`. Premise: `registry.resolve_slot_id(SURGEON_SLOT) is None` (BF-907 does not take slots, so the facade's slot path is its own). | live boot |
| T2 | `test_resolve_an_asset_slot_and_its_asset_uuid` | `tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")`. `resolve(TOOL_SLOT)` and `resolve(tag.asset_uuid)` both equal a ref with `sovereign_id == tag.asset_uuid`, `did == ""`, `agent_type == "calculator"`. | |
| T3 | **`test_the_facade_agrees_with_resolve_slot_id_over_every_identity_form`** | A populated registry (surgeon and counselor certificates, a tool tag). For **every** key K in {each slot, each certificate UUID, each DID, the asset UUID, `RUNTIME_ID`, `"system"`, `"captain"`, `PEER_KEY`, `"mcp-peer:tool-x"`, `"device:usb-1"`, an unknown UUID, an unknown DID, the ship DID `did:probos:<instance>`, a 5-part DID, `"Meridian"`}: if `identity.is_sovereign_identity_key(K)`, then `(service.resolve(K).slot_id if service.resolve(K) else None) == registry.resolve_slot_id(K)`; for each slot, `registry.resolve_slot_id(slot) is None` and `service.resolve(slot).slot_id == slot`; for every other key, both are None. Then `await registry.reassign_slot(surgeon.agent_uuid, SURGEON_SECOND_SLOT)` (ambiguous), and the same loop runs again. The surgeon UUID and DID now give None from both, and `resolve(SURGEON_SLOT)` and `resolve(SURGEON_SECOND_SLOT)` carry the same `sovereign_id` and are unequal. | that callsigns agree (T6) |
| T4 | `test_resolve_returns_none_for_empty_non_string_unknown_and_callsign_keys` | `resolve(x) is None` for `""`, `None`, `7`, `["x"]` (unhashable: kills M1), `b"x"`, `"Meridian"`, `"meridian"`, an unknown UUID and every non-candidate from T3. None of them raises. | |
| T5 | `test_the_certificate_wins_over_an_asset_tag_on_one_slot` | `tag = await registry.resolve_or_issue_asset_tag(SURGEON_SLOT, "surgeon", "surgeon")`, then `cert = await _issue(registry)`. This is the live order (D7). `resolve(SURGEON_SLOT).sovereign_id == cert.agent_uuid`, and `resolve(tag.asset_uuid)` has `slot_id == SURGEON_SLOT` and `sovereign_id == cert.agent_uuid`. Premise: `registry.get_asset_by_slot(SURGEON_SLOT) is tag` and `registry.get_by_slot(SURGEON_SLOT) is cert`. | |
| T6 | `test_resolve_callsign_names_the_live_agent_and_nothing_else` | Register live agents for the surgeon slot and `SCOUT_SLOT = "scout_scout_0_1a2b3c4d"`. The scout has no certificate or tag. `resolve_callsign("Meridian") == resolve_callsign("meridian") == resolve(SURGEON_SLOT)`. `resolve_callsign("Ezri")` is None (a profile with no live agent). `resolve_callsign("Wesley")` is None (a live agent with no identity). `resolve_callsign("Nobody")`, `("")`, `(None)` and `(["x"])` are None, and none raises (`["x"]` kills M5). | the order among several live agents (not changed) |
| T7 | `test_the_facade_reads_the_registries_live` | Build `service` **before** issuing. `resolve(SURGEON_SLOT) is None`. After `_issue`, it resolves (a reference, not a copy). Then `callsigns.set_callsign("surgeon", "Zed")`. The new ref has `callsign == "Zed"` while `cert.callsign == "Meridian"` (kills M9), and it equals the earlier ref and has the same hash (D3). | |
| T8 | `test_a_reused_slot_is_a_different_ref` | Issue surgeon and counselor. `before = resolve(SURGEON_SLOT)`, then `reassign_slot(counselor.agent_uuid, SURGEON_SLOT)`, then `after = resolve(SURGEON_SLOT)`. `before != after`, `len({before, after}) == 2`, `after.sovereign_id == counselor.agent_uuid`, and `resolve(surgeon.agent_uuid) is None` (bound to no slot). | |
| T9 | `test_identity_ref_rejects_non_str_and_empty_identity` | Direct construction (allowed in tests). Raises `TypeError` for a `str` subclass `class _S(str)` in `slot_id` (kills M14) and for `did=None`. Raises `ValueError` for `slot_id=""` and for `sovereign_id=""` (kills M15). | |
| T10 | **`test_identity_ref_v1_is_frozen`** (the M3 pin) | `IDENTITY_REF_KEYS == ("slot_id", "sovereign_id", "did", "callsign", "agent_type")`. `[f.name for f in dataclasses.fields(IdentityRef)] == list(IDENTITY_REF_KEYS)`. `[f.name for f in fields(IdentityRef) if f.compare] == ["slot_id", "sovereign_id"]` (kills M12, M13). For the T1 ref, `list(ref.to_dict()) == list(IDENTITY_REF_KEYS)` and `ref.to_dict() == {"slot_id": SURGEON_SLOT, "sovereign_id": cert.agent_uuid, "did": cert.did, "callsign": "Meridian", "agent_type": "surgeon"}` (kills M16, M17). Every value is `type(v) is str`. `json.loads(json.dumps(ref.to_dict())) == ref.to_dict()`. Assigning `ref.slot_id = "x"` raises `dataclasses.FrozenInstanceError`. Docstring line: *"Changing any assertion here breaks AD-1346 M3's shadow records; add keys at the end only (D4)."* | |
| T11 | `test_the_facade_never_creates_or_changes_an_identity` | Before and after calling every `resolve` and `resolve_callsign` input from T3 to T6, these are equal: `[c.agent_uuid for c in registry.get_all()]`, `[t.asset_uuid for t in registry.get_asset_tags()]`, `await registry.export_chain()`, `callsigns.all_callsigns()`, and `{s: registry.get_by_slot(s) for s in slots}`. Also `inspect.iscoroutinefunction(IdentityService.resolve)` and `(IdentityService.resolve_callsign)` are both False. `IdentityService(None, callsigns)` and `IdentityService(registry, None)` raise `TypeError` (kills M18). | |
| T12 | **`test_only_the_facade_constructs_an_identity_ref_in_src`** | An AST walk over every `src/probos/**/*.py` collects `ast.Call` nodes whose `func` is `Name(id="IdentityRef")` or `Attribute(attr="IdentityRef")`. Result: `{"probos/identity_service.py": 2}` exactly, which also proves the detector's premise that it finds the two real constructions. | `dataclasses.replace` copies (none exist; recorded in the residuals) |
| T13 | `test_the_facade_imports_no_resolution_logic` | An AST of `identity_service.py`. The module-level imports outside `if TYPE_CHECKING:` are exactly `{"__future__", "dataclasses", "typing"}`. Inside it they are exactly `{"probos.crew_profile", "probos.identity"}`. No `parse_did`, `re` or `is_sovereign_identity_key` import, so the module holds no copy of the logic (D9). | |

That is 13 tests. T10, T12 and T13 are the structural and freeze tests.

### File 2: `tests/test_ad1346_identity_service_boot.py` (a real boot; 3 tests)

Boot as `tests/test_bf906_crew_enrollment_boot.py:43-58` does: `SystemConfig()` with `onboarding.naming_ceremony = False`, `proactive_cognitive.enabled = False` and `qa.enabled = False`, then `ProbOSRuntime(config=..., data_dir=tmp_path / "data", llm_client=MockLLMClient())` and `await runtime.start()`, stopped in `finally`. Crew are selected with `is_crew_agent(a, rt.ontology)` (`crew_utils.py:69`).

| # | Test | Proves |
|---|---|---|
| T14 | **`test_after_a_real_boot_every_identified_agent_resolves_to_its_own_slot`** | Premises: at least one crew agent with a non-empty `did`, issued in Phase 7, which proves a reference rather than a copy; and at least one non-crew agent with `sovereign_id != ""` and `did == ""` (an asset). Then, for **every** `agent in rt.registry.all()` with `agent.sovereign_id`: `ref = rt.identity_service.resolve(agent.id)` has `ref.slot_id == agent.id`, `ref.sovereign_id == agent.sovereign_id`, `ref.did == agent.did` and `ref.callsign == rt.callsign_registry.get_callsign(agent.agent_type)`. For every crew agent where `rt.identity_registry.resolve_slot_id(agent.sovereign_id) == agent.id`: `resolve(agent.sovereign_id) == ref` and `resolve(agent.did) == ref`. Assert this held for at least one agent. For every crew agent whose type has a non-empty callsign and exactly one live agent in its pool: `rt.identity_service.resolve_callsign(callsign).slot_id == agent.id`. Assert at least one. **Does not prove:** agents with an empty `sovereign_id` (BF-907's finalize check covers crew). |
| T15 | **`test_the_facade_exists_before_the_fleet_and_a_failed_start_releases_it`** | Use `make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))` (`tests/fixtures/runtime_factory.py:95`, `tests/fixtures/runtime_lifecycle.py:74`) after `monkeypatch.chdir(tmp_path)`, as `tests/test_issue1419_failed_start_rollback.py:959-962` does. Then `inject_start_failure(monkeypatch, runtime, "fleet_entry", on_fire=lambda rt: seen.append(rt.identity_service))` (`runtime_lifecycle.py:336-373`; `fleet_entry` wraps `create_agent_fleet`). Run `with pytest.raises(InjectedStartFailure): await runtime.start()`. Assert `isinstance(seen[0], IdentityService)`: it was built **before** the fleet, which is the boot-order proof. Assert `runtime.identity_service is None` after the rollback (kills M20). |
| T16 | `test_a_clean_stop_releases_the_facade` | Boot, assert `rt.identity_service is not None`, `await rt.stop()`, then assert `rt.identity_service is None` (kills M20). |

That makes **16 tests** in total (13 + 3).

---

## Milestones (about 50 tool calls each)

| M | Scope | Focused checks (run at `-n 0`; never `pytest tests/`) |
|---|---|---|
| **M1** | Section 1 and File 1 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_identity_service.py -v -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf907_trust_identity.py -q -n 0 -k "resolve_slot_id"`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` |
| **M2** | Sections 2 to 4 and File 2 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_identity_service_boot.py -v -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_issue1419_failed_start_rollback.py -q -n 0 -k "a_failed_start_rolls_back_everything or every_guarded_step or every_step_that_stops or a_clean_stop_makes_every_session_write"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf906_crew_enrollment_boot.py -q -n 0 -k "every_boot_wired"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf907_trust_identity.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_seam_contracts.py` |
| **M3** | The mutation campaign (below), the trackers, and the section audit (each Section maps to code, each T to a test) | Rerun Files 1 and 2 after the trackers. The broad gate is run once by the main session, not the Builder. |

---

## Mutation table (run once on the final tree; every anchor is a whole, unique, stripped line)

Apply one mutant at a time, run the named tests at `-n 0`, and restore. **Campaign of record:** record the base tree SHA and the sha256 of `src/probos/identity_service.py`, `src/probos/runtime.py` and `src/probos/startup/shutdown.py`. A later round whose files match does not repeat it. If one differs, rerun only the rows anchored in that file.

| ID | File | Line (stripped) → mutant | Killed by |
|---|---|---|---|
| M1 | identity_service.py | `if type(key) is not str or not key:` → `if not key:` | T4 |
| M2 | identity_service.py | `ref = self._ref_for_slot(key)` → `ref = None` | T1, T3 |
| M3 | identity_service.py | `slot_id = self._identities.resolve_slot_id(key)` → `slot_id = None` | T2, T3 |
| M4 | identity_service.py | `return self._ref_for_slot(slot_id)` → `return self._ref_for_slot(key)` | T2, T3 |
| M5 | identity_service.py | `if type(callsign) is not str or not callsign:` → `if not callsign:` | T6 |
| M6 | identity_service.py | `entry = self._callsigns.resolve(callsign)` → `entry = None` | T6, T14 |
| M7 | identity_service.py | `cert = self._identities.get_by_slot(slot_id)` → `cert = None` | T1, T3, T14 |
| M8 | identity_service.py | `if cert is not None:` → `if False:` | T1, T5 |
| M9 | identity_service.py | `callsign=self._callsigns.get_callsign(cert.agent_type),` → `callsign=cert.callsign,` | T7 |
| M10 | identity_service.py | `sovereign_id=cert.agent_uuid,` → `sovereign_id=cert.did,` | T1, T14 |
| M11 | identity_service.py | `tag = self._identities.get_asset_by_slot(slot_id)` → `tag = None` | T2, T14 |
| M12 | identity_service.py | `did: str = field(compare=False)` → `did: str` | T10 |
| M13 | identity_service.py | `sovereign_id: str` → `sovereign_id: str = field(compare=False)` | T8, T10 |
| M14 | identity_service.py | `if type(getattr(self, name)) is not str:` → `if not isinstance(getattr(self, name), str):` | T9 |
| M15 | identity_service.py | `if not self.slot_id or not self.sovereign_id:` → `if not self.slot_id:` | T9 |
| M16 | identity_service.py | `IDENTITY_REF_KEYS: tuple[str, ...] = ("slot_id", "sovereign_id", "did", "callsign", "agent_type")` → drop `"agent_type"` | T10 |
| M17 | identity_service.py | `return {name: getattr(self, name) for name in IDENTITY_REF_KEYS}` → `... in IDENTITY_REF_KEYS[:-1]}` | T10 |
| M18 | identity_service.py | `if identity_registry is None or callsign_registry is None:` → `if False:` | T11 |
| M19 | runtime.py | `self.identity_service = IdentityService(infra.identity_registry, self.callsign_registry)` → `self.identity_service = None` | T14, T15 |
| M20 | shutdown.py | `runtime.identity_service = None  # AD-1346 M1a: the facade holds the registry; released with it` → `pass` | T15, T16 |

Equivalent mutants, excluded with reasons:
- `if slot_id is None:` removed: `get_by_slot(None)` returns None.
- `if type(agent_id) is not str or not agent_id:` → `if agent_id is None:`: `CallsignRegistry.resolve` sets `agent_id` only to None or `agent.id` (`crew_profile.py:722,730`).

---

## What This Does NOT Change

- **No local resolver is migrated.** The 18 sites (`architecture-review-2026-10-20.md:84`), `routers/agent_stop.py:62` and `TrustNetwork`'s injected resolver (`startup/trust_identity.py:51`) are unchanged. Those are the M1 migration slices (M1b onward: telemetry, commands, counselor, Ward Room and fan-out, dispatch).
- **No checker rule** (D11, M1b).
- `AgentIdentityRegistry`, `CallsignRegistry`, `parse_did`, `is_sovereign_identity_key`, `resolve_slot_id` and `TrustNetwork` are unchanged. No store key changes; trust stays slot-keyed.
- No route, no persisted schema or table, no config field (`config.py` untouched; `check_config_facade.py` unaffected), no `EventType` (the AD-1195 freeze in `tests/test_ad1195_eventlog_pair_freeze.py` is unaffected), no store registration.
- `startup/finalize.py`, `credential_store.py` and `runtime.py` Phase 1 and 1a (`:2745-2773`) are untouched (BF-908's regions).
- No sovereign-id rekey (#1604 "Do Not Build"), and no embodiment field (AD-1342).

## Compatibility

Every existing caller behaves exactly as before. The only additions are a new module and a new public runtime attribute, `identity_service`. It is None until Phase 2 entry, and None again after shutdown or a rolled-back start. Absences are listed below.

## Tracking

- `PROGRESS.md`: a new top entry, `**AD-1346 M1a (date), #1601 -- one identity reference, resolved in one place.** ...`, in the style of `PROGRESS.md:3-9`. State: the `IdentityRef` v1 key set frozen for M3, the facade at Phase 2 entry, and that no resolver is migrated yet.
- `DECISIONS.md`: a heading `### AD-1346 M1a -- IdentityRef and the IdentityService facade (date, #1601)`, appended after the BF-909 entry (`DECISIONS.md:369`). Include D1-D12, the binding on M3 and the campaign of record.
- `docs/development/roadmap.md`: none (not a BF).
- GitHub (orchestrator): progress on #1601's checklist M1 ("M1a done; migrations and checker rule remain, M1b next"). A note on #1604 that `IdentityRef` v1 is frozen (T10), so M3's contract may be drafted. Filing a child issue for M1a, as was done for M3, is the orchestrator's call.

## Acceptance Criteria

1. `IdentityService.resolve` agrees with `AgentIdentityRegistry.resolve_slot_id` on every sovereign form, and adds the slot form, on a populated real registry, including the ambiguous state (T3).
2. After a real boot, every identified agent resolves to its own slot, sovereign id and DID, and crew certificates issued in Phase 7 resolve through the facade built in Phase 2 (T14).
3. The facade exists before `create_agent_fleet`, and a rolled-back start and a clean stop both release it (T15, T16).
4. `IdentityRef` v1 is pinned: keys, order, types, compare fields, JSON round trip and immutability (T10). Only `identity_service.py` constructs one in `src/` (T12).
5. The facade is synchronous, imports no resolution logic and never creates or changes an identity (T11, T13).
6. All 20 mutants are killed; the campaign of record is recorded.
7. `check_architecture_principles.py --check` and `check_seam_contracts.py` pass, and the M2 focused checks are green.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Diff Reviewer: properties to verify

1. `resolve` and `resolve_callsign` delegate. No DID parsing, UUID regex or cache copy is added.
2. No path writes to either registry, the ledger or any file.
3. Equality and hash use exactly `slot_id` and `sovereign_id`, and `to_dict` keys equal `IDENTITY_REF_KEYS` in order.
4. The construction sits after the onboarding service and before `create_agent_fleet`, uses `infra.identity_registry`, and touches nothing in `runtime.py:2745-2773`.
5. The shutdown release is inside the identity-registry block and is not a `steps(...)` call.
6. No existing test was edited.

---

## Verified Against Codebase (2026-10-20, on `b67e9e60`)

```
grep -n "^def parse_did\|^def is_sovereign_identity_key\|^class AgentIdentityRegistry\|def resolve_slot_id" src/probos/identity.py
  120: def parse_did(did: str) -> dict[str, str] | None:
  157: def is_sovereign_identity_key(key: str) -> bool:
  518: class AgentIdentityRegistry:
  804:     def resolve_slot_id(self, identity: str) -> str | None:
grep -n "def get_by_slot\|def get_asset_by_slot\|def get_all\|def get_asset_tags\|def resolve_or_issue\|def reassign_slot\|def export_chain" src/probos/identity.py
  787 get_by_slot -> self._slot_cache.get(slot_id) (:794); 887 get_asset_by_slot -> self._asset_cache.get (:889)
  796 get_all; 883 get_asset_tags; 870 resolve_or_issue_asset_tag(slot_id, asset_type, pool_name, tier=...)
  1004-1014 resolve_or_issue(slot_id, agent_type, callsign, instance_id, vessel_name, department, post_id, baseline_version)
  1573 reassign_slot(agent_uuid, new_slot_id); :1594 self._slot_cache[new_slot_id] = cert; 1169 export_chain
identity.py:808-810  resolve_slot_id docstring: "Returns None for any other key (a slot id, ..."
identity.py:821-827  slots comprehension; len(slots)==1 -> slot; >1 -> None; else _asset_slot_by_uuid
identity.py:174-177  AgentBirthCertificate.agent_uuid, did, agent_type, callsign
identity.py:326-328  AssetTag.asset_uuid, asset_type, slot_id
Grep "^    def |^    async def " in identity.py, lines 529-1650 (AgentIdentityRegistry): 30 direct methods (__init__ :529 ... get_transfer_certificates_for :1650)
crew_profile.py:660 class CallsignRegistry; :663 __init__(self); :669 load_from_profiles(profiles_dir); :690 data.get("callsign")
crew_profile.py:705 bind_registry; :709 resolve(callsign); :715 callsign.lower(); :722 "agent_id": None; :727 get_by_pool(agent_type); :730 agent.id
crew_profile.py:734 get_callsign(agent_type) -> str; :738 all_callsigns; :752 set_callsign; :24-25 TYPE_CHECKING AgentRegistry
substrate/registry.py:24 AgentRegistry.__init__(self); :29 async register(agent); :61-62 get_by_pool matches a.pool; :71 all()
substrate/agent.py:44-45  self.sovereign_id: str = "" / self.did: str = ""
agent_onboarding.py:419-431 crew identity deferred when no instance_id ("ship not yet commissioned"); :446-457 resolve_or_issue(slot_id=agent.id) -> sovereign_id, did
agent_onboarding.py:461-476 non-crew asset tag; :475 agent.sovereign_id = tag.asset_uuid; :476 agent.did = ""
startup/communication.py:895-921 deferred crew birth certificates; :910 resolve_or_issue; :920-921 sovereign_id, did
crew_utils.py:69 is_crew_agent(agent, ontology=None); :73-76 ontology else legacy _WARD_ROOM_CREW
runtime.py:3   from __future__ import annotations
runtime.py:158 if TYPE_CHECKING:   :200 from probos.identity import AgentIdentityRegistry   :201 ... IdentityKeyBinding  # AD-1196   :202 ... BackupResult, BackupService
runtime.py:522-524 identity_registry / identity_key_binding / pool_scaler annotations
runtime.py:723-725 self.callsign_registry = CallsignRegistry(); load_from_profiles(); bind_registry(self.registry)
runtime.py:1198-1200 "# --- Sovereign Agent Identity (AD-441) ---" / identity_registry / identity_key_binding
runtime.py:2748 infra = await boot_infrastructure(   :2760 self.identity_registry = infra.identity_registry
runtime.py:2765-2773 AD-1343 Phase 1a (agent_stops) and durable_events.bind_loop  [BF-908 region]
runtime.py:2789-2804 self.onboarding = _AOS(... ontology=None (:2797) ... ward_room=None, acm=None, )   :2806 fleet = await create_agent_fleet(
grep "acm=None,$" runtime.py -> only :2803; grep "from probos.identity import" -> :200 and :2696 (different line)
startup/results.py:80 class InfrastructureResult; :83 identity_registry: "AgentIdentityRegistry"
startup/infrastructure.py:170-178 AgentIdentityRegistry(...); start(); InfrastructureResult(identity_registry=...)
startup/shutdown.py:1429-1433 "# Stop Identity Registry (AD-441)" ... runtime.identity_registry = None
scripts/check_architecture_principles.py:80-82 only five packages ranked; top-level probos/ modules unranked
scripts/check_architecture_principles.py:160-165 gating categories; :187-188 SRP 500 lines / 15 methods; :574 srp key is the dotted name (not the size)
tests/fixtures/runtime_lifecycle.py:60-68 START_FAILURE_PHASES incl. "fleet_entry"; :74 lifecycle_config; :336-343 inject_start_failure(..., on_fire=); :372-373 fleet_entry wraps create_agent_fleet
tests/fixtures/runtime_factory.py:95-106 make_runtime(tmp_path, *, llm=None, config=None)
tests/test_issue1419_failed_start_rollback.py:959-962 chdir + make_runtime(lifecycle_config(zero_grace=True)); :1392, :1399 shutdown step census tests
tests/test_bf906_crew_enrollment_boot.py:43-58 _config/_boot; :70-73 _crew via is_crew_agent(a, rt.ontology)
tests/test_bf907_trust_identity.py:60-67 live-shape constants; :75-121 registry fixture and _issue; :340-342 resolve_slot_id(slot) is None
routers/agent_stop.py:62 slot = identities.resolve_slot_id(agent_id) ...
pyproject.toml:9 requires-python >=3.12 (dataclass slots=True ok); :181 asyncio_mode = "auto"; :196 addopts "-n 16 --dist=loadfile"
scripts/ad_ceiling.py (2026-10-20): CEILING AD-1346, NEXT AD-1347
```

## Absence Verified (2026-10-20)

| Claim | Run | Found | Holds |
|---|---|---|---|
| A1: nothing named `IdentityService`, `IdentityRef` or `identity_service` exists in `src/` or `tests/` | Grep `resolve_slot_id\|IdentityService\|identity_service` over the repository excluding `prompts/` | `src/`: only `trust.py:305`, `trust_identity.py:51,57`, `identity.py:804`, `routers/agent_stop.py:62` (all `resolve_slot_id`). `tests/`: `identity_services` (a kwarg) in `test_ad1129_eventlog_query_tool.py` only. Docs: the architecture review. | yes |
| A2: no test pins `ProbOSRuntime`'s attribute set | Grep `ProbOSRuntime\.__annotations__\|get_type_hints\(ProbOSRuntime\|vars\(runtime\)\|runtime\.__dict__` over `tests/` | `vars(runtime)` only on fakes: `test_ad1198_identity_continuity.py:1008`, `test_ad1206_repair_issue.py:1225-1361`, `test_ad1286_wiring.py:133`, `test_issue1452_stop_leftovers.py:492` (a `SimpleNamespace` passed to `_stop_held`, not to shutdown) | yes |
| A3: no test constructs a fake `InfrastructureResult` for a runtime start | Grep `InfrastructureResult\(` over `tests/` | `test_ad1240_workspace_result_lifecycle.py:3614-3615` (dataclass field tests only) | yes |
| A4: no source-scan test reads the lines Sections 3 and 4 edit | Grep `fleet = await create_agent_fleet\|Create onboarding service first\|Stop Identity Registry\|runtime\.identity_registry = None` over the repository excluding `prompts/` | `runtime.py:2787,2806`; `shutdown.py:1429,1433`; tests set `identity_registry = None` on mocks only (`test_ad611…:66`, `test_ad622…:270`, `test_api_profile.py:47`) | yes |
| A5: no new event, config or store, so the pins are unaffected | `test_ad1195_eventlog_pair_freeze.py` greps for `agent_stops\|identity`: `:90`, `:115-117` (trust merge pair only) | no M1a hunk | yes |
| A6: crew certificates are issued after Phase 2 | Grep `resolve_or_issue\(\|\.sovereign_id = ` over `src/probos` | `agent_onboarding.py:446,456,475`; `startup/communication.py:910,920` | yes |
| Not verifiable | BF-908's exact hunks (not merged; not read, per instruction) | n/a | The orchestrator re-verifies Sections 2 and 3 after it merges |

## Prior Art and Blind Spots

**Internal.**
- `docs/architecture/architecture-review-2026-10-20.md` §2.2 (`:72-86`, the identity forms and the 18 resolvers) and §3.6 (`:252-257`): **adopted**, with the five fields as listed and embodiment later.
- The BF-907 contract and its `DECISIONS.md:243-275` entry (D2: inject a bound method; D3: unknown → key unchanged): **adopted**. The facade composes the same resolver and keeps "None means unresolved".
- AD-441's two-tier identity, certificates and asset tags (`agent_onboarding.py:418-476`): **adopted** as the meaning of `sovereign_id`.

**External** (2 searches; reference-projects date used: 2026-10-20).
- W3C DID Resolution ([w3id.org/did-resolution](https://w3id.org/did-resolution); CR snapshot noted by [ppc.land](https://ppc.land/w3c-sets-september-3-deadline-for-feedback-on-did-resolution-v1/)) returns `notFound` and `invalidDid` as separate metadata: **adapted**. v1 returns None for both, and a reason code is deferred (D12).
- Kubernetes owner references carry both a reusable name and a per-instance UID, so a recreated same-name object is a different referent ([KodeKloud notes](https://notes.kodekloud.com/docs/Kubernetes-Operators/Building-The-WebApp-Operator-Core-Reconcile/Owner-References-And-Garbage-Collection/page)): **adopted** as D3. The slot is the reusable name, and the sovereign id is in equality.
- `docs/research/reference-projects.md`, Protocols: MCP Apps (last reviewed 2026-04-08, overdue) and AG-UI (never). **Considered, deferred**: neither bears on identity references. No row was examined, so no row needs updating.

**Blind spots** (the issue does not name these):
1. Crew are **unresolved between Phase 2 and Phase 7** (Problem, fact 3). M3 must record "unresolved" for them, not a raw id.
2. One slot can hold both a tag and a certificate (D7). The certificate wins, which matches `agent.sovereign_id`'s final value.
3. With several live agents of one type, a callsign follows `CallsignRegistry.resolve`'s first-live rule. That is unchanged and documented.
4. A certificate bound to two slots resolves to None by UUID but to two distinct refs by slot (T3).
5. A foreign certificate without a slot resolves to None.
6. Cost: the slot path is two dict lookups. The sovereign path is BF-907's O(crew) scan (16 live), which is acceptable for M3's hot path when called with slot ids.
7. Shutdown order: a reference that outlived the registry would resolve against a closed one. Released together (Section 4).
8. **Thread safety:** `resolve_slot_id` iterates `_slot_cache`. A call from a non-loop thread, such as `_emit_from_any_thread`, could race a Phase 7 issuance. The facade is loop-only, binding on M3.

## Residuals

- R1: `dataclasses.replace(ref, ...)` can copy a ref outside the facade. There are none today. M1b's checker can add it.
- R2: The 18 local resolvers and `routers/agent_stop.py:62` remain until the migration slices.
- R3: A reason code for unresolved identities (D12).

## Amendment A1 (2026-10-20, after review round 1)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 1 (`gpt-6.1-sol`) found the source sound, but three statements in this contract wrong, plus one missing test. (1) "Crew are unresolved between Phase 2 and Phase 7" is false for a crew agent that the Phase 2 crew test tags as an asset. It was measured on a real boot (70 agents): before Phase 7 one of 16 crew, `yeoman_yeoman_0_cbc42abe`, resolved to an asset ref; after Phase 7 the same slot resolved to a certificate ref with a DID and a different sovereign id; afterwards no crew agent was unresolved. The same statement is also false on every later boot (D14). (2) "Nothing sleeps" is false: a clean stop runs the production shutdown grace waits (`startup/shutdown.py:999,1055`). (3) "The slot path is two dict lookups" holds only for a certificate slot.

**Apply order.** Tests first, then source (none), then trackers. Apply these blocks to the staged candidate tree `fe872f7c`. Each SEARCH occurs exactly once in its file. The working tree uses CRLF, so match line by line.

**Supersedes:**
- Header "Estimated tests": now **18 new (13 unit and structural, 5 real-boot)**.
- Problem, fact 3, the sentence "Non-crew agents get an asset tag at wiring (`agent_onboarding.py:461-476`)." Replaced below.
- "Binding on M3's contract", the sentence "Crew agents are unresolved between Phase 2 and Phase 7 (Problem, fact 3)." Replaced by D14.
- Tests intro, "Nothing sleeps." Replaced below.
- File 2 heading "(a real boot; 3 tests)" now reads "(a real boot; 5 tests)". New rows T17 and T18. "That makes **16 tests**" now reads "That makes **18 tests** in total (13 + 5)".
- Blind spots 1 and 6. Replaced below. New blind spot 9 and residual R4.
- Acceptance Criteria: new criterion 2a. Diff Reviewer properties: new 7 and 8.
- Mutation table: **no change**. A1 changes no source file, so the campaign of record's sha256 values stand. T17 and T18 kill no one-line mutant that the existing rows leave alive. Swapping the precedence or making the facade hold a copy is a multi-line change; M8 and M11 already cover the one-line forms.
- Milestone focused checks: **no change**. M2 already runs the whole boot file.

### Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D13 | **An asset-then-certificate slot is kept as built.** On a vessel's first boot `runtime.ontology` is None at Phase 2 (`runtime.py:1198`; loaded in Phase 7, `communication.py:787-793`), so `is_crew_agent` falls back to `_WARD_ROOM_CREW` (`crew_utils.py:58-76`). A crew type outside that set (the yeoman today) gets an asset tag at wiring (`agent_onboarding.py:461-476`) and its certificate in Phase 7 (`communication.py:898-921`), on the same slot. The facade reports an asset ref (`did == ""`) until Phase 7, then the certificate ref: same `slot_id`, new `sovereign_id` and DID. By D3 these are two different refs. D7's certificate-first precedence is unchanged. | (1) **Asset first.** The tag is never deleted (no `_asset_cache.pop`, `del` or `DELETE FROM asset_tags` in `src/`) and is reloaded on every boot (`identity.py:598-609`). The slot would resolve to its old tag forever, even after Phase 7, against `agent.sovereign_id` (`communication.py:920`) and against the certificate's own UUID. This trades a one-time correct change for a permanent wrong answer. (2) **Hide asset refs until Phase 7.** Without the ontology the facade cannot tell a crew-to-be tag from an asset. A phase flag would add boot-order state and report None for a slot that does have an identity. (3) **Add the type to the legacy set, or load the ontology before Phase 2.** That changes onboarding, outside this slice. It leaves the stored tag on every existing vessel (R4), and it fails again with the next new crew type. |
| D14 | **When a crew ref can change: once in a slot's life.** On a later boot `AgentIdentityRegistry.start()` (Phase 1, `infrastructure.py:173`) loads the stored slot mappings (`identity.py:589-596`). Slot ids are deterministic (`substrate/identity.py:17-27`), and `resolve_or_issue` returns the stored certificate (`identity.py:1021-1024`). So every crew agent resolves to its certificate ref from Phase 2 onward. Only a vessel's first boot has an unresolved window (crew deferred at wiring, `agent_onboarding.py:430-431`) or an asset-to-certificate change. | Stating the window without the boot kind: that is how the original claim went wrong. |
| D15 | **How T17 and T18 read Phase 7: a direct `monkeypatch` wrapper around `probos.startup.communication.init_communication`** that resolves every registered slot on entry and then calls the original. `runtime.py:3179` imports the function inside `start()`, so the patched module attribute is the one called. That is its only import in `src/`. | `inject_start_failure(..., "communication")` (`tests/fixtures/runtime_lifecycle.py:336-377`): `StartFailure.fire` always raises after `on_fire` (`:310-320`), so the boot cannot finish. Disarming it inside `on_fire` would still raise. |
| D16 | **T18 is added** (one more than the review asked for). D14 corrects the M3 binding using a fact that was read from the code, not measured. T18 measures it. Cost: two boots and two stops (about 6 s of shutdown grace waits). | Leaving D14 unmeasured: M3 freezes on it. |

### Corrected statements

- **Problem, fact 3** (replaces the sentence named above): "Every agent that the Phase 2 crew test does not name gets an asset tag at wiring (`agent_onboarding.py:461-476`). With the ontology None, that test is the legacy set (`crew_utils.py:58-76`), so a crew type outside it (the yeoman today) is tagged at Phase 2 and certified in Phase 7, on the same slot (D7, D13)."
- **Binding on M3's contract** (replaces the sentence named above): "On a vessel's first boot, crew agents are unresolved from Phase 2 until Phase 7 issues their certificates. The exception is a crew agent that the Phase 2 crew test tagged as an asset: it resolves to that asset ref until Phase 7 (D13). On every later boot, each crew agent resolves to its stored certificate from Phase 2 (D14). M3 keys and aggregates on `slot_id` only. It reads `sovereign_id` and `did` as facts of the record's moment. These change at most once in a slot's life, from an asset ref (`did == ""`) to a certificate ref on the same slot. M3 treats that change as one principal, not as a reused slot, and does not compare refs across it (D3 makes them unequal). A certificate ref followed by a different certificate ref on one slot is a reused slot. `agent_type` does not change across it; `callsign` is live. An asset-tag UUID from an earlier record still resolves to the slot's current ref (T17). M3 never reads `agent.sovereign_id`, which lags the facade before Phase 7 (blind spot 9)."
- **Tests intro** (replaces "Nothing sleeps."): "No test sleeps of its own. A clean `stop()` in T14, T16, T17 and T18 runs the production shutdown grace waits (`startup/shutdown.py:999,1055`, 1.0 s and 2.0 s); T15's zero-grace config skips them."
- **Blind spot 1** (replaced): "Crew may be unresolved, or resolve to an asset ref, between Phase 2 and Phase 7 on a vessel's first boot only (D13, D14). M3 records None as unresolved, never as a raw id."
- **Blind spot 6** (replaced): "Cost, measured: two `dict.get` calls for a certificate slot and three for an asset slot. A certificate UUID costs four and a DID five, plus BF-907's scan over certificate slots (`identity.py:821`, 16 crew live). Each resolution builds one ref and runs no SQL. M3 should call with slot ids."
- **Blind spot 9** (new): "Between Phase 2 and Phase 7 of a later boot, `agent.sovereign_id` is `""` for a deferred crew agent (`agent_onboarding.py:430-431`) and the tag UUID for the yeoman (`:475`), while the facade already returns the stored certificate. The facade is right and the attribute lags, so a migration slice must not prefer `agent.sovereign_id` over the facade."
- **R4** (new residual): "A crew slot that was asset-tagged on its first boot keeps that tag after Phase 7 certifies it, and `GET /assets` lists it (`routers/identity.py:101-111`). This predates M1a, which neither causes nor changes it. It is a follow-up issue, not this slice."

### New test rows (File 2)

| # | Test | Proves |
|---|---|---|
| T17 | **`test_across_phase_7_a_crew_agent_keeps_its_slot_and_only_an_asset_ref_is_replaced`** | One first boot, read through the D15 wrapper at Phase 7 entry and again after the boot. The crew set comes from `is_crew_agent(a, rt.ontology)` after the boot; no crew type is hardcoded. Assertions: every crew agent resolves after Phase 7 with a non-empty DID and its own slot. Every crew agent that resolved at Phase 7 entry was an asset ref (`did == ""`), keeps its `slot_id`, gains a DID if its `sovereign_id` changed (and the ref is then unequal, D3), and its earlier asset-tag UUID resolves to its new ref. Every non-crew agent that resolved at entry resolves after Phase 7 to an equal ref with `did == ""`. Premise: at least one crew agent resolved at entry; the failure message says what to change if no crew agent is ever tagged. |
| T18 | **`test_on_a_second_boot_every_crew_agent_resolves_from_phase_2_to_its_stored_certificate`** | First boot: record every crew agent's ref (each with a DID). Second boot on the same `data_dir`, through the D15 wrapper: every recorded crew slot present at Phase 7 entry resolves there to an equal ref with the same DID, and to the same ref after the boot. Premise: at least one slot was checked. |

### Tests first: `tests/test_ad1346_identity_service_boot.py`

A1.T1: the module docstring lists T17 and T18.

SEARCH:
```text
- T16  a clean ``stop()`` releases the facade together with the identity registry.
```
REPLACE:
```text
- T16  a clean ``stop()`` releases the facade together with the identity registry.
- T17  across Phase 7 of a first boot, a crew agent asset-tagged at wiring keeps its slot and gains its certificate
       ref (a new sovereign id and a DID), every crew agent resolves with a DID after Phase 7, and no asset changes.
- T18  on a second boot over the same data directory, every crew agent resolves to its stored certificate from
       Phase 2 on, so the change T17 pins happens once in a slot's life.
```

A1.T2: the sleep wording.

SEARCH:
```text
Every data directory is under ``tmp_path`` and every runtime is stopped or rolled back; nothing sleeps and nothing
reads the live data directory, the OS keyring (``tests/conftest.py`` forces the failing backend) or the network.
```
REPLACE:
```text
Every data directory is under ``tmp_path`` and every runtime is stopped or rolled back. No test sleeps of its own, but a
clean ``stop()`` runs the production shutdown grace waits (``startup/shutdown.py``, about 3 s; T15's zero-grace config
skips them). Nothing reads the live data directory, the OS keyring (``tests/conftest.py`` forces the failing backend)
or the network.
```

A1.T3: imports (three blocks).

SEARCH:
```text
from pathlib import Path
```
REPLACE:
```text
from pathlib import Path
from typing import Any
```

SEARCH:
```text
from probos.identity_service import IdentityService
```
REPLACE:
```text
from probos.identity_service import IdentityRef, IdentityService
```

SEARCH:
```text
from probos.runtime import ProbOSRuntime
```
REPLACE:
```text
from probos.runtime import ProbOSRuntime
from probos.startup import communication as startup_communication
```

A1.T4: the Phase 7 wrapper helper, after `_boot`.

SEARCH:
```python
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime
```
REPLACE:
```python
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _read_the_facade_at_phase_7_entry(
    monkeypatch: pytest.MonkeyPatch, runtime: ProbOSRuntime,
) -> list[dict[str, IdentityRef | None] | None]:
    """Wrap Phase 7 (``init_communication``) so that, on entry, the facade resolves every registered agent's slot.

    A direct wrapper, not ``inject_start_failure(..., "communication")``: that helper always raises once it fires
    (``tests/fixtures/runtime_lifecycle.py:310-320``), and these boots must finish. ``runtime.py`` imports
    ``init_communication`` inside ``start()``, so the patched module attribute is the one it calls; ``monkeypatch``
    restores it. Each list entry is one Phase 7 call; None means the facade did not exist then.
    """
    original = startup_communication.init_communication
    reads: list[dict[str, IdentityRef | None] | None] = []

    async def at_phase_7_entry(*args: Any, **kwargs: Any) -> Any:
        service = runtime.identity_service
        if service is None:
            reads.append(None)
        else:
            reads.append({agent.id: service.resolve(agent.id) for agent in runtime.registry.all()})
        return await original(*args, **kwargs)

    monkeypatch.setattr(startup_communication, "init_communication", at_phase_7_entry)
    return reads
```

A1.T5: T17 and T18, after T16.

SEARCH:
```python
    assert rt.identity_service is None, "a clean stop must release the facade"
```
REPLACE:
```python
    assert rt.identity_service is None, "a clean stop must release the facade"


async def test_across_phase_7_a_crew_agent_keeps_its_slot_and_only_an_asset_ref_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T17: one first boot, read through the facade before and after Phase 7 (AD-1346 M1a A1, D13).

    ``rt.ontology`` is None until Phase 7, so the crew test at wiring falls back to a legacy set, and a crew type
    outside it is asset-tagged at Phase 2 and certified in Phase 7 on the same slot. The crew are therefore read
    after the boot, from the ontology; no crew type is named here.
    """
    rt = ProbOSRuntime(config=_config(), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, rt)
    await rt.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = rt.identity_service
        assert isinstance(service, IdentityService), "premise: the boot built the facade"
        assert rt.ontology is not None, "premise: Phase 7 loaded the ontology that names the crew"
        agents = list(rt.registry.all())
        crew_ids = {a.id for a in agents if is_crew_agent(a, rt.ontology)}
        assert crew_ids, "premise: the ontology names at least one crew agent"

        tagged = 0  # crew agents that resolved at Phase 7 entry
        for agent in agents:
            who = f"{agent.agent_type} {agent.id}"
            before = entry.get(agent.id)
            after = service.resolve(agent.id)
            if agent.id not in crew_ids:
                if before is not None:
                    assert after is not None and after == before, (
                        f"{who}: an asset's ref must not change across Phase 7 ({before} -> {after})"
                    )
                    assert after.did == "", f"{who}: an asset gained a DID in Phase 7"
                continue
            assert after is not None and after.did, f"{who}: a crew agent must resolve with a DID after Phase 7"
            assert after.slot_id == agent.id, who
            if before is None:
                continue  # unresolved at Phase 7 entry: deferred at wiring, or wired in Phase 7
            tagged += 1
            assert before.did == "", f"{who}: before Phase 7 a crew agent can hold only an asset tag, got {before}"
            assert before.slot_id == after.slot_id, f"{who}: Phase 7 must keep the slot"
            if before.sovereign_id != after.sovereign_id:
                assert after.did, f"{who}: a new sovereign id must come with a DID"
                assert before != after, f"{who}: a new sovereign id is a new ref (D3)"
            assert service.resolve(before.sovereign_id) == after, (
                f"{who}: the asset-tag UUID read before Phase 7 must resolve to the slot's ref after it"
            )
        assert tagged > 0, (
            "premise: no crew agent resolved at Phase 7 entry, so none was asset-tagged at wiring. Either every crew "
            "type of the ontology is now in crew_utils._WARD_ROOM_CREW, or the ontology is loaded before Phase 2. "
            "A crew ref then no longer changes at Phase 7: remove this test, and in DECISIONS.md (AD-1346 M1a) "
            "drop D13's asset-then-certificate case and the matching clause of the binding on M3."
        )
    finally:
        await rt.stop()


async def test_on_a_second_boot_every_crew_agent_resolves_from_phase_2_to_its_stored_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: the change T17 pins happens once in a slot's life (AD-1346 M1a A1, D14).

    On a later boot the identity registry loads the stored slot mappings in Phase 1, so every crew agent resolves to
    its certificate ref from Phase 2 on, and Phase 7 returns the same certificate.
    """
    data_dir = tmp_path / "data"
    first = await _boot(data_dir)
    try:
        first_service = first.identity_service
        assert isinstance(first_service, IdentityService), "premise: the first boot built the facade"
        first_refs = {
            a.id: first_service.resolve(a.id) for a in first.registry.all() if is_crew_agent(a, first.ontology)
        }
    finally:
        await first.stop()
    assert first_refs, "premise: the first boot has crew"
    assert all(ref is not None and ref.did for ref in first_refs.values()), (
        "premise: the first boot certified every crew agent"
    )

    second = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, second)
    await second.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = second.identity_service
        assert isinstance(service, IdentityService), "premise: the second boot built the facade"
        checked = 0
        for slot, ref in first_refs.items():
            assert ref is not None, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            early = entry[slot]
            assert early is not None, f"{slot}: a stored certificate must resolve before Phase 7 of a later boot"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 of a later boot must not change the ref"
            checked += 1
        assert checked > 0, "premise: at least one crew slot was registered before Phase 7 of the second boot"
    finally:
        await second.stop()
```

### Source

None. No file under `src/` changes.

### Trackers: `DECISIONS.md`

A1.D1: D13 and D14 go before the binding.

SEARCH:
```text
- *Binding on M3.* The principal of a decision
```
REPLACE:
```text
- *D13 (an asset-then-certificate slot).* On a vessel's first boot the ontology is None at Phase 2, so the crew test at wiring falls back to a legacy set; a crew type outside it (the yeoman today) gets an asset tag at Phase 2 and its certificate in Phase 7, on the same slot. The facade reports an asset ref (empty DID) until Phase 7, then the certificate ref, with the same slot id and a new sovereign id and DID; by D3 they are two refs. Kept as built. Rejected: asset first (the tag is never deleted and reloads on every boot, so the slot would resolve to its stale tag even after Phase 7, against `agent.sovereign_id` and the certificate's own UUID); hiding asset refs until Phase 7 (without the ontology the facade cannot tell a crew-to-be tag from an asset, and a phase flag would report None for a slot that has an identity); adding the type to the legacy set or loading the ontology before Phase 2 (a change to onboarding outside this slice, which leaves the stored tag on every existing vessel and fails again with the next new crew type).
- *D14 (once in a slot's life).* On a later boot the identity registry loads the stored slot mappings in Phase 1, and slot ids are deterministic, so every crew agent resolves to its stored certificate from Phase 2 and Phase 7 returns the same one. Only a vessel's first boot has an unresolved window or an asset-to-certificate change.
- *Binding on M3.* The principal of a decision
```

A1.D2: the binding sentence.

SEARCH:
```text
Crew agents are unresolved between Phase 2 and Phase 7, when their certificates are issued.
```
REPLACE:
```text
On a vessel's first boot crew agents are unresolved from Phase 2 until Phase 7 issues their certificates, except a crew agent the Phase 2 crew test tagged as an asset, which resolves to that asset ref until Phase 7 (D13); on a later boot every crew agent resolves to its stored certificate from Phase 2 (D14). M3 keys and aggregates on `slot_id` only and reads `sovereign_id` and `did` as facts of the record's moment: they change at most once in a slot's life, from an asset ref (empty `did`) to a certificate ref on the same slot, which M3 treats as one principal, not a reused slot, without comparing refs across it (D3 makes them unequal). A certificate ref followed by a different certificate ref on one slot is a reused slot. `agent_type` does not change across it and `callsign` is live. An asset-tag UUID in an earlier record still resolves to the slot's current ref. M3 never reads `agent.sovereign_id`, which lags the facade before Phase 7 on a later boot.
```

A1.D3: the test count and the sleep wording.

SEARCH:
```text
16: 13 in `tests/test_ad1346_identity_service.py`, over real registries, and 3 real-boot tests in `tests/test_ad1346_identity_service_boot.py` (every identified agent resolves after a boot, the facade exists before the fleet and a failed start releases it, a clean stop releases it). Nothing sleeps; no live data is read.
```
REPLACE:
```text
18: 13 in `tests/test_ad1346_identity_service.py`, over real registries, and 5 real-boot tests in `tests/test_ad1346_identity_service_boot.py` (every identified agent resolves after a boot, the facade exists before the fleet and a failed start releases it, a clean stop releases it, a crew agent's ref across Phase 7 of a first boot, and every crew agent's stored certificate from Phase 2 of a second boot). No test sleeps of its own, but a clean stop runs the production shutdown grace waits; no live data is read.
```

A1.D4: the lookup cost.

SEARCH:
```text
while the slot path is two dict lookups.
```
REPLACE:
```text
while the slot path reads two dictionaries for a certificate slot and three for an asset slot (four for a certificate UUID and five for a DID, plus the scan) and builds one ref, with no SQL.
```

A1.D5: residual R4.

SEARCH:
```text
(R3) A reason code for an unresolved identity is deferred (D12).
```
REPLACE:
```text
(R3) A reason code for an unresolved identity is deferred (D12). (R4) A crew slot asset-tagged on its first boot keeps that tag after Phase 7 certifies it, and the identity routes list it among the assets (`routers/identity.py:107`); this predates M1a, which neither causes nor changes it.
```

### Trackers: `PROGRESS.md`

SEARCH:
```text
crew certificates are issued in Phase 7, so the facade holds references to the registries and sees them.
```
REPLACE:
```text
crew certificates are issued in Phase 7 of a vessel's first boot, so the facade holds references to the registries and sees them; a crew agent the Phase 2 crew test missed (the yeoman) resolves to an asset ref until then and to its certificate on the same slot after, once in the slot's life.
```

SEARCH:
```text
16 new tests (13 unit and structural, 3 real-boot).
```
REPLACE:
```text
18 new tests (13 unit and structural, 5 real-boot).
```

### Acceptance Criteria (added)

2a. On a first boot, every crew agent that resolved at Phase 7 entry was an asset ref and keeps its slot, every crew agent resolves with a DID after Phase 7, and no asset ref changes (T17). On a second boot, every crew agent resolves to its stored certificate from Phase 7 entry onward (T18).

### Diff Reviewer: properties to verify (added)

7. A1 changes no file under `src/`. The T17 and T18 wrapper passes every argument to the original `init_communication`, returns its result, and is reverted by `monkeypatch`.
8. The "Binding on M3" text in `DECISIONS.md` agrees with D13 and D14: keyed on `slot_id`, at most one asset-to-certificate change per slot, on a first boot only.

### Verified Against Codebase (2026-10-20, on the staged tree `fe872f7c`)

```
runtime.py:1198 self.ontology ... = None; :3179 from probos.startup.communication import init_communication (inside start)
startup/communication.py:787-793 ontology built in Phase 7; :898-921 deferred crew certificates; :920-921 sovereign_id, did
crew_utils.py:58-66 _WARD_ROOM_CREW (15 types, no yeoman); :74-76 ontology else legacy set
agent_onboarding.py:430-431 deferred crew; :469-476 asset tag, sovereign_id = tag.asset_uuid, did = ""
identity.py:560 start(); :589-596 slot_mappings -> _slot_cache; :598-609 asset_tags -> _asset_cache, _asset_slot_by_uuid
identity.py:821-827 resolve_slot_id: cert scan, then _asset_slot_by_uuid; :1021-1024 resolve_or_issue returns get_by_slot
startup/infrastructure.py:170-173 AgentIdentityRegistry(...); await identity_registry.start()
substrate/identity.py:17-27 generate_agent_id is deterministic (sha256 of type:pool:index)
identity_service.py:115-135 _ref_for_slot: get_by_slot, get_asset_by_slot, get_callsign
startup/shutdown.py:999 sleep(_write_grace); :1055 sleep(_dispatch_grace)
tests/fixtures/runtime_lifecycle.py:310-320 StartFailure.fire always raises; :376-377 "communication" wraps init_communication
tests/test_bf906_crew_enrollment_boot.py:214-247, 267-296 two boots on one data_dir (precedent for T18)
routers/identity.py:101-111 GET /assets lists get_asset_tags()
```

### Absence Verified (2026-10-20)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Nothing deletes an asset tag | Grep `_asset_cache\.(pop\|clear)\|del self\._asset_cache\|DELETE FROM asset_tags` over `src/probos` | none | yes |
| `init_communication` is imported only inside `start()` | Grep `init_communication` over `src/probos` | `runtime.py:3179,3181`; the other hits are docstrings and storage-declaration strings | yes |
| No test already wraps `init_communication` for a start that passes | Grep `"init_communication"` over `tests` | `runtime_lifecycle.py:377` only (the failure injector) | yes |

## Amendment A2 (2026-10-20, after review round 2)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

**Trigger.** Review round 2 (`gpt-6.1-sol`) found one P2, a regression introduced by A1, in claims only. D14 and the A1 binding said that on a later boot every crew agent resolves to its stored certificate from Phase 2, and that "only a vessel's first boot has an unresolved window or an asset-to-certificate change". That is false when a later boot adds crew slots that have no stored certificate. Measured by the reviewer and reproduced by the orchestrator (`logs/probe_m1a_second_boot.py.txt`). Boot 1 ran with `utility_agents.enabled = False`, and boot 2 ran over the same data directory with it True. Boot 2 had 16 crew. The 7 slots stored by boot 1 resolved unchanged at Phase 7 entry. The 9 added slots were unresolved (8) or an asset ref (1, the yeoman) at Phase 7 entry, and certificate refs with a DID on the same slots after Phase 7. The window belongs to a slot that has no stored certificate, on any boot. A2 also corrects one source attribution: the crew test at wiring reads the onboarding service's ontology, which is None from `runtime.py:2804` until Phase 8 (`startup/finalize.py:5557`). It does not read `runtime.ontology`.

**Wording rule (binding on this amendment and on later M1a text).** State a claim only if a test pins it or a cited line shows it. Qualify every claim about when an identity state is possible by the slot's state at Phase 1 (a stored certificate or not) and by the phase, never by "first boot" or "later boot". Where neither a test nor a line supports a statement, remove it rather than rewrite it.

**Apply order.** Tests first, then source (none), then trackers. Apply these blocks to the staged candidate tree `e21e11618a37dda21c52f2ce68724b3bed5f19e1`. Each SEARCH occurs exactly once in its file. The working tree uses CRLF, so match line by line.

**Supersedes:**
- Header "Estimated tests": now **19 new (13 unit and structural, 6 real-boot)**.
- Problem, fact 3, its first two sentences ("Crew certificates are issued in Phase 7, not Phase 2. At wiring the onboarding service has `ontology=None` (`runtime.py:2797`), so a crew agent's certificate is deferred"). Replaced below.
- A1 Trigger, the sentence "The same statement is also false on every later boot (D14)." Replaced by: "It is also false for a crew slot with a stored certificate, which resolves to it from Phase 2 on any boot (D14 as restated by D17)."
- A1 D13, its first sentence. Replaced below. The rest of D13 and its rejected alternatives stand.
- A1 D14. Replaced by D17.
- A1 D16, the sentence "T18 measures it." Replaced by: "T18 measures it for crew slots with a stored certificate, and T19 for the crew slots a configuration change adds (D18)."
- A1 Corrected statements: the Binding on M3's contract, the Tests intro, blind spot 1, blind spot 9 and R4. Replaced below. Through A1, this also supersedes the original binding sentence at the contract's "Binding on M3's contract" and blind spot 1 of the original list.
- A1 New test rows T17 and T18. Replaced below. New row T19.
- File 2 heading now reads "(a real boot; 6 tests)". "That makes **18 tests**" now reads "That makes **19 tests** in total (13 + 6)".
- A1's apply blocks (A1.T1, A1.T5, A1.D1 to A1.D5 and the A1 `PROGRESS.md` blocks): their text for the T14 to T18 docstrings, comments and messages, the T18 name and the tracker sentences named below is superseded by the A2 blocks. The A1 blocks are history and are not reapplied.
- Acceptance Criterion 2a and Diff Reviewer property 8. Replaced below. New properties 9 and 10.
- Mutation table: **no change**. A2 changes no file under `src/`, so the sha256 values of the campaign of record stand. T19 kills only mutants that T17 (asset-first precedence) or T18 (skipping the stored slot-mapping load) already kill. No one-line mutant is left alive that T19 alone kills.
- Milestone focused checks: **no change**. M2 already runs the whole boot file.

### Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D17 | **D14 restated per slot, not per boot.** The identity registry loads every stored slot-to-certificate mapping in Phase 1 of every boot, before any agent is wired: `AgentIdentityRegistry.start()` (`startup/infrastructure.py:173`; native certificates `identity.py:589-596`, foreign ones `:626-632`). Slot ids are deterministic (`substrate/identity.py:17-27`). So a crew slot with a stored certificate resolves to it from Phase 2 (`identity_service.py:115-125`), and Phase 7 returns the same one (`identity.py:1021-1024`) (T18, T19). A crew slot with no stored certificate has D13's window on any boot. It is unresolved from its wiring, or an asset ref if the crew test tagged it, until Phase 7 issues its certificate (T17 on a fresh data directory, T19 for the crew slots a later boot adds). A slot's ref changes from an asset ref to a certificate ref at most once, because nothing removes a certificate from a slot (Absence Verified). | (1) **Per boot** (A1): refuted by round 2's two-boot measurement. (2) **"A slot first seen on this boot"**: a slot that was registered before but never certified also has no stored certificate. Examples are a boot that stopped between the slot's registration and Phase 7, or a mapping whose certificate row is missing (`identity.py:594-595`). The slot's state decides, not its history. |
| D18 | **T19 is a separate test.** Boot 1 runs with `utility_agents.enabled = False`, and boot 2 runs over the same data directory with the default (True), which adds crew pools (`startup/agent_fleet.py:100-271`). The crew sets come from the ontology, and no type is hardcoded. Cost: two boots and two stops. | (1) **Fold into T18**: T18 would lose its same-configuration control, and a T18 failure would no longer say which half broke. (2) **Wording only**: the added-slot half, the case round 2 found, would be pinned by no test, against the wording rule. (3) **A helper shared with T18**: it would rewrite T18's body in this delta. The duplicated stored-slot loop is test-only. |
| D19 | **T18 is renamed and its docstring and two messages narrowed.** The new name is `test_a_crew_slot_with_a_stored_certificate_resolves_to_it_before_and_after_phase_7`. The old name ("every crew agent ... on a second boot") reads as the refuted rule. T18's assertions are unchanged. | Keep the name: it states a claim that no test pins. |
| D20 | **The binding on M3 is stated in slot state only.** M3 handles None and an asset ref for any crew slot whenever the facade returns one, and infers no identity state from the boot number or the phase. | Give M3 a phase guarantee: the onboarding service gets the ontology in Phase 8 (`startup/finalize.py:5557`), after Phase 7's issuance loop (`startup/communication.py:898-921`). A guarantee by phase would need a test or a line for every wiring path. |

### Corrected statements

- **Problem, fact 3** (replaces its first two sentences): "A crew slot with no stored certificate gets its certificate in Phase 7, not Phase 2. The onboarding service is built with `ontology=None` (`runtime.py:2804` on the staged tree) and receives the ontology only in Phase 8 (`startup/finalize.py:5557`), so at wiring a crew agent's certificate is deferred (`agent_onboarding.py:430-431`)." The rest of fact 3 stands.
- **D13, first sentence** (replaced): "At wiring in Phase 2 of every boot the onboarding service's ontology is None (`runtime.py:2804`; set in Phase 8, `startup/finalize.py:5557`), so `is_crew_agent` (`agent_onboarding.py:421`) falls back to `_WARD_ROOM_CREW` (`crew_utils.py:58-76`). A crew slot of a type outside that set (the yeoman today) that has no stored certificate gets an asset tag at wiring (`agent_onboarding.py:461-476`) and its certificate in Phase 7 (`communication.py:898-921`), on the same slot."
- **Binding on M3's contract** (replaces A1's text): "A crew slot with a stored certificate resolves to it from Phase 2 (D17). A crew slot without one, on any boot, is unresolved from its wiring until Phase 7 issues its certificate. Until then it resolves to an asset ref if the Phase 2 crew test tagged it as an asset (D13). M3 infers neither state from the boot number or the phase: it handles None and an asset ref for any crew slot whenever the facade returns one (D20). M3 keys and aggregates on `slot_id` only. It reads `sovereign_id` and `did` as facts of the record's moment. These change at most once in a slot's life, from an asset ref (`did == ""`) to a certificate ref on the same slot. M3 treats that change as one principal, not as a reused slot, and does not compare refs across it (D3 makes them unequal). A certificate ref followed by a different certificate ref on one slot is a reused slot. `agent_type` does not change across it; `callsign` is live. An asset-tag UUID from an earlier record still resolves to the slot's current ref (T17, T19). M3 never reads `agent.sovereign_id`, which lags the facade before Phase 7 for a crew slot with a stored certificate (blind spot 9). M3 calls the facade on the event loop only (blind spot 8)."
- **Tests intro** (replaces A1's text): "No test sleeps of its own. A clean `stop()` in T14, T16, T17, T18 and T19 runs the production shutdown grace waits (`startup/shutdown.py:999,1055`, 1.0 s and 2.0 s); T15's zero-grace config skips them."
- **Blind spot 1** (replaced): "A crew slot with no stored certificate, on any boot, may be unresolved, or resolve to an asset ref, until Phase 7 issues its certificate (D13, D17). M3 records None as unresolved, never as a raw id, and infers no state from the boot number or the phase."
- **Blind spot 9** (replaced): "Between Phase 2 and Phase 7, for a crew slot with a stored certificate, `agent.sovereign_id` has two lagging values while the facade already returns the stored certificate. It is `\"\"` for a deferred crew agent (`agent_onboarding.py:430-431`; default `substrate/agent.py:44`). It is the tag UUID for an asset-tagged one (`agent_onboarding.py:475`). The facade is right and the attribute lags, so a migration slice must not prefer `agent.sovereign_id` over the facade."
- **Blind spot 10** (new): "The phase alone does not tell a crew slot's state. The onboarding service gets the ontology in Phase 8 (`startup/finalize.py:5557`), after Phase 7's issuance loop (`startup/communication.py:898-921`). Whether a crew slot has a certificate at a given moment depends on what was stored for it and when it was wired. M3 reads the facade (D20)."
- **R4** (replaced): "A crew slot asset-tagged at wiring before its certificate was issued keeps that tag after Phase 7 certifies it, and `GET /assets` lists it (`routers/identity.py:101-111`). This predates M1a, which neither causes nor changes it. It is a follow-up issue, not this slice."

### New and replaced test rows (File 2)

| # | Test | Proves |
|---|---|---|
| T17 | **`test_across_phase_7_a_crew_agent_keeps_its_slot_and_only_an_asset_ref_is_replaced`** (unchanged name) | One boot on a fresh data directory, where no slot has a stored certificate. The facade is read through the D15 wrapper at Phase 7 entry and again after the boot. Assertions are unchanged from A1. Docstring and two messages are reworded per A2. |
| T18 | **`test_a_crew_slot_with_a_stored_certificate_resolves_to_it_before_and_after_phase_7`** (renamed, D19) | First boot: record every crew slot's ref (each with a DID). Second boot on the same `data_dir` with the same configuration, through the D15 wrapper: every recorded crew slot present at Phase 7 entry resolves there to an equal ref with the same DID, and to the same ref after the boot. Premise: at least one slot was checked. Assertions are unchanged from A1. |
| T19 | **`test_after_a_config_change_the_added_crew_slots_wait_for_phase_7_and_the_stored_ones_do_not`** | Boot 1 with `utility_agents.enabled = False`; record every crew slot's ref. Boot 2 on the same `data_dir` with the default configuration, through the D15 wrapper. Crew sets come from `is_crew_agent(a, rt.ontology)` after each boot, and no type is hardcoded. Premises: boot 1 has crew and certified all of them; boot 2 keeps every boot-1 crew slot and adds at least one; Phase 7 ran once; at least one stored slot and one added slot were registered at Phase 7 entry; at least one added slot was unresolved and at least one was an asset ref there. Each stored slot resolves at Phase 7 entry to its boot-1 ref with the same DID, and to the same ref after Phase 7. Each added slot resolves after Phase 7 with a DID and its own `slot_id`. At Phase 7 entry an added slot is None or an asset ref (`did == ""`) on the same slot, and its asset-tag UUID resolves to its ref after Phase 7. |

### Tests first: `tests/test_ad1346_identity_service_boot.py`

A2.T1: the T14 line of the module docstring.

SEARCH:
```text
- T14  after a real boot every identified agent resolves through ``runtime.identity_service`` to its own slot,
       sovereign id, DID and live callsign. Crew certificates are issued in Phase 7, after the facade is built at
       Phase 2 entry, so a crew agent that resolves proves the facade holds a reference, not a copy.
```
REPLACE:
```text
- T14  after a real boot every identified agent resolves through ``runtime.identity_service`` to its own slot,
       sovereign id, DID and live callsign. On a fresh data directory no slot has a stored certificate, so the crew
       certificates are issued in Phase 7, after the facade is built at Phase 2 entry, and a crew agent that
       resolves proves the facade holds a reference, not a copy.
```

A2.T2: the T17 and T18 lines of the module docstring, and the new T19 line.

SEARCH:
```text
- T17  across Phase 7 of a first boot, a crew agent asset-tagged at wiring keeps its slot and gains its certificate
       ref (a new sovereign id and a DID), every crew agent resolves with a DID after Phase 7, and no asset changes.
- T18  on a second boot over the same data directory, every crew agent resolves to its stored certificate from
       Phase 2 on, so the change T17 pins happens once in a slot's life.
```
REPLACE:
```text
- T17  across Phase 7 on a fresh data directory, a crew slot asset-tagged at wiring keeps its slot and gains its
       certificate ref (a new sovereign id and a DID), every crew agent resolves with a DID after Phase 7, and no
       asset changes.
- T18  on the next boot over the same data directory and configuration, each crew slot with a stored certificate
       resolves to it at Phase 7 entry and after it.
- T19  on the next boot with a configuration that adds crew slots, the added slots (no stored certificate) go
       through T17's window while the stored ones resolve as in T18: the window is per slot, not per boot.
```

A2.T3: the import.

SEARCH:
```text
from probos.config import SystemConfig
```
REPLACE:
```text
from probos.config import SystemConfig, UtilityAgentsConfig
```

A2.T4: T14's premise comment.

SEARCH:
```text
        # Premises. A crew certificate is issued in Phase 7, after the facade exists, so a crew agent with a DID
        # that resolves proves a reference rather than a copy. An asset (a non-crew agent holding a tag and no
        # DID) is the other identity the facade resolves.
```
REPLACE:
```text
        # Premises. On this fresh data directory a crew certificate is issued in Phase 7, after the facade exists, so
        # a crew agent with a DID that resolves proves a reference rather than a copy. An asset (a non-crew agent
        # holding a tag and no DID) is the other identity the facade resolves.
```

A2.T5: T17's docstring.

SEARCH:
```text
    """T17: one first boot, read through the facade before and after Phase 7 (AD-1346 M1a A1, D13).

    ``rt.ontology`` is None until Phase 7, so the crew test at wiring falls back to a legacy set, and a crew type
    outside it is asset-tagged at Phase 2 and certified in Phase 7 on the same slot. The crew are therefore read
    after the boot, from the ontology; no crew type is named here.
```
REPLACE:
```text
    """T17: one boot on a fresh data directory, read through the facade before and after Phase 7 (AD-1346 M1a, D13).

    No slot has a stored certificate. The onboarding service is built without the ontology and receives it in
    Phase 8, so the crew test at wiring falls back to a legacy set, and a crew type outside it is asset-tagged at
    Phase 2 and certified in Phase 7 on the same slot. The crew are therefore read after the boot, from the
    ontology; no crew type is named here.
```

A2.T6: T17's asset-tag message.

SEARCH:
```text
            assert before.did == "", f"{who}: before Phase 7 a crew agent can hold only an asset tag, got {before}"
```
REPLACE:
```text
            assert before.did == "", (
                f"{who}: before Phase 7 a crew slot with no stored certificate can hold only an asset tag: {before}"
            )
```

A2.T7: T17's premise message.

SEARCH:
```text
            "type of the ontology is now in crew_utils._WARD_ROOM_CREW, or the ontology is loaded before Phase 2. "
            "A crew ref then no longer changes at Phase 7: remove this test, and in DECISIONS.md (AD-1346 M1a) "
            "drop D13's asset-then-certificate case and the matching clause of the binding on M3."
```
REPLACE:
```text
            "type of the ontology is now in crew_utils._WARD_ROOM_CREW, or the onboarding service gets the ontology "
            "before Phase 2. A crew slot's ref then no longer changes at Phase 7: remove this test and T19's asset "
            "premise, and in DECISIONS.md (AD-1346 M1a) drop D13's asset-then-certificate case and the matching "
            "clauses of D14 and the binding on M3."
```

A2.T8: T18's name and docstring.

SEARCH:
```text
async def test_on_a_second_boot_every_crew_agent_resolves_from_phase_2_to_its_stored_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: the change T17 pins happens once in a slot's life (AD-1346 M1a A1, D14).

    On a later boot the identity registry loads the stored slot mappings in Phase 1, so every crew agent resolves to
    its certificate ref from Phase 2 on, and Phase 7 returns the same certificate.
    """
```
REPLACE:
```text
async def test_a_crew_slot_with_a_stored_certificate_resolves_to_it_before_and_after_phase_7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: a crew slot with a stored certificate has no Phase 7 window (AD-1346 M1a, D14).

    The identity registry loads the stored slot mappings in Phase 1 of every boot, before any agent is wired. A
    second boot over the same data directory and the same configuration therefore resolves each crew slot of the
    first boot to its certificate ref at Phase 7 entry, and Phase 7 returns the same certificate. T19 covers the
    crew slots a configuration change adds, which have no stored certificate.
    """
```

A2.T9: T18's two messages.

SEARCH:
```text
            assert early is not None, f"{slot}: a stored certificate must resolve before Phase 7 of a later boot"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 of a later boot must not change the ref"
```
REPLACE:
```text
            assert early is not None, f"{slot}: a slot with a stored certificate must resolve to it before Phase 7"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 must not change a stored certificate's ref"
```

A2.T10: T19, after T18.

SEARCH:
```python
        assert checked > 0, "premise: at least one crew slot was registered before Phase 7 of the second boot"
    finally:
        await second.stop()
```
REPLACE:
```python
        assert checked > 0, "premise: at least one crew slot was registered before Phase 7 of the second boot"
    finally:
        await second.stop()


async def test_after_a_config_change_the_added_crew_slots_wait_for_phase_7_and_the_stored_ones_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T19: the Phase 7 window belongs to a crew slot with no stored certificate, on any boot (AD-1346 M1a, D14).

    The first boot runs with the utility agent pools off; the next boot over the same data directory turns them on,
    which adds crew slots that have no stored certificate. Each added slot is unresolved, or an asset ref, at Phase 7
    entry and a certificate ref with a DID on the same slot after it, as in T17; each crew slot of the first boot
    resolves to its stored certificate at Phase 7 entry and after it, as in T18. The crew are read from the ontology
    after each boot; no crew type is named here.
    """
    data_dir = tmp_path / "data"
    first_config = _config()
    first_config.utility_agents = UtilityAgentsConfig(enabled=False)
    first = ProbOSRuntime(config=first_config, data_dir=data_dir, llm_client=MockLLMClient())
    await first.start()
    try:
        first_service = first.identity_service
        assert isinstance(first_service, IdentityService), "premise: the first boot built the facade"
        stored = {
            a.id: first_service.resolve(a.id) for a in first.registry.all() if is_crew_agent(a, first.ontology)
        }
    finally:
        await first.stop()
    assert stored, "premise: the first boot has crew"
    assert all(ref is not None and ref.did for ref in stored.values()), (
        "premise: the first boot certified every crew agent"
    )

    second_config = _config()
    assert second_config.utility_agents.enabled, "premise: the utility agent pools are on by default"
    second = ProbOSRuntime(config=second_config, data_dir=data_dir, llm_client=MockLLMClient())
    reads = _read_the_facade_at_phase_7_entry(monkeypatch, second)
    await second.start()
    try:
        assert len(reads) == 1, "premise: Phase 7 ran once"
        entry = reads[0]
        assert entry is not None, "premise: the facade existed at Phase 7 entry"
        service = second.identity_service
        assert isinstance(service, IdentityService), "premise: the second boot built the facade"
        crew = {a.id for a in second.registry.all() if is_crew_agent(a, second.ontology)}
        assert set(stored) <= crew, "premise: the second boot keeps every crew slot of the first"
        added = crew - set(stored)
        assert added, (
            "premise: turning the utility agent pools on added no crew slot; use another configuration change that "
            "adds a crew pool (startup/agent_fleet.py)"
        )

        kept = 0  # stored crew slots read at Phase 7 entry
        for slot, ref in stored.items():
            assert ref is not None, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            early = entry[slot]
            assert early is not None, f"{slot}: a slot with a stored certificate must resolve to it before Phase 7"
            assert early == ref and early.did == ref.did, f"{slot}: {early} before Phase 7, {ref} after the first boot"
            assert service.resolve(slot) == ref, f"{slot}: Phase 7 must not change a stored certificate's ref"
            kept += 1
        assert kept > 0, "premise: at least one stored crew slot was registered before Phase 7"

        deferred = 0  # added crew slots unresolved at Phase 7 entry
        tagged = 0  # added crew slots that resolved to an asset ref at Phase 7 entry
        for slot in sorted(added):
            after = service.resolve(slot)
            assert after is not None and after.did, f"{slot}: an added crew slot must resolve with a DID after Phase 7"
            assert after.slot_id == slot, slot
            if slot not in entry:
                continue  # wired in Phase 7, so not readable before it
            before = entry[slot]
            if before is None:
                deferred += 1
                continue
            tagged += 1
            assert before.did == "", (
                f"{slot}: before Phase 7 a crew slot with no stored certificate can hold only an asset tag: {before}"
            )
            assert before.slot_id == after.slot_id, f"{slot}: Phase 7 must keep the slot"
            assert service.resolve(before.sovereign_id) == after, (
                f"{slot}: the asset-tag UUID read before Phase 7 must resolve to the slot's ref after it"
            )
        assert deferred > 0, "premise: at least one added crew slot was unresolved at Phase 7 entry"
        assert tagged > 0, (
            "premise: no added crew slot resolved to an asset ref at Phase 7 entry. T17's premise fails for the same "
            "cause; follow its message, and also drop this premise and the asset clause of T19's docstring."
        )
    finally:
        await second.stop()
```

### Source

None. No file under `src/` changes.

### Trackers: `DECISIONS.md`

A2.D1: D13's first sentence.

SEARCH:
```text
On a vessel's first boot the ontology is None at Phase 2, so the crew test at wiring falls back to a legacy set; a crew type outside it (the yeoman today) gets an asset tag at Phase 2 and its certificate in Phase 7, on the same slot.
```
REPLACE:
```text
At wiring in Phase 2 of every boot the onboarding service has no ontology (it is built without one and receives it in Phase 8), so the crew test falls back to a legacy set; a crew slot of a type outside it (the yeoman today) that has no stored certificate gets an asset tag at Phase 2 and its certificate in Phase 7, on the same slot.
```

A2.D2: D14.

SEARCH:
```text
- *D14 (once in a slot's life).* On a later boot the identity registry loads the stored slot mappings in Phase 1, and slot ids are deterministic, so every crew agent resolves to its stored certificate from Phase 2 and Phase 7 returns the same one. Only a vessel's first boot has an unresolved window or an asset-to-certificate change.
```
REPLACE:
```text
- *D14 (per slot, not per boot).* The identity registry loads every stored slot-to-certificate mapping in Phase 1 of every boot, before any agent is wired, and slot ids are deterministic, so a crew slot with a stored certificate resolves to it from Phase 2 and Phase 7 returns the same one. A crew slot with no stored certificate, on any boot, has D13's window: unresolved from its wiring, or an asset ref if the crew test tagged it, until Phase 7 issues its certificate. That is every crew slot of a fresh data directory, and every crew slot a later boot adds (a configuration change that adds a crew pool, for one). A slot's ref changes from an asset ref to a certificate ref at most once, because nothing removes a certificate from a slot. Rejected: stating the window by boot number, which a later boot that adds crew slots refutes.
```

A2.D3: the binding's window clause.

SEARCH:
```text
On a vessel's first boot crew agents are unresolved from Phase 2 until Phase 7 issues their certificates, except a crew agent the Phase 2 crew test tagged as an asset, which resolves to that asset ref until Phase 7 (D13); on a later boot every crew agent resolves to its stored certificate from Phase 2 (D14).
```
REPLACE:
```text
A crew slot with a stored certificate resolves to it from Phase 2 (D14). A crew slot without one, on any boot, is unresolved from its wiring until Phase 7 issues its certificate, or resolves until then to an asset ref if the Phase 2 crew test tagged it as an asset (D13). M3 infers neither state from the boot number or the phase: it handles None and an asset ref for any crew slot whenever the facade returns one.
```

A2.D4: the binding's lag clause.

SEARCH:
```text
which lags the facade before Phase 7 on a later boot.
```
REPLACE:
```text
which lags the facade before Phase 7 for a crew slot with a stored certificate.
```

A2.D5: the test count.

SEARCH:
```text
- *Tests.* 18: 13 in `tests/test_ad1346_identity_service.py`, over real registries, and 5 real-boot tests in `tests/test_ad1346_identity_service_boot.py` (every identified agent resolves after a boot, the facade exists before the fleet and a failed start releases it, a clean stop releases it, a crew agent's ref across Phase 7 of a first boot, and every crew agent's stored certificate from Phase 2 of a second boot).
```
REPLACE:
```text
- *Tests.* 19: 13 in `tests/test_ad1346_identity_service.py`, over real registries, and 6 real-boot tests in `tests/test_ad1346_identity_service_boot.py` (every identified agent resolves after a boot, the facade exists before the fleet and a failed start releases it, a clean stop releases it, a crew slot's ref across Phase 7 on a fresh data directory, a crew slot's stored certificate before and after Phase 7 of the next boot, and the crew slots a configuration change adds on the next boot, which go through the window while the stored ones do not).
```

A2.D6: R4.

SEARCH:
```text
(R4) A crew slot asset-tagged on its first boot keeps that tag
```
REPLACE:
```text
(R4) A crew slot asset-tagged at wiring before its certificate was issued keeps that tag
```

### Trackers: `PROGRESS.md`

A2.P1: the window sentence.

SEARCH:
```text
crew certificates are issued in Phase 7 of a vessel's first boot, so the facade holds references to the registries and sees them; a crew agent the Phase 2 crew test missed (the yeoman) resolves to an asset ref until then and to its certificate on the same slot after, once in the slot's life.
```
REPLACE:
```text
a crew slot with no stored certificate, on any boot, gets its certificate in Phase 7, so the facade holds references to the registries and sees it; until then that slot is unresolved, or an asset ref if the Phase 2 crew test missed its type (the yeoman), and from then on the certificate ref on the same slot, a change made once in the slot's life; a crew slot with a stored certificate resolves to it from Phase 2.
```

A2.P2: the test count.

SEARCH:
```text
18 new tests (13 unit and structural, 5 real-boot).
```
REPLACE:
```text
19 new tests (13 unit and structural, 6 real-boot).
```

### Acceptance Criteria (replaced and added)

2a (replaced). On a fresh data directory, every crew slot that resolved at Phase 7 entry was an asset ref and keeps its slot, every crew agent resolves with a DID after Phase 7, and no asset ref changes (T17). On the next boot over the same data directory, each crew slot with a stored certificate resolves to it at Phase 7 entry and after it (T18, T19). Each crew slot that boot adds is unresolved or an asset ref at Phase 7 entry, and a certificate ref with a DID on the same slot after it (T19).

2b (new). No M1a text (contract, `DECISIONS.md`, `PROGRESS.md`, the boot test file) states when an identity state is possible by "first boot" or "later boot". Every such statement is qualified by the slot's state at Phase 1 and by the phase, and is pinned by a test or shown by a cited line.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

### Diff Reviewer: properties to verify (replaced and added)

8 (replaced). The "Binding on M3" text in `DECISIONS.md` agrees with D13 and D14. It is keyed on `slot_id`, with at most one asset-to-certificate change per slot. It states every identity state per slot (a stored certificate at Phase 1 or not) and never by boot number. It tells M3 to handle None and an asset ref whenever the facade returns one.
9 (new). T19's premises are asserted and reached. Boot 1 has crew and certified all of them. Boot 2 keeps every boot-1 crew slot and adds at least one. At least one stored slot and one added slot are read at Phase 7 entry. At least one added slot is unresolved there and at least one is an asset ref. The crew sets come from the ontology, and no crew type is named. Boot 2's configuration differs from boot 1's only in `utility_agents`. T19 is green on the unchanged source.
10 (new). A2 changes no file under `src/`. In the boot test file it changes only: the module docstring; T14's premise comment; T17's docstring and two messages; T18's name, docstring and two messages (T18's assertions unchanged); the `UtilityAgentsConfig` import; and the new T19. A grep for `first boot|later boot|second boot|vessel's first|on its first boot` over `DECISIONS.md` (the AD-1346 M1a entry), `PROGRESS.md` line 3 and the boot test file leaves only lines that name a test's own `first` or `second` runtime.

### Verified Against Codebase (2026-10-20, on the staged tree `e21e1161`)

```
runtime.py:2796-2811 AgentOnboardingService(..., ontology=None at :2804, ...); :2818 IdentityService(...); :2820 create_agent_fleet
runtime.py:1198 self.ontology = None; :3326 self.ontology = comm.ontology (after Phase 7 returns)
startup/finalize.py:3936 async def finalize_startup; :5557 runtime.onboarding._ontology = runtime.ontology
agent_onboarding.py:421 is_crew_agent(agent, self._ontology); :425-431 instance_id from ontology, else "Identity deferred"; :446 resolve_or_issue; :469-476 asset tag, sovereign_id = tag.asset_uuid, did = ""
substrate/agent.py:44-45 sovereign_id = "", did = ""
crew_utils.py:69-76 is_crew_agent: ontology crew types, else _WARD_ROOM_CREW
identity.py:567 if not self._db (the load runs once); :589-596 slot_mappings -> _slot_cache (native); :626-632 slot_mappings -> foreign certs; :794 get_by_slot = _slot_cache.get
identity.py:1021-1024 resolve_or_issue returns the stored certificate; :1573-1600 reassign_slot replaces a slot's certificate
startup/communication.py:787-793 ontology built in Phase 7; :889 identity_registry.start(instance_id=...); :898-921 deferred crew certificates
startup/infrastructure.py:170-173 AgentIdentityRegistry(...); await identity_registry.start()
identity_service.py:115-135 _ref_for_slot: certificate first, then asset tag, else None
config_models/crew.py:226-229 UtilityAgentsConfig, enabled: bool = True; config.py:151 re-exported, :3902 SystemConfig.utility_agents
startup/agent_fleet.py:100,121,163,171,179,196,244,252,260,268 if config.utility_agents.enabled; :164 architect, :172 scout, :188 counselor, :197 yeoman, :245-271 officers
tests/test_ad1197_envelope_wiring.py:33-40 from probos.config import ..., UtilityAgentsConfig (import precedent)
tests/test_ad1346_identity_service_boot.py:32 from probos.config import SystemConfig; :55-77 _read_the_facade_at_phase_7_entry; :218-262 T18
```

Measured by others, not by the Architect: the reviewer's probe (`logs/review-m1a-r2.md`) and the orchestrator's probe (`logs/probe_m1a_second_boot.py.txt`). Boot 1 (`utility_agents.enabled = False`): 41 agents, 7 crew. Boot 2: 70 agents, 16 crew. Old slots: 7 certificate refs at Phase 7 entry, unchanged. Added slots: 8 unresolved and 1 asset ref (yeoman) at entry, 9 certificate refs after.

### Absence Verified (2026-10-20)

| Claim | Run | Found | Holds |
|---|---|---|---|
| Nothing removes a certificate from a slot | Grep `_slot_cache\s*(:[^=]*)?=[^=]\|_slot_cache\.\w+\(` and `_slot_cache\[\|_slot_cache\.(pop\|clear\|update)\|del self\._slot_cache\|DELETE FROM slot_mappings` over `src/probos` | init `identity.py:540`; writes `:596, :632, :959, :1594`, each assigning a certificate; reads `:794, :821, :949, :1591`; no pop, clear, del or DELETE | yes |
| No test or check selects T18 by its old name | Grep `test_on_a_second_boot` over the repository, excluding `logs/` | `tests/test_ad1346_identity_service_boot.py:218`; contract `:571, :745` (A1 history) | yes |
| The ledger files carry no wording A2 changes | Grep `first boot\|18 new\|real-boot\|once in the slot` over `docs/development/{ad-ledger-snapshot.json,open-ads-report.md}` | none | yes |
| The two consensus proposer types are not crew | Grep `consensus_proposer` over `config/ontology` | none | yes |
