"""AD-1177: the crew's self-description must match the tools they actually hold.

``CognitiveAgent._conversational_agentic_self_description`` (AD-1070) told a crew
agent, in prose, that it held exactly four tools -- ``run_python``,
``search_capabilities``, ``use_skill``, ``delegate_task`` -- the set that existed
when AD-1070 shipped. The loop's assembly (``agentic_dispatch``) has since grown
to eleven groups, so the narration made a false claim about a strictly larger
tool array. That is the BF-701 / BF-706 defect shape: a hand-maintained
declaration of a vocabulary drifting from the vocabulary actually offered.

AD-1177 retires the drift class rather than refreshing the list. The block now
DEFERS to the tool array the model already receives as the authoritative list,
keeps ``search_capabilities`` and ``run_python`` named (each is an *act* the
model must know to perform, not merely a schema to read), frames ``run_python``
as the general-purpose fallback, tells the agent to name plainly what is absent,
and states the chain-of-command boundary in the same breath as the
resourcefulness.

The headline test here is ``test_block_does_not_hardcode_a_partial_tool_enumeration``
-- the drift guard. It fails if a future edit reintroduces a partial
hand-written list.

Fixtures are reused from ``tests/test_ad1070_capability_suppression.py`` (BF-287:
a real ``SystemConfig`` at the config boundary, real registry / descriptor
objects, and the real gate bound onto the unbound-method-with-``SimpleNamespace``
-self, so the full will-run -> render chain is exercised) rather than reinvented.
"""

from __future__ import annotations

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import is_capability_gap
from tests.test_ad1070_capability_suppression import _obs, _self, _self_desc

# Every tool id the conversational agentic path can offer, across all eleven
# groups assembled in ``agentic_dispatch`` (granted / mesh / mcp / exec / skill /
# search / delegate / event-log / oracle / publish / browser). The mesh group is
# dynamic, so the three read intents an agent most reliably receives stand in for
# it. This is the population the prose must not partially enumerate.
_OFFERABLE_TOOL_IDS = frozenset({
    "run_python",
    "use_skill",
    "search_capabilities",
    "delegate_task",
    "event_log_query",
    "oracle_query",
    "publish_finding",
    "browser",
    "web_search",
    "read_page",
    "http_fetch",
})

# The two AD-1177 keeps named ON PURPOSE, because each is an act the model must
# know to perform rather than a schema it can simply read off the tool array.
_DELIBERATELY_NAMED = frozenset({"run_python", "search_capabilities"})


def _block(*, enabled: bool = True, params: dict | None = None) -> str:
    return _self_desc(_self(enabled=enabled), _obs(params=params))


def _defers_to_tool_array(block: str) -> bool:
    """True when the prose points at the model's tool array as the source of
    truth instead of competing with it."""
    return "authoritative list of what you hold" in block and "tool schemas" in block


# ── (1) byte-identical whenever the loop will NOT run (three cases) ─────────
def test_block_empty_when_dm_agentic_flag_off() -> None:
    assert _block(enabled=False) == ""


def test_block_empty_for_group_turn_even_when_flag_on() -> None:
    assert _block(enabled=True, params={"is_group_chat": True}) == ""


def test_block_empty_for_vision_turn_even_when_flag_on() -> None:
    assert _block(enabled=True, params={"vision_messages": [{"type": "image"}]}) == ""


# ── (2) renders on a 1:1 DM with the affirmative disposition ───────────────
def test_block_renders_on_1to1_dm_with_affirmative_disposition() -> None:
    block = _block()
    assert block != ""
    assert "Acting directly this turn" in block
    assert "do the work and report the result" in block


# ── (3) gap-regex-safe via the REAL detector (AD-957 / AD-596) ─────────────
def test_block_is_gap_regex_safe_via_the_real_detector() -> None:
    """The composed prompt must never trip the AD-596 capability-gap detector.

    Asserted through the real ``is_capability_gap`` rather than a re-implemented
    pattern, so the guarantee tracks the live regex if it ever changes.
    """
    block = _block()
    assert block != ""
    assert is_capability_gap(block) is False


def test_block_avoids_the_no_tool_phrasing_trap() -> None:
    """"no tool" matches ``no (?:built-in |native )?(?:...|tool)``, and this AD's
    subject matter invites it. The safe phrasing is "fits none of the other
    tools"."""
    block = _block()
    assert "fits none of the other tools" in block
    assert "no tool" not in block.lower()
    assert "lack" not in block.lower()


# ── (4) THE DRIFT GUARD (headline) ─────────────────────────────────────────
def test_block_does_not_hardcode_a_partial_tool_enumeration() -> None:
    """The property AD-1177 pins: the block either names EVERY offerable tool id
    or defers to the tool array -- never a hand-written subset.

    A partial list is what went stale in AD-1070 (four named of eleven offered)
    and it is the BF-701 / BF-706 defect shape: a hand-maintained declaration
    drifting from the vocabulary actually assembled. This test fails if a future
    edit reintroduces one, in either of the two shapes it can take.
    """
    block = _block()
    assert block != ""

    # (a) The deference statement is present, so the model is pointed at the
    #     authoritative array rather than at prose competing with it.
    assert _defers_to_tool_array(block)

    # (b) No BULLETED line enumerates a tool id. A bullet list is the exact
    #     shape the drifted AD-1070 text had.
    bulleted = [
        line for line in block.splitlines()
        if line.lstrip().startswith(("-", "*", "\u2022"))
    ]
    for line in bulleted:
        for tool_id in _OFFERABLE_TOOL_IDS:
            assert tool_id not in line, (
                f"bulleted tool enumeration reintroduced: {line!r}"
            )

    # (c) The set of tool ids named anywhere in the prose is EITHER the two kept
    #     deliberately OR the complete offerable population. Anything between is
    #     a partial hand-written list and fails here.
    named = {tool_id for tool_id in _OFFERABLE_TOOL_IDS if tool_id in block}
    assert named in (_DELIBERATELY_NAMED, _OFFERABLE_TOOL_IDS), (
        f"partial tool enumeration: named={sorted(named)}; either name every "
        f"offerable tool or defer to the tool array"
    )


def test_block_defers_to_the_tool_array_as_authoritative() -> None:
    block = _block()
    assert _defers_to_tool_array(block)
    # ... and tells the agent not to assume a DIFFERENT set than it was handed.
    #
    # BF-727 (#1179) widened this from one direction to two. AD-1177 wrote only
    # "narrower set than you were given", guarding under-reach. The failure that
    # actually reached the Captain was over-reach: asked what the sandbox could
    # produce, the agent claimed PDFs and matplotlib plots, neither of which is
    # importable. Guarding one direction of a symmetric drift leaves the other
    # open, and BF-726's description test already asserts this same symmetry
    # ("a present library left unnamed is the same drift pointed the other
    # way") — the disposition needed it too.
    assert "narrower or a wider set than you were given" in block


# ── (5) run_python framed as the general-purpose fallback ─────────────────
def test_run_python_framed_as_general_fallback_not_only_file_producer() -> None:
    block = _block()
    assert "run_python is your general-purpose instrument" in block
    assert "fits none of the other tools" in block
    # BF-727 (#1179): this line used to read
    #
    #     # The concrete file-production example is kept -- it works and it is real.
    #     assert ".docx" in block
    #
    # It is UPDATED rather than deleted, because the reason it was wrong is the
    # finding. `.docx` was indeed real — but it was one item in a parenthetical
    # that also promised `.pdf` and `chart`, and neither reportlab nor
    # matplotlib was installed. Pinning the true member of the list made the
    # whole list a contract, so the false members rode along under the
    # protection of a passing test.
    #
    # The irony is local: check (c) thirty lines above forbids a PARTIAL TOOL
    # enumeration in this same prose — "either name every offerable tool or
    # defer to the tool array" — and this assertion then required a partial
    # FORMAT enumeration. Same defect class, same file, opposite verdicts.
    #
    # So the assertion now pins the BEHAVIOUR (run_python produces real,
    # downloadable files) and leaves the format vocabulary to the one surface
    # that derives it from real importability: the BF-726 tool description.
    assert "downloadable file" in block
    for literal in (".docx", ".xlsx", ".pdf", ".pptx", "chart"):
        assert literal not in block.lower(), (
            f"the disposition names {literal!r} again — prose cannot know what "
            "is installed, and this is exactly how the Captain came to be told "
            "the sandbox could author PDFs (BF-727)"
        )


# ── (6) search_capabilities still named as a distinct act ─────────────────
def test_search_capabilities_named_as_a_distinct_act() -> None:
    block = _block()
    assert "search_capabilities" in block
    assert "discovering what is reachable" in block


# ── (7) chain of command stated alongside the resourcefulness ─────────────
def test_chain_of_command_boundary_is_stated() -> None:
    block = _block()
    assert "your orders and your granted authority" in block
    assert "to the Captain for approval" in block
    # Stated in the same breath as the licence to act, not as a separate brake.
    assert "act freely within them" in block


# ── (8) absent resources are named plainly and the work continues ─────────
def test_absent_resource_is_named_plainly_and_work_continues() -> None:
    block = _block()
    assert "plainly what is needed" in block
    assert "carry the task as far as the tools at hand allow" in block


# ── (9) overridable (Open/Closed), matching the sibling hooks ─────────────
class _SilentSelfDescription(CognitiveAgent):
    """A crew agent that opts out of the AD-1177 block entirely."""

    def _conversational_agentic_self_description(self, observation: dict) -> str:
        return ""


def test_block_is_overridable_by_subclass() -> None:
    agent = object.__new__(_SilentSelfDescription)
    agent._runtime = _self(enabled=True)._runtime
    obs = _obs()
    # The gate says the loop WILL run for this self ...
    assert CognitiveAgent._conversational_agentic_will_run(agent, obs) is True
    # ... and the base implementation does render for it ...
    assert CognitiveAgent._conversational_agentic_self_description(agent, obs) != ""
    # ... but the subclass override wins.
    assert agent._conversational_agentic_self_description(obs) == ""
