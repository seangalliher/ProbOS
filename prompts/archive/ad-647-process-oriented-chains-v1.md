# AD-647 v1 — Process-Oriented Cognitive Chains: Scaffold + Scout-Internal Migration

**Status:** Ready for build
**Issue:** #291
**Parent:** AD-632 (Cognitive Chain Architecture); BF-209 (Scout chain bypass — interim)
**Depends on:** none at runtime (Bills/Watch Bill/NATS deferred to AD-647b/c)
**Estimated tests:** 7–8

---

## v1 Scope (NARROW)

This AD ships **two things**:

1. **A reusable Process-Oriented Cognitive Chain primitive** — `ProcessChainStep`, `ProcessChainDefinition`, `ProcessChainExecutor` — distinct from the AD-632 communication chain (`SubTaskExecutor`). Step kinds: `QUERY`, `TRANSFORM`, `STORE`, `NOTIFY`. Callable handlers only (LLM-template handlers deferred).
2. **A reference Scout migration** — Scout's `act()` post-classification pipeline (parse → enrich → filter → store → notify) is wrapped as a `SCOUT_REPORT_CHAIN: ProcessChainDefinition` and invoked through the executor. The inline pipeline becomes 4 named callable handlers.

**BF-209 stays.** Removing it requires (a) a registry mapping intent/duty → ProcessChainDefinition and (b) a base-class hook in `CognitiveAgent._should_activate_chain`. Both are architectural surface deferred to AD-647b.

This v1 is greenfield with respect to AD-647 — the codebase has zero `ProcessChain*` symbols today.

---

## Verified Anchors (HEAD 449c733)

```
grep -n "class SubTaskType" src/probos/cognitive/sub_task.py
  31: class SubTaskType(str, Enum):

grep -n "_should_activate_chain" src/probos/cognitive/scout.py
  247:    def _should_activate_chain(self, observation: dict) -> bool:
  262:        return super()._should_activate_chain(observation)

grep -n "async def act" src/probos/cognitive/scout.py
  380:    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:

grep -n "^def parse_scout_reports\|^def filter_findings\|^def format_digest\|^def _load_seen\|^def _save_seen" src/probos/cognitive/scout.py
  80: def parse_scout_reports(...)
  130: def filter_findings(...)
  139: def format_digest(...)
  182: def _load_seen(...)
  192: def _save_seen(...)

grep -n "AD-647" DECISIONS.md
  1729: ### AD-647 — Process-Oriented Cognitive Chains   (status: Scoped — design only, no implementation)

grep -n "AD-641g" DECISIONS.md
  1369: ### AD-641g — Asynchronous Cognitive Pipeline via NATS   (status: Design — NOT shipped; no chain.X.analyze subjects in src)

grep -rn "ProcessChainStep\|ProcessChainDefinition\|ProcessChainExecutor\|SCOUT_REPORT_CHAIN" src/probos/
  (zero hits — greenfield)
```

FYI dependencies (NOT consumed in v1, but verified shipped for downstream ADs):
- AD-618a-e Bills/SOPs: `BillDefinition`, `BillRuntime`, `BillInstance` shipped (DECISIONS.md:1040–1112).
- AD-595a-e Watch Bill / Billets: `BilletRegistry`, `assign()`, qualification gate shipped (DECISIONS.md:1210–1253).

---

## Section 0 — Naming Collision Notice

`src/probos/cognitive/sub_task.py:31` already defines `SubTaskType(str, Enum)` with `QUERY/ANALYZE/COMPOSE/EVALUATE/REFLECT`. **Do NOT reuse this enum.** Define a NEW, distinct enum `ProcessChainStepKind` in the new module. The names "QUERY" overlap as Python identifiers in different namespaces — that's fine (different modules). The two are conceptually distinct: `SubTaskType` = cognitive step inside the comm chain; `ProcessChainStepKind` = lifecycle stage of a structured process.

---

## Section 1 — New module `src/probos/cognitive/process_chains.py`

Create a new module. Full file content:

```python
"""AD-647 v1 — Process-Oriented Cognitive Chains.

A process chain is an ordered sequence of typed steps that runs a structured
pipeline (data gather → enrichment → persistence → notification) for an agent
duty. Distinct from the AD-632 communication chain (`SubTaskExecutor`) which
runs LLM cognition over a conversation context.

v1 supports CALLABLE handlers only. LLM-template handlers, parallel steps,
conditional branching, rollback, and persistence are deferred (AD-647b/c).

Scout report is the reference implementation; see scout.SCOUT_REPORT_CHAIN.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


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


@runtime_checkable
class ProcessChainHandler(Protocol):
    """Callable signature for v1 process-chain handlers.

    Receives the accumulated context dict and returns a dict that is merged
    into the context before the next step runs. Handlers may raise; the
    executor surfaces the exception to the caller (no swallow at v1).
    """
    async def __call__(self, context: dict[str, Any]) -> dict[str, Any]: ...


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


@dataclass(frozen=True)
class ProcessChainDefinition:
    """Declarative definition of a process chain.

    Steps run sequentially. Step output dicts are merged into the running
    context, so later steps can read earlier outputs by key.
    """
    name: str
    steps: tuple[ProcessChainStep, ...] = field(default_factory=tuple)
    description: str = ""

    def __post_init__(self) -> None:  # type: ignore[override]
        # Step-name uniqueness — fail fast at construction.
        seen: set[str] = set()
        for step in self.steps:
            if step.name in seen:
                raise ValueError(
                    f"ProcessChainDefinition '{self.name}': duplicate step name '{step.name}'"
                )
            seen.add(step.name)
            if step.prompt_template_id:
                raise ValueError(
                    f"ProcessChainDefinition '{self.name}' step '{step.name}': "
                    "prompt_template_id is reserved for AD-647b; v1 supports callable handlers only"
                )


class ProcessChainExecutionError(Exception):
    """Raised when a process-chain step handler fails or definition is invalid."""

    def __init__(self, chain_name: str, step_name: str, cause: BaseException) -> None:
        self.chain_name = chain_name
        self.step_name = step_name
        self.cause = cause
        super().__init__(
            f"Process chain '{chain_name}' step '{step_name}' failed: "
            f"{type(cause).__name__}: {cause}"
        )


class ProcessChainExecutor:
    """Runs a ProcessChainDefinition sequentially, threading context across steps.

    v1 contract:
      - Steps run in declared order.
      - Each step's returned dict is merged (`context.update(...)`) before next step.
      - On handler exception, executor wraps it in ProcessChainExecutionError and raises.
      - Empty step list is rejected at run() time.
    """

    def __init__(self, *, emit_event: Callable[[str, dict], Any] | None = None) -> None:
        self._emit_event = emit_event

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
```

---

## Section 2 — Scout migration: `SCOUT_REPORT_CHAIN`

In `src/probos/cognitive/scout.py`:

### 2a. Add imports near the top (after the existing `from probos.types import ...`):

SEARCH:
```python
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)
```

REPLACE:
```python
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutor,
    ProcessChainStep,
    ProcessChainStepKind,
)
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)
```

### 2b. Refactor `act()` to invoke the executor.

Replace the body of `ScoutAgent.act()` such that the four post-classification phases (parse + mark seen, enrich, filter + store report, notify) are method handlers on the agent and `act()` builds + runs the chain.

SEARCH (the existing `act` method body — match the full method from `async def act` through the final `return {"success": True, "result": digest}`):

```python
    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM classification, store report, deliver notifications."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        # BF-177: Allow duty-triggered proactive_think (scout_report) to reach report generation
        is_duty_triggered = bool(decision.get("duty", {}).get("duty_id"))
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think") and not is_duty_triggered:
            return {"success": True, "result": decision.get("llm_output", "")}
        llm_output = decision.get("llm_output", "")
        if "No new repositories" in llm_output or not llm_output.strip():
            # BF-214: "No new repositories" means perceive found nothing new —
            # no pending repos to mark. Safe to return.
            return {"success": True, "result": "No new findings to report."}
```

REPLACE:
```python
    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM classification, store report, deliver notifications.

        AD-647 v1: post-classification pipeline (parse → enrich → filter → store → notify)
        runs through `SCOUT_REPORT_CHAIN` via `ProcessChainExecutor`. The chain handlers
        are bound methods on this agent so they have access to runtime, paths, and state.
        """
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        # BF-177: Allow duty-triggered proactive_think (scout_report) to reach report generation
        is_duty_triggered = bool(decision.get("duty", {}).get("duty_id"))
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think") and not is_duty_triggered:
            return {"success": True, "result": decision.get("llm_output", "")}
        llm_output = decision.get("llm_output", "")
        if "No new repositories" in llm_output or not llm_output.strip():
            # BF-214: "No new repositories" means perceive found nothing new —
            # no pending repos to mark. Safe to return.
            return {"success": True, "result": "No new findings to report."}

        # AD-647 v1: build per-invocation chain (handlers are bound methods)
        chain = ProcessChainDefinition(
            name="scout_report",
            description="Scout: parse classification → enrich → filter+store → notify.",
            steps=(
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM,
                    name="parse_and_mark_seen",
                    handler=self._scout_step_parse_and_mark_seen,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM,
                    name="enrich_and_filter",
                    handler=self._scout_step_enrich_and_filter,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.STORE,
                    name="persist_report",
                    handler=self._scout_step_persist_report,
                ),
                ProcessChainStep(
                    kind=ProcessChainStepKind.NOTIFY,
                    name="notify_and_deliver",
                    handler=self._scout_step_notify_and_deliver,
                ),
            ),
        )
        executor = ProcessChainExecutor()
        try:
            result_ctx = await executor.run(chain, context={"llm_output": llm_output})
        except Exception:
            logger.warning("AD-647: scout_report chain failed; falling back to error result", exc_info=True)
            return {"success": False, "result": "Scout report pipeline failed. See logs."}

        digest = result_ctx.get("digest", "")
        return {"success": True, "result": digest}
```

### 2c. Remove the inline pipeline code that previously followed the `is_duty_triggered` / `No new repositories` guards (the original `findings = parse_scout_reports(...)`, `_pending = ...`, enrich loop, filter, write report, notify queue, `await self._deliver_discord(...)`, and the trailing `digest = format_digest(...)` / `return` lines) and migrate it into four bound handler methods just BEFORE `_deliver_discord`:

INSERT before the existing `async def _deliver_discord(...)` definition:

```python
    # ------------------------------------------------------------------
    # AD-647 v1: Scout process-chain handlers (bound to this agent so
    # handlers can read self._runtime / self._reports_dir / self._seen_file
    # / self._repo_metadata / self._pending_seen_repos).
    # ------------------------------------------------------------------

    async def _scout_step_parse_and_mark_seen(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """TRANSFORM: parse ===SCOUT_REPORT=== blocks, mark seen on success."""
        llm_output = ctx.get("llm_output", "") or ""
        findings = parse_scout_reports(llm_output)

        # BF-214: mark seen only after classification succeeds
        # (succeeded = at least one ===SCOUT_REPORT=== block parsed, even if all are SKIP).
        _pending = getattr(self, "_pending_seen_repos", [])
        _classification_succeeded = bool(findings) or "===SCOUT_REPORT===" in llm_output
        if _pending and _classification_succeeded:
            seen = _load_seen(self._seen_file)
            _now = datetime.now(timezone.utc).isoformat()
            for repo_name in _pending:
                seen[repo_name] = _now
            _save_seen(seen, self._seen_file)
            logger.info("Scout: marked %d repos as seen after classification", len(_pending))
            self._pending_seen_repos = []
        elif _pending and not _classification_succeeded:
            logger.warning(
                "Scout: classification failed — %d repos NOT marked as seen, will retry next cycle",
                len(_pending),
            )
            self._pending_seen_repos = []

        return {"findings": findings}

    async def _scout_step_enrich_and_filter(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """TRANSFORM: enrich findings with repo metadata, filter by relevance."""
        findings: list[ScoutFinding] = ctx.get("findings", []) or []
        metadata = getattr(self, "_repo_metadata", {})
        for f in findings:
            meta = metadata.get(f.repo_full_name, {})
            f.language = meta.get("language", f.language)
            f.license = meta.get("license", f.license)
            f.topics = meta.get("topics", f.topics)

        filtered = filter_findings(findings, min_relevance=3)
        self._last_findings = filtered
        return {"filtered": filtered, "total_classified": len(findings)}

    async def _scout_step_persist_report(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """STORE: write the day's report JSON to the reports directory."""
        filtered: list[ScoutFinding] = ctx.get("filtered", []) or []
        total_classified: int = ctx.get("total_classified", 0)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._reports_dir / f"{date_str}.json"
        report_data = {
            "date": date_str,
            "total_classified": total_classified,
            "total_relevant": len(filtered),
            "findings": [asdict(f) for f in filtered],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        return {"date_str": date_str, "report_path": str(report_path)}

    async def _scout_step_notify_and_deliver(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """NOTIFY: post high-scoring findings to notification queue + deliver to Discord."""
        filtered: list[ScoutFinding] = ctx.get("filtered", []) or []
        date_str: str = ctx.get("date_str", "unknown")

        if self._runtime and hasattr(self._runtime, "notification_queue"):
            for f in filtered:
                if f.composite_score >= 4:
                    self._runtime.notification_queue.notify(
                        agent_id=self.id,
                        agent_type="scout",
                        department="science",
                        title=f"Scout: {f.repo_full_name}",
                        detail=f"[{f.classification}] {f.summary}",
                        notification_type="info",
                        action_url=f.url,
                    )

        await self._deliver_discord(filtered, date_str)
        digest = format_digest(filtered, date_str)
        return {"digest": digest}
```

> Note: this insertion REMOVES the inline pipeline that previously sat between the `if "No new repositories"` early return and the `return {"success": True, "result": digest}` close — that whole block is now relocated into the handlers above, which the new `act()` invokes via the executor.

---

## Section 3 — Tests

New file: `tests/test_ad647_process_chains.py`. Target: 8 tests (over the 7 floor by 1).

```python
"""AD-647 v1 — process-chain primitives + Scout migration."""
from __future__ import annotations

import json
import pytest

from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutionError,
    ProcessChainExecutor,
    ProcessChainStep,
    ProcessChainStepKind,
)


@pytest.mark.asyncio
async def test_definition_step_name_uniqueness_enforced():
    """ProcessChainDefinition rejects duplicate step names at construction."""
    async def _h(ctx): return {}
    with pytest.raises(ValueError, match="duplicate step name"):
        ProcessChainDefinition(
            name="dup",
            steps=(
                ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="a", handler=_h),
                ProcessChainStep(kind=ProcessChainStepKind.STORE, name="a", handler=_h),
            ),
        )


@pytest.mark.asyncio
async def test_definition_rejects_prompt_template_id_in_v1():
    """v1 supports callable handlers only — prompt_template_id reserved for AD-647b."""
    async def _h(ctx): return {}
    with pytest.raises(ValueError, match="reserved for AD-647b"):
        ProcessChainDefinition(
            name="bad",
            steps=(
                ProcessChainStep(
                    kind=ProcessChainStepKind.TRANSFORM, name="x",
                    handler=_h, prompt_template_id="future_template",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_executor_runs_steps_sequentially_and_threads_context():
    """Each step's returned dict is merged before the next step runs."""
    order: list[str] = []

    async def step1(ctx):
        order.append("s1")
        assert ctx == {"seed": 1}
        return {"a": "alpha"}

    async def step2(ctx):
        order.append("s2")
        assert ctx == {"seed": 1, "a": "alpha"}
        return {"b": "beta"}

    async def step3(ctx):
        order.append("s3")
        assert ctx == {"seed": 1, "a": "alpha", "b": "beta"}
        return {"c": "gamma"}

    chain = ProcessChainDefinition(
        name="ordered",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="s1", handler=step1),
            ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="s2", handler=step2),
            ProcessChainStep(kind=ProcessChainStepKind.STORE, name="s3", handler=step3),
        ),
    )
    final = await ProcessChainExecutor().run(chain, context={"seed": 1})
    assert order == ["s1", "s2", "s3"]
    assert final == {"seed": 1, "a": "alpha", "b": "beta", "c": "gamma"}


@pytest.mark.asyncio
async def test_executor_rejects_empty_chain():
    """Empty chain is a configuration error — fail fast at run()."""
    chain = ProcessChainDefinition(name="empty", steps=())
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert ei.value.chain_name == "empty"


@pytest.mark.asyncio
async def test_executor_surfaces_handler_exception_with_metadata():
    """Handler raises → executor wraps in ProcessChainExecutionError, no swallow."""
    async def ok_step(ctx): return {"x": 1}

    async def boom(ctx):
        raise RuntimeError("simulated failure")

    chain = ProcessChainDefinition(
        name="boomchain",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="ok", handler=ok_step),
            ProcessChainStep(kind=ProcessChainStepKind.NOTIFY, name="boom", handler=boom),
        ),
    )
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert ei.value.chain_name == "boomchain"
    assert ei.value.step_name == "boom"
    assert isinstance(ei.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_executor_rejects_non_dict_handler_return():
    """Handler must return dict | None — anything else is a contract violation."""
    async def bad(ctx):
        return "not a dict"  # type: ignore[return-value]

    chain = ProcessChainDefinition(
        name="badret",
        steps=(ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="bad", handler=bad),),
    )
    with pytest.raises(ProcessChainExecutionError) as ei:
        await ProcessChainExecutor().run(chain)
    assert isinstance(ei.value.cause, TypeError)


@pytest.mark.asyncio
async def test_executor_treats_none_return_as_empty_dict():
    """Handler returning None is shorthand for 'no context update' — must not crash."""
    async def silent(ctx):
        return None

    async def follower(ctx):
        return {"ok": True}

    chain = ProcessChainDefinition(
        name="nonechain",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="silent", handler=silent),
            ProcessChainStep(kind=ProcessChainStepKind.NOTIFY, name="follower", handler=follower),
        ),
    )
    final = await ProcessChainExecutor().run(chain, context={"seed": 1})
    assert final == {"seed": 1, "ok": True}


@pytest.mark.asyncio
async def test_scout_act_runs_through_process_chain(tmp_path, monkeypatch):
    """End-to-end Scout migration: act() invokes SCOUT_REPORT_CHAIN handlers and produces a report file."""
    from probos.cognitive.scout import ScoutAgent, ScoutFinding

    agent = ScoutAgent.__new__(ScoutAgent)  # bypass spawner ctor — we wire the minimum we need
    agent.id = "scout-test"
    agent._runtime = None  # no notification queue, no discord
    agent._last_findings = []
    agent._pending_seen_repos = []  # already marked / nothing to mark
    agent._repo_metadata = {
        "octo/agent": {"language": "Python", "license": "MIT", "topics": ["ai-agents"]},
    }

    # Redirect data dir to tmp_path so report write + seen file are isolated.
    monkeypatch.setattr(
        type(agent),
        "_data_dir",
        property(lambda self: tmp_path),
    )

    llm_output = (
        "===SCOUT_REPORT===\n"
        "REPO: octo/agent\n"
        "STARS: 1500\n"
        "URL: https://github.com/octo/agent\n"
        "CLASS: absorb\n"
        "RELEVANCE: 4\n"
        "CREDIBILITY: 4\n"
        "RELIABILITY: 4\n"
        "SUMMARY: Multi-agent orchestration\n"
        "INSIGHT: Demonstrates governed delegation\n"
        "===END===\n"
    )
    decision = {
        "intent": "scout_search",
        "llm_output": llm_output,
        "duty": {"duty_id": "scout_report"},
    }
    out = await agent.act(decision)

    assert out["success"] is True
    assert "octo/agent" in out["result"]  # digest contains the finding
    # Report file landed in tmp_path/scout_reports/<date>.json
    report_files = list((tmp_path / "scout_reports").glob("*.json"))
    assert len(report_files) == 1
    payload = json.loads(report_files[0].read_text(encoding="utf-8"))
    assert payload["total_classified"] == 1
    assert payload["total_relevant"] == 1
    assert payload["findings"][0]["repo_full_name"] == "octo/agent"
    assert payload["findings"][0]["language"] == "Python"  # enrichment ran
```

---

## What This Does NOT Change

- **BF-209 stays as-is.** `ScoutAgent._should_activate_chain()` still returns False for duty-triggered `scout_report`. Removal requires registry + base-class hook → AD-647b.
- **No registry surface** mapping intent/duty → ProcessChainDefinition. Scout builds its chain inline in `act()`. Generalization deferred.
- **No CognitiveAgent base-class hook** for process chains. Only `ScoutAgent` is migrated.
- **No Bills (AD-618) integration.** BillRuntime / BillDefinition / BillInstance are NOT consumed in v1. Bill-driven process chains → AD-647c.
- **No Watch Bill (AD-595) integration.** Role-based chain assignment deferred.
- **No NATS coupling.** AD-641g cognitive pipeline is design-only at HEAD. Sync executor in v1; NATS subjects deferred.
- **No LLM prompt-template handlers.** `prompt_template_id` is reserved (rejected in v1) → AD-647b.
- **No parallel steps, conditional branching, rollback, or retry.** Sequential only.
- **No persistence of chain executions.** No journal table, no event emission. Telemetry deferred.
- **No new EventType.**
- **No new Pydantic config.** ProcessChainExecutor takes no config in v1.
- **No HXI surface.**
- **No removal of Scout's existing inline helpers** (`parse_scout_reports`, `filter_findings`, `format_digest`, `_load_seen`, `_save_seen`) — handlers wrap them.
- **No changes to `perceive()`** — GitHub search and seen-file deferred-marking semantics (BF-208/BF-214/BF-225) stay intact.

---

## Tracking

- **PROGRESS.md:** flip the AD-647 line (currently `AD-647 SCOPED. ...`) to `AD-647 v1 CLOSED. Process-Oriented Cognitive Chains — scaffold + Scout-internal migration. ProcessChainStep/Definition/Executor + SCOUT_REPORT_CHAIN. BF-209 retained as comm-chain bypass; removal deferred to AD-647b. 8 tests. Issue #291.`
- **DECISIONS.md AD-647 entry:** append a `**v1 (2026-05-04):** scaffold (ProcessChainStepKind/Step/Definition/Executor) + Scout-internal migration. BF-209 retained.` line. Do NOT rewrite the original Scoped entry.
- **roadmap.md:** if an AD-647 row exists, mark v1 shipped; otherwise no change.
- **Issue #291:** close on merge.

---

## Acceptance Criteria

1. `src/probos/cognitive/process_chains.py` exists and exports `ProcessChainStepKind`, `ProcessChainStep`, `ProcessChainDefinition`, `ProcessChainExecutor`, `ProcessChainExecutionError`, `ProcessChainHandler`.
2. `ProcessChainDefinition` validates step-name uniqueness and rejects `prompt_template_id` at construction.
3. `ProcessChainExecutor.run()` runs steps sequentially, threads context across steps, surfaces handler exceptions wrapped in `ProcessChainExecutionError`, treats `None` returns as empty-dict, and rejects empty chains.
4. `ScoutAgent.act()` builds `SCOUT_REPORT_CHAIN` (4 steps: `parse_and_mark_seen`/TRANSFORM, `enrich_and_filter`/TRANSFORM, `persist_report`/STORE, `notify_and_deliver`/NOTIFY) and runs it via `ProcessChainExecutor`. The previous inline pipeline is fully migrated into the four bound-method handlers.
5. The four handler methods are public-named (`_scout_step_*` is acceptable as the existing convention) bound methods on `ScoutAgent`, callable independently for tests.
6. `tests/test_ad647_process_chains.py` ships 8 tests as specified; all pass.
7. Existing Scout tests remain green (`tests/test_scout.py`, `tests/test_bf208*`, `tests/test_bf209*`, `tests/test_bf214*`, `tests/test_bf225*`). Behavior on the duty-triggered path must produce the same report file + digest as pre-AD-647.
8. BF-209 opt-out (`scout.py:247`) is unchanged.
9. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
10. Full parallel gate green: `pytest tests/ -q -n 8 --dist=loadfile`. Test-count delta vs Wave 33 baseline (10950): +8.
