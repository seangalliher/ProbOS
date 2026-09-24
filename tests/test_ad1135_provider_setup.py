"""AD-1135 (#1054): unit tests for the ``probos setup`` support code.

Covers the byte-identical ``probos init`` extraction, the shared config
resolver, the in-place editor applied to init's own scaffold, the classified
provider probes (through ``httpx.MockTransport``), input validation, file
modes and the import census behind the SSRF statement.
"""

from __future__ import annotations

import argparse
import ast
import base64
import codecs
import difflib
import hashlib
import json
import random
import stat
import sys
from collections.abc import Callable
from datetime import datetime
from io import StringIO
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote, unquote_plus

import httpx
import pytest
import yaml
from rich.console import Console

import probos.__main__ as main_mod
from probos import provider_setup as ps
from probos.cognitive.image_gen_dispatch import is_image_gen_tier_configured
from probos.cognitive.llm_client import _LLM_TIERS
from probos.cognitive.vision_dispatch import is_vision_tier_configured
from probos.config import CognitiveConfig, load_config

_REPO_ROOT = Path(__file__).resolve().parents[1]

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_BASE = "https://llm.example.test/v1"
_KEY = "sk-ad1135-unit-sentinel-4K9W"
# OpenAI's 401 body echoes the key partially masked like this.
_MASKED = f"{_KEY[:8]}{'*' * 20}{_KEY[-4:]}"
# "/", " " and "+" each encode, so the key's literal, percent-encoded and base64 forms all differ (B6/H1).
_ENC_KEY = "sk-ad1135/enc key+9Z"
_ENC_FORMS = {
    "literal": _ENC_KEY,
    "quote": quote(_ENC_KEY, safe=""),
    "quote-plus": quote_plus(_ENC_KEY),
    "base64": base64.b64encode(_ENC_KEY.encode()).decode(),
    "base64-bearer": base64.b64encode(b"Bearer " + _ENC_KEY.encode()).decode(),
}

# Captured at 164e575b (contract section 1.4): CRLF -> LF, home.as_posix() -> <HOME>.
_INIT_GOLDENS = [
    ("strict", "https://api.example.com/v1", "model-x", 979,
     "93310b2a62c79becd5e969d256c29515647e2ba2ed1f82442511b17032945a74"),
    ("relaxed", "https://api.example.com/v1", "model-x", 774,
     "05556e840eb18afb9c65ff60b50fe9c6c22950cf3e880b5e7a6cd0ab21182afd"),
    ("strict", "http://localhost:11434/v1", "llama3.1:8b", 982,
     "d07186a043e8ced2e14633faae2614c2b49c71e37ece8593c7a2509c26658aae"),
]


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(
        main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml",
    )
    for name in ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", *_PROXY_VARS):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


@pytest.mark.parametrize(
    ("profile", "url", "model", "lf_bytes", "sha256"),
    _INIT_GOLDENS,
    ids=["strict", "relaxed", "strict-ollama"],
)
def test_cmd_init_output_is_byte_identical_after_render_extraction(
    profile: str,
    url: str,
    model: str,
    lf_bytes: int,
    sha256: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "init-home"
    answers = iter([url, model])
    monkeypatch.setattr(main_mod, "_detect_llm_providers", lambda console: {})
    monkeypatch.setattr(main_mod, "Console", lambda *args, **kwargs: Console(file=StringIO()))
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *args, **kwargs: next(answers))

    main_mod._cmd_init(argparse.Namespace(force=True, probos_home=str(home), security_profile=profile))

    assert next(answers, None) is None  # premise: both prompts consumed our inputs
    raw = (home / "config.yaml").read_bytes()
    normalised = raw.replace(b"\r\n", b"\n").replace(home.as_posix().encode("utf-8"), b"<HOME>")
    assert len(normalised) == lf_bytes
    assert hashlib.sha256(normalised).hexdigest() == sha256


def test_resolve_config_path_explicit_then_home_then_repo_default(tmp_path: Path) -> None:
    home_config = tmp_path / "home" / "config.yaml"
    repo_default = tmp_path / "repo" / "config" / "system.yaml"
    explicit = tmp_path / "explicit" / "missing.yaml"

    # Neither file exists (a wheel install): the repo default is still the answer, loading defaults.
    assert main_mod._resolve_config_path(None) == repo_default
    config, path = main_mod._load_config_with_fallback(None)
    assert (path, config.system.name) == (repo_default, "ProbOS")

    repo_default.parent.mkdir(parents=True)
    repo_default.write_text('system:\n  name: "from-repo"\n', encoding="utf-8")
    assert main_mod._resolve_config_path(None) == repo_default
    config, path = main_mod._load_config_with_fallback(None)
    assert (path, config.system.name) == (repo_default, "from-repo")

    home_config.parent.mkdir(parents=True)
    home_config.write_text('system:\n  name: "from-home"\n', encoding="utf-8")
    assert main_mod._resolve_config_path(None) == home_config
    config, path = main_mod._load_config_with_fallback(None)
    assert (path, config.system.name) == (home_config, "from-home")

    assert not explicit.exists()
    assert main_mod._resolve_config_path(explicit) == explicit
    config, path = main_mod._load_config_with_fallback(explicit)
    assert (path, config.system.name) == (explicit, "ProbOS")


def test_apply_managed_values_init_scaffold_replaces_four_and_inserts_nine(tmp_path: Path) -> None:
    scaffold = main_mod._render_init_config(
        tmp_path / "home",
        llm_url="http://127.0.0.1:8080/v1",
        llm_model="unset",
        api_format="openai",
        profile="strict",
        generated_by="probos setup",
    )
    choice = ps.ProviderChoice(
        provider="custom",
        base_url="https://llm.example.test/v1",
        models={tier: f"model-{tier}" for tier in ps.TEXT_TIERS},
        api_key="sk-unit-test",
    )
    values = ps.managed_values(choice)
    fields = ("base_url", "api_key", "model", "api_format")
    assert list(values) == ["llm_base_url", *(f"llm_{f}_{tier}" for tier in ps.TEXT_TIERS for f in fields)]

    edited = ps.apply_managed_values(scaffold, values)

    original = yaml.safe_load(scaffold)
    assert yaml.safe_load(edited) == {**original, "cognitive": {**original["cognitive"], **values}}

    def managed_key(line: str) -> str | None:
        return next((key for key in values if line.startswith(f"  {key}:")), None)

    old_lines, new_lines = scaffold.splitlines(), edited.splitlines()
    assert [ln for ln in old_lines if managed_key(ln) is None] == [ln for ln in new_lines if managed_key(ln) is None]
    replaced = [managed_key(ln) for ln in old_lines if managed_key(ln) is not None]
    assert replaced == [f"llm_{f}_fast" for f in fields]
    inserted = [key for key in values if key not in replaced]
    assert len(inserted) == 9
    assert [managed_key(ln) for ln in new_lines if managed_key(ln) is not None] == replaced + inserted
    assert len(new_lines) == len(old_lines) + 9
    assert "\r" not in edited


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.MockTransport(record), seen


def _answer(status: int, **kwargs: object) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, **kwargs)


def _completion(message: object) -> dict:
    return {"choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def _choice(base_url: str = _BASE, api_key: str = _KEY, model: str = "model-x") -> ps.ProviderChoice:
    return ps.ProviderChoice(
        provider="custom", base_url=base_url, models={tier: model for tier in ps.TEXT_TIERS}, api_key=api_key,
    )


def test_probe_models_connect_error_returns_unreachable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport, seen = _transport(refuse)
    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.UNREACHABLE, None)
    assert "ConnectError" in result.message
    assert [(r.method, str(r.url)) for r in seen] == [("GET", f"{_BASE}/models")]


def test_probe_models_read_timeout_returns_timeout() -> None:
    def stall(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    transport, seen = _transport(stall)
    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.TIMEOUT, None)
    assert "ReadTimeout" in result.message
    assert seen[0].extensions["timeout"]["read"] == ps.MODELS_PROBE_TIMEOUT_S


def test_probe_models_401_returns_auth_rejected_without_provider_body() -> None:
    body = {"error": {"message": f"Incorrect API key provided: {_MASKED}. PROVIDER-BODY-401"}}
    transport, seen = _transport(_answer(401, json=body))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert seen[0].headers["authorization"] == f"Bearer {_KEY}"  # premise: the key was presented
    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.AUTH_REJECTED, 401)
    assert "rejected the API key" in result.message
    assert "PROVIDER-BODY-401" not in result.message
    assert _MASKED not in result.message


def test_probe_models_403_returns_auth_rejected() -> None:
    transport, _ = _transport(_answer(403, json={"error": {"message": "PROVIDER-BODY-403"}}))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.AUTH_REJECTED, 403)
    assert "PROVIDER-BODY-403" not in result.message


def test_probe_models_404_returns_not_found() -> None:
    transport, _ = _transport(_answer(404, text="<html>no such page</html>"))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code, result.model_ids) == (ps.ProbeOutcome.NOT_FOUND, 404, ())


def test_probe_models_405_returns_not_found() -> None:
    transport, seen = _transport(_answer(405, json={"error": {"message": "method not allowed"}}))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    # B5: a server without a listing may refuse the method rather than the path; both mean "no listing here".
    assert (result.outcome, result.status_code, result.model_ids) == (ps.ProbeOutcome.NOT_FOUND, 405, ())
    assert "HTTP 405" in result.message
    assert [(r.method, str(r.url)) for r in seen] == [("GET", f"{_BASE}/models")]


@pytest.mark.parametrize("status", [400, 406, 409, 410, 422])
def test_probe_models_other_4xx_returns_request_rejected(status: int) -> None:
    transport, _ = _transport(_answer(status, json={"error": {"message": "refused"}}))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.REQUEST_REJECTED, status)


def test_probe_models_302_returns_redirected_and_sends_one_request() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        if request.url.host == "llm.example.test":
            return httpx.Response(302, headers={"Location": "https://elsewhere.example.test/v1/models"})
        return httpx.Response(200, json={"object": "list", "data": [{"id": "model-x"}]})

    transport, seen = _transport(redirect)
    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.REDIRECTED, 302)
    # This line pinned the Location's host in the message; B6/H1 shows no part of a Location, which can carry the key.
    assert "elsewhere.example.test" not in result.message
    assert "does not forward your API key to redirects" in result.message
    assert [str(r.url) for r in seen] == [f"{_BASE}/models"]


@pytest.mark.parametrize("probe", ["models", "chat"])
def test_probe_redirect_message_shows_no_part_of_the_location(probe: str) -> None:
    location = f"https://login.example.test/steal/{_ENC_FORMS['quote']}?k={_ENC_KEY}&b={_ENC_FORMS['base64']}"
    transport, seen = _transport(_answer(302, headers={"Location": location}))

    if probe == "models":
        result = ps.probe_models(_BASE, _ENC_KEY, transport=transport)
    else:
        result = ps.probe_chat(_BASE, _ENC_KEY, "model-x", transport=transport)

    assert len(set(_ENC_FORMS.values())) == len(_ENC_FORMS)  # premise: no two forms coincide
    assert (result.outcome, result.status_code, len(seen)) == (ps.ProbeOutcome.REDIRECTED, 302, 1)
    assert "does not forward your API key to redirects" in result.message
    for fragment in (*_ENC_FORMS.values(), "login.example.test", "/steal", "?k=", location):
        assert fragment not in result.message


def test_probe_models_200_returns_ok_with_model_ids() -> None:
    listing = {"object": "list", "data": [{"id": "model-a", "object": "model"}, {"id": "model-b"}]}
    transport, _ = _transport(_answer(200, json=listing))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code, result.model_ids) == (
        ps.ProbeOutcome.OK, 200, ("model-a", "model-b"),
    )


def test_probe_models_200_html_returns_bad_response() -> None:
    page = "<!doctype html><title>Welcome</title>"
    transport, _ = _transport(_answer(200, text=page, headers={"Content-Type": "text/html"}))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code, result.model_ids) == (ps.ProbeOutcome.BAD_RESPONSE, 200, ())


def test_probe_models_429_returns_rate_limited() -> None:
    body = {"error": {"message": f"Rate limit reached for key {_KEY}; retry later"}}
    transport, _ = _transport(_answer(429, json=body))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.RATE_LIMITED, 429)
    assert "retry later" in result.message
    assert "<redacted>" in result.message
    assert _KEY not in result.message


def test_probe_models_503_returns_provider_error() -> None:
    transport, _ = _transport(_answer(503, text="upstream\n\x1b[31moverloaded"))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.PROVIDER_ERROR, 503)
    assert "upstream [31moverloaded" in result.message  # one line; the escape byte is blanked
    assert "\x1b" not in result.message


def test_probe_models_empty_key_sends_no_authorization_header() -> None:
    transport, seen = _transport(_answer(200, json={"object": "list", "data": []}))

    result = ps.probe_models(_BASE, "", transport=transport)

    assert result.outcome is ps.ProbeOutcome.OK
    assert "authorization" not in seen[0].headers


def test_probe_models_undecodable_answer_returns_bad_response() -> None:
    def garble(request: httpx.Request) -> httpx.Response:
        raise httpx.DecodingError("bad gzip stream", request=request)

    transport, _ = _transport(garble)
    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.BAD_RESPONSE, None)
    assert "DecodingError" in result.message


def test_probe_models_unexpected_2xx_returns_bad_response() -> None:
    transport, _ = _transport(_answer(204))

    result = ps.probe_models(_BASE, _KEY, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.BAD_RESPONSE, 204)
    assert "unexpected HTTP 204" in result.message


def test_probe_chat_sends_the_runtime_boot_probe_payload() -> None:
    transport, seen = _transport(_answer(200, json=_completion({"role": "assistant", "content": "pong"})))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.OK, 200)
    (request,) = seen
    assert (request.method, str(request.url)) == ("POST", f"{_BASE}/chat/completions")
    # The OpenAI-format body of llm_client.py _check_endpoint's boot probe.
    assert json.loads(request.content) == {
        "model": "model-x", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1,
    }
    assert request.headers["authorization"] == f"Bearer {_KEY}"
    assert request.extensions["timeout"]["read"] == ps.CHAT_PROBE_TIMEOUT_S


def test_probe_chat_404_with_listing_returns_model_rejected_with_suggestions() -> None:
    transport, _ = _transport(_answer(404, json={"error": {"code": "model_not_found"}}))
    listed = ("gpt-4o-mini", "gpt-4o", "o3", "text-embedding-3-small")

    result = ps.probe_chat(_BASE, _KEY, "gpt-4o-mnii", model_ids=listed, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.MODEL_REJECTED, 404)
    assert "'gpt-4o-mnii'" in result.message
    assert "'gpt-4o-mini'" in result.message
    assert "text-embedding-3-small" not in result.message


def test_probe_chat_404_without_listing_returns_not_found() -> None:
    transport, _ = _transport(_answer(404, text="not found"))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.NOT_FOUND, 404)


def test_probe_chat_400_returns_request_rejected_with_redacted_excerpt() -> None:
    body = json.dumps({"error": {"message": f"key {_KEY} may not set max_tokens {'x' * 400} TAIL-MARKER"}})
    transport, _ = _transport(_answer(400, text=body))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.REQUEST_REJECTED, 400)
    assert "may not set max_tokens" in result.message
    assert "<redacted>" in result.message
    assert _KEY not in result.message
    assert "TAIL-MARKER" not in result.message  # the excerpt is capped
    assert result.message.endswith("...")


def test_probe_chat_400_excerpt_redacts_the_full_key_but_may_show_a_provider_masked_form() -> None:
    body = {"error": {"message": f"key {_KEY} ({_MASKED}) may not use this model"}}
    transport, _ = _transport(_answer(400, json=body))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    # The measured property the module docstring states (B5): never the full key; a provider-masked form may show.
    assert result.outcome is ps.ProbeOutcome.REQUEST_REJECTED
    assert _KEY not in result.message
    assert "<redacted>" in result.message
    assert _MASKED in result.message


@pytest.mark.parametrize("form", list(_ENC_FORMS), ids=list(_ENC_FORMS))
def test_probe_chat_excerpt_redacts_each_encoded_form_of_the_key(form: str) -> None:
    transport, _ = _transport(_answer(400, text=f"upstream echoed [{_ENC_FORMS[form]}] and refused"))

    result = ps.probe_chat(_BASE, _ENC_KEY, "model-x", transport=transport)

    assert result.outcome is ps.ProbeOutcome.REQUEST_REJECTED
    assert "upstream echoed [<redacted>] and refused" in result.message  # premise: the excerpt is shown
    assert all(value not in result.message for value in _ENC_FORMS.values())


def test_probe_chat_excerpt_redacts_a_key_that_whitespace_folding_rebuilds() -> None:
    # The excerpt folds each whitespace run to one space, which rebuilds a key that contains a space.
    body = _ENC_KEY.replace(" ", "\n\t ") + " tail"
    assert _ENC_KEY not in body  # premise: only the folding makes the key
    transport, _ = _transport(_answer(400, text=body))

    result = ps.probe_chat(_BASE, _ENC_KEY, "model-x", transport=transport)

    assert "<redacted> tail" in result.message
    assert _ENC_KEY not in result.message


def test_probe_chat_excerpt_cap_leaves_no_part_of_a_key_that_whitespace_folding_rebuilds() -> None:
    # Folding rebuilds the key across the 200-character cap; only a redaction before the cap removes all of it.
    transport, _ = _transport(_answer(400, text="x" * 190 + " " + _ENC_KEY.replace(" ", "\n")))

    result = ps.probe_chat(_BASE, _ENC_KEY, "model-x", transport=transport)

    assert result.message.endswith("...")  # premise: the excerpt was capped
    assert _ENC_KEY[:6] not in result.message


@pytest.mark.parametrize(
    ("api_key", "shown"), [("Q", "near <redacted> here"), ("", "near Q here")], ids=["one-character", "empty"],
)
def test_probe_chat_excerpt_redaction_applies_from_a_one_character_key(api_key: str, shown: str) -> None:
    transport, _ = _transport(_answer(400, text="near Q here"))

    result = ps.probe_chat(_BASE, api_key, "model-x", transport=transport)

    assert shown in result.message


def test_probe_chat_405_stays_request_rejected() -> None:
    transport, _ = _transport(_answer(405, text="POST not allowed here"))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    # B5 reads only the listing's 405 like a 404; a chat endpoint refusing POST is a rejected request.
    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.REQUEST_REJECTED, 405)


def test_probe_chat_200_without_choices_returns_bad_response() -> None:
    transport, _ = _transport(_answer(200, json={"id": "chatcmpl-1", "object": "chat.completion"}))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.BAD_RESPONSE, 200)


@pytest.mark.parametrize(
    "message",
    [
        {"role": "assistant", "content": ""},
        {"content": "  \n "},
        {"content": None},
        {"role": "assistant"},
        {"content": ["pong"]},
        {"content": "", "reasoning": " "},
    ],
    ids=["empty", "blank", "null", "absent", "list", "blank-reasoning"],
)
def test_probe_chat_200_without_text_returns_empty_response(message: dict) -> None:
    transport, _ = _transport(_answer(200, json=_completion(message)))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.EMPTY_RESPONSE, 200)
    assert "returned no text for model 'model-x'" in result.message
    assert "degraded" in result.message


def test_probe_chat_200_with_reasoning_but_no_content_returns_ok() -> None:
    transport, _ = _transport(_answer(200, json=_completion({"content": "", "reasoning": "thinking"})))

    result = ps.probe_chat(_BASE, _KEY, "model-x", transport=transport)

    assert result.outcome is ps.ProbeOutcome.OK


@pytest.mark.parametrize(
    ("choice", "fragment"),
    [
        (_choice(base_url=f"{_BASE}/"), "slash"),
        (_choice(model="model-\x1bx"), "model"),
        (_choice(model="model-\u200bx"), "model"),
        (_choice(model=""), "model"),
        (_choice(api_key="sk-\u00e9t\u00e9"), "API key"),
        (_choice(base_url="http://llm.example.test/v1"), "--allow-insecure-http"),
        (_choice(api_key="sk-ad1135<redacted>tail"), "redaction marker"),
        (
            _choice(base_url=f"https://llm.example.test/{_ENC_FORMS['quote']}/v1", api_key=_ENC_KEY),
            "the base URL contains the API key",
        ),
        (_choice(api_key=_ENC_KEY, model=f"m-{_ENC_FORMS['base64']}"), "the model for the fast tier contains the API key"),
    ],
    ids=[
        "trailing-slash", "model-escape", "model-zero-width", "model-empty", "key-non-ascii", "plain-http-key",
        "marker-key", "url-holds-key", "model-holds-key",
    ],
)
def test_validate_choice_rejects_values_that_cannot_be_written_or_sent(
    choice: ps.ProviderChoice, fragment: str,
) -> None:
    with pytest.raises(ps.SetupInputError) as exc_info:
        ps.validate_choice(choice, allow_insecure_http=False)

    assert fragment in str(exc_info.value)
    assert choice.api_key not in str(exc_info.value)


@pytest.mark.parametrize(
    ("choice", "allow_insecure_http"),
    [
        (_choice(), False),
        (_choice(base_url="http://127.0.0.1:11434/v1"), False),
        (_choice(base_url="http://localhost:11434/v1"), False),
        (_choice(base_url="http://[::1]:11434/v1"), False),
        (_choice(base_url="http://llm.example.test/v1", api_key=""), False),
        (_choice(base_url="http://llm.example.test/v1"), True),
    ],
    ids=["https", "loopback-ip", "localhost", "loopback-ipv6", "plain-http-without-key", "plain-http-override"],
)
def test_validate_choice_accepts_sendable_values(choice: ps.ProviderChoice, allow_insecure_http: bool) -> None:
    ps.validate_choice(choice, allow_insecure_http=allow_insecure_http)


@pytest.mark.parametrize(
    ("base_url", "api_key", "expected"),
    [
        ("http://llm.example.test/v1", _KEY, True),
        ("http://192.168.1.10:8000/v1", _KEY, True),
        ("https://llm.example.test/v1", _KEY, False),
        ("http://127.0.0.1:11434/v1", _KEY, False),
        ("http://localhost:11434/v1", _KEY, False),
        ("http://[::1]:11434/v1", _KEY, False),
        ("http://llm.example.test/v1", "", False),
    ],
    ids=["remote-http", "lan-http", "https", "loopback-ip", "localhost", "loopback-ipv6", "no-key"],
)
def test_sends_key_in_clear_only_for_a_key_over_plain_http_to_a_non_loopback_host(
    base_url: str, api_key: str, expected: bool,
) -> None:
    assert ps.sends_key_in_clear(base_url, api_key) is expected


@pytest.mark.parametrize(
    ("base_url", "api_key", "allow_insecure_http", "refusal"),
    [
        (_BASE, _KEY, False, None),
        ("http://llm.example.test/v1", _KEY, True, None),
        ("http://llm.example.test/v1", "", False, None),
        ("http://llm.example.test/v1", _KEY, False, "--allow-insecure-http"),
        (_BASE, "sk-\u00e9t\u00e9", False, "printable ASCII"),
        (_BASE, "sk-ad1135\ttab", True, "printable ASCII"),
        (_BASE, "sk-ad1135<redacted>tail", False, "redaction marker"),
        (_BASE, "a<", False, "API keys do not contain < or >"),
        (_BASE, "sk-ad1135>tail", False, "API keys do not contain < or >"),
    ],
    ids=[
        "https", "plain-http-override", "plain-http-without-key", "plain-http-key", "non-ascii-key", "control-key",
        "marker-key", "less-than-key", "greater-than-key",
    ],
)
def test_validate_key_transport_refuses_only_a_key_that_cannot_be_sent_as_given(
    base_url: str, api_key: str, allow_insecure_http: bool, refusal: str | None,
) -> None:
    if refusal is None:
        ps.validate_key_transport(base_url, api_key, allow_insecure_http=allow_insecure_http)
        return
    with pytest.raises(ps.SetupInputError, match=refusal) as exc_info:
        ps.validate_key_transport(base_url, api_key, allow_insecure_http=allow_insecure_http)
    assert api_key not in str(exc_info.value)


@pytest.mark.parametrize("form", list(_ENC_FORMS), ids=list(_ENC_FORMS))
def test_validate_choice_names_the_tier_whose_model_holds_the_key(form: str) -> None:
    models = {"fast": "model-a", "standard": "model-b", "deep": f"m-{_ENC_FORMS[form]}"}
    choice = ps.ProviderChoice(provider="custom", base_url=_BASE, models=models, api_key=_ENC_KEY)

    with pytest.raises(ps.SetupInputError) as exc_info:
        ps.validate_choice(choice, allow_insecure_http=False)

    assert str(exc_info.value) == "the model for the deep tier contains the API key, or an encoding of it"


@pytest.mark.parametrize("form", list(_ENC_FORMS), ids=list(_ENC_FORMS))
def test_validate_holds_no_key_refuses_each_form_and_names_the_input_not_its_value(form: str) -> None:
    with pytest.raises(ps.SetupInputError) as exc_info:
        ps.validate_holds_no_key(f"x-{_ENC_FORMS[form]}-y", _ENC_KEY, name="the widget")

    assert str(exc_info.value) == "the widget contains the API key, or an encoding of it"


def test_validate_holds_no_key_accepts_text_without_the_key_and_any_text_under_an_empty_key() -> None:
    ps.validate_holds_no_key("model-a", _ENC_KEY, name="the model")
    ps.validate_holds_no_key("", _ENC_KEY, name="the model")
    ps.validate_holds_no_key(_ENC_KEY, "", name="the model")


def test_provider_choice_repr_excludes_api_key() -> None:
    choice = _choice()

    assert _KEY not in repr(choice)
    assert _KEY not in str(choice)
    assert "model-x" in repr(choice)  # premise: the ordinary dataclass repr, with only the key left out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes; runs only on a POSIX host, such as the Linux CI job")
def test_write_config_atomic_posix_modes_are_0600(tmp_path: Path) -> None:
    home = tmp_path / "new-home"
    path = home / "config.yaml"

    assert ps.write_config_atomic(path, "a: 1\n", had_bom=False, create=True, verify=lambda p: None) is None
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    path.chmod(0o644)
    backup = ps.write_config_atomic(path, "a: 2\n", had_bom=False, create=False, verify=lambda p: None)
    assert backup is not None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


def test_provider_setup_is_imported_only_by_the_cli() -> None:
    package = Path(main_mod.__file__).resolve().parent
    assert Path(ps.__file__).resolve().parent == package  # premise: the census walks the code under test
    importers: set[str] = set()
    scanned = 0
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        if relative == "provider_setup.py":
            continue
        scanned += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = [node.value]  # importlib.import_module("probos.provider_setup") and the like
            else:
                continue
            if any("provider_setup" in name for name in names):
                importers.add(relative)

    assert scanned > 100  # premise: the walk saw the package, not an empty directory
    assert importers == {"__main__.py"}


def _values() -> dict[str, str]:
    return ps.managed_values(_choice())


def _shipped_copy(tmp_path: Path) -> Path:
    # Tests read the shipped config only to copy it; every edit happens on the copy.
    copy = tmp_path / "system.yaml"
    copy.write_bytes((_REPO_ROOT / "config" / "system.yaml").read_bytes())
    return copy


def _managed_line_indexes(text: str) -> dict[str, list[int]]:
    lines = text.splitlines(keepends=True)
    return {key: [i for i, line in enumerate(lines) if line.startswith(f"  {key}:")] for key in _values()}


def _changed_lines(old: str, new: str) -> set[int]:
    old_lines, new_lines = old.splitlines(keepends=True), new.splitlines(keepends=True)
    assert len(new_lines) == len(old_lines)  # every managed key edited in place; nothing inserted
    return {i for i, (before, after) in enumerate(zip(old_lines, new_lines)) if before != after}


def test_apply_managed_values_shipped_system_yaml_copy_changes_only_managed_lines(tmp_path: Path) -> None:
    copy = _shipped_copy(tmp_path)
    text, had_bom = ps.read_config_text(copy)
    managed = _managed_line_indexes(text)
    # Premise: the shipped file sets each of the 13 managed keys on exactly one line.
    assert (not had_bom, sorted(len(hits) for hits in managed.values())) == (True, [1] * 13)
    managed_lines = {hits[0] for hits in managed.values()}

    edited = ps.apply_managed_values(text, _values())

    changed = _changed_lines(text, edited)
    assert changed <= managed_lines
    # llm_api_format_fast is already "openai" in the shipped file, so its line keeps its bytes (B3).
    assert changed == managed_lines - {managed["llm_api_format_fast"][0]}
    assert (edited.count("\r\n"), edited.count("\n")) == (text.count("\r\n"), text.count("\n"))
    edited_path = tmp_path / "edited.yaml"
    edited_path.write_bytes(edited.encode("utf-8"))
    before, after = load_config(copy).model_dump(), load_config(edited_path).model_dump()
    assert set(after) == set(before)
    assert {name for name in before if name != "cognitive" and after[name] != before[name]} == set()
    old_cognitive, new_cognitive = before["cognitive"], after["cognitive"]
    assert {key for key in old_cognitive if old_cognitive[key] != new_cognitive[key]} <= set(managed)
    assert {key: new_cognitive[key] for key in managed} == _values()


def test_apply_managed_values_shipped_system_yaml_all_values_differ_changes_exactly_13_lines(tmp_path: Path) -> None:
    text, _ = ps.read_config_text(_shipped_copy(tmp_path))
    # The one managed value setup shares with the shipped file; changing it makes all 13 differ.
    text = text.replace("  llm_api_format_fast: openai", "  llm_api_format_fast: ollama", 1)
    assert "  llm_api_format_fast: ollama" in text  # premise: the copy was altered
    managed = _managed_line_indexes(text)

    edited = ps.apply_managed_values(text, _values())

    assert _changed_lines(text, edited) == {hits[0] for hits in managed.values()}
    assert len(_changed_lines(text, edited)) == 13


_HAND_EDITED = (
    "# ProbOS config, hand-edited\n"
    "system:\n"
    "  name: ProbOS  # keep\n"
    "\n"
    "cognitive:\n"
    "  # which endpoint the fast tier uses\n"
    "  llm_base_url_fast: http://127.0.0.1:8080/v1\n"
    "\n"
    "  llm_timeout_seconds: 300.0\n"
    "  # models\n"
    "  llm_model_fast: claude-sonnet-4.6\n"
    "  default_llm_tier: fast\n"
    "# column-0 comment before the next section\n"
    "\n"
    "memory:\n"
    "  enabled: true\n"
)


def test_apply_managed_values_preserves_comments_blank_lines_and_order() -> None:
    values = _values()
    inserted = [key for key in values if key not in ("llm_base_url_fast", "llm_model_fast")]
    expected = (
        "# ProbOS config, hand-edited\n"
        "system:\n"
        "  name: ProbOS  # keep\n"
        "\n"
        "cognitive:\n"
        "  # which endpoint the fast tier uses\n"
        f"  llm_base_url_fast: {_BASE}\n"
        "\n"
        "  llm_timeout_seconds: 300.0\n"
        "  # models\n"
        "  llm_model_fast: model-x\n"
        "  default_llm_tier: fast\n"
        + "".join(f"  {key}: {values[key]}\n" for key in inserted)
        + "# column-0 comment before the next section\n"
        "\n"
        "memory:\n"
        "  enabled: true\n"
    )

    assert ps.apply_managed_values(_HAND_EDITED, values) == expected
    assert len(inserted) == 11


def test_apply_managed_values_preserves_crlf_line_endings() -> None:
    text = _HAND_EDITED.replace("\n", "\r\n")

    edited = ps.apply_managed_values(text, _values())

    assert "\n" not in edited.replace("\r\n", "")  # every EOL, kept or inserted, is CRLF
    assert edited.count("\r\n") == text.count("\r\n") + 11
    assert edited.replace("\r\n", "\n") == ps.apply_managed_values(_HAND_EDITED, _values())


def test_apply_managed_values_preserves_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    original = codecs.BOM_UTF8 + _HAND_EDITED.replace("\n", "\r\n").encode("utf-8")
    path.write_bytes(original)

    text, had_bom = ps.read_config_text(path)
    edited = ps.apply_managed_values(text, _values())
    backup = ps.write_config_atomic(path, edited, had_bom=had_bom, create=False, verify=lambda p: None)

    assert (had_bom, text.startswith("\ufeff")) == (True, False)
    assert path.read_bytes() == codecs.BOM_UTF8 + edited.encode("utf-8")
    assert backup is not None and backup.read_bytes() == original


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  llm_model_fast: old-model  # the fast one", "  llm_model_fast: model-x  # the fast one"),
        ('  llm_model_fast: "old-model"   # quoted', "  llm_model_fast: model-x   # quoted"),
        ("  llm_model_fast:  # set me", "  llm_model_fast: model-x  # set me"),
        ("  llm_model_fast: old-model", "  llm_model_fast: model-x"),
    ],
    ids=["plain", "quoted", "empty-value", "no-comment"],
)
def test_apply_managed_values_keeps_isolated_trailing_comment(line: str, expected: str) -> None:
    edited = ps.apply_managed_values(f"cognitive:\n{line}\n", {"llm_model_fast": "model-x"})

    assert edited == f"cognitive:\n{expected}\n"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('  llm_model_fast: "a #b"  # real', "  llm_model_fast: model-x  # real"),
        ("  llm_model_fast: 'x # y'", "  llm_model_fast: model-x"),
    ],
    ids=["quoted-hash-then-comment", "quoted-hash-only"],
)
def test_apply_managed_values_hash_inside_quoted_value_is_not_a_comment(line: str, expected: str) -> None:
    edited = ps.apply_managed_values(f"cognitive:\n{line}\n", {"llm_model_fast": "model-x"})

    assert edited == f"cognitive:\n{expected}\n"


def test_apply_managed_values_unchanged_value_keeps_line_bytes() -> None:
    text = 'cognitive:\n  llm_model_fast: "model-x"   # pinned\n  llm_model_deep: old\n'
    values = {"llm_model_fast": "model-x", "llm_model_deep": "model-x"}

    edited = ps.apply_managed_values(text, values)

    assert edited == 'cognitive:\n  llm_model_fast: "model-x"   # pinned\n  llm_model_deep: model-x\n'
    assert ps.apply_managed_values(edited, values) == edited


@pytest.mark.parametrize(
    "text",
    ["system:\n  name: ProbOS\n", "system:\n  name: ProbOS", ""],
    ids=["final-eol", "no-final-eol", "empty"],
)
def test_apply_managed_values_appends_block_when_cognitive_absent(text: str) -> None:
    values = _values()

    edited = ps.apply_managed_values(text, values)

    kept = text if not text or text.endswith("\n") else text + "\n"
    assert edited == kept + "cognitive:\n" + "".join(f"  {key}: {value}\n" for key, value in values.items())


@pytest.mark.parametrize("header", ["cognitive:", "cognitive:   # provider settings"], ids=["bare", "commented"])
def test_apply_managed_values_fills_empty_cognitive_header(header: str) -> None:
    values = _values()
    text = f"system:\n  name: ProbOS\n{header}\n\nmemory:\n  enabled: true\n"

    edited = ps.apply_managed_values(text, values)

    children = "".join(f"  {key}: {value}\n" for key, value in values.items())
    assert edited == f"system:\n  name: ProbOS\n{header}\n{children}\nmemory:\n  enabled: true\n"


@pytest.mark.parametrize(
    "text",
    [
        "cognitive: {llm_model_fast: a}\n",
        "cognitive: &shared\n  llm_model_fast: a\n",
        "cognitive: !!map\n  llm_model_fast: a\n",
        "cognitive: null\n",
    ],
    ids=["flow-mapping", "anchor", "tag", "scalar"],
)
def test_apply_managed_values_flow_style_cognitive_refused(text: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match="inline content"):
        ps.apply_managed_values(text, _values())


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("cognitive:\n  llm_model_fast: a\nmemory: {}\ncognitive:\n  llm_model_deep: b\n", "more than one"),
        ('"cognitive":\n  llm_model_fast: a\n', "in quotes"),
        ("'cognitive':\n  llm_model_fast: a\n", "in quotes"),
    ],
    ids=["twice", "double-quoted", "single-quoted"],
)
def test_apply_managed_values_duplicate_cognitive_header_refused(text: str, reason: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match=reason):
        ps.apply_managed_values(text, _values())


@pytest.mark.parametrize(
    ("block", "reason"),
    [
        ("  llm_model_fast: a\n  llm_model_fast: b\n", "more than once"),
        ('  "llm_model_fast": a\n', "in quotes"),
    ],
    ids=["twice", "quoted-key"],
)
def test_apply_managed_values_duplicate_managed_key_refused(block: str, reason: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match=reason):
        ps.apply_managed_values(f"cognitive:\n{block}", _values())


def test_apply_managed_values_tab_indentation_refused() -> None:
    # PyYAML rejects tab indentation outright, so the refusal is the YAML check's.
    with pytest.raises(ps.ConfigEditRefused):
        ps.apply_managed_values("cognitive:\n\tllm_model_fast: a\n", _values())


@pytest.mark.parametrize("indicator", ["|", "|-", ">", ">+"])
def test_apply_managed_values_block_scalar_value_refused(indicator: str) -> None:
    text = f"cognitive:\n  llm_model_fast: {indicator}\n    a model\n  llm_model_deep: b\n"

    with pytest.raises(ps.ConfigEditRefused, match="single-line value"):
        ps.apply_managed_values(text, _values())


@pytest.mark.parametrize(
    "block",
    [
        "  llm_model_fast: &m a\n",
        "  llm_system_prompt_suffix_fast: &m a\n  llm_model_deep: *m\n",
        "  llm_model_fast: !!str a\n",
        "  llm_model_fast: [a]\n",
        "  llm_model_fast: {a: 1}\n",
        "  llm_model_fast:\n    - a\n",
        "  llm_model_fast: first\n    continued\n",
    ],
    ids=["anchor", "alias", "tag", "flow-sequence", "flow-mapping", "nested", "continued-plain"],
)
def test_apply_managed_values_anchor_alias_or_tag_value_refused(block: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match="single-line value"):
        ps.apply_managed_values(f"cognitive:\n{block}", _values())


@pytest.mark.parametrize(
    "text",
    ["- a\n- b\n", "just text\n", "cognitive: [a]\n", "cognitive: 3\n"],
    ids=["list", "scalar", "cognitive-list", "cognitive-scalar"],
)
def test_apply_managed_values_non_mapping_document_refused(text: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match="not a mapping"):
        ps.apply_managed_values(text, _values())


def test_apply_managed_values_key_text_inside_multiline_string_refused() -> None:
    text = (
        "cognitive:\n"
        '  llm_system_prompt_suffix_fast: "first\n'
        "  llm_model_fast: fake\n"
        '  last"\n'
        "  llm_model_deep: real\n"
    )
    # Premise: the key-looking line is string content, so the parse has no llm_model_fast at all.
    assert "llm_model_fast" not in yaml.safe_load(text)["cognitive"]

    with pytest.raises(ps.ConfigEditRefused, match="could not prove"):
        ps.apply_managed_values(text, _values())


@pytest.mark.parametrize(
    "text",
    ["cognitive:\n  llm_model_fast: a\n...\n", "--- # config\ncognitive:\n  llm_model_fast: a\n...\n"],
    ids=["end-marker", "start-and-end"],
)
def test_apply_managed_values_document_markers_other_than_one_leading_start_refused(text: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match="document marker"):
        ps.apply_managed_values(text, {"llm_model_fast": "b"})


def test_apply_managed_values_single_leading_document_start_is_kept() -> None:
    text = "--- # config\ncognitive:\n  llm_model_fast: a\n"

    assert ps.apply_managed_values(text, {"llm_model_fast": "b"}) == "--- # config\ncognitive:\n  llm_model_fast: b\n"


def test_rewrite_with_managed_values_keeps_every_setting_and_the_file_eol() -> None:
    text = "# a comment\r\ncognitive: {llm_timeout_seconds: 120, llm_model_fast: old}\r\nmemory:\r\n  enabled: true\r\n"
    with pytest.raises(ps.ConfigEditRefused):
        ps.apply_managed_values(text, _values())  # premise: the in-place editor refuses this file

    rewritten = ps.rewrite_with_managed_values(text, _values(), header="rewritten by a test")

    original = yaml.safe_load(text)
    assert yaml.safe_load(rewritten) == {**original, "cognitive": {**original["cognitive"], **_values()}}
    assert rewritten.startswith("# rewritten by a test\r\n")
    assert "\n" not in rewritten.replace("\r\n", "")
    assert "a comment" not in rewritten


def test_rewrite_with_managed_values_empty_text_gets_a_cognitive_block() -> None:
    rewritten = ps.rewrite_with_managed_values("", _values(), header="x")

    assert yaml.safe_load(rewritten) == {"cognitive": _values()}


@pytest.mark.parametrize(
    "text", ["- a\n", "cognitive: [a]\n", "cognitive: {a: [\n"], ids=["list-document", "list-cognitive", "invalid-yaml"],
)
def test_rewrite_with_managed_values_refuses_what_it_cannot_rewrite(text: str) -> None:
    with pytest.raises(ps.ConfigEditRefused):
        ps.rewrite_with_managed_values(text, _values(), header="x")


def test_write_config_atomic_backup_name_gains_a_suffix_on_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 9, 23, 12, 0, 0, tzinfo=tz)  # type: ignore[arg-type]

    monkeypatch.setattr(ps, "datetime", _Frozen)
    path = tmp_path / "config.yaml"
    path.write_bytes(b"a: 1\n")

    first = ps.write_config_atomic(path, "a: 2\n", had_bom=False, create=False, verify=lambda p: None)
    second = ps.write_config_atomic(path, "a: 3\n", had_bom=False, create=False, verify=lambda p: None)

    assert first is not None and second is not None
    assert (first.name, second.name) == ("config.yaml.bak-20260923T120000Z", "config.yaml.bak-20260923T120000Z-1")
    assert (first.read_bytes(), second.read_bytes(), path.read_bytes()) == (b"a: 1\n", b"a: 2\n", b"a: 3\n")


def test_write_config_atomic_final_replace_failure_keeps_and_names_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"a: 1\n")
    real_replace = ps.os.replace

    def replace(src: object, dst: object) -> None:
        if Path(dst) == path:
            raise PermissionError("simulated final replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(ps.os, "replace", replace)

    with pytest.raises(ps.ConfigReplaceFailed) as exc_info:
        ps.write_config_atomic(path, "a: 2\n", had_bom=False, create=False, verify=lambda p: None)

    error = exc_info.value
    assert isinstance(error, OSError)  # callers that catch OSError still catch it
    assert str(error) == "simulated final replace failure"
    assert isinstance(error.__cause__, PermissionError)
    # B5: the backup made before the failure holds the original bytes and is kept.
    assert (error.backup.parent, error.backup.read_bytes(), path.read_bytes()) == (tmp_path, b"a: 1\n", b"a: 1\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["config.yaml", error.backup.name])


def test_write_config_atomic_backup_failure_raises_the_os_error_and_keeps_no_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(b"a: 1\n")

    def replace(src: object, dst: object) -> None:
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(ps.os, "replace", replace)

    with pytest.raises(PermissionError) as exc_info:
        ps.write_config_atomic(path, "a: 2\n", had_bom=False, create=False, verify=lambda p: None)

    assert not isinstance(exc_info.value, ps.ConfigReplaceFailed)  # no backup exists to name
    assert [p.name for p in tmp_path.iterdir()] == ["config.yaml"]
    assert path.read_bytes() == b"a: 1\n"


# ----- B7: an optional tier with a model keeps the shared llm_base_url it uses where it is -----

# vision inherits the shared URL; compute_use's own URL is "", which tier_config treats as unset;
# vision_fast has its own URL; image_gen has no model.
_OPTIONAL_TIER_CONFIG = (
    "cognitive:\n"
    "  llm_base_url: http://127.0.0.1:8080/v1\n"
    "  llm_model_vision: qwen-vl\n"
    "  llm_base_url_vision_fast: http://127.0.0.1:11434/v1\n"
    "  llm_model_vision_fast: moondream\n"
    "  llm_base_url_compute_use: ''\n"
    "  llm_model_compute_use: ui-tars\n"
)
_OLD_SHARED = "http://127.0.0.1:8080/v1"


def _consumer_configured(config: object, tier: str) -> bool:
    # What the tier's runtime consumer reads: image_gen_dispatch.py:142 for image_gen, else vision_dispatch's check.
    return is_image_gen_tier_configured(config) if tier == "image_gen" else is_vision_tier_configured(config, tier)


def test_optional_tiers_are_every_runtime_tier_outside_the_text_chain() -> None:
    assert ps.OPTIONAL_TIERS == tuple(tier for tier in _LLM_TIERS if tier not in ps.TEXT_TIERS)
    assert "vision" in ps.OPTIONAL_TIERS
    assert set(ps.OPTIONAL_TIERS).isdisjoint(ps.TEXT_TIERS)


def test_optional_tier_endpoints_match_the_runtime_tier_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(_OPTIONAL_TIER_CONFIG, encoding="utf-8")
    runtime = load_config(path).cognitive

    endpoints = ps.optional_tier_endpoints(_OPTIONAL_TIER_CONFIG)

    assert list(endpoints) == list(ps.OPTIONAL_TIERS)
    for tier, endpoint in endpoints.items():
        resolved = runtime.tier_config(tier)
        assert (endpoint.base_url, endpoint.model) == (resolved["base_url"], resolved["model"])
        assert endpoint.configured is _consumer_configured(runtime, tier)
    assert {tier for tier, endpoint in endpoints.items() if endpoint.inherited} == {"vision", "compute_use", "image_gen"}
    # Premise: the consumers' checks tell these tiers apart, so the comparison above can fail. This set held image_gen
    # while every tier was read through is_vision_tier_configured, True for a tier it does not know (B8).
    assert {tier for tier, endpoint in endpoints.items() if endpoint.configured} == {"vision_fast"}


def test_tiers_using_shared_url_name_only_tiers_with_a_model_and_no_own_url() -> None:
    endpoints = ps.optional_tier_endpoints(_OPTIONAL_TIER_CONFIG)

    assert ps.tiers_using_shared_url(endpoints) == {"vision": "qwen-vl", "compute_use": "ui-tars"}


def test_optional_tier_endpoints_of_no_config_keep_nothing() -> None:
    assert ps.optional_tier_endpoints(None) == {}
    assert ps.tiers_using_shared_url({}) == {}


def test_optional_tier_endpoints_shipped_copy_has_no_tier_using_the_shared_url(tmp_path: Path) -> None:
    copy = _shipped_copy(tmp_path)
    text, _ = ps.read_config_text(copy)
    runtime = load_config(copy).cognitive

    endpoints = ps.optional_tier_endpoints(text)

    # This compared is_vision_tier_configured for image_gen too, which reads True for the shipped image_gen (B8).
    assert {tier: (e.base_url, e.model, e.configured) for tier, e in endpoints.items()} == {
        tier: (
            runtime.tier_config(tier)["base_url"], runtime.tier_config(tier)["model"], _consumer_configured(runtime, tier),
        )
        for tier in ps.OPTIONAL_TIERS
    }
    # Premise: the shipped vision tier has a model and its own URL, so it does not inherit.
    assert (bool(endpoints["vision"].model), endpoints["vision"].inherited) == (True, False)
    assert ps.tiers_using_shared_url(endpoints) == {}


@pytest.mark.parametrize(
    ("line", "field"),
    [("  llm_model_vision: [a, b]", "llm_model_vision"), ("  llm_base_url: null", "llm_base_url")],
    ids=["model-list", "shared-url-null"],
)
def test_optional_tier_endpoints_refuse_settings_that_do_not_load(line: str, field: str) -> None:
    with pytest.raises(ps.ConfigEditRefused, match=field) as exc_info:
        ps.optional_tier_endpoints(f"cognitive:\n{line}\n")

    assert "[a, b]" not in str(exc_info.value)


def test_managed_values_retaining_the_shared_url_leaves_out_only_llm_base_url() -> None:
    full = ps.managed_values(_choice())

    retained = ps.managed_values(_choice(), retain_shared_url=True)

    assert (len(full), next(iter(full))) == (13, "llm_base_url")  # premise: by default the shared URL is written
    assert list(retained) == list(full)[1:]
    assert retained == {key: value for key, value in full.items() if key != "llm_base_url"}


def _edited_file(tmp_path: Path, text: str, values: dict[str, str]) -> Path:
    path = tmp_path / "result.yaml"
    path.write_text(ps.apply_managed_values(text, values), encoding="utf-8")
    return path


def _tier_endpoint(path: Path, tier: str) -> tuple[str, str | None]:
    resolved = load_config(path).cognitive.tier_config(tier)
    return resolved["base_url"], resolved["model"]


def test_verify_config_file_accepts_a_result_that_leaves_the_shared_url_in_place(tmp_path: Path) -> None:
    kept = ps.optional_tier_endpoints(_OPTIONAL_TIER_CONFIG)
    choice = _choice()
    values = {key: value for key, value in ps.managed_values(choice).items() if key != "llm_base_url"}
    result = _edited_file(tmp_path, _OPTIONAL_TIER_CONFIG, values)

    ps.verify_config_file(result, choice, kept=kept)

    # image_gen has no model and no own URL, so it stays with the shared URL, which stayed.
    assert _tier_endpoint(result, "image_gen") == (_OLD_SHARED, None)


def test_verify_config_file_refuses_a_shared_url_moved_under_a_tier_that_uses_it(tmp_path: Path) -> None:
    kept = ps.optional_tier_endpoints(_OPTIONAL_TIER_CONFIG)
    choice = _choice()
    result = _edited_file(tmp_path, _OPTIONAL_TIER_CONFIG, ps.managed_values(choice))

    ps.verify_config_file(result, choice)  # premise: without kept endpoints only the text tiers are checked
    with pytest.raises(ps.ConfigEditRefused, match="moves the vision tier"):
        ps.verify_config_file(result, choice, kept=kept)


def test_verify_config_file_refuses_a_pin_that_makes_a_tier_configured(tmp_path: Path) -> None:
    kept = ps.optional_tier_endpoints(_OPTIONAL_TIER_CONFIG)
    choice = _choice()
    before = tmp_path / "before.yaml"
    before.write_text(_OPTIONAL_TIER_CONFIG, encoding="utf-8")
    pins = {"llm_base_url_vision": _OLD_SHARED, "llm_base_url_compute_use": _OLD_SHARED}
    result = _edited_file(tmp_path, _OPTIONAL_TIER_CONFIG, {**ps.managed_values(choice), **pins})
    # Premise: the pin keeps vision's URL and model, so only its configured-ness tells the result apart.
    assert _tier_endpoint(result, "vision") == (_OLD_SHARED, "qwen-vl")
    assert [is_vision_tier_configured(load_config(path).cognitive, "vision") for path in (before, result)] == [False, True]

    with pytest.raises(ps.ConfigEditRefused, match="whether the vision tier is configured"):
        ps.verify_config_file(result, choice, kept=kept)


def test_verify_config_file_keeps_a_no_model_tier_in_place_while_another_uses_the_shared_url(tmp_path: Path) -> None:
    # image_gen has a model and no own URL. This comment said is_vision_tier_configured reads True for it either way;
    # image_gen's own check reads the pin below as configured (B8), but vision, the tier under test, is checked first.
    text = "cognitive:\n  llm_base_url: http://127.0.0.1:8080/v1\n  llm_model_image_gen: gpt-image-1\n"
    kept = ps.optional_tier_endpoints(text)
    choice = _choice()
    result = _edited_file(tmp_path, text, {**ps.managed_values(choice), "llm_base_url_image_gen": _OLD_SHARED})
    # Premise: the pin keeps image_gen's endpoint, so vision (no model) is the tier the moved shared URL takes.
    assert (kept["image_gen"].inherited, _tier_endpoint(result, "image_gen")) == (True, (_OLD_SHARED, "gpt-image-1"))
    assert (kept["image_gen"].configured, is_image_gen_tier_configured(load_config(result).cognitive)) == (False, True)
    assert _tier_endpoint(result, "vision") == (_BASE, None)

    with pytest.raises(ps.ConfigEditRefused, match="moves the vision tier"):
        ps.verify_config_file(result, choice, kept=kept)


# vision has its own URL; compute_use has neither a model nor its own URL, so no tier uses the shared URL.
_NO_TIER_USES_THE_SHARED_URL = (
    "cognitive:\n"
    "  llm_base_url: http://127.0.0.1:8080/v1\n"
    "  llm_base_url_vision: http://127.0.0.1:11434/v1\n"
    "  llm_model_vision: qwen-vl\n"
    "  llm_timeout_compute_use: 60.0\n"
)


def test_verify_config_file_lets_a_no_model_tier_follow_a_shared_url_no_tier_uses(tmp_path: Path) -> None:
    kept = ps.optional_tier_endpoints(_NO_TIER_USES_THE_SHARED_URL)
    choice = _choice()
    result = _edited_file(tmp_path, _NO_TIER_USES_THE_SHARED_URL, ps.managed_values(choice))

    ps.verify_config_file(result, choice, kept=kept)

    assert (_tier_endpoint(result, "compute_use"), _tier_endpoint(result, "vision")) == (
        (_BASE, None), ("http://127.0.0.1:11434/v1", "qwen-vl"),
    )


def test_verify_config_file_refuses_a_no_model_tier_that_stops_following_the_shared_url(tmp_path: Path) -> None:
    kept = ps.optional_tier_endpoints(_NO_TIER_USES_THE_SHARED_URL)
    choice = _choice()
    values = {**ps.managed_values(choice), "llm_base_url_compute_use": _OLD_SHARED}
    result = _edited_file(tmp_path, _NO_TIER_USES_THE_SHARED_URL, values)

    with pytest.raises(ps.ConfigEditRefused, match="moves the compute_use tier"):
        ps.verify_config_file(result, choice, kept=kept)


# ----- B8: provider data that holds a form of the key is withheld; each optional tier's own configured check -----


@pytest.mark.parametrize("form", list(_ENC_FORMS), ids=list(_ENC_FORMS))
def test_carries_key_matches_each_form_that_redact_replaces(form: str) -> None:
    text = f"id-{_ENC_FORMS[form]}-tail"

    assert ps.carries_key(text, _ENC_KEY) is True
    assert ps.redact(text, _ENC_KEY) == "id-<redacted>-tail"


def test_carries_key_is_false_for_clean_text_empty_text_and_an_empty_key() -> None:
    assert (ps.carries_key("model-a", _ENC_KEY), ps.redact("model-a", _ENC_KEY)) == (False, "model-a")
    assert ps.carries_key("", _ENC_KEY) is False
    assert (ps.carries_key(_ENC_KEY, ""), ps.redact(_ENC_KEY, "")) == (False, _ENC_KEY)


@pytest.mark.parametrize("form", list(_ENC_FORMS), ids=list(_ENC_FORMS))
def test_probe_models_withholds_a_listed_id_that_holds_a_form_of_the_key(form: str) -> None:
    listing = {"object": "list", "data": [{"id": "model-a"}, {"id": f"org/{_ENC_FORMS[form]}"}, {"id": "model-b"}]}
    transport, seen = _transport(_answer(200, json=listing))

    result = ps.probe_models(_BASE, _ENC_KEY, transport=transport)

    assert len(set(_ENC_FORMS.values())) == len(_ENC_FORMS)  # premise: no two forms coincide
    assert seen[0].headers["authorization"] == f"Bearer {_ENC_KEY}"  # premise: the key was sent
    assert (result.outcome, result.model_ids) == (ps.ProbeOutcome.OK, ("model-a", "model-b"))
    assert result.message == "the provider lists 3 model(s); setup withholds 1 whose ID contains the API key"


def test_probe_models_withholds_ids_from_a_one_character_key_as_redaction_does() -> None:
    transport, _ = _transport(_answer(200, json={"object": "list", "data": [{"id": "gpt-4.1"}, {"id": "llama3"}]}))

    result = ps.probe_models(_BASE, "1", transport=transport)

    # The filter is redaction's matcher, which applies from one character (B6), so a short key withholds more IDs.
    assert result.model_ids == ("llama3",)


def test_probe_models_without_a_key_withholds_nothing() -> None:
    listing = {"object": "list", "data": [{"id": f"org/{_ENC_KEY}"}, {"id": "model-a"}]}
    transport, _ = _transport(_answer(200, json=listing))

    result = ps.probe_models(_BASE, "", transport=transport)

    assert (result.model_ids, result.message) == ((f"org/{_ENC_KEY}", "model-a"), "the provider lists 2 model(s)")


def test_probe_chat_404_never_offers_a_listed_id_that_holds_the_key_as_a_close_match() -> None:
    transport, _ = _transport(_answer(404, json={"error": {"code": "model_not_found"}}))
    listed = ("llama3.1", "llama3-K/9")

    result = ps.probe_chat(_BASE, "K/9", "llama3", model_ids=listed, transport=transport)

    assert (result.outcome, result.status_code) == (ps.ProbeOutcome.MODEL_REJECTED, 404)
    # Premise: difflib ranks both listed IDs as close matches, so only the filter keeps the second one out.
    assert difflib.get_close_matches("llama3", list(listed), n=5) == list(listed)
    assert result.message == "the provider does not serve model 'llama3' (HTTP 404); close matches: 'llama3.1'"


@pytest.mark.parametrize("field", ["content", "reasoning"])
def test_probe_chat_ok_message_never_includes_the_reply_text(field: str) -> None:
    reply = " ".join(f"echo {value}" for value in _ENC_FORMS.values())
    transport, _ = _transport(_answer(200, json=_completion({"role": "assistant", "content": None, field: reply})))

    result = ps.probe_chat(_BASE, _ENC_KEY, "model-x", transport=transport)

    assert (result.outcome, result.message) == (ps.ProbeOutcome.OK, "model 'model-x' answered")


def test_tier_configured_checks_are_each_optional_tier_consumers_own_check() -> None:
    shapes = [{}, {"model": "m"}, {"base_url": "http://127.0.0.1:9/v1"}, {"model": "m", "base_url": "http://127.0.0.1:9/v1"}]

    assert list(ps.TIER_CONFIGURED_CHECKS) == list(ps.OPTIONAL_TIERS)
    for tier in ps.OPTIONAL_TIERS:
        configs = [CognitiveConfig.model_validate({f"llm_{k}_{tier}": v for k, v in shape.items()}) for shape in shapes]
        answers = [ps.TIER_CONFIGURED_CHECKS[tier](config) for config in configs]
        assert answers == [_consumer_configured(config, tier) for config in configs]
        assert answers == [False, False, False, True]  # premise: each check gives both answers across these shapes
    # Premise: the vision check reads True for image_gen with nothing set, so it cannot stand in for image_gen's own.
    assert is_vision_tier_configured(CognitiveConfig(), "image_gen") is True


def test_optional_tier_endpoints_image_gen_with_a_model_and_no_own_url_reports_its_consumers_answer(
    tmp_path: Path,
) -> None:
    text = "cognitive:\n  llm_base_url: http://127.0.0.1:8080/v1\n  llm_model_image_gen: gpt-image-1\n"
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    runtime = load_config(path).cognitive

    endpoint = ps.optional_tier_endpoints(text)["image_gen"]

    assert (endpoint.base_url, endpoint.model, endpoint.inherited) == (_OLD_SHARED, "gpt-image-1", True)
    assert endpoint.configured is is_image_gen_tier_configured(runtime)
    assert endpoint.configured is False
    assert is_vision_tier_configured(runtime, "image_gen") is True  # premise: the two checks disagree here


# ----- B10: redact is one pass over the whole text, and hides every form of every key setup accepts -----

_MARKER = "<redacted>"
# Printable ASCII, as setup requires of a key, without the < and > it refuses.
_KEY_ALPHABET = "".join(chr(code) for code in range(0x20, 0x7F) if chr(code) not in "<>")


def _forms_of(api_key: str) -> list[str]:
    raw = api_key.encode()
    return [
        api_key, quote(api_key, safe=""), quote_plus(api_key),
        base64.b64encode(raw).decode(), base64.b64encode(b"Bearer " + raw).decode(),
    ]


def _accepted(api_key: str) -> bool:
    try:
        ps.validate_key_transport(_BASE, api_key, allow_insecure_http=False)
    except ps.SetupInputError:
        return False
    return True


def test_validate_key_transport_refuses_every_part_of_the_marker_with_one_fixed_message() -> None:
    parts = {_MARKER[i:j] for i in range(len(_MARKER)) for j in range(i + 1, len(_MARKER) + 1)}
    inner = {part for part in parts if "<" not in part and ">" not in part}
    assert (len(parts), len(inner)) == (52, 33)  # premise: every distinct part; 33 lie inside "redacted"
    # A percent form made only of letters is the key itself, so only these keys have a literal or percent form there.
    assert all(unquote(part) == unquote_plus(part) == part for part in inner)
    messages = set()
    for part in sorted(parts):
        with pytest.raises(ps.SetupInputError) as exc_info:
            ps.validate_key_transport(_BASE, part, allow_insecure_http=False)
        if part in inner:
            messages.add(str(exc_info.value))
    # One fixed text for all 33, so it cannot be echoing a key that merely shares its letters.
    assert messages == {"the API key is part of setup's redaction marker '<redacted>'"}


def test_no_base64_window_of_the_marker_word_decodes_to_printable_ascii() -> None:
    word = _MARKER[1:-1]
    windows = [word[i:i + size] for size in (4, 8) for i in range(len(word) - size + 1)]
    # Premise: base64 comes in 4s and "redacted" holds no "=", so a base64 form could lie only in these.
    assert windows == ["reda", "edac", "dact", "acte", "cted", "redacted"]
    for window in windows:
        decoded = base64.b64decode(window, validate=True)
        assert base64.b64encode(decoded).decode() == window  # premise: only these bytes encode to the window
        assert not (decoded.isascii() and decoded.decode("ascii").isprintable()), (window, decoded)
    # The shortest Bearer form, a one-character key's, is already longer than "redacted".
    assert len(base64.b64encode(b"Bearer x")) == 12 > len(word)


def test_redact_is_one_pass_over_the_whole_text_and_exempts_no_marker() -> None:
    # The reviewer's reproducer; setup now also refuses this key. The marker split printed it intact here.
    assert ps.redact("a<redacted>", "a<") == "<redacted>redacted>"


def test_redact_hides_every_form_of_every_accepted_key_beside_and_between_markers() -> None:
    rng = random.Random(1135)
    candidates = [*_KEY_ALPHABET]  # every one-character key, the six letters of "redacted" among them
    candidates += ["".join(rng.choices(_KEY_ALPHABET, k=rng.randint(2, 12))) for _ in range(300)]
    keys = [key for key in candidates if _accepted(key)]
    # Premise: every length from 1 to 12, and keys whose five forms all differ, so each form is exercised alone.
    assert {len(key) for key in keys} == set(range(1, 13))
    assert sum(len(set(_forms_of(key))) == 5 for key in keys) >= 10
    joins = ("", " ", "\t\n", _MARKER, f" {_MARKER} ", _MARKER * 2)
    failures = []
    for key in keys:
        forms = _forms_of(key)
        text = _MARKER + "".join(first + join + second + join for join in joins for first in forms for second in forms)
        assert ps.carries_key(text, key)  # premise: the input holds the key
        once = ps.redact(text, key)
        if ps.carries_key(once, key) or any(form in once for form in forms) or ps.redact(once, key) != once:
            failures.append(key)
    assert failures == []
    assert set("redact").isdisjoint(keys)  # premise: acceptance is what left out the keys inside the marker
