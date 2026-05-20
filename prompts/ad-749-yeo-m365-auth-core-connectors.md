# AD-749 - Yeo M365 Auth + Core Connector Agents

Status: drafted (planning slate only)
Issue: #695
Parent: #486 (AD-710 umbrella)
Related: #480 (AD-704 channel adapters)

## Objective
Define OSS-ready foundation for Microsoft 365 assistant capabilities through connector boundaries that all crew agents can use.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- M365 auth boundary (device-code/OAuth lifecycle contracts).
- Connector agent interfaces for Outlook, Teams, Calendar, SharePoint, OneDrive.
- Adapter boundary pattern for channels/plugins (pattern absorption from AionUi only).
- Pairing/authorization entry controls for remote channel activation.

## Out of Scope
- Re-implementing Telegram/WhatsApp/Matrix/Teams adapters from #480.
- Enterprise-only tenant provisioning workflows (extension-point only).

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Single-user OAuth device-flow auth with local token caching.
- Connector agents for personal M365 account (Outlook, Teams, Calendar, SharePoint, OneDrive read).
- Local BYOL credential storage (operator brings own API keys).

**Commercial Extension Point:**
- Multi-tenant enterprise provisioning (SSO, SCIM, token broker).
- Tenant policy connectors and conditional-access compatibility.
- Compliance-scoped credential management (key vault integration).
- Audit logging for enterprise SOC teams.

## File Targets
- `src/probos/channels/`
- `src/probos/integrations/`
- `src/probos/config.py`
- `src/probos/runtime.py`
- `src/probos/routers/` (auth + management surfaces)

## Pre-Flight Anchors
- Verify current channel adapter baseline in `src/probos/channels/`.
- Verify auth and config extension points in `src/probos/config.py` and `src/probos/routers/auth.py`.
- Verify runtime wiring seam in `src/probos/runtime.py`.

## Implementation Spec

### Section 1: OAuth Token Lifecycle Manager

**File:** `src/probos/integrations/m365_token_manager.py`

Create `M365TokenManager` class:
```python
class M365TokenManager:
    def __init__(self, cache_dir: str, config: M365Config) -> None:
        """Initialize token manager with local cache.
        
        Args:
            cache_dir: Directory for token storage (encrypted via system keyring).
            config: M365Config with client_id, authority, scopes.
        """
    
    async def acquire_token_device_code_flow(self) -> str:
        """Device-code OAuth flow for personal accounts.
        
        Returns:
            Access token (valid for Outlook/Teams/Calendar/SharePoint/OneDrive).
        
        On auth failure: log warning (no credentials in logs), return None, 
        honest-degrade (connector agents raise NotAuthorizedError).
        """
    
    async def get_token(self, scope: str = "https://graph.microsoft.com/.default") -> str | None:
        """Get cached token or refresh if expired.
        
        Stores raw refresh_token in system keyring (Windows DPAPI / macOS Keychain / Linux libsecret).
        Never logs credentials or tokens.
        """
    
    def revoke(self) -> None:
        """User-initiated token erasure ('forget this' flow)."""
```

**Tests:** `tests/test_m365_token_manager.py` (3 tests minimum)
- Happy path: device-code flow acquires + caches token
- Error case: offline/network failure returns None, logs warning (no sensitive data)
- Boundary: token expiry triggers refresh, keyring fallback if unavailable

**Dependencies:** Use `msal` (MIT license, Microsoft official) for device-code flow.

### Section 2: Connector Agent Base Protocol

**File:** `src/probos/integrations/m365_connector.py`

Create `M365Connector` protocol (typing.Protocol):
```python
class M365Connector(Protocol):
    """Base interface for M365-backed agents (Outlook/Teams/Calendar/SharePoint/OneDrive).
    
    All M365 agents must implement this to be routable by Yeo + crew.
    """
    
    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
    
    async def list_changes(self, since: datetime) -> list[Change]:
        """Retrieve changes since timestamp for this connector's resource."""
    
    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return dict with: resource_id, action, timestamp, success, error."""
```

Create concrete agents:
- `OutlookAgent`: read inbox, draft message, flag/snooze, search
- `TeamsAgent`: list chats, channel messages, search
- `CalendarAgent`: find-time, book meeting, list events
- `SharePointAgent`: search sites/lists, read permissions
- `OneDriveAgent`: search files, download, metadata, permissions

Each inherits from `CognitiveAgent` or `SkillBasedAgent` (existing base).

**Router Surface:** New agents register intents:
- `outlook_read_inbox`, `outlook_draft`, `outlook_flag`
- `teams_list_chats`, `teams_search_channel`
- `calendar_find_time`, `calendar_book_event`
- etc.

**Tests:** `tests/test_m365_connectors.py` (3 tests per agent, 15 min)
- Mock M365TokenManager, verify happy-path read + error-case auth failure
- Verify no credentials logged
- Verify intent descriptors are registered

### Section 3: Auth Router & Config Extension Points

**File:** `src/probos/routers/auth_m365.py`

Add auth endpoints:
```python
@router.post("/auth/m365/authorize")
async def authorize_m365_personal(request: Request) -> dict:
    """Trigger device-code OAuth flow. Returns device_code + user_code for display."""

@router.post("/auth/m365/complete")
async def complete_m365_auth(request: Request) -> dict:
    """Poll until token acquired. Safe for unattended operation with honest-degrade."""
```

**File:** `src/probos/config.py` (Pydantic extension)

Add `M365Config` model:
```python
class M365Config(BaseModel):
    enabled: bool = False
    client_id: str | None = None  # operator's app registration ID
    authority: str = "https://login.microsoftonline.com/common"
    scopes: list[str] = ["https://graph.microsoft.com/.default"]
    cache_dir: str = "${HOME}/.probos/m365_cache"
    
    class Config:
        # Validator: if enabled=True, client_id must not be None
        pass
```

Extend `RuntimeConfig`:
```python
class RuntimeConfig(BaseModel):
    m365: M365Config = Field(default_factory=M365Config)
    # ... existing fields
```

**File:** `config/system.yaml` (operator config)

Add:
```yaml
m365:
  enabled: false  # personal user sets to true + provides client_id
  client_id: null
  authority: "https://login.microsoftonline.com/common"
  cache_dir: ~/.probos/m365_cache
```

**Tests:** `tests/test_auth_m365.py` (2 tests)
- Config load: enabled=False (default), M365 agents not spawned
- Config load: enabled=True + client_id set, M365TokenManager initialized

### Section 4: Runtime Wiring

**File:** `src/probos/runtime.py`

In `_create_pools()` method, after existing pool setup, add:
```python
if self.config.m365.enabled and self.config.m365.client_id:
    self._m365_token_manager = M365TokenManager(
        cache_dir=self.config.m365.cache_dir,
        config=self.config.m365
    )
    # Spawn connector agents
    for agent_class in [OutlookAgent, TeamsAgent, CalendarAgent, SharePointAgent, OneDriveAgent]:
        agent = agent_class(runtime=self, token_manager=self._m365_token_manager)
        self._pool_by_intent.register(agent)
else:
    logger.info("M365 connectors disabled (enable in config.m365.enabled)")
```

In `_build_runtime_summary()`, add M365 connector count to "Intent Count" breakdown.

**Tests:** `tests/test_runtime_m365_wiring.py` (2 tests)
- Config disabled: no M365 agents spawned
- Config enabled: all 5 M365 agents present in intent registry

### Section 5: Data Hardening (Minimal for AD-749)

- Token storage: system keyring only (never plaintext files, never env vars)
- Logging: all log messages must pass through `_redact_pii()` (email, phone, URL masking)
  - Use existing `scripts/diagnose_llm.py` audit as reference
- No credential in error messages: any auth failure logs "M365 auth unavailable" not the token or error detail

**Tests:** `tests/test_m365_security_baseline.py` (2 tests)
- Tokens never logged: grep test artifacts for "Authorization: Bearer" (should be zero)
- PII redaction: email addresses in log messages masked as `***@***.***`

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_m365_token_manager.py`: 3 tests
- `test_m365_connectors.py`: 15 tests (3 per agent)
- `test_auth_m365.py`: 2 tests
- `test_runtime_m365_wiring.py`: 2 tests
- `test_m365_security_baseline.py`: 2 tests
- **Total: 24 new tests** (should not break existing suite)

**Type Annotations:** Every new public method must have full type hints (parameters + return).

**Engineering Principles Compliance:**
- (S) M365TokenManager has single responsibility: token lifecycle
- (O) M365Connector protocol is open for extension (new agents), closed for modification
- (L) All agent subclasses implement M365Connector contract
- (I) Depend on M365Connector protocol, not concrete agents
- (D) TokenManager + auth config injected into agents, not imported
- (LOD) No `agent._token_manager._cache` chains; all access through public API

**Captain Invariant:** Verify final code includes "all crew agents can use M365 connectors; Yeo is the front-door delegator" in a docstring or inline comment on the runtime wiring block.

**Completion Signal:** 
- All 24 tests passing
- No type errors or circular imports
- M365 agents appear in `/introspect agent_info` output when enabled
- Config load + pool wiring confirmed in runtime.py diffs
