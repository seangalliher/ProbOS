"""ProbOS API request/response models (AD-516).

All Pydantic models extracted from api.py for use by routers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ── Chat models ───────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    response: str
    dag: dict[str, Any] | None = None
    results: dict[str, Any] | None = None


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
