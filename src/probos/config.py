"""Configuration loader for ProbOS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Trust Threshold Constants ─────────────────────────────────────
# Canonical trust boundaries used across the system.
# Rank thresholds define promotion gates in crew_profile.py.
# Other thresholds reference these for consistency.

TRUST_SENIOR = 0.85        # Senior rank promotion threshold
TRUST_COMMANDER = 0.7      # Commander rank promotion threshold
TRUST_LIEUTENANT = 0.5     # Lieutenant rank promotion threshold
TRUST_DEFAULT = 0.5        # Default trust for new/unknown agents
TRUST_FLOOR_CONN = 0.6     # Minimum trust for Conn eligibility
TRUST_FLOOR_CREDIBILITY = 0.3  # Minimum credibility for channel creation
TRUST_DEGRADED = 0.2       # Agent degraded state threshold
TRUST_HARD_FLOOR = 0.05    # AD-558: Protective minimum — below this, negative updates silently absorbed
TRUST_OUTLIER_LOW = 0.3    # Trust outlier detection — low flag
TRUST_OUTLIER_HIGH = 0.9   # Trust outlier detection — high flag

# Display
TRUST_DISPLAY_PRECISION = 4  # Decimal places for trust/score display
TRUST_COLOR_GREEN = 0.6      # HXI trust color: green above this
TRUST_COLOR_YELLOW = 0.4     # HXI trust color: yellow above this

# Counselor assessment
COUNSELOR_TRUST_PROMOTION = 0.7    # Min trust for promotion fitness
COUNSELOR_WELLNESS_PROMOTION = 0.8  # Min wellness for promotion fitness
COUNSELOR_WELLNESS_YELLOW = 0.5    # Yellow alert wellness threshold
COUNSELOR_WELLNESS_FIT = 0.3       # Minimum wellness for fit-for-duty
COUNSELOR_CONFIDENCE_LOW = 0.3     # Low confidence concern threshold
COUNSELOR_TRUST_DRIFT_CONCERN = -0.2  # Significant trust drop

# ─── Cognitive JIT (AD-534) ───────────────────────────────────────
# Replay-first dispatch thresholds for procedural memory.

PROCEDURE_MATCH_THRESHOLD = 0.6     # Minimum semantic similarity for replay
PROCEDURE_MIN_COMPILATION_LEVEL = 2  # AD-535: Minimum Level 2 (Guided) for replay dispatch
PROCEDURE_MIN_SELECTIONS = 5        # Minimum selections before health diagnosis
PROCEDURE_HEALTH_FALLBACK_RATE = 0.4    # FIX diagnosis threshold
PROCEDURE_HEALTH_COMPLETION_RATE = 0.35  # FIX diagnosis (with applied > 0.4)
PROCEDURE_HEALTH_APPLIED_RATE = 0.4      # FIX diagnosis trigger
PROCEDURE_HEALTH_EFFECTIVE_RATE = 0.55   # DERIVED diagnosis threshold
PROCEDURE_HEALTH_DERIVED_APPLIED = 0.25  # DERIVED minimum applied_rate
EVOLUTION_COOLDOWN_SECONDS = 259200  # 72 hours — don't re-evolve same procedure within this window

# AD-532e: Reactive & proactive triggers
REACTIVE_COOLDOWN_SECONDS: int = 60       # Per-agent cooldown for reactive checks
PROACTIVE_SCAN_INTERVAL_SECONDS: int = 300  # 5 minutes between proactive scans
EVOLUTION_MAX_RETRIES: int = 3              # Max retry attempts for evolution

# AD-534b: Fallback learning
MAX_FALLBACK_RESPONSE_CHARS: int = 4000   # Truncation limit for LLM response in fallback events
MAX_FALLBACK_QUEUE_SIZE: int = 50         # Cap on in-memory fallback queue per dream cycle

# AD-534c: Multi-agent replay dispatch
COMPOUND_STEP_TIMEOUT_SECONDS: float = 10.0  # Per-step dispatch timeout

# AD-535: Graduated compilation
COMPILATION_PROMOTION_THRESHOLD: int = 3        # Consecutive successes to promote
COMPILATION_DEMOTION_LEVEL: int = 2              # Level to demote to on failure (Guided)
COMPILATION_MAX_LEVEL: int = 5                   # Maximum level (AD-537: Level 5 Expert unlocked)
COMPILATION_VALIDATION_TIMEOUT_SECONDS: float = 15.0  # LLM validation call timeout at Level 3
COMPILATION_TRUST_LEVEL_2_MIN: float = 0.0       # Ensign+ (any trust)
COMPILATION_TRUST_LEVEL_3_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)
COMPILATION_TRUST_LEVEL_4_MIN: float = 0.5       # Lieutenant+ (TRUST_LIEUTENANT)

# AD-536: Procedure Promotion
PROMOTION_MIN_COMPILATION_LEVEL: int = 4          # Must be Level 4+ to request promotion
PROMOTION_MIN_TOTAL_COMPLETIONS: int = 10          # Minimum successful completions
PROMOTION_MIN_EFFECTIVE_RATE: float = 0.7           # Minimum effective_rate
PROMOTION_REJECTION_COOLDOWN_HOURS: int = 72        # Anti-loop: no re-submit within 72h
PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD: str = "high"  # "high"/"critical" -> Captain
PROMOTION_DESTRUCTIVE_KEYWORDS: frozenset[str] = frozenset({
    "delete", "remove", "destroy", "reset", "drop", "purge", "force", "override",
})

# AD-537: Observational Learning
OBSERVATION_MIN_TRUST: float = 0.5               # Only observe agents with trust >= this
OBSERVATION_MAX_THREADS_PER_DREAM: int = 20       # Cap threads scanned per dream cycle
OBSERVATION_MIN_DETAIL_SCORE: float = 0.6         # LLM-assessed actionability threshold
OBSERVATION_WARD_ROOM_LOOKBACK_HOURS: float = 24  # Scan threads from last N hours
TEACHING_MIN_COMPILATION_LEVEL: int = 5           # Must be Level 5 to teach
TEACHING_MIN_TRUST: float = 0.85                  # Must be Commander+ trust to teach

# AD-538: Procedure Lifecycle
LIFECYCLE_DECAY_DAYS: int = 30                  # Unused for this many days → lose 1 compilation level
LIFECYCLE_ARCHIVE_DAYS: int = 90                # Unused at Level 1 for this many days → archived
LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD: float = 0.85  # ChromaDB cosine similarity → flag as duplicate
LIFECYCLE_DEDUP_MAX_CANDIDATES: int = 50        # Max procedures to scan for dedup per dream
LIFECYCLE_REVALIDATION_LEVEL: int = 2           # Decayed procedures drop to this level (Guided)
LIFECYCLE_MIN_SELECTIONS_FOR_DECAY: int = 3     # Don't decay procedures that haven't had a fair chance

# AD-539: Gap → Qualification Pipeline
GAP_MIN_FAILURE_RATE: float = 0.30         # Cluster failure rate threshold for gap detection
GAP_MIN_EPISODES: int = 5                  # Minimum episodes in cluster to qualify as gap evidence
GAP_MIN_PROCEDURE_FAILURES: int = 3        # Minimum procedure failures to constitute a gap
GAP_PROFICIENCY_TARGET: int = 3            # Target ProficiencyLevel (APPLY) for gap closure
GAP_REPORT_MAX_PER_DREAM: int = 10         # Cap gap reports per dream cycle


def format_trust(value: float, precision: int = TRUST_DISPLAY_PRECISION) -> float:
    """Round a trust/score value for display. Centralizes precision."""
    return round(value, precision)


class PoolConfig(BaseModel):
    """Agent pool configuration."""

    default_pool_size: int = 3
    max_pool_size: int = 7
    min_pool_size: int = 2
    spawn_cooldown_ms: int = 500
    health_check_interval_seconds: float = 5.0


class MeshConfig(BaseModel):
    """Mesh communication configuration."""

    gossip_interval_ms: int = 1000
    hebbian_decay_rate: float = 0.995
    # AD-571c v1: per-rel_type decay. SOCIAL weights persist longer than intent-routing
    # weights. Default falls back to hebbian_decay_rate so v1 is behavior-equivalent;
    # AD-571c-i forcing function flips this to 0.999 once AD-557 benchmarks land.
    hebbian_social_decay_rate: float = 0.995
    # AD-428b v1: Map intent_id -> skill_id for skill-weighted routing.
    # Empty dict (default) means skill weighting is off; the router returns
    # base_weight unchanged. Reread per call so config reload picks up changes.
    intent_skill_map: dict[str, str] = Field(default_factory=dict)
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0
    semantic_matching: bool = True  # Enable semantic matching in CapabilityRegistry


class ConsensusConfig(BaseModel):
    """Consensus layer configuration."""

    min_votes: int = 3
    approval_threshold: float = 0.6
    use_confidence_weights: bool = True
    verification_timeout_seconds: float = 5.0
    red_team_pool_size: int = 2
    trust_prior_alpha: float = 2.0  # Beta distribution prior successes
    trust_prior_beta: float = 2.0  # Beta distribution prior failures
    trust_decay_rate: float = 0.999  # Slow decay of trust observations


class CognitiveConfig(BaseModel):
    """Cognitive layer configuration."""

    # Shared endpoint (backward compat — used when per-tier not specified)
    llm_base_url: str = "http://127.0.0.1:8080/v1"  # OpenAI-compatible endpoint
    llm_api_key: str = ""
    llm_timeout_seconds: float = 30.0

    # Per-tier model names (existing)
    llm_model_fast: str = "claude-sonnet-4-6"
    llm_model_standard: str = "claude-sonnet-4-6"
    llm_model_deep: str = "claude-opus-4-6"

    # BF-240: Dwell-time criterion for LLM health recovery
    llm_health_min_consecutive_healthy: int = 3  # Consecutive successes before tier transitions to operational

    @field_validator("llm_health_min_consecutive_healthy")
    @classmethod
    def _validate_min_consecutive_healthy(cls, v: int) -> int:
        if v < 1:
            raise ValueError("llm_health_min_consecutive_healthy must be >= 1")
        return v

    @model_validator(mode="after")
    def _apply_env_overrides(self) -> "CognitiveConfig":
        """Docker-friendly: allow PROBOS_LLM_URL to override default LLM endpoint."""
        url = os.environ.get("PROBOS_LLM_URL")
        if url:
            self.llm_base_url = url
        return self

    # Per-tier endpoint overrides (None = fall back to shared)
    llm_base_url_fast: str | None = None
    llm_api_key_fast: str | None = None
    llm_timeout_fast: float | None = None
    llm_api_format_fast: str | None = None  # "openai" or "ollama"

    llm_base_url_standard: str | None = None
    llm_api_key_standard: str | None = None
    llm_timeout_standard: float | None = None
    llm_api_format_standard: str | None = None

    llm_base_url_deep: str | None = None
    llm_api_key_deep: str | None = None
    llm_timeout_deep: float | None = None
    llm_api_format_deep: str | None = None

    # AD-732: vision tier — fourth peer of fast/standard/deep. Default
    # unconfigured. Operators uncomment the config/system.yaml block
    # (or set values here) to enable image-aware DMs. When unconfigured
    # OR unhealthy, image attachments degrade to the honest-degrade
    # message (see vision_dispatch.VISION_UNCONFIGURED_MESSAGE /
    # VISION_UNHEALTHY_MESSAGE). Vision does NOT participate in the
    # fast→standard→deep fallback chain (standard/deep can't see images).
    llm_base_url_vision: str | None = None
    llm_api_key_vision: str | None = None
    llm_model_vision: str | None = None
    llm_timeout_vision: float | None = None
    llm_api_format_vision: str | None = None  # "openai" or "ollama"

    # AD-706c-2: compute_use tier — fifth peer of fast/standard/deep/vision.
    # Coordinate-aware image LLM for DOM-less surfaces (canvas, embedded VNC,
    # screenshot-only PDFs). Default unconfigured; opt-in via system.yaml.
    # When unconfigured OR unhealthy, BrowserTool ``compute_use_click``
    # honest-degrades with the shared VISION_UNCONFIGURED_MESSAGE.
    # Does NOT participate in the fast→standard→deep fallback chain.
    llm_base_url_compute_use: str | None = None
    llm_api_key_compute_use: str | None = None
    llm_model_compute_use: str | None = None
    llm_timeout_compute_use: float | None = None
    llm_api_format_compute_use: str | None = None  # "openai" or "ollama"
    llm_temperature_compute_use: float | None = None
    llm_top_p_compute_use: float | None = None
    llm_max_tokens_compute_use: int | None = None

    # AD-742a (Wave 174): vision_fast tier — small-VLM peer of AD-732 vision.
    # Per-frame supervisor-flagged describe calls (~400-800ms target) instead
    # of the 27B narrative-tier model. Default unconfigured; opt-in via
    # system.yaml. When unconfigured OR unhealthy, VisionConsumer._describe
    # falls back to the AD-732 vision tier (NOT to text tiers).
    # ModelRouter bypassed (BF-273 lesson). Does NOT participate in the
    # fast→standard→deep fallback chain (BF-269 lesson).
    # Suggested default: moondream (Apache 2.0, 1.8B, Ollama-pullable).
    llm_base_url_vision_fast: str | None = None
    llm_api_key_vision_fast: str | None = None
    llm_model_vision_fast: str | None = None
    llm_timeout_vision_fast: float | None = None
    llm_api_format_vision_fast: str | None = None  # "openai" or "ollama"

    # AD-721b-3 (Wave 179): operator-pulled Whisper tiny.en GGML model
    # path. Relative paths resolve against ``runtime.data_dir``; absolute
    # paths are used as-is. The default points at the location
    # ``scripts/whisper-tiny-en-fetch.ps1`` writes to. AD-705a consumes
    # this via the browser-side whisperLoader; AD-705c reserves a future
    # negative-sample augmentation hook. Restart-required (the loader
    # caches the path at boot).
    # BF-301: DEPRECATED. The whisper.cpp WASM artifact pipeline this
    # path was created for is abandoned upstream. Retained for one
    # release cycle; air-gapped operators may use it in a future AD to
    # pre-warm the transformers.js Cache API. New deployments should
    # ignore this field and rely on transformers.js's HF CDN fetch.
    whisper_model_path: str = "whisper/ggml-tiny.en.bin"

    # AD-705a (Wave 179): offline STT toggle. Default OFF (convention
    # #14 — opt-in until operators pull the whisper.cpp WASM artifacts
    # via ``scripts/whisper-tiny-en-fetch.ps1``). When True AND the
    # browser whisperLoader successfully loads the operator-pulled
    # artifacts, the AD-733c-7-5 VAD-bounded utterance is transcribed
    # locally and dispatched through the existing IntentSurface keyboard
    # path. When False (default) OR artifacts absent, the browser-native
    # ``SpeechRecognition`` path remains primary (AD-705 v1 fallback —
    # cloud-routed on Chrome; privacy-conscious operators set this to
    # True AND disable the wake-word loop to go fully offline).
    # Hot-reload via the BF-308 settings watcher.
    offline_stt_enabled: bool = False

    # AD-826 — Primary STT engine. ``whisper`` (default) routes PTT and
    # conversation-mode utterances through the AD-705a browser-side
    # whisper.cpp WASM path first; browser ``SpeechRecognition`` is the
    # fallback (mirror image of AD-760's empty-counter logic). Set to
    # ``browser`` to preserve pre-AD-826 behavior (browser SR primary,
    # whisper after 2 empty transcripts). Hot-reload.
    primary_stt: Literal["transformers", "whisper", "browser"] = Field(
        default="transformers",
        description=(
            "BF-301 (was AD-826): which STT engine the UI PTT handler "
            "arms first. transformers = local @huggingface/transformers "
            "Whisper running in a Web Worker (cross-browser, no operator "
            "setup, default since BF-301). whisper = DEPRECATED alias "
            "for transformers — retained for back-compat with saved "
            "operator configs; resolves to engine='transformers' in "
            "the health endpoint. browser = Web Speech API (Chrome-only "
            "reliable; flaky on Edge/Firefox/Safari). When transformers "
            "is selected AND offline_stt_enabled is False, the UI "
            "honest-degrades to the browser engine. Hot-reload."
        ),
    )
    # BF-301 (#775): transformers.js Whisper model id. The browser-side
    # @huggingface/transformers pipeline fetches the ONNX shards from HF
    # CDN on first use and caches them in the browser's Cache API.
    # Defaults to ``Xenova/whisper-tiny.en`` (~40 MB, English-only,
    # lowest-latency tier with usable PTT accuracy). Operators on
    # high-bandwidth machines can swap to ``Xenova/whisper-base.en`` for
    # better accuracy at ~150 MB. The runtime does NOT validate the model
    # id against the HF hub — typos surface as a model-load failure in
    # the browser (the UI honest-degrades to browser SR). Hot-reload.
    transformers_model: str = Field(
        default="Xenova/whisper-tiny.en",
        description=(
            "BF-301: HuggingFace model id for the browser-side "
            "transformers.js ASR pipeline. Browser fetches and caches; "
            "the runtime never holds the weights. Hot-reload."
        ),
    )
    # AD-826: enable the cross-engine fallback (whisper→browser when
    # primary=whisper, browser→whisper when primary=browser). Defaults
    # to True; set False to lock the primary engine with no cross-over.
    fallback_stt_enabled: bool = Field(
        default=True,
        description=(
            "AD-826: when True, two consecutive empty transcripts from "
            "the primary STT engine fall through to the other engine "
            "for the next press. When False, the primary engine is the "
            "only path and empty transcripts are surfaced as-is. "
            "Hot-reload."
        ),
    )

    # AD-747 — Always-on conversation mode (LiveKit VoicePipelineAgent
    # pattern absorbed Apache 2.0). When ON and a DM thread is active,
    # the ConversationController acquires PRIORITY_CONVERSATION on the
    # BF-318 arbiter, gates STT by VAD, auto-submits transcripts to the
    # open DM agent, and supports barge-in (VAD speech_start during TTS
    # interrupts the agent's playback). Default-OFF (Wave 10 convention
    # #14 transitional gate); press-to-talk continues to work either
    # way. Hot-reload.
    conversation_mode_enabled: bool = Field(default=False,
        description=(
            "AD-747: when ON, opening a DM thread arms an always-on "
            "conversation. Default OFF; press-to-talk preserved. "
            "Hot-reload."
        ),
    )
    conversation_silence_timeout_ms: int = Field(default=30000, ge=1000, le=300000,
        description=(
            "AD-747: silence-timeout in ms after the agent's TTS reply "
            "finishes; expiry disarms the conversation and returns to "
            "wake-word. 30000 matches ChatGPT advanced voice mode. "
            "Hot-reload."
        ),
    )
    conversation_barge_in_enabled: bool = Field(default=True,
        description=(
            "AD-747: when ON, VAD speech_start during agent_speaking "
            "stops the TTS mid-utterance and re-arms STT. Operators in "
            "noisy environments can disable; AD-747-1 forward marker "
            "for prosody-gated barge-in. Hot-reload."
        ),
    )

    # AD-730-3: image_gen tier — sixth peer of fast/standard/deep/vision/
    # compute_use. Image generation via OpenAI-compatible
    # POST /v1/images/generations (DALL-E 3 / gpt-image-1 / local SD via
    # ComfyUI/A1111 OpenAI-shape adapter). Default unconfigured; opt-in
    # via system.yaml. When unconfigured OR unhealthy, agent
    # [GEN_IMAGE ...] markers honest-degrade to silent strip.
    # Does NOT participate in the fast→standard→deep fallback chain
    # (text tiers can't generate images, per BF-269 lesson).
    # ModelRouter bypassed at call site (BF-273 lesson).
    # LLMResponseCache bypassed (BF-272 lesson).
    llm_base_url_image_gen: str | None = None
    llm_api_key_image_gen: str | None = None
    llm_model_image_gen: str | None = None
    llm_timeout_image_gen: float | None = None
    llm_api_format_image_gen: str | None = None  # "openai" (only supported shape)

    # Per-tier sampling overrides (None = use request-level value)
    llm_temperature_fast: float | None = None
    llm_temperature_standard: float | None = None
    llm_temperature_deep: float | None = None
    llm_temperature_vision: float | None = None

    llm_top_p_fast: float | None = None
    llm_top_p_standard: float | None = None
    llm_top_p_deep: float | None = None
    llm_top_p_vision: float | None = None

    # Per-tier max_tokens overrides (None = use request-level value).
    # Useful for thinking models (qwen3.6, gpt-5.x-thinking, claude-extended-
    # thinking) where the reasoning trace eats the token budget before the
    # final answer is produced. Bumping vision to 8192+ on a 32K-context model
    # gives the model room to think AND produce a complete reply.
    llm_max_tokens_fast: int | None = None
    llm_max_tokens_standard: int | None = None
    llm_max_tokens_deep: int | None = None
    llm_max_tokens_vision: int | None = None

    # AD-835 (Wave 202): per-tier system-prompt suffix. None = no-op (the
    # composed system message is byte-identical to pre-AD-835 behaviour).
    # When set, the LLM client appends this text to the system message of
    # any call routed to that tier — the seam by which a tier can carry a
    # terse harness adaptation (e.g. a deep-tier reasoning preamble, or a
    # vision-tier "describe only what is visible" guard) without the caller
    # knowing which tier it landed on. Follows the ATTEMPT tier during
    # fallback (the suffix that ships is the one for the tier that actually
    # served the request). Never applied to user or tool messages.
    llm_system_prompt_suffix_fast: str | None = None
    llm_system_prompt_suffix_standard: str | None = None
    llm_system_prompt_suffix_deep: str | None = None
    llm_system_prompt_suffix_vision: str | None = None

    # Default tier for LLM requests ("fast", "standard", or "deep")
    default_llm_tier: str = "fast"

    # Ollama keep_alive: how long the model stays loaded after the last request.
    # Prevents cold-start delays when Ollama unloads idle models.
    # Examples: "5m", "30m", "1h", "-1" (forever). Default "30m".
    ollama_keep_alive: str = "30m"

    working_memory_token_budget: int = 4000
    decomposition_timeout_seconds: float = 30.0
    dag_execution_timeout_seconds: float = 60.0
    use_consensus_for_writes: bool = True
    max_concurrent_tasks: int = 8
    attention_decay_rate: float = 0.95  # Per-second decay for stale tasks
    focus_history_size: int = 10
    background_demotion_factor: float = 0.25

    def tier_config(self, tier: str) -> dict:
        """Return resolved endpoint config for a tier.

        Returns {"base_url": str, "api_key": str, "model": str, "timeout": float}
        with per-tier overrides applied, falling back to shared values.
        """
        model_map = {
            "fast": self.llm_model_fast,
            "standard": self.llm_model_standard,
            "deep": self.llm_model_deep,
            "vision": self.llm_model_vision,
            "vision_fast": self.llm_model_vision_fast,
            "compute_use": self.llm_model_compute_use,
            "image_gen": self.llm_model_image_gen,
        }
        url_map = {
            "fast": self.llm_base_url_fast,
            "standard": self.llm_base_url_standard,
            "deep": self.llm_base_url_deep,
            "vision": self.llm_base_url_vision,
            "vision_fast": self.llm_base_url_vision_fast,
            "compute_use": self.llm_base_url_compute_use,
            "image_gen": self.llm_base_url_image_gen,
        }
        key_map = {
            "fast": self.llm_api_key_fast,
            "standard": self.llm_api_key_standard,
            "deep": self.llm_api_key_deep,
            "vision": self.llm_api_key_vision,
            "vision_fast": self.llm_api_key_vision_fast,
            "compute_use": self.llm_api_key_compute_use,
            "image_gen": self.llm_api_key_image_gen,
        }
        timeout_map = {
            "fast": self.llm_timeout_fast,
            "standard": self.llm_timeout_standard,
            "deep": self.llm_timeout_deep,
            "vision": self.llm_timeout_vision,
            "vision_fast": self.llm_timeout_vision_fast,
            "compute_use": self.llm_timeout_compute_use,
            "image_gen": self.llm_timeout_image_gen,
        }
        format_map = {
            "fast": self.llm_api_format_fast,
            "standard": self.llm_api_format_standard,
            "deep": self.llm_api_format_deep,
            "vision": self.llm_api_format_vision,
            "vision_fast": self.llm_api_format_vision_fast,
            "compute_use": self.llm_api_format_compute_use,
            "image_gen": self.llm_api_format_image_gen,
        }
        temp_map = {
            "fast": self.llm_temperature_fast,
            "standard": self.llm_temperature_standard,
            "deep": self.llm_temperature_deep,
            "vision": self.llm_temperature_vision,
            "vision_fast": None,
            "compute_use": self.llm_temperature_compute_use,
            "image_gen": None,
        }
        top_p_map = {
            "fast": self.llm_top_p_fast,
            "standard": self.llm_top_p_standard,
            "deep": self.llm_top_p_deep,
            "vision": self.llm_top_p_vision,
            "vision_fast": None,
            "compute_use": self.llm_top_p_compute_use,
            "image_gen": None,
        }
        max_tokens_map = {
            "fast": self.llm_max_tokens_fast,
            "standard": self.llm_max_tokens_standard,
            "deep": self.llm_max_tokens_deep,
            "vision": self.llm_max_tokens_vision,
            "vision_fast": None,
            "compute_use": self.llm_max_tokens_compute_use,
            "image_gen": None,
        }
        # AD-835: per-tier system-prompt suffix (None = no per-tier suffix).
        suffix_map = {
            "fast": self.llm_system_prompt_suffix_fast,
            "standard": self.llm_system_prompt_suffix_standard,
            "deep": self.llm_system_prompt_suffix_deep,
            "vision": self.llm_system_prompt_suffix_vision,
        }
        return {
            "base_url": url_map.get(tier) or self.llm_base_url,
            "api_key": key_map.get(tier) if key_map.get(tier) is not None else self.llm_api_key,
            "model": model_map.get(tier, self.llm_model_standard),
            "timeout": timeout_map.get(tier) if timeout_map.get(tier) is not None else self.llm_timeout_seconds,
            "api_format": format_map.get(tier) or "openai",
            "temperature": temp_map.get(tier),   # None = use request default
            "top_p": top_p_map.get(tier),        # None = don't send
            "max_tokens": max_tokens_map.get(tier),  # None = use request default
            "system_prompt_suffix": suffix_map.get(tier),  # AD-835: None = no-op
        }

    # AD-739: Captain Card — operator self-card always-in-context.
    captain_card_enabled: bool = Field(
        default=True,
        description=(
            "AD-739: inject the Captain Card into CognitiveAgent system "
            "prompts. Default ON — the Card is a benign context anchor."
        ),
    )
    captain_card_path: str = Field(
        default="captain_card.json",
        description=(
            "AD-739: relative path under runtime.data_dir for the "
            "Captain Card JSON sidecar."
        ),
    )
    captain_card_max_tokens: int = Field(
        default=500,
        ge=100,
        le=1500,
        description=(
            "AD-739: token budget for the rendered Card text injected "
            "into system prompts. Approximated as max chars / 4."
        ),
    )
    captain_card_refresh_min_interval_seconds: int = Field(
        default=3600,
        ge=60,
        description=(
            "AD-739: minimum interval between Dreaming-driven Card refreshes."
        ),
    )

    # AD-797 (Wave 197): minimum line count for a fenced code block to be
    # extracted as an artifact. Below this threshold, fenced blocks stay
    # inline in the chat scrollback. Default 40 — short snippets read
    # better inline; long files belong in the drawer.
    artifact_fenced_threshold_lines: int = Field(
        default=40,
        ge=10,
        description=(
            "AD-797: fenced code block line-count threshold for artifact "
            "extraction. Blocks shorter than this stay inline."
        ),
    )


class SubTaskConfig(BaseModel):
    """AD-632a: Sub-task protocol configuration."""

    enabled: bool = True                       # AD-632f: MVP chain complete, enabled by default
    chain_timeout_ms: int = 30000              # Default chain timeout (30s)
    step_timeout_ms: int = 15000               # Default per-step timeout (15s)
    max_chain_steps: int = 6                   # Maximum steps per chain (defense in depth)
    fallback_on_timeout: str = "single_call"   # Degradation strategy
    max_concurrent_chains: int = 4             # AD-636: Cap simultaneous chain executions
    nats_publish_enabled: bool = False         # AD-641g: opt-in chain step publish to NATS
    nats_payload_max_bytes: int = 16384        # AD-641g: cap on result-dict serialized size


class BootCampConfig(BaseModel):
    """AD-638: Cold-start boot camp configuration."""

    enabled: bool = True
    min_episodes: int = 5
    min_ward_room_posts: int = 3
    min_dm_conversations: int = 1
    min_trust_score: float = 0.55
    min_time_minutes: int = 60
    timeout_minutes: int = 120
    nudge_cooldown_seconds: int = 600


class ShipStateSnapshotConfig(BaseModel):
    """AD-683: Ship State Snapshot for Cold-Start Onboarding."""

    enabled: bool = True


class TieredTrustConfig(BaseModel):
    """AD-640: Role-based trust initialization tiers."""

    enabled: bool = True

    # Bridge tier (Captain, First Officer, Counselor)
    bridge_alpha: float = 4.5
    bridge_beta: float = 1.0

    # Department Chief tier
    chief_alpha: float = 3.0
    chief_beta: float = 1.0

    # Crew tier uses existing consensus priors — no separate config needed.

    # Callsigns in each tier.
    bridge_pools: list[str] = ["counselor", "yeoman"]
    bridge_callsigns: list[str] = ["Meridian", "Yeo"]
    chief_callsigns: list[str] = ["Bones", "LaForge", "Number One", "Worf", "O'Brien"]


class ChainTuningConfig(BaseModel):
    """AD-639: Trust-adaptive chain personality tuning."""

    enabled: bool = True

    # Trust band thresholds
    low_trust_ceiling: float = 0.60   # Below this: skip evaluate/reflect
    high_trust_floor: float = 0.75    # At or above: full chain as-is
    # Mid band is implicitly [low_trust_ceiling, high_trust_floor)


class ChainOptimizerConfig(BaseModel):
    """AD-659 v1 + AD-659b: Cognitive Chain Self-Optimization service.

    v1 (AD-659) shipped analysis-only proposal generation + Captain approval
    REST surface. AD-659b adds the apply path (gated by `apply_enabled`),
    SQLite persistence, dedup keyed on (detector_name, target_parameter),
    manual revert, and an opt-in scheduled analyze loop.

    Both new flags default OFF. `apply_enabled=True` grants live-mutation
    authority over `chain_tuning.low_trust_ceiling` / `high_trust_floor`.
    `analysis_interval_seconds > 0` enables periodic background analysis.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20
    apply_enabled: bool = False  # AD-659b: apply path gate (default OFF)
    analysis_interval_seconds: int = 0  # AD-659b: 0 disables scheduled loop

    @field_validator("analysis_interval_seconds")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 0:
            raise ValueError("analysis_interval_seconds must be >= 0")
        return v


class ChainOptimizerCounselorConfig(BaseModel):
    """AD-659c v1: OptimizationCounselor watchdog for AD-659b applied proposals.

    Default-OFF (Wave-10 convention #14). Captain opts in once AD-659b apply
    has accumulated production data and detection accuracy is validated.

    `auto_revert_enabled` is a SECOND gate — the watchdog can be enabled to
    only observe + record decisions (no destructive action) without granting
    revert authority. Captain flips auto_revert separately once observed
    decisions look correct.
    """

    enabled: bool = False
    baseline_window_seconds: float = 1800.0       # 30 min
    observation_window_seconds: float = 1800.0    # 30 min
    success_rate_drop_floor: float = 0.10         # 10% absolute drop
    min_samples_per_window: int = 20
    auto_revert_enabled: bool = False             # SECOND gate

    @field_validator(
        "baseline_window_seconds",
        "observation_window_seconds",
    )
    @classmethod
    def _validate_window(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError("window seconds must be > 0")
        return v

    @field_validator("success_rate_drop_floor")
    @classmethod
    def _validate_drop_floor(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("success_rate_drop_floor must be in [0.0, 1.0]")
        return v

    @field_validator("min_samples_per_window")
    @classmethod
    def _validate_min_samples(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_per_window must be >= 1")
        return v


class DiagnosticContextConfig(BaseModel):
    """AD-661 v1 + AD-661b/c: Diagnostic Context Service — pull-based bundle assembly.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `assemble()`. See AD-661 prompt for the convention deviation rationale.

    AD-661b adds a 4th allocation tier (`records_ratio`) for Ship's Records
    (AD-434). The synthetic system-context reader naturally surfaces only
    ship/fleet records; per-agent record authorization is deferred (AD-661f).

    AD-661c adds `redistribute_remainder` (default True): unused budget from
    under-filled tiers is redistributed to other tiers in priority order
    (chain_traces > procedures > episodes > records) while candidates remain.
    """

    enabled: bool = True
    default_budget_tokens: int = 8000
    chain_trace_ratio: float = 0.30
    procedure_ratio: float = 0.25
    episode_ratio: float = 0.25
    records_ratio: float = 0.20
    chars_per_token: int = 4
    redistribute_remainder: bool = True

    @field_validator(
        "chain_trace_ratio", "procedure_ratio", "episode_ratio", "records_ratio",
    )
    @classmethod
    def _ratio_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("ratio must be in [0.0, 1.0]")
        return v

    @model_validator(mode="after")
    def _ratios_sum_to_one(self) -> "DiagnosticContextConfig":
        total = (
            self.chain_trace_ratio
            + self.procedure_ratio
            + self.episode_ratio
            + self.records_ratio
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"ratios must sum to 1.0 (±0.01); got {total:.4f}"
            )
        return self


class CausalReasoningConfig(BaseModel):
    """AD-660 v1 + AD-660b: Agent Causal Reasoning Framework.

    v1 (AD-660) shipped the four-step template + journal storage + opt-in
    counselor concern hook. AD-660b flips the default ON, adds AD-557
    emergence-warning hooks (groupthink + fragmentation) on the same path,
    introduces hypothesis ranking + recommended-action surfacing, and adds
    a per-bucket sliding-window rate limiter to bound LLM cost.

    Default-on is safe because (a) the rate limiter caps invocations per
    bucket per hour, (b) `analyze()` is fire-and-forget — never raises into
    callers, and (c) downstream consumers (counselor hooks, journal) treat
    every result as best-effort.
    """

    enabled: bool = True  # AD-660b: default-on (rate-limited)
    max_tokens: int = 700
    tier: str = "standard"
    max_invocations_per_hour: int = 5  # AD-660b: per-bucket rate cap

    @field_validator("max_invocations_per_hour")
    @classmethod
    def _validate_rate_cap(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_invocations_per_hour must be >= 1")
        return v


class NLGraphQueryConfig(BaseModel):
    """AD-691 v1: NL-to-Graph Query Service.

    Default-enabled (deviation from Wave-10 transitional-flag convention)
    because the service is a callable read-only aggregator with no automatic
    invocation; it is invisible at runtime until a caller invokes
    `runtime.nl_graph_query.query()`. Same precedent as
    `DiagnosticContextConfig` and `KnowledgeEdgesConfig`.
    """

    enabled: bool = True
    default_max_hops: int = 2
    default_limit: int = 10
    llm_tier: str = "standard"
    extraction_max_tokens: int = 600
    synthesis_max_tokens: int = 800

    @field_validator("default_max_hops")
    @classmethod
    def _hops_in_range(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("default_max_hops must be in [1, 3]")
        return v

    @field_validator("default_limit")
    @classmethod
    def _limit_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("default_limit must be >= 1")
        return v


class StepInstructionConfig(BaseModel):
    """AD-651: Step-specific standing order decomposition."""

    enabled: bool = False  # Disabled by default — opt-in after validation

    # Step-to-category mappings. Keys are chain step names (matching SubTaskType values),
    # values are lists of category tags that the step should receive.
    step_categories: dict[str, list[str]] = {
        "query": [],  # Query is deterministic, no LLM — receives no instructions
        "analyze": [
            "observation_guidelines",
            "situation_assessment",
            "when_to_act_vs_observe",
            "memory_anchoring",
            "source_attribution",
            "self_monitoring",
        ],
        "compose": [
            "communication_style",
            "personality_expression",
            "audience_awareness",
            "ward_room_actions",
            "knowledge_capture",
            "duty_reporting",
        ],
        "evaluate": [
            "self_monitoring",
            "scope_discipline",
            "communication_style",
        ],
        "reflect": [
            "self_monitoring",
            "scope_discipline",
            "knowledge_capture",
        ],
    }

    # Categories that every LLM-calling step receives regardless of mapping.
    # These are foundational and should never be excluded.
    universal_categories: list[str] = [
        "identity",
        "chain_of_command",
        "core_directives",
        "encoding_safety",
    ]

    # If True, log token savings per step at DEBUG level.
    log_token_savings: bool = True


class LLMRateConfig(BaseModel):
    """AD-617: LLM call rate governance configuration."""

    # Per-tier requests per minute (0 = disabled)
    rpm_fast: int = 120
    rpm_standard: int = 120
    rpm_deep: int = 30

    # Max seconds to wait for a rate limit slot before returning error
    max_wait_seconds: float = 30.0

    # Max LLM response cache entries (LRU eviction)
    cache_max_entries: int = 500

    # AD-617b: Per-agent hourly token cap (0 = disabled)
    per_agent_hourly_token_cap: int = 0

    # AD-636: Global concurrency cap for LLM calls
    max_concurrent_calls: int = 6
    # AD-636: Reserved slots for interactive (Captain DM) priority
    interactive_reserved_slots: int = 2


class MemoryConfig(BaseModel):
    """Episodic memory configuration."""

    collection_name: str = "probos_episodes"
    max_episodes: int = 100000
    # AD-607e: Cross-shard recall access policy. PERMISSIVE preserves the
    # AD-462c cross-shard recall behavior verbatim. Opt-in tightening via
    # OWN_SHARD_ONLY or OWN_SHARD_PLUS_PUBLIC.
    access_policy: str = "permissive"
    relevance_threshold: float = 0.7
    # BF-134 / AD-593: Agent-scoped recall threshold.
    # MiniLM QA-trained model cosine similarity for question-vs-statement is typically 0.20-0.45.
    # 0.25 eliminates near-random associations while remaining generous for cross-topic recall.
    # Anchor confidence gate and composite score floor (AD-590) provide additional quality filtering.
    agent_recall_threshold: float = 0.25
    # BF-134: Minimum semantic similarity floor for FTS5 keyword-only hits.
    # Episodes found by keyword search but not semantic search get this
    # floor instead of 0.0, preventing keyword-relevant episodes from
    # being buried by the composite score formula.
    fts_keyword_semantic_floor: float = 0.2
    # AD-584: Embedding model and query reformulation
    embedding_model: str = "multi-qa-MiniLM-L6-cos-v1"
    query_reformulation_enabled: bool = True
    similarity_threshold: float = 0.6  # Semantic similarity threshold for recall/fuzzy lookup
    verify_content_hash: bool = True    # AD-541e: Verify episode hashes on recall
    eviction_audit_enabled: bool = True  # AD-541f: Append-only eviction audit trail
    # AD-820: shutdown consolidation budget. Old default was a hardcoded 2s
    # which is too tight when the dream cycle has real work to do; a partial
    # consolidation tears ChromaDB's HNSW index. Default raised to 30s so
    # normal shutdowns complete; operator can lower for fast-restart workflows.
    shutdown_consolidation_timeout_s: float = 30.0
    # BF-295 (#748): per-migration timeout for episodic-memory startup
    # migrations (BF-103, AD-570, AD-570b, AD-584, AD-605). Stuck or
    # CPU-bound migrations honest-degrade to a warning after this
    # ceiling and boot continues. Default 300s (5 min) — generous
    # enough for AD-605 enriched re-embed on a 10k-episode store on
    # CPU; operator can raise for very large stores or lower for
    # fast-restart workflows. Replaces the hardcoded 120.0 in
    # cognitive_services.py shipped with commit 44c80c70.
    migration_timeout_s: float = Field(
        default=300.0, ge=10.0, le=3600.0,
        description=(
            "BF-295 (#748): per-migration timeout in seconds for episodic-memory "
            "startup migrations. Stuck migrations honest-degrade after this "
            "ceiling. Default 300s; range 10s–3600s."
        ),
    )
    # AD-818 (#751): skip a migration's full-collection scan when its recorded
    # schema version matches. Default False (opt-in) for one release of bake
    # time; a grandchild AD flips it True.
    schema_version_tracking: bool = False
    # AD-825: max seconds to wait for write-holding background tasks
    # (dream monitor loop, episodic backup) to finish their current
    # operation before the AD-824 cancel sweep force-cancels them. Drain
    # is best-effort; cancel is the fallback. Default 30s mirrors
    # shutdown_consolidation_timeout_s. Operator can lower for
    # fast-restart workflows or raise for write-heavy snapshots.
    shutdown_drain_timeout_s: float = Field(
        default=30.0, ge=1.0, le=300.0,
        description=(
            "AD-825: max seconds to wait for write-holding tasks (dreaming, "
            "consolidation, episodic backup) to finish current operation "
            "before falling through to AD-824 cancel sweep."
        ),
    )
    # AD-821: ChromaDB HNSW per-collection sync threshold.
    # Chroma's default is 1000 records before the HNSW index flushes to disk;
    # if the process dies before that window flushes, the unsynced batch is
    # lost and the on-disk index can drift from SQLite metadata. Lowering to
    # 64 caps the worst-case loss window at the cost of more frequent (but
    # smaller) flushes during heavy writes (dream consolidation). 64/32 is a
    # conservative midpoint; operators can raise for write-heavy workloads or
    # lower for fast-restart workflows. Cross-field cap (batch_size <= threshold/2)
    # is enforced at the use site in EpisodicMemory.start(), not via validator.
    hnsw_sync_threshold: int = Field(default=64, ge=4, le=10000)
    hnsw_batch_size: int = Field(default=32, ge=1, le=10000)
    # AD-823: daily uncompressed-tar snapshot of chroma's on-disk footprint.
    # Pairs with AD-822 (boot probe) + AD-819 (rebuild from ward room) as the
    # third-line recovery primitive when both chroma and ward room are gone.
    # Default-on because the storage cost is small (current chroma footprint
    # is ~10-50 MB) and the recovery upside is large. Retain 7 days by default;
    # operators on tight disks can lower to 1, paranoid operators can raise.
    backup_enabled: bool = True
    backup_retain_days: int = Field(default=7, ge=1, le=365)
    # AD-567b/AD-584c: Salience-weighted recall (rebalanced for QA-trained embeddings)
    recall_weights: dict[str, float] = {
        "semantic": 0.35,
        "keyword": 0.20,
        "trust": 0.10,
        "hebbian": 0.05,
        "recency": 0.15,
        "anchor": 0.15,
    }
    recall_convergence_bonus: float = 0.10  # AD-584c: bonus for multi-channel hits
    # AD-873: Composite recall reranking (Ebbinghaus strength × similarity ×
    # recency × importance). Off + neutral by default: with the flag False the
    # recall() path is byte-identical to semantic-only, and even when enabled,
    # all-zero weights reproduce semantic-only ordering (x**0 == 1). Defaults
    # are sensible non-zero weights so flipping the flag produces useful
    # behavior; operators tune per workload.
    recall_rerank_enabled: bool = False
    recall_rerank_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "strength": 1.0,
            "recency": 0.5,
            "importance": 0.5,
        }
    )
    recall_temporal_match_weight: float = 0.25       # BF-147→BF-155: bonus for temporal cue match in score_recall()
    recall_temporal_mismatch_penalty: float = 0.15   # BF-155: penalty when query watch differs from episode watch
    # AD-979a: lower bound of the "weak" Feeling-of-Knowing band. A best recall
    # similarity in [weak_floor, relevance_threshold) is the invisible miss
    # (relevant-ish but below the confident-recall bar); below it is "none".
    recall_confidence_weak_floor: float = 0.45
    # AD-979c: hybrid dense+sparse retrieval. When enabled, recall fuses the
    # cosine ranking with the FTS5 keyword ranking via Reciprocal Rank Fusion so
    # a vocabulary-mismatched episode (below the cosine threshold but
    # keyword-present) is still surfaced. Default OFF -> byte-identical recall.
    hybrid_recall_enabled: bool = False
    hybrid_rrf_k: int = 60
    # AD-601: TCM Temporal Context Model
    tcm_enabled: bool = True
    tcm_dimension: int = 16
    tcm_drift_rate: float = 0.95
    tcm_weight: float = 0.15
    tcm_fallback_watch_weight: float = 0.05
    recall_context_budget_chars: int = 4000  # ~4K char memory budget
    # AD-567c: Anchor confidence scoring
    anchor_dimension_weights: dict[str, float] = {
        "temporal": 0.25,
        "spatial": 0.25,
        "social": 0.25,
        "causal": 0.15,
        "evidential": 0.10,
    }
    anchor_confidence_gate: float = 0.3  # RPMS: suppress below this from default recall
    # AD-590: Composite score floor — filter marginal episodes from recall results.
    # Episodes with composite_score below this threshold are excluded regardless
    # of remaining budget. 0.0 = disabled (backward compatible).
    composite_score_floor: float = 0.35
    # AD-591: Quality-aware budget enforcement.
    # max_recall_episodes: hard cap on episodes returned per recall. 0 = use k*2 default.
    max_recall_episodes: int = 0
    # recall_quality_floor: stop adding episodes if mean composite would drop below this.
    # 0.0 = disabled (character budget only).
    recall_quality_floor: float = 0.40
    # AD-462c: Variable Recall Tiers
    recall_tiers: dict[str, dict[str, Any]] = {
        "basic": {
            "k": 3,
            "context_budget": 1500,
            "anchor_confidence_gate": 0.0,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": False,
            "cross_department_anchors": False,
        },
        "enhanced": {
            "k": 5,
            "context_budget": 4000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": False,
        },
        "full": {
            "k": 8,
            "context_budget": 6000,
            "anchor_confidence_gate": 0.3,
            "composite_score_floor": 0.35,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.40,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
        "oracle": {
            "k": 10,
            "context_budget": 8000,
            "anchor_confidence_gate": 0.2,
            "composite_score_floor": 0.0,
            "max_recall_episodes": 0,
            "recall_quality_floor": 0.0,
            "use_salience_weights": True,
            "cross_department_anchors": True,
        },
    }

    @field_validator("access_policy")
    @classmethod
    def _validate_access_policy(cls, v: str) -> str:
        """AD-607e: Validate cross-shard access policy values."""
        valid = {"permissive", "own_shard_only", "own_shard_plus_public"}
        if v not in valid:
            raise ValueError(
                f"access_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    idle_threshold_seconds: float = 120.0  # Tier 2: full dream after idle (AD-288)
    dream_interval_seconds: float = 600.0
    replay_episode_count: int = 50
    pathway_strengthening_factor: float = 0.03
    pathway_weakening_factor: float = 0.02
    prune_threshold: float = 0.01
    trust_boost: float = 0.1
    trust_penalty: float = 0.1
    pre_warm_top_k: int = 5
    # AD-551: Notebook consolidation
    notebook_consolidation_enabled: bool = True
    notebook_consolidation_threshold: float = 0.6
    notebook_consolidation_min_entries: int = 2
    notebook_convergence_threshold: float = 0.5
    notebook_convergence_min_agents: int = 3
    notebook_convergence_min_departments: int = 2
    # AD-541c: Spaced Retrieval Therapy
    active_retrieval_enabled: bool = False
    retrieval_episodes_per_cycle: int = 3
    retrieval_success_threshold: float = 0.6
    retrieval_partial_threshold: float = 0.3
    retrieval_initial_interval_hours: float = 24.0
    retrieval_max_interval_hours: float = 168.0
    retrieval_counselor_failure_streak: int = 3
    # AD-541d: Guided Reminiscence
    reminiscence_enabled: bool = True
    reminiscence_episodes_per_session: int = 3
    reminiscence_concern_threshold: int = 3
    reminiscence_confabulation_alert: float = 0.3
    reminiscence_cooldown_hours: float = 2.0
    # AD-567d / AD-462b: Activation-based memory lifecycle
    activation_enabled: bool = True
    activation_decay_d: float = 0.5
    activation_prune_threshold: float = -2.0
    activation_access_max_age_days: int = 180
    # AD-593: Pruning acceleration — configurable parameters (previously hardcoded)
    prune_min_age_hours: int = 24  # Standard tier: only prune episodes older than this
    prune_max_fraction: float = 0.10  # Standard tier: max fraction of candidates per cycle
    # AD-599: Reflection episode promotion
    reflection_enabled: bool = True
    reflection_max_per_cycle: int = 3        # Cap reflections per dream cycle to prevent flooding
    reflection_min_importance: int = 8       # Importance score for reflection episodes (1-10 scale)
    # AD-593: Aggressive pruning tier — targets old, low-activation episodes
    aggressive_prune_enabled: bool = True
    aggressive_prune_min_age_hours: int = 168  # 7 days
    aggressive_prune_threshold: float = 0.0  # Higher threshold than standard (-2.0)
    aggressive_prune_max_fraction: float = 0.25  # Up to 25% of old candidates
    # AD-593: Episode pool pressure — accelerate pruning when pool is large
    episode_pressure_threshold: int = 5000  # Above this count, increase pruning aggressiveness
    episode_pressure_multiplier: float = 1.5  # Multiply prune fraction by this when above pressure threshold
    # AD-657: Trace exemplars preserved per consolidated procedure (0 = disabled)
    trace_exemplars_per_procedure: int = 3
    # AD-690: Dream Step 7i — Relationship inference from co-occurring episode agents
    relationship_inference_enabled: bool = True
    relationship_inference_max_pairs_per_run: int = 50
    relationship_inference_max_per_entity: int = 5
    relationship_inference_min_confidence: float = 0.6


class DreamWMConfig(BaseModel):
    """AD-671: Dream-Working Memory bridge configuration."""

    enabled: bool = True
    max_priming_entries: int = 3
    flush_min_entries: int = 5
    priming_category: str = "observation"


class ScalingConfig(BaseModel):
    """Adaptive pool scaling configuration."""

    enabled: bool = True
    scale_up_threshold: float = 0.8
    scale_down_threshold: float = 0.2
    scale_up_step: int = 1
    scale_down_step: int = 1
    cooldown_seconds: float = 30.0
    observation_window_seconds: float = 60.0
    idle_scale_down_seconds: float = 120.0


class PeerConfig(BaseModel):
    """Configuration for a single peer node."""

    node_id: str
    address: str  # e.g. "tcp://127.0.0.1:5556"


class FederationMCPServerConfig(BaseModel):
    """AD-480a: Inbound MCP server — exposes ProbOS capabilities as MCP tools."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    path_prefix: str = "/mcp"


class KnowledgeBrowserConfig(BaseModel):
    """AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS)."""
    enabled: bool = False
    max_graph_nodes: int = Field(default=500, ge=0, le=2000)
    max_graph_edges: int = Field(default=1000, ge=0, le=5000)
    jaccard_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_suggestions_per_entry: int = Field(default=5, ge=0, le=50)
    index_refresh_seconds: int = Field(default=300, ge=10, le=3600)


class SpatialExplorerConfig(BaseModel):
    """AD-520: Spatial Knowledge Explorer (Phase 1 Knowledge Graph View + Phase 2 Spatial Ship Layout).

    Default-False per AD-695 transitional precedent — wirer reads YAML and
    constructs an in-memory layout, not zero-cost on boot. Operator opt-in.
    """

    enabled: bool = False
    max_graph_edges: int = Field(default=500, ge=0, le=5000)
    max_graph_nodes: int = Field(default=200, ge=0, le=2000)
    spatial_layout_path: str = ""  # empty → resolves to config/ontology/spatial.yaml then to _DEFAULT_LAYOUT


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
        description="AD-706f: backend kind. v1 only supports 'file'.",
    )
    file_path: str = Field(
        default="data/credential_vault.json",
        description="AD-706f: JSON sidecar path for the EncryptedFileCredentialVault.",
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


class BrowserToolConfig(BaseModel):
    """AD-706: BrowserTool (Computer Use via Playwright).

    Safety guidelines (verbatim from anthropics/claude-quickstarts/computer-use-demo, MIT):

    1. Use a dedicated virtual machine or container with minimal privileges to
       prevent direct system attacks or accidents.
    2. Avoid giving the model access to sensitive data, such as account login
       information, to prevent information theft.
    3. Limit internet access to an allowlist of domains to reduce exposure to
       malicious content.
    4. Ask a human to confirm decisions that may result in meaningful real-world
       consequences as well as any tasks requiring affirmative consent, such as
       accepting cookies, executing financial transactions, or agreeing to terms
       of service.

    Source: anthropics/claude-quickstarts/computer-use-demo, MIT-licensed.
    """

    enabled: bool = False  # Wave 10 convention #14: default-False on transitional flags
    headless: bool = True
    default_timeout_ms: int = 30000
    session_max_duration_seconds: int = 1800
    session_reaper_interval_seconds: int = 60

    # Network egress policy
    domain_allowlist: list[str] | None = None  # None = all allowed (subject to denylist)
    domain_denylist: list[str] = Field(default_factory=list)

    # XGA screenshot scaling (Anthropic computer-use-demo discipline, MIT)
    screenshot_max_width: int = 1024
    screenshot_max_height: int = 768

    # Tier-3 confirmation policy
    require_confirmation_for_tier_3: bool = True
    confirmation_timeout_seconds: int = 300  # auto-deny if Captain doesn't ACK

    # Per-domain rate limiting (mirrors HttpFetchAgent)
    default_min_interval_seconds: float = 1.0

    # Per-action overrides
    per_action_timeout_ms: dict[str, int] = Field(default_factory=dict)

    # Tier-3 classification — host-suffix glob patterns that force Captain ACK.
    # Matched case-insensitively against the URL host via fnmatch.
    tier_3_domain_patterns: list[str] = Field(
        default_factory=lambda: [
            "*bank*",
            "*paypal*",
            "*stripe*",
            "*chase*",
            "*coinbase*",
            "*checkout*",
        ]
    )

    # AD-706d: LLM-driven tier classifier (default-OFF augmentation of the
    # rule-based classifier). When enabled, layered ON TOP of `classify_action`
    # via the companion function `classify_action_with_llm`. The LLM can only
    # UPGRADE risk, never DOWNGRADE — preserves the rule-based safety floor.
    llm_classifier_enabled: bool = Field(
        default=False,
        description=(
            "AD-706d: LLM-driven tier classifier for Browser Tool actions. "
            "Augments the rule-based classifier; default OFF."
        ),
    )
    llm_classifier_tier: str = Field(
        default="fast",
        description=(
            "AD-706d: LLM tier for classification calls. Fast is cheapest "
            "and adequate for tier classification."
        ),
    )
    llm_classifier_max_per_hour: int = Field(
        default=60,
        ge=0,
        description=(
            "AD-706d: per-runtime hourly cap on LLM classifier calls. "
            "0 disables. Reuses the AD-722a-1 VisionLLMRateLimit primitive "
            "under scope 'browser_action_classifier'."
        ),
    )
    llm_classifier_cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        description=(
            "AD-706d: in-memory cache TTL for identical (action, url-prefix, "
            "element-text, page-title) tuples. 0 disables caching."
        ),
    )

    # AD-706c-2: coordinate-aware compute_use trust budget (Guard #10).
    compute_use_max_consecutive_autonomous_actions: int = Field(
        default=5,
        ge=0,
        le=20,
        description=(
            "AD-706c-2: per-session cap on consecutive ``compute_use_click`` "
            "actions without a Captain ACK. Resets on any tier-3 ACK signal. "
            "0 disables compute_use entirely."
        ),
    )
    compute_use_max_per_session: int = Field(
        default=50,
        ge=0,
        le=500,
        description=(
            "AD-706c-2: per-session hard cap on total ``compute_use_click`` "
            "calls. Independent of the consecutive-autonomous cap. 0 disables."
        ),
    )

    # AD-706a: Captain-watch MJPEG streaming bridge.
    streaming_enabled: bool = Field(
        default=False,
        description="AD-706a: enable MJPEG-over-HTTP Captain-watch streaming. Default-OFF (Wave 10 convention #14).",
    )
    streaming_fps: int = Field(
        default=4,
        ge=1,
        le=15,
        description="AD-706a: frames-per-second for MJPEG streaming. Higher fps quickly overwhelms localhost.",
    )
    streaming_jpeg_quality: int = Field(
        default=60,
        ge=20,
        le=95,
        description="AD-706a: JPEG quality (Playwright page.screenshot quality param).",
    )
    streaming_max_concurrent_viewers: int = Field(
        default=4,
        ge=1,
        le=16,
        description="AD-706a: per-runtime cap on concurrent Captain-watch viewer slots.",
    )

    # AD-706b: Browser session video recording (Playwright record_video_dir).
    recording_enabled: bool = Field(
        default=False,
        description="AD-706b: enable Playwright record_video_dir on each BrowserSession. Default-OFF.",
    )
    recording_dir: str = Field(
        default="data/browser-sessions",
        description="AD-706b: directory tree where session subdirs (and .webm files) are written.",
    )
    recording_retention_days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="AD-706b: delete recordings older than this many days.",
    )
    recording_reaper_interval_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="AD-706b: sleep interval between recording-reaper sweeps.",
    )
    recording_max_size_mb_per_session: int = Field(
        default=500,
        ge=10,
        le=5000,
        description="AD-706b: per-session size cap (MB); oldest webm files deleted when exceeded.",
    )

    # AD-706f: credential vault (encrypted-at-rest). Default-OFF gate.
    credential_vault: CredentialVaultConfig = Field(
        default_factory=CredentialVaultConfig,
        description="AD-706f: nested credential vault config; default-OFF.",
    )

    # AD-745: action dispatch from DM replies. Default-OFF (Wave 10 convention #14).
    action_dispatch_enabled: bool = Field(
        default=False,
        description=(
            "AD-745: master switch for parsing [ACTION: ...] markers in DM "
            "replies and dispatching them to BrowserTool. Default OFF."
        ),
    )
    action_dispatch_max_consecutive_autonomous: int = Field(
        default=5, ge=0, le=20,
        description=(
            "AD-745: consecutive tier-1/2 dispatched actions before forcing "
            "tier-3 Captain confirm. Reuses AD-706c-2 Guard #10 trust-budget "
            "pattern across all action verbs (not just compute_use_click)."
        ),
    )
    action_dispatch_max_per_dm_turn: int = Field(
        default=1, ge=1, le=10,
        description=(
            "AD-745 v1: single action per DM reply. >1 reserved for "
            "AD-745-6 multi-step plans (forward marker)."
        ),
    )
    action_dispatch_ack_timeout_seconds: int = Field(
        default=60, ge=5, le=600,
        description=(
            "AD-745: tier-2 ACK timeout. Honest-degrade to TIMED_OUT after "
            "this many seconds without Captain ack. Tier-3 confirms NEVER "
            "time out (Captain decision required)."
        ),
    )
    destructive_url_patterns: list[str] = Field(
        default_factory=lambda: [
            "*/checkout*", "*/payment*", "*/billing*",
            "*/auth/*", "*/login*", "*/oauth*",
            "*/admin/*", "*/settings/account*",
            "*/delete*", "*/destroy*",
        ],
        description=(
            "AD-745: fnmatch patterns. URLs matching any pattern force ALL "
            "action verbs to tier-3 (Captain ACK every call)."
        ),
    )


class BaselineVRMManifest(BaseModel):
    """AD-721g: per-rank baseline VRM filenames.

    Resolved against ``<avatars_dir>/_baselines/<filename>``. Each entry is a
    bare filename (no path separators, no parent-dir traversal). Empty string
    disables the tier baseline — the resolver then falls back to the seed
    profile, then to the parametric capsule. License-clean by construction:
    no avatar bytes ship in the repo; operators install their own files
    under the AD-721i-1 CC0/MIT/Apache/BSD/CC-BY whitelist.
    """

    ensign: str = ""
    lieutenant: str = ""
    commander: str = ""
    senior: str = ""


class AvatarsConfig(BaseModel):
    """AD-721: 3D crew avatars (VRM popout)."""

    enabled: bool = True                                   # BF #536: default-on per Captain confirmation; parametric fallback is license-safe
    avatars_dir: str = "data/avatars"
    max_vrm_size_bytes: int = 25 * 1024 * 1024             # 25 MB hard cap
    fallback_to_parametric_on_error: bool = True
    # AD-721i: headless Blender renderer (operator brings the binary).
    blender_path: str = ""                                 # "" = search PATH via shutil.which("blender")
    blender_render_timeout_s: int = 180
    dsl_drafts_dir: str = "data/avatars/.drafts"
    # Wave 10 convention #14: transitional flag default-False; flip in a
    # follow-up AD once the renderer is exercised end-to-end.
    renderer_enabled: bool = False
    # Captain ruling 2026-05-09: capsule fallback default-on so v1 is end-to-end
    # without requiring operator-supplied base meshes.
    procedural_base_mesh_fallback: bool = True
    # AD-721d-1: how many revision iterations before the Captain MUST approve
    # or reject. Iteration 1 = initial proposal; iterations 2..N are
    # revisions. Bounded 1..10 to keep LLM cost predictable.
    max_proposal_iterations: int = 3

    # AD-721g: per-rank baseline VRM filenames resolved under
    # ``<avatars_dir>/_baselines/``. Empty string per rank → no tier baseline;
    # resolver falls back to seed profile then parametric. License-clean:
    # no avatar bytes ship in the repo.
    baseline_vrms: BaselineVRMManifest = Field(
        default_factory=BaselineVRMManifest,
        description=(
            "AD-721g: per-rank baseline VRM filenames. Each entry is a bare "
            "filename resolved under ``<avatars_dir>/_baselines/<filename>``. "
            "Empty string disables the tier baseline."
        ),
    )

    # AD-721d-4: optional disk-sidecar path for the per-agent proposal
    # history. When None, defaults to ``<data_dir>/proposal_history.json``.
    proposal_history_path: str | None = Field(
        default=None,
        description=(
            "AD-721d-4: filesystem path for the per-agent DSL proposal "
            "history JSON sidecar. When None, defaults to "
            "``<runtime.data_dir>/proposal_history.json``."
        ),
    )

    # AD-720d-2.1: optional disk-sidecar path for vision-capability proposal
    # history. When None, defaults to ``<data_dir>/vision_proposal_history.json``.
    vision_proposal_history_path: str | None = Field(
        default=None,
        description=(
            "AD-720d-2.1: filesystem path for the vision-capability "
            "proposal-history JSON sidecar."
        ),
    )

    # AD-722a-1: vision-LLM intent-divergence gating (default-OFF transitional).
    vision_intent_divergence_enabled: bool = Field(
        default=False,
        description=(
            "AD-722a-1: enable vision-LLM intent-vs-render divergence "
            "detection. Default-OFF until AD-721i backend renderer ref "
            "lookup is stable."
        ),
    )
    vision_intent_divergence_max_per_hour_per_agent: int = Field(
        default=3,
        description=(
            "AD-722a-1: per-agent hourly call cap for vision-LLM intent "
            "divergence (aligns with AD-728 cost ceiling)."
        ),
    )

    # AD-722e-2: vision-LLM self-render verification (default-OFF transitional).
    self_render_verify_enabled: bool = Field(
        default=False,
        description=(
            "AD-722e-2: enable vision-LLM digital-vs-render coherence "
            "verification. Default-OFF until AD-721i backend renderer "
            "ref lookup is stable."
        ),
    )
    self_render_verify_max_per_hour_per_agent: int = Field(
        default=3,
        description=(
            "AD-722e-2: per-agent hourly call cap for vision-LLM "
            "self-render verification (aligns with AD-728 cost ceiling)."
        ),
    )

    # AD-728: vision-LLM render-coherence mirror (default-OFF transitional).
    render_verification_enabled: bool = Field(
        default=False,
        description=(
            "AD-728: vision-LLM render-coherence mirror. Default OFF "
            "until AD-721i backend renderer is stable."
        ),
    )
    render_verification_max_per_hour_per_agent: int = Field(
        default=3,
        ge=0,
        description=(
            "AD-728: per-agent hourly cap for render-verification vision "
            "calls. 0 disables. Shares the AD-722a-1 VisionLLMRateLimit "
            "primitive under scope 'render_verification'."
        ),
    )
    render_verification_followup_enabled: bool = Field(
        default=False,
        description=(
            "AD-728: when True, an AD-722a-1 intent-divergence observation "
            "triggers a render-coherence mirror call with "
            "trigger='divergence_followup'. Default OFF; flip after AD-728 "
            "RENDER_DIVERGENCE_OBSERVED telemetry is stable."
        ),
    )

    # AD-728c: agent-initiated render self-check (default-OFF transitional).
    render_self_check_enabled: bool = Field(
        default=False,
        description=(
            "AD-728c: flip agent_initiated_stub trigger from hard-reject to "
            "a gated, rate-limited self-check. Default OFF; flip after "
            "AD-728 telemetry confirms vision-tier cost is bounded."
        ),
    )
    render_self_check_max_per_hour_per_agent: int = Field(
        default=3,
        ge=0,
        description=(
            "AD-728c: per-agent hourly cap for agent-initiated render "
            "self-checks. Applies when the agent is NOT in an active "
            "conversation. 0 disables. Uses the AD-722a-1 "
            "VisionLLMRateLimit primitive under scope "
            "'render_self_check_hour'."
        ),
    )
    render_self_check_max_per_active_conversation: int = Field(
        default=2,
        ge=0,
        description=(
            "AD-728c: per-agent budget within a single active conversation "
            "window. Pattern: 'before reply + 1 mid-conversation'. Applies "
            "INSTEAD OF the hourly budget while the agent is in an active "
            "conversation. 0 disables self-check during active conversations."
        ),
    )
    render_self_check_active_window_seconds: int = Field(
        default=600,
        ge=0,
        description=(
            "AD-728c: seconds since the agent's last reply emission to "
            "consider it 'in an active conversation' for self-check budget "
            "selection. Default 600s = 10 minutes. Uses CognitiveAgent."
            "last_reply_emitted_at (AD-722)."
        ),
    )

    # AD-740: affect-vs-intent drift trend over recent divergence history.
    # Summarises the existing AD-722a-5 ring buffer; pure read-only.
    affect_drift_default_window: int = Field(
        default=8,
        ge=2,
        le=128,
        description=(
            "AD-740: default window size (most recent N divergence entries) "
            "for affect-vs-intent drift trend summary. Operators may pass "
            "an explicit ``window`` to ``get_affect_drift`` to override."
        ),
    )
    affect_drift_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "AD-740: match-score threshold below which an entry counts as "
            "a 'divergent' turn in the drift summary. Default 0.7 mirrors "
            "the conservative end of the AD-722a divergence band."
        ),
    )

    # AD-730-3: agent image generation in DM replies.
    image_gen_enabled: bool = Field(
        default=False,
        description=(
            "AD-730-3: master switch for agent image generation via "
            "[GEN_IMAGE ...] bracket marker. Default OFF (transitional). "
            "Requires CognitiveConfig.llm_base_url_image_gen to be set."
        ),
    )
    image_gen_max_prompt_chars: int = Field(
        default=512,
        ge=8,
        le=4000,
        description=(
            "AD-730-3: hard cap on the [GEN_IMAGE ...] prompt length. "
            "Markers exceeding this are silently stripped and a single "
            "WARNING is logged."
        ),
    )
    image_gen_wellness_review_required: bool = Field(
        default=True,
        description=(
            "AD-730-3: when True, the FIRST image_gen invocation per "
            "agent per process triggers a Counselor wellness review log "
            "entry (AD-727 governance pattern). Subsequent invocations "
            "by the same agent skip the review until process restart."
        ),
    )
    image_gen_max_image_bytes: int = Field(
        default=4 * 1024 * 1024,
        ge=64 * 1024,
        le=25 * 1024 * 1024,
        description=(
            "AD-730-3: per-image size cap on bytes written to "
            "AttachmentStore. Defense in depth alongside the upstream "
            "API's own limits."
        ),
    )
    image_gen_mime: str = Field(
        default="image/png",
        description=(
            "AD-730-3: declared MIME for stored images. PNG is OpenAI's "
            "default. Operator may set to image/jpeg if their endpoint "
            "returns JPEG."
        ),
    )

    # AD-729: peer avatar perception governance contract (default-OFF
    # transitional). Capability stays OFF until AD-729a Standing Orders ship
    # and AD-729b certification grades at least one officer.
    peer_perception_enabled: bool = Field(
        default=False,
        description=(
            "AD-729: peer avatar perception capability. Default OFF until "
            "AD-729a Standing Orders ship and AD-729b certification grades "
            "at least one officer."
        ),
    )
    peer_observation_decay_seconds: int = Field(
        default=86400 * 7,
        ge=3600,
        description=(
            "AD-729: impression decay window in seconds. Observations older "
            "than this are filtered from composite impressions."
        ),
    )
    peer_observation_max_per_pair_per_thread: int = Field(
        default=1,
        ge=0,
        description=(
            "AD-729: mechanical floor — max observations per (observer, "
            "observed) pair per WR thread. 0 disables capability entirely."
        ),
    )

    # AD-722a-6: peer perception of intent-vs-presentation divergence
    # (default-OFF transitional; consumer of AD-722a-1 + AD-729).
    cross_agent_divergence_observation_enabled: bool = Field(
        default=False,
        description=(
            "AD-722a-6: peer perception of intent-vs-presentation. Default "
            "OFF; requires peer_perception_enabled True AND AD-729a "
            "Standing Orders shipped before being flipped."
        ),
    )

    # AD-721f: Cognitive Canvas VRM avatar rendering (default-OFF
    # transitional). When enabled, agents within ``canvas_vrm_lod_distance``
    # render as VRMs (capped at ``canvas_max_concurrent_vrms`` simultaneous);
    # remaining agents stay on the orb instanced-mesh path.
    canvas_render_vrm_avatars: bool = Field(
        default=False,
        description=(
            "AD-721f: render registered VRMs in the Cognitive Canvas at "
            "canvas scale for agents within the LOD distance threshold. "
            "Default OFF -- operators with low-end GPUs keep the orb-only "
            "path."
        ),
    )
    canvas_max_concurrent_vrms: int = Field(
        default=12,
        ge=0,
        le=64,
        description=(
            "AD-721f: max VRMs rendered simultaneously in the canvas. "
            "Agents beyond this count fall back to orb instances."
        ),
    )
    canvas_vrm_lod_distance: float = Field(
        default=15.0,
        gt=0.0,
        description=(
            "AD-721f: camera-distance threshold (world units) under which "
            "agents render as VRMs. Beyond this distance, the orb path is "
            "used."
        ),
    )

    # AD-721e: skeletal animation library (Quaternius CC0 default; Mixamo
    # REJECTED per AD-721i-1). Operator runs scripts/animations-fetch.ps1 to
    # populate ``animations_dir``; clips are SHA-256 integrity-checked at
    # manifest registration time.
    animations_dir: str = Field(
        default="data/avatars/animations",
        description=(
            "AD-721e: directory of operator-installed CC0/MIT animation "
            "clips. Gitignored; operator-fetched via "
            "scripts/animations-fetch.ps1."
        ),
    )
    animations_enabled: bool = Field(
        default=False,
        description=(
            "AD-721e: enable AnimationMixer playback in CrewVRM. Default "
            "OFF -- operators without animations installed keep the "
            "procedural idle fallback."
        ),
    )

    # AD-743: adaptive conversational pacing for active 1:1 DMs.
    pacing_enabled: bool = Field(
        default=False,
        description=(
            "AD-743: enable [FOLLOW_UP delay reason] marker parsing and "
            "the ConversationPacingScheduler runtime service. Default "
            "OFF transitional flag (convention #14) — existing turn-"
            "taking DM behavior is bit-for-bit preserved when disabled."
        ),
    )
    pacing_max_followups_per_active_conversation: int = Field(
        default=2,
        ge=0,
        le=10,
        description=(
            "AD-743: per-conversation cap on synthesized follow-ups "
            "before the active window resets."
        ),
    )
    pacing_max_followups_per_hour_per_agent: int = Field(
        default=6,
        ge=0,
        le=60,
        description=(
            "AD-743: rolling 1h ceiling on follow-ups per agent across "
            "all conversations (safety cap)."
        ),
    )
    pacing_active_window_seconds: int = Field(
        default=600,
        ge=60,
        le=3600,
        description=(
            "AD-743: silence threshold beyond which a conversation is "
            "considered inactive and the per-conversation budget resets."
        ),
    )
    pacing_min_delay_seconds: int = Field(
        default=1,
        ge=1,
        le=60,
        description=(
            "AD-743: minimum allowed delay for a [FOLLOW_UP] marker. "
            "Markers below this floor are stripped and discarded."
        ),
    )
    pacing_max_delay_seconds: int = Field(
        default=300,
        ge=1,
        le=900,
        description=(
            "AD-743: maximum allowed delay for a [FOLLOW_UP] marker. "
            "Markers above this ceiling are stripped and discarded."
        ),
    )

    @field_validator("max_proposal_iterations")
    @classmethod
    def _bound_max_proposal_iterations(cls, v: int) -> int:
        if not 1 <= v <= 10:
            raise ValueError(
                f"max_proposal_iterations must be 1 ≤ v ≤ 10, got {v}"
            )
        return v


class SamplingRatesConfig(BaseModel):
    """AD-722f: per-agent avatar-telemetry sampling rates (3 tiers).

    Driven by ``runtime.avatar_sampling_state`` state machine. All three
    fields default — ``SamplingRatesConfig()`` MUST succeed. Operator
    overrides via system.yaml. Validators clamp to a safety floor (250 ms)
    to prevent UI/backend hammering — same floor as ``polling_interval_ms``.
    """

    high_ms: int = 250      # DM in flight, popout open (forward marker — Wave 142)
    normal_ms: int = 2000   # Chain reasoning active
    low_ms: int = 10000     # Idle / WR posting / default

    @field_validator("high_ms", "normal_ms", "low_ms")
    @classmethod
    def _bound_rate(cls, v: int) -> int:
        if v < 250:
            raise ValueError(
                f"sampling-rate field must be >= 250 to prevent UI hammering, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _check_ordering(self) -> "SamplingRatesConfig":
        if not (self.high_ms <= self.normal_ms <= self.low_ms):
            raise ValueError(
                f"sampling rates must satisfy high_ms <= normal_ms <= low_ms; "
                f"got high={self.high_ms}, normal={self.normal_ms}, low={self.low_ms}"
            )
        return self


class AvatarTelemetryConfig(BaseModel):
    """AD-722: agent-observable avatar telemetry channel.

    Read-only telemetry — exposes the agent's own avatar state via a
    snapshot dataclass. v1 is poll-only (HTTP + in-process method on
    ``CognitiveAgent``); push (WebSocket) is forward marker AD-722b.

    AD-722f added per-agent adaptive sampling (``sampling_rates`` field
    + ``runtime.avatar_sampling_state`` state machine). The legacy
    ``polling_interval_ms`` field is retained as a UI hint (consumed
    directly by ``SelfImageTab.tsx``); Wave 142's WS push channel will
    collapse the two surfaces.

    All fields default — ``AvatarTelemetryConfig()`` MUST succeed.
    """

    enabled: bool = True
    inject_into_agent_context: bool = False  # Feature-gated; default OFF.
    mouth_active_window_seconds: float = 3.0
    polling_interval_ms: int = 2000          # AD-722 — UI hint, not backend-driven.
    sampling_rates: SamplingRatesConfig = Field(default_factory=SamplingRatesConfig)  # AD-722f
    max_connections_per_agent: int = 4       # AD-722b — WS popout connections per agent
    # AD-722a: intent-vs-presentation divergence detector.
    # Default OFF — operator opt-in for token cost (~10 prompt + ~5 reply
    # tokens per DM cycle). When True, the LLM is instructed to append
    # ``<intent emotion=...>`` to every DM reply, the server parses + strips
    # it, and divergence drives trust + Hebbian updates.
    divergence_detection: bool = False
    divergence_negative_threshold: float = 0.3   # |magnitude| > this fires NEGATIVE trust delta (output diverged AWAY)
    divergence_positive_threshold: float = 0.5   # |magnitude| > this fires POSITIVE trust delta (output exceeded SAME direction; higher bar)
    divergence_negative_weight: float = 0.4   # Output diverged AWAY (asymmetric heavier)
    divergence_positive_weight: float = 0.1   # Output exceeded same direction (soft inform)
    # AD-722a-5: in-memory ring buffer for the divergence history surface.
    # Volatile (restart wipes). Per-agent. Size 0 disables history capture
    # entirely (the surface degrades to an empty list + 0% aggregate).
    divergence_history_size: int = 100
    # AD-722a-5: window walked by the aggregate-metric calculation.
    # Clamped at read time to min(window, len(history)).
    divergence_aggregate_window: int = 50
    # AD-722a-4: auto-correction loop on high-magnitude divergence.
    # Default OFF — INVERTS the AD-727 rule #1 read-only contract for the
    # MODULATION path (aesthetic judgment influences prosody output).
    # Carve-out is intentionally narrow: re-modulation does NOT rewrite
    # response_text; only the prosody parameters consumed by TTS change.
    auto_correct_enabled: bool = False
    # Magnitude above which a re-modulation attempt fires. Higher than
    # divergence_negative_threshold (0.3) to avoid retry storms on mild
    # misses. Operator can tune downward at their own risk.
    auto_correct_threshold: float = 0.6
    # Per-utterance budget. Set to 0 to disable corrections without flipping
    # auto_correct_enabled (useful for A/B comparison runs).
    max_corrections_per_utterance: int = 1
    # Multiplicative factor applied to Piper noise_scale during correction.
    # Higher noise = more prosodic variation; correction nudges TOWARD the
    # intended emotion's expressive profile (verified by AD-738e-1 deltas).
    correction_noise_factor: float = 1.15
    # Multiplicative factor applied to Piper length_scale during correction.
    # Lower length = faster speech; correction profile mirrors AD-738e-1's
    # excited (faster) vs. concerned (slower) intent direction.
    correction_length_factor: float = 0.92
    # AD-722c: append-only JSONL persistence under {history_dir}/<agent_id>.jsonl.
    # Operator opt-out via history_enabled=False. Retention is enforced lazily
    # at query time (rows older than now - history_retention_days are
    # filtered out; on-disk pruning is deferred to AD-722c-1 forward marker).
    history_enabled: bool = True
    history_retention_days: int = 30
    history_dir: str = "data/avatar_telemetry"
    # AD-722d: auto-write significant telemetry events to Ship's Records.
    # Default OFF — Records is a durable git-backed ledger; the Captain
    # opts in. v1 vocabulary covers three event names; unknown event
    # names in records_significant_events are silently ignored.
    records_auto_write_enabled: bool = False
    records_throttle_seconds: int = 3600           # max 1 Records entry per agent per hour
    records_significant_events: list[str] = Field(
        default_factory=lambda: [
            "emotion_divergence_high",
            "working_state_transition_to_blocked",
            "sustained_silence",
        ],
    )
    sustained_silence_seconds: int = 1800          # 30 min
    # AD-722b-3: WS frame diffing. Default ON — pure additive perf win.
    # Disable to revert to AD-722b's always-full-snapshot behavior.
    ws_diff_enabled: bool = True
    # Relative-change threshold for numeric fields. Below this, the field
    # is treated as unchanged for diff purposes (frame is suppressed if
    # all numeric deltas are sub-threshold AND no non-numeric changes).
    ws_diff_threshold: float = 0.05
    # Send a full snapshot every N publish-loop wakes regardless of diff,
    # so late-arriving subscribers and any browser that missed a diff
    # reconcile. Set to 1 to disable diff entirely (behaves as full).
    ws_full_snapshot_every_n: int = 10
    # AD-722b-4: fleet-level telemetry stream — one WS, fan-out by agent_id.
    # Default-ON: zero behavior change for operators because no UI consumer
    # ships in v1; setting False mutes the endpoint (returns 1008 close).
    fleet_stream_enabled: bool = True

    @field_validator("mouth_active_window_seconds")
    @classmethod
    def _bound_mouth_window(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"mouth_active_window_seconds must be > 0, got {v}")
        return v

    @field_validator("polling_interval_ms")
    @classmethod
    def _bound_polling(cls, v: int) -> int:
        if v < 250:
            raise ValueError(f"polling_interval_ms must be >= 250 to prevent UI hammering, got {v}")
        return v

    @field_validator("max_connections_per_agent")
    @classmethod
    def _bound_max_connections(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"max_connections_per_agent must be >= 1, got {v}"
            )
        return v

    @field_validator(
        "divergence_negative_threshold",
        "divergence_positive_threshold",
        "divergence_negative_weight",
        "divergence_positive_weight",
    )
    @classmethod
    def _bound_divergence_weights(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"divergence weight/threshold fields must be in [0.0, 1.0], got {v}"
            )
        return v

    @field_validator("divergence_history_size", "divergence_aggregate_window")
    @classmethod
    def _bound_divergence_history_counts(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                f"divergence_history_size / divergence_aggregate_window must be >= 0, got {v}"
            )
        return v

    @field_validator("history_retention_days")
    @classmethod
    def _bound_history_retention_days(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"history_retention_days must be >= 1, got {v}"
            )
        return v

    @field_validator("records_throttle_seconds")
    @classmethod
    def _bound_records_throttle_seconds(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"records_throttle_seconds must be >= 1, got {v}"
            )
        return v

    @field_validator("sustained_silence_seconds")
    @classmethod
    def _bound_sustained_silence_seconds(cls, v: int) -> int:
        if v < 60:
            raise ValueError(
                f"sustained_silence_seconds must be >= 60, got {v}"
            )
        return v

    @field_validator("ws_diff_threshold")
    @classmethod
    def _bound_ws_diff_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(
                f"ws_diff_threshold must be in [0.0, 1.0], got {v}"
            )
        return v

    @field_validator("ws_full_snapshot_every_n")
    @classmethod
    def _bound_ws_full_snapshot_every_n(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"ws_full_snapshot_every_n must be >= 1, got {v}"
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


class CloudPickersConfig(BaseModel):
    """AD-720c: cloud file picker config (OAuth-bound). Default OFF."""

    enabled: bool = Field(default=False, description="AD-720c master switch.")
    max_file_size_bytes: int = Field(default=50_000_000, ge=1)
    state_ttl_seconds: int = Field(
        default=300,
        ge=30,
        description="AD-720c: CSRF state-token TTL (seconds).",
    )
    google_drive: CloudPickerProviderConfig = Field(
        default_factory=CloudPickerProviderConfig
    )
    onedrive: CloudPickerProviderConfig = Field(
        default_factory=CloudPickerProviderConfig
    )
    dropbox: CloudPickerProviderConfig = Field(
        default_factory=CloudPickerProviderConfig
    )


class CameraStreamConfig(BaseModel):
    """AD-733: client-side camera streaming controls."""

    enabled: bool = False
    """Default-OFF per privacy posture; operator flips explicitly."""

    default_fps: int = Field(default=1, ge=1, le=4,
        description=(
            "Client-side capture cadence. Vision tier inference budget caps "
            "this; 1 fps is the safe default."
        ),
    )

    frame_jpeg_quality: float = Field(default=0.6, ge=0.2, le=0.95)

    frame_max_dimension: int = Field(default=512, ge=128, le=1024,
        description="Longest-edge downsample target for capture.",
    )


class ScreenStreamConfig(BaseModel):
    """AD-733-2: client-side screen-share streaming controls.

    Mirrors :class:`CameraStreamConfig`. Default-OFF — Captain must opt-in
    explicitly. ``getDisplayMedia`` browser-prompt consent is the floor;
    this toggle is the additional ProbOS-side switch the operator can flip
    to hide the surface entirely (e.g. kiosk mode).
    """

    enabled: bool = False
    """Default-OFF — Captain flips explicitly."""

    default_fps: int = Field(default=1, ge=1, le=4,
        description=(
            "Client-side screen-capture cadence. Vision tier inference budget "
            "caps this; 1 fps is the safe default."
        ),
    )


class PerceptionConfig(BaseModel):
    """AD-733: visual sensor input from operator-side capture devices."""

    enabled: bool = False
    """Master switch for the entire perception subsystem."""

    camera: CameraStreamConfig = Field(default_factory=CameraStreamConfig)

    # AD-733-2: screen-source sub-block. Mirrors camera.* shape; default-OFF.
    screen: ScreenStreamConfig = Field(default_factory=ScreenStreamConfig)

    # AD-744: master switch for the Captain-initiated "Share to agent"
    # surface. Default-ON is safe: the underlying getDisplayMedia API
    # requires a fresh browser-prompt consent on every click; this toggle
    # exists for operators who want to disable the surface entirely
    # (e.g. kiosk mode).
    explicit_share_enabled: bool = Field(default=True,
        description=(
            "AD-744: master switch for Captain-initiated 'Share to agent' "
            "shortcuts. Default-ON because getDisplayMedia requires a fresh "
            "browser-prompt consent on every invocation; toggle off for "
            "kiosk mode."
        ),
    )

    camera_max_fps_server: int = Field(default=4, ge=1, le=10,
        description="Server-side hard cap on frame ingestion rate per session.",
    )

    # AD-733-2: server-side fps cap on screen frames. Independent bucket
    # from camera_max_fps_server — operator can throttle screen-share
    # without affecting the camera stream.
    screen_max_fps_server: int = Field(default=2, ge=1, le=4,
        description=(
            "AD-733-2: server-side hard cap on screen-frame ingestion rate "
            "per session. Independent of camera cap."
        ),
    )

    frame_max_size_bytes: int = Field(default=512 * 1024, ge=4096, le=5 * 1024 * 1024,
        description="Reject frame uploads larger than this. Default 512 KB.",
    )

    # AD-733-1: ephemeral-frame retention. Perception frames are
    # content-addressed and written to the AttachmentStore for the
    # VisionConsumer's working-memory + force-describe cache, but they
    # are NOT operator intent -- they expire shortly after capture. The
    # reaper sweeps origin=perception_frame entries older than this.
    frame_retention_seconds: int = Field(default=300, ge=30, le=86400,
        description=(
            "AD-733-1: TTL for perception-origin attachments. Default 5 min -- "
            "covers VisionConsumer WM window + AD-733c-1 force-describe cache."
        ),
    )

    reaper_interval_seconds: int = Field(default=60, ge=10, le=3600,
        description=(
            "AD-733-1: how often the AttachmentReaper sweeps. Default 60s -- "
            "produces at most one full directory scan per minute."
        ),
    )

    # AD-733a (Wave 171): VisionConsumer cost-discipline + buffer sizing.
    vision_consumer_enabled: bool = Field(default=True,
        description="Run the VisionConsumer that calls the vision LLM on supervisor-flagged frames.",
    )
    vision_min_interval_seconds: float = Field(default=3.0, ge=1.0, le=120.0,
        description="Minimum seconds between vision LLM calls per session. Cost-discipline floor.",
    )
    vision_novelty_threshold: float = Field(default=0.08, ge=0.0, le=1.0,
        description="Perceptual aHash diff threshold above which a frame is flagged as novel. Lower = more sensitive to small scene changes. BF-307: 0.08 default after empirical evidence that 0.15 was too high for static-camera setups.",
    )
    vision_baseline_max_age_seconds: float = Field(default=30.0, ge=0.0, le=600.0,
        description="BF-309: after this many seconds with no admit, the supervisor re-baselines on the next frame. Prevents static-scene anchoring where a steady pose makes every later frame look low-novelty against a stale baseline. 0 = disable.",
    )
    vision_supervisor_strategy: str = Field(default="ahash",
        description="AD-742d: frame-admission strategy. 'ahash' (default, perceptual-hash diff), 'motion' (per-pixel diff), 'scene_change' (HSV histogram delta), 'never' (drop all frames; describe only on force / DM), 'always' (admit all; debug/test only). Restart required to swap.",
    )
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
        description="Per-agent vision working memory ring buffer size.",
    )
    wm_persistence_enabled: bool = Field(default=True,
        description="AD-742f: persist VisionWorkingMemory rings to data/perception_wm.db so Captain's per-agent visual history survives restart. Set False to operate in-memory only (legacy behavior).",
    )
    vision_tier: str = Field(default="vision",
        description="LLM tier name for narrative / proactive-observer vision calls (AD-733b scene-introduction + high-novelty triggers). Falls back to standard/deep behavior if vision_fast is unset.",
    )
    vision_fast_tier: str = Field(default="vision_fast",
        description="AD-742a (Wave 174): LLM tier for per-frame supervisor-flagged describe calls. Falls back to vision_tier when unconfigured (which itself honest-degrades).",
    )

    # AD-733c-1 (Wave 172): DM-receive force-describe of the latest cached frame
    # before the agent's reply is composed. 4s wall-clock timeout enforced by
    # VisionConsumer.force_describe_current_frame. Default True so the
    # subsystem benefits from fresh-frame grounding out of the box; operator
    # can disable for cost-discipline experiments.
    dm_force_describe_enabled: bool = Field(default=True,
        description="On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor).",
    )

    # AD-733c-4 (Wave 172): idle drop-back thresholds. ENGAGED -> AMBIENT
    # after engaged_idle_seconds of no DM activity. AMBIENT -> DORMANT
    # after ambient_idle_seconds since entering AMBIENT (AMBIENT-entry is
    # tracked via the controller's mode_since timestamp).
    engaged_idle_seconds: float = Field(default=300.0, ge=30.0, le=3600.0,
        description="ENGAGED -> AMBIENT after this many seconds of no DM activity. Default 5 min.",
    )
    ambient_idle_seconds: float = Field(default=1800.0, ge=60.0, le=86400.0,
        description="AMBIENT -> DORMANT after this many seconds in AMBIENT with no engagement signal. Default 30 min.",
    )
    idle_watchdog_tick_seconds: float = Field(default=30.0, ge=5.0, le=300.0,
        description="How often the controller's idle watchdog polls. Default 30s.",
    )

    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
    # DEPRECATED by AD-742b; retained for backwards-compat. If
    # ``data/captain_identity.json`` exists, that takes precedence.
    captain_avatar_ref: str = Field(default="",
        description="DEPRECATED (AD-742b): SHA-256 of a reference photo of the Captain in AttachmentStore. Use face-embedding enrollment instead.",
    )

    # AD-742b (Wave 174): face-embedding identity recognition.
    identity_match_threshold: float = Field(default=0.6, ge=0.0, le=2.0,
        description="Cosine distance threshold for face-embedding identity match. Smaller = stricter. facenet-pytorch VGGFace2-pretrained default: 0.6. Operator-tunable.",
    )
    identity_resolver_enabled: bool = Field(default=True,
        description="AD-742b: use face-embedding identity resolution. False = fall back to AD-733b LLM-prompt path (deprecated, expensive).",
    )

    # AD-733b: proactive observer budget.
    proactive_observer_enabled: bool = Field(default=True,
        description="Allow the agent to proactively surface novel visual scenes in a DM.",
    )
    proactive_max_emissions: int = Field(default=3, ge=0, le=20,
        description="Maximum proactive vision DMs per session.",
    )
    proactive_dwell_seconds: float = Field(default=30.0, ge=5.0, le=600.0,
        description="Minimum seconds between consecutive proactive vision DMs.",
    )
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )

    # AD-733c-6 (Wave 175): engaged-mode vision LLM call budget.
    # AD-742e ships the counters; this section ships the enforcement.
    engaged_budget_enforcement: bool = Field(default=True,
        description="AD-733c-6: when True, exceeding the per-session or per-day vision call cap in ENGAGED mode auto-drops to AMBIENT. False = counters-only behavior (AD-742e baseline).",
    )
    engaged_call_cap_per_session: int = Field(default=200, ge=10, le=10000,
        description="AD-733c-6: vision LLM calls per session in ENGAGED mode before auto-drop to AMBIENT. Captain default 200; tune via Settings or BF-308 hot-reload.",
    )
    engaged_call_cap_per_day: int = Field(default=2000, ge=50, le=100000,
        description="AD-733c-6: vision LLM calls per UTC day before auto-drop to AMBIENT. Captain default 2000.",
    )

    # AD-733c-7: Silero VAD secondary engagement trigger. Off by default
    # (convention #14 transitional gate). Browser-side VAD pulls from the
    # existing wake-word getUserMedia stream and POSTs only a boolean
    # speech-detected event to /api/perception/voice-activity. Audio
    # bytes NEVER leave the browser.
    vad_engagement_enabled: bool = Field(default=False,
        description="AD-733c-7: enable Silero VAD as a secondary engagement trigger. Default OFF — endpoint exists but the browser never calls it. When enabled, browser POSTs speech-detected events to /api/perception/voice-activity which routes through the per-agent PerceptionEngagementRegistry (AD-733c-5).",
    )
    vad_min_speech_duration_ms: int = Field(default=400, ge=100, le=2000,
        description="AD-733c-7: browser-side debounce floor before firing the voice-activity endpoint. Prevents single-syllable false positives.",
    )

    # AD-746 Layer 1: VisionAggregator debounce-fusion of camera +
    # screen sources. Default-ON because the symptom (budget burn 2x
    # when both sources stream concurrently) is material in production.
    # Honest-degrade: when False, the aggregator is bypassed and the
    # consumer subscribes directly to the bus (zero behavior delta vs
    # pre-AD-746).
    source_fusion_enabled: bool = Field(default=True,
        description=(
            "AD-746 Layer 1: when ON, ambient camera + screen frames "
            "are buffered within ``fusion_window_ms`` and forwarded as "
            "a single fused vision_observation. Reduces AD-733c-6 "
            "budget burn + AD-541b anchor noise when both sources "
            "stream. Hot-reload."
        ),
    )
    fusion_window_ms: int = Field(default=800, ge=100, le=5000,
        description=(
            "AD-746 Layer 1: debounce window for cross-source fusion. "
            "Pipecat default. Hot-reload."
        ),
    )

    @field_validator("vision_supervisor_strategy")
    @classmethod
    def _validate_supervisor_strategy(cls, v: str) -> str:
        allowed = {"ahash", "motion", "scene_change", "never", "always"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(
                f"vision_supervisor_strategy must be one of {sorted(allowed)}, got {v!r}"
            )
        return v


class LipSyncConfig(BaseModel):
    """AD-721b-1 — Server-side lip-sync backend selection.

    Default: ``heuristic`` — the AD-721b v1 text→viseme driver in
    ``ui/src/audio/lipSyncTrack.ts``. Operator opts in to ``rhubarb``
    by setting ``backend: "rhubarb"`` AND providing the binary at
    ``binary_path``. If the binary is missing or a probe fails, the
    system logs WARNING and degrades to the heuristic path — speech
    must NEVER stop animating because of a viseme failure.
    """

    enabled: bool = True
    """Master switch for the lip-sync pipeline. ``False`` disables both
    backends — CrewVRM falls back to the AD-721 D5 amplitude path."""

    backend: Literal["heuristic", "rhubarb"] = "heuristic"
    """``heuristic``: AD-721b v1 text→viseme. ``rhubarb``: subprocess to
    rhubarb-lip-sync for phonetic alignment of real audio."""

    binary_path: str = "tools/rhubarb/rhubarb"
    """Path (relative to repo root or absolute) to the rhubarb binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary themselves; the repo
    never ships it (gitignored under ``/tools/``)."""

    timeout_seconds: float = 30.0
    """Subprocess timeout. rhubarb on a 5-10s utterance typically takes
    1-3s; the default leaves ample headroom for cold disk reads. Tier-2
    log-and-degrade on TimeoutExpired — falls back to heuristic."""

    ffmpeg_binary_path: str = "tools/ffmpeg/ffmpeg"
    """AD-721b-1a: optional ffmpeg binary for converting non-WAV/OGG audio
    (e.g. Chrome MediaRecorder's audio/webm) to rhubarb's required format.
    When the binary is missing, generate_visemes honest-degrades to the
    heuristic lip-sync path (BF-292 contract preserved). Operator places
    the binary; the repo never ships it (gitignored under ``/tools/``).
    License posture: ffmpeg is LGPL-2.1+ / GPL-2+; the operator-provided
    binary keeps ProbOS distribution clean."""


class TTSConfig(BaseModel):
    """AD-738 — Server-side TTS backend selection.

    Default: ``browser`` — every ``speakResponse()`` call uses
    ``SpeechSynthesisUtterance`` (today's behaviour, zero regression).
    Operator opts in to ``piper`` by setting ``backend: "piper"`` AND
    placing the binary at ``binary_path`` AND placing the voice model
    files at ``tools/piper/voices/<voice_model>.onnx`` (+ ``.onnx.json``).
    Any failure (binary missing, model missing, subprocess error,
    timeout) returns honest-degrade — the browser falls back to
    SpeechSynthesisUtterance. Speech must NEVER stop because of a TTS
    failure.
    """

    enabled: bool = True
    """Master switch for the server-side TTS pipeline. ``False`` makes
    ``POST /api/avatars/tts`` return ``{"backend": "disabled"}``; the
    browser falls back to SpeechSynthesisUtterance."""

    backend: Literal["browser", "piper"] = "browser"
    """``browser``: server returns ``{"backend": "disabled"}``, browser
    uses SpeechSynthesisUtterance (default — zero behaviour change for
    operators who don't install Piper). ``piper``: subprocess wrapper
    around the piper binary."""

    binary_path: str = "tools/piper/piper"
    """Path (relative to repo root or absolute) to the piper binary.
    On Windows the wrapper auto-appends ``.exe`` if the literal path
    does not exist. Operator places the binary; the repo never ships
    it (gitignored under ``/tools/``)."""

    voice_model: str = "en_US-amy-medium"
    """Voice model name. Operator places ``tools/piper/voices/<name>.onnx``
    AND ``tools/piper/voices/<name>.onnx.json`` (Piper requires both).
    Default ``en_US-amy-medium`` is MIT-licensed (verified on the
    rhasspy/piper-voices model card). Operator who picks a different
    voice is responsible for the license check until AD-738a surfaces
    a license display in the per-agent voice selector."""

    timeout_seconds: float = 10.0
    """Subprocess timeout. Piper on a sentence-length input typically
    takes 0.3-1.5s on CPU; default leaves ample headroom for cold
    model load on first call. Tier-2 log-and-degrade on TimeoutExpired —
    endpoint returns honest-degrade, browser falls back."""

    # AD-738e (BF-285 2026-05-13): prosody controls. Piper-VITS exposes
    # three inference knobs plus a sentence-silence gap. Defaults below
    # are tuned for *more* natural variation than Piper's safe-minimum
    # defaults — Captain reported "monotone" + "strange consistent rhythm"
    # on the upstream defaults (noise_scale=0.667, noise_w=0.8,
    # sentence_silence=0.2). Tuning higher trades a touch of clarity for
    # noticeable expressiveness.

    noise_scale: float = 0.85
    """Piper ``--noise_scale``. Generator noise — controls pitch/expression
    variation. Higher = more expressive, less robotic. Piper upstream
    default 0.667. Range 0.0-1.5. At 0 the voice is robotically uniform;
    at 1.5 it starts to wobble unnaturally."""

    length_scale: float = 1.0
    """Piper ``--length_scale``. Phoneme duration multiplier. >1.0 = slower
    speech, <1.0 = faster. Operator-tunable for users who prefer slower
    diction; per-agent AD-735 ``rate`` (browser-side ``playbackRate``)
    still applies on top of this. Piper upstream default 1.0."""

    noise_w: float = 1.0
    """Piper ``--noise_w``. Phoneme-width (duration) variation. Higher =
    more natural rhythm because each phoneme's duration varies. Piper
    upstream default 0.8. Range 0.0-1.5. The Captain's "strange consistent
    rhythm" comment maps directly to this knob — at 0.8 every phoneme is
    the same length; at 1.0+ rhythm breathes."""

    sentence_silence: float = 0.35
    """Piper ``--sentence_silence``. Seconds of silence inserted after
    each sentence boundary. Piper upstream default 0.2. A small bump
    here adds natural pauses for paragraph-style replies. Range 0.0-2.0."""


class A2APeerConfig(BaseModel):
    """AD-480e: Outbound A2A peer registration entry."""

    peer_url: str
    auth_token: str = ""


class FederationA2AConfig(BaseModel):
    """AD-480d / AD-480e: Inbound A2A server + outbound A2A clients."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8766, ge=1, le=65535)
    agent_card_path: str = "/.well-known/agent.json"
    outbound_peers: list[A2APeerConfig] = Field(default_factory=list)


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


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus
    # AD-443c: Memory portability tier for incoming agent transfers.
    # CLEAN_ROOM (default) means foreign agents arrive with sovereign identity
    # but zero episodic memory — safest default. SELECTIVE filters by tag.
    # FULL accepts all episodes verbatim. Per-agent overrides via Standing Orders.
    memory_policy: str = "clean_room"
    # AD-443c: Tag whitelist for SELECTIVE memory policy. Ignored for the
    # other two policies. Empty list with SELECTIVE means no episodes pass.
    memory_policy_selective_tags: list[str] = []

    # AD-480: Cross-ecosystem federation adapters.
    mcp_server: FederationMCPServerConfig = Field(
        default_factory=FederationMCPServerConfig
    )
    a2a: FederationA2AConfig = Field(default_factory=FederationA2AConfig)
    peer_trust: FederationPeerTrustConfig = Field(
        default_factory=FederationPeerTrustConfig
    )
    # AD-479f / AD-479g / AD-479h: hardening surfaces (all default-False or
    # additive-only).
    tls: FederationTLSConfig = Field(default_factory=FederationTLSConfig)
    discovery: FederationDiscoveryConfig = Field(
        default_factory=FederationDiscoveryConfig
    )
    cluster_monitor: FederationClusterMonitorConfig = Field(
        default_factory=FederationClusterMonitorConfig
    )
    # AD-479b ranking gate (default 0.0 keeps W87/W89 baseline behavior).
    min_peer_trust_score: float = 0.0
    # AD-607g federation outbound privacy filter. Default ``shared_trust``
    # honors the AD-479b peer-trust ranking surface that W91 shipped.
    memory_access_policy: str = "shared_trust"
    shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)

    @field_validator("memory_access_policy")
    @classmethod
    def _validate_memory_access_policy(cls, v: str) -> str:
        """AD-607g: validate federation outbound privacy policy values."""
        valid = {"public", "shared_trust", "private"}
        if v not in valid:
            raise ValueError(
                f"memory_access_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v

    @field_validator("memory_policy")
    @classmethod
    def _validate_memory_policy(cls, v: str) -> str:
        from probos.mobility import MemoryPolicy
        valid = {p.value for p in MemoryPolicy}
        if v not in valid:
            raise ValueError(
                f"memory_policy must be one of {sorted(valid)}; got {v!r}"
            )
        return v


class SelfModConfig(BaseModel):
    """Self-modification configuration."""

    enabled: bool = False  # Disabled by default — opt-in capability
    require_user_approval: bool = True  # Human must confirm before agent goes live
    probationary_alpha: float = 1.0  # Beta prior alpha for self-created agents
    probationary_beta: float = 3.0  # Beta prior beta → E[trust] = 0.25
    max_designed_agents: int = 5  # Maximum self-created agent types in system
    sandbox_timeout_seconds: float = 60.0  # Timeout for sandbox test execution (LLM-backed agents need more)
    allowed_imports: list[str] = [
        "asyncio", "pathlib", "json", "os", "re", "datetime",
        "typing", "dataclasses", "collections", "math", "hashlib",
        "urllib.parse", "base64", "csv", "io", "tempfile",
    ]
    forbidden_patterns: list[str] = [
        r"subprocess", r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
        r"eval\s*\(", r"exec\s*\(", r"__import__",
        r"open\s*\(.*['\"][waxWAX]", r"socket\b", r"ctypes\b",
        # BF-086: Close security gaps found by bypass testing
        r"os\.system", r"os\.popen", r"os\.exec", r"os\.kill",
        r"\.write_text\s*\(", r"\.write_bytes\s*\(",
        r"\.unlink\s*\(",
        r"__builtins__",
        r"compile\s*\(",
    ]
    research_enabled: bool = False  # Opt-in web research before design
    research_domain_whitelist: list[str] = [
        "docs.python.org",
        "pypi.org",
        "developer.mozilla.org",
        "learn.microsoft.com",
    ]
    research_max_pages: int = 3
    research_max_content_per_page: int = 2000


class QAConfig(BaseModel):
    """SystemQAAgent configuration."""

    enabled: bool = True                    # QA runs by default when self-mod is enabled
    smoke_test_count: int = 5               # Number of synthetic intents per new agent
    timeout_per_test_seconds: float = 10.0  # Per-intent timeout
    total_timeout_seconds: float = 30.0     # Total QA budget per agent
    pass_threshold: float = 0.6             # Fraction of tests that must pass (3/5)
    trust_reward_weight: float = 1.0        # Weight for trust_network.record_outcome on success
    trust_penalty_weight: float = 2.0       # Weight for trust_network.record_outcome on failure
    flag_on_fail: bool = True               # Emit warning event if agent fails QA
    auto_remove_on_total_fail: bool = False  # Remove agent if 0/N pass


class KnowledgeConfig(BaseModel):
    """Persistent knowledge store configuration."""

    enabled: bool = True
    repo_path: str = ""             # Empty = ~/.probos/knowledge/
    auto_commit: bool = True        # Auto-commit on writes
    commit_debounce_seconds: float = 5.0  # Batch writes within this window
    max_episodes: int = 1000        # Max episodes to persist (oldest evicted)
    max_workflows: int = 200        # Max workflow cache entries to persist
    restore_on_boot: bool = True    # Warm boot from existing repo


class KnowledgeLoadingConfig(BaseModel):
    """AD-585: Tiered knowledge loading configuration."""

    enabled: bool = True

    # Per-tier token budgets (approximate: 1 token is about 4 chars)
    ambient_token_budget: int = 200
    contextual_token_budget: int = 400
    on_demand_token_budget: int = 600

    # Per-tier max age in seconds (0 = always fresh)
    ambient_max_age_seconds: float = 300.0
    contextual_max_age_seconds: float = 60.0
    on_demand_max_age_seconds: float = 0.0  # Always fresh

    # Intent-to-knowledge category mapping.
    # Keys are intent types; values are KnowledgeStore subdirectory names.
    intent_knowledge_map: dict[str, list[str]] = Field(default_factory=lambda: {
        "security_alert": ["trust", "agents"],
        "proactive_think": ["episodes", "proactive"],
        "ward_room_notification": ["episodes", "agents"],
        "direct_message": ["episodes", "agents"],
    })


class RecordsConfig(BaseModel):
    """Ship's Records configuration (AD-434)."""

    enabled: bool = True
    repo_path: str = ""  # Empty = {data_dir}/ship-records/
    auto_commit: bool = True
    commit_debounce_seconds: float = 5.0
    max_episodes_per_hour: int = 20  # Rate limit for notebook writes
    # AD-550: Notebook dedup settings
    notebook_dedup_enabled: bool = True
    notebook_similarity_threshold: float = 0.8
    notebook_staleness_hours: float = 72.0
    notebook_max_scan_entries: int = 20
    # AD-552: Notebook self-repetition detection
    notebook_repetition_enabled: bool = True
    notebook_repetition_window_hours: float = 48.0
    notebook_repetition_threshold_count: int = 3
    notebook_repetition_novelty_threshold: float = 0.2
    notebook_repetition_suppression_count: int = 5
    # AD-553: Notebook metric capture
    notebook_metrics_enabled: bool = True
    # AD-554: Real-time convergence/divergence detection
    realtime_convergence_enabled: bool = True
    realtime_convergence_threshold: float = 0.5
    realtime_divergence_threshold: float = 0.3
    realtime_convergence_staleness_hours: float = 72.0
    realtime_max_scan_per_agent: int = 5
    realtime_min_convergence_agents: int = 2
    realtime_min_convergence_departments: int = 2
    # AD-583: Wrong convergence detection
    convergence_independence_threshold: float = 0.3
    # AD-555: Notebook quality metrics
    notebook_quality_enabled: bool = True
    notebook_quality_low_threshold: float = 0.3
    notebook_quality_warn_threshold: float = 0.5
    notebook_staleness_alert_rate: float = 0.7


class ArchiveConfig(BaseModel):
    """Ship's Archive configuration (AD-524)."""

    enabled: bool = True
    db_path: str = ""


class TelemetryConfig(BaseModel):
    """Ship's Telemetry configuration (AD-461)."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    max_samples_per_bucket: int = 1000


class PostBudgetTelemetryConfig(BaseModel):
    """BF-238: Post-budget exhaustion telemetry configuration."""

    enabled: bool = True
    exhaustion_alert_threshold: float = 0.5  # Per-agent rate that triggers WARN
    min_samples_for_alert: int = 10          # Suppress alert below this invocation count
    recent_suppressions_max: int = 100       # Ring buffer size for ops review


class ConfidenceConfig(BaseModel):
    """AD-444: Knowledge confidence scoring configuration."""

    enabled: bool = True
    default_confidence: float = 0.5
    confirm_delta: float = 0.15
    contradict_delta: float = 0.25
    auto_supersede_threshold: float = 0.1
    auto_apply_threshold: float = 0.8
    suppress_threshold: float = 0.5


class LintConfig(BaseModel):
    """AD-563: Knowledge linting configuration."""

    enabled: bool = True
    min_coverage_per_department: int = 5
    inconsistency_keywords: dict[str, str] = Field(default_factory=lambda: {
        "increased": "decreased",
        "improved": "degraded",
        "rising": "falling",
        "positive": "negative",
        "success": "failure",
    })


class QualityTriggerConfig(BaseModel):
    """AD-564: Quality-triggered forced consolidation configuration."""

    enabled: bool = True
    min_quality_threshold: float = 0.4
    max_stale_rate: float = 0.3
    max_repetition_rate: float = 0.2
    cooldown_seconds: float = 1800.0
    max_forced_per_day: int = 5


class QualityRouterConfig(BaseModel):
    """AD-565: Quality-informed routing configuration."""

    enabled: bool = True
    min_weight: float = 0.5
    max_weight: float = 1.5
    concern_threshold: float = 0.3


class OrientationConfig(BaseModel):
    """AD-567g: Cognitive re-localization configuration."""

    enabled: bool = True
    orientation_window_seconds: float = 600.0  # 10 minutes
    cold_start_full_orientation: bool = True
    warm_boot_orientation: bool = True
    proactive_supplement: bool = True
    populate_watch_section: bool = True
    populate_ward_room_department: bool = True
    populate_event_log_window: bool = True


class SocialVerificationConfig(BaseModel):
    """AD-567f: Social Verification Protocol configuration."""

    enabled: bool = True
    # Corroboration
    corroboration_threshold: float = 0.4  # Score above this = corroborated
    corroboration_max_agents: int = 5  # Denominator for agent count scoring
    corroboration_min_confidence: float = 0.3  # Anchor confidence gate for matches
    # Cascade detection
    cascade_enabled: bool = True
    cascade_independence_threshold: float = 0.3  # Below this = cascade risk
    cascade_cooldown_seconds: float = 300.0  # Dedup window for cascade alerts
    # Provenance (AD-662)
    anomaly_window_discount: float = 0.5  # 0.0-1.0: weight discount for anomaly window pairs
    # Provenance validation (AD-665)
    provenance_version_independence_weight: float = 0.7  # 0.0=reject, 1.0=full independence
    provenance_validation_enabled: bool = True  # Master toggle for AD-665 graded validation
    # Privacy
    expose_episode_content: bool = False  # MUST stay False — privacy boundary


class AnomalyWindowConfig(BaseModel):
    """Anomaly window detection configuration (AD-673)."""

    enabled: bool = True
    max_window_duration_seconds: float = 1800.0
    lookback_seconds: float = 60.0


class SourceTracingConfig(BaseModel):
    """AD-583g: Ward Room echo detection and source tracing."""

    echo_min_chain_length: int = 3
    echo_similarity_threshold: float = 0.4
    echo_analysis_enabled: bool = True


class ObservableStateConfig(BaseModel):
    """AD-583f: Observable state verification."""

    verification_enabled: bool = True
    max_claims_per_thread: int = 10


class PredictiveBranchingConfig(BaseModel):
    """AD-633 v1: Predictive Cognitive Branching.

    Default-False — speculation actually consumes tokens (separate budget pool,
    but still real LLM cost when SpeculationExecutor dispatches). Operator
    opt-in. AD-695 default-False precedent applies.
    """

    enabled: bool = False
    cache_ttl_seconds: float = Field(default=60.0, ge=1.0)
    cache_max_entries: int = Field(default=128, ge=1)
    speculation_tokens_per_window: int = Field(default=2000, ge=0)
    speculation_window_seconds: float = Field(default=300.0, ge=1.0)
    flush_rate_feedback_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    flush_rate_window_seconds: float = Field(default=3600.0, ge=1.0)
    accuracy_ring_size: int = Field(default=100, ge=10)
    cheap_tier_min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    standard_tier_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    anticipatory_tier_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class SelfImprovementConfig(BaseModel):
    """AD-482 v1: Self-improvement pipeline (proposal -> approval -> QA -> evolution -> versioning).

    Default-False -- operator opt-in. The pipeline spawns real QA agents, opens a
    new ChromaDB collection, and writes promoted agents to
    ``src/probos/agents/designed/``. AD-633 / AD-695 default-False precedent.
    """

    enabled: bool = False
    qa_pool_size: int = Field(default=3, ge=1, le=8)
    iteration_cap: int = Field(default=5, ge=1, le=20)
    evolution_half_life_seconds: float = Field(default=2592000.0, ge=1.0)  # 30 days
    evolution_collection_name: str = "self_improvement_lessons"
    persistence_root_dir: str = "src/probos/agents/designed"


class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration."""

    token_budget: int = 3000  # Max tokens for working memory context
    max_recent_actions: int = 10  # Ring buffer capacity
    max_recent_observations: int = 5
    max_recent_conversations: int = 5
    max_events: int = 10
    proactive_budget: int = 1500  # Lower budget for proactive (supplemental)
    stale_threshold_hours: float = 24.0  # Entries older than this pruned on restore
    conclusion_ttl_seconds: float = 1800.0
    max_conclusions: int = 20
    duty_budget: int = 600
    social_budget: int = 800
    ship_budget: int = 800
    engagement_budget: int = 800


class MemoryBudgetConfig(BaseModel):
    """AD-573: Memory budget accounting across recall tiers."""

    enabled: bool = True
    total_budget_tokens: int = 4650
    l0_budget: int = 150
    l1_budget: int = 3000
    l2_budget: int = 1000
    l3_budget: int = 500


class ConsultationConfig(BaseModel):
    """AD-594: Crew Consultation Protocol configuration."""

    enabled: bool = True
    timeout_seconds: float = 30.0
    max_consultations_per_agent_per_hour: int = 20
    max_pending_requests: int = 10
    expert_selection_max_candidates: int = 5
    weight_capability_match: float = 0.5
    weight_trust: float = 0.3
    weight_billet_relevance: float = 0.2


class ExpertiseConfig(BaseModel):
    """AD-600: Transactive Memory expertise directory configuration."""

    enabled: bool = True
    max_topics_per_agent: int = 50
    min_confidence: float = 0.1
    decay_rate: float = 0.95
    top_k_experts: int = 3


class QuestionAdaptiveConfig(BaseModel):
    """AD-602: Question-adaptive retrieval strategy configuration."""

    enabled: bool = True
    strategy_overrides: dict[str, dict] = Field(default_factory=dict)


class SpreadingActivationConfig(BaseModel):
    """AD-604: Spreading activation / multi-hop retrieval configuration."""

    enabled: bool = True
    max_hops: int = 2
    k_per_hop: int = 5
    hop_decay_factor: float = 0.6
    min_anchor_fields: int = 2


class ThoughtStoreConfig(BaseModel):
    """AD-606: Think-in-Memory thought storage configuration."""

    enabled: bool = True
    min_importance: int = 5
    max_thoughts_per_cycle: int = 3


class DistillationConfig(BaseModel):
    """AD-609: Multi-faceted distillation configuration."""

    enabled: bool = True
    min_failure_cluster_size: int = 3
    comparative_enabled: bool = True


class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management."""

    enabled: bool = True
    decay_half_life_seconds: float = 3600.0
    forget_threshold: float = 0.05
    min_entries_per_buffer: int = 2
    audit_enabled: bool = True
    cycle_interval_seconds: float = 300.0
    triage_fullness_threshold: float = 0.8
    triage_base_score: float = 0.3


class ReconsolidationConfig(BaseModel):
    """AD-574: Episodic decay reconsolidation scheduling."""

    enabled: bool = True
    base_intervals_hours: list[float] = Field(default_factory=lambda: [1.0, 6.0, 24.0, 72.0, 168.0, 720.0])
    importance_scale_factor: float = 0.1
    max_scheduled: int = 500


class StorageGateConfig(BaseModel):
    """AD-610: Utility-based storage gating - write-time validation."""

    enabled: bool = True
    duplicate_threshold: float = 0.95
    utility_floor: float = 0.2
    recent_window: int = 50
    contradiction_check_enabled: bool = True


class RetroactiveConfig(BaseModel):
    """AD-608: Retroactive memory evolution - store-time metadata propagation."""

    enabled: bool = True
    neighbor_k: int = 5
    similarity_threshold: float = 0.7
    max_relations_per_episode: int = 10
    propagate_watch_section: bool = True
    propagate_department: bool = True


class PinnedKnowledgeConfig(BaseModel):
    """AD-579a: Pinned knowledge buffer configuration."""

    enabled: bool = True
    max_tokens: int = 150
    max_pins: int = 10
    default_ttl_seconds: float = 86400.0


class TemporalValidityConfig(BaseModel):
    """AD-579b: Temporal validity windows for episodic memory."""

    enabled: bool = True
    default_validity_hours: float = 0.0


class TaskContextConfig(BaseModel):
    """Task-contextual standing orders configuration (AD-586)."""

    enabled: bool = True
    orders_dir: str = "config/task_orders"
    max_tokens: int = 500


class SalienceConfig(BaseModel):
    """AD-668: Salience filter for working memory promotion."""

    enabled: bool = True
    weights: dict[str, float] = {
        "relevance": 0.30,
        "recency": 0.25,
        "novelty": 0.15,
        "urgency": 0.20,
        "social": 0.10,
    }
    threshold: float = 0.3
    background_max_entries: int = 50


class SensoriumConfig(BaseModel):
    """AD-666: Agent Sensorium tracking configuration."""

    enabled: bool = True
    token_budget_warning: int = 10000


class RuntimeOverridesConfig(BaseModel):
    """Runtime override layer configuration (AD-468)."""

    enabled: bool = True
    store_filename: str = "runtime_overrides.json"


class OrdersConfig(BaseModel):
    """Chain-of-command order configuration (AD-440)."""

    enabled: bool = True
    max_active_per_post: int = Field(default=8, ge=1, le=64)
    default_ttl_seconds: float = Field(default=3600.0, ge=60.0, le=86400.0)


class ValidationFrameworkConfig(BaseModel):
    """Validation framework configuration (AD-451)."""

    enabled: bool = True
    metadata_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    min_confidence_delta: float = Field(default=0.20, ge=0.0, le=1.0)


class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458 / AD-458b)."""

    enabled: bool = True
    # AD-458b: optional LLM-tier reachability and token-budget checks.
    # Default-True on _check_enabled flags so the wiring is live; the
    # token-budget check is harmless under AD-469 v1 (`check_budgets()`
    # returns `[]`) and activates automatically once AD-469b lands.
    # `token_budget_blocking` defaults False — warn rather than abort
    # until operator confidence builds.
    llm_tier_check_enabled: bool = True
    required_llm_tier: str = "deep"
    token_budget_check_enabled: bool = True
    token_budget_blocking: bool = False


class EngineeringConfig(BaseModel):
    """Engineering crew configuration (AD-457)."""

    enabled: bool = True
    performance_interval_seconds: float = Field(default=10.0, ge=1.0)
    maintenance_interval_seconds: float = Field(default=300.0, ge=60.0)
    damage_control_cooldown_seconds: float = Field(default=60.0, ge=1.0)


class InfrastructureConfig(BaseModel):
    """Engineering infrastructure configuration (AD-466)."""

    enabled: bool = True
    backup_enabled: bool = True
    backup_subdir: str = "backups"

class DegradationConfig(BaseModel):
    """Saucer separation / graceful degradation (AD-459 / AD-459b).

    AD-459 v1 shipped the read-only coordinator (always-wired, no
    operator-tunable fields). AD-459b adds active subsystem pause/resume
    hooks gated by ``auto_pause_enabled`` (default False per Wave-10
    convention #14 — transitional flag, default off until validated in
    rehearsal). When True, finalize.py registers ``dream_scheduler`` and
    ``proactive_loop`` adopters via ``LifecycleAdapter``; the manager
    invokes their pause/resume callbacks on tier-mask transitions.

    Future: custom policies, stress-level thresholds, operator override
    for shed-ESSENTIAL emergency mode.
    """

    auto_pause_enabled: bool = False


class InfodynamicConfig(BaseModel):
    """Infodynamic telemetry configuration (AD-491)."""

    enabled: bool = True
    event_window_seconds: float = Field(default=3600.0, ge=60.0)
    trust_buckets: int = Field(default=10, ge=2, le=100)


class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b, AD-528c)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True
    # AD-528b: active rejection & metadata quarantine. Default False per
    # Convention #14 (transitional flag) + Convention #3 (default off until
    # caller integration lands at AD-528b-2). When True, finalize.py
    # constructs a GroundTruthRejectionGate that wraps the verifier; the
    # gate emits VERIFICATION_REJECTED + WORK_ITEM_QUARANTINED on the
    # rejection branch and writes a quarantine payload into the work item's
    # metadata under `quarantine_metadata_key`.
    active_rejection_enabled: bool = False
    quarantine_metadata_key: str = "ground_truth_quarantine"
    # AD-528c: trust-network feedback. Default False per Convention #14
    # (transitional flag) + Convention #3 (default off until fleet rehearsal
    # confirms no false-positive trust drops, AD-528c-1). When True,
    # finalize.py registers a GroundTruthTrustFeedback listener that
    # subscribes to VERIFICATION_PASSED + VERIFICATION_FAILED and calls
    # runtime.trust_network.record_outcome(...) — the public API that
    # internally stores raw (alpha, beta) per ProbOS principle 3.
    # VERIFICATION_REJECTED is NOT consumed in v1 (every REJECTED co-fires
    # with FAILED inside verifier.verify(); double-counting prevention).
    # REJECTED-aware weighting is deferred to AD-528c-1.
    trust_feedback_enabled: bool = False
    trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)
    trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)


class OperationsConfig(BaseModel):
    """Operations crew configuration (AD-467)."""

    enabled: bool = True
    resource_interval_seconds: float = Field(default=30.0, ge=1.0)
    resource_emit_interval_seconds: float = Field(default=60.0, ge=10.0)
    scheduler_interval_seconds: float = Field(default=60.0, ge=10.0)
    coordinator_interval_seconds: float = Field(default=60.0, ge=10.0)


class ModelRoutingConfig(BaseModel):
    """Model routing configuration (AD-463)."""

    enabled: bool = True
    cost_ceiling_per_million_output_tokens: float | None = None  # USD; None disables


class ReadyRoomConfig(BaseModel):
    """Captain's Ready Room configuration (AD-475)."""

    enabled: bool = True
    idea_store_filename: str = "ready_room/ideas.json"
    wardroom_channel_id: str = "ready_room"


class DepartmentCognitiveProfile(BaseModel):
    """AD-656: per-department cognitive profile overlay.

    Modulates retrieval depth, similarity threshold, and context budget
    for the cognitive chain on a per-department basis.
    """

    recall_depth: int = Field(default=5, ge=1, le=20)
    recall_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    context_token_budget: int = Field(default=4000, ge=500)


class DepartmentProfilesConfig(BaseModel):
    """AD-656: dict of department-name -> DepartmentCognitiveProfile."""

    profiles: dict[str, DepartmentCognitiveProfile] = Field(default_factory=dict)


class EPSDepartmentConfig(BaseModel):
    """One department's EPS allocation entry (AD-469)."""

    name: str
    percent: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=5, ge=1, le=10)


class EPSConfig(BaseModel):
    """EPS - Compute/Token Distribution (AD-469)."""

    enabled: bool = True
    window_seconds: float = Field(default=60.0, ge=10.0)
    over_budget_threshold: float = Field(default=1.25, ge=1.0, le=10.0)
    departments: list[EPSDepartmentConfig] = Field(
        default_factory=lambda: [
            EPSDepartmentConfig(name="engineering", percent=0.30, priority=3),
            EPSDepartmentConfig(name="science", percent=0.20, priority=4),
            EPSDepartmentConfig(name="medical", percent=0.15, priority=2),
            EPSDepartmentConfig(name="security", percent=0.15, priority=2),
            EPSDepartmentConfig(name="operations", percent=0.10, priority=4),
            EPSDepartmentConfig(name="other", percent=0.10, priority=6),
        ]
    )


class MCPServerConfig(BaseModel):
    """One MCP server registration entry (AD-449)."""

    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class MCPConfig(BaseModel):
    """MCP Bridge configuration (AD-449)."""

    enabled: bool = True
    request_timeout_seconds: float = Field(default=30.0, ge=1.0)
    servers: list[MCPServerConfig] = Field(default_factory=list)


class ObservabilityBridgeConfig(BaseModel):
    """AD-641a: Observability Bridge configuration."""

    enabled: bool = True
    publish_interval_seconds: float = 60.0
    system_channel: str = "system_observability"


class ThresholdAlertConfig(BaseModel):
    """AD-695: Threshold-driven bridge alerts.

    Default-False — opt-in until a node operator chooses to surface health
    breaches into the ward room. Replaces the AD-641a continuous-posting
    loop with on-breach-only notifications.
    """

    enabled: bool = False
    pool_saturation_floor: float = Field(default=0.9, ge=0.0, le=1.0)
    degradation_min_severity: str = "degraded"
    attention_queue_depth: int = Field(default=20, ge=0)
    dedup_window_seconds: float = Field(default=300.0, ge=1.0)


class WardRoomHebbianConfig(BaseModel):
    """AD-641b: Ward Room Hebbian Router configuration."""

    enabled: bool = True
    learning_rate: float = 0.10
    decay_factor: float = 0.99


class EngineeringSensorsConfig(BaseModel):
    """AD-641f: Engineering Chief Observability configuration."""

    enabled: bool = True
    report_interval_seconds: float = 60.0
    auto_start_periodic_report: bool = False


class LearnedShortcutsConfig(BaseModel):
    """AD-641e: LearnedShortcut Registry configuration."""

    enabled: bool = True
    register_workflow_cache: bool = True


class ThreadPriorityConfig(BaseModel):
    """AD-641c: Ward Room Thread Priority configuration."""

    enabled: bool = True
    weight_captain: float = 0.30
    weight_unresolved: float = 0.20
    weight_cross_department: float = 0.15
    weight_recency: float = 0.20
    weight_endorsement: float = 0.15
    captain_callsign: str = "Captain"


class DeliberationConfig(BaseModel):
    """AD-641d: Crew Deliberation Protocol configuration."""

    enabled: bool = True
    captain_callsign: str = "Captain"


class SecurityInfraConfig(BaseModel):
    """Security infrastructure configuration (AD-456 + AD-456b).

    Distinct from ``SecurityConfig`` (AD-455) which configures threat detection,
    input validation, trust integrity, and red-team coordination.
    """

    secrets_persistence_enabled: bool = True
    secrets_store_filename: str = "secrets.json"
    egress_enabled: bool = True
    egress_deny_by_default: bool = True  # v1: real-signal default per no-theater
    audit_enabled: bool = True

    # AD-456b: Runtime Sandboxing
    sandbox_enabled: bool = True
    sandbox_default_wall_timeout_seconds: float = 30.0
    sandbox_default_memory_peak_mb: float = 256.0
    # AD-456b: Egress active enforcement (v1 default False — preserves AD-456
    # consultation-only behavior on existing deployments; flip to True at upgrade
    # time after reviewing allowlist coverage. AD-456b-7 will flip default to True
    # once fleet-wide allowlist coverage is verified.).
    egress_active_enforcement: bool = False

    # AD-456c: Per-tier credential lookup gate (v1 default False — preserves
    # AD-456 ungated-lookup behavior on existing deployments; flip to True at
    # upgrade time after reviewing per-spec ``min_tier`` coverage. AD-456c-5
    # will flip default to True once fleet-wide ``min_tier`` coverage is
    # verified AND caller-side ``tier=`` argument propagation (AD-456c-2)
    # has landed in all production credential-using agent paths.).
    credential_tier_enforcement: bool = False

    # AD-456d: AuditLog SQLite persistence (v1 default False — preserves
    # AD-456 in-memory-only audit chain on existing deployments; flip to
    # True at upgrade time after rehearsing rehydrate-on-boot against a
    # production-shaped audit trail. AD-456d-4 will flip default to True
    # once AD-456d-1 (shutdown-flush hook) lands.).
    audit_persistence_enabled: bool = False
    audit_persistence_filename: str = "audit_log.db"
    audit_retention_days: int = 90


class PermissionsConfig(BaseModel):
    """AD-711: declarative permission lists (enforcement deferred to AD-711-1)."""

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class AuthConfig(BaseModel):
    """AD-722b-1: minimal crew-scope authentication.

    v1 is single-secret. ``crew_scope_token`` empty (default) disables
    auth entirely - backward-compatible with single-operator HXI installs.
    """

    crew_scope_token: str = Field(
        default="",
        description=(
            "Shared bearer token for crew-scope auth on telemetry surfaces. "
            "Empty string disables auth. Set via config/system.yaml to opt in."
        ),
    )


class SecurityConfig(BaseModel):
    """Security Team configuration (AD-455).

    AD-711 (Wave 130): adds ``profile`` and ``permissions`` fields for
    claude-bootstrap-derived secure-by-default init wizard. ``profile`` is
    a declarative marker; ``permissions.deny`` is consumed at the wizard +
    doctor layer today and at the runtime enforcement layer in AD-711-1.
    """

    enabled: bool = True
    max_payload_bytes: int = Field(default=65536, ge=1024)
    rate_window_seconds: float = Field(default=60.0, ge=1.0)
    rate_max_requests: int = Field(default=60, ge=1)
    max_threat_severity: float = Field(default=0.80, ge=0.0, le=1.0)
    burst_window_seconds: float = Field(default=60.0, ge=1.0)
    burst_threshold: int = Field(default=20, ge=2)
    campaign_interval_seconds: float = Field(default=3600.0, ge=60.0)
    # AD-607: Memory security framework (Wave 92).
    memory: "MemorySecurityConfig" = Field(default_factory=lambda: MemorySecurityConfig())
    # AD-711: claude-bootstrap-derived security profile + permissions deny-list.
    profile: Literal["strict", "relaxed"] = "strict"
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    # AD-753: unattended permission posture for personal-desktop scope.
    permission_mode: Literal["manual", "autopilot"] = "manual"
    policy_engine_class: str = "NullPolicyEngine"


class MemorySecurityConfig(BaseModel):
    """AD-607: Memory security framework configuration.

    All ``enforce_*`` flags default-False per the AD-695 + W82 + W88 + W91
    default-False precedent — v1 ships observational by default.
    """

    enforce_recall: bool = False        # AD-607a opt-in: drop anomalous episodes from recall
    enforce_provenance: bool = False    # AD-607b opt-in: reject provenance-gap episodes from recall
    enforce_leak_guard: bool = False    # AD-607d opt-in: redact response when leak suspected
    enforce_store: bool = False         # AD-607h opt-in: reject prompt-injection at store time
    anchor_mismatch_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dp_min_cohort_size: int = Field(default=3, ge=1)


class OnboardingConfig(BaseModel):
    """AD-442: Onboarding ceremony configuration."""

    enabled: bool = True
    activation_trust_threshold: float = 0.65
    naming_ceremony: bool = True  # If False, agents keep seed callsigns


class HolodeckBirthChamberConfig(BaseModel):
    """AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

    Default-False per AD-695 transitional-flag precedent: enabling the
    chamber gates Ward Room subscription and proactive-loop dispatch
    behind 5-phase graduation, which is a meaningful behavior change.
    Operators flip ``enabled=True`` after Phase α validation (manual
    cohort under observation).
    """

    enabled: bool = False
    bypass_for_existing_agents: bool = True
    department_order: list[str] = Field(
        default_factory=lambda: [
            "security",
            "operations",
            "engineering",
            "science",
            "medical",
        ]
    )
    calibration_min_episodes: int = Field(default=5, ge=1)
    affective_baseline_check_enabled: bool = True
    auto_advance_enabled: bool = True
    auto_advance_poll_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=30.0
    )
    max_self_discovery_probe_attempts: int = Field(default=3, ge=1)

    @field_validator("department_order")
    @classmethod
    def _department_order_lowercase(cls, v: list[str]) -> list[str]:
        return [d.lower() for d in v]


class HolodeckScenarioConfig(BaseModel):
    """AD-539b: Holodeck scenario generation from skill gaps.

    Default-False per AD-695 transitional-flag precedent: enabling the
    bridge causes ``HolodeckGapBridge.bridge_gap_to_holodeck`` to
    register a runnable ``HolodeckGapDrill`` with the AD-477
    ``QualificationHarness`` for every classified knowledge gap that
    has a ``mapped_skill_id``. v1 ships dormant — operators flip
    ``enabled=True`` once an AD-486 cohort produces real ``GapReport``
    instances with non-empty ``mapped_skill_id`` to bridge against.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    category_fallback: str = "construction"
    persist_to_sqlite: bool = False
    data_subdir: str = "holodeck_scenarios"


class HolodeckTeamSimulationConfig(BaseModel):
    """AD-510: Holodeck team simulations — group discovery & collaboration.

    Default-False per AD-695 transitional-flag precedent: enabling the
    orchestrator causes ``TeamSimulationOrchestrator.start_simulation``
    to register a runnable ``TeamSimulationDrill`` with the AD-477
    ``QualificationHarness`` for every started simulation. v1 ships
    dormant — operators flip ``enabled=True`` once an AD-486 cohort
    reaches Phase α with crew-tier agents available across >=2
    departments to populate team rosters.
    """

    enabled: bool = False
    auto_register_with_harness: bool = True
    default_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    default_tier: int = Field(default=2, ge=1, le=3)
    enforce_required_departments: bool = True
    persist_to_sqlite: bool = False
    data_subdir: str = "team_simulations"


class NamingConfig(BaseModel):
    """Ship & crew naming conventions (AD-499)."""

    enabled: bool = True
    captain_ship_override: str = ""  # If non-empty, overrides seed selection
    extra_banned_words: list[str] = Field(default_factory=list)


class UtilityAgentsConfig(BaseModel):
    """Utility agent suite configuration (AD-252)."""

    enabled: bool = True  # Create utility CognitiveAgent pools at boot


class SoftwareEngineerSpecialistsConfig(BaseModel):
    """AD-476 v1 — opt-in pool registration for the five SWE specialists.

    Default ``enabled=False`` per AD-695 transitional-flag precedent: pool
    creation is a real cognitive-budget side-effect (five new agents at
    boot), so v1 ships dormant. Operators flip ``enabled=True`` after
    AD-546 wires the production chunk-routing call site.
    """

    enabled: bool = False
    pool_size_per_specialty: int = 1
    model_tier_overrides: dict[str, str] = Field(
        default_factory=lambda: {
            "backend": "deep",
            "frontend": "standard",
            "test": "fast",
            "infrastructure": "standard",
            "data": "deep",
        }
    )

    @field_validator("pool_size_per_specialty")
    @classmethod
    def _pool_size_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("pool_size_per_specialty must be >= 1")
        return v

    @field_validator("model_tier_overrides")
    @classmethod
    def _tier_values_valid(cls, v: dict[str, str]) -> dict[str, str]:
        valid_tiers = {"fast", "standard", "deep"}
        for specialty, tier in v.items():
            if tier not in valid_tiers:
                raise ValueError(
                    f"AD-476 model_tier_overrides[{specialty!r}]={tier!r} "
                    f"not in {sorted(valid_tiers)}"
                )
        return v


class NativeSWEHarnessConfig(BaseModel):
    """AD-549: Configuration for the native SWE agentic harness.

    Default-False on ``enabled`` per AD-695 transitional-flag precedent —
    pool wiring + tool registration happen unconditionally, but route
    selection in ``SoftwareEngineerAgent.perceive()`` requires opt-in.
    """

    enabled: bool = Field(
        default=False,
        description="Master gate. When False, builds route to existing native/visiting paths.",
    )
    eligibility_modify_only: bool = Field(
        default=True,
        description="Phase α default. Only modify-only builds (all targets exist) eligible.",
    )
    max_iterations: int = Field(default=25, ge=1, le=200)
    max_fix_iterations: int = Field(default=5, ge=1, le=20)
    token_budget: int | None = Field(default=None, ge=1024)
    compaction_threshold_pct: float = Field(default=0.8, ge=0.1, le=0.95)
    blocked_paths: list[str] = Field(
        default_factory=lambda: [
            "src/probos/security/",
            ".env",
            "config/sealed_modules.yaml",
        ],
        description="AD-548: Pre-hook denies tool calls touching these path substrings.",
    )


class GroupChatConfig(BaseModel):
    """AD-915: ad-hoc group-chat turn-taking facilitator.

    Defaults preserve AD-914 (all crew reply, once): the truncation cap is
    OFF (0) and the convergence gate cannot fire until a real exchange has
    accumulated (>= convergence_min_messages from >= convergence_min_agents).
    """

    max_speakers_per_turn: int = 0          # 0 = off (AD-914 all-at-once). >0 caps NON-mentioned speakers.
    convergence_enabled: bool = True
    convergence_similarity_threshold: float = 0.6   # AD-614 Jaccard precedent
    convergence_min_messages: int = 4       # min recent agent msgs before the gate can fire
    convergence_min_agents: int = 2         # min distinct agents in the recent window
    weight_mention: float = 0.40            # also a hard-include (see facilitator)
    weight_recency: float = 0.25            # anti-domination / fairness
    weight_department: float = 0.25
    weight_trust: float = 0.10
    # AD-958a: exploration / anti-rich-get-richer term (Minimal Authority axiom —
    # earned trust, everyone has a path). A trust-weighted facilitator risks
    # rich-get-richer: a high-trust agent keeps being surfaced and a low-trust
    # but domain-relevant agent never gets a chance to EARN trust. The
    # exploration bonus is a deterministic "optimism under uncertainty" (UCB-
    # style) term: ``weight_exploration * department_relevance * (1 - trust)`` —
    # the more relevant AND the LESS proven an agent is, the bigger the boost,
    # so a domain-relevant newcomer is surfaced to earn trust while a high-trust
    # agent (already carried by the trust term) gets ~0 extra. Bounded below the
    # mention weight so a direct address always still wins; NO randomness (the
    # facilitator stays pure + deterministic). Transitional flag (#14) — Pydantic
    # default 0.0 (OFF, ranking byte-identical to pre-AD-958a); system.yaml sets
    # the live value.
    weight_exploration: float = 0.0
    # AD-918: per-agent rate limit on agent-initiated group-chat creation.
    # Conservative defaults prevent a create-storm without blocking
    # legitimate ad-hoc collaboration. Reuses the BF-163 (60s DM cooldown)
    # + BF-257 (sliding-window budget) shape.
    agent_create_cooldown_seconds: float = 60.0   # min seconds between two creates by one agent
    agent_create_max_per_window: int = 5          # max creates per agent per window
    agent_create_window_seconds: float = 3600.0   # sliding window (1 hour)
    # AD-925: auto-create ONE task-linked workspace room when CrewTaskExecutor
    # fans a parent out to >=2 distinct crew. Transitional flag (wave-10 #14) —
    # ships OFF; the Captain flips it on after reviewing AD-925..927. Note the
    # crew pipeline that drives the executor (agentic_dispatch.orchestrator_enabled)
    # also ships OFF, so a zero-config boot creates no task rooms.
    auto_task_room_enabled: bool = False
    # AD-935: bounded synchronous agent-to-agent reactivity. When enabled, an
    # agent reply in a group chat fans to the OTHER crew for up to
    # ``max_agent_rounds`` extra rounds, gated by the AD-915 convergence gate
    # + [NO_RESPONSE]. Transitional flag (#14) — ships OFF; system.yaml flips it
    # on. Synchronous within the Captain turn (no live-refresh exists yet).
    agent_reactivity_enabled: bool = False
    max_agent_rounds: int = 2   # extra agent-only rounds after the Captain round (0 = AD-914 single round)
    # AD-951: turn-allocation rule 1a ("current speaker selects next"). When
    # enabled (and reactivity is on), an agent that DIRECTLY ADDRESSES a peer by
    # callsign in a group reply ("@yeo ..." or "Yeo, ...") hard-includes that peer
    # as a speaker in the next cascade round (overriding the per-turn cap +
    # convergence, still bounded by max_agent_rounds). Makes AD-950's "hand the
    # floor to a named peer" mechanical. Transitional flag (#14) — ships OFF;
    # system.yaml flips it on. Off => the AD-935 cascade is byte-identical.
    agent_next_speaker_selection_enabled: bool = False
    # AD-961: cascade-extend-on-address. A directed address ("Ezri, ...") in the
    # LAST normal cascade round (round == max_agent_rounds) would otherwise be
    # dropped — the addressed peer never gets a turn. When next-speaker selection
    # is on, allow up to this many EXTRA rounds PAST max_agent_rounds, each
    # consumed only by an unanswered directed address, so a hand-off is always
    # answered. Bounded so a chain of mutual hand-offs (Ezri->Yeo->Ezri...) can't
    # ping-pong forever. Only takes effect when agent_next_speaker_selection_enabled
    # is on (which is itself an operator opt-in), so the default of 1 never
    # changes a zero-config boot. 0 = disable the extension (pre-AD-961 behavior).
    max_address_extensions: int = 1
    # AD-970: agent-initiated kickoff. When an agent OPENS a group chat with a
    # first message (the AD-924 [GROUP_CHAT] tag), fan that opening out to the
    # OTHER participants so they can respond — the agent-initiated analogue of a
    # Captain turn, bounded by the SAME AD-935 backstops (cap / convergence /
    # [NO_RESPONSE] / max_agent_rounds). Fixes the Captain-reported bug where an
    # agent opened a room and addressed a peer who never responded (the opening
    # was role="agent" and AD-914 fan-out gates on role=="captain"). Lifts the
    # deliberate AD-918 "no auto-reply on create" boundary, now that the bounded
    # cascade exists. Transitional flag (#14) — ships OFF (zero-config boot keeps
    # the AD-918 quiet-create behavior); system.yaml flips it on.
    agent_initiated_kickoff_enabled: bool = False
    # AD-963a: broadcast turn-mode terminator. The AD-935 cascade stops at
    # ``max_agent_rounds`` or the convergence gate — right for a DISCUSSION
    # ("hash this out"), but wrong for a BROADCAST ("what do you ALL think?")
    # where the Captain wants EACH relevant crew member to answer ONCE, not
    # "until convergence" and not capped at two rounds. When enabled, a Captain
    # turn classified as a broadcast (a plural ask to the whole room) round-robins
    # every crew participant exactly once (relevance-ordered, each seeing prior
    # answers), naturally bounded by the participant count. A non-broadcast turn
    # (the default classification) is byte-identical to AD-935/961. Transitional
    # flag (#14) — ships OFF; system.yaml flips it on.
    broadcast_terminator_enabled: bool = False


class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready
    max_agent_rounds: int = 5           # AD-407d / BF-201: max consecutive agent-only rounds per thread
    agent_cooldown_seconds: float = 45  # AD-407d: cooldown for agent-triggered responses
    max_thread_posts: int = 50          # BF-201: total posts per thread (all authors)
    default_discuss_responder_cap: int = 3  # AD-424: Default max_responders for DISCUSS threads
    # AD-416: Retention & archival
    retention_days: int = 7                    # Regular posts older than this are pruned
    retention_days_endorsed: int = 30          # Posts with net_score > 0 retained longer
    retention_days_captain: int = 0            # 0 = indefinite retention for Captain posts
    archive_enabled: bool = True               # Write pruned posts to JSONL archive before deletion
    prune_interval_seconds: float = 86400.0    # How often to run pruning (default: daily)
    dm_exchange_limit: int = 15          # BF-257: lowered from 40 (BF-200's value) — 15 still allows substantive DM conversations
    dm_similarity_threshold: float = 0.6  # AD-614: Jaccard threshold for DM self-similarity suppression
    router_concurrency_limit: int = 10     # AD-616: max concurrent route_event() tasks
    event_coalesce_ms: int = 200           # AD-616: coalesce window for rapid-fire post events (0 = disabled)
    dm_response_budget: int = 6             # BF-257: max DM responses per agent per window
    dm_response_window_seconds: float = 600.0  # BF-257: sliding window (10 minutes)
    dm_pair_exchange_budget: int = 8        # BF-257: max exchanges per A<->B pair per window


class AssignmentConfig(BaseModel):
    """Dynamic assignment groups configuration (AD-408)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready


class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.

    Default-False per Wave 10 standing convention #14: this is a transitional
    feature that must be explicitly enabled by the operator. The registry
    issues sovereign DIDs under ``agent_type='visiting'`` and runs an async
    sweep loop, so silently enabling it would change the substrate's
    process-tree shape on first commit.
    """

    enabled: bool = False
    session_ttl_seconds: float = Field(default=3600.0, gt=0.0)
    sweep_interval_seconds: float = Field(default=60.0, gt=0.0)
    default_capabilities: list[str] = Field(
        default_factory=lambda: ["ward_room.post", "ward_room.read"]
    )


class WorkflowCronTriggerConfig(BaseModel):
    """AD-707: Workflow cron-trigger scheduler configuration.

    Default-False per Wave 10 convention #14. ``db_path`` empty means
    in-memory only (triggers lost on restart); supply a path to enable
    persistence. ``initial_triggers`` items must have keys
    ``user_input`` and ``cron_expr``.
    """

    enabled: bool = False
    db_path: str = ""
    tick_interval_seconds: float = Field(default=1.0, gt=0.0)
    initial_triggers: list[dict[str, str]] = Field(default_factory=list)


class QueryPlannerConfig(BaseModel):
    """Memvid pattern 1: relational query routing for the recall pipeline.

    Default-False per Wave 10 convention #14: opt-in until coverage proves
    out the regex classifier on real production traffic. When enabled, the
    runtime exposes a ``query_planner`` attribute that recall consumers can
    use via ``QueryPlanner.recall_with_fallback(episodic, query, k)``.
    """

    enabled: bool = False
    fall_through_on_empty: bool = True


class BridgeAlertConfig(BaseModel):
    """Bridge Alerts — proactive Captain & crew notifications (AD-410)."""
    enabled: bool = False
    cooldown_seconds: float = 300        # Dedup window per alert type+subject
    trust_drop_threshold: float = 0.15   # Trust drop triggering advisory
    trust_drop_alert_threshold: float = 0.25  # Trust drop triggering alert
    resolve_clean_period: float = 3600.0       # AD-580: seconds before resolved alert can re-fire
    default_dismiss_duration: float = 14400.0  # AD-580: default dismiss duration (4 hours)


class FirewallConfig(BaseModel):
    """AD-529: Communication Contagion Firewall configuration."""

    enabled: bool = True
    scan_trust_threshold: float = 0.65      # Scan posts from agents below this
    low_trust_threshold: float = 0.45       # Extra checks for very low trust
    hex_id_min_length: int = 6              # Min hex string length to flag
    hex_id_threshold: int = 2               # Flag if N+ ungrounded hex IDs
    fabricated_metrics_threshold: int = 3   # Flag if N+ precise claims with no source
    flag_window_seconds: float = 3600.0     # Window for counting flags
    quarantine_threshold: int = 3           # Flags in window before quarantine escalation


class EmergenceCollectorConfig(BaseModel):
    """AD-454: EvidenceCollector — research opt-in, default disabled."""

    enabled: bool = False
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    dedup_window_seconds: float = Field(default=600.0, ge=0.0)
    output_dir: str = "data/research/emergence-evidence"
    llm_tier: str = "fast"
    trial_id: str = "default"
    thread_context_limit: int = Field(default=5, ge=0, le=50)
    max_reasoning_chars: int = Field(default=2000, ge=100, le=20000)


class EmergentDetectorConfig(BaseModel):
    """BF-124: Emergent detector calibration parameters."""
    cluster_edge_threshold: float = 0.3
    cluster_min_size: int = 3
    cluster_min_avg_weight: float = 0.25
    cluster_cooldown_seconds: float = 1800.0
    cluster_activity_window: float = 900.0  # BF-165: seconds without Hebbian interaction before suppressing cluster detection (0 = disabled)
    dream_min_history: int = 5  # BF-166: minimum dream reports before anomaly detection fires
    # BF-175: Minimum absolute floors — prevent false positives when baseline averages are low
    dream_anomaly_min_strengthened: int = 10  # ignore strengthened spikes below this count
    dream_anomaly_min_pruned: int = 5  # ignore pruning spikes below this count
    dream_anomaly_min_trust_adj: int = 10  # ignore trust adjustment spikes below this count
    # AD-556: Per-agent adaptive trust anomaly detection
    adaptive_window_size: int = 30     # Number of trust snapshots per agent for rolling window
    adaptive_z_threshold: float = 2.5  # Z-score threshold for personal baseline anomaly
    adaptive_debounce_count: int = 2   # Consecutive anomalous cycles required before escalation
    adaptive_min_history: int = 8      # Minimum history entries before adaptive detection activates


class NoveltyGateConfig(BaseModel):
    """AD-493: Semantic novelty gate — suppress rehashed observations."""
    enabled: bool = True
    # Cosine similarity threshold — observations above this vs any recent
    # fingerprint are considered "not novel" and suppressed.
    # MiniLM cosine: 0.85+ = near-paraphrase, 0.70-0.85 = same topic/different angle,
    # 0.50-0.70 = related topic, <0.50 = different topic.
    similarity_threshold: float = 0.82
    # How many recent observation fingerprints to retain per agent.
    max_fingerprints_per_agent: int = 50
    # Decay: fingerprints older than this (hours) are evicted, making
    # the topic "novel again." 0 = no decay (fingerprints persist until
    # max_fingerprints_per_agent pushes them out).
    decay_hours: float = 24.0
    # Minimum text length to gate. Very short responses (acknowledgments,
    # social replies) skip the novelty check.
    min_text_length: int = 80


class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""
    enabled: bool = False
    # AD-674: Graduated initiative thresholds
    initiative_trust_thresholds: dict[str, float] = {
        "responsive": 0.3,    # Ensign threshold
        "contributory": 0.5,  # Lieutenant threshold
        "proactive": 0.7,     # Commander threshold
    }


class RiskTierConfig(BaseModel):
    """Action Risk Tier configuration (AD-676)."""

    enabled: bool = True
    elevated_min_trust: float = 0.0
    critical_min_trust: float = 0.70


class DutyDefinition(BaseModel):
    """A single recurring duty for a crew agent type."""
    duty_id: str                # e.g., "scout_report"
    description: str            # Human-readable task description
    cron: str = ""              # Cron expression (croniter format). Empty = interval-based.
    interval_seconds: float = 0 # Alternative to cron: simple interval. 0 = use cron.
    priority: int = 2           # 1-5, higher = more important when multiple due
    required_skills: list[str] = []  # AD-423c: skill_ids needed for this duty (informational)


class DutyScheduleConfig(BaseModel):
    """Duty schedule definitions per agent type (AD-419)."""
    enabled: bool = True
    schedules: dict[str, list[DutyDefinition]] = {}
    use_work_items: bool = False  # AD-500: opt-in for duty WorkItem producer; flips to True in AD-500a-1


class PolicyWindowConfig(BaseModel):
    """Time window policy definition used for proactive scheduling."""

    start_time: str = Field(default="08:00")
    end_time: str = Field(default="18:00")
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])


class DutyPolicyConfig(BaseModel):
    """Captain-configured work-hours/quiet-hours policy for proactive scans."""

    work_hours: PolicyWindowConfig = Field(default_factory=PolicyWindowConfig)
    quiet_hours: PolicyWindowConfig = Field(
        default_factory=lambda: PolicyWindowConfig(start_time="19:00", end_time="08:00", days=[])
    )
    scan_throttle_sec: dict[str, int] = Field(
        default_factory=lambda: {
            "inbox": 300,
            "calendar": 600,
            "teams": 900,
        }
    )
    daily_briefing_time: str = Field(default="08:00")
    briefing_reminder_throttle_sec: int = Field(default=3600)

    @field_validator("daily_briefing_time")
    @classmethod
    def _validate_daily_briefing_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("daily_briefing_time must be HH:MM")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("daily_briefing_time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"


class ProactiveCognitiveConfig(BaseModel):
    """Proactive Cognitive Loop — periodic idle-think (Phase 28b)."""
    enabled: bool = False
    interval_seconds: float = 120.0
    cooldown_seconds: float = 300.0
    # AD-414: Trust signal weights for proactive thinks
    trust_reward_weight: float = 0.1        # Trust signal for successful proactive think (posted to Ward Room)
    trust_no_response_weight: float = 0.0   # Trust signal for [NO_RESPONSE] (0 = no signal, silence is fine)
    trust_duty_bonus: float = 0.1           # Additional trust weight when completing a scheduled duty
    duty_schedule: DutyScheduleConfig = DutyScheduleConfig()
    # AD-636: Stagger proactive agent dispatch across cycle interval
    stagger_enabled: bool = True
    min_stagger_seconds: float = 5.0
    # AD-766: YeomanAgent proactive-scan digest aggregation window. Multiple
    # proactive_scan emissions arriving within this window are collapsed into
    # a single Captain DM digest. Set <= 0 to flush each scan immediately.
    yeoman_digest_window_seconds: float = 60.0


class ProactiveScanInboxConfig(BaseModel):
    """AD-763: per-operator scoping of the inbox proactive scan."""

    folders: list[str] = Field(
        default_factory=lambda: ["Inbox"],
        description="Graph mail folder IDs (or 'Inbox' alias) to include in scans.",
    )
    lookback_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 14,
        description="Window (hours) to query backward from now.",
    )
    importance_filter: Literal["any", "high"] = Field(
        default="any",
        description="'any' includes all importance levels; 'high' restricts to high-importance only.",
    )
    unread_only: bool = Field(
        default=False,
        description="If True, only unread messages are surfaced.",
    )
    sender_allowlist: list[str] = Field(
        default_factory=list,
        description="Email addresses or domains (e.g. '@acme.com'). Empty = no allow filter.",
    )
    sender_denylist: list[str] = Field(
        default_factory=list,
        description="Email addresses or domains. Senders matching are dropped post-fetch.",
    )


class ProactiveScanCalendarConfig(BaseModel):
    """AD-763: per-operator scoping of the calendar proactive scan."""

    calendar_ids: list[str] = Field(
        default_factory=lambda: ["primary"],
        description="Graph calendar IDs ('primary' alias resolves to default calendar).",
    )
    lookahead_hours: int = Field(
        default=24,
        ge=1,
        le=24 * 30,
        description="Window (hours) to query forward from now.",
    )
    include_declined: bool = Field(
        default=False,
        description="If True, events the operator has declined are still surfaced.",
    )


class ProactiveScanConfig(BaseModel):
    """AD-763: scoping config for proactive scans (folders, calendars, filters).

    v1 scope: operator-tunable scoping for inbox and calendar connectors.
    Per-scan-type intervals are deferred to AD-763d (forward marker).
    """

    inbox: ProactiveScanInboxConfig = Field(default_factory=ProactiveScanInboxConfig)
    calendar: ProactiveScanCalendarConfig = Field(default_factory=ProactiveScanCalendarConfig)


class PersistentTasksConfig(BaseModel):
    """Persistent Task Engine — SQLite-backed scheduled tasks (Phase 25a)."""
    enabled: bool = False
    tick_interval_seconds: float = 5.0
    max_concurrent_executions: int = 1   # Sequential by design
    dag_auto_resume: bool = False        # Future: auto-resume stale DAGs


class DiscordConfig(BaseModel):
    """Discord bot adapter configuration."""

    enabled: bool = False
    token: str = ""                          # Bot token (prefer env var PROBOS_DISCORD_TOKEN)
    allowed_channel_ids: list[int] = []      # Empty = respond in all channels
    allowed_user_ids: list[int] = []         # Empty = respond to all users (SECURITY RISK)
    command_prefix: str = "!"                # "!status" -> "/status"
    mention_required: bool = False           # Only respond when @mentioned
    scout_channel_id: int = 0                # Discord channel ID for scout reports (0 = disabled)


class SlackConfig(BaseModel):
    """Slack adapter configuration (AD-472 + AD-804).

    AD-472 v1 shipped webhook-only inbound via slack-sdk (opt-in extra).
    AD-804 (Wave 191) adds polling-mode inbound on a thin httpx client
    (no slack-sdk dep required), AD-802a pairing-gate integration, and
    a doctor health check. The polling-mode fields below are additive
    and back-compat with AD-472 webhook deployments.
    """

    enabled: bool = False
    bot_token: str = ""           # xoxb-... (prefer env var PROBOS_SLACK_BOT_TOKEN)
    signing_secret: str = ""      # for events-api verification
    allowed_channel_ids: list[str] = []
    allowed_user_ids: list[str] = []
    default_thread_ts: bool = True
    # AD-804: polling-mode inbound config (no slack-sdk dep required).
    channels: list[str] = []      # explicit channel-id list, empty = auto-discover via conversations.list
    poll_interval_s: float = 8.0  # seconds between conversations.history polls
    poll_inbound: bool = True     # opt-in to polling mode; AD-472 webhook receive() always available
    api_base: str = "https://slack.com/api"  # override only for testing


class WebhookConfig(BaseModel):
    """Webhook adapter configuration (AD-472)."""

    enabled: bool = False
    shared_secret: str = ""       # set via env var PROBOS_WEBHOOK_SECRET
    allowed_channels: list[str] = []


class ChannelsConfig(BaseModel):
    """Channel adapter configurations."""

    discord: DiscordConfig = DiscordConfig()
    slack: SlackConfig = SlackConfig()
    webhook: WebhookConfig = WebhookConfig()


class MedicalConfig(BaseModel):
    """Medical team pool configuration (AD-290)."""

    enabled: bool = True
    vitals_interval_seconds: float = 5.0
    vitals_window_size: int = 12
    pool_health_min: float = 0.5
    trust_floor: float = 0.3
    health_floor: float = 0.6
    max_trust_outliers: int = 3
    scheduled_diagnosis_interval: float = 300.0


class CounselorConfig(BaseModel):
    """Counselor cognitive wellness configuration (AD-503)."""

    enabled: bool = True
    profile_retention_days: int = 90
    trust_delta_threshold: float = 0.15
    sweep_max_agents: int = 50
    alert_on_red: bool = True
    alert_on_yellow: bool = False


class CaptainsLogConfig(BaseModel):
    """Captain's Log daily-narrative configuration (AD-477)."""

    enabled: bool = True
    output_dir: Path = Path("data/captains_log")
    end_of_day_hour: int = 23  # local hour to trigger generation
    top_episodes_count: int = 5
    importance_threshold: int = 5


class PlanOfDayConfig(BaseModel):
    """Plan of the Day morning-summary configuration (AD-477)."""

    enabled: bool = True
    output_dir: Path = Path("data/plan_of_day")
    start_of_day_hour: int = 8
    include_alert_conditions: bool = True


class NavalOrganizationConfig(BaseModel):
    """Naval Organization Protocols (AD-477) — v1 ships Captain's Log + Plan of the Day."""

    captains_log: CaptainsLogConfig = Field(default_factory=CaptainsLogConfig)
    plan_of_day: PlanOfDayConfig = Field(default_factory=PlanOfDayConfig)



class CircuitBreakerConfig(BaseModel):
    """Cognitive circuit breaker thresholds (AD-506a)."""

    velocity_threshold: int = 8
    velocity_window_seconds: float = 300.0
    similarity_threshold: float = 0.6
    similarity_min_events: int = 4
    base_cooldown_seconds: float = 900.0
    max_cooldown_seconds: float = 3600.0
    # Amber zone thresholds
    amber_similarity_ratio: float = 0.25  # Amber when similarity pair ratio exceeds this
    amber_velocity_ratio: float = 0.6     # Amber when velocity > this fraction of threshold
    amber_decay_seconds: float = 900.0    # 15 min quiet -> amber decays to green
    red_decay_seconds: float = 1800.0     # 30 min quiet -> red decays to amber
    critical_decay_seconds: float = 3600.0  # 1h quiet -> critical decays to red
    critical_trip_window_seconds: float = 3600.0  # Window for counting trips toward critical
    critical_trip_count: int = 3           # Trips in window to reach critical


class TraitAdaptiveConfig(BaseModel):
    """Trait-adaptive circuit breaker configuration (AD-494)."""

    enabled: bool = True


class ConcurrencyConfig(BaseModel):
    """AD-672: Per-agent concurrency management."""

    enabled: bool = True
    default_max_concurrent: int = 4
    queue_max_size: int = 10
    capacity_warning_ratio: float = 0.75
    role_overrides: dict[str, int] = Field(default_factory=lambda: {
        "bridge": 3,
        "operations": 6,
        "engineering": 5,
        "science": 4,
        "medical": 3,
        "security": 3,
    })


class TrustDampeningConfig(BaseModel):
    """Trust cascade dampening configuration (AD-558)."""

    # Progressive dampening
    dampening_window_seconds: float = 300.0
    dampening_geometric_factors: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25)
    dampening_floor: float = 0.25

    # Hard trust floor
    hard_trust_floor: float = 0.05

    # Network circuit breaker
    cascade_agent_threshold: int = 3
    cascade_department_threshold: int = 2
    cascade_delta_threshold: float = 0.15
    cascade_window_seconds: float = 300.0
    cascade_global_dampening: float = 0.5
    cascade_cooldown_seconds: float = 600.0

    # Cold-start scaling
    cold_start_observation_threshold: float = 20.0
    cold_start_dampening_floor: float = 0.5


class EmergenceMetricsConfig(BaseModel):
    """Configuration for emergence metrics computation (AD-557)."""

    # PID computation
    pid_bins: int = 2  # K=2 quantile binning (per Riedl 2025)
    pid_permutation_shuffles: int = 50  # Significance testing
    pid_significance_threshold: float = 0.05  # p-value threshold

    # Thread analysis
    min_thread_contributors: int = 2  # Minimum agents in thread to analyze
    min_thread_posts: int = 3  # Minimum posts in thread to analyze
    thread_lookback_hours: float = 24.0  # How far back to look for threads

    # Coordination balance
    groupthink_redundancy_threshold: float = 0.8  # Flag when redundancy dominates
    fragmentation_synergy_threshold: float = 0.1  # Flag when synergy is near zero

    # ToM effectiveness
    tom_baseline_window: int = 20  # Initial threads to establish baseline
    tom_trend_min_samples: int = 10  # Minimum threads before computing trend

    # Hebbian correlation
    hebbian_synergy_min_interactions: int = 5  # Minimum Hebbian interactions to correlate


class EmergentLeadershipConfig(BaseModel):
    """Emergent leadership detection configuration (AD-439)."""

    enabled: bool = True
    min_weight: float = 0.10
    min_ratio: float = 1.5


class BehavioralMetricsConfig(BaseModel):
    """AD-569: Observation-Grounded Crew Intelligence Metrics."""

    # Thread analysis
    thread_lookback_hours: float = 72.0  # How far back to analyze threads
    min_thread_contributors: int = 2  # Minimum unique authors for a qualifying thread
    min_thread_posts: int = 3  # Minimum posts for a qualifying thread

    # Frame Diversity (Metric 1)
    frame_diversity_min_departments: int = 2  # Need 2+ departments represented

    # Synthesis Detection (Metric 2)
    synthesis_novelty_threshold: float = 0.35  # Cosine distance threshold for "novel"
    synthesis_min_thread_posts: int = 4  # Threads need 4+ posts for synthesis analysis

    # Cross-Department Trigger (Metric 3)
    trigger_correlation_window_hours: float = 24.0  # Window for topic trigger correlation
    trigger_topic_similarity_threshold: float = 0.6  # Cosine similarity for "same topic"

    # Convergence Correctness (Metric 4)
    convergence_similarity_threshold: float = 0.75  # When posts are "converging"
    convergence_min_agreeing: int = 2  # Minimum agents agreeing for convergence

    # Anchor-Grounded Emergence (Metric 5)
    anchor_independence_min_episodes: int = 3  # Minimum episodes for anchor analysis

    # Snapshot history
    max_snapshots: int = 100  # Rolling window of historical snapshots


class EventLogConfig(BaseModel):
    """Event log retention configuration."""
    retention_days: int = 7          # Delete events older than N days (0 = keep forever)
    max_rows: int = 100_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0  # Check for pruning every N seconds


class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class KnowledgeEdgesConfig(BaseModel):
    """Knowledge Edge Store — typed-triple graph (AD-687).

    Default ``enabled=True`` is intentional and DEVIATES from the Wave-10
    transitional-flag convention. Rationale: this v1 ships an empty,
    write-only-when-called-by-consumers SQLite table. Consumers (Oracle
    Tier 6, Hebbian backfill, Dream Step 10) arrive in AD-688/689/690. With
    no consumers the store costs one CREATE TABLE IF NOT EXISTS at boot —
    invisible at runtime. Same precedent: ``CognitiveJournalConfig`` (also
    enabled=True for an infrastructure store).
    """
    enabled: bool = True
    db_path: str = "data/knowledge_edges.sqlite"
    max_traverse_hops: int = 3

    @field_validator("max_traverse_hops")
    @classmethod
    def _cap_hops(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError(
                "knowledge_edges.max_traverse_hops must be in [1, 3] "
                "(MAX_HOPS_CEILING; research §Phase 1)"
            )
        return v


class KnowledgeEdgeClassificationConfig(BaseModel):
    """AD-692: Classification enforcement on knowledge graph edges.

    OSS extension point. Default ``enabled=True`` follows the same precedent
    as ``KnowledgeEdgesConfig`` — the wrapper is a transparent pass-through
    when ``requester_agent_id`` is ``None`` (system/internal callers,
    backward-compatible with Wave 37/38/39/40). Filtering only applies once
    consumers (Oracle Tier 6 via AD-688 plumbing) supply a requester id.
    """
    enabled: bool = True
    default_classification: str = "private"

    @field_validator("default_classification")
    @classmethod
    def _validate_default(cls, v: str) -> str:
        allowed = {"private", "department", "ship", "fleet"}
        if v.lower() not in allowed:
            raise ValueError(
                f"knowledge_edge_classification.default_classification "
                f"must be one of {sorted(allowed)}, got {v!r}"
            )
        return v.lower()


class EdgeBackfillConfig(BaseModel):
    """AD-689: One-shot backfill of ``knowledge_edges`` from existing data.

    Default ``enabled=True`` follows the same precedent as
    ``KnowledgeEdgesConfig`` — the warm-boot wirer is a no-op once the table
    has any rows (idempotency-by-row-count guard). The first cold boot after
    AD-689 lands populates the graph from ontology/Hebbian/episodes/DECISIONS;
    subsequent boots see ``find_edges(limit=1) != []`` and skip.
    """
    enabled: bool = True
    run_on_warm_boot: bool = True
    hebbian_threshold: float = 0.5
    force: bool = False
    decisions_paths: list[str] = Field(
        default_factory=lambda: [
            "DECISIONS.md",
            "decisions-era-1-genesis.md",
            "decisions-era-2-emergence.md",
            "decisions-era-3-product.md",
            "decisions-era-4-evolution.md",
        ]
    )

    @field_validator("hebbian_threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("edge_backfill.hebbian_threshold must be in [0.0, 1.0]")
        return v


class ClinicalTelemetryConfig(BaseModel):
    """AD-635 / AD-635b / AD-635c: Clearance-gated clinical query facade (Medical / Counselor).

    AD-635 v1 shipped the read-only query facade with a bounded in-memory
    audit ring (``audit_max_entries`` deque). AD-635b adds optional
    SQLite persistence of the audit ring for post-incident review,
    gated by ``audit_persistence_enabled``. AD-635c adds optional
    SQLite persistence of cognitive-circuit-breaker state and zone
    transitions, gated by ``circuit_breaker_history_persistence_enabled``,
    plus a clearance-gated ``query_circuit_breaker_history`` method on
    ``ClinicalTelemetryService`` that reads from the durable store.

    Each persistence flag defaults False per Wave-10 convention #14
    (transitional flag, default off until validated). The service is
    invisible at runtime out-of-the-box (``enabled=False``). Captain
    opts in via YAML; each persistence side requires its own opt-in.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
    audit_persistence_enabled: bool = False
    audit_db_path: str = "data/clinical_audit.db"
    circuit_breaker_history_persistence_enabled: bool = False
    circuit_breaker_history_db_path: str = "data/circuit_breaker_history.db"


class ProcessChainRegistryConfig(BaseModel):
    """AD-647b v1: Registry of named process chains (`ProcessChainDefinition`).

    Default-True is intentional — registry construction cost is one empty
    dict + one ``register_chain(SCOUT_REPORT_CHAIN)`` call at boot, and
    Scout's ``act()`` depends on the registry being present (the
    module-level fallback is a defensive belt — disabling the registry
    would still log a WARNING per scout invocation).
    """
    enabled: bool = True


class ConsultationWorkspaceConfig(BaseModel):
    """AD-594a v1: Session-scoped consultation workspace registry.

    Default-True is intentional — the registry is read-only on boot (constructs
    an empty in-memory cache and ensures the ``consultations/`` subdir exists
    in Ship's Records). No automatic side effects until an agent calls
    ``runtime.consultation_workspaces.create(...)``. Same precedent as
    ``KnowledgeEdgesConfig`` / ``EdgeBackfillConfig``.
    """
    enabled: bool = True
    root_path: str = "consultations"
    input_processor: str = "passthrough"


class ConsultationDeliveryConfig(BaseModel):
    """AD-594d v1: Consultation delivery pipeline.

    Default-True is intentional — pipeline construction is read-only on boot
    (registers built-in adapters into an in-memory dict; no IO). Workspaces
    consume the pipeline only when an agent calls ``runtime.consultation_delivery
    .deliver(...)``. Same precedent as ``ConsultationWorkspaceConfig``.
    """
    enabled: bool = True
    # Adapter enablement — operators can disable individual adapters without
    # disabling the pipeline. Disabled adapters are not registered.
    local_file_enabled: bool = True
    github_enabled: bool = True
    # LocalFileAdapter: list of allowed destination root paths (absolute or
    # tilde-expandable). Empty = LocalFileAdapter registered with no roots
    # (rejects every delivery with "no allowed_roots configured").
    local_file_allowed_roots: list[str] = Field(default_factory=list)
    # GitHubAdapter: env var name from which the token is read at delivery time.
    github_token_env: str = "GITHUB_TOKEN"
    # Default approval requirement — used when a request does not specify
    # requires_approval explicitly via the dataclass default of False.
    default_requires_approval: bool = False


class ConsultationDispatchConfig(BaseModel):
    """AD-594c v1: Parallel execution dispatch.

    Default-True is intentional — dispatcher construction is read-only on boot
    (no IO; only resolves runtime.work_item_store + runtime.consultation_workspaces
    references). Side effects only fire when an agent calls
    ``runtime.consultation_dispatcher.dispatch(...)``. Same precedent as
    ``ConsultationWorkspaceConfig`` / ``ConsultationDeliveryConfig``.
    """
    enabled: bool = True
    # Default work_type used for WorkItems created by the dispatcher when a
    # plan spec does not specify one. "duty" is registered in the WorkTypeRegistry.
    default_work_type: str = "duty"
    # Tags applied to every dispatched WorkItem in addition to the workspace_id
    # tag — used by get_progress to scope list_work_items queries.
    default_tags: list[str] = Field(default_factory=lambda: ["consultation"])
    # Blocker escalation: emit PARALLEL_DISPATCH_BLOCKED when a spec's depends_on
    # set has been unmet for at least this many seconds since dispatch.
    blocker_threshold_seconds: float = 600.0
    # Progress event emission cadence (caller-driven; no internal timer in v1).
    # When True, get_progress() emits PARALLEL_DISPATCH_PROGRESS on each call.
    progress_subscription_enabled: bool = True
    # AD-858: pluggable plan decomposer. "markdown" preserves the v1
    # MarkdownPlanDecomposer behaviour; "llm" selects the semantic
    # LLMPlanDecomposer (single goal -> validated WorkItemSpec DAG).
    decomposer: Literal["markdown", "llm"] = "markdown"
    # AD-858: Safety Budget cap on how many sub-tasks the LLM decomposer may
    # emit for a single goal. Bounds unbounded fan-out.
    max_subtasks: int = 12
    # AD-858: LLM tier used by the semantic decomposer.
    decomposer_tier: str = "standard"


class HybridDispatchConfig(BaseModel):
    """AD-581 v1: Hybrid dispatch routing policy (581a + 581d).

    Default-True is intentional — DepartmentDispatcher construction is
    read-only on boot (no IO; only resolves runtime.hebbian_router +
    runtime.ontology references). The WorkItemRouter side-effect path
    activates only when a WORK_ITEM_CREATED event fires. Same precedent
    as ConsultationDispatchConfig / ConsultationDeliveryConfig.

    AD-581b order protocol additions are unconditional — declining or
    refusing an order is always available on OrderManager regardless of
    this config; the gate here governs the auto-routing layer only.
    """

    enabled: bool = True

    # AD-581d: Routing confidence thresholds.
    confidence_threshold: float = 0.4
    confidence_margin: float = 0.05
    min_hebbian_weight: float = 0.05

    # AD-581d: Per-(intent_type, agent_id) success-rate ring buffer.
    success_rate_window: int = 50
    min_samples_for_routing: int = 3

    # AD-581a: WorkItemRouter activation criteria.
    dispatchable_tags: list[str] = Field(default_factory=lambda: ["consultation"])

    @field_validator("confidence_threshold", "confidence_margin", "min_hebbian_weight")
    @classmethod
    def _weight_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("weight must be in [0.0, 1.0]")
        return v

    @field_validator("success_rate_window")
    @classmethod
    def _window_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("success_rate_window must be >= 1")
        return v

    @field_validator("min_samples_for_routing")
    @classmethod
    def _min_samples_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("min_samples_for_routing must be >= 1")
        return v


class WorkBoardReconcilerConfig(BaseModel):
    """AD-876: periodic + warm-boot work-board reconciliation (Quartermaster).

    Requires ``hybrid_dispatch`` enabled — the reconciler re-dispatches through
    ``runtime.work_item_router``, which only exists when hybrid dispatch is
    wired. Default ``enabled=False`` is load-bearing: unlike
    ``HybridDispatchConfig.enabled`` (a read-only boot path), this gate guards a
    side-effecting ticker that unassigns / re-dispatches work items, so it ships
    off and is flipped by operator config.
    """

    enabled: bool = False  # transitional flag — default False (conv #14)
    interval_seconds: int = Field(default=300, ge=30, le=3600)
    warm_boot: bool = True
    scan_limit: int = Field(default=200, ge=1, le=2000)
    # AD-877: thrash guard — bounded re-route attempts before dead-letter
    # quarantine (metadata flag), and a per-item backoff between sweeps.
    max_reconcile_attempts: int = Field(default=3, ge=1, le=20)
    reconcile_backoff_seconds: int = Field(default=600, ge=0, le=86400)
    # AD-878: boot-race grace period — skip items younger than this age so a
    # mid-first-dispatch item is not reclaimed by the warm-boot sweep.
    min_item_age_seconds: int = Field(default=30, ge=0, le=600)
    # AD-880: reactive reclaim — subscribe to AGENT_REMOVED and reclaim the dead
    # agent's items immediately (additive to the periodic sweep). Default off.
    reactive_reclaim: bool = False  # transitional flag — default False (conv #14)
    # AD-881: live-but-stalled reroute — an in_progress item whose live assignee
    # made no board progress within this window is rerouted. updated_at is
    # last-mutation (not a heartbeat), so this is a coarse signal — default off.
    stall_timeout_seconds: int = Field(default=0, ge=0, le=86400)  # 0 = disabled


class CommunicationsConfig(BaseModel):
    """Communications settings (AD-485)."""
    dm_min_rank: str = "ensign"  # Minimum rank to send DMs: ensign|lieutenant|commander|senior
    recreation_min_rank: str = "ensign"  # Minimum rank for game challenges: ensign|lieutenant|commander|senior
    group_chat_min_rank: str = "commander"  # AD-924: min rank to open an ad-hoc group chat: ensign|lieutenant|commander|senior
    # AD-927: agent-authored [ARTIFACT] -> task-room Output pane.
    artifact_min_rank: str = "lieutenant"  # min rank to write an artifact into a task room: ensign|lieutenant|commander|senior
    artifact_max_per_turn: int = 3         # anti-flood: honor at most this many [ARTIFACT] tags per proactive turn
    artifact_max_bytes: int = 262144       # anti-flood: reject artifact bodies larger than 256 KiB (oversized -> honest-degrade)
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


class WorkforceConfig(BaseModel):
    """Workforce Scheduling Engine configuration (AD-496)."""
    enabled: bool = False
    tick_interval_seconds: float = 10.0
    default_capacity: int = 1           # Default concurrent task limit per agent
    custom_work_types: list[dict] = []
    custom_templates: list[dict] = []
    template_config_path: str = "config/work_templates.yaml"


class TemporalConfig(BaseModel):
    """AD-502: Temporal awareness configuration."""
    enabled: bool = True
    include_birth_time: bool = True
    include_system_uptime: bool = True
    include_last_action: bool = True
    include_post_count: bool = True
    include_episode_timestamps: bool = True


class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"


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


class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True
    significance_threshold: float = 0.15
    test_timeout_seconds: float = 60.0

    # AD-595e: Qualification Gate Enforcement
    enforcement_enabled: bool = False
    enforcement_log_only: bool = True

    # AD-642: Communication Quality Benchmarks
    communication_benchmarks: CommunicationBenchmarksConfig = CommunicationBenchmarksConfig()

    # AD-566c: Drift Detection Pipeline
    drift_check_enabled: bool = True
    drift_check_interval_seconds: float = 604800.0  # 1 week
    drift_warning_sigma: float = 2.0    # Counselor alert threshold
    drift_critical_sigma: float = 3.0   # Bridge/Captain alert threshold
    drift_min_samples: int = 3          # Minimum data points before drift analysis
    drift_history_window: int = 20      # Max historical results for stats
    drift_cooldown_seconds: float = 3600.0  # Min time between alerts per agent+test
    drift_check_tiers: list[int] = [1, 2, 3]  # AD-566d/e: Which tiers the drift scheduler runs

    # AD-729b: peer-observation conduct training module path + gate.
    peer_observation_module_path: str = Field(
        default="config/manuals/peer_observation_conduct.yaml",
        description=(
            "AD-729b: training module YAML path. Loaded at Boot Camp graduation "
            "gate when peer_observation_certification_required is True."
        ),
    )
    peer_observation_certification_required: bool = Field(
        default=False,
        description=(
            "AD-729b: when True, Boot Camp / Qualification gates block "
            "advancement unless the peer-observation conduct module is "
            "passed. Default False — flips to True after AD-729a Standing "
            "Orders ship."
        ),
    )


class NatsConfig(BaseModel):
    """NATS event bus configuration (AD-637)."""

    enabled: bool = Field(
        default=False,
        validate_default=True,
        description="Enable NATS event bus. Overridden by PROBOS_NATS_ENABLED env var.",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def _env_override_enabled(cls, v: Any) -> Any:
        """BF-245: Allow env var to force-disable NATS in test workers."""
        env_val = os.environ.get("PROBOS_NATS_ENABLED")
        if env_val is not None:
            return env_val.lower() in ("true", "1", "yes")
        return v

    url: str = "nats://localhost:4222"
    connect_timeout_seconds: float = 5.0
    max_reconnect_attempts: int = 60
    reconnect_time_wait_seconds: float = 2.0
    drain_timeout_seconds: float = 5.0

    # JetStream
    jetstream_enabled: bool = True
    jetstream_domain: str | None = None  # For leaf node isolation

    # Subject prefix — derived from ship DID at runtime, fallback for local
    subject_prefix: str = "probos.local"

    # BF-230: JetStream publish timeout (seconds) — raised from nats-py default
    # to tolerate CPU load spikes. Applied per-publish, not connection-level.
    js_publish_timeout: float = 5.0


class AgentTierConfig(BaseModel):
    """Agent tier classification for trust separation (AD-571)."""

    crew_types: list[str] = Field(default_factory=lambda: [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ])
    core_types: list[str] = Field(default_factory=lambda: ["event_log", "vitals_monitor", "introspect"])


class OperationalStatusConfig(BaseModel):
    """Operational status tracker configuration (AD-571b)."""

    # Number of recent calls retained per agent for rolling metrics.
    sample_window_size: int = 50
    # Minimum success rate to be considered AVAILABLE. Below this → DEGRADED.
    available_success_rate: float = 0.85
    # p95 latency (ms) above which an otherwise-healthy agent is DEGRADED.
    degraded_p95_latency_ms: float = 5000.0
    # Consecutive error count that flips an agent to OFFLINE.
    offline_consecutive_errors: int = 5


class BridgeConfig(BaseModel):
    """Episodic-procedural bridge configuration (AD-572)."""

    enabled: bool = True
    min_cross_cycle_episodes: int = 5
    novelty_threshold: float = 0.3


class SelfDistillationConfig(BaseModel):
    """Configuration for AD-487 self-distillation v1 (Map step only)."""

    enabled: bool = True
    rate_limit_hours: int = 24
    llm_timeout_seconds: float = 30.0
    max_sub_topics: int = 5
    db_path: Path = Path("data/agent_probes.db")


class CreativeExpressionConfig(BaseModel):
    """Configuration for AD-525 v1 (Skills Inventory + Records Output)."""

    enabled: bool = True
    default_classification: Literal["ship", "department", "private"] = "ship"


class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate."""

    enabled: bool = True
    # v1: pattern set is hardcoded; register_pattern is runtime-only.


class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1: Agent Autonomy Boundaries (registry + observational detector)."""

    enabled: bool = True
    # v1: 5 federation-tier boundaries + 6 detection patterns are hardcoded.
    # register_pattern is runtime-only. Active blocking is AD-511b.


class CrewDevelopmentConfig(BaseModel):
    """AD-507 v1: Crew Development Framework (Core Knowledge Curriculum Registry)."""

    enabled: bool = True
    # v1: 9 default modules are hardcoded. register_module is runtime-only.
    # Progression tracking, competency assessment, and Standing Orders
    # integration are deferred to AD-507b/c/d.


class BootCampPhaseConfig(BaseModel):
    """AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

    Disambiguated from AD-638 ``BootCampConfig`` (cold-start boot camp); the
    AD-509 v1 tracker records 5-phase progression per agent.
    """

    enabled: bool = True
    # v1: tracker only. A-School curriculum, graduated stimuli,
    # completion-criteria gating, and trait-adaptive pacing are deferred
    # to AD-509b/c/d/e.


class DiscoveryLearningConfig(BaseModel):
    """AD-512 v1: Discovery-Based Capability Building substrate (observational).

    Default-True follows AD-507/509/511 v1 precedent — substrate is in-memory
    only, emits events, no resource creation, no I/O, no LLM calls. The
    eventual AD-486 Holodeck wave is the consumer that drives outcomes
    through this substrate; v1 ships the registry + per-agent maps + ZPD
    calibrator without that consumer.
    """

    enabled: bool = True
    # v1: 8 default scenarios + Beta(1,1) confidence priors + scaffolding
    # heuristic. Hebbian writes, episode storage, and Holodeck wiring are
    # caller responsibilities and are deferred to AD-486 / AD-510.
    confidence_prior_alpha: float = Field(default=1.0, ge=0.01)
    confidence_prior_beta: float = Field(default=1.0, ge=0.01)
    zpd_lower_bound: float = Field(default=0.40, ge=0.0, le=1.0)
    zpd_upper_bound: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_zpd_band(self) -> "DiscoveryLearningConfig":
        if self.zpd_lower_bound >= self.zpd_upper_bound:
            raise ValueError(
                "zpd_lower_bound must be strictly less than zpd_upper_bound"
            )
        return self


class ScopedCognitionConfig(BaseModel):
    """AD-508 v1: Duty Scope helper (read-only observational)."""

    enabled: bool = True


class WorkspaceOntologyConfig(BaseModel):
    """AD-478 v1: Workspace Ontology read-only register (frequency-bounded)."""

    enabled: bool = True
    max_terms: int = 1000


class GapPipelineExtensionsConfig(BaseModel):
    """AD-539c + AD-539d v1 config (observational gap pipeline extensions)."""

    remediation_tracker_enabled: bool = True
    fleet_aggregator_enabled: bool = True
    remediation_max_history: int = 100
    # AD-539c-i: opt-in active remediation. Default-False keeps observational
    # mode the default; flip to True to actually trigger qualifications,
    # request data routing, and escalate capability gaps.
    active_remediation_enabled: bool = False


class SPCConfig(BaseModel):
    """AD-522 v1: Statistical Process Control (calibration profile + WE rules)."""

    enabled: bool = True
    sample_window: int = 100


class ExtensionsConfig(BaseModel):
    """AD-481: Extension subsystem master config.

    Mirrors src/probos/extensions/protocol.py:ExtensionsConfig — duplicated here
    to avoid circular import (config.py is imported very early; the extensions/
    package imports config indirectly via runtime).
    """

    enabled: bool = False
    enforce_sealed_core: bool = False
    default_profile: str = "minimal"
    extensions_dir: str = "src/probos/extensions"


class DmSanityGateConfig(BaseModel):  # AD-724
    """Configuration for the DM one-shot sanity gate.

    Default-ON: this config gates three previously-unconditional regex
    cleanups (BF-120, BF-119, AD-572) plus three new log-only checks.
    Disabling it preserves only the BF-120 markdown strip.

    Must stay structurally identical to the ``DmSanityGateConfig`` copy in
    ``cognitive/dm_sanity_gate.py`` (cluster invariant from the AD-724
    archive prompt — do not split DmSanityGate / DmSanityGateConfig /
    DmSanityResult across multiple files).
    """

    enabled: bool = True
    length_floor: int = 5
    repetition_prefix_chars: int = 100

    # AD-724-2: similarity-based repetition.
    repetition_similarity_threshold: float = 0.85

    # AD-724-1: controlled one-shot retry on rejection.
    retry_on_rejection: bool = True
    retry_warnings: list[str] = Field(
        default_factory=lambda: ["length_floor", "orphaned_tag"]
    )


class DmTargetedLookupConfig(BaseModel):  # AD-725 (Wave 159)
    """AD-725: pre-LLM targeted sub-intent dispatch on the DM one-shot path.

    Default OFF — opt-in because the lookup adds latency (max(classifier,
    lookup) ~ 100-300ms) and the v1 regex classifier is intentionally
    conservative. Per-store enables let the operator narrow the surface
    further.
    """

    enabled: bool = False
    classifier_tier: str = "regex"             # v1 ladder; "embedding" reserved for AD-725-2
    timeout_ms: int = 500                      # hard cap; lookup ABORTS on timeout
    enable_oracle: bool = True
    enable_episodic: bool = True
    enable_codebase: bool = False              # default OFF — codebase queries can be slow
    enable_knowledge: bool = True
    identity_enabled: bool = True              # AD-735: cheap in-memory self-identity lookup
    max_lookup_chars: int = 1500               # truncate lookup result before injection

    @field_validator("classifier_tier")
    @classmethod
    def _bound_classifier_tier(cls, v: str) -> str:
        allowed = {"regex", "embedding"}
        if v not in allowed:
            raise ValueError(
                f"classifier_tier must be one of {sorted(allowed)}, got {v!r}"
            )
        return v

    @field_validator("timeout_ms", "max_lookup_chars")
    @classmethod
    def _bound_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"must be >= 1, got {v}")
        return v


class DmDeliberateConfig(BaseModel):  # AD-934
    """AD-934 (Option C): flag-gated [THINK]/[DELIBERATE] deep-tier re-roll.
    Default OFF — opt-in because the re-roll adds a full deep-tier LLM pass
    (latency + cost) per marker-bearing reply."""
    enabled: bool = False
    tier: str = "deep"
    max_tokens: int = 800


class WakeWordConfig(BaseModel):
    """AD-705c (Wave 179) — custom wake-word training pipeline config.

    All fields default-OFF / privacy-preserving per convention #14.
    Operator opts in via system.yaml. The training audio NEVER leaves
    the local runtime; the trainer runs entirely in-process.
    """

    wake_word_trainer_enabled: bool = False
    custom_model_filename: str = "captain.onnx"
    retain_training_samples: bool = False
    training_samples_max_count: int = 200
    training_audio_max_bytes: int = 1_048_576


class M365Config(BaseModel):
    """AD-749: Microsoft 365 integration configuration.
    
    OSS (personal): single-user OAuth device-code flow with local token caching.
    Commercial: multi-tenant SSO + enterprise policy extensions (not in OSS).
    """

    enabled: bool = False
    client_id: str | None = None
    authority: str = "https://login.microsoftonline.com/common"
    scopes: list[str] = Field(
        default_factory=lambda: ["https://graph.microsoft.com/.default"]
    )
    cache_dir: str = "~/.probos/m365_cache"

    @field_validator("cache_dir")
    @classmethod
    def _expand_cache_dir(cls, v: str) -> str:
        return os.path.expanduser(v)


class OfficeSkillsConfig(BaseModel):
    """AD-755: Local office-document skills and template registry config."""

    enabled: bool = False
    template_dir: str = "~/.probos/templates"
    output_dir: str = "~/.probos/output"

    @field_validator("template_dir")
    @classmethod
    def _expand_template_dir(cls, v: str) -> str:
        return os.path.expanduser(v)

    @field_validator("output_dir")
    @classmethod
    def _expand_output_dir(cls, v: str) -> str:
        return os.path.expanduser(v)


class DesktopConfig(BaseModel):
    """AD-751: Desktop UX Surface — tray, hotkey, notifications, autostart."""

    enabled: bool = Field(
        default=False,
        description="AD-751: master switch for desktop surface. Default OFF (Wave 10 convention #14).",
    )
    tray_autostart: bool = Field(
        default=True,
        description="Auto-start tray icon on boot when desktop enabled.",
    )
    hotkey: str = Field(
        default="ctrl+shift+space",
        description="Global hotkey to activate mini-mode (pynput syntax).",
    )
    notification_timeout_sec: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Toast notification display duration (seconds).",
    )
    quiet_hours_start: str = Field(
        default="19:00",
        description="Start of quiet hours (HH:MM format, local time).",
    )
    quiet_hours_end: str = Field(
        default="08:00",
        description="End of quiet hours (HH:MM format, local time).",
    )
    lock_file: str = Field(
        default="~/.probos/yeo.lock",
        description="Single-instance lock file path.",
    )
    autostart_enabled: bool = Field(
        default=False,
        description="Register for OS autostart on boot.",
    )

    @property
    def quiet_hours_start_tuple(self) -> tuple[int, int]:
        """Parse quiet_hours_start into (hour, minute) tuple."""
        parts = self.quiet_hours_start.split(":")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    @property
    def quiet_hours_end_tuple(self) -> tuple[int, int]:
        """Parse quiet_hours_end into (hour, minute) tuple."""
        parts = self.quiet_hours_end.split(":")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


class DependencyConfig(BaseModel):
    """AD-838c: Dynamic dependency installation for the task path.

    Distinct from SelfModConfig — this governs whether runtime task execution
    may install missing third-party packages (Copilot-style ask-before-install),
    independent of the self-modification pipeline. ``config.self_mod.allowed_imports``
    is reused as the auto-approve tier.
    """

    dynamic_install_enabled: bool = False
    dynamic_install_policy: Literal["whitelist", "prompt_unlisted"] = "prompt_unlisted"
    dynamic_install_deny: list[str] = Field(default_factory=list)


class CapabilityTriageConfig(BaseModel):
    """AD-854: Acquire-vs-build triage grant fast-path gating.

    Conservative defaults — the zero-prompt grant fast path is OFF and the trust
    floor is high, so a grant is auto-approved only after the operator opts in.
    ``install`` and ``build`` never use the fast path (Captain / self-mod gate).
    """

    grant_fast_path_enabled: bool = False
    grant_trust_floor: float = 0.8

    @field_validator("grant_trust_floor")
    @classmethod
    def _trust_floor_in_unit(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("grant_trust_floor must be in [0.0, 1.0]")
        return v


class AgenticDispatchConfig(BaseModel):
    """AD-856: Gate the AgenticLoop execution path for dispatched work items.

    Conservative default per convention #14 — the multi-turn loop is OFF, so
    dispatched work items keep using the existing single-shot ``handle_intent``
    path until the operator opts in.
    """

    enabled: bool = False

    # AD-859: bound the crew fan-out so a wide parent (many child subtasks)
    # cannot exhaust the LLM tier. Conservative default per Safety Budget —
    # keeps concurrent subtask runs small until the operator widens it.
    max_parallel_subtasks: int = 3

    # AD-860: cap the adversarial verify -> re-run -> re-verify convergence
    # loop. Conservative default per Safety Budget — at most two correction
    # rounds before a still-refuted subtask is escalated as "unverified"
    # rather than looped indefinitely.
    max_convergence_rounds: int = 2

    # AD-867: gate the full crew pipeline (resolve -> delegate -> fan-out ->
    # verify -> synthesize) behind one runtime entry point. Conservative default
    # per convention #14 — the orchestrator trigger stays OFF so a multi-spec
    # dispatch keeps the existing single-agent path until the operator opts in.
    orchestrator_enabled: bool = False


class SystemConfig(BaseModel):
    """Root configuration model."""

    system: SystemInfo = SystemInfo()
    pools: PoolConfig = PoolConfig()
    mesh: MeshConfig = MeshConfig()
    consensus: ConsensusConfig = ConsensusConfig()
    cognitive: CognitiveConfig = CognitiveConfig()
    health_probe_interval_seconds: float = 30.0  # BF-246: Periodic LLM connectivity probe
    memory: MemoryConfig = MemoryConfig()
    dreaming: DreamingConfig = DreamingConfig()
    dream_wm: DreamWMConfig = DreamWMConfig()  # AD-671
    scaling: ScalingConfig = ScalingConfig()
    federation: FederationConfig = FederationConfig()
    self_mod: SelfModConfig = SelfModConfig()
    dependency: DependencyConfig = Field(default_factory=DependencyConfig)  # AD-838c
    qa: QAConfig = QAConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    records: RecordsConfig = RecordsConfig()
    archive: ArchiveConfig = ArchiveConfig()
    telemetry: TelemetryConfig = TelemetryConfig()  # AD-461
    post_budget_telemetry: PostBudgetTelemetryConfig = PostBudgetTelemetryConfig()  # BF-238
    confidence: ConfidenceConfig = ConfidenceConfig()  # AD-444
    lint: LintConfig = LintConfig()  # AD-563
    quality_trigger: QualityTriggerConfig = QualityTriggerConfig()  # AD-564
    quality_router: QualityRouterConfig = QualityRouterConfig()  # AD-565
    onboarding: OnboardingConfig = OnboardingConfig()
    holodeck_birth_chamber: HolodeckBirthChamberConfig = HolodeckBirthChamberConfig()
    holodeck_scenarios: HolodeckScenarioConfig = HolodeckScenarioConfig()
    team_simulations: HolodeckTeamSimulationConfig = HolodeckTeamSimulationConfig()
    naming: NamingConfig = NamingConfig()  # AD-499
    runtime_overrides: RuntimeOverridesConfig = RuntimeOverridesConfig()  # AD-468
    utility_agents: UtilityAgentsConfig = UtilityAgentsConfig()
    swe_specialists: SoftwareEngineerSpecialistsConfig = Field(
        default_factory=SoftwareEngineerSpecialistsConfig
    )
    native_swe_harness: NativeSWEHarnessConfig = Field(
        default_factory=NativeSWEHarnessConfig,
        description="AD-549: Native SWE agentic harness configuration.",
    )
    ward_room: WardRoomConfig = WardRoomConfig()
    group_chat: GroupChatConfig = GroupChatConfig()  # AD-915
    visiting_officers: VisitingOfficersConfig = VisitingOfficersConfig()  # AD-701
    workflow_cron: WorkflowCronTriggerConfig = WorkflowCronTriggerConfig()  # AD-707
    query_planner: QueryPlannerConfig = QueryPlannerConfig()  # Memvid pattern 1
    assignments: AssignmentConfig = AssignmentConfig()
    bridge_alerts: BridgeAlertConfig = BridgeAlertConfig()
    firewall: FirewallConfig = FirewallConfig()
    security: SecurityConfig = SecurityConfig()  # AD-455
    auth: AuthConfig = Field(default_factory=AuthConfig)  # AD-722b-1 (Wave 161)
    emergent_detector: EmergentDetectorConfig = EmergentDetectorConfig()
    emergence_collector: "EmergenceCollectorConfig" = Field(
        default_factory=lambda: EmergenceCollectorConfig()
    )  # AD-454
    novelty_gate: NoveltyGateConfig = NoveltyGateConfig()
    earned_agency: EarnedAgencyConfig = EarnedAgencyConfig()
    duty_schedule: DutyPolicyConfig = Field(default_factory=DutyPolicyConfig)
    proactive_cognitive: ProactiveCognitiveConfig = ProactiveCognitiveConfig()
    proactive_scan: ProactiveScanConfig = Field(default_factory=ProactiveScanConfig)  # AD-763
    persistent_tasks: PersistentTasksConfig = PersistentTasksConfig()
    channels: ChannelsConfig = ChannelsConfig()
    m365: M365Config = Field(default_factory=M365Config)  # AD-749
    office_skills: OfficeSkillsConfig = Field(default_factory=OfficeSkillsConfig)  # AD-755
    medical: MedicalConfig = MedicalConfig()
    counselor: CounselorConfig = CounselorConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    trait_adaptive: TraitAdaptiveConfig = TraitAdaptiveConfig()  # AD-494
    concurrency: ConcurrencyConfig = ConcurrencyConfig()  # AD-672
    trust_dampening: TrustDampeningConfig = TrustDampeningConfig()
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
    emergent_leadership: EmergentLeadershipConfig = EmergentLeadershipConfig()  # AD-439
    orders: OrdersConfig = OrdersConfig()  # AD-440
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
    engineering: EngineeringConfig = EngineeringConfig()  # AD-457
    degradation: DegradationConfig = DegradationConfig()  # AD-459
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
    infrastructure: InfrastructureConfig = InfrastructureConfig()  # AD-466
    security_infra: SecurityInfraConfig = SecurityInfraConfig()  # AD-456
    ground_truth: GroundTruthConfig = GroundTruthConfig()  # AD-528
    operations: OperationsConfig = OperationsConfig()  # AD-467
    model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
    ready_room: ReadyRoomConfig = ReadyRoomConfig()  # AD-475
    dept_profiles: DepartmentProfilesConfig = DepartmentProfilesConfig()  # AD-656
    eps: EPSConfig = EPSConfig()  # AD-469
    mcp: MCPConfig = MCPConfig()  # AD-449
    mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)  # AD-597
    browser_tool: BrowserToolConfig = Field(default_factory=BrowserToolConfig)  # AD-706
    avatars: AvatarsConfig = Field(default_factory=AvatarsConfig)  # AD-721
    avatar_telemetry: AvatarTelemetryConfig = Field(default_factory=AvatarTelemetryConfig)  # AD-722
    dm_sanity_gate: DmSanityGateConfig = Field(default_factory=DmSanityGateConfig)  # AD-724
    dm_targeted_lookup: DmTargetedLookupConfig = Field(default_factory=DmTargetedLookupConfig)  # AD-725 (Wave 159)
    dm_deliberate: DmDeliberateConfig = Field(default_factory=DmDeliberateConfig)  # AD-934
    attachments: AttachmentsConfig = Field(default_factory=AttachmentsConfig)  # AD-720
    cloud_pickers: CloudPickersConfig = Field(default_factory=CloudPickersConfig)  # AD-720c
    lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)  # AD-721b-1 (Wave 155)
    tts: TTSConfig = Field(default_factory=TTSConfig)  # AD-738 (Wave 157)    spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520
    knowledge_browser: KnowledgeBrowserConfig = Field(default_factory=KnowledgeBrowserConfig)  # AD-562
    extensions: ExtensionsConfig = Field(default_factory=ExtensionsConfig)  # AD-481
    observability_bridge: ObservabilityBridgeConfig = Field(default_factory=ObservabilityBridgeConfig)  # AD-641a
    threshold_alerts: ThresholdAlertConfig = Field(default_factory=ThresholdAlertConfig)  # AD-695
    ward_room_hebbian: WardRoomHebbianConfig = Field(default_factory=WardRoomHebbianConfig)  # AD-641b
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)  # AD-733 (Wave 170)
    wake_word: WakeWordConfig = Field(default_factory=WakeWordConfig)  # AD-705c (Wave 179)
    engineering_sensors: EngineeringSensorsConfig = Field(default_factory=EngineeringSensorsConfig)  # AD-641f
    learned_shortcuts: LearnedShortcutsConfig = Field(default_factory=LearnedShortcutsConfig)  # AD-641e
    thread_priority: ThreadPriorityConfig = Field(default_factory=ThreadPriorityConfig)  # AD-641c
    deliberation: DeliberationConfig = Field(default_factory=DeliberationConfig)  # AD-641d
    behavioral_metrics: BehavioralMetricsConfig = BehavioralMetricsConfig()
    event_log: EventLogConfig = EventLogConfig()
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
    knowledge_edge_classification: KnowledgeEdgeClassificationConfig = Field(
        default_factory=KnowledgeEdgeClassificationConfig
    )  # AD-692
    edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
    communications: CommunicationsConfig = CommunicationsConfig()
    workforce: WorkforceConfig = WorkforceConfig()
    temporal: TemporalConfig = TemporalConfig()
    qualification: QualificationConfig = QualificationConfig()
    orientation: OrientationConfig = OrientationConfig()
    social_verification: SocialVerificationConfig = SocialVerificationConfig()
    anomaly_window: AnomalyWindowConfig = AnomalyWindowConfig()  # AD-673
    working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
    predictive_branching: PredictiveBranchingConfig = PredictiveBranchingConfig()  # AD-633
    self_improvement: SelfImprovementConfig = SelfImprovementConfig()  # AD-482
    memory_budget: MemoryBudgetConfig = MemoryBudgetConfig()  # AD-573
    metabolism: MetabolismConfig = MetabolismConfig()  # AD-670
    pinned_knowledge: PinnedKnowledgeConfig = PinnedKnowledgeConfig()  # AD-579a
    temporal_validity: TemporalValidityConfig = TemporalValidityConfig()  # AD-579b
    task_context: TaskContextConfig = TaskContextConfig()  # AD-586
    question_adaptive: QuestionAdaptiveConfig = QuestionAdaptiveConfig()  # AD-602
    storage_gate: StorageGateConfig = StorageGateConfig()  # AD-610
    salience: SalienceConfig = SalienceConfig()  # AD-668
    sensorium: SensoriumConfig = SensoriumConfig()  # AD-666
    source_tracing: SourceTracingConfig = SourceTracingConfig()
    observable_state: ObservableStateConfig = ObservableStateConfig()
    llm_rate: LLMRateConfig = LLMRateConfig()  # AD-617
    sub_task: SubTaskConfig = SubTaskConfig()  # AD-632a
    boot_camp: BootCampConfig = BootCampConfig()  # AD-638
    ship_state_snapshot: ShipStateSnapshotConfig = Field(
        default_factory=ShipStateSnapshotConfig
    )  # AD-683
    tiered_trust: TieredTrustConfig = TieredTrustConfig()  # AD-640
    chain_tuning: ChainTuningConfig = ChainTuningConfig()  # AD-639
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
    chain_optimizer_counselor: ChainOptimizerCounselorConfig = ChainOptimizerCounselorConfig()  # AD-659c
    causal_reasoning: CausalReasoningConfig = CausalReasoningConfig()  # AD-660
    diagnostic_context: DiagnosticContextConfig = Field(
        default_factory=DiagnosticContextConfig
    )  # AD-661
    nl_graph_query: NLGraphQueryConfig = Field(
        default_factory=NLGraphQueryConfig
    )  # AD-691
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    consultation_delivery: ConsultationDeliveryConfig = Field(
        default_factory=ConsultationDeliveryConfig
    )  # AD-594d
    consultation_dispatch: ConsultationDispatchConfig = Field(
        default_factory=ConsultationDispatchConfig
    )  # AD-594c
    capability_triage: CapabilityTriageConfig = Field(
        default_factory=CapabilityTriageConfig
    )  # AD-854
    agentic_dispatch: AgenticDispatchConfig = Field(
        default_factory=AgenticDispatchConfig
    )  # AD-856
    hybrid_dispatch: HybridDispatchConfig = Field(
        default_factory=HybridDispatchConfig
    )  # AD-581 v1 (sub-ADs 581a/b/d)
    work_board_reconciler: WorkBoardReconcilerConfig = Field(
        default_factory=WorkBoardReconcilerConfig
    )  # AD-876
    process_chain_registry: ProcessChainRegistryConfig = Field(
        default_factory=ProcessChainRegistryConfig
    )  # AD-647b
    knowledge_loading: KnowledgeLoadingConfig = KnowledgeLoadingConfig()  # AD-585
    step_instruction: StepInstructionConfig = StepInstructionConfig()  # AD-651
    agent_tiers: AgentTierConfig = AgentTierConfig()  # AD-571
    operational_status: OperationalStatusConfig = OperationalStatusConfig()  # AD-571b
    risk_tiers: RiskTierConfig = RiskTierConfig()  # AD-676
    procedural_bridge: BridgeConfig = BridgeConfig()  # AD-572
    nats: NatsConfig = NatsConfig()  # AD-637
    bill: BillConfig = BillConfig()  # AD-618b
    consultation: ConsultationConfig = ConsultationConfig()  # AD-594
    expertise: ExpertiseConfig = ExpertiseConfig()  # AD-600
    creative_expression: CreativeExpressionConfig = Field(default_factory=CreativeExpressionConfig)  # AD-525
    classification_gate: ClassificationGateConfig = Field(default_factory=ClassificationGateConfig)  # AD-530
    autonomy_boundaries: AutonomyBoundariesConfig = Field(default_factory=AutonomyBoundariesConfig)  # AD-511
    crew_development: CrewDevelopmentConfig = Field(default_factory=CrewDevelopmentConfig)  # AD-507
    boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)  # AD-509
    discovery_learning: DiscoveryLearningConfig = Field(default_factory=DiscoveryLearningConfig)  # AD-512
    scoped_cognition: ScopedCognitionConfig = Field(default_factory=ScopedCognitionConfig)  # AD-508
    workspace_ontology: WorkspaceOntologyConfig = Field(default_factory=WorkspaceOntologyConfig)  # AD-478
    gap_pipeline_extensions: GapPipelineExtensionsConfig = Field(default_factory=GapPipelineExtensionsConfig)  # AD-539c/d
    spreading_activation: SpreadingActivationConfig = SpreadingActivationConfig()  # AD-604
    thought_store: ThoughtStoreConfig = ThoughtStoreConfig()  # AD-606
    retroactive: RetroactiveConfig = RetroactiveConfig()  # AD-608
    distillation: DistillationConfig = DistillationConfig()  # AD-609
    reconsolidation: ReconsolidationConfig = ReconsolidationConfig()  # AD-574
    naval_organization: NavalOrganizationConfig = Field(default_factory=NavalOrganizationConfig)  # AD-477
    self_distillation: SelfDistillationConfig = SelfDistillationConfig()  # AD-487
    spc: SPCConfig = Field(default_factory=SPCConfig)  # AD-522 v1
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)  # AD-751

    @field_validator("health_probe_interval_seconds")
    @classmethod
    def _validate_probe_interval(cls, v: float) -> float:
        if v < 5.0:
            raise ValueError(
                "health_probe_interval_seconds must be >= 5.0 to avoid hammering a recovering proxy"
            )
        return v


def load_config(path: str | Path) -> SystemConfig:
    """Load and validate system config from a YAML file."""
    path = Path(path)
    if not path.exists():
        return SystemConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    # YAML sections with all values commented out parse as key: None.
    # Remove these so pydantic uses defaults instead of failing validation.
    raw = {k: v for k, v in raw.items() if v is not None}
    return SystemConfig.model_validate(raw)
