"""BF-785 (#1249): ship.fetch was advertised whenever the flag was on.

`_network_clause` chose the broker wording from `fetch_broker_enabled` alone.
But `_start_fetch_broker` also needs a registered agent exposing
`fetch_governed`; without one it returns `({}, None)`, the helper file is never
written into the workdir, and a script following the instruction gets an
ImportError on `import ship`.

Measured before the fix -- the flag on, the registry empty:

    fetcher_present=True:  recommends ship.fetch = True
    fetcher_present=False: recommends ship.fetch = True    <- the defect

The issue proposed degrading at runtime instead, on the premise that "the
description property cannot currently see" the dependency, descriptions being
built at offer time and the broker starting at invoke time. That premise is
wrong for THIS dependency: `_governed_fetcher()` is synchronous and reads the
registry, so it is fully available while the description is being built --
verified in the same measurement:

    governed_fetcher visible at description time: True / True

So the offer can require what the run will need, which is the smaller and
earlier fix. It narrows rather than eliminates the window -- an agent could be
deregistered between offer and invoke -- and that residue is recorded below
rather than implied away.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.tools.code_execution_tool import CodeExecutionTool


def _tool(*, flag: bool, fetcher: bool):
    tool = CodeExecutionTool.__new__(CodeExecutionTool)
    tool._cfg = lambda: SimpleNamespace(  # type: ignore[method-assign]
        timeout_seconds=30,
        max_output_bytes=65536,
        max_memory_mb=512,
        fetch_broker_enabled=flag,
    )

    # Production AWAITS `fetch_governed`. Review caught a synchronous lambda
    # here: the offer was made, the broker started, and the first real request
    # died on `object NoneType can't be used in 'await' expression` -- so the
    # test named "when it will work" proved only that an attribute was callable.
    async def _fetch_governed(url, method, **kwargs):
        return {"body": b"", "status_code": 200, "truncated": False,
                "total_bytes": 0}

    agents = (
        [SimpleNamespace(fetch_governed=_fetch_governed)] if fetcher else []
    )
    tool._runtime = SimpleNamespace(  # type: ignore[attr-defined]
        registry=SimpleNamespace(all=lambda: agents),
    )
    return tool


def test_the_broker_wording_needs_a_fetcher_not_just_the_flag() -> None:
    clause = _tool(flag=True, fetcher=False)._network_clause()

    assert "PREFER THIS" not in clause
    assert "ship.fetch" not in clause


def test_the_broker_wording_is_still_offered_when_it_will_work() -> None:
    """The positive premise. Suppressing the clause unconditionally would pass
    the test above and silently remove a capability the operator turned on."""
    clause = _tool(flag=True, fetcher=True)._network_clause()

    assert "PREFER THIS" in clause
    assert "ship.fetch" in clause


def test_the_flag_being_off_is_unchanged() -> None:
    for fetcher in (True, False):
        clause = _tool(flag=False, fetcher=fetcher)._network_clause()
        assert "ship.fetch" not in clause, fetcher


def test_the_fallback_names_the_alternative() -> None:
    """A refusal that does not name the alternative does not change the choice.

    With no relay the model must still be pointed somewhere, or it plans around
    a capability it does not have.
    """
    clause = _tool(flag=True, fetcher=False)._network_clause()
    assert "http_fetch" in clause


def test_the_dependency_is_readable_while_the_description_is_built() -> None:
    """The premise the fix rests on, asserted rather than assumed.

    If `_governed_fetcher` ever became invoke-only, the clause above would
    silently start reporting "no relay" for every run.
    """
    assert _tool(flag=True, fetcher=True)._governed_fetcher() is not None
    assert _tool(flag=True, fetcher=False)._governed_fetcher() is None
