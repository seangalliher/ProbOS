"""BF-686: a call refused by an open breaker is not a new error.

Observed live on 2026-07-27: the runtime log carried **2,025**
``All LLM tiers unavailable and no cached response`` ERROR lines describing
**19** actual BF-674 cooldown events — a ~107:1 amplification. Those lines were
100% of ``llm_client``'s ERROR volume and roughly 78% of every ERROR in the
log, which is what made a transient endpoint wobble look like a systemic
runtime fault and buried the genuine failures underneath it.

The severity was keyed to the *outcome* (no content returned) rather than to
the *attribution* (why). When BF-674 opens its endpoint breaker it deliberately
refuses queued background calls so they honest-degrade — that is the breaker
succeeding, and the endpoint condition was already reported in full, once, when
the cooldown opened. Repeating it per refused call adds no information.

BF-674's design is not changed here: the breaker is endpoint-keyed on purpose
("Track one state per real endpoint, not per alias tier"), so all tiers sharing
a ``base_url|format`` going unavailable together is correct. Only the reporting
changes.

Attribution is structural, not string-matched: ``_endpoint_permit`` already
returns ``allowed=False`` for a refusal, so the loop records whether any tier
reached transport at all. An exhaustion where none did is breaker-attributable;
anything that tried and failed keeps ERROR.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from probos.cognitive.llm_client import _EndpointFailureState


class _Reporter:
    """The BF-686 reporting surface, bound to hand-built state.

    The real ``complete()`` needs a configured client, live transport and a
    populated tier table; the reporting decision under test depends only on the
    epoch map and the failure states, so those are supplied directly. The
    methods are the production ones, taken unbound off the class.
    """

    def __init__(self, *endpoint_keys: str) -> None:
        from probos.cognitive.llm_client import OpenAICompatibleClient

        self._endpoint_failure_states = {
            key: _EndpointFailureState() for key in endpoint_keys
        }
        self._reported_exhaustion_epochs: dict[str, int] = {}
        self._breaker_suppressed_exhaustions = 0
        self._report = (
            OpenAICompatibleClient._report_breaker_suppressed_exhaustion.__get__(
                self
            )
        )

    def refuse(self, *keys: str) -> None:
        self._report(set(keys), "req12345", "cooldown active for 9.9s")

    def open_new_cooldown(self, key: str) -> None:
        """What BF-674 does when it trips again: a fresh epoch."""
        self._endpoint_failure_states[key].epoch += 1


def _levels(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.levelname for r in caplog.records]


# ---------------------------------------------------------------------------
# One line per outage, not per call
# ---------------------------------------------------------------------------

def test_first_refusal_in_an_epoch_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reporter = _Reporter("proxy|openai")
    with caplog.at_level(logging.DEBUG):
        reporter.refuse("proxy|openai")

    assert _levels(caplog) == ["WARNING"]
    assert "BF-674 breaker is refusing background LLM calls" in caplog.text
    assert "proxy|openai@epoch0" in caplog.text


def test_the_storm_behind_it_collapses_to_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The 2,025-line case: many queued callers, one endpoint event."""
    reporter = _Reporter("proxy|openai")
    with caplog.at_level(logging.DEBUG):
        for _ in range(200):
            reporter.refuse("proxy|openai")

    levels = _levels(caplog)
    assert levels.count("WARNING") == 1
    assert levels.count("DEBUG") == 199
    assert "ERROR" not in levels


def test_a_new_cooldown_earns_a_new_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Suppression is bounded by epoch, so a genuinely new outage is never
    hidden behind an earlier one."""
    reporter = _Reporter("proxy|openai")
    with caplog.at_level(logging.DEBUG):
        reporter.refuse("proxy|openai")
        reporter.refuse("proxy|openai")
        reporter.open_new_cooldown("proxy|openai")
        reporter.refuse("proxy|openai")

    assert _levels(caplog).count("WARNING") == 2
    assert "proxy|openai@epoch1" in caplog.text


def test_each_endpoint_is_tracked_independently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A second endpoint's first outage must not be swallowed by the first's."""
    reporter = _Reporter("proxy-a|openai", "proxy-b|openai")
    with caplog.at_level(logging.DEBUG):
        reporter.refuse("proxy-a|openai")
        reporter.refuse("proxy-b|openai")
        reporter.refuse("proxy-a|openai")

    assert _levels(caplog).count("WARNING") == 2
    assert "proxy-a|openai@epoch0" in caplog.text
    assert "proxy-b|openai@epoch0" in caplog.text


def test_the_suppressed_volume_is_still_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The count is what the log no longer carries; losing it would trade
    noise for blindness."""
    reporter = _Reporter("proxy|openai")
    with caplog.at_level(logging.DEBUG):
        for _ in range(50):
            reporter.refuse("proxy|openai")

    assert reporter._breaker_suppressed_exhaustions == 50


def test_an_unknown_endpoint_key_still_reports(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Defensive: a key with no failure state must not silently drop the
    report, or a whole outage could go unlogged."""
    reporter = _Reporter("proxy|openai")
    with caplog.at_level(logging.DEBUG):
        reporter.refuse("never-registered|openai")

    assert _levels(caplog) == ["WARNING"]
    assert "never-registered|openai@epoch-1" in caplog.text


def test_reporting_survives_an_instance_built_without_init(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Several suites construct this client bypassing ``__init__``, so the
    BF-686 attributes are absent there. A diagnostics counter must never be
    the thing that breaks an otherwise healthy client.
    """
    from probos.cognitive.llm_client import OpenAICompatibleClient

    bare = object.__new__(OpenAICompatibleClient)
    with caplog.at_level(logging.DEBUG):
        bare._report_breaker_suppressed_exhaustion(
            {"proxy|openai"}, "req12345", "cooldown active",
        )

    assert _levels(caplog) == ["WARNING"]
    assert bare._breaker_suppressed_exhaustions == 1


def test_health_status_survives_an_instance_built_without_init() -> None:
    """Same bypass, on the read side."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    bare = object.__new__(OpenAICompatibleClient)
    bare._consecutive_failures = {}
    bare._consecutive_successes = {}
    bare._last_success = {}
    bare._last_failure = {}
    bare._UNREACHABLE_THRESHOLD = 3
    bare._endpoint_cooldown_remaining = lambda _tier: 0.0

    assert bare.get_health_status()["breaker_suppressed_exhaustions"] == 0


def test_reporting_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    """This sits on the honest-degrade path; a failure to describe an outage
    must not become a second outage."""
    reporter = _Reporter("proxy|openai")
    reporter._endpoint_failure_states = "not-a-mapping"  # type: ignore[assignment]

    with caplog.at_level(logging.DEBUG):
        reporter.refuse("proxy|openai")  # must not raise

    assert "ERROR" not in _levels(caplog)


# ---------------------------------------------------------------------------
# The carve-out stays narrow
# ---------------------------------------------------------------------------

def test_health_status_publishes_the_suppressed_count() -> None:
    """The volume moved out of the log has to remain observable somewhere."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    reporter = _Reporter("proxy|openai")
    for _ in range(7):
        reporter.refuse("proxy|openai")

    # The tier loop in the real accessor reads per-tier counters and the
    # cooldown probe for every tier in ``_LLM_TIERS``, so those are supplied
    # rather than assumed absent — this exercises the production method, not a
    # reimplementation of it.
    reporter._consecutive_failures = {}
    reporter._consecutive_successes = {}
    reporter._last_success = {}
    reporter._last_failure = {}
    reporter._UNREACHABLE_THRESHOLD = 3
    reporter._endpoint_cooldown_remaining = lambda _tier: 0.0
    status: dict[str, Any] = OpenAICompatibleClient.get_health_status(
        reporter,  # type: ignore[arg-type]
    )
    assert status["breaker_suppressed_exhaustions"] == 7
    assert status["overall"] == "operational"


def test_the_error_message_still_exists_for_real_exhaustion() -> None:
    """Guards the guard: the ERROR path must not have been deleted outright.

    Attribution decides severity, so a genuine exhaustion — anything that
    reached transport and failed — still has to be loud.
    """
    import inspect

    from probos.cognitive.llm_client import OpenAICompatibleClient

    source = inspect.getsource(OpenAICompatibleClient._complete_inner)
    assert "logger.error(\"All LLM tiers unavailable" in source
    assert "if breaker_refused_keys and not attempted_transport:" in source
