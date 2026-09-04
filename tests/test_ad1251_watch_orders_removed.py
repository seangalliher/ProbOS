"""AD-1251: the watch-order dispatch half is gone; the roster half is live.

``WatchManager`` carried two halves. The dispatch half -- ``StandingTask``,
``CaptainOrder``, and the two sweeps that fed them to the intent bus -- had no
producer anywhere in ``src``: ``CaptainOrder(`` was never constructed and
``add_standing_task`` was never called, so the loop swept two permanently empty
lists and ``/watch`` reported ``Active orders: 0`` structurally rather than
factually. BF-790, BF-790a and BF-814 were three fixes to that unreachable
path. AD-1251 deleted it.

Deleting it removes no Captain capability, and these tests are the evidence:
orders live in :class:`~probos.cognitive.orders.OrderManager`, which has a real
producer in ``cognitive/crew_delegation.py`` and enforces the chain of command.

BF-287 (HARD) for the delegation test below: it walks the real chain of command
and reads ``authority_over`` off real posts, so it uses a real
:class:`VesselOntologyService`, a real :class:`AgentRegistry` holding concrete
:class:`BaseAgent` instances, and a real :class:`OrderManager`. A MagicMock
would auto-create every attribute and pass against a phantom name.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from probos.cognitive.crew_assignment import AssignmentDecision
from probos.cognitive.crew_delegation import CrewDelegator
from probos.cognitive.orders import OrderManager, OrderState
from probos.federation.bridge import FederationForwardOutcome
from probos.mesh.intent import IntentBus, IntentNoSubscriber
from probos.mesh.signal import SignalManager
from probos.ontology import VesselOntologyService
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage, IntentResult
from probos.watch_rotation import WatchManager, WatchType


# ── 1. Anti-resurrection ────────────────────────────────────────────

# Every name below exists on the pre-AD-1251 ``WatchManager`` (measured: all
# four ``hasattr`` True at b4acdbfe, all four False after). A future AD that
# reintroduces watch-scheduled orders must DELETE this assertion and say in its
# prompt why a second orders path beside ``OrderManager`` is the right shape --
# the burden the three prior fixes never had to meet.
_REMOVED_WATCH_ORDER_NAMES = (
    "issue_order",
    "rescind_order",
    "get_active_orders",
    "add_standing_task",
    "remove_standing_task",
    "get_standing_tasks",
    "_captain_orders",
    "_standing_tasks",
    "_dispatch_due_orders",
    "_dispatch_due_tasks",
    "_dispatch_fn",
)


def test_watch_manager_carries_no_order_surface() -> None:
    mgr = WatchManager()
    present = [n for n in _REMOVED_WATCH_ORDER_NAMES if hasattr(mgr, n)]
    assert present == [], (
        f"AD-1251 removed these from WatchManager; still present: {present}"
    )


def test_watch_rotation_module_exports_no_order_types() -> None:
    import probos.watch_rotation as wr

    assert not hasattr(wr, "CaptainOrder")
    assert not hasattr(wr, "StandingTask")
    # The Night Orders feature is a DIFFERENT system in the same module and is
    # untouched -- confusing the two is the trap #1282 names.
    assert hasattr(wr, "NightOrders")
    assert hasattr(wr, "NightOrdersManager")
    assert hasattr(wr, "NIGHT_ORDER_TEMPLATES")


def test_runtime_has_no_watch_dispatch_bridge() -> None:
    from probos.runtime import ProbOSRuntime

    assert not hasattr(ProbOSRuntime, "_dispatch_watch_intent")


# ── 2. The status payload ───────────────────────────────────────────

def test_get_watch_status_key_set_is_exact() -> None:
    mgr = WatchManager()
    mgr.assign_to_watch("a1", WatchType.ALPHA)

    status = mgr.get_watch_status()

    assert set(status) == {
        "current_watch",
        "time_appropriate_watch",
        "on_duty",
        "roster",
    }
    assert status["on_duty"] == ["a1"]


def test_get_watch_status_drops_the_structurally_zero_counters() -> None:
    # Both counted lists nothing could append to, so both were always 0 and
    # read to the Captain as "no orders outstanding".
    status = WatchManager().get_watch_status()
    assert "standing_tasks_count" not in status
    assert "active_orders_count" not in status


# ── 3. The surviving half is live, not assumed ──────────────────────

@pytest.mark.asyncio
async def test_started_manager_auto_rotates_by_wall_clock() -> None:
    """The loop that remains still does the one job it kept.

    Drives the real ``start()``/``stop()`` pair rather than calling
    ``auto_rotate()`` directly, so an empty loop body fails here.
    """
    with patch("probos.watch_rotation.datetime") as mock_dt:
        mock_dt.now.return_value.hour = 20  # BETA window
        mgr = WatchManager(check_interval=0.02)
        mgr.set_current_watch(WatchType.ALPHA)
        assert mgr.current_watch is WatchType.ALPHA  # premise: rotation is due

        await mgr.start()
        try:
            deadline = time.monotonic() + 5.0
            while mgr.current_watch is not WatchType.BETA:
                assert time.monotonic() < deadline, "loop never rotated the watch"
                await asyncio.sleep(0.01)
        finally:
            await mgr.stop()

        assert mgr.current_watch is WatchType.BETA

        # ...and a stopped manager stops rotating.
        mock_dt.now.return_value.hour = 3  # GAMMA window
        await asyncio.sleep(0.15)  # several check_intervals
        assert mgr.current_watch is WatchType.BETA


# ── 4. No capability was lost: OrderManager still works ─────────────

class _CrewAgent(BaseAgent):
    """Concrete BaseAgent so the registry holds a real ``.id``/``.agent_type``."""

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


@pytest.fixture
async def ontology(tmp_path: Path) -> VesselOntologyService:
    src = Path(__file__).resolve().parents[1] / "config" / "ontology"
    dst = tmp_path / "ontology"
    shutil.copytree(src, dst)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    svc = VesselOntologyService(dst, data_dir=data_dir)
    await svc.initialize()
    return svc


async def _wire(
    ontology: VesselOntologyService,
    registry: AgentRegistry,
    *,
    ontology_type: str,
    agent_id: str,
    registry_type: str | None = None,
) -> None:
    ontology.wire_agent(ontology_type, agent_id)
    agent = _CrewAgent(agent_id=agent_id)
    agent.agent_type = registry_type or ontology_type
    await registry.register(agent)


def _decision(spec_id: str, agent_id: str) -> AssignmentDecision:
    return AssignmentDecision(
        spec_id=spec_id,
        agent_id=agent_id,
        department="engineering",
        capability="build code",
        score=0.5,
        reason="capability_match",
    )


@pytest.mark.asyncio
async def test_crew_delegation_still_issues_a_real_order(
    ontology: VesselOntologyService,
) -> None:
    """The producer AD-1251 leaves standing, end to end.

    ``crew_delegation`` resolves the worker's chief and issues through
    ``OrderManager`` -- the orders path that always had a producer, which is
    why deleting the watch-order surface costs the Captain nothing.
    """
    registry = AgentRegistry()
    await _wire(ontology, registry, ontology_type="engineering_officer", agent_id="chief-eng-1")
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    mgr = OrderManager(ontology=ontology, registry=registry)
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s1", "builder-1"))

    assert result.delegated is True
    assert result.reason == "delegated_via_chief"
    assert result.chief_agent_id == "chief-eng-1"
    assert result.order_id is not None

    # The order is really in the manager, addressed down the chain, and
    # acknowledgeable by the subordinate it was issued to.
    order = next(o for o in mgr.all_orders() if o.id == result.order_id)
    assert order.from_agent_id == "chief-eng-1"
    assert order.to_post_id == "builder_officer"
    assert order.state == OrderState.PENDING
    assert mgr.acknowledge(order.id, "builder-1") is True


@pytest.mark.asyncio
async def test_crew_delegation_out_of_chain_is_rejected(
    ontology: VesselOntologyService,
) -> None:
    """Authority is still enforced -- the chain of command is the live one."""
    registry = AgentRegistry()
    # chief_engineer billet filled by an agent whose real role (scout) holds no
    # authority over builder_officer.
    await _wire(
        ontology, registry,
        ontology_type="engineering_officer", agent_id="rogue-1", registry_type="scout",
    )
    await _wire(ontology, registry, ontology_type="builder", agent_id="builder-1")
    emitted: list[tuple[Any, dict[str, Any]]] = []
    mgr = OrderManager(
        ontology=ontology, registry=registry,
        emit_event=lambda et, data: emitted.append((et, data)),
    )
    delegator = CrewDelegator(ontology=ontology, order_manager=mgr, agent_registry=registry)

    result = delegator.delegate(_decision("s2", "builder-1"))

    assert result.delegated is False
    assert result.reason == "out_of_chain"
    assert result.order_id is None
    assert any(d.get("reason") == "out_of_chain" for _, d in emitted)
    assert mgr.all_orders() == []


# ── 5. Rescued from the BF-814 suite ────────────────────────────────

def _bus() -> IntentBus:
    return IntentBus(SignalManager())


async def _noop(msg: IntentMessage) -> None:
    return None


async def _refuses_delivery(bus: IntentBus, intent_name: str = "nobody") -> bool:
    """Drive the AD-1297 opt-in against ``bus``; True when it refused delivery.

    Returning a bool rather than wrapping each row in ``pytest.raises`` keeps
    the matrix below symmetric -- the raising row and the four non-raising rows
    run the identical call.
    """
    try:
        await bus.publish(
            IntentMessage(intent=intent_name, params={}),
            raise_on_no_subscriber=True,
        )
    except IntentNoSubscriber:
        return True
    return False


class TestIntentBusNoSubscriberSeam:
    """Rescued verbatim from ``test_bf814_no_subscriber_is_not_execution.py``
    when AD-1251 deleted the watch-order surface that file was written around.

    They exercise ``IntentBus`` alone and touch nothing AD-1251 removed. They
    are here because the ``broadcast(raise_on_no_subscriber=True)`` opt-in is
    DELIBERATELY RETAINED (AD-1297) with no production caller left in ``src``
    -- deleting its only coverage along with the watch bridge would leave a
    retained seam with nothing proving it, which is #1282's defect shape one
    level down.

    ``candidate_agent_ids`` is a DIFFERENT case and is kept here for
    continuity, not necessity: it still has a live production caller at
    ``federation/bridge.py:1716``, where AD-1297's inbound half reports whether
    this node admitted a federated intent.

    NOT ported: ``test_without_federation_an_empty_mesh_still_refuses``, which
    drives ``ProbOSRuntime._dispatch_watch_intent`` -- deleted surface. Porting
    it needs a stand-in consumer, which is a design choice, not a move.
    """

    def test_no_subscribers_means_no_candidates(self) -> None:
        assert _bus().candidate_agent_ids("anything") == set()

    def test_a_filtered_subscriber_is_a_candidate_for_its_own_intent(self) -> None:
        bus = _bus()
        bus.subscribe("a1", _noop, ["mine"])
        assert bus.candidate_agent_ids("mine") == {"a1"}

    def test_an_unfiltered_subscriber_is_a_candidate_for_every_intent(self) -> None:
        """The fallback that makes "no subscriber" narrower than it looks: an agent
        registering no intent_names is reached by everything."""
        bus = _bus()
        bus.subscribe("catch_all", _noop)
        assert bus.candidate_agent_ids("anything_at_all") == {"catch_all"}

    def test_a_filtered_subscriber_is_not_a_candidate_for_another_indexed_intent(
        self,
    ) -> None:
        """Only discriminates once the other intent is in the index -- otherwise the
        fallback branch applies and everyone is a candidate."""
        bus = _bus()
        bus.subscribe("a1", _noop, ["mine"])
        bus.subscribe("a2", _noop, ["yours"])
        assert bus.candidate_agent_ids("mine") == {"a1"}
        assert bus.candidate_agent_ids("yours") == {"a2"}

    @pytest.mark.asyncio
    async def test_the_predicate_agrees_with_what_broadcast_actually_invokes(
        self,
    ) -> None:
        """The two must not drift: broadcast reads this same computation. A
        predicate that disagreed with the fan-out would be worse than none."""
        bus = _bus()
        invoked: list[str] = []

        async def record(msg: IntentMessage) -> IntentResult:
            invoked.append("a1")
            return IntentResult(intent_id=msg.id, agent_id="a1", success=True)

        bus.subscribe("a1", record, ["mine"])
        predicted = bus.candidate_agent_ids("mine")
        await bus.publish(IntentMessage(intent="mine", params={}))
        assert set(invoked) == predicted

    @pytest.mark.asyncio
    async def test_raise_on_no_subscriber_still_raises_when_driven_directly(
        self,
    ) -> None:
        """The AD-1297 seam kept alive after its only caller was deleted.

        ``_dispatch_watch_intent`` was the sole production site passing
        ``raise_on_no_subscriber=True``, and AD-1251 deleted it. The kwarg is
        retained deliberately -- ``broadcast``'s docstring carries the two
        reasons and what the default path still costs -- but retaining a seam
        on a stated rationale with nothing exercising it is precisely the
        defect BF-818 exists to remove, one level down. So the seam is proven
        against the bus directly, which is where the behaviour actually lives;
        the deleted bridge was only ever a caller of it.
        """
        bus = _bus()

        with pytest.raises(IntentNoSubscriber):
            await bus.publish(
                IntentMessage(intent="nobody", params={}),
                raise_on_no_subscriber=True,
            )

    @pytest.mark.asyncio
    async def test_an_unsubscribed_intent_is_silent_without_the_opt_in(
        self,
    ) -> None:
        """Control for the test above -- without it, that one proves nothing.

        If publishing to an empty mesh raised unconditionally, the previous
        test would pass with the kwarg gone entirely. This pins that the raise
        is caused by the opt-in and not by the empty mesh.
        """
        bus = _bus()

        await bus.publish(IntentMessage(intent="nobody", params={}))

    # ── the retained contract, clause by clause ─────────────────────
    #
    # The raise needs FOUR conditions at once (intent.py, AD-1297):
    #
    #     raise_on_no_subscriber and not candidate_ids and not results
    #     and federation_admitted == 0 and federation_unknown == 0
    #
    # The two tests above drive only the all-zero corner, so three of those
    # clauses had no branch coverage once the watch bridge was deleted. The
    # matrix below pins each one independently. Ported mechanically from the
    # ``test_bf814_no_subscriber_is_not_execution.py`` cases AD-1251 deleted:
    # same federation shapes, same reasoning, driven against the bus rather
    # than through the WatchManager sweep that no longer exists.

    @pytest.mark.asyncio
    async def test_a_local_handler_returning_none_is_still_a_candidate(
        self,
    ) -> None:
        """The ``not candidate_ids`` clause alone.

        A handler that runs, performs its side effect and returns ``None``
        leaves ``results`` empty -- which is why an empty list can never be the
        delivery signal. Only the candidate set separates this from reaching
        nobody, and reading it wrong re-fires real work.
        """
        bus = _bus()
        ran: list[str] = []

        async def acts_then_returns_none(msg: IntentMessage) -> None:
            ran.append(msg.intent)
            return None

        bus.subscribe("worker", acts_then_returns_none, ["mine"])

        refused = await _refuses_delivery(bus, "mine")

        assert ran == ["mine"], "premise: the handler really was invoked"
        assert refused is False

    @pytest.mark.parametrize(
        ("outcome", "expect_refusal"),
        [
            pytest.param(
                lambda: FederationForwardOutcome(
                    peers_attempted=1, peers_answered=1,
                    peers_admitted=1, peers_unknown=0,
                ),
                False,
                id="a_peer_admitted_it",
            ),
            pytest.param(
                lambda: FederationForwardOutcome(
                    peers_attempted=2, peers_answered=0,
                    peers_admitted=0, peers_unknown=2,
                ),
                False,
                id="peers_attempted_and_silent_is_unknown",
            ),
            pytest.param(
                lambda: FederationForwardOutcome(
                    peers_attempted=1, peers_answered=1,
                    peers_admitted=0, peers_unknown=0,
                ),
                True,
                id="every_peer_answered_no_candidate",
            ),
            pytest.param(
                lambda: FederationForwardOutcome(
                    [IntentResult(intent_id="i-1", agent_id="remote", success=True)],
                    peers_attempted=1, peers_answered=1,
                    peers_admitted=0, peers_unknown=0,
                ),
                False,
                id="a_remote_result_proves_delivery",
            ),
            pytest.param(
                list,
                False,
                id="a_legacy_callback_is_unknown_not_absent",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_each_federation_clause_independently_blocks_the_raise(
        self, outcome: Any, expect_refusal: bool,
    ) -> None:
        """One row per clause, all with zero local candidates.

        ``admitted`` -- a peer took delivery, so something may have run it.
        ``unknown`` -- peers were attempted and stayed silent; silence proves
        nothing, and treating it as absence was measured producing duplicate
        remote side effects. ``results`` -- a remote reply came back, which is
        delivery on its own. The legacy row is the mixed-version mesh the
        comment at ``intent.py`` marks: a callback predating
        ``FederationForwardOutcome`` reports no admission at all, and reading
        that as "no candidate" strands every order on a mesh with one
        un-upgraded node. Only the all-zeros row is a KNOWN absence.
        """
        bus = _bus()
        forwarded: list[str] = []

        async def _federate(intent: IntentMessage) -> Any:
            forwarded.append(intent.intent)
            return outcome()

        bus.set_federation_handler(_federate)
        assert bus.candidate_agent_ids("nobody") == set(), (
            "premise: no local candidate, so only federation can decide this"
        )

        refused = await _refuses_delivery(bus)

        assert forwarded == ["nobody"], "premise: federation really was consulted"
        assert refused is expect_refusal
