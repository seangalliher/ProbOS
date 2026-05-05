# WAVE 56 DISPATCH — AD-456c v1 Security Infrastructure: Per-Tier Credential Lookup

**Wave id:** 56
**Single AD:** AD-456c
**Closes:** #399
**Baseline test count:** 11239 (Wave 55, commit `557316e`) → expected **11252** (+13 net), ceiling **+14**
**HEAD at draft:** post-Wave-55 (`557316e`, working tree clean)

## Summary

AD-456 v1 (Wave 7) shipped three of four security-infrastructure layers (Secrets / Egress / Audit) and deferred the fourth (Runtime Sandboxing → AD-456b, shipped Wave 55). Cross-cutting that work, the AD-456 review identified a follow-up policy seam: every credential lookup currently routes through `CredentialStore.get(name, requester=, department=)` without consulting the agent's Earned Agency tier. The roadmap entry (`docs/development/roadmap.md:4146`) contracts AD-456c to plumb the seam:

> "Secrets Manager credential lookup gated by Earned Agency tier. Ensign-level agents get no direct credential access; Commander+ agents can request scoped secrets. **v1 ships flat access model.**"

AD-456c v1 ships:

1. **`CredentialSpec.min_tier: str | None = None`** — additive field on the existing dataclass at `credential_store.py:22-31`. Default None preserves every existing built-in (`github`, `discord`, `llm_api` ungated). Operator extensions register with `min_tier="autonomous"` etc.

2. **`CredentialStore._tier_enforcement: bool = False`** + **`set_tier_enforcement(enabled)`** instance method. Mirrors AD-456b's `egress_active_enforcement` transitional-flag posture exactly. Default False; finalize flips to True only when `config.security_infra.credential_tier_enforcement=True` (also default False).

3. **`CredentialStore.get(...)` adds optional `tier: str | None = None` kwarg** + a tier-gate block AFTER the existing department gate (defense in depth). When enforcement is off OR `spec.min_tier is None`, the block is a no-op. When enforcement is on AND the spec is gated, an `_AGENCY_ORDER` ordinal comparison decides; on deny, emit `CREDENTIAL_TIER_DENIED` + log to `event_log` via existing `_log_access` chain + return None.

4. **Module-level `_AGENCY_ORDER` ordering map** — `reactive=0` / `suggestive=1` / `autonomous=2` / `unrestricted=3`. Mirrors `_TIER_ORDER` shape from `earned_agency.py:90`. Local copy avoids importing the full `earned_agency` module surface (Law of Demeter).

5. **`EventType.CREDENTIAL_TIER_DENIED`** — single new enum value, inserted adjacent to AD-456 / AD-456b sandbox events.

6. **`SecurityInfraConfig.credential_tier_enforcement: bool = False`** — single new Pydantic field, appended after `egress_active_enforcement`.

7. **`startup/finalize.py`** — single new if-block calling `credential_store.set_tier_enforcement(True)` when the config flag is set, sited immediately after the existing AD-456 `credential_store._emit_event = runtime.emit_event` extension.

5 sections + Section 0 EventType, 3 source-edit files (`events.py`, `config.py`, `credential_store.py`, `startup/finalize.py` — `credential_store.py` carries six cohesive sub-edits), 1 new test file (13 tests).

Caller-side automatic tier resolution from `runtime.crew_profile_store` at the ~N production credential call sites is explicitly deferred to AD-456c-2 (DLog #4 forcing function). Per-secret scope policy (read/write/rotate split), HXI Captain-issued temporary tier-elevation grants, RedTeamAgent/IntrospectionAgent consumption, default-flip of the enforcement flag, and commercial overlays (Vault adapters, HSM-backed stores, Entra-issued tier tokens) are pre-deferred at the prompt level to AD-456c-1 / -3 / -6 / -5 / -4 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — Mirror AD-456b's transitional-flag posture exactly.** Convention #14 + #3 + Wave 55 precedent: default-False on a transitional flag. `egress_active_enforcement` (Wave 55, AD-456b) is the immediate sibling pattern; `credential_tier_enforcement` follows the same naming, default, comment shape, and finalize-block conditional. Deviation from the established sibling pattern would burn review cycles for nothing — pre-applied. Forcing function: AD-456c-5 flips default to True once fleet-wide caller-side `tier=` propagation (AD-456c-2) lands.

- **DLog #2 — Instance attribute (`self._tier_enforcement`), NOT ClassVar.** AD-456b's `HttpFetchAgent._egress_policy` is ClassVar because `HttpFetchAgent` has many pool members sharing the same agent class. `CredentialStore` is a singleton owned by `runtime.credential_store` (`runtime.py:317`); there's exactly one instance per process. Instance attribute + `set_tier_enforcement(enabled)` instance method is cleaner than mimicking the ClassVar shape and keeps the singleton's state co-located with its other instance state (`_store_path`, `_emit_event`, `_specs`, `_cache`).

- **DLog #3 — `min_tier: str | None = None` (string) NOT `AgencyLevel | None`.** Three reasons:
  1. Avoids importing `probos.earned_agency` into `probos.credential_store`. `earned_agency` already imports `probos.crew_profile.Rank` (`earned_agency.py:7`); credential_store is a primitive — should not depend on the rank/agency module's full surface.
  2. Roadmap deferral language ("v1 ships flat access model") suggests the gate stays string-based even at v2 — Pydantic config / YAML / operator-supplied spec files all serialize tiers as strings.
  3. `AgencyLevel` is `(str, Enum)` (`earned_agency.py:11`) — the `.value` IS the string. Callers who want type-safety can pass `agency_from_rank(rank).value`; callers who don't need it pass `"autonomous"` literal.

- **DLog #4 — Caller-side `tier=` resolution is OUT OF SCOPE in this AD (AD-456c-2).** Every existing call site `runtime.credential_store.get(name, requester=...)` continues to function unchanged. With `_tier_enforcement=False` (the v1 default), the new `tier=` kwarg is dead code. The forcing function for AD-456c-2: ship the seam, Captain validates that ≥1 production agent path exercises `tier=` end-to-end, then the wide rollout (auto-resolution at every call site from `agency_from_rank(self._crew_profile.rank).value`) becomes specifiable as additive plumbing.

- **DLog #5 — Tier check runs AFTER department check (defense in depth).** Department is the cohort gate (AD-395, e.g., `allowed_departments=["security"]`); tier is the rank gate (AD-456c, e.g., `min_tier="autonomous"`). Both can apply — a credential might be readable only by Security Department AND only by Commander+ agents. Existing department-deny logs `denied_department` and returns None; new tier-deny logs `denied_tier` and returns None. Test #11 (`test_credential_tier_denied_event_emitted_on_deny`) locks the tier-emit shape; existing AD-395 tests already lock the department path.

- **DLog #6 — Fail-closed when `tier is None` AND enforcement on AND spec gated.** `_AGENCY_ORDER.get(tier, -1)` returns `-1` for `None` (and for any unknown string), which is below every `min_tier` ordinal — caller MUST pass tier explicitly. Test #10 locks this. The forcing function: AD-456c-2 caller-side wiring is mandatory before any production deployment flips the enforcement flag to True. v1 ships the seam in fail-closed mode by design — operators who flip the flag without AD-456c-2 will see immediate denials, signal that propagation isn't complete.

- **DLog #7 — Unknown tier strings deny.** Operator typos (`"comander"` instead of `"commander"`), future-tier values (`"captain-mode"`), or upstream-corrupted data resolve to ordinal `-1` and are denied. Test #12 locks this. Fail-safe contract — never grant access on garbled tier input. AD-456c-N might add a strict-mode that raises on unknown strings; v1 silently denies + logs.

- **DLog #8 — `_AGENCY_ORDER` is module-level constant, NOT a method on the class.** Module constant matches the precedent at `earned_agency.py:90` (`_TIER_ORDER`); makes test #12 cleanly verifiable (`_AGENCY_ORDER.get("captain-mode", -1) == -1` is a direct module-symbol assertion). Single-source-of-truth — both `get()` and tests reference the same constant.

- **DLog #9 — `available()` and `list_credentials()` not modified.** Both call `get(name, requester="availability_check")` internally. With `_tier_enforcement=True` and a spec carrying `min_tier`, both will return False / non-availability. Test #11 locks `available()` respecting the tier gate. This IS the correct security posture — an introspection caller without tier context should not get a green `available=True` signal for a tier-gated credential. `list_credentials` returns names + booleans; the name surface is already semi-public via `_register_builtins` (test #3 locks built-in tier-ungated). Operators who want tier-aware introspection can pass `tier=` as a future enhancement (AD-456c-3 HXI overlay surface).

- **DLog #10 — `_emit_tier_denied` is log-and-degrade tier (3-tier rule, tier 2).** Emit failures must NOT propagate. The deny decision is already returned to the caller; the access has been logged via `_log_access`; the `_emit_event` channel is a third-party observer for which a failure is non-critical. Mirrors `_emit_rotated`'s exception handler exactly (`credential_store.py:262-264`).

- **DLog #11 — No new pool, agent, module beyond the new test file. No EventType beyond `CREDENTIAL_TIER_DENIED`. No journal table. No new Pydantic config class.** Strictly additive: every existing AD-456 / AD-456b / AD-395 / `CredentialStore` test continues to pass without modification. New `min_tier` field defaults `None`; new `_tier_enforcement` instance attr defaults `False`; new `credential_tier_enforcement` config field defaults `False`. The migration is forward-compatible.

- **DLog #12 — Phantom-API pre-check status.** Same recurring blocker as Waves 52, 53, 54, 55 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (24 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `557316e`). Net-new symbols (8 listed: `CredentialSpec.min_tier`, `CredentialStore._tier_enforcement`, `CredentialStore.set_tier_enforcement`, `CredentialStore._emit_tier_denied`, `_AGENCY_ORDER`, `EventType.CREDENTIAL_TIER_DENIED`, `SecurityInfraConfig.credential_tier_enforcement`, `tests/test_ad456c_per_tier_credentials.py`) are intra-prompt-introduction (Sections 0 / 1 / 2a-f / 3 SEARCH/REPLACE). Same FP class as Waves 27-55.

- **DLog #13 — Test count target +13, ceiling +14.** 13 explicit tests in Section 4. The +14 ceiling allows one boundary discovery during build (Wave-30/39/41/42/53/55 precedent). If post-build delta is <+13 or >+14, hard-stop and triage before commit. Wave 55 baseline (11239) + 13 new = 11252 net target.

- **DLog #14 — Commercial-leak audit: clean.** AD-456c is OSS plumbing — `CredentialSpec.min_tier` field + `_tier_enforcement` toggle + tier-gate block in `get()`. AD-456c-4 *(Commercial)* deferral entry tags Vault adapters / HSM-backed stores / Entra-issued tier tokens / RBAC over secret namespaces / SSO over policy management as the extension-point seam — describes WHAT plugs in (extension point on the `CredentialStore.set_tier_enforcement` + `CredentialSpec.min_tier` contract), NOT business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #15 — No Wave-10 reframe trigger.** v1 scope is already minimal (the API surface + the toggle + the gate); the natural deferrals (caller-side wiring, per-secret scope, HXI grants) are all pre-applied at draft time per Wave-10 wave-5 convention #3. No mid-wave reframe expected. If the Builder discovers that the `tier=` kwarg passing requires modifying ≥1 existing call site to maintain test invariants, hard-stop and surface — that would be a Wave-10 trigger to defer the wiring change to AD-456c-2.

## Highest-risk constraints (re-read before each Section)

1. **Section 2a `min_tier` insertion order in `CredentialSpec`.** Default-valued fields in a `@dataclass` must come AFTER non-defaulted fields. `min_tier: str | None = None` slots between `allowed_departments` (defaulted) and `description` (defaulted) — both already have defaults, so insertion is safe. SEARCH locks the entire dataclass body so REPLACE is unambiguous.

2. **Section 2b `_AGENCY_ORDER` insertion site between `CredentialSpec` and `CredentialStore`.** SEARCH locks the blank gap + `class CredentialStore:` opening line + its docstring head. If the Builder accidentally inserts inside `CredentialSpec` or inside `CredentialStore`, the module won't parse / `_AGENCY_ORDER` won't be a module-level constant.

3. **Section 2c `_tier_enforcement` insertion in `__init__`.** New line slots between `self._store_loaded = False` and `self._register_builtins()`. SEARCH locks the entire `__init__` body so REPLACE is unambiguous. If `_register_builtins()` runs BEFORE `_tier_enforcement` is set, builtins still register fine — they don't read enforcement state — but ordering matters for readability.

4. **Section 2d `set_tier_enforcement` insertion before `register`.** SEARCH locks the `register` method head. If the Builder accidentally inserts inside `register` or after `_register_builtins`, the public API surface fragments. Test #4 (`test_set_tier_enforcement_toggles_flag`) directly calls `store.set_tier_enforcement(True)` then `store.set_tier_enforcement(False)` — verifies the method is reachable from outside.

5. **Section 2e tier-gate block insertion ordering.** New block runs AFTER department check (lines 195-202) and BEFORE cache check (line 204). SEARCH locks the department check block + the trailing `# Check cache` comment + `cached = self._cache.get(name)` line so REPLACE is unambiguous. If new block lands BEFORE the department check, the defense-in-depth ordering inverts; if it lands AFTER cache lookup, a previously-cached value bypasses the new gate (cache poisoning vector). Test #9 (deny lower tier) implicitly locks the ordering — if the cache-bypass were broken, repeated denies would inconsistently flip to grant after a single grant.

6. **Section 2e ordinal comparison shape.** `_AGENCY_ORDER.get(tier, -1) if tier is not None else -1` — `tier is None → -1`; `tier is unknown string → -1` (via `.get(name, -1)`). Both paths deny when `min_tier` is set (since every legitimate `min_tier` ordinal ≥ 0). Builder MUST NOT short-circuit the `tier is not None` check (e.g., by writing `_AGENCY_ORDER.get(tier or "", -1)`) — that path subtly behaves identically here BUT loses the explicit `None`-deny path that test #10 relies on for clarity.

7. **Section 2f `_emit_tier_denied` is log-and-degrade.** `try/except Exception → logger.warning` mirrors `_emit_rotated` exactly. NEVER let an emit failure propagate up to the caller — the deny decision and the `_log_access` audit are already complete; the emit channel is observer-only.

8. **Section 3 finalize wiring placement.** New if-block goes immediately after the existing `credential_store._emit_event = runtime.emit_event` extension block (lines 1249-1267) and BEFORE the EgressPolicy block (line 1269). SEARCH locks the entire AD-456 CredentialStore extension block so REPLACE is unambiguous. The new block is gated on `credential_store is not None AND config.security_infra.credential_tier_enforcement=True` — if `credential_store` is None (impossible at finalize time, but defensive), the new block silently skips.

9. **Section 4 test isolation.** Tests use `monkeypatch.setenv` (auto-reverts at test exit). No tests share `CredentialStore` instances — each test calls `_make_store()` fresh. No tests leak class-level state (there is none — `_tier_enforcement` is instance, not ClassVar). pytest-xdist parallel runs are safe.

10. **Test #11 (`test_credential_tier_denied_event_emitted_on_deny`) payload assertion.** Locks the four-key payload shape (`name` / `requester` / `requested_tier` / `required_tier`). If the Builder accidentally adds `denied_at` / `spec_id` / etc., test #11 fails. The payload shape is part of the public AD-456c contract — downstream consumers (HXI, audit dashboards) will key off these field names. Lock is intentional.

11. **Do NOT touch `CredentialStore._resolve` chain** (config → env → store → CLI). Tier gate runs BEFORE `_resolve`; chain is unchanged.

12. **Do NOT touch `_log_access`.** Existing source values (`cache` / `resolved` / `not_found` / `denied_department`) preserved; new `denied_tier` source is the only addition, emitted via the new gate block (not via a `_log_access` modification).

13. **Do NOT touch `rotate()` / `_emit_rotated()` / cache TTL.** Orthogonal to the tier gate.

14. **Do NOT modify the existing `available()` or `list_credentials()` method bodies.** Test #11 locks that `available()` respects the tier gate via the `get()` path automatically — no method-level modification needed.

15. **Do NOT touch `runtime.credential_store` instantiation at `runtime.py:317`.** The runtime constructs `CredentialStore` once; finalize merely sets `_store_path` / `_emit_event` / now `_tier_enforcement` on the existing instance.

16. **Do NOT add an `import probos.earned_agency` to `credential_store.py`.** DLog #3 — the local `_AGENCY_ORDER` map exists specifically to avoid this coupling.

17. **Do NOT add a new pool, agent, module, journal table, or EventType beyond `CREDENTIAL_TIER_DENIED`.**

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #12, recurring from Waves 52-55). Manual verify-first pass: 24 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `557316e`. Net-new symbols (8 listed in DLog #12) are intra-prompt-introduction (Sections 0 / 1 / 2a-f / 3 SEARCH/REPLACE). Same FP class as Waves 27-55.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11239 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `events.py` adds `CREDENTIAL_TIER_DENIED`
2. Section 1 — `config.py` `SecurityInfraConfig` adds `credential_tier_enforcement: bool = False`
3. Section 2a — `credential_store.py` `CredentialSpec.min_tier` field
4. Section 2b — `credential_store.py` module-level `_AGENCY_ORDER` constant
5. Section 2c — `credential_store.py` `__init__` adds `_tier_enforcement: bool = False`
6. Section 2d — `credential_store.py` `set_tier_enforcement` method
7. Section 2e — `credential_store.py` `get(...)` adds `tier=` kwarg + tier-gate block
8. Section 2f — `credential_store.py` `_emit_tier_denied` helper
9. Section 3 — `startup/finalize.py` wires `set_tier_enforcement` conditional on config flag
10. Section 4 — `tests/test_ad456c_per_tier_credentials.py` NEW (13 tests)
11. Run focused gate: `pytest tests/test_ad456c_per_tier_credentials.py tests/test_ad456_security_infrastructure.py tests/test_ad456b_runtime_sandboxing.py tests/test_credential_store.py -v -n 0`
12. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `tests/test_credential_store.py` regresses after Section 2 lands. The change is strictly additive — `CredentialSpec` gains one defaulted field; `CredentialStore.__init__` gains one defaulted instance attribute; `get()` gains one defaulted kwarg; existing call sites are unchanged. If a regression appears, most likely cause is Section 2e SEARCH/REPLACE ordering wrong (tier-gate block landed BEFORE the department check, OR AFTER the cache check). SEARCH locks both anchors — verify the indentation and the surrounding context preserved exactly.

- An existing test in `tests/test_ad456_security_infrastructure.py` regresses. AD-456 contracts are preserved bit-for-bit — `runtime.credential_store` is the same instance; `_emit_event` / `_store_path` / `_register_builtins` unchanged; `rotate()` / `_resolve()` unchanged. If a regression appears, most likely cause is Section 3 finalize block placement wrong (new wiring landed BEFORE the existing AD-456 CredentialStore block, breaking attribute setup ordering).

- An existing test in `tests/test_ad456b_runtime_sandboxing.py` regresses. AD-456b contracts are orthogonal — no symbol overlap. If a regression appears, the failure is most likely in `events.py` (Section 0 — verify `SANDBOX_CAPABILITY_DENIED` is preserved AND the new `CREDENTIAL_TIER_DENIED` value is unique).

- Pydantic config validation failure at startup (every test would fail). Section 1 SEARCH locks the existing `egress_active_enforcement` field with its multi-line comment; REPLACE re-emits the existing field unchanged plus the new field. If the Builder accidentally overwrites the old field's default or comment, validation breaks. Verify that `egress_active_enforcement: bool = False` survives the REPLACE.

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage per `.github/copilot-instructions.md` — re-run failing file at `-n 0` first. Section 4 tests use `monkeypatch` exclusively (no class-level state, no module-level mutation, no temp-file races). If parallel-only failures appear, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

- Phantom-API pre-check script remains broken (DLog #12) — non-blocker for THIS wave; cleanup AD remains pending.

- Test count delta < +13 OR > +14 — investigate before commit (drift signal).

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-456c CLOSED entry.
- `docs/development/roadmap.md` — flip AD-456c row to ✅ shipped under the AD-456 cluster; add AD-456c-1 (per-secret scope policy), AD-456c-2 (caller-side `tier=` propagation across all production credential call sites), AD-456c-3 (HXI Captain-issued temporary tier-elevation grants), AD-456c-4 *(Commercial)* (Vault / HSM / Entra-issued tier tokens / RBAC / SSO — extension point), AD-456c-5 (`credential_tier_enforcement` default flip), AD-456c-6 (`RedTeamAgent` / `IntrospectionAgent` tier consumption) deferral entries with explicit forcing functions.
- `DECISIONS.md` — prepend AD-456c entry at top of Era V.

## Issues to close

GitHub MCP `issue_write` close on **#399** (expect EMU 403 same as Waves 31-55; Captain closes manually).

## Commit message

`AD-456c: Security infrastructure per-tier credential lookup v1 (CredentialSpec.min_tier + CredentialStore tier gate) (+13 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #12, recurring from Waves 52-55). Builder cannot run the standard pre-check; manual verify-first pass already done at draft (24 verifying greps). Forcing function for a tooling-hygiene-AD logged but NOT scoped into this wave.

2. **No new runtime dep introduced.** v1 implementation uses ONLY stdlib + existing `probos.events`. `_AGENCY_ORDER` is a literal `dict[str, int]`. No `psutil`, no `resource`, no third-party library — and explicitly NO import of `probos.earned_agency` into `credential_store.py` (DLog #3).

3. **Test count baseline asserted at 11239.** Wave-55 dispatch projected exactly 11227 + 12 = 11239; commit `f47c4b1` landed at 11239. If pre-flight returns ≠ 11239, hard-stop and triage before dispatching Builder.

4. **Wave 56 is single-AD, sequential, 4 sections + 6 sub-edits in Section 2 across 1 module + 3 single-edit files + 1 new test file (~290 lines, 13 tests).** Smaller envelope than Wave 55 (which added a 225-line new module file). Builder envelope: tighter than Waves 53/55, comparable to Waves 51/52.

5. **Strictly additive — zero existing-symbol modifications.** All 16 existing AD-456 tests + all 12 existing AD-456b tests + all existing CredentialStore tests + all existing finalize tests continue to function unchanged. New `min_tier` field defaults `None`; new `_tier_enforcement` defaults `False`; new `credential_tier_enforcement` config field defaults `False`; new `tier=` kwarg defaults `None`. The only `get()` signature change is the additive kwarg, which has a default — every existing call site continues to bind correctly. The migration is forward-compatible.

6. **No mid-wave reframe expected.** v1 scope is already minimal per Wave-10 / wave-5 convention #3 pre-application: caller-side `tier=` resolution at production call sites is AD-456c-2 (DLog #4); per-secret scope policy is AD-456c-1; HXI grants AD-456c-3; commercial overlays AD-456c-4; default-flip AD-456c-5; RedTeamAgent/IntrospectionAgent integration AD-456c-6. All known scope-bloat targets are pre-deferred at the prompt level.

7. **No commercial leak.** AD-456c is OSS plumbing: `CredentialSpec.min_tier` field + `_tier_enforcement` toggle + tier-gate block. AD-456c-4 *(Commercial)* deferral entry tags Vault / HSM / Entra / RBAC / SSO as the extension-point seam — describes WHAT plugs in (extension point on the `CredentialStore.set_tier_enforcement` + `CredentialSpec.min_tier` contract), NOT business model. v1 ships zero references to pricing, tier strategy, customer counts, competitive analysis, professional-services positioning, or demo scripts with sales framing. Commercial-leak audit: **clean**.

8. **Caller-side wiring is explicitly NOT in this wave** (DLog #4). v1 ships the API surface (`tier=` kwarg + enforcement toggle); production credential call sites continue to call `runtime.credential_store.get(name, requester=...)` without a `tier=` argument. With `_tier_enforcement=False` (the v1 default), the kwarg is dead code; with the flag flipped to True, those call sites would deny — that's the AD-456c-2 forcing function.

9. **Earned Agency module coupling intentionally avoided.** `credential_store.py` does NOT import `probos.earned_agency` (DLog #3). The `_AGENCY_ORDER` map duplicates four string constants; this is a deliberate Law-of-Demeter posture — credential resolution is a primitive that should not depend on the rank/agency module's full surface (which transitively imports `crew_profile.Rank`, agency-graduation logic, clearance-grant resolution, etc.).
