"""AD-1270e2 batch 3 -- the ``experience`` batch left ``config.py`` unchanged.

Sixteen leaf models -- the approval inbox, group chat, the desktop/workstation
and knowledge-browser surfaces, the camera/screen streams, voice and avatar
(TTS, lip-sync, wake word, baseline VRMs) and the Discord/Slack/webhook channel
adapters -- now live in ``probos.config_models.experience`` and are re-exported
from ``probos.config``. The property under test is that no consumer can tell:
same class object, same qualname, same MRO, same ordered fields, same dumped
defaults. A name-only check would pass a wrapper or a re-declared copy, so the
identity assertions compare ``is``.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` at
authoring time -- the class text *before* the move, evaluated on its own. Had it
been derived from the moved module the assertion would compare the code against
itself and pass for any value.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.experience as config_experience
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_EXPERIENCE_SOURCE = (
    _REPO_ROOT / "src" / "probos" / "config_models" / "experience.py"
)

#: The batch, named once. Every parametrised case walks exactly these sixteen.
MOVED_MODELS: tuple[str, ...] = (
    "ApprovalInboxConfig",
    "BaselineVRMManifest",
    "CameraStreamConfig",
    "DesktopConfig",
    "DiscordConfig",
    "GroupChatConfig",
    "KnowledgeBrowserConfig",
    "LipSyncConfig",
    "OnboardingConfig",
    "ScreenStreamConfig",
    "SlackConfig",
    "SpatialExplorerConfig",
    "TTSConfig",
    "WakeWordConfig",
    "WebhookConfig",
    "WorkstationsConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``, so a dump assertion
#: names both ends. Six of the sixteen hang one level down (``channels.*``,
#: ``perception.*``, ``avatars.*``) rather than off the root.
MODEL_TO_PATH: dict[str, str] = {
    "ApprovalInboxConfig": "approval_inbox",
    "BaselineVRMManifest": "avatars.baseline_vrms",
    "CameraStreamConfig": "perception.camera",
    "DesktopConfig": "desktop",
    "DiscordConfig": "channels.discord",
    "GroupChatConfig": "group_chat",
    "KnowledgeBrowserConfig": "knowledge_browser",
    "LipSyncConfig": "lipsync",
    "OnboardingConfig": "onboarding",
    "ScreenStreamConfig": "perception.screen",
    "SlackConfig": "channels.slack",
    "SpatialExplorerConfig": "spatial_explorer",
    "TTSConfig": "tts",
    "WakeWordConfig": "wake_word",
    "WebhookConfig": "channels.webhook",
    "WorkstationsConfig": "workstations",
}

#: Pre-move ``model_dump(mode="json")`` for each moved model, measured against
#: ``HEAD``'s ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {
    'ApprovalInboxConfig': {   'enabled': False,
                               'standing_rules_enabled': False,
                               'standing_rule_max_ttl_hours': 168,
                               'standing_rule_default_ttl_hours': 24,
                               'max_pending_per_agent': 20,
                               'pending_ask_ttl_hours': 72,
                               'work_permits_enabled': False,
                               'work_permit_default_ttl_seconds': 3600.0,
                               'work_permit_max_tier_ceiling': 2},
    'BaselineVRMManifest': {   'ensign': '',
                               'lieutenant': '',
                               'commander': '',
                               'senior': ''},
    'CameraStreamConfig': {   'enabled': False,
                              'default_fps': 1,
                              'frame_jpeg_quality': 0.6,
                              'frame_max_dimension': 512},
    'DesktopConfig': {   'enabled': False,
                         'tray_autostart': True,
                         'hotkey': 'ctrl+shift+space',
                         'notification_timeout_sec': 5,
                         'quiet_hours_start': '19:00',
                         'quiet_hours_end': '08:00',
                         'lock_file': '~/.probos/yeo.lock',
                         'autostart_enabled': False},
    'DiscordConfig': {   'enabled': False,
                         'token': '',
                         'allowed_channel_ids': [],
                         'allowed_user_ids': [],
                         'command_prefix': '!',
                         'mention_required': False,
                         'scout_channel_id': 0},
    'GroupChatConfig': {   'max_speakers_per_turn': 0,
                           'convergence_enabled': True,
                           'convergence_similarity_threshold': 0.6,
                           'convergence_min_messages': 4,
                           'convergence_min_agents': 2,
                           'weight_mention': 0.4,
                           'weight_recency': 0.25,
                           'weight_department': 0.25,
                           'weight_trust': 0.1,
                           'weight_exploration': 0.0,
                           'conversation_trust_enabled': False,
                           'conversation_trust_positive_weight': 0.05,
                           'conversation_trust_negative_weight': 0.15,
                           'conversation_trust_max_outcomes': 4,
                           'conversation_trust_correction_observe_enabled': False,
                           'agent_create_cooldown_seconds': 60.0,
                           'agent_create_max_per_window': 5,
                           'agent_create_window_seconds': 3600.0,
                           'auto_task_room_enabled': False,
                           'agent_reactivity_enabled': False,
                           'max_agent_rounds': 2,
                           'agent_next_speaker_selection_enabled': False,
                           'max_address_extensions': 1,
                           'agent_initiated_kickoff_enabled': False,
                           'escalation_suggestion_enabled': False,
                           'escalation_min_crew': 3,
                           'escalation_min_posts': 6,
                           'broadcast_terminator_enabled': False,
                           'turn_mode_policy_enabled': False,
                           'broadcast_weight_mention': 0.2,
                           'broadcast_weight_recency': 0.15,
                           'broadcast_weight_department': 0.5,
                           'broadcast_weight_trust': 0.1,
                           'scale_aware_facilitation_enabled': False,
                           'facilitation_gate_threshold': 5,
                           'force_facilitation_min': 0},
    'KnowledgeBrowserConfig': {   'enabled': False,
                                  'max_graph_nodes': 500,
                                  'max_graph_edges': 1000,
                                  'jaccard_threshold': 0.3,
                                  'max_suggestions_per_entry': 5,
                                  'index_refresh_seconds': 300},
    'LipSyncConfig': {   'enabled': True,
                         'backend': 'heuristic',
                         'binary_path': 'tools/rhubarb/rhubarb',
                         'timeout_seconds': 30.0,
                         'ffmpeg_binary_path': 'tools/ffmpeg/ffmpeg'},
    'OnboardingConfig': {   'enabled': True,
                            'activation_trust_threshold': 0.65,
                            'naming_ceremony': True},
    'ScreenStreamConfig': {'enabled': False, 'default_fps': 1},
    'SlackConfig': {   'enabled': False,
                       'bot_token': '',
                       'signing_secret': '',
                       'allowed_channel_ids': [],
                       'allowed_user_ids': [],
                       'default_thread_ts': True,
                       'channels': [],
                       'poll_interval_s': 8.0,
                       'poll_inbound': True,
                       'api_base': 'https://slack.com/api'},
    'SpatialExplorerConfig': {   'enabled': False,
                                 'max_graph_edges': 500,
                                 'max_graph_nodes': 200,
                                 'spatial_layout_path': ''},
    'TTSConfig': {   'enabled': True,
                     'backend': 'browser',
                     'binary_path': 'tools/piper/piper',
                     'voice_model': 'en_US-amy-medium',
                     'voices_dir': 'tools/piper/voices',
                     'timeout_seconds': 10.0,
                     'noise_scale': 0.85,
                     'length_scale': 1.0,
                     'noise_w': 1.0,
                     'sentence_silence': 0.35,
                     'sentence_pipelining_enabled': False},
    'WakeWordConfig': {   'wake_word_trainer_enabled': False,
                          'custom_model_filename': 'captain.onnx',
                          'retain_training_samples': False,
                          'training_samples_max_count': 200,
                          'training_audio_max_bytes': 1048576},
    'WebhookConfig': {'enabled': False, 'shared_secret': '', 'allowed_channels': []},
    'WorkstationsConfig': {'enabled': False},
}


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _walk(dumped: dict[str, Any], dotted: str) -> Any:
    """Follow a ``MODEL_TO_PATH`` entry into a ``model_dump`` result."""
    node: Any = dumped
    for part in dotted.split("."):
        node = node[part]
    return node


facade = _load("_ad1270e2c_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    document = yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))
    return document["models"]


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_experience, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    """``config_models/__init__`` must not shadow the module with a copy."""
    assert getattr(config_pkg, name) is getattr(config_experience, name)
    assert name in config_pkg.__all__


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_identity_matches_the_e1_baseline(
    name: str, baseline_models: dict[str, dict]
) -> None:
    """Qualname, MRO bases and ordered fields are what e1 froze."""
    stored = baseline_models[name]
    model = getattr(config_facade, name)

    assert model.__qualname__ == stored["qualname"]
    assert [base.__name__ for base in model.__mro__[1:]] == stored["bases"]
    assert list(model.model_fields) == [field["name"] for field in stored["fields"]]


def test_the_literal_consumer_spelling_still_imports() -> None:
    """The existing call sites spell it exactly this way."""
    from probos.config import (  # noqa: F401
        ApprovalInboxConfig,
        BaselineVRMManifest,
        CameraStreamConfig,
        DesktopConfig,
        DiscordConfig,
        GroupChatConfig,
        KnowledgeBrowserConfig,
        LipSyncConfig,
        OnboardingConfig,
        ScreenStreamConfig,
        SlackConfig,
        SpatialExplorerConfig,
        TTSConfig,
        WakeWordConfig,
        WebhookConfig,
        WorkstationsConfig,
    )

    assert ApprovalInboxConfig is config_experience.ApprovalInboxConfig
    assert WorkstationsConfig is config_experience.WorkstationsConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``.

    That is the one predicate this move breaks. If it did, all sixteen would
    reclassify as import leakage and the baseline would demand a regeneration
    that proves nothing.
    """
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.experience"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_system_config_dump_is_unchanged_for_the_moved_model(name: str) -> None:
    """Reached through the real composition path, nested ones included."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    """Empty input: every field falls back to its own default."""
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    """The direct instance, not just the one ``SystemConfig`` composes."""
    model = getattr(config_facade, name)

    assert model().model_dump(mode="json") == EXPECTED_DUMPS[name]


def test_camera_stream_bounds_survived_the_move() -> None:
    """``ge``/``le`` on both ends; a move must not drop either half."""
    assert config_facade.CameraStreamConfig(default_fps=4).default_fps == 4
    with pytest.raises(ValueError):
        config_facade.CameraStreamConfig(default_fps=5)
    with pytest.raises(ValueError):
        config_facade.CameraStreamConfig(default_fps=0)
    assert (
        config_facade.CameraStreamConfig(frame_jpeg_quality=0.2).frame_jpeg_quality
        == 0.2
    )
    with pytest.raises(ValueError):
        config_facade.CameraStreamConfig(frame_jpeg_quality=0.19)


def test_knowledge_browser_bounds_survived_the_move() -> None:
    assert (
        config_facade.KnowledgeBrowserConfig(index_refresh_seconds=10).index_refresh_seconds
        == 10
    )
    with pytest.raises(ValueError):
        config_facade.KnowledgeBrowserConfig(index_refresh_seconds=9)
    with pytest.raises(ValueError):
        config_facade.KnowledgeBrowserConfig(jaccard_threshold=1.1)


def test_approval_inbox_exclusive_lower_bound_survived_the_move() -> None:
    """``gt=0.0`` is exclusive -- the one bound ``ge`` would silently widen."""
    assert (
        config_facade.ApprovalInboxConfig(
            work_permit_default_ttl_seconds=0.5
        ).work_permit_default_ttl_seconds
        == 0.5
    )
    with pytest.raises(ValueError):
        config_facade.ApprovalInboxConfig(work_permit_default_ttl_seconds=0.0)
    with pytest.raises(ValueError):
        config_facade.ApprovalInboxConfig(work_permit_max_tier_ceiling=4)


@pytest.mark.parametrize(
    ("model_name", "value"),
    [("TTSConfig", "piper"), ("LipSyncConfig", "rhubarb")],
)
def test_backend_literals_accept_their_declared_alternative(
    model_name: str, value: str
) -> None:
    assert getattr(config_facade, model_name)(backend=value).backend == value


@pytest.mark.parametrize("model_name", ["TTSConfig", "LipSyncConfig"])
def test_backend_literals_still_reject_an_unlisted_value(model_name: str) -> None:
    """``Literal`` is the only type constraint in the voice/avatar pair."""
    with pytest.raises(ValueError):
        getattr(config_facade, model_name)(backend="espeak")


def test_group_chat_validator_accepts_the_asymmetry_boundary() -> None:
    """AD-958c allows equality: negative >= positive, not strictly greater."""
    model = config_facade.GroupChatConfig(
        conversation_trust_positive_weight=0.15,
        conversation_trust_negative_weight=0.15,
    )

    assert model.conversation_trust_negative_weight == 0.15


def test_group_chat_validator_rejects_a_broken_asymmetry() -> None:
    with pytest.raises(ValueError, match="asymmetry"):
        config_facade.GroupChatConfig(conversation_trust_positive_weight=0.2)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("conversation_trust_positive_weight", -0.1, "must be >= 0"),
        ("conversation_trust_max_outcomes", -1, "must be >= 0"),
    ],
)
def test_group_chat_validator_rejects_negative_inputs(
    field_name: str, value: float, message: str
) -> None:
    """The other two branches of the batch's only ``model_validator``."""
    with pytest.raises(ValueError, match=message):
        config_facade.GroupChatConfig(**{field_name: value})


def test_group_chat_field_lower_bound_survived_the_move() -> None:
    assert (
        config_facade.GroupChatConfig(
            facilitation_gate_threshold=2
        ).facilitation_gate_threshold
        == 2
    )
    with pytest.raises(ValueError):
        config_facade.GroupChatConfig(facilitation_gate_threshold=1)


@pytest.mark.parametrize("value", ["not-a-number", None, [1]])
def test_moved_models_still_reject_wrong_types(value: object) -> None:
    """Error path: the move must not have loosened coercion."""
    with pytest.raises(ValueError):
        config_facade.CameraStreamConfig(frame_max_dimension=value)


def test_list_defaults_are_not_shared_between_instances() -> None:
    """``allowed_channel_ids`` is a mutable default; sharing it would leak."""
    first = config_facade.DiscordConfig()
    second = config_facade.DiscordConfig()

    assert first.allowed_channel_ids is not second.allowed_channel_ids

    first.allowed_channel_ids.append(1)

    assert second.allowed_channel_ids == []


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.group_chat is not second.group_chat
    assert first.channels.discord is not second.channels.discord

    first.group_chat.convergence_enabled = not first.group_chat.convergence_enabled

    assert (
        second.group_chat.convergence_enabled
        == EXPECTED_DUMPS["GroupChatConfig"]["convergence_enabled"]
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_experience_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_EXPERIENCE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "probos.config" not in imported
    assert not any(name.startswith("probos.config.") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    """A re-export beside a surviving definition would shadow silently."""
    tree = ast.parse(
        (_REPO_ROOT / "src" / "probos" / "config.py").read_text(encoding="utf-8")
    )
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_no_name_is_defined_in_more_than_one_domain_module() -> None:
    """Three batches now share one namespace; a collision would shadow one."""
    owners: dict[str, list[str]] = {}
    for module in ("core", "cognition", "experience"):
        source = (
            _REPO_ROOT / "src" / "probos" / "config_models" / f"{module}.py"
        ).read_text(encoding="utf-8")
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef):
                owners.setdefault(node.name, []).append(module)

    assert {name: mods for name, mods in owners.items() if len(mods) > 1} == {}


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_an_experience_model_change() -> None:
    """A model change must still select the full suite."""
    selector = _load("_ad1270e2c_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/experience.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    """The widened scan must reach every file in the package, not just core."""
    profiles = _load(
        "_ad1270e2c_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )
    package = _REPO_ROOT / "src" / "probos"

    scanned = [path.name for path in profiles._env_scan_paths(package)]

    assert "config.py" in scanned
    assert "experience.py" in scanned
    assert profiles.env_reads_reaching_defaults(package)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
