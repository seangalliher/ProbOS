# AD-802 — DM Pairing + Visiting Officer Trust Integration (Substrate v1)

**Issue:** [#726](https://github.com/seangalliher/ProbOS/issues/726)
**Wave:** 189
**Author:** Architect (sole-author small-AD fast path; Wave 187/188 precedent)
**Estimated tests added:** ~12

## Scope (substrate-only v1)

Hard prerequisite for channel adapters AD-803..807. **No channel adapter integration in this AD** — that hook lands in AD-802a alongside the first adapter consumer (AD-803 Telegram). v1 ships:

1. **Persistent pairing registry** (SQLite) — the layer the AD-701 in-memory `VisitingOfficerRegistry` explicitly defers (per `visiting_officers.py:19` *"Persistence is a follow-up AD-701b"*).
2. **Pairing service** — mint code → store → approve → mint VO session → revoke.
3. **CLI verb** — `probos pairing` with subcommands `pending | list | approve | revoke`.
4. **EventLog integration** — three new `EventType` values.
5. **Runtime startup wiring** — on boot, re-register active pairings as VO sessions until their TTL expires.

## File layout

- `src/probos/security/pairing/__init__.py` — re-exports `PairingRegistry`, `PairingService`, types.
- `src/probos/security/pairing/store.py` — `PairingRegistry` SQLite store. Schema:
  - `pending_pairings(channel TEXT, raw_id TEXT, code TEXT PRIMARY KEY, capabilities TEXT, ttl_seconds REAL, minted_at REAL, expires_at REAL)`
  - `paired_users(channel TEXT, raw_id TEXT, did TEXT PRIMARY KEY, capabilities TEXT, ttl_seconds REAL, paired_at REAL, expires_at REAL)`
  - UNIQUE (channel, raw_id) on `paired_users` (one DID per sender per channel).
- `src/probos/security/pairing/service.py` — `PairingService` — coordinates the registry + `VisitingOfficerRegistry` + event emission.
- `src/probos/security/pairing/types.py` — `PendingPairing`, `PairedUser`, `PairingError` exception hierarchy.
- `src/probos/events.py` — add three EventType values (next index after AD-456b's `SANDBOX_*` block).

## Public surface

### `PairingRegistry` (SQLite store; sync; idempotent)

```python
class PairingRegistry:
    def __init__(self, db_path: Path, *, clock: Callable[[], float] = time.time): ...
    def mint_pending(self, channel: str, raw_id: str, capabilities: list[str], ttl_seconds: float = 86400.0) -> PendingPairing: ...
    def get_pending(self, channel: str, code: str) -> PendingPairing | None: ...
    def list_pending(self, channel: str | None = None) -> list[PendingPairing]: ...
    def consume_pending(self, channel: str, code: str) -> PendingPairing | None: ...  # delete + return
    def record_pairing(self, channel: str, raw_id: str, did: str, capabilities: list[str], ttl_seconds: float) -> PairedUser: ...
    def lookup_by_raw_id(self, channel: str, raw_id: str) -> PairedUser | None: ...
    def lookup_by_did(self, did: str) -> PairedUser | None: ...
    def list_paired(self, channel: str | None = None) -> list[PairedUser]: ...
    def revoke(self, did: str) -> bool: ...
    def sweep_expired_pending(self) -> int: ...  # garbage collect; called by service on startup + periodically
    def all_active_paired(self) -> list[PairedUser]: ...  # for VO re-registration on boot
```

### `PairingService` (orchestrator; async)

```python
class PairingService:
    def __init__(
        self,
        registry: PairingRegistry,
        visiting_officers: VisitingOfficerRegistry,
        *,
        emit_event: Callable[[str, dict], None] | None = None,
        code_alphabet: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",  # ambiguous chars removed
        code_length: int = 6,
        default_pending_ttl_s: float = 86400.0,
        default_session_ttl_s: float = 604800.0,  # 7d for paired users (vs 1h VO default)
    ): ...

    async def request_pairing(self, channel: str, raw_id: str, capabilities: list[str] | None = None) -> str: ...
        # Returns the 6-char code; emits PAIRING_REQUESTED; idempotent if pending already exists for (channel, raw_id).

    async def approve_pairing(self, channel: str, code: str, *, capabilities_override: list[str] | None = None, session_ttl_seconds: float | None = None) -> PairedUser: ...
        # Consumes pending → registers VO session → records paired_user → emits PAIRING_APPROVED.

    async def revoke_pairing(self, did: str, *, reason: str = "explicit") -> bool: ...
        # Deregisters VO session + deletes paired_user row + emits PAIRING_REVOKED.

    async def restore_active_sessions(self) -> int: ...
        # On runtime boot: walk paired_users, re-register each as a VO session with remaining TTL.
        # Skip rows whose expires_at < now (cleaned up).

    def resolve_did(self, channel: str, raw_id: str) -> str | None: ...
        # Fast-path lookup for the channel adapter hook (AD-802a): given an inbound message,
        # find the paired DID. None means the sender is unknown and must be paired first.
```

### Default capability set

For now: `["dm.send", "dm.receive"]`. Operator-override on `approve` via `--cap ward_room.post,tool.use` (parsed by CLI, passed to `capabilities_override`).

## CLI verb

`probos pairing` subcommand registered in `__main__.py`. Subcommands:

- `probos pairing pending [--channel CHANNEL]` — list pending pairings (code, channel, raw_id, age, expires_in).
- `probos pairing list [--channel CHANNEL]` — list active paired users.
- `probos pairing approve <channel> <code> [--cap CAP1,CAP2] [--ttl-days N]` — approve a pending pairing.
- `probos pairing revoke <did>` — revoke an active pairing.

Output uses the existing `Console()` + Rich tables pattern (see `_cmd_doctor` for reference).

## EventLog additions

In `src/probos/events.py` after the `SANDBOX_*` block:

```python
    # AD-802: DM pairing for channel-adapter inbound from unknown senders.
    PAIRING_REQUESTED = "pairing_requested"
    PAIRING_APPROVED = "pairing_approved"
    PAIRING_REVOKED = "pairing_revoked"
```

## Runtime wiring

In `src/probos/startup/finalize.py` (after `vo_registry` is created and before runtime returns):

```python
from probos.security.pairing import PairingRegistry, PairingService
pairing_db = data_dir / "pairings.db"
pairing_registry = PairingRegistry(pairing_db)
pairing_service = PairingService(
    registry=pairing_registry,
    visiting_officers=vo_registry,
    emit_event=runtime._emit_event,  # existing AD-701 wiring shape
)
restored = await pairing_service.restore_active_sessions()
if restored:
    logger.info("AD-802: restored %d paired users as VO sessions", restored)
runtime.pairing_service = pairing_service
runtime.pairing_registry = pairing_registry
```

Wiring is opt-in via `config.security.pairing_enabled` (default `True`).

## Add to PairingService doctor check

Register a `pairing_check` in the AD-801 doctor that reports `len(registry.list_paired())` active pairings. Trivial — single new file `src/probos/doctor/checks/pairing_check.py`.

## Test plan (`tests/test_ad802_pairing.py`)

12 tests, all `-n 0`-safe:

1. `PairingRegistry.mint_pending` creates a row with a 6-char code from the unambiguous alphabet (no I/O/0/1).
2. `mint_pending` is idempotent on `(channel, raw_id)` — returns the same code for the same pending request.
3. `consume_pending` deletes + returns; second call returns None.
4. `sweep_expired_pending` removes rows past expiry; returns count removed.
5. `PairingService.request_pairing` emits `PAIRING_REQUESTED`.
6. `approve_pairing` consumes the pending row, calls `vo_registry.register(...)`, persists a `paired_users` row, emits `PAIRING_APPROVED`. (Fake VO registry.)
7. `approve_pairing` raises `PairingError` on unknown code.
8. `revoke_pairing` deregisters the VO session, deletes the row, emits `PAIRING_REVOKED`.
9. `restore_active_sessions` re-registers all active paired users on simulated boot; skips rows whose `expires_at < now`.
10. `resolve_did(channel, raw_id)` returns the DID for paired senders, None for unknown.
11. `capabilities_override` on approve uses the override, not the originally-requested cap set.
12. `pairing_check` (doctor) returns OK with count line when registry is populated; OK with "no active pairings" when empty.

## Acceptance

- `python -m probos pairing pending` on a fresh install lists 0 rows.
- Mint a pending pairing programmatically → `probos pairing pending` lists it → `probos pairing approve <channel> <code>` returns OK with the new DID → `probos pairing list` shows the paired user → `probos pairing revoke <did>` returns OK.
- Restart the runtime → `restore_active_sessions` re-registers the VO session for any active pairing (verified via fake VO + log inspection in the smoke test).
- AD-801 `probos doctor` includes the new `pairing` check.
- +12 new pytest in `tests/test_ad802_pairing.py`; total runtime <2s.
- Full pytest gate stays non-decreasing.

## Out of scope (forward markers)

- **AD-802a** — ChannelAdapter base-class pre-dispatch hook (`adapter.handle_inbound()` → `service.resolve_did(...)` → mint+reply if unpaired). Ships with AD-803 Telegram adapter, the first consumer.
- **AD-802b** — HXI decision-queue card surfacing pending pairings with Approve/Deny buttons. UI scope.
- **AD-802c** — `--anon-mode` per-channel config flag for public bots that bypass pairing (with `you sure?` warning). Add when a real use case demands it.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
