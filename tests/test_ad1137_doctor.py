"""AD-1137 (#1056): ``probos doctor`` checks what ``probos`` would use, and says how to fix it.

In-process tests of the config file doctor resolves, the provider check it shares
with ``probos setup``, the Python and optional-extras checks, its rendering, the
setup hint that names it, and the boot banner. Provider traffic
goes to an ``httpx.MockTransport`` that records every request, or, in one test, to
a provider on 127.0.0.1:0 that sends its answer slowly, so no test can reach a
network; the home directory, the checkout's ``config/system.yaml`` and
the data directory are all redirected into ``tmp_path``.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import socket
import sys
import threading
import time
import tomllib
from collections.abc import Callable
from importlib import metadata
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import BaseModel, ValidationError, field_validator
from rich.console import Console

import probos.__main__ as main_mod
from probos import provider_setup as ps
from probos.config import load_config
from probos.doctor import registry as doctor_registry
from probos.doctor.checks import extras_check, llm_check, python_check
from probos.doctor.checks.config_check import _ConfigCheck
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor import runner as doctor_runner
from probos.doctor.runner import build_context, run_doctor

_KEY = "sk-ad1137-doctor-sentinel-4F7Q"
_OTHER_KEY = "sk-ad1137-doctor-vision-key-8M2X"
_KEY_ENV = "PROBOS_TEST_AD1137_DOCTOR_KEY"
_MODEL = "model-x"
_BASE = "https://llm.example.test/v1"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ABSENT = "probos-ad1137-absent-distribution"
OK, WARN, FAIL = CheckOutcome.OK, CheckOutcome.WARN, CheckOutcome.FAIL

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml")
    monkeypatch.setattr(main_mod, "_default_data_dir", lambda: tmp_path / "data")
    for name in ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", _KEY_ENV, *_PROXY_VARS):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)


# ----- helpers -----


def _completion(content: object) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}


def _listing(*model_ids: str) -> Handler:
    return lambda request: httpx.Response(200, json={"object": "list", "data": [{"id": m} for m in model_ids]})


def _status(status: int, **kwargs: object) -> Handler:
    return lambda request: httpx.Response(status, **kwargs)


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _stall(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


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

    def calls(self) -> list[tuple[str, str, str]]:
        return [(request.method, request.url.host, request.url.path) for request in self.requests]


def _cognitive(**overrides: object) -> dict:
    values: dict[str, object] = {"llm_base_url": _BASE}
    for tier in ps.TEXT_TIERS:
        values[f"llm_base_url_{tier}"] = _BASE
        values[f"llm_api_key_{tier}"] = _KEY
        values[f"llm_model_{tier}"] = _MODEL
        values[f"llm_api_format_{tier}"] = "openai"
    values.update(overrides)
    return values


def _write(path: Path, document: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def _ctx(tmp_path: Path, provider: _Provider, cognitive: dict | None = None) -> DoctorContext:
    path = _write(tmp_path / "checked.yaml", {"cognitive": _cognitive() if cognitive is None else cognitive})
    return build_context(
        home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=path, transport=provider.transport,
    )


def _bare(tmp_path: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)


async def _llm(tmp_path: Path, provider: _Provider, cognitive: dict | None = None) -> CheckResult:
    return await llm_check._LLMCheck().run(_ctx(tmp_path, provider, cognitive))


def _shown(result: CheckResult) -> str:
    return " ".join(f"{result.message}\n{result.remediation}".split())


def _setup_args(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    return parser.parse_args(["setup", *argv])


def _main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> object:
    monkeypatch.setattr(sys, "argv", ["probos", *argv])
    monkeypatch.setattr(main_mod.asyncio, "set_event_loop_policy", lambda policy: None)
    with pytest.raises(SystemExit) as exc_info:
        main_mod.main()
    return exc_info.value.code


class _Recorder:
    """A doctor check that records the context it is handed."""

    name = "recorder"

    def __init__(self) -> None:
        self.contexts: list[DoctorContext] = []

    async def run(self, ctx: DoctorContext) -> CheckResult:
        self.contexts.append(ctx)
        return CheckResult(OK, "recorded")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    check = _Recorder()
    monkeypatch.setattr(doctor_registry, "_CHECKS", [check])
    monkeypatch.setattr(doctor_registry, "_NAMES", {check.name})
    return check


# ----- which config and data directory doctor checks -----


def test_cmd_doctor_checks_the_home_config_probos_loads(tmp_path: Path, recorder: _Recorder) -> None:
    home_config = _write(tmp_path / "home" / "config.yaml", {"system": {"name": "home"}})
    _write(tmp_path / "repo" / "config" / "system.yaml", {"system": {"name": "repo"}})

    assert main_mod._cmd_doctor(argparse.Namespace(command="doctor")) == 0

    (ctx,) = recorder.contexts
    assert (ctx.config_target, ctx.config_path, ctx.config.system.name) == (home_config, home_config, "home")


def test_cmd_doctor_falls_back_to_the_checkout_config_like_the_shell(tmp_path: Path, recorder: _Recorder) -> None:
    repo_default = _write(tmp_path / "repo" / "config" / "system.yaml", {"system": {"name": "repo"}})

    assert main_mod._cmd_doctor(argparse.Namespace(command="doctor")) == 0

    # Before AD-1137 doctor read only ~/.probos/config.yaml and reported it missing here.
    (ctx,) = recorder.contexts
    assert ctx.config_path == repo_default == main_mod._resolve_config_path(None)
    assert ctx.config.system.name == "repo"


@pytest.mark.parametrize(
    "argv",
    [("--config", "{}", "doctor"), ("doctor", "--config", "{}"), ("-c", "{}", "doctor"), ("doctor", "-c", "{}")],
    ids=["root-flag", "doctor-flag", "root-short", "doctor-short"],
)
def test_main_doctor_honours_config_before_or_after_the_subcommand(
    argv: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: _Recorder,
) -> None:
    _write(tmp_path / "home" / "config.yaml", {"system": {"name": "home"}})
    explicit = _write(tmp_path / "elsewhere" / "node.yaml", {"system": {"name": "explicit"}})

    assert _main(monkeypatch, *(part.format(explicit) for part in argv)) == 0

    (ctx,) = recorder.contexts
    assert (ctx.config_path, ctx.config.system.name) == (explicit, "explicit")


@pytest.mark.parametrize(
    "argv", [("--data-dir", "{}", "doctor"), ("doctor", "--data-dir", "{}")], ids=["root-flag", "doctor-flag"],
)
def test_main_doctor_honours_data_dir_before_or_after_the_subcommand(
    argv: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorder: _Recorder,
) -> None:
    chosen = tmp_path / "chosen-data"

    assert _main(monkeypatch, *(part.format(chosen) for part in argv)) == 0

    (ctx,) = recorder.contexts
    assert ctx.data_dir == chosen


def test_cmd_doctor_defaults_the_data_dir_to_the_platform_directory(tmp_path: Path, recorder: _Recorder) -> None:
    assert main_mod._cmd_doctor(argparse.Namespace(command="doctor")) == 0

    (ctx,) = recorder.contexts
    assert ctx.data_dir == tmp_path / "data"  # main_mod._default_data_dir, patched by _isolate


def test_build_context_without_a_config_path_keeps_the_ad801_default(tmp_path: Path) -> None:
    ctx = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data")

    assert (ctx.config_target, ctx.config_path, ctx.config, ctx.config_error) == (
        tmp_path / "home" / "config.yaml", None, None, "",
    )


async def test_config_check_names_a_missing_file_and_its_fix(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    ctx = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=missing)

    result = await _ConfigCheck().run(ctx)

    assert result.outcome is FAIL
    assert result.message == f"No config file at {missing}: probos would start on built-in defaults"
    assert "probos setup" in result.remediation


@pytest.mark.parametrize(
    ("content", "expected", "withheld"),
    [
        (b"cognitive:\n  llm_timeout_seconds: [ad1137-unclosed\n", "not valid YAML (line ", "ad1137-unclosed"),
        (b"- ad1137-first\n- second\n", "its top level is not a mapping of config sections", "ad1137-first"),
        (
            b"cognitive:\n  llm_timeout_seconds: ad1137-not-a-number\n",
            "invalid settings: cognitive.llm_timeout_seconds: ",
            "ad1137-not-a-number",
        ),
        (b"system:\n  name: \xff\xfe\n", "not valid UTF-8 text", None),
    ],
    ids=["yaml", "not-a-mapping", "invalid-setting", "not-utf8"],
)
async def test_config_check_says_why_a_file_does_not_load(
    content: bytes, expected: str, withheld: str | None, tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_bytes(content)
    ctx = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=path)

    result = await _ConfigCheck().run(ctx)

    assert (ctx.config, result.outcome) == (None, FAIL)
    assert result.message.startswith(f"Config {path} does not load: ")
    assert expected in result.message
    if withheld is not None:
        assert withheld not in result.message  # the file's own text is never repeated


def test_describe_load_failure_withholds_a_secret_the_error_repeats(tmp_path: Path) -> None:
    secret = "sk-ad1137-config-secret-5T9W"
    path = _write(tmp_path / "config.yaml", {"cognitive": {"llm_api_key": secret}})

    class _Echoes(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def _reject(cls, value: str) -> str:
            raise ValueError(f"rejected {value}")

    with pytest.raises(ValidationError) as exc_info:
        _Echoes(value=secret)

    detail = doctor_runner.describe_load_failure(exc_info.value, path)

    assert detail == "invalid settings: value: Value error, rejected <redacted>"


def test_build_context_logs_no_value_from_a_config_that_does_not_load(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-ad1137-log-secret-9Q3Z"
    path = _write(tmp_path / "config.yaml", {"cognitive": {"llm_timeout_seconds": secret}})
    with pytest.raises(ValidationError) as exc_info:
        load_config(path)
    assert secret in str(exc_info.value)  # premise: the exception quotes the value (Pydantic's input_value)
    caplog.set_level(logging.DEBUG, logger=doctor_runner.logger.name)

    ctx = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=path)

    # AD-1137 A-2 (review round 1): the record carried the traceback, and so the value; now the class and reason.
    (record,) = [record for record in caplog.records if record.name == doctor_runner.logger.name]
    assert record.exc_info is None
    assert record.getMessage() == f"AD-1137: doctor could not load {path} (ValidationError: {ctx.config_error})"
    assert secret not in caplog.text


# ----- the LLM check: setup's probes, setup's reading -----


async def test_llm_check_passes_when_every_text_tier_answers(tmp_path: Path) -> None:
    provider = _Provider()

    result = await _llm(tmp_path, provider)

    assert result.outcome is OK
    assert result.message == f"LLM tiers answer: fast, standard, deep: model '{_MODEL}' at {_BASE}"
    # One listing and one chat serve all three tiers: they share the endpoint, key and model.
    assert provider.calls() == [
        ("GET", "llm.example.test", "/v1/models"), ("POST", "llm.example.test", "/v1/chat/completions"),
    ]
    assert {request.headers["Authorization"] for request in provider.requests} == {f"Bearer {_KEY}"}


_FAILURES = [
    (_status(401), None, FAIL, "the provider rejected the API key (HTTP 401)", "Check the API key"),
    (_status(403), None, FAIL, "the provider rejected the API key (HTTP 403)", "Check the API key"),
    (_status(404), _status(404), FAIL, "no OpenAI-compatible API at this base URL", "usually end in /v1"),
    (_listing("model-y"), _status(404), FAIL, "the provider does not serve model 'model-x' (HTTP 404)", "Choose a model"),
    (
        _status(307, headers={"Location": "https://elsewhere.example.test/v1/models"}), None, FAIL,
        "the provider redirected the model listing elsewhere (HTTP 307)", "provider's own API URL",
    ),
    (_refuse, None, FAIL, "could not reach the provider (ConnectError)", "Start the provider"),
    (_stall, None, FAIL, "the provider did not answer within 10 s (ReadTimeout)", "not overloaded"),
    (_status(429), None, WARN, "the provider rate-limited the model listing (HTTP 429)", "rate-limiting"),
    (None, _status(500), FAIL, "the provider failed the chat check for model 'model-x' (HTTP 500)", "check its status"),
    (None, _status(400), FAIL, "the provider rejected the chat check for model 'model-x' (HTTP 400)", "model name"),
    (
        None, lambda request: httpx.Response(200, json=_completion("")), FAIL,
        "the provider answered but returned no text for model 'model-x'", "without text",
    ),
    (
        lambda request: httpx.Response(200, text="<html>a web page</html>"), None, FAIL,
        "the model listing is not an OpenAI-compatible JSON response", "OpenAI-compatible API answered",
    ),
]
_FAILURE_IDS = [
    "401", "403", "no-api", "unknown-model", "redirect", "unreachable", "timeout", "rate-limited",
    "provider-error", "request-rejected", "empty-reply", "web-page",
]


@pytest.mark.parametrize(("listing", "chat", "outcome", "said", "fix"), _FAILURES, ids=_FAILURE_IDS)
async def test_llm_check_names_what_failed_and_the_fix(
    listing: Handler | None, chat: Handler | None, outcome: CheckOutcome, said: str, fix: str, tmp_path: Path,
) -> None:
    result = await _llm(tmp_path, _Provider(listing=listing, chat=chat))

    assert result.outcome is outcome
    if outcome is FAIL:
        assert result.message == "LLM tier check failed for fast, standard, deep"
    else:
        assert result.message == "LLM tiers answer: none; not verified: fast, standard, deep"
    assert result.remediation.startswith(f"fast, standard, deep: {_BASE}: ")
    assert said in _shown(result)
    assert fix in result.remediation


def test_every_failed_probe_outcome_names_a_fix() -> None:
    assert set(llm_check.REMEDIATION) == set(ps.ProbeOutcome) - {ps.ProbeOutcome.OK}
    assert all(fix.strip() for fix in llm_check.REMEDIATION.values())


_AGREEMENT = [(listing, chat) for listing, chat, *_ in _FAILURES] + [
    (None, None), (_status(404), None), (_status(405), None),
]


@pytest.mark.parametrize(
    ("listing", "chat"), _AGREEMENT, ids=[*_FAILURE_IDS, "answers", "listing-404", "listing-405"],
)
async def test_doctor_passes_exactly_when_setup_accepts_the_same_provider(
    listing: Handler | None, chat: Handler | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    flags = ("--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, "--model", _MODEL, "--yes")
    setup = main_mod._cmd_setup(
        _setup_args(*flags, "--config", str(tmp_path / "setup.yaml")),
        transport=_Provider(listing=listing, chat=chat).transport,
    )

    doctor = await _llm(tmp_path, _Provider(listing=listing, chat=chat))

    # No third status classifier: doctor reads the probes as setup reads them.
    assert (setup == 0) is (doctor.outcome is OK)


async def test_llm_check_redacts_every_configured_key(tmp_path: Path) -> None:
    echo = lambda request: httpx.Response(400, json={"error": {"message": f"keys {_KEY} {_OTHER_KEY}"}})  # noqa: E731
    cognitive = _cognitive(
        llm_base_url_vision="https://vision.example.test/v1", llm_model_vision="vision-model", llm_api_key_vision=_OTHER_KEY,
    )

    result = await _llm(tmp_path, _Provider(listing=_listing(_MODEL, "vision-model"), chat=echo), cognitive)

    shown = _shown(result)
    assert result.outcome is FAIL
    assert "llm.example.test" in shown and "vision.example.test" in shown  # premise: both endpoints answered
    assert shown.count("<redacted>") >= 2
    assert not ps.carries_key(shown, _KEY) and not ps.carries_key(shown, _OTHER_KEY)


async def test_llm_check_shows_urls_without_credentials(tmp_path: Path) -> None:
    base = "https://ad1137user:ad1137pass@llm.example.test:8443/v1"

    result = await _llm(
        tmp_path, _Provider(listing=_status(401)), _cognitive(**{f"llm_base_url_{t}": base for t in ps.TEXT_TIERS}),
    )

    shown = _shown(result)
    assert "https://llm.example.test:8443/v1: the provider rejected the API key" in shown
    assert "ad1137user" not in shown and "ad1137pass" not in shown


async def test_llm_check_withholds_a_credential_in_the_url_path(tmp_path: Path) -> None:
    secret = "sk-ad1137-urlpath-8623"
    cognitive = _cognitive(
        **{f"llm_base_url_{t}": f"https://llm.example.test/private/{secret}/v1" for t in ps.TEXT_TIERS},
        llm_base_url_image_gen=f"https://images.example.test/{secret}/v1", llm_model_image_gen="image-model",
    )

    result = await _llm(tmp_path, _Provider(listing=_status(401)), cognitive)

    # AD-1137 A-2 (review round 1): the whole path was shown, so a credential in it reached every tier line.
    shown = _shown(result)
    assert "https://llm.example.test/<redacted>/<redacted>/v1: the provider rejected the API key" in shown
    assert "https://images.example.test/<redacted>/v1: not checked" in shown  # premise: both lines show a URL
    assert secret not in shown and "private" not in shown


@pytest.mark.parametrize(
    ("base_url", "shown"),
    [
        ("https://u:ad1137pass@llm.example.test:8443/v1?token=ad1137q#ad1137f", "https://llm.example.test:8443/v1"),
        ("http://[::1]:8080/v1", "http://[::1]:8080/v1"),
        ("http://localhost:11434/v1/", "http://localhost:11434/v1/"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://llm.example.test:not-a-port/v1", "the configured base URL"),
        (
            "https://llm.example.test/private/sk-ad1137-urlpath-8623/v1",
            "https://llm.example.test/<redacted>/<redacted>/v1",
        ),
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1"),
        ("https://gen.example.test/v1beta/openai/", "https://gen.example.test/v1beta/openai/"),
        ("https://api.example.test/inference/v1", "https://api.example.test/inference/v1"),
        ("https://api.example.test/compatible-mode/v1", "https://api.example.test/compatible-mode/v1"),
        ("https://llm.example.test/v123/V1", "https://llm.example.test/<redacted>/V1"),
        ("https://llm.example.test/v1;ad1137param", "https://llm.example.test/<redacted>"),
        ("https://llm.example.test/%76%31/v1", "https://llm.example.test/<redacted>/v1"),
    ],
    ids=[
        "credentials", "ipv6", "plain", "no-path", "bad-port", "path-secret", "api-v1", "v1beta-openai",
        "inference", "compatible-mode", "version-bound", "path-params", "percent-encoded",
    ],
)
def test_shown_base_url_keeps_only_the_api_path(base_url: str, shown: str) -> None:
    # AD-1137 A-2: moved from llm_check._shown_url, which also kept every path segment, to one rule for all displays.
    assert ps.shown_base_url(base_url) == shown


@pytest.mark.parametrize(
    ("base_url", "keys", "shown"),
    [
        ("https://standin.invalid/compatible-mode/v1", ["compatible-mode"], "https://standin.invalid/<redacted>/v1"),
        ("https://standin.invalid/v1", ["v1"], "https://standin.invalid/<redacted>"),
        ("https://standin.invalid/api/v1", ["api/v1"], "https://standin.invalid/<redacted>"),
        ("https://sk-ad1137-a3-host.example.test/v1", ["sk-ad1137-a3-host"], "https://<redacted>.example.test/v1"),
        ("https://sk-a3-longer.example.test/v1", ["sk-a3", "sk-a3-longer"], "https://<redacted>.example.test/v1"),
        ("http://127.0.0.1:8080/v1", ["1"], "http://<redacted>27.0.0.<redacted>:8080/v<redacted>"),
        ("https://openrouter.ai/api/v1", ["sk-ad1137-a3-unrelated"], "https://openrouter.ai/api/v1"),
    ],
    ids=["path-word", "version", "across-segments", "host", "longest-first", "short-key", "unrelated"],
)
def test_shown_base_url_withholds_every_configured_key(base_url: str, keys: list[str], shown: str) -> None:
    for key in keys:
        ps.validate_key_transport(base_url, key, allow_insecure_http=True)  # premise: keys setup itself accepts
    # AD-1137 A-3 (review round 2): the segment rule keeps API words, versions and the host, and so a key there.
    kept = ps.shown_base_url(base_url)
    assert any(ps.carries_key(kept, key) for key in keys) is (shown != kept)

    assert ps.shown_base_url(base_url, keys) == shown
    assert not any(ps.carries_key(shown, key) for key in keys)  # a short key costs readability, never the key


def test_redact_keys_replaces_the_longest_key_first() -> None:
    text = "one sk-a3-longer two sk-a3 three"

    assert ps.redact("one sk-a3-longer", "sk-a3") == "one <redacted>-longer"  # premise: the short key splits the long
    assert ps.redact_keys(text, ["sk-a3", "sk-a3-longer"]) == "one <redacted> two <redacted> three"
    assert ps.redact_keys(text, []) == ps.redact_keys(text, [""]) == text


def test_configured_api_keys_names_each_key_a_tier_would_send(tmp_path: Path) -> None:
    shared = "sk-ad1137-a3-shared-key"
    cognitive = _cognitive(
        llm_api_key=shared, llm_api_key_deep=None,
        llm_base_url_vision="https://vision.example.test/v1", llm_model_vision="vision-model", llm_api_key_vision=_OTHER_KEY,
    )

    keys = ps.configured_api_keys(load_config(_write(tmp_path / "keys.yaml", {"cognitive": cognitive})).cognitive)

    # deep has no key of its own, so it sends the shared one, as the unconfigured optional tiers would.
    assert keys == [_OTHER_KEY, _KEY, shared]
    assert ps.configured_api_keys(load_config(_write(tmp_path / "none.yaml", {"cognitive": {}})).cognitive) == []


async def test_llm_check_probes_configured_optional_tiers_only(tmp_path: Path) -> None:
    provider = _Provider(listing=_listing(_MODEL, "vision-model"))
    cognitive = _cognitive(llm_base_url_vision="https://vision.example.test/v1", llm_model_vision="vision-model")

    result = await _llm(tmp_path, provider, cognitive)

    assert result.outcome is OK
    assert result.message.endswith("; vision: model 'vision-model' at https://vision.example.test/v1")
    # vision_fast, compute_use and image_gen are unconfigured, so nothing probes them.
    assert [host for _, host, _ in provider.calls()] == ["llm.example.test"] * 2 + ["vision.example.test"] * 2


async def test_llm_check_reports_tiers_it_does_not_probe(tmp_path: Path) -> None:
    provider = _Provider()
    cognitive = _cognitive(
        llm_api_format_deep="ollama",
        llm_base_url_image_gen="https://images.example.test/v1",
        llm_model_image_gen="image-model",
    )

    result = await _llm(tmp_path, provider, cognitive)

    assert result.outcome is WARN
    assert result.message == "LLM tiers answer: fast, standard; not verified: deep, image_gen"
    assert "this tier uses api_format ollama" in _shown(result)
    assert "probos setup --provider ollama" in result.remediation
    assert "would create an image" in _shown(result)
    assert {host for _, host, _ in provider.calls()} == {"llm.example.test"}


async def test_llm_check_fails_a_text_tier_without_a_model(tmp_path: Path) -> None:
    provider = _Provider()

    result = await _llm(tmp_path, provider, _cognitive(llm_model_fast=""))

    assert result.outcome is FAIL
    assert result.message == "LLM tier check failed for fast (standard, deep answer)"
    assert "no model is configured" in result.remediation and "llm_model_fast" in result.remediation
    assert [json.loads(request.content)["model"] for request in provider.requests if request.method == "POST"] == [
        _MODEL,
    ]


@pytest.mark.parametrize(("tier_timeout", "expected"), [(7.0, 7.0), (300.0, 30.0)], ids=["tier", "capped"])
async def test_llm_check_waits_as_long_as_the_runtime_boot_probe(
    tier_timeout: float, expected: float, tmp_path: Path,
) -> None:
    provider = _Provider()

    await _llm(tmp_path, provider, _cognitive(**{f"llm_timeout_{t}": tier_timeout for t in ps.TEXT_TIERS}))

    # llm_client.py _check_endpoint (BF-270): min(tier timeout, 30 s); the listing keeps setup's 10 s.
    waits = [(request.method, request.extensions["timeout"]["read"]) for request in provider.requests]
    assert waits == [("GET", ps.MODELS_PROBE_TIMEOUT_S), ("POST", expected)]


async def test_llm_check_is_skipped_when_the_config_did_not_load(tmp_path: Path) -> None:
    result = await llm_check._LLMCheck().run(_bare(tmp_path))

    assert (result.outcome, result.message) == (WARN, "LLM tiers: skipped (config unavailable)")


async def test_llm_check_reports_a_probe_that_raises_as_a_failed_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> ps.ProbeResult:
        raise ValueError("ad1137-hidden-detail")

    monkeypatch.setattr(ps, "probe_models", explode)

    result = await _llm(tmp_path, _Provider())

    assert result.outcome is FAIL
    assert "the check could not run (ValueError)" in result.remediation
    assert "ad1137-hidden-detail" not in _shown(result)


async def test_llm_check_logs_only_the_type_of_a_probe_that_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    def explode(*args: object, **kwargs: object) -> ps.ProbeResult:
        raise ValueError("https://ad1137user:ad1137pass@llm.example.test/v1")

    monkeypatch.setattr(ps, "probe_models", explode)
    caplog.set_level(logging.DEBUG, logger=llm_check.logger.name)

    await _llm(tmp_path, _Provider())

    # AD-1137 A-2 (review round 1): the DEBUG record held the exception's text; now only its type.
    records = [record for record in caplog.records if record.name == llm_check.logger.name]
    assert [record.getMessage() for record in records] == [
        f"AD-1137: doctor could not probe the {tier} tier (ValueError); reporting it as failed"
        for tier in ps.TEXT_TIERS
    ]
    assert all(record.exc_info is None for record in records)
    assert "ad1137pass" not in caplog.text


class _Clock:
    """Stands in for llm_check._clock: a slow provider advances it instead of making the test wait."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _hangs(clock: _Clock) -> Handler:
    """A provider that holds a request for its whole read timeout, then times out."""

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += request.extensions["timeout"]["read"]
        raise httpx.ReadTimeout("timed out", request=request)

    return handler


def _answers_after(clock: _Clock, seconds: float) -> Handler:
    """A provider that answers a chat check after ``seconds``."""

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += seconds
        return httpx.Response(200, json=_completion("pong"))

    return handler


async def test_llm_check_starts_no_probe_past_its_time_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    provider = _Provider(chat=_hangs(clock))
    tiers = (*ps.TEXT_TIERS, "vision", "vision_fast", "compute_use")
    cognitive = _cognitive(
        **{f"llm_base_url_{tier}": f"https://{tier.replace('_', '-')}.example.test/v1" for tier in tiers},
        **{f"llm_model_{tier}": _MODEL for tier in tiers},
    )

    result = await _llm(tmp_path, provider, cognitive)

    # AD-1137 A-2 (review round 1): six endpoints whose chat checks hang took 6 x 30 s; now nothing starts past 60 s.
    assert clock.now == llm_check.LLM_CHECK_BUDGET_S == 60.0
    assert provider.calls() == [
        ("GET", "fast.example.test", "/v1/models"), ("POST", "fast.example.test", "/v1/chat/completions"),
        ("GET", "standard.example.test", "/v1/models"), ("POST", "standard.example.test", "/v1/chat/completions"),
    ]
    assert (result.outcome, result.message) == (FAIL, "LLM tier check failed for fast, standard")
    for host in ("deep", "vision", "vision-fast", "compute-use"):
        # AD-1137 A-3: "the tiers before it used" was untrue when a tier's own listing used the time; now the wait is named.
        assert (
            f"https://{host}.example.test/v1: not checked: less than the model listing's 10 s timeout is left of "
            "doctor's 60 s for provider checks"
        ) in _shown(result)


async def test_llm_check_reports_a_tier_its_time_budget_left_unchecked_as_not_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    provider = _Provider(listing=_listing("model-a", "model-b", "model-c"), chat=_answers_after(clock, 29.0))
    cognitive = _cognitive(llm_model_fast="model-a", llm_model_standard="model-b", llm_model_deep="model-c")

    result = await _llm(tmp_path, provider, cognitive)

    # Each chat check answers in 29 s, so a third (58 s + its 30 s) would not fit: deep is reported, not guessed.
    assert [json.loads(request.content)["model"] for request in provider.requests if request.method == "POST"] == [
        "model-a", "model-b",
    ]
    assert (result.outcome, result.message) == (WARN, "LLM tiers answer: fast, standard; not verified: deep")
    # AD-1137 A-3: "Fix the tiers above" assumed an earlier tier; the slow one can be the tier itself.
    assert "Fix the slow or failing tiers listed here, then rerun `probos doctor`." in result.remediation


async def test_llm_check_resolves_a_tier_that_shares_a_probe_after_the_budget_is_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    provider = _Provider(chat=_hangs(clock))
    cognitive = _cognitive(llm_base_url_standard="https://standard.example.test/v1")  # fast and deep share one

    result = await _llm(tmp_path, provider, cognitive)

    # standard's probes spend the budget; deep needs no new request, so it is resolved, not reported unchecked.
    assert (clock.now, len(provider.requests)) == (60.0, 4)
    assert result.message == "LLM tier check failed for fast, standard, deep"
    assert "not checked" not in _shown(result)


def _lists_after(clock: _Clock, seconds: float) -> Handler:
    """A provider that answers the model listing after ``seconds``."""

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += seconds
        return _listing(_MODEL)(request)

    return handler


class _Stall:
    """A chat check still running at doctor's deadline: it moves the clock past it, then waits for the test."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self._clock.now = llm_check.LLM_CHECK_BUDGET_S + 1.0
        self.entered.set()
        self.release.wait(5.0)
        return httpx.Response(200, json=_completion("pong"))


class _Trickle:
    """A provider on 127.0.0.1:0 that sends each answer a byte every ``gap`` s for ``for_s`` s, then the rest.

    httpx's timeouts bound each read, so a probe timeout far shorter than ``for_s`` does not end the request.
    ``open`` counts the connections it is answering, and ``gone`` is set when a client leaves before its answer.
    """

    def __init__(self, gap: float, for_s: float) -> None:
        self._gap, self._for_s = gap, for_s
        self.connections = 0
        self.open = 0
        self.gone = threading.Event()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.base_url = f"http://127.0.0.1:{self._server.getsockname()[1]}/v1"
        threading.Thread(target=self._serve, name="ad1137-trickle", daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:  # closed
                return
            self.connections += 1
            threading.Thread(target=self._answer, args=(conn,), name="ad1137-trickle-answer", daemon=True).start()

    def _answer(self, conn: socket.socket) -> None:
        body = json.dumps({"object": "list", "data": [{"id": _MODEL}]}).encode("utf-8")
        answer = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
        with self._lock:
            self.open += 1
        try:
            with conn:
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = conn.recv(65536)
                    if not chunk:
                        return
                    request += chunk
                sent, started = 0, time.monotonic()
                while sent < len(answer) and time.monotonic() - started < self._for_s:
                    if self._stop.wait(self._gap):
                        return
                    conn.sendall(answer[sent:sent + 1])
                    sent += 1
                conn.sendall(answer[sent:])
        except OSError:  # the client closed its connection before the answer was sent
            self.gone.set()
        finally:
            with self._lock:
                self.open -= 1

    def close(self) -> None:
        self._stop.set()
        self._server.close()


def _probe_threads() -> list[threading.Thread]:
    return [thread for thread in threading.enumerate() if thread.name == "probos-doctor-probe"]


async def _until(condition: Callable[[], bool], within: float) -> bool:
    """Whether ``condition`` holds within ``within`` s, checked every 10 ms."""
    deadline = time.monotonic() + within
    while not condition():
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def _trickle_ctx(tmp_path: Path, provider: _Trickle) -> DoctorContext:
    cognitive = _cognitive(**{f"llm_base_url_{tier}": provider.base_url for tier in ps.TEXT_TIERS})
    path = _write(tmp_path / "trickle.yaml", {"cognitive": cognitive})
    return build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=path)


async def test_llm_check_names_the_wait_that_did_not_fit_when_a_tier_used_the_time_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    provider = _Provider(listing=_lists_after(clock, 45.0))

    result = await _llm(tmp_path, provider)

    # AD-1137 A-3 (review round 2): fast's own listing took the time, and the report said "the tiers before it" did.
    assert [request.method for request in provider.requests] == ["GET"]
    assert (result.outcome, result.message) == (WARN, "LLM tiers answer: none; not verified: fast, standard, deep")
    assert (
        f"fast, standard, deep: {_BASE}: not checked: less than the chat check's 30 s timeout is left of doctor's 60 s"
    ) in _shown(result)


async def test_llm_check_stops_waiting_for_a_probe_when_its_budget_runs_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    stall = _Stall(clock)
    provider = _Provider(listing=_lists_after(clock, 20.0), chat=stall)
    try:
        result = await _llm(tmp_path, provider)

        # AD-1137 A-3 (review round 2): the check waited for a started probe however long it ran; now until 60 s.
        assert stall.entered.is_set() and not stall.release.is_set()  # premise: the chat check is still running
        assert [(worker.is_alive(), worker.daemon) for worker in _probe_threads()] == [(True, True)]
        assert provider.calls() == [
            ("GET", "llm.example.test", "/v1/models"), ("POST", "llm.example.test", "/v1/chat/completions"),
        ]
        assert (result.outcome, result.message) == (WARN, "LLM tiers answer: none; not verified: fast, standard, deep")
        shown = _shown(result)
        assert (
            f"fast: {_BASE}: not verified: the chat check was still waiting for the provider when doctor's 60 s "
            "for provider checks ran out"
        ) in shown
        assert f"standard, deep: {_BASE}: not checked: less than the chat check's 30 s timeout is left" in shown
    finally:
        stall.release.set()
        for worker in _probe_threads():
            worker.join(10.0)
    assert not _probe_threads()


async def test_llm_check_returns_within_its_budget_while_a_provider_trickles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Trickle(gap=0.05, for_s=2.0)
    try:
        started = time.monotonic()
        listing = ps.probe_models(provider.base_url, _KEY, timeout=0.2)
        # Premise: httpx's timeout bounds each read, not the request, so setup's own probe outlasts it tenfold.
        assert (listing.outcome, time.monotonic() - started >= 1.9) == (ps.ProbeOutcome.OK, True)
        monkeypatch.setattr(llm_check, "LLM_CHECK_BUDGET_S", 0.4)
        monkeypatch.setattr(ps, "MODELS_PROBE_TIMEOUT_S", 0.2)
        cognitive = _cognitive(**{f"llm_base_url_{tier}": provider.base_url for tier in ps.TEXT_TIERS})
        path = _write(tmp_path / "trickle.yaml", {"cognitive": cognitive})
        ctx = build_context(home_dir=tmp_path / "home", data_dir=tmp_path / "data", config_path=path)

        started = time.monotonic()
        result = await llm_check._LLMCheck().run(ctx)
        waited = time.monotonic() - started

        # AD-1137 A-3 (review round 2): the check waited as long as the provider trickled; now it stops at its budget.
        assert waited < 1.4
        assert (result.outcome, result.message) == (WARN, "LLM tiers answer: none; not verified: fast, standard, deep")
        assert "not verified: the model listing was still waiting for the provider when doctor's 0.4 s" in _shown(result)
        assert provider.connections == 2  # the premise's request and doctor's one listing: none starts after the deadline
        # AD-1137 A-4 (review round 3): the abandoned listing kept its request open in a live daemon thread, so two
        # checks in one process had two requests open at once; now its client is closed at the deadline.
        assert await _until(lambda: provider.gone.is_set() and not _probe_threads(), within=1.5)
    finally:
        provider.close()
        for worker in _probe_threads():
            worker.join(10.0)
    assert not _probe_threads()


async def test_llm_check_leaves_no_request_to_log_after_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _Trickle(gap=0.05, for_s=0.8)
    caplog.set_level(logging.INFO, logger="httpx")
    try:
        ps.probe_models(provider.base_url, _KEY, timeout=5.0)
        # Premise: httpx logs each request it completes, and this provider completes one in about 0.8 s.
        assert sum(record.name == "httpx" for record in caplog.records) == 1
        caplog.clear()
        monkeypatch.setattr(llm_check, "LLM_CHECK_BUDGET_S", 0.4)
        monkeypatch.setattr(ps, "MODELS_PROBE_TIMEOUT_S", 0.2)

        result = await llm_check._LLMCheck().run(_trickle_ctx(tmp_path, provider))
        await asyncio.sleep(1.5)  # past the time the abandoned listing's answer would have been complete

        assert "not verified: the model listing was still waiting for the provider" in _shown(result)
        # AD-1137 A-4 (review round 3): the abandoned request finished later, and httpx logged it after doctor returned.
        assert [record.getMessage() for record in caplog.records if record.name == "httpx"] == []
    finally:
        provider.close()
        for worker in _probe_threads():
            worker.join(10.0)
    assert not _probe_threads()


async def test_a_cancelled_llm_check_stops_waiting_and_closes_its_request(tmp_path: Path) -> None:
    provider = _Trickle(gap=0.05, for_s=30.0)
    try:
        check = asyncio.create_task(llm_check._LLMCheck().run(_trickle_ctx(tmp_path, provider)))
        assert await _until(lambda: provider.open == 1, within=5.0)  # premise: the listing is being answered
        await asyncio.sleep(0.2)
        assert not check.done()

        check.cancel()
        with pytest.raises(asyncio.CancelledError):
            await check

        # AD-1137 A-4 (review round 3): check_tiers kept waiting on the provider, and asyncio.run's join of its thread
        # held Ctrl+C for up to the budget; now the wait stops, the request is closed, and no probe starts after it.
        assert await _until(lambda: provider.gone.is_set() and not _probe_threads(), within=2.0)
        assert provider.connections == 1
    finally:
        provider.close()
        for worker in _probe_threads():
            worker.join(10.0)
    assert not _probe_threads()


def test_check_tiers_starts_no_probe_once_it_is_stopped(tmp_path: Path) -> None:
    provider = _Provider()
    cognitive = load_config(_write(tmp_path / "checked.yaml", {"cognitive": _cognitive()})).cognitive
    assert [f.outcome for f in llm_check.check_tiers(cognitive, provider.transport)] == [OK, OK, OK]
    assert len(provider.requests) == 2  # premise: unstopped, the same call probes the provider
    stop = threading.Event()
    stop.set()  # the check was cancelled before check_tiers began

    findings = llm_check.check_tiers(cognitive, provider.transport, stop)

    # AD-1137 A-4: a stopped check reads as if its budget had run out, and starts no probe.
    assert [(f.outcome, "not checked" in f.detail) for f in findings] == [(WARN, True)] * 3
    assert len(provider.requests) == 2


def test_bounded_starts_no_probe_once_it_is_stopped() -> None:
    provider = _Provider()
    calls: list[str] = []

    def probe(abort: llm_check._Abort) -> ps.ProbeResult:
        calls.append("listing")
        return ps.probe_models(_BASE, _KEY, transport=provider.transport, on_client=abort)

    deadline = llm_check._clock() + llm_check.LLM_CHECK_BUDGET_S
    listing = llm_check._bounded(probe, deadline, threading.Event())
    assert listing is not None and listing.outcome is ps.ProbeOutcome.OK  # premise: unstopped, the probe runs
    assert (len(calls), len(provider.requests)) == (1, 1)
    stop = threading.Event()
    stop.set()  # the check was stopped after _probe_tier admitted this probe

    result = llm_check._bounded(probe, deadline, stop)
    started = _probe_threads()
    for worker in started:
        worker.join(10.0)  # a probe that started anyway has ended, so the counts below are final

    # AD-1137 A-5 (review round 4): an admitted probe was started after the stop, and could send its request.
    assert (result, len(calls), len(provider.requests)) == (None, 1, 1)
    assert started == []


def test_a_probe_handed_its_client_after_the_check_stopped_sends_nothing() -> None:
    provider = _Provider()
    listing = ps.probe_models(_BASE, _KEY, transport=provider.transport, on_client=llm_check._Abort(threading.Event()))
    assert (listing.outcome, len(provider.requests)) == (ps.ProbeOutcome.OK, 1)  # premise: unstopped, it sends
    stop = threading.Event()
    stop.set()  # the check is stopped after its probe started and before the probe built its client

    # AD-1137 A-5 (review round 4): the handoff saw only the wait's end, so a stopped check's probe sent its request.
    with pytest.raises(RuntimeError):
        ps.probe_models(_BASE, _KEY, transport=provider.transport, on_client=llm_check._Abort(stop))
    assert len(provider.requests) == 1


class _InlineThread:
    """Stands in for llm_check's ``threading.Thread``: runs its target in ``start()``, so the probe has ended first."""

    def __init__(self, *, target: Callable[[], None], **_kwargs: object) -> None:
        self._target = target

    def start(self) -> None:
        self._target()

    def is_alive(self) -> bool:
        return False


def test_bounded_uses_no_result_once_the_check_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_check, "threading", SimpleNamespace(Thread=_InlineThread, Event=threading.Event, Lock=threading.Lock),
    )
    deadline = llm_check._clock() + llm_check.LLM_CHECK_BUDGET_S
    stop = threading.Event()

    def closed(abort: llm_check._Abort) -> ps.ProbeResult:
        raise RuntimeError("Cannot send a request, as the client has been closed.")

    def stopped_then_closed(abort: llm_check._Abort) -> ps.ProbeResult:
        stop.set()  # the check is stopped while this probe runs, and its client is closed under it
        raise RuntimeError("Cannot send a request, as the client has been closed.")

    with pytest.raises(RuntimeError):  # premise: unstopped, _bounded raises its probe's error
        llm_check._bounded(closed, deadline, threading.Event())

    # AD-1137 A-5 (review round 4): a stopped probe's closed-client error was raised, so its tier read as FAIL.
    assert llm_check._bounded(stopped_then_closed, deadline, stop) is None


def test_a_check_stopped_between_admission_and_the_probe_sends_nothing(tmp_path: Path) -> None:
    tc = load_config(_write(tmp_path / "checked.yaml", {"cognitive": _cognitive()})).cognitive.tier_config("fast")
    deadline = llm_check._clock() + llm_check.LLM_CHECK_BUDGET_S
    provider = _Provider()
    unstopped = threading.Event()
    finding = llm_check._probe_tier(
        "fast", tc, {}, {}, provider.transport, lambda wait: True,
        lambda probe: llm_check._bounded(probe, deadline, unstopped),
    )
    assert (finding.outcome, len(provider.requests)) == (OK, 2)  # premise: unstopped, the listing and chat check go
    provider = _Provider()
    stop = threading.Event()

    def admits(wait: float) -> bool:
        stop.set()  # the check is stopped just after it admits the probe (the reviewer's handoff)
        return True

    finding = llm_check._probe_tier(
        "fast", tc, {}, {}, provider.transport, admits, lambda probe: llm_check._bounded(probe, deadline, stop),
    )

    # AD-1137 A-5 (review round 4): the admitted probe was started after the stop, and sent a request.
    assert (finding.outcome, len(provider.requests)) == (WARN, 0)


def test_a_probe_whose_wait_ended_before_it_had_its_client_sends_nothing() -> None:
    provider = _Provider()
    listing = ps.probe_models(_BASE, _KEY, transport=provider.transport, on_client=llm_check._Abort())
    assert (listing.outcome, len(provider.requests)) == (ps.ProbeOutcome.OK, 1)  # premise: a live one sends
    late = llm_check._Abort()
    late.close()  # the checking thread stopped waiting before the probe built its client

    # AD-1137 A-4: its client is closed as it is handed over, so no request reaches the provider after the wait.
    with pytest.raises(RuntimeError):
        ps.probe_models(_BASE, _KEY, transport=provider.transport, on_client=late)
    assert len(provider.requests) == 1


# ----- the Python and optional-extras checks -----


async def test_python_check_names_this_interpreter(tmp_path: Path) -> None:
    result = await python_check._PythonCheck().run(_bare(tmp_path))

    assert result.outcome is OK
    assert result.message == f"Python {'.'.join(map(str, sys.version_info[:3]))} ({sys.executable})"


@pytest.mark.parametrize(
    ("version", "outcome"), [((3, 11, 9), FAIL), ((3, 12, 0), OK), ((4, 0, 0), OK)], ids=["older", "minimum", "newer"],
)
async def test_python_check_compares_against_the_minimum(
    version: tuple[int, ...], outcome: CheckOutcome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(python_check, "_running_version", lambda: version)

    result = await python_check._PythonCheck().run(_bare(tmp_path))

    assert result.outcome is outcome
    if outcome is FAIL:
        assert result.message == "Python 3.11.9 is older than ProbOS's minimum, 3.12"
        assert "Install Python 3.12 or newer" in result.remediation


def test_python_minimum_is_pyproject_requires_python() -> None:
    project = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["requires-python"] == ">=" + ".".join(map(str, python_check.MINIMUM_PYTHON))


class _Metadata:
    def __init__(self, extras: list[str]) -> None:
        self._extras = extras

    def get_all(self, name: str, failobj: object = None) -> object:
        return list(self._extras) if name == "Provides-Extra" else failobj


class _Distribution:
    """The parts of ``importlib.metadata.Distribution`` the extras check reads."""

    def __init__(self, extras: list[str], requires: list[str], direct_url: str | None = None) -> None:
        self.metadata = _Metadata(extras)
        self.requires = requires
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        return self._direct_url if filename == "direct_url.json" else None


def test_extras_status_reads_declared_extras_and_their_requirements() -> None:
    distribution = _Distribution(["dev", "alpha", "Beta_X"], [
        'pytest>=8.0; extra == "dev"',
        f'{_ABSENT}>=1.0; extra == "alpha"',
        "pytest ; extra == 'beta-x'",
        "httpx>=0.27",  # a core requirement, not an extra's
    ])

    assert extras_check.extras_status(distribution) == {"alpha": [_ABSENT], "beta-x": []}


@pytest.mark.parametrize(
    ("direct_url", "hint"),
    [
        ('{"url": "file:///src", "dir_info": {"editable": true}}', 'pip install -e ".[<extra>]", run in the ProbOS checkout'),
        ('{"url": "file:///src", "dir_info": {}}', 'pip install ".[<extra>]", run in the ProbOS checkout'),
        (None, 'pip install "probos[<extra>]"'),
        ("not json", 'pip install "probos[<extra>]"'),
    ],
    ids=["editable-checkout", "checkout", "index", "unreadable"],
)
def test_install_hint_follows_how_probos_was_installed(direct_url: str | None, hint: str) -> None:
    assert extras_check.install_hint(_Distribution([], [], direct_url)) == hint


@pytest.mark.parametrize(
    ("requires", "message"),
    [
        (
            [f'{_ABSENT}; extra == "alpha"', 'pytest; extra == "beta"'],
            'Optional extras installed: beta; not installed: alpha (add one with pip install -e ".[<extra>]", '
            "run in the ProbOS checkout)",
        ),
        (['pytest; extra == "alpha"', 'pytest; extra == "beta"'], "Optional extras: all installed (alpha, beta)"),
    ],
    ids=["one-missing", "all-installed"],
)
async def test_extras_check_lists_extras_and_never_fails_for_a_missing_one(
    requires: list[str], message: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_url = '{"url": "file:///src", "dir_info": {"editable": true}}'
    monkeypatch.setattr(extras_check, "_distribution", lambda: _Distribution(["alpha", "beta"], requires, direct_url))

    result = await extras_check._ExtrasCheck().run(_bare(tmp_path))

    assert (result.outcome, result.message) == (OK, message)


async def test_extras_check_warns_without_package_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> metadata.Distribution:
        raise metadata.PackageNotFoundError("probos")

    monkeypatch.setattr(extras_check, "_distribution", missing)

    result = await extras_check._ExtrasCheck().run(_bare(tmp_path))

    assert result.outcome is WARN
    assert result.message == "Optional extras: not checked (ProbOS's package metadata was not found)"


async def test_extras_check_never_fails_on_this_install(tmp_path: Path) -> None:
    result = await extras_check._ExtrasCheck().run(_bare(tmp_path))

    assert result.outcome in (OK, WARN)


# ----- rendering -----


class _Says:
    name = "says"

    def __init__(self, outcome: CheckOutcome, message: str, remediation: str) -> None:
        self._result = CheckResult(outcome, message, remediation)

    async def run(self, ctx: DoctorContext) -> CheckResult:
        return self._result


@pytest.mark.parametrize("outcome", [OK, WARN, FAIL], ids=["ok", "warn", "fail"])
async def test_doctor_prints_check_text_literally_and_indents_each_fix_line(
    outcome: CheckOutcome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = "[/dim]BROKEN [bold]x[/bold]"
    check = _Says(outcome, f"message {hostile}", f"first {hostile}\nsecond line")
    monkeypatch.setattr(doctor_registry, "_CHECKS", [check])
    monkeypatch.setattr(doctor_registry, "_NAMES", {check.name})
    buffer = StringIO()

    await run_doctor(argparse.Namespace(), Console(file=buffer, width=200), ctx=_bare(tmp_path))

    # Printed literally: an unescaped "[/dim]" would raise MarkupError instead.
    out = buffer.getvalue()
    assert f"message {hostile}" in out
    assert (f"    first {hostile}\n" in out, "    second line\n" in out) == ((outcome is not OK),) * 2


@pytest.mark.parametrize(
    ("outcomes", "closing", "code"),
    [
        ((OK,), "All checks passed.", 0),
        ((OK, WARN), "No check failed; 1 warning(s) above.", 0),
        ((WARN, OK, WARN), "No check failed; 2 warning(s) above.", 0),
        ((FAIL, WARN), "1 issue(s) found.", 1),
    ],
    ids=["all-ok", "one-warning", "two-warnings", "failure-and-warning"],
)
async def test_doctor_says_all_checks_passed_only_when_none_failed_or_warned(
    outcomes: tuple[CheckOutcome, ...], closing: str, code: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = [_Says(outcome, f"check {index}", "") for index, outcome in enumerate(outcomes)]
    monkeypatch.setattr(doctor_registry, "_CHECKS", checks)
    monkeypatch.setattr(doctor_registry, "_NAMES", {check.name for check in checks})
    buffer = StringIO()

    exit_code = await run_doctor(argparse.Namespace(), Console(file=buffer, width=200), ctx=_bare(tmp_path))

    lines = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
    assert sum("\u26a0" in line for line in lines) == outcomes.count(WARN)  # premise: each warning was printed
    # AD-1137 A-3 (review round 2): "All checks passed." followed printed warnings; a WARN still exits 0.
    assert (exit_code, lines[-1]) == (code, closing)


async def test_doctor_does_not_say_all_checks_passed_when_the_budget_leaves_a_tier_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    monkeypatch.setattr(llm_check, "_clock", clock)
    provider = _Provider(listing=_listing("model-a", "model-b", "model-c"), chat=_answers_after(clock, 29.0))
    cognitive = _cognitive(llm_model_fast="model-a", llm_model_standard="model-b", llm_model_deep="model-c")
    check = llm_check._LLMCheck()
    monkeypatch.setattr(doctor_registry, "_CHECKS", [check])
    monkeypatch.setattr(doctor_registry, "_NAMES", {check.name})
    buffer = StringIO()

    exit_code = await run_doctor(argparse.Namespace(), Console(file=buffer, width=200), ctx=_ctx(tmp_path, provider, cognitive))

    lines = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
    assert "\u26a0 LLM tiers answer: fast, standard; not verified: deep" in lines  # premise: the budget left deep
    assert (exit_code, lines[-1]) == (0, "No check failed; 1 warning(s) above.")


# ----- the setup hint and the boot banner -----


def test_setup_names_doctor_when_its_file_is_the_one_probos_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(_KEY_ENV, _KEY)
    repo_default = tmp_path / "repo" / "config" / "system.yaml"
    flags = ("--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV, "--model", _MODEL, "--yes")

    assert main_mod._cmd_setup(_setup_args(*flags, "--config", str(repo_default)), transport=_Provider().transport) == 0

    # Before AD-1137 setup named doctor only for ~/.probos/config.yaml, the one file doctor read.
    assert "Run probos doctor to check the rest of the installation." in " ".join(capsys.readouterr().out.split())


class _Connectivity:
    """Stands in for OpenAICompatibleClient at boot: a fixed check_connectivity() answer."""

    def __init__(self, answer: dict[str, bool]) -> None:
        self._answer = answer

    async def check_connectivity(self) -> dict[str, bool]:
        return dict(self._answer)

    async def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("overrides", "warning"),
    [({}, None), ({"llm_base_url_vision": "https://vision.example.test/v1", "llm_model_vision": "vision-model"}, "vision")],
    ids=["unconfigured", "vision-configured"],
)
async def test_boot_banner_names_only_configured_tiers_as_unreachable(
    overrides: dict, warning: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(_write(tmp_path / "boot.yaml", {"cognitive": _cognitive(**overrides)}))
    answer = {tier: tier in (*ps.TEXT_TIERS, "compute_use", "image_gen") for tier in (*ps.TEXT_TIERS, *ps.OPTIONAL_TIERS)}
    monkeypatch.setattr(main_mod, "OpenAICompatibleClient", lambda **kwargs: _Connectivity(answer))
    buffer = StringIO()

    await main_mod._create_llm_client(config, Console(file=buffer, width=200))

    # check_connectivity() reports an unconfigured vision tier False without probing it (AD-732).
    out = buffer.getvalue()
    if warning is None:
        assert "tier(s) unreachable" not in out
    else:
        assert f"Warning: {warning} tier(s) unreachable" in out


async def test_boot_banner_shows_urls_and_models_as_doctor_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-ad1137-banner-path-5K2P"
    base = f"https://ad1137user:ad1137pass@llm.example.test/private/{secret}/v1"
    cognitive = _cognitive(
        **{f"llm_base_url_{t}": base for t in ps.TEXT_TIERS},
        llm_model_fast="model-[bold]x",
        llm_base_url_vision=f"https://vision.example.test/{secret}/v1", llm_model_vision="vision-model",
    )
    config = load_config(_write(tmp_path / "boot.yaml", {"cognitive": cognitive}))
    answer = {tier: tier in ps.TEXT_TIERS for tier in (*ps.TEXT_TIERS, *ps.OPTIONAL_TIERS)}
    monkeypatch.setattr(main_mod, "OpenAICompatibleClient", lambda **kwargs: _Connectivity(answer))
    buffer = StringIO()

    await main_mod._create_llm_client(config, Console(file=buffer, width=200))

    # AD-1137 A-2 (contract F-5): the banner printed tc['base_url'] raw, with its userinfo and path, into markup.
    out = buffer.getvalue()
    assert "LLM fast: model-[bold]x at https://llm.example.test/<redacted>/<redacted>/v1" in out
    assert "LLM vision: https://vision.example.test/<redacted>/v1 unreachable" in out
    assert not any(text in out for text in (secret, "ad1137user", "ad1137pass", "private"))


_KEY_CASES = [
    (
        ps.TEXT_TIERS, "https://standin.invalid/compatible-mode/v1", "compatible-mode", _MODEL,
        "LLM fast: model-x at https://standin.invalid/<redacted>/v1",
        "model 'model-x' at https://standin.invalid/<redacted>/v1",
    ),
    (
        ps.TEXT_TIERS, "https://standin.invalid/v1", "v1", _MODEL,
        "LLM fast: model-x at https://standin.invalid/<redacted>", "model 'model-x' at https://standin.invalid/<redacted>",
    ),
    (
        ps.TEXT_TIERS, "https://standin.invalid/v1", "sk-ad1137-a3-model-key", "sk-ad1137-a3-model-key",
        "LLM fast: <redacted> at https://standin.invalid/v1", "model '<redacted>' at https://standin.invalid/v1",
    ),
    (
        ("vision",), "https://sk-ad1137-a3-vision.example.test/v1", "sk-ad1137-a3-vision", "vision-model",
        "LLM vision: https://<redacted>.example.test/v1 unreachable",
        "vision: model 'vision-model' at https://<redacted>.example.test/v1",
    ),
]


@pytest.mark.parametrize(
    ("tiers", "base_url", "key", "model", "banner", "doctor"), _KEY_CASES,
    ids=["path-word", "version", "model", "optional-tier"],
)
async def test_boot_banner_withholds_every_configured_key_as_doctor_does(
    tiers: tuple[str, ...], base_url: str, key: str, model: str, banner: str, doctor: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ps.validate_key_transport(base_url, key, allow_insecure_http=False)  # premise: setup accepts the key itself
    assert ps.carries_key(f"{model} at {ps.shown_base_url(base_url)}", key)  # premise: A-2's display shows it
    cognitive = _cognitive(**{
        name: value
        for tier in tiers
        for name, value in ((f"llm_base_url_{tier}", base_url), (f"llm_api_key_{tier}", key), (f"llm_model_{tier}", model))
    })
    config = load_config(_write(tmp_path / "boot.yaml", {"cognitive": cognitive}))
    answer = {tier: tier in ps.TEXT_TIERS for tier in (*ps.TEXT_TIERS, *ps.OPTIONAL_TIERS)}
    monkeypatch.setattr(main_mod, "OpenAICompatibleClient", lambda **kwargs: _Connectivity(answer))
    buffer = StringIO()

    await main_mod._create_llm_client(config, Console(file=buffer, width=200))
    checked = await _llm(tmp_path, _Provider(listing=_listing(_MODEL, "vision-model")), cognitive)

    # AD-1137 A-3 (review round 2): a key the URL rule keeps, or one in a model name, was printed by the banner.
    out = buffer.getvalue()
    assert banner in out
    assert doctor in checked.message
    assert not ps.carries_key(out, key) and not ps.carries_key(_shown(checked), key)


def test_the_doctor_package_is_imported_only_by_the_cli() -> None:
    package = Path(main_mod.__file__).resolve().parent
    importers: set[str] = set()
    scanned = 0
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        if relative.startswith("doctor/"):
            continue
        scanned += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
            else:
                continue
            if any(name == "probos.doctor" or name.startswith("probos.doctor.") for name in names):
                importers.add(relative)

    assert scanned > 100  # premise: the walk saw the package, not an empty directory
    # AD-1137: the doctor now reaches provider_setup, which must stay in the operator's own CLI process.
    assert importers == {"__main__.py"}
