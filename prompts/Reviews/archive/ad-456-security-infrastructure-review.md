# Review: AD-456 — Security Infrastructure (Secrets / Egress / Audit)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ❌ **Not Ready** — `SecretsManager` duplicates the existing `CredentialStore` (AD-395 at `src/probos/credential_store.py:32`). Five-minute pre-flight grep would have caught this; the prompt's own footer didn't include `grep -rn "credential_store\|CredentialStore" src/probos/`. Remediation: Section 1 must either extend CredentialStore (preferred) or document a clear orthogonality (lookup-chain vs persistent-rotation) the prompt body does not currently establish.

EgressPolicy and AuditLog v1 designs are clean. The dispatch's pre-flagged concern about "EgressPolicy consultation-only being theater dressed as deferral" is borderline — EgressPolicy emits real `EGRESS_BLOCKED` events under the deny-by-default path, which is observable signal even without active interception. Acceptable for v1.

---

## Required (must fix before building)

### 1. `SecretsManager` duplicates existing `CredentialStore` (AD-395)

Verified phantom — the prompt did NOT grep for existing credential resolution surfaces:

```
grep -n "class CredentialStore" src/probos/credential_store.py
  32: class CredentialStore:

grep -n "CredentialStore" src/probos/runtime.py
  61: from probos.credential_store import CredentialStore
  185: credential_store: CredentialStore
  317: self.credential_store = CredentialStore(
```

`CredentialStore` (AD-395, in production today) does:
- Centralizes credential lookup (✅ same as proposed `SecretsManager.get()`)
- Resolution chain: explicit config → environment variable → CLI tool → None (✅ richer than proposed `SecretsManager`)
- Department access control (`allowed_departments` per spec) — `SecretsManager` has no equivalent
- Caching with TTL (`cache_ttl=300.0`) — `SecretsManager` has no caching

`SecretsManager` adds two things `CredentialStore` lacks:
1. **Persistent rotation** — `rotate(key, value)` writes to JSON store atomically.
2. **`SECRET_ROTATED` event emission** — observability surface.

These are real value-adds. But shipping `SecretsManager` as a parallel class duplicates 80% of `CredentialStore`'s functionality and creates two competing credential surfaces — exactly the DRY violation the engineering principles forbid.

**Action:** Pick one of three resolutions:

- **(a) Extend `CredentialStore`** — add `rotate(name: str, value: str) -> bool` method to the existing class; emit `SECRET_ROTATED` from there. Add a `secrets.json` persistence layer as a new resolution-chain step (priority below env-var; survives across resets). Drop the `SecretsManager` class wholesale; the prompt body already contains the rotation logic, just relocate it.

- **(b) Define clear orthogonality.** `SecretsManager` becomes "persistent secrets store with rotation auditing"; `CredentialStore` remains "lookup-chain for service credentials." The prompt body must spell this out explicitly with examples of when an operator uses one vs the other. AD-456 currently says "single-source-of-truth for secret reads" — that contradicts the existing `CredentialStore`.

- **(c) Defer `SecretsManager` wholesale to AD-456c.** Land EgressPolicy and AuditLog only in v1; bring SecretsManager back when the rotation use case is exercised (today there's no consumer of rotation).

**Recommended:** (a). Preserves the existing `CredentialStore` department-access control and caching; adds rotation as a method on the established surface. Single source of truth maintained.

### 2. `SecretsManager.ENV_PREFIX = "PROBOS_"` is broader than the existing convention

The prompt's footer claims:
> AD-456 SecretsManager `ENV_PREFIX = "PROBOS_"` chosen to match the existing `PROBOS_LLM_URL` env-var convention

Verified — the live convention is **per-purpose env var names**, not a uniform `PROBOS_*` prefix:

```
grep -n "PROBOS_" src/probos/config.py | head -10
  175: url = os.environ.get("PROBOS_LLM_URL")
  1263: token: str = ""  # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
  1539: description="Enable NATS event bus. Overridden by PROBOS_NATS_ENABLED env var.",
  1546: env_val = os.environ.get("PROBOS_NATS_ENABLED")
```

Three existing env vars use `PROBOS_*` prefix — but `CredentialStore` registers `LLM_API_KEY` (no prefix) for the `llm_api` credential at `credential_store.py:66`. The existing convention is mixed: bespoke Docker overrides use `PROBOS_*`; legacy/external API keys do not.

If Required #1 resolves toward (a) extending `CredentialStore`, this issue dissolves — credential lookup follows whatever env_var the spec declares.

If Required #1 resolves toward (b) orthogonal surfaces, the `ENV_PREFIX = "PROBOS_"` claim needs to be documented as AD-456-specific (does NOT govern existing CredentialStore env_vars).

**Action:** resolve as part of Required #1.

### 3. EgressPolicy `_DEFAULT_ALLOWLIST` collides with HttpFetchAgent's existing per-domain rate limiting

`HttpFetchAgent` has per-domain rate-limit state at `agents/http_fetch.py:34`. AD-456's EgressPolicy v1 ships a parallel allow/deny surface but does NOT consume the existing per-domain state.

Two surfaces operating on the same data (outbound URLs) without a clear seam invites drift. Either:
- Document explicitly that AD-456b will integrate EgressPolicy.is_allowed() as a pre-check inside HttpFetchAgent's rate-limit flow.
- Or note the orthogonality (per-domain rate limits = throughput control; egress allow/deny = security posture).

The prompt's "What This Does NOT Change" says "agents/http_fetch.py is unchanged. EgressPolicy is consultation-only in v1." That's correct but misses the explicit AD-456b integration plan. Add a one-line note: "AD-456b will wire `EgressPolicy.is_allowed(url)` as a pre-check in `HttpFetchAgent._domain_state` flow."

**Action:** add the AD-456b integration note to "What This Does NOT Change."

---

## Recommended

### 1. EgressPolicy `deny_by_default=False` makes v1 consultation-only path silent

When `deny_by_default=False` (the v1 default per `SecurityInfraConfig.egress_deny_by_default: bool = False`), only explicit denylist hits emit `EGRESS_BLOCKED`. Operators who want to observe what their runtime is fetching get no signal until they configure denylist entries.

The dispatch's pre-flagged concern (EgressPolicy theater) bites here mildly. Mitigation options:

- **(a)** Add a `log_unknown: bool = True` field to EgressPolicy that emits an `EGRESS_OBSERVED` event (new EventType) on every unknown-host request — pure observability, no blocking.
- **(b)** Document that operators should set `deny_by_default=True` to get observability, accepting that this also blocks unknown hosts.
- **(c)** Accept the v1 silence and document — operators add denylist entries when they want signal.

Recommended **(c)** — keeps v1 narrow, no new EventType. AD-456b can layer an observability surface.

### 2. AuditLog `verify_chain()` is O(n) per call — document scaling

AuditLog stores entries in an in-memory list. `verify_chain()` re-derives every hash. After 10K entries this becomes slow. Document in "What This Does NOT Change":

- AD-456 v1 is suitable for short-lived audit windows (hours, not weeks).
- AD-456d (SQLite-persisted audit) will add incremental verification.

Operators need to know they can't keep 10M entries in `AuditLog.entries` and expect cheap verification.

### 3. `SecretsManager.rotate()` returns `False` when env-sourced — name is misleading

The method name `rotate` implies state mutation. But for env-sourced secrets the operator must update the env var externally; `rotate()` only emits an event. Returning `False` to signal "nothing rotated" is correct semantics, but a caller reading `if not secrets.rotate(...)` may interpret the result as failure.

Recommend renaming to `request_rotation` or splitting:
- `rotate(key, value)` — mutates store; raises if env-sourced.
- `notify_rotation(key)` — emits event without mutation; for env-sourced.

This is cosmetic if Required #1 resolves toward (a) — extending CredentialStore — because rotation semantics get rewritten anyway.

### 4. `AuditLog.verify_chain` doesn't validate `prior_hash` against the chain start

The chain-start guard `prior_hash == prior` works for sequential validation, but a tampered first entry whose `prior_hash != GENESIS_HASH` would slip past if the recomputed `entry_hash` happens to match.

Verified — the implementation does check `entry.prior_hash != prior` where `prior = self.GENESIS_HASH` initially. So the chain-start check is correct.

But the test plan's `test_audit_log_verify_chain_detects_tamper` only mutates `entries[1].detail`. Add a second tamper case: mutate `entries[0].prior_hash` to a non-GENESIS value. Boundary coverage gap.

### 5. Section 6 `runtime.secrets_manager = None` when disabled

Section 6 sets:

```python
if config.security_infra.secrets_enabled:
    runtime.secrets_manager = SecretsManager(...)
else:
    runtime.secrets_manager = None
```

This is the always-wired pattern from AD-459. Good — consumers can always check `if runtime.secrets_manager is not None`. ✅

But the same isn't applied uniformly: `SecretsManager`, `EgressPolicy`, and `AuditLog` all have separate config flags. If Required #1 resolves toward (a), the SecretsManager flag goes away (CredentialStore is always wired). For (b) orthogonal surfaces, keep the flags.

---

## Nits

### 1. Footer line drift on `runtime.emit_event`

Footer says line 775; actual is 785 (verified). Off by 10. Update.

### 2. AuditLog `entry_hash` uses `json.dumps(payload, sort_keys=True)` — note about float precision

`json.dumps` of `payload["timestamp"] = time.time()` may differ in trailing-precision across platforms. The hash chain assumes deterministic encoding. Float precision in `json.dumps` is consistent within Python 3.12 but not across language ports.

For v1 in-memory chain this doesn't matter. AD-456d (SQLite persistence) will need a more robust serialization. Document.

### 3. `SecretsManager._load()` returns nothing on first-call cache miss

The `_loaded` flag prevents repeated reads but doesn't expose a way to force-reload (e.g., after operator manually edits `secrets.json`). `reload()` method would be helpful in v1; AD-456c can add it.

### 4. Test 11 (`test_egress_policy_deny_by_default_blocks_unknown`) — verify emit fires

The test description says "emit fires" but the test plan doesn't show the assertion. Confirm the test asserts `mock_emit.call_count == 1`.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied (3 attributes)

`runtime.secrets_manager`, `runtime.egress_policy`, `runtime.audit_log` — all public.

But: collides with existing `runtime.credential_store` (AD-395 at `runtime.py:317`). See Required #1.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

`json` (stdlib), `hashlib` (stdlib), `urllib.parse` (stdlib), `os.replace` (stdlib atomic). No new pyproject deps.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

`EgressPolicy` v1 ships consultation-only; consumer wiring deferred to AD-456b. `RuntimeSandbox` deferred wholesale to AD-456b. ✅

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied

EgressPolicy doesn't intercept. AuditLog is additive. SecretsManager creates a NEW path (not gating an existing one), but it still violates DRY against CredentialStore — see Required #1.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 6 wires from `startup/finalize.py` (receives `runtime` directly). ✅

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Required #1 + #2

The footer is missing the critical grep:

```
grep -n "class CredentialStore" src/probos/credential_store.py
```

The prompt's verify-first pass missed the duplication. Required #1.

### No-theater discipline (Wave-5 convention #7) — ⚠️ Required #1

`SecretsManager` is documented as v1 real-work, but its existence is theater because it duplicates an existing in-production class. Either extend CredentialStore (Required #1 (a)) or defer (Required #1 (c)).

### TYPE_CHECKING cross-layer imports (Wave-6 note) — ✅ N/A

No cross-layer imports required.

### ASCII-only source comments (Wave-6 note) — ✅ Applied

Verified — no unicode arrows or em-dashes in source comments.

### Anchor-chain fallback (Wave-6 note) — ✅ Applied

Section 5 anchor chain terminates at `orders: OrdersConfig` (config.py:1593). ✅

### Section 0 EventTypes — ✅ Clean

`SECRET_ROTATED`, `EGRESS_BLOCKED`, `AUDIT_RECORDED` — all absent from `events.py`. No collision with other Wave 7 prompts.

### `security/__init__.py` extension (Wave 5 AD-455 precedent) — ✅ Documented

AD-456 explicitly does NOT modify `security/__init__.py` (single-line stub from AD-455). New modules are imported via dotted paths (`probos.security.secrets`, etc.). ✅

### `RuntimeSandbox` deferred wholesale — ✅ Documented

The dispatch flagged this as the no-theater move; the prompt explicitly defers it to AD-456b. ✅ AD-456 ships nothing under that capability name.

### Test plan — ✅ Comprehensive (14 tests)

Boundary coverage: env-var precedence, store-fallback, allowlist/denylist matching, deny-by-default, hash chain integrity, tamper detection.

---

## Verdict Summary

**Three blocking issues:**
1. `SecretsManager` duplicates existing `CredentialStore` (AD-395). Pick a resolution: extend, distinguish, or defer.
2. `ENV_PREFIX = "PROBOS_"` doesn't match the live convention (mixed). Resolve via Required #1.
3. EgressPolicy / HttpFetchAgent integration not documented (AD-456b plan needed).

**5 Recommended findings:** observability, scaling notes, naming clarity, test boundary, config flag uniformity.

**4 Nits:** cosmetic.

**Wave-5 conventions:** 5 of 7 cleanly applied; #6 (verify-first) and #7 (no-theater) need Required #1 resolution.

**Build-readiness after fix:** ~30 minutes architect time. Required #1 is the substantial rework. Recommended (a) extends `CredentialStore` — preserves AD-395's department access control + caching, adds rotation + persistence + `SECRET_ROTATED` emit. v1 ships 2 net-new security primitives (EgressPolicy, AuditLog) plus a CredentialStore extension. Cleaner narrative, no DRY violation.

**Recommended build order:** AD-456 second in Wave 7 (after AD-466), but only after Required #1 is resolved. If unresolved, defer AD-456 entirely until the duplication is settled.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — all 3 Required findings resolved cleanly; CredentialStore extension is non-breaking (additive keyword-only kwargs); EgressPolicy theater check resolved real-today (`deny_by_default=True` + EGRESS_BLOCKED emits to event_log).

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: SecretsManager duplicates CredentialStore | ✅ Resolved | Section 1+2 rewritten: extends `credential_store.py:32` CredentialStore. New ctor kwargs `store_path`, `emit_event` are keyword-only with defaults (verified non-breaking against existing `runtime.py:317` callsite). New methods `_load_store`, `_resolve_from_store`, `rotate`, `_emit_rotated` are additive. `_resolve` modification inserts the JSON-store step between env-aliases and CLI; existing return paths preserved. SecretsManager class dropped wholesale; no `runtime.secrets_manager` attribute. |
| R#2: ENV_PREFIX = "PROBOS_" collision | ✅ Resolved | Resolved by R#1: env-var resolution remains via existing `CredentialSpec.env_var` per-spec configuration. No global prefix introduced. The mixed live convention (`PROBOS_*` for Docker/NATS overrides; bespoke names for legacy keys) is preserved unchanged. |
| R#3: EgressPolicy / HttpFetchAgent integration not documented | ✅ Applied | "What This Does NOT Change" line 707 explicitly notes "AD-456b will wire `EgressPolicy.is_allowed(url)` as a pre-check in `HttpFetchAgent`'s request path." |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: deny_by_default default to True | ✅ Applied | Section 3 line 351 default flipped to `True`; Section 5 config `egress_deny_by_default: bool = True`; Test #11 asserts `mock_emit.call_count == 1` under default. |
| rec#2: AuditLog scaling note | ✅ Applied | Documented in "What This Does NOT Change". |
| rec#3: rotate() naming clarity | ✅ Applied | `_emit_rotated` payload includes a `persisted: bool` field; callers can distinguish persisted-rotation from rotation-requested-but-not-persisted (env-sourced or no-store-configured). |
| rec#4: AuditLog.verify_chain genesis-tamper test | ✅ Applied | Added as Test #14 (`test_audit_log_verify_chain_detects_genesis_tamper`). |
| rec#5: Section 6 always-wired uniformity | ✅ Applied | `runtime.credential_store` is always-wired (existing AD-395). EgressPolicy and AuditLog use always-wired `runtime.X = None` when disabled. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1: footer line drift | ✅ Applied | `runtime.emit_event` line corrected to 785. |
| nit#2: AuditLog hash float-precision note | ✅ Applied | Documented. |
| nit#3: SecretsManager._load reload | ✅ N/A | SecretsManager dropped; CredentialStore `_load_store()` is idempotent with `_store_loaded` flag. |
| nit#4: Test 11 emit assertion | ✅ Applied | Test #11 description explicitly asserts `mock_emit.call_count == 1`. |

### New Findings (introduced during revision)

None.

### Verified Against Revised Codebase Claims

- `class CredentialStore` at `credential_store.py:32` — confirmed.
- `__init__` signature accepts only existing positional args (`config`, `event_log`, `cache_ttl`); revision adds keyword-only `*, store_path, emit_event` — non-breaking. Verified by inspection of existing `runtime.py:317` call: `self.credential_store = CredentialStore(...)` with positional `config, event_log` only — works under the new signature.
- `runtime.credential_store` referenced ONLY in `runtime.py:61, 185, 317` (verified via grep). No other consumers; no breaking-change risk.
- `_resolve` method exists at `credential_store.py:119` (verified).
- EgressPolicy `EGRESS_BLOCKED` events emit via `runtime.emit_event` → routed to `event_log` (the standing audit consumer) plus IntentBus subscribers. Real consumer in v1 — events are logged to SQLite immediately. Not theater.
- `::1` IPv6 localhost addition to `_DEFAULT_ALLOWLIST` at line 319 — confirmed.
- `deny_by_default = True` at Section 3 line 351 and Section 5 line 594 — confirmed.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| AD-456 R#1 (extend CredentialStore option a) | ✅ Applied wholesale | No new SecretsManager class; CredentialStore extension is additive non-breaking. |
| EgressPolicy theater check | ✅ Applied | `deny_by_default=True` + `::1` allowlist + EGRESS_BLOCKED → event_log. Real signal today. |

### Hard-Stop Audit

The dispatch flagged: "If AD-456 EgressPolicy events still have no consumer in v1, surface — even with deny_by_default=True and events firing, theater can persist if no one reads the output."

Verified: `runtime.emit_event` routes events to `event_log` (SQLite append-only audit log). The event_log is the standing audit consumer — operators query it for security review. EGRESS_BLOCKED events flowing to event_log = real consumer. ✅ Not theater.

The dispatch also flagged: "AD-456 CredentialStore extension introduced any breaking change to AD-395 existing consumers — surface immediately." Verified: only positional args (`config`, `event_log`, `cache_ttl`) are preserved; new kwargs are keyword-only with defaults. Existing call at `runtime.py:317` continues to work. ✅ No breaking change.

### Verdict

**✅ Approved.** Build-ready as AD-456 second in Wave 7 (after AD-466). The R#1 architectural decision (extend CredentialStore) was the substantial rework; all mechanical fixes applied cleanly.
