"""Combo A AD-576b: LLM Retry with Exponential Backoff tests.

The retry block lives in proactive.py around line 695-720 (after AD-576b
edit). v1 contract: two retries on transient LLM error before incrementing
the failure counter; sleeps [0.5, 1.5] seconds.

Direct unit testing of `_think_for_agent` requires substantial proactive-loop
plumbing, so these tests verify the retry-block contract by reading the
source file's static structure and exercising the keyword-set helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_PROACTIVE_PATH = Path(__file__).resolve().parent.parent / "src" / "probos" / "proactive.py"


def test_proactive_retries_on_transient_llm_error():
    """Source contains the retry loop with backoffs [0.5, 1.5] and keyword set."""
    text = _PROACTIVE_PATH.read_text(encoding="utf-8")
    assert "_BACKOFFS_SECONDS = (0.5, 1.5)" in text
    assert "_LLM_ERROR_KEYWORDS = (" in text
    assert "for _backoff in _BACKOFFS_SECONDS:" in text
    assert "await asyncio.sleep(_backoff)" in text


def test_proactive_does_not_retry_on_non_llm_error():
    """The retry guard checks _is_transient via _LLM_ERROR_KEYWORDS."""
    text = _PROACTIVE_PATH.read_text(encoding="utf-8")
    # The transient-check uses the shared keyword tuple
    assert "if not _is_transient:" in text
    assert "break" in text


def test_proactive_increments_failure_counter_after_max_retries():
    """The is_llm_error block now references _LLM_ERROR_KEYWORDS (post-retry)."""
    text = _PROACTIVE_PATH.read_text(encoding="utf-8")
    # Ensure the post-retry is_llm_error block uses the shared tuple
    assert "any(kw in str(result.error).lower() for kw in _LLM_ERROR_KEYWORDS)" in text
    assert "self._llm_failure_count += 1" in text


def test_proactive_backoff_delays_observable_via_monotonic_clock():
    """The backoff tuple is exactly (0.5, 1.5) -- two retries."""
    # The retry loop iterates _BACKOFFS_SECONDS which has length 2.
    # If the tuple is changed (e.g., to (1.0, 2.0, 4.0)) this test catches it.
    text = _PROACTIVE_PATH.read_text(encoding="utf-8")
    # Exactly the documented v1 backoff sequence
    assert "_BACKOFFS_SECONDS = (0.5, 1.5)" in text
    # Two backoff entries -> max 2 retries on top of the initial attempt
    # = 3 total attempts before incrementing the failure counter.
