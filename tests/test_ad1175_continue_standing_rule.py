"""AD-1175: an exhausted turn can be granted a standing rule to continue.

AD-1164 gave a turn that hits its step limit a second pass — but only while a
live standing rule permits it. Nothing could ever issue that rule, so the branch
was dormant from the day it shipped, and the reference vessel's log said so on
every single run:

    reached its step limit on pass 1/2 and no standing rule covers
    continuation, so the turn stops and the Captain is asked

The cause was circular and total. `_maybe_issue_standing_rule` refused anything
where `kind != "action"`, and AD-1164's continue request uses `kind="continue"`.
The only path to the rule refused the only kind that needed it.

The guard's stated reason was that other kinds "have no action shape to scope a
standing rule to". That is true of `grant`/`install`/`build`, which name a
capability to acquire rather than an operation to repeat — and false of
`continue`, whose payload is the same validated six-key shape as an `action`
request. The guard tested the kind label rather than the shape.
"""

from __future__ import annotations

import pytest

from probos.cognitive.continue_or_ask import (
    CONTINUE_ACTION,
    CONTINUE_REQUEST_KIND,
    CONTINUE_SCOPE_KEY,
    CONTINUE_TOOL_ID,
    continue_payload,
)
from probos.routers.capability_requests import _STANDING_RULE_KINDS


# ── the headline ──────────────────────────────────────────────────


def test_a_continue_request_can_be_scoped_to_a_standing_rule() -> None:
    """THE AD-1175 regression.

    Before this, `continue` was not in the set, so AD-1164's second pass could
    never be armed by any means.
    """
    assert CONTINUE_REQUEST_KIND in _STANDING_RULE_KINDS


def test_the_action_kind_is_unchanged() -> None:
    """AD-1154's original behaviour must be untouched."""
    assert "action" in _STANDING_RULE_KINDS


@pytest.mark.parametrize("kind", ["grant", "install", "build"])
def test_capability_kinds_still_get_no_standing_rule(kind: str) -> None:
    """These name a capability to ACQUIRE, not an operation to repeat. There is
    nothing to scope a rule to, and admitting them would grant durable
    privilege from a one-time approval."""
    assert kind not in _STANDING_RULE_KINDS


def test_the_allowlist_is_explicit() -> None:
    """Per Minimal Authority: a future kind gets a standing rule when someone
    decides it should, not by inheriting one from "has a payload"."""
    assert _STANDING_RULE_KINDS == frozenset({"action", "continue"})


# ── the payload really does have an action shape ──────────────────


def test_the_continue_payload_is_a_valid_action_payload() -> None:
    """The premise of the fix, asserted rather than assumed.

    A standing rule is keyed on (agent, tool_id, action, scope_key) taken from
    the payload. If a continue request did not carry a valid one, admitting the
    kind would produce an unscopable rule.
    """
    from probos.capability_request import validate_action_payload

    payload = continue_payload("thread-1")
    assert validate_action_payload(payload) is not None
    assert payload["tool_id"] == CONTINUE_TOOL_ID
    assert payload["action"] == CONTINUE_ACTION
    assert payload["scope_key"] == CONTINUE_SCOPE_KEY


def test_the_rule_scope_matches_what_the_gate_reads() -> None:
    """`_standing_rule_permits` looks up exactly this tuple. If the payload and
    the lookup disagreed, a granted rule would never be found."""
    payload = continue_payload("thread-1")
    assert (
        payload["tool_id"], payload["action"], payload["scope_key"]
    ) == (CONTINUE_TOOL_ID, CONTINUE_ACTION, CONTINUE_SCOPE_KEY)


def test_a_non_string_thread_id_still_yields_a_valid_payload() -> None:
    from probos.capability_request import validate_action_payload

    assert validate_action_payload(continue_payload(None)) is not None
    assert validate_action_payload(continue_payload(12345)) is not None


# ── the gate still fails closed ───────────────────────────────────


def test_the_continue_gate_fails_closed_without_a_store() -> None:
    """A granted rule is the ONLY thing that arms pass 2. Every failure to read
    one must mean "ask the Captain" -- the direction that cannot manufacture
    authority out of a failure."""
    from types import SimpleNamespace

    from probos.cognitive.continue_or_ask import _standing_rule_permits

    assert _standing_rule_permits(SimpleNamespace(), "agent-1") is False
    assert _standing_rule_permits(
        SimpleNamespace(action_approval_store=None), "agent-1",
    ) is False


def test_the_continue_gate_fails_closed_on_a_raising_store() -> None:
    from types import SimpleNamespace

    from probos.cognitive.continue_or_ask import _standing_rule_permits

    class _Boom:
        def is_approved_sync(self, *_a, **_k):
            raise RuntimeError("cache down")

    assert _standing_rule_permits(
        SimpleNamespace(action_approval_store=_Boom()), "agent-1",
    ) is False


def test_a_live_rule_permits_continuation() -> None:
    from types import SimpleNamespace

    from probos.cognitive.continue_or_ask import _standing_rule_permits

    class _Store:
        def __init__(self) -> None:
            self.asked: list[tuple] = []

        def is_approved_sync(self, agent_id, tool_id, action, scope_key):
            self.asked.append((agent_id, tool_id, action, scope_key))
            return True

    store = _Store()
    assert _standing_rule_permits(
        SimpleNamespace(action_approval_store=store), "agent-1",
    ) is True
    # It asks for exactly the tuple the continue payload declares.
    assert store.asked == [
        ("agent-1", CONTINUE_TOOL_ID, CONTINUE_ACTION, CONTINUE_SCOPE_KEY)
    ]
