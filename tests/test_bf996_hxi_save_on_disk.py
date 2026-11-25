"""BF-996 (#1414 Batch A, slice A3): an HXI settings save merges its patch onto the config file on disk.

Before, POST /api/config wrote a dump of the configuration the process booted with, so an edit made since
boot (probos setup, a hand edit, an earlier save awaiting restart) was reverted, and a value the
environment set was written into the file. These tests drive the real router over a real file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi.testclient import TestClient

import probos.config as config_mod
import probos.routers.config as config_router
from probos.api import create_app
from probos.config import CognitiveConfig, SystemConfig, load_config

_ENV_URL = "http://env-only.example.test/v1"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)


def _client(path: Path, config: SystemConfig | None = None) -> tuple[TestClient, MagicMock]:
    # The tests/test_ad741_config_api.py pattern: a real SystemConfig and a real config_path behind a
    # MagicMock runtime; _data_dir is real so create_app makes no directory in the repo root (BF-326).
    runtime = MagicMock()
    runtime.config = config if config is not None else SystemConfig()
    runtime.config_path = str(path)
    runtime._data_dir = path.parent / "data"
    runtime._start_time = 0.0
    return TestClient(create_app(runtime)), runtime


def _save(client: TestClient, patch: dict[str, Any]) -> Any:
    csrf = client.get("/api/config").json()["csrf_token"]
    return client.post("/api/config", json={"patch": patch}, headers={"X-Probos-CSRF": csrf})


def _on_disk(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _empty_file(tmp_path: Path) -> Path:
    path = tmp_path / "system.yaml"
    path.write_text("{}\n", encoding="utf-8")
    return path


def test_a_save_keeps_an_edit_made_to_the_file_after_boot(tmp_path: Path) -> None:
    path = _empty_file(tmp_path)
    client, runtime = _client(path)
    path.write_text("cognitive:\n  llm_model_fast: edited-after-boot\n", encoding="utf-8")  # probos setup, or by hand
    assert runtime.config.cognitive.llm_model_fast != "edited-after-boot"  # premise: booted without it

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 200, response.text
    assert _on_disk(path) == {"cognitive": {"llm_model_fast": "edited-after-boot"}, "system": {"log_level": "DEBUG"}}


def test_two_saves_before_a_restart_keep_both_changes(tmp_path: Path) -> None:
    path = _empty_file(tmp_path)
    client, runtime = _client(path)

    first = _save(client, {"system": {"log_level": "DEBUG"}})
    second = _save(client, {"system": {"name": "Enterprise"}})

    assert (first.status_code, first.json()["restart_required"], second.status_code) == (200, True, 200)
    assert runtime.config.system.log_level == "INFO"  # premise: the first change is not live yet
    assert _on_disk(path) == {"system": {"log_level": "DEBUG", "name": "Enterprise"}}


def test_a_save_writes_no_value_the_environment_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROBOS_LLM_URL", _ENV_URL)
    path = _empty_file(tmp_path)
    # SystemConfig() copies the CognitiveConfig built when probos.config was imported, and PROBOS_LLM_URL is read each time a
    # CognitiveConfig is built: the config of a process started with the variable set is built here, after setenv.
    client, runtime = _client(path, SystemConfig(cognitive=CognitiveConfig()))
    assert runtime.config.cognitive.llm_base_url == _ENV_URL  # premise: the booted config holds the env value

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _ENV_URL not in path.read_text(encoding="utf-8")
    assert _on_disk(path) == {"system": {"log_level": "DEBUG"}}


def test_a_save_onto_a_missing_file_writes_only_the_patch(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    client, _ = _client(path)
    assert not path.exists()  # premise

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path) == {"system": {"log_level": "DEBUG"}}
    assert load_config(path).system.log_level == "DEBUG"


def test_a_section_whose_values_are_all_commented_out_does_not_block_a_save(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text("memory:\n  # max_episodes: 10\nsystem:\n  name: Kept\n", encoding="utf-8")
    client, _ = _client(path)
    assert load_config(path).system.name == "Kept"  # premise: load_config drops the empty section

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path) == {"system": {"name": "Kept", "log_level": "DEBUG"}}


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"system: [\n", "not valid YAML"),
        (b"- a\n- b\n", "not a mapping of config sections"),
        (b"system:\n  name: \xff\n", "not valid UTF-8 text"),
        # PyYAML raises a ValueError for the date and a RecursionError for the nesting, not a YAMLError.
        (b"system:\n  name: 2023-13-45\n", "not valid YAML"),
        (b"system: " + b"[" * 5000 + b"]" * 5000 + b"\n", "not valid YAML"),
    ],
    ids=["yaml", "list", "utf-8", "impossible-date", "deep-nesting"],
)
def test_an_unusable_file_is_refused_and_left_as_it_is(data: bytes, reason: str, tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (409, {"error": "config_unreadable", "reason": reason})
    assert path.read_bytes() == data
    assert runtime.config.system.log_level == "INFO"


def test_a_file_that_does_not_validate_is_refused_without_quoting_it(tmp_path: Path) -> None:
    data = b"memory:\n  max_episodes: sk-bf996-file-value\n"
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, _ = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "config_invalid"
    assert [error["loc"] for error in body["errors"]] == [["memory", "max_episodes"]]
    assert all(set(error) == {"loc", "type"} for error in body["errors"])
    assert "sk-bf996-file-value" not in response.text
    assert path.read_bytes() == data


def test_a_secret_already_in_the_file_survives_a_save(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.write_text("cloud_pickers:\n  google_drive:\n    client_secret: disk-secret-bf996\n", encoding="utf-8")
    client, runtime = _client(path)
    assert runtime.config.cloud_pickers.google_drive.client_secret != "disk-secret-bf996"  # premise

    assert _save(client, {"system": {"log_level": "DEBUG"}}).status_code == 200

    assert _on_disk(path)["cloud_pickers"]["google_drive"]["client_secret"] == "disk-secret-bf996"


def test_drop_null_sections_drops_only_none_and_load_config_uses_it(tmp_path: Path) -> None:
    drop = config_mod.drop_null_sections

    assert drop({"a": None, "b": {}, "c": 0, "d": ""}) == {"b": {}, "c": 0, "d": ""}
    path = tmp_path / "system.yaml"
    path.write_text("memory:\nsystem:\n  name: Kept\n", encoding="utf-8")
    assert load_config(path).system.name == "Kept"


@pytest.mark.parametrize(
    ("data", "refusal"),
    [
        # int() of a hex string has no digit limit, str() of the result does (3,600 hex digits = 4,335 decimal).
        (b"x: 0x" + b"f" * 3600 + b"\n", ValueError),
        # The composer recurses two frames a level, the representer three: 360 levels load but do not dump.
        (b"x: " + b"[" * 360 + b"]" * 360 + b"\n", RecursionError),
    ],
    ids=["hex-int", "nesting"],
)
def test_a_file_holding_a_value_the_dump_refuses_is_refused_and_left_as_it_is(
    data: bytes, refusal: type[BaseException], tmp_path: Path,
) -> None:
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    assert load_config(path).system.log_level == "INFO"  # premise: the file boots (an unknown section is ignored)
    with pytest.raises(refusal):  # premise: PyYAML loads the value but cannot dump it
        yaml.safe_dump(yaml.safe_load(data))
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_unreadable", "reason": "holds a value that cannot be written back"},
    )
    assert path.read_bytes() == data
    assert list(tmp_path.glob("*.tmp")) == []  # the dump runs before a temporary file is made
    assert runtime.config.system.log_level == "INFO"


def test_a_file_a_validator_cannot_check_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    data = b"dm_agentic:\n  budget_awareness_thresholds: [" + b"9" * 400 + b"]\n"
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    # premise: math.isfinite on a 400-digit int raises OverflowError, which pydantic does not wrap, so there is no loc;
    # load_config raises the same at boot (#1820).
    with pytest.raises(OverflowError):
        SystemConfig.model_validate(yaml.safe_load(data))
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_invalid", "errors": [{"loc": [], "type": "OverflowError"}]},
    )
    assert path.read_bytes() == data
    assert runtime.config.system.log_level == "INFO"


@pytest.mark.parametrize(
    ("data", "error"),
    [
        (b"x: !!bool not-a-boolean\n", KeyError),
        (b'x: !!int ""\n', IndexError),
        (b'x: !!float ""\n', IndexError),
        (b"x: !!timestamp not-a-date\n", AttributeError),
        (b"x: " + b"1:" * 199 + b"1.5\n", OverflowError),  # 200 sexagesimal segments: 60**199 is past a float
    ],
    ids=["bool", "int", "float", "timestamp", "sexagesimal"],
)
def test_a_file_pyyaml_cannot_construct_is_refused_and_left_as_it_is(
    data: bytes, error: type[BaseException], tmp_path: Path,
) -> None:
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    with pytest.raises(error):  # premise: PyYAML's constructor raises this, not a YAMLError
        yaml.safe_load(data)
    with pytest.raises(error):  # premise: the file does not boot either
        load_config(path)
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (409, {"error": "config_unreadable", "reason": "not valid YAML"})
    assert path.read_bytes() == data
    assert runtime.config.system.log_level == "INFO"


def test_a_write_the_os_refuses_answers_write_failed_and_leaves_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _empty_file(tmp_path)
    client, runtime = _client(path)

    def refuse(cfg_path: str, data: dict[str, Any]) -> None:
        raise PermissionError(13, "Permission denied", cfg_path)

    monkeypatch.setattr(config_router, "_write_yaml_atomic", refuse)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    # AD-741's answer, kept: only the dump's refusals are 409; an OS refusal of the write is 500 write_failed.
    assert (response.status_code, response.json()["error"]) == (500, "write_failed")
    assert path.read_text(encoding="utf-8") == "{}\n"
    assert runtime.config.system.log_level == "INFO"


@pytest.mark.parametrize(
    "error",
    [yaml.representer.RepresenterError("cannot represent an object"), TypeError("not serializable")],
    ids=["representer-error", "type-error"],
)
def test_a_dump_that_fails_with_any_other_exception_answers_409_and_leaves_the_file(
    error: Exception, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No loadable value is known to make the dump raise anything but ValueError or RecursionError, so the fault is injected
    # at the dump itself, the one step whose failures the router answers 409.
    path = _empty_file(tmp_path)
    client, runtime = _client(path)

    def fail(data: Any, **kwargs: Any) -> str:
        raise error

    monkeypatch.setattr(config_router.yaml, "safe_dump", fail)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_unreadable", "reason": "holds a value that cannot be written back"},
    )
    assert path.read_text(encoding="utf-8") == "{}\n"
    assert list(tmp_path.glob("*.tmp")) == []  # the dump runs before a temporary file is made
    assert runtime.config.system.log_level == "INFO"


@pytest.mark.parametrize("error", [TypeError("not a path"), MemoryError()], ids=["type-error", "memory-error"])
def test_a_failure_after_the_dump_is_not_answered_as_an_unwritable_value(
    error: BaseException, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Round 3 answered any exception from the write step 409 "cannot be written back" (A3-R3-F2). Only the dump's failures
    # are that; a later step's exception that is not an OSError reaches the server's own 500, as on the base.
    path = _empty_file(tmp_path)
    _, runtime = _client(path)
    client = TestClient(create_app(runtime), raise_server_exceptions=False)

    def fail(src: Any, dst: Any) -> None:
        raise error

    monkeypatch.setattr(config_router.os, "replace", fail)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 500
    assert "config_unreadable" not in response.text
    assert path.read_text(encoding="utf-8") == "{}\n"
    assert list(tmp_path.glob("*.tmp")) == []  # the temporary file is removed when the replace fails
    assert runtime.config.system.log_level == "INFO"


def test_a_config_path_the_os_will_not_stat_is_refused_and_left_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "system:\n  name: Kept\n"
    path = tmp_path / "system.yaml"
    path.write_text(text, encoding="utf-8")
    client, runtime = _client(path)
    # Injected: a config path under a directory the process cannot search. Path.exists() ignores ENOENT, ENOTDIR,
    # EBADF and ELOOP only, so the EACCES from stat reaches its caller.
    real_exists = Path.exists

    def exists(self: Path, *args: Any, **kwargs: Any) -> bool:
        if self == path:
            raise PermissionError(13, "Permission denied")
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    with pytest.raises(PermissionError):  # premise: the injected denial reaches Path.exists' caller
        path.exists()

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert (response.status_code, response.json()) == (
        409, {"error": "config_unreadable", "reason": "unreadable (PermissionError)"},
    )
    assert path.read_text(encoding="utf-8") == text
    assert runtime.config.system.log_level == "INFO"


def test_a_directory_at_the_config_path_is_refused_and_left_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "system.yaml"
    path.mkdir()
    client, runtime = _client(path)

    response = _save(client, {"system": {"log_level": "DEBUG"}})

    assert response.status_code == 409, response.text
    assert response.json()["error"] == "config_unreadable"
    # A real OS read failure: Windows raises PermissionError for a directory, POSIX IsADirectoryError.
    assert response.json()["reason"] in {"unreadable (PermissionError)", "unreadable (IsADirectoryError)"}
    assert path.is_dir()
    assert runtime.config.system.log_level == "INFO"


def test_a_secret_path_is_refused_before_the_file_is_read(tmp_path: Path) -> None:
    data = b"system: [\n"  # unreadable: a guard that ran after the read would answer 409 config_unreadable
    path = tmp_path / "system.yaml"
    path.write_bytes(data)
    client, _ = _client(path)

    response = _save(client, {"cloud_pickers": {"google_drive": {"client_secret": "new-secret"}}})

    assert (response.status_code, response.json()) == (
        400, {"error": "secret_field_readonly", "blocked": ["cloud_pickers.google_drive.client_secret"]},
    )
    assert path.read_bytes() == data
