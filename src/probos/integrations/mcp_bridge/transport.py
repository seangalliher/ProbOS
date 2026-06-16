"""AD-1014: pluggable MCP transports — HTTP (byte-identical) and stdio/subprocess.

The transport seam lives *inside* ``MCPClient``: the client builds the JSON-RPC
payload and delegates the wire I/O to a ``Transport``. Transports are
**event-free** — they raise ``MCPProtocolError(reason=…)`` on any wire failure
and the owning layer emits the ``MCP_BRIDGE_*`` events (``MCPClient._call`` for
request-time failures, ``MCPBridge.register_stdio_server`` for registration-time
failures). This keeps a single emission site per lifecycle phase and the
``Transport`` interface free of ``EventType`` / egress / request-header concerns.

The ``HttpTransport`` lifts the wire body of the pre-AD-1014 ``MCPClient._call``
verbatim (egress gate → header build → ``httpx.post`` → response-header capture →
status check → ``response.json()``), including the request-direction
``Mcp-Session-Id`` injection — so the HTTP path stays byte-identical.

The ``StdioTransport`` spawns ``command + args`` as a subprocess and speaks
JSON-RPC over stdin/stdout as newline-delimited JSON (NDJSON), per the MCP stdio
transport spec. stderr is drained to ``logger.debug`` on a held task ref.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

import httpx

from probos.integrations.mcp_bridge.client import MCPProtocolError

logger = logging.getLogger(__name__)


@runtime_checkable
class Transport(Protocol):
    """Narrow, event-free wire seam for one MCP server connection.

    Implementations send a single JSON-RPC request and return the parsed
    envelope (``{jsonrpc, id, result|error}``). Any wire failure raises
    ``MCPProtocolError(reason=…)``; the caller emits the event. ``last_metadata``
    carries response-direction metadata only (HTTP exposes the lower-cased
    response headers so ``initialize()`` can read ``mcp-session-id``).
    """

    last_metadata: dict[str, str]

    async def start(self) -> None:
        """Bring the transport up (HTTP: no-op; stdio: spawn the subprocess)."""
        ...

    async def request(self, payload: dict[str, Any]) -> dict:
        """Send one JSON-RPC request; return the parsed envelope dict."""
        ...

    async def close(self) -> None:
        """Tear the transport down (HTTP: close client; stdio: kill subprocess)."""
        ...


class HttpTransport:
    """JSON-RPC-over-Streamable-HTTP wire body (lifted from ``MCPClient._call``).

    Byte-identical to the pre-AD-1014 HTTP path: egress gate on ``server_url``,
    header build (``Content-Type`` / ``Accept`` / base headers /
    request-direction ``Mcp-Session-Id``), ``httpx.post`` with
    ``json.dumps(payload)``, response-header capture, status-≥400 check, and
    ``response.json()``. The request-direction session id is **self-managed**:
    seeded from ``initial_session_id``, updated from each response's
    ``mcp-session-id`` header, and injected on every request when non-empty.
    """

    def __init__(
        self,
        *,
        server_url: str,
        base_headers: dict[str, str],
        egress_policy: Any | None = None,
        timeout: float = 30.0,
        initial_session_id: str = "",
    ) -> None:
        self._server_url = server_url
        self._base_headers = dict(base_headers or {})
        self._egress_policy = egress_policy
        self._timeout = timeout
        # Request-direction session id (transport-internal — NOT surfaced via
        # last_metadata, which is response-direction only).
        self._session_id = initial_session_id or ""
        self._http: httpx.AsyncClient | None = httpx.AsyncClient(timeout=timeout)
        self.last_metadata: dict[str, str] = {}

    async def start(self) -> None:
        # httpx client is created in __init__ (exactly as the legacy client did);
        # nothing to bring up here.
        return None

    async def request(self, payload: dict[str, Any]) -> dict:
        url = self._server_url
        # Egress policy gate (HTTP-only; AD-456 integration; convention #3).
        policy = self._egress_policy
        if policy is not None and not policy.is_allowed(url):
            raise MCPProtocolError(f"egress denied for {url}", reason="egress_blocked")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._base_headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        http = self._http
        if http is None:
            raise MCPProtocolError("client closed", reason="client_closed")

        try:
            response = await http.post(url, content=json.dumps(payload), headers=headers)
        except httpx.HTTPError as exc:
            raise MCPProtocolError(
                f"transport error: {exc}", reason="transport_error",
            ) from exc

        # Capture response headers (response-direction metadata) and self-manage
        # the request-direction session id off the same header.
        self.last_metadata = {k.lower(): v for k, v in response.headers.items()}
        new_sid = self.last_metadata.get("mcp-session-id", "")
        if new_sid:
            self._session_id = new_sid

        if response.status_code >= 400:
            raise MCPProtocolError(
                f"HTTP {response.status_code} from {url}", reason="http_error",
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(f"bad JSON from {url}", reason="bad_json") from exc

    async def close(self) -> None:
        http = self._http
        if http is not None:
            await http.aclose()
        self._http = None


class StdioTransport:
    """JSON-RPC-over-stdio subprocess transport (MCP stdio spec).

    Spawns ``command + args`` and exchanges newline-delimited JSON over the
    subprocess's stdin/stdout. stderr is drained to ``logger.debug`` on a held
    task ref. ``request`` is **single-flight** (one outstanding request per
    client; the bridge awaits ``invoke`` serially) — a concurrent read-loop with
    id-keyed futures and server→client request handling is deferred to AD-1015.

    The transport is event-free: it raises ``MCPProtocolError(reason=…)``;
    spawn-time failures are emitted by the bridge, request-time failures by
    ``MCPClient._call``.
    """

    def __init__(
        self,
        *,
        command: str,
        args: list[str],
        env: dict[str, str],
        cwd: str,
        timeout: float,
        name: str = "",
    ) -> None:
        self._command = command
        self._args = list(args or [])
        self._env = dict(env or {})
        self._cwd = cwd
        self._timeout = timeout
        self._name = name or command
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.last_metadata: dict[str, str] = {}

    async def start(self) -> None:
        env = {**os.environ, **self._env} if self._env else None
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self._cwd or None,
            )
        except OSError as exc:
            # FileNotFoundError (command missing) is an OSError subclass.
            raise MCPProtocolError(
                f"spawn failed: {self._command}", reason="spawn_failed",
            ) from exc
        # Hold the drain task ref (async hygiene: create_task, not ensure_future).
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                logger.debug(
                    "AD-1014 stdio[%s] stderr: %s",
                    self._name,
                    line.decode("utf-8", "replace").rstrip(),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "AD-1014 stdio[%s] stderr drain ended unexpectedly",
                self._name,
                exc_info=True,
            )

    async def request(self, payload: dict[str, Any]) -> dict:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise MCPProtocolError("stdio pipe closed", reason="closed_pipe")

        try:
            proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            raise MCPProtocolError(
                f"stdio write failed: {exc}", reason="closed_pipe",
            ) from exc

        want_id = payload.get("id")
        try:
            return await asyncio.wait_for(
                self._read_matching(want_id), timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise MCPProtocolError(
                f"stdio timeout after {self._timeout}s", reason="timeout",
            ) from exc

    async def _read_matching(self, want_id: Any) -> dict:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise MCPProtocolError("stdio pipe closed", reason="closed_pipe")
        stdout = proc.stdout
        while True:
            line = await stdout.readline()
            if not line:
                # EOF — the subprocess closed stdout (crashed or exited).
                raise MCPProtocolError("stdio pipe closed", reason="closed_pipe")
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                envelope = json.loads(text)
            except json.JSONDecodeError as exc:
                raise MCPProtocolError(
                    f"bad JSON from stdio: {exc}", reason="bad_json",
                ) from exc
            if not isinstance(envelope, dict):
                # JSON-RPC envelopes are objects; skip stray non-objects.
                continue
            # Skip spec-legal notifications/* (no id) and any non-matching id —
            # keep reading until the response for *this* request arrives.
            if envelope.get("id") != want_id:
                continue
            return envelope

    async def close(self) -> None:
        proc = self._proc
        if proc is not None:
            # Shutdown order per spec: close stdin, terminate, kill-fallback.
            try:
                if proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.close()
            except Exception:
                logger.debug(
                    "AD-1014 stdio[%s] stdin close failed", self._name, exc_info=True,
                )
            try:
                proc.terminate()
            except ProcessLookupError:
                pass  # already exited
            except Exception:
                logger.debug(
                    "AD-1014 stdio[%s] terminate failed", self._name, exc_info=True,
                )
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

        task = self._stderr_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug(
                    "AD-1014 stdio[%s] stderr task cleanup failed",
                    self._name,
                    exc_info=True,
                )
        self._stderr_task = None
