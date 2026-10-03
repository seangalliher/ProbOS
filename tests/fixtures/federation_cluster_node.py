"""AD-1198 (#1135): one ProbOS node as a real process, for the two-node cluster gate.

Run as a script by ``tests/fixtures/federation_cluster.py`` (the parent harness), never imported by a test::

    python -X utf8 -u federation_cluster_node.py <config.yaml> <data_dir> <control_port> <name>

The parent builds the environment: ``PYTHONPATH`` names the worktree's ``src``, so this script edits no
``sys.path``; stdin is DEVNULL (a pipe there hung the knowledge store's git flush on shutdown, probe N r2).
On Windows the selector loop is installed first (AD-108): zmq.asyncio hangs on the Proactor loop (probe Z0p).

The node connects to the parent's 127.0.0.1 control socket and speaks JSON lines, each
``{"kind": ..., "node": <name>, ...}``. It emits ``hello``, boots ``ProbOSRuntime`` with an injected
``MockLLMClient`` and emits ``ready`` (or ``failed`` if the start raised), then answers the parent's ops --
``forward`` (``forwarded``), ``status`` (``status``) and ``rotate`` (``rotated``); an op that fails is
answered ``error`` -- until ``stop`` or until the control socket closes (the parent is gone), and then stops
the runtime and emits ``stopped``. After ``main`` returns a faulthandler watchdog dumps every stack into
the run log and exits 1 if anything keeps the interpreter alive (the #1455 convention): a clean exit is 0.

Import-safe: everything runs only when this file is run as a script.
"""

from __future__ import annotations

import asyncio
import faulthandler
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_STOP_WATCHDOG_S = 60  # runtime.stop() took 3.2 s in probe N3
_EXIT_WATCHDOG_S = 30  # after main returns


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
    return "error", {"message": f"unknown op {op!r}"}


async def main(config_path: str, data_dir: str, control_port: int, name: str) -> None:
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
    try:
        bridge = runtime.federation_bridge
        await emit(
            "ready", probos_file=probos.__file__, boot_s=round(time.monotonic() - began, 2),
            federation=bridge is not None,
            connected_peers=[] if bridge is None else bridge.federation_status()["connected_peers"],
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
        await runtime.stop()
        faulthandler.cancel_dump_traceback_later()
        try:
            await emit("stopped", stop_s=round(time.monotonic() - stopping, 2))
        except (ConnectionError, OSError):
            pass  # the parent closed the control socket first; it reads the exit code instead
        writer.close()


if __name__ == "__main__":
    if sys.platform == "win32":  # AD-108: pyzmq needs add_reader, which the Proactor loop lacks (probe Z0p)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]))
    faulthandler.dump_traceback_later(_EXIT_WATCHDOG_S, exit=True, file=sys.stderr)
