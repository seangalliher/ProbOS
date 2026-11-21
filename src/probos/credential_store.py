"""CredentialStore -- Ship's Computer credential resolution service (AD-395).

Centralizes credential lookup across ProbOS agents and adapters.
Resolution chain: explicit config -> environment variable -> CLI tool -> None.

BF-908: the crew-scope token is not a CredentialSpec. ``crew_scope_token(runtime)``
below is its one reader: the OS keyring's entry (``CredentialStore.crew_scope``,
read once at startup), else ``auth.crew_scope_token`` from the runtime's config.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.execution.command_env import trusted_command_env
from probos.security.crew_scope import (  # noqa: F401 -- CREW_SCOPE_UNAVAILABLE is re-exported for routers/auth.py
    CREW_SCOPE_UNAVAILABLE,
    CrewScopeKeyring,
    configured_crew_scope_token,
)

logger = logging.getLogger(__name__)


@dataclass
class CredentialSpec:
    """Defines how to resolve a credential."""

    name: str  # e.g., "github", "discord", "llm_api"
    config_key: str | None = None  # system.yaml dot-path, e.g., "channels.discord.token"
    env_var: str | None = None  # e.g., "GH_TOKEN"
    env_var_aliases: list[str] = field(default_factory=list)  # e.g., ["GITHUB_TOKEN"]
    cli_command: list[str] | None = None  # e.g., ["gh", "auth", "token"]
    allowed_departments: list[str] | None = None  # None = unrestricted
    # AD-456c: minimum Earned Agency tier required to read this credential.
    # String matches ``probos.earned_agency.AgencyLevel.value`` --
    # ``"reactive"`` (Ensign) / ``"suggestive"`` (Lieutenant) /
    # ``"autonomous"`` (Commander) / ``"unrestricted"`` (Senior). Default
    # ``None`` = no tier gate (preserves AD-456 v1 ungated-lookup behavior).
    # Only enforced when ``CredentialStore._tier_enforcement`` is True (set
    # at finalize via ``config.security_infra.credential_tier_enforcement``).
    min_tier: str | None = None
    description: str = ""


# AD-456c: Earned Agency tier ordinal map. Mirrors ``_TIER_ORDER`` shape from
# ``probos.earned_agency`` (line 90) but locally defined to avoid importing
# the full ``earned_agency`` module surface into credential_store. Unknown
# tier strings resolve to ``-1`` via ``.get(name, -1)`` -- sentinel for deny
# when ``_tier_enforcement`` is True (test #12 locks this).
_AGENCY_ORDER: dict[str, int] = {
    "reactive": 0,        # Ensign
    "suggestive": 1,      # Lieutenant
    "autonomous": 2,      # Commander
    "unrestricted": 3,    # Senior
}


class CredentialStore:
    """Ship's Computer service -- centralized credential resolution.

    AD-456: Extended with persistent rotation, JSON-backed store resolution
    step, and SECRET_ROTATED emission.
    """

    def __init__(
        self,
        config: Any = None,
        event_log: Any = None,
        cache_ttl: float = 300.0,
        *,
        store_path: Path | None = None,
        emit_event: Any | None = None,
    ):
        self._config = config
        self._event_log = event_log
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        # AD-1337: the last value get() resolved for each name, kept past the cache's TTL so a value only the CLI
        # gives stays maskable (masked_credential_values below). rotate() drops the name's entry.
        self._last_resolved: dict[str, str] = {}
        self._cache_ttl = cache_ttl
        # AD-456: optional persistent JSON store (atomic write + rotation events)
        self._store_path = store_path
        self._emit_event = emit_event
        self._store: dict[str, str] = {}
        self._store_loaded = False
        # AD-1337: the first load can run in a worker thread (S2's priming get) while rotate() runs on the loop.
        self._store_lock = threading.Lock()
        # AD-1337: True after a load that failed; get() keeps AD-456's empty store, the secret masker reads the file.
        self._store_load_failed = False
        # AD-456c: per-tier credential lookup gate. Default False preserves
        # AD-456 v1 ungated-lookup behavior; finalize flips to True when
        # ``config.security_infra.credential_tier_enforcement`` is set.
        self._tier_enforcement: bool = False
        # BF-908: the crew-scope token's keyring step. Not a CredentialSpec and never in
        # the JSON store, so get(), available(), list_credentials() and rotate() never
        # reach it; crew_scope_token(runtime) at the end of this module is its one reader.
        self.crew_scope = CrewScopeKeyring()
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in credential specs for known services."""
        self.register(CredentialSpec(
            name="github",
            env_var="GH_TOKEN",
            env_var_aliases=["GITHUB_TOKEN"],
            cli_command=["gh", "auth", "token"],
            description="GitHub API token (via gh CLI auth or env var)",
        ))
        self.register(CredentialSpec(
            name="discord",
            config_key="channels.discord.token",
            env_var="PROBOS_DISCORD_TOKEN",
            description="Discord bot token",
        ))
        self.register(CredentialSpec(
            name="llm_api",
            config_key="cognitive.llm_api_key",
            env_var="LLM_API_KEY",
            description="Shared LLM API key",
        ))

    def set_tier_enforcement(self, enabled: bool) -> None:
        """AD-456c: Toggle per-tier credential lookup gate.

        When enabled, ``get(...)`` consults ``CredentialSpec.min_tier`` and
        the caller-supplied ``tier`` kwarg; specs with ``min_tier=None``
        remain ungated. When disabled (the v1 default), the tier check is a
        no-op regardless of any ``min_tier`` settings -- AD-456 v1
        ungated-lookup behavior is preserved bit-for-bit.

        Wired from ``startup/finalize.py`` based on
        ``config.security_infra.credential_tier_enforcement``.
        """
        self._tier_enforcement = bool(enabled)

    def register(self, spec: CredentialSpec) -> None:
        """Register a credential spec. Extensions can add their own."""
        self._specs[spec.name] = spec

    # ---------- AD-456: persistent rotation ----------

    def _load_store(self) -> None:
        """Lazy-load the JSON-backed store. Idempotent.

        AD-1337: the body runs under ``_store_lock``, so the store loads once and a first load in a worker thread
        cannot store a value it read before a ``rotate`` replaced it. A read that fails leaves ``get`` AD-456's empty
        store, as before, and sets ``_store_load_failed`` so ``masked_credential_values`` reads the file itself.
        """
        with self._store_lock:
            if self._store_loaded or self._store_path is None:
                return
            if self._store_path.exists():
                try:
                    self._store.update(_read_store_file(self._store_path))
                except (json.JSONDecodeError, OSError):
                    self._store_load_failed = True
                    logger.warning(
                        "AD-456: secrets store read failed (path=%s); "
                        "starting with empty store",
                        self._store_path, exc_info=True,
                    )
            self._store_loaded = True

    def _resolve_from_store(self, name: str) -> str | None:
        """Resolution-chain step: read from JSON store. Returns None if absent."""
        self._load_store()
        return self._store.get(name)

    def rotate(self, name: str, value: str) -> bool:
        """Operator-side rotate: persist to JSON store and emit SECRET_ROTATED.

        Returns True on persisted rotation, False if the rotation could not
        be persisted (no store_path configured, env var precedence, or write
        failure). Env-sourced secrets are NOT mutated by rotate(); operator
        must update the env var externally. The method emits SECRET_ROTATED
        with appropriate `source` and `persisted` flags so observers know
        whether persistence succeeded.
        """
        self._load_store()
        if self._store_path is None:
            logger.warning(
                "AD-456: rotate(%s) called but no store_path configured; "
                "cannot persist", name,
            )
            self._emit_rotated(name, source="no_store", persisted=False)
            return False

        spec = self._specs.get(name)
        if spec is not None and spec.env_var:
            env_value = os.environ.get(spec.env_var, "").strip()
            if env_value:
                # Env var is set; persistent rotation does not override env priority.
                self._emit_rotated(name, source="env", persisted=False)
                return False

        self._store[name] = value
        # Invalidate cache so next get(...) resolves fresh.
        self._cache.pop(name, None)
        self._last_resolved.pop(name, None)  # AD-1337: the old value is no longer masked

        try:
            tmp = self._store_path.with_suffix(".json.tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._store), encoding="utf-8")
            os.replace(tmp, self._store_path)
        except OSError:
            logger.error(
                "AD-456: secrets store write failed (path=%s); "
                "in-memory cache updated but not persisted",
                self._store_path, exc_info=True,
            )
            self._emit_rotated(name, source="store", persisted=False)
            return False
        self._emit_rotated(name, source="store", persisted=True)
        return True

    def _emit_rotated(self, name: str, *, source: str, persisted: bool) -> None:
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType
            self._emit_event(
                EventType.SECRET_ROTATED,
                {
                    "name": name,
                    "source": source,
                    "persisted": persisted,
                    "rotated_at": time.time(),
                },
            )
        except Exception:
            logger.warning(
                "AD-456: SECRET_ROTATED emit failed (name=%s)", name, exc_info=True,
            )

    def _emit_tier_denied(
        self,
        *,
        name: str,
        requester: str,
        requested_tier: str | None,
        required_tier: str,
    ) -> None:
        """AD-456c: Emit ``CREDENTIAL_TIER_DENIED`` on a tier-gated denial.

        Log-and-degrade tier -- emit failures must NOT propagate; the deny
        decision is already returned to the caller and the access has been
        logged via ``_log_access``.
        """
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType
            self._emit_event(
                EventType.CREDENTIAL_TIER_DENIED,
                {
                    "name": name,
                    "requester": requester,
                    "requested_tier": requested_tier,
                    "required_tier": required_tier,
                },
            )
        except Exception:
            logger.warning(
                "AD-456c: CREDENTIAL_TIER_DENIED emit failed (name=%s, requester=%s)",
                name, requester, exc_info=True,
            )

    # ---------- end AD-456 extension ----------

    def get(
        self,
        name: str,
        *,
        requester: str = "unknown",
        department: str | None = None,
        tier: str | None = None,
    ) -> str | None:
        """Resolve a credential by name. Returns None if not available.

        AD-456c: When ``CredentialStore._tier_enforcement`` is True AND the
        spec carries a ``min_tier``, ``tier`` (Earned Agency level value --
        ``"reactive"``/``"suggestive"``/``"autonomous"``/``"unrestricted"``)
        must satisfy the floor or the lookup is denied. When enforcement is
        False (v1 default), ``tier`` is ignored and AD-456 ungated-lookup
        behavior is preserved.
        """
        spec = self._specs.get(name)
        if not spec:
            logger.warning("CredentialStore: unknown credential '%s'", name)
            return None

        # Department access check (AD-395)
        if spec.allowed_departments is not None and department:
            if department not in spec.allowed_departments:
                logger.warning(
                    "CredentialStore: department '%s' denied access to '%s'",
                    department, name,
                )
                self._log_access(name, requester, "denied_department")
                return None

        # AD-456c: Per-tier access check (defense in depth -- runs AFTER
        # department check). Only consulted when enforcement is on AND the
        # spec carries a min_tier; otherwise this block is a no-op.
        if self._tier_enforcement and spec.min_tier is not None:
            required_order = _AGENCY_ORDER[spec.min_tier]
            actual_order = _AGENCY_ORDER.get(tier, -1) if tier is not None else -1
            if actual_order < required_order:
                logger.warning(
                    "CredentialStore: tier '%s' denied access to '%s' "
                    "(required min_tier=%s)",
                    tier, name, spec.min_tier,
                )
                self._emit_tier_denied(
                    name=name,
                    requester=requester,
                    requested_tier=tier,
                    required_tier=spec.min_tier,
                )
                self._log_access(name, requester, "denied_tier")
                return None

        # Check cache
        cached = self._cache.get(name)
        if cached:
            value, expiry = cached
            if time.monotonic() < expiry:
                self._log_access(name, requester, "cache")
                return value
            del self._cache[name]

        # Resolution chain
        value = self._resolve(spec)

        # Log access
        source = "resolved" if value else "not_found"
        self._log_access(name, requester, source)

        # Cache if found
        if value:
            self._cache[name] = (value, time.monotonic() + self._cache_ttl)
            self._last_resolved[name] = value  # AD-1337: kept past the TTL for the secret masker

        return value

    def _resolve(self, spec: CredentialSpec) -> str | None:
        """Walk the resolution chain: config -> env -> CLI."""
        # 1. Config key
        if spec.config_key and self._config:
            val = self._resolve_config_key(spec.config_key)
            if val:
                return val

        # 2. Primary env var
        if spec.env_var:
            val = os.environ.get(spec.env_var, "").strip()
            if val:
                return val

        # 3. Env var aliases
        for alias in spec.env_var_aliases:
            val = os.environ.get(alias, "").strip()
            if val:
                return val

        # 3a. AD-456: JSON-backed store (rotated values; survives across resets)
        store_val = self._resolve_from_store(spec.name)
        if store_val:
            return store_val

        # 4. CLI command
        if spec.cli_command:
            try:
                result = subprocess.run(
                    spec.cli_command,
                    env=trusted_command_env(),
                    capture_output=True, encoding="utf-8", errors="replace", timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

        return None

    def _resolve_config_key(self, dot_path: str) -> str | None:
        """Traverse config by dot-separated path (e.g., 'channels.discord.token')."""
        obj = self._config
        for part in dot_path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        if isinstance(obj, str) and obj.strip():
            return obj.strip()
        return None

    def _log_access(self, name: str, requester: str, source: str) -> None:
        """Log credential access to event_log if available."""
        if self._event_log is None:
            return
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_log.log(
                category="credential",
                event=f"access:{name}",
                agent_type=requester,
                detail=f"source={source}",
            ))
        except RuntimeError:
            # No event loop running (e.g., during tests)
            pass

    def available(self, name: str) -> bool:
        """Check if a credential can be resolved without returning the value."""
        return self.get(name, requester="availability_check") is not None

    def list_credentials(self) -> list[dict[str, str | bool]]:
        """List registered credential names and status. Never returns values."""
        results = []
        for spec in self._specs.values():
            results.append({
                "name": spec.name,
                "available": self.available(spec.name),
                "description": spec.description,
            })
        return results


def _read_store_file(path: Path) -> dict[str, str]:
    """AD-456's reading of the JSON store at ``path``: its ``str``-to-``str`` entries, ``{}`` for JSON that is not
    an object. Raises what reading or parsing raises. AD-1337: ``_load_store`` and ``masked_credential_values``
    share it, so the two cannot disagree on what the file holds."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)}


def masked_credential_values(store: CredentialStore) -> tuple[tuple[str, str], ...]:
    """AD-1337 (#1560): every credential value ``store`` can name, as ``(name, value)`` pairs, for the secret masker.

    Each spec's configured value, its environment variable and aliases, every JSON-store entry, the last value
    ``get`` resolved for each name, and the crew-scope token. No CLI command runs, no access row is written and no
    department or tier gate applies, because nothing here is handed to a requester:
    ``probos.security.secret_masking.SecretMasker`` turns the values into patterns and never returns them. It is
    this function's only caller in ``src`` (pinned by ``tests/test_ad1337_secret_masking.py``). A module function,
    not a method: ``CredentialStore`` is at the 15-method SRP review trigger. Safe from a worker thread: the first
    load runs under the store's ``_store_lock``, so it cannot undo a concurrent ``rotate``, and each dict is copied
    in one step before it is read. After a load that failed (``_store_load_failed``), ``get`` keeps AD-456's empty
    store, but the file can still hold values a tool could print: it is read on every call while it exists, and a
    read that fails raises, so the masker withholds the output (AD-1337 D7) until the file reads again.
    """
    pairs: list[tuple[str, str]] = []
    for spec in list(store._specs.values()):
        if spec.config_key and store._config:
            configured = store._resolve_config_key(spec.config_key)
            if configured:
                pairs.append((spec.name, configured))
        for env_name in (spec.env_var, *spec.env_var_aliases):
            if env_name:
                env_value = os.environ.get(env_name, "").strip()
                if env_value:
                    pairs.append((spec.name, env_value))
    store._load_store()
    pairs.extend((name, value) for name, value in dict(store._store).items() if value.strip())
    if store._store_load_failed and store._store_path is not None and store._store_path.exists():
        pairs.extend((name, value) for name, value in _read_store_file(store._store_path).items() if value.strip())
    pairs.extend(dict(store._last_resolved).items())
    crew_scope = store.crew_scope.token(store._config)
    if isinstance(crew_scope, str) and crew_scope.strip():
        pairs.append(("crew_scope", crew_scope.strip()))
    return tuple(pairs)


def crew_scope_token(runtime: Any) -> str:
    """BF-908 (#1605): the crew-scope token to enforce; the one read every route and startup use.

    The OS keyring's entry (read once at startup through ``runtime.credential_store``),
    else ``auth.crew_scope_token`` from the runtime's current config, else ``""``. A
    runtime without a ``CredentialStore`` (a test double) reads its config only.
    """
    config = getattr(runtime, "config", None)
    store = getattr(runtime, "credential_store", None)
    if isinstance(store, CredentialStore):
        return store.crew_scope.token(config)
    return configured_crew_scope_token(config)


def crew_scope_locked(runtime: Any) -> bool:
    """BF-908: True when no token is configured and the keyring could not be read, or startup has not read it yet.

    Refuse every caller then (A2, D21). A runtime without a real ``CredentialStore`` (a test double) is never locked.
    """
    store = getattr(runtime, "credential_store", None)
    return isinstance(store, CredentialStore) and store.crew_scope.locked(getattr(runtime, "config", None))
