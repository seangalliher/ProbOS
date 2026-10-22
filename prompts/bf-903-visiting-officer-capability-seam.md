# BF-903: visiting-officer capabilities are checked where the officer acts, and the capability names have one owner

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Mechanical repair before the contract was committed (orchestrator, 2026-10-22; no decision changed):** section 7.5's third pair no longer quotes the two lines that end in `session_ttl_seconds=0`. `scripts/phantom-api-precheck.ps1` flags that integer literal against `register`'s float annotation (`type_shape_mismatch`), and the staged contract has to pass the precheck at preflight. The pair now changes only the first `["c"]` case; the other two cases keep their text and still raise `ValueError` on their own earlier checks (no capability, a ttl of zero), which `register` runs before the new capability check. The precheck also lists thirteen candidates for the new `check` and `attach_visiting_officers` methods; they exist only once the code is built, and the check is re-run on the built tree.

**Status:** M1 and M2 are build-ready on `origin/main` `0e122174`. M3 (the channel adapters and the inbound MCP server) is decided in section 3 and follows as Amendment A1 in the same PR; M3 closes #1581. **Tier HIGH.** No new AD or BF number. Both flags stay off: `config/system.yaml:297` and `:933` are not edited. AD-1342 stays paused.

**Tests:** three new files.
- M1 `tests/test_bf903_visitor_scope.py`: 8 functions, 12 cases.
- M2 `tests/test_bf903_ward_room_scope.py`: 8 functions, 35 cases.
- M2 `tests/test_bf903_seam_was_open.py`: 1 case. It is written against names that exist before BF-903, so on today's tree it fails for its premise, not on an import.
- Updated, each with an inline reason: `tests/test_ad701_visiting_officers.py` (6 call sites) and `tests/test_ad802_pairing.py` (1 test).

**Line endings:** every edited working copy is CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own line endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause of #1581 | State | Evidence |
|---|---|---|
| The seam is enforced on Ward Room and router paths | absent | `has_capability(` has no production caller (Absence Verified 1) |
| A path that carries a visitor's own DID into the Ward Room | none today | `runtime.pairing_service` is never assigned (AV2); `paired_did` is never read (AV3); MCP dispatches as the handling agent (`mcp_server.py:474-479`) |
| The HXI routes take actor ids from the request body | present (impersonation) | `routers/wardroom.py:282`, `:352`, `:368`, `:382`, `:396`; `routers/agents.py:3842` |
| One owner for the names | absent | `config_models/crew.py:316-318` (read by nothing, AV5) against `security/pairing/service.py:27` |
| MCP binding | absent | `mcp_server.py:198`, `:331` |
| Expiry at use | partly met | `has_capability` reads expiry (`visiting_officers.py:169`); `get` does not (`:162-163`) |

## 1. Problem

AD-701 says the registry is the enforcement seam and that consumers check `has_capability` before acting. No consumer does. A Ward Room write or read for a visiting officer's DID succeeds whatever its session holds, or with no session at all (`tests/test_bf903_seam_was_open.py`). The capability names live in two unrelated places, and nothing refuses a misspelt one.

## 2. Solution overview

- **M1.**
  - `probos.visiting_officers` owns the four names and refuses any other at `register`, at pairing request and approve, in `probos pairing approve` and at config parse.
  - The registry gains `refusal` and `check`; `get` hides an expired session.
  - The module gains `is_visiting_identity` (by certificate) and the one guard, `require_visitor_capability`.
- **M2.**
  - The Ward Room facade calls the guard at the eleven methods that act for an actor id. The twelve test cases count the DM channel twice, once per participant side.
  - A write needs `dm.send` in a DM channel and `ward_room.post` elsewhere.
  - Finalize attaches the registry, and the API answers a refusal with 403.
- **M3** (Amendment A1): the channel adapters and MCP; see section 16.

## 3. Decisions

- **D1 (premise).** No visitor-identity path into the Ward Room exists today; the routers' body-supplied actor ids are the only way a visiting DID arrives. The guard covers every caller of the facade, present and future.
- **D2 (where; recognition).**
  - (A) **Chosen:** one guard function, applied at the facade now and at the edge entries in M3. A visitor is recognised by its certificate's agent type.
  - (B) Channel layer only: rejected; it misses the routers and future paths.
  - (C) Recognition by registry membership: rejected; it fails open at expiry.
  - (D) Recognition by DID shape: rejected; real visiting DIDs have the crew shape.
  - Entries with no actor id (`get_thread`, `list_threads`, `get_post`, `get_recent_activity`) are guarded at the visitor path's own entry (M3, AD-1342).
  - `create_channel`, `unsubscribe` and the queries that take a subject id stay unguarded (section 9; register).
- **D3 (names).**
  - (A) **Chosen:** a closed set in code; configuration chooses among the names.
  - (B) A set configuration can extend: rejected.
  - (C) Warn only: rejected.
- **D4 (MCP, built in M3).** (A) **Chosen:** refuse arguments that name a visiting DID. (B) A per-visitor token: deferred to AD-1342, which should build it on the MCP authorization spec. (C) Record only: rejected.
- **D5 (the record).**
  - `VISITING_OFFICER_REFUSED` through the registry's emitter, plus a warning; with the registry off, the warning alone.
  - Reason codes: `visitor_session_unknown`, `visitor_session_expired`, `visitor_capability_missing`, `visitor_registry_off`.
  - No `EventType` member: the registry's existing events are strings too. No admission record (#1604).
- **D6 (expiry).** `refusal`, `check` and `get` read the clock at use; `deregister` already removes the session.
- **D7 (M3, coupled).** `_check_pairing`'s `resolve_did` failure fails closed. Slash commands and natural language for a paired sender are refused, because no declared capability grants them. The Captain may overrule.
- **D8 (tier).** HIGH.

**Disclosed effects (M1 and M2)**
1. These now raise `UnknownCapabilityError` (a `ValueError`) for an undeclared name: `register`, `request_pairing`, `approve_pairing`, `probos pairing approve` (prints the reason and returns 1) and `VisitingOfficersConfig`.
   - A `system.yaml` that lists an undeclared name under `visiting_officers.default_capabilities` no longer loads.
   - AD-802's example `--cap tool.use` is refused.
   - A pending row minted before BF-903 that holds an undeclared name is consumed and then refused at approve.
2. `VisitingOfficerRegistry.get` returns None for an expired session.
3. A visiting DID at a guarded entry is refused unless a live session holds the capability; with no registry attached, it is always refused. The API answers 403 `{"error": "visitor_scope_refused", "capability", "reason", "surface"}`.
4. Crew, Captain and system ids behave as before, with no added lookup or query.

## 4. Milestones

One Builder delegation and one local commit per milestone, built in order. Run each focused gate at `-n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Production files | Tests | Focused gate |
|---|---|---|---|
| **M1** | `visiting_officers.py` (7.1), `config_models/crew.py` (7.2), `security/pairing/service.py` (7.3), `__main__.py` (7.4) | new 7.7; update 7.5, 7.6 | `tests/test_bf903_visitor_scope.py tests/test_ad701_visiting_officers.py tests/test_ad802_pairing.py tests/test_ad1270e1_config_facade.py tests/test_ad1346_identity_service.py tests/test_channel_base.py tests/test_bf804_pairing_notification.py` |
| **M2** and trackers | `ward_room/service.py` (7.8), `startup/finalize.py` (7.9), `api.py` (7.10); trackers (section 8) | new 7.11, 7.12 | `tests/test_bf903_ward_room_scope.py tests/test_bf903_seam_was_open.py tests/test_bf903_visitor_scope.py tests/test_ward_room.py tests/test_ward_room_dms.py tests/test_ward_room_agents.py tests/test_api_wardroom.py tests/test_ad615_wardroom_db_hardening.py tests/test_ad613_wardroom_performance.py tests/test_ad1229_message_receipts.py tests/test_ad1229_receipt_facts.py tests/test_ad630_leadership_feedback.py tests/test_bf771_intent_authorization.py tests/test_ad1184_ad_ledger.py` |

**Hard stops**
- If a config-facade or layer test fails because `config_models/crew.py` now imports `probos.visiting_officers` inside a function, stop and report. Do not move the import to module level.
- If an existing test fails because it registered or paired with an undeclared name, update it with an inline `BF-903 (#1581)` reason and never delete it. Stop and report any other failure.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `VISITOR_CAPABILITIES` and `CAP_*` | `register`; `require_known_capabilities`; the pairing defaults; the config default and validator; the Ward Room facade; M3 | one set of names |
| `register` refusing undeclared names | `PairingService.approve_pairing` (`:171`) and `restore_active_sessions` (`:255`, no caller, AV4) | restore catches `Exception` and logs (`:262-266`) |
| `get` hiding expired sessions | no production caller; `test_ad701` `:127`, `:169`, `:201`, `:207` | their assertions hold |
| `has_capability` delegating to `refusal` | no production caller; `test_ad701:180-193` | same truth table |
| `DEFAULT_CAPABILITIES` | `security/pairing/__init__.py` re-export; `request_pairing`; `approve_pairing`; `test_ad802` | same value |
| `UnknownCapabilityError` | the CLI approve branch (7.4) | prints the reason and returns 1 |
| `VisitorScopeRefused` (`PermissionError`) | the API handler (7.10); the routers catch `ValueError` only (`wardroom.py:289`, `:357`, `:371`, `:385`), so it reaches the handler | 403 |
| facade guards | every caller of the eleven methods: crew (slot ids), the Captain, the system | unchanged for them |
| `attach_visiting_officers` | finalize (7.9) | registry attached when AD-701 is on |

## 6. Tests

All tests use real objects: a real `AgentIdentityRegistry` in `tmp_path` (started as `tests/test_ad1346_admission_service.py:92-100` does), the real `VisitingOfficerRegistry` with an injected clock, the real `PairingRegistry` and `PairingService`, a real `WardRoomService` on a temporary database, the real API app and one real boot. W7's Ward Room stand-in only raises the real exception; the guard itself is W1-W6's.

Every BF-903 test errors on today's tree at its `probos.visiting_officers` imports. The **Behaviour** column says what each test asserts and which build it fails on; "guard" means it passes after the fix.

| Id | Test | Premise asserted | Behaviour |
|---|---|---|---|
| V1 | `test_one_vocabulary_names_every_visitor_capability` | registry, pairing and config share one set of names | guard |
| V2 | `test_register_refuses_an_undeclared_capability_before_a_certificate[typo, undeclared, one-of-two, a-bare-string]` | refused by name; no certificate, session or event | fails without 7.1 |
| V3 | `test_the_config_refuses_an_undeclared_default_capability` | refused at parse | fails without 7.2 |
| V4 | `test_pairing_refuses_an_undeclared_capability_before_it_is_stored` | no pending row; the code survives a refused override; the defaults register | fails without 7.3 |
| V5 | `test_the_cli_names_an_undeclared_capability_and_approves_nothing[undeclared-cap-flag, row-minted-before-bf903]` | returns 1, names the capability, records no pairing | fails without 7.3 and 7.4 |
| V6 | `test_the_registry_refuses_by_session_capability_and_expiry_at_use` | three reasons, three events, no sweep; `get` and `has_capability` agree | fails without 7.1 |
| V7 | `test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up` | a certificate outlives its session; crew, ship and unknown DIDs and slot ids are not visitors; no lookup for non-DIDs | fails without 7.1 |
| V8 | `test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow` | crew pass; held served; missing refused; registry off refused; an undeclared name raises | fails without 7.1 |
| W0 | `test_a_visitor_without_ward_room_post_cannot_open_a_thread` (`test_bf903_seam_was_open.py`) | a reader cannot open a thread | **fails today: DID NOT RAISE**, and on the M1-only tree; passes after M2 |
| W1 | `test_a_visitor_without_the_capability_is_refused_at_each_entry[12 entries]` | each entry refuses the one missing capability, naming it and the entry, with one event | fails on M1-only (DID NOT RAISE) |
| W2 | `test_a_visitor_with_only_that_capability_is_served_at_each_entry[12 entries]` | exactly that capability is enough | guard (catches over-refusal) |
| W3 | `test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere[post-in-ship-thread, post-in-dm-thread, thread-in-dm-channel, edit-in-dm-thread]` | the capability follows the channel | fails on M1-only |
| W4 | `test_a_lapsed_or_unattached_session_is_refused_at_its_next_request[expired, deregistered, registry-off]` | expired before the sweep, deregistered and registry off are all refused; crew still post | fails on M1-only |
| W5 | `test_crew_and_the_captain_are_served_as_before_without_a_lookup` | golden: every entry, registry on and off, and no certificate read | guard |
| W6 | `test_a_crew_did_is_served` | a crew certificate DID is not a visitor | guard |
| W7 | `test_the_api_answers_a_visitor_refusal_with_403_and_the_reason` | 403 with the body | fails on M1-only (500) |
| W8 | `test_a_real_boot_scopes_visitors_in_the_ward_room` | finalize attaches the registry: refused for capability, then served | fails on M1-only |

## 7. The contract

Third-party names used below, none of them ProbOS's: `TestClient` is not a ProbOS name (FastAPI's), `Namespace` is not one (argparse's), and `ValidationError` is not one (pydantic's). The tests import the first two under a leading underscore.

### 7.1 `src/probos/visiting_officers.py` (M1)

SEARCH:
```python
- **Capabilities are strings, not enums** (Open/Closed): new caps land
  via configuration, not code edits.
```
REPLACE:
```python
- **Capabilities are strings, not enums**: sessions, pairing rows and
  events carry them as strings. BF-903 (#1581) closes the set: a
  capability means something only where a checking path reads it, and
  that path is code, so a new capability lands in ``VISITOR_CAPABILITIES``
  with its check, in one change. Configuration and the Captain's
  ``--cap`` choose among the declared names; an undeclared one is refused
  by name, so a typo can neither grant nor deny in silence.
- **One guard** (BF-903): every path that acts for an actor id calls
  ``require_visitor_capability`` before acting. A crew member's id is
  never looked up; a visiting officer's DID must hold the capability in a
  live session, read at use.
```

SEARCH:
```python
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"
```
REPLACE:
```python
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"

# BF-903 (#1581): the visiting-officer capability vocabulary, its one owner. The registry, the
# pairing defaults, the config default and every checking path use these names. AD-701 declared
# the two Ward Room capabilities and AD-802 the two DM ones; nothing else is a capability.
CAP_WARD_ROOM_POST: str = "ward_room.post"
CAP_WARD_ROOM_READ: str = "ward_room.read"
CAP_DM_SEND: str = "dm.send"
CAP_DM_RECEIVE: str = "dm.receive"
VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE})

# BF-903: why a visiting officer was refused (AD-1316's stable-code syntax). The refusal event
# and ``VisitorScopeRefused.reason`` carry one of these.
REFUSED_NO_SESSION: str = "visitor_session_unknown"
REFUSED_EXPIRED: str = "visitor_session_expired"
REFUSED_CAPABILITY: str = "visitor_capability_missing"
REFUSED_REGISTRY_OFF: str = "visitor_registry_off"


class UnknownCapabilityError(ValueError):
    """BF-903: a capability name the vocabulary does not declare."""

    def __init__(self, unknown: Iterable[str]) -> None:
        self.unknown: tuple[str, ...] = tuple(unknown)
        super().__init__(
            f"undeclared visiting-officer capabilities {list(self.unknown)!r}; "
            f"declared: {sorted(VISITOR_CAPABILITIES)!r} (BF-903)"
        )


class VisitorScopeRefused(PermissionError):
    """BF-903: a visiting officer's request that its session does not allow.

    ``reason`` is one of the ``REFUSED_*`` codes. The API answers it with 403, as it answers
    BF-771's denial (``api.py``).
    """

    def __init__(self, did: str, capability: str, reason: str, surface: str) -> None:
        self.did = did
        self.capability = capability
        self.reason = reason
        self.surface = surface
        super().__init__(
            f"BF-903: visiting officer {did} may not use {capability!r} at {surface}: {reason}"
        )


def require_known_capabilities(capabilities: Iterable[str]) -> None:
    """BF-903: raise ``UnknownCapabilityError`` naming every capability the vocabulary lacks.

    A bare string is iterated as its characters and so refused, never read as one name.
    """
    unknown = [c for c in dict.fromkeys(capabilities) if c not in VISITOR_CAPABILITIES]
    if unknown:
        raise UnknownCapabilityError(unknown)
```

SEARCH:
```python
      - has_capability(did, capability) -> bool
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    Consumers SHOULD call ``has_capability(did, "ward_room.post")`` before
    relaying a Ward Room post on behalf of a visiting officer (D4).
    """
```
REPLACE:
```python
      - has_capability(did, capability) -> bool
      - refusal(did, capability) -> str | None   (BF-903)
      - check(did, capability, *, surface) -> None   (BF-903; raises on refusal)
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    BF-903: consumers call the module's ``require_visitor_capability``,
    which recognises a visiting officer and then calls ``check``. ``get``,
    ``refusal`` and ``check`` read expiry at use, so an expired session is
    refused before the sweep removes it.
    """
```

SEARCH:
```python
        if ttl <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        cert = await self._identity.issue_birth_certificate(
```
REPLACE:
```python
        if ttl <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        require_known_capabilities(capabilities)  # BF-903 (#1581): refused before a certificate is issued
        cert = await self._identity.issue_birth_certificate(
```

SEARCH:
```python
    def get(self, did: str) -> VisitingOfficerSession | None:
        return self._sessions.get(did)

    def has_capability(self, did: str, capability: str) -> bool:
        session = self._sessions.get(did)
        if session is None:
            return False
        if self._clock() >= session.expires_at:
            return False
        return capability in session.capabilities
```
REPLACE:
```python
    def get(self, did: str) -> VisitingOfficerSession | None:
        session = self._sessions.get(did)
        if session is None or self._clock() >= session.expires_at:  # BF-903: an expired session is gone at use
            return None
        return session

    def refusal(self, did: str, capability: str) -> str | None:
        """BF-903: why ``did`` may not use ``capability`` now, or None when it may.

        Read at each use: a deregistered session is refused at once and an expired one before
        the sweep removes it.
        """
        session = self._sessions.get(did)
        if session is None:
            return REFUSED_NO_SESSION
        if self._clock() >= session.expires_at:
            return REFUSED_EXPIRED
        if capability not in session.capabilities:
            return REFUSED_CAPABILITY
        return None

    def has_capability(self, did: str, capability: str) -> bool:
        return self.refusal(did, capability) is None

    def check(self, did: str, capability: str, *, surface: str) -> None:
        """BF-903: return when ``did`` may use ``capability``; otherwise record the refusal and raise.

        The record is a ``VISITING_OFFICER_REFUSED`` event through this registry's emitter, the
        sink its registration and deregistration events use, and a warning.
        """
        reason = self.refusal(did, capability)
        if reason is None:
            return
        self._emit("VISITING_OFFICER_REFUSED", {
            "did": did, "capability": capability, "reason": reason, "surface": surface,
        })
        logger.warning("BF-903: refused visiting officer %s %r at %s: %s", did, capability, surface, reason)
        raise VisitorScopeRefused(did, capability, reason, surface)
```

SEARCH:
```python
            logger.warning(
                "AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True
            )
```
REPLACE:
```python
            logger.warning(
                "AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True
            )


def is_visiting_identity(identity_registry: Any, actor_id: object) -> bool:
    """BF-903: whether ``actor_id`` is the DID of a visiting officer's birth certificate.

    Only a did:probos agent DID is looked up, in the identity registry's in-memory certificate
    cache (``get_by_uuid``, which never raises), so a slot id, a callsign, "captain" or "system"
    costs no lookup and is never refused here. The certificate outlives its session, so an
    expired or deregistered visitor is still recognised and refused. BF-907's
    ``resolve_slot_id`` and AD-1346's ``IdentityService.resolve`` return None for a visitor,
    which holds no slot, so they cannot classify one; this reads the agent type AD-701 sets.
    """
    if type(actor_id) is not str or not actor_id.startswith("did:") or identity_registry is None:
        return False
    from probos.identity import parse_did  # BF-903: imported at use, so loading this module loads no other ProbOS module

    parsed = parse_did(actor_id)
    if parsed is None or parsed.get("type") != "agent":
        return False
    cert = identity_registry.get_by_uuid(parsed["agent_uuid"])
    return cert is not None and cert.agent_type == VISITING_AGENT_TYPE


def require_visitor_capability(
    actor_id: str,
    capability: str,
    *,
    surface: str,
    identity_registry: Any,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): the one check every path that acts for an actor id calls before it acts.

    A crew member, the Captain or the system passes without a lookup. A visiting officer must
    hold ``capability`` in a live session; with AD-701's registry off it holds none and is
    refused. ``surface`` names the entry in the refusal and its record. An undeclared
    ``capability`` raises ``UnknownCapabilityError`` whoever acts, so a typo in a checking
    path fails on its first call.
    """
    if capability not in VISITOR_CAPABILITIES:
        raise UnknownCapabilityError([capability])
    if not is_visiting_identity(identity_registry, actor_id):
        return
    if visiting_officers is None:
        logger.warning(
            "BF-903: refused visiting officer %s %r at %s: AD-701's registry is off, so no session exists",
            actor_id, capability, surface,
        )
        raise VisitorScopeRefused(actor_id, capability, REFUSED_REGISTRY_OFF, surface)
    visiting_officers.check(actor_id, capability, surface=surface)
```

### 7.2 `src/probos/config_models/crew.py` (M1)

SEARCH:
```python
class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.
```
REPLACE:
```python
def _default_visitor_capabilities() -> list[str]:
    """BF-903 (#1581): the default comes from the vocabulary's one owner.

    Imported at call time, so loading the config models loads no other ProbOS package.
    """
    from probos.visiting_officers import CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ

    return [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]


class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.
```

SEARCH:
```python
    default_capabilities: list[str] = Field(
        default_factory=lambda: ["ward_room.post", "ward_room.read"]
    )
```
REPLACE:
```python
    default_capabilities: list[str] = Field(default_factory=_default_visitor_capabilities)

    @field_validator("default_capabilities")
    @classmethod
    def _declared_capabilities_only(cls, value: list[str]) -> list[str]:
        """BF-903: an undeclared capability is refused when the configuration is parsed."""
        from probos.visiting_officers import require_known_capabilities

        require_known_capabilities(value)
        return value
```

### 7.3 `src/probos/security/pairing/service.py` (M1)

SEARCH:
```python
    UnknownPairingCode,
)

logger = logging.getLogger(__name__)
```
REPLACE:
```python
    UnknownPairingCode,
)
from probos.visiting_officers import CAP_DM_RECEIVE, CAP_DM_SEND, require_known_capabilities

logger = logging.getLogger(__name__)
```

SEARCH:
```python
DEFAULT_CAPABILITIES = ("dm.send", "dm.receive")
```
REPLACE:
```python
DEFAULT_CAPABILITIES = (CAP_DM_SEND, CAP_DM_RECEIVE)  # BF-903: AD-802's defaults, named by the vocabulary's owner
```

SEARCH:
```python
        caps = tuple(capabilities or DEFAULT_CAPABILITIES)
        code = self._generate_code()
```
REPLACE:
```python
        caps = tuple(capabilities or DEFAULT_CAPABILITIES)
        require_known_capabilities(caps)  # BF-903: refused before a pending row is minted
        code = self._generate_code()
```

SEARCH:
```python
        pending = self._registry.consume_pending(channel, code)
        if pending is None:
            raise UnknownPairingCode(f"No pending pairing for channel={channel!r} code={code!r}")
```
REPLACE:
```python
        if capabilities_override:
            require_known_capabilities(capabilities_override)  # BF-903: refused before the code is consumed
        pending = self._registry.consume_pending(channel, code)
        if pending is None:
            raise UnknownPairingCode(f"No pending pairing for channel={channel!r} code={code!r}")
```

SEARCH:
```python
        if not caps:
            caps = DEFAULT_CAPABILITIES
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl
```
REPLACE:
```python
        if not caps:
            caps = DEFAULT_CAPABILITIES
        require_known_capabilities(caps)  # BF-903: a row minted before BF-903 may hold any string
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl
```

### 7.4 `src/probos/__main__.py` (M1)

SEARCH:
```python
    from probos.security.pairing import (
        PairingRegistry,
        PairingService,
        UnknownPairingCode,
    )
```
REPLACE:
```python
    from probos.security.pairing import (
        PairingRegistry,
        PairingService,
        UnknownPairingCode,
    )
    from probos.visiting_officers import UnknownCapabilityError
```

SEARCH:
```python
        except UnknownPairingCode as exc:
            console.print(f"[red]Approve failed:[/red] {exc}")
```
REPLACE:
```python
        except (UnknownPairingCode, UnknownCapabilityError) as exc:  # BF-903: an undeclared --cap is refused with its name
            console.print(f"[red]Approve failed:[/red] {exc}")
```

### 7.5 `tests/test_ad701_visiting_officers.py` (M1: "c" was any string; it is an undeclared name now)

The pairs apply in order. After the fourth and fifth, the last `["c"]` call is unique.

SEARCH:
```python
    await reg.register(callsign="x", capabilities=["c"], origin="o")
```
REPLACE:
```python
    # BF-903 (#1581): a capability is a declared name now; "c" is refused at register.
    await reg.register(callsign="x", capabilities=["ward_room.read"], origin="o")
```

SEARCH:
```python
    assert payload["capabilities"] == ["c"]
```
REPLACE:
```python
    assert payload["capabilities"] == ["ward_room.read"]
```

SEARCH:
```python
    with pytest.raises(ValueError):
        await reg.register(callsign="", capabilities=["c"])
```
REPLACE:
```python
    # BF-903 (#1581): a declared capability, so the empty callsign is what raises. The next two
    # cases keep their text: each raises on its own earlier check (no capability, a ttl of zero)
    # before the capability check runs, so they stay ValueError cases for the reason they name.
    with pytest.raises(ValueError):
        await reg.register(callsign="", capabilities=["ward_room.read"])
```

SEARCH:
```python
    reg, _identity, emit_log, _clock = _make_registry()
    session = await reg.register(callsign="x", capabilities=["c"])
```
REPLACE:
```python
    reg, _identity, emit_log, _clock = _make_registry()
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
```

SEARCH:
```python
    reg, _identity, emit_log, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["c"])
```
REPLACE:
```python
    reg, _identity, emit_log, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
```

SEARCH:
```python
    s1 = await reg.register(callsign="alive", capabilities=["c"])
    s2 = await reg.register(
        callsign="dying", capabilities=["c"], session_ttl_seconds=5.0
    )
```
REPLACE:
```python
    s1 = await reg.register(callsign="alive", capabilities=["ward_room.read"])  # BF-903: a declared name
    s2 = await reg.register(
        callsign="dying", capabilities=["ward_room.read"], session_ttl_seconds=5.0
    )
```

SEARCH:
```python
    )
    session = await reg.register(callsign="x", capabilities=["c"])
    assert session.did.startswith("did:probos:")
```
REPLACE:
```python
    )
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
    assert session.did.startswith("did:probos:")
```

### 7.6 `tests/test_ad802_pairing.py` (M1: the test pinned "tool.use" as grantable)

SEARCH:
```python
    paired = await service.approve_pairing(
        "telegram", code,
        capabilities_override=["dm.send", "tool.use", "ward_room.post"],
    )
    assert "tool.use" in paired.capabilities
    assert "ward_room.post" in paired.capabilities
```
REPLACE:
```python
    # BF-903 (#1581): "tool.use" was AD-802's example override, but no checking path reads it, so it is
    # refused now (tests/test_bf903_visitor_scope.py). The override still replaces the requested set.
    paired = await service.approve_pairing(
        "telegram", code,
        capabilities_override=["dm.send", "ward_room.post"],
    )
    assert set(paired.capabilities) == {"dm.send", "ward_room.post"}
```

### 7.7 New file: `tests/test_bf903_visitor_scope.py` (M1)

```python
"""BF-903 (#1581) M1: one owner for the visiting-officer capability names, and AD-701's registry as the seam.

Real objects: a real ``AgentIdentityRegistry`` in ``tmp_path`` (started and commissioned as
``tests/test_ad1346_admission_service.py`` does), the real ``VisitingOfficerRegistry`` with an injected clock, the
real ``PairingRegistry`` and ``PairingService``, the real config models and the real ``probos pairing approve``.
Nothing reads the live data directory.
"""

from __future__ import annotations

from argparse import Namespace as _Namespace  # the standard library's, not a ProbOS name
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import probos.__main__ as probos_main
from probos.config import SystemConfig, VisitingOfficersConfig
from probos.identity import AgentIdentityRegistry
from probos.security.pairing import DEFAULT_CAPABILITIES, PairingRegistry, PairingService
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VISITOR_CAPABILITIES,
    UnknownCapabilityError,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
    is_visiting_identity,
    require_visitor_capability,
)

INSTANCE_ID = "bf903-m1-ship"
VESSEL_NAME = "Bf903m1"
CREW_SLOT = "counselor_counselor_0_67c601cb"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
Events = list[tuple[str, dict[str, Any]]]


class _Clock:
    """The registry's injected clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def identities(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield registry
    finally:
        await registry.stop()


def _officers(identities: AgentIdentityRegistry, clock: _Clock, events: Events) -> VisitingOfficerRegistry:
    return VisitingOfficerRegistry(
        identities,
        instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME,
        baseline_version="1",
        emit_event=lambda name, payload: events.append((name, payload)),
        clock=clock,
    )


async def _crew(identities: AgentIdentityRegistry) -> Any:
    return await identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


def test_one_vocabulary_names_every_visitor_capability() -> None:
    """V1: the registry, the pairing defaults and the config default use one set of four names."""
    assert (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE) == (
        "ward_room.post", "ward_room.read", "dm.send", "dm.receive",
    )
    assert VISITOR_CAPABILITIES == frozenset({"ward_room.post", "ward_room.read", "dm.send", "dm.receive"})
    assert DEFAULT_CAPABILITIES == (CAP_DM_SEND, CAP_DM_RECEIVE)
    assert VisitingOfficersConfig().default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]
    assert SystemConfig().visiting_officers.default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]


@pytest.mark.parametrize(
    ("capabilities", "unknown"),
    [
        (["ward_room.pots"], ("ward_room.pots",)),
        (["tool.use"], ("tool.use",)),
        ([CAP_DM_SEND, "tool.use", "tool.use"], ("tool.use",)),
        ("dm.send", ("d", "m", ".", "s", "e", "n")),
    ],
    ids=["typo", "undeclared", "one-of-two", "a-bare-string"],
)
async def test_register_refuses_an_undeclared_capability_before_a_certificate(
    identities: AgentIdentityRegistry, capabilities: Any, unknown: tuple[str, ...],
) -> None:
    """V2: an undeclared name is refused by name; no certificate, session or event follows."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    births = len(identities.get_all())
    with pytest.raises(UnknownCapabilityError) as refused:
        await officers.register("visitor", capabilities)
    assert refused.value.unknown == unknown
    assert len(identities.get_all()) == births
    assert officers.active() == ()
    assert events == []


def test_the_config_refuses_an_undeclared_default_capability() -> None:
    """V3: an undeclared name in visiting_officers.default_capabilities fails when the config is parsed."""
    with pytest.raises(ValidationError, match="tool.use"):
        VisitingOfficersConfig(default_capabilities=[CAP_WARD_ROOM_POST, "tool.use"])
    assert VisitingOfficersConfig(default_capabilities=[CAP_DM_SEND]).default_capabilities == [CAP_DM_SEND]


async def test_pairing_refuses_an_undeclared_capability_before_it_is_stored(
    identities: AgentIdentityRegistry, tmp_path: Path,
) -> None:
    """V4: a request or an override naming an undeclared capability stores nothing, the refused override
    leaves the code usable, and the defaults register as declared capabilities."""
    officers = _officers(identities, _Clock(), [])
    store = PairingRegistry(tmp_path / "pairings.db")
    service = PairingService(store, officers)
    with pytest.raises(UnknownCapabilityError):
        await service.request_pairing("telegram", "tg-1", capabilities=["tool.use"])
    assert store.list_pending() == []
    code = await service.request_pairing("telegram", "tg-1")
    with pytest.raises(UnknownCapabilityError):
        await service.approve_pairing("telegram", code, capabilities_override=[CAP_DM_SEND, "tool.use"])
    assert store.get_pending("telegram", code) is not None
    assert officers.active() == ()
    paired = await service.approve_pairing("telegram", code)
    session = officers.get(paired.did)
    assert session is not None
    assert session.capabilities == frozenset({CAP_DM_SEND, CAP_DM_RECEIVE})


@pytest.mark.parametrize(
    ("stored", "cap"),
    [([CAP_DM_SEND], "dm.send,tool.use"), (["tool.use"], None)],
    ids=["undeclared-cap-flag", "row-minted-before-bf903"],
)
def test_the_cli_names_an_undeclared_capability_and_approves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    stored: list[str], cap: str | None,
) -> None:
    """V5: `probos pairing approve` names the undeclared capability, returns 1 and records no pairing;
    a refused --cap leaves the code pending (the offline approve has no registry to refuse it)."""
    data = tmp_path / "data"
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)
    store = PairingRegistry(data / "pairings.db")
    store.mint_pending("telegram", "tg-9", "ABCDEF", stored, ttl_seconds=600.0)
    status = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=cap, ttl_days=None),
    )
    assert status == 1
    assert "tool.use" in capsys.readouterr().out
    assert store.list_paired() == []
    assert (store.get_pending("telegram", "ABCDEF") is not None) is (cap is not None)


async def test_the_registry_refuses_by_session_capability_and_expiry_at_use(identities: AgentIdentityRegistry) -> None:
    """V6: check() serves a held capability and refuses a missing one, a deregistered session and an expired
    one before any sweep, each with its code and one event; get() and has_capability agree."""
    clock = _Clock()
    events: Events = []
    officers = _officers(identities, clock, events)
    reader = await officers.register("reader", [CAP_WARD_ROOM_READ], session_ttl_seconds=10.0)
    gone = await officers.register("gone", [CAP_WARD_ROOM_READ])
    officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    with pytest.raises(VisitorScopeRefused) as missing:
        officers.check(reader.did, CAP_WARD_ROOM_POST, surface="v6.post")
    assert (missing.value.did, missing.value.capability, missing.value.reason, missing.value.surface) == (
        reader.did, CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "v6.post",
    )
    officers.deregister(gone.did)
    with pytest.raises(VisitorScopeRefused) as deregistered:
        officers.check(gone.did, CAP_WARD_ROOM_READ, surface="v6.gone")
    assert deregistered.value.reason == REFUSED_NO_SESSION
    clock.now += 10.0
    assert officers.get(reader.did) is None
    assert officers.has_capability(reader.did, CAP_WARD_ROOM_READ) is False
    with pytest.raises(VisitorScopeRefused) as expired:
        officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    assert expired.value.reason == REFUSED_EXPIRED
    assert _refusals(events) == [
        {"did": reader.did, "capability": CAP_WARD_ROOM_POST, "reason": REFUSED_CAPABILITY, "surface": "v6.post"},
        {"did": gone.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_NO_SESSION, "surface": "v6.gone"},
        {"did": reader.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_EXPIRED, "surface": "v6.read"},
    ]
    assert [p["reason"] for n, p in events if n == "VISITING_OFFICER_DEREGISTERED"] == ["explicit"]


async def test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up(
    identities: AgentIdentityRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V7: a visiting certificate's DID is a visitor even after its session ends; a crew DID, an unknown DID,
    the ship's DID and a missing registry are not; ids that are not DIDs are never looked up."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    crew = await _crew(identities)
    assert is_visiting_identity(identities, session.did) is True
    officers.deregister(session.did)
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, crew.did) is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}:{UNKNOWN_UUID}") is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}") is False
    assert is_visiting_identity(None, session.did) is False

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: an id that is not a DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (CREW_SLOT, "captain", "system", crew.agent_uuid, "", None):
        assert is_visiting_identity(identities, actor) is False


async def test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow(
    identities: AgentIdentityRegistry,
) -> None:
    """V8: crew pass with or without the registry; a visitor is served a held capability, refused a missing
    one and refused outright with the registry off; an undeclared capability raises for anyone."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    for registry in (None, officers):
        require_visitor_capability(
            CREW_SLOT, CAP_WARD_ROOM_POST, surface="v8", identity_registry=identities, visiting_officers=registry,
        )
    require_visitor_capability(
        session.did, CAP_WARD_ROOM_READ, surface="v8", identity_registry=identities, visiting_officers=officers,
    )
    with pytest.raises(VisitorScopeRefused) as missing:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_POST, surface="v8.post", identity_registry=identities,
            visiting_officers=officers,
        )
    assert missing.value.reason == REFUSED_CAPABILITY
    with pytest.raises(VisitorScopeRefused) as off:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_READ, surface="v8.off", identity_registry=identities, visiting_officers=None,
        )
    assert (off.value.reason, off.value.surface) == (REFUSED_REGISTRY_OFF, "v8.off")
    with pytest.raises(UnknownCapabilityError):
        require_visitor_capability(
            CREW_SLOT, "ward_room.pots", surface="v8", identity_registry=identities, visiting_officers=officers,
        )
    assert [p["surface"] for p in _refusals(events)] == ["v8.post"]
```

### 7.8 `src/probos/ward_room/service.py` (M2)

SEARCH:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.ward_room.channels import ChannelManager
```
REPLACE:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    is_visiting_identity,
    require_visitor_capability,
)
from probos.ward_room.channels import ChannelManager
```

SEARCH:
```python
logger = logging.getLogger(__name__)


class WardRoomService(EventEmitterMixin):
```
REPLACE:
```python
logger = logging.getLogger(__name__)

# BF-903 (#1581): the channel type a visiting officer's write lands in. Read only for a visiting
# officer, so a crew write costs no query; a DM channel needs dm.send, any other ward_room.post.
_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ?"
_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ?"
_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ?"


class WardRoomService(EventEmitterMixin):
```

SEARCH:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
```
REPLACE:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
        self._visiting_officers: Any = None  # BF-903: AD-701's registry, attached by finalize when it is on
```

SEARCH:
```python
    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference (constructed after WardRoom)."""
        self._ontology = ontology
```
REPLACE:
```python
    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference (constructed after WardRoom)."""
        self._ontology = ontology

    def attach_visiting_officers(self, registry: Any) -> None:
        """BF-903 (#1581): late-bind AD-701's registry, which finalize builds after the Ward Room.

        Unattached (and whenever AD-701 is off), a visiting officer's DID is refused at every
        guarded entry. A crew member's or the Captain's id is never looked up either way.
        """
        self._visiting_officers = registry

    def _require_visitor(self, actor_id: str, capability: str, entry: str) -> None:
        """BF-903: refuse a visiting officer whose session lacks ``capability`` at ``entry``; anyone else passes."""
        require_visitor_capability(
            actor_id,
            capability,
            surface=f"ward_room.{entry}",
            identity_registry=self._identity_registry,
            visiting_officers=self._visiting_officers,
        )

    async def _require_visitor_write(self, actor_id: str, entry: str, query: str, key: str) -> None:
        """BF-903: a visiting officer's write needs dm.send in a DM channel and ward_room.post elsewhere."""
        if not is_visiting_identity(self._identity_registry, actor_id):
            return
        channel_type = ""
        if self._db is not None:
            async with self._db.execute(query, (key,)) as cursor:
                row = await cursor.fetchone()
            channel_type = row[0] if row else ""
        capability = CAP_DM_SEND if channel_type == "dm" else CAP_WARD_ROOM_POST
        self._require_visitor(actor_id, capability, entry)
```

SEARCH:
```python
        return await self._channels.list_channels(agent_id)
```
REPLACE:
```python
        self._require_visitor(agent_id or "", CAP_WARD_ROOM_READ, "list_channels")  # BF-903
        return await self._channels.list_channels(agent_id)
```

SEARCH:
```python
        return await self._channels.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)
```
REPLACE:
```python
        for participant in (agent_a_id, agent_b_id):  # BF-903: a visiting officer in a DM must be able to receive it
            self._require_visitor(participant, CAP_DM_RECEIVE, "get_or_create_dm_channel")
        return await self._channels.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)
```

SEARCH:
```python
        return await self._threads.browse_threads(agent_id, channels, thread_mode, limit, since, sort)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "browse_threads")  # BF-903
        return await self._threads.browse_threads(agent_id, channels, thread_mode, limit, since, sort)
```

SEARCH:
```python
    ) -> WardRoomThread:
        return await self._threads.create_thread(
```
REPLACE:
```python
    ) -> WardRoomThread:
        await self._require_visitor_write(author_id, "create_thread", _CHANNEL_TYPE_OF_CHANNEL, channel_id)  # BF-903
        return await self._threads.create_thread(
```

SEARCH:
```python
        return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)
```
REPLACE:
```python
        await self._require_visitor_write(author_id, "create_post", _CHANNEL_TYPE_OF_THREAD, thread_id)  # BF-903
        return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)
```

SEARCH:
```python
        return await self._messages.edit_post(post_id, author_id, new_body)
```
REPLACE:
```python
        await self._require_visitor_write(author_id, "edit_post", _CHANNEL_TYPE_OF_POST, post_id)  # BF-903
        return await self._messages.edit_post(post_id, author_id, new_body)
```

SEARCH:
```python
        return await self._messages.endorse(target_id, target_type, voter_id, direction)
```
REPLACE:
```python
        self._require_visitor(voter_id, CAP_WARD_ROOM_POST, "endorse")  # BF-903
        return await self._messages.endorse(target_id, target_type, voter_id, direction)
```

SEARCH:
```python
        await self._messages.subscribe(agent_id, channel_id, role)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "subscribe")  # BF-903
        await self._messages.subscribe(agent_id, channel_id, role)
```

SEARCH:
```python
        await self._messages.update_last_seen(agent_id, channel_id)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "update_last_seen")  # BF-903
        await self._messages.update_last_seen(agent_id, channel_id)
```

SEARCH:
```python
        return await self._messages.get_unread_counts(agent_id)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "get_unread_counts")  # BF-903
        return await self._messages.get_unread_counts(agent_id)
```

SEARCH:
```python
        return await self._messages.get_unread_dms(agent_id, limit, exchange_limit=exchange_limit)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_DM_RECEIVE, "get_unread_dms")  # BF-903
        return await self._messages.get_unread_dms(agent_id, limit, exchange_limit=exchange_limit)
```

### 7.9 `src/probos/startup/finalize.py` (M2)

SEARCH:
```python
        await runtime.visiting_officers.start()
        logger.info(
            "AD-701: VisitingOfficerRegistry wired (ttl=%.0fs, sweep=%.0fs)",
```
REPLACE:
```python
        await runtime.visiting_officers.start()
        if runtime.ward_room is not None:  # BF-903 (#1581): the Ward Room checks visiting officers against this registry
            runtime.ward_room.attach_visiting_officers(runtime.visiting_officers)
        logger.info(
            "AD-701: VisitingOfficerRegistry wired (ttl=%.0fs, sweep=%.0fs)",
```

### 7.10 `src/probos/api.py` (M2)

SEARCH:
```python
from probos.routers.auth import verify_ws_token
from probos.ws_event_stream import WSEventStreamHub
```
REPLACE:
```python
from probos.routers.auth import verify_ws_token
from probos.visiting_officers import VisitorScopeRefused
from probos.ws_event_stream import WSEventStreamHub
```

SEARCH:
```python
                "reason": str(exc.reason),
            },
        )

    # CORS for HXI dev server (AD-260)
```
REPLACE:
```python
                "reason": str(exc.reason),
            },
        )

    # BF-903 (#1581): a visiting officer refused by AD-701's seam is a policy outcome, as BF-771's
    # denial is, so a route that reaches a guarded Ward Room entry answers 403 with the reason.
    @app.exception_handler(VisitorScopeRefused)
    async def _visitor_refused(_request: Request, exc: VisitorScopeRefused) -> JSONResponse:
        logger.info("BF-903: %s at the API boundary", exc)
        return JSONResponse(
            status_code=403,
            content={
                "error": "visitor_scope_refused",
                "capability": exc.capability,
                "reason": exc.reason,
                "surface": exc.surface,
            },
        )

    # CORS for HXI dev server (AD-260)
```

### 7.11 New file: `tests/test_bf903_ward_room_scope.py` (M2)

```python
"""BF-903 (#1581) M2: the Ward Room checks a visiting officer's capability at every entry that acts for an actor id.

Real objects: a real ``AgentIdentityRegistry`` and ``WardRoomService`` in ``tmp_path``, the real
``VisitingOfficerRegistry`` with an injected clock, the real API app for the 403, and one real boot (mock LLM).
Crew act by slot id, as ``agent.id`` does, and the Captain by "captain".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient as _TestClient  # FastAPI's, not a ProbOS name

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AuthConfig, SystemConfig
from probos.identity import AgentIdentityRegistry
from probos.runtime import ProbOSRuntime
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
)
from probos.ward_room.service import WardRoomService

INSTANCE_ID = "bf903-m2-ship"
VESSEL_NAME = "Bf903m2"
CREW_SLOT = "counselor_counselor_0_67c601cb"
ALL = (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE)
Events = list[tuple[str, dict[str, Any]]]

#: entry -> (the capability a visitor needs there, the refusal's surface)
ENTRIES: dict[str, tuple[str, str]] = {
    "create_thread": (CAP_WARD_ROOM_POST, "ward_room.create_thread"),
    "create_post": (CAP_WARD_ROOM_POST, "ward_room.create_post"),
    "edit_post": (CAP_WARD_ROOM_POST, "ward_room.edit_post"),
    "endorse": (CAP_WARD_ROOM_POST, "ward_room.endorse"),
    "subscribe": (CAP_WARD_ROOM_READ, "ward_room.subscribe"),
    "update_last_seen": (CAP_WARD_ROOM_READ, "ward_room.update_last_seen"),
    "browse_threads": (CAP_WARD_ROOM_READ, "ward_room.browse_threads"),
    "list_channels": (CAP_WARD_ROOM_READ, "ward_room.list_channels"),
    "get_unread_counts": (CAP_WARD_ROOM_READ, "ward_room.get_unread_counts"),
    "get_unread_dms": (CAP_DM_RECEIVE, "ward_room.get_unread_dms"),
    "dm_channel_as_a": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
    "dm_channel_as_b": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _Rig:
    identities: AgentIdentityRegistry
    officers: VisitingOfficerRegistry
    ward_room: WardRoomService
    clock: _Clock
    events: Events
    all_hands: str
    crew_thread: str
    crew_post: str
    dm_channel: str
    dm_thread: str
    dm_post: str


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        await ward_room.start()
        clock = _Clock()
        events: Events = []
        officers = VisitingOfficerRegistry(
            identities, instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, baseline_version="1",
            emit_event=lambda name, payload: events.append((name, payload)), clock=clock,
        )
        ward_room.attach_visiting_officers(officers)
        all_hands = await ward_room.get_channel_by_name("All Hands")
        thread = await ward_room.create_thread(all_hands.id, CREW_SLOT, "Crew thread", "crew body")
        post = await ward_room.create_post(thread.id, CREW_SLOT, "crew post")
        dm = await ward_room.get_or_create_dm_channel(CREW_SLOT, "captain")
        dm_thread = await ward_room.create_thread(dm.id, CREW_SLOT, "Crew DM", "dm body")
        dm_post = await ward_room.create_post(dm_thread.id, CREW_SLOT, "dm post")
        yield _Rig(
            identities, officers, ward_room, clock, events,
            all_hands.id, thread.id, post.id, dm.id, dm_thread.id, dm_post.id,
        )
    finally:
        await ward_room.stop()
        await identities.stop()


async def _visitor(rig: _Rig, *capabilities: str) -> str:
    session = await rig.officers.register("visitor", list(capabilities))
    return session.did


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


async def _act(rig: _Rig, entry: str, actor: str, *, own: bool) -> None:
    """One call at ``entry`` as ``actor``; with ``own`` an edit targets a post the actor writes first."""
    wr = rig.ward_room
    if entry == "create_thread":
        await wr.create_thread(rig.all_hands, actor, "A visitor's thread", "body")
    elif entry == "create_post":
        await wr.create_post(rig.crew_thread, actor, "a reply")
    elif entry == "edit_post":
        target = (await wr.create_post(rig.crew_thread, actor, "mine")).id if own else rig.crew_post
        await wr.edit_post(target, actor, "edited")
    elif entry == "endorse":
        await wr.endorse(rig.crew_post, "post", actor, "up")
    elif entry == "subscribe":
        await wr.subscribe(actor, rig.all_hands)
    elif entry == "update_last_seen":
        await wr.update_last_seen(actor, rig.all_hands)
    elif entry == "browse_threads":
        await wr.browse_threads(actor)
    elif entry == "list_channels":
        await wr.list_channels(actor)
    elif entry == "get_unread_counts":
        await wr.get_unread_counts(actor)
    elif entry == "get_unread_dms":
        await wr.get_unread_dms(actor)
    elif entry == "dm_channel_as_a":
        await wr.get_or_create_dm_channel(actor, CREW_SLOT)
    elif entry == "dm_channel_as_b":
        await wr.get_or_create_dm_channel(CREW_SLOT, actor)
    else:
        raise AssertionError(f"not an entry: {entry}")


async def _write(rig: _Rig, where: str, actor: str, *, own: bool) -> None:
    wr = rig.ward_room
    if where == "post-in-ship-thread":
        await wr.create_post(rig.crew_thread, actor, "reply")
    elif where == "post-in-dm-thread":
        await wr.create_post(rig.dm_thread, actor, "reply")
    elif where == "thread-in-dm-channel":
        await wr.create_thread(rig.dm_channel, actor, "title", "body")
    elif where == "edit-in-dm-thread":
        target = (await wr.create_post(rig.dm_thread, actor, "mine")).id if own else rig.dm_post
        await wr.edit_post(target, actor, "edited")
    else:
        raise AssertionError(f"not a write: {where}")


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_without_the_capability_is_refused_at_each_entry(rig: _Rig, entry: str) -> None:
    """W1: each entry refuses a visitor holding every capability but the one it needs, names that capability
    and the entry, and records one refusal."""
    capability, surface = ENTRIES[entry]
    visitor = await _visitor(rig, *(c for c in ALL if c != capability))
    with pytest.raises(VisitorScopeRefused) as refused:
        await _act(rig, entry, visitor, own=False)
    assert (refused.value.did, refused.value.capability, refused.value.reason, refused.value.surface) == (
        visitor, capability, REFUSED_CAPABILITY, surface,
    )
    assert _refusals(rig.events) == [
        {"did": visitor, "capability": capability, "reason": REFUSED_CAPABILITY, "surface": surface},
    ]


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_with_only_that_capability_is_served_at_each_entry(rig: _Rig, entry: str) -> None:
    """W2: holding exactly the capability an entry needs is enough there."""
    capability, _surface = ENTRIES[entry]
    visitor = await _visitor(rig, capability)
    await _act(rig, entry, visitor, own=True)
    assert _refusals(rig.events) == []


@pytest.mark.parametrize(
    ("where", "granted", "needed"),
    [
        ("post-in-ship-thread", CAP_DM_SEND, CAP_WARD_ROOM_POST),
        ("post-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("thread-in-dm-channel", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("edit-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
    ],
    ids=["post-in-ship-thread", "post-in-dm-thread", "thread-in-dm-channel", "edit-in-dm-thread"],
)
async def test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere(
    rig: _Rig, where: str, granted: str, needed: str,
) -> None:
    """W3: the capability a visitor's write needs follows the channel it lands in; holding it serves the write."""
    with pytest.raises(VisitorScopeRefused) as refused:
        await _write(rig, where, await _visitor(rig, granted), own=False)
    assert refused.value.capability == needed
    await _write(rig, where, await _visitor(rig, needed), own=True)


@pytest.mark.parametrize("lapse", ["expired", "deregistered", "registry-off"])
async def test_a_lapsed_or_unattached_session_is_refused_at_its_next_request(rig: _Rig, lapse: str) -> None:
    """W4: an expired session is refused before any sweep, a deregistered one at once, and with no registry a
    visitor is refused; crew post throughout."""
    session = await rig.officers.register("visitor", list(ALL), session_ttl_seconds=10.0)
    expected = {"expired": REFUSED_EXPIRED, "deregistered": REFUSED_NO_SESSION, "registry-off": REFUSED_REGISTRY_OFF}
    if lapse == "expired":
        rig.clock.now += 10.0
    elif lapse == "deregistered":
        rig.officers.deregister(session.did)
    else:
        rig.ward_room.attach_visiting_officers(None)
    with pytest.raises(VisitorScopeRefused) as refused:
        await rig.ward_room.create_post(rig.crew_thread, session.did, "late")
    assert refused.value.reason == expected[lapse]
    await rig.ward_room.create_post(rig.crew_thread, CREW_SLOT, "crew still posts")
    deregistrations = [n for n, _ in rig.events if n == "VISITING_OFFICER_DEREGISTERED"]
    assert len(deregistrations) == (1 if lapse == "deregistered" else 0)


async def test_crew_and_the_captain_are_served_as_before_without_a_lookup(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5 golden: every guarded entry serves a crew slot id and "captain", with the registry attached and not,
    and reads no certificate for them (a lookup raises here)."""
    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: a crew or Captain id was looked up")

    monkeypatch.setattr(rig.identities, "get_by_uuid", _no_lookup)
    wr = rig.ward_room
    for attached in (True, False):
        wr.attach_visiting_officers(rig.officers if attached else None)
        for actor, other in ((CREW_SLOT, "captain"), ("captain", CREW_SLOT)):
            thread = await wr.create_thread(rig.all_hands, actor, "t", "b")
            post = await wr.create_post(thread.id, actor, "p")
            await wr.edit_post(post.id, actor, "edited")
            await wr.endorse(post.id, "post", other, "up")
            await wr.subscribe(actor, rig.all_hands)
            await wr.update_last_seen(actor, rig.all_hands)
            await wr.browse_threads(actor)
            await wr.list_channels(actor)
            await wr.get_unread_counts(actor)
            await wr.get_unread_dms(actor)
            await wr.get_or_create_dm_channel(actor, other)
    assert _refusals(rig.events) == []


async def test_a_crew_did_is_served(rig: _Rig) -> None:
    """W6: a crew member acting by its certificate DID is looked up, found not visiting, and served."""
    crew = await rig.identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )
    thread = await rig.ward_room.create_thread(rig.all_hands, crew.did, "t", "b")
    assert thread.author_id == crew.did
    assert _refusals(rig.events) == []


class _RefusingWardRoom:
    """Raises the real refusal from create_thread; the guard itself is W1-W4's."""

    async def create_thread(self, **_kwargs: Any) -> None:
        raise VisitorScopeRefused(
            "did:probos:ship:visitor", CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "ward_room.create_thread",
        )


def _api_runtime(ward_room: Any) -> Any:
    """The mock runtime BF-771's API test builds (tests/test_bf771_intent_authorization.py:515-534)."""
    runtime = MagicMock()
    runtime.registry = MagicMock()
    runtime.profile_store = None
    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = ""
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.all_callsigns.return_value = {}
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.ward_room = ward_room
    return runtime


def test_the_api_answers_a_visitor_refusal_with_403_and_the_reason() -> None:
    """W7: a refusal from the Ward Room reaches the client as 403 with the capability, reason and surface."""
    client = _TestClient(create_app(_api_runtime(_RefusingWardRoom())), raise_server_exceptions=False)
    response = client.post(
        "/api/wardroom/channels/c1/threads",
        json={"author_id": "did:probos:ship:visitor", "title": "t", "body": "b"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {
        "error": "visitor_scope_refused",
        "capability": CAP_WARD_ROOM_POST,
        "reason": REFUSED_CAPABILITY,
        "surface": "ward_room.create_thread",
    }


async def test_a_real_boot_scopes_visitors_in_the_ward_room(tmp_path: Path) -> None:
    """W8: with AD-701 on, a booted Ward Room refuses a reader's thread for its capability and serves a poster's."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.visiting_officers.enabled = True
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        reader = await runtime.visiting_officers.register("boot-reader", [CAP_WARD_ROOM_READ])
        poster = await runtime.visiting_officers.register("boot-poster", [CAP_WARD_ROOM_POST])
        all_hands = await runtime.ward_room.get_channel_by_name("All Hands")
        with pytest.raises(VisitorScopeRefused) as refused:
            await runtime.ward_room.create_thread(all_hands.id, reader.did, "t", "b")
        assert refused.value.reason == REFUSED_CAPABILITY
        thread = await runtime.ward_room.create_thread(all_hands.id, poster.did, "t", "b")
        assert thread.author_id == poster.did
    finally:
        await runtime.stop()
```

### 7.12 New file: `tests/test_bf903_seam_was_open.py` (M2)

```python
"""BF-903 (#1581): the seam was open. Written against names that exist before BF-903, so on that tree this test
fails for its premise (a visiting officer without ward_room.post opens a thread), not on an import. After BF-903
the Ward Room has no registry attached here, so the visitor is refused with ``visitor_registry_off``."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.identity import AgentIdentityRegistry
from probos.visiting_officers import VisitingOfficerRegistry
from probos.ward_room.service import WardRoomService


async def test_a_visitor_without_ward_room_post_cannot_open_a_thread(tmp_path: Path) -> None:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id="bf903-open-ship", vessel_name="Bf903open", version="1")
        await ward_room.start()
        officers = VisitingOfficerRegistry(
            identities, instance_id="bf903-open-ship", vessel_name="Bf903open", baseline_version="1",
        )
        reader = await officers.register("reader", ["ward_room.read"])
        channel = await ward_room.get_channel_by_name("All Hands")
        before = await ward_room.count_threads(channel.id)
        with pytest.raises(PermissionError):
            await ward_room.create_thread(channel.id, reader.did, "Not allowed", "body")
        assert await ward_room.count_threads(channel.id) == before
    finally:
        await ward_room.stop()
        await identities.stop()
```

## 8. Tracking (tracker pairs, in M2's commit; Amendment A1 updates both for M3)

**`PROGRESS.md`**, anchored on the title, the blank line and the bold lead of BF-904b's line 3:

SEARCH:
```markdown
# ProbOS Progress

**BF-904b (2026-10-22), closes #1585 -- the sealed-core observation can fire, a syntax error a repair fixed no longer blocks the commit, a build in review holds its files, and the visiting builder works from whole files.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-903 (2026-10-22), #1581, M1 and M2 of three -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.** AD-701 called its registry the enforcement seam, but nothing called `has_capability`. M1: `probos.visiting_officers` owns the four names AD-701 and AD-802 declared (`ward_room.post`, `ward_room.read`, `dm.send`, `dm.receive`); `register`, the pairing service, `probos pairing approve` and `visiting_officers.default_capabilities` refuse any other name before a certificate, a pending row or a consumed code. The registry gains `refusal` and `check`, which read expiry at use (`get` hides an expired session), and the module gains the one guard every path calls, `require_visitor_capability`: it recognises a visiting officer by its birth certificate's agent type and never looks up a crew member's, the Captain's or the system's id. M2: the Ward Room facade calls it at the eleven entries that act for an actor id (a write needs `dm.send` in a DM channel and `ward_room.post` elsewhere); finalize attaches the registry; the API answers a refusal with 403 and the reason. A refusal is a `VISITING_OFFICER_REFUSED` event through the registry's emitter and a warning. Both flags stay off. M3 (the channel adapters and the inbound MCP server) follows in the same PR. New: `tests/test_bf903_visitor_scope.py`, `tests/test_bf903_ward_room_scope.py`, `tests/test_bf903_seam_was_open.py`. Updated: `test_ad701_visiting_officers.py`, `test_ad802_pairing.py`. The contract is `prompts/bf-903-visitor-capability-seam.md`.

**BF-904b (2026-10-22), closes #1585 -- the sealed-core observation can fire, a syntax error a repair fixed no longer blocks the commit, a build in review holds its files, and the visiting builder works from whole files.**
```

**`DECISIONS.md`**, after BF-904b's entry, anchored on its *Reversal* bullet (line 559, unique), the blank line and the heading that follows:

SEARCH:
```markdown
- *Reversal.* Revert the three BF-904b commits. Nothing persisted changes; the observation stops firing, refusals and syntax share one list again, a build in review stops holding its files and the visiting builder is seeded with excerpts again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the three BF-904b commits. Nothing persisted changes; the observation stops firing, refusals and syntax share one list again, a build in review stops holding its files and the visiting builder is seeded with excerpts again.

### BF-903 -- Visiting-officer capabilities are checked where the officer acts, and the names have one owner (2026-10-22, #1581)

- *Scope.* M1 and M2 of three, one gate and one PR; M3 (the channel adapters and the inbound MCP server) is Amendment A1. `visiting_officers.py`, `config_models/crew.py`, `security/pairing/service.py`, `__main__.py` (M1); `ward_room/service.py`, `startup/finalize.py`, `api.py` (M2); tests. Contract: `prompts/bf-903-visitor-capability-seam.md`.
- *D1 (premise).* No path carries a visitor's own identity into the Ward Room today: `runtime.pairing_service` is never assigned, so `paired_did` is never set, and nothing reads it; the MCP server dispatches as the handling agent. The HXI routes take actor ids from the request body, so a body naming a visiting DID reached the Ward Room unchecked.
- *D2 (where).* One guard, `require_visitor_capability`, in the registry's module, applied at every Ward Room facade entry that takes an actor id and, in M3, at the channel and MCP entries. A visitor is a did:probos agent DID whose certificate's agent type is `visiting`, read from the identity registry's cache; the certificate outlives the session. Crew ids return before any lookup or query. BF-907's resolver and AD-1346's `IdentityService` return None for a slotless visitor and cannot classify one. Rejected: guarding only the channel layer, recognising a visitor by registry membership (fails open at expiry), and by DID shape (real visiting DIDs have the crew shape).
- *D3 (names).* A closed set in code, chosen among by configuration and `--cap`. AD-701's "new caps via configuration" is narrowed: a capability without a checking path grants nothing, and that path is code.
- *D4 (MCP, built in M3).* A tools/call whose arguments name a visiting DID is refused with a reason; the shared token stays BF-875's federation-peer credential. A per-visitor binding is AD-1342's, on the MCP authorization spec.
- *D5 (record).* `VISITING_OFFICER_REFUSED` through the registry's emitter and a warning (with the registry off, the warning alone); reason codes in AD-1316's syntax. No `EventType` member and no admission record (#1604 owns admission).
- *D7 (M3, coupled).* `_check_pairing` fails closed when the pairing store cannot be read. A paired sender's slash commands and natural language are refused: no declared capability grants them. The AD that wires pairing declares what a paired sender may do.
- *Disclosed effects.* An undeclared capability is refused at `register`, pairing, `probos pairing approve` and config parse; a `system.yaml` naming one no longer loads; a pending row minted before BF-903 with one is consumed and refused at approve. `get` hides an expired session. A visiting DID at a guarded entry is refused unless a live session holds the capability (always, with no registry attached); the API answers 403. Crew, Captain and system ids are unchanged.
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors and any capability string is accepted again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. Both outputs go in M2's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after M3's code commit:** add a *Validation of record* bullet in BF-903's entry, before its *Reversal* line: the mutation campaign of record (base tree, the sha256 of each file in section 10 and of the new test files, and each row's first failing test). Add a matching closing section to this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row (`BF-903` count is 0; BF-904b added none).

## 9. What this does NOT change

- Both flags in `config/system.yaml`. AD-1342 and the visitor-to-crew path.
- AD-802's pairing flow apart from the name checks: `resolve_did`, `revoke_pairing` and `restore_active_sessions` (register R1).
- The channel adapters and `federation/mcp_server.py` (M3). The A2A server (register R4).
- These Ward Room entries: `create_channel`, `unsubscribe`, `update_thread`, the reads with no actor id (`get_thread`, `list_threads`, `get_post`, `get_recent_activity`, `get_posts_by_author`), and the subject-id queries (`get_credibility`, `get_agent_comm_stats`, `count_posts_by_author`, `dm_receipt_facts`).
- `admission/`, `identity_service.py`, `identity.py` and `EventType`.
- The routers' acceptance of body-supplied actor ids (register R6).

## 10. Mutation rows

There are 51 rows, as whole stripped lines, each occurring once in its file after section 7.

Tier HIGH: every changed production file has rows.
- Run A1-A27 against `tests/test_bf903_visitor_scope.py`, and B1-B23 against `tests/test_bf903_ward_room_scope.py`.
- Start each group with an unmutated run of its file that passes.
- Restore the file after each row.
- "First failing" is in file order. Where another test fails first, run the named test alone against the mutant.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| A1 | `src/probos/visiting_officers.py` | `VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE})` | `VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND})` | V1 |
| A2 | `src/probos/visiting_officers.py` | `unknown = [c for c in dict.fromkeys(capabilities) if c not in VISITOR_CAPABILITIES]` | `unknown = []` | V2 `[typo]` |
| A3 | `src/probos/visiting_officers.py` | `raise UnknownCapabilityError(unknown)` | `pass` | V2 `[typo]` |
| A4 | `src/probos/visiting_officers.py` | `require_known_capabilities(capabilities)  # BF-903 (#1581): refused before a certificate is issued` | `pass` | V2 `[typo]` |
| A5 | `src/probos/visiting_officers.py` | `if session is None or self._clock() >= session.expires_at:  # BF-903: an expired session is gone at use` | `if session is None:` | V6 (`get` after expiry) |
| A6 | `src/probos/visiting_officers.py` | `return REFUSED_NO_SESSION` | `return None` | V6 (deregistered) |
| A7 | `src/probos/visiting_officers.py` | `if self._clock() >= session.expires_at:` | `if False:` | V6 (`has_capability` after expiry) |
| A8 | `src/probos/visiting_officers.py` | `return REFUSED_EXPIRED` | `return None` | V6 |
| A9 | `src/probos/visiting_officers.py` | `if capability not in session.capabilities:` | `if False:` | V6 (missing) |
| A10 | `src/probos/visiting_officers.py` | `return self.refusal(did, capability) is None` | `return True` | V6 |
| A11 | `src/probos/visiting_officers.py` | `"did": did, "capability": capability, "reason": reason, "surface": surface,` | `"did": did,` | V6 (event equality) |
| A12 | `src/probos/visiting_officers.py` | `raise VisitorScopeRefused(did, capability, reason, surface)` | `return` | V6 |
| A13 | `src/probos/visiting_officers.py` | `if parsed is None or parsed.get("type") != "agent":` | `if parsed is None:` | V7 (the ship DID raises `KeyError`) |
| A14 | `src/probos/visiting_officers.py` | `return cert is not None and cert.agent_type == VISITING_AGENT_TYPE` | `return cert is not None` | V7 (crew DID) |
| A15 | `src/probos/visiting_officers.py` | `if capability not in VISITOR_CAPABILITIES:` | `if False:` | V8 (undeclared) |
| A16 | `src/probos/visiting_officers.py` | `if not is_visiting_identity(identity_registry, actor_id):` | `if False:` | V8 (crew refused with no registry) |
| A17 | `src/probos/visiting_officers.py` | `if visiting_officers is None:` | `if False:` | V8 (registry off) |
| A18 | `src/probos/visiting_officers.py` | `raise VisitorScopeRefused(actor_id, capability, REFUSED_REGISTRY_OFF, surface)` | `return` | V8 |
| A19 | `src/probos/visiting_officers.py` | `visiting_officers.check(actor_id, capability, surface=surface)` | `pass` | V8 (missing) |
| A20 | `src/probos/config_models/crew.py` | `return [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]` | `return [CAP_WARD_ROOM_POST]` | V1 |
| A21 | `src/probos/config_models/crew.py` | `require_known_capabilities(value)` | `pass` | V3 |
| A22 | `src/probos/security/pairing/service.py` | `DEFAULT_CAPABILITIES = (CAP_DM_SEND, CAP_DM_RECEIVE)  # BF-903: AD-802's defaults, named by the vocabulary's owner` | `DEFAULT_CAPABILITIES = (CAP_DM_SEND,)` | V1 |
| A23 | `src/probos/security/pairing/service.py` | `require_known_capabilities(caps)  # BF-903: refused before a pending row is minted` | `pass` | V4 |
| A24 | `src/probos/security/pairing/service.py` | `require_known_capabilities(capabilities_override)  # BF-903: refused before the code is consumed` | `pass` | V4 (the code-survives assertion) |
| A25 | `src/probos/security/pairing/service.py` | `require_known_capabilities(caps)  # BF-903: a row minted before BF-903 may hold any string` | `pass` | V5 `[row-minted-before-bf903]`. The real registry refuses in V4 regardless, so only the offline stub kills it. |
| A26 | `src/probos/__main__.py` | `except (UnknownPairingCode, UnknownCapabilityError) as exc:  # BF-903: an undeclared --cap is refused with its name` | `except UnknownPairingCode as exc:` | V5 `[undeclared-cap-flag]` |
| A27 | `src/probos/visiting_officers.py` | `if type(actor_id) is not str or not actor_id.startswith("did:") or identity_registry is None:` | `if type(actor_id) is not str or not actor_id.startswith("did:"):` | V7 (`None` registry raises `AttributeError`) |
| B1 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ?"` | `_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ? AND 0"` | W3 `[thread-in-dm-channel]` |
| B2 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ?"` | `_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ? AND 0"` | W3 `[post-in-dm-thread]` |
| B3 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ?"` | `_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ? AND 0"` | W3 `[edit-in-dm-thread]` |
| B4 | `src/probos/ward_room/service.py` | `self._visiting_officers = registry` | `self._visiting_officers = None` | W1 `[create_thread]` (reason is registry off) |
| B5 | `src/probos/ward_room/service.py` | `surface=f"ward_room.{entry}",` | `surface=entry,` | W1 `[create_thread]` |
| B6 | `src/probos/ward_room/service.py` | `visiting_officers=self._visiting_officers,` | `visiting_officers=None,` | W1 `[create_thread]` |
| B7 | `src/probos/ward_room/service.py` | `channel_type = row[0] if row else ""` | `channel_type = ""` | W3 `[post-in-dm-thread]` |
| B8 | `src/probos/ward_room/service.py` | `capability = CAP_DM_SEND if channel_type == "dm" else CAP_WARD_ROOM_POST` | `capability = CAP_WARD_ROOM_POST` | W3 `[post-in-dm-thread]` |
| B9 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id or "", CAP_WARD_ROOM_READ, "list_channels")  # BF-903` | `pass` | W1 `[list_channels]` |
| B10 | `src/probos/ward_room/service.py` | `for participant in (agent_a_id, agent_b_id):  # BF-903: a visiting officer in a DM must be able to receive it` | `for participant in (agent_a_id,):` | W1 `[dm_channel_as_b]` |
| B11 | `src/probos/ward_room/service.py` | `self._require_visitor(participant, CAP_DM_RECEIVE, "get_or_create_dm_channel")` | `pass` | W1 `[dm_channel_as_a]` |
| B12 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "browse_threads")  # BF-903` | `pass` | W1 `[browse_threads]` |
| B13 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "create_thread", _CHANNEL_TYPE_OF_CHANNEL, channel_id)  # BF-903` | `pass` | W1 `[create_thread]` |
| B14 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "create_post", _CHANNEL_TYPE_OF_THREAD, thread_id)  # BF-903` | `pass` | W1 `[create_post]` |
| B15 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "edit_post", _CHANNEL_TYPE_OF_POST, post_id)  # BF-903` | `pass` | W1 `[edit_post]` (raises the author `ValueError` instead) |
| B16 | `src/probos/ward_room/service.py` | `self._require_visitor(voter_id, CAP_WARD_ROOM_POST, "endorse")  # BF-903` | `pass` | W1 `[endorse]` |
| B17 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "subscribe")  # BF-903` | `pass` | W1 `[subscribe]` |
| B18 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "update_last_seen")  # BF-903` | `pass` | W1 `[update_last_seen]` |
| B19 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "get_unread_counts")  # BF-903` | `pass` | W1 `[get_unread_counts]` |
| B20 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_DM_RECEIVE, "get_unread_dms")  # BF-903` | `pass` | W1 `[get_unread_dms]` |
| B21 | `src/probos/startup/finalize.py` | `runtime.ward_room.attach_visiting_officers(runtime.visiting_officers)` | `pass` | W8 (reason is registry off) |
| B22 | `src/probos/api.py` | `@app.exception_handler(VisitorScopeRefused)` | `@app.exception_handler(LookupError)` | W7 (500) |
| B23 | `src/probos/api.py` | `"error": "visitor_scope_refused",` | `"error": "intent_denied",` | W7 |

**Lines without a row**
- `_require_visitor_write`'s `if not is_visiting_identity(...)`: equivalent, since removing it only adds a query for crew.
- `identity_registry=self._identity_registry,`: not unique in `service.py`; `start()` has two.
- `if self._db is not None:`: only the in-memory mode has no database.
- The `startswith("did:")` half of A27's line: `parse_did` refuses the same keys.
- `if unknown:`: equivalent to A3.
- `if runtime.ward_room is not None:`: equivalent to B21.
- `status_code=403,`: not unique in `api.py`.
- Log lines and docstrings.

## 11. Verified Against Codebase (2026-10-22, HEAD `0e122174`)

**How uniqueness was checked.** Each SEARCH's distinctive line was grepped without a `$` anchor and counted once, or read in a whole-file or whole-region read: `visiting_officers.py` (whole), `pairing/service.py` (whole), `test_ad701` (whole), `ward_room/service.py:1-454`, `__main__.py:1895-2030`, `finalize.py:4915-4974`, `api.py:120-190`, `crew.py:295-330`, `test_ad802:1-214`.

```
src/probos/visiting_officers.py   17-18 docstring | 31 from typing import Any, Callable | 37 VISITING_AGENT_TYPE
  55-64 class docstring | 105 async def register | 118-119 ttl check | 120 issue_birth_certificate
  140 / 154 / 191 _emit("VISITING_OFFICER_*") | 151 deregister pops | 162-163 get | 165-171 has_capability
  173-175 active | 197-205 _emit and its warning
src/probos/config_models/crew.py  10 field_validator import | 303 class VisitingOfficersConfig | 316-318 default_capabilities
src/probos/config.py              152 VisitingOfficersConfig re-export | 3916 visiting_officers field
src/probos/security/pairing/service.py  15-16 UnknownPairingCode,) | 27 DEFAULT_CAPABILITIES | 101-102 caps/code
  153-155 consume_pending | 162-165 caps | 171 register | 238-267 restore (re-mints a DID) | 269-283 resolve_did
src/probos/security/pairing/store.py    76-85 __init__(db_path, *, clock) | 101-109 mint_pending | 159 get_pending | 179 list_pending
src/probos/__main__.py            1908-1912 pairing import | 1952-1956 offline stub | 1974-1975 except | 2022 stub DID shape
src/probos/identity.py            92-100 generate_did | 120-149 parse_did | 773 get_by_uuid | 804-827 resolve_slot_id
  893-937 issue_birth_certificate (new uuid each call) | 587 cache load at start | 1004 resolve_or_issue
src/probos/identity_service.py    79-95 resolve -> None without a slot
src/probos/ward_room/service.py   14-15 imports | 27 logger | 30 class | 41 identity_registry | 60 _receipt_facts
  238-240 set_ontology | 246-247 list_channels | 258-262 dm channel | 340-345 browse | 362-368 create_thread
  405-409 create_post | 414-415 edit_post | 417-420 endorse | 425-426 subscribe | 431-432 update_last_seen
  434-435 get_unread_counts | 445-446 get_unread_dms
src/probos/ward_room/models.py    95-104 channels(id, channel_type) | 106-123 threads(id, channel_id) | 125-129 posts(id, thread_id)
src/probos/ward_room/messages.py  487 "Only the original author can edit" | 532-533 self-endorse | 561 "up"
src/probos/ward_room/channels.py  28 dm_channel_name 8-char prefix | 224-261 get_or_create_dm_channel
src/probos/startup/communication.py 465-471 WardRoomService(..., identity_registry=identity_registry)
src/probos/startup/finalize.py    4926-4970 AD-701 wiring; 4963 start(); vo_cfg reads 4930, 4960-4967
src/probos/runtime.py             1063 self.ward_room | 1974 emit_event(event: BaseEvent | str | EventType, ...)
src/probos/api.py                 22 IntentAuthorizationDenied import | 23 verify_ws_token | 165-181 BF-771 handler | 183 CORS
src/probos/routers/wardroom.py    20 prefix /api/wardroom | 276-290 create_thread (except ValueError) | 351-358 | 366-372 | 380-386 | 396
src/probos/api_models.py          211-217 CreateThreadRequest
src/probos/channels/base.py       37 paired_did | 159-175 _check_pairing (fail-open 164-170) | 238-269 handle_message
src/probos/federation/mcp_server.py 196-207 bearer check | 331 authenticated | 425-429 peer id | 435-455 app tools | 457-479 intents
src/probos/config_models/integrations.py 34-41 exposed_intents default []
src/probos/execution/authority.py 109 _REASON_CODE_RE | src/probos/admission/taxonomy.py 66-73 DEFERRED_CHECKS
src/probos/mesh/pre_intent_auth.py 65 IntentAuthorizationDenied(PermissionError)
config/system.yaml                297 mcp enabled: false | 933 visiting enabled: false | 936-938 default caps
pyproject.toml                    181 asyncio_mode = "auto"
tests/test_bf771_intent_authorization.py 515-538 mock-runtime create_app pattern
tests/test_ad1346_admission_service.py   92-100 identity registry fixture; 131-137 resolve_or_issue
tests/test_ad630_leadership_feedback.py  302/321/339 __new__ services call only get_agent_comm_stats (unguarded)
```

## Absence Verified (2026-10-22)

```
AV1 CLAIM: no production caller of has_capability
    RUN:   rg -n 'has_capability\(' src
    FOUND: visiting_officers.py:10, :59, :63 (docstrings), :165 (def); federation/router.py:70, :91 (peer_has_capability)
    HOLDS: yes
AV2 CLAIM: runtime.pairing_service is never assigned
    RUN:   rg -n 'pairing_service' src
    FOUND: channels/base.py:131,134,159,160,163,178; discord_adapter.py:61; slack_adapter.py:49; __main__.py:1904
    HOLDS: yes (reads and comments only)
AV3 CLAIM: nothing reads paired_did
    RUN:   rg -n 'paired_did' src/probos
    FOUND: base.py:32,37 (field), :135 (docstring), :173 (write)
    HOLDS: yes
AV4 CLAIM: restore_active_sessions has no production caller
    RUN:   rg -n 'restore_active_sessions\(' src
    FOUND: security/pairing/service.py:238 (def)
    HOLDS: yes
AV5 CLAIM: VisitingOfficersConfig.default_capabilities is read by nothing
    RUN:   rg -n 'vo_cfg\.' src ; rg -n 'default_capabilities' src
    FOUND: finalize.py:4930,4960,4961,4966,4967 (enabled, ttl, sweep); crew.py:316 is the only visitor one
    HOLDS: yes
AV6 CLAIM: no BF-903 symbol or test file exists yet
    RUN:   rg -l 'VisitorScopeRefused|is_visiting_identity|require_visitor_capability|VISITOR_CAPABILITIES|attach_visiting_officers|UnknownCapabilityError|require_known_capabilities|CAP_WARD_ROOM|VISITING_OFFICER_REFUSED' ; glob tests/test_bf903*
    FOUND: none ; none
    HOLDS: yes
AV7 CLAIM: no visitor consumer in the Ward Room or the routers
    RUN:   rg -i 'visiting|visitor' src/probos/ward_room ; rg -i 'visiting_officer|visitor' src/probos/routers
    FOUND: 0 ; 0
    HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- **Precheck** (`scripts/phantom-api-precheck.ps1`):
  - `TestClient` and `Namespace` are imported under a leading underscore.
  - `JSONResponse` exists (`api.py:166`, `-> JSONResponse:`).
  - `MagicMock` and `Path` are stdlib-listed.
  - The new classes are defined in this contract.
  - Each `AssertionError(` message begins with "not".
  - The `runtime.X` names used (`ward_room`, `visiting_officers`, `identity_registry`, `start`, `stop`, `callsign_registry`, `registry`, `hebbian_router`, `ontology`) exist in `src`.
  - The SQL uses one-letter aliases only.
- **Import cycle:** `visiting_officers.py` imports only the standard library at load. `parse_did` and the config's imports run at call time.
- **CRLF:** match the working copy's line endings; never anchor a grep with `$`.
- **The deletion check** before each commit: `git diff --cached --stat`.

## 13. Not verified here, and prior art

- **Not run:** any test, the precheck or ruff.
- **Not confirmed:**
  - that Rich's 80-column wrap keeps `tool.use` intact in V5's output (it wraps at spaces);
  - that the BF-771 mock runtime serves `/api/wardroom` (the same app);
  - that W8's boot posts as a visitor without side effects beyond Ward Room routing to crew (proactive is off).
- **Prior art:**
  - **Adopted:** the MCP authorization spec (2026-07-28 revision: an MCP server is an OAuth 2.1 resource server with audience-bound tokens; Client ID Metadata Documents replace Dynamic Client Registration). This is the design AD-1342's binding should take; D4 defers it there instead of a bespoke per-visitor token.
  - **Absorbed:** BF-771's `PermissionError`-plus-app-handler pattern for policy refusals (`api.py:147-181`).
  - **Reference projects** (date used 2026-10-22): MCP Apps was overdue (2026-04-08, interval 180 days). Checked: it is now an official extension in the 2026-07-28 spec, with nothing for BF-903. Update the row to `2026-10-22 | checked | BF-903 (#1581) Prior Art`. AG-UI (never reviewed) was considered and deferred: it is a UI protocol and not relevant.
  - **Blind spots folded in:** the restore path's DID mismatch, the DM-name collision and the A2A inbound door (register).

## 14. Diff Reviewer: properties to verify

1. A crew, Captain or system id causes no certificate lookup and no database query at any guarded entry.
2. Each of the eleven facade methods calls the guard before it delegates, with the capability in ENTRIES.
3. A visiting DID is refused when the registry is unattached, the session is missing, the session has expired (`clock >= expires_at`) or the capability is absent, each with the matching code.
4. `VisitorScopeRefused` is not a `ValueError`, so the routers' `except ValueError` cannot turn it into a 400; the app handler returns 403.
5. `register`, `request_pairing`, an approve override and config parse refuse an undeclared name before any certificate, row or consume.
6. `visiting_officers.py` imports no ProbOS module at load.
7. `config/system.yaml` is unchanged; no `EventType` is added; `admission/` is untouched.
8. `has_capability` keeps its truth table (`test_ad701:180-193`).

## 15. Acceptance criteria

- Sections 7.1-7.12 are applied, all of sections 6 and 10 pass and are killed, and the focused gates in section 4 are green.
- The tracker pairs and the ledger are regenerated and pass `--check`.
- One broad gate after M3, with a receipt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. M3, to follow as Amendment A1 (decided; contract on request)

**Files**
- `channels/base.py`:
  - In `handle_message`, once `paired_did` is set, refuse slash commands and natural language with a reply naming the reason.
  - An `@callsign` DM needs `dm.send`, checked directly with `runtime.visiting_officers.check(paired_did, CAP_DM_SEND, surface=...)`, because pairing alone identifies the sender as a visitor. With no registry, the DM is refused.
  - A `resolve_did` failure raises a `PairingNotificationError` subclass.
- `federation/mcp_server.py`: before either dispatch branch, refuse a `tools/call` whose arguments, walked iteratively, contain a string that `is_visiting_identity(runtime.identity_registry, ...)` accepts. The refusal emits `_emit_failed(..., reason="visitor_unbound")`.

**Tests** in `tests/test_bf903_channel_and_mcp.py`, on real objects: a real `ChannelAdapter` subclass, a real `PairingService` and `PairingRegistry`, the registries, and `build_mcp_app` driven through its JSON-RPC endpoint.

**Pinned tests to update with reasons:** `test_channel_base.py`, `test_bf804_pairing_notification.py`, `test_ad803a_telegram.py`, `test_ad804_slack.py`, `test_ad806_matrix.py` and `test_ad807_discord_refresh.py`, wherever a paired fake proceeds to natural language or the fail-open branch.

**Trackers:** A1 extends the PROGRESS line and the DECISIONS entry, and closes #1581.
