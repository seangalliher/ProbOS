"""BF-994 (#1414 Batch A, slice A1): the config `probos init` writes reaches the API its URL serves.

Item 2: init's Ollama default is Ollama's OpenAI-compatible /v1 API, so it is written with the openai
format; only a bare Ollama root (port 11434, no path) keeps the native format. Item 5: the scaffold that
init and setup's create path share sets llm_timeout_seconds: 300.0, the shipped config/system.yaml value;
an existing file is not given one.
"""
from __future__ import annotations

import argparse
import string
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from rich.console import Console

import probos.__main__ as main_mod
from probos import provider_setup
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import load_config
from probos.types import LLMRequest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEXT_TIERS = ("fast", "standard", "deep")
_ENV = ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_SETUP_OFFLINE = (
    "--provider", "custom", "--base-url", "https://llm.example.test/v1", "--model", "model-x",
    "--skip-validation", "--yes",
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml")
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _no_detection(console: object) -> dict[str, str]:
    raise AssertionError("setup probed for local providers, which this test does not script")


def _init(
    monkeypatch: pytest.MonkeyPatch, home: Path, detected: dict[str, str], *answers: str,
    output: StringIO | None = None,
) -> dict[str, Any]:
    """Run the real _cmd_init; each prompt takes the next answer, or its own default once none is left."""
    pending = list(answers)
    sink = StringIO() if output is None else output
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=sink, width=200))
    monkeypatch.setattr(
        "rich.prompt.Prompt.ask", lambda *args, **kwargs: pending.pop(0) if pending else kwargs["default"],
    )
    main_mod._cmd_init(argparse.Namespace(force=True, probos_home=str(home), security_profile="strict"))
    assert not pending  # premise: init asked for every scripted answer
    return yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))


def _setup_args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["setup", *argv])


def _timeouts(path: Path) -> dict[str, float]:
    cognitive = load_config(path).cognitive
    return {tier: cognitive.tier_config(tier)["timeout"] for tier in _TEXT_TIERS}


async def _chat_posts(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Send one request through the real client built from ``config_path``; return the paths it POSTed, as sent."""
    posts: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request.url.raw_path.decode("ascii"))  # encoded: /%2F stays /%2F
        # One body both formats read: Ollama's native message and the OpenAI choices.
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={
            "model": "m", "message": message, "done": True,
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}], "usage": {},
        })

    real_client = httpx.AsyncClient

    class _Recorded(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = httpx.MockTransport(answer)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _Recorded)
    client = OpenAICompatibleClient(config=load_config(config_path).cognitive)
    try:
        await client.complete(LLMRequest(prompt="ping", tier="fast"))
    finally:
        await client.close()
    return posts


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("http://localhost:11434/v1", "openai"),
        ("http://localhost:11434/v1/", "openai"),
        ("http://localhost:11434/v1/.", "openai"),
        ("http://localhost:11434", "ollama"),
        ("http://localhost:11434/", "ollama"),
        ("http://localhost:11434//", "ollama"),
        ("http://localhost:11434/./", "ollama"),
        ("http://localhost:11434/v1/..", "ollama"),
        ("http://localhost:11434/a/../", "ollama"),
        ("http://127.0.0.1:8080/v1", "openai"),
        ("http://127.0.0.1:8080", "openai"),
        ("http://localhost:11434/%2F", "openai"),
        ("http://localhost:11434/\\u002f", "openai"),
        ('http://localhost:11434/v1"x', "openai"),
    ],
    # #1414 review: dot segments are judged as httpx sends them (/v1/.. is the root); a port that does not
    # parse is now refused by init (test_init_asks_again_for_a_url_setup_would_refuse). The path is judged
    # encoded, as sent (/%2F is not the root), and a URL with a backslash or a quote is written as typed.
    ids=[
        "ollama-v1", "ollama-v1-slash", "v1-dot", "ollama-root", "ollama-root-slash", "root-double-slash",
        "root-dot", "v1-dotdot", "sub-dotdot", "proxy-v1", "other-root", "encoded-slash", "escaped-slash",
        "double-quote",
    ],
)
def test_init_writes_the_format_the_typed_url_serves(
    typed: str, expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = _init(monkeypatch, tmp_path / "init", {}, typed, "llama3.1:8b")

    assert written["cognitive"]["llm_base_url_fast"] == typed  # premise: init kept the URL as typed
    assert written["cognitive"]["llm_api_format_fast"] == expected


@pytest.mark.parametrize(
    ("detected", "answers", "url", "path"),
    [
        ({"ollama": "http://localhost:11434"}, (), "http://localhost:11434/v1", "/v1/chat/completions"),
        ({}, ("http://localhost:11434", "llama3.1:8b"), "http://localhost:11434", "/api/chat"),
        ({}, ("http://localhost:11434/v1/..", "llama3.1:8b"), "http://localhost:11434/v1/..", "/api/chat"),
        ({}, ("http://localhost:11434/%2F", "llama3.1:8b"), "http://localhost:11434/%2F", "/%2F/chat/completions"),
        (
            {}, ("http://localhost:11434/\\u002f", "llama3.1:8b"), "http://localhost:11434/\\u002f",
            "/\\u002f/chat/completions",
        ),
    ],
    ids=["detected-default", "bare-root", "root-by-dot-segments", "encoded-slash", "escaped-slash"],
)
async def test_the_init_config_reaches_the_api_its_url_serves(
    detected: dict[str, str], answers: tuple[str, ...], url: str, path: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "init"
    written = _init(monkeypatch, home, detected, *answers)
    assert written["cognitive"]["llm_base_url_fast"] == url  # premise: the accepted default, or the typed root

    posts = await _chat_posts(home / "config.yaml", monkeypatch)

    assert posts, "premise: the client sent its request"
    assert posts[0] == path  # before #1414 the detected default posted /v1/api/chat


@pytest.mark.parametrize(
    ("refused", "reason"),
    [
        ("http://localhost:11434?q=1", "must not have a query or fragment"),
        ("http://localhost:11434/v1?q=1", "must not have a query or fragment"),
        ("http://localhost:114340/v1", "is not a valid URL"),
    ],
    ids=["root-query", "v1-query", "port-out-of-range"],
)
def test_init_asks_again_for_a_url_setup_would_refuse(
    refused: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = "http://localhost:11434/v1"
    output = StringIO()

    written = _init(monkeypatch, tmp_path / "init", {}, refused, accepted, "llama3.1:8b", output=output)

    # A query would carry the path the client appends (/?q=1/api/chat); setup's rule refuses it.
    assert written["cognitive"]["llm_base_url_fast"] == accepted
    assert reason in " ".join(output.getvalue().split())


@pytest.mark.parametrize(
    ("refused", "reason"),
    [
        ("http://[v1.a]:11434/", "Invalid IPv6 address"),
        ("http://\u00fc-.example/v1", "Invalid IDNA hostname"),
    ],
    ids=["ipv6-literal", "idna-host"],
)
def test_init_asks_again_for_a_url_the_client_cannot_parse(
    refused: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert provider_setup.normalize_base_url(refused)  # premise: setup's rule alone accepts it
    with pytest.raises(httpx.InvalidURL):
        httpx.URL(refused.rstrip("/") + "/")  # premise: the client could not be built from it
    accepted = "http://localhost:11434/v1"
    output = StringIO()

    written = _init(monkeypatch, tmp_path / "init", {}, refused, accepted, "llama3.1:8b", output=output)

    assert written["cognitive"]["llm_base_url_fast"] == accepted
    assert reason in " ".join(output.getvalue().split())


@pytest.mark.parametrize("model", ['m"x', "m\\tx"], ids=["double-quote", "backslash-t"])
def test_init_writes_the_model_as_typed(model: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    written = _init(monkeypatch, tmp_path / "init", {}, "http://localhost:11434/v1", model)

    # Written raw, a quote broke the file and \t loaded as a tab.
    assert written["cognitive"]["llm_model_fast"] == model


@pytest.mark.parametrize("refused", ["m\x7fx", "m\x85x"], ids=["delete", "next-line"])
def test_init_asks_again_for_a_model_setup_would_refuse(
    refused: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = StringIO()

    written = _init(
        monkeypatch, tmp_path / "init", {}, "http://localhost:11434/v1", refused, "llama3.1:8b", output=output,
    )

    # Setup's model rule (non-empty, printable); JSON would leave these characters raw.
    assert written["cognitive"]["llm_model_fast"] == "llama3.1:8b"
    assert "must be non-empty printable text" in " ".join(output.getvalue().split())


def test_the_scaffold_writes_any_printable_url_and_model_as_given(tmp_path: Path) -> None:
    # The class behind the escaped-slash and double-quote rows: every printable ASCII character, and three beyond.
    for ch in [c for c in string.printable if not c.isspace()] + ["\u00fc", "\u2603", "\U0001f600"]:
        url, model = f"http://localhost:11434/v1/a{ch}b", f"m{ch}x"
        text = main_mod._render_init_config(
            tmp_path, llm_url=url, llm_model=model, api_format="openai", profile="strict",
        )
        cognitive = yaml.safe_load(text)["cognitive"]
        assert (cognitive["llm_base_url_fast"], cognitive["llm_model_fast"]) == (url, model), repr(ch)


def test_the_init_scaffold_gives_every_text_tier_the_shipped_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "init"
    _init(monkeypatch, home, {}, "https://api.example.com/v1", "model-x")
    shipped = yaml.safe_load((_REPO_ROOT / "config" / "system.yaml").read_text(encoding="utf-8"))
    assert shipped["cognitive"]["llm_timeout_seconds"] == 300.0  # premise: the value the scaffold copies

    assert _timeouts(home / "config.yaml") == dict.fromkeys(_TEXT_TIERS, 300.0)


def test_setup_create_path_writes_the_shipped_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    config = tmp_path / "home" / "config.yaml"
    assert not config.exists()  # premise: setup creates it from init's scaffold

    assert main_mod._cmd_setup(_setup_args(*_SETUP_OFFLINE)) == 0

    assert _timeouts(config) == dict.fromkeys(_TEXT_TIERS, 300.0)


def test_setup_on_an_existing_file_adds_no_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    config = tmp_path / "home" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("cognitive:\n  llm_model_fast: old\n", encoding="utf-8")

    assert main_mod._cmd_setup(_setup_args(*_SETUP_OFFLINE)) == 0

    assert "llm_timeout_seconds" not in yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]
    assert load_config(config).cognitive.llm_timeout_seconds == 30.0  # an existing config keeps its default
