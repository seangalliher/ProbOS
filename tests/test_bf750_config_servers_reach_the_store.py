"""BF-750: a config-declared MCP server must reach the store agents read.

On 2026-08-11 a counselor asked a documentation question drove four Chromium
instances at a search engine while a ``learn.microsoft.com`` MCP server sat
"connected". AD-1239 fixed the tool descriptions, correctly — but the
descriptions were never the binding constraint.

The live vessel showed why. ``mcp_servers.db`` held **zero rows**, while the
boot log said ``MCPBridge wired (1 server(s) preregistered)``. Both seeding
arrows in ``startup/finalize.py`` pointed at the bridge:

    config -> bridge     (for srv in config.mcp.servers: register_server(...))
    store  -> bridge     (for rec in store.list_sync(): register_server(...))

and nothing ever wrote ``config -> store``. But the bridge is not what agents
read. ``MCPWorkbench.find_mcp_tool``, ``preload_open_tools`` and
``enabled_server_names`` all iterate the STORE. An empty store returns nothing,
for every agent, always — so a server the operator explicitly declared was
registered, reachable by direct bridge call, and invisible to the entire crew.

Same shape as BF-744, BF-746 and BF-747: code declaring a property it does not
provide. The ``system.yaml`` comment said config servers "register FIRST at boot
and survive a fresh DB", which was true of the bridge and false of everything an
agent could reach.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from probos.integrations.mcp_bridge.store import (
    McpServerRecord,
    McpServerStore,
    derive_server_name,
)
from probos.startup.finalize import _seed_config_mcp_servers


class _Cfg:
    """Only the shape the seeder reads."""

    def __init__(
        self, servers: list[Any], *, command_allowlist: list[str] | None = None
    ) -> None:
        self.mcp = type(
            "_Mcp",
            (),
            {
                "servers": servers,
                "command_allowlist": command_allowlist or ["uvx", "npx", "python"],
            },
        )()


class _Srv:
    def __init__(
        self, *, type: str = "http", url: str = "", command: str = "",
        args: list[str] | None = None, env: dict | None = None, cwd: str = "",
        headers: dict | None = None, timeout_seconds: float | None = None,
        name: str = "",
    ) -> None:
        self.type = type
        self.url = url
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.headers = headers or {}
        self.timeout_seconds = timeout_seconds
        self.name = name


@pytest.fixture
async def store(tmp_path):
    s = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await s.start()
    yield s
    await s.stop()


_LEARN = "https://learn.microsoft.com/api/mcp"


# ---------------------------------------------------------------------------
# The defect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_configured_server_reaches_the_store(store) -> None:
    """The live vessel's exact configuration: one HTTP server, empty store."""
    assert store.list_sync() == []

    added = await _seed_config_mcp_servers(_Cfg([_Srv(url=_LEARN)]), store)

    assert added == 1
    assert [r.url for r in store.list_sync()] == [_LEARN]


@pytest.mark.asyncio
async def test_the_seeded_row_is_what_the_workbench_can_use(store) -> None:
    """Reaching the store is not enough: the row must be enabled and typed, or
    every discovery path skips it anyway."""
    await _seed_config_mcp_servers(_Cfg([_Srv(url=_LEARN)]), store)

    rec = store.list_sync()[0]

    assert rec.enabled is True
    assert rec.type == "http"
    assert rec.name == "learn-microsoft-com-api-mcp"


@pytest.mark.asyncio
async def test_a_stdio_server_reaches_the_store_too(store) -> None:
    added = await _seed_config_mcp_servers(
        _Cfg([_Srv(type="stdio", command="uvx", args=["a"])]), store
    )

    assert added == 1
    rec = store.list_sync()[0]
    assert rec.name == "uvx"
    assert rec.args == ["a"]


@pytest.mark.asyncio
async def test_a_stdio_command_outside_the_allowlist_is_refused(
    store, caplog
) -> None:
    """``McpServerStore.create`` checks only name uniqueness -- the command
    allowlist lives in ``validate_record``, which until BF-750 only the CRUD
    router called. The config path must clear the same gate."""
    with caplog.at_level(logging.WARNING):
        added = await _seed_config_mcp_servers(
            _Cfg([_Srv(type="stdio", command="curl")], command_allowlist=["uvx"]),
            store,
        )

    assert added == 0
    assert store.list_sync() == []
    assert "BF-750" in caplog.text


# ---------------------------------------------------------------------------
# Seed-if-absent: the store is the Captain's surface
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_seeding_twice_adds_one_row(store) -> None:
    """Every boot runs this. It must not grow the store."""
    cfg = _Cfg([_Srv(url=_LEARN)])

    assert await _seed_config_mcp_servers(cfg, store) == 1
    assert await _seed_config_mcp_servers(cfg, store) == 0
    assert len(store.list_sync()) == 1


@pytest.mark.asyncio
async def test_a_captain_edit_survives_the_next_boot(store) -> None:
    """The store is runtime-mutable. A Captain who disabled a server, or
    re-tiered its risk, must not have that undone by a reboot."""
    await _seed_config_mcp_servers(_Cfg([_Srv(url=_LEARN)]), store)
    rec = store.list_sync()[0]
    await store.update(rec.id, enabled=False, default_risk="consensus")

    await _seed_config_mcp_servers(_Cfg([_Srv(url=_LEARN)]), store)

    after = store.list_sync()[0]
    assert after.enabled is False
    assert after.default_risk == "consensus"


# ---------------------------------------------------------------------------
# The name is load-bearing
# ---------------------------------------------------------------------------

def test_the_derived_name_is_stable_across_boots() -> None:
    """Grants are keyed mcp:{server} and mcp:{server}:{tool}. A name that
    changed between boots would silently revoke every grant issued against it."""
    first = derive_server_name(server_type="http", url=_LEARN)
    second = derive_server_name(server_type="http", url=_LEARN)

    assert first == second == "learn-microsoft-com-api-mcp"


def test_two_servers_on_one_host_get_different_names() -> None:
    """Deriving from the host alone would collide, and the second server would
    be silently dropped as a duplicate."""
    a = derive_server_name(server_type="http", url="https://example.com/api/one")
    b = derive_server_name(server_type="http", url="https://example.com/api/two")

    assert a != b


def test_the_derived_name_is_legal_for_the_store() -> None:
    """The store enforces ^[a-z0-9][a-z0-9-]*$; an illegal name would make
    create() raise on every boot."""
    import re

    from probos.integrations.mcp_bridge.store import _NAME_RE

    for url in (
        _LEARN,
        "https://EXAMPLE.com:8443/a_b/c.d",
        "http://127.0.0.1:9000/mcp",
    ):
        name = derive_server_name(server_type="http", url=url)
        assert re.match(_NAME_RE, name), f"{url!r} derived illegal name {name!r}"


def test_an_operator_supplied_name_wins() -> None:
    """The readable alternative to learn-microsoft-com-api-mcp."""
    assert derive_server_name(server_type="http", url=_LEARN) != "microsoft-learn"


@pytest.mark.asyncio
async def test_a_configured_name_is_used_verbatim(store) -> None:
    await _seed_config_mcp_servers(
        _Cfg([_Srv(url=_LEARN, name="microsoft-learn")]), store
    )

    assert store.list_sync()[0].name == "microsoft-learn"


def test_a_name_that_cannot_be_derived_is_empty_not_invented() -> None:
    """Inventing one would produce a different name next boot and orphan the
    grants issued against the last one.

    ``urlparse("not a url")`` yields no hostname and a path of the whole string,
    which slugs cleanly to ``not-a-url`` -- a legal name for a junk row that no
    bridge call can ever reach. Requiring a hostname is what stops that.
    """
    assert derive_server_name(server_type="http", url="not a url") == ""
    assert derive_server_name(server_type="http", url="") == ""
    assert derive_server_name(server_type="stdio", command="") == ""


# ---------------------------------------------------------------------------
# Honest degrade: a bad entry must not stop the boot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_unnameable_server_is_skipped_and_reported(
    store, caplog
) -> None:
    with caplog.at_level(logging.WARNING):
        added = await _seed_config_mcp_servers(
            _Cfg([_Srv(url="not a url"), _Srv(url=_LEARN)]), store
        )

    assert added == 1
    assert "BF-750" in caplog.text
    assert [r.url for r in store.list_sync()] == [_LEARN]


@pytest.mark.asyncio
async def test_a_credential_bearing_server_is_refused_without_stopping_the_boot(
    store, caplog
) -> None:
    """The secret-guard refuses an Authorization header by design -- the secret
    belongs in the credential vault, not a config file.

    This is the one that mattered most. ``create()`` applies no secret-guard at
    all (only name uniqueness), so seeding straight into it would have written
    ``Authorization: Bearer ...`` from system.yaml into mcp_servers.db in
    plaintext -- a security regression introduced BY the fix. The refusal must
    also degrade rather than crash: the bridge still holds the registration.
    """
    with caplog.at_level(logging.WARNING):
        added = await _seed_config_mcp_servers(
            _Cfg([
                _Srv(url="https://private.test/mcp",
                     headers={"Authorization": "Bearer abc"}),
                _Srv(url=_LEARN),
            ]),
            store,
        )

    assert added == 1
    assert "BF-750" in caplog.text
    assert [r.url for r in store.list_sync()] == [_LEARN]


@pytest.mark.asyncio
async def test_no_secret_reaches_the_database(store, tmp_path) -> None:
    """Stated as bytes on disk, not as a refusal count.

    The ``store`` fixture writes to ``tmp_path / "srv.db"``; this reads that same
    file back raw rather than trusting the store's own view of itself.
    """
    await _seed_config_mcp_servers(
        _Cfg([_Srv(url="https://private.test/mcp",
                   headers={"Authorization": "Bearer s3cret"})]),
        store,
    )

    db = tmp_path / "srv.db"
    assert db.is_file(), "the fixture's database is not where this test expects it"
    assert b"s3cret" not in db.read_bytes()
    assert store.list_sync() == []


@pytest.mark.asyncio
async def test_no_configured_servers_is_a_no_op(store) -> None:
    assert await _seed_config_mcp_servers(_Cfg([]), store) == 0
    assert store.list_sync() == []
