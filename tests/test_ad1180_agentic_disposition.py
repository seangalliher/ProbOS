"""AD-1180: the agentic disposition must reach every path that hands out tools.

AD-1177 authored a disposition — read your tool array, ``run_python`` is the
general-purpose instrument, be resourceful and retry, act inside your orders —
and wired it into ``CognitiveAgent._conversational_agentic_self_description``,
which is composed into the prompt only on the Captain's 1:1 DM turn. The other
four callers of :meth:`WorkItemAgenticExecutor.run` — the AD-856 task path,
crew children (``crew_executor``), the AD-860 convergence re-run
(``crew_verifier``) and AD-1072 delegation (``delegate_task_tool``) — each pass
the agent's *static* ``instructions`` attribute straight through. All five go
through the same executor and receive the same eleven-group tool array, so
autonomous work happened with a full toolbox and no disposition about using it.

AD-1180 moves the text to a leaf module and composes it at that single choke
point, gated by ``agentic_tools.disposition_enabled`` (default-OFF).

Three properties carry the weight here:

* **Byte-identity of the extraction** — the constant equals the AD-1177 text in
  full. The golden copy below is the guard that this refactor moved prose
  without editing it.
* **Exactly once** — the conversational path already carries the block through
  the AD-1177 hook, so it opts out. That is asserted by COUNTING occurrences,
  never by ``in``: ``in`` cannot see a second copy, and a second copy is the
  entire failure mode of composing at a shared seam.
* **Default-OFF byte-identity** — proved with a recording loop stub against the
  real executor, for ``compose_disposition`` both True and False, rather than by
  reading the branch.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from types import SimpleNamespace
from typing import Any

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.agentic_disposition import AGENTIC_DISPOSITION
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import is_capability_gap
from probos.config import AgenticToolsConfig, DmAgenticConfig, SystemConfig
from tests.test_ad1070_capability_suppression import _obs, _self, _self_desc


# ── the golden copy: the AD-1177 text as amended by BF-727 ─────────────────
#
# Held here rather than derived from the source, because the source is what this
# AD moved. A derived copy would agree with any edit; this one only agrees with
# the text we deliberately settled on.
#
# AMENDED by BF-727 (#1179) — recorded, not silently rewritten, because this
# test's original claim ("the extraction moved prose, it did not edit it") was
# true of AD-1180 and is no longer the whole story. Two clauses changed:
#
#   1. "...produce a real downloadable file (a .docx, .xlsx, .pdf, chart, or
#      archive) the Captain can open..."
#      → the parenthetical is GONE. It was a second, hand-maintained declaration
#        of the sandbox's artifact surface, and it went stale exactly as AD-1177
#        predicted for the tool list it retired three lines above. BF-726 had
#        already made the tool description derive from real importability; this
#        prose still promised .pdf and charts, and the vessel (restarted WITH
#        BF-726 in place) told the Captain it could produce PDFs and matplotlib
#        plots. Neither library is importable. The prose now points at the
#        schema instead of racing it.
#
#   2. "...instead of assuming a narrower set than you were given..."
#      → "...instead of assuming either a narrower or a wider set...". AD-1177
#        guarded one direction; the observed failure was the other one.
#
# The remaining ~85% is AD-1177 verbatim and must stay that way.
_GOLDEN_TEXT = (
    "\n\nActing directly this turn: you have a working loop that runs real "
    "tools before you reply, so do the work and report the result rather "
    "than only describing how it might be done. The tool schemas you were "
    "handed this turn are the authoritative list of what you hold -- read "
    "them and reach for whichever one fits the task, instead of assuming "
    "either a narrower or a wider set than you were given. When you are "
    "unsure what the ship offers right now, search_capabilities is itself a "
    "move worth making: discovering what is reachable grounds your reply in "
    "what is truly there this turn. run_python is your general-purpose "
    "instrument -- when a task fits none of the other tools, write and run "
    "Python to carry it: compute, transform data, drive a library, or "
    "produce a real downloadable file the Captain can open. Its schema "
    "names the libraries actually present this turn, so let that decide what "
    "you offer to build rather than what you would expect to be installed, "
    "then hand back the result. Be resourceful: take the "
    "direct route first, and when an attempt falls short, adjust it and go "
    "again before settling for an explanation. If something you need is "
    "missing -- a library, a file, a detail only the Captain holds -- say "
    "plainly what is needed and why, then carry the task as far as the "
    "tools at hand allow. All of this sits inside your orders and your "
    "granted authority: act freely within them, and bring anything that "
    "would exceed them to the Captain for approval rather than routing "
    "around it. Prefer finishing the task within this turn; describe an "
    "approach only when the Captain asks for the plan itself."
)

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
_INSTRUCTIONS = "You are Ezri, ship's counselor. Standing orders: be kind."


# ── harness ────────────────────────────────────────────────────────────────
class _RecordingLoop:
    """Records the ``system_prompt`` that actually reaches the loop.

    Constructor absorbs every behaviour kwarg the executor threads (AD-1146
    structured_tool_messages, AD-1147 parallel_tool_calls_*, AD-1148
    tool_result_*, AD-1142 compaction) — this stub asserts on ``run``, so
    pinning a constructor signature would only make it break on the next
    additive option (the BF-678 class).
    """

    prompts: list[str] = []

    def __init__(self, **_loop_kwargs: Any) -> None:
        pass

    async def run(self, *, system_prompt, user_message, tools, context):
        _RecordingLoop.prompts.append(system_prompt)
        return SimpleNamespace(
            final_text="done",
            stopped_reason="complete",
            tool_calls=[],
            total_tokens=0,
        )


def _arm_loop(monkeypatch) -> None:
    _RecordingLoop.prompts = []
    monkeypatch.setattr(
        "probos.cognitive.swe_harness.agentic_loop.AgenticLoop", _RecordingLoop,
    )


def _runtime(*, disposition_enabled: bool, dm_agentic: bool = False) -> SimpleNamespace:
    """A real ``SystemConfig`` at the config boundary (BF-287) with only the
    AD-1180 flag moved. Every other runtime service is absent, so tool assembly
    stays empty and the prompt is the only variable under test."""
    return SimpleNamespace(
        config=SystemConfig(
            agentic_tools=AgenticToolsConfig(
                disposition_enabled=disposition_enabled
            ),
            dm_agentic=DmAgenticConfig(enabled=dm_agentic),
        ),
    )


async def _run(*, disposition_enabled: bool, **kwargs: Any) -> str:
    """Drive the REAL executor and return the system prompt the loop received."""
    executor = WorkItemAgenticExecutor(llm_client=object())
    await executor.run(
        runtime=_runtime(disposition_enabled=disposition_enabled), **kwargs
    )
    assert len(_RecordingLoop.prompts) == 1, "expected exactly one loop run"
    return _RecordingLoop.prompts[-1]


def _base_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "agent_id": "agentezri",
        "instructions": _INSTRUCTIONS,
        "task_text": "summarise the sensor logs",
    }
    kwargs.update(overrides)
    return kwargs


# ── (1) the extraction moved prose; later edits are deliberate ─────────────
def test_the_constant_is_byte_identical_to_the_golden_text() -> None:
    """Full-string equality, not a substring match.

    A substring assertion passes on a reworded block that merely retains a
    phrase. AD-1177 settled this wording and verified it against the real gap
    regex; AD-1180 widened its reach without touching it; BF-727 made the two
    corrections recorded above the golden copy. Anything further has to update
    this constant on purpose.
    """
    assert AGENTIC_DISPOSITION == _GOLDEN_TEXT
    assert len(AGENTIC_DISPOSITION) == 1606


def test_the_conversational_hook_returns_the_shared_constant() -> None:
    """Identity, so the hook cannot drift into a near-copy of the constant."""
    assert _self_desc(_self(enabled=True), _obs()) is AGENTIC_DISPOSITION


def test_the_hook_still_returns_empty_when_the_loop_will_not_run() -> None:
    """The AD-1070 default-OFF guarantee survives the extraction."""
    assert _self_desc(_self(enabled=False), _obs()) == ""
    assert _self_desc(_self(enabled=True), _obs(params={"is_group_chat": True})) == ""


def test_the_constant_is_gap_regex_safe_via_the_real_detector() -> None:
    """Through the real ``is_capability_gap``, never a re-implemented pattern.

    The block now reaches four more paths, so a phrase matching
    ``_CAPABILITY_GAP_RE`` would fire the AD-596 capability-gap driver on text
    that is affirming capability rather than reporting its absence.
    """
    assert is_capability_gap(AGENTIC_DISPOSITION) is False


def test_the_leaf_module_imports_nothing_from_probos() -> None:
    """The cycle-safety property that justifies a third module.

    ``cognitive_agent`` imports ``WorkItemAgenticExecutor`` only INSIDE methods
    to avoid a cycle with ``agentic_dispatch``. Both now import this module at
    module level, so it must stay a leaf.
    """
    tree = ast.parse((_SRC / "cognitive" / "agentic_disposition.py").read_text("utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert [m for m in imported if m.startswith("probos")] == []
    assert imported == ["__future__"]


# ── (2) default-OFF is byte-identical, both ways ───────────────────────────
async def test_default_off_is_byte_identical_when_composing_is_requested(
    monkeypatch,
) -> None:
    """The operator-facing guarantee: the flag, not the kwarg, keeps this inert."""
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=False, **_base_kwargs(compose_disposition=True)
    )
    assert prompt == _INSTRUCTIONS


async def test_default_off_is_byte_identical_when_composing_is_declined(
    monkeypatch,
) -> None:
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=False, **_base_kwargs(compose_disposition=False)
    )
    assert prompt == _INSTRUCTIONS


async def test_default_off_preserves_the_empty_instructions_coercion(
    monkeypatch,
) -> None:
    """``instructions or ""`` was the pre-AD-1180 expression; a falsy value must
    still reach the loop as the empty string rather than ``None``."""
    _arm_loop(monkeypatch)
    prompt = await _run(disposition_enabled=False, **_base_kwargs(instructions=""))
    assert prompt == ""


# ── (3) armed: composes once, and leaves the orders intact ─────────────────
async def test_armed_and_composing_appends_the_disposition_exactly_once(
    monkeypatch,
) -> None:
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=True, **_base_kwargs(compose_disposition=True)
    )
    assert prompt.count(AGENTIC_DISPOSITION) == 1
    # The agent's own orders survive in full and stay in front — the disposition
    # is an operating note on top of the identity, not a replacement for it.
    assert _INSTRUCTIONS in prompt
    assert prompt.startswith(_INSTRUCTIONS)
    assert prompt == _INSTRUCTIONS + AGENTIC_DISPOSITION


async def test_armed_but_declining_leaves_the_prompt_untouched(monkeypatch) -> None:
    """The conversational path's guarantee, isolated."""
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=True, **_base_kwargs(compose_disposition=False)
    )
    assert prompt == _INSTRUCTIONS
    assert prompt.count(AGENTIC_DISPOSITION) == 0


# ── (4) THE HEADLINE: no double injection on the conversational path ───────
async def test_the_conversational_path_carries_the_disposition_exactly_once(
    monkeypatch,
) -> None:
    """Drive the real ``_maybe_run_conversational_agentic`` with the flag armed.

    Its ``system_prompt`` is the COMPOSED conversational prompt, which already
    carries the block via the AD-1177 hook (``composed += _agentic_self_desc``
    in ``_decide_via_llm``) — so the executor must not add a second copy.
    Counted, not tested with ``in``: ``in`` is true for one copy and for two,
    and two is precisely what composing at a shared seam risks.
    """
    _arm_loop(monkeypatch)
    runtime = _runtime(disposition_enabled=True, dm_agentic=True)
    agent = SimpleNamespace(
        id="agentezri",
        callsign="Ezri",
        agent_type="counselor",
        _runtime=runtime,
        _llm_client=object(),
        _promoted_turn_tasks=set(),
    )
    agent._conversational_agentic_will_run = (
        lambda obs: CognitiveAgent._conversational_agentic_will_run(agent, obs)
    )
    # Exactly what ``_decide_via_llm`` hands over: the composed prompt with the
    # AD-1177 block already appended.
    composed = _INSTRUCTIONS + AGENTIC_DISPOSITION

    text = await CognitiveAgent._maybe_run_conversational_agentic(
        agent,
        {"intent": "direct_message", "params": {}},
        system_prompt=composed,
        user_message="make me a doc",
    )

    assert text == "done", "the loop honest-degraded; the prompt proves nothing"
    assert len(_RecordingLoop.prompts) == 1
    assert _RecordingLoop.prompts[0].count(AGENTIC_DISPOSITION) == 1
    assert _RecordingLoop.prompts[0] == composed


async def test_the_double_injection_this_guards_is_detectable(monkeypatch) -> None:
    """Counterfactual: prove the assertion above can actually fail.

    A test that only ever sees one copy cannot show it would notice two. Feeding
    the already-composed prompt through with ``compose_disposition=True`` — what
    the conversational call site would do if it forgot to opt out — must produce
    a count of 2.
    """
    _arm_loop(monkeypatch)
    composed = _INSTRUCTIONS + AGENTIC_DISPOSITION
    prompt = await _run(
        disposition_enabled=True,
        **_base_kwargs(instructions=composed, compose_disposition=True),
    )
    assert prompt.count(AGENTIC_DISPOSITION) == 2


# ── (5) each static-instruction path composes when armed ───────────────────
async def test_the_crew_child_kwargs_shape_composes_when_armed(monkeypatch) -> None:
    """``crew_executor._run_child_to_completion`` builds exactly these kwargs.

    A full crew boot is not required to prove the seam: the executor is the
    choke point, and this is the kwarg shape that reaches it.
    """
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=True,
        **_base_kwargs(
            thread_id="thread-crew",
            extra_context={
                "_crew_session_id": "parent-1",
                "_crew_work_item_id": "child-1",
            },
        ),
    )
    assert prompt.count(AGENTIC_DISPOSITION) == 1
    assert prompt == _INSTRUCTIONS + AGENTIC_DISPOSITION


async def test_the_verifier_rerun_kwargs_shape_composes_when_armed(
    monkeypatch,
) -> None:
    """``SubtaskVerifier.converge_for_session`` passes only four kwargs."""
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=True,
        **_base_kwargs(task_text="redo it\n\nCRITIQUE:\nthin evidence"),
    )
    assert prompt.count(AGENTIC_DISPOSITION) == 1
    assert prompt == _INSTRUCTIONS + AGENTIC_DISPOSITION


async def test_the_delegation_kwargs_shape_composes_when_armed(monkeypatch) -> None:
    """``DelegateTaskTool`` threads the depth guard through ``extra_context``."""
    _arm_loop(monkeypatch)
    prompt = await _run(
        disposition_enabled=True,
        **_base_kwargs(
            thread_id="thread-dm",
            max_iterations=5,
            tier="standard",
            extra_context={"_delegation_depth": 1},
        ),
    )
    assert prompt.count(AGENTIC_DISPOSITION) == 1
    assert prompt == _INSTRUCTIONS + AGENTIC_DISPOSITION


async def test_the_task_path_kwargs_shape_composes_when_armed(monkeypatch) -> None:
    """The AD-856 task path passes no ``compose_disposition`` at all, so it
    inherits the True default — which is the point of that default."""
    _arm_loop(monkeypatch)
    prompt = await _run(disposition_enabled=True, **_base_kwargs())
    assert prompt.count(AGENTIC_DISPOSITION) == 1
    assert prompt == _INSTRUCTIONS + AGENTIC_DISPOSITION


# ── (6) the default is True, and exactly one caller opts out ───────────────
def test_compose_disposition_defaults_to_true() -> None:
    """A FUTURE call site must inherit the disposition rather than remember it.

    AD-1177 reached one of five paths because each caller passed a static
    ``instructions`` attribute and nothing composed anything; a default of False
    would reproduce that the next time someone adds a caller. Inertness for
    operators comes from the config gate, not from this kwarg.
    """
    param = inspect.signature(WorkItemAgenticExecutor.run).parameters[
        "compose_disposition"
    ]
    assert param.default is True
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


def test_exactly_one_call_site_opts_out_and_it_is_the_conversational_one() -> None:
    """The 'exactly one copy on every path' invariant, pinned at the call sites.

    Only the conversational path may decline, because only it receives an
    already-composed prompt. A second opt-out anywhere in ``src/probos`` means a
    path silently lost the disposition again — the defect this AD exists to fix.
    """
    opt_outs: list[tuple[str, int]] = []
    for path in _SRC.rglob("*.py"):
        text = path.read_text("utf-8")
        if "compose_disposition" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "compose_disposition":
                    continue
                assert isinstance(kw.value, ast.Constant), (
                    f"{path.name}:{node.lineno} passes a non-literal "
                    "compose_disposition; the opt-out must be readable"
                )
                if kw.value.value is False:
                    opt_outs.append((path.name, node.lineno))

    assert len(opt_outs) == 1, f"expected exactly one opt-out, found {opt_outs}"
    assert opt_outs[0][0] == "cognitive_agent.py"
