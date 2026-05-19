"""AD-741: Single source of truth for the HXI Settings panel sections.

The 10 sections wired by AD-741 + the 11th (``perception``) inserted by
AD-733 in the same wave are listed in :data:`SECTIONS`. Every field id
resolves to a real Pydantic attribute path under
:class:`probos.config.SystemConfig`. The standing-rule guard against
phantom field references slipping into the registry between waves lives
in ``tests/test_ad741_section_registry.py``.

Secret-named fields (regex on the terminal segment of the dot-path) are
auto-redacted by :func:`is_secret_field_id`. See ``ad-741-settings-control-panel.md``
section "Secret-field rule" for the full contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

FieldKind = Literal[
    "text",
    "readonly",
    "enum",
    "bool",
    "int",
    "float",
    "secret_present_only",
]

Domain = Literal[
    "Core",
    "Perception & Voice",
    "Identity & Presentation",
    "Connectivity",
]


@dataclass(frozen=True)
class FieldDescriptor:
    """Per-field metadata for the Settings main panel."""

    field_id: str  # dot-path into SystemConfig, e.g. "system.log_level"
    label: str
    kind: FieldKind
    enum_values: tuple[str, ...] = ()
    description: str = ""
    hot_reload: bool = False  # v1: always False (forward marker AD-741-1)


@dataclass(frozen=True)
class SectionDescriptor:
    """Per-section metadata for the Settings sidebar + main panel."""

    section_id: str
    label: str
    glyph: str
    domain: Domain
    description: str
    fields: tuple[FieldDescriptor, ...] = ()


# Order matters: rendered top-to-bottom in the sidebar inside each domain
# group. Domain ordering is enforced separately in
# :func:`domain_render_order`.
SECTIONS: tuple[SectionDescriptor, ...] = (
    SectionDescriptor(
        section_id="system",
        label="System",
        glyph="◇",
        domain="Core",
        description="Process identity and global log level.",
        fields=(
            FieldDescriptor("system.name", "Process name", "text"),
            FieldDescriptor("system.version", "Version", "readonly"),
            FieldDescriptor(
                "system.log_level",
                "Log level",
                "enum",
                enum_values=("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"),
            ),
        ),
    ),
    SectionDescriptor(
        section_id="llm_tiers",
        label="LLM Tiers",
        glyph="✺",
        domain="Core",
        description=(
            "Per-tier LLM endpoints. Fast / standard / deep are text tiers; "
            "vision (AD-732) handles image observations; image_gen (AD-730-3) "
            "renders pictures. Each tier honest-degrades when unconfigured."
        ),
        fields=(
            FieldDescriptor("cognitive.llm_base_url_fast", "Fast tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_fast", "Fast tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_fast", "Fast tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_standard", "Standard tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_standard", "Standard tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_standard", "Standard tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_deep", "Deep tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_deep", "Deep tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_deep", "Deep tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_vision", "Vision tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_vision", "Vision tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_vision", "Vision tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_vision_fast", "Vision_fast tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_vision_fast", "Vision_fast tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_vision_fast", "Vision_fast tier — timeout (s)", "float"),
            FieldDescriptor("cognitive.llm_base_url_image_gen", "Image-gen tier — base URL", "text"),
            FieldDescriptor("cognitive.llm_model_image_gen", "Image-gen tier — model", "text"),
            FieldDescriptor("cognitive.llm_timeout_image_gen", "Image-gen tier — timeout (s)", "float"),
            FieldDescriptor(
                "cognitive.whisper_model_path",
                "Whisper model path",
                "text",
                description=(
                    "Path to ggml-tiny.en.bin under runtime.data_dir "
                    "(or absolute). Operator-pull via "
                    "scripts/whisper-tiny-en-fetch.ps1 (AD-721b-3). "
                    "Restart-required."
                ),
            ),
            FieldDescriptor(
                "cognitive.offline_stt_enabled",
                "Offline STT (whisper.cpp WASM)",
                "bool",
                description=(
                    "AD-705a: when enabled, the VAD-bounded utterance "
                    "is transcribed locally via the operator-pulled "
                    "whisper.cpp WASM artifacts. When disabled (default) "
                    "or artifacts absent, the browser-native "
                    "SpeechRecognition path remains primary."
                ),
                hot_reload=True,
            ),
        ),
    ),
    SectionDescriptor(
        section_id="memory",
        label="Memory",
        glyph="◈",
        domain="Core",
        description="Episodic memory retention and recall thresholds.",
        fields=(
            FieldDescriptor("memory.max_episodes", "Max episodes", "int"),
            FieldDescriptor("memory.relevance_threshold", "Relevance threshold", "float"),
            FieldDescriptor(
                "memory.agent_recall_threshold",
                "Agent recall threshold",
                "float",
                description="Per-agent semantic similarity floor (BF-134).",
            ),
            FieldDescriptor("memory.embedding_model", "Embedding model", "text"),
        ),
    ),
    SectionDescriptor(
        section_id="voice",
        label="Voice",
        glyph="≈",
        domain="Perception & Voice",
        description=(
            "Server-side TTS backend and lip-sync controls. The browser "
            "honest-degrades to SpeechSynthesisUtterance if Piper is unset."
        ),
        fields=(
            FieldDescriptor("tts.enabled", "TTS pipeline enabled", "bool"),
            FieldDescriptor(
                "tts.backend",
                "TTS backend",
                "enum",
                enum_values=("browser", "piper"),
            ),
            FieldDescriptor("tts.voice_model", "Piper voice model", "text"),
            FieldDescriptor("tts.length_scale", "Speech length scale", "float"),
            FieldDescriptor("tts.noise_scale", "Speech noise scale", "float"),
            FieldDescriptor("lipsync.enabled", "Lip-sync enabled", "bool"),
            FieldDescriptor(
                "lipsync.backend",
                "Lip-sync backend",
                "enum",
                enum_values=("heuristic", "rhubarb"),
            ),
            FieldDescriptor("lipsync.binary_path", "Rhubarb binary path", "text"),
        ),
    ),
    SectionDescriptor(
        section_id="avatars",
        label="Avatars",
        glyph="✿",
        domain="Identity & Presentation",
        description=(
            "3D crew avatar settings (VRM popout). Per-agent appearance "
            "lives in the Crew Roster — not duplicated here."
        ),
        fields=(
            FieldDescriptor("avatars.enabled", "Avatars enabled", "bool"),
            FieldDescriptor("avatars.avatars_dir", "Avatar assets directory", "text"),
            FieldDescriptor("avatars.max_vrm_size_bytes", "Max VRM size (bytes)", "int"),
            FieldDescriptor("avatars.renderer_enabled", "Headless Blender renderer", "bool"),
            FieldDescriptor(
                "avatars.fallback_to_parametric_on_error",
                "Fallback to parametric on error",
                "bool",
            ),
        ),
    ),
    SectionDescriptor(
        section_id="ward_room",
        label="Ward Room",
        glyph="◊",
        domain="Identity & Presentation",
        description=(
            "Ward Room conversation fabric. Hebbian router toggle lives "
            "alongside (top-level ward_room_hebbian block)."
        ),
        fields=(
            FieldDescriptor("ward_room.enabled", "Ward Room enabled", "bool"),
            FieldDescriptor("ward_room.max_thread_posts", "Max thread posts", "int"),
            FieldDescriptor("ward_room.dm_exchange_limit", "DM exchange limit", "int"),
            FieldDescriptor("ward_room.retention_days", "Retention (days)", "int"),
            FieldDescriptor("ward_room_hebbian.enabled", "Hebbian router enabled", "bool"),
        ),
    ),
    SectionDescriptor(
        section_id="federation",
        label="Federation",
        glyph="⊞",
        domain="Connectivity",
        description="Multi-node federation. Single-node is the default posture.",
        fields=(
            FieldDescriptor("federation.enabled", "Federation enabled", "bool"),
            FieldDescriptor("federation.node_id", "Node ID", "readonly"),
            FieldDescriptor("federation.bind_address", "Bind address", "text"),
        ),
    ),
    SectionDescriptor(
        section_id="channels",
        label="Channels",
        glyph="≣",
        domain="Connectivity",
        description=(
            "External chat-adapter bridges. Bot tokens and signing "
            "secrets are read-only here — edit system.yaml directly."
        ),
        fields=(
            FieldDescriptor("channels.discord.enabled", "Discord enabled", "bool"),
            FieldDescriptor("channels.discord.command_prefix", "Discord command prefix", "text"),
            FieldDescriptor(
                "channels.discord.mention_required",
                "Discord — mention required",
                "bool",
            ),
            FieldDescriptor("channels.discord.token", "Discord bot token", "secret_present_only"),
            FieldDescriptor("channels.slack.enabled", "Slack enabled", "bool"),
            FieldDescriptor(
                "channels.slack.default_thread_ts",
                "Slack — reply in threads by default",
                "bool",
            ),
            FieldDescriptor("channels.slack.bot_token", "Slack bot token", "secret_present_only"),
            FieldDescriptor(
                "channels.slack.signing_secret",
                "Slack signing secret",
                "secret_present_only",
            ),
            FieldDescriptor("channels.webhook.enabled", "Webhook adapter enabled", "bool"),
            FieldDescriptor(
                "channels.webhook.shared_secret",
                "Webhook shared secret",
                "secret_present_only",
            ),
        ),
    ),
    SectionDescriptor(
        section_id="cloud_pickers",
        label="Cloud Pickers",
        glyph="↑",
        domain="Connectivity",
        description=(
            "OAuth-bound cloud file pickers (Google Drive, OneDrive, Dropbox). "
            "Per-provider client_secret is read-only — edit system.yaml directly."
        ),
        fields=(
            FieldDescriptor("cloud_pickers.enabled", "Cloud pickers enabled", "bool"),
            FieldDescriptor("cloud_pickers.google_drive.enabled", "Google Drive enabled", "bool"),
            FieldDescriptor("cloud_pickers.google_drive.client_id", "Google Drive client ID", "text"),
            FieldDescriptor(
                "cloud_pickers.google_drive.client_secret",
                "Google Drive client secret",
                "secret_present_only",
            ),
            FieldDescriptor("cloud_pickers.onedrive.enabled", "OneDrive enabled", "bool"),
            FieldDescriptor("cloud_pickers.onedrive.client_id", "OneDrive client ID", "text"),
            FieldDescriptor(
                "cloud_pickers.onedrive.client_secret",
                "OneDrive client secret",
                "secret_present_only",
            ),
            FieldDescriptor("cloud_pickers.dropbox.enabled", "Dropbox enabled", "bool"),
            FieldDescriptor("cloud_pickers.dropbox.client_id", "Dropbox client ID", "text"),
            FieldDescriptor(
                "cloud_pickers.dropbox.client_secret",
                "Dropbox client secret",
                "secret_present_only",
            ),
        ),
    ),
    SectionDescriptor(
        section_id="tools",
        label="Tools",
        glyph="⚒",
        domain="Connectivity",
        description=(
            "Captain-facing tool integrations: Computer Use browser tool "
            "and MCP server bridge. Adding new MCP servers via the UI is "
            "forward marker AD-741-2."
        ),
        fields=(
            FieldDescriptor("browser_tool.enabled", "Browser tool enabled", "bool"),
            FieldDescriptor("browser_tool.headless", "Browser tool headless", "bool"),
            FieldDescriptor(
                "browser_tool.session_max_duration_seconds",
                "Browser session max duration (s)",
                "int",
            ),
            FieldDescriptor("mcp.enabled", "MCP bridge enabled", "bool"),
        ),
    ),
)


# Domain rendering order — frequency-of-use, not architectural layer.
_DOMAIN_ORDER: tuple[Domain, ...] = (
    "Core",
    "Perception & Voice",
    "Identity & Presentation",
    "Connectivity",
)

_SECRET_RE = re.compile(r"(?i)(secret|token|password|api_key|private_key)")


def is_secret_field_id(field_id: str) -> bool:
    """Return True when the *terminal* dot segment matches the secret regex.

    See AD-741 ``ad-741-settings-control-panel.md`` §"Secret-field rule".
    """
    if not field_id:
        return False
    terminal = field_id.rsplit(".", 1)[-1]
    return bool(_SECRET_RE.search(terminal))


def get_section(section_id: str) -> SectionDescriptor | None:
    """Return the descriptor for the given section_id, or None if not found."""
    for s in SECTIONS:
        if s.section_id == section_id:
            return s
    return None


def domain_counts() -> dict[str, int]:
    """Return a {domain: section_count} mapping for sidebar headers."""
    out: dict[str, int] = {}
    for s in SECTIONS:
        out[s.domain] = out.get(s.domain, 0) + 1
    return out


def domain_render_order() -> tuple[Domain, ...]:
    """Return the canonical rendering order of domain groups."""
    return _DOMAIN_ORDER


def resolve_dot_path(model: object, dotted: str) -> object:
    """Walk a dot-path against a Pydantic model. Raises AttributeError if missing.

    Used by both the section-registry test (guards against phantom field
    references) and the ``/api/config`` POST validator. Wide ``object``
    annotation keeps the helper test-friendly.
    """
    cursor: object = model
    for part in dotted.split("."):
        if not hasattr(cursor, part):
            raise AttributeError(
                f"AD-741 phantom field path: {dotted!r} (no attribute {part!r} on {type(cursor).__name__})"
            )
        cursor = getattr(cursor, part)
    return cursor


def insert_section(section: SectionDescriptor, *, before: str | None = None) -> None:
    """Append (or insert before another section) into the live registry.

    AD-733 calls this from ``probos.perception.__init__`` to add the
    ``perception`` section without bumping AD-741's own SECTIONS tuple.
    Idempotent on ``section_id`` — re-registration replaces the prior
    descriptor.
    """
    global SECTIONS
    if any(s.section_id == section.section_id for s in SECTIONS):
        SECTIONS = tuple(section if s.section_id == section.section_id else s for s in SECTIONS)
        return
    if before is not None:
        items: list[SectionDescriptor] = []
        inserted = False
        for s in SECTIONS:
            if not inserted and s.section_id == before:
                items.append(section)
                inserted = True
            items.append(s)
        if not inserted:
            items.append(section)
        SECTIONS = tuple(items)
    else:
        SECTIONS = SECTIONS + (section,)
