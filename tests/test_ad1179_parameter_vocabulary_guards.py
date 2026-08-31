"""AD-1179 (slice 2): no tool silently ignores a parameter it never declared.

Slice 1 closed the drift at the *enum* layer — a vocabulary restated beside its
own executable gate. This is the other half of the same class, one level up: a
tool declares a set of parameters in ``input_schema`` and then its ``invoke``
reads only the keys it happens to recognise, dropping the rest without a word.

That is not a cosmetic gap. Measured during slice 1 on ``find_mcp_tool``:
removing an undeclared ``concept`` alias made a ``concept``-only call search for
``""`` and return an **empty match list inside a SUCCESS envelope** —
indistinguishable from "the mesh has no such tool". The caller reads a wrong
answer as a true one, and nothing anywhere records that a question was asked in
a spelling the tool did not understand. An error is correctable. A confident
wrong answer is not.

The gate is :func:`probos.tools.protocol.refuse_undeclared_params`, which reads
the accepted set from the tool's **own** ``input_schema`` rather than from a
second hand-written list beside it. A restated copy would recreate exactly the
drift this AD exists to remove.

What each guard here catches, and what it does not:

* **G4a — a tool that silently accepts an unknown key** — caught, behaviourally,
  by invoking the real tool through its real ``invoke``. Covers every registered
  tool except ``browser`` (see ``DELEGATING`` below).
* **G4b — a refusal that does not say which key was wrong** — caught for the
  nineteen tools using the derived gate. The three tools listed in
  ``PRE_EXISTING_STRICT`` deliberately answer with a content-free governance
  code and are excluded *by name*, with their code asserted exactly instead.
* **G4c — the gate firing on a legitimate call** — caught. A guard that only
  proves refusal would be satisfied by a tool that refuses everything.
* **G5 — the three hand-written ``_ALLOWED_KEYS`` frozensets drifting from the
  schema beside them** — caught. Slice 2 did not rewrite those validators, so
  the restatement is pinned rather than removed.

Not covered, stated rather than rounded up: a tool whose schema declares a
parameter nothing reads. That direction is G3's in the slice 1 guard file, and
it is only checked for the tools G3 enumerates.

Every guard carries a negative control driven through the *same* assertion the
parametrized cases use, so a control passing on a broken tree is impossible.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from probos.tools.protocol import (
    ToolResult,
    declared_params,
    refuse_undeclared_params,
)
from tests.test_ad1179_tool_schema_golden import (
    EXPECTED_TOOL_IDS,
    build_pinned_instances,
)

# The key no schema declares. Long and self-identifying so a failure message
# says where it came from.
UNKNOWN_KEY = "__ad1179_undeclared_probe__"

# ``browser`` dispatches to sixteen action handlers, and those handlers read
# keys the schema does not declare — ``selector_or_url``, ``script``,
# ``credential_ref``, ``file_path``, ``_runtime`` — while ``invoke`` itself
# injects ``agent_id`` into the forwarded dict for ``fill_credential``. It is a
# genuine pass-through, so strictness there would break working verbs. Named
# here rather than filtered silently, matching ``G3_DELEGATED_ADMISSION``.
DELEGATING: frozenset[str] = frozenset({"browser"})

# Tools that already refused an unknown key before slice 2, through their own
# module-level ``_ALLOWED_KEYS`` frozenset. They are still required to refuse
# (G4a covers them) but they answer with a content-free code by design, so the
# "name the key" assertion does not apply and G5 pins their frozenset instead.
PRE_EXISTING_STRICT: frozenset[str] = frozenset({
    "event_log_query",
    "oracle_query",
    "publish_finding",
})

# Everything the AD-1179 slice-2 derived gate was installed on.
DERIVED_GATE: frozenset[str] = EXPECTED_TOOL_IDS - DELEGATING - PRE_EXISTING_STRICT

# Every tool required to refuse an unknown key, however it words the refusal.
MUST_REFUSE: frozenset[str] = DERIVED_GATE | PRE_EXISTING_STRICT

# ``event_log_query`` checks authorization BEFORE it looks at the parameters, so
# an empty context makes it answer ``event_log_query_denied`` and the probe would
# pass without ever reaching the key check — a control that proves nothing. This
# context clears that gate so the refusal under test is the parameter one.
_CONTEXTS: dict[str, dict[str, Any]] = {
    "event_log_query": {
        "agent_id": "guard-agent",
        "agent_department": "engineering",
        "agent_rank": "commander",
        "permission": "read",
    },
}

# The exact refusal ``PRE_EXISTING_STRICT`` tools produce for an unknown key.
# Asserted verbatim so "it returned some error" cannot stand in for "it refused
# because of the key" — those two are indistinguishable otherwise, and one of
# them is a vacuous pass.
_STRICT_REFUSALS: dict[str, str] = {
    "event_log_query": "event_log_query_invalid:unknown_parameter",
    "oracle_query": "oracle_query_invalid:parameter",
    "publish_finding": "publish_finding_invalid:parameter",
}


def _tools_by_id() -> dict[str, Any]:
    return {tool.tool_id: tool for tool in build_pinned_instances()}


def _context_for(tool_id: str) -> dict[str, Any]:
    return dict(_CONTEXTS.get(tool_id, {"agent_id": "guard-agent"}))


async def assert_refuses_unknown_key(tool: Any, context: dict[str, Any]) -> str:
    """The single assertion every G4a case and its negative control run.

    Returns the refusal text so a caller can make a stronger claim about it.
    """
    result = await tool.invoke({UNKNOWN_KEY: "x"}, context)
    assert isinstance(result, ToolResult), (
        f"{tool.tool_id}: invoke returned {type(result).__name__}, not a "
        f"ToolResult — the refusal must stay inside the tool contract"
    )
    assert result.error is not None, (
        f"{tool.tool_id}: accepted an undeclared parameter {UNKNOWN_KEY!r} and "
        f"answered successfully with output={result.output!r}. A key the schema "
        f"never named must be refused, not dropped: dropping it returns a "
        f"confident answer to a question the tool did not understand"
    )
    return result.error


# ══ G4a — every non-delegating tool refuses an unknown key ════════


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", sorted(MUST_REFUSE))
async def test_g4a_an_undeclared_parameter_is_refused(tool_id: str) -> None:
    await assert_refuses_unknown_key(_tools_by_id()[tool_id], _context_for(tool_id))


@pytest.mark.asyncio
async def test_g4a_negative_control_flags_a_tool_that_silently_ignores() -> None:
    """The pre-slice-2 shape, driven through the same assertion.

    If this does not raise, ``assert_refuses_unknown_key`` cannot fail and every
    parametrized case above is decorative.
    """

    class _SilentlyIgnoringTool:
        tool_id = "silent"
        input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

        async def invoke(self, params, context=None):  # noqa: ANN001, ANN202
            return ToolResult(output={"matches": []})

    with pytest.raises(AssertionError, match="accepted an undeclared parameter"):
        await assert_refuses_unknown_key(_SilentlyIgnoringTool(), {})


@pytest.mark.asyncio
async def test_g4a_negative_control_passes_a_tool_that_refuses() -> None:
    """And must not fail a compliant one, or it is an unconditional failure."""

    class _StrictTool:
        tool_id = "strict"
        input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

        async def invoke(self, params, context=None):  # noqa: ANN001, ANN202
            return refuse_undeclared_params(self, params) or ToolResult(output={})

    error = await assert_refuses_unknown_key(_StrictTool(), {})
    assert UNKNOWN_KEY in error


def test_g4a_covers_every_registered_tool_exactly_once() -> None:
    """Premise assertion. A coverage set derived from what happens to be
    constructible shrinks silently; this one is asserted."""
    assert MUST_REFUSE | DELEGATING == EXPECTED_TOOL_IDS
    assert not (DERIVED_GATE & PRE_EXISTING_STRICT)
    assert not (MUST_REFUSE & DELEGATING)
    assert set(_tools_by_id()) == EXPECTED_TOOL_IDS


def test_g4a_the_delegating_exclusion_is_earned_not_assumed() -> None:
    """``browser`` is excluded because its handlers really do read keys the
    schema does not declare. If that stops being true it must lose the
    exemption, so the claim is measured rather than asserted in a comment."""
    from probos.tools.browser import actions as browser_actions

    tool = _tools_by_id()["browser"]
    schema_keys = set(declared_params(tool))
    handler_source = inspect.getsource(browser_actions)
    beyond = {
        key
        for key in ("selector_or_url", "script", "credential_ref", "file_path")
        if f'params.get("{key}")' in handler_source
    }
    assert beyond - schema_keys, (
        "no browser handler reads a key outside the schema any more, so the "
        "delegating exemption is no longer earned and browser should join "
        "MUST_REFUSE"
    )


# ══ G4b — the refusal names the offending key ═════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", sorted(DERIVED_GATE))
async def test_g4b_the_refusal_names_the_offending_key(tool_id: str) -> None:
    """A refusal that does not say WHICH key was wrong leaves the caller to
    guess, which for an LLM means retrying the same misspelling."""
    tool = _tools_by_id()[tool_id]
    error = await assert_refuses_unknown_key(tool, _context_for(tool_id))
    assert UNKNOWN_KEY in error, (
        f"{tool_id}: refused, but the message {error!r} does not name the key"
    )
    assert tool_id in error, f"{tool_id}: refusal does not identify the tool"
    for name in declared_params(tool):
        assert name in error, (
            f"{tool_id}: refusal does not offer the declared alternative {name!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", sorted(PRE_EXISTING_STRICT))
async def test_g4b_pre_existing_strict_tools_use_their_governance_code(
    tool_id: str,
) -> None:
    """The three excluded from the naming rule answer with a content-free code.
    Pinned exactly: "it returned some error" and "it refused because of the key"
    are otherwise the same observation, and one of them is a vacuous pass."""
    error = await assert_refuses_unknown_key(
        _tools_by_id()[tool_id], _context_for(tool_id)
    )
    assert error == _STRICT_REFUSALS[tool_id]


# ══ G4c — the gate does not fire on a declared call ═══════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_id", sorted(MUST_REFUSE))
async def test_g4c_declared_keys_do_not_trip_the_gate(tool_id: str) -> None:
    """Every declared key, passed together, must reach the tool's own logic.

    Values are empty on purpose: each tool then refuses on its OWN required-field
    check before doing any work, so this exercises the admission gate without
    running a command, writing a file, or opening a browser.
    """
    tool = _tools_by_id()[tool_id]
    params = {name: "" for name in declared_params(tool)}
    result = await tool.invoke(params, _context_for(tool_id))
    assert isinstance(result, ToolResult)
    error = result.error or ""
    assert "unknown parameter" not in error.lower(), (
        f"{tool_id}: refused its own declared parameters {sorted(params)} — the "
        f"gate is over-refusing, which is the same drift in the other direction"
    )
    assert error != _STRICT_REFUSALS.get(tool_id), (
        f"{tool_id}: answered a fully-declared call with the unknown-parameter "
        f"code, so the G4a probe above proves nothing"
    )


# ══ G5 — the hand-written _ALLOWED_KEYS must match the schema ═════


@pytest.mark.parametrize("tool_id", sorted(PRE_EXISTING_STRICT))
def test_g5_hand_written_allowed_keys_match_the_schema_beside_them(
    tool_id: str,
) -> None:
    """Slice 2 left these three validators alone — ``event_log_query`` gates in a
    module function with no instance to read a schema from, and rewriting the
    other two would change governed refusal paths this slice did not need. The
    restatement therefore stays, and this pins it so it cannot drift."""
    tool = _tools_by_id()[tool_id]
    module = inspect.getmodule(type(tool))
    allowed = getattr(module, "_ALLOWED_KEYS", None)
    assert allowed is not None, f"{tool_id}: module has no _ALLOWED_KEYS"
    assert set(allowed) == set(declared_params(tool)), (
        f"{tool_id}: _ALLOWED_KEYS and input_schema disagree — "
        f"only in _ALLOWED_KEYS: {sorted(set(allowed) - set(declared_params(tool)))}, "
        f"only in the schema: {sorted(set(declared_params(tool)) - set(allowed))}"
    )


# ══ the gate itself ═══════════════════════════════════════════════


class _Probe:
    tool_id = "probe"

    def __init__(self, schema: Any) -> None:
        self.input_schema = schema


def test_declared_params_reads_the_schema_in_order() -> None:
    probe = _Probe({"type": "object", "properties": {"b": {}, "a": {}}})
    assert declared_params(probe) == ("b", "a")


def test_declared_params_is_empty_for_a_schema_without_properties() -> None:
    assert declared_params(_Probe({"type": "object"})) == ()
    assert declared_params(_Probe(None)) == ()
    assert declared_params(_Probe({"properties": ["not", "a", "dict"]})) == ()


def test_refuse_undeclared_params_passes_a_clean_call() -> None:
    probe = _Probe({"type": "object", "properties": {"query": {}}})
    assert refuse_undeclared_params(probe, {"query": "x"}) is None
    assert refuse_undeclared_params(probe, {}) is None
    assert refuse_undeclared_params(probe, None) is None
    assert refuse_undeclared_params(probe, "not a dict") is None


def test_refuse_undeclared_params_lists_every_unknown_key_sorted() -> None:
    probe = _Probe({"type": "object", "properties": {"query": {}}})
    refusal = refuse_undeclared_params(probe, {"zeta": 1, "query": "x", "alpha": 2})
    assert refusal is not None and refusal.output is None
    assert "alpha, zeta" in refusal.error
    assert "query" in refusal.error


def test_refuse_undeclared_params_survives_a_non_string_key() -> None:
    """A key that is not a string still has to be reportable. Sorting the raw
    keys would raise TypeError on a mixed dict and turn a refusal into a crash."""
    probe = _Probe({"type": "object", "properties": {"query": {}}})
    refusal = refuse_undeclared_params(probe, {1: "a", "b": "c"})
    assert refusal is not None
    assert "1" in refusal.error and "b" in refusal.error


def test_refuse_undeclared_params_says_so_when_nothing_is_accepted() -> None:
    """``system_self_model`` declares no parameters at all; the refusal must not
    read as an empty list of alternatives."""
    refusal = refuse_undeclared_params(_Probe({"type": "object"}), {"x": 1})
    assert refusal is not None
    assert "no parameters" in refusal.error
