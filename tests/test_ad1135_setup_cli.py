"""AD-1135 (#1054): ``probos setup`` behaviour through ``_cmd_setup``.

Arguments come from the real ``_add_setup_parser``; provider traffic goes to an
``httpx.MockTransport`` that records every request, and every call passes one,
so no test can reach a network. Interactive tests answer Rich's real prompts
through a patched ``input()`` and ``getpass``. No home directory, live data
directory or real ``config/system.yaml`` is touched.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import quote, quote_plus

import httpx
import pytest
import rich.prompt
import yaml
from rich.console import Console

import probos.__main__ as main_mod
from probos import provider_setup as ps
from probos.cognitive.image_gen_dispatch import is_image_gen_tier_configured
from probos.cognitive.llm_client import _LLM_TIERS
from probos.cognitive.vision_dispatch import is_vision_tier_configured
from probos.config import load_config
from probos.doctor.checks.config_check import _ConfigCheck
from probos.doctor.checks.security_check import _SecurityCheck
from probos.doctor.protocol import CheckOutcome
from probos.doctor.runner import build_context

_KEY = "sk-ad1135-cli-sentinel-7Q2Z"
# OpenAI's 401 body echoes the key partially masked like this.
_MASKED = f"{_KEY[:8]}{'*' * 20}{_KEY[-4:]}"
_KEY_ENV = "PROBOS_TEST_AD1135_CLI_KEY"
_MODEL = "model-x"
_BASE = "https://llm.example.test/v1"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_REPO_ROOT = Path(__file__).resolve().parents[1]

Handler = Callable[[httpx.Request], httpx.Response]


def _unexpected(what: str) -> Callable[..., object]:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"setup reached {what} that this test did not script")

    return fail


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml",
    )
    for name in ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", _KEY_ENV, *_PROXY_VARS):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    # No prompt, hidden prompt or local-provider probe runs unless the test scripts it (M4).
    monkeypatch.setattr("builtins.input", _unexpected("a terminal prompt"))
    monkeypatch.setattr(getpass, "getpass", _unexpected("a hidden prompt"))
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _unexpected("local provider detection"))


def _completion(content: object) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


def _listing(*model_ids: str) -> Handler:
    return lambda request: httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in model_ids]})


class _Provider:
    """An OpenAI-compatible provider behind ``httpx.MockTransport`` that records every request."""

    def __init__(self, *, listing: Handler | None = None, chat: Handler | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._listing = listing or _listing(_MODEL)
        self._chat = chat or (lambda request: httpx.Response(200, json=_completion("pong")))
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/models"):
            return self._listing(request)
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            return self._chat(request)
        return httpx.Response(404)

    def calls(self) -> list[tuple[str, str]]:
        return [(request.method, request.url.path) for request in self.requests]

    def chat_models(self) -> list[str]:
        return [json.loads(request.content)["model"] for request in self.requests if request.method == "POST"]


def _args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["setup", *argv])


def _setup(provider: _Provider, *argv: str) -> int:
    return main_mod._cmd_setup(_args(*argv), transport=provider.transport)


def _flags(*extra: str, base_url: str = _BASE) -> tuple[str, ...]:
    return (
        "--provider", "custom", "--base-url", base_url, "--api-key-env", _KEY_ENV, "--model", _MODEL, "--yes", *extra,
    )


def _home_config(tmp_path: Path) -> Path:
    return tmp_path / "home" / "config.yaml"


def _cognitive(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["cognitive"]


def _out(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _stall(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


def _echo(status: int) -> Handler:
    return lambda request: httpx.Response(status, json={"error": {"message": f"key {_KEY} ({_MASKED}) refused"}})


def test_cmd_setup_listing_404_but_chat_ok_writes_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(404))

    assert _setup(provider, *_flags()) == 0

    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    assert _cognitive(_home_config(tmp_path))["llm_model_fast"] == _MODEL


def test_cmd_setup_listing_404_and_chat_404_exits_3_with_v1_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(404), chat=lambda request: httpx.Response(404))

    assert _setup(provider, *_flags(base_url="https://llm.example.test")) == 3

    assert provider.calls() == [("GET", "/models"), ("POST", "/chat/completions")]
    out = _out(capsys)
    assert "no OpenAI-compatible API at this base URL" in out
    assert "/v1" in out
    assert "/api/v1" in out
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(("chat_status", "code"), [(200, 0), (404, 3)], ids=["chat-ok", "chat-404"])
def test_cmd_setup_listing_405_is_treated_like_a_404(
    chat_status: int, code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    chat = None if chat_status == 200 else (lambda request: httpx.Response(404))
    provider = _Provider(listing=lambda request: httpx.Response(405), chat=chat)

    assert _setup(provider, *_flags()) == code

    # B5: no listing at this path or method, so the chat check decides, as after a 404.
    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    out = _out(capsys)
    assert "No model listing at this base URL (HTTP 405)" in out
    if code == 0:
        assert _cognitive(_home_config(tmp_path))["llm_model_fast"] == _MODEL
    else:
        assert "no OpenAI-compatible API at this base URL" in out
        assert not (tmp_path / "home").exists()


def test_cmd_setup_unreachable_exits_3_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=_refuse)

    assert _setup(provider, *_flags()) == 3

    assert provider.calls() == [("GET", "/v1/models")]
    assert "could not reach the provider" in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_listing_400_exits_3_without_a_chat_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(400, json={"error": {"message": "bad listing"}}))

    assert _setup(provider, *_flags()) == 3

    # Only OK and NOT_FOUND listings go on to the chat check (contract 3.4 step 5).
    assert provider.calls() == [("GET", "/v1/models")]
    out = _out(capsys)
    assert "rejected the model listing (HTTP 400)" in out
    assert "bad listing" in out  # the capped, redacted body excerpt
    assert not (tmp_path / "home").exists()


def test_cmd_setup_listing_html_exits_3_with_web_page_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(200, text="<!doctype html><title>Home</title>"))

    assert _setup(provider, *_flags()) == 3

    assert provider.calls() == [("GET", "/v1/models")]
    assert "a web page may have answered instead of the API" in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_empty_chat_reply_exits_3_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(chat=lambda request: httpx.Response(200, json=_completion("")))

    assert _setup(provider, *_flags()) == 3

    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    out = _out(capsys)
    assert "returned no text for model 'model-x'" in out
    assert "degraded" in out
    assert not (tmp_path / "home").exists()


def test_cmd_setup_skip_validation_writes_without_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(500), chat=lambda request: httpx.Response(500))

    code = _setup(provider, *_flags("--skip-validation"))

    assert (code, provider.calls()) == (0, [])
    assert _cognitive(_home_config(tmp_path))["llm_api_key_deep"] == _KEY
    assert "--skip-validation" in _out(capsys)


@pytest.mark.parametrize(
    ("model_flags", "probed"),
    [
        (("--model-fast", "model-a", "--model-standard", "model-b", "--model-deep", "model-c"),
         ["model-a", "model-b", "model-c"]),
        (("--model", "model-x"), ["model-x"]),
        (("--model", "model-x", "--model-deep", "model-d"), ["model-x", "model-d"]),
    ],
    ids=["three-distinct", "one-shared", "deep-override"],
)
def test_cmd_setup_distinct_tier_models_are_each_checked_once(
    model_flags: tuple[str, ...], probed: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, *model_flags, "--yes")

    assert code == 0
    assert provider.chat_models() == probed
    cognitive = _cognitive(_home_config(tmp_path))
    assert {cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS} == set(probed)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://llm.example.test/v1",
        "llm.example.test/v1",
        "https:///v1",
        "https://:8080/v1",
        "https://user:secret@llm.example.test/v1",
        "https://user@llm.example.test/v1",
        "https://@llm.example.test/v1",
        "https://llm.example.test/v1?api-version=1",
        "https://llm.example.test/v1?",
        "https://llm.example.test/v1#part",
        " https://llm.example.test/v1",
        "https://llm.example.test/v1 ",
        "https://llm.example.test /v1",
        "https://llm.example.test/v1\n",
        "https://llm.example.test/v1\t",
        "https://llm.example.test/\x1bv1",
        "https://llm.example.test:0/v1",
        "https://llm.example.test:99999/v1",
        "https://llm.example.test:port/v1",
        "https://[::1/v1",
        "",
    ],
)
def test_normalize_base_url_rejects_userinfo_scheme_query_and_whitespace(url: str) -> None:
    with pytest.raises(ps.SetupInputError):
        ps.normalize_base_url(url)


@pytest.mark.parametrize(
    ("url", "normalised"),
    [
        ("https://llm.example.test/v1///", "https://llm.example.test/v1"),
        ("http://[::1]:11434/v1/", "http://[::1]:11434/v1"),
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1"),
    ],
)
def test_normalize_base_url_strips_trailing_slashes(url: str, normalised: str) -> None:
    assert ps.normalize_base_url(url) == normalised


def test_cmd_setup_invalid_base_url_exits_2_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    code = _setup(provider, *_flags(base_url="https://operator:hunter2@llm.example.test/v1"))

    assert (code, provider.calls()) == (2, [])
    assert "hunter2" not in capsys.readouterr().out
    assert not (tmp_path / "home").exists()


def test_cmd_setup_plain_http_remote_with_key_exits_2_without_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    code = _setup(provider, *_flags(base_url="http://llm.example.test/v1"))

    assert (code, provider.calls()) == (2, [])
    assert "--allow-insecure-http" in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_plain_http_remote_with_key_proceeds_with_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    assert _setup(provider, *_flags("--allow-insecure-http", base_url="http://llm.example.test/v1")) == 0

    assert {request.headers.get("authorization") for request in provider.requests} == {f"Bearer {_KEY}"}
    assert _cognitive(_home_config(tmp_path))["llm_base_url_standard"] == "http://llm.example.test/v1"


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:1234/v1", "http://localhost:1234/v1", "http://[::1]:1234/v1", "http://127.8.9.10/v1"],
    ids=["ipv4", "localhost", "ipv6", "loopback-block"],
)
def test_cmd_setup_plain_http_loopback_with_key_proceeds(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    assert _setup(provider, *_flags(base_url=base_url)) == 0

    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    assert _cognitive(_home_config(tmp_path))["llm_base_url_fast"] == base_url


def test_cmd_setup_plain_http_remote_without_key_proceeds(tmp_path: Path) -> None:
    provider = _Provider()

    code = _setup(provider, "--provider", "custom", "--base-url", "http://llm.example.test/v1", "--model", _MODEL, "--yes")

    assert code == 0
    assert len(provider.requests) == 2
    assert all("authorization" not in request.headers for request in provider.requests)


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_cmd_setup_api_key_env_unset_exits_1(
    value: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    if value is not None:
        monkeypatch.setenv(_KEY_ENV, value)
    provider = _Provider()

    assert (_setup(provider, *_flags()), provider.calls()) == (1, [])

    assert _KEY_ENV in _out(capsys)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(
    "bad",
    ["\r", "\n", "\x00", "\x1b[2J", "\u200b", "\u00e9"],
    ids=["carriage-return", "newline", "nul", "escape", "zero-width-space", "non-ascii"],
)
def test_cmd_setup_api_key_control_characters_exits_2(
    bad: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    key = f"sk-ad1135-unsendable{bad}tail"
    provider = _Provider()

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key", key, "--model", _MODEL, "--yes")

    assert (code, provider.calls()) == (2, [])
    out = capsys.readouterr().out
    assert "API key" in out
    assert "sk-ad1135-unsendable" not in out
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(
    ("argv", "clash"),
    [
        (("--api-key", "k", "--api-key-env", "VAR"), "--api-key-env"),
        (("--probos-home", "h", "--config", "c.yaml"), "--config"),
    ],
    ids=["key-sources", "targets"],
)
def test_add_setup_parser_mutually_exclusive_options_exit_2(
    argv: tuple[str, ...], clash: str, capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _args("--provider", "custom", *argv)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "not allowed with argument" in err
    assert clash in err


def _masked_401(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {_MASKED}."}})


@pytest.mark.parametrize(
    ("listing", "chat", "extra", "code", "body_shown"),
    [
        (None, None, (), 0, False),
        (None, None, ("--skip-validation",), 0, False),
        (_masked_401, None, (), 3, False),
        (_echo(403), None, (), 3, False),
        # This case was body_shown=True while the Location was shown key-redacted; B6/H1 shows none of it.
        (lambda request: httpx.Response(302, headers={"Location": f"https://login.example.test/?key={_KEY}"}),
         None, (), 3, False),
        (_echo(429), None, (), 3, True),
        (_echo(503), None, (), 3, True),
        (lambda request: httpx.Response(200, text=f"<html>{_KEY} {_MASKED}</html>"), None, (), 3, False),
        (_refuse, None, (), 3, False),
        (_stall, None, (), 3, False),
        (None, _masked_401, (), 3, False),
        (None, _echo(400), (), 3, True),
        (None, _echo(404), (), 3, False),
        (None, _echo(500), (), 3, True),
        (None, lambda request: httpx.Response(200, json=_completion("")), (), 3, False),
        (None, lambda request: httpx.Response(200, text=f"{_KEY} {_MASKED}"), (), 3, False),
    ],
    ids=[
        "success", "skip-validation", "listing-401-masked", "listing-403", "listing-302", "listing-429",
        "listing-503", "listing-html", "unreachable", "timeout", "chat-401-masked", "chat-400", "chat-404",
        "chat-500", "chat-empty", "chat-not-json",
    ],
)
def test_cmd_setup_never_prints_or_logs_the_key(
    listing: Handler | None,
    chat: Handler | None,
    extra: tuple[str, ...],
    code: int,
    body_shown: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=listing, chat=chat)

    assert _setup(provider, *_flags(*extra)) == code

    if "--skip-validation" not in extra:
        assert provider.requests[0].headers["authorization"] == f"Bearer {_KEY}"  # premise: the key was sent
    out, err = capsys.readouterr()
    for text in (out, err, caplog.text):
        assert _KEY not in _squash(text)
        # Only 401/403 bodies are suppressed; other excerpts redact the full key alone (contract Q3).
        if not body_shown:
            assert _MASKED not in _squash(text)
    if body_shown:
        assert "<redacted>" in out  # premise: this excerpt was shown, and the key in it replaced


# "/", " " and "+" each encode, so the key's literal, percent-encoded and base64 forms all differ (B6/H1).
_ENC_KEY = "sk-ad1135/cli enc+4R"
_ENC_FORMS = (
    _ENC_KEY,
    quote(_ENC_KEY, safe=""),
    quote_plus(_ENC_KEY),
    base64.b64encode(_ENC_KEY.encode()).decode(),
    base64.b64encode(b"Bearer " + _ENC_KEY.encode()).decode(),
)


def test_cmd_setup_redirect_never_prints_the_location_or_an_encoded_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    location = f"https://login.example.test/steal/{_ENC_FORMS[1]}?k={_ENC_KEY}&b={_ENC_FORMS[3]}"
    provider = _Provider(listing=lambda request: httpx.Response(302, headers={"Location": location}))

    assert _setup(provider, *_flags()) == 3

    assert len(set(_ENC_FORMS)) == len(_ENC_FORMS)  # premise: no two forms coincide
    assert provider.requests[0].headers["authorization"] == f"Bearer {_ENC_KEY}"  # premise: the key was sent
    assert provider.calls() == [("GET", "/v1/models")]  # the redirect was not followed
    out, err = capsys.readouterr()
    assert "does not forward your API key to redirects" in " ".join(out.split())
    for text in (out, err, caplog.text):
        for fragment in (*_ENC_FORMS, "login.example.test", "/steal", "?k=", location):
            assert fragment not in text
            assert _squash(fragment) not in _squash(text)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_summary_reports_key_presence_not_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    assert _setup(_Provider(), *_flags()) == 0
    with_key = _out(capsys)
    assert "API key: present" in with_key
    assert _KEY not in _squash(with_key)

    keyless = tmp_path / "keyless.yaml"
    code = _setup(
        _Provider(), "--provider", "custom", "--base-url", "http://127.0.0.1:1234/v1", "--model", _MODEL, "--yes",
        "--config", str(keyless),
    )
    assert code == 0
    assert "API key: not set" in _out(capsys)
    assert _cognitive(keyless)["llm_api_key_fast"] == ""


@pytest.mark.parametrize("env_value", [None, "http://127.0.0.1:9/v1"], ids=["unset", "set"])
def test_cmd_setup_notes_probos_llm_url_when_set(
    env_value: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    if env_value is not None:
        monkeypatch.setenv("PROBOS_LLM_URL", env_value)

    assert _setup(_Provider(), *_flags()) == 0

    out = _out(capsys)
    assert ("PROBOS_LLM_URL" in out) is (env_value is not None)
    assert ("without their own endpoint" in out) is (env_value is not None)


def test_cmd_setup_long_target_path_prints_unbroken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    monkeypatch.setenv("COLUMNS", "80")
    target = tmp_path / ("long-" * 20) / "config.yaml"
    assert len(str(target)) > 120  # premise: the path cannot fit on one 80-column line

    assert _setup(_Provider(), *_flags("--config", str(target))) == 0

    assert str(target) in capsys.readouterr().out


@pytest.mark.parametrize(
    ("home", "named", "silent"),
    [
        (PurePosixPath('/srv/probos"home'), "double quote", False),
        (PurePosixPath("/srv/probos\\thome"), "backslash", True),
        (PurePosixPath("/srv/probos\\\\home"), "backslash", True),
        (PurePosixPath("/srv/probos\\qhome"), "backslash", False),
        (PurePosixPath("/srv/probos\u0085home"), "non-printable", True),
    ],
    ids=["quote", "backslash-t", "double-backslash", "backslash-q", "next-line"],
)
def test_setup_scaffold_refuses_home_paths_the_init_template_cannot_carry(
    home: PurePosixPath, named: str, silent: bool,
) -> None:
    # Render inputs are pure POSIX paths so every case runs on every OS.
    scaffold = main_mod._render_init_config(
        home, llm_url="http://127.0.0.1:8080/v1", llm_model="unset", api_format="openai", profile="strict",
        generated_by="probos setup",
    )
    values = ps.managed_values(ps.ProviderChoice(provider="custom", base_url=_BASE, models={t: _MODEL for t in ps.TEXT_TIERS}))
    if silent:
        # Premise: the editor's own proof accepts this scaffold, so only the repo_path check can refuse it.
        ps.apply_managed_values(scaffold, values)

    with pytest.raises(ps.SetupInputError) as exc_info:
        main_mod._setup_scaffold(home)

    assert named in str(exc_info.value)


def test_setup_scaffold_keeps_a_plain_home_path() -> None:
    home = PurePosixPath("/srv/probos home/\u00fcn\u00efcode")

    scaffold = main_mod._setup_scaffold(home)

    assert yaml.safe_load(scaffold)["knowledge"]["repo_path"] == "/srv/probos home/\u00fcn\u00efcode/knowledge"


@pytest.mark.skipif(sys.platform == "win32", reason='Windows forbids " in names and treats \\ as a separator')
@pytest.mark.parametrize("name", ['probos"home', "probos\\thome"], ids=["quote", "backslash-t"])
def test_cmd_setup_create_path_home_with_quote_or_backslash_exits_2(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    home = tmp_path / name
    provider = _Provider()

    assert (_setup(provider, *_flags("--probos-home", str(home))), provider.calls()) == (2, [])

    assert not home.exists()


_HAND_EDITED = (
    b"# hand-edited ProbOS config\r\n"
    b"system:\r\n"
    b'  log_level: "INFO"\r\n'
    b"cognitive:\r\n"
    b'  llm_base_url_fast: "http://127.0.0.1:8080/v1"  # the proxy\r\n'
    b'  llm_model_fast: "claude-sonnet-4.6"\r\n'
    b"  llm_timeout_seconds: 300.0\r\n"
    b"self_mod:\r\n"
    b"  enabled: false\r\n"
)


def _existing(tmp_path: Path, data: bytes) -> Path:
    config = _home_config(tmp_path)
    config.parent.mkdir(parents=True)
    config.write_bytes(data)
    return config


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _backups(config: Path) -> list[Path]:
    return sorted(config.parent.glob(f"{config.name}.bak-*"))


def test_cmd_setup_refused_edit_exits_4_and_leaves_file_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, b"cognitive:\r\n  llm_model_fast: a\r\n  llm_model_fast: b\r\n")
    digest = _digest(config)
    provider = _Provider()

    assert (_setup(provider, *_flags()), provider.calls()) == (4, [])

    assert _digest(config) == digest
    assert _names(config.parent) == ["config.yaml"]
    out = _out(capsys)
    assert "sets llm_model_fast more than once" in out
    assert "--force" in out


def test_cmd_setup_force_rewrites_with_backup_and_keeps_every_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    original = (
        b"# this comment does not survive --force\r\n"
        b"system: {log_level: DEBUG}\r\n"
        b"cognitive: {llm_timeout_seconds: 120.0, default_llm_tier: deep, llm_model_fast: old}\r\n"
        b"self_mod:\r\n"
        b"  enabled: false\r\n"
    )
    config = _existing(tmp_path, original)
    before = load_config(config).model_dump()
    provider = _Provider()
    assert (_setup(provider, *_flags()), provider.calls()) == (4, [])  # premise: refused without --force

    assert _setup(provider, *_flags("--force")) == 0

    (backup,) = _backups(config)
    assert backup.read_bytes() == original
    after = load_config(config).model_dump()
    assert {name for name in before if name != "cognitive" and after[name] != before[name]} == set()
    managed = set(ps.managed_values(ps.ProviderChoice("custom", _BASE, {t: _MODEL for t in ps.TEXT_TIERS})))
    assert {k for k in before["cognitive"] if before["cognitive"][k] != after["cognitive"][k]} <= managed
    assert (after["cognitive"]["llm_timeout_seconds"], after["cognitive"]["default_llm_tier"]) == (120.0, "deep")
    assert (after["system"]["log_level"], after["self_mod"]["enabled"]) == ("DEBUG", False)
    written = config.read_bytes()
    assert b"does not survive" not in written
    assert b"\n" not in written.replace(b"\r\n", b"")  # the file's CRLF is kept


@pytest.mark.parametrize(
    ("data", "reason"),
    [(b"cognitive: {llm_model_fast: [\r\n", "not valid YAML"), (b"cognitive:\r\n  x: \xff\xfe\r\n", "not valid UTF-8")],
    ids=["yaml", "utf-8"],
)
def test_cmd_setup_invalid_yaml_exits_4_even_with_force(
    data: bytes, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, data)
    provider = _Provider()

    assert (_setup(provider, *_flags("--force")), provider.calls()) == (4, [])

    assert config.read_bytes() == data
    assert _names(config.parent) == ["config.yaml"]
    assert reason in _out(capsys)


def test_cmd_setup_invalid_yaml_exits_4_before_the_flags_are_read(tmp_path: Path) -> None:
    config = _existing(tmp_path, b"cognitive: {llm_model_fast: [\r\n")
    provider = _Provider()

    # No --provider (exit 1 once the flags are read): the unreadable file is reported first (contract 3.4 step 1).
    assert (_setup(provider, "--yes"), provider.calls()) == (4, [])

    assert _names(config.parent) == ["config.yaml"]


def test_cmd_setup_existing_file_writes_timestamped_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _HAND_EDITED)

    assert _setup(_Provider(), *_flags()) == 0

    (backup,) = _backups(config)
    assert re.fullmatch(r"config\.yaml\.bak-\d{8}T\d{6}Z", backup.name)
    assert backup.read_bytes() == _HAND_EDITED
    assert config.read_bytes() != _HAND_EDITED
    assert _cognitive(config)["llm_model_standard"] == _MODEL
    assert f"Backup: {backup}" in capsys.readouterr().out


def test_cmd_setup_rerun_with_same_values_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _HAND_EDITED)
    assert _setup(_Provider(), *_flags()) == 0
    digest, names = _digest(config), _names(config.parent)
    assert len(_backups(config)) == 1
    capsys.readouterr()
    provider = _Provider()

    assert _setup(provider, *_flags()) == 0

    assert (_digest(config), _names(config.parent)) == (digest, names)
    assert "already uses this provider" in _out(capsys)
    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]  # still checked


@pytest.mark.parametrize("fail_backup", [False, True], ids=["final-replace", "every-replace"])
def test_cmd_setup_replace_failure_leaves_target_byte_identical(
    fail_backup: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _HAND_EDITED)
    real_replace = os.replace
    attempts: list[str] = []

    def replace(src: object, dst: object) -> None:
        attempts.append(Path(dst).name)
        if fail_backup or Path(dst) == config:
            raise PermissionError("simulated replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(ps.os, "replace", replace)

    assert _setup(_Provider(), *_flags()) == 4

    assert config.read_bytes() == _HAND_EDITED
    assert not [name for name in _names(config.parent) if name.endswith(".tmp")]
    if fail_backup:
        assert (len(attempts), _backups(config)) == (1, [])
    else:
        # The backup copy was made before the final replace failed; it holds the untouched original.
        assert attempts[-1] == "config.yaml"
        assert [backup.read_bytes() for backup in _backups(config)] == [_HAND_EDITED]
    assert "Could not write" in _out(capsys)


def test_cmd_setup_final_replace_failure_names_the_kept_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _HAND_EDITED)
    real_replace = os.replace

    def replace(src: object, dst: object) -> None:
        if Path(dst) == config:
            raise PermissionError("simulated final replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(ps.os, "replace", replace)

    assert _setup(_Provider(), *_flags()) == 4

    (backup,) = _backups(config)
    assert backup.read_bytes() == _HAND_EDITED == config.read_bytes()
    out = capsys.readouterr().out
    assert "simulated final replace failure" in out
    assert str(backup) in out  # B5: the exit-4 message names the backup it kept


def test_cmd_setup_result_that_does_not_load_exits_4_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    original = b"cognitive:\r\n  llm_health_min_consecutive_healthy: 0\r\n"
    config = _existing(tmp_path, original)

    assert _setup(_Provider(), *_flags("--skip-validation")) == 4

    assert config.read_bytes() == original
    assert _names(config.parent) == ["config.yaml"]
    out = _out(capsys)
    assert "does not load: cognitive.llm_health_min_consecutive_healthy" in out
    assert _KEY not in _squash(out)


# ----- B7: an optional tier with a model keeps the shared llm_base_url it uses where it is -----

_OLD_SHARED = "http://127.0.0.1:8080/v1"
_OPTIONAL_TIERS = tuple(tier for tier in _LLM_TIERS if tier not in ps.TEXT_TIERS)
_SHARED_URL_NOTE = (
    "Left the shared llm_base_url unchanged because vision (model 'qwen-vl') uses it; "
    "give vision its own llm_base_url_vision to move it"
)


def _endpoint(config: Path, tier: str) -> tuple[str, str | None]:
    resolved = load_config(config).cognitive.tier_config(tier)
    return resolved["base_url"], resolved["model"]


def _optional_endpoints(config: Path) -> dict[str, tuple[str, str | None]]:
    return {tier: _endpoint(config, tier) for tier in _OPTIONAL_TIERS}


def _configured(config: Path) -> dict[str, bool]:
    # Each tier's runtime consumer's own check; this read image_gen through is_vision_tier_configured too (B8).
    cognitive = load_config(config).cognitive
    return {
        tier: is_image_gen_tier_configured(cognitive) if tier == "image_gen" else is_vision_tier_configured(cognitive, tier)
        for tier in _OPTIONAL_TIERS
    }


def _managed_old(*extra: str) -> bytes:
    # Every managed key, each set to a value setup changes, then the ``extra`` lines.
    lines = ["cognitive:", f"  llm_base_url: {_OLD_SHARED}"]
    for tier in ps.TEXT_TIERS:
        lines += [
            f"  llm_base_url_{tier}: {_OLD_SHARED}",
            f"  llm_api_key_{tier}: sk-old",
            f"  llm_model_{tier}: old-model",
            f"  llm_api_format_{tier}: ollama",
        ]
    return "".join(f"{line}\r\n" for line in [*lines, *extra]).encode("utf-8")


def _changed_keys(old: bytes, new: bytes) -> list[str]:
    old_lines, new_lines = old.split(b"\r\n"), new.split(b"\r\n")
    assert len(new_lines) == len(old_lines)  # every managed key edited in place; nothing inserted
    return [before.decode().split(":")[0].strip() for before, after in zip(old_lines, new_lines) if before != after]


def test_cmd_setup_leaves_the_shared_url_in_place_for_an_optional_tier_that_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _managed_old("  llm_model_vision: qwen-vl", "  llm_timeout_vision: 120.0"))
    old, before, configured = config.read_bytes(), _optional_endpoints(config), _configured(config)
    assert (before["vision"], configured["vision"]) == ((_OLD_SHARED, "qwen-vl"), False)  # premise: vision uses it
    provider = _Provider()

    assert _setup(provider, *_flags()) == 0

    # This test first pinned vision to its own llm_base_url_vision (B6), which made it configured; B7 retains instead.
    assert _configured(config) == configured
    assert _optional_endpoints(config) == before
    assert load_config(config).cognitive.llm_base_url == _OLD_SHARED
    assert {tier: _endpoint(config, tier) for tier in ps.TEXT_TIERS} == dict.fromkeys(ps.TEXT_TIERS, (_BASE, _MODEL))
    changed = _changed_keys(old, config.read_bytes())
    assert (len(changed), "llm_base_url" in changed) == (12, False)
    assert provider.chat_models() == [_MODEL]  # the vision model was not sent to the new provider
    assert _SHARED_URL_NOTE in _out(capsys)


def test_cmd_setup_optional_tier_without_a_model_follows_the_new_shared_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _managed_old("  llm_timeout_compute_use: 60.0"))
    old, configured = config.read_bytes(), _configured(config)
    assert _endpoint(config, "compute_use") == (_OLD_SHARED, None)  # premise: no model, the shared URL

    assert _setup(_Provider(), *_flags()) == 0

    assert _endpoint(config, "compute_use") == (_BASE, None)
    assert "llm_base_url_compute_use" not in _cognitive(config)
    assert _configured(config) == configured
    assert len(_changed_keys(old, config.read_bytes())) == 13
    assert "Left the shared llm_base_url" not in _out(capsys)


def test_cmd_setup_force_rewrite_applies_the_same_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, b"cognitive: {llm_base_url: 'http://127.0.0.1:8080/v1', llm_model_vision: qwen-vl}\r\n")
    before, configured = _optional_endpoints(config), _configured(config)
    provider = _Provider()
    assert (_setup(provider, *_flags()), provider.calls()) == (4, [])  # premise: refused in place

    assert _setup(provider, *_flags("--force")) == 0

    assert (_configured(config), _optional_endpoints(config)) == (configured, before)
    assert load_config(config).cognitive.llm_base_url == _OLD_SHARED
    assert _endpoint(config, "fast") == (_BASE, _MODEL)
    assert _SHARED_URL_NOTE in _out(capsys)


def test_cmd_setup_create_path_writes_all_13_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)

    assert _setup(_Provider(), *_flags()) == 0

    cognitive = _cognitive(_home_config(tmp_path))
    values = ps.managed_values(ps.ProviderChoice("custom", _BASE, {t: _MODEL for t in ps.TEXT_TIERS}, _KEY))
    assert (len(values), {key: cognitive[key] for key in values}) == (13, values)
    urls = {key for key in cognitive if key.startswith("llm_base_url_")}
    assert urls == {f"llm_base_url_{tier}" for tier in ps.TEXT_TIERS}
    assert "Left the shared llm_base_url" not in _out(capsys)


def test_cmd_setup_shipped_config_copy_writes_all_13_keys_and_changes_only_managed_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    # The shipped config is copied, never edited in place.
    copy = tmp_path / "system.yaml"
    copy.write_bytes((_REPO_ROOT / "config" / "system.yaml").read_bytes())
    old = copy.read_bytes().decode("utf-8")
    before, configured = _optional_endpoints(copy), _configured(copy)
    shipped = load_config(copy).cognitive
    # Premise: the shipped vision tier has a model and its own URL, so it does not use the shared URL.
    assert (bool(shipped.llm_model_vision), bool(shipped.llm_base_url_vision)) == (True, True)

    assert _setup(_Provider(), *_flags("--config", str(copy))) == 0

    new = copy.read_bytes().decode("utf-8")
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    assert len(new_lines) == len(old_lines)  # nothing inserted: every managed key edited in place
    choice = ps.ProviderChoice("custom", _BASE, {t: _MODEL for t in ps.TEXT_TIERS})
    managed = tuple(f"  {key}:" for key in ps.managed_values(choice))
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert changed and all(old_lines[i].startswith(managed) for i in changed)
    assert load_config(copy).cognitive.llm_base_url == _BASE  # no tier uses the shared URL, so it is written
    assert _configured(copy) == configured
    # A tier with a model keeps its own endpoint; one without follows the new shared URL.
    assert _optional_endpoints(copy) == {tier: point if point[1] else (_BASE, None) for tier, point in before.items()}
    assert "Left the shared llm_base_url" not in _out(capsys)


def test_cmd_setup_rerun_keeps_the_retained_shared_url_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, b"cognitive:\r\n  llm_base_url: http://127.0.0.1:8080/v1\r\n  llm_model_vision: qwen-vl\r\n")
    configured = _configured(config)
    assert _setup(_Provider(), *_flags()) == 0
    digest = _digest(config)
    capsys.readouterr()

    assert _setup(_Provider(), *_flags()) == 0

    assert _digest(config) == digest
    assert "already uses this provider" in _out(capsys)
    assert (load_config(config).cognitive.llm_base_url, _configured(config)) == (_OLD_SHARED, configured)


def test_cmd_setup_optional_tier_settings_that_do_not_load_exit_4_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    original = b"cognitive:\r\n  llm_model_vision: [a, b]\r\n"
    config = _existing(tmp_path, original)
    provider = _Provider()

    assert (_setup(provider, *_flags("--force")), provider.calls()) == (4, [])

    assert config.read_bytes() == original
    assert _names(config.parent) == ["config.yaml"]
    assert "llm_model_vision" in _out(capsys)


def test_cmd_setup_creating_home_config_over_repo_default_requires_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    repo_default = tmp_path / "repo" / "config" / "system.yaml"
    repo_default.parent.mkdir(parents=True)
    repo_default.write_text("system:\n  name: from-repo\n", encoding="utf-8")
    assert main_mod._resolve_config_path(None) == repo_default  # premise: bare serve loads the repo file today
    flags = tuple(flag for flag in _flags() if flag != "--yes")
    provider = _Provider()
    # M4 made a run without --yes interactive: the guard asks, and Enter takes its default, No.
    terminal = _Terminal(monkeypatch, [""], provider=provider)

    assert (_setup(provider, *flags), provider.calls()) == (1, [])
    (ask,) = terminal.asked
    assert (ask.kind, ask.kwargs["default"]) == ("Confirm", False)
    out = capsys.readouterr().out
    assert str(repo_default) in out
    assert str(_home_config(tmp_path)) in out
    assert "Nothing was written" in out
    assert not (tmp_path / "home").exists()

    assert _setup(provider, *flags, "--yes") == 0
    assert len(terminal.asked) == 1  # --yes confirmed without asking
    assert main_mod._resolve_config_path(None) == _home_config(tmp_path)
    assert "fall back to their defaults" in _out(capsys)


def test_cmd_setup_custom_probos_home_prints_serve_config_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    target = tmp_path / "custom-home" / "config.yaml"

    assert _setup(_Provider(), *_flags("--probos-home", str(target.parent))) == 0

    assert target.exists()
    assert not (tmp_path / "home").exists()
    out = capsys.readouterr().out
    assert f'probos serve --config "{target}"' in out
    assert f'probos --config "{target}"' in out
    assert "probos doctor" not in out  # doctor reads only the default home config


def test_cmd_setup_config_flag_targets_the_explicit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    explicit = tmp_path / "elsewhere" / "node-1.yaml"

    assert _setup(_Provider(), *_flags("--config", str(explicit))) == 0
    assert _cognitive(explicit)["llm_model_deep"] == _MODEL
    assert not (tmp_path / "home").exists()
    assert f'probos serve --config "{explicit}"' in capsys.readouterr().out

    explicit.write_bytes(_HAND_EDITED)
    assert _setup(_Provider(), *_flags("--config", str(explicit))) == 0
    assert [backup.read_bytes() for backup in _backups(explicit)] == [_HAND_EDITED]


@pytest.mark.parametrize("with_key", [True, False], ids=["key", "no-key"])
def test_cmd_setup_repo_default_target_with_key_warns_not_to_commit(
    with_key: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    repo_default = tmp_path / "repo" / "config" / "system.yaml"
    repo_default.parent.mkdir(parents=True)
    repo_default.write_bytes(_HAND_EDITED)
    if with_key:
        monkeypatch.setenv(_KEY_ENV, _KEY)
        argv = _flags("--config", str(repo_default))
    else:
        argv = ("--provider", "custom", "--base-url", _BASE, "--model", _MODEL, "--yes", "--config", str(repo_default))

    assert _setup(_Provider(), *argv) == 0

    out = _out(capsys)
    assert ("do not commit it with the API key" in out) is with_key
    assert "probos serve --config" not in out  # bare serve already loads this file


async def test_setup_created_config_passes_doctor_config_and_security_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    assert _setup(_Provider(), *_flags()) == 0
    out = _out(capsys)
    assert "probos doctor" in out  # the default home config is the one doctor reads
    assert "probos serve --config" not in out

    context = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data")

    assert (context.config_path, context.config is not None) == (_home_config(tmp_path), True)
    assert (await _ConfigCheck().run(context)).outcome is CheckOutcome.OK
    assert (await _SecurityCheck().run(context)).outcome is CheckOutcome.OK


# ----- M4: presets and the interactive flow -----


class _Ask(NamedTuple):
    kind: str
    prompt: str
    kwargs: dict[str, object]
    sent: int  # provider requests sent before this prompt was shown


class _Terminal:
    """Scripted answers for setup's real prompts, recording each prompt as it is asked.

    Rich's own ``Prompt.ask`` and ``Confirm.ask`` run, wrapped only to record their
    arguments; ``lines`` reach them through ``input()``, where Rich reads a typed line,
    and ``secrets`` answer ``getpass.getpass``. An exception in ``lines`` is raised, and
    running out of answers raises EOFError, as a closed terminal does.
    """

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        lines: Sequence[str | BaseException] = (),
        *,
        secrets: Sequence[str] = (),
        provider: _Provider | None = None,
    ) -> None:
        self._lines = list(lines)
        self._secrets = list(secrets)
        self._provider = provider
        self.asked: list[_Ask] = []
        monkeypatch.setattr("builtins.input", self._input)
        monkeypatch.setattr(getpass, "getpass", self._getpass)
        for prompt_class in (rich.prompt.Prompt, rich.prompt.Confirm):
            monkeypatch.setattr(prompt_class, "ask", self._recording(prompt_class.__name__, prompt_class.ask))

    def _sent(self) -> int:
        return len(self._provider.requests) if self._provider is not None else 0

    def _recording(self, kind: str, real_ask: Callable[..., object]) -> Callable[..., object]:
        def ask(prompt: object = "", **kwargs: object) -> object:
            self.asked.append(_Ask(kind, str(prompt), dict(kwargs), self._sent()))
            return real_ask(prompt, **kwargs)

        return ask

    def _input(self, prompt: object = "") -> str:
        if not self._lines:
            raise EOFError
        line = self._lines.pop(0)
        if isinstance(line, BaseException):
            raise line
        return line

    def _getpass(self, prompt: str = "Password: ", stream: object = None) -> str:
        self.asked.append(_Ask("getpass", prompt, {}, self._sent()))
        if not self._secrets:
            raise EOFError
        return self._secrets.pop(0)

    def unused(self) -> tuple[int, int]:
        return len(self._lines), len(self._secrets)

    def kinds(self) -> list[str]:
        return [ask.kind for ask in self.asked]


def _interactive(*extra: str, base_url: str = _BASE) -> tuple[str, ...]:
    return tuple(flag for flag in _flags(*extra, base_url=base_url) if flag != "--yes")


def test_presets_cover_five_providers_with_verified_base_urls(tmp_path: Path) -> None:
    # The shipped config is copied, never loaded in place.
    shipped = tmp_path / "system.yaml"
    shipped.write_bytes((_REPO_ROOT / "config" / "system.yaml").read_bytes())
    cognitive = yaml.safe_load(shipped.read_text(encoding="utf-8"))["cognitive"]

    assert list(ps.PRESETS) == ["openai", "openrouter", "ollama", "copilot-proxy", "custom"]
    assert {name: (preset.name, preset.base_url) for name, preset in ps.PRESETS.items()} == {
        "openai": ("openai", "https://api.openai.com/v1"),
        "openrouter": ("openrouter", "https://openrouter.ai/api/v1"),
        "ollama": ("ollama", "http://localhost:11434/v1"),
        "copilot-proxy": ("copilot-proxy", "http://127.0.0.1:8080/v1"),
        "custom": ("custom", ""),
    }
    assert {name: (preset.requires_key, preset.key_env) for name, preset in ps.PRESETS.items()} == {
        "openai": (True, "OPENAI_API_KEY"),
        "openrouter": (True, "OPENROUTER_API_KEY"),
        "ollama": (False, None),
        "copilot-proxy": (False, None),
        "custom": (False, None),
    }
    proxy = ps.PRESETS["copilot-proxy"]
    # The copilot-proxy preset tracks the shipped defaults instead of restating them.
    assert proxy.base_url == cognitive["llm_base_url"]
    assert dict(proxy.models) == {tier: cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS}
    assert all(ps.normalize_base_url(preset.base_url) == preset.base_url for preset in ps.PRESETS.values() if preset.base_url)


def test_presets_cloud_providers_ship_no_default_model() -> None:
    assert {name: dict(preset.models) for name, preset in ps.PRESETS.items() if name != "copilot-proxy"} == {
        "openai": {}, "openrouter": {}, "ollama": {}, "custom": {},
    }


def test_cmd_setup_interactive_openai_prompts_hidden_key_and_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: {})
    provider = _Provider(listing=_listing("gpt-test-mini", "gpt-test-large"))
    # Enter (the openai default), the model, Enter (one model for every tier), Enter (write).
    terminal = _Terminal(monkeypatch, ["", "gpt-test-large", "", ""], secrets=[_KEY], provider=provider)

    assert _setup(provider) == 0

    assert terminal.unused() == (0, 0)  # premise: every scripted answer was read by a real prompt
    choose, key, model, per_tier, write = terminal.asked
    assert (choose.kind, choose.kwargs["default"], choose.kwargs["choices"]) == ("Prompt", "openai", list(ps.PRESETS))
    assert (key.kind, key.sent) == ("getpass", 0)
    assert "hidden" in key.prompt
    assert (model.kind, "default" in model.kwargs, model.sent) == ("Prompt", False, 1)  # suggestions listed first
    assert (per_tier.kind, per_tier.kwargs["default"]) == ("Confirm", False)
    assert (write.kind, write.kwargs["default"], write.sent) == ("Confirm", True, 2)  # checked before asking
    cognitive = _cognitive(_home_config(tmp_path))
    assert {cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS} == {"gpt-test-large"}
    assert {cognitive[f"llm_api_key_{tier}"] for tier in ps.TEXT_TIERS} == {_KEY}
    assert cognitive["llm_base_url"] == "https://api.openai.com/v1"
    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    assert {request.headers["authorization"] for request in provider.requests} == {f"Bearer {_KEY}"}
    out = capsys.readouterr().out
    assert "gpt-test-mini" in out  # the listing's IDs are offered as suggestions
    assert _KEY not in _squash(out)


@pytest.mark.parametrize("use_it", [True, False], ids=["accepted", "declined"])
def test_cmd_setup_interactive_uses_conventional_env_key_after_confirmation(
    use_it: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    env_key = "sk-ad1135-openai-env-5S8V"
    monkeypatch.setenv("OPENAI_API_KEY", env_key)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["" if use_it else "n", ""], secrets=[] if use_it else [_KEY], provider=provider)

    assert _setup(provider, "--provider", "openai", "--model", _MODEL) == 0

    assert terminal.unused() == (0, 0)
    confirm = terminal.asked[0]
    assert (confirm.kind, confirm.kwargs["default"], confirm.sent) == ("Confirm", True, 0)
    assert "OPENAI_API_KEY" in confirm.prompt
    assert env_key not in confirm.prompt
    assert terminal.kinds() == ["Confirm", *([] if use_it else ["getpass"]), "Confirm"]
    expected = env_key if use_it else _KEY
    assert {_cognitive(_home_config(tmp_path))[f"llm_api_key_{tier}"] for tier in ps.TEXT_TIERS} == {expected}
    assert {request.headers["authorization"] for request in provider.requests} == {f"Bearer {expected}"}
    out = capsys.readouterr().out
    assert env_key not in _squash(out)
    assert _KEY not in _squash(out)


def test_cmd_setup_interactive_ollama_defaults_to_first_listed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    detected = {"ollama": "http://localhost:11434", "anthropic": "https://api.anthropic.com"}
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    provider = _Provider(listing=_listing("llama3.2:3b", "qwen2.5:7b"))
    terminal = _Terminal(monkeypatch, ["", "", "", ""], provider=provider)  # Enter at every prompt

    assert _setup(provider) == 0

    assert terminal.unused() == (0, 0)
    choose, model, per_tier, write = terminal.asked
    assert choose.kwargs["default"] == "ollama"
    assert (model.kind, model.kwargs["default"], model.sent) == ("Prompt", "llama3.2:3b", 1)
    assert (per_tier.kind, write.kind) == ("Confirm", "Confirm")
    cognitive = _cognitive(_home_config(tmp_path))
    assert {cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS} == {"llama3.2:3b"}
    assert (cognitive["llm_base_url_fast"], cognitive["llm_api_key_fast"]) == ("http://localhost:11434/v1", "")
    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    assert all("authorization" not in request.headers for request in provider.requests)


@pytest.mark.parametrize(
    ("detected", "default"),
    [
        ({}, "openai"),
        ({"anthropic": "https://api.anthropic.com"}, "openai"),
        ({"copilot-proxy": "http://127.0.0.1:8080"}, "copilot-proxy"),
        ({"copilot-proxy": "http://127.0.0.1:8080", "ollama": "http://localhost:11434"}, "ollama"),
    ],
    ids=["nothing", "anthropic-only", "copilot-proxy", "both-local"],
)
def test_cmd_setup_interactive_default_provider_follows_local_detection(
    detected: dict[str, str],
    default: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: dict(detected))
    terminal = _Terminal(monkeypatch)  # the provider prompt reads EOF

    assert _setup(_Provider()) == 1

    (choose,) = terminal.asked
    assert (choose.kind, choose.kwargs["default"], choose.kwargs["choices"]) == ("Prompt", default, list(ps.PRESETS))
    assert "Cancelled" in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_interactive_per_tier_models_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=_listing("model-base", "model-fast", "model-deep"))
    # The model, "y" (a model per tier), fast, Enter (standard keeps model-base), deep, Enter (write).
    terminal = _Terminal(monkeypatch, ["model-base", "y", "model-fast", "", "model-deep", ""], provider=provider)

    assert _setup(provider, "--provider", "openrouter", "--api-key-env", _KEY_ENV) == 0

    assert terminal.unused() == (0, 0)
    per_tier = [ask for ask in terminal.asked if ask.kind == "Prompt"][1:]
    assert [ask.prompt.strip() for ask in per_tier] == [f"Model for the {tier} tier" for tier in ps.TEXT_TIERS]
    assert [ask.kwargs["default"] for ask in per_tier] == ["model-base"] * 3
    cognitive = _cognitive(_home_config(tmp_path))
    assert [cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS] == ["model-fast", "model-base", "model-deep"]
    assert cognitive["llm_base_url"] == "https://openrouter.ai/api/v1"
    assert provider.chat_models() == ["model-fast", "model-base", "model-deep"]


def test_cmd_setup_interactive_declined_write_exits_1_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["n"], provider=provider)

    assert _setup(provider, *_interactive()) == 1

    assert terminal.unused() == (0, 0)
    (write,) = terminal.asked
    assert (write.kind, write.kwargs["default"], write.sent) == ("Confirm", True, 2)  # asked once the check passed
    assert str(_home_config(tmp_path)) in write.prompt
    assert "Nothing was written" in _out(capsys)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(
    ("argv", "lines", "secrets", "sent"),
    [
        ((), [], [], 0),
        (("--provider", "openai"), [], [], 0),
        (("--provider", "custom", "--base-url", _BASE, "--model", _MODEL), [KeyboardInterrupt()], [""], 2),
    ],
    ids=["eof-at-provider", "eof-at-hidden-key", "ctrl-c-at-write"],
)
def test_cmd_setup_interactive_eof_exits_1_cancelled(
    argv: tuple[str, ...],
    lines: list[str | BaseException],
    secrets: list[str],
    sent: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: {})
    provider = _Provider()
    terminal = _Terminal(monkeypatch, lines, secrets=secrets, provider=provider)

    try:
        code = _setup(provider, *argv)
    except KeyboardInterrupt:  # escaping would end the whole pytest session, not just this test
        pytest.fail("Ctrl+C escaped _cmd_setup instead of cancelling it")

    assert code == 1
    assert terminal.unused() == (0, 0)
    assert len(provider.requests) == sent
    assert "Cancelled." in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_yes_with_missing_model_exits_1_without_prompting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()

    code = _setup(provider, "--provider", "openai", "--api-key-env", _KEY_ENV, "--yes")

    # The autouse guard fails any prompt or local probe, so reaching the exit proves none ran.
    assert (code, provider.calls()) == (1, [])
    assert "A model is required" in _out(capsys)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(
    ("argv", "env", "message"),
    [
        (("--model", _MODEL), {}, "--provider is required"),
        (("--provider", "custom", "--model", _MODEL), {}, "--base-url is required"),
        (("--provider", "openai", "--model", _MODEL), {"OPENAI_API_KEY": "sk-ad1135-unused-env-2P4Q"},
         "--api-key-env OPENAI_API_KEY"),
    ],
    ids=["provider", "base-url", "key-with-conventional-variable-set"],
)
def test_cmd_setup_yes_with_other_missing_input_exits_1_without_prompting(
    argv: tuple[str, ...],
    env: dict[str, str],
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    provider = _Provider()

    assert (_setup(provider, *argv, "--yes"), provider.calls()) == (1, [])

    out = _out(capsys)
    assert message in out
    assert all(value not in _squash(out) for value in env.values())  # --yes never reads the variable
    assert not (tmp_path / "home").exists()


def test_cmd_setup_provider_flag_skips_local_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _Provider()
    # The autouse guard makes detection raise; --provider must bypass it even when interactive.
    terminal = _Terminal(monkeypatch, [""], provider=provider)

    assert _setup(provider, "--provider", "copilot-proxy") == 0

    assert terminal.unused() == (0, 0)
    assert terminal.kinds() == ["Confirm"]  # only the final write question
    assert _home_config(tmp_path).exists()


def test_cmd_setup_copilot_proxy_preset_writes_shipped_model_names(tmp_path: Path) -> None:
    provider = _Provider()

    assert _setup(provider, "--provider", "copilot-proxy", "--yes") == 0

    preset = ps.PRESETS["copilot-proxy"]
    cognitive = _cognitive(_home_config(tmp_path))
    assert {tier: cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS} == dict(preset.models)
    assert (cognitive["llm_base_url"], cognitive["llm_base_url_deep"]) == (preset.base_url, preset.base_url)
    assert {cognitive[f"llm_api_key_{tier}"] for tier in ps.TEXT_TIERS} == {""}
    assert provider.chat_models() == list(dict.fromkeys(preset.models.values()))
    assert all("authorization" not in request.headers for request in provider.requests)


def test_main_model_alias_dispatches_to_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["probos", "model", "--provider", "custom", "--base-url", _BASE, "--model", _MODEL, "--skip-validation", "--yes"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()

    assert exc_info.value.code == 0
    assert _cognitive(_home_config(tmp_path))["llm_model_standard"] == _MODEL


# ----- B6/H3: a --config before `setup` survives the setup parser -----

_OFFLINE = ("--provider", "custom", "--base-url", _BASE, "--model", _MODEL, "--skip-validation", "--yes")


def _main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> object:
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(sys, "argv", ["probos", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()
    return exc_info.value.code


@pytest.mark.parametrize("before_setup", [True, False], ids=["root-config", "setup-config"])
def test_main_setup_writes_the_config_named_before_or_after_the_subcommand(
    before_setup: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = tmp_path / "elsewhere" / "node.yaml"
    flag = ("--config", str(explicit))
    argv = (*flag, "setup", *_OFFLINE) if before_setup else ("setup", *flag, *_OFFLINE)

    assert _main(monkeypatch, *argv) == 0

    assert (explicit.exists(), _home_config(tmp_path).exists()) == (True, False)
    assert _cognitive(explicit)["llm_model_fast"] == _MODEL


@pytest.mark.parametrize("before_setup", [True, False], ids=["root-config", "setup-config"])
def test_main_setup_config_with_probos_home_exits_2_and_writes_nothing(
    before_setup: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    explicit = tmp_path / "elsewhere" / "node.yaml"
    other_home = tmp_path / "other-home"
    flag = ("--config", str(explicit))
    home = ("--probos-home", str(other_home))
    argv = (*flag, "setup", *home, *_OFFLINE) if before_setup else ("setup", *flag, *home, *_OFFLINE)

    assert _main(monkeypatch, *argv) == 2

    assert (explicit.exists(), other_home.exists(), (tmp_path / "home").exists()) == (False, False, False)
    captured = capsys.readouterr()
    said = " ".join((captured.out + captured.err).split())
    assert "--config" in said
    assert "--probos-home" in said


def test_main_config_parsing_for_serve_and_the_shell_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, object]] = []
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(main_mod.asyncio, "set_event_loop_policy", lambda policy: None)
    monkeypatch.setattr(main_mod.asyncio, "run", lambda awaitable: None)
    monkeypatch.setattr(main_mod, "_serve", lambda **kwargs: seen.append(("serve", kwargs["config_path"])))
    monkeypatch.setattr(main_mod, "_boot_and_run", lambda **kwargs: seen.append(("shell", kwargs["config_path"])))
    explicit = tmp_path / "node.yaml"

    for argv in (("--config", str(explicit), "serve"), ("serve", "--config", str(explicit)), ("--config", str(explicit))):
        monkeypatch.setattr(sys, "argv", ["probos", *argv])
        main_mod.main()

    # Measured before B6: serve's own --config default replaces one given before `serve`. Only setup's
    # parser changed, so this stays; the two commands setup prints (serve --config X, --config X) name X.
    assert seen == [("serve", None), ("serve", explicit), ("shell", explicit)]


@pytest.mark.parametrize("where", ["chat-excerpt", "listed-model"])
def test_cmd_setup_escapes_rich_markup_in_provider_messages(
    where: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    buffer = StringIO()
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=buffer, **kwargs))
    hostile = "[/dim]BROKEN [bold]x[/bold]"
    if where == "chat-excerpt":
        provider = _Provider(chat=lambda request: httpx.Response(400, text=hostile))
        code, argv = 3, _flags()
    else:
        provider = _Provider(listing=_listing(hostile, _MODEL))
        _Terminal(monkeypatch, [_MODEL, "", ""], provider=provider)
        code, argv = 0, ("--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV)

    assert _setup(provider, *argv) == code

    # Rendered literally; an unescaped "[/dim]" would raise MarkupError instead.
    assert hostile in buffer.getvalue()


def test_cmd_init_still_asks_exactly_its_two_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: {})
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=StringIO(), **kwargs))
    terminal = _Terminal(monkeypatch, ["", ""])  # Enter twice: init's own defaults
    home = tmp_path / "init-home"

    main_mod._cmd_init(argparse.Namespace(force=False, probos_home=str(home), security_profile="strict"))

    assert terminal.unused() == (0, 0)
    assert [(ask.kind, ask.prompt, ask.kwargs.get("default")) for ask in terminal.asked] == [
        ("Prompt", "  LLM endpoint URL", "http://127.0.0.1:8080/v1"),
        ("Prompt", "  LLM model", "claude-sonnet-4-20250514"),
    ]
    written = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))["cognitive"]
    assert (written["llm_base_url_fast"], written["llm_model_fast"]) == (
        "http://127.0.0.1:8080/v1", "claude-sonnet-4-20250514",
    )


@pytest.mark.parametrize("answer", ["y", "n", ""], ids=["accepted", "declined", "enter-declines"])
def test_cmd_setup_interactive_plain_http_remote_with_key_asks_before_sending_it(
    answer: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()
    accepted = answer == "y"
    terminal = _Terminal(monkeypatch, [answer, *([""] if accepted else [])], provider=provider)

    assert _setup(provider, *_interactive(base_url="http://llm.example.test/v1")) == (0 if accepted else 1)

    assert terminal.unused() == (0, 0)
    ask = terminal.asked[0]
    assert (ask.kind, ask.kwargs["default"], ask.sent) == ("Confirm", False, 0)  # asked before any request (B5)
    if accepted:
        assert {request.headers.get("authorization") for request in provider.requests} == {f"Bearer {_KEY}"}
        assert _cognitive(_home_config(tmp_path))["llm_base_url_deep"] == "http://llm.example.test/v1"
    else:
        assert provider.calls() == []
        assert "Nothing was written" in _out(capsys)
        assert not (tmp_path / "home").exists()


def test_cmd_setup_interactive_plain_http_key_is_confirmed_before_the_suggestion_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["y", _MODEL, "", ""], provider=provider)

    code = _setup(provider, "--provider", "custom", "--base-url", "http://llm.example.test/v1", "--api-key-env", _KEY_ENV)

    assert code == 0
    assert terminal.unused() == (0, 0)
    insecure, model = terminal.asked[:2]
    assert (insecure.kind, insecure.sent) == ("Confirm", 0)
    assert (model.kind, model.sent) == ("Prompt", 1)  # the listing that carried the key came after the yes


def test_cmd_setup_interactive_shadow_guard_accepted_creates_the_home_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    repo_default = tmp_path / "repo" / "config" / "system.yaml"
    repo_default.parent.mkdir(parents=True)
    repo_default.write_text("system:\n  name: from-repo\n", encoding="utf-8")
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["y", ""], provider=provider)

    assert _setup(provider, *_interactive()) == 0

    assert terminal.unused() == (0, 0)
    shadow, write = terminal.asked
    assert (shadow.kind, shadow.kwargs["default"], shadow.sent) == ("Confirm", False, 0)
    assert (write.kind, write.sent) == ("Confirm", 2)
    assert main_mod._resolve_config_path(None) == _home_config(tmp_path)


def test_cmd_setup_interactive_suggests_at_most_20_listed_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    listed = [f"model-{number:02d}" for number in range(25)]
    provider = _Provider(listing=_listing(*listed))
    _Terminal(monkeypatch, [listed[0], "", ""], provider=provider)

    assert _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV) == 0

    out = capsys.readouterr().out
    assert [model_id for model_id in listed if model_id in out] == listed[:20]
    assert "5 more" in out


def test_cmd_setup_interactive_custom_asks_for_base_url_and_an_optional_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider()
    terminal = _Terminal(monkeypatch, [f"{_BASE}/", _MODEL, "", ""], secrets=[""], provider=provider)

    assert _setup(provider, "--provider", "custom") == 0

    assert terminal.unused() == (0, 0)
    base, key, model = terminal.asked[:3]
    assert (base.kind, "default" in base.kwargs) == ("Prompt", False)
    assert (key.kind, "optional" in key.prompt) == ("getpass", True)
    assert model.kind == "Prompt"
    cognitive = _cognitive(_home_config(tmp_path))
    assert (cognitive["llm_base_url"], cognitive["llm_api_key_fast"]) == (_BASE, "")
    assert all("authorization" not in request.headers for request in provider.requests)


def test_cmd_setup_interactive_skip_validation_asks_for_a_model_without_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, [_MODEL, "", ""], provider=provider)

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, "--skip-validation")

    assert (code, provider.calls()) == (0, [])
    assert terminal.unused() == (0, 0)
    assert "default" not in terminal.asked[0].kwargs
    assert _cognitive(_home_config(tmp_path))["llm_model_deep"] == _MODEL


def test_cmd_setup_interactive_empty_model_exits_1_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(404))
    terminal = _Terminal(monkeypatch, [""], provider=provider)

    assert _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV) == 1

    assert terminal.unused() == (0, 0)
    assert provider.calls() == [("GET", "/v1/models")]
    assert "A model is required" in _out(capsys)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_interactive_rejected_key_at_the_listing_exits_3_before_asking_for_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    provider = _Provider(listing=lambda request: httpx.Response(401))
    terminal = _Terminal(monkeypatch, provider=provider)

    assert _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV) == 3

    assert terminal.asked == []
    assert provider.calls() == [("GET", "/v1/models")]
    out = _out(capsys)
    assert "rejected the API key" in out
    assert "Nothing was written" in out
    assert not (tmp_path / "home").exists()


def test_cmd_setup_interactive_write_question_names_the_tier_that_keeps_the_shared_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    original = b"cognitive:\r\n  llm_base_url: http://127.0.0.1:8080/v1\r\n  llm_model_vision: qwen-vl\r\n"
    config = _existing(tmp_path, original)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["n"], provider=provider)

    assert _setup(provider, *_interactive()) == 1

    assert terminal.unused() == (0, 0)
    (write,) = terminal.asked
    assert (write.kind, write.sent, str(config) in write.prompt) == ("Confirm", 2, True)
    out = _out(capsys)
    assert _SHARED_URL_NOTE in out
    assert out.index(_SHARED_URL_NOTE) < out.index("Write ")  # said with the question, before anything is written
    assert config.read_bytes() == original


# ----- B8: provider data that holds a form of the key is never shown, suggested or written -----

# Each holds one form of _ENC_KEY; listed first, so an unfiltered Ollama default would be one of them.
_LEAKY_IDS = tuple(f"leak-{form}" for form in _ENC_FORMS)
_CLEAN_IDS = ("llama3.2:3b", "qwen2.5:7b")


def _no_key_form(*texts: str) -> None:
    for text in texts:
        for form in _ENC_FORMS:
            assert form not in text
            assert _squash(form) not in _squash(text)


def test_cmd_setup_interactive_listed_ids_that_hold_the_key_are_never_shown_suggested_or_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    provider = _Provider(listing=_listing(*_LEAKY_IDS, *_CLEAN_IDS))
    terminal = _Terminal(monkeypatch, ["", "", ""], provider=provider)  # Enter: the model, per-tier and write questions

    assert _setup(provider, "--provider", "ollama", "--api-key-env", _KEY_ENV) == 0

    assert terminal.unused() == (0, 0)
    assert len(set(_ENC_FORMS)) == len(_ENC_FORMS)  # premise: no two forms coincide
    assert provider.requests[0].headers["authorization"] == f"Bearer {_ENC_KEY}"  # premise: the key was sent
    model = next(ask for ask in terminal.asked if ask.kind == "Prompt")
    assert model.kwargs["default"] == _CLEAN_IDS[0]
    out, err = capsys.readouterr()
    assert all(model_id in out for model_id in _CLEAN_IDS)  # premise: the other listed IDs are suggested
    assert "leak-" not in out
    assert "The provider lists 7 model(s); setup withholds 5 whose ID contains the API key:" in " ".join(out.split())
    _no_key_form(out, err, caplog.text)
    assert provider.chat_models() == [_CLEAN_IDS[0]]
    config = _home_config(tmp_path)
    cognitive = _cognitive(config)
    assert {cognitive[f"llm_model_{tier}"] for tier in ps.TEXT_TIERS} == {_CLEAN_IDS[0]}
    assert {cognitive[f"llm_api_key_{tier}"] for tier in ps.TEXT_TIERS} == {_ENC_KEY}  # premise: the key fields hold it
    # Outside those three key fields the written file holds no form of the key.
    lines = config.read_text(encoding="utf-8").splitlines()
    _no_key_form("\n".join(line for line in lines if not line.lstrip().startswith("llm_api_key_")))


def test_cmd_setup_interactive_suggestions_redact_an_id_that_reached_them_unfiltered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    # A listing that skipped probe_models' filter: the display redacts on its own (defense in depth).
    unfiltered = ps.ProbeResult(ps.ProbeOutcome.OK, "the provider lists 6 model(s)", 200, (*_LEAKY_IDS, _MODEL))
    monkeypatch.setattr(ps, "probe_models", lambda *args, **kwargs: unfiltered)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, [_MODEL, "", ""], provider=provider)

    assert _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV) == 0

    assert terminal.unused() == (0, 0)
    out, err = capsys.readouterr()
    assert out.count("leak-<redacted>") == len(_LEAKY_IDS)  # premise: each reached the suggestions
    _no_key_form(out, err)


@pytest.mark.parametrize("form", _ENC_FORMS, ids=["literal", "quote", "quote-plus", "base64", "base64-bearer"])
def test_cmd_setup_interactive_write_question_shows_no_key_form_in_a_model_name(
    form: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    # B9 now refuses this --model at input (test_cmd_setup_model_flag_holding_the_key_exits_2_before_any_request),
    # so the refusal is bypassed here to keep pinning the question's own B8 redaction, now defense in depth.
    monkeypatch.setattr(ps, "validate_holds_no_key", lambda value, api_key, *, name: None)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["n"], provider=provider)
    model = f"m-{form}"

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, "--model", model)

    assert (code, terminal.unused(), terminal.kinds()) == (1, (0, 0), ["Confirm"])
    assert provider.chat_models() == [model]  # premise: that model name was checked, so it reached the question
    out, err = capsys.readouterr()
    assert "models: fast m-<redacted>, standard m-<redacted>, deep m-<redacted>;" in " ".join(out.split())
    _no_key_form(out, err)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("field", ["content", "reasoning"])
def test_cmd_setup_chat_reply_that_echoes_the_key_is_never_printed(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    reply = " ".join(f"echo {form}" for form in _ENC_FORMS)
    message = {"role": "assistant", "content": None, field: reply}
    provider = _Provider(chat=lambda request: httpx.Response(200, json={"choices": [{"index": 0, "message": message}]}))

    assert _setup(provider, *_flags()) == 0

    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    out, err = capsys.readouterr()
    assert f"model '{_MODEL}' answered" in out  # premise: the chat check passed on that reply
    _no_key_form(out, err, caplog.text)


def test_cmd_setup_image_gen_tier_with_a_model_keeps_its_consumers_configured_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = _existing(tmp_path, _managed_old("  llm_model_image_gen: gpt-image-1"))
    old = load_config(config).cognitive
    reported = ps.optional_tier_endpoints(config.read_text(encoding="utf-8"))["image_gen"]
    before = is_image_gen_tier_configured(old)
    # Premise: image_gen uses the shared URL, and the vision check reads it differently from image_gen's own.
    assert (reported.inherited, before, is_vision_tier_configured(old, "image_gen")) == (True, False, True)

    assert _setup(_Provider(), *_flags()) == 0

    assert reported.configured is before  # setup reads image_gen as its consumer does
    assert is_image_gen_tier_configured(load_config(config).cognitive) is before
    assert _endpoint(config, "image_gen") == (_OLD_SHARED, "gpt-image-1")
    assert "because image_gen (model 'gpt-image-1') uses it" in _out(capsys)


# ----- Review round 3: text setup prints from the existing config holds no form of the key -----

_FORM_IDS = ("literal", "quote", "quote-plus", "base64", "base64-bearer")


@pytest.mark.parametrize("declined", [True, False], ids=["declined", "written"])
@pytest.mark.parametrize("form", _ENC_FORMS, ids=_FORM_IDS)
def test_cmd_setup_retention_notice_shows_no_key_form_in_the_retained_model(
    form: str,
    declined: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    model = f"m-{form}"
    original = f"cognitive:\r\n  llm_base_url: {_OLD_SHARED}\r\n  llm_model_vision: {json.dumps(model)}\r\n".encode()
    config = _existing(tmp_path, original)
    # Premise: vision keeps the shared URL, so the notice names its model, which holds a form of the key.
    assert ps.tiers_using_shared_url(ps.optional_tier_endpoints(original.decode())) == {"vision": model}
    assert ps.carries_key(model, _ENC_KEY)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, ["n"], provider=provider) if declined else None

    assert _setup(provider, *(_interactive() if declined else _flags())) == (1 if declined else 0)

    assert provider.requests[0].headers["authorization"] == f"Bearer {_ENC_KEY}"  # premise: the key was sent
    if terminal is not None:
        assert (terminal.unused(), terminal.kinds()) == ((0, 0), ["Confirm"])
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert "Left the shared llm_base_url unchanged because vision (model " in said  # premise: the notice ran
    _no_key_form(out, err, caplog.text)
    assert "because vision (model 'm-<redacted>') uses it" in said
    assert (config.read_bytes() == original) is declined


@pytest.mark.parametrize("where", ["quoted-value", "mapping-key"])
@pytest.mark.parametrize("form", _ENC_FORMS, ids=_FORM_IDS)
def test_cmd_setup_load_failure_shows_no_key_form_from_the_existing_config(
    form: str,
    where: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    # memory.access_policy's validator quotes the value it refuses; pydantic's loc carries a mapping key.
    if where == "quoted-value":
        memory, field = f"  access_policy: {json.dumps(form)}", "memory.access_policy"
    else:
        memory, field = f"  recall_weights:\r\n    {json.dumps(form)}: not-a-number", "memory.recall_weights."
    original = f"memory:\r\n{memory}\r\n".encode()
    config = _existing(tmp_path, original)
    provider = _Provider()

    assert _setup(provider, *_flags()) == 4

    assert provider.requests[0].headers["authorization"] == f"Bearer {_ENC_KEY}"  # premise: the key was sent
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert f"the result does not load: {field}" in said  # premise: the final check refused that setting
    _no_key_form(out, err, caplog.text)
    assert "<redacted>" in said  # premise: the form reached the message, and was replaced
    assert config.read_bytes() == original
    assert _names(config.parent) == ["config.yaml"]


# ----- Review round 4 (B9): inputs that redaction could not hide are refused before anything shows them -----

# B9's own check refuses this key first; B10's < and > rule would refuse it too.
_MARKER_KEY = "sk-ad1135<redacted>tail"
# _ENC_KEY's literal form holds a space, which the URL's own check refuses first; _KEY stands in for it.
_URL_KEYS_AND_FORMS = ((_KEY, _KEY), *((_ENC_KEY, form) for form in _ENC_FORMS[1:]))
_KEY_SOURCES = ["api-key", "api-key-env", "hidden-prompt", "conventional-variable"]


def _setup_with_key_from(
    source: str, key: str, provider: _Provider, monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, _Terminal | None]:
    """Run setup with ``key`` from ``source``; return the exit code and the terminal that answered, if one did."""
    terminal: _Terminal | None = None
    if source == "api-key":
        argv: tuple[str, ...] = (
            "--provider", "custom", "--base-url", _BASE, "--api-key", key, "--model", _MODEL, "--yes",
        )
    elif source == "api-key-env":
        monkeypatch.setenv(_KEY_ENV, key)
        argv = _flags()
    elif source == "hidden-prompt":
        terminal = _Terminal(monkeypatch, secrets=[key], provider=provider)
        argv = ("--provider", "custom", "--base-url", _BASE, "--model", _MODEL)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
        terminal = _Terminal(monkeypatch, [""], provider=provider)  # Enter: use the variable's key
        argv = ("--provider", "openai", "--model", _MODEL)
    return _setup(provider, *argv), terminal


@pytest.mark.parametrize("source", _KEY_SOURCES)
def test_cmd_setup_key_holding_the_redaction_marker_exits_2_before_any_request(
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    provider = _Provider()

    code, terminal = _setup_with_key_from(source, _MARKER_KEY, provider, monkeypatch)

    assert (code, provider.calls()) == (2, [])

    if terminal is not None:
        assert terminal.unused() == (0, 0)  # premise: the key came from that source
    out, err = capsys.readouterr()
    assert "Invalid setting: the API key contains setup's redaction marker" in " ".join(out.split())
    for text in (out, err, caplog.text):
        assert _MARKER_KEY not in text
        assert "sk-ad1135" not in text
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(("key", "form"), _URL_KEYS_AND_FORMS, ids=_FORM_IDS)
@pytest.mark.parametrize("interactive", [False, True], ids=["yes", "interactive"])
def test_cmd_setup_base_url_holding_the_key_exits_2_before_any_request(
    key: str,
    form: str,
    interactive: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, key)
    base_url = f"https://llm.example.test/{form}/v1"
    assert ps.normalize_base_url(base_url) == base_url  # premise: only the key check can refuse it
    provider = _Provider()
    # Interactively, the model question's suggestion listing would print the URL and send the key to it.
    terminal = _Terminal(monkeypatch, [_MODEL, "", ""], provider=provider) if interactive else None
    argv = ("--provider", "custom", "--base-url", base_url, "--api-key-env", _KEY_ENV)

    code = _setup(provider, *(argv if interactive else (*argv, "--model", _MODEL, "--yes")))

    assert (code, provider.calls()) == (2, [])
    if terminal is not None:
        assert terminal.asked == []
    out, err = capsys.readouterr()
    assert "Invalid --base-url: the base URL contains the API key, or an encoding of it" in " ".join(out.split())
    for text in (out, err, caplog.text):
        assert form not in text
        assert "llm.example.test" not in text
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("form", _ENC_FORMS, ids=_FORM_IDS)
@pytest.mark.parametrize(
    ("tier", "models"), [("fast", ("--model",)), ("deep", ("--model", _MODEL, "--model-deep"))], ids=["every-tier", "deep"],
)
def test_cmd_setup_model_flag_holding_the_key_exits_2_before_any_request(
    form: str,
    tier: str,
    models: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    provider = _Provider()

    code = _setup(
        provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, *models, f"m-{form}", "--yes",
    )

    assert (code, provider.calls()) == (2, [])
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert f"Invalid setting: the model for the {tier} tier contains the API key, or an encoding of it" in said
    _no_key_form(out, err, caplog.text)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("form", _ENC_FORMS, ids=_FORM_IDS)
def test_cmd_setup_interactive_model_holding_the_key_exits_2_before_any_per_tier_question(
    form: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    provider = _Provider()
    # The model, then yes to a model per tier, whose three questions would each offer the model back as the default.
    terminal = _Terminal(monkeypatch, [f"m-{form}", "y", "", "", ""], provider=provider)

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV)

    assert (code, terminal.kinds(), terminal.unused()) == (2, ["Prompt"], (4, 0))
    assert provider.calls() == [("GET", "/v1/models")]  # premise: the suggestion listing ran before the question
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert "Invalid setting: the model for the fast tier contains the API key, or an encoding of it" in said
    _no_key_form(out, err, caplog.text)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_interactive_per_tier_model_holding_the_key_exits_2_naming_its_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    provider = _Provider()
    terminal = _Terminal(monkeypatch, [_MODEL, "y", "", "", f"m-{_ENC_FORMS[3]}"], provider=provider)

    code = _setup(provider, "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV)

    assert (code, terminal.unused()) == (2, (0, 0))
    assert provider.calls() == [("GET", "/v1/models")]  # no chat check spent on it
    out, err = capsys.readouterr()
    assert "Invalid setting: the model for the deep tier contains the API key" in " ".join(out.split())
    _no_key_form(out, err)
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("fails", ["final", "every"], ids=["final-replace", "backup-replace"])
def test_cmd_setup_write_failure_shows_no_key_that_the_target_path_holds(
    fails: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _KEY)
    config = tmp_path / f"cfg-{_KEY}" / "config.yaml"
    config.parent.mkdir()
    config.write_bytes(_HAND_EDITED)
    real_replace = os.replace

    def replace(src: object, dst: object) -> None:
        if fails == "every" or Path(dst) == config:
            raise PermissionError(13, "Permission denied", str(dst))  # a real OSError names its path
        real_replace(src, dst)

    monkeypatch.setattr(ps.os, "replace", replace)

    assert _setup(_Provider(), *_flags("--skip-validation", "--config", str(config))) == 4

    assert config.read_bytes() == _HAND_EDITED
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert "Could not write" in said and "Permission denied" in said  # premise: the exit-4 message ran
    # The target, the path the OSError names and, after a final-replace failure, the kept backup.
    assert said.count("cfg-<redacted>") == (3 if fails == "final" else 2)
    for text in (out, err, caplog.text):
        assert _KEY not in _squash(text)


# ----- Review round 5 (B10): setup accepts only keys that redact can hide, and redact hides them in one pass -----

_LESS_OR_GREATER = "the API key contains < or >; API keys do not contain < or >"
# Each key breaks one rule only: neither a< nor sk-ad1135>tail lies inside <redacted>, and dact holds no < or >.
_UNHIDEABLE_KEYS = {
    "less-than": ("a<", _LESS_OR_GREATER),
    "greater-than": ("sk-ad1135>tail", _LESS_OR_GREATER),
    "inside-the-marker": ("dact", "the API key is part of setup's redaction marker '<redacted>'"),
}


@pytest.mark.parametrize("case", list(_UNHIDEABLE_KEYS))
@pytest.mark.parametrize("source", _KEY_SOURCES)
def test_cmd_setup_key_that_redaction_could_not_hide_exits_2_before_any_request(
    source: str,
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    key, refusal = _UNHIDEABLE_KEYS[case]
    provider = _Provider()

    code, terminal = _setup_with_key_from(source, key, provider, monkeypatch)

    assert (code, provider.calls()) == (2, [])
    if terminal is not None:
        assert terminal.unused() == (0, 0)  # premise: the key came from that source
    out, err = capsys.readouterr()
    said = " ".join(out.split())
    assert f"Invalid setting: {refusal}" in said
    # The refusal is fixed text, whose letters a key inside the marker shares; nothing else shows the key.
    for text in (said.replace(refusal, ""), err, caplog.text):
        assert key not in _squash(text)
    assert not (tmp_path / "home").exists()


def test_cmd_setup_400_excerpt_with_each_key_form_beside_a_literal_marker_prints_none_of_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv(_KEY_ENV, _ENC_KEY)
    marker = "<redacted>"
    body = f"refused {marker}{marker.join(_ENC_FORMS)}{marker} end"
    provider = _Provider(chat=lambda request: httpx.Response(400, text=body))

    assert _setup(provider, *_flags()) == 3

    assert provider.calls() == [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]
    out, err = capsys.readouterr()
    # Premise: the excerpt was shown, the provider's six markers kept and each of the five forms replaced.
    assert f"(HTTP 400): refused {marker * 11} end" in " ".join(out.split())
    _no_key_form(out, err, caplog.text)
    assert not (tmp_path / "home").exists()
