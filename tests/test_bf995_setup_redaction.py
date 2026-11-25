"""BF-995 (#1414 Batch A, slice A2): setup's messages show no API key, its own or one the file already holds.

Item 6: the provider excerpt is cut with U+2026, which no form of a key holds, so _result's second
redaction cannot take it past 200 characters. Item 7: wherever setup prints text read from the existing
config, it redacts every cognitive.llm_api_key* value that file holds, as well as the key it is configuring.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import pytest
import yaml

import probos.__main__ as main_mod
from probos import provider_setup as ps

_BASE = "https://llm.example.test/v1"
_CHOSEN = "sk-bf995-chosen-key-4Q7Z"
_OTHER = "sk-bf995-other-secret-9X2W"
_KEY_ENV = "PROBOS_TEST_BF995_KEY"
_ENV = ("PROBOS_LLM_URL", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_MARKER = "\u2026"


def _no_detection(console: object) -> dict[str, str]:
    raise AssertionError("setup probed for local providers, which this test does not script")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_mod, "_probos_home", lambda: tmp_path / "home")
    monkeypatch.setattr(main_mod, "_repo_default_config_path", lambda: tmp_path / "repo" / "config" / "system.yaml")
    monkeypatch.setattr(main_mod, "_detect_llm_providers", _no_detection)
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv(_KEY_ENV, _CHOSEN)


def _setup(*extra: str, yes: bool = True) -> int:
    parser = argparse.ArgumentParser(prog="probos")
    main_mod._add_setup_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args([
        "setup", "--provider", "custom", "--base-url", _BASE, "--api-key-env", _KEY_ENV,
        "--model", "model-x", "--skip-validation", *(("--yes",) if yes else ()), *extra,
    ])
    return main_mod._cmd_setup(args)


def _existing(tmp_path: Path, *cognitive_lines: str) -> Path:
    config = tmp_path / "home" / "config.yaml"
    config.parent.mkdir(parents=True)
    lines = ["cognitive:", "  llm_base_url: http://127.0.0.1:8080/v1", *cognitive_lines]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config


def _printed(capsys: pytest.CaptureFixture[str]) -> str:
    return " ".join(capsys.readouterr().out.split())


def _excerpt_of(api_key: str, body: str) -> str:
    transport = httpx.MockTransport(lambda request: httpx.Response(400, text=body))
    result = ps.probe_chat(_BASE, api_key, "model-x", transport=transport)
    assert result.outcome is ps.ProbeOutcome.REQUEST_REJECTED  # premise: the 400 branch, which shows an excerpt
    return result.message.split("(HTTP 400): ", 1)[1]


def test_the_excerpt_for_a_key_of_dots_stays_at_200_characters() -> None:
    detail = _excerpt_of(".", "." * 300)

    assert (len(detail), detail[-1]) == (200, _MARKER)  # 227 before #1414: _result redacted the "..."
    assert "." not in detail


def test_the_cut_completes_no_key() -> None:
    detail = _excerpt_of("ab.", "x" * 195 + "ab" + "y" * 100)

    assert (len(detail), detail[-1]) == (200, _MARKER)  # before #1414 the cut wrote "ab..." and so the key
    assert "<redacted>" not in detail


@pytest.mark.parametrize("field", ["llm_api_key", "llm_api_key_vision", "llm_api_key_verifier"])
def test_a_retained_model_holding_a_key_from_the_file_is_shown_redacted(
    field: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    config = _existing(tmp_path, f"  {field}: {_OTHER}", f"  llm_model_vision: {_OTHER}")

    assert _setup() == 0

    out = _printed(capsys)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]["llm_model_vision"] == _OTHER  # premise
    assert "vision (model '<redacted>') uses it" in out  # the B7 note names the tier; its model is the file's key
    assert _OTHER not in out


def _refuse_quoting_the_file(*args: object, **kwargs: object) -> object:
    raise ps.ConfigEditRefused(f"the setting quotes {_OTHER}")


@pytest.mark.parametrize(
    ("seam", "extra", "code"),
    [
        ("optional_tier_endpoints", (), 4),
        ("apply_managed_values", (), 4),
        ("apply_managed_values", ("--force",), 0),
    ],
    ids=["reading-the-file", "editing-the-file", "force-rewrite-note"],
)
def test_a_refusal_quoting_the_file_prints_no_key_from_it(
    seam: str, extra: tuple[str, ...], code: int,
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _existing(tmp_path, f"  llm_api_key: {_OTHER}")
    monkeypatch.setattr(ps, seam, _refuse_quoting_the_file)

    assert _setup(*extra) == code

    out = _printed(capsys)
    assert "the setting quotes <redacted>" in out  # premise: the refusal was printed
    assert _OTHER not in out


def test_a_write_failure_quoting_the_file_prints_no_key_from_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _existing(tmp_path, f"  llm_api_key: {_OTHER}")

    def fail(*args: object, **kwargs: object) -> object:
        raise OSError(f"no space left beside {_OTHER}")

    monkeypatch.setattr(ps, "write_config_atomic", fail)

    assert _setup() == 4

    out = _printed(capsys)
    assert "no space left beside <redacted>" in out  # premise: the failure was printed
    assert _OTHER not in out


def test_redact_keys_hides_a_key_with_no_utf8_form() -> None:
    lone = "\ud800"
    with pytest.raises(UnicodeEncodeError):
        lone.encode("utf-8")  # premise: no UTF-8 form, so no percent-encoded or base64 form either

    assert ps.redact_keys(f"model {lone} here", [lone, _OTHER]) == "model <redacted> here"


@pytest.mark.parametrize("yes", [True, False], ids=["report", "confirm-and-report"])
def test_a_key_with_no_utf8_form_is_hidden_and_setup_completes(
    yes: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A YAML escape gives the vision key and the retained model a lone surrogate; config_text_api_keys keeps it.
    config = _existing(tmp_path, '  llm_api_key_vision: "\\uD800"', '  llm_model_vision: "\\uD800"')
    asked: list[str] = []

    def confirm(prompt: str, *args: object, **kwargs: object) -> bool:
        asked.append(prompt)
        return True

    monkeypatch.setattr("rich.prompt.Confirm.ask", confirm)

    assert _setup(yes=yes) == 0  # before the review, setup raised UnicodeEncodeError after replacing the file

    out = _printed(capsys)
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["cognitive"]["llm_model_vision"] == "\ud800"  # premise
    assert len(asked) == (0 if yes else 1)  # premise: only the final question, and only without --yes
    assert out.count("vision (model '<redacted>') uses it") == (1 if yes else 2)


_FILE_SECRET = "sk-bf995-file-secret-N9Q4"


@pytest.mark.parametrize(
    ("key", "key_yaml", "model_yaml", "note"),
    [
        (f"'{_FILE_SECRET}'", f"\"'{_FILE_SECRET}'\"", _FILE_SECRET, "model <redacted>"),
        ("sk-bf995-file\\\\N9Q4", "sk-bf995-file\\\\N9Q4", "sk-bf995-file\\N9Q4", "model '<redacted>'"),
        ("sk-bf995-file\\N9Q4", "sk-bf995-file\\N9Q4", "sk-bf995-file\\N9Q4", "model '<redacted>'"),
    ],
    ids=["quoted", "doubled-backslash", "raw-backslash"],
)
def test_a_shown_model_never_completes_a_file_key(
    key: str, key_yaml: str, model_yaml: str, note: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # quoted and doubled-backslash: the model's repr adds the quotes or the second backslash and so forms the key;
    # raw-backslash: only the raw redaction finds the key, since repr doubles its backslash.
    config = _existing(tmp_path, f"  llm_api_key_vision: {key_yaml}", f"  llm_model_vision: {model_yaml}")
    assert ps.config_text_api_keys(config.read_text(encoding="utf-8")) == [key]  # premise: the file holds the key

    assert _setup() == 0

    out = _printed(capsys)
    assert f"vision ({note}) uses it" in out
    assert key not in out
