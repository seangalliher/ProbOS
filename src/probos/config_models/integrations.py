"""Federation, MCP and integration configuration models (AD-1270e2).

Batch 4 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator



class FederationMCPServerConfig(BaseModel):
    """AD-480a: Inbound MCP server — exposes ProbOS capabilities as MCP tools."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    path_prefix: str = "/mcp"


class MCPAppHostConfig(BaseModel):
    """AD-597 — MCP App Host configuration."""

    enabled: bool = False
    serve_internal_games: bool = True
    discover_external_apps: bool = False
    internal_default_csp: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    external_default_csp: str = (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    )
    bundles_dir: str = ""


class CredentialVaultConfig(BaseModel):
    """AD-706f: Browser Tool credential vault.

    Default-OFF transitional gate. Requires ``auth.crew_scope_token`` to be
    non-empty for KEK derivation; the runtime startup wires the vault only
    when both ``enabled=True`` AND the auth token is set.
    """

    enabled: bool = Field(
        default=False,
        description="AD-706f: enable encrypted credential vault. Default OFF.",
    )
    backend: str = Field(
        default="file",
        description=(
            "AD-706f/AD-1016: credential backend kind. "
            "'file' (default) = encrypted JSON vault (Fernet KEK from "
            "auth.crew_scope_token); 'keychain' = OS keychain (DPAPI / macOS "
            "Keychain / libsecret) with a non-secret metadata sidecar."
        ),
    )
    file_path: str = Field(
        default="data/credential_vault.json",
        description="AD-706f: JSON sidecar path for the EncryptedFileCredentialVault.",
    )
    keyring_index_path: str = Field(
        default="data/credential_keyring_index.json",
        description=(
            "AD-1016: non-secret metadata sidecar path for the keychain backend "
            "(holds scope/timestamps only — never a secret value)."
        ),
    )
    keyring_service_name: str = Field(
        default="probos.credentials",
        description=(
            "AD-1016: OS-keychain service name for the keychain backend "
            "(CredentialEncryptor namespace)."
        ),
    )
    max_credentials: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="AD-706f: per-vault hard cap on stored credentials.",
    )
    require_https_for_fill: bool = Field(
        default=True,
        description=(
            "AD-706f: when True, fill_credential blocks page.fill on http:// "
            "URLs. Operators override only for explicit dev/local scenarios."
        ),
    )

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, v: str) -> str:
        """AD-1016: only the file and keychain backends are supported."""
        valid = {"file", "keychain"}
        if v not in valid:
            raise ValueError(
                f"credential_vault.backend must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class AttachmentsConfig(BaseModel):
    """AD-720: chat attachments configuration.

    AD-720 v1 (Wave 135): image paste — 4 image MIMEs.
    AD-720a (Wave 139): file upload — 9 MIMEs (PDF, txt, md, json, csv added),
        plus three new fields consumed by AD-720d (commit N+1, same wave):
        ``vision_tier``, ``text_extraction_max_bytes``, ``pdf_extraction_enabled``.
    """

    enabled: bool = True                                   # stable feature, default-on
    # AD-731a-1: serve attachment bytes to authenticated federation peers.
    # Default-OFF. When True, ALSO requires auth.crew_scope_token to be set (the
    # endpoint 403s otherwise — never serve bytes through a pass-through gate).
    serve_remote_enabled: bool = False
    # AD-731a-1c: when True, a host that receives an IntentMessage referencing an
    # attachment SHA it lacks locally auto-fetches the bytes from the SENDER peer
    # (only when the sender is a configured a2a.outbound_peer with a matching
    # node_id). Default-OFF -> the resolver never runs (byte-identical).
    auto_resolve_remote_enabled: bool = False
    attachments_dir: str = "data/attachments"
    max_attachment_bytes: int = 10 * 1024 * 1024           # 10 MiB
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
            # AD-721b-1 (Wave 155): browser-captured utterance audio for the
            # rhubarb-lip-sync backend. Both mimes have unambiguous magic
            # bytes registered in attachments/mime.py._SIGNATURES; magic-byte
            # sniffing remains the primary correctness signal.
            "audio/webm",
            "audio/wav",
            # AD-720e (Wave 159): playback-only audio attachments (mpeg, m4a, ogg).
            # AttachmentStore stores bytes content-addressably (AD-731); browser
            # renders via <audio controls src=/api/chat/attachments/<sha>>.
            # Transcription is OUT OF SCOPE — AD-705a forward marker.
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg",
        ],
    )
    # AD-720a/AD-732: tier selection for vision-capable LLM dispatch.
    # Default changed from "standard" → "vision" in AD-732. Existing operator
    # configs that explicitly set vision_tier: "standard" still validate.
    vision_tier: str = "vision"
    # AD-720a: cap on bytes appended to the prompt by AD-720d's text extractor.
    text_extraction_max_bytes: int = 1 * 1024 * 1024       # 1 MiB
    # AD-720a: PDF text extraction is deferred to AD-720a-1 (needs pypdf).
    pdf_extraction_enabled: bool = False

    # AD-720d-1 (Wave 154): soft warning when a single vision turn includes
    # more than this many images. Log-only; never blocks or truncates.
    # Set to 0 to disable the warning entirely.
    multi_image_warn_threshold: int = 5

    # AD-730-2: hard cap on images per DM. When len(image_ids) exceeds
    # this, the handler returns HTTP 413. multi_image_warn_threshold
    # (soft warn) fires at 5; hard cap fires at 8 by default. Set to 0
    # to disable the hard cap (warning still fires).
    images_per_dm_hard_cap: int = 8

    # AD-730-2: downscale bounding box for inbound vision images. When
    # either image dimension exceeds this, the policy enforcer calls
    # PIL.Image.thumbnail to fit a (image_max_dimension, image_max_dimension)
    # box (aspect ratio preserved). The downscaled bytes are stored as a
    # NEW content-addressable ref; the ORIGINAL ref is preserved
    # (AD-731 invariant — refs are immutable). Set to 0 to disable
    # downscaling.
    image_max_dimension: int = 1024

    # AD-730-2: per-Captain daily image budget (rolling 24h window). When
    # the count of images included in DMs from this Captain in the last
    # 24h exceeds the budget, the handler returns HTTP 429 with a
    # Retry-After header. Tracking is in-memory (volatile across restart;
    # AD-730-2-1 forward marker for persistence). Set to 0 to disable
    # the budget gate entirely.
    daily_image_budget_per_captain: int = 50

    image_budget_path: str | None = Field(
        default=None,
        description=(
            "AD-730-2-1: filesystem path for the per-Captain image-budget "
            "JSON sidecar. When None, defaults to "
            "``<runtime.config.data_dir>/image_budget.json``."
        ),
    )

    # AD-730-5: per-agent_type vision tier override. Empty default means
    # no overrides; behavior identical to today (every agent uses
    # ``vision_tier``). Operator opts a specific agent type into a
    # specialized vision tier registered in the LLM client (e.g.
    # ``{"Diagnostician": "vision_medical"}``). When the override tier is
    # unknown to the LLM client at dispatch time, the helper logs a
    # warning and falls back to ``vision_tier`` (tier-2 log-and-degrade).
    vision_tier_overrides: dict[str, str] = Field(default_factory=dict)

    # AD-733-1: store-level LRU cap. Tier-2 safety net regardless of
    # which producer (chat paste, perception, browser tool, future
    # sensors) leaks. 0 disables the LRU pass; the age-TTL still runs.
    # Default 5 GiB matches typical operator dev-laptop free-space
    # budget; honest-degrade well before disk-full.
    max_store_bytes: int = Field(
        default=5 * 1024 * 1024 * 1024,
        ge=0,
        description=(
            "AD-733-1: total bytes ceiling for attachments_dir. Reaper "
            "evicts oldest perception_frame entries first, then oldest "
            "chat_attachment entries, until under cap. 0 = disabled."
        ),
    )

    @field_validator("vision_tier")
    @classmethod
    def _vision_tier_must_be_known(cls, v: str) -> str:
        allowed = {"fast", "standard", "deep", "vision"}
        if v not in allowed:
            raise ValueError(
                f"AD-720a/AD-732: vision_tier must be one of {sorted(allowed)}; got {v!r}"
            )
        return v


class CloudPickerProviderConfig(BaseModel):
    """AD-720c: per-provider OAuth client credentials. Operator-supplied (BYOC)."""

    enabled: bool = Field(default=False, description="AD-720c: enable this provider.")
    client_id: str = Field(default="", description="Operator-supplied OAuth client ID.")
    client_secret: str = Field(
        default="", description="Operator-supplied OAuth client secret."
    )
    redirect_uri: str = Field(
        default="http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback",
        description=(
            "AD-720c: OAuth redirect URI; must match the registration at the "
            "provider. {provider} is substituted with the provider id."
        ),
    )


class A2APeerConfig(BaseModel):
    """AD-480e: Outbound A2A peer registration entry."""

    peer_url: str
    auth_token: str = ""
    # AD-731a-1c: optional federation node_id this http-addressable A2A peer
    # corresponds to. Empty (default) = unmapped -> never an auto-resolution
    # source (byte-identical). Lets an inbound source_node map to a fetchable peer.
    node_id: str = ""


class FederationArdConfig(BaseModel):
    """AD-1040: ARD (Agentic Resource Discovery) integration. Default-OFF."""

    enabled: bool = False
    well_known_path: str = "/.well-known/ai-catalog.json"
    discovery_endpoints: list[str] = Field(default_factory=list)
    registry_url: str = ""
    publisher_namespace_domain: str = ""
    # AD-1049: discovery-before-design — when True the self-mod path SURFACES
    # existing ARD resources before designing a new agent (governance). Default
    # False keeps the runtime hook byte-identical (the call-site guard short-
    # circuits before any work runs).
    discovery_before_design: bool = False
    # AD-1050: federated ARD discovery mode. "none" (default) → no peer fetch
    # (byte-identical when off); "referrals" → fan out to a2a.outbound_peers;
    # "auto" honest-degrades to "referrals" in v1.
    federation_mode: Literal["none", "referrals", "auto"] = "none"
    # AD-1050: hard cap on referral peers fanned out per federated discovery.
    # 0 disables referral fan-out entirely.
    max_referral_peers: int = Field(default=5, ge=0, le=50)


class FederationPeerTrustConfig(BaseModel):
    """AD-480g: Probationary trust prior for federated peers."""

    probationary_alpha: float = Field(default=1.0, gt=0.0)
    probationary_beta: float = Field(default=3.0, gt=0.0)


class FederationTLSConfig(BaseModel):
    """AD-479f: Federation TLS surface (NATS pass-through in v1).

    Default-False. v1 wires the NATS path via ``nats_bus.config.tls``.
    ZeroMQ CURVE encryption is parked as AD-479l with explicit forcing
    function — AD-637e moved default federation traffic to NATS, so ZMQ
    TLS is downstream of "ZMQ becomes production transport again".
    """

    enabled: bool = False
    cert_file: str | None = None
    key_file: str | None = None
    ca_file: str | None = None
    verify_peer: bool = True


class FederationDiscoveryConfig(BaseModel):
    """AD-479h: Multicast peer discovery (opt-in, default-False).

    Raw UDP multicast on the local broadcast domain. Cross-LAN mDNS via
    ``zeroconf`` is parked as AD-479j.
    """

    multicast_enabled: bool = False
    multicast_group: str = "239.255.42.99"
    multicast_port: int = 5556
    announce_interval_seconds: float = 5.0


class FederationClusterMonitorConfig(BaseModel):
    """AD-479g: Cluster health monitor.

    Default-True (the gossip-driven liveness flag is purely additive — peers
    that never fall silent never get flagged unreachable). The two trip-wire
    EventTypes (``FEDERATION_PEER_UNREACHABLE`` / ``FEDERATION_PEER_RECOVERED``)
    are always-on observability when federation is enabled.
    """

    enabled: bool = True
    peer_unreachable_seconds: float = 60.0


class HooksConfig(BaseModel):
    """AD-1004: lifecycle-hook bus (deterministic interception at agent-loop
    points — the VS Code / Claude / Copilot hook model).

    The bus substrate always exists and is harmless when unwired (firing with no
    registered handlers is a no-op). This flag governs whether the runtime wires
    hooks into the live dispatch path + loads pack/operator hook handlers.
    **Default OFF** until handlers + wiring land in a follow-up slice.
    """

    enabled: bool = False


class PacksConfig(BaseModel):
    """AD-1003c: Capability Packs — installed-pack inventory directory.

    Points at the directory the AD-1003b scanner walks to report installed packs
    (the cross-tool agent-plugin format, AD-1003a). **Default OFF / read-only** —
    when disabled the inventory is empty; even when enabled, NOTHING is installed,
    loaded, or executed (that's the later loader slice). ``packs_dir`` is resolved
    relative to the runtime data dir when not absolute.
    """

    enabled: bool = False
    packs_dir: str = "data/packs"


class MCPServerConfig(BaseModel):
    """One MCP server registration entry (AD-449; AD-1014 stdio).

    Back-compat: existing ``{url, headers}`` entries default to ``type="http"``
    and are unaffected. ``type="stdio"`` (AD-1014) launches ``command + args`` as
    a subprocess (NDJSON JSON-RPC over stdin/stdout) instead of HTTP.
    """

    type: Literal["http", "stdio"] = "http"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""
    timeout_seconds: float | None = None
    # BF-750: the name this server is seeded into McpServerStore under, and so
    # the name its grants are keyed by (mcp:{name}, mcp:{name}:{tool}). Optional
    # -- derived from the transport identity when empty -- but an operator who
    # sets it gets a readable grant id instead of learn-microsoft-com-api-mcp.
    # Changing it after grants exist orphans them, so it is stable by contract.
    name: str = ""

    @model_validator(mode="after")
    def _validate_transport(self) -> "MCPServerConfig":
        if self.type == "http" and not self.url:
            raise ValueError("MCPServerConfig type='http' requires a non-empty 'url'")
        if self.type == "stdio" and not self.command:
            raise ValueError(
                "MCPServerConfig type='stdio' requires a non-empty 'command'"
            )
        return self


class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"


class CommunicationsConfig(BaseModel):
    """Communications settings (AD-485)."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior
    group_chat_min_rank: str = "commander"  # AD-924: min rank to open an ad-hoc group chat: ensign|lieutenant|commander|senior
    # AD-927: agent-authored [ARTIFACT] -> task-room Output pane.
    artifact_min_rank: str = "lieutenant"  # min rank to write an artifact into a task room: ensign|lieutenant|commander|senior
    artifact_max_per_turn: int = 3         # anti-flood: honor at most this many [ARTIFACT] tags per proactive turn
    artifact_max_bytes: int = 262144       # anti-flood: reject artifact bodies larger than 256 KiB (oversized -> honest-degrade)
    # AD-811a: agent-authored [A2UI] choice widget -> interactive card in the
    # 1:1 DM transcript. Default-OFF operator opt-in: when a2ui_enabled is
    # False (default) no agent is taught the tag and the pipeline step skips,
    # so behavior is byte-identical to pre-AD-811a.
    a2ui_enabled: bool = Field(
        default=False,
        description="AD-811a: enable the [A2UI] choice widget on the 1:1 DM path (default OFF -> byte-identical).",
    )
    a2ui_min_rank: str = Field(
        default="lieutenant",
        description="AD-811a: min rank to emit an [A2UI] choice widget: ensign|lieutenant|commander|senior",
    )
    a2ui_max_options: int = Field(
        default=10, ge=2, le=20,
        description="AD-811a: anti-flood cap on choice options honored per [A2UI] block (schema hard-caps at 20).",
    )
    # AD-1081: agent-driven room Todo checklist (the AD-1080 senior-validation
    # loop). Default-OFF operator opt-in: when room_todos_enabled is False no
    # agent is taught the tags and the pipeline step skips -> byte-identical.
    room_todos_enabled: bool = Field(
        default=False,
        description="AD-1081: enable [TODOS]/[TODO_DONE]/[TODO_CONFIRM]/[TODO_REJECT] room-task tags (default OFF).",
    )
    room_todos_min_rank: str = Field(
        default="commander",
        description="AD-1081: min rank to seed the plan + confirm/reject Todos (the senior/facilitator): ensign|lieutenant|commander|senior",
    )
    room_todos_seed_min_rank: str = Field(
        default="ensign",
        description="AD-1082: min rank to SEED the plan ([TODOS]) — open to any crew so the asked agent can plan; confirm/reject stay at room_todos_min_rank.",
    )
    # BF-646: backend for rendering agent-produced Office docs. "python-docx"
    # (default, zero-dep) or "libreoffice" (higher fidelity via headless soffice
    # convert-to; auto-degrades to python-docx if soffice is not installed).
    office_backend: str = Field(
        default="python-docx",
        description="BF-646: Office doc backend: python-docx (default) | libreoffice (headless soffice, higher fidelity, degrades if absent).",
    )
    libreoffice_path: str = Field(
        default="",
        description="BF-646: explicit soffice/soffice.exe path; empty = auto-detect on PATH.",
    )
    # AD-928: agent-authored [STATUS] -> task-room "show your work" activity.
    status_min_rank: str = "lieutenant"  # min rank to post a status into a task room: ensign|lieutenant|commander|senior
    status_max_per_turn: int = 3         # anti-flood: honor at most this many [STATUS] tags per proactive turn
    status_max_bytes: int = 4096         # anti-flood: reject status bodies larger than 4 KiB (oversized -> honest-degrade)
    # AD-930: presence "working" = an operation completed within this many
    # seconds (recent-activity proxy via AgentMeta.last_active; there is no
    # true in-flight signal at HEAD — AD-930a). Read-only/computed, so this
    # ships ON by default (not a transitional behavioral flag).
    presence_working_window_seconds: float = 90.0
    # AD-950: conversation-advancing ("proactivity") guidance on the live
    # 1:1/group direct_message reply path — teach agents to end an engaged turn
    # with ONE forward move (a follow-up question or proposal) so a conversation
    # has momentum instead of dying between Captain turns. Pure prompt text (no
    # extra LLM pass, no cost, no structural change), so it ships ON for the
    # richness the North Star demands; this is the Captain's tuning knob /
    # off-switch if the proactivity ever reads as over-eager.
    proactive_conversation_enabled: bool = True
    # AD-953: conversational memory & callbacks on the live 1:1/group
    # direct_message reply path — teach agents to draw on what they GENUINELY
    # recall (the episodic memories + session history already injected into the
    # reply context, AD-573/AD-723a-1) and make natural callbacks ("you mentioned
    # …", "last time we …") so a conversation feels continuous instead of
    # amnesiac, with a hard AD-592 honesty bound: reference only what is actually
    # recalled, never fabricate a shared memory. Pure prompt text (no extra LLM
    # pass, no cost), so it ships ON for the richness the North Star demands;
    # the Captain's tuning knob / off-switch if callbacks ever read as forced.
    conversational_memory_enabled: bool = True
    # AD-955: advisory room awareness on the group direct_message reply path —
    # surface the facilitator's per-speaker ranking (how much you've contributed
    # recently, whether the topic is your area, which peer the room would value
    # hearing) to the speaker so a dominating agent can hold back or hand off and
    # an agent can defer to a better-placed peer BY NAME (an AD-951 hand-off).
    # ADVISORY ONLY — it never changes who is dispatched; the cap/convergence
    # backstops are untouched. Pure prompt text (no cost), ships ON so the
    # Captain can observe self-selection emerge; the off-switch if the room ever
    # reads as over-deferential.
    room_awareness_enabled: bool = True
    # AD-980a: reflective recall interpretation. When enabled, an agent can run
    # an instructions-first LLM pass over its recalled memories to produce an
    # honesty-bounded *interpretation* ("what I make of this"), stored as an
    # agent-owned reflection episode. This is an EXTRA LLM pass (a real cost),
    # so unlike the pure-prompt-text knobs above it ships OFF — the Captain
    # enables it to exercise the meaning-making rung (AD-980).
    recall_interpretation_enabled: bool = False
    # AD-980c: dream interpretation loop. When enabled, an agent can interpret
    # ITS OWN dream — the per-agent dream reflections attributed by AD-980b —
    # and store the interpretation as an agent-owned episode that feeds its
    # self-model (the sleep->dream->wake->interpret loop). Requires AD-980b
    # attribution to have given the dream a dreamer. Extra LLM pass per agent
    # per dream, so ships OFF; the Captain enables the loop for the test.
    dream_interpretation_enabled: bool = False


class CommunicationBenchmarksConfig(BaseModel):
    """AD-642: Communication Quality Benchmarks configuration."""

    enabled: bool = True
    frequency_hours: float = 12.0
    probes: list[str] = [
        "thread_relevance",
        "memory_grounding",
        "memory_absence",
        "expertise",
        "silence_appropriateness",
        "dm_action",
    ]


class BillConfig(BaseModel):
    """Configuration for the Bill System runtime (AD-618b)."""

    # Maximum concurrent bill instances (0 = unlimited)
    max_concurrent_instances: int = 10

    # Default step timeout in seconds (0 = no timeout)
    default_step_timeout_seconds: float = 300.0

    # Whether to allow bills to activate with unfilled roles
    allow_partial_assignment: bool = False
