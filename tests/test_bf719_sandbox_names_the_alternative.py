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

    def test_it_still_states_the_network_failure_plainly(self):
        # Assert
        #
        # AD-1217 (#1177) reworded this from "THIS SANDBOX HAS NO NETWORK
        # ACCESS" to "OUTBOUND NETWORK IS BLOCKED HERE". BF-781 reworded it
        # again, because the second phrasing was still an enforcement claim:
        # isolation.py sets blackhole proxy variables and its own comment calls
        # that a "soft deterrent only". requests/httpx/urllib honour them, so
        # the practical claim holds; a raw socket, or any client built with
        # trust_env=False, does not.
        #
        # UPDATED twice, deleted neither time. BF-719's property is that the
        # failure is stated plainly enough to change the agent's routing, and
        # that survives -- now as a leading imperative rather than a trailing
        # fact, which is strictly stronger for the behaviour BF-719 measured.
        d = _description()
        assert "DO NOT FETCH URLS WITH run_python" in d
        assert "FAILS here" in d

    def test_the_routing_instruction_precedes_the_library_note(self):
        """Order matters: the routing fact should not trail the housekeeping."""
        # Assert — same property, BF-781's wording.
        d = _description()
        assert d.index("DO NOT FETCH URLS") < d.index("libraries")

    def test_it_does_not_claim_an_enforcement_level_the_code_lacks(self):
        """AD-1217. The risk was never an agent breaking out — it was a
        reviewer or a later AD treating the sentence as an enforced boundary
        and building on it, the same class as the false comment corrected in
        AD-1211. The sandbox docstring already admits a determined script can
        read host files by absolute path; the network limit now matches that
        honesty."""
        d = _description()
        assert "HAS NO NETWORK ACCESS" not in d
        # BF-781: the replacement was itself an enforcement claim. Both are
        # banned now, and the honest mechanism is asserted positively so a
        # future edit cannot quietly restore absolutism.
        assert "OUTBOUND NETWORK IS BLOCKED" not in d
        assert "deterrent, not isolation" in d

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
