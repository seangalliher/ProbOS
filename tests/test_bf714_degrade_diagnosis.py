"""BF-714 (#1145): the degrade reply carries the diagnosis the runtime made.

When an LLM tier degrades the runtime already knows which tier failed, that the
pool was recycled, that a breaker opened, and how many seconds remain until a
half-open probe (BF-612, BF-659, BF-674, BF-680). All of that went to a console
the Captain cannot see from the HXI, and the reply said "check upstream
proxy/endpoint at the configured tier" -- an instruction to go and rediscover
what the ship already knew.

HXI Design Principle #10 inverted: the Ship's Computer reports from sensors. It
had the sensor reading and emitted a generic instruction instead.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.routers.agents import _LLM_DEGRADE_FALLBACK, _llm_degrade_message


def _runtime(health: Any) -> Any:
    if health is _MISSING:
        return SimpleNamespace(llm_client=SimpleNamespace())

    class _Client:
        def get_health_status(self) -> Any:
            if isinstance(health, Exception):
                raise health
            return health

    return SimpleNamespace(llm_client=_Client())


_MISSING = object()


# ── the diagnosis reaches the Captain ─────────────────────────────


def test_an_open_cooldown_reports_the_countdown() -> None:
    """The countdown is the only part the Captain can act on: wait, or don't."""
    msg = _llm_degrade_message(_runtime({
        "overall": "degraded",
        "tiers": {
            "standard": {"status": "unreachable", "consecutive_failures": 3,
                         "endpoint_cooldown_remaining_seconds": 12.4},
        },
    }))

    assert "standard recovering in 12s" in msg
    assert "degraded" in msg
    assert "check upstream" not in msg


def test_every_exhausted_tier_is_named() -> None:
    """The runtime knew all three tiers were tried in order. Saying so is the
    difference between "something is wrong" and "the endpoint is down".
    """
    msg = _llm_degrade_message(_runtime({
        "overall": "offline",
        "tiers": {
            "fast": {"status": "unreachable", "consecutive_failures": 3,
                     "endpoint_cooldown_remaining_seconds": 15.0},
            "standard": {"status": "unreachable", "consecutive_failures": 3,
                         "endpoint_cooldown_remaining_seconds": 15.0},
            "deep": {"status": "unreachable", "consecutive_failures": 3,
                     "endpoint_cooldown_remaining_seconds": 15.0},
        },
    }))

    for tier in ("fast", "standard", "deep"):
        assert tier in msg
    assert "offline" in msg


def test_a_failing_tier_without_a_cooldown_reports_its_failure_count() -> None:
    msg = _llm_degrade_message(_runtime({
        "overall": "degraded",
        "tiers": {
            "standard": {"status": "recovering", "consecutive_failures": 2,
                         "endpoint_cooldown_remaining_seconds": 0.0},
        },
    }))

    assert "standard recovering after 2 failures" in msg


def test_an_operational_tier_is_not_reported_as_a_problem() -> None:
    """Only the degraded tiers belong in the message; naming a healthy one
    would make the diagnosis wrong.
    """
    msg = _llm_degrade_message(_runtime({
        "overall": "degraded",
        "tiers": {
            "fast": {"status": "operational", "consecutive_failures": 0,
                     "endpoint_cooldown_remaining_seconds": 0.0},
            "deep": {"status": "unreachable", "consecutive_failures": 3,
                     "endpoint_cooldown_remaining_seconds": 9.0},
        },
    }))

    assert "deep recovering in 9s" in msg
    assert "fast" not in msg


# ── it never replaces a diagnosis with a traceback ────────────────


def test_all_tiers_healthy_falls_back_rather_than_claiming_a_fault() -> None:
    """The empty completion had some other cause. Inventing a tier fault would
    send the Captain after the wrong thing.
    """
    msg = _llm_degrade_message(_runtime({
        "overall": "operational",
        "tiers": {
            "fast": {"status": "operational", "consecutive_failures": 0,
                     "endpoint_cooldown_remaining_seconds": 0.0},
        },
    }))

    assert msg == _LLM_DEGRADE_FALLBACK


@pytest.mark.parametrize("health", [
    None,
    {},
    {"tiers": None},
    {"tiers": {}},
    {"tiers": "not a dict"},
    {"tiers": {"fast": "not a dict"}},
    {"tiers": {"fast": {"endpoint_cooldown_remaining_seconds": "soon"}}},
    RuntimeError("health probe exploded"),
])
def test_any_malformed_or_raising_health_degrades_to_the_old_message(
    health: Any,
) -> None:
    """This runs on a path that has ALREADY failed. A formatting error must not
    turn a degraded reply into a 500.
    """
    msg = _llm_degrade_message(_runtime(health))

    assert msg == _LLM_DEGRADE_FALLBACK


def test_a_runtime_without_an_llm_client_degrades() -> None:
    assert _llm_degrade_message(SimpleNamespace()) == _LLM_DEGRADE_FALLBACK
    assert _llm_degrade_message(SimpleNamespace(llm_client=None)) == _LLM_DEGRADE_FALLBACK


def test_a_client_without_the_health_method_degrades() -> None:
    """``get_health_status`` is on the client protocol, but a test double or a
    third-party client may not implement it.
    """
    assert _llm_degrade_message(_runtime(_MISSING)) == _LLM_DEGRADE_FALLBACK


# ── the router uses it ────────────────────────────────────────────


def test_the_router_has_no_hardcoded_degrade_string_left() -> None:
    """The message existed twice in the handler. Both sites must route through
    the helper, or one of them keeps telling the Captain to go look for himself.
    """
    import inspect

    from probos.routers import agents as agents_router

    src = inspect.getsource(agents_router)
    # The literal survives exactly once: inside the fallback constant.
    assert src.count("check upstream proxy/endpoint at the configured tier") == 1
    assert src.count("_llm_degrade_message(runtime)") == 2
