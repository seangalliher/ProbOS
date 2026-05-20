"""Tests for M365 runtime wiring."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from probos.config import SystemConfig, M365Config
from probos.runtime import ProbOSRuntime


@pytest.fixture
def config_m365_disabled():
    """Config with M365 disabled."""
    config = MagicMock(spec=SystemConfig)
    config.m365 = M365Config(enabled=False)
    config.system = MagicMock()
    config.system.version = "0.4.0"
    config.pools = MagicMock()
    config.mesh = MagicMock()
    config.consensus = MagicMock()
    config.cognitive = MagicMock()
    config.cognitive.llm_base_url = "http://localhost:8080/v1"
    config.cognitive.llm_api_key = ""
    config.cognitive.working_memory_token_budget = 4000
    config.cognitive.decomposition_timeout_seconds = 30.0
    config.memory = MagicMock()
    config.dreaming = MagicMock()
    config.knowledge = MagicMock()
    config.records = MagicMock()
    config.telemetry = MagicMock()
    config.federation = MagicMock()
    config.federation.enabled = False
    config.self_mod = MagicMock()
    config.qa = MagicMock()
    config.operational_status = MagicMock()
    config.trust_dampening = MagicMock()
    config.avatar_telemetry = MagicMock()
    config.avatar_telemetry.enabled = False
    config.attachments = MagicMock()
    config.attachments.image_budget_path = None
    config.avatars = MagicMock()
    config.avatars.enabled = False
    config.avatars.avatar_telemetry = MagicMock()
    config.avatars.avatar_telemetry.enabled = False
    config.browsers_tools = MagicMock()
    config.browsers_tools.enabled = False
    config.swe_specialists = MagicMock()
    config.swe_specialists.enabled = False
    config.mcp_app_host = MagicMock()
    config.mcp_app_host.enabled = False
    config.dm_sanity_gate = MagicMock()
    config.dm_targeted_lookup = MagicMock()
    config.perception = MagicMock()
    config.online_stt_enabled = False
    config.wake_word = MagicMock()
    config.wake_word.wake_word_trainer_enabled = False
    config.credential_vault = MagicMock()
    config.spatial_explorer = MagicMock()
    config.knowledge_browser = MagicMock()
    config.extensions = MagicMock()
    config.md_pla_browser_network_requests = MagicMock()
    config.temporal = MagicMock()
    config.dream_wm = MagicMock()
    config.scaling = MagicMock()
    config.backend_call = MagicMock()
    config.pre_flight = MagicMock()
    config.post_budget_telemetry = MagicMock()
    config.ltl_monitor = MagicMock()
    config.llm_rate = MagicMock()
    config.sub_task = MagicMock()
    config.persistent_tasks = MagicMock()
    config.channels = MagicMock()
    config.medical = MagicMock()
    config.medical.enabled = False
    config.counselor = MagicMock()
    config.utility_agents = MagicMock()
    config.security = MagicMock()
    config.auth = MagicMock()
    config.auth.crew_scope_token = ""
    config.behavioral_metrics = MagicMock()
    config.cognitive_journal = MagicMock()
    config.event_log = MagicMock()
    config.working_memory = MagicMock()
    config.anomaly_window = MagicMock()
    config.circuit_breaker = MagicMock()
    config.degradation = MagicMock()
    config.onboarding = MagicMock()
    config.holodeck_scenarios = MagicMock()
    config.holodeck_scenarios.enabled = False
    config.team_simulations = MagicMock()
    config.team_simulations.enabled = False
    config.holodeck_birth_chamber = MagicMock()
    config.holodeck_birth_chamber.enabled = False
    return config


@pytest.fixture
def config_m365_enabled():
    """Config with M365 enabled."""
    config = MagicMock(spec=SystemConfig)
    config.m365 = M365Config(enabled=True, client_id="test-client-id")
    # Copy all other config from disabled version
    config.system = MagicMock()
    config.system.version = "0.4.0"
    config.pools = MagicMock()
    config.mesh = MagicMock()
    config.consensus = MagicMock()
    config.cognitive = MagicMock()
    config.cognitive.llm_base_url = "http://localhost:8080/v1"
    config.cognitive.llm_api_key = ""
    config.cognitive.working_memory_token_budget = 4000
    config.cognitive.decomposition_timeout_seconds = 30.0
    config.memory = MagicMock()
    config.dreaming = MagicMock()
    config.knowledge = MagicMock()
    config.records = MagicMock()
    config.telemetry = MagicMock()
    config.federation = MagicMock()
    config.federation.enabled = False
    config.self_mod = MagicMock()
    config.qa = MagicMock()
    config.operational_status = MagicMock()
    config.trust_dampening = MagicMock()
    config.avatar_telemetry = MagicMock()
    config.avatar_telemetry.enabled = False
    config.attachments = MagicMock()
    config.attachments.image_budget_path = None
    config.avatars = MagicMock()
    config.avatars.enabled = False
    config.swe_specialists = MagicMock()
    config.swe_specialists.enabled = False
    config.mcp_app_host = MagicMock()
    config.mcp_app_host.enabled = False
    config.dm_sanity_gate = MagicMock()
    config.dm_targeted_lookup = MagicMock()
    config.perception = MagicMock()
    config.online_stt_enabled = False
    config.wake_word = MagicMock()
    config.wake_word.wake_word_trainer_enabled = False
    config.credential_vault = MagicMock()
    config.spatial_explorer = MagicMock()
    config.knowledge_browser = MagicMock()
    config.extensions = MagicMock()
    config.temporal = MagicMock()
    config.dream_wm = MagicMock()
    config.scaling = MagicMock()
    config.backend_call = MagicMock()
    config.pre_flight = MagicMock()
    config.post_budget_telemetry = MagicMock()
    config.llm_rate = MagicMock()
    config.sub_task = MagicMock()
    config.persistent_tasks = MagicMock()
    config.channels = MagicMock()
    config.medical = MagicMock()
    config.medical.enabled = False
    config.counselor = MagicMock()
    config.utility_agents = MagicMock()
    config.security = MagicMock()
    config.auth = MagicMock()
    config.auth.crew_scope_token = ""
    config.behavioral_metrics = MagicMock()
    config.cognitive_journal = MagicMock()
    config.event_log = MagicMock()
    config.working_memory = MagicMock()
    config.anomaly_window = MagicMock()
    config.circuit_breaker = MagicMock()
    config.degradation = MagicMock()
    config.onboarding = MagicMock()
    config.holodeck_scenarios = MagicMock()
    config.holodeck_scenarios.enabled = False
    config.team_simulations = MagicMock()
    config.team_simulations.enabled = False
    config.holodeck_birth_chamber = MagicMock()
    config.holodeck_birth_chamber.enabled = False
    return config


def test_config_m365_disabled(config_m365_disabled):
    """Test config loading with M365 disabled."""
    assert config_m365_disabled.m365.enabled is False
    assert config_m365_disabled.m365.client_id is None


def test_config_m365_enabled(config_m365_enabled):
    """Test config loading with M365 enabled."""
    assert config_m365_enabled.m365.enabled is True
    assert config_m365_enabled.m365.client_id == "test-client-id"
