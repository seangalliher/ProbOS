# Review: AD-499 — Ship & Crew Naming Conventions

**Reviewer:** Architect (self-review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — core policy classes are solid and verify-first, but the wiring sections (4, 5, 6) point at the wrong layer in two places and call a phantom EventLog API. Builder will hit hard-stops on Sections 4 and 5 as written.

---

## Required (must fix before building)

### 1. Section 5 calls `self._event_log.append(...)` — phantom API

The prompt's Section 5 sketch:
```python
await self._event_log.append(EventType.AGENT_SELF_NAMED, {...})
```

The real `EventLog` API is `log(...)`, not `append(...)`. Verified:

```
grep -n "async def log\|async def append" src/probos/substrate/event_log.py
  94:    async def log(
```

There is no `EventLog.append`. Existing callers in the same file use `log`:

```
grep -n "_event_log\." src/probos/agent_onboarding.py
  364:        await self._event_log.log(
```

**Action:** Replace `append` with `log` (or use the runtime `emit_event` path which is the post-AD-680 standard).

### 2. Section 5 references undefined `_BANNED_DEFAULT` and uses the wrong local variable

Section 5 sketch reads:
```python
policy = AgentNamingPolicy(
    banned=frozenset({*_BANNED_DEFAULT, *self._config.naming.extra_banned_words})
    ...
)
validation = policy.validate(chosen_callsign)
...
chosen_callsign = fallback_callsign  # existing seed callsign path
```

Three issues:
- `_BANNED_DEFAULT` does not exist in `agent_onboarding.py`. Grep returns no matches. The actual banned defaults live as `_BANNED_WORDS_DEFAULT` inside `naming.py` (Section 1 of this prompt). The Builder cannot import that name from inside `agent_onboarding.py` because the policy class already encapsulates it; the splat is unnecessary.
- The actual local variable in `run_naming_ceremony` at `agent_onboarding.py:532` is `chosen`, not `chosen_callsign`. The outer assignment at line 223 uses `chosen_callsign`, so context matters — the validation hook belongs at the seam where the LLM result lands (inside `run_naming_ceremony`, around line 532–540), not at the caller site.
- `fallback_callsign` is also undefined; the existing fallback variable is `seed_callsign` (`agent_onboarding.py:467`).

**Action:** Replace the Section 5 sketch with a precise SEARCH/REPLACE block keyed on the actual code at lines 530–545. Drop the `_BANNED_DEFAULT` splat — `AgentNamingPolicy(banned=frozenset(extra))` is sufficient; the policy merges with its own defaults internally if the prompt updates `AgentNamingPolicy.__init__` to accept an `extra_banned` parameter.

### 3. Section 4 targets the wrong layer — ship naming happens in `communication.py`, not `identity.py`

Section 4 says "wire `ShipNamingPolicy` into commissioning" and points at `_load_or_commission_ship` (verified at `identity.py:455`). But by the time that method runs, `vessel_name` has already been chosen and passed in as a parameter:

```
grep -n "vessel_name=" src/probos/startup/communication.py
  403:            vessel_name=vi.name,
  427:                        vessel_name=vi.name,
```

`vi.name` comes from `ontology.get_vessel_identity()` at line 400. The actual choice point for the ship name is **before** `identity_registry.start(...)` is called. Wiring `ShipNamingPolicy` inside `_commission_ship` would be too late: at that moment the `vessel_name` argument has already been bound to whatever the ontology returned.

The correct seam is `src/probos/startup/communication.py` around line 398–405:

```python
vi = ontology.get_vessel_identity()
# AD-499: route the ontology's vessel name through ShipNamingPolicy
from probos.naming import ShipNamingPolicy
ship_policy = ShipNamingPolicy()
decision = ship_policy.select(
    instance_id=vi.instance_id,
    override_name=config.naming.captain_ship_override or vi.name,
)
chosen_vessel_name = decision.name
await identity_registry.start(
    instance_id=vi.instance_id,
    vessel_name=chosen_vessel_name,
    version=config.system.version,
)
```

(plus `runtime.emit_event(EventType.SHIP_NAMED, ...)` per AD-680.)

**Action:** Move Section 4 from `identity.py` to `startup/communication.py`. Replace the sketch with a real SEARCH/REPLACE block keyed on `vi = ontology.get_vessel_identity()`.

### 4. Section 6 federation integration has no real anchor

Section 6 says "find the existing peer-display path and route it through `FederationDisplayFormat.format()`. If no display path exists, add a public helper." Verified:

```
grep -n "def " src/probos/federation/router.py
  29:    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
  36:    def peer_has_capability(self, peer_node_id: str, intent_name: str) -> bool:
```

No display-name path exists in `router.py`. The fallback ("add a public helper") is a no-op deliverable — a function nobody calls is dead code. AD-499 should either:

- (a) Drop Section 6 entirely. `FederationDisplayFormat` becomes a library helper; consumers will adopt it when federation surfaces a peer-display path. Document the deferred integration in the prompt's "What This Does NOT Change" section.
- (b) Identify a real consumer (e.g., the federation log lines in `bridge.py`) and wire one site through the helper.

**Action:** Choose one. (a) is the lower-risk default given AD-499's trivial-class scope.

### 5. `SystemInfo.ship_name` does not exist (pre-existing bug, prompt should not perpetuate)

```
grep -n "class SystemInfo" src/probos/config.py
  1384: class SystemInfo(BaseModel):
```

`SystemInfo` has only `name`, `version`, `log_level` (`config.py:1384–1389`). The naming ceremony at `agent_onboarding.py:470` reads:

```python
ship_name = getattr(getattr(self._config, 'system', None), 'ship_name', None) or "ProbOS"
```

This always falls back to `"ProbOS"` because `ship_name` is a phantom attribute — pre-existing bug. AD-499 should NOT silently route through this dead path. Either fix the attribute name (use `name`) or surface the existing bug as a separate observation.

**Action:** Note the pre-existing dead-path in the prompt's "What This Does NOT Change" section and choose `vi.name` (the real source of truth) as the input to `ShipNamingPolicy.select()`.

---

## Recommended

### R1. Add a `runtime.emit_event` call in Section 4 instead of free-floating `emit_event`

The prompt's Section 4 sketch uses a parameterized `emit_event` callable. Post-AD-680, the standard is `runtime.emit_event(EventType.SHIP_NAMED, {...})`. Pin the Section 4 sketch to that surface so the Builder doesn't have to reverse-engineer which emit shim to use.

### R2. `AgentNamingPolicy.banned_words` should be a method, not a property — or just drop it

The exposure is for tests only. A test can read `policy._banned` (private attr) is fine for internal tests, but if exposed publicly, it should be a regular method `def banned_words(self) -> frozenset[str]` for consistency with the rest of the codebase's tendency to favor methods over properties for set/dict accessors.

### R3. Test 4 (`test_ship_naming_deterministic_seed_stable`) should also verify that two different `instance_id`s probably produce different names

The current test only checks within-instance stability. Adding "two distinct instance_ids → two distinct names with high probability" catches a regression where someone accidentally drops the seed and returns a constant. One-line addition.

### R4. Curated pool size of 15 is small — collisions are likely across multiple test ships

For testability and federation, document the pool-size choice in DECISIONS.md. The trivial-class scope means we don't need a generator-based pool yet, but recording the deliberate choice prevents later "is 15 enough?" debates.

---

## Nits

- The phrase "AD-499 only validates the LLM's output" in *What This Does NOT Change* is accurate and worth keeping.
- `frozenset(b.lower() for b in banned)` in `AgentNamingPolicy.__init__` is fine; minor style nit: a frozenset comprehension `frozenset({b.lower() for b in banned})` is identical performance and slightly more idiomatic.
- The `_CALLSIGN_RE` pattern `^[A-Z][a-zA-Z0-9_-]{1,31}$` allows underscores and hyphens, which differs from the run_naming_ceremony prompt text "alphabetic characters" (line 512). Document or align.

---

## Verified

- `EventType.SHIP_NAMED` and `EventType.AGENT_SELF_NAMED` are absent in `events.py` — Section 0 introduces them cleanly. Insertion point at `events.py:179` (`DISCLOSURE_FILTERED`) is clean.
- `naming.py` is a flat-layout new file matching the convention of `identity.py`, `proactive.py`, `crew_profile.py`. Layout decision is correct.
- `Field` is already imported in `config.py` at line 10. The Section 3 verify-first note is correct but defensive.
- `_CALLSIGN_RE` allows all real callsigns currently in tests (Picard, Riker, etc.).
- `ShipNamingPolicy` and `AgentNamingPolicy` and `FederationDisplayFormat` are absent from the codebase — verified via `grep -rn "ShipNamingPolicy|AgentNamingPolicy|FederationDisplayFormat" src/probos/` (no matches). Clean introduction.
- AD-441 / AD-441b / AD-442 dependencies confirmed complete via `class AgentBirthCertificate` at `identity.py:101` and `run_naming_ceremony` at `agent_onboarding.py:465`.
- No EventType collision with the other 4 Wave 5 prompts.

---

## Required Disposition

⚠️ **Conditional approval.** The three policy classes (Sections 1, 7-test) are clean and ship-ready. Sections 4, 5, 6 need targeted rewrites against the real code anchors before Builder picks this up. Estimated rework: ~30 minutes architect time.

After fixes, the prompt should re-pass review and become ✅ Approved.


---

## Second-Pass Review (2026-05-01)

**Verdict:** ⚠️ **Conditional** — 4 of 5 pass-1 Required findings cleanly resolved; pass-1 #3 (Section 4 layer move) introduced a NEW Required-class phantom: `runtime` is not in scope inside `startup/communication.py`.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| #1 `EventLog.append` phantom | ✅ Resolved | Section 5 line 351 now uses `self._event_log.log(category=..., event=..., data=...)`. Verify-first footer line 489 confirms `log()` is the real API. |
| #2 `_BANNED_DEFAULT` & wrong variable names | ✅ Resolved | Section 5 (line 303-342) now keys on `chosen` and `seed_callsign` (the real local variables at `agent_onboarding.py:467,532`). `_BANNED_DEFAULT` splat removed; defaults folded into `AgentNamingPolicy.__init__` extension. |
| #3 Section 4 wrong layer | ⚠️ **Partial — new Required introduced** | Section moved to `startup/communication.py` line 399 (correct seam). BUT the SEARCH/REPLACE block (line 270-294) calls `runtime.emit_event(EventType.SHIP_NAMED, ...)` and the verify-first note (line 295) claims `runtime` is in scope. **Verified false:** `init_communication` (the actual function at `communication.py:37`) takes `emit_event_fn: Callable[..., Any]` at line 46, not `runtime`. Building this prompt as written produces `NameError: name 'runtime' is not defined`. |
| #4 Section 6 federation dead code | ✅ Resolved | Section 6 explicitly removed (line 380-382). "What This Does NOT Change" documents the deferral (line 412). |
| #5 `SystemInfo.ship_name` pre-existing bug | ✅ Resolved | Documented in "What This Does NOT Change" line 415; AD-499 routes through `vi.name` (the real source). |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| R1 (`runtime.emit_event` per AD-680) | ⚠️ **Compromised by Required #3** — the intent was right, but the call site doesn't have `runtime` available |
| R2 (`banned_words` accessor style) | 📦 Deferred — kept as-is; cosmetic |
| R3 (distinct-instance distinct-name test) | ✅ Tracked for Builder; Test plan unchanged |
| R4 (DECISIONS.md pool size) | ✅ Tracking section calls for optional entry |

### New Findings (introduced during revision)

1. **⚠️ Required (NEW): `runtime` is not a parameter of `init_communication`.** Verify-first contradicts the live signature. Fix: replace `runtime.emit_event(...)` with `emit_event_fn(...)` in Section 4's REPLACE block. Update the verify-first note. Single-line fix, ~5-minute architect rework.
2. **Nit: variable name regression at line 355.** The `data={"agent_id": agent.id, "callsign": chosen_callsign}` dict still uses `chosen_callsign` — should be `chosen` to match the rest of Section 5's revision.
3. **Nit: stale Pre-Commit Sanity Check delta (line 439, 441).** `identity.py: ~12 lines` is stale (Section 4 moved to `communication.py`). `federation/router.py: ~5 lines` is stale (Section 6 removed). Update the expected-delta list.

### Verified Against Revised Codebase Claims

- `init_communication` signature at `communication.py:37`:
  `
  grep -n "^async def init_communication" src/probos/startup/communication.py
    37: async def init_communication(
  grep -n "emit_event_fn" src/probos/startup/communication.py
    46:    emit_event_fn: Callable[..., Any],
  `
  No `runtime` parameter.
- `communication.py:399-405` SEARCH anchor: confirmed verbatim ✓.
- `EventLog.log` at `event_log.py:94`: confirmed ✓.
- `agent_onboarding.py:467,532`: confirmed ✓.
- `Field` import at `config.py:10`: confirmed ✓.
- No federation peer-display path: confirmed; only `select_peers`, `peer_has_capability` ✓.

### Recommended Next Step

One-edit fix to Section 4: replace `runtime.emit_event(EventType.SHIP_NAMED, ...)` with `emit_event_fn(EventType.SHIP_NAMED, ...)`, update the verify-first note, fix the two stale Pre-Commit estimates, and align the line-355 variable name. ~5 minutes architect rework. Then re-pass review; expected verdict ✅ Approved.
