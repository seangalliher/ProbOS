"""AD-528c: Ground-Truth Trust-Network Feedback tests.

Subscribes to AD-528 verification events (PASSED/FAILED) and updates
TrustNetwork via the public record_outcome API. v1 invokes the public
method only — ProbOS principle 3 (raw alpha/beta storage) is enforced
by TrustNetwork internally; AD-528c never bypasses it.

VERIFICATION_REJECTED is NOT consumed in v1 (co-fires with FAILED;
double-counting prevention). Distinct REJECTED-aware weighting is
deferred to AD-528c-1.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.ground_truth import GroundTruthTrustFeedback
from probos.config import GroundTruthConfig
from probos.events import EventType


# ----- Helpers -----


def _make_runtime(*, with_trust_network: bool = True):
    """Build a SimpleNamespace runtime with optional MagicMock trust_network."""
    rt = SimpleNamespace()
    if with_trust_network:
        rt.trust_network = MagicMock()
        rt.trust_network.record_outcome = MagicMock(return_value=0.5)
    else:
        rt.trust_network = None
    return rt


def _make_feedback(rt=None, **kwargs):
    if rt is None:
        rt = _make_runtime()
    fb = GroundTruthTrustFeedback(runtime=rt, **kwargs)
    return fb, rt


def _evt(type_str: str, **data) -> dict:
    """Build an event payload matching runtime._emit_event shape."""
    return {"type": type_str, "data": data, "timestamp": 0.0}


# ----- 1-3: Config field defaults -----


def test_ground_truth_config_trust_feedback_enabled_default_false():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_enabled is False


def test_ground_truth_config_trust_feedback_success_weight_default():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_success_weight == 1.0


def test_ground_truth_config_trust_feedback_failure_weight_default():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_failure_weight == 0.5


# ----- 4: PASSED dispatch -----


def test_on_event_passed_calls_record_outcome_success_true():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="a1", booking_id="bk1"))
    assert rt.trust_network.record_outcome.call_count == 1
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("a1",)
    assert call.kwargs["success"] is True
    assert call.kwargs["weight"] == 1.0


# ----- 5: FAILED dispatch -----


def test_on_event_failed_calls_record_outcome_success_false():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))
    assert rt.trust_network.record_outcome.call_count == 1
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("a1",)
    assert call.kwargs["success"] is False
    assert call.kwargs["weight"] == 0.5


# ----- 6-7: REJECTED + QUARANTINED no-op (double-counting prevention) -----


def test_on_event_rejected_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_REJECTED.value, agent_id="a1", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


def test_on_event_quarantined_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.WORK_ITEM_QUARANTINED.value, agent_id="a1", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


# ----- 8: Empty agent_id is a no-op -----



def test_on_event_empty_agent_id_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()
    # Missing agent_id key entirely
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


# ----- 9: Missing trust_network is a no-op -----


def test_on_event_missing_trust_network_is_noop():
    rt = _make_runtime(with_trust_network=False)
    fb = GroundTruthTrustFeedback(runtime=rt)
    # Should NOT raise
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="a1", booking_id="bk1"))
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))


# ----- 10: record_outcome exception swallowed (tier-2 log-and-degrade) -----


def test_on_event_record_outcome_exception_log_and_degrade(caplog):
    fb, rt = _make_feedback()
    rt.trust_network.record_outcome.side_effect = RuntimeError("trust db locked")
    with caplog.at_level(logging.WARNING):
        # Should NOT raise
        fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))
    assert any(
        "AD-528c: trust_network.record_outcome failed" in rec.getMessage()
        for rec in caplog.records
    )


# ----- 11: on_event is sync, not async -----


def test_on_event_is_sync_not_async():
    fb, _rt = _make_feedback()
    assert inspect.iscoroutinefunction(fb.on_event) is False


# ----- 12: record_outcome kwargs locked -----


def test_on_event_passes_record_outcome_kwargs_correctly():
    fb, rt = _make_feedback(success_weight=3.5, failure_weight=0.75)
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="agent-7", booking_id="bk-x"))
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("agent-7",)
    assert call.kwargs == {
        "success": True,
        "weight": 3.5,
        "intent_type": "ground_truth_verification",
        "episode_id": "bk-x",
        "verifier_id": "ground_truth",
        "source": "ground_truth_verification",
    }
    # FAILED path uses failure_weight
    rt.trust_network.record_outcome.reset_mock()
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="agent-7", booking_id="bk-y"))
    call2 = rt.trust_network.record_outcome.call_args
    assert call2.kwargs["weight"] == 0.75
    assert call2.kwargs["episode_id"] == "bk-y"
    assert call2.kwargs["success"] is False
