"""BF-706: the in-page input verbs the agent was never offered.

BF-701 fixed one action refused at the gate. This is the same defect for four
more, and it is my error being corrected: that change was written to avoid
opening `eval_js` and `fill_credential`, and swept up four verbs beside them
without checking how they are governed.

The cost was observed directly. Asked to bold a word in a document, the agent
needed Ctrl+F, had no verb for it, and typed the literal text "Control+f" into
the Captain's document — then "ctrl+f" on the next attempt. It knew exactly what
it needed and said so: *"use Ctrl+F to find Ezri"*. Exactly the BF-701 shape —
the verb exists, it is governed, nobody offered it, so the agent reached for the
nearest thing that was offered.

The rule these tests enforce, so the call is not made by judgement twice:

    A verb belongs on the agent surface when it acts INSIDE the page and
    `classify_action` gives it the same tier treatment as verbs already there.
    Always-tier-3 verbs and host-side effects stay off.
"""

from __future__ import annotations

import inspect

import pytest

from probos.config import BrowserToolConfig
from probos.tools.browser import actions as browser_actions
from probos.tools.browser.tool import _AGENT_ACTION_SET, _AGENT_ACTIONS, BrowserTool


def _tool() -> BrowserTool:
    return BrowserTool(config=BrowserToolConfig(enabled=True))


class _GateProbe(BrowserTool):
    """Session creation is a tripwire, so the gate's decision is what is tested."""

    class Admitted(Exception):
        pass

    async def _get_or_create_session(self, *_a: object, **_k: object):
        raise _GateProbe.Admitted()


async def _admitted(action: str) -> bool:
    tool = _GateProbe(config=BrowserToolConfig(enabled=True))
    try:
        result = await tool.invoke({"action": action}, context={"agent_id": "t"})
    except _GateProbe.Admitted:
        return True
    return not (result.error or "").startswith("unknown browser action")


# ── the headline ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_combo_is_offered() -> None:
    """THE BF-706 regression.

    Without this the agent types "Control+f" as literal text, because key_type
    is the only keyboard verb it has.
    """
    assert "key_combo" in _AGENT_ACTION_SET
    assert await _admitted("key_combo") is True


@pytest.mark.parametrize("verb", ["key_combo", "drag", "mouse_move", "mouse_button"])
@pytest.mark.asyncio
async def test_the_in_page_input_verbs_are_offered(verb: str) -> None:
    assert verb in _AGENT_ACTION_SET
    assert await _admitted(verb) is True


def test_the_shortcut_recipe_is_taught() -> None:
    """The action list alone does not imply that typing a shortcut's NAME is
    the failure mode. It cost a live turn, so it is said explicitly."""
    description = _tool().description
    assert "key_combo" in description
    assert "Ctrl+F" in description
    assert "literal text" in description


def test_key_combo_carries_its_arguments() -> None:
    """Offering a verb without the parameters it requires is the same defect
    one layer down: told it exists, still unable to call it."""
    props = _tool().input_schema["properties"]
    assert "keys" in props
    assert props["keys"]["type"] == "array"
    assert "Control" in props["keys"]["description"]


@pytest.mark.parametrize(
    "param,verb",
    [
        ("keys", "key_combo"),
        ("from_index", "drag"),
        ("to_index", "drag"),
        ("x", "mouse_move"),
        ("y", "mouse_move"),
        ("button", "mouse_button"),
    ],
)
def test_every_new_verb_has_its_parameters(param: str, verb: str) -> None:
    assert verb in _AGENT_ACTION_SET
    assert param in _tool().input_schema["properties"]


# ── the criterion, enforced ───────────────────────────────────────


def _always_tier_3() -> set[str]:
    """Verbs `classify_action` short-circuits to 3 regardless of context."""
    source = inspect.getsource(browser_actions.classify_action)
    return {
        name for name in browser_actions._HANDLERS
        if f'if action == "{name}":\n        return 3' in source
    }


def test_no_always_tier_3_verb_is_offered() -> None:
    """The line that must never move. These bypass contextual tiering entirely,
    so offering one would hand every agent a permanently privileged action."""
    privileged = _always_tier_3()
    assert privileged, "sanity: classify_action must still short-circuit some verbs"
    assert privileged.isdisjoint(_AGENT_ACTION_SET), (
        f"{privileged & _AGENT_ACTION_SET} are always tier 3 and must not be "
        "offered to agents"
    )


@pytest.mark.parametrize(
    "verb", ["eval_js", "fill_credential", "upload_file", "compute_use_click"],
)
def test_the_privileged_four_stay_off(verb: str) -> None:
    assert verb in browser_actions._HANDLERS
    assert verb not in _AGENT_ACTION_SET


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verb", ["eval_js", "fill_credential", "upload_file", "compute_use_click"],
)
async def test_the_privileged_four_are_refused_at_the_gate(verb: str) -> None:
    """Behavioural, not just a set comparison."""
    assert await _admitted(verb) is False


def test_download_stays_off_because_it_writes_to_the_host() -> None:
    """`download` is tier 2 like the offered verbs, and is still excluded.

    Every verb on this surface acts inside the page. `download` writes to the
    host filesystem, which is a categorical difference from "operates on the
    document" and deserves its own decision rather than inheriting one from a
    tier number.
    """
    assert "download" in browser_actions._HANDLERS
    assert "download" not in _AGENT_ACTION_SET


def test_every_offered_verb_has_an_implementation() -> None:
    """The inverse of BF-701: the gate must not admit what nothing implements.

    `_HANDLERS` is not the whole registry — `verify` is dispatched through
    `action_verify`, imported directly by the tool, and the core navigation
    verbs resolve inside `dispatch_action`. So the check is that every offered
    verb resolves SOMEWHERE, which is asserted behaviourally by BF-701's
    "every advertised action is admitted". What this test guards is narrower
    and is the thing BF-706 actually changed: the four newly-offered verbs are
    real registered handlers, not names invented for the schema.
    """
    for verb in ("key_combo", "drag", "mouse_move", "mouse_button"):
        assert verb in browser_actions._HANDLERS, f"{verb} has no handler"


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["key_combo", "drag", "mouse_move", "mouse_button"])
async def test_a_new_verb_fails_on_ITS_ARGUMENTS_not_on_being_unknown(
    verb: str,
) -> None:
    """The distinction that matters.

    Invoked with no arguments, a properly wired verb complains about what it
    needs. An unwired one is rejected as unknown before it can look. BF-701 was
    the second case; this asserts these four are the first.
    """
    tool = _GateProbe(config=BrowserToolConfig(enabled=True))
    try:
        result = await tool.invoke({"action": verb}, context={"agent_id": "t"})
    except _GateProbe.Admitted:
        return  # reached session creation, i.e. fully admitted
    error = result.error or ""
    assert not error.startswith("unknown browser action"), (
        f"{verb} is advertised but the gate rejects it"
    )


def test_schema_gate_and_description_still_share_one_source() -> None:
    tool = _tool()
    assert set(tool.input_schema["properties"]["action"]["enum"]) == _AGENT_ACTION_SET
    assert f"{len(_AGENT_ACTIONS)}-action vocabulary" in tool.description
    for action in _AGENT_ACTIONS:
        assert action in tool.description


def test_the_surface_grew_by_exactly_the_four() -> None:
    """A guard against a future change quietly widening this.

    BF-701 shipped twelve. These four are the deliberate addition; anything
    else appearing here should be a decision someone made on purpose.
    """
    assert len(_AGENT_ACTIONS) == 16
    assert _AGENT_ACTION_SET >= {"key_combo", "drag", "mouse_move", "mouse_button"}
