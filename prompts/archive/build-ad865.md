# Build Prompt — AD-865: Route assignment through the department chief (chain of command)

**Repo:** OSS (`d:\ProbOS`). One AD = one commit (additive-only; corruption pre-check first).
**Parent epic:** `prompts/ad-863-chain-of-command-crew-collaboration.md`. **GitHub issue:** #835.
**Depends on:** AD-864 (`AssignmentDecision`). Build AD-864 first.

> Verified against live HEAD. Field-name and ctor-param corrections are baked in (see "Spec corrections").

---

## Goal

Make the org chart load-bearing. When a sub-task resolves to a worker in a department, the **department chief** is the delegating authority: the chief issues a validated `Order` to the qualified subordinate via `OrderManager`, respecting `authority_over`. Replaces direct worker-assignment with governed delegation. Honest-degrade to direct assignment when no chief / out-of-chain / OrderManager unavailable.

## New module

`src/probos/cognitive/crew_delegation.py` (Cognitive layer).

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class DelegationDecision:
    spec_id: str
    chief_agent_id: str | None      # the delegating authority
    worker_agent_id: str | None     # the resolved subordinate
    order_id: str | None            # OrderManager order id when delegation succeeded
    delegated: bool                 # True only when an Order was issued in-chain
    reason: str                     # "delegated_via_chief" | "direct_no_chief"
                                    # | "out_of_chain" | "self_assigned" | "unresolved"

class CrewDelegator:
    def __init__(self, *, ontology, order_manager, agent_registry) -> None: ...
    def delegate(self, decision: "AssignmentDecision") -> DelegationDecision: ...
```

## Verified collaborator APIs (use exactly these)

- `OrderManager.issue_order(*, from_agent_id: str, to_post_id: str, directive: str, ttl_seconds: int | None = None, metadata: dict | None = None) -> Order | None` (`src/probos/cognitive/orders.py`, issue_order). **Keyword-only.** Returns `None` on `out_of_chain` rejection (when `to_post_id not in from_post.authority_over`).
- `Order.id` is the order identifier (orders.py:59). **Not `order.order_id`.**
- `OrderManager.__init__(self, *, ontology, registry, emit_event=None, max_active_per_post=8, default_ttl=..., standing_order_predicate=None)` — the agent-registry param is named **`registry`**, not `agent_registry`. (Relevant only for the test fixture that constructs a real OrderManager.)
- `VesselOntologyService.get_post_for_agent(agent_type: str) -> Post | None` (service.py:165) — takes **agent_type**.
- `VesselOntologyService.get_agent_department(agent_type: str) -> str | None` (service.py:159).
- `VesselOntologyService.get_chain_of_command(post_id: str) -> list[Post]` (service.py:126).
- `VesselOntologyService.get_agents_for_post(post_id: str) -> list[Assignment]` (service.py:177) — returns `Assignment`s; the live chief agent id is `assignment.agent_id` (**may be `None`** if the post is unwired → degrade).
- `VesselOntologyService.get_subordinate_agent_types(agent_type: str) -> list[str]` (service.py:181).
- `Post` fields (models.py:33): **`id`** (the post id — NOT `post_id`), `title`, `department_id`, `reports_to`, `authority_over: list[str]`, `tier: str = "crew"`, `capabilities`, `does_not_have`, `required_qualifications`.
- `Assignment` fields (models.py:47): `agent_type`, `post_id`, `callsign`, `watches`, `agent_id: str | None = None`.
- `AgentRegistry.get(agent_id) -> BaseAgent | None`; `BaseAgent.agent_type`, `BaseAgent.id`.

## Algorithm

`decision` is the AD-864 `AssignmentDecision`. If `decision.agent_id is None` → return `DelegationDecision(..., reason="unresolved", delegated=False)` immediately.

1. Resolve the worker's agent_type via `agent_registry.get(decision.agent_id).agent_type`; then `worker_post = ontology.get_post_for_agent(worker_agent_type)`; worker dept = `worker_post.department_id`. If no post → honest-degrade direct (`reason="direct_no_chief"`).
2. **Find the chief**: the post in the same department whose `authority_over` includes `worker_post.id`. Walk `ontology.get_chain_of_command(worker_post.id)` to the first superior whose `department_id == worker_post.department_id` and whose `authority_over` contains `worker_post.id`. Resolve the chief's live `agent_id` via `ontology.get_agents_for_post(chief_post.id)` → first assignment with a non-`None` `agent_id`.
3. **Chief found & in-chain** (`worker_post.id in chief_post.authority_over`) → `order = order_manager.issue_order(from_agent_id=chief_agent_id, to_post_id=worker_post.id, directive=<spec title/description>)`. On non-`None` order → `delegated=True`, `order_id=order.id`, reason `"delegated_via_chief"`. On `None` (rejected) → reason `"out_of_chain"`, `delegated=False` (worker still keeps the work directly).
4. **Worker IS the chief** (no in-department superior with authority over it) → reason `"self_assigned"`, `delegated=False`. A chief can execute its own department's leaf task; worker keeps the assignment.
5. **No chief / chief unwired (agent_id None) / OrderManager unavailable** → honest-degrade direct (`reason="direct_no_chief"`, `delegated=False`). The worker still gets the work; we just couldn't route it through a chief.

`worker_agent_id` is always carried (it's what lands in `WorkItem.assigned_to` in AD-867). `chief_agent_id`/`order_id` are recorded for provenance.

Wrap collaborator calls in Tier-2 log-and-degrade — a delegation failure must never propagate into the dispatch path.

---

## Tests — `tests/test_ad865_crew_delegation.py` (≥9)

**BF-287 (HARD):** **real** `VesselOntologyService`, **real** `OrderManager` (constructed with `registry=<real AgentRegistry>, ontology=<real ontology>`), **real** `AgentRegistry`. No MagicMock at these boundaries.

1. Chief delegates to a subordinate → `Order` issued, `delegated=True`, `order_id` set, reason `"delegated_via_chief"`.
2. Worker-is-chief → reason `"self_assigned"`, `delegated=False`.
3. Cross-department / fabricated out-of-chain pair → `issue_order` returns `None` → reason `"out_of_chain"`, `delegated=False`.
4. No chief in the department → reason `"direct_no_chief"`.
5. OrderManager unavailable (None injected) → degrade direct, no raise.
6. `order_id` carried through correctly from `order.id`.
7. Chief post wired but `agent_id is None` (unwired) → degrade direct.
8. `authority_over` actually enforced — a worker whose post is NOT in the chief's `authority_over` is rejected, not forced.
9. `decision.agent_id is None` (unresolved upstream) → reason `"unresolved"`, no order attempt.

Run:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad865_crew_delegation.py -q -n 0
```

---

## Do NOT build / change

- The runtime orchestrator (AD-867).
- `OrderManager`'s validation logic — consume it as-is.
- Order auto-acknowledgement or the duty state machine.
- Do not mutate WorkItems here (that's AD-867 reading these decisions).

## Highest-risk constraints (restated)

- It is `Post.id`, **not** `Post.post_id`. It is `order.id`, **not** `order.order_id`.
- `issue_order` is keyword-only and returns `None` on out-of-chain — treat `None` as the governed rejection, do not retry/force.
- `get_agents_for_post` returns `Assignment`s; the chief id is `assignment.agent_id` and may be `None` → degrade.
- Never raise out of `delegate`. Direct-assignment degrade is always a valid outcome.

## Tracking

PROGRESS.md AD-865 entry; commit impl; `docs(AD-865)` for corrections; close #835.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Spec corrections (file:line evidence)

| Spec claim | Reality | Evidence |
|---|---|---|
| `Post.post_id` / `worker_post_id` | Field is `Post.id`; department is `Post.department_id` | models.py:33 |
| `order.id` access | `Order.id` exists | orders.py:59 |
| OrderManager ctor `agent_registry` | Param is `registry` | orders.py (OrderManager.__init__, `*, ontology, registry, ...`) |
| `get_agents_for_post` yields agent ids | Returns `list[Assignment]`; id via `.agent_id` (nullable) | service.py:177, models.py:47 |
