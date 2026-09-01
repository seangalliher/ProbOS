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
    """Source-level contract guarding the two distinct branches.

    BF-714 moved the empty-content wording out of ``agent_chat`` and into
    ``_llm_degrade_message``, which reports the runtime's actual diagnosis
    (which tier, and the seconds until the BF-674 breaker probes again) instead
    of a fixed instruction to go and check upstream. The BF-289 contract is
    unchanged -- the two failures must stay distinguishable -- so the assertion
    follows the wording to where it now lives rather than pinning the branch to
    a literal it no longer holds.
    """
    from probos.routers import agents as agents_module

    # BF-813 split the routed entry point from the handler body so one
    # ``finally`` could own the DM-sampling bracket. ``agent_chat`` is now the
    # six-line wrapper; the branches this test is about live in the body.
    src = inspect.getsource(agents_module._agent_chat_impl)

    # Empty-content branch: routes through the BF-714 diagnosis helper.
    assert "_llm_degrade_message(runtime)" in src, (
        "BF-289/BF-714: the empty-content branch must render the LLM degrade "
        "message, which is what distinguishes it from the missing-result case."
    )

    # ...and that helper still names the LLM endpoint, in every path it can take.
    helper_src = inspect.getsource(agents_module._llm_degrade_message)
    assert "language model is" in helper_src
    assert "LLM endpoint returned empty content" in inspect.getsource(agents_module), (
        "BF-289: the empty-content case must remain explicitly attributable to "
        "the LLM endpoint, including on the fallback path."
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


def test_bf289_the_two_failures_produce_different_text_at_runtime() -> None:
    """The behavioural half of the contract above.

    A source scan proves the branches exist; it cannot prove they say different
    things. BF-714 changed one of them, which is exactly when this matters.
    """
    from types import SimpleNamespace

    from probos.routers.agents import _llm_degrade_message

    missing_result = "(no reply — agent did not respond to intent)"

    degraded = _llm_degrade_message(SimpleNamespace(llm_client=SimpleNamespace(
        get_health_status=lambda: {
            "overall": "degraded",
            "tiers": {"standard": {
                "status": "unreachable", "consecutive_failures": 3,
                "endpoint_cooldown_remaining_seconds": 12.0,
            }},
        },
    )))

    assert degraded != missing_result
    assert "did not respond to intent" not in degraded
    # And the degraded text is diagnosable rather than an instruction.
    assert "standard" in degraded and "12s" in degraded


def test_bf289_branches_log_at_warning_for_operator_visibility() -> None:
    """Both branches should log at WARNING so operators see the failure mode
    without trawling DEBUG. The generic branch was silent."""
    from probos.routers import agents as agents_module

    # BF-813: the routed entry point is now a wrapper; the branches live in the
    # handler body it delegates to.
    src = inspect.getsource(agents_module._agent_chat_impl)

    # Two distinct logger.warning calls citing BF-289.
    bf289_warnings = src.count("BF-289:")
    # 2 in warning messages + 2 in inline comments = 4. Tolerate >= 2 to
    # allow comment-style or refactor without breaking this contract.
    assert bf289_warnings >= 2, (
        f"BF-289: expected >=2 BF-289 references for the two branches; "
        f"got {bf289_warnings}."
    )
