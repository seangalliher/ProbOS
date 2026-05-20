# AD-757 - Identity and Continuity (Captain Card + Voice/Avatar Profile Continuity)

Status: drafted (planning slate only)
Issue: #703
Parent: #486
Depends on: AD-756 (#702)

## Objective
Ensure Yeo continuity across restart and context transitions, grounded in Captain Card and persisted profile state.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Captain Card context bootstrap for Yeo front-door behavior.
- Session continuity contract for active delegated tasks.
- Voice/avatar/profile continuity linkage for Yeo identity over restart.

## Out of Scope
- New 3D avatar rendering architectures.
- Non-OSS identity provider productization.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Captain Card as primary identity anchor for Yeo personalization.
- Session continuity contract for active delegated tasks (local storage).
- Voice profile and avatar identity linkage (AV choices persist).
- Local identity recovery on restart.

**Commercial Extension Point:**
- Multi-device identity sync via cloud state (commercial overlay).
- Org SSO binding for team member profiles.
- Identity federation and cross-org guest access.
- Behavioral continuity metrics and anomaly detection.

## File Targets
- `src/probos/captain_card/`
- `src/probos/identity.py`
- `src/probos/crew_profile.py`
- `src/probos/service_profile.py`
- `ui/src/components/`

## Pre-Flight Anchors
- Verify captain-card API in `src/probos/captain_card/card.py`.
- Verify identity and onboarding continuity paths in `src/probos/agent_onboarding.py` and `src/probos/identity.py`.
- Verify voice/profile APIs in `src/probos/api_models.py` and related routers.

## Implementation Spec

### Section 1: Captain Card Context Bootstrap

**File:** `src/probos/captain_card/card.py` (extend existing)

Extend `CaptainCard` with continuity fields:
```python
@dataclass
class CaptainCard:
    id: str  # UUID, immutable
    name: str
    email: str | None = None
    preferred_work_hours: str = "08:00-18:00"
    timezone: str = "UTC"
    voice_profile: str | None = None  # "Ezri" | "Computer" | operator custom
    avatar_theme: str = "default"  # color/style for visual identification
    last_active_session: datetime | None = None
    continuity_checksum: str  # SHA256 of profile for anomaly detection
    
    def to_system_context(self) -> str:
        """Generate system prompt preamble from card for LLM context bootstrap."""
        return f"""You are Yeo, {self.name}'s personal assistant.
Working hours: {self.preferred_work_hours} {self.timezone}
Voice: {self.voice_profile or 'Ship\\'s Computer'}
Avatar: {self.avatar_theme}
"""
```

**Tests:** `tests/test_captain_card.py` (2 tests)
- Card creation + persistence
- System context generation from card

### Section 2: Session Continuity Model (AD-750 session persistence)

**File:** `src/probos/cognitive/session_manager.py` (extend from AD-750)

Add continuity recovery:
```python
class SessionManager:
    async def restore_active_session(self, captain_id: str) -> Session | None:
        """On startup, recover last active session if within 24h."""
        last_session = self._db.query(Session).filter(
            Session.user_id == captain_id,
            Session.last_activity > datetime.now() - timedelta(hours=24)
        ).order_by(Session.last_activity.desc()).first()
        
        if last_session:
            # Restore context, resume pending tasks
            last_session.context = self._restore_context(last_session.id)
            return last_session
        return None
    
    async def resume_delegated_tasks(self, session: Session) -> list[str]:
        """List incomplete tasks from session (active_tasks field)."""
        return session.active_tasks
```

**Tests:** `tests/test_session_continuity.py` (2 tests)
- Session restored after 1h restart
- Active tasks recoverable from session

### Section 3: Delegated Task Continuity & Recovery

**File:** `src/probos/cognitive/task_recovery.py` (new)

Create `TaskRecoveryManager`:
```python
class TaskRecoveryManager:
    async def list_pending_delegations(self, session_id: str) -> list[str]:
        """Tasks awaiting completion from crew (e.g. BuilderAgent running a build)."""
    
    async def check_delegation_status(self, task_id: str) -> dict:
        """Poll task status: running | completed | blocked | failed."""
    
    async def resume_or_retry(self, task_id: str) -> dict:
        """Resume incomplete task or retry if failed (with exponential backoff)."""
```

**Endpoint:** `GET /work/pending-tasks` returns active delegations with status.

**Tests:** `tests/test_task_recovery.py` (2 tests)
- Pending tasks listed on session restore
- Task status polling functional

### Section 4: Voice & Avatar Continuity Hooks

**File:** `src/probos/identity.py` (new)

Create `VoiceProfileManager` + `AvatarProfileManager`:
```python
class VoiceProfileManager:
    async def set_voice_profile(self, captain_id: str, voice: str) -> None:
        """Store voice preference (e.g. 'Ezri', 'Ship\\'s Computer')."""
    
    async def get_voice_profile(self, captain_id: str) -> str | None:
        """Retrieve voice for TTS rendering."""

class AvatarProfileManager:
    async def set_avatar_theme(self, captain_id: str, theme: str) -> None:
        """Store avatar visual theme (color, style, etc.)."""
    
    async def get_avatar_theme(self, captain_id: str) -> dict:
        """Retrieve avatar config for UI rendering."""
```

**Storage:** CaptainCard fields persist preferences across restart.

**Tests:** `tests/test_voice_avatar_profiles.py` (2 tests)
- Voice profile persists across restart
- Avatar theme persists across restart

### Section 5: Continuity Checksum & Anomaly Detection Hook

**File:** `src/probos/identity.py` (extend)

Add anomaly detection preparation:
```python
class ContinuityValidator:
    async def validate_profile_integrity(self, card: CaptainCard) -> bool:
        """Compute fresh checksum, compare against stored.
        
        OSS: Log warning if mismatch (informational only).
        Commercial: Could trigger behavioral anomaly detection.
        """
        fresh_hash = self._compute_profile_hash(card)
        if fresh_hash != card.continuity_checksum:
            logger.warning(f"Profile anomaly detected: {card.id}")
            return False
        return True
```

**Tests:** `tests/test_continuity_validator.py` (1 test)
- Checksum matches for unchanged card

### Section 6: Runtime Wiring for Identity Continuity

**File:** `src/probos/runtime.py` (extend startup)

In `async def startup()`:
```python
# Load or create Captain Card
self.captain_card = await self.identity_manager.get_or_create_card()

# Attempt session recovery
self.active_session = await self.session_manager.restore_active_session(self.captain_card.id)
if self.active_session:
    logger.info(f"Resumed session {self.active_session.id}")
    pending = await self.task_recovery.list_pending_delegations(self.active_session.id)
    logger.info(f"Pending delegations: {len(pending)}")

# Bootstrap LLM context with Captain Card
self._system_context = self.captain_card.to_system_context()
```

### Section 7: Acceptance Criteria & Gate

**Test Expectations:**
- `test_captain_card.py`: 2 tests
- `test_session_continuity.py`: 2 tests
- `test_task_recovery.py`: 2 tests
- `test_voice_avatar_profiles.py`: 2 tests
- `test_continuity_validator.py`: 1 test
- **Total: 9 new tests**

**Dependencies:** Requires AD-750 (session manager), AD-756 (conversational UX for task display).

**Integration Gate:** Captain Card must be available at runtime startup; fallback to generating one if missing.

**Completion Signal:**
- All 9 tests passing
- Yeo continuity survives restart (session + context restored)
- Delegated tasks recoverable after shutdown
- Voice/avatar preferences persist across restarts
- Anomaly detection hook available for commercial extension

## Acceptance Criteria
- Yeo continuity survives restart without identity drift.
- Delegated-task continuity is recoverable and auditable.
- Voice/avatar continuity hooks are additive and optional.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
