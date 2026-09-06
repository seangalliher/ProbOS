"""BF-751: the egress allowlist needs an operator surface.

Live test, 2026-08-11 13:32. The Captain asked Ezri a documentation question and
said explicitly "Use the Microsoft Learn tool." She never called it. She answered
from six ``http_fetch`` calls instead — correctly, with real content, but from
the wrong rung of the AD-1239 ladder.

Asked directly, the running vessel said why:

    GET /api/mcp/servers/{id}/agents/counselor_.../access
    {"server_enabled": true, "tools": [],
     "error": "egress denied for https://learn.microsoft.com/api/mcp"}

``EgressPolicy`` shipped deny-by-default with a hardcoded loopback-only
allowlist and **no way for an operator to extend it** — ``finalize.py`` never
passed ``allowlist``, no config field existed, and the ``allow_host()`` the
docstring offers for "operator-side mutation" is called by nothing at startup.

``mcp_bridge/transport.py`` consults the policy unconditionally. So with the
shipped defaults, no MCP server outside loopback could EVER be reached, and
registration, the server store, risk tiers, the three-tier grant model and
AD-1239's offering were all scaffolding above a gate nothing could open.

The sharp part is which path was blocked. ``HttpFetchAgent`` consults the policy
only when ``egress_active_enforcement`` is True (it is False), so the ship
enforced egress on its MOST governed path -- audited, consent-gated, risk-tiered
-- while leaving raw fetching of the same domain wide open. Design Principle
13(b) inverted: the governed path was the one that was removed.

And it failed silently at every layer, which is why it read as "the agent
ignored MCP" rather than "MCP was unreachable".
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import SecurityInfraConfig
from probos.security.egress import EgressPolicy
from probos.startup.finalize import _warn_on_mcp_egress_mismatch
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission

LEARN = "https://learn.microsoft.com/api/mcp"


class _Srv:
    def __init__(self, url: str, *, type: str = "http") -> None:
        self.url = url
        self.type = type


class _Cfg:
    def __init__(self, servers: list[Any]) -> None:
        self.mcp = type("_Mcp", (), {"servers": servers})()


class _Store:
    def __init__(self, records: list[Any] | None = None) -> None:
        self._records = records or []

    def list_sync(self) -> list[Any]:
        return list(self._records)


def _policy(allowlist: list[str]) -> EgressPolicy:
    return EgressPolicy(allowlist=list(allowlist), deny_by_default=True)


# ---------------------------------------------------------------------------
# The operator surface
# ---------------------------------------------------------------------------

def test_the_default_allowlist_is_exactly_the_old_hardcoded_triple() -> None:
    """Unset must be byte-identical to the behaviour that shipped, or this fix
    silently changes the egress posture of every existing deployment."""
    assert SecurityInfraConfig().egress_allowlist == ["127.0.0.1", "localhost", "::1"]


def test_the_default_denies_the_server_that_started_this() -> None:
    """The defect, stated directly."""
    policy = _policy(SecurityInfraConfig().egress_allowlist)

    assert policy.is_allowed(LEARN) is False


def test_an_allowlisted_host_is_permitted() -> None:
    policy = _policy(["127.0.0.1", "localhost", "::1", "learn.microsoft.com"])

    assert policy.is_allowed(LEARN) is True


def test_allowlisting_one_host_does_not_open_the_rest() -> None:
    """Deny-by-default has to survive the fix."""
    policy = _policy(["learn.microsoft.com"])

    assert policy.is_allowed(LEARN) is True
    assert policy.is_allowed("https://evil.test/api") is False


def test_a_configured_allowlist_reaches_the_policy() -> None:
    """The wiring, not a reimplementation of it.

    An earlier version of this test built the ``EgressPolicy`` itself and passed
    happily with the wiring deleted — half-chain evidence. This drives the real
    ``finalize`` helper so removing the ``allowlist=`` argument fails here.
    """
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_egress_policy

    config = SystemConfig()
    config.security_infra.egress_allowlist = ["example.com"]
    runtime = SimpleNamespace(emit_event=None, egress_policy=None)

    _wire_egress_policy(runtime=runtime, config=config)

    assert runtime.egress_policy.is_allowed("https://example.com/x") is True
    assert runtime.egress_policy.is_allowed("https://localhost/x") is False


def test_the_wiring_preserves_the_loopback_default() -> None:
    """An operator who sets nothing keeps exactly today's posture."""
    from probos.config import SystemConfig
    from probos.startup.finalize import _wire_egress_policy

    runtime = SimpleNamespace(emit_event=None, egress_policy=None)

    _wire_egress_policy(runtime=runtime, config=SystemConfig())

    assert runtime.egress_policy.is_allowed("https://localhost/x") is True
    assert runtime.egress_policy.is_allowed(LEARN) is False


# ---------------------------------------------------------------------------
# A registered-but-denied server must be audible
# ---------------------------------------------------------------------------

def test_a_denied_config_server_is_reported_at_boot(caplog) -> None:
    """Registering a server is a statement of intent. When the allowlist
    disagrees, say so where the operator can act on it."""
    with caplog.at_level(logging.WARNING):
        refused = _warn_on_mcp_egress_mismatch(
            _Cfg([_Srv(LEARN)]), _Store(), _policy(["localhost"])
        )

    assert refused == 1
    assert "learn.microsoft.com" in caplog.text
    assert "egress_allowlist" in caplog.text


def test_a_denied_stored_server_is_reported_too(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        refused = _warn_on_mcp_egress_mismatch(
            _Cfg([]), _Store([_Srv(LEARN)]), _policy(["localhost"])
        )

    assert refused == 1
    assert "learn.microsoft.com" in caplog.text


def test_an_allowed_server_is_silent(caplog) -> None:
    """No warning when config and policy agree — the healthy case must not nag."""
    with caplog.at_level(logging.WARNING):
        refused = _warn_on_mcp_egress_mismatch(
            _Cfg([_Srv(LEARN)]), _Store(), _policy(["learn.microsoft.com"])
        )

    assert refused == 0
    assert "BF-751" not in caplog.text


def test_the_same_host_is_reported_once(caplog) -> None:
    """The live vessel had it in BOTH config and the store."""
    with caplog.at_level(logging.WARNING):
        refused = _warn_on_mcp_egress_mismatch(
            _Cfg([_Srv(LEARN)]), _Store([_Srv(LEARN)]), _policy(["localhost"])
        )

    assert refused == 1


def test_no_policy_means_nothing_to_report() -> None:
    """``egress_enabled: false`` leaves the policy None; that is not a mismatch."""
    assert _warn_on_mcp_egress_mismatch(_Cfg([_Srv(LEARN)]), _Store(), None) == 0


def test_stdio_servers_are_not_egress_checked() -> None:
    """The policy is HTTP-only; a subprocess server has no URL to allow."""
    cfg = _Cfg([_Srv("", type="stdio")])

    assert _warn_on_mcp_egress_mismatch(cfg, _Store(), _policy(["localhost"])) == 0


def test_a_broken_store_does_not_stop_the_boot(caplog) -> None:
    class _Broken:
        def list_sync(self) -> list[Any]:
            raise RuntimeError("store is down")

    with caplog.at_level(logging.WARNING):
        refused = _warn_on_mcp_egress_mismatch(
            _Cfg([_Srv(LEARN)]), _Broken(), _policy(["localhost"])
        )

    assert refused == 1  # the config server is still reported


# ---------------------------------------------------------------------------
# No silent empty tool list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_server_with_no_bridge_client_is_reported(caplog) -> None:
    """This return was silent, which made registered-but-unreachable
    indistinguishable from a server that simply has no tools."""
    from probos.cognitive.mcp_workbench import MCPWorkbench

    wb = MCPWorkbench(
        tool_registry=None,
        bridge=SimpleNamespace(get_client=lambda key: None),
        consensus_invoke=None,
        episode_writer=None,
        server_store=None,
        perm_store=None,
        dept_grant_store=None,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )
    record = SimpleNamespace(name="microsoft-learn", type="http", url=LEARN)

    with caplog.at_level(logging.WARNING):
        tools = await wb._enumerate_tools(record)

    assert tools == []
    assert "microsoft-learn" in caplog.text


@pytest.mark.asyncio
async def test_candidates_that_cannot_be_pulled_are_reported(caplog) -> None:
    """The live shape: tools matched and authorized, none reachable. Silence here
    is what made this read as 'the agent ignored MCP'."""
    from probos.cognitive.mcp_workbench import MCPWorkbench

    permissions = ToolPermissionStore()
    grant = await permissions.issue_grant(
        "a1", "mcp:microsoft-learn", ToolPermission.READ,
    )
    assert permissions.get_active_grants_sync("a1") == [grant]
    descriptor = {"name": "microsoft_docs_search", "description": "d"}

    async def _tools(_rec: Any) -> list[dict[str, str]]:
        return [descriptor]

    record = SimpleNamespace(
        name="microsoft-learn", type="http", url=LEARN,
        enabled=True, default_risk="open", id="s1",
    )
    wb = MCPWorkbench(
        tool_registry=None,
        # No client => pull_tool cannot reach the server, exactly as egress
        # denial produced live.
        bridge=SimpleNamespace(get_client=lambda key: None),
        consensus_invoke=None,
        episode_writer=None,
        server_store=_Store([record]),
        perm_store=permissions,
        dept_grant_store=None,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )
    wb._enumerate_tools = _tools  # type: ignore[assignment]
    pull_calls: list[tuple[str, str, str, Any]] = []

    async def _cannot_pull(
        aid: str, server: str, tool: str, *, descriptor: Any = None
    ) -> bool:
        pull_calls.append((aid, server, tool, descriptor))
        return False

    wb.pull_tool = _cannot_pull  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        pulled = await wb.preload_open_tools("a1", limit=24)

    assert pull_calls == [
        ("a1", "microsoft-learn", "microsoft_docs_search", descriptor),
    ]
    assert pulled == []
    assert "none could be pulled" in caplog.text


# ---------------------------------------------------------------------------
# BF-751a: the silent outcomes were logged at DEBUG, so at the vessel's INFO
# level "no third silent outcome" was never actually met. A run that offered
# nothing still gave no reason why, and diagnosing it cost a restart and a
# guess.
# ---------------------------------------------------------------------------

def _wb(
    records: list[Any], *, store: Any | None = None,
    permissions: ToolPermissionStore | None = None,
) -> Any:
    from probos.cognitive.mcp_workbench import MCPWorkbench

    return MCPWorkbench(
        tool_registry=None,
        bridge=SimpleNamespace(get_client=lambda key: None),
        consensus_invoke=None,
        episode_writer=None,
        server_store=_Store(records) if store is None else store,
        perm_store=permissions,
        dept_grant_store=None,
        risk_store=None,
        ontology=None,
        agent_registry=None,
    )


def _record() -> Any:
    return SimpleNamespace(
        name="microsoft-learn", type="http", url=LEARN,
        enabled=True, default_risk="open", id="s1",
    )


@pytest.mark.asyncio
async def test_a_zero_limit_says_so_at_info(caplog) -> None:
    with caplog.at_level(logging.INFO):
        assert await _wb([_record()]).preload_open_tools("a1", limit=0) == []

    assert "limit=0" in caplog.text


@pytest.mark.asyncio
async def test_an_unwired_store_says_so_at_info(caplog) -> None:
    from probos.cognitive.mcp_workbench import MCPWorkbench

    wb = MCPWorkbench(
        tool_registry=None, bridge=None, consensus_invoke=None,
        episode_writer=None, server_store=None, perm_store=None,
        dept_grant_store=None, risk_store=None, ontology=None,
        agent_registry=None,
    )

    with caplog.at_level(logging.INFO):
        assert await wb.preload_open_tools("a1", limit=24) == []

    assert "server_store_wired=False" in caplog.text


@pytest.mark.asyncio
async def test_a_server_that_enumerates_nothing_names_that_cause(caplog) -> None:
    """The live shape: a server is enabled, egress or transport eats the tool
    list, and the agent is offered nothing. This is the message that would have
    saved a restart and two rounds of inference."""
    wb = _wb([_record()])

    async def _none(_rec: Any) -> list[dict[str, str]]:
        return []

    wb._enumerate_tools = _none  # type: ignore[assignment]

    with caplog.at_level(logging.INFO):
        assert await wb.preload_open_tools("a1", limit=24) == []

    assert "1 enabled server(s), 0 tool(s) enumerated" in caplog.text


@pytest.mark.asyncio
async def test_unauthorized_tools_are_counted_separately(caplog) -> None:
    """'Enumerated but unauthorized' and 'never enumerated' are different
    failures with different fixes; the message has to tell them apart."""
    permissions = ToolPermissionStore()
    assert permissions.get_active_grants_sync("a1") == []
    wb = _wb([_record()], permissions=permissions)

    async def _two(_rec: Any) -> list[dict[str, str]]:
        return [{"name": "a", "description": ""}, {"name": "b", "description": ""}]

    wb._enumerate_tools = _two  # type: ignore[assignment]

    with caplog.at_level(logging.INFO):
        assert await wb.preload_open_tools("a1", limit=24) == []

    assert "2 tool(s) enumerated, 2 unauthorized" in caplog.text


@pytest.mark.asyncio
async def test_a_ship_with_no_mcp_servers_stays_quiet(caplog) -> None:
    """Most vessels run none. Reporting 'offered nothing' every turn would be
    noise, and noise is how the real signal got missed in the first place."""
    with caplog.at_level(logging.INFO):
        assert await _wb([]).preload_open_tools("a1", limit=24) == []

    assert "AD-1239" not in caplog.text
