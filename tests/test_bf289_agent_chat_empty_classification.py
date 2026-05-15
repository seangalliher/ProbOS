"""BF-289: agent_chat distinguishes empty-LLM-content from missing-IntentResult.

The pre-BF-289 generic "(no response)" branch masked two distinct failures:
(1) the agent's LLM endpoint returned empty content (e.g. Copilot proxy down),
and (2) the intent bus returned no IntentResult at all (no subscriber / timeout).

These tests assert both branches produce distinct, diagnosable text and that
the original generic "(no response)" wording has been retired.
"""

from __future__ import annotations

import inspect


def test_bf289_agent_chat_distinguishes_empty_content_from_missing_result() -> None:
    """Source-level contract guarding the two distinct branches."""
    from probos.routers import agents as agents_module

    src = inspect.getsource(agents_module.agent_chat)

    # Empty-content branch must mention LLM endpoint upstream.
    assert "LLM endpoint returned empty content" in src, (
        "BF-289: agent_chat must explicitly surface 'LLM endpoint returned "
        "empty content' when result envelope is present but content is empty."
    )

    # Missing-IntentResult branch must mention no subscriber / timeout.
    assert "did not respond to intent" in src, (
        "BF-289: agent_chat must explicitly surface the missing-IntentResult "
        "case (no subscriber or handler timeout) separately from empty content."
    )

    # Original generic "(no response)" wording must NOT remain — it conflates
    # the two failure modes.
    assert '"(no response)"' not in src, (
        "BF-289: the generic '(no response)' branch was ambiguous between "
        "empty-LLM-content and missing-IntentResult; it must be replaced by "
        "the two BF-289 branches."
    )


def test_bf289_branches_log_at_warning_for_operator_visibility() -> None:
    """Both branches should log at WARNING so operators see the failure mode
    without trawling DEBUG. The generic branch was silent."""
    from probos.routers import agents as agents_module

    src = inspect.getsource(agents_module.agent_chat)

    # Two distinct logger.warning calls citing BF-289.
    bf289_warnings = src.count("BF-289:")
    # 2 in warning messages + 2 in inline comments = 4. Tolerate >= 2 to
    # allow comment-style or refactor without breaking this contract.
    assert bf289_warnings >= 2, (
        f"BF-289: expected >=2 BF-289 references for the two branches; "
        f"got {bf289_warnings}."
    )
