"""AD-1137 (#1056): the documented quickstart, end to end, through the real CLI.

``docs/quickstart.md`` is Beta because this file runs it: ``probos setup``,
``probos doctor`` and a first conversation in the ``probos`` shell, each a real
``python -m probos`` process (the ``probos`` console script's own entry point),
with a temporary home and data directory, against an OpenAI-compatible stand-in
on 127.0.0.1:0 that records every request. The children run OSS-only, with
offline Hugging Face and local embeddings, and route any proxied request to a
closed port, so the stand-in is the only endpoint they can reach. They run the
``probos`` this interpreter imports: the quickstart's install step is not run,
because it downloads the dependencies. One more test interrupts ``probos doctor``
with Ctrl+C while the stand-in holds its chat check.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import subprocess
import sys
import threading
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

import probos
from probos import provider_setup as ps
from probos.config import load_config

_KEY = "sk-ad1137-quickstart-accepted-0123456789"
_OTHER_KEY = "sk-ad1137-quickstart-rotated-9876543210"
_KEY_ENV = "PROBOS_TEST_AD1137_KEY"
_MODEL = "model-x"
_PROMPT = "What can you do?"
_REPLY = "AD-1137 stand-in reply: ready to help."
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = Path(probos.__file__).resolve().parents[1]
# A closed port: a request that honours the proxy variables fails instead of leaving the machine.
_DEAD_PROXY = "http://127.0.0.1:9"
_NOT_THE_INSTALL = "the install step is not part of the test"
_FROM_SETUP = "an automated test runs it from `probos setup` on"
# `python -m probos`, plus a thread that sends Ctrl+C once a flag file appears: on Windows the C handler runs in that
# thread, as for a console Ctrl+C. Not stdin: a thread blocked reading it held the doctor back until it closed (A-4).
_INTERRUPTED = """\
import os, runpy, signal, sys, threading, time
def _interrupt():
    while not os.path.exists(os.environ["AD1137_INTERRUPT_FLAG"]):
        time.sleep(0.005)
    if os.name == "nt":
        signal.raise_signal(signal.SIGINT)
    else:
        os.kill(os.getpid(), signal.SIGINT)
threading.Thread(target=_interrupt, daemon=True).start()
sys.argv = ["probos", *sys.argv[1:]]
runpy.run_module("probos", run_name="__main__", alter_sys=True)
"""
# Doctor's chat check waits 30 s, and at HEAD and before A-4 Ctrl+C ended doctor only when it did (29.7 s, measured).
_CTRL_C_WITHIN_S = 15.0


@dataclass(frozen=True)
class _Seen:
    method: str
    path: str
    authorization: str | None
    body: object


class _StandIn:
    """OpenAI-compatible provider on 127.0.0.1:0; accepts one key, which a test can rotate.

    Every chat reply is the decomposer's JSON shape, ``{"intents": [], "response": ...}``, so the
    shell's first answer is ``_REPLY``. With ``hold_chats`` set, a chat request is recorded and held
    unanswered until ``stop``, and ``chat_held`` is set.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        self.hold_chats = False
        self.chat_held = threading.Event()
        self._release = threading.Event()
        self._seen: list[_Seen] = []
        self._lock = threading.Lock()
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="ad1137-stand-in", daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def seen(self) -> list[_Seen]:
        with self._lock:
            return list(self._seen)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._release.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def _hold(self, method: str, path: str, authorization: str | None, body: object) -> None:
        with self._lock:
            self._seen.append(_Seen(method, path, authorization, body))
        self.chat_held.set()
        self._release.wait(120)

    def _answer(self, method: str, path: str, authorization: str | None, body: object) -> tuple[int, dict]:
        with self._lock:
            self._seen.append(_Seen(method, path, authorization, body))
            key = self.key
        if (method, path) not in {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}:
            return 404, {"error": {"message": "not found"}}
        if authorization != f"Bearer {key}":
            # OpenAI's 401 echoes the presented credential, so a leaked body would be visible.
            return 401, {"error": {"message": f"Incorrect API key provided: {authorization}"}}
        if path == "/v1/models":
            return 200, {"object": "list", "data": [{"id": _MODEL, "object": "model"}]}
        content = json.dumps({"intents": [], "response": _REPLY})
        return 200, {
            "id": "chatcmpl-ad1137",
            "object": "chat.completion",
            "model": body.get("model") if isinstance(body, dict) else None,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        stand_in = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _reply(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                if method == "POST" and stand_in.hold_chats:
                    self.close_connection = True
                    stand_in._hold(method, self.path, self.headers.get("Authorization"), body)
                    return
                status, payload = stand_in._answer(method, self.path, self.headers.get("Authorization"), body)
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._reply("GET")

            def do_POST(self) -> None:
                self._reply("POST")

        return _Handler


@pytest.fixture
def stand_in() -> Iterator[_StandIn]:
    provider = _StandIn(_KEY)
    provider.start()
    try:
        yield provider
    finally:
        provider.stop()


@dataclass(frozen=True)
class _Home:
    root: Path
    home: Path
    data: Path
    env: dict[str, str]

    @property
    def config(self) -> Path:
        return self.home / ".probos" / "config.yaml"


@pytest.fixture
def user(tmp_path: Path) -> _Home:
    home, data = tmp_path / "home", tmp_path / "data"
    home.mkdir()
    env = {
        name: value for name, value in os.environ.items()
        if not name.upper().startswith(("PROBOS_", "PYTEST_", "OPENAI_", "OPENROUTER_", "ANTHROPIC_"))
        and name.upper() not in {"PYTHONPATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    }
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_DATA_HOME": str(home / ".local" / "share"), "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "PROBOS_DATA_DIR": str(data), "PROBOS_DISABLE_OVERLAY": "1", "PROBOS_EMBEDDINGS": "local",
        "PROBOS_LLM_URL": "", _KEY_ENV: _KEY,
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ANONYMIZED_TELEMETRY": "False",
        "HTTP_PROXY": _DEAD_PROXY, "HTTPS_PROXY": _DEAD_PROXY, "ALL_PROXY": _DEAD_PROXY,
        "NO_PROXY": "127.0.0.1,localhost",
        "PYTHONPATH": str(_SRC_ROOT), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "COLUMNS": "200",
    })
    for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        env.pop(name, None)
    return _Home(tmp_path, home, data, env)


def _run(user: _Home, *argv: str, stdin: str | None = None, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "probos", *argv],
        cwd=user.root, env=user.env, input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def _setup(user: _Home, stand_in: _StandIn) -> subprocess.CompletedProcess[str]:
    return _run(
        user, "setup", "--provider", "custom", "--base-url", stand_in.base_url,
        "--api-key-env", _KEY_ENV, "--model", _MODEL, "--yes",
    )


def _said(*runs: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(run.stdout + run.stderr for run in runs)


def _squashed(text: str) -> str:
    return " ".join(text.split())


def _assert_no_key(text: str) -> None:
    for key in (_KEY, _OTHER_KEY):
        assert not ps.carries_key(text, key)


def _assert_children_import_this_tree(user: _Home) -> None:
    """Premise: each child runs the probos under test, not another install."""
    probe = subprocess.run(
        [sys.executable, "-c", "import probos, sys; sys.stdout.write(probos.__file__)"],
        cwd=user.root, env=user.env, capture_output=True, text=True, timeout=60,
    )

    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout).resolve() == Path(probos.__file__).resolve()


def test_quickstart_path_reaches_a_first_conversation(user: _Home, stand_in: _StandIn) -> None:
    _assert_children_import_this_tree(user)
    setup = _setup(user, stand_in)
    assert setup.returncode == 0, _said(setup)
    # Premise: every tier the runtime resolves is the stand-in, and nothing configured reaches a live service.
    config = load_config(user.config)
    assert {config.cognitive.tier_config(tier)["base_url"] for tier in (*ps.TEXT_TIERS, *ps.OPTIONAL_TIERS)} == {
        stand_in.base_url,
    }
    assert (config.nats.enabled, config.federation.enabled) == (False, False)
    assert "Run probos doctor" in _squashed(setup.stdout)

    doctor = _run(user, "doctor")
    doctor_out = _squashed(doctor.stdout)
    assert doctor.returncode == 0, _said(doctor)
    assert f"Config: {user.config}" in doctor_out
    assert f"LLM tiers answer: fast, standard, deep: model '{_MODEL}' at {stand_in.base_url}" in doctor_out
    # AD-1137 A-3: printed only when no check failed or warned, so this also pins a path without warnings.
    assert "All checks passed." in doctor_out

    shell = _run(user, stdin=f"{_PROMPT}\n", timeout=150)
    shell_out = shell.stdout
    assert shell.returncode == 0, _said(shell)
    # The reply comes from the stand-in, after the question; the mock client would not answer this way.
    assert shell_out.index(f"> {_PROMPT}") < shell_out.index(_REPLY), _said(shell)
    assert "MockLLMClient" not in shell_out
    assert "tier(s) unreachable" not in shell_out  # #1414 F-f: the optional tiers setup left unconfigured
    asked = [seen.body for seen in stand_in.seen() if seen.method == "POST"]
    assert any(_PROMPT in json.dumps(body) for body in asked)

    assert {seen.authorization for seen in stand_in.seen()} == {f"Bearer {_KEY}"}
    logs = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in user.data.rglob("*.log"))
    _assert_no_key(_said(setup, doctor, shell) + logs)


def test_doctor_fails_when_the_provider_rejects_the_key(user: _Home, stand_in: _StandIn) -> None:
    _assert_children_import_this_tree(user)
    setup = _setup(user, stand_in)
    assert setup.returncode == 0, _said(setup)
    stand_in.key = _OTHER_KEY  # the provider revokes the key setup checked

    doctor = _run(user, "doctor")

    out = _squashed(doctor.stdout)
    assert doctor.returncode >= 1, _said(doctor)  # AD-1137: this exited 0, "LLM tiers reachable", before
    assert "LLM tier check failed for fast, standard, deep" in out
    assert "the provider rejected the API key (HTTP 401)" in out
    assert "Check the API key: rerun `probos setup`" in out
    _assert_no_key(_said(setup, doctor))


def test_ctrl_c_ends_doctor_while_a_provider_holds_its_check(user: _Home, stand_in: _StandIn) -> None:
    _assert_children_import_this_tree(user)
    setup = _setup(user, stand_in)
    assert setup.returncode == 0, _said(setup)
    stand_in.hold_chats = True
    flag = user.root / "interrupt.flag"
    child = subprocess.Popen(
        [sys.executable, "-c", _INTERRUPTED, "doctor"], cwd=user.root,
        env={**user.env, "AD1137_INTERRUPT_FLAG": str(flag)}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    try:
        assert stand_in.chat_held.wait(120), "premise: doctor never sent its chat check"
        asked = len(stand_in.seen())
        assert child.poll() is None  # premise: the chat check is in flight and unanswered
        flag.write_text("", encoding="utf-8")
        try:
            out, err = child.communicate(timeout=_CTRL_C_WITHIN_S)
        except subprocess.TimeoutExpired:
            # AD-1137 A-4 (review round 3): doctor ran on until its chat check timed out.
            pytest.fail(f"probos doctor was still running {_CTRL_C_WITHIN_S:g} s after Ctrl+C")
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()

    assert child.returncode != 0 and "KeyboardInterrupt" in err, out + err  # premise: Ctrl+C is what ended it
    assert len(stand_in.seen()) == asked  # no probe started after it
    _assert_no_key(out + err)


def test_quickstart_documents_the_commands_this_file_runs() -> None:
    text = (_REPO_ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```(?:bash)?\n(.*?)```", text, flags=re.S)
    commands = [line.split("#")[0].strip() for block in blocks for line in block.splitlines()]

    for command in ("pip install -e .", "probos setup", "probos doctor", "probos"):
        assert command in commands, f"quickstart no longer runs {command!r}"
    assert f"> {_PROMPT}" in commands
    assert "Status: Beta" in text and Path(__file__).name in text
    scripts = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["probos"] == "probos.__main__:main"  # the entry point `python -m probos` runs here


def test_the_docs_claim_only_what_this_file_runs() -> None:
    quickstart = (_REPO_ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    status = " ".join(quickstart.split("**Status: Beta.**", 1)[1].split("\n\n", 1)[0].split())
    readme = " ".join((_REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    installation_page = _REPO_ROOT / "docs" / "getting-started" / "installation.md"
    installation = " ".join(installation_page.read_text(encoding="utf-8").split())

    # AD-1137 A-2 (review round 1): they said this file runs the quickstart from the install, which it does not.
    for step in ("`probos setup`", "`probos doctor`", "a first conversation", Path(__file__).name):
        assert step in status, step
    assert _NOT_THE_INSTALL in status and _NOT_THE_INSTALL in readme
    assert _FROM_SETUP in readme and _FROM_SETUP in installation
