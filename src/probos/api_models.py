"""ProbOS API request/response models (AD-516).

All Pydantic models extracted from api.py for use by routers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


# ── Chat models ───────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    # AD-720: optional content-hash references to previously-uploaded images.
    attachment_ids: list[str] = Field(default_factory=list)


class PerAgentReply(BaseModel):
    """AD-719: one entry of a multi-agent fan-out reply."""
    agent_id: str
    callsign: str
    text: str


class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None
    # AD-719: multi-agent fan-out attribution. Both optional for backward compat.
    mentions: list[str] = Field(default_factory=list)
    per_agent_replies: list[PerAgentReply] = Field(default_factory=list)
    # AD-791a: chat-thread provenance. Populated by the inline-callsign and
    # vision branches; ``None`` for the fan-out path (deferred to AD-791g)
    # and for the no-default-thread response shapes (slash commands, etc.).
    thread_id: str | None = None


# ── Chat attachments (AD-720) ─────────────────────────────────────

class AttachmentUploadRequest(BaseModel):
    """AD-720: image paste upload request body (JSON, base64-encoded)."""
    content_hash: str   # client-computed sha256 hex
    blob_b64: str       # base64-encoded raw bytes
    mime: str           # declared MIME type


class AttachmentUploadResponse(BaseModel):
    """AD-720: image paste upload response."""
    attachment_id: str  # == content_hash
    url: str            # browser-fetchable URL
    mime: str
    size_bytes: int
    sha256: str


# ── Self-mod models ───────────────────────────────────────────────

class SelfModRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    original_message: str = ""


class EnrichRequest(BaseModel):
    intent_name: str
    intent_description: str
    parameters: dict[str, str] = {}
    user_guidance: str


# ── Build models (AD-304, AD-326, AD-345, AD-375) ────────────────

class BuildRequest(BaseModel):
    """Request to trigger the BuilderAgent."""
    title: str
    description: str
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []
    force_native: bool = False
    force_visiting: bool = False
    model: str = ""


class BuildApproveRequest(BaseModel):
    """Request to approve and execute a generated build."""
    build_id: str
    file_changes: list[dict[str, Any]] = []
    title: str = ""
    description: str = ""
    ad_number: int = 0
    branch_name: str = ""


class BuildResolveRequest(BaseModel):
    """Request to resolve a failed build (AD-345)."""
    build_id: str
    resolution: str  # "retry_extended", "retry_targeted", "retry_fix", "commit_override", "abort"


class BuildQueueApproveRequest(BaseModel):
    """Request to approve a queued build — merge to main (AD-375)."""
    build_id: str


class BuildQueueRejectRequest(BaseModel):
    """Request to reject a queued build (AD-375)."""
    build_id: str


class BuildEnqueueRequest(BaseModel):
    """Request to add a build spec to the dispatch queue (AD-375)."""
    title: str
    description: str = ""
    target_files: list[str] = []
    reference_files: list[str] = []
    test_files: list[str] = []
    ad_number: int = 0
    constraints: list[str] = []
    priority: int = 5


# ── Design models (AD-308) ───────────────────────────────────────

class DesignRequest(BaseModel):
    """Request to trigger the ArchitectAgent."""
    feature: str
    phase: str = ""


class DesignApproveRequest(BaseModel):
    """Request to approve an architect proposal — forwards BuildSpec to builder."""
    design_id: str


# ── Agent chat model (AD-430b) ───────────────────────────────────

class AgentChatRequest(BaseModel):
    """Request to send a direct message to a specific agent."""
    message: str
    history: list[dict[str, str]] = []  # AD-430b: conversation history from HXI
    # BF (2026-05-11): optional attachment content-hashes — augments prompt with
    # extracted text + image markers before /api/agent/{id}/chat dispatches the
    # direct_message intent. Mirrors ChatRequest.attachment_ids.
    attachment_ids: list[str] = Field(default_factory=list)
    # AD-791a: optional explicit thread override. ``None`` (default) routes
    # the turn to the implicit default 1:1 thread for the target agent.
    # When set, must reference an existing thread that includes this agent
    # in its participants list; otherwise the router returns 400.
    thread_id: str | None = None


# ── Ward Room models (AD-407, AD-424) ────────────────────────────

class CreateChannelRequest(BaseModel):
    name: str
    description: str = ""
    created_by: str  # agent_id


class CreateThreadRequest(BaseModel):
    author_id: str
    title: str
    body: str
    author_callsign: str = ""
    thread_mode: str = "discuss"      # AD-424
    max_responders: int = 0           # AD-424


class UpdateThreadRequest(BaseModel):
    """AD-424: Captain thread management."""
    locked: bool | None = None
    thread_mode: str | None = None     # "inform" | "discuss" | "action"
    max_responders: int | None = None
    pinned: bool | None = None


class CreatePostRequest(BaseModel):
    author_id: str
    body: str
    parent_id: str | None = None
    author_callsign: str = ""


class EndorseRequest(BaseModel):
    voter_id: str
    direction: str  # "up" | "down" | "unvote"


class ShutdownRequest(BaseModel):
    reason: str = ""


class SubscribeRequest(BaseModel):
    agent_id: str
    action: str = "subscribe"  # "subscribe" | "unsubscribe"


# ── Skill Framework models (AD-428) ──────────────────────────────

class SkillAssessmentRequest(BaseModel):
    skill_id: str
    new_level: int             # ProficiencyLevel value (1-7)
    source: str = "assessment"
    notes: str = ""


class SkillCommissionRequest(BaseModel):
    agent_type: str


# ── ACM lifecycle models (BF-093) ────────────────────────────────

class AgentLifecycleRequest(BaseModel):
    """Request body for ACM lifecycle transitions (decommission/suspend/reinstate)."""
    reason: str = ""


# ── Capability-request decision model (AD-857) ───────────────────

class CapabilityRequestDecideRequest(BaseModel):
    """Request body for approving/denying a pending capability request.

    A deny (``approve=False``) requires a non-empty ``reason`` so the
    requesting agent gets actionable feedback; an approve may omit it.
    """
    approve: bool
    reason: str = ""

    @model_validator(mode="after")
    def _require_reason_on_deny(self) -> "CapabilityRequestDecideRequest":
        if not self.approve and not (self.reason or "").strip():
            raise ValueError("a reason is required when denying a capability request")
        return self


# ── Agent cooldown model (BF-093) ────────────────────────────────

class SetCooldownRequest(BaseModel):
    """Request body for per-agent proactive cooldown."""
    cooldown: float = 300.0  # seconds, range 60–1800


# ── Voice profile model (AD-718) ─────────────────────────────────

class SetVoiceProfileRequest(BaseModel):
    """Request body for per-agent voice profile (AD-718, extended AD-718a).

    ``proposal_rationale`` is set ONLY on approve-from-proposal flows
    (see AD-718a). Hand-edits leave it empty; episode-write is gated on
    a non-empty value (Captain Q4 ruling: hand-edits carry no rationale
    to learn from, so the episodic write only fires when the proposal
    rationale is present).
    """
    voice_name: str = ""
    pitch: float = 0.9
    rate: float = 0.95
    volume: float = 0.8
    # AD-718c: optional per-agent wake phrase (≤ 50 chars; bounds re-checked
    # by ``VoiceProfile.__post_init__`` on the server side).
    wake_phrase: str = ""
    proposal_rationale: str = ""  # AD-718a: non-empty iff approve-from-proposal


# ── Voice proposal models (AD-718a) ──────────────────────────────

class ProposeVoiceProfileRequest(BaseModel):
    """AD-718a: Optional Captain revision note for "Request revisions" flows."""
    captain_note: str = ""


class ProposeVoiceProfileResponse(BaseModel):
    """AD-718a: Validated VoiceProfile candidate returned for Captain review.

    NOT persisted — caller must follow up with
    ``PUT /{agent_id}/voice-profile`` (carrying ``proposal_rationale``)
    once the Captain approves.
    """
    agent_id: str
    voice_profile: dict  # VoiceProfile.to_dict() shape
    rationale: str       # agent's reasoning, ≤ 500 chars


# ── Appearance models (AD-721d, extended AD-721d-1) ──────────────

class ProposeAppearanceRequest(BaseModel):
    """AD-721d + AD-721d-1: Captain revision note plus optional prior DSL.

    AD-721d-1: when ``previous_dsl`` is non-null AND ``captain_note`` is
    non-empty, this is a *revision* request. The server validates
    ``previous_dsl`` matches the ``AvatarDSL`` schema (rejects 422 if not)
    and increments the per-agent iteration counter. At
    ``AvatarsConfig.max_proposal_iterations`` the endpoint returns 429.

    ``captain_note`` IS the revision note — there is intentionally no
    separate ``revision_note`` field. The semantic difference between
    "initial proposal" and "revision" is carried by the presence of
    ``previous_dsl`` plus the existing iteration counter.
    """
    captain_note: str = ""
    previous_dsl: dict | None = None  # AD-721d-1


class ProposeAppearanceResponse(BaseModel):
    """AD-721d + AD-721d-1: Validated AvatarDSL plus iteration metadata."""
    agent_id: str
    dsl: dict
    proposal_iteration: int = 1   # AD-721d-1: 1-based; 1 for initial proposal
    max_iterations: int = 3       # AD-721d-1: echo of AvatarsConfig.max_proposal_iterations


class SetAppearanceRequest(BaseModel):
    """AD-721d: Persist an approved AvatarDSL to ``AppearanceProfile.dsl``.

    The endpoint re-validates ``dsl`` with ``AvatarDSL.model_validate(...)``
    before writing. Invalid → HTTP 422. AD-721d-1: on success, clears the
    in-memory proposal history for ``agent_id``.
    """
    dsl: dict


class PreviewAppearanceRequest(BaseModel):
    """AD-721d-3: render an unpersisted AvatarDSL to a draft VRM for Captain preview.

    Does NOT persist. Does NOT consume an iteration slot. Does NOT touch the
    canonical ``<avatars_dir>/<agent_id>.vrm`` cache. The endpoint writes the
    rendered bytes through ``AttachmentStore`` (SHA-256 ref per AD-731
    invariant) and returns ``{"attachment_id": "<sha>", ...}``.
    """
    dsl: dict


class ChatToolGrantRequest(BaseModel):
    """AD-720b: in-chat tool capability grant.

    Captain grants an agent scoped access to a registered tool (BrowserTool
    via AD-706, MCP servers via AD-449) from inside a DM, without leaving
    the chat surface. Persistence flows through the existing
    ``ToolPermissionStore.issue_grant`` so a grant issued here is
    indistinguishable on disk from one issued via ``/tool-access grant``.
    """
    agent_id: str = Field(..., min_length=1)
    tool_id: str = Field(..., min_length=1)
    permission: str = Field(..., description="ToolPermission enum value")
    duration_hours: float | None = Field(default=None, ge=0.0, le=720.0)
    reason: str = Field(default="", max_length=500)


# ── Vision-capability proposal models (AD-720d-2.1) ──────────────

class ProposeVisionCapability(BaseModel):
    """AD-720d-2.1: agent requests vision capability.

    Rationale must be non-empty and ≤280 chars — matches AD-718a /
    AD-721d-1 Captain-note budget.
    """
    rationale: str = Field(..., min_length=1, max_length=280)


class VisionCapabilityProposalResponse(BaseModel):
    """AD-720d-2.1: response to a propose call."""
    agent_id: str
    rationale: str
    proposal_id: str
    proposed_at: float


class ApproveVisionCapability(BaseModel):
    """AD-720d-2.1: Captain approve/deny payload."""
    approve: bool
    reason: str = Field(default="", max_length=280)


class MediateAppearanceRevision(BaseModel):
    """AD-721d-2: Captain-initiated request to route a revision hint through
    a mediator (typically the Counselor).
    """
    target_agent_id: str
    captain_hint: str = Field(..., min_length=1, max_length=280)


# ── Assignment models (AD-408) ───────────────────────────────────

class CreateAssignmentRequest(BaseModel):
    name: str
    assignment_type: str  # "bridge" | "away_team" | "working_group"
    members: list[str]    # agent_ids
    created_by: str = "captain"
    mission: str = ""


class ModifyMembersRequest(BaseModel):
    agent_id: str
    action: str = "add"  # "add" | "remove"


# ── Scheduled Task models (Phase 25a, AD-418) ────────────────────

class ScheduledTaskRequest(BaseModel):
    """Request to create a persistent scheduled task (Phase 25a)."""
    intent_text: str
    name: str = ""
    schedule_type: str = "once"   # once | interval | cron
    execute_at: float | None = None
    interval_seconds: float | None = None
    cron_expr: str | None = None
    channel_id: str | None = None
    max_runs: int | None = None
    created_by: str = "captain"
    webhook_name: str | None = None
    agent_hint: str | None = None            # AD-418


class UpdateAgentHintRequest(BaseModel):
    """AD-418: Update a scheduled task's agent_hint for routing bias."""
    agent_hint: str | None = None
