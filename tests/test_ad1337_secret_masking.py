"""AD-1337 S1 (#1560): the secret masker and the credential store's value read.

Proves, with a real CredentialStore on a tmp file, a real SecretRegistry, an EnvSecretSource over a dict the test
builds, and real ToolResult values:
- N1-N8: the forms of a value, the floor, nested and overlapping occurrences, multi-line values, idempotence;
- N9-N10: the same objects come back when nothing matches, with no values and with values;
- N11-N16: mask_result over strings, containers, other types, subclasses and its bounds; bad arguments;
- N17-N19: a failing pass withholds the output; labels; which source names a shared value;
- N20-N21: the registry;
- N22-N25: the environment source decides by name only, and its rule only narrows BF-890's;
- N26-N31: masked_credential_values: each source, no CLI and no access row, rotation, its only caller;
- N32-N37: padded values, a non-ASCII value, an unpadded base64, a config double, the floor argument, and a form
  found only across the join of a result's strings;
- N38-N43 (review round 1): an unreadable store withholds the output until its file is removed or repaired; a
  first load in another thread cannot undo a rotation; the walk's node budget; a shared form's label; a label
  that holds a value; a store file that is not an object of strings loads as AD-456 loaded it.
Does not prove: any seam (AD-1337 S2, S3), the masking event (S2), or the cost of a pass (the orchestrator's probe).
No test reads the process environment's values: every environment is a dict the test builds.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote, quote_plus

import pytest

from probos.credential_store import CredentialSpec, CredentialStore, masked_credential_values
from probos.execution.command_env import env_name_refusal
from probos.security import secret_masking
from probos.security.secret_masking import (
    DEFAULT_FLOOR,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    MASKING_FAILED_TEXT,
    EnvSecretSource,
    MaskOutcome,
    SecretMasker,
    SecretRegistry,
    env_name_is_mask_shaped,
    secret_forms,
)
from probos.tools.protocol import ToolResult

TOKEN = "tok-Q7f2Lx9Pz4Wm8Rk3"
BUILTIN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "PROBOS_DISCORD_TOKEN", "LLM_API_KEY")


@pytest.fixture(autouse=True)
def _no_builtin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The built-in specs read these names; each test sets the ones it needs."""
    for name in BUILTIN_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_cli(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """No test runs gh: the CLI step fails as if gh were not installed, and records the call."""
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: Any) -> None:
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr("probos.credential_store.subprocess.run", _run)
    return calls


def _store(directory: Path, entries: dict[str, str] | None = None, **kwargs: Any) -> CredentialStore:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "secrets.json"
    if entries is not None:
        path.write_text(json.dumps(entries), encoding="utf-8")
    return CredentialStore(store_path=path, **kwargs)


def _masker(
    store: CredentialStore,
    *,
    registry: SecretRegistry | None = None,
    environ: dict[str, str] | None = None,
    **kwargs: Any,
) -> SecretMasker:
    return SecretMasker(
        credential_store=store,
        registry=registry if registry is not None else SecretRegistry(),
        env_source=EnvSecretSource(environ if environ is not None else {}),
        **kwargs,
    )


@dataclasses.dataclass(frozen=True)
class _TypedResult(ToolResult):
    evidence: str = dataclasses.field(kw_only=True)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise TypeError("typed evidence required")


# -- N1 to N8: forms ----------------------------------------------------------------------------------------------


def test_raw_and_json_escaped_forms_are_masked(tmp_path: Path) -> None:
    value = 'pa"ss\\word-7Kq2'
    masker = _masker(_store(tmp_path, {"db": value}))
    out = masker.mask_text(f"raw={value} json={json.dumps({'p': value})}")
    assert value not in out.text and json.dumps(value)[1:-1] not in out.text
    assert out.text.count("<secret:db>") == 2
    assert out.names == frozenset({"db"}) and out.failed is False


URL_VALUE = "k>>> j??? m-secret"


@pytest.mark.parametrize(
    "encoded",
    [quote(URL_VALUE, safe=""), quote(URL_VALUE, safe="").lower(), quote_plus(URL_VALUE)],
    ids=["upper-hex", "lower-hex", "plus"],
)
def test_url_encoded_forms_are_masked(tmp_path: Path, encoded: str) -> None:
    assert encoded != URL_VALUE  # premise: the form differs from the raw value
    assert _masker(_store(tmp_path, {"url": URL_VALUE})).mask_text(f"u={encoded}").text == "u=<secret:url>"


B64_VALUE = "k>>>j???m-secret-99"


@pytest.mark.parametrize("encode", [base64.b64encode, base64.urlsafe_b64encode], ids=["standard", "urlsafe"])
@pytest.mark.parametrize("prefix", [b"", b"a", b"ab", b"Bearer ", b"x-access-token:", b"abcd"])
def test_base64_forms_at_every_alignment(tmp_path: Path, encode: Any, prefix: bytes) -> None:
    raw = B64_VALUE.encode("utf-8")
    assert base64.b64encode(raw) != base64.urlsafe_b64encode(raw)  # premise: the two alphabets differ here
    stream = encode(prefix + raw + b"!tail").decode("ascii")
    skip = (-len(prefix)) % 3
    aligned = raw[skip:]
    core = encode(aligned[: len(aligned) - len(aligned) % 3]).decode("ascii")
    assert core in stream  # premise: the aligned core is in the encoded stream
    out = _masker(_store(tmp_path, {"b64": B64_VALUE})).mask_text(f"header {stream} end")
    assert "<secret:b64>" in out.text
    assert core not in out.text


def test_the_floor_is_eight_characters(tmp_path: Path) -> None:
    seven, eight = "Zq7#kP2", "Zq7#kP2w"
    assert len(seven) == DEFAULT_FLOOR - 1 and len(eight) == DEFAULT_FLOOR
    assert secret_forms(seven) == frozenset()
    text = f"a {seven} b {base64.b64encode(seven.encode('utf-8')).decode('ascii')} c"
    assert _masker(_store(tmp_path / "seven", {"short": seven})).mask_text(text).text is text
    assert _masker(_store(tmp_path / "eight", {"exact": eight})).mask_text(f"a {eight} b").text == "a <secret:exact> b"


def test_an_occurrence_inside_another_is_one_placeholder(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"long": "outer-SECRET-value-77", "short": "SECRET-value"}))
    out = masker.mask_text("x outer-SECRET-value-77 y SECRET-value z")
    assert out.text == "x <secret:long> y <secret:short> z"
    assert out.names == frozenset({"long", "short"})


def test_overlapping_occurrences_are_masked_as_one_span(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"left": "1234567890ab", "right": "90abcdefghij"}))
    out = masker.mask_text("[1234567890abcdefghij]")
    assert out.text == "[<secret:left>]"
    assert out.names == frozenset({"left", "right"})


PEM = (
    "-----BEGIN PRIVATE KEY-----\r\n"
    "MIIBVQIBADANBgkqhkiG9w0BAQEFAASC\r\n"
    "AT8wggE7AgEAAkEAq1w2e3r4t5y6u7i8\r\n"
    "-----END PRIVATE KEY-----"
)


def test_a_multi_line_value_is_masked_whole_and_by_line(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"pem": PEM}))
    assert masker.mask_text(f"a {PEM.replace(chr(13) + chr(10), chr(10))} b").text == "a <secret:pem> b"
    assert masker.mask_text("line AT8wggE7AgEAAkEAq1w2e3r4t5y6u7i8 only").text == "line <secret:pem> only"
    fence = "-----BEGIN PRIVATE KEY----- is a header"
    assert masker.mask_text(fence).text is fence


def test_masking_twice_changes_nothing_more(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    once = masker.mask_text(f"t={TOKEN} b={base64.b64encode(TOKEN.encode('utf-8')).decode('ascii')}")
    assert once.text == "t=<secret:github> b=<secret:github>"
    twice = masker.mask_text(once.text)
    assert twice.text is once.text and twice.names == frozenset()


# -- N9, N10: the golden identity ---------------------------------------------------------------------------------


def test_with_no_values_the_same_objects_come_back(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path))
    text = "nothing secret here " * 100
    result = ToolResult(output={"k": ["v", ("w",)]}, error="e", metadata={"m": 1})
    assert masker.mask_text(text).text is text
    masked = masker.mask_result(result)
    assert masked[0] is result and masked.names == frozenset() and masked.failed is False


def test_with_values_and_no_match_the_same_objects_come_back(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("vault:x", "vault-value-0001")
    masker = _masker(_store(tmp_path, {"github": TOKEN}), registry=registry, environ={"HF_TOKEN": "hf-env-value-123"})
    text = "no credential in this line"
    result = ToolResult(output=["a", {"b": ("c",)}], error="plain error")
    assert masker.mask_text(text).text is text
    assert masker.mask_result(result)[0] is result


# -- N11 to N16: mask_result --------------------------------------------------------------------------------------


def test_output_and_error_strings_are_masked_and_metadata_is_not(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    metadata = {"echo": TOKEN}
    result = ToolResult(output=f"out {TOKEN}", error=f"err {TOKEN}", duration_ms=5.0, metadata=metadata)
    masked = masker.mask_result(result)
    assert masked.result.output == "out <secret:github>" and masked.result.error == "err <secret:github>"
    assert masked.result.metadata is metadata and masked.result.duration_ms == 5.0
    assert masked.names == frozenset({"github"}) and masked.failed is False
    assert result.output == f"out {TOKEN}"  # the input is not changed


def test_container_values_are_masked_keys_and_types_kept(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    untouched = ["plain"]
    output = {"a": [f"x{TOKEN}", untouched], "b": (TOKEN, 3), TOKEN: "key stays", "n": None}
    masked = masker.mask_result(ToolResult(output=output)).result.output
    assert masked == {"a": ["x<secret:github>", ["plain"]], "b": ("<secret:github>", 3), TOKEN: "key stays", "n": None}
    assert type(masked["b"]) is tuple and masked["a"][1] is untouched
    assert output["a"][0] == f"x{TOKEN}"


def test_other_output_types_are_left_to_the_render_seam(tmp_path: Path) -> None:
    class Shown:
        def __repr__(self) -> str:
            return TOKEN

    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    for output in (Shown(), TOKEN.encode("utf-8"), OrderedDict(k=TOKEN)):
        result = ToolResult(output=output)
        assert masker.mask_result(result)[0] is result


def test_a_subclass_keeps_its_type_and_fields(tmp_path: Path) -> None:
    masked = _masker(_store(tmp_path, {"github": TOKEN})).mask_result(_TypedResult(output=TOKEN, evidence="ev")).result
    assert type(masked) is _TypedResult and masked.evidence == "ev" and masked.output == "<secret:github>"


def test_the_walk_stops_at_its_depth_and_node_bounds(tmp_path: Path) -> None:
    def nest(depth: int, leaf: str) -> Any:
        value: Any = leaf
        for _ in range(depth):
            value = [value]
        return value

    store = _store(tmp_path, {"github": TOKEN})
    deep = _masker(store, max_depth=3)
    assert deep.mask_result(ToolResult(output=nest(3, TOKEN))).result.output == nest(3, "<secret:github>")
    too_deep = ToolResult(output=nest(4, TOKEN))
    assert deep.mask_result(too_deep)[0] is too_deep
    wide = _masker(store, max_nodes=3).mask_result(ToolResult(output=[TOKEN, TOKEN, TOKEN])).result.output
    assert wide == ["<secret:github>", "<secret:github>", TOKEN]


def test_the_unmeasured_defaults_and_bad_arguments(tmp_path: Path) -> None:
    assert (DEFAULT_FLOOR, DEFAULT_MAX_DEPTH, DEFAULT_MAX_NODES) == (8, 32, 10_000)
    store = _store(tmp_path)
    for bad in (
        {"credential_store": MagicMock(), "registry": SecretRegistry(), "env_source": EnvSecretSource({})},
        {"credential_store": store, "registry": MagicMock(), "env_source": EnvSecretSource({})},
        {"credential_store": store, "registry": SecretRegistry(), "env_source": MagicMock()},
    ):
        with pytest.raises(TypeError):
            SecretMasker(**bad)
    for bound in ("floor", "max_depth", "max_nodes"):
        with pytest.raises(ValueError):
            _masker(store, **{bound: 0})
    with pytest.raises(TypeError):
        _masker(store).mask_text(b"bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _masker(store).mask_result({"output": "x"})  # type: ignore[arg-type]


# -- N17 to N19: failure, labels, precedence ----------------------------------------------------------------------


def test_a_failing_pass_withholds_and_logs_only_the_exception_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    def _raise(_store: CredentialStore) -> tuple[tuple[str, str], ...]:
        raise RuntimeError(f"boom {TOKEN}")

    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    monkeypatch.setattr(secret_masking, "masked_credential_values", _raise)
    caplog.set_level(logging.DEBUG)
    assert masker.mask_text(f"t {TOKEN}") == MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
    masked = masker.mask_result(_TypedResult(output=TOKEN, evidence="ev", duration_ms=2.0, metadata={"op": 1}))
    assert type(masked.result) is ToolResult and masked.result.output is None and masked.failed is True
    assert masked.result.error == MASKING_FAILED_TEXT and masked.result.duration_ms == 2.0
    assert masked.result.metadata == {"op": 1}
    assert "RuntimeError" in caplog.text
    assert TOKEN not in caplog.text and "boom" not in caplog.text


def test_a_name_that_is_not_a_plain_label_is_shown_as_unnamed(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("bad name!", TOKEN)
    out = _masker(_store(tmp_path), registry=registry).mask_text(TOKEN)
    assert out.text == "<secret:unnamed>" and out.names == frozenset({"unnamed"})


def test_the_store_names_a_value_the_environment_also_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    assert _masker(_store(tmp_path), environ={"GH_TOKEN": TOKEN}).mask_text(TOKEN).text == "<secret:github>"


# -- N20, N21: the registry ---------------------------------------------------------------------------------------


def test_a_registered_value_is_masked_until_released(tmp_path: Path) -> None:
    registry = SecretRegistry()
    masker = _masker(_store(tmp_path), registry=registry)
    handle = registry.register("vault:site", TOKEN)
    assert masker.mask_text(TOKEN).text == "<secret:vault:site>"
    handle.release()
    handle.release()
    assert masker.mask_text(TOKEN).text == TOKEN
    with registry.register("vault:site", TOKEN):
        assert masker.mask_text(TOKEN).text == "<secret:vault:site>"
    first, second = registry.register("a", TOKEN), registry.register("b", TOKEN)
    first.release()
    assert masker.mask_text(TOKEN).text == "<secret:b>"
    second.release()
    assert registry.values() == ()
    with pytest.raises(TypeError):
        registry.register("n", 123)  # type: ignore[arg-type]


def test_the_registry_is_safe_across_threads() -> None:
    registry = SecretRegistry()

    def churn() -> None:
        for index in range(200):
            registry.register(f"n{index}", f"value-{index:04d}-xyz").release()

    threads = [threading.Thread(target=churn) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert registry.values() == ()


# -- N22 to N25: the environment ----------------------------------------------------------------------------------

MASKED_NAMES = (
    "PROBOS_DISCORD_TOKEN", "HF_TOKEN", "OPENAI_API_KEY", "OPENAI_API_KEY_2", "STRIPE_KEY", "AWS_SECRET_ACCESS_KEY",
    "DB_PASSWORD", "DB_PASS", "DB_PWD", "SENTRY_DSN", "MY_APIKEY", "GPG_PASSPHRASE", "NPM_PAT", "BASIC_AUTH",
    "GOOGLE_CREDENTIALS_JSON", "FILE_ENCRYPTION_KEY",
)
# E2 (2026-11-21): the first four matched BF-890's rule in the orchestrator's shell and are not secrets. The last
# five name a path (F1): the rule decides by name, so a secret that starts with "/" is still masked (N24).
UNMASKED_NAMES = (
    "GIT_CONFIG_KEY_0", "GIT_CONFIG_KEY_1", "GIT_CONFIG_KEY_2", "COPILOT_AGENT_SESSION_ID", "PROBOS_PROFILE",
    "GIT_AUTHOR_EMAIL", "AZURE_AUTHORITY_HOST", "COOKIE_DOMAIN", "KEYBOARD_LAYOUT", "MONKEY_PATCH", "PRIVATE_NOTES",
    "DB_PASSWORD_FILE", "SSH_AUTH_SOCK", "PWD", "GOOGLE_APPLICATION_CREDENTIALS", "TOKEN_DIR",
)


@pytest.mark.parametrize("name", MASKED_NAMES)
def test_credential_names_are_masked(name: str) -> None:
    assert env_name_is_mask_shaped(name)
    assert env_name_refusal(name) == "credential_shaped"  # the rule only narrows BF-890's


@pytest.mark.parametrize("name", UNMASKED_NAMES)
def test_identifier_config_and_path_names_are_not_masked(name: str) -> None:
    assert not env_name_is_mask_shaped(name)
    assert env_name_refusal(name) == "credential_shaped"  # BF-890 still keeps each out of a child's environment


def test_the_environment_source_decides_by_name_and_strips_values(tmp_path: Path) -> None:
    session = "0f8fad5b-d9cb-469f-a165-70867728950e"
    environ = {
        "PROBOS_DISCORD_TOKEN": "discord-env-token-1",
        "HF_TOKEN": "  padded-token-1  ",
        "DEPLOY_TOKEN": "/fake-token+slash/value-01",
        "DB_PASSWORD_FILE": "/run/secrets/db-password",
        "PWD": "/home/user/project",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "COPILOT_AGENT_SESSION_ID": session,
        "PROBOS_PROFILE": "supported",
    }
    assert sorted(EnvSecretSource(environ).values()) == [
        ("env:DEPLOY_TOKEN", "/fake-token+slash/value-01"),
        ("env:HF_TOKEN", "padded-token-1"),
        ("env:PROBOS_DISCORD_TOKEN", "discord-env-token-1"),
    ]
    masker = _masker(_store(tmp_path), environ=environ)
    text = f"credential.helper supported /run/secrets/db-password /home/user/project {session}"
    assert masker.mask_text(text).text is text
    assert masker.mask_text("discord-env-token-1").text == "<secret:env:PROBOS_DISCORD_TOKEN>"
    assert masker.mask_text("key=/fake-token+slash/value-01").text == "key=<secret:env:DEPLOY_TOKEN>"


def test_the_default_source_reads_the_environment_on_each_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = {"AD1337_PROBE_TOKEN": "probe-env-value-42"}
    monkeypatch.setattr(secret_masking, "os", SimpleNamespace(environ=fake))
    masker = SecretMasker(credential_store=_store(tmp_path), registry=SecretRegistry(), env_source=EnvSecretSource())
    assert masker.mask_text("probe-env-value-42").text == "<secret:env:AD1337_PROBE_TOKEN>"
    fake.clear()
    assert masker.mask_text("probe-env-value-42").text == "probe-env-value-42"


# -- N26 to N31: the store's values -------------------------------------------------------------------------------


def test_every_store_source_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "alias-github-token-1")
    config = SimpleNamespace(
        channels=SimpleNamespace(discord=SimpleNamespace(token="discord-config-token-1")),
        auth=SimpleNamespace(crew_scope_token="crew-scope-token-123"),
    )
    store = _store(tmp_path, {"custom": "json-store-value-1"}, config=config)
    assert sorted(masked_credential_values(store)) == [
        ("crew_scope", "crew-scope-token-123"),
        ("custom", "json-store-value-1"),
        ("discord", "discord-config-token-1"),
        ("github", "alias-github-token-1"),
    ]


def test_a_value_only_the_cli_gave_is_kept_after_its_cache_expires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def _gh(argv: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(list(argv))
        return SimpleNamespace(returncode=0, stdout="cli-only-token-77\n")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _gh)
    store = _store(tmp_path, cache_ttl=0.0)
    assert ("github", "cli-only-token-77") not in masked_credential_values(store)
    assert calls == []
    assert store.get("github", requester="test") == "cli-only-token-77"
    assert ("github", "cli-only-token-77") in masked_credential_values(store)
    assert calls == [["gh", "auth", "token"]]


async def test_reading_the_values_runs_no_command_and_writes_no_access_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, Any]] = []

    class _Log:
        async def log(self, **fields: Any) -> None:
            rows.append(fields)

    def _forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("masked_credential_values ran a command")

    monkeypatch.setattr("probos.credential_store.subprocess.run", _forbidden)
    monkeypatch.setenv("AD1337_GATED_TOKEN", "gated-env-token-9")
    store = _store(tmp_path, {"custom": "json-store-value-1"}, event_log=_Log())
    store.set_tier_enforcement(True)
    store.register(CredentialSpec(name="gated", env_var="AD1337_GATED_TOKEN", min_tier="unrestricted"))
    pairs = masked_credential_values(store)
    await asyncio.sleep(0)
    assert rows == []
    assert ("gated", "gated-env-token-9") in pairs and ("custom", "json-store-value-1") in pairs
    assert store.get("discord", requester="control") is None  # control: a get writes a row
    await asyncio.sleep(0)
    assert len(rows) == 1


def test_a_rotated_value_is_masked_and_the_old_one_is_not(tmp_path: Path) -> None:
    store = _store(tmp_path, {"github": "old-github-token-1"})
    masker = _masker(store)
    assert store.get("github", requester="test") == "old-github-token-1"
    assert masker.mask_text("old-github-token-1").text == "<secret:github>"
    assert store.rotate("github", "new-github-token-2") is True
    assert masker.mask_text("new-github-token-2").text == "<secret:github>"
    assert masker.mask_text("old-github-token-1").text == "old-github-token-1"


def test_a_rotation_the_environment_refuses_keeps_that_value_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "env-github-token-3")
    store = _store(tmp_path)
    assert store.rotate("github", "unused-token-44") is False
    masker = _masker(store)
    assert masker.mask_text("env-github-token-3").text == "<secret:github>"
    assert masker.mask_text("unused-token-44").text == "unused-token-44"


def test_the_secret_masker_is_the_only_reader_of_the_values() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "probos"
    found = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "masked_credential_values" in path.read_text(encoding="utf-8", errors="replace")
    )
    assert found == ["credential_store.py", "security/secret_masking.py"]


# -- N32 to N37: padded, non-ASCII and unpadded values; a config double; the floor argument; the join ------------


def test_padded_store_and_registry_values_are_masked_by_their_core(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("vault:pad", "  padded-vault-value-1  ")
    masker = _masker(_store(tmp_path, {"github": " padded-store-token-1\n"}), registry=registry)
    out = masker.mask_text("a padded-store-token-1 b padded-vault-value-1 c")
    assert out.text == "a <secret:github> b <secret:vault:pad> c"


UNICODE_VALUE = 'p\u00e4ss"w\u00f6rd-\u00dcn\u00ef-9Kq'
UNICODE_FORMS = (
    UNICODE_VALUE,
    json.dumps(UNICODE_VALUE)[1:-1],
    json.dumps(UNICODE_VALUE, ensure_ascii=False)[1:-1],
    quote(UNICODE_VALUE, safe=""),
    base64.b64encode(UNICODE_VALUE.encode("utf-8")).decode("ascii"),
)


@pytest.mark.parametrize("form", UNICODE_FORMS, ids=["raw", "json-ascii", "json-utf8", "url", "base64"])
def test_a_non_ascii_value_is_masked_in_every_form(tmp_path: Path, form: str) -> None:
    assert len(set(UNICODE_FORMS)) == 5  # premise: the five forms are distinct strings
    assert _masker(_store(tmp_path, {"uni": UNICODE_VALUE})).mask_text(f"v={form};").text == "v=<secret:uni>;"


def test_an_unpadded_whole_base64_value_is_masked_whole(tmp_path: Path) -> None:
    raw = B64_VALUE.encode("utf-8")
    assert len(raw) % 3 != 0  # premise: the full encoding is padded, so the unpadded one differs
    unpadded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert _masker(_store(tmp_path, {"b64": B64_VALUE})).mask_text(f"t={unpadded}").text == "t=<secret:b64>"


def test_a_config_double_gives_no_values(tmp_path: Path) -> None:
    assert masked_credential_values(_store(tmp_path, config=MagicMock())) == ()


def test_the_floor_argument_is_used(tmp_path: Path) -> None:
    low = _masker(_store(tmp_path / "low", {"five": "Zq7#k"}), floor=5)
    assert low.mask_text("a Zq7#k b").text == "a <secret:five> b"
    high = _masker(_store(tmp_path / "high", {"twelve": "Zq7#kP2wLm9x"}), floor=13)
    text = "a Zq7#kP2wLm9x b"
    assert high.mask_text(text).text is text


def test_a_form_found_only_across_the_join_leaves_the_result_as_it_is(tmp_path: Path) -> None:
    masker = _masker(_store(tmp_path, {"nul": "nul\x00value-123"}))
    result = ToolResult(output=["nul", "value-123"])
    masked = masker.mask_result(result)
    assert masked.result is result and masked.names == frozenset() and masked.failed is False


# -- N38 to N43: review round 1 (the store's file, a first load in another thread, the node budget, labels) ---


@pytest.mark.parametrize("damage", ["truncated", "directory"])
def test_an_unreadable_store_withholds_the_output_until_its_file_is_repaired(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, damage: str,
) -> None:
    path = tmp_path / "secrets.json"
    if damage == "truncated":
        path.write_text('{"github": "' + TOKEN, encoding="utf-8")  # the raw value is in a file a tool could print
    else:
        path.mkdir()  # reading a directory raises an OSError (IsADirectoryError, or PermissionError on Windows)
    store = CredentialStore(store_path=path)
    masker = _masker(store)
    caplog.set_level(logging.DEBUG)
    for _ in range(2):  # a later pass does not take the failed load for an empty store either
        assert masker.mask_text(f"t {TOKEN}") == MaskOutcome(MASKING_FAILED_TEXT, frozenset(), True)
    assert masker.mask_result(ToolResult(output=TOKEN)).failed is True
    errors = [record for record in caplog.records if record.name == secret_masking.logger.name]
    assert len(errors) == 3 and all(r.levelno == logging.ERROR and r.exc_info is None for r in errors)
    legacy = [record for record in caplog.records if record.name == "probos.credential_store"]
    assert len(legacy) == 1 and legacy[0].levelno == logging.WARNING  # AD-456's one warning; the load ran once
    assert TOKEN not in caplog.text
    assert store.get("github", requester="test") is None  # AD-456's policy for get: an empty store
    logged = len(caplog.records)
    if damage == "directory":
        path.rmdir()
    else:
        path.unlink()
    # removed: the store is empty, as it is for get, so the pass succeeds with no value to mask
    assert masker.mask_text(f"t {TOKEN}") == MaskOutcome(f"t {TOKEN}", frozenset(), False)
    assert all(record.levelno < logging.ERROR for record in caplog.records[logged:])
    path.write_text(json.dumps({"github": TOKEN}), encoding="utf-8")
    assert masker.mask_text(f"t {TOKEN}") == MaskOutcome("t <secret:github>", frozenset({"github"}), False)
    assert store.get("github", requester="test") is None  # the masker reads the file; what get returns is unchanged


class _ReportingLock:
    """The store's load lock; the thread named ``rotator`` reports when it reaches it."""

    def __init__(self, reached: threading.Event) -> None:
        self._inner = threading.Lock()
        self._reached = reached

    def __enter__(self) -> None:
        if threading.current_thread().name == "rotator":
            self._reached.set()
        self._inner.acquire()

    def __exit__(self, *_exc: object) -> None:
        self._inner.release()


@pytest.mark.parametrize("first_read", ["masker", "get"])
def test_a_first_load_in_another_thread_cannot_undo_a_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first_read: str,
) -> None:
    store = _store(tmp_path, {"github": "old-github-token-1"})
    read, resume, rotator_waits_or_is_done = threading.Event(), threading.Event(), threading.Event()

    def loads(text: str) -> Any:
        parsed = json.loads(text)
        if threading.current_thread().name == "reader":
            read.set()  # the reader has parsed the old file and stored nothing yet
            resume.wait(timeout=10.0)
        return parsed

    monkeypatch.setattr(
        "probos.credential_store.json",
        SimpleNamespace(loads=loads, dumps=json.dumps, JSONDecodeError=json.JSONDecodeError),
    )
    store._store_lock = _ReportingLock(rotator_waits_or_is_done)  # type: ignore[assignment]
    rotated: list[bool] = []

    def first_load() -> None:
        if first_read == "masker":
            masked_credential_values(store)
        else:
            store.get("github", requester="test")

    def rotate() -> None:
        rotated.append(store.rotate("github", "new-github-token-2"))
        rotator_waits_or_is_done.set()

    reader = threading.Thread(target=first_load, name="reader")
    rotator = threading.Thread(target=rotate, name="rotator")
    try:
        reader.start()
        assert read.wait(timeout=10.0)
        rotator.start()
        assert rotator_waits_or_is_done.wait(timeout=10.0)  # done (no lock), or waiting for the reader's load
    finally:
        resume.set()
        for thread in (reader, rotator):
            if thread.ident is not None:
                thread.join(timeout=10.0)
    assert not reader.is_alive() and not rotator.is_alive() and rotated == [True]
    assert json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8")) == {"github": "new-github-token-2"}
    assert ("github", "new-github-token-2") in masked_credential_values(store)
    assert _masker(store).mask_text("new-github-token-2").text == "<secret:github>"


def test_the_walk_visits_at_most_max_nodes_and_copies_only_what_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    masker = _masker(_store(tmp_path, {"github": TOKEN}))
    walk = masker._map_strings
    calls, drawn = [0], [0]

    def counted_walk(*args: Any) -> Any:
        calls[0] += 1
        return walk(*args)

    def counted_enumerate(iterable: Any) -> Any:
        for pair in enumerate(iterable):
            drawn[0] += 1
            yield pair

    monkeypatch.setattr(masker, "_map_strings", counted_walk)
    monkeypatch.setattr(secret_masking, "enumerate", counted_enumerate, raising=False)
    flat = ToolResult(output=["x"] * 200_000 + [TOKEN])
    assert masker.mask_result(flat).result is flat  # the value past the budget is left to the render seam
    assert calls[0] == DEFAULT_MAX_NODES  # the list and 9,999 items, in one walk (no hit, so no second walk)
    assert drawn[0] == DEFAULT_MAX_NODES  # 9,999 items walked and one drawn before the stop; no further iteration
    small = _masker(_store(tmp_path, {"github": TOKEN}), max_nodes=3)
    as_dict = small.mask_result(ToolResult(output={"a": TOKEN, "b": TOKEN, "c": TOKEN})).result.output
    assert list(as_dict.items()) == [("a", "<secret:github>"), ("b", "<secret:github>"), ("c", TOKEN)]
    as_tuple = small.mask_result(ToolResult(output=(TOKEN, TOKEN, TOKEN))).result.output
    assert type(as_tuple) is tuple and as_tuple == ("<secret:github>", "<secret:github>", TOKEN)
    ordered = ToolResult(output=OrderedDict({TOKEN: TOKEN}))
    assert small.mask_result(ordered).result is ordered  # only an exact dict is walked; its keys are never nodes


def test_a_form_two_values_share_is_labelled_by_the_smaller_label(tmp_path: Path) -> None:
    smaller_value, larger_value = "Aabcdefghijkl", "Babcdefghijkl"
    shared = base64.b64encode(b"abcdefghijkl").decode("ascii")
    assert shared in secret_forms(smaller_value) & secret_forms(larger_value)  # premise: one aligned form, two values
    masker = _masker(_store(tmp_path, {"z-label": smaller_value, "a-label": larger_value}))
    assert masker.mask_text(f"x {shared} y").text == "x <secret:a-label> y"


def test_a_label_that_holds_a_value_is_shown_as_unnamed(tmp_path: Path) -> None:
    registry = SecretRegistry()
    registry.register("tok-ABCD1234efgh", "tok-ABCD1234efgh")
    registry.register("vault:tok-WXYZ5678ijkl", "tok-WXYZ5678ijkl")
    masker = _masker(_store(tmp_path, {"github": TOKEN}), registry=registry)
    out = masker.mask_text(f"x tok-ABCD1234efgh y tok-WXYZ5678ijkl z {TOKEN}")
    assert out.text == "x <secret:unnamed> y <secret:unnamed> z <secret:github>"
    assert out.names == frozenset({"unnamed", "github"}) and masker.mask_text(out.text).text is out.text


@pytest.mark.parametrize(
    ("content", "text", "names", "got"),
    [
        (["github", 5], f"t {TOKEN}", frozenset(), None),
        (
            {"github": TOKEN, "count": 5, "nested": {"depth": 2}},
            "t <secret:github>",
            frozenset({"github"}),
            TOKEN,
        ),
    ],
    ids=["array", "non-string-values"],
)
def test_a_store_file_that_is_not_an_object_of_strings_loads_as_ad456_loaded_it(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    content: Any,
    text: str,
    names: frozenset[str],
    got: str | None,
) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    store = CredentialStore(store_path=path)
    caplog.set_level(logging.WARNING)
    assert _masker(store).mask_text(f"t {TOKEN}") == MaskOutcome(text, names, False)  # a string entry only
    assert store.get("github", requester="test") == got  # AD-456: an array is an empty store; the rest is skipped
    assert not caplog.records  # no AD-456 warning, and no masking failure
