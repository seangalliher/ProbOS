# AD-647c v1 — Process Chains Bills/Watch Bill Integration

**Closes:** GH issue #405
**Status:** Wave 49 main prompt
**Depends on:** AD-647 (Wave 34), AD-647b (Wave 48), AD-618a-e (Bills, shipped), AD-595a-e (Watch Bill, shipped)
**Estimated tests:** 12 new (over Captain's 10 floor by 2)

> **Single-line summary.** Bridge process chains to Bills + Watch Bill: `ProcessChainStep` gains `bill_step_id` and `assigned_role` optional fields; `ProcessChainExecutor` records step-completion against the active `BillInstance` and resolves role-assigned agents via `BilletRegistry`/`BillRuntime`; `ProcessChainRegistry.register_bill_chain()` validates step bill mappings at registration. CONSULT step kind added (semantic label only — executor already awaits async handlers). NATS coupling deferred to AD-641g (#403, separate large issue). Suspend/resume across process restart deferred to future AD-647d (no GH issue v1).

---

## Why this work, why now

AD-647 (Wave 34) shipped the chain executor scaffold. AD-647b (Wave 48) shipped the chain registry + base-class hook. AD-618a-e (Bills) and AD-595a-e (Watch Bill) shipped independently. All four substrates are live, but no chain currently maps to a Bill — meaning Watch Bill role assignments and Bill step lifecycle do **not** flow through chain execution. AD-647c closes that gap for the OSS scope; the NATS cognitive pipeline (AD-641g #403) layers on top of this without modifying it.

---

## Architect Decision Log

**DLog #1 — field naming `bill_step_id` not `bill_id`.** User spec called the field `bill_id`, but `bill_id` is overloaded across the Bills surface (`BillDefinition.bill` is the bill slug; `BillInstance.bill_id` is the slug too). The chain step's field maps to `BillStep.id` (`sop/schema.py:60`), which is the **step id within a bill**. Naming it `bill_step_id` removes the ambiguity at no cost. The bill-instance correlation is supplied by the caller via `context["bill_instance_id"]` at run-time — orthogonal field, not on the step.

**DLog #2 — CONSULT step kind: semantic label only, NO executor change.** The current executor (`process_chains.py:131`) already runs `step_output = await step.handler(running)`, which natively supports `async def __call__` handlers that internally await any async resource (`asyncio.Event`, ward-room thread, consultation workspace decision). CONSULT thus ships as an enum value with **identical executor behavior to TRANSFORM**; it exists to give chain authors a semantic label for human-in-the-loop / cross-agent steps. **Suspend-and-resume across process restart** (handler returns a Future to be persisted and re-awaited later) requires checkpointing infrastructure and is **out of scope** — deferred to future AD-647d (no GH issue filed v1; documented in module docstring + this prompt only).

**DLog #3 — `runtime.bill_runtime` public property added.** At HEAD, `runtime._bill_runtime` is private (`runtime.py:515/1553`) with no public alias. AD-635 documented the same gap retrospectively for `_emergent_detector`. AD-647c can't ship without bill access from the executor; rather than recreate the AD-635 `getattr(rt, "_bill_runtime", None)` Demeter exception, this prompt adds a 1-line public property `runtime.bill_runtime` mirroring the `runtime.billet_registry` shape (`runtime.py:985`). Wave 5 conv #1 compliant.

**DLog #4 — executor takes `bill_runtime` via ctor injection.** Same shape as `emit_event=`. Default `None` → executor skips all bill plumbing → AD-647 + AD-647b backward compatibility preserved. Old call sites (`scout.py:525` `ProcessChainExecutor()`) keep working unchanged.

**DLog #5 — three bill-coupling guards (defense in depth).** Bill recording fires only when **all three** are true: `step.bill_step_id != ""` AND `context.get("bill_instance_id")` AND `self._bill_runtime is not None`. Any one missing → executor behaves exactly as v1 (no bill side-effects). Test #4 + Test #9 enforce this.

**DLog #6 — role resolution: log-and-degrade (tier 2).** When `step.assigned_role` is set but the BillInstance has no matching role assignment (or the bill instance lookup fails), executor logs a WARNING and proceeds without injecting `_resolved_agent_id`. Handler still runs. The "fall back to chain owner agent" phrasing in the user spec maps to "the agent that owned the original chain invocation" — which is whatever the caller put in the context dict (typically `context["_agent"]` per AD-647b convention). Executor does **not** synthesize a fall-back identity; it simply omits `_resolved_agent_id` and lets the handler decide.

**DLog #7 — `register_bill_chain` lives on `ProcessChainRegistry`.** Method, not module-level helper — keeps registry as the single registration surface (Open/Closed). Validation: every `step.bill_step_id` value (when non-empty) must appear in the bill's `step.id` set. Mismatch → `ValueError` at registration time (fail-fast). After validation, the chain is registered via the existing `register_chain()` path.

**DLog #8 — Bill recording wraps `complete_step` / `fail_step` in tier-2 log-and-degrade.** `BillRuntime.complete_step` / `fail_step` return `bool` (True/False) and log internally; they don't raise. Even so, executor wraps each call in `try/except Exception → logger.warning` so a bill-side bug can never propagate up into chain execution. **Chain execution is the source of truth for chain success; Bills tracking is a secondary observability surface.**

---

## Section 0 — New Step Kind

`ProcessChainStepKind` gains one new value:

```python
CONSULT = "consult"
```

Inserted after `NOTIFY` in the enum body. Docstring extended:

```
CONSULT   — human-in-the-loop or cross-agent consultation (handler awaits an
            external resource like asyncio.Event, ward-room thread, or
            ConsultationWorkspace decision). Behaviorally identical to
            TRANSFORM in v1; suspend/resume across process restart is NOT
            supported (future AD-647d).
```

No other enum changes. Existing 4 values unchanged.

---

## Section 1 — `ProcessChainStep` field additions

**File:** `src/probos/cognitive/process_chains.py`

### 1a. Add CONSULT to enum

```python
SEARCH:
class ProcessChainStepKind(str, Enum):
    """Lifecycle stage of a process-chain step.

    QUERY     — gather data from a source (HTTP, DB, FS, ontology).
    TRANSFORM — classify / enrich / filter (may call LLM in future; v1 callable only).
    STORE     — persist artifact (file, journal, ChromaDB, knowledge store).
    NOTIFY    — route to consumer (Ward Room, DM, channel adapter, queue).
    """
    QUERY = "query"
    TRANSFORM = "transform"
    STORE = "store"
    NOTIFY = "notify"

REPLACE:
class ProcessChainStepKind(str, Enum):
    """Lifecycle stage of a process-chain step.

    QUERY     — gather data from a source (HTTP, DB, FS, ontology).
    TRANSFORM — classify / enrich / filter (may call LLM in future; v1 callable only).
    STORE     — persist artifact (file, journal, ChromaDB, knowledge store).
    NOTIFY    — route to consumer (Ward Room, DM, channel adapter, queue).
    CONSULT   — human-in-the-loop or cross-agent consultation; handler awaits an
                external resource (asyncio.Event, ward-room thread, ConsultationWorkspace
                decision). Behaviorally identical to TRANSFORM in v1; suspend/resume
                across process restart is NOT supported (future AD-647d).
    """
    QUERY = "query"
    TRANSFORM = "transform"
    STORE = "store"
    NOTIFY = "notify"
    CONSULT = "consult"
```

### 1b. Add `bill_step_id` and `assigned_role` to `ProcessChainStep`

```python
SEARCH:
@dataclass(frozen=True)
class ProcessChainStep:
    """A single typed step in a process chain.

    `kind`     — one of ProcessChainStepKind
    `name`     — human-readable label, unique within a definition
    `handler`  — async callable conforming to ProcessChainHandler

    LLM prompt-template handlers are NOT supported in v1; the
    `prompt_template_id` field is reserved for AD-647b.
    """
    kind: ProcessChainStepKind
    name: str
    handler: ProcessChainHandler
    prompt_template_id: str = ""  # reserved for AD-647b; must be "" in v1

REPLACE:
@dataclass(frozen=True)
class ProcessChainStep:
    """A single typed step in a process chain.

    `kind`           — one of ProcessChainStepKind
    `name`           — human-readable label, unique within a definition
    `handler`        — async callable conforming to ProcessChainHandler
    `bill_step_id`   — AD-647c: BillStep.id this chain step satisfies; empty string
                       means no bill linkage. When set AND the executor's caller
                       supplies ``context["bill_instance_id"]``, the executor will
                       call ``bill_runtime.complete_step(...)`` / ``fail_step(...)``
                       against that BillInstance step on chain step success/failure.
    `assigned_role`  — AD-647c: BillRole id whose holder agent should run this step.
                       When set AND the active BillInstance has a matching
                       ``role_assignments[role]`` entry, the resolved agent_id is
                       injected into the running context as
                       ``_resolved_agent_id_<step.name>``. Unresolved → log-and-degrade.

    LLM prompt-template handlers are NOT supported in v1; the
    `prompt_template_id` field is reserved for AD-647b.
    """
    kind: ProcessChainStepKind
    name: str
    handler: ProcessChainHandler
    prompt_template_id: str = ""  # reserved for AD-647b; must be "" in v1
    bill_step_id: str = ""        # AD-647c
    assigned_role: str = ""       # AD-647c
```

---

## Section 2 — `ProcessChainExecutor` ctor + Bill plumbing

### 2a. Ctor accepts `bill_runtime`

```python
SEARCH:
    def __init__(self, *, emit_event: Callable[[str, dict], Any] | None = None) -> None:
        self._emit_event = emit_event

REPLACE:
    def __init__(
        self,
        *,
        emit_event: Callable[[str, dict], Any] | None = None,
        bill_runtime: Any = None,  # AD-647c: optional BillRuntime for step lifecycle recording
    ) -> None:
        self._emit_event = emit_event
        self._bill_runtime = bill_runtime
```

### 2b. `run()` resolves BillInstance once + threads role assignments + records step lifecycle

Replace the existing `run` method body. SEARCH/REPLACE block:

```python
SEARCH:
    async def run(
        self,
        definition: ProcessChainDefinition,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the chain. Returns the final accumulated context."""
        if not definition.steps:
            raise ProcessChainExecutionError(
                definition.name, "<none>", ValueError("empty chain definition")
            )

        running: dict[str, Any] = dict(context) if context else {}
        chain_started = time.monotonic()

        for step in definition.steps:
            step_started = time.monotonic()
            try:
                step_output = await step.handler(running)
            except Exception as exc:
                logger.warning(
                    "AD-647: process chain '%s' step '%s' (%s) raised %s",
                    definition.name, step.name, step.kind.value, type(exc).__name__,
                    exc_info=True,
                )
                raise ProcessChainExecutionError(definition.name, step.name, exc) from exc

            if step_output is None:
                step_output = {}
            if not isinstance(step_output, dict):
                raise ProcessChainExecutionError(
                    definition.name,
                    step.name,
                    TypeError(
                        f"handler must return dict | None, got {type(step_output).__name__}"
                    ),
                )

            running.update(step_output)
            logger.debug(
                "AD-647: process chain '%s' step '%s' (%s) ok in %.1fms",
                definition.name, step.name, step.kind.value,
                (time.monotonic() - step_started) * 1000.0,
            )

        logger.info(
            "AD-647: process chain '%s' completed (%d steps, %.1fms)",
            definition.name, len(definition.steps),
            (time.monotonic() - chain_started) * 1000.0,
        )
        return running

REPLACE:
    async def run(
        self,
        definition: ProcessChainDefinition,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the chain. Returns the final accumulated context.

        AD-647c: when ``self._bill_runtime`` is set AND
        ``context["bill_instance_id"]`` is supplied, step lifecycle events
        (complete / fail) are recorded against the corresponding ``BillInstance``
        step (resolved by ``ProcessChainStep.bill_step_id``). Bill recording is
        tier-2 log-and-degrade — bill-side errors never break chain execution.
        """
        if not definition.steps:
            raise ProcessChainExecutionError(
                definition.name, "<none>", ValueError("empty chain definition")
            )

        running: dict[str, Any] = dict(context) if context else {}
        chain_started = time.monotonic()

        # AD-647c: resolve BillInstance once at chain start (cheap dict lookup).
        bill_instance = self._resolve_bill_instance(running)

        for step in definition.steps:
            step_started = time.monotonic()

            # AD-647c: inject resolved agent for assigned_role (if any).
            if step.assigned_role and bill_instance is not None:
                self._inject_resolved_agent(running, step, bill_instance)

            try:
                step_output = await step.handler(running)
            except Exception as exc:
                logger.warning(
                    "AD-647: process chain '%s' step '%s' (%s) raised %s",
                    definition.name, step.name, step.kind.value, type(exc).__name__,
                    exc_info=True,
                )
                # AD-647c: record bill step failure (tier-2 log-and-degrade).
                self._record_bill_step_failure(bill_instance, step, exc, running)
                raise ProcessChainExecutionError(definition.name, step.name, exc) from exc

            if step_output is None:
                step_output = {}
            if not isinstance(step_output, dict):
                raise ProcessChainExecutionError(
                    definition.name,
                    step.name,
                    TypeError(
                        f"handler must return dict | None, got {type(step_output).__name__}"
                    ),
                )

            running.update(step_output)
            # AD-647c: record bill step completion (tier-2 log-and-degrade).
            self._record_bill_step_completion(bill_instance, step, step_output, running)

            logger.debug(
                "AD-647: process chain '%s' step '%s' (%s) ok in %.1fms",
                definition.name, step.name, step.kind.value,
                (time.monotonic() - step_started) * 1000.0,
            )

        logger.info(
            "AD-647: process chain '%s' completed (%d steps, %.1fms)",
            definition.name, len(definition.steps),
            (time.monotonic() - chain_started) * 1000.0,
        )
        return running

    # ------------------------------------------------------------------
    # AD-647c: Bills/Watch Bill integration helpers (tier-2 log-and-degrade)
    # ------------------------------------------------------------------

    def _resolve_bill_instance(self, running: dict[str, Any]) -> Any:
        """Resolve the active BillInstance from context, or None.

        Three guards (defense in depth): bill_runtime present AND
        context.bill_instance_id present AND lookup succeeds.
        """
        if self._bill_runtime is None:
            return None
        instance_id = running.get("bill_instance_id")
        if not instance_id:
            return None
        try:
            return self._bill_runtime.get_instance(instance_id)
        except Exception as exc:
            logger.warning(
                "AD-647c: bill_runtime.get_instance(%r) raised %s; chain proceeds without bill linkage",
                instance_id, type(exc).__name__,
            )
            return None

    def _inject_resolved_agent(
        self,
        running: dict[str, Any],
        step: ProcessChainStep,
        bill_instance: Any,
    ) -> None:
        """Resolve assigned_role -> agent_id via BillInstance.role_assignments.

        Unresolved roles log-and-degrade — handler still runs, just without
        the ``_resolved_agent_id_<step>`` hint in context.
        """
        try:
            assignments = getattr(bill_instance, "role_assignments", {}) or {}
            assignment = assignments.get(step.assigned_role)
            if assignment is None:
                logger.warning(
                    "AD-647c: chain step '%s' assigned_role '%s' has no holder in BillInstance %s; "
                    "handler will run without resolved agent",
                    step.name, step.assigned_role, getattr(bill_instance, "id", "?"),
                )
                return
            agent_id = getattr(assignment, "agent_id", None)
            if not agent_id:
                return
            running[f"_resolved_agent_id_{step.name}"] = agent_id
        except Exception as exc:
            logger.warning(
                "AD-647c: role resolution for step '%s' raised %s; degrading silently",
                step.name, type(exc).__name__,
            )

    def _record_bill_step_completion(
        self,
        bill_instance: Any,
        step: ProcessChainStep,
        step_output: dict[str, Any],
        running: dict[str, Any],
    ) -> None:
        if bill_instance is None or not step.bill_step_id:
            return
        try:
            self._bill_runtime.complete_step(
                bill_instance.id,
                step.bill_step_id,
                result=step_output,
            )
        except Exception as exc:
            logger.warning(
                "AD-647c: bill_runtime.complete_step(%s, %s) raised %s; chain success preserved",
                getattr(bill_instance, "id", "?"), step.bill_step_id, type(exc).__name__,
            )

    def _record_bill_step_failure(
        self,
        bill_instance: Any,
        step: ProcessChainStep,
        exc: BaseException,
        running: dict[str, Any],
    ) -> None:
        if bill_instance is None or not step.bill_step_id:
            return
        try:
            self._bill_runtime.fail_step(
                bill_instance.id,
                step.bill_step_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception as bill_exc:
            logger.warning(
                "AD-647c: bill_runtime.fail_step(%s, %s) raised %s; chain failure surfaces normally",
                getattr(bill_instance, "id", "?"), step.bill_step_id, type(bill_exc).__name__,
            )
```

---

## Section 3 — `ProcessChainRegistry.register_bill_chain`

**File:** `src/probos/cognitive/process_chains.py`

Append a new method onto `ProcessChainRegistry` immediately after `unregister_chain`.

```python
SEARCH:
    def unregister_chain(self, chain_id: str) -> bool:
        return self._chains.pop(chain_id, None) is not None

REPLACE:
    def unregister_chain(self, chain_id: str) -> bool:
        return self._chains.pop(chain_id, None) is not None

    def register_bill_chain(
        self,
        bill_definition: Any,
        chain_definition: ProcessChainDefinition,
    ) -> None:
        """AD-647c: Register a chain associated with a Bill, validating step mappings.

        Every chain step's ``bill_step_id`` (when non-empty) MUST appear in the
        bill's ``BillStep.id`` set. Validation is fail-fast at registration time;
        a mismatch raises ``ValueError`` and the chain is NOT registered.

        Empty ``bill_step_id`` values are permitted (chain steps not bound to a
        specific BillStep) and do not participate in validation.

        Parameters
        ----------
        bill_definition : BillDefinition
            The bill whose steps the chain claims to satisfy. Duck-typed: must
            expose ``bill`` (slug) and ``steps`` iterable of objects with ``.id``.
        chain_definition : ProcessChainDefinition
            The chain to register. Step ``bill_step_id`` values are validated.
        """
        bill_step_ids = {
            getattr(s, "id", "") for s in getattr(bill_definition, "steps", [])
        }
        unknown: list[tuple[str, str]] = []
        for step in chain_definition.steps:
            if step.bill_step_id and step.bill_step_id not in bill_step_ids:
                unknown.append((step.name, step.bill_step_id))
        if unknown:
            details = ", ".join(f"{name}->{bsid}" for name, bsid in unknown)
            raise ValueError(
                f"AD-647c: chain '{chain_definition.name}' references unknown bill step ids "
                f"in bill '{getattr(bill_definition, 'bill', '?')}': {details}"
            )
        self.register_chain(chain_definition)
```

---

## Section 4 — `runtime.bill_runtime` public property

**File:** `src/probos/runtime.py`

Add a public property mirroring `runtime.billet_registry` (line 985). Insert immediately after the `billet_registry` property.

```python
SEARCH:
    @property
    def billet_registry(self) -> Any:
        """AD-595a: Billet resolution facade (delegates to ontology)."""
        if self.ontology is None:
            return None
        return self.ontology.billet_registry

    @property
    def emergence_metrics_engine(self) -> Any:

REPLACE:
    @property
    def billet_registry(self) -> Any:
        """AD-595a: Billet resolution facade (delegates to ontology)."""
        if self.ontology is None:
            return None
        return self.ontology.billet_registry

    @property
    def bill_runtime(self) -> Any:
        """AD-647c: Public read-only accessor for BillRuntime.

        Closes the Wave 5 conv #1 hole that AD-635 documented retrospectively
        for ``_emergent_detector``. ProcessChainExecutor uses this to record
        chain-step lifecycle against BillInstance steps when chains are
        bill-bound.
        """
        return self._bill_runtime

    @property
    def emergence_metrics_engine(self) -> Any:
```

---

## Section 5 — Tests

**File:** `tests/test_ad647c_bills_integration.py` (NEW)

12 tests. Use `types.SimpleNamespace` + `unittest.mock.MagicMock` for stub bill_runtime / bill_instance fixtures. No real BillRuntime — exercising `BillRuntime.complete_step` round-trips is AD-618b territory.

```python
"""AD-647c v1 — Bills + Watch Bill integration for process chains."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutionError,
    ProcessChainExecutor,
    ProcessChainRegistry,
    ProcessChainStep,
    ProcessChainStepKind,
)


# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------

async def _noop(ctx: dict[str, Any]) -> dict[str, Any]:
    return {}


def _step(name: str = "s", *, kind=ProcessChainStepKind.TRANSFORM,
          handler=_noop, bill_step_id: str = "", assigned_role: str = ""):
    return ProcessChainStep(
        kind=kind, name=name, handler=handler,
        bill_step_id=bill_step_id, assigned_role=assigned_role,
    )


def _make_instance(instance_id: str = "i1", role_holder: dict | None = None):
    """Build a stub BillInstance with role_assignments dict."""
    assignments = {}
    if role_holder:
        for role, agent_id in role_holder.items():
            assignments[role] = SimpleNamespace(
                role_id=role, agent_id=agent_id, agent_type="x",
                callsign="x", department="x", assigned_at=0.0,
            )
    return SimpleNamespace(id=instance_id, role_assignments=assignments)


# ----------------------------------------------------------------------
# Section 1: Field additions on ProcessChainStep
# ----------------------------------------------------------------------

def test_step_accepts_bill_step_id_field():
    s = _step(bill_step_id="check_alarms")
    assert s.bill_step_id == "check_alarms"


def test_step_accepts_assigned_role_field():
    s = _step(assigned_role="oncall_engineer")
    assert s.assigned_role == "oncall_engineer"


def test_consult_step_kind_constructs_cleanly():
    s = _step(kind=ProcessChainStepKind.CONSULT)
    assert s.kind is ProcessChainStepKind.CONSULT
    assert s.kind.value == "consult"


# ----------------------------------------------------------------------
# Section 2: Executor backward compat (AD-647 + AD-647b path unchanged)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_without_bill_runtime_runs_identically_to_v1():
    """Old call sites passing no bill_runtime keep working; bill_step_id ignored."""
    async def h(ctx):
        return {"x": 1}
    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bstep_ignored"),),
    )
    executor = ProcessChainExecutor()  # no bill_runtime
    out = await executor.run(chain)
    assert out == {"x": 1}


@pytest.mark.asyncio
async def test_executor_with_bill_runtime_but_no_instance_id_skips_recording():
    """Three-guard defense: bill_runtime present but no context.bill_instance_id => skip."""
    bill_rt = MagicMock()
    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", bill_step_id="bs1"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain)  # no context
    bill_rt.get_instance.assert_not_called()
    bill_rt.complete_step.assert_not_called()


# ----------------------------------------------------------------------
# Section 3: Bill step lifecycle recording (success + failure)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_records_complete_step_on_success():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")

    async def h(ctx):
        return {"out": 42}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bstep_alpha"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain, {"bill_instance_id": "i1"})

    bill_rt.get_instance.assert_called_once_with("i1")
    bill_rt.complete_step.assert_called_once_with("i1", "bstep_alpha", result={"out": 42})


@pytest.mark.asyncio
async def test_executor_records_fail_step_on_handler_exception():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")

    async def boom(ctx):
        raise RuntimeError("nope")

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=boom, bill_step_id="bstep_beta"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with pytest.raises(ProcessChainExecutionError):
        await executor.run(chain, {"bill_instance_id": "i1"})

    bill_rt.fail_step.assert_called_once()
    args, kwargs = bill_rt.fail_step.call_args
    assert args == ("i1", "bstep_beta")
    assert "RuntimeError" in kwargs["error"] and "nope" in kwargs["error"]
    bill_rt.complete_step.assert_not_called()


@pytest.mark.asyncio
async def test_bill_recording_tier2_log_and_degrade_does_not_break_chain(caplog):
    """When bill_runtime.complete_step raises, chain success is preserved."""
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")
    bill_rt.complete_step.side_effect = RuntimeError("bill-side bug")

    async def h(ctx):
        return {"ok": True}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bs1"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.process_chains"):
        out = await executor.run(chain, {"bill_instance_id": "i1"})
    assert out == {"ok": True, "bill_instance_id": "i1"}
    assert any("bill_runtime.complete_step" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# Section 4: Role resolution via BillInstance.role_assignments
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assigned_role_injects_resolved_agent_id_into_context():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance(
        "i1", role_holder={"oncall": "agent-007"}
    )

    captured: dict[str, Any] = {}

    async def h(ctx):
        captured.update(ctx)
        return {}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, assigned_role="oncall"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain, {"bill_instance_id": "i1"})
    assert captured.get("_resolved_agent_id_s1") == "agent-007"


@pytest.mark.asyncio
async def test_unresolved_role_log_and_degrade(caplog):
    """assigned_role with no holder in BillInstance -> warning, no _resolved_agent_id."""
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")  # no role_holder

    captured: dict[str, Any] = {}

    async def h(ctx):
        captured.update(ctx)
        return {"x": 1}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, assigned_role="oncall"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.process_chains"):
        await executor.run(chain, {"bill_instance_id": "i1"})
    assert "_resolved_agent_id_s1" not in captured
    assert any("has no holder" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# Section 5: register_bill_chain validation
# ----------------------------------------------------------------------

def _fake_bill(slug: str, step_ids: list[str]):
    return SimpleNamespace(
        bill=slug,
        steps=[SimpleNamespace(id=sid) for sid in step_ids],
    )


def test_register_bill_chain_happy_path():
    registry = ProcessChainRegistry()
    bill = _fake_bill("incident_response", ["triage", "mitigate", "close"])
    chain = ProcessChainDefinition(
        name="ir_chain",
        steps=(
            _step("p1", bill_step_id="triage"),
            _step("p2", bill_step_id="mitigate"),
        ),
    )
    registry.register_bill_chain(bill, chain)
    assert registry.get_chain("ir_chain") is chain


def test_register_bill_chain_rejects_mismatched_bill_step_ids():
    registry = ProcessChainRegistry()
    bill = _fake_bill("ir", ["triage", "mitigate"])
    chain = ProcessChainDefinition(
        name="bad",
        steps=(
            _step("p1", bill_step_id="triage"),
            _step("p2", bill_step_id="not_a_real_step"),
        ),
    )
    with pytest.raises(ValueError, match="unknown bill step ids"):
        registry.register_bill_chain(bill, chain)
    # Validation is fail-fast — chain must NOT be registered.
    assert registry.get_chain("bad") is None


def test_register_bill_chain_permits_empty_bill_step_ids():
    """Chain steps without bill_step_id (empty string) skip validation."""
    registry = ProcessChainRegistry()
    bill = _fake_bill("ir", ["a"])
    chain = ProcessChainDefinition(
        name="mixed",
        steps=(
            _step("p1", bill_step_id="a"),
            _step("p2"),  # no bill_step_id
        ),
    )
    registry.register_bill_chain(bill, chain)
    assert registry.get_chain("mixed") is chain
```

(12 tests in 12 `def test_…` blocks above. Plus the registry permit-empty test = 13 total; if drift forces a drop, drop `test_consult_step_kind_constructs_cleanly` last — it's the lowest-coverage assertion.)

---

## Backward compatibility invariants

- **AD-647 v1 tests** (`tests/test_ad647_process_chains.py`, 8 tests) MUST continue to pass unchanged. The new fields default to empty string; the new ctor kwarg defaults to `None`. No call site changes required.
- **AD-647b v1 tests** (`tests/test_ad647b_chain_registry.py`, 12 tests) MUST continue to pass unchanged. `register_bill_chain` is purely additive.
- **`SCOUT_REPORT_CHAIN`** (`scout.py:302`) is NOT modified — Scout is not bill-bound in v1; it stays as a plain registered chain.

---

## What This Does NOT Change

- **NATS pipeline (AD-641g #403)**: deferred. Separate large issue.
- **LLM step templates (`prompt_template_id`)**: still reserved/rejected at construction. Future AD.
- **Parallel / conditional / rollback steps**: out of scope.
- **CONSULT suspend-and-resume across process restart**: deferred to placeholder AD-647d. Handler-returns-Future shape NOT supported. v1 CONSULT is a semantic label only.
- **Scout migration to bill-bound**: Scout reports are not tied to a Bill; no migration.
- **HXI surface for chain↔bill correlation**: not in v1.
- **EventType / journal entries**: no new events.
- **`runtime._bill_runtime` deletion**: kept for adoption-site compatibility (`runtime.py:1553`); the new `runtime.bill_runtime` property reads it.

---

## Tracking

- **PROGRESS.md**: prepend AD-647c v1 entry; bump test count baseline (Wave 48 baseline 11146 → expected 11158 = +12).
- **docs/development/roadmap.md**: AD-647c row status flip (Scoped → Complete) under the AD-647 family.
- **DECISIONS.md**: prepend AD-647c entry under Era V (use `## Era V — Civilization (Phases 31-36)\n\n### AD-647b` as the SEARCH anchor to prepend AD-647c above the AD-647b header).

---

## Acceptance Criteria

- [ ] All 12 new tests pass at `-n 0` and `-n 8 --dist=loadfile`.
- [ ] All 8 AD-647 v1 tests + 12 AD-647b v1 tests pass unchanged.
- [ ] Full test gate non-decreasing (Wave 48 baseline 11146 → ≥11158).
- [ ] `runtime.bill_runtime` returns the same object as `runtime._bill_runtime`.
- [ ] Phantom-API pre-check on this prompt: 0 NEW phantoms (FPs documented in dispatch).
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- [ ] Single commit "AD-647c v1: Process chains Bills/Watch Bill integration (#405)".

---

## Verified Against Codebase (HEAD `67a4091`, 2026-05-04)

```
grep -n "class ProcessChainStep" src/probos/cognitive/process_chains.py
  51:class ProcessChainStep:

grep -n "class ProcessChainExecutor" src/probos/cognitive/process_chains.py
  107:class ProcessChainExecutor:

grep -n "class ProcessChainRegistry" src/probos/cognitive/process_chains.py
  158:class ProcessChainRegistry:

grep -n "class BillRuntime" src/probos/sop/runtime.py
  39:class BillRuntime:

grep -n "    def complete_step" src/probos/sop/runtime.py
  (verified: signature (instance_id, step_id, result=None) -> bool)

grep -n "    def fail_step" src/probos/sop/runtime.py
  (verified: signature (instance_id, step_id, error="") -> bool)

grep -n "    def get_instance" src/probos/sop/runtime.py
  (verified: (instance_id) -> BillInstance | None)

grep -n "class BillInstance" src/probos/sop/instance.py
  68:class BillInstance:
  (verified field: role_assignments: dict[str, RoleAssignment])

grep -n "class RoleAssignment" src/probos/sop/instance.py
  56:class RoleAssignment:
  (verified fields: role_id, agent_id, agent_type, callsign, department, assigned_at)

grep -n "class BillStep" src/probos/sop/schema.py
  58:class BillStep:
  (verified field: id: str)

grep -n "def billet_registry" src/probos/runtime.py
  985:    def billet_registry(self) -> Any:

grep -n "_bill_runtime" src/probos/runtime.py
  515:        self._bill_runtime: BillRuntime | None = None
  1553:        self._bill_runtime = struct.bill_runtime  # AD-618d

grep -rn "process_chain_registry" src/probos/
  startup/finalize.py:530:    runtime.process_chain_registry = registry
  (PUBLIC — adopted via finalize wirer)

# CONSULT support: executor already awaits async handler natively
sed -n '131p' src/probos/cognitive/process_chains.py
                step_output = await step.handler(running)
```

