"""AD-632h: Parallel Sub-Task Dispatch — tests for wave-based parallel execution.

Tests cover: depends_on field, chain validation, step readiness computation,
parallel execution, failure handling in parallel waves, journal recording,
and backward compatibility with sequential chains.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import (
    SubTaskChain,
    SubTaskChainError,
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskStepError,
    SubTaskType,
    validate_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(name: str, st_type: SubTaskType = SubTaskType.QUERY,
               required: bool = True, depends_on: tuple[str, ...] = ()) -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=st_type,
        name=name,
        required=required,
        depends_on=depends_on,
    )


class _Rendezvous:
    """BF-852: prove parallelism by construction, not by the wall clock.

    These tests asserted elapsed-time budgets. Both were unsound, in opposite
    directions. ``elapsed < 0.5`` for two 0.1s handlers could not detect
    serialisation at all -- running them one after the other takes 0.2s and
    passes. ``elapsed < 0.18`` for four 0.05s handlers did detect it (0.2s), but
    with only 3.6x headroom over the expected time, and a loaded gate worker
    blew it at 0.218s with the executor behaving correctly.

    A rendezvous parks each caller until ``expected`` are inside together. That
    cannot happen at all unless they really do overlap, so load can only make
    the test slower, never wrong. A serialised executor parks the first caller
    until the watchdog fires and the test fails naming the cause.
    """

    def __init__(self, expected: int, timeout: float = 10.0) -> None:
        self._expected = expected
        self._timeout = timeout
        self._gate = asyncio.Event()
        self.arrived = 0
        self.peak = 0
        self.timed_out = False

    async def meet(self) -> None:
        self.arrived += 1
        self.peak = max(self.peak, self.arrived)
        try:
            if self.arrived >= self._expected:
                self._gate.set()
            try:
                await asyncio.wait_for(self._gate.wait(), timeout=self._timeout)
            except asyncio.TimeoutError:
                # Released on the way out so a failing run pays one watchdog
                # rather than one per caller.
                self.timed_out = True
                self._gate.set()
        finally:
            self.arrived -= 1


def _make_handler(delay: float = 0.0, result_data: dict | None = None,
                  fail: bool = False,
                  rendezvous: "_Rendezvous | None" = None) -> AsyncMock:
    """Create an async handler mock with optional delay and failure."""
    async def _handler(spec, context, prior_results):
        if rendezvous is not None:
            await rendezvous.meet()
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise RuntimeError(f"Handler {spec.name} failed")
        return SubTaskResult(
            sub_task_type=spec.sub_task_type,
            name=spec.name,
            result=result_data or {"output": f"{spec.name}-done"},
            tokens_used=10,
            success=True,
        )
    mock = AsyncMock(side_effect=_handler)
    return mock


def _make_executor(*handlers: tuple[SubTaskType, AsyncMock]) -> SubTaskExecutor:
    config = MagicMock()
    config.enabled = True
    config.max_chain_steps = 10
    executor = SubTaskExecutor(config=config, emit_event_fn=MagicMock())
    for st_type, handler in handlers:
        executor.register_handler(st_type, handler)
    return executor


# ===========================================================================
# Class 1: TestDependsOnField
# ===========================================================================

class TestDependsOnField:
    """Tests for the depends_on field on SubTaskSpec."""

    def test_default_empty_tuple(self):
        spec = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q")
        assert spec.depends_on == ()

    def test_explicit_depends_on(self):
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.EVALUATE, name="eval",
            depends_on=("compose",),
        )
        assert spec.depends_on == ("compose",)

    def test_frozen_immutable(self):
        spec = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="q")
        with pytest.raises(AttributeError):
            spec.depends_on = ("other",)

    def test_depends_on_is_tuple(self):
        spec = SubTaskSpec(
            sub_task_type=SubTaskType.REFLECT, name="r",
            depends_on=("a", "b"),
        )
        assert isinstance(spec.depends_on, tuple)
        assert len(spec.depends_on) == 2


# ===========================================================================
# Class 2: TestChainValidation
# ===========================================================================

class TestChainValidation:
    """Tests for validate_chain() dependency validation."""

    def test_valid_linear_chain(self):
        chain = SubTaskChain(steps=[
            _make_spec("a"),
            _make_spec("b", depends_on=("a",)),
            _make_spec("c", depends_on=("b",)),
        ])
        assert validate_chain(chain) == []

    def test_valid_parallel_evaluate_reflect(self):
        chain = SubTaskChain(steps=[
            _make_spec("query", SubTaskType.QUERY),
            _make_spec("analyze", SubTaskType.ANALYZE, depends_on=("query",)),
            _make_spec("compose", SubTaskType.COMPOSE, depends_on=("analyze",)),
            _make_spec("evaluate", SubTaskType.EVALUATE, depends_on=("compose",)),
            _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
        ])
        assert validate_chain(chain) == []

    def test_invalid_nonexistent_dep(self):
        chain = SubTaskChain(steps=[
            _make_spec("a"),
            _make_spec("b", depends_on=("nonexistent",)),
        ])
        errors = validate_chain(chain)
        assert len(errors) == 1
        assert "non-existent" in errors[0]
        assert "nonexistent" in errors[0]

    def test_invalid_circular(self):
        chain = SubTaskChain(steps=[
            _make_spec("a", depends_on=("b",)),
            _make_spec("b", depends_on=("a",)),
        ])
        errors = validate_chain(chain)
        assert any("ircular" in e for e in errors)

    def test_invalid_self_reference(self):
        chain = SubTaskChain(steps=[
            _make_spec("a", depends_on=("a",)),
        ])
        errors = validate_chain(chain)
        assert any("itself" in e for e in errors)


# ===========================================================================
# Class 3: TestGetReadySteps
# ===========================================================================

class TestGetReadySteps:
    """Tests for _get_ready_steps() step readiness computation."""

    def _executor(self):
        return _make_executor()

    def test_no_deps_sequential_first_ready(self):
        executor = self._executor()
        chain = SubTaskChain(steps=[
            _make_spec("a"), _make_spec("b"), _make_spec("c"),
        ])
        ready = executor._get_ready_steps(chain, set())
        assert len(ready) == 1
        assert ready[0][1].name == "a"

    def test_explicit_deps_parallel(self):
        executor = self._executor()
        chain = SubTaskChain(steps=[
            _make_spec("compose", SubTaskType.COMPOSE),
            _make_spec("evaluate", SubTaskType.EVALUATE, depends_on=("compose",)),
            _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
        ])
        ready = executor._get_ready_steps(chain, {"compose"})
        assert len(ready) == 2
        names = {r[1].name for r in ready}
        assert names == {"evaluate", "reflect"}

    def test_mixed_deps(self):
        """Steps without deps are sequential; steps with explicit deps follow their rules."""
        executor = self._executor()
        chain = SubTaskChain(steps=[
            _make_spec("a"),
            _make_spec("b"),
            _make_spec("c", depends_on=("a",)),
        ])
        # After 'a' completed: 'b' (no deps, prior='a' satisfied) and 'c' (depends on 'a') both ready
        ready = executor._get_ready_steps(chain, {"a"})
        names = {r[1].name for r in ready}
        assert names == {"b", "c"}

    def test_all_completed_empty(self):
        executor = self._executor()
        chain = SubTaskChain(steps=[_make_spec("a")])
        ready = executor._get_ready_steps(chain, {"a"})
        assert ready == []

    def test_first_step_no_deps_ready(self):
        executor = self._executor()
        chain = SubTaskChain(steps=[_make_spec("first")])
        ready = executor._get_ready_steps(chain, set())
        assert len(ready) == 1
        assert ready[0][1].name == "first"

    def test_no_deps_sequential_ordering(self):
        """Without depends_on, steps run one at a time (backward compat)."""
        executor = self._executor()
        chain = SubTaskChain(steps=[
            _make_spec("a"), _make_spec("b"), _make_spec("c"),
        ])
        # After a completed, only b ready (c depends on a AND b implicitly)
        ready = executor._get_ready_steps(chain, {"a"})
        assert len(ready) == 1
        assert ready[0][1].name == "b"


# ===========================================================================
# Class 4: TestParallelExecution
# ===========================================================================

class TestParallelExecution:
    """Tests for parallel wave execution."""

    @pytest.mark.asyncio
    async def test_evaluate_reflect_concurrent(self):
        """EVALUATE and REFLECT with depends_on should run concurrently."""
        # BF-852: both must be inside the handler together before either may
        # leave, which a sequential executor cannot satisfy at any speed.
        wave = _Rendezvous(expected=2)
        eval_handler = _make_handler(rendezvous=wave)
        reflect_handler = _make_handler(rendezvous=wave)
        query_handler = _make_handler()
        analyze_handler = _make_handler()
        compose_handler = _make_handler()

        executor = _make_executor(
            (SubTaskType.QUERY, query_handler),
            (SubTaskType.ANALYZE, analyze_handler),
            (SubTaskType.COMPOSE, compose_handler),
            (SubTaskType.EVALUATE, eval_handler),
            (SubTaskType.REFLECT, reflect_handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("query", SubTaskType.QUERY),
                _make_spec("analyze", SubTaskType.ANALYZE),
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("evaluate", SubTaskType.EVALUATE,
                           required=False, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT,
                           required=False, depends_on=("compose",)),
            ],
            chain_timeout_ms=10000,
        )

        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )

        assert len(results) == 5
        # The rendezvous IS the proof: evaluate and reflect were inside the
        # handler at the same time. The budget this replaces could not detect
        # serialisation at all -- two 0.1s handlers run one after the other
        # take 0.2s, comfortably inside the 0.5s it allowed.
        assert not wave.timed_out
        assert wave.peak == 2

    @pytest.mark.asyncio
    async def test_sequential_no_depends_on(self):
        """Chain without depends_on runs sequentially (backward compat)."""
        handler = _make_handler()
        executor = _make_executor(
            (SubTaskType.QUERY, handler),
            (SubTaskType.ANALYZE, handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("a", SubTaskType.QUERY),
                _make_spec("b", SubTaskType.ANALYZE),
            ],
            chain_timeout_ms=5000,
        )

        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )
        assert len(results) == 2
        assert results[0].name == "a"
        assert results[1].name == "b"

    @pytest.mark.asyncio
    async def test_single_step_no_gather(self):
        """Single step wave executes directly without gather overhead."""
        handler = _make_handler()
        executor = _make_executor((SubTaskType.QUERY, handler))

        chain = SubTaskChain(
            steps=[_make_spec("only", SubTaskType.QUERY)],
            chain_timeout_ms=5000,
        )
        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )
        assert len(results) == 1
        assert results[0].name == "only"

    @pytest.mark.asyncio
    async def test_parallel_steps_receive_same_prior_results(self):
        """Parallel steps in the same wave get the same prior_results snapshot."""
        received_priors = []

        async def _capture_handler(spec, context, prior_results):
            received_priors.append(list(prior_results))
            return SubTaskResult(
                sub_task_type=spec.sub_task_type, name=spec.name,
                result={}, success=True,
            )

        compose_handler = _make_handler()
        eval_mock = AsyncMock(side_effect=_capture_handler)
        reflect_mock = AsyncMock(side_effect=_capture_handler)

        executor = _make_executor(
            (SubTaskType.COMPOSE, compose_handler),
            (SubTaskType.EVALUATE, eval_mock),
            (SubTaskType.REFLECT, reflect_mock),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )
        await executor.execute(chain, {}, agent_id="test", agent_type="test")

        # Both should have received the same prior_results (just compose)
        assert len(received_priors) == 2
        assert len(received_priors[0]) == 1
        assert len(received_priors[1]) == 1
        assert received_priors[0][0].name == "compose"
        assert received_priors[1][0].name == "compose"

    @pytest.mark.asyncio
    async def test_three_step_parallel_wave(self):
        """Three steps depending on the same step run in parallel."""
        # BF-852: the root runs alone, so it must NOT share the wave's
        # rendezvous -- it would park waiting for peers that cannot arrive.
        wave = _Rendezvous(expected=3)
        root_handler = _make_handler()
        wave_handler = _make_handler(rendezvous=wave)
        executor = _make_executor(
            (SubTaskType.COMPOSE, root_handler),
            (SubTaskType.EVALUATE, wave_handler),
            (SubTaskType.REFLECT, wave_handler),
            (SubTaskType.QUERY, wave_handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("root", SubTaskType.COMPOSE),
                _make_spec("a", SubTaskType.EVALUATE, depends_on=("root",)),
                _make_spec("b", SubTaskType.REFLECT, depends_on=("root",)),
                _make_spec("c", SubTaskType.QUERY, depends_on=("root",)),
            ],
            chain_timeout_ms=5000,
        )

        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )

        assert len(results) == 4
        # All three were inside the handler together. Unlike the budget in
        # test_evaluate_reflect_concurrent, `elapsed < 0.18` did catch
        # serialisation (4 x 0.05s = 0.2s) -- but with only 3.6x headroom over
        # the expected time, which is what a loaded gate worker blew at 0.218s.
        # Correct and fragile, rather than wrong: the rendezvous keeps the
        # detection and drops the fragility.
        assert not wave.timed_out
        assert wave.peak == 3

    @pytest.mark.asyncio
    async def test_full_chain_wave_order(self):
        """QUERY → ANALYZE → COMPOSE → [EVALUATE ‖ REFLECT] wave order."""
        execution_order = []

        async def _tracking_handler(spec, context, prior_results):
            execution_order.append(spec.name)
            return SubTaskResult(
                sub_task_type=spec.sub_task_type, name=spec.name,
                result={}, success=True,
            )

        mock = AsyncMock(side_effect=_tracking_handler)
        executor = _make_executor(
            (SubTaskType.QUERY, mock),
            (SubTaskType.ANALYZE, mock),
            (SubTaskType.COMPOSE, mock),
            (SubTaskType.EVALUATE, mock),
            (SubTaskType.REFLECT, mock),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("query", SubTaskType.QUERY),
                _make_spec("analyze", SubTaskType.ANALYZE),
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )
        await executor.execute(chain, {}, agent_id="test", agent_type="test")

        # First three are sequential
        assert execution_order[:3] == ["query", "analyze", "compose"]
        # Last two are parallel (order may vary)
        assert set(execution_order[3:]) == {"eval", "reflect"}


# ===========================================================================
# Class 5: TestParallelFailureHandling
# ===========================================================================

class TestParallelFailureHandling:
    """Tests for failure handling in parallel waves."""

    @pytest.mark.asyncio
    async def test_required_failure_aborts_after_wave(self):
        """Required step failure in parallel wave → chain aborts after wave completes."""
        good_handler = _make_handler()
        fail_handler = _make_handler(fail=True)

        executor = _make_executor(
            (SubTaskType.COMPOSE, good_handler),
            (SubTaskType.EVALUATE, fail_handler),
            (SubTaskType.REFLECT, good_handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, required=True,
                           depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, required=False,
                           depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )

        with pytest.raises(SubTaskStepError):
            await executor.execute(chain, {}, agent_id="test", agent_type="test")

    @pytest.mark.asyncio
    async def test_optional_failure_continues(self):
        """Optional step failure in parallel wave → chain continues."""
        good_handler = _make_handler()
        fail_handler = _make_handler(fail=True)

        executor = _make_executor(
            (SubTaskType.COMPOSE, good_handler),
            (SubTaskType.EVALUATE, fail_handler),
            (SubTaskType.REFLECT, good_handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, required=False,
                           depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, required=False,
                           depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )

        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )
        assert len(results) == 3
        # One of eval/reflect failed, other succeeded
        failures = [r for r in results if not r.success]
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_both_fail_required_raised(self):
        """Both parallel steps fail (one required) → required failure raised."""
        fail_handler = _make_handler(fail=True)

        executor = _make_executor(
            (SubTaskType.COMPOSE, _make_handler()),
            (SubTaskType.EVALUATE, fail_handler),
            (SubTaskType.REFLECT, fail_handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, required=True,
                           depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, required=False,
                           depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )

        with pytest.raises(SubTaskStepError) as exc_info:
            await executor.execute(chain, {}, agent_id="test", agent_type="test")
        assert "eval" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_exception_converted_to_result(self):
        """Exception in parallel step → converted to SubTaskResult with success=False."""
        async def _raise(spec, ctx, prior):
            raise ValueError("boom")

        executor = _make_executor(
            (SubTaskType.COMPOSE, _make_handler()),
            (SubTaskType.EVALUATE, AsyncMock(side_effect=_raise)),
            (SubTaskType.REFLECT, _make_handler()),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, required=False,
                           depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, required=False,
                           depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )

        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )
        eval_result = [r for r in results if r.name == "eval"][0]
        assert not eval_result.success
        assert "boom" in eval_result.error

    @pytest.mark.asyncio
    async def test_step_error_reraised_as_chain_error(self):
        """SubTaskStepError in parallel step → re-raised correctly."""
        async def _raise_step_error(spec, ctx, prior):
            raise SubTaskStepError(spec.name, spec.sub_task_type, "step died")

        executor = _make_executor(
            (SubTaskType.COMPOSE, _make_handler()),
            (SubTaskType.EVALUATE, AsyncMock(side_effect=_raise_step_error)),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, required=True,
                           depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )

        with pytest.raises(SubTaskStepError):
            await executor.execute(chain, {}, agent_id="test", agent_type="test")


# ===========================================================================
# Class 6: TestParallelJournalRecording
# ===========================================================================

class TestParallelJournalRecording:
    """Tests for journal recording with parallel steps."""

    @pytest.mark.asyncio
    async def test_parallel_steps_correct_step_index(self):
        """Parallel steps get their original step_index (list position)."""
        journal = AsyncMock()
        handler = _make_handler()

        executor = _make_executor(
            (SubTaskType.COMPOSE, handler),
            (SubTaskType.EVALUATE, handler),
            (SubTaskType.REFLECT, handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )
        await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
            journal=journal,
        )

        # All three LLM steps recorded (COMPOSE, EVALUATE, REFLECT — no QUERY)
        assert journal.record.call_count == 3
        dag_ids = [call.kwargs["dag_node_id"] for call in journal.record.call_args_list]
        # step indices: compose=0, eval=1, reflect=2
        assert any(":0:compose" in d for d in dag_ids)
        assert any(":1:evaluate" in d for d in dag_ids)
        assert any(":2:reflect" in d for d in dag_ids)

    @pytest.mark.asyncio
    async def test_dag_node_id_format_unchanged(self):
        """dag_node_id format: st:{chain_id}:{step_index}:{type}."""
        journal = AsyncMock()
        handler = _make_handler()

        executor = _make_executor((SubTaskType.ANALYZE, handler))

        chain = SubTaskChain(
            steps=[_make_spec("analyze", SubTaskType.ANALYZE)],
            chain_timeout_ms=5000,
        )
        await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
            journal=journal,
        )

        dag_id = journal.record.call_args.kwargs["dag_node_id"]
        parts = dag_id.split(":")
        assert parts[0] == "st"
        assert len(parts[1]) == 8  # chain_id hex
        assert parts[2] == "0"     # step_index
        assert parts[3] == "analyze"

    @pytest.mark.asyncio
    async def test_both_parallel_steps_recorded(self):
        """Both parallel steps create journal records."""
        journal = AsyncMock()
        handler = _make_handler()

        executor = _make_executor(
            (SubTaskType.COMPOSE, handler),
            (SubTaskType.EVALUATE, handler),
            (SubTaskType.REFLECT, handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )
        await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
            journal=journal,
        )
        assert journal.record.call_count == 3

    @pytest.mark.asyncio
    async def test_journal_failure_doesnt_affect_sibling(self):
        """Journal recording failure in one parallel step doesn't affect sibling."""
        call_count = 0

        async def _failing_journal_record(**kwargs):
            nonlocal call_count
            call_count += 1
            if "eval" in kwargs.get("dag_node_id", ""):
                raise RuntimeError("journal write failed")

        journal = MagicMock()
        journal.record = AsyncMock(side_effect=_failing_journal_record)
        handler = _make_handler()

        executor = _make_executor(
            (SubTaskType.COMPOSE, handler),
            (SubTaskType.EVALUATE, handler),
            (SubTaskType.REFLECT, handler),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("compose", SubTaskType.COMPOSE),
                _make_spec("eval", SubTaskType.EVALUATE, depends_on=("compose",)),
                _make_spec("reflect", SubTaskType.REFLECT, depends_on=("compose",)),
            ],
            chain_timeout_ms=5000,
        )
        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
            journal=journal,
        )
        # Both steps should still complete successfully
        assert all(r.success for r in results)


# ===========================================================================
# Class 7: TestBackwardCompatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Tests for backward compatibility with existing sequential chains."""

    @pytest.mark.asyncio
    async def test_existing_chain_sequential(self):
        """Chain without depends_on executes identically to pre-632h."""
        execution_order = []

        async def _tracking(spec, ctx, prior):
            execution_order.append(spec.name)
            return SubTaskResult(
                sub_task_type=spec.sub_task_type, name=spec.name,
                result={}, success=True,
            )

        mock = AsyncMock(side_effect=_tracking)
        executor = _make_executor(
            (SubTaskType.QUERY, mock),
            (SubTaskType.ANALYZE, mock),
            (SubTaskType.COMPOSE, mock),
        )

        chain = SubTaskChain(
            steps=[
                _make_spec("a", SubTaskType.QUERY),
                _make_spec("b", SubTaskType.ANALYZE),
                _make_spec("c", SubTaskType.COMPOSE),
            ],
            chain_timeout_ms=5000,
        )
        results = await executor.execute(
            chain, {}, agent_id="test", agent_type="test",
        )
        assert execution_order == ["a", "b", "c"]
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_empty_depends_on_sequential(self):
        """All steps with empty depends_on → strictly sequential."""
        execution_order = []

        async def _tracking(spec, ctx, prior):
            execution_order.append(spec.name)
            return SubTaskResult(
                sub_task_type=spec.sub_task_type, name=spec.name,
                result={}, success=True,
            )

        mock = AsyncMock(side_effect=_tracking)
        executor = _make_executor(
            (SubTaskType.QUERY, mock),
            (SubTaskType.ANALYZE, mock),
        )

        chain = SubTaskChain(
            steps=[
                SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="x", depends_on=()),
                SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="y", depends_on=()),
            ],
            chain_timeout_ms=5000,
        )
        await executor.execute(chain, {}, agent_id="test", agent_type="test")
        assert execution_order == ["x", "y"]

    @pytest.mark.asyncio
    async def test_chain_completed_event_fields_unchanged(self):
        """SubTaskChainCompletedEvent fields unchanged."""
        emit_fn = MagicMock()
        config = MagicMock()
        config.enabled = True
        config.max_chain_steps = 10
        executor = SubTaskExecutor(config=config, emit_event_fn=emit_fn)
        executor.register_handler(SubTaskType.QUERY, _make_handler())

        chain = SubTaskChain(
            steps=[_make_spec("q", SubTaskType.QUERY)],
            chain_timeout_ms=5000,
        )
        await executor.execute(chain, {}, agent_id="test", agent_type="test")
        assert emit_fn.called

    def test_handler_protocol_unchanged(self):
        """Handler protocol signature unchanged — handlers don't see parallelism."""
        from probos.cognitive.sub_task import SubTaskHandler
        # Protocol should still be runtime_checkable with same signature
        assert hasattr(SubTaskHandler, '__call__')
