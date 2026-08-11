"""AD-1015: McpServerStore — persisted, runtime-mutable MCP server registrations.

The foundation for the MCP management UX (epic #955). MCP servers were previously
**static config + read-only** (``config.mcp.servers`` registered once at boot). This
store adds a SQLite-backed, runtime-mutable registry of server definitions so the
CRUD API (``routers/mcp_servers.py``) can add/edit/remove/enable/disable servers
without an edit-config-and-restart cycle.

Mirrors ``IntentGrantStore`` exactly (``ConnectionFactory`` + WAL PRAGMAs +
in-memory ``_cache`` for sync reads + ``db_path=""`` cache-only for tests). The
store is co-located with ``MCPBridge`` because it is MCP *integration/registration*
state tightly coupled to the bridge (the router reads both ``runtime.mcp_bridge``
and ``runtime.mcp_server_store``).

**No secrets.** ``validate_record`` enforces a structural secret-key denylist so no
credential-bearing header/env value is ever persisted; ``McpServerRecord.to_public_dict``
is the single serialization seam. Credentials are an AD-1016 concern — ``auth_kind``
and ``credential_ref`` are inert stored strings this AD.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from probos.integrations.mcp_bridge.risk import McpToolRisk
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    url TEXT DEFAULT '',
    headers_json TEXT DEFAULT '{}',
    command TEXT DEFAULT '',
    args_json TEXT DEFAULT '[]',
    env_json TEXT DEFAULT '{}',
    cwd TEXT DEFAULT '',
    timeout_seconds REAL,
    enabled INTEGER NOT NULL DEFAULT 1,
    auth_kind TEXT NOT NULL DEFAULT 'none',
    credential_ref TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    auth_header_name TEXT NOT NULL DEFAULT 'Authorization',
    auth_scheme TEXT NOT NULL DEFAULT 'Bearer',
    auth_env_var TEXT NOT NULL DEFAULT '',
    oauth_json TEXT NOT NULL DEFAULT '',
    default_risk TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_name ON mcp_servers(name);
"""

# AD-1017: non-secret auth columns added after AD-1015's schema shipped. A DB
# created by AD-1015 lacks these columns; ``ALTER TABLE ADD COLUMN`` appends each
# (with a default, so existing rows are fine). ``ADD COLUMN`` always appends to
# the END of the row, so the AD-1015 CREATE-TABLE order placed these four AFTER
# created_at/updated_at — a fresh DB and a migrated DB therefore share identical
# positional column order (the positional ``_row_to_record`` indices stay valid).
_AD1017_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE mcp_servers ADD COLUMN auth_header_name TEXT NOT NULL DEFAULT 'Authorization'",
    "ALTER TABLE mcp_servers ADD COLUMN auth_scheme TEXT NOT NULL DEFAULT 'Bearer'",
    "ALTER TABLE mcp_servers ADD COLUMN auth_env_var TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE mcp_servers ADD COLUMN oauth_json TEXT NOT NULL DEFAULT ''",
)

# AD-1019b: the tool risk-tier default column, appended AFTER the AD-1017
# columns. Same ``ADD COLUMN``-appends-to-END invariant: a fresh CREATE TABLE and
# an ALTER-migrated DB share identical positional order, so ``_row_to_record``'s
# ``row[19]`` index is valid on both.
_AD1019B_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE mcp_servers ADD COLUMN default_risk TEXT NOT NULL DEFAULT 'open'",
)

# --------------------------------------------------------------------------- #
# Secret-guard denylist (single source of truth, AD-1015 §2a)
# --------------------------------------------------------------------------- #
# Known credential-bearing channels. A NON-EMPTY value on one of these keys is
# refused — the operator must declare the channel via auth_kind+credential_ref
# (AD-1016 resolves the secret at registration). Empty values are allowed (the
# operator may declare the channel exists without a literal secret).
_SECRET_HEADER_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "apikey",
        "cookie",
        "x-auth-token",
        "x-amz-security-token",
    }
)
_SECRET_ENV_EXACT: frozenset[str] = frozenset(
    {"token", "secret", "password", "apikey", "api_key"}
)
_SECRET_ENV_SUFFIXES: tuple[str, ...] = (
    "_token",
    "_key",
    "_secret",
    "_password",
    "_apikey",
    "_api_key",
)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# AD-1019b: the legal ``default_risk`` tier strings, derived from the enum so a
# future 4th tier is covered automatically (single source of truth). The DB-read
# path stays tolerant (a bad legacy value is not rejected on load); this is the
# create/update *boundary* guard only (Defense in Depth).
_VALID_RISK_TIERS: frozenset[str] = frozenset(r.value for r in McpToolRisk)


def derive_server_name(
    *, server_type: str, url: str = "", command: str = ""
) -> str:
    """BF-750: a stable store name for a server declared in ``system.yaml``.

    Config entries carry no ``name`` (``MCPServerConfig`` never had one), but
    the store requires a unique one matching ``^[a-z0-9][a-z0-9-]*$`` — and that
    name is load-bearing far beyond the row: MCP grants are keyed
    ``mcp:{server}`` and ``mcp:{server}:{tool}``. A name that changed between
    boots would silently revoke every grant issued against it. So this is a pure
    function of the transport identity and nothing else: same config entry, same
    name, forever.

    HTTP derives from host + path (``https://learn.microsoft.com/api/mcp`` ->
    ``learn-microsoft-com-api-mcp``) rather than host alone, so two servers on
    one host do not collide. stdio derives from the command's basename.

    Returns ``""`` when no legal name can be formed; the caller skips seeding
    rather than inventing one. An operator who wants a readable name sets
    ``name:`` on the config entry, which always wins over this.
    """
    if server_type == "http":
        parsed = urlparse(url)
        # A hostname is required, not merely a non-empty url. ``urlparse("not a
        # url")`` yields no hostname and a path of the whole string, which would
        # slug cleanly to ``not-a-url`` and seed a junk row that no bridge call
        # can ever reach. No host, no name.
        if not parsed.hostname:
            return ""
        raw = f"{parsed.hostname}{parsed.path or ''}"
    else:
        raw = PurePosixPath((command or "").replace("\\", "/")).name

    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug if _NAME_RE.match(slug) else ""


class McpServerValidationError(ValueError):
    """Raised by :func:`validate_record`.

    Carries a stable ``code`` so the router can map a validation failure onto a
    clean ``400`` with a machine-readable error identifier.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class McpServerRecord:
    """One persisted MCP server registration (AD-1015).

    Frozen — mutations go through :meth:`McpServerStore.update` (which builds a
    new record via ``dataclasses.replace``). ``headers``/``args``/``env`` are
    non-secret by construction (the secret-guard rejects credential-bearing
    values before persistence).
    """

    name: str
    type: str
    id: str = ""
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    timeout_seconds: float | None = None
    enabled: bool = True
    auth_kind: str = "none"
    credential_ref: str = ""
    # AD-1017: non-secret auth metadata. The secret VALUE never lives here — it
    # is resolved from the credential vault by ``credential_ref`` at register
    # time. ``oauth_json`` is the non-secret OAuth client config (client_id,
    # authorize_url, token_url, scopes, redirect_uri); the client_secret + token
    # bundle live in the vault.
    auth_header_name: str = "Authorization"
    auth_scheme: str = "Bearer"
    auth_env_var: str = ""
    oauth_json: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    # AD-1019b: server-level default risk tier (open|confirm|consensus). A
    # per-tool override (McpToolRiskStore) wins over this; non-secret config.
    default_risk: str = "open"

    def to_public_dict(self) -> dict[str, Any]:
        """The single serialization seam — never emits a secret value.

        The persisted ``headers``/``env`` are non-secret (the secret-guard
        denylist refuses credential-bearing values at validation time), so they
        are safe to surface for the management UX.
        """
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "url": self.url,
            "headers": dict(self.headers),
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "enabled": self.enabled,
            "auth_kind": self.auth_kind,
            "credential_ref": self.credential_ref,
            "auth_header_name": self.auth_header_name,
            "auth_scheme": self.auth_scheme,
            "auth_env_var": self.auth_env_var,
            "oauth_json": self.oauth_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "default_risk": self.default_risk,
        }


def validate_record(
    record: McpServerRecord, *, command_allowlist: list[str]
) -> None:
    """Pure validation (no I/O) — first gate before ``create``/``update``.

    Raises :class:`McpServerValidationError` (a ``ValueError`` subclass with a
    stable ``code``) on:

      - ``name`` not matching ``^[a-z0-9][a-z0-9-]*$`` (``invalid_name``);
      - ``type`` not in ``{http, stdio}`` (``invalid_type``);
      - ``type=='http'`` with empty ``url`` (``url_required``);
      - ``type=='stdio'`` with empty ``command`` (``command_required``) or a
        ``command`` not in ``command_allowlist`` (``command_not_allowed``);
      - a non-empty value on a known secret-bearing header/env key
        (``secret_value_not_allowed``).

    Defense-in-depth: the bridge re-checks the allowlist at spawn
    (``register_stdio_server``), so this is the *first* gate, not the only one.
    """
    if not _NAME_RE.match(record.name or ""):
        raise McpServerValidationError(
            f"invalid name {record.name!r}: must match ^[a-z0-9][a-z0-9-]*$ (kebab-case)",
            code="invalid_name",
        )
    if record.type == "http":
        if not record.url:
            raise McpServerValidationError(
                "type='http' requires a non-empty 'url'", code="url_required"
            )
    elif record.type == "stdio":
        if not record.command:
            raise McpServerValidationError(
                "type='stdio' requires a non-empty 'command'", code="command_required"
            )
        if record.command not in command_allowlist:
            raise McpServerValidationError(
                f"command {record.command!r} is not in the command allowlist",
                code="command_not_allowed",
            )
    else:
        raise McpServerValidationError(
            f"invalid type {record.type!r}: must be 'http' or 'stdio'",
            code="invalid_type",
        )

    if record.default_risk not in _VALID_RISK_TIERS:
        raise McpServerValidationError(
            f"invalid default_risk {record.default_risk!r}: must be one of "
            f"{sorted(_VALID_RISK_TIERS)}",
            code="invalid_default_risk",
        )

    for key, value in (record.headers or {}).items():
        if value and key.lower() in _SECRET_HEADER_KEYS:
            raise McpServerValidationError(
                f"secret-bearing header {key!r} value is not stored in AD-1015; set "
                "auth_kind+credential_ref (AD-1016 resolves credentials at registration)",
                code="secret_value_not_allowed",
            )
    for key, value in (record.env or {}).items():
        key_lower = key.lower()
        if value and (
            key_lower in _SECRET_ENV_EXACT or key_lower.endswith(_SECRET_ENV_SUFFIXES)
        ):
            raise McpServerValidationError(
                f"secret-bearing env {key!r} value is not stored in AD-1015; set "
                "auth_kind+credential_ref (AD-1016 resolves credentials at registration)",
                code="secret_value_not_allowed",
            )


class McpServerStore:
    """Persistent registry of runtime-mutable MCP server registrations.

    SQLite-backed with an in-memory ``_cache`` for zero-I/O sync reads
    (``list_sync``). Follows the ``IntentGrantStore`` pattern; ``db_path=""``
    runs cache-only (tests skip DB I/O).

    Public API:
        start() / stop() — lifecycle
        create(record) -> McpServerRecord
        get(id) -> McpServerRecord | None
        list() -> list[McpServerRecord]
        update(id, **fields) -> McpServerRecord | None
        delete(id) -> bool
        set_enabled(id, enabled) -> McpServerRecord | None
        list_sync() -> list[McpServerRecord]
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._cache: list[McpServerRecord] = []
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._migrate_ad1017()
            await self._migrate_ad1019b()
            await self._load_cache()

    async def _migrate_ad1017(self) -> None:
        """Add the AD-1017 non-secret auth columns to a pre-AD-1017 DB.

        Each ``ADD COLUMN`` carries a default, so existing rows are unaffected;
        a duplicate-column ``OperationalError`` (columns already present from a
        fresh ``CREATE TABLE``) is the expected no-op and is swallowed.
        """
        if not self._db:
            return
        for ddl in _AD1017_MIGRATIONS:
            try:
                await self._db.execute(ddl)
            except sqlite3.OperationalError:
                pass
        await self._db.commit()

    async def _migrate_ad1019b(self) -> None:
        """Add the AD-1019b ``default_risk`` column to a pre-AD-1019b DB.

        Mirrors :meth:`_migrate_ad1017`: ``ADD COLUMN`` carries a default and
        appends to the END, so existing rows and positional order are preserved;
        the duplicate-column ``OperationalError`` on a fresh DB is a swallowed
        no-op.
        """
        if not self._db:
            return
        for ddl in _AD1019B_MIGRATIONS:
            try:
                await self._db.execute(ddl)
            except sqlite3.OperationalError:
                pass
        await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _load_cache(self) -> None:
        self._cache.clear()
        if not self._db:
            return
        async with self._db.execute("SELECT * FROM mcp_servers ORDER BY created_at") as cur:
            async for row in cur:
                self._cache.append(self._row_to_record(row))

    def _row_to_record(self, row: Any) -> McpServerRecord:
        return McpServerRecord(
            id=row[0],
            name=row[1],
            type=row[2],
            url=row[3],
            headers=json.loads(row[4] or "{}"),
            command=row[5],
            args=json.loads(row[6] or "[]"),
            env=json.loads(row[7] or "{}"),
            cwd=row[8],
            timeout_seconds=row[9],
            enabled=bool(row[10]),
            auth_kind=row[11],
            credential_ref=row[12],
            created_at=row[13],
            updated_at=row[14],
            auth_header_name=row[15],
            auth_scheme=row[16],
            auth_env_var=row[17],
            oauth_json=row[18],
            default_risk=row[19],
        )

    async def create(self, record: McpServerRecord) -> McpServerRecord:
        """Persist a new registration. Assigns ``id`` + timestamps.

        Raises ``ValueError`` on a duplicate ``name`` (the store's UNIQUE axis;
        mirrors ``CognitiveSkillCatalog.import_skill``).
        """
        if any(r.name == record.name for r in self._cache):
            raise ValueError(f"MCP server name already exists: {record.name}")
        now = time.time()
        rec = replace(
            record, id=uuid.uuid4().hex, created_at=now, updated_at=now
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO mcp_servers "
                "(id, name, type, url, headers_json, command, args_json, env_json, cwd, "
                "timeout_seconds, enabled, auth_kind, credential_ref, created_at, updated_at, "
                "auth_header_name, auth_scheme, auth_env_var, oauth_json, default_risk) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._record_to_params(rec),
            )
            await self._db.commit()
        self._cache.append(rec)
        logger.info(
            "AD-1015: MCP server registration created: %s (%s)", rec.name, rec.type
        )
        return rec

    async def get(self, server_id: str) -> McpServerRecord | None:
        for rec in self._cache:
            if rec.id == server_id:
                return rec
        return None

    async def list(self) -> list[McpServerRecord]:
        return list(self._cache)

    async def update(self, server_id: str, **fields: Any) -> McpServerRecord | None:
        """Apply ``fields`` to the record, bumping ``updated_at``.

        Returns ``None`` if the id is unknown. Raises ``ValueError`` when a
        ``name`` change collides with another registration.
        """
        idx = next(
            (i for i, r in enumerate(self._cache) if r.id == server_id), None
        )
        if idx is None:
            return None
        current = self._cache[idx]
        safe = {
            k: v for k, v in fields.items() if k not in ("id", "created_at", "updated_at")
        }
        new_name = safe.get("name", current.name)
        if new_name != current.name and any(
            r.name == new_name for r in self._cache if r.id != server_id
        ):
            raise ValueError(f"MCP server name already exists: {new_name}")
        updated = replace(current, **safe, updated_at=time.time())
        if self._db:
            await self._db.execute(
                "UPDATE mcp_servers SET "
                "name = ?, type = ?, url = ?, headers_json = ?, command = ?, args_json = ?, "
                "env_json = ?, cwd = ?, timeout_seconds = ?, enabled = ?, auth_kind = ?, "
                "credential_ref = ?, auth_header_name = ?, auth_scheme = ?, auth_env_var = ?, "
                "oauth_json = ?, default_risk = ?, updated_at = ? WHERE id = ?",
                (
                    updated.name,
                    updated.type,
                    updated.url,
                    json.dumps(updated.headers),
                    updated.command,
                    json.dumps(updated.args),
                    json.dumps(updated.env),
                    updated.cwd,
                    updated.timeout_seconds,
                    int(updated.enabled),
                    updated.auth_kind,
                    updated.credential_ref,
                    updated.auth_header_name,
                    updated.auth_scheme,
                    updated.auth_env_var,
                    updated.oauth_json,
                    updated.default_risk,
                    updated.updated_at,
                    updated.id,
                ),
            )
            await self._db.commit()
        self._cache[idx] = updated
        return updated

    async def delete(self, server_id: str) -> bool:
        idx = next(
            (i for i, r in enumerate(self._cache) if r.id == server_id), None
        )
        if idx is None:
            return False
        if self._db:
            await self._db.execute(
                "DELETE FROM mcp_servers WHERE id = ?", (server_id,)
            )
            await self._db.commit()
        del self._cache[idx]
        logger.info("AD-1015: MCP server registration deleted: %s", server_id)
        return True

    async def set_enabled(
        self, server_id: str, enabled: bool
    ) -> McpServerRecord | None:
        """Toggle the soft-disable axis (keeps the row)."""
        return await self.update(server_id, enabled=enabled)

    def list_sync(self) -> list[McpServerRecord]:
        """Sync read from cache — zero I/O (used by the finalize seed loop)."""
        return list(self._cache)

    def _record_to_params(self, rec: McpServerRecord) -> tuple[Any, ...]:
        return (
            rec.id,
            rec.name,
            rec.type,
            rec.url,
            json.dumps(rec.headers),
            rec.command,
            json.dumps(rec.args),
            json.dumps(rec.env),
            rec.cwd,
            rec.timeout_seconds,
            int(rec.enabled),
            rec.auth_kind,
            rec.credential_ref,
            rec.created_at,
            rec.updated_at,
            rec.auth_header_name,
            rec.auth_scheme,
            rec.auth_env_var,
            rec.oauth_json,
            rec.default_risk,
        )


__all__ = [
    "McpServerStore",
    "McpServerRecord",
    "McpServerValidationError",
    "validate_record",
]
