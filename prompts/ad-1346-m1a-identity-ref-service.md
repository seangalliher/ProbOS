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
