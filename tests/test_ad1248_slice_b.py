"""AD-1248 slice B: the remaining Captain-visible sinks, and the structural
test that keeps them covered.

The sink list has been wrong in every one of seven review rounds -- 19 routes,
then 22 mixed rows, then 14, 18, 21, 24 -- and one entry turned out to be a
pseudo-sink hiding seven real adapters. A list maintained by hand will keep
being wrong. ``test_no_dm_result_reaches_a_sink_unrendered`` below is what turns
"we remembered every sink" into "a new sink cannot ship un-rendered".
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from types import SimpleNamespace

import pytest

from probos.cognitive.dm.reply_value import (
    DM_REPLY_METADATA_KEY,
    DmReply,
    ToolFailures,
    call_signature,
    failure_key,
)
from probos.types import IntentResult

ROOT = "aaaaaaaaaaaa"
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"


def _failures(name: str = "web_search") -> ToolFailures:
    return ToolFailures.from_mapping(
        {failure_key(ROOT, ROOT, call_signature(name, None)): name}
    )


def _result(body: str = "Here is what I found.") -> IntentResult:
    return IntentResult(
        intent_id="i", agent_id="ezri", success=True, result=body,
        metadata={DM_REPLY_METADATA_KEY: _failures().to_wire()},
    )


# ── B1 / BF-800: the sanity retry replaces, it does not preserve ────────────


def test_a_sanity_retry_drops_the_first_attempts_failures() -> None:
    """A retry is a FRESH ANSWER to the same question. Preserving the first
    attempt's attachments names a tool the retry never called."""
    first = DmReply(body="garbled", tool_failures=_failures("web_search"))
    retry = DmReply(body="clean answer", tool_failures=ToolFailures())
    assert first.replaced_by(retry).tool_failures.is_empty


def test_a_sanity_retry_discloses_its_OWN_failure() -> None:
    """The other direction, and the one that is BF-773 reproducing inside the
    mechanism built to fix BF-773."""
    first = DmReply(body="garbled", tool_failures=_failures("web_search"))
    retry = DmReply(body="clean answer", tool_failures=_failures("read_file"))
    assert first.replaced_by(retry).tool_failures.names() == ("read_file",)


def test_the_retry_site_replaces_rather_than_assigning_through_the_property() -> None:
    """Past the boundary: ``ctx.response_text = ...`` routes through the DD-6
    property, which is ``with_body`` -- preserve. That is the defect."""
    from probos.cognitive.dm import reply_pipeline as rp

    source = inspect.getsource(rp.DmReplyPipeline.step_1_sanity_gate_retry)
    assert "self.ctx.reply = self.ctx.reply.replaced_by(" in source
    assert "DmReply.from_intent_result(retry_resp)" in source


def test_a_failed_retry_retains_the_previous_disclosure() -> None:
    """DD-2: replacement applies only when the fresh run yields a VALID result.
    The empty/error branches must retain, or a failed retry erases a good
    disclosure."""
    from probos.cognitive.dm import reply_pipeline as rp

    source = inspect.getsource(rp.DmReplyPipeline.step_1_sanity_gate_retry)
    replace_at = source.index("self.ctx.reply = self.ctx.reply.replaced_by(")
    guard_at = source.index("if retry_text:")
    assert guard_at < replace_at, "replacement must sit inside the valid-result guard"


# ── B2: the other two DD-2 sites are already correct, and must stay so ──────


def test_the_deliberate_re_roll_is_a_transform_not_a_replacement() -> None:
    """AD-934 re-rolls the PROSE of one run. Its tool failures are still that
    run's, so the attachments ride through -- which is what the DD-6 property
    gives for free."""
    from probos.cognitive.dm import reply_pipeline as rp

    source = inspect.getsource(rp.DmReplyPipeline.step_4j_deliberate_parse)
    assert "replaced_by" not in source, (
        "AD-934 is a transform; replacing here would discard the run's own "
        "failures along with its draft"
    )
    original = DmReply(body="draft", tool_failures=_failures())
    assert original.with_body("refined").tool_failures.names() == ("web_search",)


def test_a_continuation_pass_supersedes_within_the_turn() -> None:
    """AD-1164 reinvokes ``_run_pass``, so each pass folds in through
    ``_accumulate_pass_failures``. Verified as behaviour, not by reading."""
    from probos.cognitive.cognitive_agent import _accumulate_pass_failures

    observation: dict = {}
    _accumulate_pass_failures(observation, SimpleNamespace(tool_failures=_failures()))
    _accumulate_pass_failures(
        observation,
        SimpleNamespace(tool_failures=ToolFailures.from_mapping(
            {failure_key(ROOT, ROOT, call_signature("web_search", None)): ""}
        )),
    )
    assert observation["_dm_tool_failures"].names() == ()


# ── B3: the HXI routes ──────────────────────────────────────────────────────


def test_the_multi_mention_route_composes_once_for_both_sinks() -> None:
    """Sinks: the per-agent HTTP reply AND the main-chat thread append. Both
    read ``PerAgentReply.text``, so composing at the single assignment covers
    both -- and makes it impossible for them to disagree."""
    from probos.routers import chat

    source = inspect.getsource(chat)
    compose = source.index("DmReply.from_intent_result(result).render()")
    append = source.index("body=_reply.text,")
    assert compose < append
    assert "reply_text = (result.result" not in source


def test_the_inline_callsign_route_composes_once_for_both_sinks() -> None:
    """Round 4 found this exact route disclosing on one sink and concealing on
    the other."""
    from probos.routers import chat

    source = inspect.getsource(chat)
    # Both HXI routes in this module compose: multi-mention and inline callsign.
    # Asserting the VARIABLE exists is too weak -- it survives a mutation that
    # keeps the name and drops the composition.
    assert source.count("DmReply.from_intent_result(result).render()") == 2, (
        "each HXI route must compose exactly once: multi-mention and inline"
    )
    assert "body=_inline_body," in source
    assert 'f"{resolved[\'callsign\']}: {_inline_body}"' in source
    assert "str(result.result)" not in source, (
        "no HXI route may emit the raw result"
    )


# ── B4: channels and shell ──────────────────────────────────────────────────


# ── B4: channels are DEFERRED, see BF-802 ───────────────────────────────────
#
# Composing in ``channels/base.py`` was implemented and REVERTED. The reasoning
# -- "all seven send_response overrides transmit what the base returns" -- was
# measurably false, and pre-commit review found three obstacles by execution:
#
#   * Gmail and Teams DISCARD the returned string entirely, so composing in the
#     base reaches neither (GMAIL_SEND_CALLS=[], TEAMS_SEND_CALLS=[]);
#   * WebhookAdapter.send_response is a no-op and has no production caller;
#   * only Discord chunks. A 4,053-char Telegram reply became 4,124 after
#     composition, raised "message is too long", and delivered ZERO messages --
#     i.e. the change would make Telegram strictly WORSE than before.
#
# Also blocked on BF-801 (#1265): channels/ may not import cognitive/.


def test_channel_adapters_do_not_yet_compose() -> None:
    """Pinned so the gap is visible in the suite, not only in an issue."""
    from probos.channels import base

    source = inspect.getsource(base)
    assert "DmReply" not in source, (
        "BF-802 (#1266): if channels start composing, Gmail/Teams wiring and "
        "Telegram chunking must land first, or long replies are lost entirely"
    )


def test_the_channel_adapter_surface_is_pinned_exactly() -> None:
    """An exact count, not a lower bound. ``>=`` passed with 7, 8 AND 9 -- so it
    detected neither a removed adapter nor an added one."""
    import probos.channels as channels_pkg

    overrides: set[str] = set()
    for path in sorted(pathlib.Path(channels_pkg.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                            item.name == "send_response":
                        overrides.add(node.name)

    assert overrides == {
        "ChannelAdapter",        # the abstract base
        "DiscordAdapter",
        "GmailAdapter",
        "MatrixAdapter",
        "SlackAdapter",
        "TeamsAdapter",
        "TelegramAdapter",
        "WebhookAdapter",
    }, (
        f"the adapter surface changed: {sorted(overrides)}. A new adapter needs "
        "a BF-802 wire-limit decision before it can carry a disclosure."
    )


def test_the_shell_session_composes() -> None:
    from probos.experience.commands import session

    source = inspect.getsource(session)
    assert "DmReply.from_intent_result(result).render()" in source
    assert "response_text = str(result.result)" not in source


# ── B5: DD-12 layer 3 — the safeguard that outlives the list ────────────────

#: Exact ``file::function`` fingerprints allowed to consume a direct_message
#: ``IntentResult`` without composing. Function-granular, not file-level: one
#: function in chat.py holds Captain, system, ordinary-agent and DM appends
#: together, so a file exemption would silence the DM path by accident.
_AUDITED_EXEMPTIONS: dict[str, str] = {
    "channels/base.py::_handle_callsign_resolved": (
        "BF-802 (#1266): composing here was implemented and REVERTED. Gmail and "
        "Teams discard the returned string entirely, Webhook's send_response is "
        "a no-op, and only Discord chunks -- a 4,053-char Telegram reply became "
        "4,124 after composition and delivered ZERO messages. Also blocked on "
        "BF-801: channels/ may not import cognitive/."
    ),
    "routers/thread_fanout.py::_fan_one_round": (
        "Group fan-out. AD-1248 excludes it deliberately: the conversational "
        "agentic loop does not run there, so these replies have no tool run "
        "behind them and there is nothing to disclose."
    ),
    "routers/thread_fanout.py::_send_one": "Group fan-out -- see _fan_one_round.",
    "routers/thread_fanout.py::_dispatch_intent": (
        "Group fan-out -- see _fan_one_round. Same exclusion, same reason."
    ),
    "federation/bridge.py::forward_direct_message": (
        "BF-799 (#1263): directed federation is a transport hop, not a sink. "
        "Carriage is deferred pending the layer + frozen-AST decisions."
    ),
    "cognitive/qualification_tests.py::_send_probe": (
        "Surfaced by this test, not by the hand-built register -- which is the "
        "point of it. The probe's reply is scored into a TestResult and never "
        "reaches a human surface, so composing here would add a disclosure to "
        "text nobody reads while telling the scorer a tool failed."
    ),
}


def test_no_dm_result_reaches_a_sink_unrendered() -> None:
    """Every production read of ``<x>.result`` in a module that sends a
    ``direct_message`` must sit in a FUNCTION that also composes a ``DmReply``.

    **What this catches and what it does not**, stated because a safeguard that
    is trusted beyond its reach is worse than none. Pre-commit review broke the
    first version four ways; three are closed here and the fourth is admitted.

    Closed:
      * comments no longer count -- the scan is AST over real nodes, so a
        ``# DmReply`` comment does not immunise anything;
      * a ``DmReply`` mention elsewhere in the module no longer immunises a
        sink -- composition must be in the SAME function as the read;
      * the variable name is no longer hardcoded to ``result`` / ``retry_resp``
        -- any name bound from an ``intent_bus.send``/``dispatch`` in that
        function counts.

    NOT closed: a sink that reads ``.result`` in one function and displays it
    from another still passes. Full provenance needs whole-program dataflow,
    which is what DD-12's NOMINAL boundary (``RenderedDmText``) exists to avoid
    needing. This test is a net, not a proof -- it earned its place by finding
    ``cognitive/qualification_tests.py``, which the hand-built register missed.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        source = path.read_text(encoding="utf-8")
        if "direct_message" not in source:
            continue
        tree = ast.parse(source)
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if f"{rel}::{func.name}" in _AUDITED_EXEMPTIONS:
                continue
            # Scoped to the FUNCTION, not the module: a 12,000-line file that
            # mentions direct_message somewhere would otherwise flag every
            # unrelated dispatch in it (``_execute_compound_replay`` sends
            # ``compound_step_replay`` and was a false positive this way).
            if "direct_message" not in ast.dump(func):
                continue
            sent: set[str] = set()
            for node in ast.walk(func):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Await):
                    call = node.value.value
                    fn = getattr(call, "func", None)
                    if isinstance(fn, ast.Attribute) and fn.attr in {"send", "dispatch"}:
                        for tgt in node.targets:
                            if isinstance(tgt, ast.Name):
                                sent.add(tgt.id)
            if not sent:
                continue
            reads = [
                n for n in ast.walk(func)
                if isinstance(n, ast.Attribute) and n.attr == "result"
                and isinstance(n.value, ast.Name) and n.value.id in sent
            ]
            if not reads:
                continue
            composes = any(
                isinstance(n, ast.Attribute) and n.attr == "from_intent_result"
                for n in ast.walk(func)
            )
            if not composes:
                offenders.append(f"{rel}::{func.name}")

    assert not offenders, (
        "these functions turn a direct_message IntentResult into text without "
        f"composing a DmReply: {offenders}. Either compose, or add an exact "
        "audited exemption with a reason."
    )


def test_every_exemption_names_a_reason_and_a_real_function() -> None:
    """An exemption list that accumulates unaudited entries is how DD-12
    degrades back into the convention it replaced."""
    for key, reason in _AUDITED_EXEMPTIONS.items():
        rel, _, func_name = key.partition("::")
        path = SRC / rel
        assert path.exists(), f"stale exemption: {key}"
        assert func_name, f"exemption must name a function: {key}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert func_name in names, f"stale exemption, no such function: {key}"
        assert len(reason) > 30, f"exemption for {key} has no real reason"


# ── the property that makes all of the above worth doing ────────────────────


@pytest.mark.parametrize(
    "compose",
    [
        lambda r: str(DmReply.from_intent_result(r).render()),
        lambda r: f"Ezri: {DmReply.from_intent_result(r).render()}",
    ],
)
def test_every_composition_form_carries_the_disclosure(compose) -> None:
    assert "web_search" in compose(_result())


def test_a_clean_reply_is_unchanged_by_composition() -> None:
    clean = IntentResult(intent_id="i", agent_id="ezri", success=True, result="All good.")
    assert str(DmReply.from_intent_result(clean).render()) == "All good."


# ── failure-only replies: the disclosure is the ONLY truthful content ────────
#
# I made this mistake in the slice A gaps, the reviewer caught it, I fixed it in
# two places -- and then reintroduced it in three more here. Gating on
# ``result.result`` BEFORE composing turns a run that failed a tool and produced
# no prose into a false "(no response)".


def _failures_only() -> IntentResult:
    return IntentResult(
        intent_id="i", agent_id="ezri", success=True, result="",
        metadata={DM_REPLY_METADATA_KEY: _failures().to_wire()},
    )


def test_an_empty_body_with_failures_renders_the_disclosure() -> None:
    assert "web_search" in DmReply.from_intent_result(_failures_only()).render()


@pytest.mark.parametrize(
    "module_name,func_name",
    [
        ("probos.routers.chat", None),
        ("probos.experience.commands.session", None),
    ],
)
def test_sinks_compose_before_testing_emptiness(module_name, func_name) -> None:
    """Past the boundary: the composition must be guarded on ``is not None``,
    not on ``result.result`` -- the latter discards exactly the failures-only
    case above."""
    import importlib

    source = inspect.getsource(importlib.import_module(module_name))
    assert "if result and result.result else" not in source, (
        "composition is gated on a non-empty body, which drops a failures-only "
        "reply"
    )
    assert "if result is not None" in source
