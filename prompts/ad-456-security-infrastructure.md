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

## Section 1: `SecretsManager`

**File:** `src/probos/security/secrets.py` (new)

```python
"""AD-456: SecretsManager -- single-source-of-truth for secret reads.

v1: in-process read API + JSON store under runtime.data_dir/secrets.json.
Stdlib-only persistence per Wave 5 retrospective convention #2 -- no new
pyproject deps.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretMetadata:
    """Public metadata about a secret -- never includes the secret value."""

    key: str
    last_rotated_at: float
    source: str  # "env" or "store"


class SecretsManager:
    """Stdlib-only secrets store.

    Reads:
      1. ProbOS-prefixed env vars (e.g., PROBOS_LLM_API_KEY) -- highest priority.
      2. JSON store under data_dir/secrets.json -- secondary.

    Writes:
      - rotate(key, value) updates the JSON store atomically (write-to-tmp +
        os.replace). Env-var-sourced secrets are NOT written -- the rotate()
        call updates the in-memory cache only and emits SECRET_ROTATED.

    Public read API never returns plaintext to logs. Callers receive the
    secret string; it is the caller's responsibility to handle it safely.
    """

    ENV_PREFIX = "PROBOS_"

    def __init__(
        self,
        *,
        data_dir: Path,
        emit_event: Any | None = None,
        store_filename: str = "secrets.json",
    ) -> None:
        self._data_dir = data_dir
        self._emit_event = emit_event
        self._store_path = data_dir / store_filename
        self._cache: dict[str, str] = {}
        self._metadata: dict[str, SecretMetadata] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if isinstance(key, str) and isinstance(value, str):
                            self._cache[key] = value
                            self._metadata[key] = SecretMetadata(
                                key=key,
                                last_rotated_at=0.0,
                                source="store",
                            )
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "AD-456: secrets.json read failed (path=%s); "
                    "starting with empty store",
                    self._store_path, exc_info=True,
                )
        self._loaded = True

    def get(self, key: str) -> str | None:
        """Return the secret value or None. Never logs the value."""
        self._load()
        env_key = self.ENV_PREFIX + key.upper()
        env_value = os.environ.get(env_key)
        if env_value is not None:
            return env_value
        return self._cache.get(key)

    def metadata(self, key: str) -> SecretMetadata | None:
        """Return metadata WITHOUT the secret value."""
        self._load()
        env_key = self.ENV_PREFIX + key.upper()
        if env_key in os.environ:
            return SecretMetadata(key=key, last_rotated_at=0.0, source="env")
        return self._metadata.get(key)

    def rotate(self, key: str, value: str) -> bool:
        """Operator-side rotate. Writes JSON store, emits SECRET_ROTATED.

        Returns True on persisted rotation, False if the rotation could not
        be persisted (env-sourced or write failure).
        """
        self._load()
        env_key = self.ENV_PREFIX + key.upper()
        if env_key in os.environ:
            # Env-sourced secrets are NOT written to JSON store.
            self._emit_rotated(key, source="env")
            return False
        self._cache[key] = value
        self._metadata[key] = SecretMetadata(
            key=key, last_rotated_at=time.time(), source="store",
        )
        try:
            tmp = self._store_path.with_suffix(".json.tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError:
            logger.error(
                "AD-456: secrets.json write failed (path=%s); "
                "in-memory cache updated but not persisted",
                self._store_path, exc_info=True,
            )
            return False
        self._emit_rotated(key, source="store")
        return True

    def _emit_rotated(self, key: str, *, source: str) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.SECRET_ROTATED,
                {"key": key, "source": source, "rotated_at": time.time()},
            )
        except Exception:
            logger.warning(
                "AD-456: SECRET_ROTATED emit failed (key=%s)", key, exc_info=True,
            )
```

---

## Section 2: `EgressPolicy`

**File:** `src/probos/security/egress.py` (new)

```python
"""AD-456: EgressPolicy -- allow/deny consultation for outbound HTTP.

v1 read-only consultation surface. Subsystems that send outbound HTTP
(HttpFetchAgent, RedTeamAgent verification probes) call `is_allowed(url)`
before making the request. v1 emits EGRESS_BLOCKED when a check would
block -- but does NOT actually intercept the request. Active interception
(consumer wiring) is deferred to AD-456b per the coordinator-then-dispatch
convention.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from probos.events import EventType

logger = logging.getLogger(__name__)


# Default LLM proxy + standard ProbOS-internal endpoints. Operators extend.
_DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "127.0.0.1",
    "localhost",
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
    """

    allowlist: list[str] = field(default_factory=lambda: list(_DEFAULT_ALLOWLIST))
    denylist: list[str] = field(default_factory=list)
    emit_event: Any | None = None
    deny_by_default: bool = False  # v1 default: allow unknown hosts (observation only)

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

    secrets_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = False
    audit_enabled: bool = True
```

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

Place near the existing AD-455 SecurityTeam wiring block (verified at `finalize.py:422` for `runtime.red_team_lead`):

```python
    # AD-456: Security Infrastructure (Secrets / Egress / Audit)
    if config.security_infra.secrets_enabled:
        from probos.security.secrets import SecretsManager
        runtime.secrets_manager = SecretsManager(
            data_dir=runtime.data_dir,
            emit_event=runtime.emit_event,
            store_filename=config.security_infra.secrets_store_filename,
        )
        logger.info("AD-456: SecretsManager wired")
    else:
        runtime.secrets_manager = None

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

> Verify-first: `runtime.data_dir` is a public property post-AD-468 (`runtime.py:934`). `runtime.emit_event` is the post-AD-680 public method. All three new attributes are public (no leading underscore) per Wave 5 retrospective convention #1.

---

## Tests

**File:** `tests/test_ad456_security_infrastructure.py`

14 tests:

1. `test_event_type_secret_rotated_exists`
2. `test_event_type_egress_blocked_exists`
3. `test_event_type_audit_recorded_exists`
4. `test_security_infra_config_defaults` -- `SecurityInfraConfig()` defaults match documented values.
5. `test_secrets_manager_get_returns_env_first` -- `PROBOS_LLM_API_KEY` set in env -> `get("llm_api_key")` returns env value, not store.
6. `test_secrets_manager_get_returns_store_when_no_env` -- empty env, `secrets.json` populated -> `get()` returns store value.
7. `test_secrets_manager_rotate_persists_to_store` -- `rotate("k", "v")` writes JSON store atomically; `get("k")` returns "v" on next call. Emit fires with `SECRET_ROTATED`.
8. `test_secrets_manager_rotate_skips_persist_for_env_sourced` -- env var set; `rotate()` returns False, JSON store unchanged, emit fires with `source="env"`.
9. `test_egress_policy_default_allowlist_includes_localhost` -- `is_allowed("http://127.0.0.1:8080/v1")` is True without configuration.
10. `test_egress_policy_denylist_blocks_match` -- `deny_host("evil.com")` then `is_allowed("https://evil.com/x")` -> False; `EGRESS_BLOCKED` emit fires.
11. `test_egress_policy_deny_by_default_blocks_unknown` -- `deny_by_default=True`, `is_allowed("https://unknown.com")` -> False; emit fires.
12. `test_audit_log_append_creates_chained_entry` -- first append: `prior_hash=GENESIS_HASH`. Second append: `prior_hash` matches first entry's `entry_hash`. `AUDIT_RECORDED` emits per append.
13. `test_audit_log_verify_chain_detects_tamper` -- append 3 entries; mutate `entries[1].detail` -> `verify_chain()` returns False.
14. `test_audit_log_verify_chain_intact_after_appends` -- append 5 entries -> `verify_chain()` returns True.

Each test uses `tmp_path` for filesystem fixtures (SecretsManager) and isolated `os.environ` patches (monkeypatch). No shared mutable state.

---

## What This Does NOT Change

- `agents/http_fetch.py` is unchanged. EgressPolicy is consultation-only in v1; consumer wiring deferred to AD-456b.
- `agents/red_team.py` HTTP probes unchanged. EgressPolicy does not gate them in v1.
- `cognitive/llm_client.py` is unchanged. SecretsManager is shipped but consumer wiring (LLM tier auth) deferred to AD-456c -- existing env-var reads continue.
- `event_log.py` SQLite schema is unchanged. AuditLog is in-memory only in v1; SQLite persistence deferred to AD-456d.
- `cognitive/code_validator.py` and self-mod pipeline are unchanged. **`RuntimeSandbox` (process isolation) is deferred wholesale to AD-456b.**
- `security/__init__.py` (AD-455) is NOT modified -- `secrets`, `egress`, `audit` are imported from their dotted paths, not re-exported from the package's `__init__.py`. AD-456 does NOT touch AD-455's existing `ThreatDetector`, `InputValidator`, `TrustIntegrityMonitor`, `RedTeamLead` services.
- AD-456 introduces NO destructive intents -- all three v1 services are read-only or operator-side mutations. The `requires_consensus=True` rule does not apply to this v1.

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
- `src/probos/security/secrets.py`: ~135 lines (new).
- `src/probos/security/egress.py`: ~125 lines (new).
- `src/probos/security/audit.py`: ~95 lines (new).
- `src/probos/events.py`: 3 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~28 lines added.
- `tests/test_ad456_security_infrastructure.py`: ~290 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

`security/__init__.py` is NOT touched -- the new modules are imported from their dotted paths. Sanity check should show 0 deletions on every file.

---

## Acceptance Criteria

- All 14 tests pass under `pytest tests/test_ad456_security_infrastructure.py -v -n 0`.
- Full parallel gate non-decreasing.
- 3 new EventTypes appear exactly once in `events.py`.
- `runtime.secrets_manager`, `runtime.egress_policy`, `runtime.audit_log` are public attributes (no leading underscore).
- `SecretsManager`, `EgressPolicy`, `AuditLog` use stdlib only (`json`, `os`, `hashlib`, `urllib.parse`, `pathlib`, `time`); no new pyproject deps.
- `agents/http_fetch.py` and `agents/red_team.py` are unchanged.
- `event_log.py` is unchanged.
- `security/__init__.py` (AD-455) is unchanged.
- `RuntimeSandbox` is NOT shipped in v1 -- explicitly deferred to AD-456b.
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
```
