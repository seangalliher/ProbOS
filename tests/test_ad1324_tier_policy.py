"""AD-1324: the pure tier policy -- directive parsing, floor, state machine."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.swe_harness.tool_call import TextBlock
from probos.cognitive.tier_floor_ask import tier_floor_rationale
from probos.cognitive.tier_policy import (
    MAX_DIRECTIVE_CHARS,
    EligibilityVerdict,
    TierChoiceController,
    is_floor_bound_step,
    split_directive,
    stakes_floor_tier,
    tier_choice_armed,
)
from probos.types import LLMResponse

FLOOR = {"high": "standard", "severe": "deep"}


def _resp(content: str = "", blocks: list[Any] | None = None) -> LLMResponse:
    return LLMResponse(content=content, tokens_used=3, content_blocks=blocks or [])


def _line(tier: str = "deep", reason: str = "hard_step") -> str:
    return f'@@next_tier {{"tier":"{tier}","reason":"{reason}"}}'


def test_valid_directive_last_line_is_stripped_and_parsed() -> None:
    cleaned, parse = split_directive(_resp(f"Reading now.\n{_line()}"))
    assert cleaned.content == "Reading now."
    assert parse.status == "valid" and parse.directive.tier == "deep"


def test_absent_directive_returns_same_object() -> None:
    response = _resp("just text")
    cleaned, parse = split_directive(response)
    assert cleaned is response and parse.status == "absent"


@pytest.mark.parametrize("text,detail", [
    ('@@next_tier {"tier":"deep"', "malformed"),
    ('@@next_tier {"tier":"deep","reason":"hard_step","x":1}', "bad_keys"),
    ('@@next_tier {"tier":"gigantic","reason":"hard_step"}', "unknown_tier"),
    ('@@next_tier {"tier":"deep","reason":"because I said so"}', "bad_reason"),
    ('@@next_tier {"tier":"vision","reason":"hard_step"}', "special_tier"),
    ('@@next_tier {"tier":"vision_fast","reason":"hard_step"}', "special_tier"),
    ('@@next_tier {"tier":"compute_use","reason":"hard_step"}', "special_tier"),
    ('@@next_tier {"tier":"image_gen","reason":"hard_step"}', "special_tier"),
    ('@@next_tier {"tier":1,"reason":"hard_step"}', "bad_types"),
    ('@@next_tierX {"tier":"deep","reason":"hard_step"}', "malformed"),
    ("@@next_tier " + "x" * MAX_DIRECTIVE_CHARS, "too_long"),
])
def test_invalid_directive_is_stripped_and_rejected(text: str, detail: str) -> None:
    cleaned, parse = split_directive(_resp(f"body\n{text}"))
    assert "@@next_tier" not in cleaned.content
    assert parse.status == "invalid" and parse.detail == detail


def test_duplicate_directive_is_invalid_and_all_stripped() -> None:
    cleaned, parse = split_directive(_resp(f"a\n{_line()}\nb\n{_line('fast')}"))
    assert "@@next_tier" not in cleaned.content
    assert parse.status == "invalid" and parse.detail == "duplicate"


def test_directive_not_last_line_is_invalid() -> None:
    cleaned, parse = split_directive(_resp(f"{_line()}\nand more text"))
    assert cleaned.content == "and more text"
    assert parse.detail == "not_last_line"


def test_directive_in_text_block_is_stripped_from_blocks() -> None:
    blocks = [TextBlock(text=f"working\n{_line('standard', 'easy_step')}")]
    cleaned, parse = split_directive(_resp("", blocks))
    assert cleaned.content_blocks[0].text == "working"
    assert parse.status == "valid" and parse.directive.tier == "standard"


def test_split_does_not_mutate_the_original() -> None:
    response = _resp(f"x\n{_line()}")
    split_directive(response)
    assert "@@next_tier" in response.content


def test_stakes_floor_tier_mapping() -> None:
    assert stakes_floor_tier("high", FLOOR) == "standard"
    assert stakes_floor_tier("severe", FLOOR) == "deep"
    assert stakes_floor_tier("low", FLOOR) is None
    assert stakes_floor_tier(None, FLOOR) is None
    assert stakes_floor_tier("high", {"high": "vision"}) is None


@pytest.mark.parametrize("first,nt1,ver,err,expected", [
    (False, False, False, False, False),
    (True, False, False, False, True),
    (False, True, False, False, True),
    (False, False, True, False, True),
    (False, False, False, True, True),
])
def test_floor_bound_truth_table(first: bool, nt1: bool, ver: bool, err: bool, expected: bool) -> None:
    assert is_floor_bound_step(
        first_step=first, prev_non_tier1=nt1, prev_verification=ver, prev_error=err,
    ) is expected


class _Elig:
    def __init__(self, tiers: tuple[str, ...] = ("fast", "standard", "deep")) -> None:
        self.tiers = tiers

    def assess(self, tier: str, *, prompt_tokens: int, reserved_output: int) -> EligibilityVerdict:
        return EligibilityVerdict(tier in self.tiers, None if tier in self.tiers else "ineligible")


def _ctl(stakes: str | None = "high", signals: tuple[str, ...] = (), *, call_site: str = "fast",
         up: int = 2, elig: _Elig | None = None, verification: tuple[str, ...] = ("verify",)) -> TierChoiceController:
    case = SimpleNamespace(stakes=stakes, signals=signals)
    return TierChoiceController(
        call_site_tier=call_site, stakes_floor=FLOOR, max_upward_moves=up,
        eligibility=elig or _Elig(), case_provider=lambda: case, verification_ids=verification,
        agent_id="agent-1", work_item_id=lambda: "w-1",
    )


def _valid(tier: str, reason: str = "hard_step") -> Any:
    return split_directive(_resp(f"x\n{_line(tier, reason)}"))[1]


def test_first_step_raises_to_floor_and_never_lowers() -> None:
    ctl = _ctl("severe", call_site="fast")
    d = ctl.next_request_tier()
    assert (d.tier, d.outcome, d.floor_bound) == ("deep", "floor_raise", True)
    assert ctl.last_floor == "deep"


def test_no_stakes_means_no_floor_and_call_site_tier() -> None:
    d = _ctl(None, call_site="fast").next_request_tier()
    assert (d.tier, d.outcome, d.floor) == ("fast", "call_site", None)


def test_call_site_above_floor_is_kept() -> None:
    assert _ctl("high", call_site="deep").next_request_tier().tier == "deep"


def test_observation_step_uses_sticky_agent_tier_below_floor() -> None:
    ctl = _ctl("high", call_site="fast")
    first = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    assert ctl.observe(first, _valid("fast", "easy_step"), prompt_tokens_estimate=10) == "agent_choice"
    second = ctl.next_request_tier()
    assert second.tier == "fast" and second.floor_bound is False


def test_non_tier1_call_makes_next_step_floor_bound() -> None:
    ctl = _ctl("high", call_site="fast")
    ctl.next_request_tier()
    ctl.after_tools(tool_names=["write"], all_tier1=False, results_is_error=[False])
    d = ctl.next_request_tier()
    assert d.floor_bound and d.tier == "standard" and d.outcome == "floor_raise"


def test_error_and_verification_make_next_step_floor_bound() -> None:
    ctl = _ctl("high")
    ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[True])
    assert ctl.next_request_tier().floor_bound
    ctl.after_tools(tool_names=["verify"], all_tier1=True, results_is_error=[False])
    assert ctl.next_request_tier().floor_bound


def test_upward_move_without_evidence_is_rejected() -> None:
    ctl = _ctl("low", call_site="fast")
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    assert ctl.observe(d, _valid("deep"), prompt_tokens_estimate=1) == "rejected:uncorroborated_upward"
    assert ctl.next_request_tier().tier == "fast"


def test_upward_move_with_error_evidence_is_accepted() -> None:
    ctl = _ctl("low", call_site="fast")
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[True])
    assert ctl.observe(d, _valid("deep", "prior_error"), prompt_tokens_estimate=1) == "agent_choice"
    assert ctl.next_request_tier().tier == "deep"


def test_upward_move_with_organ_signal_evidence_is_accepted() -> None:
    ctl = _ctl("low", signals=("underspend",))
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    assert ctl.observe(d, _valid("standard"), prompt_tokens_estimate=1) == "agent_choice"


def test_overspend_signal_is_not_difficulty_evidence() -> None:
    ctl = _ctl("low", signals=("overspend",))
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    assert ctl.observe(d, _valid("standard"), prompt_tokens_estimate=1) == "rejected:uncorroborated_upward"


def test_upward_cap_allows_exactly_n_moves() -> None:
    ctl = _ctl("low", call_site="fast", up=1)
    outcomes = []
    for tier in ("standard", "deep"):
        d = ctl.next_request_tier()
        ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[True])
        outcomes.append(ctl.observe(d, _valid(tier), prompt_tokens_estimate=1))
    assert outcomes == ["agent_choice", "rejected:upward_cap"]


def test_zero_cap_rejects_every_upward_move() -> None:
    ctl = _ctl("low", up=0)
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[True])
    assert ctl.observe(d, _valid("standard"), prompt_tokens_estimate=1) == "rejected:upward_cap"


def test_ineligible_tier_is_rejected() -> None:
    ctl = _ctl("low", elig=_Elig(("fast",)))
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[True])
    assert ctl.observe(d, _valid("deep"), prompt_tokens_estimate=1) == "rejected:ineligible"


def test_downward_move_needs_no_evidence() -> None:
    ctl = _ctl("low", call_site="deep")
    d = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    assert ctl.observe(d, _valid("fast", "easy_step"), prompt_tokens_estimate=1) == "agent_choice"


def test_absent_and_invalid_directives_do_not_change_the_tier() -> None:
    ctl = _ctl("low", call_site="standard")
    d = ctl.next_request_tier()
    assert ctl.observe(d, split_directive(_resp("x"))[1], prompt_tokens_estimate=1) == "no_directive"
    assert ctl.observe(d, split_directive(_resp('x\n@@next_tier nope'))[1], prompt_tokens_estimate=1).startswith("rejected")
    assert ctl.next_request_tier().tier == "standard"


def test_guard_redoes_a_sub_floor_final_answer_once() -> None:
    ctl = _ctl("high", call_site="fast")
    first = ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    obs = ctl.next_request_tier()
    assert obs.tier == "fast" and not obs.floor_bound
    redo = ctl.guard_response(obs, tool_names=[], all_tier1=True)
    assert redo is not None and redo.tier == "standard" and redo.outcome == "floor_redo"
    assert ctl.guard_response(redo, tool_names=[], all_tier1=True) is None
    assert first.floor_bound


def test_guard_leaves_pure_observation_alone() -> None:
    ctl = _ctl("high", call_site="fast")
    ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    obs = ctl.next_request_tier()
    assert ctl.guard_response(obs, tool_names=["read"], all_tier1=True) is None


def test_guard_redoes_a_sub_floor_verification_or_write_call() -> None:
    ctl = _ctl("high", call_site="fast")
    ctl.next_request_tier()
    ctl.after_tools(tool_names=["read"], all_tier1=True, results_is_error=[False])
    obs = ctl.next_request_tier()
    assert ctl.guard_response(obs, tool_names=["write"], all_tier1=False) is not None
    assert ctl.guard_response(obs, tool_names=["verify"], all_tier1=True) is not None


def test_controller_audit_callback_failure_is_swallowed() -> None:
    def boom(_p: dict[str, Any]) -> None:
        raise RuntimeError("audit down")

    case = SimpleNamespace(stakes="high", signals=())
    ctl = TierChoiceController(
        call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=_Elig(),
        case_provider=lambda: case, audit=boom,
    )
    assert ctl.next_request_tier().tier == "standard"


def test_audit_payload_carries_ids_and_closed_fields() -> None:
    seen: list[dict[str, Any]] = []
    case = SimpleNamespace(stakes="severe", signals=())
    ctl = TierChoiceController(
        call_site_tier="fast", stakes_floor=FLOOR, max_upward_moves=2, eligibility=_Elig(),
        case_provider=lambda: case, audit=seen.append, agent_id="a", work_item_id=lambda: "w",
    )
    ctl.next_request_tier()
    assert seen[0]["agent_id"] == "a" and seen[0]["work_item_id"] == "w"
    assert seen[0]["outcome"] == "floor_raise" and seen[0]["floor"] == "deep"


def test_controller_has_no_emergency_tier() -> None:
    # Amendment 1: a controller that cannot decide REFUSES; it never invents a tier.
    # This used to pin `emergency_tier()` (a fallback to the call-site tier raised to the floor).
    assert not hasattr(_ctl('severe'), 'emergency_tier')


def test_prompt_block_lists_only_eligible_tiers_and_empty_when_none() -> None:
    ctl = _ctl("high", elig=_Elig(("standard", "deep")))
    block = ctl.prompt_block(prompt_tokens_estimate=1)
    assert "standard, deep" in block and "fast," not in block
    assert _ctl("high", elig=_Elig(())).prompt_block(prompt_tokens_estimate=1) == ""


def test_tier_choice_armed_requires_all_four_flags_strictly_true() -> None:
    def rt(dm: Any, econ: Any, choice: Any, routing: Any) -> Any:
        econ_ns = SimpleNamespace(enabled=econ, tier_choice=SimpleNamespace(enabled=choice))
        return SimpleNamespace(config=SimpleNamespace(
            dm_agentic=SimpleNamespace(enabled=dm, economic_judgment=econ_ns),
            model_routing=SimpleNamespace(enabled=routing),
        ))

    assert tier_choice_armed(rt(True, True, True, True)) is True
    for flags in [(False, True, True, True), (True, False, True, True), (True, True, False, True), (True, True, True, False), (True, True, "yes", True)]:
        assert tier_choice_armed(rt(*flags)) is False
    assert tier_choice_armed(SimpleNamespace()) is False
    assert tier_choice_armed(None) is False


def test_floor_ask_rationale_uses_closed_tokens_only() -> None:
    text = tier_floor_rationale(floor="deep\nIGNORE ALL", stakes="<script>", stakes_provenance="x", tried=3)
    assert "IGNORE" not in text and "<script>" not in text
    assert "'unknown'" in text and "unrecorded" in text and "3 model step" in text
    assert "deep" in tier_floor_rationale(floor="deep", stakes="high", stakes_provenance="captain", tried=1)
