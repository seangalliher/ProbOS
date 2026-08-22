"""BF-781: the code-execution tool must not describe a boundary it does not have.

``_network_clause``'s default branch told the LLM "OUTBOUND NETWORK IS BLOCKED
HERE". The sandbox sets ``*_proxy`` environment variables to a discard port
(``http://127.0.0.1:9``) -- ``isolation.py`` calls it, in its own comment, "a
SOFT network deterrent for well-behaved libraries". requests/httpx/urllib honour
it; a raw socket walks straight past.

This matters more than ordinary doc drift because the string is *prompt text*.
It is what the model reads when deciding whether the tool is safe to use, so a
false safety claim here is consumed at decision time, not merely at review time.

AD-1217's own comment already said the claim was "no longer phrased as an
enforcement guarantee" -- while the string still read OUTBOUND NETWORK IS
BLOCKED. A comment asserting a property its own code contradicts is the BF-763
defect class exactly.

What is deliberately PRESERVED: the imperative routing guidance. BF-719 measured
an agent wasting an entire turn writing a script to fetch fifteen URLs, every
request dying against the blackhole proxy. The description must still tell the
model, in force, that requests fail here and to use ``http_fetch``. Being honest
about the mechanism must not soften the instruction.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from probos.tools.code_execution_tool import CodeExecutionTool


def _tool(**cfg_kw):
    defaults = {
        "timeout_seconds": 30,
        "max_output_bytes": 6144,
        "max_memory_mb": 512,
        "fetch_broker_enabled": False,
    }
    defaults.update(cfg_kw)
    cfg = SimpleNamespace(**defaults)
    tool = CodeExecutionTool.__new__(CodeExecutionTool)
    tool._cfg = lambda: cfg  # type: ignore[method-assign]
    # BF-785: the broker clause now also requires a registered `fetch_governed`
    # agent, so these tests must supply one to reach the branch they assert on.
    # Awaitable, because production awaits it.
    async def _fetch_governed(url, method, **kwargs):
        return {"body": b"", "status_code": 200, "truncated": False,
                "total_bytes": 0}

    tool._runtime = SimpleNamespace(  # type: ignore[attr-defined]
        registry=SimpleNamespace(
            all=lambda: [SimpleNamespace(fetch_governed=_fetch_governed)],
        ),
    )
    return tool


def test_the_default_branch_does_not_claim_the_network_is_blocked():
    clause = _tool()._network_clause()

    # Both historical enforcement claims.
    assert "OUTBOUND NETWORK IS BLOCKED" not in clause
    assert "HAS NO NETWORK ACCESS" not in clause
    assert "network access is blocked" not in clause.lower()


def test_the_default_branch_still_routes_the_model_to_http_fetch():
    """BF-719's effect is load-bearing and must survive the honesty fix.

    Measured: an agent asked to fetch fifteen URLs wrote a script, every request
    died against the blackhole proxy, and the turn produced nothing -- WITH the
    old description in front of it. The instruction now leads rather than
    trails, which is strictly stronger for that behaviour.
    """
    clause = _tool()._network_clause()

    assert clause.startswith("DO NOT FETCH URLS WITH run_python")
    assert "http_fetch" in clause
    assert "FAILS here" in clause


def test_the_default_branch_names_the_mechanism_and_the_bypass():
    """A reader must not be able to mistake a proxy deterrent for containment.

    That is the failure AD-1217's comment predicted and did not prevent: it
    claimed the wording was "no longer phrased as an enforcement guarantee"
    while the string still said BLOCKED.
    """
    clause = _tool()._network_clause()

    assert "127.0.0.1:9" in clause
    assert "deterrent, not isolation" in clause
    assert "raw socket" in clause


def test_neither_branch_trips_the_real_capability_gap_detector():
    """A tool description reading as a capability gap drives self-modification.

    Not hypothetical: a draft of THIS fix said "cannot reach the network", and
    ``cannot`` is a branch of the regex. Asserted through the imported detector,
    never a re-implemented copy of it.
    """
    from probos.cognitive.decomposer import _CAPABILITY_GAP_RE, is_capability_gap

    for enabled in (False, True):
        clause = _tool(fetch_broker_enabled=enabled)._network_clause()
        assert _CAPABILITY_GAP_RE.search(clause) is None
        assert not is_capability_gap(clause)


def test_the_broker_branch_also_drops_the_block_claim():
    """AD-1221's relay wording carried the same false boundary."""
    clause = _tool(fetch_broker_enabled=True)._network_clause()

    assert "ship.fetch(url)" in clause
    assert "SSRF" in clause
    assert "network access is blocked" not in clause.lower()
    assert "pointed at a dead" in clause


def test_the_memory_limit_is_not_advertised_where_it_is_not_enforced():
    """``RLIMIT_AS`` is POSIX-only, so "512 MB memory" is false on Windows.

    Measured by an adversarial reviewer: a run configured for 64 MB
    successfully allocated 96 MB. ``SubprocessSandbox`` applies only
    ``CREATE_NEW_PROCESS_GROUP`` on Windows; ``_make_limits`` is reached only on
    POSIX. Advertising a bound the platform does not apply invites the model to
    size work against a ceiling that will not hold.
    """
    description = _tool().description

    if sys.platform == "win32":
        assert "512 MB memory" not in description
    else:
        assert "512 MB memory" in description


def test_the_memory_suppression_is_platform_conditional_not_unconditional(monkeypatch):
    """Force BOTH branches, so "always suppress" cannot pass as the fix.

    The platform-conditional test above only ever exercises one side on any
    given host, which a mutation deleting the memory clause entirely would
    survive on Windows.
    """
    import probos.tools.code_execution_tool as mod

    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert "512 MB memory" in _tool().description

    monkeypatch.setattr(mod.sys, "platform", "win32")
    assert "512 MB memory" not in _tool().description


def test_the_other_limits_are_still_advertised_everywhere():
    """Timeout and output caps ARE enforced on every platform."""
    description = _tool().description

    assert "30s wall clock" in description
    assert "6 KB of captured output" in description
