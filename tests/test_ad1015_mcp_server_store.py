"""AD-1015: McpServerStore + validate_record unit tests.

BF-287: a real ``McpServerStore`` (``db_path=""`` cache-only, plus one real-DB
round-trip via ``tmp_path``) — no MagicMock at the store boundary.
``validate_record`` is a pure function with its own boundary tests (happy path +
each error code + the secret-guard accept/reject matrix proving the guard is
neither leaky nor over-constraining).

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1015_mcp_server_store.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import sys

import pytest

from probos.integrations.mcp_bridge.store import (
    McpServerRecord,
    McpServerStore,
    McpServerValidationError,
    validate_record,
)

_ALLOW = ["uvx", "npx", "python", "node", "docker", sys.executable]


async def _started_store(db_path: str = "") -> McpServerStore:
    store = McpServerStore(db_path=db_path)
    await store.start()  # no-op for db_path="" (cache-only), real I/O otherwise
    return store


def _http_record(
    name: str = "weather", url: str = "https://example.com/mcp"
) -> McpServerRecord:
    return McpServerRecord(name=name, type="http", url=url)


# --------------------------------------------------------------------------- #
# Store CRUD
# --------------------------------------------------------------------------- #


async def test_create_assigns_uuid_and_timestamps() -> None:
    store = await _started_store()
    rec = await store.create(_http_record())
    assert rec.id and len(rec.id) == 32  # uuid4 hex
    assert rec.created_at > 0
    assert rec.updated_at == rec.created_at
    assert rec.name == "weather"
    await store.stop()


async def test_get_returns_record_and_none_for_missing() -> None:
    store = await _started_store()
    rec = await store.create(_http_record())
    got = await store.get(rec.id)
    assert got is not None and got.id == rec.id
    assert await store.get("does-not-exist") is None
    await store.stop()


async def test_list_returns_all_records() -> None:
    store = await _started_store()
    await store.create(_http_record(name="a"))
    await store.create(_http_record(name="b", url="https://b/mcp"))
    records = await store.list()
    assert {r.name for r in records} == {"a", "b"}
    await store.stop()


async def test_list_sync_reads_cache() -> None:
    store = await _started_store()
    await store.create(_http_record(name="a"))
    synced = store.list_sync()
    assert [r.name for r in synced] == ["a"]
    await store.stop()


async def test_update_bumps_updated_at_and_applies_fields() -> None:
    store = await _started_store()
    rec = await store.create(_http_record())
    updated = await store.update(rec.id, url="https://new.example.com/mcp")
    assert updated is not None
    assert updated.url == "https://new.example.com/mcp"
    assert updated.updated_at >= rec.updated_at
    assert updated.created_at == rec.created_at  # preserved
    assert updated.id == rec.id
    await store.stop()


async def test_update_missing_returns_none() -> None:
    store = await _started_store()
    assert await store.update("nope", url="x") is None
    await store.stop()


async def test_delete_removes_record_and_reports_missing() -> None:
    store = await _started_store()
    rec = await store.create(_http_record())
    assert await store.delete(rec.id) is True
    assert await store.get(rec.id) is None
    assert await store.delete(rec.id) is False  # already gone
    await store.stop()


async def test_set_enabled_toggles_flag() -> None:
    store = await _started_store()
    rec = await store.create(_http_record())
    assert rec.enabled is True
    disabled = await store.set_enabled(rec.id, False)
    assert disabled is not None and disabled.enabled is False
    assert await store.set_enabled("nope", True) is None
    await store.stop()


async def test_create_duplicate_name_raises_value_error() -> None:
    store = await _started_store()
    await store.create(_http_record(name="dup"))
    with pytest.raises(ValueError):
        await store.create(_http_record(name="dup", url="https://other/mcp"))
    await store.stop()


async def test_update_to_duplicate_name_raises_value_error() -> None:
    store = await _started_store()
    await store.create(_http_record(name="a"))
    rec_b = await store.create(_http_record(name="b", url="https://b/mcp"))
    with pytest.raises(ValueError):
        await store.update(rec_b.id, name="a")
    await store.stop()


async def test_real_db_roundtrip_persists_and_reloads(tmp_path) -> None:
    db = str(tmp_path / "mcp_servers.db")
    store = await _started_store(db)
    rec = await store.create(
        McpServerRecord(
            name="echo",
            type="stdio",
            command="python",
            args=["-m", "server"],
            env={"NODE_ENV": "prod"},
        )
    )
    await store.stop()
    # A new store over the same DB loads its cache from disk (_load_cache).
    store2 = await _started_store(db)
    loaded = await store2.get(rec.id)
    assert loaded is not None
    assert loaded.name == "echo"
    assert loaded.type == "stdio"
    assert loaded.args == ["-m", "server"]
    assert loaded.env == {"NODE_ENV": "prod"}
    assert loaded.enabled is True
    await store2.stop()


def test_to_public_dict_shape() -> None:
    rec = McpServerRecord(name="weather", type="http", url="https://x/mcp", id="abc")
    pub = rec.to_public_dict()
    assert pub["id"] == "abc"
    assert pub["name"] == "weather"
    assert pub["type"] == "http"
    assert pub["url"] == "https://x/mcp"
    assert pub["auth_kind"] == "none"
    assert pub["credential_ref"] == ""
    assert pub["enabled"] is True


# --------------------------------------------------------------------------- #
# validate_record (pure)
# --------------------------------------------------------------------------- #


def test_validate_http_happy_path() -> None:
    validate_record(_http_record(), command_allowlist=_ALLOW)  # no raise


def test_validate_stdio_happy_path() -> None:
    rec = McpServerRecord(name="echo", type="stdio", command="python", args=["x"])
    validate_record(rec, command_allowlist=_ALLOW)  # no raise


def test_validate_http_needs_url() -> None:
    rec = McpServerRecord(name="weather", type="http", url="")
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "url_required"


def test_validate_stdio_needs_command() -> None:
    rec = McpServerRecord(name="echo", type="stdio", command="")
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "command_required"


def test_validate_stdio_command_not_allowlisted() -> None:
    rec = McpServerRecord(name="echo", type="stdio", command="rm")
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "command_not_allowed"


def test_validate_invalid_type() -> None:
    rec = McpServerRecord(name="x", type="grpc")
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "invalid_type"


@pytest.mark.parametrize("bad", ["Weather", "weather_x", "-weather", "weather!", ""])
def test_validate_non_kebab_name_rejected(bad: str) -> None:
    rec = McpServerRecord(name=bad, type="http", url="https://x/mcp")
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "invalid_name"


@pytest.mark.parametrize(
    "header", ["Authorization", "X-Api-Key", "Cookie", "x-amz-security-token"]
)
def test_validate_secret_header_with_value_rejected(header: str) -> None:
    rec = McpServerRecord(
        name="weather",
        type="http",
        url="https://x/mcp",
        headers={header: "Bearer abc"},
    )
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "secret_value_not_allowed"


@pytest.mark.parametrize(
    "env_key", ["API_TOKEN", "MY_SECRET", "FOO_API_KEY", "password", "apikey"]
)
def test_validate_secret_env_with_value_rejected(env_key: str) -> None:
    rec = McpServerRecord(
        name="echo", type="stdio", command="python", env={env_key: "s3cr3t"}
    )
    with pytest.raises(McpServerValidationError) as exc:
        validate_record(rec, command_allowlist=_ALLOW)
    assert exc.value.code == "secret_value_not_allowed"


def test_validate_empty_secret_value_allowed() -> None:
    # The operator may DECLARE a secret channel with an empty value (AD-1016
    # fills it via credential_ref); a non-secret header alongside still passes.
    rec = McpServerRecord(
        name="weather",
        type="http",
        url="https://x/mcp",
        headers={"Authorization": "", "Content-Type": "application/json"},
    )
    validate_record(rec, command_allowlist=_ALLOW)  # no raise


def test_validate_non_secret_pairs_pass_through() -> None:
    rec = McpServerRecord(
        name="echo",
        type="stdio",
        command="python",
        headers={"Content-Type": "application/json"},
        env={"NODE_ENV": "production", "PORT": "8080"},
    )
    validate_record(rec, command_allowlist=_ALLOW)  # no raise
