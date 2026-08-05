"""BF-717: the stop notice must lead, and must name the action that works.

Measured on the reference vessel 2026-08-04. A promoted turn hit its step
limit, filed a continue request, and posted this into the thread:

    The responses for numpy and setuptools are getting truncated before the
    `"version"` field in the `"info"` object. Let me fetch via the simpler
    `/pypi/{package}/{latest}` approach to get clean version info.

    ---
    I stopped here because this turn reached its step limit. The work above is
    partial and the task is still open. I filed request a386c83e-62ba-... asking
    the Captain whether to keep going; say the word and I will pick up from
    exactly where this stopped.

Two defects in one message:

1. ORDER. It opens with 200 characters of mid-thought technical detail that
   reads as an agent still working. The Captain read the top, saw progress, and
   waited 22 minutes. The stop notice was there the whole time, below a rule.

2. DIRECTION. "say the word" tells the Captain a chat reply will resume the
   work. It will not, and never did. Approval is the mechanism — in the Bridge.
   This is the most damaging line in the message because it sends the human to
   the one surface that cannot help them.
"""

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome
from probos.cognitive.continue_or_ask import (
    _CUT_OFF_LEAD_NO_WORK,
    _CUT_OFF_LEAD_WITH_WORK,
    _CUT_OFF_TAIL,
    _CUT_OFF_TAIL_WITH_REQUEST,
    resolve_exhausted_turn,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE

_REQ = "a386c83e-62ba-484b-b9c9-01db8ba91921"
_PARTIAL = (
    "The responses for numpy and setuptools are getting truncated before the "
    "version field. Let me fetch via the simpler endpoint."
)


async def _never_reinvoked(_task_text: str):  # pragma: no cover - guard
    raise AssertionError("must not re-invoke")


class _Runtime:
    """No request store: exercises the filing-failed tail without I/O."""

    capability_request_store = None


def _config(**kw):
    from types import SimpleNamespace

    base = dict(
        enabled=True,
        continue_or_ask_enabled=True,
        continue_or_ask_max_passes=1,
        max_iterations=10,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestTheStopLeads:
    """The first line a Captain reads must be the one that needs them."""

    @pytest.mark.asyncio
    async def test_the_notice_comes_before_the_partial_work(self):
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text=_PARTIAL, stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="counselor_0",
            base_task_text="fetch fifteen packages",
            config=_config(),
        )

        # Assert — this is the regression. Before BF-717 the partial work came
        # first and the Captain never reached the notice.
        assert text.index("I have stopped") < text.index("The responses for")

    @pytest.mark.asyncio
    async def test_the_first_line_says_it_stopped(self):
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text=_PARTIAL, stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="counselor_0",
            base_task_text="fetch fifteen packages",
            config=_config(),
        )

        # Assert — a human scanning a thread reads exactly this much.
        first_line = text.splitlines()[0].lower()
        assert "stopped" in first_line
        assert "approval" in first_line

    @pytest.mark.asyncio
    async def test_the_partial_work_is_still_returned_verbatim(self):
        """BF-717 moves the work; AD-1164's guarantee that it survives holds."""
        # Act
        text = await resolve_exhausted_turn(
            WorkItemAgenticOutcome(
                final_text=_PARTIAL, stopped_reason="max_iterations"
            ),
            reinvoke=_never_reinvoked,
            runtime=_Runtime(),
            agent_id="counselor_0",
            base_task_text="fetch fifteen packages",
            config=_config(),
        )

        # Assert
        assert _PARTIAL in text


class TestItNamesTheActionThatWorks:
    """"Say the word" sent the Captain to a surface that cannot help."""

    def test_no_variant_tells_the_captain_to_say_the_word(self):
        # Assert — the phrase that cost 22 minutes.
        for text in (
            _CUT_OFF_LEAD_WITH_WORK,
            _CUT_OFF_LEAD_NO_WORK,
            _CUT_OFF_TAIL,
            _CUT_OFF_TAIL_WITH_REQUEST,
        ):
            assert "say the word" not in text.lower()

    def test_the_request_tail_points_at_the_bridge(self):
        # Assert — approval is the mechanism, and the Bridge is where it lives.
        rendered = _CUT_OFF_TAIL_WITH_REQUEST.format(request_id=_REQ)
        assert "approve" in rendered.lower()
        assert "Bridge" in rendered

    def test_the_failed_filing_tail_promises_no_approval(self):
        """When filing failed there is nothing to approve — do not imply there is."""
        # Assert
        assert "bridge" not in _CUT_OFF_TAIL.lower()
        assert "approve the" not in _CUT_OFF_TAIL.lower()
        # It must still offer the Captain a way forward.
        assert "ask me again" in _CUT_OFF_TAIL.lower()


class TestTheTextStaysHonest:
    """Constraints inherited from AD-1164 that a reword must not break."""

    @pytest.mark.parametrize(
        "text",
        [
            _CUT_OFF_LEAD_WITH_WORK,
            _CUT_OFF_LEAD_NO_WORK,
            _CUT_OFF_TAIL,
            _CUT_OFF_TAIL_WITH_REQUEST.format(request_id=_REQ),
        ],
    )
    def test_no_variant_trips_the_capability_gap_regex(self, text):
        """The constant's own comment demands this on every reword.

        A cut-off note that reads as a capability gap would drive the
        self-modification pipeline: the runtime would conclude it is missing a
        capability because an agent said it ran out of steps.
        """
        assert _CAPABILITY_GAP_RE.search(text) is None

    def test_each_lead_describes_the_work_that_is_actually_there(self):
        # Assert — with the work below, the with-work lead points down; the
        # no-work lead must claim no work in either direction.
        assert "below" in _CUT_OFF_LEAD_WITH_WORK
        assert "below" not in _CUT_OFF_LEAD_NO_WORK
        assert "above" not in _CUT_OFF_LEAD_NO_WORK
        assert "above" not in _CUT_OFF_LEAD_WITH_WORK

    def test_both_leads_say_the_task_is_still_open(self):
        """The note must never read as a completion."""
        # Assert
        assert "still open" in _CUT_OFF_LEAD_WITH_WORK.lower()
        assert "still open" in _CUT_OFF_LEAD_NO_WORK.lower()
