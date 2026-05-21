# AD-754 - Yeo Data Hardening Baseline

Status: drafted (planning slate only)
Issue: #700
Parent: #486
Depends on: AD-749 (#695)

## Objective
Define OSS personal-assistant hardening baseline for data safety and user trust.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Encryption-at-rest boundary for sensitive assistant/session material.
- PII redaction rules for logs, traces, and memory artifacts.
- Assistant audit log records for delegated actions.
- "Forget this" deletion path for user-requested erasure.
- Credential-encryption utility pattern (AionUi-inspired pattern only).

## Out of Scope
- Commercial DLP/compliance SKU features.
- New external paid encryption services.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Encryption at rest for local tokens and session material (system keyring or DPAPI/Keychain).
- PII redaction in diagnostic logs (email/phone/doc-URL masking).
- Assistant audit log for personal traceability.
- "Forget this" deletion path for explicit erasure.

**Commercial Extension Point:**
- DLP policy engine (sensitivity-label aware, pattern-based).
- Key management services (BYOK, HSM, Azure Key Vault).
- Retention policies and legal hold for org compliance.
- Encrypted transport and TLS pinning for regulated environments.

## File Targets
- `src/probos/security/`
- `src/probos/attachments/`
- `src/probos/knowledge/`
- `src/probos/routers/`
- `src/probos/config.py`

## Pre-Flight Anchors
- Verify existing audit infrastructure in `src/probos/security/audit.py`.
- Verify attachment and retention flows in `src/probos/attachments/`.
- Verify memory/record deletion seams in `src/probos/knowledge/` and routers.

## Implementation Spec

### Section 1: Encryption-at-Rest for Credentials

**File:** `src/probos/security/credential_encryption.py` (new)

Create `CredentialEncryptor` class:
```python
class CredentialEncryptor:
    """Platform-aware credential storage: DPAPI (Windows), Keychain (macOS), libsecret (Linux)."""
    
    def __init__(self, app_name: str = "ProbOS"):
        """Use system keyring (no manual key management required)."""
    
    def store(self, key: str, value: str) -> None:
        """Encrypt + store credential. Example: 'm365_refresh_token' -> encrypted value."""
    
    def retrieve(self, key: str) -> str | None:
        """Decrypt credential. Returns None if not found."""
    
    def delete(self, key: str) -> None:
        """Securely delete credential from keyring."""
```

**Platform-Specific:**
- Windows: `keyring` lib → DPAPI (Win32 CryptProtectData)
- macOS: `keyring` lib → Keychain (`security` command)
- Linux: `keyring` lib → libsecret (systemd service)

**Usage in M365TokenManager (from AD-749):**
```python
async def get_token(self) -> str | None:
    encrypted_token = self._encryptor.retrieve("m365_access_token")
    if encrypted_token:
        return encrypted_token
    # Refresh flow...
    self._encryptor.store("m365_refresh_token", refresh_token)
```

**Tests:** `tests/test_credential_encryptor.py` (2 tests)
- Store + retrieve round-trip
- Delete removes credential from keyring

### Section 2: PII Redaction Engine

**File:** `src/probos/security/pii_redaction.py` (new)

Create `PIIRedactor` class:
```python
class PIIRedactor:
    """Masking engine for logs, traces, and memory artifacts."""
    
    _EMAIL_PATTERN = r'[\w\.-]+@[\w\.-]+\.\w+'
    _PHONE_PATTERN = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    _URL_PATTERN = r'https?://[^\s]+'
    _DOCID_PATTERN = r'(docid|file_id|item_id)=([A-Za-z0-9_\-]+)'
    
    @staticmethod
    def redact_email(text: str) -> str:
        """Replace email with ***@***.***"""
        return re.sub(PIIRedactor._EMAIL_PATTERN, "***@***.***", text)
    
    @staticmethod
    def redact_phone(text: str) -> str:
        """Replace phone with ***-***-****"""
        return re.sub(PIIRedactor._PHONE_PATTERN, "***-***-****", text)
    
    @staticmethod
    def redact_url(text: str) -> str:
        """Replace URL path + query with [REDACTED_URL]"""
        return re.sub(PIIRedactor._URL_PATTERN, "[REDACTED_URL]", text)
    
    @staticmethod
    def redact_all(text: str) -> str:
        """Apply all redaction rules."""
        text = PIIRedactor.redact_email(text)
        text = PIIRedactor.redact_phone(text)
        text = PIIRedactor.redact_url(text)
        return text
```

**Logger Integration:**
```python
class LogRedactionFormatter(logging.Formatter):
    """Custom formatter that redacts PII from all log messages."""
    
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return PIIRedactor.redact_all(msg)

# Install globally:
for handler in logging.root.handlers:
    handler.setFormatter(LogRedactionFormatter("%(name)s - %(levelname)s - %(message)s"))
```

**Tests:** `tests/test_pii_redaction.py` (4 tests)
- Email redaction: "alice@example.com" → "***@***.***"
- Phone redaction: "555-123-4567" → "***-***-****"
- URL redaction: "https://...?api_key=abc" → "[REDACTED_URL]"
- Log messages automatically redacted (logger integration)

### Section 3: Assistant Audit Log

**File:** `src/probos/security/audit_log.py` (new)

Create `AuditLog` class:
```python
@dataclass
class AuditEntry:
    timestamp: datetime
    action: str  # "intent_executed", "file_read", "credential_stored", etc.
    resource: str  # file path, M365 resource, etc. (PII-redacted before storage)
    actor: str  # "Yeo", "OutlookAgent", "Captain", etc.
    success: bool
    reason: str | None  # reason if failed
    session_id: str  # link to session for correlation

class AuditLog:
    def __init__(self, db_path: str):
        """Store audit entries in SQLite (local, not cloud)."""
    
    async def log_intent(self, intent: str, resource: str, actor: str, success: bool) -> None:
        """Record intent execution."""
    
    async def log_credential_operation(self, op: str, key: str) -> None:
        """Record credential store/retrieve/delete."""
    
    async def query(self, days_back: int = 7) -> list[AuditEntry]:
        """Retrieve recent audit entries for `/explain` + debugging."""
```

**Data Retention:** 90 days by default (configurable via `audit_retention_days` in config.yaml).

**Tests:** `tests/test_audit_log.py` (3 tests)
- Log intent + query returns entry
- PII redacted in stored resource names
- Retention policy enforced (90-day cutoff)

### Section 4: "Forget This" Deletion Path

**File:** `src/probos/knowledge/erasure.py` (new)

Create `ErasureManager` class:
```python
class ErasureManager:
    async def forget_episode(self, episode_id: str, reason: str = "user_request") -> ErasureResult:
        """User-initiated deletion of specific episode.
        
        Cascading deletions:
        - Remove from ChromaDB episodic store
        - Remove related attachments from AttachmentStore
        - Mark audit entries with [DELETED]
        - Return ErasureResult with deleted count + timestamps
        """
    
    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all records mentioning specific resource (e.g., ~/private/secrets.txt)."""
    
    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """User-initiated wipe of all history with specific agent."""
```

**Endpoints:**
```python
@router.post("/security/forget")
async def request_erasure(request: ForgetRequest) -> dict:
    """User manually requests episode/resource/agent-memory erasure."""
    result = await erasure_manager.forget_episode(request.episode_id)
    return {"deleted_count": result.count, "timestamps": result.timestamps}
```

**UI Component:** `ui/src/components/wardroom/ForgetThis.tsx`

Shows:
- Recent episodes list with summary text
- "Delete This Conversation" button
- Confirmation: "Episode deleted. Forget permanently? [Yes] [Cancel]"

**Tests:** `tests/test_erasure_manager.py` (3 tests)
- Forget episode removes from ChromaDB + attachments
- Cascading deletions complete without errors
- Audit trail shows [DELETED] marker post-erasure

### Section 5: Data Classification Policy

**File:** `src/probos/security/data_classification.py` (new)

Create classification enum + policy:
```python
class DataClassification(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"

class ClassificationPolicy:
    """OSS: simple policy. Commercial: advanced sensitivity-label mapping."""
    
    @staticmethod
    def classify(content: str, source: str = "unknown") -> DataClassification:
        """Infer classification from content + source.
        
        Examples:
        - Email from Outlook: CONFIDENTIAL (personal data)
        - File from ~/Documents: INTERNAL (general personal)
        - Chrome history: RESTRICTED (PII-heavy)
        """
        if "email" in source or "outlook" in source.lower():
            return DataClassification.CONFIDENTIAL
        if "password" in content.lower() or "secret" in content.lower():
            return DataClassification.RESTRICTED
        return DataClassification.INTERNAL
```

**Tests:** `tests/test_data_classification.py` (2 tests)
- Email classified as CONFIDENTIAL
- Password-bearing content classified as RESTRICTED

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_credential_encryptor.py`: 2 tests
- `test_pii_redaction.py`: 4 tests
- `test_audit_log.py`: 3 tests
- `test_erasure_manager.py`: 3 tests
- `test_data_classification.py`: 2 tests
- **Total: 14 new tests**

**Security Compliance:**
- All credentials stored via system keyring (no plaintext files)
- All logs automatically redacted for email/phone/URL
- All audit entries persist locally (no export without user consent)
- Erasure deletions are cascading + auditable

**Integration Gate:** Requires AD-749 (M365 tokens stored via CredentialEncryptor).

**Type Annotations:** All public methods fully typed.

**Completion Signal:**
- All 14 tests passing
- Credentials never appear in plaintext in logs
- Audit log traces every assistant action (user-facing `/explain` ready)
- "Forget this" deletion endpoint functional with cascading cleanup
- Classification policy correctly infers sensitivity from source
- For free leverage documented: redaction/audit hooks integrate with existing logging and records pipelines.

## Acceptance Criteria
- Data-classification and redaction policies are explicit and test-covered.
- Erasure workflow has auditable completion states.
- Secrets/tokens are never logged in plaintext.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
