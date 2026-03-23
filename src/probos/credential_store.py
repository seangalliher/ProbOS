"""CredentialStore -- Ship's Computer credential resolution service (AD-395).

Centralizes credential lookup across ProbOS agents and adapters.
Resolution chain: explicit config -> environment variable -> CLI tool -> None.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

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
    description: str = ""


class CredentialStore:
    """Ship's Computer service -- centralized credential resolution."""

    def __init__(
        self,
        config: Any = None,
        event_log: Any = None,
        cache_ttl: float = 300.0,
    ):
        self._config = config
        self._event_log = event_log
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name -> (value, expiry_time)
        self._cache_ttl = cache_ttl
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

    def register(self, spec: CredentialSpec) -> None:
        """Register a credential spec. Extensions can add their own."""
        self._specs[spec.name] = spec

    def get(
        self,
        name: str,
        *,
        requester: str = "unknown",
        department: str | None = None,
    ) -> str | None:
        """Resolve a credential by name. Returns None if not available."""
        spec = self._specs.get(name)
        if not spec:
            logger.warning("CredentialStore: unknown credential '%s'", name)
            return None

        # Department access check
        if spec.allowed_departments is not None and department:
            if department not in spec.allowed_departments:
                logger.warning(
                    "CredentialStore: department '%s' denied access to '%s'",
                    department, name,
                )
                self._log_access(name, requester, "denied_department")
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

        # 4. CLI command
        if spec.cli_command:
            try:
                result = subprocess.run(
                    spec.cli_command,
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
