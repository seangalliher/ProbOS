# AD-595e: Qualification Gate Enforcement

**Issue:** (AD-595 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-595a (BilletRegistry — COMPLETE), AD-595b (naming ceremony wiring — COMPLETE), AD-595c (standing orders templating — COMPLETE), AD-595d (qualification data model + check API — COMPLETE), AD-618b (BillRuntime — COMPLETE)
**Files:** `src/probos/config.py` (EDIT), `src/probos/events.py` (EDIT), `src/probos/sop/runtime.py` (EDIT), `src/probos/proactive.py` (EDIT), `src/probos/cognitive/cognitive_agent.py` (EDIT), `src/probos/ontology/billet_registry.py` (EDIT), `tests/test_ad595e_qualification_gate.py` (NEW)

## Problem

AD-595d delivered `check_qualifications()` and `assign_qualified()` on BilletRegistry — the qualification check API. AD-618b's `_assign_role()` already filters bill role candidates by qualification. But there is **no enforcement at the cognitive pipeline level**: an agent assigned to a billet with `required_qualifications` can still receive intents, execute proactive duties, and participate in Ward Room dispatch without any qualification check. The check API exists but nothing calls it outside of bill activation.

AD-595e adds enforcement gates at three points:

1. **Bill step execution** — `BillRuntime.start_step()` should verify the assigned agent still holds required qualifications before allowing step start.
2. **Proactive duty dispatch** — `ProactiveCognitiveLoop` should check whether the agent's billet has qualification requirements and whether they're met before dispatching duties that require specific qualifications.
3. **Cognitive pipeline awareness** — `CognitiveAgent.decide()` should have a lightweight qualification status injected into context so agents are aware of their qualification standing (what they hold, what's missing), enabling informed self-regulation.

**Design constraints:**
- **Graceful degradation**: If QualificationStore is unavailable or not wired, all gates default to ALLOW. No qualification enforcement blocks normal operation during cold start.
- **Config toggle**: A single `enforcement_enabled` flag in `QualificationConfig` controls whether gates actively block (True) or only log/warn (False, default). This allows incremental rollout.
- **Feedback, not silent rejection**: When an agent is blocked, the system provides a clear reason (which qualifications are missing) via events and log messages. The agent receives structured feedback, not a silent failure.
- **Cold-start tolerance**: Agents with no test results are always allowed through (matches `allow_untested=True` default from AD-595d).

**What this does NOT include:**
- Ward Room routing qualification gates (future — routing is trust-based, not qualification-based)
- Automatic re-qualification scheduling when an agent fails a gate (future — AD-566c drift detection handles periodic re-testing)
- HXI surface for qualification enforcement status (future — AD-595f)

---

## Section 1: Config — Add Enforcement Toggle

**File:** `src/probos/config.py` (EDIT)

Add an enforcement toggle to the existing `QualificationConfig` class (line ~1017). Insert after the existing `test_timeout_seconds` field:

```python
    # AD-595e: Qualification gate enforcement
    enforcement_enabled: bool = False  # When True, gates actively block; when False, log-only
    enforcement_log_only: bool = True  # When True + enforcement_enabled, log warnings but don't block
```

**Why two flags:** `enforcement_enabled` is the master switch. `enforcement_log_only` enables "shadow mode" — enforcement logic runs and logs warnings but doesn't actually block, letting operators observe what WOULD be blocked before flipping to active enforcement.

### Verified insertion point

The `QualificationConfig` class is at config.py line 1017. Add the two new fields after `test_timeout_seconds: float = 60.0` (line 1023) and before `# AD-642: Communication Quality Benchmarks`:

```python
class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True
    significance_threshold: float = 0.15
    test_timeout_seconds: float = 60.0

    # AD-595e: Qualification gate enforcement
    enforcement_enabled: bool = False  # Master switch: run gate checks at all
    enforcement_log_only: bool = True  # Shadow mode: log warnings but don't block

    # AD-642: Communication Quality Benchmarks
    communication_benchmarks: CommunicationBenchmarksConfig = CommunicationBenchmarksConfig()
    # ... rest unchanged
```

---

## Section 2: Events — Add Qualification Gate Event

**File:** `src/probos/events.py` (EDIT)

Add a new event type after the existing `QUALIFICATION_DRIFT_DETECTED` entry (line ~145):

```python
    QUALIFICATION_GATE_BLOCKED = "qualification_gate_blocked"  # AD-595e
```

This event fires when an agent is blocked (or would be blocked in log-only mode) by a qualification gate. Payload includes `agent_id`, `agent_type`, `gate` (which enforcement point), `missing_qualifications`, and `log_only` (whether it was actually blocked or just warned).

---

## Section 3: BilletRegistry — Add Qualification Summary Helper

**File:** `src/probos/ontology/billet_registry.py` (EDIT)

Add a lightweight method that returns an agent's qualification standing for their current billet. This is used by the cognitive pipeline to inject qualification awareness into agent context without a full async check on every decide() call.

Add after the `assign()` method (after line 323), before `_emit()`:

```python
    async def get_qualification_standing(
        self,
        agent_type: str,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """AD-595e: Get qualification standing for an agent's current billet.

        Returns a summary dict with:
        - billet_id: str — the agent's current billet
        - required: list[str] — required qualification test names
        - held: list[str] — qualifications the agent has passed
        - missing: list[str] — qualifications the agent has not passed
        - qualified: bool — True if all requirements met

        Returns empty dict if no billet found, no requirements, or
        QualificationStore unavailable.
        """
        # Find agent's billet from current assignments
        assignment = self._dept.get_assignment_for_agent(agent_type)
        if not assignment:
            return {}

        post = self._dept.get_post(assignment.post_id)
        if not post or not post.required_qualifications:
            return {}

        if not self._qualification_store:
            return {}

        # Resolve agent_id if not provided
        if not agent_id:
            agent_id = assignment.agent_id if assignment.agent_id else ""
        if not agent_id:
            return {}

        held: list[str] = []
        missing: list[str] = []
        for test_name in post.required_qualifications:
            result = await self._qualification_store.get_latest(agent_id, test_name)
            if result and result.passed:
                held.append(test_name)
            else:
                missing.append(test_name)

        return {
            "billet_id": post.id,
            "required": list(post.required_qualifications),
            "held": held,
            "missing": missing,
            "qualified": len(missing) == 0,
        }
```

**Import needed:** Add `Any` to the existing TYPE_CHECKING import if not already there. Check the import block — `Any` is already imported from `typing` at line 14. No new imports needed.

---

## Section 4: BillRuntime — Gate on Step Start

**File:** `src/probos/sop/runtime.py` (EDIT)

The `start_step()` method (line ~205) currently checks only that the step exists, is PENDING, and the instance is not terminal. Add a qualification check: verify the agent starting the step holds the qualifications required by their assigned role.

### Step 4a: Add qualification_config parameter to BillRuntime.__init__

Add an optional `qualification_config` parameter after `emit_event_fn`:

Current `__init__` signature (line 53):
```python
    def __init__(
        self,
        config: BillConfig | None = None,
        billet_registry: Any = None,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
    ) -> None:
```

New signature:
```python
    def __init__(
        self,
        config: BillConfig | None = None,
        billet_registry: Any = None,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
        qualification_config: Any = None,  # AD-595e
    ) -> None:
```

Add to `__init__` body after `self._definitions`:
```python
        self._qualification_config = qualification_config  # AD-595e
```

Add a setter for late binding:
```python
    def set_qualification_config(self, config: Any) -> None:
        """AD-595e: Late-bind qualification config for gate enforcement."""
        self._qualification_config = config
```

### Step 4b: Add qualification gate to start_step()

Modify `start_step()` (line ~205). Insert the qualification check **after** the existing step status/instance terminal checks but **before** actually transitioning the step state.

Current code (lines 218–224):
```python
        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status != StepStatus.PENDING:
            return False

        step_state.status = StepStatus.ACTIVE
```

New code:
```python
        step_state = instance.step_states.get(step_id)
        if not step_state or step_state.status != StepStatus.PENDING:
            return False

        # AD-595e: Qualification gate — check agent holds role qualifications
        if not await self._check_step_qualification(
            instance, step_id, agent_id, agent_type,
        ):
            return False

        step_state.status = StepStatus.ACTIVE
```

**IMPORTANT:** This changes `start_step()` from sync to async. Update the method signature:

```python
    async def start_step(
```

**Builder must check all callers of `start_step()`** and add `await` to each call site. Search for `start_step(` across the codebase:
- `src/probos/sop/runtime.py` (internal calls)
- Any test files that call it

### Step 4c: Add the gate check method

Add after `start_step()`:

```python
    async def _check_step_qualification(
        self,
        instance: BillInstance,
        step_id: str,
        agent_id: str,
        agent_type: str,
    ) -> bool:
        """AD-595e: Check if agent is qualified for the bill step's role.

        Returns True if:
        - Qualification enforcement is disabled
        - No BilletRegistry available
        - The step's role has no qualifications
        - The agent passes qualification checks

        Returns False (and emits event) only when enforcement is active
        and the agent lacks required qualifications.
        """
        # Gate 1: Is enforcement enabled?
        qc = self._qualification_config
        if not qc or not getattr(qc, 'enforcement_enabled', False):
            return True

        # Gate 2: Do we have a billet registry with qualification store?
        if not self._billet_registry:
            return True

        # Gate 3: Find the step's role and its qualifications
        # Look up the bill definition to get role qualifications
        defn = self._definitions.get(instance.bill_id)
        if not defn:
            return True

        # Find which role this step belongs to
        step_defn = None
        for s in defn.steps:
            if s.id == step_id:
                step_defn = s
                break
        if not step_defn or not step_defn.role:
            return True

        role_defn = defn.roles.get(step_defn.role)
        if not role_defn or not role_defn.qualifications:
            return True

        # Gate 4: Check qualifications via BilletRegistry
        try:
            qualified, missing = await self._billet_registry.check_qualifications(
                role_defn.id if hasattr(role_defn, 'id') else step_defn.role,
                agent_type,
                agent_id,
                allow_untested=True,  # Cold-start tolerance
            )
        except Exception:
            logger.debug(
                "AD-595e: Qualification check failed for step %s — allowing (graceful degradation)",
                step_id, exc_info=True,
            )
            return True

        if qualified:
            return True

        # Agent is NOT qualified
        log_only = getattr(qc, 'enforcement_log_only', True)
        logger.warning(
            "AD-595e: Agent %s (%s) lacks qualifications for step %s in bill %s — missing: %s%s",
            agent_id, agent_type, step_id, instance.bill_id, missing,
            " (log-only, allowing)" if log_only else " (BLOCKED)",
        )

        self._emit(EventType.QUALIFICATION_GATE_BLOCKED, {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "gate": "bill_step_start",
            "bill_id": instance.bill_id,
            "instance_id": instance.id,
            "step_id": step_id,
            "role_id": step_defn.role,
            "missing_qualifications": missing,
            "log_only": log_only,
        })

        return log_only  # If log_only, return True (allow); if enforcing, return False (block)
```

**Note on `check_qualifications()` call:** The method takes `(billet_id, agent_type, agent_id)`. For bill role qualification checks, we're checking whether the agent meets the role's qualification requirements, not whether they meet a specific billet's requirements. However, `check_qualifications()` looks up `post.required_qualifications` from the billet_id — if the bill role's qualifications don't map to a billet post, we need to check directly against the QualificationStore instead.

**Builder verification step:** Read `billet_registry.check_qualifications()` (line 167-225) carefully. It looks up `self._dept.get_post(billet_id)` and checks `post.required_qualifications`. For bill roles, the qualifications are on the `BillRole` object, NOT on the billet post. If the role qualifications don't align with a billet post, the builder must fall back to a direct QualificationStore check. In that case, replace the `check_qualifications()` call with:

```python
        # Direct qualification check against QualificationStore
        qual_store = getattr(self._billet_registry, '_qualification_store', None)
        if not qual_store:
            return True  # No store, graceful degradation

        missing: list[str] = []
        for test_name in role_defn.qualifications:
            result = await qual_store.get_latest(agent_id, test_name)
            if result is None:
                pass  # allow_untested = True
            elif not result.passed:
                missing.append(test_name)

        if not missing:
            return True

        # ... rest of the blocking/logging logic ...
```

---

## Section 5: ProactiveCognitiveLoop — Gate on Duty Dispatch

**File:** `src/probos/proactive.py` (EDIT)

The proactive loop dispatches duties to agents (line ~519). Before dispatching a duty, check if the agent's current billet has qualification requirements and whether they're met.

### Step 5a: Wire qualification config into proactive loop

Add a `_qualification_config` attribute. The proactive loop already has `set_config()` (line ~278) that receives `ProactiveCognitiveConfig`. Add a separate setter for qualification config.

Add after `self._orientation_service = None` (find the existing orientation setter pattern):

```python
        self._qualification_config = None  # AD-595e
        self._billet_registry = None       # AD-595e
```

Add setter methods:

```python
    def set_qualification_config(self, config: Any) -> None:
        """AD-595e: Set qualification config for duty dispatch gating."""
        self._qualification_config = config

    def set_billet_registry(self, registry: Any) -> None:
        """AD-595e: Set BilletRegistry for duty qualification checks."""
        self._billet_registry = registry
```

### Step 5b: Add qualification check before duty dispatch

In the `_run_agent_cycle()` method (or whichever method dispatches the duty — search for `duty = due_duties[0]` at line ~530), add a qualification gate after the duty is selected but before `handle_intent()` is called.

Insert after the duty selection (after `duty = due_duties[0]`, before the intent message construction):

```python
                # AD-595e: Qualification gate for duty dispatch
                if duty and duty.required_skills and self._qualification_config:
                    blocked = await self._check_duty_qualification(agent, duty)
                    if blocked:
                        continue  # Skip this agent, move to next
```

Add the gate check method to the class:

```python
    async def _check_duty_qualification(self, agent: Any, duty: Any) -> bool:
        """AD-595e: Check if agent holds qualifications for duty's required_skills.

        Returns True if the agent is BLOCKED (should skip), False if allowed.
        Degrades gracefully — returns False (allow) if any component is unavailable.
        """
        qc = self._qualification_config
        if not qc or not getattr(qc, 'enforcement_enabled', False):
            return False  # Not blocked

        if not self._billet_registry:
            return False  # No registry, can't check

        # Check qualification standing for this agent's billet
        try:
            standing = await self._billet_registry.get_qualification_standing(
                agent.agent_type,
                getattr(agent, 'id', ''),
            )
        except Exception:
            logger.debug(
                "AD-595e: Qualification standing check failed for %s — allowing",
                agent.agent_type, exc_info=True,
            )
            return False

        if not standing or standing.get("qualified", True):
            return False  # Qualified or no requirements

        missing = standing.get("missing", [])
        log_only = getattr(qc, 'enforcement_log_only', True)

        logger.warning(
            "AD-595e: %s lacks qualifications for duty '%s' — missing: %s%s",
            agent.agent_type, duty.duty_id, missing,
            " (log-only, allowing)" if log_only else " (BLOCKED)",
        )

        if hasattr(self, '_on_event') and self._on_event:
            self._on_event({
                "type": "qualification_gate_blocked",
                "data": {
                    "agent_id": getattr(agent, 'id', ''),
                    "agent_type": agent.agent_type,
                    "gate": "proactive_duty",
                    "duty_id": duty.duty_id,
                    "missing_qualifications": missing,
                    "log_only": log_only,
                },
            })

        return not log_only  # Blocked only when not log-only
```

**Note:** The proactive loop uses `self._on_event` (a callback from constructor `on_event` param) for event emission, not `_emit_event_fn`. Builder should verify the event emission pattern by grepping for `self._on_event` in `proactive.py`.

---

## Section 6: CognitiveAgent — Qualification Context Injection

**File:** `src/probos/cognitive\cognitive_agent.py` (EDIT)

Rather than gating `decide()` (which would block all cognitive processing), inject qualification standing as context into the agent's observation. This enables agents to self-regulate: they know what they're qualified for and what they're not, and can factor this into their responses.

### Step 6a: Add qualification standing cache

Add to `__init__` after the working memory initialization (around line 100):

```python
        # AD-595e: Qualification standing cache — refreshed periodically, not per-decide()
        self._qualification_standing: dict[str, Any] = {}
        self._qualification_standing_ts: float = 0.0
        self._qualification_standing_ttl: float = 300.0  # Refresh every 5 minutes
```

### Step 6b: Add method to refresh qualification standing

Add to the class (after the existing `_check_procedural_memory` method or in a logical location):

```python
    async def _refresh_qualification_standing(self) -> dict[str, Any]:
        """AD-595e: Refresh qualification standing from BilletRegistry.

        Cached to avoid per-decide() async lookups. Returns empty dict
        if BilletRegistry or QualificationStore is unavailable.
        """
        now = time.monotonic()
        if now - self._qualification_standing_ts < self._qualification_standing_ttl:
            return self._qualification_standing

        self._qualification_standing_ts = now

        runtime = self._runtime
        if not runtime:
            return self._qualification_standing

        billet_reg = None
        if hasattr(runtime, 'ontology') and runtime.ontology:
            billet_reg = getattr(runtime.ontology, 'billet_registry', None)
        if not billet_reg:
            return self._qualification_standing

        try:
            standing = await billet_reg.get_qualification_standing(
                self.agent_type,
                self.id,
            )
            self._qualification_standing = standing
        except Exception:
            logger.debug(
                "AD-595e: Qualification standing refresh failed for %s",
                self.agent_type, exc_info=True,
            )

        return self._qualification_standing
```

### Step 6c: Inject qualification context into decide()

In the `decide()` method, **after** the decision cache lookup block (after line ~1160, the cache miss line) and **before** the procedural memory check (line ~1163), add:

```python
        # AD-595e: Inject qualification standing into observation context
        qual_standing = await self._refresh_qualification_standing()
        if qual_standing and qual_standing.get("missing"):
            observation["_qualification_standing"] = qual_standing
```

This adds `_qualification_standing` to the observation dict only when there are missing qualifications — agents with all qualifications met (or no requirements) don't get extra context noise.

The `_` prefix follows the existing convention for metadata injected into observations (e.g., `_augmentation_skill_instructions`, `_qualification_test`).

---

## Section 7: Startup Wiring

**File:** `src/probos/startup/finalize.py` (EDIT)

Wire the qualification config and billet registry into the proactive loop and BillRuntime.

### Step 7a: Wire into ProactiveCognitiveLoop

After the existing proactive loop setup (after `await proactive_loop.start()` around line 88), add:

```python
        # AD-595e: Wire qualification gate dependencies into proactive loop
        if getattr(runtime, '_qualification_store', None):
            proactive_loop.set_qualification_config(config.qualification)
        if runtime.ontology and runtime.ontology.billet_registry:
            proactive_loop.set_billet_registry(runtime.ontology.billet_registry)
```

### Step 7b: Wire into BillRuntime

After the existing AD-618d BillRuntime wiring block (after line 129 `logger.info("AD-618d: BillRuntime wired")`), add:

```python
        # AD-595e: Wire qualification enforcement config into BillRuntime
        if getattr(runtime, '_bill_runtime', None):
            runtime._bill_runtime.set_qualification_config(config.qualification)
```

---

## Section 8: Tests

**File:** `tests/test_ad595e_qualification_gate.py` (NEW)

### Test categories (14 tests):

**BillRuntime gate tests (6 tests):**

1. `test_start_step_allowed_when_enforcement_disabled` — `enforcement_enabled=False`, agent lacking qualifications, step starts successfully.
2. `test_start_step_allowed_when_no_qualifications_required` — Role has empty `qualifications` list, step starts regardless of config.
3. `test_start_step_blocked_when_enforcement_active` — `enforcement_enabled=True, enforcement_log_only=False`, agent missing a required qualification, `start_step()` returns False.
4. `test_start_step_logged_but_allowed_in_shadow_mode` — `enforcement_enabled=True, enforcement_log_only=True`, agent missing qualification, `start_step()` returns True, `QUALIFICATION_GATE_BLOCKED` event emitted with `log_only=True`.
5. `test_start_step_allowed_when_qualification_store_unavailable` — BilletRegistry has no QualificationStore wired, step starts (graceful degradation).
6. `test_start_step_allowed_for_untested_agent` — Agent has no test results at all (`allow_untested=True` behavior), step starts.

**ProactiveCognitiveLoop gate tests (4 tests):**

7. `test_duty_dispatch_allowed_when_enforcement_disabled` — Default config, duty dispatches normally.
8. `test_duty_dispatch_blocked_when_enforcement_active` — Agent's billet has requirements, agent lacks qualification, duty is skipped.
9. `test_duty_dispatch_allowed_in_shadow_mode` — Log-only mode, duty dispatches with warning logged.
10. `test_duty_dispatch_allowed_when_no_billet_registry` — No billet registry wired, duty dispatches (graceful degradation).

**CognitiveAgent context injection tests (3 tests):**

11. `test_qualification_standing_injected_when_missing` — Agent has missing qualifications, `_qualification_standing` appears in observation dict.
12. `test_qualification_standing_not_injected_when_fully_qualified` — Agent passes all qualifications, no `_qualification_standing` in observation.
13. `test_qualification_standing_cached` — Second `decide()` call within TTL uses cached standing (no second async call to BilletRegistry).

**Event emission test (1 test):**

14. `test_gate_blocked_event_payload` — Verify `QUALIFICATION_GATE_BLOCKED` event payload contains `agent_id`, `agent_type`, `gate`, `missing_qualifications`, and `log_only` fields.

### Test implementation guidance

- Use `unittest.mock.AsyncMock` for `QualificationStore.get_latest()` to control pass/fail results.
- Create minimal `BillDefinition` and `BillRole` with `qualifications=["test_x"]`.
- Create `QualificationConfig(enforcement_enabled=True, enforcement_log_only=False)` for active enforcement tests.
- For CognitiveAgent tests, mock `self._runtime.ontology.billet_registry.get_qualification_standing()` to return controlled standing dicts.
- For ProactiveCognitiveLoop tests, create a minimal agent mock with `agent_type`, `id`, and `handle_intent` attributes.

---

## Engineering Principles Compliance

- **SOLID/S** — Each enforcement point has a single gate check method. BilletRegistry owns qualification standing queries. BillRuntime owns step-level gating. ProactiveCognitiveLoop owns duty-level gating.
- **SOLID/O** — Enforcement added via new methods and config fields, not modifying existing check logic. `check_qualifications()` (AD-595d) is unchanged.
- **SOLID/D** — Gates depend on `QualificationConfig` abstraction (Pydantic model), not hardcoded thresholds. BilletRegistry accessed via runtime wiring, not direct construction.
- **Law of Demeter** — `get_qualification_standing()` encapsulates the multi-step lookup (find assignment → find post → check qualifications). Callers don't reach through billet registry internals.
- **Fail Fast (log-and-degrade)** — All gates default to ALLOW on any exception or missing dependency. This is non-critical enforcement — the system works without it, it just works better with it.
- **Defense in Depth** — Three layers of gating (bill step, proactive duty, cognitive awareness). Each can be independently enabled/disabled. Config toggle provides operational control.
- **DRY** — `get_qualification_standing()` is the single source for qualification status, reused by both proactive loop and cognitive agent. `check_qualifications()` (AD-595d) is reused by BillRuntime gate.
- **Cloud-Ready Storage** — No new storage. Reuses existing `QualificationStore` via `ConnectionFactory`.

---

## Tracker Updates

After all tests pass:

1. **PROGRESS.md** — Add entry:
   ```
   AD-595e COMPLETE. Qualification Gate Enforcement — enforcement gates at bill step start (BillRuntime), proactive duty dispatch, and cognitive pipeline context injection. Config toggle (enforcement_enabled/enforcement_log_only) for shadow mode rollout. Graceful degradation: all gates default to ALLOW when QualificationStore unavailable. QUALIFICATION_GATE_BLOCKED event emission. 14 tests.
   ```

2. **docs/development/roadmap.md** — Update the AD-595e row status to Closed.

3. **DECISIONS.md** — Add entry:
   ```
   ### AD-595e — Qualification Gate Enforcement (2026-04-26)
   **Context:** AD-595d delivered check_qualifications() API but nothing enforced it outside bill role assignment. Agents could execute duties and bill steps without holding required qualifications.
   **Decision:** Three enforcement layers: (1) BillRuntime.start_step() checks role qualifications before step execution, (2) ProactiveCognitiveLoop checks billet standing before duty dispatch, (3) CognitiveAgent.decide() injects qualification standing into observation context for agent self-awareness. All gates default to ALLOW (graceful degradation). Two-flag config: enforcement_enabled (master switch) + enforcement_log_only (shadow mode). Cold-start tolerance via allow_untested=True. start_step() becomes async to support qualification store lookup.
   **Consequences:** Qualification system moves from "check API exists" to "system actually uses it." Shadow mode enables observation before enforcement. Agents gain self-awareness of their qualification gaps. Breaking change: start_step() sync→async requires updating all call sites.
   ```
