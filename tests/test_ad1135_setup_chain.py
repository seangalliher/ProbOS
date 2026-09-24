"""AD-1135 (#1054): ``probos setup`` to a working chat through the real CLI and runtime client.

An OpenAI-compatible stand-in runs on 127.0.0.1:0. ``probos.__main__.main()``
writes the config, and serve's own loader, client factory and ``complete()``
then talk to the stand-in. No other network, home directory or live data
directory is touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import http.server
import json
import logging
import re
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

import probos.__main__ as main_mod
from probos import provider_setup as ps
from probos.cognitive.llm_client import _LLM_TIERS, OpenAICompatibleClient
from probos.config import CognitiveConfig
from probos.types import LLMRequest

_GOOD_KEY = "sk-ad1135-chain-accepted-0123456789"
_BAD_KEY = "sk-ad1135-chain-rejected-9876543210"
_KEY_ENV = "PROBOS_TEST_AD1135_KEY"
_MODEL = "model-x"
_PROMPT = "AD-1135 chain prompt"
_REPLY = "AD-1135 fake provider reply"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_BOOT_PROBE = {"model": _MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
_EXISTING_CONFIG = (
    b"# hand-edited ProbOS config\r\n"
    b"system:\r\n"
    b'  log_level: "INFO"\r\n'
    b"cognitive:\r\n"
    b'  llm_base_url_fast: "http://127.0.0.1:8080/v1"\r\n'
    b'  llm_model_fast: "claude-sonnet-4.6"\r\n'
)


@dataclass(frozen=True)
class _Seen:
    method: str
    path: str
    authorization: str | None
    body: object
    status: int


class _FakeProvider:
    """OpenAI-compatible stand-in that records every request it answers.

    ``chat_body``, when given, is the raw 200 body of every accepted chat request.
    """

    def __init__(self, key: str, *, chat_body: bytes | None = None) -> None:
        self.key = key
        self.chat_body = chat_body
        self._requests: list[_Seen] = []
        self._lock = threading.Lock()
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="ad1135-fake-provider", daemon=True,
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def seen(self) -> list[_Seen]:
        with self._lock:
            return list(self._requests)

    def record(self, seen: _Seen) -> None:
        with self._lock:
            self._requests.append(seen)

    def respond(self, method: str, path: str, authorization: str | None, body: object) -> tuple[int, bytes]:
        if (method, path) not in {("GET", "/v1/models"), ("POST", "/v1/chat/completions")}:
            return 404, _json({"error": {"message": "not found"}})
        if authorization != f"Bearer {self.key}":
            # Echo the presented credential as OpenAI's 401 does, so a leaked body is detectable.
            return 401, _json({"error": {"message": f"Incorrect API key provided: {authorization}"}})
        if path == "/v1/models":
            return 200, _json({"object": "list", "data": [{"id": _MODEL, "object": "model"}]})
        if self.chat_body is not None:
            return 200, self.chat_body
        model = body.get("model") if isinstance(body, dict) else None
        return 200, _json({
            "id": "chatcmpl-ad1135",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": _REPLY}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        })

    def _handler_class(self) -> type[http.server.BaseHTTPRequestHandler]:
        provider = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

            def _answer(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                authorization = self.headers.get("Authorization")
                status, data = provider.respond(method, self.path, authorization, body)
                provider.record(_Seen(method, self.path, authorization, body, status))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._answer("GET")

            def do_POST(self) -> None:
                self._answer("POST")

        return _Handler


def _json(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml",
    )
    for name in ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", _KEY_ENV, *_PROXY_VARS):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)


@pytest.fixture
def fake_provider() -> Iterator[_FakeProvider]:
    provider = _FakeProvider(_GOOD_KEY)
    provider.start()
    try:
        yield provider
    finally:
        provider.stop()


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> object:
    monkeypatch.setattr(sys, "argv", ["probos", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()
    return exc_info.value.code


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


async def test_main_setup_custom_provider_serves_chat_through_runtime_client(
    fake_provider: _FakeProvider, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _GOOD_KEY)
    home_config = tmp_path / "home" / "config.yaml"
    policy_before = asyncio.get_event_loop_policy()

    # Q7 step 1: the real argparse, dispatch and sys.exit.
    code = _run_main(
        monkeypatch, "setup", "--provider", "custom", "--base-url", fake_provider.base_url,
        "--api-key-env", _KEY_ENV, "--model", _MODEL, "--yes",
    )
    assert code == 0
    assert asyncio.get_event_loop_policy() is policy_before

    # Q7 step 2 (premise): setup's listing and one-token probe reached the provider with the key.
    setup_seen = fake_provider.seen()
    assert [(s.method, s.path, s.status) for s in setup_seen] == [
        ("GET", "/v1/models", 200), ("POST", "/v1/chat/completions", 200),
    ]
    assert {s.authorization for s in setup_seen} == {f"Bearer {_GOOD_KEY}"}
    assert setup_seen[1].body == _BOOT_PROBE

    # Q7 step 3: serve's resolver returns the file setup wrote.
    config, path = main_mod._load_config_with_fallback(None)
    assert path == home_config
    assert sorted(p.name for p in home_config.parent.iterdir()) == ["config.yaml"]  # no temp or backup left
    # Premise: every tier resolves to the stand-in, so no probe below can reach another endpoint.
    assert {config.cognitive.tier_config(tier)["base_url"] for tier in _LLM_TIERS} == {fake_provider.base_url}

    # Q7 step 4: serve's factory returns the real client, not MockLLMClient.
    client = await main_mod._create_llm_client(config, Console(file=StringIO()))
    try:
        assert type(client) is OpenAICompatibleClient
        # Q7 step 5: a completion through the runtime client returns the provider's reply.
        response = await client.complete(LLMRequest(prompt=_PROMPT, tier="fast"))
    finally:
        await client.close()
    assert response.error is None
    assert response.content == _REPLY

    # Q7 step 6: the provider received the boot probe and then that completion, with model and key.
    runtime_seen = fake_provider.seen()[len(setup_seen):]
    assert [(s.method, s.path, s.status) for s in runtime_seen] == [("POST", "/v1/chat/completions", 200)] * 2
    assert runtime_seen[0].body == _BOOT_PROBE
    completion = runtime_seen[1]
    assert completion.authorization == f"Bearer {_GOOD_KEY}"
    assert isinstance(completion.body, dict)
    assert completion.body["model"] == _MODEL
    assert completion.body["messages"] == [{"role": "user", "content": _PROMPT}]


def test_main_setup_rejected_key_exits_3_and_creates_nothing(
    fake_provider: _FakeProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    before = _tree(tmp_path)

    code = _run_main(
        monkeypatch, "setup", "--provider", "custom", "--base-url", fake_provider.base_url,
        "--api-key", _BAD_KEY, "--model", _MODEL, "--yes",
    )

    assert code == 3
    # Premise: the provider saw this key and rejected it with a body that echoes it.
    assert [(s.method, s.path, s.status, s.authorization) for s in fake_provider.seen()] == [
        ("GET", "/v1/models", 401, f"Bearer {_BAD_KEY}"),
    ]
    out, err = capsys.readouterr()
    assert "rejected the API key" in " ".join(out.split())
    for text in (out, err, caplog.text):
        assert _BAD_KEY not in _squash(text)
    assert not (tmp_path / "home").exists()
    assert _tree(tmp_path) == before


# One 200 chat body per case: the runtime's boot probe and setup must reach the same verdict on each.
_BOOT_PROBE_BODIES = {
    "text": b'{"choices": [{"message": {"role": "assistant", "content": "pong"}}]}',
    "reasoning-only": b'{"choices": [{"message": {"content": "", "reasoning": "thinking"}}]}',
    "false-content-with-reasoning": b'{"choices": [{"message": {"content": false, "reasoning": "x"}}]}',
    "empty": b'{"choices": [{"message": {"content": ""}}]}',
    "blank": b'{"choices": [{"message": {"content": " \\n "}}]}',
    "null": b'{"choices": [{"message": {"content": null}}]}',
    "absent": b'{"choices": [{"message": {"role": "assistant"}}]}',
    "blank-reasoning": b'{"choices": [{"message": {"content": "", "reasoning": "  "}}]}',
    "list-content": b'{"choices": [{"message": {"content": ["pong"]}}]}',
    "number-content": b'{"choices": [{"message": {"content": 5}}]}',
    "no-choices": b'{"choices": []}',
    "string-message": b'{"choices": [{"message": "pong"}]}',
    "no-message": b'{"choices": [{}]}',
    "empty-object": b"{}",
    "json-list": b"[]",
    "not-json": b"<html>pong</html>",
}


@pytest.mark.parametrize("body", list(_BOOT_PROBE_BODIES.values()), ids=list(_BOOT_PROBE_BODIES))
async def test_probe_chat_passes_a_200_exactly_when_the_runtime_boot_probe_does(
    body: bytes, caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _FakeProvider(_GOOD_KEY, chat_body=body)
    provider.start()
    try:
        cognitive = CognitiveConfig(
            llm_base_url=provider.base_url,
            llm_api_key=_GOOD_KEY,
            **{f"llm_base_url_{tier}": provider.base_url for tier in ps.TEXT_TIERS},
            **{f"llm_model_{tier}": _MODEL for tier in ps.TEXT_TIERS},
        )
        client = OpenAICompatibleClient(config=cognitive)
        try:
            with caplog.at_level(logging.WARNING, logger="probos.cognitive.llm_client"):
                runtime_ok = (await client.check_connectivity())["fast"]
        finally:
            await client.close()
        setup = ps.probe_chat(provider.base_url, _GOOD_KEY, _MODEL)
        seen = provider.seen()
    finally:
        provider.stop()

    # Premise: exactly the runtime's probe, then setup's, each sent the boot-probe payload and got this body.
    assert [(s.method, s.path, s.status, s.body) for s in seen] == [
        ("POST", "/v1/chat/completions", 200, _BOOT_PROBE),
    ] * 2
    if runtime_ok:
        runtime = "ok"
    elif "empty HTTP 200" in caplog.text:
        runtime = "empty"
    elif "malformed HTTP 200" in caplog.text:
        runtime = "malformed"
    else:
        runtime = "unclassified"
    setup_verdicts = {
        ps.ProbeOutcome.OK: "ok", ps.ProbeOutcome.EMPTY_RESPONSE: "empty", ps.ProbeOutcome.BAD_RESPONSE: "malformed",
    }
    assert setup_verdicts.get(setup.outcome, setup.outcome.name) == runtime


def test_main_setup_rejected_key_leaves_existing_config_byte_identical(
    fake_provider: _FakeProvider,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    config_path = tmp_path / "home" / "config.yaml"
    config_path.parent.mkdir()
    config_path.write_bytes(_EXISTING_CONFIG)
    digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    before = _tree(tmp_path)

    code = _run_main(
        monkeypatch, "setup", "--provider", "custom", "--base-url", fake_provider.base_url,
        "--api-key", _BAD_KEY, "--model", _MODEL, "--yes",
    )

    assert code == 3
    # Premise: setup got past the editor and asked the provider, which rejected the key.
    assert [(s.method, s.path, s.status) for s in fake_provider.seen()] == [("GET", "/v1/models", 401)]
    assert hashlib.sha256(config_path.read_bytes()).hexdigest() == digest
    assert _tree(tmp_path) == before
    out, err = capsys.readouterr()
    assert "rejected the API key" in " ".join(out.split())
    for text in (out, err, caplog.text):
        assert _BAD_KEY not in _squash(text)
