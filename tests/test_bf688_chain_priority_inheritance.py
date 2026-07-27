"""BF-688: a sub-task chain inherits its originating request's LLM lane.

Observed live 2026-07-27. The Captain DM'd Anvil; the reply never arrived:

    10:11:24  BF-631 DM-recall: agent=3fc92188 q='Hello Anvil'
    10:12:16  BF-082: Anvil has 1 unread DMs, notified
    10:12:52  BF-184/187: Evaluate auto-approved for engineering_officer
                          (social obligation: dm_recipient)

Still in evaluate/reflect 88s after arrival, against the 60s `ttl_seconds`
AD-636 set for Captain DMs, so `IntentBus` returned "Agent did not respond in
time." The endpoint was healthy throughout — zero BF-612/BF-674 lines in the
window.

AD-636/637f built two halves of a solution and connected only one:

- `Priority.classify()` in types.py is the documented single source of truth
  ("Captain-originated or @mentioned -> CRITICAL; DMs -> CRITICAL"), and
  `_decide_via_llm` calls it correctly.
- `llm_client.complete()` honours it with a reserved interactive semaphore
  separate from the background lane.
- But all four sub-task handlers called `complete(request)` with no priority,
  taking the `Priority.NORMAL` default.

So a Captain DM that triages into a chain ran ONE call (the `decide()` call) in
the interactive lane and the remaining four in the background lane, competing
with sixteen agents' proactive thinking under `max_concurrent_calls = 6`.

Same defect shape as AD-1157: the mechanism existed, the caller never passed
the value. Neither is visible from either side alone — the producer looks
correct, the consumer looks correct, and nothing connects them.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from probos.cognitive.sub_task import (
    CHAIN_PRIORITY_KEY,
    resolve_chain_priority,
)
from probos.types import Priority

_HANDLER_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "probos" / "cognitive" / "sub_tasks"
)
_LLM_HANDLERS = ("analyze.py", "compose.py", "evaluate.py", "reflect.py")


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

def test_absent_priority_keeps_the_previous_default() -> None:
    """Chains built before this change, and any caller that does not stamp a
    priority, must behave exactly as they did."""
    assert resolve_chain_priority({}) is Priority.NORMAL


@pytest.mark.parametrize("priority", list(Priority))
def test_every_priority_round_trips(priority: Priority) -> None:
    assert resolve_chain_priority({CHAIN_PRIORITY_KEY: priority}) is priority


@pytest.mark.parametrize("junk", ["critical", 0, None, object(), ["critical"]])
def test_a_non_priority_value_degrades_rather_than_raising(junk: object) -> None:
    """A chain that cannot determine its lane must still run. Raising here
    would convert a scheduling detail into a failed reply."""
    assert resolve_chain_priority({CHAIN_PRIORITY_KEY: junk}) is Priority.NORMAL


def test_the_key_survives_the_context_filter() -> None:
    """Load-bearing: `_execute_step` narrows context to `spec.context_keys`,
    keeping only those plus keys starting with `_`. A key without the
    underscore would be filtered out for every spec that declares
    context_keys, silently restoring the old behaviour for those steps."""
    assert CHAIN_PRIORITY_KEY.startswith("_")


# ---------------------------------------------------------------------------
# Every LLM-calling handler participates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", _LLM_HANDLERS)
def test_handler_passes_an_inherited_priority(filename: str) -> None:
    """Asserted across all four rather than one, because the defect was
    precisely that a subset of call sites was updated and the rest kept the
    default. A new handler added without this line reintroduces the bug for
    its own step."""
    source = (_HANDLER_DIR / filename).read_text(encoding="utf-8")
    assert "resolve_chain_priority(context)" in source, filename


@pytest.mark.parametrize("filename", _LLM_HANDLERS)
def test_no_handler_calls_complete_without_a_priority(filename: str) -> None:
    """The regression guard. `complete(request)` with no priority is exactly
    the line that caused this."""
    source = (_HANDLER_DIR / filename).read_text(encoding="utf-8")
    assert "complete(request)" not in source, filename


def test_the_handler_list_matches_reality() -> None:
    """Guards the guard: if a fifth LLM-calling handler appears, the two tests
    above would still pass while ignoring it."""
    callers = {
        path.name
        for path in _HANDLER_DIR.glob("*.py")
        if "_llm_client.complete(" in path.read_text(encoding="utf-8")
    }
    assert callers == set(_LLM_HANDLERS)


# ---------------------------------------------------------------------------
# The producer side
# ---------------------------------------------------------------------------

def _chain_entry_sources() -> list[str]:
    from probos.cognitive.cognitive_agent import CognitiveAgent

    return [
        inspect.getsource(CognitiveAgent._execute_sub_task_chain),
        inspect.getsource(CognitiveAgent._execute_chain_with_intent_routing),
    ]


@pytest.mark.parametrize("index", [0, 1])
def test_both_chain_entry_points_stamp_the_priority(index: int) -> None:
    """Two entry points run the same handlers; stamping only one would leave
    whichever path the agent happened to take unfixed."""
    source = _chain_entry_sources()[index]
    assert "CHAIN_PRIORITY_KEY" in source
    assert "Priority.classify(" in source


@pytest.mark.parametrize("index", [0, 1])
def test_chain_priority_is_classified_not_hardcoded(index: int) -> None:
    """The chain must not assert its own lane. Using the shared classifier is
    what guarantees a chain and a single call for the same observation cannot
    land in different lanes — hardcoding CRITICAL here would put every
    proactive think into the interactive lane and starve the Captain, which is
    the same bug pointing the other way."""
    source = _chain_entry_sources()[index]
    assert "[CHAIN_PRIORITY_KEY] = Priority.classify(" in source
    assert "= Priority.CRITICAL" not in source


# ---------------------------------------------------------------------------
# End to end: the classification that matters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("intent", "is_captain", "was_mentioned", "expected"),
    [
        ("direct_message", True, False, Priority.CRITICAL),
        ("direct_message", False, False, Priority.CRITICAL),
        ("ward_room_notification", True, False, Priority.CRITICAL),
        ("ward_room_notification", False, True, Priority.CRITICAL),
        ("proactive_think", False, False, Priority.LOW),
        ("ward_room_notification", False, False, Priority.NORMAL),
    ],
)
def test_the_lane_a_chain_step_would_actually_get(
    intent: str, is_captain: bool, was_mentioned: bool, expected: Priority,
) -> None:
    """Mirrors what the entry points compute and the handlers then read."""
    context = {
        CHAIN_PRIORITY_KEY: Priority.classify(
            intent=intent, is_captain=is_captain, was_mentioned=was_mentioned,
        ),
    }
    assert resolve_chain_priority(context) is expected


def test_proactive_work_does_not_reach_the_interactive_lane() -> None:
    """The reserved lane is only worth having if background work stays out of
    it. This is the half of the fix that protects the Captain."""
    context = {
        CHAIN_PRIORITY_KEY: Priority.classify(intent="proactive_think"),
    }
    assert resolve_chain_priority(context) is not Priority.CRITICAL
