"""BF-884 (#1462): a taken A2A or MCP server port must not end the ProbOS process.

uvicorn 0.46 answers a port it cannot bind by calling ``sys.exit(1)`` in ``Server.startup``, inside the task
``start()`` creates. The ``SystemExit`` left the event loop and ended the whole process, so the AD-480d / AD-480a
``except OSError`` around ``create_task`` never ran. Both servers now serve through ``serve_unless_bind_fails``:
that exit is logged with the port and stops only the server. It is told apart by two facts uvicorn sets: it is
raised before ``started`` is set, while the ``OSError`` is handled (``__context__``). An exit with the same code
for another reason (an app uvicorn cannot load), an exit after startup and any other exception still propagate.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

import probos
from probos.config import FederationA2AConfig, FederationMCPServerConfig
from probos.federation.a2a.server import FederationA2AServer
from probos.federation.mcp_server import FederationMCPServer, serve_unless_bind_fails

_SRC = Path(probos.__file__).resolve().parents[1]
_TOKEN = "k" * 40  # synthetic
_LOGGER = {"a2a": "probos.federation.a2a.server", "mcp": "probos.federation.mcp_server"}
_PREFIX = {"a2a": "AD-480d: A2A server bind failed", "mcp": "AD-480a: MCP server bind failed"}
_PROBE = logging.getLogger("tests.bf884")
_MESSAGE = "probe bind failed (port %d): %s"
# The production shape (finalize.py): build the server, await start(), keep running; then stop and return.
_CHILD = """
import asyncio, json, logging, sys
from types import SimpleNamespace
logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
import probos
from probos.config import FederationA2AConfig, FederationMCPServerConfig
from probos.federation.a2a.server import FederationA2AServer
from probos.federation.mcp_server import FederationMCPServer


async def main(kind, port):
    settings = {"enabled": True, "auth_token": "k" * 40, "bind_host": "127.0.0.1", "bind_port": port}
    if kind == "a2a":
        server = FederationA2AServer(runtime=SimpleNamespace(), config=FederationA2AConfig(**settings))
    else:
        server = FederationMCPServer(runtime=SimpleNamespace(), config=FederationMCPServerConfig(**settings))
    await server.start()
    for _ in range(200):
        if not server.is_running:
            break
        await asyncio.sleep(0.05)
    running = server.is_running
    await server.stop()
    print(json.dumps({"probos": probos.__file__, "running": running}), flush=True)


asyncio.run(main(sys.argv[1], int(sys.argv[2])))
print("ALIVE", flush=True)
"""


@pytest.fixture
def taken_port() -> Iterator[int]:
    """A 127.0.0.1 port another socket listens on for the whole test."""
    with socket.create_server(("127.0.0.1", 0)) as squatter:
        yield int(squatter.getsockname()[1])


def _server(kind: str, port: int) -> FederationA2AServer | FederationMCPServer:
    settings: dict[str, Any] = {"enabled": True, "auth_token": _TOKEN, "bind_host": "127.0.0.1", "bind_port": port}
    if kind == "a2a":
        return FederationA2AServer(runtime=SimpleNamespace(), config=FederationA2AConfig(**settings))
    return FederationMCPServer(runtime=SimpleNamespace(), config=FederationMCPServerConfig(**settings))


async def _until_stopped(server: FederationA2AServer | FederationMCPServer) -> bool:
    """Wait up to 10 s for the serving task to end; ``is_running`` then."""
    for _ in range(200):
        if not server.is_running:
            break
        await asyncio.sleep(0.05)
    return server.is_running


class _Serving:
    """Stands in for ``uvicorn.Server``: ``serve()`` raises ``error`` while it handles an ``OSError``."""

    def __init__(self, error: BaseException, *, started: bool) -> None:
        self.started = started
        self._error = error

    async def serve(self) -> None:
        try:
            raise OSError(98, "Address already in use")
        except OSError:
            raise self._error  # its __context__ is the OSError, as uvicorn's exit's is


async def _never_called(scope: dict[str, Any], receive: Any, send: Any) -> None:
    raise AssertionError("nothing connects in BF-884's tests")


# ---------------------------------------------------------------- the real failure, in a whole process


@pytest.mark.parametrize("kind", ["a2a", "mcp"])
def test_a_taken_port_leaves_the_process_running(kind: str, taken_port: int) -> None:
    env = {**os.environ, "PYTHONPATH": str(_SRC), "PYTHONIOENCODING": "utf-8"}
    child = subprocess.run(
        [sys.executable, "-P", "-c", _CHILD, kind, str(taken_port)], env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, check=False, stdin=subprocess.DEVNULL,
    )
    assert child.returncode == 0, child.stderr[-3000:]
    *_, report, alive = child.stdout.splitlines()
    assert alive == "ALIVE"
    assert json.loads(report)["running"] is False
    assert Path(json.loads(report)["probos"]).resolve().is_relative_to(_SRC)  # the premise: it ran this checkout
    assert f"{_LOGGER[kind]} WARNING {_PREFIX[kind]} (port {taken_port}): " in child.stderr


# ---------------------------------------------------------------- each server, in this process


@pytest.mark.parametrize("kind", ["a2a", "mcp"])
def test_a_taken_port_is_warned_and_stops_only_that_server(
    kind: str, taken_port: int, caplog: pytest.LogCaptureFixture,
) -> None:
    server = _server(kind, taken_port)

    async def scenario() -> tuple[bool, bool]:
        await server.start()
        running = await _until_stopped(server)
        await server.stop()  # safe on a server whose bind failed
        return running, server.is_running

    with caplog.at_level(logging.WARNING, logger=_LOGGER[kind]):
        assert asyncio.run(scenario()) == (False, False)
    (warning,) = [r.getMessage() for r in caplog.records if r.name == _LOGGER[kind] and r.levelno == logging.WARNING]
    assert warning.startswith(f"{_PREFIX[kind]} (port {taken_port}): ")


@pytest.mark.parametrize("kind", ["a2a", "mcp"])
def test_an_exit_that_is_not_the_bind_failure_still_ends_the_loop(
    kind: str, taken_port: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exits(self: uvicorn.Server, sockets: Any = None) -> None:  # in place of the bind: no socket error
        raise SystemExit(3)

    monkeypatch.setattr(uvicorn.Server, "startup", exits)
    server = _server(kind, taken_port)

    async def scenario() -> None:
        await server.start()
        await _until_stopped(server)

    with pytest.raises(SystemExit) as raised:
        asyncio.run(scenario())
    assert raised.value.code == 3


# ---------------------------------------------------------------- serve_unless_bind_fails


async def test_an_exit_uvicorn_makes_for_another_reason_propagates(
    taken_port: int, caplog: pytest.LogCaptureFixture,
) -> None:
    config = uvicorn.Config("bf884-not-an-app", host="127.0.0.1", port=taken_port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    with caplog.at_level(logging.WARNING, logger=_PROBE.name), pytest.raises(SystemExit) as raised:
        await serve_unless_bind_fails(server, port=taken_port, log=_PROBE, message=_MESSAGE)
    assert (raised.value.code, server.started) == (1, False)  # the premise: the bind failure's code and timing
    assert not isinstance(raised.value.__context__, OSError)
    assert [r for r in caplog.records if r.name == _PROBE.name] == []


async def test_an_exit_after_startup_propagates_while_a_socket_error_is_handled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exit_request = SystemExit(1)
    with caplog.at_level(logging.WARNING, logger=_PROBE.name), pytest.raises(SystemExit) as raised:
        await serve_unless_bind_fails(_Serving(exit_request, started=True), port=1, log=_PROBE, message=_MESSAGE)
    assert raised.value is exit_request and isinstance(exit_request.__context__, OSError)
    assert [r for r in caplog.records if r.name == _PROBE.name] == []


async def test_only_a_system_exit_is_ever_absorbed() -> None:
    error = RuntimeError("not an exit")
    with pytest.raises(RuntimeError) as raised:
        await serve_unless_bind_fails(_Serving(error, started=False), port=1, log=_PROBE, message=_MESSAGE)
    assert raised.value is error and isinstance(error.__context__, OSError)


async def test_a_server_that_binds_returns_when_asked_to_stop(caplog: pytest.LogCaptureFixture) -> None:
    server = uvicorn.Server(uvicorn.Config(_never_called, host="127.0.0.1", port=0, log_level="warning", lifespan="off"))
    server.should_exit = True  # bind, then stop at once
    with caplog.at_level(logging.WARNING, logger=_PROBE.name):
        assert await serve_unless_bind_fails(server, port=0, log=_PROBE, message=_MESSAGE) is None
    assert server.started is True
    assert [r for r in caplog.records if r.name == _PROBE.name] == []
