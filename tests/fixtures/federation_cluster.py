"""AD-1198 (#1135): the parent harness of the two-node cluster gate (``tests/test_ad1198_cluster_gate.py``).

Two real ProbOS processes built from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml``, derived for
offline use: ephemeral 127.0.0.1 ports, LLM URLs on a closed port (each node also gets an injected
``MockLLMClient``) and an isolated home, data directory and knowledge repo per node, so nothing on disk is shared.
Each node runs ``federation_cluster_node.py`` and is driven over a 127.0.0.1 control socket (``ControlServer``).
In the ``mitm`` topology each node's peer address is a ``WireProxy`` lane, a blocking-pyzmq relay that can drop,
duplicate and replay whole payloads; in the ``direct`` topology (the shipped one) the nodes connect to each other.

Only blocking pyzmq runs in this (the pytest) process: zmq.asyncio hangs on the Windows Proactor loop (probe
Z0p). Every wait is bounded, and ``ClusterHarness.__exit__`` kills every child still running, so a failing test
leaves no process behind; a node whose control socket closes stops by itself.

Import-safe: nothing runs at import. The ``test_`` prefix is absent on purpose, so pytest never collects it.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal

import yaml
import zmq

from probos.federation_envelope_store import ENVELOPE_DB_NAME

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
NODE_RUNNER = Path(__file__).with_name("federation_cluster_node.py")
NODES = ("node-1", "node-2")
SHORT = {"node-1": "n1", "node-2": "n2"}  # H15: short directory names under a pytest tmp_path
OTHER = {"node-1": "node-2", "node-2": "node-1"}

CLOSED_PORT_URL = "http://127.0.0.1:9"  # nothing listens on port 9: no live LLM or proxy is reachable
READY_TIMEOUT_S = 180.0
STOP_TIMEOUT_S = 120.0
EXIT_TIMEOUT_S = 60.0
FORWARD_TIMEOUT_S = 30.0
OP_TIMEOUT_S = 60.0

_STRIPPED_PREFIXES = ("PROBOS_", "PYTEST_", "OPENAI_", "OPENROUTER_", "ANTHROPIC_")
_STRIPPED_NAMES = frozenset({"PYTHONPATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"})
_TRANSPORT_FAILED = "Federation transport failed to start"  # fleet_organization's ZeroMQ start failure (H7)
_REFUSAL = re.compile(
    r"AD-1197: envelope .* rejected \(|AD-1198: envelope .* refused \(|AD-1198: the key history held for"
)
_SHIPPED_ADDRESS = re.compile(r"tcp://127\.0\.0\.1:555\d")


def reserve_port() -> int:
    """A free 127.0.0.1 port for a node's ROUTER to bind (a race lost to another process is retried once, H7)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def node_dir(root: Path, name: str) -> Path:
    return root / SHORT[name]


def derive_node_config(
    name: str,
    root: Path,
    *,
    bind_port: int,
    peer_port: int,
    phase: Literal["mint", "pinned"],
    pinned_public_key: str | None = None,
) -> Path:
    """The shipped ``config/<name>.yaml`` derived for one offline boot; written to ``<root>/<short>/<phase>.yaml``.

    ``mint`` boots with federation off, only to commission the ship key. ``pinned`` arms envelope signing under
    policy ``require`` and peer admission, with the one peer pinned to ``pinned_public_key``.
    """
    other = OTHER[name]
    data = yaml.safe_load((REPO / "config" / f"{name}.yaml").read_text(encoding="utf-8"))
    federation = data["federation"]
    peers = federation["peers"]
    assert federation["enabled"] is True and federation["node_id"] == name, federation  # premise: the shipped topology
    assert len(peers) == 1 and peers[0]["node_id"] == other, peers
    assert _SHIPPED_ADDRESS.fullmatch(federation["bind_address"]) and _SHIPPED_ADDRESS.fullmatch(peers[0]["address"])
    cognitive = data.setdefault("cognitive", {})
    for key in [key for key in cognitive if key.startswith("llm_base_url")]:
        cognitive[key] = f"{CLOSED_PORT_URL}/v1"
    federation["bind_address"] = f"tcp://127.0.0.1:{bind_port}"
    peers[0]["address"] = f"tcp://127.0.0.1:{peer_port}"
    federation.update(forward_timeout_ms=2000, identity_keys_enabled=True, identity_key_store="plaintext_dev")
    if phase == "mint":
        federation["enabled"] = False
    elif phase == "pinned":
        assert pinned_public_key, f"a pinned boot of {name} needs {other}'s minted public key"
        federation.update(envelope_signing_enabled=True, envelope_policy="require", peer_admission_enabled=True)
        peers[0]["pinned_public_key"] = pinned_public_key
    else:
        raise ValueError(f"unknown phase {phase!r}")
    data.setdefault("knowledge", {})["repo_path"] = str(node_dir(root, name) / "k")
    out = node_dir(root, name) / f"{phase}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return out


def child_env(root: Path, name: str, data_dir: Path) -> dict[str, str]:
    """The node's environment, built explicitly (``os.environ`` itself is never changed)."""
    home = node_dir(root, name) / "h"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(_STRIPPED_PREFIXES) and key.upper() not in _STRIPPED_NAMES
    }
    env.update(
        HOME=str(home), USERPROFILE=str(home),
        APPDATA=str(home / "AppData" / "Roaming"), LOCALAPPDATA=str(home / "AppData" / "Local"),
        XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        PROBOS_DATA_DIR=str(data_dir), PROBOS_DISABLE_OVERLAY="1", PROBOS_EMBEDDINGS="local", PROBOS_LLM_URL="",
        PROBOS_NATS_ENABLED="false", PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="False",
        HTTP_PROXY=CLOSED_PORT_URL, HTTPS_PROXY=CLOSED_PORT_URL, ALL_PROXY=CLOSED_PORT_URL,
        NO_PROXY="127.0.0.1,localhost",
        PYTHONPATH=str(SRC), PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
    )
    return env


class ControlServer:
    """The 127.0.0.1 listener the node children connect back to; one event queue per node connection.

    A child's first event names it; a new connection under the same name (a restart) replaces the old one, and
    ``forget`` drops a name before its next run so no stale event can answer a wait meant for the new run.
    """

    _TERMINAL = frozenset({"eof", "failed", "stopped", "error"})

    def __init__(self) -> None:
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port = int(self._server.getsockname()[1])
        self._lock = threading.Lock()
        self._queues: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._connections: dict[str, socket.socket] = {}
        self._accepted: list[socket.socket] = []
        threading.Thread(target=self._accept, name="ad1198-control", daemon=True).start()

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return  # closed
            with self._lock:
                self._accepted.append(connection)
            threading.Thread(target=self._pump, args=(connection,), name="ad1198-control-pump", daemon=True).start()

    def _pump(self, connection: socket.socket) -> None:
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        name: str | None = None
        try:
            with connection.makefile("r", encoding="utf-8", errors="replace") as lines:
                for line in lines:
                    event = json.loads(line)
                    if name is None:
                        name = str(event.get("node"))
                        with self._lock:
                            self._queues[name] = events
                            self._connections[name] = connection
                    events.put(event)
        except (OSError, ValueError):
            pass
        events.put({"kind": "eof", "node": name})

    def wait(self, name: str, kind: str, timeout: float) -> dict[str, Any]:
        """The next ``kind`` event from ``name``; raises on another terminal event or at the deadline."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                events = self._queues.get(name)
            if events is not None:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{name} did not connect to the control socket within {timeout:g} s")
            time.sleep(0.05)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"{name}: no {kind!r} event within {timeout:g} s")
            try:
                event = events.get(timeout=left)
            except queue.Empty:
                continue
            if event.get("kind") == kind:
                return event
            if event.get("kind") in self._TERMINAL:
                raise RuntimeError(f"{name}: waiting for {kind!r}, got {event}")

    def send(self, name: str, **command: Any) -> None:
        with self._lock:
            connection = self._connections[name]
        connection.sendall((json.dumps(command) + "\n").encode("utf-8"))

    def forget(self, name: str) -> None:
        with self._lock:
            self._queues.pop(name, None)
            self._connections.pop(name, None)

    def close(self) -> None:
        self._server.close()
        with self._lock:
            accepted = list(self._accepted)
        for connection in accepted:
            with contextlib.suppress(OSError):
                connection.close()


def _topic(payload: bytes) -> str | None:
    with contextlib.suppress(ValueError, AttributeError):
        message = json.loads(payload)
        kind = message.get("type")
        return kind if type(kind) is str else None
    return None


class WireProxy:
    """A blocking-pyzmq man in the middle on a daemon thread: one one-way lane per direction.

    ``lanes`` maps a lane name to its back port, the receiving node's ROUTER. Each lane's front is a ROUTER bound
    to a random 127.0.0.1 port (no reservation race), which is the sending node's peer address; its back is a
    DEALER with routing id ``mitm-<lane>``. Every payload is recorded in ``seen`` before it is dropped,
    duplicated or passed on whole.
    """

    def __init__(self, lanes: dict[str, int]) -> None:
        self._lanes = dict(lanes)
        self._lock = threading.Lock()
        self._drop = False
        self._duplicate: dict[str, str] = {}
        self._seen: dict[str, list[bytes]] = {lane: [] for lane in lanes}
        self._injections: queue.Queue[tuple[str, bytes, threading.Event]] = queue.Queue()
        self._front_ports: dict[str, int] = {}
        self._failure: list[BaseException] = []
        self._running = True
        self._ready = threading.Event()
        self._context = zmq.Context()
        self._thread = threading.Thread(target=self._run, name="ad1198-wire-proxy", daemon=True)
        self._thread.start()
        if not self._ready.wait(10) or self._failure:
            self.close()
            raise RuntimeError(f"the wire proxy did not start: {self._failure}")

    def _run(self) -> None:
        fronts: list[tuple[zmq.Socket[bytes], str]] = []
        backs: dict[str, zmq.Socket[bytes]] = {}
        poller = zmq.Poller()
        try:
            for lane, back_port in self._lanes.items():
                front = self._context.socket(zmq.ROUTER)
                front.setsockopt(zmq.LINGER, 0)
                self._front_ports[lane] = front.bind_to_random_port("tcp://127.0.0.1")
                back = self._context.socket(zmq.DEALER)
                back.setsockopt(zmq.LINGER, 0)
                back.setsockopt(zmq.IDENTITY, f"mitm-{lane}".encode())
                back.connect(f"tcp://127.0.0.1:{back_port}")
                fronts.append((front, lane))
                backs[lane] = back
                poller.register(front, zmq.POLLIN)
        except BaseException as error:  # noqa: BLE001 -- reported to the constructor, which raises
            self._failure.append(error)
        self._ready.set()
        try:
            while self._running and not self._failure:
                for ready, _ in poller.poll(50):
                    lane = next(name for socket_, name in fronts if socket_ is ready)
                    payload = ready.recv_multipart()[-1]
                    with self._lock:
                        self._seen[lane].append(payload)
                        drop = self._drop
                        copies = 1
                        if not drop and self._duplicate.get(lane) is not None and _topic(payload) == self._duplicate[lane]:
                            copies = 2
                            del self._duplicate[lane]
                    if not drop:
                        for _ in range(copies):
                            backs[lane].send(payload)
                while True:
                    try:
                        lane, payload, sent = self._injections.get_nowait()
                    except queue.Empty:
                        break
                    backs[lane].send(payload)
                    sent.set()
        finally:
            for socket_, _ in fronts:
                socket_.close(linger=0)
            for socket_ in backs.values():
                socket_.close(linger=0)

    def front_port(self, lane: str) -> int:
        return self._front_ports[lane]

    def set_drop(self, flag: bool) -> None:
        """Drop every payload on every lane (a partition) while ``flag`` holds; ``seen`` still records them."""
        with self._lock:
            self._drop = flag

    def duplicate_next(self, lane: str, topic: str = "intent_request") -> None:
        """Pass the next payload on ``lane`` whose JSON ``type`` is ``topic`` twice (gossip is never duplicated)."""
        with self._lock:
            self._duplicate[lane] = topic

    def seen(self, lane: str, topic: str | None = None) -> list[bytes]:
        """A copy of every payload ``lane`` received, in order; only those of JSON ``type`` ``topic`` if given."""
        with self._lock:
            payloads = list(self._seen[lane])
        return payloads if topic is None else [payload for payload in payloads if _topic(payload) == topic]

    def inject(self, lane: str, payload: bytes) -> None:
        """Send ``payload`` down ``lane``'s back socket; returns once the proxy thread has sent it."""
        sent = threading.Event()
        self._injections.put((lane, payload, sent))
        if not sent.wait(10):
            raise TimeoutError(f"the wire proxy did not send the injected payload on {lane} within 10 s")

    def close(self) -> None:
        self._running = False
        self._thread.join(10)
        if self._thread.is_alive():
            self._context.destroy(linger=0)
        else:
            self._context.term()


@dataclass(frozen=True)
class Identity:
    """A node's ship key as minted: its DID, active key id, base64 public key and key-event position."""

    did: str
    kid: str
    public_key: str
    key_seq: int


@dataclass
class _Run:
    process: subprocess.Popen[bytes]
    log: IO[bytes]
    number: int


class ClusterHarness:
    """Two real nodes from the shipped node configs, under one root; a context manager that kills what it started."""

    def __init__(self, root: Path, *, topology: Literal["mitm", "direct"]) -> None:
        if topology not in ("mitm", "direct"):
            raise ValueError(f"unknown topology {topology!r}")
        self.root = root
        self.topology = topology
        self.minted: dict[str, Identity] = {}
        self.port_retries: list[str] = []
        self.proxy: WireProxy | None = None
        self._control: ControlServer | None = None
        self._ports: dict[str, int] = {}
        self._runs: dict[str, _Run] = {}
        self._run_counts = {name: 0 for name in NODES}
        self._tokens: dict[str, str] = {}

    # -- lifecycle ------------------------------------------------------------------------------------------

    def __enter__(self) -> ClusterHarness:
        try:
            self._control = ControlServer()
            self._new_ports()
        except BaseException:
            self._close_shared()
            raise
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        try:
            for name in list(self._runs):
                self._kill(name)
        finally:
            self._close_shared()

    def _close_shared(self) -> None:
        try:
            if self.proxy is not None:
                self.proxy.close()
        finally:
            if self._control is not None:
                self._control.close()

    @property
    def control(self) -> ControlServer:
        assert self._control is not None, "use the harness as a context manager"
        return self._control

    def _new_ports(self) -> None:
        """Fresh ROUTER ports for both nodes and, in the mitm topology, a fresh proxy relaying to them."""
        ports = {name: reserve_port() for name in NODES}
        while ports["node-2"] == ports["node-1"]:
            ports["node-2"] = reserve_port()
        self._ports = ports
        if self.topology == "mitm":
            if self.proxy is not None:
                self.proxy.close()
                self.proxy = None
            self.proxy = WireProxy({"1to2": ports["node-2"], "2to1": ports["node-1"]})

    def _peer_port(self, name: str) -> int:
        if self.proxy is not None:
            return self.proxy.front_port("1to2" if name == "node-1" else "2to1")
        return self._ports[OTHER[name]]

    def _data_dir(self, name: str) -> Path:
        return node_dir(self.root, name) / "d"

    def _assert_isolated(self, name: str, config: Path, env: dict[str, str]) -> None:
        own, other = node_dir(self.root, name), node_dir(self.root, OTHER[name])
        assert not own.is_relative_to(other) and not other.is_relative_to(own), (own, other)
        text = config.read_text(encoding="utf-8")
        for needle in {str(other), other.as_posix()}:  # no shared filesystem: nothing names the other node's root
            assert needle not in text, f"{name}'s config names {other}"
            assert not any(needle in value for value in env.values()), f"{name}'s environment names {other}"

    def _spawn(self, name: str, phase: Literal["mint", "pinned"], pin: str | None) -> None:
        assert name not in self._runs, f"{name} is already running"
        config = derive_node_config(
            name, self.root, bind_port=self._ports[name], peer_port=self._peer_port(name), phase=phase,
            pinned_public_key=pin,
        )
        data_dir = self._data_dir(name)
        env = child_env(self.root, name, data_dir)
        self._assert_isolated(name, config, env)
        self.control.forget(name)
        self._run_counts[name] += 1
        number = self._run_counts[name]
        log = open(node_dir(self.root, name) / f"run{number}.log", "ab")  # noqa: SIM115 -- closed when the run ends
        try:
            process = subprocess.Popen(
                [
                    sys.executable, "-X", "utf8", "-u", str(NODE_RUNNER), str(config), str(data_dir),
                    str(self.control.port), name,
                ],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(node_dir(self.root, name)),
            )
        except BaseException:
            log.close()
            raise
        self._runs[name] = _Run(process, log, number)

    def _ready(self, name: str) -> dict[str, Any]:
        event = self.control.wait(name, "ready", READY_TIMEOUT_S)
        assert Path(event["probos_file"]).resolve().is_relative_to(SRC.resolve()), event["probos_file"]  # H4
        return event

    def _kill(self, name: str) -> None:
        run = self._runs.pop(name, None)
        if run is None:
            return
        try:
            if run.process.poll() is None:
                if sys.platform == "win32":  # the venv's python.exe launches a base interpreter: end the tree
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(run.process.pid)], capture_output=True, timeout=30,
                        check=False,
                    )
                run.process.kill()
                run.process.wait(timeout=30)
        finally:
            run.log.close()

    # -- boots ----------------------------------------------------------------------------------------------

    def mint(self) -> dict[str, Identity]:
        """Commission both ship keys (federation off) and record each node's minted identity; both are stopped."""
        for name in NODES:
            self._spawn(name, "mint", None)
        for name in NODES:
            ready = self._ready(name)
            assert ready["key_status"] == "active" and ready["federation"] is False, ready
            self.minted[name] = Identity(ready["did"], ready["kid"], ready["public_key"], ready["key_seq"])
        self.stop(*NODES)
        assert self.minted["node-1"].did != self.minted["node-2"].did  # premise: two ships, two DIDs
        return dict(self.minted)

    def _boot_pinned(self, names: Iterable[str]) -> dict[str, dict[str, Any]]:
        names = tuple(names)
        for name in names:
            self._spawn(name, "pinned", self.minted[OTHER[name]].public_key)
        return {name: self._ready(name) for name in names}

    def _bind_failed(self, name: str, ready: dict[str, Any]) -> bool:
        return ready["connected_peers"] == [] and _TRANSPORT_FAILED in self.log(name, self.run_of(name))

    def boot(self, *names: str) -> dict[str, dict[str, Any]]:
        """Boot ``names`` (default both), each pinned to the other's minted key; their ``ready`` events.

        H7: a node whose ROUTER could not bind its reserved port (``connected_peers == []`` and the start
        failure in its run log) makes every running node restart once on fresh ports; the retry is recorded in
        ``port_retries`` and warned.
        """
        targets = names or NODES
        assert self.minted, "boot() needs the minted identities: call mint() first"
        ready = self._boot_pinned(targets)
        failed = [name for name, event in ready.items() if self._bind_failed(name, event)]
        if failed:
            running = tuple(name for name in NODES if name in self._runs)
            note = f"H7: {failed} could not bind; restarting {list(running)} once on fresh ports"
            self.port_retries.append(note)
            warnings.warn(f"AD-1198 cluster gate {note}", stacklevel=2)
            self.stop(*running)
            self._new_ports()
            ready = self._boot_pinned(running)
            failed = [name for name, event in ready.items() if self._bind_failed(name, event)]
            assert not failed, f"H7: {failed} still could not bind after one retry on fresh ports"
        for name in targets:
            event = ready[name]
            assert event["federation"] is True, event
            assert event["connected_peers"] == [OTHER[name]], event
            assert event["kid"] == self.minted[name].kid, event
        return {name: ready[name] for name in targets}

    def stop(self, *names: str) -> None:
        """Stop ``names`` through the control socket; each must report ``stopped`` and then exit 0 by itself."""
        for name in names:
            self.control.send(name, op="stop")
        for name in names:
            self.control.wait(name, "stopped", STOP_TIMEOUT_S)
        for name in names:
            run = self._runs[name]
            try:
                code = run.process.wait(timeout=EXIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._kill(name)
                raise AssertionError(f"{name} run {run.number} did not exit within {EXIT_TIMEOUT_S:g} s of stopping")
            del self._runs[name]
            run.log.close()
            assert code == 0, f"{name} run {run.number} exited {code}: {self.log(name, run.number)[-3000:]}"

    def restart(self, name: str) -> dict[str, Any]:
        """Stop ``name`` and boot it again on the same data, config and ports; its ``ready`` event."""
        self.stop(name)
        return self.boot(name)[name]

    # -- operations -----------------------------------------------------------------------------------------

    def forward(self, path: str, sender: str = "node-1") -> dict[str, Any]:
        """``sender`` forwards ``read_file(path)``; the ``forwarded`` event plus ``ok``: a result is the token."""
        self.control.send(sender, op="forward", intent="read_file", params={"path": path}, timeout=FORWARD_TIMEOUT_S)
        event = self.control.wait(sender, "forwarded", FORWARD_TIMEOUT_S + 30.0)
        token = self._tokens[path]
        event["ok"] = any(result.get("result") == token for result in event["results"])
        return event

    def status(self, name: str) -> dict[str, Any]:
        self.control.send(name, op="status")
        return self.control.wait(name, "status", OP_TIMEOUT_S)

    def rotate(self, name: str) -> dict[str, Any]:
        self.control.send(name, op="rotate")
        return self.control.wait(name, "rotated", OP_TIMEOUT_S)

    def write_token(self, name: str) -> tuple[str, str]:
        """A fresh token in a file only ``name`` is told about; ``(path, token)``."""
        directory = node_dir(self.root, name) / "files"
        directory.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(16)
        path = directory / f"token-{token[:8]}.txt"
        path.write_text(token, encoding="utf-8")
        self._tokens[str(path)] = token
        return str(path), token

    def router_port(self, name: str) -> int:
        return self._ports[name]

    # -- evidence -------------------------------------------------------------------------------------------

    def run_of(self, name: str) -> int:
        """The number of ``name``'s current (or last) run; the mint boot is run 1."""
        return self._run_counts[name]

    def log(self, name: str, run: int | None = None) -> str:
        """``name``'s run log (``run``), or all of its run logs in order."""
        numbers = range(1, self._run_counts[name] + 1) if run is None else (run,)
        paths = [node_dir(self.root, name) / f"run{number}.log" for number in numbers]
        return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.exists())

    def wait_for_log(self, name: str, marker: str, timeout: float = 60.0) -> str:
        """The first log line of ``name`` containing ``marker``; a bounded poll, never a bare sleep."""
        deadline = time.monotonic() + timeout
        while True:
            for line in self.log(name).splitlines():
                if marker in line:
                    return line
            if time.monotonic() >= deadline:
                raise AssertionError(f"{name}: no log line containing {marker!r} within {timeout:g} s")
            time.sleep(0.1)

    def refusal_lines(self, name: str, run: int | None = None) -> list[str]:
        """Every AD-1197 envelope rejection and AD-1198 refusal ``name`` logged."""
        return [line for line in self.log(name, run).splitlines() if _REFUSAL.search(line)]

    def store_rows(self, name: str) -> list[tuple[Any, ...]]:
        """``name``'s held senders ``(source_node, did, key_seq, key_ids_json)``; read after ``stop``."""
        assert name not in self._runs, f"{name} is still running: read its store after stop()"
        path = self._data_dir(name) / ENVELOPE_DB_NAME
        assert path.is_file(), path
        with contextlib.closing(sqlite3.connect(path)) as db:
            return db.execute(
                "SELECT source_node, did, key_seq, key_ids_json FROM envelope_senders ORDER BY source_node"
            ).fetchall()
