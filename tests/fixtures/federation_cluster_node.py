"""AD-1198 (#1135): one ProbOS node as a real process, for the two-node cluster gate.

Run as a script by ``tests/fixtures/federation_cluster.py`` (the parent harness), never imported by a test::

    python -X utf8 -u federation_cluster_node.py <config.yaml> <data_dir> <control_port> <name> [<api_port>]

The parent builds the environment: ``PYTHONPATH`` names the worktree's ``src``, so this script edits no
``sys.path``; stdin is DEVNULL (a pipe there hung the knowledge store's git flush on shutdown, probe N r2).
On Windows the selector loop is installed first (AD-108): zmq.asyncio hangs on the Proactor loop (probe Z0p).

The node connects to the parent's 127.0.0.1 control socket and speaks JSON lines, each
``{"kind": ..., "node": <name>, ...}``. It emits ``hello``, boots ``ProbOSRuntime`` with an injected
``MockLLMClient`` and emits ``ready`` (or ``failed`` if the start raised), then answers the parent's ops --
``forward`` (``forwarded``), ``status`` (``status``), ``rotate`` (``rotated``), ``put_attachment`` (``put``),
``has_attachment`` (``has``), ``a2a_post`` (``a2a``: an A2A request signed with this node's peer requests and
POSTed, AD-1198 slice 3b), ``a2a_callers`` (``a2a_callers``), ``transfer`` (``transferred``: this node's first crew
member by callsign, transferred with a certificate and its chain through ``FederationBridge.request_transfer``, AD-1198
slice 2a), ``foreign`` (``foreign``: what this node's identity registry holds for a transferred agent) and ``slot``
(``slotted``: a slot given to a crew member, AD-1198 slice 2b-iii); an op that fails is answered ``error`` -- until
``stop`` or until the
control socket closes (the parent is gone), and then stops the runtime and emits ``stopped``. Given an
``<api_port>`` (AD-1198 slice 3a), the node also serves the production main API (``create_app(runtime)``)
with uvicorn on 127.0.0.1 before ``ready`` and stops it before the runtime. After ``main`` returns a
faulthandler watchdog dumps every stack into the run log and exits 1 if anything keeps the interpreter alive
(the #1455 convention): a clean exit is 0.

Import-safe: everything runs only when this file is run as a script.
"""

from __future__ import annotations

import asyncio
import faulthandler
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_STOP_WATCHDOG_S = 60  # runtime.stop() took 3.2 s in probe N3
_EXIT_WATCHDOG_S = 30  # after main returns
_API_START_S = 30  # create_app and uvicorn were ready in 2.8-3.8 s per node under load (probe P4)
_API_STOP_S = 15


async def _key_fields(binding: Any) -> dict[str, Any]:
    """The ship key's public status: ``key_status``, ``did``, ``kid``, ``public_key`` (the active key's), ``key_seq``."""
    if binding is None:
        return {"key_status": None, "did": None, "kid": None, "public_key": None, "key_seq": None}
    status = await binding.status()
    kid = status.get("active_kid")
    public_key = next((key.get("public_key") for key in status.get("keys", []) if key.get("kid") == kid), None)
    return {
        "key_status": status.get("status"), "did": status.get("did"), "kid": kid, "public_key": public_key,
        "key_seq": status.get("seq"),
    }


async def _answer(command: dict[str, Any], runtime: Any) -> tuple[str, dict[str, Any]]:
    """The event that answers one op."""
    from probos.types import IntentMessage

    bridge = runtime.federation_bridge
    binding = runtime.identity_key_binding
    op = command.get("op")
    if op == "forward":
        began = time.monotonic()
        outcome = await asyncio.wait_for(
            bridge.forward_intent(IntentMessage(intent=command["intent"], params=command.get("params", {}))),
            timeout=float(command.get("timeout", 30)),
        )
        return "forwarded", {
            "seconds": round(time.monotonic() - began, 2),
            "results": [{"success": result.success, "result": result.result, "error": result.error} for result in outcome],
            "attempted": outcome.peers_attempted, "answered": outcome.peers_answered,
            "admitted": outcome.peers_admitted, "unknown": outcome.peers_unknown,
        }
    if op == "status":
        federation = None if bridge is None else bridge.federation_status()
        return "status", {"federation": federation, **await _key_fields(binding)}
    if op == "rotate":
        await binding.rotate()
        return "rotated", await _key_fields(binding)
    if op == "put_attachment":
        data = bytes.fromhex(command["hex"])
        sha = hashlib.sha256(data).hexdigest()
        await runtime.attachment_store.write(sha, data, command["mime"])
        return "put", {"sha": sha}
    if op == "has_attachment":
        return "has", {"sha": command["sha"], "exists": await runtime.attachment_store.exists(command["sha"])}
    if op == "a2a_post":
        import httpx

        from probos.federation.peer_requests import A2A_REQUEST

        body = await runtime.federation_peer_requests.sign(command["target"], A2A_REQUEST, command["rpc"])
        if body is None:
            return "a2a", {"signed": False}
        headers = {"Content-Type": "application/json", **command.get("headers", {})}
        async with httpx.AsyncClient(trust_env=False, timeout=30.0) as http:
            response = await http.post(command["url"], content=body, headers=headers)
        return "a2a", {"signed": True, "status": response.status_code, "response": response.json(), "body": body.hex()}
    if op == "a2a_callers":
        peers = runtime.federation_peer_registry.list_peers("a2a")
        return "a2a_callers", {"callers": sorted([peer.peer_id, peer.trust_record_id] for peer in peers)}
    if op == "transfer":
        registry = runtime.identity_registry
        crew = min(registry.get_all(), key=lambda born: born.callsign)
        certificate = await registry.issue_transfer_certificate(crew.agent_uuid, command["target_did"])
        accepted, message = await bridge.request_transfer(command["target"], certificate, await registry.export_chain())
        return "transferred", {
            "accepted": accepted, "message": message, "agent_uuid": certificate.agent_uuid, "did": certificate.did,
            "certificate_hash": certificate.certificate_hash, "origin_ship_did": certificate.origin_ship_did,
            "origin_vessel": certificate.origin_vessel_name,
        }
    if op == "foreign":
        registry = runtime.identity_registry
        known = registry.get_by_uuid(command["agent_uuid"])
        chain = registry.get_foreign_chain(command["origin_ship_did"])
        rows = await registry.get_transfer_certificates_for(command["did"])
        return "foreign", {
            "found": known is not None, "did": None if known is None else known.did,
            "vessel_name": None if known is None else known.vessel_name,
            "transfers": sorted([row["direction"], row["certificate_hash"]] for row in rows),
            "foreign_chain_blocks": None if chain is None else len(chain),
        }
    if op == "slot":  # AD-1198 slice 2b-iii a transferred crew member has a slot only once a caller gives it one (AD-443d)
        assigned, message = await runtime.identity_registry.reassign_slot(command["agent_uuid"], command["slot_id"])
        return "slotted", {"assigned": assigned, "message": message}
    return "error", {"message": f"unknown op {op!r}"}


async def _serve_api(runtime: Any, port: int) -> tuple[Any, asyncio.Task[Any]]:
    """Serve the production main API, ``create_app(runtime)``, with uvicorn on 127.0.0.1:``port`` (AD-1198 slice 3a).

    Returns the server and its task once the server has started, its task has ended (a port it could not
    bind leaves ``server.started`` false, H7) or ``_API_START_S`` has passed.
    """
    import uvicorn

    from probos.api import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(runtime), host="127.0.0.1", port=port, log_level="warning"))

    async def _serve() -> None:
        try:
            await server.serve()
        except SystemExit:  # uvicorn calls sys.exit(1) on a port it cannot bind: report api_started False (H7)
            pass

    serving = asyncio.create_task(_serve(), name=f"cluster-api-{port}")
    deadline = time.monotonic() + _API_START_S
    while not server.started and not serving.done() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    return server, serving


async def _stop_api(server: Any, serving: Any) -> None:
    """Ask uvicorn to exit and wait for it, bounded by ``_API_STOP_S``; a server still running then is cancelled."""
    server.should_exit = True
    done, _ = await asyncio.wait({serving}, timeout=_API_STOP_S)
    if not done:
        serving.cancel()


async def main(config_path: str, data_dir: str, control_port: int, name: str, api_port: int | None = None) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", control_port)

    async def emit(kind: str, **data: Any) -> None:
        writer.write((json.dumps({"kind": kind, "node": name, **data}, default=str) + "\n").encode("utf-8"))
        await writer.drain()

    await emit("hello")
    import probos
    from probos.cognitive.llm_client import MockLLMClient
    from probos.config import load_config
    from probos.runtime import ProbOSRuntime

    began = time.monotonic()
    runtime = ProbOSRuntime(config=load_config(Path(config_path)), data_dir=Path(data_dir), llm_client=MockLLMClient())
    try:
        await runtime.start()
    except BaseException as error:
        await emit("failed", error=f"{type(error).__name__}: {error}")
        writer.close()
        raise
    server, serving = None, None
    try:
        if api_port is not None:
            server, serving = await _serve_api(runtime, api_port)
        bridge = runtime.federation_bridge
        await emit(
            "ready", probos_file=probos.__file__, boot_s=round(time.monotonic() - began, 2),
            federation=bridge is not None,
            connected_peers=[] if bridge is None else bridge.federation_status()["connected_peers"],
            api_started=None if server is None else bool(server.started),
            identity_exchange=runtime.federation_identity_exchange is not None,  # AD-1198 slice 2a: wired only while armed
            **await _key_fields(runtime.identity_key_binding),
        )
        while True:
            line = await reader.readline()
            if not line:
                break  # the parent is gone: stop, never linger
            command = json.loads(line)
            if command.get("op") == "stop":
                break
            try:
                kind, data = await _answer(command, runtime)
            except Exception as error:  # noqa: BLE001 -- the parent reads the error event and fails its wait
                kind, data = "error", {"message": f"{command.get('op')}: {type(error).__name__}: {error}"}
            await emit(kind, **data)
    finally:
        faulthandler.dump_traceback_later(_STOP_WATCHDOG_S, repeat=False, file=sys.stderr)
        stopping = time.monotonic()
        if server is not None:
            await _stop_api(server, serving)
        await runtime.stop()
        faulthandler.cancel_dump_traceback_later()
        try:
            await emit(
                "stopped", stop_s=round(time.monotonic() - stopping, 2),
                peer_requests_released=getattr(runtime, "federation_peer_requests", None) is None,
                identity_exchange_released=getattr(runtime, "federation_identity_exchange", None) is None,
            )
        except (ConnectionError, OSError):
            pass  # the parent closed the control socket first; it reads the exit code instead
        writer.close()


if __name__ == "__main__":
    if sys.platform == "win32":  # AD-108: pyzmq needs add_reader, which the Proactor loop lacks (probe Z0p)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    api_port = int(sys.argv[5]) if len(sys.argv) > 5 else None
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], api_port))
    faulthandler.dump_traceback_later(_EXIT_WATCHDOG_S, exit=True, file=sys.stderr)
