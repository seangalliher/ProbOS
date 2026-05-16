"""AD-706d: LLM-driven Browser Tool tier classifier tests."""
from __future__ import annotations

import inspect
import time
from typing import Any

import pytest

from probos.avatars.vision_intent_divergence import VisionLLMRateLimit
from probos.config import SystemConfig
from probos.tools.browser import llm_classifier as lc
from probos.tools.browser.llm_classifier import (
    classify_action_with_llm,
    clear_cache,
)


class _FakeLLMResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeLLMClient:
    def __init__(self, text: str = "auto_run", raise_exc: bool = False) -> None:
        self._text = text
        self._raise = raise_exc
        self.calls: list[Any] = []

    def complete_sync(self, request: Any) -> _FakeLLMResponse:
        self.calls.append(request)
        if self._raise:
            raise RuntimeError("LLM offline")
        return _FakeLLMResponse(self._text)


class _FakeRuntime:
    def __init__(self, config: SystemConfig, llm: _FakeLLMClient) -> None:
        self.config = config
        self.llm_client = llm


def _config_enabled(max_per_hour: int = 60, ttl: int = 300) -> SystemConfig:
    cfg = SystemConfig()
    cfg.browser_tool.llm_classifier_enabled = True
    cfg.browser_tool.llm_classifier_max_per_hour = max_per_hour
    cfg.browser_tool.llm_classifier_cache_ttl_seconds = ttl
    return cfg


@pytest.fixture(autouse=True)
def _reset_caches():
    clear_cache()
    VisionLLMRateLimit.reset_all()
    yield
    clear_cache()
    VisionLLMRateLimit.reset_all()


# 1. classifier disabled → rule tier preserved.
def test_classifier_disabled_preserves_rule_tier() -> None:
    cfg = SystemConfig()  # default llm_classifier_enabled=False
    llm = _FakeLLMClient("destructive")
    rt = _FakeRuntime(cfg, llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=2, action="click",
    )
    assert tier == 2
    assert llm.calls == []


# 2. rule tier=3 short-circuits, LLM not called.
def test_destructive_short_circuits() -> None:
    llm = _FakeLLMClient("auto_run")
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=3, action="click",
    )
    assert tier == 3
    assert llm.calls == []


# 3. LLM upgrades 1 → 2.
def test_llm_upgrades_tier() -> None:
    llm = _FakeLLMClient("ack_required")
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click", url="https://example.com/submit",
    )
    assert tier == 2
    assert len(llm.calls) == 1


# 4. LLM CANNOT downgrade tier.
def test_llm_cannot_downgrade_tier() -> None:
    llm = _FakeLLMClient("auto_run")
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=2, action="click",
    )
    assert tier == 2  # No downgrade to 1.


# 5. LLM failure → honest-degrade to rule tier.
def test_llm_failure_honest_degrades() -> None:
    llm = _FakeLLMClient("unused", raise_exc=True)
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click",
    )
    assert tier == 1


# 6. Malformed LLM output → honest-degrade.
def test_llm_malformed_output_honest_degrades() -> None:
    llm = _FakeLLMClient("I am not certain about this")
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click",
    )
    assert tier == 1


# 7. LLM returns out-of-enum string → honest-degrade.
def test_llm_unknown_enum_honest_degrades() -> None:
    llm = _FakeLLMClient("medium_risk")
    rt = _FakeRuntime(_config_enabled(), llm)
    tier = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click",
    )
    assert tier == 1


# 8. Rate-limit cap exhaustion → honest-degrade.
def test_rate_limit_exhaustion() -> None:
    llm = _FakeLLMClient("ack_required")
    rt = _FakeRuntime(_config_enabled(max_per_hour=2, ttl=0), llm)
    # Cache TTL=0 so each call hits the LLM.
    classify_action_with_llm(runtime=rt, rule_tier=1, action="a")
    classify_action_with_llm(runtime=rt, rule_tier=1, action="b")
    # Third call exceeds the per-hour cap.
    tier = classify_action_with_llm(runtime=rt, rule_tier=1, action="c")
    assert tier == 1
    assert len(llm.calls) == 2


# 9. Cache hit: identical signature within TTL → no LLM call.
def test_cache_hit_reuses_prior_tier() -> None:
    llm = _FakeLLMClient("ack_required")
    rt = _FakeRuntime(_config_enabled(ttl=300), llm)
    tier1 = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click",
        url="https://example.com/foo", element_text="Submit",
    )
    tier2 = classify_action_with_llm(
        runtime=rt, rule_tier=1, action="click",
        url="https://example.com/foo", element_text="Submit",
    )
    assert tier1 == 2
    assert tier2 == 2
    assert len(llm.calls) == 1  # second call cache-hits


# 10. classify_action (the rule-based function) is UNCHANGED — companion exists.
def test_classify_action_unchanged_companion_exists() -> None:
    from probos.tools.browser import actions as actions_module
    from probos.tools.browser.llm_classifier import (
        classify_action_with_llm as companion,
    )
    # Existing function still present.
    assert hasattr(actions_module, "classify_action")
    # Companion exists.
    assert callable(companion)
    # Reuse: rate-limit class is shared with vision intent divergence.
    source = inspect.getsource(lc)
    assert "VisionLLMRateLimit" in source
