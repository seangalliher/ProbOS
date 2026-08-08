"""AD-1217 (#1177) / AD-1218 (#1178): the sandbox describes itself honestly.

Two siblings of BF-726, on the same surface — ``run_python``'s description,
which is the premise every agent reasons from before choosing a tool.

**AD-1217.** The description asserted, in capitals, *"THIS SANDBOX HAS NO
NETWORK ACCESS"*. ``execution/isolation.py::_build_env`` sets blackhole PROXY
variables and says so in its own comment: *"Soft deterrent only (well-behaved
libs honor proxy env). Hard network isolation is Tier 2."* requests and httpx
honour them, which is why the claim holds in practice — a raw socket would not.
The risk was never an agent breaking out. It was a reviewer, an operator or a
later AD treating the sentence as an enforced boundary and building on it: the
same class as the false comment corrected in AD-1211, which I wrote and then
believed. This codebase is careful about the distinction elsewhere — the
sandbox docstring already admits *"a determined script can still read host
files by absolute path"*. The filesystem limit was described honestly and the
network limit was not.

**AD-1218.** A limit an agent can hit should be a limit it is told about, in
the tool that imposes it. The wall clock is the sharpest: a script looping over
fifteen URLs has no way to know it has 30 seconds, so it writes something
reasonable, gets killed mid-run, and has to diagnose a truncation it was never
warned about. Same cycle-burn as the network case, with no signpost at all.

The limits are DERIVED from config rather than written into prose, for exactly
the reason BF-726/BF-727 exist: a hand-maintained number goes stale against the
thing it describes, and then the tool lies about itself.

**What is deliberately NOT decided here.** Whether Tier 1 should actually
enforce the network block (OS-level egress for the child, or requiring Tier 2
containers for untrusted execution) is a security-posture call. #1177 reserves
it for the Captain, and this AD leaves the enforcement exactly as it was and
only stops overstating it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE, is_capability_gap
from probos.config import ExecutionConfig
from probos.tools.code_execution_tool import CodeExecutionTool


def _tool(**overrides):
    cfg = ExecutionConfig(**overrides)
    return CodeExecutionTool(runtime=SimpleNamespace(config=SimpleNamespace(execution=cfg)))


def _description(**overrides) -> str:
    return _tool(**overrides).description


# ── AD-1217: state the limit without overstating the enforcement ───────────
class TestTheNetworkClaimIsAccurate:
    def test_it_no_longer_asserts_an_absolute_guarantee(self) -> None:
        """The headline. `isolation.py` provides a proxy hint, not isolation."""
        assert "HAS NO NETWORK ACCESS" not in _description()

    def test_it_still_states_the_block_plainly(self) -> None:
        """BF-719's property, preserved. The behavioural effect is the whole
        point of the sentence: an agent that knows outbound calls fail routes
        to http_fetch instead of writing a doomed script."""
        desc = _description()
        assert "OUTBOUND NETWORK IS BLOCKED HERE" in desc
        assert "requests fail" in desc

    def test_it_still_names_the_alternative(self) -> None:
        """BF-719's actual finding: a constraint that does not name the
        alternative does not change the choice."""
        assert "http_fetch" in _description()

    def test_the_block_still_precedes_the_library_housekeeping(self) -> None:
        """BF-719's ordering property, unchanged."""
        desc = _description()
        assert desc.index("OUTBOUND NETWORK IS BLOCKED HERE") < desc.index("libraries")

    def test_the_wording_is_safe_against_the_real_gap_detector(self) -> None:
        """A tool description reading as a capability gap drives self-mod.
        Asserted through the imported detector, never a re-implemented regex."""
        desc = _description()
        assert _CAPABILITY_GAP_RE.search(desc) is None
        assert not is_capability_gap(desc)


# ── AD-1218: the limits an agent can hit are stated ────────────────────────
class TestTheLimitsAreStated:
    def test_the_wall_clock_is_stated(self) -> None:
        """The sharpest unstated limit — the one that kills a script mid-run."""
        assert "30s wall clock" in _description(timeout_seconds=30.0)

    def test_the_output_cap_is_stated(self) -> None:
        assert "64 KB of captured output" in _description(max_output_bytes=65536)

    def test_the_memory_cap_is_stated(self) -> None:
        assert "512 MB memory" in _description(max_memory_mb=512)

    def test_it_says_what_to_do_instead(self) -> None:
        """BF-719's lesson applied to the new constraints: naming a limit
        without naming the remedy does not change the choice."""
        assert "split into steps" in _description()

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("timeout_seconds", 120.0, "120s wall clock"),
            ("max_output_bytes", 1024 * 1024, "1024 KB of captured output"),
            ("max_memory_mb", 2048, "2048 MB memory"),
        ],
    )
    def test_the_limits_are_derived_not_written_down(
        self, field, value, expected
    ) -> None:
        """The BF-726 property. A re-tuned sandbox must not start lying about
        itself, which is exactly what a hardcoded number would do."""
        assert expected in _description(**{field: value})

    def test_a_runtime_without_config_still_yields_a_usable_description(
        self,
    ) -> None:
        """Honest-degrade: no config means the limits are simply not claimed,
        rather than claimed wrongly or the property raising."""
        desc = CodeExecutionTool(runtime=None).description
        assert "Limits:" not in desc
        assert "OUTBOUND NETWORK IS BLOCKED HERE" in desc
        assert "http_fetch" in desc

    def test_a_zeroed_limit_is_not_advertised(self) -> None:
        """0 means unbounded in this config; announcing '0 MB memory' would be
        a limit the agent would wrongly plan around."""
        desc = _description(max_memory_mb=0, max_output_bytes=0)
        assert "0 MB memory" not in desc
        assert "0 KB of captured output" not in desc
