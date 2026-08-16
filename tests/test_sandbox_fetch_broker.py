"""AD-1221 (#1183): the sandbox fetch broker.

The load-bearing test here is `test_script_in_real_sandbox_fetches_through_ship`
— a real subprocess, the real generated helper, a real loopback socket. Every
other test proves one link; that one proves the chain. This repository's most
common defect is every link working and the chain dead, so a suite that only
unit-tests the broker would not be evidence that an agent can actually fetch.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import types
from pathlib import Path

import pytest

from probos.config import ExecutionConfig
from probos.execution.fetch_broker import SandboxFetchBroker
from probos.tools.code_execution_tool import CodeExecutionTool


# ── helpers ───────────────────────────────────────────────────────────────
def _speak(host: str, port: int, payload: dict) -> dict:
    """One request over the broker's line protocol, from a plain socket."""
    sock = socket.create_connection((host, port), timeout=10)
    try:
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    raw = b"".join(chunks)
    return json.loads(raw.decode("utf-8")) if raw else {}


async def _ask(host: str, port: int, payload: dict) -> dict:
    return await asyncio.get_running_loop().run_in_executor(
        None, _speak, host, port, payload
    )


class _RecordingFetcher:
    """Stands in for HttpFetchAgent. Records what the ship was asked to do so a
    test can assert the ship performed NO fetch, not merely that the caller got
    an error — the two are very different security claims."""

    def __init__(self, body: str = "hello world") -> None:
        self.calls: list[tuple[str, str]] = []
        self.caps: list[int | None] = []
        self._body = body

    async def fetch_governed(
        self, url: str, method: str = "GET", *, max_body_bytes: int | None = None
    ) -> dict:
        self.calls.append((url, method))
        self.caps.append(max_body_bytes)
        return {
            "success": True,
            "data": {
                "url": url,
                "status_code": 200,
                "headers": {},
                "body": self._body,
                "body_length": len(self._body),
                "truncated": False,
                "total_bytes": len(self._body),
            },
        }


def _runtime(cfg: ExecutionConfig, fetcher: object | None) -> types.SimpleNamespace:
    registry = types.SimpleNamespace(all=lambda: ([fetcher] if fetcher else []))
    return types.SimpleNamespace(
        config=types.SimpleNamespace(execution=cfg, dependency=None),
        registry=registry,
        artifact_store=None,
        attachment_store=None,
    )


# ── the broker itself ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_valid_token_reaches_the_governed_fetch() -> None:
    fetcher = _RecordingFetcher()
    broker = SandboxFetchBroker(fetch=fetcher.fetch_governed)
    host, port, token = await broker.start()
    try:
        reply = await _ask(
            host, port, {"token": token, "url": "https://example.com", "method": "GET"}
        )
    finally:
        await broker.stop()

    assert reply["data"]["body"] == "hello world"
    assert fetcher.calls == [("https://example.com", "GET")]
    assert broker.served == 1


@pytest.mark.asyncio
async def test_invalid_token_performs_no_fetch_at_all() -> None:
    """The claim is not "the caller got an error" — it is that the ship never
    made the request. Only the recorder can prove that."""
    fetcher = _RecordingFetcher()
    broker = SandboxFetchBroker(fetch=fetcher.fetch_governed)
    host, port, _token = await broker.start()
    try:
        reply = await _ask(
            host, port, {"token": "n" * 43, "url": "https://evil.test", "method": "GET"}
        )
    finally:
        await broker.stop()

    assert reply == {"error": "unauthorized"}
    assert fetcher.calls == []
    assert broker.served == 0


@pytest.mark.asyncio
async def test_missing_token_field_performs_no_fetch() -> None:
    fetcher = _RecordingFetcher()
    broker = SandboxFetchBroker(fetch=fetcher.fetch_governed)
    host, port, _ = await broker.start()
    try:
        reply = await _ask(host, port, {"url": "https://example.com"})
    finally:
        await broker.stop()
    assert reply == {"error": "unauthorized"}
    assert fetcher.calls == []


def _raw(host: str, port: int, payload: bytes) -> bytes:
    sock = socket.create_connection((host, port), timeout=10)
    try:
        sock.sendall(payload)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        sock.close()
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_malformed_request_is_refused_not_buffered() -> None:
    fetcher = _RecordingFetcher()
    broker = SandboxFetchBroker(fetch=fetcher.fetch_governed)
    host, port, _ = await broker.start()
    try:
        # Must go through an executor: the broker serves on THIS event loop, so
        # a blocking recv on the loop thread deadlocks until the socket timeout.
        raw = await asyncio.get_running_loop().run_in_executor(
            None, _raw, host, port, b"this is not json\n"
        )
    finally:
        await broker.stop()
    assert json.loads(raw.decode()) == {"error": "malformed request"}
    assert fetcher.calls == []


@pytest.mark.asyncio
async def test_token_is_rotated_on_stop() -> None:
    """A token captured from one run must not be replayable against a later
    broker that happens to reuse the port."""
    fetcher = _RecordingFetcher()
    broker = SandboxFetchBroker(fetch=fetcher.fetch_governed)
    _host, _port, token = await broker.start()
    await broker.stop()
    assert broker.token != token


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_safe_before_start() -> None:
    """The tool calls stop() in `finally`, which can run after a failed start."""
    broker = SandboxFetchBroker(fetch=_RecordingFetcher().fetch_governed)
    await broker.stop()
    await broker.stop()


@pytest.mark.asyncio
async def test_binds_loopback_only() -> None:
    broker = SandboxFetchBroker(fetch=_RecordingFetcher().fetch_governed)
    host, port, _ = await broker.start()
    try:
        assert host == "127.0.0.1"
        assert port > 0
    finally:
        await broker.stop()


@pytest.mark.asyncio
async def test_a_failing_fetch_does_not_kill_the_broker() -> None:
    async def boom(url: str, method: str) -> dict:
        raise RuntimeError("upstream exploded")

    broker = SandboxFetchBroker(fetch=boom)
    host, port, token = await broker.start()
    try:
        reply = await _ask(host, port, {"token": token, "url": "https://x.test"})
    finally:
        await broker.stop()
    assert reply == {"error": "broker failure"}


# ── config posture ────────────────────────────────────────────────────────
def test_capability_is_off_by_default() -> None:
    cfg = ExecutionConfig()
    assert cfg.fetch_broker_enabled is False


def test_broker_cap_exceeds_the_bus_cap() -> None:
    """The broker's body never crosses the intent bus, so the 1 MB cap that
    exists to protect the bus (#636) is not the constraint that applies. If
    these ever converge, the reason for the difference has been lost."""
    from probos.agents.http_fetch import HttpFetchAgent

    assert ExecutionConfig().fetch_broker_max_body_bytes > HttpFetchAgent.MAX_BODY_BYTES


def test_description_declares_the_posture_it_actually_has() -> None:
    """AD-1217's defect was a description asserting a boundary the code no
    longer had. Assert both directions so the same drift cannot recur.

    BF-781: the broker-OFF branch used to be asserted as
    ``"OUTBOUND NETWORK IS BLOCKED"``, and the broker-ON branch said "Direct
    network access is blocked here". Both were the very drift this test was
    written to catch -- it pinned the enforcement claim while checking that the
    posture switched. Updated to assert the switch AND that neither branch
    claims a block.
    """
    cfg = ExecutionConfig()
    tool = CodeExecutionTool(runtime=_runtime(cfg, None))

    off = tool.description
    assert "DO NOT FETCH URLS WITH run_python" in off
    assert "ship.fetch" not in off

    cfg.fetch_broker_enabled = True
    on = tool.description
    assert "ship.fetch" in on
    assert "DO NOT FETCH URLS WITH run_python" not in on

    # Neither posture may claim an enforced network boundary.
    for desc in (off, on):
        assert "OUTBOUND NETWORK IS BLOCKED" not in desc
        assert "network access is blocked" not in desc.lower()


def test_helper_must_not_shadow_the_installed_package() -> None:
    """The helper was originally named `probos.py`. It could never have worked:
    ProbOS is installed in the same interpreter as an editable install, which
    registers a `sys.meta_path` finder, and meta-path finders are consulted
    BEFORE `sys.path` — so `import probos` in the sandbox resolves to the real
    package and `probos.fetch` raises AttributeError. Pin the lesson."""
    from probos.execution.fetch_broker import SANDBOX_HELPER_FILENAME

    assert SANDBOX_HELPER_FILENAME != "probos.py"
    assert SANDBOX_HELPER_FILENAME.removesuffix(".py") not in sys.modules


# ── tool wiring ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_disabled_writes_no_helper_and_no_env(tmp_path: Path) -> None:
    cfg = ExecutionConfig()
    tool = CodeExecutionTool(runtime=_runtime(cfg, _RecordingFetcher()))
    env, broker = await tool._start_fetch_broker(cfg, tmp_path)
    assert env == {}
    assert broker is None
    assert not (tmp_path / "ship.py").exists()


@pytest.mark.asyncio
async def test_enabled_without_a_fetcher_degrades_rather_than_failing(
    tmp_path: Path,
) -> None:
    cfg = ExecutionConfig(fetch_broker_enabled=True)
    tool = CodeExecutionTool(runtime=_runtime(cfg, None))
    env, broker = await tool._start_fetch_broker(cfg, tmp_path)
    assert env == {}
    assert broker is None


@pytest.mark.asyncio
async def test_enabled_writes_the_helper_and_passes_credentials(
    tmp_path: Path,
) -> None:
    cfg = ExecutionConfig(fetch_broker_enabled=True)
    tool = CodeExecutionTool(runtime=_runtime(cfg, _RecordingFetcher()))
    env, broker = await tool._start_fetch_broker(cfg, tmp_path)
    try:
        assert (tmp_path / "ship.py").exists()
        assert set(env) == {
            "PROBOS_FETCH_HOST", "PROBOS_FETCH_PORT", "PROBOS_FETCH_TOKEN",
        }
        assert env["PROBOS_FETCH_HOST"] == "127.0.0.1"
    finally:
        if broker is not None:
            await broker.stop()


@pytest.mark.asyncio
async def test_configured_cap_reaches_the_governed_fetch(tmp_path: Path) -> None:
    fetcher = _RecordingFetcher()
    cfg = ExecutionConfig(fetch_broker_enabled=True, fetch_broker_max_body_bytes=4242)
    tool = CodeExecutionTool(runtime=_runtime(cfg, fetcher))
    env, broker = await tool._start_fetch_broker(cfg, tmp_path)
    assert broker is not None
    try:
        await _ask(
            env["PROBOS_FETCH_HOST"],
            int(env["PROBOS_FETCH_PORT"]),
            {"token": env["PROBOS_FETCH_TOKEN"], "url": "https://example.com"},
        )
    finally:
        await broker.stop()
    assert fetcher.caps == [4242]


# ── the crossing test ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_script_in_real_sandbox_fetches_through_ship(tmp_path: Path) -> None:
    """The whole point, end to end: a real Python subprocess, under the real
    sandbox, imports the real generated helper, opens a real socket, and gets
    the ship's fetch result back INSIDE the sandbox where it can be processed.

    This is the capability AD-1221 exists to provide. If it regresses, an agent
    is back to carrying every byte through its context window.
    """
    from probos.execution.isolation import ExecutionRequest, SubprocessSandbox

    fetcher = _RecordingFetcher(body="<html><title>Ship</title></html>")
    cfg = ExecutionConfig(fetch_broker_enabled=True)
    tool = CodeExecutionTool(runtime=_runtime(cfg, fetcher))

    workdir = tmp_path / "run"
    workdir.mkdir()
    env, broker = await tool._start_fetch_broker(cfg, workdir)
    assert broker is not None
    try:
        result = await SubprocessSandbox(scratch_root=str(tmp_path)).run(
            ExecutionRequest(
                code=(
                    "import ship\n"
                    "r = ship.fetch('https://example.com/big')\n"
                    # Prove the sandbox can REDUCE in place: it received the
                    # document and prints only the extracted answer.
                    "import re\n"
                    "print('TITLE=' + re.search(r'<title>(.*?)</title>', "
                    "r['body']).group(1))\n"
                    "print('STATUS=%d' % r['status_code'])\n"
                ),
                workdir=workdir,
                timeout_seconds=60,
                allow_network=False,
                env=env,
                import_workdir=True,
            )
        )
    finally:
        await broker.stop()

    assert result.success, result.stderr
    assert "TITLE=Ship" in result.stdout
    assert "STATUS=200" in result.stdout
    assert fetcher.calls == [("https://example.com/big", "GET")]


@pytest.mark.asyncio
async def test_agent_tracebacks_keep_the_agent_s_line_numbers(
    tmp_path: Path,
) -> None:
    """The launcher exists so the workdir can be importable WITHOUT prepending
    a prelude to the agent's source. A prelude would shift every line number,
    so a failure on the agent's line 3 would be reported as line 4 — a small
    lie in exactly the place an agent is trying to debug itself."""
    from probos.execution.isolation import ExecutionRequest, SubprocessSandbox

    workdir = tmp_path / "run"
    workdir.mkdir()
    result = await SubprocessSandbox(scratch_root=str(tmp_path)).run(
        ExecutionRequest(
            code="x = 1\ny = 2\nraise ValueError('boom')\n",
            workdir=workdir,
            timeout_seconds=60,
            allow_network=False,
            import_workdir=True,
        )
    )
    assert not result.success
    assert 'line 3' in result.stderr, result.stderr


@pytest.mark.asyncio
async def test_script_without_credentials_gets_an_honest_error(
    tmp_path: Path,
) -> None:
    """With the capability off, the helper is absent — but if a script somehow
    imports it, it must say the relay is unavailable rather than hang."""
    from probos.execution.fetch_broker import (
        SANDBOX_HELPER_FILENAME,
        SANDBOX_HELPER_SOURCE,
    )
    from probos.execution.isolation import ExecutionRequest, SubprocessSandbox

    workdir = tmp_path / "run"
    workdir.mkdir()
    (workdir / SANDBOX_HELPER_FILENAME).write_text(
        SANDBOX_HELPER_SOURCE, encoding="utf-8"
    )

    result = await SubprocessSandbox(scratch_root=str(tmp_path)).run(
        ExecutionRequest(
            code=(
                "import ship\n"
                "try:\n"
                "    ship.fetch('https://example.com')\n"
                "except ship.FetchError as e:\n"
                "    print('DECLINED=' + str(e))\n"
            ),
            workdir=workdir,
            timeout_seconds=60,
            allow_network=False,
            import_workdir=True,
        )
    )
    assert "DECLINED=" in result.stdout
    assert "not available" in result.stdout


def test_generated_scaffolding_is_not_offered_as_a_work_product() -> None:
    """`ship.py` and the launcher are machinery. If they leaked into artifact
    capture the Captain would be handed them as files the agent produced."""
    from probos.execution.fetch_broker import SANDBOX_HELPER_FILENAME
    from probos.tools.code_execution_tool import _GENERATED_NAMES

    assert SANDBOX_HELPER_FILENAME in _GENERATED_NAMES
    assert "_probos_launch.py" in _GENERATED_NAMES
    assert "script.py" in _GENERATED_NAMES
