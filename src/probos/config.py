"""Configuration loader for ProbOS."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


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
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0


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

    llm_base_url: str = "http://127.0.0.1:8080/v1"  # OpenAI-compatible endpoint
    llm_api_key: str = ""
    llm_model_fast: str = "gpt-4o-mini"
    llm_model_standard: str = "claude-sonnet-4"
    llm_model_deep: str = "claude-sonnet-4"
    llm_timeout_seconds: float = 30.0
    working_memory_token_budget: int = 4000
    decomposition_timeout_seconds: float = 30.0
    dag_execution_timeout_seconds: float = 60.0
    use_consensus_for_writes: bool = True
    max_concurrent_tasks: int = 8
    attention_decay_rate: float = 0.95  # Per-second decay for stale tasks
    focus_history_size: int = 10
    background_demotion_factor: float = 0.25


class MemoryConfig(BaseModel):
    """Episodic memory configuration."""

    collection_name: str = "probos_episodes"
    max_episodes: int = 100000
    relevance_threshold: float = 0.7


class DreamingConfig(BaseModel):
    """Dreaming / offline consolidation configuration."""

    idle_threshold_seconds: float = 300.0
    dream_interval_seconds: float = 600.0
    replay_episode_count: int = 50
    pathway_strengthening_factor: float = 0.03
    pathway_weakening_factor: float = 0.02
    prune_threshold: float = 0.01
    trust_boost: float = 0.1
    trust_penalty: float = 0.1
    pre_warm_top_k: int = 5


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


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus


class SelfModConfig(BaseModel):
    """Self-modification configuration."""

    enabled: bool = False  # Disabled by default — opt-in capability
    require_user_approval: bool = True  # Human must confirm before agent goes live
    probationary_alpha: float = 1.0  # Beta prior alpha for self-created agents
    probationary_beta: float = 3.0  # Beta prior beta → E[trust] = 0.25
    max_designed_agents: int = 5  # Maximum self-created agent types in system
    sandbox_timeout_seconds: float = 10.0  # Timeout for sandbox test execution
    allowed_imports: list[str] = [
        "asyncio", "pathlib", "json", "os", "re", "datetime",
        "typing", "dataclasses", "collections", "math", "hashlib",
        "urllib.parse", "base64", "csv", "io", "tempfile",
    ]
    forbidden_patterns: list[str] = [
        r"subprocess", r"shutil\.rmtree", r"os\.remove", r"os\.unlink",
        r"eval\s*\(", r"exec\s*\(", r"__import__",
        r"open\s*\(.*['\"]w['\"]", r"socket\b", r"ctypes\b",
    ]


class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"


class SystemConfig(BaseModel):
    """Root configuration model."""

    system: SystemInfo = SystemInfo()
    pools: PoolConfig = PoolConfig()
    mesh: MeshConfig = MeshConfig()
    consensus: ConsensusConfig = ConsensusConfig()
    cognitive: CognitiveConfig = CognitiveConfig()
    memory: MemoryConfig = MemoryConfig()
    dreaming: DreamingConfig = DreamingConfig()
    scaling: ScalingConfig = ScalingConfig()
    federation: FederationConfig = FederationConfig()
    self_mod: SelfModConfig = SelfModConfig()


def load_config(path: str | Path) -> SystemConfig:
    """Load and validate system config from a YAML file."""
    path = Path(path)
    if not path.exists():
        return SystemConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return SystemConfig.model_validate(raw)
