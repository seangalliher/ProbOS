"""AD-1273 / BF-823 slice A: an agent is born once, wired once, torn down once.

An agent is not finished when its constructor returns. Startup wires substantial
per-instance state onto it afterwards, in functions the spawner cannot see, and
``AgentSpawner.recycle`` replaces the object and reapplies none of it. BF-808
restored the *constructor* kwargs; its own docstring says the rest needs "a
runtime-owned rehydration hook, tracked separately". This is that hook.

Measured at HEAD before the fix, driving the real ``AgentSpawner.recycle``::

    CONTROL constructor kwarg (_runtime) survived : True
    BF-808 guard would report a loss              : False
      _reconciler / _store / _router / _episodic  : all False

The guard reports the agent CLEAN and every post-construction attribute is gone.
Slice A closes the cognitive-queue variant, which is the one that silently
disables a governance control: ``unregister_queue`` popped the dict and nothing
recreated the queue, so after a recycle the replacement was subscribed but
queueless — priority, backpressure and the dequeue-time circuit breaker all
bypassed — while the predecessor's processor loop stayed alive for the life of
the process, bound to a stopped object.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.agent_onboarding import AgentOnboardingService
from probos.config import PoolConfig, SystemConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.startup.finalize import make_cognitive_queue_rehydrator
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import AgentState, IntentMessage, Priority

QUEUE_REHYDRATOR = "ad654b_cognitive_queue"


class _CrewAgent(BaseAgent):
    """``scout`` is in ``_WARD_ROOM_CREW``, so ``is_crew_agent`` is True here
    without an ontology — the same predicate the production rehydrator uses."""

    agent_type = "scout"

    async def perceive(self, intent):
        return {}

    async def decide(self, observation):
        return {}

    async def act(self, decision):
        return {"success": True}

    async def report(self, result):
        return result

    async def handle_intent(self, intent):
        return None


class _NonCrewAgent(_CrewAgent):
    agent_type = "plain"


@dataclass
class _Ship:
    registry: AgentRegistry
    spawner: AgentSpawner
    bus: IntentBus
    onboarding: AgentOnboardingService
    runtime: SimpleNamespace
    pool: ResourcePool

    async def boot(self) -> BaseAgent:
        """The initial-startup path, exactly as ``runtime.create_pool`` runs it:
        ``pool.start()`` spawns without notifying, then the runtime wires."""
        await self.pool.start()
        for agent in self.registry.get_by_pool(self.pool.name):
            await self.onboarding.wire_agent(agent)
        return self.registry.get_by_pool(self.pool.name)[0]

    async def recycle(self, agent: BaseAgent) -> BaseAgent:
        """The recycle path: a degraded member, replaced by the pool."""
        agent.state = AgentState.DEGRADED
        await self.pool.check_health()
        replacement = self.registry.get(agent.id)
        assert replacement is not None
        return replacement

    async def teardown(self) -> None:
        await self.pool.stop()


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.enabled = False
    config.onboarding.naming_ceremony = False
    config.orientation.enabled = False
    return config


def _ship(*, agent_type: str = "scout", target_size: int = 1) -> _Ship:
    registry = AgentRegistry()
    spawner = AgentSpawner(registry)
    spawner.register_template("scout", _CrewAgent)
    spawner.register_template("plain", _NonCrewAgent)

    bus = IntentBus(SignalManager())

    trust = MagicMock()
    trust.get_score.return_value = 0.5
    callsigns = MagicMock()
    callsigns.get_callsign.return_value = ""

    onboarding = AgentOnboardingService(
        callsign_registry=callsigns,
        capability_registry=MagicMock(),
        gossip=MagicMock(),
        intent_bus=bus,
        trust_network=trust,
        event_log=MagicMock(log=AsyncMock()),
        identity_registry=None,
        ontology=None,
        event_emitter=MagicMock(),
        config=_config(),
        llm_client=None,
        registry=registry,
        ward_room=None,
        acm=None,
    )

    runtime = SimpleNamespace(
        ontology=None,
        registry=registry,
        intent_bus=bus,
        emit_event=lambda *a, **k: None,
        proactive_loop=None,
        onboarding=onboarding,
    )

    pool = ResourcePool(
        name=f"{agent_type}s",
        agent_type=agent_type,
        spawner=spawner,
        registry=registry,
        config=PoolConfig(default_pool_size=1, min_pool_size=1, max_pool_size=4),
        target_size=target_size,
        on_agent_spawned=onboarding.wire_agent,
        on_agent_removing=onboarding.unwire_agent,
    )
    return _Ship(registry, spawner, bus, onboarding, runtime, pool)


def _with_queue_rehydrator(ship: _Ship) -> _Ship:
    """Register the production rehydrator — the same factory finalize calls."""
    ship.onboarding.register_rehydrator(
        "*", QUEUE_REHYDRATOR,
        make_cognitive_queue_rehydrator(ship.runtime, ship.bus),
    )
    return ship


# ── the registry itself ──────────────────────────────────────────


class TestRegisterRehydrator:
    async def test_a_wildcard_rehydrator_runs_for_every_agent(self):
        ship = _ship()
        seen: list[str] = []

        async def _stamp(agent):
            seen.append(agent.agent_type)

        ship.onboarding.register_rehydrator("*", "stamp", _stamp)
        agent = await ship.boot()

        assert seen == [agent.agent_type]
        await ship.teardown()

    async def test_a_typed_rehydrator_skips_other_types(self):
        ship = _ship()
        seen: list[str] = []

        async def _stamp(agent):
            seen.append(agent.id)

        ship.onboarding.register_rehydrator("counselor", "stamp", _stamp)
        await ship.boot()

        assert seen == []
        await ship.teardown()

    async def test_reregistering_the_same_key_replaces_rather_than_doubles(self):
        """A second startup pass must not double-register. Keyed by
        (agent_type, name); the same key overwrites in place."""
        ship = _ship()
        calls: list[str] = []

        async def _first(agent):
            calls.append("first")

        async def _second(agent):
            calls.append("second")

        ship.onboarding.register_rehydrator("*", "dup", _first)
        ship.onboarding.register_rehydrator("*", "dup", _second)

        assert ship.onboarding.rehydrator_count() == 1
        await ship.boot()
        assert calls == ["second"]
        await ship.teardown()

    async def test_rehydrators_run_in_registration_order(self):
        ship = _ship()
        order: list[str] = []

        def _make(tag: str):
            async def _fn(agent):
                order.append(tag)
            return _fn

        ship.onboarding.register_rehydrator("*", "a", _make("a"))
        ship.onboarding.register_rehydrator("scout", "b", _make("b"))
        ship.onboarding.register_rehydrator("*", "c", _make("c"))
        await ship.boot()

        assert order == ["a", "b", "c"]
        await ship.teardown()

    async def test_replacing_a_key_keeps_its_original_position(self):
        """Replace semantics must not silently reorder — a rehydrator that
        legitimately depends on an earlier one would start seeing a half-built
        agent."""
        ship = _ship()
        order: list[str] = []

        def _make(tag: str):
            async def _fn(agent):
                order.append(tag)
            return _fn

        ship.onboarding.register_rehydrator("*", "a", _make("a"))
        ship.onboarding.register_rehydrator("*", "b", _make("b"))
        ship.onboarding.register_rehydrator("*", "a", _make("a2"))
        await ship.boot()

        assert order == ["a2", "b"]
        await ship.teardown()

    async def test_a_rehydrator_sees_an_already_subscribed_agent(self):
        """Ordering contract: rehydrators run AFTER the intent-bus
        subscription, because one may legitimately depend on it — the queue
        rehydrator binds a handler the bus has already indexed."""
        ship = _ship()
        subscribed_at_call_time: list[bool] = []

        async def _observe(agent):
            subscribed_at_call_time.append(agent.id in ship.bus._subscribers)

        ship.onboarding.register_rehydrator("*", "observe", _observe)
        await ship.boot()

        assert subscribed_at_call_time == [True]
        await ship.teardown()


class TestAFailingRehydratorDegrades:
    async def test_one_failure_does_not_strand_the_others(self, caplog):
        ship = _ship()
        ran: list[str] = []

        async def _ok_before(agent):
            ran.append("before")

        async def _boom(agent):
            raise RuntimeError("rehydrator exploded")

        async def _ok_after(agent):
            ran.append("after")

        ship.onboarding.register_rehydrator("*", "ok_before", _ok_before)
        ship.onboarding.register_rehydrator("*", "explodes", _boom)
        ship.onboarding.register_rehydrator("*", "ok_after", _ok_after)

        with caplog.at_level(logging.ERROR):
            agent = await ship.boot()

        assert ran == ["before", "after"]
        # Still onboarded — a bad rehydrator must not abort the wiring, or the
        # pool's rollback path tears down a healthy agent.
        assert agent.id in ship.bus._subscribers
        await ship.teardown()

    async def test_the_failure_is_logged_at_error_naming_the_rehydrator(self, caplog):
        """A silently skipped rehydrator is the exact defect AD-1273 exists to
        close, so the log has to name which one went missing."""
        ship = _ship()

        async def _boom(agent):
            raise RuntimeError("rehydrator exploded")

        ship.onboarding.register_rehydrator("*", "explodes", _boom)

        with caplog.at_level(logging.ERROR):
            agent = await ship.boot()

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any(
            "explodes" in r.getMessage() and agent.id in r.getMessage()
            for r in errors
        ), [r.getMessage() for r in errors]
        await ship.teardown()

    async def test_cancellation_is_not_swallowed(self):
        """``except Exception`` and not ``BaseException`` — a cancelled
        onboarding must stay cancelled, not be logged and skipped."""
        ship = _ship()

        async def _cancel(agent):
            raise asyncio.CancelledError()

        ship.onboarding.register_rehydrator("*", "cancels", _cancel)
        await ship.pool.start()
        agent = ship.registry.get_by_pool(ship.pool.name)[0]

        with pytest.raises(asyncio.CancelledError):
            await ship.onboarding.wire_agent(agent)
        await ship.teardown()


# ── the queue, across all three producing paths ──────────────────


class TestTheQueueSurvivesARecycle:
    async def test_the_replacement_has_a_queue_bound_to_itself(self):
        """The headline for slice A. Before the fix the replacement was
        subscribed and queueless."""
        ship = _with_queue_rehydrator(_ship())
        original = await ship.boot()

        before = ship.bus._get_agent_queue(original.id)
        assert before is not None, "premise: the predecessor HAD a queue"
        assert before._handler.__self__ is original

        replacement = await ship.recycle(original)

        assert replacement is not original
        after = ship.bus._get_agent_queue(replacement.id)
        assert after is not None
        assert after is not before
        # Identity, not equality — a queue bound to the corpse would still be a
        # queue, and would still answer _get_agent_queue.
        assert after._handler.__self__ is replacement
        await ship.teardown()

    async def test_the_predecessors_processor_task_is_done(self):
        """The leak assertion, and the one a naive fix survives: popping the
        dict leaves the processor loop running against a stopped object."""
        ship = _with_queue_rehydrator(_ship())
        original = await ship.boot()

        old_queue = ship.bus._get_agent_queue(original.id)
        old_task = old_queue._task
        assert old_task is not None and not old_task.done(), (
            "premise: the predecessor's processor was RUNNING"
        )

        await ship.recycle(original)

        assert old_task.done()
        await ship.teardown()

    async def test_backpressure_is_enforced_on_the_replacement(self):
        """A queue that exists but is never consulted passes the two tests
        above. This one fails unless the bound is live."""
        ship = _with_queue_rehydrator(_ship())
        original = await ship.boot()
        replacement = await ship.recycle(original)

        queue = ship.bus._get_agent_queue(replacement.id)
        # Sync fills — the processor cannot drain without an await point.
        for i in range(queue._max_size):
            assert queue.enqueue(IntentMessage(intent=f"fill.{i}"), Priority.NORMAL)

        assert queue.enqueue(IntentMessage(intent="overflow"), Priority.NORMAL) is False
        assert queue.pending_count() == queue._max_size
        await ship.teardown()

    async def test_a_non_crew_agent_still_gets_no_queue(self):
        """The rehydrator keeps the ``is_crew_agent`` guard the one-time loop
        had; widening it would give every utility agent a processor task."""
        ship = _with_queue_rehydrator(_ship(agent_type="plain"))
        agent = await ship.boot()

        assert ship.bus._get_agent_queue(agent.id) is None
        await ship.teardown()

    async def test_wiring_twice_produces_one_queue_and_one_subscription(self):
        """Idempotence is what lets a migration land without removing the old
        startup call in the same breath."""
        ship = _with_queue_rehydrator(_ship())
        agent = await ship.boot()

        first = ship.bus._get_agent_queue(agent.id)
        await ship.onboarding.wire_agent(agent)
        second = ship.bus._get_agent_queue(agent.id)

        assert second is first
        assert first._task is not None and not first._task.done()
        assert len(ship.bus._subscribers) == 1
        await ship.teardown()


class TestAllThreeProducingPathsAgree:
    """Initial startup, recycle and dynamic scale-up must yield the same
    rehydrated state. Compared as sets, not spot-checked."""

    @staticmethod
    def _fingerprint(ship: _Ship, agent: BaseAgent) -> set[str]:
        names = {
            name
            for name in ("_probe_one", "_probe_two")
            if getattr(agent, name, None) is not None
        }
        if ship.bus._get_agent_queue(agent.id) is not None:
            names.add("cognitive_queue")
        if agent.id in ship.bus._subscribers:
            names.add("subscribed")
        return names

    @staticmethod
    def _with_probes(ship: _Ship) -> _Ship:
        async def _probe_one(agent):
            agent._probe_one = object()

        async def _probe_two(agent):
            agent._probe_two = object()

        ship.onboarding.register_rehydrator("*", "probe_one", _probe_one)
        ship.onboarding.register_rehydrator("scout", "probe_two", _probe_two)
        return _with_queue_rehydrator(ship)

    async def test_startup_recycle_and_scale_up_produce_the_same_set(self):
        ship = self._with_probes(_ship(target_size=1))

        born = await ship.boot()
        startup = self._fingerprint(ship, born)
        assert startup, "premise: the startup path rehydrated SOMETHING"

        replacement = await ship.recycle(born)
        recycled = self._fingerprint(ship, replacement)

        added_id = await ship.pool.add_agent()
        assert added_id is not None
        added = ship.registry.get(added_id)
        scaled = self._fingerprint(ship, added)

        assert recycled == startup
        assert scaled == startup
        await ship.teardown()


# ── the teardown seam, directly ──────────────────────────────────


class _RecordingQueue:
    """Stands in for AgentCognitiveQueue at the IntentBus boundary."""

    def __init__(self, *, explode: bool = False) -> None:
        self.shut_down = False
        self._explode = explode

    async def shutdown(self) -> None:
        # Several suspension points: a caller that fired-and-forgot would
        # return long before this flag is set.
        for _ in range(3):
            await asyncio.sleep(0)
        if self._explode:
            raise RuntimeError("drain failed")
        self.shut_down = True


def _bus_with_queue(agent_id: str, queue: object) -> IntentBus:
    async def _handler(intent):
        return None

    bus = IntentBus(SignalManager())
    bus.subscribe(agent_id, _handler)
    bus.register_queue(agent_id, queue)
    return bus


class TestUnregisterQueueHandsTheQueueBack:
    def test_it_returns_the_removed_queue(self):
        """Popping and discarding is what left the processor loop alive; the
        async caller needs the object back to shut it down."""
        queue = _RecordingQueue()
        bus = _bus_with_queue("a1", queue)

        assert bus.unregister_queue("a1") is queue
        assert bus._get_agent_queue("a1") is None

    def test_it_returns_none_for_an_agent_without_a_queue(self):
        bus = IntentBus(SignalManager())
        assert bus.unregister_queue("nobody") is None


class TestTeardownStopsTheProcessor:
    async def test_unsubscribe_and_wait_awaits_the_shutdown(self):
        """Awaited, not deferred to a task: on the recycle path the
        replacement subscribes next, and a background drain would race its
        first dispatch."""
        queue = _RecordingQueue()
        bus = _bus_with_queue("a1", queue)

        await bus.unsubscribe_and_wait("a1")

        assert queue.shut_down is True
        assert bus._get_agent_queue("a1") is None

    async def test_a_queueless_agent_tears_down_cleanly(self):
        async def _handler(intent):
            return None

        bus = IntentBus(SignalManager())
        bus.subscribe("a1", _handler)

        await bus.unsubscribe_and_wait("a1")

        assert "a1" not in bus._subscribers

    async def test_a_failing_drain_does_not_abort_teardown(self, caplog):
        """Tier-2: teardown must complete even if the drain fails, or a recycle
        rollback inherits a half-unwired agent."""
        queue = _RecordingQueue(explode=True)
        bus = _bus_with_queue("a1", queue)

        with caplog.at_level(logging.ERROR):
            await bus.unsubscribe_and_wait("a1")

        assert "a1" not in bus._subscribers
        assert bus._get_agent_queue("a1") is None
        assert any(
            "a1" in r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.ERROR
        ), [r.getMessage() for r in caplog.records]

    async def test_the_sync_path_owns_its_shutdown_task(self):
        """``unsubscribe`` has no await point, so the drain is a tracked
        pending task rather than fire-and-forget."""
        queue = _RecordingQueue()
        bus = _bus_with_queue("a1", queue)

        bus.unsubscribe("a1")

        tasks = tuple(bus._pending_sub_tasks)
        assert tasks, "the drain must be owned, not dropped on the floor"
        await asyncio.gather(*tasks)
        assert queue.shut_down is True


class TestFinalizeStillWiresTheRehydrator:
    """Drift guards, not behaviour tests. The behaviour above is driven through
    the real ``make_cognitive_queue_rehydrator``; what these pin is the two
    lines inside ``finalize_startup`` that register and back-fill it, which
    cannot be reached without booting the whole runtime."""

    @staticmethod
    def _source() -> str:
        import inspect

        from probos.startup import finalize

        return inspect.getsource(finalize.finalize_startup)

    def test_startup_registers_the_queue_rehydrator(self):
        src = self._source()
        assert "make_cognitive_queue_rehydrator(" in src
        assert f'"{QUEUE_REHYDRATOR}"' in src

    def test_startup_no_longer_builds_queues_in_a_one_time_pass(self):
        """The single construction site is the rehydrator now. A second one
        here would be invisible to recycle again."""
        assert "AgentCognitiveQueue(" not in self._source()

    def test_startup_backfills_agents_that_were_wired_before_finalize(self):
        """finalize runs after ``create_pool`` has already wired every agent,
        so registration alone would leave the entire cold-boot crew queueless
        until their first recycle."""
        src = self._source()
        assert "await _rehydrate_cognitive_queue(agent)" in src


# ── review repairs: the two must-fix findings ────────────────────


class TestAFailedQueueStartDoesNotBlackholeTheAgent:
    """AD-1273 review, High: register-then-start left a blackhole.

    The idempotence guard treats "registered" as "live", so a queue whose
    ``start()`` raised stayed registered with no task draining it -- and every
    later rewire skipped, because the guard saw a queue. The agent was
    subscribed to something nothing read. That is strictly worse than having no
    queue: with no queue the intent bus path still works.
    """

    @pytest.mark.asyncio
    async def test_a_failed_start_leaves_nothing_registered(self, monkeypatch):
        ship = _with_queue_rehydrator(_ship())
        agent = _CrewAgent(agent_id="crew-1")
        await ship.registry.register(agent)

        from probos.cognitive import queue as qmod

        async def _boom(self):
            raise RuntimeError("start failed")

        monkeypatch.setattr(qmod.AgentCognitiveQueue, "start", _boom)

        await ship.onboarding.wire_agent(agent)

        # Tier-2 containment means wiring continued; what must NOT survive is a
        # registered queue with nothing draining it.
        assert ship.bus._get_agent_queue(agent.id) is None, (
            "a queue whose start() failed must not stay registered, or the "
            "idempotence guard refuses every retry"
        )

    @pytest.mark.asyncio
    async def test_the_next_wire_can_still_build_one(self, monkeypatch):
        """The control: after the failure clears, a rewire must succeed.

        Without this, 'nothing registered' would also pass against a rehydrator
        that had simply stopped working.
        """
        ship = _with_queue_rehydrator(_ship())
        agent = _CrewAgent(agent_id="crew-1")
        await ship.registry.register(agent)

        from probos.cognitive import queue as qmod

        calls = {"n": 0}
        real_start = qmod.AgentCognitiveQueue.start

        async def _fail_once(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("start failed")
            await real_start(self)

        monkeypatch.setattr(qmod.AgentCognitiveQueue, "start", _fail_once)

        await ship.onboarding.wire_agent(agent)
        assert ship.bus._get_agent_queue(agent.id) is None

        await ship.onboarding.wire_agent(agent)
        assert ship.bus._get_agent_queue(agent.id) is not None, (
            "the retry must be able to build a queue once the cause clears"
        )


class TestShutdownCannotHangOnAHandlerThatIgnoresCancellation:
    """AD-1273 review, Critical: the post-cancel await was unbounded.

    ``shutdown``'s docstring promises "up to 10s, then force cancel". It waited
    10s, cancelled, and then awaited the task WITHOUT a bound -- so a handler
    that suppresses ``CancelledError`` hung shutdown forever. Latent until this
    AD made teardown await the drain, which put it on the vessel's stop path.
    """

    @pytest.mark.asyncio
    async def test_it_abandons_a_task_that_refuses_to_die(self, monkeypatch):
        from probos.cognitive import queue as qmod

        monkeypatch.setattr(qmod, "_INFLIGHT_GRACE_SECONDS", 0.05)
        monkeypatch.setattr(qmod, "_CANCEL_GRACE_SECONDS", 0.05)

        q = qmod.AgentCognitiveQueue(
            agent_id="stuck-1",
            handler=AsyncMock(),
            should_process=lambda *a, **k: True,
            emit_event=lambda *a, **k: None,
        )

        release = asyncio.Event()

        async def _immortal():
            while not release.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue  # the exact pathology: cancellation suppressed

        task = asyncio.create_task(_immortal())
        q._task = task
        try:
            # Well under the unbounded-hang case, so a regression fails loudly
            # instead of stalling the suite.
            await asyncio.wait_for(q.shutdown(), timeout=10.0)
        finally:
            # The task outlives shutdown BY DESIGN -- abandoning it is the fix.
            # The test still has to reap it, or it keeps the loop alive.
            release.set()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        assert not task.done() or True  # returning at all is the assertion

    @pytest.mark.asyncio
    async def test_the_control_a_well_behaved_task_still_stops(self, monkeypatch):
        """If shutdown returned for everything regardless, the test above
        would prove nothing about abandoning."""
        from probos.cognitive import queue as qmod

        monkeypatch.setattr(qmod, "_INFLIGHT_GRACE_SECONDS", 0.05)
        monkeypatch.setattr(qmod, "_CANCEL_GRACE_SECONDS", 0.05)

        q = qmod.AgentCognitiveQueue(
            agent_id="tidy-1",
            handler=AsyncMock(),
            should_process=lambda *a, **k: True,
            emit_event=lambda *a, **k: None,
        )

        async def _polite():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_polite())
        q._task = task
        await asyncio.wait_for(q.shutdown(), timeout=10.0)
        assert task.done(), "a cancellable task must actually be stopped"
