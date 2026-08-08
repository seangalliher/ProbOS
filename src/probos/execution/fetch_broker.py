"""AD-1221 (#1183): a governed way for sandboxed code to fetch a URL.

The Captain asked that an agent reach the same productive ceiling as a
foreground coding agent (Design Principle 13). Measured on the same task — the
current version of the top 15 PyPI packages — a foreground agent fetched
17,341,659 bytes and put ~1,672 characters into its context, a 10,372x
reduction, because it fetched and extracted *in one process*. A ProbOS agent
could not: ``http_fetch`` has network and no compute, ``run_python`` has compute
and no network, so every byte had to transit the agent's context window to get
from one to the other. Every truncation defect of the week (BF-728, BF-729) is a
symptom of that single split.

This closes it **by adding a governed path, not by removing a control**
(DP-13(b)). The sandbox still gets no general network access; it gets a socket
to one loopback broker that performs the ordinary governed mesh fetch — SSRF
validation, per-domain rate limiting, audit — and hands the body back inside the
sandbox process. The agent then writes ordinary Python to extract what it needs.

Design notes, each a deliberate choice:

* **Per-execution, tool-owned — not an endpoint on the API.** The broker is
  started by :class:`CodeExecutionTool` for one run and closed in ``finally``.
  It therefore exists only while a script is running, adds no permanent public
  surface to the ship, and needs no knowledge of the API's port. The original
  sketch in #1183 proposed an API route; this is strictly smaller.

* **A raw TCP line protocol, not HTTP.** The helper the sandbox imports uses
  ``socket`` from the standard library. That means it needs no third-party
  package to be installed, and — load-bearing — a raw socket ignores the
  blackhole ``http_proxy`` variables the sandbox sets, so ``isolation.py``
  needs no change and the proxy deterrent stays exactly as it was for
  everything else.

* **The fetch callable is injected.** The broker knows nothing about
  ``HttpFetchAgent`` (Dependency Inversion), which is also what makes its
  governance testable: a test can prove the broker refuses to fetch without a
  valid token without standing up the mesh.

* **A byte cap distinct from the mesh one.** ``HttpFetchAgent.MAX_BODY_BYTES``
  is 1 MB because that body crosses the intent bus inline (BF-729, AD-731,
  the #636 OOM). A body returned through this broker never touches the bus or
  the message history — it goes to the sandbox's own memory — so the cap that
  defends the bus does not apply here. That is why this path may carry more,
  and saying so is the point: a limit should be a decision (DP-13(a)).
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from typing import Any, Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)

# A request line is {"token": ..., "url": ..., "method": ...}. Anything beyond
# this is malformed or hostile; refuse rather than buffer it.
_MAX_REQUEST_BYTES = 8 * 1024
_READ_TIMEOUT_SECONDS = 10.0


class GovernedFetch(Protocol):
    """The one capability the broker needs. Narrow by design (ISP): the broker
    must not be able to do anything to the mesh except ask for one URL."""

    async def __call__(self, url: str, method: str) -> dict[str, Any]: ...


class SandboxFetchBroker:
    """A loopback fetch relay that lives exactly as long as one sandbox run."""

    def __init__(
        self,
        *,
        fetch: GovernedFetch | Callable[[str, str], Awaitable[dict[str, Any]]],
        host: str = "127.0.0.1",
    ) -> None:
        self._fetch = fetch
        self._host = host
        self._token = secrets.token_urlsafe(32)
        self._server: asyncio.AbstractServer | None = None
        self._port: int | None = None
        self._served = 0

    @property
    def token(self) -> str:
        return self._token

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def served(self) -> int:
        """Requests answered. Lets a caller log what a run actually did."""
        return self._served

    async def start(self) -> tuple[str, int, str]:
        """Bind an ephemeral loopback port. Returns (host, port, token).

        Binding to ``127.0.0.1`` with port 0 is the whole isolation story at
        this layer: an ephemeral port on loopback, plus a token no other
        process was told, for the duration of one script.
        """
        self._server = await asyncio.start_server(
            self._handle, host=self._host, port=0
        )
        sock = self._server.sockets[0]
        self._port = int(sock.getsockname()[1])
        logger.info(
            "AD-1221: sandbox fetch broker listening on %s:%d for one execution",
            self._host, self._port,
        )
        return self._host, self._port, self._token

    async def stop(self) -> None:
        """Close the listener. Idempotent — the tool calls this in ``finally``,
        which can run after a failed start."""
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        try:
            await server.wait_closed()
        except Exception:  # noqa: BLE001 — shutting down; nothing to salvage
            logger.debug("AD-1221: broker close raised", exc_info=True)
        # Invalidate the token even though the listener is gone, so a captured
        # token cannot be replayed against a later broker that happens to land
        # on the same port.
        self._token = secrets.token_urlsafe(32)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            payload = await self._read_request(reader)
            if payload is None:
                await self._respond(writer, {"error": "malformed request"})
                return

            token = payload.get("token")
            # Constant-time: the token is the only thing standing between a
            # local process and the ship's fetch capability.
            if not isinstance(token, str) or not secrets.compare_digest(
                token, self._token
            ):
                logger.warning(
                    "AD-1221: sandbox fetch broker refused a request with an "
                    "invalid token; the fetch was not performed"
                )
                await self._respond(writer, {"error": "unauthorized"})
                return

            url = payload.get("url")
            if not isinstance(url, str) or not url:
                await self._respond(writer, {"error": "no url"})
                return
            method = payload.get("method")
            method = method if isinstance(method, str) and method else "GET"

            result = await self._fetch(url, method)
            self._served += 1
            await self._respond(writer, result)
        except Exception:  # noqa: BLE001 — a broker fault must not kill the run
            logger.warning(
                "AD-1221: sandbox fetch broker failed to serve a request; the "
                "script receives an error and continues", exc_info=True,
            )
            try:
                await self._respond(writer, {"error": "broker failure"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _read_request(
        self, reader: asyncio.StreamReader
    ) -> dict[str, Any] | None:
        try:
            line = await asyncio.wait_for(
                reader.readline(), timeout=_READ_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, ValueError):
            # ValueError = asyncio's own limit exceeded before our check.
            return None
        if not line or len(line) > _MAX_REQUEST_BYTES:
            return None
        try:
            payload = json.loads(line.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 — not JSON is just malformed
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    async def _respond(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        try:
            body = json.dumps(payload).encode("utf-8")
        except Exception:  # noqa: BLE001 — unserialisable result
            body = json.dumps({"error": "unserialisable result"}).encode("utf-8")
        writer.write(body)
        await writer.drain()
        # The client reads to EOF, so the half-close IS the framing.
        try:
            writer.write_eof()
        except Exception:  # noqa: BLE001 — some transports disallow it
            pass


# The helper the sandbox imports. Standard library only: the sandbox may have
# no third-party package installed, and a raw socket also sidesteps the
# blackhole proxy variables without needing them changed.
#
# NAMED `ship`, NOT `probos`, and that is load-bearing. ProbOS is installed in
# the same interpreter the sandbox runs, as an EDITABLE install — which
# registers a finder on ``sys.meta_path``. Meta-path finders are consulted
# BEFORE ``sys.path``, so a `probos.py` sitting in the working directory does
# not win: `import probos` resolves to the real package and
# ``probos.fetch`` raises AttributeError. Caught by the crossing test, which
# is exactly the kind of thing only a real subprocess can catch.
SANDBOX_HELPER_FILENAME = "ship.py"

SANDBOX_HELPER_SOURCE = '''"""ProbOS sandbox helpers (AD-1221). Generated per run — do not edit."""

import json
import os
import socket

__all__ = ["fetch", "FetchError"]


class FetchError(RuntimeError):
    """The ship declined or could not complete the fetch."""


def fetch(url, method="GET"):
    """Fetch a URL through the ship's governed HTTP path.

    Returns a dict with `status_code`, `headers`, `body`, `body_length`,
    `truncated` and `total_bytes`. Raises FetchError if the ship declined.

    The request is performed by the ship, not by this process: it passes the
    same SSRF checks, per-domain rate limiting and audit as any other fetch.
    The response comes back here, inside the sandbox, so a large document can
    be parsed and reduced locally instead of being carried through the
    conversation.
    """
    host = os.environ.get("PROBOS_FETCH_HOST")
    port = os.environ.get("PROBOS_FETCH_PORT")
    token = os.environ.get("PROBOS_FETCH_TOKEN")
    if not (host and port and token):
        raise FetchError(
            "the ship's fetch relay is not available in this run"
        )

    request = json.dumps(
        {"token": token, "url": url, "method": method}
    ).encode("utf-8") + b"\\n"

    with socket.create_connection((host, int(port)), timeout=120) as sock:
        sock.sendall(request)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    raw = b"".join(chunks)
    if not raw:
        raise FetchError("the ship's fetch relay returned nothing")
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        raise FetchError("the ship's fetch relay returned a malformed reply")

    if isinstance(payload, dict) and payload.get("error"):
        raise FetchError(str(payload["error"]))
    if isinstance(payload, dict) and payload.get("success") is False:
        raise FetchError(str(payload.get("error") or "fetch failed"))
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload
'''
