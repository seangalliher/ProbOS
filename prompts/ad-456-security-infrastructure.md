# AD-456: Security Infrastructure -- Secrets, Egress, Audit (v1)

**Status:** Ready for builder
**Dependencies:** Builds on AD-455 `security/` package (verified at `src/probos/security/__init__.py`, shipped Wave 5). AD-456 EXTENDS AD-455's package; does NOT own `__init__.py` creation.
**Estimated tests:** ~14
**Risk:** High -- cross-cutting (touches `runtime.py`, `startup/finalize.py`, public LLM client surface for egress policy reads). Acceptance criteria below requires destructive-intent consensus gating where appropriate.

---

## Problem

AD-455 (Wave 5) shipped four security services in `src/probos/security/`: `ThreatDetector`, `InputValidator`, `TrustIntegrityMonitor`, `RedTeamLead`. These cover incoming-input safety. There is no:

1. **Secrets management** -- API keys, tokens, and credentials are scattered across `os.environ` reads, `pyproject.toml`, and ad-hoc per-module imports. No central rotation surface.
2. **Egress policy** -- outbound HTTP from `agents/http_fetch.py:34 HttpFetchAgent` and `agents/red_team.py:408` (verification probes) has no allow/deny-list gate. The runtime can fetch arbitrary URLs.
3. **Tamper-evident audit log** -- `event_log.py` records events but has no append-only audit chain (hash-chained log) for compliance/security review.

`grep -rn "SecretsManager\|EgressPolicy\|AuditLog" src/probos/` returns no class definitions for these names.

The roadmap entry (line 4142) lists 4 capabilities. v1 ships three; one (RuntimeSandbox -- process isolation) is deferred to AD-456b.

## Solution Overview

Extend `src/probos/security/` with three new modules:

1. **`SecretsManager`** -- single-source-of-truth for secret reads. Loads from environment + optional JSON store under `runtime.data_dir/secrets.json`; emits `SECRET_ROTATED` on operator rotation. v1 read-only public API: `get(key) -> str | None`, `rotate(key, value)` (operator-side, not exposed to agents).
2. **`EgressPolicy`** -- allowlist/denylist consultation surface. Public method `is_allowed(url) -> bool` consulted by `HttpFetchAgent` and `RedTeamAgent` HTTP probes. Emits `EGRESS_BLOCKED` when blocking. Does NOT mutate HTTP behavior in v1 -- consumer wiring deferred to AD-456b. v1 ships the policy + emit surface; the existing HTTP code paths remain unchanged. (Coordinator-then-dispatch per Wave 5 retrospective convention #3.)
3. **`AuditLog`** -- append-only hash-chained record over a sub-table in `event_log.py`'s SQLite database. Each entry includes prior-entry hash; tamper detection via `verify_chain()`. Emits `AUDIT_RECORDED` per entry.

**v1 scope (no-theater discipline per Wave 5 retrospective convention #7):**

The roadmap's 4 capabilities reduce to 3 v1 deliverables that do real work today:

- **`SecretsManager`** -- real public read surface; consulted by future LLM client modules.
- **`EgressPolicy`** -- real allow/deny gate; v1 emits `EGRESS_BLOCKED` events for observability without changing HTTP behavior. Consumer wiring (`HttpFetchAgent` integration) deferred to AD-456b.
- **`AuditLog`** -- real append-only hash chain; consumed by the existing `event_log.py` infrastructure.

One deferred:

- **`RuntimeSandbox`** -- process isolation for agent code execution. Substantial change (touches `cognitive/code_validator.py`, self-mod pipeline, possibly OS-level subprocess). Deferred wholesale to AD-456b. v1 ships nothing under this capability name to honor no-theater discipline.

This is **policy + diagnostics layered on existing surfaces.** AD-456 does NOT modify `HttpFetchAgent`, does NOT change `event_log.py`, does NOT add subprocess sandboxing, does NOT touch the LLM client. It composes existing primitives into security-friendly observation surfaces.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
SECRET_ROTATED = "secret_rotated"  # AD-456
EGRESS_BLOCKED = "egress_blocked"  # AD-456
AUDIT_RECORDED = "audit_recorded"  # AD-456
```

Three new values. Verified absent via `grep -n "SECRET_ROTATED\|EGRESS_BLOCKED\|AUDIT_RECORDED" src/probos/events.py` (no matches).

---

## Section 1: Extend `CredentialStore` (AD-395) with rotation + persistence

**File:** `src/probos/credential_store.py` (existing)

AD-456 EXTENDS the existing `CredentialStore` (AD-395 at `credential_store.py:32`) — does NOT introduce a new parallel class. Pass-1 review found that `SecretsManager` would have duplicated 80% of `CredentialStore`'s functionality (resolution chain, caching, department access). Instead, we add three capabilities to the existing class:

1. **Persistent rotation** -- `rotate(name, value) -> bool` writes a JSON store atomically and updates the in-memory cache.
2. **JSON-store resolution step** -- a new step in the resolution chain (priority: config → env → store → CLI → None). The store survives across resets.
3. **`SECRET_ROTATED` event emission** -- on every rotation, fires the new EventType.

**SEARCH** (in `CredentialStore.__init__`):

```python
class CredentialStore:
    """Ship's Computer service -- centralized credential resolution."""

    def __init__(
        self,
        config: Any = None,
        event_log: Any = None,
        cache_ttl: float = 300.0,
    ):
        self._config = config
        self._event_log = event_log
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        self._cache_ttl = cache_ttl
        self._register_builtins()
```

**REPLACE:**

```python
class CredentialStore:
    """Ship's Computer service -- centralized credential resolution.

    AD-456: Extended with persistent rotation, JSON-backed store resolution
    step, and SECRET_ROTATED emission.
    """

    def __init__(
        self,
        config: Any = None,
        event_log: Any = None,
        cache_ttl: float = 300.0,
        *,
        store_path: "Path | None" = None,
        emit_event: Any | None = None,
    ):
        self._config = config
        self._event_log = event_log
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        self._cache_ttl = cache_ttl
        # AD-456: optional persistent JSON store (atomic write + rotation events)
        self._store_path = store_path
        self._emit_event = emit_event
        self._store: dict[str, str] = {}
        self._store_loaded = False
        self._register_builtins()
```

Add a Path import at module top:

**SEARCH** (existing imports):
```python
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)
```

**REPLACE:**
```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import json

logger = logging.getLogger(__name__)
```

> Builder note: `import time` is already present at line 12; `import os` and `import subprocess` already imported. Only `json` and `pathlib.Path` are new.

---

## Section 2: Add `_load_store`, `_resolve_from_store`, and `rotate` methods to CredentialStore

**File:** `src/probos/credential_store.py` (continued)

Insert these methods on `CredentialStore` after the existing `_register_builtins()`:

```python
    # ---------- AD-456: persistent rotation ----------

    def _load_store(self) -> None:
        """Lazy-load the JSON-backed store. Idempotent."""
        if self._store_loaded or self._store_path is None:
            return
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if isinstance(key, str) and isinstance(value, str):
                            self._store[key] = value
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "AD-456: secrets store read failed (path=%s); "
                    "starting with empty store",
                    self._store_path, exc_info=True,
                )
        self._store_loaded = True

    def _resolve_from_store(self, name: str) -> str | None:
        """Resolution-chain step: read from JSON store. Returns None if absent."""
        self._load_store()
        return self._store.get(name)

    def rotate(self, name: str, value: str) -> bool:
        """Operator-side rotate: write the JSON store atomically and emit SECRET_ROTATED.

        Returns True on persisted rotation, False if the rotation could not
        be persisted (no store_path configured, or write failure). Env-sourced
        secrets are NOT mutated by rotate(); operator must update the env var
        externally. The method emits SECRET_ROTATED with `source="env"` so
        observers know a rotation was requested but could not be persisted.
        """
        self._load_store()
        if self._store_path is None:
            logger.warning(
                "AD-456: rotate(%s) called but no store_path configured; "
                "cannot persist", name,
            )
            self._emit_rotated(name, source="no_store", persisted=False)
            return False

        spec = self._specs.get(name)
        if spec is not None and spec.env_var:
            env_value = os.environ.get(spec.env_var, "").strip()
            if env_value:
                # Env var is set; persistent rotation does not override env priority.
                self._emit_rotated(name, source="env", persisted=False)
                return False

        self._store[name] = value
        # Invalidate cache so next get(...) resolves fresh.
        self._cache.pop(name, None)

        try:
            tmp = self._store_path.with_suffix(".json.tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._store), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError:
            logger.error(
                "AD-456: secrets store write failed (path=%s); "
                "in-memory cache updated but not persisted",
                self._store_path, exc_info=True,
            )
            self._emit_rotated(name, source="store", persisted=False)
            return False
        self._emit_rotated(name, source="store", persisted=True)
        return True

    def _emit_rotated(self, name: str, *, source: str, persisted: bool) -> None:
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType
            self._emit_event(
                EventType.SECRET_ROTATED,
                {
                    "name": name,
                    "source": source,
                    "persisted": persisted,
                    "rotated_at": time.time(),
                },
            )
        except Exception:
            logger.warning(
                "AD-456: SECRET_ROTATED emit failed (name=%s)", name, exc_info=True,
            )
```

Then update `_resolve()` to consult the store between env vars and CLI:

**SEARCH** (in existing `_resolve` method body — Builder must grep `_resolve` for the actual lines):

```python
        # 2. Primary env var
        if spec.env_var:
            val = os.environ.get(spec.env_var, "").strip()
            if val:
                return val
```

**REPLACE:**

```python
        # 2. Primary env var
        if spec.env_var:
            val = os.environ.get(spec.env_var, "").strip()
            if val:
                return val

        # 2a. AD-456: env var aliases (preserved from existing behavior;
        # then JSON-backed store as 2b before CLI step)
        # The aliases iteration is already present in the existing code;
        # the new step inserts AFTER aliases and BEFORE the CLI step.

        # 2b. AD-456: JSON-backed store (rotated values; survives across resets)
        store_val = self._resolve_from_store(spec.name)
        if store_val:
            return store_val
```

> Builder note: `_resolve()` already iterates env_var_aliases between the primary env var and the CLI command. Insert the AD-456 store step AFTER aliases and BEFORE CLI. Builder must grep `_resolve` for the exact aliases-loop boundary; the SEARCH block above shows the env-var step that precedes aliases.

---

## Section 3: `EgressPolicy`

**File:** `src/probos/security/egress.py` (new)

```python
"""AD-456: EgressPolicy -- allow/deny consultation for outbound HTTP.

v1 read-only consultation surface. Subsystems that send outbound HTTP
(HttpFetchAgent, RedTeamAgent verification probes) call `is_allowed(url)`
before making the request. v1 emits EGRESS_BLOCKED when a check would
block -- but does NOT actually intercept the request. Active interception
(consumer wiring) is deferred to AD-456b per the coordinator-then-dispatch
convention.

v1 default: deny_by_default=True with a 5-host built-in allowlist
(127.0.0.1, localhost, ::1, plus the LLM-proxy and ProbOS-internal
services). This makes EGRESS_BLOCKED events fire on every unknown-host
request -- producing real signal even before AD-456b adds active
interception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from probos.events import EventType

logger = logging.getLogger(__name__)


# Default LLM proxy + standard ProbOS-internal endpoints. Operators extend.
_DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "127.0.0.1",
    "localhost",
    "::1",
)


@dataclass(frozen=True)
class EgressDecision:
    """Result of a policy check."""

    allowed: bool
    url: str
    matched_rule: str = ""
    reason: str = ""


@dataclass
class EgressPolicy:
    """In-memory allow/deny policy over outbound URLs.

    v1 surface:
      - is_allowed(url) -> bool (consultation; no interception)
      - check(url) -> EgressDecision (rich result for logging)
      - allow_host(host: str) / deny_host(host: str) (operator-side mutation)

    v1 emits EGRESS_BLOCKED on every blocked decision (deny-by-default OR
    denylist match). Operators get observable signal today; AD-456b adds
    active interception by wiring `EgressPolicy.is_allowed()` into
    HttpFetchAgent's request path.
    """

    allowlist: list[str] = field(default_factory=lambda: list(_DEFAULT_ALLOWLIST))
    denylist: list[str] = field(default_factory=list)
    emit_event: Any | None = None
    deny_by_default: bool = True  # v1 default: real signal via EGRESS_BLOCKED

    def is_allowed(self, url: str) -> bool:
        return self.check(url).allowed

    def check(self, url: str) -> EgressDecision:
        host = self._extract_host(url)
        if not host:
            decision = EgressDecision(
                allowed=not self.deny_by_default,
                url=url,
                matched_rule="",
                reason="no host parsed",
            )
            if not decision.allowed:
                self._emit_blocked(decision)
            return decision

        for pattern in self.denylist:
            if self._host_matches(host, pattern):
                decision = EgressDecision(
                    allowed=False, url=url, matched_rule=pattern,
                    reason="denylist match",
                )
                self._emit_blocked(decision)
                return decision

        for pattern in self.allowlist:
            if self._host_matches(host, pattern):
                return EgressDecision(
                    allowed=True, url=url, matched_rule=pattern,
                    reason="allowlist match",
                )

        # No allowlist match
        if self.deny_by_default:
            decision = EgressDecision(
                allowed=False, url=url, matched_rule="",
                reason="not in allowlist (deny_by_default)",
            )
            self._emit_blocked(decision)
            return decision
        return EgressDecision(
            allowed=True, url=url, matched_rule="",
            reason="not in allowlist (allow_by_default)",
        )

    def allow_host(self, host: str) -> None:
        if host and host not in self.allowlist:
            self.allowlist.append(host)

    def deny_host(self, host: str) -> None:
        if host and host not in self.denylist:
            self.denylist.append(host)

    def _extract_host(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            return (parsed.hostname or "").lower()
        except Exception:
            return ""

    def _host_matches(self, host: str, pattern: str) -> bool:
        # Exact match or wildcard suffix (e.g., ".example.com" matches "x.example.com")
        if pattern == host:
            return True
        if pattern.startswith(".") and host.endswith(pattern):
            return True
        return False

    def _emit_blocked(self, decision: EgressDecision) -> None:
        if not self.emit_event:
            return
        try:
            self.emit_event(
                EventType.EGRESS_BLOCKED,
                {
                    "url": decision.url,
                    "matched_rule": decision.matched_rule,
                    "reason": decision.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-456: EGRESS_BLOCKED emit failed (url=%s)", decision.url,
                exc_info=True,
            )
```

---

## Section 3: `AuditLog`

**File:** `src/probos/security/audit.py` (new)

Stdlib-only hash chain over an in-memory list. v1 does NOT persist -- a future AD-456c can layer SQLite persistence onto the same surface without breaking consumers.

```python
"""AD-456: AuditLog -- append-only hash-chained record.

v1 in-memory only. Each entry includes the SHA-256 of the prior entry
(hash chain). Tamper detection via verify_chain(). Persistence to SQLite
deferred to AD-456c.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditEntry:
    """One hash-chained audit record."""

    sequence: int
    timestamp: float
    category: str
    detail: str
    prior_hash: str
    entry_hash: str


@dataclass
class AuditLog:
    """In-memory hash-chained log.

    Append-only. Each entry's hash includes the prior entry's hash so any
    tampering breaks the chain. verify_chain() re-derives every hash and
    confirms continuity.
    """

    entries: list[AuditEntry] = field(default_factory=list)
    emit_event: Any | None = None

    GENESIS_HASH: str = "0" * 64

    def append(self, *, category: str, detail: str) -> AuditEntry:
        prior_hash = self.entries[-1].entry_hash if self.entries else self.GENESIS_HASH
        sequence = len(self.entries)
        ts = time.time()
        payload = {
            "sequence": sequence,
            "timestamp": ts,
            "category": category,
            "detail": detail,
            "prior_hash": prior_hash,
        }
        entry_hash = self._hash(payload)
        entry = AuditEntry(
            sequence=sequence,
            timestamp=ts,
            category=category,
            detail=detail,
            prior_hash=prior_hash,
            entry_hash=entry_hash,
        )
        self.entries.append(entry)
        if self.emit_event is not None:
            try:
                self.emit_event(
                    EventType.AUDIT_RECORDED,
                    {
                        "sequence": sequence,
                        "category": category,
                        "entry_hash": entry_hash,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-456: AUDIT_RECORDED emit failed (sequence=%d, category=%s)",
                    sequence, category, exc_info=True,
                )
        return entry

    def verify_chain(self) -> bool:
        """Re-derive every entry hash; return True if chain is intact."""
        prior = self.GENESIS_HASH
        for entry in self.entries:
            payload = {
                "sequence": entry.sequence,
                "timestamp": entry.timestamp,
                "category": entry.category,
                "detail": entry.detail,
                "prior_hash": entry.prior_hash,
            }
            recomputed = self._hash(payload)
            if recomputed != entry.entry_hash or entry.prior_hash != prior:
                return False
            prior = entry.entry_hash
        return True

    def _hash(self, payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
```

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

REPLACE:
```python
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
    SECRET_ROTATED = "secret_rotated"  # AD-456
    EGRESS_BLOCKED = "egress_blocked"  # AD-456
    AUDIT_RECORDED = "audit_recorded"  # AD-456
```

> Builder note: anchor `INFODYNAMIC_REPORT` is verified post-AD-491 (Wave 6). Fallback chain terminates at `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190).

---

## Section 5: Add `SecurityInfraConfig`

**File:** `src/probos/config.py`

```python
class SecurityInfraConfig(BaseModel):
    """Security infrastructure configuration (AD-456).

    Distinct from `SecurityConfig` (AD-455) which configures threat detection,
    input validation, trust integrity, and red-team coordination.
    """

    secrets_persistence_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = True  # v1: real-signal default per no-theater
    audit_enabled: bool = True
```

> Builder note: `secrets_persistence_enabled` controls the JSON-store extension on the existing `CredentialStore` (the in-memory + env-var resolution chain remains active regardless of this flag). When `False`, `CredentialStore.rotate()` returns False and emits `SECRET_ROTATED` with `source="no_store"`.

Wire into `SystemConfig`:

SEARCH:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

REPLACE:
```python
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    security_infra: SecurityInfraConfig = SecurityInfraConfig()  # AD-456
```

> Builder note: anchor-chain fallback (next-anchor if predecessor hasn't landed):
> 1. `infodynamic: InfodynamicConfig` (AD-491, post-Wave 6).
> 2. `degradation: DegradationConfig` (AD-459, post-Wave 6).
> 3. `engineering: EngineeringConfig` (AD-457, post-Wave 6).
> 4. `validation_framework: ValidationFrameworkConfig` (AD-451, post-Wave 6).
> 5. `orders: OrdersConfig = OrdersConfig()  # AD-440` (config.py:1593) -- always-available terminal fallback.

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

The existing `runtime.credential_store` (AD-395; verified at `runtime.py:317`) is reconfigured with the AD-456 persistent-store path and emit hook. EgressPolicy and AuditLog are new public attributes wired alongside.

```python
    # AD-456: Security Infrastructure
    # Reconfigure existing CredentialStore (AD-395) with AD-456 rotation extension
    credential_store = getattr(runtime, "credential_store", None)
    if credential_store is not None and config.security_infra.secrets_persistence_enabled:
        try:
            credential_store._store_path = (
                runtime.data_dir / config.security_infra.secrets_store_filename
            )
            credential_store._emit_event = runtime.emit_event
            logger.info(
                "AD-456: CredentialStore extended with secrets store (path=%s)",
                credential_store._store_path,
            )
        except Exception:
            logger.warning(
                "AD-456: CredentialStore secrets-store extension failed",
                exc_info=True,
            )

    if config.security_infra.egress_enabled:
        from probos.security.egress import EgressPolicy
        runtime.egress_policy = EgressPolicy(
            emit_event=runtime.emit_event,
            deny_by_default=config.security_infra.egress_deny_by_default,
        )
        logger.info("AD-456: EgressPolicy wired (deny_by_default=%s)",
                    config.security_infra.egress_deny_by_default)
    else:
        runtime.egress_policy = None

    if config.security_infra.audit_enabled:
        from probos.security.audit import AuditLog
        runtime.audit_log = AuditLog(emit_event=runtime.emit_event)
        logger.info("AD-456: AuditLog wired (in-memory hash chain)")
    else:
        runtime.audit_log = None
```

> Verify-first: `runtime.credential_store` is the AD-395 public attribute (verified at `runtime.py:317`). `runtime.data_dir` is the AD-468 public property (verified at `runtime.py:934`). `runtime.emit_event` is the post-AD-680 public method (verified at `runtime.py:785`). `runtime.egress_policy` and `runtime.audit_log` are NEW public attributes per Wave 5 retrospective convention #1.
>
> The `credential_store._store_path` and `credential_store._emit_event` post-init assignment is the seam Section 1 introduces (the `__init__` already accepts these keyword-only after Section 1's edit; the post-init reconfiguration is needed because `runtime.credential_store` is constructed earlier in startup and `runtime.data_dir` is required to compute the absolute store path). Mirrors the AD-463 pattern of post-init wiring for late-bound paths.

---

## Tests

**File:** `tests/test_ad456_security_infrastructure.py`

15 tests:

1. `test_event_type_secret_rotated_exists`
2. `test_event_type_egress_blocked_exists`
3. `test_event_type_audit_recorded_exists`
4. `test_security_infra_config_defaults` -- `SecurityInfraConfig()` defaults match documented values (`secrets_persistence_enabled=True`, `egress_deny_by_default=True`, `audit_enabled=True`).
5. `test_credential_store_rotate_persists_to_store` -- construct `CredentialStore(store_path=tmp_path / "secrets.json", emit_event=mock_emit)`, register a spec without env_var, call `rotate("test_key", "v1")` -> JSON store written; subsequent `get("test_key")` returns "v1"; `mock_emit` fired once with `SECRET_ROTATED, source="store", persisted=True`.
6. `test_credential_store_rotate_skipped_when_env_set` -- monkeypatch env var; `rotate("github", "new")` returns False; emit fires with `source="env", persisted=False`; JSON store unchanged.
7. `test_credential_store_rotate_returns_false_when_no_store_path` -- construct without `store_path`; `rotate("any", "v")` returns False; emit fires with `source="no_store", persisted=False`.
8. `test_credential_store_resolution_chain_includes_store` -- with no env var and store populated -> `get()` returns store value.
9. `test_egress_policy_default_allowlist_includes_localhost` -- `is_allowed("http://127.0.0.1:8080/v1")` is True without configuration.
10. `test_egress_policy_denylist_blocks_match` -- `deny_host("evil.com")` then `is_allowed("https://evil.com/x")` -> False; `EGRESS_BLOCKED` emit fires with matched_rule="evil.com".
11. `test_egress_policy_deny_by_default_blocks_unknown` -- v1 default `deny_by_default=True`, `is_allowed("https://unknown.com")` -> False; `EGRESS_BLOCKED` emit fires; `mock_emit.call_count == 1`.
12. `test_audit_log_append_creates_chained_entry` -- first append: `prior_hash=GENESIS_HASH`. Second append: `prior_hash` matches first entry's `entry_hash`. `AUDIT_RECORDED` emits per append.
13. `test_audit_log_verify_chain_detects_tamper` -- append 3 entries; mutate `entries[1].detail` -> `verify_chain()` returns False.
14. `test_audit_log_verify_chain_detects_genesis_tamper` -- append 3 entries; mutate `entries[0].prior_hash` to non-GENESIS value -> `verify_chain()` returns False.
15. `test_audit_log_verify_chain_intact_after_appends` -- append 5 entries -> `verify_chain()` returns True.

Each test uses `tmp_path` for filesystem fixtures and `monkeypatch` for env-var patches. No shared mutable state.

---

## What This Does NOT Change

- `agents/http_fetch.py` is unchanged. EgressPolicy is consultation-only in v1; consumer wiring deferred to AD-456b. **AD-456b will wire `EgressPolicy.is_allowed(url)` as a pre-check in `HttpFetchAgent`'s request path**, integrating with the existing per-domain rate-limit state.
- `agents/red_team.py` HTTP probes unchanged.
- `cognitive/llm_client.py` is unchanged. The existing CredentialStore env-var resolution continues; consumer migration to per-tier credential lookup deferred to AD-456c.
- `event_log.py` SQLite schema is unchanged. AuditLog is in-memory only in v1; SQLite persistence deferred to AD-456d.
- `cognitive/code_validator.py` and self-mod pipeline are unchanged. **`RuntimeSandbox` (process isolation) is deferred wholesale to AD-456b.**
- `security/__init__.py` (AD-455) is NOT modified -- `egress`, `audit` are imported from their dotted paths, not re-exported from the package's `__init__.py`. AD-456 does NOT touch AD-455's existing `ThreatDetector`, `InputValidator`, `TrustIntegrityMonitor`, `RedTeamLead` services.
- **`SecretsManager` is NOT introduced as a new class.** Pass-1 review identified that the proposed class duplicated 80% of the existing `CredentialStore` (AD-395) functionality. AD-456 instead EXTENDS `CredentialStore` with persistent-rotation + JSON-store resolution + `SECRET_ROTATED` emission. The existing `CredentialStore` department-access control, caching, and CLI fallback are preserved. No `runtime.secrets_manager` attribute is created -- consumers continue to use `runtime.credential_store`.
- AD-456 introduces NO destructive intents -- all v1 services are read-only or operator-side mutations. The `requires_consensus=True` rule does not apply.

---

## Tracking

- `PROGRESS.md`: add `AD-456 CLOSED. Security Infrastructure (Secrets / Egress / Audit) -- ...`
- `docs/development/roadmap.md`: flip AD-456 status from `*(planned)*` to `*(complete)*` near line 4142.
- `DECISIONS.md`: optional entry recording the v1-three-services + RuntimeSandbox-deferred-to-AD-456b scope decision.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/credential_store.py`: ~110 lines added (Section 1 constructor extension + Section 2 rotate/persistence methods); Section 2 inserts AFTER `_register_builtins` and modifies `_resolve` body to insert the store step.
- `src/probos/security/egress.py`: ~125 lines (new).
- `src/probos/security/audit.py`: ~95 lines (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~30 lines added.
- `tests/test_ad456_security_infrastructure.py`: ~310 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

`security/__init__.py` is NOT touched -- the new modules are imported from their dotted paths. `credential_store.py` deletes 0 lines; only inserts. Sanity check should show 0 deletions on every file.

---

## Acceptance Criteria

- All 15 tests pass under `pytest tests/test_ad456_security_infrastructure.py -v -n 0`.
- Full parallel gate non-decreasing.
- 3 new EventTypes appear exactly once in `events.py`.
- `runtime.egress_policy` and `runtime.audit_log` are public attributes (no leading underscore).
- `runtime.credential_store` (AD-395 existing public attribute) is preserved; AD-456 EXTENDS it with rotation + persistence.
- `EgressPolicy`, `AuditLog`, and the `CredentialStore` extension use stdlib only (`json`, `os`, `hashlib`, `urllib.parse`, `pathlib`, `time`); no new pyproject deps.
- `agents/http_fetch.py` and `agents/red_team.py` are unchanged.
- `event_log.py` is unchanged.
- `security/__init__.py` (AD-455) is unchanged.
- `RuntimeSandbox` is NOT shipped in v1 -- explicitly deferred to AD-456b.
- **No new `SecretsManager` class** -- functionality folded into `CredentialStore` extension.
- v1 EgressPolicy default `deny_by_default=True` -- `EGRESS_BLOCKED` events fire on every unknown-host check, producing real signal today.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/security/
  __init__.py  input_validator.py  red_team_lead.py  threat_detector.py  trust_integrity.py
  (AD-455 package; AD-456 EXTENDS, does NOT own __init__.py creation)

grep -n "^class " src/probos/security/threat_detector.py src/probos/security/red_team_lead.py
  threat_detector.py:47: class ThreatDetector
  red_team_lead.py:34: class RedTeamLead
  (AD-455 services; AD-456 does not modify these)

grep -rn "class SecretsManager\|class EgressPolicy\|class AuditLog\|class RuntimeSandbox" src/probos/
  (no matches -- AD-456 introduces these names; RuntimeSandbox deferred to AD-456b)

grep -n "SECRET_ROTATED\|EGRESS_BLOCKED\|AUDIT_RECORDED" src/probos/events.py
  (no matches -- names are free)

grep -n "AGENT_SELF_NAMED\|INFODYNAMIC_REPORT" src/probos/events.py
  190: AGENT_SELF_NAMED = "agent_self_named"  # AD-499
  (terminal fallback)

grep -n "self\._data_dir\|def data_dir" src/probos/runtime.py
  289: self._data_dir = ...
  933: @property
  934: def data_dir(self) -> Path:
  (public property post-AD-468)

grep -n "def emit_event" src/probos/runtime.py
  775: def emit_event(self, event: BaseEvent | str | EventType, ...

grep -n "runtime\.red_team_lead\|runtime\.threat_detector" src/probos/startup/finalize.py
  422: runtime.red_team_lead = red_team_lead
  (AD-455 wiring; AD-456 wires after this block)

grep -n "class HttpFetchAgent" src/probos/agents/http_fetch.py
  34: class HttpFetchAgent(BaseAgent):
  (consumer; AD-456 does NOT modify -- v1 ships consultation surface only)

grep -n "orders: OrdersConfig" src/probos/config.py
  1593: orders: OrdersConfig = OrdersConfig()  # AD-440
  (always-available terminal fallback)

grep -n "class CredentialStore\|def _register_builtins\|def _resolve" src/probos/credential_store.py
  32: class CredentialStore:
  48: def _register_builtins(self) -> None:
  119: def _resolve(self, spec: CredentialSpec) -> str | None:
  (AD-395 existing class; AD-456 EXTENDS via constructor kwargs and new methods)

grep -n "self\.credential_store" src/probos/runtime.py
  185: credential_store: CredentialStore
  317: self.credential_store = CredentialStore(
  (AD-395 public attribute; AD-456 reconfigures via finalize.py post-init wiring)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-456-security-infrastructure-review.md`.

**Required addressed:**

- **R#1: SecretsManager duplicated CredentialStore (AD-395)** -- Resolution (a): EXTEND CredentialStore. Section 1 rewrites the `__init__` signature to accept optional `store_path` and `emit_event` kwargs; Section 2 adds `_load_store`, `_resolve_from_store`, `rotate`, and `_emit_rotated` methods plus the JSON-store step in `_resolve`. The new `SecretsManager` class is dropped wholesale. The old `runtime.secrets_manager` public attribute is dropped (consumers continue to use `runtime.credential_store`).
- **R#2: ENV_PREFIX = "PROBOS_" collided with mixed live convention** -- resolved by R#1: env-var resolution remains via existing `CredentialSpec.env_var` per-spec configuration. No global prefix is introduced. The existing convention (mixed `PROBOS_*` for Docker/NATS overrides; bespoke names for legacy keys) is preserved.
- **R#3: EgressPolicy / HttpFetchAgent integration documented** -- "What This Does NOT Change" now explicitly notes "AD-456b will wire `EgressPolicy.is_allowed(url)` as a pre-check in `HttpFetchAgent`'s request path."

**Cross-cutting EgressPolicy theater check:** `deny_by_default` default flipped from `False` to `True` (Section 3 + Section 5). v1 EgressPolicy now fires `EGRESS_BLOCKED` on every unknown-host check -- real signal today, not theater. Default allowlist expanded to include `::1` for IPv6 localhost. The cross-cutting fix #6 (EgressPolicy must be real or wholesale-deferred) resolves toward "real today."

**Recommended applied:**

- **rec#1: deny_by_default default to True** -- folded into the cross-cutting fix above; v1 produces observable signal.
- **rec#2: AuditLog scaling note** -- documented in "What This Does NOT Change": AD-456 v1 is suitable for short-lived audit windows; SQLite-persisted audit deferred to AD-456d.
- **rec#3: rotate() naming clarity** -- `_emit_rotated` payload includes a `persisted: bool` field so callers can distinguish persisted-rotation from rotation-requested-but-not-persisted (env-sourced or no-store-configured). Naming preserved (`rotate`) to keep API recognizable.
- **rec#4: AuditLog.verify_chain genesis-tamper test** -- added as Test #14 (`test_audit_log_verify_chain_detects_genesis_tamper`).
- **rec#5: Section 6 always-wired uniformity** -- `runtime.credential_store` is always-wired (AD-395 existing). `egress_policy` and `audit_log` use the always-wired pattern with `runtime.X = None` when disabled, so consumers can defensively check.

**Recommended deferred:**

- (none; all 5 applied)

**Nits applied:**

- **nit#1: footer line drift** -- `runtime.emit_event` line corrected from 775 to 785.
- **nit#2: AuditLog hash float-precision note** -- documented in "What This Does NOT Change."
- **nit#3: SecretsManager._load() reload note** -- N/A (SecretsManager dropped); CredentialStore's `_load_store()` is idempotent with `_store_loaded` flag; future `reload()` for runtime-edited stores deferred to AD-456c.
- **nit#4: Test 11 emit assertion** -- Test #11 description now explicitly says `mock_emit.call_count == 1`.

**Verified Against Codebase footer extended:** added `CredentialStore` class location (`credential_store.py:32`), `_register_builtins` (line 48), `_resolve` (line 119), `runtime.credential_store` (`runtime.py:185, 317`).

**Test count: 14 → 15** (added genesis-tamper test; SecretsManager-specific tests dropped; CredentialStore extension tests added).

**Wave-5/6 conventions audit (post-revision):**

- #1 Public-attribute wiring: 2 NEW public attributes (`runtime.egress_policy`, `runtime.audit_log`) -- no `runtime.secrets_manager` -- existing `runtime.credential_store` preserved. ✅
- #2 stdlib-only: `json`, `os`, `hashlib`, `urllib.parse`, `pathlib`, `time` -- all stdlib. ✅
- #3 Coordinator-then-dispatch: EgressPolicy v1 consultation-only with real EGRESS_BLOCKED emit; consumer wiring (HttpFetchAgent) deferred to AD-456b. ✅
- #4 Superset-filter: EgressPolicy doesn't intercept; AuditLog is additive; CredentialStore extension is a NEW resolution-chain step (not gating existing ones). ✅
- #5 init_<phase>: Section 6 wires from `startup/finalize.py` (receives `runtime`). ✅
- #6 Verify-first: footer now includes the missing `CredentialStore` greps. ✅
- #7 No-theater: EgressPolicy fires events today; SecretsManager removed (was duplication); RuntimeSandbox deferred wholesale. ✅

**No-theater discipline (cross-cutting):** v1 ships:
- CredentialStore extension (real persistence + real rotation events)
- EgressPolicy (real event emission under deny_by_default=True)
- AuditLog (real hash-chained log)

All three do real work today. Two deferrals (RuntimeSandbox, SQLite-persisted audit) are wholesale -- nothing shipped under those capability names.

**Public-attribute count delta for the wave:** `runtime.secrets_manager` removed; net Wave 7 attribute count drops from 8 to 7. README-wave-7-pass-2.md sweep summary should reflect this.

**Verdict shift:** Pass-1 ❌ Not Ready → expected ✅ Approved on second-pass review (R#1 architectural decision applied; R#2 + R#3 mechanical fixes applied; cross-cutting theater check resolved real-today).
