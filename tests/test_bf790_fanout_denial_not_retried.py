"""BF-790 (#1254): a denied fan-out send must not be re-submitted.

``thread_fanout._dispatch_intent`` opts into ``raise_on_denial=True`` and
reports the refusal as a third return element, ``_denied``; the BF-636
addressed-retry is then gated on it::

    if not reply_text.strip() and _is_addressed and not _denied:
        result, reply_text, _denied = await _dispatch_intent()

Without either half a denial is indistinguishable from a transient empty LLM
result, so the addressed-retry re-submits the refused intent and a stateful
pre-intent hook -- a rate limiter, a quota -- is charged TWICE for one turn.
That is the exact harm BF-771's evaluate-once rule exists to prevent.

WHY THIS FILE EXISTS. The original guard lived in
``test_bf790_denial_is_not_success.py`` and asserted on the ``ast`` of
``thread_fanout``. AD-1251 deleted that file, and BF-773 measured the same day
that three separate ways of breaking a disclosure all SURVIVED a source-text
assertion: a source scan proves a line is written, never that it runs. So this
drives the real ``group_chat_fanout`` and counts delivery ATTEMPTS at the
policy boundary. Removing ``raise_on_denial=True`` or the ``not _denied``
guard makes the count go to two.

BF-287 discipline, and the harness is ported from
``test_bf636_empty_result_thinning.py`` (which owns the positive case, that an
addressed agent DOES get one retry when the failure is transient): real
``ChatThreadStore`` on ``tmp_path``, real ``IntentBus(SignalManager(...))``,
real ``GroupChatConfig``, real AD-698 hook registry, real-but-fake
registry/agents with scripted ``direct_message`` handlers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import GroupChatConfig
from probos.extensions import overlay
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


@pytest.fixture(autouse=True)
def _clean_hook_registry():
    overlay.reset_for_tests()
    yield
    overlay.reset_for_tests()


# ---------------- BF-287 real-but-fake substrate ----------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str) -> _FakeAgent | None:
        return self._a.get(agent_id)


class _FakeCallsigns:
    def get_callsign(self, agent_type: str) -> str:
        return {"scout": "Scout", "diagnostician": "Bones"}.get(agent_type, "")


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _scripted(agent_id: str, replies: list[str]):
    state = {"n": 0}

    async def _h(intent: IntentMessage) -> IntentResult:
        text = replies[min(state["n"], len(replies) - 1)]
        state["n"] += 1
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=text,
        )

    return _h


def _build_env(tmp_path, *, bones_replies: list[str], deny_bones: bool):
    """Two-crew room where Scout hands the turn to Bones.

    ``attempts`` records every delivery the AD-698 boundary was asked to
    authorize, which counts a refused send as well as a delivered one -- the
    handler never runs on a denial, so a handler-side counter cannot see the
    re-submission this test is about.
    """
    attempts: list[tuple[str, str]] = []

    def _hook(intent: Any) -> bool:
        target = getattr(intent, "target_agent_id", "") or ""
        attempts.append((target, (getattr(intent, "params", None) or {}).get("text", "")))
        return not (deny_bones and target == "bones1")

    overlay.register_pre_intent_authorization_hook("bf790-test-policy", _hook)

    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    bus.subscribe("scout1", _scripted("scout1", ["@Bones your read?"]), intent_names=["direct_message"])
    bus.subscribe("bones1", _scripted("bones1", bones_replies), intent_names=["direct_message"])
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry({"scout1": _FakeAgent("scout"), "bones1": _FakeAgent("diagnostician")}),
        ontology=None,
        callsign_registry=_FakeCallsigns(),
        project_store=None,
        config=SimpleNamespace(
            group_chat=GroupChatConfig(
                agent_reactivity_enabled=True,
                agent_next_speaker_selection_enabled=True,
                max_agent_rounds=1,
                max_speakers_per_turn=1,
            ),
            attachments=None,
        ),
    )
    return store, runtime, attempts


async def _run(store, runtime) -> tuple[str, list[dict[str, str]]]:
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="thoughts team?",
    )
    replies = await group_chat_fanout(
        runtime, t.id, captain_body="thoughts team?", captain_msg=cap,
    )
    return t.id, replies


def _agent_bodies(store, thread_id: str) -> list[str]:
    return [
        m.body for m in store.list_messages(thread_id, limit=1000) if m.role == "agent"
    ]


_HANDOFF = "Scout: @Bones your read?"


async def test_a_denied_addressed_fanout_send_is_not_re_submitted(tmp_path) -> None:
    """The load-bearing assertion: ONE attempt at the refused recipient.

    Scout speaks round 0 (cap of one) and hands off to Bones by callsign, so
    Bones is hard-included and ADDRESSED in round 1 -- the only state in which
    the BF-636 retry fires at all. Policy then refuses Bones. A refusal is not
    a transient failure, so it must not be tried again.
    """
    store, runtime, attempts = _build_env(
        tmp_path, bones_replies=["would-be retry reply"], deny_bones=True,
    )

    thread_id, replies = await _run(store, runtime)

    bones = [text for target, text in attempts if target == "bones1"]
    assert bones == [_HANDOFF], (
        "the addressed round must attempt the refused recipient exactly once; "
        f"got {len(bones)} attempts: {bones}"
    )
    # Premise: the cascade round really ran and really addressed Bones -- the
    # single attempt above carried the hand-off, not the Captain's turn.
    assert [r["agent_id"] for r in replies] == ["scout1"]
    assert "would-be retry reply" not in _agent_bodies(store, thread_id)


async def test_an_addressed_agent_is_retried_when_the_failure_is_transient(
    tmp_path,
) -> None:
    """Discrimination control. Without it the test above passes trivially on an
    implementation that never retries anything, which would break the BF-636
    recovery the guard is carved out of."""
    store, runtime, attempts = _build_env(
        tmp_path, bones_replies=["", "I concur, proceed."], deny_bones=False,
    )

    _thread_id, replies = await _run(store, runtime)

    bones = [text for target, text in attempts if target == "bones1"]
    assert bones == [_HANDOFF, _HANDOFF], (
        "an ADDRESSED agent whose first reply is transiently empty must be "
        f"retried exactly once; got {len(bones)} attempts"
    )
    assert [r["agent_id"] for r in replies] == ["scout1", "bones1"]
    assert replies[1]["text"] == "I concur, proceed."
