# Review: AD-440 — Chain of Command Delegation

**Reviewer:** Architect (self-review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — solid core design with a clean ontology-Demeter posture, but two private-attribute access leaks (`runtime._order_manager`, frozen-dataclass `**__dict__` reconstruction) and incomplete test coverage on the rejection-reason matrix. Highest-risk prompt of Wave 5; verify carefully.

**Note on dispatch's pre-flagged item:** the user's dispatch flagged "AD-440 `_superior_agent_ids` Demeter." That symbol lives in **AD-439**, not AD-440. AD-440 itself accesses ontology via the public `get_assignment_for_agent` and `get_post` methods only — clean on that front.

---

## Required (must fix before building)

### 1. `runtime._order_manager` is accessed across module boundary — Demeter violation

The prompt's Section 4 wiring sets `runtime._order_manager = order_manager` (private name). Section 5 then reads it from `proactive.py`:

```python
order_mgr = getattr(rt, "_order_manager", None)
```

That's the same anti-pattern AD-680 was created to eliminate (`runtime._emit_event` → `runtime.emit_event`). The post-AD-680 standard is: any cross-module accessor on the runtime is a public attribute or a `@property`. The leading underscore is reserved for runtime-internal state.

The existing precedent (AD-676 risk registry, AD-679 disclosure router) currently use `runtime._risk_registry` / `runtime._disclosure_router` — those are also Demeter violations carried over from earlier waves. AD-440 should NOT propagate the pattern.

**Action:** Add `runtime.order_manager` as a public attribute (no underscore). Section 4 wiring becomes:

```python
runtime.order_manager = order_manager
```

Section 5 reads `getattr(rt, "order_manager", None)` (public name, matches the convention). Document the choice in DECISIONS.md alongside the other AD-440 decisions; it sets the precedent for the rest of Wave 5/6/7.

### 2. `Order` reconstruction via `Order(**{**order.__dict__, ...})` is fragile

The prompt's `acknowledge` and `_prune_expired` methods rebuild `Order` instances via:

```python
updated = Order(
    **{**order.__dict__, "state": OrderState.ACKNOWLEDGED, ...},
)
```

This works for non-slotted frozen dataclasses but is fragile: any future field added to `Order` requires no code change here, but the pattern hides field changes from the type checker. The canonical Python pattern is `dataclasses.replace`:

```python
updated = dataclasses.replace(
    order,
    state=OrderState.ACKNOWLEDGED,
    acknowledged_by=by_agent_id,
    acknowledged_at=time.time(),
)
```

`dataclasses.replace` is already used in the codebase (AD-673 anchor stamping uses it on a frozen dataclass per the AD-673 description). Match the precedent.

**Action:** Replace the `Order(**{**order.__dict__, ...})` patterns with `dataclasses.replace(order, ...)`. Two call sites in Section 1.

### 3. Rejection-reason matrix has gaps

The prompt's `_emit_rejection` is called with six distinct `reason` strings: `empty_directive`, `unknown_issuer`, `issuer_no_assignment`, `issuer_post_missing`, `out_of_chain`, `queue_full`. The 14 tests cover only four (`out_of_chain`, `empty_directive`, `unknown_issuer`, `queue_full`).

Two reasons are unreachable in normal flow but emitted on construction failures:
- `issuer_no_assignment` — agent in the registry but `get_assignment_for_agent(agent_type)` returns None.
- `issuer_post_missing` — assignment exists but `get_post(post_id)` returns None.

Either:
- (a) Add two tests to cover these branches (a registry mock returning an agent whose ontology entry is incomplete is straightforward).
- (b) Collapse the two reasons into a single `issuer_resolution_failed` to keep the surface narrow, then the existing happy-path coverage is sufficient.

**Action:** Pick (a) or (b). Recommended (a) — diagnostic precision is valuable in an authority/trust subsystem; the two extra tests cost ~10 lines.

### 4. The proactive context injection prose is misleading about the data shape

The prompt's Section 5 says:

> The existing pattern (search for `if hasattr(rt, 'bridge_alerts')` for an analogous block) is to read a list and inject formatted strings into `context_parts`.

That's not quite the shape. Verified at `proactive.py:1345-1356`: the bridge-alerts block reads from `rt.bridge_alerts.get_recent_alerts(...)` and writes into `context["recent_alerts"]` (a dict KEY, value is a list of dicts). `_gather_context` returns the `context` dict, which is named `context_parts` at the call site (`proactive.py:633`).

The actual sketch in the prompt does the right thing — it writes `context["active_orders"] = "\n".join(lines)` — but the prose is confusing for a Builder. Update the prose to match the live pattern: "inject as a string under `context["active_orders"]`, matching the bridge-alerts pattern at `proactive.py:1345`."

**Action:** Fix the prose. The code sketch itself is correct.

---

## Recommended

### R1. `_agent_type_for_id` performs an O(N) registry scan

Same finding as AD-439 R3. For an agent count under 100, this is negligible. For a future federation with 1000+ agents, document or pre-index. Non-blocking for AD-440's scope.

### R2. `acknowledge` allows only the post-holder to ack — what about superiors?

The current `acknowledge` checks the acknowledger's post matches `order.to_post_id`. That's restrictive — a Captain or First Officer cannot ack on a subordinate's behalf. Probably intended (acks are personal), but worth a one-line comment in the docstring. Or accept a `by_role: str` parameter for a future override. Skip for v1; document as out-of-scope.

### R3. `default_ttl` configuration name vs. constant naming

`OrderManager.DEFAULT_TTL_SECONDS = 3600.0` (class constant) and `default_ttl` (constructor param). Codebase tends to prefer either both-class-constants or both-instance-fields. Cosmetic.

### R4. Captain override path is omitted but referenced

Section 6 says:
> `POST /api/orders` — Captain-only override path to issue orders bypassing chain validation. Out of scope; **omit** in this AD.

Good — explicitly out of scope. But the prompt does NOT add a stub or hook for this. If a future AD wants to add it, the Builder will need to revisit this file. Acceptable for the v1 scope. Confirm the deferral lands in DECISIONS.md per the prompt's tracking section.

### R5. `OrdersConfig.default_ttl_seconds` should have validation

The Pydantic model field has no `Field(ge=60.0, le=86400.0)` validator. AD-440's documented MIN/MAX (`max(60.0, min(86400.0, ...))` is in the manager's `_coerce`-equivalent path, but the `OrdersConfig` field itself accepts any float. A user could set `default_ttl_seconds = -1` and break the manager. Add a `field_validator`. Pattern matches `health_probe_interval_seconds` at `config.py:1587`.

---

## Nits

- The class docstring on `OrderManager` says "in-memory chain-of-command delegation store" — accurate.
- `OrderState.PENDING/ACKNOWLEDGED/EXPIRED` — three states. No CANCELLED. If the Captain wants to revoke an order before it's acted on, there's no path. Consider adding CANCELLED + a `cancel(order_id)` method, or document the omission.
- `metadata: dict[str, Any] = field(default_factory=dict)` — good; uses `field(default_factory=...)` not the bare `{}` mutable default anti-pattern flagged in `architect.md`.
- `Order.id = uuid.uuid4().hex[:12]` — 12 hex chars = ~48 bits, low collision probability for in-memory use. Fine.

---

## Verified

- `EventType.ORDER_ISSUED`, `ORDER_REJECTED`, `ORDER_ACKNOWLEDGED` absent from events.py — Section 0 introduces cleanly.
- SEARCH anchor `DM_CONVERGENCE_DETECTED ... SENSORIUM_BUDGET_EXCEEDED` confirmed at `events.py:167-168`.
- `class VesselOntologyService` at `service.py:45` ✓
- `get_assignment_for_agent` at `service.py:153` ✓
- `get_post` at `service.py:120` ✓
- `authority_over` field at `organization.yaml:28,38,80,124` ✓
- `cmd_order` (existing CAPTAIN_ORDER) at `commands_directives.py:99` — **orthogonal**, AD-440 does not modify it ✓
- `_gather_context` at `proactive.py:1053` ✓
- `bridge_alerts` block at `proactive.py:1345-1356` exists ✓
- `_disclosure_router = disclosure_router` at `finalize.py:330` (insertion neighborhood) ✓
- `emergence_metrics: EmergenceMetricsConfig` at `config.py:1544` (config insertion neighborhood) ✓
- No EventType collision with AD-439/455/468/499 ✓
- AD-477 (Naval Org Protocols) is PLANNED but **not** a hard prerequisite — `authority_over` is owned by AD-429 (closed). The prompt's status header correctly documents this ✓

---

## Required Disposition

⚠️ **Conditional approval.** Three Required findings (Demeter on `_order_manager`, frozen-dataclass reconstruction, test coverage gap) and one prose fix. None require redesign — all are surgical edits. Estimated rework: ~25 minutes architect time.

After fixes, this should pass re-review at ✅ Approved. Of the 5 Wave 5 prompts, AD-440 is the highest-risk (trust/authority surface) and should land sequenced **after** AD-455 and AD-468 — both of which establish wiring patterns AD-440 should mirror.
