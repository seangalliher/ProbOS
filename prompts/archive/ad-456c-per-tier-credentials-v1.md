# AD-456c v1 — Security Infrastructure: Per-Tier Credential Lookup

**Status:** ready
**Dependencies:** AD-456 v1 (`CredentialStore`, `SecurityInfraConfig`, `runtime.credential_store` — all shipped); AD-456b v1 (`SecurityInfraConfig.egress_active_enforcement` transitional-flag pattern — shipped Wave 55); AD-680 (`runtime.emit_event` public); AD-357 / AD-674 (Earned Agency `AgencyLevel` — shipped)
**Estimated tests:** 13 new (1 new test file `tests/test_ad456c_per_tier_credentials.py`)
**Closes:** GH issue #399

---

## Problem

`CredentialStore` (`src/probos/credential_store.py`) is the Ship's-Computer credential resolution surface (AD-395, extended by AD-456 v1 with persistent rotation + `SECRET_ROTATED` emission). Every agent-side credential lookup routes through `runtime.credential_store.get(name, requester=..., department=...)`. The store ships **two** access-control axes today:

1. `CredentialSpec.allowed_departments: list[str] | None` — coarse cohort gate (`credential_store.py:30`).
2. `_log_access` audit trail to `event_log` (`credential_store.py:277-292`).

It does **not** consult the agent's Earned Agency tier (Ensign / Lieutenant / Commander / Senior). The roadmap entry (`docs/development/roadmap.md:4146`) contracts AD-456c to plumb this:

> "Secrets Manager credential lookup gated by Earned Agency tier. Ensign-level agents get no direct credential access; Commander+ agents can request scoped secrets. **v1 ships flat access model.**"

The Earned Agency tier model is already shipped (AD-357 → AD-674): `AgencyLevel` enum (`earned_agency.py:11`) — `REACTIVE` (Ensign) / `SUGGESTIVE` (Lieutenant) / `AUTONOMOUS` (Commander) / `UNRESTRICTED` (Senior); `agency_from_rank()` resolves rank → agency. The piece that does NOT exist is the consumption seam in `CredentialStore` and a transitional config flag mirroring `egress_active_enforcement` (AD-456b v1 pattern).

This AD plumbs the seam:

```
CredentialSpec.min_tier: str | None      # NEW: per-spec minimum AgencyLevel string ("reactive"/"suggestive"/"autonomous"/"unrestricted"), default None = no gate
CredentialStore._tier_enforcement: bool  # NEW: instance flag, default False, flipped via set_tier_enforcement(True) at finalize when config.security_infra.credential_tier_enforcement=True
CredentialStore.get(name, *, requester, department=None, tier=None)
    │
    ├── existing department gate                                     # unchanged
    ├── if _tier_enforcement and spec.min_tier is not None:          # NEW (Section 2e)
    │       deny if tier missing OR ord(tier) < ord(spec.min_tier)
    │       emit CREDENTIAL_TIER_DENIED + log_access(..., "denied_tier")
    └── existing cache + resolution chain                            # unchanged
```

`v1 ships the flat access model` per the roadmap — every spec carries ONE `min_tier`; caller passes a single `tier` string per `get()` call. Per-secret scope policy (e.g., "only the GitHub Department can read `github`"), graduated trust → capability-set mapping, and caller-side automatic tier resolution from `runtime.crew_profile_store` are deferred to AD-456c-1 / AD-456c-2 / AD-456c-3 with explicit forcing functions.

## Solution

v1 ships:

1. **`CredentialSpec.min_tier: str | None = None`** — new field on the existing dataclass at `credential_store.py:22-30`. Default `None` preserves backwards compat — every existing built-in spec (`github`, `discord`, `llm_api` registered in `_register_builtins` lines 62-81) is ungated. Operator extensions register new specs with `min_tier="autonomous"` etc.

2. **Module-level `_AGENCY_ORDER` ordering map.** Maps `AgencyLevel.value` strings to ordinal ints — `reactive=0` / `suggestive=1` / `autonomous=2` / `unrestricted=3`. Mirrors `_TIER_ORDER` at `earned_agency.py:90-96`. Local copy avoids importing `probos.earned_agency` into `credential_store.py` (Law of Demeter — credential resolution should not depend on the rank/agency module's full surface; a four-string ordering map is the minimum coupling). Unknown tier strings return ordinal `-1` (sentinel — deny).

3. **`CredentialStore._tier_enforcement: bool = False`** — new instance attribute. Defaults False so AD-456 + AD-456b deployments preserve consultation-only behavior. Flipped to True via `set_tier_enforcement(True)` at finalize when `config.security_infra.credential_tier_enforcement=True`. Convention #14 + #3: default-False on transitional flag; AD-456c-N flips default in a future grandchild AD once fleet-wide `min_tier` coverage is verified.

4. **`CredentialStore.set_tier_enforcement(self, enabled: bool)`** — new instance method. Mirrors AD-456b's `HttpFetchAgent.set_egress_policy` opt-in shape, but instance-level (not ClassVar) because `CredentialStore` is a singleton owned by `runtime` (`runtime.py:317`), unlike `HttpFetchAgent` which has many pool members sharing a class.

5. **`CredentialStore.get(...)` adds optional `tier: str | None = None` kwarg.** Insert tier check AFTER the existing department check (defense in depth — department is the cohort gate; tier is the rank gate). When `_tier_enforcement=False`, the new block is a no-op regardless of `spec.min_tier`. When `_tier_enforcement=True` AND `spec.min_tier is not None`:
   - `tier is None` → deny (fail-closed: caller must pass tier when enforcement is on).
   - `_AGENCY_ORDER.get(tier, -1) < _AGENCY_ORDER[spec.min_tier]` → deny.
   On deny: emit `CREDENTIAL_TIER_DENIED` via `self._emit_event` (existing field, AD-456 wiring) + `_log_access(name, requester, "denied_tier")` (existing event_log audit chain) + return `None`.

6. **`EventType.CREDENTIAL_TIER_DENIED`** — new enum value. Inserted adjacent to the AD-456 / AD-456b sandbox events at `events.py:204-212`, immediately after `SANDBOX_CAPABILITY_DENIED` (line 212).

7. **`SecurityInfraConfig.credential_tier_enforcement: bool = False`** — new field appended after `egress_active_enforcement` at `config.py:1471`. Default False; mirrors `egress_active_enforcement` exactly (Wave 55 / AD-456b precedent).

8. **`startup/finalize.py` wiring** — add a single `if`-block after the existing AD-456 `credential_store._emit_event = runtime.emit_event` extension (`finalize.py:1257-1267`) that calls `credential_store.set_tier_enforcement(True)` when the config flag is on. When `credential_tier_enforcement=False` (default), the new wiring is a no-op and AD-456 / AD-456b behavior is preserved bit-for-bit.

`tokens_used`-style backwards compatibility: every existing AD-456 test, every existing CredentialStore test (`tests/test_credential_store.py`), every existing AD-456b test, every existing finalize test continues to function. No symbol is removed; no signature is changed except the additive `tier=` kwarg on `get()`. New `min_tier` field defaults `None`; new `_tier_enforcement` defaults `False`; new `credential_tier_enforcement` defaults `False`. Existing call sites (`credential_store.get(name)` / `credential_store.get(name, requester="x")`) behave identically to today.

### Scope

| Component | Status |
|---|---|
| `CredentialSpec.min_tier` field | EDIT (additive) |
| `CredentialStore._tier_enforcement` instance attr + `set_tier_enforcement` method | EDIT (additive) |
| `CredentialStore.get(...)` tier-gate block + `_emit_tier_denied` helper | EDIT (additive) |
| Module-level `_AGENCY_ORDER` constant | NEW (in `credential_store.py`) |
| `EventType.CREDENTIAL_TIER_DENIED` | NEW |
| `SecurityInfraConfig.credential_tier_enforcement` | NEW |
| `startup/finalize.py` `set_tier_enforcement` wiring (1 if-block) | EDIT (additive) |
| `tests/test_ad456c_per_tier_credentials.py` (13 tests) | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Caller-side tier resolution.** Agents currently call `runtime.credential_store.get(name, requester=self.agent_type)` without passing `tier`. v1 ships the API surface; AD-456c-2 wires automatic tier resolution at the call site (`tier=agency_from_rank(self._crew_profile.rank).value`) once production call sites surface concrete tier requirements. v1 forcing function: ship the seam, Captain validates that ≥1 agent path exercises `tier=` end-to-end before the auto-resolution rollout.
- **Per-secret scope policy.** v1 ships ONE `min_tier` per spec. Per-spec read/write/rotate scopes (e.g., GitHub spec readable by GitHub Department but rotatable only by Captain) deferred to AD-456c-1.
- **Graduated trust → capability-set policy.** `BayesianTrust` score → `frozenset[capability]` mapping (`net.read` / `fs.write` etc.). Cross-link to AD-456b-2 (sandbox capability policy) — same forcing function. Deferred to AD-456c-2-trust-band (or rolled into AD-456b-2 — Architect call at AD-456b-2 draft).
- **HXI surface for tier-override grants.** Captain-issued temporary tier elevation (analog of `ClearanceGrant` at `earned_agency.py:80-89`) for credential access. Deferred to AD-456c-3.
- **Enterprise RBAC over secret namespaces / SSO over policy management / federated credential vaults.** *(Commercial)* — extension point only; v1's `min_tier` + `_tier_enforcement` seam is the plug-in point where commercial overlays (Vault adapters, HSM-backed stores, Entra-issued tier tokens) attach. Deferred to AD-456c-4.
- **Default-flip of `credential_tier_enforcement` to True.** v1 default False per Convention #14 + Convention #3. Deferred to AD-456c-5 once the fleet-wide `min_tier` coverage census shows that flipping to True will not break existing agents that haven't yet adopted `tier=` argument passing.
- **`RedTeamAgent` / `IntrospectionAgent` tier consumption.** Same boundary as AD-456b — these are policy consumers; AD-456c-6 wires them once AD-456c-2 (caller-side resolution) lands.
- **No new pool, agent, or module beyond the 1 new EventType + 1 new config field + the additive edits in `credential_store.py` + 1 new test file.**
- **No journal table or persistent tier-deny log.** `_log_access` already routes `denied_tier` events through `event_log`; that's sufficient v1 audit.
- **No change to `_resolve` chain** (config → env → store → CLI). Tier gate runs BEFORE `_resolve`; the chain is unchanged.
- **No change to `rotate()` / `_emit_rotated()` / cache TTL semantics.**
- **No change to `available()` / `list_credentials()`.** Both call `get` internally with `requester="availability_check"`; with `_tier_enforcement=True` and a spec that has `min_tier`, both will return False / non-availability. Test #11 locks this — operator-facing introspection respects the tier gate, which is correct security posture (no information leak about the existence of restricted credentials beyond what `list_credentials` already exposes via `name`).

---

## Verified Against Codebase (HEAD post-Wave-55, `557316e`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `CredentialSpec` dataclass | `src/probos/credential_store.py` | 22 | `class CredentialSpec:` |
| `CredentialSpec.allowed_departments` (sibling field — append point for `min_tier`) | `src/probos/credential_store.py` | 30 | `allowed_departments: list[str] \| None = None  # None = unrestricted` |
| `CredentialSpec.description` (last existing field) | `src/probos/credential_store.py` | 31 | `description: str = ""` |
| `CredentialStore` class | `src/probos/credential_store.py` | 34 | `class CredentialStore:` |
| `CredentialStore.__init__` (new `_tier_enforcement` insertion point) | `src/probos/credential_store.py` | 41-60 | `def __init__(self, config: Any = None, ... emit_event: Any \| None = None,)` |
| `CredentialStore.register` (mirror target for spec updates) | `src/probos/credential_store.py` | 84 | `def register(self, spec: CredentialSpec) -> None:` |
| `CredentialStore.get` signature (insertion point for `tier=` kwarg) | `src/probos/credential_store.py` | 182-188 | `def get(self, name: str, *, requester: str = "unknown", department: str \| None = None,) -> str \| None:` |
| `CredentialStore.get` department-deny path (mirror target — tier check goes immediately after) | `src/probos/credential_store.py` | 195-202 | `if spec.allowed_departments is not None and department:` … `self._log_access(name, requester, "denied_department")` |
| `CredentialStore._resolve` | `src/probos/credential_store.py` | 227 | `def _resolve(self, spec: CredentialSpec) -> str \| None:` |
| `CredentialStore._log_access` | `src/probos/credential_store.py` | 277 | `def _log_access(self, name: str, requester: str, source: str) -> None:` |
| `CredentialStore._emit_event` field (existing AD-456 emit channel) | `src/probos/credential_store.py` | 56 | `self._emit_event = emit_event` |
| `CredentialStore.available` (calls `get` internally — test #11 anchor) | `src/probos/credential_store.py` | 294 | `def available(self, name: str) -> bool:` |
| `runtime.credential_store` attribute | `src/probos/runtime.py` | 317 | `self.credential_store = CredentialStore(` |
| AD-456 finalize block (insertion target — new wiring goes after `_emit_event` line) | `src/probos/startup/finalize.py` | 1249-1267 | `# AD-456: Security Infrastructure` … `credential_store._emit_event = runtime.emit_event` |
| AD-456 EgressPolicy wiring (sibling — new wiring goes BEFORE this block) | `src/probos/startup/finalize.py` | 1269 | `if config.security_infra.egress_enabled:` |
| `SecurityInfraConfig` Pydantic class | `src/probos/config.py` | 1450 | `class SecurityInfraConfig(BaseModel):` |
| `SecurityInfraConfig.egress_active_enforcement` (sibling — append point) | `src/probos/config.py` | 1471 | `egress_active_enforcement: bool = False` |
| `EventType.SANDBOX_CAPABILITY_DENIED` (insertion-anchor sibling — line above) | `src/probos/events.py` | 212 | `SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b` |
| `EventType.VERIFICATION_PASSED` (insertion-anchor sibling — line below) | `src/probos/events.py` | 213 | `VERIFICATION_PASSED = "verification_passed"  # AD-528` |
| `AgencyLevel` enum (string values used by `_AGENCY_ORDER`) | `src/probos/earned_agency.py` | 11-15 | `class AgencyLevel(str, Enum):` … `REACTIVE = "reactive"` … `UNRESTRICTED = "unrestricted"` |
| `_TIER_ORDER` precedent (mirror target for `_AGENCY_ORDER` shape) | `src/probos/earned_agency.py` | 90-95 | `_TIER_ORDER: dict[RecallTier, int] = { ... }` |
| `agency_from_rank` helper (consumed by future AD-456c-2; NOT used in v1) | `src/probos/earned_agency.py` | 173-180 | `def agency_from_rank(rank: Rank) -> AgencyLevel:` |
| Existing AD-456 test file (no modification) | `tests/test_ad456_security_infrastructure.py` | — | passes at HEAD |
| Existing AD-456b test file (no modification) | `tests/test_ad456b_runtime_sandboxing.py` | — | passes at HEAD |
| Existing CredentialStore test file (no modification) | `tests/test_credential_store.py` | — | passes at HEAD |

`CredentialSpec.min_tier`, `CredentialStore._tier_enforcement`, `CredentialStore.set_tier_enforcement`, `CredentialStore._emit_tier_denied`, `_AGENCY_ORDER`, `EventType.CREDENTIAL_TIER_DENIED`, `SecurityInfraConfig.credential_tier_enforcement`, `tests/test_ad456c_per_tier_credentials.py` — all greenfield, verified zero hits at HEAD `557316e`.

---

## Implementation

### Section 0 — Event Type

**File:** `src/probos/events.py`

`SEARCH` block (the AD-456b sandbox events plus their immediate context, lines 210-213):
```python
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
    VERIFICATION_PASSED = "verification_passed"  # AD-528
```

`REPLACE`:
```python
    AUDIT_RECORDED = "audit_recorded"  # AD-456
    SANDBOX_LIMIT_EXCEEDED = "sandbox_limit_exceeded"  # AD-456b
    SANDBOX_CAPABILITY_DENIED = "sandbox_capability_denied"  # AD-456b
    CREDENTIAL_TIER_DENIED = "credential_tier_denied"  # AD-456c
    VERIFICATION_PASSED = "verification_passed"  # AD-528
```

---

### Section 1 — `SecurityInfraConfig` extension

**File:** `src/probos/config.py`

`SEARCH` block (the AD-456b transitional flag + trailing class boundary, lines 1467-1472):
```python
    # AD-456b: Egress active enforcement (v1 default False — preserves AD-456
    # consultation-only behavior on existing deployments; flip to True at upgrade
    # time after reviewing allowlist coverage. AD-456b-7 will flip default to True
    # once fleet-wide allowlist coverage is verified.).
    egress_active_enforcement: bool = False
```

`REPLACE`:
```python
    # AD-456b: Egress active enforcement (v1 default False — preserves AD-456
    # consultation-only behavior on existing deployments; flip to True at upgrade
    # time after reviewing allowlist coverage. AD-456b-7 will flip default to True
    # once fleet-wide allowlist coverage is verified.).
    egress_active_enforcement: bool = False

    # AD-456c: Per-tier credential lookup gate (v1 default False — preserves
    # AD-456 ungated-lookup behavior on existing deployments; flip to True at
    # upgrade time after reviewing per-spec ``min_tier`` coverage. AD-456c-5
    # will flip default to True once fleet-wide ``min_tier`` coverage is
    # verified AND caller-side ``tier=`` argument propagation (AD-456c-2)
    # has landed in all production credential-using agent paths.).
    credential_tier_enforcement: bool = False
```

---

### Section 2 — `CredentialStore` per-tier gate

**File:** `src/probos/credential_store.py`

#### Section 2a — `CredentialSpec.min_tier` field

`SEARCH` block (the `CredentialSpec` body, lines 21-31):
```python
@dataclass
class CredentialSpec:
    """Defines how to resolve a credential."""

    name: str  # e.g., "github", "discord", "llm_api"
    config_key: str | None = None  # system.yaml dot-path, e.g., "channels.discord.token"
    env_var: str | None = None  # e.g., "GH_TOKEN"
    env_var_aliases: list[str] = field(default_factory=list)  # e.g., ["GITHUB_TOKEN"]
    cli_command: list[str] | None = None  # e.g., ["gh", "auth", "token"]
    allowed_departments: list[str] | None = None  # None = unrestricted
    description: str = ""
```

`REPLACE`:
```python
@dataclass
class CredentialSpec:
    """Defines how to resolve a credential."""

    name: str  # e.g., "github", "discord", "llm_api"
    config_key: str | None = None  # system.yaml dot-path, e.g., "channels.discord.token"
    env_var: str | None = None  # e.g., "GH_TOKEN"
    env_var_aliases: list[str] = field(default_factory=list)  # e.g., ["GITHUB_TOKEN"]
    cli_command: list[str] | None = None  # e.g., ["gh", "auth", "token"]
    allowed_departments: list[str] | None = None  # None = unrestricted
    # AD-456c: minimum Earned Agency tier required to read this credential.
    # String matches ``probos.earned_agency.AgencyLevel.value`` —
    # ``"reactive"`` (Ensign) / ``"suggestive"`` (Lieutenant) /
    # ``"autonomous"`` (Commander) / ``"unrestricted"`` (Senior). Default
    # ``None`` = no tier gate (preserves AD-456 v1 ungated-lookup behavior).
    # Only enforced when ``CredentialStore._tier_enforcement`` is True (set
    # at finalize via ``config.security_infra.credential_tier_enforcement``).
    min_tier: str | None = None
    description: str = ""
```

#### Section 2b — Module-level ordering map

`SEARCH` block (the `CredentialSpec` close + `CredentialStore` opening, must locate the gap between the two classes — lines 33-35 after Section 2a applied):
```python


class CredentialStore:
    """Ship's Computer service -- centralized credential resolution.
```

`REPLACE`:
```python


# AD-456c: Earned Agency tier ordinal map. Mirrors ``_TIER_ORDER`` shape from
# ``probos.earned_agency`` (line 90) but locally defined to avoid importing
# the full ``earned_agency`` module surface into credential_store. Unknown
# tier strings resolve to ``-1`` via ``.get(name, -1)`` — sentinel for deny
# when ``_tier_enforcement`` is True (test #12 locks this).
_AGENCY_ORDER: dict[str, int] = {
    "reactive": 0,        # Ensign
    "suggestive": 1,      # Lieutenant
    "autonomous": 2,      # Commander
    "unrestricted": 3,    # Senior
}


class CredentialStore:
    """Ship's Computer service -- centralized credential resolution.
```

#### Section 2c — `__init__` adds `_tier_enforcement` instance attribute

`SEARCH` block (the existing `__init__` body, lines 49-61):
```python
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

`REPLACE`:
```python
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
        # AD-456c: per-tier credential lookup gate. Default False preserves
        # AD-456 v1 ungated-lookup behavior; finalize flips to True when
        # ``config.security_infra.credential_tier_enforcement`` is set.
        self._tier_enforcement: bool = False
        self._register_builtins()
```

#### Section 2d — `set_tier_enforcement` method

`SEARCH` block (the `register` method head — `set_tier_enforcement` inserts immediately before, lines 83-86):
```python
    def register(self, spec: CredentialSpec) -> None:
        """Register a credential spec. Extensions can add their own."""
        self._specs[spec.name] = spec
```

`REPLACE`:
```python
    def set_tier_enforcement(self, enabled: bool) -> None:
        """AD-456c: Toggle per-tier credential lookup gate.

        When enabled, ``get(...)`` consults ``CredentialSpec.min_tier`` and
        the caller-supplied ``tier`` kwarg; specs with ``min_tier=None``
        remain ungated. When disabled (the v1 default), the tier check is a
        no-op regardless of any ``min_tier`` settings — AD-456 v1
        ungated-lookup behavior is preserved bit-for-bit.

        Wired from ``startup/finalize.py`` based on
        ``config.security_infra.credential_tier_enforcement``.
        """
        self._tier_enforcement = bool(enabled)

    def register(self, spec: CredentialSpec) -> None:
        """Register a credential spec. Extensions can add their own."""
        self._specs[spec.name] = spec
```

#### Section 2e — `get(...)` tier-gate block + `tier=` kwarg

`SEARCH` block (the existing `get` signature + spec lookup + department check, lines 182-205):
```python
    def get(
        self,
        name: str,
        *,
        requester: str = "unknown",
        department: str | None = None,
    ) -> str | None:
        """Resolve a credential by name. Returns None if not available."""
        spec = self._specs.get(name)
        if not spec:
            logger.warning("CredentialStore: unknown credential '%s'", name)
            return None

        # Department access check
        if spec.allowed_departments is not None and department:
            if department not in spec.allowed_departments:
                logger.warning(
                    "CredentialStore: department '%s' denied access to '%s'",
                    department, name,
                )
                self._log_access(name, requester, "denied_department")
                return None

        # Check cache
        cached = self._cache.get(name)
```

`REPLACE`:
```python
    def get(
        self,
        name: str,
        *,
        requester: str = "unknown",
        department: str | None = None,
        tier: str | None = None,
    ) -> str | None:
        """Resolve a credential by name. Returns None if not available.

        AD-456c: When ``CredentialStore._tier_enforcement`` is True AND the
        spec carries a ``min_tier``, ``tier`` (Earned Agency level value —
        ``"reactive"``/``"suggestive"``/``"autonomous"``/``"unrestricted"``)
        must satisfy the floor or the lookup is denied. When enforcement is
        False (v1 default), ``tier`` is ignored and AD-456 ungated-lookup
        behavior is preserved.
        """
        spec = self._specs.get(name)
        if not spec:
            logger.warning("CredentialStore: unknown credential '%s'", name)
            return None

        # Department access check (AD-395)
        if spec.allowed_departments is not None and department:
            if department not in spec.allowed_departments:
                logger.warning(
                    "CredentialStore: department '%s' denied access to '%s'",
                    department, name,
                )
                self._log_access(name, requester, "denied_department")
                return None

        # AD-456c: Per-tier access check (defense in depth — runs AFTER
        # department check). Only consulted when enforcement is on AND the
        # spec carries a min_tier; otherwise this block is a no-op.
        if self._tier_enforcement and spec.min_tier is not None:
            required_order = _AGENCY_ORDER[spec.min_tier]
            actual_order = _AGENCY_ORDER.get(tier, -1) if tier is not None else -1
            if actual_order < required_order:
                logger.warning(
                    "CredentialStore: tier '%s' denied access to '%s' "
                    "(required min_tier=%s)",
                    tier, name, spec.min_tier,
                )
                self._emit_tier_denied(
                    name=name,
                    requester=requester,
                    requested_tier=tier,
                    required_tier=spec.min_tier,
                )
                self._log_access(name, requester, "denied_tier")
                return None

        # Check cache
        cached = self._cache.get(name)
```

#### Section 2f — `_emit_tier_denied` helper

`SEARCH` block (the existing `_emit_rotated` helper + the trailing AD-456 marker, lines 250-265):
```python
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

`REPLACE`:
```python
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

    def _emit_tier_denied(
        self,
        *,
        name: str,
        requester: str,
        requested_tier: str | None,
        required_tier: str,
    ) -> None:
        """AD-456c: Emit ``CREDENTIAL_TIER_DENIED`` on a tier-gated denial.

        Log-and-degrade tier — emit failures must NOT propagate; the deny
        decision is already returned to the caller and the access has been
        logged via ``_log_access``.
        """
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType
            self._emit_event(
                EventType.CREDENTIAL_TIER_DENIED,
                {
                    "name": name,
                    "requester": requester,
                    "requested_tier": requested_tier,
                    "required_tier": required_tier,
                },
            )
        except Exception:
            logger.warning(
                "AD-456c: CREDENTIAL_TIER_DENIED emit failed (name=%s, requester=%s)",
                name, requester, exc_info=True,
            )
```

---

### Section 3 — `startup/finalize.py` wiring

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (the AD-456 CredentialStore extension block, lines 1249-1267):
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
```

`REPLACE`:
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

    # AD-456c: Per-tier credential lookup gate. Default False preserves
    # AD-456 ungated-lookup behavior; Captain flips at upgrade time after
    # reviewing per-spec min_tier coverage AND caller-side tier= argument
    # propagation (AD-456c-2).
    if (
        credential_store is not None
        and config.security_infra.credential_tier_enforcement
    ):
        credential_store.set_tier_enforcement(True)
        logger.info("AD-456c: CredentialStore per-tier gate enabled")
```

---

### Section 4 — Tests

**File:** `tests/test_ad456c_per_tier_credentials.py` (NEW)

13 tests:

```python
"""AD-456c: Per-tier credential lookup tests."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from probos.credential_store import (
    CredentialSpec,
    CredentialStore,
    _AGENCY_ORDER,
)
from probos.events import EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(*, with_emit: bool = True) -> tuple[CredentialStore, MagicMock]:
    """Build a CredentialStore with no config/event_log and an attached emit."""
    emit = MagicMock()
    store = CredentialStore(emit_event=emit if with_emit else None)
    return store, emit


def _set_env(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)


# ---------------------------------------------------------------------------
# Spec defaults / backwards compat
# ---------------------------------------------------------------------------

def test_credential_spec_default_min_tier_is_none() -> None:
    """New ``min_tier`` field defaults to None — preserves AD-395/AD-456 contract."""
    spec = CredentialSpec(name="custom", env_var="CUSTOM_TOKEN")
    assert spec.min_tier is None


def test_register_with_min_tier_persists_on_spec() -> None:
    store, _ = _make_store(with_emit=False)
    spec = CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    store.register(spec)

    assert store._specs["ops_secret"].min_tier == "autonomous"


def test_existing_builtin_specs_have_no_min_tier() -> None:
    """github / discord / llm_api are ungated v1 — flipping defaults is AD-456c-N."""
    store, _ = _make_store(with_emit=False)

    for name in ("github", "discord", "llm_api"):
        assert store._specs[name].min_tier is None, (
            f"built-in spec {name!r} unexpectedly has min_tier — "
            "AD-456c v1 must preserve AD-395 ungated defaults"
        )


def test_set_tier_enforcement_toggles_flag() -> None:
    store, _ = _make_store(with_emit=False)
    assert store._tier_enforcement is False

    store.set_tier_enforcement(True)
    assert store._tier_enforcement is True

    store.set_tier_enforcement(False)
    assert store._tier_enforcement is False


# ---------------------------------------------------------------------------
# Backwards compat — enforcement off
# ---------------------------------------------------------------------------

def test_get_no_min_tier_no_enforcement_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default-everything: spec ungated, enforcement off. AD-456 baseline."""
    store, _ = _make_store(with_emit=False)
    store.register(CredentialSpec(name="custom", env_var="CUSTOM_TOKEN"))
    _set_env(monkeypatch, "CUSTOM_TOKEN", "value-1")

    assert store.get("custom", requester="t") == "value-1"


def test_get_min_tier_enforcement_off_resolves_regardless_of_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec carries min_tier but enforcement is OFF → tier is ignored.

    Locks AD-456c v1 default-False migration safety: deployments may register
    specs with min_tier before flipping the enforcement flag.
    """
    store, emit = _make_store()
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")

    # Caller passes a too-low tier — but enforcement is off, so resolves.
    assert store.get("ops_secret", requester="t", tier="reactive") == "ops-value"
    # No CREDENTIAL_TIER_DENIED emitted on the no-op path.
    assert not any(
        c.args and c.args[0] == EventType.CREDENTIAL_TIER_DENIED
        for c in emit.call_args_list
    )


# ---------------------------------------------------------------------------
# Enforcement on — gate semantics
# ---------------------------------------------------------------------------

def test_get_min_tier_enforcement_on_allows_equal_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="autonomous") == "ops-value"


def test_get_min_tier_enforcement_on_allows_higher_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="unrestricted") == "ops-value"


def test_get_min_tier_enforcement_on_denies_lower_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="t", tier="suggestive") is None


def test_get_min_tier_enforcement_on_no_tier_passed_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: when enforcement is on and the spec is gated, caller MUST
    pass ``tier=`` or the lookup is denied. Locks the AD-456c-2 forcing
    function — caller-side tier propagation is mandatory before any
    production deployment flips the flag to True.
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # tier=None (default) → deny.
    assert store.get("ops_secret", requester="t") is None


# ---------------------------------------------------------------------------
# Event + audit emission
# ---------------------------------------------------------------------------

def test_credential_tier_denied_event_emitted_on_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, emit = _make_store()
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    assert store.get("ops_secret", requester="ensign-007", tier="reactive") is None

    denied_calls = [
        c for c in emit.call_args_list
        if c.args and c.args[0] == EventType.CREDENTIAL_TIER_DENIED
    ]
    assert len(denied_calls) == 1
    payload = denied_calls[0].args[1]
    assert payload == {
        "name": "ops_secret",
        "requester": "ensign-007",
        "requested_tier": "reactive",
        "required_tier": "autonomous",
    }


# ---------------------------------------------------------------------------
# Fail-safe — unknown tier strings + introspection respect gate
# ---------------------------------------------------------------------------

def test_unknown_tier_string_denies_when_enforcement_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown tier strings (operator typo, future-tier values) resolve to
    ordinal -1 via ``_AGENCY_ORDER.get(name, -1)`` and are denied. Locks
    the fail-safe contract — never grant access on garbled tier input.
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="suggestive")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # Sanity: unknown tier maps to -1 sentinel.
    assert _AGENCY_ORDER.get("captain-mode", -1) == -1
    # And lookup is denied.
    assert store.get("ops_secret", requester="t", tier="captain-mode") is None


def test_available_respects_tier_gate_when_enforcement_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``CredentialStore.available`` calls ``get`` internally with
    ``requester='availability_check'`` and no ``tier`` kwarg. With
    enforcement on and a spec carrying ``min_tier``, ``available`` MUST
    return False (no information leak about a restricted credential's
    underlying resolvability beyond the bare ``list_credentials`` name
    surface).
    """
    store, _ = _make_store(with_emit=False)
    store.register(
        CredentialSpec(name="ops_secret", env_var="OPS_SECRET", min_tier="autonomous")
    )
    _set_env(monkeypatch, "OPS_SECRET", "ops-value")
    store.set_tier_enforcement(True)

    # Without enforcement, available would return True (env var resolves).
    # With enforcement on AND no tier passed, get() denies → available False.
    assert store.available("ops_secret") is False
```

---

## Tracking

- `PROGRESS.md` — prepend AD-456c CLOSED entry (Era V).
- `docs/development/roadmap.md` — flip the AD-456c row to ✅ shipped under the AD-456 cluster; add deferral entries:
  - **AD-456c-1**: Per-secret scope policy (read/write/rotate).
  - **AD-456c-2**: Caller-side automatic `tier=` resolution from `runtime.crew_profile_store` at every existing `runtime.credential_store.get(...)` call site.
  - **AD-456c-3**: HXI Captain-issued temporary tier-elevation grants (analog of `ClearanceGrant`).
  - **AD-456c-4** *(Commercial)*: RBAC over secret namespaces / SSO over policy management / federated credential vault adapters (Vault, HSM, Entra-issued tier tokens) — extension point on the `CredentialStore.set_tier_enforcement` + `CredentialSpec.min_tier` seam.
  - **AD-456c-5**: Default-flip of `credential_tier_enforcement` to True once AD-456c-2 caller wiring is fleet-complete.
  - **AD-456c-6**: `RedTeamAgent` / `IntrospectionAgent` tier consumption.
- `DECISIONS.md` — prepend AD-456c entry at the top of Era V.

---

## Acceptance Criteria

- All 13 new tests in `tests/test_ad456c_per_tier_credentials.py` pass.
- All 16 existing AD-456 tests in `tests/test_ad456_security_infrastructure.py` pass unchanged.
- All 12 existing AD-456b tests in `tests/test_ad456b_runtime_sandboxing.py` pass unchanged.
- All existing tests in `tests/test_credential_store.py` pass unchanged.
- Full gate (`pytest tests/ -q -n 8 --dist=loadfile`) net-passes at **11252** (baseline 11239 + 13 new), ceiling **11253** (one fixture-split discovery permitted per Wave-30/39/41/42/53 precedent).
- No existing-symbol modification beyond the additive `tier=` kwarg on `CredentialStore.get` (which has a default value, preserving every existing call site).
- `_log_access` audit chain unchanged for existing paths; new `denied_tier` source value is emitted only on the new tier-deny path.
- `runtime.credential_store` instance is the same object created at `runtime.py:317`; no re-instantiation.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
