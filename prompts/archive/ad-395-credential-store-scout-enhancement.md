# AD-395: CredentialStore + Scout `gh` CLI Enhancement

## Context

ProbOS agents currently manage credentials ad-hoc:
- **ScoutAgent** (`scout.py:177-191`): `_get_gh_token()` tries `GH_TOKEN` → `GITHUB_TOKEN` env vars → `gh auth token` CLI
- **Discord adapter**: token from `system.yaml` plaintext or `PROBOS_DISCORD_TOKEN` env var
- **LLM tiers**: API keys in `system.yaml` or per-tier env vars
- **Copilot SDK**: `gh auth login` OAuth flow (separate from above)

This is credential sprawl — every agent/adapter implements its own auth lookup. As ProbOS gains more external integrations (more channel adapters, research APIs, federation), this gets worse.

Additionally, ScoutAgent uses `httpx.AsyncClient` to hit the GitHub REST API directly, which is throttled at 10 req/min for unauthenticated search API calls. Switching to `gh api` via subprocess gets authenticated 5000 req/hr rate limits and leverages the user's existing `gh auth` session.

Finally, GPT Researcher (25.9K stars) demonstrates multi-dimensional source curation — scoring sources on credibility and reliability, not just relevance. We absorb this pattern into Scout's classification.

## Objectives

### 1. CredentialStore — Ship's Computer Service

A centralized credential resolution service. Agents call `credential_store.get("github")` instead of implementing their own auth lookup.

**File:** `src/probos/credential_store.py`

**Design principles:**
- **Resolution chain** (priority order): explicit config → environment variable → CLI tool → None
- **No secrets stored in memory long-term** — resolve on demand, cache with short TTL (5 min default)
- **Audit logging** — every credential access logged to event_log (agent_type, credential_name, timestamp, resolution_source)
- **Department-scoped access** (future-ready) — credential definitions include `allowed_departments` field, enforced at `get()` time
- **Shared Cognitive Fabric Principle** — this is a Ship's Computer service, not a per-agent store

**Credential definition:**

```python
@dataclass
class CredentialSpec:
    """Defines how to resolve a credential."""
    name: str                                # e.g., "github", "discord", "llm_api"
    config_key: str | None = None           # system.yaml path, e.g., "channels.discord.token"
    env_var: str | None = None              # e.g., "GH_TOKEN"
    env_var_aliases: list[str] = field(default_factory=list)  # e.g., ["GITHUB_TOKEN"]
    cli_command: list[str] | None = None    # e.g., ["gh", "auth", "token"]
    allowed_departments: list[str] | None = None  # None = unrestricted
    description: str = ""
```

**CredentialStore class:**

```python
class CredentialStore:
    """Ship's Computer service — centralized credential resolution."""

    def __init__(self, config: ProbOSConfig, event_log: EventLog | None = None):
        self._config = config
        self._event_log = event_log
        self._specs: dict[str, CredentialSpec] = {}
        self._cache: dict[str, tuple[str, float]] = {}  # name → (value, expiry_time)
        self._cache_ttl: float = 300.0  # 5 minutes
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in credential specs for known services."""
        # GitHub — used by ScoutAgent, future research agents
        self.register(CredentialSpec(
            name="github",
            env_var="GH_TOKEN",
            env_var_aliases=["GITHUB_TOKEN"],
            cli_command=["gh", "auth", "token"],
            description="GitHub API token (via gh CLI auth or env var)",
        ))
        # Discord — used by DiscordAdapter
        self.register(CredentialSpec(
            name="discord",
            config_key="channels.discord.token",
            env_var="PROBOS_DISCORD_TOKEN",
            description="Discord bot token",
        ))
        # LLM API key (shared) — used by tiered LLM client
        self.register(CredentialSpec(
            name="llm_api",
            config_key="cognitive.llm_api_key",
            env_var="LLM_API_KEY",
            description="Shared LLM API key",
        ))

    def register(self, spec: CredentialSpec) -> None:
        """Register a credential spec. Extensions can add their own."""
        self._specs[spec.name] = spec

    def get(self, name: str, *, requester: str = "unknown", department: str | None = None) -> str | None:
        """Resolve a credential by name. Returns None if not available."""
        # 1. Check cache
        # 2. Check department access (if spec.allowed_departments is set)
        # 3. Try config_key (traverse self._config by dot-path)
        # 4. Try env_var, then env_var_aliases
        # 5. Try cli_command (subprocess.run, timeout=5)
        # 6. Log access to event_log
        # 7. Cache result with TTL
        # Return value or None

    def available(self, name: str) -> bool:
        """Check if a credential can be resolved without returning the value."""

    def list_credentials(self) -> list[dict]:
        """List registered credential names and their resolution status (available/unavailable).
        Never returns actual values."""
```

**Registration on Runtime:**

In `runtime.py`, register the CredentialStore alongside other Ship's Computer services:

```python
# In Runtime.__init__ or start():
from probos.credential_store import CredentialStore
self.credential_store = CredentialStore(config=self.config, event_log=self.event_log)
```

Pass `credential_store` to agents that need it (ScoutAgent via `runtime` reference, which they already have).

### 2. Scout `gh` CLI Migration

Replace `httpx.AsyncClient` GitHub API calls in `scout.py` `perceive()` with `gh api` subprocess calls.

**Why:** `gh api` uses the authenticated session from `gh auth login`, getting 5000 req/hr vs 10 req/min for unauthenticated search. No need to manage auth headers — `gh` handles it.

**Changes to `scout.py`:**

a) **Remove `_get_gh_token()` function entirely.** Auth is now handled by CredentialStore (for token resolution) and `gh api` (for authenticated requests).

b) **Replace `httpx` search with `gh api` calls in `perceive()`:**

```python
async def _search_github(self, query: str, min_stars: int) -> list[dict]:
    """Search GitHub via gh CLI for authenticated rate limits."""
    import asyncio
    encoded_query = f"{query} stars:>={min_stars}"
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["gh", "api", "search/repositories",
             "--method", "GET",
             "-f", f"q={encoded_query}",
             "-f", "sort=stars",
             "-f", "per_page=30"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("gh api search failed: %s", result.stderr)
            return []
        data = json.loads(result.stdout)
        return data.get("items", [])
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        logger.warning("GitHub search error: %s", e)
        return []
```

c) **Update `perceive()` to call `_search_github()` instead of httpx:**

Replace the two httpx search blocks with calls to `_search_github()` using the same topic queries. Remove `import httpx` if no longer needed.

d) **Fallback:** If `gh` CLI is not available, log a warning and return empty results (graceful degradation). Do NOT fall back to httpx — the whole point is to use authenticated access.

### 3. Source Curation Enrichment (from GPT Researcher)

Enhance the Scout's classification schema with multi-dimensional scoring.

**Changes to `_INSTRUCTIONS` (system prompt):**

Add to the existing RELEVANCE field description:

```
RELEVANCE: 1-5 (how relevant to ProbOS's mission)
CREDIBILITY: 1-5 (project maturity — docs quality, CI status, contributor count, release cadence)
RELIABILITY: 1-5 (maintenance health — last commit recency, issue response, test coverage indicators)
```

**Changes to `ScoutFinding` dataclass:**

```python
@dataclass
class ScoutFinding:
    repo_full_name: str
    stars: int
    url: str
    classification: str  # "absorb" | "visiting_officer"
    relevance: int  # 1-5
    credibility: int  # 1-5 (NEW)
    reliability: int  # 1-5 (NEW)
    summary: str
    insight: str
    language: str = ""
    license: str = ""
    topics: list[str] = field(default_factory=list)

    @property
    def composite_score(self) -> float:
        """Weighted composite: relevance 50%, credibility 25%, reliability 25%."""
        return self.relevance * 0.5 + self.credibility * 0.25 + self.reliability * 0.25
```

**Changes to `parse_scout_reports()`:**
- Parse the new `CREDIBILITY:` and `RELIABILITY:` fields from `===SCOUT_REPORT===` blocks
- Default to 3 if missing (backward compat with existing reports)

**Changes to `filter_findings()`:**
- Filter on `composite_score >= min_relevance` instead of just `relevance >= min_relevance`
- Sort by `composite_score` descending

**Changes to `format_digest()`:**
- Include credibility/reliability in the digest output alongside relevance
- Show composite score

**Changes to `act()`:**
- Bridge notifications triggered by `composite_score >= 4` instead of `relevance >= 4`
- JSON report includes the new fields

### 4. Shell Command Enhancement

Add `/credentials` command to shell.py for Captain visibility:

```python
"/credentials": "List registered credentials and their status (/credentials)",
```

Handler:
```python
async def _cmd_credentials(self, arg: str) -> None:
    """List credential status (names + available/unavailable, never values)."""
    store = self.runtime.credential_store
    for cred in store.list_credentials():
        status = "[green]available[/green]" if cred["available"] else "[red]unavailable[/red]"
        self.console.print(f"  {cred['name']}: {status} — {cred['description']}")
```

This gives the Captain visibility into which credentials are configured without ever showing values.

## Files to Create

| File | Purpose |
|------|---------|
| `src/probos/credential_store.py` | CredentialStore service |
| `tests/test_credential_store.py` | Tests for CredentialStore |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/scout.py` | Remove `_get_gh_token()`, replace httpx with `gh api`, add credibility/reliability fields, update scoring |
| `src/probos/runtime.py` | Register CredentialStore on Runtime |
| `src/probos/experience/shell.py` | Add `/credentials` command |
| `tests/test_scout.py` | Update tests for new fields and gh CLI approach |

## Testing Requirements

### CredentialStore tests (`test_credential_store.py`):
1. Test config_key resolution (mock config with nested access)
2. Test env_var resolution (monkeypatch env)
3. Test env_var_aliases resolution (first alias wins)
4. Test CLI command resolution (mock subprocess)
5. Test priority chain (config > env > CLI)
6. Test cache TTL (resolve once, return cached, expire after TTL)
7. Test `available()` returns bool without exposing value
8. Test `list_credentials()` returns names + status, never values
9. Test department-scoped access (future-ready — when `allowed_departments` is set, reject mismatched departments)
10. Test `register()` for extension-added credentials
11. Test audit logging (event_log receives access records)

### Scout tests (`test_scout.py` — update existing):
12. Test `_search_github()` calls `gh api` subprocess correctly
13. Test `_search_github()` handles gh CLI not found gracefully
14. Test `ScoutFinding.composite_score` calculation
15. Test `parse_scout_reports()` extracts credibility/reliability fields
16. Test `parse_scout_reports()` defaults to 3 when fields missing (backward compat)
17. Test `filter_findings()` uses composite_score
18. Test `format_digest()` includes new fields

## Architecture Notes

- CredentialStore follows the **Shared Cognitive Fabric Principle** — centralized Ship's Computer service with per-credential scoped access, not per-agent credential management
- Aligns with the **Secrets Management** roadmap item under Security Team (Phase 31) — this is the first step: resolution chain. Future steps: keyring integration, rotation support, encryption at rest
- The `register()` method enables **Extension-First Architecture** (Phase 30) — extensions can register their own credential specs without modifying core
- Source curation enrichment absorbed from **GPT Researcher** (25.9K stars, Apache 2.0, 2026-03-22)

## What NOT to Change

- Do NOT modify Discord adapter auth (keep existing env var pattern for now; CredentialStore registration makes it discoverable but adapter migration is a separate AD)
- Do NOT modify LLM client auth (same reasoning)
- Do NOT add `httpx` fallback — if `gh` CLI is not available, Scout returns empty results and logs a warning
- Do NOT add encryption or keyring integration yet — that's Phase 31 Secrets Management scope
