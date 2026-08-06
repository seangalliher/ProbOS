"""BF-719: a constraint that does not name the alternative does not change the choice.

Measured on the reference vessel 2026-08-05. Asked to fetch fifteen web pages,
an agent wrote a Python script to do it. Every request died against the
blackhole proxy the sandbox sets (``isolation.py`` ``_build_env``), the turn
produced nothing, and the Captain was told "That background task is finished."

The agent HAD the constraint. The old description said:

    "Run a Python script in an isolated sandbox to perform a task or produce a
     file ... Network is off; required libraries must already be installed."

It opens by inviting general use ("to perform a task"), and the network
constraint is a trailing clause sixty words later that says what is FORBIDDEN
without saying what to use INSTEAD. The agent had every fact and still routed
into the one tool that cannot reach the network.

The agent then diagnosed this itself, correctly, when asked to investigate.
"""

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.tools.code_execution_tool import CodeExecutionTool


def _description() -> str:
    return CodeExecutionTool(runtime=None).description


class TestTheConstraintNamesTheAlternative:
    """The fix is not "say no harder" — it is "say what to do instead"."""

    def test_it_names_http_fetch_as_the_way_to_reach_a_url(self):
        # Assert — this is the regression. Without a named alternative the
        # model has nowhere to route and picks the tool it was already holding.
        assert "http_fetch" in _description()

    def test_it_still_states_the_sandbox_has_no_network(self):
        # Assert
        lowered = _description().lower()
        assert "no network access" in lowered

    def test_the_no_network_statement_precedes_the_library_note(self):
        """Order matters: the blocking fact should not trail the housekeeping."""
        # Assert
        d = _description()
        assert d.index("NO NETWORK ACCESS") < d.index("libraries")

    def test_it_no_longer_invites_general_task_use(self):
        """"to perform a task" is what made a fetch look in-scope."""
        # Assert
        assert "perform a task" not in _description()


class TestTheDescriptionStaysSafe:
    """Constraints any agent-facing text in this repo has to meet."""

    def test_it_does_not_trip_the_capability_gap_regex(self):
        """A tool description reading as a capability gap would drive self-mod.

        ``is_capability_gap`` fires the self-modification pipeline, and the
        natural phrasing for a restriction reaches straight for "cannot",
        "unable to" and "no ... capability". This description says "HAS NO
        NETWORK ACCESS" and "requests fail", which state the limit without
        matching the gap vocabulary.
        """
        # Assert
        assert _CAPABILITY_GAP_RE.search(_description()) is None

    def test_it_still_describes_what_the_tool_is_for(self):
        """Narrowing the opening must not lose the tool's actual purpose."""
        # Assert
        lowered = _description().lower()
        assert "produce a file" in lowered
        assert "downloadable artifact" in lowered
